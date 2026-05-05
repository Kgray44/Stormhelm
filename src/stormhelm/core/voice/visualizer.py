from __future__ import annotations

import math
import os
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any

from stormhelm.core.voice.models import utc_now_iso


ENVELOPE_SOURCES = {
    "pcm_stream_meter",
    "playback_pcm",
    "stormhelm_playback_meter",
    "playback_output_envelope",
    "streaming_chunk_envelope",
    "precomputed_artifact_envelope",
    "synthetic_fallback_envelope",
    "unavailable",
}

CENTER_BLOB_SCALE_GAIN = 0.32
_ANCHOR_VISUALIZER_MODE_ENV = "STORMHELM_ANCHOR_VISUALIZER_MODE"
_PLAYBACK_ENVELOPE_ALIGNMENT_TOLERANCE_MS = 260
_FORCED_ANCHOR_VISUALIZER_STRATEGIES = {
    "off": "off",
    "constant_test_wave": "constant_test_wave",
    "pcm_stream_meter": "pcm_stream_meter",
    "procedural": "procedural_speaking",
    "envelope_timeline": "playback_envelope_timeline",
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


@dataclass(frozen=True, slots=True)
class VoicePlaybackEnvelopeSample:
    playback_id: str
    sample_time_ms: int
    monotonic_time_ms: int
    rms: float
    peak: float
    energy: float
    smoothed_energy: float
    sample_rate: int
    channels: int
    source: str = "pcm_playback"
    valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "playback_id": self.playback_id,
            "sample_time_ms": int(self.sample_time_ms),
            "monotonic_time_ms": int(self.monotonic_time_ms),
            "rms": _round(self.rms),
            "peak": _round(self.peak),
            "energy": _round(self.energy),
            "smoothed_energy": _round(self.smoothed_energy),
            "sample_rate": int(self.sample_rate),
            "channels": int(self.channels),
            "source": self.source,
            "valid": bool(self.valid),
            "raw_audio_present": False,
        }

    def to_timeline_dict(self) -> dict[str, Any]:
        return {
            "t_ms": int(self.sample_time_ms),
            "energy": _round(self.smoothed_energy),
        }


