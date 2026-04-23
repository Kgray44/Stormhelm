from __future__ import annotations

from typing import Any


ROUTE_FAMILIES = [
    "native_deterministic",
    "native_orchestration",
    "adapter_backed",
    "observational",
    "preview_and_confirm",
    "recovery",
    "ui_only",
]
RESULT_STATES = [
    "requested",
    "planned",
    "pending_approval",
    "executing",
    "completed",
    "verified",
    "failed",
    "blocked",
    "stale",
    "unknown",
]


def build_bridge_authority_snapshot(
    *,
    calculations: dict[str, object] | None = None,
    software_control: dict[str, object] | None = None,
    software_recovery: dict[str, object] | None = None,
    screen_awareness: dict[str, object] | None = None,
    discord_relay: dict[str, object] | None = None,
    trust: dict[str, object] | None = None,
    provider_state: dict[str, object] | None = None,
    tool_state: dict[str, object] | None = None,
    watch_state: dict[str, object] | None = None,
    active_task: dict[str, object] | None = None,
    memory: dict[str, object] | None = None,
    event_stream: dict[str, object] | None = None,
    lifecycle: dict[str, object] | None = None,
    system_state: dict[str, object] | None = None,
    systems_interpretation: dict[str, object] | None = None,
    jobs: list[dict[str, object]] | None = None,
    active_workspace: dict[str, object] | None = None,
) -> dict[str, object]:
    del provider_state, watch_state, event_stream, jobs, active_workspace
    families = [
        _trust_family(_as_dict(trust)),
        _tasks_family(_as_dict(active_task)),
        _lifecycle_family(_as_dict(lifecycle)),
        _relay_family(_as_dict(discord_relay)),
        _software_family(_as_dict(software_control), _as_dict(software_recovery)),
        _adapters_family(_as_dict(tool_state)),
        _memory_family(_as_dict(memory)),
        _systems_family(_as_dict(system_state), _as_dict(systems_interpretation), _as_dict(screen_awareness), _as_dict(calculations)),
    ]
    gap_register = [
        {
            "familyId": family["familyId"],
            "severity": family["status"],
            "summary": family.get("degradedReason") or family.get("summary") or "Authority is degraded.",
        }
        for family in families
        if family.get("status") in {"degraded", "blocked", "stale"}
    ]
    ghost_cards = _ghost_cards(families, _as_dict(trust), _as_dict(active_task), _as_dict(lifecycle))
    deck_sections = _deck_sections(families, gap_register)
    summary = {
        "mappedFamilyCount": len(families),
        "commandableFamilyCount": _count_authority(families, "commandAuthority"),
        "inspectableFamilyCount": _count_authority(families, "inspectAuthority"),
        "previewableFamilyCount": _count_authority(families, "previewAuthority"),
        "degradedFamilyCount": sum(1 for family in families if family.get("status") in {"degraded", "blocked", "stale", "pending_approval"}),
        "blockedFamilyCount": sum(1 for family in families if family.get("status") == "blocked"),
        "bridgeReadiness": "partial" if gap_register else "ready",
    }
    return {
        "schema": "stormhelm.bridge_authority.v1",
        "summary": summary,
        "routeFamilies": list(ROUTE_FAMILIES),
        "resultStates": list(RESULT_STATES),
        "families": families,
        "familiesById": {str(family["familyId"]): family for family in families},
        "ghostCards": ghost_cards,
        "deckSections": deck_sections,
        "gapRegister": gap_register,
    }


def _trust_family(trust: dict[str, object]) -> dict[str, object]:
    pending = _int(trust.get("pending_request_count"))
    state = "pending_approval" if pending else "verified"
    return _family(
        family_id="trust",
        label="Trust",
        owner_family="trust",
        route_family="preview_and_confirm",
        status=state,
        result_state=state,
        command_authority="limited",
        inspect_authority="available",
        preview_authority="available",
        summary=(
            f"{pending} trust decision is waiting for operator confirmation."
            if pending == 1
            else f"{pending} trust decisions are waiting for operator confirmation."
            if pending
            else "Trust approvals and grants are available for inspection."
        ),
        supported_commands=["approval.review_via_chat", "approval.respond"],
    )


