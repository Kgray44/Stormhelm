from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION = "browser_semantic_observation"
CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION_COMPARISON = "browser_semantic_observation_comparison"
CLAIM_CEILING_BROWSER_SEMANTIC_ACTION_PREVIEW = "browser_semantic_action_preview"
CLAIM_CEILING_BROWSER_SEMANTIC_ACTION_EXECUTION = "browser_semantic_action_execution"
CLAIM_CEILING_BROWSER_SEMANTIC_TASK_PLAN = "browser_semantic_task_plan"
CLAIM_CEILING_BROWSER_SEMANTIC_TASK_EXECUTION = "browser_semantic_task_execution"


def _serialize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {str(key): _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class ScreenObservationScope(StrEnum):
    ACTIVE_WINDOW = "active_window"
    FULL_SCREEN = "full_screen"
    REGION = "region"
    MONITOR = "monitor"


class ScreenSourceType(StrEnum):
    PLACEHOLDER = "placeholder"
    SCREEN_CAPTURE = "screen_capture"
    LOCAL_OCR = "local_ocr"
    ACCESSIBILITY = "accessibility"
    BROWSER_DOM = "browser_dom"
    FOCUS_STATE = "focus_state"
    SELECTION = "selection"
    CLIPBOARD = "clipboard"
    WORKSPACE_CONTEXT = "workspace_context"
    PROVIDER_VISION = "provider_vision"
    APP_ADAPTER = "app_adapter"


class ScreenConfidenceLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScreenTruthState(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNAVAILABLE = "unavailable"
    UNVERIFIED = "unverified"


class ScreenSensitivityLevel(StrEnum):
    UNKNOWN = "unknown"
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class ScreenRouteDisposition(StrEnum):
    NOT_REQUESTED = "not_requested"
    FEATURE_DISABLED = "feature_disabled"
    ROUTING_DISABLED = "routing_disabled"
    PHASE1_ANALYZE = "phase1_analyze"
    PHASE2_GROUND = "phase2_ground"
    PHASE3_GUIDE = "phase3_guide"
    PHASE4_VERIFY = "phase4_verify"
    PHASE5_ACT = "phase5_act"
    PHASE6_CONTINUE = "phase6_continue"
    PHASE8_PROBLEM_SOLVE = "phase8_problem_solve"
    PHASE9_WORKFLOW_REUSE = "phase9_workflow_reuse"
    PHASE10_BRAIN_INTEGRATION = "phase10_brain_integration"
    PHASE11_POWER = "phase11_power"
    PHASE0_SCAFFOLD = "phase0_scaffold"


class ScreenLimitationCode(StrEnum):
    OBSERVATION_UNAVAILABLE = "observation_unavailable"
    SCREEN_CAPTURE_DISABLED = "screen_capture_disabled"
    SCREEN_CAPTURE_UNAVAILABLE = "screen_capture_unavailable"
    SENSITIVE_CONTENT_RESTRICTED = "sensitive_content_restricted"
    LOW_CONFIDENCE = "low_confidence"
    PRIOR_OBSERVATION_REQUIRED = "prior_observation_required"
    UNVERIFIED_CHANGE = "unverified_change"
    PHASE0_FOUNDATION_ONLY = "phase0_foundation_only"


class ScreenIntentType(StrEnum):
    INSPECT_VISIBLE_STATE = "inspect_visible_state"
    EXPLAIN_VISIBLE_CONTENT = "explain_visible_content"
    SOLVE_VISIBLE_PROBLEM = "solve_visible_problem"
    DETECT_VISIBLE_CHANGE = "detect_visible_change"
    GUIDE_NAVIGATION = "guide_navigation"
    VERIFY_SCREEN_STATE = "verify_screen_state"
    EXECUTE_UI_ACTION = "execute_ui_action"
    CONTINUE_WORKFLOW = "continue_workflow"
    LEARN_WORKFLOW_REUSE = "learn_workflow_reuse"
    BRAIN_INTEGRATION = "brain_integration"


class GroundingRequestType(StrEnum):
    REFERENCE_RESOLUTION = "reference_resolution"
    EXPLANATION = "explanation"
    PROBLEM_IDENTIFICATION = "problem_identification"
    DISAMBIGUATION = "disambiguation"
    SOLUTION = "solution"


class GroundingCandidateRole(StrEnum):
    UNKNOWN = "unknown"
    WINDOW = "window"
    DOCUMENT = "document"
    ITEM = "item"
    BUTTON = "button"
    CHECKBOX = "checkbox"
    FIELD = "field"
    WARNING = "warning"
    ERROR = "error"
    POPUP = "popup"
    MESSAGE = "message"
    TAB = "tab"
    REGION = "region"


class GroundingEvidenceChannel(StrEnum):
    NATIVE_OBSERVATION = "native_observation"
    WORKSPACE_CONTEXT = "workspace_context"
    ADAPTER_SEMANTICS = "adapter_semantics"
    VISUAL_PROVIDER = "visual_provider"
    INTERPRETATION = "interpretation"


class GroundingAmbiguityStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED_INSUFFICIENT_EVIDENCE = "unresolved_insufficient_evidence"
    UNRESOLVED_CONFLICTING_EVIDENCE = "unresolved_conflicting_evidence"


class NavigationRequestType(StrEnum):
    NEXT_STEP = "next_step"
    TARGET_SELECTION = "target_selection"
    RIGHT_PAGE_CHECK = "right_page_check"
    RECOVERY = "recovery"
    BLOCKER_CHECK = "blocker_check"


class NavigationStepStatus(StrEnum):
    READY = "ready"
    AMBIGUOUS = "ambiguous"
    BLOCKED = "blocked"
    WRONG_PAGE = "wrong_page"
    REENTRY = "reentry"
    UNRESOLVED = "unresolved"


class VerificationRequestType(StrEnum):
    RESULT_CHECK = "result_check"
    CHANGE_CHECK = "change_check"
    COMPLETION_CHECK = "completion_check"
    PAGE_CHECK = "page_check"
    ERROR_CHECK = "error_check"
    BLOCKER_CHECK = "blocker_check"


class CompletionStatus(StrEnum):
    COMPLETED = "completed"
    NOT_COMPLETED = "not_completed"
    AMBIGUOUS = "ambiguous"
    BLOCKED = "blocked"
    DIVERTED = "diverted"


class ChangeClassification(StrEnum):
    VERIFIED_CHANGE = "verified_change"
    LIKELY_CHANGE = "likely_change"
    NO_VISIBLE_CHANGE = "no_visible_change"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CHANGED_BUT_NOT_UNDERSTOOD = "changed_but_not_understood"


class ActionPolicyMode(StrEnum):
    OBSERVE_ONLY = "observe_only"
    GUIDE = "guide"
    CONFIRM_BEFORE_ACT = "confirm_before_act"
    TRUSTED_ACTION = "trusted_action"


class ActionIntent(StrEnum):
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE_TEXT = "type_text"
    PRESS_KEY = "press_key"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    FOCUS = "focus"
    SELECT = "select"
    HOVER = "hover"


class ActionRiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    RESTRICTED = "restricted"


class ActionExecutionStatus(StrEnum):
    PLANNED = "planned"
    GATED = "gated"
    ATTEMPTED = "attempted"
    VERIFIED_SUCCESS = "verified_success"
    ATTEMPTED_UNVERIFIED = "attempted_unverified"
    BLOCKED = "blocked"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class WorkflowContinuityRequestType(StrEnum):
    RESUME = "resume"
    FLOW_STATUS = "flow_status"
    DETOUR_RECOVERY = "detour_recovery"
    BACKTRACK_CHECK = "backtrack_check"
    RECOVERY = "recovery"
    UNDO_HINT = "undo_hint"


class WorkflowContinuityStatus(StrEnum):
    ACTIVE_FLOW = "active_flow"
    INTERRUPTED_FLOW = "interrupted_flow"
    DETOURED = "detoured"
    RECOVERY_READY = "recovery_ready"
    RESUME_READY = "resume_ready"
    WEAK_BASIS = "weak_basis"
    BLOCKED = "blocked"
    AMBIGUOUS = "ambiguous"


class WorkflowLearningRequestType(StrEnum):
    START_OBSERVATION = "start_observation"
    SAVE_WORKFLOW = "save_workflow"
    INSPECT_WORKFLOW = "inspect_workflow"
    MATCH_WORKFLOW = "match_workflow"
    REUSE_WORKFLOW = "reuse_workflow"


class WorkflowMatchStatus(StrEnum):
    STRONG_MATCH = "strong_match"
    PARTIAL_MATCH = "partial_match"
    DOWNGRADED_MATCH = "downgraded_match"
    AMBIGUOUS_MATCH = "ambiguous_match"
    REFUSED = "refused"
    NO_MATCH = "no_match"


class WorkflowLearningStatus(StrEnum):
    OBSERVING = "observing"
    WEAK_BASIS = "weak_basis"
    REUSABLE_ACCEPTED = "reusable_accepted"
    STRONG_MATCH = "strong_match"
    PARTIAL_MATCH = "partial_match"
    DOWNGRADED_MATCH = "downgraded_match"
    AMBIGUOUS_MATCH = "ambiguous_match"
    REFUSED = "refused"
    REUSE_PLANNED = "reuse_planned"
    REUSE_ATTEMPTED = "reuse_attempted"
    REUSE_VERIFIED_SUCCESS = "reuse_verified_success"
    REUSE_ATTEMPTED_UNVERIFIED = "reuse_attempted_unverified"


class BrainIntegrationRequestType(StrEnum):
    AUTO_INTEGRATE = "auto_integrate"
    REMEMBER_WORKFLOW = "remember_workflow"
    LEARN_PREFERENCE = "learn_preference"
    LEARN_ENVIRONMENT_QUIRK = "learn_environment_quirk"
    RECALL_CONTEXT = "recall_context"
    ENABLE_PROACTIVE_CONTINUITY = "enable_proactive_continuity"


class BrainIntegrationStatus(StrEnum):
    SESSION_INTEGRATED = "session_integrated"
    CANDIDATE_CREATED = "candidate_created"
    PREFERENCE_LEARNED = "preference_learned"
    QUIRK_LEARNED = "quirk_learned"
    CONTEXT_RECALLED = "context_recalled"
    PROACTIVE_SUGGESTION = "proactive_suggestion"
    DEFERRED = "deferred"
    REFUSED = "refused"


class MemoryBindingTarget(StrEnum):
    WORKING_MEMORY = "working_memory"
    SESSION_MEMORY = "session_memory"
    LONG_TERM_CANDIDATE = "long_term_candidate"
    LEARNED_PREFERENCE = "learned_preference"
    ENVIRONMENT_QUIRK = "environment_quirk"
    DEFERRED = "deferred"
    REFUSED = "refused"


class PowerFeatureRequestType(StrEnum):
    AUTO = "auto"
    MONITOR_QUERY = "monitor_query"
    ACCESSIBILITY_QUERY = "accessibility_query"
    OVERLAY_REQUEST = "overlay_request"
    TRANSLATION_REQUEST = "translation_request"
    ENTITY_QUERY = "entity_query"
    NOTIFICATION_QUERY = "notification_query"
    WORKSPACE_MAP_QUERY = "workspace_map_query"


class OverlayAnchorPrecision(StrEnum):
    GROUNDED = "grounded"
    CANDIDATE = "candidate"
    APPROXIMATE = "approximate"


class NotificationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AppAdapterId(StrEnum):
    BROWSER = "browser"
    FILE_EXPLORER = "file_explorer"
    SYSTEM_SETTINGS = "system_settings"
    TERMINAL = "terminal"
    EDITOR = "editor"


class AdapterFallbackReason(StrEnum):
    NO_SEMANTIC_STATE = "no_semantic_state"
    STALE_SEMANTIC_STATE = "stale_semantic_state"
    UNSUPPORTED_SURFACE = "unsupported_surface"
    CONFLICTING_SURFACE = "conflicting_surface"
    HIDDEN_ONLY_SEMANTIC_TARGETS = "hidden_only_semantic_targets"
    INSUFFICIENT_SEMANTIC_STATE = "insufficient_semantic_state"


class ScreenProblemType(StrEnum):
    UNKNOWN = "unknown"
    CODE_ERROR = "code_error"
    VALIDATION_ERROR = "validation_error"
    EQUATION_SOLVE = "equation_solve"
    CHART_INTERPRETATION = "chart_interpretation"
    TABLE_INTERPRETATION = "table_interpretation"
    DIAGRAM_INTERPRETATION = "diagram_interpretation"
    GENERAL_VISIBLE_PROBLEM = "general_visible_problem"


class ScreenArtifactKind(StrEnum):
    UNKNOWN = "unknown"
    CODE = "code"
    FORM = "form"
    EQUATION = "equation"
    CHART = "chart"
    TABLE = "table"
    DIAGRAM = "diagram"
    TEXT = "text"


class ExplanationMode(StrEnum):
    DIRECT_ANSWER = "direct_answer"
    CONCISE_EXPLANATION = "concise_explanation"
    STEP_BY_STEP = "step_by_step"
    TEACHING = "teaching"
    STRESSED_USER = "stressed_user"


class TeachingMode(StrEnum):
    NONE = "none"
    TEACHING = "teaching"
    STRESSED_USER = "stressed_user"


class ProblemAmbiguityState(StrEnum):
    CLEAR = "clear"
    PARTIAL = "partial"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ProblemAnswerStatus(StrEnum):
    DIRECT_ANSWER = "direct_answer"
    EXPLANATION_ONLY = "explanation_only"
    APPROXIMATE = "approximate"
    PARTIAL = "partial"
    REFUSED = "refused"


class ScreenAuditSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ScreenRecoveryStatus(StrEnum):
    STEADY = "steady"
    RECOVERED = "recovered"
    PARTIALLY_RECOVERED = "partially_recovered"
    UNRESOLVED = "unresolved"


def confidence_level_for_score(score: float) -> ScreenConfidenceLevel:
    if score <= 0.0:
        return ScreenConfidenceLevel.NONE
    if score < 0.35:
        return ScreenConfidenceLevel.LOW
    if score < 0.7:
        return ScreenConfidenceLevel.MEDIUM
    return ScreenConfidenceLevel.HIGH


@dataclass(slots=True)
class ScreenConfidence:
    score: float
    level: ScreenConfidenceLevel
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level.value,
            "note": self.note,
        }


@dataclass(slots=True)
class ScreenLimitation:
    code: ScreenLimitationCode
    message: str
    truth_state: ScreenTruthState = ScreenTruthState.UNAVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "truth_state": self.truth_state.value,
        }


