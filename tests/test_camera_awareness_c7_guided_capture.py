from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CAMERA_SOURCE_PROVENANCE_MOCK,
    CameraAwarenessSubsystem,
    CameraCaptureGuidanceStatus,
    CameraCaptureQualityIssueKind,
    CameraComparisonMode,
    CameraComparisonResult,
    CameraComparisonStatus,
    CameraConfidenceLevel,
    CameraFrameArtifact,
    CameraStorageMode,
    utc_now,
)
from stormhelm.core.events import EventBuffer
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2
from stormhelm.ui.bridge import UiBridge


FORBIDDEN_PAYLOAD_KEYS = {
    "api_key",
    "authorization",
    "image_base64",
    "image_bytes",
    "image_url",
    "provider_request",
    "provider_request_body",
    "raw_image",
    "request_body",
}
FORBIDDEN_PAYLOAD_TOKENS = ("data:image", "base64,", "SECRET_IMAGE_PAYLOAD", "sk-test-secret")


def _contains_forbidden_payload(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_PAYLOAD_KEYS:
                return True
            if _contains_forbidden_payload(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_contains_forbidden_payload(item) for item in value)
    text = str(value)
    return any(token in text for token in FORBIDDEN_PAYLOAD_TOKENS)


def _service(temp_project_root) -> tuple[CameraAwarenessSubsystem, EventBuffer]:
    events = EventBuffer(capacity=128)
    app_config = load_config(project_root=temp_project_root, env={})
    camera = app_config.camera_awareness
    camera.enabled = True
    camera.privacy.confirm_before_capture = False
    camera.capture.provider = "mock"
    camera.vision.provider = "mock"
    camera.vision.allow_cloud_vision = False
    camera.allow_cloud_vision = False
    return CameraAwarenessSubsystem(camera, events=events), events


def _artifact(
    artifact_id: str,
    *,
    warnings: list[str] | None = None,
    expired: bool = False,
    fixture_name: str = "guidance",
) -> CameraFrameArtifact:
    created_at = utc_now() - timedelta(minutes=10) if expired else utc_now()
    expires_at = utc_now() - timedelta(minutes=1) if expired else utc_now() + timedelta(minutes=5)
    return CameraFrameArtifact(
        capture_result_id=f"capture-{artifact_id}",
        image_artifact_id=artifact_id,
        storage_mode=CameraStorageMode.EPHEMERAL,
        created_at=created_at,
        expires_at=expires_at,
        image_format="mock",
        mock_artifact=True,
        fixture_name=fixture_name,
        source_provenance=CAMERA_SOURCE_PROVENANCE_MOCK,
        quality_warnings=list(warnings or []),
    )


def _camera_request(stage: str = "capture_guidance_ready") -> dict[str, Any]:
    return {
        "request_id": "camera-c7-request",
        "family": "camera_awareness",
        "subject": "camera guidance",
        "request_type": "camera_awareness_request",
        "query_shape": "camera_awareness_request",
        "parameters": {
            "request_stage": stage,
            "result_state": stage,
            "selected_source_route": "camera_awareness",
        },
    }


def _camera_status(**overrides: Any) -> dict[str, Any]:
    status: dict[str, Any] = {
        "enabled": True,
        "route_family": "camera_awareness",
        "providerKind": "mock",
        "captureProviderKind": "mock",
        "visionProviderKind": "mock",
        "mockMode": True,
        "mockCapture": True,
        "realCameraUsed": False,
        "cloudUploadPerformed": False,
        "cloudAnalysisPerformed": False,
        "rawImageIncluded": False,
        "storageMode": "ephemeral",
        "lastVisionStatus": "camera_answer_ready",
        "lastArtifactFresh": True,
        "artifactExpired": False,
        "artifactReadable": True,
        "artifactExists": True,
        "artifactFormat": "mock",
        "artifactSourceProvenance": "camera_mock",
        "latestArtifactId": "camera-guidance",
    }
    status.update(overrides)
    return status


def _guidance_message(guidance_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": "assistant-camera-c7",
        "role": "assistant",
        "content": guidance_result["concise_guidance"],
        "created_at": "2026-04-30T22:00:00Z",
        "metadata": {
            "bearing_title": "Camera Guidance",
            "micro_response": guidance_result["concise_guidance"],
            "camera_awareness": {"capture_guidance": guidance_result},
            "route_state": {
                "winner": {
                    "route_family": "camera_awareness",
                    "query_shape": "camera_awareness_request",
                    "posture": "clear_winner",
                    "status": "capture_guidance_ready",
                },
            },
        },
    }


def _entries_by_primary(station: dict[str, Any]) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}
    for section in station.get("sections", []):
        for entry in section.get("entries", []):
            entries[str(entry.get("primary", ""))] = entry
    return entries


