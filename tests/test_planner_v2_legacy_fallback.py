from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def _plan(message: str):
    return DeterministicPlanner().plan(
        message,
        session_id="planner-v2-legacy",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state={},
        active_context={},
        recent_tool_results=[],
    )


def test_planner_v2_explicitly_declines_unowned_prompt_for_legacy_fallback() -> None:
    trace = PlannerV2().plan("write me a cozy paragraph about planning")

    assert trace.authoritative is False
    assert trace.legacy_fallback_used is True
    assert trace.route_decision.routing_engine == "legacy_planner"
    assert trace.route_decision.generic_provider_gate_reason == "no_planner_v2_native_owner"


def test_deterministic_planner_uses_legacy_only_after_planner_v2_declines() -> None:
    decision = _plan("write me a cozy paragraph about planning")

    assert decision.debug["planner_v2"]["authoritative"] is False
    assert decision.debug["planner_v2"]["legacy_fallback_used"] is True
    assert decision.debug["routing_engine"] != "planner_v2"


def test_near_miss_negative_does_not_overroute_to_watch_runtime() -> None:
    trace = PlannerV2().plan("which neural network is more stable")

    assert trace.route_decision.selected_route_family == "generic_provider"
    assert trace.route_decision.selected_route_family != "watch_runtime"
    assert trace.legacy_fallback_used is False

