from __future__ import annotations

from stormhelm.core.orchestrator.command_eval.corpus import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval.models import AssertionOutcome
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.runner import _target_slots
from stormhelm.core.orchestrator.command_eval.runner import _failure_category
from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _case(case_id: str):
    return next(case for case in build_command_usability_corpus(min_cases=250) if case.case_id == case_id)


def _plan(message: str):
    return DeterministicPlanner().plan(
        message,
        session_id="stabilization-2-test",
        surface_mode="chat",
        active_module="chat",
    )


def test_browser_destination_target_slots_stay_eval_stable_with_planner_v2() -> None:
    decision = _plan("open youtube in a browser")
    jobs = tuple({"arguments": request.arguments} for request in decision.tool_requests)

    slots = _target_slots(decision.debug, jobs)

    assert slots["destination_name"] == "youtube"


def test_restored_weather_owner_reaches_planner_v2_native_route() -> None:
    decision = _plan("what is the weather here")

    assert decision.structured_query is not None
    assert decision.structured_query.domain == "weather"
    assert [request.tool_name for request in decision.tool_requests] == ["weather_current"]
    assert decision.debug.get("routing_engine") == "planner_v2"


def test_exact_weather_prompt_does_not_hit_voice_control_helper_regression() -> None:
    decision = _plan("what is the weather")

    assert decision.structured_query is not None
    assert decision.structured_query.domain == "weather"
    assert [request.tool_name for request in decision.tool_requests] == ["weather_current"]
    assert decision.debug.get("routing_engine") == "planner_v2"


def test_voice_control_prompt_reaches_planner_v2_native_route() -> None:
    decision = _plan("stop talking")
    winner = decision.route_state.to_dict()["winner"] if decision.route_state is not None else {}

    assert decision.structured_query is not None
    assert decision.structured_query.domain == "voice"
    assert winner.get("route_family") == "voice_control"
    assert decision.debug.get("routing_engine") == "planner_v2"


def test_terminal_direct_eval_taxonomy_matches_terminal_subsystem() -> None:
    case = _case("shell_command_canonical_00")

    assert case.expected.route_family == "terminal"
    assert case.expected.subsystem == "terminal"


def test_screen_awareness_without_grounding_expects_native_clarification() -> None:
    case = _case("screen_awareness_canonical_00")

    assert case.expected.route_family == "screen_awareness"
    assert case.expected.clarification == "expected"


def test_where_left_off_routeable_case_supplies_workspace_context() -> None:
    case = _case("workspace_where_left_off_canonical_00")

    assert case.expected.route_family == "task_continuity"
    assert case.workspace_context


def test_latency_only_legacy_rows_stay_latency_not_missing_telemetry() -> None:
    case = CommandEvalCase(
        case_id="system_info_canonical_00",
        message="/system",
        expected=ExpectedBehavior(
            route_family="machine",
            subsystem="system",
            tools=("system_info",),
        ),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=2624.734,
        ui_response="Dry-run only: would execute System Info. No external action was performed.",
        actual_route_family="machine",
        actual_subsystem="system",
        tool_chain=("system_info",),
        result_state="dry_run",
        verification_state="dry_run_preview",
        route_state={},
        planner_obedience={},
    )
    assertions = {
        "route_family": AssertionOutcome("route_family", True, "machine", "machine"),
        "subsystem": AssertionOutcome("subsystem", True, "system", "system"),
        "tool_chain": AssertionOutcome("tool_chain", True, ("system_info",), ("system_info",)),
        "latency": AssertionOutcome("latency", False, 2500, 2624.734),
    }

    assert _failure_category(case, observation, assertions, score_in_pass_fail=True) == "latency_issue"
