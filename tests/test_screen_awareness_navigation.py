from __future__ import annotations

from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem


class FakeObservationProbe:
    def __init__(self, *, focused_window: dict[str, object] | None = None, windows: list[dict[str, object]] | None = None) -> None:
        self._focused_window = focused_window
        self._windows = list(windows or ([focused_window] if focused_window else []))

    def window_status(self) -> dict[str, object]:
        return {
            "focused_window": self._focused_window,
            "windows": list(self._windows),
            "monitors": [{"index": 1, "device_name": "\\\\.\\DISPLAY1", "is_primary": True}],
        }


def _phase3_screen_config(temp_config):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase3"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    return temp_config.screen_awareness


def _focused_browser_window(title: str, *, window_handle: int) -> dict[str, object]:
    return {
        "process_name": "chrome",
        "window_title": title,
        "window_handle": window_handle,
        "pid": 4000 + window_handle,
        "monitor_index": 1,
        "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "is_focused": True,
        "minimized": False,
    }


def _build_phase3_subsystem(temp_config, *, title: str, window_handle: int) -> object:
    return build_screen_awareness_subsystem(
        _phase3_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_browser_window(title, window_handle=window_handle),
        ),
    )


def test_phase3_guided_navigation_recommends_next_button_from_strong_current_context(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase3_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Release Form - Google Chrome",
                "window_handle": 601,
                "pid": 4010,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what should I click next?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-1", "title": "Release Form"},
            "active_item": {
                "itemId": "field-email",
                "title": "Release email",
                "kind": "text-field",
                "focused": True,
                "selected": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                },
                {
                    "itemId": "button-cancel",
                    "title": "Cancel",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                },
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "ready"
    assert navigation.winning_candidate is not None
    assert navigation.winning_candidate.label == "Continue"
    assert navigation.guidance is not None
    assert "continue" in navigation.guidance.instruction.lower()
    assert response.telemetry["navigation"]["outcome"] == "ready"
    assert response.telemetry["navigation"]["winning_candidate_id"] == "button-continue"
    assert "clicked" not in response.assistant_response.lower()


def test_phase3_guided_navigation_reuses_phase2_grounded_field_for_target_selection(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase3_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "API Settings - Google Chrome",
                "window_handle": 611,
                "pid": 4020,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="which field am I supposed to use?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-2", "title": "API Settings"},
            "active_item": {
                "itemId": "field-token",
                "title": "API token",
                "kind": "text-field",
                "focused": True,
                "selected": True,
            },
            "opened_items": [
                {"itemId": "field-token", "title": "API token", "kind": "text-field", "focused": True, "selected": True},
                {"itemId": "field-name", "title": "Workspace name", "kind": "text-field"},
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    grounding = response.analysis.grounding_result
    navigation = response.analysis.navigation_result

    assert grounding is not None
    assert grounding.winning_target is not None
    assert navigation is not None
    assert navigation.winning_candidate is not None
    assert navigation.winning_candidate.candidate_id == grounding.winning_target.candidate_id
    assert navigation.context.grounding_reused is True
    assert response.telemetry["navigation"]["grounding_reused"] is True
    assert "focused" in response.assistant_response.lower() or "grounded" in response.assistant_response.lower()


def test_phase3_guided_navigation_preserves_ambiguity_for_multiple_plausible_next_buttons(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase3_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Shipping Wizard - Google Chrome",
                "window_handle": 621,
                "pid": 4030,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what should I click next?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-3", "title": "Shipping Wizard"},
            "active_item": {"itemId": "wizard-page", "title": "Shipping Wizard", "kind": "settings-page"},
            "opened_items": [
                {"itemId": "button-continue-top", "title": "Continue", "kind": "button", "pane": "toolbar", "enabled": True},
                {"itemId": "button-continue-bottom", "title": "Continue", "kind": "button", "pane": "footer", "enabled": True},
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "ambiguous"
    assert navigation.winning_candidate is None
    assert navigation.clarification_need is not None
    assert navigation.clarification_need.needed is True
    assert response.telemetry["navigation"]["outcome"] == "ambiguous"
    assert "multiple plausible next targets" in response.assistant_response.lower() or "which one" in response.assistant_response.lower()


def test_phase3_guided_navigation_requests_clarification_when_no_next_step_is_justified(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase3_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "PyInstaller Docs - Google Chrome",
                "window_handle": 631,
                "pid": 4040,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="where do I go from here?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "unresolved"
    assert navigation.clarification_need is not None
    assert navigation.clarification_need.needed is True
    assert response.telemetry["navigation"]["outcome"] == "unresolved"
    assert "can't justify a single next step" in response.assistant_response.lower()


def test_phase3_guided_navigation_detects_visible_blocker_without_overclaiming(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase3_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Permission Setup - Google Chrome",
                "window_handle": 641,
                "pid": 4050,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="I'm stuck, what do I do now?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-5", "title": "Permission Setup"},
            "active_item": {"itemId": "permissions-page", "title": "Permission Setup", "kind": "settings-page"},
            "opened_items": [
                {"itemId": "button-continue", "title": "Continue", "kind": "button", "pane": "footer", "enabled": False},
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "blocked"
    assert navigation.blocker is not None
    assert "disabled" in navigation.blocker.summary.lower()
    assert navigation.recovery_hint is not None
    assert response.telemetry["navigation"]["blocker_present"] is True
    assert "blocking" in response.assistant_response.lower()
    assert "clicked" not in response.assistant_response.lower()


def test_phase3_guided_navigation_detects_likely_wrong_page_from_visible_message(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase3_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Account Overview - Google Chrome",
                "window_handle": 651,
                "pid": 4060,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="is this the right page?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-6", "title": "Account Overview"},
            "active_item": {"itemId": "account-overview", "title": "Account Overview", "kind": "settings-page"},
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "Open Security settings to continue.",
                "preview": "Open Security settings to continue.",
            },
            "clipboard": {},
        },
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "wrong_page"
    assert navigation.recovery_hint is not None
    assert "security" in navigation.recovery_hint.summary.lower()
    assert response.telemetry["navigation"]["wrong_page"] is True
    assert "wrong place" in response.assistant_response.lower() or "wrong page" in response.assistant_response.lower()


def test_phase3_guided_navigation_telemetry_reports_native_first_truthfully(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase3_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Release Form - Google Chrome",
                "window_handle": 661,
                "pid": 4070,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="which field am I supposed to use?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-7", "title": "Release Form"},
            "active_item": {"itemId": "field-email", "title": "Release email", "kind": "text-field", "focused": True, "selected": True},
            "opened_items": [{"itemId": "field-email", "title": "Release email", "kind": "text-field", "focused": True, "selected": True}],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    telemetry = response.telemetry["navigation"]

    assert telemetry["requested"] is True
    assert telemetry["outcome"] == "ready"
    assert telemetry["dominant_channel"] in {"workspace_context", "native_observation"}
    assert "visual_provider" not in telemetry["provenance_channels"]
    assert telemetry["grounding_reused"] is True
    assert telemetry["ranked_candidates"][0]["based_on_grounding"] is True
    assert response.telemetry["grounding_visual_augmentation"]["used"] is False


def test_phase31_guided_navigation_ignores_unrelated_warning_text_when_next_step_is_clear(temp_config) -> None:
    subsystem = _build_phase3_subsystem(
        temp_config,
        title="Profile Setup - Google Chrome",
        window_handle=701,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what should I click next?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-31-1", "title": "Profile Setup"},
            "active_item": {
                "itemId": "field-display-name",
                "title": "Display name",
                "kind": "text-field",
                "focused": True,
                "selected": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "Warning: your name will be visible to teammates.",
                "preview": "Warning: your name will be visible to teammates.",
            },
            "clipboard": {},
        },
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "ready"
    assert navigation.blocker is None
    assert navigation.winning_candidate is not None
    assert navigation.winning_candidate.label == "Continue"
    assert response.telemetry["navigation"]["blocker_present"] is False
    assert "blocking the next step" not in response.assistant_response.lower()


def test_phase31_guided_navigation_prefers_enabled_alternate_path_over_disabled_candidate(temp_config) -> None:
    subsystem = _build_phase3_subsystem(
        temp_config,
        title="Identity Setup - Google Chrome",
        window_handle=702,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="I'm stuck, what do I do now?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-31-2", "title": "Identity Setup"},
            "active_item": {
                "itemId": "field-email",
                "title": "Work email",
                "kind": "text-field",
                "focused": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": False,
                },
                {
                    "itemId": "button-continue-email",
                    "title": "Continue with email",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                },
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "ready"
    assert navigation.blocker is None
    assert navigation.winning_candidate is not None
    assert navigation.winning_candidate.label == "Continue with email"
    assert response.telemetry["navigation"]["outcome"] == "ready"
    assert response.telemetry["navigation"]["blocker_present"] is False


def test_phase31_guided_navigation_does_not_claim_wrong_page_from_help_sidebar_text(temp_config) -> None:
    subsystem = _build_phase3_subsystem(
        temp_config,
        title="Account Overview - Google Chrome",
        window_handle=703,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="is this the right page?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-31-3", "title": "Account Overview"},
            "active_item": {
                "itemId": "account-overview",
                "title": "Account Overview",
                "kind": "settings-page",
            },
            "opened_items": [
                {
                    "itemId": "help-sidebar",
                    "title": "Help: Open Security settings to continue.",
                    "kind": "message",
                    "pane": "sidebar",
                }
            ],
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "Help: Open Security settings to continue.",
                "preview": "Help: Open Security settings to continue.",
            },
            "clipboard": {},
        },
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "unresolved"
    assert navigation.clarification_need is not None
    assert response.telemetry["navigation"]["wrong_page"] is False
    assert "wrong place" not in response.assistant_response.lower()


def test_phase31_guided_navigation_prefers_modal_detour_candidate_over_background_next_step(temp_config) -> None:
    subsystem = _build_phase3_subsystem(
        temp_config,
        title="Sign In - Google Chrome",
        window_handle=704,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what should I click next?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-31-4", "title": "Sign In"},
            "active_item": {"itemId": "signin-page", "title": "Sign in", "kind": "settings-page"},
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                },
                {
                    "itemId": "signin-modal",
                    "title": "Choose sign-in method",
                    "kind": "dialog",
                    "pane": "modal",
                    "focused": True,
                },
                {
                    "itemId": "button-use-browser",
                    "title": "Use browser instead",
                    "kind": "button",
                    "pane": "modal",
                    "enabled": True,
                },
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "ready"
    assert navigation.winning_candidate is not None
    assert navigation.winning_candidate.label == "Use browser instead"
    assert navigation.blocker is None
    assert "modal" in (navigation.guidance.look_for or "").lower()


def test_phase31_guided_navigation_blocks_grounding_reuse_when_modal_detour_changes_immediate_step(temp_config) -> None:
    subsystem = _build_phase3_subsystem(
        temp_config,
        title="API Settings - Google Chrome",
        window_handle=705,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="which field am I supposed to use?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-31-5", "title": "API Settings"},
            "active_item": {
                "itemId": "field-token",
                "title": "API token",
                "kind": "text-field",
                "focused": True,
                "selected": True,
            },
            "opened_items": [
                {
                    "itemId": "field-token",
                    "title": "API token",
                    "kind": "text-field",
                    "focused": True,
                    "selected": True,
                },
                {
                    "itemId": "permission-modal",
                    "title": "Permission required",
                    "kind": "dialog",
                    "pane": "modal",
                },
                {
                    "itemId": "button-allow",
                    "title": "Allow",
                    "kind": "button",
                    "pane": "modal",
                    "enabled": True,
                },
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "blocked"
    assert navigation.winning_candidate is None
    assert navigation.blocker is not None
    assert "permission" in navigation.blocker.summary.lower()
    assert response.telemetry["navigation"]["grounding_reused"] is False
    assert "api token" not in response.assistant_response.lower()


def test_phase31_guided_navigation_refuses_weak_next_step_without_anchor(temp_config) -> None:
    subsystem = _build_phase3_subsystem(
        temp_config,
        title="Setup Wizard - Google Chrome",
        window_handle=706,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what do I click next?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-31-6", "title": "Setup Wizard"},
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                }
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "unresolved"
    assert navigation.clarification_need is not None
    assert response.telemetry["navigation"]["outcome"] == "unresolved"
    assert "can't justify a single next step" in response.assistant_response.lower()


def test_phase31_guided_navigation_penalizes_stale_background_metadata_against_current_focus(temp_config) -> None:
    subsystem = _build_phase3_subsystem(
        temp_config,
        title="Review Changes - Google Chrome",
        window_handle=707,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what should I click next?",
        intent=ScreenIntentType.GUIDE_NAVIGATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-nav-31-7", "title": "Review Changes"},
            "active_item": {
                "itemId": "button-review",
                "title": "Review",
                "kind": "button",
                "focused": True,
                "selected": True,
                "enabled": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                    "stale": True,
                }
            ],
        },
        active_context={"selection": {}, "clipboard": {}},
    )

    navigation = response.analysis.navigation_result

    assert navigation is not None
    assert navigation.step_state.status.value == "ready"
    assert navigation.winning_candidate is not None
    assert navigation.winning_candidate.label == "Review"
    assert navigation.clarification_need is None
    assert response.telemetry["navigation"]["winning_candidate_id"] == "button-review"
