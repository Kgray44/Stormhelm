from __future__ import annotations

import asyncio
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.voice.providers import MockCaptureProvider
from stormhelm.core.voice.providers import MockPlaybackProvider
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
        "capture": VoiceCaptureConfig(
            enabled=True,
            provider="mock",
            device="test-mic",
            max_duration_ms=4000,
            max_audio_bytes=128,
            allow_dev_capture=True,
        ),
    }
    values.update(overrides)
    return VoiceConfig(**values)


def _service(**config_overrides: Any):
    service = build_voice_subsystem(_voice_config(**config_overrides), _openai_config())
    service.provider = MockVoiceProvider(stt_transcript="what time is it?", stt_confidence=0.91)
    service.capture_provider = MockCaptureProvider(capture_audio_bytes=b"captured voice", duration_ms=900)
    service.attach_core_bridge(RecordingCoreBridge(route_family="clock", subsystem="tools", spoken_summary="The time is 10:15."))
    return service


def test_push_to_talk_start_stop_produces_bounded_audio_input_without_routing() -> None:
    service = _service()

    session = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session", metadata={"surface": "ghost"}))
    result = asyncio.run(service.stop_push_to_talk_capture(session.capture_id, reason="user_released"))

    assert session.status == "recording"
    assert session.session_id == "voice-session"
    assert result.ok is True
    assert result.status == "completed"
    assert result.audio_input is not None
    assert result.audio_input.source == "mock"
    assert result.audio_input.size_bytes == len(b"captured voice")
    assert result.audio_input.metadata["capture_source"] == "push_to_talk"
    assert result.microphone_was_active is False
    assert result.always_listening_claimed is False
    assert result.wake_word_claimed is False
    assert service.last_audio_turn_result is None


def test_capture_blocks_when_disabled_or_provider_unavailable_without_real_device_fallback() -> None:
    disabled = build_voice_subsystem(
        _voice_config(capture=VoiceCaptureConfig(enabled=False, provider="mock")),
        _openai_config(),
    )
    disabled.capture_provider = MockCaptureProvider()
    unavailable = _service()
    unavailable.capture_provider = MockCaptureProvider(available=False)

    disabled_result = asyncio.run(disabled.start_push_to_talk_capture())
    unavailable_result = asyncio.run(unavailable.start_push_to_talk_capture())

    assert disabled_result.status == "blocked"
    assert disabled_result.error_code == "capture_disabled"
    assert disabled.capture_provider.start_call_count == 0
    assert unavailable_result.status == "unavailable"
    assert unavailable_result.error_code == "provider_unavailable"
    assert unavailable.capture_provider.start_call_count == 0


def test_capture_blocks_when_voice_or_openai_unavailable_without_dev_override() -> None:
    voice_disabled = build_voice_subsystem(
        _voice_config(enabled=False, capture=VoiceCaptureConfig(enabled=True, provider="mock")),
        _openai_config(),
    )
    voice_disabled.capture_provider = MockCaptureProvider()
    openai_disabled = build_voice_subsystem(
        _voice_config(
            capture=VoiceCaptureConfig(
                enabled=True,
                provider="mock",
                allow_dev_capture=False,
            )
        ),
        _openai_config(enabled=False, api_key=None),
    )
    openai_disabled.capture_provider = MockCaptureProvider()

    voice_result = asyncio.run(voice_disabled.start_push_to_talk_capture())
    openai_result = asyncio.run(openai_disabled.start_push_to_talk_capture())

    assert voice_result.status == "blocked"
    assert voice_result.error_code == "voice_disabled"
    assert voice_disabled.capture_provider.start_call_count == 0
    assert openai_result.status == "blocked"
    assert openai_result.error_code == "openai_disabled"
    assert openai_disabled.capture_provider.start_call_count == 0


