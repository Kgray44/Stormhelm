from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

from stormhelm.config.loader import load_config
from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import build_execution_report
from stormhelm.core.api.app import create_app
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.shared.result import ToolResult

from .feature_audit import build_feature_audit
from .feature_audit import should_score_case
from .models import AssertionOutcome
from .models import CommandEvalCase
from .models import CommandEvalResult
from .models import CoreObservation
from .models import command_eval_result_from_dict
from .models import json_ready


PAYLOAD_GUARDRAIL_FAIL_BYTES = 5_000_000


TOOL_ROUTE_FAMILY = {
    "active_apps": "app_control",
    "activity_summary": "watch_runtime",
    "app_control": "app_control",
    "browser_context": "watch_runtime",
    "clock": "time",
    "context_action": "context_action",
    "control_capabilities": "system_control",
    "deck_open_file": "file",
    "deck_open_url": "browser_destination",
    "desktop_search": "desktop_search",
    "echo": "development",
    "external_open_file": "file",
    "external_open_url": "browser_destination",
    "file_operation": "file_operation",
    "file_reader": "file",
    "location_status": "location",
    "machine_status": "machine",
    "maintenance_action": "maintenance",
    "network_diagnosis": "network",
    "network_status": "network",
    "network_throughput": "network",
    "notes_write": "notes",
    "power_diagnosis": "power",
    "power_projection": "power",
    "power_status": "power",
    "recent_files": "machine",
    "repair_action": "software_recovery",
    "resource_diagnosis": "resources",
    "resource_status": "resources",
    "routine_execute": "routine",
    "routine_save": "routine",
    "save_location": "location",
    "saved_locations": "location",
    "shell_command": "terminal",
    "storage_diagnosis": "storage",
    "storage_status": "storage",
    "system_control": "system_control",
    "system_info": "machine",
    "trusted_hook_execute": "routine",
    "trusted_hook_register": "routine",
    "weather_current": "weather",
    "window_control": "window_control",
    "window_status": "window_control",
    "workflow_execute": "workflow",
    "workspace_archive": "workspace_operations",
    "workspace_assemble": "workspace_operations",
    "workspace_clear": "workspace_operations",
    "workspace_list": "workspace_operations",
    "workspace_next_steps": "task_continuity",
    "workspace_rename": "workspace_operations",
    "workspace_restore": "workspace_operations",
    "workspace_save": "workspace_operations",
    "workspace_tag": "workspace_operations",
    "workspace_where_left_off": "task_continuity",
}

ROUTE_SUBSYSTEM = {
    "app_control": "system",
    "browser_destination": "browser",
    "calculations": "calculations",
    "context_action": "context",
    "context_clarification": "context",
    "desktop_search": "workflow",
    "development": "development",
    "discord_relay": "discord_relay",
    "file": "files",
    "file_operation": "files",
    "generic_provider": "provider",
    "location": "location",
    "machine": "system",
    "maintenance": "maintenance",
    "network": "system",
    "notes": "workspace",
    "power": "system",
    "resources": "system",
    "routine": "routine",
    "screen_awareness": "screen_awareness",
    "software_control": "software_control",
    "software_recovery": "software_recovery",
    "storage": "system",
    "system_control": "system",
    "task_continuity": "workspace",
    "terminal": "terminal",
    "time": "system",
    "trust_approvals": "trust",
    "unsupported": "none",
    "watch_runtime": "operations",
    "weather": "weather",
    "window_control": "system",
    "workflow": "workflow",
    "workspace_operations": "workspace",
}

TOOL_SUBSYSTEM = {
    "activity_summary": "operations",
    "browser_context": "context",
    "shell_command": "terminal",
}


