from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stormhelm.config.models import OpenAIConfig, VoiceConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.live_kraken_probe import (
    classify_live_kraken_scenario,
    kraken_markdown,
    qsg_candidate_promotion_gate,
    renderer_comparison_markdown,
    sanitize_kraken_payload,
    summarize_live_kraken,
)
from scripts.run_voice_ar5_live_kraken_probe import (
    _clamp_voice_visual_offset_ms,
    _normalize_qsg_visual_approval,
    _pcm_events_have_valid_stimulus,
    _resolve_renderer_plan,
)
from stormhelm.core.voice.service import build_voice_subsystem
from stormhelm.core.voice.visualizer import VoiceAudioEnvelope


FORBIDDEN_RAW_TOKENS = [
    "pcm_bytes",
    "raw_samples",
    "audio_bytes",
    "raw_audio_bytes",
    "sample_values",
    "base64",
]


def _openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        enabled=True,
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model="gpt-5.4-nano",
        planner_model="gpt-5.4-nano",
        reasoning_model="gpt-5.4",
        timeout_seconds=60,
        max_tool_rounds=4,
        max_output_tokens=1200,
        planner_max_output_tokens=900,
        reasoning_max_output_tokens=1400,
        instructions="",
    )


def test_pcm_visualizer_updates_are_visible_to_default_ui_event_stream() -> None:
    events = EventBuffer(capacity=16)
    service = build_voice_subsystem(
        VoiceConfig(enabled=True, mode="manual", spoken_responses_enabled=True),
        _openai_config(),
        events=events,
    )

    service._publish_voice_output_envelope_update(
        VoiceAudioEnvelope(
            source="pcm_stream_meter",
            rms_level=0.42,
            peak_level=0.64,
            visual_drive_level=0.58,
            center_blob_drive=0.52,
            center_blob_scale_drive=0.48,
            audio_reactive_available=True,
            raw_audio_present=False,
        ),
        session_id="ar5-live-kraken-fixture-session",
        turn_id="turn-1",
        speech_request_id="speech-1",
        playback_request_id="playback-request-1",
        playback_id="playback-1",
        playback_status="playing",
    )

    default_stream_events = events.recent(limit=16, session_id="default")
    visualizer = [
        event
        for event in default_stream_events
        if event.get("event_type") == "voice.visualizer_update"
    ]

    assert len(visualizer) == 1
    assert visualizer[0]["session_id"] is None
    assert visualizer[0]["payload"]["playback_id"] == "playback-1"
    assert visualizer[0]["payload"]["metadata"]["voice"]["voice_visual_source"] == "pcm_stream_meter"
    assert visualizer[0]["payload"]["metadata"]["raw_audio_present"] is False
    assert "ar5-live-kraken-fixture-session" not in str(default_stream_events)


def test_kraken_detects_false_speaking_without_audio() -> None:
    rows = [
        {
            "time_ms": 0,
            "voice_visual_active": False,
            "speaking_visual_active": False,
            "anchor_visual_state": "idle",
            "playback_status": "idle",
        },
        {
            "time_ms": 1000,
            "voice_visual_active": False,
            "speaking_visual_active": True,
            "anchor_visual_state": "speaking",
            "playback_status": "idle",
            "finalSpeakingEnergy": 0.22,
        },
    ]

    classifications = classify_live_kraken_scenario(
        "idle_baseline",
        rows,
        report={"spoken_stimulus_valid": False},
    )

    assert "idle_false_speaking" in classifications
    assert "false_speaking_without_audio" in classifications


