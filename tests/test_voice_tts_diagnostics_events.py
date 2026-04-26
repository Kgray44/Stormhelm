from __future__ import annotations

import asyncio

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem


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


def test_tts_status_snapshot_reports_last_synthesis_without_audio_bytes() -> None:
    service = build_voice_subsystem(
        VoiceConfig(
            enabled=True,
            mode="manual",
            spoken_responses_enabled=True,
            openai=VoiceOpenAIConfig(tts_model="gpt-4o-mini-tts", tts_voice="cedar", tts_format="mp3"),
        ),
        _openai_config(),
    )
    service.provider = MockVoiceProvider(tts_audio_bytes=b"private synthesized bytes")

    synthesis = asyncio.run(service.synthesize_speech_text("Bearing acquired.", source="manual_test", session_id="voice-session"))
    snapshot = service.status_snapshot()

    assert synthesis.ok is True
    assert snapshot["current_phase"] == "voice4"
    assert snapshot["tts"]["enabled"] is True
    assert snapshot["tts"]["spoken_responses_enabled"] is True
    assert snapshot["tts"]["provider"] == "mock"
    assert snapshot["tts"]["model"] == "mock-tts"
    assert snapshot["tts"]["voice"] == "mock-voice"
    assert snapshot["tts"]["format"] == "mp3"
    assert snapshot["tts"]["last_speech_request_id"] == synthesis.speech_request.speech_request_id
    assert snapshot["tts"]["last_synthesis_id"] == synthesis.synthesis_id
    assert snapshot["tts"]["last_synthesis_state"] == "succeeded"
    assert snapshot["tts"]["last_spoken_text_preview"] == "Bearing acquired."
    assert snapshot["tts"]["last_audio_output_metadata"]["size_bytes"] == len(b"private synthesized bytes")
    assert snapshot["tts"]["playback_available"] is False
    assert snapshot["runtime_truth"]["no_audio_playback"] is True
    assert snapshot["runtime_truth"]["no_live_conversation_loop"] is True
    assert "private synthesized bytes" not in str(snapshot)


def test_tts_events_are_recorded_without_fake_playback_or_microphone_events() -> None:
    events = EventBuffer(capacity=64)
    service = build_voice_subsystem(
        VoiceConfig(enabled=True, mode="manual", spoken_responses_enabled=True),
        _openai_config(),
        events=events,
    )
    service.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")

    synthesis = asyncio.run(service.synthesize_speech_text("Bearing acquired.", source="manual_test", session_id="voice-session"))
    recent = events.recent(limit=64)
    event_types = [event["event_type"] for event in recent]

    assert synthesis.ok is True
    assert "voice.speech_request_created" in event_types
    assert "voice.synthesis_started" in event_types
    assert "voice.synthesis_completed" in event_types
    assert "voice.audio_output_created" in event_types
    assert "voice.speaking_started" not in event_types
    assert "voice.speaking_completed" not in event_types
    assert "voice.speech_started" not in event_types
    assert "voice.wake_detected" not in event_types

    completed = next(event for event in recent if event["event_type"] == "voice.synthesis_completed")
    assert completed["payload"]["speech_request_id"] == synthesis.speech_request.speech_request_id
    assert completed["payload"]["synthesis_id"] == synthesis.synthesis_id
    assert completed["payload"]["audio_output_id"] == synthesis.audio_output.output_id
    assert completed["payload"]["voice"] == "mock-voice"
    assert completed["payload"]["format"] == "mp3"
    assert "voice bytes" not in str(completed["payload"])


def test_tts_block_and_failure_events_are_truthful() -> None:
    events = EventBuffer(capacity=64)
    service = build_voice_subsystem(
        VoiceConfig(enabled=True, mode="manual", spoken_responses_enabled=True),
        _openai_config(),
        events=events,
    )
    service.provider = MockVoiceProvider(tts_error_code="provider_unavailable", tts_error_message="provider offline")

    blocked = asyncio.run(service.synthesize_speech_text("", source="manual_test", session_id="voice-session"))
    failed = asyncio.run(service.synthesize_speech_text("Bearing acquired.", source="manual_test", session_id="voice-session"))
    event_types = [event["event_type"] for event in events.recent(limit=64)]

    assert blocked.ok is False
    assert blocked.error_code == "empty_speech_text"
    assert failed.ok is False
    assert failed.error_code == "provider_unavailable"
    assert "voice.speech_request_blocked" in event_types
    assert "voice.synthesis_failed" in event_types
