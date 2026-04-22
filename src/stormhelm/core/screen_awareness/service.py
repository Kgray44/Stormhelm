from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean
from time import monotonic
from typing import Any
from uuid import uuid4

from stormhelm.core.calculations import CalculationResultVisibility
from stormhelm.core.calculations import build_calculations_subsystem
from stormhelm.config.models import CalculationsConfig
from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.screen_awareness.adapters import SemanticAdapterRegistry
from stormhelm.core.screen_awareness.calculations import run_screen_calculation
from stormhelm.core.screen_awareness.action import DeterministicActionEngine
from stormhelm.core.screen_awareness.action import WindowsNativeActionExecutor
from stormhelm.core.screen_awareness.brain_integration import DeterministicBrainIntegrationEngine
from stormhelm.core.screen_awareness.continuity import DeterministicContinuityEngine
from stormhelm.core.screen_awareness.grounding import DeterministicGroundingEngine
from stormhelm.core.screen_awareness.interpretation import DeterministicContextSynthesizer
from stormhelm.core.screen_awareness.interpretation import DeterministicScreenInterpreter
from stormhelm.core.screen_awareness.navigation import DeterministicNavigationEngine
from stormhelm.core.screen_awareness.power_features import DeterministicPowerFeaturesEngine
from stormhelm.core.screen_awareness.problem_solving import DeterministicProblemSolvingEngine
from stormhelm.core.screen_awareness.workflow_learning import DeterministicWorkflowLearningEngine
from stormhelm.core.screen_awareness.models import ActionExecutionResult
from stormhelm.core.screen_awareness.models import ActionExecutionStatus
from stormhelm.core.screen_awareness.models import ActionPolicyMode
from stormhelm.core.screen_awareness.models import ScreenAnalysisResult
from stormhelm.core.screen_awareness.models import ScreenAuditFinding
from stormhelm.core.screen_awareness.models import ScreenAuditSeverity
from stormhelm.core.screen_awareness.models import AppAdapterResolution
from stormhelm.core.screen_awareness.models import ChangeClassification
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import GroundingAmbiguityStatus
from stormhelm.core.screen_awareness.models import NavigationOutcome
from stormhelm.core.screen_awareness.models import CompletionStatus
from stormhelm.core.screen_awareness.models import ProblemSolvingResult
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenLatencyTrace
from stormhelm.core.screen_awareness.models import ScreenLimitation
from stormhelm.core.screen_awareness.models import ScreenLimitationCode
from stormhelm.core.screen_awareness.models import ScreenPolicyState
from stormhelm.core.screen_awareness.models import ScreenRecoveryState
from stormhelm.core.screen_awareness.models import ScreenRecoveryStatus
from stormhelm.core.screen_awareness.models import ScreenResponse
from stormhelm.core.screen_awareness.models import ScreenSourceType
from stormhelm.core.screen_awareness.models import ScreenStageTiming
from stormhelm.core.screen_awareness.models import ScreenTruthState
from stormhelm.core.screen_awareness.models import ScreenTruthfulnessAudit
from stormhelm.core.screen_awareness.models import ScreenTruthfulnessContract
from stormhelm.core.screen_awareness.models import VerificationOutcome
from stormhelm.core.screen_awareness.models import WorkflowContinuityResult
from stormhelm.core.screen_awareness.models import WorkflowLearningResult
from stormhelm.core.screen_awareness.models import BrainIntegrationResult
from stormhelm.core.screen_awareness.models import PowerFeaturesResult
from stormhelm.core.screen_awareness.models import confidence_level_for_score
from stormhelm.core.screen_awareness.observation import NativeContextObservationSource
from stormhelm.core.screen_awareness.observation import best_live_visible_text
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
            "brain_integration": True,
            "power_features": True,
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
    brain_integration_engine: DeterministicBrainIntegrationEngine = field(init=False)
    power_features_engine: DeterministicPowerFeaturesEngine = field(default_factory=DeterministicPowerFeaturesEngine)
    response_composer: ScreenResponseComposer = field(default_factory=ScreenResponseComposer)
    observation_source: Any | None = None
    action_executor: Any | None = None
    adapter_registry: SemanticAdapterRegistry = field(init=False)
    _recent_trace_summaries: deque[dict[str, Any]] = field(init=False, repr=False)

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
        self.brain_integration_engine = DeterministicBrainIntegrationEngine(config=self.config)
        self._recent_trace_summaries = deque(maxlen=24)

    def status_snapshot(self) -> dict[str, Any]:
        policy_state = self._policy_state()
        return {
            "phase": self.config.phase,
            "enabled": self.config.enabled,
            "planner_routing_enabled": self.config.planner_routing_enabled,
            "debug_events_enabled": self.config.debug_events_enabled,
            "action_policy_mode": self.config.action_policy_mode,
            "capabilities": self.config.capability_flags(),
            "policy_state": policy_state.to_dict(),
            "hardening": {
                "enabled": self._phase12_enabled(),
                "truthfulness_audit_enabled": self._phase12_enabled(),
                "latency_trace_enabled": self._phase12_enabled(),
                "scenario_evaluation_ready": True,
                "recent_trace_count": len(self._recent_trace_summaries),
                "latest_trace": self._recent_trace_summaries[-1] if self._recent_trace_summaries else None,
            },
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
                "brain_integration_engine_ready": True,
                "power_features_engine_ready": bool(self.config.capability_flags().get("power_features_enabled", False)),
                "supported_adapters": self.adapter_registry.supported_adapter_ids(),
                "calculations_seam_available": self.calculations is not None,
                "system_probe_available": self.system_probe is not None,
                "provider_visual_augmentation_available": self.provider is not None,
                "workflow_learning": self.workflow_learning_engine.status_snapshot(),
                "brain_integration": self.brain_integration_engine.status_snapshot(),
                "power_features": self.power_features_engine.status_snapshot(),
            },
        }

    def _phase12_enabled(self) -> bool:
        return bool(self.config.capability_flags().get("hardening_enabled"))

    def _action_policy_mode(self) -> ActionPolicyMode:
        raw_mode = str(self.config.action_policy_mode or ActionPolicyMode.OBSERVE_ONLY.value).strip().lower()
        try:
            return ActionPolicyMode(raw_mode)
        except ValueError:
            return ActionPolicyMode.OBSERVE_ONLY

    def _policy_state(self) -> ScreenPolicyState:
        action_policy_mode = self._action_policy_mode()
        summary = (
            f"Phase {self.config.phase.replace('phase', '').strip() or '?'} runs with "
            f"{action_policy_mode.value.replace('_', ' ')} posture; restricted domains stay guarded and "
            f"{'debug traces are on' if self.config.debug_events_enabled else 'debug traces are off'}."
        )
        return ScreenPolicyState(
            phase=self.config.phase,
            feature_enabled=self.config.enabled,
            planner_routing_enabled=self.config.planner_routing_enabled,
            action_policy_mode=action_policy_mode,
            action_execution_enabled=bool(self.config.capability_flags().get("action_enabled")),
            verification_enabled=bool(self.config.capability_flags().get("verification_enabled")),
            restricted_domain_guarded=True,
            confirmation_required=action_policy_mode == ActionPolicyMode.CONFIRM_BEFORE_ACT,
            debug_events_enabled=self.config.debug_events_enabled,
            summary=summary,
        )

    def _build_recovery_state(
        self,
        *,
        limitations: list[ScreenLimitation],
        adapter_resolution: AppAdapterResolution | None,
        verification_result: VerificationOutcome | None,
        action_result: ActionExecutionResult | None,
        continuity_result: WorkflowContinuityResult | None,
        problem_solving_result: ProblemSolvingResult | None,
    ) -> ScreenRecoveryState:
        trigger_conditions: list[str] = []
        recovered_via: list[str] = []
        unresolved_conditions: list[str] = []
        limitation_codes = {limitation.code for limitation in limitations}

        if adapter_resolution is not None and adapter_resolution.fallback_reason is not None:
            trigger_conditions.append(f"adapter_fallback:{adapter_resolution.fallback_reason.value}")
            recovered_via.append("generic native-first fallback")
        if ScreenLimitationCode.OBSERVATION_UNAVAILABLE in limitation_codes:
            trigger_conditions.append("observation_unavailable")
            unresolved_conditions.append("No reliable live screen observation was available.")
        if ScreenLimitationCode.LOW_CONFIDENCE in limitation_codes:
            trigger_conditions.append("partial_visible_signal")
            unresolved_conditions.append("The visible signal remains partial.")
        if ScreenLimitationCode.PRIOR_OBSERVATION_REQUIRED in limitation_codes:
            trigger_conditions.append("comparison_basis_missing")
            unresolved_conditions.append("A grounded before/after comparison basis is still missing.")

        if verification_result is not None:
            if verification_result.completion_status in {CompletionStatus.AMBIGUOUS, CompletionStatus.BLOCKED, CompletionStatus.DIVERTED}:
                trigger_conditions.append(f"verification_{verification_result.completion_status.value}")
                unresolved_conditions.append(verification_result.explanation.summary or verification_result.comparison.summary)
            if verification_result.comparison.change_classification in {
                ChangeClassification.INSUFFICIENT_EVIDENCE,
                ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD,
            }:
                trigger_conditions.append(f"change_{verification_result.comparison.change_classification.value}")
                unresolved_conditions.append(verification_result.comparison.summary)

        if action_result is not None:
            if action_result.status in {
                ActionExecutionStatus.GATED,
                ActionExecutionStatus.BLOCKED,
                ActionExecutionStatus.AMBIGUOUS,
                ActionExecutionStatus.FAILED,
            }:
                trigger_conditions.append(f"action_{action_result.status.value}")
                unresolved_conditions.append(action_result.explanation_summary or action_result.gate.reason)
            elif action_result.status == ActionExecutionStatus.ATTEMPTED_UNVERIFIED:
                trigger_conditions.append("post_action_verification_weak")
                unresolved_conditions.append("The action was attempted, but the post-action verification remained weak.")

        if continuity_result is not None and continuity_result.status.value in {"detoured", "weak_basis", "blocked", "ambiguous"}:
            trigger_conditions.append(f"continuity_{continuity_result.status.value}")
            unresolved_conditions.append(continuity_result.explanation_summary or continuity_result.status.value.replace("_", " "))

        if problem_solving_result is not None and (
            problem_solving_result.answer_status.value == "refused"
            or problem_solving_result.ambiguity_state.value in {"partial", "ambiguous", "insufficient_evidence"}
        ):
            trigger_conditions.append(f"problem_{problem_solving_result.ambiguity_state.value}")
            unresolved_conditions.append(problem_solving_result.explanation_summary or "Problem interpretation remains incomplete.")

        retry_behavior: str | None = None
        if any(code in limitation_codes for code in {ScreenLimitationCode.OBSERVATION_UNAVAILABLE, ScreenLimitationCode.PRIOR_OBSERVATION_REQUIRED}):
            retry_behavior = "Retry only after a fresh, grounded observation is available."
        elif action_result is not None and action_result.gate.confirmation_required:
            retry_behavior = "Wait for operator confirmation before attempting another direct action."
        elif action_result is not None and action_result.status == ActionExecutionStatus.ATTEMPTED_UNVERIFIED:
            retry_behavior = "Re-check the screen before calling the attempt successful."

        handoff_required = bool(
            ScreenLimitationCode.OBSERVATION_UNAVAILABLE in limitation_codes
            or (action_result is not None and action_result.status in {ActionExecutionStatus.GATED, ActionExecutionStatus.BLOCKED})
        )

        missing_primary_basis = any(
            code in limitation_codes
            for code in {
                ScreenLimitationCode.OBSERVATION_UNAVAILABLE,
                ScreenLimitationCode.PRIOR_OBSERVATION_REQUIRED,
            }
        )

        if unresolved_conditions and recovered_via and not missing_primary_basis:
            status = ScreenRecoveryStatus.PARTIALLY_RECOVERED
            summary = "Stormhelm recovered part of the flow through truthful fallback, but unresolved conditions remain."
        elif unresolved_conditions:
            status = ScreenRecoveryStatus.UNRESOLVED
            summary = "Stormhelm kept the current failure state bounded and unresolved rather than inventing closure."
        elif recovered_via:
            status = ScreenRecoveryStatus.RECOVERED
            summary = "Stormhelm recovered gracefully through native-first fallback without claiming hidden certainty."
        else:
            status = ScreenRecoveryStatus.STEADY
            summary = "No recovery path was needed for the current screen-aware request."

        return ScreenRecoveryState(
            status=status,
            trigger_conditions=trigger_conditions,
            recovered_via=recovered_via,
            unresolved_conditions=unresolved_conditions,
            retry_behavior=retry_behavior,
            handoff_required=handoff_required,
            summary=summary,
        )

    def _build_truthfulness_audit(
        self,
        *,
        analysis: ScreenAnalysisResult,
        response_text: str,
    ) -> ScreenTruthfulnessAudit:
        findings: list[ScreenAuditFinding] = []
        lowered = response_text.lower()
        limitation_codes = {limitation.code for limitation in analysis.limitations}

        if (
            ScreenLimitationCode.OBSERVATION_UNAVAILABLE in limitation_codes
            and not any(token in lowered for token in ("don't have", "can't", "unable", "no reliable"))
        ):
            findings.append(
                ScreenAuditFinding(
                    code="missing_unavailable_language",
                    severity=ScreenAuditSeverity.ERROR,
                    message="The response did not clearly say that live observation was unavailable.",
                    evidence=["response"],
                )
            )

        if analysis.verification_state != ScreenTruthState.OBSERVED and any(token in lowered for token in ("verified", "confirmed")):
            findings.append(
                ScreenAuditFinding(
                    code="unverified_claim_language",
                    severity=ScreenAuditSeverity.WARNING,
                    message="The wording sounds verified even though the structured verification state is not observed.",
                    evidence=["response", "verification_state"],
                )
            )

        if (
            analysis.grounding_result is not None
            and analysis.grounding_result.ambiguity_status == GroundingAmbiguityStatus.AMBIGUOUS
            and not any(token in lowered for token in ("two plausible", "ambiguous", "clarify", "can't justify", "multiple"))
        ):
            findings.append(
                ScreenAuditFinding(
                    code="ambiguity_not_signaled",
                    severity=ScreenAuditSeverity.WARNING,
                    message="The structured grounding result stayed ambiguous, but the wording does not clearly surface that ambiguity.",
                    evidence=["response", "grounding_result"],
                )
            )

        if analysis.action_result is not None and analysis.action_result.status != ActionExecutionStatus.VERIFIED_SUCCESS:
            if any(phrase in lowered for phrase in ("i clicked", "i pressed", "i typed", "i scrolled")) and "attempt" not in lowered:
                findings.append(
                    ScreenAuditFinding(
                        code="attempted_action_worded_as_done",
                        severity=ScreenAuditSeverity.ERROR,
                        message="The response sounds like a completed action even though execution was not verified successful.",
                        evidence=["response", "action_result"],
                    )
                )

        if analysis.recovery_state is not None and analysis.recovery_state.status == ScreenRecoveryStatus.UNRESOLVED:
            if any(token in lowered for token in ("resolved", "back on track", "fixed")):
                findings.append(
                    ScreenAuditFinding(
                        code="unresolved_state_overclaimed",
                        severity=ScreenAuditSeverity.ERROR,
                        message="The wording implies resolution even though the structured recovery state remains unresolved.",
                        evidence=["response", "recovery_state"],
                    )
                )

        if analysis.confidence.score < 0.7 and any(token in lowered for token in ("definitely", "certainly", "guaranteed")):
            findings.append(
                ScreenAuditFinding(
                    code="tone_outpaces_confidence",
                    severity=ScreenAuditSeverity.WARNING,
                    message="The wording sounds more certain than the structured confidence supports.",
                    evidence=["response", "confidence"],
                )
            )

        error_count = sum(1 for finding in findings if finding.severity == ScreenAuditSeverity.ERROR)
        warning_count = sum(1 for finding in findings if finding.severity == ScreenAuditSeverity.WARNING)
        if not findings:
            summary = "No truthfulness issues detected."
        else:
            summary = f"Truthfulness audit found {error_count} error(s) and {warning_count} warning(s)."
        return ScreenTruthfulnessAudit(
            passed=error_count == 0,
            findings=findings,
            summary=summary,
        )

    def _record_trace_summary(
        self,
        *,
        trace_id: str,
        intent: ScreenIntentType,
        analysis: ScreenAnalysisResult,
    ) -> None:
        if not self._phase12_enabled() or analysis.latency_trace is None:
            return
        self._recent_trace_summaries.append(
            {
                "trace_id": trace_id,
                "intent": intent.value,
                "phase": self.config.phase,
                "confidence": analysis.confidence.to_dict(),
                "verification_state": analysis.verification_state.value,
                "fallback_reason": analysis.fallback_reason,
                "total_duration_ms": analysis.latency_trace.total_duration_ms,
                "slowest_stage": analysis.latency_trace.slowest_stage,
                "audit_passed": analysis.truthfulness_audit.passed if analysis.truthfulness_audit is not None else True,
                "audit_error_count": analysis.truthfulness_audit.error_count if analysis.truthfulness_audit is not None else 0,
                "audit_warning_count": analysis.truthfulness_audit.warning_count if analysis.truthfulness_audit is not None else 0,
                "recovery_status": analysis.recovery_state.status.value if analysis.recovery_state is not None else None,
            }
        )

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
        hardening_enabled = self._phase12_enabled()
        trace_id = f"screen-{uuid4().hex}"
        request_started = monotonic()
        stage_timings: list[ScreenStageTiming] = []

        def record_stage(stage: str, stage_started: float, *, status: str = "completed", note: str = "") -> None:
            if not hardening_enabled:
                return
            stage_timings.append(
                ScreenStageTiming(
                    stage=stage,
                    duration_ms=round((monotonic() - stage_started) * 1000.0, 3),
                    status=status,
                    note=note,
                )
            )

        def skip_stage(stage: str, note: str) -> None:
            if not hardening_enabled:
                return
            stage_timings.append(ScreenStageTiming(stage=stage, duration_ms=0.0, status="skipped", note=note))

        stage_started = monotonic()
        observation = self.native_observer.observe(
            session_id=session_id,
            surface_mode=surface_mode,
            active_module=active_module,
            active_context=active_context,
            workspace_context=workspace_context,
        )
        record_stage("observation", stage_started)
        stage_started = monotonic()
        interpretation = self.interpreter.interpret(observation, operator_text=operator_text)
        record_stage("interpretation", stage_started)
        stage_started = monotonic()
        current_screen_context = self.context_synthesizer.synthesize(observation, interpretation)
        record_stage("context_synthesis", stage_started)
        adapter_resolution: AppAdapterResolution | None = None
        if self.config.capability_flags().get("adapters_enabled"):
            stage_started = monotonic()
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
            record_stage("adapter_resolution", stage_started)
        else:
            skip_stage("adapter_resolution", "adapter semantics are not enabled for the active phase")
        grounding_result: GroundingOutcome | None = None
        navigation_result: NavigationOutcome | None = None
        verification_result: VerificationOutcome | None = None
        action_result: ActionExecutionResult | None = None
        continuity_result: WorkflowContinuityResult | None = None
        problem_solving_result: ProblemSolvingResult | None = None
        workflow_learning_result: WorkflowLearningResult | None = None
        brain_integration_result: BrainIntegrationResult | None = None
        power_features_result: PowerFeaturesResult | None = None
        calculation_activity = None

        limitations: list[ScreenLimitation] = []
        fallback_reason: str | None = None
        if not has_direct_screen_signal(observation):
            limitations.append(
                ScreenLimitation(
                    code=ScreenLimitationCode.OBSERVATION_UNAVAILABLE,
                    message="No reliable focused window, selected text, or grounded workspace surface was available.",
                    truth_state=ScreenTruthState.UNAVAILABLE,
                )
            )
            fallback_reason = "observation_unavailable"
        elif not observation.selected_text and not best_live_visible_text(observation):
            limitations.append(
                ScreenLimitation(
                    code=ScreenLimitationCode.LOW_CONFIDENCE,
                    message="The visible signal is partial because no direct selected text or live visible cue was available.",
                    truth_state=ScreenTruthState.UNVERIFIED,
                )
            )
        if adapter_resolution is not None and adapter_resolution.fallback_reason is not None and fallback_reason is None:
            fallback_reason = adapter_resolution.fallback_reason.value

        if intent == ScreenIntentType.DETECT_VISIBLE_CHANGE and not (
            self.config.phase in {"phase4", "phase5", "phase6", "phase7", "phase8", "phase9", "phase10", "phase11", "phase12"}
            and self.config.verification_enabled
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
        if self.config.phase in {"phase2", "phase3", "phase4", "phase5", "phase6", "phase7", "phase8", "phase9", "phase10", "phase11", "phase12"} and self.config.grounding_enabled and not any(
            limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations
        ):
            stage_started = monotonic()
            grounding_result = self.grounding_engine.resolve(
                operator_text=operator_text,
                intent=intent,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
            )
            record_stage("grounding", stage_started)
        else:
            skip_stage("grounding", "grounding was not applicable for the active phase, capability state, or observation quality")
        if (
            self.config.phase in {"phase3", "phase4", "phase5", "phase6", "phase7", "phase8", "phase9", "phase10", "phase11", "phase12"}
            and self.config.guidance_enabled
            and intent in {ScreenIntentType.GUIDE_NAVIGATION, ScreenIntentType.EXECUTE_UI_ACTION, ScreenIntentType.LEARN_WORKFLOW_REUSE}
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            stage_started = monotonic()
            navigation_result = self.navigation_engine.resolve(
                operator_text=operator_text,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
                grounding_result=grounding_result,
            )
            record_stage("navigation", stage_started)
        else:
            skip_stage("navigation", "guided-navigation resolution was not applicable for this request")
        if (
            self.config.phase in {"phase4", "phase5", "phase6", "phase7", "phase8", "phase9", "phase10", "phase11", "phase12"}
            and self.config.verification_enabled
            and intent != ScreenIntentType.EXECUTE_UI_ACTION
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            stage_started = monotonic()
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
            record_stage("verification", stage_started)
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
        else:
            skip_stage("verification", "verification was not applicable for this request or the active phase")

        if (
            intent == ScreenIntentType.SOLVE_VISIBLE_PROBLEM
            and self.config.phase not in {"phase8", "phase9", "phase10", "phase11", "phase12"}
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            preferred_text = (
                grounding_result.winning_target.visible_text
                if grounding_result is not None and grounding_result.winning_target is not None
                else None
            )
            stage_started = monotonic()
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
            record_stage("calculation_overlay", stage_started)
        else:
            skip_stage("calculation_overlay", "no standalone calculation overlay was needed for this request")

        if (
            self.config.phase in {"phase5", "phase6", "phase7", "phase8", "phase9", "phase10", "phase11", "phase12"}
            and self.config.action_enabled
            and intent == ScreenIntentType.EXECUTE_UI_ACTION
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            stage_started = monotonic()
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
            record_stage("action_execution", stage_started)
        else:
            skip_stage("action_execution", "direct action execution was not applicable for this request")

        if (
            self.config.phase in {"phase11", "phase12"}
            and self.config.capability_flags().get("power_features_enabled")
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            stage_started = monotonic()
            power_features_result = self.power_features_engine.assess(
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
                active_context=active_context,
                workspace_context=workspace_context,
            )
            record_stage("power_features", stage_started)
        else:
            skip_stage("power_features", "power-feature enrichment was not applicable for this request")

        if (
            self.config.phase in {"phase6", "phase7", "phase8", "phase9", "phase10", "phase11", "phase12"}
            and self.config.memory_enabled
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            stage_started = monotonic()
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
            record_stage("continuity", stage_started)
        else:
            skip_stage("continuity", "workflow continuity was not applicable for this request")

        if (
            self.config.phase in {"phase8", "phase9", "phase10", "phase11", "phase12"}
            and self.config.capability_flags().get("problem_solving_enabled")
            and intent in {ScreenIntentType.EXPLAIN_VISIBLE_CONTENT, ScreenIntentType.SOLVE_VISIBLE_PROBLEM}
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            stage_started = monotonic()
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
            record_stage("problem_solving", stage_started)
        else:
            skip_stage("problem_solving", "problem-solving expansion was not applicable for this request")

        if (
            self.config.phase in {"phase9", "phase10", "phase11", "phase12"}
            and self.config.capability_flags().get("workflow_learning_enabled")
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            stage_started = monotonic()
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
            record_stage("workflow_learning", stage_started)
        else:
            skip_stage("workflow_learning", "workflow-learning reuse was not applicable for this request")

        if (
            self.config.phase in {"phase10", "phase11", "phase12"}
            and self.config.capability_flags().get("brain_integration_enabled")
            and not any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations)
        ):
            stage_started = monotonic()
            brain_integration_result = self.brain_integration_engine.assess(
                session_id=session_id,
                operator_text=operator_text,
                intent=intent,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
                grounding_result=grounding_result,
                verification_result=verification_result,
                action_result=action_result,
                continuity_result=continuity_result,
                workflow_learning_result=workflow_learning_result,
                adapter_resolution=adapter_resolution,
                active_context=active_context,
                workspace_context=workspace_context,
            )
            record_stage("brain_integration", stage_started)
        else:
            skip_stage("brain_integration", "brain-integration memory binding was not applicable for this request")

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
        if brain_integration_result is not None:
            confidence_scores.append(brain_integration_result.confidence.score)
        if power_features_result is not None:
            confidence_scores.append(power_features_result.confidence.score)
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

        policy_state = self._policy_state() if hardening_enabled else None
        recovery_state = (
            self._build_recovery_state(
                limitations=limitations,
                adapter_resolution=adapter_resolution,
                verification_result=verification_result,
                action_result=action_result,
                continuity_result=continuity_result,
                problem_solving_result=problem_solving_result,
            )
            if hardening_enabled
            else None
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
            brain_integration_result=brain_integration_result,
            power_features_result=power_features_result,
            calculation_activity=calculation_activity,
            limitations=limitations,
            fallback_reason=fallback_reason,
            confidence=ScreenConfidence(
                score=overall_score,
                level=confidence_level_for_score(overall_score),
                note="Overall screen-awareness confidence blends native observation, interpretation, and context synthesis.",
            ),
            trace_id=trace_id if hardening_enabled else None,
            policy_state=policy_state,
            recovery_state=recovery_state,
            truthfulness_contract=self.truthfulness_contract,
            verification_state=verification_state,
        )
        stage_started = monotonic()
        response = self.response_composer.compose(intent=intent, analysis=analysis)
        record_stage("response_composition", stage_started)
        if hardening_enabled:
            total_duration_ms = round((monotonic() - request_started) * 1000.0, 3)
            slowest_stage = max(stage_timings, key=lambda item: item.duration_ms).stage if stage_timings else None
            analysis.latency_trace = ScreenLatencyTrace(
                trace_id=trace_id,
                total_duration_ms=total_duration_ms,
                stage_timings=stage_timings,
                slowest_stage=slowest_stage,
                notes=["Stage timings cover executed work and explicit skipped branches."],
            )
        if hardening_enabled:
            analysis.truthfulness_audit = self._build_truthfulness_audit(
                analysis=analysis,
                response_text=response.assistant_response,
            )
            self._record_trace_summary(trace_id=trace_id, intent=intent, analysis=analysis)
        response.telemetry.update(
            {
                "route": {"intent": intent.value, "surface_mode": surface_mode, "active_module": active_module},
                "visual_augmentation": self._visual_augmentation_status(observation),
                "grounding_visual_augmentation": self.grounding_engine.provider_grounding_status(observation),
                "trace": {
                    "trace_id": trace_id if hardening_enabled else None,
                    "phase": self.config.phase,
                    "slowest_stage": analysis.latency_trace.slowest_stage if analysis.latency_trace is not None else None,
                },
                "timing": analysis.latency_trace.to_dict() if analysis.latency_trace is not None else None,
                "truthfulness_audit": analysis.truthfulness_audit.to_dict() if analysis.truthfulness_audit is not None else None,
                "policy": analysis.policy_state.to_dict() if analysis.policy_state is not None else None,
                "recovery": analysis.recovery_state.to_dict() if analysis.recovery_state is not None else None,
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