def _tasks_family(active_task: dict[str, object]) -> dict[str, object]:
    continuity = _as_dict(active_task.get("continuity"))
    state = str(continuity.get("resumeStatus") or active_task.get("state") or "unknown").strip() or "unknown"
    has_task = bool(active_task)
    return _family(
        family_id="tasks",
        label="Tasks",
        owner_family="tasks",
        route_family="native_orchestration",
        status="ready" if state not in {"stale", "blocked", "failed"} else state,
        result_state=_normalize_result_state(state),
        command_authority="available" if has_task else "limited",
        inspect_authority="available",
        preview_authority="available" if has_task else "limited",
        summary=str(active_task.get("title") or continuity.get("summary") or "Durable task continuity is available."),
        supported_commands=(
            ["task.resume", "task.next_steps", "task.where_left_off"]
            if has_task
            else ["task.inspect_recent", "task.where_left_off"]
        ),
    )


def _lifecycle_family(lifecycle: dict[str, object]) -> dict[str, object]:
    bootstrap = _as_dict(lifecycle.get("bootstrap"))
    hold_reason = str(bootstrap.get("lifecycle_hold_reason") or "").strip()
    return _family(
        family_id="lifecycle",
        label="Lifecycle",
        owner_family="lifecycle",
        route_family="recovery",
        status="blocked" if hold_reason else "ready",
        result_state="blocked" if hold_reason else "verified",
        command_authority="available",
        inspect_authority="available",
        preview_authority="available",
        summary=hold_reason or "Lifecycle posture and recovery plans are backend-owned.",
        supported_commands=["lifecycle.inspect", "lifecycle.resolve", "lifecycle.uninstall_preview"],
    )


def _relay_family(discord_relay: dict[str, object]) -> dict[str, object]:
    enabled = _bool(discord_relay.get("enabled"))
    preview_enabled = _bool(discord_relay.get("preview_before_send"))
    return _family(
        family_id="relay",
        label="Relay",
        owner_family="relay",
        route_family="preview_and_confirm",
        status="ready" if enabled else "blocked",
        result_state=_normalize_result_state(_as_dict(discord_relay.get("last_trace")).get("state") or "planned"),
        command_authority="available" if enabled else "unavailable",
        inspect_authority="available",
        preview_authority="available" if enabled and preview_enabled else "limited" if enabled else "unavailable",
        summary="Relay dispatches use preview and verification before send.",
        supported_commands=["relay.preview", "relay.confirm_send"],
    )


def _software_family(software: dict[str, object], recovery: dict[str, object]) -> dict[str, object]:
    enabled = _bool(software.get("enabled"))
    result = _normalize_result_state(_as_dict(software.get("last_trace")).get("execution_status") or "planned")
    return _family(
        family_id="software",
        label="Software",
        owner_family="software",
        route_family="native_orchestration",
        status="ready" if enabled else "blocked",
        result_state=result if enabled else "blocked",
        command_authority="available" if enabled else "unavailable",
        inspect_authority="available",
        preview_authority="available" if enabled else "unavailable",
        display_only_zone="none",
        command_scope="backend_orchestrated",
        summary=(
            "Software plans, verification, and recovery are backend-owned."
            if recovery
            else "Software plans and verification are backend-owned."
        ),
        supported_commands=["software.plan", "software.execute", "software.verify"] if enabled else ["software.inspect"],
    )


def _adapters_family(tool_state: dict[str, object]) -> dict[str, object]:
    failures = _int(tool_state.get("adapter_contract_validation_failures"))
    contract_count = _int(tool_state.get("adapter_contract_count"))
    healthy_count = _int(tool_state.get("healthy_adapter_contract_count"))
    degraded = failures > 0 or (contract_count and healthy_count < contract_count)
    return _family(
        family_id="adapters",
        label="Adapters",
        owner_family="adapters",
        route_family="adapter_backed",
        status="degraded" if degraded else "ready" if contract_count else "not_reported",
        result_state="blocked" if degraded else "verified" if contract_count else "unknown",
        command_authority="limited" if contract_count else "unavailable",
        inspect_authority="available",
        preview_authority="limited" if degraded else "available" if contract_count else "unavailable",
        degraded_reason=(
            f"Adapter contract validation is degraded: {failures} validation failure(s)."
            if degraded
            else ""
        ),
        blockers=["adapter_contract_validation"] if degraded else [],
        summary="Adapter contracts are visible with downgrade truth.",
        supported_commands=["adapter.inspect"] if contract_count else [],
    )