def test_kraken_probe_rejects_flat_pcm_as_valid_spoken_stimulus() -> None:
    def pcm_event(energy: float, peak: float, rms: float) -> dict:
        return {
            "event_type": "voice.pcm_submitted_to_playback",
            "payload": {
                "metadata": {
                    "voice_ar1_pcm_submit": {
                        "voice_visual_energy": energy,
                        "peak": peak,
                        "rms": rms,
                        "raw_audio_present": False,
                    }
                }
            },
        }

    assert _pcm_events_have_valid_stimulus(
        [pcm_event(0.0, 0.0, 0.0), pcm_event(0.0, 0.005, 0.002), pcm_event(0.0, 0.0, 0.0)]
    ) is False
    assert _pcm_events_have_valid_stimulus(
        [pcm_event(0.0, 0.0, 0.0), pcm_event(0.32, 0.44, 0.22), pcm_event(0.25, 0.31, 0.18)]
    ) is True


def test_kraken_does_not_treat_bounded_residual_energy_as_false_speaking() -> None:
    rows = [
        {
            "time_ms": 0,
            "playback_status": "completed",
            "voice_visual_active": False,
            "authoritativeVoiceVisualActive": False,
            "speaking_visual_active": False,
            "anchorSpeakingVisualActive": False,
            "anchor_visual_state": "idle",
            "pcm_energy": 0.0,
            "meter_energy": 0.0,
            "finalSpeakingEnergy": 0.052,
            "blobScaleDrive": 0.041,
        }
    ]

    classifications = classify_live_kraken_scenario(
        "single_spoken_response",
        rows,
        report={
            "speaking_lifetime": {
                "anchor_speaking_stuck_after_audio_ms": 134,
                "anchor_release_tail_ms": 134,
            }
        },
    )

    assert "false_speaking_without_audio" not in classifications
    assert "speaking_stuck_after_audio" not in classifications


def test_kraken_detects_delayed_speaking_entry_and_animation() -> None:
    rows = [
        {
            "time_ms": 0,
            "voice_visual_active": True,
            "speaking_visual_active": False,
            "playback_status": "playing",
            "qml_received_energy": 0.4,
            "finalSpeakingEnergy": 0.0,
            "blobScaleDrive": 0.0,
        },
        {
            "time_ms": 320,
            "voice_visual_active": True,
            "speaking_visual_active": True,
            "playback_status": "playing",
            "qml_received_energy": 0.5,
            "finalSpeakingEnergy": 0.0,
            "blobScaleDrive": 0.0,
        },
        {
            "time_ms": 420,
            "voice_visual_active": True,
            "speaking_visual_active": True,
            "playback_status": "playing",
            "qml_received_energy": 0.5,
            "finalSpeakingEnergy": 0.18,
            "blobScaleDrive": 0.15,
        },
    ]

    classifications = classify_live_kraken_scenario(
        "single_spoken_response",
        rows,
        report={
            "speaking_lifetime": {
                "anchor_speaking_start_delay_ms": 330,
            }
        },
    )

    assert "delayed_speaking_entry" in classifications
    assert "delayed_anchor_animation_entry" in classifications


def test_kraken_detects_stuck_speaking_and_stale_snapshot_override() -> None:
    rows = [
        {
            "time_ms": 0,
            "voice_visual_active": True,
            "bridge_voice_visual_active": True,
            "speaking_visual_active": True,
            "playback_status": "playing",
            "bridge_energy": 0.5,
            "qml_received_energy": 0.5,
        },
        {
            "time_ms": 120,
            "voice_visual_active": False,
            "bridge_voice_visual_active": True,
            "speaking_visual_active": True,
            "playback_status": "playing",
            "bridge_energy": 0.52,
            "qml_received_energy": 0.52,
        },
    ]

    classifications = classify_live_kraken_scenario(
        "single_spoken_response",
        rows,
        report={
            "speaking_lifetime": {
                "anchor_speaking_stuck_after_audio_ms": 1400,
                "anchor_release_tail_ms": 1400,
            }
        },
    )

    assert "speaking_stuck_after_audio" in classifications
    assert "anchor_release_bug" in classifications
    assert "stale_broad_voice_snapshot_overrides_hot_path" in classifications


