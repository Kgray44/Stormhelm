from __future__ import annotations

import sys
import tempfile
import threading
import time
import wave
from collections.abc import Awaitable
from collections.abc import Callable
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
from stormhelm.core.voice.models import VoicePlaybackRequest
from stormhelm.core.voice.models import VoicePlaybackResult
from stormhelm.core.voice.models import VoiceRealtimeSession
from stormhelm.core.voice.models import VoiceRealtimeTranscriptEvent
from stormhelm.core.voice.models import VoiceSpeechRequest
from stormhelm.core.voice.models import VoiceSpeechSynthesisResult
from stormhelm.core.voice.models import VoiceTranscriptionResult
from stormhelm.core.voice.models import VoiceVADSession
from stormhelm.core.voice.models import VoiceWakeEvent
from stormhelm.shared.time import utc_now_iso


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
            if handle["overflow"]:
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
            },
        }

    def timeout(self, handle: dict[str, Any]) -> None:
        handle["timed_out"] = True
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
            "cleanup_warning": self._last_cleanup_warning,
        }
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
                stop_reason=reason,
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
            stop_reason=reason,
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
class LocalPlaybackProvider:
    config: VoiceConfig
    provider_name: str = "local"

    @property
    def name(self) -> str:
        return self.provider_name

    @property
    def is_mock(self) -> bool:
        return False

    def get_availability(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "available": False,
            "unavailable_reason": "local_playback_not_implemented",
            "mock": False,
        }

    def play(self, request: VoicePlaybackRequest) -> VoicePlaybackResult:
        return VoicePlaybackResult(
            ok=False,
            playback_request_id=request.playback_request_id,
            audio_output_id=request.audio_output_id,
            synthesis_id=request.synthesis_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            provider=self.provider_name,
            device=request.device,
            status="unavailable",
            error_code="local_playback_not_implemented",
            error_message="Real local playback is not implemented in this Voice-4 boundary.",
            output_metadata=request.to_metadata(),
            played_locally=False,
            user_heard_claimed=False,
        )

    def stop(
        self,
        playback_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoicePlaybackResult:
        del playback_id
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

    def get_active_playback(self) -> VoicePlaybackResult | None:
        return None


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


@dataclass(slots=True)
class OpenAIVoiceProvider(OpenAIVoiceProviderStub):
    post_transcription: PostTranscription | None = None
    post_speech: PostSpeech | None = None

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
        return str(self.config.openai.tts_voice or "").strip() or "cedar"

    @property
    def tts_format(self) -> str:
        return str(self.config.openai.tts_format or "mp3").strip().lower() or "mp3"

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
