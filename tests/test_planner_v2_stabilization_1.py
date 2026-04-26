from __future__ import annotations

import pytest

from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2


@pytest.mark.parametrize(
    "prompt,legacy_family",
    [
        ("what is my battery at", "power"),
        ("what windows are open", "window_control"),
        ("what is the weather here", "weather"),
    ],
)
def test_planner_v2_defers_unmigrated_native_owners_instead_of_overcapturing(prompt: str, legacy_family: str) -> None:
    trace = PlannerV2().plan(prompt)

    assert trace.authoritative is False
    assert trace.route_decision.routing_engine == "legacy_planner"
    assert trace.route_decision.legacy_fallback_allowed is True
    assert trace.route_decision.legacy_family == legacy_family
    assert trace.route_decision.generic_provider_allowed is False
    assert "native_owner_not_migrated" in trace.route_decision.planner_v2_decline_reason


def test_deterministic_planner_reports_browser_context_under_context_subsystem() -> None:
    decision = DeterministicPlanner().plan(
        "what browser page am I on",
        session_id="planner-v2-stabilization",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state={},
        active_context={},
        recent_tool_results=[],
    )
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}

    assert decision.debug["routing_engine"] == "planner_v2"
    assert winner.get("route_family") == "watch_runtime"
    assert winner.get("query_shape") == "browser_context"
    assert decision.request_type == "browser_context"
    assert [request.tool_name for request in decision.tool_requests] == ["browser_context"]


def test_planner_v2_routine_execute_uses_native_routine_tool_not_provider() -> None:
    decision = DeterministicPlanner().plan(
        "run my cleanup routine",
        session_id="planner-v2-stabilization",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state={},
        active_context={},
        recent_tool_results=[],
    )
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}

    assert decision.debug["routing_engine"] == "planner_v2"
    assert winner.get("route_family") == "routine"
    assert decision.request_type == "routine_execution"
    assert [request.tool_name for request in decision.tool_requests] == ["routine_execute"]


@pytest.mark.parametrize(
    "prompt",
    [
        "give me morning routine advice",
        "what next steps would algebra students learn",
        "explain Discord documentation format",
    ],
)
def test_stabilization_near_misses_stay_out_of_migrated_native_families(prompt: str) -> None:
    trace = PlannerV2().plan(prompt)

    assert trace.route_decision.selected_route_family not in {"routine", "task_continuity", "discord_relay"}
    assert trace.route_decision.generic_provider_allowed or trace.legacy_fallback_used
