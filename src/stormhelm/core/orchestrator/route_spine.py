from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from stormhelm.core.orchestrator.intent_frame import IntentFrame
from stormhelm.core.orchestrator.intent_frame import IntentFrameExtractor
from stormhelm.core.orchestrator.route_family_specs import RouteFamilySpec
from stormhelm.core.orchestrator.route_family_specs import default_route_family_specs


MIGRATED_ROUTE_FAMILIES = {
    "calculations",
    "browser_destination",
    "app_control",
    "window_control",
    "file",
    "context_action",
    "screen_awareness",
    "watch_runtime",
    "network",
    "machine",
    "resources",
    "power",
    "software_control",
    "unsupported",
    "discord_relay",
    "routine",
    "comparison",
    "trust_approvals",
    "file_operation",
    "task_continuity",
    "workspace_operations",
    "workflow",
    "maintenance",
    "terminal",
    "desktop_search",
    "software_recovery",
}


def _workspace_conceptual_text(text: str) -> bool:
    if re.search(r"\bworkspace\b.{0,28}\b(?:philosoph|theory|ideas?)\b", text):
        return True
    return "workspace" in text and bool(re.search(r"\binspiration\b.{0,16}\bboard\b", text))


@dataclass(frozen=True, slots=True)
class RouteSpecCandidate:
    route_family: str
    subsystem: str
    score: float
    selected: bool = False
    accepted: bool = False
    missing_preconditions: tuple[str, ...] = ()
    score_factors: dict[str, float] = field(default_factory=dict)
    positive_reasons: tuple[str, ...] = ()
    decline_reasons: tuple[str, ...] = ()
    tool_candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RouteSpineWinner:
    route_family: str
    subsystem: str = ""
    score: float = 0.0
    result_state: str = "routed"
    tool_candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RouteSpineDecision:
    routing_engine: str
    intent_frame: IntentFrame
    winner: RouteSpineWinner
    candidate_specs_considered: tuple[str, ...] = ()
    candidates: tuple[RouteSpecCandidate, ...] = ()
    selected_route_spec: str = ""
    native_decline_reasons: dict[str, list[str]] = field(default_factory=dict)
    generic_provider_allowed: bool = False
    generic_provider_gate_reason: str = ""
    generic_provider_reason: str = ""
    clarification_needed: bool = False
    clarification_text: str = ""
    missing_preconditions: tuple[str, ...] = ()
    tool_candidates: list[str] = field(default_factory=list)
    legacy_fallback_used: bool = False
    authoritative: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "routing_engine": self.routing_engine,
            "intent_frame": self.intent_frame.to_dict(),
            "winner": self.winner.to_dict(),
            "candidate_specs_considered": list(self.candidate_specs_considered),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected_route_spec": self.selected_route_spec,
            "native_decline_reasons": {key: list(value) for key, value in self.native_decline_reasons.items()},
            "generic_provider_allowed": self.generic_provider_allowed,
            "generic_provider_gate_reason": self.generic_provider_gate_reason,
            "generic_provider_reason": self.generic_provider_reason,
            "clarification_needed": self.clarification_needed,
            "clarification_text": self.clarification_text,
            "missing_preconditions": list(self.missing_preconditions),
            "tool_candidates": list(self.tool_candidates),
            "legacy_fallback_used": self.legacy_fallback_used,
            "authoritative": self.authoritative,
        }


