from __future__ import annotations

import asyncio

from stormhelm.core.events import EventBuffer
from stormhelm.core.container import build_container
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.latency import attach_latency_metadata
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import NotesRepository
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.core.memory.repositories import ToolRunRepository
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.subsystem_continuations import SubsystemContinuationRegistry
from stormhelm.core.subsystem_continuations import SubsystemContinuationRequest
from stormhelm.core.subsystem_continuations import SubsystemContinuationResult
from stormhelm.core.subsystem_continuations import SubsystemContinuationRunner
from stormhelm.core.subsystem_continuations import classify_subsystem_continuation
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins.subsystem_continuation import SubsystemContinuationTool
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry


def test_continuation_request_serializes_safely_and_redacts_sensitive_payload() -> None:
    request = SubsystemContinuationRequest.create(
        route_family="software_control",
        subsystem="software_control",
        operation_kind="software_control.execute_approved_operation",
        stage="queued",
        session_id="s1",
        payload_summary={
            "target": "Minecraft",
            "api_key": "sk-secret",
            "raw_audio": b"not allowed",
        },
        debug={"Authorization": "Bearer secret", "safe": "ok"},
    )

    payload = request.to_dict()

    assert payload["continuation_id"].startswith("subcont-")
    assert payload["route_family"] == "software_control"
    assert payload["completion_claimed"] is False
    assert payload["verification_claimed"] is False
    assert payload["payload_summary"]["api_key"] == "<redacted>"
    assert payload["payload_summary"]["raw_audio"] == "<redacted>"
    assert payload["debug"]["Authorization"] == "<redacted>"


def test_continuation_result_clamps_completion_and_verification_truth() -> None:
    queued = SubsystemContinuationResult(
        continuation_id="subcont-test",
        route_family="workspace_operations",
        subsystem="workspace",
        operation_kind="workspace.assemble_deep",
        status="queued",
        result_state="queued",
        verification_state="not_verified",
        summary="Queued.",
        completion_claimed=True,
        verification_claimed=True,
    ).to_dict()
    completed_unverified = SubsystemContinuationResult(
        continuation_id="subcont-test",
        route_family="workspace_operations",
        subsystem="workspace",
        operation_kind="workspace.assemble_deep",
        status="completed",
        result_state="completed_unverified",
        verification_state="not_verified",
        summary="Assembled.",
        completion_claimed=True,
        verification_claimed=True,
    ).to_dict()

    assert queued["completion_claimed"] is False
    assert queued["verification_claimed"] is False
    assert completed_unverified["completion_claimed"] is True
    assert completed_unverified["verification_claimed"] is False


def test_subsystem_continuation_policy_marks_slow_back_halves_only() -> None:
    cases = [
        ("calculations", "calculations.evaluate", False),
        ("trust_approvals", "trust_approval.bind", False),
        ("voice_control", "voice.stop_speaking", False),
        ("browser_destination", "browser.open_url", False),
        ("workspace_operations", "workspace.assemble_deep", True),
        ("workspace_operations", "workspace.clear", False),
        ("software_control", "software_control.plan_operation", False),
        ("software_control", "software_control.execute_approved_operation", True),
        ("software_recovery", "software_recovery.run_recovery_plan", True),
        ("discord_relay", "discord_relay.preview", False),
        ("discord_relay", "discord_relay.dispatch_approved_preview", True),
        ("screen_awareness", "screen_awareness.clarify_target", False),
        ("screen_awareness", "screen_awareness.verify_change", True),
    ]

    for route_family, operation_kind, expected in cases:
        policy = classify_subsystem_continuation(
            route_family=route_family,
            subsystem=route_family,
            operation_kind=operation_kind,
            approved=True,
        )
        assert policy.worker_continuation_expected is expected, operation_kind


