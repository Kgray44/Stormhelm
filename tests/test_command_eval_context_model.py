from __future__ import annotations

from stormhelm.core.orchestrator.command_eval.corpus import build_command_usability_corpus
from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def _case(case_id: str):
    return next(case for case in build_command_usability_corpus(min_cases=1000) if case.case_id == case_id)


def test_no_context_can_handle_this_expects_context_clarification() -> None:
    case = _case("software_control_install_ambiguous_00")

    assert case.message == "can you handle this?"
    assert case.expected.route_family == "context_clarification"
    assert case.expected.subsystem == "context"
    assert case.expected.clarification == "expected"
    assert case.context_lane == "no_context_ambiguity"
    assert case.seeded_context_required is False
    assert case.expected_behavior_without_context == "context_clarification"


def test_correction_rows_declare_prior_owner_and_alternate_target() -> None:
    case = _case("browser_destination_correction_00")

    assert case.message == "no, use the other one"
    assert case.context_lane == "correction_with_prior_owner"
    assert case.seeded_context_required is True
    assert case.expected_prior_family == "browser_destination"
    assert case.expected_prior_tool == "external_open_url"
    assert case.expected_alternate_target == "Stormhelm docs"
    assert case.expected_behavior_without_context == "context_clarification"


def test_confirmation_rows_require_pending_preview_metadata() -> None:
    case = _case("browser_destination_confirm_00")

    assert case.message == "yes, go ahead with that preview"
    assert case.context_lane == "seeded_context_binding"
    assert case.seeded_context_required is True
    assert case.expected_confirmation_state == "pending_preview"
    assert case.expected_behavior_without_context == "context_clarification"


def test_planner_v2_no_context_correction_and_confirmation_clarify_natively() -> None:
    planner = PlannerV2()

    for prompt in ("no, use the other one", "yes, go ahead"):
        trace = planner.plan(prompt)

        assert trace.route_decision.routing_engine == "planner_v2"
        assert trace.route_decision.selected_route_family == "context_clarification"
        assert trace.result_state_draft.result_state == "needs_clarification"
        assert trace.route_decision.generic_provider_allowed is False


def test_planner_v2_seeded_browser_correction_binds_to_prior_owner() -> None:
    trace = PlannerV2().plan(
        "no, use the other one",
        active_context={
            "recent_entities": [
                {"kind": "page", "title": "Stormhelm docs", "url": "https://docs.example.com/stormhelm", "freshness": "current"},
                {"kind": "page", "title": "Example", "url": "https://example.com", "freshness": "current"},
            ]
        },
        active_request_state={
            "family": "browser_destination",
            "subject": "YouTube",
            "parameters": {
                "source_case": "browser_destination",
                "tool_name": "external_open_url",
                "previous_choice": "YouTube",
                "alternate_target": "Stormhelm docs",
                "request_stage": "preview",
                "context_freshness": "current",
            },
        },
    )

    assert trace.route_decision.selected_route_family == "browser_destination"
    assert trace.plan_draft.tool_name == "external_open_url"
    assert trace.context_binding.status == "available"
    assert trace.route_decision.generic_provider_allowed is False


def test_planner_v2_seeded_software_can_handle_this_binds_to_prior_owner() -> None:
    trace = PlannerV2().plan(
        "can you handle this?",
        active_request_state={
            "family": "software_control",
            "subject": "Firefox",
            "parameters": {
                "operation_type": "install",
                "target_name": "Firefox",
                "request_stage": "preview",
                "context_freshness": "current",
            },
        },
    )

    assert trace.route_decision.selected_route_family == "software_control"
    assert trace.context_binding.status == "available"
    assert trace.route_decision.generic_provider_allowed is False
