from __future__ import annotations

from typing import Any


_ROUTE_LABELS = {
    "discord_relay": "Discord Relay",
    "software_control": "Software Control",
    "software_recovery": "Software Recovery",
    "screen_awareness": "Visual Context",
    "task_continuity": "Task Continuity",
    "watch_runtime": "Runtime Watch",
    "memory": "Memory",
}
_RESULT_LABELS = {
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
_STAGE_LABELS = {
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
    request = dict(active_request_state or {})
    latest = dict(latest_message or {})
    metadata = latest.get("metadata") if isinstance(latest.get("metadata"), dict) else {}
    route_state = metadata.get("route_state") if isinstance(metadata.get("route_state"), dict) else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    deictic = route_state.get("deictic_binding") if isinstance(route_state.get("deictic_binding"), dict) else {}
    decomposition = route_state.get("decomposition") if isinstance(route_state.get("decomposition"), dict) else {}
    parameters = request.get("parameters") if isinstance(request.get("parameters"), dict) else {}
    trust = request.get("trust") if isinstance(request.get("trust"), dict) else {}
    task = dict(active_task or {})
    status_payload = dict(status or {})
    recent = [dict(item) for item in recent_context_resolutions or [] if isinstance(item, dict)]
    workspace = dict(workspace_focus or {})

    if not request and not route_state:
        return _empty_surface()

    stage = _text(parameters.get("request_stage")) or _text(winner.get("status"))
    family = _family_key(_text(request.get("family")) or _text(winner.get("route_family")), stage)
    continuity = _continuity(task)
    memory = _memory(status_payload, recent)
    runtime = _runtime(status_payload)
    invalidations = _invalidations(parameters, trust, deictic, route_state, continuity)
    result_state = _result_state(stage, trust, winner, parameters, invalidations)
    route_label = _route_label(family)
    status_label = _RESULT_LABELS.get(result_state, _title(result_state))
    subject = _text(request.get("subject")) or _text(decomposition.get("subject"))
    title = _text(latest.get("bearingTitle")) or _text(latest.get("bearing_title")) or _default_title(family, stage, result_state)
    body = _text(latest.get("fullResponse")) or _text(latest.get("content")) or _text(trust.get("operator_message")) or continuity["summary"] or next(iter(memory["contributors"] or ["Stormhelm is holding the current command posture truthfully."]), "")
    subtitle = " • ".join(part for part in (route_label, subject, status_label) if part)
    provenance = _provenance(parameters, trust, deictic, recent, workspace)
    trace = _trace(family, request, winner, parameters, deictic)
    support = _support(status_payload, task, trust)
    actions = _actions(family, result_state, stage, trust, parameters, latest)
    stations = _stations(family, subtitle, body, status_label, result_state, subject, parameters, trust, deictic, continuity, memory, runtime, invalidations, actions)
    chips = [_chip("Route", route_label), _chip("Request Stage", _stage(stage)), _chip("Status", status_label, _tone(result_state))]
    for entry in provenance:
        if entry["label"] in {"Binding", "Trust"}:
            chips.append(_chip(entry["label"], entry["value"], str(entry.get("tone") or "steady")))
    if continuity["present"]:
        chips.append(_chip("Continuity", continuity["posture"], continuity["tone"]))
    return {
        "ghostPrimaryCard": {"title": title, "subtitle": subtitle, "body": body, "routeLabel": route_label, "resultState": result_state, "statusLabel": status_label, "provenance": provenance},
        "ghostActionStrip": actions,
        "requestComposer": {"placeholder": _placeholder(result_state), "headline": title, "summary": _text(latest.get("microResponse")) or body, "chips": chips, "quickActions": [dict(action) for action in actions if action.get("sendText")][:4], "clarificationChoices": [dict(action) for action in actions if action.get("category") == "clarify"]},
        "routeInspector": {"title": title, "subtitle": subtitle, "summary": _ROUTE_INSPECTOR_SUMMARY, "body": body, "resultState": result_state, "statusLabel": status_label, "trace": trace, "provenance": provenance, "supportSystems": support, "invalidations": invalidations, "actions": _dedupe(actions + _reveal_actions(stations))},
        "deckStations": stations,
    }


def _stations(
    family: str,
    subtitle: str,
    body: str,
    status_label: str,
    result_state: str,
    subject: str,
    parameters: dict[str, Any],
    trust: dict[str, Any],
    deictic: dict[str, Any],
    continuity: dict[str, Any],
    memory: dict[str, Any],
    runtime: dict[str, Any],
    invalidations: list[dict[str, str]],
    base_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ctx = {
        "family": family,
        "subtitle": subtitle,
        "body": body,
        "status_label": status_label,
        "result_state": result_state,
        "subject": subject,
        "parameters": parameters,
        "trust": trust,
        "deictic": deictic,
        "continuity": continuity,
        "memory": memory,
        "runtime": runtime,
        "invalidations": invalidations,
        "base_actions": base_actions,
    }
    stations: list[dict[str, Any]] = []
    if family == "discord_relay":
        preview = parameters.get("pending_preview") if isinstance(parameters.get("pending_preview"), dict) else {}
        payload = preview.get("payload") if isinstance(preview.get("payload"), dict) else {}
        stations.append(_station("discord_relay", ctx, chips=[_chip("State", status_label, _tone(result_state)), _chip("Payload", _payload(_text(payload.get("kind")) or _text(parameters.get("payload_hint"))))], sections=[_section("Relay Preview", [_entry("Destination", _text(preview.get("destination", {}).get("label")) or _text(parameters.get("destination_alias")) or "Relay"), _entry("Payload", _payload(_text(payload.get("kind")) or _text(parameters.get("payload_hint"))), _text(payload.get("summary")) or _text(payload.get("preview_text"))), _entry("Binding", _source(_text(deictic.get("selected_source"))), _text(deictic.get("source_summary")))])], invalidations=_filter_invalidations(invalidations, {"Preview", "Binding", "Continuity"}), actions=_station_actions("discord_relay", ctx, True)))
    elif family in {"software_control", "software_recovery"}:
        operation = _title(_text(parameters.get("operation_type")) or "software")
        target = _title(_text(parameters.get("target_name")) or _text(subject))
        route = _title(_text(parameters.get("selected_source_route")) or "native")
        stations.append(_station(family, ctx, chips=[_chip("State", status_label, _tone(result_state)), _chip("Operation", f"{operation} {target}".strip()), _chip("Route", route)], sections=[_section("Software Route", [_entry("Operation", f"{operation} {target}".strip()), _entry("Request Stage", _stage(_text(parameters.get("request_stage")))), _entry("Recovery Route", route), _entry("Verification", status_label, _text(parameters.get("recovery_summary")) or body)])], invalidations=_filter_invalidations(invalidations, {"Recovery", "Binding", "Approval"}), actions=_station_actions(family, ctx, True)))
    elif family == "screen_awareness":
        screen = runtime["screenAwareness"]
        stations.append(_station("screen_awareness", ctx, chips=[_chip("State", status_label, _tone(result_state)), _chip("Phase", _text(screen.get("phase")) or "Active")], sections=[_section("Screen Route", [_entry("Policy", _title(_text(screen.get("policy", {}).get("action_policy_mode")) or "confirm_before_act")), _entry("Binding", _text(deictic.get("selected_target", {}).get("label")) or "Current screen target", _text(deictic.get("source_summary"))), _entry("Trace", f"{screen.get('trace', {}).get('durationMs', 0):.1f} ms" if screen.get("trace", {}).get("durationMs") else "", _text(screen.get("trace", {}).get("summary")))])], invalidations=_filter_invalidations(invalidations, {"Binding"}), actions=_station_actions("screen_awareness", ctx, True)))
    trust_state = _text(trust.get("approval_state")).lower()
    if trust and trust_state not in {"approved_for_task", "approved_for_session", "approved_once", "allowed", "not_required"}:
        scopes = ", ".join(_title(scope) for scope in trust.get("available_scopes") or [] if _text(scope))
        stations.append(_station("trust", ctx, chips=[_chip("Approval", _title(_text(trust.get("approval_state")) or "not_required"), _tone(result_state))], sections=[_section("Approval Flow", [_entry("Approval State", _title(_text(trust.get("approval_state")) or "Not Required"), _text(trust.get("operator_message"))), _entry("Request", _text(trust.get("request_id")) or "Live trust object"), _entry("Scopes", scopes or "No approval scopes"), _entry("Binding", _source(_text(deictic.get("selected_source"))), _text(deictic.get("source_summary")))])], invalidations=_filter_invalidations(invalidations, {"Approval", "Binding"}), actions=_station_actions("trust", ctx, True)))
    if continuity["present"]:
        stations.append(_station("task_continuity", ctx, chips=[_chip("Continuity", continuity["posture"], continuity["tone"]), _chip("Freshness", continuity["freshness"], continuity["tone"])], sections=[_section("Task Continuity", [_entry("Task", continuity["task"], continuity["state"]), _entry("Posture", continuity["posture"]), _entry("Active Step", continuity["active_step"]), _entry("Next Move", continuity["next_label"], continuity["next_detail"]), _entry("Blocker", continuity["blocker"])])], invalidations=_filter_invalidations(invalidations, {"Continuity"}), actions=_station_actions("task_continuity", ctx, False)))
    if runtime["present"]:
        entries = []
        if runtime["watch"]["present"]:
            entries.extend([_entry("Watch Health", runtime["watch"]["health"]), _entry("Queue", runtime["watch"]["queue"]), _entry("Recent Failures", runtime["watch"]["failures"]), _entry("Current Tool", runtime["watch"]["tool"])])
        if runtime["lifecycle"]["present"]:
            entries.extend([_entry("Lifecycle State", runtime["lifecycle"]["state"]), _entry("Lifecycle Hold", runtime["lifecycle"]["hold"], runtime["lifecycle"]["cleanup"])])
        stations.append(_station("watch_runtime", ctx, chips=[_chip("Runtime", runtime["headline"], runtime["tone"])], sections=[_section("Runtime Watch", entries)], invalidations=_filter_invalidations(invalidations, {"Lifecycle", "Recovery"}), actions=_station_actions("watch_runtime", ctx, False)))
    if memory["present"]:
        stations.append(_station("memory", ctx, chips=[_chip("Memory", memory["count"])], sections=[_section("Support Memory", [_entry("Role", "Support Only"), _entry("Families", memory["count"]), _entry("Recent Support", "Current contributors", next(iter(memory["contributors"] or []), ""))])], invalidations=[], actions=_station_actions("memory", ctx, False)))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for station in stations:
        station_id = str(station["stationId"])
        if station_id in seen:
            continue
        seen.add(station_id)
        deduped.append(station)
    for index, station in enumerate(deduped[:3]):
        station["layoutSlot"] = ("primary", "secondary", "tertiary")[index]
    return deduped[:3]


def _station(station_key: str, ctx: dict[str, Any], *, chips: list[dict[str, str]], sections: list[dict[str, Any]], invalidations: list[dict[str, str]], actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {"stationId": _STATION_IDS[station_key], "stationFamily": station_key, "eyebrow": _route_label(station_key), "title": _STATION_TITLES[station_key], "subtitle": ctx["subtitle"], "summary": ctx["body"], "body": ctx["body"], "statusLabel": ctx["status_label"], "resultState": ctx["result_state"], "chips": chips, "sections": sections, "invalidations": invalidations, "actions": actions}


def _station_actions(station_family: str, ctx: dict[str, Any], include_base: bool) -> list[dict[str, Any]]:
    actions = list(ctx["base_actions"]) if include_base else []
    if station_family == "task_continuity":
        suggestion = next((action for action in ctx["base_actions"] if action.get("sendText") and action.get("category") in {"retry", "continue", "resume"}), None)
        if suggestion is not None:
            actions.insert(0, dict(suggestion))
    workspace_action = _WORKSPACE_ACTIONS.get(station_family)
    if workspace_action:
        module_key, section_key, label = workspace_action
        actions.append({"label": label, "category": "reveal", "localAction": f"open_workspace:{module_key}:{section_key}", "authority": "local_presentational"})
    if station_family == "trust":
        actions.append({"label": "Inspect Route", "category": "inspect", "localAction": "open_route_inspector", "authority": "local_presentational"})
    return _dedupe(actions)


def _reveal_actions(stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = {"trust": "Show Trust", "task_continuity": "Show Continuity", "watch_runtime": "Show Runtime", "memory": "Show Memory"}
    return _dedupe([{"label": labels[family], "category": "reveal", "localAction": f"open_panel:{station['stationId']}", "authority": "local_presentational"} for station in stations if (family := str(station.get("stationFamily") or "")) in labels])


def _provenance(parameters: dict[str, Any], trust: dict[str, Any], deictic: dict[str, Any], recent: list[dict[str, Any]], workspace: dict[str, Any]) -> list[dict[str, str]]:
    entries = []
    selected_source = _text(deictic.get("selected_source")) or _text(next(iter(recent or [{}]), {}).get("selected_source"))
    selected_target = deictic.get("selected_target") if isinstance(deictic.get("selected_target"), dict) else {}
    freshness = _text(selected_target.get("freshness")).lower()
    if selected_source:
        value = _source(selected_source)
        if freshness in _STALE_TOKENS:
            value = f"{value} (Stale)"
        entries.append({"label": "Binding", "value": value, "tone": "stale" if freshness in _STALE_TOKENS else "steady"})
    payload_hint = _text(parameters.get("payload_hint")) or _text(selected_target.get("target_type"))
    if payload_hint:
        entries.append({"label": "Payload", "value": _payload(payload_hint), "tone": "steady"})
    approval_state = _text(trust.get("approval_state"))
    if approval_state:
        entries.append({"label": "Trust", "value": _title(approval_state), "tone": "stale" if approval_state in {"expired", "revoked"} else "attention"})
    if workspace.get("name"):
        entries.append({"label": "Workspace", "value": _text(workspace.get("name")), "tone": "steady"})
    return entries


def _trace(family: str, request: dict[str, Any], winner: dict[str, Any], parameters: dict[str, Any], deictic: dict[str, Any]) -> list[dict[str, str]]:
    route = request.get("route") if isinstance(request.get("route"), dict) else {}
    entries = [{"label": "Route", "value": _route_label(family)}, {"label": "Query Shape", "value": _title(_text(request.get("query_shape")) or _text(winner.get("query_shape")))}, {"label": "Posture", "value": _title(_text(winner.get("posture")))}, {"label": "Request Stage", "value": _stage(_text(parameters.get("request_stage")) or _text(winner.get("status")))}]
    if _text(parameters.get("selected_source_route")):
        entries.append({"label": "Selected Route", "value": _text(parameters.get("selected_source_route"))})
    if _text(route.get("route_mode")):
        entries.append({"label": "Route Mode", "value": _text(route.get("route_mode"))})
    if _text(route.get("response_mode")):
        entries.append({"label": "Response Mode", "value": _title(_text(route.get("response_mode")))})
    if _text(deictic.get("selected_source")):
        entries.append({"label": "Binding Source", "value": _source(_text(deictic.get("selected_source")))})
    return entries


def _support(status: dict[str, Any], task: dict[str, Any], trust: dict[str, Any]) -> list[dict[str, str]]:
    entries = []
    if task.get("title"):
        entries.append({"label": "Task", "value": _text(task.get("title"))})
    if _text(trust.get("approval_state")):
        entries.append({"label": "Trust", "value": _title(_text(trust.get("approval_state")))})
    memory = status.get("memory") if isinstance(status.get("memory"), dict) else {}
    families = memory.get("families") if isinstance(memory.get("families"), dict) else {}
    count = sum(int(value or 0) for value in families.values())
    if count:
        entries.append({"label": "Memory", "value": f"{count} family {'record' if count == 1 else 'records'}"})
    lifecycle = status.get("lifecycle") if isinstance(status.get("lifecycle"), dict) else {}
    bootstrap = lifecycle.get("bootstrap") if isinstance(lifecycle.get("bootstrap"), dict) else {}
    if _text(bootstrap.get("lifecycle_hold_reason")):
        entries.append({"label": "Lifecycle", "value": _text(bootstrap.get("lifecycle_hold_reason"))})
    watch = status.get("watch_state") if isinstance(status.get("watch_state"), dict) else {}
    active_jobs = int(watch.get("active_jobs") or 0)
    queued_jobs = int(watch.get("queued_jobs") or 0)
    if active_jobs or queued_jobs:
        entries.append({"label": "Watch", "value": f"{active_jobs} active / {queued_jobs} queued"})
    return entries


def _actions(family: str, result_state: str, stage: str, trust: dict[str, Any], parameters: dict[str, Any], latest: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    choices = parameters.get("ambiguity_choices") if isinstance(parameters.get("ambiguity_choices"), list) else []
    if stage == "clarify_payload":
        for choice in choices[:3]:
            choice_text = _text(choice).lower()
            if choice_text:
                actions.append({"label": _title(choice_text), "category": "clarify", "sendText": choice_text, "authority": "backend_follow_up"})
    approval_state = _text(trust.get("approval_state")).lower()
    if approval_state == "pending_operator_confirmation" or (_text(trust.get("decision")) == "confirmation_required" and approval_state not in {"expired", "revoked", "denied"}):
        for scope, label, command in (("once", "Approve Once", "approve once"), ("task", "Approve Task", "approve for task"), ("session", "Approve Session", "approve for session")):
            if scope in [str(item).strip().lower() for item in trust.get("available_scopes") or []]:
                actions.append({"label": label, "category": "approve", "sendText": command, "authority": "backend_follow_up"})
        actions.append({"label": "Deny", "category": "deny", "sendText": "deny", "authority": "backend_follow_up"})
    suggestion = latest.get("nextSuggestion") if isinstance(latest.get("nextSuggestion"), dict) else {}
    if _text(suggestion.get("command")):
        label = _text(suggestion.get("title")) or ("Continue Recovery" if result_state == "recovery_in_progress" else "Refresh" if result_state == "stale" else "Continue")
        category = "retry" if "retry" in label.lower() or result_state in {"recovery_in_progress", "stale"} else "continue"
        actions.append({"label": label, "category": category, "sendText": _text(suggestion.get("command")), "authority": "backend_follow_up"})
    if family:
        actions.append({"label": "Inspect Route", "category": "inspect", "localAction": "open_route_inspector", "authority": "local_presentational"})
    return _dedupe(actions)


def _invalidations(parameters: dict[str, Any], trust: dict[str, Any], deictic: dict[str, Any], route_state: dict[str, Any], continuity: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    preview = parameters.get("pending_preview") if isinstance(parameters.get("pending_preview"), dict) else {}
    if _text(preview.get("invalidated_reason")) or _text(preview.get("freshness")).lower() in _STALE_TOKENS:
        entries.append({"label": "Preview", "reason": _text(preview.get("invalidated_reason")) or "The stored preview is no longer current.", "tone": "stale"})
    approval_state = _text(trust.get("approval_state")).lower()
    if approval_state in {"expired", "revoked"}:
        entries.append({"label": "Approval", "reason": _text(trust.get("operator_message")) or "The approval object is no longer live.", "tone": "stale"})
    selected_target = deictic.get("selected_target") if isinstance(deictic.get("selected_target"), dict) else {}
    if _text(deictic.get("binding_posture")).lower() in _STALE_TOKENS or _text(selected_target.get("freshness")).lower() in _STALE_TOKENS:
        entries.append({"label": "Binding", "reason": _text(deictic.get("source_summary")) or "The bound target is no longer live.", "tone": "stale"})
    if continuity["present"] and continuity["tone"] == "stale":
        entries.append({"label": "Continuity", "reason": continuity["stale_reason"] or continuity["summary"] or "Task continuity lost to fresher state.", "tone": "stale"})
    continuation = route_state.get("continuation") if isinstance(route_state.get("continuation"), dict) else {}
    if _text(continuation.get("posture")).lower() in _STALE_TOKENS:
        entries.append({"label": "Recovery", "reason": _text(continuation.get("reason")) or "The prior recovery posture is no longer live.", "tone": "stale"})
    return _dedupe_invalidations(entries)


def _memory(status: dict[str, Any], recent: list[dict[str, Any]]) -> dict[str, Any]:
    memory = status.get("memory") if isinstance(status.get("memory"), dict) else {}
    families = memory.get("families") if isinstance(memory.get("families"), dict) else {}
    count = sum(int(value or 0) for value in families.values())
    contributors = [_text(item.get("summary")) for item in memory.get("active_contributors") or [] if isinstance(item, dict) and _text(item.get("summary"))]
    if not contributors:
        contributors = [_text(item.get("summary")) for item in recent[:2] if _text(item.get("summary"))]
    return {"present": bool(count or contributors), "count": f"{count} family {'record' if count == 1 else 'records'}" if count else "Support memory", "contributors": contributors}


def _runtime(status: dict[str, Any]) -> dict[str, Any]:
    watch = status.get("watch_state") if isinstance(status.get("watch_state"), dict) else {}
    lifecycle = status.get("lifecycle") if isinstance(status.get("lifecycle"), dict) else {}
    bootstrap = lifecycle.get("bootstrap") if isinstance(lifecycle.get("bootstrap"), dict) else {}
    uninstall = lifecycle.get("uninstall_plan") if isinstance(lifecycle.get("uninstall_plan"), dict) else {}
    cleanup = uninstall.get("destructive_cleanup_plan") if isinstance(uninstall.get("destructive_cleanup_plan"), dict) else {}
    screen = status.get("screen_awareness") if isinstance(status.get("screen_awareness"), dict) else {}
    policy = screen.get("policy_state") if isinstance(screen.get("policy_state"), dict) else {}
    hardening = screen.get("hardening") if isinstance(screen.get("hardening"), dict) else {}
    latest_trace = hardening.get("latest_trace") if isinstance(hardening.get("latest_trace"), dict) else {}
    active_jobs = int(watch.get("active_jobs") or 0)
    queued_jobs = int(watch.get("queued_jobs") or 0)
    recent_failures = int(watch.get("recent_failures") or 0)
    return {
        "present": bool(active_jobs or queued_jobs or recent_failures or _text(bootstrap.get("lifecycle_hold_reason")) or screen),
        "headline": "Degraded" if recent_failures else "Live",
        "tone": "warning" if recent_failures else "steady",
        "watch": {"present": bool(active_jobs or queued_jobs or recent_failures or _text(watch.get("health")) or _text(watch.get("current_tool"))), "health": _title(_text(watch.get("health")) or ("degraded" if recent_failures else "steady")), "queue": f"{active_jobs} active / {queued_jobs} queued", "failures": str(recent_failures), "tool": _title(_text(watch.get("current_tool")) or "Not reported")},
        "lifecycle": {"present": bool(_text(bootstrap.get("lifecycle_hold_reason")) or _text(cleanup.get("operator_summary"))), "state": _title(_text(bootstrap.get("state")) or "steady"), "hold": _text(bootstrap.get("lifecycle_hold_reason")) or "No lifecycle hold", "cleanup": _text(cleanup.get("operator_summary"))},
        "screenAwareness": {"phase": _title(_text(screen.get("phase"))), "policy": {"action_policy_mode": _text(policy.get("action_policy_mode"))}, "trace": {"durationMs": float(latest_trace.get("total_duration_ms") or 0.0), "summary": _text(policy.get("summary"))}},
    }


def _continuity(task: dict[str, Any]) -> dict[str, Any]:
    if not task:
        return {"present": False, "summary": "", "stale_reason": "", "tone": "steady", "posture": "", "freshness": "", "task": "", "state": "", "active_step": "", "next_label": "", "next_detail": "", "blocker": ""}
    continuity = task.get("continuity") if isinstance(task.get("continuity"), dict) else {}
    posture = _text(continuity.get("posture")) or _text(task.get("state")) or "live"
    freshness = _text(continuity.get("freshness")) or ("stale" if posture.lower() in _STALE_TOKENS else "current")
    return {
        "present": True,
        "summary": _text(continuity.get("stale_reason")) or _text(continuity.get("next_step")) or _text(task.get("whereLeftOff")) or _text(task.get("latestSummary")),
        "stale_reason": _text(continuity.get("stale_reason")),
        "tone": "stale" if freshness.lower() in _STALE_TOKENS or posture.lower() in _STALE_TOKENS else "live" if posture.lower() in {"resumable", "ready", "current"} else "steady",
        "posture": _title(posture),
        "freshness": _title(freshness),
        "task": _text(task.get("title")) or "Active task",
        "state": _title(_text(task.get("state")) or posture),
        "active_step": _text(continuity.get("active_step")) or _text(task.get("whereLeftOff")) or "Awaiting next move",
        "next_label": _title(_text(continuity.get("next_move")) or "Continue"),
        "next_detail": _text(continuity.get("next_step")) or _text(task.get("whereLeftOff")) or _text(task.get("latestSummary")),
        "blocker": _text(continuity.get("blocker_state")) or "No active blocker",
    }


def _result_state(stage: str, trust: dict[str, Any], winner: dict[str, Any], parameters: dict[str, Any], invalidations: list[dict[str, str]]) -> str:
    approval_state = _text(trust.get("approval_state")).lower()
    winner_status = _text(winner.get("status")).lower()
    if stage == "clarify_payload" or bool(winner.get("clarification_needed")):
        return "unresolved"
    if invalidations:
        return "stale"
    if stage == "recovery_ready" or "recovery" in winner_status:
        return "recovery_in_progress"
    if stage == "preview":
        return "preview_ready"
    if stage == "awaiting_confirmation" or approval_state == "pending_operator_confirmation":
        return "awaiting_approval"
    if stage == "confirm_execution" or winner_status == "ready_after_approval":
        return "ready_after_approval"
    if _text(trust.get("decision")).lower() == "blocked" or approval_state == "denied":
        return "blocked"
    raw = (_text(parameters.get("result_state")) or winner_status or approval_state).lower()
    if raw == "verified":
        return "verified"
    if raw in {"attempted", "completed", "dispatch", "dispatched"}:
        return "attempted"
    if raw in {"failed", "uncertain", "unknown"}:
        return "unresolved"
    if raw in _STALE_TOKENS:
        return "stale"
    return "prepared"


def _placeholder(result_state: str) -> str:
    if result_state == "preview_ready":
        return "Continue the live request or redirect it with a grounded follow-up."
    if result_state == "awaiting_approval":
        return "Approve, deny, or redirect the held request with a truthful follow-up."
    if result_state == "recovery_in_progress":
        return "Continue the recovery flow or redirect it with a grounded follow-up."
    if result_state == "stale":
        return "Refresh the stale request, rebind the target, or start a fresh command."
    if result_state == "unresolved":
        return "Clarify the live request or ask Stormhelm to rebind it."
    return "Give Stormhelm a grounded request or continue the current thread."


def _family_key(family: str, stage: str) -> str:
    return "software_recovery" if family.strip().lower() == "software_control" and stage.strip().lower() == "recovery_ready" else family.strip().lower()


def _default_title(family: str, stage: str, result_state: str) -> str:
    if family == "software_recovery" or result_state == "recovery_in_progress":
        return "Software Recovery"
    if stage == "preview":
        return "Relay Preview" if family == "discord_relay" else "Preview Ready"
    if stage == "clarify_payload":
        return "Relay Clarification" if family == "discord_relay" else "Clarification Needed"
    if stage == "awaiting_confirmation":
        return "Software Approval" if family == "software_control" else "Approval Needed"
    return _route_label(family) if family else "Command Bearing"


def _empty_surface() -> dict[str, Any]:
    return {
        "ghostPrimaryCard": {},
        "ghostActionStrip": [],
        "requestComposer": {"placeholder": "Give Stormhelm a grounded request or continue the current thread.", "headline": "", "summary": "", "chips": [], "quickActions": [], "clarificationChoices": []},
        "routeInspector": {},
        "deckStations": [],
    }


def _dedupe_invalidations(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped = []
    for entry in entries:
        key = (str(entry.get("label") or ""), str(entry.get("reason") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _dedupe(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped = []
    for entry in entries:
        key = (str(entry.get("label") or ""), str(entry.get("sendText") or entry.get("localAction") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _chip(label: str, value: str, tone: str = "steady") -> dict[str, str]:
    return {"label": label, "value": value, "tone": tone}


def _section(title: str, entries: list[dict[str, str]]) -> dict[str, Any]:
    return {"title": title, "summary": "", "entries": entries}


def _entry(primary: str, secondary: str, detail: str = "") -> dict[str, str]:
    return {"primary": primary, "secondary": secondary, "detail": detail}


def _filter_invalidations(entries: list[dict[str, str]], allowed: set[str]) -> list[dict[str, str]]:
    return [dict(entry) for entry in entries if str(entry.get("label") or "") in allowed]


def _route_label(value: str) -> str:
    return _ROUTE_LABELS.get(value, _title(value)) if value else "Command Surface"


def _stage(value: str) -> str:
    return _STAGE_LABELS.get(value, _title(value)) if value else "Live"


def _payload(value: str) -> str:
    return _PAYLOAD_LABELS.get(value, _title(value)) if value else "Contextual"


def _source(value: str) -> str:
    return _SOURCE_LABELS.get(value, _title(value)) if value else "Context"


def _tone(result_state: str) -> str:
    return _RESULT_TONES.get(result_state, "steady")


def _title(value: str) -> str:
    text = _text(value).replace("-", " ").replace("_", " ")
    return text.title() if text else ""


def _text(value: Any) -> str:
    return str(value or "").strip()
