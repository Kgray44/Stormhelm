from __future__ import annotations

from datetime import datetime, timedelta
import re

from stormhelm.config.models import CameraAwarenessConfig, OpenAIConfig
from stormhelm.core.camera_awareness.artifacts import (
    CameraArtifactStore,
    get_artifact_readiness as build_artifact_readiness,
    reject_if_expired_or_missing as reject_artifact_if_expired_or_missing,
    validate_artifact_for_analysis as validate_camera_artifact_for_analysis,
)
from stormhelm.core.camera_awareness.comparison import (
    classify_camera_comparison_request,
    default_slot_ids_for_mode,
    infer_comparison_mode,
)
from stormhelm.core.camera_awareness.helpers import build_default_camera_helper_registry
from stormhelm.core.camera_awareness.models import (
    CAMERA_SOURCE_PROVENANCE_UNAVAILABLE,
    ROUTE_FAMILY_CAMERA_AWARENESS,
    CameraArtifactCleanupResult,
    CameraArtifactReadiness,
    CameraAnalysisMode,
    CameraAwarenessFlowResult,
    CameraAwarenessPolicyResult,
    CameraAwarenessResultState,
    CameraCaptureRequest,
    CameraCaptureResult,
    CameraCaptureSlot,
    CameraCaptureSlotStatus,
    CameraCaptureSource,
    CameraCaptureStatus,
    CameraComparisonArtifactSummary,
    CameraComparisonMode,
    CameraComparisonRequest,
    CameraComparisonResult,
    CameraComparisonStatus,
    CameraConfidenceLevel,
    CameraEngineeringHelperResult,
    CameraFrameArtifact,
    CameraMultiCaptureSession,
    CameraMultiCaptureSessionStatus,
    CameraObservationTrace,
    CameraStorageMode,
    CameraVisionAnswer,
    CameraVisionQuestion,
    utc_now,
)
from stormhelm.core.camera_awareness.policy import CameraAwarenessPolicy
from stormhelm.core.camera_awareness.providers import (
    CameraCaptureProvider,
    LocalCameraCaptureProvider,
    MockCameraCaptureProvider,
    MockVisionAnalysisProvider,
    OpenAIVisionAnalysisProvider,
    UnavailableCameraCaptureProvider,
    UnavailableVisionAnalysisProvider,
    VisionAnalysisProvider,
)
from stormhelm.core.camera_awareness.telemetry import CameraTelemetryEmitter
from stormhelm.core.events import EventBuffer
from stormhelm.core.providers.base import AssistantProvider


