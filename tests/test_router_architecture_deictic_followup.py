from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.route_spine import RouteSpine


def _route(
    message: str,
    *,
    active_context: dict[str, object] | None = None,
    active_request_state: dict[str, object] | None = None,
):
    return RouteSpine().route(
        message,
        active_context=active_context or {},
        active_request_state=active_request_state or {},
        recent_tool_results=[],
    )


def _calculation_context() -> dict[str, object]:
    return {
        "recent_context_resolutions": [
            {
                "kind": "calculation",
                "result": {"expression": "54 / 6", "display_result": "9"},
                "trace": {"extracted_expression": "54 / 6"},
            }
        ]
    }


def _browser_context() -> dict[str, object]:
    return {
        "recent_entities": [
            {
                "kind": "page",
                "title": "Stormhelm deck",
                "url": "https://stormhelm.local/deck",
                "freshness": "current",
            }
        ]
    }


def _file_context() -> dict[str, object]:
    return {
        "recent_entities": [
            {
                "kind": "file",
                "title": "README.md",
                "path": r"C:\Stormhelm\README.md",
                "freshness": "current",
            }
        ]
    }


def _selection_context() -> dict[str, object]:
    return {
        "selection": {
            "kind": "text",
            "value": "Selected notes about command routing.",
            "preview": "Selected notes about command routing.",
        }
    }


def _plan(message: str, *, active_context: dict[str, object] | None = None):
    return DeterministicPlanner().plan(
        message,
        session_id="router-architecture",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state={},
        active_context=active_context or {},
        recent_tool_results=[],
    )


def test_calculation_followups_bind_or_clarify_inside_calculations() -> None:
    positives = [
        "walk me through that answer",
        "reuse that result but multiply by 4",
        "same equation, swap in 72",
        "now compare that number with 12",
        "show arithmetic for the previous answer",
        "divide the last answer by 3",
    ]
    for prompt in positives:
        decision = _route(prompt, active_context=_calculation_context(), active_request_state={"family": "calculations"})

        assert decision.winner.route_family == "calculations", prompt
        assert decision.intent_frame.context_status == "available", prompt
        assert decision.generic_provider_allowed is False, prompt

    missing = _route("divide the last answer by 3")

    assert missing.winner.route_family == "calculations"
    assert missing.clarification_needed is True
    assert "calculation_context" in missing.missing_preconditions


def test_planner_v2_calculations_still_execute_native_calculation_plan() -> None:
    decision = _plan("answer 7 times 4")

    assert decision.debug["routing_engine"] == "planner_v2"
    assert decision.debug["planner_v2"]["route_decision"]["selected_route_family"] == "calculations"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "calculation_evaluate"
    assert decision.structured_query is not None
    calculation_request = decision.structured_query.slots["calculation_request"]
    assert calculation_request["extracted_expression"] == "7 times 4"


def test_browser_file_and_selection_deictics_use_compatible_context_only() -> None:
    browser = _route("open the link we were using", active_context=_browser_context())
    assert browser.winner.route_family == "browser_destination"
    assert browser.intent_frame.context_status == "available"
    assert browser.tool_candidates in (["external_open_url"], ["deck_open_url"])

    file_decision = _route("show me that previous document", active_context=_file_context())
    assert file_decision.winner.route_family == "file"
    assert file_decision.intent_frame.context_status == "available"
    assert "external_open_file" in file_decision.tool_candidates or "deck_open_file" in file_decision.tool_candidates

    selected = _route("turn the highlighted text into tasks", active_context=_selection_context())
    assert selected.winner.route_family in {"context_action", "task_continuity"}
    assert selected.intent_frame.context_status == "available"
    assert selected.generic_provider_allowed is False

    wrong_context = _route("open that website", active_context=_file_context())
    assert wrong_context.winner.route_family == "browser_destination"
    assert wrong_context.clarification_needed is True
    assert "destination_context" in wrong_context.missing_preconditions


def test_cross_family_boundaries_are_contractual() -> None:
    expectations = {
        "which apps are running": "app_control",
        "open that website": "browser_destination",
        "which neural network should I use": "generic_provider",
        "press coverage summary": "generic_provider",
        "click the submit button": "screen_awareness",
        "quit Notepad, not uninstall it": "app_control",
        "update Notepad": "software_control",
        "relay the selected text to Baby on Discord": "discord_relay",
    }
    for prompt, family in expectations.items():
        active_context = _selection_context() if "selected text" in prompt else {}
        decision = _route(prompt, active_context=active_context)

        assert decision.winner.route_family == family, prompt