def test_kraken_does_not_treat_ar6_ignored_snapshot_as_override() -> None:
    rows = [
        {
            "time_ms": 0,
            "authoritativeVoiceStateVersion": "AR6",
            "authoritativeVoiceVisualActive": True,
            "voice_visual_active": True,
            "bridge_voice_visual_active": True,
            "speaking_visual_active": True,
            "authoritativePlaybackStatus": "playing",
            "playback_status": "playing",
            "bridge_energy": 0.52,
            "qml_received_energy": 0.50,
            "staleBroadSnapshotIgnored": True,
            "staleBroadSnapshotIgnoredCount": 3,
        },
        {
            "time_ms": 80,
            "authoritativeVoiceStateVersion": "AR6",
            "authoritativeVoiceVisualActive": True,
            "voice_visual_active": True,
            "bridge_voice_visual_active": True,
            "speaking_visual_active": True,
            "authoritativePlaybackStatus": "playing",
            "playback_status": "playing",
            "bridge_energy": 0.38,
            "qml_received_energy": 0.36,
            "staleBroadSnapshotIgnored": True,
            "staleBroadSnapshotIgnoredCount": 4,
        },
    ]

    classifications = classify_live_kraken_scenario(
        "single_spoken_response",
        rows,
        report={},
    )

    assert "stale_broad_voice_snapshot_overrides_hot_path" not in classifications
    assert "voice_visual_active_flap" not in classifications


def test_ar12_kraken_reports_stale_authoritative_rows_without_latch_bug() -> None:
    rows = [
        {
            "time_ms": 0,
            "authoritativeVoiceVisualActive": True,
            "authoritativePlaybackStatus": "playing",
            "qml_received_energy": 0.6,
            "targetVoiceVisualEnergy": 0.6,
            "voiceVisualTargetAgeMs": 20,
            "speaking_visual_active": True,
            "anchor_visual_state": "speaking",
            "finalSpeakingEnergy": 0.4,
            "blobScaleDrive": 0.3,
        },
        {
            "time_ms": 120,
            "authoritativeVoiceVisualActive": True,
            "authoritativePlaybackStatus": "playing",
            "qml_received_energy": 0.6,
            "targetVoiceVisualEnergy": 0.0,
            "voiceVisualTargetAgeMs": 1200,
            "anchorStaleEnergyReason": "voice_visual_stale",
            "speaking_visual_active": False,
            "anchor_visual_state": "idle",
            "finalSpeakingEnergy": 0.0,
            "blobScaleDrive": 0.0,
        },
    ]

    classifications = classify_live_kraken_scenario(
        "repeated_speech",
        rows,
        report={
            "speaking_state_stability": {
                "anchorStatusGlitchDetected": False,
                "midSpeechAnchorIdleRows": 0,
                "midSpeechSpeakingVisualFalseRows": 0,
                "staleAuthoritativeRowsIgnoredForLatch": 1,
                "latchBugReason": "stale_authoritative_rows_ignored",
            }
        },
    )

    assert "anchor_state_latch_bug" not in classifications
    assert "sync_measurement_stale_authoritative_rows" in classifications


