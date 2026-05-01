from __future__ import annotations

import re
from typing import Any

from stormhelm.core.camera_awareness.models import (
    CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
    CameraCaptureGuidanceResult,
    CameraCaptureGuidanceStatus,
    CameraCaptureQualityIssue,
    CameraCaptureQualityIssueKind,
    CameraCaptureQualitySeverity,
    CameraComparisonResult,
    CameraConfidenceLevel,
    CameraEngineeringHelperResult,
    CameraFrameArtifact,
    CameraStorageMode,
    CameraVisionAnswer,
)


_ISSUE_ALIASES: tuple[tuple[CameraCaptureQualityIssueKind, tuple[str, ...]], ...] = (
    (CameraCaptureQualityIssueKind.COMPARISON_ANGLE_MISMATCH, ("comparison_angle_mismatch", "different angle", "same angle", "not aligned")),
    (CameraCaptureQualityIssueKind.COMPARISON_LIGHTING_MISMATCH, ("comparison_lighting_mismatch", "lighting differs", "different lighting", "match lighting")),
    (CameraCaptureQualityIssueKind.COMPARISON_SCALE_MISMATCH, ("comparison_scale_mismatch", "different scale", "scale mismatch", "same distance")),
    (CameraCaptureQualityIssueKind.MOTION_BLUR, ("motion_blur", "motion blur")),
    (CameraCaptureQualityIssueKind.TEXT_BLURRY, ("text_blurry", "blurry text", "label blurry", "marking blurry", "unreadable text")),
    (CameraCaptureQualityIssueKind.BLUR, ("blur", "blurry", "out of focus", "soft focus", "focus")),
    (CameraCaptureQualityIssueKind.LOW_LIGHT, ("low_light", "low light", "too dark", "dim lighting", "dark")),
    (CameraCaptureQualityIssueKind.GLARE, ("glare", "reflection", "shiny", "specular")),
    (CameraCaptureQualityIssueKind.OVEREXPOSED, ("overexposed", "washed out")),
    (CameraCaptureQualityIssueKind.UNDEREXPOSED, ("underexposed",)),
    (CameraCaptureQualityIssueKind.OBJECT_OUT_OF_FRAME, ("object_out_of_frame", "out of frame", "cropped", "partly cut off")),
    (CameraCaptureQualityIssueKind.OBJECT_TOO_SMALL, ("object_too_small", "too far", "object small")),
    (CameraCaptureQualityIssueKind.OBJECT_TOO_CLOSE, ("object_too_close", "too close")),
    (CameraCaptureQualityIssueKind.TEXT_TOO_SMALL, ("text_too_small", "label too small", "marking too small", "text small")),
    (CameraCaptureQualityIssueKind.LABEL_NOT_CENTERED, ("label_not_centered", "label off center", "not centered")),
    (CameraCaptureQualityIssueKind.ANGLE_TOO_OBLIQUE, ("angle_too_oblique", "oblique", "angled", "not straight on", "perspective")),
    (CameraCaptureQualityIssueKind.MISSING_SCALE_REFERENCE, ("missing_scale_reference", "no scale", "scale reference", "ruler")),
    (CameraCaptureQualityIssueKind.MISSING_CONTEXT, ("missing_context", "needs context", "wider shot", "wide context")),
    (CameraCaptureQualityIssueKind.MISSING_CLOSEUP, ("missing_closeup", "needs close", "close-up", "closeup")),
    (CameraCaptureQualityIssueKind.OCCLUDED, ("occluded", "blocked", "hidden", "covered")),
    (CameraCaptureQualityIssueKind.WRONG_SIDE, ("wrong_side", "other side", "back side", "front side", "solder side")),
)