class CameraAwarenessSubsystem:
    def __init__(
        self,
        config: CameraAwarenessConfig,
        *,
        events: EventBuffer | None = None,
        artifact_store: CameraArtifactStore | None = None,
        capture_provider: CameraCaptureProvider | None = None,
        vision_provider: VisionAnalysisProvider | None = None,
        openai_config: OpenAIConfig | None = None,
        responses_provider: AssistantProvider | None = None,
    ) -> None:
        self.config = config
        self.openai_config = openai_config
        self.responses_provider = responses_provider
        self.policy = CameraAwarenessPolicy(config)
        self.artifacts = artifact_store or CameraArtifactStore()
        self.telemetry = CameraTelemetryEmitter(
            events,
            enabled=bool(config.debug_events_enabled),
        )
        self.helper_registry = build_default_camera_helper_registry()
        self.capture_provider = capture_provider or self._build_capture_provider()
        self.vision_provider = vision_provider or self._build_vision_provider()
        self._active = False
        self._last_result_state: CameraAwarenessResultState | None = None
        self._last_capture_source: str | None = None
        self._last_artifact_storage_mode: str | None = None
        self._last_artifact_expired = False
        self._last_mock_capture = False
        self._last_real_camera_used = False
        self._last_cloud_upload_performed = False
        self._last_raw_image_included = False
        self._last_source_provenance: str | None = None
        self._last_artifact_readiness: CameraArtifactReadiness | None = None
        self._last_cleanup_result: CameraArtifactCleanupResult | None = None
        self._last_vision_status: CameraAwarenessResultState | None = None
        self._last_vision_confidence: str | None = None
        self._last_vision_error_code: str | None = None
        self._last_cloud_analysis_allowed = False
        self._last_cloud_analysis_performed = False
        self._last_helper_result: CameraEngineeringHelperResult | None = None
        self._multi_capture_sessions: dict[str, CameraMultiCaptureSession] = {}
        self._last_multi_capture_session: CameraMultiCaptureSession | None = None
        self._last_comparison_request: CameraComparisonRequest | None = None
        self._last_comparison_result: CameraComparisonResult | None = None
        self._warnings: list[str] = []

    def answer_mock_question(
        self,
        *,
        user_question: str,
        user_request_id: str,
        session_id: str | None = None,
        source: CameraCaptureSource | str = CameraCaptureSource.USER_REQUEST,
        user_confirmed: bool | None = None,
        cloud_analysis_confirmed: bool | None = None,
        background_capture: bool = False,
    ) -> CameraAwarenessFlowResult:
        self._active = True
        request = CameraCaptureRequest(
            user_request_id=user_request_id,
            session_id=session_id,
            source=CameraCaptureSource(source),
            reason="camera_awareness_mock_flow",
            user_question=user_question,
            requested_resolution=self.config.capture.requested_resolution,
            background_capture=background_capture,
        )
        self._last_capture_source = request.source.value
        self.telemetry.emit(
            "camera.capture_requested",
            "Camera capture requested.",
            session_id=session_id,
            payload={
                "capture_request_id": request.capture_request_id,
                "source": request.source.value,
                "provider_kind": self.capture_provider.provider_kind,
                "background_capture": request.background_capture,
            },
        )
        self.telemetry.emit(
            "camera.provider_selected",
            "Camera capture provider selected.",
            session_id=session_id,
            payload={
                "configured_capture_provider": self.config.capture.provider,
                "provider_kind": self.capture_provider.provider_kind,
                "backend_kind": getattr(self.capture_provider, "backend_kind", None),
                "capture_attempted": bool(
                    getattr(self.capture_provider, "capture_attempted", False)
                ),
                "hardware_access_attempted": bool(
                    getattr(self.capture_provider, "hardware_access_attempted", False)
                ),
            },
        )
        try:
            policy_result = self.policy.evaluate_capture_request(
                request,
                requested_storage_mode=CameraStorageMode(self.config.default_storage_mode),
                user_confirmed=(
                    user_confirmed
                    if user_confirmed is not None
                    else not self.config.privacy.confirm_before_capture
                ),
            )
            self.telemetry.emit(
                "camera.policy_checked",
                "Camera privacy policy checked.",
                session_id=session_id,
                payload=policy_result.to_dict(),
            )
            if not policy_result.allowed:
                flow = self._blocked_flow(
                    request,
                    policy_result,
                    session_id=session_id,
                )
                self._remember_flow_truth(flow)
                return flow

            self.telemetry.emit(
                "camera.capture_started",
                "Camera capture started.",
                session_id=session_id,
                payload={
                    "capture_request_id": request.capture_request_id,
                    "provider_kind": self.capture_provider.provider_kind,
                    "backend_kind": getattr(self.capture_provider, "backend_kind", None),
                    "storage_mode": self.config.default_storage_mode,
                    "background_capture": request.background_capture,
                },
            )
            capture_result, artifact = self.capture_provider.capture_still(request)
            if hasattr(self.capture_provider, "release_count"):
                self.telemetry.emit(
                    "camera.device_released",
                    "Camera device released.",
                    session_id=session_id,
                    payload={
                        "provider_kind": self.capture_provider.provider_kind,
                        "backend_kind": getattr(self.capture_provider, "backend_kind", None),
                        "device_id": capture_result.device_id,
                        "active": bool(getattr(self.capture_provider, "active", False)),
                        "release_count": int(
                            getattr(self.capture_provider, "release_count", 0)
                        ),
                    },
                )
            if artifact is not None:
                self.artifacts.add(artifact)
                self._last_artifact_storage_mode = artifact.storage_mode.value
                self._last_artifact_expired = False
                self.telemetry.emit(
                    "camera.artifact_created",
                    "Ephemeral camera frame artifact created.",
                    session_id=session_id,
                    payload={
                        "image_artifact_id": artifact.image_artifact_id,
                        "storage_mode": artifact.storage_mode.value,
                        "source_provenance": artifact.source_provenance,
                        "expires_at": artifact.expires_at,
                        "mock_artifact": artifact.mock_artifact,
                    },
                )
            self.telemetry.emit(
                "camera.capture_completed",
                "Camera capture completed.",
                session_id=session_id,
                payload=capture_result.to_dict(),
            )
            if capture_result.status != CameraCaptureStatus.CAPTURED or artifact is None:
                flow = self._capture_failed_flow(
                    request,
                    policy_result,
                    capture_result,
                    session_id=session_id,
                )
                self._remember_flow_truth(flow)
                return flow

            readiness = self.get_artifact_readiness(
                artifact.image_artifact_id,
                session_id=session_id,
            )
            if not readiness.ready:
                question = CameraVisionQuestion(
                    image_artifact_id=artifact.image_artifact_id,
                    user_question=user_question,
                    normalized_question=_normalize_question(user_question),
                    analysis_mode=_analysis_mode(user_question),
                    provider="unavailable",
                    model="unavailable",
                    cloud_analysis_allowed=False,
                    mock_analysis=False,
                )
                answer = UnavailableVisionAnalysisProvider(
                    reason=readiness.reason_code or "camera_artifact_not_ready"
                ).analyze_image(question, artifact)
                trace = CameraObservationTrace(
                    capture_request_id=request.capture_request_id,
                    capture_result_id=capture_result.capture_result_id,
                    image_artifact_id=artifact.image_artifact_id,
                    vision_question_id=question.vision_question_id,
                    vision_answer_id=answer.vision_answer_id,
                    result_state=answer.result_state,
                    source_provenance=artifact.source_provenance,
                    provider_kind=self.capture_provider.provider_kind,
                    storage_mode=artifact.storage_mode,
                    policy_allowed=policy_result.allowed,
                    blocked_reason=readiness.reason_code,
                    raw_image_included=False,
                    raw_image_persisted=False,
                    cloud_upload_performed=False,
                    real_camera_used=capture_result.real_camera_used,
                    mock_mode=False,
                )
                self.telemetry.emit(
                    "camera.vision_blocked",
                    "Camera vision blocked because the artifact is not ready.",
                    session_id=session_id,
                    payload={
                        **readiness.to_dict(),
                        "capture_result_id": capture_result.capture_result_id,
                        "vision_question_id": question.vision_question_id,
                        "cloud_upload_performed": False,
                        "raw_image_included": False,
                    },
                )
                self.telemetry.emit(
                    "camera.answer_ready",
                    "Camera awareness answer ready.",
                    session_id=session_id,
                    payload=trace.to_dict(),
                )
                flow = CameraAwarenessFlowResult(
                    capture_request=request,
                    policy_result=policy_result,
                    capture_result=capture_result,
                    artifact=artifact,
                    vision_question=question,
                    vision_answer=answer,
                    trace=trace,
                    result_state=answer.result_state,
                    response_text=answer.answer_text,
                )
                self._remember_flow_truth(flow)
                return flow

            cloud_analysis_requested = _vision_provider_requires_cloud(self.vision_provider)
            vision_policy = self.policy.evaluate_vision_request(
                cloud_analysis_requested=cloud_analysis_requested,
                user_confirmed=cloud_analysis_confirmed,
                extra={"reason_schema": "c2"},
            )
            self._last_cloud_analysis_allowed = vision_policy.cloud_analysis_allowed
            self.telemetry.emit(
                "camera.vision_policy_checked",
                "Camera vision policy checked.",
                session_id=session_id,
                payload={
                    **vision_policy.to_dict(),
                    "provider_kind": self.vision_provider.provider_kind,
                    "cloud_analysis_requested": cloud_analysis_requested,
                    "cloud_analysis_performed": False,
                    "raw_image_included": False,
                },
            )
            if not vision_policy.allowed:
                flow = self._vision_blocked_flow(
                    request,
                    policy_result,
                    vision_policy,
                    capture_result,
                    artifact,
                    session_id=session_id,
                )
                self._remember_flow_truth(flow)
                return flow
            question = CameraVisionQuestion(
                image_artifact_id=artifact.image_artifact_id,
                user_question=user_question,
                normalized_question=_normalize_question(user_question),
                analysis_mode=_analysis_mode(user_question),
                provider=self.vision_provider.provider_kind,
                model=self.config.vision.model
                if self.vision_provider.provider_kind in {"mock", "openai"}
                else "unavailable",
                cloud_analysis_allowed=vision_policy.cloud_analysis_allowed,
                mock_analysis=self.vision_provider.provider_kind == "mock",
            )
            self.telemetry.emit(
                "camera.vision_provider_selected",
                "Camera vision provider selected.",
                session_id=session_id,
                payload={
                    "provider_kind": self.vision_provider.provider_kind,
                    "model": question.model,
                    "cloud_analysis_requested": cloud_analysis_requested,
                    "cloud_analysis_allowed": vision_policy.cloud_analysis_allowed,
                    "network_access_attempted": bool(
                        getattr(self.vision_provider, "network_access_attempted", False)
                    ),
                    "raw_image_included": False,
                },
            )
            self.telemetry.emit(
                "camera.vision_requested",
                "Camera vision requested.",
                session_id=session_id,
                payload=question.to_dict(),
            )
            answer = self.vision_provider.analyze_image(question, artifact)
            trace = CameraObservationTrace(
                capture_request_id=request.capture_request_id,
                capture_result_id=capture_result.capture_result_id,
                image_artifact_id=artifact.image_artifact_id,
                vision_question_id=question.vision_question_id,
                vision_answer_id=answer.vision_answer_id,
                result_state=answer.result_state,
                source_provenance=artifact.source_provenance,
                provider_kind=self.capture_provider.provider_kind,
                storage_mode=artifact.storage_mode,
                policy_allowed=policy_result.allowed,
                raw_image_included=False,
                raw_image_persisted=False,
                cloud_upload_performed=answer.cloud_upload_performed,
                real_camera_used=capture_result.real_camera_used,
                mock_mode=answer.mock_answer and capture_result.mock_capture,
            )
            self.telemetry.emit(
                "camera.vision_completed",
                "Camera vision completed.",
                session_id=session_id,
                payload=answer.to_dict(),
            )
            self.telemetry.emit(
                "camera.answer_normalized",
                "Camera vision answer normalized.",
                session_id=session_id,
                payload={
                    "vision_answer_id": answer.vision_answer_id,
                    "image_artifact_id": answer.image_artifact_id,
                    "provider_kind": answer.provider_kind,
                    "model": answer.model,
                    "analysis_mode": answer.analysis_mode.value,
                    "confidence": answer.confidence.value,
                    "result_state": answer.result_state.value,
                    "error_code": answer.error_code,
                    "cloud_analysis_performed": answer.cloud_analysis_performed,
                    "cloud_upload_performed": answer.cloud_upload_performed,
                    "mock_analysis": answer.mock_answer,
                    "raw_image_included": False,
                },
            )
            helper_result = self._apply_helper_result(
                user_question=user_question,
                answer=answer,
                session_id=session_id,
            )
            self.telemetry.emit(
                "camera.answer_ready",
                "Camera awareness answer ready.",
                session_id=session_id,
                payload=trace.to_dict(),
            )
            flow = CameraAwarenessFlowResult(
                capture_request=request,
                policy_result=policy_result,
                capture_result=capture_result,
                artifact=artifact,
                vision_question=question,
                vision_answer=answer,
                trace=trace,
                result_state=answer.result_state,
                response_text=answer.answer_text,
                helper_result=helper_result,
            )
            self._remember_flow_truth(flow)
            return flow
        finally:
            self._active = False

    def get_recent_camera_artifact(self, *, at: datetime | None = None) -> CameraFrameArtifact | None:
        artifact = self.artifacts.latest(at=at)
        self._last_artifact_expired = artifact is None and bool(self._last_artifact_storage_mode)
        return artifact

    def get_artifact_readiness(
        self,
        image_artifact_id: str | None = None,
        *,
        at: datetime | None = None,
        session_id: str | None = None,
        emit_event: bool = True,
    ) -> CameraArtifactReadiness:
        artifact_id = image_artifact_id or self.artifacts.latest_artifact_id
        artifact = self.artifacts.peek(artifact_id)
        readiness = build_artifact_readiness(
            artifact,
            image_artifact_id=artifact_id,
            at=at,
            max_size_bytes=_max_artifact_bytes(self.config),
        )
        self._last_artifact_readiness = readiness
        self._last_artifact_expired = readiness.artifact_expired
        self._last_source_provenance = readiness.artifact_source_provenance
        self._last_artifact_storage_mode = readiness.storage_mode.value
        if emit_event:
            self.telemetry.emit(
                "camera.artifact_readiness_checked",
                "Camera artifact readiness checked.",
                session_id=session_id,
                payload={
                    **readiness.to_dict(),
                    "cloud_upload_performed": False,
                    "raw_image_included": False,
                },
            )
        return readiness

    def validate_artifact_for_analysis(
        self,
        image_artifact_id: str | None = None,
        *,
        at: datetime | None = None,
        session_id: str | None = None,
        emit_event: bool = True,
    ) -> CameraArtifactReadiness:
        artifact_id = image_artifact_id or self.artifacts.latest_artifact_id
        artifact = self.artifacts.peek(artifact_id)
        readiness = validate_camera_artifact_for_analysis(
            artifact,
            image_artifact_id=artifact_id,
            at=at,
            max_size_bytes=_max_artifact_bytes(self.config),
        )
        self._last_artifact_readiness = readiness
        self._last_artifact_expired = readiness.artifact_expired
        self._last_source_provenance = readiness.artifact_source_provenance
        self._last_artifact_storage_mode = readiness.storage_mode.value
        if emit_event:
            self.telemetry.emit(
                "camera.artifact_validation_checked",
                "Camera artifact analysis validation checked.",
                session_id=session_id,
                payload={
                    **readiness.to_dict(),
                    "analysis_performed": False,
                    "cloud_upload_performed": False,
                    "raw_image_included": False,
                },
            )
        return readiness

    def reject_if_expired_or_missing(
        self,
        image_artifact_id: str | None = None,
        *,
        at: datetime | None = None,
        session_id: str | None = None,
        emit_event: bool = True,
    ) -> CameraArtifactReadiness:
        artifact_id = image_artifact_id or self.artifacts.latest_artifact_id
        artifact = self.artifacts.peek(artifact_id)
        readiness = reject_artifact_if_expired_or_missing(
            artifact,
            image_artifact_id=artifact_id,
            at=at,
            max_size_bytes=_max_artifact_bytes(self.config),
        )
        self._last_artifact_readiness = readiness
        self._last_artifact_expired = readiness.artifact_expired
        if emit_event:
            self.telemetry.emit(
                "camera.artifact_reuse_checked",
                "Camera artifact reuse validation checked.",
                session_id=session_id,
                payload={
                    **readiness.to_dict(),
                    "analysis_performed": False,
                    "cloud_upload_performed": False,
                    "raw_image_included": False,
                },
            )
        return readiness

    def analyze_artifact_with_selected_provider(
        self,
        *,
        image_artifact_id: str | None = None,
        user_question: str,
        user_request_id: str,
        session_id: str | None = None,
        cloud_analysis_confirmed: bool | None = None,
        at: datetime | None = None,
    ) -> CameraAwarenessFlowResult:
        request = CameraCaptureRequest(
            user_request_id=user_request_id,
            session_id=session_id,
            source=CameraCaptureSource.USER_REQUEST,
            reason="camera_awareness_artifact_analysis",
            user_question=user_question,
            background_capture=False,
        )
        artifact_id = image_artifact_id or self.artifacts.latest_artifact_id
        artifact = self.artifacts.peek(artifact_id)
        readiness = self.validate_artifact_for_analysis(
            artifact_id,
            at=at,
            session_id=session_id,
        )
        capture_result = CameraCaptureResult(
            request_id=request.capture_request_id,
            status=CameraCaptureStatus.CAPTURED if artifact is not None else CameraCaptureStatus.FAILED,
            capture_result_id=artifact.capture_result_id if artifact is not None else "missing-artifact",
            image_artifact_id=artifact_id,
            device_id=None,
            width=artifact.width if artifact is not None else 0,
            height=artifact.height if artifact is not None else 0,
            image_format=artifact.image_format if artifact is not None else "none",
            raw_image_persisted=False,
            cloud_upload_allowed=False,
            cloud_upload_performed=False,
            mock_capture=bool(artifact and artifact.mock_artifact),
            real_camera_used=bool(
                artifact and artifact.source_provenance == "camera_local"
            ),
            source_provenance=artifact.source_provenance if artifact is not None else "camera_unavailable",
        )
        if not readiness.ready:
            vision_policy = CameraAwarenessPolicyResult(
                allowed=False,
                blocked_reason=readiness.reason_code,
                cloud_analysis_allowed=False,
                result_state=_result_state_for_readiness(readiness.reason_code),
            )
            flow = self._vision_blocked_flow(
                request,
                CameraAwarenessPolicyResult(allowed=True, cloud_analysis_allowed=False),
                vision_policy,
                capture_result,
                artifact,
                session_id=session_id,
                blocked_reason=readiness.reason_code,
            )
            self._remember_flow_truth(flow)
            return flow

        cloud_analysis_requested = _vision_provider_requires_cloud(self.vision_provider)
        vision_policy = self.policy.evaluate_vision_request(
            cloud_analysis_requested=cloud_analysis_requested,
            user_confirmed=cloud_analysis_confirmed,
            extra={"reason_schema": "c2"},
        )
        self._last_cloud_analysis_allowed = vision_policy.cloud_analysis_allowed
        self.telemetry.emit(
            "camera.vision_policy_checked",
            "Camera vision policy checked.",
            session_id=session_id,
            payload={
                **vision_policy.to_dict(),
                "provider_kind": self.vision_provider.provider_kind,
                "cloud_analysis_requested": cloud_analysis_requested,
                "cloud_analysis_performed": False,
                "raw_image_included": False,
            },
        )
        if not vision_policy.allowed:
            flow = self._vision_blocked_flow(
                request,
                CameraAwarenessPolicyResult(allowed=True, cloud_analysis_allowed=False),
                vision_policy,
                capture_result,
                artifact,
                session_id=session_id,
            )
            self._remember_flow_truth(flow)
            return flow

        question = CameraVisionQuestion(
            image_artifact_id=artifact.image_artifact_id,
            user_question=user_question,
            normalized_question=_normalize_question(user_question),
            analysis_mode=_analysis_mode(user_question),
            provider=self.vision_provider.provider_kind,
            model=self.config.vision.model
            if self.vision_provider.provider_kind in {"mock", "openai"}
            else "unavailable",
            cloud_analysis_allowed=vision_policy.cloud_analysis_allowed,
            mock_analysis=self.vision_provider.provider_kind == "mock",
        )
        self.telemetry.emit(
            "camera.vision_provider_selected",
            "Camera vision provider selected.",
            session_id=session_id,
            payload={
                "provider_kind": self.vision_provider.provider_kind,
                "model": question.model,
                "cloud_analysis_requested": cloud_analysis_requested,
                "cloud_analysis_allowed": vision_policy.cloud_analysis_allowed,
                "network_access_attempted": bool(
                    getattr(self.vision_provider, "network_access_attempted", False)
                ),
                "raw_image_included": False,
            },
        )
        self.telemetry.emit(
            "camera.vision_requested",
            "Camera vision requested.",
            session_id=session_id,
            payload=question.to_dict(),
        )
        answer = self.vision_provider.analyze_image(question, artifact)
        preparation = getattr(self.vision_provider, "last_preparation", None)
        if preparation is not None and hasattr(preparation, "to_safe_dict"):
            self.telemetry.emit(
                "camera.vision_image_prepared",
                "Camera vision image prepared.",
                session_id=session_id,
                payload={
                    **preparation.to_safe_dict(),
                    "provider_kind": self.vision_provider.provider_kind,
                    "model": question.model,
                    "cloud_upload_performed": False,
                    "raw_image_included": False,
                },
            )
        trace = CameraObservationTrace(
            capture_request_id=request.capture_request_id,
            capture_result_id=capture_result.capture_result_id,
            image_artifact_id=artifact.image_artifact_id,
            vision_question_id=question.vision_question_id,
            vision_answer_id=answer.vision_answer_id,
            result_state=answer.result_state,
            source_provenance=artifact.source_provenance,
            provider_kind=self.capture_provider.provider_kind,
            storage_mode=artifact.storage_mode,
            policy_allowed=vision_policy.allowed,
            blocked_reason=answer.error_code,
            raw_image_included=False,
            raw_image_persisted=False,
            cloud_upload_performed=answer.cloud_upload_performed,
            real_camera_used=capture_result.real_camera_used,
            mock_mode=answer.mock_answer and capture_result.mock_capture,
        )
        self.telemetry.emit(
            "camera.vision_completed",
            "Camera vision completed.",
            session_id=session_id,
            payload=answer.to_dict(),
        )
        self.telemetry.emit(
            "camera.answer_normalized",
            "Camera vision answer normalized.",
            session_id=session_id,
            payload={
                "vision_answer_id": answer.vision_answer_id,
                "image_artifact_id": answer.image_artifact_id,
                "provider_kind": answer.provider_kind,
                "model": answer.model,
                "analysis_mode": answer.analysis_mode.value,
                "confidence": answer.confidence.value,
                "result_state": answer.result_state.value,
                "error_code": answer.error_code,
                "cloud_analysis_performed": answer.cloud_analysis_performed,
                "cloud_upload_performed": answer.cloud_upload_performed,
                "mock_analysis": answer.mock_answer,
                "raw_image_included": False,
            },
        )
        helper_result = self._apply_helper_result(
            user_question=user_question,
            answer=answer,
            session_id=session_id,
        )
        self.telemetry.emit(
            "camera.answer_ready",
            "Camera awareness answer ready.",
            session_id=session_id,
            payload=trace.to_dict(),
        )
        flow = CameraAwarenessFlowResult(
            capture_request=request,
            policy_result=vision_policy,
            capture_result=capture_result,
            artifact=artifact,
            vision_question=question,
            vision_answer=answer,
            trace=trace,
            result_state=answer.result_state,
            response_text=answer.answer_text,
            helper_result=helper_result,
        )
        self._remember_flow_truth(flow)
        return flow

    def expire_artifact(self, image_artifact_id: str) -> bool:
        expired = self.artifacts.expire(image_artifact_id)
        if expired:
            self._last_cleanup_result = self.artifacts.last_cleanup_result
            cleanup = self._last_cleanup_result
            self._last_artifact_expired = True
            self._last_result_state = CameraAwarenessResultState.CAMERA_ARTIFACT_EXPIRED
            if self._last_artifact_readiness is not None:
                self._last_artifact_readiness.artifact_expired = True
                self._last_artifact_readiness.ready = False
                self._last_artifact_readiness.cleanup_failed = bool(
                    cleanup and cleanup.cleanup_failed
                )
                self._last_artifact_readiness.cleanup_pending = bool(
                    cleanup and cleanup.cleanup_pending
                )
            self.telemetry.emit(
                "camera.artifact_expired",
                "Ephemeral camera artifact expired.",
                payload={"image_artifact_id": image_artifact_id},
            )
            self.telemetry.emit(
                "camera.artifact_cleanup",
                "Ephemeral camera artifact cleanup completed.",
                payload={
                    "image_artifact_id": image_artifact_id,
                    "storage_mode": self._last_artifact_storage_mode or "ephemeral",
                    "cleanup_attempted": bool(cleanup and cleanup.cleanup_attempted),
                    "cleanup_succeeded": bool(cleanup and cleanup.cleanup_succeeded),
                    "cleanup_failed": bool(cleanup and cleanup.cleanup_failed),
                    "cleanup_pending": bool(cleanup and cleanup.cleanup_pending),
                    "file_existed_before": bool(cleanup and cleanup.file_existed_before),
                    "file_exists_after": bool(cleanup and cleanup.file_exists_after),
                    "error_code": cleanup.error_code if cleanup else None,
                    "raw_image_included": False,
                    "cloud_upload_performed": False,
                },
            )
        return expired

    def retry_artifact_cleanup(self, image_artifact_id: str) -> CameraArtifactCleanupResult:
        cleanup = self.artifacts.retry_cleanup(image_artifact_id)
        self._last_cleanup_result = cleanup
        if self._last_artifact_readiness is not None:
            self._last_artifact_readiness.cleanup_failed = cleanup.cleanup_failed
            self._last_artifact_readiness.cleanup_pending = cleanup.cleanup_pending
        self.telemetry.emit(
            "camera.artifact_cleanup_retry",
            "Ephemeral camera artifact cleanup retry completed.",
            payload={
                "image_artifact_id": image_artifact_id,
                "storage_mode": self._last_artifact_storage_mode or "ephemeral",
                "cleanup_attempted": cleanup.cleanup_attempted,
                "cleanup_succeeded": cleanup.cleanup_succeeded,
                "cleanup_failed": cleanup.cleanup_failed,
                "cleanup_pending": cleanup.cleanup_pending,
                "file_existed_before": cleanup.file_existed_before,
                "file_exists_after": cleanup.file_exists_after,
                "error_code": cleanup.error_code,
                "raw_image_included": False,
                "cloud_upload_performed": False,
            },
        )
        return cleanup

    def resolve_artifact_for_followup(
        self,
        image_artifact_id: str | None = None,
        *,
        at: datetime | None = None,
    ):
        resolution = self.artifacts.resolve_for_followup(image_artifact_id, at=at)
        if resolution.artifact is None:
            self._last_artifact_expired = True
            self._last_result_state = resolution.result_state
            self._last_cleanup_result = self.artifacts.last_cleanup_result
            if self._last_artifact_readiness is not None:
                self._last_artifact_readiness.ready = False
                self._last_artifact_readiness.artifact_expired = True
                self._last_artifact_readiness.reason_code = "camera_artifact_expired"
                self._last_artifact_readiness.message = resolution.message
                if self._last_cleanup_result is not None:
                    self._last_artifact_readiness.cleanup_failed = (
                        self._last_cleanup_result.cleanup_failed
                    )
                    self._last_artifact_readiness.cleanup_pending = (
                        self._last_cleanup_result.cleanup_pending
                    )
        return resolution

    def create_multi_capture_session(
        self,
        *,
        user_request_id: str,
        session_id: str | None = None,
        task_id: str | None = None,
        purpose: str = "",
        user_question: str = "",
        slot_labels: list[str] | None = None,
        comparison_mode: CameraComparisonMode | str | None = None,
        helper_family: str | None = None,
    ) -> CameraMultiCaptureSession:
        classification = classify_camera_comparison_request(user_question or purpose)
        mode = CameraComparisonMode(
            comparison_mode
            or (
                classification.comparison_mode
                if classification.applicable
                else infer_comparison_mode(user_question or purpose)
            )
        )
        slot_ids = [_slot_id(label) for label in (slot_labels or default_slot_ids_for_mode(mode))]
        slots = [
            CameraCaptureSlot(
                slot_id=slot_id,
                label=_slot_label(slot_id),
                description=f"Explicit still for {slot_id.replace('_', ' ')}.",
                required=True,
            )
            for slot_id in slot_ids[:6]
        ]
        created_at = utc_now()
        session = CameraMultiCaptureSession(
            user_request_id=user_request_id,
            session_id=session_id,
            task_id=task_id,
            purpose=purpose or user_question or mode.value,
            helper_category=classification.helper_category,
            helper_family=helper_family or classification.helper_family,
            comparison_mode=mode,
            status=CameraMultiCaptureSessionStatus.ACTIVE,
            created_at=created_at,
            expires_at=created_at + _camera_ttl(self.config),
            expected_slots=slots,
            storage_mode_default=CameraStorageMode(self.config.default_storage_mode),
            cloud_analysis_allowed=False,
            cloud_analysis_performed=False,
            mock_session=self.capture_provider.provider_kind == "mock",
        )
        self._multi_capture_sessions[session.multi_capture_session_id] = session
        self._last_multi_capture_session = session
        self.telemetry.emit(
            "camera.multi_capture_session_created",
            "Camera multi-capture session created.",
            session_id=session_id,
            payload={
                "multi_capture_session_id": session.multi_capture_session_id,
                "comparison_mode": session.comparison_mode.value,
                "helper_category": session.helper_category,
                "helper_family": session.helper_family,
                "slot_count": len(session.expected_slots),
                "storage_mode": session.storage_mode_default.value,
                "mock_session": session.mock_session,
                "raw_image_included": False,
                "action_executed": False,
            },
        )
        for slot in session.expected_slots:
            self.telemetry.emit(
                "camera.multi_capture_slot_requested",
                "Camera multi-capture slot requested.",
                session_id=session_id,
                payload={
                    "multi_capture_session_id": session.multi_capture_session_id,
                    "slot_id": slot.slot_id,
                    "label": slot.label,
                    "status": slot.status.value,
                    "raw_image_included": False,
                    "action_executed": False,
                },
            )
        return session

    def get_multi_capture_session(
        self,
        multi_capture_session_id: str,
        *,
        at: datetime | None = None,
    ) -> CameraMultiCaptureSession | None:
        session = self._multi_capture_sessions.get(str(multi_capture_session_id or "").strip())
        if session is not None and session.is_expired(at=at):
            session.status = CameraMultiCaptureSessionStatus.EXPIRED
            session.error_code = "multi_capture_session_expired"
            self._last_multi_capture_session = session
        return session

    def add_capture_to_session(
        self,
        multi_capture_session_id: str,
        slot_id: str,
        artifact_id: str,
        *,
        capture_request_id: str | None = None,
        capture_result_id: str | None = None,
        at: datetime | None = None,
    ) -> CameraMultiCaptureSession:
        session = self.get_multi_capture_session(multi_capture_session_id, at=at)
        if session is None:
            raise KeyError("multi_capture_session_not_found")
        if session.status in {
            CameraMultiCaptureSessionStatus.CANCELLED,
            CameraMultiCaptureSessionStatus.EXPIRED,
        }:
            raise ValueError(session.status.value)
        slot = _find_slot(session, slot_id)
        if slot is None:
            raise KeyError("capture_slot_missing")
        artifact = self.artifacts.peek(artifact_id)
        slot.status = CameraCaptureSlotStatus.CAPTURED
        slot.artifact_id = artifact_id
        slot.capture_request_id = capture_request_id
        slot.capture_result_id = capture_result_id or (artifact.capture_result_id if artifact else None)
        slot.captured_at = at or utc_now()
        slot.expires_at = artifact.expires_at if artifact else None
        slot.source_provenance = artifact.source_provenance if artifact else CAMERA_SOURCE_PROVENANCE_UNAVAILABLE
        _refresh_session_slot_state(session)
        self._last_multi_capture_session = session
        self.telemetry.emit(
            "camera.multi_capture_slot_captured",
            "Camera multi-capture slot captured.",
            session_id=session.session_id,
            payload={
                "multi_capture_session_id": session.multi_capture_session_id,
                "slot_id": slot.slot_id,
                "artifact_id": artifact_id,
                "slot_count": len(session.expected_slots),
                "artifact_count": len(session.artifact_ids),
                "source_provenance": slot.source_provenance,
                "raw_image_included": False,
                "action_executed": False,
            },
        )
        if session.status == CameraMultiCaptureSessionStatus.READY_TO_COMPARE:
            self.telemetry.emit(
                "camera.multi_capture_session_ready",
                "Camera multi-capture session is ready to compare.",
                session_id=session.session_id,
                payload={
                    "multi_capture_session_id": session.multi_capture_session_id,
                    "comparison_mode": session.comparison_mode.value,
                    "artifact_count": len(session.artifact_ids),
                    "raw_image_included": False,
                    "action_executed": False,
                },
            )
        return session

    def cancel_multi_capture_session(self, multi_capture_session_id: str) -> CameraMultiCaptureSession | None:
        session = self._multi_capture_sessions.get(str(multi_capture_session_id or "").strip())
        if session is None:
            return None
        session.status = CameraMultiCaptureSessionStatus.CANCELLED
        session.error_code = "multi_capture_session_cancelled"
        self._last_multi_capture_session = session
        self.telemetry.emit(
            "camera.multi_capture_session_cancelled",
            "Camera multi-capture session cancelled.",
            session_id=session.session_id,
            payload={
                "multi_capture_session_id": session.multi_capture_session_id,
                "raw_image_included": False,
                "action_executed": False,
            },
        )
        return session

    def expire_multi_capture_session(self, multi_capture_session_id: str) -> CameraMultiCaptureSession | None:
        session = self._multi_capture_sessions.get(str(multi_capture_session_id or "").strip())
        if session is None:
            return None
        session.status = CameraMultiCaptureSessionStatus.EXPIRED
        session.error_code = "multi_capture_session_expired"
        for slot in session.expected_slots:
            if slot.status == CameraCaptureSlotStatus.PENDING:
                slot.status = CameraCaptureSlotStatus.EXPIRED
        self._last_multi_capture_session = session
        self.telemetry.emit(
            "camera.multi_capture_session_expired",
            "Camera multi-capture session expired.",
            session_id=session.session_id,
            payload={
                "multi_capture_session_id": session.multi_capture_session_id,
                "artifact_count": len(session.artifact_ids),
                "raw_image_included": False,
                "action_executed": False,
            },
        )
        return session

    def create_comparison_request(
        self,
        *,
        user_request_id: str,
        user_question: str,
        multi_capture_session_id: str | None = None,
        artifact_ids: list[str] | None = None,
    ) -> CameraComparisonRequest:
        session = (
            self.get_multi_capture_session(multi_capture_session_id)
            if multi_capture_session_id
            else None
        )
        classification = classify_camera_comparison_request(user_question)
        if session is not None:
            artifacts = list(session.artifact_ids)
            slot_ids = [slot.slot_id for slot in session.captured_slots]
            mode = session.comparison_mode
            helper_category = session.helper_category or classification.helper_category
            helper_family = session.helper_family or classification.helper_family
        else:
            artifacts = list(artifact_ids or [])
            slot_ids = list(classification.slot_ids[: len(artifacts)])
            mode = classification.comparison_mode
            helper_category = classification.helper_category
            helper_family = classification.helper_family
        provider_kind = self.vision_provider.provider_kind
        request = CameraComparisonRequest(
            user_request_id=user_request_id,
            multi_capture_session_id=multi_capture_session_id,
            artifact_ids=artifacts,
            slot_ids=slot_ids,
            comparison_mode=mode,
            helper_category=helper_category,
            helper_family=helper_family,
            user_question=user_question,
            normalized_question=_normalize_question(user_question),
            provider_kind=provider_kind,
            mock_comparison=provider_kind == "mock",
            cloud_analysis_requested=_vision_provider_requires_cloud(self.vision_provider),
        )
        self._last_comparison_request = request
        self.telemetry.emit(
            "camera.comparison_requested",
            "Camera comparison requested.",
            session_id=session.session_id if session else None,
            payload={
                **request.to_dict(),
                "artifact_count": len(request.artifact_ids),
                "raw_image_included": False,
                "visual_evidence_only": True,
                "verified_outcome": False,
                "action_executed": False,
            },
        )
        return request

    def analyze_comparison_with_selected_provider(
        self,
        request: CameraComparisonRequest,
        *,
        cloud_analysis_confirmed: bool | None = None,
        at: datetime | None = None,
    ) -> CameraComparisonResult:
        session = (
            self.get_multi_capture_session(request.multi_capture_session_id, at=at)
            if request.multi_capture_session_id
            else None
        )
        if session is not None:
            session.status = CameraMultiCaptureSessionStatus.COMPARING
            self._last_multi_capture_session = session
        summaries, error_code = self._comparison_artifact_summaries(request, at=at)
        if error_code is not None:
            result = self._blocked_comparison_result(request, summaries, error_code)
            self._remember_comparison_result(result, session=session)
            return result

        cloud_requested = _vision_provider_requires_cloud(self.vision_provider)
        policy = self.policy.evaluate_vision_request(
            cloud_analysis_requested=cloud_requested,
            user_confirmed=cloud_analysis_confirmed,
            extra={"reason_schema": "c6"},
        )
        self._last_cloud_analysis_allowed = policy.cloud_analysis_allowed
        self.telemetry.emit(
            "camera.comparison_policy_checked",
            "Camera comparison policy checked.",
            session_id=session.session_id if session else None,
            payload={
                **policy.to_dict(),
                "comparison_request_id": request.comparison_request_id,
                "provider_kind": self.vision_provider.provider_kind,
                "cloud_analysis_requested": cloud_requested,
                "cloud_analysis_performed": False,
                "raw_image_included": False,
                "visual_evidence_only": True,
                "verified_outcome": False,
                "action_executed": False,
            },
        )
        if not policy.allowed:
            reason = "comparison_confirmation_required" if policy.requires_user_confirmation else "comparison_cloud_blocked"
            result = self._blocked_comparison_result(request, summaries, reason)
            self._remember_comparison_result(result, session=session)
            return result

        self.telemetry.emit(
            "camera.comparison_provider_selected",
            "Camera comparison provider selected.",
            session_id=session.session_id if session else None,
            payload={
                "comparison_request_id": request.comparison_request_id,
                "provider_kind": self.vision_provider.provider_kind,
                "mock_comparison": self.vision_provider.provider_kind == "mock",
                "cloud_analysis_performed": False,
                "network_access_attempted": bool(
                    getattr(self.vision_provider, "network_access_attempted", False)
                ),
                "raw_image_included": False,
                "visual_evidence_only": True,
                "verified_outcome": False,
                "action_executed": False,
            },
        )
        if self.vision_provider.provider_kind != "mock":
            result = self._blocked_comparison_result(
                request,
                summaries,
                "comparison_provider_unavailable",
            )
            self._remember_comparison_result(result, session=session)
            return result

        result = _mock_comparison_result(
            request,
            summaries,
            provider_kind=self.vision_provider.provider_kind,
        )
        self._remember_comparison_result(result, session=session)
        self.telemetry.emit(
            "camera.comparison_completed",
            "Camera comparison completed.",
            session_id=session.session_id if session else None,
            payload={
                **result.to_dict(),
                "artifact_count": len(result.artifact_summaries),
                "raw_image_included": False,
                "visual_evidence_only": True,
                "verified_outcome": False,
                "action_executed": False,
            },
        )
        return result

    def _comparison_artifact_summaries(
        self,
        request: CameraComparisonRequest,
        *,
        at: datetime | None = None,
    ) -> tuple[list[CameraComparisonArtifactSummary], str | None]:
        if len(request.artifact_ids) < 2:
            return [], "comparison_requires_at_least_two_artifacts"
        summaries: list[CameraComparisonArtifactSummary] = []
        for index, artifact_id in enumerate(request.artifact_ids):
            artifact = self.artifacts.peek(artifact_id)
            readiness = build_artifact_readiness(
                artifact,
                image_artifact_id=artifact_id,
                at=at,
                max_size_bytes=_max_artifact_bytes(self.config),
            )
            slot_id = request.slot_ids[index] if index < len(request.slot_ids) else f"artifact_{index + 1}"
            summary = CameraComparisonArtifactSummary(
                artifact_id=artifact_id,
                slot_id=slot_id,
                label=_slot_label(slot_id),
                safe_preview_ref=f"camera-artifact:{artifact_id}" if readiness.ready else "",
                source_provenance=readiness.artifact_source_provenance,
                storage_mode=readiness.storage_mode,
                artifact_format=readiness.artifact_format,
                artifact_size_bytes=readiness.artifact_size_bytes,
                ready=readiness.ready,
                artifact_exists=readiness.artifact_exists,
                artifact_readable=readiness.artifact_readable,
                artifact_expired=readiness.artifact_expired,
                reason_code=readiness.reason_code,
                raw_image_included=False,
            )
            summaries.append(summary)
            if not readiness.ready:
                return summaries, _comparison_error_for_readiness(readiness.reason_code)
        return summaries, None

    def _blocked_comparison_result(
        self,
        request: CameraComparisonRequest,
        summaries: list[CameraComparisonArtifactSummary],
        error_code: str,
    ) -> CameraComparisonResult:
        return CameraComparisonResult(
            comparison_request_id=request.comparison_request_id,
            status=CameraComparisonStatus.BLOCKED,
            title="Camera Comparison Blocked",
            concise_answer=_comparison_blocked_text(error_code, summaries),
            comparison_mode=request.comparison_mode,
            artifact_summaries=summaries,
            confidence_kind="insufficient",
            helper_category=request.helper_category,
            helper_family=request.helper_family,
            similarities=[],
            differences=[],
            evidence_summary="Comparison was blocked before provider use.",
            uncertainty_reasons=[error_code],
            caveats=["No visual comparison was performed."],
            suggested_next_capture="Retake or restore the blocked image if you want a fresh comparison.",
            provider_kind=self.vision_provider.provider_kind,
            mock_comparison=self.vision_provider.provider_kind == "mock",
            cloud_analysis_performed=False,
            visual_evidence_only=True,
            verified_outcome=False,
            action_executed=False,
            raw_image_included=False,
            error_code=error_code,
        )

    def _remember_comparison_result(
        self,
        result: CameraComparisonResult,
        *,
        session: CameraMultiCaptureSession | None,
    ) -> None:
        self._last_comparison_result = result
        if session is not None:
            session.status = (
                CameraMultiCaptureSessionStatus.COMPLETED
                if result.status == CameraComparisonStatus.COMPLETED
                else CameraMultiCaptureSessionStatus.FAILED
            )
            session.cloud_analysis_performed = result.cloud_analysis_performed
            session.error_code = result.error_code
            self._last_multi_capture_session = session

    def status_snapshot(self) -> dict[str, object]:
        provider_kind = self.capture_provider.provider_kind
        vision_provider_kind = self.vision_provider.provider_kind
        storage_mode = self._last_artifact_storage_mode or str(
            self.config.default_storage_mode or "ephemeral"
        )
        provider_unavailable_reason = (
            getattr(self.capture_provider, "reason", None)
            if provider_kind == "unavailable"
            else getattr(self.capture_provider, "backend_unavailable_reason", None)
        )
        vision_unavailable_reason = (
            getattr(self.vision_provider, "reason", None)
            if vision_provider_kind == "unavailable"
            else getattr(getattr(self.vision_provider, "last_availability", None), "reason", None)
        )
        vision_availability = getattr(self.vision_provider, "get_availability", None)
        if callable(vision_availability):
            availability = vision_availability()
        else:
            availability = None
        readiness = self._last_artifact_readiness
        latest_artifact_id = self.artifacts.latest_artifact_id
        if latest_artifact_id and (
            readiness is None or readiness.image_artifact_id != latest_artifact_id
        ):
            readiness = self.get_artifact_readiness(latest_artifact_id, emit_event=False)
        cleanup = self._last_cleanup_result
        artifact_fresh = bool(
            readiness.ready
            if readiness is not None
            else self._last_artifact_storage_mode and not self._last_artifact_expired
        )
        helper = self._last_helper_result
        multi_session = self._last_multi_capture_session
        comparison = self._last_comparison_result
        return {
            "enabled": bool(self.config.enabled),
            "route_family": ROUTE_FAMILY_CAMERA_AWARENESS,
            "providerKind": provider_kind,
            "provider_kind": provider_kind,
            "captureProviderKind": provider_kind,
            "capture_provider_kind": provider_kind,
            "visionProviderKind": vision_provider_kind,
            "vision_provider_kind": vision_provider_kind,
            "configuredCaptureProvider": str(self.config.capture.provider),
            "configured_capture_provider": str(self.config.capture.provider),
            "configuredVisionProvider": str(self.config.vision.provider),
            "configured_vision_provider": str(self.config.vision.provider),
            "providerUnavailableReason": provider_unavailable_reason,
            "provider_unavailable_reason": provider_unavailable_reason,
            "visionUnavailableReason": vision_unavailable_reason,
            "vision_unavailable_reason": vision_unavailable_reason,
            "visionProviderAvailable": bool(
                availability.available if availability is not None else vision_provider_kind != "unavailable"
            ),
            "vision_provider_available": bool(
                availability.available if availability is not None else vision_provider_kind != "unavailable"
            ),
            "cloudAnalysisAllowed": self._last_cloud_analysis_allowed,
            "cloud_analysis_allowed": self._last_cloud_analysis_allowed,
            "cloudAnalysisPerformed": self._last_cloud_analysis_performed,
            "cloud_analysis_performed": self._last_cloud_analysis_performed,
            "lastVisionStatus": self._last_vision_status.value
            if self._last_vision_status is not None
            else None,
            "last_vision_status": self._last_vision_status.value
            if self._last_vision_status is not None
            else None,
            "lastVisionConfidence": self._last_vision_confidence,
            "last_vision_confidence": self._last_vision_confidence,
            "lastVisionErrorCode": self._last_vision_error_code,
            "last_vision_error_code": self._last_vision_error_code,
            "lastHelperCategory": helper.category.value if helper is not None else None,
            "last_helper_category": helper.category.value if helper is not None else None,
            "lastHelperFamily": helper.helper_family.value if helper is not None else None,
            "last_helper_family": helper.helper_family.value if helper is not None else None,
            "lastHelperConfidence": helper.confidence_kind.value if helper is not None else None,
            "last_helper_confidence": helper.confidence_kind.value if helper is not None else None,
            "lastHelperVerifiedMeasurement": bool(helper.verified_measurement)
            if helper is not None
            else False,
            "last_helper_verified_measurement": bool(helper.verified_measurement)
            if helper is not None
            else False,
            "lastHelperActionExecuted": bool(helper.action_executed)
            if helper is not None
            else False,
            "last_helper_action_executed": bool(helper.action_executed)
            if helper is not None
            else False,
            "lastMultiCaptureSessionId": multi_session.multi_capture_session_id
            if multi_session is not None
            else None,
            "last_multi_capture_session_id": multi_session.multi_capture_session_id
            if multi_session is not None
            else None,
            "lastMultiCaptureSessionStatus": multi_session.status.value
            if multi_session is not None
            else None,
            "last_multi_capture_session_status": multi_session.status.value
            if multi_session is not None
            else None,
            "lastMultiCaptureSlotCount": len(multi_session.expected_slots)
            if multi_session is not None
            else 0,
            "last_multi_capture_slot_count": len(multi_session.expected_slots)
            if multi_session is not None
            else 0,
            "lastMultiCaptureArtifactCount": len(multi_session.artifact_ids)
            if multi_session is not None
            else 0,
            "last_multi_capture_artifact_count": len(multi_session.artifact_ids)
            if multi_session is not None
            else 0,
            "lastComparisonStatus": comparison.status.value if comparison is not None else None,
            "last_comparison_status": comparison.status.value if comparison is not None else None,
            "lastComparisonMode": comparison.comparison_mode.value
            if comparison is not None
            else None,
            "last_comparison_mode": comparison.comparison_mode.value
            if comparison is not None
            else None,
            "lastComparisonVisualEvidenceOnly": bool(comparison.visual_evidence_only)
            if comparison is not None
            else False,
            "last_comparison_visual_evidence_only": bool(comparison.visual_evidence_only)
            if comparison is not None
            else False,
            "lastComparisonVerifiedOutcome": bool(comparison.verified_outcome)
            if comparison is not None
            else False,
            "last_comparison_verified_outcome": bool(comparison.verified_outcome)
            if comparison is not None
            else False,
            "lastComparisonActionExecuted": bool(comparison.action_executed)
            if comparison is not None
            else False,
            "last_comparison_action_executed": bool(comparison.action_executed)
            if comparison is not None
            else False,
            "mockMode": provider_kind == "mock"
            and vision_provider_kind == "mock",
            "mock_mode": provider_kind == "mock"
            and vision_provider_kind == "mock",
            "mockCapture": self._last_mock_capture,
            "mock_capture": self._last_mock_capture,
            "realCameraUsed": self._last_real_camera_used,
            "real_camera_used": self._last_real_camera_used,
            "cloudUploadPerformed": self._last_cloud_upload_performed,
            "cloud_upload_performed": self._last_cloud_upload_performed,
            "rawImageIncluded": self._last_raw_image_included,
            "raw_image_included": self._last_raw_image_included,
            "storageMode": storage_mode,
            "storage_mode": storage_mode,
            "active": self._active,
            "cameraActive": bool(
                self._active or getattr(self.capture_provider, "active", False)
            ),
            "camera_active": bool(
                self._active or getattr(self.capture_provider, "active", False)
            ),
            "providerActive": bool(getattr(self.capture_provider, "active", False)),
            "provider_active": bool(getattr(self.capture_provider, "active", False)),
            "permissionState": "granted"
            if provider_kind == "mock"
            else "unknown"
            if provider_kind == "local"
            else "unavailable",
            "permission_state": "granted"
            if provider_kind == "mock"
            else "unknown"
            if provider_kind == "local"
            else "unavailable",
            "backendKind": getattr(self.capture_provider, "backend_kind", None),
            "backend_kind": getattr(self.capture_provider, "backend_kind", None),
            "backendAvailable": getattr(self.capture_provider, "backend_available", None),
            "backend_available": getattr(self.capture_provider, "backend_available", None),
            "lastDeviceId": getattr(self.capture_provider, "last_device_id", None),
            "last_device_id": getattr(self.capture_provider, "last_device_id", None),
            "lastResultState": self._last_result_state.value
            if self._last_result_state is not None
            else None,
            "lastCaptureSource": self._last_capture_source,
            "lastArtifactStorageMode": self._last_artifact_storage_mode,
            "latestArtifactId": latest_artifact_id,
            "latest_artifact_id": latest_artifact_id,
            "lastArtifactExpired": self._last_artifact_expired,
            "lastArtifactFresh": artifact_fresh,
            "lastSourceProvenance": self._last_source_provenance,
            "artifactExists": bool(readiness.artifact_exists) if readiness else False,
            "artifact_exists": bool(readiness.artifact_exists) if readiness else False,
            "artifactReadable": bool(readiness.artifact_readable) if readiness else False,
            "artifact_readable": bool(readiness.artifact_readable) if readiness else False,
            "artifactExpired": bool(readiness.artifact_expired)
            if readiness
            else self._last_artifact_expired,
            "artifact_expired": bool(readiness.artifact_expired)
            if readiness
            else self._last_artifact_expired,
            "artifactSizeBytes": readiness.artifact_size_bytes if readiness else None,
            "artifact_size_bytes": readiness.artifact_size_bytes if readiness else None,
            "artifactFormat": readiness.artifact_format if readiness else "unknown",
            "artifact_format": readiness.artifact_format if readiness else "unknown",
            "artifactSourceProvenance": readiness.artifact_source_provenance
            if readiness
            else self._last_source_provenance,
            "artifact_source_provenance": readiness.artifact_source_provenance
            if readiness
            else self._last_source_provenance,
            "cleanupPending": bool(
                (cleanup and cleanup.cleanup_pending)
                or (readiness and readiness.cleanup_pending)
            ),
            "cleanup_pending": bool(
                (cleanup and cleanup.cleanup_pending)
                or (readiness and readiness.cleanup_pending)
            ),
            "cleanupFailed": bool(
                (cleanup and cleanup.cleanup_failed)
                or (readiness and readiness.cleanup_failed)
            ),
            "cleanup_failed": bool(
                (cleanup and cleanup.cleanup_failed)
                or (readiness and readiness.cleanup_failed)
            ),
            "backgroundCaptureAllowed": bool(self.config.allow_background_capture),
            "background_capture_allowed": bool(self.config.allow_background_capture),
            "captureAttempted": bool(getattr(self.capture_provider, "capture_attempted", False)),
            "capture_attempted": bool(getattr(self.capture_provider, "capture_attempted", False)),
            "hardwareAccessAttempted": bool(
                getattr(self.capture_provider, "hardware_access_attempted", False)
            ),
            "hardware_access_attempted": bool(
                getattr(self.capture_provider, "hardware_access_attempted", False)
            ),
            "deviceReleaseCount": int(getattr(self.capture_provider, "release_count", 0)),
            "device_release_count": int(getattr(self.capture_provider, "release_count", 0)),
            "realCameraImplemented": provider_kind == "local",
            "openaiVisionImplemented": False,
            "warnings": list(self._warnings),
        }

    def _build_capture_provider(self):
        provider = str(self.config.capture.provider).strip().lower() or "mock"
        if provider == "mock" and self.config.dev.mock_capture_enabled:
            return MockCameraCaptureProvider(self.config)
        if provider == "mock":
            return UnavailableCameraCaptureProvider(
                reason="mock_capture_disabled",
                configured_provider=provider,
            )
        if provider in {"local", "real", "system", "webcam", "default", "windows"}:
            return LocalCameraCaptureProvider(self.config)
        return UnavailableCameraCaptureProvider(
            reason="unknown_capture_provider",
            configured_provider=provider,
        )

    def _build_vision_provider(self):
        provider = str(self.config.vision.provider).strip().lower() or "mock"
        if provider == "mock" and self.config.dev.mock_vision_enabled:
            return MockVisionAnalysisProvider(self.config)
        if provider == "mock":
            return UnavailableVisionAnalysisProvider(reason="mock_vision_disabled")
        if provider in {"openai", "cloud", "real"}:
            return OpenAIVisionAnalysisProvider(
                self.config,
                openai_config=self.openai_config,
                responses_provider=self.responses_provider,
            )
        if provider == "local":
            return UnavailableVisionAnalysisProvider(reason="local_vision_not_implemented")
        return UnavailableVisionAnalysisProvider(reason="unknown_vision_provider")

    def _apply_helper_result(
        self,
        *,
        user_question: str,
        answer: CameraVisionAnswer,
        session_id: str | None,
    ) -> CameraEngineeringHelperResult | None:
        if answer.result_state != CameraAwarenessResultState.CAMERA_ANSWER_READY:
            self._last_helper_result = None
            return None
        classification = self.helper_registry.classify(
            user_question=user_question,
            vision_answer=answer,
        )
        if not classification.applicable:
            self._last_helper_result = None
            return None
        self.telemetry.emit(
            "camera.engineering_helper_classified",
            "Camera engineering helper classified.",
            session_id=session_id,
            payload={
                **classification.to_dict(),
                "vision_answer_id": answer.vision_answer_id,
                "image_artifact_id": answer.image_artifact_id,
                "provider_kind": answer.provider_kind,
                "mock_analysis": answer.mock_answer,
                "cloud_analysis_performed": answer.cloud_analysis_performed,
                "verified_measurement": False,
                "action_executed": False,
                "raw_image_included": False,
            },
        )
        result = self.helper_registry.build_result(
            user_question=user_question,
            vision_answer=answer,
        )
        if result is None:
            self._last_helper_result = None
            return None
        self._last_helper_result = result
        self.telemetry.emit(
            "camera.engineering_helper_completed",
            "Camera engineering helper result completed.",
            session_id=session_id,
            payload={
                **result.to_dict(),
                "verified_measurement": False,
                "action_executed": False,
                "trust_approved": False,
                "task_mutation_performed": False,
                "raw_image_included": False,
            },
        )
        return result

    def _remember_flow_truth(self, flow: CameraAwarenessFlowResult) -> None:
        self._last_result_state = flow.result_state
        self._last_mock_capture = bool(flow.capture_result.mock_capture)
        self._last_real_camera_used = bool(
            flow.capture_result.real_camera_used or flow.trace.real_camera_used
        )
        self._last_cloud_upload_performed = bool(
            flow.capture_result.cloud_upload_performed
            or flow.trace.cloud_upload_performed
            or flow.vision_answer.cloud_upload_performed
        )
        self._last_raw_image_included = bool(flow.trace.raw_image_included)
        self._last_source_provenance = flow.trace.source_provenance
        self._last_vision_status = flow.vision_answer.result_state
        self._last_vision_confidence = flow.vision_answer.confidence.value
        self._last_vision_error_code = flow.vision_answer.error_code
        self._last_cloud_analysis_performed = bool(
            flow.vision_answer.cloud_analysis_performed
            or flow.vision_answer.cloud_upload_performed
        )
        self._last_helper_result = flow.helper_result
        if flow.artifact is not None:
            self._last_artifact_storage_mode = flow.artifact.storage_mode.value
            self._last_artifact_expired = False
        else:
            self._last_artifact_storage_mode = flow.trace.storage_mode.value

    def _blocked_flow(
        self,
        request: CameraCaptureRequest,
        policy_result: CameraAwarenessPolicyResult,
        *,
        session_id: str | None,
    ) -> CameraAwarenessFlowResult:
        capture_result = CameraCaptureResult(
            request_id=request.capture_request_id,
            status=CameraCaptureStatus.BLOCKED,
            error_code=policy_result.blocked_reason,
            error_message=f"Camera capture blocked: {policy_result.blocked_reason}",
            raw_image_persisted=False,
            cloud_upload_performed=False,
            mock_capture=False,
            real_camera_used=False,
            source_provenance="camera_policy",
        )
        question = CameraVisionQuestion(
            image_artifact_id="no-artifact",
            user_question=request.user_question,
            normalized_question=_normalize_question(request.user_question),
            analysis_mode=_analysis_mode(request.user_question),
            provider="unavailable",
            model="unavailable",
        )
        answer = CameraVisionAnswer(
            vision_question_id=question.vision_question_id,
            image_artifact_id="no-artifact",
            answer_text=f"Camera capture was blocked: {policy_result.blocked_reason}.",
            concise_answer="Camera capture blocked.",
            confidence="insufficient",
            result_state=policy_result.result_state
            or CameraAwarenessResultState.CAMERA_CAPTURE_BLOCKED,
            provider="unavailable",
            model="unavailable",
            analysis_mode=question.analysis_mode,
            mock_answer=False,
            provenance={
                "source": "camera_policy",
                "blocked_reason": policy_result.blocked_reason,
                "cloud_upload_performed": False,
                "real_camera_used": False,
            },
            cloud_upload_performed=False,
        )
        trace = CameraObservationTrace(
            capture_request_id=request.capture_request_id,
            capture_result_id=capture_result.capture_result_id,
            result_state=answer.result_state,
            source_provenance="camera_policy",
            provider_kind="policy",
            policy_allowed=False,
            blocked_reason=policy_result.blocked_reason,
            mock_mode=False,
        )
        self.telemetry.emit(
            "camera.capture_blocked",
            "Camera capture blocked by policy.",
            session_id=session_id,
            payload=trace.to_dict(),
        )
        return CameraAwarenessFlowResult(
            capture_request=request,
            policy_result=policy_result,
            capture_result=capture_result,
            artifact=None,
            vision_question=question,
            vision_answer=answer,
            trace=trace,
            result_state=answer.result_state,
            response_text=answer.answer_text,
        )

    def _vision_blocked_flow(
        self,
        request: CameraCaptureRequest,
        capture_policy_result: CameraAwarenessPolicyResult,
        vision_policy_result: CameraAwarenessPolicyResult,
        capture_result: CameraCaptureResult,
        artifact: CameraFrameArtifact | None,
        *,
        session_id: str | None,
        blocked_reason: str | None = None,
    ) -> CameraAwarenessFlowResult:
        del capture_policy_result
        reason = blocked_reason or vision_policy_result.blocked_reason or "camera_vision_blocked"
        question = CameraVisionQuestion(
            image_artifact_id=artifact.image_artifact_id if artifact is not None else "missing-artifact",
            user_question=request.user_question,
            normalized_question=_normalize_question(request.user_question),
            analysis_mode=_analysis_mode(request.user_question),
            provider="unavailable",
            model="unavailable",
            cloud_analysis_allowed=vision_policy_result.cloud_analysis_allowed,
            mock_analysis=False,
        )
        state = vision_policy_result.result_state or _result_state_for_readiness(reason)
        answer = CameraVisionAnswer(
            vision_question_id=question.vision_question_id,
            image_artifact_id=question.image_artifact_id,
            answer_text=_vision_blocked_text(reason),
            concise_answer="Camera vision analysis blocked.",
            confidence="insufficient",
            result_state=state,
            provider="unavailable",
            provider_kind="unavailable",
            model="unavailable",
            analysis_mode=question.analysis_mode,
            mock_answer=False,
            cloud_upload_performed=False,
            cloud_analysis_performed=False,
            raw_image_included=False,
            evidence_summary="",
            uncertainty_reasons=[reason],
            error_code=reason,
            provenance={
                "source": artifact.source_provenance if artifact is not None else "camera_unavailable",
                "reason": reason,
                "provider": "unavailable",
                "provider_kind": "unavailable",
                "cloud_upload_performed": False,
                "cloud_analysis_performed": False,
                "raw_image_included": False,
            },
        )
        trace = CameraObservationTrace(
            capture_request_id=request.capture_request_id,
            capture_result_id=capture_result.capture_result_id,
            image_artifact_id=artifact.image_artifact_id if artifact is not None else None,
            vision_question_id=question.vision_question_id,
            vision_answer_id=answer.vision_answer_id,
            result_state=answer.result_state,
            source_provenance=artifact.source_provenance if artifact is not None else "camera_unavailable",
            provider_kind=self.capture_provider.provider_kind,
            storage_mode=artifact.storage_mode if artifact is not None else CameraStorageMode.EPHEMERAL,
            policy_allowed=False,
            blocked_reason=reason,
            raw_image_included=False,
            raw_image_persisted=False,
            cloud_upload_performed=False,
            real_camera_used=capture_result.real_camera_used,
            mock_mode=False,
        )
        self.telemetry.emit(
            "camera.vision_blocked",
            "Camera vision analysis blocked.",
            session_id=session_id,
            payload={
                **trace.to_dict(),
                "error_code": reason,
                "provider_kind": self.vision_provider.provider_kind,
                "cloud_analysis_performed": False,
                "raw_image_included": False,
            },
        )
        self.telemetry.emit(
            "camera.answer_ready",
            "Camera awareness answer ready.",
            session_id=session_id,
            payload=trace.to_dict(),
        )
        return CameraAwarenessFlowResult(
            capture_request=request,
            policy_result=vision_policy_result,
            capture_result=capture_result,
            artifact=artifact,
            vision_question=question,
            vision_answer=answer,
            trace=trace,
            result_state=answer.result_state,
            response_text=answer.answer_text,
        )

    def _capture_failed_flow(
        self,
        request: CameraCaptureRequest,
        policy_result: CameraAwarenessPolicyResult,
        capture_result: CameraCaptureResult,
        *,
        session_id: str | None,
    ) -> CameraAwarenessFlowResult:
        question = CameraVisionQuestion(
            image_artifact_id="missing-artifact",
            user_question=request.user_question,
            normalized_question=_normalize_question(request.user_question),
            analysis_mode=_analysis_mode(request.user_question),
            provider="unavailable",
            model="unavailable",
        )
        answer = UnavailableVisionAnalysisProvider(
            reason=capture_result.error_code or "capture_failed"
        ).analyze_image(question, None)
        trace = CameraObservationTrace(
            capture_request_id=request.capture_request_id,
            capture_result_id=capture_result.capture_result_id,
            result_state=answer.result_state,
            source_provenance=capture_result.source_provenance,
            provider_kind=self.capture_provider.provider_kind,
            policy_allowed=policy_result.allowed,
            blocked_reason=capture_result.error_code,
            real_camera_used=capture_result.real_camera_used,
            mock_mode=False,
        )
        self.telemetry.emit(
            "camera.capture_failed",
            "Camera capture failed.",
            session_id=session_id,
            payload=trace.to_dict(),
        )
        return CameraAwarenessFlowResult(
            capture_request=request,
            policy_result=policy_result,
            capture_result=capture_result,
            artifact=None,
            vision_question=question,
            vision_answer=answer,
            trace=trace,
            result_state=answer.result_state,
            response_text=answer.answer_text,
        )


