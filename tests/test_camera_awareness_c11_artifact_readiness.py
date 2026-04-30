from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import tempfile

import pytest

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CameraAwarenessResultState,
    CameraAwarenessSubsystem,
    CameraCaptureSource,
    CameraDeviceStatus,
    CameraPermissionState,
    LocalCameraCaptureProvider,
    LocalStillCaptureBackendResult,
)
from stormhelm.core.events import EventBuffer


@pytest.fixture(autouse=True)
def cleanup_camera_temp_artifacts_created_by_test():
    root = Path(tempfile.gettempdir()) / "stormhelm-camera-awareness"
    before = {path.resolve() for path in root.glob("camera-frame-*.jpg")} if root.exists() else set()
    yield
    if not root.exists():
        return
    after = {path.resolve() for path in root.glob("camera-frame-*.jpg")}
    for path in after - before:
        path.unlink(missing_ok=True)


def _camera_config(temp_project_root):
    config = load_config(project_root=temp_project_root, env={})
    camera = config.camera_awareness
    camera.enabled = True
    camera.capture.provider = "local"
    camera.vision.provider = "mock"
    camera.privacy.confirm_before_capture = True
    camera.auto_discard_after_seconds = 9
    camera.dev.mock_vision_enabled = True
    return camera


class FakeReadableStillBackend:
    backend_kind = "fake_readable_still"

    def __init__(
        self,
        *,
        payload: bytes = b"fake-readable-camera-frame",
        image_format: str = "jpg",
    ) -> None:
        self.payload = payload
        self.image_format = image_format
        self.capture_calls = 0

    def is_available(self) -> bool:
        return True

    def get_devices(self, *, timeout_seconds: float) -> list[CameraDeviceStatus]:
        del timeout_seconds
        return [
            CameraDeviceStatus(
                device_id="fake-camera-0",
                display_name="Fake Camera",
                provider=self.backend_kind,
                available=True,
                permission_state=CameraPermissionState.UNKNOWN,
                mock_device=False,
                source_provenance="camera_local",
                resolution_options=["1280x720"],
            )
        ]

    def capture_still(
        self,
        *,
        device_id: str,
        output_path: Path,
        timeout_seconds: float,
        requested_resolution: str,
    ) -> LocalStillCaptureBackendResult:
        del timeout_seconds, requested_resolution
        self.capture_calls += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(self.payload)
        return LocalStillCaptureBackendResult(
            success=True,
            device_id=device_id,
            width=1280,
            height=720,
            image_format=self.image_format,
            file_path=output_path,
        )


class CountingVisionProvider:
    provider_kind = "mock"
    network_access_attempted = False

    def __init__(self) -> None:
        self.calls = 0

    def analyze_image(self, question, artifact):  # noqa: ANN001
        self.calls += 1
        raise AssertionError("artifact validation must not call vision analysis")


def _capture_local_flow(temp_project_root, *, payload: bytes = b"fake-readable-camera-frame", image_format: str = "jpg"):
    camera = _camera_config(temp_project_root)
    events = EventBuffer(capacity=64)
    backend = FakeReadableStillBackend(payload=payload, image_format=image_format)
    provider = LocalCameraCaptureProvider(camera, backend=backend)
    service = CameraAwarenessSubsystem(camera, events=events, capture_provider=provider)

    flow = service.answer_mock_question(
        user_question="Look at this with the camera.",
        user_request_id="c11-local-capture",
        session_id="session-c11",
        source=CameraCaptureSource.TEST,
        user_confirmed=True,
    )
    return service, events, flow


def test_c11_real_captured_artifact_readiness_has_truthful_metadata(temp_project_root) -> None:
    service, events, flow = _capture_local_flow(temp_project_root)

    readiness = service.get_artifact_readiness(flow.artifact.image_artifact_id)
    snapshot = service.status_snapshot()

    assert readiness.ready is True
    assert readiness.artifact_exists is True
    assert readiness.artifact_readable is True
    assert readiness.artifact_expired is False
    assert readiness.artifact_size_bytes == len(b"fake-readable-camera-frame")
    assert readiness.artifact_format == "jpg"
    assert readiness.artifact_source_provenance == "camera_local"
    assert readiness.storage_mode == "ephemeral"
    assert snapshot["artifactExists"] is True
    assert snapshot["artifactReadable"] is True
    assert snapshot["artifactExpired"] is False
    assert snapshot["artifactSizeBytes"] == len(b"fake-readable-camera-frame")
    assert snapshot["artifactFormat"] == "jpg"
    assert snapshot["artifactSourceProvenance"] == "camera_local"
    assert snapshot["storageMode"] == "ephemeral"

    readiness_payload = next(
        event["payload"]
        for event in events.recent(limit=32)
        if event["event_type"] == "camera.artifact_readiness_checked"
    )
    assert readiness_payload["artifact_exists"] is True
    assert readiness_payload["artifact_readable"] is True
    assert readiness_payload["artifact_size_bytes"] == len(b"fake-readable-camera-frame")
    assert readiness_payload["artifact_source_provenance"] == "camera_local"
    assert "raw_image" not in readiness_payload
    assert "image_bytes" not in readiness_payload