@dataclass(slots=True)
class ScreenTruthfulnessContract:
    observation_vs_inference: str = "separate"
    low_confidence_behavior: str = "state_uncertainty"
    unavailable_observation_behavior: str = "say_unavailable"
    unverified_change_behavior: str = "never_claim_verified"
    action_boundary: str = "no_action_without_execution"

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_vs_inference": self.observation_vs_inference,
            "low_confidence_behavior": self.low_confidence_behavior,
            "unavailable_observation_behavior": self.unavailable_observation_behavior,
            "unverified_change_behavior": self.unverified_change_behavior,
            "action_boundary": self.action_boundary,
        }


@dataclass(slots=True)
class BrowserSemanticControl:
    control_id: str
    role: str = ""
    name: str = ""
    label: str = ""
    text: str = ""
    selector_hint: str = ""
    bounding_hint: dict[str, Any] = field(default_factory=dict)
    enabled: bool | None = None
    visible: bool | None = None
    checked: bool | None = None
    expanded: bool | None = None
    required: bool | None = None
    readonly: bool | None = None
    value_summary: str = ""
    risk_hint: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserGroundingCandidate:
    candidate_id: str = field(default_factory=lambda: f"browser-grounding-{uuid4().hex[:12]}")
    target_phrase: str = ""
    control_id: str = ""
    role: str = ""
    name: str = ""
    label: str = ""
    text: str = ""
    selector_hint: str = ""
    match_reason: str = ""
    confidence: float = 0.0
    ambiguity_reason: str = ""
    action_supported: bool = False
    verification_supported: bool = False
    evidence_terms: list[str] = field(default_factory=list)
    mismatch_terms: list[str] = field(default_factory=list)
    source_observation_id: str = ""
    source_provider: str = ""
    claim_ceiling: str = CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserSemanticObservation:
    observation_id: str = field(default_factory=lambda: f"browser-semantic-{uuid4().hex[:12]}")
    provider: str = "playwright"
    adapter_id: str = "screen_awareness.browser.playwright"
    session_id: str = ""
    page_url: str = ""
    page_title: str = ""
    browser_context_kind: str = "none"
    observed_at: str = ""
    controls: list[BrowserSemanticControl] = field(default_factory=list)
    text_regions: list[dict[str, Any]] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)
    landmarks: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    dialogs: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=lambda: ["playwright_scaffold_only", "no_actions"])
    confidence: float = 0.0
    claim_ceiling: str = CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserSemanticChange:
    change_id: str = field(default_factory=lambda: f"browser-semantic-change-{uuid4().hex[:12]}")
    change_type: str = ""
    before_summary: str = ""
    after_summary: str = ""
    control_id_before: str = ""
    control_id_after: str = ""
    role: str = ""
    name: str = ""
    label: str = ""
    evidence_terms: list[str] = field(default_factory=list)
    confidence: float = 0.0
    sensitive_redacted: bool = False
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserSemanticVerificationRequest:
    request_id: str = field(default_factory=lambda: f"browser-semantic-verification-{uuid4().hex[:12]}")
    before_observation_id: str = ""
    after_observation_id: str = ""
    expected_change_kind: str = ""
    target_phrase: str = ""
    expected_target: str = ""
    expected_state: bool | str | None = None
    route_family: str = "screen_awareness"
    source_provider: str = "playwright"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserSemanticVerificationResult:
    result_id: str = field(default_factory=lambda: f"browser-semantic-comparison-{uuid4().hex[:12]}")
    request_id: str = ""
    status: str = "insufficient_basis"
    summary: str = ""
    changes: list[BrowserSemanticChange] = field(default_factory=list)
    expected_change_supported: bool = False
    expected_change_evidence: list[str] = field(default_factory=list)
    expected_change_missing: list[str] = field(default_factory=list)
    before_observation_id: str = ""
    after_observation_id: str = ""
    confidence: float = 0.0
    comparison_basis: str = "isolated_browser_semantic_observation"
    claim_ceiling: str = CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION_COMPARISON
    limitations: list[str] = field(default_factory=list)
    user_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserSemanticActionPreview:
    preview_id: str = field(default_factory=lambda: f"browser-semantic-action-preview-{uuid4().hex[:12]}")
    observation_id: str = ""
    source_provider: str = "playwright"
    target_phrase: str = ""
    target_candidate_id: str = ""
    target_role: str = ""
    target_name: str = ""
    target_label: str = ""
    target_options: list[dict[str, Any]] = field(default_factory=list)
    action_kind: str = "unsupported"
    preview_state: str = "preview_only"
    action_supported_now: bool = False
    action_supported: bool = False
    executable_now: bool = False
    reason_not_executable: str = "action_execution_deferred"
    confidence: float = 0.0
    risk_level: str = "medium"
    approval_required: bool = True
    required_trust_scope: str = "browser_action_once_future"
    expected_outcome: list[str] = field(default_factory=list)
    verification_strategy: str = "semantic_before_after_comparison_required"
    limitations: list[str] = field(default_factory=lambda: ["preview_only", "action_execution_deferred", "no_actions"])
    claim_ceiling: str = CLAIM_CEILING_BROWSER_SEMANTIC_ACTION_PREVIEW

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserSemanticActionPlan:
    plan_id: str = field(default_factory=lambda: f"browser-semantic-action-plan-{uuid4().hex[:12]}")
    preview_id: str = ""
    observation_id: str = ""
    target_candidate: dict[str, Any] = field(default_factory=dict)
    action_kind: str = "unsupported"
    action_arguments_redacted: dict[str, Any] = field(default_factory=dict)
    action_arguments_private: dict[str, Any] = field(default_factory=dict, repr=False)
    preconditions: list[str] = field(default_factory=lambda: ["fresh_semantic_observation_required", "operator_approval_required"])
    approval_request_hint: str = "Future execution would require approval."
    adapter_capability_required: str = ""
    adapter_capability_declared: bool = False
    executable_now: bool = False
    verification_request_template: dict[str, Any] = field(default_factory=dict)
    result_state: str = "preview_only"
    user_message: str = "Action plan preview only. Execution is not enabled yet."
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    claim_ceiling: str = CLAIM_CEILING_BROWSER_SEMANTIC_ACTION_PREVIEW
    limitations: list[str] = field(default_factory=lambda: ["preview_only", "action_execution_deferred", "no_actions"])

    def to_dict(self) -> dict[str, Any]:
        payload = _serialize(self)
        payload.pop("action_arguments_private", None)
        return payload