_ISSUE_GUIDANCE: dict[CameraCaptureQualityIssueKind, str] = {
    CameraCaptureQualityIssueKind.BLUR: "Hold still and retake with the target centered.",
    CameraCaptureQualityIssueKind.MOTION_BLUR: "Hold still and brace the object before taking the next still.",
    CameraCaptureQualityIssueKind.TEXT_BLURRY: "Hold still and retake with the label centered.",
    CameraCaptureQualityIssueKind.LOW_LIGHT: "Add more light or move closer to a light source before the next still.",
    CameraCaptureQualityIssueKind.GLARE: "Reduce glare by shifting the light to the side or tilting the object slightly.",
    CameraCaptureQualityIssueKind.OVEREXPOSED: "Reduce direct light so bright areas are not washed out.",
    CameraCaptureQualityIssueKind.UNDEREXPOSED: "Improve lighting so the object is not underexposed.",
    CameraCaptureQualityIssueKind.OBJECT_OUT_OF_FRAME: "Center the object and include the whole part in frame.",
    CameraCaptureQualityIssueKind.OBJECT_TOO_SMALL: "Move closer or capture a close-up of the relevant area.",
    CameraCaptureQualityIssueKind.OBJECT_TOO_CLOSE: "Move farther back so the whole relevant area is in frame.",
    CameraCaptureQualityIssueKind.TEXT_TOO_SMALL: "Move closer or capture a close-up around the label.",
    CameraCaptureQualityIssueKind.LABEL_NOT_CENTERED: "Center the object or label before retaking.",
    CameraCaptureQualityIssueKind.ANGLE_TOO_OBLIQUE: "Retake straight-on so the surface is flatter to the camera.",
    CameraCaptureQualityIssueKind.MISSING_SCALE_REFERENCE: "Include a ruler or scale reference beside the part.",
    CameraCaptureQualityIssueKind.MISSING_CONTEXT: "Capture a wider context shot so the surrounding object is visible.",
    CameraCaptureQualityIssueKind.MISSING_CLOSEUP: "Capture a close-up of the label or area of interest.",
    CameraCaptureQualityIssueKind.OCCLUDED: "Move anything blocking the view before retaking.",
    CameraCaptureQualityIssueKind.WRONG_SIDE: "Capture the other side as a separate explicit still.",
    CameraCaptureQualityIssueKind.COMPARISON_ANGLE_MISMATCH: "Retake from the same angle as the matching comparison still.",
    CameraCaptureQualityIssueKind.COMPARISON_LIGHTING_MISMATCH: "Match lighting between the stills before comparing.",
    CameraCaptureQualityIssueKind.COMPARISON_SCALE_MISMATCH: "Use a similar distance and scale for each comparison still.",
    CameraCaptureQualityIssueKind.UNSUPPORTED_QUALITY_ASSESSMENT: "Capture a clearer, better-lit still before relying on the result.",
}


_SEVERITY_RANK = {
    CameraCaptureQualitySeverity.INFO: 0,
    CameraCaptureQualitySeverity.LOW: 1,
    CameraCaptureQualitySeverity.MEDIUM: 2,
    CameraCaptureQualitySeverity.HIGH: 3,
}


