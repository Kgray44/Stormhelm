from __future__ import annotations

from stormhelm.core.latency_gates import build_latency_gate_report


def test_l10_ui_bridge_model_timing_reported_and_render_unknown_preserved() -> None:
    report = build_latency_gate_report(
        [
            {
                "test_id": "ui",
                "ui_bridge_apply_ms": 11,
                "ui_model_notify_ms": 8,
                "ui_render_visible_ms": None,
                "ui_render_visible_status": "unknown",
            }
        ],
        profile="ui_profile",
    )

    ui = report["ui_perceived_latency_metrics"]
    assert ui["ui_bridge_apply_ms"]["p95"] == 11
    assert ui["ui_model_notify_ms"]["p95"] == 8
    assert ui["ui_render_visible_status"] == "unknown"


def test_l10_fake_render_confirmed_timing_fails() -> None:
    report = build_latency_gate_report(
        [
            {
                "test_id": "ui-fake",
                "ui_render_visible_ms": 25,
                "ui_render_visible_status": "confirmed",
                "render_confirmation_source": "",
            }
        ],
        profile="ui_profile",
    )

    assert report["release_posture"]["posture"] == "blocked_missing_required_metrics"
    assert report["ui_perceived_latency_metrics"]["fake_render_confirmed_count"] == 1


def test_l10_voice_mock_first_audio_p95_computed_without_user_heard_claim() -> None:
    report = build_latency_gate_report(
        [
            {"test_id": "voice-1", "actual_route_family": "voice_control", "voice_first_audio_ms": 900, "voice_user_heard_claimed": False},
            {"test_id": "voice-2", "actual_route_family": "voice_control", "voice_first_audio_ms": 1100, "voice_user_heard_claimed": False},
        ],
        profile="voice_profile",
    )

    voice = report["voice_first_audio_metrics"]
    assert voice["voice_first_audio_ms"]["p95"] == 1090
    assert voice["voice_user_heard_claimed_count"] == 0


def test_l10_voice_stage_truth_not_collapsed() -> None:
    report = build_latency_gate_report(
        [
            {
                "test_id": "voice-stage",
                "actual_route_family": "voice_control",
                "voice_tts_first_chunk_ms": 200,
                "voice_playback_start_ms": 400,
                "voice_first_chunk_before_complete": True,
                "voice_user_heard_claimed": False,
            }
        ],
        profile="voice_profile",
    )

    voice = report["voice_first_audio_metrics"]
    assert voice["tts_started_as_playback_started_count"] == 0
    assert voice["voice_user_heard_claimed_count"] == 0
