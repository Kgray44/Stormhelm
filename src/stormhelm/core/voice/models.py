from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from stormhelm.core.voice.availability import VoiceAvailability
from stormhelm.core.voice.bridge import VoiceCoreRequest
from stormhelm.core.voice.bridge import VoiceCoreResult
from stormhelm.core.voice.speech_renderer import SpokenResponseRequest
from stormhelm.core.voice.speech_renderer import SpokenResponseResult
from stormhelm.core.voice.state import VoiceState
from stormhelm.core.voice.state import VoiceStateSnapshot
from stormhelm.shared.time import utc_now_iso


_MIME_BY_EXTENSION: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


@dataclass(slots=True, frozen=True)
class VoiceAudioInput:
    source: str
    filename: str
    mime_type: str
    size_bytes: int
    input_id: str = field(default_factory=lambda: f"voice-audio-{uuid4().hex[:12]}")
    duration_ms: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)
    privacy_posture: str = "transient"
    transient: bool = True
    file_path: str | None = field(default=None, repr=False, compare=False)
    data: bytes | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        filename: str = "voice-input.wav",
        mime_type: str | None = None,
        duration_ms: int | None = None,
        sample_rate: int | None = None,
        channels: int | None = None,
        metadata: dict[str, Any] | None = None,
        source: str = "bytes",
    ) -> "VoiceAudioInput":
        resolved_filename = (
            str(filename or "voice-input.wav").strip() or "voice-input.wav"
        )
        payload = bytes(data or b"")
        return cls(
            source=source,
            filename=Path(resolved_filename).name,
            mime_type=_resolve_mime_type(resolved_filename, mime_type),
            duration_ms=duration_ms,
            size_bytes=len(payload),
            sample_rate=sample_rate,
            channels=channels,
            metadata=dict(metadata or {}),
            data=payload,
        )

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        mime_type: str | None = None,
        duration_ms: int | None = None,
        sample_rate: int | None = None,
        channels: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "VoiceAudioInput":
        resolved = Path(path)
        size = (
            resolved.stat().st_size if resolved.exists() and resolved.is_file() else 0
        )
        return cls(
            source="file",
            filename=resolved.name,
            mime_type=_resolve_mime_type(resolved.name, mime_type),
            duration_ms=duration_ms,
            size_bytes=size,
            sample_rate=sample_rate,
            channels=channels,
            metadata=dict(metadata or {}),
            file_path=str(resolved),
        )

    def read_bytes(self) -> bytes:
        if self.data is not None:
            return bytes(self.data)
        if self.file_path:
            return Path(self.file_path).read_bytes()
        return b""

    def to_metadata(self) -> dict[str, Any]:
        return {
            "input_id": self.input_id,
            "source": self.source,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "duration_ms": self.duration_ms,
            "size_bytes": self.size_bytes,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "privacy_posture": self.privacy_posture,
            "transient": self.transient,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_metadata()


@dataclass(slots=True, frozen=True)
class VoiceTranscriptionResult:
    ok: bool
    input_id: str
    provider: str
    model: str
    transcript: str
    transcription_id: str = field(
        default_factory=lambda: f"voice-transcription-{uuid4().hex[:12]}"
    )
    language: str | None = None
    confidence: float | None = None
    duration_ms: int | None = None
    provider_latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw_provider_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    source: str = "openai_stt"
    usable_for_core_turn: bool = True
    transcription_uncertain: bool = False
    status: str = "completed"
    audio_input_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceSpeechRequest:
    source: str
    text: str
    persona_mode: str
    speech_length_hint: str
    provider: str
    model: str
    voice: str
    format: str
    speech_request_id: str = field(
        default_factory=lambda: f"voice-speech-{uuid4().hex[:12]}"
    )
    text_hash: str = ""
    result_state_source: str | None = None
    core_result_id: str | None = None
    turn_id: str | None = None
    session_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)
    allowed_to_synthesize: bool = False
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        normalized_text = " ".join(str(self.text or "").split()).strip()
        object.__setattr__(self, "text", normalized_text)
        if not self.text_hash:
            object.__setattr__(
                self,
                "text_hash",
                sha256(normalized_text.encode("utf-8")).hexdigest()[:16],
            )
        object.__setattr__(
            self, "format", str(self.format or "mp3").strip().lower() or "mp3"
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "speech_request_id": self.speech_request_id,
            "source": self.source,
            "text_preview": _preview_text(self.text),
            "text_hash": self.text_hash,
            "persona_mode": self.persona_mode,
            "speech_length_hint": self.speech_length_hint,
            "result_state_source": self.result_state_source,
            "core_result_id": self.core_result_id,
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "voice": self.voice,
            "format": self.format,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
            "allowed_to_synthesize": self.allowed_to_synthesize,
            "blocked_reason": self.blocked_reason,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.to_metadata()
        data["text"] = self.text
        return data


@dataclass(slots=True, frozen=True)
class VoiceAudioOutput:
    source: str
    format: str
    mime_type: str
    size_bytes: int
    output_id: str = field(
        default_factory=lambda: f"voice-audio-output-{uuid4().hex[:12]}"
    )
    file_path: str | None = None
    bytes_ref: str | None = None
    transient: bool = True
    created_at: str = field(default_factory=utc_now_iso)
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    data: bytes | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        format: str,
        source: str = "tts",
        metadata: dict[str, Any] | None = None,
    ) -> "VoiceAudioOutput":
        payload = bytes(data or b"")
        normalized_format = str(format or "mp3").strip().lower() or "mp3"
        output_id = f"voice-audio-output-{uuid4().hex[:12]}"
        return cls(
            source=source,
            format=normalized_format,
            mime_type=_audio_output_mime_type(normalized_format),
            size_bytes=len(payload),
            output_id=output_id,
            bytes_ref=f"memory:{output_id}",
            transient=True,
            metadata=dict(metadata or {}),
            data=payload,
        )

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        format: str,
        source: str = "tts",
        metadata: dict[str, Any] | None = None,
    ) -> "VoiceAudioOutput":
        resolved = Path(path)
        size = (
            resolved.stat().st_size if resolved.exists() and resolved.is_file() else 0
        )
        normalized_format = (
            str(format or resolved.suffix.lstrip(".") or "mp3").strip().lower() or "mp3"
        )
        return cls(
            source=source,
            format=normalized_format,
            mime_type=_audio_output_mime_type(normalized_format),
            size_bytes=size,
            file_path=str(resolved),
            transient=False,
            metadata=dict(metadata or {}),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "output_id": self.output_id,
            "source": self.source,
            "format": self.format,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "file_path": self.file_path,
            "bytes_ref": self.bytes_ref,
            "transient": self.transient,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "metadata": dict(self.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_metadata()


@dataclass(slots=True, frozen=True)
class VoiceSpeechSynthesisResult:
    ok: bool
    speech_request_id: str | None
    provider: str
    model: str
    voice: str
    format: str
    status: str
    synthesis_id: str = field(
        default_factory=lambda: f"voice-synthesis-{uuid4().hex[:12]}"
    )
    speech_request: VoiceSpeechRequest | None = None
    audio_output: VoiceAudioOutput | None = None
    output_size_bytes: int | None = None
    duration_ms: int | None = None
    provider_latency_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    raw_provider_metadata: dict[str, Any] = field(default_factory=dict)
    playable: bool = False
    persisted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "synthesis_id": self.synthesis_id,
            "speech_request_id": self.speech_request_id,
            "speech_request": self.speech_request.to_metadata()
            if self.speech_request is not None
            else None,
            "provider": self.provider,
            "model": self.model,
            "voice": self.voice,
            "format": self.format,
            "status": self.status,
            "audio_output": self.audio_output.to_metadata()
            if self.audio_output is not None
            else None,
            "output_size_bytes": self.output_size_bytes,
            "duration_ms": self.duration_ms,
            "provider_latency_ms": self.provider_latency_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "raw_provider_metadata": dict(self.raw_provider_metadata),
            "playable": self.playable,
            "persisted": self.persisted,
        }


@dataclass(slots=True, frozen=True)
class VoicePlaybackRequest:
    audio_output_id: str | None
    source: str
    audio_ref: str | None
    file_path: str | None
    format: str
    mime_type: str
    size_bytes: int
    provider: str
    device: str
    volume: float
    playback_request_id: str = field(
        default_factory=lambda: f"voice-playback-request-{uuid4().hex[:12]}"
    )
    synthesis_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    duration_ms: int | None = None
    created_at: str = field(default_factory=utc_now_iso)
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    allowed_to_play: bool = False
    blocked_reason: str | None = None
    data: bytes | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source", str(self.source or "tts_output").strip() or "tts_output"
        )
        object.__setattr__(self, "format", str(self.format or "").strip().lower())
        object.__setattr__(
            self, "provider", str(self.provider or "local").strip().lower() or "local"
        )
        object.__setattr__(
            self, "device", str(self.device or "default").strip() or "default"
        )
        try:
            volume = float(self.volume)
        except (TypeError, ValueError):
            volume = 1.0
        object.__setattr__(self, "volume", min(1.0, max(0.0, volume)))

    def to_metadata(self) -> dict[str, Any]:
        return {
            "playback_request_id": self.playback_request_id,
            "synthesis_id": self.synthesis_id,
            "audio_output_id": self.audio_output_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "source": self.source,
            "audio_ref": self.audio_ref,
            "file_path": self.file_path,
            "format": self.format,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "duration_ms": self.duration_ms,
            "provider": self.provider,
            "device": self.device,
            "volume": self.volume,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "metadata": dict(self.metadata),
            "allowed_to_play": self.allowed_to_play,
            "blocked_reason": self.blocked_reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_metadata()


@dataclass(slots=True, frozen=True)
class VoicePlaybackResult:
    ok: bool
    playback_request_id: str | None
    audio_output_id: str | None
    provider: str
    device: str
    status: str
    playback_id: str = field(
        default_factory=lambda: f"voice-playback-{uuid4().hex[:12]}"
    )
    synthesis_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    stopped_at: str | None = None
    elapsed_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    output_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    played_locally: bool = False
    user_heard_claimed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "playback_id": self.playback_id,
            "playback_request_id": self.playback_request_id,
            "audio_output_id": self.audio_output_id,
            "synthesis_id": self.synthesis_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "provider": self.provider,
            "device": self.device,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "stopped_at": self.stopped_at,
            "elapsed_ms": self.elapsed_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "output_metadata": dict(self.output_metadata),
            "created_at": self.created_at,
            "played_locally": self.played_locally,
            "user_heard_claimed": False,
        }


