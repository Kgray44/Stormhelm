from __future__ import annotations

import asyncio

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.providers import MockCaptureProvider
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
            capture=VoiceCaptureConfig(
                enabled=True,
                provider="mock",
                device="test-mic",
                max_duration_ms=3000,
                max_audio_bytes=1024,
                allow_dev_capture=True,
            ),
        ),
        _openai_config(),
        events=events,
    )
    service.provider = MockVoiceProvider(stt_transcript="open downloads", stt_confidence=0.9)
    service.capture_provider = MockCaptureProvider(capture_audio_bytes=b"private captured bytes", duration_ms=700)
    service.attach_core_bridge(RecordingCoreBridge(route_family="desktop_search", subsystem="desktop_search"))
    return service


def test_capture_status_snapshot_reports_active_and_last_capture_without_raw_audio() -> None:
    service = _service()

    session = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    active = service.status_snapshot()
    capture = asyncio.run(service.stop_push_to_talk_capture(session.capture_id, reason="user_released"))
    stopped = service.status_snapshot()

    assert active["current_phase"] == "voice5"
    assert active["capture"]["enabled"] is True
    assert active["capture"]["provider"] == "mock"
    assert active["capture"]["available"] is True
    assert active["capture"]["mode"] == "push_to_talk"
    assert active["capture"]["active_capture_id"] == session.capture_id
    assert active["capture"]["active_capture_status"] == "recording"
    assert stopped["capture"]["last_capture_request_id"] == capture.capture_request_id
    assert stopped["capture"]["last_capture_id"] == capture.capture_id
    assert stopped["capture"]["last_capture_status"] == "completed"
    assert stopped["capture"]["last_capture_duration_ms"] == 700
    assert stopped["capture"]["last_capture_audio_input_metadata"]["input_id"] == capture.audio_input.input_id
    assert stopped["capture"]["always_listening"] is False
    assert stopped["capture"]["no_wake_word"] is True
    assert stopped["capture"]["no_vad"] is True
    assert stopped["capture"]["no_realtime"] is True
    assert stopped["runtime_truth"]["controlled_push_to_talk_capture_boundary"] is True
    assert stopped["runtime_truth"]["always_listening"] is False
    assert "private captured bytes" not in str(stopped)
    assert "data" not in stopped["capture"]["last_capture_audio_input_metadata"]


def test_capture_events_are_recorded_without_fake_wake_vad_or_realtime_events() -> None:
    events = EventBuffer(capacity=64)
    service = _service(events=events)

    session = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    capture = asyncio.run(service.stop_push_to_talk_capture(session.capture_id, reason="user_released"))
    asyncio.run(service.submit_captured_audio_turn(capture, session_id="voice-session"))
    recent = events.recent(limit=64)
    event_types = [event["event_type"] for event in recent]

    assert "voice.capture_request_created" in event_types
    assert "voice.capture_started" in event_types
    assert "voice.capture_stopped" in event_types
    assert "voice.capture_audio_created" in event_types
    assert "voice.audio_input_received" in event_types
    assert "voice.transcription_started" in event_types
    assert "voice.core_request_started" in event_types
    assert "voice.wake_detected" not in event_types
    assert "voice.speech_started" not in event_types
    assert "voice.speech_stopped" not in event_types
    assert "voice.listening_started" not in event_types

    stopped = next(event for event in recent if event["event_type"] == "voice.capture_stopped")
    assert stopped["payload"]["capture_id"] == capture.capture_id
    assert stopped["payload"]["capture_request_id"] == capture.capture_request_id
    assert stopped["payload"]["device"] == "test-mic"
    assert stopped["payload"]["status"] == "completed"
    assert stopped["payload"]["duration_ms"] == 700
    assert "private captured bytes" not in str(stopped["payload"])
