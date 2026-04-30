from __future__ import annotations

import json

from fastapi.testclient import TestClient

from scripts import live_runtime_latency_trace as trace
from stormhelm.core.api.app import create_app


def _row(**overrides):
    row = {
        "prompt_id": 1,
        "prompt": "what time is it",
        "category": "fast",
        "mode": "voice_enabled",
        "path": "direct_backend",
        "started_at": "2026-04-29T12:00:00Z",
        "chat_send_wall_ms": 520.0,
        "response_json_bytes": 1200,
        "stage_timings_ms": {"route_handler_ms": 100.0},
        "latency_trace": {},
        "latency_summary": {},
        "route_family": "clock",
        "voice_output": {
            "scheduled": True,
            "decision": {"voice_service_called": True, "speakable": True},
        },
        "voice_speak_decision": {"voice_service_called": True, "speakable": True},
        "status_samples": [],
        "snapshot_samples": [],
        "event_stream_events": [],
        "anchor_samples": [],
        "classifications": [],
    }
    row.update(overrides)
    return row


def test_report_schema_serializes() -> None:
    row = _row()

    summary = trace.build_summary(
        rows=[row],
        process_identity={"listener": {"pid": 1234}},
        config_gates={"voice": {"enabled": True}},
        voice_doctor={"raw_secret_logged": False},
        ui_path_results=[],
        started_at="2026-04-29T12:00:00Z",
        finished_at="2026-04-29T12:01:00Z",
    )

    encoded = json.dumps(summary)
    assert "process_identity" in summary
    assert "test_matrix" in summary
    assert "root_cause_ranking" in summary
    assert "top_10_slowest_backend_prompts" in summary
    assert "raw_audio" not in encoded.lower()


def test_row_required_fields_are_reported() -> None:
    missing = trace.missing_required_row_fields({"prompt": "5*4/2"})

    assert "prompt_id" in missing
    assert "chat_send_wall_ms" in missing
    assert "status_samples" in missing


def test_classification_logic_detects_backend_status_snapshot_and_payload() -> None:
    row = _row(
        chat_send_wall_ms=6100.0,
        response_json_bytes=900_000,
        stage_timings_ms={"route_handler_ms": 5300.0},
        status_samples=[{"phase": "during", "wall_ms": 4300.0}],
        snapshot_samples=[{"profile": "deck_detail", "wall_ms": 3800.0}],
    )

    classes = trace.classify_row(row)

    assert "backend_slow" in classes
    assert "status_polling_slow" in classes
    assert "snapshot_slow" in classes
    assert "response_payload_large" in classes


def test_voice_enabled_vs_muted_comparison_uses_fake_rows() -> None:
    rows = [
        _row(prompt="what time is it", mode="voice_enabled", chat_send_wall_ms=3100.0),
        _row(prompt="what time is it", mode="voice_muted", chat_send_wall_ms=510.0),
    ]

    comparisons = trace.compare_voice_modes(rows)

    assert comparisons[0]["prompt"] == "what time is it"
    assert comparisons[0]["voice_enabled_ms"] == 3100.0
    assert comparisons[0]["voice_muted_ms"] == 510.0
    assert comparisons[0]["delta_ms"] == 2590.0
    assert "voice_enabled_slower" in comparisons[0]["classification"]


def test_weather_tail_classification_uses_fake_stage_data() -> None:
    row = _row(
        prompt="what is the weather in Perkinsville Vermont",
        route_family="weather",
        chat_send_wall_ms=12_000.0,
        stage_timings_ms={
            "route_handler_ms": 8400.0,
            "job_wait_ms": 6700.0,
            "location_lookup_ms": 5100.0,
            "weather_provider_ms": 5900.0,
        },
        latency_trace={"weather_timeout_seconds": 6, "cache_hit": False},
    )

    weather = trace.classify_weather_tail(row)

    assert "provider_or_tool_wait" in weather
    assert "weather_location_wait" in weather
    assert "weather_provider_wait" in weather
    assert "provider_timeout_high" in weather


def test_weather_tail_classification_uses_l63b_weather_subspans() -> None:
    row = _row(
        prompt="what is the weather",
        route_family="weather",
        chat_send_wall_ms=3_200.0,
        stage_timings_ms={
            "route_handler_ms": 2_900.0,
            "weather_job_wait_ms": 2_600.0,
            "weather_location_lookup_ms": 1_300.0,
            "weather_provider_call_ms": 1_200.0,
            "weather_timeout_ms": 6_000.0,
        },
    )

    weather = trace.classify_weather_tail(row)
    digest = trace._weather_digest(row)

    assert "job_manager_wait" in weather
    assert "weather_location_wait" in weather
    assert "weather_provider_wait" in weather
    assert "provider_timeout_high" in weather
    assert digest["job_wait_ms"] == 2600.0
    assert digest["location_lookup_ms"] == 1300.0
    assert digest["weather_provider_ms"] == 1200.0