class VoiceInterruptionIntent(str, Enum):
    NONE = "none"
    STOP_OUTPUT_ONLY = "stop_output_only"
    STOP_PLAYBACK = "stop_playback"
    STOP_SPEAKING = "stop_speaking"
    SUPPRESS_CURRENT_RESPONSE = "suppress_current_response"
    MUTE_SPOKEN_OUTPUT = "mute_spoken_output"
    UNMUTE_SPOKEN_OUTPUT = "unmute_spoken_output"
    MUTE_SPOKEN_RESPONSES = "mute_spoken_responses"
    UNMUTE_SPOKEN_RESPONSES = "unmute_spoken_responses"
    CANCEL_CAPTURE = "cancel_capture"
    CANCEL_LISTEN_WINDOW = "cancel_listen_window"
    REJECT_PENDING_CONFIRMATION = "reject_pending_confirmation"
    CANCEL_PENDING_CONFIRMATION = "cancel_pending_confirmation"
    CANCEL_PENDING_PROMPT = "cancel_pending_prompt"
    CORE_ROUTED_CANCEL_REQUEST = "core_routed_cancel_request"
    CORRECTION = "correction"
    NEW_REQUEST = "new_request"
    HOLD = "hold"
    WAIT = "wait"
    PAUSE = "pause"
    REPEAT_PROMPT = "repeat_prompt"
    SHOW_PLAN = "show_plan"
    UNCLEAR = "unclear"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


def _normalize_interruption_intent(
    intent: VoiceInterruptionIntent | str | None,
) -> VoiceInterruptionIntent:
    if isinstance(intent, VoiceInterruptionIntent):
        return intent
    normalized = str(intent or "unknown").strip().lower()
    for value in VoiceInterruptionIntent:
        if normalized == value.value:
            return value
    return VoiceInterruptionIntent.UNKNOWN