def _camera_station(bridge: UiBridge) -> dict[str, Any]:
    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    return panels["camera-visual-context"]["stationData"]


def _plan(message: str):
    return DeterministicPlanner().plan(
        message,
        session_id="camera-c7-route-test",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state={},
        active_context={},
        recent_tool_results=[],
    )


def _winner(decision) -> str:  # noqa: ANN001
    return decision.route_state.to_dict()["winner"]["route_family"]


def test_c7_quality_warnings_map_to_typed_retake_guidance_without_side_effects(temp_project_root) -> None:
    service, events = _service(temp_project_root)
    artifact = service.artifacts.add(
        _artifact(
            "camera-guidance",
            warnings=[
                "blur",
                "low_light",
                "glare",
                "object_out_of_frame",
                "text_too_small",
                "angle_too_oblique",
                "missing_scale_reference",
                "missing_context",
                "missing_closeup",
            ],
        )
    )

    guidance = service.create_capture_guidance(
        image_artifact_id=artifact.image_artifact_id,
        user_question="Can you read this component marking?",
        helper_family="engineering.component_marking",
        session_id="chat-c7",
    )

    assert guidance.status == CameraCaptureGuidanceStatus.GUIDANCE_READY
    issue_kinds = {issue.issue_kind for issue in guidance.quality_issues}
    assert CameraCaptureQualityIssueKind.BLUR in issue_kinds
    assert CameraCaptureQualityIssueKind.LOW_LIGHT in issue_kinds
    assert CameraCaptureQualityIssueKind.GLARE in issue_kinds
    assert CameraCaptureQualityIssueKind.OBJECT_OUT_OF_FRAME in issue_kinds
    assert CameraCaptureQualityIssueKind.TEXT_TOO_SMALL in issue_kinds
    assert CameraCaptureQualityIssueKind.ANGLE_TOO_OBLIQUE in issue_kinds
    assert CameraCaptureQualityIssueKind.MISSING_SCALE_REFERENCE in issue_kinds
    assert CameraCaptureQualityIssueKind.MISSING_CONTEXT in issue_kinds
    assert CameraCaptureQualityIssueKind.MISSING_CLOSEUP in issue_kinds
    guidance_text = f"{guidance.concise_guidance} {guidance.detailed_guidance}".lower()
    assert "hold still" in guidance_text
    assert "more light" in guidance_text or "improve lighting" in guidance_text
    assert "glare" in guidance_text
    assert "center" in guidance_text
    assert "move closer" in guidance_text
    assert "straight-on" in guidance_text
    assert "ruler" in guidance_text or "scale reference" in guidance_text
    assert "wider" in guidance_text
    assert "close-up" in guidance_text
    assert guidance.source_provenance == "camera_mock"
    assert guidance.storage_mode == CameraStorageMode.EPHEMERAL
    assert guidance.visual_evidence_only is True
    assert guidance.capture_triggered is False
    assert guidance.analysis_triggered is False
    assert guidance.upload_triggered is False
    assert guidance.raw_image_included is False
    assert service.capture_provider.capture_attempted is False
    assert service.vision_provider.network_access_attempted is False

    event_types = [event["event_type"] for event in events.recent(limit=32)]
    assert "camera.capture_quality_evaluated" in event_types
    assert "camera.capture_guidance_created" in event_types
    assert "camera.capture_started" not in event_types
    assert "camera.vision_requested" not in event_types
    assert _contains_forbidden_payload([event["payload"] for event in events.recent(limit=32)]) is False


@pytest.mark.parametrize(
    ("helper_family", "warnings", "expected_phrases"),
    [
        (
            "engineering.resistor_color_bands",
            ["text_blurry", "low_light", "glare"],
            ("bands centered", "side lighting"),
        ),
        (
            "engineering.connector_identification",
            ["missing_scale_reference", "angle_too_oblique"],
            ("ruler", "known-size part"),
        ),
        (
            "engineering.component_marking",
            ["text_too_small", "glare"],
            ("marking flat", "light angled"),
        ),
        (
            "engineering.solder_joint_inspection",
            ["angle_too_oblique", "glare"],
            ("straight-on", "diffuse light"),
        ),
        (
            "plant.identification",
            ["missing_context", "missing_closeup"],
            ("wider context", "close-up"),
        ),
    ],
)
def test_c7_helper_aware_guidance_is_specific_but_not_engineering_only(
    temp_project_root,
    helper_family: str,
    warnings: list[str],
    expected_phrases: tuple[str, ...],
) -> None:
    service, _events = _service(temp_project_root)
    artifact = service.artifacts.add(
        _artifact("camera-helper-guidance", warnings=warnings, fixture_name=helper_family)
    )

    guidance = service.create_capture_guidance(
        image_artifact_id=artifact.image_artifact_id,
        user_question="How should I retake this?",
        helper_family=helper_family,
    )

    assert guidance.status == CameraCaptureGuidanceStatus.GUIDANCE_READY
    assert guidance.helper_family == helper_family
    text = f"{guidance.concise_guidance} {guidance.detailed_guidance}".lower()
    for phrase in expected_phrases:
        assert phrase in text
    assert guidance.verified_measurement is False
    assert guidance.verified_outcome is False
    assert guidance.action_executed is False


