from __future__ import annotations

import pytest

from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def _planner_v2(message: str, *, active_context=None, active_request_state=None):
    return PlannerV2().plan(
        message,
        active_context=active_context or {},
        active_request_state=active_request_state or {},
    )


def _deterministic(message: str, *, active_context=None, active_request_state=None):
    return DeterministicPlanner().plan(
        message,
        session_id="planner-v2-expansion",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state=active_request_state or {},
        active_context=active_context or {},
        recent_tool_results=[],
    )


WORKSPACE_CONTEXT = {
    "current_resolution": {
        "kind": "workspace_seed",
        "title": "Router diagnostics notes",
        "items": [{"title": "ping log"}, {"title": "driver notes"}],
    }
}

TASK_CONTEXT = {
    "workspace": {"name": "Stormhelm command eval", "workspaceId": "eval-workspace"},
    "current_task": {"title": "Route spine cleanup", "status": "in_progress"},
}

SELECTION_CONTEXT = {
    "selection": {
        "kind": "text",
        "value": "Selected command-routing notes.",
        "preview": "Selected command-routing notes.",
    }
}

WORKFLOW_STATE = {
    "family": "workflow",
    "subject": "writing_setup",
    "parameters": {"workflow_kind": "writing_setup", "query": "open writing setup"},
}


POSITIVE_CASES = [
    # workspace_operations exact/repro and unseen variants
    ("workspace_exact_make_for_this", "make a workspace for this", "workspace_operations", WORKSPACE_CONTEXT, {}),
    ("workspace_positive_assemble_project", "assemble a workspace for the router diagnostics project", "workspace_operations", {}, {}),
    ("workspace_positive_gather_notes", "gather everything relevant into a workspace", "workspace_operations", {}, {}),
    ("workspace_positive_open_project", "open the project workspace", "workspace_operations", {}, {}),
    ("workspace_positive_restore_setup", "restore the client research workspace", "workspace_operations", {}, {}),
    ("workspace_positive_save_current", "save current workspace", "workspace_operations", {}, {}),
    ("workspace_positive_snapshot", "snapshot the workspace", "workspace_operations", {}, {}),
    ("workspace_positive_list_recent", "list my recent workspaces", "workspace_operations", {}, {}),
    ("workspace_positive_show_archived", "show my archived workspaces", "workspace_operations", {}, {}),
    # routine exact/repro and unseen variants
    ("routine_exact_save_this", "save this as a routine called cleanup", "routine", {}, WORKFLOW_STATE),
    ("routine_positive_remember_workflow", "remember this workflow as cleanup", "routine", {}, WORKFLOW_STATE),
    ("routine_positive_turn_into", "turn this into a routine named review pass", "routine", {}, WORKFLOW_STATE),
    ("routine_positive_make_routine", "make this a routine", "routine", {}, WORKFLOW_STATE),
    ("routine_positive_save_that", "save that as a routine called morning check", "routine", {}, WORKFLOW_STATE),
    ("routine_positive_run_cleanup", "run my cleanup routine", "routine", {}, {}),
    ("routine_positive_run_health", "run the network health check", "routine", {}, {}),
    ("routine_positive_rerun_setup", "rerun my normal setup", "routine", {}, {}),
    ("routine_positive_execute_saved", "execute the saved workflow cleanup", "routine", {}, {}),
    # workflow exact/repro and unseen variants
    ("workflow_exact_writing", "set up my writing environment", "workflow", {}, {}),
    ("workflow_positive_diagnostics", "prepare a diagnostics setup", "workflow", {}, {}),
    ("workflow_positive_research", "open my research setup", "workflow", {}, {}),
    ("workflow_positive_current_context", "open my current work context", "workflow", {}, {}),
    ("workflow_positive_project_setup", "set up my project environment", "workflow", {}, {}),
    ("workflow_positive_run_workflow", "run the review workflow", "workflow", {}, {}),
    ("workflow_positive_restore_workflow", "restore the debugging workflow", "workflow", {}, {}),
    ("workflow_positive_prepare_setup", "prepare my review setup", "workflow", {}, {}),
    ("workflow_positive_launch_setup", "launch the diagnostics workflow", "workflow", {}, {}),
    # task_continuity exact/repro and unseen variants
    ("task_exact_continue_that", "continue that", "task_continuity", TASK_CONTEXT, {}),
    ("task_positive_resume_task", "resume the task", "task_continuity", TASK_CONTEXT, {}),
    ("task_positive_where_were_we", "where were we", "task_continuity", TASK_CONTEXT, {}),
    ("task_positive_where_left_off", "where did we leave off", "task_continuity", TASK_CONTEXT, {}),
    ("task_positive_pick_up", "pick up where we left off", "task_continuity", TASK_CONTEXT, {}),
    ("task_positive_next_steps", "what should I do next", "task_continuity", TASK_CONTEXT, {}),
    ("task_positive_still_left", "what is still left on this task", "task_continuity", TASK_CONTEXT, {}),
    ("task_positive_resume_previous", "resume the previous task", "task_continuity", TASK_CONTEXT, {}),
    ("task_positive_continue_from_there", "continue from there", "task_continuity", TASK_CONTEXT, {}),
    # discord_relay exact/repro and unseen variants
    ("discord_exact_send_this", "send this to Baby", "discord_relay", SELECTION_CONTEXT, {}),
    ("discord_positive_relay_selected", "relay the selected text to Baby", "discord_relay", SELECTION_CONTEXT, {}),
    ("discord_positive_message_baby", "message Baby this", "discord_relay", SELECTION_CONTEXT, {}),
    ("discord_positive_share_this", "share this with Baby on Discord", "discord_relay", SELECTION_CONTEXT, {}),
    ("discord_positive_forward_selection", "forward the highlighted text to Baby", "discord_relay", SELECTION_CONTEXT, {}),
    ("discord_positive_dm_baby", "dm Baby the selected text", "discord_relay", SELECTION_CONTEXT, {}),
    ("discord_positive_post_note", "post this to Baby with a note", "discord_relay", SELECTION_CONTEXT, {}),
    ("discord_positive_pass_along", "pass this along to Baby", "discord_relay", SELECTION_CONTEXT, {}),
    ("discord_positive_send_clip", "send the clipboard note to Baby", "discord_relay", SELECTION_CONTEXT, {}),
]


