from __future__ import annotations

import json

import pytest

from stormhelm.core.orchestrator.planner_v2 import PlannerV2

from test_assistant_orchestrator import FakeSystemProbe
from test_assistant_orchestrator import _build_assistant_with_workspace


def test_command_eval_compact_trace_uses_refs_for_duplicate_context_state(temp_config) -> None:
    assistant, _, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        request_state = {
            "family": "software_control",
            "context_freshness": "current",
            "context_reusable": True,
            "subject": "Example App",
            "parameters": {"tool_name": "repair_action", "target_name": "Example App"},
        }
        payload = {
            "session_id": "default",
            "user_message": {"role": "user", "content": "can you handle this?", "metadata": {}},
            "assistant_message": {
                "role": "assistant",
                "content": "Prepared a dry-run plan.",
                "metadata": {
                    "route_state": {"winner": {"route_family": "software_control", "subsystem": "software"}},
                    "route_handler_subspans": {"dry_run_plan_ms": 1.0},
                    "stage_timings_ms": {"route_handler_ms": 1.0},
                    "planner_debug": {
                        "routing_engine": "planner_v2",
                        "route_family": "software_control",
                        "subsystem": "software",
                        "tool_chain": ["repair_action"],
                        "planner_v2": {
                            "authoritative": True,
                            "context_binding": {
                                "context_reference": "this",
                                "context_type": "software",
                                "context_source": "active_request_state",
                                "status": "available",
                                "value": {"active_request_state": dict(request_state)},
                            },
                            "route_decision": {
                                "selected_route_spec": "software_control",
                                "candidate_specs_considered": [
                                    {"route_family": f"family_{index}", "subsystem": "test"}
                                    for index in range(12)
                                ],
                            },
                            "capability_specs": [
                                {"route_family": f"family_{index}", "subsystem": "test"}
                                for index in range(30)
                            ],
                        },
                    },
                },
            },
            "jobs": [],
            "actions": [],
            "active_request_state": request_state,
            "recent_context_resolutions": [],
            "active_task": {},
        }

        compact = assistant._apply_response_profile(
            payload,
            profile="command_eval_compact",
            reason="unit_test",
        )
        assistant._attach_stage_timings_to_response(compact, {"route_handler_ms": 1.0, "context_cache_hits": 1.0})
    finally:
        executor.shutdown()

    planner_debug = compact["assistant_message"]["metadata"]["planner_debug"]
    context_binding = planner_debug["planner_v2"]["context_binding"]
    assert compact["active_request_state"]["family"] == "software_control"
    assert context_binding["active_request_state_ref"] == "payload.active_request_state"
    assert "value" not in context_binding
    assert planner_debug["stage_timings_ref"] == "assistant_message.metadata.stage_timings_ms"
    assert "stage_timings_ms" not in planner_debug
    route_decision = planner_debug["planner_v2"]["route_decision"]
    assert len(route_decision["candidate_specs_considered"]) <= 2
    assert planner_debug["planner_v2"]["capability_specs_summary"]["total_count"] == 30


