from __future__ import annotations

from datetime import timedelta

import pytest

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CameraAwarenessSubsystem,
    CameraAwarenessResultState,
    CameraCaptureRequest,
    CameraCaptureSource,
    CameraCaptureStatus,
    CameraDeviceStatus,
    CameraPermissionState,
    CameraStorageMode,
    LocalCameraCaptureProvider,
    build_camera_awareness_subsystem,
)
from stormhelm.core.container import build_container
from stormhelm.core.events import EventBuffer
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2
from stormhelm.core.orchestrator.route_triage import FastRouteClassifier


def _enabled_camera_config(temp_project_root):
    config = load_config(project_root=temp_project_root, env={})
    camera = config.camera_awareness
    camera.enabled = True
    camera.privacy.confirm_before_capture = False
    camera.dev.mock_capture_enabled = True
    camera.dev.mock_vision_enabled = True
    camera.dev.mock_image_fixture = "resistor"
    return camera


def _plan(message: str, *, active_context: dict[str, object] | None = None):
    active_context = active_context or {}
    return DeterministicPlanner().plan(
        message,
        session_id="camera-awareness-c01",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=active_context,
        active_posture={},
        active_request_state={},
        active_context=active_context,
        recent_tool_results=[],
    )


def _winner(decision) -> str:  # noqa: ANN001
    return decision.route_state.to_dict()["winner"]["route_family"]


class UnavailableLocalBackend:
    backend_kind = "fake_unavailable_local"

    def is_available(self) -> bool:
        return False

    def get_devices(self, *, timeout_seconds: float) -> list[CameraDeviceStatus]:
        del timeout_seconds
        return [
            CameraDeviceStatus(
                device_id="local-unavailable",
                display_name="Local camera unavailable",
                provider=self.backend_kind,
                available=False,
                permission_state=CameraPermissionState.UNAVAILABLE,
                mock_device=False,
                source_provenance="camera_unavailable",
                error_code="local_capture_backend_unavailable",
            )
        ]

    def capture_still(self, **kwargs):  # noqa: ANN003
        raise AssertionError("unavailable local backend should fail before capture")


@pytest.mark.parametrize(
    "message",
    [
        "What is this I'm holding?",
        "Look at this with the camera.",
        "Can you identify this part I'm holding?",
    ],
)
def test_c01_obvious_camera_requests_route_to_camera_awareness(message: str) -> None:
    trace = PlannerV2().plan(message)
    decision = _plan(message)
    triage = FastRouteClassifier().classify(message)

    assert trace.route_decision.selected_route_family == "camera_awareness"
    assert trace.intent_frame.extracted_entities["source_provenance"] == "camera_request"
    assert _winner(decision) == "camera_awareness"
    assert decision.active_request_state["source_provenance"] == "camera_request"
    assert triage.likely_route_families == ("camera_awareness",)
    assert triage.route_hints["source_provenance"] == "camera_request"
    assert triage.provider_fallback_eligible is False


@pytest.mark.parametrize(
    "message",
    [
        "What is this?",
        "Can you read this?",
        "What am I looking at?",
    ],
)
def test_c01_ambiguous_visual_requests_do_not_blindly_route_to_camera(message: str) -> None:
    trace = PlannerV2().plan(message)
    decision = _plan(message)
    triage = FastRouteClassifier().classify(message)

    assert trace.route_decision.selected_route_family != "camera_awareness"
    assert _winner(decision) != "camera_awareness"
    assert triage.likely_route_families != ("camera_awareness",)
    assert decision.active_request_state.get("source_provenance") != "camera_request"


@pytest.mark.parametrize(
    "message",
    [
        "What is on my screen?",
        "What does this popup mean?",
        "What window am I looking at?",
    ],
)
def test_c01_screen_requests_keep_screen_authority(message: str) -> None:
    screen_context = {
        "visible_ui": {
            "label": "Visible installer error",
            "source": "screen",
            "evidence_kind": "screen_capture",
        }
    }

    decision = _plan(message, active_context=screen_context)

    assert _winner(decision) == "screen_awareness"
    assert decision.active_request_state.get("source_provenance") != "camera_request"


@pytest.mark.parametrize(
    "message",
    [
        "What is a JST connector?",
        "How do resistor color codes work?",
        "Explain cold solder joints.",
    ],
)
def test_c01_general_knowledge_does_not_trigger_camera_awareness(message: str) -> None:
    trace = PlannerV2().plan(message)
    decision = _plan(message)
    triage = FastRouteClassifier().classify(message)

    assert trace.route_decision.selected_route_family != "camera_awareness"
    assert _winner(decision) != "camera_awareness"
    assert triage.likely_route_families != ("camera_awareness",)


