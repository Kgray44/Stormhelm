from __future__ import annotations

import csv
import io
import math
import struct
from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable, Sequence

from stormhelm.core.voice.voice_visual_meter import VoiceVisualMeter


PCM_STREAM_SOURCE = "pcm_stream_meter"
DEFAULT_SAMPLE_RATE_HZ = 24_000
DEFAULT_UPDATE_HZ = 60
DEFAULT_NOISE_FLOOR = 0.015
DEFAULT_GAIN = 2.0


def _clamp01(value: float) -> float:
    if not math.isfinite(float(value)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _round(value: float | int | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _meter_energy_from_levels(
    rms: float,
    peak: float,
    *,
    noise_floor: float = DEFAULT_NOISE_FLOOR,
    gain: float = DEFAULT_GAIN,
) -> float:
    combined = max(_clamp01(rms), _clamp01(peak) * 0.62)
    if combined <= noise_floor:
        return 0.0
    normalized = (combined - noise_floor) / max(0.001, 1.0 - noise_floor)
    return _clamp01(math.pow(_clamp01(normalized * gain), 0.65))


def _value(row: Any, key: str, fallback: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, fallback)
    return getattr(row, key, fallback)


def _series(rows: Sequence[Any], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _value(row, key)
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            values.append(number)
    return values


def _range(values: Sequence[float]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {"count": 0, "min": None, "max": None, "span": 0.0}
    low = min(clean)
    high = max(clean)
    return {
        "count": len(clean),
        "min": _round(low),
        "max": _round(high),
        "span": _round(high - low),
    }


def correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    count = min(len(left), len(right))
    if count < 3:
        return None
    x_values = [float(value) for value in left[:count]]
    y_values = [float(value) for value in right[:count]]
    x_mean = mean(x_values)
    y_mean = mean(y_values)
    x_variance = sum((value - x_mean) ** 2 for value in x_values)
    y_variance = sum((value - y_mean) ** 2 for value in y_values)
    if x_variance <= 1e-12 or y_variance <= 1e-12:
        return 0.0
    covariance = sum(
        (x_values[index] - x_mean) * (y_values[index] - y_mean)
        for index in range(count)
    )
    return max(-1.0, min(1.0, covariance / math.sqrt(x_variance * y_variance)))


def _varies(values: Sequence[float], *, threshold: float = 0.035) -> bool:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if len(clean) < 3:
        return False
    return max(clean) - min(clean) >= threshold


def _mean_delta(left: Sequence[float], right: Sequence[float]) -> float | None:
    count = min(len(left), len(right))
    if count <= 0:
        return None
    deltas = [
        float(right[index]) - float(left[index])
        for index in range(count)
        if math.isfinite(float(left[index])) and math.isfinite(float(right[index]))
    ]
    return mean(deltas) if deltas else None


def _estimated_lag_ms(
    source_values: Sequence[float],
    target_values: Sequence[float],
    *,
    sample_interval_ms: float,
    max_lag_ms: float = 800.0,
) -> float | None:
    count = min(len(source_values), len(target_values))
    if count < 6 or sample_interval_ms <= 0:
        return None
    max_lag_steps = min(int(round(max_lag_ms / sample_interval_ms)), count // 2)
    best_lag = 0
    best_score = -2.0
    for lag in range(-max_lag_steps, max_lag_steps + 1):
        if lag < 0:
            left = source_values[-lag:count]
            right = target_values[: count + lag]
        elif lag > 0:
            left = source_values[: count - lag]
            right = target_values[lag:count]
        else:
            left = source_values[:count]
            right = target_values[:count]
        score = correlation(left, right)
        if score is None:
            continue
        if score > best_score:
            best_score = score
            best_lag = lag
    return best_lag * sample_interval_ms


def _plateau_report(values: Sequence[float]) -> dict[str, float | int]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if len(clean) < 2:
        return {"plateau_run_max": 0, "clipped_count": 0, "near_zero_count": 0}
    run = 1
    max_run = 1
    previous = clean[0]
    for value in clean[1:]:
        if abs(value - previous) <= 0.002:
            run += 1
        else:
            max_run = max(max_run, run)
            run = 1
        previous = value
    max_run = max(max_run, run)
    return {
        "plateau_run_max": int(max_run),
        "clipped_count": sum(1 for value in clean if value >= 0.985),
        "near_zero_count": sum(1 for value in clean if value <= 0.005),
    }


@dataclass(frozen=True, slots=True)
class ExpectedEnergySample:
    sample_time_ms: int
    expected_energy: float
    expected_rms: float
    expected_peak: float
    segment: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_time_ms": int(self.sample_time_ms),
            "expected_energy": _round(self.expected_energy),
            "expected_rms": _round(self.expected_rms),
            "expected_peak": _round(self.expected_peak),
            "segment": self.segment,
            "raw_audio_present": False,
        }


@dataclass(frozen=True, slots=True)
class SyntheticPCMStimulus:
    pcm_bytes: bytes
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    duration_ms: int
    update_hz: int
    expected_timeline: list[ExpectedEnergySample]

    def expected_energy_at(self, sample_time_ms: int | float) -> float:
        if not self.expected_timeline:
            return 0.0
        target = float(sample_time_ms)
        closest = min(
            self.expected_timeline,
            key=lambda sample: abs(float(sample.sample_time_ms) - target),
        )
        return closest.expected_energy


@dataclass(frozen=True, slots=True)
class BackendMeterDiagnosticRow:
    playback_id: str
    sample_time_ms: int
    monotonic_time_ms: float
    expected_energy: float
    rms: float
    peak: float
    voice_visual_energy: float
    smoothed_energy: float
    source: str = PCM_STREAM_SOURCE
    raw_audio_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "playback_id": self.playback_id,
            "sample_time_ms": int(self.sample_time_ms),
            "monotonic_time_ms": _round(self.monotonic_time_ms),
            "expected_energy": _round(self.expected_energy),
            "rms": _round(self.rms),
            "peak": _round(self.peak),
            "voice_visual_energy": _round(self.voice_visual_energy),
            "smoothed_energy": _round(self.smoothed_energy),
            "source": self.source,
            "raw_audio_present": False,
        }


@dataclass(frozen=True, slots=True)
class PayloadDiagnosticRow:
    playback_id: str
    payload_monotonic_time_ms: float
    payload_voice_visual_energy: float
    payload_voice_visual_active: bool
    payload_source: str
    payload_sample_time_ms: int
    sample_age_ms: float
    raw_audio_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "playback_id": self.playback_id,
            "payload_monotonic_time_ms": _round(self.payload_monotonic_time_ms),
            "payload_voice_visual_energy": _round(self.payload_voice_visual_energy),
            "payload_voice_visual_active": bool(self.payload_voice_visual_active),
            "payload_source": self.payload_source,
            "payload_sample_time_ms": int(self.payload_sample_time_ms),
            "sample_age_ms": _round(self.sample_age_ms),
            "raw_audio_present": False,
        }


class _DeterministicClock:
    def __init__(self) -> None:
        self.now_seconds = 0.0

    def __call__(self) -> float:
        return self.now_seconds


def _stimulus_segment(time_seconds: float) -> tuple[str, float]:
    if time_seconds < 0.5:
        return "silence_start", 0.0
    if time_seconds < 1.5:
        return "low_sine", 0.13
    if time_seconds < 2.5:
        return "high_sine", 0.56
    if time_seconds < 3.5:
        local = time_seconds - 2.5
        pulse = max(0.0, math.sin(2.0 * math.pi * 3.8 * local))
        envelope = math.pow(pulse, 1.7)
        return "syllable_pulses", 0.07 + 0.55 * envelope
    return "silence_end", 0.0


def generate_synthetic_pcm_stimulus(
    *,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    update_hz: int = DEFAULT_UPDATE_HZ,
    duration_ms: int = 4_000,
    frequency_hz: float = 440.0,
    channels: int = 1,
    sample_width_bytes: int = 2,
) -> SyntheticPCMStimulus:
    """Generate deterministic voiced/silent PCM plus a scalar expected timeline.

    The PCM stays in memory for the playback/meter path. Public report helpers
    intentionally emit only the expected scalar envelope and stage energies.
    """

    sample_rate = max(1, int(sample_rate_hz))
    updates = max(1, int(update_hz))
    total_frames = int(round(sample_rate * max(1, duration_ms) / 1000.0))
    pcm = bytearray()
    for frame_index in range(total_frames):
        time_seconds = frame_index / sample_rate
        _, amplitude = _stimulus_segment(time_seconds)
        value = max(
            -0.98,
            min(0.98, amplitude * math.sin(2.0 * math.pi * frequency_hz * time_seconds)),
        )
        sample = int(round(value * 32767.0))
        packed = struct.pack("<h", sample)
        for _ in range(max(1, channels)):
            pcm.extend(packed)

    expected: list[ExpectedEnergySample] = []
    interval_ms = 1000.0 / updates
    sample_count = int(round(duration_ms / interval_ms))
    for index in range(sample_count):
        sample_time_ms = int(round(index * interval_ms))
        segment, amplitude = _stimulus_segment(sample_time_ms / 1000.0)
        expected_peak = _clamp01(amplitude)
        expected_rms = expected_peak / math.sqrt(2.0) if expected_peak > 0 else 0.0
        expected_energy = _meter_energy_from_levels(expected_rms, expected_peak)
        expected.append(
            ExpectedEnergySample(
                sample_time_ms=sample_time_ms,
                expected_energy=expected_energy,
                expected_rms=expected_rms,
                expected_peak=expected_peak,
                segment=segment,
            )
        )

    return SyntheticPCMStimulus(
        pcm_bytes=bytes(pcm),
        sample_rate_hz=sample_rate,
        channels=max(1, int(channels)),
        sample_width_bytes=max(1, int(sample_width_bytes)),
        duration_ms=int(duration_ms),
        update_hz=updates,
        expected_timeline=expected,
    )


def run_backend_meter_diagnostics(
    stimulus: SyntheticPCMStimulus,
    *,
    playback_id: str,
    attack_ms: int = 60,
    release_ms: int = 160,
    noise_floor: float = DEFAULT_NOISE_FLOOR,
    gain: float = DEFAULT_GAIN,
) -> list[BackendMeterDiagnosticRow]:
    clock = _DeterministicClock()
    meter = VoiceVisualMeter(
        playback_id=playback_id,
        update_hz=stimulus.update_hz,
        sample_rate_hz=stimulus.sample_rate_hz,
        channels=stimulus.channels,
        sample_width_bytes=stimulus.sample_width_bytes,
        window_ms=max(8, int(round(1000.0 / stimulus.update_hz))),
        startup_preroll_ms=350,
        attack_ms=attack_ms,
        release_ms=release_ms,
        noise_floor=noise_floor,
        gain=gain,
        clock=clock,
    )
    meter.feed_preroll_pcm(stimulus.pcm_bytes)
    clock.now_seconds = 0.0
    meter.start_playback(start_monotonic=0.0)

    rows: list[BackendMeterDiagnosticRow] = []
    for expected in stimulus.expected_timeline:
        clock.now_seconds = expected.sample_time_ms / 1000.0
        frame = meter.sample_at_playback_position(expected.sample_time_ms)
        rows.append(
            BackendMeterDiagnosticRow(
                playback_id=playback_id,
                sample_time_ms=expected.sample_time_ms,
                monotonic_time_ms=float(expected.sample_time_ms),
                expected_energy=expected.expected_energy,
                rms=frame.rms,
                peak=frame.peak,
                voice_visual_energy=frame.energy,
                smoothed_energy=frame.energy,
            )
        )
    return rows


def build_payload_diagnostics(
    backend_rows: Sequence[BackendMeterDiagnosticRow],
    *,
    handoff_latency_ms: float = 4.0,
) -> list[PayloadDiagnosticRow]:
    rows: list[PayloadDiagnosticRow] = []
    for backend in backend_rows:
        payload_time = float(backend.monotonic_time_ms) + float(handoff_latency_ms)
        rows.append(
            PayloadDiagnosticRow(
                playback_id=backend.playback_id,
                payload_monotonic_time_ms=payload_time,
                payload_voice_visual_energy=_clamp01(backend.voice_visual_energy),
                payload_voice_visual_active=True,
                payload_source=backend.source,
                payload_sample_time_ms=backend.sample_time_ms,
                sample_age_ms=max(0.0, payload_time - float(backend.monotonic_time_ms)),
            )
        )
    return rows


def classify_reactive_chain(
    expected_energy: Sequence[float],
    backend_energy: Sequence[float],
    payload_energy: Sequence[float],
    qml_received_energy: Sequence[float],
    qml_final_speaking_energy: Sequence[float],
    *,
    paint_count: int | None = None,
    sample_drop_count: int = 0,
    max_latency_ms: float | None = None,
    correlation_floor: float = 0.45,
) -> list[str]:
    expected_varies = _varies(expected_energy)
    backend_varies = _varies(backend_energy)
    payload_varies = _varies(payload_energy)
    qml_varies = _varies(qml_received_energy)
    final_varies = _varies(qml_final_speaking_energy)

    if expected_varies and not backend_varies:
        return ["backend_meter_flat"]
    if backend_varies and not payload_varies:
        return ["payload_handoff_flat"]
    if payload_varies and not qml_varies:
        return ["qml_receive_flat"]
    if qml_varies and not final_varies:
        return ["anchor_mapping_flat"]
    if final_varies and paint_count is not None and paint_count <= 0:
        return ["qml_paint_missing"]

    problems: list[str] = []
    if sample_drop_count > 0:
        problems.append("sample_drop_detected")
    if max_latency_ms is not None and max_latency_ms > 350.0:
        problems.append("latency_too_high")

    checks = [
        (expected_energy, backend_energy),
        (backend_energy, payload_energy),
        (payload_energy, qml_received_energy),
        (qml_received_energy, qml_final_speaking_energy),
    ]
    for left, right in checks:
        if _varies(left) and _varies(right):
            score = correlation(left, right)
            if score is not None and score < correlation_floor:
                problems.append("correlation_poor")
                break

    return problems or ["chain_pass"]


def _stage_values(
    expected_rows: Sequence[ExpectedEnergySample],
    backend_rows: Sequence[BackendMeterDiagnosticRow],
    payload_rows: Sequence[PayloadDiagnosticRow],
    qml_rows: Sequence[dict[str, Any]],
) -> dict[str, list[float]]:
    return {
        "expected": _series(expected_rows, "expected_energy"),
        "backend": _series(backend_rows, "voice_visual_energy"),
        "payload": _series(payload_rows, "payload_voice_visual_energy"),
        "qml_received": _series(qml_rows, "qmlReceivedVoiceVisualEnergy"),
        "qml_final": _series(qml_rows, "qmlFinalSpeakingEnergy"),
    }


def _stage_times(
    backend_rows: Sequence[BackendMeterDiagnosticRow],
    payload_rows: Sequence[PayloadDiagnosticRow],
    qml_rows: Sequence[dict[str, Any]],
) -> dict[str, list[float]]:
    return {
        "backend": _series(backend_rows, "monotonic_time_ms"),
        "payload": _series(payload_rows, "payload_monotonic_time_ms"),
        "qml_received": _series(qml_rows, "qmlReceivedMonotonicTimeMs"),
        "qml_final": _series(qml_rows, "qmlFinalMonotonicTimeMs"),
        "paint": _series(qml_rows, "qmlPaintMonotonicTimeMs"),
    }


def _missing_count(*stages: Sequence[Any]) -> int:
    non_empty_lengths = [len(stage) for stage in stages if len(stage) > 0]
    if not non_empty_lengths:
        return 0
    target = max(non_empty_lengths)
    return sum(max(0, target - len(stage)) for stage in stages if len(stage) > 0)


def build_reactive_chain_report(
    *,
    playback_id: str,
    expected_rows: Sequence[ExpectedEnergySample],
    backend_rows: Sequence[BackendMeterDiagnosticRow],
    payload_rows: Sequence[PayloadDiagnosticRow],
    qml_rows: Sequence[dict[str, Any]],
    mode: str,
    audible_playback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = _stage_values(expected_rows, backend_rows, payload_rows, qml_rows)
    times = _stage_times(backend_rows, payload_rows, qml_rows)
    sample_interval_ms = 16.0
    if len(expected_rows) > 1:
        sample_interval_ms = max(1.0, mean(
            expected_rows[index].sample_time_ms - expected_rows[index - 1].sample_time_ms
            for index in range(1, min(len(expected_rows), 24))
        ))

    correlations = {
        "expected_to_backend": _round(correlation(values["expected"], values["backend"])),
        "backend_to_payload": _round(correlation(values["backend"], values["payload"])),
        "payload_to_qml_received": _round(
            correlation(values["payload"], values["qml_received"])
        ),
        "qml_received_to_finalSpeakingEnergy": _round(
            correlation(values["qml_received"], values["qml_final"])
        ),
    }
    latency = {
        "pcm_sample_to_backend_meter": _round(
            _estimated_lag_ms(
                values["expected"],
                values["backend"],
                sample_interval_ms=max(1.0, sample_interval_ms),
            )
        ),
        "backend_meter_to_ui_payload": _round(
            _mean_delta(times["backend"], times["payload"])
        ),
        "ui_payload_to_qml_receive": _round(
            _mean_delta(times["payload"], times["qml_received"])
        ),
        "qml_receive_to_finalSpeakingEnergy": _round(
            _mean_delta(times["qml_received"], times["qml_final"])
        ),
        "finalSpeakingEnergy_to_paint_timestamp": _round(
            _mean_delta(times["qml_final"], times["paint"])
        ),
    }
    compression = {
        "backend_vs_expected": _round(
            (_range(values["backend"])["span"] or 0.0)
            / max(0.001, float(_range(values["expected"])["span"] or 0.0))
        ),
        "payload_vs_backend": _round(
            (_range(values["payload"])["span"] or 0.0)
            / max(0.001, float(_range(values["backend"])["span"] or 0.0))
        ),
        "final_vs_qml_received": _round(
            (_range(values["qml_final"])["span"] or 0.0)
            / max(0.001, float(_range(values["qml_received"])["span"] or 0.0))
        ),
    }
    missing = _missing_count(expected_rows, backend_rows, payload_rows, qml_rows)
    paint_count = max(
        [int(_value(row, "qmlAnchorPaintCount", 0) or 0) for row in qml_rows] or [0]
    )
    numeric_latencies = [
        float(value)
        for value in latency.values()
        if value is not None and math.isfinite(float(value))
    ]
    classifications = classify_reactive_chain(
        values["expected"],
        values["backend"],
        values["payload"],
        values["qml_received"],
        values["qml_final"],
        paint_count=paint_count if qml_rows else None,
        sample_drop_count=missing,
        max_latency_ms=max(numeric_latencies) if numeric_latencies else None,
    )

    return {
        "probe": "voice_reactive_chain",
        "mode": mode,
        "playback_id": playback_id,
        "chain_version": "Voice-AR-DIAG",
        "privacy": {
            "raw_audio_present": False,
            "raw_audio_logged": False,
            "raw_audio_exposed": False,
            "scalar_only": True,
        },
        "source": PCM_STREAM_SOURCE,
        "ranges": {
            "expected": _range(values["expected"]),
            "backend_meter": _range(values["backend"]),
            "ui_payload": _range(values["payload"]),
            "qml_received": _range(values["qml_received"]),
            "qml_finalSpeakingEnergy": _range(values["qml_final"]),
        },
        "correlations": correlations,
        "latency_ms": latency,
        "missing_samples": {"total": int(missing)},
        "energy_compression_ratio": compression,
        "plateau_clipping": {
            "backend_meter": _plateau_report(values["backend"]),
            "ui_payload": _plateau_report(values["payload"]),
            "qml_received": _plateau_report(values["qml_received"]),
            "qml_finalSpeakingEnergy": _plateau_report(values["qml_final"]),
        },
        "max_frame_gap_ms": _round(
            max(
                [
                    times["qml_received"][index] - times["qml_received"][index - 1]
                    for index in range(1, len(times["qml_received"]))
                ]
                or [0.0]
            )
        ),
        "classification": classifications,
        "audible_playback": audible_playback or {"attempted": False},
        "raw_audio_present": False,
    }


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "to_dict"):
        return row.to_dict()
    return dict(row)


def energy_timeline_rows(
    *,
    expected_rows: Sequence[ExpectedEnergySample],
    backend_rows: Sequence[BackendMeterDiagnosticRow],
    payload_rows: Sequence[PayloadDiagnosticRow],
    qml_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    count = max(len(expected_rows), len(backend_rows), len(payload_rows), len(qml_rows))
    rows: list[dict[str, Any]] = []
    for index in range(count):
        expected = _row_dict(expected_rows[index]) if index < len(expected_rows) else {}
        backend = _row_dict(backend_rows[index]) if index < len(backend_rows) else {}
        payload = _row_dict(payload_rows[index]) if index < len(payload_rows) else {}
        qml = _row_dict(qml_rows[index]) if index < len(qml_rows) else {}
        rows.append(
            {
                "sample_time_ms": expected.get(
                    "sample_time_ms",
                    backend.get("sample_time_ms", payload.get("payload_sample_time_ms", "")),
                ),
                "segment": expected.get("segment", ""),
                "expected_energy": expected.get("expected_energy", ""),
                "backend_energy": backend.get("voice_visual_energy", ""),
                "backend_rms": backend.get("rms", ""),
                "backend_peak": backend.get("peak", ""),
                "backend_monotonic_time_ms": backend.get("monotonic_time_ms", ""),
                "payload_energy": payload.get("payload_voice_visual_energy", ""),
                "payload_monotonic_time_ms": payload.get("payload_monotonic_time_ms", ""),
                "payload_active": str(payload.get("payload_voice_visual_active", "")).lower(),
                "payload_source": payload.get("payload_source", ""),
                "sample_age_ms": payload.get("sample_age_ms", ""),
                "qml_received_energy": qml.get("qmlReceivedVoiceVisualEnergy", ""),
                "qml_received_time_ms": qml.get("qmlReceivedMonotonicTimeMs", ""),
                "qml_energy_sample_age_ms": qml.get("qmlEnergySampleAgeMs", ""),
                "qml_final_speaking_energy": qml.get("qmlFinalSpeakingEnergy", ""),
                "qml_final_time_ms": qml.get("qmlFinalMonotonicTimeMs", ""),
                "qml_speech_energy_source": qml.get("qmlSpeechEnergySource", ""),
                "qml_voice_visual_active": str(qml.get("qmlVoiceVisualActive", "")).lower(),
                "qml_anchor_paint_count": qml.get("qmlAnchorPaintCount", ""),
                "qml_last_paint_time_ms": qml.get("qmlLastPaintTimeMs", ""),
                "qml_paint_monotonic_time_ms": qml.get("qmlPaintMonotonicTimeMs", ""),
                "raw_audio_present": "false",
            }
        )
    return rows


def energy_timeline_csv_text(
    *,
    expected_rows: Sequence[ExpectedEnergySample],
    backend_rows: Sequence[BackendMeterDiagnosticRow],
    payload_rows: Sequence[PayloadDiagnosticRow],
    qml_rows: Sequence[dict[str, Any]],
) -> str:
    rows = energy_timeline_rows(
        expected_rows=expected_rows,
        backend_rows=backend_rows,
        payload_rows=payload_rows,
        qml_rows=qml_rows,
    )
    output = io.StringIO()
    fieldnames = [
        "sample_time_ms",
        "segment",
        "expected_energy",
        "backend_energy",
        "backend_rms",
        "backend_peak",
        "backend_monotonic_time_ms",
        "payload_energy",
        "payload_monotonic_time_ms",
        "payload_active",
        "payload_source",
        "sample_age_ms",
        "qml_received_energy",
        "qml_received_time_ms",
        "qml_energy_sample_age_ms",
        "qml_final_speaking_energy",
        "qml_final_time_ms",
        "qml_speech_energy_source",
        "qml_voice_visual_active",
        "qml_anchor_paint_count",
        "qml_last_paint_time_ms",
        "qml_paint_monotonic_time_ms",
        "raw_audio_present",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def report_markdown(report: dict[str, Any]) -> str:
    classification = ", ".join(report.get("classification", []))
    ranges = report.get("ranges", {})
    correlations = report.get("correlations", {})
    latency = report.get("latency_ms", {})
    lines = [
        "# Voice Reactive Chain Probe",
        "",
        f"- Mode: `{report.get('mode', 'unknown')}`",
        f"- Playback ID: `{report.get('playback_id', '')}`",
        f"- Source: `{report.get('source', PCM_STREAM_SOURCE)}`",
        f"- Classification: `{classification}`",
        f"- Privacy: scalar-only, raw_audio_present={str(report.get('raw_audio_present', False)).lower()}",
        "",
        "## Energy Ranges",
    ]
    for name in [
        "expected",
        "backend_meter",
        "ui_payload",
        "qml_received",
        "qml_finalSpeakingEnergy",
    ]:
        stage = ranges.get(name, {})
        lines.append(
            f"- {name}: min={stage.get('min')}, max={stage.get('max')}, span={stage.get('span')}, count={stage.get('count')}"
        )
    lines.extend(["", "## Correlations"])
    for key, value in correlations.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Latency"])
    for key, value in latency.items():
        lines.append(f"- {key}: {value} ms")
    lines.extend(
        [
            "",
            "## Interpretation",
            "- `backend_meter_flat`: expected PCM varies but the backend meter did not.",
            "- `payload_handoff_flat`: backend varies but the UI payload did not.",
            "- `qml_receive_flat`: payload varies but QML received energy did not.",
            "- `anchor_mapping_flat`: QML received energy varies but finalSpeakingEnergy did not.",
            "- `qml_paint_missing`: finalSpeakingEnergy varies but no anchor paint was observed.",
            "- `chain_pass`: scalar energy survived the measured chain with bounded latency.",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "BackendMeterDiagnosticRow",
    "ExpectedEnergySample",
    "PayloadDiagnosticRow",
    "SyntheticPCMStimulus",
    "build_payload_diagnostics",
    "build_reactive_chain_report",
    "classify_reactive_chain",
    "correlation",
    "energy_timeline_csv_text",
    "energy_timeline_rows",
    "generate_synthetic_pcm_stimulus",
    "report_markdown",
    "run_backend_meter_diagnostics",
]