def _camera_ttl(config: CameraAwarenessConfig):
    try:
        seconds = int(config.auto_discard_after_seconds)
    except (TypeError, ValueError):
        seconds = 300
    return timedelta(seconds=max(1, seconds))


def _slot_id(label: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(label or "").strip().lower()).strip("_")
    return text or "slot"


def _slot_label(slot_id: str | None) -> str:
    text = str(slot_id or "artifact").replace("_", " ").strip()
    return text.title() if text else "Artifact"


def _find_slot(session: CameraMultiCaptureSession, slot_id: str) -> CameraCaptureSlot | None:
    normalized = _slot_id(slot_id)
    for slot in session.expected_slots:
        if slot.slot_id == normalized or _slot_id(slot.label) == normalized:
            return slot
    return None


def _refresh_session_slot_state(session: CameraMultiCaptureSession) -> None:
    captured = [
        slot
        for slot in session.expected_slots
        if slot.status == CameraCaptureSlotStatus.CAPTURED and slot.artifact_id
    ]
    session.captured_slots = captured
    session.artifact_ids = [str(slot.artifact_id) for slot in captured if slot.artifact_id]
    pending = [slot for slot in session.expected_slots if slot.status == CameraCaptureSlotStatus.PENDING]
    session.current_slot_id = pending[0].slot_id if pending else None
    if len(session.artifact_ids) >= 2 and not pending:
        session.status = CameraMultiCaptureSessionStatus.READY_TO_COMPARE
    else:
        session.status = CameraMultiCaptureSessionStatus.ACTIVE


