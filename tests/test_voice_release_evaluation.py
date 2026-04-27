from __future__ import annotations

from stormhelm.core.voice.evaluation import VoiceReleaseScenario
from stormhelm.core.voice.evaluation import default_voice_release_scenarios
from stormhelm.core.voice.evaluation import run_voice_release_scenario
from stormhelm.core.voice.evaluation import run_voice_release_suite


def test_voice20_default_release_suite_covers_required_voice_paths() -> None:
    scenarios = default_voice_release_scenarios()

    scenario_ids = {scenario.scenario_id for scenario in scenarios}
    assert {
        "push_to_talk_happy_path",
        "wake_driven_happy_path",
        "realtime_transcription_bridge",
        "realtime_speech_core_bridge",
        "spoken_confirmation",
        "interruption_stop_talking",
        "correction_routed",
        "core_blocked",
        "attempted_not_verified",
        "playback_failure",
        "stt_failure",
        "empty_transcript",
        "provider_unavailable",
        "privacy_redaction",
        "realtime_authority_boundary",
    }.issubset(scenario_ids)

    results = run_voice_release_suite(scenarios)

    assert all(result.passed for result in results)
    assert all(result.latency_breakdown["total_ms"] >= 0 for result in results)
    assert all(result.expected_privacy_flags["no_raw_audio"] is True for result in results)
    assert all(result.expected_privacy_flags["no_secrets"] is True for result in results)
    assert all(not result.redaction_findings for result in results)
    assert all(not result.ui_payload_findings for result in results)


def test_voice20_blocked_and_attempted_not_verified_scenarios_do_not_overclaim() -> None:
    blocked = run_voice_release_scenario(
        VoiceReleaseScenario(
            scenario_id="blocked-check",
            name="Blocked result",
            phase_coverage=("voice19", "voice20"),
            entrypoint="realtime_speech",
            expected_stages=("realtime", "core_bridge", "response_gate"),
            expected_final_status="blocked",
            expected_result_state="blocked",
            core_result_state="blocked",
            spoken_response="Core blocked that request.",
        )
    )
    attempted = run_voice_release_scenario(
        VoiceReleaseScenario(
            scenario_id="attempted-check",
            name="Attempted but unverified",
            phase_coverage=("voice19", "voice20"),
            entrypoint="realtime_speech",
            expected_stages=("realtime", "core_bridge", "response_gate"),
            expected_final_status="attempted_not_verified",
            expected_result_state="attempted_not_verified",
            expected_verification_posture="not_verified",
            core_result_state="attempted_not_verified",
            verification_posture="not_verified",
            spoken_response="Attempted, but not verified.",
        )
    )

    assert blocked.passed
    assert attempted.passed
    assert "done" not in str(blocked.ui_payload).lower()
    assert "verified" not in str(attempted.ui_payload).lower()
    assert blocked.result_state_findings == []
    assert attempted.result_state_findings == []


def test_voice20_release_scenario_reports_event_correlation_and_stage_truth() -> None:
    result = run_voice_release_scenario(
        VoiceReleaseScenario(
            scenario_id="correlation-check",
            name="Realtime speech correlation",
            phase_coverage=("voice18", "voice19", "voice20"),
            entrypoint="realtime_speech",
            expected_stages=("realtime", "core_bridge", "response_gate"),
            expected_final_status="completed",
            expected_result_state="completed",
            expected_event_sequence=(
                "voice.realtime_speech_session_started",
                "voice.realtime_core_bridge_call_started",
                "voice.realtime_core_bridge_call_completed",
                "voice.realtime_response_gated",
            ),
        )
    )

    assert result.passed
    assert result.event_trace
    assert all(event["session_id"] == result.session_id for event in result.event_trace)
    assert all(event["correlation_id"] == result.scenario_id for event in result.event_trace)
    assert result.event_trace[-1]["realtime_session_id"] == result.correlation_ids["realtime_session_id"]
    assert result.actual_stage_summary["core_result_state"] == "completed"
    assert result.actual_stage_summary["response_gate_status"] == "allowed"
