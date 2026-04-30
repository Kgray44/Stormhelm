from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from stormhelm.ui.camera_ghost_surface import build_camera_ghost_surface_model


_ROUTE_LABELS = {
    "camera_awareness": "Camera Awareness",
    "discord_relay": "Discord Relay",
    "web_retrieval": "Web Evidence",
    "software_control": "Software Control",
    "software_recovery": "Software Recovery",
    "screen_awareness": "Visual Context",
    "task_continuity": "Task Continuity",
    "watch_runtime": "Runtime Watch",
    "memory": "Memory",
    "generic_provider": "Provider Fallback",
}
_RESULT_LABELS = {
    "prepared": "Prepared",
    "preview_ready": "Preview Ready",
    "awaiting_approval": "Awaiting Approval",
    "ready_after_approval": "Ready After Approval",
    "attempted": "Attempted",
    "verified": "Verified",
    "extracted": "Extracted",
    "partial": "Partial",
    "fallback_available": "Fallback Available",
    "fallback_used": "Fallback Used",
    "provider_unavailable": "Provider Unavailable",
    "provider_running": "Provider Running",
    "provider_cancelled": "Provider Cancelled",
    "timeout": "Timed Out",
    "unsupported": "Unsupported",
    "failed": "Failed",
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
    "web_retrieval": "web-evidence-station",
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
    "web_retrieval": "Web Evidence",
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
    "extracted": "live",
    "partial": "attention",
    "fallback_available": "attention",
    "fallback_used": "attention",
    "provider_unavailable": "warning",
    "provider_running": "attention",
    "provider_cancelled": "warning",
    "timeout": "warning",
    "unsupported": "warning",
    "failed": "warning",
    "unresolved": "warning",
    "blocked": "warning",
    "recovery_in_progress": "attention",
    "stale": "stale",
}
_STALE_TOKENS = {"stale", "expired", "invalid", "invalidated", "superseded", "replaced", "revoked"}
_ROUTE_INSPECTOR_SUMMARY = "Backend-owned route, provenance, and trace state."


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _ms_text(value: Any) -> str:
    number = _number(value)
    if number.is_integer():
        return f"{int(number)} ms"
    return f"{round(number, 3)} ms"


def _screen_awareness_state(value: Any) -> dict[str, Any]:
    screen = _mapping(value)
    policy = _mapping(screen.get("policy")) or _mapping(screen.get("policy_state"))
    trace = _mapping(screen.get("trace"))
    if not trace:
        hardening = _mapping(screen.get("hardening"))
        trace = _mapping(hardening.get("latest_trace"))
    browser_adapters = _mapping(screen.get("browser_adapters"))
    if not browser_adapters:
        browser_adapters = _mapping(screen.get("browserAdapters"))
    duration = _number(trace.get("durationMs") if "durationMs" in trace else trace.get("total_duration_ms"))
    return {
        "present": bool(screen or policy or trace or browser_adapters),
        "phase": _text(screen.get("phase")),
        "policy": {"action_policy_mode": _text(policy.get("action_policy_mode"))},
        "trace": {"durationMs": duration, "summary": _text(trace.get("summary")) or _text(policy.get("summary"))},
        "browser_adapters": browser_adapters,
    }


def _continuity_state(value: Any) -> dict[str, Any]:
    continuity = _mapping(value)
    return {
        "present": bool(continuity.get("present", False)),
        "summary": _text(continuity.get("summary")),
        "stale_reason": _text(continuity.get("stale_reason")),
        "tone": _text(continuity.get("tone")) or "steady",
        "posture": _text(continuity.get("posture")),
        "freshness": _text(continuity.get("freshness")),
        "task": _text(continuity.get("task")),
        "state": _text(continuity.get("state")),
        "active_step": _text(continuity.get("active_step")),
        "next_label": _text(continuity.get("next_label")),
        "next_detail": _text(continuity.get("next_detail")),
        "blocker": _text(continuity.get("blocker")),
    }


def _memory_state(value: Any) -> dict[str, Any]:
    memory = _mapping(value)
    contributors = [_text(item) for item in memory.get("contributors") or [] if _text(item)]
    return {
        "present": bool(memory.get("present", False)),
        "count": _text(memory.get("count")) or "Support memory",
        "contributors": contributors,
    }


