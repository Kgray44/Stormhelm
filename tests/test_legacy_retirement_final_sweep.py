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
        session_id="legacy-retirement-final-sweep",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state=active_request_state or {},
        active_context=active_context or {},
        recent_tool_results=[],
    )


def _case(case_id: str):
    for case in build_command_usability_corpus(min_cases=1000):
        if case.case_id == case_id:
            return case
    raise AssertionError(f"missing corpus case {case_id}")


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


@pytest.mark.parametrize(
    "case_id",
    [
        "saved_locations_canonical_00",
        "saved_locations_casual_00",
        "saved_locations_shorthand_00",
        "saved_locations_typo_00",
        "saved_locations_slang_00",
        "saved_locations_near_miss_00",
        "saved_locations_negative_00",
        "saved_locations_unsupported_probe_00",
        "saved_locations_cross_family_00",
    ],
)
def test_saved_locations_variants_are_planner_v2_location(case_id: str) -> None:
    case = _case(case_id)
    decision = _plan(case.message, active_context=case.input_context, active_request_state=case.active_request_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "location"
    assert _winner_family(decision) != "generic_provider"
    assert "saved_locations" in _tools(decision)
    assert decision.debug["generic_provider_gate_reason"] == "native_route_candidate_present"


@pytest.mark.parametrize("message", ["show my wrkspaces", "uhhh show my wrkspaces -- quick quick"])
def test_workspace_list_typo_routes_natively_or_clarifies_without_provider(message: str) -> None:
    decision = _plan(message)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "workspace_operations"
    assert _winner_family(decision) != "generic_provider"
    assert "workspace_list" in _tools(decision)


@pytest.mark.parametrize(
    "case_id",
    [
        "system_info_canonical_00",
        "system_info_casual_00",
        "system_info_polite_00",
        "system_info_shorthand_00",
        "system_info_indirect_00",
        "system_info_question_00",
        "system_info_command_mode_00",
    ],
)
def test_system_slash_variants_do_not_use_legacy(case_id: str) -> None:
    case = _case(case_id)
    decision = _plan(case.message, active_context=case.input_context, active_request_state=case.active_request_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert decision.debug["routing_engine"] != "legacy_planner"
    assert decision.debug["routing_engine"] != "route_spine"
    assert _winner_family(decision) == "machine"
    assert "system_info" in _tools(decision)


@pytest.mark.parametrize(
    "case_id",
    [
        "file_reader_canonical_00",
        "file_reader_casual_00",
        "file_reader_polite_00",
        "file_reader_shorthand_00",
        "file_reader_indirect_00",
        "file_reader_question_00",
        "file_reader_command_mode_00",
    ],
)
def test_read_slash_variants_do_not_use_legacy(case_id: str) -> None:
    case = _case(case_id)
    decision = _plan(case.message, active_context=case.input_context, active_request_state=case.active_request_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert decision.debug["routing_engine"] != "legacy_planner"
    assert decision.debug["routing_engine"] != "route_spine"
    assert _winner_family(decision) == "file"
    assert "file_reader" in _tools(decision)


def test_note_cross_family_slash_does_not_route_to_desktop_search() -> None:
    case = _case("notes_write_cross_family_00")
    decision = _plan(case.message, active_context=case.input_context, active_request_state=case.active_request_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "notes"
    assert _winner_family(decision) != "desktop_search"
    assert "notes_write" in _tools(decision)


def test_context_binding_canaries_remain_native_and_non_provider() -> None:
    planner = PlannerV2()

    no_context = planner.plan("no, use the other one")
    correction = planner.plan(
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
    confirmation = planner.plan(
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

    assert no_context.route_decision.selected_route_family == "context_clarification"
    assert no_context.route_decision.generic_provider_allowed is False
    assert correction.route_decision.selected_route_family == "browser_destination"
    assert correction.route_decision.generic_provider_allowed is False
    assert confirmation.route_decision.selected_route_family == "discord_relay"
    assert confirmation.route_decision.generic_provider_allowed is False
