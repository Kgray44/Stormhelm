from __future__ import annotations

from stormhelm.core.orchestrator.command_eval.corpus import build_command_usability_corpus
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def _plan(
    message: str,
    *,
    active_context: dict[str, object] | None = None,
    active_request_state: dict[str, object] | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="ambiguous-deictic-test",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state=active_request_state or {},
        active_context=active_context or {},
        recent_tool_results=[],
    )


def _winner_family(decision) -> str:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    return str(winner.get("route_family") or "")


def _winner_subsystem(decision) -> str:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    planner_v2 = decision.debug.get("planner_v2") if isinstance(decision.debug, dict) else {}
    route_decision = planner_v2.get("route_decision") if isinstance(planner_v2, dict) else {}
    structured = decision.structured_query.to_dict() if decision.structured_query is not None else {}
    return str(winner.get("subsystem") or route_decision.get("selected_subsystem") or structured.get("domain") or "")


def _result_state(decision) -> str:
    draft = decision.debug.get("planner_v2", {}).get("result_state_draft", {})
    return str(draft.get("result_state") or "")


def _selected_text_context() -> dict[str, object]:
    return {
        "selection": {
            "kind": "text",
            "preview": "Selected launch notes",
            "value": "Selected launch notes",
        }
    }


def test_use_this_for_that_without_prior_owner_routes_to_native_clarification_lane() -> None:
    trace = PlannerV2().plan("use this for that", active_context=_selected_text_context())
    decision = _plan("use this for that", active_context=_selected_text_context())

    assert trace.route_decision.routing_engine == "planner_v2"
    assert trace.route_decision.selected_route_family == "context_clarification"
    assert trace.route_decision.generic_provider_allowed is False
    assert trace.result_state_draft.result_state == "needs_clarification"
    assert trace.plan_draft.tool_name is None
    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "context_clarification"
    assert _winner_subsystem(decision) == "context"
    assert _result_state(decision) == "needs_clarification"
    assert decision.tool_requests == []


def test_do_same_before_without_prior_owner_routes_to_native_clarification_lane() -> None:
    trace = PlannerV2().plan("do the same thing as before")

    assert trace.route_decision.routing_engine == "planner_v2"
    assert trace.route_decision.selected_route_family == "context_clarification"
    assert trace.route_decision.generic_provider_allowed is False
    assert trace.result_state_draft.result_state == "needs_clarification"
    assert trace.plan_draft.tool_name is None


def test_use_this_for_that_with_prior_browser_owner_stays_browser_owned() -> None:
    active_state = {
        "family": "browser_destination",
        "subject": "browser destination",
        "parameters": {"request_stage": "preview"},
    }

    trace = PlannerV2().plan(
        "use this for that",
        active_request_state=active_state,
    )

    assert trace.route_decision.selected_route_family == "browser_destination"
    assert trace.result_state_draft.result_state == "needs_clarification"
    assert trace.route_decision.generic_provider_allowed is False


def test_use_this_for_that_with_prior_app_status_owner_stays_app_owned() -> None:
    active_state = {
        "family": "app_control",
        "subject": "active apps",
        "parameters": {"source_case": "active_apps", "request_stage": "preview"},
    }

    trace = PlannerV2().plan(
        "use this for that",
        active_request_state=active_state,
    )

    assert trace.route_decision.selected_route_family == "app_control"
    assert trace.plan_draft.tool_name == "active_apps"
    assert trace.route_decision.generic_provider_allowed is False


def test_discord_missing_payload_or_recipient_clarifies_inside_discord_family() -> None:
    trace = PlannerV2().plan("send this to Baby")

    assert trace.route_decision.selected_route_family == "discord_relay"
    assert trace.result_state_draft.result_state == "needs_clarification"
    assert trace.route_decision.generic_provider_allowed is False


def test_routine_save_missing_context_clarifies_inside_routine_family() -> None:
    trace = PlannerV2().plan("save this as a routine")

    assert trace.route_decision.selected_route_family == "routine"
    assert trace.result_state_draft.result_state == "needs_clarification"
    assert trace.route_decision.generic_provider_allowed is False


def test_conceptual_this_question_does_not_enter_context_clarification_lane() -> None:
    trace = PlannerV2().plan("what is this architecture concept")

    assert trace.route_decision.selected_route_family != "context_clarification"
    assert trace.route_decision.generic_provider_allowed is True


def test_general_question_without_deictic_does_not_enter_context_clarification_lane() -> None:
    trace = PlannerV2().plan("write a two sentence pep talk for finals")

    assert trace.route_decision.selected_route_family != "context_clarification"


def test_confident_migrated_family_still_routes_normally() -> None:
    trace = PlannerV2().plan("open https://example.com")

    assert trace.route_decision.selected_route_family == "browser_destination"
    assert trace.result_state_draft.result_state == "dry_run_ready"


def test_unsupported_feature_request_remains_unsupported() -> None:
    trace = PlannerV2().plan("book me a real flight and pay for it now")

    assert trace.route_decision.selected_route_family != "context_clarification"
    assert trace.route_decision.generic_provider_allowed is True


def test_trust_pending_deictic_routes_to_trust_approval_owner() -> None:
    active_state = {
        "family": "software_control",
        "subject": "firefox",
        "parameters": {
            "operation_type": "install",
            "request_stage": "awaiting_confirmation",
            "target_name": "firefox",
        },
        "trust": {
            "request_id": "trust-eval-1",
            "reason": "Installing software changes the machine.",
        },
    }

    trace = PlannerV2().plan(
        "use this for that",
        active_context=_selected_text_context(),
        active_request_state=active_state,
    )

    assert trace.route_decision.selected_route_family == "trust_approvals"
    assert trace.route_decision.selected_subsystem == "trust"
    assert trace.route_decision.generic_provider_allowed is False


def test_command_eval_deictic_no_owner_expectation_normalizes_to_context_clarification() -> None:
    case = next(
        item
        for item in build_command_usability_corpus(min_cases=250)
        if item.case_id == "browser_destination_deictic_00"
    )

    assert case.expected.route_family == "context_clarification"
    assert case.expected.subsystem == "context"
    assert case.expected.tools == ()
    assert case.expected.clarification == "expected"
    assert case.expected.approval == "not_expected"


def test_command_eval_followup_browser_destination_uses_bound_page_target_slot() -> None:
    case = next(
        item
        for item in build_command_usability_corpus(min_cases=250)
        if item.case_id == "browser_destination_follow_up_00"
    )

    assert case.expected.route_family == "browser_destination"
    assert case.expected.target_slots == {"destination_name": "Stormhelm docs"}


def test_command_eval_discord_followup_clarification_does_not_require_approval() -> None:
    case = next(
        item
        for item in build_command_usability_corpus(min_cases=250)
        if item.case_id == "discord_relay_follow_up_00"
    )

    assert case.expected.route_family == "discord_relay"
    assert case.expected.approval == "allowed"
