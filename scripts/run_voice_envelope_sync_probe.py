from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_DIR = Path("reports") / "voice_playback_envelope"
REPORT_PATH = REPORT_DIR / "voice_envelope_sync_probe_report.json"
SAMPLES_PATH = REPORT_DIR / "envelope_sync_samples.csv"


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def calibrated_sample_time_ms(
    visual_time_ms: int | float,
    *,
    estimated_output_latency_ms: int | float,
    envelope_visual_offset_ms: int | float,
    enabled: bool = True,
) -> tuple[int, int]:
    visual = max(0, int(round(float(visual_time_ms))))
    if not enabled:
        return visual, 0
    latency = _clamp_int(
        estimated_output_latency_ms,
        default=120,
        minimum=0,
        maximum=500,
    )
    offset = _clamp_int(
        envelope_visual_offset_ms,
        default=0,
        minimum=-500,
        maximum=500,
    )
    applied = -latency - offset
    return max(0, visual + applied), applied


def interpolate_energy(samples: list[dict[str, float]], target_time_ms: int) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples, key=lambda sample: sample["sample_time_ms"])
    if target_time_ms <= ordered[0]["sample_time_ms"]:
        return float(ordered[0]["energy"])
    for index, sample in enumerate(ordered[:-1]):
        next_sample = ordered[index + 1]
        start = float(sample["sample_time_ms"])
        end = float(next_sample["sample_time_ms"])
        if start <= target_time_ms <= end:
            span = max(1.0, end - start)
            alpha = (target_time_ms - start) / span
            return float(sample["energy"]) + (
                float(next_sample["energy"]) - float(sample["energy"])
            ) * alpha
    return float(ordered[-1]["energy"])


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    scalar_envelope = [
        {"sample_time_ms": 120.0, "energy": 0.10},
        {"sample_time_ms": 160.0, "energy": 0.20},
        {"sample_time_ms": 200.0, "energy": 0.78},
        {"sample_time_ms": 240.0, "energy": 0.34},
        {"sample_time_ms": 280.0, "energy": 0.16},
        {"sample_time_ms": 320.0, "energy": 0.08},
    ]
    scenarios = [
        {
            "name": "default_latency",
            "visual_time_ms": 300,
            "estimated_output_latency_ms": 100,
            "envelope_visual_offset_ms": 0,
            "expected_sample_time_ms": 200,
        },
        {
            "name": "advance_visual_negative_offset",
            "visual_time_ms": 300,
            "estimated_output_latency_ms": 100,
            "envelope_visual_offset_ms": -40,
            "expected_sample_time_ms": 240,
        },
        {
            "name": "delay_visual_positive_offset",
            "visual_time_ms": 300,
            "estimated_output_latency_ms": 100,
            "envelope_visual_offset_ms": 40,
            "expected_sample_time_ms": 160,
        },
        {
            "name": "clamped_extreme_offset",
            "visual_time_ms": 700,
            "estimated_output_latency_ms": 900,
            "envelope_visual_offset_ms": -900,
            "expected_sample_time_ms": 700,
        },
    ]

    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for scenario in scenarios:
        sample_time, applied = calibrated_sample_time_ms(
            scenario["visual_time_ms"],
            estimated_output_latency_ms=scenario["estimated_output_latency_ms"],
            envelope_visual_offset_ms=scenario["envelope_visual_offset_ms"],
        )
        sampled_energy = interpolate_energy(scalar_envelope, sample_time)
        passed = sample_time == scenario["expected_sample_time_ms"]
        if not passed:
            failures.append(
                f"{scenario['name']}: expected {scenario['expected_sample_time_ms']} got {sample_time}"
            )
        rows.append(
            {
                "scenario": scenario["name"],
                "visual_time_ms": scenario["visual_time_ms"],
                "estimated_output_latency_ms": scenario[
                    "estimated_output_latency_ms"
                ],
                "envelope_visual_offset_ms": scenario["envelope_visual_offset_ms"],
                "applied_offset_ms": applied,
                "sample_time_ms": sample_time,
                "sampled_energy": round(sampled_energy, 6),
                "passed": passed,
            }
        )

    with SAMPLES_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    report = {
        "probe": "voice_envelope_sync",
        "version": "Voice-L0.5",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "formula": (
            "sample_time_ms = playback_visual_time_ms - "
            "estimated_output_latency_ms - envelope_visual_offset_ms"
        ),
        "sign_convention": {
            "negative_envelope_visual_offset_ms": "advance visual reaction",
            "positive_envelope_visual_offset_ms": "delay visual reaction",
        },
        "raw_audio_present": False,
        "raw_audio_logged": False,
        "scenario_count": len(rows),
        "failures": failures,
        "passed": not failures,
        "rows": rows,
        "artifacts": {
            "samples_csv": str(SAMPLES_PATH),
            "report_json": str(REPORT_PATH),
        },
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
