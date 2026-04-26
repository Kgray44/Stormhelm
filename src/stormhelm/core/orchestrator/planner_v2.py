from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.orchestrator.intent_frame import IntentFrame
from stormhelm.core.orchestrator.intent_frame import IntentFrameExtractor
from stormhelm.core.orchestrator.route_family_specs import RouteFamilySpec
from stormhelm.core.orchestrator.route_family_specs import default_route_family_specs
from stormhelm.core.orchestrator.route_spine import RouteSpecCandidate
from stormhelm.core.orchestrator.route_spine import RouteSpineDecision
from stormhelm.core.orchestrator.route_spine import RouteSpineWinner


PLANNER_V2_ROUTE_FAMILIES = {
    "calculations",
    "browser_destination",
    "app_control",
    "file",
    "context_action",
    "context_clarification",
    "screen_awareness",
    "software_control",
    "watch_runtime",
    "network",
    "workspace_operations",
    "routine",
    "workflow",
    "task_continuity",
    "discord_relay",
    "trust_approvals",
}

PLANNER_V2_LEGACY_DEFER_FAMILIES = {
    "comparison",
    "desktop_search",
    "file_operation",
    "machine",
    "maintenance",
    "power",
    "power_projection",
    "resources",
    "software_recovery",
    "terminal",
    "trust_approvals",
    "weather",
    "window_control",
}


LEGACY_MIGRATION_SCHEDULE: dict[str, tuple[str, str]] = {
    "workspace_operations": ("migrated", "migrated_in_planner_v2_expansion_1"),
    "routine": ("migrated", "migrated_in_planner_v2_expansion_1"),
    "workflow": ("migrated", "migrated_in_planner_v2_expansion_1"),
    "task_continuity": ("migrated", "migrated_in_planner_v2_expansion_1"),
    "discord_relay": ("migrated", "migrated_in_planner_v2_expansion_1"),
    "terminal": ("scheduled", "medium"),
    "maintenance": ("scheduled", "medium"),
    "trust_approvals": ("scheduled", "medium"),
    "power": ("scheduled", "low"),
    "weather": ("scheduled", "low"),
    "window_control": ("scheduled", "low"),
    "resources": ("scheduled", "low"),
    "software_recovery": ("scheduled", "medium"),
    "machine": ("scheduled", "low"),
    "desktop_search": ("scheduled", "medium"),
}


def _routine_conceptual_text(text: str) -> bool:
    return bool(
        re.search(r"\broutine\b.{0,28}\b(?:advice|ideas?|design|philosoph|concept|programming)\b", text)
        or re.search(r"\b(?:daily|morning|workout|habit)\b.{0,24}\broutine\b", text)
    )


def _task_conceptual_text(text: str) -> bool:
    if re.search(r"\b(?:task management|prioritize tasks|planning theory)\b", text):
        return True
    if re.search(r"\btask continuity\b.{0,16}\b(?:mean|means|concept|definition)\b", text):
        return True
    if re.search(r"\b(?:this|that|there|workspace|previous|left off)\b", text):
        return False
    return bool(
        re.search(r"\bnext steps\b", text)
    )


def _discord_conceptual_text(text: str) -> bool:
    return bool(
        re.search(r"\bdiscord\b.{0,36}\b(?:architecture|bot|api|community|slack|docs?|format|rules|product|moderation)\b", text)
        or re.search(r"\b(?:what is|explain|compare)\b.{0,24}\bdiscord\b", text)
    )


def _workspace_conceptual_text(text: str) -> bool:
    if re.search(r"\bwhat\s+is\s+a\s+workspace\b", text):
        return True
    if re.search(r"\bworkspace\b.{0,28}\b(?:philosoph|theory|ui\s+design|organization)\b", text):
        return True
    if re.search(r"\bworkspace\b.{0,28}\bideas?\b", text):
        return True
    return "workspace" in text and bool(re.search(r"\binspiration\b.{0,16}\bboard\b", text))


def _json_ready(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {str(key): _json_ready(item) for key, item in asdict(value).items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class NormalizedRequest:
    raw_text: str
    normalized_text: str
    tokens: tuple[str, ...] = ()
    surface_mode: str = "ghost"
    active_module: str = "chartroom"
    invocation_prefix_removed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True, slots=True)
class ContextBinding:
    context_reference: str = "none"
    context_type: str = "none"
    context_source: str = ""
    status: str = "available"
    value: Any | None = None
    label: str = ""
    freshness: str = "current"
    ambiguity: str = ""
    candidate_bindings: tuple[dict[str, Any], ...] = ()
    missing_preconditions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    route_family: str
    subsystem: str
    owned_operations: tuple[str, ...]
    owned_target_types: tuple[str, ...]
    required_context_types: tuple[str, ...] = ()
    allowed_context_types: tuple[str, ...] = ()
    disallowed_context_types: tuple[str, ...] = ()
    risk_classes: tuple[str, ...] = ()
    tool_candidates: tuple[str, ...] = ()
    confidence_floor: float = 0.58

    @classmethod
    def from_route_family_spec(cls, spec: RouteFamilySpec) -> "CapabilitySpec":
        return cls(
            route_family=spec.route_family,
            subsystem=spec.subsystem,
            owned_operations=tuple(spec.owned_operations),
            owned_target_types=tuple(spec.owned_target_types),
            required_context_types=tuple(spec.required_context_types),
            allowed_context_types=tuple(spec.allowed_context_types),
            disallowed_context_types=tuple(spec.disallowed_context_types),
            risk_classes=tuple(spec.risk_classes),
            tool_candidates=tuple(spec.tool_candidates),
            confidence_floor=spec.confidence_floor,
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    route_family: str
    subsystem: str
    score: float
    accepted: bool = False
    selected: bool = False
    missing_preconditions: tuple[str, ...] = ()
    score_factors: dict[str, float] = field(default_factory=dict)
    positive_reasons: tuple[str, ...] = ()
    decline_reasons: tuple[str, ...] = ()
    tool_candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True, slots=True)
class RouteDecision:
    routing_engine: str
    selected_route_family: str
    selected_subsystem: str = ""
    selected_route_spec: str = ""
    score: float = 0.0
    route_candidates: tuple[RouteCandidate, ...] = ()
    candidate_specs_considered: tuple[str, ...] = ()
    native_decline_reasons: dict[str, list[str]] = field(default_factory=dict)
    generic_provider_allowed: bool = False
    generic_provider_gate_reason: str = ""
    legacy_fallback_allowed: bool = False
    legacy_fallback_reason: str = ""
    legacy_family: str = ""
    planner_v2_decline_reason: str = ""
    legacy_family_scheduled_for_migration: bool = False
    migration_priority: str = ""
    clarification_needed: bool = False
    clarification_text: str = ""
    missing_preconditions: tuple[str, ...] = ()
    authoritative: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True, slots=True)
class PlanDraft:
    route_family: str
    subsystem: str
    operation: str
    target_type: str
    subject: str = ""
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    request_type_hint: str = ""
    execution_type: str = ""
    requires_execution: bool = False
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    risk_class: str
    approval_required_live: bool = False
    approval_required_eval_dry_run: bool = False
    preview_required_live: bool = False
    preview_required_eval_dry_run: bool = False
    dry_run_allowed: bool = True
    execution_blocked: bool = False
    trust_scope_required: str = ""
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True, slots=True)
class ResultStateDraft:
    result_state: str
    response_mode: str
    user_facing_status: str
    message: str = ""
    missing_preconditions: tuple[str, ...] = ()
    clarification_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(frozen=True, slots=True)
class PlannerV2Trace:
    normalized_request: NormalizedRequest
    intent_frame: IntentFrame
    context_binding: ContextBinding
    capability_specs: tuple[CapabilitySpec, ...]
    route_decision: RouteDecision
    plan_draft: PlanDraft
    policy_decision: PolicyDecision
    result_state_draft: ResultStateDraft
    stage_order: tuple[str, ...] = (
        "InputNormalizer",
        "IntentFrameExtractor",
        "ContextBinder",
        "CapabilityRegistry",
        "CandidateGenerator",
        "RouteArbitrator",
        "PlanBuilder",
        "PolicyEvaluator",
        "ResultStateComposer",
        "TelemetryEmitter",
    )
    authoritative: bool = False
    legacy_fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)

    def to_route_spine_decision(self) -> RouteSpineDecision:
        candidate_rows = tuple(
            RouteSpecCandidate(
                route_family=candidate.route_family,
                subsystem=candidate.subsystem,
                score=candidate.score,
                selected=candidate.selected,
                accepted=candidate.accepted,
                missing_preconditions=candidate.missing_preconditions,
                score_factors=dict(candidate.score_factors),
                positive_reasons=candidate.positive_reasons,
                decline_reasons=candidate.decline_reasons,
                tool_candidates=candidate.tool_candidates,
            )
            for candidate in self.route_decision.route_candidates
        )
        winner = RouteSpineWinner(
            route_family=self.route_decision.selected_route_family,
            subsystem=self.route_decision.selected_subsystem,
            score=self.route_decision.score,
            result_state=(
                "needs_clarification"
                if self.result_state_draft.result_state in {"needs_clarification", "blocked_missing_context"}
                else "routed"
            ),
            tool_candidates=tuple(self.plan_draft.tool_name for _ in [0] if self.plan_draft.tool_name)
            or tuple(self.route_decision.route_candidates[0].tool_candidates if self.route_decision.route_candidates else ()),
        )
        return RouteSpineDecision(
            routing_engine=self.route_decision.routing_engine,
            intent_frame=self.intent_frame,
            winner=winner,
            candidate_specs_considered=self.route_decision.candidate_specs_considered,
            candidates=candidate_rows,
            selected_route_spec=self.route_decision.selected_route_spec,
            native_decline_reasons=self.route_decision.native_decline_reasons,
            generic_provider_allowed=self.route_decision.generic_provider_allowed,
            generic_provider_gate_reason=self.route_decision.generic_provider_gate_reason,
            generic_provider_reason=self.route_decision.generic_provider_gate_reason,
            clarification_needed=self.route_decision.clarification_needed,
            clarification_text=self.route_decision.clarification_text,
            missing_preconditions=self.route_decision.missing_preconditions,
            tool_candidates=list(winner.tool_candidates),
            legacy_fallback_used=self.legacy_fallback_used,
            authoritative=self.authoritative,
        )