@dataclass(slots=True, frozen=True)
class VoiceInterruptionRequest:
    intent: VoiceInterruptionIntent | str = VoiceInterruptionIntent.UNKNOWN
    source: str = "api"
    interruption_id: str = field(
        default_factory=lambda: f"voice-interruption-{uuid4().hex[:12]}"
    )
    transcript: str = ""
    normalized_phrase: str = ""
    session_id: str | None = None
    turn_id: str | None = None
    playback_id: str | None = None
    capture_id: str | None = None
    listen_window_id: str | None = None
    realtime_session_id: str | None = None
    pending_confirmation_id: str | None = None
    active_loop_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    reason: str = "user_requested"
    muted_scope: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    allowed_to_interrupt: bool = False
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent", _normalize_interruption_intent(self.intent))
        transcript = " ".join(str(self.transcript or "").split()).strip()
        object.__setattr__(self, "transcript", transcript)
        normalized = self.normalized_phrase or transcript
        object.__setattr__(
            self,
            "normalized_phrase",
            " ".join(str(normalized or "").lower().split()).strip(),
        )
        object.__setattr__(
            self, "source", str(self.source or "api").strip().lower() or "api"
        )
        object.__setattr__(
            self,
            "reason",
            str(self.reason or "user_requested").strip() or "user_requested",
        )
        if self.muted_scope is not None:
            object.__setattr__(
                self,
                "muted_scope",
                str(self.muted_scope or "session").strip().lower() or "session",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interruption_id": self.interruption_id,
            "interruption_request_id": self.interruption_id,
            "transcript_preview": _preview_text(self.transcript),
            "normalized_phrase": self.normalized_phrase,
            "intent": self.intent.value,
            "source": self.source,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "playback_id": self.playback_id,
            "capture_id": self.capture_id,
            "listen_window_id": self.listen_window_id,
            "realtime_session_id": self.realtime_session_id,
            "pending_confirmation_id": self.pending_confirmation_id,
            "active_loop_id": self.active_loop_id,
            "created_at": self.created_at,
            "reason": self.reason,
            "muted_scope": self.muted_scope,
            "metadata": dict(self.metadata),
            "allowed_to_interrupt": self.allowed_to_interrupt,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(slots=True, frozen=True)
class VoiceInterruptionClassification:
    transcript: str
    normalized_phrase: str
    intent: VoiceInterruptionIntent | str
    confidence: float = 0.0
    source: str = "manual_voice"
    session_id: str | None = None
    turn_id: str | None = None
    listen_window_id: str | None = None
    capture_id: str | None = None
    realtime_session_id: str | None = None
    playback_id: str | None = None
    pending_confirmation_id: str | None = None
    active_loop_id: str | None = None
    classification_id: str = field(
        default_factory=lambda: f"voice-interrupt-class-{uuid4().hex[:12]}"
    )
    created_at: str = field(default_factory=utc_now_iso)
    matched_phrase_family: str | None = None
    context_used: dict[str, Any] = field(default_factory=dict)
    ambiguity_reason: str | None = None
    unsafe_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent", _normalize_interruption_intent(self.intent))
        object.__setattr__(self, "transcript", " ".join(str(self.transcript or "").split()).strip())
        object.__setattr__(
            self,
            "normalized_phrase",
            " ".join(str(self.normalized_phrase or self.transcript or "").lower().split()).strip(),
        )
        object.__setattr__(
            self,
            "source",
            str(self.source or "manual_voice").strip().lower() or "manual_voice",
        )
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        object.__setattr__(self, "confidence", min(1.0, max(0.0, confidence)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification_id": self.classification_id,
            "transcript_preview": _preview_text(self.transcript),
            "normalized_phrase": self.normalized_phrase,
            "intent": self.intent.value,
            "confidence": self.confidence,
            "source": self.source,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "listen_window_id": self.listen_window_id,
            "capture_id": self.capture_id,
            "realtime_session_id": self.realtime_session_id,
            "playback_id": self.playback_id,
            "pending_confirmation_id": self.pending_confirmation_id,
            "active_loop_id": self.active_loop_id,
            "created_at": self.created_at,
            "matched_phrase_family": self.matched_phrase_family,
            "context_used": dict(self.context_used),
            "ambiguity_reason": self.ambiguity_reason,
            "unsafe_reason": self.unsafe_reason,
        }


@dataclass(slots=True, frozen=True)
class VoiceInterruptionResult:
    interruption_id: str
    intent: VoiceInterruptionIntent | str
    status: str
    ok: bool = False
    interruption_result_id: str = field(
        default_factory=lambda: f"voice-interrupt-result-{uuid4().hex[:12]}"
    )
    classification_id: str | None = None
    playback_result: VoicePlaybackResult | None = None
    capture_result: "VoiceCaptureResult | None" = None
    affected_playback_id: str | None = None
    affected_capture_id: str | None = None
    affected_listen_window_id: str | None = None
    affected_realtime_session_id: str | None = None
    affected_confirmation_id: str | None = None
    core_request_id: str | None = None
    core_task_cancelled: bool = False
    core_result_mutated: bool = False
    action_executed: bool = False
    spoken_output_suppressed: bool | None = None
    muted_scope: str | None = None
    muted: bool | None = None
    output_stopped: bool = False
    capture_cancelled: bool = False
    listen_window_cancelled: bool = False
    realtime_session_cancelled: bool = False
    confirmation_rejected: bool = False
    routed_as_new_request: bool = False
    routed_as_correction: bool = False
    reason: str = ""
    user_message: str = ""
    spoken_response_candidate: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent", _normalize_interruption_intent(self.intent))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "interruption_id": self.interruption_id,
            "interruption_request_id": self.interruption_id,
            "interruption_result_id": self.interruption_result_id,
            "classification_id": self.classification_id,
            "intent": self.intent.value,
            "status": self.status,
            "playback_result": self.playback_result.to_dict()
            if self.playback_result is not None
            else None,
            "capture_result": self.capture_result.to_dict()
            if self.capture_result is not None
            else None,
            "affected_playback_id": self.affected_playback_id,
            "affected_capture_id": self.affected_capture_id,
            "affected_listen_window_id": self.affected_listen_window_id,
            "affected_realtime_session_id": self.affected_realtime_session_id,
            "affected_confirmation_id": self.affected_confirmation_id,
            "core_request_id": self.core_request_id,
            "core_task_cancelled": self.core_task_cancelled,
            "core_result_mutated": self.core_result_mutated,
            "action_executed": self.action_executed,
            "spoken_output_suppressed": self.spoken_output_suppressed,
            "muted_scope": self.muted_scope,
            "muted": self.muted,
            "output_stopped": self.output_stopped,
            "capture_cancelled": self.capture_cancelled,
            "listen_window_cancelled": self.listen_window_cancelled,
            "realtime_session_cancelled": self.realtime_session_cancelled,
            "confirmation_rejected": self.confirmation_rejected,
            "routed_as_new_request": self.routed_as_new_request,
            "routed_as_correction": self.routed_as_correction,
            "reason": self.reason,
            "user_message": self.user_message,
            "spoken_response_candidate": self.spoken_response_candidate,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


class VoiceSpokenConfirmationIntentKind(str, Enum):
    NONE = "none"
    CONFIRM = "confirm"
    REJECT = "reject"
    CANCEL_PENDING_CONFIRMATION = "cancel_pending_confirmation"
    SHOW_PLAN = "show_plan"
    REPEAT_PROMPT = "repeat_prompt"
    EXPLAIN_RISK = "explain_risk"
    CLARIFY = "clarify"
    WAIT = "wait"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    NOT_CONFIRMATION = "not_confirmation"


class VoiceConfirmationStrength(str, Enum):
    NONE = "none"
    WEAK_ACK = "weak_ack"
    NORMAL_CONFIRM = "normal_confirm"
    EXPLICIT_CONFIRM = "explicit_confirm"
    DESTRUCTIVE_CONFIRM = "destructive_confirm"


def _normalize_confirmation_intent(
    intent: VoiceSpokenConfirmationIntentKind | str | None,
) -> VoiceSpokenConfirmationIntentKind:
    if isinstance(intent, VoiceSpokenConfirmationIntentKind):
        return intent
    normalized = str(intent or "unknown").strip().lower()
    for value in VoiceSpokenConfirmationIntentKind:
        if normalized == value.value:
            return value
    return VoiceSpokenConfirmationIntentKind.UNKNOWN


def _normalize_confirmation_strength(
    strength: VoiceConfirmationStrength | str | None,
) -> VoiceConfirmationStrength:
    if isinstance(strength, VoiceConfirmationStrength):
        return strength
    normalized = str(strength or "none").strip().lower()
    for value in VoiceConfirmationStrength:
        if normalized == value.value:
            return value
    return VoiceConfirmationStrength.NONE


@dataclass(slots=True, frozen=True)
class VoiceSpokenConfirmationIntent:
    transcript: str
    normalized_phrase: str
    intent: VoiceSpokenConfirmationIntentKind | str
    confidence: float = 0.0
    source: str = "manual_voice"
    session_id: str | None = None
    turn_id: str | None = None
    spoken_confirmation_intent_id: str = field(
        default_factory=lambda: f"voice-confirm-intent-{uuid4().hex[:12]}"
    )
    created_at: str = field(default_factory=utc_now_iso)
    matched_phrase_family: str | None = None
    provided_strength: VoiceConfirmationStrength | str = VoiceConfirmationStrength.NONE
    requires_pending_confirmation: bool = True
    allowed_without_pending_confirmation: bool = False
    ambiguity_reason: str | None = None
    unsafe_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent", _normalize_confirmation_intent(self.intent))
        object.__setattr__(
            self,
            "provided_strength",
            _normalize_confirmation_strength(self.provided_strength),
        )
        object.__setattr__(self, "transcript", " ".join(str(self.transcript or "").split()).strip())
        object.__setattr__(
            self,
            "normalized_phrase",
            " ".join(str(self.normalized_phrase or "").lower().split()).strip(),
        )
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        object.__setattr__(self, "confidence", min(1.0, max(0.0, confidence)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "spoken_confirmation_intent_id": self.spoken_confirmation_intent_id,
            "transcript_preview": _preview_text(self.transcript),
            "normalized_phrase": self.normalized_phrase,
            "intent": self.intent.value,
            "confidence": self.confidence,
            "source": self.source,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "created_at": self.created_at,
            "matched_phrase_family": self.matched_phrase_family,
            "provided_strength": self.provided_strength.value,
            "requires_pending_confirmation": self.requires_pending_confirmation,
            "allowed_without_pending_confirmation": self.allowed_without_pending_confirmation,
            "ambiguity_reason": self.ambiguity_reason,
            "unsafe_reason": self.unsafe_reason,
        }


@dataclass(slots=True, frozen=True)
class VoiceConfirmationBinding:
    pending_confirmation_id: str | None = None
    approval_request_id: str | None = None
    task_id: str | None = None
    action_id: str | None = None
    route_family: str | None = None
    subsystem: str | None = None
    target_summary: str = ""
    payload_hash: str | None = None
    recipient_id: str | None = None
    risk_level: str = "unknown"
    required_confirmation_strength: VoiceConfirmationStrength | str = (
        VoiceConfirmationStrength.NORMAL_CONFIRM
    )
    provided_confirmation_strength: VoiceConfirmationStrength | str = (
        VoiceConfirmationStrength.NONE
    )
    source_turn_id: str | None = None
    current_turn_id: str | None = None
    session_id: str | None = None
    binding_id: str = field(
        default_factory=lambda: f"voice-confirm-binding-{uuid4().hex[:12]}"
    )
    created_at: str = field(default_factory=utc_now_iso)
    expires_at: str | None = None
    consumed_at: str | None = None
    stale: bool = False
    valid: bool = False
    invalid_reason: str | None = None
    same_task: bool = True
    same_action: bool = True
    same_payload: bool = True
    same_route_family: bool = True
    same_session: bool = True
    restart_boundary_valid: bool = True
    confidence: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_confirmation_strength",
            _normalize_confirmation_strength(self.required_confirmation_strength),
        )
        object.__setattr__(
            self,
            "provided_confirmation_strength",
            _normalize_confirmation_strength(self.provided_confirmation_strength),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "pending_confirmation_id": self.pending_confirmation_id,
            "approval_request_id": self.approval_request_id,
            "task_id": self.task_id,
            "action_id": self.action_id,
            "route_family": self.route_family,
            "subsystem": self.subsystem,
            "target_summary": _preview_text(self.target_summary),
            "payload_hash": self.payload_hash,
            "recipient_id": self.recipient_id,
            "risk_level": self.risk_level,
            "required_confirmation_strength": self.required_confirmation_strength.value,
            "provided_confirmation_strength": self.provided_confirmation_strength.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
            "stale": self.stale,
            "valid": self.valid,
            "invalid_reason": self.invalid_reason,
            "source_turn_id": self.source_turn_id,
            "current_turn_id": self.current_turn_id,
            "same_task": self.same_task,
            "same_action": self.same_action,
            "same_payload": self.same_payload,
            "same_route_family": self.same_route_family,
            "same_session": self.same_session,
            "restart_boundary_valid": self.restart_boundary_valid,
            "confidence": self.confidence,
        }


@dataclass(slots=True, frozen=True)
class VoiceSpokenConfirmationRequest:
    transcript: str
    session_id: str = "default"
    request_id: str = field(
        default_factory=lambda: f"voice-confirm-request-{uuid4().hex[:12]}"
    )
    normalized_phrase: str = ""
    turn_id: str | None = None
    source: str = "manual_voice"
    pending_confirmation_id: str | None = None
    task_id: str | None = None
    route_family: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        transcript = " ".join(str(self.transcript or "").split()).strip()
        object.__setattr__(self, "transcript", transcript)
        normalized = self.normalized_phrase or transcript
        object.__setattr__(
            self,
            "normalized_phrase",
            " ".join(str(normalized or "").lower().split()).strip(),
        )
        object.__setattr__(
            self,
            "session_id",
            str(self.session_id or "default").strip() or "default",
        )
        object.__setattr__(
            self,
            "source",
            str(self.source or "manual_voice").strip().lower() or "manual_voice",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "transcript_preview": _preview_text(self.transcript),
            "normalized_phrase": self.normalized_phrase,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "source": self.source,
            "pending_confirmation_id": self.pending_confirmation_id,
            "task_id": self.task_id,
            "route_family": self.route_family,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True, frozen=True)
class VoiceSpokenConfirmationResult:
    request_id: str
    intent: VoiceSpokenConfirmationIntentKind | str
    status: str
    ok: bool = False
    result_id: str = field(
        default_factory=lambda: f"voice-confirm-result-{uuid4().hex[:12]}"
    )
    binding: VoiceConfirmationBinding | None = None
    pending_confirmation_id: str | None = None
    consumed_confirmation: bool = False
    core_task_cancelled: bool = False
    core_result_mutated: bool = False
    action_executed: bool = False
    route_family: str | None = None
    subsystem: str | None = None
    reason: str = ""
    user_message: str = ""
    spoken_response_candidate: str | None = None
    error_code: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "intent", _normalize_confirmation_intent(self.intent))
        object.__setattr__(self, "core_task_cancelled", False)
        object.__setattr__(self, "core_result_mutated", False)

    @property
    def binding_id(self) -> str | None:
        return self.binding.binding_id if self.binding is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "result_id": self.result_id,
            "request_id": self.request_id,
            "intent": self.intent.value,
            "status": self.status,
            "binding": self.binding.to_dict() if self.binding is not None else None,
            "binding_id": self.binding_id,
            "pending_confirmation_id": self.pending_confirmation_id,
            "consumed_confirmation": self.consumed_confirmation,
            "core_task_cancelled": self.core_task_cancelled,
            "core_result_mutated": self.core_result_mutated,
            "action_executed": self.action_executed,
            "route_family": self.route_family,
            "subsystem": self.subsystem,
            "reason": self.reason,
            "user_message": self.user_message,
            "spoken_response_candidate": self.spoken_response_candidate,
            "error_code": self.error_code,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True, frozen=True)
