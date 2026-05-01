from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CAMERA_SOURCE_PROVENANCE_MOCK,
    CameraArtifactStore,
    CameraAwarenessPolicy,
    CameraAwarenessResultState,
    CameraAwarenessSubsystem,
    CameraCaptureGuidanceResult,
    CameraCaptureGuidanceStatus,
    CameraCaptureRequest,
    CameraCaptureResult,
    CameraCaptureSlotStatus,
    CameraCaptureStatus,
    CameraComparisonArtifactSummary,
    CameraComparisonMode,
    CameraComparisonResult,
    CameraComparisonStatus,
    CameraConfidenceLevel,
    CameraEngineeringHelperResult,
    CameraFrameArtifact,
    CameraHelperCategory,
    CameraHelperFamily,
    CameraStorageMode,
    CameraTelemetryEmitter,
    CameraVisionAnswer,
    CameraVisionQuestion,
    build_default_camera_helper_registry,
    utc_now,
)
from stormhelm.core.camera_awareness.providers import CameraVisionProviderAvailability
from stormhelm.core.events import EventBuffer
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2
from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.camera_ghost_surface import build_camera_ghost_surface_model


FORBIDDEN_PAYLOAD_KEYS = {
    "api_key",
    "authorization",
    "base64",
    "bytes",
    "image_base64",
    "image_bytes",
    "image_url",
    "provider_request",
    "provider_request_body",
    "provider_response",
    "provider_raw_response",
    "raw_provider_response",
    "raw_image",
    "request_body",
    "unbounded_provider_response",
}
FORBIDDEN_PAYLOAD_TOKENS = (
    "data:image",
    "base64,",
    "SECRET_IMAGE_PAYLOAD",
    "sk-test-secret",
)


CAMERA_C8_SCENARIOS: list[dict[str, Any]] = [
    {
        "scenario_id": "routing.camera_positive.holding",
        "user_utterance": "What is this I'm holding?",
        "context": {},
        "expected_route_family": "camera_awareness",
        "expected_result_state": "camera_permission_required",
        "expected_policy_state": "capture_confirmation_required",
        "expected_provider_behavior": "no_provider_until_explicit_capture",
        "expected_artifact_behavior": "no_artifact_yet",
        "expected_ui_truth": "camera_still_needed",
        "forbidden_claims": ["verified", "measured", "saved"],
        "forbidden_side_effects": ["capture_attempted", "analysis_attempted", "cloud_upload_attempted"],
    },
    {
        "scenario_id": "routing.camera_ambiguous.what_is_this",
        "user_utterance": "What is this?",
        "context": {},
        "expected_route_family": "not_camera_awareness",
        "expected_result_state": "ambiguous_visual_source",
        "expected_policy_state": "no_camera_policy_use",
        "expected_provider_behavior": "none",
        "expected_artifact_behavior": "none",
        "expected_ui_truth": "no_camera_source_claim",
        "forbidden_claims": ["camera provenance"],
        "forbidden_side_effects": ["capture_attempted", "analysis_attempted", "cloud_upload_attempted"],
    },
    {
        "scenario_id": "routing.upload_vs_camera.uploaded_image",
        "user_utterance": "Analyze this uploaded image.",
        "context": {"source": "uploaded_image"},
        "expected_route_family": "not_camera_awareness",
        "expected_result_state": "source_specific_non_camera",
        "expected_policy_state": "no_camera_policy_use",
        "expected_provider_behavior": "none",
        "expected_artifact_behavior": "uploaded_image_not_camera_artifact",
        "expected_ui_truth": "no_camera_source_claim",
        "forbidden_claims": ["camera provenance"],
        "forbidden_side_effects": ["capture_attempted", "analysis_attempted", "cloud_upload_attempted"],
    },
    {
        "scenario_id": "privacy.raw_payload.provider_response",
        "user_utterance": "Show the camera answer.",
        "context": {"surface": "ghost_and_deck"},
        "expected_route_family": "camera_awareness",
        "expected_result_state": "answer_ready",
        "expected_policy_state": "raw_payload_redacted",
        "expected_provider_behavior": "provider_response_not_surfaced",
        "expected_artifact_behavior": "safe_ref_only",
        "expected_ui_truth": "visual_evidence_only",
        "forbidden_claims": ["verified fixed", "action executed"],
        "forbidden_side_effects": ["capture_attempted", "analysis_attempted", "cloud_upload_attempted"],
    },
]


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


