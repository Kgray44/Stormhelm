from __future__ import annotations

import pytest

from stormhelm.core.orchestrator.command_eval.corpus import build_command_usability_corpus
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def _plan(
    message: str,
    *,
    active_context: dict[str, object] | None = None,
    active_request_state: dict[str, object] | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="legacy-planner-retirement-finalization",
        surface_mode="ghost",
        active_module="chartroom",
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


def _tools(decision) -> tuple[str, ...]:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    planned = winner.get("planned_tools") if isinstance(winner.get("planned_tools"), list) else []
    explicit = [request.tool_name for request in decision.tool_requests]
    return tuple(dict.fromkeys([*planned, *explicit]))


def _case(case_id: str):
    for case in build_command_usability_corpus(min_cases=1000):
        if case.case_id == case_id:
            return case
    raise AssertionError(f"missing corpus case {case_id}")


@pytest.mark.parametrize(
    ("case_id", "expected_family", "expected_tool"),
    [
        ("trusted_hook_register_canonical_00", "routine", "trusted_hook_register"),
        ("trusted_hook_execute_canonical_00", "routine", "trusted_hook_execute"),
        ("file_reader_canonical_00", "file", "file_reader"),
        ("machine_status_canonical_00", "machine", "machine_status"),
        ("system_info_near_miss_00", "machine", "system_info"),
        ("storage_diagnosis_canonical_00", "storage", "storage_diagnosis"),
        ("network_diagnosis_canonical_00", "network", "network_diagnosis"),
    ],
)
def test_retired_legacy_families_route_through_planner_v2(case_id: str, expected_family: str, expected_tool: str) -> None:
    case = _case(case_id)
    decision = _plan(case.message, active_context=case.input_context, active_request_state=case.active_request_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == expected_family
    assert _winner_family(decision) != "generic_provider"
    assert expected_tool in _tools(decision)
    assert decision.debug["generic_provider_gate_reason"] == "native_route_candidate_present"


def test_old_legacy_slice_has_no_current_legacy_or_route_spine_escape() -> None:
    migrated_prefixes = (
        "trusted_hook_register",
        "trusted_hook_execute",
        "file_reader",
        "machine_status",
        "system_info",
        "storage_diagnosis",
        "network_diagnosis",
    )
    cases = [
        case
        for case in build_command_usability_corpus(min_cases=1000)
        if case.case_id.startswith(migrated_prefixes)
    ]

    assert cases
    for case in cases:
        decision = _plan(case.message, active_context=case.input_context, active_request_state=case.active_request_state)
        assert decision.debug["routing_engine"] == "planner_v2", case.case_id
        assert _winner_family(decision) != "generic_provider", case.case_id


def test_no_context_ambiguity_and_confirmation_stay_native_clarifications() -> None:
    planner = PlannerV2()

    for prompt in ("can you handle this?", "no, use the other one", "yes, go ahead"):
        trace = planner.plan(prompt)
        assert trace.route_decision.routing_engine == "planner_v2"
        assert trace.route_decision.selected_route_family == "context_clarification"
        assert trace.route_decision.generic_provider_allowed is False


def test_confirmation_and_correction_bind_only_with_valid_prior_context() -> None:
    correction = PlannerV2().plan(
        "no, use the other one",
        active_request_state={
            "family": "browser_destination",
            "subject": "YouTube",
            "parameters": {
                "tool_name": "external_open_url",
                "previous_choice": "YouTube",
                "alternate_target": "Stormhelm docs",
                "context_freshness": "current",
            },
        },
    )
    confirmation = PlannerV2().plan(
        "yes, go ahead",
        active_request_state={
            "family": "discord_relay",
            "subject": "preview",
            "parameters": {
                "tool_name": "discord_relay_preview",
                "pending_preview": {"id": "preview-discord-1", "status": "pending"},
                "context_freshness": "current",
            },
        },
    )

    assert correction.route_decision.selected_route_family == "browser_destination"
    assert correction.route_decision.generic_provider_allowed is False
    assert confirmation.route_decision.selected_route_family == "discord_relay"
    assert confirmation.context_binding.context_type == "pending_preview"
    assert confirmation.route_decision.generic_provider_allowed is False


def test_unsupported_requests_remain_truthful_without_legacy_or_provider_win() -> None:
    decision = _plan("book me a real flight and pay for it now")

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "unsupported"
    assert _winner_family(decision) != "generic_provider"
