from __future__ import annotations

import json
import math
from collections import defaultdict
from statistics import mean
from typing import Any, Mapping, Sequence


FORBIDDEN_RAW_KEY_TOKENS = (
    "pcm_bytes",
    "audio_bytes",
    "raw_audio_bytes",
    "raw_samples",
    "sample_values",
    "base64",
)
PLAYBACK_ACTIVE_STATES = {
    "active",
    "opened",
    "playing",
    "playback_active",
    "prerolling",
    "started",
    "streaming",
}
VOICE_LATE_THRESHOLD_MS = 250.0
STUCK_SPEAKING_THRESHOLD_MS = 1000.0
ENERGY_ACTIVE_THRESHOLD = 0.035
QSG_RENDERER = "legacy_blob_qsg_candidate"
QSG_ALLOWED_SYNC_CLASSES = {
    "production_chain_pass",
    "sync_visual_early",
    "sync_visual_late",
}
QSG_BLOCKING_CLASSES = {
    "idle_false_speaking",
    "delayed_speaking_entry",
    "repeated_speech_delayed_entry",
    "delayed_anchor_animation_entry",
    "speaking_stuck_after_audio",
    "false_speaking_without_audio",
    "stale_playback_id",
    "stale_broad_voice_snapshot_overrides_hot_path",
    "voice_visual_active_flap",
    "qml_binding_stale",
    "anchor_state_latch_bug",
    "anchor_release_bug",
    "render_cadence_problem",
    "canvas_paint_backend_bottleneck",
    "fog_or_shared_clock_starvation",
}
QSG_BLOCKING_VISUAL_DIFFERENCES = {
    "reflection_shape_mismatch",
    "rounded_rect_reflection_visible",
    "reflection_animation_mismatch",
    "center_glass_highlight_mismatch",
}


