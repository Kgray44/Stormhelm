from __future__ import annotations

import re

from stormhelm.config.models import CalculationsConfig
from stormhelm.core.calculations.helpers import get_cached_helper_registry
from stormhelm.core.calculations.models import CalculationOutputMode
from stormhelm.core.calculations.models import CalculationPlannerEvaluation
from stormhelm.core.calculations.models import CalculationRouteDisposition
from stormhelm.core.calculations.normalizer import detect_expression_candidate
from stormhelm.core.calculations.normalizer import detect_requested_output_mode


VERIFICATION_REQUEST_PATTERN = re.compile(
    r"^\s*(?:verify|check)\s+(?P<expr>.+?)\s*(?:=|equals?|equal to)\s+(?P<claim>.+?)\s*[?.!]*\s*$",
    re.IGNORECASE,
)
EXPLANATION_FOLLOW_UP_PHRASES = (
    "show the steps",
    "show me the steps",
    "how did you get that",
    "walk me through it",
    "walk me through that",
    "show the formula",
    "show the formula substitution",
    "show your work",
    "why is that the answer",
    "show me the arithmetic",
    "show the arithmetic",
    "walk through that calculation",
)
CONTINUITY_FOLLOW_UP_PHRASES = (
    "same calculation",
    "same thing",
    "as before",
    "that result",
    "this result",
    "that preview",
    "other one",
    "use this",
    "use that",
    "what about if",
    "numerator",
    "denominator",
    "multiply that",
    "same setup",
    "that answer",
    "redo it",
    "go ahead",
    "continue",
)