def build_quality_issues_from_signals(
    *,
    artifact: CameraFrameArtifact | None = None,
    vision_answer: CameraVisionAnswer | None = None,
    helper_result: CameraEngineeringHelperResult | None = None,
    comparison_result: CameraComparisonResult | None = None,
    helper_family: str | None = None,
) -> list[CameraCaptureQualityIssue]:
    artifact_id = (
        artifact.image_artifact_id
        if artifact is not None
        else vision_answer.image_artifact_id
        if vision_answer is not None
        else comparison_result.artifact_summaries[0].artifact_id
        if comparison_result is not None and comparison_result.artifact_summaries
        else None
    )
    resolved_helper = helper_family or (
        helper_result.helper_family.value if helper_result is not None else None
    ) or (
        comparison_result.helper_family if comparison_result is not None else None
    )
    signals: list[tuple[str, str]] = []
    if artifact is not None:
        signals.extend(("artifact_warning", item) for item in artifact.quality_warnings)
        signals.append(("artifact_fixture", artifact.fixture_name))
    if vision_answer is not None:
        signals.extend(("vision_uncertainty", item) for item in vision_answer.uncertainty_reasons)
        if vision_answer.suggested_next_capture:
            signals.append(("vision_suggested_next_capture", vision_answer.suggested_next_capture))
        if vision_answer.evidence_summary:
            signals.append(("vision_evidence", vision_answer.evidence_summary))
    if helper_result is not None:
        signals.extend(("helper_uncertainty", item) for item in helper_result.uncertainty_reasons)
        signals.extend(("helper_caveat", item) for item in helper_result.caveats)
        if helper_result.suggested_next_capture:
            signals.append(("helper_suggested_next_capture", helper_result.suggested_next_capture))
    if comparison_result is not None:
        signals.extend(("comparison_uncertainty", item) for item in comparison_result.uncertainty_reasons)
        signals.extend(("comparison_difference", item) for item in comparison_result.differences)
        if comparison_result.suggested_next_capture:
            signals.append(("comparison_suggested_next_capture", comparison_result.suggested_next_capture))

    issues: list[CameraCaptureQualityIssue] = []
    seen: set[CameraCaptureQualityIssueKind] = set()
    for source, signal in signals:
        kind = classify_quality_issue_signal(signal)
        if kind is None or kind in seen:
            continue
        seen.add(kind)
        issues.append(
            CameraCaptureQualityIssue(
                issue_kind=kind,
                artifact_id=artifact_id,
                severity=_severity_for_issue(kind),
                confidence_kind=CameraConfidenceLevel.MEDIUM,
                evidence=f"{source}: {_safe_text(signal)}",
                helper_family=resolved_helper,
            )
        )
    return issues


def classify_quality_issue_signal(signal: Any) -> CameraCaptureQualityIssueKind | None:
    text = _normalize(signal)
    if not text:
        return None
    for kind, aliases in _ISSUE_ALIASES:
        if any(alias in text for alias in aliases):
            return kind
    return None


def build_guidance_result(
    *,
    artifact_id: str | None,
    issues: list[CameraCaptureQualityIssue],
    source_provenance: str,
    storage_mode: CameraStorageMode | str,
    helper_family: str | None = None,
    multi_capture_session_id: str | None = None,
    comparison_request_id: str | None = None,
    suggested_capture_label: str | None = None,
    title: str | None = None,
    concise_guidance: str | None = None,
) -> CameraCaptureGuidanceResult:
    instructions = _guidance_instructions(issues, helper_family=helper_family)
    if concise_guidance:
        concise = concise_guidance
    elif instructions:
        concise = " ".join(instructions[:2])
    else:
        concise = "I do not have enough information to recommend a specific retake. A closer, better-lit image is the safest next step."
    detailed = " ".join(instructions) if instructions else concise
    suggested = _suggested_next_capture(
        issues,
        instructions=instructions,
        suggested_capture_label=suggested_capture_label,
    )
    return CameraCaptureGuidanceResult(
        status=CameraCaptureGuidanceStatus.GUIDANCE_READY if issues else CameraCaptureGuidanceStatus.INSUFFICIENT_EVIDENCE,
        title=title or ("Retake Recommended" if issues else "Capture Guidance Limited"),
        concise_guidance=concise,
        detailed_guidance=detailed,
        artifact_id=artifact_id,
        multi_capture_session_id=multi_capture_session_id,
        comparison_request_id=comparison_request_id,
        helper_family=helper_family,
        quality_issues=list(issues),
        suggested_next_capture=suggested,
        suggested_capture_label=suggested_capture_label,
        suggested_user_actions=["retake_explicitly"] if issues else [],
        confidence_kind=_confidence_for_issues(issues),
        source_provenance=source_provenance or CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
        storage_mode=CameraStorageMode(storage_mode),
        error_code=None if issues else "capture_guidance_no_quality_signal",
    )


