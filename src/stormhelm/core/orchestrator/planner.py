from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.orchestrator.router import ToolRequest

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


@dataclass(slots=True)
class PlannerDecision:
    request_type: str = "unclassified"
    tool_requests: list[ToolRequest] = field(default_factory=list)
    assistant_message: str | None = None
    requires_reasoner: bool = False
    active_request_state: dict[str, object] = field(default_factory=dict)


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
    ) -> PlannerDecision:
        lower = normalize_phrase(message)
        if not lower:
            return PlannerDecision()

        guardrail_message = self._guardrail_message(message, lower, active_context=active_context)
        if guardrail_message:
            return PlannerDecision(request_type="guardrail_clarify", assistant_message=guardrail_message)

        system_control = self._system_control_request(message, lower)
        if system_control is not None:
            return PlannerDecision(
                request_type="direct_action",
                tool_requests=[ToolRequest("system_control", system_control)],
                active_request_state={
                    "family": "system_control",
                    "subject": "system_control",
                    "request_type": "direct_action",
                    "parameters": dict(system_control),
                },
            )

        window_control = self._window_control_request(message, lower)
        if window_control is not None:
            return PlannerDecision(
                request_type="direct_action",
                tool_requests=[ToolRequest("window_control", window_control)],
                active_request_state={
                    "family": "window_control",
                    "subject": "window_control",
                    "request_type": "direct_action",
                    "parameters": dict(window_control),
                },
            )

        routine_save = self._routine_save_request(
            message,
            lower,
            active_request_state=active_request_state or {},
        )
        if routine_save is not None:
            return PlannerDecision(
                request_type="routine_save",
                tool_requests=[ToolRequest("routine_save", {**routine_save, "session_id": session_id})],
                active_request_state={
                    "family": "routine",
                    "subject": str(routine_save.get("routine_name", "routine")),
                    "request_type": "routine_save",
                    "parameters": dict(routine_save),
                },
            )

        trusted_hook_register = self._trusted_hook_register_request(message, lower)
        if trusted_hook_register is not None:
            return PlannerDecision(
                request_type="trusted_hook_register",
                tool_requests=[ToolRequest("trusted_hook_register", trusted_hook_register)],
                active_request_state={
                    "family": "trusted_hook",
                    "subject": str(trusted_hook_register.get("hook_name", "trusted hook")),
                    "request_type": "trusted_hook_register",
                    "parameters": dict(trusted_hook_register),
                },
            )

        trusted_hook_execute = self._trusted_hook_execute_request(message, lower)
        if trusted_hook_execute is not None:
            return PlannerDecision(
                request_type="trusted_hook_execution",
                tool_requests=[ToolRequest("trusted_hook_execute", {**trusted_hook_execute, "session_id": session_id})],
                active_request_state={
                    "family": "trusted_hook",
                    "subject": str(trusted_hook_execute.get("hook_name", "trusted hook")),
                    "request_type": "trusted_hook_execution",
                    "parameters": dict(trusted_hook_execute),
                },
            )

        maintenance_action = self._maintenance_action_request(message, lower)
        if maintenance_action is not None:
            return PlannerDecision(
                request_type="maintenance_execution",
                tool_requests=[ToolRequest("maintenance_action", {**maintenance_action, "session_id": session_id})],
                active_request_state={
                    "family": "maintenance",
                    "subject": str(maintenance_action.get("maintenance_kind", "maintenance")),
                    "request_type": "maintenance_execution",
                    "parameters": dict(maintenance_action),
                },
            )

        file_operation = self._file_operation_request(message, lower)
        if file_operation is not None:
            return PlannerDecision(
                request_type="file_operation",
                tool_requests=[ToolRequest("file_operation", {**file_operation, "session_id": session_id})],
                active_request_state={
                    "family": "file_operation",
                    "subject": str(file_operation.get("operation", "file operation")),
                    "request_type": "file_operation",
                    "parameters": dict(file_operation),
                },
            )

        routine_execute = self._routine_execute_request(message, lower)
        if routine_execute is not None:
            return PlannerDecision(
                request_type="routine_execution",
                tool_requests=[ToolRequest("routine_execute", {**routine_execute, "session_id": session_id})],
                active_request_state={
                    "family": "routine",
                    "subject": str(routine_execute.get("routine_name", "routine")),
                    "request_type": "routine_execution",
                    "parameters": dict(routine_execute),
                },
            )

        repair_action = self._repair_action_request(message, lower)
        if repair_action is not None:
            return PlannerDecision(
                request_type="repair_execution",
                tool_requests=[ToolRequest("repair_action", {**repair_action, "session_id": session_id})],
                active_request_state={
                    "family": "repair",
                    "subject": str(repair_action.get("repair_kind", "repair")),
                    "request_type": "repair_execution",
                    "parameters": dict(repair_action),
                },
            )

        activity_summary = self._activity_summary_request(message, lower)
        if activity_summary is not None:
            return PlannerDecision(
                request_type="activity_summary",
                tool_requests=[ToolRequest("activity_summary", {**activity_summary, "session_id": session_id})],
                active_request_state={
                    "family": "activity",
                    "subject": "recent_activity",
                    "request_type": "activity_summary",
                    "parameters": dict(activity_summary),
                },
            )

        browser_request = self._browser_context_request(message, lower, active_context=active_context)
        if browser_request is not None:
            return PlannerDecision(
                request_type="browser_context",
                tool_requests=[ToolRequest("browser_context", {**browser_request, "session_id": session_id})],
                active_request_state={
                    "family": "browser",
                    "subject": str(browser_request.get("operation", "browser_context")),
                    "request_type": "browser_context",
                    "parameters": dict(browser_request),
                },
            )

        desktop_search = self._desktop_search_request(message, lower, surface_mode=surface_mode)
        if desktop_search is not None:
            return PlannerDecision(
                request_type="search_and_act" if str(desktop_search.get("action", "search")) == "open" else "search",
                tool_requests=[ToolRequest("desktop_search", {**desktop_search, "session_id": session_id})],
                active_request_state={
                    "family": "search",
                    "subject": str(desktop_search.get("query", "search")),
                    "request_type": "search_and_act" if str(desktop_search.get("action", "search")) == "open" else "search",
                    "parameters": dict(desktop_search),
                },
            )

        workflow_request = self._workflow_execution_request(message, lower)
        if workflow_request is not None:
            return PlannerDecision(
                request_type="workflow_execution",
                tool_requests=[ToolRequest("workflow_execute", {**workflow_request, "query": message, "session_id": session_id})],
                active_request_state={
                    "family": "workflow",
                    "subject": str(workflow_request.get("workflow_kind", "workflow")),
                    "request_type": "workflow_execution",
                    "parameters": dict(workflow_request),
                },
            )

        context_action = self._context_action_request(message, lower, active_context=active_context)
        if context_action is not None:
            return PlannerDecision(
                request_type="context_action",
                tool_requests=[ToolRequest("context_action", {**context_action, "session_id": session_id})],
                active_request_state={
                    "family": "context",
                    "subject": str(context_action.get("operation", "context")),
                    "request_type": "context_action",
                    "parameters": dict(context_action),
                },
            )

        app_control = self._app_control_request(message, lower)
        if app_control is not None:
            return PlannerDecision(
                request_type="direct_action",
                tool_requests=[ToolRequest("app_control", app_control)],
                active_request_state={
                    "family": "app_control",
                    "subject": "app_control",
                    "request_type": "direct_action",
                    "parameters": dict(app_control),
                },
            )

        if self._looks_like_open_location_settings(lower):
            return PlannerDecision(
                request_type="direct_action",
                tool_requests=[ToolRequest("external_open_url", {"url": "ms-settings:privacy-location"})],
            )
        if self._looks_like_workspace_clear(lower):
            return PlannerDecision(
                request_type="direct_action",
                tool_requests=[ToolRequest("workspace_clear", {"session_id": session_id})],
            )
        if self._looks_like_workspace_save(lower):
            return PlannerDecision(
                request_type="direct_action",
                tool_requests=[ToolRequest("workspace_save", {"session_id": session_id})],
            )
        if self._looks_like_workspace_archive(lower):
            return PlannerDecision(
                request_type="direct_action",
                tool_requests=[ToolRequest("workspace_archive", {"query": message, "session_id": session_id})],
            )
        if self._looks_like_workspace_rename(lower):
            new_name = self._extract_after_phrase(message, " to ")
            if new_name:
                return PlannerDecision(
                    request_type="direct_action",
                    tool_requests=[ToolRequest("workspace_rename", {"new_name": new_name, "session_id": session_id})],
                )
        if self._looks_like_workspace_tag(lower):
            tags = self._extract_tags(message)
            if tags:
                return PlannerDecision(
                    request_type="direct_action",
                    tool_requests=[ToolRequest("workspace_tag", {"tags": tags, "session_id": session_id})],
                )
        if self._looks_like_workspace_list(lower):
            return PlannerDecision(
                request_type="direct_deterministic_fact",
                tool_requests=[
                    ToolRequest(
                        "workspace_list",
                        {
                            "query": self._extract_workspace_list_query(message),
                            "archived_only": "archived" in lower,
                            "include_archived": "archived" in lower,
                            "session_id": session_id,
                        },
                    )
                ]
            )
        if self._looks_like_where_left_off(lower):
            return PlannerDecision(
                request_type="follow_up_grounded",
                tool_requests=[ToolRequest("workspace_where_left_off", {"session_id": session_id})],
            )
        if self._looks_like_next_steps(lower):
            return PlannerDecision(
                request_type="follow_up_grounded",
                tool_requests=[ToolRequest("workspace_next_steps", {"session_id": session_id})],
            )
        if self._looks_like_workspace_restore(lower):
            return PlannerDecision(
                request_type="workspace_restore",
                tool_requests=[ToolRequest("workspace_restore", {"query": message, "session_id": session_id})],
                requires_reasoner=True,
            )
        if self._looks_like_workspace_assemble(lower):
            return PlannerDecision(
                request_type="workspace_assembly",
                tool_requests=[ToolRequest("workspace_assemble", {"query": message, "session_id": session_id})],
                requires_reasoner=True,
            )
        if self._looks_like_save_home_location(lower):
            return PlannerDecision(
                request_type="direct_action",
                tool_requests=[ToolRequest("save_location", {"target": "home", "source_mode": "current"})],
            )
        if self._looks_like_saved_locations_list(lower):
            return PlannerDecision(
                request_type="direct_deterministic_fact",
                tool_requests=[ToolRequest("saved_locations", {"mode": "all"})],
            )
        location_source_message = self._location_source_follow_up_message(
            lower,
            active_request_state=active_request_state or {},
            recent_tool_results=recent_tool_results or [],
        )
        if location_source_message:
            return PlannerDecision(
                request_type="follow_up_grounded",
                assistant_message=location_source_message,
            )
        open_item_decision = self._plan_active_item_follow_up(
            message,
            surface_mode=surface_mode,
            workspace_context=workspace_context,
            active_posture=active_posture,
        )
        if open_item_decision is not None:
            return open_item_decision

        classification = self.classify(
            message,
            surface_mode=surface_mode,
            active_module=active_module,
            workspace_context=workspace_context,
            active_posture=active_posture,
            active_request_state=active_request_state or {},
            recent_tool_results=recent_tool_results or [],
            learned_preferences=learned_preferences or {},
        )
        if classification.family == "weather":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[
                    ToolRequest(
                        "weather_current",
                        {
                            "location_mode": classification.location_mode,
                            "named_location": classification.named_location,
                            "named_location_type": classification.named_location_type,
                            "allow_home_fallback": classification.allow_home_fallback,
                            "forecast_target": classification.forecast_target,
                            "open_target": classification.open_target,
                        },
                    )
                ],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "location":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[
                    ToolRequest(
                        "location_status",
                        {
                            "mode": classification.location_mode,
                            "named_location": classification.named_location,
                            "named_location_type": classification.named_location_type,
                            "allow_home_fallback": classification.allow_home_fallback,
                        },
                    )
                ],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "power":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[
                    ToolRequest(
                        "power_status",
                        {"focus": classification.focus, "present_in": classification.present_in},
                    )
                ],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "power_projection":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[
                    ToolRequest(
                        "power_projection",
                        {
                            "metric": classification.metric,
                            "target_percent": classification.target_percent,
                            "assume_unplugged": classification.assume_unplugged,
                            "present_in": classification.present_in,
                        },
                    )
                ],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "power_diagnosis":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[ToolRequest("power_diagnosis", {"present_in": classification.present_in})],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "resource":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[
                    ToolRequest(
                        "resource_status",
                        {
                            "focus": classification.focus,
                            "query_kind": classification.query_kind,
                            "metric": classification.metric,
                            "present_in": classification.present_in,
                        },
                    )
                ],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "resource_diagnosis":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[ToolRequest("resource_diagnosis", {"present_in": classification.present_in})],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "network":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[
                    ToolRequest(
                        "network_status",
                        {"focus": classification.focus, "present_in": classification.present_in},
                    )
                ],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "network_diagnosis":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[
                    ToolRequest(
                        "network_diagnosis",
                        {
                            "focus": classification.focus,
                            "diagnostic_burst": classification.metric == "diagnostic_burst",
                            "present_in": classification.present_in,
                        },
                    )
                ],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "machine":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[
                    ToolRequest(
                        "machine_status",
                        {"focus": classification.focus, "present_in": classification.present_in},
                    )
                ],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "active_apps":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[ToolRequest("active_apps")],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "recent_files":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[ToolRequest("recent_files")],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "storage":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[ToolRequest("storage_status")],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "storage_diagnosis":
            return PlannerDecision(
                request_type=classification.request_type,
                tool_requests=[ToolRequest("storage_diagnosis", {"present_in": classification.present_in})],
                active_request_state=classification.to_active_request_state(),
            )
        if classification.family == "system_overview":
            return PlannerDecision(
                request_type=classification.request_type,
                requires_reasoner=classification.requires_reasoner,
                tool_requests=[
                    ToolRequest("machine_status", {"focus": "overview", "present_in": classification.present_in}),
                    ToolRequest("power_status", {"focus": "overview", "present_in": classification.present_in}),
                    ToolRequest("resource_status", {"focus": "overview", "present_in": classification.present_in}),
                    ToolRequest("storage_status"),
                    ToolRequest("network_status", {"focus": "overview", "present_in": classification.present_in}),
                ],
                active_request_state=classification.to_active_request_state(),
            )
        if surface_mode.strip().lower() == "ghost" and any(token in lower for token in {"open externally", "open in browser"}):
            return PlannerDecision(
                request_type="direct_action",
                assistant_message="Standing by for a specific URL or file path to open externally.",
            )
        return PlannerDecision(request_type=classification.request_type, active_request_state=classification.to_active_request_state())

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
            return RequestClassification(
                request_type="direct_deterministic_fact",
                family="network",
                focus="ip" if " ip" in f" {lower}" or "address" in lower else "overview",
                present_in=present_in,
            )
        if self._looks_like_machine(lower):
            return RequestClassification(
                request_type="direct_deterministic_fact",
                family="machine",
                focus="time" if "timezone" in lower or "time zone" in lower else "identity",
                present_in=present_in,
            )
        if any(token in lower for token in {"running apps", "open apps", "active windows", "what is open", "open windows"}):
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
        if request_type in {"direct_deterministic_fact", "deterministic_projection_request", "deterministic_diagnostic_request", "follow_up_grounded", "direct_action"}:
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
        return (
            any(
                phrase in lower
                for phrase in {
                    "restore the workspace",
                    "open my workspace",
                    "open my",
                    "open the",
                    "continue where we left off",
                    "pick up where we left off",
                    "bring back the workspace",
                    "bring back the",
                    "pull up the",
                    "continue the ",
                }
            )
            and any(token in lower for token in {"workspace", "setup", "environment", "project", "stuff", "thing"})
        ) or "where we left off" in lower

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
                "reset the workspace",
                "empty the workspace",
            }
        )

    def _looks_like_workspace_archive(self, lower: str) -> bool:
        return any(phrase in lower for phrase in {"archive this workspace", "archive the workspace"})

    def _looks_like_workspace_rename(self, lower: str) -> bool:
        return "rename this workspace to" in lower or "rename the workspace to" in lower

    def _looks_like_workspace_tag(self, lower: str) -> bool:
        return "tag this workspace" in lower or "tag the workspace" in lower

    def _looks_like_workspace_list(self, lower: str) -> bool:
        return any(
            phrase in lower
            for phrase in {
                "list my recent workspaces",
                "show my recent workspaces",
                "show my archived workspaces",
                "list workspaces",
                "recent workspaces",
                "archived workspaces",
            }
        )

    def _looks_like_where_left_off(self, lower: str) -> bool:
        return any(phrase in lower for phrase in {"what were we doing", "where did we leave off", "continue from there"})

    def _looks_like_next_steps(self, lower: str) -> bool:
        return any(phrase in lower for phrase in {"what's next", "what is next", "what still needs doing", "what's left"})

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
        ):
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
            token in lower
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
        return any(token in lower for token in {"wifi", "wi-fi", "network", "internet", "connected", " ip", "my ip", "address"})

    def _looks_like_network_diagnosis(self, lower: str) -> bool:
        return any(
            token in lower
            for token in {
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

    def _looks_like_machine(self, lower: str) -> bool:
        return any(token in lower for token in {"machine name", "os version", "what computer", "what machine", "timezone", "time zone"})

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
    ) -> dict[str, object] | None:
        if "save this as a routine" not in lower:
            return None
        match = re.search(r"(?:called|named)\s+(.+)$", message, flags=re.IGNORECASE)
        routine_name = "saved routine"
        if match:
            routine_name = " ".join(str(match.group(1) or "").split()).strip(" .,:;!?")
        family = str(active_request_state.get("family") or "").strip().lower()
        parameters = active_request_state.get("parameters") if isinstance(active_request_state.get("parameters"), dict) else {}
        if family == "repair":
            return {
                "routine_name": routine_name,
                "execution_kind": "repair",
                "parameters": {
                    "repair_kind": str(parameters.get("repair_kind") or active_request_state.get("subject") or "").strip() or "connectivity_checks",
                    "target": str(parameters.get("target") or "system").strip() or "system",
                },
                "description": f"Saved repair routine for {routine_name}.",
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
            }
        if family == "maintenance":
            return {
                "routine_name": routine_name,
                "execution_kind": "maintenance",
                "parameters": dict(parameters),
                "description": f"Saved maintenance routine for {routine_name}.",
            }
        if family == "file_operation":
            return {
                "routine_name": routine_name,
                "execution_kind": "file_operation",
                "parameters": dict(parameters),
                "description": f"Saved file operation routine for {routine_name}.",
            }
        return None

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

    def _file_operation_request(self, message: str, lower: str) -> dict[str, object] | None:
        del message
        if any(phrase in lower for phrase in {"rename these screenshots by date", "rename my screenshots by date"}):
            return {"operation": "rename_by_date", "target_mode": "screenshots_default", "dry_run": False, "source_paths": []}
        if "find duplicates in this folder" in lower:
            return {"operation": "find_duplicates", "target_mode": "explicit", "dry_run": True, "source_paths": []}
        return None

    def _workflow_execution_request(self, message: str, lower: str) -> dict[str, object] | None:
        del message
        if any(phrase in lower for phrase in {"set up my writing environment", "setup my writing environment", "open my writing setup", "writing setup"}):
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
        if any(phrase in lower for phrase in {"show me the source i was just reading", "find the page i was just reading", "find the page from earlier"}):
            return {"operation": "recent_page", "query": message}
        if any(phrase in lower for phrase in {"find the tab", "find the page", "bring up the page", "bring that page forward"}) or (" tab " in lower and lower.startswith(("find ", "show ", "bring "))) or ("page about" in lower and any(lower.startswith(prefix) for prefix in {"find ", "show ", "bring "})):
            return {"operation": "find", "query": message}
        return None

    def _desktop_search_request(self, message: str, lower: str, *, surface_mode: str) -> dict[str, object] | None:
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
        if any(phrase in lower for phrase in {"try fixing my wi fi", "try fixing my wi-fi", "try fixing my wifi", "try fixing my network", "fix my wi fi", "fix my wi-fi", "fix my wifi", "fix my network"}):
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

        if lower in {"continue where i left off", "continue that", "resume that", "resume where i left off"}:
            return {"operation": "restore_context"}

        if any(phrase in lower for phrase in {"what i copied", "the thing i copied", "clipboard"}) and lower.startswith(("open ", "show ")):
            source = preferred_source("clipboard")
            if source:
                return {"operation": "open", "source": source}

        if any(phrase in lower for phrase in {"what i selected", "the thing i selected", "selection"}) and lower.startswith(("open ", "show ")):
            source = preferred_source("selection")
            if source:
                return {"operation": "open", "source": source}

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
            target = re.sub(r"^(?:delete|remove)\s+", "", message, flags=re.IGNORECASE).strip(" .")
            normalized_target = normalize_phrase(target)
            if normalized_target in {"this", "that", "it", "these", "those", "that folder", "this folder", "that file", "this file"}:
                return "Delete scope is too broad without a clearer target."
            return "Destructive deletion isn't available through Stormhelm yet."
        return None

    def _app_control_request(self, message: str, lower: str) -> dict[str, object] | None:
        if any(token in lower for token in {" setup", " environment", "workspace", "context"}) and not any(
            lower.startswith(prefix) for prefix in {"force quit ", "quit ", "close ", "restart ", "relaunch "}
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
            (r"^(?:quit)\s+(.+)$", "quit"),
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

    def _window_control_request(self, message: str, lower: str) -> dict[str, object] | None:
        deictic_targets = {"this", "that", "this window", "that window", "current window", "focused window", "current app", "focused app"}

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
        if any(phrase in lower for phrase in {"open bluetooth settings", "open bluetooth setting"}):
            return {"action": "open_settings_page", "target": "bluetooth"}
        if any(phrase in lower for phrase in {"open wifi settings", "open wi fi settings", "open wi-fi settings"}):
            return {"action": "open_settings_page", "target": "wifi"}
        if "open network settings" in lower:
            return {"action": "open_settings_page", "target": "network"}
        if "open sound settings" in lower:
            return {"action": "open_settings_page", "target": "sound"}
        if "open display settings" in lower:
            return {"action": "open_settings_page", "target": "display"}
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
        if not normalized or normalized in {
            "deck",
            "ghost",
            "workspace",
            "weather",
            "location settings",
            "layout",
            "saved layout",
            "deck layout",
            "panel launcher",
            "launcher",
        }:
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
        for marker in ("tag this workspace", "tag the workspace"):
            if marker not in lower:
                continue
            raw = message[lower.index(marker) + len(marker) :].strip(" .")
            if not raw:
                return []
            if "," in raw:
                return [part.strip() for part in raw.split(",") if part.strip()]
            return [part.strip() for part in raw.split() if part.strip()]
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
