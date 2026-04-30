from __future__ import annotations

from stormhelm.core.latency_gates import (
    default_latency_lane_profiles,
    rows_for_lane,
)


def test_l10_native_hot_path_lane_excludes_provider_fallback_rows() -> None:
    lanes = default_latency_lane_profiles()
    rows = [
        {"test_id": "calc", "actual_route_family": "calculations", "provider_called": False, "l8_hot_path_name": "calculations_direct"},
        {"test_id": "provider", "actual_route_family": "generic_provider", "provider_called": True, "provider_total_ms": 2000},
    ]

    native_rows = rows_for_lane(rows, lanes["native_hot_path"])

    assert [row["test_id"] for row in native_rows] == ["calc"]


def test_l10_provider_lane_includes_provider_rows() -> None:
    lanes = default_latency_lane_profiles()
    rows = [
        {"test_id": "native", "actual_route_family": "calculations", "provider_called": False},
        {"test_id": "provider", "actual_route_family": "generic_provider", "provider_called": True},
    ]

    provider_rows = rows_for_lane(rows, lanes["provider_fallback"])

    assert [row["test_id"] for row in provider_rows] == ["provider"]


def test_l10_async_ack_lane_uses_initial_feedback_not_full_completion() -> None:
    lanes = default_latency_lane_profiles()
    row = {
        "test_id": "async",
        "actual_route_family": "software_control",
        "async_continuation": True,
        "async_initial_response_returned": True,
        "first_feedback_ms": 350,
        "total_latency_ms": 9000,
    }

    async_rows = rows_for_lane([row], lanes["async_long_task_ack"])

    assert async_rows[0]["first_feedback_ms"] == 350
    assert async_rows[0]["total_latency_ms"] == 9000


def test_l10_ui_render_lane_keeps_unknown_when_unavailable() -> None:
    lanes = default_latency_lane_profiles()
    row = {
        "test_id": "ui",
        "ui_bridge_apply_ms": 12,
        "ui_render_visible_ms": None,
        "ui_render_visible_status": "unknown",
    }

    ui_rows = rows_for_lane([row], lanes["ui_render_visible"])

    assert ui_rows[0]["ui_render_visible_status"] == "unknown"


def test_l10_voice_mock_lane_reports_first_audio_rows() -> None:
    lanes = default_latency_lane_profiles()
    row = {
        "test_id": "voice",
        "actual_route_family": "voice_control",
        "voice_first_audio_ms": 900,
        "voice_user_heard_claimed": False,
    }

    voice_rows = rows_for_lane([row], lanes["voice_mock_first_audio"])

    assert voice_rows == [row]
