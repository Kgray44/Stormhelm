from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from time import monotonic
from uuid import uuid4

from stormhelm.config.models import CalculationsConfig
from stormhelm.core.calculations.helpers import CalculationHelperExecution
from stormhelm.core.calculations.helpers import CalculationHelperMatch
from stormhelm.core.calculations.helpers import get_cached_helper_registry
from stormhelm.core.calculations.explanations import compose_explanation_response
from stormhelm.core.calculations.explanations import render_direct_explanation
from stormhelm.core.calculations.explanations import render_helper_explanation
from stormhelm.core.calculations.explanations import render_verification_explanation
from stormhelm.core.calculations.evaluator import CalculationEvaluationError
from stormhelm.core.calculations.evaluator import evaluate_expression
from stormhelm.core.calculations.formatter import compose_success_response
from stormhelm.core.calculations.formatter import format_calculation_value
from stormhelm.core.calculations.models import CalculationFailure
from stormhelm.core.calculations.models import CalculationCallerContext
from stormhelm.core.calculations.models import CalculationFailureType
from stormhelm.core.calculations.models import CalculationInputOrigin
from stormhelm.core.calculations.models import CalculationOutputMode
from stormhelm.core.calculations.models import CalculationProvenance
from stormhelm.core.calculations.models import CalculationRequest
from stormhelm.core.calculations.models import CalculationResponse
from stormhelm.core.calculations.models import CalculationResultVisibility
from stormhelm.core.calculations.models import CalculationResult
from stormhelm.core.calculations.models import CalculationTrace
from stormhelm.core.calculations.models import CalculationVerification
from stormhelm.core.calculations.normalizer import CalculationNormalizationError
from stormhelm.core.calculations.normalizer import detect_expression_candidate
from stormhelm.core.calculations.normalizer import normalize_expression_text
from stormhelm.core.calculations.parser import CalculationParseError
from stormhelm.core.calculations.parser import parse_expression
from stormhelm.core.calculations.planner import CalculationsPlannerSeam
from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.subsystem_latency import classify_subsystem_hot_path