def test_system_resource_classification_uses_l63d_subspans() -> None:
    row = _row(
        prompt="what is my CPU at",
        route_family="resources",
        chat_send_wall_ms=420.0,
        stage_timings_ms={
            "route_handler_ms": 180.0,
            "system_resource_cache_hit": True,
            "system_resource_cache_age_ms": 750.0,
            "cpu_probe_ms": 0.0,
            "resource_status_probe_ms": 12.0,
            "hardware_telemetry_probe_ms": 0.0,
            "system_probe_deferred": False,
        },
    )

    classes = trace.classify_system_resource_tail(row)
    digest = trace._system_resource_digest(row)

    assert classes == []
    assert digest["cache_hit"] is True
    assert digest["cache_age_ms"] == 750.0
    assert digest["resource_status_probe_ms"] == 12.0


def test_system_resource_classification_marks_deferred_stale_tail() -> None:
    row = _row(
        prompt="CPU usage",
        route_family="resources",
        chat_send_wall_ms=460.0,
        stage_timings_ms={
            "route_handler_ms": 190.0,
            "system_resource_cache_hit": False,
            "system_resource_cache_age_ms": 92_000.0,
            "system_probe_deferred": True,
            "system_resource_freshness_state": "stale",
        },
    )

    classes = trace.classify_system_resource_tail(row)

    assert "system_resource_cache_miss" in classes
    assert "system_resource_cache_stale" in classes
    assert "system_live_refresh_deferred" in classes
    assert "system_resource_probe_wait" not in classes


def test_system_resource_subspan_extraction_keeps_deferred_metadata() -> None:
    metadata = {
        "system_resource_trace": {
            "system_resource_cache_hit": False,
            "system_resource_cache_age_ms": None,
            "system_probe_deferred": True,
            "system_live_refresh_job_id": "system-resource-refresh-123",
            "system_resource_freshness_state": "missing",
        },
        "stage_timings_ms": {"resource_status_probe_ms": 8.5},
    }

    subspans = trace._extract_system_resource_subspans(metadata)

    assert subspans["system_resource_cache_hit"] is False
    assert subspans["system_probe_deferred"] is True
    assert subspans["system_live_refresh_job_id"] == "system-resource-refresh-123"
    assert subspans["system_resource_freshness_state"] == "missing"
    assert subspans["resource_status_probe_ms"] == 8.5


def test_status_stall_classification() -> None:
    samples = [
        {"phase": "baseline", "wall_ms": 95.0},
        {"phase": "during_playback", "wall_ms": 4500.0},
        {"phase": "after", "wall_ms": 120.0},
    ]

    stalls = trace.status_stalls(samples)

    assert len(stalls) == 1
    assert stalls[0]["phase"] == "during_playback"
    assert stalls[0]["wall_ms"] == 4500.0


def test_anchor_missing_link_classification() -> None:
    row = _row(
        status_samples=[
            {
                "phase": "during_playback",
                "wall_ms": 120.0,
                "voice_anchor_state": "idle",
                "speaking_visual_active": False,
                "live_playback_active": True,
                "streaming_tts_active": True,
            }
        ]
    )

    classes = trace.classify_anchor_path(row)

    assert "anchor_state_not_propagated" in classes


def test_no_secrets_or_raw_audio_are_serialized() -> None:
    payload = {
        "OPENAI_API_KEY": "sk-proj-this-must-not-leak",
        "authorization": "Bearer abc",
        "audio_bytes": b"raw-audio",
        "nested": {"tts_audio": "abc123", "safe": "ok"},
    }

    sanitized = trace.sanitize_for_report(payload)
    encoded = json.dumps(sanitized)

    assert "sk-proj" not in encoded
    assert "Bearer abc" not in encoded
    assert "raw-audio" not in encoded
    assert "tts_audio" in encoded
    assert "ok" in encoded


def test_health_exposes_safe_runtime_identity_for_trace(temp_config) -> None:
    with TestClient(create_app(temp_config)) as client:
        payload = client.get("/health").json()

    identity = payload["runtime_identity"]
    assert identity["pid"] > 0
    assert identity["python_executable"]
    assert identity["working_directory"]
    assert identity["project_root"] == str(temp_config.project_root)
    assert "api_key" not in json.dumps(identity).lower()
