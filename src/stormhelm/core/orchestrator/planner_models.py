from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {str(key): _serialize(item) for key, item in asdict(value).items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class QueryShape(StrEnum):
    CALCULATION_REQUEST = "calculation_request"
    SOFTWARE_CONTROL_REQUEST = "software_control_request"
    SCREEN_AWARENESS_REQUEST = "screen_awareness_request"
    CAMERA_AWARENESS_REQUEST = "camera_awareness_request"
    DISCORD_RELAY_REQUEST = "discord_relay_request"
    WEB_RETRIEVAL_REQUEST = "web_retrieval_request"
    TRUST_APPROVAL_REQUEST = "trust_approval_request"
    CURRENT_METRIC = "current_metric"
    CURRENT_STATUS = "current_status"
    DIAGNOSTIC_CAUSAL = "diagnostic_causal"
    HISTORY_TREND = "history_trend"
    IDENTITY_LOOKUP = "identity_lookup"
    CONTROL_COMMAND = "control_command"
    OPEN_BROWSER_DESTINATION = "open_browser_destination"
    SEARCH_BROWSER_DESTINATION = "search_browser_destination"
    REPAIR_REQUEST = "repair_request"
    SEARCH_REQUEST = "search_request"
    SEARCH_AND_OPEN = "search_and_open"
    WORKSPACE_REQUEST = "workspace_request"
    WORKFLOW_REQUEST = "workflow_request"
    SUMMARY_REQUEST = "summary_request"
    COMPARISON_REQUEST = "comparison_request"
    FORECAST_REQUEST = "forecast_request"
    BROWSER_CONTEXT = "browser_context"
    CONTEXT_ACTION = "context_action"
    ROUTINE_REQUEST = "routine_request"
    MAINTENANCE_REQUEST = "maintenance_request"
    FILE_OPERATION = "file_operation"
    FOLLOW_UP_MUTATION = "follow_up_mutation"
    UNCLASSIFIED = "unclassified"


class ResponseMode(StrEnum):
    CALCULATION_RESULT = "calculation_result"
    NUMERIC_METRIC = "numeric_metric"
    STATUS_SUMMARY = "status_summary"
    DIAGNOSTIC_SUMMARY = "diagnostic_summary"
    HISTORY_SUMMARY = "history_summary"
    IDENTITY_SUMMARY = "identity_summary"
    ACTION_RESULT = "action_result"
    SEARCH_RESULT = "search_result"
    WEB_EVIDENCE_RESULT = "web_evidence_result"
    WORKSPACE_RESULT = "workspace_result"
    SUMMARY_RESULT = "summary_result"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"
    FORECAST_SUMMARY = "forecast_summary"


class RoutePosture(StrEnum):
    CLEAR_WINNER = "clear_winner"
    LIKELY_WINNER = "likely_winner"
    CONDITIONAL_WINNER = "conditional_winner"
    BLOCKED_WINNER = "blocked_winner"
    UNRESOLVED_COMPETITION = "unresolved_competition"
    NATIVE_UNSUPPORTED = "native_unsupported"
    GENUINE_PROVIDER_FALLBACK = "genuine_provider_fallback"


@dataclass(slots=True)
class RouteTargetCandidate:
    target_type: str
    label: str
    value: Any | None = None
    source: str = "operator_text"
    confidence: float = 0.0
    freshness: str = "current"
    selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type,
            "label": self.label,
            "value": _serialize(self.value),
            "source": self.source,
            "confidence": self.confidence,
            "freshness": self.freshness,
            "selected": self.selected,
        }


@dataclass(slots=True)
class RequestDecomposition:
    action_intent: str | None = None
    subject: str | None = None
    explicit_targets: list[RouteTargetCandidate] = field(default_factory=list)
    deictic_references: list[str] = field(default_factory=list)
    continuity_cues: list[str] = field(default_factory=list)
    correction_cues: list[str] = field(default_factory=list)
    result_expectation: str | None = None
    approval_hints: list[str] = field(default_factory=list)
    verification_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_intent": self.action_intent,
            "subject": self.subject,
            "explicit_targets": _serialize(self.explicit_targets),
            "deictic_references": list(self.deictic_references),
            "continuity_cues": list(self.continuity_cues),
            "correction_cues": list(self.correction_cues),
            "result_expectation": self.result_expectation,
            "approval_hints": list(self.approval_hints),
            "verification_hints": list(self.verification_hints),
        }


