from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.models import VoiceCaptureRequest
from stormhelm.core.voice.providers import LocalCaptureProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge


class FakeLocalCaptureBackend:
    dependency_name = "fake-recorder"
    platform_name = "test-platform"

    def __init__(
        self,
        *,
        dependency_available: bool = True,
        platform_supported: bool = True,
        device_available: bool | None = True,
        permission_error: bool = False,
        timeout_on_stop: bool = False,
        audio_bytes: bytes = b"RIFF fake wav bytes",
        duration_ms: int = 800,
    ) -> None:
        self.dependency_available = dependency_available
        self.platform_supported = platform_supported
        self.device_available = device_available
        self.permission_error = permission_error
        self.timeout_on_stop = timeout_on_stop
        self.audio_bytes = audio_bytes
        self.duration_ms = duration_ms
        self.started = 0
        self.stopped = 0
        self.cancelled = 0
        self.cleaned: list[str] = []

    def get_availability(self, config: VoiceConfig) -> dict[str, Any]:
        del config
        reason = None
        available = True
        if not self.platform_supported:
            available = False
            reason = "unsupported_platform"
        elif not self.dependency_available:
            available = False
            reason = "dependency_missing"
        elif self.device_available is False:
            available = False
            reason = "device_unavailable"
        return {
            "available": available,
            "unavailable_reason": reason,
            "platform_supported": self.platform_supported,
            "dependency_available": self.dependency_available,
            "dependency": self.dependency_name,
            "device_available": self.device_available,
            "permission_state": "unknown",
        }

    def start(self, request: VoiceCaptureRequest, output_path: Path) -> dict[str, Any]:
        if self.permission_error:
            raise PermissionError("microphone permission denied")
        self.started += 1
        return {
            "output_path": str(output_path),
            "platform": self.platform_name,
            "dependency": self.dependency_name,
            "device_available": self.device_available,
            "permission_state": "granted",
            "sample_rate": request.sample_rate,
            "channels": request.channels,
        }

    def stop(self, handle: dict[str, Any], *, reason: str) -> dict[str, Any]:
        del reason
        self.stopped += 1
        output_path = Path(handle["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(self.audio_bytes)
        return {
            "output_path": str(output_path),
            "duration_ms": self.duration_ms,
            "size_bytes": len(self.audio_bytes),
            "timed_out": self.timeout_on_stop,
            "metadata": {"fake_backend": True},
        }

    def cancel(self, handle: dict[str, Any], *, reason: str) -> None:
        del reason
        self.cancelled += 1
        path = Path(handle["output_path"])
        if path.exists():
            path.unlink()

    def cleanup(self, path: str | Path) -> None:
        self.cleaned.append(str(path))
        Path(path).unlink(missing_ok=True)


def _voice_config(
    *,
    capture_enabled: bool = True,
    allow_dev_capture: bool = True,
    provider: str = "local",
    delete_transient_after_turn: bool = True,
) -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="manual",
        spoken_responses_enabled=True,
        debug_mock_provider=False,
        openai=VoiceOpenAIConfig(max_audio_bytes=1024, max_audio_seconds=10),
        capture=VoiceCaptureConfig(
            enabled=capture_enabled,
            provider=provider,
            device="test-mic",
            sample_rate=16000,
            channels=1,
            format="wav",
            max_duration_ms=3000,
            max_audio_bytes=1024,
            allow_dev_capture=allow_dev_capture,
            delete_transient_after_turn=delete_transient_after_turn,
        ),
    )


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


def _request(**overrides: Any) -> VoiceCaptureRequest:
    values = {
        "source": "push_to_talk",
        "provider": "local",
        "device": "test-mic",
        "sample_rate": 16000,
        "channels": 1,
        "format": "wav",
        "max_duration_ms": 3000,
        "max_audio_bytes": 1024,
        "persist_audio": False,
        "allowed_to_capture": True,
    }
    values.update(overrides)
    return VoiceCaptureRequest(**values)


def test_local_capture_provider_reports_config_dependency_platform_and_permission_gates(tmp_path: Path) -> None:
    disabled = LocalCaptureProvider(config=_voice_config(capture_enabled=False), backend=FakeLocalCaptureBackend(), temp_dir=tmp_path)
    dev_blocked = LocalCaptureProvider(config=_voice_config(allow_dev_capture=False), backend=FakeLocalCaptureBackend(), temp_dir=tmp_path)
    missing_dependency = LocalCaptureProvider(
        config=_voice_config(),
        backend=FakeLocalCaptureBackend(dependency_available=False),
        temp_dir=tmp_path,
    )
    unsupported_platform = LocalCaptureProvider(
        config=_voice_config(),
        backend=FakeLocalCaptureBackend(platform_supported=False),
        temp_dir=tmp_path,
    )
    permission_denied = LocalCaptureProvider(
        config=_voice_config(),
        backend=FakeLocalCaptureBackend(permission_error=True),
        temp_dir=tmp_path,
    )

    assert disabled.get_availability()["unavailable_reason"] == "capture_disabled"
    assert dev_blocked.get_availability()["unavailable_reason"] == "dev_capture_not_allowed"
    assert missing_dependency.get_availability()["unavailable_reason"] == "dependency_missing"
    assert missing_dependency.get_availability()["dependency_available"] is False
    assert unsupported_platform.get_availability()["unavailable_reason"] == "unsupported_platform"

    result = permission_denied.start_capture(_request())
    assert result.status == "unavailable"
    assert result.error_code == "permission_denied"
    assert result.microphone_was_active is False
    assert result.always_listening_claimed is False
    assert result.wake_word_claimed is False


def test_local_capture_provider_starts_stops_and_bounds_fake_backend_output(tmp_path: Path) -> None:
    backend = FakeLocalCaptureBackend(audio_bytes=b"RIFF captured local wav", duration_ms=900)
    provider = LocalCaptureProvider(config=_voice_config(), backend=backend, temp_dir=tmp_path)

    session = provider.start_capture(_request(session_id="voice-session"))
    second = provider.start_capture(_request(session_id="voice-session"))
    result = provider.stop_capture(session.capture_id, reason="user_released")

    assert session.status == "recording"
    assert session.provider == "local"
    assert session.microphone_was_active is True
    assert session.always_listening_claimed is False
    assert session.wake_word_claimed is False
    assert second.status == "blocked"
    assert second.error_code == "active_capture_exists"
    assert result.ok is True
    assert result.status == "completed"
    assert result.audio_input is not None
    assert result.audio_input.source == "file"
    assert result.audio_input.mime_type == "audio/wav"
    assert result.audio_input.duration_ms == 900
    assert result.audio_input.sample_rate == 16000
    assert result.audio_input.channels == 1
    assert result.size_bytes == len(b"RIFF captured local wav")
    assert result.microphone_was_active is True
    assert result.always_listening_claimed is False
    assert result.wake_word_claimed is False
    assert "RIFF captured local wav" not in str(result.to_dict())
    assert provider.get_active_capture() is None
    assert backend.started == 1
    assert backend.stopped == 1


def test_local_capture_provider_cancel_timeout_and_oversize_are_truthful(tmp_path: Path) -> None:
    cancel_backend = FakeLocalCaptureBackend()
    provider = LocalCaptureProvider(config=_voice_config(), backend=cancel_backend, temp_dir=tmp_path)
    session = provider.start_capture(_request())
    cancelled = provider.cancel_capture(session.capture_id, reason="user_cancelled")

    timeout_backend = FakeLocalCaptureBackend(timeout_on_stop=True)
    timeout_provider = LocalCaptureProvider(config=_voice_config(), backend=timeout_backend, temp_dir=tmp_path)
    timed_session = timeout_provider.start_capture(_request())
    timed_out = timeout_provider.stop_capture(timed_session.capture_id, reason="max_duration")

    oversized_backend = FakeLocalCaptureBackend(audio_bytes=b"x" * 2048)
    oversized_provider = LocalCaptureProvider(config=_voice_config(), backend=oversized_backend, temp_dir=tmp_path)
    oversized_session = oversized_provider.start_capture(_request(max_audio_bytes=64))
    oversized = oversized_provider.stop_capture(oversized_session.capture_id, reason="user_released")

    assert cancelled.status == "cancelled"
    assert cancelled.audio_input is None
    assert cancelled.microphone_was_active is True
    assert cancel_backend.cancelled == 1
    assert timed_out.status == "timeout"
    assert timed_out.error_code == "capture_timeout"
    assert timed_out.audio_input is None
    assert oversized.status == "failed"
    assert oversized.error_code == "captured_audio_too_large"
    assert oversized.audio_input is None


def test_local_capture_diagnostics_and_cleanup_do_not_expose_raw_audio(tmp_path: Path) -> None:
    events = EventBuffer(capacity=64)
    service = build_voice_subsystem(_voice_config(), _openai_config(), events=events)
    backend = FakeLocalCaptureBackend(audio_bytes=b"RIFF private local audio", duration_ms=600)
    service.capture_provider = LocalCaptureProvider(config=service.config, backend=backend, temp_dir=tmp_path)
    service.provider = MockVoiceProvider(stt_transcript="open downloads", stt_confidence=0.9)
    service.attach_core_bridge(RecordingCoreBridge(route_family="desktop_search", subsystem="desktop_search"))

    session = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    active_status = service.status_snapshot()
    capture = asyncio.run(service.stop_push_to_talk_capture(session.capture_id))
    stopped_status = service.status_snapshot()
    turn = asyncio.run(service.submit_captured_audio_turn(capture, session_id="voice-session"))
    recent = events.recent(limit=64)

    assert active_status["capture"]["provider"] == "local"
    assert active_status["capture"]["available"] is True
    assert active_status["capture"]["dependency_available"] is True
    assert active_status["capture"]["device_available"] is True
    assert active_status["capture"]["permission_state"] == "granted"
    assert active_status["capture"]["active_capture_id"] == session.capture_id
    assert stopped_status["capture"]["last_capture_file_metadata"]["file_path"]
    assert stopped_status["capture"]["last_capture_audio_input_metadata"]["file_path"] is None
    assert turn.ok is True
    assert backend.cleaned == [capture.audio_input.file_path]
    assert "RIFF private local audio" not in str(stopped_status)
    assert "RIFF private local audio" not in str([event["payload"] for event in recent])
    assert "voice.wake_detected" not in [event["event_type"] for event in recent]
    assert "voice.speech_started" not in [event["event_type"] for event in recent]