def _runtime_state(value: Any) -> dict[str, Any]:
    runtime = _mapping(value)
    watch = _mapping(runtime.get("watch"))
    lifecycle = _mapping(runtime.get("lifecycle"))
    screen = _screen_awareness_state(runtime.get("screenAwareness"))
    return {
        "present": bool(runtime.get("present", False)),
        "headline": _text(runtime.get("headline")) or "Live",
        "tone": _text(runtime.get("tone")) or "steady",
        "watch": {
            "present": bool(watch.get("present", False)),
            "health": _text(watch.get("health")) or "Not reported",
            "queue": _text(watch.get("queue")),
            "failures": _text(watch.get("failures")),
            "tool": _text(watch.get("tool")) or "Not reported",
        },
        "lifecycle": {
            "present": bool(lifecycle.get("present", False)),
            "state": _text(lifecycle.get("state")) or "Steady",
            "hold": _text(lifecycle.get("hold")) or "No lifecycle hold",
            "cleanup": _text(lifecycle.get("cleanup")),
        },
        "screenAwareness": screen,
    }


def build_command_surface_model(
    *,
    active_request_state: dict[str, Any] | None,
    active_task: dict[str, Any] | None,
    recent_context_resolutions: list[dict[str, Any]] | None,
    latest_message: dict[str, Any] | None,
    status: dict[str, Any] | None,
    workspace_focus: dict[str, Any] | None,
) -> dict[str, Any]:
    request = _mapping(active_request_state)
    latest = _mapping(latest_message)
    metadata = latest.get("metadata") if isinstance(latest.get("metadata"), dict) else {}
    route_state = metadata.get("route_state") if isinstance(metadata.get("route_state"), dict) else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    deictic = route_state.get("deictic_binding") if isinstance(route_state.get("deictic_binding"), dict) else {}
    decomposition = route_state.get("decomposition") if isinstance(route_state.get("decomposition"), dict) else {}
    parameters = request.get("parameters") if isinstance(request.get("parameters"), dict) else {}
    trust = request.get("trust") if isinstance(request.get("trust"), dict) else {}
    task = _mapping(active_task)
    status_payload = _mapping(status)
    recent = _mapping_list(recent_context_resolutions)
    workspace = _mapping(workspace_focus)

    if not request and not route_state:
        return _empty_surface()

    stage = _text(parameters.get("request_stage")) or _text(winner.get("status"))
    family = _family_key(_text(request.get("family")) or _text(winner.get("route_family")), stage)
    if family == "camera_awareness":
        camera_surface = build_camera_ghost_surface_model(
            active_request_state=request,
            latest_message=latest,
            status=status_payload,
        )
        if camera_surface.get("ghostPrimaryCard"):
            return camera_surface
    continuity = _continuity(task)
    memory = _memory(status_payload, recent)
    runtime = _runtime(status_payload)
    invalidations = _invalidations(parameters, trust, deictic, route_state, continuity)
    result_state = _result_state(stage, trust, winner, parameters, invalidations)
    route_label = _route_label(family)
    status_label = _RESULT_LABELS.get(result_state, _title(result_state))
    subject = _text(request.get("subject")) or _text(decomposition.get("subject"))
    title = _text(latest.get("bearingTitle")) or _text(latest.get("bearing_title")) or _default_title(family, stage, result_state)
    body = _text(latest.get("fullResponse")) or _text(latest.get("content")) or _text(trust.get("operator_message")) or _text(parameters.get("progress_summary")) or continuity["summary"] or next(iter(memory["contributors"] or ["Stormhelm is holding the current command posture truthfully."]), "")
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
    parameters = _mapping(parameters)
    trust = _mapping(trust)
    deictic = _mapping(deictic)
    continuity = _continuity_state(continuity)
    memory = _memory_state(memory)
    runtime = _runtime_state(runtime)
    invalidations = _mapping_list(invalidations)
    base_actions = _mapping_list(base_actions)
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
    if family == "web_retrieval":
        stations.append(_web_evidence_station(ctx))
    if family == "discord_relay":
        preview = parameters.get("pending_preview") if isinstance(parameters.get("pending_preview"), dict) else {}
        payload = preview.get("payload") if isinstance(preview.get("payload"), dict) else {}
        destination = _mapping(preview.get("destination"))
        stations.append(_station("discord_relay", ctx, chips=[_chip("State", status_label, _tone(result_state)), _chip("Payload", _payload(_text(payload.get("kind")) or _text(parameters.get("payload_hint"))))], sections=[_section("Relay Preview", [_entry("Destination", _text(destination.get("label")) or _text(parameters.get("destination_alias")) or "Relay"), _entry("Payload", _payload(_text(payload.get("kind")) or _text(parameters.get("payload_hint"))), _text(payload.get("summary")) or _text(payload.get("preview_text"))), _entry("Binding", _source(_text(deictic.get("selected_source"))), _text(deictic.get("source_summary")))])], invalidations=_filter_invalidations(invalidations, {"Preview", "Binding", "Continuity"}), actions=_station_actions("discord_relay", ctx, True)))
    elif family in {"software_control", "software_recovery"}:
        operation = _title(_text(parameters.get("operation_type")) or "software")
        target = _title(_text(parameters.get("target_name")) or _text(subject))
        route = _title(_text(parameters.get("selected_source_route")) or "native")
        stations.append(_station(family, ctx, chips=[_chip("State", status_label, _tone(result_state)), _chip("Operation", f"{operation} {target}".strip()), _chip("Route", route)], sections=[_section("Software Route", [_entry("Operation", f"{operation} {target}".strip()), _entry("Request Stage", _stage(_text(parameters.get("request_stage")))), _entry("Recovery Route", route), _entry("Verification", status_label, _text(parameters.get("recovery_summary")) or body)])], invalidations=_filter_invalidations(invalidations, {"Recovery", "Binding", "Approval"}), actions=_station_actions(family, ctx, True)))
    elif family == "screen_awareness":
        screen = _screen_awareness_state(runtime.get("screenAwareness"))
        policy = _mapping(screen.get("policy"))
        trace = _mapping(screen.get("trace"))
        selected_target = _mapping(deictic.get("selected_target"))
        duration = _number(trace.get("durationMs"))
        trace_value = f"{duration:.1f} ms" if duration else ""
        screen_entries = [
            _entry("Policy", _title(_text(policy.get("action_policy_mode")) or "confirm_before_act")),
            _entry("Binding", _text(selected_target.get("label")) or "Current screen target", _text(deictic.get("source_summary")) or "Screen-awareness state is partial."),
            _entry("Trace", trace_value, _text(trace.get("summary")) or "No screen trace summary is available."),
        ]
        screen_entries.extend(_playwright_browser_adapter_entries(screen))
        stations.append(_station("screen_awareness", ctx, chips=[_chip("State", status_label, _tone(result_state)), _chip("Phase", _text(screen.get("phase")) or "Active")], sections=[_section("Screen Route", screen_entries)], invalidations=_filter_invalidations(invalidations, {"Binding"}), actions=_station_actions("screen_awareness", ctx, True)))
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