class VoiceCaptureRequest:
    source: str
    provider: str
    device: str
    sample_rate: int
    channels: int
    format: str
    max_duration_ms: int
    max_audio_bytes: int
    persist_audio: bool
    capture_request_id: str = field(
        default_factory=lambda: f"voice-capture-request-{uuid4().hex[:12]}"
    )
    session_id: str | None = None
    turn_id: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    allowed_to_capture: bool = False
    blocked_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source",
            str(self.source or "push_to_talk").strip().lower() or "push_to_talk",
        )
        object.__setattr__(
            self, "provider", str(self.provider or "local").strip().lower() or "local"
        )
        object.__setattr__(
            self, "device", str(self.device or "default").strip() or "default"
        )
        object.__setattr__(
            self, "format", str(self.format or "wav").strip().lower() or "wav"
        )
        object.__setattr__(self, "sample_rate", max(1, int(self.sample_rate or 16000)))
        object.__setattr__(self, "channels", max(1, int(self.channels or 1)))
        object.__setattr__(
            self,
            "max_duration_ms",
            int(self.max_duration_ms if self.max_duration_ms is not None else 30000),
        )
        object.__setattr__(
            self,
            "max_audio_bytes",
            int(self.max_audio_bytes if self.max_audio_bytes is not None else 10000000),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "capture_request_id": self.capture_request_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "source": self.source,
            "provider": self.provider,
            "device": self.device,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "format": self.format,
            "max_duration_ms": self.max_duration_ms,
            "max_audio_bytes": self.max_audio_bytes,
            "persist_audio": self.persist_audio,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "metadata": dict(self.metadata),
            "allowed_to_capture": self.allowed_to_capture,
            "blocked_reason": self.blocked_reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_metadata()


@dataclass(slots=True, frozen=True)
class VoiceCaptureSession:
    capture_request_id: str
    provider: str
    device: str
    status: str
    capture_id: str = field(default_factory=lambda: f"voice-capture-{uuid4().hex[:12]}")
    session_id: str | None = None
    turn_id: str | None = None
    started_at: str | None = field(default_factory=utc_now_iso)
    max_duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    microphone_was_active: bool = False
    always_listening_claimed: bool = False
    wake_word_claimed: bool = False

    @property
    def ok(self) -> bool:
        return self.status in {"started", "recording"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "capture_id": self.capture_id,
            "capture_request_id": self.capture_request_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "provider": self.provider,
            "device": self.device,
            "status": self.status,
            "started_at": self.started_at,
            "max_duration_ms": self.max_duration_ms,
            "metadata": dict(self.metadata),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "microphone_was_active": self.microphone_was_active,
            "always_listening_claimed": False,
            "wake_word_claimed": False,
        }


@dataclass(slots=True, frozen=True)
class VoiceCaptureResult:
    ok: bool
    capture_request_id: str | None
    capture_id: str | None
    status: str
    provider: str
    device: str
    audio_input: VoiceAudioInput | None = None
    duration_ms: int | None = None
    size_bytes: int | None = None
    stopped_at: str | None = None
    stop_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_audio_persisted: bool = False
    microphone_was_active: bool = False
    always_listening_claimed: bool = False
    wake_word_claimed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "capture_request_id": self.capture_request_id,
            "capture_id": self.capture_id,
            "status": self.status,
            "provider": self.provider,
            "device": self.device,
            "audio_input": self.audio_input.to_metadata()
            if self.audio_input is not None
            else None,
            "duration_ms": self.duration_ms,
            "size_bytes": self.size_bytes,
            "stopped_at": self.stopped_at,
            "stop_reason": self.stop_reason,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": dict(self.metadata),
            "raw_audio_persisted": self.raw_audio_persisted,
            "microphone_was_active": self.microphone_was_active,
            "always_listening_claimed": False,
            "wake_word_claimed": False,
        }


