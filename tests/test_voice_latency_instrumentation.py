from __future__ import annotations

from stormhelm.core.voice.evaluation import VoiceLatencyBreakdown
from stormhelm.core.voice.evaluation import VoiceReleaseScenario
from stormhelm.core.voice.evaluation import run_voice_release_scenario


def test_voice_latency_breakdown_uses_fake_clock_marks() -> None:
    breakdown = VoiceLatencyBreakdown.from_marks(
        {
            "wake": 0,
            "ghost": 20,
            "listen_window": 35,
            "capture_start": 50,
            "capture_complete": 950,
            "stt_complete": 1200,
            "core_bridge_complete": 1350,
            "spoken_render_complete": 1380,
            "tts_complete": 1600,
            "playback_started": 1660,
            "realtime_response_gate_complete": 1700,
            "complete": 1800,
        },
        latency_budget_ms=2000,
        budget_label="release-smoke",
    )

    assert breakdown.wake_ms == 20
    assert breakdown.listen_window_ms == 15
    assert breakdown.capture_ms == 900
    assert breakdown.stt_ms == 250
    assert breakdown.core_bridge_ms == 150
    assert breakdown.tts_ms == 220
    assert breakdown.playback_start_ms == 60
    assert breakdown.realtime_response_gate_ms == 40
    assert breakdown.total_ms == 1800
    assert breakdown.exceeded_budget is False
    assert breakdown.budget_label == "release-smoke"


def test_voice_release_scenario_marks_latency_budget_exceeded_without_failing_truth() -> None:
    result = run_voice_release_scenario(
        VoiceReleaseScenario(
            scenario_id="latency-budget-check",
            name="Latency budget check",
            phase_coverage=("voice20",),
            entrypoint="wake_loop",
            expected_stages=("wake", "ghost", "listen_window", "capture", "stt", "core"),
            expected_final_status="completed",
            expected_result_state="completed",
            latency_budget_ms=10,
        )
    )

    assert result.passed
    assert result.latency_breakdown["exceeded_budget"] is True
    assert result.latency_breakdown["budget_label"] == "latency-budget-check"
    assert result.notes
