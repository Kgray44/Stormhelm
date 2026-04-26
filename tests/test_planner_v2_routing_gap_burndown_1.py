from __future__ import annotations

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
        session_id="routing-gap-burndown-1",
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


def _result_state(decision) -> str:
    draft = decision.debug.get("planner_v2", {}).get("result_state_draft", {})
    return str(draft.get("result_state") or "")


def test_followup_with_active_browser_state_stays_native_and_uses_recent_page_context() -> None:
    active_state = {
        "family": "browser_destination",
        "subject": "browser destination",
        "parameters": {"request_stage": "preview", "source_case": "browser_destination"},
    }
    active_context = {
        "recent_entities": [
            {
                "kind": "page",
                "title": "Stormhelm docs",
                "url": "https://docs.example.com/stormhelm",
                "freshness": "current",
            }
        ]
    }

    trace = PlannerV2().plan(
        "do the same thing as before",
        active_context=active_context,
        active_request_state=active_state,
    )
    decision = _plan(
        "do the same thing as before",
        active_context=active_context,
        active_request_state=active_state,
    )

    assert trace.intent_frame.native_owner_hint == "browser_destination"
    assert trace.context_binding.status == "available"
    assert trace.context_binding.value == "https://docs.example.com/stormhelm"
    assert trace.route_decision.generic_provider_allowed is False
    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "browser_destination"


def test_followup_with_active_context_action_state_clarifies_inside_context_family_when_selection_missing() -> None:
    active_state = {
        "family": "context_action",
        "subject": "context action",
        "parameters": {"request_stage": "preview", "source_case": "context_action"},
    }

    decision = _plan("do the same thing as before", active_request_state=active_state)

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "context_action"
    assert _result_state(decision) in {"needs_clarification", "blocked_missing_context"}
    assert decision.debug["generic_provider_gate_reason"] == "native_route_candidate_present"


def test_followup_with_active_apps_state_stays_on_app_control_status() -> None:
    active_state = {
        "family": "app_control",
        "subject": "active apps",
        "parameters": {"request_stage": "preview", "source_case": "active_apps"},
    }

    decision = _plan("do the same thing as before", active_request_state=active_state)
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "app_control"
    assert "active_apps" in winner.get("planned_tools", [])


def test_unseen_active_apps_followup_variant_does_not_require_missing_app_context() -> None:
    active_state = {
        "family": "app_control",
        "subject": "active apps",
        "parameters": {"request_stage": "preview", "source_case": "active_apps"},
    }

    trace = PlannerV2().plan("show active apps again", active_request_state=active_state)

    assert trace.route_decision.routing_engine == "planner_v2"
    assert trace.route_decision.selected_route_family == "app_control"
    assert trace.context_binding.status == "available"
    assert trace.plan_draft.tool_name == "active_apps"


def test_followup_with_active_discord_state_clarifies_natively_without_provider_fallback() -> None:
    active_state = {
        "family": "discord_relay",
        "subject": "discord relay",
        "parameters": {"request_stage": "preview", "source_case": "discord_relay"},
    }
    active_context = {
        "selection": {
            "kind": "text",
            "preview": "Selected launch notes for the relay preview.",
            "value": "Selected launch notes for the relay preview.",
        }
    }

    decision = _plan(
        "do the same thing as before",
        active_context=active_context,
        active_request_state=active_state,
    )

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner_family(decision) == "discord_relay"
    assert _result_state(decision) in {"needs_clarification", "blocked_missing_context"}
    assert decision.debug["generic_provider_gate_reason"] == "native_route_candidate_present"


def test_bare_generic_followup_without_active_owner_clarifies_natively() -> None:
    decision = _plan("do the same thing as before")

    assert _winner_family(decision) == "context_clarification"
    assert decision.debug["routing_engine"] == "planner_v2"
    assert _result_state(decision) in {"needs_clarification", "blocked_missing_context"}