@pytest.mark.parametrize(
    ("message", "active_context", "expected_source"),
    [
        (
            "Can you read this?",
            {"clipboard": {"value": "R1 10k", "kind": "text", "source": "clipboard"}},
            "clipboard",
        ),
        (
            "Can you read this?",
            {"selection": {"value": "JST-XH connector", "kind": "selected_text", "source": "selection"}},
            "selection",
        ),
        (
            "What is this uploaded image?",
            {"uploaded_image": {"path": "part.png", "source": "uploaded_image", "evidence_kind": "uploaded_image"}},
            "uploaded_image",
        ),
        (
            "What does this file show?",
            {"file": {"path": "C:/tmp/part.png", "source": "file", "evidence_kind": "file"}},
            "file",
        ),
    ],
)
def test_c01_non_camera_sources_are_not_mislabeled_as_camera_provenance(
    message: str,
    active_context: dict[str, object],
    expected_source: str,
) -> None:
    decision = _plan(message, active_context=active_context)
    route_state = decision.route_state.to_dict()

    assert _winner(decision) != "camera_awareness"
    assert decision.active_request_state.get("source_provenance") != "camera_request"
    assert expected_source != "camera_request"
    assert route_state["winner"]["route_family"] != "camera_awareness"


def test_c01_local_capture_provider_fails_closed_without_hardware(temp_project_root) -> None:
    camera = _enabled_camera_config(temp_project_root)
    camera.capture.provider = "local"
    events = EventBuffer(capacity=32)
    provider = LocalCameraCaptureProvider(camera, backend=UnavailableLocalBackend())
    service = CameraAwarenessSubsystem(camera, events=events, capture_provider=provider)

    flow = service.answer_mock_question(
        user_question="Look at this with the camera.",
        user_request_id="c01-local-provider",
        session_id="session-c01",
    )

    assert service.capture_provider.provider_kind == "local"
    assert service.capture_provider.backend_available is False
    assert service.capture_provider.hardware_access_attempted is False
    assert service.capture_provider.capture_attempted is True
    assert flow.capture_result.status == CameraCaptureStatus.BLOCKED
    assert flow.capture_result.error_code == "local_capture_backend_unavailable"
    assert flow.capture_result.real_camera_used is False
    assert flow.capture_result.mock_capture is False
    assert flow.trace.provider_kind == "local"
    assert flow.trace.source_provenance == "camera_unavailable"
    assert flow.trace.cloud_upload_performed is False
    assert flow.trace.raw_image_included is False
    assert flow.vision_answer.provenance["reason"] == "local_capture_backend_unavailable"

    failed_payload = next(
        event["payload"]
        for event in events.recent(limit=16)
        if event["event_type"] == "camera.capture_failed"
    )
    assert failed_payload["provider_kind"] == "local"
    assert failed_payload["source_provenance"] == "camera_unavailable"
    assert failed_payload["cloud_upload_performed"] is False
    assert failed_payload["raw_image_included"] is False


def test_c01_unknown_capture_provider_fails_closed_truthfully(temp_project_root) -> None:
    camera = _enabled_camera_config(temp_project_root)
    camera.capture.provider = "mysterycam"
    service = build_camera_awareness_subsystem(camera)

    flow = service.answer_mock_question(
        user_question="Look at this with the camera.",
        user_request_id="c01-unknown-provider",
        session_id="session-c01",
    )
    snapshot = service.status_snapshot()

    assert service.capture_provider.provider_kind == "unavailable"
    assert service.capture_provider.hardware_access_attempted is False
    assert flow.capture_result.status == CameraCaptureStatus.BLOCKED
    assert flow.capture_result.error_code == "unknown_capture_provider"
    assert snapshot["configuredCaptureProvider"] == "mysterycam"
    assert snapshot["providerUnavailableReason"] == "unknown_capture_provider"
    assert snapshot["providerKind"] == "unavailable"
    assert snapshot["realCameraUsed"] is False
    assert snapshot["mockCapture"] is False


def test_c01_disabled_subsystem_blocks_before_provider_capture(temp_project_root) -> None:
    camera = load_config(project_root=temp_project_root, env={}).camera_awareness
    camera.enabled = False
    camera.capture.provider = "local"
    camera.privacy.confirm_before_capture = False
    service = build_camera_awareness_subsystem(camera)

    flow = service.answer_mock_question(
        user_question="Look at this with the camera.",
        user_request_id="c01-disabled",
        session_id="session-c01",
    )

    assert flow.policy_result.allowed is False
    assert flow.policy_result.blocked_reason == "camera_awareness_disabled"
    assert flow.capture_result.status == CameraCaptureStatus.BLOCKED
    assert flow.capture_result.error_code == "camera_awareness_disabled"
    assert service.capture_provider.capture_attempted is False
    assert service.capture_provider.hardware_access_attempted is False
    assert flow.trace.source_provenance == "camera_policy"
    assert flow.trace.provider_kind == "policy"