@dataclass(slots=True)
class DeicticBindingCandidate:
    source: str
    target_type: str
    label: str
    value: Any | None = None
    confidence: float = 0.0
    freshness: str = "current"
    route_family: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target_type": self.target_type,
            "label": self.label,
            "value": _serialize(self.value),
            "confidence": self.confidence,
            "freshness": self.freshness,
            "route_family": self.route_family,
        }


@dataclass(slots=True)
class DeicticBinding:
    resolved: bool = False
    selected_source: str | None = None
    selected_target: DeicticBindingCandidate | None = None
    candidates: list[DeicticBindingCandidate] = field(default_factory=list)
    unresolved_reason: str | None = None
    binding_posture: str = "none"
    source_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolved": self.resolved,
            "selected_source": self.selected_source,
            "selected_target": _serialize(self.selected_target),
            "candidates": _serialize(self.candidates),
            "unresolved_reason": self.unresolved_reason,
            "binding_posture": self.binding_posture,
            "source_summary": self.source_summary,
        }


@dataclass(slots=True)
class RouteCandidate:
    route_family: str
    query_shape: str | None = None
    score: float = 0.0
    posture_seed: str = "weak"
    semantic_reasons: list[str] = field(default_factory=list)
    score_factors: dict[str, float] = field(default_factory=dict)
    required_targets: list[str] = field(default_factory=list)
    target_candidates: list[RouteTargetCandidate] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    disqualifiers: list[str] = field(default_factory=list)
    clarification_pressure: float = 0.0
    support_augmentation: list[str] = field(default_factory=list)
    provider_fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_family": self.route_family,
            "query_shape": self.query_shape,
            "score": self.score,
            "posture_seed": self.posture_seed,
            "semantic_reasons": list(self.semantic_reasons),
            "score_factors": dict(self.score_factors),
            "required_targets": list(self.required_targets),
            "target_candidates": _serialize(self.target_candidates),
            "missing_evidence": list(self.missing_evidence),
            "disqualifiers": list(self.disqualifiers),
            "clarification_pressure": self.clarification_pressure,
            "support_augmentation": list(self.support_augmentation),
            "provider_fallback_reason": self.provider_fallback_reason,
        }


@dataclass(slots=True)
class RouteWinnerPosture:
    route_family: str
    query_shape: str | None = None
    confidence: float = 0.0
    posture: RoutePosture = RoutePosture.LIKELY_WINNER
    status: str = "immediate"
    score: float = 0.0
    dominant_evidence: list[str] = field(default_factory=list)
    unresolved_targets: list[str] = field(default_factory=list)
    clarification_needed: bool = False
    clarification_reason: str | None = None
    clarification_code: str | None = None
    runner_up_summary: dict[str, Any] | None = None
    support_system_augmentation: list[str] = field(default_factory=list)
    provider_fallback_reason: str | None = None
    margin_to_runner_up: float | None = None
    ambiguity_live: bool = False
    planned_tools: list[str] = field(default_factory=list)
    capability_requirements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_family": self.route_family,
            "query_shape": self.query_shape,
            "confidence": self.confidence,
            "posture": self.posture.value,
            "status": self.status,
            "score": self.score,
            "dominant_evidence": list(self.dominant_evidence),
            "unresolved_targets": list(self.unresolved_targets),
            "clarification_needed": self.clarification_needed,
            "clarification_reason": self.clarification_reason,
            "clarification_code": self.clarification_code,
            "runner_up_summary": _serialize(self.runner_up_summary),
            "support_system_augmentation": list(self.support_system_augmentation),
            "provider_fallback_reason": self.provider_fallback_reason,
            "margin_to_runner_up": self.margin_to_runner_up,
            "ambiguity_live": self.ambiguity_live,
            "planned_tools": list(self.planned_tools),
            "capability_requirements": list(self.capability_requirements),
        }


@dataclass(slots=True)
class RoutingTelemetry:
    normalized_summary: dict[str, Any]
    decomposition: RequestDecomposition
    candidates: list[RouteCandidate]
    winner: RouteWinnerPosture
    runner_up: RouteCandidate | None = None
    deictic_binding: DeicticBinding = field(default_factory=DeicticBinding)
    support_augmentation_summary: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "normalized_summary": dict(self.normalized_summary),
            "decomposition": self.decomposition.to_dict(),
            "candidates": _serialize(self.candidates),
            "winner": self.winner.to_dict(),
            "runner_up": _serialize(self.runner_up),
            "deictic_binding": self.deictic_binding.to_dict(),
            "support_augmentation_summary": list(self.support_augmentation_summary),
        }


