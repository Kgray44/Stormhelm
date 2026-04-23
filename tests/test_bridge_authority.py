from __future__ import annotations

from stormhelm.core.bridge_authority import build_bridge_authority_snapshot


def _families_by_id(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
    families = snapshot.get("families", [])
    assert isinstance(families, list)
    return {
        str(family.get("familyId")): family
        for family in families
        if isinstance(family, dict)
    }


def test_bridge_authority_maps_major_backend_families_to_truthful_contract() -> None:
    snapshot = build_bridge_authority_snapshot(
        calculations={
            "enabled": True,
            "planner_routing_enabled": True,
            "capabilities": {"direct_expression": True, "formula_helpers": True},
        },
        software_control={
            "enabled": True,
            "planner_routing_enabled": True,
            "package_manager_routes_enabled": True,
            "browser_guided_routes_enabled": True,
            "truthfulness_contract": {"verification_required_for_success": True},
            "last_trace": {"operation_type": "install", "execution_status": "planned"},
        },
        software_recovery={
            "enabled": True,
            "cloud_fallback_enabled": False,
            "capabilities": {"local_troubleshooting": True},
        },
        screen_awareness={
            "enabled": True,
            "phase": "phase3",
            "capabilities": {"observation_enabled": True, "action_enabled": False},
        },
        discord_relay={
            "enabled": True,
            "planner_routing_enabled": True,
            "preview_before_send": True,
            "verification_enabled": True,
            "truthfulness_contract": {"preview_fingerprint_binding": True},
            "last_trace": {"state": "preview_ready", "destination_alias": "kai"},
        },
        trust={
            "enabled": True,
            "pending_request_count": 1,
            "active_grant_count": 0,
            "recent_audit_count": 2,
            "ghost_card": {
                "title": "Approval Needed",
                "subtitle": "Install",
                "body": "Stormhelm needs confirmation before changing installed software.",
            },
            "deck_groups": [{"title": "Pending Approval", "entries": []}],
        },
        provider_state={"enabled": True, "configured": True},
        tool_state={
            "enabled_count": 9,
            "adapter_contract_count": 6,
            "healthy_adapter_contract_count": 6,
            "adapter_contract_validation_failures": 0,
            "adapter_families": ["browser", "settings", "workspace"],
            "contract_bound_tools": {"external_open_url": ["browser.external"]},
        },
        watch_state={"active_jobs": 1, "queued_jobs": 0, "recent_failures": 0},
        active_task={
            "taskId": "task-1",
            "title": "Package the portable build",
            "state": "blocked",
            "nextSteps": ["Verify package"],
            "ghostSummary": {
                "title": "Package the portable build",
                "subtitle": "Blocked",
                "body": "A verification artifact is missing.",
            },
            "continuity": {"resumeStatus": "stale", "summary": "Verification artifact is missing."},
        },
        memory={"families": {"task": 2, "workspace": 1}, "recentQueries": [{"query": "resume"}]},
        event_stream={"buffered": 5, "capacity": 128},
        lifecycle={
            "runtime": {"core_status": "held", "shell_status": "attached"},
            "bootstrap": {
                "lifecycle_hold_reason": "Migration needs operator review.",
                "resolution_plan": {"resolvable": True, "summary": "Re-run the migration safely."},
            },
            "uninstall_plan": {
                "destructive_cleanup_plan": {"operator_summary": "Deep cleanup requires confirmation."}
            },
        },
        system_state={"machine": {"machine_name": "Stormhelm-Test"}},
        systems_interpretation={"headline": "Machine steady", "summary": "Local probes are healthy."},
        jobs=[{"job_id": "job-1", "status": "running", "tool_name": "echo"}],
        active_workspace={
            "workspace": {"workspaceId": "ws-1", "name": "Release Workspace"},
            "opened_items": [{"itemId": "file-1"}],
        },
    )

    families = _families_by_id(snapshot)

    for family_id in {
        "trust",
        "tasks",
        "lifecycle",
        "relay",
        "software",
        "adapters",
        "memory",
        "systems",
    }:
        assert family_id in families

    assert families["trust"]["routeFamily"] == "preview_and_confirm"
    assert families["trust"]["resultState"] == "pending_approval"
    assert families["trust"]["previewAuthority"] == "available"
    assert families["tasks"]["resultState"] == "stale"
    assert families["lifecycle"]["commandAuthority"] == "available"
    assert families["relay"]["previewAuthority"] == "available"
    assert families["software"]["commandScope"] == "backend_orchestrated"
    assert families["systems"]["commandAuthority"] == "unavailable"

    summary = snapshot["summary"]
    assert isinstance(summary, dict)
    assert summary["mappedFamilyCount"] >= 8
    assert summary["commandableFamilyCount"] >= 4
    assert summary["previewableFamilyCount"] >= 4

    ghost_cards = snapshot["ghostCards"]
    assert isinstance(ghost_cards, list)
    assert ghost_cards[0]["familyId"] == "trust"
    assert ghost_cards[0]["title"] == "Approval Needed"
    assert len(ghost_cards[0]["body"]) <= 160

    deck_sections = snapshot["deckSections"]
    assert isinstance(deck_sections, list)
    assert any(section["title"] == "Commandable Families" for section in deck_sections)


def test_bridge_authority_fails_closed_when_adapter_contracts_are_degraded() -> None:
    snapshot = build_bridge_authority_snapshot(
        tool_state={
            "enabled_count": 4,
            "adapter_contract_count": 5,
            "healthy_adapter_contract_count": 3,
            "adapter_contract_validation_failures": 2,
            "adapter_families": ["browser", "settings"],
            "contract_bound_tools": {"external_open_url": ["browser.external"]},
        }
    )

    adapters = _families_by_id(snapshot)["adapters"]

    assert adapters["routeFamily"] == "adapter_backed"
    assert adapters["status"] == "degraded"
    assert adapters["commandAuthority"] == "limited"
    assert adapters["inspectAuthority"] == "available"
    assert "validation" in str(adapters["degradedReason"]).lower()
    assert adapters["blockers"]

    gap_register = snapshot["gapRegister"]
    assert isinstance(gap_register, list)
    assert any(
        isinstance(gap, dict)
        and gap.get("familyId") == "adapters"
        and gap.get("severity") == "degraded"
        for gap in gap_register
    )


def test_bridge_authority_exposes_shared_route_and_result_taxonomy() -> None:
    snapshot = build_bridge_authority_snapshot()

    assert snapshot["routeFamilies"] == [
        "native_deterministic",
        "native_orchestration",
        "adapter_backed",
        "observational",
        "preview_and_confirm",
        "recovery",
        "ui_only",
    ]
    assert snapshot["resultStates"] == [
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