class CalculationsPlannerSeam:
    def __init__(self, config: CalculationsConfig) -> None:
        self.config = config
        self._helpers = get_cached_helper_registry()

    def evaluate(
        self,
        *,
        raw_text: str,
        normalized_text: str,
        surface_mode: str,
        active_module: str,
        active_context: dict[str, object] | None = None,
    ) -> CalculationPlannerEvaluation:
        del surface_mode, active_module
        if _unsupported_browser_automation_text(normalized_text):
            return CalculationPlannerEvaluation(
                candidate=False,
                disposition=CalculationRouteDisposition.NOT_REQUESTED,
                reasons=["unsupported_browser_automation_signal"],
                feature_enabled=self.config.enabled,
                planner_routing_enabled=self.config.planner_routing_enabled,
            )
        candidate = detect_expression_candidate(raw_text, normalized_text)
        requested_mode = detect_requested_output_mode(raw_text, normalized_text)
        if requested_mode == CalculationOutputMode.ANSWER_ONLY:
            requested_mode = candidate.requested_mode
        verification_match = VERIFICATION_REQUEST_PATTERN.match(raw_text)
        if verification_match:
            expression = str(verification_match.group("expr") or "").strip()
            claim = str(verification_match.group("claim") or "").strip()
            if expression:
                disposition = (
                    CalculationRouteDisposition.FEATURE_DISABLED
                    if not self.config.enabled
                    else CalculationRouteDisposition.ROUTING_DISABLED
                    if not self.config.planner_routing_enabled
                    else CalculationRouteDisposition.VERIFICATION_REQUEST
                )
                return CalculationPlannerEvaluation(
                    candidate=True,
                    disposition=disposition,
                    extracted_expression=expression,
                    requested_mode=CalculationOutputMode.VERIFICATION_EXPLANATION,
                    reasons=["verification request matched"],
                    feature_enabled=self.config.enabled,
                    planner_routing_enabled=self.config.planner_routing_enabled,
                    route_confidence=0.96,
                    verification_claim=claim,
                )
        if candidate.candidate:
            if not self.config.enabled:
                return CalculationPlannerEvaluation(
                    candidate=True,
                    disposition=CalculationRouteDisposition.FEATURE_DISABLED,
                    extracted_expression=candidate.extracted_expression,
                    requested_mode=requested_mode if requested_mode != CalculationOutputMode.ANSWER_ONLY else candidate.requested_mode,
                    reasons=list(candidate.reasons),
                    feature_enabled=False,
                    planner_routing_enabled=self.config.planner_routing_enabled,
                    route_confidence=candidate.route_confidence,
                )

            if not self.config.planner_routing_enabled:
                return CalculationPlannerEvaluation(
                    candidate=True,
                    disposition=CalculationRouteDisposition.ROUTING_DISABLED,
                    extracted_expression=candidate.extracted_expression,
                    requested_mode=requested_mode if requested_mode != CalculationOutputMode.ANSWER_ONLY else candidate.requested_mode,
                    reasons=list(candidate.reasons),
                    feature_enabled=True,
                    planner_routing_enabled=False,
                    route_confidence=candidate.route_confidence,
                )

            return CalculationPlannerEvaluation(
                candidate=True,
                disposition=CalculationRouteDisposition.DIRECT_EXPRESSION,
                extracted_expression=candidate.extracted_expression,
                requested_mode=requested_mode if requested_mode != CalculationOutputMode.ANSWER_ONLY else candidate.requested_mode,
                reasons=list(candidate.reasons),
                feature_enabled=True,
                planner_routing_enabled=True,
                route_confidence=candidate.route_confidence,
            )

        helper_match = self._helpers.match_request(raw_text=raw_text, normalized_text=normalized_text)
        if not helper_match.candidate:
            follow_up = self._follow_up_from_active_context(
                raw_text=raw_text,
                normalized_text=normalized_text,
                active_context=active_context or {},
            )
            if follow_up is not None:
                return follow_up
            return CalculationPlannerEvaluation(
                candidate=False,
                disposition=CalculationRouteDisposition.NOT_REQUESTED,
                feature_enabled=self.config.enabled,
                planner_routing_enabled=self.config.planner_routing_enabled,
            )

        if not self.config.enabled:
            return CalculationPlannerEvaluation(
                candidate=True,
                disposition=CalculationRouteDisposition.FEATURE_DISABLED,
                requested_mode=requested_mode,
                helper_name=helper_match.helper_name,
                helper_status=helper_match.helper_status,
                arguments=dict(helper_match.arguments),
                missing_arguments=list(helper_match.missing_arguments),
                reasons=list(helper_match.reasons),
                feature_enabled=False,
                planner_routing_enabled=self.config.planner_routing_enabled,
                route_confidence=helper_match.route_confidence,
            )

        if not self.config.planner_routing_enabled:
            return CalculationPlannerEvaluation(
                candidate=True,
                disposition=CalculationRouteDisposition.ROUTING_DISABLED,
                requested_mode=requested_mode,
                helper_name=helper_match.helper_name,
                helper_status=helper_match.helper_status,
                arguments=dict(helper_match.arguments),
                missing_arguments=list(helper_match.missing_arguments),
                reasons=list(helper_match.reasons),
                feature_enabled=True,
                planner_routing_enabled=False,
                route_confidence=helper_match.route_confidence,
            )

        return CalculationPlannerEvaluation(
            candidate=True,
            disposition=CalculationRouteDisposition.HELPER_REQUEST,
            requested_mode=requested_mode,
            helper_name=helper_match.helper_name,
            helper_status=helper_match.helper_status,
            arguments=dict(helper_match.arguments),
            missing_arguments=list(helper_match.missing_arguments),
            reasons=list(helper_match.reasons),
            feature_enabled=True,
            planner_routing_enabled=True,
            route_confidence=helper_match.route_confidence,
        )

    def _follow_up_from_active_context(
        self,
        *,
        raw_text: str,
        normalized_text: str,
        active_context: dict[str, object],
    ) -> CalculationPlannerEvaluation | None:
        requested_mode = detect_requested_output_mode(raw_text, normalized_text)
        continuity_follow_up = any(phrase in normalized_text for phrase in CONTINUITY_FOLLOW_UP_PHRASES)
        explanation_follow_up = any(phrase in normalized_text for phrase in EXPLANATION_FOLLOW_UP_PHRASES)
        if requested_mode == CalculationOutputMode.ANSWER_ONLY and not continuity_follow_up:
            return None
        if not explanation_follow_up and not continuity_follow_up:
            return None
        recent = active_context.get("recent_context_resolutions")
        if not isinstance(recent, list):
            return None
        for item in recent:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip().lower()
            if kind == "screen_awareness":
                screen_follow_up = self._screen_follow_up_evaluation(
                    requested_mode=requested_mode,
                    resolution=item,
                )
                if screen_follow_up is not None:
                    return screen_follow_up
                continue
            if kind != "calculation":
                continue
            result = item.get("result")
            trace = item.get("trace")
            if not isinstance(result, dict) or not isinstance(trace, dict):
                continue
            helper_name = str(trace.get("helper_used") or result.get("helper_used") or "").strip() or None
            extracted_expression = str(
                trace.get("extracted_expression") or result.get("expression") or ""
            ).strip() or None
            helper_arguments = trace.get("helper_arguments") if isinstance(trace.get("helper_arguments"), dict) else {}
            if helper_name:
                disposition = (
                    CalculationRouteDisposition.FEATURE_DISABLED
                    if not self.config.enabled
                    else CalculationRouteDisposition.ROUTING_DISABLED
                    if not self.config.planner_routing_enabled
                    else CalculationRouteDisposition.HELPER_REQUEST
                )
                return CalculationPlannerEvaluation(
                    candidate=True,
                    disposition=disposition,
                    requested_mode=requested_mode,
                    helper_name=helper_name,
                    helper_status="matched",
                    arguments=dict(helper_arguments),
                    reasons=["calculation follow-up reused prior helper result"],
                    feature_enabled=self.config.enabled,
                    planner_routing_enabled=self.config.planner_routing_enabled,
                    route_confidence=0.98,
                    follow_up_reuse=True,
                )
            if extracted_expression:
                disposition = (
                    CalculationRouteDisposition.FEATURE_DISABLED
                    if not self.config.enabled
                    else CalculationRouteDisposition.ROUTING_DISABLED
                    if not self.config.planner_routing_enabled
                    else CalculationRouteDisposition.DIRECT_EXPRESSION
                )
                return CalculationPlannerEvaluation(
                    candidate=True,
                    disposition=disposition,
                    extracted_expression=extracted_expression,
                    requested_mode=requested_mode,
                    reasons=["calculation follow-up reused prior direct expression"],
                    feature_enabled=self.config.enabled,
                    planner_routing_enabled=self.config.planner_routing_enabled,
                    route_confidence=0.98,
                    follow_up_reuse=True,
                )
        return None

    def _screen_follow_up_evaluation(
        self,
        *,
        requested_mode: CalculationOutputMode,
        resolution: dict[str, object],
    ) -> CalculationPlannerEvaluation | None:
        analysis = resolution.get("analysis_result")
        if not isinstance(analysis, dict):
            return None
        activity = analysis.get("calculation_activity")
        if not isinstance(activity, dict) or str(activity.get("status") or "").strip().lower() != "resolved":
            return None
        trace = activity.get("calculation_trace")
        result = activity.get("calculation_result")
        if not isinstance(trace, dict) or not isinstance(result, dict):
            return None
        helper_name = str(trace.get("helper_used") or result.get("helper_used") or "").strip() or None
        extracted_expression = str(
            trace.get("extracted_expression") or result.get("expression") or ""
        ).strip() or None
        helper_arguments = trace.get("helper_arguments") if isinstance(trace.get("helper_arguments"), dict) else {}
        if helper_name:
            disposition = (
                CalculationRouteDisposition.FEATURE_DISABLED
                if not self.config.enabled
                else CalculationRouteDisposition.ROUTING_DISABLED
                if not self.config.planner_routing_enabled
                else CalculationRouteDisposition.HELPER_REQUEST
            )
            return CalculationPlannerEvaluation(
                candidate=True,
                disposition=disposition,
                requested_mode=requested_mode,
                helper_name=helper_name,
                helper_status="matched",
                arguments=dict(helper_arguments),
                reasons=["explanation follow-up reused prior screen-aware helper result"],
                feature_enabled=self.config.enabled,
                planner_routing_enabled=self.config.planner_routing_enabled,
                route_confidence=0.97,
                follow_up_reuse=True,
            )
        if extracted_expression:
            disposition = (
                CalculationRouteDisposition.FEATURE_DISABLED
                if not self.config.enabled
                else CalculationRouteDisposition.ROUTING_DISABLED
                if not self.config.planner_routing_enabled
                else CalculationRouteDisposition.DIRECT_EXPRESSION
            )
            return CalculationPlannerEvaluation(
                candidate=True,
                disposition=disposition,
                extracted_expression=extracted_expression,
                requested_mode=requested_mode,
                reasons=["explanation follow-up reused prior screen-aware direct expression"],
                feature_enabled=self.config.enabled,
                planner_routing_enabled=self.config.planner_routing_enabled,
                route_confidence=0.97,
                follow_up_reuse=True,
            )
        return None


def _unsupported_browser_automation_text(text: str) -> bool:
    return bool(re.search(r"\b(?:captcha|robot|human\s+verification)\b", str(text or ""), flags=re.IGNORECASE))