def test_c7_multi_capture_guidance_tracks_next_slot_and_expiry_without_auto_capture(temp_project_root) -> None:
    service, events = _service(temp_project_root)
    session = service.create_multi_capture_session(
        user_request_id="c7-front-back",
        session_id="chat-c7",
        purpose="front_back_pcb",
        user_question="Guide me through the front and back of this PCB.",
    )

    first_guidance = service.create_comparison_capture_guidance(
        multi_capture_session_id=session.multi_capture_session_id,
    )

    assert first_guidance.status == CameraCaptureGuidanceStatus.GUIDANCE_READY
    assert first_guidance.suggested_capture_label == "front"
    assert "front" in first_guidance.concise_guidance.lower()
    assert first_guidance.capture_triggered is False

    front = service.artifacts.add(_artifact("camera-front", fixture_name="pcb_front"))
    service.add_capture_to_session(
        session.multi_capture_session_id,
        "front",
        front.image_artifact_id,
        capture_request_id="front-request",
        capture_result_id=front.capture_result_id,
    )
    next_guidance = service.create_comparison_capture_guidance(
        multi_capture_session_id=session.multi_capture_session_id,
    )

    assert next_guidance.suggested_capture_label == "back"
    assert "back" in next_guidance.concise_guidance.lower()
    assert service.capture_provider.capture_attempted is False

    session.expires_at = utc_now() - timedelta(seconds=1)
    expired = service.create_comparison_capture_guidance(
        multi_capture_session_id=session.multi_capture_session_id,
    )

    assert expired.status == CameraCaptureGuidanceStatus.BLOCKED
    assert expired.error_code == "capture_guidance_session_expired"
    assert "expired" in expired.concise_guidance.lower()
    assert "camera.capture_guidance_failed" in [
        event["event_type"] for event in events.recent(limit=64)
    ]


def test_c7_comparison_alignment_guidance_uses_existing_result_only(temp_project_root) -> None:
    service, _events = _service(temp_project_root)
    session = service.create_multi_capture_session(
        user_request_id="c7-align-session",
        session_id="chat-c7",
        purpose="before_after_alignment",
        user_question="Compare before and after.",
    )
    before = service.artifacts.add(_artifact("camera-before", warnings=[]))
    after = service.artifacts.add(_artifact("camera-after", warnings=[]))
    service.add_capture_to_session(
        session.multi_capture_session_id,
        "before",
        before.image_artifact_id,
        capture_request_id="before-request",
        capture_result_id=before.capture_result_id,
    )
    service.add_capture_to_session(
        session.multi_capture_session_id,
        "after",
        after.image_artifact_id,
        capture_request_id="after-request",
        capture_result_id=after.capture_result_id,
    )
    request = service.create_comparison_request(
        multi_capture_session_id=session.multi_capture_session_id,
        user_question="Compare before and after.",
        user_request_id="c7-align",
    )
    summaries, reason = service._comparison_artifact_summaries(request)
    assert reason is None
    comparison_result = CameraComparisonResult(
        comparison_request_id=request.comparison_request_id,
        status=CameraComparisonStatus.COMPLETED,
        title="Visual Comparison Ready",
        concise_answer="The before and after shots are not aligned enough to compare confidently.",
        comparison_mode=CameraComparisonMode.BEFORE_AFTER,
        artifact_summaries=summaries,
        confidence_kind=CameraConfidenceLevel.LOW,
        differences=["The after image is from a different angle."],
        uncertainty_reasons=["comparison_angle_mismatch", "lighting differs between shots"],
        suggested_next_capture="Retake the after image from the same angle as the before image.",
    )

    guidance = service.create_comparison_capture_guidance(
        comparison_result=comparison_result,
    )

    issue_kinds = {issue.issue_kind for issue in guidance.quality_issues}
    assert CameraCaptureQualityIssueKind.COMPARISON_ANGLE_MISMATCH in issue_kinds
    assert CameraCaptureQualityIssueKind.COMPARISON_LIGHTING_MISMATCH in issue_kinds
    assert "same angle" in guidance.concise_guidance.lower()
    assert guidance.analysis_triggered is False
    assert guidance.upload_triggered is False
    assert service.vision_provider.network_access_attempted is False


