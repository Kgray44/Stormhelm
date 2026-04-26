from __future__ import annotations

from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def test_policy_is_separate_from_browser_route_selection() -> None:
    trace = PlannerV2().plan("open https://example.com/status")

    assert trace.route_decision.selected_route_family == "browser_destination"
    assert trace.plan_draft.tool_name == "external_open_url"
    assert trace.policy_decision.risk_class == "external_browser_open"
    assert trace.policy_decision.approval_required_live is True
    assert trace.policy_decision.approval_required_eval_dry_run is False
    assert trace.policy_decision.dry_run_allowed is True


def test_software_lifecycle_requires_live_approval_without_changing_route() -> None:
    trace = PlannerV2().plan("install Minecraft")

    assert trace.route_decision.selected_route_family == "software_control"
    assert trace.plan_draft.route_family == "software_control"
    assert trace.policy_decision.risk_class == "software_lifecycle"
    assert trace.policy_decision.approval_required_live is True
    assert trace.policy_decision.dry_run_allowed is True
    assert trace.result_state_draft.result_state == "dry_run_ready"


def test_read_only_software_verification_does_not_require_eval_approval() -> None:
    trace = PlannerV2().plan("check if Git is installed")

    assert trace.route_decision.selected_route_family == "software_control"
    assert trace.policy_decision.risk_class == "read_only"
    assert trace.policy_decision.approval_required_live is False
    assert trace.policy_decision.approval_required_eval_dry_run is False
    assert trace.result_state_draft.result_state == "dry_run_ready"


def test_screen_action_preflight_blocks_execution_without_changing_native_owner() -> None:
    trace = PlannerV2().plan("press submit")

    assert trace.route_decision.selected_route_family == "screen_awareness"
    assert trace.policy_decision.execution_blocked is True
    # Planner v2 now uses the shared visible_screen contract for screen-missing policy reasons.
    assert "visible_screen" in trace.policy_decision.reasons
    assert trace.route_decision.generic_provider_allowed is False

