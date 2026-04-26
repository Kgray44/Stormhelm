from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import CommandEvalCase
from .models import ExpectedBehavior


_STYLE_ORDER = (
    "canonical",
    "casual",
    "polite",
    "shorthand",
    "typo",
    "slang",
    "indirect",
    "question",
    "terse",
    "command_mode",
    "deictic",
    "follow_up",
    "ambiguous",
    "near_miss",
    "cross_family",
    "negative",
    "noisy",
    "confirm",
    "correction",
    "unsupported_probe",
)

_STYLE_TAGS = {
    "canonical": ("canonical",),
    "casual": ("casual",),
    "polite": ("casual",),
    "shorthand": ("casual", "shorthand"),
    "typo": ("typo",),
    "slang": ("casual", "slang"),
    "indirect": ("indirect",),
    "question": ("casual",),
    "terse": ("casual", "shorthand"),
    "command_mode": ("canonical", "explicit"),
    "deictic": ("deictic",),
    "follow_up": ("follow_up",),
    "ambiguous": ("ambiguous",),
    "near_miss": ("near_miss",),
    "cross_family": ("cross_family",),
    "negative": ("negative",),
    "noisy": ("casual", "noisy"),
    "confirm": ("follow_up",),
    "correction": ("follow_up", "correction"),
    "unsupported_probe": ("unsupported",),
}

_ACTION_TOOLS = {
    "app_control",
    "deck_open_file",
    "deck_open_url",
    "external_open_file",
    "external_open_url",
    "file_operation",
    "shell_command",
    "system_control",
}


@dataclass(frozen=True, slots=True)
class _Blueprint:
    key: str
    route_family: str
    subsystem: str
    tools: tuple[str, ...]
    canonical: str
    target_slots: dict[str, Any] | None = None
    tags: tuple[str, ...] = ()
    result_state: str = "dry_run_or_completed"
    verification: str = "bounded_or_not_applicable"
    approval: str = "not_expected"
    clarification: str | None = None
    response_terms: tuple[str, ...] = ()
    variants: dict[str, str] | None = None
    input_context: dict[str, Any] | None = None
    active_request_state: dict[str, Any] | None = None
    workspace_context: dict[str, Any] | None = None


def build_command_usability_corpus(*, min_cases: int = 1000) -> list[CommandEvalCase]:
    """Build a large labeled command-surface corpus from the current route/tool inventory."""
    blueprints = _blueprints()
    cases: list[CommandEvalCase] = []
    for blueprint in blueprints:
        for style in _STYLE_ORDER:
            message = _message_for_style(blueprint, style)
            case_id = f"{blueprint.key}_{style}_00"
            expected_route_family = blueprint.route_family
            expected_subsystem = blueprint.subsystem
            expected_tools = blueprint.tools
            expected_target_slots = dict(blueprint.target_slots or {})
            expected_clarification = (
                blueprint.clarification
                if blueprint.clarification is not None and style not in {"deictic", "follow_up", "ambiguous"}
                else "expected"
                if style == "ambiguous"
                else "allowed"
                if style in {"deictic", "follow_up"}
                else "none"
            )
            if _is_ambiguous_deictic_no_owner(blueprint, style):
                expected_route_family = "context_clarification"
                expected_subsystem = "context"
                expected_tools = ()
                expected_target_slots = {}
                expected_clarification = "expected"
            elif style == "follow_up" and blueprint.route_family == "browser_destination":
                expected_target_slots = {"destination_name": "Stormhelm docs"}
            expected = ExpectedBehavior(
                route_family=expected_route_family,
                subsystem=expected_subsystem,
                tools=expected_tools,
                target_slots=expected_target_slots,
                clarification=expected_clarification,
                approval=_approval_expectation(blueprint, style),
                result_state=blueprint.result_state,
                verification=blueprint.verification,
                response_terms=blueprint.response_terms,
            )
            style_tags = _STYLE_TAGS.get(style, (style,))
            sequence_id = f"{blueprint.key}_{style}" if style in {"deictic", "follow_up", "confirm", "correction"} else ""
            cases.append(
                CommandEvalCase(
                    case_id=case_id,
                    message=message,
                    expected=expected,
                    input_context=_context_for_style(blueprint, style),
                    active_request_state=_request_state_for_style(blueprint, style),
                    workspace_context=dict(blueprint.workspace_context or {}),
                    sequence_id=sequence_id,
                    turn_index=1 if sequence_id else 0,
                    tags=tuple(dict.fromkeys((*blueprint.tags, *style_tags))),
                )
            )
    if len(cases) >= min_cases:
        return cases

    expanded: list[CommandEvalCase] = list(cases)
    index = 1
    while len(expanded) < min_cases:
        for case in cases:
            if len(expanded) >= min_cases:
                break
            expanded.append(
                CommandEvalCase(
                    case_id=f"{case.case_id[:-2]}{index:02d}",
                    message=_extra_variant(case.message, index),
                    expected=case.expected,
                    session_id=case.session_id,
                    surface_mode=case.surface_mode,
                    active_module=case.active_module,
                    workspace_context=case.workspace_context,
                    input_context=case.input_context,
                    active_request_state=case.active_request_state,
                    sequence_id=case.sequence_id,
                    turn_index=case.turn_index,
                    tags=case.tags,
                    notes=case.notes,
                )
            )
        index += 1
    return expanded


