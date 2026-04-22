from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class CalculationRouteDisposition(StrEnum):
    NOT_REQUESTED = "not_requested"
    FEATURE_DISABLED = "feature_disabled"
    ROUTING_DISABLED = "routing_disabled"
    DIRECT_EXPRESSION = "direct_expression"
    HELPER_REQUEST = "helper_request"
    VERIFICATION_REQUEST = "verification_request"


class CalculationOutputMode(StrEnum):
    ANSWER_ONLY = "answer_only"
    SHORT_EXPRESSION = "short_expression"
    SHORT_BREAKDOWN = "short_breakdown"
    FORMULA_SUBSTITUTION = "formula_substitution"
    STEP_BY_STEP = "step_by_step"
    VERIFICATION_EXPLANATION = "verification_explanation"
    FAILURE = "failure"


class CalculationFailureType(StrEnum):
    EXTRACTION_FAILED = "extraction_failed"
    NORMALIZATION_ERROR = "normalization_error"
    OUT_OF_SCOPE = "out_of_scope"
    PARSE_ERROR = "parse_error"
    DIVISION_BY_ZERO = "division_by_zero"
    EVALUATION_ERROR = "evaluation_error"
    HELPER_UNDER_SPECIFIED = "helper_under_specified"
    HELPER_AMBIGUOUS = "helper_ambiguous"


class CalculationProvenance(StrEnum):
    DETERMINISTIC_LOCAL_EXPRESSION = "deterministic_local_expression"
    DETERMINISTIC_LOCAL_HELPER = "deterministic_local_helper"
    DETERMINISTIC_LOCAL_VERIFICATION = "deterministic_local_verification"


class CalculationInputOrigin(StrEnum):
    USER_TEXT = "user_text"
    SCREEN_SELECTION = "screen_selection"
    SCREEN_CLIPBOARD = "screen_clipboard"
    SCREEN_VISIBLE_TEXT = "screen_visible_text"
    REUSED_CONTEXT = "reused_context"
    INTERNAL_PREPARED_EXPRESSION = "internal_prepared_expression"


class CalculationResultVisibility(StrEnum):
    USER_FACING = "user_facing"
    SILENT_INTERNAL = "silent_internal"


@dataclass(slots=True)
class CalculationCallerContext:
    subsystem: str = "assistant"
    caller_intent: str = "direct_request"
    input_origin: CalculationInputOrigin = CalculationInputOrigin.USER_TEXT
    visual_extraction_dependency: bool = False
    internal_validation: bool = False
    result_visibility: CalculationResultVisibility = CalculationResultVisibility.USER_FACING
    reuse_path: str | None = None
    provenance_stack: list[str] = field(default_factory=list)
    evidence_confidence: float | None = None
    evidence_confidence_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "caller_intent": self.caller_intent,
            "input_origin": self.input_origin.value,
            "visual_extraction_dependency": self.visual_extraction_dependency,
            "internal_validation": self.internal_validation,
            "result_visibility": self.result_visibility.value,
            "reuse_path": self.reuse_path,
            "provenance_stack": list(self.provenance_stack),
            "evidence_confidence": self.evidence_confidence,
            "evidence_confidence_note": self.evidence_confidence_note,
        }


@dataclass(slots=True)
class CalculationPlannerEvaluation:
    candidate: bool
    disposition: CalculationRouteDisposition
    extracted_expression: str | None = None
    requested_mode: CalculationOutputMode = CalculationOutputMode.ANSWER_ONLY
    helper_name: str | None = None
    helper_status: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    missing_arguments: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    feature_enabled: bool = False
    planner_routing_enabled: bool = False
    route_confidence: float = 0.0
    follow_up_reuse: bool = False
    verification_claim: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "disposition": self.disposition.value,
            "extracted_expression": self.extracted_expression,
            "requested_mode": self.requested_mode.value,
            "helper_name": self.helper_name,
            "helper_status": self.helper_status,
            "arguments": _serialize(self.arguments),
            "missing_arguments": list(self.missing_arguments),
            "reasons": list(self.reasons),
            "feature_enabled": self.feature_enabled,
            "planner_routing_enabled": self.planner_routing_enabled,
            "route_confidence": self.route_confidence,
            "follow_up_reuse": self.follow_up_reuse,
            "verification_claim": self.verification_claim,
        }


