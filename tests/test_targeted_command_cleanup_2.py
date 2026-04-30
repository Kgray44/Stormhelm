from __future__ import annotations

from stormhelm.core.orchestrator.command_eval.corpus import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.runner import _approval_observed
from stormhelm.core.orchestrator.command_eval.runner import _tools_match_for_case
from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _case(case_id: str) -> CommandEvalCase:
    return {case.case_id: case for case in build_command_usability_corpus(min_cases=1000)}[case_id]


def _plan_case(case_id: str):
    case = _case(case_id)
    return DeterministicPlanner().plan(
        case.message,
        session_id="targeted-command-cleanup-2",
        surface_mode=case.surface_mode,
        active_module=case.active_module,
        workspace_context=case.workspace_context,
        active_context=case.input_context,
        active_request_state=case.active_request_state,
        recent_tool_results=[],
    )


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


def test_deck_followups_preserve_deck_tool_identity() -> None:
    for case_id in (
        "browser_deck_follow_up_00",
        "browser_deck_confirm_00",
        "browser_deck_correction_00",
        "file_deck_follow_up_00",
        "file_deck_confirm_00",
        "file_deck_correction_00",
    ):
        decision = _plan_case(case_id)

        assert decision.debug["routing_engine"] == "planner_v2"
        assert _winner_family(decision) == _case(case_id).expected.route_family
        assert _case(case_id).expected.tools[0] in _winner_tools(decision)
        assert "external_open_url" not in _winner_tools(decision)
        assert "external_open_file" not in _winner_tools(decision)


def test_file_reader_followups_preserve_read_only_tool_identity() -> None:
    for case_id in ("file_reader_follow_up_00", "file_reader_confirm_00", "file_reader_correction_00"):
        decision = _plan_case(case_id)

        assert decision.debug["routing_engine"] == "planner_v2"
        assert _winner_family(decision) == "file"
        assert _winner_tools(decision) == ("file_reader",)
        assert _result_state(decision) in {"dry_run_ready", "planned"}


def test_explicit_deck_file_and_browser_near_miss_are_not_overcaptured() -> None:
    deck_file = _plan_case("file_deck_terse_00")
    near_miss = _plan_case("browser_deck_near_miss_00")

    assert _winner_tools(deck_file) == ("deck_open_file",)
    assert deck_file.tool_requests[0].arguments["path"] == "C:\\Stormhelm\\README.md"
    assert _winner_family(near_miss) == "context_clarification"
    assert near_miss.clarification_reason is not None


def test_strong_cross_family_wrappers_route_to_inner_native_owner() -> None:
    expected = {
        "desktop_search_cross_family_00": ("desktop_search", "desktop_search"),
        "workspace_where_left_off_cross_family_00": ("task_continuity", "workspace_where_left_off"),
        "shell_command_cross_family_00": ("terminal", "shell_command"),
        "workspace_save_cross_family_00": ("workspace_operations", "workspace_save"),
        "workspace_clear_cross_family_00": ("workspace_operations", "workspace_clear"),
        "workspace_archive_cross_family_00": ("workspace_operations", "workspace_archive"),
    }

    for case_id, (family, tool) in expected.items():
        decision = _plan_case(case_id)
        assert decision.debug["routing_engine"] == "planner_v2"
        assert _winner_family(decision) == family
        assert tool in _winner_tools(decision)
        assert _winner_family(decision) not in {"generic_provider", "screen_awareness"}


def test_routine_save_deictic_and_confirmation_keep_correct_boundary() -> None:
    vague = _plan_case("routine_save_deictic_00")
    confirm = _plan_case("routine_save_confirm_00")

    assert _winner_family(vague) == "context_clarification"
    assert vague.clarification_reason is not None
    assert _winner_family(confirm) == "routine"
    assert _winner_tools(confirm) == ("routine_save",)


def test_workspace_assemble_async_continuation_satisfies_eval_tool_contract() -> None:
    case = CommandEvalCase(
        case_id="workspace_assemble_async_contract",
        message="create a research workspace",
        expected=ExpectedBehavior(
            route_family="workspace_operations",
            subsystem="workspace",
            tools=("workspace_assemble",),
        ),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=100.0,
        ui_response="Queued workspace assembly.",
        actual_route_family="workspace_operations",
        actual_subsystem="workspace",
        tool_chain=("subsystem_continuation",),
        result_state="queued",
        latency_summary={
            "subsystem_continuation_created": True,
            "subsystem_continuation_kind": "workspace.assemble_deep",
        },
    )

    assert _tools_match_for_case(case, observation)


def test_planner_v2_policy_preview_counts_as_approval_posture() -> None:
    assistant_message = {
        "metadata": {
            "planner_debug": {
                "planner_v2": {
                    "policy_decision": {
                        "approval_required_live": True,
                        "preview_required_live": True,
                    }
                }
            }
        }
    }

    assert _approval_observed((), {}, assistant_message) is True