def test_continuation_tool_runs_handler_in_worker_and_publishes_progress(temp_config) -> None:
    events = EventBuffer(capacity=64)
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    tool_runs = ToolRunRepository(database)
    registry = ToolRegistry()

    async def fake_handler(request: SubsystemContinuationRequest, context: ToolContext) -> SubsystemContinuationResult:
        context.report_progress({"stage": "running", "api_key": "sk-secret"})
        await asyncio.sleep(0)
        return SubsystemContinuationResult(
            continuation_id=request.continuation_id,
            request_id=request.request_id,
            session_id=request.session_id,
            route_family=request.route_family,
            subsystem=request.subsystem,
            operation_kind=request.operation_kind,
            stage="completed_unverified",
            status="completed",
            result_state="completed_unverified",
            verification_state="not_verified",
            summary="Continuation back half finished.",
            progress_event_count=1,
            completion_claimed=True,
            verification_claimed=False,
        )

    continuation_registry = SubsystemContinuationRegistry()
    continuation_registry.register("workspace.assemble_deep", fake_handler)
    runner = SubsystemContinuationRunner(registry=continuation_registry, events=events)
    registry.register(SubsystemContinuationTool())
    executor = ToolExecutor(registry, max_sync_workers=1)
    jobs = JobManager(
        config=temp_config,
        executor=executor,
        context_factory=lambda job_id: ToolContext(
            job_id=job_id,
            config=temp_config,
            events=events,
            notes=notes,
            preferences=preferences,
            safety_policy=SafetyPolicy(temp_config),
            continuation_runner=runner,
        ),
        tool_runs=tool_runs,
        events=events,
    )
    request = SubsystemContinuationRequest.create(
        route_family="workspace_operations",
        subsystem="workspace",
        operation_kind="workspace.assemble_deep",
        session_id="default",
        payload_summary={"query": "motor torque"},
        worker_lane="normal",
        priority_level="normal",
    )

    async def run_job() -> dict[str, object]:
        await jobs.start()
        try:
            job = await jobs.submit(
                "subsystem_continuation",
                {"continuation_request": request.to_dict()},
                session_id="default",
                priority_lane="normal",
                priority_level="normal",
                route_family="workspace_operations",
                subsystem="workspace",
                continuation_id=request.continuation_id,
            )
            completed = await jobs.wait(job.job_id)
            return completed.to_dict()
        finally:
            await jobs.stop()
            executor.shutdown()

    job_payload = asyncio.run(run_job())
    recent_events = events.recent(limit=32)
    event_types = [event["event_type"] for event in recent_events]
    progress_payloads = [
        event["payload"]
        for event in recent_events
        if event["event_type"] == "job.progress"
    ]

    assert job_payload["tool_name"] == "subsystem_continuation"
    assert job_payload["continuation_id"] == request.continuation_id
    assert job_payload["worker_lane"] == "normal"
    assert job_payload["queue_wait_ms"] >= 0
    assert job_payload["job_run_ms"] >= 0
    assert job_payload["result"]["data"]["subsystem_continuation_result"]["result_state"] == "completed_unverified"
    assert job_payload["result"]["data"]["subsystem_continuation_result"]["verification_claimed"] is False
    assert "subsystem.continuation.started" in event_types
    assert "subsystem.continuation.completed_unverified" in event_types
    assert progress_payloads
    assert progress_payloads[-1]["progress"]["api_key"] == "<redacted>"
    assert progress_payloads[-1]["completion_claimed"] is False
    assert progress_payloads[-1]["verification_claimed"] is False


def test_workspace_assembly_returns_worker_backed_initial_response(temp_project_root, temp_config) -> None:
    docs_dir = temp_project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "motor-torque-notes.md").write_text("Motor torque notes", encoding="utf-8")
    container = build_container(temp_config)

    async def run_request() -> dict[str, object]:
        await container.jobs.start()
        try:
            return await container.assistant.handle_message(
                "create a research workspace for motor torque",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await container.jobs.stop()
            container.tool_executor.shutdown()

    payload = asyncio.run(run_request())
    metadata = payload["assistant_message"]["metadata"]

    assert payload["jobs"][0]["tool_name"] == "subsystem_continuation"
    assert payload["jobs"][0]["status"] == "queued"
    assert metadata["subsystem_continuation_created"] is True
    assert metadata["direct_subsystem_async_converted"] is True
    assert metadata["returned_before_subsystem_completion"] is True
    assert metadata["partial_response"]["completion_claimed"] is False
    assert metadata["partial_response"]["verification_claimed"] is False
    assert metadata["latency_summary"]["subsystem_continuation_kind"] == "workspace.assemble_deep"


def test_latency_trace_and_kraken_rows_include_l42_continuation_fields() -> None:
    metadata = {
        "route_family": "workspace_operations",
        "subsystem": "workspace",
        "subsystem_continuation": {
            "subsystem_continuation_created": True,
            "subsystem_continuation_id": "subcont-1",
            "subsystem_continuation_kind": "workspace.assemble_deep",
            "subsystem_continuation_stage": "queued",
            "subsystem_continuation_status": "queued",
            "subsystem_continuation_worker_lane": "normal",
            "subsystem_continuation_queue_wait_ms": 0.0,
            "subsystem_continuation_run_ms": 0.0,
            "subsystem_continuation_total_ms": 0.0,
            "subsystem_continuation_progress_event_count": 0,
            "subsystem_continuation_final_result_state": "queued",
            "subsystem_continuation_verification_state": "not_verified",
            "direct_subsystem_async_converted": True,
            "inline_front_half_ms": 12.5,
            "worker_back_half_ms": 0.0,
            "returned_before_subsystem_completion": True,
            "async_conversion_expected": True,
            "async_conversion_missing_reason": "",
        },
    }
    attach_latency_metadata(
        metadata,
        stage_timings_ms={"total_latency_ms": 12.5, "inline_front_half_ms": 12.5},
        request_id="chat-test",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
    )

    summary = metadata["latency_summary"]
    case = CommandEvalCase(
        case_id="l42-row-1",
        message="create a research workspace for motor torque",
        expected=ExpectedBehavior(route_family="workspace_operations", subsystem="workspace"),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=12.5,
        ui_response="Queued workspace assembly.",
        actual_route_family="workspace_operations",
        actual_subsystem="workspace",
        result_state="queued",
        stage_timings_ms={"total_latency_ms": 12.5, "inline_front_half_ms": 12.5},
        latency_summary=summary,
        budget_result=dict(metadata["budget_result"]),
    )
    result = CommandEvalResult(case=case, observation=observation, assertions={})
    aggregate = build_checkpoint_summary([result])["kraken_latency_report"]
    row = result.to_dict()

    assert summary["subsystem_continuation_created"] is True
    assert summary["subsystem_continuation_id"] == "subcont-1"
    assert summary["direct_subsystem_async_converted"] is True
    assert summary["returned_before_subsystem_completion"] is True
    assert row["subsystem_continuation_kind"] == "workspace.assemble_deep"
    assert row["direct_subsystem_async_converted"] is True
    assert aggregate["converted_subsystem_route_count"] == 1
    assert aggregate["p95_inline_front_half_ms"] == 12.5
