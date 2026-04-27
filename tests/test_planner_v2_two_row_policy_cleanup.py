from __future__ import annotations

from stormhelm.core.orchestrator.command_eval.corpus import build_command_usability_corpus
from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _plan(
    message: str,
    *,
    active_context: dict[str, object] | None = None,
    active_request_state: dict[str, object] | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="planner-v2-two-row-policy-cleanup",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state=active_request_state or {},
        active_context=active_context or {},
        recent_tool_results=[],
    )


def _case(case_id: str):
    for case in build_command_usability_corpus(min_cases=250):
        if case.case_id == case_id:
            return case
    raise AssertionError(f"missing corpus case {case_id}")


def _winner_family(decision) -> str:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    return str(winner.get("route_family") or "")


def _winner_tools(decision) -> tuple[str, ...]:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    planned = winner.get("planned_tools") if isinstance(winner.get("planned_tools"), list) else []
    explicit = [request.tool_name for request in decision.tool_requests]
    return tuple(dict.fromkeys([*planned, *explicit]))


def _result_state(decision) -> str:
    draft = decision.debug.get("planner_v2", {}).get("result_state_draft", {})
    return str(draft.get("result_state") or "")


def test_calculation_ambiguous_without_numeric_or_prior_context_expects_context_clarification() -> None:
    case = _case("calculations_ambiguous_00")

    assert case.message == "can you handle this?"
    assert case.input_context == {}
    assert case.active_request_state == {}
    assert case.expected.route_family == "context_clarification"
    assert case.expected.subsystem == "context"
    assert case.expected.tools == ()
    assert case.expected.response_terms == ()

    decision = _plan(case.message)
    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "context_clarification"
    assert _result_state(decision) in {"needs_clarification", "blocked_missing_context"}


def test_calculation_followup_with_fresh_prior_context_stays_calculations() -> None:
    decision = _plan(
        "do the same thing as before",
        active_context={
            "recent_context_resolutions": [
                {
                    "kind": "calculation",
                    "result": {"expression": "18 / 3", "display_result": "6"},
                    "trace": {"extracted_expression": "18 / 3"},
                }
            ]
        },
        active_request_state={
            "family": "calculations",
            "subject": "18 / 3",
            "parameters": {"source_case": "calculations", "request_stage": "preview"},
        },
    )

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "calculations"
    assert decision.debug["generic_provider_gate_reason"] == "native_route_candidate_present"


def test_echo_exact_and_clear_casual_forms_route_to_development_echo() -> None:
    for message in ("/echo harness ping", "please echo harness ping"):
        decision = _plan(message)

        assert decision.debug["routing_engine"] == "planner_v2"
        assert _winner_family(decision) == "development"
        assert "echo" in _winner_tools(decision)
        assert decision.tool_requests[0].arguments.get("text") == "harness ping"
        assert decision.debug["generic_provider_gate_reason"] == "native_route_candidate_present"


def test_echo_near_miss_uses_native_development_clarification_not_generic_provider() -> None:
    case = _case("echo_near_miss_00")

    assert case.expected.route_family == "development"
    assert case.expected.subsystem == "development"
    assert case.expected.tools == ()
    assert case.expected.clarification == "expected"
    assert case.expected.response_terms == ()

    decision = _plan(case.message)
    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "development"
    assert _winner_family(decision) != "generic_provider"
    assert _winner_tools(decision) == ()
    assert _result_state(decision) in {"needs_clarification", "blocked_missing_context"}
    assert decision.debug["generic_provider_gate_reason"] == "native_route_candidate_present"
