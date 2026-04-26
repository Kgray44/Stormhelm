from __future__ import annotations

from stormhelm.core.voice.evaluation import VoicePipelineExpectedResult
from stormhelm.core.voice.evaluation import VoicePipelineScenario
from stormhelm.core.voice.evaluation import run_voice_pipeline_scenario
from stormhelm.core.voice.evaluation import run_voice_pipeline_suite


def test_voice_pipeline_happy_path_preserves_stage_truth_and_event_order() -> None:
    result = run_voice_pipeline_scenario(
        VoicePipelineScenario(
            scenario_id="happy-path",
            transcript="what time is it?",
            core_result_state="completed",
            core_spoken_summary="The time is 10:15.",
            synthesize_response=True,
            play_response=True,
        )
    )

    assert result.ok is True
    assert result.final_status == "completed"
    assert result.stopped_stage is None
    assert result.stage_results["capture"]["status"] == "completed"
    assert result.stage_results["stt"]["status"] == "completed"
    assert result.stage_results["core"]["result_state"] == "completed"
    assert result.stage_results["tts"]["status"] == "succeeded"
    assert result.stage_results["playback"]["status"] == "completed"
    assert result.pipeline_summary["last_successful_stage"] == "playback"
    assert result.pipeline_summary["user_heard_claimed"] is False
    assert result.pipeline_summary["truth_flags"]["no_wake_word"] is True
    assert result.pipeline_summary["truth_flags"]["no_vad"] is True
    assert result.pipeline_summary["truth_flags"]["no_realtime"] is True

    event_types = [event["event_type"] for event in result.events]
    expected_order = [
        "voice.capture_started",
        "voice.capture_stopped",
        "voice.capture_audio_created",
        "voice.audio_input_received",
        "voice.transcription_started",
        "voice.transcription_completed",
        "voice.core_request_started",
        "voice.core_request_completed",
        "voice.spoken_response_prepared",
        "voice.synthesis_started",
        "voice.synthesis_completed",
        "voice.audio_output_created",
        "voice.playback_started",
        "voice.playback_completed",
    ]
    assert event_types == expected_order
    assert {event["correlation_id"] for event in result.events} == {result.pipeline_id}
    assert (
        result.stage_results["capture"]["audio_input_id"]
        == result.stage_results["stt"]["input_id"]
    )
    assert (
        result.stage_results["stt"]["transcription_id"]
        == result.stage_results["core"]["transcription_id"]
    )
    assert (
        result.stage_results["tts"]["synthesis_id"]
        == result.stage_results["playback"]["synthesis_id"]
    )
    assert "fake wav bytes" not in str(result.to_dict())
    assert "mock audio" not in str(result.to_dict())


def test_voice_pipeline_capture_cancelled_stops_without_downstream_stages() -> None:
    result = run_voice_pipeline_scenario(
        VoicePipelineScenario(scenario_id="cancelled", capture_status="cancelled")
    )

    assert result.ok is False
    assert result.final_status == "cancelled"
    assert result.stopped_stage == "capture"
    assert result.stage_results["capture"]["status"] == "cancelled"
    assert result.stage_results["stt"]["status"] == "skipped"
    assert result.stage_results["core"]["status"] == "skipped"
    assert result.stage_results["tts"]["status"] == "skipped"
    assert result.stage_results["playback"]["status"] == "skipped"
    assert [event["event_type"] for event in result.events] == [
        "voice.capture_started",
        "voice.capture_cancelled",
    ]
    assert result.ghost_payload["primary_label"] == "Capture cancelled."
    assert result.ghost_payload["voice_core_state"] == "idle"


def test_voice_pipeline_capture_timeout_preserves_timeout_without_false_completion() -> (
    None
):
    result = run_voice_pipeline_scenario(
        VoicePipelineScenario(scenario_id="timeout", capture_status="timeout")
    )

    assert result.ok is False
    assert result.final_status == "timeout"
    assert result.stopped_stage == "capture"
    assert result.stage_results["capture"]["status"] == "timeout"
    assert result.stage_results["core"]["status"] == "skipped"
    assert result.pipeline_summary["failed_stage"] == "capture"
    assert result.ghost_payload["primary_label"] == "Capture timeout."
    assert "Done" not in str(result.ghost_payload)


def test_voice_pipeline_stt_failure_and_empty_transcript_do_not_route_core() -> None:
    failed = run_voice_pipeline_scenario(
        VoicePipelineScenario(
            scenario_id="stt-failed",
            transcript="open downloads",
            stt_error_code="provider_unavailable",
        )
    )
    empty = run_voice_pipeline_scenario(
        VoicePipelineScenario(scenario_id="empty", transcript="")
    )

    assert failed.final_status == "failed"
    assert failed.stopped_stage == "stt"
    assert failed.stage_results["core"]["status"] == "skipped"
    assert failed.stage_results["tts"]["status"] == "skipped"
    assert failed.stage_results["playback"]["status"] == "skipped"
    assert failed.ghost_payload["primary_label"] == "Speech transcription failed."
    assert "heard" not in str(failed.ghost_payload).lower()
    assert "understood" not in str(failed.ghost_payload).lower()
    assert empty.final_status == "failed"
    assert empty.stopped_stage == "stt"
    assert empty.stage_results["stt"]["error_code"] == "empty_transcript"
    assert empty.stage_results["core"]["status"] == "skipped"


