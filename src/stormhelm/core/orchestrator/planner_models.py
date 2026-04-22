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
    DISCORD_RELAY_REQUEST = "discord_relay_request"
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
    WORKSPACE_RESULT = "workspace_result"
    SUMMARY_RESULT = "summary_result"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"
    FORECAST_SUMMARY = "forecast_summary"


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
