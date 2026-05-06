from __future__ import annotations

import math
import struct

import pytest

from stormhelm.core.voice.voice_visual_meter import VoiceVisualMeter


def _pcm_constant(level: int, *, samples: int = 2400) -> bytes:
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


def _sample_meter(meter: VoiceVisualMeter, *, seconds: float, hz: int = 60) -> list:
    frames = []
    ticks = int(seconds * hz)
    for index in range(ticks):
        frame = meter.sample_due(now_monotonic=index / hz)
        if frame is not None:
            frames.append(frame)
    return frames


def test_pcm_stream_meter_silence_produces_low_energy() -> None:
    meter = VoiceVisualMeter(playback_id="silence", update_hz=60)
    meter.feed_pcm(_pcm_constant(0, samples=24_000))
    meter.start_playback(start_monotonic=0.0)

    frames = _sample_meter(meter, seconds=0.5)

    assert frames
    assert max(frame.energy for frame in frames) <= 0.01
    assert frames[-1].to_payload()["raw_audio_present"] is False


def test_pcm_stream_meter_sine_wave_produces_stable_energy() -> None:
    meter = VoiceVisualMeter(playback_id="sine", update_hz=60, gain=2.0)
    meter.feed_pcm(_pcm_sine(amplitude=9000, duration_ms=1200))
    meter.start_playback(start_monotonic=0.0)

    frames = _sample_meter(meter, seconds=1.0)
    settled = [frame.energy for frame in frames[10:]]

    assert 54 <= len(frames) <= 61
    assert min(settled) > 0.20
    assert max(settled) - min(settled) < 0.16
    assert all(frame.source == "pcm_stream_meter" for frame in frames)


def test_pcm_stream_meter_attack_and_release_follow_amplitude_steps() -> None:
    meter = VoiceVisualMeter(
        playback_id="step",
        update_hz=60,
        attack_ms=60,
        release_ms=160,
        gain=2.0,
    )
    meter.feed_pcm(
        _pcm_constant(0, samples=12_000)
        + _pcm_constant(18_000, samples=12_000)
        + _pcm_constant(0, samples=12_000)
    )
    meter.start_playback(start_monotonic=0.0)

    frames = _sample_meter(meter, seconds=1.5)
    energies = [frame.energy for frame in frames]
    quiet = max(energies[:20])
    attack_start = energies[31]
    attack_settled = max(energies[40:55])
    release_start = energies[61]
    release_later = energies[74]

    assert quiet <= 0.02
    assert 0.02 < attack_start < attack_settled
    assert attack_settled > 0.60
    assert release_start > release_later
    assert release_later < 0.35


def test_pcm_stream_meter_speech_like_pcm_varies_energy() -> None:
    meter = VoiceVisualMeter(playback_id="speech-like", update_hz=60, gain=2.0)
    pcm = b"".join(
        _pcm_constant(level, samples=2400)
        for level in [0, 2600, 9000, 4200, 15_000, 1200, 0]
    )
    meter.feed_pcm(pcm)
    meter.start_playback(start_monotonic=0.0)

    frames = _sample_meter(meter, seconds=0.7)
    energies = [frame.energy for frame in frames]

    assert max(energies) > min(energies) + 0.45
    assert any(energy <= 0.03 for energy in energies[:8])
    assert any(energy >= 0.55 for energy in energies)


def test_pcm_stream_meter_preroll_primes_initial_energy_before_playback_start() -> None:
    meter = VoiceVisualMeter(playback_id="preroll", update_hz=60, startup_preroll_ms=350)
    meter.feed_preroll_pcm(_pcm_constant(14_000, samples=8400))

    preroll_payload = meter.to_payload(active=False, now_monotonic=0.0)
    meter.start_playback(start_monotonic=0.0)
    first_frame = meter.sample_due(now_monotonic=0.0)

    assert preroll_payload["voice_visual_energy"] > 0.25
    assert preroll_payload["voice_visual_active"] is False
    assert first_frame is not None
    assert first_frame.energy > 0.25
    assert first_frame.playback_position_ms == 0


def test_pcm_stream_meter_startup_wait_status_prevents_hanging() -> None:
    meter = VoiceVisualMeter(
        playback_id="timeout",
        update_hz=60,
        startup_preroll_ms=350,
        max_startup_wait_ms=800,
    )
    meter.feed_preroll_pcm(_pcm_constant(8000, samples=1200))

    early = meter.preroll_status(elapsed_ms=500)
    expired = meter.preroll_status(elapsed_ms=801)

    assert early["startup_preroll_ready"] is False
    assert early["startup_preroll_timeout"] is False
    assert expired["startup_preroll_ready"] is False
    assert expired["startup_preroll_timeout"] is True
    assert expired["voice_visual_disabled_reason"] == "startup_preroll_max_wait_elapsed"


def test_pcm_stream_meter_payload_never_exposes_raw_audio() -> None:
    meter = VoiceVisualMeter(playback_id="privacy", update_hz=60)
    meter.feed_pcm(_pcm_constant(20_000, samples=2400))
    meter.start_playback(start_monotonic=0.0)
    frame = meter.sample_due(now_monotonic=0.0)

    payload = frame.to_payload() if frame is not None else meter.to_payload()
    serialized = str(payload)

    assert payload["voice_visual_source"] == "pcm_stream_meter"
    assert payload["voice_visual_energy_source"] == "pcm_stream_meter"
    assert payload["raw_audio_present"] is False
    assert "20000" not in serialized
    assert "audio_bytes" not in serialized
    assert "data': b" not in serialized


def test_pcm_stream_meter_visual_offset_samples_future_audio_without_shifting_clock() -> None:
    meter = VoiceVisualMeter(
        playback_id="offset",
        update_hz=60,
        visual_offset_ms=-120,
        attack_ms=1,
        release_ms=1,
        gain=2.0,
    )
    meter.feed_pcm(_pcm_constant(0, samples=2400) + _pcm_constant(18_000, samples=4800))
    meter.start_playback(start_monotonic=0.0)

    frame = meter.sample_due(now_monotonic=0.0)

    assert frame is not None
    assert frame.playback_position_ms == 0
    assert frame.playback_clock_position_ms == 0
    assert frame.sample_time_ms == 120
    assert frame.visual_offset_ms == -120
    assert frame.energy > 0.50
    payload = frame.to_payload()
    assert payload["voice_visual_offset_ms"] == -120
    assert payload["voice_visual_sample_time_ms"] == 120
    assert payload["voice_visual_playback_clock_position_ms"] == 0
