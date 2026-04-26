from __future__ import annotations

from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _recent_calculation_context() -> dict[str, object]:
    return {
        "recent_context_resolutions": [
            {
                "kind": "calculation",
                "result": {"expression": "18 / 3", "display_result": "6"},
                "trace": {"extracted_expression": "18 / 3"},
            }
        ]
    }


def _plan(
    message: str,
    *,
    active_context: dict[str, object] | None = None,
    active_request_state: dict[str, object] | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="readiness-pass-3",
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


def _winner_subsystem(decision) -> str:
    family = _winner_family(decision)
    domain = str(decision.structured_query.domain if decision.structured_query is not None else "")
    if family == "generic_provider":
        return "provider"
    if family == "calculations":
        return "calculations"
    return domain


def _tool_names(decision) -> list[str]:
    return [request.tool_name for request in decision.tool_requests]


def _case(case_id: str):
    corpus = build_command_usability_corpus(min_cases=1000)
    matches = [case for case in corpus if case.case_id == case_id]
    assert len(matches) == 1
    return matches[0]


def test_embedded_math_expressions_own_noisy_cross_family_wrappers() -> None:
    exact_repros = [
        "open or diagnose this if that is the right route: what is 18 / 3",
        "almost what is 18 / 3, but not exactly",
        "can you magically what is 18 / 3 without any local evidence?",
    ]
    unseen_positives = [
        "quick check: what is 42 / 7",
        "route this safely: compute 9 * 4",
        "not an app, just calculate 144 / 12",
        "before anything else, evaluate 5 + 8",
        "pls just calc 81 / 9",
        "diagnose the route: what's 64 / 8",
    ]

    for prompt in [*exact_repros, *unseen_positives]:
        decision = _plan(prompt)

        assert _winner_family(decision) == "calculations", prompt
        assert _winner_subsystem(decision) == "calculations", prompt
        assert _tool_names(decision) == [], prompt


def test_calculation_near_misses_do_not_get_overcaptured() -> None:
    near_misses = [
        "what is division?",
        "compare neural network architectures",
        "open Calculator",
        "diagnose why my math homework is hard",
        "calculate the vibes of this paragraph",
    ]

    for prompt in near_misses:
        decision = _plan(prompt)

        assert _winner_family(decision) != "calculations", prompt


def test_fresh_calculation_context_binds_followups_without_provider_fallback() -> None:
    active_context = _recent_calculation_context()
    prompts = [
        "do the same calculation again",
        "same thing as before",
        "use that result again",
        "yes, go ahead with that preview",
        "no, use the other one",
        "use this for that",
        "show the steps",
    ]

    for prompt in prompts:
        decision = _plan(prompt, active_context=active_context)

        assert _winner_family(decision) == "calculations", prompt
        assert _winner_subsystem(decision) == "calculations", prompt
        assert _tool_names(decision) == [], prompt


def test_missing_calculation_followup_context_clarifies_natively() -> None:
    active_request_state = {
        "family": "calculations",
        "subject": "calculation",
        "parameters": {"request_stage": "preview"},
    }
    prompts = [
        "do the same thing as before",
        "continue that calculation",
        "yes, go ahead with that preview",
        "no, use the other one",
    ]

    for prompt in prompts:
        decision = _plan(prompt, active_request_state=active_request_state)

        assert _winner_family(decision) == "calculations", prompt
        assert decision.request_type == "clarification_request", prompt
        assert decision.clarification_reason is not None
        assert "calculation_context" in decision.clarification_reason.missing_slots
        assert _tool_names(decision) == [], prompt


def test_command_eval_approval_expectations_match_dry_run_policy() -> None:
    assert _case("discord_relay_canonical_00").expected.approval == "expected_or_preview"
    assert _case("discord_relay_indirect_00").expected.approval == "expected_or_preview"

    assert _case("system_control_canonical_00").expected.approval == "not_expected"
    assert _case("system_control_command_mode_00").expected.approval == "not_expected"

    assert _case("software_control_install_canonical_00").expected.approval == "expected_or_preview"
    assert _case("software_control_update_canonical_00").expected.approval == "expected_or_preview"
    assert _case("browser_deck_canonical_00").expected.approval == "not_expected"
    assert _case("file_deck_canonical_00").expected.approval == "not_expected"
