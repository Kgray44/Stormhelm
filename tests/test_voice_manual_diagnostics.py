from __future__ import annotations

import asyncio

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge


def _openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        enabled=True,
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model="gpt-5.4-nano",
        planner_model="gpt-5.4-nano",
        reasoning_model="gpt-5.4",
        timeout_seconds=60,
        max_tool_rounds=4,
        max_output_tokens=1200,
        planner_max_output_tokens=900,
        reasoning_max_output_tokens=1400,
        instructions="",
    )


def test_voice_status_snapshot_reports_last_manual_turn_truthfully() -> None:
    service = build_voice_subsystem(
        VoiceConfig(enabled=True, mode="manual", spoken_responses_enabled=True),
        _openai_config(),
    )
    service.attach_core_bridge(
        RecordingCoreBridge(
            result_state="completed",
            route_family="calculations",
            subsystem="calculations",
            spoken_summary="Core reports the calculation completed.",
            visual_summary="4",
        )
    )

    result = asyncio.run(
        service.submit_manual_voice_turn(
            "2 + 2 with a very long extra transcript tail that should be bounded in diagnostics",
            session_id="voice-session",
        )
    )
    snapshot = service.status_snapshot()

    assert result.ok is True
    assert snapshot["manual_turns"]["enabled"] is True
    assert snapshot["manual_turns"]["last_turn_id"] == result.turn.turn_id
    assert snapshot["manual_turns"]["last_transcript_preview"].endswith("...")
    assert snapshot["manual_turns"]["last_core_result_state"] == "completed"
    assert snapshot["manual_turns"]["last_route_family"] == "calculations"
    assert snapshot["manual_turns"]["last_subsystem"] == "calculations"
    assert snapshot["manual_turns"]["last_verification_posture"] == "not_verified"
    assert snapshot["manual_turns"]["last_spoken_response_candidate"]["should_speak"] is True
    assert snapshot["runtime_truth"]["no_real_audio"] is True
    assert snapshot["runtime_truth"]["no_live_stt"] is True
    assert snapshot["runtime_truth"]["controlled_audio_file_or_blob_only"] is True
    assert snapshot["runtime_truth"]["controlled_tts_audio_artifacts_only"] is True
    assert snapshot["runtime_truth"]["no_live_tts"] is True
    assert snapshot["runtime_truth"]["no_audio_playback"] is True
    assert snapshot["runtime_truth"]["no_realtime"] is True


def test_manual_voice_turn_events_are_recorded_without_audio_events() -> None:
    events = EventBuffer(capacity=64)
    service = build_voice_subsystem(
        VoiceConfig(enabled=True, mode="manual", spoken_responses_enabled=True),
        _openai_config(),
        events=events,
    )
    service.attach_core_bridge(RecordingCoreBridge(route_family="clock", subsystem="tools"))

    result = asyncio.run(service.submit_manual_voice_turn("what time is it?", session_id="voice-session"))
    event_types = [event["event_type"] for event in events.recent(limit=32)]

    assert result.ok is True
    assert "voice.manual_turn_received" in event_types
    assert "voice.core_request_started" in event_types
    assert "voice.core_request_completed" in event_types
    assert "voice.spoken_response_prepared" in event_types
    assert "voice.turn_completed" in event_types
    assert "voice.speech_started" not in event_types
    assert "voice.speech_stopped" not in event_types
    assert "voice.speaking_started" not in event_types
    assert "voice.transcription_started" not in event_types

    completed = next(event for event in events.recent(limit=32) if event["event_type"] == "voice.turn_completed")
    assert completed["payload"]["turn_id"] == result.turn.turn_id
    assert completed["payload"]["source"] == "manual_voice"
    assert completed["payload"]["result_state"] == "completed"
    assert completed["payload"]["route_family"] == "clock"


def test_spoken_responses_disabled_returns_preview_silent_and_never_invokes_tts() -> None:
    service = build_voice_subsystem(
        VoiceConfig(enabled=True, mode="manual", spoken_responses_enabled=False),
        _openai_config(),
    )
    service.attach_core_bridge(RecordingCoreBridge(spoken_summary="Bearing acquired."))

    result = asyncio.run(service.submit_manual_voice_turn("what time is it?", session_id="voice-session"))

    assert result.ok is True
    assert result.spoken_response.should_speak is False
    assert result.spoken_response.reason_if_not_speaking == "spoken_responses_disabled"
    assert result.tts_invoked is False
    assert result.audio_playback_started is False
