from __future__ import annotations

import math
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any

from stormhelm.core.voice.models import utc_now_iso


ENVELOPE_SOURCES = {
    "stormhelm_playback_meter",
    "playback_output_envelope",
    "streaming_chunk_envelope",
    "precomputed_artifact_envelope",
    "synthetic_fallback_envelope",
    "unavailable",
}

CENTER_BLOB_SCALE_GAIN = 0.32

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
    instant_audio_level: float = 0.0
    fast_audio_level: float = 0.0
    smoothed_level: float = 0.0
    speech_energy: float = 0.0
    visual_drive_level: float = 0.0
    visual_drive_peak: float = 0.0
    center_blob_drive: float = 0.0
    center_blob_scale_drive: float = 0.0
    center_blob_scale: float = 1.0
    outer_speaking_motion: float = 0.0
    visual_gain: float = 1.85
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
            "instant_audio_level": _round(self.instant_audio_level),
            "fast_audio_level": _round(self.fast_audio_level),
            "smoothed_level": _round(self.smoothed_level),
            "speech_energy": _round(self.speech_energy),
            "visual_drive_level": _round(self.visual_drive_level),
            "visual_drive_peak": _round(self.visual_drive_peak),
            "center_blob_drive": _round(self.center_blob_drive),
            "center_blob_scale_drive": _round(self.center_blob_scale_drive),
            "center_blob_scale": _round(self.center_blob_scale, maximum=2.0),
            "outer_speaking_motion": _round(self.outer_speaking_motion),
            "visual_gain": _round(self.visual_gain, maximum=4.0),
            "noise_floor": _round(self.noise_floor),
            "is_silence": bool(self.is_silence),
            "last_update_at": self.last_update_at,
            "update_hz": int(self.update_hz),
            "audio_reactive_available": bool(self.audio_reactive_available),
            "synthetic": bool(self.synthetic),
            "raw_audio_present": False,
        }


@dataclass(frozen=True, slots=True)
class AudioEnvelopeFrame:
    timestamp: str
    audio_offset_ms: int
    duration_ms: int
    rms: float
    peak: float
    visual_drive: float
    envelope: VoiceAudioEnvelope

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "audio_offset_ms": int(self.audio_offset_ms),
            "duration_ms": int(self.duration_ms),
            "rms": _round(self.rms),
            "peak": _round(self.peak),
            "visual_drive": _round(self.visual_drive),
            "center_blob_drive": _round(self.envelope.center_blob_drive),
            "center_blob_scale_drive": _round(self.envelope.center_blob_scale_drive),
            "center_blob_scale": _round(self.envelope.center_blob_scale, maximum=2.0),
            "source": self.envelope.source,
            "synthetic": bool(self.envelope.synthetic),
            "raw_audio_present": False,
        }


@dataclass(frozen=True, slots=True)
class VoicePlaybackMeterFrame:
    timestamp: str
    playback_position_ms: int
    duration_ms: int
    rms: float
    peak: float
    visual_drive: float
    envelope: VoiceAudioEnvelope
    playback_meter_alignment: str = "estimated"

    @property
    def source(self) -> str:
        return self.envelope.source

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "playback_position_ms": int(self.playback_position_ms),
            "audio_offset_ms": int(self.playback_position_ms),
            "duration_ms": int(self.duration_ms),
            "rms": _round(self.rms),
            "peak": _round(self.peak),
            "visual_drive": _round(self.visual_drive),
            "center_blob_drive": _round(self.envelope.center_blob_drive),
            "center_blob_scale_drive": _round(self.envelope.center_blob_scale_drive),
            "center_blob_scale": _round(self.envelope.center_blob_scale, maximum=2.0),
            "source": self.envelope.source,
            "playback_meter_alignment": self.playback_meter_alignment,
            "synthetic": bool(self.envelope.synthetic),
            "raw_audio_present": False,
        }


