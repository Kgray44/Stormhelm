from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any

from stormhelm.core.voice.models import utc_now_iso


ENVELOPE_SOURCES = {
    "playback_output_envelope",
    "streaming_chunk_envelope",
    "precomputed_artifact_envelope",
    "synthetic_fallback_envelope",
    "unavailable",
}

ANCHOR_STATES = {
    "dormant",
    "idle",
    "wake_detected",
    "listening",
    "transcribing",
    "thinking",
    "confirmation_required",
    "preparing_speech",
    "speaking",
    "interrupted",
    "muted",
    "continuing_task",
    "blocked",
    "error",
}


@dataclass(frozen=True, slots=True)
class VoiceAudioEnvelope:
    source: str
    rms_level: float = 0.0
    peak_level: float = 0.0
    smoothed_level: float = 0.0
    speech_energy: float = 0.0
    noise_floor: float = 0.015
    is_silence: bool = True
    last_update_at: str = ""
    update_hz: int = 30
    audio_reactive_available: bool = False
    synthetic: bool = False
    raw_audio_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "rms_level": _round(self.rms_level),
            "peak_level": _round(self.peak_level),
            "smoothed_level": _round(self.smoothed_level),
            "speech_energy": _round(self.speech_energy),
            "noise_floor": _round(self.noise_floor),
            "is_silence": bool(self.is_silence),
            "last_update_at": self.last_update_at,
            "update_hz": int(self.update_hz),
            "audio_reactive_available": bool(self.audio_reactive_available),
            "synthetic": bool(self.synthetic),
            "raw_audio_present": False,
        }


def compute_voice_audio_envelope(
    audio: bytes | bytearray | memoryview | None,
    *,
    audio_format: str = "pcm",
    source: str = "streaming_chunk_envelope",
    previous: VoiceAudioEnvelope | dict[str, Any] | None = None,
    update_hz: int = 30,
    noise_floor: float = 0.015,
) -> VoiceAudioEnvelope:
    """Compute a bounded visual envelope from transient output audio bytes."""

    normalized_source = _source(source)
    payload = _audio_payload(audio, audio_format=audio_format)
    if not payload:
        return synthetic_voice_audio_envelope(
            level=0.0,
            source="unavailable",
            previous=previous,
            update_hz=update_hz,
            noise_floor=noise_floor,
        )
    samples = _pcm16_samples(payload)
    if not samples:
        return synthetic_voice_audio_envelope(
            level=0.0,
            source="unavailable",
            previous=previous,
            update_hz=update_hz,
            noise_floor=noise_floor,
        )
    peak = max(abs(sample) for sample in samples) / 32768.0
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
    energy = _compress_level(rms, noise_floor=noise_floor)
    smoothed = _smooth_level(energy, previous)
    return VoiceAudioEnvelope(
        source=normalized_source,
        rms_level=_clamp(rms),
        peak_level=_clamp(peak),
        smoothed_level=smoothed,
        speech_energy=energy,
        noise_floor=_clamp(noise_floor),
        is_silence=energy <= 0.02,
        last_update_at=utc_now_iso(),
        update_hz=max(1, min(60, int(update_hz or 30))),
        audio_reactive_available=normalized_source
        in {"playback_output_envelope", "streaming_chunk_envelope", "precomputed_artifact_envelope"},
        synthetic=False,
        raw_audio_present=False,
    )


def synthetic_voice_audio_envelope(
    *,
    level: float,
    source: str = "synthetic_fallback_envelope",
    previous: VoiceAudioEnvelope | dict[str, Any] | None = None,
    update_hz: int = 30,
    noise_floor: float = 0.015,
) -> VoiceAudioEnvelope:
    normalized = _source(source)
    value = _clamp(level)
    energy = _compress_level(value, noise_floor=0.0)
    smoothed = _smooth_level(energy, previous)
    return VoiceAudioEnvelope(
        source=normalized,
        rms_level=value,
        peak_level=value,
        smoothed_level=smoothed,
        speech_energy=energy,
        noise_floor=_clamp(noise_floor),
        is_silence=energy <= 0.02,
        last_update_at=utc_now_iso(),
        update_hz=max(1, min(60, int(update_hz or 30))),
        audio_reactive_available=False,
        synthetic=normalized == "synthetic_fallback_envelope",
        raw_audio_present=False,
    )


