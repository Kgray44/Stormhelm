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
    "web_retrieval",
    "browser_destination",
    "app_control",
    "file",
    "context_action",
    "context_clarification",
    "unsupported",
    "screen_awareness",
    "camera_awareness",
    "software_control",
    "watch_runtime",
    "network",
    "workspace_operations",
    "routine",
    "workflow",
    "task_continuity",
    "discord_relay",
    "trust_approvals",
    "machine",
    "system_control",
    "terminal",
    "desktop_search",
    "development",
    "time",
    "storage",
    "location",
    "weather",
    "power",
    "resources",
    "window_control",
    "file_operation",
    "maintenance",
    "notes",
    "software_recovery",
}

PLANNER_V2_LEGACY_DEFER_FAMILIES = {
    "comparison",
    "power_projection",
    "trust_approvals",
}


LEGACY_MIGRATION_SCHEDULE: dict[str, tuple[str, str]] = {
    "workspace_operations": ("migrated", "migrated_in_planner_v2_expansion_1"),
    "routine": ("migrated", "migrated_in_planner_v2_expansion_1"),
    "workflow": ("migrated", "migrated_in_planner_v2_expansion_1"),
    "task_continuity": ("migrated", "migrated_in_planner_v2_expansion_1"),
    "discord_relay": ("migrated", "migrated_in_planner_v2_expansion_1"),
    "web_retrieval": ("migrated", "obscura_public_page_rendering_adapter"),
    "camera_awareness": ("migrated", "camera_awareness_c0_foundation"),
    "maintenance": ("scheduled", "medium"),
    "trust_approvals": ("scheduled", "medium"),
    "power": ("scheduled", "low"),
    "weather": ("scheduled", "low"),
    "window_control": ("scheduled", "low"),
    "resources": ("scheduled", "low"),
    "software_recovery": ("scheduled", "medium"),
    "desktop_search": ("migrated", "migrated_in_boundary_alignment"),
    "system_control": ("migrated", "migrated_in_boundary_alignment"),
    "terminal": ("migrated", "migrated_in_boundary_alignment"),
    "machine": ("migrated", "migrated_in_boundary_alignment"),
    "development": ("migrated", "restored_from_legacy_retirement_baseline"),
    "time": ("migrated", "restored_from_legacy_retirement_baseline"),
    "storage": ("migrated", "restored_from_legacy_retirement_baseline"),
    "location": ("migrated", "restored_from_legacy_retirement_baseline"),
    "weather": ("migrated", "restored_from_legacy_retirement_baseline"),
    "power": ("migrated", "restored_from_legacy_retirement_baseline"),
    "resources": ("migrated", "restored_from_legacy_retirement_baseline"),
    "window_control": ("migrated", "restored_from_legacy_retirement_baseline"),
    "file_operation": ("migrated", "restored_from_legacy_retirement_baseline"),
    "maintenance": ("migrated", "restored_from_legacy_retirement_baseline"),
    "notes": ("migrated", "restored_from_legacy_retirement_baseline"),
    "software_recovery": ("migrated", "restored_from_legacy_retirement_baseline"),
}


