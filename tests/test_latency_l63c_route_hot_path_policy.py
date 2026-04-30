from __future__ import annotations

import json
import time
from time import monotonic

from fastapi.testclient import TestClient

from scripts import live_runtime_latency_trace as live_trace
from stormhelm.core.api.app import create_app
from stormhelm.core.async_routes import classify_async_route_policy
from stormhelm.core.container import build_container
from stormhelm.core.latency import ROUTE_FAMILY_LATENCY_CONTRACTS
from stormhelm.core.latency import RouteExecutionMode
from stormhelm.core.latency import RouteLatencyPosture
from stormhelm.core.latency import classify_route_latency_policy
from stormhelm.core.latency import get_route_latency_contract
from stormhelm.core.orchestrator.assistant import _direct_route_family
from stormhelm.core.system.probe import SystemProbe


REQUIRED_ROUTE_FAMILIES = {
    "calculations",
    "browser_destination",
    "time",
    "weather",
    "location",
    "power",
    "network",
    "resources",
    "storage",
    "machine",
    "hardware_telemetry",
    "workspace_operations",
    "task_continuity",
    "file_operation",
    "desktop_search",
    "app_control",
    "window_control",
    "system_control",
    "software_control",
    "software_recovery",
    "discord_relay",
    "screen_awareness",
    "trust_approvals",
    "voice_control",
    "generic_provider",
    "unsupported",
}


def test_every_required_route_family_has_latency_contract() -> None:
    missing = REQUIRED_ROUTE_FAMILIES.difference(ROUTE_FAMILY_LATENCY_CONTRACTS)

    assert missing == set()
    for route_family in REQUIRED_ROUTE_FAMILIES:
        contract = get_route_latency_contract(route_family)
        assert contract.route_family == route_family
        assert contract.latency_posture in set(RouteLatencyPosture)
        assert contract.hot_path_budget_ms > 0.0
        assert contract.no_fake_data_rule


def test_system_resource_families_are_cached_fast_by_default() -> None:
    for route_family in ("resources", "power", "storage", "network", "machine"):
        contract = get_route_latency_contract(route_family)

        assert contract.latency_posture == RouteLatencyPosture.CACHED_FAST
        assert contract.stale_allowed is True
        assert contract.cache_family
        assert contract.live_probe_budget_ms <= contract.hot_path_budget_ms


def test_slow_live_system_probe_defers_instead_of_blocking(temp_config, monkeypatch) -> None:
    probe = SystemProbe(temp_config)
    refreshes: list[str] = []

    def slow_live_probe(self, *args, **kwargs):  # noqa: ANN001
        time.sleep(0.25)
        return {"available": True}

    def fake_refresh(self):  # noqa: ANN001
        refreshes.append("resource")
        return "system-resource-refresh-l63c"

    monkeypatch.setattr(SystemProbe, "_resource_status_live", slow_live_probe, raising=False)
    monkeypatch.setattr(SystemProbe, "_start_resource_status_refresh", fake_refresh, raising=False)

    started = monotonic()
    result = probe.resource_status(allow_live_refresh=False)
    elapsed_ms = (monotonic() - started) * 1000.0

    assert elapsed_ms < 100.0
    assert result["system_cache_hit"] is False
    assert result["system_freshness_state"] == "missing"
    assert result["live_probe_deferred"] is True
    assert result["live_probe_job_id"] == "system-resource-refresh-l63c"
    assert result["cpu_probe_ms"] == 0.0
    assert result["resource_probe_ms"] < 100.0
    assert refreshes == ["resource"]


