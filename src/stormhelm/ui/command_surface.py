from __future__ import annotations

from typing import Any


_ROUTE_LABELS = {
    "discord_relay": "Discord Relay",
    "software_control": "Software Control",
    "software_recovery": "Software Recovery",
    "trust": "Trust",
    "task_continuity": "Task Continuity",
    "watch_runtime": "Runtime Watch",
    "memory": "Memory",
    "desktop_search": "Desktop Search",
    "browser_destination": "Browser",
    "browser_context": "Browser",
    "screen_awareness": "Visual Context",
    "generic_provider": "Provider",
}

_RESULT_STATE_LABELS = {
    "prepared": "Prepared",
    "preview_ready": "Preview Ready",
    "awaiting_approval": "Awaiting Approval",
    "ready_after_approval": "Ready After Approval",
    "attempted": "Attempted",
    "verified": "Verified",
    "unresolved": "Unresolved",
    "blocked": "Blocked",
    "recovery_in_progress": "Recovery In Progress",
    "stale": "Stale",
}

_REQUEST_STAGE_LABELS = {
    "preview": "Preview",
    "clarify_payload": "Clarify Payload",
    "awaiting_confirmation": "Awaiting Confirmation",
    "confirm_execution": "Confirm Execution",
    "recovery_ready": "Recovery Ready",
    "dispatch": "Dispatch",
    "prepare_plan": "Prepare Plan",
}

_PAYLOAD_LABELS = {
    "selected_text": "Selected Text",
    "clipboard": "Clipboard",
    "page_link": "Page Link",
    "file": "File",
    "note_artifact": "Note",
    "screenshot_candidate": "Screenshot",
    "software_target": "Software Target",
    "window": "Window",
}

_SOURCE_LABELS = {
    "selection": "Selection",
    "clipboard": "Clipboard",
    "active_preview": "Active Preview",
    "browser": "Browser",
    "workspace": "Workspace",
    "recent_session_entity": "Recent Session Entity",
}

_STATION_IDS = {
    "discord_relay": "relay-station",
    "software_control": "software-control-station",
    "software_recovery": "software-recovery-station",
    "screen_awareness": "screen-awareness-station",
    "trust": "trust-station",
    "task_continuity": "continuity-station",
    "watch_runtime": "runtime-station",
    "memory": "memory-station",
}

_STATION_TITLES = {
    "discord_relay": "Relay Station",
    "software_control": "Software Control",
    "software_recovery": "Software Recovery",
    "screen_awareness": "Screen Awareness",
    "trust": "Trust Station",
    "task_continuity": "Task Continuity",
    "watch_runtime": "Runtime Station",
    "memory": "Memory Support",
}

_WORKSPACE_ACTIONS = {
    "screen_awareness": ("visual-context", "focus-surface", "Open Visual Context"),
    "task_continuity": ("chartroom", "tasks", "Open Tasks"),
    "watch_runtime": ("watch", "overview", "Open Watch"),
    "memory": ("logbook", "memory", "Open Memory"),
}

_RESULT_TONES = {
    "prepared": "steady",
    "preview_ready": "attention",
    "awaiting_approval": "attention",
    "ready_after_approval": "attention",
    "attempted": "steady",
    "verified": "live",
    "unresolved": "warning",
    "blocked": "warning",
    "recovery_in_progress": "attention",
    "stale": "stale",
}

_STALE_TOKENS = {"stale", "expired", "invalid", "invalidated", "superseded", "replaced", "revoked"}

_ROUTE_INSPECTOR_SUMMARY = "Backend-owned route, provenance, and trace state."