@dataclass(slots=True)
class BrowserSemanticActionExecutionRequest:
    request_id: str = field(default_factory=lambda: f"browser-semantic-action-exec-{uuid4().hex[:12]}")
    plan_id: str = ""
    preview_id: str = ""
    observation_id: str = ""
    target_candidate_id: str = ""
    action_kind: str = "unsupported"
    trust_request_id: str = ""
    approval_request_id: str = ""
    approval_grant_id: str = ""
    session_id: str = ""
    task_id: str = ""
    source_provider: str = "playwright"
    expected_outcome: list[str] = field(default_factory=list)
    typed_text_redacted: bool = False
    text_fingerprint: str = ""
    text_length: int = 0
    text_classification: str = ""
    text_redacted_summary: str = ""
    option_redacted_summary: str = ""
    option_fingerprint: str = ""
    option_ordinal: int = 0
    expected_checked_state: bool | None = None
    scroll_direction: str = ""
    scroll_amount_pixels: int = 0
    scroll_max_attempts: int = 0
    scroll_target_phrase: str = ""
    scroll_fingerprint: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserSemanticActionExecutionResult:
    result_id: str = field(default_factory=lambda: f"browser-semantic-action-result-{uuid4().hex[:12]}")
    request_id: str = ""
    plan_id: str = ""
    preview_id: str = ""
    action_kind: str = "unsupported"
    status: str = "blocked"
    action_attempted: bool = False
    action_completed: bool = False
    verification_attempted: bool = False
    verification_status: str = ""
    before_observation_id: str = ""
    after_observation_id: str = ""
    comparison_result_id: str = ""
    target_summary: dict[str, Any] = field(default_factory=dict)
    risk_level: str = ""
    trust_scope: str = ""
    trust_request_id: str = ""
    approval_request_id: str = ""
    approval_grant_id: str = ""
    provider: str = "playwright"
    claim_ceiling: str = CLAIM_CEILING_BROWSER_SEMANTIC_ACTION_EXECUTION
    typed_text_redacted: bool = False
    text_fingerprint: str = ""
    text_length: int = 0
    text_classification: str = ""
    text_redacted_summary: str = ""
    option_redacted_summary: str = ""
    option_fingerprint: str = ""
    option_ordinal: int = 0
    expected_checked_state: bool | None = None
    scroll_direction: str = ""
    scroll_amount_pixels: int = 0
    scroll_max_attempts: int = 0
    scroll_target_phrase: str = ""
    scroll_target_found: bool = False
    scroll_fingerprint: str = ""
    limitations: list[str] = field(default_factory=list)
    error_code: str = ""
    bounded_error_message: str = ""
    user_message: str = ""
    cleanup_status: str = "not_started"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserSemanticTaskStep:
    step_id: str = field(default_factory=lambda: f"browser-semantic-task-step-{uuid4().hex[:12]}")
    step_index: int = 0
    action_kind: str = "unsupported"
    target_phrase: str = ""
    target_candidate_id: str = ""
    target_fingerprint: str = ""
    action_args_redacted: dict[str, Any] = field(default_factory=dict)
    action_arguments_private: dict[str, Any] = field(default_factory=dict, repr=False)
    expected_outcome: list[str] = field(default_factory=list)
    required_capability: str = ""
    approval_binding_fingerprint: str = ""
    status: str = "pending"
    verification_result_id: str = ""
    limitations: list[str] = field(default_factory=list)
    action_plan_private: BrowserSemanticActionPlan | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_index": self.step_index,
            "action_kind": self.action_kind,
            "target_phrase": self.target_phrase,
            "target_candidate_id": self.target_candidate_id,
            "target_fingerprint": self.target_fingerprint,
            "action_args_redacted": _serialize(self.action_args_redacted),
            "expected_outcome": list(self.expected_outcome),
            "required_capability": self.required_capability,
            "approval_binding_fingerprint": self.approval_binding_fingerprint,
            "status": self.status,
            "verification_result_id": self.verification_result_id,
            "limitations": list(self.limitations),
        }


@dataclass(slots=True)
class BrowserSemanticTaskPlan:
    plan_id: str = field(default_factory=lambda: f"browser-semantic-task-plan-{uuid4().hex[:12]}")
    source_observation_id: str = ""
    provider: str = "playwright_live_semantic"
    plan_kind: str = "safe_browser_sequence"
    steps: list[BrowserSemanticTaskStep] = field(default_factory=list)
    max_steps: int = 5
    risk_level: str = "medium"
    approval_required: bool = True
    approval_request_id: str = ""
    approval_grant_id: str = ""
    executable_now: bool = False
    reason_not_executable: str = ""
    expected_final_state: list[str] = field(default_factory=list)
    stop_policy: dict[str, Any] = field(default_factory=dict)
    claim_ceiling: str = CLAIM_CEILING_BROWSER_SEMANTIC_TASK_PLAN
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str = ""
    limitations: list[str] = field(default_factory=list)
    approval_binding_fingerprint: str = ""
    source_task_phrase: str = ""
    user_message: str = "Plan ready; approval required."

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "source_observation_id": self.source_observation_id,
            "provider": self.provider,
            "plan_kind": self.plan_kind,
            "steps": [step.to_dict() for step in self.steps],
            "max_steps": self.max_steps,
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "approval_request_id": self.approval_request_id,
            "approval_grant_id": self.approval_grant_id,
            "executable_now": self.executable_now,
            "reason_not_executable": self.reason_not_executable,
            "expected_final_state": list(self.expected_final_state),
            "stop_policy": _serialize(self.stop_policy),
            "claim_ceiling": self.claim_ceiling,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "limitations": list(self.limitations),
            "approval_binding_fingerprint": self.approval_binding_fingerprint,
            "source_task_phrase": self.source_task_phrase,
            "user_message": self.user_message,
        }


