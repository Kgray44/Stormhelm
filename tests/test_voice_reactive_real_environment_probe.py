from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stormhelm.core.voice.reactive_real_environment_probe import (
    audio_visual_sync_diagnosis,
    classify_real_environment_chain,
    real_environment_report_markdown,
    real_environment_timeline_csv_text,
    sanitize_scalar_payload,
    speaking_lifetime_report,
    summarize_real_environment_chain,
)
from scripts.run_voice_reactive_real_environment_probe import (
    _build_timelines,
    _enrich_status_rows_with_authority,
    _playback_boundary_segments,
    _speaking_lifetime,
    _status_row_from_voice_status,
)


FORBIDDEN_RAW_TOKENS = [
    "pcm_bytes",
    "raw_samples",
    "audio_bytes",
    "raw_audio_bytes",
    "sample_values",
    "base64",
]


def test_real_environment_sanitizer_keeps_scalar_fields_only() -> None:
    payload = {
        "playback_id": "live-1",
        "voice_visual_energy": 0.42,
        "voice_visual_active": True,
        "voice_visual_source": "pcm_stream_meter",
        "pcm_bytes": b"\x00\x01",
        "raw_samples": [0, 1, 2],
        "nested": {
            "rms": 0.2,
            "audio_bytes": "abc",
            "sample_values": [0.1, 0.2],
        },
    }

    sanitized = sanitize_scalar_payload(payload)
    serialized = json.dumps(sanitized, sort_keys=True)

    assert sanitized["playback_id"] == "live-1"
    assert sanitized["voice_visual_energy"] == 0.42
    assert sanitized["nested"]["rms"] == 0.2
    assert sanitized["raw_audio_present"] is False
    assert all(token not in serialized for token in FORBIDDEN_RAW_TOKENS)


def test_real_environment_classification_detects_stage_breaks() -> None:
    varied_pcm = [0.0, 0.1, 0.55, 0.18, 0.7, 0.01]
    varied_meter = [0.0, 0.12, 0.5, 0.2, 0.63, 0.02]
    varied_payload = [0.01, 0.11, 0.49, 0.22, 0.61, 0.01]
    varied_bridge = [0.0, 0.1, 0.5, 0.2, 0.6, 0.02]
    varied_qml = [0.01, 0.09, 0.47, 0.19, 0.58, 0.01]
    varied_final = [0.0, 0.08, 0.35, 0.22, 0.44, 0.03]
    flat = [0.02] * len(varied_pcm)

    assert classify_real_environment_chain(
        pcm_energy=varied_pcm,
        meter_energy=flat,
        payload_energy=[],
        bridge_energy=[],
        qml_energy=[],
        final_energy=[],
    ) == ["pcm_meter_flat"]
    assert classify_real_environment_chain(
        pcm_energy=varied_pcm,
        meter_energy=varied_meter,
        payload_energy=flat,
        bridge_energy=[],
        qml_energy=[],
        final_energy=[],
    ) == ["meter_to_payload_broken"]
    assert classify_real_environment_chain(
        pcm_energy=varied_pcm,
        meter_energy=varied_meter,
        payload_energy=varied_payload,
        bridge_energy=flat,
        qml_energy=[],
        final_energy=[],
    ) == ["payload_to_bridge_broken"]
    assert classify_real_environment_chain(
        pcm_energy=varied_pcm,
        meter_energy=varied_meter,
        payload_energy=varied_payload,
        bridge_energy=varied_bridge,
        qml_energy=flat,
        final_energy=[],
    ) == ["bridge_to_qml_broken"]
    assert classify_real_environment_chain(
        pcm_energy=varied_pcm,
        meter_energy=varied_meter,
        payload_energy=varied_payload,
        bridge_energy=varied_bridge,
        qml_energy=varied_qml,
        final_energy=flat,
    ) == ["qml_to_anchor_mapping_broken"]
    assert classify_real_environment_chain(
        pcm_energy=varied_pcm,
        meter_energy=varied_meter,
        payload_energy=varied_payload,
        bridge_energy=varied_bridge,
        qml_energy=varied_qml,
        final_energy=varied_final,
        paint_count=0,
    ) == ["anchor_paint_not_updating"]