@dataclass(slots=True, frozen=True)
class VoiceTurn:
    transcript: str
    session_id: str
    interaction_mode: str = "ghost"
    turn_id: str = field(default_factory=lambda: f"voice-turn-{uuid4().hex[:12]}")
    source: str = "manual_voice"
    normalized_transcript: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    availability_snapshot: dict[str, Any] = field(default_factory=dict)
    voice_state_before: dict[str, Any] = field(default_factory=dict)
    voice_state_after: dict[str, Any] = field(default_factory=dict)
    screen_context_permission: str = "not_requested"
    confirmation_intent: str | None = None
    interrupt_intent: str | None = None
    transcript_confidence: float | None = None
    transcription_provider: str | None = None
    transcription_model: str | None = None
    transcription_uncertain: bool = False
    transcription_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    core_bridge_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceTurnResult:
    ok: bool
    turn: VoiceTurn | None = None
    core_request: VoiceCoreRequest | None = None
    core_result: VoiceCoreResult | None = None
    transcription_result: VoiceTranscriptionResult | None = None
    spoken_response: SpokenResponseResult | None = None
    voice_state_before: dict[str, Any] | None = None
    voice_state_after: dict[str, Any] | None = None
    state_transitions: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    provider_network_call_count: int = 0
    no_real_audio: bool = True
    stt_invoked: bool = False
    tts_invoked: bool = False
    realtime_invoked: bool = False
    audio_playback_started: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


@dataclass(slots=True, frozen=True)
class VoiceCaptureTurnResult:
    capture_result: VoiceCaptureResult | None = None
    voice_turn_result: VoiceTurnResult | None = None
    synthesis_result: VoiceSpeechSynthesisResult | None = None
    playback_result: VoicePlaybackResult | None = None
    final_status: str = "not_started"
    error_code: str | None = None
    stopped_stage: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "capture_result": self.capture_result.to_dict()
            if self.capture_result is not None
            else None,
            "voice_turn_result": self.voice_turn_result.to_dict()
            if self.voice_turn_result is not None
            else None,
            "synthesis_result": self.synthesis_result.to_dict()
            if self.synthesis_result is not None
            else None,
            "playback_result": self.playback_result.to_dict()
            if self.playback_result is not None
            else None,
            "final_status": self.final_status,
            "error_code": self.error_code,
            "stopped_stage": self.stopped_stage,
        }


