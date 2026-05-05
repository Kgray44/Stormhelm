from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "reports" / "stormforge_envelope_dynamics"
REPORT_PATH = OUTPUT_DIR / "envelope_dynamics_probe_report.json"
SAMPLES_PATH = OUTPUT_DIR / "envelope_dynamics_samples.csv"


def clamp01(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def step_toward(current: float, target: float, max_fall: float, max_rise: float) -> float:
    delta = target - current
    if delta > max_rise:
        return clamp01(current + max_rise)
    if delta < -max_fall:
        return clamp01(current - max_fall)
    return clamp01(target)


def visual_drive_for_energy(energy: float) -> float:
    value = clamp01(energy)
    if value <= 0.0:
        return 0.0
    return clamp01(0.080 + math.sqrt(value) * 0.460)


@dataclass
class EnvelopeDynamicsSimulator:
    window_ms: int = 1600
    history: list[tuple[float, float]] = field(default_factory=list)
    expanded: float = 0.0
    dynamic_energy: float = 0.0
    transient: float = 0.0
    peak_hold: float = 0.0
    last_energy: float = 0.0
    last_sample_ms: float = 0.0
    final_energy: float = 0.0

    def procedural_energy(self, time_ms: float) -> float:
        seconds = time_ms / 1000.0
        phrase = 0.5 + math.sin(seconds * math.tau * 1.35) * 0.5
        syllable = 0.5 + math.sin(seconds * math.tau * 4.8 + math.sin(seconds * 1.1) * 0.6) * 0.5
        breath = 0.5 + math.sin(seconds * math.tau * 0.7 + 0.8) * 0.5
        return clamp01(0.070 + phrase * 0.105 + syllable * 0.060 + breath * 0.035)

    def sample(self, *, time_ms: float, energy: float, frame_ms: float = 16.667) -> dict[str, float | int]:
        frame_scale = max(0.5, min(2.4, frame_ms / 32.0))
        current = clamp01(energy)
        cutoff = time_ms - self.window_ms
        self.history = [(t, e) for t, e in self.history if t >= cutoff]
        if current > 0.006:
            self.history.append((time_ms, current))
        if len(self.history) > 96:
            self.history = self.history[-96:]

        if self.history:
            recent_min = min(e for _, e in self.history)
            recent_max = max(e for _, e in self.history)
        else:
            recent_min = 0.0
            recent_max = 0.0
        dynamic_range = max(0.0, recent_max - recent_min)
        range_active = dynamic_range >= 0.012
        normalized = clamp01((current - recent_min) / max(0.001, dynamic_range)) if range_active else 0.0
        adaptive_gain = max(1.2, min(8.0, 0.32 / max(0.001, dynamic_range))) if range_active else 1.0

        previous = self.last_energy if self.last_sample_ms > 0 else current
        derivative = current - previous
        derivative_energy = clamp01(abs(derivative) * adaptive_gain * 1.35) if range_active else 0.0
        transient_target = clamp01(max(0.0, derivative) * adaptive_gain * 2.0) if range_active else 0.0
        dynamic_target = clamp01((current - recent_min) * adaptive_gain) if range_active else 0.0
        self.transient = step_toward(self.transient, transient_target, 0.055 * frame_scale, 0.180 * frame_scale)
        expanded_target = (
            clamp01(math.pow(normalized, 0.74) * 0.56 + dynamic_target * 0.18 + self.transient * 0.22)
            if range_active
            else 0.0
        )
        self.dynamic_energy = step_toward(self.dynamic_energy, dynamic_target, 0.060 * frame_scale, 0.120 * frame_scale)
        self.expanded = step_toward(self.expanded, expanded_target, 0.075 * frame_scale, 0.140 * frame_scale)
        self.peak_hold = max(self.peak_hold - 0.045 * frame_scale, self.expanded, self.transient)

        procedural = self.procedural_energy(time_ms)
        visual_drive = visual_drive_for_energy(current)
        procedural_carrier = clamp01(procedural * 0.22)
        speaking_base = clamp01(0.135 + procedural_carrier * 0.52 + visual_drive * 0.10)
        target_final = clamp01(speaking_base + self.expanded * 0.48 + self.transient * 0.18 + visual_drive * 0.12)
        self.final_energy = step_toward(self.final_energy, target_final, 0.022 * frame_scale, 0.048 * frame_scale)

        self.last_energy = current
        self.last_sample_ms = time_ms
        return {
            "time_ms": round(time_ms, 3),
            "input_energy": round(current, 6),
            "recent_min": round(recent_min, 6),
            "recent_max": round(recent_max, 6),
            "dynamic_range": round(dynamic_range, 6),
            "adaptive_gain": round(adaptive_gain, 6),
            "dynamic_energy": round(self.dynamic_energy, 6),
            "expanded_energy": round(self.expanded, 6),
            "transient_energy": round(self.transient, 6),
            "derivative_energy": round(derivative_energy, 6),
            "speaking_base_energy": round(speaking_base, 6),
            "procedural_carrier_energy": round(procedural_carrier, 6),
            "final_speaking_energy": round(self.final_energy, 6),
        }


def scenario_values(name: str, frames: int, hz: int) -> Iterable[float]:
    for index in range(frames):
        t = index / hz
        if name == "quiet_live_like":
            yield 0.160 + math.sin(t * math.tau * 3.8) * 0.017 + math.sin(t * math.tau * 7.3) * 0.004
        elif name == "louder":
            yield 0.320 + math.sin(t * math.tau * 3.2) * 0.120 + math.sin(t * math.tau * 6.2) * 0.035
        elif name == "flat":
            yield 0.160
        elif name == "syllable_peaks":
            pulse = max(0.0, math.sin(t * math.tau * 4.6)) ** 2.4
            yield 0.130 + pulse * 0.090 + math.sin(t * math.tau * 1.1) * 0.012
        elif name == "gaps":
            gap = 0.012 if 0.75 < t < 1.0 or 1.55 < t < 1.72 else 1.0
            yield (0.150 + max(0.0, math.sin(t * math.tau * 3.9)) * 0.045) * gap
        else:
            yield 0.0


def summarize(samples: list[dict[str, float | int]]) -> dict[str, float | int | bool]:
    steady_samples = [row for row in samples if float(row["time_ms"]) >= 500.0]
    measured = steady_samples or samples
    inputs = [float(row["input_energy"]) for row in measured]
    expanded = [float(row["expanded_energy"]) for row in measured]
    final = [float(row["final_speaking_energy"]) for row in measured]
    dynamic_ranges = [float(row["dynamic_range"]) for row in measured]
    final_range = max(final) - min(final) if final else 0.0
    input_range = max(inputs) - min(inputs) if inputs else 0.0
    expanded_range = max(expanded) - min(expanded) if expanded else 0.0
    plateau_score = 1.0 - clamp01(final_range / 0.22)
    continuity_jumps = [
        abs(final[index] - final[index - 1])
        for index in range(1, len(final))
    ]
    return {
        "input_min": round(min(inputs), 6) if inputs else 0.0,
        "input_max": round(max(inputs), 6) if inputs else 0.0,
        "input_range": round(input_range, 6),
        "expanded_min": round(min(expanded), 6) if expanded else 0.0,
        "expanded_max": round(max(expanded), 6) if expanded else 0.0,
        "expanded_range": round(expanded_range, 6),
        "final_min": round(min(final), 6) if final else 0.0,
        "final_max": round(max(final), 6) if final else 0.0,
        "final_range": round(final_range, 6),
        "max_dynamic_range": round(max(dynamic_ranges), 6) if dynamic_ranges else 0.0,
        "max_frame_jump": round(max(continuity_jumps), 6) if continuity_jumps else 0.0,
        "plateau_score": round(plateau_score, 6),
        "motion_continuity_score": round(1.0 - clamp01((max(continuity_jumps) if continuity_jumps else 0.0) / 0.16), 6),
        "passes": bool(final_range >= 0.06 if input_range >= 0.025 else max(expanded, default=0.0) <= 0.12),
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    hz = 60
    duration_s = 2.2
    frames = int(hz * duration_s)
    rows: list[dict[str, float | int | str]] = []
    scenario_reports: dict[str, dict[str, float | int | bool]] = {}
    for scenario in ("quiet_live_like", "louder", "flat", "syllable_peaks", "gaps"):
        simulator = EnvelopeDynamicsSimulator()
        samples: list[dict[str, float | int]] = []
        for index, energy in enumerate(scenario_values(scenario, frames, hz)):
            row = simulator.sample(time_ms=index * 1000.0 / hz, energy=energy, frame_ms=1000.0 / hz)
            samples.append(row)
            rows.append({"scenario": scenario, **row})
        scenario_reports[scenario] = summarize(samples)

    report = {
        "probe": "Voice-L0.3 Stormforge envelope dynamics",
        "version": "Voice-L0.3",
        "sample_rate_hz": hz,
        "raw_audio_present": False,
        "raw_audio_logged": False,
        "scenarios": scenario_reports,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with SAMPLES_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scenario",
                "time_ms",
                "input_energy",
                "recent_min",
                "recent_max",
                "dynamic_range",
                "adaptive_gain",
                "dynamic_energy",
                "expanded_energy",
                "transient_energy",
                "derivative_energy",
                "speaking_base_energy",
                "procedural_carrier_energy",
                "final_speaking_energy",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"artifact={REPORT_PATH}")
    print(f"samples={SAMPLES_PATH}")
    return 0 if all(item["passes"] for item in scenario_reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
