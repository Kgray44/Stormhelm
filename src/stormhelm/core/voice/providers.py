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
from stormhelm.core.voice.availability import VoiceAvailability
from stormhelm.core.voice.availability import compute_voice_availability
from stormhelm.core.voice.models import VoiceAudioInput
from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.models import VoiceCaptureRequest
from stormhelm.core.voice.models import VoiceCaptureResult
from stormhelm.core.voice.models import VoiceCaptureSession
from stormhelm.core.voice.models import VoicePlaybackRequest
from stormhelm.core.voice.models import VoicePlaybackResult
from stormhelm.core.voice.models import VoiceSpeechRequest
from stormhelm.core.voice.models import VoiceSpeechSynthesisResult
from stormhelm.core.voice.models import VoiceTranscriptionResult
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

    def close_session(self, session_id: str | None = None) -> VoiceProviderOperationResult: ...

    def submit_text_turn(self, text: str, *, session_id: str | None = None) -> VoiceProviderOperationResult: ...


@runtime_checkable
class SpeechToTextProvider(Protocol):
    def transcribe_audio(
        self,
        audio: VoiceAudioInput | bytes | None = None,
        *,
        content_type: str | None = None,
    ) -> VoiceProviderOperationResult | VoiceTranscriptionResult | Awaitable[VoiceTranscriptionResult]: ...


@runtime_checkable
class TextToSpeechProvider(Protocol):
    def synthesize_speech(
        self,
        text: str | VoiceSpeechRequest,
    ) -> VoiceProviderOperationResult | VoiceSpeechSynthesisResult | Awaitable[VoiceSpeechSynthesisResult]: ...


@runtime_checkable
class RealtimeVoiceProvider(Protocol):
    def start_listening(self) -> VoiceProviderOperationResult: ...

    def stop_listening(self) -> VoiceProviderOperationResult: ...


