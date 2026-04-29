from __future__ import annotations

import asyncio

import pytest

from stormhelm.core.orchestrator.planner_v2 import PlannerV2
from stormhelm.core.orchestrator.router import ToolRequest

from test_assistant_orchestrator import FakeSystemProbe
from test_assistant_orchestrator import _build_assistant_with_workspace


def _run(coro):
    return asyncio.run(coro)


def test_compact_workspace_summary_defers_detail_and_memory_context(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, executor, _, workspace_service = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        monkeypatch.setattr(
            workspace_service,
            "_workspace_memory_context",
            lambda *args, **kwargs: pytest.fail("compact workspace summary loaded memory detail"),
        )
        monkeypatch.setattr(
            workspace_service,
            "_build_workspace_plan",
            lambda *args, **kwargs: pytest.fail("compact workspace summary built full workspace detail"),
        )

        result = workspace_service.assemble_workspace(
            "create a workspace for latency runtime pass",
            session_id="default",
            compact=True,
        )
    finally:
        executor.shutdown()

    assert result["detail_load_deferred"] is True
    assert result["workspace"]["detailLoadDeferred"] is True
    assert result["workspace_summary_compact"]["detailLoadDeferred"] is True
    assert result["workspace_summary_compact"]["workspaceId"]
    assert result["action"]["type"] == "workspace_restore"
    assert "surfaceContent" not in result["workspace"]
    assert result["debug"]["route_handler_subspans"]["workspace_dto_build_ms"] >= 0


def test_workspace_summary_for_request_is_memoized_per_request(temp_config) -> None:
    assistant, _, executor, session_state, workspace_service = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        workspace = workspace_service.repository.upsert_workspace(
            name="Memoized Workspace",
            topic="latency memoization",
            summary="Runtime pass summary.",
        )
        session_state.set_active_workspace_id("default", workspace.workspace_id)
        request_cache: dict[str, object] = {}
        stage_timings = {key: 0.0 for key in assistant.STAGE_TIMING_KEYS} if hasattr(assistant, "STAGE_TIMING_KEYS") else {}
        stage_timings.setdefault("memoized_summary_hits", 0.0)

        first = assistant._workspace_summary_for_request(
            session_id="default",
            profile="command_eval_compact",
            request_cache=request_cache,
            stage_timings=stage_timings,
        )
        second = assistant._workspace_summary_for_request(
            session_id="default",
            profile="command_eval_compact",
            request_cache=request_cache,
            stage_timings=stage_timings,
        )
    finally:
        executor.shutdown()

    assert first is second
    assert first["detail_load_deferred"] is True
    assert stage_timings["memoized_summary_hits"] == 1.0
    assert stage_timings["workspace_summary_ms"] >= 0


def test_command_eval_compact_inline_dry_run_bypasses_job_manager_and_preserves_truth(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STORMHELM_COMMAND_EVAL_DRY_RUN", "true")
    assistant, jobs, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )

    def fail_submit(*args, **kwargs):
        pytest.fail("compact command-eval dry-run should not submit live jobs")

    monkeypatch.setattr(jobs, "submit", fail_submit)
    stage_timings = {key: 0.0 for key in assistant.STAGE_TIMING_KEYS} if hasattr(assistant, "STAGE_TIMING_KEYS") else {}
    route_subspans: dict[str, float] = {}
    try:
        assistant_text, dry_run_jobs, actions = _run(
            assistant._execute_tool_requests(
                [
                    ToolRequest(
                        "file_operation",
                        {
                            "operation": "organize",
                            "source_paths": ["C:/Stormhelm/README.md"],
                            "target_directory": "C:/Stormhelm/docs",
                            "dry_run": True,
                            "session_id": "default",
                        },
                    )
                ],
                session_id="default",
                prompt="preview organizing the README into docs",
                surface_mode="ghost",
                active_module="chartroom",
                stage_timings=stage_timings,
                route_handler_subspans=route_subspans,
                response_profile="command_eval_compact",
                request_cache={},
            )
        )
    finally:
        executor.shutdown()

    assert "No external action was performed" in assistant_text
    assert actions == []
    assert dry_run_jobs[0]["job_id"].startswith("inline-dry-run-")
    assert dry_run_jobs[0]["tool_name"] == "file_operation"
    assert dry_run_jobs[0]["status"] == "completed"
    result = dry_run_jobs[0]["result"]
    assert result["data"]["dry_run"] is True
    assert result["data"]["dry_run_compact"] is True
    assert result["data"]["detail_load_deferred"] is True
    assert result["adapter_execution"]["verification_observed"] == "dry_run"
    assert stage_timings["dry_run_plan_ms"] >= 0
    assert stage_timings["detail_load_deferred"] == 1.0
    assert route_subspans["dry_run_plan_ms"] >= 0


def test_compact_tool_data_preserves_pass2_runtime_markers(temp_config) -> None:
    assistant, _, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        compact = assistant._compact_tool_data(
            {
                "dry_run": True,
                "dry_run_compact": True,
                "detail_load_deferred": True,
                "workspace_summary_compact": {"workspaceId": "ws-1", "detailLoadDeferred": True},
                "openedItemsSummary": {"total_count": 20, "displayed_count": 2, "truncated": True},
                "referencesSummary": {"total_count": 10, "displayed_count": 2, "truncated": True},
                "route_handler_subspans": {"dry_run_plan_ms": 1.2},
            },
            profile="command_eval_compact",
        )
    finally:
        executor.shutdown()

    assert compact["dry_run"] is True
    assert compact["dry_run_compact"] is True
    assert compact["detail_load_deferred"] is True
    assert compact["workspace_summary_compact"]["workspaceId"] == "ws-1"
    assert compact["openedItemsSummary"]["truncated"] is True
    assert compact["referencesSummary"]["truncated"] is True
    assert compact["route_handler_subspans"]["dry_run_plan_ms"] == 1.2


def test_context_binding_and_retirement_canaries_remain_native() -> None:
    planner = PlannerV2()

    no_context = planner.plan("no, use the other one")
    correction = planner.plan(
        "no, use the other one",
        active_request_state={
            "family": "browser_destination",
            "subject": "YouTube",
            "parameters": {
                "tool_name": "external_open_url",
                "previous_choice": "YouTube",
                "alternate_target": "Stormhelm docs",
                "context_freshness": "current",
            },
        },
    )
    confirmation = planner.plan(
        "yes, go ahead",
        active_request_state={
            "family": "discord_relay",
            "subject": "preview",
            "parameters": {
                "tool_name": "discord_relay_preview",
                "pending_preview": {"id": "preview-discord-1", "status": "pending"},
                "context_freshness": "current",
            },
        },
    )

    assert no_context.route_decision.selected_route_family == "context_clarification"
    assert no_context.route_decision.generic_provider_allowed is False
    assert correction.route_decision.selected_route_family == "browser_destination"
    assert correction.route_decision.generic_provider_allowed is False
    assert confirmation.route_decision.selected_route_family == "discord_relay"
    assert confirmation.route_decision.generic_provider_allowed is False