def _app_config(temp_project_root):
    app_config = load_config(project_root=temp_project_root, env={})
    camera = app_config.camera_awareness
    camera.enabled = True
    camera.privacy.confirm_before_capture = False
    camera.capture.provider = "mock"
    camera.vision.provider = "mock"
    camera.allow_cloud_vision = False
    camera.vision.allow_cloud_vision = False
    camera.allow_task_artifact_save = False
    camera.allow_session_permission = False
    return app_config


def _plan(message: str, *, context: dict[str, Any] | None = None):
    context = context or {}
    return DeterministicPlanner().plan(
        message,
        session_id="camera-c8-route-test",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=context,
        active_posture={},
        active_request_state={},
        active_context=context,
        recent_tool_results=[],
    )


def _winner(decision) -> str:  # noqa: ANN001
    return decision.route_state.to_dict()["winner"]["route_family"]


def _artifact(
    artifact_id: str,
    *,
    file_path: str | None = None,
    image_format: str = "mock",
    expired: bool = False,
    mock_artifact: bool = True,
    warnings: list[str] | None = None,
) -> CameraFrameArtifact:
    created_at = utc_now() - timedelta(minutes=10) if expired else utc_now()
    expires_at = utc_now() - timedelta(minutes=1) if expired else utc_now() + timedelta(minutes=5)
    return CameraFrameArtifact(
        capture_result_id=f"capture-{artifact_id}",
        image_artifact_id=artifact_id,
        storage_mode=CameraStorageMode.EPHEMERAL,
        created_at=created_at,
        expires_at=expires_at,
        file_path=file_path,
        image_format=image_format,
        mock_artifact=mock_artifact,
        fixture_name="c8",
        source_provenance=CAMERA_SOURCE_PROVENANCE_MOCK,
        quality_warnings=list(warnings or []),
    )


def _camera_request(stage: str = "camera_answer_ready") -> dict[str, Any]:
    return {
        "request_id": "camera-c8-request",
        "family": "camera_awareness",
        "subject": "camera still",
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
        "mockAnalysis": True,
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
        "latestArtifactId": "camera-c8-artifact",
        "lastComparisonStatus": "completed",
        "lastComparisonVisualEvidenceOnly": True,
        "lastCaptureGuidanceStatus": "guidance_ready",
        "lastCaptureGuidanceVisualEvidenceOnly": True,
    }
    status.update(overrides)
    return status


