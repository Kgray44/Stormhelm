from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from stormhelm.core.api.app import create_app
from stormhelm.core.container import CoreContainer
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.core.orchestrator.assistant import STAGE_TIMING_KEYS, _subspans_from_jobs
from stormhelm.core.orchestrator.command_eval.runner import _stage_timings_from_metadata
from stormhelm.core.orchestrator.planner_v2 import PlannerV2
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.system.probe import SystemProbe
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


def test_status_default_uses_fast_hot_path_without_full_status_snapshot(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_status_snapshot(self):  # noqa: ANN001
        pytest.fail("default /status should use the fast hot-path snapshot")

    monkeypatch.setattr(CoreContainer, "status_snapshot", fail_status_snapshot)

    with TestClient(create_app(temp_config)) as client:
        response = client.get("/status")

    payload = response.json()
    assert response.status_code == 200
    assert payload["status_profile"] == "fast_status"
    assert payload["detail_load_deferred"] is True
    assert "voice" in payload
    assert "bridge_authority" not in payload
    assert "tool_state" not in payload


def test_status_default_exposes_bounded_hot_path_timing(temp_config) -> None:
    with TestClient(create_app(temp_config)) as client:
        response = client.get("/status")

    payload = response.json()
    assert response.status_code == 200
    assert payload["status_profile"] == "fast_status"
    assert payload["status_total_ms"] >= 0.0
    assert isinstance(payload["status_sections_ms"], dict)
    assert "voice" in payload["status_sections_ms"]
    assert "system_state" in payload["status_sections_ms"]
    assert "workspace" in payload["status_deferred_sections"]
    assert payload["status_payload_bytes"] > 0
    assert payload["status_payload_bytes"] < 120_000


def test_status_full_detail_remains_explicit_opt_in(temp_config) -> None:
    with TestClient(create_app(temp_config)) as client:
        response = client.get("/status", params={"detail": "full"})

    payload = response.json()
    assert response.status_code == 200
    assert "bridge_authority" in payload
    assert payload.get("status_profile") != "fast_status"


def test_ghost_light_snapshot_is_default_and_avoids_deck_detail(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_status_snapshot(self):  # noqa: ANN001
        pytest.fail("ghost_light snapshot should not build full status snapshot")

    monkeypatch.setattr(CoreContainer, "status_snapshot", fail_status_snapshot)

    with TestClient(create_app(temp_config)) as client:
        response = client.get("/snapshot", params={"session_id": "default"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["snapshot_profile"] == "ghost_light"
    assert payload["status"]["status_profile"] == "fast_status"
    assert payload["active_workspace"]["detail_load_deferred"] is True
    assert "settings" not in payload
    assert "tools" not in payload
    assert "deck_detail" not in payload


def test_ghost_light_snapshot_exposes_profile_timing_and_size(temp_config) -> None:
    with TestClient(create_app(temp_config)) as client:
        response = client.get(
            "/snapshot",
            params={
                "session_id": "default",
                "event_limit": 12,
                "job_limit": 8,
                "note_limit": 0,
                "history_limit": 12,
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["snapshot_profile"] == "ghost_light"
    assert payload["snapshot_total_ms"] >= 0.0
    assert payload["snapshot_payload_bytes"] > 0
    assert payload["snapshot_payload_bytes"] < 200_000
    assert "deck_detail" in payload["snapshot_deferred_sections"]
    assert isinstance(payload["snapshot_largest_sections"], list)
    assert payload["snapshot_largest_sections"]
    assert all("section" in item and "bytes" in item for item in payload["snapshot_largest_sections"])


def test_deck_detail_snapshot_remains_explicit_opt_in(temp_config) -> None:
    with TestClient(create_app(temp_config)) as client:
        response = client.get(
            "/snapshot",
            params={
                "session_id": "default",
                "profile": "deck_detail",
                "event_limit": 1,
                "job_limit": 1,
                "note_limit": 1,
                "history_limit": 1,
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["snapshot_profile"] == "deck_detail"
    assert "settings" in payload
    assert "tools" in payload
    assert "status" in payload


def test_weather_status_exposes_safe_location_provider_cache_subspans(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = SystemProbe(temp_config)

    def fake_resolve(self, **kwargs):  # noqa: ANN001, ANN202
        return {
            "resolved": True,
            "source": "queried_place",
            "label": "Perkinsville, Vermont",
            "latitude": 43.15,
            "longitude": -72.51,
            "timezone": "America/New_York",
            "approximate": False,
        }

    def fake_fetch(self, url: str, *, timeout: float):  # noqa: ANN001, ANN202
        assert "api_key" not in url.lower()
        return {
            "current": {
                "temperature_2m": 51.0,
                "apparent_temperature": 48.0,
                "weather_code": 3,
                "wind_speed_10m": 6.0,
                "relative_humidity_2m": 67,
            },
            "daily": {
                "weather_code": [3, 45],
                "temperature_2m_max": [56.0, 60.0],
                "temperature_2m_min": [39.0, 42.0],
                "precipitation_probability_max": [20, 35],
            },
            "hourly": {
                "temperature_2m": [50.0],
                "apparent_temperature": [47.0],
                "weather_code": [3],
                "precipitation_probability": [20],
            },
        }

    monkeypatch.setattr(SystemProbe, "resolve_best_location_for_request", fake_resolve)
    monkeypatch.setattr(SystemProbe, "_fetch_json", fake_fetch)

    result = probe.weather_status(
        location_mode="named",
        named_location="Perkinsville Vermont",
        named_location_type="place_query",
    )

    assert result["available"] is True
    trace = result["weather_trace"]
    assert trace["weather_location_lookup_ms"] >= 0.0
    assert trace["weather_provider_call_ms"] >= 0.0
    assert trace["weather_cache_hit"] is False
    assert trace["weather_timeout_ms"] == 6000.0
    assert trace["weather_provider_status"] == "ok"
    assert trace["weather_job_wait_ms"] == 0.0
    assert trace["weather_provider_service"] == "open-meteo"
    assert "api_key" not in str(trace).lower()
    assert result["weather_location_lookup_ms"] == trace["weather_location_lookup_ms"]
    assert result["weather_provider_call_ms"] == trace["weather_provider_call_ms"]


def test_weather_job_subspans_are_available_for_route_metadata() -> None:
    class _Job:
        result = {
            "data": {
                "weather_trace": {
                    "weather_location_lookup_ms": 12.5,
                    "weather_provider_call_ms": 34.25,
                    "weather_timeout_ms": 6000.0,
                    "weather_job_wait_ms": 0.0,
                }
            }
        }

    subspans = _subspans_from_jobs([_Job()])

    assert subspans["weather_location_lookup_ms"] == 12.5
    assert subspans["weather_provider_call_ms"] == 34.25
    assert subspans["weather_timeout_ms"] == 6000.0


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
