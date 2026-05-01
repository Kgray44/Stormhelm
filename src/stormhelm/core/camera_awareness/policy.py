from __future__ import annotations

from typing import Any

from stormhelm.config.models import CameraAwarenessConfig
from stormhelm.core.camera_awareness.models import (
    CameraAwarenessPolicyResult,
    CameraAwarenessResultState,
    CameraCaptureRequest,
    CameraStorageMode,
)


class CameraAwarenessPolicy:
    """Privacy-first gate for C0 camera capture and mock analysis."""

    def __init__(self, config: CameraAwarenessConfig) -> None:
        self.config = config

    def evaluate_capture_request(
        self,
        request: CameraCaptureRequest,
        *,
        requested_storage_mode: CameraStorageMode | str | None = None,
        user_confirmed: bool | None = None,
    ) -> CameraAwarenessPolicyResult:
        storage_mode = CameraStorageMode(
            requested_storage_mode or self.config.default_storage_mode
        )
        if not self.config.enabled:
            return CameraAwarenessPolicyResult(
                allowed=False,
                blocked_reason="camera_awareness_disabled",
                cloud_analysis_allowed=False,
                background_capture_allowed=False,
                storage_allowed=storage_mode == CameraStorageMode.EPHEMERAL,
                result_state=CameraAwarenessResultState.CAMERA_CAPTURE_BLOCKED,
            )
        if request.background_capture and not self.config.allow_background_capture:
            return CameraAwarenessPolicyResult(
                allowed=False,
                blocked_reason="background_capture_not_allowed",
                cloud_analysis_allowed=False,
                background_capture_allowed=False,
                storage_allowed=storage_mode == CameraStorageMode.EPHEMERAL,
                result_state=CameraAwarenessResultState.CAMERA_CAPTURE_BLOCKED,
            )
        if storage_mode in {CameraStorageMode.SAVED, CameraStorageMode.TASK}:
            if not self.config.allow_task_artifact_save:
                return CameraAwarenessPolicyResult(
                    allowed=False,
                    blocked_reason="image_persistence_not_allowed",
                    cloud_analysis_allowed=False,
                    background_capture_allowed=bool(self.config.allow_background_capture),
                    storage_allowed=False,
                    result_state=CameraAwarenessResultState.CAMERA_CAPTURE_BLOCKED,
                )
        if storage_mode == CameraStorageMode.SESSION and not self.config.allow_session_permission:
            return CameraAwarenessPolicyResult(
                allowed=False,
                blocked_reason="session_camera_permission_not_allowed",
                cloud_analysis_allowed=False,
                background_capture_allowed=bool(self.config.allow_background_capture),
                storage_allowed=False,
                result_state=CameraAwarenessResultState.CAMERA_CAPTURE_BLOCKED,
            )
        if self.config.privacy.confirm_before_capture and user_confirmed is not True:
            return CameraAwarenessPolicyResult(
                allowed=False,
                requires_user_confirmation=True,
                blocked_reason="camera_capture_confirmation_required",
                cloud_analysis_allowed=False,
                background_capture_allowed=bool(self.config.allow_background_capture),
                storage_allowed=storage_mode == CameraStorageMode.EPHEMERAL,
                result_state=CameraAwarenessResultState.CAMERA_PERMISSION_REQUIRED,
            )
        return CameraAwarenessPolicyResult(
            allowed=True,
            requires_user_confirmation=bool(self.config.privacy.confirm_before_capture),
            blocked_reason=None,
            cloud_analysis_allowed=bool(self.config.allow_cloud_vision),
            background_capture_allowed=bool(self.config.allow_background_capture),
            storage_allowed=True,
            result_state=None,
        )

    def evaluate_vision_request(
        self,
        *,
        cloud_analysis_requested: bool = False,
        user_confirmed: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> CameraAwarenessPolicyResult:
        extra = dict(extra or {})
        if not self.config.enabled:
            return CameraAwarenessPolicyResult(
                allowed=False,
                requires_user_confirmation=False,
                blocked_reason="camera_awareness_disabled",
                cloud_analysis_allowed=False,
                background_capture_allowed=False,
                result_state=CameraAwarenessResultState.CAMERA_ANALYSIS_FAILED,
            )
        cloud_allowed = bool(
            self.config.allow_cloud_vision
            and getattr(self.config.vision, "allow_cloud_vision", False)
        )
        if cloud_analysis_requested and not cloud_allowed:
            blocked_reason = (
                "camera_cloud_analysis_disabled"
                if extra.get("reason_schema") == "c2"
                else "cloud_vision_not_allowed"
            )
            return CameraAwarenessPolicyResult(
                allowed=False,
                requires_user_confirmation=False,
                blocked_reason=blocked_reason,
                cloud_analysis_allowed=False,
                background_capture_allowed=bool(self.config.allow_background_capture),
                result_state=CameraAwarenessResultState.CAMERA_CLOUD_ANALYSIS_DISABLED,
            )
        if (
            cloud_analysis_requested
            and bool(getattr(self.config.vision, "require_confirmation_for_cloud", True))
            and user_confirmed is not True
        ):
            return CameraAwarenessPolicyResult(
                allowed=False,
                requires_user_confirmation=True,
                blocked_reason="camera_vision_confirmation_required",
                permission_scope_required="camera.cloud_vision",
                cloud_analysis_allowed=cloud_allowed,
                background_capture_allowed=bool(self.config.allow_background_capture),
                result_state=CameraAwarenessResultState.CAMERA_VISION_PERMISSION_REQUIRED,
            )
        return CameraAwarenessPolicyResult(
            allowed=True,
            requires_user_confirmation=False,
            cloud_analysis_allowed=cloud_allowed,
            background_capture_allowed=bool(self.config.allow_background_capture),
        )

    def evaluate_artifact_save_request(
        self,
        *,
        user_confirmed: bool | None = None,
    ) -> CameraAwarenessPolicyResult:
        if not self.config.enabled:
            return CameraAwarenessPolicyResult(
                allowed=False,
                requires_user_confirmation=False,
                blocked_reason="camera_awareness_disabled",
                permission_scope_required="camera.artifact_save",
                cloud_analysis_allowed=False,
                storage_allowed=False,
                background_capture_allowed=False,
                result_state=CameraAwarenessResultState.CAMERA_ARTIFACT_SAVE_BLOCKED,
            )
        if not self.config.allow_task_artifact_save:
            return CameraAwarenessPolicyResult(
                allowed=False,
                requires_user_confirmation=False,
                blocked_reason="image_persistence_not_allowed",
                permission_scope_required="camera.artifact_save",
                cloud_analysis_allowed=False,
                storage_allowed=False,
                background_capture_allowed=bool(self.config.allow_background_capture),
                result_state=CameraAwarenessResultState.CAMERA_ARTIFACT_SAVE_BLOCKED,
            )
        if user_confirmed is not True:
            return CameraAwarenessPolicyResult(
                allowed=False,
                requires_user_confirmation=True,
                blocked_reason="camera_artifact_save_confirmation_required",
                permission_scope_required="camera.artifact_save",
                cloud_analysis_allowed=False,
                storage_allowed=False,
                background_capture_allowed=bool(self.config.allow_background_capture),
                result_state=CameraAwarenessResultState.CAMERA_ARTIFACT_SAVE_PERMISSION_REQUIRED,
            )
        return CameraAwarenessPolicyResult(
            allowed=True,
            requires_user_confirmation=False,
            permission_scope_required="camera.artifact_save",
            cloud_analysis_allowed=False,
            storage_allowed=True,
            background_capture_allowed=bool(self.config.allow_background_capture),
        )
