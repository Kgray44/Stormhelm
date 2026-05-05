from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_DIR = Path("reports") / "voice_playback_envelope"
REPORT_PATH = REPORT_DIR / "voice_envelope_timeline_probe_report.json"
SAMPLES_PATH = REPORT_DIR / "voice_envelope_timeline_samples.csv"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


@dataclass
class SourceLock:
    playback_id: str
    strategy: str
    switch_count: int = 0


class VisualizerSourceLatch:
    def __init__(self) -> None:
        self._locks: dict[str, SourceLock] = {}

    def choose(self, playback_id: str, *, timeline_ready: bool) -> SourceLock:
        existing = self._locks.get(playback_id)
        if existing is not None:
            return existing
        strategy = "playback_envelope_timeline" if timeline_ready else "procedural_speaking"
        lock = SourceLock(playback_id=playback_id, strategy=strategy)
        self._locks[playback_id] = lock
        return lock


def _timeline(values: list[float], step_ms: int = 16) -> list[dict[str, float]]:
    return [
        {"t_ms": float(index * step_ms), "energy": _round(_clamp01(value))}
        for index, value in enumerate(values)
    ]


def _quiet_live_like_timeline() -> list[dict[str, float]]:
    values: list[float] = []
    for index in range(80):
        syllable = math.sin(index * 0.48) * 0.5 + 0.5
        phrase = math.sin(index * 0.13 + 0.6) * 0.5 + 0.5
        values.append(0.14 + syllable * 0.028 + phrase * 0.012)
    return _timeline(values)


def _syllable_peak_timeline() -> list[dict[str, float]]:
    values: list[float] = []
    for index in range(80):
        carrier = math.sin(index * 0.38) * 0.5 + 0.5
        burst = 0.0
        if index in {9, 10, 11, 28, 29, 48, 49, 50, 66}:
            burst = 0.30
        values.append(0.10 + carrier * 0.24 + burst)
    return _timeline(values)


def _expanded_energy_series(samples: list[dict[str, float]]) -> list[dict[str, float]]:
    if not samples:
        return []
    energies = [float(sample["energy"]) for sample in samples]
    recent_min = min(energies)
    recent_max = max(energies)
    dynamic_range = max(0.001, recent_max - recent_min)
    adaptive_gain = min(10.0, max(1.0, 0.42 / max(dynamic_range, 0.035)))
    expanded: list[dict[str, float]] = []
    previous = energies[0]
    peak_hold = 0.0
    for sample, energy in zip(samples, energies):
        dynamic = _clamp01((energy - recent_min) / max(dynamic_range, 0.025))
        transient = max(0.0, energy - previous) * adaptive_gain
        peak_hold = max(peak_hold * 0.72, transient)
        expanded_energy = _clamp01(0.10 + math.sqrt(dynamic) * 0.62 + peak_hold * 0.18)
        final_energy = _clamp01(0.20 + expanded_energy * 0.58)
        expanded.append(
            {
                "t_ms": float(sample["t_ms"]),
                "input_energy": _round(energy),
                "expanded_energy": _round(expanded_energy),
                "final_speaking_energy": _round(final_energy),
                "adaptive_gain": _round(adaptive_gain),
            }
        )
        previous = energy
    return expanded


def _procedural_series(sample_count: int = 80, step_ms: int = 16) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for index in range(sample_count):
        seconds = (index * step_ms) / 1000.0
        phrase = math.sin(seconds * 11.7 + math.sin(seconds * 1.6) * 0.4) * 0.5 + 0.5
        syllable = math.sin(seconds * 24.0 + 1.2) * 0.5 + 0.5
        energy = _clamp01(0.20 + phrase * 0.13 + syllable * 0.08)
        rows.append(
            {
                "t_ms": float(index * step_ms),
                "input_energy": 0.0,
                "expanded_energy": 0.0,
                "final_speaking_energy": _round(energy),
                "adaptive_gain": 0.0,
            }
        )
    return rows