@dataclass(slots=True)
class CalculationRequest:
    request_id: str
    source_surface: str
    raw_input: str
    user_visible_text: str
    extracted_expression: str | None = None
    requested_mode: CalculationOutputMode = CalculationOutputMode.ANSWER_ONLY
    helper_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    missing_arguments: list[str] = field(default_factory=list)
    follow_up_reuse: bool = False
    verification_claim: str | None = None
    caller: CalculationCallerContext | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "source_surface": self.source_surface,
            "raw_input": self.raw_input,
            "user_visible_text": self.user_visible_text,
            "extracted_expression": self.extracted_expression,
            "requested_mode": self.requested_mode.value,
            "helper_name": self.helper_name,
            "arguments": _serialize(self.arguments),
            "missing_arguments": list(self.missing_arguments),
            "follow_up_reuse": self.follow_up_reuse,
            "verification_claim": self.verification_claim,
            "caller": _serialize(self.caller),
        }


@dataclass(slots=True)
class CalculationNormalizationDetail:
    raw_token: str
    normalized_token: str
    token_kind: str
    start_index: int
    end_index: int
    engineering_suffix: str | None = None
    unit_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_token": self.raw_token,
            "normalized_token": self.normalized_token,
            "token_kind": self.token_kind,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "engineering_suffix": self.engineering_suffix,
            "unit_label": self.unit_label,
        }


@dataclass(slots=True)
class NormalizedCalculation:
    normalized_expression: str
    normalization_notes: list[str] = field(default_factory=list)
    normalization_details: list[CalculationNormalizationDetail] = field(default_factory=list)
    parseable_boolean: bool = False
    display_preference: str = "decimal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "normalized_expression": self.normalized_expression,
            "normalization_notes": list(self.normalization_notes),
            "normalization_details": _serialize(self.normalization_details),
            "parseable_boolean": self.parseable_boolean,
            "display_preference": self.display_preference,
        }


@dataclass(slots=True)
class CalculationExplanation:
    mode: CalculationOutputMode
    source_type: str
    summary: str
    steps: list[str] = field(default_factory=list)
    formula: str | None = None
    substitution_rows: list[str] = field(default_factory=list)
    verification_summary: str | None = None
    rounding_note: str | None = None
    reused_prior_result: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "source_type": self.source_type,
            "summary": self.summary,
            "steps": list(self.steps),
            "formula": self.formula,
            "substitution_rows": list(self.substitution_rows),
            "verification_summary": self.verification_summary,
            "rounding_note": self.rounding_note,
            "reused_prior_result": self.reused_prior_result,
        }


@dataclass(slots=True)
class CalculationVerification:
    claim_text: str
    actual_value: Decimal
    matches: bool
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_text": self.claim_text,
            "actual_value": str(self.actual_value),
            "matches": self.matches,
            "summary": self.summary,
        }


@dataclass(slots=True)
class CalculationResult:
    status: str
    numeric_value: Decimal
    formatted_value: str
    expression: str
    normalized_expression: str
    provenance: CalculationProvenance
    warnings: list[str] = field(default_factory=list)
    display_mode: str = "decimal"
    display_is_approximate: bool = False
    helper_used: str | None = None
    explanation: CalculationExplanation | None = None
    verification: CalculationVerification | None = None
    provenance_stack: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "numeric_value": str(self.numeric_value),
            "formatted_value": self.formatted_value,
            "expression": self.expression,
            "normalized_expression": self.normalized_expression,
            "provenance": self.provenance.value,
            "warnings": list(self.warnings),
            "display_mode": self.display_mode,
            "display_is_approximate": self.display_is_approximate,
            "helper_used": self.helper_used,
            "explanation": _serialize(self.explanation),
            "verification": _serialize(self.verification),
            "provenance_stack": list(self.provenance_stack),
        }