def test_weather_slow_provider_defers_with_truthful_trace(temp_config, monkeypatch) -> None:
    probe = SystemProbe(temp_config)
    refreshes: list[str] = []

    def fake_location(self, **kwargs):  # noqa: ANN001
        del kwargs
        return {
            "resolved": True,
            "source": "saved_home",
            "label": "Test Harbor",
            "latitude": 41.0,
            "longitude": -73.0,
            "approximate": False,
        }

    def slow_weather_live(self, **kwargs):  # noqa: ANN001
        del kwargs
        time.sleep(0.25)
        return {"available": True, "temperature": {"current": 55, "unit": "F"}}

    def fake_refresh(self, **kwargs):  # noqa: ANN001
        refreshes.append(str(kwargs.get("forecast_target") or "current"))
        return "weather-refresh-l63c"

    monkeypatch.setattr(SystemProbe, "resolve_best_location_for_request", fake_location)
    monkeypatch.setattr(SystemProbe, "_weather_status_live", slow_weather_live, raising=False)
    monkeypatch.setattr(SystemProbe, "_start_weather_status_refresh", fake_refresh, raising=False)

    started = monotonic()
    result = probe.weather_status(
        location_mode="home",
        forecast_target="current",
        allow_live_refresh=False,
        live_probe_budget_ms=5.0,
    )
    elapsed_ms = (monotonic() - started) * 1000.0

    assert elapsed_ms < 100.0
    assert result["available"] is False
    assert result["reason"] == "weather_live_probe_deferred"
    assert result["weather_cache_hit"] is False
    assert result["weather_provider_status"] == "deferred"
    assert result["live_probe_deferred"] is True
    assert result["live_probe_job_id"] == "weather-refresh-l63c"
    assert refreshes == ["current"]


def test_workspace_file_and_deep_search_routes_use_async_continuation() -> None:
    cases = [
        ("workspace_operations", "workspace_restore", "workspace_restore_deep"),
        ("workspace_operations", "workspace_assemble", "workspace_assemble"),
        ("desktop_search", "desktop_search", "search_then_open"),
        ("file_operation", "file_operation", "execute_control_command"),
        ("hardware_telemetry", "hardware_telemetry_snapshot", "live_probe"),
    ]

    for route_family, request_kind, execution_plan_type in cases:
        policy = classify_route_latency_policy(
            route_family=route_family,
            request_kind=request_kind,
            execution_plan_type=execution_plan_type,
        )
        async_decision = classify_async_route_policy(
            route_family=route_family,
            execution_mode=policy.execution_mode,
            budget_label=policy.budget.label,
        )

        assert policy.latency_posture == RouteLatencyPosture.ASYNC_CONTINUATION
        assert policy.execution_mode == RouteExecutionMode.ASYNC_FIRST
        assert async_decision.should_return_initial_response is True
        assert async_decision.should_create_job is True


def test_instant_routes_remain_inline() -> None:
    for route_family in (
        "calculations",
        "browser_destination",
        "time",
        "trust_approvals",
        "voice_control",
    ):
        policy = classify_route_latency_policy(route_family=route_family)

        assert policy.latency_posture == RouteLatencyPosture.INSTANT
        assert policy.execution_mode == RouteExecutionMode.INSTANT
        assert policy.async_expected is False


def test_provider_fallback_cannot_own_native_status_routes() -> None:
    expected = {
        "machine_status": "machine",
        "resource_status": "resources",
        "power_status": "power",
        "storage_status": "storage",
        "network_status": "network",
        "weather_current": "weather",
        "location_status": "location",
        "saved_locations": "location",
        "recent_files": "task_continuity",
    }

    for tool_name, route_family in expected.items():
        assert _direct_route_family(tool_name) == route_family
        assert _direct_route_family(tool_name) != "generic_provider"


def test_storage_status_routes_to_native_family_instead_of_echo(temp_config) -> None:
    with TestClient(create_app(temp_config)) as client:
        response = client.post(
            "/chat/send",
            json={
                "message": "storage status",
                "session_id": "default",
                "surface_mode": "ghost",
                "active_module": "chartroom",
            },
        )

    payload = response.json()

    assert response.status_code == 200
    assert payload["jobs"][0]["tool_name"] == "storage_status"
    assert payload["assistant_message"]["content"].lower() != "echoed 11 characters."


def test_recent_files_and_machine_status_use_native_hot_path_tools(temp_config) -> None:
    with TestClient(create_app(temp_config)) as client:
        recent_response = client.post(
            "/chat/send",
            json={
                "message": "show recent files",
                "session_id": "default",
                "surface_mode": "ghost",
                "active_module": "chartroom",
            },
        )
        machine_response = client.post(
            "/chat/send",
            json={
                "message": "machine status",
                "session_id": "default",
                "surface_mode": "ghost",
                "active_module": "chartroom",
            },
        )

    recent_payload = recent_response.json()
    machine_payload = machine_response.json()

    assert recent_response.status_code == 200
    assert recent_payload["jobs"][0]["tool_name"] == "recent_files"
    assert recent_payload["jobs"][0]["tool_name"] != "desktop_search"
    assert machine_response.status_code == 200
    assert machine_payload["jobs"][0]["tool_name"] == "machine_status"