def _approval_expectation(blueprint: _Blueprint, style: str) -> str:
    if blueprint.approval != "not_expected":
        return blueprint.approval
    if blueprint.route_family == "discord_relay" and style in {"deictic", "follow_up", "ambiguous"}:
        return "allowed"
    if _is_ambiguous_deictic_no_owner(blueprint, style):
        return "not_expected"
    if blueprint.route_family in {"discord_relay", "software_control", "trust_approvals"}:
        return "expected_or_preview"
    if "deck" in blueprint.tags:
        return "not_expected"
    if "internal_surface" in blueprint.tags:
        return "not_expected"
    if "unresolved_destination" in blueprint.tags:
        return "not_expected"
    if any(tool in _ACTION_TOOLS for tool in blueprint.tools):
        return "expected_or_preview"
    if style in {"confirm", "unsupported_probe"} and blueprint.tools:
        return "allowed"
    return "not_expected"


def _is_ambiguous_deictic_no_owner(blueprint: _Blueprint, style: str) -> bool:
    if style != "deictic":
        return False
    if blueprint.active_request_state:
        return False
    return not bool(blueprint.input_context)


def _context_for_style(blueprint: _Blueprint, style: str) -> dict[str, Any]:
    context = dict(blueprint.input_context or {})
    if style == "deictic" and not context:
        context["selection"] = {
            "kind": "text",
            "value": f"Selected context for {blueprint.key}",
            "preview": f"Selected context for {blueprint.key}",
        }
    if style == "follow_up" and blueprint.route_family == "browser_destination":
        context.setdefault(
            "recent_entities",
            [
                {
                    "title": "Stormhelm docs",
                    "kind": "page",
                    "url": "https://docs.example.com/stormhelm",
                    "freshness": "current",
                }
            ],
        )
    if blueprint.route_family == "calculations" and style in {"deictic", "follow_up", "confirm", "correction"}:
        context.setdefault(
            "recent_context_resolutions",
            [
                {
                    "kind": "calculation",
                    "result": {"expression": "18 / 3", "display_result": "6"},
                    "trace": {"extracted_expression": "18 / 3"},
                }
            ],
        )
    return context


def _request_state_for_style(blueprint: _Blueprint, style: str) -> dict[str, Any]:
    if blueprint.active_request_state:
        return dict(blueprint.active_request_state)
    if style in {"follow_up", "confirm", "correction"}:
        return {
            "family": blueprint.route_family,
            "subject": blueprint.key.replace("_", " "),
            "parameters": {"source_case": blueprint.key, "request_stage": "preview"},
        }
    return {}


