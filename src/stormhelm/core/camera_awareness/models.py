from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


ROUTE_FAMILY_CAMERA_AWARENESS = "camera_awareness"
CAMERA_SOURCE_PROVENANCE_MOCK = "camera_mock"
CAMERA_SOURCE_PROVENANCE_LOCAL = "camera_local"
CAMERA_SOURCE_PROVENANCE_UNAVAILABLE = "camera_unavailable"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def camera_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def serialize_camera_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {
            str(key): serialize_camera_value(item)
            for key, item in asdict(value).items()
        }
    if isinstance(value, dict):
        return {str(key): serialize_camera_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize_camera_value(item) for item in value]
    return value


class CameraCaptureSource(StrEnum):
    USER_REQUEST = "user_request"
    VOICE = "voice"
    DECK_ACTION = "deck_action"
    TEST = "test"


class CameraCaptureMode(StrEnum):
    SINGLE_STILL = "single_still"
    RETAKE = "retake"
    MULTI_CAPTURE = "multi_capture"


class CameraPermissionState(StrEnum):
    UNKNOWN = "unknown"
    REQUIRED = "required"
    GRANTED = "granted"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class CameraCaptureStatus(StrEnum):
    CAPTURED = "captured"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PERMISSION_REQUIRED = "permission_required"
    NO_DEVICE = "no_device"
    DEVICE_BUSY = "device_busy"


class CameraStorageMode(StrEnum):
    EPHEMERAL = "ephemeral"
    SESSION = "session"
    TASK = "task"
    SAVED = "saved"


class CameraArtifactPersistenceStatus(StrEnum):
    SAVED = "saved"
    ALREADY_SAVED = "already_saved"
    BLOCKED = "blocked"
    FAILED = "failed"


class CameraAnalysisMode(StrEnum):
    IDENTIFY = "identify"
    READ_TEXT = "read_text"
    INSPECT = "inspect"
    TROUBLESHOOT = "troubleshoot"
    EXPLAIN = "explain"
    GUIDANCE = "guidance"
    UNKNOWN = "unknown"


class CameraConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class CameraHelperCategory(StrEnum):
    ENGINEERING_INSPECTION = "engineering_inspection"
    UNKNOWN = "unknown"


class CameraHelperFamily(StrEnum):
    ENGINEERING_RESISTOR_COLOR_BANDS = "engineering.resistor_color_bands"
    ENGINEERING_CONNECTOR_IDENTIFICATION = "engineering.connector_identification"
    ENGINEERING_COMPONENT_MARKING = "engineering.component_marking"
    ENGINEERING_SOLDER_JOINT_INSPECTION = "engineering.solder_joint_inspection"
    ENGINEERING_PCB_VISUAL_INSPECTION = "engineering.pcb_visual_inspection"
    ENGINEERING_LABEL_READING = "engineering.label_reading"
    ENGINEERING_MECHANICAL_PART_INSPECTION = "engineering.mechanical_part_inspection"
    ENGINEERING_PHOTO_QUALITY_GUIDANCE = "engineering.photo_quality_guidance"
    ENGINEERING_PHYSICAL_TROUBLESHOOTING = "engineering.physical_troubleshooting"
    ENGINEERING_UNKNOWN = "engineering.unknown"
    UNKNOWN = "unknown"


class CameraMultiCaptureSessionStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    READY_TO_COMPARE = "ready_to_compare"
    COMPARING = "comparing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


class CameraCaptureSlotStatus(StrEnum):
    PENDING = "pending"
    CAPTURED = "captured"
    SKIPPED = "skipped"
    EXPIRED = "expired"
    FAILED = "failed"


class CameraComparisonMode(StrEnum):
    BEFORE_AFTER = "before_after"
    FRONT_BACK = "front_back"
    SIDE_BY_SIDE = "side_by_side"
    CLOSEUP_CONTEXT = "closeup_context"
    OPTION_A_B = "option_a_b"
    OLD_NEW = "old_new"
    QUALITY_COMPARE = "quality_compare"
    DIFFERENCE_CHECK = "difference_check"
    SIMILARITY_CHECK = "similarity_check"
    CHANGE_OVER_TIME = "change_over_time"
    GENERAL_COMPARE = "general_compare"