def test_speaking_lifetime_delay_and_stale_release_classification() -> None:
    healthy = speaking_lifetime_report(
        playback_start_ms=1_000,
        playback_end_ms=3_000,
        voice_visual_active_true_ms=1_080,
        voice_visual_active_false_ms=3_060,
        qml_speaking_true_ms=1_160,
        qml_speaking_false_ms=3_180,
        anchor_speaking_true_ms=1_230,
        anchor_speaking_false_ms=3_420,
    )

    assert healthy["speaking_visual_start_delay_ms"] == 80
    assert healthy["anchor_speaking_start_delay_ms"] == 230
    assert healthy["speaking_visual_end_delay_ms"] == 60
    assert healthy["anchor_speaking_stuck_after_audio_ms"] == 420
    assert healthy["anchor_release_tail_ms"] == 360

    delayed = dict(healthy)
    delayed["anchor_speaking_start_delay_ms"] = 700
    stale = dict(healthy)
    stale["anchor_speaking_stuck_after_audio_ms"] = 6_300

    assert classify_real_environment_chain(
        pcm_energy=[0, 0.4, 0],
        meter_energy=[0, 0.35, 0],
        payload_energy=[0, 0.34, 0],
        bridge_energy=[0, 0.33, 0],
        qml_energy=[0, 0.32, 0],
        final_energy=[0, 0.25, 0],
        paint_count=4,
        speaking_lifetime=delayed,
    ) == ["speaking_state_delayed"]
    assert classify_real_environment_chain(
        pcm_energy=[0, 0.4, 0],
        meter_energy=[0, 0.35, 0],
        payload_energy=[0, 0.34, 0],
        bridge_energy=[0, 0.33, 0],
        qml_energy=[0, 0.32, 0],
        final_energy=[0, 0.25, 0],
        paint_count=4,
        speaking_lifetime=stale,
    ) == ["speaking_state_stale_after_playback"]
    assert classify_real_environment_chain(
        pcm_energy=[0, 0.4, 0],
        meter_energy=[0, 0.35, 0],
        payload_energy=[0, 0.34, 0],
        bridge_energy=[0, 0.33, 0],
        qml_energy=[0, 0.32, 0],
        final_energy=[0, 0.25, 0],
        paint_count=4,
        speaking_lifetime=delayed,
        max_frame_gap_ms=900,
    ) == ["render_cadence_problem"]
    assert classify_real_environment_chain(
        pcm_energy=[0, 0.4, 0],
        meter_energy=[0, 0.35, 0],
        payload_energy=[0, 0.34, 0],
        bridge_energy=[0, 0.33, 0],
        qml_energy=[0, 0.32, 0],
        final_energy=[0, 0.25, 0],
        paint_count=4,
        speaking_lifetime=healthy,
        max_frame_gap_ms=24,
        render_metrics={
            "sharedAnimationClockFpsDuringSpeakingMin": 10.5,
            "anchorPaintFps": 5.6,
        },
    ) == ["render_cadence_problem"]
    assert classify_real_environment_chain(
        pcm_energy=[0, 0.4, 0],
        meter_energy=[0, 0.35, 0],
        payload_energy=[0, 0.34, 0],
        bridge_energy=[0, 0.33, 0],
        qml_energy=[0, 0.32, 0],
        final_energy=[0, 0.25, 0],
        paint_count=4,
        speaking_lifetime=healthy,
        max_frame_gap_ms=33.3,
        render_metrics={
            "sharedAnimationClockFpsDuringSpeakingMin": 17.3,
            "anchorLocalSpeakingFrameFps": 45.5,
            "dynamicCorePaintFpsDuringSpeaking": 45.5,
            "anchorPaintFpsDuringSpeaking": 45.5,
            "sharedClockUnderTargetButAnchorLocalClockCompensated": True,
            "requestPaintStormDetected": False,
        },
    ) == ["production_chain_pass"]
    assert classify_real_environment_chain(
        pcm_energy=[0, 0.4, 0],
        meter_energy=[0, 0.35, 0],
        payload_energy=[0, 0.34, 0],
        bridge_energy=[0, 0.33, 0],
        qml_energy=[0, 0.32, 0],
        final_energy=[0, 0.25, 0],
        paint_count=4,
        speaking_lifetime=healthy,
        max_frame_gap_ms=24,
        render_metrics={
            "sharedAnimationClockFpsDuringSpeakingMin": 52.0,
            "anchorLocalSpeakingFrameFps": 54.0,
            "anchorRequestPaintFpsDuringSpeaking": 46.0,
            "anchorPaintFpsDuringSpeaking": 22.0,
            "requestPaintStormDetected": False,
        },
    ) == ["anchor_canvas_paint_path_render_backend_bottleneck"]


