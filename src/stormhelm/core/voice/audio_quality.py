from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, Mapping


_INT16_MAX = 32768.0
_CLIPPING_THRESHOLD = 32760
_BOUNDARY_DISCONTINUITY_THRESHOLD = 0.22
_CHUNK_GAP_MARGIN_MS = 32.0


def _clamp_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return max(minimum, min(maximum, parsed))


def safe_playback_buffer_policy(
    *,
    jitter_buffer_ms: int | float = 120,
    min_buffer_ms: int | float = 80,
    max_buffer_ms: int | float = 400,
    underrun_recovery: str = "hold_or_silence",
) -> dict[str, Any]:
    """Return bounded scalar playback buffering policy metadata."""

    max_buffer = _clamp_int(max_buffer_ms, 400, minimum=120, maximum=1000)
    min_buffer = _clamp_int(min_buffer_ms, 80, minimum=0, maximum=max_buffer)
    jitter = _clamp_int(jitter_buffer_ms, 120, minimum=min_buffer, maximum=max_buffer)
    recovery = str(underrun_recovery or "hold_or_silence").strip().lower()
    if recovery not in {"hold_or_silence", "silence", "hold", "none"}:
        recovery = "hold_or_silence"
    return {
        "streaming_jitter_buffer_ms": jitter,
        "streaming_min_buffer_ms": min_buffer,
        "streaming_max_buffer_ms": max_buffer,
        "streaming_underrun_recovery": recovery,
        "bounded": True,
        "raw_audio_present": False,
    }


def classify_audio_quality(report: Mapping[str, Any]) -> str:
    reasons = {
        str(reason)
        for reason in report.get("playback_artifact_reasons", [])
        if str(reason)
    }
    if "playback_buffer_underrun" in reasons:
        return "playback_buffer_underrun"
    if "tts_chunk_gap" in reasons:
        return "tts_chunk_gap"
    if "playback_write_late" in reasons:
        return "playback_write_late"
    if "sample_rate_mismatch" in reasons:
        return "sample_rate_mismatch"
    if "sample_format_mismatch" in reasons:
        return "sample_format_mismatch"
    if "clipping_or_saturation" in reasons:
        return "clipping_or_saturation"
    if "chunk_boundary_discontinuity" in reasons:
        return "chunk_boundary_discontinuity"
    if "duplicate_or_out_of_order_chunk" in reasons:
        return "duplicate_or_out_of_order_chunk"
    if "stream_reset_or_overlap" in reasons:
        return "stream_reset_or_overlap"
    if "old_playback_worker_interference" in reasons:
        return "old_playback_worker_interference"
    if "playback_backend_callback_jitter" in reasons:
        return "playback_backend_callback_jitter"
    if bool(report.get("playback_artifact_suspected")):
        return "unknown_audio_artifact"
    return "pass"


