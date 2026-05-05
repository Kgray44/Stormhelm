from __future__ import annotations

import csv
import io
import math
from statistics import mean
from typing import Any, Mapping, Sequence

from stormhelm.core.voice.reactive_chain_probe import PCM_STREAM_SOURCE
from stormhelm.core.voice.reactive_chain_probe import correlation


RAW_AUDIO_KEY_TOKENS = (
    "pcm_bytes",
    "audio_bytes",
    "raw_audio_bytes",
    "raw_samples",
    "sample_values",
    "samples",
    "base64",
    "waveform",
)
SCALAR_TYPES = (str, int, float, bool, type(None))
TIMELINE_FIELDNAMES = [
    "time_ms",
    "pcm_energy",
    "meter_energy",
    "payload_energy",
    "bridge_energy",
    "qml_received_energy",
    "finalSpeakingEnergy",
    "blobScaleDrive",
    "blobDeformationDrive",
    "blobRadiusScale",
    "radianceDrive",
    "ringDrive",
    "visualAmplitudeCompressionRatio",
    "visualAmplitudeLatencyMs",
    "anchor_paint_time",
    "dynamic_core_paint_time",
    "static_frame_paint_time",
    "voice_visual_active",
    "hot_voice_visual_active",
    "authoritativeVoiceStateVersion",
    "authoritativeVoiceVisualActive",
    "authoritativeVoiceVisualEnergy",
    "authoritativePlaybackId",
    "authoritativePlaybackStatus",
    "activePlaybackId",
    "activePlaybackStatus",
    "authoritativeStateSequence",
    "authoritativeStateSource",
    "lastAcceptedUpdateSource",
    "lastIgnoredUpdateSource",
    "staleBroadSnapshotIgnored",
    "staleBroadSnapshotIgnoredCount",
    "hotPathAcceptedCount",
    "terminalEventAcceptedCount",
    "playbackIdSwitchCount",
    "playbackIdMismatchIgnoredCount",
    "voiceVisualActiveFlapCount",
    "speaking_visual_active",
    "anchor_visual_state",
    "playback_status",
    "fog_active",
    "frame_gap_ms",
    "raw_audio_present",
]
VOICE_AR1_LIVE_RENDER_BASELINE = {
    "source": "voice_ar1_live_measured_evidence",
    "anchorRequestPaintFpsDuringSpeaking": None,
    "anchorPaintFps": 5.583,
    "anchorPaintFpsDuringSpeaking": 5.583,
    "anchorLocalSpeakingFrameFps": None,
    "dynamicCorePaintFpsDuringSpeaking": None,
    "sharedAnimationClockFpsDuringSpeakingMin": 10.475,
    "finalSpeakingEnergyRange": {"min": 0.0, "max": 0.090125, "span": 0.090125},
    "anchorSpeakingStartDelayMs": 1003.72,
    "anchorReleaseTailMs": None,
    "anchorSpeakingStuckAfterAudioMs": None,
    "qmlReceiveMaxGapMsDuringSpeaking": 244.0,
    "qmlDiagnosticMaxGapMs": 625.0,
    "maxFrameGapMsDuringSpeaking": None,
    "fogTickFpsDuringSpeakingMean": None,
    "raw_audio_present": False,
}
VOICE_AR2_LIVE_RENDER_BASELINE = {
    "source": "voice_ar2_live_measured_canvas_bottleneck",
    "anchorRequestPaintFpsDuringSpeaking": 48.82,
    "anchorPaintFps": 24.57,
    "anchorPaintFpsDuringSpeaking": 24.57,
    "dynamicCorePaintFpsDuringSpeaking": None,
    "anchorLocalSpeakingFrameFps": 38.80,
    "sharedAnimationClockFpsDuringSpeakingMin": None,
    "finalSpeakingEnergyRange": {"min": 0.0, "max": 0.7206, "span": 0.7206},
    "anchorSpeakingStartDelayMs": 77.8,
    "anchorReleaseTailMs": 157.0,
    "anchorSpeakingStuckAfterAudioMs": None,
    "maxFrameGapMsDuringSpeaking": None,
    "fogTickFpsDuringSpeakingMean": None,
    "classification": "anchor_canvas_paint_path_render_backend_bottleneck",
    "raw_audio_present": False,
}


def _is_forbidden_raw_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    if normalized == "raw_audio_present":
        return False
    return any(token in normalized for token in RAW_AUDIO_KEY_TOKENS)