def test_capture_blocks_invalid_duration_and_size_without_starting_provider() -> None:
    invalid_duration = _service(
        capture=VoiceCaptureConfig(
            enabled=True,
            provider="mock",
            max_duration_ms=0,
            max_audio_bytes=128,
            allow_dev_capture=True,
        )
    )
    invalid_size = _service(
        capture=VoiceCaptureConfig(
            enabled=True,
            provider="mock",
            max_duration_ms=4000,
            max_audio_bytes=0,
            allow_dev_capture=True,
        )
    )

    duration_result = asyncio.run(invalid_duration.start_push_to_talk_capture())
    size_result = asyncio.run(invalid_size.start_push_to_talk_capture())

    assert duration_result.status == "blocked"
    assert duration_result.error_code == "invalid_capture_duration"
    assert invalid_duration.capture_provider.start_call_count == 0
    assert size_result.status == "blocked"
    assert size_result.error_code == "invalid_capture_size_limit"
    assert invalid_size.capture_provider.start_call_count == 0


def test_oversized_capture_output_fails_without_stt_or_core_routing() -> None:
    service = _service()
    service.capture_provider = MockCaptureProvider(capture_audio_bytes=b"x" * 129, duration_ms=900)

    session = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    result = asyncio.run(service.stop_push_to_talk_capture(session.capture_id))

    assert result.ok is False
    assert result.status == "failed"
    assert result.error_code == "captured_audio_too_large"
    assert result.audio_input is None
    assert service.last_audio_turn_result is None
    assert service.last_transcription_result is None


def test_capture_blocks_second_start_and_cancel_does_not_route_to_core() -> None:
    service = _service()

    first = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    second = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    cancelled = asyncio.run(service.cancel_capture(first.capture_id, reason="user_cancelled"))

    assert first.status == "recording"
    assert second.status == "blocked"
    assert second.error_code == "active_capture_exists"
    assert cancelled.status == "cancelled"
    assert cancelled.audio_input is None
    assert service.last_audio_turn_result is None


def test_completed_capture_reuses_voice2_audio_turn_and_core_bridge() -> None:
    service = _service()

    session = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    capture = asyncio.run(service.stop_push_to_talk_capture(session.capture_id))
    turn = asyncio.run(service.submit_captured_audio_turn(capture, session_id="voice-session"))

    assert turn.ok is True
    assert turn.turn is not None
    assert turn.turn.source == "mock_stt"
    assert turn.turn.transcript == "what time is it?"
    assert turn.turn.metadata["capture"]["capture_id"] == capture.capture_id
    assert turn.core_request is not None
    assert turn.core_request.voice_mode == "stt"
    assert turn.core_result.route_family == "clock"
    assert turn.stt_invoked is True
    assert service.provider.tts_call_count == 0


def test_cancelled_capture_is_not_submitted_to_stt_or_core() -> None:
    service = _service()
    session = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    capture = asyncio.run(service.cancel_capture(session.capture_id))

    turn = asyncio.run(service.submit_captured_audio_turn(capture, session_id="voice-session"))

    assert turn.ok is False
    assert turn.error_code == "capture_not_completed"
    assert turn.stt_invoked is False
    assert service.last_transcription_result is None


def test_capture_pipeline_preserves_stage_results_through_tts_and_playback_when_requested() -> None:
    service = _service(
        playback=VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            allow_dev_playback=True,
            max_audio_bytes=128,
        )
    )
    service.playback_provider = MockPlaybackProvider(complete_immediately=True)

    session = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    result = asyncio.run(
        service.capture_and_submit_turn(
            session.capture_id,
            mode="ghost",
            synthesize_response=True,
            play_response=True,
        )
    )

    assert result.final_status == "completed"
    assert result.capture_result is not None and result.capture_result.ok is True
    assert result.voice_turn_result is not None and result.voice_turn_result.ok is True
    assert result.synthesis_result is not None and result.synthesis_result.ok is True
    assert result.playback_result is not None and result.playback_result.status == "completed"
    assert result.voice_turn_result.core_result.result_state == "completed"