def test_ar12_kraken_keeps_fresh_anchor_idle_as_latch_bug() -> None:
    rows = [
        {
            "time_ms": 0,
            "authoritativeVoiceVisualActive": True,
            "authoritativePlaybackStatus": "playing",
            "qml_received_energy": 0.4,
            "targetVoiceVisualEnergy": 0.4,
            "voiceVisualTargetAgeMs": 20,
            "speaking_visual_active": True,
            "anchor_visual_state": "speaking",
            "finalSpeakingEnergy": 0.3,
            "blobScaleDrive": 0.2,
        },
        {
            "time_ms": 60,
            "authoritativeVoiceVisualActive": True,
            "authoritativePlaybackStatus": "playing",
            "qml_received_energy": 0.5,
            "targetVoiceVisualEnergy": 0.5,
            "voiceVisualTargetAgeMs": 30,
            "anchorStaleEnergyReason": "",
            "speaking_visual_active": False,
            "anchor_visual_state": "idle",
            "finalSpeakingEnergy": 0.0,
            "blobScaleDrive": 0.0,
        },
        {
            "time_ms": 120,
            "authoritativeVoiceVisualActive": True,
            "authoritativePlaybackStatus": "playing",
            "qml_received_energy": 0.4,
            "targetVoiceVisualEnergy": 0.4,
            "voiceVisualTargetAgeMs": 24,
            "speaking_visual_active": True,
            "anchor_visual_state": "speaking",
            "finalSpeakingEnergy": 0.3,
            "blobScaleDrive": 0.2,
        },
    ]

    classifications = classify_live_kraken_scenario(
        "repeated_speech",
        rows,
        report={
            "speaking_state_stability": {
                "anchorStatusGlitchDetected": True,
                "midSpeechAnchorIdleRows": 1,
                "midSpeechSpeakingVisualFalseRows": 1,
                "staleAuthoritativeRowsIgnoredForLatch": 0,
                "latchBugReason": "fresh_authoritative_active_anchor_not_speaking",
            }
        },
    )

    assert "anchor_state_latch_bug" in classifications


def test_kraken_detects_payload_energy_missing_from_bridge_and_qml() -> None:
    rows = [
        {
            "time_ms": 0,
            "voice_visual_active": True,
            "playback_status": "playing",
            "payload_energy": 0.05,
            "bridge_energy": 0.0,
            "qml_received_energy": 0.0,
            "finalSpeakingEnergy": 0.0,
        },
        {
            "time_ms": 80,
            "voice_visual_active": True,
            "playback_status": "playing",
            "payload_energy": 0.72,
            "bridge_energy": 0.0,
            "qml_received_energy": 0.0,
            "finalSpeakingEnergy": 0.0,
        },
        {
            "time_ms": 160,
            "voice_visual_active": True,
            "playback_status": "playing",
            "payload_energy": 0.2,
            "bridge_energy": 0.0,
            "qml_received_energy": 0.0,
            "finalSpeakingEnergy": 0.0,
        },
    ]

    classifications = classify_live_kraken_scenario(
        "single_spoken_response",
        rows,
        report={},
    )

    assert "qml_binding_stale" in classifications


def test_kraken_detects_renderer_cadence_and_sync_failures() -> None:
    rows = [
        {"time_ms": 0, "pcm_energy": 0.0, "blobScaleDrive": 0.0},
        {"time_ms": 100, "pcm_energy": 0.8, "blobScaleDrive": 0.0},
        {"time_ms": 600, "pcm_energy": 0.1, "blobScaleDrive": 0.7},
    ]

    classifications = classify_live_kraken_scenario(
        "renderer_comparison",
        rows,
        report={
            "classification": ["anchor_canvas_paint_path_render_backend_bottleneck"],
            "render_metrics": {
                "anchorPaintFpsDuringSpeaking": 17.0,
                "sharedAnimationClockFpsDuringSpeakingMin": 9.0,
            },
            "audio_visual_alignment": {
                "perceptual_sync_status": "visual_late",
            },
        },
    )

    assert "canvas_paint_backend_bottleneck" in classifications
    assert "render_cadence_problem" in classifications
    assert "fog_or_shared_clock_starvation" in classifications
    assert "sync_visual_late" in classifications