def _dirty_camera_message() -> dict[str, Any]:
    leaked_payload = "data:image/jpeg;base64,SECRET_IMAGE_PAYLOAD"
    answer = {
        "image_artifact_id": "camera-c8-artifact",
        "answer_text": f"Visual answer. {leaked_payload}",
        "concise_answer": "Visual answer.",
        "confidence": "medium",
        "evidence_summary": "Visible features only.",
        "uncertainty_reasons": [f"Provider echoed {leaked_payload}"],
        "safety_notes": ["Visual evidence only; not verification."],
        "provider_kind": "mock",
        "mock_answer": True,
        "raw_image_included": False,
        "provider_response": {"image_url": leaked_payload},
        "raw_provider_response": leaked_payload,
    }
    helper_result = {
        "title": "Engineering Helper",
        "category": "engineering_inspection",
        "helper_family": "engineering.connector_identification",
        "concise_answer": "Connector estimate.",
        "confidence_kind": "medium",
        "source_provenance": "camera_mock",
        "provider_kind": "mock",
        "visual_estimate": "JST-style connector, visually uncertain.",
        "verified_measurement": False,
        "action_executed": False,
        "raw_image_included": False,
        "provider_response": leaked_payload,
    }
    comparison_result = {
        "comparison_request_id": "camera-c8-comparison",
        "status": "completed",
        "title": "Camera Visual Comparison",
        "concise_answer": "Compared as visual evidence only.",
        "comparison_mode": "before_after",
        "confidence_kind": "medium",
        "artifact_summaries": [
            {
                "artifact_id": "camera-c8-artifact",
                "slot_id": "before",
                "label": "Before",
                "safe_preview_ref": "camera-artifact:camera-c8-artifact",
                "source_provenance": "camera_mock",
                "storage_mode": "ephemeral",
                "ready": True,
                "raw_image_included": False,
            }
        ],
        "visual_evidence_only": True,
        "verified_outcome": False,
        "action_executed": False,
        "raw_image_included": False,
        "provider_response": leaked_payload,
    }
    guidance = {
        "status": "guidance_ready",
        "title": "Retake Recommended",
        "concise_guidance": "Retake closer with steadier light.",
        "artifact_id": "camera-c8-artifact",
        "source_provenance": "camera_mock",
        "storage_mode": "ephemeral",
        "visual_evidence_only": True,
        "capture_triggered": False,
        "analysis_triggered": False,
        "upload_triggered": False,
        "raw_image_included": False,
        "provider_raw_response": leaked_payload,
    }
    return {
        "message_id": "assistant-camera-c8",
        "role": "assistant",
        "content": answer["concise_answer"],
        "created_at": "2026-04-30T23:00:00Z",
        "metadata": {
            "bearing_title": "Camera Awareness",
            "micro_response": answer["concise_answer"],
            "camera_awareness": {
                "vision_answer": answer,
                "helper_result": helper_result,
                "comparison_result": comparison_result,
                "capture_guidance": guidance,
                "provider_response": leaked_payload,
            },
            "route_state": {
                "winner": {
                    "route_family": "camera_awareness",
                    "query_shape": "camera_awareness_request",
                    "posture": "clear_winner",
                    "status": "camera_answer_ready",
                }
            },
        },
    }


class CountingCaptureProvider:
    provider_kind = "mock"
    backend_kind = "c8-fake"
    backend_available = True
    last_device_id = None

    def __init__(self) -> None:
        self.capture_attempted = False
        self.hardware_access_attempted = False
        self.get_devices_attempted = False
        self.release_count = 0
        self.active = False

    def get_devices(self):  # noqa: ANN201
        self.get_devices_attempted = True
        raise AssertionError("status/render paths must not enumerate camera devices")

    def capture_still(self, request: CameraCaptureRequest):  # noqa: ANN201
        del request
        self.capture_attempted = True
        self.hardware_access_attempted = True
        raise AssertionError("status/render paths must not capture")

    def release_device(self, device_id: str | None = None) -> None:
        del device_id
        self.release_count += 1


class CountingVisionProvider:
    provider_kind = "mock"

    def __init__(self) -> None:
        self.analysis_attempted = False
        self.network_access_attempted = False
        self.availability_checks = 0

    def get_availability(self) -> CameraVisionProviderAvailability:
        self.availability_checks += 1
        return CameraVisionProviderAvailability(provider_kind="mock", available=True)

    def analyze_image(self, question: CameraVisionQuestion, artifact: CameraFrameArtifact | None) -> CameraVisionAnswer:
        del question, artifact
        self.analysis_attempted = True
        raise AssertionError("status/render paths must not analyze")


def test_c8_evaluation_corpus_has_required_truth_and_side_effect_fields() -> None:
    required = {
        "scenario_id",
        "user_utterance",
        "context",
        "expected_route_family",
        "expected_result_state",
        "expected_policy_state",
        "expected_provider_behavior",
        "expected_artifact_behavior",
        "expected_ui_truth",
        "forbidden_claims",
        "forbidden_side_effects",
    }

    assert CAMERA_C8_SCENARIOS
    for scenario in CAMERA_C8_SCENARIOS:
        assert required <= set(scenario), scenario["scenario_id"]
        assert scenario["scenario_id"].count(".") >= 1
        assert "capture_attempted" in scenario["forbidden_side_effects"]


@pytest.mark.parametrize(
    "message",
    [
        "What is this I'm holding?",
        "Can you identify this part in front of me?",
        "What resistor value is this camera view showing?",
        "Use the camera to inspect this solder joint.",
    ],
)
def test_c8_adversarial_positive_camera_routes_still_need_explicit_capture(message: str) -> None:
    trace = PlannerV2().plan(message)

    assert trace.route_decision.selected_route_family == "camera_awareness"
    assert trace.intent_frame.target_type == "camera_frame"
    assert trace.intent_frame.extracted_entities["capture_mode"] == "single_still"
    assert trace.intent_frame.clarification_reason == "camera_capture_confirmation"


