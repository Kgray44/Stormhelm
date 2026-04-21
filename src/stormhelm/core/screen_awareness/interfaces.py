from __future__ import annotations

from typing import Any, Protocol

from stormhelm.core.screen_awareness.models import CurrentScreenContext
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import GroundingRequest
from stormhelm.core.screen_awareness.models import ScreenAnalysisResult
from stormhelm.core.screen_awareness.models import ScreenInterpretation
from stormhelm.core.screen_awareness.models import ScreenObservation


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
    def guide(self, context: CurrentScreenContext) -> dict[str, Any]: ...


class ActionExecutor(Protocol):
    def execute(self, action: dict[str, Any]) -> dict[str, Any]: ...


class VerificationEngine(Protocol):
    def verify(self, analysis: ScreenAnalysisResult) -> dict[str, Any]: ...


class MemoryIntegrator(Protocol):
    def integrate(self, analysis: ScreenAnalysisResult) -> dict[str, Any]: ...


class EnvironmentAdapter(Protocol):
    adapter_name: str

    def enrich(self, analysis: ScreenAnalysisResult) -> ScreenAnalysisResult: ...
