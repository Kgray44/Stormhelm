from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.voice.models import VoiceAudioOutput
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
        "spoken_responses_enabled": True,
        "debug_mock_provider": True,
        "openai": VoiceOpenAIConfig(max_tts_chars=240),
        "playback": VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            device="test-device",
            volume=0.5,
            allow_dev_playback=True,
            max_audio_bytes=64,
            max_duration_ms=5000,
        ),
    }
    values.update(overrides)
    return VoiceConfig(**values)


def _service(**config_overrides: Any):
    service = build_voice_subsystem(_voice_config(**config_overrides), _openai_config())
    service.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")
    service.playback_provider = MockPlaybackProvider(complete_immediately=True)
    return service


def _audio_output(data: bytes = b"voice bytes", *, format: str = "mp3", duration_ms: int | None = None) -> VoiceAudioOutput:
    metadata = {"duration_ms": duration_ms} if duration_ms is not None else {}
    return VoiceAudioOutput.from_bytes(data, format=format, metadata=metadata)


def test_play_speech_output_plays_voice3_synthesis_without_mutating_task_state() -> None:
    service = _service()
    synthesis = asyncio.run(service.synthesize_speech_text("Bearing acquired.", source="manual_test", session_id="voice-session"))

    playback = asyncio.run(service.play_speech_output(synthesis, session_id="voice-session", turn_id="turn-1"))

    assert synthesis.ok is True
    assert playback.ok is True
    assert playback.status == "completed"
    assert playback.synthesis_id == synthesis.synthesis_id
    assert playback.audio_output_id == synthesis.audio_output.output_id
    assert playback.played_locally is True
    assert playback.user_heard_claimed is False
    assert service.playback_provider.playback_call_count == 1


def test_playback_is_blocked_when_playback_disabled_even_if_tts_generated_audio() -> None:
    service = build_voice_subsystem(
        _voice_config(playback=VoicePlaybackConfig(enabled=False, provider="mock", allow_dev_playback=True)),
        _openai_config(),
    )
    service.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")
    service.playback_provider = MockPlaybackProvider()
    synthesis = asyncio.run(service.synthesize_speech_text("Bearing acquired.", source="manual_test", session_id="voice-session"))

    playback = asyncio.run(service.play_speech_output(synthesis, session_id="voice-session"))

    assert synthesis.ok is True
    assert playback.ok is False
    assert playback.status == "blocked"
    assert playback.error_code == "playback_disabled"
    assert service.playback_provider.playback_call_count == 0


def test_playback_is_blocked_when_voice_or_provider_unavailable() -> None:
    disabled = build_voice_subsystem(
        VoiceConfig(enabled=False, mode="disabled", playback=VoicePlaybackConfig(enabled=True, provider="mock")),
        _openai_config(),
    )
    disabled.playback_provider = MockPlaybackProvider()
    unavailable = build_voice_subsystem(
        _voice_config(debug_mock_provider=False, playback=VoicePlaybackConfig(enabled=True, provider="mock")),
        _openai_config(enabled=False, api_key=None),
    )
    unavailable.playback_provider = MockPlaybackProvider()
    audio = _audio_output()

    disabled_result = asyncio.run(disabled.play_speech_output(audio))
    unavailable_result = asyncio.run(unavailable.play_speech_output(audio))

    assert disabled_result.error_code == "voice_disabled"
    assert unavailable_result.error_code == "openai_disabled"
    assert disabled.playback_provider.playback_call_count == 0
    assert unavailable.playback_provider.playback_call_count == 0


def test_playback_validation_blocks_missing_unsupported_oversized_and_expired_audio() -> None:
    service = _service()
    missing = asyncio.run(service.play_speech_output(None))
    unsupported = asyncio.run(service.play_speech_output(_audio_output(format="ogg")))
    oversized = asyncio.run(service.play_speech_output(_audio_output(b"x" * 128)))
    expired = asyncio.run(
        service.play_speech_output(
            replace(_audio_output(), expires_at="2000-01-01T00:00:00+00:00")
        )
    )

    assert missing.error_code == "missing_audio_output"
    assert unsupported.error_code == "unsupported_playback_format"
    assert oversized.error_code == "audio_too_large"
    assert expired.error_code == "audio_output_expired"
    assert service.playback_provider.playback_call_count == 0


def test_playback_validation_blocks_overlong_audio_metadata() -> None:
    service = _service()
    overlong = _audio_output(duration_ms=7000)

    result = asyncio.run(service.play_speech_output(overlong))

    assert result.ok is False
    assert result.error_code == "audio_too_long"
    assert service.playback_provider.playback_call_count == 0


def test_play_turn_response_synthesizes_then_plays_without_rerouting_core() -> None:
    service = _service()
    bridge = RecordingCoreBridge(route_family="clock", subsystem="tools", spoken_summary="The time is 10:15.")
    service.attach_core_bridge(bridge)
    turn_result = asyncio.run(service.submit_manual_voice_turn("what time is it?", session_id="voice-session"))

    playback = asyncio.run(service.play_turn_response(turn_result, session_id="voice-session"))

    assert playback.ok is True
    assert playback.status == "completed"
    assert playback.turn_id == turn_result.turn.turn_id
    assert playback.synthesis_id is not None
    assert playback.played_locally is True
    assert playback.user_heard_claimed is False
    assert len(bridge.calls) == 1
    assert turn_result.core_result.result_state == "completed"


def test_stop_playback_stops_active_output_without_cancelling_core_tasks() -> None:
    service = _service()
    service.playback_provider = MockPlaybackProvider(complete_immediately=False)

    started = asyncio.run(service.play_speech_output(_audio_output(), session_id="voice-session"))
    stopped = asyncio.run(service.stop_playback(started.playback_id, reason="user_requested"))
    no_active = asyncio.run(service.stop_playback(reason="user_requested"))

    assert started.status == "started"
    assert stopped.ok is True
    assert stopped.status == "stopped"
    assert stopped.playback_id == started.playback_id
    assert stopped.user_heard_claimed is False
    assert no_active.ok is False
    assert no_active.error_code == "no_active_playback"