def build_command_surface_model(
    *,
    active_request_state: dict[str, Any] | None,
    active_task: dict[str, Any] | None,
    recent_context_resolutions: list[dict[str, Any]] | None,
    latest_message: dict[str, Any] | None,
    status: dict[str, Any] | None,
    workspace_focus: dict[str, Any] | None,
) -> dict[str, Any]:
    request_state = dict(active_request_state or {})
    latest = dict(latest_message or {})
    metadata = latest.get("metadata") if isinstance(latest.get("metadata"), dict) else {}
    route_state = metadata.get("route_state") if isinstance(metadata.get("route_state"), dict) else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    deictic = route_state.get("deictic_binding") if isinstance(route_state.get("deictic_binding"), dict) else {}
    decomposition = route_state.get("decomposition") if isinstance(route_state.get("decomposition"), dict) else {}
    parameters = request_state.get("parameters") if isinstance(request_state.get("parameters"), dict) else {}
    trust = request_state.get("trust") if isinstance(request_state.get("trust"), dict) else {}
    status_payload = dict(status or {})
    recent_resolutions = [dict(item) for item in recent_context_resolutions or [] if isinstance(item, dict)]
    workspace = dict(workspace_focus or {})

    if not request_state and not route_state:
        return {
            "ghostPrimaryCard": {},
            "ghostActionStrip": [],
            "requestComposer": {
                "placeholder": "Give Stormhelm a grounded request or continue the current thread.",
                "headline": "",
                "summary": "",
                "chips": [],
                "quickActions": [],
                "clarificationChoices": [],
            },
            "routeInspector": {},
        }

    family = _text(request_state.get("family")) or _text(winner.get("route_family"))
    route_label = _route_label(family)
    request_stage = _text(parameters.get("request_stage")) or _text(winner.get("status"))
    result_state = _normalized_result_state(
        request_stage=request_stage,
        trust=trust,
        winner=winner,
        parameters=parameters,
    )
    status_label = _RESULT_STATE_LABELS.get(result_state, _titleize(result_state or "prepared"))

    title = (
        _text(latest.get("bearingTitle"))
        or _text(latest.get("bearing_title"))
        or _default_title(family=family, request_stage=request_stage, result_state=result_state)
    )
    body = (
        _text(latest.get("fullResponse"))
        or _text(latest.get("content"))
        or _text(trust.get("operator_message"))
        or _text(next(iter(recent_resolutions or [{}]), {}).get("summary"))
        or "Stormhelm is holding the current command posture truthfully."
    )
    subtitle_parts = [route_label, status_label]
    subject = _text(request_state.get("subject")) or _text(decomposition.get("subject"))
    if subject:
        subtitle_parts.insert(1, subject)
    subtitle = " • ".join(part for part in subtitle_parts if part)

    provenance = _provenance_entries(
        parameters=parameters,
        trust=trust,
        deictic=deictic,
        recent_resolutions=recent_resolutions,
        workspace=workspace,
    )
    trace = _trace_entries(
        family=family,
        request_state=request_state,
        winner=winner,
        parameters=parameters,
        deictic=deictic,
    )
    support_systems = _support_system_entries(
        status=status_payload,
        active_task=dict(active_task or {}),
        trust=trust,
    )
    actions = _action_entries(
        family=family,
        request_stage=request_stage,
        trust=trust,
        parameters=parameters,
        latest_message=latest,
    )
    clarification_choices = [dict(action) for action in actions if action.get("category") == "clarify"]
    quick_actions = [dict(action) for action in actions if action.get("sendText")]

    primary_card = {
        "title": title,
        "subtitle": subtitle,
        "body": body,
        "routeLabel": route_label,
        "resultState": result_state,
        "statusLabel": status_label,
        "provenance": provenance,
    }

    composer_chips = [
        {"label": "Route", "value": route_label},
        {"label": "Request Stage", "value": _request_stage_label(request_stage)},
    ]
    for entry in provenance[:3]:
        if entry["label"] in {"Binding", "Trust"}:
            composer_chips.append({"label": entry["label"], "value": entry["value"]})

    composer = {
        "placeholder": _composer_placeholder(result_state),
        "headline": title,
        "summary": _text(latest.get("microResponse")) or body,
        "chips": composer_chips,
        "quickActions": quick_actions[:4],
        "clarificationChoices": clarification_choices,
    }

    inspector = {
        "title": title,
        "subtitle": subtitle,
        "summary": _ROUTE_INSPECTOR_SUMMARY,
        "body": body,
        "resultState": result_state,
        "statusLabel": status_label,
        "trace": trace,
        "provenance": provenance,
        "supportSystems": support_systems,
        "actions": actions,
    }

    return {
        "ghostPrimaryCard": primary_card if title else {},
        "ghostActionStrip": actions,
        "requestComposer": composer,
        "routeInspector": inspector if title else {},
    }