@dataclass(slots=True, frozen=True)
class VoiceWakeSupervisedLoopResult:
    loop_id: str
    session_id: str
    ok: bool
    final_status: str
    wake_event_id: str | None = None
    wake_session_id: str | None = None
    wake_ghost_request_id: str | None = None
    listen_window_id: str | None = None
    capture_id: str | None = None
    audio_input_id: str | None = None
    transcription_id: str | None = None
    voice_turn_id: str | None = None
    core_request_id: str | None = None
    speech_request_id: str | None = None
    synthesis_id: str | None = None
    playback_id: str | None = None
    wake_status: str | None = None
    ghost_status: str | None = None
    listen_status: str = "skipped"
    capture_status: str = "skipped"
    vad_status: str | None = None
    transcription_status: str = "skipped"
    core_result_state: str | None = None
    spoken_response_status: str = "skipped"
    synthesis_status: str = "skipped"
    playback_status: str = "skipped"
    failed_stage: str | None = None
    stopped_stage: str | None = None
    blocked_stage: str | None = None
    cancelled_stage: str | None = None
    last_successful_stage: str | None = None
    current_blocker: str | None = None
    route_family: str | None = None
    subsystem: str | None = None
    trust_posture: str | None = None
    verification_posture: str | None = None
    transcript_preview: str = ""
    spoken_preview: str = ""
    truth_flags: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    stage_results: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        truth_flags = {
            "wake_local": True,
            "openai_wake_detection": False,
            "cloud_wake_detection": False,
            "continuous_listening": False,
            "realtime_used": False,
            "command_authority": "stormhelm_core",
            "user_heard_claimed": False,
            "core_task_cancelled_by_voice": False,
            "core_result_mutated_by_voice": False,
            "vad_command_authority": False,
            "vad_semantic_completion_claimed": False,
            "post_wake_listen_is_bounded": True,
            "listen_window_does_not_route_core": True,
        }
        truth_flags.update(dict(self.truth_flags or {}))
        object.__setattr__(self, "truth_flags", truth_flags)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoicePostWakeListenWindow:
    wake_event_id: str
    wake_session_id: str
    wake_ghost_request_id: str | None
    session_id: str
    listen_window_id: str = field(
        default_factory=lambda: f"voice-listen-window-{uuid4().hex[:12]}"
    )
    status: str = "active"
    started_at: str = field(default_factory=utc_now_iso)
    expires_at: str | None = None
    listen_window_ms: int = 8000
    max_utterance_ms: int = 30_000
    capture_id: str | None = None
    audio_input_id: str | None = None
    vad_session_id: str | None = None
    voice_turn_id: str | None = None
    stop_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    capture_started: bool = False
    stt_started: bool = False
    core_routed: bool = False
    command_authority_granted: bool = False
    continuous_listening: bool = False
    realtime_used: bool = False
    raw_audio_present: bool = False
    openai_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "session_id",
            str(self.session_id or "default").strip() or "default",
        )
        object.__setattr__(
            self,
            "status",
            str(self.status or "active").strip().lower() or "active",
        )
        object.__setattr__(
            self,
            "listen_window_ms",
            max(1, int(self.listen_window_ms or 8000)),
        )
        object.__setattr__(
            self,
            "max_utterance_ms",
            max(1, int(self.max_utterance_ms or 30_000)),
        )
        object.__setattr__(self, "command_authority_granted", False)
        object.__setattr__(self, "continuous_listening", False)
        object.__setattr__(self, "realtime_used", False)
        object.__setattr__(self, "raw_audio_present", False)
        object.__setattr__(self, "openai_used", False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceWakeEvent:
    provider: str
    provider_kind: str
    wake_phrase: str
    confidence: float
    session_id: str | None = None
    backend: str | None = None
    device: str | None = None
    wake_event_id: str = field(
        default_factory=lambda: f"voice-wake-event-{uuid4().hex[:12]}"
    )
    timestamp: str = field(default_factory=utc_now_iso)
    accepted: bool = False
    rejected_reason: str | None = None
    cooldown_active: bool = False
    false_positive_candidate: bool = False
    source: str = "mock"
    raw_audio_present: bool = False
    openai_used: bool = False
    cloud_used: bool = False
    status: str = "detected"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider",
            str(self.provider or "mock").strip().lower() or "mock",
        )
        object.__setattr__(
            self,
            "provider_kind",
            str(self.provider_kind or self.provider).strip().lower() or self.provider,
        )
        object.__setattr__(
            self,
            "wake_phrase",
            str(self.wake_phrase or "Stormhelm").strip() or "Stormhelm",
        )
        object.__setattr__(
            self,
            "backend",
            str(self.backend).strip().lower() if self.backend is not None else None,
        )
        object.__setattr__(
            self,
            "device",
            str(self.device).strip() if self.device is not None else None,
        )
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        object.__setattr__(self, "confidence", min(1.0, max(0.0, confidence)))
        object.__setattr__(self, "raw_audio_present", False)
        object.__setattr__(self, "openai_used", False)
        object.__setattr__(self, "cloud_used", False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceWakeSession:
    wake_event_id: str
    session_id: str
    source: str
    confidence: float
    wake_session_id: str = field(
        default_factory=lambda: f"voice-wake-session-{uuid4().hex[:12]}"
    )
    started_at: str = field(default_factory=utc_now_iso)
    expires_at: str | None = None
    status: str = "active"
    mode_after_wake: str = "ghost"
    capture_started: bool = False
    core_routed: bool = False
    created_ghost_request: bool = False
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "session_id",
            str(self.session_id or "default").strip() or "default",
        )
        object.__setattr__(
            self,
            "source",
            str(self.source or "mock").strip().lower() or "mock",
        )
        object.__setattr__(
            self,
            "mode_after_wake",
            str(self.mode_after_wake or "ghost").strip().lower() or "ghost",
        )
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        object.__setattr__(self, "confidence", min(1.0, max(0.0, confidence)))
        object.__setattr__(self, "capture_started", False)
        object.__setattr__(self, "core_routed", False)
        object.__setattr__(self, "created_ghost_request", False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceWakeGhostRequest:
    wake_event_id: str
    wake_session_id: str
    session_id: str
    wake_phrase: str
    confidence: float
    wake_ghost_request_id: str = field(
        default_factory=lambda: f"voice-wake-ghost-{uuid4().hex[:12]}"
    )
    source: str = "wake"
    requested_mode: str = "ghost"
    status: str = "requested"
    created_at: str = field(default_factory=utc_now_iso)
    expires_at: str | None = None
    reason: str | None = None
    wake_status_label: str = "Bearing acquired."
    wake_prompt_text: str = "Ghost ready."
    capture_started: bool = False
    stt_started: bool = False
    core_routed: bool = False
    voice_turn_created: bool = False
    command_authority_granted: bool = False
    openai_used: bool = False
    raw_audio_present: bool = False
    no_post_wake_capture: bool = True
    no_vad: bool = True
    no_realtime: bool = True
    no_command_from_wake: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "session_id",
            str(self.session_id or "default").strip() or "default",
        )
        object.__setattr__(
            self,
            "source",
            str(self.source or "wake").strip().lower() or "wake",
        )
        object.__setattr__(
            self,
            "requested_mode",
            str(self.requested_mode or "ghost").strip().lower() or "ghost",
        )
        object.__setattr__(
            self,
            "status",
            str(self.status or "requested").strip().lower() or "requested",
        )
        object.__setattr__(
            self,
            "wake_phrase",
            str(self.wake_phrase or "Stormhelm").strip() or "Stormhelm",
        )
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        object.__setattr__(self, "confidence", min(1.0, max(0.0, confidence)))
        object.__setattr__(self, "capture_started", False)
        object.__setattr__(self, "stt_started", False)
        object.__setattr__(self, "core_routed", False)
        object.__setattr__(self, "voice_turn_created", False)
        object.__setattr__(self, "command_authority_granted", False)
        object.__setattr__(self, "openai_used", False)
        object.__setattr__(self, "raw_audio_present", False)
        object.__setattr__(self, "no_post_wake_capture", True)
        object.__setattr__(self, "no_vad", True)
        object.__setattr__(self, "no_realtime", True)
        object.__setattr__(self, "no_command_from_wake", True)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceWakeReadiness:
    wake_enabled: bool
    wake_provider: str
    wake_provider_kind: str
    wake_available: bool
    wake_monitoring_active: bool
    wake_phrase_configured: bool
    wake_phrase: str
    confidence_threshold: float
    cooldown_ms: int
    last_wake_event_id: str | None = None
    last_wake_status: str | None = None
    last_wake_confidence: float | None = None
    wake_backend: str | None = None
    dependency_available: bool | None = None
    platform_supported: bool | None = None
    device: str | None = None
    device_available: bool | None = None
    permission_state: str | None = None
    permission_error: str | None = None
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    no_cloud_wake_audio: bool = True
    openai_wake_detection: bool = False
    cloud_wake_detection: bool = False
    command_routing_from_wake: bool = False
    always_listening: bool = False
    realtime_wake_detection: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceActivityEvent:
    provider: str
    provider_kind: str
    status: str
    activity_event_id: str = field(
        default_factory=lambda: f"voice-activity-{uuid4().hex[:12]}"
    )
    capture_id: str | None = None
    listen_window_id: str | None = None
    vad_session_id: str | None = None
    session_id: str | None = None
    confidence: float | None = None
    timestamp: str = field(default_factory=utc_now_iso)
    silence_ms: int | None = None
    duration_ms: int | None = None
    semantic_completion_claimed: bool = False
    command_intent_claimed: bool = False
    core_routed: bool = False
    raw_audio_present: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider",
            str(self.provider or "mock").strip().lower() or "mock",
        )
        object.__setattr__(
            self,
            "provider_kind",
            str(self.provider_kind or self.provider).strip().lower() or self.provider,
        )
        object.__setattr__(
            self,
            "status",
            str(self.status or "speech_started").strip().lower() or "speech_started",
        )
        if self.confidence is not None:
            try:
                confidence = float(self.confidence)
            except (TypeError, ValueError):
                confidence = 0.0
            object.__setattr__(self, "confidence", min(1.0, max(0.0, confidence)))
        object.__setattr__(self, "semantic_completion_claimed", False)
        object.__setattr__(self, "command_intent_claimed", False)
        object.__setattr__(self, "core_routed", False)
        object.__setattr__(self, "raw_audio_present", False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceVADSession:
    provider: str
    provider_kind: str
    session_id: str | None = None
    capture_id: str | None = None
    listen_window_id: str | None = None
    vad_session_id: str = field(
        default_factory=lambda: f"voice-vad-session-{uuid4().hex[:12]}"
    )
    started_at: str = field(default_factory=utc_now_iso)
    stopped_at: str | None = None
    status: str = "active"
    speech_started_at: str | None = None
    speech_stopped_at: str | None = None
    last_activity_event_id: str | None = None
    finalized_capture: bool = False
    finalization_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider",
            str(self.provider or "mock").strip().lower() or "mock",
        )
        object.__setattr__(
            self,
            "provider_kind",
            str(self.provider_kind or self.provider).strip().lower() or self.provider,
        )
        object.__setattr__(
            self,
            "status",
            str(self.status or "active").strip().lower() or "active",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceVADReadiness:
    vad_enabled: bool
    vad_provider: str
    vad_provider_kind: str
    vad_available: bool
    vad_active: bool
    active_capture_id: str | None = None
    active_listen_window_id: str | None = None
    silence_ms: int = 900
    speech_start_threshold: float = 0.5
    speech_stop_threshold: float = 0.35
    max_utterance_ms: int = 30000
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    semantic_completion_claimed: bool = False
    realtime_vad: bool = False
    command_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceRealtimeReadiness:
    realtime_enabled: bool
    realtime_provider: str
    realtime_provider_kind: str
    realtime_available: bool
    realtime_mode: str
    model: str
    voice: str
    turn_detection: str
    semantic_vad_enabled: bool
    session_active: bool = False
    active_session_id: str | None = None
    direct_tools_allowed: bool = False
    core_bridge_required: bool = True
    speech_to_speech_enabled: bool = False
    audio_output_from_realtime: bool = False
    core_bridge_tool_enabled: bool = False
    direct_action_tools_exposed: bool = False
    require_core_for_commands: bool = True
    allow_smalltalk_without_core: bool = False
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    openai_configured: bool = False
    api_key_present: bool = False
    provider_configured: bool = True
    no_cloud_wake_detection: bool = True
    wake_detection_local_only: bool = True
    command_authority: str = "stormhelm_core"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceRealtimeSession:
    provider: str
    provider_kind: str
    mode: str
    model: str
    voice: str
    session_id: str
    source: str = "test"
    realtime_session_id: str = field(
        default_factory=lambda: f"voice-realtime-session-{uuid4().hex[:12]}"
    )
    started_at: str = field(default_factory=utc_now_iso)
    expires_at: str | None = None
    closed_at: str | None = None
    status: str = "created"
    turn_detection_mode: str = "server_vad"
    semantic_vad_enabled: bool = False
    direct_tools_allowed: bool = False
    core_bridge_required: bool = True
    speech_to_speech_enabled: bool = False
    audio_output_enabled: bool = False
    audio_output_from_realtime: bool = False
    core_bridge_tool_enabled: bool = False
    direct_action_tools_exposed: bool = False
    listen_window_id: str | None = None
    capture_id: str | None = None
    active_turn_id: str | None = None
    last_core_bridge_call_id: str | None = None
    last_core_result_state: str | None = None
    last_spoken_summary_source: str = "none"
    last_event_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider",
            str(self.provider or "unavailable").strip().lower() or "unavailable",
        )
        object.__setattr__(
            self,
            "provider_kind",
            str(self.provider_kind or self.provider).strip().lower() or self.provider,
        )
        object.__setattr__(
            self,
            "mode",
            str(self.mode or "transcription_bridge").strip().lower()
            or "transcription_bridge",
        )
        object.__setattr__(
            self, "model", str(self.model or "gpt-realtime").strip() or "gpt-realtime"
        )
        object.__setattr__(
            self,
            "voice",
            str(self.voice or "stormhelm_default").strip() or "stormhelm_default",
        )
        object.__setattr__(
            self,
            "session_id",
            str(self.session_id or "default").strip() or "default",
        )
        object.__setattr__(
            self,
            "source",
            str(self.source or "test").strip().lower() or "test",
        )
        object.__setattr__(
            self,
            "status",
            str(self.status or "created").strip().lower() or "created",
        )
        object.__setattr__(
            self,
            "turn_detection_mode",
            str(self.turn_detection_mode or "server_vad").strip().lower()
            or "server_vad",
        )
        object.__setattr__(self, "direct_tools_allowed", False)
        object.__setattr__(self, "core_bridge_required", True)
        speech_enabled = (
            self.mode == "speech_to_speech_core_bridge"
            and bool(self.speech_to_speech_enabled)
        )
        audio_from_realtime = speech_enabled and bool(
            self.audio_output_from_realtime or self.audio_output_enabled
        )
        object.__setattr__(self, "speech_to_speech_enabled", speech_enabled)
        object.__setattr__(self, "audio_output_from_realtime", audio_from_realtime)
        object.__setattr__(self, "audio_output_enabled", audio_from_realtime)
        object.__setattr__(self, "core_bridge_tool_enabled", speech_enabled)
        object.__setattr__(self, "direct_action_tools_exposed", False)
        object.__setattr__(
            self,
            "last_spoken_summary_source",
            str(self.last_spoken_summary_source or "none").strip().lower()
            or "none",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceRealtimeTranscriptEvent:
    realtime_session_id: str
    realtime_turn_id: str
    session_id: str
    source: str
    transcript_text: str
    is_partial: bool
    is_final: bool
    realtime_event_id: str = field(
        default_factory=lambda: f"voice-realtime-event-{uuid4().hex[:12]}"
    )
    listen_window_id: str | None = None
    capture_id: str | None = None
    confidence: float | None = None
    sequence_index: int = 0
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    raw_audio_present: bool = False
    command_authority: bool = False
    core_routed: bool = False

    def __post_init__(self) -> None:
        text = " ".join(str(self.transcript_text or "").split()).strip()
        object.__setattr__(self, "transcript_text", text)
        object.__setattr__(
            self,
            "source",
            str(self.source or "mock_realtime").strip().lower() or "mock_realtime",
        )
        object.__setattr__(
            self,
            "session_id",
            str(self.session_id or "default").strip() or "default",
        )
        if self.confidence is not None:
            try:
                confidence = float(self.confidence)
            except (TypeError, ValueError):
                confidence = 0.0
            object.__setattr__(self, "confidence", min(1.0, max(0.0, confidence)))
        object.__setattr__(self, "raw_audio_present", False)
        object.__setattr__(self, "command_authority", False)

    @property
    def transcript_preview(self) -> str:
        return _preview_text(self.transcript_text)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["transcript_preview"] = self.transcript_preview
        data.pop("transcript_text", None)
        return data


@dataclass(slots=True, frozen=True)
class VoiceRealtimeTurnResult:
    realtime_turn_id: str
    realtime_session_id: str
    final_transcript: str
    source: str = "mock_realtime"
    voice_turn_id: str | None = None
    core_request_id: str | None = None
    core_result_state: str | None = None
    route_family: str | None = None
    subsystem: str | None = None
    trust_posture: str | None = None
    verification_posture: str | None = None
    spoken_response_status: str | None = None
    synthesis_status: str | None = None
    playback_status: str | None = None
    final_status: str = "not_started"
    failed_stage: str | None = None
    stopped_stage: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None
    action_executed: bool = False
    core_task_cancelled_by_realtime: bool = False
    core_result_mutated_by_realtime: bool = False
    direct_tools_allowed: bool = False
    core_bridge_required: bool = True
    speech_to_speech_enabled: bool = False
    audio_output_from_realtime: bool = False
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "final_transcript", " ".join(str(self.final_transcript or "").split()).strip()
        )
        object.__setattr__(
            self,
            "source",
            str(self.source or "mock_realtime").strip().lower() or "mock_realtime",
        )
        object.__setattr__(self, "action_executed", False)
        object.__setattr__(self, "core_task_cancelled_by_realtime", False)
        object.__setattr__(self, "core_result_mutated_by_realtime", False)
        object.__setattr__(self, "direct_tools_allowed", False)
        object.__setattr__(self, "core_bridge_required", True)
        object.__setattr__(self, "speech_to_speech_enabled", False)
        object.__setattr__(self, "audio_output_from_realtime", False)

    @property
    def final_transcript_preview(self) -> str:
        return _preview_text(self.final_transcript)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["final_transcript_preview"] = self.final_transcript_preview
        data.pop("final_transcript", None)
        return data


