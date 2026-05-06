from __future__ import annotations

import math
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class VoiceVisualMeterFrame:
    playback_id: str | None
    playback_position_ms: int
    duration_ms: int
    rms: float
    peak: float
    energy: float
    sample_rate_hz: int
    sample_time_ms: int | None = None
    playback_clock_position_ms: int | None = None
    visual_offset_ms: int = 0
    source: str = "pcm_stream_meter"
    active: bool = True
    started_at_ms: int | None = None
    latest_age_ms: int | None = None
    timestamp: str = ""

    @property
    def envelope(self) -> Any:
        from stormhelm.core.voice.visualizer import synthetic_voice_audio_envelope

        return synthetic_voice_audio_envelope(
            level=self.energy,
            source=self.source,
            update_hz=self.sample_rate_hz,
        )

    @property
    def visual_drive(self) -> float:
        return self.energy

    def to_payload(self) -> dict[str, Any]:
        return {
            "voice_visual_active": bool(self.active),
            "voice_visual_available": True,
            "voice_visual_energy": round(_clamp(self.energy), 4),
            "voice_visual_source": self.source,
            "voice_visual_energy_source": self.source,
            "voice_visual_playback_id": self.playback_id,
            "voice_visual_sample_rate_hz": int(self.sample_rate_hz),
            "voice_visual_started_at_ms": self.started_at_ms,
            "voice_visual_latest_age_ms": self.latest_age_ms,
            "voice_visual_sample_time_ms": self.sample_time_ms,
            "voice_visual_playback_clock_position_ms": self.playback_clock_position_ms,
            "voice_visual_offset_ms": int(self.visual_offset_ms),
            "voice_visual_disabled_reason": None,
            "playback_id": self.playback_id,
            "playback_position_ms": int(self.playback_position_ms),
            "sample_time_ms": self.sample_time_ms,
            "duration_ms": int(self.duration_ms),
            "rms": round(_clamp(self.rms), 4),
            "peak": round(_clamp(self.peak), 4),
            "energy": round(_clamp(self.energy), 4),
            "source": self.source,
            "timestamp": self.timestamp or _utc_now_iso(),
            "raw_audio_present": False,
            "raw_audio_included": False,
            "raw_audio_logged": False,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_payload()
        payload.update(
            {
                "playback_meter_alignment": "pcm_stream_meter",
                "sample_rate": int(self.sample_rate_hz),
                "valid": True,
            }
        )
        return payload


class VoiceVisualMeter:
    """Small scalar meter for outgoing playback PCM.

    The meter stores only an internal rolling PCM buffer and exposes bounded scalar
    energy frames. Public payloads never contain audio samples or PCM bytes.
    """

    def __init__(
        self,
        *,
        playback_id: str | None = None,
        update_hz: int = 60,
        sample_rate_hz: int = 24000,
        channels: int = 1,
        sample_width_bytes: int = 2,
        window_ms: int | None = None,
        startup_preroll_ms: int = 350,
        attack_ms: int = 60,
        release_ms: int = 160,
        noise_floor: float = 0.015,
        gain: float = 2.0,
        max_startup_wait_ms: int = 800,
        visual_offset_ms: int = 0,
        clock: Any | None = None,
    ) -> None:
        self.playback_id = str(playback_id).strip() if playback_id else None
        self.update_hz = max(1, min(120, int(update_hz or 60)))
        self.sample_rate_hz = max(1, int(sample_rate_hz or 24000))
        self.channels = max(1, int(channels or 1))
        self.sample_width_bytes = max(1, int(sample_width_bytes or 2))
        self.window_ms = max(8, int(window_ms or round(1000 / self.update_hz)))
        self.startup_preroll_ms = max(0, int(startup_preroll_ms or 0))
        self.attack_ms = max(1, int(attack_ms or 60))
        self.release_ms = max(1, int(release_ms or 160))
        self.noise_floor = _clamp(float(noise_floor), 0.0, 0.5)
        self.gain = max(0.01, min(12.0, float(gain or 1.0)))
        self.max_startup_wait_ms = max(0, int(max_startup_wait_ms or 0))
        try:
            offset = int(round(float(visual_offset_ms)))
        except (TypeError, ValueError):
            offset = 0
        self.visual_offset_ms = max(-300, min(300, offset))
        self.clock = clock if callable(clock) else time.perf_counter
        self.source = "pcm_stream_meter"

        self._lock = threading.Lock()
        self._pcm = bytearray()
        self._active = False
        self._started_monotonic: float | None = None
        self._started_at_ms: int | None = None
        self._next_emit_monotonic: float | None = None
        self._last_frame_monotonic: float | None = None
        self._last_sample_monotonic: float | None = None
        self._smoothed_energy: float | None = None
        self._latest_frame: VoiceVisualMeterFrame | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def buffered_duration_ms(self) -> int:
        with self._lock:
            return self._buffered_duration_ms_locked()

    @property
    def latest_energy(self) -> float:
        with self._lock:
            if self._latest_frame is not None:
                return _clamp(self._latest_frame.energy)
            return _clamp(self._smoothed_energy or 0.0)

    def feed_pcm(self, payload: bytes | bytearray | memoryview | None) -> None:
        if not payload:
            return
        data = bytes(payload)
        if not data:
            return
        frame_width = self.channels * self.sample_width_bytes
        if frame_width <= 0:
            return
        trimmed_length = len(data) - (len(data) % frame_width)
        if trimmed_length <= 0:
            return
        with self._lock:
            self._pcm.extend(data[:trimmed_length])
            if not self._active:
                self._prime_latest_frame_locked()

    def feed_preroll_pcm(self, payload: bytes | bytearray | memoryview | None) -> None:
        self.feed_pcm(payload)

    def start_playback(self, *, start_monotonic: float | None = None) -> None:
        now = self.clock() if start_monotonic is None else float(start_monotonic)
        with self._lock:
            self._active = True
            self._started_monotonic = now
            self._started_at_ms = int(round(now * 1000.0))
            self._next_emit_monotonic = now
            self._last_frame_monotonic = None
            self._prime_latest_frame_locked(active=True, position_ms=0)

    def stop(self) -> None:
        with self._lock:
            self._active = False

    def preroll_status(self, *, elapsed_ms: int | float) -> dict[str, Any]:
        buffered_ms = self.buffered_duration_ms
        elapsed = max(0, int(round(float(elapsed_ms))))
        ready = bool(self.startup_preroll_ms <= 0 or buffered_ms >= self.startup_preroll_ms)
        timed_out = bool(
            not ready
            and self.max_startup_wait_ms > 0
            and elapsed >= self.max_startup_wait_ms
        )
        return {
            "startup_preroll_ms": int(self.startup_preroll_ms),
            "startup_preroll_buffered_ms": int(buffered_ms),
            "startup_preroll_ready": ready,
            "startup_preroll_timeout": timed_out,
            "max_startup_wait_ms": int(self.max_startup_wait_ms),
            "voice_visual_disabled_reason": (
                "startup_preroll_max_wait_elapsed" if timed_out else None
            ),
            "raw_audio_present": False,
        }

    def sample_due(
        self, *, now_monotonic: float | None = None
    ) -> VoiceVisualMeterFrame | None:
        now = self.clock() if now_monotonic is None else float(now_monotonic)
        with self._lock:
            if not self._active or self._started_monotonic is None:
                return None
            if self._next_emit_monotonic is not None and now + 0.000_001 < self._next_emit_monotonic:
                return None
            playback_position_ms = max(
                0, int(round((now - self._started_monotonic) * 1000.0))
            )
            sample_time_ms = max(0, playback_position_ms - self.visual_offset_ms)
            frame = self._sample_locked(
                playback_position_ms,
                now,
                active=True,
                sample_time_ms=sample_time_ms,
            )
            interval = 1.0 / self.update_hz
            next_emit = (
                self._next_emit_monotonic + interval
                if self._next_emit_monotonic is not None
                else now + interval
            )
            self._next_emit_monotonic = max(next_emit, now)
            return frame

    def sample_at_playback_position(
        self, playback_position_ms: int | float
    ) -> VoiceVisualMeterFrame:
        now = self.clock()
        with self._lock:
            return self._sample_locked(
                max(0, int(round(float(playback_position_ms)))),
                now,
                active=self._active,
            )

    def to_payload(
        self,
        *,
        active: bool | None = None,
        now_monotonic: float | None = None,
        disabled_reason: str | None = None,
    ) -> dict[str, Any]:
        now = self.clock() if now_monotonic is None else float(now_monotonic)
        with self._lock:
            if self._latest_frame is None:
                self._prime_latest_frame_locked(active=bool(active))
            latest = self._latest_frame
            latest_age_ms = self._latest_age_ms_locked(now)
            payload = {
                "voice_visual_active": bool(self._active if active is None else active),
                "voice_visual_available": bool(disabled_reason is None),
                "voice_visual_energy": round(_clamp(self._smoothed_energy or 0.0), 4),
                "voice_visual_source": self.source,
                "voice_visual_energy_source": self.source,
                "voice_visual_playback_id": self.playback_id,
                "voice_visual_sample_rate_hz": int(self.update_hz),
                "voice_visual_started_at_ms": self._started_at_ms,
                "voice_visual_latest_age_ms": latest_age_ms,
                "voice_visual_sample_time_ms": latest.sample_time_ms
                if latest is not None
                else None,
                "voice_visual_playback_clock_position_ms": (
                    latest.playback_clock_position_ms if latest is not None else None
                ),
                "voice_visual_offset_ms": int(self.visual_offset_ms),
                "voice_visual_disabled_reason": disabled_reason,
                "raw_audio_present": False,
                "raw_audio_included": False,
                "raw_audio_logged": False,
            }
            if latest is not None:
                payload["voice_visual_energy"] = round(_clamp(latest.energy), 4)
                payload["rms"] = round(_clamp(latest.rms), 4)
                payload["peak"] = round(_clamp(latest.peak), 4)
            return payload

    def _buffered_duration_ms_locked(self) -> int:
        frame_width = self.channels * self.sample_width_bytes
        if frame_width <= 0:
            return 0
        frames = len(self._pcm) // frame_width
        return int(round(frames / self.sample_rate_hz * 1000.0))

    def _prime_latest_frame_locked(
        self, *, active: bool = False, position_ms: int = 0
    ) -> None:
        now = self.clock()
        self._latest_frame = self._sample_locked(position_ms, now, active=active)

    def _sample_locked(
        self,
        playback_position_ms: int,
        now_monotonic: float,
        *,
        active: bool,
        sample_time_ms: int | None = None,
    ) -> VoiceVisualMeterFrame:
        effective_sample_time_ms = max(
            0,
            int(
                round(
                    float(
                        playback_position_ms
                        if sample_time_ms is None
                        else sample_time_ms
                    )
                )
            ),
        )
        rms, peak = self._window_levels_locked(effective_sample_time_ms)
        target = self._energy_from_levels(rms, peak)
        previous = self._smoothed_energy
        if previous is None:
            smoothed = target
        else:
            last = self._last_frame_monotonic
            dt_ms = (
                1000.0 / self.update_hz
                if last is None
                else max(1.0, (now_monotonic - last) * 1000.0)
            )
            tau = self.attack_ms if target >= previous else self.release_ms
            alpha = 1.0 - math.exp(-dt_ms / max(1.0, float(tau)))
            smoothed = previous + (target - previous) * alpha
        self._smoothed_energy = _clamp(smoothed)
        self._last_frame_monotonic = now_monotonic
        self._last_sample_monotonic = now_monotonic
        frame = VoiceVisualMeterFrame(
            playback_id=self.playback_id,
            playback_position_ms=int(playback_position_ms),
            duration_ms=self.window_ms,
            rms=_clamp(rms),
            peak=_clamp(peak),
            energy=_clamp(self._smoothed_energy),
            sample_rate_hz=self.update_hz,
            sample_time_ms=int(effective_sample_time_ms),
            playback_clock_position_ms=int(playback_position_ms),
            visual_offset_ms=int(self.visual_offset_ms),
            active=active,
            started_at_ms=self._started_at_ms,
            latest_age_ms=0,
            timestamp=_utc_now_iso(),
        )
        self._latest_frame = frame
        return frame

    def _window_levels_locked(self, playback_position_ms: int) -> tuple[float, float]:
        if not self._pcm:
            return 0.0, 0.0
        frame_width = self.channels * self.sample_width_bytes
        sample_count = max(1, int(self.sample_rate_hz * self.window_ms / 1000.0))
        center_frame = int(self.sample_rate_hz * max(0, playback_position_ms) / 1000.0)
        start_frame = max(0, center_frame)
        end_frame = min(
            len(self._pcm) // frame_width,
            start_frame + sample_count,
        )
        if end_frame <= start_frame:
            start_frame = max(0, (len(self._pcm) // frame_width) - sample_count)
            end_frame = len(self._pcm) // frame_width
        start = start_frame * frame_width
        end = end_frame * frame_width
        payload = bytes(self._pcm[start:end])
        if self.sample_width_bytes != 2:
            return self._levels_for_unsigned_bytes(payload)
        even_length = len(payload) - (len(payload) % 2)
        if even_length <= 0:
            return 0.0, 0.0
        sum_squares = 0.0
        peak = 0
        count = 0
        for sample in struct.iter_unpack("<h", payload[:even_length]):
            value = int(sample[0])
            magnitude = abs(value)
            peak = max(peak, magnitude)
            sum_squares += float(value * value)
            count += 1
        if count <= 0:
            return 0.0, 0.0
        rms = math.sqrt(sum_squares / count) / 32768.0
        return _clamp(rms), _clamp(peak / 32768.0)

    def _levels_for_unsigned_bytes(self, payload: bytes) -> tuple[float, float]:
        if not payload:
            return 0.0, 0.0
        centered = [int(byte) - 128 for byte in payload]
        sum_squares = sum(float(value * value) for value in centered)
        peak = max(abs(value) for value in centered)
        rms = math.sqrt(sum_squares / len(centered)) / 128.0
        return _clamp(rms), _clamp(peak / 128.0)

    def _energy_from_levels(self, rms: float, peak: float) -> float:
        combined = max(_clamp(rms), _clamp(peak) * 0.62)
        if combined <= self.noise_floor:
            return 0.0
        normalized = (combined - self.noise_floor) / max(0.001, 1.0 - self.noise_floor)
        return _clamp(math.pow(_clamp(normalized * self.gain), 0.65))

    def _latest_age_ms_locked(self, now_monotonic: float) -> int | None:
        if self._last_sample_monotonic is None:
            return None
        return max(0, int(round((now_monotonic - self._last_sample_monotonic) * 1000.0)))