def _message_for_style(blueprint: _Blueprint, style: str) -> str:
    variants = blueprint.variants or {}
    if style in variants:
        return variants[style]
    base = blueprint.canonical.strip()
    lowered = _lower_command(base)
    if style == "canonical":
        return base
    if style == "casual":
        return f"hey can you {lowered}"
    if style == "polite":
        return f"please {lowered}"
    if style == "shorthand":
        return f"pls {lowered}"
    if style == "typo":
        return _typo_variant(base)
    if style == "slang":
        return f"yo {lowered} real quick"
    if style == "indirect":
        return f"I need the Stormhelm route for this: {lowered}"
    if style == "question":
        return f"could you {lowered}?"
    if style == "terse":
        return _terse_variant(base)
    if style == "command_mode":
        return base if base.startswith("/") else f"Stormhelm, {lowered}"
    if style == "deictic":
        return "use this for that"
    if style == "follow_up":
        return "do the same thing as before"
    if style == "ambiguous":
        return "can you handle this?"
    if style == "near_miss":
        return f"almost {lowered}, but not exactly"
    if style == "cross_family":
        return f"open or diagnose this if that is the right route: {lowered}"
    if style == "negative":
        return f"don't actually {lowered}; tell me the safe route"
    if style == "noisy":
        return f"uhhh {lowered} -- quick quick"
    if style == "confirm":
        return "yes, go ahead with that preview"
    if style == "correction":
        return "no, use the other one"
    if style == "unsupported_probe":
        return f"can you magically {lowered} without any local evidence?"
    return base


