from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.screen_awareness.grounding import DeterministicGroundingEngine
from stormhelm.core.screen_awareness.interpretation import DeterministicContextSynthesizer
from stormhelm.core.screen_awareness.interpretation import DeterministicScreenInterpreter
from stormhelm.core.screen_awareness.models import ScreenAnalysisResult
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenLimitation
from stormhelm.core.screen_awareness.models import ScreenLimitationCode
from stormhelm.core.screen_awareness.models import ScreenResponse
from stormhelm.core.screen_awareness.models import ScreenTruthState
from stormhelm.core.screen_awareness.models import ScreenTruthfulnessContract
from stormhelm.core.screen_awareness.models import confidence_level_for_score
from stormhelm.core.screen_awareness.observation import NativeContextObservationSource
from stormhelm.core.screen_awareness.observation import best_visible_text
from stormhelm.core.screen_awareness.observation import has_direct_screen_signal
from stormhelm.core.screen_awareness.planner import ScreenAwarenessPlannerSeam
from stormhelm.core.screen_awareness.response import ScreenResponseComposer


@dataclass(slots=True)
class ScreenAwarenessSubsystem:
    config: ScreenAwarenessConfig
    system_probe: Any | None = None
    provider: Any | None = None
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
    response_composer: ScreenResponseComposer = field(default_factory=ScreenResponseComposer)

    def __post_init__(self) -> None:
        self.planner_seam = ScreenAwarenessPlannerSeam(self.config)
        self.native_observer = NativeContextObservationSource(system_probe=self.system_probe)
        self.grounding_engine = DeterministicGroundingEngine(provider=self.provider)

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "phase": self.config.phase,
            "enabled": self.config.enabled,
            "planner_routing_enabled": self.config.planner_routing_enabled,
            "debug_events_enabled": self.config.debug_events_enabled,
            "capabilities": self.config.capability_flags(),
            "truthfulness_contract": self.truthfulness_contract.to_dict(),
            "extension_points": dict(self.extension_points),
            "runtime_hooks": {
                "native_observer_ready": True,
                "grounding_engine_ready": True,
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

        if intent == ScreenIntentType.DETECT_VISIBLE_CHANGE:
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
        overall_score = mean(confidence_scores) if confidence_scores else 0.0
        if any(limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations):
            overall_score = 0.0
        elif any(limitation.code == ScreenLimitationCode.LOW_CONFIDENCE for limitation in limitations):
            overall_score = min(overall_score, 0.45)

        if self.config.phase == "phase2" and self.config.grounding_enabled and not any(
            limitation.code == ScreenLimitationCode.OBSERVATION_UNAVAILABLE for limitation in limitations
        ):
            grounding_result = self.grounding_engine.resolve(
                operator_text=operator_text,
                intent=intent,
                observation=observation,
                interpretation=interpretation,
                current_context=current_screen_context,
            )

        analysis = ScreenAnalysisResult(
            observation=observation,
            interpretation=interpretation,
            current_screen_context=current_screen_context,
            grounding_result=grounding_result,
            limitations=limitations,
            fallback_reason=fallback_reason,
            confidence=ScreenConfidence(
                score=overall_score,
                level=confidence_level_for_score(overall_score),
                note="Overall screen-awareness confidence blends native observation, interpretation, and context synthesis.",
            ),
            truthfulness_contract=self.truthfulness_contract,
            verification_state=ScreenTruthState.UNVERIFIED,
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
) -> ScreenAwarenessSubsystem:
    return ScreenAwarenessSubsystem(config=config, system_probe=system_probe, provider=provider)