def sanitize_kraken_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text == "raw_audio_present":
                clean[key_text] = False
                continue
            normalized = key_text.lower()
            if any(token in normalized for token in FORBIDDEN_RAW_KEY_TOKENS):
                continue
            sanitized = sanitize_kraken_payload(item)
            if sanitized is not None:
                clean[key_text] = sanitized
        clean.setdefault("raw_audio_present", False)
        return clean
    if isinstance(value, (list, tuple)):
        return [item for item in (sanitize_kraken_payload(item) for item in value) if item is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return str(value)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return math.isfinite(float(value)) and float(value) != 0.0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _row_time(row: Mapping[str, Any]) -> float | None:
    for key in ("time_ms", "qml_receive_time_ms", "status_wall_time_ms"):
        number = _number(row.get(key))
        if number is not None:
            return number
    return None


def _series(rows: Sequence[Mapping[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        number = _number(row.get(key))
        if number is not None:
            values.append(number)
    return values


def _span(values: Sequence[float]) -> float:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return 0.0
    return max(clean) - min(clean)


def _range(values: Sequence[float]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {"count": 0, "min": None, "max": None, "span": 0.0}
    low = min(clean)
    high = max(clean)
    return {
        "count": len(clean),
        "min": round(low, 6),
        "max": round(high, 6),
        "span": round(high - low, 6),
        "raw_audio_present": False,
    }


def _playback_active(row: Mapping[str, Any]) -> bool:
    status = str(
        row.get("authoritativePlaybackStatus")
        or row.get("activePlaybackStatus")
        or row.get("playback_status")
        or row.get("active_playback_status")
        or ""
    ).strip().lower()
    return status in PLAYBACK_ACTIVE_STATES


def _speaking_active(row: Mapping[str, Any]) -> bool:
    state = str(row.get("anchor_visual_state") or row.get("anchorCurrentVisualState") or "").strip().lower()
    final_energy = _number(row.get("finalSpeakingEnergy")) or 0.0
    return (
        _truthy(row.get("speaking_visual_active"))
        or _truthy(row.get("anchorSpeakingVisualActive"))
        or state == "speaking"
        or final_energy > ENERGY_ACTIVE_THRESHOLD
    )


def _speaking_state_active(row: Mapping[str, Any]) -> bool:
    state = str(row.get("anchor_visual_state") or row.get("anchorCurrentVisualState") or "").strip().lower()
    return (
        _truthy(row.get("speaking_visual_active"))
        or _truthy(row.get("anchorSpeakingVisualActive"))
        or state == "speaking"
    )


def _visual_active(row: Mapping[str, Any]) -> bool:
    return (
        _truthy(row.get("authoritativeVoiceVisualActive"))
        or _truthy(row.get("voice_visual_active"))
        or _truthy(row.get("qmlReceivedVoiceVisualActive"))
    )


def _has_audio_energy(row: Mapping[str, Any]) -> bool:
    return any(
        (_number(row.get(key)) or 0.0) > ENERGY_ACTIVE_THRESHOLD
        for key in (
            "pcm_energy",
            "meter_energy",
            "payload_energy",
            "voice_visual_energy",
            "authoritativeVoiceVisualEnergy",
        )
    )


def _first_time(rows: Sequence[Mapping[str, Any]], predicate: Any) -> float | None:
    for row in rows:
        if predicate(row):
            return _row_time(row)
    return None


def _duration_until(
    rows: Sequence[Mapping[str, Any]],
    start_predicate: Any,
    end_predicate: Any,
) -> float | None:
    start = None
    for row in rows:
        row_time = _row_time(row)
        if row_time is None:
            continue
        if start is None and start_predicate(row):
            start = row_time
        if start is not None and end_predicate(row):
            return max(0.0, row_time - start)
    if start is not None and rows:
        last = _row_time(rows[-1])
        if last is not None:
            return max(0.0, last - start)
    return None


def _active_flap_count(rows: Sequence[Mapping[str, Any]]) -> int:
    states: list[bool] = []
    for row in rows:
        if not _playback_active(row):
            continue
        states.append(_visual_active(row))
    if len(states) < 2:
        return 0
    return sum(1 for index in range(1, len(states)) if states[index] != states[index - 1])


def classify_live_kraken_scenario(
    scenario: str,
    timeline_rows: Sequence[Mapping[str, Any]],
    *,
    report: Mapping[str, Any] | None = None,
) -> list[str]:
    report = report or {}
    rows = list(timeline_rows)
    classes: set[str] = set()

    existing = [str(item) for item in report.get("classification", []) if str(item)]
    if "anchor_canvas_paint_path_render_backend_bottleneck" in existing:
        classes.add("canvas_paint_backend_bottleneck")
    if "render_cadence_problem" in existing:
        classes.add("render_cadence_problem")
    if "bridge_to_qml_broken" in existing:
        classes.add("qml_binding_stale")
    if "qml_to_anchor_mapping_broken" in existing:
        classes.add("anchor_state_latch_bug")
    if "speaking_state_delayed" in existing:
        classes.add("delayed_speaking_entry")
    if "speaking_state_stale_after_playback" in existing:
        classes.update({"speaking_stuck_after_audio", "anchor_release_bug"})

    for row in rows:
        no_audio = not _playback_active(row) and not _visual_active(row) and not _has_audio_energy(row)
        if no_audio and _speaking_state_active(row):
            classes.add("false_speaking_without_audio")
            if scenario == "idle_baseline":
                classes.add("idle_false_speaking")

    lifetime = report.get("speaking_lifetime") if isinstance(report.get("speaking_lifetime"), Mapping) else {}
    boundary_segments = (
        report.get("playback_boundary_segments")
        if isinstance(report.get("playback_boundary_segments"), Sequence)
        and not isinstance(report.get("playback_boundary_segments"), (str, bytes))
        else []
    )
    for segment in boundary_segments:
        if not isinstance(segment, Mapping):
            continue
        boundary_class = str(segment.get("boundary_classification") or "")
        boundary_delay = _number(segment.get("anchor_start_delay_from_pcm_ms"))
        if boundary_class in {
            "payload_handoff_delayed",
            "qml_handoff_delayed",
            "anchor_entry_delayed",
            "final_energy_delayed",
            "blob_drive_delayed",
        } or (boundary_delay is not None and boundary_delay > VOICE_LATE_THRESHOLD_MS):
            classes.add("delayed_speaking_entry")
            if scenario == "repeated_speech":
                classes.add("repeated_speech_delayed_entry")
            break
    start_delay = _number(lifetime.get("anchor_speaking_start_delay_ms"))
    if start_delay is None:
        playback_to_anchor = _duration_until(
            rows,
            lambda row: _playback_active(row) or _visual_active(row),
            _speaking_active,
        )
        start_delay = playback_to_anchor
    if start_delay is not None and start_delay > VOICE_LATE_THRESHOLD_MS:
        classes.add("delayed_speaking_entry")

    animation_delay = _duration_until(
        rows,
        lambda row: _playback_active(row)
        and _visual_active(row)
        and ((_number(row.get("qml_received_energy")) or _number(row.get("voice_visual_energy")) or 0.0) > ENERGY_ACTIVE_THRESHOLD),
        lambda row: ((_number(row.get("finalSpeakingEnergy")) or 0.0) > ENERGY_ACTIVE_THRESHOLD)
        and ((_number(row.get("blobScaleDrive")) or 0.0) > ENERGY_ACTIVE_THRESHOLD),
    )
    if animation_delay is not None and animation_delay > VOICE_LATE_THRESHOLD_MS:
        classes.add("delayed_anchor_animation_entry")

    stuck_after_audio = _number(lifetime.get("anchor_speaking_stuck_after_audio_ms"))
    release_tail = _number(lifetime.get("anchor_release_tail_ms"))
    if (
        stuck_after_audio is not None
        and stuck_after_audio > STUCK_SPEAKING_THRESHOLD_MS
    ) or (
        release_tail is not None and release_tail > STUCK_SPEAKING_THRESHOLD_MS
    ):
        classes.update({"speaking_stuck_after_audio", "anchor_release_bug"})

    stability = report.get("speaking_state_stability") if isinstance(report.get("speaking_state_stability"), Mapping) else {}
    if _truthy(stability.get("anchorStatusGlitchDetected")):
        classes.add("anchor_state_latch_bug")
    if (_number(stability.get("midSpeechAnchorIdleRows")) or 0) > 0 or (
        _number(stability.get("midSpeechSpeakingVisualFalseRows")) or 0
    ) > 0:
        classes.add("anchor_state_latch_bug")

    if _active_flap_count(rows) > 2:
        classes.add("voice_visual_active_flap")

    for row in rows:
        hot_active = (
            _truthy(row.get("authoritativeVoiceVisualActive"))
            or _truthy(row.get("hot_voice_visual_active"))
            or _truthy(row.get("bridge_voice_visual_active"))
            or ((_number(row.get("bridge_energy")) or 0.0) > ENERGY_ACTIVE_THRESHOLD)
            or ((_number(row.get("qml_received_energy")) or 0.0) > ENERGY_ACTIVE_THRESHOLD)
        )
        broad_inactive = not _visual_active(row)
        if _playback_active(row) and hot_active and broad_inactive:
            classes.add("stale_broad_voice_snapshot_overrides_hot_path")
            break

    bridge_span = _span(_series(rows, "bridge_energy"))
    qml_span = _span(_series(rows, "qml_received_energy"))
    upstream_visual_span = max(
        _span(_series(rows, "payload_energy")),
        _span(_series(rows, "meter_energy")),
        _span(_series(rows, "voice_visual_energy")),
    )
    if upstream_visual_span > 0.10 and bridge_span < 0.025 and qml_span < 0.025:
        classes.add("qml_binding_stale")
    if bridge_span > 0.10 and qml_span < 0.025:
        classes.add("qml_binding_stale")

    render_metrics = report.get("render_metrics") if isinstance(report.get("render_metrics"), Mapping) else {}
    anchor_paint_fps = _number(render_metrics.get("anchorPaintFpsDuringSpeaking"))
    if anchor_paint_fps is not None and 0 < anchor_paint_fps < 30:
        classes.add("render_cadence_problem")
    shared_min = _number(render_metrics.get("sharedAnimationClockFpsDuringSpeakingMin"))
    fog_mean = _number(render_metrics.get("fogTickFpsDuringSpeakingMean"))
    if (shared_min is not None and shared_min < 20) or (fog_mean is not None and fog_mean < 20):
        classes.add("fog_or_shared_clock_starvation")

    alignment = report.get("audio_visual_alignment") if isinstance(report.get("audio_visual_alignment"), Mapping) else {}
    sync_status = str(alignment.get("perceptual_sync_status") or "").strip().lower()
    if sync_status == "visual_late":
        classes.add("sync_visual_late")
    elif sync_status == "visual_early":
        classes.add("sync_visual_early")

    if not classes:
        classes.add("production_chain_pass")
    if "production_chain_pass" in classes and len(classes) > 1:
        classes.remove("production_chain_pass")
    return sorted(classes)


def _scenario_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    ranges = report.get("ranges") if isinstance(report.get("ranges"), Mapping) else {}
    render_metrics = report.get("render_metrics") if isinstance(report.get("render_metrics"), Mapping) else {}
    lifetime = report.get("speaking_lifetime") if isinstance(report.get("speaking_lifetime"), Mapping) else {}
    return sanitize_kraken_payload(
        {
            "scenario": report.get("scenario"),
            "renderer": report.get("renderer") or render_metrics.get("effectiveAnchorRenderer"),
            "classification": report.get("classification", []),
            "anchorPaintFpsDuringSpeaking": render_metrics.get("anchorPaintFpsDuringSpeaking"),
            "anchorRequestPaintFpsDuringSpeaking": render_metrics.get("anchorRequestPaintFpsDuringSpeaking"),
            "anchorLocalSpeakingFrameFps": render_metrics.get("anchorLocalSpeakingFrameFps"),
            "dynamicCorePaintFpsDuringSpeaking": render_metrics.get("dynamicCorePaintFpsDuringSpeaking"),
            "renderCadenceDuringSpeakingStable": render_metrics.get("renderCadenceDuringSpeakingStable"),
            "requestPaintStormDetected": render_metrics.get("requestPaintStormDetected"),
            "sharedAnimationClockFpsDuringSpeakingMin": render_metrics.get("sharedAnimationClockFpsDuringSpeakingMin"),
            "fogTickFpsDuringSpeakingMean": render_metrics.get("fogTickFpsDuringSpeakingMean"),
            "anchorSpeakingStartDelayMs": lifetime.get("anchor_speaking_start_delay_ms"),
            "anchorReleaseTailMs": lifetime.get("anchor_release_tail_ms"),
            "finalSpeakingEnergySpan": (ranges.get("finalSpeakingEnergy") or {}).get("span") if isinstance(ranges.get("finalSpeakingEnergy"), Mapping) else None,
            "blobScaleDriveSpan": (ranges.get("blobScaleDrive") or {}).get("span") if isinstance(ranges.get("blobScaleDrive"), Mapping) else None,
            "blobDeformationDriveSpan": (ranges.get("blobDeformationDrive") or {}).get("span") if isinstance(ranges.get("blobDeformationDrive"), Mapping) else None,
            "authoritativeVoiceStateVersion": report.get("authoritativeVoiceStateVersion")
            or report.get("authoritative_voice_state_version"),
            "authoritativePlaybackStatus": report.get("authoritativePlaybackStatus"),
            "authoritativeStateSource": report.get("authoritativeStateSource"),
            "lastAcceptedUpdateSource": report.get("lastAcceptedUpdateSource"),
            "staleBroadSnapshotIgnoredCount": report.get(
                "staleBroadSnapshotIgnoredCount"
            ),
            "terminalEventAcceptedCount": report.get("terminalEventAcceptedCount"),
            "artifact_dir": report.get("artifact_dir"),
            "visual_artifact_path": report.get("visual_artifact_path"),
            "raw_audio_present": False,
        }
    )


def _qsg_gate_rows(live_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    comparison = live_report.get("renderer_comparison")
    if isinstance(comparison, Sequence) and not isinstance(comparison, (str, bytes)):
        for item in comparison:
            if isinstance(item, Mapping) and str(item.get("renderer") or "") == QSG_RENDERER:
                rows.append(sanitize_kraken_payload(item))
    reports = live_report.get("scenario_reports")
    if not rows and isinstance(reports, Sequence) and not isinstance(reports, (str, bytes)):
        for item in reports:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("renderer") or "") == QSG_RENDERER:
                rows.append(_scenario_summary(item))
    if str(live_report.get("renderer") or "") == QSG_RENDERER:
        rows.append(_scenario_summary(live_report))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        key = (
            str(row.get("scenario") or ""),
            str(row.get("renderer") or ""),
            str(row.get("artifact_dir") or ""),
            ",".join(str(item) for item in row.get("classification", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _best_qsg_gate_row(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            _number(row.get("anchorPaintFpsDuringSpeaking")) or 0.0,
            _number(row.get("dynamicCorePaintFpsDuringSpeaking")) or 0.0,
        ),
    )


def _qsg_gate_active_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    active_rows: list[Mapping[str, Any]] = []
    for row in rows:
        scenario = str(row.get("scenario") or "")
        has_speaking_metric = _number(row.get("anchorPaintFpsDuringSpeaking")) is not None
        has_speaking_span = max(
            _number(row.get("finalSpeakingEnergySpan")) or 0.0,
            _number(row.get("blobScaleDriveSpan")) or 0.0,
        ) > 0.05
        if has_speaking_metric or has_speaking_span or scenario in {
            "single_spoken_response",
            "repeated_speech",
            "renderer_comparison",
        }:
            active_rows.append(row)
    return active_rows


def qsg_candidate_promotion_gate(
    *,
    visual_status: str = "pending_review",
    live_report: Mapping[str, Any] | None = None,
    human_approval: str = "",
    visual_differences: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return the AR8 default-promotion decision without changing defaults."""
    normalized_visual_status = str(visual_status or "pending_review").strip().lower()
    live_report = live_report or {}
    rows = _qsg_gate_rows(live_report)
    row = _best_qsg_gate_row(rows)
    reasons: list[str] = []

    if normalized_visual_status != "approved":
        reasons.append("visual_status_not_approved")
    if not str(human_approval or "").strip():
        reasons.append("human_approval_missing")
    visual_difference_values = {str(item) for item in (visual_differences or []) if str(item)}
    for item in sorted(visual_difference_values & QSG_BLOCKING_VISUAL_DIFFERENCES):
        reasons.append(item)
    if row is None:
        reasons.append("qsg_live_metrics_missing")
        row = {}

    active_rows = _qsg_gate_active_rows(rows)
    classes = {
        str(item)
        for candidate in rows
        for item in candidate.get("classification", [])
        if str(item)
    }
    for item in sorted(classes):
        if item not in QSG_ALLOWED_SYNC_CLASSES or item in QSG_BLOCKING_CLASSES:
            reasons.append(f"blocked_classification:{item}")

    if not active_rows:
        reasons.append("qsg_live_metrics_missing")

    anchor_paint_values = [_number(item.get("anchorPaintFpsDuringSpeaking")) for item in active_rows]
    dynamic_paint_values = [_number(item.get("dynamicCorePaintFpsDuringSpeaking")) for item in active_rows]
    start_delays = [_number(item.get("anchorSpeakingStartDelayMs")) for item in active_rows]
    release_tails = [_number(item.get("anchorReleaseTailMs")) for item in active_rows]
    final_spans = [_number(item.get("finalSpeakingEnergySpan")) for item in active_rows]
    blob_scale_spans = [_number(item.get("blobScaleDriveSpan")) for item in active_rows]
    blob_deformation_spans = [_number(item.get("blobDeformationDriveSpan")) for item in active_rows]

    if any(value is None or value < 30.0 for value in anchor_paint_values):
        reasons.append("anchor_paint_fps_below_30")
    if any(value is None or value < 30.0 for value in dynamic_paint_values):
        reasons.append("dynamic_core_paint_fps_below_30")
    if any(item.get("renderCadenceDuringSpeakingStable") is not True for item in active_rows):
        reasons.append("render_cadence_not_stable")
    if any(item.get("requestPaintStormDetected") is True for item in active_rows):
        reasons.append("request_paint_storm_detected")
    if any(value is None or value >= VOICE_LATE_THRESHOLD_MS for value in start_delays):
        reasons.append("speaking_start_delay_over_250ms")
    if any(value is not None and value >= STUCK_SPEAKING_THRESHOLD_MS for value in release_tails):
        reasons.append("release_tail_over_1000ms")
    if any(value is None or value < 0.25 for value in final_spans):
        reasons.append("final_speaking_energy_span_not_meaningful")
    if any(value is None or value < 0.15 for value in blob_scale_spans):
        reasons.append("blob_scale_drive_span_not_meaningful")
    if any(value is None or value < 0.10 for value in blob_deformation_spans):
        reasons.append("blob_deformation_drive_span_not_meaningful")
    if any(_truthy(item.get("raw_audio_present")) for item in rows) or _truthy(live_report.get("raw_audio_present")):
        reasons.append("raw_audio_present")

    reasons = sorted(dict.fromkeys(reasons))
    eligible = not reasons
    return sanitize_kraken_payload(
        {
            "qsg_candidate_visual_status": normalized_visual_status,
            "qsg_candidate_default_eligible": eligible,
            "qsg_candidate_rejection_reason": ";".join(reasons),
            "qsg_candidate_visual_differences": list(visual_differences or []),
            "qsg_candidate_live_metrics": row,
            "qsg_candidate_all_live_metrics": list(rows),
            "qsg_candidate_allowed_sync_classifications": sorted(QSG_ALLOWED_SYNC_CLASSES),
            "qsg_candidate_promoted_to_default": False,
            "default_renderer_after_pass": "legacy_blob_reference",
            "human_approval_present": bool(str(human_approval or "").strip()),
            "raw_audio_present": False,
        }
    )


def summarize_live_kraken(
    scenario_reports: Sequence[Mapping[str, Any]],
    *,
    process_state: Mapping[str, Any] | None = None,
    config_env_snapshot: Mapping[str, Any] | None = None,
    qsg_visual_status: str = "pending_review",
    qsg_human_approval: str = "",
    qsg_visual_differences: Sequence[str] | None = None,
) -> dict[str, Any]:
    sanitized_reports = [sanitize_kraken_payload(report) for report in scenario_reports]
    classes: set[str] = set()
    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in sanitized_reports:
        scenario = str(report.get("scenario") or "unknown")
        by_scenario[scenario].append(_scenario_summary(report))
        for item in report.get("classification", []):
            classes.add(str(item))

    if not classes:
        classes.add("production_chain_pass")
    if "production_chain_pass" in classes and len(classes) > 1:
        classes.remove("production_chain_pass")

    renderer_comparison = [
        _scenario_summary(report)
        for report in sanitized_reports
        if str(report.get("scenario") or "").startswith("renderer_")
        or str(report.get("scenario") or "") == "renderer_comparison"
        or report.get("renderer") is not None
    ]
    default_should_change = False
    for item in renderer_comparison:
        renderer = str(item.get("renderer") or "")
        classes_for_item = {str(value) for value in item.get("classification", [])}
        if renderer != "legacy_blob_reference" and classes_for_item == {"production_chain_pass"}:
            default_should_change = False

    summary = {
        "probe": "voice_ar5_live_kraken",
        "classification": sorted(classes),
        "scenarios": dict(by_scenario),
        "scenario_reports": sanitized_reports,
        "renderer_comparison": renderer_comparison,
        "default_renderer_after_pass": "legacy_blob_reference",
        "default_should_change": default_should_change,
        "process_state": sanitize_kraken_payload(process_state or {}),
        "config_env_snapshot": sanitize_kraken_payload(config_env_snapshot or {}),
        "qsg_promotion_gate": qsg_candidate_promotion_gate(
            visual_status=qsg_visual_status,
            live_report={
                "renderer_comparison": renderer_comparison,
                "scenario_reports": sanitized_reports,
                "raw_audio_present": False,
            },
            human_approval=qsg_human_approval,
            visual_differences=qsg_visual_differences,
        ),
        "raw_audio_present": False,
    }
    return sanitize_kraken_payload(summary)


def kraken_markdown(summary: Mapping[str, Any]) -> str:
    classes = ", ".join(str(item) for item in summary.get("classification", []))
    lines = [
        "# Voice-AR5 Live Kraken Flight Recorder",
        "",
        f"- Classification: `{classes}`",
        f"- Default renderer after pass: `{summary.get('default_renderer_after_pass', 'legacy_blob_reference')}`",
        "- Privacy: scalar-only, raw_audio_present=false",
        "",
        "## Scenario Results",
    ]
    scenarios = summary.get("scenarios") if isinstance(summary.get("scenarios"), Mapping) else {}
    for scenario, items in scenarios.items():
        if scenario == "raw_audio_present" or not isinstance(items, list):
            continue
        lines.append(f"### {scenario}")
        for item in items:
            item_classes = ", ".join(str(value) for value in item.get("classification", []))
            lines.append(
                "- renderer="
                f"`{item.get('renderer', '')}`, classification=`{item_classes}`, "
                f"paint_fps={item.get('anchorPaintFpsDuringSpeaking')}, "
                f"start_delay_ms={item.get('anchorSpeakingStartDelayMs')}, "
                f"release_tail_ms={item.get('anchorReleaseTailMs')}"
            )
    lines.extend(["", "## Renderer Comparison", renderer_comparison_markdown(summary.get("renderer_comparison", []))])
    gate = summary.get("qsg_promotion_gate")
    if isinstance(gate, Mapping):
        lines.extend(
            [
                "",
                "## QSG Promotion Gate",
                f"- Visual status: `{gate.get('qsg_candidate_visual_status')}`",
                f"- Default eligible: `{gate.get('qsg_candidate_default_eligible')}`",
                f"- Rejection reason: `{gate.get('qsg_candidate_rejection_reason') or ''}`",
                "- Default renderer remains `legacy_blob_reference` until explicit visual approval.",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def renderer_comparison_markdown(renderer_rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "| Renderer | Classification | Paint FPS | Final Energy Span | Blob Span | Default? |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in renderer_rows:
        classes = ", ".join(str(item) for item in row.get("classification", []))
        renderer = str(row.get("renderer") or "")
        default_note = "keep reference" if renderer == "legacy_blob_reference" else "human review required"
        lines.append(
            f"| `{renderer}` | `{classes}` | {row.get('anchorPaintFpsDuringSpeaking')} | "
            f"{row.get('finalSpeakingEnergySpan')} | {row.get('blobScaleDriveSpan')} | {default_note} |"
        )
    return "\n".join(lines)


def assert_no_raw_audio_payload(payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, sort_keys=True)
    lowered = serialized.lower()
    forbidden = [token for token in FORBIDDEN_RAW_KEY_TOKENS if token in lowered]
    if forbidden:
        raise AssertionError(f"raw audio fields present in Kraken payload: {forbidden}")
