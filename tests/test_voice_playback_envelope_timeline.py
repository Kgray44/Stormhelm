from __future__ import annotations

from stormhelm.core.voice.visualizer import VoicePlaybackEnvelopeBuffer
from stormhelm.core.voice.visualizer import VoicePlaybackEnvelopeSample


def test_playback_envelope_buffer_exports_scalar_timeline_only() -> None:
    buffer = VoicePlaybackEnvelopeBuffer(
        playback_id="timeline-playback",
        max_duration_ms=1000,
        sample_rate_hz=60,
    )
    for index in range(6):
        buffer.append(
            VoicePlaybackEnvelopeSample(
                playback_id="timeline-playback",
                sample_time_ms=index * 16,
                monotonic_time_ms=900_000 + index * 16,
                rms=0.10 + index * 0.01,
                peak=0.18 + index * 0.01,
                energy=0.14 + index * 0.02,
                smoothed_energy=0.15 + index * 0.02,
                sample_rate=24000,
                channels=1,
            )
        )

    payload = buffer.to_bridge_payload(playback_time_ms=48, max_samples=4)
    timeline = payload["envelope_timeline_samples"]

    assert payload["envelope_timeline_available"] is True
    assert payload["envelope_timeline_sample_rate_hz"] == 60
    assert payload["envelope_timeline_sample_count"] == len(timeline)
    assert [sample["t_ms"] for sample in timeline] == sorted(
        sample["t_ms"] for sample in timeline
    )
    assert all(set(sample) == {"t_ms", "energy"} for sample in timeline)
    assert "raw_audio" not in str(timeline).lower()
    assert "audio_bytes" not in str(payload)