class DryRunToolExecutor:
    """Validates route-selected tool calls but suppresses their external or mutating effects."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(self, tool_name: str, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        started = perf_counter()
        subspans: dict[str, float] = _default_tool_subspans(tool_name)
        try:
            lookup_started = perf_counter()
            tool = self.registry.get(tool_name)
            _add_tool_subspan(subspans, _tool_span_name(tool_name, "lookup"), lookup_started)
            if not context.config.tools.enabled.is_enabled(tool.name):
                return ToolResult(
                    success=False,
                    summary=f"Dry-run blocked: tool '{tool.name}' is disabled in configuration. No external action was performed.",
                    error="tool_disabled",
                    data={
                        "dry_run": True,
                        "tool_name": tool.name,
                        "disabled": True,
                        "dry_run_executor_ms": round((perf_counter() - started) * 1000, 3),
                        "route_handler_subspans": subspans,
                    },
                )
            dto_started = perf_counter()
            validated_arguments = tool.validate(dict(arguments))
            assessment = tool.adapter_route_assessment(validated_arguments)
            _add_tool_subspan(subspans, _tool_span_name(tool_name, "dto_build"), dto_started)
            if assessment.contract_required and not assessment.healthy:
                return ToolResult(
                    success=False,
                    summary=(
                        f"Dry-run blocked: {tool.display_name} is not valid contract-backed adapter work. "
                        "No external action was performed."
                    ),
                    error="adapter_contract_blocked",
                    data={
                        "dry_run": True,
                        "adapter_contract_status": assessment.to_dict(),
                        "tool_name": tool.name,
                        "dry_run_executor_ms": round((perf_counter() - started) * 1000, 3),
                        "route_handler_subspans": subspans,
                    },
                )
            contract = assessment.selected_contract
            response_started = perf_counter()
            execution = (
                build_execution_report(
                    contract,
                    success=True,
                    observed_outcome=ClaimOutcome.PREVIEW,
                    evidence=["Dry-run harness validated the route and suppressed execution."],
                    verification_observed="dry_run",
                ).to_dict()
                if contract is not None
                else {
                    "adapter_id": "",
                    "success": True,
                    "claim_ceiling": "preview",
                    "approval_required": False,
                    "preview_required": False,
                    "rollback_available": False,
                    "evidence": ["Dry-run harness validated the tool call and suppressed execution."],
                    "verification_observed": "dry_run",
                    "failure_kind": None,
                }
            )
            context.events.publish(
                event_family="tool",
                event_type="tool.execution_dry_run",
                severity="info",
                subsystem="command_eval",
                subject=context.job_id,
                visibility_scope="watch_surface",
                retention_class="operator_relevant",
                provenance={"channel": "command_eval", "kind": "dry_run"},
                message=f"Dry-run validated tool '{tool.name}' without executing it.",
                payload={"job_id": context.job_id, "tool_name": tool.name, "arguments": validated_arguments},
            )
            return ToolResult(
                success=True,
                summary=(
                    f"Dry-run only: would execute {tool.display_name}{_argument_preview(validated_arguments)}. "
                    "No external action was performed."
                ),
                data={
                    "dry_run": True,
                    "tool_name": tool.name,
                    "display_name": tool.display_name,
                    "classification": tool.classification.value,
                    "execution_mode": tool.execution_mode.value,
                    "validated_arguments": validated_arguments,
                    "adapter_contract_status": assessment.to_dict(),
                    "approval_required": bool(contract and contract.approval.required),
                    "preview_required": bool(contract and contract.approval.preview_required),
                    "dry_run_executor_ms": round((perf_counter() - started) * 1000, 3),
                    "route_handler_subspans": {
                        **subspans,
                        _tool_span_name(tool_name, "response_build"): round((perf_counter() - response_started) * 1000, 3),
                    },
                },
                adapter_contract=contract.to_dict() if contract is not None else {},
                adapter_execution=execution,
            )
        except Exception as error:
            return ToolResult(
                success=False,
                summary=f"Dry-run failed before '{tool_name}' could be validated. No external action was performed.",
                error=str(error),
                data={
                    "dry_run": True,
                    "tool_name": tool_name,
                    "dry_run_executor_ms": round((perf_counter() - started) * 1000, 3),
                    "route_handler_subspans": subspans,
                },
            )

    def shutdown(self) -> None:
        return None


def _default_tool_subspans(tool_name: str) -> dict[str, float]:
    if tool_name in {"routine_save", "routine_execute", "trusted_hook_execute", "trusted_hook_register"}:
        return {
            "routine_lookup_ms": 0.0,
            "routine_persistence_read_ms": 0.0,
            "routine_persistence_write_ms": 0.0,
            "routine_job_create_ms": 0.0,
            "routine_job_wait_ms": 0.0,
            "routine_event_emit_ms": 0.0,
            "routine_dto_build_ms": 0.0,
            "routine_response_build_ms": 0.0,
            "routine_background_task_drain_ms": 0.0,
        }
    return {}


def _tool_span_name(tool_name: str, span_kind: str) -> str:
    if tool_name in {"routine_save", "routine_execute", "trusted_hook_execute", "trusted_hook_register"}:
        return f"routine_{span_kind}_ms"
    return f"tool_{span_kind}_ms"


def _add_tool_subspan(subspans: dict[str, float], key: str, started_at: float) -> None:
    if not subspans and not key.startswith("routine_"):
        return
    subspans[key] = round(float(subspans.get(key, 0.0)) + (perf_counter() - started_at) * 1000, 3)


class CommandUsabilityHarness:
    def __init__(
        self,
        *,
        output_dir: Path,
        project_root: Path | None = None,
        per_test_timeout_seconds: float = 60.0,
        run_id: str | None = None,
        history_strategy: str = "isolated_session",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.project_root = (project_root or Path.cwd()).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.per_test_timeout_seconds = min(max(float(per_test_timeout_seconds), 0.1), 60.0)
        self.run_id = run_id or uuid4().hex[:12]
        self.history_strategy = history_strategy
        self._last_artifact_flush_ms = 0.0
        self.provider_audit_path = (self.output_dir / "provider_audit.jsonl").resolve()

    def run(
        self,
        cases: list[CommandEvalCase],
        *,
        results_name: str = "focused_results.jsonl",
        resume: bool = False,
    ) -> list[CommandEvalResult]:
        results_path = self.output_dir / results_name
        _reset_provider_audit(self.provider_audit_path, resume=resume)
        provider_env = _provider_audit_env(self.provider_audit_path)
        previous_provider_env = {key: os.environ.get(key) for key in provider_env}
        os.environ.update(provider_env)
        existing_results = self._load_existing_results(results_path) if resume else []
        completed_ids = {result.case.case_id for result in existing_results}
        pending_cases = [case for case in cases if case.case_id not in completed_ids]
        feature_audit = build_feature_audit(cases)
        config = load_config(
            project_root=self.project_root,
            env={
                "STORMHELM_DATA_DIR": str(self.output_dir / "runtime"),
                "STORMHELM_OPENAI_ENABLED": "false",
                **provider_env,
                "STORMHELM_HARDWARE_TELEMETRY_ENABLED": "false",
                "STORMHELM_SCREEN_AWARENESS_ACTION_POLICY_MODE": "observe_only",
                "STORMHELM_MAX_CONCURRENT_JOBS": "4",
                "STORMHELM_DEFAULT_JOB_TIMEOUT_SECONDS": "2",
            },
        )
        config.concurrency.history_limit = max(config.concurrency.history_limit, len(cases) * 3)
        config.event_stream.retention_capacity = max(config.event_stream.retention_capacity, len(cases) * 8)
        try:
            return asyncio.run(
                self._run_async(
                    config=config,
                    cases=cases,
                    pending_cases=pending_cases,
                    existing_results=existing_results,
                    results_name=results_name,
                    results_path=results_path,
                    resume=resume,
                    feature_audit=feature_audit,
                )
            )
        finally:
            _restore_provider_audit_env(previous_provider_env)

    async def _run_async(
        self,
        *,
        config: Any,
        cases: list[CommandEvalCase],
        pending_cases: list[CommandEvalCase],
        existing_results: list[CommandEvalResult],
        results_name: str,
        results_path: Path,
        resume: bool,
        feature_audit: dict[str, Any],
    ) -> list[CommandEvalResult]:
        app = create_app(config)
        container = app.state.container
        dry_run_executor = DryRunToolExecutor(container.tool_registry)
        container.tool_executor = dry_run_executor
        container.jobs.executor = dry_run_executor
        container.network_monitor = None

        results: list[CommandEvalResult] = list(existing_results)
        cursor = 0
        self._write_progress_checkpoint(
            results_name,
            total=len(cases),
            completed=len(results),
            skipped=len(existing_results),
            last_case_id=results[-1].case.case_id if results else "",
            done=not pending_cases,
        )
        file_mode = "a" if resume and results_path.exists() else "w"
        await container.start()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                with results_path.open(file_mode, encoding="utf-8") as handle:
                    for case in pending_cases:
                        case_index = cases.index(case)
                        result, cursor = await self._run_one_case(
                            client=client,
                            container=container,
                            case=case,
                            case_index=case_index,
                            cursor=cursor,
                            feature_audit=feature_audit,
                        )
                        result = replace(result, artifact_flush_ms=self._last_artifact_flush_ms)
                        encoded_result = json.dumps(result.to_dict(), sort_keys=True, default=str) + "\n"
                        artifact_started = perf_counter()
                        handle.write(encoded_result)
                        handle.flush()
                        artifact_flush_ms = round((perf_counter() - artifact_started) * 1000, 3)
                        self._last_artifact_flush_ms = artifact_flush_ms
                        result = replace(result, artifact_flush_ms=artifact_flush_ms)
                        results.append(result)
                        self._write_progress_checkpoint(
                            results_name,
                            total=len(cases),
                            completed=len(results),
                            skipped=len(existing_results),
                            last_case_id=case.case_id,
                            done=False,
                        )
        finally:
            await container.stop()
        self._write_progress_checkpoint(
            results_name,
            total=len(cases),
            completed=len(results),
            skipped=len(existing_results),
            last_case_id=results[-1].case.case_id if results else "",
            done=True,
        )
        self._rewrite_completed_results(results_path, results)
        return results

    async def _run_one_case(
        self,
        *,
        client: httpx.AsyncClient,
        container: Any,
        case: CommandEvalCase,
        case_index: int,
        cursor: int,
        feature_audit: dict[str, Any],
    ) -> tuple[CommandEvalResult, int]:
        session_id = self._session_id(case, case_index)
        request_payload = case.payload()
        request_payload["session_id"] = session_id
        if case.active_request_state:
            container.assistant.session_state.set_active_request_state(session_id, case.active_request_state)
        audit_start = _provider_audit_line_count(self.provider_audit_path)
        start = perf_counter()
        try:
            http_started = perf_counter()
            response = await asyncio.wait_for(
                client.post("/chat/send", json=request_payload),
                timeout=self.per_test_timeout_seconds,
            )
            http_boundary_ms = (perf_counter() - http_started) * 1000
            payload = response.json() if response.content else {}
            event_started = perf_counter()
            event_payload = (
                await client.get(
                    "/events",
                    params={"cursor": cursor, "limit": 128, "session_id": session_id},
                )
            ).json()
            event_collection_ms = (perf_counter() - event_started) * 1000
            latency_ms = (perf_counter() - start) * 1000
            next_cursor = int(event_payload.get("cursor") or cursor)
            observation = _build_observation(
                case=case,
                payload=payload,
                latency_ms=latency_ms,
                http_boundary_ms=http_boundary_ms,
                event_collection_ms=event_collection_ms,
                status_code=response.status_code,
                events=tuple(event_payload.get("events") or ()),
                session_id=session_id,
                ai_provider_calls=tuple(_provider_audit_delta(self.provider_audit_path, audit_start)),
            )
        except TimeoutError:
            latency_ms = (perf_counter() - start) * 1000
            http_boundary_ms = latency_ms
            event_started = perf_counter()
            event_payload = (
                await client.get(
                    "/events",
                    params={"cursor": cursor, "limit": 128, "session_id": session_id},
                )
            ).json()
            event_collection_ms = (perf_counter() - event_started) * 1000
            next_cursor = int(event_payload.get("cursor") or cursor)
            observation = CoreObservation(
                case_id=case.case_id,
                input_boundary="POST /chat/send",
                latency_ms=round(latency_ms, 3),
                ui_response=f"Command evaluation timed out after {self.per_test_timeout_seconds:.1f} seconds.",
                session_id=session_id,
                actual_route_family="timeout",
                actual_subsystem="harness",
                result_state="timed_out",
                verification_state="not_applicable",
                events=tuple(event_payload.get("events") or ()),
                ai_provider_calls=tuple(_provider_audit_delta(self.provider_audit_path, audit_start)),
                errors=(f"per_test_timeout_{self.per_test_timeout_seconds:.1f}s",),
                stage_timings_ms={
                    "http_boundary_ms": round(http_boundary_ms, 3),
                    "event_collection_ms": round(event_collection_ms, 3),
                    "total_latency_ms": round(latency_ms + event_collection_ms, 3),
                },
            )
        assertions = _assert_case(case, observation)
        score_in_pass_fail, scoring_note = should_score_case(case, feature_audit)
        failure_reason = _failure_reason(assertions)
        failure_category = _failure_category(case, observation, assertions, score_in_pass_fail=score_in_pass_fail)
        result = CommandEvalResult(
            case=case,
            observation=observation,
            assertions=assertions,
            run_id=self.run_id,
            case_index=case_index,
            history_strategy=self.history_strategy,
            failure_category=failure_category,
            failure_reason=failure_reason,
            score_in_pass_fail=score_in_pass_fail,
            scoring_note=scoring_note,
        )
        return result, next_cursor

    def _session_id(self, case: CommandEvalCase, case_index: int) -> str:
        if self.history_strategy == "isolated_session":
            return f"eval-{self.run_id}-{case_index:04d}-{case.case_id}"
        return case.session_id

    def _load_existing_results(self, path: Path) -> list[CommandEvalResult]:
        if not path.exists():
            return []
        results: list[CommandEvalResult] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append(command_eval_result_from_dict(json.loads(line)))
                except Exception:
                    continue
        return results

    def _write_progress_checkpoint(
        self,
        name: str,
        *,
        total: int,
        completed: int,
        skipped: int,
        last_case_id: str,
        done: bool,
    ) -> None:
        checkpoint_path = self.output_dir / f"{Path(name).stem}.checkpoint.json"
        checkpoint_path.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "history_strategy": self.history_strategy,
                    "per_test_timeout_seconds": self.per_test_timeout_seconds,
                    "results_file": name,
                    "total": total,
                    "completed": completed,
                    "skipped_existing": skipped,
                    "remaining": max(0, total - completed),
                    "last_case_id": last_case_id,
                    "done": done,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _rewrite_completed_results(self, path: Path, results: list[CommandEvalResult]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for result in results:
                handle.write(json.dumps(result.to_dict(), sort_keys=True, default=str) + "\n")


class ProcessIsolatedCommandUsabilityHarness(CommandUsabilityHarness):
    """Runs each command request against a killable child Stormhelm Core process."""

    def __init__(
        self,
        *,
        output_dir: Path,
        project_root: Path | None = None,
        per_test_timeout_seconds: float = 60.0,
        run_id: str | None = None,
        history_strategy: str = "isolated_session",
        child_script: Path | None = None,
        server_startup_timeout_seconds: float = 20.0,
        synthetic_block_seconds: float = 0.0,
        process_scope: str = "per_case",
        runtime_seed_dir: Path | None = None,
    ) -> None:
        super().__init__(
            output_dir=output_dir,
            project_root=project_root,
            per_test_timeout_seconds=per_test_timeout_seconds,
            run_id=run_id,
            history_strategy=history_strategy,
        )
        self.child_script = child_script or self.project_root / "scripts" / "serve_command_eval_core.py"
        self.server_startup_timeout_seconds = max(1.0, float(server_startup_timeout_seconds))
        self.synthetic_block_seconds = max(0.0, float(synthetic_block_seconds))
        self.process_scope = process_scope if process_scope in {"per_case", "per_run"} else "per_case"
        self.runtime_seed_dir = runtime_seed_dir

    def run(
        self,
        cases: list[CommandEvalCase],
        *,
        results_name: str = "focused_results.jsonl",
        resume: bool = False,
    ) -> list[CommandEvalResult]:
        results_path = self.output_dir / results_name
        _reset_provider_audit(self.provider_audit_path, resume=resume)
        existing_results = self._load_existing_results(results_path) if resume else []
        completed_ids = {result.case.case_id for result in existing_results}
        pending_cases = [case for case in cases if case.case_id not in completed_ids]
        feature_audit = build_feature_audit(cases)

        results: list[CommandEvalResult] = list(existing_results)
        self._write_progress_checkpoint(
            results_name,
            total=len(cases),
            completed=len(results),
            skipped=len(existing_results),
            last_case_id=results[-1].case.case_id if results else "",
            done=not pending_cases,
        )
        file_mode = "a" if resume and results_path.exists() else "w"
        shared_child: _ChildProcess | None = None
        shared_port = 0
        shared_runtime_dir: Path | None = None
        if self.process_scope == "per_run" and pending_cases:
            shared_runtime_dir = self.output_dir / "runtime" / f"run-{uuid4().hex[:8]}"
            self._prepare_runtime_dir(shared_runtime_dir)
            shared_port = _free_tcp_port()
            shared_child = self._start_child_process(port=shared_port, runtime_dir=shared_runtime_dir)
            if not _wait_for_child_ready(shared_port, shared_child, timeout_seconds=self.server_startup_timeout_seconds):
                _kill_process_tree(shared_child)
                shared_child = None
        with results_path.open(file_mode, encoding="utf-8") as handle:
            try:
                for case in pending_cases:
                    case_index = cases.index(case)
                    if self.process_scope == "per_run" and shared_child is not None:
                        result = self._run_one_case_with_child(
                            case=case,
                            case_index=case_index,
                            feature_audit=feature_audit,
                            checkpoint_path=self.output_dir / f"{Path(results_name).stem}.checkpoint.json",
                            child=shared_child,
                            port=shared_port,
                        )
                        if result.observation.process_killed and pending_cases[-1] is not case:
                            shared_runtime_dir = self.output_dir / "runtime" / f"run-{uuid4().hex[:8]}"
                            self._prepare_runtime_dir(shared_runtime_dir)
                            shared_port = _free_tcp_port()
                            shared_child = self._start_child_process(port=shared_port, runtime_dir=shared_runtime_dir)
                            if not _wait_for_child_ready(shared_port, shared_child, timeout_seconds=self.server_startup_timeout_seconds):
                                _kill_process_tree(shared_child)
                                shared_child = None
                    else:
                        result = self._run_one_case_process(
                            case=case,
                            case_index=case_index,
                            feature_audit=feature_audit,
                            checkpoint_path=self.output_dir / f"{Path(results_name).stem}.checkpoint.json",
                        )
                    result = replace(result, artifact_flush_ms=self._last_artifact_flush_ms)
                    encoded_result = json.dumps(result.to_dict(), sort_keys=True, default=str) + "\n"
                    artifact_started = perf_counter()
                    handle.write(encoded_result)
                    handle.flush()
                    artifact_flush_ms = round((perf_counter() - artifact_started) * 1000, 3)
                    self._last_artifact_flush_ms = artifact_flush_ms
                    result = replace(result, artifact_flush_ms=artifact_flush_ms)
                    results.append(result)
                    self._write_progress_checkpoint(
                        results_name,
                        total=len(cases),
                        completed=len(results),
                        skipped=len(existing_results),
                        last_case_id=case.case_id,
                        done=False,
                    )
            finally:
                if shared_child is not None:
                    _terminate_process_tree(shared_child)
        self._write_progress_checkpoint(
            results_name,
            total=len(cases),
            completed=len(results),
            skipped=len(existing_results),
            last_case_id=results[-1].case.case_id if results else "",
            done=True,
        )
        self._rewrite_completed_results(results_path, results)
        return results

    def _run_one_case_process(
        self,
        *,
        case: CommandEvalCase,
        case_index: int,
        feature_audit: dict[str, Any],
        checkpoint_path: Path,
    ) -> CommandEvalResult:
        session_id = self._session_id(case, case_index)
        request_payload = case.payload()
        request_payload["session_id"] = session_id
        runtime_dir = self.output_dir / "runtime" / f"{case_index:04d}-{uuid4().hex[:10]}"
        self._prepare_runtime_dir(runtime_dir)
        port = _free_tcp_port()
        child = self._start_child_process(port=port, runtime_dir=runtime_dir)
        try:
            if not _wait_for_child_ready(port, child, timeout_seconds=self.server_startup_timeout_seconds):
                _kill_process_tree(child)
                observation = self._hard_timeout_observation(
                    case=case,
                    session_id=session_id,
                    elapsed_ms=self.server_startup_timeout_seconds * 1000,
                    child=child,
                    checkpoint_path=checkpoint_path,
                    reason="core_child_startup_timeout",
                )
            else:
                observation = self._send_request_with_hard_timeout(
                    case=case,
                    session_id=session_id,
                    request_payload=request_payload,
                    port=port,
                    child=child,
                    checkpoint_path=checkpoint_path,
                )
        finally:
            _terminate_process_tree(child)

        assertions = _assert_case(case, observation)
        score_in_pass_fail, scoring_note = should_score_case(case, feature_audit)
        failure_reason = _failure_reason(assertions)
        failure_category = _failure_category(case, observation, assertions, score_in_pass_fail=score_in_pass_fail)
        return CommandEvalResult(
            case=case,
            observation=observation,
            assertions=assertions,
            run_id=self.run_id,
            case_index=case_index,
            history_strategy=self.history_strategy,
            failure_category=failure_category,
            failure_reason=failure_reason,
            score_in_pass_fail=score_in_pass_fail,
            scoring_note=scoring_note,
        )

    def _run_one_case_with_child(
        self,
        *,
        case: CommandEvalCase,
        case_index: int,
        feature_audit: dict[str, Any],
        checkpoint_path: Path,
        child: "_ChildProcess",
        port: int,
    ) -> CommandEvalResult:
        session_id = self._session_id(case, case_index)
        request_payload = case.payload()
        request_payload["session_id"] = session_id
        observation = self._send_request_with_hard_timeout(
            case=case,
            session_id=session_id,
            request_payload=request_payload,
            port=port,
            child=child,
            checkpoint_path=checkpoint_path,
        )
        assertions = _assert_case(case, observation)
        score_in_pass_fail, scoring_note = should_score_case(case, feature_audit)
        failure_reason = _failure_reason(assertions)
        failure_category = _failure_category(case, observation, assertions, score_in_pass_fail=score_in_pass_fail)
        return CommandEvalResult(
            case=case,
            observation=observation,
            assertions=assertions,
            run_id=self.run_id,
            case_index=case_index,
            history_strategy=self.history_strategy,
            failure_category=failure_category,
            failure_reason=failure_reason,
            score_in_pass_fail=score_in_pass_fail,
            scoring_note=scoring_note,
        )

    def _send_request_with_hard_timeout(
        self,
        *,
        case: CommandEvalCase,
        session_id: str,
        request_payload: dict[str, Any],
        port: int,
        child: "_ChildProcess",
        checkpoint_path: Path,
    ) -> CoreObservation:
        started = perf_counter()
        audit_start = _provider_audit_line_count(self.provider_audit_path)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            _post_case_over_http,
            port,
            request_payload,
            self.per_test_timeout_seconds,
            case.active_request_state,
        )
        try:
            request_result = future.result(timeout=self.per_test_timeout_seconds)
        except concurrent.futures.TimeoutError:
            elapsed_ms = round((perf_counter() - started) * 1000, 3)
            _kill_process_tree(child)
            future.cancel()
            observation = self._hard_timeout_observation(
                case=case,
                session_id=session_id,
                elapsed_ms=elapsed_ms,
                child=child,
                checkpoint_path=checkpoint_path,
                reason="hard_timeout",
                ai_provider_calls=tuple(_provider_audit_delta(self.provider_audit_path, audit_start)),
            )
        except Exception as error:
            elapsed_ms = round((perf_counter() - started) * 1000, 3)
            observation = CoreObservation(
                case_id=case.case_id,
                input_boundary="real HTTP POST /chat/send",
                latency_ms=elapsed_ms,
                ui_response=f"Process-isolated evaluator request failed: {error}",
                session_id=session_id,
                status="request_error",
                elapsed_ms=elapsed_ms,
                child_pid=child.process.pid,
                stdout_tail=child.stdout.tail(),
                stderr_tail=child.stderr.tail(),
                checkpoint_path=str(checkpoint_path),
                actual_route_family="harness_error",
                actual_subsystem="harness",
                result_state="request_error",
                verification_state="not_applicable",
                errors=(str(error),),
                stage_timings_ms={"http_boundary_ms": elapsed_ms, "total_latency_ms": elapsed_ms},
                ai_provider_calls=tuple(_provider_audit_delta(self.provider_audit_path, audit_start)),
            )
        else:
            observation = _build_observation(
                case=case,
                payload=request_result["payload"],
                snapshot=request_result.get("snapshot") if isinstance(request_result.get("snapshot"), dict) else {},
                latency_ms=request_result["latency_ms"],
                http_boundary_ms=request_result["http_boundary_ms"],
                event_collection_ms=request_result["event_collection_ms"],
                status_code=request_result["status_code"],
                events=tuple(request_result.get("events") or ()),
                session_id=session_id,
                input_boundary="real HTTP POST /chat/send",
                response_json_bytes=int(request_result.get("response_json_bytes") or 0),
                stdout_tail=child.stdout.tail(),
                stderr_tail=child.stderr.tail(),
                checkpoint_path=str(checkpoint_path),
                child_pid=child.process.pid,
                ai_provider_calls=tuple(_provider_audit_delta(self.provider_audit_path, audit_start)),
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return observation

    def _hard_timeout_observation(
        self,
        *,
        case: CommandEvalCase,
        session_id: str,
        elapsed_ms: float,
        child: "_ChildProcess",
        checkpoint_path: Path,
        reason: str,
        ai_provider_calls: tuple[dict[str, Any], ...] = (),
    ) -> CoreObservation:
        return CoreObservation(
            case_id=case.case_id,
            input_boundary="real HTTP POST /chat/send",
            latency_ms=round(elapsed_ms, 3),
            ui_response=f"Process-isolated evaluator killed Stormhelm Core after {self.per_test_timeout_seconds:.1f}s.",
            session_id=session_id,
            status="hard_timeout",
            process_killed=True,
            timeout_seconds=self.per_test_timeout_seconds,
            elapsed_ms=round(elapsed_ms, 3),
            child_pid=child.process.pid,
            stdout_tail=child.stdout.tail(),
            stderr_tail=child.stderr.tail(),
            checkpoint_path=str(checkpoint_path),
            actual_route_family="hard_timeout",
            actual_subsystem="harness",
            result_state="hard_timeout",
            verification_state="not_applicable",
            errors=(reason,),
            ai_provider_calls=ai_provider_calls,
            stage_timings_ms={
                "http_boundary_ms": round(elapsed_ms, 3),
                "total_latency_ms": round(elapsed_ms, 3),
            },
        )

    def _start_child_process(self, *, port: int, runtime_dir: Path) -> "_ChildProcess":
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(self.project_root / "src"),
                "STORMHELM_DATA_DIR": str(runtime_dir),
                "STORMHELM_OPENAI_ENABLED": "false",
                **_provider_audit_env(self.provider_audit_path),
                "STORMHELM_HARDWARE_TELEMETRY_ENABLED": "false",
                "STORMHELM_SCREEN_AWARENESS_ACTION_POLICY_MODE": "observe_only",
                "STORMHELM_MAX_CONCURRENT_JOBS": "4",
                "STORMHELM_DEFAULT_JOB_TIMEOUT_SECONDS": "2",
                "STORMHELM_COMMAND_EVAL_DRY_RUN": "true",
                "STORMHELM_COMMAND_EVAL_BLOCK_SECONDS": str(self.synthetic_block_seconds),
            }
        )
        process = subprocess.Popen(
            [
                sys.executable,
                str(self.child_script),
                "--port",
                str(port),
                "--runtime-dir",
                str(runtime_dir),
                "--project-root",
                str(self.project_root),
            ],
            cwd=str(self.project_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        return _ChildProcess(process=process, stdout=_StreamTail(process.stdout), stderr=_StreamTail(process.stderr))

    def _prepare_runtime_dir(self, runtime_dir: Path) -> None:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / "logs").mkdir(parents=True, exist_ok=True)
        (runtime_dir / "state").mkdir(parents=True, exist_ok=True)
        if self.runtime_seed_dir is None:
            return
        seed_dir = self.runtime_seed_dir.resolve()
        if not seed_dir.exists():
            return
        for source_path in seed_dir.rglob("*"):
            relative_path = source_path.relative_to(seed_dir)
            target_path = runtime_dir / relative_path
            if source_path.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)


class _StreamTail:
    def __init__(self, stream: Any, *, max_lines: int = 80) -> None:
        self._lines: list[str] = []
        self._max_lines = max_lines
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._read_stream, args=(stream,), daemon=True)
        self._thread.start()

    def _read_stream(self, stream: Any) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                with self._lock:
                    self._lines.append(str(line).rstrip())
                    if len(self._lines) > self._max_lines:
                        self._lines = self._lines[-self._max_lines :]
        except Exception:
            return

    def tail(self) -> str:
        with self._lock:
            return "\n".join(self._lines[-self._max_lines :])


class _ChildProcess:
    def __init__(self, *, process: subprocess.Popen[str], stdout: _StreamTail, stderr: _StreamTail) -> None:
        self.process = process
        self.stdout = stdout
        self.stderr = stderr


def _post_case_over_http(
    port: int,
    request_payload: dict[str, Any],
    timeout_seconds: float,
    active_request_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=timeout_seconds + 10.0) as client:
        if active_request_state:
            client.post(
                "/__command_eval/session-state",
                json={
                    "session_id": request_payload.get("session_id", "default"),
                    "active_request_state": active_request_state,
                },
            )
        started = perf_counter()
        http_started = perf_counter()
        response = client.post("/chat/send", json=request_payload)
        http_boundary_ms = (perf_counter() - http_started) * 1000
        response_json_bytes = len(response.content or b"")
        payload = response.json() if response.content else {}
        event_started = perf_counter()
        events_response = client.get(
            "/events",
            params={"cursor": 0, "limit": 512, "session_id": request_payload.get("session_id", "default")},
        )
        event_collection_ms = (perf_counter() - event_started) * 1000
        events_payload = events_response.json() if events_response.content else {}
        snapshot_response = client.get(
            "/snapshot",
            params={
                "session_id": request_payload.get("session_id", "default"),
                "event_limit": 0,
                "job_limit": 0,
                "note_limit": 0,
                "history_limit": 0,
            },
        )
        snapshot_payload = snapshot_response.json() if snapshot_response.content else {}
    return {
        "payload": payload,
        "snapshot": snapshot_payload,
        "status_code": response.status_code,
        "events": tuple(events_payload.get("events") or ()),
        "latency_ms": round((perf_counter() - started) * 1000, 3),
        "http_boundary_ms": round(http_boundary_ms, 3),
        "event_collection_ms": round(event_collection_ms, 3),
        "response_json_bytes": response_json_bytes,
    }


def _wait_for_child_ready(port: int, child: _ChildProcess, *, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if child.process.poll() is not None:
            return False
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1.0) as client:
                response = client.get("/health")
                if response.status_code == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _terminate_process_tree(child: _ChildProcess) -> None:
    if child.process.poll() is not None:
        return
    try:
        child.process.terminate()
        child.process.wait(timeout=3)
    except Exception:
        _kill_process_tree(child)


def _kill_process_tree(child: _ChildProcess) -> None:
    if child.process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(child.process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            child.process.wait(timeout=5)
        except Exception:
            return
        return
    try:
        child.process.kill()
        child.process.wait(timeout=5)
    except Exception:
        return


def _safe_path_token(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned[:80] or "case"


def _provider_audit_env(path: Path) -> dict[str, str]:
    return {
        "STORMHELM_COMMAND_EVAL_PROVIDER_AUDIT_PATH": str(path),
        "STORMHELM_COMMAND_EVAL_BLOCK_PROVIDER_CALLS": "true",
        "STORMHELM_COMMAND_EVAL_PROVIDER_ALLOWED": "false",
    }


def _restore_provider_audit_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _reset_provider_audit(path: Path, *, resume: bool) -> None:
    if resume:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _provider_audit_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def _provider_audit_delta(path: Path, start_line: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index < start_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except OSError:
        return []
    return records


def _build_observation(
    *,
    case: CommandEvalCase,
    payload: dict[str, Any],
    latency_ms: float,
    http_boundary_ms: float,
    event_collection_ms: float,
    status_code: int,
    events: tuple[dict[str, Any], ...],
    session_id: str,
    input_boundary: str = "POST /chat/send",
    response_json_bytes: int = 0,
    stdout_tail: str = "",
    stderr_tail: str = "",
    checkpoint_path: str = "",
    child_pid: int = 0,
    ai_provider_calls: tuple[dict[str, Any], ...] = (),
    snapshot: dict[str, Any] | None = None,
) -> CoreObservation:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    assistant_message = payload.get("assistant_message") if isinstance(payload, dict) else {}
    if not isinstance(assistant_message, dict):
        assistant_message = {}
    metadata = assistant_message.get("metadata") if isinstance(assistant_message.get("metadata"), dict) else {}
    route_state = metadata.get("route_state") if isinstance(metadata.get("route_state"), dict) else {}
    planner_debug = metadata.get("planner_debug") if isinstance(metadata.get("planner_debug"), dict) else {}
    planner_obedience = metadata.get("planner_obedience") if isinstance(metadata.get("planner_obedience"), dict) else {}
    jobs = tuple(job for job in payload.get("jobs", ()) if isinstance(job, dict)) if isinstance(payload, dict) else ()
    tool_chain = tuple(str(job.get("tool_name") or "") for job in jobs if job.get("tool_name"))
    tool_results = tuple(dict(job.get("result") or {}) for job in jobs if isinstance(job.get("result"), dict))
    stage_timings = _stage_timings_from_metadata(
        metadata=metadata,
        planner_debug=planner_debug,
        tool_results=tool_results,
        http_boundary_ms=http_boundary_ms,
        event_collection_ms=event_collection_ms,
        total_latency_ms=latency_ms,
    )
    route_family = _route_family(route_state, planner_debug, tool_chain, assistant_message)
    response_active_request_state = (
        payload.get("active_request_state") if isinstance(payload.get("active_request_state"), dict) else {}
    )
    snapshot_active_request_state = (
        snapshot.get("active_request_state") if isinstance(snapshot.get("active_request_state"), dict) else {}
    )
    payload_diagnostics = _payload_diagnostics(
        payload=payload,
        tool_results=tool_results,
        response_json_bytes=response_json_bytes,
    )
    return CoreObservation(
        case_id=case.case_id,
        input_boundary=input_boundary,
        latency_ms=round(latency_ms, 3),
        ui_response=str(assistant_message.get("content") or ""),
        session_id=session_id,
        status="completed" if status_code < 400 else "http_error",
        elapsed_ms=round(latency_ms, 3),
        child_pid=child_pid,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        checkpoint_path=checkpoint_path,
        actual_route_family=route_family,
        actual_subsystem=_subsystem_for_observation(route_family, tool_chain),
        tool_chain=tool_chain,
        tool_results=tool_results,
        job_states=tuple(str(job.get("status") or "") for job in jobs),
        result_state=_result_state(route_family, planner_debug, route_state, jobs, tool_results),
        verification_state=_verification_state(tool_results, metadata),
        clarification_observed=_clarification_observed(route_state, planner_debug, assistant_message),
        approval_observed=_approval_observed(tool_results, payload, assistant_message),
        target_slots=_target_slots(planner_debug, jobs),
        route_state=route_state,
        planner_debug=planner_debug,
        planner_obedience=planner_obedience,
        response_active_request_state=dict(response_active_request_state),
        snapshot_active_request_state=dict(snapshot_active_request_state),
        stage_timings_ms=stage_timings,
        response_json_bytes=int(response_json_bytes),
        event_count=len(events),
        job_count=len(jobs),
        ui_event_count=_ui_event_count(events),
        workspace_item_count=int(payload_diagnostics.get("workspace_item_count") or _workspace_item_count(payload, tool_results)),
        active_context_bytes=int(payload_diagnostics.get("active_context_bytes") or 0),
        active_context_item_count=int(payload_diagnostics.get("active_context_item_count") or 0),
        truncated_workspace_items=bool(payload_diagnostics.get("truncated_workspace_items")),
        largest_payload_fields=tuple(payload_diagnostics.get("largest_payload_fields") or ()),
        payload_guardrail_triggered=bool(payload_diagnostics.get("payload_guardrail_triggered")),
        payload_guardrail_reason=str(payload_diagnostics.get("payload_guardrail_reason") or ""),
        route_handler_subspans=_route_handler_subspans(metadata, planner_debug, tool_results),
        ai_provider_calls=ai_provider_calls,
        actions=tuple(action for action in payload.get("actions", ()) if isinstance(action, dict)) if isinstance(payload, dict) else (),
        events=events,
        errors=tuple(_errors(status_code, payload, jobs, tool_results)),
    )


def _stage_timings_from_metadata(
    *,
    metadata: dict[str, Any],
    planner_debug: dict[str, Any],
    tool_results: tuple[dict[str, Any], ...],
    http_boundary_ms: float,
    event_collection_ms: float,
    total_latency_ms: float,
) -> dict[str, float]:
    stage_timings = metadata.get("stage_timings_ms") if isinstance(metadata.get("stage_timings_ms"), dict) else {}
    if not stage_timings:
        stage_timings = planner_debug.get("stage_timings_ms") if isinstance(planner_debug.get("stage_timings_ms"), dict) else {}
    timings = {str(key): round(float(value or 0.0), 3) for key, value in dict(stage_timings).items()}
    timings["http_boundary_ms"] = round(float(http_boundary_ms or 0.0), 3)
    timings["http_client_wait_ms"] = round(float(http_boundary_ms or 0.0), 3)
    timings["event_collection_ms"] = round(float(event_collection_ms or 0.0), 3)
    timings["dry_run_executor_ms"] = round(_dry_run_executor_ms(tool_results), 3)
    timings["total_latency_ms"] = round(float(total_latency_ms or 0.0), 3)
    return timings


def _dry_run_executor_ms(tool_results: tuple[dict[str, Any], ...]) -> float:
    total = 0.0
    for result in tool_results:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        total += float(data.get("dry_run_executor_ms") or 0.0)
    return total


def _ui_event_count(events: tuple[dict[str, Any], ...]) -> int:
    return sum(
        1
        for event in events
        if str(event.get("visibility_scope") or "").strip().lower()
        not in {"internal_only", "ephemeral", ""}
    )


def _workspace_item_count(payload: dict[str, Any], tool_results: tuple[dict[str, Any], ...]) -> int:
    roots: list[Any] = [payload]
    for result in tool_results:
        roots.append(result.get("data"))
    return sum(_count_workspace_items(root) for root in roots)


def _payload_diagnostics(
    *,
    payload: dict[str, Any],
    tool_results: tuple[dict[str, Any], ...],
    response_json_bytes: int,
) -> dict[str, Any]:
    roots: list[Any] = [payload]
    for result in tool_results:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        roots.append(data)
    guardrails = [guardrail for root in roots for guardrail in _collect_payload_guardrails(root)]
    active_context_bytes = max(
        [int(guardrail.get("active_context_bytes") or 0) for guardrail in guardrails] or [0]
    )
    active_context_item_count = max(
        [int(guardrail.get("active_context_item_count") or 0) for guardrail in guardrails] or [0]
    )
    guardrail_reasons = [
        str(guardrail.get("payload_guardrail_reason") or "").strip()
        for guardrail in guardrails
        if str(guardrail.get("payload_guardrail_reason") or "").strip()
    ]
    truncated = any(bool(guardrail.get("truncated_workspace_items")) for guardrail in guardrails) or _contains_truncated_flag(roots)
    reasons = list(guardrail_reasons)
    if response_json_bytes >= 5_000_000:
        reasons.append("response_payload_over_fail_guardrail")
    elif response_json_bytes >= 1_000_000:
        reasons.append("response_payload_over_warn_guardrail")
    if truncated and "workspace_items_truncated" not in reasons:
        reasons.append("workspace_items_truncated")
    return {
        "workspace_item_count": _workspace_item_count(payload, tool_results),
        "active_context_bytes": active_context_bytes,
        "active_context_item_count": active_context_item_count,
        "truncated_workspace_items": truncated,
        "largest_payload_fields": tuple(_largest_payload_fields(payload, tool_results)),
        "payload_guardrail_triggered": bool(reasons) or any(bool(guardrail.get("payload_guardrail_triggered")) for guardrail in guardrails),
        "payload_guardrail_reason": ",".join(dict.fromkeys(reason for reason in reasons if reason)),
    }


def _collect_payload_guardrails(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        guardrails: list[dict[str, Any]] = []
        for key, item in value.items():
            if key in {"payloadGuardrails", "payload_guardrails"} and isinstance(item, dict):
                guardrails.append(dict(item))
            else:
                guardrails.extend(_collect_payload_guardrails(item))
        return guardrails
    if isinstance(value, list):
        guardrails: list[dict[str, Any]] = []
        for item in value:
            guardrails.extend(_collect_payload_guardrails(item))
        return guardrails
    return []


def _contains_truncated_flag(value: Any) -> bool:
    if isinstance(value, dict):
        if bool(value.get("truncated")):
            return True
        return any(_contains_truncated_flag(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_truncated_flag(item) for item in value)
    return False


def _largest_payload_fields(payload: dict[str, Any], tool_results: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    roots: list[tuple[str, Any]] = [("response", payload)]
    for index, result in enumerate(tool_results):
        roots.append((f"tool_results[{index}]", result.get("data")))
    for root_name, root in roots:
        if not isinstance(root, dict):
            continue
        for key, value in root.items():
            try:
                size = len(json.dumps(value, default=str, separators=(",", ":")).encode("utf-8"))
            except (TypeError, ValueError):
                size = 0
            candidates.append({"path": f"{root_name}.{key}", "bytes": size})
    return sorted(candidates, key=lambda item: int(item.get("bytes") or 0), reverse=True)[:8]


def _count_workspace_items(value: Any) -> int:
    if isinstance(value, dict):
        count = 0
        for key, item in value.items():
            if key in {"items", "opened_items", "references", "findings", "session_notes", "pending_next_steps"} and isinstance(item, list):
                count += len(item)
            else:
                count += _count_workspace_items(item)
        return count
    if isinstance(value, list):
        return sum(_count_workspace_items(item) for item in value)
    return 0


def _route_handler_subspans(
    metadata: dict[str, Any],
    planner_debug: dict[str, Any],
    tool_results: tuple[dict[str, Any], ...],
) -> dict[str, float]:
    candidates: list[dict[str, Any]] = []
    for container in (metadata, planner_debug):
        value = container.get("route_handler_subspans") if isinstance(container, dict) else None
        if isinstance(value, dict):
            candidates.append(value)
    for result in tool_results:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        debug = data.get("debug") if isinstance(data.get("debug"), dict) else {}
        value = debug.get("route_handler_subspans") if isinstance(debug.get("route_handler_subspans"), dict) else {}
        if value:
            candidates.append(value)
        value = data.get("route_handler_subspans") if isinstance(data.get("route_handler_subspans"), dict) else {}
        if value:
            candidates.append(value)
    merged: dict[str, float] = {}
    for candidate in candidates:
        for key, value in candidate.items():
            try:
                merged[str(key)] = round(float(merged.get(str(key), 0.0)) + float(value or 0.0), 3)
            except (TypeError, ValueError):
                continue
    return merged


def _argument_preview(arguments: dict[str, Any]) -> str:
    for key in ("text", "url", "path", "app_name", "query", "workflow_name", "routine_name", "destination_alias"):
        value = str(arguments.get(key) or "").strip()
        if value:
            if len(value) > 80:
                value = value[:77] + "..."
            return f" for {value!r}"
    return ""


def _route_family(
    route_state: dict[str, Any],
    planner_debug: dict[str, Any],
    tool_chain: tuple[str, ...],
    assistant_message: dict[str, Any],
) -> str:
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    family = str(winner.get("route_family") or "").strip()
    if family:
        return family
    routing = planner_debug.get("routing") if isinstance(planner_debug.get("routing"), dict) else {}
    routing_winner = routing.get("winner") if isinstance(routing.get("winner"), dict) else {}
    family = str(routing_winner.get("route_family") or "").strip()
    if family:
        return family
    if tool_chain:
        return TOOL_ROUTE_FAMILY.get(tool_chain[0], "unknown")
    content = str(assistant_message.get("content") or "").lower()
    if "not configured" in content or "can still help draft" in content:
        return "generic_provider"
    if "can't" in content or "couldn't" in content or "unsupported" in content:
        return "unsupported"
    return ""


def _result_state(
    route_family: str,
    planner_debug: dict[str, Any],
    route_state: dict[str, Any],
    jobs: tuple[dict[str, Any], ...],
    tool_results: tuple[dict[str, Any], ...],
) -> str:
    if _clarification_observed(route_state, planner_debug, {"content": ""}):
        return "needs_clarification"
    if any(result.get("data", {}).get("dry_run") for result in tool_results if isinstance(result.get("data"), dict)):
        return "dry_run"
    if jobs:
        statuses = {str(job.get("status") or "") for job in jobs}
        if statuses == {"completed"}:
            return "completed"
        if "failed" in statuses:
            return "failed"
        return ",".join(sorted(statuses))
    if route_family == "generic_provider":
        return "provider_fallback"
    if route_family == "unsupported":
        return "unsupported"
    response_mode = str(planner_debug.get("response_mode") or "").strip()
    return response_mode or "no_tool_response"


def _verification_state(tool_results: tuple[dict[str, Any], ...], metadata: dict[str, Any]) -> str:
    ceilings: list[str] = []
    for result in tool_results:
        execution = result.get("adapter_execution") if isinstance(result.get("adapter_execution"), dict) else {}
        if execution.get("verification_observed") == "dry_run":
            return "dry_run_preview"
        ceiling = str(execution.get("claim_ceiling") or "").strip()
        if ceiling:
            ceilings.append(ceiling)
    if ceilings:
        return ",".join(sorted(set(ceilings)))
    if metadata.get("verification_state"):
        return str(metadata["verification_state"])
    return "not_applicable"


def _subsystem_for_observation(route_family: str, tool_chain: tuple[str, ...]) -> str:
    if tool_chain:
        subsystem = TOOL_SUBSYSTEM.get(str(tool_chain[0] or ""))
        if subsystem:
            return subsystem
    return ROUTE_SUBSYSTEM.get(route_family, "")


def _clarification_observed(route_state: dict[str, Any], planner_debug: dict[str, Any], assistant_message: dict[str, Any]) -> bool:
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    if bool(winner.get("clarification_needed")):
        return True
    if str(planner_debug.get("response_mode") or "") == "clarification":
        return True
    content = str(assistant_message.get("content") or "").lower()
    if "reliable screen bearing" in content or "can't safely describe the visible state" in content:
        return True
    return any(phrase in content for phrase in ("which one", "i still need", "clarify", "do you mean"))


def _approval_observed(tool_results: tuple[dict[str, Any], ...], payload: dict[str, Any], assistant_message: dict[str, Any]) -> bool:
    for result in tool_results:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        execution = result.get("adapter_execution") if isinstance(result.get("adapter_execution"), dict) else {}
        if (
            data.get("approval_required")
            or data.get("preview_required")
            or execution.get("approval_required")
            or execution.get("preview_required")
        ):
            return True
    active_state = payload.get("active_request_state") if isinstance(payload.get("active_request_state"), dict) else {}
    if active_state.get("trust"):
        return True
    content = str(assistant_message.get("content") or "").lower()
    if "prepared a local" in content:
        return True
    return "approval" in content or "confirm" in content


def _target_slots(planner_debug: dict[str, Any], jobs: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    structured = planner_debug.get("structured_query") if isinstance(planner_debug.get("structured_query"), dict) else {}
    raw_slots = structured.get("slots") if isinstance(structured.get("slots"), dict) else {}
    slots.update(raw_slots)
    route_spine = raw_slots.get("route_spine") if isinstance(raw_slots.get("route_spine"), dict) else {}
    intent_frame = raw_slots.get("intent_frame") if isinstance(raw_slots.get("intent_frame"), dict) else {}
    if not intent_frame:
        intent_frame = route_spine.get("intent_frame") if isinstance(route_spine.get("intent_frame"), dict) else {}
    selected_spec = str(raw_slots.get("selected_route_spec") or route_spine.get("selected_route_spec") or "")
    if selected_spec == "browser_destination":
        target_text = str(intent_frame.get("target_text") or "").strip()
        if target_text:
            slots.setdefault("destination_name", target_text)
    for job in jobs:
        arguments = job.get("arguments") if isinstance(job.get("arguments"), dict) else {}
        slots.update({f"tool.{key}": value for key, value in arguments.items()})
    return json_ready(slots)


def _errors(
    status_code: int,
    payload: dict[str, Any],
    jobs: tuple[dict[str, Any], ...],
    tool_results: tuple[dict[str, Any], ...],
) -> list[str]:
    errors: list[str] = []
    if status_code >= 400:
        errors.append(f"http_{status_code}")
    if isinstance(payload.get("detail"), str):
        errors.append(str(payload["detail"]))
    for job in jobs:
        if job.get("error"):
            errors.append(str(job["error"]))
    for result in tool_results:
        if result.get("error"):
            errors.append(str(result["error"]))
    return errors


def _assert_case(case: CommandEvalCase, observation: CoreObservation) -> dict[str, AssertionOutcome]:
    expected = case.expected
    assertions = {
        "route_family": AssertionOutcome(
            "route_family",
            observation.actual_route_family == expected.route_family,
            expected.route_family,
            observation.actual_route_family,
        ),
        "subsystem": AssertionOutcome(
            "subsystem",
            not expected.subsystem or observation.actual_subsystem == expected.subsystem,
            expected.subsystem,
            observation.actual_subsystem,
        ),
        "tool_chain": AssertionOutcome(
            "tool_chain",
            _tools_match(expected.tools, observation.tool_chain),
            expected.tools,
            observation.tool_chain,
        ),
        "clarification": AssertionOutcome(
            "clarification",
            _clarification_matches(expected.clarification, observation.clarification_observed),
            expected.clarification,
            observation.clarification_observed,
        ),
        "approval": AssertionOutcome(
            "approval",
            _approval_matches(expected.approval, observation.approval_observed),
            expected.approval,
            observation.approval_observed,
        ),
        "target_slots": AssertionOutcome(
            "target_slots",
            _slots_match(expected.target_slots, observation.target_slots),
            expected.target_slots,
            observation.target_slots,
        ),
        "response_meaning": AssertionOutcome(
            "response_meaning",
            _response_terms_match(expected.response_terms, observation.ui_response),
            expected.response_terms,
            observation.ui_response,
        ),
        "no_overclaim": AssertionOutcome(
            "no_overclaim",
            _no_overclaim(expected.forbidden_overclaims, observation),
            expected.forbidden_overclaims,
            observation.ui_response,
        ),
        "payload_guardrail": AssertionOutcome(
            "payload_guardrail",
            int(observation.response_json_bytes or 0) <= PAYLOAD_GUARDRAIL_FAIL_BYTES,
            f"<= {PAYLOAD_GUARDRAIL_FAIL_BYTES} response_json_bytes",
            observation.response_json_bytes,
        ),
        "latency": AssertionOutcome(
            "latency",
            observation.latency_ms <= expected.latency_ms_max,
            expected.latency_ms_max,
            observation.latency_ms,
        ),
        "provider_usage": AssertionOutcome(
            "provider_usage",
            not _provider_usage_violation(case, observation),
            "no provider/model calls unless explicitly labeled provider-fallback diagnostic",
            _provider_usage_actual(case, observation),
        ),
    }
    return assertions


def _failure_reason(assertions: dict[str, AssertionOutcome]) -> str:
    failures = [
        f"{name}: expected {outcome.expected!r}, actual {outcome.actual!r}"
        for name, outcome in assertions.items()
        if not outcome.passed
    ]
    return "; ".join(failures)


def _failure_category(
    case: CommandEvalCase,
    observation: CoreObservation,
    assertions: dict[str, AssertionOutcome],
    *,
    score_in_pass_fail: bool,
) -> str:
    failed = {name for name, outcome in assertions.items() if not outcome.passed}
    if not failed:
        return "passed"
    if not score_in_pass_fail:
        return "feature_map_overexpectation"
    if observation.result_state == "hard_timeout" or observation.status == "hard_timeout":
        return "hard_timeout"
    if observation.result_state == "timed_out" or any("per_test_timeout" in error for error in observation.errors):
        return "harness_bug"
    if "provider_usage" in failed:
        return "harness_bug"
    if "payload_guardrail" in failed or int(observation.response_json_bytes or 0) > PAYLOAD_GUARDRAIL_FAIL_BYTES:
        return "payload_guardrail_failure"
    if "no_overclaim" in failed:
        return "truthfulness_failure"
    if failed == {"latency"}:
        return "latency_issue"
    if _telemetry_missing(case, observation, failed):
        return "missing_telemetry"
    if _looks_like_corpus_expectation_bug(case, observation, failed):
        return "corpus_expectation_bug"
    if "subsystem" in failed and observation.actual_route_family and observation.actual_route_family != "generic_provider":
        return "wrong_subsystem"
    if "route_family" in failed or "tool_chain" in failed:
        return "real_routing_gap"
    if "response_meaning" in failed or "target_slots" in failed:
        return "response_correctness_failure"
    if "latency" in failed:
        return "latency_issue"
    return "response_correctness_failure"


def _telemetry_missing(case: CommandEvalCase, observation: CoreObservation, failed: set[str]) -> bool:
    if observation.tool_chain and not observation.planner_obedience:
        direct_only = case.expected.route_family in {"time", "notes", "terminal", "development"}
        return not direct_only
    if case.expected.route_family not in {"time", "notes", "terminal", "development"} and not observation.route_state:
        return bool(observation.actual_route_family and observation.actual_route_family != "generic_provider")
    return False


def _looks_like_corpus_expectation_bug(case: CommandEvalCase, observation: CoreObservation, failed: set[str]) -> bool:
    response = observation.ui_response.lower()
    message = case.message.lower()
    if failed <= {"approval"} and any(phrase in response for phrase in {"i have not installed", "i have not updated", "prepared a local"}):
        return True
    if case.case_id.startswith("workflow_execute") and "morning setup" in message:
        return True
    if case.case_id.startswith("context_action") and "summarize this selection" in message:
        return True
    if case.case_id.startswith("file_operation") and "rename the screenshots" in message:
        return True
    if case.case_id.startswith("browser_deck") and failed <= {"approval"}:
        return True
    return False


def _tools_match(expected_tools: tuple[str, ...], actual_tools: tuple[str, ...]) -> bool:
    if not expected_tools:
        return not actual_tools
    return actual_tools[: len(expected_tools)] == expected_tools


def _clarification_matches(expectation: str, observed: bool) -> bool:
    if expectation == "expected":
        return observed
    if expectation == "allowed":
        return True
    return not observed


def _approval_matches(expectation: str, observed: bool) -> bool:
    if expectation in {"expected", "expected_or_preview"}:
        return observed
    if expectation == "allowed":
        return True
    return not observed


def _provider_usage_violation(case: CommandEvalCase, observation: CoreObservation) -> bool:
    if not observation.ai_provider_calls:
        return False
    return not _case_allows_provider_calls(case)


def _provider_usage_actual(case: CommandEvalCase, observation: CoreObservation) -> dict[str, Any]:
    calls = [dict(item) for item in observation.ai_provider_calls if isinstance(item, dict)]
    return {
        "provider_call_count": len(calls),
        "provider_call_allowed": _case_allows_provider_calls(case),
        "provider_names": sorted({str(item.get("provider_name") or "") for item in calls if item.get("provider_name")}),
        "model_names": sorted({str(item.get("model_name") or "") for item in calls if item.get("model_name")}),
        "blocked_count": sum(1 for item in calls if bool(item.get("blocked"))),
    }


def _case_allows_provider_calls(case: CommandEvalCase) -> bool:
    tags = {str(tag).strip().lower() for tag in case.tags}
    return bool(tags & {"provider_fallback_diagnostic", "provider_allowed", "ai_allowed", "model_allowed"})


def _slots_match(expected_slots: dict[str, Any], actual_slots: dict[str, Any]) -> bool:
    for key, expected_value in expected_slots.items():
        actual_value = actual_slots.get(key)
        if actual_value != expected_value:
            return False
    return True


def _response_terms_match(terms: tuple[str, ...], response: str) -> bool:
    lowered = response.lower()
    return all(term.lower() in lowered for term in terms)


def _no_overclaim(phrases: tuple[str, ...], observation: CoreObservation) -> bool:
    response = observation.ui_response.lower()
    if observation.verification_state in {"verified", "completed"}:
        return True
    return not any(phrase.lower() in response for phrase in phrases)