def _provenance_entries(
    *,
    parameters: dict[str, Any],
    trust: dict[str, Any],
    deictic: dict[str, Any],
    recent_resolutions: list[dict[str, Any]],
    workspace: dict[str, Any],
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    selected_source = _text(deictic.get("selected_source"))
    if not selected_source and recent_resolutions:
        selected_source = _text(recent_resolutions[0].get("selected_source"))
    if selected_source:
        entries.append({"label": "Binding", "value": _SOURCE_LABELS.get(selected_source, _titleize(selected_source))})

    payload_hint = _text(parameters.get("payload_hint"))
    if not payload_hint:
        selected_target = deictic.get("selected_target") if isinstance(deictic.get("selected_target"), dict) else {}
        payload_hint = _text(selected_target.get("target_type"))
    if payload_hint:
        entries.append({"label": "Payload", "value": _PAYLOAD_LABELS.get(payload_hint, _titleize(payload_hint))})

    approval_state = _text(trust.get("approval_state"))
    if approval_state:
        entries.append({"label": "Trust", "value": _titleize(approval_state)})

    if workspace.get("name"):
        entries.append({"label": "Workspace", "value": _text(workspace.get("name"))})

    return entries


def _trace_entries(
    *,
    family: str,
    request_state: dict[str, Any],
    winner: dict[str, Any],
    parameters: dict[str, Any],
    deictic: dict[str, Any],
) -> list[dict[str, str]]:
    route = request_state.get("route") if isinstance(request_state.get("route"), dict) else {}
    entries = [
        {"label": "Route", "value": _route_label(family)},
        {"label": "Query Shape", "value": _titleize(_text(request_state.get("query_shape")) or _text(winner.get("query_shape")))},
        {"label": "Posture", "value": _titleize(_text(winner.get("posture")))},
        {"label": "Request Stage", "value": _request_stage_label(_text(parameters.get("request_stage")) or _text(winner.get("status")))},
    ]
    selected_route = _text(parameters.get("selected_source_route"))
    if selected_route:
        entries.append({"label": "Selected Route", "value": selected_route})
    route_mode = _text(route.get("route_mode"))
    if route_mode:
        entries.append({"label": "Route Mode", "value": route_mode})
    response_mode = _text(route.get("response_mode"))
    if response_mode:
        entries.append({"label": "Response Mode", "value": _titleize(response_mode)})
    selected_source = _text(deictic.get("selected_source"))
    if selected_source:
        entries.append({"label": "Binding Source", "value": _SOURCE_LABELS.get(selected_source, _titleize(selected_source))})
    return entries


def _support_system_entries(
    *,
    status: dict[str, Any],
    active_task: dict[str, Any],
    trust: dict[str, Any],
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if active_task.get("title"):
        entries.append({"label": "Task", "value": _text(active_task.get("title"))})

    approval_state = _text(trust.get("approval_state"))
    if approval_state:
        entries.append({"label": "Trust", "value": _titleize(approval_state)})

    memory_state = status.get("memory") if isinstance(status.get("memory"), dict) else {}
    families = memory_state.get("families") if isinstance(memory_state.get("families"), dict) else {}
    family_count = sum(int(value or 0) for value in families.values())
    if family_count:
        suffix = "record" if family_count == 1 else "records"
        entries.append({"label": "Memory", "value": f"{family_count} family {suffix}"})

    lifecycle = status.get("lifecycle") if isinstance(status.get("lifecycle"), dict) else {}
    bootstrap = lifecycle.get("bootstrap") if isinstance(lifecycle.get("bootstrap"), dict) else {}
    hold_reason = _text(bootstrap.get("lifecycle_hold_reason"))
    if hold_reason:
        entries.append({"label": "Lifecycle", "value": hold_reason})

    watch = status.get("watch_state") if isinstance(status.get("watch_state"), dict) else {}
    active_jobs = int(watch.get("active_jobs") or 0)
    queued_jobs = int(watch.get("queued_jobs") or 0)
    if active_jobs or queued_jobs:
        entries.append({"label": "Watch", "value": f"{active_jobs} active / {queued_jobs} queued"})

    return entries


def _action_entries(
    *,
    family: str,
    request_stage: str,
    trust: dict[str, Any],
    parameters: dict[str, Any],
    latest_message: dict[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    ambiguity_choices = parameters.get("ambiguity_choices") if isinstance(parameters.get("ambiguity_choices"), list) else []
    if request_stage == "clarify_payload" and ambiguity_choices:
        for choice in ambiguity_choices[:3]:
            normalized = _text(choice).lower()
            if not normalized:
                continue
            actions.append(
                {
                    "label": _titleize(normalized),
                    "category": "clarify",
                    "sendText": normalized,
                    "authority": "backend_follow_up",
                }
            )

    decision = _text(trust.get("decision"))
    approval_state = _text(trust.get("approval_state"))
    available_scopes = [str(scope).strip().lower() for scope in trust.get("available_scopes") or [] if str(scope).strip()]
    if decision == "confirmation_required" or approval_state == "pending_operator_confirmation":
        scope_actions = [
            ("once", "Approve Once", "approve once"),
            ("task", "Approve Task", "approve for task"),
            ("session", "Approve Session", "approve for session"),
        ]
        for scope_key, label, command in scope_actions:
            if scope_key in available_scopes:
                actions.append(
                    {
                        "label": label,
                        "category": "approve",
                        "sendText": command,
                        "authority": "backend_follow_up",
                    }
                )
        actions.append(
            {
                "label": "Deny",
                "category": "deny",
                "sendText": "deny",
                "authority": "backend_follow_up",
            }
        )

    next_suggestion = latest_message.get("nextSuggestion") if isinstance(latest_message.get("nextSuggestion"), dict) else {}
    suggestion_command = _text(next_suggestion.get("command"))
    suggestion_label = _text(next_suggestion.get("title"))
    if suggestion_command and not any(action.get("sendText") == suggestion_command for action in actions):
        actions.append(
            {
                "label": suggestion_label or "Continue",
                "category": "continue",
                "sendText": suggestion_command,
                "authority": "backend_follow_up",
            }
        )

    if family:
        actions.append(
            {
                "label": "Inspect Route",
                "category": "inspect",
                "localAction": "open_route_inspector",
                "authority": "local_presentational",
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for action in actions:
        key = (str(action.get("label") or ""), str(action.get("sendText") or action.get("localAction") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def _normalized_result_state(
    *,
    request_stage: str,
    trust: dict[str, Any],
    winner: dict[str, Any],
    parameters: dict[str, Any],
) -> str:
    stage = request_stage.strip().lower()
    approval_state = _text(trust.get("approval_state")).lower()
    decision = _text(trust.get("decision")).lower()
    winner_status = _text(winner.get("status")).lower()

    if stage == "clarify_payload" or bool(winner.get("clarification_needed")):
        return "unresolved"
    if stage == "recovery_ready" or "recovery" in winner_status:
        return "recovery_in_progress"
    if stage == "preview":
        return "preview_ready"
    if stage == "awaiting_confirmation" or approval_state == "pending_operator_confirmation":
        return "awaiting_approval"
    if stage == "confirm_execution" or winner_status == "ready_after_approval":
        return "ready_after_approval"
    if decision == "blocked" or approval_state in {"denied", "revoked", "expired"}:
        return "blocked"
    raw_state = (
        _text(parameters.get("result_state"))
        or winner_status
        or approval_state
    ).strip().lower()
    if raw_state in {"verified", "completed"}:
        return "verified" if raw_state == "verified" else "attempted"
    if raw_state in {"failed", "uncertain", "unknown"}:
        return "unresolved"
    if raw_state == "blocked":
        return "blocked"
    if raw_state == "stale":
        return "stale"
    return "prepared"


def _composer_placeholder(result_state: str) -> str:
    if result_state == "preview_ready":
        return "Continue the live request or redirect it with a grounded follow-up."
    if result_state == "awaiting_approval":
        return "Approve, deny, or redirect the held request with a truthful follow-up."
    if result_state == "unresolved":
        return "Clarify the live request or ask Stormhelm to rebind it."
    return "Give Stormhelm a grounded request or continue the current thread."


def _default_title(*, family: str, request_stage: str, result_state: str) -> str:
    if request_stage == "preview":
        return "Relay Preview" if family == "discord_relay" else "Preview Ready"
    if request_stage == "clarify_payload":
        return "Relay Clarification" if family == "discord_relay" else "Clarification Needed"
    if request_stage == "awaiting_confirmation":
        return "Software Approval" if family == "software_control" else "Approval Needed"
    if result_state == "recovery_in_progress":
        return "Recovery Route"
    if family:
        return _route_label(family)
    return "Command Bearing"


def _route_label(family: str) -> str:
    if not family:
        return "Command Surface"
    return _ROUTE_LABELS.get(family, _titleize(family))


def _request_stage_label(value: str) -> str:
    if not value:
        return "Live"
    return _REQUEST_STAGE_LABELS.get(value, _titleize(value))


def _titleize(value: str) -> str:
    text = _text(value).replace("-", " ").replace("_", " ").strip()
    return text.title() if text else ""


def _text(value: Any) -> str:
    return str(value or "").strip()