def _memory_family(memory: dict[str, object]) -> dict[str, object]:
    families = _as_dict(memory.get("families"))
    count = sum(_int(value) for value in families.values())
    return _family(
        family_id="memory",
        label="Memory",
        owner_family="memory",
        route_family="native_orchestration",
        status="ready" if memory else "not_reported",
        result_state="verified" if count else "unknown",
        command_authority="limited",
        inspect_authority="available",
        preview_authority="available" if memory else "unavailable",
        summary=f"Memory has {count} indexed family record(s)." if count else "Memory authority is available for inspection.",
        supported_commands=["memory.inspect", "memory.recall"],
    )


def _systems_family(
    system_state: dict[str, object],
    systems_interpretation: dict[str, object],
    screen_awareness: dict[str, object],
    calculations: dict[str, object],
) -> dict[str, object]:
    del calculations, screen_awareness
    summary = str(
        systems_interpretation.get("summary")
        or systems_interpretation.get("headline")
        or "Systems exposes telemetry truth but does not pretend to control hardware."
    )
    return _family(
        family_id="systems",
        label="Systems State",
        owner_family="systems",
        route_family="observational",
        status="ready" if system_state else "not_reported",
        result_state="verified" if system_state else "unknown",
        command_authority="unavailable",
        inspect_authority="available",
        preview_authority="unavailable",
        display_only_zone="presentation_only",
        summary=summary,
        supported_commands=[],
    )


def _family(
    *,
    family_id: str,
    label: str,
    owner_family: str,
    route_family: str,
    status: str,
    result_state: str,
    command_authority: str,
    inspect_authority: str,
    preview_authority: str,
    summary: str,
    supported_commands: list[str],
    display_only_zone: str = "none",
    command_scope: str = "",
    degraded_reason: str = "",
    blockers: list[str] | None = None,
) -> dict[str, object]:
    has_commands = bool(supported_commands)
    preview_supported = preview_authority in {"available", "limited"}
    payload: dict[str, object] = {
        "familyId": family_id,
        "label": label,
        "ownerFamily": owner_family,
        "participants": [],
        "routeFamily": route_family,
        "status": status,
        "resultState": result_state,
        "commandAuthority": command_authority,
        "inspectAuthority": inspect_authority,
        "previewAuthority": preview_authority,
        "displayOnlyZone": display_only_zone,
        "verificationPosture": "backend_owned",
        "freshnessPosture": "snapshot",
        "approvalPosture": "policy_dependent",
        "summary": summary,
        "blockers": list(blockers or []),
        "degradedReason": degraded_reason,
        "nextActionCandidates": [],
        "supportedCommands": list(supported_commands),
        "requiresApproval": command_authority in {"available", "limited"} and family_id in {"trust", "relay", "software", "lifecycle"},
        "destructiveRisk": "high" if family_id == "lifecycle" else "medium" if family_id in {"software", "relay"} else "none",
        "previewSupported": preview_supported,
        "retrySupported": family_id in {"tasks", "software", "lifecycle", "relay"},
        "cancellable": family_id in {"tasks", "relay", "lifecycle"},
        "commandScope": command_scope or ("backend_orchestrated" if has_commands else "none"),
        "expectedVerificationStrength": "result_state" if has_commands else "none",
        "previewState": preview_authority if preview_supported else "unavailable",
        "previewSummary": summary if preview_supported else "",
        "previewArtifacts": [],
        "previewProvenance": [family_id],
        "previewWarnings": list(blockers or []),
        "confirmationBindingState": "required" if family_id in {"trust", "relay", "lifecycle"} else "not_required",
        "detailState": inspect_authority,
        "history": [],
        "auditOrTraceRefs": [],
        "suppressionReasons": [],
        "fallbackReason": "",
    }
    return payload


