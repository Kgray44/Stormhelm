from __future__ import annotations

from datetime import timedelta
from typing import Any

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CAMERA_SOURCE_PROVENANCE_MOCK,
    CameraAwarenessSubsystem,
    CameraFrameArtifact,
    CameraStorageMode,
    utc_now,
)
from stormhelm.core.camera_awareness.comparison import classify_camera_comparison_request
from stormhelm.core.camera_awareness.models import (
    CameraCaptureSlotStatus,
    CameraComparisonMode,
    CameraComparisonStatus,
    CameraMultiCaptureSessionStatus,
)
from stormhelm.core.camera_awareness.prompts import build_camera_comparison_prompt
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


def _service(temp_project_root, *, vision_provider: str = "mock") -> tuple[CameraAwarenessSubsystem, EventBuffer]:
    events = EventBuffer(capacity=128)
    app_config = load_config(project_root=temp_project_root, env={})
    camera = app_config.camera_awareness
    camera.enabled = True
    camera.privacy.confirm_before_capture = False
    camera.capture.provider = "mock"
    camera.vision.provider = vision_provider
    camera.vision.allow_cloud_vision = False
    camera.allow_cloud_vision = False
    return CameraAwarenessSubsystem(camera, events=events), events


def _artifact(
    artifact_id: str,
    *,
    fixture_name: str = "comparison",
    image_format: str = "mock",
    expired: bool = False,
) -> CameraFrameArtifact:
    created_at = utc_now() - timedelta(minutes=10) if expired else utc_now()
    expires_at = utc_now() - timedelta(minutes=1) if expired else utc_now() + timedelta(minutes=5)
    return CameraFrameArtifact(
        capture_result_id=f"capture-{artifact_id}",
        image_artifact_id=artifact_id,
        storage_mode=CameraStorageMode.EPHEMERAL,
        created_at=created_at,
        expires_at=expires_at,
        image_format=image_format,
        mock_artifact=True,
        fixture_name=fixture_name,
        source_provenance=CAMERA_SOURCE_PROVENANCE_MOCK,
    )


def _filled_before_after_session(service: CameraAwarenessSubsystem):
    session = service.create_multi_capture_session(
        user_request_id="c6-session",
        session_id="chat-c6",
        purpose="before_after_solder",
        user_question="Compare this solder joint before and after I reflow it.",
    )
    before = service.artifacts.add(_artifact("camera-before", fixture_name="solder_before"))
    after = service.artifacts.add(_artifact("camera-after", fixture_name="solder_after"))
    service.add_capture_to_session(
        session.multi_capture_session_id,
        "before",
        before.image_artifact_id,
        capture_request_id="capture-before-request",
        capture_result_id=before.capture_result_id,
    )
    session = service.add_capture_to_session(
        session.multi_capture_session_id,
        "after",
        after.image_artifact_id,
        capture_request_id="capture-after-request",
        capture_result_id=after.capture_result_id,
    )
    return session


def _camera_request(stage: str = "comparison_ready") -> dict[str, Any]:
    return {
        "request_id": "camera-c6-request",
        "family": "camera_awareness",
        "subject": "camera comparison",
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
        "latestArtifactId": "camera-after",
        "lastMultiCaptureSessionStatus": "completed",
        "lastComparisonStatus": "completed",
        "lastComparisonMode": "before_after",
        "lastComparisonVisualEvidenceOnly": True,
        "lastComparisonVerifiedOutcome": False,
    }
    status.update(overrides)
    return status