@dataclass(slots=True)
class BrowserSemanticTaskExecutionResult:
    result_id: str = field(default_factory=lambda: f"browser-semantic-task-result-{uuid4().hex[:12]}")
    plan_id: str = ""
    status: str = "blocked"
    step_results: list[BrowserSemanticActionExecutionResult] = field(default_factory=list)
    completed_step_count: int = 0
    blocked_step_id: str = ""
    failure_reason: str = ""
    final_verification_status: str = ""
    cleanup_status: str = "not_started"
    action_attempted: bool = False
    approval_request_id: str = ""
    approval_grant_id: str = ""
    trust_request_id: str = ""
    provider: str = "playwright_live_semantic"
    claim_ceiling: str = CLAIM_CEILING_BROWSER_SEMANTIC_TASK_EXECUTION
    limitations: list[str] = field(default_factory=list)
    user_message: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "step_results": [step.to_dict() for step in self.step_results],
            "completed_step_count": self.completed_step_count,
            "blocked_step_id": self.blocked_step_id,
            "failure_reason": self.failure_reason,
            "final_verification_status": self.final_verification_status,
            "cleanup_status": self.cleanup_status,
            "action_attempted": self.action_attempted,
            "approval_request_id": self.approval_request_id,
            "approval_grant_id": self.approval_grant_id,
            "trust_request_id": self.trust_request_id,
            "provider": self.provider,
            "claim_ceiling": self.claim_ceiling,
            "limitations": list(self.limitations),
            "user_message": self.user_message,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


@dataclass(slots=True)
class PlaywrightAdapterReadiness:
    status: str = "disabled"
    enabled: bool = False
    available: bool = False
    dependency_installed: bool = False
    browser_engines_available: bool = False
    browser_engines_checkable: bool = False
    mock_ready: bool = False
    runtime_ready: bool = False
    mock_provider_active: bool = False
    live_runtime_allowed: bool = False
    actions_enabled: bool = False
    launch_allowed: bool = False
    connect_existing_allowed: bool = False
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bounded_error_message: str = ""
    claim_ceiling: str = CLAIM_CEILING_BROWSER_SEMANTIC_OBSERVATION

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenStageTiming:
    stage: str
    duration_ms: float
    status: str = "completed"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenLatencyTrace:
    trace_id: str
    total_duration_ms: float = 0.0
    stage_timings: list[ScreenStageTiming] = field(default_factory=list)
    slowest_stage: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenAuditFinding:
    code: str
    severity: ScreenAuditSeverity
    message: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenTruthfulnessAudit:
    passed: bool = True
    findings: list[ScreenAuditFinding] = field(default_factory=list)
    summary: str = "No truthfulness issues detected."

    @property
    def error_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == ScreenAuditSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == ScreenAuditSeverity.WARNING)

    def to_dict(self) -> dict[str, Any]:
        payload = _serialize(self)
        payload["error_count"] = self.error_count
        payload["warning_count"] = self.warning_count
        return payload


