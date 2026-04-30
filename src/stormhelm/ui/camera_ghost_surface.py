from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_FORBIDDEN_KEYS = {
    "api_key",
    "authorization",
    "base64",
    "bytes",
    "file_path",
    "image_base64",
    "image_bytes",
    "image_url",
    "local_path",
    "path",
    "provider_request",
    "provider_request_body",
    "raw_bytes",
    "raw_image",
    "request_body",
    "temp_path",
}
_FORBIDDEN_TEXT_TOKENS = ("data:image", "base64,", "sk-")
_CAMERA_FAMILY = "camera_awareness"
_CAMERA_DECK_PANEL_ID = "camera-visual-context"


def build_camera_ghost_surface_model(
    *,
    active_request_state: dict[str, Any] | None,
    latest_message: dict[str, Any] | None,
    status: dict[str, Any] | None,
) -> dict[str, Any]:
    request = _mapping(active_request_state)
    latest = _mapping(latest_message)
    metadata = _mapping(latest.get("metadata"))
    route_state = _mapping(metadata.get("route_state"))
    winner = _mapping(route_state.get("winner"))
    parameters = _mapping(request.get("parameters"))
    status_payload = _mapping(status)
    camera_status = _camera_status(status_payload)
    family = (
        _text(request.get("family"))
        or _text(winner.get("route_family"))
        or _text(camera_status.get("route_family"))
    ).lower()
    if family != _CAMERA_FAMILY and not camera_status:
        return _empty_surface()

    state = _camera_state(camera_status, parameters)
    answer = _camera_answer(metadata)
    helper_result = _camera_helper_result(metadata, answer)
    comparison_result = _camera_comparison_result(metadata)
    multi_capture_session = _camera_multi_capture_session(metadata)
    source_kind = _source_kind(camera_status, answer)
    source_label = _source_label(source_kind)
    confidence = _text(
        answer.get("confidence")
        or camera_status.get("lastVisionConfidence")
        or camera_status.get("last_vision_confidence")
    ).lower()
    confidence_label = _title(confidence) if confidence else "Not Reported"
    storage_mode = _text(
        camera_status.get("storageMode") or camera_status.get("storage_mode") or "ephemeral"
    ).lower()
    provider_kind = _text(
        camera_status.get("visionProviderKind")
        or camera_status.get("vision_provider_kind")
        or camera_status.get("providerKind")
        or camera_status.get("provider_kind")
        or answer.get("provider_kind")
    ).lower()
    capture_provider_kind = _text(
        camera_status.get("captureProviderKind")
        or camera_status.get("capture_provider_kind")
        or camera_status.get("providerKind")
        or camera_status.get("provider_kind")
    ).lower()
    mock_capture = _bool(camera_status.get("mockCapture") or camera_status.get("mock_capture"))
    mock_analysis = _bool(answer.get("mock_answer")) or provider_kind == "mock"
    real_camera_used = _bool(
        camera_status.get("realCameraUsed")
        or camera_status.get("real_camera_used")
        or _mapping(answer.get("provenance")).get("real_camera_used")
    )
    cloud_upload_performed = _bool(
        camera_status.get("cloudUploadPerformed")
        or camera_status.get("cloud_upload_performed")
        or answer.get("cloud_upload_performed")
        or _mapping(answer.get("provenance")).get("cloud_upload_performed")
    )
    cloud_analysis_performed = _bool(
        camera_status.get("cloudAnalysisPerformed")
        or camera_status.get("cloud_analysis_performed")
        or answer.get("cloud_analysis_performed")
    )
    raw_image_included = False
    artifact_id = _artifact_id(camera_status, answer)
    artifact_expired = _bool(
        camera_status.get("artifactExpired")
        or camera_status.get("artifact_expired")
        or camera_status.get("lastArtifactExpired")
        or camera_status.get("last_artifact_expired")
    )
    artifact_fresh = _bool(
        camera_status.get("lastArtifactFresh") or camera_status.get("last_artifact_fresh")
    ) and not artifact_expired
    artifact_exists = _bool(camera_status.get("artifactExists") or camera_status.get("artifact_exists"))
    artifact_readable = _bool(camera_status.get("artifactReadable") or camera_status.get("artifact_readable"))
    artifact_format = _safe_text(
        camera_status.get("artifactFormat") or camera_status.get("artifact_format") or "unknown"
    ).lower()
    artifact_size_bytes = _int(
        camera_status.get("artifactSizeBytes") or camera_status.get("artifact_size_bytes")
    )
    cleanup_warning = _bool(
        camera_status.get("cleanupFailed")
        or camera_status.get("cleanup_failed")
        or camera_status.get("cleanupPending")
        or camera_status.get("cleanup_pending")
    )
    if cleanup_warning and state == "camera_answer_ready":
        state = "camera_cleanup_warning"

    title, body, status_label, result_state = _card_copy(
        state=state,
        answer=answer,
        source_label=source_label,
        provider_kind=provider_kind,
        mock_analysis=mock_analysis,
        cleanup_warning=cleanup_warning,
    )
    if _has_answer_state(state) and answer:
        body = _safe_text(answer.get("concise_answer") or answer.get("answer_text") or body)
        if mock_analysis and source_kind == "camera_mock":
            title = "Mock Camera Result"
    if helper_result:
        title = _safe_text(helper_result.get("title") or title)
        body = _safe_text(helper_result.get("concise_answer") or body)
    if comparison_result:
        title = _safe_text(comparison_result.get("title") or "Visual Comparison Ready")
        body = _safe_text(comparison_result.get("concise_answer") or body)
        state = "camera_comparison_ready"
        status_label = "Comparison Ready"
        result_state = "attempted"

    provenance = _provenance(
        source_label=source_label,
        confidence_label=confidence_label,
        storage_mode=storage_mode,
        mock_capture=mock_capture,
        mock_analysis=mock_analysis,
        real_camera_used=real_camera_used,
        cloud_analysis_performed=cloud_analysis_performed,
        cloud_upload_performed=cloud_upload_performed,
        artifact_expired=artifact_expired,
        cleanup_warning=cleanup_warning,
    )
    visual_artifact = _visual_artifact(
        artifact_id=artifact_id,
        source_label=source_label,
        storage_mode=storage_mode,
        artifact_fresh=artifact_fresh,
        artifact_expired=artifact_expired,
        artifact_exists=artifact_exists,
        artifact_readable=artifact_readable,
        artifact_format=artifact_format,
        artifact_size_bytes=artifact_size_bytes,
        cleanup_warning=cleanup_warning,
    )
    actions = _actions(
        state=state,
        enabled=_bool(camera_status.get("enabled"), default=True),
        provider_kind=capture_provider_kind,
        artifact_fresh=artifact_fresh,
    )
    chips = [
        _chip("Route", "Camera Awareness"),
        _chip("State", status_label),
        _chip("Source", source_label),
        _chip("Storage", _title(storage_mode) or "Ephemeral"),
    ]
    if confidence:
        chips.append(_chip("Confidence", confidence_label))

    camera_ghost = {
        "visible": True,
        "state": state,
        "sourceKind": source_kind,
        "sourceLabel": source_label,
        "providerKind": provider_kind or "unknown",
        "captureProviderKind": capture_provider_kind or "unknown",
        "confidence": confidence or "",
        "confidenceLabel": confidence_label,
        "storageMode": storage_mode or "ephemeral",
        "imageArtifactId": artifact_id,
        "artifactFresh": artifact_fresh,
        "artifactExpired": artifact_expired,
        "artifactExists": artifact_exists,
        "artifactReadable": artifact_readable,
        "artifactFormat": artifact_format or "unknown",
        "artifactSizeBytes": artifact_size_bytes,
        "mockCapture": mock_capture,
        "mockAnalysis": mock_analysis,
        "realCameraUsed": real_camera_used,
        "cloudAnalysisPerformed": cloud_analysis_performed,
        "cloudUploadPerformed": cloud_upload_performed,
        "rawImageIncluded": raw_image_included,
        "cleanupPending": _bool(camera_status.get("cleanupPending") or camera_status.get("cleanup_pending")),
        "cleanupFailed": _bool(camera_status.get("cleanupFailed") or camera_status.get("cleanup_failed")),
        "errorCode": _safe_text(
            camera_status.get("lastVisionErrorCode")
            or camera_status.get("last_vision_error_code")
            or answer.get("error_code")
        ),
        "evidenceSummary": _safe_text(answer.get("evidence_summary")),
        "uncertaintySummary": _safe_text("; ".join(_text_list(answer.get("uncertainty_reasons"))[:3])),
        "safetyNote": _safe_text(next(iter(_text_list(answer.get("safety_notes"))), "")),
        "providerUnavailableReason": _safe_text(
            camera_status.get("visionUnavailableReason")
            or camera_status.get("vision_unavailable_reason")
            or camera_status.get("providerUnavailableReason")
            or camera_status.get("provider_unavailable_reason")
        ),
        "helperCategory": _safe_text(
            helper_result.get("category") or camera_status.get("lastHelperCategory") or ""
        ),
        "helperFamily": _safe_text(
            helper_result.get("helper_family") or camera_status.get("lastHelperFamily") or ""
        ),
        "helperTitle": _safe_text(helper_result.get("title")),
        "helperConfidence": _safe_text(helper_result.get("confidence_kind")),
        "visualEstimate": _safe_text(helper_result.get("visual_estimate")),
        "verifiedMeasurement": _bool(helper_result.get("verified_measurement")),
        "deterministicCalculationUsed": _bool(helper_result.get("deterministic_calculation_used")),
        "calculationTraceId": _safe_text(helper_result.get("calculation_trace_id")),
        "suggestedMeasurements": _text_list(helper_result.get("suggested_measurements")),
        "engineeringCaveats": _text_list(helper_result.get("caveats")),
        "suggestedNextCapture": _safe_text(helper_result.get("suggested_next_capture")),
        "multiCaptureSessionId": _safe_text(
            multi_capture_session.get("multi_capture_session_id")
            or camera_status.get("lastMultiCaptureSessionId")
            or camera_status.get("last_multi_capture_session_id")
        ),
        "multiCaptureSessionStatus": _safe_text(
            multi_capture_session.get("status")
            or camera_status.get("lastMultiCaptureSessionStatus")
            or camera_status.get("last_multi_capture_session_status")
        ),
        "comparisonStatus": _safe_text(
            comparison_result.get("status")
            or camera_status.get("lastComparisonStatus")
            or camera_status.get("last_comparison_status")
        ),
        "comparisonMode": _safe_text(
            comparison_result.get("comparison_mode")
            or camera_status.get("lastComparisonMode")
            or camera_status.get("last_comparison_mode")
        ),
        "comparisonTitle": _safe_text(comparison_result.get("title")),
        "visualEvidenceOnly": _bool(
            comparison_result.get("visual_evidence_only")
            or camera_status.get("lastComparisonVisualEvidenceOnly")
            or camera_status.get("last_comparison_visual_evidence_only")
        ),
        "verifiedOutcome": _bool(
            comparison_result.get("verified_outcome")
            or camera_status.get("lastComparisonVerifiedOutcome")
            or camera_status.get("last_comparison_verified_outcome")
        ),
        "comparisonSimilarities": _text_list(comparison_result.get("similarities")),
        "comparisonDifferences": _text_list(comparison_result.get("differences")),
    }
    card = {
        "title": title,
        "subtitle": _subtitle(source_label, status_label, provider_kind),
        "body": body,
        "routeLabel": "Camera Awareness",
        "resultState": result_state,
        "statusLabel": status_label,
        "provenance": provenance,
        "cameraGhost": camera_ghost,
        "metaLine": _meta_line(provenance),
    }
    deck_station = _deck_station(
        title=title,
        subtitle=_subtitle(source_label, status_label, provider_kind),
        body=body,
        status_label=status_label,
        result_state=result_state,
        state=state,
        answer=answer,
        helper_result=helper_result,
        comparison_result=comparison_result,
        multi_capture_session=multi_capture_session,
        visual_artifact=visual_artifact,
        source_label=source_label,
        source_kind=source_kind,
        confidence_label=confidence_label,
        provider_kind=provider_kind,
        capture_provider_kind=capture_provider_kind,
        storage_mode=storage_mode,
        mock_capture=mock_capture,
        mock_analysis=mock_analysis,
        real_camera_used=real_camera_used,
        cloud_analysis_performed=cloud_analysis_performed,
        cloud_upload_performed=cloud_upload_performed,
        artifact_fresh=artifact_fresh,
        artifact_expired=artifact_expired,
        cleanup_warning=cleanup_warning,
        actions=actions,
    )
    return {
        "ghostPrimaryCard": _redact(card),
        "ghostActionStrip": _redact(actions),
        "requestComposer": _redact(
            {
                "placeholder": _placeholder(state),
                "headline": title,
                "summary": body,
                "chips": chips,
                "quickActions": [dict(action) for action in actions if action.get("sendText")][:4],
                "clarificationChoices": [],
            }
        ),
        "routeInspector": _redact(
            {
                "title": title,
                "subtitle": "Camera Awareness",
                "summary": "Backend-owned camera UX state. Rendering does not capture or analyze.",
                "body": body,
                "resultState": result_state,
                "statusLabel": status_label,
                "trace": [
                    {"label": "Route", "value": "Camera Awareness"},
                    {"label": "State", "value": status_label},
                    {"label": "Provider", "value": _title(provider_kind) or "Unknown"},
                    {"label": "Source", "value": source_label},
                    {"label": "Deck Panel", "value": "Visual Context"},
                ],
                "provenance": provenance,
                "supportSystems": [
                    {"label": "Artifact", "value": "Fresh" if artifact_fresh else "Expired" if artifact_expired else "Not Ready"},
                    {"label": "Boundary", "value": "Visual Evidence Only"},
                ],
                "invalidations": _invalidations(state, artifact_expired, cleanup_warning),
                "actions": actions,
            }
        ),
        "deckStations": [_redact(deck_station)],
    }


