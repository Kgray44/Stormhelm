from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from stormhelm.core.calculations import CalculationResultVisibility
from stormhelm.core.calculations import build_calculations_subsystem
from stormhelm.config.models import CalculationsConfig
from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.screen_awareness.adapters import SemanticAdapterRegistry
from stormhelm.core.screen_awareness.calculations import run_screen_calculation
from stormhelm.core.screen_awareness.action import DeterministicActionEngine
from stormhelm.core.screen_awareness.action import WindowsNativeActionExecutor
from stormhelm.core.screen_awareness.continuity import DeterministicContinuityEngine
from stormhelm.core.screen_awareness.grounding import DeterministicGroundingEngine
from stormhelm.core.screen_awareness.interpretation import DeterministicContextSynthesizer
from stormhelm.core.screen_awareness.interpretation import DeterministicScreenInterpreter
from stormhelm.core.screen_awareness.navigation import DeterministicNavigationEngine
from stormhelm.core.screen_awareness.problem_solving import DeterministicProblemSolvingEngine
from stormhelm.core.screen_awareness.workflow_learning import DeterministicWorkflowLearningEngine
from stormhelm.core.screen_awareness.models import ActionExecutionResult
from stormhelm.core.screen_awareness.models import ScreenAnalysisResult
from stormhelm.core.screen_awareness.models import AppAdapterResolution
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import NavigationOutcome
from stormhelm.core.screen_awareness.models import CompletionStatus
from stormhelm.core.screen_awareness.models import ProblemSolvingResult
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenLimitation
from stormhelm.core.screen_awareness.models import ScreenLimitationCode
from stormhelm.core.screen_awareness.models import ScreenResponse
from stormhelm.core.screen_awareness.models import ScreenSourceType
from stormhelm.core.screen_awareness.models import ScreenTruthState
from stormhelm.core.screen_awareness.models import ScreenTruthfulnessContract
from stormhelm.core.screen_awareness.models import VerificationOutcome
from stormhelm.core.screen_awareness.models import WorkflowContinuityResult
from stormhelm.core.screen_awareness.models import WorkflowLearningResult
from stormhelm.core.screen_awareness.models import confidence_level_for_score
from stormhelm.core.screen_awareness.observation import NativeContextObservationSource
from stormhelm.core.screen_awareness.observation import best_visible_text
from stormhelm.core.screen_awareness.observation import has_direct_screen_signal
from stormhelm.core.screen_awareness.planner import ScreenAwarenessPlannerSeam
from stormhelm.core.screen_awareness.response import ScreenResponseComposer
from stormhelm.core.screen_awareness.verification import DeterministicVerificationEngine


