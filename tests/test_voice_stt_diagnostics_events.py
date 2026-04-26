from __future__ import annotations

import asyncio

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.models import VoiceAudioInput
from stormhelm.core.voice.providers import MockVoiceProvider
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


def _service(events: EventBuffer | None = None):
    service = build_voice_subsystem(
        VoiceConfig(
            enabled=True,
            mode="manual",
            spoken_responses_enabled=True,
            debug_mock_provider=True,
            openai=VoiceOpenAIConfig(max_audio_bytes=1024, max_audio_seconds=10),
        ),
        _openai_config(),
        events=events,
    )
    service.provider = MockVoiceProvider(stt_transcript="2 plus 2", stt_confidence=0.88)
    service.attach_core_bridge(
        RecordingCoreBridge(
            result_state="completed",
            route_family="calculations",
            subsystem="calculations",
            spoken_summary="Core reports the calculation completed.",
            visual_summary="4",
        )
    )
    return service


def test_stt_status_snapshot_reports_last_transcription_without_raw_audio() -> None:
    service = _service()
    audio = VoiceAudioInput.from_bytes(
        b"raw audio should stay transient",
        filename="math.wav",
        mime_type="audio/wav",
        duration_ms=800,
    )

    result = asyncio.run(service.submit_audio_voice_turn(audio, session_id="voice-session"))
    snapshot = service.status_snapshot()

    assert result.ok is True
    assert snapshot["current_phase"] == "voice5"
    assert snapshot["stt"]["enabled"] is True
    assert snapshot["stt"]["provider"] == "mock"
    assert snapshot["stt"]["model"] == "mock-stt"
    assert snapshot["stt"]["last_transcription_id"] == result.transcription_result.transcription_id
    assert snapshot["stt"]["last_transcription_state"] == "completed"
    assert snapshot["stt"]["last_transcript_preview"] == "2 plus 2"
    assert snapshot["stt"]["last_audio_input_metadata"]["filename"] == "math.wav"
    assert snapshot["stt"]["last_audio_input_metadata"]["source"] == "bytes"
    assert snapshot["stt"]["last_openai_call_attempted"] is False
    assert snapshot["runtime_truth"]["controlled_audio_file_or_blob_only"] is True
    assert snapshot["runtime_truth"]["no_microphone_capture"] is True
    assert snapshot["runtime_truth"]["controlled_tts_audio_artifacts_only"] is True
    assert snapshot["runtime_truth"]["no_live_tts"] is True
    assert snapshot["runtime_truth"]["no_audio_playback"] is True
    assert snapshot["runtime_truth"]["no_realtime"] is True
    assert "raw audio should stay transient" not in str(snapshot)
    assert "data" not in snapshot["stt"]["last_audio_input_metadata"]


def test_stt_events_are_recorded_without_fake_audio_runtime_events() -> None:
    events = EventBuffer(capacity=64)
    service = _service(events=events)
    audio = VoiceAudioInput.from_bytes(b"fake wav bytes", filename="math.wav", mime_type="audio/wav")

    result = asyncio.run(service.submit_audio_voice_turn(audio, session_id="voice-session"))
    recent = events.recent(limit=64)
    event_types = [event["event_type"] for event in recent]

    assert result.ok is True
    assert "voice.audio_input_received" in event_types
    assert "voice.transcription_started" in event_types
    assert "voice.transcription_completed" in event_types
    assert "voice.core_request_started" in event_types
    assert "voice.core_request_completed" in event_types
    assert "voice.spoken_response_prepared" in event_types
    assert "voice.turn_completed" in event_types
    assert "voice.manual_turn_received" not in event_types
    assert "voice.wake_detected" not in event_types
    assert "voice.speech_started" not in event_types
    assert "voice.speech_stopped" not in event_types
    assert "voice.speaking_started" not in event_types

    transcription = next(event for event in recent if event["event_type"] == "voice.transcription_completed")
    assert transcription["payload"]["input_id"] == audio.input_id
    assert transcription["payload"]["transcription_id"] == result.transcription_result.transcription_id
    assert transcription["payload"]["provider"] == "mock"
    assert transcription["payload"]["model"] == "mock-stt"
    assert "fake wav bytes" not in str(transcription["payload"])


def test_audio_validation_failure_event_keeps_audio_private() -> None:
    events = EventBuffer(capacity=16)
    service = _service(events=events)
    audio = VoiceAudioInput.from_bytes(b"private bytes", filename="note.txt", mime_type="text/plain")

    result = asyncio.run(service.submit_audio_voice_turn(audio, session_id="voice-session"))
    recent = events.recent(limit=16)

    assert result.ok is False
    assert result.error_code == "unsupported_audio_type"
    assert "voice.audio_validation_failed" in [event["event_type"] for event in recent]
    failed = next(event for event in recent if event["event_type"] == "voice.audio_validation_failed")
    assert failed["payload"]["input_id"] == audio.input_id
    assert failed["payload"]["error_code"] == "unsupported_audio_type"
    assert "private bytes" not in str(failed["payload"])
