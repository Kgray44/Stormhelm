from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _active_selection() -> dict[str, object]:
    return {
        "selection": {
            "kind": "text",
            "value": "Selected text for generalization and overcapture tests.",
            "preview": "Selected text for generalization and overcapture tests.",
        }
    }


def _plan(
    message: str,
    *,
    active_context: dict[str, object] | None = None,
    active_request_state: dict[str, object] | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="generalization-overcapture",
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


def _tool_names(decision) -> list[str]:
    return [request.tool_name for request in decision.tool_requests]


def test_discord_relay_synonyms_route_natively_without_prompt_hardcoding() -> None:
    cases = [
        "can you relay this to Baby in Discord",
        "forward this to Baby via Discord",
        "pass this along to Baby on Discord",
        "DM this to Baby in Discord",
        "relay the selected text to Baby on Discord",
        "send current selection to Baby through Discord",
        "pls forward this to Baby on Discord",
    ]

    for prompt in cases:
        decision = _plan(prompt, active_context=_active_selection())

        assert _winner_family(decision) == "discord_relay", prompt
        assert _tool_names(decision) == [], prompt


def test_discord_near_misses_and_missing_targets_do_not_overroute() -> None:
    near_misses = [
        "explain Discord relay bots",
        "what is a relay channel in Discord",
        "Baby names in Discord communities are funny",
    ]
    for prompt in near_misses:
        decision = _plan(prompt, active_context=_active_selection())

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt

    for prompt in ["relay this on Discord", "send this through Discord"]:
        decision = _plan(prompt, active_context=_active_selection())

        assert _winner_family(decision) == "discord_relay", prompt
        assert decision.request_type == "clarification_request", prompt
        assert decision.clarification_reason is not None
        assert "destination" in decision.clarification_reason.missing_slots


def test_selected_text_context_action_beats_app_control_with_active_context() -> None:
    cases = [
        "please open the selected text",
        "open selected text",
        "show the highlighted text",
        "open the selection",
        "bring up the selected text",
        "show what I highlighted",
        "pls show selected text",
    ]

    for prompt in cases:
        decision = _plan(prompt, active_context=_active_selection())

        assert _winner_family(decision) == "context_action", prompt
        assert _tool_names(decision) == ["context_action"], prompt


def test_selected_text_near_misses_and_missing_context_do_not_launch_apps() -> None:
    for prompt in [
        "what is selected text in HTML",
        "explain selection bias",
        "open selection criteria examples",
    ]:
        decision = _plan(prompt, active_context=_active_selection())

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt

    for prompt in ["open selected text", "show the highlighted text"]:
        decision = _plan(prompt)

        assert _winner_family(decision) == "context_action", prompt
        assert decision.request_type == "clarification_request", prompt
        assert decision.clarification_reason is not None
        assert "context" in decision.clarification_reason.missing_slots
        assert _tool_names(decision) == [], prompt


def test_network_status_requires_device_connectivity_intent() -> None:
    positives = [
        "are we online",
        "is my internet connected",
        "show wifi signal",
        "what network am I on",
        "is this machine connected right now",
        "pls check if the laptop is online",
    ]
    for prompt in positives:
        decision = _plan(prompt)

        assert _winner_family(decision) == "network", prompt
        assert _tool_names(decision) == ["network_status"], prompt

    for prompt in [
        "explain network effects in startups",
        "what is a neural network",
        "draw a network graph conceptually",
        "networking advice for founders",
    ]:
        decision = _plan(prompt)

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt


def test_bare_deictic_open_does_not_become_screen_action_without_context() -> None:
    for prompt in ["open that", "open it", "click that", "press it"]:
        decision = _plan(prompt)

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt

    for prompt in ["click that button", "open that dropdown", "press continue"]:
        decision = _plan(prompt)

        assert _winner_family(decision) == "screen_awareness", prompt