def test_c7_missing_or_signal_free_artifacts_fail_truthfully(temp_project_root) -> None:
    service, _events = _service(temp_project_root)
    missing = service.create_capture_guidance(
        image_artifact_id="missing-artifact",
        user_question="How should I retake this?",
    )
    assert missing.status == CameraCaptureGuidanceStatus.BLOCKED
    assert missing.error_code == "capture_guidance_artifact_missing"

    artifact = service.artifacts.add(_artifact("camera-clean", warnings=[]))
    no_signal = service.create_capture_guidance(
        image_artifact_id=artifact.image_artifact_id,
        user_question="How should I retake this?",
    )
    assert no_signal.status == CameraCaptureGuidanceStatus.INSUFFICIENT_EVIDENCE
    assert no_signal.error_code == "capture_guidance_no_quality_signal"
    assert "closer, better-lit" in no_signal.concise_guidance.lower()
    assert no_signal.capture_triggered is False
    assert no_signal.analysis_triggered is False


def test_c7_ghost_and_deck_surface_guidance_without_raw_payloads_or_render_side_effects(temp_config) -> None:
    bridge = UiBridge(temp_config)
    guidance = {
        "guidance_result_id": "camera-guidance-c7",
        "artifact_id": "camera-guidance",
        "status": "guidance_ready",
        "title": "Retake Recommended",
        "concise_guidance": "Hold it closer, center the marking, and add more light.",
        "detailed_guidance": "The label is blurry and small. Retake closer with the marking flat to the camera.",
        "quality_issues": [
            {
                "issue_kind": "text_blurry",
                "severity": "high",
                "confidence_kind": "medium",
                "evidence": "Provider reported blurry text.",
                "artifact_id": "camera-guidance",
            },
            {
                "issue_kind": "low_light",
                "severity": "medium",
                "confidence_kind": "medium",
                "evidence": "Provider reported dim lighting.",
                "artifact_id": "camera-guidance",
            },
        ],
        "suggested_next_capture": "Retake closer with the marking centered.",
        "suggested_capture_label": "close_up_label",
        "suggested_user_actions": ["retake_explicitly"],
        "helper_family": "engineering.component_marking",
        "confidence_kind": "medium",
        "source_provenance": "camera_mock",
        "storage_mode": "ephemeral",
        "visual_evidence_only": True,
        "capture_triggered": False,
        "analysis_triggered": False,
        "upload_triggered": False,
        "raw_image_included": False,
        "verified_measurement": False,
        "verified_outcome": False,
        "action_executed": False,
    }

    bridge.apply_snapshot(
        {
            "history": [_guidance_message(guidance)],
            "status": {"camera_awareness": _camera_status(lastCaptureGuidanceStatus="guidance_ready")},
            "active_request_state": _camera_request(),
        }
    )

    card = bridge.ghostPrimaryCard
    actions = {entry["label"]: entry for entry in bridge.ghostActionStrip}
    station = _camera_station(bridge)
    entries = _entries_by_primary(station)

    assert card["title"] == "Retake Recommended"
    assert card["body"] == "Hold it closer, center the marking, and add more light."
    assert card["cameraGhost"]["state"] == "camera_guidance_ready"
    assert card["cameraGhost"]["captureGuidanceStatus"] == "guidance_ready"
    assert card["cameraGhost"]["guidanceIssueKinds"] == ["text_blurry", "low_light"]
    assert card["cameraGhost"]["guidanceSuggestedCaptureLabel"] == "close_up_label"
    assert card["cameraGhost"]["guidanceCaptureTriggered"] is False
    assert actions["Retake"]["sendText"] == "retake the camera still"
    assert actions["Open In Deck"]["enabled"] is True
    assert "Capture Quality" in [section["title"] for section in station["sections"]]
    assert entries["Guidance"]["secondary"] == guidance["concise_guidance"]
    assert entries["Verified Outcome"]["secondary"] == "No"
    assert entries["Raw Payload"]["secondary"] == "No"
    assert _contains_forbidden_payload(card) is False
    assert _contains_forbidden_payload(station) is False


def test_c7_guidance_requests_route_to_camera_only_when_artifact_context_is_implied() -> None:
    camera_cases = [
        "How should I retake this camera still?",
        "Why can't you read it with the camera?",
        "What do you need to see better in this photo?",
        "Can you guide me to capture this part better?",
    ]
    for message in camera_cases:
        trace = PlannerV2().plan(message)
        assert trace.route_decision.selected_route_family == "camera_awareness", message
        assert trace.intent_frame.extracted_entities["analysis_mode"] == "guidance"

    non_camera_cases = [
        "How do cameras focus?",
        "What is shutter speed?",
        "How do I take better photos in general?",
    ]
    for message in non_camera_cases:
        assert _winner(_plan(message)) != "camera_awareness", message