def _lower_command(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if value.startswith("/"):
        return value
    return value[:1].lower() + value[1:]


def _typo_variant(value: str) -> str:
    replacements = {
        "please": "pls",
        "you": "u",
        "open": "opne",
        "install": "instal",
        "current": "currnt",
        "weather": "wether",
        "battery": "batery",
        "network": "netwrk",
        "workspace": "wrkspace",
        "Discord": "Discrod",
        "diagnose": "diagnoze",
    }
    text = value
    for source, target in replacements.items():
        text = text.replace(source, target).replace(source.title(), target)
    return text


def _terse_variant(value: str) -> str:
    words = [word for word in value.replace("?", "").split() if word.lower() not in {"please", "can", "you", "the", "my"}]
    return " ".join(words[:6]) or value


def _extra_variant(message: str, index: int) -> str:
    prefix = ("quickly", "when you can", "from the UI", "same idea")[index % 4]
    return f"{prefix}: {message}"


def _blueprints() -> list[_Blueprint]:
    readme_path = str(Path.cwd() / "README.md")
    docs_context = {
        "workspace": {"workspaceId": "ws-docs", "name": "Docs Workspace", "topic": "Stormhelm docs"},
        "module": "chartroom",
    }
    selection_context = {
        "selection": {
            "kind": "text",
            "value": "Selected launch notes for the relay preview.",
            "preview": "Selected launch notes for the relay preview.",
        }
    }
    return [
        _Blueprint("calculations", "calculations", "calculations", (), "what is 18 / 3", tags=("math",), response_terms=("6",)),
        _Blueprint("software_control_install", "software_control", "software_control", (), "install Firefox", tags=("software", "approval")),
        _Blueprint("software_control_update", "software_control", "software_control", (), "update VLC", tags=("software", "approval")),
        _Blueprint(
            "screen_awareness",
            "screen_awareness",
            "screen_awareness",
            (),
            "what is on my screen right now",
            tags=("screen", "observation"),
            clarification="expected",
        ),
        _Blueprint(
            "discord_relay",
            "discord_relay",
            "discord_relay",
            (),
            "send this to Baby on Discord",
            tags=("relay", "deictic", "unresolved_destination"),
            input_context=selection_context,
        ),
        _Blueprint(
            "trust_approval",
            "trust_approvals",
            "trust",
            (),
            "why are you asking for approval",
            tags=("trust", "follow_up"),
            active_request_state={
                "family": "software_control",
                "subject": "firefox",
                "parameters": {"operation_type": "install", "target_name": "firefox", "request_stage": "awaiting_confirmation"},
                "trust": {"request_id": "trust-eval-1", "reason": "Installing software changes the machine."},
            },
        ),
        _Blueprint("software_recovery", "software_recovery", "software_recovery", ("repair_action",), "fix my wifi", tags=("repair",)),
        _Blueprint(
            "browser_destination",
            "browser_destination",
            "browser",
            ("external_open_url",),
            "open youtube in a browser",
            target_slots={"destination_name": "youtube"},
            tags=("browser", "approval"),
        ),
        _Blueprint("browser_deck", "browser_destination", "browser", ("deck_open_url",), "open https://example.com in the deck", tags=("browser", "deck")),
        _Blueprint("file_external", "file", "files", ("external_open_file",), f"open {readme_path} externally", tags=("files", "approval")),
        _Blueprint("file_deck", "file", "files", ("deck_open_file",), f"open {readme_path} in the deck", tags=("files", "deck")),
        _Blueprint("desktop_search", "desktop_search", "workflow", ("desktop_search",), "find README.md on this computer", tags=("search",)),
        _Blueprint("workflow_execute", "workflow", "workflow", ("workflow_execute",), "set up my writing environment", tags=("workflow", "approval")),
        _Blueprint("routine_execute", "routine", "routine", ("routine_execute",), "run my cleanup routine", tags=("routine",)),
        _Blueprint(
            "routine_save",
            "routine",
            "routine",
            ("routine_save",),
            "save this as a routine called cleanup",
            tags=("routine", "follow_up"),
            active_request_state={"family": "maintenance", "subject": "downloads", "parameters": {"action": "cleanup_downloads"}},
        ),
        _Blueprint("trusted_hook_register", "routine", "routine", ("trusted_hook_register",), "register trusted hook build-check for C:\\Stormhelm\\scripts\\check.ps1", tags=("hook", "approval")),
        _Blueprint("trusted_hook_execute", "routine", "routine", ("trusted_hook_execute",), "run trusted hook build-check", tags=("hook", "approval")),
        _Blueprint("maintenance", "maintenance", "maintenance", ("maintenance_action",), "clean up my downloads", tags=("maintenance", "approval")),
        _Blueprint("file_operation", "file_operation", "files", ("file_operation",), "rename my screenshots by date", tags=("files", "approval")),
        _Blueprint("context_action", "context_action", "context", ("context_action",), "show the selection", tags=("context",), input_context=selection_context),
        _Blueprint("browser_context", "watch_runtime", "context", ("browser_context",), "what browser page am I on", tags=("browser", "watch")),
        _Blueprint("activity_summary", "watch_runtime", "operations", ("activity_summary",), "what did I miss", tags=("watch",)),
        _Blueprint("workspace_restore", "workspace_operations", "workspace", ("workspace_restore",), "restore my docs workspace", tags=("workspace",), workspace_context=docs_context),
        _Blueprint("workspace_assemble", "workspace_operations", "workspace", ("workspace_assemble",), "create a research workspace for motor torque", tags=("workspace",)),
        _Blueprint("workspace_save", "workspace_operations", "workspace", ("workspace_save",), "save this workspace", tags=("workspace",), workspace_context=docs_context),
        _Blueprint("workspace_clear", "workspace_operations", "workspace", ("workspace_clear",), "clear the current workspace", tags=("workspace", "approval"), workspace_context=docs_context),
        _Blueprint("workspace_archive", "workspace_operations", "workspace", ("workspace_archive",), "archive the current workspace", tags=("workspace", "approval"), workspace_context=docs_context),
        _Blueprint("workspace_rename", "workspace_operations", "workspace", ("workspace_rename",), "rename this workspace to Packaging Notes", tags=("workspace",), workspace_context=docs_context),
        _Blueprint("workspace_tag", "workspace_operations", "workspace", ("workspace_tag",), "tag this workspace with packaging", tags=("workspace",), workspace_context=docs_context),
        _Blueprint("workspace_list", "workspace_operations", "workspace", ("workspace_list",), "show my workspaces", tags=("workspace",)),
        _Blueprint(
            "workspace_where_left_off",
            "task_continuity",
            "workspace",
            ("workspace_where_left_off",),
            "continue where I left off",
            tags=("workspace", "follow_up"),
            workspace_context=docs_context,
        ),
        _Blueprint("workspace_next_steps", "task_continuity", "workspace", ("workspace_next_steps",), "what should I do next in this workspace", tags=("workspace", "follow_up"), workspace_context=docs_context),
        _Blueprint("clock", "time", "system", ("clock",), "what time is it", tags=("status",)),
        _Blueprint("system_info", "machine", "system", ("system_info",), "/system", tags=("status",)),
        _Blueprint("file_reader", "file", "files", ("file_reader",), f"/read {readme_path}", tags=("files",)),
        _Blueprint("notes_write", "notes", "workspace", ("notes_write",), "/note Eval note: remember this test note", tags=("notes",)),
        _Blueprint("shell_command", "terminal", "terminal", ("shell_command",), "/shell dir", tags=("terminal", "approval", "unsupported")),
        _Blueprint("machine_status", "machine", "system", ("machine_status",), "what machine am I on", tags=("status",)),
        _Blueprint("power_status", "power", "system", ("power_status",), "what is my battery at", tags=("power",)),
        _Blueprint("power_projection", "power", "system", ("power_projection",), "how long until my battery is full", tags=("power",)),
        _Blueprint("power_diagnosis", "power", "system", ("power_diagnosis",), "why is my battery draining so fast", tags=("power", "diagnostic")),
        _Blueprint("resource_status", "resources", "system", ("resource_status",), "what is my CPU and memory usage", tags=("resources",)),
        _Blueprint("resource_diagnosis", "resources", "system", ("resource_diagnosis",), "why is my computer sluggish", tags=("resources", "diagnostic")),
        _Blueprint("storage_status", "storage", "system", ("storage_status",), "how much disk space do I have", tags=("storage",)),
        _Blueprint("storage_diagnosis", "storage", "system", ("storage_diagnosis",), "why is my disk almost full", tags=("storage", "diagnostic")),
        _Blueprint("network_status", "network", "system", ("network_status",), "am I online", tags=("network",)),
        _Blueprint("network_throughput", "network", "system", ("network_throughput",), "what is my current internet speed", tags=("network",)),
        _Blueprint("network_diagnosis", "network", "system", ("network_diagnosis",), "why is my wifi lagging", tags=("network", "diagnostic")),
        _Blueprint("location_status", "location", "location", ("location_status",), "where am I", tags=("location",)),
        _Blueprint("saved_locations", "location", "location", ("saved_locations",), "show my saved locations", tags=("location",)),
        _Blueprint("save_location", "location", "location", ("save_location",), "remember home as Brooklyn New York", tags=("location",)),
        _Blueprint("weather_current", "weather", "weather", ("weather_current",), "what is the weather here", tags=("weather",)),
        _Blueprint("active_apps", "app_control", "system", ("active_apps",), "what apps are open", tags=("apps",)),
        _Blueprint("app_control", "app_control", "system", ("app_control",), "open Chrome", tags=("apps", "approval")),
        _Blueprint("window_status", "window_control", "system", ("window_status",), "what windows are open", tags=("windows",)),
        _Blueprint("window_control", "window_control", "system", ("window_control",), "minimize the current window", tags=("windows", "approval")),
        _Blueprint("system_control", "system_control", "system", ("system_control",), "open bluetooth settings", tags=("settings", "internal_surface")),
        _Blueprint("control_capabilities", "system_control", "system", ("control_capabilities",), "what system controls can you use", tags=("settings",)),
        _Blueprint("recent_files", "machine", "system", ("recent_files",), "show recent files", tags=("files", "status")),
        _Blueprint("echo", "development", "development", ("echo",), "/echo harness ping", tags=("development",), response_terms=("harness ping",)),
        _Blueprint("generic_provider", "generic_provider", "provider", (), "write a two sentence pep talk for finals", tags=("generic",)),
        _Blueprint("unsupported", "unsupported", "none", (), "book me a real flight and pay for it now", tags=("unsupported",), result_state="unsupported_or_clarification"),
    ]