@runtime_checkable
class WakeWordProvider(Protocol):
    def start_wake_detection(self) -> VoiceProviderOperationResult: ...

    def stop_wake_detection(self) -> VoiceProviderOperationResult: ...


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
    ) -> VoiceCaptureSession | VoiceCaptureResult | Awaitable[VoiceCaptureSession | VoiceCaptureResult]: ...

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

    def start(self, request: VoiceCaptureRequest, output_path: Path) -> dict[str, Any]: ...

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
    _active_capture: VoiceCaptureSession | None = field(default=None, init=False, repr=False)

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

    def start_capture(self, request: VoiceCaptureRequest) -> VoiceCaptureSession | VoiceCaptureResult:
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
                error_message=self.error_message or "Mock capture provider failed to start.",
            )
        session = VoiceCaptureSession(
            capture_request_id=request.capture_request_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            provider=self.provider_name,
            device=request.device,
            status="recording",
            max_duration_ms=request.max_duration_ms,
            metadata={"source": request.source, "mock": True, "request": request.to_metadata()},
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
        if len(payload) > int(active.metadata.get("request", {}).get("max_audio_bytes", 0) or 0):
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
            sample_rate=int(active.metadata.get("request", {}).get("sample_rate", 16000) or 16000),
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
            return {**base, "available": False, "unavailable_reason": "unsupported_platform"}
        try:
            import sounddevice as sd  # type: ignore[import-not-found]
        except Exception:
            return {**base, "available": False, "unavailable_reason": "dependency_missing"}

        base["dependency_available"] = True
        try:
            device = None if str(config.capture.device or "default").strip().lower() == "default" else config.capture.device
            sd.query_devices(device=device, kind="input")
        except Exception as error:
            return {
                **base,
                "available": False,
                "unavailable_reason": "device_unavailable",
                "device_available": False,
                "provider_error": str(error),
            }
        return {**base, "available": True, "unavailable_reason": None, "device_available": True}

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
        elapsed_ms = int((time.perf_counter() - float(handle.get("started_at", time.perf_counter()))) * 1000)
        return {
            "output_path": str(output_path),
            "duration_ms": elapsed_ms,
            "size_bytes": output_path.stat().st_size if output_path.exists() else int(handle.get("bytes_written", 0)),
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
    _active_capture: VoiceCaptureSession | None = field(default=None, init=False, repr=False)
    _active_handle: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _active_request: VoiceCaptureRequest | None = field(default=None, init=False, repr=False)
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
            return {**base, "available": False, "unavailable_reason": "capture_disabled"}
        if not self.config.capture.allow_dev_capture:
            return {**base, "available": False, "unavailable_reason": "dev_capture_not_allowed"}
        if self.backend is None:
            return {**base, "available": False, "unavailable_reason": "provider_not_configured"}
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
            "unavailable_reason": None if available else str(reason or "provider_unavailable"),
            "mock": False,
            "permission_error": self._permission_error or backend_availability.get("permission_error"),
        }

    def start_capture(self, request: VoiceCaptureRequest) -> VoiceCaptureSession | VoiceCaptureResult:
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
            reason = str(availability.get("unavailable_reason") or "provider_unavailable")
            status = "blocked" if reason in {"capture_disabled", "dev_capture_not_allowed"} else "unavailable"
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
            handle = self.backend.start(request, output_path) if self.backend is not None else {}
        except PermissionError as error:
            self._permission_error = str(error)
            return self._result(
                request,
                status="unavailable",
                ok=False,
                error_code="permission_denied",
                error_message="Local capture permission was denied.",
                metadata={"availability": {**availability, "permission_error": str(error)}},
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
            "permission_state": handle.get("permission_state", availability.get("permission_state", "unknown")),
            "device_available": handle.get("device_available", availability.get("device_available")),
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
            payload = self.backend.stop(handle, reason=reason) if self.backend is not None else {}
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
        timed_out = bool(payload.get("timed_out")) or self._timed_out_capture_id == active.capture_id
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
        max_audio_bytes = request.max_audio_bytes if request is not None else self.config.capture.max_audio_bytes
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
            mime_type=self._mime_type_for_format(request.format if request is not None else self.config.capture.format),
            duration_ms=duration_ms,
            sample_rate=request.sample_rate if request is not None else self.config.capture.sample_rate,
            channels=request.channels if request is not None else self.config.capture.channels,
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

    def _no_active_result(self, capture_id: str | None, *, reason: str) -> VoiceCaptureResult:
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
        base = Path(self.temp_dir) if self.temp_dir is not None else Path(tempfile.gettempdir()) / "stormhelm-voice-capture"
        base.mkdir(parents=True, exist_ok=True)
        extension = str(request.format or "wav").strip().lower() or "wav"
        return base / f"{uuid4().hex}.{extension}"

    def _start_timeout_timer(self, capture_id: str, request: VoiceCaptureRequest) -> None:
        self._cancel_timeout_timer()
        if not self.config.capture.auto_stop_on_max_duration or request.max_duration_ms <= 0:
            return
        timer = threading.Timer(request.max_duration_ms / 1000.0, self._mark_capture_timeout, args=(capture_id,))
        timer.daemon = True
        self._timeout_timer = timer
        timer.start()

    def _cancel_timeout_timer(self) -> None:
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
        self._timeout_timer = None

    def _mark_capture_timeout(self, capture_id: str) -> None:
        if self._active_capture is None or self._active_capture.capture_id != capture_id:
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

    def _file_metadata(self, path: str | Path | None, *, size_bytes: int | None = None) -> dict[str, Any]:
        if not path:
            return {"file_path": None, "size_bytes": size_bytes}
        resolved = Path(path)
        resolved_size = size_bytes if size_bytes is not None else (resolved.stat().st_size if resolved.exists() and resolved.is_file() else None)
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

    def play(self, request: VoicePlaybackRequest) -> VoicePlaybackResult | Awaitable[VoicePlaybackResult]: ...

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
    _active_playback: VoicePlaybackResult | None = field(default=None, init=False, repr=False)

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
        return self._mock_result(payload={"session_id": f"mock-voice-{uuid4().hex[:8]}"})

    def close_session(self, session_id: str | None = None) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"session_id": session_id})

    def submit_text_turn(self, text: str, *, session_id: str | None = None) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"session_id": session_id, "transcript": text})

    def transcribe_audio(
        self,
        audio: VoiceAudioInput | bytes | None = None,
        *,
        content_type: str | None = None,
    ) -> VoiceProviderOperationResult | VoiceTranscriptionResult:
        if not isinstance(audio, VoiceAudioInput):
            del audio, content_type
            return self._mock_result(payload={"transcript": "", "confidence": None, "audio_processed": False})

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

    def synthesize_speech(self, text: str | VoiceSpeechRequest) -> VoiceProviderOperationResult | VoiceSpeechSynthesisResult:
        if not isinstance(text, VoiceSpeechRequest):
            return self._mock_result(payload={"text": text, "audio_playback_started": False})

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
        return self._mock_result(payload={"wake_detection_started": False, "audio_sent_to_cloud": False})

    def stop_wake_detection(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"wake_detection_stopped": True})

    def start_audio_input(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_input_started": False})

    def stop_audio_input(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_input_stopped": True})

    def start_audio_output(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_output_started": False})

    def stop_audio_output(self) -> VoiceProviderOperationResult:
        return self._mock_result(payload={"audio_output_stopped": True})

    def _mock_result(self, *, payload: dict[str, Any] | None = None) -> VoiceProviderOperationResult:
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
        return self._not_implemented("OpenAI Realtime sessions are not implemented in Voice-0.")

    def close_session(self, session_id: str | None = None) -> VoiceProviderOperationResult:
        del session_id
        return self._not_implemented("OpenAI voice sessions are not implemented in Voice-0.")

    def submit_text_turn(self, text: str, *, session_id: str | None = None) -> VoiceProviderOperationResult:
        del text, session_id
        return self._not_implemented("Voice text turns must cross the Core bridge in a later phase.")

    def transcribe_audio(self, audio: bytes | None = None, *, content_type: str | None = None) -> VoiceProviderOperationResult:
        del audio, content_type
        return self._not_implemented("OpenAI speech-to-text is not implemented in Voice-0.")

    def synthesize_speech(self, text: str) -> VoiceProviderOperationResult:
        del text
        return self._not_implemented("OpenAI text-to-speech is not implemented in Voice-0.")

    def start_listening(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Realtime listening is not implemented in Voice-0.")

    def stop_listening(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Realtime listening is not implemented in Voice-0.")

    def start_wake_detection(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Wake detection is not implemented in Voice-0.")

    def stop_wake_detection(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Wake detection is not implemented in Voice-0.")

    def start_audio_input(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Microphone capture is not implemented in Voice-0.")

    def stop_audio_input(self) -> VoiceProviderOperationResult:
        return self._not_implemented("Microphone capture is not implemented in Voice-0.")

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
        return str(self.config.openai.stt_model or "").strip() or "gpt-4o-mini-transcribe"

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
            return self._not_implemented("OpenAI speech-to-text requires a typed VoiceAudioInput in Voice-2.")
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

        transcript = " ".join(str(payload.get("text") or payload.get("transcript") or "").split()).strip()
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
            duration_ms = int(duration_value * 1000) if duration_value < 1000 else int(duration_value)
        confidence = payload.get("confidence")
        return VoiceTranscriptionResult(
            ok=True,
            input_id=audio.input_id,
            provider="openai",
            model=self.stt_model,
            transcript=transcript,
            language=str(payload.get("language") or "").strip() or self.config.openai.transcription_language,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
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
        timeout = float(self.config.openai.timeout_seconds or self.openai_config.timeout_seconds)
        url = f"{self.openai_config.base_url.rstrip('/')}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.openai_config.api_key}"}

        if self.post_transcription is not None:
            result = self.post_transcription(url=url, headers=headers, data=data, files=files, timeout=timeout)
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

    async def synthesize_speech(self, text: str | VoiceSpeechRequest) -> VoiceProviderOperationResult | VoiceSpeechSynthesisResult:
        if not isinstance(text, VoiceSpeechRequest):
            return self._not_implemented("OpenAI text-to-speech requires a typed VoiceSpeechRequest in Voice-3.")
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
        timeout = float(self.config.openai.timeout_seconds or self.openai_config.timeout_seconds)
        url = f"{self.openai_config.base_url.rstrip('/')}/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.openai_config.api_key}",
            "Content-Type": "application/json",
        }

        if self.post_speech is not None:
            result = self.post_speech(url=url, headers=headers, json=body, timeout=timeout)
            if hasattr(result, "__await__"):
                return await result  # type: ignore[no-any-return]
            return result

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.content

    def _build_tts_audio_output(self, request: VoiceSpeechRequest, audio_bytes: bytes) -> VoiceAudioOutput:
        if self.config.openai.persist_tts_outputs and self.config.openai.output_audio_dir:
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


def _speech_payload_to_bytes_and_metadata(payload: bytes | dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
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