class VoicePlaybackMeter:
    """Meter Stormhelm's own outgoing PCM buffer at playback-time cadence."""

    def __init__(
        self,
        *,
        update_hz: int = 30,
        sample_rate_hz: int = 24000,
        channels: int = 1,
        sample_width_bytes: int = 2,
        window_ms: int | None = None,
        clock: Any | None = None,
        playback_meter_alignment: str = "estimated",
    ) -> None:
        self.update_hz = max(1, min(60, int(update_hz or 30)))
        self.sample_rate_hz = max(1, int(sample_rate_hz or 24000))
        self.channels = max(1, int(channels or 1))
        self.sample_width_bytes = max(1, int(sample_width_bytes or 2))
        self.window_ms = max(1, int(window_ms or round(1000.0 / self.update_hz)))
        self.playback_meter_alignment = (
            str(playback_meter_alignment or "estimated").strip().lower()
            or "estimated"
        )
        self._clock = clock or time.perf_counter
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._started_monotonic: float | None = None
        self._last_sample_monotonic: float | None = None
        self._previous_envelope: VoiceAudioEnvelope | None = None
        self._active = False

    @property
    def active(self) -> bool:
        with self._lock:
            return bool(self._active)

    @property
    def buffered_duration_ms(self) -> int:
        with self._lock:
            return self._duration_ms_for_bytes_locked(len(self._buffer))

    def start(self, *, start_monotonic: float | None = None) -> None:
        with self._lock:
            self._started_monotonic = (
                float(start_monotonic)
                if start_monotonic is not None
                else float(self._clock())
            )
            self._last_sample_monotonic = None
            self._previous_envelope = None
            self._active = True

    def stop(self) -> None:
        with self._lock:
            self._active = False

    def feed_pcm(self, data: bytes | bytearray | memoryview | None) -> int:
        payload = bytes(data or b"")
        if not payload:
            return 0
        with self._lock:
            self._buffer.extend(payload)
            return len(payload)

    def sample_due(
        self, *, now_monotonic: float | None = None
    ) -> VoicePlaybackMeterFrame | None:
        now = float(now_monotonic if now_monotonic is not None else self._clock())
        with self._lock:
            if not self._active or self._started_monotonic is None:
                return None
            interval = 1.0 / float(self.update_hz)
            if (
                self._last_sample_monotonic is not None
                and now - self._last_sample_monotonic + 1e-9 < interval
            ):
                return None
            self._last_sample_monotonic = now
            position_ms = int(
                max(0.0, round((now - self._started_monotonic) * 1000.0))
            )
        return self.sample_at_playback_position(position_ms)

    def sample_at_playback_position(
        self, playback_position_ms: int | float
    ) -> VoicePlaybackMeterFrame:
        position_ms = int(max(0.0, round(float(playback_position_ms or 0.0))))
        with self._lock:
            payload = self._window_for_position_locked(position_ms)
            previous = self._previous_envelope
        samples = _pcm16_samples(payload)
        if not samples:
            samples = [0] * max(1, int(self.sample_rate_hz * self.channels * self.window_ms / 1000.0))
        envelope = _voice_audio_envelope_from_samples(
            samples,
            source="stormhelm_playback_meter",
            previous=previous,
            update_hz=self.update_hz,
            noise_floor=0.015,
        )
        frame = VoicePlaybackMeterFrame(
            timestamp=envelope.last_update_at,
            playback_position_ms=position_ms,
            duration_ms=self.window_ms,
            rms=envelope.rms_level,
            peak=envelope.peak_level,
            visual_drive=envelope.visual_drive_level,
            envelope=envelope,
            playback_meter_alignment=self.playback_meter_alignment,
        )
        with self._lock:
            self._previous_envelope = envelope
        return frame

    def _window_for_position_locked(self, position_ms: int) -> bytes:
        bytes_per_second = self._bytes_per_second_locked()
        frame_bytes = self.channels * self.sample_width_bytes
        start_byte = int((position_ms / 1000.0) * bytes_per_second)
        start_byte -= start_byte % frame_bytes
        window_bytes = max(
            frame_bytes,
            int((self.window_ms / 1000.0) * bytes_per_second),
        )
        window_bytes -= window_bytes % frame_bytes
        if window_bytes <= 0:
            window_bytes = frame_bytes
        end_byte = start_byte + window_bytes
        segment = bytes(self._buffer[start_byte:end_byte])
        if len(segment) < window_bytes:
            segment += b"\x00" * (window_bytes - len(segment))
        return segment

    def _bytes_per_second_locked(self) -> int:
        return self.sample_rate_hz * self.channels * self.sample_width_bytes

    def _duration_ms_for_bytes_locked(self, size_bytes: int) -> int:
        bytes_per_second = self._bytes_per_second_locked()
        if bytes_per_second <= 0:
            return 0
        return int(round((max(0, int(size_bytes)) / float(bytes_per_second)) * 1000.0))


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
    return _voice_audio_envelope_from_samples(
        samples,
        source=normalized_source,
        previous=previous,
        update_hz=update_hz,
        noise_floor=noise_floor,
    )


