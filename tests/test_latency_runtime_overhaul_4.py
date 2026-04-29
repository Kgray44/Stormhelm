from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from stormhelm.core.api.app import create_app
from stormhelm.core.container import CoreContainer
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.core.orchestrator.assistant import STAGE_TIMING_KEYS
from stormhelm.core.orchestrator.command_eval.runner import _stage_timings_from_metadata
from stormhelm.core.orchestrator.planner_v2 import PlannerV2
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.workspace.repository import WorkspaceRepository

from test_assistant_orchestrator import FakeSystemProbe
from test_assistant_orchestrator import _build_assistant_with_workspace


def _run(coro):
    return asyncio.run(coro)


def _seed_state(temp_config) -> tuple[ConversationStateStore, WorkspaceRepository]:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    preferences = PreferencesRepository(database)
    state = ConversationStateStore(preferences)
    repository = WorkspaceRepository(database)
    return state, repository


def test_compact_snapshot_omits_full_status_tools_and_workspace_detail(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, repository = _seed_state(temp_config)
    workspace = repository.upsert_workspace(
        name="Compact Snapshot Workspace",
        topic="latency pass 4",
        summary="Only the active id is needed for command-eval snapshot checks.",
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    state.set_active_request_state(
        "default",
        {
            "family": "software_control",
            "subject": "Example App",
            "context_freshness": "current",
            "context_reusable": True,
        },
    )

    def fail_status_snapshot(self):  # noqa: ANN001
        pytest.fail("compact command-eval snapshot should not build full status snapshot")

    monkeypatch.setattr(CoreContainer, "status_snapshot", fail_status_snapshot)

    with TestClient(create_app(temp_config)) as client:
        response = client.get("/snapshot", params={"session_id": "default", "compact": True})

    payload = response.json()
    assert response.status_code == 200
    assert payload["snapshot_profile"] == "command_eval_compact"
    assert payload["active_request_state"]["family"] == "software_control"
    assert payload["active_workspace"]["workspace_id"] == workspace.workspace_id
    assert payload["active_workspace"]["summary_omitted"] is True
    assert payload["active_task"]["summary_omitted"] is True
    assert "status" not in payload
    assert "tools" not in payload
    assert "settings" not in payload
    assert "history" not in payload


def test_command_eval_snapshot_timing_is_attributed() -> None:
    timings = _stage_timings_from_metadata(
        metadata={"stage_timings_ms": {"route_handler_ms": 3.0}},
        planner_debug={},
        tool_results=(),
        http_boundary_ms=10.0,
        event_collection_ms=2.0,
        snapshot_ms=4.5,
        total_latency_ms=20.0,
    )

    assert timings["snapshot_ms"] == 4.5
    assert timings["event_collection_ms"] == 2.0
    assert timings["http_boundary_ms"] == 10.0


def test_workspace_compact_payload_builds_reference_without_full_to_dict(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, executor, _, workspace_service = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        workspace = workspace_service.repository.upsert_workspace(
            name="Source Level Compact Workspace",
            topic="summary first",
            summary="Compact payload should not materialize full arrays.",
            references=[{"itemId": f"ref-{index}", "title": f"Reference {index}"} for index in range(100)],
        )

        monkeypatch.setattr(
            type(workspace),
            "to_dict",
            lambda self: pytest.fail("limit=0 compact workspace payload should not call to_dict"),
        )

        payload = workspace_service._compact_workspace_payload(workspace, limit=0)
    finally:
        executor.shutdown()

    assert payload["workspaceId"] == workspace.workspace_id
    assert payload["referencesSummary"]["total_count"] == 100
    assert payload["referencesSummary"]["displayed_count"] == 0
    assert payload["detailLoadDeferred"] is True
    assert "references" not in payload


def test_compact_workspace_save_preserves_truth_and_defers_detail(temp_config) -> None:
    _, _, executor, session_state, workspace_service = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        workspace = workspace_service.repository.upsert_workspace(
            name="Compact Save Workspace",
            topic="latency pass 4 save",
            summary="Save should still write the snapshot while returning compact detail.",
            references=[{"itemId": "ref-1", "title": "Reference"}],
        )
        session_state.set_active_workspace_id("default", workspace.workspace_id)
        session_state.set_active_posture(
            "default",
            {
                "workspace": workspace.to_dict(),
                "opened_items": [{"itemId": "item-1", "title": "Opened item"}],
                "pending_next_steps": ["Keep the save truthful."],
            },
        )

        result = workspace_service.save_workspace(session_id="default", compact=True)
        latest_snapshot = workspace_service.repository.get_latest_snapshot(workspace.workspace_id)
    finally:
        executor.shutdown()

    assert "saved" in result["summary"].lower()
    assert result["detail_load_deferred"] is True
    assert result["workspace"]["detailLoadDeferred"] is True
    assert result["workspace"]["referencesSummary"]["total_count"] == 1
    assert latest_snapshot is not None
    assert latest_snapshot.workspace_id == workspace.workspace_id


def test_payload_guardrail_triggered_is_diagnostic_not_failure_in_compact_workspace(temp_config) -> None:
    _, _, executor, _, workspace_service = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        workspace = workspace_service.repository.upsert_workspace(
            name="Guardrail Diagnostic Workspace",
            topic="payload guardrails",
            summary="Guardrails can mark truncation without being a payload failure.",
            references=[{"itemId": f"ref-{index}", "title": f"Reference {index}"} for index in range(120)],
        )
        payload = workspace_service._workspace_view_payload(workspace, pending_next_steps=["Keep it bounded."])
    finally:
        executor.shutdown()

    guardrails = payload["payloadGuardrails"]
    assert guardrails["payload_guardrail_triggered"] is True
    assert guardrails["payload_guardrail_reason"] == "workspace_items_truncated"
    assert guardrails["response_json_bytes"] < guardrails["fail_threshold_bytes"]


def test_dry_run_and_context_canaries_remain_clean_after_pass4(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORMHELM_COMMAND_EVAL_DRY_RUN", "true")
    assistant, jobs, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    planner = PlannerV2()

    async def fail_submit(*args, **kwargs):  # noqa: ANN001
        pytest.fail("command-eval dry-run should not submit live jobs")

    monkeypatch.setattr(jobs, "submit", fail_submit)

    try:
        assistant_text, dry_run_jobs, actions = _run(
            assistant._execute_tool_requests(
                [
                    ToolRequest(
                        "maintenance_action",
                        {"maintenance_kind": "cleanup", "dry_run": True},
                    ),
                ],
                session_id="default",
                prompt="run maintenance cleanup",
                surface_mode="ghost",
                active_module="chartroom",
                stage_timings={key: 0.0 for key in STAGE_TIMING_KEYS},
                route_handler_subspans={},
                response_profile="command_eval_compact",
                request_cache={},
            )
        )
    finally:
        executor.shutdown()

    no_context = planner.plan("can you handle this?")
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

    assert "No external action was performed" in assistant_text
    assert dry_run_jobs[0]["result"]["data"]["dry_run"] is True
    assert dry_run_jobs[0]["result"]["data"]["dry_run_compact"] is True
    assert actions == []
    assert no_context.route_decision.selected_route_family == "context_clarification"
    assert no_context.route_decision.generic_provider_allowed is False
    assert correction.route_decision.selected_route_family == "browser_destination"
    assert correction.route_decision.generic_provider_allowed is False