@dataclass(slots=True)
class ScreenAwarenessSubsystem:
    config: ScreenAwarenessConfig
    system_probe: Any | None = None
    provider: Any | None = None
    calculations: Any | None = None
    planner_seam: ScreenAwarenessPlannerSeam = field(init=False)
    truthfulness_contract: ScreenTruthfulnessContract = field(default_factory=ScreenTruthfulnessContract)
    extension_points: dict[str, bool] = field(
        default_factory=lambda: {
            "observation": True,
            "interpretation": True,
            "grounding": True,
            "guidance": True,
            "action": True,
            "verification": True,
            "memory": True,
            "continuity": True,
            "adapters": True,
            "problem_solving": True,
            "workflow_learning": True,
            "timeline": True,
            "response_grounding": True,
            "layered_observation": True,
            "provider_visual_augmentation": True,
        }
    )
    native_observer: NativeContextObservationSource = field(init=False)
    interpreter: DeterministicScreenInterpreter = field(default_factory=DeterministicScreenInterpreter)
    context_synthesizer: DeterministicContextSynthesizer = field(default_factory=DeterministicContextSynthesizer)
    grounding_engine: DeterministicGroundingEngine = field(init=False)
    navigation_engine: DeterministicNavigationEngine = field(init=False)
    verification_engine: DeterministicVerificationEngine = field(init=False)
    action_engine: DeterministicActionEngine = field(init=False)
    continuity_engine: DeterministicContinuityEngine = field(default_factory=DeterministicContinuityEngine)
    problem_solving_engine: DeterministicProblemSolvingEngine = field(init=False)
    workflow_learning_engine: DeterministicWorkflowLearningEngine = field(init=False)
    response_composer: ScreenResponseComposer = field(default_factory=ScreenResponseComposer)
    observation_source: Any | None = None
    action_executor: Any | None = None
    adapter_registry: SemanticAdapterRegistry = field(init=False)

    def __post_init__(self) -> None:
        self.planner_seam = ScreenAwarenessPlannerSeam(self.config)
        self.native_observer = self.observation_source or NativeContextObservationSource(system_probe=self.system_probe)
        self.adapter_registry = SemanticAdapterRegistry()
        self.grounding_engine = DeterministicGroundingEngine(provider=self.provider)
        self.navigation_engine = DeterministicNavigationEngine(grounding_engine=self.grounding_engine)
        self.verification_engine = DeterministicVerificationEngine(calculations=self.calculations)
        self.action_engine = DeterministicActionEngine(
            config=self.config,
            observer=self.native_observer,
            interpreter=self.interpreter,
            context_synthesizer=self.context_synthesizer,
            verification_engine=self.verification_engine,
            executor=self.action_executor or WindowsNativeActionExecutor(),
        )
        self.problem_solving_engine = DeterministicProblemSolvingEngine(calculations=self.calculations)
        self.workflow_learning_engine = DeterministicWorkflowLearningEngine(config=self.config)

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "phase": self.config.phase,
            "enabled": self.config.enabled,
            "planner_routing_enabled": self.config.planner_routing_enabled,
            "debug_events_enabled": self.config.debug_events_enabled,
            "action_policy_mode": self.config.action_policy_mode,
            "capabilities": self.config.capability_flags(),
            "truthfulness_contract": self.truthfulness_contract.to_dict(),
            "extension_points": dict(self.extension_points),
            "runtime_hooks": {
                "native_observer_ready": True,
                "grounding_engine_ready": True,
                "navigation_engine_ready": True,
                "verification_engine_ready": True,
                "action_engine_ready": True,
                "continuity_engine_ready": True,
                "adapter_registry_ready": True,
                "problem_solving_engine_ready": True,
                "workflow_learning_engine_ready": True,
                "supported_adapters": self.adapter_registry.supported_adapter_ids(),
                "calculations_seam_available": self.calculations is not None,
                "system_probe_available": self.system_probe is not None,
                "provider_visual_augmentation_available": self.provider is not None,
                "workflow_learning": self.workflow_learning_engine.status_snapshot(),
            },
        }

    def handle_request(
        self,
        *,
        session_id: str,
        operator_text: str,
        intent: ScreenIntentType,
        surface_mode: str,
        active_module: str,
        active_context: dict[str, Any] | None,
        workspace_context: dict[str, Any] | None = None,
    ) -> ScreenResponse:
        active_context = active_context or {}
        workspace_context = workspace_context or {}
        observation = self.native_observer.observe(
            session_id=session_id,
            surface_mode=surface_mode,
            active_module=active_module,
            active_context=active_context,
            workspace_context=workspace_context,
        )
        interpretation = self.interpreter.interpret(observation, operator_text=operator_text)
        current_screen_context = self.context_synthesizer.synthesize(observation, interpretation)
        adapter_resolution: AppAdapterResolution | None = None
        if self.config.capability_flags().get("adapters_enabled"):
            adapter_resolution = self.adapter_registry.resolve(
                observation=observation,
                active_context=active_context,
            )
            if adapter_resolution is not None:
                current_screen_context = self.adapter_registry.enrich_context(
                    current_context=current_screen_context,
                    resolution=adapter_resolution,
                )
                if ScreenSourceType.APP_ADAPTER not in observation.source_types_used:
                    observation.source_types_used.append(ScreenSourceType.APP_ADAPTER)
                if adapter_resolution.available:
                    observation.quality_notes.append(adapter_resolution.provenance_note)
                else:
                    observation.warnings.append(adapter_resolution.provenance_note)
        grounding_result: GroundingOutcome | None = None
        navigation_result: NavigationOutcome | None = None
        verification_result: VerificationOutcome | None = None
        action_result: ActionExecutionResult | None = None
        continuity_result: WorkflowContinuityResult | None = None
        problem_solving_result: ProblemSolvingResult | None = None
        workflow_learning_result: WorkflowLearningResult | None = None
        calculation_activity = None

        limitations: list[ScreenLimitation] = []
        fallback_reason: str | None = None
        if not has_direct_screen_signal(observation):
            limitations.append(
                ScreenLimitation(
                    code=ScreenLimitationCode.OBSERVATION_UNAVAILABLE,
                    message="No reliable focused window, selected text, clipboard text, or workspace surface was available.",
                    truth_state=ScreenTruthState.UNAVAILABLE,
                )
            )
            fallback_reason = "observation_unavailable"
        elif not observation.selected_text and not observation.clipboard_text:
            limitations.append(
                ScreenLimitation(
                    code=ScreenLimitationCode.LOW_CONFIDENCE,
                    message="The visible signal is partial because no direct selected text was available.",
                    truth_state=ScreenTruthState.UNVERIFIED,
                )
            )
        if adapter_resolution is not None and adapter_resolution.fallback_reason is not None and fallback_reason is None:
            fallback_reason = adapter_resolution.fallback_reason.value

        if intent == ScreenIntentType.DETECT_VISIBLE_CHANGE and not (
            self.config.phase in {"phase4", "phase5"} and self.config.verification_enabled
        ):
            limitations.append(
                ScreenLimitation(
                    code=ScreenLimitationCode.PRIOR_OBSERVATION_REQUIRED,
                    message="A prior screen observation is required to ground a change comparison.",
                    truth_state=ScreenTruthState.UNAVAILABLE,
                )
            )
            limitations.append(
                ScreenLimitation(
                    code=ScreenLimitationCode.UNVERIFIED_CHANGE,
                    message="Stormhelm must not claim a verified visible change from a single observation.",
                    truth_state=ScreenTruthState.UNVERIFIED,
                )
            )
            fallback_reason = fallback_reason or "prior_observation_required"

        confidence_scores = [current_screen_context.confidence.score]
        confidence_scores.extend(confidence.score for confidence in interpretation.confidence_by_facet.values())
        if self.config.phase in {"phase2", "phase3", "phase4", "phase5", "phase6", "phase7", "phase8", "phase9"} and self.config.grounding_enabled and not any(
            limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations
        ):
            grounding_result = self.grounding_engine.resolve(
                operator_text=operator_text,
                intent=intent,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
            )
        if (
            self.config.phase in {"phase3", "phase4", "phase5", "phase6", "phase7", "phase8", "phase9"}
            and self.config.guidance_enabled
            and intent in {ScreenIntentType.GUIDE_NAVIGATION, ScreenIntentType.EXECUTE_UI_ACTION, ScreenIntentType.LEARN_WORKFLOW_REUSE}
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            navigation_result = self.navigation_engine.resolve(
                operator_text=operator_text,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
                grounding_result=grounding_result,
            )
        if (
            self.config.phase in {"phase4", "phase5", "phase6", "phase7", "phase8", "phase9"}
            and self.config.verification_enabled
            and intent != ScreenIntentType.EXECUTE_UI_ACTION
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            verification_result = self.verification_engine.verify(
                session_id=session_id,
                operator_text=operator_text,
                intent=intent,
                surface_mode=surface_mode,
                active_module=active_module,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
                grounding_result=grounding_result,
                navigation_result=navigation_result,
                active_context=active_context,
            )
            if verification_result is not None and verification_result.calculation_activity is not None:
                calculation_activity = verification_result.calculation_activity
            if (
                intent == ScreenIntentType.DETECT_VISIBLE_CHANGE
                and verification_result is not None
                and not verification_result.comparison.comparison_ready
            ):
                limitations.append(
                    ScreenLimitation(
                        code=ScreenLimitationCode.PRIOR_OBSERVATION_REQUIRED,
                        message="A prior screen observation is required to ground a change comparison.",
                        truth_state=ScreenTruthState.UNAVAILABLE,
                    )
                )
                limitations.append(
                    ScreenLimitation(
                        code=ScreenLimitationCode.UNVERIFIED_CHANGE,
                        message="Stormhelm must not claim a verified visible change without a grounded comparison basis.",
                        truth_state=ScreenTruthState.UNVERIFIED,
                    )
                )
                fallback_reason = fallback_reason or "prior_observation_required"

        if (
            intent == ScreenIntentType.SOLVE_VISIBLE_PROBLEM
            and self.config.phase not in {"phase8", "phase9"}
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            preferred_text = (
                grounding_result.winning_target.visible_text
                if grounding_result is not None and grounding_result.winning_target is not None
                else None
            )
            calculation_activity = run_screen_calculation(
                calculations=self.calculations,
                session_id=session_id,
                surface_mode=surface_mode,
                active_module=active_module,
                operator_text=operator_text,
                observation=observation,
                caller_intent="solve_visible_problem",
                preferred_text=preferred_text,
                internal_validation=False,
                result_visibility=CalculationResultVisibility.USER_FACING,
            )

        if (
            self.config.phase in {"phase5", "phase6", "phase7", "phase8", "phase9"}
            and self.config.action_enabled
            and intent == ScreenIntentType.EXECUTE_UI_ACTION
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            action_envelope = self.action_engine.execute(
                session_id=session_id,
                operator_text=operator_text,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
                grounding_result=grounding_result,
                navigation_result=navigation_result,
                active_context=active_context,
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=workspace_context,
            )
            action_result = action_envelope.result
            observation = action_envelope.observation
            interpretation = action_envelope.interpretation
            current_screen_context = action_envelope.current_context
            if action_envelope.verification is not None:
                verification_result = action_envelope.verification
            if self.config.capability_flags().get("adapters_enabled"):
                adapter_resolution = self.adapter_registry.resolve(
                    observation=observation,
                    active_context=active_context,
                )
                if adapter_resolution is not None:
                    current_screen_context = self.adapter_registry.enrich_context(
                        current_context=current_screen_context,
                        resolution=adapter_resolution,
                    )

        if (
            self.config.phase in {"phase6", "phase7", "phase8", "phase9"}
            and self.config.memory_enabled
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            continuity_result = self.continuity_engine.assess(
                operator_text=operator_text,
                intent=intent,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
                grounding_result=grounding_result,
                navigation_result=navigation_result,
                verification_result=verification_result,
                action_result=action_result,
                active_context=active_context,
            )

        if (
            self.config.phase in {"phase8", "phase9"}
            and self.config.capability_flags().get("problem_solving_enabled")
            and intent in {ScreenIntentType.EXPLAIN_VISIBLE_CONTENT, ScreenIntentType.SOLVE_VISIBLE_PROBLEM}
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            problem_envelope = self.problem_solving_engine.solve(
                session_id=session_id,
                operator_text=operator_text,
                intent=intent,
                surface_mode=surface_mode,
                active_module=active_module,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
                grounding_result=grounding_result,
                navigation_result=navigation_result,
                verification_result=verification_result,
                action_result=action_result,
                continuity_result=continuity_result,
                adapter_resolution=adapter_resolution,
                active_context=active_context,
            )
            if problem_envelope is not None:
                problem_solving_result = problem_envelope.result
                if problem_envelope.calculation_activity is not None:
                    calculation_activity = problem_envelope.calculation_activity

        if (
            self.config.phase == "phase9"
            and self.config.capability_flags().get("workflow_learning_enabled")
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            workflow_envelope = self.workflow_learning_engine.assess(
                session_id=session_id,
                operator_text=operator_text,
                intent=intent,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
                grounding_result=grounding_result,
                navigation_result=navigation_result,
                verification_result=verification_result,
                action_result=action_result,
                continuity_result=continuity_result,
                adapter_resolution=adapter_resolution,
                problem_solving_result=problem_solving_result,
                active_context=active_context,
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=workspace_context,
                action_engine=self.action_engine,
            )
            if workflow_envelope is not None:
                workflow_learning_result = workflow_envelope.result
                if workflow_envelope.action_result is not None:
                    action_result = workflow_envelope.action_result
                    observation = workflow_envelope.observation or observation
                    interpretation = workflow_envelope.interpretation or interpretation
                    current_screen_context = workflow_envelope.current_context or current_screen_context
                    if workflow_envelope.verification is not None:
                        verification_result = workflow_envelope.verification

        if adapter_resolution is not None:
            channels = set()
            if grounding_result is not None:
                channels.update(channel.value for channel in grounding_result.provenance.channels_used)
            if navigation_result is not None:
                channels.update(channel.value for channel in navigation_result.provenance.channels_used)
            if verification_result is not None:
                channels.update(channel.value for channel in verification_result.provenance.channels_used)
            if continuity_result is not None:
                channels.update(channel.value for channel in continuity_result.provenance.channels_used)
            if problem_solving_result is not None:
                channels.update(channel.value for channel in problem_solving_result.provenance.channels_used)
            adapter_resolution.used_for_grounding = "adapter_semantics" in channels or bool(
                grounding_result is not None
                and grounding_result.winning_target is not None
                and grounding_result.winning_target.source_channel.value == "adapter_semantics"
            )
            adapter_resolution.used_for_navigation = "adapter_semantics" in channels or bool(
                navigation_result is not None
                and navigation_result.winning_candidate is not None
                and navigation_result.winning_candidate.source_channel.value == "adapter_semantics"
            )
            adapter_resolution.used_for_verification = "adapter_semantics" in channels or bool(
                verification_result is not None
                and verification_result.context.provenance_channels
                and any(channel.value == "adapter_semantics" for channel in verification_result.context.provenance_channels)
            )
            adapter_resolution.used_for_action = bool(
                action_result is not None
                and action_result.plan.target is not None
                and action_result.plan.target.source_channel is not None
                and action_result.plan.target.source_channel.value == "adapter_semantics"
            )
            adapter_resolution.used_for_continuity = "adapter_semantics" in channels
            adapter_resolution.used_for_problem_solving = bool(
                problem_solving_result is not None and problem_solving_result.reused_adapter
            )

        if verification_result is not None:
            confidence_scores.append(verification_result.confidence.score)
        if action_result is not None:
            confidence_scores.append(action_result.confidence.score)
        if continuity_result is not None:
            confidence_scores.append(continuity_result.confidence.score)
        if problem_solving_result is not None:
            confidence_scores.append(problem_solving_result.confidence.score)
        if workflow_learning_result is not None:
            confidence_scores.append(workflow_learning_result.confidence.score)
        overall_score = mean(confidence_scores) if confidence_scores else 0.0
        if any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations):
            overall_score = 0.0
        elif any(limitation.code == ScreenLimitationCode.LOW_CONFIDENCE for limitation in limitations):
            overall_score = min(overall_score, 0.45)
        verification_state = ScreenTruthState.UNVERIFIED
        if action_result is not None and action_result.status.value == "verified_success":
            verification_state = ScreenTruthState.OBSERVED
        elif verification_result is not None:
            verification_state = (
                ScreenTruthState.OBSERVED
                if verification_result.comparison.comparison_ready or verification_result.completion_status == CompletionStatus.COMPLETED
                else ScreenTruthState.UNVERIFIED
            )

        analysis = ScreenAnalysisResult(
            observation=observation,
            interpretation=interpretation,
            current_screen_context=current_screen_context,
            adapter_resolution=adapter_resolution,
            grounding_result=grounding_result,
            navigation_result=navigation_result,
            verification_result=verification_result,
            action_result=action_result,
            continuity_result=continuity_result,
            problem_solving_result=problem_solving_result,
            workflow_learning_result=workflow_learning_result,
            calculation_activity=calculation_activity,
            limitations=limitations,
            fallback_reason=fallback_reason,
            confidence=ScreenConfidence(
                score=overall_score,
                level=confidence_level_for_score(overall_score),
                note="Overall screen-awareness confidence blends native observation, interpretation, and context synthesis.",
            ),
            truthfulness_contract=self.truthfulness_contract,
            verification_state=verification_state,
        )
        response = self.response_composer.compose(intent=intent, analysis=analysis)
        response.telemetry.update(
            {
                "route": {"intent": intent.value, "surface_mode": surface_mode, "active_module": active_module},
                "visual_augmentation": self._visual_augmentation_status(observation),
                "grounding_visual_augmentation": self.grounding_engine.provider_grounding_status(observation),
                "analysis_result": analysis.to_dict(),
            }
        )
        return response

    def _visual_augmentation_status(self, observation: Any) -> dict[str, Any]:
        capture_reference = str(getattr(observation, "capture_reference", "") or "").strip()
        if not self.provider:
            return {"attempted": False, "used": False, "reason": "provider_unavailable"}
        if not capture_reference:
            return {"attempted": False, "used": False, "reason": "no_capture_reference"}
        if not best_visible_text(observation):
            return {"attempted": False, "used": False, "reason": "sync_phase1_visual_augmentation_deferred"}
        return {"attempted": False, "used": False, "reason": "native_signal_sufficient"}


def build_screen_awareness_subsystem(
    config: ScreenAwarenessConfig,
    *,
    system_probe: Any | None = None,
    provider: Any | None = None,
    calculations: Any | None = None,
    observation_source: Any | None = None,
    action_executor: Any | None = None,
) -> ScreenAwarenessSubsystem:
    return ScreenAwarenessSubsystem(
        config=config,
        system_probe=system_probe,
        provider=provider,
        calculations=calculations or build_calculations_subsystem(CalculationsConfig()),
        observation_source=observation_source,
        action_executor=action_executor,
    )