def test_timeline_uses_each_playback_start_for_audible_pcm_wall_time() -> None:
    events = [
        {
            "event_type": "voice.playback_started",
            "timestamp": "2026-05-04T12:00:01Z",
            "payload": {"playback_id": "playback-a"},
        },
        {
            "event_type": "voice.pcm_submitted_to_playback",
            "timestamp": "2026-05-04T12:00:01.010Z",
            "payload": {
                "playback_id": "playback-a",
                "metadata": {
                    "voice_ar1_pcm_submit": {
                        "playback_id": "playback-a",
                        "pcm_sample_time_ms": 50.0,
                        "pcm_submit_wall_time_ms": 1_000.0,
                        "voice_visual_energy": 0.2,
                        "raw_audio_present": False,
                    }
                },
            },
        },
        {
            "event_type": "voice.playback_started",
            "timestamp": "2026-05-04T12:00:05Z",
            "payload": {"playback_id": "playback-b"},
        },
        {
            "event_type": "voice.pcm_submitted_to_playback",
            "timestamp": "2026-05-04T12:00:05.010Z",
            "payload": {
                "playback_id": "playback-b",
                "metadata": {
                    "voice_ar1_pcm_submit": {
                        "playback_id": "playback-b",
                        "pcm_sample_time_ms": 50.0,
                        "pcm_submit_wall_time_ms": 5_000.0,
                        "voice_visual_energy": 0.4,
                        "raw_audio_present": False,
                    }
                },
            },
        },
    ]

    _timeline, stage_rows = _build_timelines(events, [])
    pcm_rows = stage_rows["pcm_rows"]

    assert pcm_rows[0]["pcm_audible_wall_time_ms"] == pytest.approx(
        1_777_896_001_050.0
    )
    assert pcm_rows[1]["pcm_audible_wall_time_ms"] == pytest.approx(
        1_777_896_005_050.0
    )


def test_repeated_speech_lifetime_is_segmented_by_playback_id() -> None:
    events = [
        {
            "event_type": "voice.playback_started",
            "timestamp": "2026-05-04T12:00:01Z",
            "payload": {"playback_id": "playback-a"},
        },
        {
            "event_type": "voice.playback_completed",
            "timestamp": "2026-05-04T12:00:03Z",
            "payload": {"playback_id": "playback-a"},
        },
        {
            "event_type": "voice.playback_started",
            "timestamp": "2026-05-04T12:00:04Z",
            "payload": {"playback_id": "playback-b"},
        },
        {
            "event_type": "voice.playback_completed",
            "timestamp": "2026-05-04T12:00:06Z",
            "payload": {"playback_id": "playback-b"},
        },
    ]
    payload_rows = [
        {
            "voice_visual_playback_id": "playback-a",
            "payload_wall_time_ms": 1_777_896_001_010.0,
            "voice_visual_active": True,
        },
        {
            "voice_visual_playback_id": "playback-a",
            "payload_wall_time_ms": 1_777_896_003_080.0,
            "voice_visual_active": False,
        },
        {
            "voice_visual_playback_id": "playback-b",
            "payload_wall_time_ms": 1_777_896_004_020.0,
            "voice_visual_active": True,
        },
        {
            "voice_visual_playback_id": "playback-b",
            "payload_wall_time_ms": 1_777_896_006_090.0,
            "voice_visual_active": False,
        },
    ]
    qml_rows = [
        {
            "qml_receive_time_ms": 1_777_896_001_040.0,
            "qmlReceivedPlaybackId": "playback-a",
            "speaking_visual_active": True,
            "anchorSpeakingVisualActive": True,
        },
        {
            "qml_receive_time_ms": 1_777_896_003_180.0,
            "qmlReceivedPlaybackId": "playback-a",
            "speaking_visual_active": False,
            "anchorSpeakingVisualActive": False,
        },
        {
            "qml_receive_time_ms": 1_777_896_004_060.0,
            "qmlReceivedPlaybackId": "playback-b",
            "speaking_visual_active": True,
            "anchorSpeakingVisualActive": True,
        },
        {
            "qml_receive_time_ms": 1_777_896_006_210.0,
            "qmlReceivedPlaybackId": "playback-b",
            "speaking_visual_active": False,
            "anchorSpeakingVisualActive": False,
        },
    ]

    lifetime = _speaking_lifetime(events, qml_rows, payload_rows)

    assert lifetime["speaking_lifetime_method"] == "per_playback_authoritative"
    assert lifetime["playback_lifetime_count"] == 2
    assert lifetime["anchor_speaking_start_delay_ms"] == pytest.approx(60.0)
    assert lifetime["anchor_release_tail_ms"] == pytest.approx(120.0)
    assert len(lifetime["playback_lifetimes"]) == 2
    assert {row["playback_id"] for row in lifetime["playback_lifetimes"]} == {
        "playback-a",
        "playback-b",
    }


