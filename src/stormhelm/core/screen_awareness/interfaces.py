from __future__ import annotations

from typing import Any, Protocol

from stormhelm.core.screen_awareness.models import CurrentScreenContext
from stormhelm.core.screen_awareness.models import ActionPlan
from stormhelm.core.screen_awareness.models import ActionExecutionResult
from stormhelm.core.screen_awareness.models import AppAdapterResolution
from stormhelm.core.screen_awareness.models import BrainIntegrationResult
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import GroundingRequest
from stormhelm.core.screen_awareness.models import NavigationOutcome
from stormhelm.core.screen_awareness.models import ProblemSolvingResult
from stormhelm.core.screen_awareness.models import ScreenAnalysisResult
from stormhelm.core.screen_awareness.models import ScreenInterpretation
from stormhelm.core.screen_awareness.models import ScreenObservation
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import PowerFeaturesResult
from stormhelm.core.screen_awareness.models import VerificationOutcome
from stormhelm.core.screen_awareness.models import WorkflowContinuityResult
from stormhelm.core.screen_awareness.models import WorkflowLearningResult


class ObservationSource(Protocol):
    name: str

    def observe(
        self,
        *,
        session_id: str,
        surface_mode: str,
        active_module: str,
        active_context: dict[str, Any],
    ) -> ScreenObservation: ...


class InterpretationEngine(Protocol):
    def interpret(self, observation: ScreenObservation) -> ScreenInterpretation: ...


class ContextSynthesizer(Protocol):
    def synthesize(
        self,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
    ) -> CurrentScreenContext: ...


class GroundingResolver(Protocol):
    def resolve(
        self,
        *,
        operator_text: str,
        context: CurrentScreenContext,
        request: GroundingRequest,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
    ) -> GroundingOutcome | None: ...


class GuidanceEngine(Protocol):
    def guide(
        self,
        *,
        operator_text: str,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
    ) -> NavigationOutcome | None: ...


class ActionExecutor(Protocol):
    def execute_plan(self, *, plan: ActionPlan) -> dict[str, Any]: ...


class VerificationEngine(Protocol):
    def verify(
        self,
        *,
        operator_text: str,
        intent: ScreenIntentType,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        active_context: dict[str, Any] | None,
    ) -> VerificationOutcome | None: ...


class WorkflowContinuityEngine(Protocol):
    def assess(
        self,
        *,
        operator_text: str,
        intent: ScreenIntentType,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        verification_result: VerificationOutcome | None,
        action_result: ActionExecutionResult | None,
        active_context: dict[str, Any] | None,
    ) -> WorkflowContinuityResult | None: ...


class ProblemSolvingEngine(Protocol):
    def solve(
        self,
        *,
        session_id: str,
        operator_text: str,
        intent: ScreenIntentType,
        surface_mode: str,
        active_module: str,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        verification_result: VerificationOutcome | None,
        action_result: ActionExecutionResult | None,
        continuity_result: WorkflowContinuityResult | None,
        adapter_resolution: AppAdapterResolution | None,
        active_context: dict[str, Any] | None,
    ) -> ProblemSolvingResult | None: ...


class WorkflowLearningEngine(Protocol):
    def assess(
        self,
        *,
        session_id: str,
        operator_text: str,
        intent: ScreenIntentType,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        verification_result: VerificationOutcome | None,
        action_result: ActionExecutionResult | None,
        active_context: dict[str, Any] | None,
    ) -> WorkflowLearningResult | None: ...


class BrainIntegrationEngine(Protocol):
    def assess(
        self,
        *,
        session_id: str,
        operator_text: str,
        intent: ScreenIntentType,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        verification_result: VerificationOutcome | None,
        action_result: ActionExecutionResult | None,
        continuity_result: WorkflowContinuityResult | None,
        workflow_learning_result: WorkflowLearningResult | None,
        adapter_resolution: AppAdapterResolution | None,
        active_context: dict[str, Any] | None,
        workspace_context: dict[str, Any] | None,
    ) -> BrainIntegrationResult | None: ...


class PowerFeaturesEngine(Protocol):
    def assess(
        self,
        *,
        operator_text: str,
        intent: ScreenIntentType,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        verification_result: VerificationOutcome | None,
        action_result: ActionExecutionResult | None,
        continuity_result: WorkflowContinuityResult | None,
        adapter_resolution: AppAdapterResolution | None,
        active_context: dict[str, Any] | None,
        workspace_context: dict[str, Any] | None,
    ) -> PowerFeaturesResult | None: ...


class MemoryIntegrator(Protocol):
    def integrate(self, analysis: ScreenAnalysisResult) -> dict[str, Any]: ...


class EnvironmentAdapter(Protocol):
    adapter_name: str

    def enrich(self, analysis: ScreenAnalysisResult) -> ScreenAnalysisResult: ...


class SemanticAdapter(Protocol):
    adapter_id: str

    def resolve(
        self,
        *,
        observation: ScreenObservation,
        payload: dict[str, Any],
    ) -> AppAdapterResolution: ...
