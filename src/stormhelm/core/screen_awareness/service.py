from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from stormhelm.core.calculations import CalculationResultVisibility
from stormhelm.core.calculations import build_calculations_subsystem
from stormhelm.config.models import CalculationsConfig
from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.screen_awareness.calculations import run_screen_calculation
from stormhelm.core.screen_awareness.action import DeterministicActionEngine
from stormhelm.core.screen_awareness.action import WindowsNativeActionExecutor
from stormhelm.core.screen_awareness.continuity import DeterministicContinuityEngine
from stormhelm.core.screen_awareness.grounding import DeterministicGroundingEngine
from stormhelm.core.screen_awareness.interpretation import DeterministicContextSynthesizer
from stormhelm.core.screen_awareness.interpretation import DeterministicScreenInterpreter
from stormhelm.core.screen_awareness.navigation import DeterministicNavigationEngine
from stormhelm.core.screen_awareness.models import ActionExecutionResult
from stormhelm.core.screen_awareness.models import ScreenAnalysisResult
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import NavigationOutcome
from stormhelm.core.screen_awareness.models import CompletionStatus
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenLimitation
from stormhelm.core.screen_awareness.models import ScreenLimitationCode
from stormhelm.core.screen_awareness.models import ScreenResponse
from stormhelm.core.screen_awareness.models import ScreenTruthState
from stormhelm.core.screen_awareness.models import ScreenTruthfulnessContract
from stormhelm.core.screen_awareness.models import VerificationOutcome
from stormhelm.core.screen_awareness.models import WorkflowContinuityResult
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
    response_composer: ScreenResponseComposer = field(default_factory=ScreenResponseComposer)
    observation_source: Any | None = None
    action_executor: Any | None = None

    def __post_init__(self) -> None:
        self.planner_seam = ScreenAwarenessPlannerSeam(self.config)
        self.native_observer = self.observation_source or NativeContextObservationSource(system_probe=self.system_probe)
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
                "calculations_seam_available": self.calculations is not None,
                "system_probe_available": self.system_probe is not None,
                "provider_visual_augmentation_available": self.provider is not None,
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
        grounding_result: GroundingOutcome | None = None
        navigation_result: NavigationOutcome | None = None
        verification_result: VerificationOutcome | None = None
        action_result: ActionExecutionResult | None = None
        continuity_result: WorkflowContinuityResult | None = None
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
        if self.config.phase in {"phase2", "phase3", "phase4", "phase5", "phase6"} and self.config.grounding_enabled and not any(
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
            self.config.phase in {"phase3", "phase4", "phase5", "phase6"}
            and self.config.guidance_enabled
            and intent in {ScreenIntentType.GUIDE_NAVIGATION, ScreenIntentType.EXECUTE_UI_ACTION}
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
            self.config.phase in {"phase4", "phase5", "phase6"}
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
            self.config.phase in {"phase5", "phase6"}
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

        if (
            self.config.phase == "phase6"
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

        if verification_result is not None:
            confidence_scores.append(verification_result.confidence.score)
        if action_result is not None:
            confidence_scores.append(action_result.confidence.score)
        if continuity_result is not None:
            confidence_scores.append(continuity_result.confidence.score)
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
            grounding_result=grounding_result,
            navigation_result=navigation_result,
            verification_result=verification_result,
            action_result=action_result,
            continuity_result=continuity_result,
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