def test_kraken_report_and_renderer_comparison_are_scalar_only(tmp_path: Path) -> None:
    scenario_reports = [
        {
            "scenario": "idle_baseline",
            "renderer": "legacy_blob_reference",
            "classification": ["production_chain_pass"],
            "ranges": {"finalSpeakingEnergy": {"span": 0.0}},
            "raw_audio_present": False,
            "pcm_bytes": b"forbidden",
        },
        {
            "scenario": "single_spoken_response",
            "renderer": "legacy_blob_qsg_candidate",
            "classification": ["sync_visual_late"],
            "authoritativeVoiceStateVersion": "AR6",
            "authoritativePlaybackStatus": "playing",
            "authoritativeStateSource": "hot_path",
            "lastAcceptedUpdateSource": "hot_path",
            "staleBroadSnapshotIgnoredCount": 0,
            "terminalEventAcceptedCount": 1,
            "render_metrics": {"anchorPaintFpsDuringSpeaking": 45.0},
            "ranges": {
                "finalSpeakingEnergy": {"span": 0.55},
                "blobScaleDrive": {"span": 0.44},
            },
            "raw_samples": [1, 2, 3],
        },
    ]

    summary = summarize_live_kraken(
        scenario_reports,
        process_state={"core": {"pid": 10}, "ui": {"pid": 11}},
        config_env_snapshot={"renderer_modes": ["legacy_blob_reference"]},
    )
    markdown = kraken_markdown(summary)
    renderer_md = renderer_comparison_markdown(summary["renderer_comparison"])
    serialized = json.dumps(summary, sort_keys=True) + markdown + renderer_md

    assert summary["raw_audio_present"] is False
    assert "sync_visual_late" in summary["classification"]
    assert "legacy_blob_qsg_candidate" in renderer_md
    qsg_row = next(
        row
        for row in summary["renderer_comparison"]
        if row["renderer"] == "legacy_blob_qsg_candidate"
    )
    assert qsg_row["authoritativeVoiceStateVersion"] == "AR6"
    assert qsg_row["authoritativePlaybackStatus"] == "playing"
    assert qsg_row["authoritativeStateSource"] == "hot_path"
    assert qsg_row["lastAcceptedUpdateSource"] == "hot_path"
    assert qsg_row["terminalEventAcceptedCount"] == 1
    assert all(token not in serialized for token in FORBIDDEN_RAW_TOKENS)

    artifact = tmp_path / "ar5_live_kraken_report.json"
    artifact.write_text(json.dumps(sanitize_kraken_payload(summary)), encoding="utf-8")
    assert "pcm_bytes" not in artifact.read_text(encoding="utf-8")


def test_kraken_classifies_audio_quality_separately_from_state() -> None:
    classifications = classify_live_kraken_scenario(
        "single_spoken_response",
        [
            {
                "time_ms": 0,
                "playback_status": "playing",
                "voice_visual_active": True,
                "speaking_visual_active": True,
                "audio_quality_status": "playback_buffer_underrun",
                "underrun_count": 2,
                "raw_audio_present": False,
            }
        ],
        report={
            "classification": ["production_chain_pass"],
            "audio_quality_status": "playback_buffer_underrun",
            "audio_quality_reasons": ["playback_buffer_underrun"],
            "anchor_dynamics_status": "pass",
            "renderer_cadence_status": "pass",
            "state_lifetime_status": "pass",
        },
    )

    assert "playback_buffer_underrun" in classifications
    assert "production_chain_pass" not in classifications


