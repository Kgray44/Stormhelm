from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.screen_awareness.models import ScreenAnalysisResult
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenRouteDisposition


INSPECTION_PHRASES = {
    "what am i looking at",
    "what is on my screen",
    "what's on my screen",
    "what is this",
    "what is that",
    "which button are you talking about",
    "which checkbox are you talking about",
    "what page is this",
    "what page am i on",
    "summarize what is on my screen",
    "summarize what's on my screen",
}
EXPLANATION_PHRASES = {
    "what does this mean",
    "what does this warning mean",
    "what does that popup mean",
    "what error is this",
    "what is this warning",
    "what is this popup",
    "explain the selected field",
    "is this the problem",
    "explain this",
    "what does this settings page do",
}
SOLVE_PHRASES = {
    "can you solve this",
    "solve this on my screen",
}
NAVIGATION_PHRASES = {
    "what should i click next",
    "where do i go from here",
    "i'm stuck",
    "im stuck",
    "i am stuck",
    "what do i do now",
    "is this the right page",
    "which field am i supposed to use",
    "which button am i supposed to use",
    "how do i get to the next step",
    "i think i'm in the wrong place",
    "i think im in the wrong place",
    "what am i looking for on this screen",
    "walk me through this",
}
VERIFICATION_PHRASES = {
    "did that work",
    "did it work",
    "did anything change",
    "am i done with this step",
    "did that button actually do anything",
    "did the error go away",
    "is this the page i was trying to get to",
    "what is still preventing me from continuing",
    "what is still blocking me",
    "is it still loading",
    "do these numbers add up",
    "do these values add up",
    "does this add up",
    "does this total add up",
    "is this total right",
    "what do these add up to",
    "double check this total",
}
CHANGE_PHRASES = {
    "what changed",
    "what changed on my screen",
    "did this change",
}
ACTION_PHRASES = {
    "click that button",
    "click save",
    "click the save button",
    "press continue",
    "scroll down a bit",
    "open that dropdown",
    "press enter here",
    "go ahead and do it",
}
CONTINUITY_PHRASES = {
    "continue where we left off",
    "what was i doing here",
    "what was i just doing",
    "this popup interrupted me",
    "what step was next",
    "i think i went backward",
    "where was i supposed to be",
    "how do i recover from this",
    "help me resume this workflow",
    "how do i get back to the thing i was just doing",
}
_CONFIRMATION_FOLLOW_UPS = {"go ahead", "do it", "proceed", "confirm it"}
VISUAL_REFERENT_HINTS = {
    "screen",
    "page",
    "window",
    "dialog",
    "popup",
    "button",
    "checkbox",
    "dropdown",
    "warning",
    "error",
}
DEICTIC_HINTS = {"this", "that", "these", "those"}
INSPECTION_MARKERS = {
    "what ",
    "what's",
    "what is",
    "which ",
    "explain",
    "describe",
    "summarize",
    "why ",
    "can you",
}
ACTION_VERBS = {"click", "press", "type", "enter", "fill", "focus", "select", "scroll", "hover", "open"}


@dataclass(slots=True)
class ScreenPlannerEvaluation:
    candidate: bool
    disposition: ScreenRouteDisposition
    intent: ScreenIntentType | None = None
    reasons: list[str] = field(default_factory=list)
    feature_enabled: bool = False
    planner_routing_enabled: bool = False
    route_confidence: float = 0.0
    input_signals: dict[str, Any] = field(default_factory=dict)
    analysis_result: ScreenAnalysisResult | None = None
    response_contract: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "disposition": self.disposition.value,
            "intent": self.intent.value if self.intent is not None else None,
            "reasons": list(self.reasons),
            "feature_enabled": self.feature_enabled,
            "planner_routing_enabled": self.planner_routing_enabled,
            "route_confidence": self.route_confidence,
            "input_signals": dict(self.input_signals),
            "analysis_result": self.analysis_result.to_dict() if self.analysis_result is not None else None,
            "response_contract": dict(self.response_contract),
        }