def _comparison_error_for_readiness(reason_code: str | None) -> str:
    mapping = {
        "camera_artifact_missing": "comparison_artifact_missing",
        "camera_artifact_missing_metadata": "comparison_artifact_missing",
        "camera_artifact_expired": "comparison_artifact_expired",
        "camera_artifact_unreadable": "comparison_artifact_unreadable",
        "camera_artifact_unsupported_format": "comparison_artifact_unsupported_format",
        "camera_artifact_too_large": "comparison_artifact_too_large",
    }
    return mapping.get(str(reason_code or ""), "comparison_artifact_missing")


def _comparison_blocked_text(
    error_code: str,
    summaries: list[CameraComparisonArtifactSummary],
) -> str:
    label = next((summary.label for summary in summaries if not summary.ready), "")
    if error_code == "comparison_requires_at_least_two_artifacts":
        return "I need at least two fresh camera stills to compare."
    if error_code == "comparison_artifact_expired":
        return f"The {label or 'requested'} image has expired, so I cannot compare it."
    if error_code == "comparison_artifact_missing":
        return f"The {label or 'requested'} image is missing, so I cannot compare it."
    if error_code == "comparison_artifact_unreadable":
        return f"The {label or 'requested'} image is not readable, so I cannot compare it."
    if error_code == "comparison_artifact_unsupported_format":
        return f"The {label or 'requested'} image format is not supported for comparison."
    if error_code == "comparison_artifact_too_large":
        return f"The {label or 'requested'} image is too large for comparison."
    if error_code == "comparison_confirmation_required":
        return "Cloud comparison needs explicit confirmation before any image leaves the device."
    if error_code == "comparison_cloud_blocked":
        return "Cloud comparison is disabled by policy. No provider request was made."
    return "Camera comparison was blocked before provider use."


