from __future__ import annotations

import asyncio
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoiceVADConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.providers import MockCaptureProvider
from stormhelm.core.voice.providers import MockVADProvider
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


def _voice_config(**vad_overrides: Any) -> VoiceConfig:
    vad_values = {
        "enabled": True,
        "provider": "mock",
        "allow_dev_vad": True,
        "silence_ms": 900,
        "auto_finalize_capture": True,
    }
    vad_values.update(vad_overrides)
    return VoiceConfig(
        enabled=True,
        mode="manual",
        debug_mock_provider=True,
        openai=VoiceOpenAIConfig(max_audio_bytes=128, max_audio_seconds=4),
        capture=VoiceCaptureConfig(
            enabled=True,
            provider="mock",
            device="test-mic",
            max_duration_ms=4000,
            max_audio_bytes=128,
            allow_dev_capture=True,
        ),
        vad=VoiceVADConfig(**vad_values),
    )


def _service(*, events: EventBuffer | None = None, **vad_overrides: Any):
    service = build_voice_subsystem(
        _voice_config(**vad_overrides), _openai_config(), events=events
    )
    service.capture_provider = MockCaptureProvider(
        capture_audio_bytes=b"captured voice",
        duration_ms=900,
    )
    service.vad_provider = MockVADProvider(config=service.config.vad)
    service.attach_core_bridge(RecordingCoreBridge())
    return service


def test_vad_readiness_distinguishes_disabled_ready_and_active() -> None:
    disabled = build_voice_subsystem(_voice_config(enabled=False), _openai_config())
    disabled_report = disabled.vad_readiness_report().to_dict()

    assert disabled_report["vad_enabled"] is False
    assert disabled_report["vad_available"] is False
    assert disabled_report["vad_active"] is False
    assert disabled_report["blocking_reasons"] == ["vad_disabled"]
    assert disabled_report["semantic_completion_claimed"] is False
    assert disabled_report["command_authority"] is False
    assert disabled_report["realtime_vad"] is False

    service = _service()
    ready = service.vad_readiness_report().to_dict()
    capture = asyncio.run(
        service.start_push_to_talk_capture(session_id="voice-session")
    )
    active = service.vad_readiness_report().to_dict()

    assert ready["vad_available"] is True
    assert ready["vad_active"] is False
    assert capture.status == "recording"
    assert active["vad_active"] is True
    assert active["active_capture_id"] == capture.capture_id
    assert active["warnings"] == ["mock_vad_provider_active"]


def test_vad_speech_events_finalize_capture_without_routing_core() -> None:
    events = EventBuffer(capacity=64)
    service = _service(events=events)

    capture = asyncio.run(
        service.start_push_to_talk_capture(session_id="voice-session")
    )
    started = asyncio.run(
        service.simulate_speech_started(capture_id=capture.capture_id)
    )
    stopped = asyncio.run(
        service.simulate_speech_stopped(capture_id=capture.capture_id)
    )

    assert started.status == "speech_started"
    assert stopped.status == "speech_stopped"
    assert stopped.semantic_completion_claimed is False
    assert stopped.command_intent_claimed is False
    assert service.last_capture_result is not None
    assert service.last_capture_result.status == "completed"
    assert service.last_capture_result.stop_reason == "vad_silence_timeout"
    assert service.last_audio_turn_result is None
    assert service.last_transcription_result is None
    assert service.core_bridge.calls == []

    emitted = [record["event_type"] for record in events.recent()]
    assert "voice.vad_detection_started" in emitted
    assert "voice.speech_activity_started" in emitted
    assert "voice.speech_activity_stopped" in emitted
    assert "voice.vad_detection_stopped" in emitted
    assert "voice.core_request_started" not in emitted
    assert "voice.transcription_started" not in emitted
    assert "voice.wake_detected" not in emitted


def test_vad_stops_when_capture_is_cancelled_and_manual_stop_still_works() -> None:
    service = _service(auto_finalize_capture=False)
    capture = asyncio.run(
        service.start_push_to_talk_capture(session_id="voice-session")
    )
    cancelled = asyncio.run(service.cancel_capture(capture.capture_id))

    assert cancelled.status == "cancelled"
    assert service.get_active_vad_session() is None

    second = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    stopped = asyncio.run(service.stop_push_to_talk_capture(second.capture_id))

    assert stopped.status == "completed"
    assert stopped.stop_reason == "user_released"
    assert service.get_active_vad_session() is None


def test_vad_status_snapshot_redacts_audio_and_preserves_truth_flags() -> None:
    service = _service()
    capture = asyncio.run(
        service.start_push_to_talk_capture(session_id="voice-session")
    )
    asyncio.run(service.simulate_speech_started(capture_id=capture.capture_id))

    snapshot = service.status_snapshot()
    vad = snapshot["vad"]

    assert vad["enabled"] is True
    assert vad["provider"] == "mock"
    assert vad["available"] is True
    assert vad["active"] is True
    assert vad["active_capture_id"] == capture.capture_id
    assert vad["last_activity_event"]["status"] == "speech_started"
    assert vad["semantic_completion_claimed"] is False
    assert vad["command_authority"] is False
    assert vad["realtime_vad"] is False
    assert "raw_audio" not in str(vad).lower()
    assert "captured voice" not in str(vad).lower()
