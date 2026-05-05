from __future__ import annotations

import pytest

from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _plan(message: str):
    return DeterministicPlanner().plan(
        message,
        session_id="baseline-sanity-provider-route-selection",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state={},
        active_context={},
        recent_tool_results=[],
    )


def _winner_family(decision) -> str:  # noqa: ANN001
    assert decision.route_state is not None
    return str(decision.route_state.to_dict()["winner"]["route_family"])


def _generic_provider_candidate(decision):  # noqa: ANN001
    assert decision.route_state is not None
    for candidate in decision.route_state.to_dict().get("candidates", []):
        if candidate.get("route_family") == "generic_provider":
            return candidate
    return None


KRAKEN_PROVIDER_HIJACK_CASES = [
    pytest.param("hot_calc_11", "convert 2.2k to ohms", {"calculations"}, id="calculation-engineering-suffix"),
    pytest.param("screen_02", "What window am I in?", {"screen_awareness", "context_clarification"}, id="screen-window"),
    pytest.param("screen_04", "What should I click?", {"screen_awareness", "context_clarification"}, id="screen-click-guidance"),
    pytest.param("screen_05", "Is that warning gone?", {"screen_awareness", "context_clarification"}, id="screen-warning-gone"),
    pytest.param("screen_07", "Describe the current window.", {"screen_awareness", "context_clarification"}, id="screen-describe-window"),
    pytest.param("screen_08", "What app is focused?", {"screen_awareness", "context_clarification"}, id="screen-focused-app"),
    pytest.param("screen_12", "Is the old installer warning still visible?", {"screen_awareness", "context_clarification"}, id="screen-stale-warning"),
    pytest.param("browser_obs_14", "Where should I click to log in?", {"screen_awareness", "context_clarification"}, id="browser-click-guidance"),
    pytest.param("browser_obs_16", "What field should I fill out next?", {"screen_awareness", "context_clarification"}, id="browser-field-guidance"),
    pytest.param("browser_obs_17", "Did the page finish loading?", {"screen_awareness", "context_clarification"}, id="browser-page-load"),
    pytest.param("browser_obs_20", "Tell me the current browser URL.", {"watch_runtime"}, id="browser-current-url"),
    pytest.param("browser_obs_23", "Is this the login page?", {"screen_awareness", "context_clarification"}, id="browser-login-page"),
    pytest.param("provider_native_08", "stop talking", {"voice_control"}, id="voice-stop-talking"),
    pytest.param("provider_native_15", "what window am I in?", {"screen_awareness"}, id="provider-native-screen-window"),
    pytest.param("truth_03", "Did the browser page load?", {"screen_awareness", "context_clarification"}, id="truth-browser-load"),
    pytest.param("truth_04", "Is the warning gone?", {"screen_awareness", "context_clarification"}, id="truth-warning-gone"),
    pytest.param("truth_09", "Is this definitely a JST-XH connector?", {"camera_awareness", "context_clarification"}, id="truth-camera-connector"),
    pytest.param("truth_12", "Did the page finish loading?", {"screen_awareness", "context_clarification"}, id="truth-page-load"),
    pytest.param("truth_13", "Is that warning gone now?", {"screen_awareness", "context_clarification"}, id="truth-warning-gone-now"),
    pytest.param("truth_14", "Did the download start?", {"screen_awareness", "context_clarification"}, id="truth-download-start"),
    pytest.param("truth_16", "Is the screenshot current?", {"screen_awareness", "context_clarification"}, id="truth-screenshot-current"),
    pytest.param("truth_20", "Did the approval go through?", {"trust_approvals", "context_clarification"}, id="truth-approval-status"),
]


@pytest.mark.parametrize(("case_id", "prompt", "allowed_families"), KRAKEN_PROVIDER_HIJACK_CASES)
def test_baseline_hijack_prompts_do_not_select_generic_provider(case_id: str, prompt: str, allowed_families: set[str]) -> None:
    decision = _plan(prompt)
    winner = _winner_family(decision)

    assert winner != "generic_provider", case_id
    assert winner in allowed_families, case_id
    provider_candidate = _generic_provider_candidate(decision)
    if provider_candidate is not None:
        assert "native_route_candidate_present" in provider_candidate.get("disqualifiers", []), case_id


@pytest.mark.parametrize(
    ("prompt", "expected_family"),
    [
        ("open github.com", "browser_destination"),
        ("install Git", "software_control"),
        ("check if Python is installed", "software_control"),
        ("send this to Baby", "discord_relay"),
        ("approve it", "trust_approvals"),
        ("what is in front of me?", "camera_awareness"),
    ],
)
def test_native_protection_canaries_do_not_select_generic_provider(prompt: str, expected_family: str) -> None:
    decision = _plan(prompt)
    winner = _winner_family(decision)

    assert winner != "generic_provider"
    assert winner == expected_family
