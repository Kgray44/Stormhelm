from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.config.models import VoiceVADConfig
from stormhelm.core.voice.models import VoiceCaptureRequest
from stormhelm.core.voice.providers import LocalCaptureProvider
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge


class EndpointingCaptureBackend:
    dependency_name = "fake-endpointing-mic"
    platform_name = "test-platform"

    def __init__(
        self,
        *,
        endpoint_reason: str = "speech_ended",
        speech_detected: bool = True,
        audio_bytes: bytes = b"RIFF endpointed local speech",
        duration_ms: int = 860,
    ) -> None:
        self.endpoint_reason = endpoint_reason
        self.speech_detected = speech_detected
        self.audio_bytes = audio_bytes
        self.duration_ms = duration_ms
        self.started = 0
        self.waited = 0
        self.stopped = 0
        self.cancelled = 0

    def get_availability(self, config: VoiceConfig) -> dict[str, Any]:
        del config
        return {
            "available": True,
            "unavailable_reason": None,
            "platform_supported": True,
            "dependency_available": True,
            "dependency": self.dependency_name,
            "device_available": True,
            "permission_state": "granted",
        }

    def start(self, request: VoiceCaptureRequest, output_path: Path) -> dict[str, Any]:
        self.started += 1
        return {
            "output_path": str(output_path),
            "platform": self.platform_name,
            "dependency": self.dependency_name,
            "device_available": True,
            "permission_state": "granted",
            "sample_rate": request.sample_rate,
            "channels": request.channels,
        }

    def wait_for_endpoint(
        self, handle: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        self.waited += 1
        del timeout_ms
        endpoint = {
            "reason": self.endpoint_reason,
            "speech_detected": self.speech_detected,
            "speech_detected_ms": 120 if self.speech_detected else None,
            "endpoint_ms": self.duration_ms,
            "raw_audio_logged": False,
            "raw_secret_logged": False,
        }
        handle["endpoint"] = endpoint
        return endpoint

    def stop(self, handle: dict[str, Any], *, reason: str) -> dict[str, Any]:
        self.stopped += 1
        output_path = Path(handle["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(self.audio_bytes)
        endpoint = dict(handle.get("endpoint") or {})
        return {
            "output_path": str(output_path),
            "duration_ms": self.duration_ms,
            "size_bytes": len(self.audio_bytes),
            "timed_out": reason == "max_duration",
            "metadata": {"fake_backend": True, "endpoint": endpoint},
            "endpoint": endpoint,
        }

    def cancel(self, handle: dict[str, Any], *, reason: str) -> None:
        del reason
        self.cancelled += 1
        Path(str(handle.get("output_path") or "")).unlink(missing_ok=True)

    def cleanup(self, path: str | Path) -> None:
        Path(path).unlink(missing_ok=True)


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


def _voice_config() -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="manual",
        spoken_responses_enabled=True,
        debug_mock_provider=False,
        openai=VoiceOpenAIConfig(max_audio_bytes=2048, max_audio_seconds=10),
        capture=VoiceCaptureConfig(
            enabled=True,
            provider="local",
            device="test-mic",
            sample_rate=16000,
            channels=1,
            format="wav",
            max_duration_ms=3000,
            max_audio_bytes=2048,
            allow_dev_capture=True,
            delete_transient_after_turn=True,
        ),
        vad=VoiceVADConfig(enabled=True, provider="mock", silence_ms=700),
        playback=VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            allow_dev_playback=True,
            max_audio_bytes=2048,
        ),
    )


def _service(tmp_path: Path, backend: EndpointingCaptureBackend):
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.capture_provider = LocalCaptureProvider(
        config=service.config,
        backend=backend,
        temp_dir=tmp_path,
    )
    service.provider = MockVoiceProvider(
        stt_transcript="what time is it?",
        stt_confidence=0.92,
    )
    service.playback_provider = MockPlaybackProvider(complete_immediately=True)
    service.attach_core_bridge(
        RecordingCoreBridge(
            route_family="clock",
            subsystem="tools",
            spoken_summary="The time is 10:15.",
        )
    )
    return service


def test_l6_manual_listen_turn_endpoints_transcribes_routes_and_speaks(
    tmp_path: Path,
) -> None:
    backend = EndpointingCaptureBackend()
    service = _service(tmp_path, backend)

    result = asyncio.run(
        service.listen_and_submit_turn(
            session_id="voice-session",
            mode="ghost",
            play_response=True,
        )
    )
    status = service.status_snapshot()

    assert result.final_status == "completed"
    assert result.capture_result is not None
    assert result.capture_result.stop_reason == "speech_ended"
    assert result.voice_turn_result is not None
    assert result.voice_turn_result.turn is not None
    assert result.voice_turn_result.turn.transcript == "what time is it?"
    assert result.voice_turn_result.core_request is not None
    assert result.voice_turn_result.core_request.voice_mode == "stt"
    assert result.voice_turn_result.core_result is not None
    assert result.voice_turn_result.core_result.route_family == "clock"
    assert result.playback_result is not None
    assert result.playback_result.status == "completed"
    assert backend.started == 1
    assert backend.waited == 1
    assert backend.stopped == 1
    assert service.core_bridge.calls[0]["message"] == "what time is it?"
    assert status["voice_input"]["last_listen_result"]["endpoint_reason"] == "speech_ended"
    assert status["voice_input"]["last_voice_dispatch_result"]["core_result_state"] == "completed"
    assert status["voice_input"]["raw_audio_logged"] is False
    assert status["voice_input"]["raw_secret_logged"] is False


def test_l6_manual_listen_no_speech_does_not_call_stt_or_core(tmp_path: Path) -> None:
    backend = EndpointingCaptureBackend(
        endpoint_reason="no_speech_detected",
        speech_detected=False,
        audio_bytes=b"RIFF silence",
    )
    service = _service(tmp_path, backend)

    result = asyncio.run(
        service.listen_and_submit_turn(
            session_id="voice-session",
            mode="ghost",
            play_response=True,
        )
    )
    status = service.status_snapshot()

    assert result.final_status == "no_speech_detected"
    assert result.capture_result is not None
    assert result.capture_result.status == "failed"
    assert result.capture_result.error_code == "no_speech_detected"
    assert result.voice_turn_result is None
    assert result.playback_result is None
    assert service.core_bridge.calls == []
    assert service.last_transcription_result is None
    assert status["voice_input"]["last_skip_reason"] == "no_speech_detected"
    assert status["voice_input"]["last_transcription_result"] is None
