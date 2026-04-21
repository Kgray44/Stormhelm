from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner


def test_planner_routes_find_tab_request_to_browser_context_tool() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "find the tab with that forum post",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "browser_context"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "browser_context"
    assert decision.tool_requests[0].arguments["operation"] == "find"


def test_planner_routes_add_this_page_to_workspace_to_browser_context_tool() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "add this page to the workspace",
        session_id="default",
        surface_mode="deck",
        active_module="browser",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "browser_context"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "browser_context"
    assert decision.tool_requests[0].arguments["operation"] == "add_to_workspace"


def test_planner_routes_recent_activity_summary_request_to_activity_summary_tool() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "what did I miss?",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "activity_summary"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "activity_summary"