class RouteSpine:
    """Authoritative contract-based router for migrated route families."""

    def __init__(
        self,
        *,
        extractor: IntentFrameExtractor | None = None,
        specs: dict[str, RouteFamilySpec] | None = None,
    ) -> None:
        self._extractor = extractor or IntentFrameExtractor()
        self._specs = dict(specs or default_route_family_specs())

    def route(
        self,
        raw_text: str,
        *,
        active_context: dict[str, Any] | None,
        active_request_state: dict[str, Any] | None,
        recent_tool_results: list[dict[str, Any]] | None,
    ) -> RouteSpineDecision:
        frame = self._extractor.extract(
            raw_text,
            active_context=active_context or {},
            active_request_state=active_request_state or {},
            recent_tool_results=recent_tool_results or [],
        )
        candidates = self._candidates(frame)
        accepted = [candidate for candidate in candidates if candidate.accepted]
        if accepted:
            selected = sorted(accepted, key=lambda item: item.score, reverse=True)[0]
            missing = selected.missing_preconditions
            winner = RouteSpineWinner(
                route_family=selected.route_family,
                subsystem=selected.subsystem,
                score=selected.score,
                result_state="needs_clarification" if missing else "routed",
                tool_candidates=selected.tool_candidates,
            )
            return RouteSpineDecision(
                routing_engine="route_spine",
                intent_frame=frame,
                winner=winner,
                candidate_specs_considered=tuple(candidate.route_family for candidate in candidates),
                candidates=tuple(candidate if candidate.route_family != selected.route_family else _select(candidate) for candidate in candidates),
                selected_route_spec=selected.route_family,
                native_decline_reasons=self._decline_reasons(candidates),
                generic_provider_allowed=False,
                generic_provider_gate_reason="native_route_candidate_present",
                generic_provider_reason="native_route_candidate_present",
                clarification_needed=bool(missing),
                clarification_text=self._clarification_text(selected.route_family, missing),
                missing_preconditions=missing,
                tool_candidates=list(selected.tool_candidates),
                legacy_fallback_used=False,
                authoritative=True,
            )
        if candidates and self._declined_candidates_are_meaningful_for_migrated_spine(frame, candidates):
            return RouteSpineDecision(
                routing_engine="generic_provider",
                intent_frame=frame,
                winner=RouteSpineWinner(route_family="generic_provider", subsystem="provider", score=0.35),
                candidate_specs_considered=tuple(candidate.route_family for candidate in candidates),
                candidates=tuple(candidates),
                selected_route_spec="",
                native_decline_reasons=self._decline_reasons(candidates),
                generic_provider_allowed=True,
                generic_provider_gate_reason="native_candidates_declined",
                generic_provider_reason=frame.generic_provider_reason,
                legacy_fallback_used=False,
                authoritative=True,
            )
        if self._conceptual_migrated_near_miss(frame.normalized_text):
            return RouteSpineDecision(
                routing_engine="generic_provider",
                intent_frame=frame,
                winner=RouteSpineWinner(route_family="generic_provider", subsystem="provider", score=0.35),
                candidate_specs_considered=tuple(candidate.route_family for candidate in candidates),
                candidates=tuple(candidates),
                selected_route_spec="",
                native_decline_reasons=self._decline_reasons(candidates),
                generic_provider_allowed=True,
                generic_provider_gate_reason="conceptual_near_miss_no_native_action",
                generic_provider_reason="conceptual_prompt_mentions_native_terms_without_action_target",
                legacy_fallback_used=False,
                authoritative=True,
            )
        return RouteSpineDecision(
            routing_engine="legacy_planner",
            intent_frame=frame,
            winner=RouteSpineWinner(route_family="legacy_planner", subsystem="legacy", score=0.0),
            generic_provider_allowed=True,
            generic_provider_gate_reason="no_migrated_family_signal",
            generic_provider_reason="defer_to_legacy_planner",
            legacy_fallback_used=True,
            authoritative=False,
        )

    def _declined_candidates_are_meaningful_for_migrated_spine(
        self,
        frame: IntentFrame,
        candidates: list[RouteSpecCandidate],
    ) -> bool:
        if frame.native_owner_hint in MIGRATED_ROUTE_FAMILIES:
            return True
        return any("negative_or_near_miss_signal" in candidate.decline_reasons for candidate in candidates)

    def _candidates(self, frame: IntentFrame) -> list[RouteSpecCandidate]:
        candidates: list[RouteSpecCandidate] = []
        for family in MIGRATED_ROUTE_FAMILIES:
            spec = self._specs.get(family) or self._synthetic_spec(family)
            candidate = self._score(spec, frame)
            if candidate.score > 0 or candidate.decline_reasons:
                candidates.append(candidate)
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _score(self, spec: RouteFamilySpec, frame: IntentFrame) -> RouteSpecCandidate:
        factors: dict[str, float] = {}
        reasons: list[str] = []
        declines: list[str] = []
        score = 0.0

        if spec.route_family == "calculations" and frame.native_owner_hint != "calculations":
            declines.append("no_numeric_or_calculation_context_signal")
            return RouteSpecCandidate(
                route_family=spec.route_family,
                subsystem=spec.subsystem,
                score=0.0,
                accepted=False,
                score_factors={"calculation_signal": 0.0},
                decline_reasons=tuple(declines),
                tool_candidates=spec.tool_candidates,
            )
        if (
            spec.route_family in {"file", "browser_destination", "app_control", "context_action"}
            and frame.target_type not in spec.owned_target_types
            and frame.native_owner_hint != spec.route_family
        ):
            declines.append("target_type_mismatch_for_action_family")
            return RouteSpecCandidate(
                route_family=spec.route_family,
                subsystem=spec.subsystem,
                score=0.0,
                accepted=False,
                score_factors={"target_type_match": 0.0},
                decline_reasons=tuple(declines),
                tool_candidates=spec.tool_candidates,
            )

        if self._near_miss(spec, frame):
            declines.append("negative_or_near_miss_signal")
            return RouteSpecCandidate(
                route_family=spec.route_family,
                subsystem=spec.subsystem,
                score=0.0,
                accepted=False,
                score_factors={"negative_guard": -1.0},
                decline_reasons=tuple(declines),
                tool_candidates=spec.tool_candidates,
            )

        if spec.route_family == "network" and not self._network_status_signal(frame.normalized_text) and frame.native_owner_hint != "network":
            declines.append("no_network_status_signal")
            return self._declined(spec, declines, {"network_status_signal": 0.0})
        if spec.route_family == "watch_runtime" and not self._watch_runtime_signal(frame.normalized_text) and frame.native_owner_hint != "watch_runtime":
            declines.append("no_runtime_status_signal")
            return self._declined(spec, declines, {"runtime_status_signal": 0.0})
        if spec.route_family == "machine" and not self._machine_signal(frame.normalized_text) and frame.native_owner_hint != "machine":
            declines.append("no_machine_status_signal")
            return self._declined(spec, declines, {"machine_status_signal": 0.0})
        if spec.route_family == "power" and not self._power_signal(frame.normalized_text) and frame.native_owner_hint != "power":
            declines.append("no_power_status_signal")
            return self._declined(spec, declines, {"power_status_signal": 0.0})
        if spec.route_family == "resources" and not self._resource_signal(frame.normalized_text) and frame.native_owner_hint != "resources":
            declines.append("no_resource_status_signal")
            return self._declined(spec, declines, {"resource_status_signal": 0.0})
        if spec.route_family == "window_control" and not self._window_status_signal(frame.normalized_text) and frame.native_owner_hint != "window_control":
            declines.append("no_window_status_signal")
            return self._declined(spec, declines, {"window_status_signal": 0.0})
        if spec.route_family == "task_continuity" and not self._task_continuity_signal(frame.normalized_text) and frame.native_owner_hint != "task_continuity":
            declines.append("no_task_continuity_signal")
            return self._declined(spec, declines, {"task_continuity_signal": 0.0})
        if spec.route_family == "workspace_operations" and not self._workspace_signal(frame.normalized_text) and frame.native_owner_hint != "workspace_operations":
            declines.append("no_workspace_operation_signal")
            return self._declined(spec, declines, {"workspace_operation_signal": 0.0})
        if spec.route_family == "workspace_operations" and frame.native_owner_hint == "task_continuity":
            declines.append("task_continuity_takes_precedence_over_workspace_operation")
            return self._declined(spec, declines, {"task_continuity_owner_hint": 1.0})
        if spec.route_family == "workflow" and not self._workflow_signal(frame.normalized_text) and frame.native_owner_hint != "workflow":
            declines.append("no_workflow_signal")
            return self._declined(spec, declines, {"workflow_signal": 0.0})
        if spec.route_family == "maintenance" and not self._maintenance_signal(frame.normalized_text) and frame.native_owner_hint != "maintenance":
            declines.append("no_maintenance_signal")
            return self._declined(spec, declines, {"maintenance_signal": 0.0})
        if spec.route_family == "terminal" and not self._terminal_signal(frame.normalized_text) and frame.native_owner_hint != "terminal":
            declines.append("no_terminal_signal")
            return self._declined(spec, declines, {"terminal_signal": 0.0})
        if spec.route_family == "desktop_search" and not self._desktop_search_signal(frame.normalized_text) and frame.native_owner_hint != "desktop_search":
            declines.append("no_desktop_search_signal")
            return self._declined(spec, declines, {"desktop_search_signal": 0.0})
        if spec.route_family == "desktop_search" and frame.native_owner_hint == "maintenance":
            declines.append("maintenance_operation_takes_precedence_over_local_search")
            return self._declined(spec, declines, {"maintenance_owner_hint": 1.0})
        if spec.route_family == "software_recovery" and not self._software_recovery_signal(frame.normalized_text) and frame.native_owner_hint != "software_recovery":
            declines.append("no_software_recovery_signal")
            return self._declined(spec, declines, {"software_recovery_signal": 0.0})
        if spec.route_family == "unsupported" and frame.native_owner_hint != "unsupported":
            declines.append("no_unsupported_external_commitment_signal")
            return self._declined(spec, declines, {"unsupported_signal": 0.0})

        if frame.operation in spec.owned_operations:
            factors["operation_match"] = 0.36
            reasons.append("operation matched route-family contract")
            score += 0.36
        if frame.target_type in spec.owned_target_types:
            factors["target_type_match"] = 0.32
            reasons.append("target type matched route-family contract")
            score += 0.32
        if frame.native_owner_hint == spec.route_family:
            factors["native_owner_hint"] = 0.22
            reasons.append("intent frame named this family as native owner")
            score += 0.22
        if self._positive_signal(spec, frame.normalized_text):
            factors["positive_signal"] = 0.18
            reasons.append("positive route-family signal matched")
            score += 0.18

        if spec.route_family == "network" and self._network_status_signal(frame.normalized_text):
            factors["network_status_signal"] = 0.82
            reasons.append("local network status signal matched")
            score = max(score, 0.82)
        if spec.route_family == "watch_runtime" and self._watch_runtime_signal(frame.normalized_text):
            factors["runtime_status_signal"] = 0.82
            reasons.append("runtime/app status signal matched")
            score = max(score, 0.82)
        if spec.route_family == "app_control" and self._app_status_signal(frame.normalized_text):
            factors["app_status_signal"] = 0.84
            reasons.append("active application status signal matched")
            score = max(score, 0.84)
        if spec.route_family == "window_control" and self._window_status_signal(frame.normalized_text):
            factors["window_status_signal"] = 0.84
            reasons.append("window status signal matched")
            score = max(score, 0.84)
        if spec.route_family == "task_continuity" and self._task_continuity_signal(frame.normalized_text):
            factors["task_continuity_signal"] = 0.78
            reasons.append("task continuity signal matched")
            score = max(score, 0.78)
        if spec.route_family == "workspace_operations" and self._workspace_signal(frame.normalized_text):
            factors["workspace_operation_signal"] = 0.82
            reasons.append("workspace operation signal matched")
            score = max(score, 0.82)
        if spec.route_family == "workflow" and self._workflow_signal(frame.normalized_text):
            factors["workflow_signal"] = 0.82
            reasons.append("workflow setup signal matched")
            score = max(score, 0.82)
        if spec.route_family == "maintenance" and self._maintenance_signal(frame.normalized_text):
            factors["maintenance_signal"] = 0.82
            reasons.append("maintenance action signal matched")
            score = max(score, 0.82)
        if spec.route_family == "terminal" and self._terminal_signal(frame.normalized_text):
            factors["terminal_signal"] = 0.82
            reasons.append("terminal action signal matched")
            score = max(score, 0.82)
        if spec.route_family == "desktop_search" and self._desktop_search_signal(frame.normalized_text):
            factors["desktop_search_signal"] = 0.84
            reasons.append("desktop search signal matched")
            score = max(score, 0.84)
        if spec.route_family == "software_recovery" and self._software_recovery_signal(frame.normalized_text):
            factors["software_recovery_signal"] = 0.84
            reasons.append("software recovery signal matched")
            score = max(score, 0.84)
        if spec.route_family == "unsupported" and frame.native_owner_hint == "unsupported":
            factors["unsupported_external_commitment_signal"] = 0.9
            reasons.append("unsupported external commitment signal matched")
            score = max(score, 0.9)
        if spec.route_family == "machine" and self._machine_signal(frame.normalized_text):
            factors["machine_status_signal"] = 0.8
            reasons.append("machine status signal matched")
            score = max(score, 0.8)
        if spec.route_family == "power" and self._power_signal(frame.normalized_text):
            factors["power_status_signal"] = 0.8
            reasons.append("power status signal matched")
            score = max(score, 0.8)
        if spec.route_family == "resources" and self._resource_signal(frame.normalized_text):
            factors["resource_status_signal"] = 0.82
            reasons.append("resource status signal matched")
            score = max(score, 0.82)
        if score > 0 and frame.risk_class in spec.risk_classes:
            factors["risk_match"] = 0.12
            score += 0.12

        missing = self._missing_preconditions(spec.route_family, frame)
        if missing:
            factors["missing_context_owned"] = 0.08
            score += 0.08
            reasons.append("native family owns intent but requires clarification")

        if score <= 0:
            declines.append("no_operation_or_target_or_signal_match")
        accepted = score >= spec.confidence_floor or bool(missing and score >= 0.42)
        if not accepted and score > 0:
            declines.append("below_confidence_floor")
        return RouteSpecCandidate(
            route_family=spec.route_family,
            subsystem=spec.subsystem,
            score=round(min(score, 0.99), 3),
            accepted=accepted,
            missing_preconditions=tuple(missing),
            score_factors=factors,
            positive_reasons=tuple(reasons),
            decline_reasons=tuple(declines),
            tool_candidates=self._tool_candidates(spec.route_family, frame, spec),
        )

    def _synthetic_spec(self, route_family: str) -> RouteFamilySpec:
        if route_family == "network":
            return RouteFamilySpec(
                route_family="network",
                subsystem="system",
                owned_operations=("status", "inspect"),
                owned_target_types=("system_resource",),
                risk_classes=("read_only",),
                positive_intent_signals=("wifi", "network", "connection", "ssid"),
                negative_intent_signals=("neural network", "network architecture"),
                near_miss_examples=("which neural network is better",),
                missing_context_behavior="network status does not require deictic context",
                clarification_template="Which network detail should I check?",
                tool_candidates=("network_status",),
                overcapture_guards=("neural network", "network architecture"),
            )
        raise KeyError(route_family)

    def _declined(
        self,
        spec: RouteFamilySpec,
        decline_reasons: list[str],
        score_factors: dict[str, float],
    ) -> RouteSpecCandidate:
        return RouteSpecCandidate(
            route_family=spec.route_family,
            subsystem=spec.subsystem,
            score=0.0,
            accepted=False,
            score_factors=score_factors,
            decline_reasons=tuple(decline_reasons),
            tool_candidates=spec.tool_candidates,
        )

    def _near_miss(self, spec: RouteFamilySpec, frame: IntentFrame) -> bool:
        text = frame.normalized_text
        for guard in (*spec.negative_intent_signals, *spec.overcapture_guards):
            if guard and str(guard).lower() in text:
                return True
        for example in spec.near_miss_examples:
            if example and text == str(example).lower():
                return True
        if spec.route_family == "screen_awareness" and "coverage summary" in text:
            return True
        if spec.route_family == "browser_destination" and "not exactly" in text and "almost" in text:
            return True
        if spec.route_family in {"file", "file_operation"} and "without opening" in text and frame.operation != "inspect":
            return True
        if spec.route_family == "discord_relay" and re.search(r"\b(?:explain|what is|what are)\b", text):
            return True
        if spec.route_family in {"network", "watch_runtime", "machine"} and re.search(r"\b(?:neural network|network architecture|machine learning)\b", text):
            return True
        if spec.route_family == "calculations" and re.search(r"\b(?:neural network|network architecture|machine learning)\b", text):
            return True
        if spec.route_family == "context_action" and any(phrase in text for phrase in {"selected text in html", "selection bias"}):
            return True
        if spec.route_family == "workspace_operations" and ("clean workspace" in text or _workspace_conceptual_text(text) or "workspace design" in text):
            return True
        if spec.route_family == "maintenance" and any(phrase in text for phrase in {"clean workspace", "workspace ideas", "clean writing style"}):
            return True
        if spec.route_family == "power" and "battery acid" in text:
            return True
        return False

    def _positive_signal(self, spec: RouteFamilySpec, normalized_text: str) -> bool:
        return any(str(signal).lower() in normalized_text for signal in spec.positive_intent_signals)

    def _missing_preconditions(self, family: str, frame: IntentFrame) -> list[str]:
        if family in {"network", "watch_runtime", "machine", "power", "resources", "window_control"}:
            return []
        if family == "screen_awareness":
            return ["visible_screen"] if frame.native_owner_hint == "screen_awareness" else []
        if family == "discord_relay":
            return ["payload", "destination"]
        if family == "routine" and frame.clarification_reason:
            return [frame.clarification_reason]
        if frame.clarification_reason and frame.native_owner_hint == family:
            return [frame.clarification_reason]
        if frame.context_reference != "none" and frame.context_status != "available" and frame.native_owner_hint == family:
            return [frame.clarification_reason or "context"]
        return []

    def _tool_candidates(self, family: str, frame: IntentFrame, spec: RouteFamilySpec) -> tuple[str, ...]:
        if family == "browser_destination":
            if "in the deck" in frame.normalized_text or "inside the deck" in frame.normalized_text:
                return ("deck_open_url",)
            return ("external_open_url",)
        if family == "file":
            if frame.operation == "inspect":
                return ("file_reader",)
            if "in the deck" in frame.normalized_text or "inside the deck" in frame.normalized_text:
                return ("deck_open_file",)
            return ("external_open_file",)
        if family == "app_control":
            if self._app_status_signal(frame.normalized_text):
                return ("active_apps",)
            return ("app_control",)
        if family == "window_control":
            return ("window_status",)
        if family == "watch_runtime":
            if self._browser_context_signal(frame.normalized_text):
                return ("browser_context",)
            if "app" in frame.normalized_text or "program" in frame.normalized_text:
                return ("active_apps",)
            return ("activity_summary",)
        if family == "power":
            if any(phrase in frame.normalized_text for phrase in {"until", "time to full", "time to empty"}):
                return ("power_projection",)
            return ("power_status",)
        if family == "resources":
            return ("resource_status",)
        if family == "network":
            return ("network_status",)
        if family == "desktop_search":
            return ("desktop_search",)
        if family == "terminal":
            return ("shell_command",)
        if family == "software_recovery":
            return ("repair_action",)
        if family == "workspace_operations":
            if "archive" in frame.normalized_text:
                return ("workspace_archive",)
            if "restore" in frame.normalized_text:
                return ("workspace_restore",)
            if "save" in frame.normalized_text:
                return ("workspace_save",)
            if "clear" in frame.normalized_text:
                return ("workspace_clear",)
            if "list" in frame.normalized_text:
                return ("workspace_list",)
            return ("workspace_assemble",)
        if family == "workflow":
            return ("workflow_execute",)
        if family == "maintenance":
            return ("maintenance_action",)
        return spec.tool_candidates

    def _decline_reasons(self, candidates: list[RouteSpecCandidate]) -> dict[str, list[str]]:
        return {
            candidate.route_family: list(candidate.decline_reasons)
            for candidate in candidates
            if candidate.decline_reasons
        }

    def _clarification_text(self, family: str, missing: tuple[str, ...]) -> str:
        primary = missing[0] if missing else "context"
        templates = {
            "calculations": "Which calculation should I reuse?",
            "browser_destination": "Which website or page should I open? I need a URL, current page, or recent browser reference first.",
            "file": "Which file should I use? I need a current file, selected file, or recent file reference first.",
            "context_action": "Which selected or highlighted context should I use? I need an active selection or clipboard first.",
            "screen_awareness": "Which visible control should I use? I need screen grounding before I can guide that action.",
            "discord_relay": "What should I send, and where should it go?",
            "routine": "What steps or recent action should I save as that routine?",
            "trust_approvals": "Which approval request should I use?",
            "file_operation": "Which file should I rename or change?",
            "terminal": "Which folder should I open the terminal in?",
            "workflow": "Which workflow or work context should I use?",
            "workspace_operations": "Which workspace should I use?",
            "desktop_search": "What should I search for on this computer?",
            "maintenance": "Which folder or file set should I prepare a maintenance plan for?",
            "software_recovery": "Which software, system component, or recovery target should I check?",
        }
        return templates.get(family, f"Which {primary.replace('_', ' ')} should I use?")

    def _network_status_signal(self, text: str) -> bool:
        if re.search(r"\b(?:neural network|network architecture|network design|network effects|networking advice|network graph concept)\b", text):
            return False
        return bool(
            re.search(r"\b(?:which|what|tell|show|check)\b.{0,28}\b(?:wifi|wi-fi|wireless|network|connection|ssid|internet)\b", text)
            or re.search(r"\bcheck\b.{0,32}\b(?:online|connected)\b", text)
            or re.search(r"\b(?:am i|are we|is my|is this|is the)\b.{0,32}\b(?:online|connected|on wifi|on wi-fi)\b", text)
            or re.search(r"\b(?:wifi|wi-fi|wireless)\b.{0,20}\b(?:signal|name|ssid|network)\b", text)
        )

    def _watch_runtime_signal(self, text: str) -> bool:
        return bool(
            self._browser_context_signal(text)
            or "what did i miss" in text
            or "while i was away" in text
        )

    def _app_status_signal(self, text: str) -> bool:
        if any(phrase in text for phrase in {"app architecture", "app marketing", "apps should i build"}):
            return False
        return bool(
            re.search(r"\b(?:which|what|show|list)\b.{0,24}\b(?:apps?|applications?|programs?)\b.{0,24}\b(?:running|open|active)\b", text)
            or re.search(r"\b(?:apps?|applications?|programs?)\b.{0,24}\b(?:running|open|active)\b", text)
            or re.search(r"\b(?:running|active|open)\b.{0,24}\b(?:apps?|applications?|programs?)\b", text)
        )

    def _window_status_signal(self, text: str) -> bool:
        if "window pattern" in text or "application window pattern" in text:
            return False
        return bool(
            re.search(r"\b(?:what|which|show|list)\b.{0,24}\bwindows?\b.{0,24}\b(?:open|active|focused|running)\b", text)
            or re.search(r"\b(?:open|active|focused)\b.{0,24}\bwindows?\b", text)
        )

    def _task_continuity_signal(self, text: str) -> bool:
        return any(phrase in text for phrase in {"where left off", "where i left off", "continue where i left off", "resume where i left off", "next steps", "do next", "what should i do next"})

    def _workspace_signal(self, text: str) -> bool:
        if "workspace design theory" in text or "clean workspace" in text or _workspace_conceptual_text(text):
            return False
        return "workspace" in text and not self._workflow_signal(text)

    def _workflow_signal(self, text: str) -> bool:
        if any(phrase in text for phrase in {"workflow theory", "workflow philosophy"}):
            return False
        return bool(
            re.search(r"\b(?:set up|setup|prepare|open|restore)\b.{0,36}\b(?:workflow|environment|setup|work context)\b", text)
            or re.search(r"\b(?:writing|research|project|diagnostics)\b.{0,24}\b(?:environment|setup|workflow|context)\b", text)
            or re.search(r"\brun\b.{0,24}\b(?:workflow|setup)\b", text)
        )

    def _maintenance_signal(self, text: str) -> bool:
        if any(phrase in text for phrase in {"clean up this paragraph", "clean writing style", "cleanup advice", "clean workspace ideas", "clean workspace"}):
            return False
        return bool(
            re.search(r"\b(?:clean up|cleanup|clean|archive|tidy)\b.{0,36}\b(?:downloads?|screenshots?|files?|folder|workspace)\b", text)
            or re.search(r"\b(?:find|show)\b.{0,24}\b(?:stale|large|old)\b.{0,24}\bfiles?\b", text)
        )

    def _terminal_signal(self, text: str) -> bool:
        if any(phrase in text for phrase in {"terminal velocity", "terminal illness", "terminal value"}):
            return False
        return bool(re.search(r"\b(?:terminal|powershell|command shell|shell)\b", text))

    def _desktop_search_signal(self, text: str) -> bool:
        if any(phrase in text for phrase in {"search algorithms", "search theory", "search engine", "search the web", "research online"}):
            return False
        return bool(
            re.search(r"\b(?:find|locate|search|pull up)\b.{0,48}\b(?:file|files|folder|document|doc|readme|pdf|downloads?|desktop|computer|machine)\b", text)
            or re.search(r"\b(?:find|locate|search)\b.{0,36}\b(?:on|from|under)\s+(?:this\s+)?(?:computer|machine|pc|desktop)\b", text)
        )

    def _software_recovery_signal(self, text: str) -> bool:
        if "status" in text and not re.search(r"\b(?:fix|repair|flush|restart)\b", text):
            return False
        return bool(
            re.search(r"\b(?:fix|repair|diagnose|flush|restart)\b.{0,32}\b(?:wifi|wi-fi|wi fi|network|connection|dns|explorer)\b", text)
            or re.search(r"\b(?:run)\b.{0,24}\b(?:connectivity checks?|network checks?)\b", text)
        )

    def _browser_context_signal(self, text: str) -> bool:
        return bool(
            re.search(r"\b(?:what|which)\b.{0,24}\b(?:browser\s+)?(?:page|tab)\b.{0,24}\bam i on\b", text)
            or re.search(r"\bcurrent\b.{0,16}\b(?:browser\s+)?(?:page|tab)\b", text)
        )

    def _machine_signal(self, text: str) -> bool:
        return any(phrase in text for phrase in {"machine name", "os version", "what computer", "what machine", "time zone", "timezone"})

    def _power_signal(self, text: str) -> bool:
        if "battery acid" in text:
            return False
        return any(term in text for term in {"battery", "charging", "power status", "time to empty", "time to full"})

    def _resource_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(?:cpu|memory|ram)\b.{0,24}\b(?:usage|use|load)\b", text) or "cpu and memory" in text)

    def _conceptual_migrated_near_miss(self, text: str) -> bool:
        return bool(
            any(
                phrase in text
                for phrase in {
                    "file naming philosophy",
                    "terminal velocity",
                    "daily routine",
                    "clean workspace",
                    "selected text in html",
                    "what is a website",
                    "what is a file",
                }
            )
            or (
                any(term in text for term in {"philosophy", "principles", "concept", "architecture", "design"})
                and any(term in text for term in {"file", "app", "website", "terminal", "routine", "network"})
            )
        )


def _select(candidate: RouteSpecCandidate) -> RouteSpecCandidate:
    return RouteSpecCandidate(
        route_family=candidate.route_family,
        subsystem=candidate.subsystem,
        score=candidate.score,
        selected=True,
        accepted=candidate.accepted,
        missing_preconditions=candidate.missing_preconditions,
        score_factors=candidate.score_factors,
        positive_reasons=candidate.positive_reasons,
        decline_reasons=candidate.decline_reasons,
        tool_candidates=candidate.tool_candidates,
    )