@dataclass(slots=True, frozen=True)
class VoiceRealtimeCoreBridgeCall:
    transcript: str
    session_id: str
    realtime_session_id: str | None = None
    realtime_turn_id: str | None = None
    core_bridge_call_id: str = field(
        default_factory=lambda: f"voice-realtime-core-{uuid4().hex[:12]}"
    )
    core_bridge_tool_name: str = "stormhelm_core_request"
    status: str = "started"
    voice_turn_id: str | None = None
    core_request_id: str | None = None
    result_state: str | None = None
    route_family: str | None = None
    subsystem: str | None = None
    trust_posture: str | None = None
    verification_posture: str | None = None
    task_id: str | None = None
    approval_required: bool = False
    confirmation_prompt: str | None = None
    spoken_summary: str = ""
    visual_summary: str = ""
    speak_allowed: bool = True
    continue_listening: bool = False
    followup_binding: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    provenance_summary: dict[str, Any] = field(default_factory=dict)
    direct_tools_allowed: bool = False
    core_bridge_required: bool = True
    direct_action_tools_exposed: bool = False
    action_executed: bool = False
    core_task_cancelled_by_realtime: bool = False
    core_result_mutated_by_realtime: bool = False
    raw_audio_present: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "transcript", " ".join(str(self.transcript or "").split()).strip()
        )
        object.__setattr__(
            self, "session_id", str(self.session_id or "default").strip() or "default"
        )
        object.__setattr__(
            self,
            "status",
            str(self.status or "started").strip().lower() or "started",
        )
        object.__setattr__(self, "core_bridge_tool_name", "stormhelm_core_request")
        object.__setattr__(self, "direct_tools_allowed", False)
        object.__setattr__(self, "core_bridge_required", True)
        object.__setattr__(self, "direct_action_tools_exposed", False)
        object.__setattr__(self, "action_executed", False)
        object.__setattr__(self, "core_task_cancelled_by_realtime", False)
        object.__setattr__(self, "core_result_mutated_by_realtime", False)
        object.__setattr__(self, "raw_audio_present", False)

    @property
    def transcript_preview(self) -> str:
        return _preview_text(self.transcript)

    @property
    def spoken_preview(self) -> str:
        return _preview_text(self.spoken_summary)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["transcript_preview"] = self.transcript_preview
        data["spoken_preview"] = self.spoken_preview
        data.pop("transcript", None)
        return data