@pytest.mark.parametrize(
    "message",
    [
        "What is this?",
        "Can you read this?",
        "Does this look right?",
        "What am I looking at?",
        "Analyze this uploaded image.",
        "Read the selected text.",
        "What does this file image show?",
        "Can you read what I copied to the clipboard?",
        "How do resistor color codes work?",
        "What is JST-XH?",
        "How do I take clearer photos?",
        "How do I use my webcam?",
        "Open webcam settings.",
        "Why can't you read it?",
    ],
)
def test_c8_adversarial_source_specific_or_general_visual_requests_do_not_steal_camera(message: str) -> None:
    decision = _plan(message)

    assert _winner(decision) != "camera_awareness", message


@pytest.mark.parametrize(
    "message",
    [
        "What is on my screen?",
        "What does this popup mean?",
        "What button on my screen should I click?",
    ],
)
def test_c8_screen_specific_requests_remain_screen_not_camera(message: str) -> None:
    screen_context = {
        "visible_ui": {
            "source": "screen",
            "evidence_kind": "screen_capture",
            "label": "Visible app dialog",
        }
    }
    decision = _plan(message, context=screen_context)

    assert _winner(decision) == "screen_awareness", message


def test_c8_policy_matrix_keeps_capture_cloud_and_save_permissions_separate(temp_project_root) -> None:
    app_config = _app_config(temp_project_root)
    policy = CameraAwarenessPolicy(app_config.camera_awareness)
    request = CameraCaptureRequest(user_request_id="c8-policy", user_question="Use the camera.")

    capture = policy.evaluate_capture_request(request, user_confirmed=True)
    assert capture.allowed is True
    assert capture.cloud_analysis_allowed is False
    assert capture.storage_allowed is True

    save_blocked = policy.evaluate_capture_request(
        request,
        requested_storage_mode=CameraStorageMode.SAVED,
        user_confirmed=True,
    )
    assert save_blocked.allowed is False
    assert save_blocked.blocked_reason == "image_persistence_not_allowed"

    app_config.camera_awareness.allow_task_artifact_save = True
    save_allowed = policy.evaluate_capture_request(
        request,
        requested_storage_mode=CameraStorageMode.SAVED,
        user_confirmed=True,
    )
    assert save_allowed.allowed is True
    assert save_allowed.cloud_analysis_allowed is False

    app_config.camera_awareness.allow_cloud_vision = True
    app_config.camera_awareness.vision.allow_cloud_vision = False
    cloud_global_only = policy.evaluate_vision_request(
        cloud_analysis_requested=True,
        user_confirmed=True,
        extra={"reason_schema": "c2"},
    )
    assert cloud_global_only.allowed is False
    assert cloud_global_only.blocked_reason == "camera_cloud_analysis_disabled"

    app_config.camera_awareness.vision.allow_cloud_vision = True
    app_config.camera_awareness.vision.require_confirmation_for_cloud = True
    cloud_needs_confirmation = policy.evaluate_vision_request(
        cloud_analysis_requested=True,
        user_confirmed=None,
        extra={"reason_schema": "c2"},
    )
    assert cloud_needs_confirmation.allowed is False
    assert cloud_needs_confirmation.blocked_reason == "camera_vision_confirmation_required"
    assert cloud_needs_confirmation.permission_scope_required == "camera.cloud_vision"

    cloud_allowed = policy.evaluate_vision_request(
        cloud_analysis_requested=True,
        user_confirmed=True,
        extra={"reason_schema": "c2"},
    )
    assert cloud_allowed.allowed is True
    assert cloud_allowed.cloud_analysis_allowed is True
    assert cloud_allowed.storage_allowed is True