@dataclass(slots=True)
class ScreenPolicyState:
    phase: str
    feature_enabled: bool
    planner_routing_enabled: bool
    action_policy_mode: ActionPolicyMode = ActionPolicyMode.OBSERVE_ONLY
    action_execution_enabled: bool = False
    verification_enabled: bool = False
    restricted_domain_guarded: bool = True
    confirmation_required: bool = False
    debug_events_enabled: bool = False
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenRecoveryState:
    status: ScreenRecoveryStatus = ScreenRecoveryStatus.STEADY
    trigger_conditions: list[str] = field(default_factory=list)
    recovered_via: list[str] = field(default_factory=list)
    unresolved_conditions: list[str] = field(default_factory=list)
    retry_behavior: str | None = None
    handoff_required: bool = False
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenObservation:
    captured_at: str = ""
    scope: ScreenObservationScope = ScreenObservationScope.ACTIVE_WINDOW
    source_types_used: list[ScreenSourceType] = field(default_factory=list)
    window_metadata: dict[str, Any] = field(default_factory=dict)
    app_identity: str | None = None
    capture_reference: str | None = None
    selected_text: str | None = None
    clipboard_text: str | None = None
    visual_text: str | None = None
    workspace_snapshot: dict[str, Any] = field(default_factory=dict)
    monitor_metadata: dict[str, Any] = field(default_factory=dict)
    quality_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    selection_metadata: dict[str, Any] = field(default_factory=dict)
    focus_metadata: dict[str, Any] = field(default_factory=dict)
    cursor_metadata: dict[str, Any] = field(default_factory=dict)
    visual_metadata: dict[str, Any] = field(default_factory=dict)
    sensitivity: ScreenSensitivityLevel = ScreenSensitivityLevel.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenInterpretation:
    likely_environment: str | None = None
    visible_purpose: str | None = None
    visible_messages: list[str] = field(default_factory=list)
    visible_entities: list[str] = field(default_factory=list)
    visible_errors: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    candidate_next_actions: list[str] = field(default_factory=list)
    likely_task: str | None = None
    question_relevant_findings: list[str] = field(default_factory=list)
    confidence_by_facet: dict[str, ScreenConfidence] = field(default_factory=dict)
    uncertainty_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class CurrentScreenContext:
    context_id: str
    active_environment: str | None = None
    summary: str | None = None
    visible_task_state: str | None = None
    blockers_or_prompts: list[str] = field(default_factory=list)
    candidate_next_steps: list[str] = field(default_factory=list)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No live screen context is available.",
        )
    )
    sensitivity_markers: list[str] = field(default_factory=list)
    ephemeral_context_id: str | None = None
    adapter_resolution: AppAdapterResolution | None = None
    semantic_targets: list[AppSemanticTarget] = field(default_factory=list)
    monitor_topology: MonitorTopology | None = None
    workspace_map: WorkspaceMap | None = None
    accessibility_summary: AccessibilitySummary | None = None
    focus_context: FocusContext | None = None
    visible_translations: list[VisibleTranslation] = field(default_factory=list)
    extracted_entity_set: ExtractedEntitySet | None = None
    notification_events: list[NotificationEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserTabIdentity:
    title: str | None = None
    index: int | None = None
    active: bool = True
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserFormSemantic:
    field_id: str
    label: str
    role: GroundingCandidateRole = GroundingCandidateRole.FIELD
    visible: bool = True
    enabled: bool | None = None
    kind: str | None = None
    semantic_type: str | None = None
    bounds: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrowserSemanticContext:
    page_title: str | None = None
    url: str | None = None
    tab_identity: BrowserTabIdentity | None = None
    loading_state: str | None = None
    validation_messages: list[str] = field(default_factory=list)
    form_fields: list[BrowserFormSemantic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ExplorerSemanticContext:
    current_path: str | None = None
    selected_item_name: str | None = None
    selected_item_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class AppSemanticTarget:
    candidate_id: str
    label: str
    role: GroundingCandidateRole
    visible: bool = True
    enabled: bool | None = None
    parent_container: str | None = None
    bounds: dict[str, Any] = field(default_factory=dict)
    source_type: ScreenSourceType = ScreenSourceType.APP_ADAPTER
    semantic_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class AppSemanticContext:
    adapter_id: AppAdapterId
    summary: str = ""
    page_title: str | None = None
    url: str | None = None
    current_path: str | None = None
    selected_item_label: str | None = None
    selected_item_kind: str | None = None
    loading_state: str | None = None
    tab_identity: BrowserTabIdentity | None = None
    browser: BrowserSemanticContext | None = None
    explorer: ExplorerSemanticContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class AppAdapterResolution:
    adapter_id: AppAdapterId
    available: bool
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No adapter semantics are available.",
        )
    )
    semantic_context: AppSemanticContext | None = None
    semantic_targets: list[AppSemanticTarget] = field(default_factory=list)
    freshness_seconds: float | None = None
    fallback_reason: AdapterFallbackReason | None = None
    provenance_note: str = ""
    used_for_context: bool = False
    used_for_grounding: bool = False
    used_for_navigation: bool = False
    used_for_verification: bool = False
    used_for_action: bool = False
    used_for_continuity: bool = False
    used_for_problem_solving: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class GroundingRequest:
    utterance: str
    request_type: GroundingRequestType
    target_phrase: str = ""
    label_tokens: list[str] = field(default_factory=list)
    spatial_descriptors: list[str] = field(default_factory=list)
    role_descriptors: list[GroundingCandidateRole] = field(default_factory=list)
    appearance_descriptors: list[str] = field(default_factory=list)
    has_selected_region: bool = False
    has_focus_anchor: bool = False
    has_cursor_anchor: bool = False
    mode_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class GroundingEvidence:
    signal: str
    channel: GroundingEvidenceChannel
    score: float
    note: str
    truth_state: ScreenTruthState = ScreenTruthState.OBSERVED

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class GroundingScore:
    source_trust_weight: float = 0.0
    selection_match: float = 0.0
    focus_match: float = 0.0
    label_match: float = 0.0
    role_match: float = 0.0
    positional_match: float = 0.0
    appearance_match: float = 0.0
    semantic_match: float = 0.0
    penalty: float = 0.0
    final_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class GroundingCandidate:
    candidate_id: str
    label: str
    role: GroundingCandidateRole
    source_channel: GroundingEvidenceChannel
    source_type: ScreenSourceType | None = None
    visible_text: str | None = None
    visible_state: str = "visible"
    enabled: bool | None = None
    parent_container: str | None = None
    bounds: dict[str, Any] = field(default_factory=dict)
    semantic_metadata: dict[str, Any] = field(default_factory=dict)
    evidence: list[GroundingEvidence] = field(default_factory=list)
    score: GroundingScore = field(default_factory=GroundingScore)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class GroundedTarget:
    candidate_id: str
    label: str
    role: GroundingCandidateRole
    source_channel: GroundingEvidenceChannel
    source_type: ScreenSourceType | None = None
    visible_text: str | None = None
    enabled: bool | None = None
    parent_container: str | None = None
    bounds: dict[str, Any] = field(default_factory=dict)
    semantic_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class GroundingProvenance:
    channels_used: list[GroundingEvidenceChannel] = field(default_factory=list)
    dominant_channel: GroundingEvidenceChannel | None = None
    signal_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class GroundingExplanation:
    summary: str
    evidence_summary: list[str] = field(default_factory=list)
    ambiguity_note: str | None = None
    truthfulness_note: str = "Observed evidence and inferred interpretation remain separate."

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ClarificationNeed:
    needed: bool
    reason: str
    prompt: str
    candidate_labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PlannerGroundingResult:
    request_type: GroundingRequestType
    resolved: bool
    winning_candidate_id: str | None = None
    alternative_candidate_ids: list[str] = field(default_factory=list)
    ambiguity_status: GroundingAmbiguityStatus = GroundingAmbiguityStatus.NOT_REQUESTED
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No grounding result is available.",
        )
    )
    explanation_summary: str = ""
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class GroundingOutcome:
    request: GroundingRequest
    winning_target: GroundedTarget | None = None
    ranked_candidates: list[GroundingCandidate] = field(default_factory=list)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No grounded target could be resolved.",
        )
    )
    ambiguity_status: GroundingAmbiguityStatus = GroundingAmbiguityStatus.NOT_REQUESTED
    explanation: GroundingExplanation = field(
        default_factory=lambda: GroundingExplanation(
            summary="Grounding was not requested.",
            evidence_summary=[],
        )
    )
    provenance: GroundingProvenance = field(default_factory=GroundingProvenance)
    clarification_need: ClarificationNeed | None = None
    planner_result: PlannerGroundingResult | None = None
    sensitivity_markers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NavigationRequest:
    utterance: str
    request_type: NavigationRequestType
    label_tokens: list[str] = field(default_factory=list)
    role_descriptors: list[GroundingCandidateRole] = field(default_factory=list)
    wants_next_step_guidance: bool = False
    wants_page_check: bool = False
    wants_recovery: bool = False
    wants_blocker_check: bool = False
    mode_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NavigationContext:
    current_summary: str = ""
    visible_task_state: str | None = None
    candidate_next_steps: list[str] = field(default_factory=list)
    blocker_cues: list[str] = field(default_factory=list)
    active_item_label: str | None = None
    active_item_kind: str | None = None
    grounded_target: GroundedTarget | None = None
    grounding_status: GroundingAmbiguityStatus = GroundingAmbiguityStatus.NOT_REQUESTED
    grounding_reused: bool = False
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NavigationStepState:
    status: NavigationStepStatus
    current_step_summary: str
    expected_target_label: str | None = None
    on_path: bool | None = None
    blocked: bool = False
    wrong_page: bool = False
    reentry_possible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NavigationCandidate:
    candidate_id: str
    label: str
    role: GroundingCandidateRole
    source_channel: GroundingEvidenceChannel
    source_type: ScreenSourceType | None = None
    enabled: bool | None = None
    parent_container: str | None = None
    bounds: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    based_on_grounding: bool = False
    semantic_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NavigationGuidance:
    instruction: str
    look_for: str | None = None
    reasoning_summary: str = ""
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No guidance confidence is available.",
        )
    )
    provenance_note: str = ""
    target_candidate_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NavigationBlocker:
    blocker_type: str
    summary: str
    evidence_summary: list[str] = field(default_factory=list)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No blocker confidence is available.",
        )
    )
    candidate_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NavigationRecoveryHint:
    summary: str
    reason: str
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No recovery confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NavigationAmbiguityState:
    ambiguous: bool
    reason: str
    candidate_labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NavigationClarificationNeed:
    needed: bool
    reason: str
    prompt: str
    candidate_labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PlannerNavigationResult:
    request_type: NavigationRequestType
    resolved: bool
    next_candidate_id: str | None = None
    alternative_candidate_ids: list[str] = field(default_factory=list)
    step_status: NavigationStepStatus = NavigationStepStatus.UNRESOLVED
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No navigation result is available.",
        )
    )
    explanation_summary: str = ""
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)
    blocker_present: bool = False
    wrong_page: bool = False
    clarification_needed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NavigationOutcome:
    request: NavigationRequest
    context: NavigationContext
    step_state: NavigationStepState
    winning_candidate: NavigationCandidate | None = None
    ranked_candidates: list[NavigationCandidate] = field(default_factory=list)
    guidance: NavigationGuidance | None = None
    blocker: NavigationBlocker | None = None
    recovery_hint: NavigationRecoveryHint | None = None
    ambiguity_state: NavigationAmbiguityState | None = None
    clarification_need: NavigationClarificationNeed | None = None
    planner_result: PlannerNavigationResult | None = None
    provenance: GroundingProvenance = field(default_factory=GroundingProvenance)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No navigation outcome is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class VerificationRequest:
    utterance: str
    request_type: VerificationRequestType
    referenced_tokens: list[str] = field(default_factory=list)
    wants_change_summary: bool = False
    wants_completion_check: bool = False
    wants_page_check: bool = False
    wants_error_check: bool = False
    wants_blocker_check: bool = False
    mode_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class VerificationEvidence:
    signal: str
    channel: GroundingEvidenceChannel
    score: float
    note: str
    truth_state: ScreenTruthState = ScreenTruthState.OBSERVED

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class VerificationContext:
    current_summary: str = ""
    prior_summary: str | None = None
    current_page_label: str | None = None
    prior_page_label: str | None = None
    expected_target_label: str | None = None
    prior_resolution_available: bool = False
    grounding_reused: bool = False
    navigation_reused: bool = False
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class VerificationExpectation:
    summary: str
    target_label: str | None = None
    derived_from: str = ""
    expected_presence: list[str] = field(default_factory=list)
    expected_absence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class VerificationComparison:
    basis: str
    prior_state_available: bool
    comparison_ready: bool
    change_classification: ChangeClassification
    compared_signals: list[str] = field(default_factory=list)
    summary: str = ""
    basis_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ChangeObservation:
    change_type: str
    classification: ChangeClassification
    summary: str
    evidence_summary: list[str] = field(default_factory=list)
    from_value: str | None = None
    to_value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class UnresolvedCondition:
    condition_type: str
    summary: str
    evidence_summary: list[str] = field(default_factory=list)
    still_present: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class VerificationExplanation:
    summary: str
    evidence_summary: list[str] = field(default_factory=list)
    unresolved_summary: str | None = None
    truthfulness_note: str = "Verification claims stay bounded to the observed current state and any explicit comparison basis."

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenCalculationActivity:
    status: str
    caller_intent: str
    input_origin: str
    source_text_preview: str = ""
    extracted_expression: str | None = None
    claim_text: str | None = None
    internal_validation: bool = False
    result_visibility: str = "user_facing"
    ambiguous_reason: str | None = None
    summary: str | None = None
    calculation_trace: dict[str, Any] = field(default_factory=dict)
    calculation_result: dict[str, Any] | None = None
    calculation_failure: dict[str, Any] | None = None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No calculation activity is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PlannerVerificationResult:
    request_type: VerificationRequestType
    resolved: bool
    completion_status: CompletionStatus
    change_classification: ChangeClassification
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No verification result is available.",
        )
    )
    explanation_summary: str = ""
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)
    grounding_reused: bool = False
    navigation_reused: bool = False
    comparison_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class VerificationOutcome:
    request: VerificationRequest
    context: VerificationContext
    expectation: VerificationExpectation | None = None
    evidence: list[VerificationEvidence] = field(default_factory=list)
    comparison: VerificationComparison = field(
        default_factory=lambda: VerificationComparison(
            basis="current_state_only",
            prior_state_available=False,
            comparison_ready=False,
            change_classification=ChangeClassification.INSUFFICIENT_EVIDENCE,
            summary="No prior screen bearing is available for comparison.",
        )
    )
    completion_status: CompletionStatus = CompletionStatus.AMBIGUOUS
    change_observations: list[ChangeObservation] = field(default_factory=list)
    unresolved_conditions: list[UnresolvedCondition] = field(default_factory=list)
    explanation: VerificationExplanation = field(
        default_factory=lambda: VerificationExplanation(
            summary="The current verification bearing is unavailable.",
        )
    )
    planner_result: PlannerVerificationResult | None = None
    provenance: GroundingProvenance = field(default_factory=GroundingProvenance)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No verification outcome is available.",
        )
    )
    calculation_activity: ScreenCalculationActivity | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ActionExecutionRequest:
    utterance: str
    intent: ActionIntent
    target_tokens: list[str] = field(default_factory=list)
    typed_text: str | None = None
    key_name: str | None = None
    hotkey_sequence: list[str] = field(default_factory=list)
    scroll_direction: str | None = None
    scroll_amount: int | None = None
    follow_up_confirmation: bool = False
    mode_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = _serialize(self)
        if isinstance(payload, dict) and payload.get("typed_text") is not None:
            payload["typed_text"] = "[redacted]"
        return payload