def compute_voice_audio_envelope_frames(
    audio: bytes | bytearray | memoryview | None,
    *,
    audio_format: str = "pcm",
    source: str = "streaming_chunk_envelope",
    previous: VoiceAudioEnvelope | dict[str, Any] | None = None,
    update_hz: int = 30,
    sample_rate_hz: int = 24000,
    channels: int = 1,
    noise_floor: float = 0.015,
) -> list[AudioEnvelopeFrame]:
    """Split PCM output into playback-time visual envelope frames."""

    normalized_source = _source(source)
    payload = _audio_payload(audio, audio_format=audio_format)
    samples = _pcm16_samples(payload)
    if not samples:
        return []
    rate = max(1, int(sample_rate_hz or 24000))
    channel_count = max(1, int(channels or 1))
    effective_hz = max(1, min(60, int(update_hz or 30)))
    samples_per_frame = max(channel_count, int((rate * channel_count) / effective_hz))
    frames: list[AudioEnvelopeFrame] = []
    previous_frame: VoiceAudioEnvelope | dict[str, Any] | None = previous
    for offset in range(0, len(samples), samples_per_frame):
        frame_samples = samples[offset : offset + samples_per_frame]
        if not frame_samples:
            continue
        envelope = _voice_audio_envelope_from_samples(
            frame_samples,
            source=normalized_source,
            previous=previous_frame,
            update_hz=effective_hz,
            noise_floor=noise_floor,
        )
        duration_ms = max(
            1,
            int(round((len(frame_samples) / float(rate * channel_count)) * 1000.0)),
        )
        frames.append(
            AudioEnvelopeFrame(
                timestamp=envelope.last_update_at,
                audio_offset_ms=int(round((offset / float(rate * channel_count)) * 1000.0)),
                duration_ms=duration_ms,
                rms=envelope.rms_level,
                peak=envelope.peak_level,
                visual_drive=envelope.visual_drive_level,
                envelope=envelope,
            )
        )
        previous_frame = envelope
    return frames


