from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .corpus import build_command_usability_corpus


@dataclass(frozen=True, slots=True)
class FeatureAuditEntry:
    name: str
    kind: str
    classification: str
    evidence_path: str
    evidence_summary: str
    route_entrypoint: str
    reachable_through_chat_send: bool
    dry_run_validates: bool
    include_in_scoring: bool
    scoring_note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ROUTE_AUDIT: dict[str, FeatureAuditEntry] = {
    "calculations": FeatureAuditEntry("calculations", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/assistant.py:443", "Assistant calls the calculations subsystem directly for planner calculation decisions.", "POST /chat/send -> AssistantOrchestrator -> DeterministicPlanner -> CalculationsSubsystem", True, False, True, "Direct subsystem path; score routing and response correctness, not tool dry-run."),
    "software_control": FeatureAuditEntry("software_control", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/assistant.py:564", "Assistant dispatches planner software-control decisions to SoftwareControlSubsystem.", "POST /chat/send -> AssistantOrchestrator -> SoftwareControlSubsystem", True, False, True, "Score route and truthful prepared-action state."),
    "software_recovery": FeatureAuditEntry("software_recovery", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:2020", "Repair phrases create repair_action tool requests.", "POST /chat/send -> DeterministicPlanner -> repair_action", True, True, True, "Score native repair routing and dry-run tool chain."),
    "screen_awareness": FeatureAuditEntry("screen_awareness", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/assistant.py:634", "Assistant dispatches screen-awareness requests to ScreenAwarenessSubsystem.", "POST /chat/send -> AssistantOrchestrator -> ScreenAwarenessSubsystem", True, False, True, "Score observe/guidance routing; no destructive screen action should execute."),
    "discord_relay": FeatureAuditEntry("discord_relay", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/assistant.py:683", "Assistant dispatches relay decisions to DiscordRelaySubsystem with preview/trust handling.", "POST /chat/send -> AssistantOrchestrator -> DiscordRelaySubsystem", True, False, True, "Score routing, alias extraction, preview/approval truthfulness."),
    "trust_approvals": FeatureAuditEntry("trust_approvals", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:4291", "Planner answers trust approval follow-up from active_request_state.", "POST /chat/send -> DeterministicPlanner active request state", True, False, True, "Score only with active trust/request setup."),
    "workspace_operations": FeatureAuditEntry("workspace_operations", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1760", "Workspace restore/save/archive/list/tag/rename/assemble requests produce workspace tool calls.", "POST /chat/send -> DeterministicPlanner -> workspace_* tools", True, True, True, "Score route/tool chain; workspace mutation is dry-run suppressed."),
    "task_continuity": FeatureAuditEntry("task_continuity", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1800", "Continuation and next-step requests route through workspace/context tools.", "POST /chat/send -> DeterministicPlanner -> workspace_where_left_off/workspace_next_steps/context_action", True, True, True, "Score route/tool chain with isolated session setup."),
    "watch_runtime": FeatureAuditEntry("watch_runtime", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1952", "Browser-context and activity-summary routes produce watch/runtime tool calls.", "POST /chat/send -> DeterministicPlanner -> browser_context/activity_summary", True, True, True, "Score supported phrases only."),
    "browser_destination": FeatureAuditEntry("browser_destination", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:4890", "Browser destination resolver maps known sites/direct domains/searches to open URL tools.", "POST /chat/send -> DeterministicPlanner -> deck/external open URL", True, True, True, "Score route/tool chain; dry-run suppresses external browser handoff."),
    "desktop_search": FeatureAuditEntry("desktop_search", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:5008", "Desktop search phrases produce desktop_search tool calls.", "POST /chat/send -> DeterministicPlanner -> desktop_search", True, True, True, "Score search routing and target extraction."),
    "workflow": FeatureAuditEntry("workflow", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:4808", "Only specific setup phrases map to workflow_execute.", "POST /chat/send -> DeterministicPlanner -> workflow_execute", True, True, True, "Score supported setup phrases; unsupported workflow names are corpus expectation bugs."),
    "routine": FeatureAuditEntry("routine", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1853", "Routine save/execute and trusted-hook execute route through planner tool proposals.", "POST /chat/send -> DeterministicPlanner -> routine_* / trusted_hook_execute", True, True, True, "Score routeable routine and hook-execute cases; hook-register is scaffold-only."),
    "maintenance": FeatureAuditEntry("maintenance", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:4265", "Maintenance phrases create maintenance_action requests.", "POST /chat/send -> DeterministicPlanner -> maintenance_action", True, True, True, "Score supported maintenance phrases."),
    "file_operation": FeatureAuditEntry("file_operation", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:4783", "A narrow set of file-operation phrases maps to file_operation.", "POST /chat/send -> DeterministicPlanner -> file_operation", True, True, True, "Score supported phrases; near phrases are corpus expectation bugs."),
    "context_action": FeatureAuditEntry("context_action", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:5143", "Only explicit context mutation/extract/open phrases map to context_action.", "POST /chat/send -> DeterministicPlanner -> context_action", True, True, True, "Score supported context-action phrases; generic summarization is provider work."),
    "context_clarification": FeatureAuditEntry("context_clarification", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner_v2.py:1272", "Planner v2 owns ambiguous deictic/follow-up requests when no specific native family can be inferred.", "POST /chat/send -> PlannerV2 -> native context clarification", True, False, True, "Score native clarification; no provider fallback or external action should occur."),
    "file": FeatureAuditEntry("file", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/router.py:145", "Router and planner have native file read/open tools.", "POST /chat/send -> IntentRouter/DeterministicPlanner -> file_reader/deck_open_file/external_open_file", True, True, True, "Score path/read/open routing; file path misclassification is a real routing concern unless phrase is unsupported."),
    "app_control": FeatureAuditEntry("app_control", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1650", "Control-command phrases map to app_control/active_apps.", "POST /chat/send -> DeterministicPlanner -> app_control/active_apps", True, True, True, "Score app/window distinction and dry-run tool chain."),
    "window_control": FeatureAuditEntry("window_control", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1680", "Window-control phrases map to window_control; status is also available as a tool.", "POST /chat/send -> DeterministicPlanner -> window_control/window_status", True, True, True, "Score window-control routes where phrase is supported."),
    "system_control": FeatureAuditEntry("system_control", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1705", "Settings/system-control phrases map to system_control or settings URL tools.", "POST /chat/send -> DeterministicPlanner -> system_control/external_open_url", True, True, True, "Score supported settings/control phrases."),
    "location": FeatureAuditEntry("location", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1510", "Location status/saved/save requests map to location tools.", "POST /chat/send -> DeterministicPlanner -> location_* tools", True, True, True, "Score current location and saved-location routes."),
    "weather": FeatureAuditEntry("weather", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1540", "Weather requests map to weather_current.", "POST /chat/send -> DeterministicPlanner -> weather_current", True, True, True, "Score routing; live weather fetch remains dry-run suppressed."),
    "power": FeatureAuditEntry("power", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1390", "Power status/projection/diagnosis route through planner.", "POST /chat/send -> DeterministicPlanner -> power_* tools", True, True, True, "Score expected family with tool-level aliases normalized."),
    "network": FeatureAuditEntry("network", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1460", "Network status/throughput/diagnosis route through planner.", "POST /chat/send -> DeterministicPlanner -> network_* tools", True, True, True, "Score network status and diagnosis."),
    "resources": FeatureAuditEntry("resources", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1420", "Resource status/diagnosis route through planner.", "POST /chat/send -> DeterministicPlanner -> resource_* tools", True, True, True, "Score resource route family."),
    "storage": FeatureAuditEntry("storage", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner.py:1440", "Storage status/diagnosis route through planner.", "POST /chat/send -> DeterministicPlanner -> storage_* tools", True, True, True, "Score storage route family."),
    "machine": FeatureAuditEntry("machine", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/router.py:36", "Machine/system status available through legacy router and planner tools.", "POST /chat/send -> IntentRouter/DeterministicPlanner -> machine/system tools", True, True, True, "Score route/tool; some direct commands are legacy telemetry gaps."),
    "time": FeatureAuditEntry("time", "route_family", "implemented_direct_only", "src/stormhelm/core/orchestrator/router.py:28", "Time routes first through IntentRouter before planner.", "POST /chat/send -> IntentRouter -> clock", True, True, True, "Score direct behavior, but missing planner route_state is a legacy/direct telemetry gap."),
    "notes": FeatureAuditEntry("notes", "route_family", "implemented_direct_only", "src/stormhelm/core/orchestrator/router.py:56", "Notes are slash-command routed through IntentRouter.", "POST /chat/send -> IntentRouter -> notes_write", True, True, True, "Score explicit /note only; fuzzy note requests need separate intent design."),
    "terminal": FeatureAuditEntry("terminal", "route_family", "implemented_direct_only", "src/stormhelm/core/orchestrator/router.py:66", "Shell command stub is slash-command routed and safety gated.", "POST /chat/send -> IntentRouter -> shell_command", True, True, True, "Score explicit /shell stub only; no live shell execution."),
    "development": FeatureAuditEntry("development", "route_family", "implemented_direct_only", "src/stormhelm/core/orchestrator/router.py:49", "Echo is a direct slash command.", "POST /chat/send -> IntentRouter -> echo", True, True, True, "Score explicit /echo only; route_state absence is legacy/direct telemetry."),
    "generic_provider": FeatureAuditEntry("generic_provider", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/assistant.py:926", "Provider fallback is emitted when no native route owns the request or provider is disabled.", "POST /chat/send -> DeterministicPlanner/provider fallback", True, False, True, "Score only cases explicitly expected to be generic provider."),
    "unsupported": FeatureAuditEntry("unsupported", "route_family", "implemented_routeable", "src/stormhelm/core/orchestrator/planner_models.py:49", "Planner has unsupported response mode/native unsupported posture.", "POST /chat/send -> DeterministicPlanner unsupported/generic fallback", True, False, True, "Score refusal/clarification behavior for unsupported requests."),
}

_SUBSYSTEM_AUDIT: dict[str, FeatureAuditEntry] = {
    "calculations": _ROUTE_AUDIT["calculations"],
    "software_control": _ROUTE_AUDIT["software_control"],
    "software_recovery": _ROUTE_AUDIT["software_recovery"],
    "screen_awareness": _ROUTE_AUDIT["screen_awareness"],
    "discord_relay": _ROUTE_AUDIT["discord_relay"],
    "trust": _ROUTE_AUDIT["trust_approvals"],
    "workspace": _ROUTE_AUDIT["workspace_operations"],
    "operations": _ROUTE_AUDIT["watch_runtime"],
    "browser": _ROUTE_AUDIT["browser_destination"],
    "workflow": _ROUTE_AUDIT["workflow"],
    "routine": _ROUTE_AUDIT["routine"],
    "maintenance": _ROUTE_AUDIT["maintenance"],
    "files": _ROUTE_AUDIT["file"],
    "context": _ROUTE_AUDIT["context_action"],
    "system": _ROUTE_AUDIT["machine"],
    "location": _ROUTE_AUDIT["location"],
    "weather": _ROUTE_AUDIT["weather"],
    "provider": _ROUTE_AUDIT["generic_provider"],
    "none": _ROUTE_AUDIT["unsupported"],
    "development": _ROUTE_AUDIT["development"],
}

_TOOL_SCORING_OVERRIDES: dict[str, FeatureAuditEntry] = {
    "trusted_hook_register": FeatureAuditEntry("trusted_hook_register", "tool", "scaffold_only", "src/stormhelm/core/orchestrator/planner.py:4250", "Parser helper exists, and tool exists, but planner flow does not call the register helper.", "No active POST /chat/send planner entrypoint found", False, True, False, "Exclude from normal pass/fail until route entrypoint is wired."),
    "control_capabilities": FeatureAuditEntry("control_capabilities", "tool", "implemented_direct_only", "src/stormhelm/core/tools/builtins/system_state.py:1893", "Tool exists but no natural planner route was confirmed.", "Tool registry only; no confirmed planner route", False, True, False, "Exclude from route scoring unless a route entrypoint is added."),
}


def build_feature_audit(cases: list[Any] | None = None) -> dict[str, Any]:
    selected_cases = list(cases or build_command_usability_corpus(min_cases=1000))
    expected_families = sorted({case.expected.route_family for case in selected_cases})
    expected_subsystems = sorted({case.expected.subsystem for case in selected_cases})
    expected_tools = sorted({tool for case in selected_cases for tool in case.expected.tools})
    route_entries = {name: _entry_for_route(name).to_dict() for name in expected_families}
    subsystem_entries = {name: _entry_for_subsystem(name).to_dict() for name in expected_subsystems}
    tool_entries = {
        name: _TOOL_SCORING_OVERRIDES[name].to_dict()
        for name in expected_tools
        if name in _TOOL_SCORING_OVERRIDES
    }
    return {
        "source": "repo-derived audit of current command_eval corpus expectations",
        "classification_values": [
            "implemented_routeable",
            "implemented_direct_only",
            "scaffold_only",
            "docs_only",
            "deprecated_or_legacy",
        ],
        "route_families": route_entries,
        "subsystems": subsystem_entries,
        "tool_overrides": tool_entries,
        "summary": _summary([*route_entries.values(), *subsystem_entries.values(), *tool_entries.values()]),
    }


def should_score_case(case: Any, feature_audit: dict[str, Any] | None = None) -> tuple[bool, str]:
    audit = feature_audit or build_feature_audit([case])
    route_entry = dict(audit.get("route_families", {}).get(case.expected.route_family) or {})
    if route_entry.get("include_in_scoring") is False:
        return False, str(route_entry.get("scoring_note") or "Route family excluded by feature audit.")
    tool_overrides = audit.get("tool_overrides", {}) if isinstance(audit.get("tool_overrides"), dict) else {}
    for tool in case.expected.tools:
        tool_entry = dict(tool_overrides.get(tool) or {})
        if tool_entry.get("include_in_scoring") is False:
            return False, str(tool_entry.get("scoring_note") or f"Tool {tool} excluded by feature audit.")
    return True, str(route_entry.get("scoring_note") or "")


def _entry_for_route(route_family: str) -> FeatureAuditEntry:
    return _ROUTE_AUDIT.get(
        route_family,
        FeatureAuditEntry(
            route_family,
            "route_family",
            "docs_only",
            "",
            "No repo route evidence recorded in command_eval feature audit.",
            "",
            False,
            False,
            False,
            "Exclude until implementation evidence is added.",
        ),
    )


def _entry_for_subsystem(subsystem: str) -> FeatureAuditEntry:
    return _SUBSYSTEM_AUDIT.get(
        subsystem,
        FeatureAuditEntry(
            subsystem,
            "subsystem",
            "docs_only",
            "",
            "No repo subsystem evidence recorded in command_eval feature audit.",
            "",
            False,
            False,
            False,
            "Exclude until implementation evidence is added.",
        ),
    )


def _summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    scoring_count = 0
    for entry in entries:
        classification = str(entry.get("classification") or "unknown")
        counts[classification] = counts.get(classification, 0) + 1
        if entry.get("include_in_scoring"):
            scoring_count += 1
    return {
        "classification_counts": dict(sorted(counts.items())),
        "include_in_scoring_count": scoring_count,
        "excluded_from_scoring_count": max(0, len(entries) - scoring_count),
    }