def test_c8_disabled_subsystem_blocks_capture_before_provider_use(temp_project_root) -> None:
    app_config = _app_config(temp_project_root)
    app_config.camera_awareness.enabled = False
    capture_provider = CountingCaptureProvider()
    vision_provider = CountingVisionProvider()
    service = CameraAwarenessSubsystem(
        app_config.camera_awareness,
        capture_provider=capture_provider,
        vision_provider=vision_provider,
    )

    flow = service.answer_mock_question(
        user_request_id="c8-disabled",
        user_question="Use the camera.",
        user_confirmed=True,
    )

    assert flow.result_state == CameraAwarenessResultState.CAMERA_CAPTURE_BLOCKED
    assert flow.policy_result.blocked_reason == "camera_awareness_disabled"
    assert capture_provider.capture_attempted is False
    assert capture_provider.hardware_access_attempted is False
    assert vision_provider.analysis_attempted is False
    assert vision_provider.network_access_attempted is False


def test_c8_status_validation_guidance_and_ui_mapping_have_no_camera_or_provider_side_effects(
    temp_project_root,
) -> None:
    app_config = _app_config(temp_project_root)
    events = EventBuffer(capacity=128)
    capture_provider = CountingCaptureProvider()
    vision_provider = CountingVisionProvider()
    service = CameraAwarenessSubsystem(
        app_config.camera_awareness,
        events=events,
        capture_provider=capture_provider,
        vision_provider=vision_provider,
    )
    artifact = service.artifacts.add(
        _artifact("camera-c8-artifact", warnings=["blur", "low_light"])
    )
    second = service.artifacts.add(_artifact("camera-c8-second"))

    status = service.status_snapshot()
    readiness = service.get_artifact_readiness(artifact.image_artifact_id)
    validation = service.validate_artifact_for_analysis(artifact.image_artifact_id)
    reuse = service.reject_if_expired_or_missing(artifact.image_artifact_id)
    guidance = service.create_capture_guidance(image_artifact_id=artifact.image_artifact_id)
    comparison_request = service.create_comparison_request(
        user_request_id="c8-compare",
        user_question="Compare these two stills.",
        artifact_ids=[artifact.image_artifact_id, second.image_artifact_id],
    )

    surface = build_camera_ghost_surface_model(
        active_request_state=_camera_request("capture_guidance_ready"),
        latest_message={
            "metadata": {
                "camera_awareness": {"capture_guidance": guidance.to_dict()},
                "route_state": {"winner": {"route_family": "camera_awareness"}},
            }
        },
        status=status,
    )
    bridge = UiBridge(app_config)
    bridge.apply_snapshot(
        {
            "status": {"camera_awareness": status},
            "active_request_state": _camera_request("capture_guidance_ready"),
            "history": [
                {
                    "role": "assistant",
                    "content": guidance.concise_guidance,
                    "metadata": {
                        "camera_awareness": {"capture_guidance": guidance.to_dict()},
                        "route_state": {"winner": {"route_family": "camera_awareness"}},
                    },
                }
            ],
        }
    )
    _ = bridge.ghostPrimaryCard
    _ = bridge.ghostActionStrip
    _ = bridge.deckPanels
    _ = bridge.routeInspector

    assert readiness.ready is True
    assert validation.ready is True
    assert reuse.ready is True
    assert guidance.capture_triggered is False
    assert comparison_request.artifact_ids == [artifact.image_artifact_id, second.image_artifact_id]
    assert surface["ghostPrimaryCard"]["cameraGhost"]["rawImageIncluded"] is False
    assert capture_provider.capture_attempted is False
    assert capture_provider.hardware_access_attempted is False
    assert capture_provider.get_devices_attempted is False
    assert capture_provider.release_count == 0
    assert vision_provider.analysis_attempted is False
    assert vision_provider.network_access_attempted is False
    assert all(
        event["event_type"]
        not in {
            "camera.capture_started",
            "camera.vision_requested",
            "camera.provider_request_constructed",
            "camera.artifact_expired",
            "camera.artifact_cleanup_retry",
        }
        for event in events.recent(limit=128)
    )