MISSING_CONTEXT_CASES = [
    ("workspace_missing_this", "make a workspace for this", "workspace_operations"),
    ("workspace_missing_current", "save this workspace", "workspace_operations"),
    ("workspace_missing_that", "assemble that workspace", "workspace_operations"),
    ("workspace_missing_project", "make a project workspace from that", "workspace_operations"),
    ("workspace_missing_save_here", "snapshot where we are", "workspace_operations"),
    ("routine_missing_save_this", "save this as a routine called cleanup", "routine"),
    ("routine_missing_make_this", "make this a routine", "routine"),
    ("routine_missing_remember_that", "remember that workflow as cleanup", "routine"),
    ("routine_missing_turn_this", "turn this into a routine", "routine"),
    ("routine_missing_save_that", "save that as a routine", "routine"),
    ("workflow_missing_that", "run that workflow again", "workflow"),
    ("workflow_missing_previous", "restore the previous workflow", "workflow"),
    ("workflow_missing_same", "set up the same workflow again", "workflow"),
    ("workflow_missing_this_setup", "prepare this setup", "workflow"),
    ("workflow_missing_current", "open that work context", "workflow"),
    ("task_missing_continue", "continue that", "task_continuity"),
    ("task_missing_resume", "resume the task", "task_continuity"),
    ("task_missing_where", "where were we", "task_continuity"),
    ("task_missing_next", "what should I do next", "task_continuity"),
    ("task_missing_there", "continue from there", "task_continuity"),
    ("discord_missing_payload", "send this to Baby", "discord_relay"),
    ("discord_missing_destination", "send the selected text to Discord", "discord_relay"),
    ("discord_missing_both", "send this to Discord", "discord_relay"),
    ("discord_missing_forward", "forward that to Baby", "discord_relay"),
    ("discord_missing_message", "message this on Discord", "discord_relay"),
]


NEAR_MISS_CASES = [
    ("workspace_near_philosophy", "what is a workspace in product design", "workspace_operations"),
    ("workspace_near_ideas", "workspace organization philosophy ideas", "workspace_operations"),
    ("workspace_near_theory", "compare workspace theory for teams", "workspace_operations"),
    ("workspace_near_design", "workspace UI design principles", "workspace_operations"),
    ("workspace_near_clean", "clean workspace ideas for my desk", "workspace_operations"),
    ("routine_near_daily", "give me daily routine advice", "routine"),
    ("routine_near_design", "routine design ideas for habits", "routine"),
    ("routine_near_concept", "what is a routine in programming", "routine"),
    ("routine_near_theory", "compare morning routine philosophies", "routine"),
    ("routine_near_health", "should I change my workout routine", "routine"),
    ("workflow_near_theory", "explain workflow theory", "workflow"),
    ("workflow_near_philosophy", "workflow philosophy notes", "workflow"),
    ("workflow_near_diagram", "what is a workflow diagram", "workflow"),
    ("workflow_near_essay", "write an essay about workflows", "workflow"),
    ("workflow_near_history", "history of workflow automation", "workflow"),
    ("task_near_algebra", "what are next steps in algebra", "task_continuity"),
    ("task_near_management", "task management philosophy", "task_continuity"),
    ("task_near_advice", "how do I prioritize tasks generally", "task_continuity"),
    ("task_near_concept", "what does task continuity mean", "task_continuity"),
    ("task_near_theory", "continue the explanation about planning theory", "task_continuity"),
    ("discord_near_what", "what is Discord architecture", "discord_relay"),
    ("discord_near_format", "message format for Discord docs", "discord_relay"),
    ("discord_near_bot", "explain Discord bot API rules", "discord_relay"),
    ("discord_near_history", "Discord community moderation theory", "discord_relay"),
    ("discord_near_compare", "compare Discord and Slack as products", "discord_relay"),
]