def test_playback_boundary_segments_keep_repeated_speech_playbacks_separate() -> None:
    events: list[dict[str, object]] = []
    pcm_rows = [
        {
            "playback_id": "playback-a",
            "pcm_audible_wall_time_ms": 1_777_895_200_020.0,
            "voice_visual_energy": 0.24,
            "raw_audio_present": False,
        },
        {
            "playback_id": "playback-b",
            "pcm_audible_wall_time_ms": 1_777_895_204_030.0,
            "voice_visual_energy": 0.31,
            "raw_audio_present": False,
        },
    ]
    payload_rows = [
        {
            "voice_visual_playback_id": "playback-a",
            "payload_wall_time_ms": 1_777_895_200_040.0,
            "voice_visual_active": True,
            "voice_visual_energy": 0.23,
            "raw_audio_present": False,
        },
        {
            "voice_visual_playback_id": "playback-b",
            "payload_wall_time_ms": 1_777_895_204_060.0,
            "voice_visual_active": True,
            "voice_visual_energy": 0.3,
            "raw_audio_present": False,
        },
    ]
    qml_rows = [
        {
            "qmlReceivedPlaybackId": "playback-a",
            "qml_receive_time_ms": 1_777_895_200_090.0,
            "authoritativeVoiceVisualActive": True,
            "anchorSpeakingVisualActive": True,
            "finalSpeakingEnergy": 0.18,
            "blobScaleDrive": 0.14,
            "anchorLastPaintTimeMs": 1_777_895_200_105.0,
            "raw_audio_present": False,
        },
        {
            "qmlReceivedPlaybackId": "playback-b",
            "qml_receive_time_ms": 1_777_895_204_100.0,
            "authoritativeVoiceVisualActive": True,
            "anchorSpeakingVisualActive": True,
            "finalSpeakingEnergy": 0.21,
            "blobScaleDrive": 0.17,
            "anchorLastPaintTimeMs": 1_777_895_204_116.0,
            "raw_audio_present": False,
        },
    ]

    segments = _playback_boundary_segments(events, pcm_rows, payload_rows, qml_rows)

    assert [row["playback_id"] for row in segments] == ["playback-a", "playback-b"]
    assert segments[0]["anchor_start_delay_from_pcm_ms"] == pytest.approx(70.0)
    assert segments[1]["anchor_start_delay_from_pcm_ms"] == pytest.approx(70.0)
    assert all(row["boundary_classification"] == "playback_boundary_pass" for row in segments)
    assert "pcm_bytes" not in json.dumps(segments, sort_keys=True)
    assert all(row["raw_audio_present"] is False for row in segments)


def test_real_environment_report_and_csv_are_scalar_only() -> None:
    rows = [
        {
            "time_ms": 0,
            "pcm_energy": 0.0,
            "meter_energy": 0.0,
            "payload_energy": 0.0,
            "bridge_energy": 0.0,
            "qml_received_energy": 0.0,
            "finalSpeakingEnergy": 0.0,
            "voice_visual_active": False,
            "anchor_visual_state": "idle",
            "pcm_bytes": b"nope",
        },
        {
            "time_ms": 40,
            "pcm_energy": 0.55,
            "meter_energy": 0.48,
            "payload_energy": 0.47,
            "bridge_energy": 0.46,
            "qml_received_energy": 0.45,
            "finalSpeakingEnergy": 0.34,
            "voice_visual_active": True,
            "anchor_visual_state": "speaking",
            "raw_samples": [1, 2, 3],
        },
    ]
    report = summarize_real_environment_chain(
        playback_id="real-scalar",
        spoken_stimulus_valid=True,
        timeline_rows=rows,
        process_state={"core": {"pid": 10}, "ui": {"pid": 20}},
        speaking_lifetime=speaking_lifetime_report(
            playback_start_ms=0,
            playback_end_ms=80,
            voice_visual_active_true_ms=20,
            voice_visual_active_false_ms=90,
            qml_speaking_true_ms=30,
            qml_speaking_false_ms=100,
            anchor_speaking_true_ms=40,
            anchor_speaking_false_ms=110,
        ),
        paint_count=2,
    )
    markdown = real_environment_report_markdown(report)
    csv_text = real_environment_timeline_csv_text(rows)
    serialized = json.dumps(report, sort_keys=True) + "\n" + markdown + "\n" + csv_text

    assert report["classification"] == ["production_chain_pass"]
    assert "raw_audio_present" in serialized
    assert all(token not in serialized for token in FORBIDDEN_RAW_TOKENS)
    assert "pcm_stream_meter" in serialized


