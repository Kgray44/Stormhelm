from __future__ import annotations

import argparse
import json

from scripts.run_voice_ar11_sync_offset_sweep import (
    _build_kraken_command,
    extract_offset_result,
    parse_offsets,
    summarize_offset_sweep,
)


def _report(
    *,
    lag: float,
    confidence: str = "medium",
    classification: str = "sync_visual_late",
    offset_safe: bool | None = None,
) -> dict:
    scenario = {
        "scenario": "single_spoken_response",
        "renderer": "legacy_blob_qsg_candidate",
        "classification": [classification],
        "render_metrics": {
            "anchorPaintFpsDuringSpeaking": 40.0,
            "dynamicCorePaintFpsDuringSpeaking": 40.0,
        },
        "speaking_lifetime": {
            "anchor_speaking_start_delay_ms": 80.0,
            "anchor_release_tail_ms": 30.0,
        },
        "ranges": {
            "finalSpeakingEnergy": {"span": 0.7},
            "blobScaleDrive": {"span": 0.55},
        },
        "audio_visual_alignment": {
            "perceptual_sync_best_lag_ms": lag,
            "perceptual_sync_correlation": 0.62,
            "sync_confidence": confidence,
            "syncMeasurementConfidence": confidence,
            "syncMeasurementRejectionReason": ""
            if confidence in {"medium", "high"}
            else "direct_correlation_low",
            "syncOffsetCandidateSafe": confidence in {"medium", "high"}
            if offset_safe is None
            else offset_safe,
            "syncOffsetCandidateRejectedReason": ""
            if (confidence in {"medium", "high"} if offset_safe is None else offset_safe)
            else "low_confidence_sync_measurement",
            "stage_latency_estimate_ms": lag,
            "perceptual_sync_status": "visual_late" if lag > 120 else "aligned",
            "perceptual_sync_basis": "direct_correlation",
        },
        "raw_audio_present": False,
    }
    return {
        "classification": [classification],
        "scenario_reports": [
            dict(scenario),
            {**scenario, "scenario": "repeated_speech"},
            {**scenario, "scenario": "renderer_comparison"},
        ],
        "raw_audio_present": False,
    }


def test_ar11_parse_offsets_clamps_and_dedupes() -> None:
    assert parse_offsets("0,-60,-999,-60,999") == [0, -60, -300, 300]


def test_ar11_extract_offset_result_contains_only_scalar_sync_metrics() -> None:
    result = extract_offset_result(_report(lag=140), offset_ms=-100)
    serialized = json.dumps(result)

    assert result["visual_offset_ms"] == -100
    assert result["scenarios"]["repeated_speech"]["direct_pcm_to_blob_lag_ms"] == 140
    assert "pcm_bytes" not in serialized
    assert "raw_samples" not in serialized
    assert "base64" not in serialized


def test_ar11_sync_sweep_does_not_apply_offset_by_default() -> None:
    baseline = extract_offset_result(_report(lag=140), offset_ms=0)
    improved = extract_offset_result(_report(lag=40, classification="production_chain_pass"), offset_ms=-100)

    summary = summarize_offset_sweep(
        [baseline, improved],
        visual_approval="approved",
        apply_requested=False,
        operator_sync_approved=True,
    )

    assert summary["recommended_visual_offset_ms"] == -100
    assert summary["offset_applied"] is False
    assert summary["visual_offset_applied_ms"] == 0
    assert "visual_offset_ms = 0" in summary["rollback_config"]


def test_ar11_sync_sweep_requires_operator_approval_to_apply() -> None:
    baseline = extract_offset_result(_report(lag=140), offset_ms=0)
    improved = extract_offset_result(_report(lag=40, classification="production_chain_pass"), offset_ms=-100)

    summary = summarize_offset_sweep(
        [baseline, improved],
        visual_approval="approved",
        apply_requested=True,
        operator_sync_approved=False,
    )

    assert summary["recommended_visual_offset_ms"] == -100
    assert summary["offset_applied"] is False


def test_ar12_sync_sweep_rejects_low_confidence_offset_candidate() -> None:
    baseline = extract_offset_result(_report(lag=140, confidence="medium"), offset_ms=0)
    low_confidence = extract_offset_result(
        _report(lag=40, confidence="low", classification="production_chain_pass"),
        offset_ms=-100,
    )

    summary = summarize_offset_sweep(
        [baseline, low_confidence],
        visual_approval="approved",
        apply_requested=False,
        operator_sync_approved=True,
    )

    scenario = low_confidence["scenarios"]["single_spoken_response"]
    assert scenario["syncMeasurementConfidence"] == "low"
    assert scenario["syncOffsetCandidateSafe"] is False
    assert summary["recommended_visual_offset_ms"] == "none"
    assert summary["recommended_visual_offset_ms_value"] == "none"


def test_ar12_sync_sweep_blocks_stale_authoritative_measurement_rows() -> None:
    baseline = extract_offset_result(_report(lag=140, confidence="medium"), offset_ms=0)
    stale_state = extract_offset_result(
        _report(
            lag=40,
            confidence="medium",
            classification="sync_measurement_stale_authoritative_rows",
            offset_safe=False,
        ),
        offset_ms=-140,
    )

    summary = summarize_offset_sweep(
        [baseline, stale_state],
        visual_approval="approved",
        apply_requested=False,
        operator_sync_approved=True,
    )

    assert "sync_measurement_stale_authoritative_rows" in stale_state["classification"]
    assert stale_state["scenarios"]["repeated_speech"]["syncOffsetCandidateSafe"] is False
    assert summary["recommended_visual_offset_ms"] == "none"


def test_ar11_kraken_command_carries_qsg_approval_and_offset() -> None:
    args = argparse.Namespace(
        host="127.0.0.1",
        port=8765,
        fog="on",
        spoken_prompt="Testing",
        timeout_seconds=24,
        idle_observe_seconds=10,
        post_speech_observe_seconds=8,
        qsg_visual_approval="approved",
        qsg_visual_approval_reason="operator approved visual package",
        stormforge=True,
        clear_cache=True,
        audible=True,
        use_local_pcm_voice_fixture=True,
    )

    command = _build_kraken_command(args, offset=-140, output_dir=__import__("pathlib").Path("out"))

    assert "--voice-visual-offset-ms" in command
    assert "-140" in command
    assert "--qsg-visual-approval" in command
    assert "approved" in command
    assert "--stormforge" in command