def test_c8_raw_provider_response_payloads_are_removed_from_telemetry_ghost_and_deck(temp_config) -> None:
    leaked_payload = "data:image/png;base64,SECRET_IMAGE_PAYLOAD"
    events = EventBuffer(capacity=8)
    emitter = CameraTelemetryEmitter(events)

    emitter.emit(
        "camera.c8.payload_sweep",
        "Camera payload sweep.",
        payload={
            "provider_response": {"image_url": leaked_payload},
            "raw_provider_response": leaked_payload,
            "unbounded_provider_response": {"api_key": "sk-test-secret"},
            "safe": {"artifact_id": "camera-c8-artifact"},
        },
    )
    telemetry_payload = events.recent(limit=1)[0]["payload"]
    assert telemetry_payload["safe"]["artifact_id"] == "camera-c8-artifact"
    assert _contains_forbidden_payload(telemetry_payload) is False

    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "history": [_dirty_camera_message()],
            "active_request_state": _camera_request(),
            "status": {"camera_awareness": _camera_status(provider_response=leaked_payload)},
        }
    )

    ui_payload = {
        "ghostPrimaryCard": bridge.ghostPrimaryCard,
        "ghostActionStrip": bridge.ghostActionStrip,
        "requestComposer": bridge.requestComposer,
        "routeInspector": bridge.routeInspector,
        "deckPanels": bridge.deckPanels,
        "deckPanelCatalog": bridge.deckPanelCatalog,
    }
    assert _contains_forbidden_payload(ui_payload) is False


def test_c8_artifact_cleanup_is_truthful_and_idempotent(tmp_path) -> None:
    artifact_path = tmp_path / "camera-c8-cleanup.jpg"
    artifact_path.write_bytes(b"fake-jpg")
    artifact = _artifact(
        "camera-c8-cleanup",
        file_path=str(artifact_path),
        image_format="jpg",
        mock_artifact=False,
    )
    store = CameraArtifactStore()
    store.add(artifact)

    assert artifact_path.exists()
    assert store.expire(artifact.image_artifact_id) is True
    cleanup = store.last_cleanup_result
    assert cleanup is not None
    assert cleanup.cleanup_attempted is True
    assert cleanup.cleanup_succeeded is True
    assert cleanup.cleanup_failed is False
    assert cleanup.cleanup_pending is False
    assert artifact_path.exists() is False

    retry = store.retry_cleanup(artifact.image_artifact_id)
    assert retry.cleanup_attempted is False
    assert retry.cleanup_succeeded is True
    assert retry.cleanup_failed is False
    assert retry.cleanup_pending is False


def test_c8_unknown_provider_fails_closed_without_network_or_fake_success(temp_project_root) -> None:
    app_config = _app_config(temp_project_root)
    app_config.camera_awareness.vision.provider = "mystery_cloud"
    service = CameraAwarenessSubsystem(app_config.camera_awareness, events=EventBuffer(capacity=32))
    artifact = service.artifacts.add(_artifact("camera-c8-provider"))

    flow = service.analyze_artifact_with_selected_provider(
        image_artifact_id=artifact.image_artifact_id,
        user_question="What is this?",
        user_request_id="c8-provider",
        cloud_analysis_confirmed=True,
    )

    assert service.vision_provider.provider_kind == "unavailable"
    assert flow.result_state == CameraAwarenessResultState.CAMERA_ANALYSIS_FAILED
    assert flow.vision_answer.error_code == "unknown_vision_provider"
    assert flow.vision_answer.cloud_upload_performed is False
    assert flow.vision_answer.cloud_analysis_performed is False
    assert flow.vision_answer.raw_image_included is False
    assert getattr(service.vision_provider, "network_access_attempted", False) is False