def test_c11_expired_artifact_fails_readiness_and_analysis_validation(temp_project_root) -> None:
    service, _, flow = _capture_local_flow(temp_project_root)
    expired_at = flow.artifact.expires_at

    readiness = service.get_artifact_readiness(
        flow.artifact.image_artifact_id,
        at=expired_at,
    )
    validation = service.validate_artifact_for_analysis(
        flow.artifact.image_artifact_id,
        at=expired_at,
    )
    followup = service.resolve_artifact_for_followup(
        flow.artifact.image_artifact_id,
        at=flow.artifact.created_at + timedelta(seconds=10),
    )

    assert readiness.ready is False
    assert readiness.artifact_expired is True
    assert readiness.reason_code == "camera_artifact_expired"
    assert validation.ready is False
    assert validation.reason_code == "camera_artifact_expired"
    assert followup.artifact is None
    assert followup.result_state == CameraAwarenessResultState.CAMERA_ARTIFACT_EXPIRED
    assert "no longer have" in followup.message.lower()


def test_c11_missing_artifact_file_fails_readiness_without_fake_analysis(temp_project_root) -> None:
    camera = _camera_config(temp_project_root)
    counting_vision = CountingVisionProvider()
    backend = FakeReadableStillBackend()
    provider = LocalCameraCaptureProvider(camera, backend=backend)
    service = CameraAwarenessSubsystem(camera, capture_provider=provider)
    flow = service.answer_mock_question(
        user_question="Look at this with the camera.",
        user_request_id="c11-missing-file",
        session_id="session-c11",
        source=CameraCaptureSource.TEST,
        user_confirmed=True,
    )

    service.vision_provider = counting_vision
    Path(flow.artifact.file_path).unlink()
    readiness = service.validate_artifact_for_analysis(flow.artifact.image_artifact_id)

    assert readiness.ready is False
    assert readiness.artifact_exists is False
    assert readiness.artifact_readable is False
    assert readiness.reason_code == "camera_artifact_missing"
    assert counting_vision.calls == 0


def test_c11_cleanup_failure_is_reported_without_claiming_success(temp_project_root, monkeypatch) -> None:
    service, events, flow = _capture_local_flow(temp_project_root)
    file_path = Path(flow.artifact.file_path)
    original_unlink = Path.unlink

    def fail_unlink(self, missing_ok=False):  # noqa: ANN001, ANN202
        del missing_ok
        if self == file_path:
            raise OSError("locked by test")
        return original_unlink(self)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    try:
        assert service.expire_artifact(flow.artifact.image_artifact_id) is True
        snapshot = service.status_snapshot()
    finally:
        monkeypatch.undo()
        file_path.unlink(missing_ok=True)

    cleanup_payload = next(
        event["payload"]
        for event in events.recent(limit=32)
        if event["event_type"] == "camera.artifact_cleanup"
    )
    assert cleanup_payload["cleanup_succeeded"] is False
    assert cleanup_payload["cleanup_failed"] is True
    assert cleanup_payload["file_exists_after"] is True
    assert snapshot["cleanupFailed"] is True
    assert snapshot["cleanupPending"] is True
    assert snapshot["artifactExpired"] is True


def test_c11_unsupported_format_and_too_large_artifact_fail_placeholder_validation(
    temp_project_root,
) -> None:
    service, _, flow = _capture_local_flow(temp_project_root, image_format="tiff")

    unsupported = service.validate_artifact_for_analysis(flow.artifact.image_artifact_id)

    assert unsupported.ready is False
    assert unsupported.reason_code == "camera_artifact_unsupported_format"
    assert unsupported.artifact_format == "tiff"

    flow.artifact.image_format = "unknown"
    unknown = service.validate_artifact_for_analysis(flow.artifact.image_artifact_id)

    assert unknown.ready is False
    assert unknown.reason_code == "camera_artifact_unsupported_format"
    assert unknown.artifact_format == "unknown"

    camera = _camera_config(temp_project_root)
    camera.capture.max_artifact_bytes = 4
    backend = FakeReadableStillBackend(payload=b"0123456789", image_format="jpg")
    provider = LocalCameraCaptureProvider(camera, backend=backend)
    service = CameraAwarenessSubsystem(camera, capture_provider=provider)
    flow = service.answer_mock_question(
        user_question="Look at this with the camera.",
        user_request_id="c11-too-large",
        session_id="session-c11",
        source=CameraCaptureSource.TEST,
        user_confirmed=True,
    )

    too_large = service.validate_artifact_for_analysis(flow.artifact.image_artifact_id)

    assert too_large.ready is False
    assert too_large.reason_code == "camera_artifact_too_large"
    assert too_large.artifact_size_bytes == 10


def test_c11_mock_vision_handoff_accepts_fresh_real_artifact_truthfully(temp_project_root) -> None:
    service, events, flow = _capture_local_flow(temp_project_root)

    assert flow.result_state == CameraAwarenessResultState.CAMERA_ANSWER_READY
    assert flow.capture_result.real_camera_used is True
    assert flow.capture_result.mock_capture is False
    assert flow.vision_answer.mock_answer is True
    assert flow.vision_answer.provenance["source"] == "camera_local"
    assert flow.vision_answer.provenance["real_camera_used"] is True
    assert flow.vision_answer.provenance["mock_analysis"] is True
    assert flow.trace.real_camera_used is True
    assert flow.trace.mock_mode is False
    assert flow.trace.cloud_upload_performed is False
    assert flow.trace.raw_image_included is False

    vision_payload = next(
        event["payload"]
        for event in events.recent(limit=32)
        if event["event_type"] == "camera.vision_completed"
    )
    assert vision_payload["mock_answer"] is True
    assert vision_payload["provenance"]["source"] == "camera_local"
    assert vision_payload["cloud_upload_performed"] is False
    assert "raw_image" not in vision_payload
    assert "image_bytes" not in vision_payload