class ScreenAwarenessPlannerSeam:
    def __init__(self, config: ScreenAwarenessConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        raw_text: str,
        normalized_text: str,
        surface_mode: str,
        active_module: str,
        active_context: dict[str, Any] | None,
    ) -> ScreenPlannerEvaluation:
        del raw_text
        active_context = active_context or {}
        input_signals = {
            "surface_mode": surface_mode,
            "active_module": active_module,
            "selection_available": bool(
                isinstance(active_context.get("selection"), dict) and active_context["selection"].get("value")
            ),
            "clipboard_available": bool(
                isinstance(active_context.get("clipboard"), dict) and active_context["clipboard"].get("value")
            ),
            "workspace_available": bool(active_context.get("workspace")),
            "recent_screen_resolution_available": self._has_recent_screen_resolution(active_context),
        }
        intent, reasons, route_confidence = self._detect_intent(normalized_text, input_signals=input_signals)
        if intent is None:
            return ScreenPlannerEvaluation(
                candidate=False,
                disposition=ScreenRouteDisposition.NOT_REQUESTED,
                feature_enabled=self.config.enabled,
                planner_routing_enabled=self.config.planner_routing_enabled,
                input_signals=input_signals,
            )

        if not self.config.enabled:
            return ScreenPlannerEvaluation(
                candidate=True,
                disposition=ScreenRouteDisposition.FEATURE_DISABLED,
                intent=intent,
                reasons=reasons,
                feature_enabled=False,
                planner_routing_enabled=self.config.planner_routing_enabled,
                route_confidence=route_confidence,
                input_signals=input_signals,
            )

        if not self.config.planner_routing_enabled:
            return ScreenPlannerEvaluation(
                candidate=True,
                disposition=ScreenRouteDisposition.ROUTING_DISABLED,
                intent=intent,
                reasons=reasons,
                feature_enabled=True,
                planner_routing_enabled=False,
                route_confidence=route_confidence,
                input_signals=input_signals,
            )

        if self.config.observation_enabled and self.config.interpretation_enabled and self.config.phase != "phase0":
            disposition = ScreenRouteDisposition.PHASE1_ANALYZE
            if intent == ScreenIntentType.EXECUTE_UI_ACTION and self.config.phase in {"phase5", "phase6"}:
                disposition = ScreenRouteDisposition.PHASE5_ACT
            elif (
                intent == ScreenIntentType.CONTINUE_WORKFLOW
                and self.config.phase == "phase6"
                and self.config.memory_enabled
            ):
                disposition = ScreenRouteDisposition.PHASE6_CONTINUE
            elif intent == ScreenIntentType.GUIDE_NAVIGATION and self.config.phase in {"phase3", "phase4", "phase5", "phase6"} and self.config.guidance_enabled:
                disposition = ScreenRouteDisposition.PHASE3_GUIDE
            elif intent in {ScreenIntentType.VERIFY_SCREEN_STATE, ScreenIntentType.DETECT_VISIBLE_CHANGE} and self.config.phase in {"phase4", "phase5", "phase6"} and self.config.verification_enabled:
                disposition = ScreenRouteDisposition.PHASE4_VERIFY
            elif self.config.phase in {"phase2", "phase3", "phase4", "phase5", "phase6"} and self.config.grounding_enabled:
                disposition = ScreenRouteDisposition.PHASE2_GROUND
            return ScreenPlannerEvaluation(
                candidate=True,
                disposition=disposition,
                intent=intent,
                reasons=reasons,
                feature_enabled=True,
                planner_routing_enabled=True,
                route_confidence=route_confidence,
                input_signals=input_signals,
                response_contract={
                    "bearing_title": (
                        "Action Bearings"
                        if disposition == ScreenRouteDisposition.PHASE5_ACT
                        else
                        "Continuity Bearings"
                        if disposition == ScreenRouteDisposition.PHASE6_CONTINUE
                        else
                        "Guided Bearings"
                        if disposition == ScreenRouteDisposition.PHASE3_GUIDE
                        else "Verification Bearings"
                        if disposition == ScreenRouteDisposition.PHASE4_VERIFY
                        else "Screen Bearings"
                    ),
                },
            )

        return ScreenPlannerEvaluation(
            candidate=True,
            disposition=ScreenRouteDisposition.PHASE0_SCAFFOLD,
            intent=intent,
            reasons=reasons,
            feature_enabled=True,
            planner_routing_enabled=True,
            route_confidence=route_confidence,
            input_signals=input_signals,
            analysis_result=ScreenAnalysisResult.phase_zero_placeholder(
                intent=intent,
                surface_mode=surface_mode,
                active_module=active_module,
            ),
            response_contract={
                "bearing_title": "Screen awareness offline",
                "micro_response": "Live screen bearings aren't available yet.",
                "full_response": (
                    "Screen bearings aren't available yet in this phase. "
                    "The foundation is in place, but live observation has not been brought online."
                ),
            },
        )

    def _detect_intent(
        self,
        normalized_text: str,
        *,
        input_signals: dict[str, Any],
    ) -> tuple[ScreenIntentType | None, list[str], float]:
        lower = normalized_text.strip()
        if not lower:
            return None, [], 0.0

        if any(phrase in lower for phrase in CONTINUITY_PHRASES):
            return ScreenIntentType.CONTINUE_WORKFLOW, ["explicit workflow-continuity phrase matched"], 0.96
        if any(phrase in lower for phrase in NAVIGATION_PHRASES):
            return ScreenIntentType.GUIDE_NAVIGATION, ["explicit guided-navigation phrase matched"], 0.95
        if any(phrase in lower for phrase in VERIFICATION_PHRASES):
            return ScreenIntentType.VERIFY_SCREEN_STATE, ["explicit verification phrase matched"], 0.94
        if any(phrase in lower for phrase in ACTION_PHRASES):
            return ScreenIntentType.EXECUTE_UI_ACTION, ["explicit direct-action phrase matched"], 0.95
        if any(phrase in lower for phrase in INSPECTION_PHRASES):
            return ScreenIntentType.INSPECT_VISIBLE_STATE, ["explicit screen inspection phrase matched"], 0.96
        if any(phrase in lower for phrase in CHANGE_PHRASES):
            return ScreenIntentType.DETECT_VISIBLE_CHANGE, ["explicit screen change phrase matched"], 0.91
        if any(phrase in lower for phrase in EXPLANATION_PHRASES) and (
            input_signals.get("selection_available")
            or input_signals.get("clipboard_available")
            or self._contains_visible_referent(lower)
        ):
            return ScreenIntentType.EXPLAIN_VISIBLE_CONTENT, ["explicit visible-content explanation phrase matched"], 0.93
        if any(phrase in lower for phrase in SOLVE_PHRASES) and (
            input_signals.get("selection_available")
            or input_signals.get("clipboard_available")
            or self._contains_visible_referent(lower)
        ):
            return ScreenIntentType.SOLVE_VISIBLE_PROBLEM, ["explicit visible-problem phrase matched"], 0.9
        if any(phrase in lower for phrase in {"which button", "which checkbox", "selected field", "is this the problem"}):
            return ScreenIntentType.INSPECT_VISIBLE_STATE, ["grounding-oriented referential phrase matched"], 0.9
        if self._looks_like_action_request(lower, input_signals=input_signals):
            return ScreenIntentType.EXECUTE_UI_ACTION, ["explicit direct-action verb matched against the current screen context"], 0.88

        if (
            self._looks_like_visual_inspection_request(lower)
            and self._contains_visible_referent(lower)
            and (
                any(re.search(rf"\b{re.escape(token)}\b", lower) for token in DEICTIC_HINTS)
                or lower.startswith("which ")
            )
        ):
            return ScreenIntentType.INSPECT_VISIBLE_STATE, ["deictic phrase includes a visible-surface referent"], 0.72
        return None, [], 0.0

    def _has_recent_screen_resolution(self, active_context: dict[str, Any]) -> bool:
        recent = active_context.get("recent_context_resolutions")
        if not isinstance(recent, list):
            return False
        return any(isinstance(item, dict) and str(item.get("kind") or "").strip() == "screen_awareness" for item in recent)

    def _contains_visible_referent(self, normalized_text: str) -> bool:
        return any(re.search(rf"\b{re.escape(hint)}\b", normalized_text) for hint in VISUAL_REFERENT_HINTS)

    def _looks_like_visual_inspection_request(self, normalized_text: str) -> bool:
        return any(marker in normalized_text for marker in INSPECTION_MARKERS)

    def _looks_like_action_request(self, normalized_text: str, *, input_signals: dict[str, Any]) -> bool:
        tokens = normalized_text.split()
        if not tokens:
            return False
        if tokens[0] in ACTION_VERBS and (
            self._contains_visible_referent(normalized_text)
            or any(token in {"this", "that", "it", "here"} for token in tokens)
        ):
            return True
        if input_signals.get("recent_screen_resolution_available") and any(
            phrase in normalized_text for phrase in _CONFIRMATION_FOLLOW_UPS
        ):
            return True
        return False