def test_kraken_summary_preserves_ar14_split_statuses_and_operator_scoring() -> None:
    summary = summarize_live_kraken(
        [
            {
                "scenario": "single_spoken_response",
                "renderer": "legacy_blob_qsg_candidate",
                "classification": ["playback_buffer_underrun"],
                "audio_quality_status": "playback_buffer_underrun",
                "anchor_dynamics_status": "startup_overshoot_limited",
                "sync_status": "inconclusive",
                "renderer_cadence_status": "pass",
                "state_lifetime_status": "pass",
                "operator_scoring": {
                    "audible_skip_seen": "yes",
                    "audible_buzz_or_squelch_seen": "no",
                    "anchor_startup_overshoot_seen": "uncertain",
                    "anchor_late_motion_collapse_seen": "uncertain",
                    "subjective_sync_good": "uncertain",
                    "operator_notes": "manual note",
                    "raw_audio_present": False,
                },
                "ranges": {
                    "finalSpeakingEnergy": {"span": 0.7},
                    "blobScaleDrive": {"span": 0.5},
                    "blobDeformationDrive": {"span": 0.3},
                },
                "render_metrics": {
                    "effectiveAnchorRenderer": "legacy_blob_qsg_candidate",
                    "anchorPaintFpsDuringSpeaking": 35.0,
                    "dynamicCorePaintFpsDuringSpeaking": 35.0,
                    "renderCadenceDuringSpeakingStable": True,
                    "requestPaintStormDetected": False,
                },
                "speaking_lifetime": {
                    "anchor_speaking_start_delay_ms": 40,
                    "anchor_release_tail_ms": 30,
                },
                "raw_audio_present": False,
            }
        ],
        process_state={"raw_audio_present": False},
        config_env_snapshot={"raw_audio_present": False},
    )

    item = summary["scenarios"]["single_spoken_response"][0]
    assert item["audio_quality_status"] == "playback_buffer_underrun"
    assert item["anchor_dynamics_status"] == "startup_overshoot_limited"
    assert item["operator_scoring"]["audible_skip_seen"] == "yes"
    assert summary["audio_quality_status"] == "playback_buffer_underrun"
    assert summary["anchor_dynamics_status"] == "startup_overshoot_limited"
    assert summary["state_lifetime_status"] == "pass"


def test_kraken_summary_ignores_not_measured_audio_when_active_scenarios_pass() -> None:
    summary = summarize_live_kraken(
        [
            {
                "scenario": "idle_baseline",
                "classification": ["production_chain_pass"],
                "audio_quality_status": "not_measured",
                "raw_audio_present": False,
            },
            {
                "scenario": "single_spoken_response",
                "classification": ["production_chain_pass"],
                "audio_quality_status": "pass",
                "raw_audio_present": False,
            },
        ],
        process_state={"raw_audio_present": False},
        config_env_snapshot={"raw_audio_present": False},
    )

    assert summary["audio_quality_status"] == "pass"


def test_ar8_qsg_promotion_gate_requires_human_visual_approval() -> None:
    live_summary = {
        "renderer_comparison": [
            {
                "renderer": "legacy_blob_qsg_candidate",
                "classification": ["sync_visual_late"],
                "anchorPaintFpsDuringSpeaking": 53.0,
                "dynamicCorePaintFpsDuringSpeaking": 53.0,
                "renderCadenceDuringSpeakingStable": True,
                "requestPaintStormDetected": False,
                "anchorSpeakingStartDelayMs": 90.0,
                "anchorReleaseTailMs": 180.0,
                "finalSpeakingEnergySpan": 0.62,
                "blobScaleDriveSpan": 0.44,
                "blobDeformationDriveSpan": 0.28,
                "raw_audio_present": False,
            }
        ],
        "raw_audio_present": False,
    }

    gate = qsg_candidate_promotion_gate(
        visual_status="pending_review",
        live_report=live_summary,
        human_approval="",
    )

    assert gate["qsg_candidate_visual_status"] == "pending_review"
    assert gate["qsg_candidate_default_eligible"] is False
    assert "visual_status_not_approved" in gate["qsg_candidate_rejection_reason"]
    assert "human_approval_missing" in gate["qsg_candidate_rejection_reason"]


def test_ar11_qsg_promotion_gate_rejected_state_blocks_default() -> None:
    live_summary = {
        "renderer_comparison": [
            {
                "renderer": "legacy_blob_qsg_candidate",
                "classification": ["production_chain_pass"],
                "anchorPaintFpsDuringSpeaking": 53.0,
                "dynamicCorePaintFpsDuringSpeaking": 53.0,
                "renderCadenceDuringSpeakingStable": True,
                "requestPaintStormDetected": False,
                "anchorSpeakingStartDelayMs": 90.0,
                "anchorReleaseTailMs": 180.0,
                "finalSpeakingEnergySpan": 0.62,
                "blobScaleDriveSpan": 0.44,
                "blobDeformationDriveSpan": 0.28,
                "raw_audio_present": False,
            }
        ],
        "raw_audio_present": False,
    }

    gate = qsg_candidate_promotion_gate(
        visual_status="rejected",
        live_report=live_summary,
        human_approval="operator rejected AR11 artifacts",
    )

    assert gate["qsg_candidate_default_eligible"] is False
    assert "visual_status_rejected" in gate["qsg_candidate_rejection_reason"]