def test_voice_pipeline_core_clarification_confirmation_and_blocked_are_not_softened() -> (
    None
):
    clarification = run_voice_pipeline_scenario(
        VoicePipelineScenario(
            scenario_id="clarify",
            transcript="open it",
            core_result_state="clarification_required",
            core_spoken_summary="Clarification required. Which item should I use?",
            synthesize_response=True,
            play_response=False,
        )
    )
    confirmation = run_voice_pipeline_scenario(
        VoicePipelineScenario(
            scenario_id="confirm",
            transcript="close the browser",
            core_result_state="requires_confirmation",
            core_spoken_summary="Confirmation required before closing the browser.",
            synthesize_response=True,
            play_response=False,
        )
    )
    blocked = run_voice_pipeline_scenario(
        VoicePipelineScenario(
            scenario_id="blocked",
            transcript="delete everything",
            core_result_state="blocked",
            core_spoken_summary="Blocked by trust policy.",
            synthesize_response=True,
            play_response=False,
        )
    )

    assert (
        clarification.stage_results["core"]["result_state"] == "clarification_required"
    )
    assert (
        "Clarification required"
        in clarification.stage_results["spoken_response"]["spoken_text"]
    )
    assert confirmation.stage_results["core"]["result_state"] == "requires_confirmation"
    assert (
        "Confirmation required"
        in confirmation.stage_results["spoken_response"]["spoken_text"]
    )
    assert blocked.final_status == "blocked"
    assert blocked.stopped_stage == "core"
    assert blocked.stage_results["core"]["result_state"] == "blocked"
    assert blocked.stage_results["tts"]["status"] == "skipped"
    for payload in (clarification.to_dict(), confirmation.to_dict(), blocked.to_dict()):
        text = str(payload).lower()
        assert "all set" not in text
        assert "verified" not in text
        assert "done" not in text


def test_voice_pipeline_tts_disabled_and_tts_failure_do_not_attempt_playback() -> None:
    disabled = run_voice_pipeline_scenario(
        VoicePipelineScenario(
            scenario_id="tts-disabled",
            core_spoken_summary="Response prepared.",
            synthesize_response=True,
            spoken_responses_enabled=False,
            play_response=True,
        )
    )
    failed = run_voice_pipeline_scenario(
        VoicePipelineScenario(
            scenario_id="tts-failed",
            core_spoken_summary="Response prepared.",
            synthesize_response=True,
            tts_error_code="provider_unavailable",
            play_response=True,
        )
    )

    assert disabled.final_status == "response_ready_tts_blocked"
    assert disabled.stopped_stage == "tts"
    assert disabled.stage_results["core"]["result_state"] == "completed"
    assert disabled.stage_results["playback"]["status"] == "skipped"
    assert disabled.ghost_payload["primary_label"] == "Response prepared."
    assert failed.final_status == "response_ready_tts_failed"
    assert failed.stopped_stage == "tts"
    assert failed.stage_results["core"]["result_state"] == "completed"
    assert failed.stage_results["playback"]["status"] == "skipped"
    assert failed.ghost_payload["primary_label"] == "Speech synthesis failed."
    assert "spoke" not in str(failed.ghost_payload).lower()


def test_voice_pipeline_playback_unavailable_failure_and_stop_do_not_mutate_core_truth() -> (
    None
):
    unavailable = run_voice_pipeline_scenario(
        VoicePipelineScenario(
            scenario_id="playback-unavailable",
            synthesize_response=True,
            play_response=True,
            playback_enabled=False,
        )
    )
    failed = run_voice_pipeline_scenario(
        VoicePipelineScenario(
            scenario_id="playback-failed",
            synthesize_response=True,
            play_response=True,
            playback_error_code="device_unavailable",
        )
    )
    stopped = run_voice_pipeline_scenario(
        VoicePipelineScenario(
            scenario_id="playback-stopped",
            synthesize_response=True,
            play_response=True,
            playback_complete_immediately=False,
            stop_playback=True,
        )
    )

    assert unavailable.final_status == "response_audio_prepared_playback_blocked"
    assert unavailable.stage_results["core"]["result_state"] == "completed"
    assert unavailable.stage_results["playback"]["error_code"] == "playback_disabled"
    assert failed.final_status == "response_audio_prepared_playback_failed"
    assert failed.stage_results["core"]["result_state"] == "completed"
    assert failed.pipeline_summary["failed_stage"] == "playback"
    assert stopped.final_status == "playback_stopped"
    assert stopped.stage_results["playback"]["status"] == "stopped"
    assert stopped.stage_results["core"]["result_state"] == "completed"
    assert stopped.pipeline_summary["core_result_state"] == "completed"
    assert stopped.pipeline_summary["user_heard_claimed"] is False


def test_voice_pipeline_suite_reports_expected_vs_actual_without_generic_success() -> (
    None
):
    results = run_voice_pipeline_suite(
        [
            VoicePipelineScenario(
                scenario_id="expected-pass",
                expected=VoicePipelineExpectedResult(
                    final_status="completed",
                    stopped_stage=None,
                    core_result_state="completed",
                    playback_status="completed",
                ),
                synthesize_response=True,
                play_response=True,
            ),
            VoicePipelineScenario(
                scenario_id="expected-fail",
                capture_status="cancelled",
                expected=VoicePipelineExpectedResult(
                    final_status="completed",
                    stopped_stage=None,
                ),
            ),
        ]
    )

    assert len(results) == 2
    assert results[0].passed is True
    assert results[0].expectation_mismatches == []
    assert results[1].passed is False
    assert (
        "final_status expected completed got cancelled"
        in results[1].expectation_mismatches
    )
    assert results[1].final_status == "cancelled"
