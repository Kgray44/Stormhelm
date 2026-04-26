from __future__ import annotations

from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def test_missing_browser_deictic_clarifies_inside_browser_family() -> None:
    trace = PlannerV2().plan("open that website")

    assert trace.route_decision.selected_route_family == "browser_destination"
    assert trace.context_binding.context_reference == "that"
    assert trace.context_binding.status == "missing"
    assert trace.result_state_draft.result_state in {"needs_clarification", "blocked_missing_context"}
    assert trace.route_decision.generic_provider_allowed is False


def test_available_current_page_binds_browser_deictic() -> None:
    trace = PlannerV2().plan(
        "open that website",
        active_context={
            "recent_entities": [
                {
                    "kind": "page",
                    "title": "Stormhelm docs",
                    "url": "https://docs.example.com/stormhelm",
                    "freshness": "current",
                }
            ]
        },
    )

    assert trace.context_binding.status == "available"
    assert trace.context_binding.context_type in {"current_page", "website"}
    assert trace.context_binding.value == "https://docs.example.com/stormhelm"
    assert trace.plan_draft.tool_arguments["url"] == "https://docs.example.com/stormhelm"


def test_calculation_followup_binds_prior_calculation_context() -> None:
    trace = PlannerV2().plan(
        "now divide that by 3",
        active_context={
            "recent_context_resolutions": [
                {
                    "kind": "calculation",
                    "result": {"expression": "18 / 3", "display_result": "6"},
                    "trace": {"extracted_expression": "18 / 3"},
                }
            ]
        },
    )

    assert trace.route_decision.selected_route_family == "calculations"
    assert trace.context_binding.status == "available"
    assert trace.context_binding.context_type == "prior_calculation"
    assert trace.result_state_draft.result_state == "dry_run_ready"


def test_missing_prior_calculation_clarifies_inside_calculations() -> None:
    trace = PlannerV2().plan("now divide that by 3")

    assert trace.route_decision.selected_route_family == "calculations"
    assert trace.context_binding.status == "missing"
    assert trace.result_state_draft.result_state in {"needs_clarification", "blocked_missing_context"}
    assert trace.route_decision.generic_provider_allowed is False


def test_selected_text_context_action_binds_selected_text() -> None:
    trace = PlannerV2().plan(
        "summarize the selected text",
        active_context={
            "selection": {
                "kind": "text",
                "value": "Selected Stormhelm routing notes.",
                "preview": "Selected Stormhelm routing notes.",
            }
        },
    )

    assert trace.route_decision.selected_route_family == "context_action"
    assert trace.context_binding.status == "available"
    assert trace.context_binding.context_type == "selected_text"
    assert trace.plan_draft.tool_name == "context_action"


def test_visible_ui_target_requires_grounding_before_action() -> None:
    trace = PlannerV2().plan("press submit")

    assert trace.route_decision.selected_route_family == "screen_awareness"
    assert trace.context_binding.status == "missing"
    assert trace.policy_decision.execution_blocked is True
    assert trace.result_state_draft.result_state in {"needs_clarification", "blocked_missing_context"}

