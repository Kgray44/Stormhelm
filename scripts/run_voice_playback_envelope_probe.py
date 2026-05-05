from __future__ import annotations

import csv
import json
import math
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stormhelm.core.voice.visualizer import VoicePlaybackEnvelopeFollower


OUTPUT_DIR = ROOT / "reports" / "voice_playback_envelope"
REPORT_PATH = OUTPUT_DIR / "voice_envelope_probe_report.json"
SAMPLES_PATH = OUTPUT_DIR / "voice_envelope_samples.csv"


def _speech_like_pcm(
    *,
    duration_seconds: float = 1.8,
    sample_rate_hz: int = 24_000,
) -> bytes:
    values: list[int] = []
    total = int(duration_seconds * sample_rate_hz)
    for index in range(total):
        t = index / sample_rate_hz
        syllable = 0.5 + math.sin(t * math.tau * 4.7 + math.sin(t * 3.1) * 0.8) * 0.5
        phrase = 0.5 + math.sin(t * math.tau * 1.4 + 0.6) * 0.5
        breath = 0.5 + math.sin(t * math.tau * 0.62 + 1.2) * 0.5
        gap = 0.28 if 0.72 < t < 0.88 else 1.0
        amplitude = (0.08 + syllable * 0.42 + phrase * 0.22 + breath * 0.10) * gap
        carrier = (
            math.sin(t * math.tau * 180.0)
            + math.sin(t * math.tau * 310.0 + 0.4) * 0.45
            + math.sin(t * math.tau * 520.0 + 1.1) * 0.22
        )
        values.append(int(max(-1.0, min(1.0, carrier * amplitude * 0.42)) * 32767))
    return struct.pack("<" + "h" * len(values), *values)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sample_rate_hz = 24_000
    follower = VoicePlaybackEnvelopeFollower(
        playback_id="voice-envelope-probe",
        sample_rate_hz=sample_rate_hz,
        channels=1,
        sample_width_bytes=2,
        envelope_sample_rate_hz=60,
        max_duration_ms=5000,
        estimated_output_latency_ms=80,
    )
    pcm = _speech_like_pcm(sample_rate_hz=sample_rate_hz)
    chunk_bytes = int(sample_rate_hz * 0.02) * 2
    produced = []
    for offset in range(0, len(pcm), chunk_bytes):
        produced.extend(
            follower.feed_pcm(
                pcm[offset : offset + chunk_bytes],
                submitted_at_monotonic_ms=1_000_000 + (offset // 2) / sample_rate_hz * 1000,
            )
        )

    payload = follower.to_bridge_payload(max_samples=24)
    samples = [sample.to_dict() for sample in produced]
    sample_times = [sample["sample_time_ms"] for sample in samples]
    energies = [sample["smoothed_energy"] for sample in samples]
    intervals = [
        sample_times[index] - sample_times[index - 1]
        for index in range(1, len(sample_times))
    ]
    report = {
        "probe": "Voice-L0.2 playback envelope follower",
        "playback_id": payload["playback_id"],
        "envelope_supported": payload["envelope_supported"],
        "envelope_available": payload["envelope_available"],
        "envelope_source": payload["envelope_source"],
        "sample_rate_hz": payload["envelope_sample_rate_hz"],
        "sample_count": len(samples),
        "duration_ms": sample_times[-1] if sample_times else 0,
        "min_energy": min(energies) if energies else 0.0,
        "max_energy": max(energies) if energies else 0.0,
        "latest_voice_energy": payload["latest_voice_energy"],
        "max_sample_interval_ms": max(intervals) if intervals else 0,
        "timestamps_monotonic": sample_times == sorted(sample_times),
        "ring_samples_returned": len(payload["envelope_samples_recent"]),
        "samples_dropped": payload["samples_dropped"],
        "estimated_output_latency_ms": payload["estimated_output_latency_ms"],
        "raw_audio_present": False,
        "raw_audio_logged": False,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    with SAMPLES_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_time_ms",
                "monotonic_time_ms",
                "rms",
                "peak",
                "energy",
                "smoothed_energy",
                "source",
                "valid",
            ],
        )
        writer.writeheader()
        for sample in samples:
            writer.writerow(
                {
                    "sample_time_ms": sample["sample_time_ms"],
                    "monotonic_time_ms": sample["monotonic_time_ms"],
                    "rms": sample["rms"],
                    "peak": sample["peak"],
                    "energy": sample["energy"],
                    "smoothed_energy": sample["smoothed_energy"],
                    "source": sample["source"],
                    "valid": sample["valid"],
                }
            )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