def _web_evidence_station(ctx: dict[str, Any]) -> dict[str, Any]:
    parameters = ctx["parameters"]
    bundle = parameters.get("evidence_bundle") if isinstance(parameters.get("evidence_bundle"), dict) else {}
    trace = parameters.get("trace") if isinstance(parameters.get("trace"), dict) else {}
    if not trace and isinstance(bundle.get("trace"), dict):
        trace = bundle.get("trace")
    pages = bundle.get("pages") if isinstance(bundle.get("pages"), list) else []
    page = pages[0] if pages and isinstance(pages[0], dict) else {}
    provider_chain = bundle.get("provider_chain") if isinstance(bundle.get("provider_chain"), list) else []
    provider = (
        _text(page.get("provider"))
        or _text(trace.get("selected_provider"))
        or next((_text(item) for item in provider_chain if _text(item)), "")
        or "provider"
    )
    status = _text(page.get("status")) or _text(bundle.get("result_state")) or ctx["result_state"]
    text_chars = _text(page.get("text_chars")) or _text(bundle.get("text_chars")) or "0"
    links = _text(page.get("link_count")) or _text(bundle.get("link_count")) or "0"
    elapsed = _text(page.get("elapsed_ms"))
    title = _text(page.get("title"))
    load_state = _text(page.get("load_state"))
    network = page.get("network_summary") if isinstance(page.get("network_summary"), dict) else {}
    console = page.get("console_summary") if isinstance(page.get("console_summary"), dict) else {}
    network_requests = _text(network.get("request_count"))
    network_failures = _text(network.get("failed_count"))
    console_errors = _text(console.get("error_count"))
    cdp = trace.get("cdp") if isinstance(trace.get("cdp"), dict) else {}
    compatibility_level = _text(cdp.get("protocol_compatibility_level"))
    endpoint_status = _text(cdp.get("endpoint_status"))
    protocol_version = _text(cdp.get("protocol_version"))
    optional_domains = cdp.get("optional_domains") if isinstance(cdp.get("optional_domains"), dict) else {}
    optional_domain_label = ", ".join(
        f"{_title(_text(key))}: {_title(_text(value))}"
        for key, value in optional_domains.items()
        if _text(key) and _text(value)
    )
    startup_error = _text(cdp.get("last_startup_error_code"))
    cleanup_status = _text(cdp.get("last_cleanup_status"))
    cdp_navigation_supported = cdp.get("navigation_supported")
    cdp_navigation_label = ""
    if cdp.get("diagnostic_only") is True or cdp_navigation_supported is False:
        cdp_navigation_label = "unsupported"
    elif cdp_navigation_supported is True:
        cdp_navigation_label = "supported"
    fallback_provider = _text(cdp.get("recommended_fallback_provider")) or _text(page.get("fallback_provider"))
    claim_ceiling = _text(bundle.get("claim_ceiling")) or _text(trace.get("claim_ceiling")) or "rendered_page_evidence"
    fallback_used = bool(bundle.get("fallback_used") or trace.get("fallback_used"))
    fallback_reason = _text(trace.get("fallback_reason"))
    fallback_outcome = _text(trace.get("fallback_outcome"))
    attempted = trace.get("attempted_providers") if isinstance(trace.get("attempted_providers"), list) else provider_chain
    attempted_label = ", ".join(_title(_text(item)) for item in attempted if _text(item))
    limitation_values: list[str] = []
    for source in (bundle.get("limitations"), page.get("limitations")):
        if isinstance(source, list):
            limitation_values.extend(_text(item) for item in source if _text(item))
    limitation_detail = "Public page evidence only. I did not verify the source's claims independently, and this is not the user's visible screen."
    if limitation_values:
        limitation_detail = f"{limitation_detail} " + ", ".join(_web_limit_label(item) for item in limitation_values[:4])
    link_preview: list[str] = []
    raw_links = page.get("links") if isinstance(page.get("links"), list) else []
    for link in raw_links:
        if isinstance(link, dict):
            label = _text(link.get("text")) or _text(link.get("url"))
            if label:
                link_preview.append(label)
    return _station(
        "web_retrieval",
        ctx,
        chips=[
            _chip("Provider", _title(provider)),
            _chip("State", _title(status), _tone(ctx["result_state"])),
            _chip("Claim", _title(claim_ceiling)),
        ],
        sections=[
            _section(
                "Rendered Page Evidence",
                [
                    _entry("URL", _text(page.get("final_url")) or _text(page.get("requested_url")) or ctx["subject"]),
                    _entry("Provider", _title(provider)),
                    _entry("Status", _title(status)),
                    _entry("Title", title),
                    _entry("Load State", _title(load_state)),
                    _entry("Text", text_chars, "characters extracted"),
                    _entry("Links", links, ", ".join(link_preview[:3])),
                    _entry(
                        "Network",
                        f"{network_requests} requests" if network_requests else "",
                        f"{network_failures} failed" if network_failures else "",
                    ),
                    _entry("Console", f"{console_errors} errors" if console_errors else ""),
                    *(
                        [
                            _entry(
                                "CDP Compatibility",
                                _title(compatibility_level),
                                f"Endpoint: {_title(endpoint_status)}" if endpoint_status else "",
                            ),
                            _entry("Protocol", protocol_version, optional_domain_label),
                            _entry("CDP Navigation", _title(cdp_navigation_label)),
                            _entry("Recommended Fallback", _title(fallback_provider)),
                            _entry("CDP Cleanup", _title(cleanup_status), f"Startup: {_title(startup_error)}" if startup_error else ""),
                        ]
                        if provider == "obscura_cdp" or compatibility_level or endpoint_status
                        else []
                    ),
                    _entry("Elapsed", f"{elapsed} ms" if elapsed else ""),
                    _entry("Attempted Providers", attempted_label),
                    _entry("Fallback", "Used" if fallback_used else "No", f"{fallback_reason} -> {fallback_outcome}" if fallback_used else ""),
                    _entry("Claim Ceiling", _title(claim_ceiling)),
                    _entry("Limitations", "Public page evidence", limitation_detail),
                ],
            )
        ],
        invalidations=[],
        actions=_station_actions("web_retrieval", ctx, False),
    )


