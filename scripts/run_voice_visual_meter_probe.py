from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from stormhelm.core.voice.voice_visual_meter import VoiceVisualMeter


def _pcm_constant(level: int, *, samples: int) -> bytes:
    values = [level if index % 2 == 0 else -level for index in range(samples)]
    return struct.pack("<" + "h" * len(values), *values)


def _pcm_sine(
    *,
    amplitude: int,
    sample_rate_hz: int = 24000,
    duration_ms: int = 1000,
    frequency_hz: float = 440.0,
) -> bytes:
    sample_count = int(sample_rate_hz * duration_ms / 1000)
    values = [
        int(amplitude * math.sin(2.0 * math.pi * frequency_hz * index / sample_rate_hz))
        for index in range(sample_count)
    ]
    return struct.pack("<" + "h" * len(values), *values)


def _sample_meter(meter: VoiceVisualMeter, *, seconds: float, hz: int = 60) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for index in range(int(seconds * hz)):
        frame = meter.sample_due(now_monotonic=index / hz)
        if frame is not None:
            frames.append(frame.to_payload())
    return frames


def _run_probe() -> dict[str, Any]:
    sample_rate_hz = 24000
    preroll_meter = VoiceVisualMeter(
        playback_id="voice-visual-meter-probe",
        update_hz=60,
        sample_rate_hz=sample_rate_hz,
        startup_preroll_ms=350,
        attack_ms=60,
        release_ms=160,
        noise_floor=0.015,
        gain=2.0,
        max_startup_wait_ms=800,
    )
    preroll_meter.feed_preroll_pcm(_pcm_sine(amplitude=9000, duration_ms=350))
    preroll_payload = preroll_meter.to_payload(active=False, now_monotonic=0.0)

    meter = VoiceVisualMeter(
        playback_id="voice-visual-meter-probe",
        update_hz=60,
        sample_rate_hz=sample_rate_hz,
        startup_preroll_ms=350,
        attack_ms=60,
        release_ms=160,
        noise_floor=0.015,
        gain=2.0,
        max_startup_wait_ms=800,
    )
    meter.feed_pcm(
        _pcm_constant(0, samples=12_000)
        + _pcm_constant(18_000, samples=12_000)
        + _pcm_constant(0, samples=12_000)
    )
    meter.start_playback(start_monotonic=0.0)
    frames = _sample_meter(meter, seconds=1.5)
    energies = [float(frame["voice_visual_energy"]) for frame in frames]
    emit_rate_hz = len(frames) / 1.5 if frames else 0.0
    first_energy = energies[0] if energies else 0.0
    attack_energy = energies[40] if len(energies) > 40 else 0.0
    release_energy = energies[74] if len(energies) > 74 else 0.0
    timeout_meter = VoiceVisualMeter(
        playback_id="voice-visual-timeout-probe",
        update_hz=60,
        sample_rate_hz=sample_rate_hz,
        startup_preroll_ms=350,
        max_startup_wait_ms=800,
    )
    timeout_meter.feed_preroll_pcm(_pcm_constant(6000, samples=1200))
    timeout_status = timeout_meter.preroll_status(elapsed_ms=801)

    return {
        "probe": "voice_visual_meter",
        "source": "pcm_stream_meter",
        "sample_rate_hz": 60,
        "frame_count": len(frames),
        "emit_rate_hz": round(emit_rate_hz, 3),
        "energy_min": round(min(energies), 4) if energies else 0.0,
        "energy_max": round(max(energies), 4) if energies else 0.0,
        "first_energy": round(first_energy, 4),
        "attack_energy": round(attack_energy, 4),
        "release_energy": round(release_energy, 4),
        "preroll_energy": preroll_payload["voice_visual_energy"],
        "preroll_ready": preroll_payload["voice_visual_energy"] > 0.10,
        "sample_rate_ok": 54 <= len(frames) / 1.5 <= 66,
        "attack_release_ok": attack_energy > first_energy + 0.20
        and release_energy < attack_energy,
        "timeout_guard_ok": bool(timeout_status["startup_preroll_timeout"]),
        "raw_audio_present": False,
        "raw_audio_included": False,
        "frames": frames[:12],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Stormhelm voice visual meter probe.")
    parser.add_argument(
        "--output",
        default=str(ROOT / "voice_visual_meter_probe_report.json"),
        help="Path for the JSON report.",
    )
    args = parser.parse_args()
    report = _run_probe()
    output = Path(args.output)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: report[key] for key in report if key != "frames"}, indent=2))
    return 0 if report["sample_rate_ok"] and report["attack_release_ok"] and report["preroll_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
