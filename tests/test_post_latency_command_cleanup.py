from __future__ import annotations

import pytest

from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def _plan(
    message: str,
    *,
    active_context: dict[str, object] | None = None,
    active_request_state: dict[str, object] | None = None,
    surface_mode: str = "ghost",
    active_module: str = "chartroom",
):
    return DeterministicPlanner().plan(
        message,
        session_id="post-latency-command-cleanup",
        surface_mode=surface_mode,
        active_module=active_module,
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


def _winner_tools(decision) -> tuple[str, ...]:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    planned = winner.get("planned_tools") if isinstance(winner.get("planned_tools"), list) else []
    explicit = [request.tool_name for request in decision.tool_requests]
    return tuple(dict.fromkeys([*planned, *explicit]))


def _result_state(decision) -> str:
    draft = decision.debug.get("planner_v2", {}).get("result_state_draft", {})
    return str(draft.get("result_state") or "")


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("why is my computer sluggish", "resource_diagnosis"),
        ("why is computer sluggish", "resource_diagnosis"),
        ("why is my battery draining so fast", "power_diagnosis"),
        ("why is battery draining so fast", "power_diagnosis"),
    ],
)
def test_diagnosis_taxonomy_uses_native_family_and_tool(message: str, expected_tool: str) -> None:
    decision = _plan(message)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == ("resources" if expected_tool == "resource_diagnosis" else "power")
    assert expected_tool in _winner_tools(decision)
    assert _winner_family(decision) not in {"resource_diagnosis", "power_diagnosis", "generic_provider"}


@pytest.mark.parametrize(
    ("message", "expected_tool", "argument_key", "argument_value"),
    [
        ("rename this workspace to Packaging Notes", "workspace_rename", "new_name", "Packaging Notes"),
        ("tag this workspace with packaging", "workspace_tag", "tags", ["packaging"]),
    ],
)
def test_workspace_rename_and_tag_keep_specific_workspace_tool(
    message: str,
    expected_tool: str,
    argument_key: str,
    argument_value: object,
) -> None:
    decision = _plan(message)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "workspace_operations"
    assert expected_tool in _winner_tools(decision)
    assert "workspace_assemble" not in _winner_tools(decision)
    assert _result_state(decision) in {"dry_run_ready", "planned"}
    assert decision.tool_requests
    assert decision.tool_requests[0].arguments.get(argument_key) == argument_value


@pytest.mark.parametrize(
    ("active_state", "expected_tool"),
    [
        (
            {
                "family": "workspace_operations",
                "subject": "workspace rename",
                "parameters": {
                    "source_case": "workspace_rename",
                    "tool_name": "workspace_rename",
                    "new_name": "Packaging Notes",
                    "request_stage": "preview",
                    "context_reusable": True,
                    "context_freshness": "current",
                },
            },
            "workspace_rename",
        ),
        (
            {
                "family": "workspace_operations",
                "subject": "workspace tag",
                "parameters": {
                    "source_case": "workspace_tag",
                    "tool_name": "workspace_tag",
                    "tags": ["packaging"],
                    "request_stage": "preview",
                    "context_reusable": True,
                    "context_freshness": "current",
                },
            },
            "workspace_tag",
        ),
        (
            {
                "family": "power",
                "subject": "power projection",
                "parameters": {
                    "source_case": "power_projection",
                    "tool_name": "power_projection",
                    "request_stage": "preview",
                    "context_reusable": True,
                    "context_freshness": "current",
                },
            },
            "power_projection",
        ),
    ],
)
def test_seeded_followups_preserve_prior_tool_binding(active_state: dict[str, object], expected_tool: str) -> None:
    decision = _plan("do the same thing as before", active_request_state=active_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert expected_tool in _winner_tools(decision)
    assert _winner_family(decision) != "generic_provider"
    assert _result_state(decision) in {"dry_run_ready", "planned"}


@pytest.mark.parametrize("message", ["install Firefox", "update VLC"])
def test_software_lifecycle_cross_family_stays_software_control(message: str) -> None:
    decision = _plan(f"open or diagnose this if that is the right route: {message}")

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "software_control"
    assert _winner_family(decision) not in {"app_control", "file_operation", "generic_provider"}
    assert decision.request_type == "software_control_response"


def test_no_context_correction_still_clarifies_without_provider() -> None:
    trace = PlannerV2().plan("no, use the other one")

    assert trace.route_decision.selected_route_family == "context_clarification"
    assert trace.result_state_draft.result_state in {"needs_clarification", "blocked_missing_context"}
    assert trace.route_decision.generic_provider_allowed is False


def test_legacy_route_spine_and_generic_do_not_return_for_native_cleanup_canaries() -> None:
    for message in (
        "why is my computer sluggish",
        "rename this workspace to Packaging Notes",
        "open or diagnose this if that is the right route: update VLC",
    ):
        decision = _plan(message)
        assert decision.debug["routing_engine"] == "planner_v2"
        assert decision.debug["routing_engine"] not in {"legacy_planner", "route_spine"}
        assert _winner_family(decision) != "generic_provider"