def _playwright_browser_adapter_entries(screen: dict[str, Any]) -> list[dict[str, str]]:
    adapters = _mapping(screen.get("browser_adapters"))
    playwright = _mapping(adapters.get("playwright"))
    if not playwright:
        return []
    observation = _mapping(playwright.get("last_observation_summary"))
    grounding = _mapping(playwright.get("last_grounding_summary"))
    verification = _mapping(playwright.get("last_verification_summary"))
    action_preview = _mapping(playwright.get("last_action_preview_summary"))
    action_execution = _mapping(playwright.get("last_action_execution_summary"))
    status = _text(playwright.get("playwright_adapter_status")) or _text(playwright.get("status")) or "unavailable"
    entries = [
        _entry(
            "Browser Adapter",
            _title(status),
            "Playwright semantic observation is owned by Screen Awareness.",
        )
    ]
    if observation:
        control_count = int(observation.get("control_count") or 0)
        dialog_count = int(observation.get("dialog_count") or 0)
        form_count = int(observation.get("form_count") or 0)
        provider = _text(observation.get("provider"))
        observation_label = "Live Observation" if provider == "playwright_live_semantic" else "Mock Observation"
        detail_parts = []
        title = _text(observation.get("page_title"))
        if title:
            detail_parts.append(title)
        context_kind = _text(observation.get("browser_context_kind"))
        if context_kind:
            detail_parts.append(_title(context_kind))
        if form_count:
            detail_parts.append(f"{form_count} form")
        if dialog_count:
            detail_parts.append(f"{dialog_count} dialog")
        entries.append(
            _entry(
                observation_label,
                f"{control_count} controls",
                ". ".join(detail_parts),
            )
        )
        form_summary = _mapping(observation.get("form_summary"))
        if form_summary:
            summary_form_count = int(form_summary.get("form_count") or form_count or 0)
            required_count = int(form_summary.get("required_field_count") or 0)
            disabled_count = int(form_summary.get("disabled_control_count") or 0)
            warning_count = int(form_summary.get("warning_count") or 0)
            detail = "; ".join(
                part
                for part in [
                    f"{required_count} required" if required_count else "",
                    f"{disabled_count} disabled" if disabled_count else "",
                    f"{warning_count} warning" if warning_count else "",
                    "form-like inferred" if form_summary.get("form_like_structure_inferred") else "",
                ]
                if part
            )
            entries.append(
                _entry(
                    "Form Summary",
                    f"{summary_form_count} {'form' if summary_form_count == 1 else 'forms'}",
                    detail,
                )
            )
        limitations = observation.get("limitations") if isinstance(observation.get("limitations"), list) else []
        if limitations:
            labels = [_title(_text(item)) for item in limitations[:3] if _text(item)]
            entries.append(
                _entry(
                    "Limitations",
                    labels[0] if labels else "Bounded",
                    "; ".join(labels[1:]) if len(labels) > 1 else "Bounded semantic observation only.",
                )
            )
    if grounding:
        count = int(grounding.get("candidate_count") or 0)
        top_candidates = grounding.get("top_candidates") if isinstance(grounding.get("top_candidates"), list) else []
        candidate_detail = _title(_text(grounding.get("status")))
        if top_candidates:
            labels = []
            for item in top_candidates[:3]:
                if isinstance(item, dict):
                    name = _text(item.get("name")) or _text(item.get("control_id"))
                    confidence = item.get("confidence")
                    evidence = item.get("evidence_terms") if isinstance(item.get("evidence_terms"), list) else []
                    evidence_label = ", ".join(_title(_text(term)) for term in evidence[:2] if _text(term))
                    confidence_label = f"{float(confidence):.2f}" if isinstance(confidence, (int, float)) else ""
                    bits = " / ".join(part for part in [confidence_label, evidence_label] if part)
                    labels.append(f"{name} ({bits})" if bits else name)
            if labels:
                candidate_detail = "; ".join(labels)
        entries.append(
            _entry(
                "Grounding",
                f"{count} {'candidate' if count == 1 else 'candidates'}",
                candidate_detail,
            )
        )
    if verification:
        change_count = int(verification.get("change_count") or 0)
        verification_status = _title(_text(verification.get("status")))
        detail_parts = []
        summary = _text(verification.get("summary"))
        if summary:
            detail_parts.append(summary)
        confidence = verification.get("confidence")
        if isinstance(confidence, (int, float)):
            detail_parts.append(f"confidence {float(confidence):.2f}")
        evidence = verification.get("expected_change_evidence") if isinstance(verification.get("expected_change_evidence"), list) else []
        if evidence:
            detail_parts.append(", ".join(_title(_text(item)) for item in evidence[:3] if _text(item)))
        entries.append(
            _entry(
                "Semantic Comparison",
                verification_status or f"{change_count} changes",
                "; ".join(detail_parts) or f"{change_count} bounded changes",
            )
        )
        top_changes = verification.get("top_changes") if isinstance(verification.get("top_changes"), list) else []
        if top_changes:
            change_labels = []
            for item in top_changes[:3]:
                if isinstance(item, dict):
                    change_labels.append(_title(_text(item.get("change_type"))))
            entries.append(
                _entry(
                    "Change Evidence",
                    f"{change_count} {'change' if change_count == 1 else 'changes'}",
                    "; ".join(label for label in change_labels if label),
                )
            )
    if action_preview:
        action_kind = _title(_text(action_preview.get("action_kind")) or "Preview")
        preview_state = _title(_text(action_preview.get("preview_state")) or _text(action_preview.get("result_state")) or "Preview Only")
        risk_level = _title(_text(action_preview.get("risk_level")) or "Medium")
        executable = "Yes" if action_preview.get("executable_now") is True else "No"
        target = _text(action_preview.get("target_name")) or _text(action_preview.get("target_phrase")) or "browser target"
        entries.append(
            _entry(
                "Action Preview",
                preview_state,
                f"{action_kind} target: {target}. Execution is not enabled.",
            )
        )
        entries.append(
            _entry(
                "Future Trust",
                f"Risk: {risk_level}",
                f"Approval required; executable now: {executable}",
            )
        )
        expected = action_preview.get("expected_outcome") if isinstance(action_preview.get("expected_outcome"), list) else []
        if expected:
            entries.append(
                _entry(
                    "Future Check",
                    _title(_text(expected[0])),
                    "; ".join(_title(_text(item)) for item in expected[1:3] if _text(item)),
                )
            )
    if action_execution:
        execution_status = _title(_text(action_execution.get("status")) or "Unknown")
        action_kind = _title(_text(action_execution.get("action_kind")) or "Action")
        verification_status = _title(_text(action_execution.get("verification_status")) or "Not Conclusive")
        cleanup_status = _title(_text(action_execution.get("cleanup_status")) or "Not Started")
        target = _mapping(action_execution.get("target_summary"))
        target_name = _text(target.get("name")) or _text(target.get("label")) or _text(action_execution.get("target_name")) or "browser target"
        entries.append(
            _entry(
                "Action Execution",
                execution_status,
                f"{action_kind} target: {target_name}. Verification: {verification_status}. Cleanup: {cleanup_status}.",
            )
        )
        if _text(action_execution.get("before_observation_id")) or _text(action_execution.get("after_observation_id")):
            entries.append(
                _entry(
                    "Execution Evidence",
                    _title(_text(action_execution.get("claim_ceiling")) or "browser_semantic_action_execution"),
                    f"Before: {_text(action_execution.get('before_observation_id'))}; after: {_text(action_execution.get('after_observation_id'))}",
                )
            )
    claim = _text(playwright.get("claim_ceiling")) or _text(observation.get("claim_ceiling"))
    claim = _text(verification.get("claim_ceiling")) or claim
    claim = _text(action_preview.get("claim_ceiling")) or claim
    claim = _text(action_execution.get("claim_ceiling")) or claim
    if claim:
        entries.append(_entry("Claim Ceiling", _title(claim), "Not visible-screen or source-truth proof."))
    return entries


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
    labels = {"web_retrieval": "Show Evidence", "trust": "Show Trust", "task_continuity": "Show Continuity", "watch_runtime": "Show Runtime", "memory": "Show Memory"}
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
    provider = _mapping(parameters.get("provider_fallback"))
    if provider:
        provider_state = _text(provider.get("state")) or _text(parameters.get("result_state"))
        if provider_state:
            entries.append({"label": "Provider State", "value": _title(provider_state)})
        if _text(provider.get("provider_budget_label")):
            entries.append({"label": "Provider Budget", "value": _text(provider.get("provider_budget_label"))})
        if provider.get("first_output_ms") is not None:
            entries.append({"label": "First Output", "value": _ms_text(provider.get("first_output_ms"))})
        if provider.get("total_provider_ms") is not None and _number(provider.get("total_provider_ms")) > 0:
            entries.append({"label": "Provider Total", "value": _ms_text(provider.get("total_provider_ms"))})
        if provider.get("streaming_used") is not None:
            entries.append({"label": "Provider Streaming", "value": "Used" if provider.get("streaming_used") else "Not used"})
        if _text(provider.get("fallback_reason")):
            entries.append({"label": "Fallback Reason", "value": _text(provider.get("fallback_reason"))})
        if _text(provider.get("failure_code")):
            entries.append({"label": "Provider Failure", "value": _text(provider.get("failure_code"))})
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
    screen_state = _screen_awareness_state(
        {
            "phase": screen.get("phase"),
            "policy": policy,
            "trace": {
                "durationMs": latest_trace.get("total_duration_ms"),
                "summary": policy.get("summary"),
            },
            "browser_adapters": screen.get("browser_adapters") if isinstance(screen.get("browser_adapters"), dict) else {},
        }
    )
    return {
        "present": bool(active_jobs or queued_jobs or recent_failures or _text(bootstrap.get("lifecycle_hold_reason")) or screen),
        "headline": "Degraded" if recent_failures else "Live",
        "tone": "warning" if recent_failures else "steady",
        "watch": {"present": bool(active_jobs or queued_jobs or recent_failures or _text(watch.get("health")) or _text(watch.get("current_tool"))), "health": _title(_text(watch.get("health")) or ("degraded" if recent_failures else "steady")), "queue": f"{active_jobs} active / {queued_jobs} queued", "failures": str(recent_failures), "tool": _title(_text(watch.get("current_tool")) or "Not reported")},
        "lifecycle": {"present": bool(_text(bootstrap.get("lifecycle_hold_reason")) or _text(cleanup.get("operator_summary"))), "state": _title(_text(bootstrap.get("state")) or "steady"), "hold": _text(bootstrap.get("lifecycle_hold_reason")) or "No lifecycle hold", "cleanup": _text(cleanup.get("operator_summary"))},
        "screenAwareness": {"phase": _title(_text(screen_state.get("phase"))), "policy": screen_state["policy"], "trace": screen_state["trace"], "browser_adapters": screen_state["browser_adapters"]},
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
    if raw in {"extracted", "partial", "fallback_available", "fallback_used", "provider_unavailable", "provider_running", "provider_cancelled", "timeout", "unsupported", "blocked", "failed"}:
        return raw
    if raw in {"attempted", "completed", "dispatch", "dispatched"}:
        return "attempted"
    if raw in {"uncertain", "unknown"}:
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


def _web_limit_label(value: str) -> str:
    key = _text(value).lower()
    labels = {
        "not_truth_verified": "No independent truth check",
        "not_user_visible_screen": "Not the visible screen",
        "no_user_visible_screen_claim": "No visible-screen claim",
    }
    return labels.get(key, _title(value))


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