class CameraComparisonStatus(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"


class CameraCaptureQualityIssueKind(StrEnum):
    BLUR = "blur"
    MOTION_BLUR = "motion_blur"
    LOW_LIGHT = "low_light"
    GLARE = "glare"
    OVEREXPOSED = "overexposed"
    UNDEREXPOSED = "underexposed"
    OBJECT_OUT_OF_FRAME = "object_out_of_frame"
    OBJECT_TOO_SMALL = "object_too_small"
    OBJECT_TOO_CLOSE = "object_too_close"
    TEXT_TOO_SMALL = "text_too_small"
    TEXT_BLURRY = "text_blurry"
    LABEL_NOT_CENTERED = "label_not_centered"
    ANGLE_TOO_OBLIQUE = "angle_too_oblique"
    MISSING_SCALE_REFERENCE = "missing_scale_reference"
    MISSING_CONTEXT = "missing_context"
    MISSING_CLOSEUP = "missing_closeup"
    OCCLUDED = "occluded"
    WRONG_SIDE = "wrong_side"
    COMPARISON_ANGLE_MISMATCH = "comparison_angle_mismatch"
    COMPARISON_LIGHTING_MISMATCH = "comparison_lighting_mismatch"
    COMPARISON_SCALE_MISMATCH = "comparison_scale_mismatch"
    UNSUPPORTED_QUALITY_ASSESSMENT = "unsupported_quality_assessment"


class CameraCaptureQualitySeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CameraCaptureGuidanceStatus(StrEnum):
    GUIDANCE_READY = "guidance_ready"
    NOT_NEEDED = "not_needed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BLOCKED = "blocked"
    FAILED = "failed"


class CameraAwarenessResultState(StrEnum):
    CAMERA_ANSWER_READY = "camera_answer_ready"
    CAMERA_PERMISSION_REQUIRED = "camera_permission_required"
    CAMERA_VISION_PERMISSION_REQUIRED = "camera_vision_permission_required"
    CAMERA_CLOUD_ANALYSIS_DISABLED = "camera_cloud_analysis_disabled"
    CAMERA_VISION_PROVIDER_UNAVAILABLE = "camera_vision_provider_unavailable"
    CAMERA_VISION_PROVIDER_AUTH_FAILED = "camera_vision_provider_auth_failed"
    CAMERA_VISION_PROVIDER_RATE_LIMITED = "camera_vision_provider_rate_limited"
    CAMERA_VISION_PROVIDER_TIMEOUT = "camera_vision_provider_timeout"
    CAMERA_VISION_ARTIFACT_MISSING = "camera_vision_artifact_missing"
    CAMERA_VISION_ARTIFACT_EXPIRED = "camera_vision_artifact_expired"
    CAMERA_VISION_ARTIFACT_UNREADABLE = "camera_vision_artifact_unreadable"
    CAMERA_VISION_IMAGE_TOO_LARGE = "camera_vision_image_too_large"
    CAMERA_VISION_UNSUPPORTED_FORMAT = "camera_vision_unsupported_format"
    CAMERA_VISION_PROVIDER_BAD_REQUEST = "camera_vision_provider_bad_request"
    CAMERA_VISION_PROVIDER_SAFETY_BLOCKED = "camera_vision_provider_safety_blocked"
    CAMERA_VISION_PROVIDER_RESPONSE_MALFORMED = "camera_vision_provider_response_malformed"
    CAMERA_CAPTURE_BLOCKED = "camera_capture_blocked"
    CAMERA_CAPTURE_FAILED = "camera_capture_failed"
    CAMERA_NO_DEVICE = "camera_no_device"
    CAMERA_DEVICE_BUSY = "camera_device_busy"
    CAMERA_ANALYSIS_FAILED = "camera_analysis_failed"
    CAMERA_INSUFFICIENT_IMAGE_QUALITY = "camera_insufficient_image_quality"
    CAMERA_NEEDS_RETAKE = "camera_needs_retake"
    CAMERA_CANCELLED = "camera_cancelled"
    CAMERA_ARTIFACT_EXPIRED = "camera_artifact_expired"
    CAMERA_ARTIFACT_SAVED = "camera_artifact_saved"
    CAMERA_ARTIFACT_SAVE_PERMISSION_REQUIRED = "camera_artifact_save_permission_required"
    CAMERA_ARTIFACT_SAVE_BLOCKED = "camera_artifact_save_blocked"
    CAMERA_ARTIFACT_SAVE_FAILED = "camera_artifact_save_failed"
    CAMERA_SAVED_TO_TASK = "camera_saved_to_task"


@dataclass(slots=True)
class CameraDeviceStatus:
    device_id: str
    display_name: str
    provider: str
    available: bool = True
    permission_state: CameraPermissionState = CameraPermissionState.UNKNOWN
    active: bool = False
    mock_device: bool = False
    last_seen_at: datetime = field(default_factory=utc_now)
    source_provenance: str = CAMERA_SOURCE_PROVENANCE_MOCK
    error_code: str | None = None
    error_message: str | None = None
    resolution_options: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.permission_state = CameraPermissionState(self.permission_state)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraCaptureRequest:
    user_request_id: str
    session_id: str | None = None
    task_id: str | None = None
    source: CameraCaptureSource = CameraCaptureSource.USER_REQUEST
    reason: str = ""
    user_question: str = ""
    capture_request_id: str = field(default_factory=lambda: camera_id("camera-capture-req"))
    mode: CameraCaptureMode = CameraCaptureMode.SINGLE_STILL
    device_id: str | None = None
    requested_resolution: str = "1280x720"
    requires_permission: bool = True
    permission_scope_requested: str = "camera.single_still"
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    background_capture: bool = False

    def __post_init__(self) -> None:
        self.source = CameraCaptureSource(self.source)
        self.mode = CameraCaptureMode(self.mode)
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(minutes=5)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraFrameArtifact:
    capture_result_id: str
    storage_mode: CameraStorageMode = CameraStorageMode.EPHEMERAL
    retention_policy: str = "discard_after_ttl"
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    image_artifact_id: str = field(default_factory=lambda: camera_id("camera-frame"))
    file_path: str | None = None
    blob_ref: str | None = None
    thumbnail_ref: str | None = None
    width: int = 1280
    height: int = 720
    image_format: str = "mock"
    hash_hint: str = ""
    redaction_applied: bool = False
    persisted_by_user_request: bool = False
    mock_artifact: bool = False
    fixture_name: str = "resistor"
    source_provenance: str = CAMERA_SOURCE_PROVENANCE_MOCK
    quality_warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.storage_mode = CameraStorageMode(self.storage_mode)
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(minutes=5)

    def is_expired(self, *, at: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (at or utc_now()) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraArtifactReadiness:
    image_artifact_id: str
    ready: bool
    artifact_exists: bool = False
    artifact_readable: bool = False
    artifact_expired: bool = False
    artifact_size_bytes: int | None = None
    artifact_format: str = "unknown"
    artifact_source_provenance: str = CAMERA_SOURCE_PROVENANCE_UNAVAILABLE
    storage_mode: CameraStorageMode = CameraStorageMode.EPHEMERAL
    reason_code: str | None = None
    message: str = ""
    cleanup_pending: bool = False
    cleanup_failed: bool = False
    checked_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.storage_mode = CameraStorageMode(self.storage_mode)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraArtifactCleanupResult:
    image_artifact_id: str
    cleanup_attempted: bool = False
    cleanup_succeeded: bool = False
    cleanup_failed: bool = False
    cleanup_pending: bool = False
    file_existed_before: bool = False
    file_exists_after: bool = False
    error_code: str | None = None
    error_message: str | None = None
    checked_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraArtifactLibraryEntry:
    image_artifact_id: str
    safe_library_ref: str
    label: str = ""
    storage_mode: CameraStorageMode = CameraStorageMode.SAVED
    artifact_format: str = "unknown"
    artifact_size_bytes: int | None = None
    source_provenance: str = CAMERA_SOURCE_PROVENANCE_UNAVAILABLE
    persisted_by_user_request: bool = True
    raw_image_included: bool = False
    cloud_upload_performed: bool = False
    saved_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.storage_mode = CameraStorageMode(self.storage_mode)
        self.persisted_by_user_request = True
        self.raw_image_included = False
        self.cloud_upload_performed = False

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraArtifactPersistenceResult:
    image_artifact_id: str
    status: CameraArtifactPersistenceStatus
    result_state: CameraAwarenessResultState
    safe_library_ref: str = ""
    label: str = ""
    storage_mode: CameraStorageMode = CameraStorageMode.EPHEMERAL
    artifact_exists: bool = False
    artifact_readable: bool = False
    artifact_expired: bool = False
    artifact_size_bytes: int | None = None
    artifact_format: str = "unknown"
    artifact_source_provenance: str = CAMERA_SOURCE_PROVENANCE_UNAVAILABLE
    save_performed: bool = False
    image_persisted_by_user_request: bool = False
    raw_image_included: bool = False
    cloud_upload_performed: bool = False
    task_mutation_performed: bool = False
    memory_write_performed: bool = False
    permission_scope_required: str | None = None
    error_code: str | None = None
    message: str = ""
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.status = CameraArtifactPersistenceStatus(self.status)
        self.result_state = CameraAwarenessResultState(self.result_state)
        self.storage_mode = CameraStorageMode(self.storage_mode)
        self.raw_image_included = False
        self.cloud_upload_performed = False
        self.task_mutation_performed = False
        self.memory_write_performed = False

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraCaptureResult:
    request_id: str
    status: CameraCaptureStatus
    capture_result_id: str = field(default_factory=lambda: camera_id("camera-capture-result"))
    image_artifact_id: str | None = None
    captured_at: datetime = field(default_factory=utc_now)
    device_id: str | None = None
    width: int = 0
    height: int = 0
    image_format: str = "none"
    quality_warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    raw_image_persisted: bool = False
    cloud_upload_allowed: bool = False
    cloud_upload_performed: bool = False
    mock_capture: bool = False
    real_camera_used: bool = False
    source_provenance: str = CAMERA_SOURCE_PROVENANCE_UNAVAILABLE

    def __post_init__(self) -> None:
        self.status = CameraCaptureStatus(self.status)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraVisionQuestion:
    image_artifact_id: str
    user_question: str
    normalized_question: str
    analysis_mode: CameraAnalysisMode = CameraAnalysisMode.UNKNOWN
    provider: str = "mock"
    model: str = "mock-vision"
    vision_question_id: str = field(default_factory=lambda: camera_id("camera-vision-question"))
    cloud_analysis_allowed: bool = False
    mock_analysis: bool = False
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.analysis_mode = CameraAnalysisMode(self.analysis_mode)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraVisionPrompt:
    analysis_mode: CameraAnalysisMode
    system_prompt: str
    user_prompt: str

    def __post_init__(self) -> None:
        self.analysis_mode = CameraAnalysisMode(self.analysis_mode)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraVisionAnswer:
    vision_question_id: str
    image_artifact_id: str
    answer_text: str
    concise_answer: str
    confidence: CameraConfidenceLevel
    result_state: CameraAwarenessResultState
    vision_answer_id: str = field(default_factory=lambda: camera_id("camera-vision-answer"))
    provider: str = "mock"
    model: str = "mock-vision"
    analysis_mode: CameraAnalysisMode = CameraAnalysisMode.UNKNOWN
    mock_answer: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)
    cloud_upload_performed: bool = False
    provider_kind: str = "mock"
    cloud_analysis_performed: bool = False
    raw_image_included: bool = False
    detailed_answer: str | None = None
    evidence_summary: str = ""
    uncertainty_reasons: list[str] = field(default_factory=list)
    suggested_next_capture: str | None = None
    recommended_user_action: str | None = None
    safety_notes: list[str] = field(default_factory=list)
    helper_hints: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    provider_raw_ref: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.confidence = CameraConfidenceLevel(self.confidence)
        self.result_state = CameraAwarenessResultState(self.result_state)
        self.analysis_mode = CameraAnalysisMode(self.analysis_mode)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraHelperClassification:
    category: CameraHelperCategory = CameraHelperCategory.UNKNOWN
    helper_family: CameraHelperFamily = CameraHelperFamily.UNKNOWN
    applicable: bool = False
    confidence: CameraConfidenceLevel = CameraConfidenceLevel.INSUFFICIENT
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.category = CameraHelperCategory(self.category)
        self.helper_family = CameraHelperFamily(self.helper_family)
        self.confidence = CameraConfidenceLevel(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraEngineeringHelperResult:
    vision_answer_id: str
    artifact_id: str
    helper_family: CameraHelperFamily
    title: str
    concise_answer: str
    confidence_kind: CameraConfidenceLevel
    source_provenance: str
    provider_kind: str
    category: CameraHelperCategory = CameraHelperCategory.ENGINEERING_INSPECTION
    helper_result_id: str = field(default_factory=lambda: camera_id("camera-helper"))
    detailed_answer: str | None = None
    confidence_label: str = ""
    visual_estimate: str = ""
    visual_evidence: list[str] = field(default_factory=list)
    uncertainty_reasons: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    suggested_next_capture: str | None = None
    suggested_measurements: list[str] = field(default_factory=list)
    suggested_user_actions: list[str] = field(default_factory=list)
    deterministic_calculation_used: bool = False
    calculation_trace_id: str | None = None
    mock_analysis: bool = False
    cloud_analysis_performed: bool = False
    verified_measurement: bool = False
    action_executed: bool = False
    trust_approved: bool = False
    task_mutation_performed: bool = False
    raw_image_included: bool = False
    error_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.category = CameraHelperCategory(self.category)
        self.helper_family = CameraHelperFamily(self.helper_family)
        self.confidence_kind = CameraConfidenceLevel(self.confidence_kind)
        if not self.confidence_label:
            self.confidence_label = self.confidence_kind.value.title()
        self.verified_measurement = False
        self.action_executed = False
        self.trust_approved = False
        self.task_mutation_performed = False
        self.raw_image_included = False

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraCaptureQualityIssue:
    issue_kind: CameraCaptureQualityIssueKind
    artifact_id: str | None = None
    severity: CameraCaptureQualitySeverity = CameraCaptureQualitySeverity.MEDIUM
    confidence_kind: CameraConfidenceLevel = CameraConfidenceLevel.MEDIUM
    evidence: str = ""
    affected_region_label: str | None = None
    helper_family: str | None = None
    issue_id: str = field(default_factory=lambda: camera_id("camera-quality-issue"))
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.issue_kind = CameraCaptureQualityIssueKind(self.issue_kind)
        self.severity = CameraCaptureQualitySeverity(self.severity)
        self.confidence_kind = CameraConfidenceLevel(self.confidence_kind)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraCaptureGuidanceResult:
    status: CameraCaptureGuidanceStatus
    title: str
    concise_guidance: str
    artifact_id: str | None = None
    multi_capture_session_id: str | None = None
    comparison_request_id: str | None = None
    helper_family: str | None = None
    guidance_result_id: str = field(default_factory=lambda: camera_id("camera-guidance"))
    detailed_guidance: str | None = None
    quality_issues: list[CameraCaptureQualityIssue] = field(default_factory=list)
    suggested_next_capture: str | None = None
    suggested_capture_label: str | None = None
    suggested_user_actions: list[str] = field(default_factory=list)
    confidence_kind: CameraConfidenceLevel = CameraConfidenceLevel.MEDIUM
    source_provenance: str = CAMERA_SOURCE_PROVENANCE_UNAVAILABLE
    storage_mode: CameraStorageMode = CameraStorageMode.EPHEMERAL
    visual_evidence_only: bool = True
    capture_triggered: bool = False
    analysis_triggered: bool = False
    upload_triggered: bool = False
    save_triggered: bool = False
    cleanup_triggered: bool = False
    memory_write_triggered: bool = False
    raw_image_included: bool = False
    verified_measurement: bool = False
    verified_outcome: bool = False
    action_executed: bool = False
    trust_approved: bool = False
    task_mutation_performed: bool = False
    error_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.status = CameraCaptureGuidanceStatus(self.status)
        self.confidence_kind = CameraConfidenceLevel(self.confidence_kind)
        self.storage_mode = CameraStorageMode(self.storage_mode)
        self.visual_evidence_only = True
        self.capture_triggered = False
        self.analysis_triggered = False
        self.upload_triggered = False
        self.save_triggered = False
        self.cleanup_triggered = False
        self.memory_write_triggered = False
        self.raw_image_included = False
        self.verified_measurement = False
        self.verified_outcome = False
        self.action_executed = False
        self.trust_approved = False
        self.task_mutation_performed = False

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraCaptureSlot:
    slot_id: str
    label: str
    description: str = ""
    required: bool = True
    status: CameraCaptureSlotStatus = CameraCaptureSlotStatus.PENDING
    artifact_id: str | None = None
    capture_request_id: str | None = None
    capture_result_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    captured_at: datetime | None = None
    expires_at: datetime | None = None
    source_provenance: str | None = None

    def __post_init__(self) -> None:
        self.status = CameraCaptureSlotStatus(self.status)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraMultiCaptureSession:
    user_request_id: str
    purpose: str
    expected_slots: list[CameraCaptureSlot]
    session_id: str | None = None
    task_id: str | None = None
    helper_category: str | None = None
    helper_family: str | None = None
    comparison_mode: CameraComparisonMode = CameraComparisonMode.GENERAL_COMPARE
    status: CameraMultiCaptureSessionStatus = CameraMultiCaptureSessionStatus.ACTIVE
    multi_capture_session_id: str = field(default_factory=lambda: camera_id("camera-multi"))
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    captured_slots: list[CameraCaptureSlot] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    current_slot_id: str | None = None
    policy_state: str = "explicit_user_guided"
    storage_mode_default: CameraStorageMode = CameraStorageMode.EPHEMERAL
    cloud_analysis_allowed: bool = False
    cloud_analysis_performed: bool = False
    mock_session: bool = False
    error_code: str | None = None

    def __post_init__(self) -> None:
        self.comparison_mode = CameraComparisonMode(self.comparison_mode)
        self.status = CameraMultiCaptureSessionStatus(self.status)
        self.storage_mode_default = CameraStorageMode(self.storage_mode_default)
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(minutes=5)
        if self.current_slot_id is None and self.expected_slots:
            self.current_slot_id = self.expected_slots[0].slot_id

    def is_expired(self, *, at: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (at or utc_now()) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraComparisonArtifactSummary:
    artifact_id: str
    slot_id: str | None = None
    label: str = ""
    safe_preview_ref: str = ""
    source_provenance: str = CAMERA_SOURCE_PROVENANCE_UNAVAILABLE
    storage_mode: CameraStorageMode = CameraStorageMode.EPHEMERAL
    artifact_format: str = "unknown"
    artifact_size_bytes: int | None = None
    ready: bool = False
    artifact_exists: bool = False
    artifact_readable: bool = False
    artifact_expired: bool = False
    reason_code: str | None = None
    raw_image_included: bool = False

    def __post_init__(self) -> None:
        self.storage_mode = CameraStorageMode(self.storage_mode)
        self.raw_image_included = False

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraComparisonRequest:
    user_request_id: str
    artifact_ids: list[str]
    user_question: str
    normalized_question: str
    multi_capture_session_id: str | None = None
    slot_ids: list[str] = field(default_factory=list)
    comparison_mode: CameraComparisonMode = CameraComparisonMode.GENERAL_COMPARE
    helper_category: str | None = None
    helper_family: str | None = None
    provider_kind: str = "mock"
    mock_comparison: bool = True
    cloud_analysis_requested: bool = False
    cloud_analysis_allowed: bool = False
    comparison_request_id: str = field(default_factory=lambda: camera_id("camera-comparison-req"))
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.comparison_mode = CameraComparisonMode(self.comparison_mode)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraComparisonClassification:
    applicable: bool = False
    comparison_mode: CameraComparisonMode = CameraComparisonMode.GENERAL_COMPARE
    helper_category: str | None = None
    helper_family: str | None = None
    slot_ids: list[str] = field(default_factory=list)
    confidence: CameraConfidenceLevel = CameraConfidenceLevel.INSUFFICIENT
    reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.comparison_mode = CameraComparisonMode(self.comparison_mode)
        self.confidence = CameraConfidenceLevel(self.confidence)

    def to_request(
        self,
        *,
        user_request_id: str,
        artifact_ids: list[str],
        slot_ids: list[str] | None = None,
        user_question: str = "",
        provider_kind: str = "mock",
        multi_capture_session_id: str | None = None,
    ) -> CameraComparisonRequest:
        return CameraComparisonRequest(
            user_request_id=user_request_id,
            artifact_ids=list(artifact_ids),
            slot_ids=list(slot_ids or self.slot_ids),
            user_question=user_question,
            normalized_question=" ".join(str(user_question or "").lower().split()),
            multi_capture_session_id=multi_capture_session_id,
            comparison_mode=self.comparison_mode,
            helper_category=self.helper_category,
            helper_family=self.helper_family,
            provider_kind=provider_kind,
            mock_comparison=provider_kind == "mock",
            cloud_analysis_requested=provider_kind in {"openai", "cloud", "real"},
        )

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraComparisonPrompt:
    comparison_mode: CameraComparisonMode
    system_prompt: str
    user_prompt: str

    def __post_init__(self) -> None:
        self.comparison_mode = CameraComparisonMode(self.comparison_mode)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraComparisonResult:
    comparison_request_id: str
    status: CameraComparisonStatus
    title: str
    concise_answer: str
    comparison_mode: CameraComparisonMode
    artifact_summaries: list[CameraComparisonArtifactSummary]
    confidence_kind: CameraConfidenceLevel
    comparison_result_id: str = field(default_factory=lambda: camera_id("camera-comparison"))
    detailed_answer: str | None = None
    helper_category: str | None = None
    helper_family: str | None = None
    similarities: list[str] = field(default_factory=list)
    differences: list[str] = field(default_factory=list)
    changed_regions: list[str] = field(default_factory=list)
    confidence_label: str = ""
    evidence_summary: str = ""
    uncertainty_reasons: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    suggested_next_capture: str | None = None
    suggested_measurements: list[str] = field(default_factory=list)
    suggested_user_actions: list[str] = field(default_factory=list)
    source_provenance: list[str] = field(default_factory=list)
    provider_kind: str = "mock"
    mock_comparison: bool = True
    cloud_analysis_performed: bool = False
    visual_evidence_only: bool = True
    verified_outcome: bool = False
    action_executed: bool = False
    trust_approved: bool = False
    task_mutation_performed: bool = False
    raw_image_included: bool = False
    error_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.status = CameraComparisonStatus(self.status)
        self.comparison_mode = CameraComparisonMode(self.comparison_mode)
        self.confidence_kind = CameraConfidenceLevel(self.confidence_kind)
        if not self.confidence_label:
            self.confidence_label = self.confidence_kind.value.title()
        self.visual_evidence_only = True
        self.verified_outcome = False
        self.action_executed = False
        self.trust_approved = False
        self.task_mutation_performed = False
        self.raw_image_included = False

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraAwarenessPolicyResult:
    allowed: bool
    requires_user_confirmation: bool = True
    blocked_reason: str | None = None
    permission_scope_required: str | None = "camera.single_still"
    cloud_analysis_allowed: bool = False
    storage_allowed: bool = True
    background_capture_allowed: bool = False
    audit_required: bool = True
    warnings: list[str] = field(default_factory=list)
    result_state: CameraAwarenessResultState | None = None

    def __post_init__(self) -> None:
        if self.result_state is not None:
            self.result_state = CameraAwarenessResultState(self.result_state)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraObservationTrace:
    capture_request_id: str
    result_state: CameraAwarenessResultState
    route_family: str = ROUTE_FAMILY_CAMERA_AWARENESS
    capture_result_id: str | None = None
    image_artifact_id: str | None = None
    vision_question_id: str | None = None
    vision_answer_id: str | None = None
    source_provenance: str = CAMERA_SOURCE_PROVENANCE_MOCK
    provider_kind: str = "mock"
    storage_mode: CameraStorageMode = CameraStorageMode.EPHEMERAL
    policy_allowed: bool = False
    blocked_reason: str | None = None
    raw_image_included: bool = False
    raw_image_persisted: bool = False
    cloud_upload_performed: bool = False
    real_camera_used: bool = False
    mock_mode: bool = True
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.result_state = CameraAwarenessResultState(self.result_state)
        self.storage_mode = CameraStorageMode(self.storage_mode)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraAwarenessFlowResult:
    capture_request: CameraCaptureRequest
    policy_result: CameraAwarenessPolicyResult
    capture_result: CameraCaptureResult
    artifact: CameraFrameArtifact | None
    vision_question: CameraVisionQuestion | None
    vision_answer: CameraVisionAnswer
    trace: CameraObservationTrace
    result_state: CameraAwarenessResultState
    response_text: str
    helper_result: CameraEngineeringHelperResult | None = None

    def __post_init__(self) -> None:
        self.result_state = CameraAwarenessResultState(self.result_state)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)


@dataclass(slots=True)
class CameraArtifactResolution:
    artifact: CameraFrameArtifact | None
    result_state: CameraAwarenessResultState
    message: str = ""

    def __post_init__(self) -> None:
        self.result_state = CameraAwarenessResultState(self.result_state)

    def to_dict(self) -> dict[str, Any]:
        return serialize_camera_value(self)