def test_real_environment_report_includes_ar3_visual_drive_metrics() -> None:
    rows = [
        {
            "time_ms": 0,
            "pcm_energy": 0.0,
            "meter_energy": 0.0,
            "payload_energy": 0.0,
            "bridge_energy": 0.0,
            "qml_received_energy": 0.0,
            "finalSpeakingEnergy": 0.0,
            "blobScaleDrive": 0.0,
            "blobDeformationDrive": 0.0,
            "radianceDrive": 0.0,
        },
        {
            "time_ms": 40,
            "pcm_energy": 0.4,
            "meter_energy": 0.38,
            "payload_energy": 0.37,
            "bridge_energy": 0.36,
            "qml_received_energy": 0.35,
            "finalSpeakingEnergy": 0.30,
            "blobScaleDrive": 0.24,
            "blobDeformationDrive": 0.21,
            "radianceDrive": 0.30,
        },
        {
            "time_ms": 80,
            "pcm_energy": 0.9,
            "meter_energy": 0.86,
            "payload_energy": 0.84,
            "bridge_energy": 0.82,
            "qml_received_energy": 0.80,
            "finalSpeakingEnergy": 0.70,
            "blobScaleDrive": 0.58,
            "blobDeformationDrive": 0.52,
            "radianceDrive": 0.70,
        },
    ]

    report = summarize_real_environment_chain(
        playback_id="ar3-visual-drive",
        spoken_stimulus_valid=True,
        timeline_rows=rows,
        process_state={},
        speaking_lifetime={},
        paint_count=3,
        render_metrics={
            "anchorPaintFpsDuringSpeaking": 42.0,
            "dynamicCorePaintFpsDuringSpeaking": 42.0,
            "anchorRequestPaintFpsDuringSpeaking": 45.0,
            "sharedAnimationClockFpsDuringSpeakingMin": 55.0,
            "requestPaintStormDetected": False,
        },
    )
    csv_text = real_environment_timeline_csv_text(rows)

    assert report["ranges"]["blobScaleDrive"]["span"] > 0.50
    assert report["ranges"]["blobDeformationDrive"]["span"] > 0.45
    assert report["correlations"]["finalSpeakingEnergy_to_blobScaleDrive"] > 0.99
    assert report["correlations"]["finalSpeakingEnergy_to_blobDeformationDrive"] > 0.99
    assert "blobScaleDrive" in csv_text
    assert "raw_samples" not in json.dumps(report, sort_keys=True)


def test_real_environment_report_measures_audio_visual_alignment_lag() -> None:
    rows = [
        {
            "time_ms": 0,
            "pcm_energy": 0.0,
            "meter_energy": 0.0,
            "qml_received_energy": 0.0,
            "finalSpeakingEnergy": 0.0,
            "blobScaleDrive": 0.0,
            "blobDeformationDrive": 0.0,
            "radianceDrive": 0.0,
        },
        {
            "time_ms": 20,
            "pcm_energy": 0.2,
            "meter_energy": 0.2,
            "qml_received_energy": 0.2,
            "finalSpeakingEnergy": 0.0,
            "blobScaleDrive": 0.0,
            "blobDeformationDrive": 0.0,
            "radianceDrive": 0.0,
        },
        {
            "time_ms": 40,
            "pcm_energy": 0.8,
            "meter_energy": 0.8,
            "qml_received_energy": 0.8,
            "finalSpeakingEnergy": 0.2,
            "blobScaleDrive": 0.16,
            "blobDeformationDrive": 0.14,
            "radianceDrive": 0.2,
        },
        {
            "time_ms": 60,
            "pcm_energy": 0.3,
            "meter_energy": 0.3,
            "qml_received_energy": 0.3,
            "finalSpeakingEnergy": 0.8,
            "blobScaleDrive": 0.64,
            "blobDeformationDrive": 0.56,
            "radianceDrive": 0.8,
        },
        {
            "time_ms": 80,
            "pcm_energy": 0.1,
            "meter_energy": 0.1,
            "qml_received_energy": 0.1,
            "finalSpeakingEnergy": 0.3,
            "blobScaleDrive": 0.24,
            "blobDeformationDrive": 0.21,
            "radianceDrive": 0.3,
        },
    ]

    report = summarize_real_environment_chain(
        playback_id="ar3-alignment",
        spoken_stimulus_valid=True,
        timeline_rows=rows,
        process_state={},
        speaking_lifetime={},
        paint_count=5,
    )
    markdown = real_environment_report_markdown(report)

    alignment = report["audio_visual_alignment"]
    assert alignment["pcm_to_finalSpeakingEnergy"]["best_lag_ms"] == 20
    assert alignment["qml_received_to_finalSpeakingEnergy"]["best_lag_ms"] == 20
    assert alignment["finalSpeakingEnergy_to_blobScaleDrive"]["best_lag_ms"] == 0
    assert alignment["finalSpeakingEnergy_to_radianceDrive"]["correlation"] == pytest.approx(1.0)
    assert alignment["perceptual_sync_status"] == "aligned"
    assert "## Audio/Visual Alignment" in markdown
    assert "perceptual_sync_status" in markdown