DIRECT_STATUS_FAMILY_TOOLS: dict[str, tuple[str, str, str, str, bool]] = {
    "development": ("development", "echo", "direct_echo", "echo", False),
    "time": ("system", "clock", "direct_deterministic_fact", "retrieve_current_status", False),
    "storage": ("system", "storage_status", "direct_deterministic_fact", "retrieve_current_status", False),
    "location": ("location", "location_status", "direct_deterministic_fact", "retrieve_current_status", False),
    "weather": ("weather", "weather_current", "direct_deterministic_fact", "retrieve_current_status", False),
    "power": ("system", "power_status", "direct_deterministic_fact", "retrieve_current_status", False),
    "resources": ("system", "resource_status", "direct_deterministic_fact", "retrieve_current_status", False),
    "window_control": ("system", "window_status", "direct_deterministic_fact", "retrieve_current_status", False),
    "file_operation": ("files", "file_operation", "file_operation", "execute_control_command", True),
    "maintenance": ("maintenance", "maintenance_action", "maintenance_action", "execute_control_command", True),
    "notes": ("workspace", "notes_write", "notes_write", "execute_control_command", True),
    "software_recovery": ("software_recovery", "repair_action", "repair_action", "execute_control_command", True),
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


def _web_retrieval_intent(text: str, operation: str) -> str:
    normalized = str(text or "").strip().lower()
    if re.search(r"\b(?:obscura\s+cdp|cdp\s+provider|browser\s+renderer|headless\s+renderer)\b", normalized):
        if re.search(r"\bnetwork\s+summary\b", normalized):
            return "cdp_network_summary"
        return "cdp_inspect"
    if re.search(r"\b(?:dom\s+text|network\s+summary)\b", normalized):
        return "cdp_network_summary" if "network summary" in normalized else "cdp_inspect"
    if "link" in normalized:
        return "extract_links"
    if "render" in normalized:
        return "render_page"
    if operation == "compare" or re.search(r"\b(?:compare|versus|vs|diff)\b", normalized):
        return "compare_pages"
    if "summary" in normalized or "summarize" in normalized:
        return "summarize_page"
    return "read_page"


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
        if frame.native_owner_hint == "camera_awareness":
            return ContextBinding(
                context_reference=frame.context_reference,
                context_type="camera_frame",
                context_source="camera_request",
                status="missing",
                label=frame.target_text or "camera still",
                missing_preconditions=("camera_capture_confirmation",),
            )
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
        if frame.native_owner_hint == "development" and frame.clarification_needed:
            return self._missing(frame, "echo_command_intent")
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
                tool_name = str(frame.extracted_entities.get("tool_name") or "").strip()
                if tool_name in {"workspace_rename", "workspace_tag"}:
                    return ContextBinding(
                        context_reference=frame.context_reference,
                        context_type="workspace",
                        context_source="current_workspace_implicit",
                        status="available",
                        label="current workspace",
                        freshness="current",
                    )
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
        requested_tool = str(frame.extracted_entities.get("tool_name") or "").strip()
        if requested_tool in {"trusted_hook_execute", "trusted_hook_register"}:
            return ContextBinding(
                context_reference=frame.context_reference,
                context_type="routine",
                status="available",
                label=frame.target_text or "trusted hook",
            )
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
        if spec.route_family == "unsupported" and frame.native_owner_hint != "unsupported":
            return RouteCandidate(
                route_family=spec.route_family,
                subsystem=spec.subsystem,
                score=0.0,
                accepted=False,
                score_factors={"unsupported_owner_gate": 0.0},
                decline_reasons=("requires_explicit_unsupported_external_commitment_signal",),
                tool_candidates=spec.tool_candidates,
            )
        if (
            spec.route_family == "desktop_search"
            and frame.native_owner_hint != "desktop_search"
            and not self._desktop_search_signal(frame.normalized_text)
        ):
            return RouteCandidate(
                route_family=spec.route_family,
                subsystem=spec.subsystem,
                score=0.0,
                accepted=False,
                score_factors={"desktop_search_signal_gate": 0.0},
                decline_reasons=("requires_local_file_or_desktop_search_signal",),
                tool_candidates=spec.tool_candidates,
            )
        if spec.route_family == "system_control" and frame.native_owner_hint != "system_control":
            return RouteCandidate(
                route_family=spec.route_family,
                subsystem=spec.subsystem,
                score=0.0,
                accepted=False,
                score_factors={"system_control_signal_gate": 0.0},
                decline_reasons=("requires_explicit_system_control_signal",),
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

    def _desktop_search_signal(self, text: str) -> bool:
        if re.search(r"\b(?:youtube|google|bing|duckduckgo|tripadvisor|amazon|wikipedia|reddit|github)\b", text):
            return False
        if re.search(r"\b(?:search|look up|lookup|find)\b.{0,40}\b(?:web|internet|online|site|website|youtube|google)\b", text):
            return False
        return bool(
            re.search(r"\b(?:find|search|locate|pull up|open)\b.{0,48}\b(?:file|files|folder|folders|document|documents|downloads|desktop|screenshot|screenshots|readme|pdf|docx|txt)\b", text)
            or re.search(r"\b(?:recent|latest)\b.{0,24}\b(?:file|files|document|documents|download|downloads|screenshot|screenshots)\b", text)
            or re.search(r"\b(?:documents|downloads|desktop)\b.{0,24}\b(?:file|folder|document)\b", text)
        )


class RouteArbitrator:
    def decide(
        self,
        frame: IntentFrame,
        candidates: tuple[RouteCandidate, ...],
    ) -> RouteDecision:
        considered = tuple(candidate.route_family for candidate in candidates)
        if (
            frame.generic_provider_allowed
            and frame.generic_provider_reason == "operator_wrapper_browser_near_miss_no_native_action"
        ):
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
                generic_provider_gate_reason=frame.generic_provider_reason,
                authoritative=True,
            )
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
            selected_unsupported = selected.route_family == "unsupported"
            return RouteDecision(
                routing_engine="planner_v2",
                selected_route_family=selected.route_family,
                selected_subsystem=selected.subsystem,
                selected_route_spec=selected.route_family,
                score=selected.score,
                route_candidates=selected_candidates,
                candidate_specs_considered=considered,
                native_decline_reasons=self._declines(candidates),
                generic_provider_allowed=selected_unsupported,
                generic_provider_gate_reason="unsupported_external_commitment_allows_safe_planning_help"
                if selected_unsupported
                else "native_route_candidate_present",
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
        if family == "development":
            return "Should I run that echo exactly, or did you want a different development command?"
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
        if family == "web_retrieval":
            urls = [
                str(url).strip()
                for url in frame.extracted_entities.get("urls", [])
                if str(url).strip()
            ]
            if not urls:
                url = str(binding.value or frame.extracted_entities.get("url") or frame.target_text or "").strip()
                urls = [url] if url else []
            intent = _web_retrieval_intent(frame.normalized_text, frame.operation)
            include_html = bool(re.search(r"\b(?:html|source)\b", frame.normalized_text))
            preferred_provider = "obscura_cdp" if intent.startswith("cdp_") else "auto"
            return PlanDraft(
                family,
                "web_retrieval",
                frame.operation,
                "url",
                subject=urls[0] if urls else subject,
                tool_name="web_retrieval_fetch",
                tool_arguments={
                    "urls": urls,
                    "intent": intent,
                    "preferred_provider": preferred_provider,
                    "require_rendering": intent in {"render_page", "compare_pages"} or intent.startswith("cdp_"),
                    "include_links": intent
                    in {"extract_links", "summarize_page", "read_page", "compare_pages", "cdp_inspect", "cdp_network_summary"},
                    "include_html": include_html or intent.startswith("cdp_"),
                },
                request_type_hint="web_retrieval_response",
                execution_type="web_retrieval_extract",
                requires_execution=True,
            )
        if family == "browser_destination":
            url = str(binding.value or frame.extracted_entities.get("url") or frame.target_text)
            requested_tool = str(frame.extracted_entities.get("tool_name") or "").strip()
            deck_requested = surface_mode.strip().lower() == "deck" or bool(
                re.search(r"\b(?:in|inside|within)\s+(?:the\s+)?deck\b", frame.normalized_text)
            )
            tool = (
                requested_tool
                if requested_tool in {"external_open_url", "deck_open_url"}
                else "deck_open_url"
                if deck_requested
                else "external_open_url"
            )
            return PlanDraft(family, "browser", "open", "website", subject=url, tool_name=tool, tool_arguments={"url": url}, request_type_hint="direct_action", execution_type="resolve_url_then_open_in_browser", requires_execution=True)
        if family == "app_control":
            if frame.operation == "status":
                return PlanDraft(family, "system", "status", "app", subject="active_apps", tool_name="active_apps", tool_arguments={"focus": "applications"}, request_type_hint="direct_deterministic_fact", execution_type="retrieve_current_status")
            action = "close" if frame.operation in {"quit", "close"} else "open"
            return PlanDraft(family, "system", action, "app", subject=subject, tool_name="app_control", tool_arguments={"action": action, "target": subject}, request_type_hint="direct_action", execution_type="execute_control_command", requires_execution=True)
        if family == "file":
            path = str(binding.value or frame.extracted_entities.get("path") or frame.target_text)
            requested_tool = str(frame.extracted_entities.get("tool_name") or "").strip()
            deck_requested = surface_mode.strip().lower() == "deck" or bool(
                re.search(r"\b(?:in|inside|within)\s+(?:the\s+)?deck\b", frame.normalized_text)
            )
            tool = (
                requested_tool
                if requested_tool in {"file_reader", "deck_open_file", "external_open_file"}
                else "file_reader"
                if frame.operation == "inspect"
                else "deck_open_file"
                if deck_requested
                else "external_open_file"
            )
            operation = "inspect" if tool == "file_reader" else frame.operation
            return PlanDraft(family, "files", operation, "file", subject=path, tool_name=tool, tool_arguments={"path": path}, request_type_hint="file_read" if tool == "file_reader" else "direct_action", execution_type="read_file" if tool == "file_reader" else "execute_control_command", requires_execution=tool != "file_reader")
        if family == "context_action":
            return PlanDraft(family, "context", frame.operation, "selected_text", subject="selection", tool_name="context_action", tool_arguments={"operation": "inspect", "source": "selection"}, request_type_hint="context_action", execution_type="execute_context_action")
        if family == "context_clarification":
            return PlanDraft(family, "context", "clarify", "unknown", subject="ambiguous context", request_type_hint="context_clarification", execution_type="clarify_route_context")
        if family == "screen_awareness":
            return PlanDraft(family, "screen_awareness", frame.operation, "visible_ui", subject="visible_screen", request_type_hint="screen_awareness_response", execution_type="screen_awareness_preflight")
        if family == "camera_awareness":
            return PlanDraft(
                family,
                "camera_awareness",
                "inspect",
                "camera_frame",
                subject=subject or "camera still",
                request_type_hint="camera_awareness_confirmation",
                execution_type="camera_awareness_c0_mock_or_permission_gate",
            )
        if family == "software_control":
            return PlanDraft(family, "software_control", frame.operation, "software_package", subject=subject, request_type_hint="software_control_response", execution_type="software_control_execute", requires_execution=frame.operation in {"install", "uninstall", "update", "repair"})
        if family == "network":
            requested_tool = str(frame.extracted_entities.get("tool_name") or "").strip()
            tool_name = requested_tool if requested_tool in {"network_status", "network_throughput", "network_diagnosis"} else "network_status"
            request_type_hint = "deterministic_diagnostic_request" if tool_name == "network_diagnosis" else "direct_deterministic_fact"
            execution_type = "diagnostic_summary" if tool_name == "network_diagnosis" else "retrieve_current_status"
            focus = "diagnosis" if tool_name == "network_diagnosis" else "throughput" if tool_name == "network_throughput" else "overview"
            return PlanDraft(family, "system", "status", "system_resource", subject="network", tool_name=tool_name, tool_arguments={"focus": focus}, request_type_hint=request_type_hint, execution_type=execution_type)
        if family == "watch_runtime":
            source_case = str(frame.extracted_entities.get("source_case") or "").strip().lower()
            if source_case == "browser_context" or str(frame.extracted_entities.get("tool_name") or "").strip().lower() == "browser_context":
                return PlanDraft(family, "context", "inspect", "current_page", subject=subject or "browser page", tool_name="browser_context", tool_arguments={"operation": "current_page"}, request_type_hint="browser_context", execution_type="retrieve_browser_context")
            return PlanDraft(family, "operations", "status", "system_resource", subject="runtime", tool_name="activity_summary", tool_arguments={}, request_type_hint="activity_summary", execution_type="summarize_activity")
        if family == "machine":
            source_case = str(frame.extracted_entities.get("source_case") or "").strip().lower()
            tool_name = "system_info" if source_case == "system_info" or str(frame.raw_text).strip().lower().startswith("/system") else "machine_status"
            return PlanDraft(family, "system", "status", "system_resource", subject=subject or "machine", tool_name=tool_name, tool_arguments={"focus": "identity"}, request_type_hint="direct_deterministic_fact", execution_type="retrieve_identity")
        if family == "system_control":
            return PlanDraft(family, "system", frame.operation, "system_resource", subject=subject or "settings", tool_name="system_control", tool_arguments={"action": "open_settings", "target": subject or "settings", "dry_run": True}, request_type_hint="direct_action", execution_type="execute_control_command", requires_execution=True)
        if family == "terminal":
            command = str(frame.extracted_entities.get("shell_command") or frame.target_text or "open_terminal").strip()
            return PlanDraft(family, "terminal", frame.operation, "workspace", subject=command or "terminal", tool_name="shell_command", tool_arguments={"command": command, "dry_run": True}, request_type_hint="terminal_preflight", execution_type="execute_control_command", requires_execution=True)
        if family == "desktop_search":
            source_case = str(frame.extracted_entities.get("source_case") or "").strip().lower()
            requested_tool = str(frame.extracted_entities.get("tool_name") or "").strip().lower()
            if source_case == "recent_files" or requested_tool == "recent_files":
                return PlanDraft(
                    family,
                    "system",
                    "status",
                    "system_resource",
                    subject="recent_files",
                    tool_name="recent_files",
                    tool_arguments={},
                    request_type_hint="direct_deterministic_fact",
                    execution_type="retrieve_current_status",
                )
            return PlanDraft(family, "workflow", frame.operation, frame.target_type, subject=subject or "desktop_search", tool_name="desktop_search", tool_arguments={"query": subject or frame.raw_text, "action": "search"}, request_type_hint="search_and_act", execution_type="search_then_open")
        if family == "development" and frame.clarification_needed:
            return PlanDraft(family, "development", "clarify", "unknown", subject=subject or "echo command", request_type_hint="development_echo_clarification", execution_type="clarify_route_context")
        if family in DIRECT_STATUS_FAMILY_TOOLS:
            subsystem, default_tool, request_type_hint, execution_type, requires_execution = DIRECT_STATUS_FAMILY_TOOLS[family]
            tool_name = str(frame.extracted_entities.get("tool_name") or default_tool).strip() or default_tool
            if family == "development":
                payload = str(frame.extracted_entities.get("echo_text") or subject or frame.raw_text).strip()
                args = {"text": payload}
            elif family == "notes":
                args = {"text": subject or frame.raw_text, "dry_run": True}
            elif family in {"file_operation", "maintenance", "software_recovery"}:
                args = {"query": frame.raw_text, "target": subject, "dry_run": True}
            elif family == "storage" and tool_name == "storage_diagnosis":
                args = {"focus": "capacity_pressure"}
                request_type_hint = "deterministic_diagnostic_request"
                execution_type = "diagnostic_summary"
            elif family == "resources" and tool_name == "resource_diagnosis":
                args = {"present_in": "none"}
                request_type_hint = "deterministic_diagnostic_request"
                execution_type = "diagnostic_summary"
            elif family == "power" and tool_name == "power_diagnosis":
                args = {"present_in": "none"}
                request_type_hint = "deterministic_diagnostic_request"
                execution_type = "diagnostic_summary"
            elif family == "power" and tool_name == "power_projection":
                args = {
                    "metric": "time_to_empty" if "empty" in frame.normalized_text else "drain_rate" if "drain" in frame.normalized_text else "time_to_percent",
                    "target_percent": None,
                    "assume_unplugged": "unplug" in frame.normalized_text,
                    "present_in": "none",
                }
                request_type_hint = "deterministic_projection_request"
                execution_type = "project_power_state"
            else:
                args = {"focus": family}
            return PlanDraft(
                family,
                subsystem,
                frame.operation,
                frame.target_type,
                subject=subject,
                tool_name=tool_name,
                tool_arguments=args,
                request_type_hint=request_type_hint,
                execution_type=execution_type,
                requires_execution=requires_execution,
            )
        if family == "workspace_operations":
            tool_name = self._workspace_tool(frame)
            action = tool_name.replace("workspace_", "")
            if tool_name in {"workspace_assemble", "workspace_restore", "workspace_archive"}:
                args = {"query": frame.raw_text}
            elif tool_name == "workspace_rename":
                args = {"new_name": str(frame.extracted_entities.get("new_name") or frame.extracted_entities.get("alternate_target") or frame.target_text or "").strip()}
            elif tool_name == "workspace_tag":
                tags = frame.extracted_entities.get("tags")
                if isinstance(tags, (list, tuple)):
                    args = {"tags": [str(tag) for tag in tags if str(tag).strip()]}
                else:
                    label = str(frame.extracted_entities.get("alternate_target") or frame.target_text or "").strip()
                    args = {"tags": [label]} if label else {}
            else:
                args = {}
            return PlanDraft(family, "workspace", frame.operation, "workspace", subject=subject or action, tool_name=tool_name, tool_arguments=args, request_type_hint="workspace_operation", execution_type=f"{action}_workspace", requires_execution=True)
        if family == "routine":
            requested_tool = str(frame.extracted_entities.get("tool_name") or "").strip()
            tool_name = requested_tool if requested_tool in {"routine_execute", "routine_save", "trusted_hook_execute", "trusted_hook_register"} else "routine_save" if frame.operation == "save" else "routine_execute"
            action = (
                "register_trusted_hook"
                if tool_name == "trusted_hook_register"
                else "execute_trusted_hook"
                if tool_name == "trusted_hook_execute"
                else "save_routine"
                if tool_name == "routine_save"
                else "execute_routine"
            )
            args: dict[str, Any] = {"query": frame.raw_text, "target": subject}
            hook_name = str(frame.extracted_entities.get("hook_name") or "").strip()
            hook_path = str(frame.extracted_entities.get("path") or "").strip()
            if hook_name:
                args["hook_name"] = hook_name
            if hook_path:
                args["path"] = hook_path
            return PlanDraft(family, "routine", frame.operation, "routine", subject=subject or "routine", tool_name=tool_name, tool_arguments=args, request_type_hint=tool_name, execution_type=action, requires_execution=True)
        if family == "workflow":
            return PlanDraft(family, "workflow", frame.operation, "workspace", subject=subject or "workflow", tool_name="workflow_execute", tool_arguments={"query": frame.raw_text, "workflow_kind": subject or "workflow"}, request_type_hint="workflow_execution", execution_type="execute_workflow", requires_execution=True)
        if family == "task_continuity":
            source_case = str(frame.extracted_entities.get("source_case") or "").strip().lower()
            tool_name = "workspace_where_left_off" if "left off" in frame.normalized_text or "where were we" in frame.normalized_text or source_case == "workspace_where_left_off" else "workspace_next_steps"
            action = "where_left_off" if tool_name == "workspace_where_left_off" else "next_steps"
            return PlanDraft(family, "workspace", frame.operation, "workspace", subject=action, tool_name=tool_name, tool_arguments={}, request_type_hint="task_continuity", execution_type="summarize_workspace")
        if family == "discord_relay":
            payload = binding.value if isinstance(binding.value, dict) else {}
            return PlanDraft(family, "discord_relay", "send", "discord_recipient", subject=str(payload.get("destination") or subject or "discord"), tool_name=None, tool_arguments={"preview_only": True, **payload}, request_type_hint="discord_relay_preview", execution_type="discord_relay_preview", requires_execution=True)
        return PlanDraft(family, decision.selected_subsystem, frame.operation, frame.target_type, subject=subject)

    def _workspace_tool(self, frame: IntentFrame) -> str:
        text = frame.normalized_text
        source_case = str(frame.extracted_entities.get("source_case") or "").strip().lower()
        tool_name = str(frame.extracted_entities.get("tool_name") or "").strip()
        if tool_name.startswith("workspace_"):
            return tool_name
        if source_case in {
            "workspace_restore",
            "workspace_assemble",
            "workspace_save",
            "workspace_list",
            "workspace_archive",
            "workspace_clear",
            "workspace_rename",
            "workspace_tag",
        }:
            return source_case
        if re.search(r"\brename\b.{0,40}\b(?:workspace|wrkspace)\b", text):
            return "workspace_rename"
        if re.search(r"\btag\b.{0,40}\b(?:workspace|wrkspace)\b", text):
            return "workspace_tag"
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
        if plan.tool_name in {"deck_open_url", "deck_open_file"}:
            risk = "internal_surface_open"
        if plan.tool_name == "file_reader":
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
        if decision.selected_route_family == "unsupported":
            return ResultStateDraft(
                result_state="unsupported",
                response_mode="summary",
                user_facing_status="blocked_unsupported",
                message="That request is unsupported as a native command, so no real external action will run.",
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
        planner_text = self._strong_operator_route_probe_inner(raw_text) or raw_text
        normalized = self._normalizer.normalize(planner_text, surface_mode=surface_mode, active_module=active_module)
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

    def _strong_operator_route_probe_inner(self, raw_text: str) -> str:
        match = re.match(
            (
                r"^\s*(?:open|route|run|use|try|diagnose|inspect)\s+or\s+"
                r"(?:open|route|run|use|try|diagnose|inspect)\s+this\s+"
                r"if\s+that\s+is\s+the\s+right\s+route\s*:\s*(?P<inner>.+?)\s*$"
            ),
            str(raw_text or ""),
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        inner = " ".join(str(match.group("inner") or "").split()).strip()
        if not inner:
            return ""
        normalized = normalize_phrase(inner)
        if re.search(r"\b(?:almost|nearly|sort of|kind of)\b", normalized) and re.search(
            r"\b(?:not exactly|not quite|but not|instead)\b",
            normalized,
        ):
            return ""
        if inner.lstrip().startswith(("/", "\\")):
            return inner
        if re.search(r"\bhttps?://|\bwww\.", inner, flags=re.IGNORECASE):
            return inner
        if re.search(r"(?:[A-Za-z]:\\|\\\\|/)[^\s,;?!]+", inner):
            return inner
        if self._direct_status_family(normalized, inner.lower()):
            return inner
        if (
            self._workspace_signal(normalized)
            or self._routine_signal(normalized)
            or self._workflow_signal(normalized)
            or self._task_continuity_signal(normalized)
            or re.search(r"\b(?:continue|resume|pick up)\b.{0,24}\bwhere\s+i\s+left\s+off\b", normalized)
            or self._discord_relay_signal(normalized)
            or self._software_lifecycle_text(normalized)
        ):
            return inner
        if re.search(r"\b(?:open|launch|navigate|go to|show)\b.{0,48}\b(?:browser|page|site|url|youtube|deck)\b", normalized):
            return inner
        if re.search(r"\b(?:find|search|locate)\b.{0,48}\b(?:on this computer|on my computer|desktop|file|folder|readme)\b", normalized):
            return inner
        return ""

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
        raw_lower = str(frame.raw_text or "").strip().lower()
        if re.search(r"\bbattery\s+acid\b", text):
            frame.operation = "unknown"
            frame.target_type = "unknown"
            frame.target_text = ""
            frame.native_owner_hint = None
            frame.candidate_route_families = []
            frame.generic_provider_allowed = True
            frame.generic_provider_reason = "power_near_miss_no_native_action"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
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
        if self._unsupported_external_commitment_signal(text):
            frame.operation = "send"
            frame.target_type = "unknown"
            frame.target_text = "external commitment"
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "external_send"
            frame.native_owner_hint = "unsupported"
            frame.candidate_route_families = ["unsupported"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        if self._saved_locations_list_signal(text):
            frame.operation = "status"
            frame.target_type = "system_resource"
            frame.target_text = "saved locations"
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "location"
            frame.candidate_route_families = ["location"]
            frame.extracted_entities["source_case"] = "saved_locations"
            frame.extracted_entities["tool_name"] = "saved_locations"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        if self._recent_files_status_signal(text):
            frame.operation = "status"
            frame.target_type = "file"
            frame.target_text = "recent files"
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "desktop_search"
            frame.candidate_route_families = ["desktop_search"]
            frame.extracted_entities["source_case"] = "recent_files"
            frame.extracted_entities["tool_name"] = "recent_files"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        if self._browser_correction_near_miss(text):
            frame.operation = "unknown"
            frame.target_type = "unknown"
            frame.target_text = ""
            if re.search(r"\b(?:stormhelm\s+)?route\s+for\s+this\b", text):
                frame.native_owner_hint = None
                frame.candidate_route_families = []
                frame.generic_provider_allowed = True
                frame.generic_provider_reason = "operator_wrapper_browser_near_miss_no_native_action"
                frame.clarification_needed = False
                frame.clarification_reason = ""
                return frame
            self._set_context_clarification(
                frame,
                reason="browser_destination_near_miss",
                context_status="missing",
            )
            return frame
        deck_file_path = self._explicit_deck_file_path(frame.raw_text)
        if deck_file_path:
            frame.operation = "open"
            frame.target_type = "file"
            frame.target_text = deck_file_path
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "internal_surface_open"
            frame.native_owner_hint = "file"
            frame.candidate_route_families = ["file"]
            frame.extracted_entities["path"] = deck_file_path
            frame.extracted_entities["source_case"] = "deck_open_file"
            frame.extracted_entities["tool_name"] = "deck_open_file"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        if self._echo_command_near_miss(text, raw_lower):
            frame.operation = "inspect"
            frame.target_type = "unknown"
            frame.target_text = self._echo_payload(frame.raw_text)
            frame.context_reference = "none"
            frame.context_status = "ambiguous"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "development"
            frame.candidate_route_families = ["development"]
            frame.extracted_entities["echo_text"] = self._echo_payload(frame.raw_text)
            frame.extracted_entities["source_case"] = "echo"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = True
            frame.clarification_reason = "echo_command_intent"
            return frame
        note_payload = self._slash_note_payload(frame.raw_text)
        if note_payload:
            frame.operation = "save"
            frame.target_type = "selected_text"
            frame.target_text = note_payload
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "dry_run_plan"
            frame.native_owner_hint = "notes"
            frame.candidate_route_families = ["notes"]
            frame.extracted_entities["note_text"] = note_payload
            frame.extracted_entities["source_case"] = "notes_write"
            frame.extracted_entities["tool_name"] = "notes_write"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        if raw_lower.startswith("/system"):
            frame.operation = "status"
            frame.target_type = "system_resource"
            frame.target_text = "system information"
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "machine"
            frame.candidate_route_families = ["machine"]
            frame.extracted_entities["source_case"] = "system_info"
            frame.extracted_entities["tool_name"] = "system_info"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        if self._slash_system_command(frame.raw_text):
            frame.operation = "status"
            frame.target_type = "system_resource"
            frame.target_text = "system information"
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "machine"
            frame.candidate_route_families = ["machine"]
            frame.extracted_entities["source_case"] = "system_info"
            frame.extracted_entities["tool_name"] = "system_info"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        if raw_lower.startswith("/shell"):
            command = frame.raw_text.split(maxsplit=1)[1] if len(frame.raw_text.split(maxsplit=1)) > 1 else ""
            frame.operation = "launch"
            frame.target_type = "workspace"
            frame.target_text = command or "shell"
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "dry_run_plan"
            frame.native_owner_hint = "terminal"
            frame.candidate_route_families = ["terminal"]
            frame.extracted_entities["shell_command"] = command or "open_terminal"
            frame.extracted_entities["tool_name"] = "shell_command"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        file_reader_path = self._slash_read_path(frame.raw_text)
        if file_reader_path:
            frame.operation = "inspect"
            frame.target_type = "file"
            frame.target_text = file_reader_path
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "file"
            frame.candidate_route_families = ["file"]
            frame.extracted_entities["path"] = file_reader_path
            frame.extracted_entities["source_case"] = "file_reader"
            frame.extracted_entities["tool_name"] = "file_reader"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        if self._workspace_list_signal(text):
            frame.operation = "open"
            frame.target_type = "workspace"
            frame.target_text = "workspace list"
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "workspace_operations"
            frame.candidate_route_families = ["workspace_operations"]
            frame.extracted_entities["source_case"] = "workspace_list"
            frame.extracted_entities["tool_name"] = "workspace_list"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        if frame.native_owner_hint == "trust_approvals":
            return frame
        trusted_hook = self._trusted_hook_request(frame.raw_text)
        if trusted_hook:
            tool_name = str(trusted_hook.get("tool_name") or "trusted_hook_execute")
            frame.operation = "save" if tool_name == "trusted_hook_register" else "launch"
            frame.target_type = "routine"
            frame.target_text = str(trusted_hook.get("hook_name") or "trusted hook")
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "dry_run_plan"
            frame.native_owner_hint = "routine"
            frame.candidate_route_families = ["routine"]
            frame.extracted_entities.update(trusted_hook)
            frame.extracted_entities["source_case"] = tool_name
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            return frame
        if self._system_control_signal(text):
            frame.operation = "open" if re.search(r"\b(?:open|show|launch|start|opne)\b", text) else "status"
            frame.target_type = "system_resource"
            frame.target_text = self._settings_target(frame.raw_text)
            frame.context_reference = "none"
            frame.context_status = "available"
            frame.risk_class = "internal_surface_open"
            frame.native_owner_hint = "system_control"
            frame.candidate_route_families = ["system_control"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
        web_page_context = self._web_retrieval_current_page_context(text, active_context, recent_tool_results)
        if web_page_context is not None:
            frame.operation = "render" if "render" in text else "compare" if re.search(r"\b(?:compare|versus|vs|diff)\b", text) else "inspect"
            frame.target_type = "url"
            frame.target_text = str(web_page_context.get("value") or "current page")
            frame.context_reference = "current_page"
            frame.context_status = "available"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "web_retrieval"
            frame.candidate_route_families = ["web_retrieval"]
            frame.extracted_entities["url"] = str(web_page_context.get("value") or "")
            frame.extracted_entities["urls"] = [str(web_page_context.get("value") or "")]
            frame.extracted_entities["source_case"] = "active_browser_page"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
        elif self._browser_context_signal(text):
            frame.operation = "inspect"
            frame.target_type = "current_page"
            frame.target_text = "browser page"
            frame.context_reference = "current_page"
            frame.context_status = "available"
            frame.risk_class = "read_only"
            frame.native_owner_hint = "watch_runtime"
            frame.candidate_route_families = ["watch_runtime"]
            frame.extracted_entities["source_case"] = "browser_context"
            frame.extracted_entities["tool_name"] = "browser_context"
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
        direct_family = self._direct_status_family(text, raw_lower)
        if direct_family and not frame.native_owner_hint:
            self._apply_direct_status_frame(frame, direct_family)
        elif frame.native_owner_hint == "power" and not frame.extracted_entities.get("tool_name"):
            frame.extracted_entities["tool_name"] = self._power_tool_name(text)
            frame.extracted_entities["source_case"] = frame.extracted_entities["tool_name"]
        elif frame.native_owner_hint == "resources" and not frame.extracted_entities.get("tool_name"):
            frame.extracted_entities["tool_name"] = self._resource_tool_name(text)
            frame.extracted_entities["source_case"] = frame.extracted_entities["tool_name"]
        if self._vague_dual_deictic_without_binding(text, active_context, active_request_state):
            self._set_context_clarification(
                frame,
                reason="ambiguous_deictic_no_owner",
                context_status="ambiguous",
            )
        active_followup_owner = self._active_state_followup_owner(frame, active_request_state)
        if active_followup_owner:
            self._apply_active_state_followup(
                frame,
                family=active_followup_owner,
                active_context=active_context,
                active_request_state=active_request_state,
                recent_tool_results=recent_tool_results,
            )
        if self._browser_semantic_control_signal(text):
            action_like = bool(
                re.search(r"\b(?:click|press|focus|type|enter|submit|check|uncheck|select)\b", text)
            )
            frame.operation = "execute" if action_like else "inspect"
            frame.target_type = "visible_ui"
            frame.target_text = self._strip_known_verbs(frame.raw_text) or "browser semantic target"
            frame.context_reference = "visible_target"
            frame.context_status = "missing"
            frame.risk_class = "direct_ui_action" if action_like else "read_only"
            frame.native_owner_hint = "screen_awareness"
            frame.candidate_route_families = ["screen_awareness"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = False
            frame.clarification_reason = ""
            frame.extracted_entities["source_case"] = "browser_semantic_control"
        if self._ambiguous_deictic_clarification_signal(frame, active_request_state):
            self._set_context_clarification(
                frame,
                reason="ambiguous_deictic_no_owner",
                context_status="ambiguous" if active_context else "missing",
            )
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
            and self._software_lifecycle_text(text)
        ):
            frame.target_type = "software_package"
            frame.target_text = self._software_lifecycle_target(frame.raw_text)
            frame.risk_class = "software_lifecycle"
            frame.native_owner_hint = "software_control"
            frame.candidate_route_families = ["software_control"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
        if self._camera_awareness_signal(text):
            frame.operation = "inspect"
            frame.target_type = "camera_frame"
            frame.target_text = self._camera_target_text(frame.raw_text)
            frame.context_reference = "explicit_camera_request"
            frame.context_status = "missing"
            frame.risk_class = "privacy_sensitive"
            frame.native_owner_hint = "camera_awareness"
            frame.candidate_route_families = ["camera_awareness"]
            frame.generic_provider_allowed = False
            frame.generic_provider_reason = "native_route_candidate_present"
            frame.clarification_needed = True
            frame.clarification_reason = "camera_capture_confirmation"
            frame.extracted_entities["source_provenance"] = "camera_request"
            frame.extracted_entities["capture_mode"] = "single_still"
            frame.extracted_entities["analysis_mode"] = self._camera_analysis_mode(text)
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
            workspace_tool = self._workspace_tool(frame)
            frame.extracted_entities["tool_name"] = workspace_tool
            frame.extracted_entities["source_case"] = workspace_tool
            if workspace_tool == "workspace_rename":
                new_name = self._workspace_rename_target(frame.raw_text)
                if new_name:
                    frame.extracted_entities["new_name"] = new_name
            elif workspace_tool == "workspace_tag":
                tags = self._workspace_tags(frame.raw_text)
                if tags:
                    frame.extracted_entities["tags"] = tags
            if any(term in text.split() for term in {"this", "that", "there"}) or any(phrase in text for phrase in {"where we are", "where i am"}):
                frame.context_reference = "this" if "this" in text.split() else "that" if "that" in text.split() else "there"
                has_context = bool(active_context.get("current_resolution") or active_context.get("workspace") or active_context.get("current_task"))
                if workspace_tool in {"workspace_rename", "workspace_tag"}:
                    has_context = True
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
        pending_preview = parameters.get("pending_preview") if isinstance(parameters.get("pending_preview"), dict) else {}
        pending_source = str(pending_preview.get("source_case") or "").strip().lower()
        if not self._active_state_is_reusable(active_request_state):
            return ""
        if self._explicit_confirmation_signal(frame.normalized_text) and pending_source == "routine_save":
            return "routine"
        if trust and stage == "awaiting_confirmation" and self._followup_signal(frame.normalized_text):
            return "trust_approvals"
        if family not in PLANNER_V2_ROUTE_FAMILIES:
            return ""
        if family in {"generic_provider", "unsupported", "context_clarification"}:
            return ""
        if frame.native_owner_hint and frame.native_owner_hint != "context_clarification":
            return ""
        text = frame.normalized_text
        if not self._followup_signal(text, frame=frame):
            return ""
        return family

    def _active_state_is_reusable(self, active_request_state: dict[str, Any]) -> bool:
        if not isinstance(active_request_state, dict) or not active_request_state:
            return False
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        if active_request_state.get("context_reusable") is False or parameters.get("context_reusable") is False:
            return False
        freshness = str(
            parameters.get("context_freshness")
            or active_request_state.get("context_freshness")
            or "current"
        ).strip().lower()
        return freshness not in {"stale", "expired", "ambiguous", "conflicting"}

    def _explicit_confirmation_signal(self, text: str) -> bool:
        normalized = re.sub(r"[\s,]+", " ", text.strip().lower()).strip()
        return bool(
            normalized in {"yes", "go ahead", "confirm", "continue", "proceed", "approve", "allow", "do it"}
            or normalized.startswith(("yes ", "go ahead", "confirm ", "continue ", "proceed ", "approve ", "allow "))
        )

    def _ambiguous_deictic_clarification_signal(self, frame: IntentFrame, active_request_state: dict[str, Any]) -> bool:
        if frame.native_owner_hint:
            return False
        active_family = str(active_request_state.get("family") or "").strip().lower()
        if (
            active_family
            and active_family not in {"generic_provider", "unsupported", "context_clarification"}
            and self._active_state_is_reusable(active_request_state)
        ):
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

    def _set_context_clarification(
        self,
        frame: IntentFrame,
        *,
        reason: str,
        context_status: str = "missing",
    ) -> None:
        frame.operation = "clarify"
        frame.target_type = "unknown"
        frame.target_text = "current context"
        if frame.context_reference == "none":
            frame.context_reference = "previous_result" if self._followup_signal(frame.normalized_text) else "this"
        frame.context_status = context_status
        frame.risk_class = "read_only"
        frame.native_owner_hint = "context_clarification"
        frame.candidate_route_families = ["context_clarification"]
        frame.generic_provider_allowed = False
        frame.generic_provider_reason = "ambiguous_deictic_requires_native_clarification"
        frame.clarification_needed = True
        frame.clarification_reason = reason

    def _browser_correction_near_miss(self, text: str) -> bool:
        near_miss = bool(
            re.search(r"\b(?:almost|nearly|sort of|kind of)\b", text)
            and re.search(r"\b(?:not exactly|not quite|but not|instead)\b", text)
        )
        if not near_miss:
            return False
        if re.search(
            r"\b(?:open|launch|navigate|go to|show)\b.{0,48}\b(?:https?://|www\.|browser|page|site|url|deck|file)\b",
            text,
        ):
            return True
        return bool(
            re.search(r"\b(?:almost|nearly|sort of|kind of)\b.{0,32}\b(?:open|launch|navigate|go to)\b.{0,32}\bbrowser\b", text)
            and re.search(r"\b(?:not exactly|not quite|but not|instead)\b", text)
        )

    def _explicit_deck_file_path(self, raw_text: str) -> str:
        text = str(raw_text or "")
        if not re.search(r"\b(?:open|show|display|view)\b", text, flags=re.IGNORECASE):
            return ""
        match = re.search(
            r"(?:^|[\s\"'])(?P<path>(?:[A-Za-z]:\\|\\\\|/)[^\r\n]+?)\s+\b(?:in|inside|within)\s+(?:the\s+)?deck\b",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        return str(match.group("path") or "").strip(" .,:;!?\"'")

    def _vague_dual_deictic_without_binding(
        self,
        text: str,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
    ) -> bool:
        if not re.fullmatch(r"(?:no,\s*)?use\s+(?:this|that|it)\s+for\s+(?:this|that|it)", text.strip()):
            return False
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        source_keys = {"source", "source_text", "source_payload", "selected_context", "payload", "content"}
        return not any(self._context_value_present(parameters.get(key)) for key in source_keys)

    def _system_control_signal(self, text: str) -> bool:
        if re.search(r"\b(?:file|note|notes|document|readme)\b", text):
            return False
        if re.fullmatch(r"(?:could you\s+|please\s+|pls\s+)?(?:open|show|launch|start)\s+(?:system\s+)?settings", text):
            return False
        return bool(
            re.search(r"\b(?:open|show|launch|start|opne)\b.{0,36}\b(?:bluetooth|wi-?fi|wifi|display|sound|privacy|network|location)\s+settings?\b", text)
            or re.search(r"\b(?:bluetooth|wi-?fi|wifi|display|sound|privacy|network|location)\b.{0,24}\bsettings?\b", text)
        )

    def _direct_status_family(self, text: str, raw_lower: str) -> str:
        if raw_lower.startswith("/echo"):
            return "development"
        if self._clear_echo_command(text, raw_lower):
            return "development"
        if raw_lower.startswith("/note"):
            return "notes"
        if re.search(r"\b(?:what time is it|current time|time right now)\b", text):
            return "time"
        if re.search(r"\b(?:what machine|what computer|machine name|machine status|computer status|os version|time ?zone|timezone|this computer)\b", text):
            return "machine"
        if self._network_status_signal(text):
            return "network"
        if self._storage_diagnosis_signal(text) or re.search(
            r"\b(?:storage status|storage usage|storage space|disk status|disk space|disk usage|drive space|free space)\b",
            text,
        ):
            return "storage"
        if re.search(r"\b(?:where am i|current location|my location)\b", text):
            return "location"
        if re.search(r"\bweather\b", text) and not re.search(r"\b(?:weathering|whether)\b", text):
            return "weather"
        if re.search(r"\bpower\s+(?:at|from|for)\b.{0,32}\d", text):
            return ""
        if re.search(r"\bbattery\s+acid\b", text):
            return ""
        if re.search(r"\b(?:battery|charging|power)\b", text):
            return "power"
        if re.search(r"\b(?:cpu|memory|ram|resource usage|computer sluggish)\b", text):
            return "resources"
        if re.search(r"\b(?:windows are open|active windows|focused window)\b", text):
            return "window_control"
        if re.search(r"\b(?:rename|move|delete|tag|archive)\b.{0,40}\b(?:file|files|screenshots|folder|folders)\b", text):
            return "file_operation"
        if re.search(r"\b(?:clean up|cleanup|archive stale)\b.{0,40}\b(?:downloads|files|folder|folders)\b", text):
            return "maintenance"
        if re.search(r"\b(?:fix|repair|diagnose)\b.{0,40}\b(?:wifi|wi-fi|network|dns|explorer)\b", text):
            return "software_recovery"
        return ""

    def _saved_locations_list_signal(self, text: str) -> bool:
        if re.search(r"\b(?:location|locations|saved place|saved places)\b.{0,24}\b(?:concept|theory|idea|architecture|settings)\b", text):
            return False
        return bool(
            re.fullmatch(r"(?:my\s+)?saved\s+(?:locations?|places?)", text.strip())
            or re.fullmatch(r"(?:saved\s+)?home\s+location", text.strip())
            or
            re.search(r"\b(?:show|list|display|view|see|open)\b.{0,48}\b(?:my\s+)?saved\s+(?:locations?|places?)\b", text)
            or re.search(r"\b(?:what|which)\b.{0,36}\bsaved\s+(?:locations?|places?)\b", text)
        )

    def _recent_files_status_signal(self, text: str) -> bool:
        if re.search(r"\b(?:recent|latest)\b.{0,24}\b(?:file|files|document|documents)\b.{0,24}\b(?:concept|theory|idea|architecture)\b", text):
            return False
        return bool(
            re.fullmatch(r"(?:show\s+|list\s+|display\s+|view\s+|see\s+|open\s+)?(?:my\s+)?(?:recent|latest)\s+(?:files?|documents?)", text.strip())
            or re.fullmatch(r"what\s+was\s+i\s+working\s+on", text.strip())
        )

    def _workspace_list_signal(self, text: str) -> bool:
        if re.search(r"\b(?:workspace|workspaces|wrkspace|wrkspaces)\b.{0,24}\b(?:concept|theory|idea|philosophy|design)\b", text):
            return False
        return bool(
            re.search(r"\b(?:show|list|display|view|see|open)\b.{0,32}\b(?:my\s+)?(?:workspaces|workspace list|wrkspaces|wrkspace list)\b", text)
            or re.search(r"\b(?:what|which)\b.{0,24}\b(?:workspaces|wrkspaces)\b", text)
        )

    def _apply_direct_status_frame(self, frame: IntentFrame, family: str) -> None:
        frame.native_owner_hint = family
        frame.candidate_route_families = [family]
        frame.context_reference = "none"
        frame.context_status = "available"
        frame.generic_provider_allowed = False
        frame.generic_provider_reason = "native_route_candidate_present"
        frame.clarification_needed = False
        frame.clarification_reason = ""
        if family in {"file_operation", "maintenance", "notes", "software_recovery"}:
            frame.operation = "save" if family == "notes" else "repair" if family in {"maintenance", "software_recovery"} else "update"
            frame.risk_class = "dry_run_plan"
        else:
            frame.operation = "status" if family != "development" else "inspect"
            frame.risk_class = "read_only"
        frame.target_type = "current_app" if family == "window_control" else "file" if family == "file_operation" else "system_resource"
        if family == "development":
            frame.target_type = "unknown"
            frame.extracted_entities["echo_text"] = self._echo_payload(frame.raw_text)
        if family == "notes":
            frame.target_type = "selected_text"
        if family in DIRECT_STATUS_FAMILY_TOOLS:
            frame.extracted_entities["tool_name"] = DIRECT_STATUS_FAMILY_TOOLS[family][1]
        if family == "network":
            frame.extracted_entities["tool_name"] = self._network_tool_name(frame.normalized_text)
        if family == "power":
            frame.extracted_entities["tool_name"] = self._power_tool_name(frame.normalized_text)
        if family == "resources":
            frame.extracted_entities["tool_name"] = self._resource_tool_name(frame.normalized_text)
        if family == "storage":
            frame.extracted_entities["tool_name"] = "storage_diagnosis" if self._storage_diagnosis_signal(frame.normalized_text) else "storage_status"
        frame.extracted_entities["source_case"] = (
            str(frame.extracted_entities.get("tool_name") or family)
            if family in {"network", "power", "resources", "storage"}
            else family
            if family not in {"time", "development"}
            else "clock"
            if family == "time"
            else "echo"
        )
        frame.target_text = self._strip_known_verbs(frame.raw_text) or family.replace("_", " ")

    def _echo_payload(self, raw_text: str) -> str:
        text = str(raw_text or "").strip()
        text = re.sub(r"\b(?:almost|nearly|sort of|kind of)\b\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*,?\s*\b(?:but\s+)?not\s+(?:exactly|quite)\b.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^/echo\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^echo\s+", "", text, flags=re.IGNORECASE)
        return " ".join(text.split()).strip() or "echo"

    def _clear_echo_command(self, text: str, raw_lower: str) -> bool:
        if self._echo_command_near_miss(text, raw_lower):
            return False
        if re.search(r"\becho\s+(?:chamber|location|effect|concept|idea|theory)\b", text):
            return False
        return bool(re.match(r"^(?:echo|repeat back|say back)\b\s+\S", text))

    def _echo_command_near_miss(self, text: str, raw_lower: str) -> bool:
        if not re.search(r"(?:^|\s)/?echo\b", raw_lower):
            return False
        return bool(
            re.search(r"\b(?:almost|nearly|sort of|kind of)\b", text)
            and re.search(r"\b(?:not exactly|not quite|but not|instead)\b", text)
        )

    def _settings_target(self, raw_text: str) -> str:
        target = re.sub(r"\b(?:open|show|launch|start|opne)\b", "", raw_text, flags=re.IGNORECASE)
        target = " ".join(target.split()).strip(" .,:;!?")
        return target or "system settings"

    def _unsupported_external_commitment_signal(self, text: str) -> bool:
        transactional = bool(re.search(r"\b(?:book|buy|purchase|order|pay|reserve)\b", text))
        external_target = bool(re.search(r"\b(?:flight|hotel|ticket|item|subscription|real\s+world|pay\s+for)\b", text))
        immediate = bool(re.search(r"\b(?:now|for real|actually|immediately)\b", text))
        return transactional and external_target and immediate

    def _slash_system_command(self, raw_text: str) -> bool:
        return bool(re.search(r"(?:^|\s)/system(?:\b|$)", str(raw_text or ""), flags=re.IGNORECASE))

    def _slash_read_path(self, raw_text: str) -> str:
        match = re.search(r"(?:^|\s)/read\s+(?P<path>(?:[A-Za-z]:\\|\\\\|/)[^\s,;?!]+)", str(raw_text or ""), flags=re.IGNORECASE)
        if not match:
            return ""
        return str(match.group("path") or "").strip(" .,:;!?\"'")

    def _slash_note_payload(self, raw_text: str) -> str:
        match = re.search(r"(?:^|\s)/note(?:\s+|$)(?P<payload>.*)$", str(raw_text or ""), flags=re.IGNORECASE)
        if not match:
            return ""
        payload = str(match.group("payload") or "").strip()
        payload = re.sub(r"\s+(?:without\s+.*|if\s+that\s+is\s+the\s+right\s+route.*)$", "", payload, flags=re.IGNORECASE).strip()
        return " ".join(payload.split()).strip(" .,:;!?\"'")

    def _trusted_hook_request(self, raw_text: str) -> dict[str, Any]:
        text = str(raw_text or "").strip()
        register = re.search(
            r"\bregister\s+trusted\s+hook\s+(?P<hook>.+?)\s+for\s+(?P<path>(?:[A-Za-z]:\\|\\\\|/)[^\s,;?!]+)",
            text,
            flags=re.IGNORECASE,
        )
        if register:
            return {
                "tool_name": "trusted_hook_register",
                "hook_name": " ".join(str(register.group("hook") or "").split()).strip(" .,:;!?"),
                "path": str(register.group("path") or "").strip(" .,:;!?\"'"),
            }
        execute = re.search(
            r"\brun\s+trusted\s+hook\s+(?P<hook>[A-Za-z0-9_.-]+(?:\s+[A-Za-z0-9_.-]+){0,4})",
            text,
            flags=re.IGNORECASE,
        )
        if execute:
            hook = " ".join(str(execute.group("hook") or "").split()).strip(" .,:;!?")
            hook = re.sub(r"\s+(?:real\s+quick|quick)\b.*$", "", hook, flags=re.IGNORECASE).strip()
            return {"tool_name": "trusted_hook_execute", "hook_name": hook or "trusted hook"}
        return {}

    def _network_status_signal(self, text: str) -> bool:
        if re.search(r"\b(?:neural\s+network|network\s+architecture|network\s+effects)\b", text):
            return False
        return bool(
            re.search(r"\b(?:am i online|internet status|connection status|which wifi|which wi-fi|ssid)\b", text)
            or re.search(r"\b(?:internet|network|wifi|wi-fi)\b.{0,36}\b(?:speed|throughput|lagging|slow|down|outage|diagnos|broken)\b", text)
            or re.search(r"\b(?:why|diagnos|troubleshoot|fix)\b.{0,36}\b(?:wifi|wi-fi|network|internet|connection)\b", text)
        )

    def _network_tool_name(self, text: str) -> str:
        if re.search(r"\b(?:speed|throughput|bandwidth)\b", text):
            return "network_throughput"
        if re.search(r"\b(?:why|lagging|slow|outage|diagnos|troubleshoot|broken|fix)\b", text):
            return "network_diagnosis"
        return "network_status"

    def _power_tool_name(self, text: str) -> str:
        if re.search(r"\b(?:why|diagnos|troubleshoot)\b.{0,40}\b(?:battery|charging|power|drain|draining)\b", text):
            return "power_diagnosis"
        if re.search(r"\b(?:battery|power)\b.{0,32}\b(?:drain|draining|drains)\b", text):
            return "power_diagnosis"
        if re.search(r"\b(?:how long|time to|until|empty|full|unplug|power draw|drain rate)\b", text):
            return "power_projection"
        return "power_status"

    def _resource_tool_name(self, text: str) -> str:
        if self._resource_diagnosis_signal(text):
            return "resource_diagnosis"
        return "resource_status"

    def _resource_diagnosis_signal(self, text: str) -> bool:
        return bool(
            re.search(r"\b(?:why|diagnos|troubleshoot|what'?s wrong)\b.{0,48}\b(?:computer|machine|pc|cpu|memory|ram|gpu|resources?)\b", text)
            or re.search(r"\b(?:computer|machine|pc|system)\b.{0,40}\b(?:sluggish|slow|laggy|bogged down|dragging)\b", text)
            or re.search(r"\b(?:cpu|memory|ram|gpu|resources?)\b.{0,40}\b(?:bottleneck|pressure|spike|high|pegged|sluggish|slow)\b", text)
        )

    def _storage_diagnosis_signal(self, text: str) -> bool:
        return bool(
            re.search(r"\b(?:why|diagnos|what'?s|what is)\b.{0,36}\b(?:disk|drive|storage)\b.{0,36}\b(?:full|almost full|filling|pressure|low)\b", text)
            or re.search(r"\b(?:disk|drive|storage)\b.{0,36}\b(?:almost full|full|filling up|pressure|low space)\b", text)
        )

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
                (
                    r"\b(?:this|that|it|these|those|same|previous|last|before|again|earlier|reuse|continue|"
                    r"current thing|what i just said|other one|the other|go ahead|confirm)\b"
                    r"|^\s*yes\b"
                ),
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
        if self._explicit_confirmation_signal(frame.normalized_text) and self._active_state_confirmation_target(active_request_state, parameters) is None:
            self._set_context_clarification(
                frame,
                reason="no_pending_confirmation",
                context_status="missing",
            )
            return
        pending_preview = parameters.get("pending_preview") if isinstance(parameters.get("pending_preview"), dict) else {}
        if family == "routine" and str(pending_preview.get("source_case") or "").strip().lower() == "routine_save":
            parameters = {**parameters, "source_case": "routine_save", "tool_name": "routine_save"}
        route = active_request_state.get("route") if isinstance(active_request_state.get("route"), dict) else {}
        route_tool_name = str(route.get("tool_name") or "").strip()
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
        for key in (
            "source_case",
            "tool_name",
            "path",
            "url",
            "operation",
            "operation_type",
            "target_name",
            "destination_name",
            "destination_alias",
            "target_url",
            "new_name",
            "tags",
            "shell_command",
            "pending_preview",
            "alternate_target",
            "alternate_target_url",
            "alternate_target_path",
            "previous_choice",
        ):
            if key in parameters and self._context_value_present(parameters.get(key)):
                frame.extracted_entities[key] = parameters.get(key)
        if route_tool_name:
            frame.extracted_entities.setdefault("tool_name", route_tool_name)
            frame.extracted_entities.setdefault("source_case", route_tool_name)
        if self._correction_signal(frame.normalized_text) and self._active_state_alternate_target(parameters) is None:
            frame.context_status = "missing"
            frame.clarification_needed = True
            frame.clarification_reason = "alternate_target"
            return
        bound = self._active_followup_context(
            frame=frame,
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

    def _context_value_present(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

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
            source_case = str(parameters.get("source_case") or "").strip().lower()
            operation = str(parameters.get("operation_type") or parameters.get("operation") or "").strip().lower()
            if not operation:
                if "install" in source_case:
                    operation = "install"
                elif "uninstall" in source_case:
                    operation = "uninstall"
                elif "update" in source_case:
                    operation = "update"
                elif "repair" in source_case:
                    operation = "repair"
                else:
                    operation = "verify"
            operation = operation if operation in {"install", "uninstall", "update", "repair", "verify"} else "verify"
            target = str(parameters.get("target_name") or subject or "software").strip()
            return operation, "software_package", target, "previous_result", "software_lifecycle" if operation != "verify" else "read_only"
        if family == "network":
            return "status", "system_resource", "network", "previous_result", "read_only"
        if family == "watch_runtime":
            source_case = str(parameters.get("source_case") or "").strip().lower()
            if source_case == "browser_context":
                return "inspect", "current_page", subject or "browser page", "previous_result", "read_only"
            return "status", "system_resource", "runtime", "previous_result", "read_only"
        if family == "machine":
            return "status", "system_resource", subject or "machine", "previous_result", "read_only"
        if family == "system_control":
            return "open", "system_resource", subject or "settings", "previous_result", "internal_surface_open"
        if family == "terminal":
            return "launch", "workspace", subject or "terminal", "previous_result", "dry_run_plan"
        if family == "desktop_search":
            return "search", "file", subject or "desktop search", "previous_result", "read_only"
        if family == "workspace_operations":
            source_case = str(parameters.get("source_case") or parameters.get("tool_name") or "").strip().lower()
            if "restore" in source_case:
                operation = "open"
            elif "save" in source_case:
                operation = "save"
            elif "list" in source_case:
                operation = "status"
            else:
                operation = "assemble"
            return operation, "workspace", subject or "workspace", "previous_result", "dry_run_plan"
        if family == "routine":
            source_case = str(parameters.get("source_case") or parameters.get("tool_name") or "").strip().lower()
            operation = "save" if "save" in source_case else "launch"
            return operation, "routine", subject or "routine", "previous_result", "dry_run_plan"
        if family == "workflow":
            return "launch", "workspace", subject or "workflow", "previous_result", "dry_run_plan"
        if family == "task_continuity":
            return "status", "workspace", subject or "task continuity", "previous_result", "read_only"
        if family == "discord_relay":
            return "send", "discord_recipient", subject or "discord", "previous_result", "external_send"
        if family == "trust_approvals":
            return "verify", "prior_result", subject or "approval request", "previous_result", "trust_sensitive_action"
        if family in DIRECT_STATUS_FAMILY_TOOLS:
            if family in {"file_operation", "maintenance", "notes", "software_recovery"}:
                operation = "save" if family == "notes" else "repair" if family in {"maintenance", "software_recovery"} else "update"
                risk = "dry_run_plan"
            else:
                operation = "status" if family != "development" else "inspect"
                risk = "read_only"
            target_type = "current_app" if family == "window_control" else "file" if family == "file_operation" else "system_resource"
            if family == "development":
                target_type = "prior_result"
            if family == "notes":
                target_type = "selected_text"
            return operation, target_type, subject or family.replace("_", " "), "previous_result", risk
        return "inspect", "unknown", subject or family, "previous_result", "read_only"

    def _active_followup_context(
        self,
        *,
        frame: IntentFrame,
        family: str,
        target_type: str,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        correction_target = self._active_state_alternate_target(parameters)
        if correction_target is not None and self._correction_signal(frame.normalized_text):
            return {
                "type": target_type,
                "source": "active_request_state.alternate_target",
                "label": str(correction_target.get("label") or correction_target.get("value") or "alternate target"),
                "value": correction_target.get("value"),
                "confidence": 0.88,
            }
        preview_target = self._active_state_confirmation_target(active_request_state, parameters)
        if preview_target is not None and self._explicit_confirmation_signal(frame.normalized_text):
            return {
                "type": "pending_preview",
                "source": "active_request_state.pending_preview",
                "label": str(preview_target.get("label") or preview_target.get("value") or "pending preview"),
                "value": preview_target.get("value"),
                "confidence": 0.9,
            }
        if family == "browser_destination":
            bound = self._recent_website_context(active_context, recent_tool_results)
            if bound is not None:
                return bound
            url = str(parameters.get("url") or parameters.get("target_url") or "").strip()
            if not url:
                structured_query = active_request_state.get("structured_query")
                slots = structured_query.get("slots") if isinstance(structured_query, dict) and isinstance(structured_query.get("slots"), dict) else {}
                tool_arguments = slots.get("tool_arguments") if isinstance(slots.get("tool_arguments"), dict) else {}
                url = str(tool_arguments.get("url") or tool_arguments.get("target_url") or "").strip()
            if url:
                return {
                    "type": "website",
                    "source": "active_request_state",
                    "label": str(active_request_state.get("subject") or url),
                    "value": url,
                    "confidence": 0.87,
                }
            return None
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
        if family == "file":
            path = str(parameters.get("path") or parameters.get("target_path") or "").strip()
            if not path:
                structured_query = active_request_state.get("structured_query")
                slots = structured_query.get("slots") if isinstance(structured_query, dict) and isinstance(structured_query.get("slots"), dict) else {}
                tool_arguments = slots.get("tool_arguments") if isinstance(slots.get("tool_arguments"), dict) else {}
                path = str(tool_arguments.get("path") or tool_arguments.get("target_path") or "").strip()
            if path:
                return {
                    "type": "file",
                    "source": "active_request_state",
                    "label": str(active_request_state.get("subject") or path),
                    "value": path,
                    "confidence": 0.87,
                }
            return None
        if target_type in {"prior_calculation", "prior_result"}:
            bound = ContextBinder()._prior_calculation(active_context, active_request_state, recent_tool_results)
            if bound is not None:
                return bound
        if family in {
            "app_control",
            "network",
            "watch_runtime",
            "software_control",
            "routine",
            "workspace_operations",
            "workflow",
            "task_continuity",
            "machine",
            "system_control",
            "terminal",
            "desktop_search",
            "development",
            "time",
            "storage",
            "location",
            "weather",
            "power",
            "resources",
            "window_control",
            "file_operation",
            "maintenance",
            "notes",
            "software_recovery",
        }:
            return {"type": target_type, "source": "active_request_state", "label": str(active_request_state.get("subject") or family), "value": dict(active_request_state), "confidence": 0.82}
        if family == "trust_approvals":
            trust = active_request_state.get("trust") if isinstance(active_request_state.get("trust"), dict) else {}
            if trust:
                return {"type": "approval_object", "source": "active_request_state", "label": str(trust.get("request_id") or "approval request"), "value": dict(active_request_state), "confidence": 0.9}
        return None

    def _correction_signal(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:no[, ]+|nah[, ]+|not\s+that|not\s+that\s+one|use\s+the\s+other|other\s+one|the\s+other)\b",
                text,
            )
        )

    def _active_state_alternate_target(self, parameters: dict[str, Any]) -> dict[str, Any] | None:
        path = str(parameters.get("alternate_target_path") or "").strip()
        if path:
            return {"label": str(parameters.get("alternate_target") or path), "value": path}
        url = str(parameters.get("alternate_target_url") or "").strip()
        if url:
            return {"label": str(parameters.get("alternate_target") or url), "value": url}
        target = parameters.get("alternate_target")
        if self._context_value_present(target):
            return {"label": str(target), "value": target}
        return None

    def _active_state_confirmation_target(
        self,
        active_request_state: dict[str, Any],
        parameters: dict[str, Any],
    ) -> dict[str, Any] | None:
        pending_preview = parameters.get("pending_preview") if isinstance(parameters.get("pending_preview"), dict) else {}
        trust = active_request_state.get("trust") if isinstance(active_request_state.get("trust"), dict) else {}
        pending_id = str(
            parameters.get("pending_confirmation_id")
            or parameters.get("pending_preview_id")
            or pending_preview.get("id")
            or trust.get("request_id")
            or (
                "software_control_confirmation"
                if str(active_request_state.get("family") or "").strip().lower() == "software_control"
                and str(parameters.get("request_stage") or "").strip().lower()
                in {"awaiting_confirmation", "awaiting_approval", "pending_confirmation"}
                else ""
            )
            or ""
        ).strip()
        if not (pending_preview or trust or pending_id):
            return None
        value = (
            parameters.get("url")
            or parameters.get("target_url")
            or parameters.get("path")
            or parameters.get("target_path")
            or parameters.get("new_name")
            or parameters.get("target_name")
            or parameters.get("destination_alias")
            or parameters.get("destination_name")
            or parameters.get("alternate_target")
            or active_request_state.get("subject")
        )
        if not self._context_value_present(value):
            value = dict(active_request_state)
        label = (
            parameters.get("destination_alias")
            or parameters.get("destination_name")
            or parameters.get("target_name")
            or parameters.get("new_name")
            or parameters.get("alternate_target")
            or active_request_state.get("subject")
            or "pending preview"
        )
        return {"label": str(label), "value": value}

    def _recent_website_context(self, active_context: dict[str, Any], recent_tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        active_item = active_context.get("active_item") if isinstance(active_context.get("active_item"), dict) else {}
        active_url = active_item.get("url") or active_item.get("value")
        active_kind = str(active_item.get("kind") or "").strip().lower()
        if active_url and (active_kind in {"browser", "browser-tab", "page", "url", "website", "link"} or str(active_url).startswith(("http://", "https://"))):
            return {
                "type": "website",
                "source": "active_context",
                "label": str(active_item.get("title") or active_url),
                "value": str(active_url),
                "confidence": 0.94,
            }
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
        if any(term in text for term in {"environment", "workspace", "workflow", "paragraph", "text", "file", "folder"}):
            return False
        return bool(re.search(r"\b(?:install|download|setup|set up|uninstall|update|upgrade|repair)\b", text))

    def _software_lifecycle_target(self, raw_text: str) -> str:
        text = re.sub(r"\b(?:download\s+and\s+install|install|download|setup|set up|uninstall|update|upgrade|repair)\b", "", raw_text, flags=re.IGNORECASE)
        return " ".join(text.split()).strip(" ?") or "software"

    def _camera_awareness_signal(self, text: str) -> bool:
        if self._camera_conceptual_or_settings_near_miss(text):
            return False
        if re.search(r"\b(?:screen|window|popup|visible ui|on my screen|desktop)\b", text):
            return False
        if re.search(r"\b(?:camera|webcam)\b", text):
            return True
        if re.search(r"\b(?:what\s+am\s+i\s+holding|what\s+is\s+this\s+i(?:'|’)??m\s+holding|thing\s+i(?:'|’)??m\s+holding|in\s+my\s+hand)\b", text):
            return True
        if re.search(r"\b(?:holding|in\s+front\s+of\s+me|held\s+up)\b", text) and re.search(
            r"\b(?:what|identify|read|look|inspect|check|does|can)\b",
            text,
        ):
            return True
        if re.search(r"\b(?:resistor\s+value|connector\s+is\s+this|solder\s+joint|label\s+in\s+front\s+of\s+me|component\s+is\s+this|part\s+is\s+this)\b", text):
            return True
        if self._camera_comparison_signal(text):
            return True
        if self._camera_guidance_signal(text):
            return True
        return False

    def _camera_comparison_signal(self, text: str) -> bool:
        if re.search(r"\b(?:how\s+does|how\s+do|what\s+is|explain)\b.{0,32}\b(?:image\s+comparison|before\s+and\s+after)\b", text):
            return False
        if re.search(r"\b(?:front\b.{0,40}\bback|back\b.{0,40}\bfront)\b", text) and re.search(
            r"\b(?:pcb|board|part|camera|show|capture)\b", text
        ):
            return True
        if re.search(r"\b(?:before\b.{0,48}\bafter|after\b.{0,48}\bbefore)\b", text) and re.search(
            r"\b(?:compare|solder|joint|photo|image|picture|capture|show)\b", text
        ):
            return True
        if re.search(r"\bcompare\b.{0,48}\b(?:two\s+)?(?:images?|photos?|pictures?|connectors?|parts?|captures?|stills?)\b", text):
            return True
        if re.search(r"\bwhich\b.{0,24}\b(?:image|photo|picture)\b.{0,24}\b(?:clearer|better|sharpest|clearest)\b", text):
            return True
        if re.search(r"\bcompare\b.{0,48}\b(?:close[ -]?up|full view|whole view|context)\b", text):
            return True
        return False

    def _camera_guidance_signal(self, text: str) -> bool:
        if re.search(r"\b(?:in\s+general|shutter\s+speed|aperture|iso|how\s+do\s+cameras\s+focus|how\s+does\s+a\s+camera\s+focus)\b", text):
            return False
        guidance_action = re.search(
            r"\b(?:retake|capture\s+better|better\s+(?:picture|photo|image|shot|still)|clearer\s+(?:picture|photo|image|shot|still)|see\s+better|read\s+it|why\s+can(?:'|â€™)??t\s+you\s+read|move\s+closer|what\s+angle|what\s+do\s+you\s+need\s+to\s+see|guide\s+me\s+to\s+capture)\b",
            text,
        )
        if not guidance_action:
            return False
        if re.search(r"\b(?:why\s+can(?:'|â€™)??t\s+you\s+read|read\s+it|see\s+better)\b", text) and not re.search(
            r"\b(?:camera|photo|picture|image|shot|still|capture|part|label|marking|connector|resistor|solder|pcb|board)\b",
            text,
        ):
            return False
        return bool(
            re.search(
                r"\b(?:this|that|it|camera|photo|picture|image|shot|still|capture|part|label|marking|connector|resistor|solder|pcb|board)\b",
                text,
            )
        )

    def _camera_conceptual_or_settings_near_miss(self, text: str) -> bool:
        if re.search(r"\b(?:open|find|search|install|update|driver|drivers|settings|privacy settings)\b.{0,24}\b(?:camera|webcam)\b", text):
            return True
        if re.search(r"\b(?:camera|webcam)\b.{0,24}\b(?:settings|drivers|driver|online)\b", text):
            return True
        if re.search(r"\b(?:what\s+is\s+a|how\s+do|how\s+does|how\s+do\s+i\s+use|explain|examples?|show\s+me\s+examples?)\b.{0,48}\b(?:camera|cameras|webcam|webcams|connector|connectors|resistor|resistors|solder\s+joint|color\s+codes?)\b", text):
            return True
        if re.search(r"\bwhat\s+is\s+a\s+[a-z0-9 -]{0,32}\b(?:connector|resistor|camera|webcam)\b", text):
            return True
        return False

    def _camera_analysis_mode(self, text: str) -> str:
        if self._camera_guidance_signal(text):
            return "guidance"
        if self._camera_comparison_signal(text):
            return "compare"
        if re.search(r"\b(?:read|label|text|say)\b", text):
            return "read_text"
        if re.search(r"\b(?:bad|broken|damage|solder|joint|wrong)\b", text):
            return "troubleshoot"
        if re.search(r"\b(?:what|identify|connector|resistor|part|holding)\b", text):
            return "identify"
        return "inspect"

    def _camera_target_text(self, raw_text: str) -> str:
        text = re.sub(r"\b(?:can\s+you|could\s+you|please|look\s+at|take\s+a\s+camera\s+look\s+at|with\s+the\s+camera|using\s+the\s+camera|identify|what\s+is|what\s+am\s+i|does|can|read|inspect|check)\b", "", raw_text, flags=re.IGNORECASE)
        text = " ".join(text.split()).strip(" ?.") or "camera still"
        return text[:96]

    def _screen_status_signal(self, text: str) -> bool:
        if (
            re.search(r"\b(?:in\s+front\s+of\s+me|holding|held\s+up|in\s+my\s+hand)\b", text)
            and re.search(
                r"\b(?:resistor|connector|jst|ic\s+marking|component\s+marking|solder\s+joint|pcb|circuit\s+board)\b",
                text,
            )
            and not re.search(r"\b(?:screen|window|popup|desktop|visible ui|on my screen)\b", text)
        ):
            return False
        has_question = bool(re.search(r"\b(?:what|which|where)\b", text))
        has_visual_target = bool(
            re.search(r"\b(?:looking\s+at|on\s+(?:my\s+)?screen|visible|in\s+front\s+of\s+me|current\s+view)\b", text)
        )
        return has_question and has_visual_target

    def _browser_semantic_control_signal(self, text: str) -> bool:
        if re.search(r"\b(?:open|launch|go to|navigate|summarize|summary|extract|fetch|render|download)\b", text):
            return False
        has_control_target = bool(
            re.search(
                r"\b(?:button|field|fields|input|textbox|text\s+box|checkbox|radio|dropdown|select|combobox|link|dialog|popup|warning|alert|form)\b",
                text,
            )
        )
        if not has_control_target:
            return False
        action_like = bool(
            re.search(r"\b(?:click|press|focus|type|enter|submit|check|uncheck|select)\b", text)
        )
        question_like = bool(re.search(r"\b(?:what|which|where|find|locate|show)\b", text))
        page_context = bool(
            re.search(r"\b(?:this|current|page|screen|visible|browser|web\s*page|site)\b", text)
        )
        where_is_target = bool(
            re.search(r"\bwhere\s+is\b.{0,60}\b(?:button|field|link|dialog|popup|warning|alert|form)\b", text)
        )
        return action_like or where_is_target or (question_like and page_context)

    def _workspace_signal(self, text: str) -> bool:
        if _workspace_conceptual_text(text):
            return False
        return bool(
            "workspace" in text
            or re.search(r"\b(?:assemble|gather|snapshot)\b.{0,36}\b(?:project|notes|everything|where we are|where i am)\b", text)
        )

    def _workspace_tool(self, frame: IntentFrame) -> str:
        text = frame.normalized_text
        source_case = str(frame.extracted_entities.get("source_case") or "").strip().lower()
        tool_name = str(frame.extracted_entities.get("tool_name") or "").strip()
        if tool_name.startswith("workspace_"):
            return tool_name
        if source_case in {
            "workspace_restore",
            "workspace_assemble",
            "workspace_save",
            "workspace_list",
            "workspace_archive",
            "workspace_clear",
            "workspace_rename",
            "workspace_tag",
        }:
            return source_case
        if re.search(r"\brename\b.{0,40}\b(?:workspace|wrkspace)\b", text):
            return "workspace_rename"
        if re.search(r"\btag\b.{0,40}\b(?:workspace|wrkspace)\b", text):
            return "workspace_tag"
        if "restore" in text or "open" in text:
            return "workspace_restore"
        if "save" in text or "snapshot" in text:
            return "workspace_save"
        if "list" in text or "show" in text:
            return "workspace_list"
        return "workspace_assemble"

    def _workspace_operation(self, text: str) -> str:
        if re.search(r"\brename\b.{0,40}\b(?:workspace|wrkspace)\b", text):
            return "rename"
        if re.search(r"\btag\b.{0,40}\b(?:workspace|wrkspace)\b", text):
            return "tag"
        if any(term in text for term in {"save", "snapshot"}):
            return "save"
        if any(term in text for term in {"open", "restore", "list", "show"}):
            return "open"
        return "assemble"

    def _workspace_rename_target(self, raw_text: str) -> str:
        match = re.search(r"\brename\b.{0,28}\b(?:workspace|wrkspace)\b\s+to\s+(?P<name>.+)$", raw_text, flags=re.IGNORECASE)
        if not match:
            return ""
        name = str(match.group("name") or "")
        name = re.sub(r"\s+(?:real\s+quick|quick\s+quick|without\s+.*|if\s+that\s+is\s+the\s+right\s+route.*)$", "", name, flags=re.IGNORECASE)
        return " ".join(name.split()).strip(" .,:;!?\"'")

    def _workspace_tags(self, raw_text: str) -> list[str]:
        match = re.search(r"\btag\b.{0,28}\b(?:workspace|wrkspace)\b(?:\s+with)?\s+(?P<tags>.+)$", raw_text, flags=re.IGNORECASE)
        if not match:
            return []
        tag_text = str(match.group("tags") or "")
        tag_text = re.sub(r"\s+(?:real\s+quick|quick\s+quick|without\s+.*|if\s+that\s+is\s+the\s+right\s+route.*)$", "", tag_text, flags=re.IGNORECASE)
        tag_text = " ".join(tag_text.split()).strip(" .,:;!?\"'")
        if not tag_text:
            return []
        if "," in tag_text:
            return [part.strip() for part in tag_text.split(",") if part.strip()]
        return [tag_text]

    def _routine_signal(self, text: str) -> bool:
        if _routine_conceptual_text(text):
            return False
        return bool(
            "routine" in text
            or "trusted hook" in text
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
        if self._browser_context_signal(text) or "forum post" in text:
            return False
        direct_verb = re.search(r"\b(?:send|share|message|relay|forward|dm)\b", text)
        explicit_post = re.search(r"\bpost\b.{0,24}\b(?:to|in)\b.{0,24}\b(?:discord|channel|chat|server|dm|message)\b", text) or re.search(
            r"\bpost\s+(?:this|that|it)\b",
            text,
        )
        pass_along = re.search(r"\bpass\b.{0,12}\b(?:this|that|it)\b.{0,16}\balong\b", text)
        relay_verb = direct_verb or explicit_post or pass_along
        return bool(relay_verb and (re.search(r"\b(?:discord|baby|selected|highlighted|clipboard|this|that|it)\b", text) or pass_along))

    def _browser_context_signal(self, text: str) -> bool:
        return bool(
            any(
                phrase in text
                for phrase in {
                    "add this page to the workspace",
                    "add this article to the workspace",
                    "add this page as a reference",
                    "collect the references from these tabs",
                    "collect references from these tabs",
                    "pull in the browser references related to this project",
                    "summarize this article",
                    "summarize this page",
                    "summarize the current page",
                    "show me the source i was just reading",
                    "find the page i was just reading",
                    "find the page from earlier",
                    "find the tab",
                    "find the page",
                    "bring up the page",
                    "bring that page forward",
                }
            )
            or (" tab " in f" {text} " and text.startswith(("find ", "show ", "bring ")))
            or ("page about" in text and any(text.startswith(prefix) for prefix in {"find ", "show ", "bring "}))
            or re.search(r"\b(?:what|which)\b.{0,24}\b(?:browser\s+)?(?:page|tab)\b.{0,24}\bam i on\b", text)
            or re.search(r"\b(?:what|which)\b.{0,24}\b(?:page|tab)\b.{0,24}\b(?:open|active|current)\b.{0,24}\b(?:browser|tab)\b", text)
            or re.search(r"\bcurrent\b.{0,16}\b(?:browser\s+)?(?:page|tab)\b", text)
        )

    def _web_retrieval_current_page_context(
        self,
        text: str,
        active_context: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not re.search(r"\b(?:read|summarize|inspect|extract|render|compare|parse)\b", text):
            return None
        if re.search(r"\b(?:open|launch|go to|navigate|click|tap|press|send|share|relay|message|install|download)\b", text):
            return None
        if not re.search(r"\b(?:this|current|active|page|article|url|site)\b", text):
            return None
        return self._recent_website_context(active_context, recent_tool_results)

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