def build_voice_anchor_payload(voice_status: dict[str, Any] | None) -> dict[str, Any]:
    voice = _dict(voice_status)
    explicit = _dict(voice.get("voice_anchor"))
    state = _state(explicit.get("state") or _derive_anchor_state(voice))
    envelope = _select_envelope(voice, state=state)
    output_level = envelope.smoothed_level
    motion_intensity = _motion_intensity(state, output_level, envelope)
    if "motion_intensity" in explicit:
        motion_intensity = _clamp(_float(explicit.get("motion_intensity")))
    audio_source = _source(
        explicit.get("audio_reactive_source")
        or explicit.get("voice_audio_reactive_source")
        or envelope.source
    )
    audio_reactive = bool(
        explicit.get("audio_reactive_available", envelope.audio_reactive_available)
    ) and audio_source not in {"synthetic_fallback_envelope", "unavailable"}
    speaking_visual_active = bool(
        state == "speaking"
        and not _truthy(_dict(voice.get("interruption")).get("spoken_output_muted"))
    )
    if "speaking_visual_active" in explicit:
        speaking_visual_active = bool(explicit.get("speaking_visual_active"))
    if state in {"muted", "interrupted", "blocked", "error", "preparing_speech"}:
        speaking_visual_active = False
    payload = {
        "state": state,
        "state_label": str(explicit.get("state_label") or _state_label(state)),
        "speaking_visual_active": bool(speaking_visual_active),
        "motion_intensity": _round(motion_intensity),
        "audio_reactive_available": bool(audio_reactive),
        "audio_reactive_source": audio_source,
        "output_level_rms": _round(
            _float(explicit.get("output_level_rms"), envelope.rms_level)
        ),
        "output_level_peak": _round(
            _float(explicit.get("output_level_peak"), envelope.peak_level)
        ),
        "smoothed_output_level": _round(
            _float(explicit.get("smoothed_output_level"), envelope.smoothed_level)
        ),
        "speech_energy": _round(
            _float(explicit.get("speech_energy"), envelope.speech_energy)
        ),
        "first_audio_started": bool(
            explicit.get("first_audio_started")
            or _dict(voice.get("playback")).get("first_audio_started")
        ),
        "streaming_tts_active": bool(
            explicit.get("streaming_tts_active") or _streaming_tts_active(voice)
        ),
        "live_playback_active": bool(
            explicit.get("live_playback_active") or _playback_active(voice)
        ),
        "visualizer_update_hz": int(
            explicit.get("visualizer_update_hz") or envelope.update_hz or 30
        ),
        "visualizer_last_update_at": str(
            explicit.get("visualizer_last_update_at")
            or explicit.get("last_update_at")
            or envelope.last_update_at
        ),
        "synthetic_fallback": bool(
            audio_source == "synthetic_fallback_envelope"
            or explicit.get("synthetic_fallback", False)
        ),
        "user_heard_claimed": False,
        "playback_started_does_not_mean_user_heard": True,
        "speaking_visual_is_not_completion": True,
        "speaking_visual_is_not_verification": True,
    }
    return payload