def test_ar11_qsg_approval_and_visual_offset_helpers_normalize_inputs() -> None:
    assert _normalize_qsg_visual_approval("pending-review") == "pending"
    assert _normalize_qsg_visual_approval("approved") == "approved"
    assert _normalize_qsg_visual_approval("nope") == "pending"
    assert _clamp_voice_visual_offset_ms("-999") == -300
    assert _clamp_voice_visual_offset_ms("999") == 300


def test_ar10_qsg_promotion_gate_rejects_reflection_mismatch_even_with_approval() -> None:
    live_summary = {
        "renderer_comparison": [
            {
                "renderer": "legacy_blob_qsg_candidate",
                "classification": ["sync_visual_late"],
                "anchorPaintFpsDuringSpeaking": 53.0,
                "dynamicCorePaintFpsDuringSpeaking": 53.0,
                "renderCadenceDuringSpeakingStable": True,
                "requestPaintStormDetected": False,
                "anchorSpeakingStartDelayMs": 90.0,
                "anchorReleaseTailMs": 180.0,
                "finalSpeakingEnergySpan": 0.62,
                "blobScaleDriveSpan": 0.44,
                "blobDeformationDriveSpan": 0.28,
                "raw_audio_present": False,
            }
        ],
        "raw_audio_present": False,
    }

    gate = qsg_candidate_promotion_gate(
        visual_status="approved",
        live_report=live_summary,
        human_approval="approved",
        visual_differences=["reflection_shape_mismatch", "rounded_rect_reflection_visible"],
    )

    assert gate["qsg_candidate_default_eligible"] is False
    assert "reflection_shape_mismatch" in gate["qsg_candidate_rejection_reason"]
    assert "rounded_rect_reflection_visible" in gate["qsg_candidate_rejection_reason"]


def test_ar8_qsg_promotion_gate_passes_only_with_clean_live_metrics_and_approval() -> None:
    live_summary = {
        "renderer_comparison": [
            {
                "renderer": "legacy_blob_qsg_candidate",
                "classification": ["sync_visual_early"],
                "anchorPaintFpsDuringSpeaking": 50.0,
                "dynamicCorePaintFpsDuringSpeaking": 49.0,
                "renderCadenceDuringSpeakingStable": True,
                "requestPaintStormDetected": False,
                "anchorSpeakingStartDelayMs": 77.0,
                "anchorReleaseTailMs": 150.0,
                "finalSpeakingEnergySpan": 0.72,
                "blobScaleDriveSpan": 0.52,
                "blobDeformationDriveSpan": 0.35,
                "raw_audio_present": False,
            }
        ],
        "raw_audio_present": False,
    }

    gate = qsg_candidate_promotion_gate(
        visual_status="approved",
        live_report=live_summary,
        human_approval="approved by user after reviewing AR8 artifacts",
    )

    assert gate["qsg_candidate_default_eligible"] is True
    assert gate["qsg_candidate_rejection_reason"] == ""
    assert gate["default_renderer_after_pass"] == "legacy_blob_reference"
    assert gate["qsg_candidate_promoted_to_default"] is False


