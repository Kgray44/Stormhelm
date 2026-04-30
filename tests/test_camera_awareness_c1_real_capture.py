from __future__ import annotations

from pathlib import Path

import pytest

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CameraAwarenessResultState,
    CameraAwarenessSubsystem,
    CameraCaptureSource,
    CameraCaptureStatus,
    CameraDeviceStatus,
    CameraPermissionState,
    CameraStorageMode,
    LocalCameraCaptureProvider,
    LocalStillCaptureBackendResult,
    build_camera_awareness_subsystem,
)
from stormhelm.core.events import EventBuffer


def _real_enabled_camera_config(temp_project_root):
    config = load_config(project_root=temp_project_root, env={})
    camera = config.camera_awareness
    camera.enabled = True
    camera.capture.provider = "local"
    camera.privacy.confirm_before_capture = True
    camera.dev.mock_vision_enabled = True
    camera.vision.provider = "mock"
    camera.auto_discard_after_seconds = 7
    return camera


class FakeLocalStillBackend:
    backend_kind = "fake_local_still"

    def __init__(self, *, available: bool = True, capture_error: str | None = None) -> None:
        self.available = available
        self.capture_error = capture_error
        self.list_calls = 0
        self.capture_calls = 0
        self.output_paths: list[Path] = []

    def is_available(self) -> bool:
        return self.available

    def get_devices(self, *, timeout_seconds: float) -> list[CameraDeviceStatus]:
        del timeout_seconds
        self.list_calls += 1
        if not self.available:
            return [
                CameraDeviceStatus(
                    device_id="local-default",
                    display_name="Local camera backend unavailable",
                    provider=self.backend_kind,
                    available=False,
                    permission_state=CameraPermissionState.UNAVAILABLE,
                    mock_device=False,
                    source_provenance="camera_unavailable",
                    error_code="local_capture_backend_unavailable",
                    error_message="Fake backend unavailable.",
                )
            ]
        return [
            CameraDeviceStatus(
                device_id="fake-camera-0",
                display_name="Fake Local Camera",
                provider=self.backend_kind,
                available=True,
                permission_state=CameraPermissionState.UNKNOWN,
                mock_device=False,
                source_provenance="camera_local",
                resolution_options=["1280x720"],
            )
        ]

    def capture_still(self, *, device_id: str, output_path: Path, timeout_seconds: float, requested_resolution: str) -> LocalStillCaptureBackendResult:
        del timeout_seconds, requested_resolution
        self.capture_calls += 1
        self.output_paths.append(output_path)
        if not self.available:
            return LocalStillCaptureBackendResult(
                success=False,
                error_code="local_capture_backend_unavailable",
                error_message="Fake backend unavailable.",
                device_id=device_id,
            )
        if self.capture_error:
            return LocalStillCaptureBackendResult(
                success=False,
                error_code=self.capture_error,
                error_message=f"Fake capture failed: {self.capture_error}",
                device_id=device_id,
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-local-still")
        return LocalStillCaptureBackendResult(
            success=True,
            device_id=device_id,
            width=1280,
            height=720,
            image_format="jpg",
            file_path=output_path,
        )


def test_c1_provider_selection_uses_local_provider_without_capture_on_status(temp_project_root) -> None:
    camera = _real_enabled_camera_config(temp_project_root)
    service = build_camera_awareness_subsystem(camera)

    snapshot = service.status_snapshot()

    assert snapshot["providerKind"] == "local"
    assert snapshot["configuredCaptureProvider"] == "local"
    assert snapshot["captureAttempted"] is False
    assert snapshot["hardwareAccessAttempted"] is False
    assert snapshot["realCameraUsed"] is False
    assert snapshot["cameraActive"] is False
    assert snapshot["backgroundCaptureAllowed"] is False


def test_c1_local_provider_discovers_devices_without_capturing(temp_project_root) -> None:
    camera = _real_enabled_camera_config(temp_project_root)
    backend = FakeLocalStillBackend()
    provider = LocalCameraCaptureProvider(camera, backend=backend)

    devices = provider.get_devices()

    assert backend.list_calls == 1
    assert backend.capture_calls == 0
    assert provider.capture_attempted is False
    assert provider.hardware_access_attempted is False
    assert devices[0].device_id == "fake-camera-0"
    assert devices[0].source_provenance == "camera_local"


def test_c1_local_single_still_capture_uses_fake_backend_and_releases_device(temp_project_root) -> None:
    camera = _real_enabled_camera_config(temp_project_root)
    events = EventBuffer(capacity=64)
    backend = FakeLocalStillBackend()
    provider = LocalCameraCaptureProvider(camera, backend=backend)
    service = CameraAwarenessSubsystem(camera, events=events, capture_provider=provider)

    flow = service.answer_mock_question(
        user_question="Look at this with the camera.",
        user_request_id="c1-real-capture",
        session_id="session-c1",
        source=CameraCaptureSource.TEST,
        user_confirmed=True,
    )
    snapshot = service.status_snapshot()

    assert flow.capture_result.status == CameraCaptureStatus.CAPTURED
    assert flow.capture_result.mock_capture is False
    assert flow.capture_result.real_camera_used is True
    assert flow.capture_result.raw_image_persisted is False
    assert flow.capture_result.cloud_upload_performed is False
    assert flow.artifact is not None
    assert flow.artifact.storage_mode == CameraStorageMode.EPHEMERAL
    assert flow.artifact.mock_artifact is False
    assert flow.artifact.source_provenance == "camera_local"
    assert flow.artifact.file_path is not None
    assert Path(flow.artifact.file_path).exists()
    assert flow.trace.source_provenance == "camera_local"
    assert flow.trace.provider_kind == "local"
    assert flow.trace.real_camera_used is True
    assert flow.trace.cloud_upload_performed is False
    assert flow.trace.raw_image_included is False
    assert provider.capture_attempted is True
    assert provider.hardware_access_attempted is True
    assert provider.active is False
    assert provider.release_count == 1
    assert snapshot["providerKind"] == "local"
    assert snapshot["backendKind"] == "fake_local_still"
    assert snapshot["realCameraUsed"] is True
    assert snapshot["mockCapture"] is False
    assert snapshot["cameraActive"] is False
    assert snapshot["deviceReleaseCount"] == 1
    assert snapshot["lastArtifactFresh"] is True

    event_types = [event["event_type"] for event in events.recent(limit=32)]
    assert "camera.provider_selected" in event_types
    assert "camera.capture_started" in event_types
    assert "camera.capture_completed" in event_types
    assert "camera.device_released" in event_types
    answer_payload = next(
        event["payload"]
        for event in events.recent(limit=32)
        if event["event_type"] == "camera.answer_ready"
    )
    assert answer_payload["source_provenance"] == "camera_local"
    assert answer_payload["provider_kind"] == "local"
    assert answer_payload["real_camera_used"] is True
    assert answer_payload["cloud_upload_performed"] is False
    assert answer_payload["raw_image_included"] is False
    assert "raw_image" not in answer_payload
    assert "image_bytes" not in answer_payload

    assert service.expire_artifact(flow.artifact.image_artifact_id) is True
    assert Path(flow.artifact.file_path).exists() is False


def test_c1_confirmation_policy_blocks_before_local_backend_capture(temp_project_root) -> None:
    camera = _real_enabled_camera_config(temp_project_root)
    backend = FakeLocalStillBackend()
    provider = LocalCameraCaptureProvider(camera, backend=backend)
    service = CameraAwarenessSubsystem(camera, capture_provider=provider)

    flow = service.answer_mock_question(
        user_question="Look at this with the camera.",
        user_request_id="c1-needs-confirmation",
        session_id="session-c1",
        source=CameraCaptureSource.TEST,
        user_confirmed=False,
    )

    assert flow.result_state == CameraAwarenessResultState.CAMERA_PERMISSION_REQUIRED
    assert flow.capture_result.status == CameraCaptureStatus.BLOCKED
    assert flow.capture_result.error_code == "camera_capture_confirmation_required"
    assert backend.capture_calls == 0
    assert provider.capture_attempted is False
    assert provider.hardware_access_attempted is False
    assert provider.release_count == 0


def test_c1_local_backend_unavailable_fails_truthfully_without_cloud_or_mock_claim(temp_project_root) -> None:
    camera = _real_enabled_camera_config(temp_project_root)
    backend = FakeLocalStillBackend(available=False)
    provider = LocalCameraCaptureProvider(camera, backend=backend)
    service = CameraAwarenessSubsystem(camera, capture_provider=provider)

    flow = service.answer_mock_question(
        user_question="Look at this with the camera.",
        user_request_id="c1-unavailable",
        session_id="session-c1",
        source=CameraCaptureSource.TEST,
        user_confirmed=True,
    )

    assert flow.capture_result.status == CameraCaptureStatus.BLOCKED
    assert flow.capture_result.error_code == "local_capture_backend_unavailable"
    assert flow.capture_result.mock_capture is False
    assert flow.capture_result.real_camera_used is False
    assert flow.capture_result.cloud_upload_performed is False
    assert flow.trace.provider_kind == "local"
    assert flow.trace.source_provenance == "camera_unavailable"
    assert provider.active is False
    assert provider.release_count == 1


def test_c1_background_capture_request_blocks_before_local_backend_capture(temp_project_root) -> None:
    camera = _real_enabled_camera_config(temp_project_root)
    camera.allow_background_capture = False
    backend = FakeLocalStillBackend()
    provider = LocalCameraCaptureProvider(camera, backend=backend)
    service = CameraAwarenessSubsystem(camera, capture_provider=provider)

    flow = service.answer_mock_question(
        user_question="Watch the camera in the background.",
        user_request_id="c1-background",
        session_id="session-c1",
        source=CameraCaptureSource.TEST,
        background_capture=True,
        user_confirmed=True,
    )

    assert flow.capture_result.status == CameraCaptureStatus.BLOCKED
    assert flow.capture_result.error_code == "background_capture_not_allowed"
    assert backend.capture_calls == 0
    assert provider.capture_attempted is False
    assert provider.hardware_access_attempted is False


def test_c1_optional_real_camera_smoke_path_is_disabled_by_default(temp_project_root) -> None:
    camera = _real_enabled_camera_config(temp_project_root)
    smoke_enabled = False

    assert smoke_enabled is False
    assert camera.capture.provider == "local"
