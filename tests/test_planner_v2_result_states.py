from __future__ import annotations

from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def test_direct_calculation_composes_dry_run_ready_state() -> None:
    trace = PlannerV2().plan("12 * 9")

    assert trace.route_decision.selected_route_family == "calculations"
    assert trace.result_state_draft.result_state == "dry_run_ready"
    assert trace.result_state_draft.user_facing_status == "planned"


def test_missing_context_composes_clarification_not_success() -> None:
    trace = PlannerV2().plan("open that website")

    assert trace.route_decision.selected_route_family == "browser_destination"
    assert trace.result_state_draft.result_state in {"needs_clarification", "blocked_missing_context"}
    assert "which website" in trace.result_state_draft.message.lower()
    assert "opened" not in trace.result_state_draft.message.lower()


def test_policy_block_composes_blocked_state_without_execution_claim() -> None:
    trace = PlannerV2().plan("click the submit button")

    assert trace.route_decision.selected_route_family == "screen_awareness"
    assert trace.policy_decision.execution_blocked is True
    assert trace.result_state_draft.result_state in {"needs_clarification", "blocked_missing_context"}
    assert "clicked" not in trace.result_state_draft.message.lower()


def test_generic_provider_result_state_is_unclassified_not_native_success() -> None:
    trace = PlannerV2().plan("which neural network architecture is better")

    assert trace.route_decision.selected_route_family == "generic_provider"
    assert trace.result_state_draft.result_state == "unsupported"
    assert trace.result_state_draft.user_facing_status == "not_native"

