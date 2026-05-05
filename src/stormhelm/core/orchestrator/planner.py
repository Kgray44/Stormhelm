from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any

from stormhelm.config.models import CalculationsConfig
from stormhelm.config.models import DiscordRelayConfig
from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.config.models import SoftwareControlConfig
from stormhelm.core.adapters import AdapterContract
from stormhelm.core.adapters import AdapterContractRegistry
from stormhelm.core.adapters import AdapterRouteAssessment
from stormhelm.core.adapters import default_adapter_contract_registry
from stormhelm.core.calculations import CalculationsPlannerSeam
from stormhelm.core.calculations import CalculationOutputMode
from stormhelm.core.calculations import CalculationPlannerEvaluation
from stormhelm.core.calculations import CalculationRouteDisposition
from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.orchestrator.browser_destinations import BrowserDestinationResolver
from stormhelm.core.orchestrator.browser_destinations import BrowserIntentType
from stormhelm.core.orchestrator.browser_destinations import BrowserOpenFailureReason
from stormhelm.core.orchestrator.browser_destinations import BrowserSearchFailureReason
from stormhelm.core.orchestrator.planner_models import CapabilityPlan
from stormhelm.core.orchestrator.planner_models import ClarificationReason
from stormhelm.core.orchestrator.planner_models import DeicticBinding
from stormhelm.core.orchestrator.planner_models import DeicticBindingCandidate
from stormhelm.core.orchestrator.planner_models import ExecutionPlan
from stormhelm.core.orchestrator.planner_models import NormalizedCommand
from stormhelm.core.orchestrator.planner_models import QueryShape
from stormhelm.core.orchestrator.planner_models import RequestDecomposition
from stormhelm.core.orchestrator.planner_models import ResponseMode
from stormhelm.core.orchestrator.planner_models import RouteCandidate
from stormhelm.core.orchestrator.planner_models import RoutePosture
from stormhelm.core.orchestrator.planner_models import RouteTargetCandidate
from stormhelm.core.orchestrator.planner_models import RouteWinnerPosture
from stormhelm.core.orchestrator.planner_models import RoutingTelemetry
from stormhelm.core.orchestrator.planner_models import SemanticParseProposal
from stormhelm.core.orchestrator.planner_models import StructuredQuery
from stormhelm.core.orchestrator.planner_models import UnsupportedReason
from stormhelm.core.orchestrator.planner_v2 import PlannerV2
from stormhelm.core.orchestrator.route_context import RouteContextArbitration
from stormhelm.core.orchestrator.route_context import RouteContextArbitrator
from stormhelm.core.orchestrator.route_spine import MIGRATED_ROUTE_FAMILIES
from stormhelm.core.orchestrator.route_spine import RouteSpine
from stormhelm.core.orchestrator.route_spine import RouteSpineDecision
from stormhelm.core.orchestrator.route_triage import RouteTriageResult
from stormhelm.core.orchestrator.route_triage import route_triage_from_dict
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.screen_awareness import ScreenAwarenessPlannerSeam
from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import ScreenPlannerEvaluation
from stormhelm.core.screen_awareness import ScreenRouteDisposition
from stormhelm.core.software_control import SoftwareControlPlannerSeam
from stormhelm.core.software_control import SoftwarePlannerEvaluation
from stormhelm.core.software_control import SoftwareRouteDisposition

NOTE_EXTENSIONS = {".md", ".markdown", ".txt"}
FILE_LOOKUP_PREFIXES = {"open ", "show ", "bring up ", "pull up "}
FILE_LOOKUP_HINTS = {
    "file",
    "files",
    "folder",
    "folders",
    "doc",
    "docs",
    "document",
    "documentation",
    "manual",
    "readme",
    "pdf",
    "note",
    "notes",
    "report",
    "screenshot",
    "screenshots",
    "download",
    "downloads",
    "desktop",
    "documents",
    "pictures",
    "music",
    "videos",
}
KNOWN_FOLDER_ALIASES: dict[str, tuple[str, ...]] = {
    "Documents": ("documents", "my documents", "documents folder", "the documents folder"),
    "Downloads": ("downloads", "my downloads", "downloads folder", "the downloads folder"),
    "Desktop": ("desktop", "my desktop", "desktop folder", "the desktop folder"),
    "Pictures": ("pictures", "my pictures", "pictures folder", "the pictures folder"),
    "Music": ("music", "my music", "music folder", "the music folder"),
    "Videos": ("videos", "my videos", "videos folder", "the videos folder"),
}
DEFAULT_AVAILABLE_TOOLS = {
    "clock",
    "system_info",
    "machine_status",
    "power_status",
    "power_projection",
    "power_diagnosis",
    "resource_status",
    "resource_diagnosis",
    "storage_status",
    "storage_diagnosis",
    "network_status",
    "network_throughput",
    "network_diagnosis",
    "location_status",
    "saved_locations",
    "save_location",
    "weather_current",
    "active_apps",
    "recent_files",
    "app_control",
    "window_status",
    "window_control",
    "system_control",
    "desktop_search",
    "workflow_execute",
    "repair_action",
    "routine_execute",
    "routine_save",
    "echo",
    "notes_write",
    "notes_recall",
    "trusted_hook_register",
    "trusted_hook_execute",
    "maintenance_action",
    "file_operation",
    "browser_context",
    "activity_summary",
    "context_action",
    "workspace_restore",
    "workspace_assemble",
    "workspace_save",
    "workspace_clear",
    "workspace_archive",
    "workspace_rename",
    "workspace_tag",
    "workspace_list",
    "workspace_where_left_off",
    "workspace_next_steps",
    "deck_open_url",
    "external_open_url",
    "deck_open_file",
    "external_open_file",
    "web_retrieval_fetch",
    "file_reader",
    "shell_command",
}

DISCORD_RELAY_CONFIRM_PHRASES = {
    "yes",
    "yes send it",
    "send it",
    "go ahead",
    "do it",
    "do that",
    "confirm",
    "send",
}


@dataclass(slots=True)
class PlannerDecision:
    request_type: str = "unclassified"
    tool_requests: list[ToolRequest] = field(default_factory=list)
    assistant_message: str | None = None
    requires_reasoner: bool = False
    active_request_state: dict[str, object] = field(default_factory=dict)
    structured_query: StructuredQuery | None = None
    capability_plan: CapabilityPlan | None = None
    execution_plan: ExecutionPlan | None = None
    response_mode: str | None = None
    unsupported_reason: UnsupportedReason | None = None
    clarification_reason: ClarificationReason | None = None
    route_state: RoutingTelemetry | None = None
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RequestClassification:
    request_type: str
    family: str | None = None
    focus: str = "overview"
    query_kind: str = "overview"
    open_target: str = "none"
    location_mode: str = "auto"
    named_location: str | None = None
    named_location_type: str | None = None
    allow_home_fallback: bool = True
    present_in: str = "none"
    requires_reasoner: bool = False
    forecast_target: str = "current"
    metric: str = "overview"
    target_percent: int | None = None
    assume_unplugged: bool = False

    def to_active_request_state(self) -> dict[str, object]:
        if not self.family:
            return {}
        return {
            "family": self.family,
            "subject": self.family,
            "request_type": self.request_type,
            "route": {
                "open_target": self.open_target,
                "present_in": self.present_in,
            },
            "parameters": {
                "focus": self.focus,
                "query_kind": self.query_kind,
                "open_target": self.open_target,
                "location_mode": self.location_mode,
                "named_location": self.named_location,
                "named_location_type": self.named_location_type,
                "allow_home_fallback": self.allow_home_fallback,
                "present_in": self.present_in,
                "forecast_target": self.forecast_target,
                "metric": self.metric,
                "target_percent": self.target_percent,
                "assume_unplugged": self.assume_unplugged,
            },
        }


class DeterministicPlanner:
    def __init__(
        self,
        *,
        available_tools: set[str] | None = None,
        screen_awareness_config: ScreenAwarenessConfig | None = None,
        screen_awareness_seam: ScreenAwarenessPlannerSeam | None = None,
        calculations_config: CalculationsConfig | None = None,
        calculations_seam: CalculationsPlannerSeam | None = None,
        software_control_config: SoftwareControlConfig | None = None,
        software_control_seam: SoftwareControlPlannerSeam | None = None,
        discord_relay_config: DiscordRelayConfig | None = None,
        adapter_contracts: AdapterContractRegistry | None = None,
    ) -> None:
        self._available_tools = set(available_tools or DEFAULT_AVAILABLE_TOOLS)
        self._browser_destination_resolver = BrowserDestinationResolver()
        self._screen_awareness_seam = screen_awareness_seam or ScreenAwarenessPlannerSeam(
            screen_awareness_config or ScreenAwarenessConfig()
        )
        self._calculations_seam = calculations_seam or CalculationsPlannerSeam(
            calculations_config or CalculationsConfig()
        )
        self._software_control_seam = software_control_seam or SoftwareControlPlannerSeam(
            software_control_config or SoftwareControlConfig()
        )
        self._discord_relay_config = discord_relay_config or DiscordRelayConfig()
        self._adapter_contracts = adapter_contracts or default_adapter_contract_registry()
        self._route_context_arbitrator = RouteContextArbitrator()
        self._planner_v2 = PlannerV2()
        self._route_spine = RouteSpine()

    def _route_triage_allows_seam(
        self,
        family: str,
        *,
        route_triage: RouteTriageResult | None,
        selected_family: str | None = None,
    ) -> bool:
        if route_triage is None:
            return True
        if selected_family == family:
            return True
        if route_triage.confidence < 0.82:
            return True
        return family not in set(route_triage.excluded_route_families)

    def _evaluate_route_family_seams(
        self,
        *,
        routing_message: str,
        normalized_text: str,
        surface_mode: str,
        active_module: str,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        route_triage: RouteTriageResult | None,
        selected_family: str | None,
        debug: dict[str, Any],
    ) -> tuple[CalculationPlannerEvaluation, SoftwarePlannerEvaluation, ScreenPlannerEvaluation]:
        evaluated: list[str] = []
        skipped: list[str] = []

        if self._route_triage_allows_seam("calculations", route_triage=route_triage, selected_family=selected_family):
            calculation_evaluation = self._calculations_seam.evaluate(
                raw_text=routing_message,
                normalized_text=normalized_text,
                surface_mode=surface_mode,
                active_module=active_module,
                active_context=active_context,
            )
            evaluated.append("calculations")
        else:
            calculation_evaluation = self._skipped_calculation_evaluation()
            skipped.append("calculations")
        debug["calculations"] = calculation_evaluation.to_dict()

        if self._route_triage_allows_seam("software_control", route_triage=route_triage, selected_family=selected_family):
            software_control_evaluation = self._software_control_seam.evaluate(
                raw_text=routing_message,
                normalized_text=normalized_text,
                surface_mode=surface_mode,
                active_module=active_module,
                active_request_state=active_request_state,
                active_context=active_context,
            )
            evaluated.append("software_control")
        else:
            software_control_evaluation = self._skipped_software_control_evaluation()
            skipped.append("software_control")
        debug["software_control"] = software_control_evaluation.to_dict()

        if self._route_triage_allows_seam("screen_awareness", route_triage=route_triage, selected_family=selected_family):
            screen_awareness_evaluation = self._screen_awareness_seam.evaluate(
                raw_text=routing_message,
                normalized_text=normalized_text,
                surface_mode=surface_mode,
                active_module=active_module,
                active_context=active_context,
            )
            evaluated.append("screen_awareness")
        else:
            screen_awareness_evaluation = self._skipped_screen_awareness_evaluation(
                surface_mode=surface_mode,
                active_module=active_module,
            )
            skipped.append("screen_awareness")
        debug["screen_awareness"] = screen_awareness_evaluation.to_dict()

        debug["route_family_seams_evaluated"] = evaluated
        debug["route_family_seams_skipped"] = skipped
        debug["planner_candidates_pruned_count"] = len(skipped)
        if skipped and route_triage is not None and route_triage.likely_route_families:
            debug["provider_fallback_suppressed_reason"] = (
                "native_route_triage"
                if route_triage.likely_route_families[0] != "generic_provider"
                and not route_triage.provider_fallback_eligible
                else ""
            )
        return calculation_evaluation, software_control_evaluation, screen_awareness_evaluation

    def _skipped_calculation_evaluation(self) -> CalculationPlannerEvaluation:
        config = getattr(self._calculations_seam, "config", CalculationsConfig())
        return CalculationPlannerEvaluation(
            candidate=False,
            disposition=CalculationRouteDisposition.NOT_REQUESTED,
            reasons=["skipped_by_route_triage"],
            feature_enabled=bool(config.enabled),
            planner_routing_enabled=bool(config.planner_routing_enabled),
        )

    def _skipped_software_control_evaluation(self) -> SoftwarePlannerEvaluation:
        config = getattr(self._software_control_seam, "config", SoftwareControlConfig())
        return SoftwarePlannerEvaluation(
            candidate=False,
            disposition=SoftwareRouteDisposition.NOT_REQUESTED,
            feature_enabled=bool(config.enabled),
            planner_routing_enabled=bool(config.planner_routing_enabled),
            reasons=["skipped_by_route_triage"],
        )

    def _skipped_screen_awareness_evaluation(
        self,
        *,
        surface_mode: str,
        active_module: str,
    ) -> ScreenPlannerEvaluation:
        config = getattr(self._screen_awareness_seam, "config", ScreenAwarenessConfig())
        return ScreenPlannerEvaluation(
            candidate=False,
            disposition=ScreenRouteDisposition.NOT_REQUESTED,
            reasons=["skipped_by_route_triage"],
            feature_enabled=bool(config.enabled),
            planner_routing_enabled=bool(config.planner_routing_enabled),
            input_signals={
                "surface_mode": surface_mode,
                "active_module": active_module,
                "skipped_by_route_triage": True,
            },
        )

    def plan(
        self,
        message: str,
        *,
        session_id: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None = None,
        active_posture: dict[str, Any] | None = None,
        active_request_state: dict[str, Any] | None = None,
        recent_tool_results: list[dict[str, Any]] | None = None,
        learned_preferences: dict[str, dict[str, object]] | None = None,
        active_context: dict[str, Any] | None = None,
        route_triage_result: RouteTriageResult | dict[str, Any] | None = None,
        available_tools: set[str] | None = None,
    ) -> PlannerDecision:
        normalized = self._normalize_command(message, surface_mode=surface_mode, active_module=active_module)
        route_triage = route_triage_from_dict(route_triage_result)
        decomposition = self._decompose_request(
            normalized,
            active_context=active_context or {},
            active_request_state=active_request_state or {},
            recent_tool_results=recent_tool_results or [],
        )
        debug: dict[str, Any] = {
            "normalized_command": normalized.to_dict(),
            "request_decomposition": decomposition.to_dict(),
        }
        if route_triage is not None:
            debug["route_triage"] = route_triage.to_dict()
        if not normalized.normalized_text:
            return self._finalize_decision(
                PlannerDecision(debug=debug),
                normalized=normalized,
                decomposition=decomposition,
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                recent_tool_results=recent_tool_results or [],
            )

        lower = normalized.normalized_text
        guardrail_message = self._guardrail_message(message, lower, active_context=active_context)
        if guardrail_message:
            clarification = ClarificationReason(code="guardrail", message=guardrail_message)
            debug["clarification_reason"] = clarification.to_dict()
            debug["response_mode"] = ResponseMode.CLARIFICATION.value
            guardrail_family = self._guardrail_route_family(lower)
            if guardrail_family:
                debug["guardrail_route_family"] = guardrail_family
            return self._finalize_decision(
                PlannerDecision(
                    request_type="guardrail_clarify",
                    assistant_message=guardrail_message,
                    clarification_reason=clarification,
                    response_mode=ResponseMode.CLARIFICATION.value,
                    debug=debug,
                ),
                normalized=normalized,
                decomposition=decomposition,
                clarification_reason=clarification,
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                recent_tool_results=recent_tool_results or [],
            )

        planner_v2_context = {
            **(workspace_context or {}),
            **(active_context or {}),
        }
        planner_v2_input = normalized.raw_text or message
        if self._operator_wrapper_browser_near_miss(message, normalized.normalized_text):
            planner_v2_input = str(message or "")
        planner_v2_trace = self._planner_v2.plan(
            planner_v2_input,
            surface_mode=surface_mode,
            active_module=active_module,
            active_context=planner_v2_context,
            active_request_state=active_request_state or {},
            recent_tool_results=recent_tool_results or [],
        )
        debug["planner_v2"] = planner_v2_trace.to_dict()
        if planner_v2_trace.authoritative:
            route_spine_decision = planner_v2_trace.to_route_spine_decision()
            debug["route_spine"] = route_spine_decision.to_dict()
            debug["routing_engine"] = "planner_v2"
            debug["intent_frame"] = planner_v2_trace.intent_frame.to_dict()
            debug["candidate_specs_considered"] = list(route_spine_decision.candidate_specs_considered)
            debug["selected_route_spec"] = route_spine_decision.selected_route_spec
            debug["native_decline_reasons"] = route_spine_decision.native_decline_reasons
            debug["generic_provider_gate_reason"] = route_spine_decision.generic_provider_gate_reason
            debug["legacy_fallback_used"] = False

            routing_message = normalized.raw_text or message
            calculation_evaluation, software_control_evaluation, screen_awareness_evaluation = self._evaluate_route_family_seams(
                routing_message=routing_message,
                normalized_text=normalized.normalized_text,
                surface_mode=surface_mode,
                active_module=active_module,
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                route_triage=route_triage,
                selected_family=str(route_spine_decision.winner.route_family or ""),
                debug=debug,
            )
            semantic = self._semantic_from_route_spine_decision(
                route_spine_decision,
                message=routing_message,
                normalized=normalized,
                surface_mode=surface_mode,
                workspace_context=workspace_context or {},
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                active_posture=active_posture or {},
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                planner_v2_trace=planner_v2_trace,
                learned_preferences=learned_preferences or {},
            )
            debug["semantic_parse_proposal"] = semantic.to_dict()
            return self._decision_from_semantic(
                semantic,
                debug=debug,
                normalized=normalized,
                decomposition=decomposition,
                session_id=session_id,
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                recent_tool_results=recent_tool_results or [],
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                available_tools=set(available_tools or self._available_tools),
            )

        route_spine_context = {
            **(workspace_context or {}),
            **(active_context or {}),
        }
        route_spine_decision = self._route_spine.route(
            normalized.raw_text or message,
            active_context=route_spine_context,
            active_request_state=active_request_state or {},
            recent_tool_results=recent_tool_results or [],
        )
        debug["route_spine"] = route_spine_decision.to_dict()
        debug["routing_engine"] = (
            route_spine_decision.routing_engine
            if route_spine_decision.authoritative
            else "legacy_planner"
        )
        debug["intent_frame"] = route_spine_decision.intent_frame.to_dict()
        debug["candidate_specs_considered"] = list(route_spine_decision.candidate_specs_considered)
        debug["selected_route_spec"] = route_spine_decision.selected_route_spec
        debug["native_decline_reasons"] = route_spine_decision.native_decline_reasons
        debug["generic_provider_gate_reason"] = route_spine_decision.generic_provider_gate_reason
        debug["legacy_fallback_used"] = route_spine_decision.legacy_fallback_used
        planner_v2_deferred_to_legacy = (
            bool(planner_v2_trace.route_decision.legacy_fallback_allowed)
            and bool(planner_v2_trace.route_decision.legacy_family)
            and route_spine_decision.authoritative
            and route_spine_decision.winner.route_family == "generic_provider"
        )
        if planner_v2_deferred_to_legacy:
            debug["routing_engine"] = "legacy_planner"
            debug["legacy_fallback_used"] = True
            debug["planner_v2_legacy_defer_respected"] = True
            debug["generic_provider_gate_reason"] = planner_v2_trace.route_decision.generic_provider_gate_reason

        routing_message = normalized.raw_text or message
        calculation_evaluation, software_control_evaluation, screen_awareness_evaluation = self._evaluate_route_family_seams(
            routing_message=routing_message,
            normalized_text=normalized.normalized_text,
            surface_mode=surface_mode,
            active_module=active_module,
            active_context=active_context or {},
            active_request_state=active_request_state or {},
            route_triage=route_triage,
            selected_family=str(route_spine_decision.winner.route_family or ""),
            debug=debug,
        )
        if route_spine_decision.authoritative and not planner_v2_deferred_to_legacy:
            semantic = self._semantic_from_route_spine_decision(
                route_spine_decision,
                message=routing_message,
                normalized=normalized,
                surface_mode=surface_mode,
                workspace_context=workspace_context or {},
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                active_posture=active_posture or {},
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                learned_preferences=learned_preferences or {},
            )
            debug["semantic_parse_proposal"] = semantic.to_dict()
            return self._decision_from_semantic(
                semantic,
                debug=debug,
                normalized=normalized,
                decomposition=decomposition,
                session_id=session_id,
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                recent_tool_results=recent_tool_results or [],
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                available_tools=set(available_tools or self._available_tools),
            )
        if (
            calculation_evaluation.candidate
            and calculation_evaluation.disposition
            in {
                CalculationRouteDisposition.DIRECT_EXPRESSION,
                CalculationRouteDisposition.HELPER_REQUEST,
                CalculationRouteDisposition.VERIFICATION_REQUEST,
            }
        ):
            helper_request = calculation_evaluation.disposition == CalculationRouteDisposition.HELPER_REQUEST
            verification_request = calculation_evaluation.disposition == CalculationRouteDisposition.VERIFICATION_REQUEST
            structured_query = StructuredQuery(
                domain="calculations",
                query_shape=QueryShape.CALCULATION_REQUEST,
                requested_action="verify_expression"
                if verification_request
                else "evaluate_helper"
                if helper_request
                else "evaluate_expression",
                output_mode=calculation_evaluation.requested_mode.value,
                execution_type="deterministic_local_verification"
                if verification_request
                else "deterministic_local_helper"
                if helper_request
                else "deterministic_local_expression",
                capability_requirements=["local_calculation"],
                confidence=calculation_evaluation.route_confidence,
                output_type="numeric",
                slots={
                    "calculation_request": calculation_evaluation.to_dict(),
                    "requested_mode": calculation_evaluation.requested_mode.value,
                },
            )
            capability_plan = CapabilityPlan(
                supported=True,
                required_capabilities=["local_calculation"],
                notes=[
                    "Routes deterministic numeric verification to the built-in calculations lane."
                    if verification_request
                    else
                    "Routes supported helper math to the built-in deterministic calculation lane."
                    if helper_request
                    else "Routes obvious arithmetic to the built-in deterministic calculation lane."
                ],
            )
            execution_plan = ExecutionPlan(
                plan_type="calculation_evaluate",
                request_type="calculation_response",
                response_mode=ResponseMode.CALCULATION_RESULT,
                family="calculations",
                subject=calculation_evaluation.helper_name or ("verification" if verification_request else "expression"),
            )
            debug["structured_query"] = structured_query.to_dict()
            debug["capability_plan"] = capability_plan.to_dict()
            debug["execution_plan"] = execution_plan.to_dict()
            debug["response_mode"] = execution_plan.response_mode.value
            return self._finalize_decision(
                PlannerDecision(
                request_type=execution_plan.request_type,
                tool_requests=[],
                assistant_message=None,
                requires_reasoner=False,
                active_request_state=self._active_request_state_from_structured_query(structured_query, execution_plan),
                structured_query=structured_query,
                capability_plan=capability_plan,
                execution_plan=execution_plan,
                response_mode=execution_plan.response_mode.value,
                debug=debug,
                ),
                normalized=normalized,
                decomposition=decomposition,
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                recent_tool_results=recent_tool_results or [],
            )

        if (
            software_control_evaluation.candidate
            and software_control_evaluation.disposition
            in {
                SoftwareRouteDisposition.DIRECT_REQUEST,
                SoftwareRouteDisposition.FOLLOW_UP_CONFIRMATION,
            }
            and software_control_evaluation.operation_type
            and software_control_evaluation.target_name
        ):
            structured_query = StructuredQuery(
                domain="software_control",
                query_shape=QueryShape.SOFTWARE_CONTROL_REQUEST,
                requested_action=software_control_evaluation.operation_type,
                output_mode=ResponseMode.ACTION_RESULT.value,
                execution_type="software_control_execute",
                capability_requirements=["software_control"],
                confidence=software_control_evaluation.route_confidence,
                output_type="action",
                slots={
                    "software_control_request": software_control_evaluation.to_dict(),
                    "operation_type": software_control_evaluation.operation_type,
                    "target_name": software_control_evaluation.target_name,
                    "request_stage": software_control_evaluation.request_stage,
                    "follow_up_reuse": software_control_evaluation.follow_up_reuse,
                    "approval_scope": software_control_evaluation.approval_scope,
                    "approval_outcome": software_control_evaluation.approval_outcome,
                    "trust_request_id": software_control_evaluation.trust_request_id,
                    "family": "software_control",
                    "subject": software_control_evaluation.target_name,
                    "request_type_hint": "software_control_response",
                },
            )
            capability_plan = CapabilityPlan(
                supported=True,
                required_capabilities=["software_control"],
                notes=[
                    "Routes software lifecycle intent into the native software-control subsystem.",
                    "Execution remains local-first and truthfully staged before any attempt.",
                ],
            )
            execution_plan = ExecutionPlan(
                plan_type="software_control_execute",
                request_type="software_control_response",
                response_mode=ResponseMode.ACTION_RESULT,
                family="software_control",
                subject=software_control_evaluation.target_name,
            )
            debug["structured_query"] = structured_query.to_dict()
            debug["capability_plan"] = capability_plan.to_dict()
            debug["execution_plan"] = execution_plan.to_dict()
            debug["response_mode"] = execution_plan.response_mode.value
            return self._finalize_decision(
                PlannerDecision(
                request_type=execution_plan.request_type,
                tool_requests=[],
                assistant_message=None,
                requires_reasoner=False,
                active_request_state=self._active_request_state_from_structured_query(structured_query, execution_plan),
                structured_query=structured_query,
                capability_plan=capability_plan,
                execution_plan=execution_plan,
                response_mode=execution_plan.response_mode.value,
                debug=debug,
                ),
                normalized=normalized,
                decomposition=decomposition,
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                recent_tool_results=recent_tool_results or [],
            )

        semantic: SemanticParseProposal
        if (
            software_control_evaluation.candidate
            and software_control_evaluation.disposition
            in {
                SoftwareRouteDisposition.FEATURE_DISABLED,
                SoftwareRouteDisposition.ROUTING_DISABLED,
            }
            and software_control_evaluation.operation_type
            and software_control_evaluation.target_name
        ):
            semantic = self._tool_proposal(
                query_shape=QueryShape.SOFTWARE_CONTROL_REQUEST,
                domain="software_control",
                request_type_hint="software_control_response",
                family="software_control",
                subject=software_control_evaluation.target_name,
                requested_action=software_control_evaluation.operation_type,
                confidence=software_control_evaluation.route_confidence,
                evidence=list(software_control_evaluation.reasons or ["software-control route remains the native owner"]),
                execution_type="software_control_execute",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots={
                    "software_control_request": software_control_evaluation.to_dict(),
                    "operation_type": software_control_evaluation.operation_type,
                    "target_name": software_control_evaluation.target_name,
                    "request_stage": software_control_evaluation.request_stage,
                    "follow_up_reuse": software_control_evaluation.follow_up_reuse,
                    "approval_scope": software_control_evaluation.approval_scope,
                    "approval_outcome": software_control_evaluation.approval_outcome,
                    "trust_request_id": software_control_evaluation.trust_request_id,
                    "family": "software_control",
                    "subject": software_control_evaluation.target_name,
                },
            )
        else:
            semantic = self._semantic_parse_proposal(
                message,
                normalized=normalized,
                session_id=session_id,
                workspace_context=workspace_context,
                active_posture=active_posture,
                active_request_state=active_request_state or {},
                recent_tool_results=recent_tool_results or [],
                learned_preferences=learned_preferences or {},
                active_context=active_context or {},
                screen_awareness_evaluation=screen_awareness_evaluation,
            )
        debug["semantic_parse_proposal"] = semantic.to_dict()

        structured_query, clarification_reason = self._validate_structured_query(
            semantic,
            normalized=normalized,
            active_context=active_context or {},
        )
        debug["structured_query"] = structured_query.to_dict()
        if clarification_reason is not None:
            clarification_execution_plan: ExecutionPlan | None = None
            clarification_active_state: dict[str, object] = {}
            if structured_query.query_shape == QueryShape.CAMERA_AWARENESS_REQUEST:
                clarification_execution_plan = ExecutionPlan(
                    plan_type=structured_query.execution_type
                    or "camera_awareness_c0_mock_or_permission_gate",
                    request_type=str(
                        structured_query.slots.get("request_type_hint")
                        or "camera_awareness_confirmation"
                    ),
                    response_mode=ResponseMode.CLARIFICATION,
                    family=str(
                        structured_query.slots.get("family")
                        or structured_query.domain
                        or "camera_awareness"
                    ),
                    subject=str(
                        structured_query.slots.get("subject")
                        or structured_query.domain
                        or "camera still"
                    ),
                    assistant_message=clarification_reason.message,
                )
                clarification_active_state = self._active_request_state_from_structured_query(
                    structured_query,
                    clarification_execution_plan,
                )
                debug["execution_plan"] = clarification_execution_plan.to_dict()
            debug["clarification_reason"] = clarification_reason.to_dict()
            debug["response_mode"] = ResponseMode.CLARIFICATION.value
            return self._finalize_decision(
                PlannerDecision(
                    request_type="clarification_request",
                    assistant_message=clarification_reason.message,
                    active_request_state=clarification_active_state,
                    structured_query=structured_query,
                    execution_plan=clarification_execution_plan,
                    clarification_reason=clarification_reason,
                    response_mode=ResponseMode.CLARIFICATION.value,
                    debug=debug,
                ),
                normalized=normalized,
                decomposition=decomposition,
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                semantic=semantic,
                clarification_reason=clarification_reason,
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                recent_tool_results=recent_tool_results or [],
            )

        if structured_query.query_shape == QueryShape.UNCLASSIFIED:
            debug["response_mode"] = ResponseMode.SUMMARY_RESULT.value
            return self._finalize_decision(
                PlannerDecision(
                    request_type="unclassified",
                    structured_query=structured_query,
                    response_mode=ResponseMode.SUMMARY_RESULT.value,
                    debug=debug,
                ),
                normalized=normalized,
                decomposition=decomposition,
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                semantic=semantic,
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                recent_tool_results=recent_tool_results or [],
            )

        capability_plan = self._plan_capabilities(
            structured_query,
            available_tools=set(available_tools or self._available_tools),
        )
        debug["capability_plan"] = capability_plan.to_dict()
        provisional_execution_plan = self._build_execution_plan(
            structured_query,
            capability_plan=capability_plan,
            session_id=session_id,
        )
        if not capability_plan.supported and capability_plan.unsupported_reason is not None:
            debug["unsupported_reason"] = capability_plan.unsupported_reason.to_dict()
            debug["execution_plan"] = provisional_execution_plan.to_dict()
            debug["response_mode"] = ResponseMode.UNSUPPORTED.value
            return self._finalize_decision(
                PlannerDecision(
                    request_type="unsupported_capability",
                    assistant_message=capability_plan.unsupported_reason.message,
                    structured_query=structured_query,
                    capability_plan=capability_plan,
                    execution_plan=provisional_execution_plan,
                    unsupported_reason=capability_plan.unsupported_reason,
                    response_mode=ResponseMode.UNSUPPORTED.value,
                    debug=debug,
                ),
                normalized=normalized,
                decomposition=decomposition,
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                semantic=semantic,
                unsupported_reason=capability_plan.unsupported_reason,
                active_context=active_context or {},
                active_request_state=active_request_state or {},
                recent_tool_results=recent_tool_results or [],
            )

        execution_plan = provisional_execution_plan
        debug["execution_plan"] = execution_plan.to_dict()
        debug["response_mode"] = execution_plan.response_mode.value

        tool_requests: list[ToolRequest] = []
        if execution_plan.tool_name:
            tool_requests.append(ToolRequest(execution_plan.tool_name, dict(execution_plan.tool_arguments)))

        return self._finalize_decision(
            PlannerDecision(
                request_type=execution_plan.request_type,
                tool_requests=tool_requests,
                assistant_message=execution_plan.assistant_message,
                requires_reasoner=execution_plan.requires_reasoner,
                active_request_state=self._active_request_state_from_structured_query(structured_query, execution_plan),
                structured_query=structured_query,
                capability_plan=capability_plan,
                execution_plan=execution_plan,
                response_mode=execution_plan.response_mode.value,
                debug=debug,
            ),
            normalized=normalized,
            decomposition=decomposition,
            calculation_evaluation=calculation_evaluation,
            software_control_evaluation=software_control_evaluation,
            screen_awareness_evaluation=screen_awareness_evaluation,
            semantic=semantic,
            active_context=active_context or {},
            active_request_state=active_request_state or {},
            recent_tool_results=recent_tool_results or [],
        )

    def _finalize_decision(
        self,
        decision: PlannerDecision,
        *,
        normalized: NormalizedCommand,
        decomposition: RequestDecomposition,
        calculation_evaluation: Any | None = None,
        software_control_evaluation: Any | None = None,
        screen_awareness_evaluation: ScreenPlannerEvaluation | None = None,
        semantic: SemanticParseProposal | None = None,
        clarification_reason: ClarificationReason | None = None,
        unsupported_reason: UnsupportedReason | None = None,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> PlannerDecision:
        route_state = self._build_routing_telemetry(
            normalized=normalized,
            decomposition=decomposition,
            decision=decision,
            calculation_evaluation=calculation_evaluation,
            software_control_evaluation=software_control_evaluation,
            screen_awareness_evaluation=screen_awareness_evaluation,
            semantic=semantic,
            clarification_reason=clarification_reason or decision.clarification_reason,
            unsupported_reason=unsupported_reason or decision.unsupported_reason,
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        decision.route_state = route_state
        decision.debug["routing"] = route_state.to_dict()
        return decision

    def _build_routing_telemetry(
        self,
        *,
        normalized: NormalizedCommand,
        decomposition: RequestDecomposition,
        decision: PlannerDecision,
        calculation_evaluation: Any | None,
        software_control_evaluation: Any | None,
        screen_awareness_evaluation: ScreenPlannerEvaluation | None,
        semantic: SemanticParseProposal | None,
        clarification_reason: ClarificationReason | None,
        unsupported_reason: UnsupportedReason | None,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> RoutingTelemetry:
        deictic_binding = self._resolve_deictic_binding(
            decomposition,
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        semantic_binding = self._semantic_deictic_binding(semantic)
        if semantic_binding is not None:
            deictic_binding = semantic_binding
        candidates = self._route_candidates(
            normalized=normalized,
            decomposition=decomposition,
            calculation_evaluation=calculation_evaluation,
            software_control_evaluation=software_control_evaluation,
            screen_awareness_evaluation=screen_awareness_evaluation,
            semantic=semantic,
            decision=decision,
            deictic_binding=deictic_binding,
            active_request_state=active_request_state,
        )
        winner_family = self._route_family_for_decision(decision)
        winner_candidate = next((candidate for candidate in candidates if candidate.route_family == winner_family), None)
        if winner_candidate is None:
            winner_candidate = RouteCandidate(
                route_family=winner_family,
                query_shape=decision.structured_query.query_shape.value if decision.structured_query is not None else None,
                score=0.0,
                posture_seed="inferred",
                semantic_reasons=["winner inferred from final planner decision"],
            )
            candidates.append(winner_candidate)

        provider_fallback_reason = None
        posture = RoutePosture.CLEAR_WINNER if winner_candidate.score >= 0.9 else RoutePosture.LIKELY_WINNER
        status = "immediate"
        unresolved_targets: list[str] = []
        clarification_needed = False
        clarification_message = None

        if decision.request_type == "unclassified" or winner_family == "generic_provider":
            posture = RoutePosture.GENUINE_PROVIDER_FALLBACK
            status = "provider_fallback"
            provider_fallback_reason = winner_candidate.provider_fallback_reason or self._provider_fallback_reason(normalized)
            winner_candidate.provider_fallback_reason = provider_fallback_reason
        elif unsupported_reason is not None:
            posture = RoutePosture.NATIVE_UNSUPPORTED
            status = "blocked"
            unresolved_targets = list(winner_candidate.missing_evidence)
        elif clarification_reason is not None:
            posture = RoutePosture.CONDITIONAL_WINNER
            status = "conditional"
            clarification_needed = True
            clarification_message = clarification_reason.message
            unresolved_targets = self._unresolved_targets_from_clarification(clarification_reason)
        elif winner_candidate.disqualifiers:
            posture = RoutePosture.BLOCKED_WINNER
            status = "blocked"

        sorted_candidates = sorted(candidates, key=lambda item: item.score, reverse=True)
        runner_up = next((candidate for candidate in sorted_candidates if candidate.route_family != winner_family), None)
        margin_to_runner_up = None if runner_up is None else round(max(0.0, winner_candidate.score - runner_up.score), 3)
        recent_entity_browser_near_tie = bool(
            winner_family == "browser_destination"
            and deictic_binding.selected_source == "recent_session_entity"
            and runner_up is not None
            and runner_up.route_family == "screen_awareness"
            and margin_to_runner_up is not None
            and margin_to_runner_up < 0.1
        )
        ambiguity_live = bool(
            runner_up is not None
            and (runner_up.score >= 0.65 or recent_entity_browser_near_tie)
            and margin_to_runner_up is not None
            and margin_to_runner_up < 0.1
        )
        runner_summary = None
        if runner_up is not None:
            runner_summary = {
                "route_family": runner_up.route_family,
                "score": runner_up.score,
                "reason": runner_up.semantic_reasons[0] if runner_up.semantic_reasons else "",
            }
        if posture == RoutePosture.CLEAR_WINNER and ambiguity_live:
            posture = RoutePosture.LIKELY_WINNER
        support_summary = sorted(
            {
                note
                for candidate in candidates
                for note in candidate.support_augmentation
                if str(note).strip()
            }
        )
        winner = RouteWinnerPosture(
            route_family=winner_family,
            query_shape=decision.structured_query.query_shape.value if decision.structured_query is not None else winner_candidate.query_shape,
            confidence=round(max(0.0, min(winner_candidate.score, 1.0)), 3),
            posture=posture,
            status=status,
            score=winner_candidate.score,
            dominant_evidence=list(winner_candidate.semantic_reasons[:4]),
            unresolved_targets=unresolved_targets,
            clarification_needed=clarification_needed,
            clarification_reason=clarification_message,
            clarification_code=clarification_reason.code if clarification_reason is not None else None,
            runner_up_summary=runner_summary,
            support_system_augmentation=support_summary,
            provider_fallback_reason=provider_fallback_reason,
            margin_to_runner_up=margin_to_runner_up,
            ambiguity_live=ambiguity_live,
            planned_tools=[request.tool_name for request in decision.tool_requests],
            capability_requirements=list(
                decision.structured_query.capability_requirements if decision.structured_query is not None else []
            ),
        )
        return RoutingTelemetry(
            normalized_summary=normalized.to_dict(),
            decomposition=decomposition,
            candidates=sorted_candidates,
            winner=winner,
            runner_up=runner_up,
            deictic_binding=deictic_binding,
            support_augmentation_summary=support_summary,
        )

    def _route_candidates(
        self,
        *,
        normalized: NormalizedCommand,
        decomposition: RequestDecomposition,
        calculation_evaluation: Any | None,
        software_control_evaluation: Any | None,
        screen_awareness_evaluation: ScreenPlannerEvaluation | None,
        semantic: SemanticParseProposal | None,
        decision: PlannerDecision,
        deictic_binding: DeicticBinding,
        active_request_state: dict[str, Any],
    ) -> list[RouteCandidate]:
        candidates_by_family: dict[str, RouteCandidate] = {}

        def upsert(candidate: RouteCandidate) -> None:
            existing = candidates_by_family.get(candidate.route_family)
            if existing is None or candidate.score >= existing.score:
                candidates_by_family[candidate.route_family] = candidate

        if calculation_evaluation is not None and bool(getattr(calculation_evaluation, "candidate", False)):
            upsert(
                RouteCandidate(
                    route_family="calculations",
                    query_shape=QueryShape.CALCULATION_REQUEST.value,
                    score=round(float(getattr(calculation_evaluation, "route_confidence", 0.0) or 0.0), 3),
                    posture_seed="native_candidate",
                    semantic_reasons=list(getattr(calculation_evaluation, "reasons", []) or ["calculation route candidate detected"]),
                    score_factors={"semantic_fit": float(getattr(calculation_evaluation, "route_confidence", 0.0) or 0.0)},
                    required_targets=["expression"],
                )
            )
        if software_control_evaluation is not None and bool(getattr(software_control_evaluation, "candidate", False)):
            target = str(getattr(software_control_evaluation, "target_name", "") or "").strip()
            upsert(
                RouteCandidate(
                    route_family="software_control",
                    query_shape=QueryShape.SOFTWARE_CONTROL_REQUEST.value,
                    score=round(float(getattr(software_control_evaluation, "route_confidence", 0.0) or 0.0), 3),
                    posture_seed="native_candidate",
                    semantic_reasons=list(getattr(software_control_evaluation, "reasons", []) or ["software-control route candidate detected"]),
                    score_factors={
                        "semantic_fit": float(getattr(software_control_evaluation, "route_confidence", 0.0) or 0.0),
                        "ownership_priority": 0.18,
                    },
                    required_targets=["software_target"],
                    target_candidates=[
                        RouteTargetCandidate(
                            target_type="software",
                            label=target,
                            value=target,
                            source="operator_text",
                            confidence=0.9,
                            selected=True,
                        )
                    ]
                    if target
                    else [],
                )
            )
        if screen_awareness_evaluation is not None and screen_awareness_evaluation.candidate:
            upsert(
                RouteCandidate(
                    route_family="screen_awareness",
                    query_shape=QueryShape.SCREEN_AWARENESS_REQUEST.value,
                    score=round(float(screen_awareness_evaluation.route_confidence or 0.0), 3),
                    posture_seed="native_candidate",
                    semantic_reasons=list(screen_awareness_evaluation.reasons or ["screen-awareness route candidate detected"]),
                    score_factors={"semantic_fit": float(screen_awareness_evaluation.route_confidence or 0.0)},
                    required_targets=["visible_screen"],
                    support_augmentation=["active screen context"],
                )
            )
        if semantic is not None and semantic.query_shape != QueryShape.UNCLASSIFIED:
            family = self._route_family_for_semantic(semantic)
            required_targets = self._required_targets_for_semantic(semantic)
            targets = self._target_candidates_for_semantic(semantic)
            score = round(float(semantic.confidence or 0.0), 3)
            if family == "browser_destination" and deictic_binding.selected_source == "recent_session_entity":
                # Bound recent-entity deictic opens below "clear winner" so routing telemetry still reflects live runner-up pressure.
                score = min(score, 0.44)
            if family == "discord_relay" and deictic_binding.resolved:
                score = min(0.99, score + 0.02)
            upsert(
                RouteCandidate(
                    route_family=family,
                    query_shape=semantic.query_shape.value,
                    score=score,
                    posture_seed="semantic_candidate",
                    semantic_reasons=list(semantic.evidence or ["semantic route proposal generated"]),
                    score_factors={
                        "semantic_fit": float(semantic.confidence or 0.0),
                        "target_compatibility": 0.2 if targets else 0.0,
                        "deictic_binding": 0.16 if deictic_binding.resolved else 0.0,
                    },
                    required_targets=required_targets,
                    target_candidates=targets,
                    missing_evidence=list(semantic.slots.get("missing_evidence") or []),
                    clarification_pressure=float(semantic.slots.get("clarification_pressure") or 0.0),
                    support_augmentation=list(semantic.slots.get("support_augmentation") or []),
                )
            )
            if family == "browser_destination" and deictic_binding.selected_source == "recent_session_entity":
                upsert(
                    RouteCandidate(
                        route_family="screen_awareness",
                        query_shape=QueryShape.SCREEN_AWARENESS_REQUEST.value,
                        score=0.36,
                        posture_seed="runner_up_candidate",
                        semantic_reasons=["recent-entity open still competes with live visible-UI grounding"],
                        score_factors={"context_overlap": 0.36},
                        required_targets=["visible_screen"],
                        support_augmentation=["active screen context"],
                    )
                )

        if decomposition.action_intent in {"send", "share", "message"} and "discord_relay" not in candidates_by_family:
            upsert(
                RouteCandidate(
                    route_family="discord_relay",
                    query_shape=QueryShape.DISCORD_RELAY_REQUEST.value,
                    score=0.76,
                    posture_seed="phrase_candidate",
                    semantic_reasons=["send/share wording suggests a relay route"],
                    required_targets=["destination", "payload"],
                    clarification_pressure=0.25 if decomposition.deictic_references else 0.0,
                )
            )
        if decomposition.approval_hints and "trust_approvals" not in candidates_by_family:
            upsert(
                RouteCandidate(
                    route_family="trust_approvals",
                    query_shape=QueryShape.TRUST_APPROVAL_REQUEST.value,
                    score=0.78,
                    posture_seed="phrase_candidate",
                    semantic_reasons=["approval or permission wording suggests the trust route"],
                    required_targets=["approval_object"],
                )
            )
        if decomposition.correction_cues and self._active_search_parameters(active_request_state):
            upsert(
                RouteCandidate(
                    route_family="desktop_search",
                    query_shape=QueryShape.SEARCH_AND_OPEN.value,
                    score=0.86,
                    posture_seed="follow_up_candidate",
                    semantic_reasons=["correction phrase can reuse the active search ambiguity"],
                    required_targets=["search_target"],
                    support_augmentation=["active request state"],
                )
            )

        native_candidates = [candidate for candidate in candidates_by_family.values() if candidate.route_family != "generic_provider" and candidate.score >= 0.35]
        provider_reason = self._provider_fallback_reason(normalized)
        provider_score = 0.72 if not native_candidates and provider_reason == "open_ended_reasoning_or_generation" else 0.35 if not native_candidates else 0.08
        provider_disqualifiers = ["native_route_candidate_present"] if native_candidates else []
        candidates_by_family["generic_provider"] = RouteCandidate(
            route_family="generic_provider",
            query_shape=QueryShape.UNCLASSIFIED.value,
            score=provider_score,
            posture_seed="fallback_candidate",
            semantic_reasons=[
                "provider fallback is available only when no native family truthfully owns the request"
            ],
            score_factors={"fallback_fit": provider_score},
            disqualifiers=provider_disqualifiers,
            provider_fallback_reason=provider_reason,
        )
        return list(candidates_by_family.values())

    def _decompose_request(
        self,
        normalized: NormalizedCommand,
        *,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> RequestDecomposition:
        del active_context, recent_tool_results
        lower = normalized.normalized_text
        tokens = list(normalized.tokens)
        deictic = [token for token in tokens if token in {"this", "that", "it", "these", "those"}]
        if (
            re.search(r"\bsame\b.{0,24}\b(?:before|thing|action|route|result|request)\b", lower)
            or re.search(r"\b(?:again|continue|resume)\b", lower)
            or re.search(r"\bwhere\b.{0,16}\bleft\s+off\b", lower)
        ):
            continuity = ["continuity"]
        else:
            continuity = []
        correction = []
        if lower.startswith(("no ", "no,", "nah ", "not ")) or any(phrase in lower for phrase in {"not that", "instead", "the other one"}):
            correction.append("correction")
        approval = []
        if any(phrase in lower for phrase in {"why are you asking", "why do you need confirmation", "permission", "allow this", "approve", "confirmation"}):
            approval.append("approval")
        verification = []
        if any(phrase in lower for phrase in {"did it work", "did that work", "verify", "check if", "actually do anything"}):
            verification.append("verification")

        action_intent = None
        for action, verbs in {
            "send": {"send", "share", "message", "post"},
            "open": {"open", "show", "launch", "start"},
            "install": {"install", "download", "get", "put", "setup", "set"},
            "resume": {"continue", "resume", "restore"},
            "explain": {"why", "explain", "what"},
        }.items():
            if tokens and tokens[0] in verbs:
                action_intent = action
                break
        if action_intent is None and any(token in tokens for token in {"send", "share", "message"}):
            action_intent = "send"
        if action_intent is None and approval:
            action_intent = "explain"

        subject = None
        if active_request_state.get("subject"):
            subject = str(active_request_state.get("subject") or "").strip() or None
        quoted_targets = [
            RouteTargetCandidate(
                target_type="quoted_text",
                label=match.group(1),
                value=match.group(1),
                source="operator_text",
                confidence=0.95,
                selected=True,
            )
            for match in re.finditer(r"\"([^\"]+)\"", normalized.raw_text)
        ]
        return RequestDecomposition(
            action_intent=action_intent,
            subject=subject,
            explicit_targets=quoted_targets,
            deictic_references=deictic,
            continuity_cues=continuity,
            correction_cues=correction,
            result_expectation="verification" if verification else None,
            approval_hints=approval,
            verification_hints=verification,
        )

    def _resolve_deictic_binding(
        self,
        decomposition: RequestDecomposition,
        *,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> DeicticBinding:
        if not decomposition.deictic_references and not decomposition.correction_cues:
            return DeicticBinding(binding_posture="none", source_summary="No deictic reference was present.")
        candidates = self._deictic_binding_candidates(
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        if not candidates:
            return DeicticBinding(
                resolved=False,
                candidates=[],
                unresolved_reason="no_current_binding_source",
                binding_posture="unbound",
                source_summary="No current preview, selection, workspace item, or recent entity could bind the reference.",
            )
        strongest = sorted(candidates, key=lambda item: item.confidence, reverse=True)
        top = strongest[0]
        if len(strongest) > 1 and abs(top.confidence - strongest[1].confidence) < 0.08:
            return DeicticBinding(
                resolved=False,
                candidates=strongest,
                unresolved_reason="multiple_live_binding_candidates",
                binding_posture="ambiguous",
                source_summary="Multiple current binding sources remain live.",
            )
        return DeicticBinding(
            resolved=True,
            selected_source=top.source,
            selected_target=top,
            candidates=strongest,
            binding_posture=self._binding_posture(top),
            source_summary=f"Bound deictic reference from {top.source}.",
        )

    def _deictic_binding_candidates(
        self,
        *,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> list[DeicticBindingCandidate]:
        candidates: list[DeicticBindingCandidate] = []
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        pending_preview = parameters.get("pending_preview") if isinstance(parameters.get("pending_preview"), dict) else {}
        if pending_preview:
            candidates.append(
                DeicticBindingCandidate(
                    source="active_preview",
                    target_type="preview",
                    label=str(active_request_state.get("subject") or parameters.get("destination_alias") or "active preview"),
                    value=dict(pending_preview),
                    confidence=0.99,
                    route_family=str(active_request_state.get("family") or "").strip() or None,
                )
            )
        trust = active_request_state.get("trust") if isinstance(active_request_state.get("trust"), dict) else {}
        if trust:
            candidates.append(
                DeicticBindingCandidate(
                    source="active_approval",
                    target_type="approval",
                    label=str(active_request_state.get("subject") or "approval request"),
                    value=dict(trust),
                    confidence=0.88,
                    route_family="trust_approvals",
                )
            )
        selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
        if selection.get("value"):
            candidates.append(
                DeicticBindingCandidate(
                    source="selection",
                    target_type=str(selection.get("kind") or "selected_text"),
                    label=str(selection.get("preview") or "selected text"),
                    value=selection.get("value"),
                    confidence=0.9,
                    route_family="context",
                )
            )
        clipboard = active_context.get("clipboard") if isinstance(active_context.get("clipboard"), dict) else {}
        if clipboard.get("value"):
            candidates.append(
                DeicticBindingCandidate(
                    source="clipboard",
                    target_type=str(clipboard.get("kind") or "clipboard"),
                    label=str(clipboard.get("preview") or "clipboard"),
                    value=clipboard.get("value"),
                    confidence=0.84,
                    route_family="context",
                )
            )
        subject = str(active_request_state.get("subject") or "").strip()
        family = str(active_request_state.get("family") or "").strip()
        if subject and family:
            candidates.append(
                DeicticBindingCandidate(
                    source="current_route_target",
                    target_type=family,
                    label=subject,
                    value=subject,
                    confidence=0.72,
                    route_family=family,
                )
            )
        recent_entities = active_context.get("recent_entities", []) if isinstance(active_context.get("recent_entities"), list) else []
        for index, entity in enumerate(recent_entities):
            if not isinstance(entity, dict):
                continue
            url = str(entity.get("url") or "").strip()
            path = str(entity.get("path") or "").strip()
            title = str(entity.get("title") or entity.get("name") or url or path or "recent entity").strip()
            kind = str(entity.get("kind") or ("page" if url else "file" if path else "entity")).strip()
            if not url and not path:
                continue
            freshness = self._entity_freshness(entity, index=index)
            candidates.append(
                DeicticBindingCandidate(
                    source="recent_session_entity",
                    target_type=kind,
                    label=title,
                    value=url or path,
                    confidence=self._recent_entity_confidence(freshness),
                    freshness=freshness,
                    route_family="browser_destination" if url else "files",
                )
            )
        if recent_tool_results:
            latest = recent_tool_results[0]
            if isinstance(latest, dict):
                candidates.append(
                    DeicticBindingCandidate(
                        source="recent_subsystem_result",
                        target_type=str(latest.get("family") or latest.get("tool_name") or "tool_result"),
                        label=str(latest.get("tool_name") or latest.get("family") or "recent result"),
                        value=dict(latest),
                        confidence=0.64,
                        freshness="recent",
                        route_family=str(latest.get("family") or "").strip() or None,
                    )
                )
        return candidates

    def _semantic_deictic_binding(self, semantic: SemanticParseProposal | None) -> DeicticBinding | None:
        if semantic is None or not isinstance(semantic.slots, dict):
            return None
        payload = semantic.slots.get("deictic_binding")
        if not isinstance(payload, dict):
            return None
        selected_target_payload = payload.get("selected_target") if isinstance(payload.get("selected_target"), dict) else None
        selected_target = self._binding_candidate_from_payload(selected_target_payload) if selected_target_payload else None
        candidate_payloads = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        candidates = [
            candidate
            for candidate in (self._binding_candidate_from_payload(item) for item in candidate_payloads if isinstance(item, dict))
            if candidate is not None
        ]
        binding_posture = str(payload.get("binding_posture") or "").strip() or (
            self._binding_posture(selected_target) if selected_target is not None else "ambiguous" if candidates else "unbound"
        )
        return DeicticBinding(
            resolved=bool(payload.get("resolved", False)),
            selected_source=str(payload.get("selected_source") or "").strip() or None,
            selected_target=selected_target,
            candidates=candidates,
            unresolved_reason=str(payload.get("unresolved_reason") or "").strip() or None,
            binding_posture=binding_posture,
            source_summary=str(payload.get("source_summary") or "").strip()
            or (
                f"Bound deictic reference from {selected_target.source}."
                if selected_target is not None
                else "Route-specific binding remains unresolved."
            ),
        )

    def _binding_candidate_from_payload(self, payload: dict[str, Any] | None) -> DeicticBindingCandidate | None:
        if not isinstance(payload, dict):
            return None
        label = str(payload.get("label") or payload.get("source") or "context target").strip()
        source = str(payload.get("source") or "context").strip()
        target_type = str(payload.get("target_type") or "context").strip()
        return DeicticBindingCandidate(
            source=source,
            target_type=target_type,
            label=label,
            value=payload.get("value"),
            confidence=float(payload.get("confidence") or 0.0),
            freshness=str(payload.get("freshness") or "current").strip() or "current",
            route_family=str(payload.get("route_family") or "").strip() or None,
        )

    def _binding_posture(self, candidate: DeicticBindingCandidate | None) -> str:
        if candidate is None:
            return "unbound"
        if candidate.freshness in {"stale", "superseded", "expired"}:
            return "stale"
        if candidate.source in {"active_preview", "current_route_target", "recent_subsystem_result"}:
            return "continuity_reuse"
        return "current"

    def _entity_freshness(self, entity: dict[str, Any], *, index: int) -> str:
        explicit = str(entity.get("freshness") or entity.get("recency") or "").strip().lower()
        if explicit in {"current", "recent", "cooling", "stale", "superseded", "expired"}:
            return explicit
        if bool(entity.get("stale", False)):
            return "stale"
        if bool(entity.get("superseded", False)):
            return "superseded"
        if index == 0:
            return "recent"
        if index == 1:
            return "cooling"
        return "stale"

    def _recent_entity_confidence(self, freshness: str) -> float:
        return {
            "current": 0.88,
            "recent": 0.78,
            "cooling": 0.62,
            "stale": 0.28,
            "superseded": 0.16,
            "expired": 0.12,
        }.get(freshness, 0.55)

    def _route_family_for_decision(self, decision: PlannerDecision) -> str:
        if decision.request_type == "unclassified":
            return "generic_provider"
        if decision.execution_plan is not None and decision.execution_plan.family:
            family = str(decision.execution_plan.family).strip()
            if family:
                return self._canonical_route_family(family)
        if decision.structured_query is not None:
            slots = decision.structured_query.slots if isinstance(decision.structured_query.slots, dict) else {}
            family = str(slots.get("family") or decision.structured_query.domain or "").strip()
            if family:
                return self._canonical_route_family(family)
            if decision.structured_query.query_shape == QueryShape.WEB_RETRIEVAL_REQUEST:
                return "web_retrieval"
            if decision.structured_query.query_shape == QueryShape.TRUST_APPROVAL_REQUEST:
                return "trust_approvals"
        if decision.request_type == "guardrail_clarify":
            family = str(decision.debug.get("guardrail_route_family") or "").strip()
            if family:
                return self._canonical_route_family(family)
            return "trust_approvals"
        return "generic_provider"

    def _route_family_for_semantic(self, semantic: SemanticParseProposal) -> str:
        slots = semantic.slots if isinstance(semantic.slots, dict) else {}
        family = str(slots.get("family") or semantic.domain or "").strip()
        if semantic.query_shape == QueryShape.TRUST_APPROVAL_REQUEST:
            return "trust_approvals"
        if semantic.query_shape == QueryShape.DISCORD_RELAY_REQUEST:
            return "discord_relay"
        if semantic.query_shape == QueryShape.WEB_RETRIEVAL_REQUEST:
            return "web_retrieval"
        if semantic.query_shape == QueryShape.CAMERA_AWARENESS_REQUEST:
            return "camera_awareness"
        if semantic.query_shape == QueryShape.OPEN_BROWSER_DESTINATION:
            return "browser_destination"
        if semantic.query_shape in {QueryShape.SEARCH_REQUEST, QueryShape.SEARCH_AND_OPEN}:
            return "desktop_search"
        return self._canonical_route_family(family or semantic.query_shape.value)

    def _canonical_route_family(self, family: str) -> str:
        aliases = {
            "workspace": "workspace_operations",
            "relay": "discord_relay",
            "discord": "discord_relay",
            "trust": "trust_approvals",
            "approval": "trust_approvals",
            "files": "file",
            "power_projection": "power",
            "resource": "resources",
            "trusted_hook": "routine",
            "browser_context": "watch_runtime",
            "activity_summary": "watch_runtime",
            "active_apps": "app_control",
            "recent_files": "machine",
            "network_diagnosis": "network",
            "resource_diagnosis": "resources",
            "storage_diagnosis": "storage",
            "app_control": "software_control" if family == "software_control" else "app_control",
        }
        return aliases.get(family, family)

    def _required_targets_for_semantic(self, semantic: SemanticParseProposal) -> list[str]:
        if semantic.query_shape == QueryShape.DISCORD_RELAY_REQUEST:
            return ["destination", "payload"]
        if semantic.query_shape == QueryShape.SOFTWARE_CONTROL_REQUEST:
            return ["software_target"]
        if semantic.query_shape == QueryShape.WEB_RETRIEVAL_REQUEST:
            return ["public_url"]
        if semantic.query_shape == QueryShape.CAMERA_AWARENESS_REQUEST:
            return ["camera_capture_confirmation"]
        if semantic.query_shape in {QueryShape.OPEN_BROWSER_DESTINATION, QueryShape.SEARCH_AND_OPEN}:
            return ["target"]
        if semantic.query_shape == QueryShape.TRUST_APPROVAL_REQUEST:
            return ["approval_object"]
        return []

    def _target_candidates_for_semantic(self, semantic: SemanticParseProposal) -> list[RouteTargetCandidate]:
        slots = semantic.slots if isinstance(semantic.slots, dict) else {}
        targets: list[RouteTargetCandidate] = []
        if slots.get("destination_alias"):
            targets.append(
                RouteTargetCandidate(
                    target_type="relay_recipient",
                    label=str(slots.get("destination_alias")),
                    value=str(slots.get("destination_alias")),
                    source="operator_text",
                    confidence=0.9,
                    selected=True,
                )
            )
        if slots.get("target_name"):
            targets.append(
                RouteTargetCandidate(
                    target_type="software",
                    label=str(slots.get("target_name")),
                    value=str(slots.get("target_name")),
                    source="operator_text",
                    confidence=0.9,
                    selected=True,
                )
            )
        deictic = slots.get("deictic_binding") if isinstance(slots.get("deictic_binding"), dict) else {}
        selected_target = deictic.get("selected_target") if isinstance(deictic.get("selected_target"), dict) else {}
        if selected_target:
            targets.append(
                RouteTargetCandidate(
                    target_type=str(selected_target.get("target_type") or "context"),
                    label=str(selected_target.get("label") or selected_target.get("source") or "context target"),
                    value=selected_target.get("value"),
                    source=str(selected_target.get("source") or "context"),
                    confidence=float(selected_target.get("confidence") or 0.0),
                    freshness=str(selected_target.get("freshness") or "current"),
                    selected=True,
                )
            )
        return targets

    def _provider_fallback_reason(self, normalized: NormalizedCommand) -> str:
        lower = normalized.normalized_text
        if any(lower.startswith(prefix) for prefix in {"write ", "brainstorm ", "draft ", "compose ", "explain "}) or any(
            phrase in lower for phrase in {"poetic explanation", "compare these philosophies", "brainstorm ten", "fictional"}
        ):
            return "open_ended_reasoning_or_generation"
        return "no_native_route_family_meaningfully_owns_request"

    def _unresolved_targets_from_clarification(self, clarification: ClarificationReason) -> list[str]:
        if clarification.code == "ambiguous_relay_payload":
            return ["payload"]
        if clarification.code == "ambiguous_open_target":
            return ["target"]
        return list(clarification.missing_slots)

    def _active_search_parameters(self, active_request_state: dict[str, Any]) -> dict[str, Any] | None:
        family = str(active_request_state.get("family") or "").strip().lower()
        if family not in {"desktop_search", "search"}:
            return None
        parameters = active_request_state.get("parameters")
        return dict(parameters) if isinstance(parameters, dict) else {}

    def _tool_proposal(
        self,
        *,
        query_shape: QueryShape,
        domain: str | None,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        request_type_hint: str | None = None,
        family: str | None = None,
        subject: str | None = None,
        requested_metric: str | None = None,
        requested_action: str | None = None,
        timescale: str | None = None,
        output_type: str | None = None,
        diagnostic_mode: bool = False,
        confidence: float = 0.9,
        evidence: list[str] | None = None,
        follow_up: bool = False,
        assistant_message: str | None = None,
        execution_type: str | None = None,
        output_mode: str | None = None,
        fallback_path: str | None = None,
        slots: dict[str, Any] | None = None,
    ) -> SemanticParseProposal:
        proposal_slots = dict(slots or {})
        if tool_name is not None:
            proposal_slots["tool_name"] = tool_name
        if tool_arguments is not None:
            proposal_slots["tool_arguments"] = dict(tool_arguments)
        if request_type_hint is not None:
            proposal_slots["request_type_hint"] = request_type_hint
        if family is not None:
            proposal_slots["family"] = family
        if subject is not None:
            proposal_slots["subject"] = subject
        if timescale is not None:
            proposal_slots["timescale"] = timescale
        if output_type is not None:
            proposal_slots["output_type"] = output_type
        if assistant_message is not None:
            proposal_slots["assistant_message"] = assistant_message
        if execution_type is not None:
            proposal_slots["execution_type"] = execution_type
        if output_mode is not None:
            proposal_slots["output_mode"] = output_mode
        if diagnostic_mode:
            proposal_slots["diagnostic_mode"] = True
        return SemanticParseProposal(
            query_shape=query_shape,
            domain=domain,
            requested_metric=requested_metric,
            requested_action=requested_action,
            slots=proposal_slots,
            confidence=confidence,
            evidence=list(evidence or []),
            follow_up=follow_up,
            fallback_path=fallback_path,
        )

    def _merge_route_spine_proposal(
        self,
        proposal: SemanticParseProposal,
        *,
        slots: dict[str, Any],
        evidence_note: str | None = None,
    ) -> SemanticParseProposal:
        merged_slots = {**slots, **dict(proposal.slots or {})}
        merged_evidence = list(proposal.evidence or [])
        if evidence_note and evidence_note not in merged_evidence:
            merged_evidence.append(evidence_note)
        return SemanticParseProposal(
            query_shape=proposal.query_shape,
            domain=proposal.domain,
            requested_metric=proposal.requested_metric,
            requested_action=proposal.requested_action,
            slots=merged_slots,
            confidence=proposal.confidence,
            evidence=merged_evidence,
            follow_up=proposal.follow_up,
            fallback_path=proposal.fallback_path,
        )

    def _screen_awareness_semantic_proposal(
        self,
        screen_awareness_evaluation: ScreenPlannerEvaluation | None,
    ) -> SemanticParseProposal | None:
        if screen_awareness_evaluation is None:
            return None
        if screen_awareness_evaluation.disposition in {
            ScreenRouteDisposition.ROUTING_DISABLED,
            ScreenRouteDisposition.FEATURE_DISABLED,
        }:
            fallback_path = (
                "screen_awareness_routing_disabled"
                if screen_awareness_evaluation.disposition == ScreenRouteDisposition.ROUTING_DISABLED
                else "screen_awareness_feature_disabled"
            )
            return SemanticParseProposal(
                query_shape=QueryShape.UNCLASSIFIED,
                domain="screen_awareness",
                confidence=0.0,
                evidence=list(screen_awareness_evaluation.reasons)
                or ["screen-awareness candidate recorded but native planner routing is unavailable"],
                fallback_path=fallback_path,
                slots={
                    "target_scope": "screen",
                    "screen_awareness": screen_awareness_evaluation.to_dict(),
                    "response_contract": dict(screen_awareness_evaluation.response_contract or {}),
                },
            )
        if screen_awareness_evaluation.disposition in {
            ScreenRouteDisposition.PHASE1_ANALYZE,
            ScreenRouteDisposition.PHASE2_GROUND,
            ScreenRouteDisposition.PHASE3_GUIDE,
            ScreenRouteDisposition.PHASE4_VERIFY,
            ScreenRouteDisposition.PHASE5_ACT,
            ScreenRouteDisposition.PHASE6_CONTINUE,
            ScreenRouteDisposition.PHASE8_PROBLEM_SOLVE,
            ScreenRouteDisposition.PHASE9_WORKFLOW_REUSE,
            ScreenRouteDisposition.PHASE10_BRAIN_INTEGRATION,
            ScreenRouteDisposition.PHASE11_POWER,
        }:
            execution_type = (
                "screen_awareness_act"
                if screen_awareness_evaluation.disposition == ScreenRouteDisposition.PHASE5_ACT
                else "screen_awareness_continue"
                if screen_awareness_evaluation.disposition == ScreenRouteDisposition.PHASE6_CONTINUE
                else "screen_awareness_workflow"
                if screen_awareness_evaluation.disposition == ScreenRouteDisposition.PHASE9_WORKFLOW_REUSE
                else "screen_awareness_brain"
                if screen_awareness_evaluation.disposition == ScreenRouteDisposition.PHASE10_BRAIN_INTEGRATION
                else "screen_awareness_power"
                if screen_awareness_evaluation.disposition == ScreenRouteDisposition.PHASE11_POWER
                else "screen_awareness_analyze"
            )
            output_mode = (
                ResponseMode.ACTION_RESULT.value
                if screen_awareness_evaluation.disposition == ScreenRouteDisposition.PHASE5_ACT
                else ResponseMode.SUMMARY_RESULT.value
            )
            output_type = (
                "screen_action"
                if screen_awareness_evaluation.disposition == ScreenRouteDisposition.PHASE5_ACT
                else "screen_analysis"
            )
            return self._tool_proposal(
                query_shape=QueryShape.SCREEN_AWARENESS_REQUEST,
                domain="screen_awareness",
                request_type_hint="screen_awareness_response",
                family="screen_awareness",
                subject=str(screen_awareness_evaluation.intent.value if screen_awareness_evaluation.intent else "screen"),
                requested_action=str(
                    screen_awareness_evaluation.intent.value if screen_awareness_evaluation.intent is not None else ""
                )
                or None,
                confidence=screen_awareness_evaluation.route_confidence,
                evidence=list(screen_awareness_evaluation.reasons),
                execution_type=execution_type,
                output_mode=output_mode,
                output_type=output_type,
                slots={
                    "target_scope": "screen",
                    "screen_awareness": screen_awareness_evaluation.to_dict(),
                    "response_contract": dict(screen_awareness_evaluation.response_contract),
                },
            )
        if screen_awareness_evaluation.disposition == ScreenRouteDisposition.PHASE0_SCAFFOLD:
            response_contract = dict(screen_awareness_evaluation.response_contract)
            analysis_result = (
                screen_awareness_evaluation.analysis_result.to_dict()
                if screen_awareness_evaluation.analysis_result is not None
                else {}
            )
            return self._tool_proposal(
                query_shape=QueryShape.SCREEN_AWARENESS_REQUEST,
                domain="screen_awareness",
                request_type_hint="screen_awareness_scaffold",
                family="screen_awareness",
                subject=str(screen_awareness_evaluation.intent.value if screen_awareness_evaluation.intent else "screen"),
                requested_action=str(
                    screen_awareness_evaluation.intent.value if screen_awareness_evaluation.intent is not None else ""
                )
                or None,
                confidence=screen_awareness_evaluation.route_confidence,
                evidence=list(screen_awareness_evaluation.reasons),
                assistant_message=str(response_contract.get("full_response") or "").strip() or None,
                execution_type="screen_awareness_scaffold",
                output_mode=ResponseMode.UNSUPPORTED.value,
                output_type="screen_analysis",
                slots={
                    "target_scope": "screen",
                    "screen_awareness": screen_awareness_evaluation.to_dict(),
                    "screen_analysis_result": analysis_result,
                    "truthfulness_contract": analysis_result.get("truthfulness_contract", {}),
                    "unsupported_reason_code": "screen_awareness_observation_unavailable",
                    "unsupported_response_contract": response_contract,
                    "response_contract": response_contract,
                },
            )
        return None

    def _screen_awareness_route_spine_override_allowed(
        self,
        decision: RouteSpineDecision,
        screen_awareness_evaluation: ScreenPlannerEvaluation | None,
    ) -> bool:
        if screen_awareness_evaluation is None or not bool(getattr(screen_awareness_evaluation, "candidate", False)):
            return False
        disposition = getattr(screen_awareness_evaluation, "disposition", None)
        if disposition not in {
            ScreenRouteDisposition.PHASE1_ANALYZE,
            ScreenRouteDisposition.PHASE2_GROUND,
            ScreenRouteDisposition.PHASE3_GUIDE,
            ScreenRouteDisposition.PHASE4_VERIFY,
            ScreenRouteDisposition.PHASE5_ACT,
            ScreenRouteDisposition.PHASE6_CONTINUE,
            ScreenRouteDisposition.PHASE8_PROBLEM_SOLVE,
            ScreenRouteDisposition.PHASE9_WORKFLOW_REUSE,
            ScreenRouteDisposition.PHASE10_BRAIN_INTEGRATION,
            ScreenRouteDisposition.PHASE11_POWER,
            ScreenRouteDisposition.ROUTING_DISABLED,
            ScreenRouteDisposition.FEATURE_DISABLED,
        }:
            return False
        family = decision.winner.route_family
        if family == "screen_awareness":
            return True
        if family == "task_continuity":
            return disposition == ScreenRouteDisposition.PHASE6_CONTINUE
        if family in {"routine", "workflow"}:
            return disposition in {
                ScreenRouteDisposition.PHASE9_WORKFLOW_REUSE,
                ScreenRouteDisposition.PHASE10_BRAIN_INTEGRATION,
            }
        if family == "context_clarification":
            reason = str(getattr(decision.intent_frame, "clarification_reason", "") or "")
            return reason not in {"page_context", "verification_context"}
        return False

    def _normalize_command(
        self,
        message: str,
        *,
        surface_mode: str,
        active_module: str,
    ) -> NormalizedCommand:
        command_text = self._strip_invocation_prefix(message)
        normalized_text = normalize_phrase(command_text)
        tokens = [token for token in normalized_text.split() if token]
        explicitness_level = "explicit"
        if len(tokens) <= 3:
            explicitness_level = "terse"
        if tokens and any(token in {"this", "that", "it", "these", "those"} for token in tokens):
            explicitness_level = "deictic"
        return NormalizedCommand(
            raw_text=command_text,
            normalized_text=normalized_text,
            tokens=tokens,
            surface_mode=surface_mode,
            active_module=active_module,
            explicitness_level=explicitness_level,
        )

    def _strip_invocation_prefix(self, message: str) -> str:
        text = re.sub(r"^\s*stormhelm\s*[,:\-]\s*", "", str(message or ""), flags=re.IGNORECASE).strip()
        return self._strip_operator_wrappers(text)

    def _strip_operator_wrappers(self, message: str) -> str:
        text = " ".join(str(message or "").split()).strip()
        if not text:
            return ""
        negative_match = re.match(
            r"^don['’]?t\s+actually\s+(.+?)\s*;\s*tell\s+me\s+the\s+safe\s+route\s*$",
            text,
            flags=re.IGNORECASE,
        )
        if negative_match:
            text = str(negative_match.group(1) or "").strip()
        text = re.sub(r"^\s*i\s+need\s+the\s+stormhelm\s+route\s+for\s+this\s*:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*(?:hey\s+)?(?:can|could)\s+you\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*(?:please|pls)\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*yo\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\s*uh+h+\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+real\s+quick\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*--\s*quick\s+quick\s*$", "", text, flags=re.IGNORECASE)
        return self._repair_common_command_typos(text.strip(" ?"))

    def _operator_wrapper_browser_near_miss(self, message: str, normalized_text: str) -> bool:
        original = " ".join(str(message or "").split()).strip().lower()
        if not re.match(r"^i\s+need\s+the\s+stormhelm\s+route\s+for\s+this\s*:", original):
            return False
        return bool(
            re.search(r"\b(?:almost|nearly|sort of|kind of)\b.{0,32}\b(?:open|launch|navigate|go to)\b.{0,32}\bbrowser\b", normalized_text)
            and re.search(r"\b(?:not exactly|not quite|but not|instead)\b", normalized_text)
        )

    def _repair_common_command_typos(self, message: str) -> str:
        replacements = (
            (r"\bopne\b", "open"),
            (r"\binstal\b", "install"),
            (r"\bcurrnt\b", "current"),
            (r"\bwether\b", "weather"),
            (r"\bbatery\b", "battery"),
            (r"\bnetwrk\b", "network"),
            (r"\bwrkspace\b", "workspace"),
            (r"\bDiscrod\b", "Discord"),
            (r"\bdiagnoze\b", "diagnose"),
            (r"\butube\b", "youtube"),
        )
        text = message
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def _decision_from_semantic(
        self,
        semantic: SemanticParseProposal,
        *,
        debug: dict[str, Any],
        normalized: NormalizedCommand,
        decomposition: RequestDecomposition,
        session_id: str,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
        calculation_evaluation: Any | None,
        software_control_evaluation: Any | None,
        screen_awareness_evaluation: ScreenPlannerEvaluation | None,
        available_tools: set[str],
    ) -> PlannerDecision:
        structured_query, clarification_reason = self._validate_structured_query(
            semantic,
            normalized=normalized,
            active_context=active_context,
        )
        debug["structured_query"] = structured_query.to_dict()
        if clarification_reason is not None:
            clarification_execution_plan: ExecutionPlan | None = None
            clarification_active_state: dict[str, object] = {}
            if structured_query.query_shape == QueryShape.CAMERA_AWARENESS_REQUEST:
                clarification_execution_plan = ExecutionPlan(
                    plan_type=structured_query.execution_type
                    or "camera_awareness_c0_mock_or_permission_gate",
                    request_type=str(
                        structured_query.slots.get("request_type_hint")
                        or "camera_awareness_confirmation"
                    ),
                    response_mode=ResponseMode.CLARIFICATION,
                    family=str(
                        structured_query.slots.get("family")
                        or structured_query.domain
                        or "camera_awareness"
                    ),
                    subject=str(
                        structured_query.slots.get("subject")
                        or structured_query.domain
                        or "camera still"
                    ),
                    assistant_message=clarification_reason.message,
                )
                clarification_active_state = self._active_request_state_from_structured_query(
                    structured_query,
                    clarification_execution_plan,
                )
                debug["execution_plan"] = clarification_execution_plan.to_dict()
            debug["clarification_reason"] = clarification_reason.to_dict()
            debug["response_mode"] = ResponseMode.CLARIFICATION.value
            return self._finalize_decision(
                PlannerDecision(
                    request_type="clarification_request",
                    assistant_message=clarification_reason.message,
                    active_request_state=clarification_active_state,
                    structured_query=structured_query,
                    execution_plan=clarification_execution_plan,
                    clarification_reason=clarification_reason,
                    response_mode=ResponseMode.CLARIFICATION.value,
                    debug=debug,
                ),
                normalized=normalized,
                decomposition=decomposition,
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                semantic=semantic,
                clarification_reason=clarification_reason,
                active_context=active_context,
                active_request_state=active_request_state,
                recent_tool_results=recent_tool_results,
            )

        if structured_query.query_shape == QueryShape.UNCLASSIFIED:
            debug["response_mode"] = ResponseMode.SUMMARY_RESULT.value
            return self._finalize_decision(
                PlannerDecision(
                    request_type="unclassified",
                    structured_query=structured_query,
                    response_mode=ResponseMode.SUMMARY_RESULT.value,
                    debug=debug,
                ),
                normalized=normalized,
                decomposition=decomposition,
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                semantic=semantic,
                active_context=active_context,
                active_request_state=active_request_state,
                recent_tool_results=recent_tool_results,
            )

        capability_plan = self._plan_capabilities(structured_query, available_tools=available_tools)
        debug["capability_plan"] = capability_plan.to_dict()
        provisional_execution_plan = self._build_execution_plan(
            structured_query,
            capability_plan=capability_plan,
            session_id=session_id,
        )
        if not capability_plan.supported and capability_plan.unsupported_reason is not None:
            debug["unsupported_reason"] = capability_plan.unsupported_reason.to_dict()
            debug["execution_plan"] = provisional_execution_plan.to_dict()
            debug["response_mode"] = ResponseMode.UNSUPPORTED.value
            return self._finalize_decision(
                PlannerDecision(
                    request_type="unsupported_capability",
                    assistant_message=capability_plan.unsupported_reason.message,
                    structured_query=structured_query,
                    capability_plan=capability_plan,
                    execution_plan=provisional_execution_plan,
                    unsupported_reason=capability_plan.unsupported_reason,
                    response_mode=ResponseMode.UNSUPPORTED.value,
                    debug=debug,
                ),
                normalized=normalized,
                decomposition=decomposition,
                calculation_evaluation=calculation_evaluation,
                software_control_evaluation=software_control_evaluation,
                screen_awareness_evaluation=screen_awareness_evaluation,
                semantic=semantic,
                unsupported_reason=capability_plan.unsupported_reason,
                active_context=active_context,
                active_request_state=active_request_state,
                recent_tool_results=recent_tool_results,
            )

        execution_plan = provisional_execution_plan
        debug["execution_plan"] = execution_plan.to_dict()
        debug["response_mode"] = execution_plan.response_mode.value
        tool_requests: list[ToolRequest] = []
        if execution_plan.tool_name:
            tool_requests.append(ToolRequest(execution_plan.tool_name, dict(execution_plan.tool_arguments)))
        return self._finalize_decision(
            PlannerDecision(
                request_type=execution_plan.request_type,
                tool_requests=tool_requests,
                assistant_message=execution_plan.assistant_message,
                requires_reasoner=execution_plan.requires_reasoner,
                active_request_state=self._active_request_state_from_structured_query(structured_query, execution_plan),
                structured_query=structured_query,
                capability_plan=capability_plan,
                execution_plan=execution_plan,
                response_mode=execution_plan.response_mode.value,
                debug=debug,
            ),
            normalized=normalized,
            decomposition=decomposition,
            calculation_evaluation=calculation_evaluation,
            software_control_evaluation=software_control_evaluation,
            screen_awareness_evaluation=screen_awareness_evaluation,
            semantic=semantic,
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )

    def _semantic_from_route_spine_decision(
        self,
        decision: RouteSpineDecision,
        *,
        message: str,
        normalized: NormalizedCommand,
        surface_mode: str,
        workspace_context: dict[str, Any] | None,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        active_posture: dict[str, Any],
        calculation_evaluation: Any | None,
        software_control_evaluation: Any | None,
        screen_awareness_evaluation: ScreenPlannerEvaluation | None,
        planner_v2_trace: Any | None = None,
        learned_preferences: dict[str, dict[str, object]] | None = None,
    ) -> SemanticParseProposal:
        family = decision.winner.route_family
        slots = self._route_spine_slots(decision)
        if family == "generic_provider":
            return SemanticParseProposal(
                query_shape=QueryShape.UNCLASSIFIED,
                confidence=0.0,
                evidence=["route_spine allowed generic provider only after migrated native specs declined"],
                fallback_path="route_spine_generic_provider",
                slots=slots,
            )
        planner_v2_proposal = self._planner_v2_plan_draft_proposal(
            planner_v2_trace,
            decision,
            slots=slots,
            learned_preferences=learned_preferences or {},
        )
        if planner_v2_proposal is not None:
            return planner_v2_proposal
        if decision.clarification_needed and family == "file":
            return self._route_spine_clarification_proposal(decision, slots=slots)
        lower = decision.intent_frame.normalized_text
        if (
            family == "calculations"
            and decision.clarification_needed
            and not self._calculation_route_spine_reuse_available(calculation_evaluation)
        ):
            return self._route_spine_clarification_proposal(decision, slots=slots)
        if (
            family == "screen_awareness"
            and decision.clarification_needed
            and self._screen_action_requires_bound_target(lower, screen_awareness_evaluation)
        ):
            return self._route_spine_clarification_proposal(decision, slots=slots)
        if family == "camera_awareness":
            slots.update(
                {
                    "source_provenance": "camera_request",
                    "target_scope": "camera_frame",
                    "capture_mode": "single_still",
                    "requires_confirmation": True,
                    "camera_awareness": {
                        "route_family": "camera_awareness",
                        "phase": "c0",
                        "provider_kind": "mock",
                        "real_camera_implemented": False,
                        "openai_vision_implemented": False,
                        "cloud_upload_allowed": False,
                        "background_capture_allowed": False,
                        "image_persistence_default": False,
                    },
                    "clarification": {
                        "code": "camera_capture_confirmation_required",
                        "message": "I can use a camera still for that, but camera capture needs confirmation first.",
                        "missing_slots": ["camera_capture_confirmation"],
                    },
                    "missing_preconditions": ["camera_capture_confirmation"],
                }
            )
            return self._tool_proposal(
                query_shape=QueryShape.CAMERA_AWARENESS_REQUEST,
                domain="camera_awareness",
                request_type_hint="camera_awareness_confirmation",
                family="camera_awareness",
                subject=decision.intent_frame.target_text or "camera still",
                requested_action="request_single_still",
                confidence=decision.winner.score or 0.88,
                evidence=["route_spine selected camera_awareness from explicit camera or physical-object request"],
                assistant_message="I can use a camera still for that, but camera capture needs confirmation first.",
                execution_type="camera_awareness_c0_mock_or_permission_gate",
                output_mode=ResponseMode.CLARIFICATION.value,
                output_type="camera_awareness",
                slots=slots,
            )
        screen_proposal = self._screen_awareness_semantic_proposal(screen_awareness_evaluation)
        if (
            screen_proposal is not None
            and self._screen_awareness_route_spine_override_allowed(decision, screen_awareness_evaluation)
        ):
            return self._merge_route_spine_proposal(
                screen_proposal,
                slots=slots,
                evidence_note="route_spine preserved screen_awareness authority while restoring planner contract details",
            )
        if family == "context_clarification" and str(getattr(decision.intent_frame, "clarification_reason", "") or "") in {
            "page_context",
            "verification_context",
        }:
            return self._route_spine_clarification_proposal(decision, slots=slots)
        if family in {"watch_runtime", "browser_destination", "workspace_operations", "context_clarification"}:
            browser_context = self._browser_context_request(message, lower, active_context=active_context)
            if browser_context is not None:
                return self._merge_route_spine_proposal(
                    self._tool_proposal(
                        query_shape=QueryShape.BROWSER_CONTEXT,
                        domain="browser",
                        tool_name="browser_context",
                        tool_arguments=browser_context,
                        request_type_hint="browser_context",
                        family="watch_runtime",
                        subject=str(browser_context.get("operation") or "browser_context"),
                        requested_action=str(browser_context.get("operation") or "browser_context"),
                        confidence=decision.winner.score or 0.95,
                        evidence=["browser-context phrase detected"],
                        execution_type="inspect_browser_context",
                        output_mode=ResponseMode.ACTION_RESULT.value,
                    ),
                    slots=slots,
                    evidence_note="route_spine preserved browser/runtime ownership while restoring browser-context follow-through",
                )
        if family in {"file", "context_clarification"}:
            active_item_follow_up = self._active_item_follow_up_semantic_proposal(
                message,
                surface_mode=surface_mode,
                workspace_context=workspace_context,
                active_posture=active_posture,
            )
            if active_item_follow_up is not None:
                return self._merge_route_spine_proposal(
                    active_item_follow_up,
                    slots=slots,
                    evidence_note="route_spine preserved file ownership while restoring active-item follow-up binding",
                )
        if family == "discord_relay":
            relay_proposal = self._discord_relay_request(
                message,
                lower,
                active_request_state=active_request_state,
                active_context=active_context,
            )
            if relay_proposal is not None:
                return self._merge_route_spine_proposal(
                    relay_proposal,
                    slots=slots,
                    evidence_note="route_spine preserved discord relay ownership while restoring relay binding contract",
                )
        if family in {"browser_destination", "file", "context_clarification"}:
            deictic_open = self._deictic_open_request(
                message,
                lower,
                surface_mode=surface_mode,
                active_context=active_context,
            )
            if deictic_open is not None:
                return self._merge_route_spine_proposal(
                    deictic_open,
                    slots=slots,
                    evidence_note="route_spine preserved native open ownership while restoring deictic binding contract",
                )
            browser_destination = self._browser_destination_request(
                message,
                lower,
                surface_mode=surface_mode,
            )
            if browser_destination is not None:
                return self._merge_route_spine_proposal(
                    browser_destination,
                    slots=slots,
                    evidence_note="route_spine preserved browser ownership while restoring destination resolution contract",
                )
        if family in {"context_action", "context_clarification"}:
            context_action = self._context_action_request(message, lower, active_context=active_context)
            if context_action is not None:
                clarification_payload = (
                    context_action.get("clarification")
                    if isinstance(context_action.get("clarification"), dict)
                    else {}
                )
                if clarification_payload:
                    return self._merge_route_spine_proposal(
                        self._tool_proposal(
                            query_shape=QueryShape.CONTEXT_ACTION,
                            domain="context",
                            request_type_hint="context_action",
                            family="context_action",
                            subject=str(context_action.get("operation") or "context_action"),
                            requested_action=str(context_action.get("operation") or "context_action"),
                            confidence=0.86,
                            evidence=["context-action phrasing detected but active context was missing"],
                            execution_type="execute_context_action",
                            output_mode=ResponseMode.CLARIFICATION.value,
                            slots={
                                "clarification": clarification_payload,
                                "missing_preconditions": list(
                                    clarification_payload.get("missing_slots") or ["context"]
                                ),
                                "target_scope": "context",
                            },
                        ),
                        slots=slots,
                        evidence_note="route_spine preserved context-action ownership while restoring bounded clarification semantics",
                    )
                return self._merge_route_spine_proposal(
                    self._tool_proposal(
                        query_shape=QueryShape.CONTEXT_ACTION,
                        domain="context",
                        tool_name="context_action",
                        tool_arguments=context_action,
                        request_type_hint="context_action",
                        family="task_continuity"
                        if str(context_action.get("operation") or "") == "extract_tasks"
                        else "context_action",
                        subject=str(context_action.get("operation") or "context_action"),
                        requested_action=str(context_action.get("operation") or "context_action"),
                        confidence=0.94,
                        evidence=["context-action phrasing detected"],
                        execution_type="execute_context_action",
                        output_mode=ResponseMode.ACTION_RESULT.value,
                    ),
                    slots=slots,
                    evidence_note="route_spine preserved context-action ownership while restoring deterministic context binding",
                )
        if family == "system_control":
            if self._looks_like_open_location_settings(lower):
                return self._merge_route_spine_proposal(
                    self._tool_proposal(
                        query_shape=QueryShape.CONTROL_COMMAND,
                        domain="location",
                        tool_name="external_open_url",
                        tool_arguments={"url": "ms-settings:privacy-location"},
                        request_type_hint="direct_action",
                        family="location",
                        subject="open_settings",
                        requested_action="open_location_settings",
                        confidence=decision.winner.score or 0.95,
                        evidence=["open location settings phrase detected"],
                        execution_type="execute_control_command",
                        output_mode=ResponseMode.ACTION_RESULT.value,
                    ),
                    slots=slots,
                    evidence_note="route_spine preserved system-control ownership while restoring location-settings URI semantics",
                )
            system_request = self._system_control_request(message, lower) or {
                "action": "open_settings_page",
                "target": decision.intent_frame.target_text or "settings",
                "dry_run": True,
            }
            return self._merge_route_spine_proposal(
                self._tool_proposal(
                    query_shape=QueryShape.CONTROL_COMMAND,
                    domain="system",
                    tool_name="system_control",
                    tool_arguments=system_request,
                    request_type_hint="direct_action",
                    family="system_control",
                    subject=str(system_request.get("target") or system_request.get("action") or "system_control"),
                    requested_action=str(system_request.get("action") or "system_control"),
                    confidence=decision.winner.score or 0.92,
                    evidence=["system-control phrasing matched a deterministic control request"],
                    execution_type="execute_control_command",
                    output_mode=ResponseMode.ACTION_RESULT.value,
                    output_type="action",
                ),
                slots=slots,
                evidence_note="route_spine preserved system-control ownership over app/search fallback",
            )
        if family in {"app_control", "workflow", "software_control", "context_clarification"}:
            window_request = self._window_control_request(message, lower)
            if window_request is not None:
                return self._merge_route_spine_proposal(
                    self._tool_proposal(
                        query_shape=QueryShape.CONTROL_COMMAND,
                        domain="system",
                        tool_name="window_control",
                        tool_arguments=window_request,
                        request_type_hint="direct_action",
                        family="window_control",
                        subject=str(window_request.get("action") or "window_control"),
                        requested_action=str(window_request.get("action") or "window_control"),
                        confidence=decision.winner.score or 0.92,
                        evidence=["window-control phrasing matched a deterministic control request"],
                        execution_type="execute_control_command",
                        output_mode=ResponseMode.ACTION_RESULT.value,
                        output_type="action",
                    ),
                    slots=slots,
                    evidence_note="route_spine restored deictic window-control ownership from the deterministic control contract",
                )
            app_request = self._app_control_request(message, lower) if family != "software_control" else None
            if app_request is not None:
                return self._merge_route_spine_proposal(
                    self._tool_proposal(
                        query_shape=QueryShape.CONTROL_COMMAND,
                        domain="system",
                        tool_name="app_control",
                        tool_arguments=app_request,
                        request_type_hint="direct_action",
                        family="app_control",
                        subject=str(app_request.get("app_name") or "app"),
                        requested_action=str(app_request.get("action") or "launch"),
                        confidence=decision.winner.score or 0.92,
                        evidence=["app-control phrasing matched a deterministic control request"],
                        execution_type="execute_control_command",
                        output_mode=ResponseMode.ACTION_RESULT.value,
                        output_type="action",
                    ),
                    slots=slots,
                    evidence_note="route_spine preserved app-control ownership while restoring action normalization",
                )
            system_request = self._system_control_request(message, lower)
            if system_request is not None:
                return self._merge_route_spine_proposal(
                    self._tool_proposal(
                        query_shape=QueryShape.CONTROL_COMMAND,
                        domain="system",
                        tool_name="system_control",
                        tool_arguments=system_request,
                        request_type_hint="direct_action",
                        family="system_control",
                        subject=str(system_request.get("action") or "system_control"),
                        requested_action=str(system_request.get("action") or "system_control"),
                        confidence=decision.winner.score or 0.92,
                        evidence=["system-control phrasing matched a deterministic control request"],
                        execution_type="execute_control_command",
                        output_mode=ResponseMode.ACTION_RESULT.value,
                        output_type="action",
                    ),
                    slots=slots,
                    evidence_note="route_spine restored deterministic system-control shaping",
                )
        if family in {"desktop_search", "file", "context_clarification"}:
            source_case = str(decision.intent_frame.extracted_entities.get("source_case") or "").strip().lower()
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip().lower()
            if family == "desktop_search" and (source_case == "recent_files" or requested_tool == "recent_files"):
                return self._merge_route_spine_proposal(
                    self._tool_proposal(
                        query_shape=QueryShape.CURRENT_STATUS,
                        domain="files",
                        tool_name="recent_files",
                        tool_arguments={},
                        request_type_hint="direct_deterministic_fact",
                        family="desktop_search",
                        subject="recent_files",
                        requested_metric="recent_files",
                        confidence=decision.winner.score or 0.92,
                        evidence=["desktop-search recent-files phrasing matched native recent-files status"],
                        execution_type="retrieve_current_status",
                        output_mode=ResponseMode.STATUS_SUMMARY.value,
                    ),
                    slots=slots,
                    evidence_note="route_spine preserved desktop-search ownership while restoring recent-files status contract",
                )
            search_request = self._desktop_search_request(message, lower, surface_mode=surface_mode)
            if search_request is not None:
                return self._merge_route_spine_proposal(
                    self._tool_proposal(
                        query_shape=QueryShape.SEARCH_AND_OPEN,
                        domain="workflow",
                        tool_name="desktop_search",
                        tool_arguments=search_request,
                        request_type_hint="search_and_act",
                        family="desktop_search",
                        subject=str(search_request.get("query") or "desktop_search"),
                        requested_action=str(search_request.get("action") or "search"),
                        confidence=decision.winner.score or 0.92,
                        evidence=["desktop-search phrasing matched a deterministic search-and-open request"],
                        execution_type="search_then_open",
                        output_mode=ResponseMode.SEARCH_RESULT.value,
                    ),
                    slots=slots,
                    evidence_note="route_spine preserved desktop-search ownership while restoring search-and-open contract",
                )
        if family == "context_clarification" and self._looks_like_resource_diagnosis(lower):
            return self._merge_route_spine_proposal(
                self._tool_proposal(
                    query_shape=QueryShape.DIAGNOSTIC_CAUSAL,
                    domain="system",
                    tool_name="resource_diagnosis",
                    tool_arguments={},
                    request_type_hint="deterministic_diagnostic_request",
                    family="resources",
                    subject="resources",
                    requested_metric="bottleneck",
                    diagnostic_mode=True,
                    confidence=0.95,
                    evidence=["machine slowdown diagnosis phrasing detected"],
                    execution_type="diagnose_from_telemetry",
                    output_mode=ResponseMode.DIAGNOSTIC_SUMMARY.value,
                ),
                slots=slots,
                evidence_note="route_spine preserved deterministic resource diagnosis ownership for concrete slowdown phrasing",
            )
        if family == "unsupported":
            intent_frame = slots.get("route_spine", {}).get("intent_frame", {}) if isinstance(slots.get("route_spine"), dict) else {}
            unsupported_browser_automation = str(intent_frame.get("target_type") or "").strip().lower() == "browser_automation"
            unsupported_browser_reason = str(intent_frame.get("target_text") or "").strip().lower()
            subject = "unsupported_browser_automation" if unsupported_browser_automation else "external_commitment"
            requested_action = (
                "decline_unsupported_browser_automation"
                if unsupported_browser_automation
                else "decline_unsupported_external_commitment"
            )
            evidence = (
                ["route_spine selected unsupported browser automation guard"]
                if unsupported_browser_automation
                else ["route_spine selected unsupported external commitment guard"]
            )
            assistant_message = (
                self._unsupported_browser_automation_message(unsupported_browser_reason)
                if unsupported_browser_automation
                else (
                    "I can't book, purchase, pay for, or commit to real-world transactions from this command surface. "
                    "I can help you draft a plan or checklist instead."
                )
            )
            return self._tool_proposal(
                query_shape=QueryShape.SUMMARY_REQUEST,
                domain="unsupported",
                request_type_hint="unsupported_capability",
                family="unsupported",
                subject=subject,
                requested_action=requested_action,
                confidence=decision.winner.score or 0.96,
                evidence=evidence,
                assistant_message=assistant_message,
                execution_type="decline_unsupported_request",
                output_mode=ResponseMode.UNSUPPORTED.value,
                slots=slots,
            )
        if family == "routine":
            routine_save = self._routine_save_request(
                message,
                lower,
                active_request_state=active_request_state,
                active_context=active_context,
                active_posture=active_posture,
            )
            if routine_save is not None:
                precondition_state = (
                    routine_save.get("routine_save_precondition_state")
                    if isinstance(routine_save.get("routine_save_precondition_state"), dict)
                    else {}
                )
                missing_preconditions = list(precondition_state.get("missing_preconditions") or [])
                if missing_preconditions:
                    slots.update(
                        {
                            "routine_save_precondition_state": precondition_state,
                            "routine_name": routine_save.get("routine_name"),
                            "missing_evidence": list(missing_preconditions),
                            "clarification": {
                                "code": "missing_routine_context",
                                "message": (
                                    "I can save that as a routine, but I need the steps or the recent action you want me to reuse. "
                                    "Send the workflow steps, or run the action first and then ask me to save it."
                                ),
                                "missing_slots": list(missing_preconditions),
                            },
                        }
                    )
                    return self._tool_proposal(
                        query_shape=QueryShape.ROUTINE_REQUEST,
                        domain="workflow",
                        request_type_hint="routine_save_preflight",
                        family="routine",
                        subject="save",
                        requested_action="save_routine",
                        confidence=decision.winner.score or 0.95,
                        evidence=["route_spine selected routine-save intent but preconditions require clarification"],
                        assistant_message=str(slots["clarification"]["message"]),
                        execution_type="save_routine_preflight",
                        output_mode=ResponseMode.CLARIFICATION.value,
                        slots=slots,
                    )
                return self._tool_proposal(
                    query_shape=QueryShape.ROUTINE_REQUEST,
                    domain="workflow",
                    tool_name="routine_save",
                    tool_arguments=routine_save,
                    request_type_hint="routine_save",
                    family="routine",
                    subject="save",
                    requested_action="save_routine",
                    confidence=decision.winner.score or 0.95,
                    evidence=["route_spine selected routine-save intent with bounded active context"],
                    execution_type="save_routine",
                        output_mode=ResponseMode.ACTION_RESULT.value,
                        slots=slots,
                    )
            if decision.clarification_needed:
                return self._route_spine_clarification_proposal(decision, slots=slots)
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip()
            if requested_tool == "routine_save":
                routine_name = str(
                    decision.intent_frame.target_text or active_request_state.get("subject") or "saved routine"
                ).strip() or "saved routine"
                precondition_state = self._routine_save_precondition_state(
                    active_request_state=active_request_state,
                    active_context=active_context,
                    active_posture=active_posture,
                )
                missing_preconditions = list(precondition_state.get("missing_preconditions") or [])
                if missing_preconditions:
                    slots.update(
                        {
                            "routine_save_precondition_state": precondition_state,
                            "routine_name": routine_name,
                            "missing_evidence": list(missing_preconditions),
                            "clarification": {
                                "code": "missing_routine_context",
                                "message": (
                                    "I can save that as a routine, but I need the steps or the recent action you want me to reuse. "
                                    "Send the workflow steps, or run the action first and then ask me to save it."
                                ),
                                "missing_slots": list(missing_preconditions),
                            },
                        }
                    )
                    return self._tool_proposal(
                        query_shape=QueryShape.ROUTINE_REQUEST,
                        domain="workflow",
                        request_type_hint="routine_save_preflight",
                        family="routine",
                        subject="save",
                        requested_action="save_routine",
                        confidence=decision.winner.score or 0.95,
                        evidence=["planner_v2 preserved pending routine-save preview but preconditions require clarification"],
                        assistant_message=str(slots["clarification"]["message"]),
                        execution_type="save_routine_preflight",
                        output_mode=ResponseMode.CLARIFICATION.value,
                        slots=slots,
                    )
                active_family = str(active_request_state.get("family") or "").strip().lower()
                parameters = (
                    active_request_state.get("parameters")
                    if isinstance(active_request_state.get("parameters"), dict)
                    else {}
                )
                routine_args = {
                    "routine_name": routine_name,
                    "execution_kind": active_family,
                    "parameters": dict(parameters),
                    "description": f"Saved {active_family or 'active'} routine for {routine_name}.",
                    "routine_save_precondition_state": precondition_state,
                }
                return self._tool_proposal(
                    query_shape=QueryShape.ROUTINE_REQUEST,
                    domain="workflow",
                    tool_name="routine_save",
                    tool_arguments=routine_args,
                    request_type_hint="routine_save",
                    family="routine",
                    subject="save",
                    requested_action="save_routine",
                    confidence=decision.winner.score or 0.95,
                    evidence=["planner_v2 preserved pending routine-save preview through typed routine contract"],
                    execution_type="save_routine",
                    output_mode=ResponseMode.ACTION_RESULT.value,
                    output_type="action",
                    slots=slots,
                )
            trusted_hook_register = self._trusted_hook_register_request(message, lower)
            if trusted_hook_register is not None or requested_tool == "trusted_hook_register":
                hook_args = trusted_hook_register or {
                    "hook_name": str(
                        decision.intent_frame.extracted_entities.get("hook_name")
                        or decision.intent_frame.target_text
                        or "trusted hook"
                    ).strip(),
                    "path": str(decision.intent_frame.extracted_entities.get("path") or "").strip(),
                    "query": message,
                    "dry_run": True,
                }
                return self._tool_proposal(
                    query_shape=QueryShape.CONTROL_COMMAND,
                    domain="system",
                    tool_name="trusted_hook_register",
                    tool_arguments=hook_args,
                    request_type_hint="trusted_hook_registration",
                    family="routine",
                    subject=str(hook_args.get("hook_name") or "trusted_hook"),
                    requested_action="register_trusted_hook",
                    confidence=decision.winner.score or 0.95,
                    evidence=["planner_v2 selected trusted hook registration from routine contract"],
                    execution_type="register_trusted_hook",
                    output_mode=ResponseMode.ACTION_RESULT.value,
                    output_type="action",
                    slots=slots,
                )
            trusted_hook = self._trusted_hook_execute_request(message, lower)
            if trusted_hook is not None or requested_tool == "trusted_hook_execute":
                hook_args = trusted_hook or {
                    "hook_name": str(
                        decision.intent_frame.extracted_entities.get("hook_name")
                        or decision.intent_frame.target_text
                        or "trusted hook"
                    ).strip(),
                    "query": message,
                    "dry_run": True,
                }
                return self._tool_proposal(
                    query_shape=QueryShape.CONTROL_COMMAND,
                    domain="system",
                    tool_name="trusted_hook_execute",
                    tool_arguments=hook_args,
                    request_type_hint="trusted_hook_execution",
                    family="routine",
                    subject=str(hook_args.get("hook_name") or "trusted_hook"),
                    requested_action="execute_trusted_hook",
                    confidence=decision.winner.score or 0.95,
                    evidence=["planner_v2 selected trusted hook execution from routine contract"],
                    execution_type="execute_control_command",
                    output_mode=ResponseMode.ACTION_RESULT.value,
                    output_type="action",
                    slots=slots,
                )
            routine_execute = self._routine_execute_request(message, lower) or {}
            routine_name = str(
                routine_execute.get("routine_name")
                or decision.intent_frame.target_text
                or decision.intent_frame.extracted_entities.get("routine")
                or "routine"
            ).strip()
            slots.update({"routine_name": routine_name, "request_stage": "dry_run"})
            return self._tool_proposal(
                query_shape=QueryShape.ROUTINE_REQUEST,
                domain="workflow",
                tool_name="routine_execute",
                tool_arguments={"routine_name": routine_name, "query": message, "dry_run": True},
                request_type_hint="routine_execution",
                family="routine",
                subject=routine_name,
                requested_action="execute_routine",
                confidence=decision.winner.score or 0.9,
                evidence=["planner_v2 selected routine execution from typed routine contract"],
                execution_type="execute_routine",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots=slots,
            )
        if decision.clarification_needed and family not in {"task_continuity", "calculations"}:
            return self._route_spine_clarification_proposal(decision, slots=slots)
        if family == "discord_relay":
            destination_alias = str(decision.intent_frame.target_text or "").strip() or "discord"
            slots.update(
                {
                    "destination_alias": destination_alias,
                    "payload_hint": "contextual",
                    "request_stage": "preview",
                    "planner_v2_policy": "preview_required_before_live_send",
                }
            )
            return self._tool_proposal(
                query_shape=QueryShape.DISCORD_RELAY_REQUEST,
                domain="discord_relay",
                request_type_hint="discord_relay_dispatch",
                family="discord_relay",
                subject=destination_alias,
                requested_action="preview",
                confidence=decision.winner.score or 0.9,
                evidence=["planner_v2 selected discord_relay with bounded preview-only policy"],
                execution_type="discord_relay_preview",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots=slots,
            )
        if family == "calculations":
            calc_payload = (
                calculation_evaluation.to_dict()
                if calculation_evaluation is not None and hasattr(calculation_evaluation, "to_dict")
                else {}
            )
            requested_mode = str(calc_payload.get("requested_mode") or "")
            helper_request = str(calc_payload.get("disposition") or "") == CalculationRouteDisposition.HELPER_REQUEST.value
            verification_request = str(calc_payload.get("disposition") or "") == CalculationRouteDisposition.VERIFICATION_REQUEST.value
            slots.update(
                {
                    "calculation_request": calc_payload
                    or {
                        "candidate": True,
                        "follow_up_reuse": True,
                        "raw_text": message,
                        "intent_frame": decision.intent_frame.to_dict(),
                    },
                    "requested_mode": requested_mode,
                }
            )
            return self._tool_proposal(
                query_shape=QueryShape.CALCULATION_REQUEST,
                domain="calculations",
                request_type_hint="calculation_response",
                family="calculations",
                subject=str(calc_payload.get("helper_name") or ("verification" if verification_request else "expression")),
                requested_action="verify_expression"
                if verification_request
                else "evaluate_helper"
                if helper_request
                else "evaluate_expression",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected calculations from IntentFrame and RouteFamilySpec"],
                execution_type="calculation_evaluate",
                output_mode=ResponseMode.CALCULATION_RESULT.value,
                output_type="numeric",
                slots=slots,
            )
        if family == "software_control":
            software_payload = (
                software_control_evaluation.to_dict()
                if software_control_evaluation is not None and hasattr(software_control_evaluation, "to_dict")
                else {}
            )
            operation_type = str(software_payload.get("operation_type") or decision.intent_frame.operation or "software_control")
            target_name = str(software_payload.get("target_name") or decision.intent_frame.target_text or "software").strip()
            slots.update(
                {
                    "software_control_request": software_payload,
                    "operation_type": operation_type,
                    "target_name": target_name,
                    "request_stage": software_payload.get("request_stage") or "plan",
                    "follow_up_reuse": bool(software_payload.get("follow_up_reuse", False)),
                    "approval_scope": software_payload.get("approval_scope"),
                    "approval_outcome": software_payload.get("approval_outcome"),
                    "trust_request_id": software_payload.get("trust_request_id"),
                }
            )
            return self._tool_proposal(
                query_shape=QueryShape.SOFTWARE_CONTROL_REQUEST,
                domain="software_control",
                request_type_hint="software_control_response",
                family="software_control",
                subject=target_name,
                requested_action=operation_type,
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected software_control from operation/risk contract"],
                execution_type="software_control_execute",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots=slots,
            )
        if family == "browser_destination":
            url = self._route_spine_selected_value(decision) or str(decision.intent_frame.extracted_entities.get("url") or "")
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip()
            tool_name = (
                requested_tool
                if requested_tool in {"deck_open_url", "external_open_url"}
                else "deck_open_url"
                if surface_mode.strip().lower() == "deck"
                or re.search(r"\b(?:in|inside|within)\s+(?:the\s+)?deck\b", decision.intent_frame.normalized_text)
                else "external_open_url"
            )
            return self._tool_proposal(
                query_shape=QueryShape.OPEN_BROWSER_DESTINATION,
                domain="browser",
                tool_name=tool_name,
                tool_arguments={"url": url or decision.intent_frame.target_text},
                request_type_hint="direct_action",
                family="browser_destination",
                subject=decision.intent_frame.target_text or "browser_destination",
                requested_action="open_browser_destination",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected browser_destination from URL/website contract"],
                execution_type="resolve_url_then_open_in_browser",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots=slots,
            )
        if family == "file":
            path = self._route_spine_selected_value(decision) or str(decision.intent_frame.extracted_entities.get("path") or decision.intent_frame.target_text)
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip()
            tool_name = (
                requested_tool
                if requested_tool in {"file_reader", "deck_open_file", "external_open_file"}
                else "file_reader"
                if decision.intent_frame.operation == "inspect"
                else "deck_open_file"
                if surface_mode.strip().lower() == "deck"
                or re.search(r"\b(?:in|inside|within)\s+(?:the\s+)?deck\b", decision.intent_frame.normalized_text)
                else "external_open_file"
            )
            return self._tool_proposal(
                query_shape=QueryShape.CONTEXT_ACTION,
                domain="files",
                tool_name=tool_name,
                tool_arguments={"path": path},
                request_type_hint="file_read" if tool_name == "file_reader" else "direct_action",
                family="file",
                subject=path or "file",
                requested_action="read_file" if tool_name == "file_reader" else "open_file",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected file from typed file target"],
                execution_type="read_file" if tool_name == "file_reader" else "execute_control_command",
                output_mode=ResponseMode.SUMMARY_RESULT.value if tool_name == "file_reader" else ResponseMode.ACTION_RESULT.value,
                output_type="file" if tool_name == "file_reader" else "action",
                slots=slots,
            )
        if family == "task_continuity":
            source_case = str(decision.intent_frame.extracted_entities.get("source_case") or "").strip().lower()
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip()
            if requested_tool == "workspace_where_left_off" or source_case == "workspace_where_left_off" or self._looks_like_where_left_off(lower):
                tool_name = "workspace_where_left_off"
                requested_action = "where_left_off"
                request_type_hint = "workspace_restore"
            else:
                tool_name = "workspace_next_steps"
                requested_action = "next_steps"
                request_type_hint = "direct_deterministic_fact"
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name=tool_name,
                tool_arguments={},
                request_type_hint=request_type_hint,
                family="task_continuity",
                subject=requested_action,
                requested_action=requested_action,
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected task continuity from workspace-context contract"],
                execution_type="summarize_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
                slots=slots,
            )
        if family == "context_action":
            operation = "extract_tasks" if "task" in decision.intent_frame.normalized_text else "inspect"
            return self._tool_proposal(
                query_shape=QueryShape.CONTEXT_ACTION,
                domain="context",
                tool_name="context_action",
                tool_arguments={"operation": operation, "source": "selection"},
                request_type_hint="context_action",
                family=family,
                subject=operation,
                requested_action=operation,
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected context target handling"],
                execution_type="execute_context_action",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots=slots,
            )
        if family == "comparison":
            comparison_target = re.sub(r"^(?:compare|diff)\s+", "", lower, flags=re.IGNORECASE).strip(" .")
            return self._tool_proposal(
                query_shape=QueryShape.COMPARISON_REQUEST,
                domain="files",
                request_type_hint="comparison_request",
                family="comparison",
                subject="files",
                requested_action="compare",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected comparison because concrete file/context targets were present"],
                execution_type="compare_items",
                output_mode=ResponseMode.SUMMARY_RESULT.value,
                slots={**slots, "comparison_target": comparison_target},
            )
        if family == "screen_awareness":
            return self._tool_proposal(
                query_shape=QueryShape.SCREEN_AWARENESS_REQUEST,
                domain="screen_awareness",
                request_type_hint="screen_awareness_response",
                family="screen_awareness",
                subject="visible_screen",
                requested_action="ground_screen_action",
                confidence=decision.winner.score or 0.88,
                evidence=["route_spine selected screen_awareness but requires grounding"],
                assistant_message=decision.clarification_text,
                execution_type="screen_awareness_act",
                output_mode=ResponseMode.CLARIFICATION.value,
                output_type="screen_action",
                slots={
                    **slots,
                    "clarification": {
                        "code": "missing_screen_awareness_context",
                        "message": decision.clarification_text,
                        "missing_slots": list(decision.missing_preconditions or ("visible_screen",)),
                    },
                    "missing_preconditions": list(decision.missing_preconditions or ("visible_screen",)),
                },
            )
        if family == "app_control":
            if decision.intent_frame.operation == "status" or "active_apps" in decision.tool_candidates:
                return self._tool_proposal(
                    query_shape=QueryShape.CURRENT_STATUS,
                    domain="system",
                    tool_name="active_apps",
                    tool_arguments={"focus": "applications"},
                    request_type_hint="direct_deterministic_fact",
                    family="app_control",
                    subject="active_apps",
                    requested_metric="applications",
                    confidence=decision.winner.score or 0.9,
                    evidence=["route_spine selected app_control status from active-app contract"],
                    execution_type="retrieve_current_status",
                    output_mode=ResponseMode.STATUS_SUMMARY.value,
                    slots=slots,
                )
            action = "close" if decision.intent_frame.operation in {"quit", "close"} else "open"
            return self._tool_proposal(
                query_shape=QueryShape.CONTROL_COMMAND,
                domain="system",
                tool_name="app_control",
                tool_arguments={"action": action, "target": decision.intent_frame.target_text},
                request_type_hint="direct_action",
                family="app_control",
                subject=decision.intent_frame.target_text or "app",
                requested_action=action,
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected app_control from app operation contract"],
                execution_type="execute_control_command",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots=slots,
            )
        if family in {"watch_runtime", "network", "machine", "power", "resources", "window_control"}:
            return self._route_spine_status_proposal(decision, slots=slots)
        if family == "file_operation":
            file_operation = self._file_operation_request(message, lower)
            return self._tool_proposal(
                query_shape=QueryShape.FILE_OPERATION,
                domain="files",
                tool_name="file_operation",
                tool_arguments=file_operation
                or {
                    "operation": decision.intent_frame.operation,
                    "target": decision.intent_frame.target_text,
                    "dry_run": True,
                },
                request_type_hint="file_operation",
                family="file_operation",
                subject=str((file_operation or {}).get("operation") or "file_operation"),
                requested_action="file_operation",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected file_operation from typed file-operation contract"],
                execution_type="execute_file_operation",
                output_mode=ResponseMode.ACTION_RESULT.value,
                slots=slots,
            )
        if family == "workspace_operations":
            source_case = str(decision.intent_frame.extracted_entities.get("source_case") or "").strip().lower()
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip()
            if requested_tool.startswith("workspace_") and requested_tool != "workspace_assemble":
                tool_name = requested_tool
                requested_action = tool_name.removeprefix("workspace_")
                request_type_hint = "workspace_restore" if tool_name == "workspace_restore" else "direct_action"
            elif source_case == "workspace_restore":
                tool_name = "workspace_restore"
                requested_action = "restore"
                request_type_hint = "workspace_restore"
            elif self._looks_like_workspace_restore(lower):
                tool_name = "workspace_restore"
                requested_action = "restore"
                request_type_hint = "workspace_restore"
            elif self._looks_like_workspace_archive(lower):
                tool_name = "workspace_archive"
                requested_action = "archive"
                request_type_hint = "direct_action"
            elif self._looks_like_workspace_save(lower):
                tool_name = "workspace_save"
                requested_action = "save"
                request_type_hint = "direct_action"
            elif self._looks_like_workspace_clear(lower):
                tool_name = "workspace_clear"
                requested_action = "clear"
                request_type_hint = "direct_action"
            elif self._looks_like_workspace_rename(lower):
                tool_name = "workspace_rename"
                requested_action = "rename"
                request_type_hint = "direct_action"
            elif self._looks_like_workspace_tag(lower):
                tool_name = "workspace_tag"
                requested_action = "tag"
                request_type_hint = "direct_action"
            elif self._looks_like_workspace_list(lower):
                tool_name = "workspace_list"
                requested_action = "list"
                request_type_hint = "direct_deterministic_fact"
            elif requested_tool == "workspace_assemble" or self._looks_like_workspace_assemble(lower):
                tool_name = "workspace_assemble"
                requested_action = "assemble"
                request_type_hint = "workspace_assembly"
            else:
                tool_name = "workspace_assemble"
                requested_action = "assemble"
                request_type_hint = "workspace_assembly"
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name=tool_name,
                tool_arguments=(
                    {"query": message}
                    if tool_name in {"workspace_restore", "workspace_assemble", "workspace_archive"}
                    else {
                        "new_name": str(
                            decision.intent_frame.extracted_entities.get("new_name")
                            or self._extract_after_phrase(message, "to")
                        ).strip()
                    }
                    if tool_name == "workspace_rename"
                    else {
                        "tags": (
                            list(decision.intent_frame.extracted_entities.get("tags"))
                            if isinstance(decision.intent_frame.extracted_entities.get("tags"), list)
                            else self._extract_tags(message)
                        )
                    }
                    if tool_name == "workspace_tag"
                    else {}
                ),
                request_type_hint=request_type_hint,
                family="workspace_operations",
                subject=requested_action,
                requested_action=requested_action,
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected workspace_operations from RouteFamilySpec"],
                execution_type=f"{requested_action}_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
                slots=slots,
            )
        if family == "workflow":
            workflow_request = self._workflow_execution_request(message, lower) or {
                "workflow_kind": decision.intent_frame.target_text or "workflow",
                "query": message,
            }
            return self._tool_proposal(
                query_shape=QueryShape.WORKFLOW_REQUEST,
                domain="workflow",
                tool_name="workflow_execute",
                tool_arguments=workflow_request,
                request_type_hint="workflow_execution",
                family="workflow",
                subject=str(workflow_request.get("workflow_kind") or "workflow"),
                requested_action="execute_workflow",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected workflow from RouteFamilySpec"],
                execution_type="execute_workflow",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots=slots,
            )
        if family == "maintenance":
            maintenance_request = self._maintenance_action_request(message, lower) or {
                "maintenance_kind": "bounded_maintenance_plan",
                "query": message,
                "dry_run": True,
            }
            return self._tool_proposal(
                query_shape=QueryShape.MAINTENANCE_REQUEST,
                domain="files",
                tool_name="maintenance_action",
                tool_arguments=maintenance_request,
                request_type_hint="maintenance_execution",
                family="maintenance",
                subject=str(maintenance_request.get("maintenance_kind") or "maintenance"),
                requested_action="execute_maintenance",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected maintenance from RouteFamilySpec"],
                execution_type="execute_maintenance",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots=slots,
            )
        if family == "desktop_search":
            source_case = str(decision.intent_frame.extracted_entities.get("source_case") or "").strip().lower()
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip().lower()
            if source_case == "recent_files" or requested_tool == "recent_files":
                return self._tool_proposal(
                    query_shape=QueryShape.CURRENT_STATUS,
                    domain="files",
                    tool_name="recent_files",
                    tool_arguments={},
                    request_type_hint="direct_deterministic_fact",
                    family="desktop_search",
                    subject="recent_files",
                    requested_metric="recent_files",
                    confidence=decision.winner.score or 0.9,
                    evidence=["route_spine selected desktop_search recent-files status contract"],
                    execution_type="retrieve_current_status",
                    output_mode=ResponseMode.STATUS_SUMMARY.value,
                    slots=slots,
                )
            search_request = self._desktop_search_request(message, lower, surface_mode=surface_mode) or {
                "query": decision.intent_frame.target_text or message,
                "domains": ["files"],
                "action": "search",
                "open_target": "deck" if surface_mode.strip().lower() == "deck" else "external",
                "latest_only": False,
                "file_extensions": [],
                "folder_hint": None,
                "prefer_folders": False,
            }
            return self._tool_proposal(
                query_shape=QueryShape.SEARCH_AND_OPEN,
                domain="workflow",
                tool_name="desktop_search",
                tool_arguments=search_request,
                request_type_hint="search_and_act",
                family="desktop_search",
                subject=str(search_request.get("query") or "desktop_search"),
                requested_action=str(search_request.get("action") or "search"),
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected desktop_search from local file/search contract"],
                execution_type="search_then_open",
                output_mode=ResponseMode.SEARCH_RESULT.value,
                slots=slots,
            )
        if family == "trust_approvals":
            trust_approval = self._trust_approval_request(lower, active_request_state=active_request_state)
            if trust_approval is not None:
                trust_approval.slots.update(slots)
                return trust_approval
            return self._tool_proposal(
                query_shape=QueryShape.TRUST_APPROVAL_REQUEST,
                domain="trust",
                request_type_hint="trust_approval_explanation",
                family="trust_approvals",
                subject="approval",
                requested_action="explain_approval",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected trust_approvals from approval/permission contract"],
                assistant_message="I can explain or inspect an approval request, but I need the active approval context for a specific allow or deny decision.",
                execution_type="explain_approval",
                output_mode=ResponseMode.SUMMARY_RESULT.value,
                output_type="trust",
                slots=slots,
            )
        if family == "terminal":
            shell_command = str(decision.intent_frame.extracted_entities.get("shell_command") or decision.intent_frame.target_text or "open_terminal").strip()
            return self._tool_proposal(
                query_shape=QueryShape.CONTROL_COMMAND,
                domain="terminal",
                tool_name="shell_command",
                tool_arguments={"command": shell_command, "target": decision.intent_frame.target_text, "dry_run": True},
                request_type_hint="terminal_preflight",
                family="terminal",
                subject=decision.intent_frame.target_text or "terminal",
                requested_action="shell_command_preflight",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected terminal from terminal/folder contract"],
                execution_type="execute_control_command",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots=slots,
            )
        if family == "software_recovery":
            repair_request = self._repair_action_request(message, lower) or {
                "repair_kind": "software_recovery",
                "target": decision.intent_frame.target_text or "system",
                "dry_run": True,
            }
            return self._tool_proposal(
                query_shape=QueryShape.REPAIR_REQUEST,
                domain="software_recovery",
                tool_name="repair_action",
                tool_arguments=repair_request,
                request_type_hint="repair_execution",
                family="software_recovery",
                subject=str(repair_request.get("target") or repair_request.get("repair_kind") or "repair"),
                requested_action=str(repair_request.get("repair_kind") or "repair"),
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected software_recovery from repair/status contract"],
                execution_type="execute_repair",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots=slots,
            )
        return SemanticParseProposal(
            query_shape=QueryShape.UNCLASSIFIED,
            confidence=0.0,
            evidence=["route_spine selected a family without a planner adapter; legacy fallback refused for migrated-family pass"],
            fallback_path="route_spine_unhandled_family",
            slots=slots,
        )

    def _planner_v2_plan_draft_proposal(
        self,
        trace: Any | None,
        decision: RouteSpineDecision,
        *,
        slots: dict[str, Any],
        learned_preferences: dict[str, dict[str, object]],
    ) -> SemanticParseProposal | None:
        if trace is None or not bool(getattr(trace, "authoritative", False)):
            return None
        plan = getattr(trace, "plan_draft", None)
        if plan is None:
            return None
        family = str(getattr(plan, "route_family", "") or decision.winner.route_family).strip()
        tool_name = str(getattr(plan, "tool_name", "") or "").strip()
        frame = getattr(trace, "intent_frame", None)
        entities = getattr(frame, "extracted_entities", {}) if frame is not None else {}
        selected_context = entities.get("selected_context") if isinstance(entities, dict) else {}
        rich_route_spine_families = {
            "app_control",
            "browser_destination",
            "calculations",
            "context_action",
            "context_clarification",
            "desktop_search",
            "discord_relay",
            "file",
            "file_operation",
            "machine",
            "maintenance",
            "network",
            "power",
            "resources",
            "routine",
            "screen_awareness",
            "software_control",
            "software_recovery",
            "system_control",
            "task_continuity",
            "terminal",
            "trust_approvals",
            "watch_runtime",
            "window_control",
            "workflow",
            "workspace_operations",
        }
        if family in rich_route_spine_families:
            return None

        planner_v2_passthrough_families = {
            "development",
            "web_retrieval",
            "time",
            "storage",
            "location",
            "weather",
            "notes",
            "voice_control",
        }
        if family not in planner_v2_passthrough_families:
            return None
        if not tool_name and family != "voice_control":
            return None

        plan_args = getattr(plan, "tool_arguments", None)
        tool_arguments = dict(plan_args) if isinstance(plan_args, dict) else {}
        request_type_hint = str(getattr(plan, "request_type_hint", "") or "").strip()
        execution_type = str(getattr(plan, "execution_type", "") or "").strip()
        subsystem = str(getattr(plan, "subsystem", "") or "").strip() or decision.winner.subsystem
        subject = str(getattr(plan, "subject", "") or "").strip() or decision.intent_frame.target_text or family

        query_shape = QueryShape.SUMMARY_REQUEST
        output_mode = ResponseMode.SUMMARY_RESULT.value
        output_type = "summary"
        requested_metric: str | None = None
        requested_action: str | None = None
        domain = subsystem or family
        if tool_name == "browser_context":
            query_shape = QueryShape.BROWSER_CONTEXT
            domain = "browser"
            output_mode = ResponseMode.ACTION_RESULT.value
            output_type = "action"
            requested_action = "browser_context"
            request_type_hint = request_type_hint or "browser_context"
            execution_type = execution_type or "inspect_browser_context"
        elif family == "weather":
            lower = decision.intent_frame.normalized_text
            if self._looks_like_save_home_location(lower):
                source_mode = "current"
                context_value = selected_context.get("value") if isinstance(selected_context, dict) else {}
                parameters = (
                    context_value.get("parameters")
                    if isinstance(context_value, dict) and isinstance(context_value.get("parameters"), dict)
                    else {}
                )
                source_mode = str(parameters.get("location_mode") or parameters.get("mode") or source_mode).strip().lower() or source_mode
                return self._merge_route_spine_proposal(
                    self._tool_proposal(
                        query_shape=QueryShape.CONTROL_COMMAND,
                        domain="location",
                        tool_name="save_location",
                        tool_arguments={"target": "home", "source_mode": source_mode},
                        request_type_hint="direct_action",
                        family="location",
                        subject="save_home",
                        requested_action="save_home_location",
                        confidence=decision.winner.score or 0.95,
                        evidence=["save home location phrase detected through planner_v2 weather handoff"],
                        execution_type="execute_control_command",
                        output_mode=ResponseMode.ACTION_RESULT.value,
                    ),
                    slots=slots,
                    evidence_note="planner_v2 preserved weather context while routing the save-home follow-up to location storage",
                )
            named_location = None
            named_location_type = None
            location_reference = self._location_reference_override(lower)
            if location_reference is not None:
                named_location, named_location_type = location_reference
            preferred_open_target = str(
                self._preference_value(learned_preferences, "weather", "open_target")
                or tool_arguments.get("open_target")
                or "none"
            ).strip().lower() or "none"
            open_target = self._open_target(lower, previous="none", preferred=preferred_open_target)
            forecast_target = self._forecast_target(
                lower,
                previous=str(tool_arguments.get("forecast_target") or "current").strip().lower() or "current",
            )
            location_mode = (
                "named"
                if named_location
                else self._location_mode(
                    lower,
                        previous=str(
                            tool_arguments.get("location_mode")
                            or self._preference_value(learned_preferences, "weather", "location_mode")
                            or "auto"
                        ).strip().lower()
                        or "auto",
                )
            )
            tool_arguments = {
                "open_target": open_target,
                "location_mode": location_mode,
                "allow_home_fallback": self._allow_home_fallback(lower, previous=True),
                "forecast_target": forecast_target,
            }
            if named_location:
                tool_arguments["named_location"] = named_location
                tool_arguments["named_location_type"] = named_location_type or "saved_alias"
            query_shape = QueryShape.FORECAST_REQUEST if forecast_target != "current" else QueryShape.CURRENT_STATUS
            output_mode = ResponseMode.FORECAST_SUMMARY.value
            requested_metric = "forecast" if forecast_target != "current" else "current_conditions"
            request_type_hint = (
                "direct_action"
                if open_target != "none"
                else "deterministic_projection_request"
                if forecast_target != "current"
                else "direct_deterministic_fact"
            )
            execution_type = "retrieve_forecast" if forecast_target != "current" else "retrieve_current_status"
        elif family == "location":
            lower = decision.intent_frame.normalized_text
            named_location = None
            named_location_type = None
            location_reference = self._location_reference_override(lower)
            if location_reference is not None:
                named_location, named_location_type = location_reference
            mode = (
                "named"
                if named_location
                else self._location_mode(
                    lower,
                    previous=str(tool_arguments.get("mode") or tool_arguments.get("location_mode") or "auto").strip().lower()
                    or "auto",
                )
            )
            tool_arguments = {
                "mode": mode,
                "allow_home_fallback": self._allow_home_fallback(lower, previous=mode != "current"),
            }
            if named_location:
                tool_arguments["named_location"] = named_location
                tool_arguments["named_location_type"] = named_location_type or "saved_alias"
            query_shape = QueryShape.CURRENT_STATUS
            output_mode = ResponseMode.STATUS_SUMMARY.value
            requested_metric = "location"
            request_type_hint = "direct_deterministic_fact"
            execution_type = "retrieve_current_status"
        elif family in {"time", "storage"}:
            query_shape = QueryShape.DIAGNOSTIC_CAUSAL if "diagnosis" in tool_name else QueryShape.CURRENT_STATUS
            output_mode = ResponseMode.DIAGNOSTIC_SUMMARY.value if "diagnosis" in tool_name else ResponseMode.STATUS_SUMMARY.value
            requested_metric = str(tool_arguments.get("focus") or family)
            request_type_hint = request_type_hint or ("deterministic_diagnostic_request" if "diagnosis" in tool_name else "direct_deterministic_fact")
            execution_type = execution_type or ("diagnostic_summary" if "diagnosis" in tool_name else "retrieve_current_status")
        elif family == "development":
            query_shape = QueryShape.CONTROL_COMMAND
            output_mode = ResponseMode.ACTION_RESULT.value
            output_type = "action"
            requested_action = "echo"
            request_type_hint = request_type_hint or "direct_echo"
            execution_type = execution_type or "echo"
        elif family == "notes":
            query_shape = QueryShape.CONTROL_COMMAND
            output_mode = ResponseMode.ACTION_RESULT.value
            output_type = "action"
            requested_action = "notes_write"
            request_type_hint = request_type_hint or "notes_write"
            execution_type = execution_type or "execute_control_command"
        elif family == "voice_control":
            query_shape = QueryShape.CONTROL_COMMAND
            domain = "voice"
            output_mode = ResponseMode.ACTION_RESULT.value
            output_type = "action"
            requested_action = str(getattr(plan, "operation", "") or "voice_control")
            request_type_hint = request_type_hint or "voice_control"
            execution_type = execution_type or f"voice_control_{requested_action}"
        elif family == "browser_destination":
            query_shape = QueryShape.OPEN_BROWSER_DESTINATION
            domain = "browser"
            output_mode = ResponseMode.ACTION_RESULT.value
            output_type = "action"
            requested_action = "open"
            request_type_hint = request_type_hint or "direct_action"
            execution_type = execution_type or "resolve_url_then_open_in_browser"
        elif family == "web_retrieval":
            query_shape = QueryShape.WEB_RETRIEVAL_REQUEST
            domain = "web_retrieval"
            output_mode = ResponseMode.WEB_EVIDENCE_RESULT.value
            output_type = "web_evidence"
            requested_action = str(tool_arguments.get("intent") or "read_page")
            request_type_hint = request_type_hint or "web_retrieval_response"
            execution_type = execution_type or "web_retrieval_extract"
        elif family == "file":
            query_shape = QueryShape.CONTROL_COMMAND
            domain = "files"
            output_mode = ResponseMode.ACTION_RESULT.value
            output_type = "action"
            requested_action = "read_file" if tool_name == "file_reader" else "open"
            request_type_hint = request_type_hint or ("file_read" if tool_name == "file_reader" else "direct_action")
            execution_type = execution_type or ("read_file" if tool_name == "file_reader" else "execute_control_command")
        elif family == "workspace_operations":
            query_shape = QueryShape.WORKSPACE_REQUEST
            domain = "workspace"
            output_mode = ResponseMode.WORKSPACE_RESULT.value
            output_type = "action"
            requested_action = tool_name.removeprefix("workspace_") if tool_name.startswith("workspace_") else "workspace"
            request_type_hint = request_type_hint or "workspace_operation"
            execution_type = execution_type or f"{requested_action}_workspace"
        elif family == "routine":
            query_shape = QueryShape.ROUTINE_REQUEST
            domain = "workflow"
            output_mode = ResponseMode.ACTION_RESULT.value
            output_type = "action"
            requested_action = tool_name
            request_type_hint = request_type_hint or tool_name
            execution_type = execution_type or ("save_routine" if tool_name == "routine_save" else "execute_routine")
        elif family in {"power", "network", "resources"}:
            query_shape = QueryShape.DIAGNOSTIC_CAUSAL if "diagnosis" in tool_name else QueryShape.CURRENT_METRIC if "throughput" in tool_name else QueryShape.CURRENT_STATUS
            domain = "network" if family == "network" else "system"
            output_mode = ResponseMode.DIAGNOSTIC_SUMMARY.value if "diagnosis" in tool_name else ResponseMode.NUMERIC_METRIC.value if "throughput" in tool_name or family == "resources" else ResponseMode.STATUS_SUMMARY.value
            requested_metric = str(tool_arguments.get("focus") or family)
            request_type_hint = request_type_hint or ("deterministic_diagnostic_request" if "diagnosis" in tool_name else "direct_deterministic_fact")
            execution_type = execution_type or ("diagnostic_summary" if "diagnosis" in tool_name else "retrieve_current_status")

        return self._merge_route_spine_proposal(
            self._tool_proposal(
                query_shape=query_shape,
                domain=domain,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                request_type_hint=request_type_hint,
                family=family,
                subject=subject,
                requested_metric=requested_metric,
                requested_action=requested_action,
                confidence=decision.winner.score or 0.9,
                evidence=["planner_v2 PlanDraft selected the authoritative tool contract"],
                execution_type=execution_type,
                output_mode=output_mode,
                output_type=output_type,
            ),
            slots=slots,
            evidence_note="planner_v2 PlanDraft remained authoritative through semantic handoff",
        )

    def _route_spine_clarification_proposal(
        self,
        decision: RouteSpineDecision,
        *,
        slots: dict[str, Any],
    ) -> SemanticParseProposal:
        family = decision.winner.route_family
        shape = {
            "calculations": QueryShape.CALCULATION_REQUEST,
            "browser_destination": QueryShape.OPEN_BROWSER_DESTINATION,
            "file": QueryShape.CONTEXT_ACTION,
            "context_action": QueryShape.CONTEXT_ACTION,
            "context_clarification": QueryShape.CONTEXT_ACTION,
            "screen_awareness": QueryShape.SCREEN_AWARENESS_REQUEST,
            "camera_awareness": QueryShape.CAMERA_AWARENESS_REQUEST,
            "discord_relay": QueryShape.DISCORD_RELAY_REQUEST,
            "routine": QueryShape.ROUTINE_REQUEST,
            "trust_approvals": QueryShape.TRUST_APPROVAL_REQUEST,
            "file_operation": QueryShape.FILE_OPERATION,
            "app_control": QueryShape.CONTROL_COMMAND,
            "workspace_operations": QueryShape.WORKSPACE_REQUEST,
            "workflow": QueryShape.WORKFLOW_REQUEST,
            "maintenance": QueryShape.MAINTENANCE_REQUEST,
            "desktop_search": QueryShape.SEARCH_AND_OPEN,
            "terminal": QueryShape.CONTROL_COMMAND,
            "software_recovery": QueryShape.REPAIR_REQUEST,
        }.get(family, QueryShape.SUMMARY_REQUEST)
        domain = {
            "browser_destination": "browser",
            "file": "files",
            "context_action": "context",
            "context_clarification": "context",
            "screen_awareness": "screen_awareness",
            "camera_awareness": "camera_awareness",
            "discord_relay": "discord_relay",
            "routine": "workflow",
            "trust_approvals": "trust",
            "file_operation": "files",
            "app_control": "system",
            "workspace_operations": "workspace",
            "workflow": "workflow",
            "maintenance": "files",
            "desktop_search": "workflow",
            "terminal": "terminal",
            "software_recovery": "software_recovery",
        }.get(family, family)
        message = decision.clarification_text or "Which context should I use?"
        slots.update(
            {
                "clarification": {
                    "code": f"missing_{family}_context",
                    "message": message,
                    "missing_slots": list(decision.missing_preconditions or ("context",)),
                },
                "missing_preconditions": list(decision.missing_preconditions or ("context",)),
            }
        )
        return self._tool_proposal(
            query_shape=shape,
            domain=domain,
            request_type_hint=f"{family}_context_clarification",
            family=family,
            subject=family,
            requested_action="clarify_context",
            confidence=decision.winner.score or 0.88,
            evidence=["route_spine selected native owner with missing/stale/ambiguous context"],
            assistant_message=message,
            execution_type="clarify_route_context",
            output_mode=ResponseMode.CLARIFICATION.value,
            slots=slots,
        )

    def _route_spine_status_proposal(self, decision: RouteSpineDecision, *, slots: dict[str, Any]) -> SemanticParseProposal:
        family = decision.winner.route_family
        lower = decision.intent_frame.normalized_text
        if family == "network":
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip()
            if requested_tool == "network_throughput" or self._looks_like_network_throughput(lower):
                metric = self._network_throughput_metric(lower)
                return self._tool_proposal(
                    query_shape=QueryShape.CURRENT_METRIC,
                    domain="network",
                    tool_name="network_throughput",
                    tool_arguments={"metric": metric, "present_in": "none"},
                    request_type_hint="direct_deterministic_fact",
                    family="network",
                    subject="throughput",
                    requested_metric=metric,
                    timescale="now",
                    output_type="numeric",
                    confidence=decision.winner.score or 0.95,
                    evidence=["network throughput phrasing detected"],
                    execution_type="run_measurement",
                    output_mode=ResponseMode.NUMERIC_METRIC.value,
                    slots=slots,
                )
            if any(token in lower for token in {"unstable today", "earlier", "lately", "recently"}) and any(
                token in lower for token in {"wi-fi", "wifi", "internet", "network", "connection"}
            ) and any(token in lower for token in {"unstable", "drop", "dropped", "skipping", "choppy", "disconnect"}):
                return self._tool_proposal(
                    query_shape=QueryShape.HISTORY_TREND,
                    domain="network",
                    tool_name="network_diagnosis",
                    tool_arguments={"focus": "history", "diagnostic_burst": False},
                    request_type_hint="deterministic_diagnostic_request",
                    family="network_diagnosis",
                    subject="network_history",
                    requested_metric="stability",
                    timescale="today" if "today" in lower else "recent",
                    output_type="summary",
                    diagnostic_mode=True,
                    confidence=decision.winner.score or 0.94,
                    evidence=["network history phrasing detected"],
                    execution_type="analyze_history",
                    output_mode=ResponseMode.HISTORY_SUMMARY.value,
                    slots=slots,
                )
            if requested_tool == "network_diagnosis" or self._looks_like_network_diagnosis(lower):
                return self._tool_proposal(
                    query_shape=QueryShape.DIAGNOSTIC_CAUSAL,
                    domain="network",
                    tool_name="network_diagnosis",
                    tool_arguments={"focus": self._network_focus(lower, previous="overview"), "diagnostic_burst": True},
                    request_type_hint="deterministic_diagnostic_request",
                    family="network_diagnosis",
                    subject="network_diagnosis",
                    requested_metric="stability",
                    output_type="summary",
                    diagnostic_mode=True,
                    confidence=decision.winner.score or 0.95,
                    evidence=["network diagnosis phrasing detected"],
                    execution_type="diagnose_from_telemetry",
                    output_mode=ResponseMode.DIAGNOSTIC_SUMMARY.value,
                    slots=slots,
                )
            focus = self._network_status_focus(lower)
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="network",
                tool_name="network_status",
                tool_arguments={"focus": focus},
                request_type_hint="direct_deterministic_fact",
                family="network",
                subject="network",
                requested_metric=focus,
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected network status from system-status contract"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
                slots=slots,
            )
        if family == "watch_runtime":
            browser_context = self._browser_context_request(decision.intent_frame.raw_text, lower, active_context={})
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip()
            source_case = str(decision.intent_frame.extracted_entities.get("source_case") or "").strip().lower()
            tool_name = (
                "browser_context"
                if browser_context is not None or requested_tool == "browser_context" or source_case == "browser_context"
                else "activity_summary"
            )
            return self._tool_proposal(
                query_shape=QueryShape.BROWSER_CONTEXT if tool_name == "browser_context" else QueryShape.SUMMARY_REQUEST,
                domain="browser" if tool_name == "browser_context" else "activity",
                tool_name=tool_name,
                tool_arguments=browser_context or ({"operation": "current_page"} if tool_name == "browser_context" else {}),
                request_type_hint="browser_context" if tool_name == "browser_context" else "activity_summary",
                family="watch_runtime",
                subject="browser_context" if tool_name == "browser_context" else "summary",
                requested_action="browser_context" if tool_name == "browser_context" else "summarize_activity",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected watch_runtime from runtime status contract"],
                execution_type="inspect_browser_context" if tool_name == "browser_context" else "summarize_activity",
                output_mode=ResponseMode.ACTION_RESULT.value if tool_name == "browser_context" else ResponseMode.SUMMARY_RESULT.value,
                slots=slots,
            )
        if family == "window_control":
            window_request = self._window_control_request(decision.intent_frame.raw_text, lower)
            if window_request is not None:
                return self._tool_proposal(
                    query_shape=QueryShape.CONTROL_COMMAND,
                    domain="system",
                    tool_name="window_control",
                    tool_arguments=window_request,
                    request_type_hint="direct_action",
                    family="window_control",
                    subject=str(window_request.get("action") or "window_control"),
                    requested_action=str(window_request.get("action") or "window_control"),
                    confidence=decision.winner.score or 0.92,
                    evidence=["window-control phrasing matched a deterministic control request"],
                    execution_type="execute_control_command",
                    output_mode=ResponseMode.ACTION_RESULT.value,
                    output_type="action",
                    slots=slots,
                )
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="system",
                tool_name="window_status",
                tool_arguments={"focus": "windows"},
                request_type_hint="direct_deterministic_fact",
                family="window_control",
                subject="windows",
                requested_metric="windows",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected window status from window-control contract"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
                slots=slots,
            )
        if family == "machine":
            focus = "time" if "time zone" in decision.intent_frame.normalized_text or "timezone" in decision.intent_frame.normalized_text else "identity"
            source_case = str(decision.intent_frame.extracted_entities.get("source_case") or "").strip().lower()
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip()
            tool_name = "system_info" if requested_tool == "system_info" or source_case == "system_info" or decision.intent_frame.raw_text.strip().lower().startswith("/system") else "machine_status"
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS if focus == "time" else QueryShape.IDENTITY_LOOKUP,
                domain="machine",
                tool_name=tool_name,
                tool_arguments={"focus": focus},
                request_type_hint="direct_deterministic_fact",
                family="machine",
                subject="machine",
                requested_metric=focus,
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected machine status"],
                execution_type="retrieve_current_status" if focus == "time" else "retrieve_identity",
                output_mode=ResponseMode.STATUS_SUMMARY.value if focus == "time" else ResponseMode.IDENTITY_SUMMARY.value,
                slots=slots,
            )
        if family == "resources":
            requested_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip()
            source_case = str(decision.intent_frame.extracted_entities.get("source_case") or "").strip().lower()
            if requested_tool == "resource_diagnosis" or source_case == "resource_diagnosis" or self._looks_like_resource_diagnosis(lower):
                return self._tool_proposal(
                    query_shape=QueryShape.DIAGNOSTIC_CAUSAL,
                    domain="system",
                    tool_name="resource_diagnosis",
                    tool_arguments={},
                    request_type_hint="deterministic_diagnostic_request",
                    family="resources",
                    subject="resources",
                    requested_metric="bottleneck",
                    diagnostic_mode=True,
                    confidence=decision.winner.score or 0.95,
                    evidence=["machine slowdown diagnosis phrasing detected"],
                    execution_type="diagnose_from_telemetry",
                    output_mode=ResponseMode.DIAGNOSTIC_SUMMARY.value,
                    slots=slots,
                )
            resource_query_kind = self._resource_query_kind(lower, recent_family="resources")
            if resource_query_kind is not None:
                focus = self._resource_focus(lower)
                metric = self._resource_metric(lower, focus=focus, query_kind=resource_query_kind)
                query_shape = QueryShape.CURRENT_METRIC
                output_mode = ResponseMode.NUMERIC_METRIC.value
                output_type = "numeric"
                request_type_hint = "direct_deterministic_fact"
                diagnostic_mode = False
                if resource_query_kind == "identity":
                    query_shape = QueryShape.IDENTITY_LOOKUP
                    output_mode = ResponseMode.IDENTITY_SUMMARY.value
                    output_type = "identity"
                elif resource_query_kind == "diagnostic":
                    query_shape = QueryShape.DIAGNOSTIC_CAUSAL
                    output_mode = ResponseMode.DIAGNOSTIC_SUMMARY.value
                    output_type = "interpreted"
                    request_type_hint = "deterministic_diagnostic_request"
                    diagnostic_mode = True
                domain = focus if focus in {"gpu", "cpu", "ram"} else "system"
                return self._tool_proposal(
                    query_shape=query_shape,
                    domain=domain,
                    tool_name="resource_status",
                    tool_arguments={"focus": focus, "query_kind": resource_query_kind, "metric": metric},
                    request_type_hint=request_type_hint,
                    family="resource",
                    subject=focus,
                    requested_metric=metric,
                    timescale="now" if query_shape == QueryShape.CURRENT_METRIC else None,
                    output_type=output_type,
                    diagnostic_mode=diagnostic_mode,
                    confidence=decision.winner.score or 0.95,
                    evidence=["resource query phrasing detected"],
                    execution_type="retrieve_identity" if query_shape == QueryShape.IDENTITY_LOOKUP else "diagnose_from_telemetry" if diagnostic_mode else "retrieve_live_metric",
                    output_mode=output_mode,
                    slots=slots,
                )
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="system",
                tool_name="resource_status",
                tool_arguments={"focus": "cpu_memory"},
                request_type_hint="direct_deterministic_fact",
                family="resources",
                subject="resources",
                requested_metric="cpu_memory",
                confidence=decision.winner.score or 0.9,
                evidence=["route_spine selected resource status from system-resource contract"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
                slots=slots,
            )
        requested_power_tool = str(decision.intent_frame.extracted_entities.get("tool_name") or "").strip()
        power_source_case = str(decision.intent_frame.extracted_entities.get("source_case") or "").strip().lower()
        selected = decision.intent_frame.extracted_entities.get("selected_context")
        previous_power_parameters: dict[str, Any] = {}
        if isinstance(selected, dict):
            selected_value = selected.get("value")
            if isinstance(selected_value, dict) and isinstance(selected_value.get("parameters"), dict):
                previous_power_parameters = dict(selected_value.get("parameters") or {})
        if requested_power_tool == "power_diagnosis" or power_source_case == "power_diagnosis" or self._looks_like_power_diagnosis(lower):
            return self._tool_proposal(
                query_shape=QueryShape.DIAGNOSTIC_CAUSAL,
                domain="power",
                tool_name="power_diagnosis",
                tool_arguments={},
                request_type_hint="deterministic_diagnostic_request",
                family="power",
                subject="power",
                requested_metric="drain_rate",
                diagnostic_mode=True,
                confidence=decision.winner.score or 0.95,
                evidence=["battery-drain diagnosis phrasing detected"],
                execution_type="diagnose_from_telemetry",
                output_mode=ResponseMode.DIAGNOSTIC_SUMMARY.value,
                slots=slots,
            )
        if requested_power_tool == "power_projection" or power_source_case == "power_projection" or self._looks_like_power_projection(lower, recent_family="power"):
            metric, target_percent = self._power_projection_shape(lower, previous_parameters=previous_power_parameters)
            return self._tool_proposal(
                query_shape=QueryShape.FORECAST_REQUEST,
                domain="power",
                tool_name="power_projection",
                tool_arguments={
                    "metric": metric,
                    "target_percent": target_percent,
                    "assume_unplugged": self._assume_unplugged(lower, previous=False),
                },
                request_type_hint="deterministic_projection_request",
                family="power",
                subject="power_projection",
                requested_metric=metric,
                output_type="summary",
                confidence=decision.winner.score or 0.95,
                evidence=["power projection phrasing detected"],
                execution_type="project_power_state",
                output_mode=ResponseMode.FORECAST_SUMMARY.value,
                slots=slots,
            )
        focus = self._power_focus(lower)
        return self._tool_proposal(
            query_shape=QueryShape.CURRENT_STATUS,
            domain="power",
            tool_name="power_status",
            tool_arguments={"focus": focus},
            request_type_hint="direct_deterministic_fact",
            family="power",
            subject="power",
            requested_metric=focus,
            confidence=decision.winner.score or 0.9,
            evidence=["route_spine selected power status"],
            execution_type="retrieve_current_status",
            output_mode=ResponseMode.STATUS_SUMMARY.value,
            slots=slots,
        )

    def _route_spine_slots(self, decision: RouteSpineDecision) -> dict[str, Any]:
        return {
            "routing_engine": decision.routing_engine,
            "route_spine": decision.to_dict(),
            "intent_frame": decision.intent_frame.to_dict(),
            "candidate_specs_considered": list(decision.candidate_specs_considered),
            "selected_route_spec": decision.selected_route_spec,
            "native_decline_reasons": decision.native_decline_reasons,
            "generic_provider_gate_reason": decision.generic_provider_gate_reason,
            "legacy_fallback_used": decision.legacy_fallback_used,
            "family": decision.winner.route_family,
            "subject": decision.intent_frame.target_text or decision.winner.route_family,
        }

    def _route_spine_selected_value(self, decision: RouteSpineDecision) -> str:
        selected = decision.intent_frame.extracted_entities.get("selected_context")
        if isinstance(selected, dict) and selected.get("value"):
            return str(selected.get("value") or "").strip()
        return ""

    def _calculation_missing_context_follow_up(
        self,
        lower: str,
        *,
        active_request_state: dict[str, Any],
    ) -> SemanticParseProposal | None:
        family = str(active_request_state.get("family") or "").strip().lower()
        math_follow_up = any(
            phrase in lower
            for phrase in (
                "show the steps",
                "show me the steps",
                "show the calculation",
                "show the arithmetic",
                "show me the arithmetic",
                "walk through that calculation",
                "redo that math",
                "redo it",
                "that math",
                "that number",
                "that value",
                "that result",
                "that answer",
                "divide that",
                "multiply that",
                "compare it to",
                "compare that answer",
                "use that number",
                "what about if",
                "what changes if",
                "numerator",
                "denominator",
                "same setup",
            )
        )
        continuity_follow_up = any(
            phrase in lower
            for phrase in (
                "same thing",
                "same calculation",
                "as before",
                "that calculation",
                "same math",
                "that preview",
                "other one",
                "use this",
                "use that",
                "go ahead",
                "continue",
            )
        )
        if family != "calculations" and not math_follow_up:
            return None
        if not math_follow_up and not continuity_follow_up:
            return None
        return self._tool_proposal(
            query_shape=QueryShape.CALCULATION_REQUEST,
            domain="calculations",
            request_type_hint="calculation_missing_context",
            family="calculations",
            subject="calculation_context",
            requested_action="clarify_calculation_context",
            confidence=0.86,
            evidence=["active calculation route owns follow-up but lacks a reusable expression"],
            follow_up=True,
            execution_type="clarify_calculation_context",
            output_mode=ResponseMode.CLARIFICATION.value,
            output_type="numeric",
            slots={
                "clarification": {
                    "code": "missing_calculation_context",
                    "message": "Which calculation should I reuse?",
                    "missing_slots": ["calculation_context"],
                },
                "missing_preconditions": ["calculation_context"],
            },
        )

    def _route_context_arbitration_request(
        self,
        message: str,
        lower: str,
        *,
        surface_mode: str,
        active_context: dict[str, Any],
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> SemanticParseProposal | None:
        arbitration = self._route_context_arbitrator.evaluate(
            normalized_text=lower,
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        if arbitration is None or not arbitration.route_family_owners:
            return None
        owner = arbitration.route_family_owners[0]
        if owner == "calculations":
            return self._arbitrated_clarification(
                query_shape=QueryShape.CALCULATION_REQUEST,
                domain="calculations",
                family="calculations",
                subject="calculation_context",
                requested_action="clarify_calculation_context",
                arbitration=arbitration,
                default_missing_slot="calculation_context",
            )
        if owner == "browser_destination":
            return self._arbitrated_browser_destination(message, surface_mode=surface_mode, arbitration=arbitration)
        if owner == "file":
            return self._arbitrated_file_request(message, surface_mode=surface_mode, arbitration=arbitration)
        if owner == "context_action":
            return self._arbitrated_context_action(arbitration=arbitration)
        if owner == "screen_awareness":
            return self._arbitrated_clarification(
                query_shape=QueryShape.SCREEN_AWARENESS_REQUEST,
                domain="screen_awareness",
                family="screen_awareness",
                subject="visible_screen",
                requested_action="ground_screen_action",
                arbitration=arbitration,
                default_missing_slot="visible_screen",
                execution_type="screen_awareness_act",
                output_type="screen_action",
            )
        if owner == "discord_relay":
            return self._arbitrated_clarification(
                query_shape=QueryShape.DISCORD_RELAY_REQUEST,
                domain="discord_relay",
                family="discord_relay",
                subject="relay_context",
                requested_action="preview",
                arbitration=arbitration,
                default_missing_slot="payload",
                execution_type="discord_relay_preview",
                output_type="action",
            )
        if owner == "trust_approvals":
            return self._arbitrated_clarification(
                query_shape=QueryShape.TRUST_APPROVAL_REQUEST,
                domain="trust",
                family="trust_approvals",
                subject="approval",
                requested_action="explain_approval",
                arbitration=arbitration,
                default_missing_slot="approval_object",
                execution_type="explain_approval",
                output_type="trust",
                output_mode=ResponseMode.SUMMARY_RESULT.value,
            )
        if owner == "file_operation":
            return self._arbitrated_clarification(
                query_shape=QueryShape.FILE_OPERATION,
                domain="files",
                family="file_operation",
                subject="file_operation",
                requested_action="file_operation",
                arbitration=arbitration,
                default_missing_slot="file_context",
            )
        if owner == "routine":
            return self._arbitrated_clarification(
                query_shape=QueryShape.ROUTINE_REQUEST,
                domain="workflow",
                family="routine",
                subject="routine",
                requested_action="execute_routine",
                arbitration=arbitration,
                default_missing_slot="routine_context",
            )
        if owner == "network":
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="network",
                tool_name="network_status",
                tool_arguments={"focus": "overview"},
                request_type_hint="direct_deterministic_fact",
                family="network",
                subject="network",
                requested_metric="overview",
                confidence=0.94,
                evidence=[arbitration.reason],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
                slots={"route_context_arbitration": arbitration.to_dict()},
            )
        if owner == "watch_runtime":
            return self._tool_proposal(
                query_shape=QueryShape.SUMMARY_REQUEST,
                domain="activity",
                tool_name="activity_summary",
                tool_arguments={"query": message},
                request_type_hint="activity_summary",
                family="watch_runtime",
                subject="summary",
                requested_action="summarize_activity",
                confidence=0.93,
                evidence=[arbitration.reason],
                execution_type="summarize_activity",
                output_mode=ResponseMode.SUMMARY_RESULT.value,
                slots={"route_context_arbitration": arbitration.to_dict()},
            )
        if owner == "system_control":
            target = self._settings_target_from_text(lower)
            if target == "location" and self._looks_like_open_location_settings(lower):
                return self._tool_proposal(
                    query_shape=QueryShape.CONTROL_COMMAND,
                    domain="location",
                    tool_name="external_open_url",
                    tool_arguments={"url": "ms-settings:privacy-location"},
                    request_type_hint="direct_action",
                    family="location",
                    subject="open_settings",
                    requested_action="open_location_settings",
                    confidence=0.94,
                    evidence=[arbitration.reason, "location settings target should open the external settings URI"],
                    execution_type="execute_control_command",
                    output_mode=ResponseMode.ACTION_RESULT.value,
                    slots={"route_context_arbitration": arbitration.to_dict()},
                )
            return self._tool_proposal(
                query_shape=QueryShape.CONTROL_COMMAND,
                domain="system",
                tool_name="system_control",
                tool_arguments={"action": "open_settings_page", "target": target},
                request_type_hint="direct_action",
                family="system_control",
                subject="open_settings",
                requested_action="open_settings_page",
                confidence=0.92,
                evidence=[arbitration.reason],
                execution_type="execute_control_command",
                output_mode=ResponseMode.ACTION_RESULT.value,
                slots={"route_context_arbitration": arbitration.to_dict()},
            )
        return None

    def _arbitrated_clarification(
        self,
        *,
        query_shape: QueryShape,
        domain: str,
        family: str,
        subject: str,
        requested_action: str,
        arbitration: RouteContextArbitration,
        default_missing_slot: str,
        execution_type: str | None = None,
        output_type: str | None = None,
        output_mode: str | None = None,
    ) -> SemanticParseProposal:
        missing = list(arbitration.missing_preconditions or (default_missing_slot,))
        message = arbitration.clarification_text or "Which context should I use?"
        return self._tool_proposal(
            query_shape=query_shape,
            domain=domain,
            request_type_hint=f"{family}_context_clarification",
            family=family,
            subject=subject,
            requested_action=requested_action,
            confidence=0.88,
            evidence=[arbitration.reason],
            assistant_message=message,
            execution_type=execution_type or "clarify_route_context",
            output_mode=output_mode or ResponseMode.CLARIFICATION.value,
            output_type=output_type,
            slots={
                "clarification": {
                    "code": f"missing_{family}_context",
                    "message": message,
                    "missing_slots": missing,
                },
                "missing_preconditions": missing,
                "route_context_arbitration": arbitration.to_dict(),
                "fallback_reason": arbitration.reason,
            },
        )

    def _arbitrated_browser_destination(
        self,
        message: str,
        *,
        surface_mode: str,
        arbitration: RouteContextArbitration,
    ) -> SemanticParseProposal:
        binding = arbitration.selected_binding
        if binding is None or not binding.value:
            return self._arbitrated_clarification(
                query_shape=QueryShape.OPEN_BROWSER_DESTINATION,
                domain="browser",
                family="browser_destination",
                subject="browser_destination",
                requested_action="open_browser_destination",
                arbitration=arbitration,
                default_missing_slot="destination_context",
                execution_type="resolve_url_then_open_in_browser",
                output_type="action",
            )
        open_in_deck = surface_mode.strip().lower() == "deck" or bool(
            re.search(r"\b(?:in|inside|within)\s+(?:the\s+)?deck\b", message, flags=re.IGNORECASE)
        )
        tool_name = "deck_open_url" if open_in_deck else "external_open_url"
        return self._tool_proposal(
            query_shape=QueryShape.OPEN_BROWSER_DESTINATION,
            domain="browser",
            tool_name=tool_name,
            tool_arguments={"url": str(binding.value)},
            request_type_hint="direct_action",
            family="browser_destination",
            subject=binding.label,
            requested_action="open_browser_destination",
            confidence=0.93,
            evidence=[arbitration.reason],
            execution_type="resolve_url_then_open_in_browser",
            output_mode=ResponseMode.ACTION_RESULT.value,
            output_type="action",
            slots={
                "target_scope": "browser",
                "route_context_arbitration": arbitration.to_dict(),
                "deictic_binding": self._arbitration_binding_payload(arbitration),
                "open_target": message,
            },
        )

    def _arbitrated_file_request(
        self,
        message: str,
        *,
        surface_mode: str,
        arbitration: RouteContextArbitration,
    ) -> SemanticParseProposal:
        explicit_path = self._route_context_arbitrator.explicit_file_path(message)
        if arbitration.tool_hint == "file_reader" and explicit_path:
            return self._tool_proposal(
                query_shape=QueryShape.CONTEXT_ACTION,
                domain="files",
                tool_name="file_reader",
                tool_arguments={"path": explicit_path},
                request_type_hint="file_read",
                family="file",
                subject=explicit_path,
                requested_action="read_file",
                confidence=0.96,
                evidence=[arbitration.reason],
                execution_type="read_file",
                output_mode=ResponseMode.SUMMARY_RESULT.value,
                output_type="file",
                slots={
                    "target_scope": "files",
                    "path": explicit_path,
                    "route_context_arbitration": arbitration.to_dict(),
                },
            )
        binding = arbitration.selected_binding
        if binding is None or not binding.value:
            return self._arbitrated_clarification(
                query_shape=QueryShape.CONTEXT_ACTION,
                domain="files",
                family="file",
                subject="file_context",
                requested_action="open_file",
                arbitration=arbitration,
                default_missing_slot="file_context",
                execution_type="execute_control_command",
                output_type="action",
            )
        open_in_deck = surface_mode.strip().lower() == "deck" or bool(
            re.search(r"\b(?:in|inside|within)\s+(?:the\s+)?deck\b", message, flags=re.IGNORECASE)
        )
        tool_name = "deck_open_file" if open_in_deck else "external_open_file"
        return self._tool_proposal(
            query_shape=QueryShape.CONTEXT_ACTION,
            domain="files",
            tool_name=tool_name,
            tool_arguments={"path": str(binding.value)},
            request_type_hint="direct_action",
            family="file",
            subject=binding.label,
            requested_action="open_file",
            confidence=0.93,
            evidence=[arbitration.reason],
            execution_type="execute_control_command",
            output_mode=ResponseMode.ACTION_RESULT.value,
            output_type="action",
            slots={
                "target_scope": "files",
                "route_context_arbitration": arbitration.to_dict(),
                "deictic_binding": self._arbitration_binding_payload(arbitration),
            },
        )

    def _arbitrated_context_action(self, *, arbitration: RouteContextArbitration) -> SemanticParseProposal:
        binding = arbitration.selected_binding
        if binding is None:
            return self._arbitrated_clarification(
                query_shape=QueryShape.CONTEXT_ACTION,
                domain="context",
                family="context_action",
                subject="context",
                requested_action=arbitration.requested_action or "inspect",
                arbitration=arbitration,
                default_missing_slot="context",
            )
        source = "clipboard" if binding.context_source == "clipboard" else "selection"
        operation = arbitration.requested_action or "inspect"
        return self._tool_proposal(
            query_shape=QueryShape.CONTEXT_ACTION,
            domain="context",
            tool_name="context_action",
            tool_arguments={"operation": operation, "source": source},
            request_type_hint="context_action",
            family="task_continuity" if operation == "extract_tasks" else "context_action",
            subject=operation,
            requested_action=operation,
            confidence=0.92,
            evidence=[arbitration.reason],
            execution_type="execute_context_action",
            output_mode=ResponseMode.ACTION_RESULT.value,
            slots={
                "target_scope": "context",
                "route_context_arbitration": arbitration.to_dict(),
                "deictic_binding": self._arbitration_binding_payload(arbitration),
            },
        )

    def _arbitration_binding_payload(self, arbitration: RouteContextArbitration) -> dict[str, Any]:
        selected = arbitration.selected_binding
        return {
            "resolved": selected is not None,
            "selected_source": selected.context_source if selected is not None else None,
            "selected_target": selected.to_dict() if selected is not None else None,
            "candidates": [binding.to_dict() for binding in arbitration.candidate_bindings],
            "unresolved_reason": None if selected is not None else "no_current_binding_source",
            "binding_posture": "current" if selected is not None else "unbound",
            "source_summary": arbitration.reason,
        }

    def _settings_target_from_text(self, lower: str) -> str:
        match = re.match(r"^(?:open|show|bring\s+up)\s+(.+?)\s+settings?$", lower)
        if not match:
            return "settings"
        return re.sub(r"[^a-z0-9_-]+", "_", str(match.group(1) or "settings").strip().lower()).strip("_") or "settings"

    def _semantic_parse_proposal(
        self,
        message: str,
        *,
        normalized: NormalizedCommand,
        session_id: str,
        workspace_context: dict[str, Any] | None,
        active_posture: dict[str, Any] | None,
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
        learned_preferences: dict[str, dict[str, object]],
        active_context: dict[str, Any],
        screen_awareness_evaluation: ScreenPlannerEvaluation,
    ) -> SemanticParseProposal:
        del session_id
        message = normalized.raw_text or self._strip_invocation_prefix(message)
        lower = normalized.normalized_text
        recent_family = self._recent_family(recent_tool_results)
        weather_open_default = str(self._preference_value(learned_preferences, "weather", "open_target") or "none")
        weather_location_default = str(self._preference_value(learned_preferences, "weather", "location_mode") or "auto")
        present_in = "deck" if any(token in lower for token in {" in systems", " in the systems", "show in systems"}) else "none"

        trust_approval = self._trust_approval_request(lower, active_request_state=active_request_state)
        if trust_approval is not None:
            return trust_approval

        search_correction = self._search_correction_request(message, lower, active_request_state=active_request_state)
        if search_correction is not None:
            return search_correction

        calculation_follow_up = self._calculation_missing_context_follow_up(
            lower,
            active_request_state=active_request_state,
        )
        if calculation_follow_up is not None:
            return calculation_follow_up

        deictic_open = self._deictic_open_request(
            message,
            lower,
            surface_mode=normalized.surface_mode,
            active_context=active_context,
        )
        if deictic_open is not None:
            return deictic_open

        route_context = self._route_context_arbitration_request(
            message,
            lower,
            surface_mode=normalized.surface_mode,
            active_context=active_context,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        if route_context is not None:
            return route_context

        screen_awareness_proposal = self._screen_awareness_semantic_proposal(screen_awareness_evaluation)
        if screen_awareness_proposal is not None:
            return screen_awareness_proposal

        discord_relay = self._discord_relay_request(
            message,
            lower,
            active_request_state=active_request_state,
            active_context=active_context,
        )
        if discord_relay is not None:
            return discord_relay

        location_source_message = self._location_source_follow_up_message(
            lower,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
        )
        if location_source_message is not None:
            return self._tool_proposal(
                query_shape=QueryShape.SUMMARY_REQUEST,
                domain="weather",
                request_type_hint="follow_up_grounded",
                family="weather",
                subject="weather",
                confidence=0.97,
                evidence=["recent weather result grounds the location-source answer"],
                follow_up=True,
                assistant_message=location_source_message,
                execution_type="summarize_context",
                output_mode=ResponseMode.SUMMARY_RESULT.value,
            )

        follow_up = self._classify_follow_up(
            lower,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
            recent_family=recent_family,
            present_in=present_in,
        )
        if follow_up is not None:
            return self._proposal_from_classification(
                follow_up,
                message=message,
                lower=lower,
                follow_up=True,
            )

        if self._looks_like_clock_time(lower):
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="time",
                tool_name="clock",
                tool_arguments={},
                request_type_hint="direct_deterministic_fact",
                family="time",
                subject="clock",
                requested_metric="local_time",
                confidence=0.97,
                evidence=["simple time/date phrasing matched the local clock lane"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )

        active_item_decision = self._plan_active_item_follow_up(
            message,
            surface_mode=normalized.surface_mode,
            workspace_context=workspace_context,
            active_posture=active_posture,
        )
        if active_item_decision is not None:
            return self._tool_proposal(
                query_shape=QueryShape.SEARCH_AND_OPEN,
                domain="files",
                request_type_hint=active_item_decision.request_type,
                family="desktop_search",
                subject="active_item",
                confidence=0.94,
                evidence=["active workspace item can satisfy the reopen request"],
                follow_up=True,
                execution_type="search_then_open",
                output_mode=ResponseMode.SEARCH_RESULT.value,
                slots={"compatibility_decision": active_item_decision},
            )

        if self._looks_like_native_comparison_request(lower):
            comparison_target = re.sub(r"^(?:compare|diff)\s+", "", lower, flags=re.IGNORECASE).strip(" .")
            return self._tool_proposal(
                query_shape=QueryShape.COMPARISON_REQUEST,
                domain="files" if "file" in lower else "system",
                request_type_hint="comparison_request",
                family="comparison",
                subject="files" if "file" in lower else "comparison",
                requested_action="compare",
                confidence=0.92,
                evidence=["comparison verb detected"],
                execution_type="compare_items",
                output_mode=ResponseMode.SUMMARY_RESULT.value,
                slots={
                    "comparison_target": comparison_target,
                    "current_context_reference": "deictic" if any(token in lower for token in {"this", "that", "these", "those"}) else None,
                },
            )

        if self._looks_like_where_left_off(lower):
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name="workspace_where_left_off",
                tool_arguments={},
                request_type_hint="workspace_restore",
                family="task_continuity",
                subject="where_left_off",
                requested_action="where_left_off",
                confidence=0.96,
                evidence=["continuity phrasing matched workspace continuation"],
                execution_type="summarize_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
            )
        if self._looks_like_next_steps(lower):
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name="workspace_next_steps",
                tool_arguments={},
                request_type_hint="direct_deterministic_fact",
                family="task_continuity",
                subject="next_steps",
                requested_action="next_steps",
                confidence=0.95,
                evidence=["next-steps phrasing matched workspace summary"],
                execution_type="summarize_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
            )
        if self._looks_like_workspace_save(lower):
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name="workspace_save",
                tool_arguments={},
                request_type_hint="direct_action",
                family="workspace",
                subject="save",
                requested_action="save",
                confidence=0.96,
                evidence=["workspace save phrase detected"],
                execution_type="save_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
            )
        if self._looks_like_workspace_clear(lower):
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name="workspace_clear",
                tool_arguments={},
                request_type_hint="direct_action",
                family="workspace",
                subject="clear",
                requested_action="clear",
                confidence=0.96,
                evidence=["workspace clear phrase detected"],
                execution_type="clear_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
            )
        if self._looks_like_workspace_archive(lower):
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name="workspace_archive",
                tool_arguments={"query": message},
                request_type_hint="direct_action",
                family="workspace",
                subject="archive",
                requested_action="archive",
                confidence=0.95,
                evidence=["workspace archive phrase detected"],
                execution_type="archive_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
            )
        if self._looks_like_workspace_rename(lower):
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name="workspace_rename",
                tool_arguments={"new_name": self._extract_after_phrase(message, "to")},
                request_type_hint="direct_action",
                family="workspace",
                subject="rename",
                requested_action="rename",
                confidence=0.95,
                evidence=["workspace rename phrase detected"],
                execution_type="rename_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
            )
        if self._looks_like_workspace_tag(lower):
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name="workspace_tag",
                tool_arguments={"tags": self._extract_tags(message)},
                request_type_hint="direct_action",
                family="workspace",
                subject="tag",
                requested_action="tag",
                confidence=0.94,
                evidence=["workspace tag phrase detected"],
                execution_type="tag_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
            )
        if self._looks_like_workspace_list(lower):
            include_archived = "archived" in lower
            archived_only = "show my archived workspaces" in lower
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name="workspace_list",
                tool_arguments={
                    "query": self._extract_workspace_list_query(message),
                    "include_archived": include_archived,
                    "archived_only": archived_only,
                },
                request_type_hint="direct_deterministic_fact",
                family="workspace",
                subject="list",
                requested_action="list",
                confidence=0.95,
                evidence=["workspace listing phrase detected"],
                execution_type="list_workspaces",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
            )
        if self._looks_like_workspace_assemble(lower):
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name="workspace_assemble",
                tool_arguments={"query": message},
                request_type_hint="workspace_assembly",
                family="workspace",
                subject="assemble",
                requested_action="assemble",
                confidence=0.95,
                evidence=["workspace assembly phrasing detected"],
                execution_type="assemble_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
            )
        if self._looks_like_workspace_restore(lower):
            return self._tool_proposal(
                query_shape=QueryShape.WORKSPACE_REQUEST,
                domain="workspace",
                tool_name="workspace_restore",
                tool_arguments={"query": message},
                request_type_hint="workspace_restore",
                family="workspace",
                subject="restore",
                requested_action="restore",
                confidence=0.95,
                evidence=["workspace restore phrasing detected"],
                execution_type="restore_workspace",
                output_mode=ResponseMode.WORKSPACE_RESULT.value,
            )

        explicit_file_open = self._explicit_file_open_request(message, lower, surface_mode=normalized.surface_mode)
        if explicit_file_open is not None:
            return explicit_file_open

        routine_save = self._routine_save_request(
            message,
            lower,
            active_request_state=active_request_state,
            active_context=active_context,
            active_posture=active_posture,
        )
        if routine_save is not None:
            precondition_state = (
                routine_save.get("routine_save_precondition_state")
                if isinstance(routine_save.get("routine_save_precondition_state"), dict)
                else {}
            )
            missing_preconditions = list(precondition_state.get("missing_preconditions") or [])
            if missing_preconditions:
                return self._tool_proposal(
                    query_shape=QueryShape.ROUTINE_REQUEST,
                    domain="workflow",
                    request_type_hint="routine_save_preflight",
                    family="routine",
                    subject="save",
                    requested_action="save_routine",
                    confidence=0.95,
                    evidence=["routine-save intent detected but deictic context is missing"],
                    execution_type="save_routine_preflight",
                    output_mode=ResponseMode.CLARIFICATION.value,
                    slots={
                        "routine_save_precondition_state": precondition_state,
                        "routine_name": routine_save.get("routine_name"),
                        "missing_evidence": list(missing_preconditions),
                        "clarification": {
                            "code": "missing_routine_context",
                            "message": (
                                "I can save that as a routine, but I need the steps or the recent action you want me to reuse. "
                                "Send the workflow steps, or run the action first and then ask me to save it."
                            ),
                            "missing_slots": list(missing_preconditions),
                        },
                    },
                )
            return self._tool_proposal(
                query_shape=QueryShape.ROUTINE_REQUEST,
                domain="workflow",
                tool_name="routine_save",
                tool_arguments=routine_save,
                request_type_hint="routine_save",
                family="routine",
                subject="save",
                requested_action="save_routine",
                confidence=0.95,
                evidence=["save this as a routine phrasing detected"],
                execution_type="save_routine",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        trusted_hook = self._trusted_hook_execute_request(message, lower)
        if trusted_hook is not None:
            return self._tool_proposal(
                query_shape=QueryShape.CONTROL_COMMAND,
                domain="system",
                tool_name="trusted_hook_execute",
                tool_arguments=trusted_hook,
                request_type_hint="trusted_hook_execution",
                family="routine",
                subject="execute",
                requested_action="execute_trusted_hook",
                confidence=0.95,
                evidence=["trusted hook execution phrase detected"],
                execution_type="execute_control_command",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        workflow_request = self._workflow_execution_request(message, lower)
        if workflow_request is not None:
            return self._tool_proposal(
                query_shape=QueryShape.WORKFLOW_REQUEST,
                domain="workflow",
                tool_name="workflow_execute",
                tool_arguments=workflow_request,
                request_type_hint="workflow_execution",
                family="workflow",
                subject=str(workflow_request.get("workflow_kind") or "workflow"),
                requested_action="execute_workflow",
                confidence=0.94,
                evidence=["workflow setup phrasing detected"],
                execution_type="execute_workflow",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        routine_execute = self._routine_execute_request(message, lower)
        if routine_execute is not None:
            return self._tool_proposal(
                query_shape=QueryShape.ROUTINE_REQUEST,
                domain="workflow",
                tool_name="routine_execute",
                tool_arguments=routine_execute,
                request_type_hint="routine_execution",
                family="routine",
                subject=str(routine_execute.get("routine_name") or "routine"),
                requested_action="execute_routine",
                confidence=0.94,
                evidence=["routine execution phrase detected"],
                execution_type="execute_routine",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        maintenance_request = self._maintenance_action_request(message, lower)
        if maintenance_request is not None:
            return self._tool_proposal(
                query_shape=QueryShape.MAINTENANCE_REQUEST,
                domain="files",
                tool_name="maintenance_action",
                tool_arguments=maintenance_request,
                request_type_hint="maintenance_execution",
                family="maintenance",
                subject=str(maintenance_request.get("maintenance_kind") or "maintenance"),
                requested_action="execute_maintenance",
                confidence=0.94,
                evidence=["maintenance phrase detected"],
                execution_type="execute_maintenance",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        file_operation = self._file_operation_request(message, lower)
        if file_operation is not None:
            return self._tool_proposal(
                query_shape=QueryShape.FILE_OPERATION,
                domain="files",
                tool_name="file_operation",
                tool_arguments=file_operation,
                request_type_hint="file_operation",
                family="file_operation",
                subject=str(file_operation.get("operation") or "file_operation"),
                requested_action="file_operation",
                confidence=0.94,
                evidence=["file-operation phrase detected"],
                execution_type="execute_file_operation",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        browser_context = self._browser_context_request(message, lower, active_context=active_context)
        if browser_context is not None:
            return self._tool_proposal(
                query_shape=QueryShape.BROWSER_CONTEXT,
                domain="browser",
                tool_name="browser_context",
                tool_arguments=browser_context,
                request_type_hint="browser_context",
                family="browser_context",
                subject=str(browser_context.get("operation") or "browser_context"),
                requested_action=str(browser_context.get("operation") or "browser_context"),
                confidence=0.95,
                evidence=["browser-context phrase detected"],
                execution_type="inspect_browser_context",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        activity_request = self._activity_summary_request(message, lower)
        if activity_request is not None:
            return self._tool_proposal(
                query_shape=QueryShape.SUMMARY_REQUEST,
                domain="activity",
                tool_name="activity_summary",
                tool_arguments=activity_request,
                request_type_hint="activity_summary",
                family="watch_runtime",
                subject="summary",
                requested_action="summarize_activity",
                confidence=0.94,
                evidence=["activity summary phrase detected"],
                execution_type="summarize_activity",
                output_mode=ResponseMode.SUMMARY_RESULT.value,
            )
        context_action = self._context_action_request(message, lower, active_context=active_context)
        if context_action is not None:
            clarification_payload = context_action.get("clarification") if isinstance(context_action.get("clarification"), dict) else {}
            if clarification_payload:
                return self._tool_proposal(
                    query_shape=QueryShape.CONTEXT_ACTION,
                    domain="context",
                    request_type_hint="context_action",
                    family="context_action",
                    subject=str(context_action.get("operation") or "context_action"),
                    requested_action=str(context_action.get("operation") or "context_action"),
                    confidence=0.86,
                    evidence=["context-action phrasing detected but active context was missing"],
                    execution_type="execute_context_action",
                    output_mode=ResponseMode.CLARIFICATION.value,
                    slots={
                        "clarification": clarification_payload,
                        "missing_preconditions": list(clarification_payload.get("missing_slots") or ["context"]),
                        "target_scope": "context",
                    },
                )
            return self._tool_proposal(
                query_shape=QueryShape.CONTEXT_ACTION,
                domain="context",
                tool_name="context_action",
                tool_arguments=context_action,
                request_type_hint="context_action",
                family="task_continuity" if str(context_action.get("operation") or "") == "extract_tasks" else "context_action",
                subject=str(context_action.get("operation") or "context_action"),
                requested_action=str(context_action.get("operation") or "context_action"),
                confidence=0.94,
                evidence=["context-action phrasing detected"],
                execution_type="execute_context_action",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        browser_destination = self._browser_destination_request(message, lower, surface_mode=normalized.surface_mode)
        if browser_destination is not None:
            return browser_destination
        browser_search = self._browser_search_request(message, lower, surface_mode=normalized.surface_mode)
        if browser_search is not None:
            return browser_search
        search_request = self._desktop_search_request(message, lower, surface_mode=normalized.surface_mode)
        if search_request is not None:
            action = str(search_request.get("action") or "search")
            return self._tool_proposal(
                query_shape=QueryShape.SEARCH_AND_OPEN if action == "open" else QueryShape.SEARCH_REQUEST,
                domain="files",
                tool_name="desktop_search",
                tool_arguments=search_request,
                request_type_hint="search_and_act",
                family="desktop_search",
                subject="search",
                requested_action=action,
                confidence=0.94,
                evidence=["desktop-search phrasing detected"],
                execution_type="search_then_open" if action == "open" else "search_desktop",
                output_mode=ResponseMode.SEARCH_RESULT.value,
                slots={"target_scope": "desktop"},
            )
        repair_request = self._repair_action_request(message, lower)
        if repair_request is not None:
            return self._tool_proposal(
                query_shape=QueryShape.REPAIR_REQUEST,
                domain="network" if "network" in str(repair_request.get("repair_kind") or "") or "dns" in str(repair_request.get("repair_kind") or "") else "system",
                tool_name="repair_action",
                tool_arguments=repair_request,
                request_type_hint="repair_execution",
                family="software_recovery",
                subject=str(repair_request.get("repair_kind") or "repair"),
                requested_action=str(repair_request.get("repair_kind") or "repair"),
                confidence=0.94,
                evidence=["repair phrasing detected"],
                execution_type="execute_repair",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        if self._looks_like_open_location_settings(lower):
            return self._tool_proposal(
                query_shape=QueryShape.CONTROL_COMMAND,
                domain="location",
                tool_name="external_open_url",
                tool_arguments={"url": "ms-settings:privacy-location"},
                request_type_hint="direct_action",
                family="location",
                subject="open_settings",
                requested_action="open_location_settings",
                confidence=0.95,
                evidence=["open location settings phrase detected"],
                execution_type="execute_control_command",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        system_control = self._system_control_request(message, lower)
        if system_control is not None:
            return self._tool_proposal(
                query_shape=QueryShape.CONTROL_COMMAND,
                domain="system",
                tool_name="system_control",
                tool_arguments=system_control,
                request_type_hint="direct_action",
                family="system_control",
                subject=str(system_control.get("action") or "system_control"),
                requested_action=str(system_control.get("action") or "system_control"),
                confidence=0.95,
                evidence=["system control phrase detected"],
                execution_type="execute_control_command",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        app_control_follow_up = self._app_control_selection_follow_up(
            lower,
            active_request_state=active_request_state,
        )
        if app_control_follow_up is not None:
            return self._tool_proposal(
                query_shape=QueryShape.CONTROL_COMMAND,
                domain="applications",
                tool_name="app_control",
                tool_arguments=app_control_follow_up,
                request_type_hint="direct_action",
                family="app_control",
                subject=str(app_control_follow_up.get("app_name") or "app_control"),
                requested_action=str(app_control_follow_up.get("action") or "close"),
                confidence=0.96,
                evidence=["app-control clarification follow-up selected previous candidates"],
                follow_up=True,
                execution_type="execute_control_command",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        window_control = self._window_control_request(message, lower)
        if window_control is not None:
            return self._tool_proposal(
                query_shape=QueryShape.CONTROL_COMMAND,
                domain="windows",
                tool_name="window_control",
                tool_arguments=window_control,
                request_type_hint="direct_action",
                family="window_control",
                subject=str(window_control.get("action") or "window_control"),
                requested_action=str(window_control.get("action") or "window_control"),
                confidence=0.95,
                evidence=["window control phrase detected"],
                execution_type="execute_control_command",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        app_control = self._app_control_request(message, lower)
        if app_control is not None:
            return self._tool_proposal(
                query_shape=QueryShape.CONTROL_COMMAND,
                domain="applications",
                tool_name="app_control",
                tool_arguments=app_control,
                request_type_hint="direct_action",
                family="app_control",
                subject=str(app_control.get("action") or "app_control"),
                requested_action=str(app_control.get("action") or "app_control"),
                confidence=0.95,
                evidence=["app control phrase detected"],
                execution_type="execute_control_command",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )

        named_location = None
        named_location_type = None
        location_reference = self._location_reference_override(lower)
        if location_reference is not None:
            named_location, named_location_type = location_reference

        if self._looks_like_save_home_location(lower):
            active_family = str(active_request_state.get("family") or "").strip().lower()
            parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
            source_mode = str(parameters.get("location_mode") or "current").strip().lower() or "current"
            if active_family == "location" and parameters.get("mode"):
                source_mode = str(parameters.get("mode")).strip().lower() or source_mode
            return self._tool_proposal(
                query_shape=QueryShape.CONTROL_COMMAND,
                domain="location",
                tool_name="save_location",
                tool_arguments={"target": "home", "source_mode": source_mode},
                request_type_hint="direct_action",
                family="location",
                subject="save_home",
                requested_action="save_home_location",
                confidence=0.95,
                evidence=["save home location phrase detected"],
                execution_type="execute_control_command",
                output_mode=ResponseMode.ACTION_RESULT.value,
            )
        if self._looks_like_saved_locations_list(lower):
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="location",
                tool_name="saved_locations",
                tool_arguments={},
                request_type_hint="direct_deterministic_fact",
                family="location",
                subject="saved_locations",
                requested_action="list_saved_locations",
                confidence=0.95,
                evidence=["saved-locations listing phrase detected"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        if self._looks_like_location(lower):
            mode = "named" if named_location else self._location_mode(lower, previous="auto")
            allow_home_fallback = self._allow_home_fallback(lower, previous=(mode != "current"))
            arguments: dict[str, Any] = {"mode": mode, "allow_home_fallback": allow_home_fallback}
            if named_location:
                arguments["named_location"] = named_location
                arguments["named_location_type"] = named_location_type or "saved_alias"
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="location",
                tool_name="location_status",
                tool_arguments=arguments,
                request_type_hint="direct_deterministic_fact",
                family="location",
                subject="location",
                requested_metric="location",
                confidence=0.95,
                evidence=["location status phrase detected"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        if self._looks_like_weather(lower):
            open_target = self._open_target(lower, previous="none", preferred=weather_open_default)
            forecast_target = self._forecast_target(lower, previous="current")
            location_mode = "named" if named_location else self._location_mode(lower, previous=weather_location_default)
            allow_home_fallback = self._allow_home_fallback(lower, previous=True)
            arguments = {
                "open_target": open_target,
                "location_mode": location_mode,
                "allow_home_fallback": allow_home_fallback,
                "forecast_target": forecast_target,
            }
            if named_location:
                arguments["named_location"] = named_location
                arguments["named_location_type"] = named_location_type or "saved_alias"
            request_type_hint = "direct_action" if open_target != "none" else ("deterministic_projection_request" if forecast_target != "current" else "direct_deterministic_fact")
            return self._tool_proposal(
                query_shape=QueryShape.FORECAST_REQUEST if forecast_target != "current" else QueryShape.CURRENT_STATUS,
                domain="weather",
                tool_name="weather_current",
                tool_arguments=arguments,
                request_type_hint=request_type_hint,
                family="weather",
                subject="weather",
                requested_metric="forecast" if forecast_target != "current" else "current_conditions",
                timescale="now" if forecast_target == "current" else forecast_target,
                output_type="summary",
                confidence=0.95,
                evidence=["weather phrasing detected"],
                execution_type="retrieve_forecast" if forecast_target != "current" else "retrieve_current_status",
                output_mode=ResponseMode.FORECAST_SUMMARY.value,
            )
        if self._looks_like_power_diagnosis(lower):
            return self._tool_proposal(
                query_shape=QueryShape.DIAGNOSTIC_CAUSAL,
                domain="power",
                tool_name="power_diagnosis",
                tool_arguments={},
                request_type_hint="deterministic_diagnostic_request",
                family="power_diagnosis",
                subject="power_diagnosis",
                requested_metric="drain_rate",
                diagnostic_mode=True,
                confidence=0.95,
                evidence=["battery-drain diagnosis phrasing detected"],
                execution_type="diagnose_from_telemetry",
                output_mode=ResponseMode.DIAGNOSTIC_SUMMARY.value,
            )
        if self._looks_like_power_projection(lower, recent_family=recent_family):
            metric, target_percent = self._power_projection_shape(lower, previous_parameters={})
            return self._tool_proposal(
                query_shape=QueryShape.FORECAST_REQUEST,
                domain="power",
                tool_name="power_projection",
                tool_arguments={
                    "metric": metric,
                    "target_percent": target_percent,
                    "assume_unplugged": self._assume_unplugged(lower, previous=False),
                },
                request_type_hint="deterministic_projection_request",
                family="power",
                subject="power_projection",
                requested_metric=metric,
                output_type="summary",
                confidence=0.95,
                evidence=["power projection phrasing detected"],
                execution_type="project_power_state",
                output_mode=ResponseMode.FORECAST_SUMMARY.value,
            )
        if self._looks_like_power_status(lower, recent_family=recent_family):
            focus = self._power_focus(lower)
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="power",
                tool_name="power_status",
                tool_arguments={"focus": focus},
                request_type_hint="direct_deterministic_fact",
                family="power",
                subject="power",
                requested_metric=focus,
                confidence=0.95,
                evidence=["power status phrasing detected"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        if self._looks_like_network_throughput(lower):
            metric = self._network_throughput_metric(lower)
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_METRIC,
                domain="network",
                tool_name="network_throughput",
                tool_arguments={"metric": metric, "present_in": present_in},
                request_type_hint="direct_deterministic_fact",
                family="network",
                subject="throughput",
                requested_metric=metric,
                timescale="now",
                output_type="numeric",
                confidence=0.95,
                evidence=["network throughput phrasing detected"],
                execution_type="run_measurement",
                output_mode=ResponseMode.NUMERIC_METRIC.value,
            )
        if any(token in lower for token in {"unstable today", "earlier", "lately", "recently"}) and any(
            token in lower for token in {"wi-fi", "wifi", "internet", "network", "connection"}
        ) and any(token in lower for token in {"unstable", "drop", "dropped", "skipping", "choppy", "disconnect"}):
            return self._tool_proposal(
                query_shape=QueryShape.HISTORY_TREND,
                domain="network",
                tool_name="network_diagnosis",
                tool_arguments={"focus": "history", "diagnostic_burst": False},
                request_type_hint="deterministic_diagnostic_request",
                family="network_diagnosis",
                subject="network_history",
                requested_metric="stability",
                timescale="today" if "today" in lower else "recent",
                output_type="summary",
                diagnostic_mode=True,
                confidence=0.94,
                evidence=["network history phrasing detected"],
                execution_type="analyze_history",
                output_mode=ResponseMode.HISTORY_SUMMARY.value,
            )
        if self._looks_like_network_diagnosis(lower):
            return self._tool_proposal(
                query_shape=QueryShape.DIAGNOSTIC_CAUSAL,
                domain="network",
                tool_name="network_diagnosis",
                tool_arguments={"focus": self._network_focus(lower, previous="overview"), "diagnostic_burst": True},
                request_type_hint="deterministic_diagnostic_request",
                family="network_diagnosis",
                subject="network_diagnosis",
                requested_metric="stability",
                output_type="summary",
                diagnostic_mode=True,
                confidence=0.95,
                evidence=["network diagnosis phrasing detected"],
                execution_type="diagnose_from_telemetry",
                output_mode=ResponseMode.DIAGNOSTIC_SUMMARY.value,
            )
        if any(phrase in lower for phrase in {"am i connected", "are we connected", "what network am i on", "what is my ip", "what's my ip", "my ip", "ip address", "wifi signal", "wi-fi signal", "signal strength", "rssi"}) or self._looks_like_network_status(lower):
            focus = self._network_status_focus(lower)
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="network",
                tool_name="network_status",
                tool_arguments={"focus": focus},
                request_type_hint="direct_deterministic_fact",
                family="network",
                subject="network",
                requested_metric=focus,
                confidence=0.95,
                evidence=["network status phrasing detected"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        if self._looks_like_resource_diagnosis(lower):
            return self._tool_proposal(
                query_shape=QueryShape.DIAGNOSTIC_CAUSAL,
                domain="system",
                tool_name="resource_diagnosis",
                tool_arguments={},
                request_type_hint="deterministic_diagnostic_request",
                family="resource_diagnosis",
                subject="resource_diagnosis",
                requested_metric="bottleneck",
                diagnostic_mode=True,
                confidence=0.95,
                evidence=["machine slowdown diagnosis phrasing detected"],
                execution_type="diagnose_from_telemetry",
                output_mode=ResponseMode.DIAGNOSTIC_SUMMARY.value,
            )
        resource_query_kind = self._resource_query_kind(lower, recent_family=recent_family)
        if resource_query_kind is not None:
            focus = self._resource_focus(lower)
            metric = self._resource_metric(lower, focus=focus, query_kind=resource_query_kind)
            query_shape = QueryShape.CURRENT_METRIC
            output_mode = ResponseMode.NUMERIC_METRIC.value
            output_type = "numeric"
            request_type_hint = "direct_deterministic_fact"
            diagnostic_mode = False
            if resource_query_kind == "identity":
                query_shape = QueryShape.IDENTITY_LOOKUP
                output_mode = ResponseMode.IDENTITY_SUMMARY.value
                output_type = "identity"
            elif resource_query_kind == "diagnostic":
                query_shape = QueryShape.DIAGNOSTIC_CAUSAL
                output_mode = ResponseMode.DIAGNOSTIC_SUMMARY.value
                output_type = "interpreted"
                request_type_hint = "deterministic_diagnostic_request"
                diagnostic_mode = True
            domain = focus if focus in {"gpu", "cpu", "ram"} else "system"
            return self._tool_proposal(
                query_shape=query_shape,
                domain=domain,
                tool_name="resource_status",
                tool_arguments={"focus": focus, "query_kind": resource_query_kind, "metric": metric},
                request_type_hint=request_type_hint,
                family="resource",
                subject=focus,
                requested_metric=metric,
                timescale="now" if query_shape == QueryShape.CURRENT_METRIC else None,
                output_type=output_type,
                diagnostic_mode=diagnostic_mode,
                confidence=0.95,
                evidence=["resource query phrasing detected"],
                execution_type="retrieve_identity" if query_shape == QueryShape.IDENTITY_LOOKUP else "diagnose_from_telemetry" if diagnostic_mode else "retrieve_live_metric",
                output_mode=output_mode,
            )
        if any(token in lower for token in {"running apps", "open apps", "what is open"}) and not self._looks_like_application_concept_prompt(lower):
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="applications",
                tool_name="active_apps",
                tool_arguments={},
                request_type_hint="direct_deterministic_fact",
                family="active_apps",
                subject="active_apps",
                requested_metric="applications",
                confidence=0.94,
                evidence=["active apps phrasing detected"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        if self._looks_like_active_apps_status(lower):
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="applications",
                tool_name="active_apps",
                tool_arguments={},
                request_type_hint="direct_deterministic_fact",
                family="active_apps",
                subject="active_apps",
                requested_metric="applications",
                confidence=0.94,
                evidence=["active-apps status phrasing detected"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        if self._looks_like_window_status(lower):
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="windows",
                tool_name="window_status",
                tool_arguments={},
                request_type_hint="direct_deterministic_fact",
                family="window_control",
                subject="windows",
                requested_metric="open_windows",
                confidence=0.94,
                evidence=["window status phrasing detected"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        if any(token in lower for token in {"recent files", "recent documents", "what was i working on"}):
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="files",
                tool_name="recent_files",
                tool_arguments={},
                request_type_hint="direct_deterministic_fact",
                family="recent_files",
                subject="recent_files",
                requested_metric="recent_files",
                confidence=0.94,
                evidence=["recent-files phrasing detected"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        if self._looks_like_storage_diagnosis(lower):
            return self._tool_proposal(
                query_shape=QueryShape.DIAGNOSTIC_CAUSAL,
                domain="storage",
                tool_name="storage_diagnosis",
                tool_arguments={},
                request_type_hint="deterministic_diagnostic_request",
                family="storage_diagnosis",
                subject="storage_diagnosis",
                requested_metric="capacity_pressure",
                diagnostic_mode=True,
                confidence=0.94,
                evidence=["storage diagnosis phrasing detected"],
                execution_type="diagnose_from_telemetry",
                output_mode=ResponseMode.DIAGNOSTIC_SUMMARY.value,
            )
        if self._looks_like_storage_status(lower):
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="storage",
                tool_name="storage_status",
                tool_arguments={},
                request_type_hint="direct_deterministic_fact",
                family="storage",
                subject="storage",
                requested_metric="storage",
                confidence=0.94,
                evidence=["storage status phrasing detected"],
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        if self._looks_like_machine(lower):
            focus = "time" if "timezone" in lower or "time zone" in lower else "identity"
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS if focus == "time" else QueryShape.IDENTITY_LOOKUP,
                domain="machine",
                tool_name="machine_status",
                tool_arguments={"focus": focus},
                request_type_hint="direct_deterministic_fact",
                family="machine",
                subject="machine",
                requested_metric=focus,
                confidence=0.94,
                evidence=["machine status phrasing detected"],
                execution_type="retrieve_current_status" if focus == "time" else "retrieve_identity",
                output_mode=ResponseMode.STATUS_SUMMARY.value if focus == "time" else ResponseMode.IDENTITY_SUMMARY.value,
            )
        if self._looks_like_system_overview(lower):
            return self._tool_proposal(
                query_shape=QueryShape.SUMMARY_REQUEST,
                domain="system",
                request_type_hint="mixed_command_explanation",
                family="system_overview",
                subject="system_overview",
                requested_action="summarize_system",
                confidence=0.8,
                evidence=["system-overview phrasing detected"],
                execution_type="summarize_activity",
                output_mode=ResponseMode.SUMMARY_RESULT.value,
                slots={"requires_reasoner": True},
            )
        if self._looks_like_unsupported_external_commitment(lower):
            return self._tool_proposal(
                query_shape=QueryShape.SUMMARY_REQUEST,
                domain="unsupported",
                request_type_hint="unsupported_capability",
                family="unsupported",
                subject="external_commitment",
                requested_action="decline_unsupported_external_commitment",
                confidence=0.96,
                evidence=["unsupported external commitment or payment request detected"],
                assistant_message=(
                    "I can't book, purchase, pay for, or commit to real-world transactions from this command surface. "
                    "I can help you draft a plan or checklist instead."
                ),
                execution_type="decline_unsupported_request",
                output_mode=ResponseMode.UNSUPPORTED.value,
            )
        return SemanticParseProposal(
            query_shape=QueryShape.UNCLASSIFIED,
            confidence=0.0,
            evidence=["no structured query shape matched"],
            fallback_path="unclassified",
        )

    def _proposal_from_classification(
        self,
        classification: RequestClassification,
        *,
        message: str,
        lower: str,
        follow_up: bool,
    ) -> SemanticParseProposal:
        del message
        if classification.family == "weather":
            return self._tool_proposal(
                query_shape=QueryShape.FORECAST_REQUEST if classification.forecast_target != "current" else QueryShape.CURRENT_STATUS,
                domain="weather",
                tool_name="weather_current",
                tool_arguments={
                    "open_target": classification.open_target,
                    "location_mode": classification.location_mode,
                    "named_location": classification.named_location,
                    "named_location_type": classification.named_location_type,
                    "allow_home_fallback": classification.allow_home_fallback,
                    "forecast_target": classification.forecast_target,
                },
                request_type_hint=classification.request_type,
                family="weather",
                subject="weather",
                requested_metric="forecast" if classification.forecast_target != "current" else "current_conditions",
                timescale="now" if classification.forecast_target == "current" else classification.forecast_target,
                output_type="summary",
                confidence=0.94,
                evidence=["follow-up classification grounded weather routing"],
                follow_up=follow_up,
                execution_type="retrieve_forecast" if classification.forecast_target != "current" else "retrieve_current_status",
                output_mode=ResponseMode.FORECAST_SUMMARY.value,
            )
        if classification.family == "power":
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="power",
                tool_name="power_status",
                tool_arguments={"focus": classification.focus},
                request_type_hint=classification.request_type,
                family="power",
                subject="power",
                requested_metric=classification.focus,
                confidence=0.94,
                evidence=["follow-up classification grounded power status"],
                follow_up=follow_up,
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        if classification.family == "power_projection":
            return self._tool_proposal(
                query_shape=QueryShape.FORECAST_REQUEST,
                domain="power",
                tool_name="power_projection",
                tool_arguments={
                    "metric": classification.metric,
                    "target_percent": classification.target_percent,
                    "assume_unplugged": classification.assume_unplugged,
                },
                request_type_hint=classification.request_type,
                family="power",
                subject="power_projection",
                requested_metric=classification.metric,
                output_type="summary",
                confidence=0.94,
                evidence=["follow-up classification grounded power projection"],
                follow_up=follow_up,
                execution_type="project_power_state",
                output_mode=ResponseMode.FORECAST_SUMMARY.value,
            )
        if classification.family == "network_diagnosis":
            focus = classification.focus or self._network_focus(lower, previous="overview")
            query_shape = QueryShape.HISTORY_TREND if focus == "history" else QueryShape.DIAGNOSTIC_CAUSAL
            output_mode = ResponseMode.HISTORY_SUMMARY.value if query_shape == QueryShape.HISTORY_TREND else ResponseMode.DIAGNOSTIC_SUMMARY.value
            return self._tool_proposal(
                query_shape=query_shape,
                domain="network",
                tool_name="network_diagnosis",
                tool_arguments={"focus": focus, "diagnostic_burst": True},
                request_type_hint=classification.request_type,
                family="network_diagnosis",
                subject="network_diagnosis",
                requested_metric="stability",
                timescale="today" if focus == "history" else None,
                output_type="summary",
                diagnostic_mode=True,
                confidence=0.94,
                evidence=["follow-up classification grounded network diagnosis"],
                follow_up=follow_up,
                execution_type="analyze_history" if query_shape == QueryShape.HISTORY_TREND else "diagnose_from_telemetry",
                output_mode=output_mode,
            )
        if classification.family == "network":
            return self._tool_proposal(
                query_shape=QueryShape.CURRENT_STATUS,
                domain="network",
                tool_name="network_status",
                tool_arguments={"focus": classification.focus, "present_in": classification.present_in},
                request_type_hint=classification.request_type,
                family="network",
                subject="network",
                requested_metric=classification.focus,
                confidence=0.94,
                evidence=["classification grounded network status routing"],
                follow_up=follow_up,
                execution_type="retrieve_current_status",
                output_mode=ResponseMode.STATUS_SUMMARY.value,
            )
        return self._tool_proposal(
            query_shape=QueryShape.UNCLASSIFIED,
            domain=classification.family,
            request_type_hint=classification.request_type,
            family=classification.family,
            subject=classification.family,
            confidence=0.2,
            evidence=["legacy follow-up classification required an unclassified compatibility fallback"],
            follow_up=follow_up,
            fallback_path="legacy_follow_up",
        )

    def _validate_structured_query(
        self,
        semantic: SemanticParseProposal,
        *,
        normalized: NormalizedCommand,
        active_context: dict[str, Any],
    ) -> tuple[StructuredQuery, ClarificationReason | None]:
        slots = dict(semantic.slots)
        query_shape = semantic.query_shape
        domain = semantic.domain
        requested_metric = semantic.requested_metric
        requested_action = semantic.requested_action
        timescale = str(slots.get("timescale") or "").strip() or None
        target_scope = str(slots.get("target_scope") or domain or "").strip() or None
        output_mode = str(slots.get("output_mode") or "").strip() or None
        execution_type = str(slots.get("execution_type") or "").strip() or None
        output_type = str(slots.get("output_type") or "").strip() or None
        diagnostic_mode = bool(slots.get("diagnostic_mode", False))
        comparison_target = str(slots.get("comparison_target") or "").strip() or None
        current_context_reference = str(slots.get("current_context_reference") or "").strip() or None
        if not current_context_reference:
            if isinstance(active_context.get("selection"), dict) and active_context["selection"].get("value"):
                current_context_reference = "selection"
            elif isinstance(active_context.get("clipboard"), dict) and active_context["clipboard"].get("value"):
                current_context_reference = "clipboard"

        if query_shape == QueryShape.CURRENT_METRIC:
            timescale = timescale or "now"
            output_mode = output_mode or ResponseMode.NUMERIC_METRIC.value
            output_type = output_type or "numeric"
            if execution_type is None:
                execution_type = "run_measurement" if domain == "network" and requested_metric in {"internet_speed", "download_speed", "upload_speed"} else "retrieve_live_metric"
        elif query_shape == QueryShape.CURRENT_STATUS:
            output_mode = output_mode or ResponseMode.STATUS_SUMMARY.value
            output_type = output_type or "summary"
            execution_type = execution_type or "retrieve_current_status"
        elif query_shape == QueryShape.DIAGNOSTIC_CAUSAL:
            output_mode = output_mode or ResponseMode.DIAGNOSTIC_SUMMARY.value
            output_type = output_type or "summary"
            diagnostic_mode = True
            execution_type = execution_type or "diagnose_from_telemetry"
        elif query_shape == QueryShape.HISTORY_TREND:
            output_mode = output_mode or ResponseMode.HISTORY_SUMMARY.value
            output_type = output_type or "summary"
            diagnostic_mode = True
            timescale = timescale or "recent"
            execution_type = execution_type or "analyze_history"
        elif query_shape == QueryShape.IDENTITY_LOOKUP:
            output_mode = output_mode or ResponseMode.IDENTITY_SUMMARY.value
            output_type = output_type or "identity"
            execution_type = execution_type or "retrieve_identity"
        elif query_shape == QueryShape.CALCULATION_REQUEST:
            output_mode = output_mode or ResponseMode.CALCULATION_RESULT.value
            output_type = output_type or "numeric"
            execution_type = execution_type or "deterministic_local_expression"
        elif query_shape == QueryShape.SCREEN_AWARENESS_REQUEST:
            output_mode = output_mode or ResponseMode.SUMMARY_RESULT.value
            output_type = output_type or "screen_analysis"
            execution_type = execution_type or "screen_awareness_analyze"
        elif query_shape == QueryShape.CAMERA_AWARENESS_REQUEST:
            output_mode = output_mode or ResponseMode.CLARIFICATION.value
            output_type = output_type or "camera_awareness"
            execution_type = execution_type or "camera_awareness_c0_mock_or_permission_gate"
        elif query_shape == QueryShape.DISCORD_RELAY_REQUEST:
            output_mode = output_mode or ResponseMode.ACTION_RESULT.value
            output_type = output_type or "action"
            execution_type = execution_type or "discord_relay_preview"
        elif query_shape == QueryShape.WEB_RETRIEVAL_REQUEST:
            output_mode = output_mode or ResponseMode.WEB_EVIDENCE_RESULT.value
            output_type = output_type or "web_evidence"
            execution_type = execution_type or "web_retrieval_extract"
        elif query_shape == QueryShape.TRUST_APPROVAL_REQUEST:
            output_mode = output_mode or ResponseMode.SUMMARY_RESULT.value
            output_type = output_type or "trust"
            execution_type = execution_type or "explain_approval"
        elif query_shape == QueryShape.CONTROL_COMMAND:
            output_mode = output_mode or ResponseMode.ACTION_RESULT.value
            output_type = output_type or "action"
            execution_type = execution_type or "execute_control_command"
        elif query_shape == QueryShape.OPEN_BROWSER_DESTINATION:
            output_mode = output_mode or ResponseMode.ACTION_RESULT.value
            output_type = output_type or "action"
            execution_type = execution_type or "resolve_url_then_open_in_browser"
        elif query_shape == QueryShape.SEARCH_BROWSER_DESTINATION:
            output_mode = output_mode or ResponseMode.ACTION_RESULT.value
            output_type = output_type or "action"
            execution_type = execution_type or "resolve_search_url_then_open_in_browser"
        elif query_shape == QueryShape.REPAIR_REQUEST:
            output_mode = output_mode or ResponseMode.ACTION_RESULT.value
            output_type = output_type or "action"
            execution_type = execution_type or "execute_repair"
        elif query_shape in {QueryShape.SEARCH_REQUEST, QueryShape.SEARCH_AND_OPEN}:
            output_mode = output_mode or ResponseMode.SEARCH_RESULT.value
            output_type = output_type or "search_result"
            execution_type = execution_type or ("search_then_open" if query_shape == QueryShape.SEARCH_AND_OPEN else "search_desktop")
        elif query_shape == QueryShape.WORKSPACE_REQUEST:
            output_mode = output_mode or ResponseMode.WORKSPACE_RESULT.value
            output_type = output_type or "workspace"
            execution_type = execution_type or "assemble_workspace"
        elif query_shape == QueryShape.WORKFLOW_REQUEST:
            output_mode = output_mode or ResponseMode.ACTION_RESULT.value
            output_type = output_type or "action"
            execution_type = execution_type or "execute_workflow"
        elif query_shape == QueryShape.SUMMARY_REQUEST:
            output_mode = output_mode or ResponseMode.SUMMARY_RESULT.value
            output_type = output_type or "summary"
            execution_type = execution_type or "summarize_activity"
        elif query_shape == QueryShape.COMPARISON_REQUEST:
            output_mode = output_mode or ResponseMode.SUMMARY_RESULT.value
            output_type = output_type or "comparison"
            execution_type = execution_type or "compare_items"
        elif query_shape == QueryShape.FORECAST_REQUEST:
            output_mode = output_mode or ResponseMode.FORECAST_SUMMARY.value
            output_type = output_type or "summary"
            execution_type = execution_type or "retrieve_forecast"
        elif query_shape in {QueryShape.BROWSER_CONTEXT, QueryShape.CONTEXT_ACTION, QueryShape.ROUTINE_REQUEST, QueryShape.MAINTENANCE_REQUEST, QueryShape.FILE_OPERATION}:
            output_mode = output_mode or ResponseMode.ACTION_RESULT.value
            output_type = output_type or "action"
            execution_type = execution_type or "execute_control_command"

        capability_requirements: list[str] = []
        if query_shape == QueryShape.CURRENT_METRIC:
            capability_requirements.append("throughput_measurement" if execution_type == "run_measurement" else "live_telemetry")
        elif query_shape == QueryShape.CURRENT_STATUS:
            capability_requirements.append("status_fetch")
        elif query_shape == QueryShape.CALCULATION_REQUEST:
            capability_requirements.append("local_calculation")
        elif query_shape == QueryShape.IDENTITY_LOOKUP:
            capability_requirements.append("identity_lookup")
        elif query_shape == QueryShape.SCREEN_AWARENESS_REQUEST:
            capability_requirements.extend(["screen_observation", "screen_interpretation"])
        elif query_shape == QueryShape.CAMERA_AWARENESS_REQUEST:
            capability_requirements.extend(
                ["camera_awareness_c0", "camera_user_confirmation", "mock_camera_capture"]
            )
        elif query_shape == QueryShape.DISCORD_RELAY_REQUEST:
            capability_requirements.append("discord_relay")
        elif query_shape == QueryShape.WEB_RETRIEVAL_REQUEST:
            capability_requirements.append("public_web_retrieval")
        elif query_shape == QueryShape.TRUST_APPROVAL_REQUEST:
            capability_requirements.append("trust_state")
        elif query_shape == QueryShape.DIAGNOSTIC_CAUSAL:
            capability_requirements.append("diagnostic_telemetry")
        elif query_shape == QueryShape.HISTORY_TREND:
            capability_requirements.append("history_telemetry")
        elif query_shape in {QueryShape.OPEN_BROWSER_DESTINATION, QueryShape.SEARCH_BROWSER_DESTINATION}:
            capability_requirements.append("browser_open")
        elif query_shape in {QueryShape.CONTROL_COMMAND, QueryShape.REPAIR_REQUEST, QueryShape.WORKFLOW_REQUEST, QueryShape.ROUTINE_REQUEST, QueryShape.MAINTENANCE_REQUEST, QueryShape.FILE_OPERATION, QueryShape.CONTEXT_ACTION}:
            capability_requirements.append("action_execution")
        elif query_shape in {QueryShape.SEARCH_REQUEST, QueryShape.SEARCH_AND_OPEN}:
            capability_requirements.append("desktop_search")
        elif query_shape == QueryShape.WORKSPACE_REQUEST:
            capability_requirements.append("workspace_management")
        elif query_shape in {QueryShape.SUMMARY_REQUEST, QueryShape.COMPARISON_REQUEST, QueryShape.FORECAST_REQUEST, QueryShape.BROWSER_CONTEXT}:
            capability_requirements.append("structured_summary")

        structured_query = StructuredQuery(
            domain=domain,
            query_shape=query_shape,
            requested_metric=requested_metric,
            requested_action=requested_action,
            timescale=timescale,
            target_scope=target_scope,
            output_mode=output_mode,
            execution_type=execution_type,
            capability_requirements=capability_requirements,
            confidence=semantic.confidence,
            diagnostic_mode=diagnostic_mode,
            output_type=output_type,
            comparison_target=comparison_target,
            current_context_reference=current_context_reference,
            slots=slots,
        )

        clarification_payload = slots.get("clarification") if isinstance(slots.get("clarification"), dict) else {}
        if clarification_payload:
            return structured_query, ClarificationReason(
                code=str(clarification_payload.get("code") or "route_target_ambiguous"),
                message=str(clarification_payload.get("message") or "Which target should I use?"),
                missing_slots=list(clarification_payload.get("missing_slots") or ["target"]),
            )
        if query_shape == QueryShape.COMPARISON_REQUEST and (
            comparison_target is None
            or comparison_target in {"these two files", "these files", "those files", "these", "those", "this", "that"}
        ):
            return structured_query, ClarificationReason(
                code="missing_comparison_targets",
                message="Which two files should I compare?",
                missing_slots=["left_target", "right_target"],
            )
        if query_shape == QueryShape.WORKSPACE_REQUEST and requested_action == "rename":
            tool_arguments = slots.get("tool_arguments") if isinstance(slots.get("tool_arguments"), dict) else {}
            if not str(tool_arguments.get("new_name") or "").strip():
                return structured_query, ClarificationReason(
                    code="missing_workspace_name",
                    message="What should I rename the workspace to?",
                    missing_slots=["new_name"],
                )
        if query_shape == QueryShape.WORKSPACE_REQUEST and requested_action == "tag":
            tool_arguments = slots.get("tool_arguments") if isinstance(slots.get("tool_arguments"), dict) else {}
            if not isinstance(tool_arguments.get("tags"), list) or not tool_arguments.get("tags"):
                return structured_query, ClarificationReason(
                    code="missing_workspace_tags",
                    message="What tags should I add to the workspace?",
                    missing_slots=["tags"],
                )
        if query_shape == QueryShape.UNCLASSIFIED and normalized.normalized_text:
            structured_query.confidence = 0.0
        return structured_query, None

    def _plan_capabilities(
        self,
        structured_query: StructuredQuery,
        *,
        available_tools: set[str],
    ) -> CapabilityPlan:
        slots = structured_query.slots if isinstance(structured_query.slots, dict) else {}
        tool_name = str(slots.get("tool_name") or "").strip() or None
        required_tools: list[str] = [tool_name] if tool_name else []
        required_capabilities = list(structured_query.capability_requirements)
        missing_capabilities: list[str] = []
        notes: list[str] = []
        freshness_expectation = None
        adapter_fields = self._adapter_capability_fields(structured_query)
        if structured_query.query_shape == QueryShape.CURRENT_METRIC:
            freshness_expectation = "live"
        elif structured_query.query_shape == QueryShape.HISTORY_TREND:
            freshness_expectation = "recent_history"
        elif structured_query.query_shape == QueryShape.CURRENT_STATUS:
            freshness_expectation = "current"
        elif structured_query.query_shape == QueryShape.SCREEN_AWARENESS_REQUEST:
            freshness_expectation = "current"
        elif structured_query.query_shape == QueryShape.SOFTWARE_CONTROL_REQUEST:
            freshness_expectation = "current"
        elif structured_query.query_shape == QueryShape.DISCORD_RELAY_REQUEST:
            freshness_expectation = "current"
        elif structured_query.query_shape == QueryShape.WEB_RETRIEVAL_REQUEST:
            freshness_expectation = "public_snapshot"
        elif structured_query.query_shape == QueryShape.TRUST_APPROVAL_REQUEST:
            freshness_expectation = "current"
        elif structured_query.query_shape in {QueryShape.CONTROL_COMMAND, QueryShape.REPAIR_REQUEST}:
            freshness_expectation = "immediate"

        if structured_query.query_shape == QueryShape.SOFTWARE_CONTROL_REQUEST:
            software_config = self._software_control_seam.config
            if software_config.enabled and software_config.planner_routing_enabled:
                return CapabilityPlan(
                    supported=True,
                    available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
                    required_tools=[],
                    required_capabilities=required_capabilities,
                    missing_capabilities=[],
                    **adapter_fields,
                    freshness_expectation=freshness_expectation,
                    unsupported_reason=None,
                    notes=[
                        "Software control stays native, typed, and local-first.",
                        "Verification and recovery remain separate checkpoints instead of being folded into a vague success state.",
                    ],
                )
            return CapabilityPlan(
                supported=False,
                available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
                required_tools=[],
                required_capabilities=required_capabilities,
                missing_capabilities=["software_control"],
                **adapter_fields,
                freshness_expectation=freshness_expectation,
                unsupported_reason=UnsupportedReason(
                    code="software_control_unavailable",
                    message="Software control isn't available in the current environment.",
                ),
                notes=["The planner recognized a software lifecycle request, but the native software-control runtime is disabled."],
            )

        if structured_query.query_shape == QueryShape.SCREEN_AWARENESS_REQUEST:
            screen_config = self._screen_awareness_seam.config
            ready_for_phase1 = (
                screen_config.enabled
                and screen_config.planner_routing_enabled
                and screen_config.observation_enabled
                and screen_config.interpretation_enabled
                and screen_config.phase != "phase0"
            )
            if ready_for_phase1:
                screen_debug = slots.get("screen_awareness") if isinstance(slots.get("screen_awareness"), dict) else {}
                disposition = str(screen_debug.get("disposition") or "").strip()
                requested_screen_action = str(structured_query.requested_action or "").strip()
                if screen_config.phase in {"phase2", "phase3", "phase4", "phase5", "phase6", "phase7", "phase8", "phase9", "phase10", "phase11", "phase12"} and screen_config.grounding_enabled and "screen_grounding" not in required_capabilities:
                    required_capabilities.append("screen_grounding")
                if disposition == "phase3_guide" and screen_config.guidance_enabled and "screen_guidance" not in required_capabilities:
                    required_capabilities.append("screen_guidance")
                if disposition == "phase4_verify" and screen_config.verification_enabled and "screen_verification" not in required_capabilities:
                    required_capabilities.append("screen_verification")
                if disposition == "phase5_act":
                    if screen_config.verification_enabled and "screen_verification" not in required_capabilities:
                        required_capabilities.append("screen_verification")
                    if screen_config.action_enabled and "screen_action_execution" not in required_capabilities:
                        required_capabilities.append("screen_action_execution")
                if disposition == "phase6_continue":
                    if screen_config.guidance_enabled and "screen_guidance" not in required_capabilities:
                        required_capabilities.append("screen_guidance")
                    if screen_config.verification_enabled and "screen_verification" not in required_capabilities:
                        required_capabilities.append("screen_verification")
                    if screen_config.memory_enabled and "screen_continuity" not in required_capabilities:
                        required_capabilities.append("screen_continuity")
                if disposition == "phase9_workflow_reuse":
                    if screen_config.capability_flags().get("workflow_learning_enabled") and "screen_workflow_learning" not in required_capabilities:
                        required_capabilities.append("screen_workflow_learning")
                    if screen_config.verification_enabled and "screen_verification" not in required_capabilities:
                        required_capabilities.append("screen_verification")
                    if screen_config.action_enabled and "screen_action_execution" not in required_capabilities:
                        required_capabilities.append("screen_action_execution")
                if disposition == "phase10_brain_integration":
                    if screen_config.capability_flags().get("workflow_learning_enabled") and "screen_workflow_learning" not in required_capabilities:
                        required_capabilities.append("screen_workflow_learning")
                    if screen_config.capability_flags().get("brain_integration_enabled") and "screen_brain_integration" not in required_capabilities:
                        required_capabilities.append("screen_brain_integration")
                if disposition == "phase11_power":
                    if screen_config.capability_flags().get("power_features_enabled") and "screen_power_features" not in required_capabilities:
                        required_capabilities.append("screen_power_features")
                if (
                    screen_config.capability_flags().get("problem_solving_enabled")
                    and (
                        disposition == "phase8_problem_solve"
                        or requested_screen_action in {"explain_visible_content", "solve_visible_problem"}
                    )
                ):
                    if "screen_problem_solving" not in required_capabilities:
                        required_capabilities.append("screen_problem_solving")
                return CapabilityPlan(
                    supported=True,
                    available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
                    required_tools=[],
                    required_capabilities=required_capabilities,
                    missing_capabilities=[],
                    **adapter_fields,
                    freshness_expectation=freshness_expectation,
                    unsupported_reason=None,
                    notes=[
                        "Screen awareness uses layered native observation first and augments later only when needed.",
                        "Phase 2 grounds referential requests only when evidence supports a truthful winner.",
                        "Phase 3 guided navigation builds on the existing grounded state rather than replacing it.",
                        "Phase 4 verification compares the current bearing to explicit expectations and any available prior screen state.",
                        "Phase 5 action execution reuses grounded targets and Phase 4 verification instead of treating attempts as success.",
                        "Phase 6 workflow continuity reuses recent grounded, guided, verified, and action bearings without pretending long-term memory.",
                        "Phase 7 adapters contribute semantic app context only when those semantics are fresh, supported, and stronger than the generic fallback.",
                        "Phase 8 problem solving keeps observed evidence, inferred interpretation, and general knowledge explicitly separated.",
                        "Phase 9 workflow learning stores bounded, inspectable workflow records and reuses them only through the existing grounding, verification, and action gates.",
                        "Phase 10 brain integration binds recent workflow and session evidence into bounded memory candidates without pretending long-term certainty.",
                        "Phase 11 power features add multi-monitor, accessibility, overlays, translation, extraction, notifications, and workspace breadth without replacing the earlier layers.",
                    ],
                )
            missing_capabilities.append("screen_observation")
            unsupported_contract = slots.get("unsupported_response_contract")
            unsupported_message = "Screen bearings aren't available in the current phase yet."
            if isinstance(unsupported_contract, dict):
                unsupported_message = str(unsupported_contract.get("full_response") or unsupported_message)
            return CapabilityPlan(
                supported=False,
                available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
                required_tools=[],
                required_capabilities=required_capabilities,
                missing_capabilities=missing_capabilities,
                **adapter_fields,
                freshness_expectation=freshness_expectation,
                unsupported_reason=UnsupportedReason(
                    code=str(slots.get("unsupported_reason_code") or "screen_awareness_observation_unavailable"),
                    message=unsupported_message,
                ),
                notes=[
                    "The screen-awareness planner route exists, but the runtime is not configured for live observation and interpretation.",
                ],
            )

        if structured_query.query_shape == QueryShape.CAMERA_AWARENESS_REQUEST:
            return CapabilityPlan(
                supported=True,
                available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
                required_tools=[],
                required_capabilities=required_capabilities,
                missing_capabilities=[],
                **adapter_fields,
                freshness_expectation="current",
                unsupported_reason=None,
                notes=[
                    "Camera awareness C0 is planner-routed but permission-gated before capture.",
                    "Only mock capture and mock vision are claimable in C0.",
                    "No real camera, background capture, image persistence, or cloud vision route is exposed.",
                ],
            )

        if structured_query.query_shape == QueryShape.DISCORD_RELAY_REQUEST:
            relay_config = self._discord_relay_config
            if relay_config.enabled and relay_config.planner_routing_enabled:
                return CapabilityPlan(
                    supported=True,
                    available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
                    required_tools=[],
                    required_capabilities=required_capabilities,
                    missing_capabilities=[],
                    **adapter_fields,
                    freshness_expectation=freshness_expectation,
                    unsupported_reason=None,
                    notes=[
                        "Discord relay stays planner-routed, backend-owned, and adapter-backed.",
                        "Preview remains mandatory before any DM send attempt.",
                        "Screen awareness is used only to break payload ties when native context is insufficient.",
                    ],
                )
            return CapabilityPlan(
                supported=False,
                available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
                required_tools=[],
                required_capabilities=required_capabilities,
                missing_capabilities=["discord_relay"],
                **adapter_fields,
                freshness_expectation=freshness_expectation,
                unsupported_reason=UnsupportedReason(
                    code="discord_relay_unavailable",
                    message="Discord relay isn't available in the current environment.",
                ),
                notes=["The planner recognized a Discord relay request, but the relay runtime is disabled."],
            )

        if structured_query.query_shape == QueryShape.COMPARISON_REQUEST and not tool_name:
            missing_capabilities.append("file_comparison")
            return CapabilityPlan(
                supported=False,
                available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
                required_tools=[],
                required_capabilities=required_capabilities,
                missing_capabilities=missing_capabilities,
                **adapter_fields,
                freshness_expectation=freshness_expectation,
                unsupported_reason=UnsupportedReason(
                    code="comparison_capability_unavailable",
                    message="Deterministic file comparison isn't available in the current execution path yet.",
                ),
                notes=["The planner can classify comparison requests before a comparison executor exists."],
            )

        if tool_name is not None and tool_name not in available_tools:
            missing_capabilities.append(tool_name)
            unsupported_code = "tool_unavailable"
            unsupported_message = f"{tool_name} isn't available in the current environment."
            if structured_query.query_shape in {QueryShape.OPEN_BROWSER_DESTINATION, QueryShape.SEARCH_BROWSER_DESTINATION}:
                unsupported_code = "browser_opening_unavailable"
                unsupported_message = "Browser opening isn't available in the current environment."
            return CapabilityPlan(
                supported=False,
                available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
                required_tools=required_tools,
                required_capabilities=required_capabilities,
                missing_capabilities=missing_capabilities,
                **adapter_fields,
                freshness_expectation=freshness_expectation,
                unsupported_reason=UnsupportedReason(
                    code=unsupported_code,
                    message=unsupported_message,
                ),
                notes=["The planner selected a deterministic route whose tool is disabled or unavailable."],
            )

        if adapter_fields.get("adapter_contract_status") == "invalid":
            missing_capabilities.append("adapter_contract")
            return CapabilityPlan(
                supported=False,
                available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
                required_tools=required_tools,
                required_capabilities=required_capabilities,
                missing_capabilities=missing_capabilities,
                **adapter_fields,
                freshness_expectation=freshness_expectation,
                unsupported_reason=UnsupportedReason(
                    code="adapter_contract_unavailable",
                    message="This route isn't available because it is not valid contract-backed adapter work.",
                ),
                notes=list(adapter_fields.get("adapter_contract_errors") or [])
                or ["The planner refused a route that could not prove valid adapter contract backing."],
            )

        if tool_name is None and not slots.get("assistant_message"):
            notes.append("No deterministic tool is required for this structured query.")
        return CapabilityPlan(
            supported=True,
            available_tools=sorted(tool for tool in available_tools if tool in DEFAULT_AVAILABLE_TOOLS),
            required_tools=required_tools,
            required_capabilities=required_capabilities,
            missing_capabilities=[],
            **adapter_fields,
            freshness_expectation=freshness_expectation,
            unsupported_reason=None,
            notes=notes,
        )

    def _adapter_capability_fields(self, structured_query: StructuredQuery) -> dict[str, Any]:
        assessment = self._adapter_contract_assessment(structured_query)
        candidate_contracts = list(assessment.candidate_contracts)
        selected_contract = assessment.selected_contract
        approval_required: bool | None = None
        preview_available: bool | None = None
        rollback_available: bool | None = None
        max_claimable_outcome: str | None = None
        if selected_contract is not None:
            approval_required = selected_contract.approval.required
            preview_available = selected_contract.preview_available()
            rollback_available = selected_contract.rollback.supported
            max_claimable_outcome = selected_contract.verification.max_claimable_outcome.value
        elif candidate_contracts:
            approval_required = any(contract.approval.required for contract in candidate_contracts)
            preview_available = any(contract.preview_available() for contract in candidate_contracts)
            rollback_available = any(contract.rollback.supported for contract in candidate_contracts)
        adapter_contract_status = "unbound"
        if assessment.contract_required:
            adapter_contract_status = "healthy" if assessment.healthy else "invalid"
        elif candidate_contracts:
            adapter_contract_status = "candidate_set"
        return {
            "candidate_adapters": [contract.planner_view() for contract in candidate_contracts],
            "selected_adapter": selected_contract.planner_view() if selected_contract is not None else None,
            "adapter_contract_status": adapter_contract_status,
            "adapter_contract_errors": list(assessment.errors),
            "approval_required": approval_required,
            "preview_available": preview_available,
            "rollback_available": rollback_available,
            "max_claimable_outcome": max_claimable_outcome,
        }

    def _adapter_contract_assessment(self, structured_query: StructuredQuery) -> AdapterRouteAssessment:
        slots = structured_query.slots if isinstance(structured_query.slots, dict) else {}
        tool_name = str(slots.get("tool_name") or "").strip()
        if tool_name:
            tool_arguments = dict(slots.get("tool_arguments") or {})
            return self._adapter_contracts.assess_tool_route(tool_name, tool_arguments)
        if structured_query.query_shape == QueryShape.DISCORD_RELAY_REQUEST:
            candidate_contracts: list[AdapterContract] = []
            errors: list[str] = []
            for adapter_id in ("relay.discord_local_client", "relay.discord_official_scaffold"):
                try:
                    candidate_contracts.append(self._adapter_contracts.get_contract(adapter_id))
                except KeyError:
                    errors.append(
                        f"Discord relay route '{adapter_id}' is unavailable because its adapter contract is missing."
                    )
            pending_preview = slots.get("pending_preview") if isinstance(slots.get("pending_preview"), dict) else {}
            route_mode = str(slots.get("route_mode") or pending_preview.get("route_mode") or "").strip().lower()
            selected_contract: AdapterContract | None = None
            if route_mode == "local_client_automation":
                selected_contract = next(
                    (contract for contract in candidate_contracts if contract.adapter_id == "relay.discord_local_client"),
                    None,
                )
                if selected_contract is None:
                    errors.append(
                        "Discord relay selected the local client route without a declared adapter contract."
                    )
            elif route_mode == "official_bot_webhook":
                selected_contract = next(
                    (contract for contract in candidate_contracts if contract.adapter_id == "relay.discord_official_scaffold"),
                    None,
                )
                if selected_contract is None:
                    errors.append(
                        "Discord relay selected the official scaffold route without a declared adapter contract."
                    )
            return AdapterRouteAssessment(
                tool_name="discord_relay",
                contract_required=bool(route_mode),
                candidate_contracts=candidate_contracts,
                selected_contract=selected_contract,
                errors=errors,
                binding_mode="conditional",
            )
        return AdapterRouteAssessment(tool_name=tool_name or "planner", contract_required=False)

    def _build_execution_plan(
        self,
        structured_query: StructuredQuery,
        *,
        capability_plan: CapabilityPlan,
        session_id: str,
    ) -> ExecutionPlan:
        del capability_plan, session_id
        slots = structured_query.slots if isinstance(structured_query.slots, dict) else {}
        compatibility_decision = slots.get("compatibility_decision")
        if isinstance(compatibility_decision, PlannerDecision):
            tool_name = None
            tool_arguments: dict[str, Any] = {}
            if compatibility_decision.tool_requests:
                tool_name = compatibility_decision.tool_requests[0].tool_name
                tool_arguments = dict(compatibility_decision.tool_requests[0].arguments)
            return ExecutionPlan(
                plan_type=structured_query.execution_type or "compatibility_shim",
                request_type=str(slots.get("request_type_hint") or compatibility_decision.request_type or "unclassified"),
                response_mode=ResponseMode(structured_query.output_mode or ResponseMode.SUMMARY_RESULT.value),
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                family=str(slots.get("family") or ""),
                subject=str(slots.get("subject") or ""),
                requires_reasoner=bool(slots.get("requires_reasoner") or compatibility_decision.requires_reasoner),
                assistant_message=compatibility_decision.assistant_message,
            )

        request_type = str(slots.get("request_type_hint") or "direct_deterministic_fact")
        return ExecutionPlan(
            plan_type=structured_query.execution_type or "unclassified",
            request_type=request_type,
            response_mode=ResponseMode(structured_query.output_mode or ResponseMode.SUMMARY_RESULT.value),
            tool_name=str(slots.get("tool_name") or "").strip() or None,
            tool_arguments=dict(slots.get("tool_arguments") or {}),
            family=str(slots.get("family") or structured_query.domain or ""),
            subject=str(slots.get("subject") or structured_query.domain or ""),
            requires_reasoner=bool(slots.get("requires_reasoner", False)),
            assistant_message=str(slots.get("assistant_message") or "").strip() or None,
        )

    def _active_request_state_from_structured_query(
        self,
        structured_query: StructuredQuery,
        execution_plan: ExecutionPlan,
    ) -> dict[str, object]:
        family = (execution_plan.family or structured_query.domain or "").strip()
        if not family:
            return {}
        parameters = dict(structured_query.slots.get("tool_arguments") or {})
        route_tool_name = str(execution_plan.tool_name or "").strip()
        parameters.update(
            {
                "query_shape": structured_query.query_shape.value,
                "execution_type": structured_query.execution_type,
                "context_freshness": "current",
                "context_reusable": True,
            }
        )
        if route_tool_name:
            parameters.setdefault("tool_name", route_tool_name)
            parameters.setdefault("source_case", route_tool_name)
        if structured_query.query_shape == QueryShape.CALCULATION_REQUEST:
            calculation_request = structured_query.slots.get("calculation_request")
            if isinstance(calculation_request, dict):
                parameters["calculation_request"] = dict(calculation_request)
                parameters["requested_mode"] = str(calculation_request.get("requested_mode") or "").strip()
                parameters["follow_up_reuse"] = bool(calculation_request.get("follow_up_reuse", False))
                if calculation_request.get("helper_name"):
                    parameters["helper_name"] = str(calculation_request.get("helper_name") or "").strip()
        if structured_query.query_shape == QueryShape.SOFTWARE_CONTROL_REQUEST:
            for key in (
                "operation_type",
                "target_name",
                "request_stage",
                "follow_up_reuse",
                "selected_source_route",
                "approval_scope",
                "approval_outcome",
                "trust_request_id",
            ):
                if key in structured_query.slots:
                    parameters[key] = structured_query.slots.get(key)
        if structured_query.requested_metric:
            parameters["metric"] = structured_query.requested_metric
        if structured_query.requested_action:
            parameters["requested_action"] = structured_query.requested_action
        if structured_query.timescale:
            parameters["timescale"] = structured_query.timescale
        if structured_query.query_shape == QueryShape.DISCORD_RELAY_REQUEST:
            for key in (
                "destination_alias",
                "payload_hint",
                "note_text",
                "request_stage",
                "pending_preview",
                "ambiguity_choices",
                "approval_scope",
                "approval_outcome",
                "trust_request_id",
            ):
                if key in structured_query.slots:
                    parameters[key] = structured_query.slots.get(key)
        state = {
            "family": family,
            "subject": execution_plan.subject or family,
            "request_type": execution_plan.request_type,
            "query_shape": structured_query.query_shape.value,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "context_source": "real_http_session",
            "context_freshness": "current",
            "context_reusable": True,
            "route": {
                "tool_name": route_tool_name,
                "response_mode": execution_plan.response_mode.value,
            },
            "parameters": parameters,
            "structured_query": structured_query.to_dict(),
        }
        if structured_query.query_shape == QueryShape.CAMERA_AWARENESS_REQUEST:
            state["source_provenance"] = "camera_request"
            state["context_source"] = "camera_request"
            parameters.setdefault("source_provenance", "camera_request")
            parameters.setdefault("capture_mode", "single_still")
            parameters.setdefault("requires_confirmation", True)
            parameters.setdefault("provider_kind", "mock")
        return state

    def classify(
        self,
        message: str,
        *,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
        active_posture: dict[str, Any] | None,
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
        learned_preferences: dict[str, dict[str, object]],
    ) -> RequestClassification:
        del surface_mode, active_module, workspace_context, active_posture
        lower = normalize_phrase(message)
        present_in = "deck" if any(token in lower for token in {" in systems", " in the systems", "show in systems"}) else "none"
        recent_family = self._recent_family(recent_tool_results)
        weather_open_default = str(self._preference_value(learned_preferences, "weather", "open_target") or "none")
        weather_location_default = str(self._preference_value(learned_preferences, "weather", "location_mode") or "auto")

        follow_up = self._classify_follow_up(
            lower,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
            recent_family=recent_family,
            present_in=present_in,
        )
        if follow_up is not None:
            return follow_up

        open_target = self._open_target(lower, previous="none", preferred=weather_open_default)
        location_reference = self._location_reference_override(lower)
        named_location = location_reference[0] if location_reference else None
        named_location_type = location_reference[1] if location_reference else None

        if self._looks_like_system_overview(lower):
            return RequestClassification(
                request_type="mixed_command_explanation",
                family="system_overview",
                present_in=present_in,
                requires_reasoner=True,
            )
        if self._looks_like_power_diagnosis(lower):
            return RequestClassification(
                request_type="deterministic_diagnostic_request",
                family="power_diagnosis",
                present_in=present_in,
            )
        if self._looks_like_location(lower):
            mode = "named" if named_location else self._location_mode(lower, previous=weather_location_default)
            allow_home_fallback = self._allow_home_fallback(lower, previous=(mode != "current"))
            return RequestClassification(
                request_type="direct_deterministic_fact",
                family="location",
                location_mode=mode,
                named_location=named_location,
                named_location_type=named_location_type,
                allow_home_fallback=allow_home_fallback,
            )
        if self._looks_like_weather(lower):
            forecast_target = self._forecast_target(lower, previous="current")
            return RequestClassification(
                request_type="direct_action" if open_target != "none" else ("deterministic_projection_request" if forecast_target != "current" else "direct_deterministic_fact"),
                family="weather",
                open_target=open_target,
                location_mode="named" if named_location else self._location_mode(lower, previous=weather_location_default),
                named_location=named_location,
                named_location_type=named_location_type,
                allow_home_fallback=self._allow_home_fallback(lower, previous=True),
                forecast_target=forecast_target,
            )

        if self._looks_like_power_status(lower, recent_family=recent_family):
            grounded = recent_family == "power" and not self._mentions_power_directly(lower)
            return RequestClassification(
                request_type="follow_up_grounded" if grounded else "direct_deterministic_fact",
                family="power",
                focus=self._power_focus(lower),
                present_in=present_in,
            )
        if self._looks_like_power_projection(lower, recent_family=recent_family):
            metric, target_percent = self._power_projection_shape(lower, previous_parameters={})
            grounded = recent_family == "power"
            return RequestClassification(
                request_type="follow_up_grounded" if grounded else "deterministic_projection_request",
                family="power_projection",
                metric=metric,
                target_percent=target_percent,
                assume_unplugged=self._assume_unplugged(lower, previous=False),
                present_in=present_in,
            )
        if self._looks_like_resource_diagnosis(lower):
            return RequestClassification(
                request_type="deterministic_diagnostic_request",
                family="resource_diagnosis",
                present_in=present_in,
            )
        resource_query_kind = self._resource_query_kind(lower, recent_family=recent_family)
        if resource_query_kind is not None:
            grounded = recent_family == "resource" and not self._mentions_resource_directly(lower)
            return RequestClassification(
                request_type=(
                    "follow_up_grounded"
                    if grounded
                    else "deterministic_diagnostic_request"
                    if resource_query_kind == "diagnostic"
                    else "direct_deterministic_fact"
                ),
                family="resource",
                focus=self._resource_focus(lower),
                query_kind=resource_query_kind,
                metric=self._resource_metric(lower, focus=self._resource_focus(lower), query_kind=resource_query_kind),
                present_in=present_in,
            )
        if self._looks_like_network_diagnosis(lower):
            return RequestClassification(
                request_type="deterministic_diagnostic_request",
                family="network_diagnosis",
                focus=self._network_focus(lower, previous="overview"),
                metric="diagnostic_burst",
                present_in=present_in,
            )
        if self._looks_like_network_status(lower):
            focus = self._network_status_focus(lower)
            return RequestClassification(
                request_type="direct_deterministic_fact",
                family="network",
                focus=focus,
                present_in=present_in,
            )
        if self._looks_like_machine(lower):
            return RequestClassification(
                request_type="direct_deterministic_fact",
                family="machine",
                focus="time" if "timezone" in lower or "time zone" in lower else "identity",
                present_in=present_in,
            )
        if any(token in lower for token in {"running apps", "open apps", "what is open"}):
            return RequestClassification(request_type="direct_deterministic_fact", family="active_apps")
        if any(token in lower for token in {"recent files", "recent documents", "what was i working on"}):
            return RequestClassification(request_type="direct_deterministic_fact", family="recent_files")
        if self._looks_like_storage_diagnosis(lower):
            return RequestClassification(
                request_type="deterministic_diagnostic_request",
                family="storage_diagnosis",
                present_in=present_in,
            )
        if self._looks_like_storage_status(lower):
            return RequestClassification(request_type="direct_deterministic_fact", family="storage")
        return RequestClassification(request_type="unclassified")

    def should_escalate(
        self,
        message: str,
        *,
        tool_job_count: int,
        actions: list[dict[str, Any]],
        planner_text: str,
        request_type: str = "unclassified",
        requires_reasoner: bool = False,
    ) -> bool:
        lower = message.lower()
        if requires_reasoner:
            return True
        if request_type in {
            "direct_deterministic_fact",
            "deterministic_projection_request",
            "deterministic_diagnostic_request",
            "follow_up_grounded",
            "direct_action",
            "software_control_response",
            "browser_search",
            "unsupported_capability",
            "clarification_request",
            "guardrail_clarify",
            "comparison_request",
            "workspace_restore",
            "workspace_assembly",
            "routine_execution",
            "routine_save",
            "maintenance_execution",
            "file_operation",
            "trusted_hook_execution",
            "browser_context",
            "activity_summary",
            "context_action",
            "workflow_execution",
            "search_and_act",
            "repair_execution",
            "discord_relay_dispatch",
            "trust_approval_explanation",
        }:
            return False
        if any(
            phrase in lower
            for phrase in {
                "save this workspace",
                "snapshot this workspace",
                "archive this workspace",
                "rename this workspace",
                "tag this workspace",
                "list my recent workspaces",
                "show my archived workspaces",
                "what were we doing",
                "what's next",
                "what is next",
            }
        ):
            return False
        if tool_job_count > 1:
            return True
        if any(action.get("type") == "workspace_restore" for action in actions):
            return True
        if any(token in lower for token in {"compare", "explain", "why", "continue", "summarize", "restore", "workspace"}):
            return True
        return not bool(planner_text.strip())

    def _classify_follow_up(
        self,
        lower: str,
        *,
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
        recent_family: str | None,
        present_in: str,
    ) -> RequestClassification | None:
        del recent_tool_results
        family = str(active_request_state.get("family") or "").strip().lower()
        parameters = active_request_state.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}
        if not family and recent_family:
            family = recent_family

        if family == "weather" and self._looks_like_weather_follow_up(lower):
            previous_open = str(parameters.get("open_target", "none")).strip().lower() or "none"
            previous_target = str(parameters.get("forecast_target", "current")).strip().lower() or "current"
            previous_location = str(parameters.get("location_mode", "auto")).strip().lower() or "auto"
            previous_named = str(parameters.get("named_location", "")).strip() or None
            previous_named_type = str(parameters.get("named_location_type", "")).strip().lower() or None
            previous_allow_home = bool(parameters.get("allow_home_fallback", True))
            location_reference = self._location_reference_override(lower)
            named_location = location_reference[0] if location_reference else previous_named
            named_location_type = location_reference[1] if location_reference else previous_named_type
            return RequestClassification(
                request_type="follow_up_grounded",
                family="weather",
                open_target=self._open_target(lower, previous=previous_open),
                forecast_target=self._forecast_target(lower, previous=previous_target),
                location_mode="named" if named_location else self._location_mode(lower, previous=previous_location),
                named_location=named_location,
                named_location_type=named_location_type,
                allow_home_fallback=self._allow_home_fallback(lower, previous=previous_allow_home),
            )

        if family in {"power", "power_projection"} and self._looks_like_power_follow_up(lower):
            if self._looks_like_power_status(lower, recent_family="power") and not self._looks_like_power_projection(lower, recent_family="power"):
                return RequestClassification(
                    request_type="follow_up_grounded",
                    family="power",
                    focus=self._power_focus(lower),
                    present_in=present_in,
                )
            metric, target_percent = self._power_projection_shape(lower, previous_parameters=parameters)
            return RequestClassification(
                request_type="follow_up_grounded",
                family="power_projection",
                metric=metric,
                target_percent=target_percent,
                assume_unplugged=self._assume_unplugged(lower, previous=bool(parameters.get("assume_unplugged", False))),
                present_in=present_in,
            )
        if family in {"network", "network_diagnosis"} and self._looks_like_network_follow_up(lower):
            return RequestClassification(
                request_type="follow_up_grounded",
                family="network_diagnosis",
                focus=self._network_focus(lower, previous=str(parameters.get("focus", "overview")) or "overview"),
                metric="diagnostic_burst",
                present_in=present_in,
            )
        return None

    def _plan_active_item_follow_up(
        self,
        message: str,
        *,
        surface_mode: str,
        workspace_context: dict[str, Any] | None,
        active_posture: dict[str, Any] | None,
    ) -> PlannerDecision | None:
        lower = normalize_phrase(message)
        if not any(
            phrase in lower
            for phrase in {
                "show me that in the deck",
                "show that in the deck",
                "open that in the deck",
                "show the pdf in deck",
                "show that pdf in deck",
                "open the pdf in deck",
                "show the file in deck",
                "show the page in deck",
                "open it in the deck",
                "show it in the deck",
                "show me the same file again",
                "open the same file again",
                "show me the same page again",
            }
        ):
            return None
        item = self._active_item(workspace_context, active_posture)
        if not isinstance(item, dict):
            return None
        path = str(item.get("path", "")).strip()
        url = str(item.get("url", "")).strip()
        if "external" in lower or "browser" in lower:
            if url:
                return PlannerDecision(
                    request_type="follow_up_grounded",
                    tool_requests=[ToolRequest("external_open_url", {"url": url})],
                )
            if path:
                return PlannerDecision(
                    request_type="follow_up_grounded",
                    tool_requests=[ToolRequest("external_open_file", {"path": path})],
                )
            return None
        if url:
            return PlannerDecision(
                request_type="follow_up_grounded",
                tool_requests=[ToolRequest("deck_open_url", {"url": url})],
            )
        if path:
            return PlannerDecision(
                request_type="follow_up_grounded",
                tool_requests=[ToolRequest("deck_open_file", {"path": path})],
            )
        if surface_mode.strip().lower() == "deck":
            return PlannerDecision(
                request_type="follow_up_grounded",
                assistant_message="Current bearings do not include a file or page I can reopen from the active workspace.",
            )
        return None

    def _calculation_route_spine_reuse_available(self, calculation_evaluation: Any | None) -> bool:
        payload = (
            calculation_evaluation.to_dict()
            if calculation_evaluation is not None and hasattr(calculation_evaluation, "to_dict")
            else {}
        )
        if not payload:
            return False
        if bool(payload.get("follow_up_reuse")):
            return True
        return bool(payload.get("candidate")) and bool(
            payload.get("extracted_expression") or payload.get("helper_name")
        )

    def _screen_action_requires_bound_target(
        self,
        lower: str,
        screen_awareness_evaluation: ScreenPlannerEvaluation | None,
    ) -> bool:
        if screen_awareness_evaluation is None:
            return False
        if getattr(screen_awareness_evaluation, "disposition", None) != ScreenRouteDisposition.PHASE5_ACT:
            return False
        if re.fullmatch(r"(?:tap|select)\s+(?:this|that|these|those)\s+\w+", lower.strip()):
            return True
        return bool(re.fullmatch(r"(?:click\s+next|press\s+submit)", lower.strip()))

    def _active_item_follow_up_semantic_proposal(
        self,
        message: str,
        *,
        surface_mode: str,
        workspace_context: dict[str, Any] | None,
        active_posture: dict[str, Any] | None,
    ) -> SemanticParseProposal | None:
        follow_up = self._plan_active_item_follow_up(
            message,
            surface_mode=surface_mode,
            workspace_context=workspace_context,
            active_posture=active_posture,
        )
        if follow_up is None:
            return None
        if follow_up.tool_requests:
            request = follow_up.tool_requests[0]
            if request.tool_name in {"deck_open_url", "external_open_url"}:
                url = str(request.arguments.get("url") or "").strip()
                return self._tool_proposal(
                    query_shape=QueryShape.OPEN_BROWSER_DESTINATION,
                    domain="browser",
                    tool_name=request.tool_name,
                    tool_arguments=dict(request.arguments),
                    request_type_hint="direct_action",
                    family="browser_destination",
                    subject=url or "active_page",
                    requested_action="open_browser_destination",
                    confidence=0.94,
                    evidence=["active-item follow-up reopened the current workspace page"],
                    execution_type="resolve_url_then_open_in_browser",
                    output_mode=ResponseMode.ACTION_RESULT.value,
                    output_type="action",
                    slots={"target_scope": "browser"},
                )
            if request.tool_name in {"deck_open_file", "external_open_file"}:
                path = str(request.arguments.get("path") or "").strip()
                return self._tool_proposal(
                    query_shape=QueryShape.CONTEXT_ACTION,
                    domain="files",
                    tool_name=request.tool_name,
                    tool_arguments=dict(request.arguments),
                    request_type_hint="direct_action",
                    family="file",
                    subject=path or "active_file",
                    requested_action="open_file",
                    confidence=0.94,
                    evidence=["active-item follow-up reopened the current workspace file"],
                    execution_type="execute_control_command",
                    output_mode=ResponseMode.ACTION_RESULT.value,
                    output_type="action",
                    slots={"target_scope": "files"},
                )
        if follow_up.assistant_message:
            return self._tool_proposal(
                query_shape=QueryShape.SUMMARY_REQUEST,
                domain="files",
                request_type_hint="follow_up_grounded",
                family="file",
                subject="active_item",
                requested_action="open_file",
                confidence=0.9,
                evidence=["active-item follow-up requested a current file or page, but none was available"],
                assistant_message=follow_up.assistant_message,
                execution_type="summarize_activity",
                output_mode=ResponseMode.SUMMARY_RESULT.value,
                output_type="summary",
                slots={"target_scope": "files"},
            )
        return None

    def _active_item(
        self,
        workspace_context: dict[str, Any] | None,
        active_posture: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        for source in (workspace_context or {}, active_posture or {}):
            active_item = source.get("active_item")
            if isinstance(active_item, dict) and active_item:
                return active_item
            opened = source.get("opened_items")
            if isinstance(opened, list):
                for item in opened:
                    if isinstance(item, dict) and item.get("title"):
                        return item
        return None

    def _looks_like_workspace_restore(self, lower: str) -> bool:
        explicit_restore = re.search(r"\brestore\b.{0,32}\b(?:workspace|setup|environment|project)\b", lower)
        explicit_workspace_open = re.search(r"\b(?:open|bring\s+back|pull\s+up)\b.{0,32}\bworkspace\b", lower)
        continuity = any(phrase in lower for phrase in {"continue where we left off", "pick up where we left off", "where we left off"})
        return bool(explicit_restore or explicit_workspace_open or continuity)

    def _looks_like_workspace_save(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "save this workspace",
                "save where we are",
                "save current workspace",
                "snapshot this workspace",
                "snapshot the workspace",
            }
        )

    def _looks_like_workspace_clear(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "clear workspace",
                "clear the workspace",
                "clear this workspace",
                "clear current workspace",
                "clear the current workspace",
                "reset the workspace",
                "empty the workspace",
            }
        )

    def _looks_like_workspace_archive(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "archive this workspace",
                "archive the workspace",
                "archive current workspace",
                "archive the current workspace",
            }
        )

    def _looks_like_workspace_rename(self, lower: str) -> bool:
        return bool(re.search(r"\brename\b.{0,40}\b(?:workspace|wrkspace)\b", lower))

    def _looks_like_workspace_tag(self, lower: str) -> bool:
        return bool(re.search(r"\btag\b.{0,40}\b(?:workspace|wrkspace)\b", lower))

    def _looks_like_workspace_list(self, lower: str) -> bool:
        if lower in {
            "show my workspace",
            "show my workspaces",
            "show workspace",
            "show workspaces",
            "my workspace",
            "my workspaces",
            "list workspace",
            "list workspaces",
            "list my workspace",
            "list my workspaces",
        }:
            return True
        return any(
            phrase in lower
            for phrase in {
                "list my recent workspaces",
                "show my recent workspaces",
                "show my archived workspaces",
                "recent workspaces",
                "archived workspaces",
            }
        )

    def _looks_like_where_left_off(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "what were we doing",
                "where did we leave off",
                "continue from there",
                "continue where i left off",
                "resume where i left off",
            }
        )

    def _looks_like_next_steps(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "what's next",
                "what is next",
                "what still needs doing",
                "what's left",
                "what should i do next",
                "what do i do next",
                "next steps",
            }
        )

    def _looks_like_workspace_assemble(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "set up a workspace",
                "setup a workspace",
                "gather everything relevant",
                "assemble a workspace",
                "open the project workspace",
                "workspace for ",
            }
        )

    def _looks_like_save_home_location(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "save this as my home location",
                "set this as my home location",
                "save my current location as home",
            }
        )

    def _looks_like_open_location_settings(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "open location settings",
                "take me to location settings",
                "open the location settings",
                "open location privacy settings",
            }
        )

    def _looks_like_saved_locations_list(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "show my saved locations",
                "list my saved locations",
                "what saved locations do you have",
            }
        )

    def _looks_like_system_overview(self, lower: str) -> bool:
        return (
            "system state" in lower
            or "machine state" in lower
            or "machine status" in lower
            or ("anything looks wrong" in lower and any(token in lower for token in {"system", "machine", "computer"}))
        )

    def _looks_like_location(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "current location",
                "my current location",
                "where am i",
                "what is my location",
                "what's my location",
                "saved home",
                "home location",
                "use my home location",
                "use my current location",
            }
        )

    def _looks_like_weather(self, lower: str) -> bool:
        return any(
            token in lower
            for token in {
                "weather",
                "forecast",
                "current temperature",
                "temperature outside",
                "outside right now",
                "temperature tonight",
                "weather tomorrow",
            }
        )

    def _looks_like_weather_follow_up(self, lower: str) -> bool:
        return any(
            token in lower
            for token in {
                "tomorrow",
                "tonight",
                "this weekend",
                "weekend",
                "show it in the deck",
                "show it internally",
                "open it externally",
                "just answer",
                "don't open",
                "do not open",
                "use my home location",
                "use my current location",
                "which location did you use",
                "what weather source",
            }
        )

    def _looks_like_power_status(self, lower: str, *, recent_family: str | None) -> bool:
        if any(
            token in lower
            for token in {
                "battery level",
                "battery percent",
                "battery percentage",
                "how much battery",
                "battery left",
                "am i charging",
                "are we charging",
                "plugged in",
                "on ac",
            }
        ) or re.search(r"\b(?:what(?:'s|\s+is)\s+(?:my|the)|how\s+much)\b.{0,16}\bbattery\b(?:\s+at|\s+left)?\b", lower):
            return True
        return recent_family == "power" and "am i charging" in lower

    def _looks_like_power_projection(self, lower: str, *, recent_family: str | None) -> bool:
        if any(
            token in lower
            for token in {
                "how long until",
                "time to full",
                "time to empty",
                "until empty",
                "unplug now",
                "if i unplug",
                "power am i using",
                "power draw",
                "draining",
                "how much longer will my battery last",
            }
        ):
            return True
        return recent_family == "power" and any(token in lower for token in {"what if i unplug", "how long until", "how much power"})

    def _looks_like_power_diagnosis(self, lower: str) -> bool:
        return any(
            token in lower
            for token in {
                "battery draining unusually fast",
                "battery draining so fast",
                "battery draining fast",
                "is my battery draining unusually fast",
                "is my battery draining fast",
                "draining unusually fast",
                "draining so fast",
            }
        )

    def _looks_like_power_follow_up(self, lower: str) -> bool:
        return self._looks_like_power_projection(lower, recent_family="power") or self._looks_like_power_status(lower, recent_family="power")

    def _mentions_power_directly(self, lower: str) -> bool:
        return any(token in lower for token in {"battery", "charging", "plugged in", "power saver", "power state"})

    def _power_focus(self, lower: str) -> str:
        if any(token in lower for token in {"charging", "am i charging", "plugged in", "on ac", "power state"}):
            return "charging"
        if any(token in lower for token in {"battery level", "battery percent", "battery percentage", "how much battery", "battery left"}):
            return "level"
        return "overview"

    def _power_projection_shape(self, lower: str, *, previous_parameters: dict[str, Any]) -> tuple[str, int | None]:
        if any(token in lower for token in {"power am i using", "power draw"}):
            return "power_draw", None
        if any(token in lower for token in {"draining so fast", "battery draining", "drain rate", "how fast is my battery draining"}):
            return "drain_rate", None
        if any(token in lower for token in {"until empty", "time to empty", "until dead"}):
            return "time_to_empty", None
        if any(token in lower for token in {"unplug now", "if i unplug", "if we unplug", "what if i unplug"}) and not any(
            token in lower for token in {"%", "until", "time to", "power draw", "draining"}
        ):
            return "time_to_empty", None
        match = re.search(r"(\d{1,3})\s*%", lower)
        target_percent = int(match.group(1)) if match else previous_parameters.get("target_percent")
        if target_percent is None and "until 100" in lower:
            target_percent = 100
        if target_percent is None and "time to full" in lower:
            target_percent = 100
        if target_percent is None and str(previous_parameters.get("metric", "")).strip() == "time_to_percent":
            target_percent = previous_parameters.get("target_percent")
        if target_percent is None:
            target_percent = 100
        return "time_to_percent", int(target_percent)

    def _assume_unplugged(self, lower: str, *, previous: bool) -> bool:
        if any(token in lower for token in {"unplug now", "if i unplug", "if we unplug", "on battery"}):
            return True
        return previous

    def _looks_like_resource(self, lower: str, *, recent_family: str | None) -> bool:
        return self._resource_query_kind(lower, recent_family=recent_family) is not None

    def _looks_like_resource_diagnosis(self, lower: str) -> bool:
        if "slowing" in lower and "down" in lower and any(token in lower for token in {"machine", "computer", "pc"}):
            return True
        if re.search(r"\b(?:computer|machine|pc|system)\b.{0,40}\b(?:sluggish|slow|laggy|bogged down|dragging)\b", lower):
            return True
        if re.search(r"\b(?:why|diagnos|troubleshoot|what'?s wrong)\b.{0,48}\b(?:computer|machine|pc|cpu|memory|ram|gpu|resources?)\b", lower):
            return True
        if re.search(r"\b(?:cpu|memory|ram|gpu|resources?)\b.{0,40}\b(?:bottleneck|pressure|spike|high|pegged|sluggish|slow)\b", lower):
            return True
        return any(
            phrase in lower
            for phrase in {
                "why is this machine slow",
                "why is the machine slow",
                "machine feels slow",
                "machine feels sluggish",
                "why is this machine sluggish",
                "why is the computer slow",
                "computer feels slow",
            }
        )

    def _resource_query_kind(self, lower: str, *, recent_family: str | None) -> str | None:
        if self._looks_like_network_throughput(lower):
            return None
        if self._looks_like_active_apps_status(lower) or self._looks_like_window_status(lower):
            return None
        if self._looks_like_resource_interpretation(lower):
            return "diagnostic"
        if self._looks_like_resource_telemetry(lower):
            return "telemetry"
        if self._looks_like_resource_identity(lower):
            return "identity"
        if recent_family == "resource" and any(
            phrase in lower for phrase in {"what about the gpu", "what about gpu", "what about ram", "what about memory", "what about cpu"}
        ):
            return "telemetry"
        if self._mentions_resource_directly(lower):
            return "telemetry"
        return None

    def _looks_like_resource_identity(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "what gpu do i have",
                "which gpu do i have",
                "what graphics card do i have",
                "what graphics card is this machine using",
                "which graphics card",
                "what video card do i have",
                "what cpu do i have",
                "which cpu do i have",
                "what processor do i have",
                "which processor do i have",
                "what ram do i have",
                "how much ram do i have",
            }
        )

    def _looks_like_resource_telemetry(self, lower: str) -> bool:
        if self._looks_like_resource_interpretation(lower):
            return False
        return any(
            token in lower
            for token in {
                "current gpu",
                "current cpu",
                "current ram",
                "usage level",
                "usage right now",
                "current usage",
                "right now",
                "currently",
                "utilization",
                "usage",
                "cpu temp",
                "gpu temp",
                "temperature",
                "temps",
                "vram",
                "gpu memory",
                "video memory",
                "memory usage",
                "ram usage",
                "free memory",
            }
        )

    def _looks_like_resource_interpretation(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "under load",
                "running hot",
                "too hot",
                "memory pressure",
                "resource bottleneck",
                "cpu load elevated",
                "gpu load elevated",
                "load appears concentrated",
            }
        )

    def _mentions_resource_directly(self, lower: str) -> bool:
        return any(
            re.search(rf"\b{re.escape(token)}\b", lower)
            for token in {
                "cpu",
                "processor",
                "ram",
                "memory",
                "gpu",
                "graphics card",
                "graphics adapter",
                "video card",
                "vram",
                "resources",
            }
        )

    def _resource_focus(self, lower: str) -> str:
        if any(token in lower for token in {"gpu", "graphics card", "graphics adapter", "video card", "vram"}):
            return "gpu"
        if "ram" in lower or "memory" in lower:
            return "ram"
        if "cpu" in lower or "processor" in lower:
            return "cpu"
        return "overview"

    def _resource_metric(self, lower: str, *, focus: str, query_kind: str) -> str:
        if query_kind == "identity":
            return "identity"
        if focus == "gpu":
            if any(token in lower for token in {"vram", "gpu memory", "video memory"}):
                return "memory"
            if "power" in lower:
                return "power"
            if any(token in lower for token in {"temp", "temperature", "hotspot"}):
                return "temperature"
            if any(token in lower for token in {"load", "usage", "utilization", "currently", "right now", "current"}):
                return "usage"
            return "overview"
        if focus == "cpu":
            if any(token in lower for token in {"temp", "temperature"}):
                return "temperature"
            if any(token in lower for token in {"clock", "mhz", "ghz", "frequency"}):
                return "clock"
            if any(token in lower for token in {"load", "usage", "utilization", "currently", "right now", "current"}):
                return "usage"
            return "overview"
        if focus == "ram":
            if "pressure" in lower:
                return "pressure"
            if any(token in lower for token in {"free", "available"}):
                return "free"
            if any(token in lower for token in {"usage", "used", "current", "currently", "right now"}):
                return "usage"
            return "overview"
        return "overview"

    def _looks_like_native_comparison_request(self, lower: str) -> bool:
        if not re.search(r"\b(?:compare|diff)\b", lower):
            return False
        native_target_terms = {
            "file",
            "files",
            "document",
            "documents",
            "doc",
            "docs",
            "folder",
            "folders",
            "spreadsheet",
            "spreadsheets",
            "pdf",
            "pdfs",
            "image",
            "images",
            "screenshot",
            "screenshots",
            "draft",
            "drafts",
            "version",
            "versions",
        }
        if any(re.search(rf"\b{re.escape(term)}\b", lower) for term in native_target_terms):
            return True
        if re.search(r"\b[\w.-]+\.(?:txt|md|pdf|docx?|xlsx?|csv|py|ts|tsx|js|jsx|json|ya?ml|toml|ini|log)\b", lower):
            return True
        if re.search(r"\b(?:compare|diff)\b.{0,40}\b(?:selected|highlighted)\b", lower):
            return True
        return False

    def _looks_like_storage_status(self, lower: str) -> bool:
        return any(
            token in lower
            for token in {
                "storage",
                "disk space",
                "free space",
                "drive space",
                "disk usage",
                "storage usage",
                "drive usage",
                "disk used",
            }
        )

    def _looks_like_storage_diagnosis(self, lower: str) -> bool:
        return any(
            token in lower
            for token in {
                "disk pressure",
                "storage pressure",
                "disk getting full",
                "storage getting full",
            }
        )

    def _looks_like_network_status(self, lower: str) -> bool:
        if any(
            phrase in lower
            for phrase in {
                "network effects",
                "neural network",
                "network graph",
                "networking advice",
            }
        ):
            return False
        if lower.startswith(("explain ", "define ", "what is a ", "what's a ", "draw ")):
            return False
        online_question = bool(re.search(r"\b(?:am\s+i|are\s+we|is\s+(?:this\s+)?(?:machine|computer|laptop|pc))\s+online\b", lower))
        connectivity_question = bool(
            re.search(
                r"\b(?:is|are|am|check|show|tell)\b.{0,40}\b(?:online|connected|internet|wi-fi|wifi|connection)\b",
                lower,
            )
        )
        connection_name_question = bool(
            any(re.search(rf"\b{term}\b", lower) for term in {"wi-fi", "wifi", "wireless", "ssid", "network", "connection"})
            and any(re.search(rf"\b{verb}\b", lower) for verb in {"what", "which", "show", "tell"})
            and (
                any(
                    phrase in lower
                    for phrase in {
                        "am i on",
                        "am i using",
                        "im on",
                        "connected to",
                        "connection name",
                        "network name",
                        "current",
                        "using",
                    }
                )
                or bool(
                    re.search(
                        r"\b(?:this|my|the)\s+(?:laptop|computer|machine|pc|device|system)\s+(?:is\s+)?(?:on|using)\b",
                        lower,
                    )
                )
            )
        )
        device_scope = bool(re.search(r"\b(?:my|this|the)\s+(?:machine|computer|laptop|pc|device|system)\b", lower))
        status_phrase = any(
            phrase in lower
            for phrase in {
                "wifi signal",
                "wi-fi signal",
                "signal strength",
                "network status",
                "internet status",
                "connection status",
                "what network am i on",
                "which network am i on",
                "my ip",
                "ip address",
            }
        )
        return online_question or connectivity_question or connection_name_question or status_phrase or (
            device_scope and any(token in lower for token in {"connected", "online", "internet", "wifi", "wi-fi"})
        )

    def _looks_like_clock_time(self, lower: str) -> bool:
        if "timezone" in lower or "time zone" in lower:
            return False
        return any(
            phrase in lower
            for phrase in {
                "what time is it",
                "whats the time",
                "what's the time",
                "current time",
                "local time",
                "tell me the time",
                "what date is it",
                "what is today's date",
                "whats todays date",
                "what's today's date",
            }
        )

    def _looks_like_network_throughput(self, lower: str) -> bool:
        speed_phrase = any(
            phrase in lower
            for phrase in {
                "download speed",
                "downloads speed",
                "upload speed",
                "uploads speed",
                "internet speed",
                "network speed",
                "connection speed",
                "speed test",
                "internet test",
                "network test",
                "top speed",
                "throughput",
            }
        )
        network_scope = any(
            token in lower
            for token in {
                "internet",
                "network",
                "wi-fi",
                "wifi",
                "connection",
                "download speed",
                "downloads speed",
                "upload speed",
                "uploads speed",
                "throughput",
            }
        )
        return speed_phrase and network_scope

    def _network_throughput_metric(self, lower: str) -> str:
        if "download speed" in lower or "downloads speed" in lower:
            return "download_speed"
        if "upload speed" in lower or "uploads speed" in lower:
            return "upload_speed"
        return "internet_speed"

    def _looks_like_network_diagnosis(self, lower: str) -> bool:
        return any(
            token in lower
            for token in {
                "how is my internet",
                "how's my internet",
                "how is the internet",
                "how's the internet",
                "how is my connection",
                "how's my connection",
                "internet health",
                "network health",
                "connection health",
                "is my internet ok",
                "is my internet okay",
                "is my connection ok",
                "is my connection okay",
                "why does my internet keep skipping",
                "why does my internet keep",
                "why is my wifi unstable",
                "why is my wi fi unstable",
                "why is my connection choppy",
                "why is this lagging",
                "what is wrong with my connection",
                "what is wrong with my network",
                "is my wifi unstable",
                "is my wi fi unstable",
                "is this my router or the isp",
                "is this my wifi or my isp",
                "packet loss",
                "latency",
                "jitter",
                "connection dropped",
                "did my connection drop",
                "internet keep skipping",
                "internet unstable",
                "network unstable",
            }
        )

    def _looks_like_network_follow_up(self, lower: str) -> bool:
        return any(
            token in lower
            for token in {
                "router or the isp",
                "wifi or the isp",
                "wi fi or the isp",
                "local or upstream",
                "packet loss",
                "jitter",
                "latency",
                "did it drop",
                "has it been unstable today",
                "upstream",
            }
        )

    def _network_focus(self, lower: str, *, previous: str) -> str:
        if any(token in lower for token in {"signal", "rssi"}):
            return "signal"
        if any(token in lower for token in {"router or the isp", "wifi or the isp", "wi fi or the isp", "local or upstream", "upstream"}):
            return "attribution"
        if "packet loss" in lower:
            return "packet_loss"
        if "jitter" in lower:
            return "jitter"
        if "latency" in lower or "lag" in lower:
            return "latency"
        if "dns" in lower:
            return "dns"
        if "today" in lower or "recently" in lower:
            return "history"
        return previous

    def _network_status_focus(self, lower: str) -> str:
        if any(token in lower for token in {"signal", "rssi"}):
            return "signal"
        if any(token in lower for token in {"wifi", "wi-fi", "wireless", "ssid"}):
            return "wifi"
        if "ip" in lower or "address" in lower:
            return "ip"
        return "overview"

    def _looks_like_machine(self, lower: str) -> bool:
        return any(token in lower for token in {"machine name", "os version", "what computer", "what machine", "timezone", "time zone"})

    def _looks_like_active_apps_status(self, lower: str) -> bool:
        if self._looks_like_application_concept_prompt(lower):
            return False
        return bool(
            re.search(
                r"\b(?:what|which|show|list)\b.{0,24}\b(?:apps?|applications?|programs?)\b.{0,24}\b(?:open|running|active)\b",
                lower,
            )
            or re.search(
                r"\b(?:open|running|active)\b.{0,16}\b(?:apps?|applications?|programs?)\b",
                lower,
            )
        )

    def _looks_like_application_concept_prompt(self, lower: str) -> bool:
        return any(
            token in lower
            for token in {
                "should i build",
                "marketing",
                "idea",
                "ideas",
                "architecture",
                "concept",
                "principle",
                "principles",
            }
        )

    def _looks_like_window_status(self, lower: str) -> bool:
        return bool(
            re.search(
                r"\b(?:what|which|show|list)\b.{0,24}\bwindows?\b.{0,24}\b(?:open|active|focused)\b",
                lower,
            )
            or re.search(
                r"\b(?:open|active|focused)\b.{0,16}\bwindows?\b",
                lower,
            )
        )

    def _looks_like_unsupported_external_commitment(self, lower: str) -> bool:
        transactional = any(token in lower for token in {"book", "buy", "purchase", "pay for", "order"})
        external_target = any(token in lower for token in {"flight", "hotel", "ticket", "reservation", "real "})
        immediate_commitment = any(token in lower for token in {"now", "for real", "actually", "pay"})
        return transactional and external_target and immediate_commitment

    def _routine_execute_request(self, message: str, lower: str) -> dict[str, object] | None:
        del message
        if any(phrase in lower for phrase in {"run my cleanup routine", "run the cleanup routine", "do the weekly downloads cleanup"}):
            return {"routine_name": "cleanup routine"}
        if any(phrase in lower for phrase in {"run the network health check", "run my network health check", "rerun my normal setup"}):
            return {"routine_name": "network health check" if "network" in lower else "normal setup"}
        return None

    def _routine_save_request(
        self,
        message: str,
        lower: str,
        *,
        active_request_state: dict[str, object],
        active_context: dict[str, Any] | None = None,
        active_posture: dict[str, Any] | None = None,
    ) -> dict[str, object] | None:
        if not self._looks_like_routine_save_request(lower):
            return None
        routine_name = self._extract_routine_save_name(message) or "saved routine"
        family = str(active_request_state.get("family") or "").strip().lower()
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        precondition_state = self._routine_save_precondition_state(
            active_request_state=active_request_state,
            active_context=active_context or {},
            active_posture=active_posture or {},
        )
        if precondition_state["missing_preconditions"]:
            return {
                "routine_name": routine_name,
                "routine_save_precondition_state": precondition_state,
                "missing_preconditions": list(precondition_state["missing_preconditions"]),
            }
        if family == "repair":
            return {
                "routine_name": routine_name,
                "execution_kind": "repair",
                "parameters": {
                    "repair_kind": str(parameters.get("repair_kind") or active_request_state.get("subject") or "").strip() or "connectivity_checks",
                    "target": str(parameters.get("target") or "system").strip() or "system",
                },
                "description": f"Saved repair routine for {routine_name}.",
                "routine_save_precondition_state": precondition_state,
            }
        if family == "workflow":
            return {
                "routine_name": routine_name,
                "execution_kind": "workflow",
                "parameters": {
                    "workflow_kind": str(parameters.get("workflow_kind") or active_request_state.get("subject") or "").strip(),
                    "query": str(parameters.get("query") or "").strip(),
                },
                "description": f"Saved workflow routine for {routine_name}.",
                "routine_save_precondition_state": precondition_state,
            }
        if family == "maintenance":
            return {
                "routine_name": routine_name,
                "execution_kind": "maintenance",
                "parameters": dict(parameters),
                "description": f"Saved maintenance routine for {routine_name}.",
                "routine_save_precondition_state": precondition_state,
            }
        if family == "file_operation":
            return {
                "routine_name": routine_name,
                "execution_kind": "file_operation",
                "parameters": dict(parameters),
                "description": f"Saved file operation routine for {routine_name}.",
                "routine_save_precondition_state": precondition_state,
            }
        return None

    def _looks_like_routine_save_request(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "save this as a routine",
                "save that as a routine",
                "make this a routine",
                "make that a routine",
                "turn this into a routine",
                "turn that into a routine",
                "remember this workflow as",
                "remember that workflow as",
            }
        )

    def _extract_routine_save_name(self, message: str) -> str:
        for pattern in (
            r"(?:called|named)\s+(.+)$",
            r"remember\s+(?:this|that)\s+workflow\s+as\s+(.+)$",
            r"(?:make|turn)\s+(?:this|that)\s+(?:into\s+)?a\s+routine\s+(?:called|named)\s+(.+)$",
        ):
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return " ".join(str(match.group(1) or "").split()).strip(" .,:;!?")
        return ""

    def _routine_save_precondition_state(
        self,
        *,
        active_request_state: dict[str, object],
        active_context: dict[str, Any],
        active_posture: dict[str, Any],
    ) -> dict[str, object]:
        family = str(active_request_state.get("family") or "").strip().lower()
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        context_payload = active_context if isinstance(active_context, dict) else {}
        posture_payload = active_posture if isinstance(active_posture, dict) else {}
        active_context_available = bool(family and family not in {"routine", "generic_provider", "unsupported"})
        if not active_context_available:
            active_context_available = bool(context_payload.get("current_resolution") or posture_payload.get("current_task_state"))
        bounded_probe = {
            "active_request_state": active_request_state,
            "active_context": context_payload,
            "active_posture": posture_payload,
        }
        try:
            active_context_bytes = len(json.dumps(bounded_probe, default=str, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            active_context_bytes = 0
        active_context_bounded = active_context_bytes <= WORKSPACE_PAYLOAD_FAIL_BYTES if "WORKSPACE_PAYLOAD_FAIL_BYTES" in globals() else active_context_bytes <= 5_000_000
        saveable_family = family in {"repair", "workflow", "maintenance", "file_operation"}
        missing: list[str] = []
        if not active_context_available or not saveable_family:
            missing.append("steps_or_recent_action")
        if not active_context_bounded:
            missing.append("bounded_active_context")
        return {
            "active_context_available": active_context_available and saveable_family,
            "active_context_fresh": bool(active_context_available),
            "active_context_bounded": active_context_bounded,
            "active_context_source": "active_request_state" if saveable_family else "none",
            "deictic_binding_status": "resolved" if active_context_available and saveable_family else "missing",
            "family": family,
            "parameter_keys": sorted(str(key) for key in parameters.keys()),
            "missing_preconditions": missing,
            "fallback_reason": "" if not missing else "missing_saveable_active_context",
            "generic_provider_competed": False,
        }

    def _trusted_hook_register_request(self, message: str, lower: str) -> dict[str, object] | None:
        match = re.match(r"^register trusted hook\s+(.+?)\s+for\s+(.+)$", message, flags=re.IGNORECASE)
        if not match:
            return None
        hook_name = " ".join(str(match.group(1) or "").split()).strip(" .,:;!?")
        command_path = " ".join(str(match.group(2) or "").split()).strip(" .,:;!?\"")
        if not hook_name or not command_path:
            return None
        return {
            "hook_name": hook_name,
            "command_path": command_path,
            "arguments": [],
            "working_directory": None,
            "description": f"Trusted hook for {hook_name}.",
        }

    def _trusted_hook_execute_request(self, message: str, lower: str) -> dict[str, object] | None:
        match = re.match(r"^run trusted hook\s+(.+)$", message, flags=re.IGNORECASE)
        if not match:
            return None
        hook_name = " ".join(str(match.group(1) or "").split()).strip(" .,:;!?")
        if not hook_name:
            return None
        return {"hook_name": hook_name}

    def _maintenance_action_request(self, message: str, lower: str) -> dict[str, object] | None:
        del message
        if any(phrase in lower for phrase in {"archive old screenshots", "archive my old screenshots"}):
            return {"maintenance_kind": "archive_old_screenshots", "target_directory": None, "older_than_days": 14, "dry_run": False}
        if any(phrase in lower for phrase in {"clean up my downloads", "cleanup my downloads", "clean my downloads"}):
            return {"maintenance_kind": "downloads_cleanup", "target_directory": None, "older_than_days": 14, "dry_run": False}
        if "find stale large files" in lower:
            return {"maintenance_kind": "find_stale_large_files", "target_directory": None, "older_than_days": 30, "dry_run": True}
        return None

    def _trust_approval_request(
        self,
        lower: str,
        *,
        active_request_state: dict[str, Any],
    ) -> SemanticParseProposal | None:
        if not any(
            phrase in lower
            for phrase in {
                "why are you asking",
                "why do you need confirmation",
                "why do you need me to confirm",
                "what are you asking permission for",
                "what am i approving",
                "can i allow this just once",
                "can i approve this once",
            }
        ):
            return None
        trust = active_request_state.get("trust") if isinstance(active_request_state.get("trust"), dict) else {}
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        subject = str(
            active_request_state.get("subject")
            or parameters.get("target_name")
            or parameters.get("destination_alias")
            or "this action"
        ).strip()
        operation = str(parameters.get("operation_type") or parameters.get("request_stage") or "action").strip()
        reason = str(trust.get("reason") or "").strip()
        reason_sentence = f" {reason}" if reason else " It needs an explicit approval because the route can affect something outside a simple chat reply."
        return self._tool_proposal(
            query_shape=QueryShape.TRUST_APPROVAL_REQUEST,
            domain="trust",
            request_type_hint="trust_approval_explanation",
            family="trust_approvals",
            subject=subject,
            requested_action="explain_approval",
            confidence=0.97,
            evidence=["approval-explanation wording matched active trust state"],
            assistant_message=(
                f"I'm asking for approval before I continue with {subject}"
                f"{f' ({operation})' if operation and operation != 'action' else ''}."
                f"{reason_sentence}"
                " You can allow it once, deny it, or ask me to change the route."
            ),
            execution_type="explain_approval",
            output_mode=ResponseMode.SUMMARY_RESULT.value,
            output_type="trust",
            slots={
                "trust_request_id": str(trust.get("request_id") or "").strip() or None,
                "approval_reason": reason or None,
                "active_family": str(active_request_state.get("family") or "").strip() or None,
                "active_request_stage": str(parameters.get("request_stage") or "").strip() or None,
            },
        )

    def _search_correction_request(
        self,
        message: str,
        lower: str,
        *,
        active_request_state: dict[str, Any],
    ) -> SemanticParseProposal | None:
        parameters = self._active_search_parameters(active_request_state)
        if parameters is None:
            return None
        if not (
            lower.startswith(("no ", "no,", "nah ", "not "))
            or any(phrase in lower for phrase in {"not that", "instead", "the other one", "folder one", "file one"})
        ):
            return None
        prefer_folders = "folder" in lower or "directory" in lower
        query = str(parameters.get("query") or active_request_state.get("subject") or message).strip()
        search_request = {
            "query": query or message,
            "domains": ["files"],
            "action": "open",
            "open_target": str(parameters.get("open_target") or "external").strip() or "external",
            "latest_only": bool(parameters.get("latest_only", False)),
            "file_extensions": list(parameters.get("file_extensions") or []),
            "folder_hint": parameters.get("folder_hint"),
            "prefer_folders": prefer_folders,
        }
        return self._tool_proposal(
            query_shape=QueryShape.SEARCH_AND_OPEN,
            domain="files",
            tool_name="desktop_search",
            tool_arguments=search_request,
            request_type_hint="search_and_act",
            family="desktop_search",
            subject="search",
            requested_action="open",
            confidence=0.93,
            evidence=["correction phrase reused active desktop-search ambiguity"],
            follow_up=True,
            execution_type="search_then_open",
            output_mode=ResponseMode.SEARCH_RESULT.value,
            slots={
                "target_scope": "desktop",
                "support_augmentation": ["active request state"],
            },
        )

    def _deictic_open_request(
        self,
        message: str,
        lower: str,
        *,
        surface_mode: str,
        active_context: dict[str, Any],
    ) -> SemanticParseProposal | None:
        del message
        opener = re.match(
            r"^(?:please\s+|pls\s+|can\s+you\s+|could\s+you\s+)?(?:open|show|bring\s+up|pull\s+up|go\s+to)\b",
            lower,
        )
        basic_shorthand = any(
            lower == phrase or lower.startswith(f"{phrase} ")
            for phrase in {
                "open it",
                "open this",
                "open that",
                "show it",
                "show this",
                "show that",
                "bring it up",
                "pull it up",
            }
        )
        typed_referent = bool(re.search(r"\b(?:page|site|website|link|url|file|document|pdf)\b", lower))
        deictic_or_prior = bool(re.search(r"\b(?:it|this|that|these|those|previous|last|earlier|before|again)\b", lower))
        if not basic_shorthand and (opener is None or not typed_referent or not deictic_or_prior):
            return None
        candidates = self._recent_entity_open_candidates(active_context)
        if not candidates:
            return None
        kinds = {str(candidate.get("kind") or "").strip().lower() for candidate in candidates}
        if len(candidates) > 1 and {"page", "file"}.issubset(kinds):
            leading = candidates[0]
            message = "I think you mean the recent page, but a recent file is also still live. Which one should I open?"
            return self._tool_proposal(
                query_shape=QueryShape.OPEN_BROWSER_DESTINATION,
                domain="browser",
                request_type_hint="direct_action",
                family="browser_destination",
                subject="recent entity",
                requested_action="open_browser_destination",
                confidence=0.86,
                evidence=["deictic open matched multiple recent entity targets"],
                assistant_message=message,
                execution_type="resolve_url_then_open_in_browser",
                output_mode=ResponseMode.ACTION_RESULT.value,
                output_type="action",
                slots={
                    "clarification": {
                        "code": "ambiguous_open_target",
                        "message": message,
                        "missing_slots": ["target"],
                    },
                    "clarification_pressure": 0.86,
                    "missing_evidence": ["target"],
                    "target_scope": "browser",
                    "recent_entity_candidates": candidates,
                    "deictic_binding": {
                        "resolved": False,
                        "selected_source": "recent_session_entity",
                        "selected_target": {
                            "source": "recent_session_entity",
                            "target_type": str(leading.get("kind") or "page"),
                            "label": str(leading.get("title") or "recent entity"),
                            "value": leading.get("url") or leading.get("path"),
                            "confidence": float(leading.get("confidence") or 0.0),
                            "freshness": str(leading.get("freshness") or "recent"),
                        },
                        "candidates": [
                            {
                                "source": "recent_session_entity",
                                "target_type": str(candidate.get("kind") or "entity"),
                                "label": str(candidate.get("title") or "recent entity"),
                                "value": candidate.get("url") or candidate.get("path"),
                                "confidence": float(candidate.get("confidence") or 0.0),
                                "freshness": str(candidate.get("freshness") or "recent"),
                            }
                            for candidate in candidates
                        ],
                        "unresolved_reason": "multiple_live_binding_candidates",
                        "binding_posture": "ambiguous",
                        "source_summary": "Multiple recent entities remain live for this open request.",
                    },
                },
            )
        selected = candidates[0]
        url = str(selected.get("url") or "").strip()
        path = str(selected.get("path") or "").strip()
        title = str(selected.get("title") or selected.get("name") or url or path or "recent entity").strip()
        open_in_deck = surface_mode.strip().lower() == "deck" or " deck" in lower
        if url:
            tool_name = "deck_open_url" if open_in_deck else "external_open_url"
            tool_arguments = {"url": url}
            family = "browser_destination"
            query_shape = QueryShape.OPEN_BROWSER_DESTINATION
            domain = "browser"
            requested_action = "open_browser_destination"
            execution_type = "resolve_url_then_open_in_browser"
        else:
            tool_name = "deck_open_file" if open_in_deck else "external_open_file"
            tool_arguments = {"path": path}
            family = "files"
            query_shape = QueryShape.CONTEXT_ACTION
            domain = "files"
            requested_action = "open_file"
            execution_type = "execute_control_command"
        return self._tool_proposal(
            query_shape=query_shape,
            domain=domain,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            request_type_hint="direct_action",
            family=family,
            subject=title,
            requested_action=requested_action,
            confidence=0.94,
            evidence=["deictic open bound to a single recent entity"],
            execution_type=execution_type,
            output_mode=ResponseMode.ACTION_RESULT.value,
            output_type="action",
            slots={
                "target_scope": "browser" if url else "files",
                "deictic_binding": {
                    "resolved": True,
                    "selected_source": "recent_session_entity",
                    "selected_target": {
                        "source": "recent_session_entity",
                        "target_type": str(selected.get("kind") or ("page" if url else "file")),
                        "label": title,
                        "value": url or path,
                        "confidence": float(selected.get("confidence") or 0.78),
                        "freshness": str(selected.get("freshness") or "recent"),
                    },
                    "binding_posture": "current" if str(selected.get("freshness") or "recent") in {"current", "recent"} else "continuity_reuse",
                    "source_summary": "Bound deictic open request from the freshest recent entity.",
                },
            },
        )

    def _recent_entity_open_candidates(self, active_context: dict[str, Any]) -> list[dict[str, Any]]:
        recent_entities = active_context.get("recent_entities")
        if not isinstance(recent_entities, list):
            return []
        candidates: list[dict[str, Any]] = []
        for index, entity in enumerate(recent_entities):
            if not isinstance(entity, dict):
                continue
            url = str(entity.get("url") or "").strip()
            path = str(entity.get("path") or "").strip()
            if not url and not path:
                continue
            title = str(entity.get("title") or entity.get("name") or url or path or "recent entity").strip()
            freshness = self._entity_freshness(entity, index=index)
            confidence = self._recent_entity_confidence(freshness)
            candidates.append(
                {
                    "title": title,
                    "kind": str(entity.get("kind") or ("page" if url else "file")).strip(),
                    "url": url or None,
                    "path": path or None,
                    "freshness": freshness,
                    "confidence": confidence,
                }
            )
        candidates.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
        return candidates

    def _relay_payload_hint_from_context(self, active_context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
        if selection.get("value"):
            candidates.append(
                {
                    "source": "selection",
                    "target_type": str(selection.get("kind") or "selected_text"),
                    "label": str(selection.get("preview") or "selected text"),
                    "value": selection.get("value"),
                    "confidence": 0.9,
                    "freshness": "current",
                }
            )
        clipboard = active_context.get("clipboard") if isinstance(active_context.get("clipboard"), dict) else {}
        if clipboard.get("value"):
            candidates.append(
                {
                    "source": "clipboard",
                    "target_type": str(clipboard.get("kind") or "clipboard"),
                    "label": str(clipboard.get("preview") or "clipboard"),
                    "value": clipboard.get("value"),
                    "confidence": 0.84,
                    "freshness": "current",
                }
            )
        if len(candidates) > 1:
            message = 'This looks like a relay request, but I still need to know whether "this" means the selected text or the clipboard.'
            return (
                "contextual",
                {
                    "clarification": {
                        "code": "ambiguous_relay_payload",
                        "message": message,
                        "missing_slots": ["payload"],
                    },
                    "clarification_pressure": 0.85,
                    "missing_evidence": ["payload"],
                    "deictic_binding": {
                        "resolved": False,
                        "candidates": candidates,
                        "unresolved_reason": "multiple_live_binding_candidates",
                        "binding_posture": "ambiguous",
                        "source_summary": "The relay route still needs a payload binding between current sources.",
                    },
                },
            )
        if not candidates:
            return (
                "contextual",
                {
                    "missing_evidence": ["payload"],
                    "deictic_binding": {
                        "resolved": False,
                        "candidates": [],
                        "unresolved_reason": "no_current_binding_source",
                    },
                },
            )
        selected = candidates[0]
        target_type = str(selected.get("target_type") or "").strip().lower()
        payload_hint = "selected_text"
        if target_type in {"url", "page", "link"}:
            payload_hint = "page_link"
        elif target_type in {"file", "path", "document"}:
            payload_hint = "file"
        elif selected.get("source") == "clipboard":
            payload_hint = "clipboard"
        return (
            payload_hint,
            {
                "deictic_binding": {
                    "resolved": True,
                    "selected_source": selected["source"],
                    "selected_target": selected,
                    "candidates": candidates,
                }
            },
        )

    def _discord_relay_request(
        self,
        message: str,
        lower: str,
        *,
        active_request_state: dict[str, Any],
        active_context: dict[str, Any],
    ) -> SemanticParseProposal | None:
        family = str(active_request_state.get("family") or "").strip().lower()
        parameters = active_request_state.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}

        if family == "discord_relay" and self._looks_like_discord_relay_confirmation(lower):
            pending_preview = parameters.get("pending_preview") if isinstance(parameters.get("pending_preview"), dict) else {}
            destination_alias = str(parameters.get("destination_alias") or "").strip()
            trust = active_request_state.get("trust") if isinstance(active_request_state.get("trust"), dict) else {}
            approval_outcome = "deny" if lower in {"no", "deny", "cancel", "stop"} else "approve"
            approval_scope = "session" if "session" in lower else "once"
            if pending_preview and destination_alias:
                return self._tool_proposal(
                    query_shape=QueryShape.DISCORD_RELAY_REQUEST,
                    domain="discord_relay",
                    request_type_hint="discord_relay_dispatch",
                    family="discord_relay",
                    subject=destination_alias,
                    requested_action="dispatch",
                    confidence=0.99,
                    evidence=["follow-up confirmation matched a pending Discord relay preview"],
                    follow_up=True,
                    execution_type="discord_relay_dispatch",
                    output_mode=ResponseMode.ACTION_RESULT.value,
                    output_type="action",
                    slots={
                        "destination_alias": destination_alias,
                        "payload_hint": str(parameters.get("payload_hint") or "contextual"),
                        "note_text": str(parameters.get("note_text") or "").strip() or None,
                        "request_stage": "dispatch",
                        "pending_preview": pending_preview,
                        "approval_scope": approval_scope,
                        "approval_outcome": approval_outcome,
                        "trust_request_id": str(trust.get("request_id") or "").strip() or None,
                    },
                )

        if family == "discord_relay":
            ambiguity_choices = parameters.get("ambiguity_choices") if isinstance(parameters.get("ambiguity_choices"), list) else []
            payload_choice = self._discord_follow_up_payload_hint(lower)
            if ambiguity_choices and payload_choice in {str(choice) for choice in ambiguity_choices}:
                destination_alias = str(parameters.get("destination_alias") or "").strip()
                return self._tool_proposal(
                    query_shape=QueryShape.DISCORD_RELAY_REQUEST,
                    domain="discord_relay",
                    request_type_hint="discord_relay_dispatch",
                    family="discord_relay",
                    subject=destination_alias or "discord",
                    requested_action="preview",
                    confidence=0.95,
                    evidence=["follow-up payload clarification resolved a pending Discord relay ambiguity"],
                    follow_up=True,
                    execution_type="discord_relay_preview",
                    output_mode=ResponseMode.ACTION_RESULT.value,
                    output_type="action",
                    slots={
                        "destination_alias": destination_alias,
                        "payload_hint": {
                            "page": "page_link",
                            "file": "file",
                            "text": "selected_text",
                            "note": "note_artifact",
                            "screenshot": "screenshot_candidate",
                        }.get(payload_choice, "contextual"),
                        "note_text": str(parameters.get("note_text") or "").strip() or None,
                        "request_stage": "preview",
                    },
                )

        match = None
        relay_patterns = (
            r"^(?:send|share|post|message|relay|forward|dm)\s+(?P<payload>.+?)\s+(?:to|for)\s+(?P<destination>.+?)(?:\s+(?:on|in|via|through)\s+discord)?(?:\s+with(?:\s+a)?\s+note(?:\s*[:\-]?\s*(?P<note>.+))?)?$",
            r"^pass\s+(?P<payload>.+?)\s+along\s+(?:to|for)\s+(?P<destination>.+?)(?:\s+(?:on|in|via|through)\s+discord)?(?:\s+with(?:\s+a)?\s+note(?:\s*[:\-]?\s*(?P<note>.+))?)?$",
        )
        for pattern in relay_patterns:
            match = re.match(pattern, message, flags=re.IGNORECASE)
            if match:
                break
        if not match:
            match = re.match(
                r"^message\s+(?P<destination>.+?)\s+(?P<payload>this|that|it|these|those|.+?)(?:\s+with(?:\s+a)?\s+note(?:\s*[:\-]?\s*(?P<note>.+))?)?$",
                message,
                flags=re.IGNORECASE,
            )
        if not match:
            if self._looks_like_discord_relay_missing_destination(lower):
                return self._tool_proposal(
                    query_shape=QueryShape.DISCORD_RELAY_REQUEST,
                    domain="discord_relay",
                    request_type_hint="discord_relay_dispatch",
                    family="discord_relay",
                    subject="discord",
                    requested_action="preview",
                    confidence=0.84,
                    evidence=["discord relay wording matched but the destination was missing"],
                    execution_type="discord_relay_preview",
                    output_mode=ResponseMode.CLARIFICATION.value,
                    output_type="action",
                    slots={
                        "clarification": {
                            "code": "missing_discord_destination",
                            "message": "Which Discord destination should I use?",
                            "missing_slots": ["destination"],
                        },
                        "payload_hint": self._discord_payload_hint(lower),
                        "missing_preconditions": ["destination"],
                        "request_stage": "clarification",
                    },
                )
            return None
        payload_phrase = " ".join(str(match.group("payload") or "").split()).strip(" .,:;!?")
        destination_alias = " ".join(str(match.group("destination") or "").split()).strip(" .,:;!?")
        destination_alias = re.sub(
            r"\s+(?:on|in|via|through)\s+discord$",
            "",
            destination_alias,
            flags=re.IGNORECASE,
        ).strip(" .,:;!?")
        if not payload_phrase or not destination_alias:
            return None
        note_text = " ".join(str(match.group("note") or "").split()).strip() or None
        payload_hint = self._discord_payload_hint(payload_phrase)
        extra_slots: dict[str, Any] = {}
        if normalize_phrase(payload_phrase) in {"this", "that", "it", "these", "those"}:
            payload_hint, extra_slots = self._relay_payload_hint_from_context(active_context)
        return self._tool_proposal(
            query_shape=QueryShape.DISCORD_RELAY_REQUEST,
            domain="discord_relay",
            request_type_hint="discord_relay_dispatch",
            family="discord_relay",
            subject=destination_alias,
            requested_action="preview",
            confidence=0.95,
            evidence=["discord relay phrasing matched a trusted-send request"],
            execution_type="discord_relay_preview",
            output_mode=ResponseMode.ACTION_RESULT.value,
            output_type="action",
            slots={
                "destination_alias": destination_alias,
                "payload_hint": payload_hint,
                "note_text": note_text,
                "request_stage": "preview",
                **extra_slots,
            },
        )

    def _discord_payload_hint(self, payload_phrase: str) -> str:
        lower = normalize_phrase(payload_phrase)
        if any(token in lower for token in {"page", "link", "url", "article", "site"}):
            return "page_link"
        if any(token in lower for token in {"file", "document", "doc", "pdf"}):
            return "file"
        if any(token in lower for token in {"selection", "selected text", "highlight", "quote", "text"}):
            return "selected_text"
        if any(token in lower for token in {"note", "artifact"}):
            return "note_artifact"
        if "screenshot" in lower:
            return "screenshot_candidate"
        return "contextual"

    def _looks_like_discord_relay_missing_destination(self, lower: str) -> bool:
        if "discord" not in lower:
            return False
        relay_verb = re.match(r"^(?:please\s+|pls\s+)?(?:send|share|post|message|relay|forward|dm|pass)\b", lower)
        has_destination = bool(re.search(r"\b(?:to|for)\s+\w+", lower))
        return bool(relay_verb and not has_destination)

    def _looks_like_discord_relay_confirmation(self, lower: str) -> bool:
        cleaned = " ".join(str(lower or "").split()).strip()
        return cleaned in DISCORD_RELAY_CONFIRM_PHRASES or cleaned in {"no", "deny", "cancel", "stop"}

    def _discord_follow_up_payload_hint(self, lower: str) -> str | None:
        cleaned = " ".join(str(lower or "").split()).strip()
        if cleaned in {"page", "link", "url"}:
            return "page"
        if cleaned in {"file", "document", "doc"}:
            return "file"
        if cleaned in {"text", "selection", "selected text"}:
            return "text"
        if cleaned in {"note", "artifact"}:
            return "note"
        if cleaned == "screenshot":
            return "screenshot"
        return None

    def _file_operation_request(self, message: str, lower: str) -> dict[str, object] | None:
        del message
        if any(phrase in lower for phrase in {"rename these screenshots by date", "rename my screenshots by date"}):
            return {"operation": "rename_by_date", "target_mode": "screenshots_default", "dry_run": False, "source_paths": []}
        if "find duplicates in this folder" in lower:
            return {"operation": "find_duplicates", "target_mode": "explicit", "dry_run": True, "source_paths": []}
        return None

    def _workflow_execution_request(self, message: str, lower: str) -> dict[str, object] | None:
        del message
        if re.search(r"\b(?:set\s+up|setup|open)\b.{0,24}\bwriting\b.{0,18}\b(?:environment|setup)\b", lower) or re.search(
            r"\bwriting\b.{0,18}\bsetup\b",
            lower,
        ):
            return {"workflow_kind": "writing_setup"}
        if any(phrase in lower for phrase in {"prepare a diagnostics setup", "diagnostics setup"}):
            return {"workflow_kind": "diagnostics_setup"}
        if any(phrase in lower for phrase in {"research setup", "set up my research environment", "open my research setup"}):
            return {"workflow_kind": "research_setup"}
        if any(phrase in lower for phrase in {"open my current work context", "open my current context", "current work context"}):
            return {"workflow_kind": "current_work_context"}
        if any(phrase in lower for phrase in {"open my project stuff", "project setup", "set up my project environment", "open the project setup"}):
            return {"workflow_kind": "project_setup"}
        return None

    def _activity_summary_request(self, message: str, lower: str) -> dict[str, object] | None:
        del message
        if lower in {"what did i miss", "what did i miss?", "what happened while i was away"}:
            return {"query": "what did I miss?"}
        if any(phrase in lower for phrase in {"summarize recent signals", "summarize recent activity", "what changed in the last few minutes", "what completed", "what failed"}):
            return {"query": lower}
        return None

    def _browser_context_request(
        self,
        message: str,
        lower: str,
        *,
        active_context: dict[str, Any] | None,
    ) -> dict[str, object] | None:
        del active_context
        if any(phrase in lower for phrase in {"add this page to the workspace", "add this article to the workspace", "add this page as a reference"}):
            return {"operation": "add_to_workspace", "query": message}
        if any(phrase in lower for phrase in {"collect the references from these tabs", "collect references from these tabs", "pull in the browser references related to this project"}):
            return {"operation": "collect_references", "query": message}
        if any(phrase in lower for phrase in {"summarize this article", "summarize this page", "summarize the current page"}):
            return {"operation": "summarize", "query": message}
        if re.search(r"\b(?:what|which)\b.{0,24}\b(?:browser\s+)?(?:page|tab)\b.{0,24}\bam\s+i\s+on\b", lower) or re.search(
            r"\bcurrent\b.{0,16}\b(?:browser\s+)?(?:page|tab)\b",
            lower,
        ):
            return {"operation": "current_page", "query": message}
        if any(phrase in lower for phrase in {"show me the source i was just reading", "find the page i was just reading", "find the page from earlier"}):
            return {"operation": "recent_page", "query": message}
        if any(phrase in lower for phrase in {"find the tab", "find the page", "bring up the page", "bring that page forward"}) or (" tab " in lower and lower.startswith(("find ", "show ", "bring "))) or ("page about" in lower and any(lower.startswith(prefix) for prefix in {"find ", "show ", "bring "})):
            return {"operation": "find", "query": message}
        return None

    def _browser_destination_request(
        self,
        message: str,
        lower: str,
        *,
        surface_mode: str,
    ) -> SemanticParseProposal | None:
        if self._looks_like_deictic_browser_destination(lower):
            return self._browser_destination_context_clarification(message, lower)
        if self._browser_destination_resolver.intent_type(lower) != BrowserIntentType.OPEN_DESTINATION:
            return None
        request = self._browser_destination_resolver.parse(message, surface_mode=surface_mode)
        if request is None:
            return None

        resolution = self._browser_destination_resolver.resolve(request)
        failure_reason = resolution.failure_reason or BrowserOpenFailureReason.DESTINATION_UNRESOLVED
        response_contract = (
            self._browser_destination_resolver.response_contract_for_success(resolution)
            if resolution.success
            else self._browser_destination_resolver.response_contract_for_failure(failure_reason)
        )
        slots: dict[str, Any] = {
            "target_scope": "browser",
            "browser_intent_type": request.intent_type.value,
            "destination_type": resolution.resolution_kind or "known_web_destination",
            "destination_scope": request.scope.value,
            "browser_preference": request.browser_preference,
            "open_target": request.open_target,
            "browser_destination_request": request.to_dict(),
            "destination_resolution": resolution.to_dict(),
            "destination_resolution_kind": resolution.resolution_kind,
            "destination_site_domain": resolution.site_domain,
            "resolved_destination_title": resolution.display_title,
            "response_contract": dict(response_contract),
            "unsupported_response_contract": self._browser_destination_resolver.response_contract_for_failure(
                BrowserOpenFailureReason.BROWSER_OPEN_UNAVAILABLE
            ),
            "legacy_routes_bypassed": {
                "desktop_search": True,
                "app_control": True,
            },
        }
        evidence = [
            "browser destination intent detected",
            "desktop-search route bypassed",
            "app-control route bypassed",
            *resolution.notes,
        ]
        if resolution.success and resolution.url is not None:
            open_plan = self._browser_destination_resolver.build_open_plan(resolution)
            slots["browser_open_plan"] = open_plan.to_dict()
            if resolution.destination is not None:
                slots["destination_name"] = resolution.destination.key
                slots["known_destination_mapping"] = resolution.destination.to_dict()
            elif resolution.site_domain:
                slots["destination_name"] = resolution.site_domain
            return self._tool_proposal(
                query_shape=QueryShape.OPEN_BROWSER_DESTINATION,
                domain="browser",
                tool_name=open_plan.tool_name,
                tool_arguments=open_plan.tool_arguments,
                request_type_hint="direct_action",
                family="browser_destination",
                subject=slots.get("destination_name") or resolution.display_title or request.destination_phrase,
                requested_action="open_browser_destination",
                confidence=0.97,
                evidence=evidence,
                execution_type="resolve_url_then_open_in_browser",
                output_mode=ResponseMode.ACTION_RESULT.value,
                slots=slots,
            )

        slots["browser_open_failure_reason"] = failure_reason.value
        slots["destination_type"] = "unresolved_web_destination"
        return self._tool_proposal(
            query_shape=QueryShape.OPEN_BROWSER_DESTINATION,
            domain="browser",
            request_type_hint="direct_action",
            family="browser_destination",
            subject=request.destination_phrase or "browser_destination",
            requested_action="open_browser_destination",
            confidence=0.9,
            evidence=evidence,
            assistant_message=response_contract["full_response"],
            execution_type="resolve_url_then_open_in_browser",
            output_mode=ResponseMode.ACTION_RESULT.value,
            slots=slots,
        )

    def _looks_like_deictic_browser_destination(self, lower: str) -> bool:
        opener = re.match(r"^(?:please\s+|pls\s+|can\s+you\s+|could\s+you\s+)?(?:open|show|bring\s+up|pull\s+up|go\s+to)\b", lower)
        if opener is None:
            return False
        web_referent = bool(re.search(r"\b(?:website|web\s+site|site|page|link|url)\b", lower))
        deictic_or_prior = bool(re.search(r"\b(?:this|that|these|those|previous|last|earlier|before)\b", lower))
        return web_referent and deictic_or_prior

    def _browser_destination_context_clarification(self, message: str, lower: str) -> SemanticParseProposal:
        target = re.sub(
            r"^(?:please\s+|pls\s+|can\s+you\s+|could\s+you\s+)?(?:open|show|bring\s+up|pull\s+up|go\s+to)\s+",
            "",
            message,
            flags=re.IGNORECASE,
        ).strip(" .")
        clarification = {
            "code": "missing_browser_destination_context",
            "message": "Which website or page should I open? I need a URL, current page, or recent browser reference first.",
            "missing_slots": ["destination_context"],
        }
        return self._tool_proposal(
            query_shape=QueryShape.OPEN_BROWSER_DESTINATION,
            domain="browser",
            request_type_hint="browser_destination",
            family="browser_destination",
            subject=target or "browser_destination",
            requested_action="open_browser_destination",
            confidence=0.88,
            evidence=["browser destination deictic detected without bound website context", "app-control route bypassed"],
            assistant_message=clarification["message"],
            execution_type="resolve_url_then_open_in_browser",
            output_mode=ResponseMode.CLARIFICATION.value,
            slots={
                "target_scope": "browser",
                "clarification": clarification,
                "missing_preconditions": ["destination_context"],
                "browser_intent_type": "open_destination",
                "open_target": target,
                "fallback_reason": "missing_browser_destination_context",
                "legacy_routes_bypassed": {
                    "desktop_search": True,
                    "app_control": True,
                },
            },
        )

    def _browser_search_request(
        self,
        message: str,
        lower: str,
        *,
        surface_mode: str,
    ) -> SemanticParseProposal | None:
        if self._browser_destination_resolver.intent_type(lower) != BrowserIntentType.SEARCH_REQUEST:
            return None
        request = self._browser_destination_resolver.parse_search(message, surface_mode=surface_mode)
        if request is None:
            return None

        resolution = self._browser_destination_resolver.resolve_search(request)
        failure_reason = resolution.failure_reason or BrowserSearchFailureReason.SEARCH_PROVIDER_UNRESOLVED
        response_contract = (
            self._browser_destination_resolver.response_contract_for_search_success(resolution)
            if resolution.success
            else self._browser_destination_resolver.response_contract_for_search_failure(failure_reason)
        )
        slots: dict[str, Any] = {
            "target_scope": "browser",
            "browser_intent_type": request.intent_type.value,
            "search_provider": request.provider_key or "unresolved",
            "requested_search_provider_phrase": request.provider_phrase or request.provider_key or "",
            "search_query": request.query,
            "browser_preference": request.browser_preference,
            "open_target": request.open_target,
            "browser_search_request": request.to_dict(),
            "search_resolution": resolution.to_dict(),
            "response_contract": dict(response_contract),
            "unsupported_response_contract": self._browser_destination_resolver.response_contract_for_search_failure(
                BrowserSearchFailureReason.BROWSER_OPEN_UNAVAILABLE
            ),
            "legacy_routes_bypassed": {
                "desktop_search": True,
                "app_control": True,
                "browser_destination": True,
            },
        }
        evidence = [
            "browser search intent detected",
            "desktop-search route bypassed",
            "app-control route bypassed",
            "browser-destination route bypassed",
            *resolution.notes,
        ]
        if resolution.success and resolution.provider is not None:
            open_plan = self._browser_destination_resolver.build_search_open_plan(resolution)
            slots.update(
                {
                    "known_search_provider_mapping": resolution.provider.to_dict(),
                    "search_resolution_kind": resolution.resolution_kind,
                    "search_site_domain": resolution.site_domain,
                    "browser_open_plan": open_plan.to_dict(),
                }
            )
            return self._tool_proposal(
                query_shape=QueryShape.SEARCH_BROWSER_DESTINATION,
                domain="browser",
                tool_name=open_plan.tool_name,
                tool_arguments=open_plan.tool_arguments,
                request_type_hint="browser_search",
                family="browser_search",
                subject=resolution.provider.key,
                requested_action="search_browser_destination",
                confidence=0.96,
                evidence=evidence,
                execution_type="resolve_search_url_then_open_in_browser",
                output_mode=ResponseMode.ACTION_RESULT.value,
                slots=slots,
            )

        slots["browser_search_failure_reason"] = failure_reason.value
        return self._tool_proposal(
            query_shape=QueryShape.SEARCH_BROWSER_DESTINATION,
            domain="browser",
            request_type_hint="browser_search",
            family="browser_search",
            subject=request.query or request.provider_key or "browser_search",
            requested_action="search_browser_destination",
            confidence=0.9,
            evidence=evidence,
            assistant_message=response_contract["full_response"],
            execution_type="resolve_search_url_then_open_in_browser",
            output_mode=ResponseMode.ACTION_RESULT.value,
            slots=slots,
        )

    def _explicit_file_open_request(
        self,
        message: str,
        lower: str,
        *,
        surface_mode: str,
    ) -> SemanticParseProposal | None:
        if any(phrase in lower for phrase in {"without opening", "do not open", "don't open", "just tell me"}):
            return None
        if not any(lower.startswith(prefix) for prefix in {"open ", "show ", "bring up ", "pull up "}):
            return None
        match = re.search(r"(?<![A-Za-z])(?P<path>[A-Za-z]:[\\/][^\r\n]+)", message)
        if not match:
            return None
        path = " ".join(str(match.group("path") or "").split()).strip(" .,:;!?\"'")
        path = re.sub(
            r"\s+(?:externally|outside|in the deck|inside the deck|in deck|in the browser|in browser)$",
            "",
            path,
            flags=re.IGNORECASE,
        ).strip(" .,:;!?\"'")
        if not path:
            return None
        open_in_deck = surface_mode.strip().lower() == "deck" or " deck" in lower
        tool_name = "deck_open_file" if open_in_deck else "external_open_file"
        return self._tool_proposal(
            query_shape=QueryShape.CONTEXT_ACTION,
            domain="files",
            tool_name=tool_name,
            tool_arguments={"path": path},
            request_type_hint="direct_action",
            family="file",
            subject=path,
            requested_action="open_file",
            confidence=0.97,
            evidence=["explicit filesystem path open request detected before app-control matching"],
            execution_type="execute_control_command",
            output_mode=ResponseMode.ACTION_RESULT.value,
            output_type="action",
            slots={
                "target_scope": "files",
                "path": path,
                "open_target": "deck" if open_in_deck else "external",
                "target_extraction_summary": {
                    "source": "operator_text",
                    "kind": "filesystem_path",
                    "path": path,
                },
            },
        )

    def _desktop_search_request(self, message: str, lower: str, *, surface_mode: str) -> dict[str, object] | None:
        if self._browser_destination_resolver.intent_type(lower) == BrowserIntentType.SEARCH_REQUEST:
            return None
        explicit_search = any(lower.startswith(prefix) for prefix in {"find ", "search ", "pull up ", "locate "}) or " find " in lower
        open_style_lookup = any(lower.startswith(prefix) for prefix in FILE_LOOKUP_PREFIXES)
        folder_hint = self._extract_known_folder_hint(lower)
        prefer_folders = any(token in lower for token in {"folder", "directory"})
        if not explicit_search and not open_style_lookup:
            return None
        if open_style_lookup and folder_hint is None and self._looks_like_active_item_follow_up_phrase(lower):
            return None
        if open_style_lookup and not self._looks_like_file_lookup(lower, folder_hint=folder_hint):
            return None

        action = "open" if open_style_lookup or any(token in lower for token in {"open it", "open them", "and open", "bring it up", "show them", "show it"}) else "search"
        if explicit_search:
            query = re.sub(r"^(?:find|search|pull up|locate)\s+", "", message, flags=re.IGNORECASE).strip()
            query = re.sub(r"\s+(?:and\s+)?(?:open|show|bring up)\s+(?:it|them|that|those)?\s*$", "", query, flags=re.IGNORECASE).strip(" .")
        else:
            query = re.sub(r"^(?:open|show|bring up|pull up)\s+", "", message, flags=re.IGNORECASE).strip()
        query = self._strip_folder_phrase(query, folder_hint)
        latest_only = any(token in lower for token in {"latest", "most recent", "recent"})
        file_extensions: list[str] = []
        if "pdf" in lower:
            file_extensions.append(".pdf")
        if "cad" in lower:
            file_extensions.extend([".dwg", ".dxf", ".step", ".stp", ".sldprt", ".sldasm", ".ipt", ".iam"])
        if any(token in lower for token in {"note", "notes", "markdown"}):
            file_extensions.extend(sorted({*NOTE_EXTENSIONS}))
        if folder_hint or any(token in lower for token in {"pdf", "file", "files", "downloads", "download", "doc", "docs", "document", "notes", "folder", "cad", "desktop", "pictures", "documents"}):
            domains = ["files"]
        elif any(token in lower for token in {"window", "tab"}):
            domains = ["windows"]
        elif any(token in lower for token in {"app", "application"}):
            domains = ["apps"]
        else:
            domains = ["files", "apps", "windows"]
        open_target = "deck" if surface_mode.strip().lower() == "deck" or "deck" in lower else "external"
        return {
            "query": query or message,
            "domains": domains,
            "action": action,
            "open_target": open_target,
            "latest_only": latest_only,
            "file_extensions": file_extensions,
            "folder_hint": folder_hint,
            "prefer_folders": prefer_folders,
        }

    def _looks_like_file_lookup(self, lower: str, *, folder_hint: str | None) -> bool:
        if folder_hint:
            return True
        return any(f" {token}" in f" {lower}" for token in FILE_LOOKUP_HINTS)

    def _extract_known_folder_hint(self, lower: str) -> str | None:
        for label, aliases in KNOWN_FOLDER_ALIASES.items():
            for alias in aliases:
                pattern = rf"\b(?:in|inside|within|from|under|at)\s+{re.escape(alias)}\b"
                if re.search(pattern, lower):
                    return label
                if lower == alias or lower.endswith(f" {alias}"):
                    return label
        return None

    def _strip_folder_phrase(self, text: str, folder_hint: str | None) -> str:
        cleaned = str(text or "").strip()
        if not folder_hint:
            return cleaned.strip(" .")
        cleaned = re.sub(
            rf"\s+(?:in|inside|within|from|under|at)\s+(?:my\s+|the\s+)?{re.escape(folder_hint)}(?:\s+folder)?\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip(" .")

    def _looks_like_active_item_follow_up_phrase(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "show me that in the deck",
                "show that in the deck",
                "open that in the deck",
                "show the pdf in deck",
                "show that pdf in deck",
                "open the pdf in deck",
                "show the file in deck",
                "show the page in deck",
                "open it in the deck",
                "show it in the deck",
                "show me the same file again",
                "open the same file again",
                "show me the same page again",
            }
        )

    def _repair_action_request(self, message: str, lower: str) -> dict[str, object] | None:
        if any(
            phrase in lower
            for phrase in {
                "try fixing my wi fi",
                "try fixing my wi-fi",
                "try fixing my wifi",
                "try fixing my network",
                "try fixing wi fi",
                "try fixing wi-fi",
                "try fixing wifi",
                "fix my wi fi",
                "fix my wi-fi",
                "fix my wifi",
                "fix my network",
                "fix wi fi",
                "fix wi-fi",
                "fix wifi",
            }
        ):
            return {"repair_kind": "network_repair", "target": "wi-fi"}
        if any(phrase in lower for phrase in {"run connectivity checks", "check my connection", "connectivity checks", "run a 60 second network check", "run a 60-second network check"}):
            return {"repair_kind": "connectivity_checks", "target": "network"}
        if "flush dns" in lower:
            return {"repair_kind": "flush_dns", "target": "dns"}
        if any(phrase in lower for phrase in {"restart the network adapter", "restart network adapter"}):
            return {"repair_kind": "restart_network_adapter", "target": "network adapter"}
        if any(phrase in lower for phrase in {"restart explorer", "restart windows explorer"}):
            return {"repair_kind": "restart_explorer", "target": "explorer"}
        relaunch_match = re.match(r"^(?:relaunch|reopen)\s+(.+?)\s+(?:cleanly|from scratch)$", lower)
        if relaunch_match:
            raw_target = message[relaunch_match.start(1) : relaunch_match.end(1)]
            candidate = self._normalize_app_candidate(raw_target)
            if candidate:
                return {"repair_kind": "relaunch_app", "target": candidate}
        return None

    def _context_action_request(
        self,
        message: str,
        lower: str,
        *,
        active_context: dict[str, Any] | None,
    ) -> dict[str, object] | None:
        del message
        active_context = active_context or {}
        selection = active_context.get("selection") if isinstance(active_context.get("selection"), dict) else {}
        clipboard = active_context.get("clipboard") if isinstance(active_context.get("clipboard"), dict) else {}

        def has_payload(descriptor: dict[str, Any]) -> bool:
            return bool(isinstance(descriptor, dict) and descriptor.get("value"))

        def preferred_source(explicit: str | None = None) -> str | None:
            if explicit == "selection" and has_payload(selection):
                return "selection"
            if explicit == "clipboard" and has_payload(clipboard):
                return "clipboard"
            if has_payload(selection):
                return "selection"
            if has_payload(clipboard):
                return "clipboard"
            return None

        if lower in {"what was i just doing", "what s my current context", "what is my current context"}:
            return {"operation": "inspect"}

        if re.search(r"\b(?:continue|resume|pick\s+up)\b.{0,28}\b(?:that|there|where\s+(?:i|we)\s+left\s+off)\b", lower):
            return {"operation": "restore_context"}

        if any(phrase in lower for phrase in {"what i copied", "the thing i copied", "clipboard"}) and lower.startswith(("open ", "show ")):
            source = preferred_source("clipboard")
            if source:
                return {"operation": "open", "source": source}

        selected_text_reference = bool(
            re.search(
                r"\b(?:open|show|display|bring\s+up)\b.{0,32}\b(?:selected\s+text|highlighted\s+text|what\s+i\s+highlighted|selection)\b",
                lower,
            )
        )
        if selected_text_reference and not any(phrase in lower for phrase in {"selection bias", "selection criteria"}):
            source = preferred_source("selection")
            if source:
                return {"operation": "open", "source": source}
            return {
                "clarification": {
                    "code": "missing_context_selection",
                    "message": "I can open the selected text, but I need an active selection or clipboard context first.",
                    "missing_slots": ["context"],
                },
                "operation": "open",
                "source": "selection",
            }

        if any(phrase in lower for phrase in {"turn this into tasks", "make tasks from this", "turn that into tasks", "make tasks from that"}):
            source = preferred_source()
            if source:
                return {"operation": "extract_tasks", "source": source}

        if any(phrase in lower for phrase in {"turn the clipboard into tasks", "turn clipboard into tasks", "make tasks from the clipboard"}):
            source = preferred_source("clipboard")
            if source:
                return {"operation": "extract_tasks", "source": source}

        if any(phrase in lower for phrase in {"turn the selection into tasks", "turn selection into tasks", "make tasks from the selection"}):
            source = preferred_source("selection")
            if source:
                return {"operation": "extract_tasks", "source": source}

        return None

    def _guardrail_message(
        self,
        message: str,
        lower: str,
        *,
        active_context: dict[str, Any] | None,
    ) -> str | None:
        del active_context
        if lower.startswith(("delete ", "remove ")):
            if re.match(r"^remove\s+.+?\s+from\s+(?:this|my|the)\s+(?:machine|computer|pc)$", lower):
                return None
            target = re.sub(r"^(?:delete|remove)\s+", "", message, flags=re.IGNORECASE).strip(" .")
            normalized_target = normalize_phrase(target)
            if normalized_target in {"this", "that", "it", "these", "those", "that folder", "this folder", "that file", "this file"}:
                return "Delete scope is too broad without a clearer target."
            return "Destructive deletion isn't available through Stormhelm yet."
        return None

    def _guardrail_route_family(self, lower: str) -> str:
        if lower.startswith(("delete ", "remove ")):
            if re.match(r"^remove\s+.+?\s+from\s+(?:this|my|the)\s+(?:machine|computer|pc)$", lower):
                return ""
            return "file_operation"
        return ""

    def _unsupported_browser_automation_message(self, reason: str) -> str:
        if reason == "form_submit":
            return "Form submission is unsupported in the Playwright Screen Awareness path."
        if reason == "login":
            return "Login automation is unsupported. Stormhelm will not enter credentials or sign in for you."
        if reason == "transaction_or_payment":
            return "Purchases, payments, and checkout automation are unsupported."
        if reason == "captcha_or_human_verification":
            return "CAPTCHA, robot, and human-verification bypasses are unsupported. Stormhelm will not automate them."
        return "Arbitrary browser automation is unsupported. Stormhelm only runs explicitly gated safe browser primitives."

    def _app_control_request(self, message: str, lower: str) -> dict[str, object] | None:
        if lower.startswith("open up "):
            return None
        if any(token in lower for token in {" setup", " environment", "workspace", "context"}) and not any(
            lower.startswith(prefix) for prefix in {"force quit ", "quit ", "exit ", "close ", "restart ", "relaunch "}
        ):
            return None
        patterns = (
            (r"^(?:open)\s+(.+)$", "launch"),
            (r"^(?:focus|switch to|bring forward)\s+(.+)$", "focus"),
            (r"^(?:bring)\s+(.+?)\s+(?:forward|to front)$", "focus"),
            (r"^(?:minimize)\s+(.+)$", "minimize"),
            (r"^(?:maximize)\s+(.+)$", "maximize"),
            (r"^(?:restore|restore window|restore app|unminimize)\s+(.+)$", "restore"),
            (r"^(?:force quit|force close|kill)\s+(.+)$", "force_quit"),
            (r"^(?:quit|exit)\s+(.+)$", "quit"),
            (r"^(?:close)\s+(.+)$", "close"),
            (r"^(?:restart|relaunch)\s+(.+)$", "restart"),
            (r"^(?:launch|start)\s+(.+)$", "launch"),
        )
        for pattern, action in patterns:
            match = re.match(pattern, lower)
            if not match:
                continue
            candidate = self._normalize_app_candidate(message[match.start(1) :])
            if not candidate:
                return None
            return {
                "action": action,
                "app_name": candidate,
            }
        return None

    def _app_control_selection_follow_up(
        self,
        lower: str,
        *,
        active_request_state: dict[str, Any],
    ) -> dict[str, object] | None:
        normalized = normalize_phrase(lower)
        if normalized not in {"both", "all", "close both", "close all", "all of them"}:
            return None
        if str(active_request_state.get("family") or "").strip().lower() != "app_control":
            return None
        parameters = (
            active_request_state.get("parameters")
            if isinstance(active_request_state.get("parameters"), dict)
            else {}
        )
        action = str(
            parameters.get("action")
            or parameters.get("requested_action")
            or active_request_state.get("requested_action")
            or "close"
        ).strip().lower()
        if normalized.startswith("close "):
            action = "close"
        if action not in {"close", "quit"}:
            return None
        has_candidate_set = bool(
            parameters.get("selection_mode") == "ambiguous_candidate_set"
            or parameters.get("candidate_targets")
            or parameters.get("candidates")
        )
        if not has_candidate_set:
            return None
        target = str(
            parameters.get("app_name")
            or parameters.get("target_name")
            or active_request_state.get("subject")
            or ""
        ).strip()
        if not target or normalize_phrase(target) in {"both", "all", "all of them"}:
            return None
        return {"action": action, "app_name": target}

    def _window_control_request(self, message: str, lower: str) -> dict[str, object] | None:
        deictic_targets = {"this", "that", "this window", "that window", "current window", "focused window", "current app", "focused app"}

        close_match = re.match(r"^(?:close|quit|exit)\s+(.+)$", lower)
        if close_match:
            raw_target = " ".join(str(close_match.group(1) or "").split()).strip()
            normalized_target = normalize_phrase(raw_target)
            if normalized_target in deictic_targets:
                return {"action": "close", "target_mode": "focused"}

        direct_state = (
            (r"^(maximize|minimize|restore)\s+(.+)$", None),
        )
        for pattern, _ in direct_state:
            match = re.match(pattern, lower)
            if not match:
                continue
            action = str(match.group(1) or "").strip().lower()
            raw_target = " ".join(str(match.group(2) or "").split()).strip()
            normalized_target = normalize_phrase(raw_target)
            if normalized_target in deictic_targets:
                return {"action": action, "target_mode": "focused"}

        match = re.match(r"^snap\s+(.+?)\s+(?:to\s+)?(?:the\s+)?(left|right)$", lower)
        if match:
            raw_target = message[match.start(1) : match.end(1)]
            candidate = self._normalize_app_candidate(raw_target)
            direction = str(match.group(2) or "").strip().lower()
            return {
                "action": f"snap_{direction}",
                "target_mode": "focused" if candidate in {"this", "that"} or not candidate else "app",
                "app_name": None if candidate in {"this", "that"} else candidate,
            }

        match = re.match(r"^move\s+(.+?)\s+to\s+monitor\s+(\d+)$", lower)
        if match:
            raw_target = message[match.start(1) : match.end(1)]
            candidate = self._normalize_app_candidate(raw_target)
            return {
                "action": "move_to_monitor",
                "target_mode": "focused" if candidate in {"this", "that"} or not candidate else "app",
                "app_name": None if candidate in {"this", "that"} else candidate,
                "monitor_index": int(match.group(2)),
            }

        match = re.match(r"^move\s+(.+?)\s+(left|right|up|down)(?:\s+a\s+little)?$", lower)
        if match:
            raw_target = message[match.start(1) : match.end(1)]
            candidate = self._normalize_app_candidate(raw_target)
            direction = str(match.group(2) or "").strip().lower()
            delta_x = 0
            delta_y = 0
            if direction == "left":
                delta_x = -120
            elif direction == "right":
                delta_x = 120
            elif direction == "up":
                delta_y = -120
            else:
                delta_y = 120
            return {
                "action": "move_by",
                "target_mode": "focused" if candidate in {"this", "that"} or not candidate else "app",
                "app_name": None if candidate in {"this", "that"} else candidate,
                "delta_x": delta_x,
                "delta_y": delta_y,
            }

        if any(phrase in lower for phrase in {"make this smaller", "make that smaller", "make this bigger", "make this larger", "make that bigger", "make that larger"}):
            grow = any(token in lower for token in {"bigger", "larger"})
            return {
                "action": "resize_by",
                "target_mode": "focused",
                "delta_width": 180 if grow else -180,
                "delta_height": 120 if grow else -120,
            }
        return None

    def _system_control_request(self, message: str, lower: str) -> dict[str, object] | None:
        if any(phrase in lower for phrase in {"lock my computer", "lock the computer", "lock computer", "lock screen"}):
            return {"action": "lock"}
        if any(phrase in lower for phrase in {"unmute", "turn sound back on"}):
            return {"action": "unmute"}
        if any(phrase in lower for phrase in {"mute everything", "mute all", "mute the volume", "mute"}):
            return {"action": "mute"}
        match = re.search(r"(?:volume|sound).{0,20}?(\d{1,3})\s*%", lower)
        if match and any(token in lower for token in {"set", "to", "down", "up", "turn"}):
            return {"action": "set_volume", "value": max(0, min(int(match.group(1)), 100))}
        if any(phrase in lower for phrase in {"raise volume", "turn volume up", "volume up", "turn sound up"}):
            return {"action": "volume_up", "value": 10}
        if any(phrase in lower for phrase in {"lower volume", "turn volume down", "volume down", "turn sound down"}):
            value_match = re.search(r"(\d{1,3})\s*%", lower)
            if value_match:
                return {"action": "set_volume", "value": max(0, min(int(value_match.group(1)), 100))}
            return {"action": "volume_down", "value": 10}
        match = re.search(r"brightness.{0,20}?(\d{1,3})\s*%", lower)
        if match and "set" in lower:
            return {"action": "set_brightness", "value": max(0, min(int(match.group(1)), 100))}
        if any(phrase in lower for phrase in {"raise brightness", "brightness up", "turn brightness up"}):
            return {"action": "brightness_up", "value": 10}
        if any(phrase in lower for phrase in {"lower brightness", "brightness down", "turn brightness down"}):
            return {"action": "brightness_down", "value": 10}
        if any(phrase in lower for phrase in {"turn wi fi off", "turn wi-fi off", "turn wifi off", "wi fi off", "wi-fi off", "wifi off"}):
            return {"action": "toggle_wifi", "state": "off"}
        if any(phrase in lower for phrase in {"turn wi fi on", "turn wi-fi on", "turn wifi on", "wi fi on", "wi-fi on", "wifi on"}):
            return {"action": "toggle_wifi", "state": "on"}
        if any(phrase in lower for phrase in {"turn bluetooth off", "bluetooth off"}):
            return {"action": "toggle_bluetooth", "state": "off"}
        if any(phrase in lower for phrase in {"turn bluetooth on", "bluetooth on"}):
            return {"action": "toggle_bluetooth", "state": "on"}
        if "open task manager" in lower:
            return {"action": "open_task_manager"}
        if "open device manager" in lower:
            return {"action": "open_device_manager"}
        if any(phrase in lower for phrase in {"open resource monitor", "open resmon"}):
            return {"action": "open_resource_monitor"}
        settings_match = re.search(
            r"\b(?:open|bring\s+up|show)\s+(?P<target>bluetooth|wi\s*fi|wi-fi|wifi|network|sound|display|privacy)\s+settings?\b",
            lower,
        )
        if settings_match:
            target = settings_match.group("target").replace(" ", "").replace("-", "")
            return {"action": "open_settings_page", "target": "wifi" if target == "wifi" else target}
        return None

    def _normalize_app_candidate(self, raw: str) -> str:
        candidate = " ".join(str(raw or "").split()).strip(" .,:;!?")
        candidate = re.sub(r"^(?:the\s+)", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+(?:app|application)$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(
            r"\s+(?:externally|outside|in the deck|inside the deck|in deck|in the browser|in browser|in the systems|in systems|instead)$",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        normalized = normalize_phrase(candidate)
        if any(
            re.search(rf"\b{re.escape(marker)}\b", normalized)
            for marker in {
                "advice",
                "architecture",
                "concept",
                "concepts",
                "examples",
                "ideas",
                "marketing",
                "principles",
                "tutorial",
            }
        ):
            return ""
        if not normalized or normalized in {
            "deck",
            "ghost",
            "workspace",
            "weather",
            "settings",
            "location settings",
            "it",
            "this",
            "that",
            "thing",
            "the thing",
            "that thing",
            "this thing",
            "selected text",
            "highlighted text",
            "selection",
            "website",
            "web site",
            "site",
            "page",
            "link",
            "url",
            "that website",
            "this website",
            "that site",
            "this site",
            "that page",
            "this page",
            "that link",
            "this link",
            "layout",
            "saved layout",
            "deck layout",
            "panel launcher",
            "launcher",
        }:
            return ""
        if normalized.startswith(("selected ", "highlighted ", "selection ")):
            return ""
        if "thing" in normalized and any(reference in normalized for reference in {"mentioned", "that", "this", "the"}):
            return ""
        return normalized

    def _open_target(self, lower: str, *, previous: str, preferred: str = "none") -> str:
        if any(phrase in lower for phrase in {"do not open", "don't open", "just answer", "just tell me", "just get me", "without opening"}):
            return "none"
        if any(phrase in lower for phrase in {"in the deck", "inside the deck", "show me that in the deck", "show this in the deck", "show it in the deck", "show it internally"}):
            return "deck"
        if any(phrase in lower for phrase in {"open externally", "externally", "in the browser", "open it externally"}):
            return "external"
        return previous if previous != "none" else preferred

    def _location_mode(self, lower: str, *, previous: str) -> str:
        if any(token in lower for token in {"use my home location", "home location", "saved home", "my home"}):
            return "home"
        if any(token in lower for token in {"use my current location", "current location", "where am i"}):
            return "current"
        return previous

    def _allow_home_fallback(self, lower: str, *, previous: bool) -> bool:
        if any(token in lower for token in {"use my home location", "home location", "saved home", "my home"}):
            return False
        if any(token in lower for token in {"use my current location", "current location", "where am i"}):
            return False
        if self._location_reference_override(lower):
            return False
        return previous

    def _forecast_target(self, lower: str, *, previous: str) -> str:
        if "tomorrow" in lower:
            return "tomorrow"
        if "tonight" in lower:
            return "tonight"
        if "weekend" in lower:
            return "weekend"
        if any(token in lower for token in {"right now", "current weather", "weather right now", "current temperature"}):
            return "current"
        return previous

    def _location_source_follow_up_message(
        self,
        lower: str,
        *,
        active_request_state: dict[str, Any],
        recent_tool_results: list[dict[str, Any]],
    ) -> str | None:
        if not any(
            phrase in lower
            for phrase in {
                "which location did you use",
                "what weather source",
                "what location did you use",
                "is that my home location or current location",
            }
        ):
            return None
        family = str(active_request_state.get("family") or "").strip().lower()
        if family not in {"weather", "location"} and not recent_tool_results:
            return None
        latest = recent_tool_results[0] if recent_tool_results else {}
        result = latest.get("result")
        if not isinstance(result, dict):
            return None
        data = result.get("data")
        if not isinstance(data, dict):
            return None
        location = data.get("location") if isinstance(data.get("location"), dict) else data
        if not isinstance(location, dict):
            return None
        source = str(location.get("source") or "unknown").strip().lower()
        label = str(location.get("label") or location.get("name") or "the current area").strip()
        if source == "device_live":
            return f"Stormhelm used live device bearings for {label}."
        if source == "approximate_device":
            return f"Stormhelm used an approximate device fix near {label}."
        if source == "saved_home":
            return f"Stormhelm used the saved home location for {label}."
        if source == "saved_named":
            return f"Stormhelm used the saved named location for {label}."
        if source == "queried_place":
            return f"Stormhelm used the requested place bearings for {label}."
        if source == "ip_estimate":
            return f"Stormhelm only had an IP-based estimate near {label} for that weather solution."
        return None

    def _location_reference_override(self, lower: str) -> tuple[str, str] | None:
        named = self._named_location_override(lower)
        if named:
            return named, "saved_alias"
        explicit = self._explicit_place_query(lower)
        if explicit:
            return explicit, "place_query"
        return None

    def _named_location_override(self, lower: str) -> str | None:
        match = re.search(r"\b(?:use|for)\s+(?:my\s+)?(?!home\b|current\b)([a-z0-9][a-z0-9 \-]{0,40}?)\s+location\b", lower)
        if not match:
            return None
        candidate = " ".join(match.group(1).split()).strip()
        return candidate or None

    def _explicit_place_query(self, lower: str) -> str | None:
        sanitized = re.sub(r"[?.!]+$", "", lower.strip())
        cleanup_patterns = (
            r"\b(?:show|open)(?: me)?(?: it| this)? in the deck(?: instead)?\b",
            r"\b(?:show|open)(?: me)?(?: it| this)? internally(?: instead)?\b",
            r"\bopen it externally\b",
            r"\b(?:just answer|don't open anything|do not open anything|without opening)\b",
        )
        for pattern in cleanup_patterns:
            sanitized = re.sub(pattern, "", sanitized)
        patterns = (
            r"\b(?:weather|forecast|temperature(?: outside)?|outside)\b.*?\b(?:for|in|at)\s+(.+)$",
            r"\b(?:tomorrow|tonight|this weekend|weekend)\b.*?\b(?:for|in|at)\s+(.+)$",
            r"\buse\s+(.+?)\s+instead\b",
        )
        for pattern in patterns:
            match = re.search(pattern, sanitized)
            if not match:
                continue
            candidate = self._normalize_location_candidate(match.group(1))
            if self._location_candidate_allowed(candidate):
                return candidate
        return None

    def _normalize_location_candidate(self, raw: str) -> str:
        candidate = " ".join(raw.split()).strip(" ,.;:!?")
        candidate = re.sub(r"\b(?:instead|please)$", "", candidate).strip(" ,.;:!?")
        candidate = re.sub(r"\b(?:in the deck|inside the deck|internally|externally)$", "", candidate).strip(" ,.;:!?")
        return candidate

    def _location_candidate_allowed(self, candidate: str) -> bool:
        if not candidate:
            return False
        if candidate in {
            "the deck",
            "deck",
            "browser",
            "systems",
            "home",
            "current",
            "my home",
            "my current location",
            "tomorrow",
            "tonight",
            "this weekend",
            "weekend",
            "it",
            "that",
            "this",
        }:
            return False
        return len(candidate) >= 2

    def _recent_family(self, recent_tool_results: list[dict[str, Any]]) -> str | None:
        if not recent_tool_results:
            return None
        latest = recent_tool_results[0]
        family = latest.get("family")
        return str(family).strip().lower() if family else None

    def _extract_after_phrase(self, message: str, marker: str) -> str:
        _, found, tail = message.partition(marker)
        if not found:
            return ""
        return tail.strip().strip(".")

    def _extract_tags(self, message: str) -> list[str]:
        lower = message.lower()
        match = re.search(r"\btag\b.{0,28}\b(?:workspace|wrkspace)\b(?:\s+with)?\s+(?P<tags>.+)$", message, flags=re.IGNORECASE)
        if match:
            raw = str(match.group("tags") or "")
            raw = re.sub(r"\s+(?:real\s+quick|quick\s+quick|without\s+.*|if\s+that\s+is\s+the\s+right\s+route.*)$", "", raw, flags=re.IGNORECASE)
            raw = " ".join(raw.split()).strip(" .,:;!?\"'")
            if not raw:
                return []
            if "," in raw:
                return [part.strip() for part in raw.split(",") if part.strip()]
            return [raw]
        return []

    def _extract_workspace_list_query(self, message: str) -> str:
        lower = message.lower()
        for phrase in ("show my", "list my", "list", "show"):
            if lower.startswith(phrase):
                trimmed = message[len(phrase) :].strip()
                trimmed_lower = trimmed.lower()
                for token in ("recent workspaces", "archived workspaces", "workspaces"):
                    trimmed_lower = trimmed_lower.replace(token, "")
                return " ".join(trimmed_lower.split()).strip()
        return ""

    def _preference_value(self, learned_preferences: dict[str, dict[str, object]], scope: str, key: str) -> object | None:
        scope_bucket = learned_preferences.get(scope)
        if not isinstance(scope_bucket, dict):
            return None
        entry = scope_bucket.get(key)
        if not isinstance(entry, dict):
            return None
        if int(entry.get("count", 0)) < 2:
            return None
        return entry.get("value")