def test_audio_visual_sync_uses_stage_latency_when_direct_correlation_is_weak() -> None:
    alignment = {
        "pcm_to_blobScaleDrive": {
            "best_lag_ms": 600,
            "correlation": 0.16,
            "sample_count": 200,
            "raw_audio_present": False,
        },
        "pcm_to_finalSpeakingEnergy": {
            "best_lag_ms": 600,
            "correlation": 0.18,
            "sample_count": 200,
            "raw_audio_present": False,
        },
        "raw_audio_present": False,
    }

    summary = audio_visual_sync_diagnosis(
        alignment,
        {"pcm_to_paint_estimated": 102.4, "raw_audio_present": False},
    )

    assert summary["perceptual_sync_status"] == "aligned"
    assert summary["perceptual_sync_basis"] == "stage_latency_pcm_to_paint_estimated"
    assert summary["perceptual_sync_best_lag_ms"] == pytest.approx(102.4)
    assert summary["direct_pcm_visual_correlation_usable"] is False
    assert summary["sync_latency_basis"] == "stage_latency"
    assert summary["stage_latency_estimate_ms"] == pytest.approx(102.4)
    assert summary["sync_confidence"] == "medium"
    assert summary["recommended_visual_offset_ms"] is None
    assert summary["visual_offset_recommendation_basis"] == "stage_latency_aligned_no_offset"
    assert summary["visual_offset_applied_ms"] == 0
    assert summary["raw_audio_present"] is False


def test_audio_visual_sync_classifies_stage_latency_as_late() -> None:
    summary = audio_visual_sync_diagnosis(
        {
            "pcm_to_blobScaleDrive": {
                "best_lag_ms": 600,
                "correlation": 0.12,
                "sample_count": 120,
                "raw_audio_present": False,
            },
            "raw_audio_present": False,
        },
        {
            "pcm_to_paint_estimated": 420.0,
            "finalSpeakingEnergy_to_paint": 310.0,
            "raw_audio_present": False,
        },
    )

    assert summary["perceptual_sync_status"] == "visual_late"
    assert summary["perceptual_sync_basis"] == "stage_latency_pcm_to_paint_estimated"
    assert summary["sync_likely_cause"] == "renderer_or_paint_cadence_latency"
    assert summary["sync_confidence"] == "medium"
    assert summary["recommended_visual_offset_ms"] is None
    assert summary["visual_offset_recommendation_basis"] == "stage_latency_measurement_only"
    assert summary["raw_audio_present"] is False


def test_audio_visual_sync_recommends_offset_only_for_high_confidence_direct_correlation() -> None:
    moderate = audio_visual_sync_diagnosis(
        {
            "pcm_to_blobScaleDrive": {
                "best_lag_ms": 160,
                "correlation": 0.52,
                "sample_count": 260,
                "raw_audio_present": False,
            },
            "raw_audio_present": False,
        },
        {"pcm_to_paint_estimated": 155.0, "raw_audio_present": False},
    )
    high = audio_visual_sync_diagnosis(
        {
            "pcm_to_blobScaleDrive": {
                "best_lag_ms": 160,
                "correlation": 0.82,
                "sample_count": 260,
                "raw_audio_present": False,
            },
            "raw_audio_present": False,
        },
        {"pcm_to_paint_estimated": 155.0, "raw_audio_present": False},
    )

    assert moderate["perceptual_sync_status"] == "visual_late"
    assert moderate["sync_confidence"] == "medium"
    assert moderate["recommended_visual_offset_ms"] is None
    assert moderate["visual_offset_recommendation_basis"] == "direct_correlation_measurement_only"
    assert high["sync_confidence"] == "high"
    assert high["recommended_visual_offset_ms"] == pytest.approx(-160.0)
    assert high["visual_offset_recommendation_basis"] == "high_confidence_direct_correlation_proposal_only"


def test_audio_visual_sync_marks_stage_latency_inconclusive_when_stage_timestamps_conflict() -> None:
    summary = audio_visual_sync_diagnosis(
        {
            "pcm_to_blobScaleDrive": {
                "best_lag_ms": 140,
                "correlation": 0.22,
                "sample_count": 300,
                "raw_audio_present": False,
            },
            "raw_audio_present": False,
        },
        {
            "pcm_to_meter": 1650.0,
            "meter_to_payload": 0.0,
            "payload_to_bridge": 160.0,
            "bridge_to_qml": -8.0,
            "qml_to_finalSpeakingEnergy": -201.0,
            "finalSpeakingEnergy_to_paint": 207.0,
            "raw_audio_present": False,
        },
    )

    assert summary["perceptual_sync_status"] == "inconclusive"
    assert summary["sync_confidence"] == "low"
    assert summary["recommended_visual_offset_ms"] is None
    assert summary["sync_likely_cause"] == "stage_timestamp_alignment_inconsistent"


