from __future__ import annotations

import json
from statistics import mean

from stormhelm.core.voice.reactive_chain_probe import (
    build_payload_diagnostics,
    build_reactive_chain_report,
    classify_reactive_chain,
    energy_timeline_csv_text,
    generate_synthetic_pcm_stimulus,
    run_backend_meter_diagnostics,
)


def _avg(samples: list[float]) -> float:
    return mean(samples) if samples else 0.0


def test_synthetic_pcm_expected_energy_generation() -> None:
    stimulus = generate_synthetic_pcm_stimulus(sample_rate_hz=12_000, update_hz=60)

    assert stimulus.duration_ms == 4_000
    assert len(stimulus.pcm_bytes) == 12_000 * 4 * 2
    assert 235 <= len(stimulus.expected_timeline) <= 245

    silence = [
        sample.expected_energy
        for sample in stimulus.expected_timeline
        if sample.sample_time_ms < 450 or sample.sample_time_ms >= 3_700
    ]
    low = [
        sample.expected_energy
        for sample in stimulus.expected_timeline
        if 650 <= sample.sample_time_ms < 1_400
    ]
    high = [
        sample.expected_energy
        for sample in stimulus.expected_timeline
        if 1_650 <= sample.sample_time_ms < 2_400
    ]
    pulsed = [
        sample.expected_energy
        for sample in stimulus.expected_timeline
        if 2_650 <= sample.sample_time_ms < 3_400
    ]

    assert max(silence) < 0.02
    assert _avg(low) > 0.05
    assert _avg(high) > _avg(low) + 0.18
    assert max(pulsed) > min(pulsed) + 0.20


def test_backend_meter_follows_synthetic_amplitude_changes() -> None:
    stimulus = generate_synthetic_pcm_stimulus(sample_rate_hz=12_000, update_hz=60)
    rows = run_backend_meter_diagnostics(stimulus, playback_id="diag-meter-test")

    silence_energy = [
        row.voice_visual_energy
        for row in rows
        if row.sample_time_ms < 450 or row.sample_time_ms >= 3_750
    ]
    low_energy = [
        row.voice_visual_energy for row in rows if 700 <= row.sample_time_ms < 1_400
    ]
    high_energy = [
        row.voice_visual_energy for row in rows if 1_700 <= row.sample_time_ms < 2_400
    ]

    assert max(silence_energy) < 0.12
    assert _avg(low_energy) > 0.05
    assert _avg(high_energy) > _avg(low_energy) + 0.10

    payload_rows = build_payload_diagnostics(rows)
    report = build_reactive_chain_report(
        playback_id="diag-meter-test",
        expected_rows=stimulus.expected_timeline,
        backend_rows=rows,
        payload_rows=payload_rows,
        qml_rows=[],
        mode="unit",
    )

    assert report["correlations"]["expected_to_backend"] > 0.55


def test_chain_report_and_csv_are_scalar_only() -> None:
    stimulus = generate_synthetic_pcm_stimulus(sample_rate_hz=8_000, update_hz=30)
    backend_rows = run_backend_meter_diagnostics(stimulus, playback_id="scalar-only")
    payload_rows = build_payload_diagnostics(backend_rows)
    report = build_reactive_chain_report(
        playback_id="scalar-only",
        expected_rows=stimulus.expected_timeline,
        backend_rows=backend_rows,
        payload_rows=payload_rows,
        qml_rows=[],
        mode="unit",
    )
    csv_text = energy_timeline_csv_text(
        expected_rows=stimulus.expected_timeline,
        backend_rows=backend_rows,
        payload_rows=payload_rows,
        qml_rows=[],
    )

    serialized = json.dumps(report, sort_keys=True) + "\n" + csv_text
    forbidden = [
        "pcm_bytes",
        "raw_samples",
        "audio_bytes",
        "raw_audio_bytes",
        "sample_values",
        "base64",
    ]

    assert all(token not in serialized for token in forbidden)
    assert "raw_audio_present" in serialized
    assert "False" not in csv_text
    assert "pcm_stream_meter" in serialized


def test_failure_classification_detects_flat_stage_cases() -> None:
    expected = [0.0, 0.12, 0.62, 0.20, 0.73, 0.0]
    varied_backend = [0.01, 0.10, 0.50, 0.24, 0.65, 0.02]
    varied_payload = [0.01, 0.11, 0.51, 0.22, 0.63, 0.01]
    varied_qml = [0.0, 0.10, 0.49, 0.25, 0.61, 0.02]
    varied_final = [0.0, 0.08, 0.31, 0.28, 0.48, 0.08]
    flat = [0.03] * len(expected)

    assert classify_reactive_chain(expected, flat, [], [], []) == ["backend_meter_flat"]
    assert classify_reactive_chain(expected, varied_backend, flat, [], []) == [
        "payload_handoff_flat"
    ]
    assert classify_reactive_chain(expected, varied_backend, varied_payload, flat, []) == [
        "qml_receive_flat"
    ]
    assert classify_reactive_chain(
        expected, varied_backend, varied_payload, varied_qml, flat
    ) == ["anchor_mapping_flat"]
    assert classify_reactive_chain(
        expected,
        varied_backend,
        varied_payload,
        varied_qml,
        varied_final,
        paint_count=0,
    ) == ["qml_paint_missing"]
    assert classify_reactive_chain(
        expected,
        varied_backend,
        varied_payload,
        varied_qml,
        varied_final,
        paint_count=8,
    ) == ["chain_pass"]