@dataclass(slots=True, frozen=True)
class VoiceRealtimeResponseGate:
    core_bridge_call_id: str
    realtime_session_id: str | None = None
    realtime_turn_id: str | None = None
    response_gate_id: str = field(
        default_factory=lambda: f"voice-realtime-gate-{uuid4().hex[:12]}"
    )
    result_state: str | None = None
    status: str = "blocked"
    speak_allowed: bool = False
    spoken_text: str = ""
    spoken_summary_source: str = "blocked"
    reason: str | None = None
    route_family: str | None = None
    subsystem: str | None = None
    trust_posture: str | None = None
    verification_posture: str | None = None
    direct_tools_allowed: bool = False
    core_bridge_required: bool = True
    direct_action_tools_exposed: bool = False
    action_executed: bool = False
    core_task_cancelled_by_realtime: bool = False
    core_result_mutated_by_realtime: bool = False
    raw_audio_present: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            str(self.status or "blocked").strip().lower() or "blocked",
        )
        object.__setattr__(
            self,
            "spoken_summary_source",
            str(self.spoken_summary_source or "blocked").strip().lower()
            or "blocked",
        )
        object.__setattr__(self, "direct_tools_allowed", False)
        object.__setattr__(self, "core_bridge_required", True)
        object.__setattr__(self, "direct_action_tools_exposed", False)
        object.__setattr__(self, "action_executed", False)
        object.__setattr__(self, "core_task_cancelled_by_realtime", False)
        object.__setattr__(self, "core_result_mutated_by_realtime", False)
        object.__setattr__(self, "raw_audio_present", False)

    @property
    def spoken_preview(self) -> str:
        return _preview_text(self.spoken_text)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["spoken_preview"] = self.spoken_preview
        data.pop("spoken_text", None)
        return data


@dataclass(slots=True, frozen=True)
class VoicePipelineStageSummary:
    stage: str = "idle"
    listen_window_status: str | None = None
    listen_window_id: str | None = None
    capture_status: str | None = None
    transcription_status: str | None = None
    core_result_state: str | None = None
    synthesis_status: str | None = None
    playback_status: str | None = None
    current_blocker: str | None = None
    last_successful_stage: str | None = None
    failed_stage: str | None = None
    transcript_preview: str = ""
    spoken_preview: str = ""
    route_family: str | None = None
    subsystem: str | None = None
    trust_posture: str | None = None
    verification_posture: str | None = None
    final_status: str | None = None
    output_stopped: bool = False
    output_suppressed: bool = False
    playback_stopped: bool = False
    muted: bool = False
    no_active_playback: bool = False
    timestamps: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceRuntimeModeReadiness:
    selected_mode: str
    effective_mode: str
    status: str
    ready: bool
    degraded: bool
    blocked: bool
    disabled: bool
    required_config_flags: list[str] = field(default_factory=list)
    required_providers: list[str] = field(default_factory=list)
    required_subcomponents: list[str] = field(default_factory=list)
    forbidden_subcomponents: list[str] = field(default_factory=list)
    expected_subsystem_posture: dict[str, str] = field(default_factory=dict)
    missing_requirements: list[str] = field(default_factory=list)
    contradictory_settings: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    user_facing_summary: str = ""
    next_fix: str | None = None
    provider_availability: dict[str, Any] = field(default_factory=dict)
    live_playback_available: bool = False
    artifact_persistence_enabled: bool = False
    artifact_persistence_counts_as_live_playback: bool = False
    core_bridge_available: bool = False
    trust_confirmation_available: bool = False
    truth_flags: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceReadinessReport:
    overall_status: str
    voice_enabled: bool
    openai_enabled: bool
    api_key_present: bool
    credential_status: str
    provider: str
    provider_available: bool
    provider_kind: str
    current_phase: str
    manual_transcript_ready: bool
    stt_ready: bool
    tts_ready: bool
    playback_ready: bool
    capture_ready: bool
    local_capture_ready: bool
    ghost_controls_ready: bool
    deck_surface_ready: bool
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_setup_action: str | None = None
    user_facing_reason: str = ""
    runtime_mode: dict[str, Any] = field(default_factory=dict)
    truth_flags: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "SpokenResponseRequest",
    "SpokenResponseResult",
    "VoiceActivityEvent",
    "VoiceAudioInput",
    "VoiceAudioOutput",
    "VoiceAvailability",
    "VoiceCoreRequest",
    "VoiceCoreResult",
    "VoiceCaptureRequest",
    "VoiceCaptureResult",
    "VoiceCaptureSession",
    "VoiceCaptureTurnResult",
    "VoiceConfirmationBinding",
    "VoiceConfirmationStrength",
    "VoiceWakeSupervisedLoopResult",
    "VoicePostWakeListenWindow",
    "VoiceInterruptionIntent",
    "VoiceInterruptionRequest",
    "VoiceInterruptionResult",
    "VoicePlaybackRequest",
    "VoicePlaybackResult",
    "VoicePipelineStageSummary",
    "VoiceReadinessReport",
    "VoiceRuntimeModeReadiness",
    "VoiceRealtimeReadiness",
    "VoiceRealtimeCoreBridgeCall",
    "VoiceRealtimeResponseGate",
    "VoiceRealtimeSession",
    "VoiceRealtimeTranscriptEvent",
    "VoiceRealtimeTurnResult",
    "VoiceSpeechRequest",
    "VoiceSpeechSynthesisResult",
    "VoiceSpokenConfirmationIntent",
    "VoiceSpokenConfirmationIntentKind",
    "VoiceSpokenConfirmationRequest",
    "VoiceSpokenConfirmationResult",
    "VoiceState",
    "VoiceStateSnapshot",
    "VoiceTranscriptionResult",
    "VoiceTurn",
    "VoiceTurnResult",
    "VoiceVADReadiness",
    "VoiceVADSession",
    "VoiceWakeEvent",
    "VoiceWakeGhostRequest",
    "VoiceWakeReadiness",
    "VoiceWakeSession",
]


def _resolve_mime_type(filename: str, explicit: str | None) -> str:
    normalized = str(explicit or "").strip().lower()
    if normalized:
        return normalized
    suffix = Path(str(filename or "")).suffix.lower()
    return _MIME_BY_EXTENSION.get(suffix, "application/octet-stream")


def _audio_output_mime_type(format_name: str) -> str:
    normalized = str(format_name or "").strip().lower()
    if normalized == "wav":
        return "audio/wav"
    if normalized == "opus":
        return "audio/ogg"
    if normalized == "aac":
        return "audio/aac"
    if normalized == "flac":
        return "audio/flac"
    if normalized == "pcm":
        return "audio/pcm"
    return "audio/mpeg"


def _preview_text(text: str, *, limit: int = 96) -> str:
    compact = " ".join(str(text or "").split()).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