def _ghost_cards(
    families: list[dict[str, object]],
    trust: dict[str, object],
    active_task: dict[str, object],
    lifecycle: dict[str, object],
) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    trust_card = _as_dict(trust.get("ghost_card"))
    if trust_card:
        trust_family = _by_family(families, "trust")
        cards.append(_card("trust", trust_card, trust_family))
    task_ghost = _as_dict(active_task.get("ghostSummary"))
    if task_ghost:
        cards.append(_card("tasks", task_ghost, _by_family(families, "tasks")))
    lifecycle_bootstrap = _as_dict(lifecycle.get("bootstrap"))
    hold_reason = str(lifecycle_bootstrap.get("lifecycle_hold_reason") or "").strip()
    if hold_reason:
        cards.append(
            _card(
                "lifecycle",
                {
                    "title": "Lifecycle Hold",
                    "subtitle": "Startup",
                    "body": hold_reason,
                },
                _by_family(families, "lifecycle"),
            )
        )
    if cards:
        return cards
    return [_card(str(family["familyId"]), {"title": family["label"], "body": family["summary"]}, family) for family in families[:3]]


def _card(family_id: str, card: dict[str, object], family: dict[str, object]) -> dict[str, object]:
    body = str(card.get("body") or card.get("summary") or family.get("summary") or "").strip()
    return {
        "familyId": family_id,
        "title": str(card.get("title") or family.get("label") or family_id).strip(),
        "subtitle": str(card.get("subtitle") or "").strip(),
        "body": body[:160],
        "routeFamily": str(family.get("routeFamily") or ""),
        "resultState": str(family.get("resultState") or "unknown"),
        "actions": list(card.get("actions") or []),
    }


def _deck_sections(families: list[dict[str, object]], gap_register: list[dict[str, object]]) -> list[dict[str, object]]:
    commandable = [
        family
        for family in families
        if family.get("commandAuthority") in {"available", "limited"}
    ]
    sections: list[dict[str, object]] = [
        {
            "title": "Commandable Families",
            "summary": "Real command lanes exposed by backend authority.",
            "entries": [
                {
                    "title": str(family.get("label") or family.get("familyId")),
                    "status": str(family.get("commandAuthority") or "unknown"),
                    "detail": ", ".join(str(command) for command in family.get("supportedCommands", [])),
                }
                for family in commandable
            ],
        },
        {
            "title": "Authority Map",
            "summary": "Backend ownership and display boundaries by family.",
            "entries": [
                {
                    "title": str(family.get("label") or family.get("familyId")),
                    "status": str(family.get("resultState") or "unknown"),
                    "detail": str(family.get("summary") or ""),
                }
                for family in families
            ],
        },
    ]
    if gap_register:
        sections.append(
            {
                "title": "Authority Gaps",
                "summary": "Families that must fail closed or downgrade.",
                "entries": [
                    {
                        "title": str(gap.get("familyId") or "unknown"),
                        "status": str(gap.get("severity") or "unknown"),
                        "detail": str(gap.get("summary") or ""),
                    }
                    for gap in gap_register
                ],
            }
        )
    return sections


def _by_family(families: list[dict[str, object]], family_id: str) -> dict[str, object]:
    return next((family for family in families if family.get("familyId") == family_id), {})


def _count_authority(families: list[dict[str, object]], key: str) -> int:
    return sum(1 for family in families if family.get(key) in {"available", "limited"})


def _normalize_result_state(value: object) -> str:
    normalized = str(value or "unknown").strip().lower()
    aliases = {
        "ready": "planned",
        "prepared": "planned",
        "preview_ready": "pending_approval",
        "awaiting_confirmation": "pending_approval",
        "confirmation_required": "pending_approval",
        "running": "executing",
        "in_progress": "executing",
        "success": "completed",
        "succeeded": "completed",
        "resumable": "planned",
        "verification": "verified",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in RESULT_STATES else "unknown"


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