def _round(value: Any, digits: int = 6) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _series(rows: Sequence[Mapping[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, bool):
            continue
        rounded = _round(value)
        if rounded is not None:
            values.append(float(rounded))
    return values


def _range(values: Sequence[float]) -> dict[str, float | int | None]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {"count": 0, "min": None, "max": None, "span": 0.0}
    low = min(clean)
    high = max(clean)
    return {
        "count": len(clean),
        "min": _round(low),
        "max": _round(high),
        "span": _round(high - low),
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _voice_visual_row_active(row: Mapping[str, Any]) -> bool:
    return _truthy(row.get("authoritativeVoiceVisualActive")) or _truthy(
        row.get("voice_visual_active")
    )


def _speaking_state_stability(
    rows: Sequence[Mapping[str, Any]]
) -> dict[str, bool | int]:
    voice_active_rows = [
        row for row in rows if _voice_visual_row_active(row)
    ]
    speaking_true_indices = [
        index
        for index, row in enumerate(rows)
        if _truthy(row.get("speaking_visual_active"))
    ]
    first_speaking_index = (
        min(speaking_true_indices) if speaking_true_indices else None
    )
    last_speaking_index = max(speaking_true_indices) if speaking_true_indices else None
    mid_speech_rows = (
        rows[first_speaking_index : last_speaking_index + 1]
        if first_speaking_index is not None and last_speaking_index is not None
        else []
    )
    active_mid_speech_rows = [
        row for row in mid_speech_rows if _voice_visual_row_active(row)
    ]
    mid_speech_false_rows = [
        row
        for row in active_mid_speech_rows
        if not _truthy(row.get("speaking_visual_active"))
    ]
    mid_speech_idle_rows = [
        row
        for row in active_mid_speech_rows
        if str(row.get("anchor_visual_state", "")).strip().lower() == "idle"
    ]
    return {
        "voiceVisualActiveRows": len(voice_active_rows),
        "speakingVisualTrueRows": len(speaking_true_indices),
        "speakingVisualFalseWhileVoiceVisualActiveRows": len(
            [
                row
                for row in voice_active_rows
                if not _truthy(row.get("speaking_visual_active"))
            ]
        ),
        "anchorIdleWhileVoiceVisualActiveRows": len(
            [
                row
                for row in voice_active_rows
                if str(row.get("anchor_visual_state", "")).strip().lower() == "idle"
            ]
        ),
        "midSpeechSpeakingVisualFalseRows": len(mid_speech_false_rows),
        "midSpeechAnchorIdleRows": len(mid_speech_idle_rows),
        "anchorStatusGlitchDetected": bool(
            mid_speech_false_rows or mid_speech_idle_rows
        ),
        "raw_audio_present": False,
    }


def _mean_or_none(values: Sequence[float]) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return None
    return _round(mean(clean), 3)


def _varies(values: Sequence[float], *, threshold: float = 0.035) -> bool:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if len(clean) < 3:
        return False
    return max(clean) - min(clean) >= threshold


def _first_gap_ms(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    times = [_round(row.get(key), 3) for row in rows]
    clean = [float(value) for value in times if value is not None]
    if len(clean) < 2:
        return None
    return max(clean[index] - clean[index - 1] for index in range(1, len(clean)))


def _mean_delta_ms(
    rows: Sequence[Mapping[str, Any]],
    left_key: str,
    right_key: str,
) -> float | None:
    deltas: list[float] = []
    for row in rows:
        left = _round(row.get(left_key), 3)
        right = _round(row.get(right_key), 3)
        if left is None or right is None:
            continue
        if float(left) <= 0.0 or float(right) <= 0.0:
            continue
        deltas.append(float(right) - float(left))
    if not deltas:
        return None
    return _round(mean(deltas), 3)


def _timed_series(
    rows: Sequence[Mapping[str, Any]],
    value_key: str,
    *,
    time_key: str = "time_ms",
) -> list[tuple[float, float]]:
    series: list[tuple[float, float]] = []
    for row in rows:
        timestamp = _round(row.get(time_key), 3)
        value = _round(row.get(value_key), 6)
        if timestamp is None or value is None:
            continue
        if isinstance(row.get(value_key), bool):
            continue
        series.append((float(timestamp), float(value)))
    return sorted(series, key=lambda item: item[0])


def _latest_value_at(series: Sequence[tuple[float, float]], timestamp: float) -> float | None:
    latest: float | None = None
    for sample_time, value in series:
        if sample_time > timestamp:
            break
        latest = value
    return latest


def _lagged_correlation(
    rows: Sequence[Mapping[str, Any]],
    source_key: str,
    target_key: str,
    *,
    max_lag_ms: int = 600,
    step_ms: int = 20,
) -> dict[str, Any]:
    """Estimate target lag relative to source using scalar envelope values only."""
    source = _timed_series(rows, source_key)
    target = _timed_series(rows, target_key)
    if len(source) < 3 or len(target) < 3:
        return {
            "source": source_key,
            "target": target_key,
            "best_lag_ms": None,
            "correlation": None,
            "sample_count": 0,
            "raw_audio_present": False,
        }
    best_lag: int | None = None
    best_corr: float | None = None
    best_count = 0
    for lag in range(-int(max_lag_ms), int(max_lag_ms) + 1, int(step_ms)):
        source_values: list[float] = []
        target_values: list[float] = []
        for target_time, target_value in target:
            source_value = _latest_value_at(source, target_time - lag)
            if source_value is None:
                continue
            source_values.append(source_value)
            target_values.append(target_value)
        if len(source_values) < 3:
            continue
        if not _varies(source_values, threshold=0.010) or not _varies(target_values, threshold=0.010):
            continue
        corr = _round(correlation(source_values, target_values), 6)
        if corr is None:
            continue
        if best_corr is None or corr > best_corr:
            best_corr = float(corr)
            best_lag = lag
            best_count = len(source_values)
    return {
        "source": source_key,
        "target": target_key,
        "best_lag_ms": best_lag,
        "correlation": _round(best_corr),
        "sample_count": best_count,
        "raw_audio_present": False,
    }


def _sync_status_from_lag(lag_ms: float | None, *, aligned_ms: float = 120.0) -> str:
    if lag_ms is None:
        return "inconclusive"
    if lag_ms > aligned_ms:
        return "visual_late"
    if lag_ms < -aligned_ms:
        return "visual_early"
    return "aligned"


def _clamped_visual_offset_ms(lag_ms: float | None) -> float | None:
    if lag_ms is None:
        return None
    return _round(max(-300.0, min(300.0, -float(lag_ms))), 3)


def _sync_confidence_from_direct_correlation(
    correlation_value: float | None,
    sample_count: int | float | None,
) -> str:
    if correlation_value is None:
        return "low"
    samples = 0
    try:
        samples = int(sample_count or 0)
    except (TypeError, ValueError):
        samples = 0
    if correlation_value >= 0.70 and samples >= 180:
        return "high"
    if correlation_value >= 0.50 and samples >= 120:
        return "medium"
    return "low"


def _offset_recommendation_for_confidence(
    lag_ms: float | None,
    *,
    status: str,
    confidence: str,
    basis: str,
) -> tuple[float | None, str]:
    if status == "aligned":
        return None, f"{basis}_aligned_no_offset"
    if confidence == "high":
        return _clamped_visual_offset_ms(lag_ms), f"high_confidence_{basis}_proposal_only"
    return None, f"{basis}_measurement_only"


def _stage_latency_components(latency: Mapping[str, Any]) -> dict[str, float]:
    stage_keys = (
        "pcm_to_meter",
        "meter_to_payload",
        "payload_to_bridge",
        "bridge_to_qml",
        "qml_to_finalSpeakingEnergy",
        "finalSpeakingEnergy_to_paint",
    )
    components: dict[str, float] = {}
    for key in stage_keys:
        value = _round(latency.get(key), 3)
        if value is not None:
            components[key] = float(value)
    return components


def _stage_latency_inconsistent(latency: Mapping[str, Any]) -> bool:
    components = _stage_latency_components(latency)
    if not components:
        return False
    if any(value < -20.0 for value in components.values()):
        return True
    pcm_to_meter = components.get("pcm_to_meter")
    return pcm_to_meter is not None and pcm_to_meter > 1000.0


def _sync_likely_cause(
    *,
    status: str,
    latency: Mapping[str, Any],
    direct_correlation_usable: bool,
) -> str:
    if status == "aligned":
        return "audio_to_visual_stage_latency_within_probe_threshold"
    if direct_correlation_usable:
        return "direct_pcm_to_visual_drive_lag"
    stage_values = {
        key: _round(latency.get(key), 3)
        for key in (
            "pcm_to_meter",
            "meter_to_payload",
            "payload_to_bridge",
            "bridge_to_qml",
            "qml_to_finalSpeakingEnergy",
            "finalSpeakingEnergy_to_paint",
        )
    }
    clean = {key: value for key, value in stage_values.items() if value is not None}
    if not clean:
        return "insufficient_stage_timestamp_evidence"
    largest_stage = max(clean, key=lambda key: abs(float(clean[key] or 0.0)))
    stage_reason = {
        "pcm_to_meter": "audio_meter_latency",
        "meter_to_payload": "backend_payload_latency",
        "payload_to_bridge": "bridge_delivery_or_status_surface_latency",
        "bridge_to_qml": "qml_delivery_latency",
        "qml_to_finalSpeakingEnergy": "anchor_energy_smoothing_or_mapping_latency",
        "finalSpeakingEnergy_to_paint": "renderer_or_paint_cadence_latency",
    }.get(largest_stage, "stage_latency")
    return stage_reason


def audio_visual_sync_diagnosis(
    alignment: Mapping[str, Any],
    latency: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidates: list[tuple[str, Mapping[str, Any], float]] = []
    for key in ("pcm_to_blobScaleDrive", "pcm_to_finalSpeakingEnergy"):
        stage = alignment.get(key)
        if not isinstance(stage, Mapping):
            continue
        correlation_value = _round(stage.get("correlation"))
        lag = _round(stage.get("best_lag_ms"))
        if correlation_value is None or lag is None:
            continue
        if correlation_value < 0.35:
            continue
        candidates.append((key, stage, float(correlation_value)))
    if candidates:
        basis, stage, _ = max(candidates, key=lambda item: item[2])
        lag_ms = _round(stage.get("best_lag_ms"))
        correlation_value = _round(stage.get("correlation"))
        confidence = _sync_confidence_from_direct_correlation(
            correlation_value,
            stage.get("sample_count"),
        )
        status = _sync_status_from_lag(lag_ms)
        recommended_offset, recommendation_basis = _offset_recommendation_for_confidence(
            lag_ms,
            status=status,
            confidence=confidence,
            basis="direct_correlation",
        )
        return {
            "perceptual_sync_status": status,
            "perceptual_sync_basis": basis,
            "perceptual_sync_best_lag_ms": lag_ms,
            "perceptual_sync_correlation": correlation_value,
            "direct_pcm_visual_correlation_usable": True,
            "sync_latency_basis": "direct_correlation",
            "sync_latency_ms": lag_ms,
            "direct_pcm_to_visual_correlation": correlation_value,
            "sync_confidence": confidence,
            "stage_latency_estimate_ms": _round(
                (latency if isinstance(latency, Mapping) else {}).get(
                    "pcm_to_paint_estimated"
                ),
                3,
            ),
            "sync_likely_cause": _sync_likely_cause(
                status=status,
                latency=latency if isinstance(latency, Mapping) else {},
                direct_correlation_usable=True,
            ),
            "recommended_visual_offset_ms": recommended_offset,
            "visual_offset_applied_ms": 0,
            "visual_offset_recommendation_basis": recommendation_basis,
            "sync_diagnosis_reason": (
                "direct audible PCM to visual-drive correlation was usable for "
                "classification; an offset is recommended only at high confidence"
            ),
            "raw_audio_present": False,
        }

    latency_payload = latency if isinstance(latency, Mapping) else {}
    if _stage_latency_inconsistent(latency_payload):
        return {
            "perceptual_sync_status": "inconclusive",
            "perceptual_sync_basis": "stage_latency_inconsistent",
            "perceptual_sync_best_lag_ms": None,
            "perceptual_sync_correlation": None,
            "direct_pcm_visual_correlation_usable": False,
            "sync_latency_basis": "stage_latency_inconsistent",
            "sync_latency_ms": None,
            "direct_pcm_to_visual_correlation": None,
            "sync_confidence": "low",
            "stage_latency_estimate_ms": None,
            "sync_likely_cause": "stage_timestamp_alignment_inconsistent",
            "recommended_visual_offset_ms": None,
            "visual_offset_applied_ms": 0,
            "visual_offset_recommendation_basis": "none",
            "sync_diagnosis_reason": (
                "stage timestamp deltas include impossible negative or implausibly "
                "large values; direct PCM-to-visual correlation was too weak to "
                "calibrate a safe visual offset"
            ),
            "raw_audio_present": False,
        }
    pcm_to_paint = _round(latency_payload.get("pcm_to_paint_estimated"), 3)
    if pcm_to_paint is None:
        stage_values = list(_stage_latency_components(latency_payload).values())
        clean_stage_values = [float(value) for value in stage_values if value is not None]
        if len(clean_stage_values) >= 3:
            pcm_to_paint = _round(sum(clean_stage_values), 3)
    if pcm_to_paint is not None:
        status = "visual_late" if pcm_to_paint > 250 else "aligned"
        if pcm_to_paint < -50:
            status = "visual_early"
        confidence = "medium"
        recommended_offset, recommendation_basis = _offset_recommendation_for_confidence(
            pcm_to_paint,
            status=status,
            confidence=confidence,
            basis="stage_latency",
        )
        return {
            "perceptual_sync_status": status,
            "perceptual_sync_basis": "stage_latency_pcm_to_paint_estimated",
            "perceptual_sync_best_lag_ms": pcm_to_paint,
            "perceptual_sync_correlation": None,
            "direct_pcm_visual_correlation_usable": False,
            "sync_latency_basis": "stage_latency",
            "sync_latency_ms": pcm_to_paint,
            "direct_pcm_to_visual_correlation": None,
            "sync_confidence": confidence,
            "stage_latency_estimate_ms": pcm_to_paint,
            "sync_likely_cause": _sync_likely_cause(
                status=status,
                latency=latency_payload,
                direct_correlation_usable=False,
            ),
            "recommended_visual_offset_ms": recommended_offset,
            "visual_offset_applied_ms": 0,
            "visual_offset_recommendation_basis": recommendation_basis,
            "sync_diagnosis_reason": (
                "direct audible PCM to visual-drive correlation was too weak or "
                "sparse; using scalar stage timestamps from audible PCM to paint "
                "without applying or recommending an offset automatically"
            ),
            "raw_audio_present": False,
        }
    return {
        "perceptual_sync_status": "inconclusive",
        "perceptual_sync_basis": "",
        "perceptual_sync_best_lag_ms": None,
        "perceptual_sync_correlation": None,
        "direct_pcm_visual_correlation_usable": False,
        "sync_latency_basis": "",
        "sync_latency_ms": None,
        "direct_pcm_to_visual_correlation": None,
        "sync_confidence": "low",
        "stage_latency_estimate_ms": None,
        "sync_likely_cause": "insufficient_direct_and_stage_timing_evidence",
        "recommended_visual_offset_ms": None,
        "visual_offset_applied_ms": 0,
        "visual_offset_recommendation_basis": "none",
        "sync_diagnosis_reason": (
            "direct audible PCM to visual-drive correlation was weak and no usable "
            "audio-to-paint stage latency was available"
        ),
        "raw_audio_present": False,
    }


def _perceptual_sync_summary(
    alignment: Mapping[str, Any],
    latency: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return audio_visual_sync_diagnosis(alignment, latency)


def sanitize_scalar_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a JSON-safe scalar diagnostic payload with raw audio fields removed."""
    sanitized: dict[str, Any] = {}
    for key, value in dict(payload or {}).items():
        if _is_forbidden_raw_key(str(key)):
            continue
        if isinstance(value, bytes | bytearray | memoryview):
            continue
        if isinstance(value, Mapping):
            sanitized[str(key)] = sanitize_scalar_payload(value)
            continue
        if isinstance(value, SCALAR_TYPES):
            if isinstance(value, float):
                rounded = _round(value)
                sanitized[str(key)] = 0.0 if rounded is None else rounded
            else:
                sanitized[str(key)] = value
            continue
        # Avoid serializing arbitrary arrays; diagnostic timelines are emitted as
        # rows, not nested sample dumps.
    sanitized["raw_audio_present"] = False
    return sanitized


def speaking_lifetime_report(
    *,
    playback_start_ms: float | int | None,
    playback_end_ms: float | int | None,
    voice_visual_active_true_ms: float | int | None,
    voice_visual_active_false_ms: float | int | None,
    qml_speaking_true_ms: float | int | None,
    qml_speaking_false_ms: float | int | None,
    anchor_speaking_true_ms: float | int | None,
    anchor_speaking_false_ms: float | int | None,
) -> dict[str, float | None]:
    playback_start = _round(playback_start_ms, 3)
    playback_end = _round(playback_end_ms, 3)
    voice_true = _round(voice_visual_active_true_ms, 3)
    voice_false = _round(voice_visual_active_false_ms, 3)
    qml_true = _round(qml_speaking_true_ms, 3)
    qml_false = _round(qml_speaking_false_ms, 3)
    anchor_true = _round(anchor_speaking_true_ms, 3)
    anchor_false = _round(anchor_speaking_false_ms, 3)

    def delta(right: float | None, left: float | None) -> float | None:
        if right is None or left is None:
            return None
        return _round(right - left, 3)

    return {
        "audible_playback_start_time_ms": playback_start,
        "audible_playback_end_time_ms": playback_end,
        "voice_visual_active_first_true_time_ms": voice_true,
        "voice_visual_active_false_time_ms": voice_false,
        "qml_speaking_visual_first_true_time_ms": qml_true,
        "qml_speaking_visual_false_time_ms": qml_false,
        "anchor_speaking_visual_first_true_time_ms": anchor_true,
        "anchor_speaking_visual_false_time_ms": anchor_false,
        "speaking_visual_start_delay_ms": delta(voice_true, playback_start),
        "anchor_speaking_start_delay_ms": delta(anchor_true, playback_start),
        "speaking_visual_end_delay_ms": delta(voice_false, playback_end),
        "anchor_speaking_stuck_after_audio_ms": delta(anchor_false, playback_end),
        "anchor_release_tail_ms": delta(anchor_false, voice_false),
        "raw_audio_present": False,
    }


def classify_real_environment_chain(
    *,
    pcm_energy: Sequence[float],
    meter_energy: Sequence[float],
    payload_energy: Sequence[float],
    bridge_energy: Sequence[float],
    qml_energy: Sequence[float],
    final_energy: Sequence[float],
    paint_count: int | None = None,
    speaking_lifetime: Mapping[str, Any] | None = None,
    max_frame_gap_ms: float | None = None,
    render_metrics: Mapping[str, Any] | None = None,
    stimulus_valid: bool = True,
) -> list[str]:
    if not stimulus_valid:
        return ["live_audio_fixture_invalid"]
    if _varies(pcm_energy) and not _varies(meter_energy):
        return ["pcm_meter_flat"]
    if _varies(meter_energy) and not _varies(payload_energy):
        return ["meter_to_payload_broken"]
    if _varies(payload_energy) and not _varies(bridge_energy):
        return ["payload_to_bridge_broken"]
    if _varies(bridge_energy) and not _varies(qml_energy):
        return ["bridge_to_qml_broken"]
    if _varies(qml_energy) and not _varies(final_energy):
        return ["qml_to_anchor_mapping_broken"]
    if _varies(final_energy) and paint_count is not None and int(paint_count) <= 0:
        return ["anchor_paint_not_updating"]
    metrics = dict(render_metrics or {})
    anchor_paint_fps = _round(
        metrics.get("anchorPaintFpsDuringSpeaking") or metrics.get("anchorPaintFps")
    )
    dynamic_core_paint_fps = _round(
        metrics.get("dynamicCorePaintFpsDuringSpeaking")
        or metrics.get("dynamicCorePaintFps")
    )
    request_paint_fps = _round(
        metrics.get("anchorRequestPaintFpsDuringSpeaking")
        or metrics.get("anchorRequestPaintFps")
    )
    local_speaking_fps = _round(metrics.get("anchorLocalSpeakingFrameFps"))
    request_storm = bool(metrics.get("requestPaintStormDetected"))
    if (
        (
            (anchor_paint_fps is not None and anchor_paint_fps < 30.0)
            or (
                dynamic_core_paint_fps is not None
                and dynamic_core_paint_fps < 30.0
            )
        )
        and not request_storm
        and (
            (request_paint_fps is not None and request_paint_fps >= 30.0)
            or (local_speaking_fps is not None and local_speaking_fps >= 30.0)
        )
    ):
        return ["anchor_canvas_paint_path_render_backend_bottleneck"]
    frame_gap = _round(max_frame_gap_ms)
    if frame_gap is not None and frame_gap > 100.0:
        return ["render_cadence_problem"]
    shared_fps_min = _round(metrics.get("sharedAnimationClockFpsDuringSpeakingMin"))
    if anchor_paint_fps is not None and anchor_paint_fps < 30.0:
        return ["render_cadence_problem"]
    visible_qsg_paint_stable = (
        metrics.get("renderCadenceDuringSpeakingStable") is True
        and anchor_paint_fps is not None
        and anchor_paint_fps >= 30.0
        and dynamic_core_paint_fps is not None
        and dynamic_core_paint_fps >= 30.0
        and not bool(metrics.get("requestPaintStormDetected"))
    )
    if (
        shared_fps_min is not None
        and shared_fps_min < 30.0
        and not bool(metrics.get("sharedClockUnderTargetButAnchorLocalClockCompensated"))
        and not visible_qsg_paint_stable
    ):
        return ["render_cadence_problem"]
    lifetime = dict(speaking_lifetime or {})
    start_delay = _round(lifetime.get("anchor_speaking_start_delay_ms"))
    if start_delay is not None and start_delay > 250.0:
        return ["speaking_state_delayed"]
    stuck_delay = _round(lifetime.get("anchor_speaking_stuck_after_audio_ms"))
    if stuck_delay is not None and stuck_delay > 1000.0:
        return ["speaking_state_stale_after_playback"]
    return ["production_chain_pass"]


def _voice_ar3_after_snapshot(
    *,
    ranges: Mapping[str, Any],
    render_metrics: Mapping[str, Any],
    speaking_lifetime: Mapping[str, Any],
) -> dict[str, Any]:
    final_range = ranges.get("finalSpeakingEnergy", {})
    return sanitize_scalar_payload(
        {
            "source": "voice_ar3_live_current_probe",
            "anchorRequestPaintFps": render_metrics.get("anchorRequestPaintFps"),
            "anchorRequestPaintFpsDuringSpeaking": render_metrics.get(
                "anchorRequestPaintFpsDuringSpeaking"
            ),
            "anchorPaintFps": render_metrics.get("anchorPaintFps"),
            "anchorPaintFpsDuringSpeaking": render_metrics.get(
                "anchorPaintFpsDuringSpeaking"
            ),
            "anchorLocalSpeakingFrameFps": render_metrics.get(
                "anchorLocalSpeakingFrameFps"
            ),
            "dynamicCorePaintFps": render_metrics.get("dynamicCorePaintFps"),
            "dynamicCorePaintFpsDuringSpeaking": render_metrics.get(
                "dynamicCorePaintFpsDuringSpeaking"
            ),
            "staticFramePaintFpsDuringSpeaking": render_metrics.get(
                "staticFramePaintFpsDuringSpeaking"
            ),
            "sharedAnimationClockFpsDuringSpeakingMin": render_metrics.get(
                "sharedAnimationClockFpsDuringSpeakingMin"
            ),
            "sharedAnimationClockFpsDuringSpeakingMean": render_metrics.get(
                "sharedAnimationClockFpsDuringSpeakingMean"
            ),
            "finalSpeakingEnergyRange": final_range,
            "anchorSpeakingStartDelayMs": speaking_lifetime.get(
                "anchor_speaking_start_delay_ms"
            ),
            "anchorReleaseTailMs": speaking_lifetime.get("anchor_release_tail_ms"),
            "anchorSpeakingStuckAfterAudioMs": speaking_lifetime.get(
                "anchor_speaking_stuck_after_audio_ms"
            ),
            "maxFrameGapMsDuringSpeaking": render_metrics.get(
                "maxFrameGapMsDuringSpeaking"
            ),
            "qmlReceiveMaxGapMsDuringSpeaking": render_metrics.get(
                "qmlReceiveMaxGapMsDuringSpeaking"
            ),
            "fogTickFpsDuringSpeakingMean": render_metrics.get(
                "fogTickFpsDuringSpeakingMean"
            ),
            "requestPaintStormDetected": render_metrics.get(
                "requestPaintStormDetected"
            ),
            "renderCadenceDuringSpeakingStable": render_metrics.get(
                "renderCadenceDuringSpeakingStable"
            ),
            "raw_audio_present": False,
        }
    )


def real_environment_timeline_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    timeline_rows: list[dict[str, Any]] = []
    for row in rows:
        sanitized = sanitize_scalar_payload(row)
        timeline_rows.append(
            {
                field: (
                    str(sanitized.get(field, "")).lower()
                    if isinstance(sanitized.get(field), bool)
                    else sanitized.get(field, "")
                )
                for field in TIMELINE_FIELDNAMES
            }
        )
        timeline_rows[-1]["raw_audio_present"] = "false"
    return timeline_rows


def real_environment_timeline_csv_text(rows: Sequence[Mapping[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=TIMELINE_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for row in real_environment_timeline_rows(rows):
        writer.writerow(row)
    return output.getvalue()


def summarize_real_environment_chain(
    *,
    playback_id: str,
    spoken_stimulus_valid: bool,
    timeline_rows: Sequence[Mapping[str, Any]],
    process_state: Mapping[str, Any],
    speaking_lifetime: Mapping[str, Any] | None,
    paint_count: int | None = None,
    render_metrics: Mapping[str, Any] | None = None,
    runtime_identity: Mapping[str, Any] | None = None,
    spoken_stimulus: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [sanitize_scalar_payload(row) for row in timeline_rows]
    pcm = _series(rows, "pcm_energy")
    meter = _series(rows, "meter_energy")
    payload = _series(rows, "payload_energy")
    bridge = _series(rows, "bridge_energy")
    qml = _series(rows, "qml_received_energy")
    final = _series(rows, "finalSpeakingEnergy")
    blob_scale = _series(rows, "blobScaleDrive")
    blob_deformation = _series(rows, "blobDeformationDrive")
    blob_radius = _series(rows, "blobRadiusScale")
    radiance = _series(rows, "radianceDrive")
    ring = _series(rows, "ringDrive")
    ranges = {
        "pcm_submit": _range(pcm),
        "backend_meter": _range(meter),
        "voice_payload": _range(payload),
        "ui_bridge": _range(bridge),
        "qml_received": _range(qml),
        "finalSpeakingEnergy": _range(final),
        "blobScaleDrive": _range(blob_scale),
        "blobDeformationDrive": _range(blob_deformation),
        "blobRadiusScale": _range(blob_radius),
        "radianceDrive": _range(radiance),
        "ringDrive": _range(ring),
    }
    max_frame_gap = _round(
        (render_metrics or {}).get("maxFrameGapMs")
        or (render_metrics or {}).get("max_frame_gap_ms")
        or _first_gap_ms(rows, "anchor_paint_time")
    )
    lifetime = sanitize_scalar_payload(dict(speaking_lifetime or {}))
    render_metrics_sanitized = sanitize_scalar_payload(render_metrics or {})
    classification = classify_real_environment_chain(
        pcm_energy=pcm,
        meter_energy=meter,
        payload_energy=payload,
        bridge_energy=bridge,
        qml_energy=qml,
        final_energy=final,
        paint_count=paint_count,
        speaking_lifetime=lifetime,
        max_frame_gap_ms=max_frame_gap,
        render_metrics=render_metrics_sanitized,
        stimulus_valid=spoken_stimulus_valid,
    )
    before_after = sanitize_scalar_payload(
        {
            "before_voice_ar1_live": VOICE_AR1_LIVE_RENDER_BASELINE,
            "before_voice_ar2_live": VOICE_AR2_LIVE_RENDER_BASELINE,
            "after_voice_ar3_live": _voice_ar3_after_snapshot(
                ranges=ranges,
                render_metrics=render_metrics_sanitized,
                speaking_lifetime=lifetime,
            ),
            "after_voice_ar5_live": _voice_ar3_after_snapshot(
                ranges=ranges,
                render_metrics=render_metrics_sanitized,
                speaking_lifetime=lifetime,
            ),
            "raw_audio_present": False,
        }
    )
    alignment_values: dict[str, Any] = {
        "pcm_to_meter": _lagged_correlation(rows, "pcm_energy", "meter_energy"),
        "meter_to_qml_received": _lagged_correlation(
            rows, "meter_energy", "qml_received_energy"
        ),
        "qml_received_to_finalSpeakingEnergy": _lagged_correlation(
            rows, "qml_received_energy", "finalSpeakingEnergy"
        ),
        "finalSpeakingEnergy_to_blobScaleDrive": _lagged_correlation(
            rows, "finalSpeakingEnergy", "blobScaleDrive"
        ),
        "finalSpeakingEnergy_to_blobDeformationDrive": _lagged_correlation(
            rows, "finalSpeakingEnergy", "blobDeformationDrive"
        ),
        "finalSpeakingEnergy_to_radianceDrive": _lagged_correlation(
            rows, "finalSpeakingEnergy", "radianceDrive"
        ),
        "pcm_to_finalSpeakingEnergy": _lagged_correlation(
            rows, "pcm_energy", "finalSpeakingEnergy"
        ),
        "pcm_to_blobScaleDrive": _lagged_correlation(
            rows, "pcm_energy", "blobScaleDrive"
        ),
        "visualAmplitudeLatencyMsMean": _mean_or_none(
            _series(rows, "visualAmplitudeLatencyMs")
        ),
        "raw_audio_present": False,
    }
    latency_values = {
        "pcm_to_meter": _mean_delta_ms(rows, "pcm_submit_wall_time_ms", "meter_wall_time_ms"),
        "meter_to_payload": _mean_delta_ms(rows, "meter_wall_time_ms", "payload_wall_time_ms"),
        "payload_to_bridge": _mean_delta_ms(rows, "payload_wall_time_ms", "bridge_receive_time_ms"),
        "bridge_to_qml": _mean_delta_ms(rows, "bridge_receive_time_ms", "qml_receive_time_ms"),
        "qml_to_finalSpeakingEnergy": _mean_delta_ms(
            rows, "qml_receive_time_ms", "finalSpeakingEnergyUpdatedAtMs"
        ),
        "finalSpeakingEnergy_to_paint": _mean_delta_ms(
            rows, "finalSpeakingEnergyUpdatedAtMs", "anchor_paint_time"
        ),
    }
    alignment_values.update(_perceptual_sync_summary(alignment_values, latency_values))
    alignment = sanitize_scalar_payload(alignment_values)
    sync_timeline_stages = sanitize_scalar_payload(
        {
            "actual_audio_output_timeline": "pcm_audible_wall_time_ms + pcm_energy",
            "pcm_meter_timeline": "meter_wall_time_ms + meter_energy",
            "authoritative_ar6_timeline": (
                "authoritativeVoiceVisualEnergy + authoritativeVoiceVisualActive"
            ),
            "qml_anchor_timeline": (
                "qml_receive_time_ms + qml_received_energy + finalSpeakingEnergy"
            ),
            "render_paint_timeline": "anchor_paint_time + frame_gap_ms",
            "direct_correlation_reliable": alignment.get(
                "direct_pcm_visual_correlation_usable"
            ),
            "stage_latency_basis": alignment.get("sync_latency_basis"),
            "raw_audio_present": False,
        }
    )
    speaking_state_stability = sanitize_scalar_payload(_speaking_state_stability(rows))
    recommendation = ""
    if "anchor_canvas_paint_path_render_backend_bottleneck" in classification:
        recommendation = (
            "Anchor Canvas paint path/render backend bottleneck: FBO/threaded Canvas "
            "is receiving >=30 Hz local/requested frames but onPaint remains below "
            "30 Hz. Reduce Canvas draw complexity or move the anchor drawing to "
            "QML Shape, ShaderEffect, or a custom QQuickItem instead of Canvas."
        )
    return {
        "probe": "voice_ar5_real_environment",
        "chain_version": "Voice-AR5",
        "playback_id": playback_id,
        "source": PCM_STREAM_SOURCE,
        "spoken_stimulus": sanitize_scalar_payload(spoken_stimulus or {}),
        "spoken_stimulus_valid": bool(spoken_stimulus_valid),
        "runtime_identity": sanitize_scalar_payload(runtime_identity or {}),
        "process_state": sanitize_scalar_payload(process_state),
        "privacy": {
            "raw_audio_present": False,
            "raw_audio_logged": False,
            "raw_audio_exposed": False,
            "scalar_only": True,
        },
        "ranges": ranges,
        "correlations": {
            "pcm_to_meter": _round(correlation(pcm, meter)),
            "meter_to_payload": _round(correlation(meter, payload)),
            "payload_to_bridge": _round(correlation(payload, bridge)),
            "bridge_to_qml": _round(correlation(bridge, qml)),
            "qml_to_finalSpeakingEnergy": _round(correlation(qml, final)),
            "audioVisualAmplitudeCorrelation": _round(correlation(qml, blob_scale)),
            "blobDriveCorrelationToVoiceEnergy": _round(correlation(qml, blob_scale)),
            "finalEnergyCorrelationToVoiceEnergy": _round(correlation(qml, final)),
            "finalSpeakingEnergy_to_blobScaleDrive": _round(
                correlation(final, blob_scale)
            ),
            "finalSpeakingEnergy_to_blobDeformationDrive": _round(
                correlation(final, blob_deformation)
            ),
            "finalSpeakingEnergy_to_radianceDrive": _round(
                correlation(final, radiance)
            ),
        },
        "latency_ms": latency_values,
        "audio_visual_alignment": alignment,
        "audio_visual_sync_stages": sync_timeline_stages,
        "speaking_lifetime": lifetime,
        "speaking_state_stability": speaking_state_stability,
        "render_metrics": render_metrics_sanitized,
        "voice_ar3_before_after": before_after,
        "voice_ar4_before_after": before_after,
        "voice_ar5_before_after": before_after,
        "recommendation": recommendation,
        "classification": classification,
        "timeline_sample_count": len(rows),
        "raw_audio_present": False,
    }


def real_environment_report_markdown(report: Mapping[str, Any]) -> str:
    classifications = ", ".join(report.get("classification", []))
    ranges = report.get("ranges", {}) if isinstance(report.get("ranges"), Mapping) else {}
    correlations = (
        report.get("correlations", {})
        if isinstance(report.get("correlations"), Mapping)
        else {}
    )
    latency = report.get("latency_ms", {}) if isinstance(report.get("latency_ms"), Mapping) else {}
    lifetime = (
        report.get("speaking_lifetime", {})
        if isinstance(report.get("speaking_lifetime"), Mapping)
        else {}
    )
    render_metrics = (
        report.get("render_metrics", {})
        if isinstance(report.get("render_metrics"), Mapping)
        else {}
    )
    before_after_payload = report.get(
        "voice_ar5_before_after",
        report.get("voice_ar3_before_after", report.get("voice_ar2_before_after", {})),
    )
    before_after = before_after_payload if isinstance(before_after_payload, Mapping) else {}
    alignment = (
        report.get("audio_visual_alignment", {})
        if isinstance(report.get("audio_visual_alignment"), Mapping)
        else {}
    )
    sync_stages = (
        report.get("audio_visual_sync_stages", {})
        if isinstance(report.get("audio_visual_sync_stages"), Mapping)
        else {}
    )
    speaking_state_stability = (
        report.get("speaking_state_stability", {})
        if isinstance(report.get("speaking_state_stability"), Mapping)
        else {}
    )
    lines = [
        "# Voice-AR5 Real Environment Chain Report",
        "",
        f"- Playback ID: `{report.get('playback_id', '')}`",
        f"- Source: `{report.get('source', PCM_STREAM_SOURCE)}`",
        f"- Spoken stimulus valid: `{str(report.get('spoken_stimulus_valid', False)).lower()}`",
        f"- Classification: `{classifications}`",
        "- Privacy: scalar-only, raw_audio_present=false",
        "",
        "## Energy Ranges",
    ]
    for name, stage in ranges.items():
        if not isinstance(stage, Mapping):
            continue
        lines.append(
            f"- {name}: min={stage.get('min')}, max={stage.get('max')}, "
            f"span={stage.get('span')}, count={stage.get('count')}"
        )
    lines.extend(["", "## Correlations"])
    for key, value in correlations.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Audio/Visual Alignment"])
    for key in [
        "pcm_to_meter",
        "meter_to_qml_received",
        "qml_received_to_finalSpeakingEnergy",
        "finalSpeakingEnergy_to_blobScaleDrive",
        "finalSpeakingEnergy_to_blobDeformationDrive",
        "finalSpeakingEnergy_to_radianceDrive",
        "pcm_to_finalSpeakingEnergy",
        "pcm_to_blobScaleDrive",
    ]:
        stage = alignment.get(key, {})
        if not isinstance(stage, Mapping):
            continue
        lines.append(
            f"- {key}: best_lag_ms={stage.get('best_lag_ms')}, "
            f"correlation={stage.get('correlation')}, "
            f"samples={stage.get('sample_count')}"
        )
    lines.append(
        f"- visualAmplitudeLatencyMsMean: {alignment.get('visualAmplitudeLatencyMsMean')}"
    )
    lines.append(f"- perceptual_sync_status: {alignment.get('perceptual_sync_status')}")
    lines.append(
        "- perceptual_sync_basis: "
        f"{alignment.get('perceptual_sync_basis')}, "
        f"best_lag_ms={alignment.get('perceptual_sync_best_lag_ms')}, "
        f"correlation={alignment.get('perceptual_sync_correlation')}"
    )
    lines.append(
        "- sync_latency_basis: "
        f"{alignment.get('sync_latency_basis')}, "
        f"sync_latency_ms={alignment.get('sync_latency_ms')}, "
        f"direct_pcm_visual_correlation_usable="
        f"{alignment.get('direct_pcm_visual_correlation_usable')}"
    )
    lines.append(
        f"- sync_diagnosis_reason: {alignment.get('sync_diagnosis_reason')}"
    )
    lines.append(f"- sync_likely_cause: {alignment.get('sync_likely_cause')}")
    lines.append(
        "- recommended_visual_offset_ms: "
        f"{alignment.get('recommended_visual_offset_ms')} "
        f"(applied={alignment.get('visual_offset_applied_ms')}, "
        f"basis={alignment.get('visual_offset_recommendation_basis')})"
    )
    if sync_stages:
        lines.extend(["", "## Sync Timeline Stages"])
        for key in [
            "actual_audio_output_timeline",
            "pcm_meter_timeline",
            "authoritative_ar6_timeline",
            "qml_anchor_timeline",
            "render_paint_timeline",
            "direct_correlation_reliable",
            "stage_latency_basis",
        ]:
            lines.append(f"- {key}: {sync_stages.get(key)}")
    lines.extend(["", "## Latency"])
    for key, value in latency.items():
        if key == "raw_audio_present":
            continue
        lines.append(f"- {key}: {value} ms")
    lines.extend(["", "## Speaking Lifetime"])
    for key in [
        "speaking_visual_start_delay_ms",
        "anchor_speaking_start_delay_ms",
        "speaking_visual_end_delay_ms",
        "anchor_speaking_stuck_after_audio_ms",
        "anchor_release_tail_ms",
    ]:
        lines.append(f"- {key}: {lifetime.get(key)} ms")
    lines.extend(["", "## Speaking State Stability"])
    for key in [
        "voiceVisualActiveRows",
        "speakingVisualTrueRows",
        "speakingVisualFalseWhileVoiceVisualActiveRows",
        "anchorIdleWhileVoiceVisualActiveRows",
        "midSpeechSpeakingVisualFalseRows",
        "midSpeechAnchorIdleRows",
        "anchorStatusGlitchDetected",
    ]:
        lines.append(f"- {key}: {speaking_state_stability.get(key)}")
    lines.extend(["", "## Render Cadence"])
    lines.append(f"- effectiveAnchorRenderer: {render_metrics.get('effectiveAnchorRenderer')}")
    for key in [
        "anchorRequestPaintFpsDuringSpeaking",
        "anchorPaintFpsDuringSpeaking",
        "dynamicCorePaintFpsDuringSpeaking",
        "anchorLocalSpeakingFrameFps",
        "sharedAnimationClockFpsDuringSpeakingMin",
        "maxFrameGapMsDuringSpeaking",
        "fogTickFpsDuringSpeakingMean",
        "requestPaintStormDetected",
        "renderCadenceDuringSpeakingStable",
        "sharedClockUnderTargetButAnchorLocalClockCompensated",
    ]:
        lines.append(f"- {key}: {render_metrics.get(key)}")
    if before_after:
        before = before_after.get("before_voice_ar2_live", before_after.get("before_voice_ar1_live", {}))
        after = before_after.get(
            "after_voice_ar5_live",
            before_after.get("after_voice_ar3_live", before_after.get("after_voice_ar2_live", {})),
        )
        if isinstance(before, Mapping) and isinstance(after, Mapping):
            lines.extend(["", "## Voice-AR3/AR4/AR5 Before/After"])
            for key in [
                "anchorRequestPaintFpsDuringSpeaking",
                "anchorPaintFpsDuringSpeaking",
                "dynamicCorePaintFpsDuringSpeaking",
                "anchorLocalSpeakingFrameFps",
                "sharedAnimationClockFpsDuringSpeakingMin",
                "anchorSpeakingStartDelayMs",
                "anchorReleaseTailMs",
                "maxFrameGapMsDuringSpeaking",
                "fogTickFpsDuringSpeakingMean",
            ]:
                lines.append(f"- {key}: before={before.get(key)}, after={after.get(key)}")
            lines.append(
                "- finalSpeakingEnergyRange: "
                f"before={before.get('finalSpeakingEnergyRange')}, "
                f"after={after.get('finalSpeakingEnergyRange')}"
            )
    recommendation = str(report.get("recommendation") or "")
    if recommendation:
        lines.extend(["", "## Recommendation", recommendation])
    lines.extend(
        [
            "",
            "## Classification Guide",
            "- `pcm_meter_flat`: PCM energy varied before playback, but the meter did not.",
            "- `meter_to_payload_broken`: meter varied, but voice/status payload stayed flat.",
            "- `payload_to_bridge_broken`: payload varied, but the UI bridge model stayed flat.",
            "- `bridge_to_qml_broken`: bridge varied, but production QML received stale/flat values.",
            "- `qml_to_anchor_mapping_broken`: QML received varied, but finalSpeakingEnergy stayed flat.",
            "- `anchor_paint_not_updating`: finalSpeakingEnergy varied, but anchor paint/frame evidence was missing.",
            "- `anchor_canvas_paint_path_render_backend_bottleneck`: local/requested frames are healthy, but Canvas onPaint remains below 30 Hz.",
            "- `production_chain_pass`: scalar energy survived the observed live production chain.",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "RAW_AUDIO_KEY_TOKENS",
    "classify_real_environment_chain",
    "real_environment_report_markdown",
    "real_environment_timeline_csv_text",
    "real_environment_timeline_rows",
    "sanitize_scalar_payload",
    "speaking_lifetime_report",
    "summarize_real_environment_chain",
]