def test_c8_helper_comparison_and_guidance_models_force_visual_evidence_boundaries() -> None:
    helper = CameraEngineeringHelperResult(
        vision_answer_id="answer-c8",
        artifact_id="artifact-c8",
        helper_family=CameraHelperFamily.ENGINEERING_RESISTOR_COLOR_BANDS,
        title="Resistor Estimate",
        concise_answer="Visual estimate only.",
        confidence_kind=CameraConfidenceLevel.MEDIUM,
        source_provenance="camera_mock",
        provider_kind="mock",
        category=CameraHelperCategory.ENGINEERING_INSPECTION,
        visual_estimate="10 kOhm visual estimate",
        suggested_measurements=["Confirm with a multimeter."],
        verified_measurement=True,
        action_executed=True,
        trust_approved=True,
        task_mutation_performed=True,
        raw_image_included=True,
    )
    comparison = CameraComparisonResult(
        comparison_request_id="comparison-c8",
        status=CameraComparisonStatus.COMPLETED,
        title="Before/After Visual Comparison",
        concise_answer="The after still appears cleaner; this is visual evidence only.",
        comparison_mode=CameraComparisonMode.BEFORE_AFTER,
        artifact_summaries=[
            CameraComparisonArtifactSummary(
                artifact_id="artifact-c8",
                slot_id="after",
                label="After",
                ready=True,
                artifact_exists=True,
                artifact_readable=True,
                source_provenance="camera_mock",
            )
        ],
        confidence_kind=CameraConfidenceLevel.MEDIUM,
        visual_evidence_only=False,
        verified_outcome=True,
        action_executed=True,
        trust_approved=True,
        task_mutation_performed=True,
        raw_image_included=True,
    )
    guidance = CameraCaptureGuidanceResult(
        status=CameraCaptureGuidanceStatus.GUIDANCE_READY,
        title="Retake Recommended",
        concise_guidance="Retake closer with steadier light.",
        artifact_id="artifact-c8",
        source_provenance="camera_mock",
        capture_triggered=True,
        analysis_triggered=True,
        upload_triggered=True,
        save_triggered=True,
        cleanup_triggered=True,
        memory_write_triggered=True,
        raw_image_included=True,
        verified_measurement=True,
        verified_outcome=True,
        action_executed=True,
        trust_approved=True,
        task_mutation_performed=True,
    )

    assert helper.verified_measurement is False
    assert helper.action_executed is False
    assert helper.trust_approved is False
    assert helper.task_mutation_performed is False
    assert helper.raw_image_included is False
    assert comparison.visual_evidence_only is True
    assert comparison.verified_outcome is False
    assert comparison.action_executed is False
    assert comparison.trust_approved is False
    assert comparison.task_mutation_performed is False
    assert comparison.raw_image_included is False
    assert guidance.visual_evidence_only is True
    assert guidance.capture_triggered is False
    assert guidance.analysis_triggered is False
    assert guidance.upload_triggered is False
    assert guidance.save_triggered is False
    assert guidance.cleanup_triggered is False
    assert guidance.memory_write_triggered is False
    assert guidance.verified_measurement is False
    assert guidance.verified_outcome is False
    assert guidance.action_executed is False
    assert guidance.trust_approved is False
    assert guidance.task_mutation_performed is False
    assert guidance.raw_image_included is False


def test_c8_helper_registry_stays_extensible_and_engineering_does_not_own_core_pipeline() -> None:
    @dataclass(slots=True)
    class FutureHelper:
        category: CameraHelperCategory = CameraHelperCategory.UNKNOWN

        def classify(
            self,
            *,
            user_question: str,
            vision_answer: CameraVisionAnswer | None,
        ):  # noqa: ANN201
            del user_question, vision_answer
            return build_default_camera_helper_registry().classify(
                user_question="not an engineering visual helper",
                vision_answer=None,
            )

        def build_result(
            self,
            *,
            user_question: str,
            vision_answer: CameraVisionAnswer,
        ):  # noqa: ANN201
            del user_question, vision_answer
            return None

    registry = build_default_camera_helper_registry()
    extended = type(registry)(helpers=(FutureHelper(), *registry.helpers))

    educational = extended.classify(
        user_question="How do resistor color codes work?",
        vision_answer=None,
    )
    visual = extended.classify(
        user_question="What resistor value is this?",
        vision_answer=None,
    )

    assert len(extended.helpers) == len(registry.helpers) + 1
    assert educational.applicable is False
    assert visual.applicable is True
    assert visual.category == CameraHelperCategory.ENGINEERING_INSPECTION


def test_c8_screen_general_and_camera_route_regression_slice() -> None:
    expectations = {
        "What is this I'm holding?": "camera_awareness",
        "Can you read this?": "not_camera_awareness",
        "What is on my screen?": "screen_awareness",
        "How do resistor color codes work?": "not_camera_awareness",
        "Compare these two camera stills.": "camera_awareness",
        "How should I retake this camera still?": "camera_awareness",
    }

    for message, expected in expectations.items():
        decision = _plan(message)
        winner = _winner(decision)
        if expected == "not_camera_awareness":
            assert winner != "camera_awareness", message
        else:
            assert winner == expected, message