def _camera_status(status: dict[str, Any]) -> dict[str, Any]:
    nested = status.get("camera_awareness")
    if isinstance(nested, Mapping):
        return dict(nested)
    nested = status.get("cameraAwareness")
    if isinstance(nested, Mapping):
        return dict(nested)
    if _text(status.get("route_family")).lower() == _CAMERA_FAMILY:
        return dict(status)
    return {}


def _camera_answer(metadata: dict[str, Any]) -> dict[str, Any]:
    camera = _mapping(metadata.get("camera_awareness")) or _mapping(metadata.get("cameraAwareness"))
    answer = _mapping(camera.get("vision_answer")) or _mapping(camera.get("visionAnswer"))
    return _redact(answer) if answer else {}


def _camera_helper_result(metadata: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    camera = _mapping(metadata.get("camera_awareness")) or _mapping(metadata.get("cameraAwareness"))
    helper = (
        _mapping(camera.get("helper_result"))
        or _mapping(camera.get("helperResult"))
        or _mapping(answer.get("helper_result"))
        or _mapping(answer.get("helperResult"))
    )
    return _redact(helper) if helper else {}


def _camera_comparison_result(metadata: dict[str, Any]) -> dict[str, Any]:
    camera = _mapping(metadata.get("camera_awareness")) or _mapping(metadata.get("cameraAwareness"))
    comparison = (
        _mapping(camera.get("comparison_result"))
        or _mapping(camera.get("comparisonResult"))
    )
    return _redact(comparison) if comparison else {}


def _camera_multi_capture_session(metadata: dict[str, Any]) -> dict[str, Any]:
    camera = _mapping(metadata.get("camera_awareness")) or _mapping(metadata.get("cameraAwareness"))
    session = (
        _mapping(camera.get("multi_capture_session"))
        or _mapping(camera.get("multiCaptureSession"))
    )
    return _redact(session) if session else {}


def _artifact_id(status: dict[str, Any], answer: dict[str, Any]) -> str:
    provenance = _mapping(answer.get("provenance"))
    return _safe_identifier(
        answer.get("image_artifact_id")
        or answer.get("imageArtifactId")
        or provenance.get("image_artifact_id")
        or provenance.get("imageArtifactId")
        or status.get("latestArtifactId")
        or status.get("latest_artifact_id")
        or status.get("imageArtifactId")
        or status.get("image_artifact_id")
    )


def _visual_artifact(
    *,
    artifact_id: str,
    source_label: str,
    storage_mode: str,
    artifact_fresh: bool,
    artifact_expired: bool,
    artifact_exists: bool,
    artifact_readable: bool,
    artifact_format: str,
    artifact_size_bytes: int | None,
    cleanup_warning: bool,
) -> dict[str, Any]:
    if artifact_expired:
        artifact_state = "expired"
        preview_kind = "expired_placeholder"
    elif cleanup_warning:
        artifact_state = "cleanup_warning"
        preview_kind = "safe_ref" if artifact_id and artifact_exists and artifact_readable else "placeholder"
    elif artifact_fresh and artifact_exists and artifact_readable:
        artifact_state = "fresh"
        preview_kind = "mock_placeholder" if artifact_format == "mock" else "safe_ref"
    elif artifact_exists:
        artifact_state = "not_ready"
        preview_kind = "placeholder"
    else:
        artifact_state = "missing"
        preview_kind = "placeholder"
    safe_ref = (
        f"camera-artifact:{artifact_id}"
        if preview_kind == "safe_ref" and artifact_id and not artifact_expired
        else ""
    )
    return {
        "artifactId": artifact_id,
        "artifactState": artifact_state,
        "previewKind": preview_kind,
        "previewLabel": _preview_label(preview_kind, source_label),
        "safePreviewRef": safe_ref,
        "sourceLabel": source_label,
        "storageMode": storage_mode or "ephemeral",
        "artifactExists": artifact_exists,
        "artifactReadable": artifact_readable,
        "artifactExpired": artifact_expired,
        "artifactFresh": artifact_fresh,
        "artifactFormat": artifact_format or "unknown",
        "artifactSizeBytes": artifact_size_bytes,
        "artifactSizeLabel": _format_bytes(artifact_size_bytes),
        "usableForAnalysis": bool(artifact_fresh and artifact_exists and artifact_readable and not artifact_expired),
        "rawPayloadIncluded": False,
        "directFilePathIncluded": False,
        "cleanupWarning": cleanup_warning,
        "renderHint": "Backend-safe preview reference only; QML must not open files directly.",
    }


def _deck_station(
    *,
    title: str,
    subtitle: str,
    body: str,
    status_label: str,
    result_state: str,
    state: str,
    answer: dict[str, Any],
    helper_result: dict[str, Any],
    comparison_result: dict[str, Any],
    multi_capture_session: dict[str, Any],
    visual_artifact: dict[str, Any],
    source_label: str,
    source_kind: str,
    confidence_label: str,
    provider_kind: str,
    capture_provider_kind: str,
    storage_mode: str,
    mock_capture: bool,
    mock_analysis: bool,
    real_camera_used: bool,
    cloud_analysis_performed: bool,
    cloud_upload_performed: bool,
    artifact_fresh: bool,
    artifact_expired: bool,
    cleanup_warning: bool,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    del actions, title
    answer_text = _safe_text(answer.get("concise_answer") or answer.get("answer_text") or body)
    evidence = _safe_text(answer.get("evidence_summary")) or "No visual evidence summary reported."
    uncertainty = "; ".join(_text_list(answer.get("uncertainty_reasons"))[:4]) or "No uncertainty reasons reported."
    safety = "; ".join(_text_list(answer.get("safety_notes"))[:3]) or "No safety notes reported."
    recommended = _safe_text(
        answer.get("recommended_user_action") or answer.get("suggested_next_capture")
    ) or "No backend recommended next step reported."
    analysis_label = _analysis_label(
        mock_analysis=mock_analysis,
        cloud_analysis_performed=cloud_analysis_performed,
        cloud_upload_performed=cloud_upload_performed,
        provider_kind=provider_kind,
        answer_present=bool(answer),
    )
    capture_label = _capture_label(
        mock_capture=mock_capture,
        real_camera_used=real_camera_used,
        capture_provider_kind=capture_provider_kind,
    )
    artifact_label = _artifact_label(
        artifact_fresh=artifact_fresh,
        artifact_expired=artifact_expired,
        cleanup_warning=cleanup_warning,
    )
    chips = [
        _chip("State", status_label, _tone(result_state)),
        _chip("Source", source_label),
        _chip("Artifact", artifact_label, "warning" if cleanup_warning else "stale" if artifact_expired else "steady"),
        _chip("Storage", _title(storage_mode) or "Ephemeral"),
    ]
    if confidence_label:
        chips.append(_chip("Confidence", confidence_label))
    sections = [
        _section(
            "Visual Artifact",
            [
                _entry("Preview", _safe_text(visual_artifact.get("previewLabel"))),
                _entry("Safe Preview Ref", _safe_text(visual_artifact.get("safePreviewRef")) or "No direct preview reference"),
                _entry("Artifact Id", _safe_text(visual_artifact.get("artifactId")) or "Not Reported"),
                _entry("Format", _title(_safe_text(visual_artifact.get("artifactFormat"))) or "Unknown"),
                _entry("Size", _safe_text(visual_artifact.get("artifactSizeLabel"))),
            ],
        ),
        _section(
            "Analysis Detail",
            [
                _entry("Answer", answer_text),
                _entry("Evidence", evidence),
                _entry("Confidence", confidence_label or "Not Reported"),
                _entry("Uncertainty", uncertainty),
                _entry("Safety Notes", safety),
                _entry("Recommended Next Step", recommended),
            ],
        ),
        *_helper_sections(helper_result),
        *_comparison_sections(comparison_result, multi_capture_session),
        _section(
            "Provenance And Policy",
            [
                _entry("Source", source_label, source_kind),
                _entry("Capture", capture_label),
                _entry("Analysis", analysis_label),
                _entry("Provider", _title(provider_kind) or "Unknown"),
                _entry("Cloud Upload", _yes_no(cloud_upload_performed)),
                _entry("Raw Payload", "No"),
            ],
        ),
        _section(
            "Artifact Lifecycle",
            [
                _entry("Storage", _title(storage_mode) or "Ephemeral"),
                _entry("Artifact State", _title(_safe_text(visual_artifact.get("artifactState")))),
                _entry("Usable For Analysis", _yes_no(bool(visual_artifact.get("usableForAnalysis")))),
                _entry("Saved", "Yes" if storage_mode == "saved" else "No"),
                _entry("Cleanup", "Warning" if cleanup_warning else "No Warning"),
            ],
        ),
        _section(
            "Trace Boundary",
            [
                _entry("Provider Output", "Visual Evidence Only"),
                _entry("Verified Outcome", "No"),
                _entry("Action Executed", "No"),
                _entry("Trust Approval", "No"),
                _entry("Task Mutation", "No"),
            ],
        ),
    ]
    return {
        "stationId": _CAMERA_DECK_PANEL_ID,
        "stationFamily": _CAMERA_FAMILY,
        "eyebrow": "Visual Context",
        "title": "Camera Visual Context",
        "subtitle": subtitle,
        "summary": body,
        "body": body,
        "statusLabel": status_label,
        "resultState": result_state,
        "cameraState": state,
        "visualArtifact": visual_artifact,
        "chips": chips,
        "sections": sections,
        "invalidations": _invalidations(state, artifact_expired, cleanup_warning),
        "actions": _deck_actions(
            enabled=state != "camera_disabled",
            provider_kind=capture_provider_kind,
            artifact_fresh=artifact_fresh,
            artifact_expired=artifact_expired,
            cleanup_warning=cleanup_warning,
        ),
        "layoutSlot": "primary",
    }


def _camera_state(status: dict[str, Any], parameters: dict[str, Any]) -> str:
    enabled = _bool(status.get("enabled"), default=True)
    if not enabled:
        return "camera_disabled"
    raw_state = (
        _text(parameters.get("result_state"))
        or _text(parameters.get("request_stage"))
        or _text(status.get("lastVisionStatus"))
        or _text(status.get("last_vision_status"))
        or _text(status.get("lastResultState"))
        or _text(status.get("last_result_state"))
    ).lower()
    mapping = {
        "capture_requested": "camera_capture_requested",
        "camera_capture_requested": "camera_capture_requested",
        "capturing": "camera_capturing",
        "camera_capturing": "camera_capturing",
        "captured": "camera_captured",
        "camera_captured": "camera_captured",
        "analyzing": "camera_analyzing",
        "camera_analyzing": "camera_analyzing",
        "camera_answer_ready": "camera_answer_ready",
        "camera_needs_retake": "camera_retake_recommended",
        "camera_insufficient_image_quality": "camera_retake_recommended",
        "camera_vision_permission_required": "camera_confirmation_required",
        "camera_cloud_analysis_disabled": "camera_cloud_blocked",
        "camera_vision_provider_unavailable": "camera_provider_unavailable",
        "camera_vision_provider_auth_failed": "camera_provider_unavailable",
        "camera_vision_provider_timeout": "camera_provider_unavailable",
        "camera_vision_provider_rate_limited": "camera_provider_unavailable",
        "camera_vision_artifact_expired": "camera_artifact_expired",
        "camera_artifact_expired": "camera_artifact_expired",
        "camera_vision_artifact_missing": "camera_failed",
        "camera_vision_artifact_unreadable": "camera_failed",
        "camera_vision_image_too_large": "camera_blocked",
        "camera_vision_unsupported_format": "camera_blocked",
        "camera_capture_blocked": "camera_blocked",
        "camera_capture_failed": "camera_failed",
        "camera_analysis_failed": "camera_failed",
        "camera_no_device": "camera_provider_unavailable",
        "camera_device_busy": "camera_provider_unavailable",
        "camera_cancelled": "camera_cancelled",
        "multi_capture_started": "camera_multi_capture_started",
        "capture_next_slot": "camera_capture_next_slot",
        "slot_captured": "camera_slot_captured",
        "ready_to_compare": "camera_ready_to_compare",
        "comparing": "camera_comparing",
        "comparison_ready": "camera_comparison_ready",
        "comparison_blocked": "camera_comparison_blocked",
        "comparison_failed": "camera_comparison_failed",
        "session_expired": "camera_session_expired",
    }
    if raw_state in mapping:
        return mapping[raw_state]
    permission = _text(status.get("permissionState") or status.get("permission_state")).lower()
    if raw_state in {"camera_permission_required", "permission_required"} or permission == "required":
        return "camera_permission_required"
    if _bool(status.get("artifactExpired") or status.get("lastArtifactExpired")):
        return "camera_artifact_expired"
    if _bool(status.get("visionProviderAvailable"), default=True) is False:
        return "camera_provider_unavailable"
    return "camera_ready"


def _card_copy(
    *,
    state: str,
    answer: dict[str, Any],
    source_label: str,
    provider_kind: str,
    mock_analysis: bool,
    cleanup_warning: bool,
) -> tuple[str, str, str, str]:
    del provider_kind
    if cleanup_warning:
        return (
            "Camera Cleanup Warning",
            "The camera answer is available, but ephemeral artifact cleanup needs attention.",
            "Cleanup Warning",
            "warning",
        )
    copy = {
        "camera_disabled": ("Camera Awareness Disabled", "Camera awareness is disabled. No camera capture will run from this surface.", "Disabled", "blocked"),
        "camera_permission_required": ("Camera Still Needed", "Stormhelm needs explicit permission for one local camera single still. It stays ephemeral by default.", "Permission Required", "awaiting_approval"),
        "camera_confirmation_required": ("Vision Analysis Needs Confirmation", "The still is captured, but cloud vision analysis needs separate confirmation before any upload.", "Confirmation Required", "awaiting_approval"),
        "camera_cloud_blocked": ("Cloud Vision Blocked", "Cloud vision is disabled by policy. The captured still remains local and ephemeral.", "Blocked", "blocked"),
        "camera_provider_unavailable": ("Vision Provider Unavailable", "The configured camera or vision provider is unavailable. No capture or upload is running.", "Provider Unavailable", "provider_unavailable"),
        "camera_capture_requested": ("Camera Capture Requested", "A backend camera capture request is queued for one explicit still.", "Capture Requested", "prepared"),
        "camera_capturing": ("Capturing Camera Still", "The backend is capturing one still and will release the device after the attempt.", "Capturing", "attempted"),
        "camera_captured": ("Camera Still Captured", "A fresh ephemeral camera still is available. It has not been analyzed yet.", "Captured", "prepared"),
        "camera_analyzing": ("Analyzing Camera Still", "The backend is analyzing the authorized camera still.", "Analyzing", "attempted"),
        "camera_answer_ready": ("Camera Answer Ready", _safe_text(answer.get("concise_answer") or answer.get("answer_text")) or f"Answer is ready from {source_label}.", "Answer Ready", "attempted"),
        "camera_retake_recommended": ("Retake Recommended", _safe_text(answer.get("suggested_next_capture")) or "Stormhelm recommends a fresh still before relying on this visual evidence.", "Retake Recommended", "partial"),
        "camera_artifact_expired": ("Camera Still Expired", "That ephemeral camera still is no longer usable. A fresh explicit capture is needed.", "Expired", "stale"),
        "camera_blocked": ("Camera Request Blocked", "Camera awareness was blocked by policy or artifact validation before provider use.", "Blocked", "blocked"),
        "camera_failed": ("Camera Request Failed", "Camera awareness failed truthfully before any fake analysis or recovery.", "Failed", "failed"),
        "camera_cancelled": ("Camera Request Cancelled", "The camera request was cancelled. No background capture is running.", "Cancelled", "stale"),
        "camera_multi_capture_started": ("Multi-Capture Started", "Stormhelm is guiding a bounded set of explicit still captures.", "Multi-Capture", "prepared"),
        "camera_capture_next_slot": ("Capture Next Still", "Capture the next labeled still when ready. No automatic capture is running.", "Next Still", "prepared"),
        "camera_slot_captured": ("Still Captured", "That labeled still is captured. Continue only with explicit capture actions.", "Slot Captured", "attempted"),
        "camera_ready_to_compare": ("Ready To Compare", "The labeled stills are ready for a visual comparison.", "Ready To Compare", "prepared"),
        "camera_comparing": ("Comparing Stills", "Stormhelm is comparing authorized still artifacts as visual evidence.", "Comparing", "attempted"),
        "camera_comparison_ready": ("Visual Comparison Ready", _safe_text(answer.get("concise_answer") or answer.get("answer_text")) or "Visual comparison is ready.", "Comparison Ready", "attempted"),
        "camera_comparison_blocked": ("Camera Comparison Blocked", "The comparison was blocked before provider use.", "Blocked", "blocked"),
        "camera_comparison_failed": ("Camera Comparison Failed", "Camera comparison failed truthfully without fake verification.", "Failed", "failed"),
        "camera_session_expired": ("Multi-Capture Session Expired", "That bounded multi-capture session is expired. Fresh stills are needed.", "Expired", "stale"),
        "camera_ready": ("Camera Awareness Ready", "Camera awareness is ready for an explicit single-still request.", "Ready", "prepared"),
    }
    title, body, status, result = copy.get(state, copy["camera_ready"])
    if state == "camera_answer_ready" and mock_analysis:
        status = "Mock Answer Ready"
    return title, body, status, result


def _actions(*, state: str, enabled: bool, provider_kind: str, artifact_fresh: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if state == "camera_permission_required" and enabled:
        actions.append(
            {
                "label": "Allow Once",
                "category": "approve",
                "sendText": "allow camera once",
                "authority": "backend_follow_up",
            }
        )
    if state == "camera_confirmation_required" and enabled:
        actions.append(
            {
                "label": "Analyze Once",
                "category": "approve",
                "sendText": "analyze this camera still once",
                "authority": "backend_follow_up",
            }
        )
    if (
        state
        in {
            "camera_answer_ready",
            "camera_retake_recommended",
            "camera_artifact_expired",
            "camera_failed",
            "camera_blocked",
            "camera_cleanup_warning",
            "camera_comparison_ready",
            "camera_comparison_blocked",
            "camera_comparison_failed",
            "camera_ready_to_compare",
            "camera_session_expired",
        }
        and enabled
        and provider_kind not in {"unavailable", "none"}
    ):
        actions.append(
            {
                "label": "Retake",
                "category": "retry",
                "sendText": "retake the camera still",
                "authority": "backend_follow_up",
            }
        )
    actions.append(
        {
            "label": "Dismiss",
            "category": "dismiss",
            "localAction": "dismiss_camera_card",
            "authority": "local_presentational",
        }
    )
    if artifact_fresh or state in {
        "camera_answer_ready",
        "camera_cleanup_warning",
        "camera_artifact_expired",
        "camera_comparison_ready",
        "camera_ready_to_compare",
        "camera_comparison_blocked",
        "camera_comparison_failed",
    }:
        actions.append(
            {
                "label": "Open In Deck",
                "category": "reveal",
                "localAction": f"open_panel:{_CAMERA_DECK_PANEL_ID}",
                "authority": "local_presentational",
                "enabled": True,
            }
        )
    return actions


def _deck_actions(
    *,
    enabled: bool,
    provider_kind: str,
    artifact_fresh: bool,
    artifact_expired: bool,
    cleanup_warning: bool,
) -> list[dict[str, Any]]:
    provider_available = enabled and provider_kind not in {"unavailable", "none"}
    can_analyze = enabled and artifact_fresh and not artifact_expired
    return [
        {
            "label": "Retake",
            "category": "retry",
            "sendText": "retake the camera still",
            "authority": "backend_follow_up",
            "enabled": provider_available,
        },
        {
            "label": "Analyze Again",
            "category": "approve",
            "sendText": "reanalyze this camera still",
            "authority": "backend_follow_up",
            "enabled": can_analyze,
            "disabledReason": "" if can_analyze else "The artifact is not fresh and usable for analysis.",
        },
        {
            "label": "Discard",
            "category": "dismiss",
            "authority": "deferred",
            "enabled": False,
            "disabledReason": "Backend discard action is not wired to the Deck bridge yet.",
        },
        {
            "label": "Attach To Task",
            "category": "attach",
            "authority": "deferred",
            "enabled": False,
            "disabledReason": "Task attachment is deferred until persistent artifact support exists.",
        },
        {
            "label": "Save To Logbook",
            "category": "save",
            "authority": "deferred",
            "enabled": False,
            "disabledReason": "Saving is deferred and requires explicit backend confirmation.",
        },
        {
            "label": "Open Trace",
            "category": "reveal",
            "localAction": "open_route_inspector",
            "authority": "local_presentational",
            "enabled": True,
            "disabledReason": "Cleanup warning present; trace remains read-only." if cleanup_warning else "",
        },
    ]


def _analysis_label(
    *,
    mock_analysis: bool,
    cloud_analysis_performed: bool,
    cloud_upload_performed: bool,
    provider_kind: str,
    answer_present: bool,
) -> str:
    if mock_analysis:
        return "Mock Analysis"
    if cloud_analysis_performed or cloud_upload_performed:
        return "Cloud Vision"
    if answer_present and provider_kind:
        return _title(provider_kind)
    return "Not Analyzed"


def _capture_label(
    *,
    mock_capture: bool,
    real_camera_used: bool,
    capture_provider_kind: str,
) -> str:
    if mock_capture:
        return "Mock Capture"
    if real_camera_used:
        return "Local Camera"
    if capture_provider_kind == "local":
        return "Local Provider Ready"
    return "No Real Camera"


def _artifact_label(*, artifact_fresh: bool, artifact_expired: bool, cleanup_warning: bool) -> str:
    if cleanup_warning:
        return "Cleanup Warning"
    if artifact_expired:
        return "Expired"
    if artifact_fresh:
        return "Fresh"
    return "Not Ready"


def _preview_label(preview_kind: str, source_label: str) -> str:
    labels = {
        "safe_ref": f"Safe backend reference for {source_label}",
        "mock_placeholder": "Mock artifact placeholder",
        "expired_placeholder": "Expired artifact placeholder",
        "placeholder": "Preview placeholder",
    }
    return labels.get(preview_kind, "Preview placeholder")


def _helper_sections(helper_result: dict[str, Any]) -> list[dict[str, Any]]:
    if not helper_result:
        return []
    suggested_measurements = "; ".join(_text_list(helper_result.get("suggested_measurements")))
    caveats = "; ".join(_text_list(helper_result.get("caveats")))
    return [
        _section(
            "Engineering Helper",
            [
                _entry("Helper Type", _helper_family_label(helper_result.get("helper_family"))),
                _entry("Visual Estimate", _safe_text(helper_result.get("visual_estimate")) or "Not Reported"),
                _entry("Verified Measurement", _yes_no(_bool(helper_result.get("verified_measurement")))),
                _entry("Suggested Measurement", suggested_measurements or "No measurement suggested."),
                _entry("Caveats", caveats or "Visual evidence only."),
                _entry(
                    "Suggested Next Capture",
                    _safe_text(helper_result.get("suggested_next_capture")) or "No retake guidance reported.",
                ),
            ],
        )
    ]


def _comparison_sections(
    comparison_result: dict[str, Any],
    multi_capture_session: dict[str, Any],
) -> list[dict[str, Any]]:
    if not comparison_result:
        return []
    summaries = [
        item for item in comparison_result.get("artifact_summaries", [])
        if isinstance(item, Mapping)
    ]
    artifact_a = _artifact_summary_label(summaries[0]) if len(summaries) >= 1 else "Not Reported"
    artifact_b = _artifact_summary_label(summaries[1]) if len(summaries) >= 2 else "Not Reported"
    return [
        _section(
            "Visual Comparison",
            [
                _entry("Comparison Mode", _title(_safe_text(comparison_result.get("comparison_mode")))),
                _entry("Similarities", "; ".join(_text_list(comparison_result.get("similarities"))) or "None reported."),
                _entry("Differences", "; ".join(_text_list(comparison_result.get("differences"))) or "None reported."),
                _entry("Confidence", _title(_safe_text(comparison_result.get("confidence_kind"))) or "Not Reported"),
                _entry("Visual Evidence Only", _yes_no(_bool(comparison_result.get("visual_evidence_only"), default=True))),
                _entry("Verified Outcome", _yes_no(_bool(comparison_result.get("verified_outcome")))),
            ],
        ),
        _section(
            "Comparison Artifacts",
            [
                _entry("Session", _safe_text(multi_capture_session.get("multi_capture_session_id")) or "Not Reported"),
                _entry("Artifact A", artifact_a),
                _entry("Artifact B", artifact_b),
                _entry("Raw Payload", "No"),
            ],
        ),
    ]


def _artifact_summary_label(summary: Mapping[str, Any]) -> str:
    label = _safe_text(summary.get("label") or summary.get("slot_id") or "Artifact")
    artifact_id = _safe_identifier(summary.get("artifact_id"))
    safe_ref = _safe_text(summary.get("safe_preview_ref"))
    parts = [label]
    if artifact_id:
        parts.append(artifact_id)
    if safe_ref:
        parts.append(safe_ref)
    return " | ".join(parts)


def _helper_family_label(value: Any) -> str:
    text = _safe_text(value).replace(".", " ").replace("-", " ").replace("_", " ")
    return text.title() if text else "Not Reported"


def _section(title: str, entries: list[dict[str, str]]) -> dict[str, Any]:
    return {"title": title, "summary": "", "entries": entries}


def _entry(primary: str, secondary: str, detail: str = "") -> dict[str, str]:
    return {
        "primary": _safe_text(primary),
        "secondary": _safe_text(secondary),
        "detail": _safe_text(detail),
    }


def _tone(result_state: str) -> str:
    if result_state in {"blocked", "failed", "provider_unavailable"}:
        return "warning"
    if result_state in {"stale"}:
        return "stale"
    if result_state in {"partial", "awaiting_approval"}:
        return "attention"
    return "steady"


def _provenance(
    *,
    source_label: str,
    confidence_label: str,
    storage_mode: str,
    mock_capture: bool,
    mock_analysis: bool,
    real_camera_used: bool,
    cloud_analysis_performed: bool,
    cloud_upload_performed: bool,
    artifact_expired: bool,
    cleanup_warning: bool,
) -> list[dict[str, str]]:
    entries = [
        {"label": "Source", "value": source_label, "tone": "steady"},
        {"label": "Confidence", "value": confidence_label, "tone": "steady"},
        {"label": "Storage", "value": _title(storage_mode) or "Ephemeral", "tone": "steady"},
    ]
    if artifact_expired:
        entries.append({"label": "Artifact", "value": "Expired", "tone": "stale"})
    elif cleanup_warning:
        entries.append({"label": "Cleanup", "value": "Warning", "tone": "warning"})
    if mock_capture or mock_analysis:
        entries.append({"label": "Analysis", "value": "Mock Analysis", "tone": "attention"})
    elif cloud_analysis_performed or cloud_upload_performed:
        entries.append({"label": "Analysis", "value": "Cloud Vision", "tone": "attention"})
    elif real_camera_used:
        entries.append({"label": "Capture", "value": "Local Camera", "tone": "steady"})
    else:
        entries.append({"label": "Analysis", "value": "Not Analyzed", "tone": "steady"})
    return entries


def _source_kind(status: dict[str, Any], answer: dict[str, Any]) -> str:
    provenance = _mapping(answer.get("provenance"))
    source = _text(
        provenance.get("source")
        or status.get("artifactSourceProvenance")
        or status.get("artifact_source_provenance")
        or status.get("lastSourceProvenance")
        or status.get("last_source_provenance")
    ).lower()
    if source:
        return source
    if _bool(status.get("mockCapture") or status.get("mock_capture")):
        return "camera_mock"
    return "camera_unavailable"


def _source_label(source_kind: str) -> str:
    labels = {
        "camera_mock": "Mock Camera",
        "camera_local": "Local Camera Still",
        "uploaded_image": "Uploaded Image",
        "file": "File",
        "clipboard": "Clipboard",
        "selection": "Selection",
        "screen": "Screen Context",
        "screen_context": "Screen Context",
        "camera_unavailable": "Unavailable",
        "camera_policy": "Camera Policy",
    }
    return labels.get(source_kind, _title(source_kind) or "Unknown")


def _subtitle(source_label: str, status_label: str, provider_kind: str) -> str:
    parts = ["Camera Awareness", source_label, status_label]
    if provider_kind:
        parts.append(_title(provider_kind))
    return " | ".join(part for part in parts if part)


def _meta_line(entries: list[dict[str, str]]) -> str:
    return " | ".join(f"{entry['label']}: {entry['value']}" for entry in entries[:4])


def _placeholder(state: str) -> str:
    if state in {"camera_permission_required", "camera_confirmation_required"}:
        return "Confirm the camera step or redirect the request."
    if state in {"camera_artifact_expired", "camera_failed", "camera_blocked"}:
        return "Retake explicitly or ask a fresh camera question."
    return "Ask a camera follow-up, retake, or dismiss this camera card."


def _invalidations(state: str, artifact_expired: bool, cleanup_warning: bool) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if artifact_expired or state == "camera_artifact_expired":
        entries.append(
            {
                "label": "Artifact",
                "reason": "The ephemeral camera still is expired and cannot be reused.",
                "tone": "stale",
            }
        )
    if cleanup_warning:
        entries.append(
            {
                "label": "Cleanup",
                "reason": "Temp artifact cleanup did not complete cleanly.",
                "tone": "warning",
            }
        )
    return entries


def _has_answer_state(state: str) -> bool:
    return state in {
        "camera_answer_ready",
        "camera_retake_recommended",
        "camera_cleanup_warning",
        "camera_comparison_ready",
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_text(value: Any) -> str:
    text = _text(value)
    lowered = text.lower()
    if any(token in lowered for token in _FORBIDDEN_TEXT_TOKENS):
        return "[redacted]"
    return text[:360]


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_safe_text(item) for item in value if _safe_text(item)]
    text = _safe_text(value)
    return [text] if text else []


def _bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "enabled", "allowed", "available", "granted"}:
        return True
    if text in {"0", "false", "no", "disabled", "blocked", "unavailable", "denied"}:
        return False
    return default


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _safe_identifier(value: Any) -> str:
    text = _safe_text(value)
    if not text or text == "[redacted]":
        return ""
    allowed = []
    for char in text:
        if char.isalnum() or char in {"-", "_"}:
            allowed.append(char)
    return "".join(allowed)[:96]


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "Unknown"
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value / (1024 * 1024):.1f} MiB"


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _title(value: str) -> str:
    text = _safe_text(value).replace("-", " ").replace("_", " ")
    return text.title() if text else ""


def _chip(label: str, value: str, tone: str = "steady") -> dict[str, str]:
    return {"label": label, "value": value, "tone": tone}


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _FORBIDDEN_KEYS:
                continue
            redacted[key_text] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _empty_surface() -> dict[str, Any]:
    return {
        "ghostPrimaryCard": {},
        "ghostActionStrip": [],
        "requestComposer": {
            "placeholder": "Give Stormhelm a grounded request or continue the current thread.",
            "headline": "",
            "summary": "",
            "chips": [],
            "quickActions": [],
            "clarificationChoices": [],
        },
        "routeInspector": {},
        "deckStations": [],
    }
