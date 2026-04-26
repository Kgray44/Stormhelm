from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
class VoicePipelineStageSummary:
    stage: str = "idle"
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
    timestamps: dict[str, Any] = field(default_factory=dict)

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
    truth_flags: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "SpokenResponseRequest",
    "SpokenResponseResult",
    "VoiceAudioInput",
    "VoiceAudioOutput",
    "VoiceAvailability",
    "VoiceCoreRequest",
    "VoiceCoreResult",
    "VoiceCaptureRequest",
    "VoiceCaptureResult",
    "VoiceCaptureSession",
    "VoiceCaptureTurnResult",
    "VoicePlaybackRequest",
    "VoicePlaybackResult",
    "VoicePipelineStageSummary",
    "VoiceReadinessReport",
    "VoiceSpeechRequest",
    "VoiceSpeechSynthesisResult",
    "VoiceState",
    "VoiceStateSnapshot",
    "VoiceTranscriptionResult",
    "VoiceTurn",
    "VoiceTurnResult",
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
