from __future__ import annotations

from datetime import timedelta
from typing import Any

from stormhelm.config.loader import load_config
from stormhelm.core.camera_awareness import (
    CAMERA_SOURCE_PROVENANCE_MOCK,
    CameraArtifactPersistenceStatus,
    CameraAwarenessResultState,
    CameraAwarenessSubsystem,
    CameraFrameArtifact,
    CameraStorageMode,
    utc_now,
)
from stormhelm.core.events import EventBuffer
from stormhelm.ui.camera_ghost_surface import build_camera_ghost_surface_model


FORBIDDEN_PAYLOAD_KEYS = {
    "api_key",
    "authorization",
    "image_base64",
    "image_bytes",
    "image_url",
    "provider_request",
    "provider_request_body",
    "provider_response",
    "raw_image",
    "raw_provider_response",
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


def _service(
    temp_project_root,
    *,
    allow_save: bool = False,
) -> tuple[CameraAwarenessSubsystem, EventBuffer]:
    events = EventBuffer(capacity=128)
    app_config = load_config(project_root=temp_project_root, env={})
    camera = app_config.camera_awareness
    camera.enabled = True
    camera.privacy.confirm_before_capture = False
    camera.capture.provider = "mock"
    camera.vision.provider = "mock"
    camera.allow_task_artifact_save = allow_save
    camera.privacy.persist_images_by_default = False
    return CameraAwarenessSubsystem(camera, events=events), events


def _artifact(
    artifact_id: str,
    *,
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
        image_format="mock",
        mock_artifact=True,
        fixture_name="artifact_library",
        source_provenance=CAMERA_SOURCE_PROVENANCE_MOCK,
    )


def _camera_request(stage: str = "camera_answer_ready") -> dict[str, Any]:
    return {
        "request_id": "camera-post-c8-save",
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


def test_post_c8_artifact_save_is_blocked_by_default_before_mutation(temp_project_root) -> None:
    service, events = _service(temp_project_root, allow_save=False)
    artifact = service.artifacts.add(_artifact("camera-save-blocked"))

    result = service.save_artifact_to_library(
        image_artifact_id=artifact.image_artifact_id,
        user_request_id="save-blocked",
        user_confirmed=True,
    )

    assert result.status == CameraArtifactPersistenceStatus.BLOCKED
    assert result.result_state == CameraAwarenessResultState.CAMERA_ARTIFACT_SAVE_BLOCKED
    assert result.error_code == "image_persistence_not_allowed"
    assert result.save_performed is False
    assert result.raw_image_included is False
    assert result.cloud_upload_performed is False
    assert artifact.storage_mode == CameraStorageMode.EPHEMERAL
    assert artifact.persisted_by_user_request is False
    assert service.artifacts.library_entry(artifact.image_artifact_id) is None
    assert all(
        event["event_type"] != "camera.artifact_saved"
        for event in events.recent(limit=32)
    )


def test_post_c8_artifact_save_requires_explicit_save_confirmation(temp_project_root) -> None:
    service, _events = _service(temp_project_root, allow_save=True)
    artifact = service.artifacts.add(_artifact("camera-save-confirmation"))

    result = service.save_artifact_to_library(
        image_artifact_id=artifact.image_artifact_id,
        user_request_id="save-needs-confirmation",
        user_confirmed=False,
    )

    assert result.status == CameraArtifactPersistenceStatus.BLOCKED
    assert result.result_state == CameraAwarenessResultState.CAMERA_ARTIFACT_SAVE_PERMISSION_REQUIRED
    assert result.error_code == "camera_artifact_save_confirmation_required"
    assert result.permission_scope_required == "camera.artifact_save"
    assert result.save_performed is False
    assert artifact.persisted_by_user_request is False


def test_post_c8_explicit_artifact_save_marks_artifact_persistent_without_raw_payloads(
    temp_project_root,
) -> None:
    service, events = _service(temp_project_root, allow_save=True)
    artifact = service.artifacts.add(_artifact("camera-save-ok"))

    result = service.save_artifact_to_library(
        image_artifact_id=artifact.image_artifact_id,
        user_request_id="save-ok",
        user_confirmed=True,
        label="Bench connector still",
    )

    assert result.status == CameraArtifactPersistenceStatus.SAVED
    assert result.result_state == CameraAwarenessResultState.CAMERA_ARTIFACT_SAVED
    assert result.save_performed is True
    assert result.safe_library_ref == f"camera-library:{artifact.image_artifact_id}"
    assert result.storage_mode == CameraStorageMode.SAVED
    assert result.image_persisted_by_user_request is True
    assert result.raw_image_included is False
    assert result.cloud_upload_performed is False
    assert result.task_mutation_performed is False
    assert artifact.storage_mode == CameraStorageMode.SAVED
    assert artifact.persisted_by_user_request is True
    assert artifact.retention_policy == "saved_by_user_request"
    assert artifact.expires_at is None

    entry = service.artifacts.library_entry(artifact.image_artifact_id)
    assert entry is not None
    assert entry.safe_library_ref == result.safe_library_ref
    assert entry.label == "Bench connector still"
    assert entry.storage_mode == CameraStorageMode.SAVED

    snapshot = service.status_snapshot()
    assert snapshot["lastArtifactSaved"] is True
    assert snapshot["lastArtifactSavedRef"] == result.safe_library_ref
    assert snapshot["storageMode"] == "saved"
    assert snapshot["rawImageIncluded"] is False
    assert snapshot["cloudUploadPerformed"] is False
    assert _contains_forbidden_payload(snapshot) is False
    assert _contains_forbidden_payload([event["payload"] for event in events.recent(limit=64)]) is False


def test_post_c8_saved_artifact_remains_available_after_original_ttl(temp_project_root) -> None:
    service, _events = _service(temp_project_root, allow_save=True)
    artifact = service.artifacts.add(_artifact("camera-save-retained"))
    service.save_artifact_to_library(
        image_artifact_id=artifact.image_artifact_id,
        user_request_id="save-retained",
        user_confirmed=True,
    )

    future = utc_now() + timedelta(days=1)
    retained = service.artifacts.get(artifact.image_artifact_id, at=future)

    assert retained is artifact
    assert retained.storage_mode == CameraStorageMode.SAVED
    assert retained.persisted_by_user_request is True
    assert retained.is_expired(at=future) is False


def test_post_c8_expired_or_missing_artifacts_cannot_be_saved(temp_project_root) -> None:
    service, _events = _service(temp_project_root, allow_save=True)
    expired = service.artifacts.add(_artifact("camera-save-expired", expired=True))

    expired_result = service.save_artifact_to_library(
        image_artifact_id=expired.image_artifact_id,
        user_request_id="save-expired",
        user_confirmed=True,
    )
    missing_result = service.save_artifact_to_library(
        image_artifact_id="missing-camera-artifact",
        user_request_id="save-missing",
        user_confirmed=True,
    )

    assert expired_result.status == CameraArtifactPersistenceStatus.BLOCKED
    assert expired_result.error_code == "camera_artifact_expired"
    assert expired_result.save_performed is False
    assert expired.persisted_by_user_request is False
    assert missing_result.status == CameraArtifactPersistenceStatus.BLOCKED
    assert missing_result.error_code == "camera_artifact_missing_metadata"
    assert missing_result.save_performed is False


def test_post_c8_deck_model_reflects_backend_saved_artifact_without_save_side_effects(
    temp_project_root,
) -> None:
    service, _events = _service(temp_project_root, allow_save=True)
    artifact = service.artifacts.add(_artifact("camera-save-deck"))
    result = service.save_artifact_to_library(
        image_artifact_id=artifact.image_artifact_id,
        user_request_id="save-deck",
        user_confirmed=True,
    )
    snapshot = service.status_snapshot()

    model = build_camera_ghost_surface_model(
        active_request_state=_camera_request(),
        latest_message={
            "metadata": {
                "camera_awareness": {
                    "vision_answer": {
                        "image_artifact_id": artifact.image_artifact_id,
                        "answer_text": "Saved camera artifact is available.",
                        "concise_answer": "Saved camera artifact.",
                        "confidence": "medium",
                        "provider_kind": "mock",
                        "mock_answer": True,
                        "raw_image_included": False,
                        "cloud_upload_performed": False,
                        "provenance": {
                            "source": "camera_mock",
                            "raw_image_included": False,
                            "cloud_upload_performed": False,
                        },
                    }
                },
                "route_state": {"winner": {"route_family": "camera_awareness"}},
            }
        },
        status=snapshot,
    )
    station = model["deckStations"][0]
    lifecycle_entries = {
        entry["primary"]: entry["secondary"]
        for section in station["sections"]
        if section["title"] == "Artifact Lifecycle"
        for entry in section["entries"]
    }

    assert lifecycle_entries["Saved"] == "Yes"
    assert model["ghostPrimaryCard"]["cameraGhost"]["storageMode"] == "saved"
    assert model["ghostPrimaryCard"]["cameraGhost"]["rawImageIncluded"] is False
    assert result.safe_library_ref not in str(model) or result.safe_library_ref.startswith("camera-library:")
    assert _contains_forbidden_payload(model) is False
