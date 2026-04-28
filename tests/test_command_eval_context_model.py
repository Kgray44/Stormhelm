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


def test_planner_v2_correction_prior_owner_without_alternate_clarifies_natively() -> None:
    trace = PlannerV2().plan(
        "no, use the other one",
        active_request_state={
            "family": "browser_destination",
            "subject": "https://example.com",
            "parameters": {
                "url": "https://example.com",
                "tool_name": "external_open_url",
                "context_freshness": "current",
            },
        },
    )

    assert trace.route_decision.selected_route_family == "browser_destination"
    assert trace.context_binding.status == "missing"
    assert trace.result_state_draft.result_state == "needs_clarification"
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


def test_planner_v2_confirmation_with_pending_preview_binds_only_to_preview() -> None:
    trace = PlannerV2().plan(
        "yes, go ahead with that preview",
        active_request_state={
            "family": "browser_destination",
            "subject": "https://example.com",
            "parameters": {
                "url": "https://example.com",
                "tool_name": "external_open_url",
                "pending_preview": {"id": "preview-browser-1", "status": "pending"},
                "request_stage": "preview",
                "context_freshness": "current",
            },
        },
    )

    assert trace.route_decision.selected_route_family == "browser_destination"
    assert trace.context_binding.context_type == "pending_preview"
    assert trace.plan_draft.tool_name == "external_open_url"
    assert trace.route_decision.generic_provider_allowed is False


def test_planner_v2_confirmation_without_pending_preview_clarifies() -> None:
    trace = PlannerV2().plan(
        "yes, go ahead",
        active_request_state={
            "family": "browser_destination",
            "subject": "https://example.com",
            "parameters": {
                "url": "https://example.com",
                "tool_name": "external_open_url",
                "context_freshness": "current",
            },
        },
    )

    assert trace.route_decision.selected_route_family == "context_clarification"
    assert trace.context_binding.status == "missing"
    assert trace.context_binding.missing_preconditions == ("no_pending_confirmation",)
    assert trace.result_state_draft.result_state == "needs_clarification"
    assert trace.route_decision.generic_provider_allowed is False


def test_planner_v2_stale_confirmation_clarifies_even_with_pending_preview() -> None:
    trace = PlannerV2().plan(
        "yes, go ahead",
        active_request_state={
            "family": "browser_destination",
            "subject": "https://example.com",
            "parameters": {
                "url": "https://example.com",
                "tool_name": "external_open_url",
                "pending_preview": {"id": "preview-browser-old", "status": "pending"},
                "request_stage": "preview",
                "context_freshness": "stale",
            },
        },
    )

    assert trace.route_decision.selected_route_family == "context_clarification"
    assert trace.result_state_draft.result_state == "needs_clarification"
    assert trace.route_decision.generic_provider_allowed is False


def test_planner_v2_active_browser_state_supplies_url_for_real_followup() -> None:
    trace = PlannerV2().plan(
        "do the same thing as before",
        active_request_state={
            "family": "browser_destination",
            "subject": "https://example.com",
            "route": {"tool_name": "external_open_url"},
            "parameters": {
                "url": "https://example.com",
                "tool_name": "external_open_url",
                "source_case": "external_open_url",
                "context_freshness": "current",
            },
        },
    )

    assert trace.route_decision.selected_route_family == "browser_destination"
    assert trace.plan_draft.tool_name == "external_open_url"
    assert trace.plan_draft.tool_arguments["url"] == "https://example.com"
    assert trace.context_binding.status == "available"
    assert trace.route_decision.generic_provider_allowed is False


def test_planner_v2_seeded_file_state_missing_path_clarifies() -> None:
    trace = PlannerV2().plan(
        "do the same thing as before",
        active_request_state={
            "family": "file",
            "subject": "file",
            "parameters": {
                "tool_name": "file_reader",
                "context_freshness": "current",
            },
        },
    )

    assert trace.route_decision.selected_route_family == "file"
    assert trace.context_binding.status == "missing"
    assert trace.result_state_draft.result_state == "needs_clarification"
    assert trace.route_decision.generic_provider_allowed is False


def test_planner_v2_active_workspace_state_preserves_prior_tool() -> None:
    trace = PlannerV2().plan(
        "do the same thing as before",
        active_request_state={
            "family": "workspace_operations",
            "subject": "workspace",
            "route": {"tool_name": "workspace_save"},
            "parameters": {
                "tool_name": "workspace_save",
                "source_case": "workspace_save",
                "context_freshness": "current",
            },
        },
    )

    assert trace.route_decision.selected_route_family == "workspace_operations"
    assert trace.plan_draft.tool_name == "workspace_save"
    assert trace.route_decision.generic_provider_allowed is False


def test_planner_v2_stale_active_state_clarifies_without_binding_prior_owner() -> None:
    trace = PlannerV2().plan(
        "do the same thing as before",
        active_request_state={
            "family": "browser_destination",
            "subject": "https://example.com",
            "route": {"tool_name": "external_open_url"},
            "parameters": {
                "url": "https://example.com",
                "tool_name": "external_open_url",
                "context_freshness": "stale",
            },
        },
    )

    assert trace.route_decision.selected_route_family == "context_clarification"
    assert trace.result_state_draft.result_state == "needs_clarification"
    assert trace.route_decision.generic_provider_allowed is False