@dataclass(slots=True)
class ActionTarget:
    candidate_id: str | None = None
    label: str | None = None
    role: GroundingCandidateRole = GroundingCandidateRole.UNKNOWN
    source_channel: GroundingEvidenceChannel | None = None
    source_type: ScreenSourceType | None = None
    enabled: bool | None = None
    bounds: dict[str, Any] = field(default_factory=dict)
    semantic_metadata: dict[str, Any] = field(default_factory=dict)
    equivalent_execution_basis: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ActionVerificationLink:
    verification_ready: bool
    expectation_summary: str = ""
    comparison_basis: str = "current_state_only"
    prior_bearing_injected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ActionPlan:
    request: ActionExecutionRequest
    action_intent: ActionIntent
    target: ActionTarget | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    preview_summary: str = ""
    verification_link: ActionVerificationLink = field(
        default_factory=lambda: ActionVerificationLink(verification_ready=False)
    )
    grounding_reused: bool = False
    navigation_reused: bool = False
    verification_reused: bool = True
    text_payload_redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = _serialize(self)
        if isinstance(payload, dict):
            parameters = payload.get("parameters")
            if isinstance(parameters, dict) and "text" in parameters:
                parameters["text"] = "[redacted]"
        return payload


@dataclass(slots=True)
class ActionGateDecision:
    allowed: bool
    outcome: str
    reason: str
    policy_mode: ActionPolicyMode
    risk_level: ActionRiskLevel
    confirmation_required: bool = False
    ambiguity_present: bool = False
    blocker_present: bool = False
    verification_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ActionExecutionAttempt:
    action_intent: ActionIntent
    target_candidate_id: str | None = None
    success: bool = False
    executor_name: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    typed_text_redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PlannerActionResult:
    resolved: bool
    execution_status: ActionExecutionStatus
    target_candidate_id: str | None = None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No action result is available.",
        )
    )
    risk_level: ActionRiskLevel = ActionRiskLevel.LOW
    explanation_summary: str = ""
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)
    confirmation_required: bool = False
    grounding_reused: bool = False
    navigation_reused: bool = False
    verification_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ActionExecutionResult:
    request: ActionExecutionRequest
    plan: ActionPlan
    gate: ActionGateDecision
    attempt: ActionExecutionAttempt | None = None
    post_action_verification: VerificationOutcome | None = None
    status: ActionExecutionStatus = ActionExecutionStatus.GATED
    explanation_summary: str = ""
    planner_result: PlannerActionResult | None = None
    provenance: GroundingProvenance = field(default_factory=GroundingProvenance)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No action outcome is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowContinuityRequest:
    utterance: str
    request_type: WorkflowContinuityRequestType
    wants_resume: bool = False
    wants_recovery: bool = False
    wants_detour_help: bool = False
    wants_backtrack_check: bool = False
    wants_undo_hint: bool = False
    mode_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowStepState:
    summary: str
    expected_target_label: str | None = None
    page_label: str | None = None
    source_intent: str = ""
    completion_status: str | None = None
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowDetourState:
    active: bool
    detour_type: str
    summary: str
    current_label: str | None = None
    prior_task_summary: str | None = None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No detour confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowRecoveryHint:
    summary: str
    reason: str
    target_label: str | None = None
    bounded_undo_hint: bool = False
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No recovery confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowResumeCandidate:
    candidate_id: str | None
    label: str
    source_layer: str
    summary: str
    score: float
    evidence_summary: list[str] = field(default_factory=list)
    from_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowTimelineEvent:
    event_id: str
    event_type: str
    source_intent: str
    summary: str
    captured_at: str = ""
    page_label: str | None = None
    target_label: str | None = None
    target_candidate_id: str | None = None
    completion_status: str | None = None
    confidence_score: float = 0.0
    stale: bool = False
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowContinuityContext:
    current_summary: str = ""
    current_page_label: str | None = None
    current_modal_label: str | None = None
    recent_event_count: int = 0
    recent_screen_available: bool = False
    grounding_reused: bool = False
    navigation_reused: bool = False
    verification_reused: bool = False
    action_reused: bool = False
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PlannerContinuityResult:
    request_type: WorkflowContinuityRequestType
    resolved: bool
    status: WorkflowContinuityStatus
    resume_candidate_id: str | None = None
    alternative_resume_candidate_ids: list[str] = field(default_factory=list)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No continuity result is available.",
        )
    )
    explanation_summary: str = ""
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)
    detour_active: bool = False
    blocked: bool = False
    clarification_needed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowContinuityResult:
    request: WorkflowContinuityRequest
    context: WorkflowContinuityContext
    status: WorkflowContinuityStatus
    active_step: WorkflowStepState | None = None
    detour_state: WorkflowDetourState | None = None
    recovery_hint: WorkflowRecoveryHint | None = None
    resume_candidate: WorkflowResumeCandidate | None = None
    resume_options: list[WorkflowResumeCandidate] = field(default_factory=list)
    timeline_events: list[WorkflowTimelineEvent] = field(default_factory=list)
    clarification_needed: bool = False
    clarification_prompt: str | None = None
    explanation_summary: str = ""
    planner_result: PlannerContinuityResult | None = None
    provenance: GroundingProvenance = field(default_factory=GroundingProvenance)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No workflow continuity result is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ErrorTriageOutcome:
    classification: str | None = None
    severity: str = "unknown"
    observed_message: str = ""
    meaning_summary: str = ""
    bounded_next_step: str | None = None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No error triage outcome is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenArtifactInterpretation:
    artifact_kind: ScreenArtifactKind = ScreenArtifactKind.UNKNOWN
    observed_excerpt: str = ""
    structured_summary: str = ""
    visible_values: list[str] = field(default_factory=list)
    uncertainty_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenProblemContext:
    visible_text_preview: str = ""
    grounding_reused: bool = False
    navigation_reused: bool = False
    verification_reused: bool = False
    action_reused: bool = False
    continuity_reused: bool = False
    adapter_reused: bool = False
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PlannerProblemSolvingResult:
    resolved: bool
    problem_type: ScreenProblemType = ScreenProblemType.UNKNOWN
    artifact_kind: ScreenArtifactKind = ScreenArtifactKind.UNKNOWN
    explanation_mode: ExplanationMode = ExplanationMode.CONCISE_EXPLANATION
    answer_status: ProblemAnswerStatus = ProblemAnswerStatus.REFUSED
    ambiguity_state: ProblemAmbiguityState = ProblemAmbiguityState.INSUFFICIENT_EVIDENCE
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No problem-solving result is available.",
        )
    )
    refusal_reason: str | None = None
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)
    adapter_contribution: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ProblemSolvingResult:
    problem_type: ScreenProblemType = ScreenProblemType.UNKNOWN
    artifact_kind: ScreenArtifactKind = ScreenArtifactKind.UNKNOWN
    explanation_mode: ExplanationMode = ExplanationMode.CONCISE_EXPLANATION
    teaching_mode: TeachingMode = TeachingMode.NONE
    answer_status: ProblemAnswerStatus = ProblemAnswerStatus.REFUSED
    ambiguity_state: ProblemAmbiguityState = ProblemAmbiguityState.INSUFFICIENT_EVIDENCE
    context: ScreenProblemContext = field(default_factory=ScreenProblemContext)
    triage: ErrorTriageOutcome | None = None
    artifact_interpretation: ScreenArtifactInterpretation | None = None
    answer_summary: str = ""
    answer_steps: list[str] = field(default_factory=list)
    background_note: str | None = None
    refusal_reason: str | None = None
    planner_result: PlannerProblemSolvingResult | None = None
    provenance: GroundingProvenance = field(default_factory=GroundingProvenance)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No problem-solving result is available.",
        )
    )
    reused_adapter: bool = False
    reused_grounding: bool = False
    reused_navigation: bool = False
    reused_verification: bool = False
    reused_action: bool = False
    reused_continuity: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowObservationSession:
    session_id: str
    started_at: str
    active: bool = True
    label_hint: str | None = None
    observed_resolution_count: int = 0
    captured_step_count: int = 0
    last_captured_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowStepEvent:
    event_id: str
    source_intent: str
    summary: str
    captured_at: str = ""
    page_label: str | None = None
    target_label: str | None = None
    target_candidate_id: str | None = None
    action_intent: ActionIntent | None = None
    completion_status: str | None = None
    confidence_score: float = 0.0
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)
    sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowStepSequence:
    steps: list[WorkflowStepEvent] = field(default_factory=list)
    summary: str = ""
    stable_signals: list[str] = field(default_factory=list)
    variable_signals: list[str] = field(default_factory=list)
    sensitive_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowLabel:
    primary_label: str
    category: str = "screen_workflow"
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowCandidate:
    candidate_id: str
    label: WorkflowLabel
    step_sequence: WorkflowStepSequence
    summary: str
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No workflow candidate confidence is available.",
        )
    )
    environment_hints: list[str] = field(default_factory=list)
    known_failure_notes: list[str] = field(default_factory=list)
    allowed_reuse_modes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ReusableWorkflow:
    workflow_id: str
    label: WorkflowLabel
    summary: str
    step_sequence: WorkflowStepSequence
    accepted_at: str
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No reusable workflow confidence is available.",
        )
    )
    environment_hints: list[str] = field(default_factory=list)
    known_failure_notes: list[str] = field(default_factory=list)
    allowed_reuse_modes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowReuseSafetyState:
    allowed: bool
    reason: str
    blocked: bool = False
    ambiguous: bool = False
    sensitive: bool = False
    verification_ready: bool = False
    current_target_supported: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowMatchResult:
    workflow_id: str | None
    workflow_label: str | None
    status: WorkflowMatchStatus
    match_score: float
    explanation_summary: str
    evidence_summary: list[str] = field(default_factory=list)
    matched_step_labels: list[str] = field(default_factory=list)
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No workflow match confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowReusePlan:
    workflow_id: str
    workflow_label: str
    reuse_mode: str
    explanation_summary: str
    next_step_label: str | None = None
    current_target_candidate_id: str | None = None
    action_request_text: str | None = None
    grounding_reused: bool = False
    navigation_reused: bool = False
    verification_reused: bool = False
    action_reused: bool = False
    confirmation_required: bool = False
    safety_state: WorkflowReuseSafetyState = field(
        default_factory=lambda: WorkflowReuseSafetyState(allowed=False, reason="No workflow reuse safety state is available.")
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PlannerWorkflowReuseResult:
    resolved: bool
    status: WorkflowLearningStatus
    workflow_id: str | None = None
    match_score: float = 0.0
    reuse_mode: str | None = None
    next_step_label: str | None = None
    explanation_summary: str = ""
    confirmation_required: bool = False
    attempted_reuse: bool = False
    verified_reuse: bool = False
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkflowLearningResult:
    request_type: WorkflowLearningRequestType
    status: WorkflowLearningStatus
    observation_session: WorkflowObservationSession | None = None
    candidate: WorkflowCandidate | None = None
    reusable_workflow: ReusableWorkflow | None = None
    available_workflows: list[ReusableWorkflow] = field(default_factory=list)
    match_result: WorkflowMatchResult | None = None
    reuse_plan: WorkflowReusePlan | None = None
    capture_status: str | None = None
    clarification_needed: bool = False
    clarification_prompt: str | None = None
    explanation_summary: str = ""
    planner_result: PlannerWorkflowReuseResult | None = None
    provenance: GroundingProvenance = field(default_factory=GroundingProvenance)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No workflow-learning result is available.",
        )
    )
    attempted_reuse: bool = False
    verified_reuse: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class TaskGraphNode:
    node_id: str
    label: str
    node_type: str
    status: str
    last_seen_at: str
    blocker_summaries: list[str] = field(default_factory=list)
    verified_outcomes: list[str] = field(default_factory=list)
    resumable_next_step: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class TaskGraphLink:
    link_id: str
    from_node_id: str
    to_node_id: str
    relation: str
    summary: str
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No task-graph link confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class TaskGraph:
    graph_id: str
    task_label: str
    session_id: str
    current_node_id: str | None = None
    nodes: list[TaskGraphNode] = field(default_factory=list)
    links: list[TaskGraphLink] = field(default_factory=list)
    active: bool = True
    last_updated_at: str = ""
    freshness_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class SessionMemoryRecord:
    record_id: str
    category: str
    summary: str
    task_graph_id: str | None
    created_at: str
    provenance_kind: str
    evidence_count: int = 1
    freshness_seconds: float | None = None
    sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class LongTermMemoryCandidate:
    candidate_id: str
    category: str
    summary: str
    source_task_graph_id: str | None
    evidence_count: int
    usefulness_score: float
    sensitivity: ScreenSensitivityLevel
    created_at: str
    freshness_seconds: float | None = None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No long-term memory candidate confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class LongTermMemoryBindingDecision:
    target_layer: MemoryBindingTarget
    reason: str
    explicit_request: bool = False
    privacy_blocked: bool = False
    freshness_blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class LearnedPreference:
    preference_key: str
    value: str
    scope: str
    evidence_count: int
    learned_at: str
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No learned-preference confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class EnvironmentQuirk:
    quirk_id: str
    summary: str
    scope: str
    evidence_count: int
    learned_at: str
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No environment-quirk confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ProactiveContinuitySuggestion:
    suggestion_id: str
    summary: str
    basis_summary: str
    task_graph_id: str | None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No proactive-continuity confidence is available.",
        )
    )
    suppressible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PlannerBrainIntegrationResult:
    resolved: bool
    status: BrainIntegrationStatus
    task_graph_id: str | None = None
    binding_target: MemoryBindingTarget | None = None
    long_term_candidate_id: str | None = None
    preference_key: str | None = None
    environment_quirk_id: str | None = None
    proactive_suggestion_present: bool = False
    explanation_summary: str = ""
    provenance_channels: list[GroundingEvidenceChannel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class BrainIntegrationResult:
    request_type: BrainIntegrationRequestType
    status: BrainIntegrationStatus
    task_graph: TaskGraph | None = None
    session_memory_entries: list[SessionMemoryRecord] = field(default_factory=list)
    long_term_candidate: LongTermMemoryCandidate | None = None
    binding_decision: LongTermMemoryBindingDecision | None = None
    learned_preference: LearnedPreference | None = None
    environment_quirk: EnvironmentQuirk | None = None
    proactive_suggestion: ProactiveContinuitySuggestion | None = None
    explanation_summary: str = ""
    planner_result: PlannerBrainIntegrationResult | None = None
    provenance: GroundingProvenance = field(default_factory=GroundingProvenance)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No brain-integration result is available.",
        )
    )
    reused_workflow_learning: bool = False
    reused_continuity: bool = False
    reused_verification: bool = False
    reused_action: bool = False
    reused_adapter: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class MonitorDescriptor:
    monitor_id: str
    label: str
    is_primary: bool = False
    bounds: dict[str, Any] = field(default_factory=dict)
    scale: float | None = None
    relative_position: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class MonitorTopology:
    monitors: list[MonitorDescriptor] = field(default_factory=list)
    active_monitor_id: str | None = None
    active_monitor_label: str | None = None
    summary: str = ""
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No monitor-topology confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkspaceWindow:
    window_id: str
    title: str
    app_identity: str | None = None
    monitor_id: str | None = None
    focused: bool = False
    minimized: bool = False
    modal_owner_id: str | None = None
    bounds: dict[str, Any] = field(default_factory=dict)
    task_relevance: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class WorkspaceMap:
    windows: list[WorkspaceWindow] = field(default_factory=list)
    active_window_id: str | None = None
    summary: str = ""
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No workspace-map confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class AccessibilitySummary:
    focused_label: str | None = None
    focused_role: str | None = None
    enabled: bool | None = None
    keyboard_hint: str | None = None
    narration_summary: str | None = None
    simplified_summary: str | None = None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No accessibility-summary confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class FocusContext:
    focus_path: list[str] = field(default_factory=list)
    control_label: str | None = None
    control_role: str | None = None
    enabled: bool | None = None
    monitor_id: str | None = None
    window_id: str | None = None
    keyboard_traversal: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class OverlayAnchor:
    monitor_id: str | None = None
    window_id: str | None = None
    target_candidate_id: str | None = None
    bounds: dict[str, Any] = field(default_factory=dict)
    precision: OverlayAnchorPrecision = OverlayAnchorPrecision.APPROXIMATE
    provenance_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class OverlayInstruction:
    overlay_id: str
    kind: str
    label: str
    anchor: OverlayAnchor
    numbered_step: int | None = None
    expires_after_seconds: float | None = None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No overlay-instruction confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class VisibleTranslation:
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    role_context: str | None = None
    direct_translation: bool = True
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No translation confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ExtractedEntity:
    entity_id: str
    entity_type: str
    raw_value: str
    normalized_value: str | None = None
    source_text: str | None = None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No extracted-entity confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ExtractedEntitySet:
    entities: list[ExtractedEntity] = field(default_factory=list)
    summary: str = ""
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No extracted-entity-set confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class NotificationEvent:
    notification_id: str
    title: str
    body: str = ""
    app_identity: str | None = None
    severity: NotificationSeverity = NotificationSeverity.INFO
    blocker: bool = False
    passive: bool = True
    monitor_id: str | None = None
    kind: str | None = None
    observed_at: str = ""
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No notification-event confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class CrossMonitorTargetContext:
    target_candidate_id: str | None = None
    active_monitor_id: str | None = None
    target_monitor_id: str | None = None
    summary: str = ""
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No cross-monitor target confidence is available.",
        )
    )

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PlannerPowerFeaturesResult:
    resolved: bool
    request_type: PowerFeatureRequestType
    monitor_count: int = 0
    workspace_window_count: int = 0
    translation_count: int = 0
    entity_count: int = 0
    notification_count: int = 0
    overlay_instruction_count: int = 0
    explanation_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PowerFeaturesResult:
    request_type: PowerFeatureRequestType
    monitor_topology: MonitorTopology | None = None
    workspace_map: WorkspaceMap | None = None
    accessibility_summary: AccessibilitySummary | None = None
    focus_context: FocusContext | None = None
    overlay_instructions: list[OverlayInstruction] = field(default_factory=list)
    translations: list[VisibleTranslation] = field(default_factory=list)
    extracted_entities: ExtractedEntitySet | None = None
    notification_events: list[NotificationEvent] = field(default_factory=list)
    cross_monitor_target_context: CrossMonitorTargetContext | None = None
    explanation_summary: str = ""
    planner_result: PlannerPowerFeaturesResult | None = None
    provenance: GroundingProvenance = field(default_factory=GroundingProvenance)
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No power-features result is available.",
        )
    )
    reused_grounding: bool = False
    reused_navigation: bool = False
    reused_verification: bool = False
    reused_action: bool = False
    reused_continuity: bool = False
    reused_adapter: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ScreenAnalysisResult:
    observation: ScreenObservation | None = None
    interpretation: ScreenInterpretation | None = None
    current_screen_context: CurrentScreenContext | None = None
    adapter_resolution: AppAdapterResolution | None = None
    grounding_result: GroundingOutcome | None = None
    navigation_result: NavigationOutcome | None = None
    verification_result: VerificationOutcome | None = None
    action_result: ActionExecutionResult | None = None
    continuity_result: WorkflowContinuityResult | None = None
    problem_solving_result: ProblemSolvingResult | None = None
    workflow_learning_result: WorkflowLearningResult | None = None
    brain_integration_result: BrainIntegrationResult | None = None
    power_features_result: PowerFeaturesResult | None = None
    calculation_activity: ScreenCalculationActivity | None = None
    limitations: list[ScreenLimitation] = field(default_factory=list)
    fallback_reason: str | None = None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No live screen analysis is available.",
        )
    )
    evidence_ranking: list[dict[str, Any]] = field(default_factory=list)
    observation_attempted: bool = False
    observation_available: bool = False
    observation_allowed: bool = False
    observation_blocked_reason: str | None = None
    observation_source: str | None = None
    observation_freshness: str | None = None
    observation_confidence: dict[str, Any] = field(default_factory=dict)
    evidence_before_observation: list[dict[str, Any]] = field(default_factory=list)
    evidence_after_observation: list[dict[str, Any]] = field(default_factory=list)
    answered_from_source: str | None = None
    weak_fallback_used: bool = False
    no_visual_evidence_reason: str | None = None
    visible_context_summary: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    latency_trace: ScreenLatencyTrace | None = None
    truthfulness_audit: ScreenTruthfulnessAudit | None = None
    policy_state: ScreenPolicyState | None = None
    recovery_state: ScreenRecoveryState | None = None
    truthfulness_contract: ScreenTruthfulnessContract = field(default_factory=ScreenTruthfulnessContract)
    verification_state: ScreenTruthState = ScreenTruthState.UNVERIFIED

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)

    @classmethod
    def phase_zero_placeholder(
        cls,
        *,
        intent: ScreenIntentType,
        surface_mode: str,
        active_module: str,
    ) -> ScreenAnalysisResult:
        summary = "Live screen context is not available in this Phase 0 foundation pass."
        observation = ScreenObservation(
            scope=ScreenObservationScope.ACTIVE_WINDOW,
            source_types_used=[ScreenSourceType.PLACEHOLDER],
            window_metadata={
                "surface_mode": surface_mode,
                "active_module": active_module,
            },
            quality_notes=["Phase 0 foundation scaffold only."],
            warnings=["Live screen observation has not been enabled yet."],
        )
        interpretation = ScreenInterpretation(
            likely_environment="screen_awareness_phase0",
            visible_purpose="foundation_only",
            candidate_next_actions=["Enable a future observation source in Phase 1."],
            likely_task=intent.value,
            confidence_by_facet={
                "environment": ScreenConfidence(
                    score=0.15,
                    level=ScreenConfidenceLevel.LOW,
                    note="Only the Phase 0 scaffold is active.",
                )
            },
            uncertainty_notes=["No screenshot, accessibility, DOM, or adapter-backed observation was attempted."],
        )
        current_context = CurrentScreenContext(
            context_id=f"screen-phase0-{uuid4().hex}",
            active_environment="screen_awareness_phase0",
            summary=summary,
            visible_task_state="unavailable",
            blockers_or_prompts=["Live observation is deferred to Phase 1."],
            candidate_next_steps=["Add an observation source.", "Add interpretation routing.", "Keep responses honest."],
            confidence=ScreenConfidence(
                score=0.0,
                level=ScreenConfidenceLevel.NONE,
                note="The current build only exposes the screen-awareness foundation.",
            ),
            sensitivity_markers=[],
            ephemeral_context_id=f"screen-phase0-{uuid4().hex}",
        )
        return cls(
            observation=observation,
            interpretation=interpretation,
            current_screen_context=current_context,
            limitations=[
                ScreenLimitation(
                    code=ScreenLimitationCode.PHASE0_FOUNDATION_ONLY,
                    message="Screen awareness is limited to foundation contracts and telemetry in Phase 0.",
                    truth_state=ScreenTruthState.UNAVAILABLE,
                ),
                ScreenLimitation(
                    code=ScreenLimitationCode.OBSERVATION_UNAVAILABLE,
                    message="No live observation source is active yet.",
                    truth_state=ScreenTruthState.UNAVAILABLE,
                ),
            ],
            fallback_reason="phase0_foundation_only",
            confidence=ScreenConfidence(
                score=0.0,
                level=ScreenConfidenceLevel.NONE,
                note="No live observation occurred.",
            ),
            truthfulness_contract=ScreenTruthfulnessContract(),
            verification_state=ScreenTruthState.UNVERIFIED,
        )


@dataclass(slots=True)
class ScreenResponse:
    analysis: ScreenAnalysisResult
    assistant_response: str
    response_contract: dict[str, str] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)