def _mock_comparison_result(
    request: CameraComparisonRequest,
    summaries: list[CameraComparisonArtifactSummary],
    *,
    provider_kind: str,
) -> CameraComparisonResult:
    mode = CameraComparisonMode(request.comparison_mode)
    engineering_solder = request.helper_family == "engineering.solder_joint_inspection"
    if mode == CameraComparisonMode.BEFORE_AFTER:
        title = "Before/After Visual Comparison"
        concise = "The after image appears cleaner around the area, but this is visual evidence only."
        differences = ["The after still appears smoother and has less visible roughness in the inspected area."]
        similarities = ["Both stills appear to show the same target area."]
        next_capture = "Retake both stills from the same angle and lighting if you need a stronger comparison."
    elif mode == CameraComparisonMode.FRONT_BACK:
        title = "Front/Back Visual Comparison"
        concise = "The stills show different sides of the object; visible findings remain side-specific."
        differences = ["One still emphasizes component-side context; the other emphasizes reverse-side details."]
        similarities = ["Both stills are part of the same bounded multi-capture session."]
        next_capture = "Retake with matching framing if the two sides need spatial correlation."
    elif mode == CameraComparisonMode.QUALITY_COMPARE:
        title = "Photo Quality Comparison"
        concise = "One still appears more useful for analysis, but this is only a mock visual comparison."
        differences = ["The second labeled still is treated as clearer in the deterministic mock comparison."]
        similarities = ["Both stills are available as fresh comparison artifacts."]
        next_capture = "Use the clearer still for analysis or retake with less glare and sharper focus."
    else:
        title = "Camera Visual Comparison"
        concise = "The labeled stills were compared as visual evidence only."
        differences = ["The deterministic mock comparison reports visible differences between labeled stills."]
        similarities = ["The compared artifacts are fresh, readable, and provenance-labeled."]
        next_capture = "Retake with consistent angle, scale, and lighting if the comparison matters."
    suggested_measurements = []
    if engineering_solder:
        suggested_measurements = ["Check continuity with a multimeter before treating the joint as repaired."]
    caveats = [
        "Visual comparison is evidence only, not verification.",
        "Lighting, angle, focus, and scale can change apparent differences.",
    ]
    return CameraComparisonResult(
        comparison_request_id=request.comparison_request_id,
        status=CameraComparisonStatus.COMPLETED,
        title=title,
        concise_answer=concise,
        detailed_answer=(
            f"{concise} Stormhelm did not verify repair state, measurements, or task completion."
        ),
        comparison_mode=mode,
        helper_category=request.helper_category,
        helper_family=request.helper_family,
        artifact_summaries=summaries,
        similarities=similarities,
        differences=differences,
        changed_regions=["Textual comparison only; no overlay generated."],
        confidence_kind=CameraConfidenceLevel.MEDIUM,
        evidence_summary="Deterministic mock comparison of authorized labeled still artifacts.",
        uncertainty_reasons=["Mock comparison; no real image model was called.", "Single stills can differ by angle and lighting."],
        caveats=caveats,
        suggested_next_capture=next_capture,
        suggested_measurements=suggested_measurements,
        suggested_user_actions=[
            "Use the comparison as visual evidence, not command authority.",
            "Verify critical outcomes with an appropriate subsystem or instrument.",
        ],
        source_provenance=list(dict.fromkeys(summary.source_provenance for summary in summaries)),
        provider_kind=provider_kind,
        mock_comparison=True,
        cloud_analysis_performed=False,
        visual_evidence_only=True,
        verified_outcome=False,
        action_executed=False,
        raw_image_included=False,
    )