def blocked_guidance_result(
    *,
    error_code: str,
    artifact_id: str | None = None,
    multi_capture_session_id: str | None = None,
    comparison_request_id: str | None = None,
    helper_family: str | None = None,
    source_provenance: str = CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
    storage_mode: CameraStorageMode | str = CameraStorageMode.EPHEMERAL,
) -> CameraCaptureGuidanceResult:
    return CameraCaptureGuidanceResult(
        status=CameraCaptureGuidanceStatus.BLOCKED,
        title="Capture Guidance Blocked",
        concise_guidance=_blocked_message(error_code),
        detailed_guidance=_blocked_message(error_code),
        artifact_id=artifact_id,
        multi_capture_session_id=multi_capture_session_id,
        comparison_request_id=comparison_request_id,
        helper_family=helper_family,
        quality_issues=[],
        suggested_user_actions=[],
        confidence_kind=CameraConfidenceLevel.INSUFFICIENT,
        source_provenance=source_provenance,
        storage_mode=storage_mode,
        error_code=error_code,
    )


def next_slot_guidance_result(
    *,
    multi_capture_session_id: str,
    slot_id: str,
    slot_label: str,
    comparison_mode: str,
    helper_family: str | None = None,
) -> CameraCaptureGuidanceResult:
    label = _safe_text(slot_label or slot_id).lower()
    issue = CameraCaptureQualityIssue(
        issue_kind=_session_issue_for_slot(slot_id, comparison_mode),
        severity=CameraCaptureQualitySeverity.INFO,
        confidence_kind=CameraConfidenceLevel.HIGH,
        evidence=f"session_slot_pending: {slot_id}",
        helper_family=helper_family,
    )
    if slot_id in {"front", "back"}:
        concise = f"Capture the {label} side next. Take one explicit still; no automatic capture is running."
    elif slot_id in {"before", "after"}:
        concise = f"Capture the {label} still next from a consistent angle."
    elif slot_id in {"close_up", "closeup", "detail"}:
        concise = "Capture a close-up of the area of interest next."
    elif slot_id in {"context", "wide"}:
        concise = "Capture a wider context shot next."
    else:
        concise = f"Capture the {label} still next."
    return CameraCaptureGuidanceResult(
        status=CameraCaptureGuidanceStatus.GUIDANCE_READY,
        title="Capture Next Still",
        concise_guidance=concise,
        detailed_guidance=concise,
        multi_capture_session_id=multi_capture_session_id,
        helper_family=helper_family,
        quality_issues=[issue],
        suggested_next_capture=concise,
        suggested_capture_label=slot_id,
        suggested_user_actions=["capture_slot_explicitly"],
        confidence_kind=CameraConfidenceLevel.HIGH,
        source_provenance="camera_session",
        storage_mode=CameraStorageMode.EPHEMERAL,
    )


def severity_max(issues: list[CameraCaptureQualityIssue]) -> str:
    if not issues:
        return CameraCaptureQualitySeverity.INFO.value
    severity = max((issue.severity for issue in issues), key=lambda item: _SEVERITY_RANK[item])
    return severity.value


def issue_kinds(issues: list[CameraCaptureQualityIssue]) -> list[str]:
    return [issue.issue_kind.value for issue in issues]


def _guidance_instructions(
    issues: list[CameraCaptureQualityIssue],
    *,
    helper_family: str | None,
) -> list[str]:
    instructions: list[str] = []
    helper_instruction = _helper_specific_instruction(issues, helper_family)
    if helper_instruction:
        instructions.append(helper_instruction)
    for issue in issues:
        instruction = _ISSUE_GUIDANCE.get(issue.issue_kind)
        if instruction:
            instructions.append(instruction)
    return _unique(instructions)


def _helper_specific_instruction(
    issues: list[CameraCaptureQualityIssue],
    helper_family: str | None,
) -> str:
    family = _safe_text(helper_family).lower()
    kinds = {issue.issue_kind for issue in issues}
    if family == "engineering.resistor_color_bands":
        return "Retake closer with the resistor horizontal and the bands centered. Use side lighting to reduce glare."
    if family == "engineering.connector_identification":
        return "Place a ruler beside the connector or a known-size part for scale."
    if family in {"engineering.component_marking", "engineering.label_reading"}:
        return "Retake closer with the marking flat to the camera and light angled from the side."
    if family == "engineering.solder_joint_inspection":
        return "Retake straight-on with the joint centered. Use diffuse light so the solder surface is visible without glare."
    if family == "engineering.pcb_visual_inspection" and CameraCaptureQualityIssueKind.WRONG_SIDE in kinds:
        return "Capture the other side of the board as a separate explicit still."
    return ""