CANARY_CASES = [
    ("canary_math", "what is 7 * 8", "calculations"),
    ("canary_browser", "open https://example.com/status", "browser_destination"),
    ("canary_app", "open Notepad", "app_control"),
    ("canary_screen", "press submit", "screen_awareness"),
    ("canary_network_near", "which neural network architecture is better", "generic_provider"),
]


@pytest.mark.parametrize("case_id,prompt,expected_family,active_context,active_request_state", POSITIVE_CASES)
def test_planner_v2_expansion_positive_cases_are_authoritative(
    case_id: str,
    prompt: str,
    expected_family: str,
    active_context: dict,
    active_request_state: dict,
) -> None:
    trace = _planner_v2(prompt, active_context=active_context, active_request_state=active_request_state)

    assert trace.route_decision.routing_engine == "planner_v2", case_id
    assert trace.route_decision.selected_route_family == expected_family, case_id
    assert trace.route_decision.generic_provider_allowed is False, case_id
    assert trace.legacy_fallback_used is False, case_id
    assert trace.result_state_draft.result_state == "dry_run_ready", case_id


@pytest.mark.parametrize("case_id,prompt,expected_family", MISSING_CONTEXT_CASES)
def test_planner_v2_expansion_missing_context_clarifies_natively(case_id: str, prompt: str, expected_family: str) -> None:
    trace = _planner_v2(prompt)

    assert trace.route_decision.routing_engine == "planner_v2", case_id
    assert trace.route_decision.selected_route_family == expected_family, case_id
    assert trace.route_decision.generic_provider_allowed is False, case_id
    assert trace.legacy_fallback_used is False, case_id
    assert trace.result_state_draft.result_state in {"needs_clarification", "blocked_missing_context"}, case_id
    assert trace.context_binding.status in {"missing", "ambiguous", "stale"}, case_id


@pytest.mark.parametrize("case_id,prompt,forbidden_family", NEAR_MISS_CASES)
def test_planner_v2_expansion_near_misses_do_not_overroute(case_id: str, prompt: str, forbidden_family: str) -> None:
    trace = _planner_v2(prompt)

    assert trace.route_decision.selected_route_family != forbidden_family, case_id
    assert trace.route_decision.generic_provider_allowed is True or trace.legacy_fallback_used is True, case_id


@pytest.mark.parametrize("case_id,prompt,expected_family", CANARY_CASES)
def test_planner_v2_expansion_preserves_existing_canaries(case_id: str, prompt: str, expected_family: str) -> None:
    trace = _planner_v2(prompt)

    assert trace.route_decision.selected_route_family == expected_family, case_id
    if expected_family != "generic_provider":
        assert trace.route_decision.routing_engine == "planner_v2", case_id


@pytest.mark.parametrize(
    "prompt,expected_family,active_context,active_request_state",
    [
        ("make a workspace for this", "workspace_operations", WORKSPACE_CONTEXT, {}),
        ("save this as a routine called cleanup", "routine", {}, WORKFLOW_STATE),
        ("set up my writing environment", "workflow", {}, {}),
        ("continue that", "task_continuity", TASK_CONTEXT, {}),
        ("send this to Baby", "discord_relay", SELECTION_CONTEXT, {}),
    ],
)
def test_deterministic_planner_uses_planner_v2_for_newly_migrated_families(
    prompt: str,
    expected_family: str,
    active_context: dict,
    active_request_state: dict,
) -> None:
    decision = _deterministic(prompt, active_context=active_context, active_request_state=active_request_state)
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}

    assert decision.debug["routing_engine"] == "planner_v2", prompt
    assert winner.get("route_family") == expected_family, prompt
    assert decision.debug["planner_v2"]["legacy_fallback_used"] is False, prompt
