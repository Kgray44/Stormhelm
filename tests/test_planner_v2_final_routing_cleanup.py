from __future__ import annotations

from stormhelm.core.orchestrator.command_eval.corpus import build_command_usability_corpus
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def _plan(
    message: str,
    *,
    active_context: dict[str, object] | None = None,
    active_request_state: dict[str, object] | None = None,
    workspace_context: dict[str, object] | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="planner-v2-final-routing-cleanup",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=workspace_context or {},
        active_posture={},
        active_request_state=active_request_state or {},
        active_context=active_context or {},
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


def _case(case_id: str):
    for case in build_command_usability_corpus(min_cases=250):
        if case.case_id == case_id:
            return case
    raise AssertionError(f"missing corpus case {case_id}")


def test_file_external_followup_reuses_active_file_open_tool() -> None:
    active_state = {
        "family": "file",
        "subject": r"C:\Stormhelm\README.md",
        "parameters": {
            "source_case": "file_external",
            "tool_name": "external_open_file",
            "path": r"C:\Stormhelm\README.md",
            "request_stage": "preview",
        },
    }

    decision = _plan("do the same thing as before", active_request_state=active_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "file"
    assert "external_open_file" in _winner_tools(decision)
    assert _result_state(decision) in {"dry_run_ready", "planned"}
    assert decision.debug["generic_provider_gate_reason"] == "native_route_candidate_present"


def test_routine_execute_followup_reuses_active_routine_tool() -> None:
    active_state = {
        "family": "routine",
        "subject": "morning build check",
        "parameters": {
            "source_case": "routine_execute",
            "tool_name": "routine_execute",
            "request_stage": "preview",
        },
    }

    decision = _plan("do the same thing as before", active_request_state=active_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "routine"
    assert "routine_execute" in _winner_tools(decision)
    assert _result_state(decision) in {"dry_run_ready", "planned"}
    assert decision.debug["generic_provider_gate_reason"] == "native_route_candidate_present"


def test_task_continuity_followup_preserves_where_left_off_tool() -> None:
    active_state = {
        "family": "task_continuity",
        "subject": "docs workspace",
        "parameters": {
            "source_case": "workspace_where_left_off",
            "tool_name": "workspace_where_left_off",
            "request_stage": "preview",
        },
    }

    decision = _plan("do the same thing as before", active_request_state=active_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "task_continuity"
    assert "workspace_where_left_off" in _winner_tools(decision)
    assert "workspace_next_steps" not in _winner_tools(decision)


def test_workspace_restore_followup_preserves_restore_tool() -> None:
    active_state = {
        "family": "workspace_operations",
        "subject": "docs workspace",
        "parameters": {
            "source_case": "workspace_restore",
            "tool_name": "workspace_restore",
            "request_stage": "preview",
        },
    }

    decision = _plan("do the same thing as before", active_request_state=active_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "workspace_operations"
    assert "workspace_restore" in _winner_tools(decision)
    assert "workspace_assemble" not in _winner_tools(decision)


def test_system_info_followup_uses_canonical_system_info_tool_label() -> None:
    active_state = {
        "family": "machine",
        "subject": "system information",
        "parameters": {
            "source_case": "system_info",
            "tool_name": "system_info",
            "request_stage": "preview",
        },
    }

    decision = _plan("do the same thing as before", active_request_state=active_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "machine"
    assert "system_info" in _winner_tools(decision)
    assert "machine_status" not in _winner_tools(decision)


def test_unsupported_followup_without_native_owner_does_not_fall_to_generic_provider() -> None:
    active_state = {
        "family": "unsupported",
        "subject": "external commitment",
        "parameters": {"source_case": "unsupported", "request_stage": "preview"},
    }

    decision = _plan("do the same thing as before", active_request_state=active_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) in {"context_clarification", "unsupported"}
    assert _winner_family(decision) != "generic_provider"
    assert _result_state(decision) in {"needs_clarification", "blocked_missing_context", "unsupported"}


def test_browser_near_miss_corpus_accepts_context_clarification_policy() -> None:
    case = _case("browser_destination_near_miss_00")

    assert case.expected.route_family == "context_clarification"
    assert case.expected.subsystem == "context"
    assert case.expected.tools == ()
    assert case.expected.clarification == "expected"

    decision = _plan(case.message)
    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "context_clarification"
    assert _result_state(decision) in {"needs_clarification", "blocked_missing_context"}


def test_file_path_external_open_does_not_route_to_calculations() -> None:
    decision = _plan(r"open C:\Stormhelm\README.md externally")

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "file"
    assert "external_open_file" in _winner_tools(decision)
    assert _winner_family(decision) != "calculations"


def test_system_settings_open_routes_to_system_control_not_desktop_search() -> None:
    decision = _plan("open bluetooth settings")

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "system_control"
    assert "system_control" in _winner_tools(decision)
    assert _winner_family(decision) != "desktop_search"


def test_system_direct_command_uses_system_info_label() -> None:
    decision = _plan("/system")

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "machine"
    assert "system_info" in _winner_tools(decision)


def test_shell_direct_command_is_safe_preflight() -> None:
    decision = _plan("/shell dir")

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "terminal"
    assert "shell_command" in _winner_tools(decision)
    assert decision.tool_requests
    assert decision.tool_requests[0].arguments.get("dry_run") is True
