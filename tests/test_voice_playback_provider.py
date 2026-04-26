from __future__ import annotations

from dataclasses import replace

from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.models import VoicePlaybackRequest
from stormhelm.core.voice.providers import MockPlaybackProvider


def _audio_output(data: bytes = b"fake audio bytes") -> VoiceAudioOutput:
    return VoiceAudioOutput.from_bytes(
        data,
        format="mp3",
        metadata={"test": True},
    )


def _playback_request(audio_output: VoiceAudioOutput | None = None) -> VoicePlaybackRequest:
    output = audio_output or _audio_output()
    return VoicePlaybackRequest(
        audio_output_id=output.output_id,
        source="tts_output",
        audio_ref=output.bytes_ref,
        file_path=output.file_path,
        format=output.format,
        mime_type=output.mime_type,
        size_bytes=output.size_bytes,
        duration_ms=output.metadata.get("duration_ms") if isinstance(output.metadata.get("duration_ms"), int) else None,
        provider="mock",
        device="test-device",
        volume=0.5,
        session_id="voice-session",
        turn_id="voice-turn",
        synthesis_id="voice-synthesis",
        metadata={"audio_output": output.to_metadata()},
        allowed_to_play=True,
    )


def test_voice_playback_request_metadata_is_bounded_and_traceable() -> None:
    output = _audio_output(b"private playback bytes")
    request = _playback_request(output)
    metadata = request.to_metadata()

    assert request.playback_request_id.startswith("voice-playback-request-")
    assert metadata["audio_output_id"] == output.output_id
    assert metadata["synthesis_id"] == "voice-synthesis"
    assert metadata["device"] == "test-device"
    assert metadata["allowed_to_play"] is True
    assert "private playback bytes" not in str(metadata)
    assert "data': b" not in str(metadata)


def test_mock_playback_provider_can_complete_without_claiming_user_heard_audio() -> None:
    provider = MockPlaybackProvider(complete_immediately=True)
    request = _playback_request()

    result = provider.play(request)

    assert result.ok is True
    assert result.status == "completed"
    assert result.provider == "mock"
    assert result.device == "test-device"
    assert result.played_locally is True
    assert result.user_heard_claimed is False
    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.output_metadata["audio_output_id"] == request.audio_output_id
    assert provider.playback_call_count == 1
    assert provider.get_active_playback() is None


def test_mock_playback_provider_can_start_then_stop_active_playback() -> None:
    provider = MockPlaybackProvider(complete_immediately=False)
    request = _playback_request()

    started = provider.play(request)
    active = provider.get_active_playback()
    stopped = provider.stop(started.playback_id, reason="test_stop")
    no_active = provider.stop(reason="test_stop")

    assert started.ok is True
    assert started.status == "started"
    assert active is not None
    assert active.playback_id == started.playback_id
    assert stopped.ok is True
    assert stopped.status == "stopped"
    assert stopped.error_code is None
    assert stopped.user_heard_claimed is False
    assert no_active.ok is False
    assert no_active.status == "unavailable"
    assert no_active.error_code == "no_active_playback"


def test_mock_playback_provider_reports_blocked_unavailable_and_failed_states() -> None:
    request = _playback_request()

    blocked = MockPlaybackProvider(blocked=True).play(request)
    unavailable = MockPlaybackProvider(available=False).play(request)
    failed = MockPlaybackProvider(fail_playback=True, error_code="device_failed").play(request)

    assert blocked.ok is False
    assert blocked.status == "blocked"
    assert blocked.error_code == "playback_blocked"
    assert unavailable.ok is False
    assert unavailable.status == "unavailable"
    assert unavailable.error_code == "provider_unavailable"
    assert failed.ok is False
    assert failed.status == "failed"
    assert failed.error_code == "device_failed"
    assert blocked.user_heard_claimed is False
    assert unavailable.user_heard_claimed is False
    assert failed.user_heard_claimed is False


def test_mock_playback_provider_respects_request_block_reason() -> None:
    request = replace(_playback_request(), allowed_to_play=False, blocked_reason="playback_disabled")
    provider = MockPlaybackProvider()

    result = provider.play(request)

    assert result.ok is False
    assert result.status == "blocked"
    assert result.error_code == "playback_disabled"
    assert provider.playback_call_count == 0
