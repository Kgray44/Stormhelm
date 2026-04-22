from __future__ import annotations

from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import ScreenLimitationCode
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


def _phase1_screen_config(temp_config):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase1"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    return temp_config.screen_awareness


def test_screen_awareness_subsystem_builds_structured_inspection_from_native_context(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase1_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "PyInstaller Docs - Google Chrome",
                "window_handle": 401,
                "pid": 1440,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what am I looking at",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-1", "title": "PyInstaller Research"},
            "active_item": {
                "itemId": "page-1",
                "title": "PyInstaller Docs",
                "url": "https://pyinstaller.org/en/stable/",
                "kind": "browser-tab",
            },
        },
        active_context={
            "workspace": {"workspaceId": "ws-1", "title": "PyInstaller Research"},
            "selection": {
                "kind": "text",
                "value": "PyInstaller bundles a Python application into a single executable.",
                "preview": "PyInstaller bundles a Python application into a single executable.",
            },
            "clipboard": {},
        },
    )

    assert response.analysis.observation is not None
    assert response.analysis.interpretation is not None
    assert response.analysis.current_screen_context is not None
    assert {source.value for source in response.analysis.observation.source_types_used} >= {
        "focus_state",
        "selection",
        "workspace_context",
    }
    assert response.analysis.interpretation.likely_environment == "browser"
    assert "pyinstaller" in (response.analysis.current_screen_context.summary or "").lower()
    assert response.telemetry["observation"]["attempted"] is True
    assert "observed:" in response.assistant_response.lower()
    assert "verified" not in response.assistant_response.lower()


def test_screen_awareness_subsystem_explains_visible_python_name_error_truthfully(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase1_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "code",
                "window_title": "main.py - Visual Studio Code",
                "window_handle": 411,
                "pid": 1660,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Microsoft VS Code\\Code.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what does this mean",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {
                "kind": "text",
                "value": "NameError: name 'foo' is not defined",
                "preview": "NameError: name 'foo' is not defined",
            },
            "clipboard": {},
        },
    )

    assert response.analysis.interpretation is not None
    assert response.analysis.interpretation.visible_errors
    assert "nameerror" in response.analysis.interpretation.visible_errors[0].lower()
    assert "python" in response.assistant_response.lower()
    assert "foo" in response.assistant_response
    assert response.analysis.verification_state.value == "unverified"


def test_screen_awareness_subsystem_solves_visible_math_expression_when_fully_available(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase1_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Homework Portal - Google Chrome",
                "window_handle": 421,
                "pid": 1770,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="can you solve this",
        intent=ScreenIntentType.SOLVE_VISIBLE_PROBLEM,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {
                "kind": "text",
                "value": "12 * (3 + 4)",
                "preview": "12 * (3 + 4)",
            },
            "clipboard": {},
        },
    )

    assert "84" in response.assistant_response
    assert response.analysis.current_screen_context is not None
    assert response.analysis.current_screen_context.visible_task_state


def test_screen_awareness_subsystem_refuses_to_claim_change_without_prior_bearing(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase1_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "CI Dashboard - Google Chrome",
                "window_handle": 431,
                "pid": 1880,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what changed on my screen",
        intent=ScreenIntentType.DETECT_VISIBLE_CHANGE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {
                "kind": "text",
                "value": "Build failed with 2 test failures.",
                "preview": "Build failed with 2 test failures.",
            },
            "clipboard": {},
        },
    )

    limitation_codes = {limitation.code for limitation in response.analysis.limitations}
    assert ScreenLimitationCode.PRIOR_OBSERVATION_REQUIRED in limitation_codes
    assert ScreenLimitationCode.UNVERIFIED_CHANGE in limitation_codes
    assert "changed" in response.assistant_response.lower()
    assert "prior" in response.assistant_response.lower() or "before" in response.assistant_response.lower()


def test_screen_awareness_subsystem_returns_honest_fallback_when_observation_is_unavailable(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase1_screen_config(temp_config),
        system_probe=FakeObservationProbe(focused_window=None, windows=[]),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what am I looking at",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    limitation_codes = {limitation.code for limitation in response.analysis.limitations}
    assert ScreenLimitationCode.OBSERVATION_UNAVAILABLE in limitation_codes
    assert response.analysis.fallback_reason == "observation_unavailable"
    assert response.telemetry["observation"]["attempted"] is True
    assert "don't have a reliable screen bearing" in response.assistant_response.lower()


def test_screen_awareness_clipboard_only_is_downgraded_to_hint_not_screen_truth(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase1_screen_config(temp_config),
        system_probe=FakeObservationProbe(focused_window=None, windows=[]),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what am I looking at",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {
                "kind": "text",
                "value": "SECRET TOKEN 123",
                "preview": "SECRET TOKEN 123",
            },
        },
    )

    limitation_codes = {limitation.code for limitation in response.analysis.limitations}

    assert ScreenLimitationCode.OBSERVATION_UNAVAILABLE in limitation_codes
    assert "clipboard contains" in response.assistant_response.lower()
    assert "can't confirm" in response.assistant_response.lower()
    assert response.telemetry["observation"]["clipboard_only"] is True
    assert response.telemetry["observation"]["live_signal_available"] is False


def test_screen_awareness_current_window_outranks_conflicting_clipboard_for_screen_question(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase1_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Stormhelm Docs - Google Chrome",
                "window_handle": 501,
                "pid": 2001,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what is on my screen",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-live-1", "title": "Stormhelm Docs"},
            "active_item": {
                "itemId": "page-1",
                "title": "Stormhelm Docs",
                "url": "https://example.com/stormhelm-docs",
                "kind": "browser-tab",
            },
        },
        active_context={
            "selection": {},
            "clipboard": {
                "kind": "text",
                "value": "stale copied text that is not the current page",
                "preview": "stale copied text that is not the current page",
            },
        },
    )

    assert "stormhelm docs" in response.assistant_response.lower()
    assert "clipboard context reads" not in response.assistant_response.lower()
    assert response.telemetry["observation"]["clipboard_only"] is False
    assert response.telemetry["observation"]["live_signal_available"] is True
