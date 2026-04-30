from __future__ import annotations

from datetime import timedelta

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CameraAnalysisMode,
    CameraAwarenessPolicy,
    CameraAwarenessResultState,
    CameraCaptureRequest,
    CameraCaptureSource,
    CameraCaptureStatus,
    CameraConfidenceLevel,
    CameraPermissionState,
    CameraStorageMode,
    CameraVisionQuestion,
    MockCameraCaptureProvider,
    MockVisionAnalysisProvider,
    UnavailableCameraCaptureProvider,
    UnavailableVisionAnalysisProvider,
    build_camera_awareness_subsystem,
)
from stormhelm.core.events import EventBuffer


def _enabled_camera_config(temp_project_root):
    config = load_config(project_root=temp_project_root, env={})
    config.camera_awareness.enabled = True
    config.camera_awareness.privacy.confirm_before_capture = False
    config.camera_awareness.dev.mock_capture_enabled = True
    config.camera_awareness.dev.mock_vision_enabled = True
    config.camera_awareness.dev.mock_image_fixture = "resistor"
    return config.camera_awareness


def test_camera_awareness_config_defaults_are_disabled_and_private(temp_project_root) -> None:
    config = load_config(project_root=temp_project_root, env={})

    camera = config.camera_awareness

    assert camera.enabled is False
    assert camera.default_capture_mode == "single_still"
    assert camera.default_storage_mode == "ephemeral"
    assert camera.allow_cloud_vision is False
    assert camera.allow_background_capture is False
    assert camera.allow_task_artifact_save is False
    assert camera.allow_session_permission is False
    assert camera.capture.provider == "mock"
    assert camera.vision.provider == "mock"
    assert camera.vision.model == "mock-vision"
    assert camera.privacy.confirm_before_capture is True
    assert camera.privacy.persist_images_by_default is False
    assert camera.dev.save_debug_images is False


def test_camera_policy_blocks_disabled_background_cloud_and_persistence(temp_project_root) -> None:
    config = load_config(project_root=temp_project_root, env={}).camera_awareness
    policy = CameraAwarenessPolicy(config)
    request = CameraCaptureRequest(
        user_request_id="user-1",
        session_id="session-1",
        source=CameraCaptureSource.USER_REQUEST,
        reason="identify held object",
        user_question="What am I holding?",
    )

    disabled = policy.evaluate_capture_request(request)

    assert disabled.allowed is False
    assert disabled.blocked_reason == "camera_awareness_disabled"
    assert disabled.background_capture_allowed is False
    assert disabled.cloud_analysis_allowed is False

    config.enabled = True
    config.privacy.confirm_before_capture = False
    background = policy.evaluate_capture_request(
        CameraCaptureRequest(
            user_request_id="user-2",
            session_id="session-1",
            source=CameraCaptureSource.USER_REQUEST,
            reason="background capture probe",
            user_question="Watch the camera in the background.",
            background_capture=True,
        )
    )
    persistent = policy.evaluate_capture_request(request, requested_storage_mode=CameraStorageMode.SAVED)
    cloud = policy.evaluate_vision_request(cloud_analysis_requested=True)

    assert background.allowed is False
    assert background.blocked_reason == "background_capture_not_allowed"
    assert persistent.storage_allowed is False
    assert persistent.blocked_reason == "image_persistence_not_allowed"
    assert cloud.allowed is False
    assert cloud.blocked_reason == "cloud_vision_not_allowed"


def test_mock_capture_provider_creates_ephemeral_provenance_without_hardware(temp_project_root) -> None:
    config = _enabled_camera_config(temp_project_root)
    provider = MockCameraCaptureProvider(config)
    request = CameraCaptureRequest(
        user_request_id="user-3",
        session_id="session-1",
        source=CameraCaptureSource.TEST,
        reason="identify test fixture",
        user_question="What resistor value is this?",
    )

    devices = provider.get_devices()
    result, artifact = provider.capture_still(request)

    assert devices[0].device_id == "mock_camera_0"
    assert devices[0].permission_state == CameraPermissionState.GRANTED
    assert devices[0].mock_device is True
    assert result.status == CameraCaptureStatus.CAPTURED
    assert result.image_artifact_id == artifact.image_artifact_id
    assert result.mock_capture is True
    assert result.real_camera_used is False
    assert result.raw_image_persisted is False
    assert result.cloud_upload_performed is False
    assert artifact.storage_mode == CameraStorageMode.EPHEMERAL
    assert artifact.file_path is None
    assert artifact.mock_artifact is True
    assert artifact.source_provenance == "camera_mock"
    assert provider.hardware_access_attempted is False


def test_mock_vision_provider_returns_deterministic_mock_answer(temp_project_root) -> None:
    config = _enabled_camera_config(temp_project_root)
    capture_provider = MockCameraCaptureProvider(config)
    _, artifact = capture_provider.capture_still(
        CameraCaptureRequest(
            user_request_id="user-4",
            session_id="session-1",
            source=CameraCaptureSource.TEST,
            reason="analyze resistor fixture",
            user_question="What resistor value is this?",
        )
    )
    question = CameraVisionQuestion(
        image_artifact_id=artifact.image_artifact_id,
        user_question="What resistor value is this?",
        normalized_question="what resistor value is this",
        analysis_mode=CameraAnalysisMode.IDENTIFY,
        provider="mock",
        model="mock-vision",
        cloud_analysis_allowed=False,
        mock_analysis=True,
    )

    answer = MockVisionAnalysisProvider(config).analyze_image(question, artifact)

    assert answer.mock_answer is True
    assert answer.confidence == CameraConfidenceLevel.MEDIUM
    assert "resistor" in answer.concise_answer.lower()
    assert answer.provenance["source"] == "camera_mock"
    assert answer.provenance["cloud_upload_performed"] is False
    assert answer.cloud_upload_performed is False