def _suggested_next_capture(
    issues: list[CameraCaptureQualityIssue],
    *,
    instructions: list[str],
    suggested_capture_label: str | None,
) -> str | None:
    if suggested_capture_label:
        return f"Capture {suggested_capture_label} explicitly."
    if not instructions:
        return None
    return instructions[0]


def _session_issue_for_slot(slot_id: str, comparison_mode: str) -> CameraCaptureQualityIssueKind:
    slot = _normalize(slot_id)
    mode = _normalize(comparison_mode)
    if slot in {"front", "back"}:
        return CameraCaptureQualityIssueKind.WRONG_SIDE
    if slot in {"close_up", "closeup", "detail"}:
        return CameraCaptureQualityIssueKind.MISSING_CLOSEUP
    if slot in {"context", "wide"}:
        return CameraCaptureQualityIssueKind.MISSING_CONTEXT
    if mode == "before_after":
        return CameraCaptureQualityIssueKind.COMPARISON_ANGLE_MISMATCH
    return CameraCaptureQualityIssueKind.MISSING_CONTEXT


def _severity_for_issue(kind: CameraCaptureQualityIssueKind) -> CameraCaptureQualitySeverity:
    if kind in {
        CameraCaptureQualityIssueKind.BLUR,
        CameraCaptureQualityIssueKind.MOTION_BLUR,
        CameraCaptureQualityIssueKind.TEXT_BLURRY,
        CameraCaptureQualityIssueKind.OBJECT_OUT_OF_FRAME,
        CameraCaptureQualityIssueKind.COMPARISON_ANGLE_MISMATCH,
    }:
        return CameraCaptureQualitySeverity.HIGH
    if kind in {
        CameraCaptureQualityIssueKind.LOW_LIGHT,
        CameraCaptureQualityIssueKind.GLARE,
        CameraCaptureQualityIssueKind.TEXT_TOO_SMALL,
        CameraCaptureQualityIssueKind.ANGLE_TOO_OBLIQUE,
        CameraCaptureQualityIssueKind.MISSING_SCALE_REFERENCE,
        CameraCaptureQualityIssueKind.COMPARISON_LIGHTING_MISMATCH,
        CameraCaptureQualityIssueKind.COMPARISON_SCALE_MISMATCH,
    }:
        return CameraCaptureQualitySeverity.MEDIUM
    return CameraCaptureQualitySeverity.LOW


def _confidence_for_issues(issues: list[CameraCaptureQualityIssue]) -> CameraConfidenceLevel:
    if not issues:
        return CameraConfidenceLevel.INSUFFICIENT
    if any(issue.severity == CameraCaptureQualitySeverity.HIGH for issue in issues):
        return CameraConfidenceLevel.MEDIUM
    return CameraConfidenceLevel.HIGH


def _blocked_message(error_code: str) -> str:
    messages = {
        "capture_guidance_artifact_missing": "I need a current camera still before I can suggest a retake.",
        "capture_guidance_artifact_expired": "That image has expired, so I cannot evaluate its capture quality anymore.",
        "capture_guidance_session_expired": "That multi-capture session has expired. Fresh stills are needed before guidance can continue.",
        "capture_guidance_no_artifact": "I need a camera still first before I can suggest a retake.",
        "capture_guidance_blocked_by_policy": "Capture guidance is blocked by policy before any retake suggestion.",
    }
    return messages.get(error_code, "Capture guidance is blocked before any camera or provider action.")


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        text = _safe_text(item)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


def _normalize(value: Any) -> str:
    text = _safe_text(value).lower().replace("-", "_")
    text = re.sub(r"[^a-z0-9_ ]+", " ", text)
    return " ".join(text.split())


def _safe_text(value: Any) -> str:
    return str(value or "").strip()
