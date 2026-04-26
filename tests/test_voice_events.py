from __future__ import annotations

from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.events import VoiceEventType
from stormhelm.core.voice.events import build_voice_event_payload
from stormhelm.core.voice.events import publish_voice_event


def test_voice_event_taxonomy_contains_voice0_and_future_event_names() -> None:
    event_values = {event.value for event in VoiceEventType}

    assert "voice.availability_changed" in event_values
    assert "voice.state_changed" in event_values
    assert "voice.audio_input_received" in event_values
    assert "voice.audio_validation_failed" in event_values
    assert "voice.wake_detected" in event_values
    assert "voice.listening_started" in event_values
    assert "voice.transcription_completed" in event_values
    assert "voice.transcription_failed" in event_values
    assert "voice.core_request_started" in event_values
    assert "voice.speaking_completed" in event_values
    assert "voice.error" in event_values


def test_voice_event_payload_keeps_session_turn_provider_and_privacy_fields() -> None:
    payload = build_voice_event_payload(
        event_type=VoiceEventType.STATE_CHANGED,
        session_id="voice-session",
        turn_id="turn-1",
        provider="openai",
        mode="manual",
        state="listening",
        privacy={"cloud_audio_before_wake": False},
    )

    assert payload["event_type"] == "voice.state_changed"
    assert payload["session_id"] == "voice-session"
    assert payload["turn_id"] == "turn-1"
    assert payload["provider"] == "openai"
    assert payload["privacy"]["cloud_audio_before_wake"] is False


def test_publish_voice_event_uses_voice_event_family() -> None:
    events = EventBuffer(capacity=8)

    record = publish_voice_event(
        events,
        VoiceEventType.AVAILABILITY_CHANGED,
        message="Voice availability changed.",
        session_id="default",
        provider="openai",
        state="unavailable",
    )

    assert record.event_family == "voice"
    assert record.event_type == "voice.availability_changed"
    assert record.subsystem == "voice"
    assert record.payload["provider"] == "openai"