def test_render_cadence_classification_uses_visible_qsg_paint_when_local_tick_metric_is_sparse() -> None:
    classification = classify_real_environment_chain(
        pcm_energy=[0.0, 0.5, 0.8, 0.2],
        meter_energy=[0.0, 0.5, 0.8, 0.2],
        payload_energy=[0.0, 0.5, 0.8, 0.2],
        bridge_energy=[0.0, 0.5, 0.8, 0.2],
        qml_energy=[0.0, 0.5, 0.8, 0.2],
        final_energy=[0.0, 0.45, 0.7, 0.18],
        paint_count=120,
        speaking_lifetime={"anchor_speaking_start_delay_ms": 80.0},
        max_frame_gap_ms=33.333,
        render_metrics={
            "anchorPaintFpsDuringSpeaking": 33.9,
            "dynamicCorePaintFpsDuringSpeaking": 33.9,
            "anchorLocalSpeakingFrameFps": 27.7,
            "sharedAnimationClockFpsDuringSpeakingMin": 29.6,
            "renderCadenceDuringSpeakingStable": True,
            "requestPaintStormDetected": False,
            "sharedClockUnderTargetButAnchorLocalClockCompensated": False,
        },
        stimulus_valid=True,
    )

    assert classification == ["production_chain_pass"]


def test_status_rows_label_legacy_and_mirror_authoritative_ar6_state() -> None:
    status_row = _status_row_from_voice_status(
        {
            "voice": {
                "voice_visual_active": False,
                "voice_visual_energy": 0.0,
                "voice_visual_source": "pcm_stream_meter",
                "active_playback_status": "playing",
                "speaking_visual_active": True,
            }
        },
        observed_at_ms=1_000.0,
    )
    enriched = _enrich_status_rows_with_authority(
        [status_row],
        [
            {
                "qml_receive_time_ms": 990.0,
                "authoritativeVoiceStateVersion": "AR6",
                "authoritativePlaybackId": "status-ar7",
                "authoritativePlaybackStatus": "playing",
                "authoritativeVoiceVisualActive": True,
                "authoritativeVoiceVisualEnergy": 0.64,
                "authoritativeStateSource": "hot_path",
                "lastAcceptedUpdateSource": "hot_path",
                "staleBroadSnapshotIgnoredCount": 2,
                "terminalEventAcceptedCount": 0,
                "raw_audio_present": False,
            }
        ],
    )

    row = enriched[0]
    assert row["legacy_voice_visual_active"] is False
    assert row["legacy_voice_visual_energy"] == 0.0
    assert row["voice_visual_active"] is True
    assert row["voice_visual_energy"] == 0.64
    assert row["authoritativeVoiceStateVersion"] == "AR6"
    assert row["authoritativePlaybackId"] == "status-ar7"
    assert row["authoritativePlaybackStatus"] == "playing"
    assert row["authoritativeVoiceVisualActive"] is True
    assert row["authoritativeVoiceVisualEnergy"] == 0.64
    assert row["status_voice_visual_authority"] == "ar6_authoritative_overlay"
    assert row["raw_audio_present"] is False


def test_real_environment_report_counts_mid_speech_state_glitches() -> None:
    rows = [
        {
            "time_ms": 0,
            "pcm_energy": 0.0,
            "meter_energy": 0.0,
            "qml_received_energy": 0.0,
            "finalSpeakingEnergy": 0.0,
            "voice_visual_active": False,
            "speaking_visual_active": False,
            "anchor_visual_state": "idle",
        },
        {
            "time_ms": 20,
            "pcm_energy": 0.3,
            "meter_energy": 0.3,
            "qml_received_energy": 0.3,
            "finalSpeakingEnergy": 0.2,
            "voice_visual_active": True,
            "speaking_visual_active": False,
            "anchor_visual_state": "thinking",
        },
        {
            "time_ms": 40,
            "pcm_energy": 0.6,
            "meter_energy": 0.6,
            "qml_received_energy": 0.6,
            "finalSpeakingEnergy": 0.5,
            "voice_visual_active": True,
            "speaking_visual_active": True,
            "anchor_visual_state": "speaking",
        },
        {
            "time_ms": 60,
            "pcm_energy": 0.5,
            "meter_energy": 0.5,
            "qml_received_energy": 0.5,
            "finalSpeakingEnergy": 0.4,
            "voice_visual_active": True,
            "speaking_visual_active": False,
            "anchor_visual_state": "idle",
        },
        {
            "time_ms": 80,
            "pcm_energy": 0.4,
            "meter_energy": 0.4,
            "qml_received_energy": 0.4,
            "finalSpeakingEnergy": 0.3,
            "voice_visual_active": True,
            "speaking_visual_active": True,
            "anchor_visual_state": "speaking",
        },
    ]

    report = summarize_real_environment_chain(
        playback_id="ar3r-state-glitch",
        spoken_stimulus_valid=True,
        timeline_rows=rows,
        process_state={},
        speaking_lifetime={},
        paint_count=3,
    )
    markdown = real_environment_report_markdown(report)

    stability = report["speaking_state_stability"]
    assert stability["voiceVisualActiveRows"] == 4
    assert stability["speakingVisualFalseWhileVoiceVisualActiveRows"] == 2
    assert stability["midSpeechSpeakingVisualFalseRows"] == 1
    assert stability["midSpeechAnchorIdleRows"] == 1
    assert stability["anchorStatusGlitchDetected"] is True
    assert "## Speaking State Stability" in markdown
    assert "midSpeechAnchorIdleRows" in markdown