def test_unavailable_providers_return_typed_unavailable_results(temp_project_root) -> None:
    config = _enabled_camera_config(temp_project_root)
    request = CameraCaptureRequest(
        user_request_id="user-5",
        session_id="session-1",
        source=CameraCaptureSource.TEST,
        reason="provider unavailable test",
        user_question="Look at this with the camera.",
    )

    capture_provider = UnavailableCameraCaptureProvider(reason="real_capture_not_implemented")
    result, artifact = capture_provider.capture_still(request)
    vision_answer = UnavailableVisionAnalysisProvider(reason="openai_vision_not_implemented").analyze_image(
        CameraVisionQuestion(
            image_artifact_id="missing-artifact",
            user_question="What is this?",
            normalized_question="what is this",
            analysis_mode=CameraAnalysisMode.UNKNOWN,
            provider="unavailable",
            model="unavailable",
        ),
        artifact,
    )

    assert result.status == CameraCaptureStatus.BLOCKED
    assert result.error_code == "real_capture_not_implemented"
    assert artifact is None
    assert vision_answer.confidence == CameraConfidenceLevel.INSUFFICIENT
    assert vision_answer.result_state == CameraAwarenessResultState.CAMERA_ANALYSIS_FAILED
    assert vision_answer.mock_answer is False
    assert "unavailable" in vision_answer.answer_text.lower()


def test_camera_awareness_service_runs_full_mock_flow_with_trace_and_safe_events(temp_project_root) -> None:
    events = EventBuffer(capacity=32)
    service = build_camera_awareness_subsystem(
        _enabled_camera_config(temp_project_root),
        events=events,
    )

    flow = service.answer_mock_question(
        user_question="What resistor value is this?",
        user_request_id="user-6",
        session_id="session-1",
        source=CameraCaptureSource.TEST,
    )

    assert flow.result_state == CameraAwarenessResultState.CAMERA_ANSWER_READY
    assert flow.capture_request.background_capture is False
    assert flow.policy_result.allowed is True
    assert flow.capture_result.mock_capture is True
    assert flow.capture_result.real_camera_used is False
    assert flow.artifact.storage_mode == CameraStorageMode.EPHEMERAL
    assert flow.vision_answer.mock_answer is True
    assert flow.trace.route_family == "camera_awareness"
    assert flow.trace.capture_request_id == flow.capture_request.capture_request_id
    assert flow.trace.image_artifact_id == flow.artifact.image_artifact_id
    assert flow.trace.cloud_upload_performed is False
    assert flow.trace.raw_image_included is False

    recent_events = events.recent(limit=16)
    event_payloads = [event["payload"] for event in recent_events]
    event_types = [event["event_type"] for event in recent_events]
    assert "camera.capture_requested" in event_types
    assert "camera.answer_ready" in event_types
    assert all("raw_image" not in payload for payload in event_payloads)
    assert all(payload.get("cloud_upload_performed") is not True for payload in event_payloads)
    assert all(payload.get("real_camera_used") is not True for payload in event_payloads)


def test_ephemeral_artifact_expires_and_followup_binding_fails_truthfully(temp_project_root) -> None:
    service = build_camera_awareness_subsystem(_enabled_camera_config(temp_project_root))
    flow = service.answer_mock_question(
        user_question="What connector is this?",
        user_request_id="user-7",
        session_id="session-1",
        source=CameraCaptureSource.TEST,
    )

    artifact = service.get_recent_camera_artifact()
    assert artifact is not None
    assert artifact.image_artifact_id == flow.artifact.image_artifact_id
    assert artifact.is_expired() is False

    service.expire_artifact(flow.artifact.image_artifact_id)

    expired = service.resolve_artifact_for_followup(flow.artifact.image_artifact_id)
    assert expired.artifact is None
    assert expired.result_state == CameraAwarenessResultState.CAMERA_ARTIFACT_EXPIRED
    assert "no longer have" in expired.message.lower()

    old_time = flow.artifact.created_at + timedelta(seconds=configured_seconds(service) + 1)
    assert flow.artifact.is_expired(at=old_time) is True


def test_status_snapshot_is_bridge_ready_without_claiming_live_camera(temp_project_root) -> None:
    service = build_camera_awareness_subsystem(_enabled_camera_config(temp_project_root))

    snapshot = service.status_snapshot()

    assert snapshot["enabled"] is True
    assert snapshot["route_family"] == "camera_awareness"
    assert snapshot["providerKind"] == "mock"
    assert snapshot["mockMode"] is True
    assert snapshot["active"] is False
    assert snapshot["realCameraImplemented"] is False
    assert snapshot["openaiVisionImplemented"] is False
    assert snapshot["cloudUploadPerformed"] is False


def configured_seconds(service) -> int:  # noqa: ANN001
    return int(service.config.auto_discard_after_seconds)