def test_ar8_qsg_promotion_gate_rejects_render_or_state_failures() -> None:
    live_summary = {
        "renderer_comparison": [
            {
                "renderer": "legacy_blob_qsg_candidate",
                "classification": ["render_cadence_problem", "false_speaking_without_audio"],
                "anchorPaintFpsDuringSpeaking": 22.0,
                "dynamicCorePaintFpsDuringSpeaking": 22.0,
                "renderCadenceDuringSpeakingStable": False,
                "requestPaintStormDetected": True,
                "anchorSpeakingStartDelayMs": 410.0,
                "anchorReleaseTailMs": 1200.0,
                "finalSpeakingEnergySpan": 0.1,
                "blobScaleDriveSpan": 0.04,
                "blobDeformationDriveSpan": 0.02,
                "raw_audio_present": False,
            }
        ],
        "raw_audio_present": False,
    }

    gate = qsg_candidate_promotion_gate(
        visual_status="approved",
        live_report=live_summary,
        human_approval="approved",
    )

    assert gate["qsg_candidate_default_eligible"] is False
    reason = gate["qsg_candidate_rejection_reason"]
    assert "blocked_classification:render_cadence_problem" in reason
    assert "blocked_classification:false_speaking_without_audio" in reason
    assert "anchor_paint_fps_below_30" in reason


def test_ar8_qsg_promotion_gate_rejects_if_any_live_qsg_scenario_blocks() -> None:
    live_summary = {
        "renderer_comparison": [
            {
                "scenario": "single_spoken_response",
                "renderer": "legacy_blob_qsg_candidate",
                "classification": ["sync_visual_late"],
                "anchorPaintFpsDuringSpeaking": 52.0,
                "dynamicCorePaintFpsDuringSpeaking": 52.0,
                "renderCadenceDuringSpeakingStable": True,
                "requestPaintStormDetected": False,
                "anchorSpeakingStartDelayMs": 90.0,
                "anchorReleaseTailMs": 35.0,
                "finalSpeakingEnergySpan": 0.7,
                "blobScaleDriveSpan": 0.58,
                "blobDeformationDriveSpan": 0.4,
                "raw_audio_present": False,
            },
            {
                "scenario": "repeated_speech",
                "renderer": "legacy_blob_qsg_candidate",
                "classification": ["delayed_speaking_entry", "sync_visual_late"],
                "anchorPaintFpsDuringSpeaking": 40.0,
                "dynamicCorePaintFpsDuringSpeaking": 40.0,
                "renderCadenceDuringSpeakingStable": True,
                "requestPaintStormDetected": False,
                "anchorSpeakingStartDelayMs": 3800.0,
                "anchorReleaseTailMs": 30.0,
                "finalSpeakingEnergySpan": 0.74,
                "blobScaleDriveSpan": 0.6,
                "blobDeformationDriveSpan": 0.41,
                "raw_audio_present": False,
            },
        ],
        "raw_audio_present": False,
    }

    gate = qsg_candidate_promotion_gate(
        visual_status="approved",
        live_report=live_summary,
        human_approval="approved",
    )

    assert gate["qsg_candidate_default_eligible"] is False
    assert "blocked_classification:delayed_speaking_entry" in gate["qsg_candidate_rejection_reason"]
    assert "speaking_start_delay_over_250ms" in gate["qsg_candidate_rejection_reason"]


def test_ar8_anchor_renderer_argument_runs_main_scenarios_with_that_renderer() -> None:
    main_renderer, renderers = _resolve_renderer_plan(
        anchor_renderer="legacy_blob_qsg_candidate",
        requested_renderers="legacy_blob_reference,legacy_blob_qsg_candidate",
    )

    assert main_renderer == "legacy_blob_qsg_candidate"
    assert renderers == ["legacy_blob_qsg_candidate"]


def test_ar8_default_renderer_plan_still_uses_legacy_reference() -> None:
    main_renderer, renderers = _resolve_renderer_plan(
        anchor_renderer="",
        requested_renderers="legacy_blob_reference,legacy_blob_fast_candidate",
    )

    assert main_renderer == "legacy_blob_reference"
    assert renderers == ["legacy_blob_reference", "legacy_blob_fast_candidate"]