@dataclass(slots=True)
class CalculationFailure:
    failure_type: CalculationFailureType
    user_safe_message: str
    internal_reason: str
    parse_location: int | None = None
    suggested_recovery: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_type": self.failure_type.value,
            "user_safe_message": self.user_safe_message,
            "internal_reason": self.internal_reason,
            "parse_location": self.parse_location,
            "suggested_recovery": self.suggested_recovery,
        }


@dataclass(slots=True)
class CalculationTrace:
    raw_input: str
    extracted_expression: str | None
    normalized_expression: str | None
    route_selected: str
    parse_success: bool
    result: str | None
    output_mode: str
    latency_ms: float
    failure_type: str | None = None
    failure_stage: str | None = None
    provenance: str | None = None
    normalization_notes: list[str] = field(default_factory=list)
    normalization_details: list[CalculationNormalizationDetail] = field(default_factory=list)
    raw_numeric_result: str | None = None
    display_format: str | None = None
    display_is_approximate: bool = False
    engineering_display_applied: bool = False
    helper_used: str | None = None
    helper_status: str | None = None
    helper_arguments: dict[str, Any] = field(default_factory=dict)
    helper_missing_arguments: list[str] = field(default_factory=list)
    explanation_mode_requested: str | None = None
    explanation_mode_used: str | None = None
    explanation_source_type: str | None = None
    explanation_follow_up_reuse: bool = False
    explanation_steps: list[str] = field(default_factory=list)
    explanation_formula: str | None = None
    rounding_note_present: bool = False
    verification_claim: str | None = None
    verification_match: bool | None = None
    caller_subsystem: str | None = None
    caller_intent: str | None = None
    input_origin: str | None = None
    visual_extraction_dependency: bool = False
    internal_validation: bool = False
    result_visibility: str | None = None
    caller_reuse_path: str | None = None
    provenance_stack: list[str] = field(default_factory=list)
    evidence_confidence: float | None = None
    evidence_confidence_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_input": self.raw_input,
            "extracted_expression": self.extracted_expression,
            "normalized_expression": self.normalized_expression,
            "route_selected": self.route_selected,
            "parse_success": self.parse_success,
            "result": self.result,
            "output_mode": self.output_mode,
            "latency_ms": self.latency_ms,
            "failure_type": self.failure_type,
            "failure_stage": self.failure_stage,
            "provenance": self.provenance,
            "normalization_notes": list(self.normalization_notes),
            "normalization_details": _serialize(self.normalization_details),
            "raw_numeric_result": self.raw_numeric_result,
            "display_format": self.display_format,
            "display_is_approximate": self.display_is_approximate,
            "engineering_display_applied": self.engineering_display_applied,
            "helper_used": self.helper_used,
            "helper_status": self.helper_status,
            "helper_arguments": _serialize(self.helper_arguments),
            "helper_missing_arguments": list(self.helper_missing_arguments),
            "explanation_mode_requested": self.explanation_mode_requested,
            "explanation_mode_used": self.explanation_mode_used,
            "explanation_source_type": self.explanation_source_type,
            "explanation_follow_up_reuse": self.explanation_follow_up_reuse,
            "explanation_steps": list(self.explanation_steps),
            "explanation_formula": self.explanation_formula,
            "rounding_note_present": self.rounding_note_present,
            "verification_claim": self.verification_claim,
            "verification_match": self.verification_match,
            "caller_subsystem": self.caller_subsystem,
            "caller_intent": self.caller_intent,
            "input_origin": self.input_origin,
            "visual_extraction_dependency": self.visual_extraction_dependency,
            "internal_validation": self.internal_validation,
            "result_visibility": self.result_visibility,
            "caller_reuse_path": self.caller_reuse_path,
            "provenance_stack": list(self.provenance_stack),
            "evidence_confidence": self.evidence_confidence,
            "evidence_confidence_note": self.evidence_confidence_note,
        }


@dataclass(slots=True)
class CalculationResponse:
    assistant_response: str
    response_contract: dict[str, str]
    trace: CalculationTrace
    result: CalculationResult | None = None
    failure: CalculationFailure | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "assistant_response": self.assistant_response,
            "response_contract": dict(self.response_contract),
            "trace": self.trace.to_dict(),
            "result": self.result.to_dict() if self.result is not None else None,
            "failure": self.failure.to_dict() if self.failure is not None else None,
        }