def _derive_anchor_state(voice: dict[str, Any]) -> str:
    availability = _dict(voice.get("availability"))
    state = _dict(voice.get("state"))
    tts = _dict(voice.get("tts"))
    playback = _dict(voice.get("playback"))
    capture = _dict(voice.get("capture"))
    stt = _dict(voice.get("stt"))
    manual = _dict(voice.get("manual_turns"))
    wake = _dict(voice.get("wake"))
    wake_ghost = _dict(voice.get("wake_ghost") or wake.get("ghost"))
    post_wake = _dict(voice.get("post_wake_listen"))
    interruption = _dict(voice.get("interruption"))
    confirmation = _dict(voice.get("spoken_confirmation"))
    pipeline = _dict(voice.get("pipeline_summary"))
    last_error = _dict(voice.get("last_error"))
    if _text(last_error.get("code")):
        return "error"
    if not _truthy(voice.get("enabled", True)) or not _truthy(
        availability.get("available", voice.get("available", True))
    ):
        return "dormant"
    if _text(playback.get("last_playback_status")) in {"failed", "error"}:
        return "error"
    if _text(tts.get("last_synthesis_state")) in {"failed", "error"}:
        return "error"
    if _text(playback.get("last_playback_status")) in {"blocked", "unsupported", "unavailable"}:
        return "blocked"
    if _interrupted(interruption):
        return "interrupted"
    if _truthy(interruption.get("spoken_output_muted")):
        return "muted"
    if _playback_active(voice):
        return "speaking"
    if _preparing_speech(voice):
        return "preparing_speech"
    if int(confirmation.get("pending_confirmation_count") or 0) > 0:
        return "confirmation_required"
    if _text(manual.get("last_trust_posture")) in {"confirmation_required", "approval_required"}:
        return "confirmation_required"
    if _capture_active(capture, post_wake):
        return "listening"
    if _text(stt.get("last_transcription_state")) in {"started", "running", "transcribing"}:
        return "transcribing"
    if _text(pipeline.get("stage")) in {"core_routing", "thinking", "planning"}:
        return "thinking"
    if _text(state.get("state")) in {"core_routing", "thinking"}:
        return "thinking"
    if _truthy(wake_ghost.get("active")) or _text(wake_ghost.get("status")) in {
        "requested",
        "active",
        "accepted",
    }:
        return "wake_detected"
    if _text(pipeline.get("stage")) in {"continuing", "async_continuation"}:
        return "continuing_task"
    return "idle"


def _select_envelope(voice: dict[str, Any], *, state: str) -> VoiceAudioEnvelope:
    for candidate in (
        voice.get("voice_output_envelope"),
        _dict(voice.get("playback")).get("voice_output_envelope"),
        _dict(voice.get("playback")).get("last_audio_envelope"),
        _dict(voice.get("tts")).get("voice_output_envelope"),
        _dict(voice.get("tts")).get("last_audio_envelope"),
        _dict(voice.get("tts")).get("precomputed_artifact_envelope"),
        _dict(voice.get("playback")).get("precomputed_artifact_envelope"),
    ):
        envelope = _envelope_from_dict(candidate)
        if envelope is not None:
            return envelope
    if state == "speaking":
        return synthetic_voice_audio_envelope(level=0.42)
    if state == "preparing_speech":
        return synthetic_voice_audio_envelope(level=0.22)
    return synthetic_voice_audio_envelope(level=0.0, source="unavailable")


def _envelope_from_dict(value: Any) -> VoiceAudioEnvelope | None:
    payload = _dict(value)
    if not payload:
        return None
    source = _source(payload.get("source") or payload.get("audio_reactive_source"))
    return VoiceAudioEnvelope(
        source=source,
        rms_level=_clamp(_float(payload.get("rms_level"), payload.get("output_level_rms"))),
        peak_level=_clamp(_float(payload.get("peak_level"), payload.get("output_level_peak"))),
        smoothed_level=_clamp(
            _float(payload.get("smoothed_level"), payload.get("smoothed_output_level"))
        ),
        speech_energy=_clamp(_float(payload.get("speech_energy"))),
        noise_floor=_clamp(_float(payload.get("noise_floor"), 0.015)),
        is_silence=bool(payload.get("is_silence", False)),
        last_update_at=str(payload.get("last_update_at") or payload.get("visualizer_last_update_at") or utc_now_iso()),
        update_hz=max(1, min(60, int(payload.get("update_hz") or payload.get("visualizer_update_hz") or 30))),
        audio_reactive_available=bool(
            payload.get("audio_reactive_available", source not in {"synthetic_fallback_envelope", "unavailable"})
        ),
        synthetic=bool(payload.get("synthetic", source == "synthetic_fallback_envelope")),
        raw_audio_present=False,
    )