def test_c01_artifact_expiry_uses_deterministic_clock_and_followup_fails_truthfully(temp_project_root) -> None:
    camera = _enabled_camera_config(temp_project_root)
    camera.auto_discard_after_seconds = 3
    service = build_camera_awareness_subsystem(camera)
    flow = service.answer_mock_question(
        user_question="What connector is this?",
        user_request_id="c01-expiry",
        session_id="session-c01",
    )

    artifact = flow.artifact
    assert artifact is not None
    assert artifact.storage_mode == CameraStorageMode.EPHEMERAL
    assert artifact.is_expired(at=artifact.created_at + timedelta(seconds=2)) is False
    assert service.resolve_artifact_for_followup(
        artifact.image_artifact_id,
        at=artifact.created_at + timedelta(seconds=2),
    ).artifact is not None

    expired = service.resolve_artifact_for_followup(
        artifact.image_artifact_id,
        at=artifact.created_at + timedelta(seconds=3),
    )
    snapshot = service.status_snapshot()

    assert expired.artifact is None
    assert expired.result_state == CameraAwarenessResultState.CAMERA_ARTIFACT_EXPIRED
    assert "no longer have" in expired.message.lower()
    assert snapshot["lastArtifactExpired"] is True
    assert snapshot["lastArtifactFresh"] is False
    assert snapshot["lastArtifactStorageMode"] == "ephemeral"
    assert snapshot["storageMode"] == "ephemeral"


def test_c01_background_capture_policy_is_fail_closed(temp_project_root) -> None:
    camera = _enabled_camera_config(temp_project_root)
    policy_result = service_policy(camera).evaluate_capture_request(
        CameraCaptureRequest(
            user_request_id="c01-background",
            session_id="session-c01",
            source=CameraCaptureSource.USER_REQUEST,
            reason="background capture probe",
            user_question="Watch the camera in the background.",
            background_capture=True,
        )
    )

    assert camera.allow_background_capture is False
    assert policy_result.allowed is False
    assert policy_result.blocked_reason == "background_capture_not_allowed"
    assert policy_result.background_capture_allowed is False
    assert policy_result.cloud_analysis_allowed is False


def test_c01_status_and_container_payloads_are_truthful_without_capture(temp_config) -> None:
    temp_config.camera_awareness.enabled = True
    temp_config.camera_awareness.privacy.confirm_before_capture = False
    temp_config.camera_awareness.dev.mock_capture_enabled = True
    temp_config.camera_awareness.dev.mock_vision_enabled = True
    container = build_container(temp_config)

    assert container.camera_awareness.capture_provider.capture_attempted is False
    snapshot = container.status_snapshot_fast()
    camera = snapshot["camera_awareness"]

    assert container.camera_awareness.capture_provider.capture_attempted is False
    assert camera["enabled"] is True
    assert camera["providerKind"] == "mock"
    assert camera["mockMode"] is True
    assert camera["mockCapture"] is False
    assert camera["realCameraUsed"] is False
    assert camera["cloudUploadPerformed"] is False
    assert camera["rawImageIncluded"] is False
    assert camera["storageMode"] == "ephemeral"
    assert camera["lastArtifactExpired"] is False
    assert camera["lastArtifactFresh"] is False
    assert camera["backgroundCaptureAllowed"] is False


def test_c01_mock_flow_status_and_telemetry_preserve_provenance_truth(temp_project_root) -> None:
    events = EventBuffer(capacity=32)
    service = build_camera_awareness_subsystem(
        _enabled_camera_config(temp_project_root),
        events=events,
    )

    flow = service.answer_mock_question(
        user_question="What resistor value is this?",
        user_request_id="c01-mock-flow",
        session_id="session-c01",
        source=CameraCaptureSource.TEST,
    )
    snapshot = service.status_snapshot()
    answer_payload = next(
        event["payload"]
        for event in events.recent(limit=16)
        if event["event_type"] == "camera.answer_ready"
    )

    assert flow.capture_result.mock_capture is True
    assert flow.capture_result.real_camera_used is False
    assert flow.trace.source_provenance == "camera_mock"
    assert flow.trace.provider_kind == "mock"
    assert flow.trace.storage_mode == CameraStorageMode.EPHEMERAL
    assert flow.trace.cloud_upload_performed is False
    assert flow.trace.raw_image_included is False
    assert snapshot["mockCapture"] is True
    assert snapshot["realCameraUsed"] is False
    assert snapshot["cloudUploadPerformed"] is False
    assert snapshot["rawImageIncluded"] is False
    assert snapshot["storageMode"] == "ephemeral"
    assert snapshot["lastArtifactFresh"] is True
    assert snapshot["lastArtifactExpired"] is False
    assert answer_payload["source_provenance"] == "camera_mock"
    assert answer_payload["storage_mode"] == "ephemeral"
    assert answer_payload["cloud_upload_performed"] is False
    assert answer_payload["raw_image_included"] is False
    assert "raw_image" not in answer_payload


def service_policy(camera):  # noqa: ANN001
    return build_camera_awareness_subsystem(camera).policy