@dataclass(slots=True)
class CalculationsSubsystem:
    config: CalculationsConfig
    planner_seam: CalculationsPlannerSeam = field(init=False)
    helper_registry: object = field(init=False)
    _recent_traces: deque[CalculationTrace] = field(default_factory=lambda: deque(maxlen=24), init=False)

    def __post_init__(self) -> None:
        self.planner_seam = CalculationsPlannerSeam(self.config)
        self.helper_registry = get_cached_helper_registry()

    def status_snapshot(self) -> dict[str, object]:
        last_trace = self._recent_traces[-1].to_dict() if self._recent_traces else None
        return {
            "phase": "calc4",
            "enabled": self.config.enabled,
            "planner_routing_enabled": self.config.planner_routing_enabled,
            "debug_events_enabled": self.config.debug_events_enabled,
            "capabilities": {
                "direct_expression": True,
                "decimals": True,
                "scientific_notation": True,
                "exponentiation": True,
                "engineering_suffixes": True,
                "engineering_formatting": True,
                "formula_helpers": True,
                "explanation_modes": True,
                "verification_explanations": True,
                "shared_caller_seam": True,
                "cross_subsystem_reuse": True,
                "unit_reasoning": False,
            },
            "truthfulness_contract": {
                "deterministic_results_only": True,
                "guessing_disallowed": True,
                "provenance_required": True,
                "outside_scope_policy": "fail_honestly",
            },
            "runtime_hooks": {
                "extractor_ready": True,
                "normalizer_ready": True,
                "parser_ready": True,
                "evaluator_ready": True,
                "formatter_ready": True,
                "helper_registry_ready": True,
            },
            "recent_trace_count": len(self._recent_traces),
            "last_trace": last_trace,
        }

    def handle_request(
        self,
        *,
        session_id: str,
        operator_text: str,
        surface_mode: str,
        active_module: str,
        request: CalculationRequest | None = None,
    ) -> CalculationResponse:
        del session_id, active_module
        started_at = monotonic()
        normalized_text = normalize_phrase(operator_text)
        candidate = detect_expression_candidate(operator_text, normalized_text)
        effective_request = request or CalculationRequest(
            request_id=f"calc-{uuid4().hex[:8]}",
            source_surface=surface_mode,
            raw_input=operator_text,
            user_visible_text=operator_text,
            extracted_expression=candidate.extracted_expression,
            requested_mode=candidate.requested_mode,
        )
        helper_match = self._resolve_helper_request(
            operator_text=operator_text,
            normalized_text=normalized_text,
            request=effective_request,
        )
        if helper_match.candidate:
            if helper_match.helper_status == "matched" and helper_match.helper_name is not None:
                try:
                    execution = self.helper_registry.execute(helper_match.helper_name, helper_match.arguments)
                except (ArithmeticError, ValueError) as error:
                    failure_type = (
                        CalculationFailureType.DIVISION_BY_ZERO if "zero" in str(error).lower() else CalculationFailureType.EVALUATION_ERROR
                    )
                    return self._failure_response(
                        raw_input=operator_text,
                        extracted_expression=None,
                        normalized_expression=self._helper_normalized_expression(helper_match),
                        normalization_notes=[],
                        normalization_details=[],
                        failure=CalculationFailure(
                            failure_type=failure_type,
                            user_safe_message="Stormhelm could not evaluate that helper request locally in this pass.",
                            internal_reason=str(error),
                            suggested_recovery="Check the numeric values and units, then try again.",
                        ),
                        output_mode=CalculationOutputMode.FAILURE,
                        started_at=started_at,
                        route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_HELPER.value,
                        parse_success=False,
                        failure_stage="helper_evaluation",
                        helper_used=helper_match.helper_name,
                        helper_status=helper_match.helper_status,
                        helper_arguments=helper_match.arguments,
                        helper_missing_arguments=helper_match.missing_arguments,
                    )
                return self._helper_success_response(
                    operator_text=operator_text,
                    output_mode=effective_request.requested_mode,
                    helper_match=helper_match,
                    execution=execution,
                    started_at=started_at,
                    follow_up_reuse=effective_request.follow_up_reuse,
                )

            if helper_match.helper_status == "under_specified":
                missing = helper_match.missing_arguments[0] if helper_match.missing_arguments else "the missing values"
                return self._failure_response(
                    raw_input=operator_text,
                    extracted_expression=None,
                    normalized_expression=self._helper_normalized_expression(helper_match),
                    normalization_notes=[],
                    normalization_details=[],
                    failure=CalculationFailure(
                        failure_type=CalculationFailureType.HELPER_UNDER_SPECIFIED,
                        user_safe_message=helper_match.user_message or f"Stormhelm can calculate that, but it still needs {missing}.",
                        internal_reason=helper_match.internal_reason or "helper_request_under_specified",
                        suggested_recovery=helper_match.suggested_recovery or f"Add {missing} so Stormhelm can resolve the helper deterministically.",
                    ),
                    output_mode=CalculationOutputMode.FAILURE,
                    started_at=started_at,
                    route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_HELPER.value,
                    parse_success=False,
                    failure_stage="helper_match",
                    helper_used=helper_match.helper_name,
                    helper_status=helper_match.helper_status,
                    helper_arguments=helper_match.arguments,
                    helper_missing_arguments=helper_match.missing_arguments,
                )

            if helper_match.helper_status == "ambiguous":
                return self._failure_response(
                    raw_input=operator_text,
                    extracted_expression=None,
                    normalized_expression=self._helper_normalized_expression(helper_match),
                    normalization_notes=[],
                    normalization_details=[],
                    failure=CalculationFailure(
                        failure_type=CalculationFailureType.HELPER_AMBIGUOUS,
                        user_safe_message=helper_match.user_message
                        or "Stormhelm can't tell whether you want voltage, current, or resistance from that Ohm's law request yet.",
                        internal_reason=helper_match.internal_reason or "helper_request_ambiguous",
                        suggested_recovery=helper_match.suggested_recovery or "Specify which quantity you want solved.",
                    ),
                    output_mode=CalculationOutputMode.FAILURE,
                    started_at=started_at,
                    route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_HELPER.value,
                    parse_success=False,
                    failure_stage="helper_match",
                    helper_used=helper_match.helper_name,
                    helper_status=helper_match.helper_status,
                    helper_arguments=helper_match.arguments,
                    helper_missing_arguments=helper_match.missing_arguments,
                )

            if helper_match.helper_status == "invalid":
                return self._failure_response(
                    raw_input=operator_text,
                    extracted_expression=None,
                    normalized_expression=self._helper_normalized_expression(helper_match),
                    normalization_notes=[],
                    normalization_details=[],
                    failure=CalculationFailure(
                        failure_type=helper_match.failure_type or CalculationFailureType.NORMALIZATION_ERROR,
                        user_safe_message=helper_match.user_message or "Stormhelm could not normalize that helper request cleanly.",
                        internal_reason=helper_match.internal_reason or "helper_request_invalid",
                        suggested_recovery=helper_match.suggested_recovery or "Check the helper inputs and try again.",
                    ),
                    output_mode=CalculationOutputMode.FAILURE,
                    started_at=started_at,
                    route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_HELPER.value,
                    parse_success=False,
                    failure_stage="helper_match",
                    helper_used=helper_match.helper_name,
                    helper_status=helper_match.helper_status,
                    helper_arguments=helper_match.arguments,
                    helper_missing_arguments=helper_match.missing_arguments,
                )

        extracted_expression = effective_request.extracted_expression
        output_mode = effective_request.requested_mode

        if not extracted_expression:
            return self._failure_response(
                raw_input=operator_text,
                extracted_expression=None,
                normalized_expression=None,
                normalization_notes=[],
                normalization_details=[],
                failure=CalculationFailure(
                    failure_type=CalculationFailureType.EXTRACTION_FAILED,
                    user_safe_message="Stormhelm could not isolate a direct math expression from that request yet.",
                    internal_reason="no_expression_extracted",
                    suggested_recovery="Send the math as a plain numeric expression such as 2+2 or (48/3)+7^2.",
                ),
                output_mode=CalculationOutputMode.FAILURE,
                started_at=started_at,
                route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_EXPRESSION.value,
                parse_success=False,
                failure_stage="routing",
            )

        try:
            normalized = normalize_expression_text(extracted_expression)
        except CalculationNormalizationError as error:
            return self._failure_response(
                raw_input=operator_text,
                extracted_expression=extracted_expression,
                normalized_expression=None,
                normalization_notes=[],
                normalization_details=[],
                failure=CalculationFailure(
                    failure_type=error.failure_type,
                    user_safe_message=error.user_message,
                    internal_reason=str(error),
                    parse_location=error.position,
                    suggested_recovery=error.recovery_hint,
                ),
                output_mode=CalculationOutputMode.FAILURE,
                started_at=started_at,
                route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_EXPRESSION.value,
                parse_success=False,
                failure_stage="normalization",
            )

        if not normalized.parseable_boolean:
            return self._failure_response(
                raw_input=operator_text,
                extracted_expression=extracted_expression,
                normalized_expression=normalized.normalized_expression,
                normalization_notes=normalized.normalization_notes,
                normalization_details=normalized.normalization_details,
                failure=CalculationFailure(
                    failure_type=CalculationFailureType.NORMALIZATION_ERROR,
                    user_safe_message="Stormhelm could not normalize that expression into a supported local calculation yet.",
                    internal_reason="normalized_expression_not_parseable",
                    suggested_recovery="Use direct arithmetic with digits, parentheses, operators, and supported suffixes like k, M, m, u, n, or p.",
                ),
                output_mode=CalculationOutputMode.FAILURE,
                started_at=started_at,
                route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_EXPRESSION.value,
                parse_success=False,
                failure_stage="normalization",
            )

        try:
            syntax_tree = parse_expression(normalized.normalized_expression)
        except CalculationParseError as error:
            return self._failure_response(
                raw_input=operator_text,
                extracted_expression=extracted_expression,
                normalized_expression=normalized.normalized_expression,
                normalization_notes=normalized.normalization_notes,
                normalization_details=normalized.normalization_details,
                failure=CalculationFailure(
                    failure_type=CalculationFailureType.PARSE_ERROR,
                    user_safe_message="Stormhelm could not parse that expression cleanly. Send it as plain math with parentheses if needed.",
                    internal_reason=str(error),
                    parse_location=error.position,
                    suggested_recovery="Use expressions such as 12/4+6 or (48/3)+7^2.",
                ),
                output_mode=CalculationOutputMode.FAILURE,
                started_at=started_at,
                route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_EXPRESSION.value,
                parse_success=False,
                failure_stage="parse",
            )

        try:
            numeric_value = evaluate_expression(syntax_tree)
        except CalculationEvaluationError as error:
            failure_type = (
                CalculationFailureType.DIVISION_BY_ZERO if "zero" in str(error).lower() else CalculationFailureType.EVALUATION_ERROR
            )
            return self._failure_response(
                raw_input=operator_text,
                extracted_expression=extracted_expression,
                normalized_expression=normalized.normalized_expression,
                normalization_notes=normalized.normalization_notes,
                normalization_details=normalized.normalization_details,
                failure=CalculationFailure(
                    failure_type=failure_type,
                    user_safe_message="Stormhelm could not evaluate that expression locally in this pass.",
                    internal_reason=str(error),
                    suggested_recovery="Keep the expression to direct arithmetic with numeric values only.",
                ),
                output_mode=CalculationOutputMode.FAILURE,
                started_at=started_at,
                route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_EXPRESSION.value,
                parse_success=True,
                failure_stage="evaluation",
            )

        formatted = format_calculation_value(
            numeric_value,
            prefer_engineering=normalized.display_preference == "engineering",
        )
        warnings = list(normalized.normalization_notes)
        if formatted.approximate:
            warnings.append("display rounded for readability")
        explanation = None
        verification = None
        provenance = CalculationProvenance.DETERMINISTIC_LOCAL_EXPRESSION
        default_response = compose_success_response(
            normalized_expression=normalized.normalized_expression,
            formatted_value=formatted.text,
            output_mode=output_mode,
            approximate=formatted.approximate,
        )
        if effective_request.verification_claim:
            try:
                verification = self._build_verification_claim(
                    normalized_expression=normalized.normalized_expression,
                    numeric_value=numeric_value,
                    formatted_value=formatted.text,
                    verification_claim=effective_request.verification_claim,
                )
            except (CalculationNormalizationError, CalculationParseError, CalculationEvaluationError) as error:
                failure = error
                if not isinstance(error, CalculationNormalizationError):
                    failure = CalculationNormalizationError(
                        "Verification claim could not be evaluated cleanly.",
                        failure_type=CalculationFailureType.NORMALIZATION_ERROR,
                        user_message="Stormhelm could not evaluate the claimed comparison value cleanly.",
                        recovery_hint="Use a single numeric claim such as 28, 159.155, or 1.2e-3.",
                    )
                return self._failure_response(
                    raw_input=operator_text,
                    extracted_expression=extracted_expression,
                    normalized_expression=normalized.normalized_expression,
                    normalization_notes=normalized.normalization_notes,
                    normalization_details=normalized.normalization_details,
                    failure=CalculationFailure(
                        failure_type=failure.failure_type,
                        user_safe_message=failure.user_message,
                        internal_reason=str(failure),
                        suggested_recovery=failure.recovery_hint,
                    ),
                    output_mode=output_mode,
                    started_at=started_at,
                    route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_VERIFICATION.value,
                    parse_success=True,
                    failure_stage="verification",
                    follow_up_reuse=effective_request.follow_up_reuse,
                    verification_claim=effective_request.verification_claim,
                )
            explanation = render_verification_explanation(
                normalized_expression=normalized.normalized_expression,
                formatted_actual_value=formatted.text,
                claim_text=effective_request.verification_claim,
                matches=verification.matches,
                follow_up_reuse=effective_request.follow_up_reuse,
            )
            assistant_response = compose_explanation_response(explanation, default_response=default_response)
            provenance = CalculationProvenance.DETERMINISTIC_LOCAL_VERIFICATION
        else:
            if output_mode == CalculationOutputMode.ANSWER_ONLY:
                assistant_response = default_response
            else:
                explanation = render_direct_explanation(
                    requested_mode=output_mode,
                    normalized_expression=normalized.normalized_expression,
                    syntax_tree=syntax_tree,
                    formatted_value=formatted.text,
                    approximate=formatted.approximate,
                    normalization_details=normalized.normalization_details,
                    follow_up_reuse=effective_request.follow_up_reuse,
                )
                assistant_response = compose_explanation_response(explanation, default_response=default_response)
        result = CalculationResult(
            status="succeeded",
            numeric_value=numeric_value,
            formatted_value=formatted.text,
            expression=extracted_expression,
            normalized_expression=normalized.normalized_expression,
            provenance=provenance,
            warnings=warnings,
            display_mode=formatted.mode,
            display_is_approximate=formatted.approximate,
            explanation=explanation,
            verification=verification,
        )
        trace = CalculationTrace(
            raw_input=operator_text,
            extracted_expression=extracted_expression,
            normalized_expression=normalized.normalized_expression,
            route_selected=provenance.value,
            parse_success=True,
            result=formatted.text,
            output_mode=output_mode.value,
            latency_ms=(monotonic() - started_at) * 1000.0,
            provenance=provenance.value,
            normalization_notes=normalized.normalization_notes,
            normalization_details=normalized.normalization_details,
            raw_numeric_result=str(numeric_value),
            display_format=formatted.mode,
            display_is_approximate=formatted.approximate,
            engineering_display_applied=formatted.engineering_applied,
            explanation_mode_requested=output_mode.value,
            explanation_mode_used=explanation.mode.value if explanation is not None else CalculationOutputMode.ANSWER_ONLY.value,
            explanation_source_type="verification" if verification is not None else "direct_expression" if explanation is not None else "lazy_skipped",
            explanation_follow_up_reuse=effective_request.follow_up_reuse,
            explanation_steps=list(explanation.steps) if explanation is not None else [],
            explanation_formula=explanation.formula if explanation is not None else None,
            rounding_note_present=explanation.rounding_note is not None if explanation is not None else formatted.approximate,
            verification_claim=effective_request.verification_claim,
            verification_match=verification.matches if verification is not None else None,
            **self._l8_trace_kwargs(operation="direct_expression"),
        )
        self._remember_trace(trace)
        response_contract = {
            "bearing_title": "Calculation",
            "micro_response": assistant_response,
            "full_response": assistant_response,
        }
        return CalculationResponse(
            assistant_response=assistant_response,
            response_contract=response_contract,
            trace=trace,
            result=result,
        )

    def execute(
        self,
        *,
        session_id: str,
        active_module: str,
        request: CalculationRequest,
    ) -> CalculationResponse:
        caller = self._effective_caller_context(
            request,
            default_surface=request.source_surface,
        )
        response = self.handle_request(
            session_id=session_id,
            operator_text=request.raw_input,
            surface_mode=request.source_surface,
            active_module=active_module,
            request=request,
        )
        provenance_value = (
            response.result.provenance
            if response.result is not None
            else CalculationProvenance(str(response.trace.provenance or response.trace.route_selected))
            if str(response.trace.provenance or response.trace.route_selected)
            in {
                CalculationProvenance.DETERMINISTIC_LOCAL_EXPRESSION.value,
                CalculationProvenance.DETERMINISTIC_LOCAL_HELPER.value,
                CalculationProvenance.DETERMINISTIC_LOCAL_VERIFICATION.value,
            }
            else None
        )
        provenance_stack = self._provenance_stack(caller, provenance_value)
        self._apply_caller_context(response=response, caller=caller, provenance_stack=provenance_stack)
        return response

    def _default_caller_context(
        self,
        *,
        surface_mode: str,
        input_origin: CalculationInputOrigin,
    ) -> CalculationCallerContext:
        provenance_stack = [surface_mode, input_origin.value]
        return CalculationCallerContext(
            subsystem="assistant",
            caller_intent="direct_request",
            input_origin=input_origin,
            visual_extraction_dependency=input_origin != CalculationInputOrigin.USER_TEXT,
            internal_validation=False,
            result_visibility=CalculationResultVisibility.USER_FACING,
            reuse_path="calculations.handle_request",
            provenance_stack=provenance_stack,
        )

    def _effective_caller_context(
        self,
        request: CalculationRequest,
        *,
        default_surface: str,
    ) -> CalculationCallerContext:
        if request.caller is not None:
            return request.caller
        return self._default_caller_context(
            surface_mode=default_surface,
            input_origin=CalculationInputOrigin.USER_TEXT,
        )

    def _provenance_stack(
        self,
        caller: CalculationCallerContext,
        provenance: CalculationProvenance | None,
    ) -> list[str]:
        stack = list(caller.provenance_stack)
        if provenance is not None:
            stack.append(provenance.value)
        return stack

    def _apply_caller_context(
        self,
        *,
        response: CalculationResponse,
        caller: CalculationCallerContext,
        provenance_stack: list[str],
    ) -> None:
        response.trace.caller_subsystem = caller.subsystem
        response.trace.caller_intent = caller.caller_intent
        response.trace.input_origin = caller.input_origin.value
        response.trace.visual_extraction_dependency = caller.visual_extraction_dependency
        response.trace.internal_validation = caller.internal_validation
        response.trace.result_visibility = caller.result_visibility.value
        response.trace.caller_reuse_path = caller.reuse_path
        response.trace.provenance_stack = list(provenance_stack)
        response.trace.evidence_confidence = caller.evidence_confidence
        response.trace.evidence_confidence_note = caller.evidence_confidence_note
        if response.result is not None:
            response.result.provenance_stack = list(provenance_stack)

    def _failure_response(
        self,
        *,
        raw_input: str,
        extracted_expression: str | None,
        normalized_expression: str | None,
        normalization_notes: list[str],
        normalization_details: list,
        failure: CalculationFailure,
        output_mode: CalculationOutputMode,
        started_at: float,
        route_selected: str,
        parse_success: bool,
        failure_stage: str,
        helper_used: str | None = None,
        helper_status: str | None = None,
        helper_arguments: dict[str, object] | None = None,
        helper_missing_arguments: list[str] | None = None,
        follow_up_reuse: bool = False,
        verification_claim: str | None = None,
    ) -> CalculationResponse:
        trace = CalculationTrace(
            raw_input=raw_input,
            extracted_expression=extracted_expression,
            normalized_expression=normalized_expression,
            route_selected=route_selected,
            parse_success=parse_success,
            result=None,
            output_mode=output_mode.value,
            latency_ms=(monotonic() - started_at) * 1000.0,
            failure_type=failure.failure_type.value,
            failure_stage=failure_stage,
            normalization_notes=normalization_notes,
            normalization_details=normalization_details,
            provenance=route_selected,
            helper_used=helper_used,
            helper_status=helper_status,
            helper_arguments=dict(helper_arguments or {}),
            helper_missing_arguments=list(helper_missing_arguments or []),
            explanation_mode_requested=output_mode.value,
            explanation_mode_used=CalculationOutputMode.FAILURE.value,
            explanation_follow_up_reuse=follow_up_reuse,
            verification_claim=verification_claim,
            **self._l8_trace_kwargs(operation="failure"),
        )
        self._remember_trace(trace)
        response_contract = {
            "bearing_title": "Calculation Issue",
            "micro_response": failure.user_safe_message,
            "full_response": failure.user_safe_message,
        }
        return CalculationResponse(
            assistant_response=failure.user_safe_message,
            response_contract=response_contract,
            trace=trace,
            failure=failure,
        )

    def _remember_trace(self, trace: CalculationTrace) -> None:
        self._recent_traces.append(trace)

    def _l8_trace_kwargs(self, *, operation: str) -> dict[str, object]:
        decision = classify_subsystem_hot_path(
            subsystem_id="calculations",
            route_family="calculations",
            operation=operation,
            metadata={"cache_hit": True, "fast_path_used": True},
        )
        return {
            "hot_path_name": decision.hot_path_name,
            "latency_mode": decision.latency_mode.value,
            "cache_policy_id": decision.cache_policy_id,
            "cache_hit": decision.cache_hit,
            "provider_fallback_used": decision.provider_fallback_used,
            "heavy_context_used": decision.heavy_context_used,
        }

    def _resolve_helper_request(
        self,
        *,
        operator_text: str,
        normalized_text: str,
        request: CalculationRequest,
    ) -> CalculationHelperMatch:
        matched = self.helper_registry.match_request(raw_text=operator_text, normalized_text=normalized_text)
        if not request.helper_name:
            return matched
        helper_status = request.missing_arguments and "under_specified" or matched.helper_status or "matched"
        if request.helper_name == "ohms_law_family" and not request.arguments:
            helper_status = "ambiguous"
        return CalculationHelperMatch(
            candidate=True,
            helper_name=request.helper_name,
            helper_status=helper_status,
            arguments=dict(request.arguments or matched.arguments),
            missing_arguments=list(request.missing_arguments or matched.missing_arguments),
            reasons=["reused planner helper request"] + list(matched.reasons),
            route_confidence=1.0 if request.arguments or request.missing_arguments else matched.route_confidence,
        )

    def _helper_success_response(
        self,
        *,
        operator_text: str,
        output_mode: CalculationOutputMode,
        helper_match: CalculationHelperMatch,
        execution: CalculationHelperExecution,
        started_at: float,
        follow_up_reuse: bool,
    ) -> CalculationResponse:
        explanation = render_helper_explanation(
            requested_mode=output_mode,
            helper_label=execution.helper_name,
            formatted_value=execution.formatted_value,
            approximate=execution.approximate,
            formula_symbolic=execution.formula_symbolic,
            substitution_rows=execution.substitution_rows,
            follow_up_reuse=follow_up_reuse,
        )
        assistant_response = compose_explanation_response(explanation, default_response=execution.assistant_response)
        result = CalculationResult(
            status="succeeded",
            numeric_value=execution.numeric_value,
            formatted_value=execution.formatted_value,
            expression=operator_text,
            normalized_expression=execution.normalized_expression,
            provenance=CalculationProvenance.DETERMINISTIC_LOCAL_HELPER,
            warnings=[],
            display_mode=execution.display_mode,
            display_is_approximate=execution.approximate,
            helper_used=helper_match.helper_name,
            explanation=explanation,
        )
        trace = CalculationTrace(
            raw_input=operator_text,
            extracted_expression=None,
            normalized_expression=execution.normalized_expression,
            route_selected=CalculationProvenance.DETERMINISTIC_LOCAL_HELPER.value,
            parse_success=True,
            result=execution.formatted_value,
            output_mode=output_mode.value,
            latency_ms=(monotonic() - started_at) * 1000.0,
            provenance=CalculationProvenance.DETERMINISTIC_LOCAL_HELPER.value,
            raw_numeric_result=str(execution.numeric_value),
            display_format=execution.display_mode,
            display_is_approximate=execution.approximate,
            engineering_display_applied=execution.engineering_applied,
            helper_used=helper_match.helper_name,
            helper_status=helper_match.helper_status,
            helper_arguments=helper_match.arguments,
            helper_missing_arguments=helper_match.missing_arguments,
            explanation_mode_requested=output_mode.value,
            explanation_mode_used=explanation.mode.value if explanation is not None else CalculationOutputMode.ANSWER_ONLY.value,
            explanation_source_type="helper",
            explanation_follow_up_reuse=follow_up_reuse,
            explanation_steps=list(explanation.steps) if explanation is not None else [],
            explanation_formula=explanation.formula if explanation is not None else execution.formula_symbolic,
            rounding_note_present=explanation.rounding_note is not None if explanation is not None else execution.approximate,
            **self._l8_trace_kwargs(operation="helper"),
        )
        self._remember_trace(trace)
        response_contract = {
            "bearing_title": "Calculation",
            "micro_response": explanation.summary if explanation is not None else assistant_response,
            "full_response": assistant_response,
        }
        return CalculationResponse(
            assistant_response=assistant_response,
            response_contract=response_contract,
            trace=trace,
            result=result,
        )

    def _helper_normalized_expression(self, helper_match: CalculationHelperMatch) -> str | None:
        if helper_match.helper_name is None:
            return None
        if helper_match.helper_status == "matched":
            try:
                execution = self.helper_registry.execute(helper_match.helper_name, helper_match.arguments)
                return execution.normalized_expression
            except (ArithmeticError, ValueError):
                return helper_match.helper_name
        return helper_match.helper_name

    def _build_verification_claim(
        self,
        *,
        normalized_expression: str,
        numeric_value: Decimal,
        formatted_value: str,
        verification_claim: str,
    ) -> CalculationVerification:
        del normalized_expression
        normalized_claim = normalize_expression_text(verification_claim)
        if not normalized_claim.parseable_boolean:
            raise CalculationNormalizationError(
                "Verification claim could not be normalized cleanly.",
                failure_type=CalculationFailureType.NORMALIZATION_ERROR,
                user_message="Stormhelm could not normalize the claimed comparison value cleanly.",
                recovery_hint="Use a single numeric claim such as 28, 159.155, or 1.2e-3.",
            )
        claim_tree = parse_expression(normalized_claim.normalized_expression)
        claim_value = evaluate_expression(claim_tree)
        matches = claim_value == numeric_value
        relation = "matches" if matches else "does not match"
        return CalculationVerification(
            claim_text=verification_claim,
            actual_value=numeric_value,
            matches=matches,
            summary=f"{formatted_value} {relation} {verification_claim}.",
        )


def build_calculations_subsystem(config: CalculationsConfig) -> CalculationsSubsystem:
    return CalculationsSubsystem(config=config)
