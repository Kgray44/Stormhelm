from __future__ import annotations

import asyncio
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.models import VoiceAudioInput
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge


def _openai_config(*, enabled: bool = True, api_key: str | None = "test-key") -> OpenAIConfig:
    return OpenAIConfig(
        enabled=enabled,
        api_key=api_key,
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


def _voice_config(**overrides: Any) -> VoiceConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "mode": "manual",
        "manual_input_enabled": True,
        "spoken_responses_enabled": True,
        "debug_mock_provider": True,
        "openai": VoiceOpenAIConfig(max_audio_bytes=128, max_audio_seconds=4),
    }
    values.update(overrides)
    return VoiceConfig(**values)


def _audio(data: bytes = b"fake wav bytes", *, mime_type: str = "audio/wav", duration_ms: int | None = 1200) -> VoiceAudioInput:
    return VoiceAudioInput.from_bytes(data, filename="voice-turn.wav", mime_type=mime_type, duration_ms=duration_ms)


def test_submit_audio_voice_turn_transcribes_then_reuses_core_bridge() -> None:
    events = EventBuffer(capacity=64)
    service = build_voice_subsystem(_voice_config(), _openai_config(), events=events)
    service.provider = MockVoiceProvider(stt_transcript="what time is it?", stt_confidence=0.91)
    bridge = RecordingCoreBridge(route_family="clock", subsystem="tools", spoken_summary="The time is 10:15.")
    service.attach_core_bridge(bridge)

    result = asyncio.run(service.submit_audio_voice_turn(_audio(), mode="ghost", session_id="voice-session"))

    assert result.ok is True
    assert result.turn is not None
    assert result.turn.source == "mock_stt"
    assert result.turn.transcript == "what time is it?"
    assert result.turn.transcription_provider == "mock"
    assert result.turn.transcription_model == "mock-stt"
    assert result.turn.transcription_id == result.transcription_result.transcription_id
    assert result.turn.core_bridge_required is True
    assert result.core_request is not None
    assert result.core_request.voice_mode == "stt"
    assert result.core_result is not None
    assert result.core_result.route_family == "clock"
    assert result.core_result.subsystem == "tools"
    assert result.spoken_response is not None
    assert result.spoken_response.spoken_text == "The time is 10:15."
    assert result.stt_invoked is True
    assert result.tts_invoked is False
    assert result.audio_playback_started is False
    assert [state["state"] for state in result.state_transitions] == [
        "dormant",
        "transcribing",
        "core_routing",
        "thinking",
        "speaking_ready",
        "dormant",
    ]
    assert bridge.calls[0]["message"] == "what time is it?"
    assert bridge.calls[0]["input_context"]["source"] == "mock_stt"
    assert bridge.calls[0]["input_context"]["voice"]["voice_mode"] == "stt"
    assert bridge.calls[0]["input_context"]["voice"]["transcription"]["provider"] == "mock"
    assert bridge.calls[0]["input_context"]["controlled_audio_transcript"] is True


def test_audio_voice_turn_blocks_disabled_voice_before_provider_call() -> None:
    service = build_voice_subsystem(VoiceConfig(enabled=False), _openai_config())
    service.provider = MockVoiceProvider(stt_transcript="what time is it?")
    service.attach_core_bridge(RecordingCoreBridge())

    result = asyncio.run(service.submit_audio_voice_turn(_audio(), session_id="voice-session"))

    assert result.ok is False
    assert result.error_code == "voice_disabled"
    assert result.stt_invoked is False
    assert result.provider_network_call_count == 0


def test_audio_voice_turn_blocks_openai_unavailable_without_mock_override() -> None:
    service = build_voice_subsystem(
        _voice_config(debug_mock_provider=False),
        _openai_config(enabled=False, api_key=None),
    )
    service.provider = MockVoiceProvider(stt_transcript="what time is it?")
    service.attach_core_bridge(RecordingCoreBridge())

    result = asyncio.run(service.submit_audio_voice_turn(_audio(), session_id="voice-session"))

    assert result.ok is False
    assert result.error_code == "openai_disabled"
    assert result.stt_invoked is False


