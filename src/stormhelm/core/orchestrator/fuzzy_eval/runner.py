from __future__ import annotations

from dataclasses import replace
import re

from stormhelm.core.orchestrator.fuzzy_eval.models import CaseEvaluationResult
from stormhelm.core.orchestrator.fuzzy_eval.models import ChainEvaluationResult
from stormhelm.core.orchestrator.fuzzy_eval.models import ClarificationExpectation
from stormhelm.core.orchestrator.fuzzy_eval.models import ClarificationQualityClass
from stormhelm.core.orchestrator.fuzzy_eval.models import EvaluationExpectation
from stormhelm.core.orchestrator.fuzzy_eval.models import FollowUpChain
from stormhelm.core.orchestrator.fuzzy_eval.models import FuzzyCorpus
from stormhelm.core.orchestrator.fuzzy_eval.models import FuzzyDecisionObservation
from stormhelm.core.orchestrator.fuzzy_eval.models import NativeUtilizationClass
from stormhelm.core.orchestrator.fuzzy_eval.models import RouteHitClass
from stormhelm.core.orchestrator.fuzzy_eval.models import SupportAugmentationClass
from stormhelm.core.orchestrator.fuzzy_eval.models import UtteranceCase
from stormhelm.core.orchestrator.planner import DeterministicPlanner


def classify_route_hit(expectation: EvaluationExpectation, observation: FuzzyDecisionObservation) -> RouteHitClass:
    if observation.route_family != expectation.expected_route_family:
        if observation.route_family == "generic_provider" and expectation.expected_route_family != "generic_provider":
            return RouteHitClass.PUNT_MISS
        return RouteHitClass.WRONG_ROUTE_MISS
    if expectation.clarification.required:
        if observation.clarification_code:
            return RouteHitClass.CLARIFIED_HIT
        if observation.ambiguity_live:
            return RouteHitClass.FABRICATED_CONFIDENCE_MISS
        return RouteHitClass.WEAK_HIT
    if observation.clarification_code:
        return RouteHitClass.WEAK_HIT
    if observation.ambiguity_live and observation.posture == "likely_winner":
        return RouteHitClass.WEAK_HIT
    return RouteHitClass.STRONG_HIT


def _clarification_quality(
    expectation: ClarificationExpectation,
    observation: FuzzyDecisionObservation,
) -> ClarificationQualityClass:
    if not expectation.required and not observation.clarification_code:
        return ClarificationQualityClass.NOT_NEEDED
    if expectation.required and not observation.clarification_code:
        return ClarificationQualityClass.FAILED_TO_REDUCE_UNCERTAINTY
    if observation.clarification_code and not expectation.required:
        return ClarificationQualityClass.UNNECESSARY
    if observation.clarification_candidate_specific:
        return ClarificationQualityClass.MINIMAL_CANDIDATE_SPECIFIC
    return ClarificationQualityClass.BROAD_GENERIC


def _utilization(
    expectation: EvaluationExpectation,
    observation: FuzzyDecisionObservation,
) -> NativeUtilizationClass:
    if observation.route_family == "generic_provider" and expectation.expected_route_family != "generic_provider":
        return NativeUtilizationClass.PROVIDER_PUNT
    expected_tools = set(expectation.expected_native_tools)
    if expected_tools and expected_tools.intersection(observation.planned_tools):
        return NativeUtilizationClass.NATIVE_MATCH
    expected_capabilities = set(expectation.expected_capabilities)
    if expected_capabilities and expected_capabilities.intersection(observation.capability_requirements):
        return NativeUtilizationClass.NATIVE_MATCH
    if not expected_tools and not expected_capabilities:
        return NativeUtilizationClass.NOT_APPLICABLE
    return NativeUtilizationClass.NATIVE_BYPASS


def _support_augmentation(
    expectation: EvaluationExpectation,
    observation: FuzzyDecisionObservation,
) -> SupportAugmentationClass:
    expected = set(expectation.expected_support_systems)
    actual = set(observation.support_systems)
    if not expected:
        return SupportAugmentationClass.CORRECTLY_QUIET if not actual else SupportAugmentationClass.INTRUSIVE
    if expected.issubset(actual):
        return SupportAugmentationClass.EXPECTED_ENGAGED
    return SupportAugmentationClass.EXPECTED_MISSING