def test_real_environment_report_includes_ar3_before_after_render_comparison() -> None:
    rows = [
        {
            "time_ms": 0,
            "pcm_energy": 0.0,
            "meter_energy": 0.0,
            "payload_energy": 0.0,
            "bridge_energy": 0.0,
            "qml_received_energy": 0.0,
            "finalSpeakingEnergy": 0.0,
        },
        {
            "time_ms": 40,
            "pcm_energy": 0.8,
            "meter_energy": 0.76,
            "payload_energy": 0.75,
            "bridge_energy": 0.74,
            "qml_received_energy": 0.73,
            "finalSpeakingEnergy": 0.52,
        },
    ]

    report = summarize_real_environment_chain(
        playback_id="ar3-before-after",
        spoken_stimulus_valid=True,
        timeline_rows=rows,
        process_state={},
        speaking_lifetime=speaking_lifetime_report(
            playback_start_ms=0,
            playback_end_ms=900,
            voice_visual_active_true_ms=20,
            voice_visual_active_false_ms=920,
            qml_speaking_true_ms=30,
            qml_speaking_false_ms=980,
            anchor_speaking_true_ms=80,
            anchor_speaking_false_ms=990,
        ),
        paint_count=9,
        render_metrics={
            "anchorRequestPaintFpsDuringSpeaking": 46.0,
            "anchorPaintFpsDuringSpeaking": 22.0,
            "anchorLocalSpeakingFrameFps": 54.0,
            "sharedAnimationClockFpsDuringSpeakingMin": 52.0,
            "maxFrameGapMsDuringSpeaking": 46.0,
            "fogTickFpsDuringSpeakingMean": 60.0,
        },
    )
    markdown = real_environment_report_markdown(report)

    comparison = report["voice_ar3_before_after"]
    assert comparison["after_voice_ar3_live"]["anchorRequestPaintFpsDuringSpeaking"] == 46.0
    assert comparison["after_voice_ar3_live"]["anchorPaintFpsDuringSpeaking"] == 22.0
    assert comparison["after_voice_ar3_live"]["anchorLocalSpeakingFrameFps"] == 54.0
    assert comparison["before_voice_ar2_live"]["anchorPaintFpsDuringSpeaking"] == 24.57
    assert "Anchor Canvas paint path/render backend bottleneck" in markdown


def test_real_environment_latency_summary_ignores_placeholder_zero_timestamps() -> None:
    rows = [
        {
            "time_ms": 0,
            "pcm_energy": 0.0,
            "meter_energy": 0.0,
            "payload_energy": 0.0,
            "bridge_energy": 0.0,
            "qml_received_energy": 0.0,
            "finalSpeakingEnergy": 0.0,
            "qml_receive_time_ms": 0,
            "finalSpeakingEnergyUpdatedAtMs": 0,
            "anchor_paint_time": 0,
        },
        {
            "time_ms": 16,
            "pcm_energy": 0.2,
            "meter_energy": 0.2,
            "payload_energy": 0.2,
            "bridge_energy": 0.2,
            "qml_received_energy": 0.2,
            "finalSpeakingEnergy": 0.1,
            "qml_receive_time_ms": 1_000,
            "finalSpeakingEnergyUpdatedAtMs": 1_025,
            "anchor_paint_time": 1_040,
        },
    ]

    report = summarize_real_environment_chain(
        playback_id="real-zero-placeholder",
        spoken_stimulus_valid=True,
        timeline_rows=rows,
        process_state={},
        speaking_lifetime={},
        paint_count=2,
    )

    assert report["latency_ms"]["qml_to_finalSpeakingEnergy"] == 25
    assert report["latency_ms"]["finalSpeakingEnergy_to_paint"] == 15
