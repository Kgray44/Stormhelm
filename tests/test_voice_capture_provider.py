from __future__ import annotations

from stormhelm.core.voice.models import VoiceCaptureRequest
from stormhelm.core.voice.providers import LocalCaptureProvider
from stormhelm.core.voice.providers import MockCaptureProvider
from stormhelm.core.voice.providers import VoiceCaptureProvider
from stormhelm.config.models import VoiceConfig


def _request(**overrides):
    values = {
        "source": "push_to_talk",
        "provider": "mock",
        "device": "test-mic",
        "sample_rate": 16000,
        "channels": 1,
        "format": "wav",
        "max_duration_ms": 30000,
        "max_audio_bytes": 10_000_000,
        "persist_audio": False,
        "allowed_to_capture": True,
    }
    values.update(overrides)
    return VoiceCaptureRequest(**values)


def test_mock_capture_provider_satisfies_capture_interface_and_completes_bounded_capture() -> None:
    provider = MockCaptureProvider(capture_audio_bytes=b"fake voice bytes", duration_ms=900)

    session = provider.start_capture(_request(session_id="voice-session"))
    result = provider.stop_capture(session.capture_id, reason="user_released")

    assert isinstance(provider, VoiceCaptureProvider)
    assert provider.is_mock is True
    assert session.status == "recording"
    assert result.ok is True
    assert result.status == "completed"
    assert result.capture_id == session.capture_id
    assert result.audio_input is not None
    assert result.audio_input.source == "mock"
    assert result.audio_input.duration_ms == 900
    assert result.audio_input.metadata["capture_id"] == session.capture_id
    assert result.raw_audio_persisted is False
    assert result.always_listening_claimed is False
    assert result.wake_word_claimed is False
    assert "fake voice bytes" not in str(result.to_dict())


def test_mock_capture_provider_reports_active_exists_cancel_timeout_and_no_active_truthfully() -> None:
    provider = MockCaptureProvider(timeout_on_stop=True)
    first = provider.start_capture(_request())
    second = provider.start_capture(_request())
    timed_out = provider.stop_capture(first.capture_id, reason="max_duration")
    no_active = provider.stop_capture(reason="user_released")

    cancellable = MockCaptureProvider()
    started = cancellable.start_capture(_request())
    cancelled = cancellable.cancel_capture(started.capture_id, reason="user_cancelled")

    assert second.status == "blocked"
    assert second.error_code == "active_capture_exists"
    assert timed_out.status == "timeout"
    assert timed_out.error_code == "capture_timeout"
    assert timed_out.audio_input is None
    assert no_active.status == "unavailable"
    assert no_active.error_code == "no_active_capture"
    assert cancelled.status == "cancelled"
    assert cancelled.audio_input is None
    assert cancelled.microphone_was_active is False


def test_local_capture_provider_is_truthfully_disabled_without_capture_gate() -> None:
    provider = LocalCaptureProvider(config=VoiceConfig())
    request = _request(provider="local")

    result = provider.start_capture(request)
    stopped = provider.stop_capture(reason="user_released")

    assert provider.is_mock is False
    assert provider.get_availability()["available"] is False
    assert provider.get_availability()["unavailable_reason"] == "capture_disabled"
    assert result.status == "blocked"
    assert result.error_code == "capture_disabled"
    assert stopped.status == "unavailable"
    assert stopped.error_code == "no_active_capture"
