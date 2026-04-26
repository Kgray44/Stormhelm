from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def _planner_decision(message: str, **kwargs):
    return DeterministicPlanner().plan(
        message,
        session_id="planner-v2-test",
        surface_mode=kwargs.pop("surface_mode", "ghost"),
        active_module="chartroom",
        workspace_context=kwargs.pop("workspace_context", {}),
        active_posture={},
        active_request_state=kwargs.pop("active_request_state", {}),
        active_context=kwargs.pop("active_context", {}),
        recent_tool_results=kwargs.pop("recent_tool_results", []),
    )


def _winner_family(decision) -> str:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    return str(winner.get("route_family") or "")


def test_planner_v2_models_are_serializable_and_pipeline_runs_first() -> None:
    trace = PlannerV2().plan("what is 7 * 8")

    payload = trace.to_dict()

    assert payload["normalized_request"]["normalized_text"] == "what is 7 * 8"
    assert payload["intent_frame"]["operation"] == "calculate"
    assert payload["route_decision"]["routing_engine"] == "planner_v2"
    assert payload["route_decision"]["selected_route_family"] == "calculations"
    assert payload["plan_draft"]["route_family"] == "calculations"
    assert payload["policy_decision"]["dry_run_allowed"] is True
    assert payload["result_state_draft"]["result_state"] == "dry_run_ready"


def test_deterministic_planner_uses_planner_v2_for_selected_families() -> None:
    cases = [
        ("what is 7 * 8", "calculations"),
        ("open https://example.com/status", "browser_destination"),
        ("open Notepad", "app_control"),
        ("quit Notepad", "app_control"),
        ("install Minecraft", "software_control"),
        ("check if Git is installed", "software_control"),
        ("what am I looking at", "screen_awareness"),
        ("which wifi am I on", "network"),
    ]

    for prompt, expected_family in cases:
        decision = _planner_decision(prompt)

        assert decision.debug["routing_engine"] == "planner_v2", prompt
        assert decision.debug["planner_v2"]["route_decision"]["routing_engine"] == "planner_v2", prompt
        assert _winner_family(decision) == expected_family, prompt


def test_planner_v2_generic_provider_is_gated_behind_native_declines() -> None:
    trace = PlannerV2().plan("which neural network architecture is better")

    assert trace.route_decision.routing_engine == "generic_provider"
    assert trace.route_decision.generic_provider_allowed is True
    assert trace.route_decision.generic_provider_gate_reason in {
        "native_candidates_declined",
        "conceptual_near_miss_no_native_action",
    }
    assert "watch_runtime" in trace.route_decision.native_decline_reasons
    assert trace.legacy_fallback_used is False