@dataclass(slots=True)
class NormalizedCommand:
    raw_text: str
    normalized_text: str
    tokens: list[str]
    surface_mode: str
    active_module: str
    explicitness_level: str = "explicit"

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "tokens": list(self.tokens),
            "surface_mode": self.surface_mode,
            "active_module": self.active_module,
            "explicitness_level": self.explicitness_level,
        }


@dataclass(slots=True)
class SemanticParseProposal:
    query_shape: QueryShape = QueryShape.UNCLASSIFIED
    domain: str | None = None
    requested_metric: str | None = None
    requested_action: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    follow_up: bool = False
    fallback_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_shape": self.query_shape.value,
            "domain": self.domain,
            "requested_metric": self.requested_metric,
            "requested_action": self.requested_action,
            "slots": _serialize(self.slots),
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "follow_up": self.follow_up,
            "fallback_path": self.fallback_path,
        }


@dataclass(slots=True)
class SlotExtractionResult:
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    explicitness_level: str = "explicit"

    def to_dict(self) -> dict[str, Any]:
        return {
            "slots": _serialize(self.slots),
            "missing_slots": list(self.missing_slots),
            "explicitness_level": self.explicitness_level,
        }


@dataclass(slots=True)
class StructuredQuery:
    domain: str | None
    query_shape: QueryShape
    requested_metric: str | None = None
    requested_action: str | None = None
    timescale: str | None = None
    target_scope: str | None = None
    output_mode: str | None = None
    execution_type: str | None = None
    capability_requirements: list[str] = field(default_factory=list)
    confidence: float = 0.0
    diagnostic_mode: bool = False
    output_type: str | None = None
    comparison_target: str | None = None
    current_context_reference: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "query_shape": self.query_shape.value,
            "requested_metric": self.requested_metric,
            "requested_action": self.requested_action,
            "timescale": self.timescale,
            "target_scope": self.target_scope,
            "output_mode": self.output_mode,
            "execution_type": self.execution_type,
            "capability_requirements": list(self.capability_requirements),
            "confidence": self.confidence,
            "diagnostic_mode": self.diagnostic_mode,
            "output_type": self.output_type,
            "comparison_target": self.comparison_target,
            "current_context_reference": self.current_context_reference,
            "slots": _serialize(self.slots),
        }


@dataclass(slots=True)
class UnsupportedReason:
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


@dataclass(slots=True)
class ClarificationReason:
    code: str
    message: str
    missing_slots: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "missing_slots": list(self.missing_slots),
        }


@dataclass(slots=True)
class CapabilityPlan:
    supported: bool
    available_tools: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    candidate_adapters: list[dict[str, Any]] = field(default_factory=list)
    selected_adapter: dict[str, Any] | None = None
    adapter_contract_status: str | None = None
    adapter_contract_errors: list[str] = field(default_factory=list)
    approval_required: bool | None = None
    preview_available: bool | None = None
    rollback_available: bool | None = None
    max_claimable_outcome: str | None = None
    freshness_expectation: str | None = None
    unsupported_reason: UnsupportedReason | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "available_tools": list(self.available_tools),
            "required_tools": list(self.required_tools),
            "required_capabilities": list(self.required_capabilities),
            "missing_capabilities": list(self.missing_capabilities),
            "candidate_adapters": _serialize(self.candidate_adapters),
            "selected_adapter": _serialize(self.selected_adapter),
            "adapter_contract_status": self.adapter_contract_status,
            "adapter_contract_errors": list(self.adapter_contract_errors),
            "approval_required": self.approval_required,
            "preview_available": self.preview_available,
            "rollback_available": self.rollback_available,
            "max_claimable_outcome": self.max_claimable_outcome,
            "freshness_expectation": self.freshness_expectation,
            "unsupported_reason": _serialize(self.unsupported_reason),
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class ExecutionPlan:
    plan_type: str
    request_type: str
    response_mode: ResponseMode
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    family: str | None = None
    subject: str | None = None
    requires_reasoner: bool = False
    assistant_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_type": self.plan_type,
            "request_type": self.request_type,
            "response_mode": self.response_mode.value,
            "tool_name": self.tool_name,
            "tool_arguments": _serialize(self.tool_arguments),
            "family": self.family,
            "subject": self.subject,
            "requires_reasoner": self.requires_reasoner,
            "assistant_message": self.assistant_message,
        }