@dataclass
class PlaybackAudioQualityTracker:
    playback_id: str
    speech_request_id: str | None = None
    tts_request_id: str | None = None
    expected_sample_rate_hz: int = 24_000
    expected_channels: int = 1
    expected_sample_width_bytes: int = 2
    streaming_jitter_buffer_ms: int = 120
    streaming_min_buffer_ms: int = 80
    streaming_max_buffer_ms: int = 400
    streaming_underrun_recovery: str = "hold_or_silence"

    def __post_init__(self) -> None:
        self.expected_sample_rate_hz = _clamp_int(
            self.expected_sample_rate_hz, 24_000, minimum=1, maximum=384_000
        )
        self.expected_channels = _clamp_int(
            self.expected_channels, 1, minimum=1, maximum=8
        )
        self.expected_sample_width_bytes = _clamp_int(
            self.expected_sample_width_bytes, 2, minimum=1, maximum=4
        )
        policy = safe_playback_buffer_policy(
            jitter_buffer_ms=self.streaming_jitter_buffer_ms,
            min_buffer_ms=self.streaming_min_buffer_ms,
            max_buffer_ms=self.streaming_max_buffer_ms,
            underrun_recovery=self.streaming_underrun_recovery,
        )
        self.streaming_jitter_buffer_ms = int(policy["streaming_jitter_buffer_ms"])
        self.streaming_min_buffer_ms = int(policy["streaming_min_buffer_ms"])
        self.streaming_max_buffer_ms = int(policy["streaming_max_buffer_ms"])
        self.streaming_underrun_recovery = str(policy["streaming_underrun_recovery"])
        self._chunk_count = 0
        self._total_sample_count = 0
        self._total_byte_length = 0
        self._total_duration_ms = 0.0
        self._rms_min: float | None = None
        self._rms_max: float | None = None
        self._peak_min: float | None = None
        self._peak_max: float | None = None
        self._queue_depth_values: list[float] = []
        self._queue_duration_values: list[float] = []
        self._last_submit_time_ms: float | None = None
        self._last_duration_ms: float | None = None
        self._last_chunk_index: int | None = None
        self._last_terminal_sample: int | None = None
        self._seen_chunk_indexes: set[int] = set()
        self._underrun_count = 0
        self._late_write_count = 0
        self._chunk_gap_count = 0
        self._chunk_gap_audio_risk_count = 0
        self._max_chunk_gap_ms = 0.0
        self._dropped_chunk_count = 0
        self._duplicate_chunk_count = 0
        self._out_of_order_chunk_count = 0
        self._clipping_count = 0
        self._chunk_boundary_discontinuity_count = 0
        self._max_boundary_discontinuity = 0.0
        self._max_zero_crossing_discontinuity = 0.0
        self._dc_offset_abs_max = 0.0
        self._sample_rate_mismatch_flag = False
        self._format_mismatch_flag = False
        self._stream_reset_count = 0
        self._write_latency_max_ms = 0.0
        self._callback_latency_max_ms = 0.0
        self._thread_scheduling_delay_max_ms = 0.0
        self._last_chunk_report: dict[str, Any] = {}

    def analyze_chunk(
        self,
        payload: bytes | bytearray | memoryview | None,
        *,
        chunk_index: int | None = None,
        submit_time_ms: float | None = None,
        actual_sample_rate_hz: int | None = None,
        actual_channels: int | None = None,
        actual_sample_width_bytes: int | None = None,
        audio_format: str = "pcm",
        queue_depth_before: int | float | None = None,
        queue_depth_after: int | float | None = None,
        queued_duration_ms_before: int | float | None = None,
        queued_duration_ms_after: int | float | None = None,
        wave_write_submit_time_ms: float | None = None,
        wave_write_complete_time_ms: float | None = None,
        callback_latency_ms: float | None = None,
        thread_scheduling_delay_ms: float | None = None,
    ) -> dict[str, Any]:
        data = bytes(payload or b"")
        now_ms = (
            _clamp_float(submit_time_ms, 0.0, minimum=0.0, maximum=10**15)
            if submit_time_ms is not None
            else None
        )
        sample_rate = _clamp_int(
            actual_sample_rate_hz if actual_sample_rate_hz is not None else self.expected_sample_rate_hz,
            self.expected_sample_rate_hz,
            minimum=1,
            maximum=384_000,
        )
        channels = _clamp_int(
            actual_channels if actual_channels is not None else self.expected_channels,
            self.expected_channels,
            minimum=1,
            maximum=8,
        )
        sample_width = _clamp_int(
            actual_sample_width_bytes
            if actual_sample_width_bytes is not None
            else self.expected_sample_width_bytes,
            self.expected_sample_width_bytes,
            minimum=1,
            maximum=4,
        )
        frame_width = max(1, channels * sample_width)
        usable_length = len(data) - (len(data) % frame_width)
        format_mismatch = (
            channels != self.expected_channels
            or sample_width != self.expected_sample_width_bytes
            or usable_length != len(data)
            or str(audio_format or "pcm").strip().lower() not in {"pcm", "wav"}
        )
        sample_rate_mismatch = sample_rate != self.expected_sample_rate_hz
        self._format_mismatch_flag = self._format_mismatch_flag or format_mismatch
        self._sample_rate_mismatch_flag = (
            self._sample_rate_mismatch_flag or sample_rate_mismatch
        )
        frame_count = usable_length // frame_width if usable_length > 0 else 0
        sample_count = usable_length // max(1, sample_width)
        self._total_sample_count += max(0, sample_count)
        duration_ms = (
            float(frame_count) / float(max(1, sample_rate)) * 1000.0
            if frame_count > 0
            else 0.0
        )
        rms, peak, dc_offset, clipping_count, first_sample, last_sample = self._levels(
            data[:usable_length],
            sample_width=sample_width,
        )
        self._chunk_count += 1
        self._total_byte_length += len(data)
        self._total_duration_ms += duration_ms
        self._rms_min = rms if self._rms_min is None else min(self._rms_min, rms)
        self._rms_max = rms if self._rms_max is None else max(self._rms_max, rms)
        self._peak_min = peak if self._peak_min is None else min(self._peak_min, peak)
        self._peak_max = peak if self._peak_max is None else max(self._peak_max, peak)
        self._clipping_count += int(clipping_count)
        self._dc_offset_abs_max = max(self._dc_offset_abs_max, abs(dc_offset))

        if chunk_index is not None:
            index = int(chunk_index)
            if index in self._seen_chunk_indexes:
                self._duplicate_chunk_count += 1
            if self._last_chunk_index is not None and index <= self._last_chunk_index:
                self._out_of_order_chunk_count += 1
            if self._last_chunk_index is not None and index > self._last_chunk_index + 1:
                self._dropped_chunk_count += index - self._last_chunk_index - 1
            self._seen_chunk_indexes.add(index)
            self._last_chunk_index = index

        if (
            first_sample is not None
            and self._last_terminal_sample is not None
            and self._chunk_count > 1
        ):
            discontinuity = abs(first_sample - self._last_terminal_sample) / 65536.0
            self._max_boundary_discontinuity = max(
                self._max_boundary_discontinuity,
                discontinuity,
            )
            zero_crossing = discontinuity if (first_sample < 0) != (self._last_terminal_sample < 0) else 0.0
            self._max_zero_crossing_discontinuity = max(
                self._max_zero_crossing_discontinuity,
                zero_crossing,
            )
            if discontinuity >= _BOUNDARY_DISCONTINUITY_THRESHOLD:
                self._chunk_boundary_discontinuity_count += 1
        if last_sample is not None:
            self._last_terminal_sample = last_sample

        excess_gap_detected_ms = 0.0
        if now_ms is not None and self._last_submit_time_ms is not None:
            gap_ms = max(0.0, now_ms - self._last_submit_time_ms)
            expected_gap = max(0.0, float(self._last_duration_ms or 0.0))
            excess_gap = gap_ms - expected_gap
            if excess_gap > _CHUNK_GAP_MARGIN_MS:
                excess_gap_detected_ms = excess_gap
                self._chunk_gap_count += 1
                self._max_chunk_gap_ms = max(self._max_chunk_gap_ms, excess_gap)
        if now_ms is not None:
            self._last_submit_time_ms = now_ms
        self._last_duration_ms = duration_ms

        q_before = _clamp_float(
            queue_depth_before if queue_depth_before is not None else 0,
            0.0,
            minimum=0.0,
            maximum=1_000_000.0,
        )
        q_after = _clamp_float(
            queue_depth_after if queue_depth_after is not None else q_before,
            q_before,
            minimum=0.0,
            maximum=1_000_000.0,
        )
        queued_before = _clamp_float(
            queued_duration_ms_before
            if queued_duration_ms_before is not None
            else 0.0,
            0.0,
            minimum=0.0,
            maximum=60_000.0,
        )
        queued_after = _clamp_float(
            queued_duration_ms_after
            if queued_duration_ms_after is not None
            else queued_before,
            queued_before,
            minimum=0.0,
            maximum=60_000.0,
        )
        self._queue_depth_values.extend([q_before, q_after])
        self._queue_duration_values.extend([queued_before, queued_after])
        if self._chunk_count > 1 and queued_before < max(4.0, self.streaming_min_buffer_ms * 0.15):
            self._underrun_count += 1
        if (
            excess_gap_detected_ms > 0.0
            and self._chunk_count > 1
            and queued_before < max(self.streaming_min_buffer_ms, excess_gap_detected_ms)
        ):
            self._chunk_gap_audio_risk_count += 1
        if (
            excess_gap_detected_ms > 0.0
            and self._chunk_count > 1
            and queued_before < self.streaming_min_buffer_ms
        ):
            self._underrun_count += 1

        write_submit = _float_or_none(wave_write_submit_time_ms)
        write_complete = _float_or_none(wave_write_complete_time_ms)
        write_latency = (
            max(0.0, write_complete - write_submit)
            if write_submit is not None and write_complete is not None
            else 0.0
        )
        self._write_latency_max_ms = max(self._write_latency_max_ms, write_latency)
        if write_latency > 24.0:
            self._late_write_count += 1
        callback_latency = _float_or_none(callback_latency_ms) or 0.0
        scheduling_delay = _float_or_none(thread_scheduling_delay_ms) or 0.0
        self._callback_latency_max_ms = max(
            self._callback_latency_max_ms,
            callback_latency,
        )
        self._thread_scheduling_delay_max_ms = max(
            self._thread_scheduling_delay_max_ms,
            scheduling_delay,
        )

        report = {
            "playback_id": self.playback_id,
            "speech_request_id": self.speech_request_id,
            "tts_request_id": self.tts_request_id,
            "chunk_index": chunk_index if chunk_index is not None else self._chunk_count - 1,
            "audio_chunk_duration_ms": round(duration_ms, 3),
            "audio_chunk_byte_length": len(data),
            "expected_sample_rate": self.expected_sample_rate_hz,
            "actual_playback_sample_rate": sample_rate,
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_format": f"pcm_s{sample_width * 8}_le",
            "chunk_queue_depth": round(q_after, 3),
            "playback_buffer_duration_queued_ms": round(queued_after, 3),
            "wave_write_submit_time_ms": round(write_submit, 3)
            if write_submit is not None
            else None,
            "wave_write_completion_time_ms": round(write_complete, 3)
            if write_complete is not None
            else None,
            "write_latency_ms": round(write_latency, 3),
            "callback_latency": round(callback_latency, 3),
            "playback_thread_scheduling_delay": round(scheduling_delay, 3),
            "rms": round(rms, 6),
            "peak": round(peak, 6),
            "dc_offset_estimate": round(dc_offset, 6),
            "clipping_count": int(clipping_count),
            "zero_crossing_discontinuity_estimate": round(
                self._max_zero_crossing_discontinuity,
                6,
            ),
            "chunk_boundary_discontinuity_estimate": round(
                self._max_boundary_discontinuity,
                6,
            ),
            "sample_rate_mismatch_flag": sample_rate_mismatch,
            "format_mismatch_flag": format_mismatch,
            "raw_audio_present": False,
        }
        self._last_chunk_report = report
        return report

    def record_stream_reset(self) -> None:
        self._stream_reset_count += 1

    def summary(self) -> dict[str, Any]:
        reasons = self._artifact_reasons()
        queue_depths = self._queue_depth_values or [0.0]
        queue_ms = self._queue_duration_values or [0.0]
        report = {
            "playback_id": self.playback_id,
            "speech_request_id": self.speech_request_id,
            "tts_request_id": self.tts_request_id,
            "audio_chunk_count": self._chunk_count,
            "audio_chunk_byte_length_total": self._total_byte_length,
            "audio_duration_ms": round(self._total_duration_ms, 3),
            "expected_sample_rate": self.expected_sample_rate_hz,
            "actual_playback_sample_rate": self.expected_sample_rate_hz,
            "channels": self.expected_channels,
            "sample_format": f"pcm_s{self.expected_sample_width_bytes * 8}_le",
            "chunk_queue_depth_min": round(min(queue_depths), 3),
            "chunk_queue_depth_max": round(max(queue_depths), 3),
            "chunk_queue_depth_avg": round(sum(queue_depths) / len(queue_depths), 3),
            "playback_buffer_duration_queued_min_ms": round(min(queue_ms), 3),
            "playback_buffer_duration_queued_max_ms": round(max(queue_ms), 3),
            "playback_buffer_duration_queued_avg_ms": round(
                sum(queue_ms) / len(queue_ms),
                3,
            ),
            "streaming_jitter_buffer_ms": self.streaming_jitter_buffer_ms,
            "streaming_min_buffer_ms": self.streaming_min_buffer_ms,
            "streaming_max_buffer_ms": self.streaming_max_buffer_ms,
            "streaming_underrun_recovery": self.streaming_underrun_recovery,
            "underrun_count": int(self._underrun_count),
            "late_write_count": int(self._late_write_count),
            "chunk_gap_count": int(self._chunk_gap_count),
            "chunk_gap_audio_risk_count": int(self._chunk_gap_audio_risk_count),
            "max_chunk_gap_ms": round(self._max_chunk_gap_ms, 3),
            "dropped_chunk_count": int(self._dropped_chunk_count),
            "duplicate_chunk_count": int(self._duplicate_chunk_count),
            "out_of_order_chunk_count": int(self._out_of_order_chunk_count),
            "clipping_count": int(self._clipping_count),
            "clipping_ratio": round(
                float(self._clipping_count) / float(max(1, self._total_sample_count)),
                6,
            ),
            "peak_min": round(float(self._peak_min or 0.0), 6),
            "peak_max": round(float(self._peak_max or 0.0), 6),
            "rms_min": round(float(self._rms_min or 0.0), 6),
            "rms_max": round(float(self._rms_max or 0.0), 6),
            "dc_offset_estimate": round(self._dc_offset_abs_max, 6),
            "chunk_boundary_discontinuity_count": int(
                self._chunk_boundary_discontinuity_count
            ),
            "chunk_boundary_discontinuity_estimate": round(
                self._max_boundary_discontinuity,
                6,
            ),
            "zero_crossing_discontinuity_estimate": round(
                self._max_zero_crossing_discontinuity,
                6,
            ),
            "sample_rate_mismatch_flag": bool(self._sample_rate_mismatch_flag),
            "format_mismatch_flag": bool(self._format_mismatch_flag),
            "stream_reset_count": int(self._stream_reset_count),
            "write_latency_max_ms": round(self._write_latency_max_ms, 3),
            "callback_latency_max_ms": round(self._callback_latency_max_ms, 3),
            "playback_thread_scheduling_delay_max_ms": round(
                self._thread_scheduling_delay_max_ms,
                3,
            ),
            "playback_artifact_suspected": bool(reasons),
            "playback_artifact_reasons": reasons,
            "last_chunk_audio_quality": dict(self._last_chunk_report),
            "raw_audio_present": False,
        }
        report["audio_quality_status"] = classify_audio_quality(report)
        return report

    def _artifact_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self._underrun_count > 0:
            reasons.append("playback_buffer_underrun")
        if self._chunk_gap_audio_risk_count > 0:
            reasons.append("tts_chunk_gap")
        if self._late_write_count > 0:
            reasons.append("playback_write_late")
        if self._sample_rate_mismatch_flag:
            reasons.append("sample_rate_mismatch")
        if self._format_mismatch_flag:
            reasons.append("sample_format_mismatch")
        clipping_ratio = float(self._clipping_count) / float(
            max(1, self._total_sample_count)
        )
        if self._clipping_count >= 10 and clipping_ratio >= 0.005:
            reasons.append("clipping_or_saturation")
        if self._chunk_boundary_discontinuity_count > 0:
            reasons.append("chunk_boundary_discontinuity")
        if self._duplicate_chunk_count > 0 or self._out_of_order_chunk_count > 0:
            reasons.append("duplicate_or_out_of_order_chunk")
        if self._stream_reset_count > 0:
            reasons.append("stream_reset_or_overlap")
        if self._callback_latency_max_ms > 32.0:
            reasons.append("playback_backend_callback_jitter")
        return reasons

    def _levels(
        self,
        payload: bytes,
        *,
        sample_width: int,
    ) -> tuple[float, float, float, int, int | None, int | None]:
        if not payload:
            return 0.0, 0.0, 0.0, 0, None, None
        if sample_width == 2:
            usable = len(payload) - (len(payload) % 2)
            if usable <= 0:
                return 0.0, 0.0, 0.0, 0, None, None
            total = 0.0
            sum_squares = 0.0
            peak = 0
            clipping = 0
            count = 0
            first_sample: int | None = None
            last_sample: int | None = None
            for (sample,) in struct.iter_unpack("<h", payload[:usable]):
                value = int(sample)
                if first_sample is None:
                    first_sample = value
                last_sample = value
                magnitude = abs(value)
                peak = max(peak, magnitude)
                if magnitude >= _CLIPPING_THRESHOLD:
                    clipping += 1
                total += value
                sum_squares += float(value * value)
                count += 1
            if count <= 0:
                return 0.0, 0.0, 0.0, 0, None, None
            rms = math.sqrt(sum_squares / count) / _INT16_MAX
            return (
                max(0.0, min(1.0, rms)),
                max(0.0, min(1.0, peak / _INT16_MAX)),
                max(-1.0, min(1.0, (total / count) / _INT16_MAX)),
                clipping,
                first_sample,
                last_sample,
            )
        centered = [int(byte) - 128 for byte in payload]
        if not centered:
            return 0.0, 0.0, 0.0, 0, None, None
        peak = max(abs(value) for value in centered)
        sum_squares = sum(float(value * value) for value in centered)
        total = sum(float(value) for value in centered)
        return (
            max(0.0, min(1.0, math.sqrt(sum_squares / len(centered)) / 128.0)),
            max(0.0, min(1.0, peak / 128.0)),
            max(-1.0, min(1.0, (total / len(centered)) / 128.0)),
            0,
            centered[0],
            centered[-1],
        )


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


__all__ = [
    "PlaybackAudioQualityTracker",
    "classify_audio_quality",
    "safe_playback_buffer_policy",
]
