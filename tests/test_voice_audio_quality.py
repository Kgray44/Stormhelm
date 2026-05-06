from __future__ import annotations

import json
import math
import struct

from stormhelm.core.voice.audio_quality import PlaybackAudioQualityTracker
from stormhelm.core.voice.audio_quality import classify_audio_quality
from stormhelm.core.voice.audio_quality import safe_playback_buffer_policy


def _pcm16_sine(
    *,
    amplitude: float = 0.5,
    sample_rate_hz: int = 24_000,
    duration_ms: int = 50,
    frequency_hz: float = 440.0,
) -> bytes:
    frames = max(1, int(sample_rate_hz * duration_ms / 1000.0))
    values = []
    for index in range(frames):
        sample = int(
            max(-1.0, min(1.0, math.sin(index * frequency_hz * math.tau / sample_rate_hz) * amplitude))
            * 32767
        )
        values.append(sample)
    return struct.pack("<" + "h" * len(values), *values)


def test_audio_quality_report_classifies_underrun_and_chunk_gap() -> None:
    tracker = PlaybackAudioQualityTracker(
        playback_id="playback-a",
        expected_sample_rate_hz=24_000,
        expected_channels=1,
        expected_sample_width_bytes=2,
        streaming_min_buffer_ms=80,
    )
    first = _pcm16_sine(duration_ms=50)
    second = _pcm16_sine(duration_ms=50)

    tracker.analyze_chunk(
        first,
        chunk_index=0,
        submit_time_ms=1000.0,
        queue_depth_before=0,
        queued_duration_ms_before=0.0,
    )
    tracker.analyze_chunk(
        second,
        chunk_index=1,
        submit_time_ms=1175.0,
        queue_depth_before=0,
        queued_duration_ms_before=0.0,
    )
    report = tracker.summary()

    assert report["chunk_gap_count"] == 1
    assert report["underrun_count"] >= 1
    assert "playback_buffer_underrun" in report["playback_artifact_reasons"]
    assert "tts_chunk_gap" in report["playback_artifact_reasons"]
    assert classify_audio_quality(report) == "playback_buffer_underrun"


def test_audio_quality_report_measures_buffered_chunk_gap_without_artifact() -> None:
    tracker = PlaybackAudioQualityTracker(
        playback_id="playback-buffered-gap",
        expected_sample_rate_hz=24_000,
        expected_channels=1,
        expected_sample_width_bytes=2,
        streaming_min_buffer_ms=80,
    )
    first = _pcm16_sine(duration_ms=50)
    second = _pcm16_sine(duration_ms=50)

    tracker.analyze_chunk(
        first,
        chunk_index=0,
        submit_time_ms=1000.0,
        queue_depth_before=10,
        queued_duration_ms_before=500.0,
    )
    tracker.analyze_chunk(
        second,
        chunk_index=1,
        submit_time_ms=1250.0,
        queue_depth_before=12,
        queued_duration_ms_before=450.0,
    )
    report = tracker.summary()

    assert report["chunk_gap_count"] == 1
    assert report["chunk_gap_audio_risk_count"] == 0
    assert "tts_chunk_gap" not in report["playback_artifact_reasons"]
    assert report["audio_quality_status"] == "pass"


def test_audio_quality_report_detects_format_mismatch_and_discontinuity() -> None:
    tracker = PlaybackAudioQualityTracker(
        playback_id="playback-b",
        expected_sample_rate_hz=24_000,
        expected_channels=1,
        expected_sample_width_bytes=2,
    )
    loud_positive = struct.pack("<" + "h" * 1200, *([30_000] * 1200))
    loud_negative = struct.pack("<" + "h" * 1200, *([-30_000] * 1200))

    tracker.analyze_chunk(
        loud_positive,
        chunk_index=0,
        submit_time_ms=10.0,
        actual_sample_rate_hz=48_000,
    )
    tracker.analyze_chunk(loud_negative, chunk_index=1, submit_time_ms=60.0)
    report = tracker.summary()

    assert report["sample_rate_mismatch_flag"] is True
    assert report["chunk_boundary_discontinuity_count"] >= 1
    assert report["clipping_count"] >= 0
    assert "sample_rate_mismatch" in report["playback_artifact_reasons"]
    assert "chunk_boundary_discontinuity" in report["playback_artifact_reasons"]


def test_audio_quality_report_is_scalar_only_and_keeps_raw_audio_out() -> None:
    tracker = PlaybackAudioQualityTracker(
        playback_id="playback-c",
        speech_request_id="speech-c",
        expected_sample_rate_hz=24_000,
        expected_channels=1,
        expected_sample_width_bytes=2,
    )
    tracker.analyze_chunk(_pcm16_sine(), chunk_index=0, submit_time_ms=1.0)
    payload = tracker.summary()
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["raw_audio_present"] is False
    assert "pcm_bytes" not in encoded
    assert "audio_bytes" not in encoded
    assert "raw_samples" not in encoded
    assert "sample_values" not in encoded


def test_jitter_buffer_policy_is_bounded_and_prefers_small_safe_buffer() -> None:
    policy = safe_playback_buffer_policy(
        jitter_buffer_ms=120,
        min_buffer_ms=80,
        max_buffer_ms=400,
    )

    assert policy["streaming_jitter_buffer_ms"] == 120
    assert policy["streaming_min_buffer_ms"] == 80
    assert policy["streaming_max_buffer_ms"] == 400
    assert policy["bounded"] is True
    assert policy["raw_audio_present"] is False