def _answer_message(comparison_result: dict[str, Any], session_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": "assistant-camera-c6",
        "role": "assistant",
        "content": comparison_result["concise_answer"],
        "created_at": "2026-04-30T21:00:00Z",
        "metadata": {
            "bearing_title": "Camera Comparison",
            "micro_response": comparison_result["concise_answer"],
            "camera_awareness": {
                "comparison_result": comparison_result,
                "multi_capture_session": session_payload,
            },
            "route_state": {
                "winner": {
                    "route_family": "camera_awareness",
                    "query_shape": "camera_awareness_request",
                    "posture": "clear_winner",
                    "status": "comparison_ready",
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


def _plan(message: str):
    return DeterministicPlanner().plan(
        message,
        session_id="camera-c6-route-test",
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


def test_c6_multi_capture_session_tracks_labeled_slots_without_auto_capture(temp_project_root) -> None:
    service, events = _service(temp_project_root)

    session = service.create_multi_capture_session(
        user_request_id="c6-front-back",
        session_id="chat-c6",
        purpose="front_back_pcb",
        user_question="I'll show you the front and back of this PCB.",
    )

    assert session.status == CameraMultiCaptureSessionStatus.ACTIVE
    assert session.comparison_mode == CameraComparisonMode.FRONT_BACK
    assert [slot.slot_id for slot in session.expected_slots] == ["front", "back"]
    assert all(slot.status == CameraCaptureSlotStatus.PENDING for slot in session.expected_slots)
    assert session.storage_mode_default == CameraStorageMode.EPHEMERAL
    assert session.mock_session is True
    assert service.capture_provider.capture_attempted is False
    assert service.capture_provider.hardware_access_attempted is False

    front = service.artifacts.add(_artifact("camera-front", fixture_name="pcb_front"))
    updated = service.add_capture_to_session(
        session.multi_capture_session_id,
        "front",
        front.image_artifact_id,
        capture_request_id="front-request",
        capture_result_id=front.capture_result_id,
    )

    assert updated.status == CameraMultiCaptureSessionStatus.ACTIVE
    assert updated.current_slot_id == "back"
    assert updated.captured_slots[0].slot_id == "front"

    back = service.artifacts.add(_artifact("camera-back", fixture_name="pcb_back"))
    updated = service.add_capture_to_session(
        session.multi_capture_session_id,
        "back",
        back.image_artifact_id,
        capture_request_id="back-request",
        capture_result_id=back.capture_result_id,
    )

    assert updated.status == CameraMultiCaptureSessionStatus.READY_TO_COMPARE
    assert updated.artifact_ids == ["camera-front", "camera-back"]
    assert all(slot.artifact_id for slot in updated.captured_slots)
    assert service.capture_provider.capture_attempted is False

    snapshot = service.status_snapshot()
    assert snapshot["lastMultiCaptureSessionStatus"] == "ready_to_compare"
    assert snapshot["lastMultiCaptureSlotCount"] == 2
    assert snapshot["lastMultiCaptureArtifactCount"] == 2
    assert snapshot["rawImageIncluded"] is False

    event_types = [event["event_type"] for event in events.recent(limit=64)]
    assert "camera.multi_capture_session_created" in event_types
    assert "camera.multi_capture_slot_requested" in event_types
    assert "camera.multi_capture_slot_captured" in event_types
    assert "camera.multi_capture_session_ready" in event_types
    assert _contains_forbidden_payload([event["payload"] for event in events.recent(limit=64)]) is False


def test_c6_comparison_classifier_is_generic_helper_aware_not_engineering_only() -> None:
    generic = classify_camera_comparison_request("Which image is clearer?")
    assert generic.applicable is True
    assert generic.comparison_mode == CameraComparisonMode.QUALITY_COMPARE
    assert generic.helper_category is None
    assert generic.helper_family is None

    engineering = classify_camera_comparison_request(
        "Compare this solder joint before and after I reflow it."
    )
    assert engineering.applicable is True
    assert engineering.comparison_mode == CameraComparisonMode.BEFORE_AFTER
    assert engineering.helper_category == "engineering_inspection"
    assert engineering.helper_family == "engineering.solder_joint_inspection"

    general_knowledge = classify_camera_comparison_request("Compare React and Vue.")
    assert general_knowledge.applicable is False
    assert general_knowledge.helper_family is None


def test_c6_mock_comparison_result_preserves_visual_only_boundaries_and_telemetry(temp_project_root) -> None:
    service, events = _service(temp_project_root)
    session = _filled_before_after_session(service)
    request = service.create_comparison_request(
        multi_capture_session_id=session.multi_capture_session_id,
        user_request_id="c6-compare",
        user_question="Compare this solder joint before and after I reflow it.",
    )

    result = service.analyze_comparison_with_selected_provider(request)

    assert result.status == CameraComparisonStatus.COMPLETED
    assert result.comparison_mode == CameraComparisonMode.BEFORE_AFTER
    assert result.helper_category == "engineering_inspection"
    assert result.helper_family == "engineering.solder_joint_inspection"
    assert result.similarities
    assert result.differences
    assert result.visual_evidence_only is True
    assert result.verified_outcome is False
    assert result.action_executed is False
    assert result.mock_comparison is True
    assert result.cloud_analysis_performed is False
    assert result.raw_image_included is False
    assert any("multimeter" in item.lower() or "continuity" in item.lower() for item in result.suggested_measurements)
    assert "fixed" not in result.concise_answer.lower()
    assert _contains_forbidden_payload(result.to_dict()) is False
    assert service.capture_provider.capture_attempted is False
    assert service.vision_provider.network_access_attempted is False

    snapshot = service.status_snapshot()
    assert snapshot["lastComparisonStatus"] == "completed"
    assert snapshot["lastComparisonMode"] == "before_after"
    assert snapshot["lastComparisonVisualEvidenceOnly"] is True
    assert snapshot["lastComparisonVerifiedOutcome"] is False
    assert snapshot["lastComparisonActionExecuted"] is False

    event_types = [event["event_type"] for event in events.recent(limit=96)]
    assert "camera.comparison_requested" in event_types
    assert "camera.comparison_policy_checked" in event_types
    assert "camera.comparison_provider_selected" in event_types
    assert "camera.comparison_completed" in event_types
    payloads = [event["payload"] for event in events.recent(limit=96)]
    assert _contains_forbidden_payload(payloads) is False
    assert all(payload.get("verified_outcome") is not True for payload in payloads)
    assert all(payload.get("action_executed") is not True for payload in payloads)


def test_c6_comparison_validation_blocks_invalid_artifacts_before_provider_use(temp_project_root) -> None:
    service, _events = _service(temp_project_root)

    one_artifact_request = service.create_comparison_request(
        artifact_ids=["only-one"],
        user_request_id="c6-one-artifact",
        user_question="Compare these images.",
    )
    one_artifact_result = service.analyze_comparison_with_selected_provider(one_artifact_request)
    assert one_artifact_result.status == CameraComparisonStatus.BLOCKED
    assert one_artifact_result.error_code == "comparison_requires_at_least_two_artifacts"
    assert service.vision_provider.network_access_attempted is False

    session = service.create_multi_capture_session(
        user_request_id="c6-expired",
        session_id="chat-c6",
        purpose="before_after",
        user_question="Compare before and after.",
    )
    service.artifacts.add(_artifact("fresh-before", fixture_name="before"))
    service.artifacts.add(_artifact("expired-after", fixture_name="after", expired=True))
    service.add_capture_to_session(session.multi_capture_session_id, "before", "fresh-before")
    service.add_capture_to_session(session.multi_capture_session_id, "after", "expired-after")
    expired_request = service.create_comparison_request(
        multi_capture_session_id=session.multi_capture_session_id,
        user_request_id="c6-expired-compare",
        user_question="Compare before and after.",
    )
    expired_result = service.analyze_comparison_with_selected_provider(expired_request)
    assert expired_result.status == CameraComparisonStatus.BLOCKED
    assert expired_result.error_code == "comparison_artifact_expired"
    assert any(summary.slot_id == "after" and summary.ready is False for summary in expired_result.artifact_summaries)

    service2, _events2 = _service(temp_project_root)
    unsupported = service2.create_multi_capture_session(
        user_request_id="c6-unsupported",
        session_id="chat-c6",
        purpose="option_a_b",
        user_question="Compare these two photos.",
    )
    service2.artifacts.add(_artifact("option-a", image_format="mock"))
    service2.artifacts.add(_artifact("option-b", image_format="bmp"))
    service2.add_capture_to_session(unsupported.multi_capture_session_id, "option_a", "option-a")
    service2.add_capture_to_session(unsupported.multi_capture_session_id, "option_b", "option-b")
    unsupported_request = service2.create_comparison_request(
        multi_capture_session_id=unsupported.multi_capture_session_id,
        user_request_id="c6-unsupported-compare",
        user_question="Compare these two photos.",
    )
    unsupported_result = service2.analyze_comparison_with_selected_provider(unsupported_request)
    assert unsupported_result.status == CameraComparisonStatus.BLOCKED
    assert unsupported_result.error_code == "comparison_artifact_unsupported_format"
    assert service2.vision_provider.network_access_attempted is False


def test_c6_cloud_comparison_policy_blocks_before_provider_request(temp_project_root) -> None:
    service, events = _service(temp_project_root, vision_provider="openai")
    session = _filled_before_after_session(service)
    request = service.create_comparison_request(
        multi_capture_session_id=session.multi_capture_session_id,
        user_request_id="c6-cloud-block",
        user_question="Compare these two images.",
    )

    result = service.analyze_comparison_with_selected_provider(request)

    assert result.status == CameraComparisonStatus.BLOCKED
    assert result.error_code == "comparison_cloud_blocked"
    assert result.cloud_analysis_performed is False
    assert result.raw_image_included is False
    assert service.vision_provider.network_access_attempted is False
    payloads = [event["payload"] for event in events.recent(limit=96)]
    assert _contains_forbidden_payload(payloads) is False


def test_c6_comparison_prompt_preserves_visual_evidence_boundary() -> None:
    request = classify_camera_comparison_request(
        "Compare this solder joint before and after I reflow it."
    ).to_request(
        user_request_id="c6-prompt",
        artifact_ids=["before-artifact", "after-artifact"],
        slot_ids=["before", "after"],
        provider_kind="mock",
    )

    prompt = build_camera_comparison_prompt(
        request,
        artifact_summaries=[
            {"slot_id": "before", "label": "Before", "artifact_id": "before-artifact"},
            {"slot_id": "after", "label": "After", "artifact_id": "after-artifact"},
        ],
    )

    prompt_text = f"{prompt.system_prompt}\n{prompt.user_prompt}".lower()
    assert "before" in prompt_text
    assert "after" in prompt_text
    assert "visual evidence" in prompt_text
    assert "do not claim" in prompt_text
    assert "fixed" in prompt_text
    assert "verified" in prompt_text
    assert "measured" in prompt_text


def test_c6_ghost_and_deck_models_present_comparison_without_raw_payloads(temp_config) -> None:
    comparison = {
        "comparison_result_id": "camera-comparison-c6",
        "comparison_request_id": "camera-comparison-request-c6",
        "status": "completed",
        "title": "Before/After Visual Comparison",
        "concise_answer": "The after image appears cleaner around the joint, but this is not verification.",
        "comparison_mode": "before_after",
        "helper_category": "engineering_inspection",
        "helper_family": "engineering.solder_joint_inspection",
        "artifact_summaries": [
            {
                "artifact_id": "camera-before",
                "slot_id": "before",
                "label": "Before",
                "safe_preview_ref": "camera-artifact:camera-before",
                "source_provenance": "camera_mock",
                "ready": True,
            },
            {
                "artifact_id": "camera-after",
                "slot_id": "after",
                "label": "After",
                "safe_preview_ref": "camera-artifact:camera-after",
                "source_provenance": "camera_mock",
                "ready": True,
            },
        ],
        "similarities": ["Both images show the same solder joint area."],
        "differences": ["The after image appears smoother and shinier."],
        "confidence_kind": "medium",
        "evidence_summary": "Mock comparison of two labeled stills.",
        "uncertainty_reasons": ["Angle and lighting differ."],
        "caveats": ["Visual comparison is not verification."],
        "suggested_measurements": ["Check continuity with a multimeter."],
        "visual_evidence_only": True,
        "verified_outcome": False,
        "action_executed": False,
        "raw_image_included": False,
        "mock_comparison": True,
        "cloud_analysis_performed": False,
        "image_url": "data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD",
    }
    session = {
        "multi_capture_session_id": "camera-session-c6",
        "status": "completed",
        "comparison_mode": "before_after",
        "artifact_ids": ["camera-before", "camera-after"],
        "provider_request_body": {"raw_image": "SECRET_IMAGE_PAYLOAD"},
    }
    bridge = UiBridge(temp_config)

    bridge.apply_snapshot(
        {
            "history": [_answer_message(comparison, session)],
            "status": {"camera_awareness": _camera_status()},
            "active_request_state": _camera_request(),
        }
    )

    card = bridge.ghostPrimaryCard
    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    station = panels["camera-visual-context"]["stationData"]
    entries = _entries_by_primary(station)

    assert card["title"] == "Before/After Visual Comparison"
    assert card["cameraGhost"]["comparisonMode"] == "before_after"
    assert card["cameraGhost"]["comparisonStatus"] == "completed"
    assert card["cameraGhost"]["visualEvidenceOnly"] is True
    assert card["cameraGhost"]["verifiedOutcome"] is False
    assert entries["Comparison Mode"]["secondary"] == "Before After"
    assert entries["Similarities"]["secondary"]
    assert entries["Differences"]["secondary"]
    assert entries["Verified Outcome"]["secondary"] == "No"
    assert entries["Artifact A"]["secondary"].startswith("Before")
    assert entries["Artifact B"]["secondary"].startswith("After")
    assert _contains_forbidden_payload(
        {
            "ghost": bridge.ghostPrimaryCard,
            "deck": bridge.deckPanels,
            "inspector": bridge.routeInspector,
        }
    ) is False


def test_c6_comparison_routes_do_not_steal_general_comparison_or_calculation_routes() -> None:
    positive = [
        "I'll show you the front and back of this PCB.",
        "Compare this solder joint before and after I reflow it.",
        "Can you compare these two connectors?",
        "Which image is clearer?",
        "Can you compare the close-up to the full view?",
    ]
    for message in positive:
        trace = PlannerV2().plan(message)
        assert trace.route_decision.selected_route_family == "camera_awareness", message

    for message in [
        "Compare React and Vue.",
        "Compare the cost of these two plans.",
        "What is a before and after study?",
        "How does image comparison work?",
        "Calculate the difference between 12 and 7.",
    ]:
        assert _winner(_plan(message)) != "camera_awareness", message
