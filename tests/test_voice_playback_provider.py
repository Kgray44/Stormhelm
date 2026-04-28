from __future__ import annotations

import asyncio
from pathlib import Path
from dataclasses import replace

from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.models import VoicePlaybackRequest
from stormhelm.core.voice.providers import LocalPlaybackProvider
from stormhelm.core.voice.providers import MockPlaybackProvider


class FakeLocalPlaybackBackend:
    platform_name = "win32"
    dependency_name = "fake_local_player"

    def __init__(
        self,
        *,
        available: bool = True,
        unavailable_reason: str | None = None,
        play_status: str = "completed",
        fail_playback: bool = False,
    ) -> None:
        self.available = available
        self.unavailable_reason = unavailable_reason
        self.play_status = play_status
        self.fail_playback = fail_playback
        self.play_calls: list[dict[str, object]] = []
        self.stop_calls: list[dict[str, object]] = []

    def get_availability(self, config: VoiceConfig) -> dict[str, object]:
        return {
            "provider": "local",
            "backend": self.dependency_name,
            "platform": self.platform_name,
            "dependency": self.dependency_name,
            "dependency_available": self.available,
            "device": config.playback.device,
            "device_available": self.available,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
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
                "exists": resolved.exists(),
                "bytes": resolved.read_bytes() if resolved.exists() else b"",
                "device": request.device,
                "volume": request.volume,
                "playback_id": playback_id,
            }
        )
        if self.fail_playback:
            raise RuntimeError("fake playback backend failed")
        return {
            "status": self.play_status,
            "elapsed_ms": 12,
            "played_locally": True,
        }

    def stop(
        self, playback_id: str | None = None, *, reason: str = "user_requested"
    ) -> dict[str, object]:
        self.stop_calls.append({"playback_id": playback_id, "reason": reason})
        return {"status": "stopped", "elapsed_ms": 3}


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
        data=output.data,
        allowed_to_play=True,
    )


def _local_config(*, enabled: bool = True, allow_dev: bool = True) -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="output_only",
        spoken_responses_enabled=True,
        playback=VoicePlaybackConfig(
            enabled=enabled,
            provider="local",
            device="test-device",
            volume=0.5,
            allow_dev_playback=allow_dev,
        ),
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


def test_local_playback_provider_plays_file_through_backend_without_claiming_user_heard(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"ID3 secret local playback bytes")
    output = VoiceAudioOutput.from_file(audio_path, format="mp3")
    request = replace(_playback_request(output), provider="local")
    backend = FakeLocalPlaybackBackend()
    provider = LocalPlaybackProvider(config=_local_config(), backend=backend)

    result = asyncio.run(provider.play(request))

    assert result.ok is True
    assert result.status == "completed"
    assert result.provider == "local"
    assert result.played_locally is True
    assert result.user_heard_claimed is False
    assert backend.play_calls[0]["path"] == str(audio_path)
    assert backend.play_calls[0]["bytes"] == b"ID3 secret local playback bytes"
    assert "secret local playback bytes" not in str(result.to_dict())


def test_local_playback_provider_writes_transient_bytes_for_backend_and_cleans_up(
    tmp_path: Path,
) -> None:
    output = _audio_output(b"secret in memory playback bytes")
    request = replace(_playback_request(output), provider="local")
    backend = FakeLocalPlaybackBackend()
    provider = LocalPlaybackProvider(
        config=_local_config(), backend=backend, temp_dir=tmp_path
    )

    result = asyncio.run(provider.play(request))
    played_path = Path(str(backend.play_calls[0]["path"]))

    assert result.ok is True
    assert result.status == "completed"
    assert backend.play_calls[0]["exists"] is True
    assert backend.play_calls[0]["bytes"] == b"secret in memory playback bytes"
    assert not played_path.exists()
    assert "secret in memory playback bytes" not in str(result.to_dict())


def test_local_playback_provider_reports_dependency_and_device_unavailable() -> None:
    request = replace(_playback_request(), provider="local")
    dependency_backend = FakeLocalPlaybackBackend(
        available=False, unavailable_reason="local_playback_dependency_missing"
    )
    dependency_provider = LocalPlaybackProvider(
        config=_local_config(), backend=dependency_backend
    )
    device_backend = FakeLocalPlaybackBackend(
        available=False, unavailable_reason="device_unavailable"
    )
    device_provider = LocalPlaybackProvider(config=_local_config(), backend=device_backend)

    dependency_availability = dependency_provider.get_availability()
    dependency_result = asyncio.run(dependency_provider.play(request))
    device_availability = device_provider.get_availability()
    device_result = asyncio.run(device_provider.play(request))

    assert dependency_availability["available"] is False
    assert dependency_availability["unavailable_reason"] == "local_playback_dependency_missing"
    assert dependency_result.ok is False
    assert dependency_result.status == "unavailable"
    assert dependency_result.error_code == "local_playback_dependency_missing"
    assert dependency_result.user_heard_claimed is False
    assert device_availability["available"] is False
    assert device_availability["unavailable_reason"] == "device_unavailable"
    assert device_result.ok is False
    assert device_result.status == "unavailable"
    assert device_result.error_code == "device_unavailable"
    assert device_result.user_heard_claimed is False


def test_local_playback_provider_can_start_then_stop_active_backend_playback(
    tmp_path: Path,
) -> None:
    output = _audio_output(b"active playback bytes")
    request = replace(_playback_request(output), provider="local")
    backend = FakeLocalPlaybackBackend(play_status="started")
    provider = LocalPlaybackProvider(
        config=_local_config(), backend=backend, temp_dir=tmp_path
    )

    started = asyncio.run(provider.play(request))
    active = provider.get_active_playback()
    stopped = provider.stop(started.playback_id, reason="stop_speaking")

    assert started.ok is True
    assert started.status == "started"
    assert active is not None
    assert active.playback_id == started.playback_id
    assert stopped.ok is True
    assert stopped.status == "stopped"
    assert stopped.playback_id == started.playback_id
    assert stopped.user_heard_claimed is False
    assert backend.stop_calls == [
        {"playback_id": started.playback_id, "reason": "stop_speaking"}
    ]