def build_camera_awareness_subsystem(
    config: CameraAwarenessConfig,
    *,
    events: EventBuffer | None = None,
    openai_config: OpenAIConfig | None = None,
    responses_provider: AssistantProvider | None = None,
) -> CameraAwarenessSubsystem:
    return CameraAwarenessSubsystem(
        config,
        events=events,
        openai_config=openai_config,
        responses_provider=responses_provider,
    )


def _normalize_question(question: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", str(question or "").lower()).split())


def _analysis_mode(question: str) -> CameraAnalysisMode:
    text = _normalize_question(question)
    if re.search(r"\b(?:read|label|text|say)\b", text):
        return CameraAnalysisMode.READ_TEXT
    if re.search(r"\b(?:bad|broken|damage|solder|joint|wrong)\b", text):
        return CameraAnalysisMode.TROUBLESHOOT
    if re.search(r"\b(?:explain|mean|seeing)\b", text):
        return CameraAnalysisMode.EXPLAIN
    if re.search(r"\b(?:what|identify|connector|resistor|part|holding)\b", text):
        return CameraAnalysisMode.IDENTIFY
    if re.search(r"\b(?:look|inspect|check)\b", text):
        return CameraAnalysisMode.INSPECT
    return CameraAnalysisMode.UNKNOWN


def _max_artifact_bytes(config: CameraAwarenessConfig) -> int | None:
    values: list[int] = []
    for value in (
        getattr(config.capture, "max_artifact_bytes", None),
        getattr(config.vision, "max_image_bytes", None),
    ):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            values.append(parsed)
    return min(values) if values else None


def _vision_provider_requires_cloud(provider: VisionAnalysisProvider) -> bool:
    provider_kind = str(getattr(provider, "provider_kind", "") or "").strip().lower()
    return provider_kind in {"openai", "cloud", "real"}


def _result_state_for_readiness(reason: str | None) -> CameraAwarenessResultState:
    mapping = {
        "camera_artifact_missing": CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_MISSING,
        "camera_artifact_missing_metadata": CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_MISSING,
        "camera_artifact_expired": CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_EXPIRED,
        "camera_artifact_unreadable": CameraAwarenessResultState.CAMERA_VISION_ARTIFACT_UNREADABLE,
        "camera_artifact_too_large": CameraAwarenessResultState.CAMERA_VISION_IMAGE_TOO_LARGE,
        "camera_artifact_unsupported_format": CameraAwarenessResultState.CAMERA_VISION_UNSUPPORTED_FORMAT,
        "camera_cloud_analysis_disabled": CameraAwarenessResultState.CAMERA_CLOUD_ANALYSIS_DISABLED,
        "camera_vision_confirmation_required": CameraAwarenessResultState.CAMERA_VISION_PERMISSION_REQUIRED,
    }
    return mapping.get(str(reason or ""), CameraAwarenessResultState.CAMERA_ANALYSIS_FAILED)


def _vision_blocked_text(reason: str) -> str:
    messages = {
        "camera_cloud_analysis_disabled": (
            "I have the camera still, but cloud vision analysis is disabled."
        ),
        "camera_vision_confirmation_required": (
            "I have the camera still, but cloud vision analysis needs explicit confirmation."
        ),
        "camera_artifact_expired": (
            "I no longer have that camera image. I can capture another still if camera access is enabled."
        ),
        "camera_artifact_missing": "That camera image artifact is missing.",
        "camera_artifact_missing_metadata": "That camera image artifact is missing.",
        "camera_artifact_unreadable": "That camera image artifact is not readable.",
        "camera_artifact_too_large": "That camera image is too large for vision analysis.",
        "camera_artifact_unsupported_format": (
            "That camera image format is not supported for vision analysis."
        ),
    }
    return messages.get(reason, f"Camera vision analysis was blocked: {reason}.")
