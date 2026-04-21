from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4


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
    PHASE0_SCAFFOLD = "phase0_scaffold"


class ScreenLimitationCode(StrEnum):
    OBSERVATION_UNAVAILABLE = "observation_unavailable"
    LOW_CONFIDENCE = "low_confidence"
    PRIOR_OBSERVATION_REQUIRED = "prior_observation_required"
    UNVERIFIED_CHANGE = "unverified_change"
    PHASE0_FOUNDATION_ONLY = "phase0_foundation_only"


class ScreenIntentType(StrEnum):
    INSPECT_VISIBLE_STATE = "inspect_visible_state"
    EXPLAIN_VISIBLE_CONTENT = "explain_visible_content"
    SOLVE_VISIBLE_PROBLEM = "solve_visible_problem"
    DETECT_VISIBLE_CHANGE = "detect_visible_change"


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
    VISUAL_PROVIDER = "visual_provider"
    INTERPRETATION = "interpretation"


class GroundingAmbiguityStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED_INSUFFICIENT_EVIDENCE = "unresolved_insufficient_evidence"
    UNRESOLVED_CONFLICTING_EVIDENCE = "unresolved_conflicting_evidence"


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
class ScreenObservation:
    captured_at: str = ""
    scope: ScreenObservationScope = ScreenObservationScope.ACTIVE_WINDOW
    source_types_used: list[ScreenSourceType] = field(default_factory=list)
    window_metadata: dict[str, Any] = field(default_factory=dict)
    app_identity: str | None = None
    capture_reference: str | None = None
    selected_text: str | None = None
    clipboard_text: str | None = None
    workspace_snapshot: dict[str, Any] = field(default_factory=dict)
    monitor_metadata: dict[str, Any] = field(default_factory=dict)
    quality_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    selection_metadata: dict[str, Any] = field(default_factory=dict)
    focus_metadata: dict[str, Any] = field(default_factory=dict)
    cursor_metadata: dict[str, Any] = field(default_factory=dict)
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
class ScreenAnalysisResult:
    observation: ScreenObservation | None = None
    interpretation: ScreenInterpretation | None = None
    current_screen_context: CurrentScreenContext | None = None
    grounding_result: GroundingOutcome | None = None
    limitations: list[ScreenLimitation] = field(default_factory=list)
    fallback_reason: str | None = None
    confidence: ScreenConfidence = field(
        default_factory=lambda: ScreenConfidence(
            score=0.0,
            level=ScreenConfidenceLevel.NONE,
            note="No live screen analysis is available.",
        )
    )
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