class InputNormalizer:
    def normalize(self, raw_text: str, *, surface_mode: str, active_module: str) -> NormalizedRequest:
        text = " ".join(str(raw_text or "").split()).strip()
        stripped = re.sub(r"^\s*stormhelm\s*[,:\-]\s*", "", text, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"^\s*(?:hey\s+)?(?:can|could)\s+you\s+", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"^\s*(?:please|pls|yo)\s+", "", stripped, flags=re.IGNORECASE)
        normalized = normalize_phrase(stripped)
        return NormalizedRequest(
            raw_text=stripped,
            normalized_text=normalized,
            tokens=tuple(token for token in normalized.split() if token),
            surface_mode=surface_mode,
            active_module=active_module,
            invocation_prefix_removed=stripped != text,
        )


class ContextBinder:
    def bind(
        self,
        frame: IntentFrame,
        *,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> ContextBinding:
        if frame.native_owner_hint == "context_clarification":
            selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
            return ContextBinding(
                context_reference=frame.context_reference,
                context_type="ambiguous_context",
                context_source="selection" if selection else "",
                status=frame.context_status or "ambiguous",
                value=selection.get("value") if selection else None,
                label=str(selection.get("preview") or "ambiguous context"),
                missing_preconditions=(frame.clarification_reason or "ambiguous_deictic_no_owner",),
            )
        if frame.native_owner_hint == "trust_approvals":
            trust = active_request_state.get("trust") if isinstance(active_request_state.get("trust"), dict) else {}
            if trust:
                return ContextBinding(
                    context_reference=frame.context_reference,
                    context_type="approval_object",
                    context_source="active_request_state",
                    status="available",
                    value={"active_request_state": dict(active_request_state), "trust": dict(trust)},
                    label=str(trust.get("request_id") or active_request_state.get("subject") or "approval request"),
                    candidate_bindings=({"type": "approval_object", "source": "active_request_state", "value": dict(trust), "confidence": 0.9},),
                )
            return self._missing(frame, "approval_object")
        if frame.native_owner_hint == "app_control" and frame.operation == "status":
            return ContextBinding(
                context_reference=frame.context_reference,
                context_type="app",
                context_source="active_request_state" if active_request_state else "status_request",
                status="available",
                value=dict(active_request_state) if active_request_state else {"target": "active applications"},
                label=frame.target_text or "active applications",
            )
        selected = frame.extracted_entities.get("selected_context")
        if isinstance(selected, dict):
            return ContextBinding(
                context_reference=frame.context_reference,
                context_type=self._context_type(selected, frame),
                context_source=str(selected.get("source") or ""),
                status=frame.context_status or "available",
                value=selected.get("value"),
                label=str(selected.get("label") or ""),
                candidate_bindings=(dict(selected),),
            )
        if frame.target_type == "selected_text":
            selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
            if selection.get("value"):
                return ContextBinding(
                    context_reference=frame.context_reference,
                    context_type="selected_text",
                    context_source="selection",
                    status="available",
                    value=selection.get("value"),
                    label=str(selection.get("preview") or "selected text"),
                )
            return self._missing(frame, "context")
        if frame.target_type == "visible_ui":
            visible = active_context.get("visible_ui") if isinstance(active_context.get("visible_ui"), dict) else {}
            if visible:
                return ContextBinding(
                    context_reference=frame.context_reference,
                    context_type="visible_ui",
                    context_source="screen",
                    status="available",
                    value=visible,
                    label=str(visible.get("label") or "visible UI"),
                )
            return self._missing(frame, "visible_screen")
        if frame.target_type in {"prior_calculation", "prior_result"}:
            bound = self._prior_calculation(active_context, active_request_state, recent_tool_results)
            if bound is not None:
                return ContextBinding(
                    context_reference=frame.context_reference,
                    context_type="prior_calculation",
                    context_source=str(bound.get("source") or "recent_context"),
                    status="available",
                    value=bound.get("value"),
                    label=str(bound.get("label") or "previous calculation"),
                    candidate_bindings=(bound,),
                )
            return self._missing(frame, "calculation_context")
        if frame.native_owner_hint == "workspace_operations":
            return self._workspace_binding(frame, active_context, active_request_state, recent_tool_results)
        if frame.native_owner_hint == "routine":
            return self._routine_binding(frame, active_context, active_request_state, recent_tool_results)
        if frame.native_owner_hint == "workflow":
            return self._workflow_binding(frame, active_context, active_request_state, recent_tool_results)
        if frame.native_owner_hint == "task_continuity":
            return self._task_binding(frame, active_context, active_request_state, recent_tool_results)
        if frame.native_owner_hint == "discord_relay":
            return self._discord_binding(frame, active_context, active_request_state, recent_tool_results)
        if frame.context_reference in {"this", "that", "it", "current_page"} and frame.target_type in {"website", "url"}:
            return self._missing(frame, "destination_context")
        if frame.context_reference in {"this", "that", "it", "current_file"} and frame.target_type in {"file", "folder"}:
            return self._missing(frame, "file_context")
        return ContextBinding(
            context_reference=frame.context_reference,
            context_type=frame.target_type if frame.target_type != "unknown" else "none",
            status=frame.context_status or "available",
        )

    def _workspace_binding(
        self,
        frame: IntentFrame,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> ContextBinding:
        bound = self._workspace_context(active_context, active_request_state, recent_tool_results)
        if self._workspace_needs_seed(frame):
            if bound is None:
                return self._missing(frame, "workspace_seed_context")
            return self._bound(frame, bound, context_type="workspace")
        return self._bound(frame, bound, context_type="workspace") if bound is not None else ContextBinding(
            context_reference=frame.context_reference,
            context_type="workspace",
            status="available",
        )

    def _routine_binding(
        self,
        frame: IntentFrame,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> ContextBinding:
        if frame.clarification_reason == "routine_context":
            return self._missing(frame, "routine_context")
        if frame.operation == "save" or self._routine_save_contextual(frame):
            bound = self._saveable_context(active_context, active_request_state, recent_tool_results)
            if bound is None:
                return self._missing(frame, "steps_or_recent_action")
            return self._bound(frame, bound, context_type=str(bound.get("type") or "routine_context"))
        if frame.context_reference in {"this", "that", "it", "previous_result"} and not frame.target_text.strip():
            return self._missing(frame, "routine_context")
        return ContextBinding(
            context_reference=frame.context_reference,
            context_type="routine",
            status="available",
            label=frame.target_text or "routine",
        )

    def _workflow_binding(
        self,
        frame: IntentFrame,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> ContextBinding:
        if self._workflow_needs_prior_context(frame):
            bound = self._workflow_context(active_context, active_request_state, recent_tool_results)
            if bound is None:
                return self._missing(frame, "workflow_context")
            return self._bound(frame, bound, context_type="workflow")
        return ContextBinding(
            context_reference=frame.context_reference,
            context_type="workflow",
            status="available",
            label=frame.target_text or "workflow",
        )

    def _task_binding(
        self,
        frame: IntentFrame,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> ContextBinding:
        bound = self._task_context(active_context, active_request_state, recent_tool_results)
        if bound is None:
            return self._missing(frame, "task_context")
        return self._bound(frame, bound, context_type="workspace")

    def _discord_binding(
        self,
        frame: IntentFrame,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> ContextBinding:
        del recent_tool_results
        destination = self._discord_destination(frame)
        payload = self._discord_payload(frame, active_context, active_request_state)
        missing: list[str] = []
        if not payload:
            missing.append("payload")
        if not destination:
            missing.append("destination")
        if missing:
            return ContextBinding(
                context_reference=frame.context_reference,
                context_type="discord_relay",
                status="missing",
                missing_preconditions=tuple(missing),
            )
        return ContextBinding(
            context_reference=frame.context_reference,
            context_type="discord_relay",
            context_source="selection" if self._selection_payload(active_context) else "operator_text",
            status="available",
            value={"destination": destination, "payload": payload},
            label=f"Discord relay to {destination}",
            candidate_bindings=({"type": "discord_relay", "destination": destination, "payload": payload, "confidence": 0.9},),
        )

    def _bound(self, frame: IntentFrame, bound: dict[str, Any], *, context_type: str) -> ContextBinding:
        return ContextBinding(
            context_reference=frame.context_reference,
            context_type=context_type,
            context_source=str(bound.get("source") or ""),
            status="available",
            value=bound.get("value"),
            label=str(bound.get("label") or context_type),
            candidate_bindings=(dict(bound),),
        )

    def _context_type(self, selected: dict[str, Any], frame: IntentFrame) -> str:
        kind = str(selected.get("type") or selected.get("kind") or "").strip()
        if kind == "website":
            return "current_page"
        if kind:
            return kind
        return frame.target_type

    def _missing(self, frame: IntentFrame, missing: str) -> ContextBinding:
        return ContextBinding(
            context_reference=frame.context_reference,
            context_type=frame.target_type,
            status="missing",
            missing_preconditions=(missing,),
        )

    def _prior_calculation(
        self,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for item in active_context.get("recent_context_resolutions", []) if isinstance(active_context.get("recent_context_resolutions"), list) else []:
            if isinstance(item, dict) and str(item.get("kind") or "").lower() == "calculation":
                result = item.get("result") if isinstance(item.get("result"), dict) else item
                return {
                    "type": "prior_calculation",
                    "source": "recent_context_resolutions",
                    "label": str(result.get("expression") or "previous calculation"),
                    "value": result,
                    "confidence": 0.92,
                }
        state_bound = self._active_state_calculation(active_request_state)
        if state_bound is not None:
            return state_bound
        for result in recent_tool_results:
            if isinstance(result, dict) and str(result.get("family") or result.get("kind") or "").lower() == "calculations":
                return {
                    "type": "prior_calculation",
                    "source": "recent_tool_results",
                    "label": str(result.get("summary") or "previous calculation"),
                    "value": dict(result),
                    "confidence": 0.78,
                }
        return None

    def _active_state_calculation(self, active_request_state: dict[str, Any]) -> dict[str, Any] | None:
        if str(active_request_state.get("family") or "").lower() != "calculations":
            return None
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        calculation_request = (
            parameters.get("calculation_request") if isinstance(parameters.get("calculation_request"), dict) else {}
        )
        extracted_expression = str(calculation_request.get("extracted_expression") or parameters.get("expression") or "").strip()
        helper_name = str(calculation_request.get("helper_name") or parameters.get("helper_name") or "").strip()
        verification_claim = str(calculation_request.get("verification_claim") or "").strip()
        helper_arguments = calculation_request.get("arguments") if isinstance(calculation_request.get("arguments"), dict) else {}
        if not (extracted_expression or helper_name or verification_claim or helper_arguments):
            return None
        label = extracted_expression or helper_name or str(active_request_state.get("subject") or "previous calculation")
        payload = dict(calculation_request) if calculation_request else dict(parameters)
        return {
            "type": "prior_calculation",
            "source": "active_request_state",
            "label": label,
            "value": payload,
            "confidence": 0.84,
        }

    def _workspace_needs_seed(self, frame: IntentFrame) -> bool:
        text = frame.normalized_text
        if frame.context_reference in {"this", "that", "it", "there"}:
            return True
        return any(phrase in text for phrase in {"for this", "from this", "from that", "where we are", "where i am"})

    def _routine_save_contextual(self, frame: IntentFrame) -> bool:
        text = frame.normalized_text
        return bool(
            frame.operation == "save"
            or re.search(r"\b(?:make|turn|remember|save)\b.{0,28}\b(?:this|that|workflow|routine)\b", text)
        )

    def _workflow_needs_prior_context(self, frame: IntentFrame) -> bool:
        text = frame.normalized_text
        return bool(
            frame.context_reference in {"this", "that", "it", "previous_result"}
            or re.search(r"\b(?:same|previous|last|again)\b.{0,20}\b(?:workflow|setup|context)\b", text)
            or re.search(r"\b(?:run|restore|prepare|open)\b.{0,18}\b(?:this|that)\b", text)
        )

    def _workspace_context(
        self,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for key, label in (
            ("current_resolution", "current resolution"),
            ("workspace", "current workspace"),
            ("current_task", "current task"),
        ):
            payload = active_context.get(key)
            if isinstance(payload, dict) and payload:
                return {"type": "workspace", "source": key, "label": str(payload.get("title") or payload.get("name") or label), "value": payload, "confidence": 0.88}
        family = str(active_request_state.get("family") or "").lower()
        if family in {"workspace_operations", "workflow", "task_continuity"}:
            return {"type": "workspace", "source": "active_request_state", "label": str(active_request_state.get("subject") or "active workspace context"), "value": dict(active_request_state), "confidence": 0.82}
        for result in recent_tool_results:
            if isinstance(result, dict) and str(result.get("family") or result.get("kind") or "").lower() in {"workspace_operations", "workspace", "workflow"}:
                return {"type": "workspace", "source": "recent_tool_results", "label": str(result.get("summary") or "recent workspace context"), "value": dict(result), "confidence": 0.74}
        return None

    def _workflow_context(
        self,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        family = str(active_request_state.get("family") or "").lower()
        if family in {"workflow", "routine"}:
            return {"type": "workflow", "source": "active_request_state", "label": str(active_request_state.get("subject") or "active workflow"), "value": dict(active_request_state), "confidence": 0.84}
        workspace = self._workspace_context(active_context, active_request_state, recent_tool_results)
        if workspace is not None:
            return {**workspace, "type": "workflow"}
        return None

    def _saveable_context(
        self,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        family = str(active_request_state.get("family") or "").lower()
        if family and family not in {"routine", "generic_provider", "unsupported"}:
            return {"type": family, "source": "active_request_state", "label": str(active_request_state.get("subject") or family), "value": dict(active_request_state), "confidence": 0.86}
        selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
        if selection.get("value"):
            return {"type": "selected_text", "source": "selection", "label": str(selection.get("preview") or "selected text"), "value": selection.get("value"), "confidence": 0.8}
        workspace = self._workspace_context(active_context, active_request_state, recent_tool_results)
        if workspace is not None:
            return workspace
        return None

    def _task_context(
        self,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        for key in ("current_task", "workspace", "current_resolution"):
            payload = active_context.get(key)
            if isinstance(payload, dict) and payload:
                return {"type": "workspace", "source": key, "label": str(payload.get("title") or payload.get("name") or "task context"), "value": payload, "confidence": 0.88}
        family = str(active_request_state.get("family") or "").lower()
        if family in {"task_continuity", "workspace_operations", "workflow"}:
            return {"type": "workspace", "source": "active_request_state", "label": str(active_request_state.get("subject") or "active task"), "value": dict(active_request_state), "confidence": 0.8}
        for result in recent_tool_results:
            if isinstance(result, dict) and str(result.get("family") or result.get("kind") or "").lower() in {"task_continuity", "workspace", "workflow"}:
                return {"type": "workspace", "source": "recent_tool_results", "label": str(result.get("summary") or "recent task"), "value": dict(result), "confidence": 0.74}
        return None

    def _discord_destination(self, frame: IntentFrame) -> str:
        text = frame.raw_text
        for pattern in (
            r"\b(?:to|with|for)\s+(?P<dest>[A-Za-z][\w.-]{1,40})(?:\s+on\s+Discord)?\b",
            r"\b(?:message|dm)\s+(?P<dest>[A-Za-z][\w.-]{1,40})\b",
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                destination = str(match.group("dest") or "").strip(" .,:;!?")
                if destination.lower() not in {"discord", "this", "that", "selected", "highlighted", "text"}:
                    return destination
        return ""

    def _discord_payload(
        self,
        frame: IntentFrame,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
    ) -> Any:
        selection = self._selection_payload(active_context)
        if selection:
            return selection
        if str(active_request_state.get("family") or "").lower() not in {"", "generic_provider", "unsupported", "discord_relay"}:
            return dict(active_request_state)
        if not any(term in frame.normalized_text.split() for term in {"this", "that", "it", "selected", "highlighted", "clipboard"}):
            payload = re.sub(r"\b(?:send|share|message|post|relay|forward|dm|pass)\b", "", frame.raw_text, flags=re.IGNORECASE)
            payload = re.sub(r"\b(?:to|with|for)\s+[A-Za-z][\w.-]{1,40}(?:\s+on\s+Discord)?\b", "", payload, flags=re.IGNORECASE)
            payload = " ".join(payload.split()).strip(" .,:;!?")
            if payload:
                return payload
        return None

    def _selection_payload(self, active_context: dict[str, Any]) -> Any:
        selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
        return selection.get("value") or selection.get("preview")


class CapabilityRegistry:
    def __init__(self, specs: dict[str, RouteFamilySpec] | None = None) -> None:
        self._specs = {
            family: spec
            for family, spec in (specs or default_route_family_specs()).items()
            if family in PLANNER_V2_ROUTE_FAMILIES
        }

    def specs(self) -> tuple[CapabilitySpec, ...]:
        return tuple(CapabilitySpec.from_route_family_spec(spec) for spec in self._specs.values())

    def route_specs(self) -> dict[str, RouteFamilySpec]:
        return dict(self._specs)


class CandidateGenerator:
    def generate(
        self,
        frame: IntentFrame,
        binding: ContextBinding,
        specs: dict[str, RouteFamilySpec],
    ) -> tuple[RouteCandidate, ...]:
        rows: list[RouteCandidate] = []
        for family, spec in specs.items():
            rows.append(self._score(frame, binding, spec))
        return tuple(sorted(rows, key=lambda item: item.score, reverse=True))

    def _score(self, frame: IntentFrame, binding: ContextBinding, spec: RouteFamilySpec) -> RouteCandidate:
        score = 0.0
        factors: dict[str, float] = {}
        positive: list[str] = []
        declines: list[str] = []
        if spec.route_family == "context_clarification" and frame.native_owner_hint != "context_clarification":
            return RouteCandidate(
                route_family=spec.route_family,
                subsystem=spec.subsystem,
                score=0.0,
                accepted=False,
                score_factors={"context_clarification_gate": 0.0},
                decline_reasons=("requires_ambiguous_deictic_no_owner",),
                tool_candidates=spec.tool_candidates,
            )
        if spec.route_family == "calculations" and frame.native_owner_hint != "calculations":
            return RouteCandidate(
                route_family=spec.route_family,
                subsystem=spec.subsystem,
                score=0.0,
                accepted=False,
                score_factors={"calculation_owner_gate": 0.0},
                decline_reasons=("requires_calculation_owner_hint",),
                tool_candidates=spec.tool_candidates,
            )
        if frame.native_owner_hint == spec.route_family:
            factors["native_owner_hint"] = 0.42
            score += 0.42
            positive.append("IntentFrame named this route family as native owner")
        if frame.operation in spec.owned_operations:
            factors["operation_match"] = 0.26
            score += 0.26
            positive.append("operation matched capability contract")
        if frame.target_type in spec.owned_target_types:
            factors["target_type_match"] = 0.24
            score += 0.24
            positive.append("target type matched capability contract")
        if frame.risk_class in spec.risk_classes:
            factors["risk_match"] = 0.1
            score += 0.1
        if spec.route_family == "network" and frame.native_owner_hint == "network":
            factors["network_status_signal"] = 0.3
            score += 0.3
        if spec.route_family == "screen_awareness" and frame.target_type == "visible_ui":
            factors["visible_ui_signal"] = 0.28
            score += 0.28
        if spec.route_family == "software_control" and frame.operation == "verify" and frame.target_type == "software_package":
            factors["software_verify_signal"] = 0.34
            score += 0.34
            positive.append("software verification is read-only software_control")
        if spec.route_family == "calculations" and frame.target_type == "prior_calculation":
            factors["calculation_context_signal"] = 0.3
            score += 0.3
        if self._near_miss(frame, spec):
            return RouteCandidate(
                route_family=spec.route_family,
                subsystem=spec.subsystem,
                score=0.0,
                accepted=False,
                score_factors={"near_miss_guard": 0.0},
                decline_reasons=("negative_or_near_miss_signal",),
                tool_candidates=spec.tool_candidates,
            )
        missing = tuple(binding.missing_preconditions)
        accepted = score >= spec.confidence_floor or frame.native_owner_hint == spec.route_family
        if accepted and missing and frame.native_owner_hint == spec.route_family:
            positive.append("native family owns intent but requires context clarification")
        if not accepted:
            if frame.operation not in spec.owned_operations:
                declines.append("operation_mismatch")
            if frame.target_type not in spec.owned_target_types and frame.native_owner_hint != spec.route_family:
                declines.append("target_type_mismatch")
            if not declines:
                declines.append("below_confidence_floor")
        return RouteCandidate(
            route_family=spec.route_family,
            subsystem=spec.subsystem,
            score=round(min(score, 0.99), 3),
            accepted=accepted,
            missing_preconditions=missing if accepted else (),
            score_factors=factors,
            positive_reasons=tuple(positive),
            decline_reasons=tuple(declines),
            tool_candidates=spec.tool_candidates,
        )

    def _near_miss(self, frame: IntentFrame, spec: RouteFamilySpec) -> bool:
        text = frame.normalized_text
        if spec.route_family in {"watch_runtime", "network"} and any(
            phrase in text for phrase in {"neural network", "network architecture", "network effects"}
        ):
            return True
        if spec.route_family == "screen_awareness" and any(
            phrase in text for phrase in {"screenwriting", "press release", "buttoned up"}
        ):
            return True
        if spec.route_family == "app_control" and any(
            phrase in text for phrase in {"app design", "open source idea", "quit procrastinating"}
        ):
            return True
        if spec.route_family == "calculations" and any(
            phrase in text for phrase in {"calculator app", "math teaching ideas", "neural network"}
        ):
            return True
        if spec.route_family == "workspace_operations" and _workspace_conceptual_text(text):
            return True
        if spec.route_family == "routine" and _routine_conceptual_text(text):
            return True
        if spec.route_family == "workflow" and any(
            phrase in text for phrase in {"workflow theory", "workflow philosophy", "workflow diagram", "essay about workflows", "history of workflow automation"}
        ):
            return True
        if spec.route_family == "task_continuity" and _task_conceptual_text(text):
            return True
        if spec.route_family == "discord_relay" and _discord_conceptual_text(text):
            return True
        return False


class RouteArbitrator:
    def decide(
        self,
        frame: IntentFrame,
        candidates: tuple[RouteCandidate, ...],
    ) -> RouteDecision:
        considered = tuple(candidate.route_family for candidate in candidates)
        if self._conceptual_near_miss(frame):
            return RouteDecision(
                routing_engine="generic_provider",
                selected_route_family="generic_provider",
                selected_subsystem="provider",
                selected_route_spec="",
                score=0.35,
                route_candidates=candidates,
                candidate_specs_considered=considered,
                native_decline_reasons=self._declines(candidates),
                generic_provider_allowed=True,
                generic_provider_gate_reason="conceptual_near_miss_no_native_action",
                authoritative=True,
            )
        accepted = [candidate for candidate in candidates if candidate.accepted]
        if accepted:
            selected = max(accepted, key=lambda item: item.score)
            selected_candidates = tuple(
                RouteCandidate(
                    route_family=candidate.route_family,
                    subsystem=candidate.subsystem,
                    score=candidate.score,
                    accepted=candidate.accepted,
                    selected=candidate.route_family == selected.route_family,
                    missing_preconditions=tuple(candidate.missing_preconditions),
                    score_factors=dict(candidate.score_factors),
                    positive_reasons=tuple(candidate.positive_reasons),
                    decline_reasons=tuple(candidate.decline_reasons),
                    tool_candidates=tuple(candidate.tool_candidates),
                )
                for candidate in candidates
            )
            missing = selected.missing_preconditions
            return RouteDecision(
                routing_engine="planner_v2",
                selected_route_family=selected.route_family,
                selected_subsystem=selected.subsystem,
                selected_route_spec=selected.route_family,
                score=selected.score,
                route_candidates=selected_candidates,
                candidate_specs_considered=considered,
                native_decline_reasons=self._declines(candidates),
                generic_provider_allowed=False,
                generic_provider_gate_reason="native_route_candidate_present",
                clarification_needed=bool(missing),
                clarification_text=self._clarification_text(selected.route_family, missing, frame),
                missing_preconditions=missing,
                authoritative=True,
            )
        return RouteDecision(
            routing_engine="legacy_planner",
            selected_route_family="legacy_planner",
            selected_subsystem="legacy",
            score=0.0,
            route_candidates=candidates,
            candidate_specs_considered=considered,
            native_decline_reasons=self._declines(candidates),
            generic_provider_allowed=True,
            generic_provider_gate_reason="no_planner_v2_native_owner",
            legacy_fallback_allowed=True,
            legacy_fallback_reason="Planner v2 selected families did not own this request",
            legacy_family=self._legacy_family_hint(frame),
            planner_v2_decline_reason="no_accepted_planner_v2_candidate",
            legacy_family_scheduled_for_migration=self._legacy_family_scheduled(frame),
            migration_priority=self._legacy_migration_priority(frame),
            authoritative=False,
        )

    def _declines(self, candidates: tuple[RouteCandidate, ...]) -> dict[str, list[str]]:
        return {
            candidate.route_family: list(candidate.decline_reasons)
            for candidate in candidates
            if candidate.decline_reasons
        }

    def _conceptual_near_miss(self, frame: IntentFrame) -> bool:
        text = frame.normalized_text
        tokens = set(text.split())
        has_conceptual_unknown = frame.operation in {"unknown", "explain"} and bool(
            tokens.intersection({"architecture", "concept", "conceptual", "principle", "philosophy", "theory", "idea"})
        )
        return (
            has_conceptual_unknown
            or any(
                phrase in text
                for phrase in {
                    "neural network",
                    "network architecture",
                    "screenwriting",
                    "what is a website",
                    "what is selected text",
                    "app design",
                    "workflow theory",
                    "workflow diagram",
                }
            )
            or _workspace_conceptual_text(text)
            or _routine_conceptual_text(text)
            or _task_conceptual_text(text)
            or _discord_conceptual_text(text)
        )

    def _clarification_text(self, family: str, missing: tuple[str, ...], frame: IntentFrame) -> str:
        if family == "browser_destination":
            return "Which website or page should I open? I need a URL, current page, or recent browser reference first."
        if family == "calculations":
            return "Which prior calculation or number should I use?"
        if family == "screen_awareness":
            return "Which visible screen target should I use? I need grounded UI context before acting."
        if family == "context_action":
            return "Which selected or highlighted text should I use?"
        if family == "file":
            return "Which file or folder should I use?"
        if family == "app_control":
            return "Which app should I use?"
        if family == "workspace_operations":
            return "Which workspace context should I use? I need the current notes, task, or project seed before assembling that."
        if family == "routine":
            return "Which steps or recent action should I save as a routine?"
        if family == "workflow":
            return "Which workflow or setup context should I use?"
        if family == "task_continuity":
            return "Which task or workspace thread should I continue?"
        if family == "discord_relay":
            if "destination" in missing and "payload" in missing:
                return "Who should receive it, and what should I send?"
            if "destination" in missing:
                return "Who should I send it to?"
            return "What should I send?"
        if missing:
            return f"Which {missing[0].replace('_', ' ')} should I use?"
        return f"Which context should I use for {frame.target_text or family}?"

    def _legacy_family_hint(self, frame: IntentFrame) -> str:
        hint = str(frame.native_owner_hint or "").strip()
        if hint:
            return hint
        if frame.candidate_route_families:
            return str(frame.candidate_route_families[0] or "").strip()
        return "unknown"

    def _legacy_family_scheduled(self, frame: IntentFrame) -> bool:
        status, _priority = LEGACY_MIGRATION_SCHEDULE.get(self._legacy_family_hint(frame), ("unscheduled", ""))
        return status in {"scheduled", "migrated"}

    def _legacy_migration_priority(self, frame: IntentFrame) -> str:
        status, priority = LEGACY_MIGRATION_SCHEDULE.get(self._legacy_family_hint(frame), ("unscheduled", ""))
        return priority if status != "migrated" else "migrated"


class PlanBuilder:
    def build(self, frame: IntentFrame, binding: ContextBinding, decision: RouteDecision, *, surface_mode: str) -> PlanDraft:
        family = decision.selected_route_family
        subject = frame.target_text or family
        if family == "calculations":
            return PlanDraft(family, "calculations", frame.operation, frame.target_type, subject=subject, request_type_hint="calculation_response", execution_type="calculation_evaluate")
        if family == "browser_destination":
            url = str(binding.value or frame.extracted_entities.get("url") or frame.target_text)
            tool = "deck_open_url" if surface_mode.strip().lower() == "deck" else "external_open_url"
            return PlanDraft(family, "browser", "open", "website", subject=url, tool_name=tool, tool_arguments={"url": url}, request_type_hint="direct_action", execution_type="resolve_url_then_open_in_browser", requires_execution=True)
        if family == "app_control":
            if frame.operation == "status":
                return PlanDraft(family, "system", "status", "app", subject="active_apps", tool_name="active_apps", tool_arguments={"focus": "applications"}, request_type_hint="direct_deterministic_fact", execution_type="retrieve_current_status")
            action = "close" if frame.operation in {"quit", "close"} else "open"
            return PlanDraft(family, "system", action, "app", subject=subject, tool_name="app_control", tool_arguments={"action": action, "target": subject}, request_type_hint="direct_action", execution_type="execute_control_command", requires_execution=True)
        if family == "file":
            path = str(binding.value or frame.extracted_entities.get("path") or frame.target_text)
            tool = "file_reader" if frame.operation == "inspect" else "deck_open_file" if surface_mode.strip().lower() == "deck" else "external_open_file"
            return PlanDraft(family, "files", frame.operation, "file", subject=path, tool_name=tool, tool_arguments={"path": path}, request_type_hint="file_read" if tool == "file_reader" else "direct_action", execution_type="read_file" if tool == "file_reader" else "execute_control_command", requires_execution=tool != "file_reader")
        if family == "context_action":
            return PlanDraft(family, "context", frame.operation, "selected_text", subject="selection", tool_name="context_action", tool_arguments={"operation": "inspect", "source": "selection"}, request_type_hint="context_action", execution_type="execute_context_action")
        if family == "context_clarification":
            return PlanDraft(family, "context", "clarify", "unknown", subject="ambiguous context", request_type_hint="context_clarification", execution_type="clarify_route_context")
        if family == "screen_awareness":
            return PlanDraft(family, "screen_awareness", frame.operation, "visible_ui", subject="visible_screen", request_type_hint="screen_awareness_response", execution_type="screen_awareness_preflight")
        if family == "software_control":
            return PlanDraft(family, "software_control", frame.operation, "software_package", subject=subject, request_type_hint="software_control_response", execution_type="software_control_execute", requires_execution=frame.operation in {"install", "uninstall", "update", "repair"})
        if family == "network":
            return PlanDraft(family, "system", "status", "system_resource", subject="network", tool_name="network_status", tool_arguments={"focus": "overview"}, request_type_hint="direct_deterministic_fact", execution_type="retrieve_current_status")
        if family == "watch_runtime":
            return PlanDraft(family, "operations", "status", "system_resource", subject="runtime", tool_name="activity_summary", tool_arguments={}, request_type_hint="activity_summary", execution_type="summarize_activity")
        if family == "workspace_operations":
            tool_name = self._workspace_tool(frame)
            action = tool_name.replace("workspace_", "")
            args = {"query": frame.raw_text} if tool_name in {"workspace_assemble", "workspace_restore"} else {}
            return PlanDraft(family, "workspace", frame.operation, "workspace", subject=subject or action, tool_name=tool_name, tool_arguments=args, request_type_hint="workspace_operation", execution_type=f"{action}_workspace", requires_execution=True)
        if family == "routine":
            tool_name = "routine_save" if frame.operation == "save" else "routine_execute"
            action = "save_routine" if tool_name == "routine_save" else "execute_routine"
            return PlanDraft(family, "routine", frame.operation, "routine", subject=subject or "routine", tool_name=tool_name, tool_arguments={"query": frame.raw_text, "target": subject}, request_type_hint=tool_name, execution_type=action, requires_execution=True)
        if family == "workflow":
            return PlanDraft(family, "workflow", frame.operation, "workspace", subject=subject or "workflow", tool_name="workflow_execute", tool_arguments={"query": frame.raw_text, "workflow_kind": subject or "workflow"}, request_type_hint="workflow_execution", execution_type="execute_workflow", requires_execution=True)
        if family == "task_continuity":
            tool_name = "workspace_where_left_off" if "left off" in frame.normalized_text or "where were we" in frame.normalized_text else "workspace_next_steps"
            action = "where_left_off" if tool_name == "workspace_where_left_off" else "next_steps"
            return PlanDraft(family, "workspace", frame.operation, "workspace", subject=action, tool_name=tool_name, tool_arguments={}, request_type_hint="task_continuity", execution_type="summarize_workspace")
        if family == "discord_relay":
            payload = binding.value if isinstance(binding.value, dict) else {}
            return PlanDraft(family, "discord_relay", "send", "discord_recipient", subject=str(payload.get("destination") or subject or "discord"), tool_name=None, tool_arguments={"preview_only": True, **payload}, request_type_hint="discord_relay_preview", execution_type="discord_relay_preview", requires_execution=True)
        return PlanDraft(family, decision.selected_subsystem, frame.operation, frame.target_type, subject=subject)

    def _workspace_tool(self, frame: IntentFrame) -> str:
        text = frame.normalized_text
        if "restore" in text or "open" in text:
            return "workspace_restore"
        if "save" in text or "snapshot" in text:
            return "workspace_save"
        if "list" in text or "show" in text:
            return "workspace_list"
        return "workspace_assemble"


class PolicyEvaluator:
    def evaluate(self, frame: IntentFrame, binding: ContextBinding, plan: PlanDraft) -> PolicyDecision:
        risk = frame.risk_class
        if plan.route_family == "software_control" and frame.operation == "verify":
            risk = "read_only"
        reasons: list[str] = []
        execution_blocked = False
        if binding.status in {"missing", "stale", "ambiguous"} and binding.missing_preconditions:
            execution_blocked = True
            reasons.extend(binding.missing_preconditions)
        if plan.route_family == "screen_awareness" and frame.operation in {"open", "verify"}:
            execution_blocked = True
            if "visible_screen" not in reasons:
                reasons.append("visible_screen")
        approval_live = risk in {"external_app_open", "external_browser_open", "local_mutation", "destructive", "external_send", "software_lifecycle"}
        preview_live = risk in {"external_send", "software_lifecycle", "destructive", "external_browser_open", "external_app_open"}
        return PolicyDecision(
            risk_class=risk,
            approval_required_live=approval_live,
            approval_required_eval_dry_run=False,
            preview_required_live=preview_live,
            preview_required_eval_dry_run=False,
            dry_run_allowed=True,
            execution_blocked=execution_blocked,
            trust_scope_required=risk if approval_live else "",
            reasons=tuple(reasons),
        )


class ResultStateComposer:
    def compose(self, decision: RouteDecision, policy: PolicyDecision) -> ResultStateDraft:
        if decision.selected_route_family == "generic_provider":
            return ResultStateDraft(
                result_state="unsupported",
                response_mode="summary",
                user_facing_status="not_native",
                message="No native command family owns that request.",
            )
        if decision.clarification_needed or policy.execution_blocked:
            message = decision.clarification_text or "I need more context before I can do that."
            return ResultStateDraft(
                result_state="needs_clarification",
                response_mode="clarification",
                user_facing_status="blocked_missing_context",
                message=message,
                missing_preconditions=decision.missing_preconditions or tuple(policy.reasons),
                clarification_reason=message,
            )
        return ResultStateDraft(
            result_state="dry_run_ready",
            response_mode="action" if policy.risk_class != "read_only" else "summary",
            user_facing_status="planned",
            message="Dry-run plan is ready; no external action has run.",
        )


class PlannerV2:
    def __init__(self, *, specs: dict[str, RouteFamilySpec] | None = None) -> None:
        self._normalizer = InputNormalizer()
        self._extractor = IntentFrameExtractor()
        self._binder = ContextBinder()
        self._registry = CapabilityRegistry(specs)
        self._candidate_generator = CandidateGenerator()
        self._arbitrator = RouteArbitrator()
        self._plan_builder = PlanBuilder()
        self._policy = PolicyEvaluator()
        self._result_state = ResultStateComposer()

    def plan(
        self,
        raw_text: str,
        *,
        surface_mode: str = "ghost",
        active_module: str = "chartroom",
        active_context: dict[str, Any] | None = None,
        active_request_state: dict[str, Any] | None = None,
        recent_tool_results: list[dict[str, Any]] | None = None,
    ) -> PlannerV2Trace:
        active_context = active_context or {}
        active_request_state = active_request_state or {}
        recent_tool_results = recent_tool_results or []
        normalized = self._normalizer.normalize(raw_text, surface_mode=surface_mode, active_module=active_module)
        frame = self._extractor.extract(
            normalized.raw_text,
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        frame = self._repair_frame(frame, active_context=active_context, active_request_state=active_request_state, recent_tool_results=recent_tool_results)
        binding = self._binder.bind(
            frame,
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        specs = self._registry.route_specs()
        candidates = self._candidate_generator.generate(frame, binding, specs)
        if self._should_defer_to_legacy(frame):
            route_decision = self._legacy_defer_decision(frame, candidates)
            plan = self._plan_builder.build(frame, binding, route_decision, surface_mode=surface_mode)
            policy = self._policy.evaluate(frame, binding, plan)
            result_state = self._result_state.compose(route_decision, policy)
            return PlannerV2Trace(
                normalized_request=normalized,
                intent_frame=frame,
                context_binding=binding,
                capability_specs=self._registry.specs(),
                route_decision=route_decision,
                plan_draft=plan,
                policy_decision=policy,
                result_state_draft=result_state,
                authoritative=False,
                legacy_fallback_used=True,
            )
        route_decision = self._arbitrator.decide(frame, candidates)
        plan = self._plan_builder.build(frame, binding, route_decision, surface_mode=surface_mode)
        policy = self._policy.evaluate(frame, binding, plan)
        result_state = self._result_state.compose(route_decision, policy)
        return PlannerV2Trace(
            normalized_request=normalized,
            intent_frame=frame,
            context_binding=binding,
            capability_specs=self._registry.specs(),
            route_decision=route_decision,
            plan_draft=plan,
            policy_decision=policy,
            result_state_draft=result_state,
            authoritative=route_decision.authoritative,
            legacy_fallback_used=route_decision.legacy_fallback_allowed,
        )

    def _should_defer_to_legacy(self, frame: IntentFrame) -> bool:
        owner = str(frame.native_owner_hint or "").strip()
        return bool(owner and owner in PLANNER_V2_LEGACY_DEFER_FAMILIES and owner not in PLANNER_V2_ROUTE_FAMILIES)

    def _legacy_defer_decision(
        self,
        frame: IntentFrame,
        candidates: tuple[RouteCandidate, ...],
    ) -> RouteDecision:
        owner = str(frame.native_owner_hint or "").strip() or "unknown"
        declines = {
            candidate.route_family: list(candidate.decline_reasons or ("deferred_to_unmigrated_native_owner",))
            for candidate in candidates
        }
        declines["planner_v2"] = [f"native_owner_{owner}_not_migrated_to_planner_v2"]
        status, priority = LEGACY_MIGRATION_SCHEDULE.get(owner, ("unscheduled", ""))
        return RouteDecision(
            routing_engine="legacy_planner",
            selected_route_family="legacy_planner",
            selected_subsystem="legacy",
            selected_route_spec="",
            score=0.0,
            route_candidates=candidates,
            candidate_specs_considered=tuple(candidate.route_family for candidate in candidates),
            native_decline_reasons=declines,
            generic_provider_allowed=False,
            generic_provider_gate_reason=f"planner_v2_deferred_to_unmigrated_native_owner:{owner}",
            legacy_fallback_allowed=True,
            legacy_fallback_reason=f"Planner v2 deferred {owner} to the legacy/native route owner",
            legacy_family=owner,
            planner_v2_decline_reason="native_owner_not_migrated_to_planner_v2",
            legacy_family_scheduled_for_migration=status in {"scheduled", "migrated"},
            migration_priority=priority if status != "migrated" else "migrated",
            authoritative=False,
        )

    def _repair_frame(
        self,
        frame: IntentFrame,
        *,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> IntentFrame:
        text = frame.normalized_text
        if self._expansion_conceptual_near_miss(text):
            frame.operation = "unknown"
            frame.target_type = "unknown"
            frame.target_text = ""
            frame.native_owner_hint = None
            frame.candidate_route_families = []
            frame.generic_provider_allowed = True
            frame.generic_provider_reason = "conceptual_near_miss_no_native_action"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        active_followup_owner = self._active_state_followup_owner(frame, active_request_state)
        if active_followup_owner:
            self._apply_active_state_followup(
                frame,
                family=active_followup_owner,
                active_context=active_context,
                active_request_state=active_request_state,
                recent_tool_results=recent_tool_results,
            )
        if self._ambiguous_deictic_clarification_signal(frame, active_request_state):
            frame.operation = "clarify"
            frame.target_type = "unknown"
            frame.target_text = "current context"
            if frame.context_reference == "none":
                frame.context_reference = "previous_result" if self._followup_signal(text) else "this"
            frame.context_status = "ambiguous" if active_context else "missing"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "context_clarification"
            frame.candidate_route_families = ["context_clarification"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "ambiguous_deictic_requires_native_clarification"
            frame.clarification_needed = True
            frame.clarification_reason = "ambiguous_deictic_no_owner"
        if self._deictic_calculation_signal(text):
            has_context = bool(
                active_context.get("recent_context_resolutions")
                or ContextBinder()._active_state_calculation(active_request_state) is not None
                or any(isinstance(item, dict) and str(item.get("family") or item.get("kind") or "").lower() == "calculations" for item in recent_tool_results)
            )
            frame.operation = "calculate"
            frame.target_type = "prior_calculation"
            frame.target_text = "previous calculation"
            frame.context_reference = "previous_calculation"
            frame.context_status = "available" if has_context else "missing"
            frame.native_owner_hint = "calculations"
            frame.candidate_route_families = ["calculations"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = not has_context
            frame.clarification_reason = "" if has_context else "calculation_context"
        if self._software_verify_signal(text):
            frame.operation = "verify"
            frame.target_type = "software_package"
            frame.target_text = self._software_target_text(frame.raw_text)
            frame.risk_class = "read_only"
            frame.native_owner_hint = "software_control"
            frame.candidate_route_families = ["software_control"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
        if (
            frame.operation in {"install", "uninstall", "update", "repair"}
            and frame.target_type == "unknown"
            and self._software_lifecycle_text(text)
        ):
            frame.target_type = "software_package"
            frame.target_text = self._software_lifecycle_target(frame.raw_text)
            frame.risk_class = "software_lifecycle"
            frame.native_owner_hint = "software_control"
            frame.candidate_route_families = ["software_control"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
        if self._screen_status_signal(text):
            frame.operation = "inspect"
            frame.target_type = "visible_ui"
            frame.target_text = "visible screen"
            frame.context_reference = "visible_target"
            frame.context_status = "missing"
            frame.native_owner_hint = "screen_awareness"
            frame.candidate_route_families = ["screen_awareness"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = True
            frame.clarification_reason = "visible_screen"
        if self._workspace_signal(text):
            frame.operation = self._workspace_operation(text)
            frame.target_type = "workspace"
            frame.target_text = self._strip_known_verbs(frame.raw_text) or "workspace"
            if any(term in text.split() for term in {"this", "that", "there"}) or any(phrase in text for phrase in {"where we are", "where i am"}):
                frame.context_reference = "this" if "this" in text.split() else "that" if "that" in text.split() else "there"
                has_context = bool(active_context.get("current_resolution") or active_context.get("workspace") or active_context.get("current_task"))
                frame.context_status = "available" if has_context else "missing"
                frame.clarification_needed = not has_context
                frame.clarification_reason = "" if has_context else "workspace_seed_context"
            frame.risk_class = "dry_run_plan"
            frame.native_owner_hint = "workspace_operations"
            frame.candidate_route_families = ["workspace_operations"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
        if self._routine_signal(text):
            save_like = self._routine_save_signal(text)
            frame.operation = "save" if save_like else "launch"
            frame.target_type = "routine"
            frame.target_text = self._strip_known_verbs(frame.raw_text) or "routine"
            frame.context_reference = self._context_reference_from_text(text)
            has_context = bool(
                not save_like
                or active_context.get("current_resolution")
                or active_context.get("selection")
                or str(active_request_state.get("family") or "").lower() not in {"", "routine", "generic_provider", "unsupported"}
            )
            frame.context_status = "available" if has_context else "missing"
            frame.risk_class = "dry_run_plan"
            frame.native_owner_hint = "routine"
            frame.candidate_route_families = ["routine"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = save_like and not has_context
            frame.clarification_reason = "" if has_context else "steps_or_recent_action"
        if self._workflow_signal(text):
            frame.operation = "assemble" if not re.search(r"\b(?:run|launch|open|restore)\b", text) else "launch"
            frame.target_type = "workspace"
            frame.target_text = self._strip_known_verbs(frame.raw_text) or "workflow"
            frame.context_reference = self._context_reference_from_text(text)
            needs_context = bool(re.search(r"\b(?:this|that|same|previous|last|current)\b", text))
            has_context = bool(active_context.get("workspace") or active_context.get("current_resolution") or str(active_request_state.get("family") or "").lower() == "workflow")
            frame.context_status = "missing" if needs_context and not has_context else "available"
            frame.risk_class = "dry_run_plan"
            frame.native_owner_hint = "workflow"
            frame.candidate_route_families = ["workflow"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = frame.context_status == "missing"
            frame.clarification_reason = "workflow_context" if frame.clarification_needed else ""
        if frame.native_owner_hint in {None, "", "workspace_operations", "context_clarification"} and self._task_continuity_signal(text):
            frame.operation = "status" if re.search(r"\b(?:where|what)\b", text) else "assemble"
            frame.target_type = "workspace"
            frame.target_text = "task continuity"
            frame.context_reference = self._context_reference_from_text(text)
            has_context = bool(active_context.get("current_task") or active_context.get("workspace") or active_context.get("current_resolution"))
            frame.context_status = "available" if has_context else "missing"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "task_continuity"
            frame.candidate_route_families = ["task_continuity"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = not has_context
            frame.clarification_reason = "" if has_context else "task_context"
        if self._discord_relay_signal(text):
            frame.operation = "send"
            frame.target_type = "discord_recipient"
            frame.target_text = self._discord_target(frame.raw_text) or "discord"
            frame.context_reference = self._context_reference_from_text(text)
            has_payload = bool(active_context.get("selection") or str(active_request_state.get("family") or "").lower() not in {"", "discord_relay", "generic_provider", "unsupported"}) or not any(
                term in text.split() for term in {"this", "that", "it", "selected", "highlighted", "clipboard"}
            )
            has_destination = bool(self._discord_target(frame.raw_text))
            frame.context_status = "available" if has_payload and has_destination else "missing"
            frame.risk_class = "external_send"
            frame.native_owner_hint = "discord_relay"
            frame.candidate_route_families = ["discord_relay"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = frame.context_status == "missing"
            frame.clarification_reason = "discord_relay_context" if frame.clarification_needed else ""
        return frame

    def _active_state_followup_owner(self, frame: IntentFrame, active_request_state: dict[str, Any]) -> str:
        family = str(active_request_state.get("family") or "").strip().lower()
        trust = active_request_state.get("trust") if isinstance(active_request_state.get("trust"), dict) else {}
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        stage = str(parameters.get("request_stage") or "").strip().lower()
        if trust and stage == "awaiting_confirmation" and self._followup_signal(frame.normalized_text):
            return "trust_approvals"
        if family not in PLANNER_V2_ROUTE_FAMILIES:
            return ""
        if family in {"generic_provider", "unsupported", "context_clarification"}:
            return ""
        if frame.native_owner_hint:
            return ""
        text = frame.normalized_text
        if not self._followup_signal(text, frame=frame):
            return ""
        return family

    def _ambiguous_deictic_clarification_signal(self, frame: IntentFrame, active_request_state: dict[str, Any]) -> bool:
        if frame.native_owner_hint:
            return False
        if str(active_request_state.get("family") or "").strip():
            return False
        if frame.speech_act in {"question", "explanation_request", "comparison"}:
            return False
        if frame.operation != "unknown" or frame.target_type != "unknown":
            return False
        if self._expansion_conceptual_near_miss(frame.normalized_text):
            return False
        if self._bare_action_deictic_generic_provider_preferred(frame.normalized_text):
            return False
        return self._followup_signal(frame.normalized_text, frame=frame)

    def _bare_action_deictic_generic_provider_preferred(self, text: str) -> bool:
        return bool(
            re.match(r"^(?:click|press|tap|scroll|hover)\s+(?:this|that|it|there)\b", text)
            or re.match(r"^pay\s+(?:for\s+)?(?:this|that|it)\b", text)
        )

    def _followup_signal(self, text: str, *, frame: IntentFrame | None = None) -> bool:
        if frame is not None and frame.context_reference in {"this", "that", "it", "previous_result", "previous_calculation", "current_page", "current_file"}:
            return True
        return bool(
            re.search(
                r"\b(?:this|that|it|these|those|same|previous|last|before|again|earlier|reuse|continue|current thing|what i just said)\b",
                text,
            )
        )

    def _apply_active_state_followup(
        self,
        frame: IntentFrame,
        *,
        family: str,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> None:
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        subject = str(active_request_state.get("subject") or parameters.get("target_name") or family.replace("_", " ")).strip()
        operation, target_type, target_text, context_reference, risk_class = self._active_followup_shape(
            family,
            subject=subject,
            parameters=parameters,
        )
        frame.operation = operation
        frame.target_type = target_type
        frame.target_text = target_text
        frame.context_reference = context_reference
        frame.risk_class = risk_class
        frame.native_owner_hint = family
        frame.candidate_route_families = [family]
        frame.generic_provider_allowed = False
        frame.generic_provider_reason = "native_route_candidate_present"
        bound = self._active_followup_context(
            family=family,
            target_type=target_type,
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        if bound is not None:
            frame.extracted_entities["selected_context"] = bound
            frame.context_status = "available"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            if family == "browser_destination" and bound.get("value"):
                frame.target_text = str(bound.get("label") or bound.get("value") or target_text)
            return
        missing_reason = self._active_followup_missing_reason(family)
        frame.context_status = "missing" if missing_reason else "available"
        frame.clarification_needed = bool(missing_reason)
        frame.clarification_reason = missing_reason

    def _active_followup_shape(
        self,
        family: str,
        *,
        subject: str,
        parameters: dict[str, Any],
    ) -> tuple[str, str, str, str, str]:
        if family == "calculations":
            return "calculate", "prior_calculation", "previous calculation", "previous_calculation", "read_only"
        if family == "browser_destination":
            return "open", "website", subject or "current page", "current_page", "external_browser_open"
        if family == "app_control":
            if str(parameters.get("source_case") or "").strip().lower() == "active_apps" or "active app" in subject.lower():
                return "status", "app", "active applications", "previous_result", "read_only"
            operation = str(parameters.get("operation") or parameters.get("action") or "open").strip().lower()
            operation = operation if operation in {"open", "launch", "close", "quit", "status"} else "open"
            return operation, "app", subject or "app", "previous_result", "external_app_open" if operation != "status" else "read_only"
        if family == "file":
            return "open", "file", subject or "current file", "current_file", "internal_surface_open"
        if family == "context_action":
            return "inspect", "selected_text", "selected text", "selected", "read_only"
        if family == "screen_awareness":
            return "inspect", "visible_ui", "visible screen", "visible_target", "read_only"
        if family == "software_control":
            operation = str(parameters.get("operation_type") or parameters.get("operation") or "verify").strip().lower()
            operation = operation if operation in {"install", "uninstall", "update", "repair", "verify"} else "verify"
            target = str(parameters.get("target_name") or subject or "software").strip()
            return operation, "software_package", target, "previous_result", "software_lifecycle" if operation != "verify" else "read_only"
        if family == "network":
            return "status", "system_resource", "network", "previous_result", "read_only"
        if family == "watch_runtime":
            return "status", "system_resource", "runtime", "previous_result", "read_only"
        if family == "workspace_operations":
            return "assemble", "workspace", subject or "workspace", "previous_result", "dry_run_plan"
        if family == "routine":
            return "launch", "routine", subject or "routine", "previous_result", "dry_run_plan"
        if family == "workflow":
            return "launch", "workspace", subject or "workflow", "previous_result", "dry_run_plan"
        if family == "task_continuity":
            return "status", "workspace", subject or "task continuity", "previous_result", "read_only"
        if family == "discord_relay":
            return "send", "discord_recipient", subject or "discord", "previous_result", "external_send"
        if family == "trust_approvals":
            return "verify", "prior_result", subject or "approval request", "previous_result", "trust_sensitive_action"
        return "inspect", "unknown", subject or family, "previous_result", "read_only"

    def _active_followup_context(
        self,
        *,
        family: str,
        target_type: str,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if family == "browser_destination":
            return self._recent_website_context(active_context, recent_tool_results)
        if family == "context_action":
            selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
            if selection.get("value"):
                return {
                    "type": "selected_text",
                    "source": "selection",
                    "label": str(selection.get("preview") or "selected text"),
                    "value": selection.get("value"),
                    "confidence": 0.94,
                }
            return None
        if family == "discord_relay":
            destination = self._discord_destination_from_state(active_request_state)
            selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
            if destination and selection.get("value"):
                return {
                    "type": "discord_payload",
                    "source": "active_request_state",
                    "label": destination,
                    "value": {"destination": destination, "payload": selection.get("value")},
                    "confidence": 0.9,
                }
            return None
        if target_type in {"prior_calculation", "prior_result"}:
            bound = ContextBinder()._prior_calculation(active_context, active_request_state, recent_tool_results)
            if bound is not None:
                return bound
        if family in {"app_control", "network", "watch_runtime", "software_control"}:
            return {"type": target_type, "source": "active_request_state", "label": str(active_request_state.get("subject") or family), "value": dict(active_request_state), "confidence": 0.82}
        if family == "trust_approvals":
            trust = active_request_state.get("trust") if isinstance(active_request_state.get("trust"), dict) else {}
            if trust:
                return {"type": "approval_object", "source": "active_request_state", "label": str(trust.get("request_id") or "approval request"), "value": dict(active_request_state), "confidence": 0.9}
        return None

    def _recent_website_context(self, active_context: dict[str, Any], recent_tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        for entity in IntentFrameExtractor()._recent_entities(active_context, recent_tool_results):
            if not isinstance(entity, dict):
                continue
            kind = str(entity.get("kind") or "").strip().lower()
            url = entity.get("url") or entity.get("value")
            if url and (kind in {"page", "url", "website", "link"} or str(url).startswith(("http://", "https://"))):
                return {
                    "type": "website",
                    "source": "recent_entities",
                    "label": str(entity.get("title") or url),
                    "value": str(url),
                    "confidence": 0.9,
                }
        return None

    def _discord_destination_from_state(self, active_request_state: dict[str, Any]) -> str:
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        destination = str(parameters.get("destination_alias") or parameters.get("recipient") or active_request_state.get("subject") or "").strip()
        if destination.lower() in {"", "discord", "discord relay", "relay", "message"}:
            return ""
        return destination

    def _active_followup_missing_reason(self, family: str) -> str:
        if family == "browser_destination":
            return "destination_context"
        if family == "context_action":
            return "context"
        if family == "discord_relay":
            return "discord_relay_context"
        if family == "calculations":
            return "calculation_context"
        if family == "screen_awareness":
            return "visible_screen"
        if family == "file":
            return "file_context"
        if family in {"workspace_operations", "workflow", "task_continuity"}:
            return "workspace_context"
        if family == "routine":
            return "routine_context"
        return ""

    def _deictic_calculation_signal(self, text: str) -> bool:
        has_deictic = bool(re.search(r"\b(?:this|that|it|previous|last)\b", text))
        has_math_action = bool(
            re.search(r"\b(?:divide|multiply|add|subtract|double|halve|show the steps|steps)\b", text)
            or re.search(r"\bcompare\b.{0,24}\b(?:answer|result|number|calculation|math)\b", text)
        )
        return has_deictic and has_math_action

    def _software_verify_signal(self, text: str) -> bool:
        return bool(re.search(r"\b(?:check|verify|is)\b.{0,36}\b(?:installed|available|on this machine)\b", text))

    def _software_target_text(self, raw_text: str) -> str:
        text = re.sub(r"\b(?:check|verify)\b", "", raw_text, flags=re.IGNORECASE)
        text = re.sub(r"\bif\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:is|installed|available|on this machine|on my computer)\b", "", text, flags=re.IGNORECASE)
        return " ".join(text.split()).strip(" ?") or "software"

    def _software_lifecycle_text(self, text: str) -> bool:
        if any(term in text for term in {"environment", "workspace", "workflow", "paragraph", "text"}):
            return False
        return bool(re.search(r"\b(?:install|download|setup|set up|uninstall|update|upgrade|repair)\b", text))

    def _software_lifecycle_target(self, raw_text: str) -> str:
        text = re.sub(r"\b(?:download\s+and\s+install|install|download|setup|set up|uninstall|update|upgrade|repair)\b", "", raw_text, flags=re.IGNORECASE)
        return " ".join(text.split()).strip(" ?") or "software"

    def _screen_status_signal(self, text: str) -> bool:
        has_question = bool(re.search(r"\b(?:what|which|where)\b", text))
        has_visual_target = bool(
            re.search(r"\b(?:looking\s+at|on\s+(?:my\s+)?screen|visible|in\s+front\s+of\s+me|current\s+view)\b", text)
        )
        return has_question and has_visual_target

    def _workspace_signal(self, text: str) -> bool:
        if _workspace_conceptual_text(text):
            return False
        return bool(
            "workspace" in text
            or re.search(r"\b(?:assemble|gather|snapshot)\b.{0,36}\b(?:project|notes|everything|where we are|where i am)\b", text)
        )

    def _workspace_operation(self, text: str) -> str:
        if any(term in text for term in {"save", "snapshot"}):
            return "save"
        if any(term in text for term in {"open", "restore", "list", "show"}):
            return "open"
        return "assemble"

    def _routine_signal(self, text: str) -> bool:
        if _routine_conceptual_text(text):
            return False
        return bool(
            "routine" in text
            or "saved workflow" in text
            or re.search(r"\bremember\b.{0,24}\b(?:this|that)\b.{0,16}\bworkflow\b", text)
            or re.search(r"\b(?:run|rerun|execute)\b.{0,36}\b(?:health check|normal setup|cleanup|saved workflow)\b", text)
        )

    def _routine_save_signal(self, text: str) -> bool:
        return bool(
            re.search(r"\b(?:save|make|turn|remember)\b.{0,36}\b(?:this|that|workflow|routine)\b", text)
            and re.search(r"\b(?:routine|workflow)\b", text)
        )

    def _workflow_signal(self, text: str) -> bool:
        if any(phrase in text for phrase in {"workflow theory", "workflow philosophy", "workflow diagram", "essay about workflows", "history of workflow automation"}):
            return False
        return bool(
            re.search(r"\b(?:set up|setup|prepare|open|restore|launch|run)\b.{0,36}\b(?:workflow|environment|setup|work context)\b", text)
            or re.search(r"\b(?:writing|research|project|diagnostics|review)\b.{0,24}\b(?:environment|setup|workflow|context)\b", text)
        )

    def _task_continuity_signal(self, text: str) -> bool:
        if _task_conceptual_text(text):
            return False
        return bool(
            re.search(r"\b(?:continue|resume|pick up)\b.{0,24}\b(?:this|that|there|task|previous|where we left off)\b", text)
            or any(
                phrase in text
                for phrase in {
                    "where were we",
                    "where did we leave off",
                    "where we left off",
                    "what should i do next",
                    "still left on this task",
                    "continue from there",
                }
            )
        )

    def _discord_relay_signal(self, text: str) -> bool:
        if _discord_conceptual_text(text):
            return False
        direct_verb = re.search(r"\b(?:send|share|message|post|relay|forward|dm)\b", text)
        pass_along = re.search(r"\bpass\b.{0,12}\b(?:this|that|it)\b.{0,16}\balong\b", text)
        relay_verb = direct_verb or pass_along
        return bool(relay_verb and (re.search(r"\b(?:discord|baby|selected|highlighted|clipboard|this|that|it)\b", text) or pass_along))

    def _expansion_conceptual_near_miss(self, text: str) -> bool:
        return (
            _workspace_conceptual_text(text)
            or any(
                phrase in text
                for phrase in {
                    "workflow theory",
                    "workflow philosophy",
                    "workflow diagram",
                    "essay about workflows",
                    "history of workflow automation",
                }
            )
            or _routine_conceptual_text(text)
            or _task_conceptual_text(text)
            or _discord_conceptual_text(text)
        )

    def _context_reference_from_text(self, text: str) -> str:
        for term in ("selected", "highlighted", "this", "that", "it", "there"):
            if term in text.split():
                return term
        if "current" in text.split():
            return "current"
        if any(term in text.split() for term in {"previous", "last", "same"}):
            return "previous_result"
        return "none"

    def _discord_target(self, raw_text: str) -> str:
        for pattern in (
            r"\b(?:to|with|for)\s+(?P<dest>[A-Za-z][\w.-]{1,40})(?:\s+on\s+Discord)?\b",
            r"\b(?:message|dm)\s+(?P<dest>[A-Za-z][\w.-]{1,40})\b",
        ):
            match = re.search(pattern, raw_text, flags=re.IGNORECASE)
            if match:
                destination = str(match.group("dest") or "").strip(" .,:;!?")
                if destination.lower() not in {"discord", "selected", "highlighted", "text", "this", "that"}:
                    return destination
        return ""

    def _strip_known_verbs(self, raw_text: str) -> str:
        text = re.sub(
            r"^(?:make|create|assemble|gather|open|restore|save|snapshot|list|show|set up|setup|prepare|launch|run|rerun|execute|turn|remember)\s+",
            "",
            raw_text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\b(?:as|called|named)\b.+$", "", text, flags=re.IGNORECASE)
        return " ".join(text.split()).strip(" .,:;!?")
