from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.models import VoicePlaybackRequest
from stormhelm.core.voice.providers import LocalPlaybackProvider
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge


class FakeLocalPlaybackBackend:
    dependency_name = "fake_local_player"
    platform_name = "win32"

    def __init__(self, *, fail_playback: bool = False) -> None:
        self.fail_playback = fail_playback
        self.play_calls: list[dict[str, object]] = []

    def get_availability(self, config: VoiceConfig) -> dict[str, object]:
        return {
            "provider": "local",
            "backend": self.dependency_name,
            "platform": self.platform_name,
            "dependency": self.dependency_name,
            "dependency_available": True,
            "device": config.playback.device,
            "device_available": True,
            "available": True,
            "unavailable_reason": None,
        }

    def play_file(
        self,
        path: str | Path,
        *,
        request: VoicePlaybackRequest,
        playback_id: str,
    ) -> dict[str, object]:
        resolved = Path(path)
        self.play_calls.append(
            {
                "path": str(resolved),
                "bytes": resolved.read_bytes() if resolved.exists() else b"",
                "request_data_present": request.data is not None,
                "playback_id": playback_id,
            }
        )
        if self.fail_playback:
            raise RuntimeError("fake local playback failed")
        return {"status": "completed", "elapsed_ms": 7, "played_locally": True}


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


def _local_output_service(tmp_path: Path, *, fail_playback: bool = False):
    events = EventBuffer(capacity=96)
    playback_config = VoicePlaybackConfig(
        enabled=True,
        provider="local",
        device="default",
        volume=0.75,
        allow_dev_playback=True,
        max_audio_bytes=1024,
        max_duration_ms=5000,
        delete_transient_after_playback=True,
    )
    service = build_voice_subsystem(
        _voice_config(
            mode="output_only",
            debug_mock_provider=False,
            playback=playback_config,
        ),
        _openai_config(),
        events=events,
    )
    backend = FakeLocalPlaybackBackend(fail_playback=fail_playback)
    service.provider = MockVoiceProvider(tts_audio_bytes=b"local voice bytes")
    service.playback_provider = LocalPlaybackProvider(
        config=service.config,
        backend=backend,
        temp_dir=tmp_path,
    )
    return service, events, backend


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


def test_output_only_playback_can_transition_from_dormant_without_error(
    tmp_path: Path,
) -> None:
    service, _events, _backend = _local_output_service(tmp_path)
    synthesis = asyncio.run(
        service.synthesize_speech_text(
            "Current weather is clear.",
            source="assistant_response",
            session_id="default",
        )
    )

    playback = asyncio.run(service.play_speech_output(synthesis, session_id="default"))

    assert playback.ok is True
    assert playback.status == "completed"
    assert service.state_controller.snapshot().state.value == "dormant"
    assert service.last_error == {"code": None, "message": None}


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


def test_output_only_mode_synthesizes_and_invokes_real_local_playback_provider(
    tmp_path: Path,
) -> None:
    service, events, backend = _local_output_service(tmp_path)

    synthesis = asyncio.run(
        service.synthesize_speech_text(
            "Bearing acquired.",
            source="output_only_test",
            session_id="voice-session",
        )
    )
    playback = asyncio.run(
        service.play_speech_output(
            synthesis,
            session_id="voice-session",
            turn_id="turn-output",
        )
    )
    recent = events.recent(limit=96)
    event_types = [event["event_type"] for event in recent]

    assert synthesis.ok is True
    assert playback.ok is True
    assert playback.status == "completed"
    assert playback.provider == "local"
    assert playback.played_locally is True
    assert playback.user_heard_claimed is False
    assert backend.play_calls
    assert backend.play_calls[0]["bytes"] == b"local voice bytes"
    assert backend.play_calls[0]["request_data_present"] is True
    assert "voice.playback_started" in event_types
    assert "voice.playback_completed" in event_types
    assert "voice.capture_started" not in event_types
    assert "voice.wake_detected" not in event_types
    assert "voice.realtime_session_started" not in event_types
    assert "local voice bytes" not in str(recent)
    assert "local voice bytes" not in str(service.status_snapshot())


def test_local_playback_failure_preserves_synthesis_result_without_core_mutation(
    tmp_path: Path,
) -> None:
    service, events, backend = _local_output_service(tmp_path, fail_playback=True)

    synthesis = asyncio.run(
        service.synthesize_speech_text(
            "Bearing acquired.",
            source="output_only_test",
            session_id="voice-session",
        )
    )
    playback = asyncio.run(service.play_speech_output(synthesis, session_id="voice-session"))
    event_types = [event["event_type"] for event in events.recent(limit=96)]

    assert synthesis.ok is True
    assert synthesis.audio_output is not None
    assert backend.play_calls
    assert playback.ok is False
    assert playback.status == "failed"
    assert playback.error_code == "local_playback_failed"
    assert playback.user_heard_claimed is False
    assert service.last_synthesis_result == synthesis
    assert "voice.playback_failed" in event_types
    assert "voice.core_request_started" not in event_types