class FuzzyEvaluationRunner:
    def __init__(self, *, planners: dict[str, DeterministicPlanner] | None = None) -> None:
        self._planners = dict(planners or {"default": DeterministicPlanner()})

    def evaluate_case(self, case: UtteranceCase) -> CaseEvaluationResult:
        planner = self._planners[case.runtime_profile]
        active_request_state = dict(case.input.active_request_state or {})
        active_context = dict(case.input.active_context or {})
        decision = planner.plan(
            case.input.message,
            session_id="fuzzy-eval",
            surface_mode=case.input.surface_mode,
            active_module=case.input.active_module,
            workspace_context=dict(case.input.workspace_context or {}) or None,
            active_posture=dict(case.input.active_posture or {}),
            active_request_state=active_request_state,
            recent_tool_results=list(case.input.recent_tool_results or []),
            active_context=active_context,
        )
        observation = self._observation_for(case, decision)
        expectation = EvaluationExpectation(
            expected_route_family=case.route_family,
            clarification=case.clarification,
            expected_native_tools=case.expected_native_tools,
            expected_capabilities=case.expected_capabilities,
            expected_support_systems=case.expected_support_systems,
        )
        return CaseEvaluationResult(
            case=case,
            observation=observation,
            route_hit=classify_route_hit(expectation, observation),
            clarification_quality=_clarification_quality(expectation.clarification, observation),
            utilization=_utilization(expectation, observation),
            support_augmentation=_support_augmentation(expectation, observation),
        )

    def evaluate_chain(self, chain: FollowUpChain, *, corpus: FuzzyCorpus) -> ChainEvaluationResult:
        return ChainEvaluationResult(
            chain=chain,
            turn_results=tuple(self.evaluate_case(corpus.cases_by_id[case_id]) for case_id in chain.case_ids),
        )

    def _observation_for(self, case: UtteranceCase, decision) -> FuzzyDecisionObservation:
        route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
        winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
        binding = route_state.get("deictic_binding") if isinstance(route_state.get("deictic_binding"), dict) else {}
        runner_up = winner.get("runner_up_summary") if isinstance(winner.get("runner_up_summary"), dict) else {}
        clarification_message = str(decision.assistant_message or winner.get("clarification_reason") or "").strip() or None
        clarification_code = str(
            winner.get("clarification_code")
            or (decision.clarification_reason.code if decision.clarification_reason is not None else "")
        ).strip() or None
        planned_tools = tuple(
            str(tool_name).strip()
            for tool_name in (
                winner.get("planned_tools")
                if isinstance(winner.get("planned_tools"), list)
                else [request.tool_name for request in decision.tool_requests]
            )
            if str(tool_name).strip()
        )
        capability_requirements = tuple(
            str(item).strip()
            for item in (
                winner.get("capability_requirements")
                if isinstance(winner.get("capability_requirements"), list)
                else list(decision.structured_query.capability_requirements if decision.structured_query is not None else [])
            )
            if str(item).strip()
        )
        support_systems = tuple(sorted(self._support_systems_for(case, decision, route_state)))
        return FuzzyDecisionObservation(
            route_family=str(winner.get("route_family") or case.route_family),
            posture=str(winner.get("posture") or ""),
            status=str(winner.get("status") or ""),
            response_mode=str(decision.response_mode or ""),
            ambiguity_live=bool(winner.get("ambiguity_live")),
            runner_up_family=str(runner_up.get("route_family") or "").strip() or None,
            clarification_code=clarification_code,
            clarification_message=clarification_message,
            clarification_candidate_specific=self._clarification_is_candidate_specific(clarification_message, route_state),
            planned_tools=planned_tools,
            capability_requirements=capability_requirements,
            support_systems=support_systems,
            deictic_source=str(binding.get("selected_source") or "").strip() or None,
        )

    def _support_systems_for(self, case: UtteranceCase, decision, route_state: dict[str, object]) -> set[str]:
        systems: set[str] = set()
        summary = route_state.get("support_augmentation_summary") if isinstance(route_state.get("support_augmentation_summary"), list) else []
        for note in summary:
            cleaned = str(note or "").strip().lower()
            if cleaned == "active request state":
                systems.add("active_request_state")
            elif cleaned == "active screen context":
                systems.add("screen_context")
            elif cleaned:
                systems.add(re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_"))
        if case.input.active_request_state:
            systems.add("active_request_state")
        trust = case.input.active_request_state.get("trust") if isinstance(case.input.active_request_state, dict) else {}
        if trust or (decision.route_state is not None and decision.route_state.winner.route_family == "trust_approvals"):
            systems.add("trust")
        if case.input.workspace_context:
            systems.add("workspace_context")
        if case.route_family == "task_continuity":
            systems.add("task_continuity")
        binding = route_state.get("deictic_binding") if isinstance(route_state.get("deictic_binding"), dict) else {}
        if binding.get("selected_source") or binding.get("candidates"):
            systems.add("deictic_binding")
        return systems

    def _clarification_is_candidate_specific(self, message: str | None, route_state: dict[str, object]) -> bool:
        if not message:
            return False
        lowered = message.lower()
        binding = route_state.get("deictic_binding") if isinstance(route_state.get("deictic_binding"), dict) else {}
        candidates = binding.get("candidates") if isinstance(binding.get("candidates"), list) else []
        mentions = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            descriptors = {
                str(candidate.get("label") or "").strip().lower(),
                str(candidate.get("target_type") or "").strip().lower(),
                str(candidate.get("source") or "").strip().lower(),
            }
            if any(descriptor and descriptor in lowered for descriptor in descriptors):
                mentions += 1
        return mentions >= 2