def test_audio_voice_turn_rejects_invalid_audio_without_raw_audio_in_error() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.provider = MockVoiceProvider(stt_transcript="what time is it?")
    service.attach_core_bridge(RecordingCoreBridge())

    unsupported = asyncio.run(service.submit_audio_voice_turn(_audio(mime_type="text/plain"), session_id="voice-session"))
    oversized = asyncio.run(service.submit_audio_voice_turn(_audio(b"x" * 256), session_id="voice-session"))
    too_long = asyncio.run(service.submit_audio_voice_turn(_audio(duration_ms=5000), session_id="voice-session"))

    assert unsupported.error_code == "unsupported_audio_type"
    assert oversized.error_code == "audio_too_large"
    assert too_long.error_code == "audio_too_long"
    assert service.status_snapshot()["stt"]["last_audio_input_metadata"]["filename"] == "voice-turn.wav"
    assert "raw_audio" not in str(service.status_snapshot()["stt"])
    assert "fake wav bytes" not in str(service.status_snapshot()["stt"])


def test_audio_voice_turn_rejects_missing_file_input_without_provider_call(tmp_path) -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.provider = MockVoiceProvider(stt_transcript="what time is it?")
    service.attach_core_bridge(RecordingCoreBridge())
    missing = VoiceAudioInput.from_file(tmp_path / "missing.wav", mime_type="audio/wav")

    result = asyncio.run(service.submit_audio_voice_turn(missing, session_id="voice-session"))

    assert result.ok is False
    assert result.error_code == "missing_audio_file"
    assert result.stt_invoked is False
    assert result.provider_network_call_count == 0


def test_empty_transcription_does_not_create_core_bound_turn() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.provider = MockVoiceProvider(stt_transcript="")
    bridge = RecordingCoreBridge()
    service.attach_core_bridge(bridge)

    result = asyncio.run(service.submit_audio_voice_turn(_audio(), session_id="voice-session"))

    assert result.ok is False
    assert result.error_code == "empty_transcript"
    assert result.turn is None
    assert result.core_request is None
    assert bridge.calls == []
    assert result.transcription_result is not None
    assert result.transcription_result.usable_for_core_turn is False


def test_provider_errors_and_uncertainty_are_preserved() -> None:
    error_service = build_voice_subsystem(_voice_config(), _openai_config())
    error_service.provider = MockVoiceProvider(stt_error_code="provider_unavailable", stt_error_message="provider offline")
    error_service.attach_core_bridge(RecordingCoreBridge())

    failed = asyncio.run(error_service.submit_audio_voice_turn(_audio(), session_id="voice-session"))

    uncertain_service = build_voice_subsystem(_voice_config(), _openai_config())
    uncertain_service.provider = MockVoiceProvider(stt_transcript="open downloads", stt_uncertain=True, stt_confidence=0.42)
    uncertain_service.attach_core_bridge(RecordingCoreBridge(route_family="desktop_search", subsystem="desktop_search"))

    uncertain = asyncio.run(uncertain_service.submit_audio_voice_turn(_audio(), session_id="voice-session"))

    assert failed.ok is False
    assert failed.error_code == "provider_unavailable"
    assert failed.core_request is None
    assert uncertain.ok is True
    assert uncertain.turn is not None
    assert uncertain.turn.transcription_uncertain is True
    assert uncertain.turn.transcript_confidence == 0.42
    assert uncertain.turn.metadata["transcription"]["uncertain"] is True
    assert uncertain.core_result.route_family == "desktop_search"


def test_unclear_short_transcription_requests_clarification_without_core_routing() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.provider = MockVoiceProvider(stt_transcript="um")
    bridge = RecordingCoreBridge()
    service.attach_core_bridge(bridge)

    result = asyncio.run(service.submit_audio_voice_turn(_audio(), session_id="voice-session"))

    assert result.ok is False
    assert result.error_code == "transcription_uncertain"
    assert result.core_result is not None
    assert result.core_result.result_state == "clarification_required"
    assert result.spoken_response is not None
    assert result.spoken_response.spoken_text
    assert bridge.calls == []
