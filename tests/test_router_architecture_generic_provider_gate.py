from __future__ import annotations

from stormhelm.core.orchestrator.route_spine import RouteSpine


def _route(message: str, *, active_context: dict[str, object] | None = None):
    return RouteSpine().route(
        message,
        active_context=active_context or {},
        active_request_state={},
        recent_tool_results=[],
    )


def test_generic_provider_is_blocked_when_native_family_owns_missing_context() -> None:
    cases = [
        ("open that website", "browser_destination", "destination_context"),
        ("show that document again", "file", "file_context"),
        ("use the highlighted bit", "context_action", "context"),
        ("press submit", "screen_awareness", "visible_screen"),
        ("send this there", "discord_relay", "payload"),
        ("save this as a routine called cleanup", "routine", "steps_or_recent_action"),
        ("approve it", "trust_approvals", "approval_object"),
        ("rename it", "file_operation", "file_context"),
        ("show me the arithmetic for that", "calculations", "calculation_context"),
    ]
    for prompt, family, missing_slot in cases:
        decision = _route(prompt)

        assert decision.winner.route_family == family, prompt
        assert decision.clarification_needed is True, prompt
        assert missing_slot in decision.missing_preconditions, prompt
        assert decision.generic_provider_allowed is False, prompt
        assert decision.generic_provider_reason == "native_route_candidate_present", prompt


def test_generic_provider_remains_available_for_true_conceptual_near_misses() -> None:
    cases = [
        "compare neural network model architectures",
        "what is selected text in HTML",
        "explain terminal velocity",
        "write ideas for a clean workspace",
        "what is a daily routine",
    ]
    for prompt in cases:
        decision = _route(prompt)

        assert decision.winner.route_family == "generic_provider", prompt
        assert decision.generic_provider_allowed is True, prompt
        assert decision.clarification_needed is False, prompt


def test_near_miss_pressure_does_not_break_native_clear_owners() -> None:
    assert _route("which wifi am I on").winner.route_family in {"network", "watch_runtime"}
    assert _route("quit Notepad").winner.route_family == "app_control"
    assert _route("uninstall Notepad").winner.route_family == "software_control"
    assert _route("open https://example.com").winner.route_family == "browser_destination"
    assert _route(r"read C:\Stormhelm\README.md").winner.route_family == "file"

