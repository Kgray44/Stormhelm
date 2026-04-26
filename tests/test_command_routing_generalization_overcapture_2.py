from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _active_selection() -> dict[str, object]:
    return {
        "selection": {
            "kind": "text",
            "value": "Selected text for second generalization and overcapture tests.",
            "preview": "Selected text for second generalization and overcapture tests.",
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
        session_id="generalization-overcapture-2",
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
    if family == "screen_awareness":
        return "screen_awareness"
    if family in {"network", "app_control"}:
        return "system"
    if family == "browser_destination":
        return "browser"
    return domain


def _tool_names(decision) -> list[str]:
    return [request.tool_name for request in decision.tool_requests]


def test_network_status_owns_wifi_status_without_capturing_conceptual_networks() -> None:
    positives = [
        "which wifi am I on",
        "which wi-fi network am I using",
        "what wi-fi am I connected to",
        "tell me the current Wi-Fi network",
        "show my wifi connection name",
        "what wireless network is this laptop on",
        "which SSID am I connected to",
        "pls show what wi-fi im on",
    ]
    for prompt in positives:
        decision = _plan(prompt)

        assert _winner_family(decision) == "network", prompt
        assert _winner_subsystem(decision) == "system", prompt
        assert _tool_names(decision) == ["network_status"], prompt

    near_misses = [
        "compare neural network architectures",
        "which neural network is better for images",
        "explain wireless network design",
        "network architecture patterns",
    ]
    for prompt in near_misses:
        decision = _plan(prompt)

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt


def test_screen_action_owns_named_controls_without_blind_bare_deictics() -> None:
    positives = [
        "press submit",
        "click submit",
        "tap submit",
        "press OK",
        "click next",
        "tap save",
        "press cancel",
        "pls click that menu",
    ]
    for prompt in positives:
        decision = _plan(prompt)

        assert _winner_family(decision) == "screen_awareness", prompt
        assert _winner_subsystem(decision) == "screen_awareness", prompt
        assert _tool_names(decision) == [], prompt

    near_misses = [
        "explain submit button design",
        "submit a proposal outline",
        "press coverage summary",
        "what does next mean in UX",
    ]
    for prompt in near_misses:
        decision = _plan(prompt)

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt

    for prompt in ["press it", "click that", "open this", "open that"]:
        decision = _plan(prompt)

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt


def test_active_app_status_beats_resource_right_now_overcapture() -> None:
    positives = [
        "which apps are running right now",
        "what programs are active right now",
        "list running applications",
        "show active apps",
        "what apps are open",
        "which programs are open",
    ]
    for prompt in positives:
        decision = _plan(prompt)

        assert _winner_family(decision) == "app_control", prompt
        assert _winner_subsystem(decision) == "system", prompt
        assert _tool_names(decision) == ["active_apps"], prompt

    near_misses = [
        "what apps should I build first",
        "running app marketing ideas",
        "open apps concept in mobile UX",
        "which application architecture should I use",
    ]
    for prompt in near_misses:
        decision = _plan(prompt)

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt


def test_browser_deictic_website_clarifies_and_does_not_launch_fake_app() -> None:
    missing_context = [
        "open that website",
        "open that site",
        "show that page",
        "open the website from before",
        "bring up that link",
    ]
    for prompt in missing_context:
        decision = _plan(prompt)

        assert _winner_family(decision) == "browser_destination", prompt
        assert _winner_subsystem(decision) == "browser", prompt
        assert decision.request_type == "clarification_request", prompt
        assert decision.clarification_reason is not None
        assert "destination_context" in decision.clarification_reason.missing_slots
        assert _tool_names(decision) == [], prompt

    concrete_destinations = [
        "open example.com",
        "open docs.python.org in browser",
        "bring up wikipedia.org",
    ]
    for prompt in concrete_destinations:
        decision = _plan(prompt)

        assert _winner_family(decision) == "browser_destination", prompt
        assert _tool_names(decision) == ["external_open_url"], prompt

    for prompt in ["what is a website", "open website design principles", "website app ideas"]:
        decision = _plan(prompt)

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt

    for prompt in ["quit Notepad", "focus Notepad"]:
        decision = _plan(prompt)

        assert _winner_family(decision) == "app_control", prompt
        assert _tool_names(decision) == ["app_control"], prompt


def test_comparison_route_requires_native_comparison_targets() -> None:
    for prompt in [
        "compare neural network architectures",
        "compare neural networks",
        "compare React and Vue",
        "compare startup pricing models",
    ]:
        decision = _plan(prompt)

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt

    native_cases = [
        "compare these two files",
        "compare this file with that one",
        "compare the selected documents",
        "diff these documents",
    ]
    for prompt in native_cases:
        decision = _plan(prompt, active_context=_active_selection())

        assert _winner_family(decision) == "comparison", prompt
