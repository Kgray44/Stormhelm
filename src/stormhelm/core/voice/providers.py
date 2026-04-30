from __future__ import annotations

import asyncio
import inspect
import struct
import sys
import tempfile
import threading
import time
import wave
from collections.abc import AsyncIterable
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

import httpx

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceRealtimeConfig
from stormhelm.config.models import VoiceVADConfig
from stormhelm.config.models import VoiceWakeConfig
from stormhelm.core.voice.availability import VoiceAvailability
from stormhelm.core.voice.availability import compute_voice_availability
from stormhelm.core.voice.models import VoiceAudioInput
from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.models import VoiceActivityEvent
from stormhelm.core.voice.models import VoiceCaptureRequest
from stormhelm.core.voice.models import VoiceCaptureResult
from stormhelm.core.voice.models import VoiceCaptureSession
from stormhelm.core.voice.models import VoiceLivePlaybackChunkResult
from stormhelm.core.voice.models import VoiceLivePlaybackRequest
from stormhelm.core.voice.models import VoiceLivePlaybackResult
from stormhelm.core.voice.models import VoiceLivePlaybackSession
from stormhelm.core.voice.models import VoicePlaybackRequest
from stormhelm.core.voice.models import VoicePlaybackPrewarmRequest
from stormhelm.core.voice.models import VoicePlaybackPrewarmResult
from stormhelm.core.voice.models import VoicePlaybackResult
from stormhelm.core.voice.models import VoiceProviderPrewarmRequest
from stormhelm.core.voice.models import VoiceProviderPrewarmResult
from stormhelm.core.voice.models import VoiceRealtimeSession
from stormhelm.core.voice.models import VoiceRealtimeTranscriptEvent
from stormhelm.core.voice.models import VoiceSpeechRequest
from stormhelm.core.voice.models import VoiceSpeechSynthesisResult
from stormhelm.core.voice.models import VoiceStreamingTTSChunk
from stormhelm.core.voice.models import VoiceStreamingTTSRequest
from stormhelm.core.voice.models import VoiceStreamingTTSResult
from stormhelm.core.voice.models import VoiceTranscriptionResult
from stormhelm.core.voice.models import VoiceVADSession
from stormhelm.core.voice.models import VoiceWakeEvent
from stormhelm.shared.time import utc_now_iso


VoiceStreamingChunkCallback = Callable[
    [VoiceStreamingTTSChunk], Awaitable[None] | None
]


async def _dispatch_streaming_chunk(
    callback: VoiceStreamingChunkCallback | None,
    chunk: VoiceStreamingTTSChunk,
) -> None:
    if callback is None:
        return
    result = callback(chunk)
    if inspect.isawaitable(result):
        await result


@dataclass(slots=True, frozen=True)
class VoiceProviderOperationResult:
    ok: bool
    status: str
    provider_name: str
    error_code: str | None = None
    error_message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class VoiceProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_mock(self) -> bool: ...

    def get_availability(self) -> VoiceAvailability: ...

    def create_session(self) -> VoiceProviderOperationResult: ...

    def close_session(
        self, session_id: str | None = None
    ) -> VoiceProviderOperationResult: ...

    def submit_text_turn(
        self, text: str, *, session_id: str | None = None
    ) -> VoiceProviderOperationResult: ...


@runtime_checkable
class SpeechToTextProvider(Protocol):
    def transcribe_audio(
        self,
        audio: VoiceAudioInput | bytes | None = None,
        *,
        content_type: str | None = None,
    ) -> (
        VoiceProviderOperationResult
        | VoiceTranscriptionResult
        | Awaitable[VoiceTranscriptionResult]
    ): ...


@runtime_checkable
class TextToSpeechProvider(Protocol):
    def synthesize_speech(
        self,
        text: str | VoiceSpeechRequest,
    ) -> (
        VoiceProviderOperationResult
        | VoiceSpeechSynthesisResult
        | Awaitable[VoiceSpeechSynthesisResult]
    ): ...

    def stream_speech(
        self,
        request: VoiceStreamingTTSRequest,
    ) -> VoiceStreamingTTSResult | Awaitable[VoiceStreamingTTSResult]: ...

    def stream_speech_progressive(
        self,
        request: VoiceStreamingTTSRequest,
        on_chunk: VoiceStreamingChunkCallback,
    ) -> VoiceStreamingTTSResult | Awaitable[VoiceStreamingTTSResult]: ...

    def prewarm_speech_provider(
        self,
        request: VoiceProviderPrewarmRequest,
    ) -> VoiceProviderPrewarmResult: ...


@runtime_checkable
class RealtimeVoiceProvider(Protocol):
    def start_listening(self) -> VoiceProviderOperationResult: ...

    def stop_listening(self) -> VoiceProviderOperationResult: ...


