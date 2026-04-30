from __future__ import annotations

from typing import Any

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CameraAwarenessSubsystem,
    CameraCaptureSource,
    CameraConfidenceLevel,
    CameraVisionAnswer,
    CameraVisionQuestion,
    build_camera_vision_prompt,
)
from stormhelm.core.camera_awareness.helpers import build_default_camera_helper_registry
from stormhelm.core.camera_awareness.models import (
    CameraAwarenessResultState,
    CameraHelperCategory,
    CameraHelperFamily,
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


def _vision_answer(
    *,
    user_question: str = "What resistor value is this?",
    answer_text: str = "The bands appear brown black orange gold.",
    confidence: CameraConfidenceLevel = CameraConfidenceLevel.MEDIUM,
    helper_hints: dict[str, Any] | None = None,
) -> CameraVisionAnswer:
    question = CameraVisionQuestion(
        image_artifact_id="camera-frame-c5",
        user_question=user_question,
        normalized_question=user_question.lower(),
    )
    return CameraVisionAnswer(
        vision_question_id=question.vision_question_id,
        image_artifact_id=question.image_artifact_id,
        answer_text=answer_text,
        concise_answer=answer_text,
        confidence=confidence,
        result_state=CameraAwarenessResultState.CAMERA_ANSWER_READY,
        provider="mock",
        model="mock-vision",
        mock_answer=True,
        provider_kind="mock",
        cloud_upload_performed=False,
        cloud_analysis_performed=False,
        raw_image_included=False,
        evidence_summary="Provider described visible engineering features.",
        uncertainty_reasons=["Single still only."],
        safety_notes=["Visual analysis only; not command authority."],
        helper_hints=helper_hints or {},
        provenance={
            "source": "camera_mock",
            "artifact_id": "camera-frame-c5",
            "mock_analysis": True,
            "cloud_upload_performed": False,
            "cloud_analysis_performed": False,
            "raw_image_included": False,
        },
    )


def _plan(message: str):
    return DeterministicPlanner().plan(
        message,
        session_id="camera-c5-route-test",
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


def _camera_request(
    *,
    stage: str = "camera_answer_ready",
    result_state: str | None = None,
) -> dict[str, Any]:
    return {
        "request_id": "camera-c5-request",
        "family": "camera_awareness",
        "subject": "camera still",
        "request_type": "camera_awareness_request",
        "query_shape": "camera_awareness_request",
        "parameters": {
            "request_stage": stage,
            "result_state": result_state or stage,
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
        "configuredCaptureProvider": "mock",
        "configuredVisionProvider": "mock",
        "mockMode": True,
        "mockCapture": True,
        "realCameraUsed": False,
        "cloudUploadPerformed": False,
        "cloudAnalysisPerformed": False,
        "rawImageIncluded": False,
        "storageMode": "ephemeral",
        "lastVisionStatus": "camera_answer_ready",
        "lastVisionConfidence": "medium",
        "lastArtifactFresh": True,
        "artifactExpired": False,
        "artifactReadable": True,
        "artifactExists": True,
        "artifactFormat": "mock",
        "artifactSourceProvenance": "camera_mock",
        "latestArtifactId": "camera-frame-c5",
    }
    status.update(overrides)
    return status


def _answer_message(answer: dict[str, Any], helper_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": "assistant-camera-c5",
        "role": "assistant",
        "content": answer["answer_text"],
        "created_at": "2026-04-30T20:00:00Z",
        "metadata": {
            "bearing_title": "Camera Awareness",
            "micro_response": answer["concise_answer"],
            "camera_awareness": {
                "vision_answer": answer,
                "helper_result": helper_result,
            },
            "route_state": {
                "winner": {
                    "route_family": "camera_awareness",
                    "query_shape": "camera_awareness_request",
                    "posture": "clear_winner",
                    "status": "camera_answer_ready",
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


def test_c5_registry_classifies_engineering_helpers_without_stealing_educational_requests() -> None:
    registry = build_default_camera_helper_registry()
    positive = {
        "What resistor value is this?": CameraHelperFamily.ENGINEERING_RESISTOR_COLOR_BANDS,
        "Can you read this resistor?": CameraHelperFamily.ENGINEERING_RESISTOR_COLOR_BANDS,
        "What connector is this?": CameraHelperFamily.ENGINEERING_CONNECTOR_IDENTIFICATION,
        "Is this JST-XH or JST-PH?": CameraHelperFamily.ENGINEERING_CONNECTOR_IDENTIFICATION,
        "What does this IC marking say?": CameraHelperFamily.ENGINEERING_COMPONENT_MARKING,
        "Does this solder joint look bad?": CameraHelperFamily.ENGINEERING_SOLDER_JOINT_INSPECTION,
        "Can you inspect this PCB?": CameraHelperFamily.ENGINEERING_PCB_VISUAL_INSPECTION,
        "The label is blurry; how should I retake this?": CameraHelperFamily.ENGINEERING_PHOTO_QUALITY_GUIDANCE,
        "What kind of screw is this?": CameraHelperFamily.ENGINEERING_MECHANICAL_PART_INSPECTION,
        "What does this warning light mean?": CameraHelperFamily.ENGINEERING_PHYSICAL_TROUBLESHOOTING,
    }

    for question, expected in positive.items():
        classification = registry.classify(user_question=question, vision_answer=None)
        assert classification.applicable is True, question
        assert classification.category == CameraHelperCategory.ENGINEERING_INSPECTION
        assert classification.helper_family == expected

    for question in [
        "How do resistor color codes work?",
        "What is a JST-XH connector?",
        "Show examples of cold solder joints.",
        "Explain what flux does.",
        "What is the MAX31856?",
    ]:
        classification = registry.classify(user_question=question, vision_answer=None)
        assert classification.applicable is False, question
        assert classification.helper_family == CameraHelperFamily.UNKNOWN


def test_c5_resistor_helper_decodes_clear_bands_as_visual_estimate_not_measurement() -> None:
    registry = build_default_camera_helper_registry()
    answer = _vision_answer(
        helper_hints={
            "helper_family": "engineering.resistor_color_bands",
            "visible_bands": ["brown", "black", "orange", "gold"],
            "band_confidence": "medium",
            "quality_warnings": ["dim lighting"],
        }
    )

    result = registry.build_result(
        user_question="What resistor value is this?",
        vision_answer=answer,
    )

    assert result is not None
    assert result.helper_family == CameraHelperFamily.ENGINEERING_RESISTOR_COLOR_BANDS
    assert result.title == "Resistor Estimate"
    assert result.visual_estimate == "10 kOhm +/-5%"
    assert result.deterministic_calculation_used is True
    assert result.calculation_trace_id == "resistor-bands:brown-black-orange-gold"
    assert result.verified_measurement is False
    assert result.action_executed is False
    assert any("multimeter" in item.lower() for item in result.suggested_measurements)
    assert any("visual estimate" in item.lower() for item in result.caveats)
    assert "measured resistance" not in str(result.to_dict()).lower()


def test_c5_connector_marking_solder_pcb_photo_and_mechanical_helpers_preserve_caveats() -> None:
    registry = build_default_camera_helper_registry()
    cases = [
        (
            "What connector is this?",
            {
                "helper_family": "engineering.connector_identification",
                "likely_connector_family": "JST-XH",
                "scale_reference_present": False,
            },
            CameraHelperFamily.ENGINEERING_CONNECTOR_IDENTIFICATION,
            "pitch",
        ),
        (
            "What does this IC marking say?",
            {
                "helper_family": "engineering.component_marking",
                "readable_text": "MAX31856",
                "uncertain_text": "M?D",
            },
            CameraHelperFamily.ENGINEERING_COMPONENT_MARKING,
            "uncertain",
        ),
        (
            "Does this solder joint look bad?",
            {
                "helper_family": "engineering.solder_joint_inspection",
                "visible_issue": "dull uneven joint",
            },
            CameraHelperFamily.ENGINEERING_SOLDER_JOINT_INSPECTION,
            "electrically verify",
        ),
        (
            "Can you inspect this PCB?",
            {
                "helper_family": "engineering.pcb_visual_inspection",
                "visible_issue": "possible solder bridge near lower pins",
            },
            CameraHelperFamily.ENGINEERING_PCB_VISUAL_INSPECTION,
            "closer",
        ),
        (
            "The photo is blurry; how should I retake this?",
            {
                "helper_family": "engineering.photo_quality_guidance",
                "quality_warnings": ["blur", "glare", "no scale reference"],
            },
            CameraHelperFamily.ENGINEERING_PHOTO_QUALITY_GUIDANCE,
            "retake",
        ),
        (
            "What kind of screw is this?",
            {
                "helper_family": "engineering.mechanical_part_inspection",
                "visible_part": "small countersunk screw",
            },
            CameraHelperFamily.ENGINEERING_MECHANICAL_PART_INSPECTION,
            "dimension",
        ),
    ]

    for question, hints, family, expected_word in cases:
        result = registry.build_result(
            user_question=question,
            vision_answer=_vision_answer(user_question=question, helper_hints=hints),
        )
        assert result is not None, question
        assert result.helper_family == family
        assert result.category == CameraHelperCategory.ENGINEERING_INSPECTION
        assert result.verified_measurement is False
        assert result.action_executed is False
        assert result.trust_approved is False
        assert result.task_mutation_performed is False
        assert expected_word in str(result.to_dict()).lower()


def test_c5_service_layers_helper_result_on_mock_flow_with_safe_telemetry(temp_project_root) -> None:
    events = EventBuffer(capacity=64)
    app_config = load_config(project_root=temp_project_root, env={})
    camera = app_config.camera_awareness
    camera.enabled = True
    camera.privacy.confirm_before_capture = False
    camera.capture.provider = "mock"
    camera.vision.provider = "mock"
    service = CameraAwarenessSubsystem(camera, events=events)

    flow = service.answer_mock_question(
        user_question="What resistor value is this?",
        user_request_id="c5-helper-flow",
        session_id="session-c5",
        source=CameraCaptureSource.TEST,
    )

    assert flow.result_state == CameraAwarenessResultState.CAMERA_ANSWER_READY
    assert flow.helper_result is not None
    assert flow.helper_result.helper_family == CameraHelperFamily.ENGINEERING_RESISTOR_COLOR_BANDS
    assert flow.helper_result.verified_measurement is False
    assert flow.helper_result.raw_image_included is False
    assert service.capture_provider.capture_attempted is True
    assert service.capture_provider.hardware_access_attempted is False
    assert service.vision_provider.network_access_attempted is False
    assert _contains_forbidden_payload(flow.helper_result.to_dict()) is False

    snapshot = service.status_snapshot()
    assert snapshot["lastHelperFamily"] == "engineering.resistor_color_bands"
    assert snapshot["lastHelperCategory"] == "engineering_inspection"
    assert snapshot["lastHelperVerifiedMeasurement"] is False
    assert snapshot["lastHelperActionExecuted"] is False

    recent_events = events.recent(limit=64)
    event_types = [event["event_type"] for event in recent_events]
    event_payloads = [event["payload"] for event in recent_events]
    assert "camera.engineering_helper_classified" in event_types
    assert "camera.engineering_helper_completed" in event_types
    assert _contains_forbidden_payload(event_payloads) is False
    assert all(payload.get("verified_measurement") is not True for payload in event_payloads)
    assert all(payload.get("action_executed") is not True for payload in event_payloads)


def test_c5_ghost_and_deck_models_present_helper_fields_without_raw_payloads(temp_config) -> None:
    registry = build_default_camera_helper_registry()
    answer = _vision_answer(
        helper_hints={
            "helper_family": "engineering.resistor_color_bands",
            "visible_bands": ["brown", "black", "orange", "gold"],
        }
    )
    helper_result = registry.build_result(
        user_question="What resistor value is this?",
        vision_answer=answer,
    )
    answer_payload = answer.to_dict()
    answer_payload["image_url"] = "data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD"
    helper_payload = helper_result.to_dict()
    helper_payload["provider_request_body"] = {"raw_image": "SECRET_IMAGE_PAYLOAD"}
    bridge = UiBridge(temp_config)

    bridge.apply_snapshot(
        {
            "history": [_answer_message(answer_payload, helper_payload)],
            "status": {"camera_awareness": _camera_status()},
            "active_request_state": _camera_request(),
        }
    )

    card = bridge.ghostPrimaryCard
    panels = {panel["panelId"]: panel for panel in bridge.deckPanels}
    station = panels["camera-visual-context"]["stationData"]
    entries = _entries_by_primary(station)

    assert card["title"] == "Resistor Estimate"
    assert card["cameraGhost"]["helperFamily"] == "engineering.resistor_color_bands"
    assert card["cameraGhost"]["visualEstimate"] == "10 kOhm +/-5%"
    assert card["cameraGhost"]["verifiedMeasurement"] is False
    assert entries["Helper Type"]["secondary"] == "Engineering Resistor Color Bands"
    assert entries["Visual Estimate"]["secondary"] == "10 kOhm +/-5%"
    assert entries["Verified Measurement"]["secondary"] == "No"
    assert entries["Suggested Measurement"]["secondary"]
    assert _contains_forbidden_payload(
        {
            "ghost": bridge.ghostPrimaryCard,
            "deck": bridge.deckPanels,
            "inspector": bridge.routeInspector,
        }
    ) is False


def test_c5_prompt_templates_include_engineering_visual_only_guidance() -> None:
    question = CameraVisionQuestion(
        image_artifact_id="camera-frame-c5",
        user_question="What resistor value is this?",
        normalized_question="what resistor value is this?",
    )

    prompt = build_camera_vision_prompt(question)

    prompt_text = f"{prompt.system_prompt}\n{prompt.user_prompt}".lower()
    assert "engineering" in prompt_text
    assert "visual estimate" in prompt_text
    assert "do not claim" in prompt_text
    assert "measured resistance" in prompt_text
    assert "verified measurement" in prompt_text


def test_c5_engineering_routes_do_not_steal_general_knowledge_or_calculation_routes() -> None:
    positive = [
        "What resistor value is this?",
        "Is this JST-XH? I'm holding it up to the camera.",
        "What does this IC marking say in front of me?",
        "Does this solder joint look bad?",
    ]
    for message in positive:
        trace = PlannerV2().plan(message)
        assert trace.route_decision.selected_route_family == "camera_awareness", message

    for message in [
        "How do resistor color codes work?",
        "What is a JST-XH connector?",
        "Show examples of cold solder joints.",
        "Explain what flux does.",
        "What is the MAX31856?",
        "Calculate resistance from 5V and 2mA.",
    ]:
        assert _winner(_plan(message)) != "camera_awareness", message