def _voice_audio_envelope_from_samples(
    samples: list[int],
    *,
    source: str,
    previous: VoiceAudioEnvelope | dict[str, Any] | None,
    update_hz: int,
    noise_floor: float,
) -> VoiceAudioEnvelope:
    peak = max(abs(sample) for sample in samples) / 32768.0
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
    energy = _compress_level(rms, noise_floor=noise_floor)
    smoothed = _smooth_level(energy, previous)
    (
        visual_drive,
        visual_peak,
        visual_gain,
        instant_audio_level,
        fast_audio_level,
        center_blob_drive,
        center_blob_scale_drive,
        center_blob_scale,
        outer_speaking_motion,
    ) = _visual_drive_levels(
        energy,
        peak,
        source=source,
        previous=previous,
        noise_floor=noise_floor,
        rms_level=rms,
        smoothed_level=smoothed,
    )
    return VoiceAudioEnvelope(
        source=source,
        rms_level=_clamp(rms),
        peak_level=_clamp(peak),
        instant_audio_level=instant_audio_level,
        fast_audio_level=fast_audio_level,
        smoothed_level=smoothed,
        speech_energy=energy,
        visual_drive_level=visual_drive,
        visual_drive_peak=visual_peak,
        center_blob_drive=center_blob_drive,
        center_blob_scale_drive=center_blob_scale_drive,
        center_blob_scale=center_blob_scale,
        outer_speaking_motion=outer_speaking_motion,
        visual_gain=visual_gain,
        noise_floor=_clamp(noise_floor),
        is_silence=energy <= 0.02,
        last_update_at=utc_now_iso(),
        update_hz=max(1, min(60, int(update_hz or 30))),
        audio_reactive_available=source
        in {
            "stormhelm_playback_meter",
            "playback_output_envelope",
            "streaming_chunk_envelope",
            "precomputed_artifact_envelope",
        },
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
    (
        visual_drive,
        visual_peak,
        visual_gain,
        instant_audio_level,
        fast_audio_level,
        center_blob_drive,
        center_blob_scale_drive,
        center_blob_scale,
        outer_speaking_motion,
    ) = _visual_drive_levels(
        energy,
        value,
        source=normalized,
        previous=previous,
        noise_floor=0.0,
        rms_level=value,
        smoothed_level=smoothed,
    )
    return VoiceAudioEnvelope(
        source=normalized,
        rms_level=value,
        peak_level=value,
        instant_audio_level=instant_audio_level,
        fast_audio_level=fast_audio_level,
        smoothed_level=smoothed,
        speech_energy=energy,
        visual_drive_level=visual_drive,
        visual_drive_peak=visual_peak,
        center_blob_drive=center_blob_drive,
        center_blob_scale_drive=center_blob_scale_drive,
        center_blob_scale=center_blob_scale,
        outer_speaking_motion=outer_speaking_motion,
        visual_gain=visual_gain,
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
    visual_drive_level = _explicit_float(
        explicit.get("visual_drive_level"),
        explicit.get("voice_visual_drive_level"),
        default=envelope.visual_drive_level,
    )
    visual_drive_peak = _explicit_float(
        explicit.get("visual_drive_peak"),
        explicit.get("voice_visual_drive_peak"),
        default=envelope.visual_drive_peak,
    )
    visual_gain = _explicit_float(
        explicit.get("visual_gain"),
        explicit.get("voice_visual_gain"),
        default=envelope.visual_gain,
        maximum=4.0,
    )
    center_blob_drive = _explicit_float(
        explicit.get("center_blob_drive"),
        explicit.get("voice_center_blob_drive"),
        explicit.get("center_blob_scale_drive"),
        explicit.get("voice_center_blob_scale_drive"),
        default=envelope.center_blob_scale_drive,
    )
    center_blob_scale_drive = _explicit_float(
        explicit.get("center_blob_scale_drive"),
        explicit.get("voice_center_blob_scale_drive"),
        explicit.get("center_blob_drive"),
        explicit.get("voice_center_blob_drive"),
        default=center_blob_drive,
    )
    center_blob_scale = _explicit_float(
        explicit.get("center_blob_scale"),
        explicit.get("voice_center_blob_scale"),
        default=1.0 + center_blob_scale_drive * CENTER_BLOB_SCALE_GAIN,
        maximum=2.0,
    )
    outer_speaking_motion = _explicit_float(
        explicit.get("outer_speaking_motion"),
        explicit.get("voice_outer_speaking_motion"),
        default=envelope.outer_speaking_motion,
    )
    if state not in {"speaking", "preparing_speech"}:
        outer_speaking_motion = min(outer_speaking_motion, visual_drive_level)
    motion_intensity = _motion_intensity(state, outer_speaking_motion, envelope)
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
        "audio_level_raw": _round(
            _float(explicit.get("audio_level_raw"), envelope.rms_level)
        ),
        "output_level_peak": _round(
            _float(explicit.get("output_level_peak"), envelope.peak_level)
        ),
        "instant_audio_level": _round(
            _float(explicit.get("instant_audio_level"), envelope.instant_audio_level)
        ),
        "fast_audio_level": _round(
            _float(explicit.get("fast_audio_level"), envelope.fast_audio_level)
        ),
        "smoothed_output_level": _round(
            _float(explicit.get("smoothed_output_level"), envelope.smoothed_level)
        ),
        "speech_energy": _round(
            _float(explicit.get("speech_energy"), envelope.speech_energy)
        ),
        "visual_drive_level": _round(visual_drive_level),
        "visual_drive_peak": _round(max(visual_drive_peak, visual_drive_level)),
        "center_blob_drive": _round(center_blob_drive),
        "center_blob_scale_drive": _round(center_blob_scale_drive),
        "center_blob_scale": _round(center_blob_scale, maximum=2.0),
        "outer_speaking_motion": _round(outer_speaking_motion),
        "visual_gain": _round(visual_gain, maximum=4.0),
        "audio_drive_level": _round(center_blob_scale_drive),
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
    playback_active_now = _playback_active(voice)
    if (
        playback_active_now
        and not _interrupted(interruption)
        and not _truthy(interruption.get("spoken_output_muted"))
    ):
        return "speaking"
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
    if playback_active_now:
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
    rms_level = _clamp(_float(payload.get("rms_level"), payload.get("output_level_rms")))
    peak_level = _clamp(_float(payload.get("peak_level"), payload.get("output_level_peak")))
    smoothed_level = _clamp(
        _float(payload.get("smoothed_level"), payload.get("smoothed_output_level"))
    )
    speech_energy = _clamp(_float(payload.get("speech_energy"), smoothed_level))
    (
        computed_drive,
        computed_peak,
        computed_gain,
        computed_instant_level,
        computed_fast_level,
        computed_center_drive,
        computed_center_scale_drive,
        computed_center_scale,
        computed_outer_motion,
    ) = _visual_drive_levels(
        speech_energy,
        peak_level,
        source=source,
        previous=None,
        noise_floor=_clamp(_float(payload.get("noise_floor"), 0.015)),
        rms_level=rms_level,
        smoothed_level=smoothed_level,
    )
    visual_drive_level = _explicit_float(
        payload.get("visual_drive_level"),
        payload.get("voice_visual_drive_level"),
        payload.get("audio_drive_level"),
        default=computed_drive,
    )
    visual_drive_peak = _explicit_float(
        payload.get("visual_drive_peak"),
        payload.get("voice_visual_drive_peak"),
        default=computed_peak,
    )
    instant_audio_level = _explicit_float(
        payload.get("instant_audio_level"),
        payload.get("voice_instant_audio_level"),
        default=computed_instant_level,
    )
    fast_audio_level = _explicit_float(
        payload.get("fast_audio_level"),
        payload.get("voice_fast_audio_level"),
        default=computed_fast_level,
    )
    center_blob_drive = _explicit_float(
        payload.get("center_blob_drive"),
        payload.get("voice_center_blob_drive"),
        payload.get("audio_drive_level"),
        payload.get("center_blob_scale_drive"),
        payload.get("voice_center_blob_scale_drive"),
        default=computed_center_scale_drive,
    )
    center_blob_scale_drive = _explicit_float(
        payload.get("center_blob_scale_drive"),
        payload.get("voice_center_blob_scale_drive"),
        payload.get("center_blob_drive"),
        payload.get("voice_center_blob_drive"),
        payload.get("audio_drive_level"),
        default=computed_center_scale_drive,
    )
    center_blob_scale = _explicit_float(
        payload.get("center_blob_scale"),
        payload.get("voice_center_blob_scale"),
        default=1.0 + center_blob_scale_drive * CENTER_BLOB_SCALE_GAIN,
        maximum=2.0,
    )
    outer_speaking_motion = _explicit_float(
        payload.get("outer_speaking_motion"),
        payload.get("voice_outer_speaking_motion"),
        default=computed_outer_motion,
    )
    visual_gain = _explicit_float(
        payload.get("visual_gain"),
        payload.get("voice_visual_gain"),
        default=computed_gain,
        maximum=4.0,
    )
    return VoiceAudioEnvelope(
        source=source,
        rms_level=rms_level,
        peak_level=peak_level,
        instant_audio_level=instant_audio_level,
        fast_audio_level=fast_audio_level,
        smoothed_level=smoothed_level,
        speech_energy=speech_energy,
        visual_drive_level=visual_drive_level,
        visual_drive_peak=max(visual_drive_peak, visual_drive_level),
        center_blob_drive=center_blob_drive,
        center_blob_scale_drive=center_blob_scale_drive,
        center_blob_scale=center_blob_scale,
        outer_speaking_motion=outer_speaking_motion,
        visual_gain=visual_gain,
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


def _motion_intensity(state: str, outer_speaking_motion: float, envelope: VoiceAudioEnvelope) -> float:
    if state == "speaking":
        if envelope.source in {"synthetic_fallback_envelope", "unavailable"}:
            return _clamp(0.16 + outer_speaking_motion * 0.26)
        return _clamp(0.14 + outer_speaking_motion * 0.74)
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


def _instant_audio_level(rms_level: float, peak_level: float, *, noise_floor: float) -> float:
    current = max(_clamp(rms_level), _clamp(peak_level) * 0.58)
    gate = max(0.004, noise_floor * 1.08)
    if current <= gate:
        return 0.0
    normalized = _clamp((current - gate) / max(0.001, 1.0 - gate))
    return _clamp(pow(normalized, 0.32) * 1.03)


def _fast_audio_level(
    value: float, previous: VoiceAudioEnvelope | dict[str, Any] | None
) -> float:
    previous_value = _previous_fast_audio_level(previous)
    if previous_value is None:
        return _clamp(value)
    alpha = 0.94 if value >= previous_value else 0.9
    return _clamp(previous_value + (_clamp(value) - previous_value) * alpha)


def _visual_drive_levels(
    energy: float,
    peak_level: float,
    *,
    source: str,
    previous: VoiceAudioEnvelope | dict[str, Any] | None,
    noise_floor: float,
    rms_level: float,
    smoothed_level: float,
) -> tuple[float, float, float, float, float, float, float, float, float]:
    if source == "unavailable":
        return 0.0, 0.0, 1.85, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0
    energy_level = _clamp(energy)
    meter_source = source == "stormhelm_playback_meter"
    drive_energy = energy_level if meter_source else max(energy_level, _clamp(smoothed_level))
    peak = _clamp(peak_level)
    instant_level = _instant_audio_level(rms_level, peak, noise_floor=noise_floor)
    fast_level = _fast_audio_level(instant_level, previous)
    if source == "synthetic_fallback_envelope":
        if energy_level <= 0.0 and peak <= 0.0:
            return 0.0, 0.0, 1.2, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0
        fallback_energy = max(energy_level, drive_energy, peak)
        drive = _clamp(pow(fallback_energy, 0.82) * 0.42)
        instant_level = _instant_audio_level(max(rms_level, fallback_energy), peak, noise_floor=0.0)
        fast_level = _fast_audio_level(instant_level, previous)
        center_drive = _clamp(fast_level)
        outer_motion = _clamp(max(0.1, drive))
        center_scale = 1.0 + center_drive * CENTER_BLOB_SCALE_GAIN
        return (
            drive,
            max(drive, _clamp(drive + 0.08)),
            1.2,
            instant_level,
            fast_level,
            center_drive,
            center_drive,
            center_scale,
            outer_motion,
        )
    if energy_level <= 0.018 and peak <= max(0.02, noise_floor):
        raw_drive = 0.0
        raw_center = 0.0
    else:
        raw_drive = _clamp(pow(max(drive_energy, 0.0), 0.45) * 0.99)
        raw_center = _clamp(pow(max(drive_energy, 0.0), 0.9) * 1.15)
    previous_drive = _previous_visual_drive(previous)
    if previous_drive is not None and not meter_source:
        alpha = 0.88 if raw_drive >= previous_drive else 0.74
        raw_drive = _clamp(previous_drive + (raw_drive - previous_drive) * alpha)
    previous_center = _previous_center_blob_drive(previous)
    if previous_center is not None and not meter_source:
        alpha = 0.92 if raw_center >= previous_center else 0.76
        raw_center = _clamp(previous_center + (raw_center - previous_center) * alpha)
    peak_floor = 0.0
    if peak > noise_floor:
        normalized_peak = _clamp((peak - noise_floor) / max(0.001, 1.0 - noise_floor))
        peak_floor = _clamp(pow(normalized_peak, 0.55) * 0.92)
    visual_peak = _clamp(max(raw_drive, peak_floor))
    center_drive = fast_level if instant_level > 0.0 or fast_level > 0.0 else raw_center
    center_scale = 1.0 + center_drive * CENTER_BLOB_SCALE_GAIN
    outer_motion = _clamp(max(raw_drive, center_drive * 0.72))
    return (
        raw_drive,
        visual_peak,
        1.85,
        instant_level,
        fast_level,
        center_drive,
        center_drive,
        center_scale,
        outer_motion,
    )


def _previous_visual_drive(
    previous: VoiceAudioEnvelope | dict[str, Any] | None
) -> float | None:
    if isinstance(previous, VoiceAudioEnvelope):
        return previous.visual_drive_level
    if isinstance(previous, dict):
        value = _optional_float(
            previous.get("visual_drive_level"),
            previous.get("voice_visual_drive_level"),
            previous.get("audio_drive_level"),
        )
        return _clamp(value) if value is not None else None
    return None


def _previous_center_blob_drive(
    previous: VoiceAudioEnvelope | dict[str, Any] | None
) -> float | None:
    if isinstance(previous, VoiceAudioEnvelope):
        return previous.center_blob_drive
    if isinstance(previous, dict):
        value = _optional_float(
            previous.get("center_blob_drive"),
            previous.get("voice_center_blob_drive"),
            previous.get("audio_drive_level"),
        )
        return _clamp(value) if value is not None else None
    return None


def _previous_fast_audio_level(
    previous: VoiceAudioEnvelope | dict[str, Any] | None
) -> float | None:
    if isinstance(previous, VoiceAudioEnvelope):
        return previous.fast_audio_level
    if isinstance(previous, dict):
        value = _optional_float(
            previous.get("fast_audio_level"),
            previous.get("voice_fast_audio_level"),
            previous.get("center_blob_scale_drive"),
            previous.get("voice_center_blob_scale_drive"),
            previous.get("center_blob_drive"),
            previous.get("voice_center_blob_drive"),
            previous.get("audio_drive_level"),
        )
        return _clamp(value) if value is not None else None
    return None


def _explicit_float(
    *values: Any,
    default: float = 0.0,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    value = _optional_float(*values)
    return _clamp(default if value is None else value, minimum, maximum)


def _optional_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


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


def _round(value: float, *, maximum: float = 1.0) -> float:
    return round(_clamp(float(value), maximum=maximum), 4)