def _motion_intensity(state: str, output_level: float, envelope: VoiceAudioEnvelope) -> float:
    if state == "speaking":
        if envelope.source in {"synthetic_fallback_envelope", "unavailable"}:
            return 0.48
        return _clamp(0.42 + output_level * 0.58)
    return {
        "dormant": 0.03,
        "idle": 0.12,
        "wake_detected": 0.28,
        "listening": 0.3,
        "transcribing": 0.26,
        "thinking": 0.24,
        "confirmation_required": 0.34,
        "preparing_speech": 0.26,
        "interrupted": 0.08,
        "muted": 0.06,
        "continuing_task": 0.2,
        "blocked": 0.09,
        "error": 0.12,
    }.get(state, 0.12)


def _streaming_tts_active(voice: dict[str, Any]) -> bool:
    tts = _dict(voice.get("tts"))
    return _text(tts.get("streaming_tts_status")) in {"started", "streaming", "running", "pending"}


def _preparing_speech(voice: dict[str, Any]) -> bool:
    playback = _dict(voice.get("playback"))
    return bool(
        _streaming_tts_active(voice)
        or playback.get("first_audio_pending")
        or _text(_dict(voice.get("tts")).get("last_synthesis_state")) in {"started", "running", "pending"}
    ) and not bool(playback.get("first_audio_started"))


def _playback_active(voice: dict[str, Any]) -> bool:
    playback = _dict(voice.get("playback"))
    active_status = _text(
        playback.get("active_playback_status")
        or playback.get("live_playback_status")
        or playback.get("stream_status")
    )
    return bool(
        playback.get("playback_streaming_active")
        or active_status in {"started", "playing"}
        or (
            playback.get("first_audio_started")
            and active_status not in {"completed", "cancelled", "failed", "stopped"}
            and bool(playback.get("active_playback_id") or playback.get("active_playback_stream_id"))
        )
    )


def _capture_active(capture: dict[str, Any], post_wake: dict[str, Any]) -> bool:
    return _text(capture.get("active_capture_status")) in {
        "started",
        "recording",
        "active",
        "capturing",
    } or _text(post_wake.get("active_listen_window_status")) in {"active", "listening"}


def _interrupted(interruption: dict[str, Any]) -> bool:
    status = _text(interruption.get("last_interruption_status"))
    intent = _text(interruption.get("last_interruption_intent"))
    return bool(
        status in {"completed", "stopped", "playback_stopped"}
        and (
            interruption.get("output_interrupted")
            or interruption.get("playback_stopped")
            or "stop" in intent
        )
    )


def _state(value: Any) -> str:
    text = _text(value)
    return text if text in ANCHOR_STATES else "idle"


def _state_label(state: str) -> str:
    return state.replace("_", " ").title()


def _audio_payload(audio: bytes | bytearray | memoryview | None, *, audio_format: str) -> bytes:
    payload = bytes(audio or b"")
    if not payload:
        return b""
    if _text(audio_format) == "wav" and payload[:4] == b"RIFF" and len(payload) > 44:
        return payload[44:]
    return payload


def _pcm16_samples(payload: bytes) -> list[int]:
    even_length = len(payload) - (len(payload) % 2)
    if even_length < 2:
        return []
    return [sample[0] for sample in struct.iter_unpack("<h", payload[:even_length])]


def _compress_level(value: float, *, noise_floor: float) -> float:
    if value <= noise_floor:
        return 0.0
    normalized = _clamp((value - noise_floor) / max(0.001, 1.0 - noise_floor))
    return _clamp(pow(normalized, 0.62))


def _smooth_level(
    value: float, previous: VoiceAudioEnvelope | dict[str, Any] | None
) -> float:
    previous_value = 0.0
    if isinstance(previous, VoiceAudioEnvelope):
        previous_value = previous.smoothed_level
    elif isinstance(previous, dict):
        previous_value = _float(
            previous.get("smoothed_level"), previous.get("smoothed_output_level")
        )
    alpha = 0.58 if value >= previous_value else 0.18
    return _clamp(previous_value + (value - previous_value) * alpha)


def _source(value: Any) -> str:
    text = _text(value)
    return text if text in ENVELOPE_SOURCES else "unavailable"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "active"}
    return bool(value)


def _float(value: Any, default: Any = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        try:
            return float(default)
        except (TypeError, ValueError):
            return 0.0


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _round(value: float) -> float:
    return round(_clamp(float(value)), 4)