@runtime_checkable
class RealtimeTranscriptionProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_mock(self) -> bool: ...

    def get_availability(self) -> dict[str, Any]: ...

    def create_session(
        self,
        *,
        session_id: str | None = None,
        source: str = "test",
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeSession: ...

    def start_session(self, realtime_session_id: str) -> VoiceRealtimeSession: ...

    def close_session(
        self, realtime_session_id: str | None = None, *, reason: str = "closed"
    ) -> VoiceRealtimeSession: ...

    def get_active_session(self) -> VoiceRealtimeSession | None: ...

    def simulate_partial_transcript(
        self,
        transcript: str,
        *,
        realtime_session_id: str | None = None,
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeTranscriptEvent: ...

    def simulate_final_transcript(
        self,
        transcript: str,
        *,
        realtime_session_id: str | None = None,
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeTranscriptEvent: ...


@runtime_checkable
class WakeWordProvider(Protocol):
    def get_availability(self) -> dict[str, Any] | VoiceAvailability: ...

    def start_wake_monitoring(self) -> VoiceProviderOperationResult: ...

    def stop_wake_monitoring(self) -> VoiceProviderOperationResult: ...

    def simulate_wake(
        self,
        *,
        session_id: str | None = None,
        confidence: float | None = None,
        source: str = "mock",
    ) -> VoiceWakeEvent: ...

    def get_active_wake_session(self) -> Any | None: ...

    def start_wake_detection(self) -> VoiceProviderOperationResult: ...

    def stop_wake_detection(self) -> VoiceProviderOperationResult: ...


@runtime_checkable
class VoiceActivityDetector(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_mock(self) -> bool: ...

    def get_availability(self) -> dict[str, Any]: ...

    def start_detection(
        self,
        *,
        capture_id: str | None = None,
        listen_window_id: str | None = None,
        session_id: str | None = None,
    ) -> VoiceVADSession: ...

    def stop_detection(
        self,
        vad_session_id: str | None = None,
        *,
        reason: str = "stopped",
    ) -> VoiceVADSession: ...

    def simulate_speech_started(
        self,
        *,
        confidence: float | None = None,
    ) -> VoiceActivityEvent: ...

    def simulate_speech_stopped(
        self,
        *,
        confidence: float | None = None,
        duration_ms: int | None = None,
    ) -> VoiceActivityEvent: ...

    def get_active_detection(self) -> VoiceVADSession | None: ...


@runtime_checkable
class WakeBackend(Protocol):
    backend_name: str
    dependency_name: str
    platform_name: str

    def get_availability(self, config: VoiceWakeConfig) -> dict[str, Any]: ...

    def start(
        self,
        config: VoiceWakeConfig,
        on_wake: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]: ...

    def stop(self, handle: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class AudioInputProvider(Protocol):
    def start_audio_input(self) -> VoiceProviderOperationResult: ...

    def stop_audio_input(self) -> VoiceProviderOperationResult: ...


@runtime_checkable
class AudioOutputProvider(Protocol):
    def start_audio_output(self) -> VoiceProviderOperationResult: ...

    def stop_audio_output(self) -> VoiceProviderOperationResult: ...


@runtime_checkable
class VoiceCaptureProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_mock(self) -> bool: ...

    def get_availability(self) -> dict[str, Any]: ...

    def start_capture(
        self,
        request: VoiceCaptureRequest,
    ) -> (
        VoiceCaptureSession
        | VoiceCaptureResult
        | Awaitable[VoiceCaptureSession | VoiceCaptureResult]
    ): ...

    def stop_capture(
        self,
        capture_id: str | None = None,
        *,
        reason: str = "user_released",
    ) -> VoiceCaptureResult | Awaitable[VoiceCaptureResult]: ...

    def cancel_capture(
        self,
        capture_id: str | None = None,
        *,
        reason: str = "user_cancelled",
    ) -> VoiceCaptureResult | Awaitable[VoiceCaptureResult]: ...

    def get_active_capture(self) -> VoiceCaptureSession | None: ...


@runtime_checkable
class LocalCaptureBackend(Protocol):
    dependency_name: str
    platform_name: str

    def get_availability(self, config: VoiceConfig) -> dict[str, Any]: ...

    def start(
        self, request: VoiceCaptureRequest, output_path: Path
    ) -> dict[str, Any]: ...

    def stop(self, handle: dict[str, Any], *, reason: str) -> dict[str, Any]: ...

    def wait_for_endpoint(
        self, handle: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]: ...

    def cancel(self, handle: dict[str, Any], *, reason: str) -> None: ...

    def cleanup(self, path: str | Path) -> None: ...


@dataclass(slots=True)
class MockCaptureProvider:
    provider_name: str = "mock"
    available: bool = True
    blocked: bool = False
    fail_capture: bool = False
    timeout_on_stop: bool = False
    error_code: str | None = None
    error_message: str | None = None
    capture_audio_bytes: bytes = b"mock captured audio"
    duration_ms: int = 1000
    endpoint_reason: str = "speech_ended"
    speech_detected: bool = True
    start_call_count: int = 0
    stop_call_count: int = 0
    cancel_call_count: int = 0
    _active_capture: VoiceCaptureSession | None = field(
        default=None, init=False, repr=False
    )

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return True

    def get_availability(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "available": self.available and not self.blocked,
            "unavailable_reason": None if self.available else "provider_unavailable",
            "mock": True,
        }

    def start_capture(
        self, request: VoiceCaptureRequest
    ) -> VoiceCaptureSession | VoiceCaptureResult:
        if not request.allowed_to_capture:
            return self._result(
                request,
                status="blocked",
                ok=False,
                error_code=request.blocked_reason or "capture_blocked",
                error_message=f"Capture request blocked: {request.blocked_reason or 'capture_blocked'}.",
            )
        if self._active_capture is not None:
            return self._result(
                request,
                status="blocked",
                ok=False,
                error_code="active_capture_exists",
                error_message="A push-to-talk capture is already active.",
            )
        if not self.available:
            return self._result(
                request,
                status="unavailable",
                ok=False,
                error_code="provider_unavailable",
                error_message="Mock capture provider is unavailable.",
            )
        if self.blocked:
            return self._result(
                request,
                status="blocked",
                ok=False,
                error_code="capture_blocked",
                error_message="Mock capture provider blocked capture.",
            )
        self.start_call_count += 1
        if self.fail_capture:
            return self._result(
                request,
                status="failed",
                ok=False,
                error_code=self.error_code or "capture_failed",
                error_message=self.error_message
                or "Mock capture provider failed to start.",
            )
        session = VoiceCaptureSession(
            capture_request_id=request.capture_request_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            provider=self.provider_name,
            device=request.device,
            status="recording",
            max_duration_ms=request.max_duration_ms,
            metadata={
                "source": request.source,
                "mock": True,
                "request": request.to_metadata(),
            },
            microphone_was_active=False,
            always_listening_claimed=False,
            wake_word_claimed=False,
        )
        self._active_capture = session
        return session

    def stop_capture(
        self,
        capture_id: str | None = None,
        *,
        reason: str = "user_released",
    ) -> VoiceCaptureResult:
        active = self._active_capture
        if active is None or (capture_id and capture_id != active.capture_id):
            return VoiceCaptureResult(
                ok=False,
                capture_request_id=None,
                capture_id=capture_id,
                status="unavailable",
                provider=self.provider_name,
                device="default",
                stopped_at=utc_now_iso(),
                stop_reason=reason,
                error_code="no_active_capture",
                error_message="No active push-to-talk capture exists.",
                raw_audio_persisted=False,
                microphone_was_active=False,
                always_listening_claimed=False,
                wake_word_claimed=False,
            )
        self.stop_call_count += 1
        self._active_capture = None
        if self.timeout_on_stop:
            return VoiceCaptureResult(
                ok=False,
                capture_request_id=active.capture_request_id,
                capture_id=active.capture_id,
                status="timeout",
                provider=self.provider_name,
                device=active.device,
                duration_ms=active.max_duration_ms,
                stopped_at=utc_now_iso(),
                stop_reason=reason,
                error_code="capture_timeout",
                error_message="Mock capture reached the configured max duration.",
                metadata={"mock": True},
                raw_audio_persisted=False,
                microphone_was_active=False,
                always_listening_claimed=False,
                wake_word_claimed=False,
            )
        payload = bytes(self.capture_audio_bytes or b"")
        if len(payload) > int(
            active.metadata.get("request", {}).get("max_audio_bytes", 0) or 0
        ):
            return VoiceCaptureResult(
                ok=False,
                capture_request_id=active.capture_request_id,
                capture_id=active.capture_id,
                status="failed",
                provider=self.provider_name,
                device=active.device,
                duration_ms=self.duration_ms,
                size_bytes=len(payload),
                stopped_at=utc_now_iso(),
                stop_reason=reason,
                error_code="captured_audio_too_large",
                error_message="Captured audio exceeded the configured size limit.",
                metadata={"mock": True},
                raw_audio_persisted=False,
                microphone_was_active=False,
                always_listening_claimed=False,
                wake_word_claimed=False,
            )
        audio = VoiceAudioInput.from_bytes(
            payload,
            filename=f"{active.capture_id}.wav",
            mime_type="audio/wav",
            duration_ms=self.duration_ms,
            sample_rate=int(
                active.metadata.get("request", {}).get("sample_rate", 16000) or 16000
            ),
            channels=int(active.metadata.get("request", {}).get("channels", 1) or 1),
            source="mock",
            metadata={
                "capture_id": active.capture_id,
                "capture_request_id": active.capture_request_id,
                "capture_source": "push_to_talk",
                "provider": self.provider_name,
                "device": active.device,
                "mock": True,
            },
        )
        return VoiceCaptureResult(
            ok=True,
            capture_request_id=active.capture_request_id,
            capture_id=active.capture_id,
            status="completed",
            provider=self.provider_name,
            device=active.device,
            audio_input=audio,
            duration_ms=self.duration_ms,
            size_bytes=audio.size_bytes,
            stopped_at=utc_now_iso(),
            stop_reason=reason,
            metadata={"mock": True, "audio_input": audio.to_metadata()},
            raw_audio_persisted=False,
            microphone_was_active=False,
            always_listening_claimed=False,
            wake_word_claimed=False,
        )

    def cancel_capture(
        self,
        capture_id: str | None = None,
        *,
        reason: str = "user_cancelled",
    ) -> VoiceCaptureResult:
        active = self._active_capture
        if active is None or (capture_id and capture_id != active.capture_id):
            return VoiceCaptureResult(
                ok=False,
                capture_request_id=None,
                capture_id=capture_id,
                status="unavailable",
                provider=self.provider_name,
                device="default",
                stopped_at=utc_now_iso(),
                stop_reason=reason,
                error_code="no_active_capture",
                error_message="No active push-to-talk capture exists.",
            )
        self.cancel_call_count += 1
        self._active_capture = None
        return VoiceCaptureResult(
            ok=False,
            capture_request_id=active.capture_request_id,
            capture_id=active.capture_id,
            status="cancelled",
            provider=self.provider_name,
            device=active.device,
            stopped_at=utc_now_iso(),
            stop_reason=reason,
            metadata={"mock": True},
            raw_audio_persisted=False,
            microphone_was_active=False,
            always_listening_claimed=False,
            wake_word_claimed=False,
        )

    def wait_for_endpoint(
        self,
        capture_id: str | None = None,
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        active = self._active_capture
        del timeout_ms
        if active is None or (capture_id and capture_id != active.capture_id):
            return {
                "ok": False,
                "reason": "no_active_capture",
                "error_code": "no_active_capture",
                "speech_detected": False,
                "raw_audio_logged": False,
                "raw_secret_logged": False,
            }
        return {
            "ok": True,
            "capture_id": active.capture_id,
            "reason": self.endpoint_reason,
            "speech_detected": self.speech_detected,
            "speech_detected_ms": 0 if self.speech_detected else None,
            "endpoint_ms": self.duration_ms,
            "raw_audio_logged": False,
            "raw_secret_logged": False,
        }

    def get_active_capture(self) -> VoiceCaptureSession | None:
        return self._active_capture

    def _result(
        self,
        request: VoiceCaptureRequest,
        *,
        status: str,
        ok: bool,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> VoiceCaptureResult:
        return VoiceCaptureResult(
            ok=ok,
            capture_request_id=request.capture_request_id,
            capture_id=None,
            status=status,
            provider=self.provider_name,
            device=request.device,
            stopped_at=utc_now_iso(),
            error_code=error_code,
            error_message=error_message,
            metadata={"request": request.to_metadata()},
            raw_audio_persisted=False,
            microphone_was_active=False,
            always_listening_claimed=False,
            wake_word_claimed=False,
        )


@dataclass(slots=True)
class SoundDeviceWavCaptureBackend:
    dependency_name: str = "sounddevice"
    platform_name: str = field(default_factory=lambda: sys.platform)

    def get_availability(self, config: VoiceConfig) -> dict[str, Any]:
        supported = sys.platform.startswith(("win", "darwin", "linux"))
        base: dict[str, Any] = {
            "platform": self.platform_name,
            "platform_supported": supported,
            "dependency": self.dependency_name,
            "dependency_available": False,
            "device_configured": config.capture.device,
            "device_available": None,
            "permission_state": "unknown",
        }
        if not supported:
            return {
                **base,
                "available": False,
                "unavailable_reason": "unsupported_platform",
            }
        try:
            import sounddevice as sd  # type: ignore[import-not-found]
        except Exception:
            return {
                **base,
                "available": False,
                "unavailable_reason": "dependency_missing",
            }

        base["dependency_available"] = True
        try:
            device = (
                None
                if str(config.capture.device or "default").strip().lower() == "default"
                else config.capture.device
            )
            sd.query_devices(device=device, kind="input")
        except Exception as error:
            return {
                **base,
                "available": False,
                "unavailable_reason": "device_unavailable",
                "device_available": False,
                "provider_error": str(error),
            }
        return {
            **base,
            "available": True,
            "unavailable_reason": None,
            "device_available": True,
        }

    def start(self, request: VoiceCaptureRequest, output_path: Path) -> dict[str, Any]:
        import sounddevice as sd  # type: ignore[import-not-found]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wav_file = wave.open(str(output_path), "wb")
        wav_file.setnchannels(request.channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(request.sample_rate)
        endpointing_enabled = bool(
            dict(request.metadata or {}).get("endpointing_enabled")
        )
        endpoint_silence_ms = int(
            dict(request.metadata or {}).get("endpoint_silence_ms") or 700
        )
        speech_start_rms = self._rms_threshold(
            dict(request.metadata or {}).get("speech_start_threshold"),
            fallback=650,
        )
        speech_stop_rms = self._rms_threshold(
            dict(request.metadata or {}).get("speech_stop_threshold"),
            fallback=420,
        )
        endpoint_event = threading.Event()
        handle: dict[str, Any] = {
            "output_path": str(output_path),
            "wav_file": wav_file,
            "bytes_written": 0,
            "overflow": False,
            "timed_out": False,
            "started_at": time.perf_counter(),
            "platform": self.platform_name,
            "dependency": self.dependency_name,
            "permission_state": "granted",
            "endpointing_enabled": endpointing_enabled,
            "endpoint_event": endpoint_event,
            "endpoint_reason": None,
            "endpoint_silence_ms": endpoint_silence_ms,
            "speech_start_rms": speech_start_rms,
            "speech_stop_rms": speech_stop_rms,
            "speech_detected": False,
            "speech_detected_ms": None,
            "last_speech_ms": None,
            "last_audio_level_rms": 0,
            "last_audio_level_peak": 0,
        }

        def callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            del frames, time_info, status
            payload = indata.tobytes()
            remaining = request.max_audio_bytes - int(handle["bytes_written"])
            if remaining <= 0:
                handle["overflow"] = True
                raise sd.CallbackStop
            if len(payload) > remaining:
                payload = payload[:remaining]
                handle["overflow"] = True
            wav_file.writeframes(payload)
            handle["bytes_written"] = int(handle["bytes_written"]) + len(payload)
            self._update_endpoint_state(handle, payload, request=request)
            if handle["overflow"]:
                self._mark_endpoint(handle, "max_duration")
                raise sd.CallbackStop
            if handle.get("endpoint_reason"):
                raise sd.CallbackStop

        device = None if request.device.strip().lower() == "default" else request.device
        stream = sd.InputStream(
            samplerate=request.sample_rate,
            channels=request.channels,
            dtype="int16",
            device=device,
            callback=callback,
        )
        handle["stream"] = stream
        try:
            stream.start()
        except Exception:
            wav_file.close()
            output_path.unlink(missing_ok=True)
            raise
        return handle

    def wait_for_endpoint(
        self, handle: dict[str, Any], *, timeout_ms: int
    ) -> dict[str, Any]:
        endpoint_event = handle.get("endpoint_event")
        if not isinstance(endpoint_event, threading.Event):
            return self._endpoint_payload(handle, reason="manual_stop_required")
        timeout = max(0.001, timeout_ms / 1000.0)
        if not endpoint_event.wait(timeout):
            self._mark_endpoint(handle, "max_duration")
            stream = handle.get("stream")
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
        return self._endpoint_payload(handle)

    def stop(self, handle: dict[str, Any], *, reason: str) -> dict[str, Any]:
        del reason
        stream = handle.get("stream")
        wav_file = handle.get("wav_file")
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        if wav_file is not None:
            wav_file.close()
        output_path = Path(str(handle.get("output_path") or ""))
        elapsed_ms = int(
            (time.perf_counter() - float(handle.get("started_at", time.perf_counter())))
            * 1000
        )
        return {
            "output_path": str(output_path),
            "duration_ms": elapsed_ms,
            "size_bytes": output_path.stat().st_size
            if output_path.exists()
            else int(handle.get("bytes_written", 0)),
            "timed_out": bool(handle.get("timed_out")),
            "metadata": {
                "dependency": self.dependency_name,
                "platform": self.platform_name,
                "overflow": bool(handle.get("overflow")),
                "endpoint": self._endpoint_payload(handle),
            },
            "endpoint": self._endpoint_payload(handle),
        }

    def timeout(self, handle: dict[str, Any]) -> None:
        handle["timed_out"] = True
        self._mark_endpoint(handle, "max_duration")
        stream = handle.get("stream")
        if stream is not None:
            stream.stop()

    def cancel(self, handle: dict[str, Any], *, reason: str) -> None:
        del reason
        stream = handle.get("stream")
        wav_file = handle.get("wav_file")
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        if wav_file is not None:
            wav_file.close()
        self.cleanup(str(handle.get("output_path") or ""))

    def cleanup(self, path: str | Path) -> None:
        if path:
            Path(path).unlink(missing_ok=True)

    def _update_endpoint_state(
        self,
        handle: dict[str, Any],
        payload: bytes,
        *,
        request: VoiceCaptureRequest,
    ) -> None:
        if not handle.get("endpointing_enabled") or handle.get("endpoint_reason"):
            return
        elapsed_ms = int(
            (time.perf_counter() - float(handle.get("started_at", time.perf_counter())))
            * 1000
        )
        rms, peak = self._pcm16_levels(payload)
        handle["last_audio_level_rms"] = rms
        handle["last_audio_level_peak"] = peak
        if rms >= int(handle.get("speech_start_rms") or 650):
            handle["speech_detected"] = True
            handle["last_speech_ms"] = elapsed_ms
            if handle.get("speech_detected_ms") is None:
                handle["speech_detected_ms"] = elapsed_ms
        elif handle.get("speech_detected") and rms >= int(
            handle.get("speech_stop_rms") or 420
        ):
            handle["last_speech_ms"] = elapsed_ms

        if bool(handle.get("speech_detected")):
            last_speech_ms = int(handle.get("last_speech_ms") or elapsed_ms)
            silence_ms = int(handle.get("endpoint_silence_ms") or 700)
            if elapsed_ms - last_speech_ms >= silence_ms:
                self._mark_endpoint(handle, "speech_ended")
                return
        if elapsed_ms >= int(request.max_duration_ms or 0):
            self._mark_endpoint(
                handle,
                "max_duration" if handle.get("speech_detected") else "no_speech_detected",
            )

    def _mark_endpoint(self, handle: dict[str, Any], reason: str) -> None:
        if not handle.get("endpoint_reason"):
            handle["endpoint_reason"] = reason
        if reason == "max_duration":
            handle["timed_out"] = True
        endpoint_event = handle.get("endpoint_event")
        if isinstance(endpoint_event, threading.Event):
            endpoint_event.set()

    def _endpoint_payload(
        self, handle: dict[str, Any], *, reason: str | None = None
    ) -> dict[str, Any]:
        resolved_reason = str(
            reason or handle.get("endpoint_reason") or "manual_stop_required"
        )
        elapsed_ms = int(
            (time.perf_counter() - float(handle.get("started_at", time.perf_counter())))
            * 1000
        )
        return {
            "reason": resolved_reason,
            "speech_detected": bool(handle.get("speech_detected")),
            "speech_detected_ms": handle.get("speech_detected_ms"),
            "endpoint_ms": elapsed_ms,
            "silence_ms": handle.get("endpoint_silence_ms"),
            "level_rms": int(handle.get("last_audio_level_rms") or 0),
            "level_peak": int(handle.get("last_audio_level_peak") or 0),
            "raw_audio_logged": False,
            "raw_secret_logged": False,
        }

    def _pcm16_levels(self, payload: bytes) -> tuple[int, int]:
        usable = len(payload) - (len(payload) % 2)
        if usable <= 0:
            return 0, 0
        count = usable // 2
        total = 0
        peak = 0
        try:
            for (sample,) in struct.iter_unpack("<h", payload[:usable]):
                total += sample * sample
                level = abs(sample)
                if level > peak:
                    peak = level
        except Exception:
            return 0, 0
        return int((total / max(1, count)) ** 0.5), int(peak)

    def _rms_threshold(self, value: Any, *, fallback: int) -> int:
        try:
            threshold = float(value)
        except (TypeError, ValueError):
            return fallback
        if threshold <= 0:
            return 0
        if threshold <= 1:
            return max(1, int(threshold * 32767))
        return int(threshold)


@dataclass(slots=True)
class LocalCaptureProvider:
    config: VoiceConfig
    provider_name: str = "local"
    backend: LocalCaptureBackend | None = None
    temp_dir: str | Path | None = None
    _active_capture: VoiceCaptureSession | None = field(
        default=None, init=False, repr=False
    )
    _active_handle: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _active_request: VoiceCaptureRequest | None = field(
        default=None, init=False, repr=False
    )
    _active_output_path: Path | None = field(default=None, init=False, repr=False)
    _timeout_timer: threading.Timer | None = field(default=None, init=False, repr=False)
    _timed_out_capture_id: str | None = field(default=None, init=False, repr=False)
    _permission_error: str | None = field(default=None, init=False, repr=False)
    _last_cleanup_warning: str | None = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return False

    def __post_init__(self) -> None:
        if self.backend is None:
            self.backend = SoundDeviceWavCaptureBackend()

    def get_availability(self) -> dict[str, Any]:
        base = {
            "provider": self.provider_name,
            "mock": False,
            "local_capture_enabled": bool(self.config.capture.enabled),
            "allow_dev_capture": bool(self.config.capture.allow_dev_capture),
            "device_configured": self.config.capture.device,
            "device": self.config.capture.device,
            "platform": getattr(self.backend, "platform_name", sys.platform),
            "dependency": getattr(self.backend, "dependency_name", "unknown"),
            "platform_supported": None,
            "dependency_available": None,
            "device_available": None,
            "permission_state": "unknown",
            "permission_error": self._permission_error,
            "cleanup_warning": self._last_cleanup_warning,
        }
        if not self.config.capture.enabled:
            return {
                **base,
                "available": False,
                "unavailable_reason": "capture_disabled",
            }
        if not self.config.capture.allow_dev_capture:
            return {
                **base,
                "available": False,
                "unavailable_reason": "dev_capture_not_allowed",
            }
        if self.backend is None:
            return {
                **base,
                "available": False,
                "unavailable_reason": "provider_not_configured",
            }
        try:
            backend_availability = dict(self.backend.get_availability(self.config))
        except Exception as error:
            return {
                **base,
                "available": False,
                "unavailable_reason": "provider_unavailable",
                "provider_error": str(error),
            }
        reason = backend_availability.get("unavailable_reason")
        available = bool(backend_availability.get("available"))
        return {
            **base,
            **backend_availability,
            "provider": self.provider_name,
            "available": available,
            "unavailable_reason": None
            if available
            else str(reason or "provider_unavailable"),
            "mock": False,
            "permission_error": self._permission_error
            or backend_availability.get("permission_error"),
        }

    def start_capture(
        self, request: VoiceCaptureRequest
    ) -> VoiceCaptureSession | VoiceCaptureResult:
        if not request.allowed_to_capture:
            return self._result(
                request,
                status="blocked",
                ok=False,
                error_code=request.blocked_reason or "capture_blocked",
                error_message=f"Capture request blocked: {request.blocked_reason or 'capture_blocked'}.",
            )
        if self._active_capture is not None:
            return self._result(
                request,
                status="blocked",
                ok=False,
                error_code="active_capture_exists",
                error_message="A push-to-talk capture is already active.",
            )

        availability = self.get_availability()
        if not availability.get("available"):
            reason = str(
                availability.get("unavailable_reason") or "provider_unavailable"
            )
            status = (
                "blocked"
                if reason in {"capture_disabled", "dev_capture_not_allowed"}
                else "unavailable"
            )
            return self._result(
                request,
                status=status,
                ok=False,
                error_code=reason,
                error_message=f"Local capture unavailable: {reason}.",
                metadata={"availability": availability},
            )

        output_path = self._capture_output_path(request)
        try:
            handle = (
                self.backend.start(request, output_path)
                if self.backend is not None
                else {}
            )
        except PermissionError as error:
            self._permission_error = str(error)
            return self._result(
                request,
                status="unavailable",
                ok=False,
                error_code="permission_denied",
                error_message="Local capture permission was denied.",
                metadata={
                    "availability": {**availability, "permission_error": str(error)}
                },
            )
        except Exception as error:
            return self._result(
                request,
                status="failed",
                ok=False,
                error_code="provider_error",
                error_message=str(error),
                metadata={"availability": availability},
            )

        if not isinstance(handle, dict):
            handle = {"raw_handle": handle}
        handle.setdefault("output_path", str(output_path))
        capture_id = f"voice-capture-{uuid4().hex[:12]}"
        metadata = {
            "source": request.source,
            "local_capture": True,
            "request": request.to_metadata(),
            "availability": availability,
            "platform": handle.get("platform", availability.get("platform")),
            "dependency": handle.get("dependency", availability.get("dependency")),
            "permission_state": handle.get(
                "permission_state", availability.get("permission_state", "unknown")
            ),
            "device_available": handle.get(
                "device_available", availability.get("device_available")
            ),
            "file": self._file_metadata(output_path),
        }
        session = VoiceCaptureSession(
            capture_id=capture_id,
            capture_request_id=request.capture_request_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            provider=self.provider_name,
            device=request.device,
            status="recording",
            max_duration_ms=request.max_duration_ms,
            metadata=metadata,
            microphone_was_active=True,
            always_listening_claimed=False,
            wake_word_claimed=False,
        )
        self._active_capture = session
        self._active_handle = handle
        self._active_request = request
        self._active_output_path = output_path
        self._timed_out_capture_id = None
        self._start_timeout_timer(capture_id, request)
        return session

    def stop_capture(
        self,
        capture_id: str | None = None,
        *,
        reason: str = "user_released",
    ) -> VoiceCaptureResult:
        active = self._active_capture
        if active is None or (capture_id and capture_id != active.capture_id):
            return self._no_active_result(capture_id, reason=reason)
        request = self._active_request
        handle = self._active_handle or {}
        output_path = self._active_output_path
        self._cancel_timeout_timer()
        try:
            payload = (
                self.backend.stop(handle, reason=reason)
                if self.backend is not None
                else {}
            )
        except PermissionError as error:
            self._permission_error = str(error)
            result = VoiceCaptureResult(
                ok=False,
                capture_request_id=active.capture_request_id,
                capture_id=active.capture_id,
                status="unavailable",
                provider=self.provider_name,
                device=active.device,
                stopped_at=utc_now_iso(),
                stop_reason=reason,
                error_code="permission_denied",
                error_message="Local capture permission was denied.",
                metadata={"capture": active.to_dict()},
                raw_audio_persisted=False,
                microphone_was_active=True,
                always_listening_claimed=False,
                wake_word_claimed=False,
            )
            self._clear_active_capture(cleanup_path=output_path)
            return result
        except Exception as error:
            result = VoiceCaptureResult(
                ok=False,
                capture_request_id=active.capture_request_id,
                capture_id=active.capture_id,
                status="failed",
                provider=self.provider_name,
                device=active.device,
                stopped_at=utc_now_iso(),
                stop_reason=reason,
                error_code="provider_error",
                error_message=str(error),
                metadata={"capture": active.to_dict()},
                raw_audio_persisted=False,
                microphone_was_active=True,
                always_listening_claimed=False,
                wake_word_claimed=False,
            )
            self._clear_active_capture(cleanup_path=output_path)
            return result

        if not isinstance(payload, dict):
            payload = {}
        output_path = Path(str(payload.get("output_path") or output_path or ""))
        endpoint = self._endpoint_payload_from(payload, handle)
        endpoint_reason = str(endpoint.get("reason") or reason or "").strip()
        effective_stop_reason = endpoint_reason or reason
        duration_ms = self._optional_int(payload.get("duration_ms"))
        size_bytes = self._resolved_size(output_path, payload.get("size_bytes"))
        timed_out = (
            bool(payload.get("timed_out"))
            or self._timed_out_capture_id == active.capture_id
        )
        file_metadata = self._file_metadata(output_path, size_bytes=size_bytes)
        base_metadata = {
            "local_capture": True,
            "capture": active.to_dict(),
            "file": file_metadata,
            "backend": dict(payload.get("metadata") or {}),
            "endpoint": endpoint,
            "cleanup_warning": self._last_cleanup_warning,
        }
        if (
            endpoint_reason == "no_speech_detected"
            and self._request_endpointing_enabled(request)
        ):
            self._clear_active_capture(cleanup_path=output_path)
            return VoiceCaptureResult(
                ok=False,
                capture_request_id=active.capture_request_id,
                capture_id=active.capture_id,
                status="failed",
                provider=self.provider_name,
                device=active.device,
                duration_ms=duration_ms,
                size_bytes=size_bytes,
                stopped_at=utc_now_iso(),
                stop_reason="no_speech_detected",
                error_code="no_speech_detected",
                error_message="No speech was detected during the listen session.",
                metadata=base_metadata,
                raw_audio_persisted=False,
                microphone_was_active=True,
                always_listening_claimed=False,
                wake_word_claimed=False,
            )
        if timed_out:
            self._clear_active_capture(cleanup_path=output_path)
            return VoiceCaptureResult(
                ok=False,
                capture_request_id=active.capture_request_id,
                capture_id=active.capture_id,
                status="timeout",
                provider=self.provider_name,
                device=active.device,
                duration_ms=duration_ms or active.max_duration_ms,
                size_bytes=size_bytes,
                stopped_at=utc_now_iso(),
                stop_reason=effective_stop_reason,
                error_code="capture_timeout",
                error_message="Local capture reached the configured max duration.",
                metadata=base_metadata,
                raw_audio_persisted=False,
                microphone_was_active=True,
                always_listening_claimed=False,
                wake_word_claimed=False,
            )
        max_audio_bytes = (
            request.max_audio_bytes
            if request is not None
            else self.config.capture.max_audio_bytes
        )
        if size_bytes > max_audio_bytes:
            self._clear_active_capture(cleanup_path=output_path)
            return VoiceCaptureResult(
                ok=False,
                capture_request_id=active.capture_request_id,
                capture_id=active.capture_id,
                status="failed",
                provider=self.provider_name,
                device=active.device,
                duration_ms=duration_ms,
                size_bytes=size_bytes,
                stopped_at=utc_now_iso(),
                stop_reason=reason,
                error_code="captured_audio_too_large",
                error_message="Captured audio exceeded the configured size limit.",
                metadata=base_metadata,
                raw_audio_persisted=False,
                microphone_was_active=True,
                always_listening_claimed=False,
                wake_word_claimed=False,
            )
        if not output_path.exists() or not output_path.is_file() or size_bytes <= 0:
            self._clear_active_capture(cleanup_path=output_path)
            return VoiceCaptureResult(
                ok=False,
                capture_request_id=active.capture_request_id,
                capture_id=active.capture_id,
                status="failed",
                provider=self.provider_name,
                device=active.device,
                duration_ms=duration_ms,
                size_bytes=size_bytes,
                stopped_at=utc_now_iso(),
                stop_reason=reason,
                error_code="capture_audio_missing",
                error_message="Local capture did not produce a usable audio file.",
                metadata=base_metadata,
                raw_audio_persisted=False,
                microphone_was_active=True,
                always_listening_claimed=False,
                wake_word_claimed=False,
            )
        audio = VoiceAudioInput.from_file(
            output_path,
            mime_type=self._mime_type_for_format(
                request.format if request is not None else self.config.capture.format
            ),
            duration_ms=duration_ms,
            sample_rate=request.sample_rate
            if request is not None
            else self.config.capture.sample_rate,
            channels=request.channels
            if request is not None
            else self.config.capture.channels,
            metadata={
                "capture_id": active.capture_id,
                "capture_request_id": active.capture_request_id,
                "capture_source": "push_to_talk",
                "provider": self.provider_name,
                "device": active.device,
                "local_capture": True,
                "platform": active.metadata.get("platform"),
                "dependency": active.metadata.get("dependency"),
            },
        )
        result = VoiceCaptureResult(
            ok=True,
            capture_request_id=active.capture_request_id,
            capture_id=active.capture_id,
            status="completed",
            provider=self.provider_name,
            device=active.device,
            audio_input=audio,
            duration_ms=duration_ms,
            size_bytes=audio.size_bytes,
            stopped_at=utc_now_iso(),
            stop_reason=effective_stop_reason,
            metadata={**base_metadata, "audio_input": audio.to_metadata()},
            raw_audio_persisted=bool(request and request.persist_audio),
            microphone_was_active=True,
            always_listening_claimed=False,
            wake_word_claimed=False,
        )
        self._clear_active_capture(cleanup_path=None)
        return result

    def cancel_capture(
        self,
        capture_id: str | None = None,
        *,
        reason: str = "user_cancelled",
    ) -> VoiceCaptureResult:
        active = self._active_capture
        if active is None or (capture_id and capture_id != active.capture_id):
            return self._no_active_result(capture_id, reason=reason)
        handle = self._active_handle or {}
        output_path = self._active_output_path
        self._cancel_timeout_timer()
        try:
            if self.backend is not None:
                self.backend.cancel(handle, reason=reason)
        except Exception as error:
            self._last_cleanup_warning = str(error)
        result = VoiceCaptureResult(
            ok=False,
            capture_request_id=active.capture_request_id,
            capture_id=active.capture_id,
            status="cancelled",
            provider=self.provider_name,
            device=active.device,
            stopped_at=utc_now_iso(),
            stop_reason=reason,
            metadata={
                "local_capture": True,
                "capture": active.to_dict(),
                "file": self._file_metadata(output_path),
                "cleanup_warning": self._last_cleanup_warning,
            },
            raw_audio_persisted=False,
            microphone_was_active=True,
            always_listening_claimed=False,
            wake_word_claimed=False,
        )
        self._clear_active_capture(cleanup_path=output_path)
        return result

    def wait_for_endpoint(
        self,
        capture_id: str | None = None,
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        active = self._active_capture
        if active is None or (capture_id and capture_id != active.capture_id):
            return {
                "ok": False,
                "reason": "no_active_capture",
                "error_code": "no_active_capture",
                "speech_detected": False,
                "raw_audio_logged": False,
                "raw_secret_logged": False,
            }
        handle = self._active_handle or {}
        wait = getattr(self.backend, "wait_for_endpoint", None)
        if not callable(wait):
            return {
                "ok": True,
                "capture_id": active.capture_id,
                "reason": "manual_stop_required",
                "speech_detected": False,
                "raw_audio_logged": False,
                "raw_secret_logged": False,
            }
        payload = wait(
            handle,
            timeout_ms=timeout_ms or active.max_duration_ms or 30_000,
        )
        endpoint = dict(payload or {})
        endpoint.setdefault("ok", True)
        endpoint.setdefault("capture_id", active.capture_id)
        endpoint.setdefault("raw_audio_logged", False)
        endpoint.setdefault("raw_secret_logged", False)
        return endpoint

    def get_active_capture(self) -> VoiceCaptureSession | None:
        return self._active_capture

    def cleanup_capture_audio(self, audio_input: VoiceAudioInput | None) -> str | None:
        if audio_input is None or not audio_input.file_path:
            return None
        if not audio_input.transient or self.config.capture.persist_captured_audio:
            return None
        if not self.config.capture.delete_transient_after_turn:
            return None
        try:
            if self.backend is not None:
                self.backend.cleanup(audio_input.file_path)
            else:
                Path(audio_input.file_path).unlink(missing_ok=True)
        except Exception as error:
            self._last_cleanup_warning = str(error)
            return self._last_cleanup_warning
        self._last_cleanup_warning = None
        return None

    def _result(
        self,
        request: VoiceCaptureRequest,
        *,
        status: str,
        ok: bool,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceCaptureResult:
        return VoiceCaptureResult(
            ok=ok,
            capture_request_id=request.capture_request_id,
            capture_id=None,
            status=status,
            provider=self.provider_name,
            device=request.device,
            stopped_at=utc_now_iso(),
            error_code=error_code,
            error_message=error_message,
            metadata={"request": request.to_metadata(), **dict(metadata or {})},
            raw_audio_persisted=False,
            microphone_was_active=False,
            always_listening_claimed=False,
            wake_word_claimed=False,
        )

    def _no_active_result(
        self, capture_id: str | None, *, reason: str
    ) -> VoiceCaptureResult:
        return VoiceCaptureResult(
            ok=False,
            capture_request_id=None,
            capture_id=capture_id,
            status="unavailable",
            provider=self.provider_name,
            device=self.config.capture.device,
            stopped_at=utc_now_iso(),
            stop_reason=reason,
            error_code="no_active_capture",
            error_message="No active local capture exists.",
            raw_audio_persisted=False,
            microphone_was_active=False,
            always_listening_claimed=False,
            wake_word_claimed=False,
        )

    def _capture_output_path(self, request: VoiceCaptureRequest) -> Path:
        base = (
            Path(self.temp_dir)
            if self.temp_dir is not None
            else Path(tempfile.gettempdir()) / "stormhelm-voice-capture"
        )
        base.mkdir(parents=True, exist_ok=True)
        extension = str(request.format or "wav").strip().lower() or "wav"
        return base / f"{uuid4().hex}.{extension}"

    def _start_timeout_timer(
        self, capture_id: str, request: VoiceCaptureRequest
    ) -> None:
        self._cancel_timeout_timer()
        if (
            not self.config.capture.auto_stop_on_max_duration
            or request.max_duration_ms <= 0
        ):
            return
        timer = threading.Timer(
            request.max_duration_ms / 1000.0,
            self._mark_capture_timeout,
            args=(capture_id,),
        )
        timer.daemon = True
        self._timeout_timer = timer
        timer.start()

    def _cancel_timeout_timer(self) -> None:
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
        self._timeout_timer = None

    def _mark_capture_timeout(self, capture_id: str) -> None:
        if (
            self._active_capture is None
            or self._active_capture.capture_id != capture_id
        ):
            return
        self._timed_out_capture_id = capture_id
        handle = self._active_handle
        timeout = getattr(self.backend, "timeout", None)
        if callable(timeout) and handle is not None:
            try:
                timeout(handle)
            except Exception:
                return

    def _clear_active_capture(self, *, cleanup_path: Path | None) -> None:
        self._cancel_timeout_timer()
        if cleanup_path is not None and not self.config.capture.persist_captured_audio:
            try:
                if self.backend is not None:
                    self.backend.cleanup(cleanup_path)
                else:
                    cleanup_path.unlink(missing_ok=True)
            except Exception as error:
                self._last_cleanup_warning = str(error)
        self._active_capture = None
        self._active_handle = None
        self._active_request = None
        self._active_output_path = None
        self._timed_out_capture_id = None

    def _file_metadata(
        self, path: str | Path | None, *, size_bytes: int | None = None
    ) -> dict[str, Any]:
        if not path:
            return {"file_path": None, "size_bytes": size_bytes}
        resolved = Path(path)
        resolved_size = (
            size_bytes
            if size_bytes is not None
            else (
                resolved.stat().st_size
                if resolved.exists() and resolved.is_file()
                else None
            )
        )
        return {
            "file_path": str(resolved),
            "filename": resolved.name,
            "size_bytes": resolved_size,
            "format": resolved.suffix.lstrip(".").lower(),
            "transient": not self.config.capture.persist_captured_audio,
        }

    def _resolved_size(self, path: Path, fallback: Any) -> int:
        value = self._optional_int(fallback)
        if value is not None:
            return value
        return path.stat().st_size if path.exists() and path.is_file() else 0

    def _optional_int(self, value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _endpoint_payload_from(
        self, payload: dict[str, Any], handle: dict[str, Any]
    ) -> dict[str, Any]:
        endpoint = payload.get("endpoint")
        if not isinstance(endpoint, dict):
            metadata = payload.get("metadata")
            if isinstance(metadata, dict) and isinstance(metadata.get("endpoint"), dict):
                endpoint = metadata.get("endpoint")
        if not isinstance(endpoint, dict):
            endpoint = handle.get("endpoint")
        clean = dict(endpoint) if isinstance(endpoint, dict) else {}
        clean.setdefault("reason", None)
        clean.setdefault("speech_detected", False)
        clean.setdefault("raw_audio_logged", False)
        clean.setdefault("raw_secret_logged", False)
        return clean

    def _request_endpointing_enabled(
        self, request: VoiceCaptureRequest | None
    ) -> bool:
        if request is None:
            return False
        return bool(dict(request.metadata or {}).get("endpointing_enabled"))

    def _mime_type_for_format(self, format_name: str) -> str:
        normalized = str(format_name or "wav").strip().lower() or "wav"
        if normalized == "wav":
            return "audio/wav"
        if normalized == "mp3":
            return "audio/mpeg"
        if normalized in {"m4a", "mp4"}:
            return "audio/mp4"
        if normalized == "webm":
            return "audio/webm"
        return "application/octet-stream"


@runtime_checkable
class VoicePlaybackProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_mock(self) -> bool: ...

    def get_availability(self) -> dict[str, Any]: ...

    def play(
        self, request: VoicePlaybackRequest
    ) -> VoicePlaybackResult | Awaitable[VoicePlaybackResult]: ...

    def stop(
        self,
        playback_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoicePlaybackResult | Awaitable[VoicePlaybackResult]: ...

    def get_active_playback(self) -> VoicePlaybackResult | None: ...

    def prewarm_playback(
        self,
        request: VoicePlaybackPrewarmRequest,
    ) -> VoicePlaybackPrewarmResult: ...

    def start_stream(
        self,
        request: VoiceLivePlaybackRequest,
    ) -> VoiceLivePlaybackSession: ...

    def feed_stream_chunk(
        self,
        playback_stream_id: str,
        data: bytes,
        *,
        chunk_index: int | None = None,
    ) -> VoiceLivePlaybackChunkResult: ...

    def complete_stream(
        self,
        playback_stream_id: str,
    ) -> VoiceLivePlaybackResult: ...

    def cancel_stream(
        self,
        playback_stream_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoiceLivePlaybackResult: ...


@dataclass(slots=True)
class MockPlaybackProvider:
    provider_name: str = "mock"
    available: bool = True
    blocked: bool = False
    fail_playback: bool = False
    error_code: str | None = None
    error_message: str | None = None
    complete_immediately: bool = True
    playback_latency_ms: int = 0
    playback_call_count: int = 0
    _active_playback: VoicePlaybackResult | None = field(
        default=None, init=False, repr=False
    )
    _active_stream: VoiceLivePlaybackSession | None = field(
        default=None, init=False, repr=False
    )

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return True

    def get_availability(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "available": self.available and not self.blocked,
            "unavailable_reason": None if self.available else "provider_unavailable",
            "mock": True,
        }

    def play(self, request: VoicePlaybackRequest) -> VoicePlaybackResult:
        if not request.allowed_to_play:
            return self._result(
                request,
                ok=False,
                status="blocked",
                error_code=request.blocked_reason or "playback_blocked",
                error_message=f"Playback request blocked: {request.blocked_reason or 'playback_blocked'}.",
            )
        if not self.available:
            return self._result(
                request,
                ok=False,
                status="unavailable",
                error_code="provider_unavailable",
                error_message="Mock playback provider is unavailable.",
            )
        if self.blocked:
            return self._result(
                request,
                ok=False,
                status="blocked",
                error_code="playback_blocked",
                error_message="Mock playback provider blocked playback.",
            )

        self.playback_call_count += 1
        if self.fail_playback:
            return self._result(
                request,
                ok=False,
                status="failed",
                error_code=self.error_code or "playback_failed",
                error_message=self.error_message or "Mock playback provider failed.",
            )

        started_at = utc_now_iso()
        if self.complete_immediately:
            return self._result(
                request,
                ok=True,
                status="completed",
                started_at=started_at,
                completed_at=utc_now_iso(),
                elapsed_ms=self.playback_latency_ms,
                played_locally=True,
            )

        result = self._result(
            request,
            ok=True,
            status="started",
            started_at=started_at,
            elapsed_ms=0,
            played_locally=True,
        )
        self._active_playback = result
        return result

    def stop(
        self,
        playback_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoicePlaybackResult:
        active = self._active_playback
        if active is None or (playback_id and playback_id != active.playback_id):
            stream = self._active_stream
            if stream is not None and (
                playback_id is None or playback_id == stream.playback_stream_id
            ):
                cancelled = self.cancel_stream(
                    stream.playback_stream_id, reason=reason
                )
                return VoicePlaybackResult(
                    ok=cancelled.ok,
                    playback_request_id=cancelled.playback_request_id,
                    audio_output_id=None,
                    provider=self.provider_name,
                    device=cancelled.device,
                    status=cancelled.status,
                    playback_id=cancelled.playback_stream_id
                    or f"voice-playback-{uuid4().hex[:12]}",
                    session_id=cancelled.session_id,
                    turn_id=cancelled.turn_id,
                    started_at=cancelled.playback_started_at,
                    stopped_at=cancelled.cancelled_at,
                    error_code=cancelled.error_code,
                    error_message=cancelled.error_message,
                    output_metadata=cancelled.to_dict(),
                    played_locally=cancelled.partial_playback,
                    partial_playback=cancelled.partial_playback,
                    user_heard_claimed=False,
                )
            return VoicePlaybackResult(
                ok=False,
                playback_request_id=None,
                audio_output_id=None,
                provider=self.provider_name,
                device="default",
                status="unavailable",
                error_code="no_active_playback",
                error_message="No active local playback exists.",
                output_metadata={"reason": reason},
                played_locally=False,
                user_heard_claimed=False,
            )
        self._active_playback = None
        return replace(
            active,
            ok=True,
            status="stopped",
            stopped_at=utc_now_iso(),
            error_code=None,
            error_message=None,
            output_metadata={**dict(active.output_metadata), "stop_reason": reason},
            user_heard_claimed=False,
        )

    def get_active_playback(self) -> VoicePlaybackResult | None:
        return self._active_playback

    def prewarm_playback(
        self, request: VoicePlaybackPrewarmRequest
    ) -> VoicePlaybackPrewarmResult:
        available = self.available and not self.blocked
        return VoicePlaybackPrewarmResult(
            ok=available,
            request_id=request.request_id,
            provider=self.provider_name,
            device=request.device,
            audio_format=request.audio_format,
            status="prepared" if available else "unavailable",
            playback_started=False,
            stream_sink_prepared=available,
            cancellation_ready=available,
            prewarm_ms=0,
            error_code=None if available else "provider_unavailable",
            error_message=None
            if available
            else "Mock playback provider is unavailable.",
            metadata={"mock": True, "raw_audio_present": False},
        )

    def start_stream(
        self, request: VoiceLivePlaybackRequest
    ) -> VoiceLivePlaybackSession:
        if not request.allowed_to_play:
            return VoiceLivePlaybackSession(
                playback_stream_id=request.playback_stream_id,
                playback_request_id=request.playback_request_id,
                provider=self.provider_name,
                device=request.device,
                audio_format=request.audio_format,
                status="blocked",
                session_id=request.session_id,
                turn_id=request.turn_id,
                tts_stream_id=request.tts_stream_id,
                speech_request_id=request.speech_request_id,
                error_code=request.blocked_reason or "playback_blocked",
                error_message=f"Playback stream blocked: {request.blocked_reason or 'playback_blocked'}.",
                metadata={"mock": True, "raw_audio_present": False},
            )
        if not self.available or self.blocked:
            reason = "provider_unavailable" if not self.available else "playback_blocked"
            return VoiceLivePlaybackSession(
                playback_stream_id=request.playback_stream_id,
                playback_request_id=request.playback_request_id,
                provider=self.provider_name,
                device=request.device,
                audio_format=request.audio_format,
                status="unavailable" if not self.available else "blocked",
                session_id=request.session_id,
                turn_id=request.turn_id,
                tts_stream_id=request.tts_stream_id,
                speech_request_id=request.speech_request_id,
                error_code=reason,
                error_message=f"Mock playback stream unavailable: {reason}.",
                metadata={"mock": True, "raw_audio_present": False},
            )
        session = VoiceLivePlaybackSession(
            playback_stream_id=request.playback_stream_id,
            playback_request_id=request.playback_request_id,
            provider=self.provider_name,
            device=request.device,
            audio_format=request.audio_format,
            status="started",
            session_id=request.session_id,
            turn_id=request.turn_id,
            tts_stream_id=request.tts_stream_id,
            speech_request_id=request.speech_request_id,
            metadata={"mock": True, "raw_audio_present": False},
        )
        self._active_stream = session
        return session

    def feed_stream_chunk(
        self,
        playback_stream_id: str,
        data: bytes,
        *,
        chunk_index: int | None = None,
    ) -> VoiceLivePlaybackChunkResult:
        active = self._active_stream
        if active is None or active.playback_stream_id != playback_stream_id:
            return VoiceLivePlaybackChunkResult(
                ok=False,
                playback_stream_id=playback_stream_id,
                chunk_index=chunk_index or 0,
                status="unavailable",
                size_bytes=0,
                error_code="no_active_playback_stream",
                error_message="No active playback stream exists.",
            )
        payload = bytes(data or b"")
        index = active.chunk_count if chunk_index is None else int(chunk_index)
        now = utc_now_iso()
        first_chunk_at = active.first_chunk_received_at or now
        playback_started_at = active.playback_started_at or now
        updated = replace(
            active,
            status="playing",
            first_chunk_received_at=first_chunk_at,
            playback_started_at=playback_started_at,
            chunk_count=active.chunk_count + 1,
            bytes_received=active.bytes_received + len(payload),
        )
        self._active_stream = updated
        return VoiceLivePlaybackChunkResult(
            ok=True,
            playback_stream_id=playback_stream_id,
            chunk_index=index,
            status="playing",
            size_bytes=len(payload),
            first_chunk_received_at=first_chunk_at,
            playback_started_at=playback_started_at,
            playback_started=True,
            metadata={"mock": True, "raw_audio_present": False},
        )

    def complete_stream(self, playback_stream_id: str) -> VoiceLivePlaybackResult:
        active = self._active_stream
        if active is None or active.playback_stream_id != playback_stream_id:
            return self._stream_result(
                None,
                playback_stream_id=playback_stream_id,
                ok=False,
                status="unavailable",
                error_code="no_active_playback_stream",
                error_message="No active playback stream exists.",
            )
        self._active_stream = None
        return self._stream_result(
            active,
            ok=True,
            status="completed",
            completed_at=utc_now_iso(),
            partial_playback=False,
        )

    def cancel_stream(
        self,
        playback_stream_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoiceLivePlaybackResult:
        active = self._active_stream
        if active is None or (
            playback_stream_id is not None
            and active.playback_stream_id != playback_stream_id
        ):
            return self._stream_result(
                None,
                playback_stream_id=playback_stream_id,
                ok=False,
                status="unavailable",
                error_code="no_active_playback_stream",
                error_message="No active playback stream exists.",
            )
        self._active_stream = None
        return self._stream_result(
            active,
            ok=True,
            status="cancelled",
            cancelled_at=utc_now_iso(),
            partial_playback=active.chunk_count > 0,
            metadata={"cancel_reason": reason},
        )

    def get_active_playback_stream(self) -> VoiceLivePlaybackSession | None:
        return self._active_stream

    def _stream_result(
        self,
        session: VoiceLivePlaybackSession | None,
        *,
        playback_stream_id: str | None = None,
        ok: bool,
        status: str,
        completed_at: str | None = None,
        cancelled_at: str | None = None,
        partial_playback: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceLivePlaybackResult:
        return VoiceLivePlaybackResult(
            ok=ok,
            playback_stream_id=(
                session.playback_stream_id if session is not None else playback_stream_id
            ),
            playback_request_id=session.playback_request_id if session is not None else None,
            provider=self.provider_name,
            device=session.device if session is not None else "default",
            audio_format=session.audio_format if session is not None else "pcm",
            status=status,
            session_id=session.session_id if session is not None else None,
            turn_id=session.turn_id if session is not None else None,
            tts_stream_id=session.tts_stream_id if session is not None else None,
            speech_request_id=session.speech_request_id if session is not None else None,
            started_at=session.started_at if session is not None else None,
            first_chunk_received_at=(
                session.first_chunk_received_at if session is not None else None
            ),
            playback_started_at=(
                session.playback_started_at if session is not None else None
            ),
            completed_at=completed_at,
            cancelled_at=cancelled_at,
            chunk_count=session.chunk_count if session is not None else 0,
            bytes_received=session.bytes_received if session is not None else 0,
            partial_playback=partial_playback,
            error_code=error_code,
            error_message=error_message,
            metadata={
                **dict(metadata or {}),
                "mock": True,
                "raw_audio_present": False,
            },
            user_heard_claimed=False,
        )

    def _result(
        self,
        request: VoicePlaybackRequest,
        *,
        ok: bool,
        status: str,
        started_at: str | None = None,
        completed_at: str | None = None,
        stopped_at: str | None = None,
        elapsed_ms: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        played_locally: bool = False,
    ) -> VoicePlaybackResult:
        return VoicePlaybackResult(
            ok=ok,
            playback_request_id=request.playback_request_id,
            audio_output_id=request.audio_output_id,
            synthesis_id=request.synthesis_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            provider=self.provider_name,
            device=request.device,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            stopped_at=stopped_at,
            elapsed_ms=elapsed_ms,
            error_code=error_code,
            error_message=error_message,
            output_metadata={
                "audio_output_id": request.audio_output_id,
                "format": request.format,
                "mime_type": request.mime_type,
                "size_bytes": request.size_bytes,
                "duration_ms": request.duration_ms,
            },
            played_locally=played_locally,
            user_heard_claimed=False,
        )


@dataclass(slots=True)
class NullStreamingPlaybackProvider(MockPlaybackProvider):
    """Silent live-playback sink for first-output timing and CI smoke runs."""

    provider_name: str = "null_stream"
    complete_immediately: bool = False
    _stream_started_monotonic_ms: int | None = field(
        default=None, init=False, repr=False
    )
    _first_accept_monotonic_ms: int | None = field(
        default=None, init=False, repr=False
    )

    @property
    def is_mock(self) -> bool:
        return False

    def _now_monotonic_ms(self) -> int:
        return int(time.perf_counter() * 1000)

    def _null_metadata(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(extra or {})
        payload.update(
            {
                "mock": False,
                "sink_kind": "null_stream",
                "null_sink": True,
                "audible_playback": False,
                "raw_audio_present": False,
                "raw_audio_logged": False,
                "user_heard_claimed": False,
            }
        )
        if self._first_accept_monotonic_ms is not None:
            payload["null_sink_first_accept_ms"] = max(
                0,
                self._first_accept_monotonic_ms
                - int(
                    self._stream_started_monotonic_ms
                    or self._first_accept_monotonic_ms
                ),
            )
            payload["first_output_start_ms"] = payload[
                "null_sink_first_accept_ms"
            ]
        return payload

    def get_availability(self) -> dict[str, Any]:
        return {
            **MockPlaybackProvider.get_availability(self),
            "provider": self.provider_name,
            "mock": False,
            "sink_kind": "null_stream",
            "null_sink": True,
            "audible_playback": False,
            "raw_audio_logged": False,
            "user_heard_claimed": False,
        }

    def prewarm_playback(
        self, request: VoicePlaybackPrewarmRequest
    ) -> VoicePlaybackPrewarmResult:
        result = MockPlaybackProvider.prewarm_playback(self, request)
        return replace(
            result,
            provider=self.provider_name,
            metadata=self._null_metadata(dict(result.metadata)),
        )

    def start_stream(
        self, request: VoiceLivePlaybackRequest
    ) -> VoiceLivePlaybackSession:
        self._stream_started_monotonic_ms = self._now_monotonic_ms()
        self._first_accept_monotonic_ms = None
        session = MockPlaybackProvider.start_stream(self, request)
        session = replace(
            session,
            provider=self.provider_name,
            metadata=self._null_metadata(dict(session.metadata)),
            user_heard_claimed=False,
        )
        if session.status in {"started", "playing"}:
            self._active_stream = session
        return session

    def feed_stream_chunk(
        self,
        playback_stream_id: str,
        data: bytes,
        *,
        chunk_index: int | None = None,
    ) -> VoiceLivePlaybackChunkResult:
        result = MockPlaybackProvider.feed_stream_chunk(
            self,
            playback_stream_id,
            data,
            chunk_index=chunk_index,
        )
        if result.ok and self._first_accept_monotonic_ms is None:
            self._first_accept_monotonic_ms = self._now_monotonic_ms()
        metadata = self._null_metadata(dict(result.metadata))
        updated_result = replace(result, metadata=metadata)
        if self._active_stream is not None:
            self._active_stream = replace(
                self._active_stream,
                provider=self.provider_name,
                metadata=self._null_metadata(dict(self._active_stream.metadata)),
                user_heard_claimed=False,
            )
        return updated_result

    def complete_stream(self, playback_stream_id: str) -> VoiceLivePlaybackResult:
        result = MockPlaybackProvider.complete_stream(self, playback_stream_id)
        return replace(
            result,
            provider=self.provider_name,
            metadata=self._null_metadata(dict(result.metadata)),
            user_heard_claimed=False,
        )

    def cancel_stream(
        self,
        playback_stream_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoiceLivePlaybackResult:
        result = MockPlaybackProvider.cancel_stream(
            self, playback_stream_id, reason=reason
        )
        return replace(
            result,
            provider=self.provider_name,
            metadata=self._null_metadata(dict(result.metadata)),
            user_heard_claimed=False,
        )


class WindowsMCIPlaybackBackend:
    """Small Windows-only MP3/WAV player using the stdlib MCI binding."""

    dependency_name = "winmm_mci"

    def __init__(self) -> None:
        self.platform_name = sys.platform
        self._aliases: dict[str, str] = {}
        self._stream_handles: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get_availability(self, config: VoiceConfig) -> dict[str, Any]:
        device = str(config.playback.device or "default").strip() or "default"
        device_available = device.lower() == "default"
        if not sys.platform.startswith("win"):
            return {
                "provider": "local",
                "backend": self.dependency_name,
                "platform": sys.platform,
                "dependency": self.dependency_name,
                "dependency_available": False,
                "device": device,
                "device_available": device_available,
                "available": False,
                "unavailable_reason": "local_playback_platform_unsupported",
            }
        try:
            import ctypes

            getattr(ctypes.windll, "winmm")
        except Exception:
            return {
                "provider": "local",
                "backend": self.dependency_name,
                "platform": sys.platform,
                "dependency": self.dependency_name,
                "dependency_available": False,
                "device": device,
                "device_available": device_available,
                "available": False,
                "unavailable_reason": "local_playback_dependency_missing",
            }
        if not device_available:
            return {
                "provider": "local",
                "backend": self.dependency_name,
                "platform": sys.platform,
                "dependency": self.dependency_name,
                "dependency_available": True,
                "device": device,
                "device_available": False,
                "available": False,
                "unavailable_reason": "device_unavailable",
            }
        return {
            "provider": "local",
            "backend": self.dependency_name,
            "platform": sys.platform,
            "dependency": self.dependency_name,
            "dependency_available": True,
            "device": device,
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
    ) -> dict[str, Any]:
        resolved = Path(path)
        if not resolved.exists() or not resolved.is_file():
            return {
                "status": "failed",
                "error_code": "audio_file_missing",
                "error_message": "Playback audio file was missing.",
            }
        availability = self._request_availability(request)
        if not bool(availability.get("available")):
            reason = str(
                availability.get("unavailable_reason") or "local_playback_unavailable"
            )
            return {
                "status": "unavailable",
                "error_code": reason,
                "error_message": f"Local playback unavailable: {reason}.",
            }
        started = time.perf_counter()
        alias = "stormhelm_voice_" + "".join(
            character if character.isalnum() else "_"
            for character in str(playback_id or uuid4().hex)
        )
        with self._lock:
            self._aliases[playback_id] = alias
        try:
            self._mci(f'open "{resolved}" alias {alias}')
            try:
                volume = int(max(0.0, min(1.0, float(request.volume))) * 1000)
                self._mci(f"setaudio {alias} volume to {volume}")
            except Exception:
                pass
            self._mci(f"play {alias} wait")
            return {
                "status": "completed",
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "played_locally": True,
            }
        except Exception as error:
            return {
                "status": "failed",
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "error_code": "local_playback_failed",
                "error_message": str(error),
            }
        finally:
            try:
                self._mci(f"close {alias}")
            except Exception:
                pass
            with self._lock:
                self._aliases.pop(playback_id, None)

    def stop(
        self, playback_id: str | None = None, *, reason: str = "user_requested"
    ) -> dict[str, Any]:
        del reason
        with self._lock:
            if playback_id:
                aliases = [self._aliases.get(playback_id)] if playback_id in self._aliases else []
            else:
                aliases = list(self._aliases.values())
        aliases = [alias for alias in aliases if alias]
        if not aliases:
            return {"status": "unavailable", "error_code": "no_active_playback"}
        for alias in aliases:
            try:
                self._mci(f"stop {alias}")
                self._mci(f"close {alias}")
            except Exception:
                pass
        return {"status": "stopped", "elapsed_ms": 0}

    def start_stream(self, *, request: VoiceLivePlaybackRequest) -> dict[str, Any]:
        if str(request.audio_format or "").strip().lower() != "pcm":
            return {
                "status": "unsupported",
                "error_code": "unsupported_live_format",
                "error_message": "Windows speaker streaming currently requires PCM audio.",
                "raw_audio_present": False,
            }
        availability = self._stream_request_availability(request)
        if not bool(availability.get("available")):
            reason = str(
                availability.get("unavailable_reason") or "local_playback_unavailable"
            )
            return {
                "status": "unavailable",
                "error_code": reason,
                "error_message": f"Local speaker streaming unavailable: {reason}.",
                "raw_audio_present": False,
            }
        sample_rate = self._stream_int_metadata(request, "sample_rate", 24000)
        channels = self._stream_int_metadata(request, "channels", 1)
        sample_width = self._stream_int_metadata(request, "sample_width_bytes", 2)
        try:
            wave_out = self._waveout_open(
                sample_rate=sample_rate,
                channels=channels,
                sample_width_bytes=sample_width,
            )
            volume = int(max(0.0, min(1.0, float(request.volume))) * 0xFFFF)
            try:
                self._waveout_set_volume(wave_out, volume)
            except Exception:
                pass
        except Exception as error:
            return {
                "status": "failed",
                "error_code": "local_speaker_stream_start_failed",
                "error_message": str(error),
                "raw_audio_present": False,
            }
        handle = {
            "wave_out": wave_out,
            "buffers": [],
            "started": time.perf_counter(),
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "chunk_count": 0,
            "bytes_received": 0,
            "first_chunk_received_at": None,
            "playback_started_at": None,
            "audible_playback": False,
        }
        with self._lock:
            self._stream_handles[request.playback_stream_id] = handle
        return {
            "status": "started",
            "backend": "winmm_waveout",
            "streaming_supported": True,
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "audible_playback": False,
            "user_heard_claimed": False,
            "raw_audio_present": False,
        }

    def feed_stream_chunk(
        self,
        playback_stream_id: str,
        data: bytes,
        *,
        chunk_index: int | None = None,
    ) -> dict[str, Any]:
        payload = bytes(data or b"")
        with self._lock:
            handle = self._stream_handles.get(playback_stream_id)
        if handle is None:
            return {
                "ok": False,
                "status": "unavailable",
                "chunk_index": chunk_index or 0,
                "error_code": "no_active_playback_stream",
                "error_message": "No active local speaker stream exists.",
                "raw_audio_present": False,
            }
        if not payload:
            return {
                "ok": True,
                "status": "playing",
                "chunk_index": chunk_index or int(handle.get("chunk_count") or 0),
                "playback_started": bool(handle.get("audible_playback")),
                "raw_audio_present": False,
            }
        try:
            self._waveout_write(handle, payload)
        except Exception as error:
            return {
                "ok": False,
                "status": "failed",
                "chunk_index": chunk_index or int(handle.get("chunk_count") or 0),
                "error_code": "local_speaker_stream_chunk_failed",
                "error_message": str(error),
                "raw_audio_present": False,
            }
        now = utc_now_iso()
        if handle.get("first_chunk_received_at") is None:
            handle["first_chunk_received_at"] = now
        if handle.get("playback_started_at") is None:
            handle["playback_started_at"] = now
        handle["chunk_count"] = int(handle.get("chunk_count") or 0) + 1
        handle["bytes_received"] = int(handle.get("bytes_received") or 0) + len(payload)
        handle["audible_playback"] = True
        return {
            "ok": True,
            "status": "playing",
            "chunk_index": chunk_index
            if chunk_index is not None
            else int(handle["chunk_count"]) - 1,
            "first_chunk_received_at": handle["first_chunk_received_at"],
            "playback_started_at": handle["playback_started_at"],
            "playback_started": True,
            "audible_playback": True,
            "user_heard_claimed": True,
            "raw_audio_present": False,
        }

    def complete_stream(self, playback_stream_id: str) -> dict[str, Any]:
        with self._lock:
            handle = self._stream_handles.pop(playback_stream_id, None)
        if handle is None:
            return {
                "status": "unavailable",
                "error_code": "no_active_playback_stream",
                "error_message": "No active local speaker stream exists.",
                "raw_audio_present": False,
            }
        error: str | None = None
        try:
            self._waveout_wait_and_close(handle)
        except Exception as exc:
            error = str(exc)
        elapsed_ms = int((time.perf_counter() - float(handle.get("started") or time.perf_counter())) * 1000)
        heard = bool(handle.get("audible_playback") and handle.get("chunk_count"))
        return {
            "status": "failed" if error else "completed",
            "elapsed_ms": elapsed_ms,
            "error_code": "local_speaker_stream_complete_failed" if error else None,
            "error_message": error,
            "chunk_count": int(handle.get("chunk_count") or 0),
            "bytes_received": int(handle.get("bytes_received") or 0),
            "first_chunk_received_at": handle.get("first_chunk_received_at"),
            "playback_started_at": handle.get("playback_started_at"),
            "audible_playback": heard,
            "user_heard_claimed": heard,
            "raw_audio_present": False,
        }

    def cancel_stream(
        self,
        playback_stream_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> dict[str, Any]:
        with self._lock:
            if playback_stream_id:
                handles = {
                    playback_stream_id: self._stream_handles.pop(playback_stream_id, None)
                }
            else:
                handles = dict(self._stream_handles)
                self._stream_handles.clear()
        handles = {key: value for key, value in handles.items() if value is not None}
        if not handles:
            return {
                "status": "unavailable",
                "error_code": "no_active_playback_stream",
                "error_message": "No active local speaker stream exists.",
                "raw_audio_present": False,
            }
        heard = False
        chunk_count = 0
        bytes_received = 0
        first_chunk_received_at = None
        playback_started_at = None
        for handle in handles.values():
            heard = heard or bool(handle.get("audible_playback") and handle.get("chunk_count"))
            chunk_count += int(handle.get("chunk_count") or 0)
            bytes_received += int(handle.get("bytes_received") or 0)
            first_chunk_received_at = first_chunk_received_at or handle.get("first_chunk_received_at")
            playback_started_at = playback_started_at or handle.get("playback_started_at")
            try:
                self._waveout_reset_and_close(handle)
            except Exception:
                pass
        return {
            "status": "cancelled",
            "cancel_reason": reason,
            "chunk_count": chunk_count,
            "bytes_received": bytes_received,
            "first_chunk_received_at": first_chunk_received_at,
            "playback_started_at": playback_started_at,
            "audible_playback": heard,
            "user_heard_claimed": heard,
            "raw_audio_present": False,
        }

    def _mci(self, command: str) -> str:
        import ctypes

        buffer = ctypes.create_unicode_buffer(512)
        result = ctypes.windll.winmm.mciSendStringW(command, buffer, len(buffer), 0)
        if result == 0:
            return buffer.value
        error_buffer = ctypes.create_unicode_buffer(512)
        try:
            ctypes.windll.winmm.mciGetErrorStringW(result, error_buffer, len(error_buffer))
            message = error_buffer.value or f"MCI error {result}"
        except Exception:
            message = f"MCI error {result}"
        raise RuntimeError(message)

    def _stream_request_availability(
        self, request: VoiceLivePlaybackRequest
    ) -> dict[str, Any]:
        device = str(request.device or "default").strip() or "default"
        device_available = device.lower() == "default"
        if not sys.platform.startswith("win"):
            return {
                "provider": "local",
                "backend": "winmm_waveout",
                "platform": sys.platform,
                "dependency": "winmm",
                "dependency_available": False,
                "device": device,
                "device_available": device_available,
                "available": False,
                "unavailable_reason": "local_playback_platform_unsupported",
            }
        try:
            import ctypes

            getattr(ctypes.windll, "winmm")
        except Exception:
            return {
                "provider": "local",
                "backend": "winmm_waveout",
                "platform": sys.platform,
                "dependency": "winmm",
                "dependency_available": False,
                "device": device,
                "device_available": device_available,
                "available": False,
                "unavailable_reason": "local_playback_dependency_missing",
            }
        if not device_available:
            return {
                "provider": "local",
                "backend": "winmm_waveout",
                "platform": sys.platform,
                "dependency": "winmm",
                "dependency_available": True,
                "device": device,
                "device_available": False,
                "available": False,
                "unavailable_reason": "device_unavailable",
            }
        return {
            "provider": "local",
            "backend": "winmm_waveout",
            "platform": sys.platform,
            "dependency": "winmm",
            "dependency_available": True,
            "device": device,
            "device_available": True,
            "available": True,
            "unavailable_reason": None,
        }

    def _stream_int_metadata(
        self,
        request: VoiceLivePlaybackRequest,
        key: str,
        default: int,
    ) -> int:
        value = request.metadata.get(key)
        try:
            return max(1, int(value if value is not None else default))
        except (TypeError, ValueError):
            return default

    def _waveout_open(
        self,
        *,
        sample_rate: int,
        channels: int,
        sample_width_bytes: int,
    ) -> Any:
        import ctypes
        from ctypes import wintypes

        class WAVEFORMATEX(ctypes.Structure):
            _fields_ = [
                ("wFormatTag", wintypes.WORD),
                ("nChannels", wintypes.WORD),
                ("nSamplesPerSec", wintypes.DWORD),
                ("nAvgBytesPerSec", wintypes.DWORD),
                ("nBlockAlign", wintypes.WORD),
                ("wBitsPerSample", wintypes.WORD),
                ("cbSize", wintypes.WORD),
            ]

        fmt = WAVEFORMATEX()
        fmt.wFormatTag = 1
        fmt.nChannels = channels
        fmt.nSamplesPerSec = sample_rate
        fmt.nBlockAlign = channels * sample_width_bytes
        fmt.nAvgBytesPerSec = sample_rate * fmt.nBlockAlign
        fmt.wBitsPerSample = sample_width_bytes * 8
        fmt.cbSize = 0
        wave_out = ctypes.c_void_p()
        result = ctypes.windll.winmm.waveOutOpen(
            ctypes.byref(wave_out),
            ctypes.c_uint(-1).value,
            ctypes.byref(fmt),
            0,
            0,
            0,
        )
        if result:
            raise RuntimeError(self._winmm_error(result))
        return wave_out

    def _waveout_set_volume(self, wave_out: Any, volume: int) -> None:
        import ctypes

        packed = (volume & 0xFFFF) | ((volume & 0xFFFF) << 16)
        ctypes.windll.winmm.waveOutSetVolume(wave_out, packed)

    def _waveout_write(self, handle: dict[str, Any], payload: bytes) -> None:
        import ctypes
        from ctypes import wintypes

        class WAVEHDR(ctypes.Structure):
            _fields_ = [
                ("lpData", ctypes.c_void_p),
                ("dwBufferLength", wintypes.DWORD),
                ("dwBytesRecorded", wintypes.DWORD),
                ("dwUser", ctypes.c_size_t),
                ("dwFlags", wintypes.DWORD),
                ("dwLoops", wintypes.DWORD),
                ("lpNext", ctypes.c_void_p),
                ("reserved", ctypes.c_size_t),
            ]

        buffer = ctypes.create_string_buffer(payload)
        header = WAVEHDR()
        header.lpData = ctypes.cast(buffer, ctypes.c_void_p)
        header.dwBufferLength = len(payload)
        wave_out = handle["wave_out"]
        prepare = ctypes.windll.winmm.waveOutPrepareHeader(
            wave_out,
            ctypes.byref(header),
            ctypes.sizeof(header),
        )
        if prepare:
            raise RuntimeError(self._winmm_error(prepare))
        write = ctypes.windll.winmm.waveOutWrite(
            wave_out,
            ctypes.byref(header),
            ctypes.sizeof(header),
        )
        if write:
            try:
                ctypes.windll.winmm.waveOutUnprepareHeader(
                    wave_out,
                    ctypes.byref(header),
                    ctypes.sizeof(header),
                )
            except Exception:
                pass
            raise RuntimeError(self._winmm_error(write))
        handle["buffers"].append((header, buffer))

    def _waveout_wait_and_close(self, handle: dict[str, Any]) -> None:
        deadline = time.perf_counter() + 10.0
        while time.perf_counter() < deadline:
            if all(header.dwFlags & 0x00000001 for header, _ in handle["buffers"]):
                break
            time.sleep(0.01)
        self._waveout_reset_and_close(handle, reset=False)

    def _waveout_reset_and_close(
        self,
        handle: dict[str, Any],
        *,
        reset: bool = True,
    ) -> None:
        import ctypes

        wave_out = handle.get("wave_out")
        if wave_out is None:
            return
        if reset:
            try:
                ctypes.windll.winmm.waveOutReset(wave_out)
            except Exception:
                pass
        for header, _buffer in list(handle.get("buffers") or []):
            try:
                ctypes.windll.winmm.waveOutUnprepareHeader(
                    wave_out,
                    ctypes.byref(header),
                    ctypes.sizeof(header),
                )
            except Exception:
                pass
        try:
            ctypes.windll.winmm.waveOutClose(wave_out)
        except Exception:
            pass
        handle["wave_out"] = None
        handle["buffers"] = []

    def _winmm_error(self, code: int) -> str:
        import ctypes

        error_buffer = ctypes.create_unicode_buffer(512)
        try:
            ctypes.windll.winmm.waveOutGetErrorTextW(
                code, error_buffer, len(error_buffer)
            )
            return error_buffer.value or f"winmm error {code}"
        except Exception:
            return f"winmm error {code}"

    def _request_availability(self, request: VoicePlaybackRequest) -> dict[str, Any]:
        device = str(request.device or "default").strip() or "default"
        device_available = device.lower() == "default"
        if not sys.platform.startswith("win"):
            return {
                "provider": "local",
                "backend": self.dependency_name,
                "platform": sys.platform,
                "dependency": self.dependency_name,
                "dependency_available": False,
                "device": device,
                "device_available": device_available,
                "available": False,
                "unavailable_reason": "local_playback_platform_unsupported",
            }
        try:
            import ctypes

            getattr(ctypes.windll, "winmm")
        except Exception:
            return {
                "provider": "local",
                "backend": self.dependency_name,
                "platform": sys.platform,
                "dependency": self.dependency_name,
                "dependency_available": False,
                "device": device,
                "device_available": device_available,
                "available": False,
                "unavailable_reason": "local_playback_dependency_missing",
            }
        if not device_available:
            return {
                "provider": "local",
                "backend": self.dependency_name,
                "platform": sys.platform,
                "dependency": self.dependency_name,
                "dependency_available": True,
                "device": device,
                "device_available": False,
                "available": False,
                "unavailable_reason": "device_unavailable",
            }
        return {
            "provider": "local",
            "backend": self.dependency_name,
            "platform": sys.platform,
            "dependency": self.dependency_name,
            "dependency_available": True,
            "device": device,
            "device_available": True,
            "available": True,
            "unavailable_reason": None,
        }


@dataclass(slots=True)
class LocalPlaybackProvider:
    config: VoiceConfig
    provider_name: str = "local"
    backend: Any | None = None
    temp_dir: str | Path | None = None
    _active_playback: VoicePlaybackResult | None = field(
        default=None, init=False, repr=False
    )
    _active_stream: VoiceLivePlaybackSession | None = field(
        default=None, init=False, repr=False
    )
    _active_temp_path: Path | None = field(default=None, init=False, repr=False)
    _active_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.backend is None:
            self.backend = WindowsMCIPlaybackBackend()

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return False

    def get_availability(self) -> dict[str, Any]:
        if not self.config.playback.enabled:
            return {
                "provider": self.provider_name,
                "provider_kind": "local",
                "available": False,
                "unavailable_reason": "playback_disabled",
                "mock": False,
                "enabled": False,
                "allow_dev_playback": bool(self.config.playback.allow_dev_playback),
            }
        if not self.config.playback.allow_dev_playback:
            return {
                "provider": self.provider_name,
                "provider_kind": "local",
                "available": False,
                "unavailable_reason": "dev_playback_not_allowed",
                "mock": False,
                "enabled": True,
                "allow_dev_playback": False,
            }
        backend_availability = {}
        if self.backend is not None and hasattr(self.backend, "get_availability"):
            backend_availability = dict(self.backend.get_availability(self.config))
        available = bool(backend_availability.get("available"))
        reason = backend_availability.get("unavailable_reason")
        if not available and reason is None:
            if backend_availability.get("device_available") is False:
                reason = "device_unavailable"
            elif backend_availability.get("dependency_available") is False:
                reason = "local_playback_dependency_missing"
            else:
                reason = "local_playback_unavailable"
        return {
            **backend_availability,
            "provider": self.provider_name,
            "provider_kind": "local",
            "available": available,
            "unavailable_reason": reason,
            "mock": False,
            "enabled": True,
            "allow_dev_playback": True,
        }

    async def play(self, request: VoicePlaybackRequest) -> VoicePlaybackResult:
        if not request.allowed_to_play:
            return self._result(
                request,
                ok=False,
                status="blocked",
                error_code=request.blocked_reason or "playback_blocked",
                error_message=f"Playback request blocked: {request.blocked_reason or 'playback_blocked'}.",
            )
        availability = self.get_availability()
        if not bool(availability.get("available")):
            reason = str(availability.get("unavailable_reason") or "local_playback_unavailable")
            return self._result(
                request,
                ok=False,
                status="unavailable",
                error_code=reason,
                error_message=f"Local playback unavailable: {reason}.",
                extra_metadata={"availability": availability},
            )
        try:
            audio_path, should_delete = self._materialize_audio_path(request)
        except ValueError as error:
            return self._result(
                request,
                ok=False,
                status="failed",
                error_code=str(error) or "missing_audio_output",
                error_message="Local playback request did not include playable audio.",
                extra_metadata={"availability": availability},
            )

        playback_id = f"voice-playback-{uuid4().hex[:12]}"
        return await self._play_foreground(
            request,
            audio_path,
            should_delete,
            playback_id=playback_id,
            availability=availability,
        )

    def stop(
        self,
        playback_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoicePlaybackResult:
        with self._lock:
            active = self._active_playback
            temp_path = self._active_temp_path
        if active is None:
            return VoicePlaybackResult(
                ok=False,
                playback_request_id=None,
                audio_output_id=None,
                provider=self.provider_name,
                device=self.config.playback.device,
                status="unavailable",
                error_code="no_active_playback",
                error_message="No active local playback exists.",
                output_metadata={"reason": reason},
                played_locally=False,
                user_heard_claimed=False,
            )
        backend_result = {}
        if self.backend is not None and hasattr(self.backend, "stop"):
            backend_result = dict(self.backend.stop(playback_id or active.playback_id, reason=reason))
        self._cleanup_temp_path(temp_path)
        stopped = replace(
            active,
            ok=True,
            status="stopped",
            stopped_at=utc_now_iso(),
            error_code=None,
            error_message=None,
            elapsed_ms=backend_result.get("elapsed_ms")
            if isinstance(backend_result.get("elapsed_ms"), int)
            else active.elapsed_ms,
            output_metadata={
                **dict(active.output_metadata),
                "stop_reason": reason,
                "backend_status": backend_result.get("status"),
            },
            user_heard_claimed=False,
        )
        with self._lock:
            self._active_playback = None
            self._active_stream = None
            self._active_temp_path = None
        return stopped

    def get_active_playback(self) -> VoicePlaybackResult | None:
        with self._lock:
            return self._active_playback

    def prewarm_playback(
        self, request: VoicePlaybackPrewarmRequest
    ) -> VoicePlaybackPrewarmResult:
        start = time.perf_counter()
        availability = self.get_availability()
        ok = bool(availability.get("available"))
        return VoicePlaybackPrewarmResult(
            ok=ok,
            request_id=request.request_id,
            provider=self.provider_name,
            device=request.device or self.config.playback.device,
            audio_format=request.audio_format,
            status="prepared" if ok else "unavailable",
            playback_started=False,
            stream_sink_prepared=ok,
            cancellation_ready=ok,
            prewarm_ms=_elapsed_ms(start),
            error_code=None if ok else str(availability.get("unavailable_reason")),
            error_message=None
            if ok
            else f"Local playback prewarm unavailable: {availability.get('unavailable_reason')}.",
            metadata={"availability": availability, "raw_audio_present": False},
        )

    def start_stream(
        self, request: VoiceLivePlaybackRequest
    ) -> VoiceLivePlaybackSession:
        availability = self.get_availability()
        if not request.allowed_to_play:
            return self._stream_session(
                request,
                status="blocked",
                error_code=request.blocked_reason or "playback_blocked",
                error_message=f"Playback stream blocked: {request.blocked_reason or 'playback_blocked'}.",
            )
        if request.audio_format not in {"pcm", "wav"}:
            return self._stream_session(
                request,
                status="unsupported",
                error_code="unsupported_live_format",
                error_message=f"Live playback format is unsupported: {request.audio_format}.",
            )
        if not bool(availability.get("available")):
            reason = str(availability.get("unavailable_reason") or "local_playback_unavailable")
            return self._stream_session(
                request,
                status="unavailable",
                error_code=reason,
                error_message=f"Local playback stream unavailable: {reason}.",
            )
        if self.backend is None or not hasattr(self.backend, "start_stream"):
            return self._stream_session(
                request,
                status="unsupported",
                error_code="streaming_playback_backend_unsupported",
                error_message="Local playback backend does not support live chunk playback.",
            )
        try:
            payload = self.backend.start_stream(request=request)  # type: ignore[attr-defined]
            payload = dict(payload or {})
        except Exception as error:
            return self._stream_session(
                request,
                status="failed",
                error_code="local_stream_start_failed",
                error_message=str(error),
            )
        session = self._stream_session(
            request,
            status=str(payload.get("status") or "started"),
            metadata={
                "availability": availability,
                "backend": payload.get("backend") or availability.get("backend"),
                "streaming_supported": bool(payload.get("streaming_supported")),
                "audible_playback": bool(payload.get("audible_playback")),
                "user_heard_claimed": False,
                "raw_audio_present": False,
            },
        )
        with self._lock:
            self._active_stream = session
            self._active_playback = VoicePlaybackResult(
                ok=True,
                playback_request_id=request.playback_request_id,
                audio_output_id=None,
                provider=self.provider_name,
                device=request.device,
                status="started",
                playback_id=request.playback_stream_id,
                session_id=request.session_id,
                turn_id=request.turn_id,
                started_at=session.started_at,
                output_metadata=session.to_dict(),
                played_locally=False,
                user_heard_claimed=False,
            )
        return session

    def feed_stream_chunk(
        self,
        playback_stream_id: str,
        data: bytes,
        *,
        chunk_index: int | None = None,
    ) -> VoiceLivePlaybackChunkResult:
        payload = bytes(data or b"")
        if self.backend is None or not hasattr(self.backend, "feed_stream_chunk"):
            return VoiceLivePlaybackChunkResult(
                ok=False,
                playback_stream_id=playback_stream_id,
                chunk_index=chunk_index or 0,
                status="unsupported",
                size_bytes=0,
                error_code="streaming_playback_backend_unsupported",
                error_message="Local playback backend does not support live chunk playback.",
            )
        try:
            result = self.backend.feed_stream_chunk(  # type: ignore[attr-defined]
                playback_stream_id, payload, chunk_index=chunk_index
            )
            result = dict(result or {})
        except Exception as error:
            return VoiceLivePlaybackChunkResult(
                ok=False,
                playback_stream_id=playback_stream_id,
                chunk_index=chunk_index or 0,
                status="failed",
                size_bytes=0,
                error_code="local_stream_chunk_failed",
                error_message=str(error),
            )
        now = utc_now_iso()
        chunk_result = VoiceLivePlaybackChunkResult(
            ok=bool(result.get("ok", True)),
            playback_stream_id=playback_stream_id,
            chunk_index=chunk_index or int(result.get("chunk_index") or 0),
            status=str(result.get("status") or "playing"),
            size_bytes=len(payload),
            first_chunk_received_at=str(result.get("first_chunk_received_at") or now),
            playback_started_at=str(result.get("playback_started_at") or now),
            playback_started=bool(result.get("playback_started", True)),
            metadata={
                "raw_audio_present": False,
                "audible_playback": bool(result.get("audible_playback")),
                "user_heard_claimed": bool(result.get("user_heard_claimed")),
            },
        )
        with self._lock:
            active_stream = self._active_stream
            if active_stream is not None and active_stream.playback_stream_id == playback_stream_id:
                self._active_stream = replace(
                    active_stream,
                    status=chunk_result.status,
                    first_chunk_received_at=active_stream.first_chunk_received_at
                    or chunk_result.first_chunk_received_at,
                    playback_started_at=active_stream.playback_started_at
                    or chunk_result.playback_started_at,
                    chunk_count=active_stream.chunk_count + 1,
                    bytes_received=active_stream.bytes_received + len(payload),
                    metadata={
                        **dict(active_stream.metadata),
                        "audible_playback": bool(
                            active_stream.metadata.get("audible_playback")
                            or result.get("audible_playback")
                        ),
                        "user_heard_claimed": bool(
                            active_stream.metadata.get("user_heard_claimed")
                            or result.get("user_heard_claimed")
                        ),
                        "raw_audio_present": False,
                    },
                )
                if self._active_playback is not None:
                    self._active_playback = replace(
                        self._active_playback,
                        played_locally=bool(
                            self._active_playback.played_locally
                            or result.get("audible_playback")
                        ),
                        user_heard_claimed=bool(
                            self._active_playback.user_heard_claimed
                            or result.get("user_heard_claimed")
                        ),
                        output_metadata={
                            **dict(self._active_playback.output_metadata),
                            "audible_playback": bool(result.get("audible_playback")),
                            "user_heard_claimed": bool(result.get("user_heard_claimed")),
                            "raw_audio_present": False,
                        },
                    )
        return chunk_result

    def complete_stream(self, playback_stream_id: str) -> VoiceLivePlaybackResult:
        active = self._active_playback
        active_stream = self._active_stream
        metadata: dict[str, Any] = {}
        if self.backend is not None and hasattr(self.backend, "complete_stream"):
            try:
                metadata = dict(self.backend.complete_stream(playback_stream_id) or {})  # type: ignore[attr-defined]
            except Exception as error:
                metadata = {"error_code": "local_stream_complete_failed", "error_message": str(error)}
        heard_claimed = self._stream_user_heard_claimed(metadata, active_stream)
        with self._lock:
            self._active_playback = None
            self._active_stream = None
        return VoiceLivePlaybackResult(
            ok=not bool(metadata.get("error_code")),
            playback_stream_id=playback_stream_id,
            playback_request_id=active.playback_request_id if active else None,
            provider=self.provider_name,
            device=active.device if active else self.config.playback.device,
            audio_format=str((active.output_metadata if active else {}).get("audio_format") or "pcm"),
            status="failed" if metadata.get("error_code") else "completed",
            session_id=active.session_id if active else None,
            turn_id=active.turn_id if active else None,
            started_at=active.started_at if active else None,
            first_chunk_received_at=active_stream.first_chunk_received_at
            if active_stream is not None
            else None,
            playback_started_at=active_stream.playback_started_at
            if active_stream is not None
            else None,
            completed_at=utc_now_iso(),
            chunk_count=active_stream.chunk_count if active_stream is not None else 0,
            bytes_received=active_stream.bytes_received if active_stream is not None else 0,
            error_code=metadata.get("error_code"),
            error_message=metadata.get("error_message"),
            metadata={**metadata, "raw_audio_present": False},
            user_heard_claimed=heard_claimed,
        )

    def cancel_stream(
        self,
        playback_stream_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoiceLivePlaybackResult:
        active = self._active_playback
        active_stream = self._active_stream
        metadata: dict[str, Any] = {}
        if self.backend is not None and hasattr(self.backend, "cancel_stream"):
            try:
                metadata = dict(
                    self.backend.cancel_stream(playback_stream_id, reason=reason)  # type: ignore[attr-defined]
                    or {}
                )
            except Exception:
                pass
        heard_claimed = self._stream_user_heard_claimed(metadata, active_stream)
        with self._lock:
            self._active_playback = None
            self._active_stream = None
        return VoiceLivePlaybackResult(
            ok=active is not None,
            playback_stream_id=playback_stream_id or (active.playback_id if active else None),
            playback_request_id=active.playback_request_id if active else None,
            provider=self.provider_name,
            device=active.device if active else self.config.playback.device,
            audio_format=str((active.output_metadata if active else {}).get("audio_format") or "pcm"),
            status="cancelled" if active is not None else "unavailable",
            session_id=active.session_id if active else None,
            turn_id=active.turn_id if active else None,
            started_at=active.started_at if active else None,
            first_chunk_received_at=active_stream.first_chunk_received_at
            if active_stream is not None
            else None,
            playback_started_at=active_stream.playback_started_at
            if active_stream is not None
            else None,
            cancelled_at=utc_now_iso(),
            chunk_count=active_stream.chunk_count if active_stream is not None else 0,
            bytes_received=active_stream.bytes_received if active_stream is not None else 0,
            partial_playback=bool(
                active_stream is not None and active_stream.chunk_count > 0
            ),
            error_code=None if active else "no_active_playback_stream",
            error_message=None if active else "No active playback stream exists.",
            metadata={**metadata, "cancel_reason": reason, "raw_audio_present": False},
            user_heard_claimed=heard_claimed,
        )

    def get_active_playback_stream(self) -> VoiceLivePlaybackSession | None:
        with self._lock:
            return self._active_stream

    def _stream_session(
        self,
        request: VoiceLivePlaybackRequest,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceLivePlaybackSession:
        return VoiceLivePlaybackSession(
            playback_stream_id=request.playback_stream_id,
            playback_request_id=request.playback_request_id,
            provider=self.provider_name,
            device=request.device,
            audio_format=request.audio_format,
            status=status,
            session_id=request.session_id,
            turn_id=request.turn_id,
            tts_stream_id=request.tts_stream_id,
            speech_request_id=request.speech_request_id,
            error_code=error_code,
            error_message=error_message,
            metadata=dict(metadata or {}),
        )

    def _stream_user_heard_claimed(
        self,
        metadata: dict[str, Any],
        stream: VoiceLivePlaybackSession | None,
    ) -> bool:
        if stream is None or stream.chunk_count <= 0 or stream.playback_started_at is None:
            return False
        return bool(
            self.provider_name == "local"
            and (
                metadata.get("user_heard_claimed")
                or metadata.get("audible_playback")
                or stream.metadata.get("user_heard_claimed")
                or stream.metadata.get("audible_playback")
            )
        )

    async def _play_foreground(
        self,
        request: VoicePlaybackRequest,
        audio_path: Path,
        should_delete: bool,
        *,
        playback_id: str,
        availability: dict[str, Any],
    ) -> VoicePlaybackResult:
        started_at = utc_now_iso()
        started_result = self._result(
            request,
            ok=True,
            status="started",
            playback_id=playback_id,
            started_at=started_at,
            played_locally=True,
            extra_metadata={
                "availability": availability,
                "backend": availability.get("backend"),
            },
        )
        with self._lock:
            self._active_playback = started_result
            self._active_temp_path = audio_path if should_delete else None
        try:
            backend_result = await asyncio.to_thread(
                self.backend.play_file,
                    audio_path,
                    request=request,
                    playback_id=playback_id,
            )
            backend_result = dict(backend_result)
        except Exception as error:
            backend_result = {
                "status": "failed",
                "error_code": "local_playback_failed",
                "error_message": str(error),
            }
        status = str(backend_result.get("status") or "completed").strip().lower()
        if should_delete and status != "started":
            self._cleanup_temp_path(audio_path)
        ok = status in {"started", "completed", "stopped"}
        result = self._result(
            request,
            ok=ok,
            status=status,
            playback_id=playback_id,
            started_at=started_at if ok else None,
            completed_at=utc_now_iso() if status == "completed" else None,
            stopped_at=utc_now_iso() if status == "stopped" else None,
            elapsed_ms=backend_result.get("elapsed_ms")
            if isinstance(backend_result.get("elapsed_ms"), int)
            else None,
            error_code=backend_result.get("error_code") if not ok else None,
            error_message=backend_result.get("error_message") if not ok else None,
            played_locally=bool(backend_result.get("played_locally", ok)),
            extra_metadata={
                "availability": availability,
                "backend": availability.get("backend"),
            },
        )
        if status == "started":
            with self._lock:
                self._active_playback = result
                self._active_temp_path = audio_path if should_delete else None
        else:
            with self._lock:
                if (
                    self._active_playback is not None
                    and self._active_playback.playback_id == playback_id
                ):
                    self._active_playback = None
                    self._active_temp_path = None
        return result

    def _materialize_audio_path(self, request: VoicePlaybackRequest) -> tuple[Path, bool]:
        if request.file_path:
            resolved = Path(str(request.file_path))
            if resolved.exists() and resolved.is_file():
                return resolved, False
        if request.data is None:
            raise ValueError("missing_audio_output")
        temp_root = Path(self.temp_dir) if self.temp_dir is not None else Path(tempfile.gettempdir()) / "stormhelm-voice-playback"
        temp_root.mkdir(parents=True, exist_ok=True)
        suffix = "".join(character for character in request.format if character.isalnum())
        suffix = suffix or "mp3"
        path = temp_root / f"{request.playback_request_id}.{suffix}"
        path.write_bytes(bytes(request.data))
        return path, True

    def _cleanup_temp_path(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return

    def _result(
        self,
        request: VoicePlaybackRequest,
        *,
        ok: bool,
        status: str,
        playback_id: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        stopped_at: str | None = None,
        elapsed_ms: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        played_locally: bool = False,
        extra_metadata: dict[str, Any] | None = None,
    ) -> VoicePlaybackResult:
        output_metadata = {
            "audio_output_id": request.audio_output_id,
            "format": request.format,
            "mime_type": request.mime_type,
            "size_bytes": request.size_bytes,
            "duration_ms": request.duration_ms,
            "audio_ref": request.audio_ref,
            "file_path": request.file_path,
            "backend_owned_playback": True,
            "raw_audio_present": False,
        }
        if extra_metadata:
            output_metadata.update(extra_metadata)
        return VoicePlaybackResult(
            ok=ok,
            playback_request_id=request.playback_request_id,
            audio_output_id=request.audio_output_id,
            synthesis_id=request.synthesis_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            provider=self.provider_name,
            device=request.device,
            status=status,
            playback_id=playback_id or f"voice-playback-{uuid4().hex[:12]}",
            started_at=started_at,
            completed_at=completed_at,
            stopped_at=stopped_at,
            elapsed_ms=elapsed_ms,
            error_code=error_code,
            error_message=error_message,
            output_metadata=output_metadata,
            played_locally=played_locally,
            user_heard_claimed=False,
        )

    def _stream_result(
        self,
        session: VoiceLivePlaybackSession | None,
        *,
        playback_stream_id: str | None = None,
        ok: bool,
        status: str,
        completed_at: str | None = None,
        cancelled_at: str | None = None,
        partial_playback: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceLivePlaybackResult:
        session_metadata = dict(session.metadata) if session is not None else {}
        session_metadata.update(dict(metadata or {}))
        return VoiceLivePlaybackResult(
            ok=ok,
            playback_stream_id=session.playback_stream_id
            if session is not None
            else playback_stream_id,
            playback_request_id=session.playback_request_id
            if session is not None
            else None,
            provider=self.provider_name,
            device=session.device if session is not None else "default",
            audio_format=session.audio_format if session is not None else "pcm",
            status=status,
            session_id=session.session_id if session is not None else None,
            turn_id=session.turn_id if session is not None else None,
            tts_stream_id=session.tts_stream_id if session is not None else None,
            speech_request_id=session.speech_request_id if session is not None else None,
            started_at=session.started_at if session is not None else None,
            first_chunk_received_at=session.first_chunk_received_at
            if session is not None
            else None,
            playback_started_at=session.playback_started_at
            if session is not None
            else None,
            completed_at=completed_at,
            cancelled_at=cancelled_at,
            chunk_count=session.chunk_count if session is not None else 0,
            bytes_received=session.bytes_received if session is not None else 0,
            partial_playback=partial_playback,
            error_code=error_code,
            error_message=error_message,
            metadata=session_metadata,
            user_heard_claimed=False,
        )


@dataclass(slots=True)
class UnavailableWakeBackend:
    reason: str = "dependency_missing"
    backend_name: str = "unavailable"
    dependency_name: str = "not_configured"
    platform_name: str = field(default_factory=lambda: sys.platform)

    def get_availability(self, config: VoiceWakeConfig) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "dependency": self.dependency_name,
            "dependency_available": False,
            "platform_supported": True,
            "device": config.device,
            "device_available": None,
            "permission_state": "unknown",
            "permission_error": None,
            "available": False,
            "unavailable_reason": self.reason,
            "uses_real_microphone": False,
        }

    def start(
        self,
        config: VoiceWakeConfig,
        on_wake: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        del config, on_wake
        raise RuntimeError(self.reason)

    def stop(self, handle: dict[str, Any]) -> dict[str, Any]:
        del handle
        return {"backend": self.backend_name}


@dataclass(slots=True)
class LocalWakeWordProvider:
    config: VoiceWakeConfig
    backend: WakeBackend | None = None
    provider_name: str = "local"
    monitoring_active: bool = False
    active_monitoring_started_at: str | None = None
    _monitoring_handle: dict[str, Any] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.backend is None:
            self.backend = UnavailableWakeBackend(reason="dependency_missing")

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return False

    def get_availability(self) -> dict[str, Any]:
        backend_availability = self._backend_availability()
        reason: str | None = None
        if not self.config.enabled:
            reason = "wake_disabled"
        elif not self.config.allow_dev_wake:
            reason = "dev_wake_not_allowed"
        elif not self.config.wake_phrase:
            reason = "wake_phrase_missing"
        elif not bool(backend_availability.get("available")):
            reason = str(
                backend_availability.get("unavailable_reason") or "backend_unavailable"
            )
        available = reason is None
        return {
            "provider": self.provider_name,
            "provider_kind": "local",
            "available": available,
            "unavailable_reason": reason,
            "wake_phrase": self.config.wake_phrase,
            "confidence_threshold": self.config.confidence_threshold,
            "cooldown_ms": self.config.cooldown_ms,
            "monitoring_active": self.monitoring_active,
            "active_monitoring_started_at": self.active_monitoring_started_at,
            "mock_provider_active": False,
            "backend": backend_availability.get("backend"),
            "dependency": backend_availability.get("dependency"),
            "dependency_available": backend_availability.get("dependency_available"),
            "platform": backend_availability.get("platform", sys.platform),
            "platform_supported": backend_availability.get("platform_supported"),
            "device": backend_availability.get("device", self.config.device),
            "device_available": backend_availability.get("device_available"),
            "permission_state": backend_availability.get("permission_state"),
            "permission_error": backend_availability.get("permission_error"),
            "uses_real_microphone": bool(
                backend_availability.get("uses_real_microphone", False)
            ),
            "real_microphone_monitoring": bool(
                self.monitoring_active
                and backend_availability.get("uses_real_microphone", False)
            ),
            "no_cloud_wake_audio": True,
            "openai_used": False,
            "cloud_used": False,
            "raw_audio_present": False,
            "always_listening": False,
            "openai_wake_detection": False,
            "cloud_wake_detection": False,
            "command_routing_from_wake": False,
        }

    def start_wake_monitoring(self) -> VoiceProviderOperationResult:
        availability = self.get_availability()
        if self.monitoring_active:
            return VoiceProviderOperationResult(
                ok=False,
                status="blocked",
                provider_name=self.provider_name,
                error_code="monitoring_already_active",
                error_message="Wake monitoring is already active.",
                payload=availability,
            )
        if not availability["available"]:
            return VoiceProviderOperationResult(
                ok=False,
                status="unavailable",
                provider_name=self.provider_name,
                error_code=str(availability["unavailable_reason"]),
                error_message=(
                    "Local wake provider unavailable: "
                    f"{availability['unavailable_reason']}."
                ),
                payload=availability,
            )
        try:
            handle = (
                self.backend.start(self.config, on_wake=None) if self.backend else {}
            )
        except PermissionError as error:
            return self._start_failed("permission_denied", str(error), availability)
        except Exception as error:
            reason = str(error) or "backend_unavailable"
            if reason not in {
                "dependency_missing",
                "unsupported_platform",
                "device_unavailable",
                "permission_denied",
                "provider_not_configured",
                "backend_unavailable",
            }:
                reason = "backend_unavailable"
            return self._start_failed(reason, str(error), availability)
        self.monitoring_active = True
        self.active_monitoring_started_at = utc_now_iso()
        self._monitoring_handle = dict(handle or {})
        payload = {
            **self.get_availability(),
            "monitoring_active": True,
            "active_monitoring_started_at": self.active_monitoring_started_at,
        }
        return VoiceProviderOperationResult(
            ok=True,
            status="monitoring_local",
            provider_name=self.provider_name,
            payload=payload,
        )

    def stop_wake_monitoring(self) -> VoiceProviderOperationResult:
        availability = self.get_availability()
        if not self.monitoring_active:
            return VoiceProviderOperationResult(
                ok=False,
                status="no_active_wake_monitoring",
                provider_name=self.provider_name,
                error_code="no_active_wake_monitoring",
                error_message="No active local wake monitoring exists.",
                payload=availability,
            )
        try:
            if self.backend is not None:
                self.backend.stop(dict(self._monitoring_handle or {}))
        finally:
            self.monitoring_active = False
            self.active_monitoring_started_at = None
            self._monitoring_handle = None
        return VoiceProviderOperationResult(
            ok=True,
            status="stopped",
            provider_name=self.provider_name,
            payload={
                **self.get_availability(),
                "monitoring_active": False,
                "active_monitoring_started_at": None,
            },
        )

    def simulate_wake(
        self,
        *,
        session_id: str | None = None,
        confidence: float | None = None,
        source: str = "local",
    ) -> VoiceWakeEvent:
        availability = self.get_availability()
        backend = str(availability.get("backend") or self.config.backend)
        event_confidence = (
            self.config.confidence_threshold if confidence is None else confidence
        )
        if not self.monitoring_active:
            return VoiceWakeEvent(
                provider=self.provider_name,
                provider_kind="local",
                backend=backend,
                device=str(availability.get("device") or self.config.device),
                wake_phrase=self.config.wake_phrase,
                confidence=event_confidence,
                session_id=session_id,
                accepted=False,
                rejected_reason="no_active_wake_monitoring",
                source=source,
                status="rejected",
                metadata={
                    "wake_provider_boundary": "local",
                    "monitoring_active": False,
                },
            )
        return VoiceWakeEvent(
            provider=self.provider_name,
            provider_kind="local",
            backend=backend,
            device=str(availability.get("device") or self.config.device),
            wake_phrase=self.config.wake_phrase,
            confidence=event_confidence,
            session_id=session_id,
            source=source,
            metadata={
                "wake_provider_boundary": "local",
                "monitoring_active": True,
                "uses_real_microphone": availability.get("uses_real_microphone"),
            },
        )

    def get_active_wake_session(self) -> Any | None:
        return None

    def start_wake_detection(self) -> VoiceProviderOperationResult:
        return self.start_wake_monitoring()

    def stop_wake_detection(self) -> VoiceProviderOperationResult:
        return self.stop_wake_monitoring()

    def _backend_availability(self) -> dict[str, Any]:
        if self.backend is None:
            return UnavailableWakeBackend().get_availability(self.config)
        try:
            value = self.backend.get_availability(self.config)
        except PermissionError as error:
            return {
                "backend": getattr(self.backend, "backend_name", self.config.backend),
                "dependency": getattr(self.backend, "dependency_name", None),
                "dependency_available": True,
                "platform": getattr(self.backend, "platform_name", sys.platform),
                "platform_supported": True,
                "device": self.config.device,
                "device_available": None,
                "permission_state": "denied",
                "permission_error": str(error),
                "available": False,
                "unavailable_reason": "permission_denied",
                "uses_real_microphone": False,
            }
        except Exception:
            return {
                "backend": getattr(self.backend, "backend_name", self.config.backend),
                "dependency": getattr(self.backend, "dependency_name", None),
                "dependency_available": None,
                "platform": getattr(self.backend, "platform_name", sys.platform),
                "platform_supported": None,
                "device": self.config.device,
                "device_available": None,
                "permission_state": "unknown",
                "permission_error": None,
                "available": False,
                "unavailable_reason": "backend_unavailable",
                "uses_real_microphone": False,
            }
        if not isinstance(value, dict):
            value = {}
        return {
            "backend": value.get(
                "backend", getattr(self.backend, "backend_name", self.config.backend)
            ),
            "dependency": value.get(
                "dependency", getattr(self.backend, "dependency_name", None)
            ),
            "dependency_available": value.get("dependency_available"),
            "platform": value.get(
                "platform", getattr(self.backend, "platform_name", sys.platform)
            ),
            "platform_supported": value.get("platform_supported"),
            "device": value.get("device", self.config.device),
            "device_available": value.get("device_available"),
            "permission_state": value.get("permission_state", "unknown"),
            "permission_error": value.get("permission_error"),
            "available": bool(value.get("available", False)),
            "unavailable_reason": value.get("unavailable_reason"),
            "uses_real_microphone": bool(value.get("uses_real_microphone", False)),
        }

    def _start_failed(
        self,
        reason: str,
        message: str,
        availability: dict[str, Any],
    ) -> VoiceProviderOperationResult:
        payload = {
            **availability,
            "available": False,
            "unavailable_reason": reason,
            "permission_error": message if reason == "permission_denied" else None,
        }
        return VoiceProviderOperationResult(
            ok=False,
            status="wake_error",
            provider_name=self.provider_name,
            error_code=reason,
            error_message=f"Local wake monitoring failed: {reason}.",
            payload=payload,
        )


@dataclass(slots=True)
class MockWakeWordProvider:
    config: VoiceWakeConfig
    provider_name: str = "mock"
    monitoring_active: bool = False
    start_call_count: int = 0
    stop_call_count: int = 0
    simulate_call_count: int = 0

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return True

    def get_availability(self) -> dict[str, Any]:
        available = bool(self.config.enabled and self.config.allow_dev_wake)
        reason: str | None = None
        if not self.config.enabled:
            reason = "wake_disabled"
        elif not self.config.allow_dev_wake:
            reason = "dev_wake_not_allowed"
        return {
            "provider": self.provider_name,
            "provider_kind": "mock",
            "available": available,
            "unavailable_reason": reason,
            "wake_phrase": self.config.wake_phrase,
            "confidence_threshold": self.config.confidence_threshold,
            "cooldown_ms": self.config.cooldown_ms,
            "monitoring_active": self.monitoring_active,
            "mock_provider_active": True,
            "real_microphone_monitoring": False,
            "no_cloud_wake_audio": True,
            "openai_used": False,
            "cloud_used": False,
            "raw_audio_present": False,
            "always_listening": False,
        }

    def start_wake_monitoring(self) -> VoiceProviderOperationResult:
        availability = self.get_availability()
        if not availability["available"]:
            return VoiceProviderOperationResult(
                ok=False,
                status="blocked",
                provider_name=self.provider_name,
                error_code=str(availability["unavailable_reason"]),
                error_message=f"Wake monitoring blocked: {availability['unavailable_reason']}.",
                payload=availability,
            )
        self.start_call_count += 1
        self.monitoring_active = True
        return VoiceProviderOperationResult(
            ok=True,
            status="monitoring_mock",
            provider_name=self.provider_name,
            payload={
                **availability,
                "monitoring_active": True,
                "real_microphone_monitoring": False,
                "openai_used": False,
                "cloud_used": False,
                "raw_audio_present": False,
            },
        )

    def stop_wake_monitoring(self) -> VoiceProviderOperationResult:
        self.stop_call_count += 1
        self.monitoring_active = False
        return VoiceProviderOperationResult(
            ok=True,
            status="stopped",
            provider_name=self.provider_name,
            payload={
                "provider": self.provider_name,
                "provider_kind": "mock",
                "monitoring_active": False,
                "real_microphone_monitoring": False,
                "openai_used": False,
                "cloud_used": False,
                "raw_audio_present": False,
            },
        )

    def simulate_wake(
        self,
        *,
        session_id: str | None = None,
        confidence: float | None = None,
        source: str = "mock",
    ) -> VoiceWakeEvent:
        self.simulate_call_count += 1
        return VoiceWakeEvent(
            provider=self.provider_name,
            provider_kind="mock",
            wake_phrase=self.config.wake_phrase,
            confidence=self.config.confidence_threshold
            if confidence is None
            else confidence,
            session_id=session_id,
            source=source,
            metadata={
                "mock_provider_active": True,
                "monitoring_active": self.monitoring_active,
                "real_microphone_monitoring": False,
            },
        )

    def get_active_wake_session(self) -> Any | None:
        return None

    def start_wake_detection(self) -> VoiceProviderOperationResult:
        return self.start_wake_monitoring()

    def stop_wake_detection(self) -> VoiceProviderOperationResult:
        return self.stop_wake_monitoring()


@dataclass(slots=True)
class UnavailableWakeWordProvider:
    config: VoiceWakeConfig
    unavailable_reason: str = "real_wake_not_implemented"
    provider_name: str | None = None

    @property
    def name(self) -> str:
        return (
            str(self.provider_name or self.config.provider or "unavailable")
            .strip()
            .lower()
        )

    @property
    def is_mock(self) -> bool:
        return False

    def get_availability(self) -> dict[str, Any]:
        reason = self.unavailable_reason
        if not self.config.enabled:
            reason = "wake_disabled"
        return {
            "provider": self.name,
            "provider_kind": "unavailable",
            "available": False,
            "unavailable_reason": reason,
            "wake_phrase": self.config.wake_phrase,
            "confidence_threshold": self.config.confidence_threshold,
            "cooldown_ms": self.config.cooldown_ms,
            "monitoring_active": False,
            "mock_provider_active": False,
            "real_microphone_monitoring": False,
            "no_cloud_wake_audio": True,
            "openai_used": False,
            "cloud_used": False,
            "raw_audio_present": False,
            "always_listening": False,
        }

    def start_wake_monitoring(self) -> VoiceProviderOperationResult:
        availability = self.get_availability()
        return VoiceProviderOperationResult(
            ok=False,
            status="unavailable",
            provider_name=self.name,
            error_code=str(availability["unavailable_reason"]),
            error_message=f"Wake provider unavailable: {availability['unavailable_reason']}.",
            payload=availability,
        )

    def stop_wake_monitoring(self) -> VoiceProviderOperationResult:
        return VoiceProviderOperationResult(
            ok=True,
            status="stopped",
            provider_name=self.name,
            payload={
                "provider": self.name,
                "provider_kind": "unavailable",
                "monitoring_active": False,
                "openai_used": False,
                "cloud_used": False,
                "raw_audio_present": False,
            },
        )

    def simulate_wake(
        self,
        *,
        session_id: str | None = None,
        confidence: float | None = None,
        source: str = "mock",
    ) -> VoiceWakeEvent:
        return VoiceWakeEvent(
            provider=self.name,
            provider_kind="unavailable",
            wake_phrase=self.config.wake_phrase,
            confidence=0.0 if confidence is None else confidence,
            session_id=session_id,
            accepted=False,
            rejected_reason=self.unavailable_reason,
            source=source,
            status="rejected",
            metadata={"unavailable_reason": self.unavailable_reason},
        )

    def get_active_wake_session(self) -> Any | None:
        return None

    def start_wake_detection(self) -> VoiceProviderOperationResult:
        return self.start_wake_monitoring()

    def stop_wake_detection(self) -> VoiceProviderOperationResult:
        return self.stop_wake_monitoring()


@dataclass(slots=True)
class MockVADProvider:
    config: VoiceVADConfig
    provider_name: str = "mock"
    _active_session: VoiceVADSession | None = field(default=None, init=False)
    start_call_count: int = 0
    stop_call_count: int = 0
    speech_started_call_count: int = 0
    speech_stopped_call_count: int = 0

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return True

    def get_availability(self) -> dict[str, Any]:
        available = bool(self.config.enabled and self.config.allow_dev_vad)
        reason: str | None = None
        if not self.config.enabled:
            reason = "vad_disabled"
        elif not self.config.allow_dev_vad:
            reason = "dev_vad_not_allowed"
        active = self._active_session
        return {
            "provider": self.provider_name,
            "provider_kind": "mock",
            "available": available,
            "unavailable_reason": reason,
            "silence_ms": self.config.silence_ms,
            "speech_start_threshold": self.config.speech_start_threshold,
            "speech_stop_threshold": self.config.speech_stop_threshold,
            "min_speech_ms": self.config.min_speech_ms,
            "max_utterance_ms": self.config.max_utterance_ms,
            "pre_roll_ms": self.config.pre_roll_ms,
            "post_roll_ms": self.config.post_roll_ms,
            "active": active is not None,
            "active_capture_id": active.capture_id if active is not None else None,
            "active_listen_window_id": active.listen_window_id
            if active is not None
            else None,
            "mock_provider_active": True,
            "openai_used": False,
            "raw_audio_present": False,
            "semantic_completion_claimed": False,
            "command_authority": False,
            "realtime_vad": False,
        }

    def start_detection(
        self,
        *,
        capture_id: str | None = None,
        listen_window_id: str | None = None,
        session_id: str | None = None,
    ) -> VoiceVADSession:
        self.start_call_count += 1
        availability = self.get_availability()
        if not availability["available"]:
            return VoiceVADSession(
                provider=self.provider_name,
                provider_kind="mock",
                capture_id=capture_id,
                listen_window_id=listen_window_id,
                session_id=session_id,
                status="failed",
                stopped_at=utc_now_iso(),
                error_code=str(availability["unavailable_reason"]),
                error_message=f"VAD unavailable: {availability['unavailable_reason']}.",
            )
        if capture_id is None and listen_window_id is None:
            return VoiceVADSession(
                provider=self.provider_name,
                provider_kind="mock",
                session_id=session_id,
                status="failed",
                stopped_at=utc_now_iso(),
                error_code="no_capture_or_listen_window",
                error_message="VAD requires an active capture or listen window.",
            )
        if self._active_session is not None:
            return VoiceVADSession(
                provider=self.provider_name,
                provider_kind="mock",
                capture_id=capture_id,
                listen_window_id=listen_window_id,
                session_id=session_id,
                status="failed",
                stopped_at=utc_now_iso(),
                error_code="active_vad_exists",
                error_message="A VAD detection session is already active.",
            )
        session = VoiceVADSession(
            provider=self.provider_name,
            provider_kind="mock",
            capture_id=capture_id,
            listen_window_id=listen_window_id,
            session_id=session_id,
            status="active",
            metadata={
                "mock_provider_active": True,
                "semantic_completion_claimed": False,
                "command_authority": False,
                "realtime_vad": False,
            },
        )
        self._active_session = session
        return session

    def stop_detection(
        self,
        vad_session_id: str | None = None,
        *,
        reason: str = "stopped",
    ) -> VoiceVADSession:
        self.stop_call_count += 1
        active = self._active_session
        if active is None or (
            vad_session_id is not None and vad_session_id != active.vad_session_id
        ):
            return VoiceVADSession(
                provider=self.provider_name,
                provider_kind="mock",
                status="stopped",
                stopped_at=utc_now_iso(),
                error_code="no_active_vad",
                error_message="No active VAD detection session exists.",
            )
        stopped = replace(
            active,
            status="stopped",
            stopped_at=utc_now_iso(),
            finalization_reason=reason,
        )
        self._active_session = None
        return stopped

    def simulate_speech_started(
        self,
        *,
        confidence: float | None = None,
    ) -> VoiceActivityEvent:
        self.speech_started_call_count += 1
        return self._activity_event(
            status="speech_started",
            confidence=confidence
            if confidence is not None
            else self.config.speech_start_threshold,
        )

    def simulate_speech_stopped(
        self,
        *,
        confidence: float | None = None,
        duration_ms: int | None = None,
    ) -> VoiceActivityEvent:
        self.speech_stopped_call_count += 1
        return self._activity_event(
            status="speech_stopped",
            confidence=confidence
            if confidence is not None
            else self.config.speech_stop_threshold,
            duration_ms=duration_ms,
        )

    def get_active_detection(self) -> VoiceVADSession | None:
        return self._active_session

    def _activity_event(
        self,
        *,
        status: str,
        confidence: float | None = None,
        duration_ms: int | None = None,
    ) -> VoiceActivityEvent:
        active = self._active_session
        return VoiceActivityEvent(
            provider=self.provider_name,
            provider_kind="mock",
            status=status if active is not None else "vad_error",
            vad_session_id=active.vad_session_id if active is not None else None,
            capture_id=active.capture_id if active is not None else None,
            listen_window_id=active.listen_window_id if active is not None else None,
            session_id=active.session_id if active is not None else None,
            confidence=confidence,
            silence_ms=self.config.silence_ms if status == "speech_stopped" else None,
            duration_ms=duration_ms,
            metadata={
                "error_code": None if active is not None else "no_active_vad",
                "mock_provider_active": True,
                "semantic_completion_claimed": False,
                "command_authority": False,
                "realtime_vad": False,
            },
        )


@dataclass(slots=True)
class UnavailableVADProvider:
    config: VoiceVADConfig
    unavailable_reason: str = "provider_not_configured"
    provider_name: str | None = None

    @property
    def name(self) -> str:
        return (
            str(self.provider_name or self.config.provider or "unavailable")
            .strip()
            .lower()
        )

    @property
    def is_mock(self) -> bool:
        return False

    def get_availability(self) -> dict[str, Any]:
        reason = self.unavailable_reason
        if not self.config.enabled:
            reason = "vad_disabled"
        return {
            "provider": self.name,
            "provider_kind": "unavailable",
            "available": False,
            "unavailable_reason": reason,
            "silence_ms": self.config.silence_ms,
            "speech_start_threshold": self.config.speech_start_threshold,
            "speech_stop_threshold": self.config.speech_stop_threshold,
            "min_speech_ms": self.config.min_speech_ms,
            "max_utterance_ms": self.config.max_utterance_ms,
            "active": False,
            "mock_provider_active": False,
            "openai_used": False,
            "raw_audio_present": False,
            "semantic_completion_claimed": False,
            "command_authority": False,
            "realtime_vad": False,
        }

    def start_detection(
        self,
        *,
        capture_id: str | None = None,
        listen_window_id: str | None = None,
        session_id: str | None = None,
    ) -> VoiceVADSession:
        availability = self.get_availability()
        return VoiceVADSession(
            provider=self.name,
            provider_kind="unavailable",
            capture_id=capture_id,
            listen_window_id=listen_window_id,
            session_id=session_id,
            status="failed",
            stopped_at=utc_now_iso(),
            error_code=str(availability["unavailable_reason"]),
            error_message=f"VAD provider unavailable: {availability['unavailable_reason']}.",
        )

    def stop_detection(
        self,
        vad_session_id: str | None = None,
        *,
        reason: str = "stopped",
    ) -> VoiceVADSession:
        del vad_session_id
        return VoiceVADSession(
            provider=self.name,
            provider_kind="unavailable",
            status="stopped",
            stopped_at=utc_now_iso(),
            finalization_reason=reason,
        )

    def simulate_speech_started(
        self,
        *,
        confidence: float | None = None,
    ) -> VoiceActivityEvent:
        return self._unavailable_event(confidence=confidence)

    def simulate_speech_stopped(
        self,
        *,
        confidence: float | None = None,
        duration_ms: int | None = None,
    ) -> VoiceActivityEvent:
        event = self._unavailable_event(confidence=confidence)
        return replace(event, duration_ms=duration_ms)

    def get_active_detection(self) -> VoiceVADSession | None:
        return None

    def _unavailable_event(self, *, confidence: float | None) -> VoiceActivityEvent:
        return VoiceActivityEvent(
            provider=self.name,
            provider_kind="unavailable",
            status="vad_error",
            confidence=confidence,
            metadata={"error_code": self.get_availability()["unavailable_reason"]},
        )


@dataclass(slots=True)
class MockRealtimeProvider:
    config: VoiceRealtimeConfig
    provider_name: str = "mock"
    _active_session: VoiceRealtimeSession | None = field(default=None, init=False)
    _sequence_index: int = field(default=0, init=False)

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return True

    def get_availability(self) -> dict[str, Any]:
        supported_mode = self.config.mode in {
            "transcription_bridge",
            "speech_to_speech_core_bridge",
        }
        speech_mode = self.config.mode == "speech_to_speech_core_bridge"
        available = bool(
            self.config.enabled
            and self.config.allow_dev_realtime
            and supported_mode
            and (
                not speech_mode
                or (
                    self.config.speech_to_speech_enabled
                    and self.config.audio_output_from_realtime
                )
            )
        )
        reason: str | None = None
        if not self.config.enabled:
            reason = "realtime_disabled"
        elif not self.config.allow_dev_realtime:
            reason = "dev_realtime_not_allowed"
        elif not supported_mode:
            reason = "unsupported_realtime_mode"
        elif speech_mode and not self.config.speech_to_speech_enabled:
            reason = "speech_to_speech_not_enabled"
        elif speech_mode and not self.config.audio_output_from_realtime:
            reason = "realtime_audio_output_not_enabled"
        active = self._active_session
        return {
            "provider": self.provider_name,
            "provider_kind": "mock",
            "available": available,
            "unavailable_reason": reason,
            "mode": self.config.mode,
            "model": self.config.model,
            "voice": self.config.voice,
            "turn_detection": self.config.turn_detection,
            "semantic_vad_enabled": bool(self.config.semantic_vad_enabled),
            "active": active is not None and active.status == "active",
            "active_session_id": active.realtime_session_id
            if active is not None and active.status == "active"
            else None,
            "direct_tools_allowed": False,
            "core_bridge_required": True,
            "speech_to_speech_enabled": bool(
                speech_mode and self.config.speech_to_speech_enabled
            ),
            "audio_output_from_realtime": bool(
                speech_mode and self.config.audio_output_from_realtime
            ),
            "core_bridge_tool_enabled": bool(
                speech_mode and self.config.speech_to_speech_enabled
            ),
            "direct_action_tools_exposed": False,
            "require_core_for_commands": True,
            "allow_smalltalk_without_core": bool(
                self.config.allow_smalltalk_without_core
            ),
            "openai_configured": False,
            "api_key_present": False,
            "mock_provider_active": True,
            "raw_audio_present": False,
            "cloud_wake_detection": False,
            "wake_detection_local_only": True,
            "command_authority": "stormhelm_core",
        }

    def create_session(
        self,
        *,
        session_id: str | None = None,
        source: str = "test",
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeSession:
        availability = self.get_availability()
        if not availability["available"]:
            return self._terminal_session(
                session_id=session_id,
                source=source,
                listen_window_id=listen_window_id,
                capture_id=capture_id,
                status="unavailable",
                error_code=str(availability["unavailable_reason"]),
                error_message=f"Realtime unavailable: {availability['unavailable_reason']}.",
            )
        if self._active_session is not None:
            return self._terminal_session(
                session_id=session_id,
                source=source,
                listen_window_id=listen_window_id,
                capture_id=capture_id,
                status="failed",
                error_code="realtime_session_already_active",
                error_message="A Realtime transcription session is already active.",
            )
        session = VoiceRealtimeSession(
            provider=self.provider_name,
            provider_kind="mock",
            mode=self.config.mode,
            model=self.config.model,
            voice=self.config.voice,
            session_id=session_id or "default",
            source=source,
            status="created",
            turn_detection_mode=self.config.turn_detection,
            semantic_vad_enabled=bool(self.config.semantic_vad_enabled),
            speech_to_speech_enabled=bool(self.config.speech_to_speech_enabled),
            audio_output_from_realtime=bool(
                self.config.audio_output_from_realtime
            ),
            listen_window_id=listen_window_id,
            capture_id=capture_id,
            metadata={
                "mock_provider_active": True,
                "direct_tools_allowed": False,
                "core_bridge_required": True,
                "speech_to_speech_enabled": bool(
                    self.config.mode == "speech_to_speech_core_bridge"
                    and self.config.speech_to_speech_enabled
                ),
                "audio_output_from_realtime": bool(
                    self.config.mode == "speech_to_speech_core_bridge"
                    and self.config.audio_output_from_realtime
                ),
                "core_bridge_tool_enabled": bool(
                    self.config.mode == "speech_to_speech_core_bridge"
                    and self.config.speech_to_speech_enabled
                ),
                "direct_action_tools_exposed": False,
                "raw_audio_present": False,
            },
        )
        self._active_session = session
        return session

    def start_session(self, realtime_session_id: str) -> VoiceRealtimeSession:
        active = self._active_session
        if active is None or active.realtime_session_id != realtime_session_id:
            return self._terminal_session(
                session_id=None,
                source="test",
                listen_window_id=None,
                capture_id=None,
                status="failed",
                error_code="no_active_realtime_session",
                error_message="No matching Realtime transcription session exists.",
            )
        started = replace(active, status="active")
        self._active_session = started
        return started

    def close_session(
        self, realtime_session_id: str | None = None, *, reason: str = "closed"
    ) -> VoiceRealtimeSession:
        active = self._active_session
        if active is None or (
            realtime_session_id is not None
            and realtime_session_id != active.realtime_session_id
        ):
            return self._terminal_session(
                session_id=None,
                source="test",
                listen_window_id=None,
                capture_id=None,
                status="closed",
                error_code="no_active_realtime_session",
                error_message="No active Realtime transcription session exists.",
            )
        status = "cancelled" if reason == "cancelled" else "closed"
        closed = replace(active, status=status, closed_at=utc_now_iso())
        self._active_session = None
        return closed

    def get_active_session(self) -> VoiceRealtimeSession | None:
        return self._active_session

    def simulate_partial_transcript(
        self,
        transcript: str,
        *,
        realtime_session_id: str | None = None,
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeTranscriptEvent:
        return self._transcript_event(
            transcript,
            realtime_session_id=realtime_session_id,
            listen_window_id=listen_window_id,
            capture_id=capture_id,
            is_partial=True,
            is_final=False,
        )

    def simulate_final_transcript(
        self,
        transcript: str,
        *,
        realtime_session_id: str | None = None,
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeTranscriptEvent:
        return self._transcript_event(
            transcript,
            realtime_session_id=realtime_session_id,
            listen_window_id=listen_window_id,
            capture_id=capture_id,
            is_partial=False,
            is_final=True,
        )

    def _transcript_event(
        self,
        transcript: str,
        *,
        realtime_session_id: str | None,
        listen_window_id: str | None,
        capture_id: str | None,
        is_partial: bool,
        is_final: bool,
    ) -> VoiceRealtimeTranscriptEvent:
        active = self._active_session
        if active is None:
            session_id = "default"
            session_ref = realtime_session_id or "voice-realtime-session-unavailable"
            source = "mock_realtime"
            turn_id = f"voice-realtime-turn-{uuid4().hex[:12]}"
        else:
            session_id = active.session_id
            session_ref = realtime_session_id or active.realtime_session_id
            source = "mock_realtime"
            turn_id = active.active_turn_id or f"voice-realtime-turn-{uuid4().hex[:12]}"
            self._active_session = replace(active, active_turn_id=turn_id)
        self._sequence_index += 1
        return VoiceRealtimeTranscriptEvent(
            realtime_session_id=session_ref,
            realtime_turn_id=turn_id,
            session_id=session_id,
            listen_window_id=listen_window_id
            or (active.listen_window_id if active else None),
            capture_id=capture_id or (active.capture_id if active else None),
            source=source,
            transcript_text=transcript,
            is_partial=is_partial,
            is_final=is_final,
            confidence=0.9,
            sequence_index=self._sequence_index,
            provider_metadata={
                "mock": True,
                "direct_tools_allowed": False,
                "core_bridge_required": True,
                "speech_to_speech_enabled": bool(
                    active.mode == "speech_to_speech_core_bridge"
                    if active
                    else False
                ),
            },
        )

    def _terminal_session(
        self,
        *,
        session_id: str | None,
        source: str,
        listen_window_id: str | None,
        capture_id: str | None,
        status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> VoiceRealtimeSession:
        return VoiceRealtimeSession(
            provider=self.provider_name,
            provider_kind="mock",
            mode=self.config.mode,
            model=self.config.model,
            voice=self.config.voice,
            session_id=session_id or "default",
            source=source,
            status=status,
            closed_at=utc_now_iso(),
            turn_detection_mode=self.config.turn_detection,
            semantic_vad_enabled=bool(self.config.semantic_vad_enabled),
            speech_to_speech_enabled=bool(self.config.speech_to_speech_enabled),
            audio_output_from_realtime=bool(
                self.config.audio_output_from_realtime
            ),
            listen_window_id=listen_window_id,
            capture_id=capture_id,
            error_code=error_code,
            error_message=error_message,
        )


@dataclass(slots=True)
class UnavailableRealtimeProvider:
    config: VoiceRealtimeConfig
    openai_config: OpenAIConfig | None = None
    unavailable_reason: str = "provider_not_configured"
    provider_name: str | None = None

    @property
    def name(self) -> str:
        return (
            str(self.provider_name or self.config.provider or "unavailable")
            .strip()
            .lower()
        )

    @property
    def is_mock(self) -> bool:
        return False

    def get_availability(self) -> dict[str, Any]:
        reason = self.unavailable_reason
        supported_mode = self.config.mode in {
            "transcription_bridge",
            "speech_to_speech_core_bridge",
        }
        speech_mode = self.config.mode == "speech_to_speech_core_bridge"
        if not self.config.enabled:
            reason = "realtime_disabled"
        elif not supported_mode:
            reason = "unsupported_realtime_mode"
        elif self.config.provider == "mock" and not self.config.allow_dev_realtime:
            reason = "dev_realtime_not_allowed"
        elif speech_mode and not self.config.speech_to_speech_enabled:
            reason = "speech_to_speech_not_enabled"
        elif speech_mode and not self.config.audio_output_from_realtime:
            reason = "realtime_audio_output_not_enabled"
        elif self.config.provider == "openai" and (
            self.openai_config is None
            or not self.openai_config.enabled
            or not self.openai_config.api_key
        ):
            reason = "openai_config_missing"
        return {
            "provider": self.name,
            "provider_kind": "unavailable",
            "available": False,
            "unavailable_reason": reason,
            "mode": self.config.mode,
            "model": self.config.model,
            "voice": self.config.voice,
            "turn_detection": self.config.turn_detection,
            "semantic_vad_enabled": bool(self.config.semantic_vad_enabled),
            "active": False,
            "active_session_id": None,
            "direct_tools_allowed": False,
            "core_bridge_required": True,
            "speech_to_speech_enabled": bool(
                speech_mode and self.config.speech_to_speech_enabled
            ),
            "audio_output_from_realtime": bool(
                speech_mode and self.config.audio_output_from_realtime
            ),
            "core_bridge_tool_enabled": bool(
                speech_mode and self.config.speech_to_speech_enabled
            ),
            "direct_action_tools_exposed": False,
            "require_core_for_commands": True,
            "allow_smalltalk_without_core": bool(
                self.config.allow_smalltalk_without_core
            ),
            "openai_configured": bool(
                self.openai_config is not None and self.openai_config.enabled
            ),
            "api_key_present": bool(
                self.openai_config is not None and self.openai_config.api_key
            ),
            "mock_provider_active": False,
            "raw_audio_present": False,
            "cloud_wake_detection": False,
            "wake_detection_local_only": True,
            "command_authority": "stormhelm_core",
        }

    def create_session(
        self,
        *,
        session_id: str | None = None,
        source: str = "test",
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeSession:
        availability = self.get_availability()
        return VoiceRealtimeSession(
            provider=self.name,
            provider_kind="unavailable",
            mode=self.config.mode,
            model=self.config.model,
            voice=self.config.voice,
            session_id=session_id or "default",
            source=source,
            status="unavailable",
            closed_at=utc_now_iso(),
            turn_detection_mode=self.config.turn_detection,
            semantic_vad_enabled=bool(self.config.semantic_vad_enabled),
            speech_to_speech_enabled=bool(self.config.speech_to_speech_enabled),
            audio_output_from_realtime=bool(
                self.config.audio_output_from_realtime
            ),
            listen_window_id=listen_window_id,
            capture_id=capture_id,
            error_code=str(availability["unavailable_reason"]),
            error_message=(
                f"Realtime unavailable: {availability['unavailable_reason']}."
            ),
        )

    def start_session(self, realtime_session_id: str) -> VoiceRealtimeSession:
        del realtime_session_id
        return self.create_session()

    def close_session(
        self, realtime_session_id: str | None = None, *, reason: str = "closed"
    ) -> VoiceRealtimeSession:
        del realtime_session_id, reason
        return self.create_session()

    def get_active_session(self) -> VoiceRealtimeSession | None:
        return None

    def simulate_partial_transcript(
        self,
        transcript: str,
        *,
        realtime_session_id: str | None = None,
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeTranscriptEvent:
        del transcript, realtime_session_id, listen_window_id, capture_id
        raise RuntimeError("Realtime provider unavailable.")

    def simulate_final_transcript(
        self,
        transcript: str,
        *,
        realtime_session_id: str | None = None,
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeTranscriptEvent:
        del transcript, realtime_session_id, listen_window_id, capture_id
        raise RuntimeError("Realtime provider unavailable.")


@dataclass(slots=True)
class MockVoiceProvider:
    provider_name: str = "mock"
    stt_transcript: str = ""
    stt_confidence: float | None = 0.9
    stt_error_code: str | None = None
    stt_error_message: str | None = None
    stt_timeout: bool = False
    stt_unsupported_audio: bool = False
    stt_uncertain: bool = False
    stt_model: str = "mock-stt"
    stt_latency_ms: int = 0
    tts_audio_bytes: bytes = b"mock audio"
    tts_error_code: str | None = None
    tts_error_message: str | None = None
    tts_timeout: bool = False
    tts_unsupported_voice: bool = False
    tts_model: str = "mock-tts"
    tts_voice: str = "mock-voice"
    tts_format: str = "mp3"
    tts_latency_ms: int = 0
    tts_call_count: int = 0
    tts_stream_chunk_size: int = 4096
    tts_stream_error_code: str | None = None
    tts_stream_error_message: str | None = None
    tts_stream_fail_after_chunks: int | None = None
    network_call_count: int = 0

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return True

    def get_availability(self) -> VoiceAvailability:
        return VoiceAvailability(
            enabled_requested=True,
            openai_enabled=False,
            provider_configured=True,
            provider_name=self.provider_name,
            available=True,
            unavailable_reason=None,
            mode="mock",
            realtime_allowed=True,
            stt_allowed=True,
            tts_allowed=True,
            wake_allowed=True,
            mock_provider_active=True,
        )

    def create_session(self) -> VoiceProviderOperationResult:
        return self._mock_result(
            payload={"session_id": f"mock-voice-{uuid4().hex[:8]}"}
        )

    def close_session(
        self, session_id: str | None = None
    ) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"session_id": session_id})

    def submit_text_turn(
        self, text: str, *, session_id: str | None = None
    ) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"session_id": session_id, "transcript": text})

    def transcribe_audio(
        self,
        audio: VoiceAudioInput | bytes | None = None,
        *,
        content_type: str | None = None,
    ) -> VoiceProviderOperationResult | VoiceTranscriptionResult:
        if not isinstance(audio, VoiceAudioInput):
            del audio, content_type
            return self._mock_result(
                payload={"transcript": "", "confidence": None, "audio_processed": False}
            )

        if self.stt_timeout:
            return self._transcription_failure(
                audio,
                error_code="provider_timeout",
                error_message="Mock STT provider timed out.",
            )
        if self.stt_unsupported_audio:
            return self._transcription_failure(
                audio,
                error_code="unsupported_audio",
                error_message="Mock STT provider rejected the audio.",
            )
        if self.stt_error_code:
            return self._transcription_failure(
                audio,
                error_code=self.stt_error_code,
                error_message=self.stt_error_message or self.stt_error_code,
            )

        transcript = " ".join(str(self.stt_transcript or "").split()).strip()
        if not transcript:
            return self._transcription_failure(
                audio,
                error_code="empty_transcript",
                error_message="Mock STT provider returned no transcript.",
            )

        return VoiceTranscriptionResult(
            ok=True,
            input_id=audio.input_id,
            provider=self.provider_name,
            model=self.stt_model,
            transcript=transcript,
            confidence=self.stt_confidence,
            duration_ms=audio.duration_ms,
            provider_latency_ms=self.stt_latency_ms,
            raw_provider_metadata={"mock": True, "uncertain": self.stt_uncertain},
            source=f"{self.provider_name}_stt",
            usable_for_core_turn=True,
            transcription_uncertain=self.stt_uncertain,
            status="completed",
            audio_input_metadata=audio.to_metadata(),
        )

    def synthesize_speech(
        self, text: str | VoiceSpeechRequest
    ) -> VoiceProviderOperationResult | VoiceSpeechSynthesisResult:
        if not isinstance(text, VoiceSpeechRequest):
            return self._mock_result(
                payload={"text": text, "audio_playback_started": False}
            )

        self.tts_call_count += 1
        if self.tts_timeout:
            return self._speech_failure(
                text,
                error_code="provider_timeout",
                error_message="Mock TTS provider timed out.",
            )
        if self.tts_unsupported_voice:
            return self._speech_failure(
                text,
                error_code="unsupported_voice",
                error_message="Mock TTS provider rejected the configured voice.",
            )
        if self.tts_error_code:
            return self._speech_failure(
                text,
                error_code=self.tts_error_code,
                error_message=self.tts_error_message or self.tts_error_code,
            )

        audio_output = VoiceAudioOutput.from_bytes(
            self.tts_audio_bytes,
            format=text.format or self.tts_format,
            metadata={"mock": True, "speech_request_id": text.speech_request_id},
        )
        return VoiceSpeechSynthesisResult(
            ok=True,
            speech_request_id=text.speech_request_id,
            speech_request=text,
            provider=self.provider_name,
            model=text.model or self.tts_model,
            voice=text.voice or self.tts_voice,
            format=text.format or self.tts_format,
            status="succeeded",
            audio_output=audio_output,
            output_size_bytes=audio_output.size_bytes,
            provider_latency_ms=self.tts_latency_ms,
            raw_provider_metadata={"mock": True},
            playable=False,
            persisted=False,
        )

    async def stream_speech(
        self, request: VoiceStreamingTTSRequest
    ) -> VoiceStreamingTTSResult:
        return await self.stream_speech_progressive(request, None)

    async def stream_speech_progressive(
        self,
        request: VoiceStreamingTTSRequest,
        on_chunk: VoiceStreamingChunkCallback | None,
    ) -> VoiceStreamingTTSResult:
        speech_request = request.speech_request
        self.tts_call_count += 1
        if self.tts_stream_error_code and not self.tts_stream_fail_after_chunks:
            return VoiceStreamingTTSResult(
                ok=False,
                tts_stream_id=request.tts_stream_id,
                speech_request_id=speech_request.speech_request_id,
                provider=self.provider_name,
                model=speech_request.model or self.tts_model,
                voice=speech_request.voice or self.tts_voice,
                live_format=request.live_format,
                artifact_format=request.artifact_format,
                status="failed",
                streaming_transport_kind="mock_stream",
                first_chunk_before_complete=False,
                stream_start_monotonic_ms=0,
                stream_complete_monotonic_ms=0,
                stream_complete_ms=0,
                bytes_total_summary_only=0,
                streaming_started=True,
                streaming_completed=False,
                error_code=self.tts_stream_error_code,
                error_message=self.tts_stream_error_message
                or self.tts_stream_error_code,
                metadata={"mock": True, "raw_audio_present": False},
            )
        if self.tts_timeout:
            return self._stream_failure(
                request,
                error_code="provider_timeout",
                error_message="Mock streaming TTS provider timed out.",
            )
        if self.tts_error_code:
            return self._stream_failure(
                request,
                error_code=self.tts_error_code,
                error_message=self.tts_error_message or self.tts_error_code,
            )
        payload = bytes(self.tts_audio_bytes or b"")
        chunk_size = max(1, int(self.tts_stream_chunk_size or len(payload) or 1))
        chunks: list[VoiceStreamingTTSChunk] = []
        started = time.perf_counter()
        for index, offset in enumerate(range(0, len(payload), chunk_size)):
            chunk_bytes = payload[offset : offset + chunk_size]
            now = utc_now_iso()
            chunk = VoiceStreamingTTSChunk(
                tts_stream_id=request.tts_stream_id,
                speech_request_id=speech_request.speech_request_id,
                chunk_index=index,
                size_bytes=len(chunk_bytes),
                live_format=request.live_format,
                provider=self.provider_name,
                model=speech_request.model or self.tts_model,
                voice=speech_request.voice or self.tts_voice,
                session_id=speech_request.session_id,
                turn_id=speech_request.turn_id,
                received_at=now,
                first_chunk=index == 0,
                final_chunk=offset + chunk_size >= len(payload),
                duration_ms=_elapsed_ms(started),
                metadata={"mock": True, "raw_audio_present": False},
                data=chunk_bytes,
            )
            chunks.append(chunk)
            await _dispatch_streaming_chunk(on_chunk, chunk)
            if (
                self.tts_stream_fail_after_chunks is not None
                and len(chunks) >= self.tts_stream_fail_after_chunks
            ):
                return VoiceStreamingTTSResult(
                    ok=False,
                    tts_stream_id=request.tts_stream_id,
                    speech_request_id=speech_request.speech_request_id,
                    provider=self.provider_name,
                    model=speech_request.model or self.tts_model,
                    voice=speech_request.voice or self.tts_voice,
                    live_format=request.live_format,
                    artifact_format=request.artifact_format,
                    status="partial_failed",
                    chunks=tuple(chunks),
                    first_chunk_at=chunks[0].received_at if chunks else None,
                    final_chunk_at=now,
                    total_chunks=len(chunks),
                    first_audio_byte_ms=_elapsed_ms(started),
                    streaming_transport_kind="mock_stream",
                    first_chunk_before_complete=True,
                    stream_start_monotonic_ms=0,
                    first_chunk_monotonic_ms=chunks[0].duration_ms
                    if chunks
                    else None,
                    stream_complete_monotonic_ms=_elapsed_ms(started),
                    stream_complete_ms=_elapsed_ms(started),
                    bytes_total_summary_only=sum(chunk.size_bytes for chunk in chunks),
                    streaming_started=True,
                    streaming_completed=False,
                    partial_audio=bool(chunks),
                    error_code=self.tts_stream_error_code or "stream_failed",
                    error_message=self.tts_stream_error_message
                    or self.tts_stream_error_code
                    or "Mock streaming TTS failed after partial audio.",
                    metadata={"mock": True, "raw_audio_present": False},
                )
        return VoiceStreamingTTSResult(
            ok=True,
            tts_stream_id=request.tts_stream_id,
            speech_request_id=speech_request.speech_request_id,
            provider=self.provider_name,
            model=speech_request.model or self.tts_model,
            voice=speech_request.voice or self.tts_voice,
            live_format=request.live_format,
            artifact_format=request.artifact_format,
            status="completed",
            chunks=tuple(chunks),
            first_chunk_at=chunks[0].received_at if chunks else None,
            final_chunk_at=chunks[-1].received_at if chunks else utc_now_iso(),
            total_chunks=len(chunks),
            first_audio_byte_ms=_elapsed_ms(started) if chunks else None,
            streaming_transport_kind="mock_stream",
            first_chunk_before_complete=bool(chunks),
            stream_start_monotonic_ms=0,
            first_chunk_monotonic_ms=chunks[0].duration_ms if chunks else None,
            stream_complete_monotonic_ms=_elapsed_ms(started),
            stream_complete_ms=_elapsed_ms(started),
            bytes_total_summary_only=sum(chunk.size_bytes for chunk in chunks),
            streaming_started=True,
            streaming_completed=True,
            partial_audio=False,
            metadata={"mock": True, "raw_audio_present": False},
        )

    def prewarm_speech_provider(
        self, request: VoiceProviderPrewarmRequest
    ) -> VoiceProviderPrewarmResult:
        return VoiceProviderPrewarmResult(
            ok=True,
            request_id=request.request_id,
            provider=self.provider_name,
            status="prepared",
            model=request.model or self.tts_model,
            voice=request.voice or self.tts_voice,
            live_format=request.live_format,
            artifact_format=request.artifact_format,
            api_key_present=False,
            client_prepared=True,
            request_shell_prepared=True,
            tts_called=False,
            network_called=False,
            prewarm_ms=0,
            metadata={"mock": True, "raw_audio_present": False},
        )

    def _stream_failure(
        self,
        request: VoiceStreamingTTSRequest,
        *,
        error_code: str,
        error_message: str,
    ) -> VoiceStreamingTTSResult:
        speech_request = request.speech_request
        return VoiceStreamingTTSResult(
            ok=False,
            tts_stream_id=request.tts_stream_id,
            speech_request_id=speech_request.speech_request_id,
            provider=self.provider_name,
            model=speech_request.model or self.tts_model,
            voice=speech_request.voice or self.tts_voice,
            live_format=request.live_format,
            artifact_format=request.artifact_format,
            status="failed",
            streaming_transport_kind="mock_stream",
            first_chunk_before_complete=False,
            stream_start_monotonic_ms=0,
            stream_complete_monotonic_ms=0,
            stream_complete_ms=0,
            bytes_total_summary_only=0,
            streaming_started=True,
            streaming_completed=False,
            error_code=error_code,
            error_message=error_message,
            metadata={"mock": True, "raw_audio_present": False},
        )

    def _transcription_failure(
        self,
        audio: VoiceAudioInput,
        *,
        error_code: str,
        error_message: str,
    ) -> VoiceTranscriptionResult:
        return VoiceTranscriptionResult(
            ok=False,
            input_id=audio.input_id,
            provider=self.provider_name,
            model=self.stt_model,
            transcript="",
            duration_ms=audio.duration_ms,
            provider_latency_ms=self.stt_latency_ms,
            error_code=error_code,
            error_message=error_message,
            raw_provider_metadata={"mock": True},
            source=f"{self.provider_name}_stt",
            usable_for_core_turn=False,
            transcription_uncertain=True,
            status="failed",
            audio_input_metadata=audio.to_metadata(),
        )

    def start_listening(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"listening_started": False})

    def _speech_failure(
        self,
        request: VoiceSpeechRequest,
        *,
        error_code: str,
        error_message: str,
    ) -> VoiceSpeechSynthesisResult:
        return VoiceSpeechSynthesisResult(
            ok=False,
            speech_request_id=request.speech_request_id,
            speech_request=request,
            provider=self.provider_name,
            model=request.model or self.tts_model,
            voice=request.voice or self.tts_voice,
            format=request.format or self.tts_format,
            status="failed",
            provider_latency_ms=self.tts_latency_ms,
            error_code=error_code,
            error_message=error_message,
            raw_provider_metadata={"mock": True},
            playable=False,
            persisted=False,
        )

    def stop_listening(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"listening_stopped": True})

    def start_wake_detection(self) -> VoiceProviderOperationResult:
        return self._mock_result(
            payload={"wake_detection_started": False, "audio_sent_to_cloud": False}
        )

    def stop_wake_detection(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"wake_detection_stopped": True})

    def start_wake_monitoring(self) -> VoiceProviderOperationResult:
        return self._mock_result(
            payload={
                "wake_monitoring_started": False,
                "mock_provider_active": True,
                "real_microphone_monitoring": False,
                "openai_used": False,
                "raw_audio_present": False,
            }
        )

    def stop_wake_monitoring(self) -> VoiceProviderOperationResult:
        return self._mock_result(
            payload={
                "wake_monitoring_stopped": True,
                "real_microphone_monitoring": False,
                "openai_used": False,
                "raw_audio_present": False,
            }
        )

    def simulate_wake(
        self,
        *,
        session_id: str | None = None,
        confidence: float | None = None,
        source: str = "mock",
    ) -> VoiceWakeEvent:
        return VoiceWakeEvent(
            provider=self.provider_name,
            provider_kind="mock",
            wake_phrase="Stormhelm",
            confidence=0.9 if confidence is None else confidence,
            session_id=session_id,
            source=source,
            metadata={
                "mock_provider_active": True,
                "real_microphone_monitoring": False,
            },
        )

    def get_active_wake_session(self) -> Any | None:
        return None

    def start_audio_input(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_input_started": False})

    def stop_audio_input(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_input_stopped": True})

    def start_audio_output(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_output_started": False})

    def stop_audio_output(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_output_stopped": True})

    def _mock_result(
        self, *, payload: dict[str, Any] | None = None
    ) -> VoiceProviderOperationResult:
        return VoiceProviderOperationResult(
            ok=True,
            status="mock",
            provider_name=self.provider_name,
            payload=dict(payload or {}),
        )


@dataclass(slots=True)
class OpenAIVoiceProviderStub:
    config: VoiceConfig
    openai_config: OpenAIConfig
    network_call_count: int = 0

    @property
    def name(self) -> str:
        return "openai"

    @property
    def is_mock(self) -> bool:
        return False

    def get_availability(self) -> VoiceAvailability:
        return compute_voice_availability(self.config, self.openai_config)

    def create_session(self) -> VoiceProviderOperationResult:
        return self._not_implemented(
            "OpenAI Realtime sessions are not implemented in Voice-0."
        )

    def close_session(
        self, session_id: str | None = None
    ) -> VoiceProviderOperationResult:
        del session_id
        return self._not_implemented(
            "OpenAI voice sessions are not implemented in Voice-0."
        )

    def submit_text_turn(
        self, text: str, *, session_id: str | None = None
    ) -> VoiceProviderOperationResult:
        del text, session_id
        return self._not_implemented(
            "Voice text turns must cross the Core bridge in a later phase."
        )

    def transcribe_audio(
        self, audio: bytes | None = None, *, content_type: str | None = None
    ) -> VoiceProviderOperationResult:
        del audio, content_type
        return self._not_implemented(
            "OpenAI speech-to-text is not implemented in Voice-0."
        )

    def synthesize_speech(self, text: str) -> VoiceProviderOperationResult:
        del text
        return self._not_implemented(
            "OpenAI text-to-speech is not implemented in Voice-0."
        )

    def start_listening(self) -> VoiceProviderOperationResult:
        return self._not_implemented(
            "Realtime listening is not implemented in Voice-0."
        )

    def stop_listening(self) -> VoiceProviderOperationResult:
        return self._not_implemented(
            "Realtime listening is not implemented in Voice-0."
        )

    def start_wake_detection(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Wake detection is not implemented in Voice-0.")

    def stop_wake_detection(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Wake detection is not implemented in Voice-0.")

    def start_audio_input(self) -> VoiceProviderOperationResult:
        return self._not_implemented(
            "Microphone capture is not implemented in Voice-0."
        )

    def stop_audio_input(self) -> VoiceProviderOperationResult:
        return self._not_implemented(
            "Microphone capture is not implemented in Voice-0."
        )

    def start_audio_output(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Audio playback is not implemented in Voice-0.")

    def stop_audio_output(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Audio playback is not implemented in Voice-0.")

    def _not_implemented(self, message: str) -> VoiceProviderOperationResult:
        return VoiceProviderOperationResult(
            ok=False,
            status="not_implemented",
            provider_name=self.name,
            error_code="not_implemented",
            error_message=message,
        )


PostTranscription = Callable[
    ...,
    dict[str, Any] | Awaitable[dict[str, Any]],
]

PostSpeech = Callable[
    ...,
    bytes | dict[str, Any] | Awaitable[bytes | dict[str, Any]],
]

PostSpeechStream = Callable[
    ...,
    Iterable[bytes] | AsyncIterable[bytes] | Awaitable[Iterable[bytes] | AsyncIterable[bytes]],
]


@dataclass(slots=True)
class OpenAIVoiceProvider(OpenAIVoiceProviderStub):
    post_transcription: PostTranscription | None = None
    post_speech: PostSpeech | None = None
    post_speech_stream: PostSpeechStream | None = None

    @property
    def stt_model(self) -> str:
        return (
            str(self.config.openai.stt_model or "").strip() or "gpt-4o-mini-transcribe"
        )

    @property
    def tts_model(self) -> str:
        return str(self.config.openai.tts_model or "").strip() or "gpt-4o-mini-tts"

    @property
    def tts_voice(self) -> str:
        return str(self.config.openai.tts_voice or "").strip() or "onyx"

    @property
    def tts_format(self) -> str:
        return str(self.config.openai.tts_format or "mp3").strip().lower() or "mp3"

    @property
    def tts_live_format(self) -> str:
        return (
            str(self.config.openai.tts_live_format or "pcm").strip().lower() or "pcm"
        )

    @property
    def tts_artifact_format(self) -> str:
        return (
            str(self.config.openai.tts_artifact_format or self.tts_format)
            .strip()
            .lower()
            or "mp3"
        )

    async def transcribe_audio(
        self,
        audio: VoiceAudioInput | bytes | None = None,
        *,
        content_type: str | None = None,
    ) -> VoiceProviderOperationResult | VoiceTranscriptionResult:
        if not isinstance(audio, VoiceAudioInput):
            del content_type
            return self._not_implemented(
                "OpenAI speech-to-text requires a typed VoiceAudioInput in Voice-2."
            )
        if not self.openai_config.enabled or not self.openai_config.api_key:
            return self._transcription_failure(
                audio,
                error_code="provider_unavailable",
                error_message="OpenAI STT is unavailable because OpenAI is disabled or missing credentials.",
            )

        start = time.perf_counter()
        self.network_call_count += 1
        try:
            payload = await self._post_transcription(audio)
        except TimeoutError:
            return self._transcription_failure(
                audio,
                error_code="provider_timeout",
                error_message="OpenAI STT provider timed out.",
                provider_latency_ms=_elapsed_ms(start),
            )
        except httpx.TimeoutException:
            return self._transcription_failure(
                audio,
                error_code="provider_timeout",
                error_message="OpenAI STT provider timed out.",
                provider_latency_ms=_elapsed_ms(start),
            )
        except Exception as error:
            return self._transcription_failure(
                audio,
                error_code="provider_error",
                error_message=str(error),
                provider_latency_ms=_elapsed_ms(start),
            )

        transcript = " ".join(
            str(payload.get("text") or payload.get("transcript") or "").split()
        ).strip()
        if not transcript:
            return self._transcription_failure(
                audio,
                error_code="empty_transcript",
                error_message="OpenAI STT returned no transcript.",
                provider_latency_ms=_elapsed_ms(start),
                raw_provider_metadata=_sanitize_openai_metadata(payload),
            )

        duration_value = payload.get("duration_ms", payload.get("duration"))
        duration_ms = audio.duration_ms
        if duration_ms is None and isinstance(duration_value, (int, float)):
            duration_ms = (
                int(duration_value * 1000)
                if duration_value < 1000
                else int(duration_value)
            )
        confidence = payload.get("confidence")
        return VoiceTranscriptionResult(
            ok=True,
            input_id=audio.input_id,
            provider="openai",
            model=self.stt_model,
            transcript=transcript,
            language=str(payload.get("language") or "").strip()
            or self.config.openai.transcription_language,
            confidence=float(confidence)
            if isinstance(confidence, (int, float))
            else None,
            duration_ms=duration_ms,
            provider_latency_ms=_elapsed_ms(start),
            raw_provider_metadata=_sanitize_openai_metadata(payload),
            source="openai_stt",
            usable_for_core_turn=True,
            transcription_uncertain=False,
            status="completed",
            audio_input_metadata=audio.to_metadata(),
        )

    async def _post_transcription(self, audio: VoiceAudioInput) -> dict[str, Any]:
        data = {
            "model": self.stt_model,
            "response_format": "json",
        }
        if self.config.openai.transcription_language:
            data["language"] = self.config.openai.transcription_language
        if self.config.openai.transcription_prompt:
            data["prompt"] = self.config.openai.transcription_prompt
        files = {"file": (audio.filename, audio.read_bytes(), audio.mime_type)}
        timeout = float(
            self.config.openai.timeout_seconds or self.openai_config.timeout_seconds
        )
        url = f"{self.openai_config.base_url.rstrip('/')}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.openai_config.api_key}"}

        if self.post_transcription is not None:
            result = self.post_transcription(
                url=url, headers=headers, data=data, files=files, timeout=timeout
            )
            if hasattr(result, "__await__"):
                return await result  # type: ignore[no-any-return]
            return dict(result)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}

    def _transcription_failure(
        self,
        audio: VoiceAudioInput,
        *,
        error_code: str,
        error_message: str,
        provider_latency_ms: int | None = None,
        raw_provider_metadata: dict[str, Any] | None = None,
    ) -> VoiceTranscriptionResult:
        return VoiceTranscriptionResult(
            ok=False,
            input_id=audio.input_id,
            provider="openai",
            model=self.stt_model,
            transcript="",
            duration_ms=audio.duration_ms,
            provider_latency_ms=provider_latency_ms,
            error_code=error_code,
            error_message=error_message,
            raw_provider_metadata=dict(raw_provider_metadata or {}),
            source="openai_stt",
            usable_for_core_turn=False,
            transcription_uncertain=True,
            status="failed",
            audio_input_metadata=audio.to_metadata(),
        )

    async def synthesize_speech(
        self, text: str | VoiceSpeechRequest
    ) -> VoiceProviderOperationResult | VoiceSpeechSynthesisResult:
        if not isinstance(text, VoiceSpeechRequest):
            return self._not_implemented(
                "OpenAI text-to-speech requires a typed VoiceSpeechRequest in Voice-3."
            )
        if not self.openai_config.enabled or not self.openai_config.api_key:
            return self._speech_failure(
                text,
                error_code="provider_unavailable",
                error_message="OpenAI TTS is unavailable because OpenAI is disabled or missing credentials.",
            )

        start = time.perf_counter()
        self.network_call_count += 1
        try:
            payload = await self._post_speech(text)
        except TimeoutError:
            return self._speech_failure(
                text,
                error_code="provider_timeout",
                error_message="OpenAI TTS provider timed out.",
                provider_latency_ms=_elapsed_ms(start),
            )
        except httpx.TimeoutException:
            return self._speech_failure(
                text,
                error_code="provider_timeout",
                error_message="OpenAI TTS provider timed out.",
                provider_latency_ms=_elapsed_ms(start),
            )
        except Exception as error:
            return self._speech_failure(
                text,
                error_code="provider_error",
                error_message=str(error),
                provider_latency_ms=_elapsed_ms(start),
            )

        audio_bytes, provider_metadata = _speech_payload_to_bytes_and_metadata(payload)
        if not audio_bytes:
            return self._speech_failure(
                text,
                error_code="empty_audio_output",
                error_message="OpenAI TTS returned no audio bytes.",
                provider_latency_ms=_elapsed_ms(start),
                raw_provider_metadata=provider_metadata,
            )

        audio_output = self._build_tts_audio_output(text, audio_bytes)
        persisted = bool(audio_output.file_path)
        return VoiceSpeechSynthesisResult(
            ok=True,
            speech_request_id=text.speech_request_id,
            speech_request=text,
            provider="openai",
            model=text.model or self.tts_model,
            voice=text.voice or self.tts_voice,
            format=text.format or self.tts_format,
            status="succeeded",
            audio_output=audio_output,
            output_size_bytes=audio_output.size_bytes,
            provider_latency_ms=_elapsed_ms(start),
            raw_provider_metadata=provider_metadata,
            playable=False,
            persisted=persisted,
        )

    async def _post_speech(self, request: VoiceSpeechRequest) -> bytes | dict[str, Any]:
        url, headers, body, timeout = self._speech_http_request(request)

        if self.post_speech is not None:
            result = self.post_speech(
                url=url, headers=headers, json=body, timeout=timeout
            )
            if hasattr(result, "__await__"):
                return await result  # type: ignore[no-any-return]
            return result

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.content

    def _speech_http_request(
        self, request: VoiceSpeechRequest
    ) -> tuple[str, dict[str, str], dict[str, object], float]:
        body: dict[str, object] = {
            "model": request.model or self.tts_model,
            "input": request.text,
            "voice": request.voice or self.tts_voice,
            "response_format": request.format or self.tts_format,
            "speed": float(self.config.openai.tts_speed or 1.0),
        }
        timeout = float(
            self.config.openai.timeout_seconds or self.openai_config.timeout_seconds
        )
        url = f"{self.openai_config.base_url.rstrip('/')}/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.openai_config.api_key}",
            "Content-Type": "application/json",
        }
        return url, headers, body, timeout

    async def _post_speech_stream(
        self, request: VoiceSpeechRequest
    ) -> AsyncIterable[bytes]:
        url, headers, body, timeout = self._speech_http_request(request)
        if self.post_speech_stream is not None:
            stream = self.post_speech_stream(
                url=url, headers=headers, json=body, timeout=timeout
            )
            if hasattr(stream, "__await__"):
                stream = await stream  # type: ignore[assignment]
            if hasattr(stream, "__aiter__"):
                async for chunk in stream:  # type: ignore[union-attr]
                    if chunk:
                        yield bytes(chunk)
            else:
                for chunk in stream:  # type: ignore[union-attr]
                    if chunk:
                        yield bytes(chunk)
            return

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=body) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield bytes(chunk)

    def _build_tts_audio_output(
        self, request: VoiceSpeechRequest, audio_bytes: bytes
    ) -> VoiceAudioOutput:
        if (
            self.config.openai.persist_tts_outputs
            and self.config.openai.output_audio_dir
        ):
            directory = Path(self.config.openai.output_audio_dir)
            directory.mkdir(parents=True, exist_ok=True)
            suffix = (request.format or self.tts_format).strip().lower() or "mp3"
            path = directory / f"{request.speech_request_id}.{suffix}"
            path.write_bytes(audio_bytes)
            return VoiceAudioOutput.from_file(
                path,
                format=suffix,
                metadata={"speech_request_id": request.speech_request_id},
            )
        return VoiceAudioOutput.from_bytes(
            audio_bytes,
            format=request.format or self.tts_format,
            metadata={"speech_request_id": request.speech_request_id},
        )

    def _speech_failure(
        self,
        request: VoiceSpeechRequest,
        *,
        error_code: str,
        error_message: str,
        provider_latency_ms: int | None = None,
        raw_provider_metadata: dict[str, Any] | None = None,
    ) -> VoiceSpeechSynthesisResult:
        return VoiceSpeechSynthesisResult(
            ok=False,
            speech_request_id=request.speech_request_id,
            speech_request=request,
            provider="openai",
            model=request.model or self.tts_model,
            voice=request.voice or self.tts_voice,
            format=request.format or self.tts_format,
            status="failed",
            provider_latency_ms=provider_latency_ms,
            error_code=error_code,
            error_message=error_message,
            raw_provider_metadata=dict(raw_provider_metadata or {}),
            playable=False,
            persisted=False,
        )

    async def stream_speech(
        self, request: VoiceStreamingTTSRequest
    ) -> VoiceStreamingTTSResult:
        return await self.stream_speech_progressive(request, None)

    async def stream_speech_progressive(
        self,
        request: VoiceStreamingTTSRequest,
        on_chunk: VoiceStreamingChunkCallback | None,
    ) -> VoiceStreamingTTSResult:
        speech_request = request.speech_request
        if not self.openai_config.enabled or not self.openai_config.api_key:
            return self._stream_failure(
                request,
                error_code="provider_unavailable",
                error_message="OpenAI TTS is unavailable because OpenAI is disabled or missing credentials.",
            )
        stream_request = replace(
            speech_request,
            format=request.live_format or self.tts_live_format,
        )
        start = time.perf_counter()
        self.network_call_count += 1
        if self.post_speech is not None and self.post_speech_stream is None:
            return await self._stream_speech_buffered_projection(
                request,
                stream_request,
                start,
            )
        chunks: list[VoiceStreamingTTSChunk] = []
        bytes_total = 0
        try:
            async for chunk_bytes in self._post_speech_stream(stream_request):
                bytes_total += len(chunk_bytes)
                index = len(chunks)
                elapsed = _elapsed_ms(start)
                chunk = VoiceStreamingTTSChunk(
                    tts_stream_id=request.tts_stream_id,
                    speech_request_id=speech_request.speech_request_id,
                    chunk_index=index,
                    size_bytes=len(chunk_bytes),
                    live_format=request.live_format or self.tts_live_format,
                    provider="openai",
                    model=speech_request.model or self.tts_model,
                    voice=speech_request.voice or self.tts_voice,
                    session_id=speech_request.session_id,
                    turn_id=speech_request.turn_id,
                    first_chunk=index == 0,
                    final_chunk=False,
                    duration_ms=elapsed,
                    metadata={
                        "response_kind": "stream_bytes",
                        "raw_audio_present": False,
                    },
                    data=chunk_bytes,
                )
                chunks.append(chunk)
                await _dispatch_streaming_chunk(on_chunk, chunk)
        except TimeoutError:
            return self._stream_failure(
                request,
                error_code="provider_timeout",
                error_message="OpenAI streaming TTS provider timed out.",
                streaming_transport_kind="true_http_stream",
            )
        except httpx.TimeoutException:
            return self._stream_failure(
                request,
                error_code="provider_timeout",
                error_message="OpenAI streaming TTS provider timed out.",
                streaming_transport_kind="true_http_stream",
            )
        except Exception as error:
            if chunks:
                stream_complete_ms = _elapsed_ms(start)
                chunks[-1] = replace(chunks[-1], final_chunk=True)
                return VoiceStreamingTTSResult(
                    ok=False,
                    tts_stream_id=request.tts_stream_id,
                    speech_request_id=speech_request.speech_request_id,
                    provider="openai",
                    model=speech_request.model or self.tts_model,
                    voice=speech_request.voice or self.tts_voice,
                    live_format=request.live_format or self.tts_live_format,
                    artifact_format=request.artifact_format or self.tts_artifact_format,
                    status="partial_failed",
                    chunks=tuple(chunks),
                    first_chunk_at=chunks[0].received_at,
                    final_chunk_at=chunks[-1].received_at,
                    total_chunks=len(chunks),
                    first_audio_byte_ms=chunks[0].duration_ms,
                    streaming_transport_kind="true_http_stream",
                    first_chunk_before_complete=True,
                    stream_start_monotonic_ms=0,
                    first_chunk_monotonic_ms=chunks[0].duration_ms,
                    stream_complete_monotonic_ms=stream_complete_ms,
                    stream_complete_ms=stream_complete_ms,
                    bytes_total_summary_only=bytes_total,
                    streaming_started=True,
                    streaming_completed=False,
                    partial_audio=True,
                    error_code="provider_error",
                    error_message=str(error),
                    metadata={"raw_audio_present": False},
                )
            return self._stream_failure(
                request,
                error_code="provider_error",
                error_message=str(error),
                streaming_transport_kind="true_http_stream",
            )
        if not chunks:
            return self._stream_failure(
                request,
                error_code="empty_audio_output",
                error_message="OpenAI TTS returned no streaming audio bytes.",
                streaming_transport_kind="true_http_stream",
            )
        stream_complete_ms = _elapsed_ms(start)
        chunks[-1] = replace(chunks[-1], final_chunk=True)
        first_chunk_ms = chunks[0].duration_ms
        return VoiceStreamingTTSResult(
            ok=True,
            tts_stream_id=request.tts_stream_id,
            speech_request_id=speech_request.speech_request_id,
            provider="openai",
            model=speech_request.model or self.tts_model,
            voice=speech_request.voice or self.tts_voice,
            live_format=request.live_format or self.tts_live_format,
            artifact_format=request.artifact_format or self.tts_artifact_format,
            status="completed",
            chunks=tuple(chunks),
            first_chunk_at=chunks[0].received_at,
            final_chunk_at=chunks[-1].received_at,
            total_chunks=len(chunks),
            first_audio_byte_ms=first_chunk_ms,
            streaming_transport_kind="true_http_stream",
            first_chunk_before_complete=True,
            stream_start_monotonic_ms=0,
            first_chunk_monotonic_ms=first_chunk_ms,
            stream_complete_monotonic_ms=stream_complete_ms,
            stream_complete_ms=stream_complete_ms,
            bytes_total_summary_only=bytes_total,
            streaming_started=True,
            streaming_completed=True,
            metadata={"raw_audio_present": False},
        )

    async def _stream_speech_buffered_projection(
        self,
        request: VoiceStreamingTTSRequest,
        stream_request: VoiceSpeechRequest,
        start: float,
    ) -> VoiceStreamingTTSResult:
        speech_request = request.speech_request
        try:
            payload = await self._post_speech(stream_request)
        except TimeoutError:
            return self._stream_failure(
                request,
                error_code="provider_timeout",
                error_message="OpenAI streaming TTS provider timed out.",
                streaming_transport_kind="buffered_chunk_projection",
            )
        except httpx.TimeoutException:
            return self._stream_failure(
                request,
                error_code="provider_timeout",
                error_message="OpenAI streaming TTS provider timed out.",
                streaming_transport_kind="buffered_chunk_projection",
            )
        except Exception as error:
            return self._stream_failure(
                request,
                error_code="provider_error",
                error_message=str(error),
                streaming_transport_kind="buffered_chunk_projection",
            )
        audio_bytes, provider_metadata = _speech_payload_to_bytes_and_metadata(payload)
        if not audio_bytes:
            return self._stream_failure(
                request,
                error_code="empty_audio_output",
                error_message="OpenAI TTS returned no streaming audio bytes.",
                metadata=provider_metadata,
                streaming_transport_kind="buffered_chunk_projection",
            )
        stream_complete_ms = _elapsed_ms(start)
        chunk_size = max(1, min(16384, len(audio_bytes)))
        chunks: list[VoiceStreamingTTSChunk] = []
        for index, offset in enumerate(range(0, len(audio_bytes), chunk_size)):
            chunk_bytes = audio_bytes[offset : offset + chunk_size]
            chunks.append(
                VoiceStreamingTTSChunk(
                    tts_stream_id=request.tts_stream_id,
                    speech_request_id=speech_request.speech_request_id,
                    chunk_index=index,
                    size_bytes=len(chunk_bytes),
                    live_format=request.live_format or self.tts_live_format,
                    provider="openai",
                    model=speech_request.model or self.tts_model,
                    voice=speech_request.voice or self.tts_voice,
                    session_id=speech_request.session_id,
                    turn_id=speech_request.turn_id,
                    first_chunk=index == 0,
                    final_chunk=offset + chunk_size >= len(audio_bytes),
                    duration_ms=stream_complete_ms,
                    metadata={
                        "response_kind": "buffered_projection",
                        "raw_audio_present": False,
                    },
                    data=chunk_bytes,
                )
            )
        return VoiceStreamingTTSResult(
            ok=True,
            tts_stream_id=request.tts_stream_id,
            speech_request_id=speech_request.speech_request_id,
            provider="openai",
            model=speech_request.model or self.tts_model,
            voice=speech_request.voice or self.tts_voice,
            live_format=request.live_format or self.tts_live_format,
            artifact_format=request.artifact_format or self.tts_artifact_format,
            status="completed",
            chunks=tuple(chunks),
            first_chunk_at=chunks[0].received_at if chunks else None,
            final_chunk_at=chunks[-1].received_at if chunks else None,
            total_chunks=len(chunks),
            first_audio_byte_ms=stream_complete_ms if chunks else None,
            streaming_transport_kind="buffered_chunk_projection",
            first_chunk_before_complete=False,
            stream_start_monotonic_ms=0,
            first_chunk_monotonic_ms=stream_complete_ms if chunks else None,
            stream_complete_monotonic_ms=stream_complete_ms,
            stream_complete_ms=stream_complete_ms,
            bytes_total_summary_only=len(audio_bytes),
            streaming_started=True,
            streaming_completed=True,
            metadata=provider_metadata,
        )

    def prewarm_speech_provider(
        self, request: VoiceProviderPrewarmRequest
    ) -> VoiceProviderPrewarmResult:
        start = time.perf_counter()
        api_key_present = bool(self.openai_config.api_key)
        ok = bool(self.openai_config.enabled and api_key_present)
        return VoiceProviderPrewarmResult(
            ok=ok,
            request_id=request.request_id,
            provider="openai",
            status="prepared" if ok else "unavailable",
            model=request.model or self.tts_model,
            voice=request.voice or self.tts_voice,
            live_format=request.live_format or self.tts_live_format,
            artifact_format=request.artifact_format or self.tts_artifact_format,
            api_key_present=api_key_present,
            client_prepared=ok,
            request_shell_prepared=ok,
            tts_called=False,
            network_called=False,
            prewarm_ms=_elapsed_ms(start),
            error_code=None if ok else "provider_unavailable",
            error_message=None
            if ok
            else "OpenAI TTS prewarm unavailable because OpenAI is disabled or missing credentials.",
            metadata={"raw_audio_present": False, "secret_redacted": True},
        )

    def _stream_failure(
        self,
        request: VoiceStreamingTTSRequest,
        *,
        error_code: str,
        error_message: str,
        first_audio_byte_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
        streaming_transport_kind: str = "unknown",
    ) -> VoiceStreamingTTSResult:
        speech_request = request.speech_request
        return VoiceStreamingTTSResult(
            ok=False,
            tts_stream_id=request.tts_stream_id,
            speech_request_id=speech_request.speech_request_id,
            provider="openai",
            model=speech_request.model or self.tts_model,
            voice=speech_request.voice or self.tts_voice,
            live_format=request.live_format or self.tts_live_format,
            artifact_format=request.artifact_format or self.tts_artifact_format,
            status="failed",
            first_audio_byte_ms=first_audio_byte_ms,
            streaming_transport_kind=streaming_transport_kind,
            first_chunk_before_complete=False,
            stream_start_monotonic_ms=0,
            stream_complete_monotonic_ms=first_audio_byte_ms,
            stream_complete_ms=first_audio_byte_ms,
            bytes_total_summary_only=0,
            streaming_started=True,
            streaming_completed=False,
            error_code=error_code,
            error_message=error_message,
            metadata=dict(metadata or {}),
        )


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _sanitize_openai_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {
        "response_keys": sorted(str(key) for key in payload.keys()),
    }
    for key in ("language", "duration", "duration_ms", "segments"):
        value = payload.get(key)
        if key == "segments" and isinstance(value, list):
            safe["segment_count"] = len(value)
            continue
        if value is not None and key != "segments":
            safe[key] = value
    return safe


def _speech_payload_to_bytes_and_metadata(
    payload: bytes | dict[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    if isinstance(payload, bytes):
        return payload, {"response_kind": "bytes"}
    if isinstance(payload, dict):
        audio = payload.get("audio") or payload.get("content") or b""
        if isinstance(audio, str):
            audio_bytes = audio.encode("utf-8")
        elif isinstance(audio, bytes):
            audio_bytes = audio
        else:
            audio_bytes = b""
        return audio_bytes, {
            "response_kind": "dict",
            "response_keys": sorted(str(key) for key in payload.keys()),
        }
    return b"", {"response_kind": type(payload).__name__}