class VoicePlaybackEnvelopeBuffer:
    """Bounded UI-safe scalar envelope samples keyed by playback time."""

    def __init__(
        self,
        *,
        playback_id: str,
        max_duration_ms: int = 5000,
        sample_rate_hz: int = 60,
    ) -> None:
        self.playback_id = str(playback_id or "")
        self.max_duration_ms = max(1, int(max_duration_ms or 5000))
        self.sample_rate_hz = max(1, min(60, int(sample_rate_hz or 60)))
        self._samples: list[VoicePlaybackEnvelopeSample] = []
        self.samples_dropped = 0

    @property
    def max_sample_count(self) -> int:
        return max(
            1,
            int(math.ceil(self.max_duration_ms * self.sample_rate_hz / 1000.0)) + 2,
        )

    @property
    def latest_sample(self) -> VoicePlaybackEnvelopeSample | None:
        return self._samples[-1] if self._samples else None

    @property
    def samples(self) -> list[VoicePlaybackEnvelopeSample]:
        return list(self._samples)

    def append(self, sample: VoicePlaybackEnvelopeSample) -> None:
        self._samples.append(sample)
        self._prune()

    def extend(self, samples: list[VoicePlaybackEnvelopeSample]) -> None:
        if not samples:
            return
        self._samples.extend(samples)
        self._prune()

    def recent(self, *, max_samples: int = 12) -> list[VoicePlaybackEnvelopeSample]:
        limit = max(0, int(max_samples or 0))
        if limit <= 0:
            return []
        return list(self._samples[-limit:])

    def around(
        self,
        *,
        playback_time_ms: int | float | None,
        max_samples: int = 12,
    ) -> list[VoicePlaybackEnvelopeSample]:
        limit = max(0, int(max_samples or 0))
        if limit <= 0 or not self._samples:
            return []
        if playback_time_ms is None:
            return self.recent(max_samples=limit)
        try:
            target = float(playback_time_ms)
        except (TypeError, ValueError):
            return self.recent(max_samples=limit)
        if not math.isfinite(target):
            return self.recent(max_samples=limit)
        target = max(0.0, target)
        sample_count = len(self._samples)
        before_index = 0
        for index, sample in enumerate(self._samples):
            if sample.sample_time_ms <= target:
                before_index = index
            else:
                break
        half_before = max(1, limit // 2)
        start = max(0, before_index - half_before + 1)
        end = min(sample_count, start + limit)
        start = max(0, end - limit)
        return list(self._samples[start:end])

    def sample_near(
        self, playback_time_ms: int | float | None
    ) -> VoicePlaybackEnvelopeSample | None:
        if not self._samples:
            return None
        if playback_time_ms is None:
            return self.latest_sample
        try:
            target = float(playback_time_ms)
        except (TypeError, ValueError):
            return self.latest_sample
        if not math.isfinite(target):
            return self.latest_sample
        target = max(0.0, target)
        return min(self._samples, key=lambda sample: abs(sample.sample_time_ms - target))

    def to_bridge_payload(
        self,
        *,
        max_samples: int = 12,
        playback_time_ms: int | float | None = None,
        envelope_supported: bool = True,
        envelope_source: str = "playback_pcm",
        estimated_output_latency_ms: int = 80,
        disabled_reason: str | None = None,
        now_monotonic_ms: int | float | None = None,
    ) -> dict[str, Any]:
        latest = self.latest_sample
        selected = self.sample_near(playback_time_ms)
        available = bool(envelope_supported and latest is not None)
        age_ms = None
        if selected is not None and now_monotonic_ms is not None:
            age_ms = max(
                0, int(round(float(now_monotonic_ms) - selected.monotonic_time_ms))
            )
        window = self.around(
            playback_time_ms=playback_time_ms,
            max_samples=max_samples,
        )
        query_time_ms = None
        window_mode = "latest"
        if playback_time_ms is not None:
            try:
                query_time_ms = max(0, int(round(float(playback_time_ms))))
                window_mode = "playback_time"
            except (TypeError, ValueError):
                query_time_ms = None
                window_mode = "latest"
        return {
            "playback_id": self.playback_id,
            "envelope_supported": bool(envelope_supported),
            "envelope_available": available,
            "envelope_source": envelope_source if envelope_supported else "unavailable",
            "envelope_sample_rate_hz": int(self.sample_rate_hz),
            "latest_voice_energy": _round(
                selected.smoothed_energy if selected else 0.0
            ),
            "latest_voice_energy_time_ms": int(selected.sample_time_ms)
            if selected
            else None,
            "latest_voice_energy_monotonic_ms": int(selected.monotonic_time_ms)
            if selected
            else None,
            "playback_envelope_sample_age_ms": age_ms,
            "playback_envelope_window_mode": window_mode,
            "playback_envelope_query_time_ms": query_time_ms,
            "estimated_output_latency_ms": int(
                max(0, int(estimated_output_latency_ms or 0))
            ),
            "envelope_samples_recent": [sample.to_dict() for sample in window],
            "envelope_timeline_samples": [
                sample.to_timeline_dict() for sample in window
            ],
            "envelopeTimelineSamples": [
                sample.to_timeline_dict() for sample in window
            ],
            "envelope_timeline_available": bool(available and len(window) >= 2),
            "envelope_timeline_sample_rate_hz": int(self.sample_rate_hz),
            "envelope_timeline_sample_count": int(len(window)),
            "envelope_timeline_source": (
                "playback_pcm" if envelope_supported and available else "unavailable"
            ),
            "samples_dropped": int(self.samples_dropped),
            "envelope_samples_dropped": int(self.samples_dropped),
            "envelope_disabled_reason": disabled_reason
            if not envelope_supported or not available
            else None,
            "raw_audio_present": False,
        }

    def _prune(self) -> None:
        if not self._samples:
            return
        latest_ms = self._samples[-1].sample_time_ms
        oldest_allowed = latest_ms - self.max_duration_ms
        while self._samples and self._samples[0].sample_time_ms < oldest_allowed:
            self._samples.pop(0)
            self.samples_dropped += 1
        while len(self._samples) > self.max_sample_count:
            self._samples.pop(0)
            self.samples_dropped += 1


class VoicePlaybackEnvelopeFollower:
    """Compute a low-rate scalar envelope from PCM being submitted to output."""

    def __init__(
        self,
        *,
        playback_id: str,
        sample_rate_hz: int = 24000,
        channels: int = 1,
        sample_width_bytes: int = 2,
        envelope_sample_rate_hz: int = 60,
        max_duration_ms: int = 5000,
        estimated_output_latency_ms: int = 80,
        clock: Any | None = None,
    ) -> None:
        self.playback_id = str(playback_id or "")
        self.sample_rate_hz = max(1, int(sample_rate_hz or 24000))
        self.channels = max(1, int(channels or 1))
        self.sample_width_bytes = max(1, int(sample_width_bytes or 2))
        self.envelope_sample_rate_hz = max(
            30, min(60, int(envelope_sample_rate_hz or 60))
        )
        self.estimated_output_latency_ms = max(
            0, int(estimated_output_latency_ms or 0)
        )
        self._clock = clock or time.perf_counter
        self._pending = bytearray()
        self._lock = threading.Lock()
        self._processed_frames = 0
        self._started_monotonic_ms: float | None = None
        self._previous_envelope: VoiceAudioEnvelope | None = None
        self._buffer = VoicePlaybackEnvelopeBuffer(
            playback_id=self.playback_id,
            max_duration_ms=max_duration_ms,
            sample_rate_hz=self.envelope_sample_rate_hz,
        )
        self._disabled_reason = (
            "unsupported_sample_width"
            if self.sample_width_bytes != 2
            else None
        )

    @property
    def supported(self) -> bool:
        return self._disabled_reason is None

    @property
    def latest_sample(self) -> VoicePlaybackEnvelopeSample | None:
        with self._lock:
            return self._buffer.latest_sample

    @property
    def samples_dropped(self) -> int:
        with self._lock:
            return int(self._buffer.samples_dropped)

    def feed_pcm(
        self,
        data: bytes | bytearray | memoryview | None,
        *,
        submitted_at_monotonic_ms: int | float | None = None,
    ) -> list[VoicePlaybackEnvelopeSample]:
        payload = bytes(data or b"")
        if not payload or not self.supported:
            return []
        now_ms = (
            float(submitted_at_monotonic_ms)
            if submitted_at_monotonic_ms is not None
            else self._now_ms()
        )
        frame_bytes = max(1, self.channels * self.sample_width_bytes)
        frames_per_window = max(
            1, int(round(self.sample_rate_hz / float(self.envelope_sample_rate_hz)))
        )
        bytes_per_window = max(frame_bytes, frames_per_window * frame_bytes)
        produced: list[VoicePlaybackEnvelopeSample] = []
        with self._lock:
            if self._started_monotonic_ms is None:
                self._started_monotonic_ms = now_ms
            self._pending.extend(payload)
            while len(self._pending) >= bytes_per_window:
                window = bytes(self._pending[:bytes_per_window])
                del self._pending[:bytes_per_window]
                sample_time_ms = int(
                    round((self._processed_frames / float(self.sample_rate_hz)) * 1000.0)
                )
                monotonic_time_ms = int(
                    round((self._started_monotonic_ms or now_ms) + sample_time_ms)
                )
                self._processed_frames += frames_per_window
                samples = _pcm16_samples(window)
                if not samples:
                    continue
                envelope = _voice_audio_envelope_from_samples(
                    samples,
                    source="playback_pcm",
                    previous=self._previous_envelope,
                    update_hz=self.envelope_sample_rate_hz,
                    noise_floor=0.015,
                )
                self._previous_envelope = envelope
                sample = VoicePlaybackEnvelopeSample(
                    playback_id=self.playback_id,
                    sample_time_ms=sample_time_ms,
                    monotonic_time_ms=monotonic_time_ms,
                    rms=envelope.rms_level,
                    peak=envelope.peak_level,
                    energy=envelope.speech_energy,
                    smoothed_energy=envelope.smoothed_level,
                    sample_rate=self.sample_rate_hz,
                    channels=self.channels,
                )
                self._buffer.append(sample)
                produced.append(sample)
        return produced

    def to_bridge_payload(
        self,
        *,
        max_samples: int = 12,
        playback_time_ms: int | float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            return self._buffer.to_bridge_payload(
                max_samples=max_samples,
                playback_time_ms=playback_time_ms,
                envelope_supported=self.supported,
                envelope_source="playback_pcm",
                estimated_output_latency_ms=self.estimated_output_latency_ms,
                disabled_reason=self._disabled_reason,
                now_monotonic_ms=self._now_ms(),
            )

    def _now_ms(self) -> float:
        return float(self._clock()) * 1000.0


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
            "pcm_stream_meter",
            "playback_pcm",
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
        audio_reactive_available=normalized
        in {
            "pcm_stream_meter",
            "playback_pcm",
            "stormhelm_playback_meter",
            "playback_output_envelope",
            "streaming_chunk_envelope",
            "precomputed_artifact_envelope",
        },
        synthetic=normalized == "synthetic_fallback_envelope",
        raw_audio_present=False,
    )


def build_voice_anchor_payload(voice_status: dict[str, Any] | None) -> dict[str, Any]:
    voice = _dict(voice_status)
    explicit = _dict(voice.get("voice_anchor"))
    state = _state(explicit.get("state") or _derive_anchor_state(voice))
    envelope = _select_envelope(voice, state=state)
    voice_visual = _select_voice_visual_payload(voice)
    voice_visual_source = _source(
        voice_visual.get("voice_visual_source")
        or voice_visual.get("voice_visual_energy_source")
        or voice_visual.get("source")
    )
    voice_visual_energy = _clamp(
        _explicit_float(
            voice_visual.get("voice_visual_energy"),
            voice_visual.get("energy"),
            voice_visual.get("latest_energy"),
            default=0.0,
        )
    )
    voice_visual_active = bool(
        _truthy(voice_visual.get("voice_visual_active"))
        or _truthy(voice_visual.get("active"))
    )
    voice_visual_available = bool(
        voice_visual_source == "pcm_stream_meter"
        and (
            _truthy(voice_visual.get("voice_visual_available"))
            or _truthy(voice_visual.get("available"))
            or voice_visual_active
        )
    )
    voice_visual_disabled_reason = _text(
        voice_visual.get("voice_visual_disabled_reason")
        or voice_visual.get("disabled_reason")
    )
    voice_visual_playback_id = (
        voice_visual.get("voice_visual_playback_id")
        or voice_visual.get("playback_id")
        or _dict(voice.get("playback")).get("active_playback_id")
    )
    voice_visual_sample_rate_hz = int(
        _explicit_float(
            voice_visual.get("voice_visual_sample_rate_hz"),
            voice_visual.get("sample_rate_hz"),
            default=0.0,
            maximum=120.0,
        )
    )
    voice_visual_started_at_ms = voice_visual.get("voice_visual_started_at_ms")
    voice_visual_latest_age_ms = voice_visual.get("voice_visual_latest_age_ms")
    pcm_meter_present = voice_visual_source == "pcm_stream_meter"
    playback_envelope = _select_playback_envelope_payload(voice)
    playback_envelope_source = _text(
        playback_envelope.get("envelope_source")
        or playback_envelope.get("playback_envelope_source")
        or "unavailable"
    )
    playback_envelope_supported = bool(playback_envelope.get("envelope_supported"))
    playback_envelope_available = bool(
        playback_envelope_supported
        and playback_envelope.get("envelope_available")
        and playback_envelope_source == "playback_pcm"
    )
    playback_envelope_energy = _clamp(
        _explicit_float(
            playback_envelope.get("latest_voice_energy"),
            playback_envelope.get("playback_envelope_energy"),
            playback_envelope.get("smoothed_energy"),
            default=0.0,
        )
    )
    playback_envelope_sample_rate_hz = int(
        max(
            0,
            _explicit_float(
                playback_envelope.get("envelope_sample_rate_hz"),
                playback_envelope.get("playback_envelope_sample_rate_hz"),
                default=0.0,
                maximum=240.0,
            ),
        )
    )
    playback_envelope_latency_ms = int(
        max(
            0,
            _explicit_float(
                playback_envelope.get("estimated_output_latency_ms"),
                playback_envelope.get("playback_envelope_latency_ms"),
                default=0.0,
                maximum=2000.0,
            ),
        )
    )
    envelope_visual_offset_ms = int(
        _explicit_float(
            playback_envelope.get("envelope_visual_offset_ms"),
            playback_envelope.get("playback_envelope_visual_offset_ms"),
            default=0.0,
            minimum=-500.0,
            maximum=500.0,
        )
    )
    playback_visual_time_ms = _optional_float(
        playback_envelope.get("playback_visual_time_ms"),
        playback_envelope.get("playback_clock_ms"),
    )
    playback_envelope_time_offset_applied_ms = _optional_float(
        playback_envelope.get("playback_envelope_time_offset_applied_ms")
    )
    playback_envelope_sync_enabled = bool(
        playback_envelope.get("playback_envelope_sync_enabled", True)
    )
    envelope_sync_calibration_version = str(
        playback_envelope.get("envelope_sync_calibration_version") or "Voice-L0.5"
    )
    envelope_sync_debug_show_sync = bool(
        playback_envelope.get("envelope_sync_debug_show_sync", False)
    )
    playback_envelope_window_mode = (
        playback_envelope.get("playback_envelope_window_mode") or "latest"
    )
    playback_envelope_query_time_ms = playback_envelope.get(
        "playback_envelope_query_time_ms"
    )
    playback_envelope_timeline_samples = _playback_envelope_timeline_samples(
        playback_envelope
    )
    if (
        playback_envelope_query_time_ms is not None
        and _text(playback_envelope_window_mode) != "playback_time"
        and (
            playback_envelope.get("envelope_samples_recent")
            or playback_envelope.get("playback_envelope_samples_recent")
            or playback_envelope_timeline_samples
        )
    ):
        playback_envelope = dict(playback_envelope)
        playback_envelope["playback_envelope_window_mode"] = "playback_time"
        playback_envelope_window_mode = "playback_time"
    playback_envelope_samples = _playback_envelope_samples(playback_envelope)
    if not playback_envelope_samples and playback_envelope_timeline_samples:
        playback_envelope_samples = _playback_envelope_samples_from_timeline(
            playback_envelope_timeline_samples,
            sample_rate=int(playback_envelope_sample_rate_hz),
        )
    playback_envelope_sample_count = len(playback_envelope_samples)
    if playback_envelope_energy <= 0.006 and playback_envelope_samples:
        playback_envelope_energy = _playback_envelope_energy_near_query(
            playback_envelope_samples,
            query_time_ms=playback_envelope_query_time_ms,
        )
    (
        computed_timebase_aligned,
        computed_alignment_error_ms,
        computed_alignment_status,
        computed_alignment_tolerance_ms,
    ) = (
        _playback_envelope_timebase_alignment(
            playback_envelope_samples,
            query_time_ms=playback_envelope_query_time_ms,
            window_mode=playback_envelope_window_mode,
        )
    )
    explicit_timebase_aligned = playback_envelope.get(
        "playback_envelope_timebase_aligned"
    )
    if isinstance(explicit_timebase_aligned, str):
        explicit_timebase_aligned_bool = (
            explicit_timebase_aligned.strip().lower()
            in {"1", "true", "yes", "on", "aligned"}
        )
    else:
        explicit_timebase_aligned_bool = bool(explicit_timebase_aligned)
    playback_envelope_timebase_aligned = (
        computed_timebase_aligned or explicit_timebase_aligned_bool
    )
    playback_envelope_alignment_error_ms = playback_envelope.get(
        "playback_envelope_alignment_error_ms"
    )
    if computed_alignment_error_ms is not None:
        playback_envelope_alignment_error_ms = computed_alignment_error_ms
    elif playback_envelope_alignment_error_ms is not None:
        try:
            playback_envelope_alignment_error_ms = max(
                0, int(round(float(playback_envelope_alignment_error_ms)))
            )
        except (TypeError, ValueError):
            playback_envelope_alignment_error_ms = None
    playback_envelope_alignment_delta_ms = playback_envelope.get(
        "playback_envelope_alignment_delta_ms"
    )
    if computed_alignment_error_ms is not None:
        playback_envelope_alignment_delta_ms = computed_alignment_error_ms
    elif playback_envelope_alignment_delta_ms is not None:
        try:
            playback_envelope_alignment_delta_ms = max(
                0, int(round(float(playback_envelope_alignment_delta_ms)))
            )
        except (TypeError, ValueError):
            playback_envelope_alignment_delta_ms = None
    playback_envelope_alignment_status = str(
        playback_envelope.get("playback_envelope_alignment_status")
        or computed_alignment_status
        or "unknown"
    )
    if computed_alignment_status not in {"no_samples", "not_playback_time"}:
        playback_envelope_alignment_status = computed_alignment_status
    playback_envelope_sample_age_value = playback_envelope.get(
        "playback_envelope_sample_age_ms"
    )
    try:
        playback_envelope_sample_age_ms = (
            None
            if playback_envelope_sample_age_value is None
            else max(0, int(round(float(playback_envelope_sample_age_value))))
        )
    except (TypeError, ValueError):
        playback_envelope_sample_age_ms = None
    playback_envelope_stale = bool(
        playback_envelope_sample_age_ms is not None
        and playback_envelope_sample_age_ms > 500
    )
    playback_envelope_has_energy = bool(
        playback_envelope_energy > 0.006
        or any(
            _explicit_float(
                sample.get("smoothed_energy"),
                sample.get("energy"),
                default=0.0,
            )
            > 0.006
            for sample in playback_envelope_samples
        )
    )
    playback_envelope_backend_usable_allowed = _truthy(
        playback_envelope.get("playback_envelope_usable", True)
    ) or (
        _text(playback_envelope.get("playback_envelope_usable_reason"))
        == "playback_envelope_unaligned"
        and playback_envelope_timebase_aligned
    )
    playback_envelope_usable = bool(
        playback_envelope_available
        and playback_envelope_backend_usable_allowed
        and playback_envelope_sample_count > 0
        and not playback_envelope_stale
        and playback_envelope_has_energy
        and playback_envelope_timebase_aligned
    )
    envelope_timeline_available = bool(
        playback_envelope.get("envelope_timeline_available")
        or len(playback_envelope_timeline_samples) >= 2
    )
    playback_envelope_fallback_reason = _text(
        playback_envelope.get("envelope_disabled_reason")
        or playback_envelope.get("playback_envelope_fallback_reason")
    )
    if not playback_envelope_fallback_reason and not playback_envelope_usable:
        if not playback_envelope_supported:
            playback_envelope_fallback_reason = "playback_envelope_unsupported"
        elif not playback_envelope_available:
            playback_envelope_fallback_reason = "playback_envelope_unavailable"
        elif playback_envelope_sample_count <= 0:
            playback_envelope_fallback_reason = "playback_envelope_empty"
        elif playback_envelope_stale:
            playback_envelope_fallback_reason = "playback_envelope_stale"
        elif not playback_envelope_timebase_aligned:
            playback_envelope_fallback_reason = "playback_envelope_unaligned"
        elif not playback_envelope_has_energy:
            playback_envelope_fallback_reason = "playback_envelope_zero_energy"
        else:
            playback_envelope_fallback_reason = "playback_envelope_unusable"
    visualizer_source_strategy = _visualizer_source_strategy(
        playback_envelope,
        speaking=state == "speaking",
        envelope_timeline_ready=bool(
            playback_envelope_usable and envelope_timeline_available
        ),
        envelope_unavailable_reason=playback_envelope_fallback_reason,
    )
    visualizer_source_locked = visualizer_source_strategy not in {"", "none", "idle"}
    visualizer_source_switch_count = int(
        _explicit_float(
            playback_envelope.get("visualizer_source_switch_count"),
            playback_envelope.get("visualizerSourceSwitchCount"),
            default=0.0,
            maximum=1_000_000.0,
        )
    )
    pcm_meter_production = bool(
        pcm_meter_present and voice_visual_available and voice_visual_active
    )
    if pcm_meter_present:
        playback_envelope_supported = False
        playback_envelope_available = False
        playback_envelope_usable = False
        playback_envelope_samples = []
        playback_envelope_timeline_samples = []
        playback_envelope_sample_count = 0
        envelope_timeline_available = False
        playback_envelope_timebase_aligned = False
        playback_envelope_alignment_status = "deprecated_pcm_meter_bypass"
        playback_envelope_alignment_error_ms = None
        playback_envelope_alignment_delta_ms = None
        playback_envelope_fallback_reason = (
            voice_visual_disabled_reason
            or "deprecated_envelope_timeline_bypassed"
        )
        visualizer_source_strategy = "pcm_stream_meter"
        visualizer_source_locked = bool(voice_visual_active or voice_visual_available)
        visualizer_source_switch_count = 0
    if state == "speaking" and pcm_meter_production:
        envelope = synthetic_voice_audio_envelope(
            level=voice_visual_energy,
            source="pcm_stream_meter",
            previous=envelope,
            update_hz=voice_visual_sample_rate_hz or 60,
        )
    elif state == "speaking" and playback_envelope_usable:
        envelope = synthetic_voice_audio_envelope(
            level=playback_envelope_energy,
            source="playback_pcm",
            previous=envelope,
            update_hz=playback_envelope_sample_rate_hz or 60,
        )
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
        or (voice_visual_source if pcm_meter_present else None)
        or envelope.source
    )
    audio_reactive = bool(
        explicit.get(
            "audio_reactive_available",
            voice_visual_available if pcm_meter_present else envelope.audio_reactive_available,
        )
    ) and audio_source not in {"synthetic_fallback_envelope", "unavailable"}
    speaking_visual_active = bool(
        state == "speaking"
        and not _truthy(_dict(voice.get("interruption")).get("spoken_output_muted"))
    )
    if "speaking_visual_active" in explicit:
        speaking_visual_active = bool(explicit.get("speaking_visual_active"))
    if state in {"muted", "interrupted", "blocked", "error", "preparing_speech"}:
        speaking_visual_active = False
    anchor_uses_playback_envelope = bool(
        speaking_visual_active
        and playback_envelope_usable
        and visualizer_source_strategy == "playback_envelope_timeline"
        and not pcm_meter_present
    )
    if not playback_envelope_fallback_reason and speaking_visual_active and not anchor_uses_playback_envelope:
        if not playback_envelope_supported:
            playback_envelope_fallback_reason = "playback_envelope_unsupported"
        elif not playback_envelope_available:
            playback_envelope_fallback_reason = "playback_envelope_unavailable"
        elif playback_envelope_sample_count <= 0:
            playback_envelope_fallback_reason = "playback_envelope_empty"
        elif playback_envelope_stale:
            playback_envelope_fallback_reason = "playback_envelope_stale"
        elif not playback_envelope_timebase_aligned:
            playback_envelope_fallback_reason = "playback_envelope_unaligned"
        elif not playback_envelope_has_energy:
            playback_envelope_fallback_reason = "playback_envelope_zero_energy"
        else:
            playback_envelope_fallback_reason = "playback_envelope_unusable"
    if speaking_visual_active and pcm_meter_present:
        speaking_visual_sync_mode = (
            "pcm_stream_meter" if pcm_meter_production else "procedural_fallback"
        )
    else:
        speaking_visual_sync_mode = (
            "playback_envelope"
            if anchor_uses_playback_envelope
            else "procedural_fallback"
            if speaking_visual_active
            else "idle"
        )
    procedural_fallback_active = bool(
        speaking_visual_active
        and not anchor_uses_playback_envelope
        and not pcm_meter_production
    )
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
        "playback_envelope_supported": bool(playback_envelope_supported),
        "playback_envelope_available": bool(playback_envelope_available),
        "playback_envelope_usable": bool(playback_envelope_usable),
        "playback_envelope_source": playback_envelope_source,
        "playback_id": playback_envelope.get("playback_id")
        or _dict(voice.get("playback")).get("active_playback_id"),
        "active_playback_id": _dict(voice.get("playback")).get("active_playback_id"),
        "active_playback_stream_id": _dict(voice.get("playback")).get(
            "active_playback_stream_id"
        ),
        "playback_envelope_energy": _round(playback_envelope_energy),
        "playback_envelope_sample_rate_hz": int(playback_envelope_sample_rate_hz),
        "playback_envelope_latency_ms": int(playback_envelope_latency_ms),
        "estimated_output_latency_ms": int(playback_envelope_latency_ms),
        "envelope_visual_offset_ms": int(envelope_visual_offset_ms),
        "playback_envelope_visual_offset_ms": int(envelope_visual_offset_ms),
        "playback_visual_time_ms": (
            None
            if playback_visual_time_ms is None
            else int(round(playback_visual_time_ms))
        ),
        "playback_envelope_time_offset_applied_ms": (
            None
            if playback_envelope_time_offset_applied_ms is None
            else int(round(playback_envelope_time_offset_applied_ms))
        ),
        "playback_envelope_sync_enabled": bool(playback_envelope_sync_enabled),
        "envelope_sync_calibration_version": envelope_sync_calibration_version,
        "envelope_sync_debug_show_sync": bool(envelope_sync_debug_show_sync),
        "playback_envelope_sample_age_ms": playback_envelope_sample_age_ms,
        "playback_envelope_sample_count": int(playback_envelope_sample_count),
        "playback_envelope_window_mode": playback_envelope_window_mode,
        "playback_envelope_query_time_ms": playback_envelope_query_time_ms,
        "playback_envelope_latest_time_ms": playback_envelope.get(
            "latest_voice_energy_time_ms"
        ),
        "playback_envelope_timebase_aligned": bool(
            playback_envelope_timebase_aligned
        ),
        "playback_envelope_alignment_error_ms": playback_envelope_alignment_error_ms,
        "playback_envelope_alignment_delta_ms": playback_envelope_alignment_delta_ms,
        "playback_envelope_alignment_tolerance_ms": computed_alignment_tolerance_ms,
        "playback_envelope_alignment_status": playback_envelope_alignment_status,
        "playback_envelope_usable_reason": (
            "playback_envelope_usable"
            if playback_envelope_usable
            else playback_envelope_fallback_reason or "playback_envelope_unusable"
        ),
        "playback_envelope_samples_recent": playback_envelope_samples,
        "envelope_timeline_samples": playback_envelope_timeline_samples,
        "envelopeTimelineSamples": playback_envelope_timeline_samples,
        "envelope_timeline_available": bool(envelope_timeline_available),
        "envelopeTimelineAvailable": bool(envelope_timeline_available),
        "envelope_timeline_sample_rate_hz": int(
            _explicit_float(
                playback_envelope.get("envelope_timeline_sample_rate_hz"),
                playback_envelope.get("envelopeTimelineSampleRateHz"),
                playback_envelope.get("envelope_sample_rate_hz"),
                playback_envelope.get("playback_envelope_sample_rate_hz"),
                default=float(playback_envelope_sample_rate_hz),
                maximum=240.0,
            )
        ),
        "envelope_timeline_sample_count": int(
            _explicit_float(
                playback_envelope.get("envelope_timeline_sample_count"),
                playback_envelope.get("envelopeTimelineSampleCount"),
                default=float(len(playback_envelope_timeline_samples)),
                maximum=1_000_000.0,
            )
        ),
        "playback_envelope_samples_dropped": int(
            _explicit_float(
                playback_envelope.get("envelope_samples_dropped"),
                playback_envelope.get("samples_dropped"),
                default=0.0,
                maximum=1_000_000.0,
            )
        ),
        "anchor_uses_playback_envelope": bool(anchor_uses_playback_envelope),
        "procedural_fallback_active": procedural_fallback_active,
        "speaking_visual_sync_mode": speaking_visual_sync_mode,
        "visualizer_source_strategy": visualizer_source_strategy,
        "visualizerSourceStrategy": visualizer_source_strategy,
        "visualizer_source_locked": bool(visualizer_source_locked),
        "visualizerSourceLocked": bool(visualizer_source_locked),
        "visualizer_source_playback_id": playback_envelope.get("playback_id")
        or voice_visual_playback_id
        or _dict(voice.get("playback")).get("active_playback_id"),
        "visualizerSourcePlaybackId": playback_envelope.get("playback_id")
        or voice_visual_playback_id
        or _dict(voice.get("playback")).get("active_playback_id"),
        "visualizer_source_switch_count": int(visualizer_source_switch_count),
        "visualizerSourceSwitchCount": int(visualizer_source_switch_count),
        "visualizer_source_switching_disabled": True,
        "visualizerSourceSwitchingDisabled": True,
        "timeline_visualizer_version": "Voice-L0.6",
        "timelineVisualizerVersion": "Voice-L0.6",
        "envelope_timeline_ready_at_playback_start": bool(
            visualizer_source_strategy == "playback_envelope_timeline"
            and playback_envelope_usable
            and envelope_timeline_available
        ),
        "envelopeTimelineReadyAtPlaybackStart": bool(
            visualizer_source_strategy == "playback_envelope_timeline"
            and playback_envelope_usable
            and envelope_timeline_available
        ),
        "requested_anchor_visualizer_mode": _text(
            playback_envelope.get("requested_anchor_visualizer_mode")
            or playback_envelope.get("requestedAnchorVisualizerMode")
            or _forced_anchor_visualizer_mode()
            or "auto"
        ),
        "requestedAnchorVisualizerMode": _text(
            playback_envelope.get("requestedAnchorVisualizerMode")
            or playback_envelope.get("requested_anchor_visualizer_mode")
            or _forced_anchor_visualizer_mode()
            or "auto"
        ),
        "effective_anchor_visualizer_mode": _text(
            playback_envelope.get("effective_anchor_visualizer_mode")
            or playback_envelope.get("effectiveAnchorVisualizerMode")
            or _forced_anchor_visualizer_mode()
            or "auto"
        ),
        "effectiveAnchorVisualizerMode": _text(
            playback_envelope.get("effectiveAnchorVisualizerMode")
            or playback_envelope.get("effective_anchor_visualizer_mode")
            or _forced_anchor_visualizer_mode()
            or "auto"
        ),
        "forced_visualizer_mode_honored": bool(
            _truthy(playback_envelope.get("forced_visualizer_mode_honored"))
            or _truthy(playback_envelope.get("forcedVisualizerModeHonored"))
            or _forced_anchor_visualizer_strategy()
            and visualizer_source_strategy == _forced_anchor_visualizer_strategy()
        ),
        "forcedVisualizerModeHonored": bool(
            _truthy(playback_envelope.get("forcedVisualizerModeHonored"))
            or _truthy(playback_envelope.get("forced_visualizer_mode_honored"))
            or _forced_anchor_visualizer_strategy()
            and visualizer_source_strategy == _forced_anchor_visualizer_strategy()
        ),
        "forced_visualizer_mode_unavailable_reason": (
            _text(
                playback_envelope.get("forced_visualizer_mode_unavailable_reason")
                or playback_envelope.get("forcedVisualizerModeUnavailableReason")
            )
            or (
                playback_envelope_fallback_reason
                if _forced_anchor_visualizer_strategy() == "playback_envelope_timeline"
                and not (playback_envelope_usable and envelope_timeline_available)
                else ""
            )
        ),
        "forcedVisualizerModeUnavailableReason": (
            _text(
                playback_envelope.get("forcedVisualizerModeUnavailableReason")
                or playback_envelope.get("forced_visualizer_mode_unavailable_reason")
            )
            or (
                playback_envelope_fallback_reason
                if _forced_anchor_visualizer_strategy() == "playback_envelope_timeline"
                and not (playback_envelope_usable and envelope_timeline_available)
                else ""
            )
        ),
        "visualizer_strategy_selected_by": _text(
            playback_envelope.get("visualizer_strategy_selected_by")
            or playback_envelope.get("visualizerStrategySelectedBy")
            or ("pcm_stream_meter" if pcm_meter_present else "")
            or ("config" if _forced_anchor_visualizer_strategy() else "service_auto")
        ),
        "visualizerStrategySelectedBy": _text(
            playback_envelope.get("visualizerStrategySelectedBy")
            or playback_envelope.get("visualizer_strategy_selected_by")
            or ("pcm_stream_meter" if pcm_meter_present else "")
            or ("config" if _forced_anchor_visualizer_strategy() else "service_auto")
        ),
        "envelope_interpolation_active": bool(
            anchor_uses_playback_envelope and len(playback_envelope_samples) >= 2
        ),
        "envelope_fallback_reason": playback_envelope_fallback_reason or None,
        "envelope_to_visual_latency_estimate_ms": int(playback_envelope_latency_ms),
        "first_audio_started": bool(
            explicit.get("first_audio_started")
            or _dict(voice.get("playback")).get("first_audio_started")
        ),
        "playback_preroll_active": bool(
            explicit.get("playback_preroll_active")
            or _dict(voice.get("playback")).get("playback_preroll_active")
        ),
        "playback_startup_stable": bool(
            explicit.get("playback_startup_stable")
            or _dict(voice.get("playback")).get("playback_startup_stable")
        ),
        "playback_buffered_ms": int(
            _float(
                explicit.get("playback_buffered_ms"),
                _dict(voice.get("playback")).get("playback_buffered_ms", 0),
            )
        ),
        "streaming_tts_active": bool(
            explicit.get("streaming_tts_active") or _streaming_tts_active(voice)
        ),
        "live_playback_active": bool(
            explicit.get("live_playback_active") or _playback_active(voice)
        ),
        "visualizer_update_hz": int(
            explicit.get("visualizer_update_hz")
            or voice_visual_sample_rate_hz
            or envelope.update_hz
            or 30
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
        "voice_visual_active": bool(voice_visual_active and speaking_visual_active),
        "voice_visual_available": bool(voice_visual_available),
        "voice_visual_energy": _round(voice_visual_energy),
        "voice_visual_source": voice_visual_source,
        "voice_visual_energy_source": voice_visual_source,
        "voice_visual_playback_id": voice_visual_playback_id,
        "voice_visual_sample_rate_hz": int(voice_visual_sample_rate_hz),
        "voice_visual_started_at_ms": voice_visual_started_at_ms,
        "voice_visual_latest_age_ms": voice_visual_latest_age_ms,
        "voice_visual_disabled_reason": voice_visual_disabled_reason or None,
        "raw_audio_present": False,
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


def _select_playback_envelope_payload(voice: dict[str, Any]) -> dict[str, Any]:
    playback = _dict(voice.get("playback"))
    explicit = _dict(voice.get("voice_anchor"))

    def first_present(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    for candidate in (
        explicit.get("playback_envelope"),
        voice.get("playback_envelope"),
        playback.get("playback_envelope"),
        voice.get("playback_envelope_payload"),
        playback.get("playback_envelope_payload"),
    ):
        payload = _dict(candidate)
        if payload:
            return payload
    source = _text(
        explicit.get("playback_envelope_source")
        or voice.get("playback_envelope_source")
        or playback.get("playback_envelope_source")
    )
    if not source:
        return {}
    return {
        "playback_id": first_present(
            explicit.get("playback_id"),
            voice.get("playback_id"),
            playback.get("active_playback_id"),
        ),
        "envelope_supported": bool(
            explicit.get(
                "playback_envelope_supported",
                voice.get(
                    "playback_envelope_supported",
                    playback.get("playback_envelope_supported", False),
                ),
            )
        ),
        "envelope_available": bool(
            explicit.get(
                "playback_envelope_available",
                voice.get(
                    "playback_envelope_available",
                    playback.get("playback_envelope_available", False),
                ),
            )
        ),
        "envelope_source": source,
        "envelope_sample_rate_hz": first_present(
            explicit.get("playback_envelope_sample_rate_hz"),
            voice.get("playback_envelope_sample_rate_hz"),
            playback.get("playback_envelope_sample_rate_hz"),
        ),
        "latest_voice_energy": first_present(
            explicit.get("playback_envelope_energy"),
            voice.get("playback_envelope_energy"),
            playback.get("playback_envelope_energy"),
        ),
        "latest_voice_energy_time_ms": first_present(
            explicit.get("playback_envelope_latest_time_ms"),
            explicit.get("latest_voice_energy_time_ms"),
            voice.get("playback_envelope_latest_time_ms"),
            voice.get("latest_voice_energy_time_ms"),
            playback.get("playback_envelope_latest_time_ms"),
            playback.get("latest_voice_energy_time_ms"),
        ),
        "estimated_output_latency_ms": first_present(
            explicit.get("estimated_output_latency_ms"),
            explicit.get("playback_envelope_latency_ms"),
            explicit.get("playback_envelope_estimated_output_latency_ms"),
            voice.get("estimated_output_latency_ms"),
            voice.get("playback_envelope_latency_ms"),
            voice.get("playback_envelope_estimated_output_latency_ms"),
            playback.get("estimated_output_latency_ms"),
            playback.get("playback_envelope_latency_ms"),
            playback.get("playback_envelope_estimated_output_latency_ms"),
        ),
        "envelope_visual_offset_ms": first_present(
            explicit.get("envelope_visual_offset_ms"),
            explicit.get("playback_envelope_visual_offset_ms"),
            voice.get("envelope_visual_offset_ms"),
            voice.get("playback_envelope_visual_offset_ms"),
            playback.get("envelope_visual_offset_ms"),
            playback.get("playback_envelope_visual_offset_ms"),
        ),
        "playback_envelope_visual_offset_ms": first_present(
            explicit.get("playback_envelope_visual_offset_ms"),
            explicit.get("envelope_visual_offset_ms"),
            voice.get("playback_envelope_visual_offset_ms"),
            voice.get("envelope_visual_offset_ms"),
            playback.get("playback_envelope_visual_offset_ms"),
            playback.get("envelope_visual_offset_ms"),
        ),
        "playback_visual_time_ms": first_present(
            explicit.get("playback_visual_time_ms"),
            voice.get("playback_visual_time_ms"),
            playback.get("playback_visual_time_ms"),
        ),
        "playback_envelope_time_offset_applied_ms": first_present(
            explicit.get("playback_envelope_time_offset_applied_ms"),
            voice.get("playback_envelope_time_offset_applied_ms"),
            playback.get("playback_envelope_time_offset_applied_ms"),
        ),
        "playback_envelope_sync_enabled": first_present(
            explicit.get("playback_envelope_sync_enabled"),
            voice.get("playback_envelope_sync_enabled"),
            playback.get("playback_envelope_sync_enabled"),
        ),
        "envelope_sync_calibration_version": first_present(
            explicit.get("envelope_sync_calibration_version"),
            voice.get("envelope_sync_calibration_version"),
            playback.get("envelope_sync_calibration_version"),
        ),
        "envelope_sync_debug_show_sync": first_present(
            explicit.get("envelope_sync_debug_show_sync"),
            voice.get("envelope_sync_debug_show_sync"),
            playback.get("envelope_sync_debug_show_sync"),
        ),
        "playback_envelope_usable": first_present(
            explicit.get("playback_envelope_usable"),
            voice.get("playback_envelope_usable"),
            playback.get("playback_envelope_usable"),
        ),
        "playback_envelope_timebase_aligned": first_present(
            explicit.get("playback_envelope_timebase_aligned"),
            voice.get("playback_envelope_timebase_aligned"),
            playback.get("playback_envelope_timebase_aligned"),
        ),
        "playback_envelope_alignment_error_ms": first_present(
            explicit.get("playback_envelope_alignment_error_ms"),
            voice.get("playback_envelope_alignment_error_ms"),
            playback.get("playback_envelope_alignment_error_ms"),
        ),
        "playback_envelope_alignment_delta_ms": first_present(
            explicit.get("playback_envelope_alignment_delta_ms"),
            voice.get("playback_envelope_alignment_delta_ms"),
            playback.get("playback_envelope_alignment_delta_ms"),
        ),
        "playback_envelope_alignment_tolerance_ms": first_present(
            explicit.get("playback_envelope_alignment_tolerance_ms"),
            voice.get("playback_envelope_alignment_tolerance_ms"),
            playback.get("playback_envelope_alignment_tolerance_ms"),
        ),
        "playback_envelope_alignment_status": first_present(
            explicit.get("playback_envelope_alignment_status"),
            voice.get("playback_envelope_alignment_status"),
            playback.get("playback_envelope_alignment_status"),
        ),
        "playback_envelope_usable_reason": first_present(
            explicit.get("playback_envelope_usable_reason"),
            voice.get("playback_envelope_usable_reason"),
            playback.get("playback_envelope_usable_reason"),
        ),
        "playback_envelope_sample_age_ms": first_present(
            explicit.get("playback_envelope_sample_age_ms"),
            voice.get("playback_envelope_sample_age_ms"),
            playback.get("playback_envelope_sample_age_ms"),
        ),
        "playback_envelope_window_mode": first_present(
            explicit.get("playback_envelope_window_mode"),
            voice.get("playback_envelope_window_mode"),
            playback.get("playback_envelope_window_mode"),
        ),
        "playback_envelope_query_time_ms": first_present(
            explicit.get("playback_envelope_query_time_ms"),
            voice.get("playback_envelope_query_time_ms"),
            playback.get("playback_envelope_query_time_ms"),
        ),
        "envelope_timeline_samples": first_present(
            explicit.get("envelope_timeline_samples"),
            explicit.get("envelopeTimelineSamples"),
            voice.get("envelope_timeline_samples"),
            voice.get("envelopeTimelineSamples"),
            playback.get("envelope_timeline_samples"),
            playback.get("envelopeTimelineSamples"),
        ),
        "envelope_timeline_available": first_present(
            explicit.get("envelope_timeline_available"),
            explicit.get("envelopeTimelineAvailable"),
            voice.get("envelope_timeline_available"),
            voice.get("envelopeTimelineAvailable"),
            playback.get("envelope_timeline_available"),
            playback.get("envelopeTimelineAvailable"),
        ),
        "envelope_timeline_sample_rate_hz": first_present(
            explicit.get("envelope_timeline_sample_rate_hz"),
            explicit.get("envelopeTimelineSampleRateHz"),
            voice.get("envelope_timeline_sample_rate_hz"),
            voice.get("envelopeTimelineSampleRateHz"),
            playback.get("envelope_timeline_sample_rate_hz"),
            playback.get("envelopeTimelineSampleRateHz"),
        ),
        "envelope_timeline_sample_count": first_present(
            explicit.get("envelope_timeline_sample_count"),
            explicit.get("envelopeTimelineSampleCount"),
            voice.get("envelope_timeline_sample_count"),
            voice.get("envelopeTimelineSampleCount"),
            playback.get("envelope_timeline_sample_count"),
            playback.get("envelopeTimelineSampleCount"),
        ),
        "envelope_timeline_ready_at_playback_start": first_present(
            explicit.get("envelope_timeline_ready_at_playback_start"),
            explicit.get("envelopeTimelineReadyAtPlaybackStart"),
            voice.get("envelope_timeline_ready_at_playback_start"),
            voice.get("envelopeTimelineReadyAtPlaybackStart"),
            playback.get("envelope_timeline_ready_at_playback_start"),
            playback.get("envelopeTimelineReadyAtPlaybackStart"),
        ),
        "visualizer_source_strategy": first_present(
            explicit.get("visualizer_source_strategy"),
            explicit.get("visualizerSourceStrategy"),
            voice.get("visualizer_source_strategy"),
            voice.get("visualizerSourceStrategy"),
            playback.get("visualizer_source_strategy"),
            playback.get("visualizerSourceStrategy"),
        ),
        "visualizer_source_locked": first_present(
            explicit.get("visualizer_source_locked"),
            explicit.get("visualizerSourceLocked"),
            voice.get("visualizer_source_locked"),
            voice.get("visualizerSourceLocked"),
            playback.get("visualizer_source_locked"),
            playback.get("visualizerSourceLocked"),
        ),
        "visualizer_source_playback_id": first_present(
            explicit.get("visualizer_source_playback_id"),
            explicit.get("visualizerSourcePlaybackId"),
            voice.get("visualizer_source_playback_id"),
            voice.get("visualizerSourcePlaybackId"),
            playback.get("visualizer_source_playback_id"),
            playback.get("visualizerSourcePlaybackId"),
        ),
        "visualizer_source_switch_count": first_present(
            explicit.get("visualizer_source_switch_count"),
            explicit.get("visualizerSourceSwitchCount"),
            voice.get("visualizer_source_switch_count"),
            voice.get("visualizerSourceSwitchCount"),
            playback.get("visualizer_source_switch_count"),
            playback.get("visualizerSourceSwitchCount"),
        ),
        "visualizer_source_switching_disabled": first_present(
            explicit.get("visualizer_source_switching_disabled"),
            explicit.get("visualizerSourceSwitchingDisabled"),
            voice.get("visualizer_source_switching_disabled"),
            voice.get("visualizerSourceSwitchingDisabled"),
            playback.get("visualizer_source_switching_disabled"),
            playback.get("visualizerSourceSwitchingDisabled"),
        ),
        "requested_anchor_visualizer_mode": first_present(
            explicit.get("requested_anchor_visualizer_mode"),
            explicit.get("requestedAnchorVisualizerMode"),
            voice.get("requested_anchor_visualizer_mode"),
            voice.get("requestedAnchorVisualizerMode"),
            playback.get("requested_anchor_visualizer_mode"),
            playback.get("requestedAnchorVisualizerMode"),
        ),
        "effective_anchor_visualizer_mode": first_present(
            explicit.get("effective_anchor_visualizer_mode"),
            explicit.get("effectiveAnchorVisualizerMode"),
            voice.get("effective_anchor_visualizer_mode"),
            voice.get("effectiveAnchorVisualizerMode"),
            playback.get("effective_anchor_visualizer_mode"),
            playback.get("effectiveAnchorVisualizerMode"),
        ),
        "forced_visualizer_mode_honored": first_present(
            explicit.get("forced_visualizer_mode_honored"),
            explicit.get("forcedVisualizerModeHonored"),
            voice.get("forced_visualizer_mode_honored"),
            voice.get("forcedVisualizerModeHonored"),
            playback.get("forced_visualizer_mode_honored"),
            playback.get("forcedVisualizerModeHonored"),
        ),
        "forced_visualizer_mode_unavailable_reason": first_present(
            explicit.get("forced_visualizer_mode_unavailable_reason"),
            explicit.get("forcedVisualizerModeUnavailableReason"),
            voice.get("forced_visualizer_mode_unavailable_reason"),
            voice.get("forcedVisualizerModeUnavailableReason"),
            playback.get("forced_visualizer_mode_unavailable_reason"),
            playback.get("forcedVisualizerModeUnavailableReason"),
        ),
        "visualizer_strategy_selected_by": first_present(
            explicit.get("visualizer_strategy_selected_by"),
            explicit.get("visualizerStrategySelectedBy"),
            voice.get("visualizer_strategy_selected_by"),
            voice.get("visualizerStrategySelectedBy"),
            playback.get("visualizer_strategy_selected_by"),
            playback.get("visualizerStrategySelectedBy"),
        ),
        "envelope_disabled_reason": first_present(
            explicit.get("playback_envelope_fallback_reason"),
            voice.get("playback_envelope_fallback_reason"),
            playback.get("playback_envelope_fallback_reason"),
        ),
        "envelope_samples_recent": first_present(
            explicit.get("playback_envelope_samples_recent"),
            voice.get("playback_envelope_samples_recent"),
            playback.get("playback_envelope_samples_recent"),
            [],
        ),
        "raw_audio_present": False,
    }


def _select_voice_visual_payload(voice: dict[str, Any]) -> dict[str, Any]:
    playback = _dict(voice.get("playback"))
    explicit = _dict(voice.get("voice_anchor"))
    visualizer = _dict(voice.get("voice_visualizer"))
    nested_visual = _dict(voice.get("voice_visual"))
    playback_visual = _dict(playback.get("voice_visual"))

    def first_present(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    return {
        "voice_visual_active": first_present(
            explicit.get("voice_visual_active"),
            voice.get("voice_visual_active"),
            playback.get("voice_visual_active"),
            nested_visual.get("voice_visual_active"),
            playback_visual.get("voice_visual_active"),
            visualizer.get("voice_visual_active"),
            visualizer.get("active"),
        ),
        "voice_visual_available": first_present(
            explicit.get("voice_visual_available"),
            voice.get("voice_visual_available"),
            playback.get("voice_visual_available"),
            nested_visual.get("voice_visual_available"),
            playback_visual.get("voice_visual_available"),
            visualizer.get("voice_visual_available"),
            visualizer.get("available"),
        ),
        "voice_visual_energy": first_present(
            explicit.get("voice_visual_energy"),
            voice.get("voice_visual_energy"),
            playback.get("voice_visual_energy"),
            nested_visual.get("voice_visual_energy"),
            playback_visual.get("voice_visual_energy"),
            visualizer.get("voice_visual_energy"),
            visualizer.get("energy"),
        ),
        "voice_visual_source": first_present(
            explicit.get("voice_visual_source"),
            explicit.get("voice_visual_energy_source"),
            voice.get("voice_visual_source"),
            voice.get("voice_visual_energy_source"),
            playback.get("voice_visual_source"),
            playback.get("voice_visual_energy_source"),
            nested_visual.get("voice_visual_source"),
            nested_visual.get("voice_visual_energy_source"),
            playback_visual.get("voice_visual_source"),
            playback_visual.get("voice_visual_energy_source"),
            visualizer.get("voice_visual_source"),
            visualizer.get("voice_visual_energy_source"),
            visualizer.get("source"),
        ),
        "voice_visual_energy_source": first_present(
            explicit.get("voice_visual_energy_source"),
            voice.get("voice_visual_energy_source"),
            playback.get("voice_visual_energy_source"),
            nested_visual.get("voice_visual_energy_source"),
            playback_visual.get("voice_visual_energy_source"),
            visualizer.get("voice_visual_energy_source"),
            visualizer.get("source"),
        ),
        "voice_visual_playback_id": first_present(
            explicit.get("voice_visual_playback_id"),
            voice.get("voice_visual_playback_id"),
            playback.get("voice_visual_playback_id"),
            nested_visual.get("voice_visual_playback_id"),
            playback_visual.get("voice_visual_playback_id"),
            visualizer.get("voice_visual_playback_id"),
            explicit.get("playback_id"),
            voice.get("playback_id"),
            playback.get("active_playback_id"),
        ),
        "voice_visual_sample_rate_hz": first_present(
            explicit.get("voice_visual_sample_rate_hz"),
            voice.get("voice_visual_sample_rate_hz"),
            playback.get("voice_visual_sample_rate_hz"),
            nested_visual.get("voice_visual_sample_rate_hz"),
            playback_visual.get("voice_visual_sample_rate_hz"),
            visualizer.get("voice_visual_sample_rate_hz"),
            visualizer.get("sample_rate_hz"),
        ),
        "voice_visual_started_at_ms": first_present(
            explicit.get("voice_visual_started_at_ms"),
            voice.get("voice_visual_started_at_ms"),
            playback.get("voice_visual_started_at_ms"),
            nested_visual.get("voice_visual_started_at_ms"),
            playback_visual.get("voice_visual_started_at_ms"),
            visualizer.get("voice_visual_started_at_ms"),
        ),
        "voice_visual_latest_age_ms": first_present(
            explicit.get("voice_visual_latest_age_ms"),
            voice.get("voice_visual_latest_age_ms"),
            playback.get("voice_visual_latest_age_ms"),
            nested_visual.get("voice_visual_latest_age_ms"),
            playback_visual.get("voice_visual_latest_age_ms"),
            visualizer.get("voice_visual_latest_age_ms"),
        ),
        "voice_visual_disabled_reason": first_present(
            explicit.get("voice_visual_disabled_reason"),
            voice.get("voice_visual_disabled_reason"),
            playback.get("voice_visual_disabled_reason"),
            nested_visual.get("voice_visual_disabled_reason"),
            playback_visual.get("voice_visual_disabled_reason"),
            visualizer.get("voice_visual_disabled_reason"),
            visualizer.get("disabled_reason"),
        ),
    }


def _playback_envelope_samples(payload: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    samples = payload.get("envelope_samples_recent") or payload.get(
        "playback_envelope_samples_recent"
    )
    if not isinstance(samples, list):
        return []
    bounded_limit = max(0, int(limit or 0))
    sanitized: list[dict[str, Any]] = []
    for sample in samples:
        item = _dict(sample)
        if not item:
            continue
        sanitized.append(
            {
                "sample_time_ms": int(_float(item.get("sample_time_ms"), 0)),
                "monotonic_time_ms": int(_float(item.get("monotonic_time_ms"), 0)),
                "rms": _round(_float(item.get("rms"), 0.0)),
                "peak": _round(_float(item.get("peak"), 0.0)),
                "energy": _round(_float(item.get("energy"), 0.0)),
                "smoothed_energy": _round(
                    _explicit_float(
                        item.get("smoothed_energy"),
                        item.get("energy"),
                        default=0.0,
                    )
                ),
                "sample_rate": int(_float(item.get("sample_rate"), 0)),
                "channels": int(_float(item.get("channels"), 0)),
                "source": _text(item.get("source") or "pcm_playback"),
                "valid": bool(item.get("valid", True)),
                "raw_audio_present": False,
            }
        )
    if bounded_limit <= 0 or len(sanitized) <= bounded_limit:
        return sanitized[-bounded_limit:] if bounded_limit > 0 else []
    window_mode = _text(payload.get("playback_envelope_window_mode") or "latest")
    if window_mode == "playback_time":
        try:
            query = float(payload.get("playback_envelope_query_time_ms"))
        except (TypeError, ValueError):
            query = float("nan")
        if math.isfinite(query):
            before_index = 0
            for index, sample in enumerate(sanitized):
                if sample["sample_time_ms"] <= query:
                    before_index = index
                else:
                    break
            half_before = max(1, bounded_limit // 2)
            start = max(0, before_index - half_before + 1)
            end = min(len(sanitized), start + bounded_limit)
            start = max(0, end - bounded_limit)
            return sanitized[start:end]
    return sanitized[-bounded_limit:]


def _playback_envelope_timeline_samples(
    payload: dict[str, Any], *, limit: int = 180
) -> list[dict[str, Any]]:
    source = (
        payload.get("envelope_timeline_samples")
        or payload.get("envelopeTimelineSamples")
        or payload.get("playback_envelope_timeline_samples")
        or []
    )
    timeline: list[dict[str, Any]] = []
    if isinstance(source, list):
        for sample in source:
            item = _dict(sample)
            if not item:
                continue
            t_ms = _optional_float(item.get("t_ms"), item.get("sample_time_ms"))
            energy = _optional_float(item.get("energy"), item.get("smoothed_energy"))
            if t_ms is None or energy is None:
                continue
            timeline.append({"t_ms": int(max(0, round(t_ms))), "energy": _round(energy)})
    if not timeline:
        for sample in _playback_envelope_samples(payload, limit=limit):
            t_ms = _optional_float(sample.get("sample_time_ms"), sample.get("t_ms"))
            energy = _optional_float(sample.get("smoothed_energy"), sample.get("energy"))
            if t_ms is None or energy is None:
                continue
            timeline.append({"t_ms": int(max(0, round(t_ms))), "energy": _round(energy)})
    timeline.sort(key=lambda sample: sample["t_ms"])
    bounded_limit = max(0, int(limit or 0))
    if bounded_limit and len(timeline) > bounded_limit:
        return timeline[-bounded_limit:]
    return timeline


def _playback_envelope_samples_from_timeline(
    timeline: list[dict[str, Any]],
    *,
    sample_rate: int = 0,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for sample in timeline:
        t_ms = _optional_float(sample.get("t_ms"), sample.get("sample_time_ms"))
        energy = _optional_float(sample.get("energy"), sample.get("smoothed_energy"))
        if t_ms is None or energy is None:
            continue
        energy = _clamp(energy)
        samples.append(
            {
                "sample_time_ms": int(max(0, round(t_ms))),
                "monotonic_time_ms": 0,
                "rms": _round(energy),
                "peak": _round(energy),
                "energy": _round(energy),
                "smoothed_energy": _round(energy),
                "sample_rate": int(sample_rate or 0),
                "channels": 0,
                "source": "pcm_playback",
                "valid": True,
                "raw_audio_present": False,
            }
        )
    samples.sort(key=lambda item: item["sample_time_ms"])
    return samples


def _playback_envelope_energy_near_query(
    samples: list[dict[str, Any]],
    *,
    query_time_ms: Any,
) -> float:
    if not samples:
        return 0.0
    query = _optional_float(query_time_ms)
    selected: dict[str, Any] | None = None
    if query is not None and math.isfinite(query):
        selected = min(
            samples,
            key=lambda sample: abs(
                _float(sample.get("sample_time_ms"), sample.get("t_ms")) - query
            ),
        )
    if selected is None:
        selected = samples[-1]
    return _clamp(
        _explicit_float(
            selected.get("smoothed_energy"),
            selected.get("energy"),
            default=0.0,
        )
    )


def _visualizer_source_strategy(
    payload: dict[str, Any],
    *,
    speaking: bool,
    envelope_timeline_ready: bool,
    envelope_unavailable_reason: str = "",
) -> str:
    forced_strategy = _forced_anchor_visualizer_strategy()
    if forced_strategy:
        return forced_strategy
    explicit = _text(
        payload.get("visualizer_source_strategy")
        or payload.get("visualizerSourceStrategy")
    )
    aliases = {
        "pcm_stream_meter": "pcm_stream_meter",
        "playback_envelope": "playback_envelope_timeline",
        "playback_pcm": "playback_envelope_timeline",
        "pcm": "playback_envelope_timeline",
        "procedural": "procedural_speaking",
        "procedural_fallback": "procedural_speaking",
        "stormhelm_playback_meter": "procedural_speaking",
        "stormhelm playback meter": "procedural_speaking",
    }
    normalized = aliases.get(explicit, explicit)
    if normalized in {"pcm_stream_meter", "playback_envelope_timeline", "procedural_speaking", "off", "constant_test_wave"}:
        return normalized
    if not speaking:
        return "idle"
    return "playback_envelope_timeline" if envelope_timeline_ready else "procedural_speaking"


def _forced_anchor_visualizer_mode() -> str:
    mode = (
        str(os.environ.get(_ANCHOR_VISUALIZER_MODE_ENV, "") or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )
    if mode == "auto":
        return ""
    return mode if mode in _FORCED_ANCHOR_VISUALIZER_STRATEGIES else ""


def _forced_anchor_visualizer_strategy() -> str:
    return _FORCED_ANCHOR_VISUALIZER_STRATEGIES.get(
        _forced_anchor_visualizer_mode(), ""
    )


def _playback_envelope_timebase_alignment(
    samples: list[dict[str, Any]],
    *,
    query_time_ms: Any,
    window_mode: Any,
) -> tuple[bool, int | None, str, int]:
    tolerance_ms = _PLAYBACK_ENVELOPE_ALIGNMENT_TOLERANCE_MS
    if not samples:
        return False, None, "no_samples", tolerance_ms
    if _text(window_mode) != "playback_time":
        return False, None, "not_playback_time", tolerance_ms
    try:
        query = float(query_time_ms)
    except (TypeError, ValueError):
        return False, None, "invalid_query", tolerance_ms
    if not math.isfinite(query):
        return False, None, "invalid_query", tolerance_ms
    sample_times = [
        int(_float(sample.get("sample_time_ms"), 0))
        for sample in samples
        if sample.get("sample_time_ms") is not None
    ]
    if not sample_times:
        return False, None, "no_sample_times", tolerance_ms
    first = min(sample_times)
    last = max(sample_times)
    if first <= query <= last:
        return True, 0, "aligned", tolerance_ms
    if query > last:
        alignment_error = int(round(query - last))
        status = "ahead_clamped" if alignment_error <= tolerance_ms else "ahead"
    else:
        alignment_error = int(round(first - query))
        status = "behind_clamped" if alignment_error <= tolerance_ms else "behind"
    return alignment_error <= tolerance_ms, alignment_error, status, tolerance_ms


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
    active_status = _text(
        playback.get("active_playback_status")
        or playback.get("live_playback_status")
        or playback.get("stream_status")
    )
    return bool(
        _streaming_tts_active(voice)
        or playback.get("first_audio_pending")
        or playback.get("playback_preroll_active")
        or active_status in {"prerolling", "buffering"}
        or _text(_dict(voice.get("tts")).get("last_synthesis_state")) in {"started", "running", "pending"}
    ) and not bool(playback.get("first_audio_started"))


def _playback_active(voice: dict[str, Any]) -> bool:
    playback = _dict(voice.get("playback"))
    active_status = _text(
        playback.get("active_playback_status")
        or playback.get("live_playback_status")
        or playback.get("stream_status")
    )
    if active_status in {"prerolling", "buffering"}:
        return False
    return bool(
        playback.get("playback_streaming_active")
        or active_status in {"started", "playing", "stable"}
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
    meter_source = source in {"pcm_stream_meter", "stormhelm_playback_meter"}
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