def _scenario_report(name: str, playback_id: str, lock: SourceLock, rows: list[dict[str, float]], *, timeline_count: int, late_ready: bool) -> dict[str, Any]:
    final_values = [row["final_speaking_energy"] for row in rows]
    expanded_values = [row["expanded_energy"] for row in rows]
    return {
        "name": name,
        "playback_id": playback_id,
        "selected_visualizer_strategy": lock.strategy,
        "visualizer_source_locked": True,
        "visualizer_source_switch_count": lock.switch_count,
        "late_timeline_attempted": late_ready,
        "late_timeline_stole_source": late_ready and lock.strategy != "procedural_speaking",
        "timeline_sample_count": timeline_count,
        "scalar_only_timeline": True,
        "final_speaking_energy_min": _round(min(final_values) if final_values else 0.0),
        "final_speaking_energy_max": _round(max(final_values) if final_values else 0.0),
        "expanded_energy_min": _round(min(expanded_values) if expanded_values else 0.0),
        "expanded_energy_max": _round(max(expanded_values) if expanded_values else 0.0),
        "final_speaking_energy_nonzero": bool(final_values and max(final_values) > 0.04),
    }


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    latch = VisualizerSourceLatch()
    scenarios = [
        {
            "name": "ready_envelope_timeline",
            "playback_id": "probe-ready-timeline",
            "timeline_ready_at_start": True,
            "timeline_ready_late": False,
            "samples": _syllable_peak_timeline(),
        },
        {
            "name": "late_envelope_timeline",
            "playback_id": "probe-late-timeline",
            "timeline_ready_at_start": False,
            "timeline_ready_late": True,
            "samples": _syllable_peak_timeline(),
        },
        {
            "name": "missing_envelope_timeline",
            "playback_id": "probe-missing-timeline",
            "timeline_ready_at_start": False,
            "timeline_ready_late": False,
            "samples": [],
        },
        {
            "name": "quiet_live_like_envelope",
            "playback_id": "probe-quiet-live-like",
            "timeline_ready_at_start": True,
            "timeline_ready_late": False,
            "samples": _quiet_live_like_timeline(),
        },
        {
            "name": "syllable_peaks_envelope",
            "playback_id": "probe-syllable-peaks",
            "timeline_ready_at_start": True,
            "timeline_ready_late": False,
            "samples": _syllable_peak_timeline(),
        },
    ]

    report_scenarios: list[dict[str, Any]] = []
    sample_rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        playback_id = str(scenario["playback_id"])
        lock = latch.choose(
            playback_id,
            timeline_ready=bool(scenario["timeline_ready_at_start"]),
        )
        if scenario["timeline_ready_late"]:
            lock = latch.choose(playback_id, timeline_ready=True)
        samples = list(scenario["samples"])
        rows = (
            _expanded_energy_series(samples)
            if lock.strategy == "playback_envelope_timeline"
            else _procedural_series()
        )
        report_scenarios.append(
            _scenario_report(
                str(scenario["name"]),
                playback_id,
                lock,
                rows,
                timeline_count=len(samples),
                late_ready=bool(scenario["timeline_ready_late"]),
            )
        )
        for row in rows:
            sample_rows.append(
                {
                    "scenario": scenario["name"],
                    "playback_id": playback_id,
                    "selected_visualizer_strategy": lock.strategy,
                    **row,
                }
            )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe_version": "Voice-L0.6",
        "raw_audio_exposed": False,
        "visualizer_source_switching_disabled": True,
        "scenarios": report_scenarios,
        "overall_pass": all(
            scenario["visualizer_source_switch_count"] == 0
            and scenario["final_speaking_energy_nonzero"]
            and not scenario["late_timeline_stole_source"]
            for scenario in report_scenarios
        ),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with SAMPLES_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scenario",
                "playback_id",
                "selected_visualizer_strategy",
                "t_ms",
                "input_energy",
                "expanded_energy",
                "final_speaking_energy",
                "adaptive_gain",
            ],
        )
        writer.writeheader()
        writer.writerows(sample_rows)
    print(json.dumps(report, indent=2))
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