def test_status_fast_path_and_ghost_light_snapshot_do_not_run_live_probes(temp_config, monkeypatch) -> None:
    container = build_container(temp_config)

    def fail_live_probe(self, *args, **kwargs):  # noqa: ANN001
        raise AssertionError("fast status and ghost_light must not run live probes")

    monkeypatch.setattr(SystemProbe, "power_status", fail_live_probe)
    monkeypatch.setattr(SystemProbe, "resource_status", fail_live_probe)
    monkeypatch.setattr(SystemProbe, "hardware_telemetry_snapshot", fail_live_probe)
    monkeypatch.setattr(SystemProbe, "storage_status", fail_live_probe)
    monkeypatch.setattr(SystemProbe, "network_status", fail_live_probe)
    monkeypatch.setattr(SystemProbe, "resolve_location", fail_live_probe)

    status = container.status_snapshot_fast()

    assert status["status_profile"] == "fast_status"
    assert status["detail_load_deferred"] is True

    with TestClient(create_app(temp_config)) as client:
        response = client.get("/snapshot", params={"profile": "ghost_light", "session_id": "default"})

    payload = response.json()
    encoded_size = len(json.dumps(payload, default=str).encode("utf-8"))
    assert response.status_code == 200
    assert payload["snapshot_profile"] == "ghost_light"
    assert payload["detail_load_deferred"] is True
    assert encoded_size < 200_000


def test_live_trace_route_posture_fields_are_reported() -> None:
    row = {
        "prompt_id": 101,
        "prompt": "what is my CPU at",
        "category": "system_resource_hot_path",
        "mode": "voice_muted",
        "path": "direct_backend",
        "started_at": "2026-04-29T12:00:00Z",
        "chat_send_wall_ms": 80.0,
        "response_json_bytes": 1200,
        "stage_timings_ms": {
            "system_cache_hit": True,
            "system_freshness_state": "fresh",
            "resource_probe_ms": 8.0,
            "live_probe_deferred": False,
        },
        "latency_trace": {},
        "latency_summary": {},
        "route_family": "resources",
        "voice_output": {},
        "voice_speak_decision": {},
        "status_samples": [{"wall_ms": 25.0}],
        "snapshot_samples": [{"wall_ms": 35.0, "response_bytes": 5000}],
        "event_stream_events": [],
        "anchor_samples": [],
        "classifications": [],
    }

    enriched = live_trace.enrich_route_posture_fields(row)

    assert enriched["expected_posture"] == "cached_fast"
    assert enriched["actual_posture"] == "cached_fast"
    assert enriched["hot_path_budget_exceeded"] is False
    assert enriched["blocking_live_probe_detected"] is False
    assert enriched["cache_hit"] is True
    assert enriched["async_deferred"] is False
    assert enriched["payload_size_bytes"] == 1200
    assert enriched["status_snapshot_impact"]["status_max_ms"] == 25.0


def test_live_trace_does_not_call_bounded_weather_blocking_when_hot_path_is_under_budget() -> None:
    row = {
        "prompt": "what is the weather",
        "category": "weather_location_system",
        "mode": "voice_muted",
        "path": "direct_backend",
        "chat_send_wall_ms": 420.0,
        "response_json_bytes": 1200,
        "stage_timings_ms": {
            "weather_location_lookup_ms": 1_550.0,
            "weather_provider_call_ms": 80.0,
        },
        "latency_trace": {},
        "latency_summary": {},
        "route_family": "weather",
        "status_samples": [{"wall_ms": 25.0}],
        "snapshot_samples": [{"wall_ms": 35.0, "response_bytes": 5000}],
    }

    enriched = live_trace.enrich_route_posture_fields(row)

    assert enriched["expected_posture"] == "bounded_live"
    assert enriched["hot_path_budget_exceeded"] is False
    assert enriched["blocking_live_probe_detected"] is False