def test_turn_context_snapshot_uses_local_memory_without_cross_session_leak(temp_config, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, executor, session_state, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        session_state.set_active_request_state(
            "session-a",
            {"family": "browser_destination", "subject": "Stormhelm docs", "context_freshness": "current"},
        )
        session_state.remember_context_resolution(
            "session-a",
            {"kind": "browser_destination", "summary": "Stormhelm docs"},
        )

        monkeypatch.setattr(
            session_state.memory,
            "list_recent_session_tool_results",
            lambda *args, **kwargs: pytest.fail("compact eval snapshot should use local tool-result memory"),
        )
        monkeypatch.setattr(
            session_state.memory,
            "list_recent_context_resolutions",
            lambda *args, **kwargs: pytest.fail("compact eval snapshot should use local context memory"),
        )
        monkeypatch.setattr(
            session_state.memory,
            "get_learned_preferences",
            lambda *args, **kwargs: pytest.fail("compact eval snapshot should use local preference memory"),
        )

        session_a = session_state.get_turn_context_snapshot("session-a", prefer_local_memory=True)
        session_b = session_state.get_turn_context_snapshot("session-b", prefer_local_memory=True)
    finally:
        executor.shutdown()

    assert session_a["active_request_state"]["family"] == "browser_destination"
    assert session_a["recent_context_resolutions"][0]["kind"] == "browser_destination"
    assert session_b["active_request_state"] == {}
    assert session_b["recent_context_resolutions"] == []


def test_compact_workspace_summary_caps_previews_and_preserves_truth_fields(temp_config) -> None:
    _, _, executor, session_state, workspace_service = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        references = [
            {"itemId": f"ref-{index}", "title": f"Reference {index}", "summary": "Deck detail " * 20}
            for index in range(12)
        ]
        workspace = workspace_service.repository.upsert_workspace(
            name="Compact Workspace",
            topic="latency runtime pass 3",
            summary="Compact summary truth.",
            references=references,
        )
        session_state.set_active_workspace_id("default", workspace.workspace_id)
        session_state.set_active_posture(
            "default",
            {
                "workspace": workspace.to_dict(),
                "opened_items": references[:6],
                "references": references,
                "pending_next_steps": ["Preserve truth.", "Defer detail."],
                "where_left_off": "Ready for the next latency pass.",
            },
        )

        summary = workspace_service.active_workspace_summary_compact("default")
    finally:
        executor.shutdown()

    workspace_payload = summary["workspace"]
    assert workspace_payload["detailLoadDeferred"] is True
    assert workspace_payload["workspaceSummaryCompact"]["referenceCount"] == 12
    assert summary["openedItemsSummary"]["displayed_count"] <= 2
    assert summary["referencesSummary"]["displayed_count"] == 0
    assert "surfaceContent" not in workspace_payload
    assert workspace_payload["whereLeftOff"] == "Ready for the next latency pass."


def test_compact_workspace_where_left_off_and_next_steps_do_not_load_memory_detail(
    temp_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, executor, session_state, workspace_service = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        workspace = workspace_service.repository.upsert_workspace(
            name="Deferred Detail Workspace",
            topic="workspace detail squeeze",
            summary="Compact paths should stay summary-first.",
            pending_next_steps=["Check the compact summary."],
        )
        session_state.set_active_workspace_id("default", workspace.workspace_id)
        session_state.set_active_posture("default", {"workspace": workspace.to_dict()})
        monkeypatch.setattr(
            workspace_service,
            "_workspace_memory_context",
            lambda *args, **kwargs: pytest.fail("compact workspace status loaded memory detail"),
        )

        left_off = workspace_service.where_we_left_off(session_id="default", compact=True)
        next_steps = workspace_service.next_steps(session_id="default", compact=True)
    finally:
        executor.shutdown()

    assert left_off["detail_load_deferred"] is True
    assert left_off["workspace"]["detailLoadDeferred"] is True
    assert next_steps["detail_load_deferred"] is True
    assert next_steps["workspace"]["detailLoadDeferred"] is True


def test_context_binding_canaries_stay_native_after_pass3_compaction() -> None:
    planner = PlannerV2()

    no_context = planner.plan("can you handle this?")
    correction = planner.plan(
        "no, use the other one",
        active_request_state={
            "family": "browser_destination",
            "subject": "YouTube",
            "parameters": {
                "tool_name": "external_open_url",
                "previous_choice": "YouTube",
                "alternate_target": "Stormhelm docs",
                "context_freshness": "current",
            },
        },
    )
    confirmation = planner.plan(
        "yes, go ahead",
        active_request_state={
            "family": "discord_relay",
            "subject": "preview",
            "parameters": {
                "tool_name": "discord_relay_preview",
                "pending_preview": {"id": "preview-discord-1", "status": "pending"},
                "context_freshness": "current",
            },
        },
    )

    assert no_context.route_decision.selected_route_family == "context_clarification"
    assert no_context.route_decision.generic_provider_allowed is False
    assert correction.route_decision.selected_route_family == "browser_destination"
    assert correction.route_decision.generic_provider_allowed is False
    assert confirmation.route_decision.selected_route_family == "discord_relay"
    assert confirmation.route_decision.generic_provider_allowed is False
