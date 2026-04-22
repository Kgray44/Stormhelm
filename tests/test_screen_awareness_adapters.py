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


def _phase7_screen_config(temp_config, *, action_policy_mode: str = "confirm_before_act"):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase7"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
    temp_config.screen_awareness.adapters_enabled = True
    temp_config.screen_awareness.action_policy_mode = action_policy_mode
    return temp_config.screen_awareness


def _focused_window(*, process_name: str, title: str, window_handle: int) -> dict[str, object]:
    return {
        "process_name": process_name,
        "window_title": title,
        "window_handle": window_handle,
        "pid": 7000 + window_handle,
        "monitor_index": 1,
        "path": f"C:\\Program Files\\{process_name}\\{process_name}.exe",
        "is_focused": True,
        "minimized": False,
    }


def _browser_semantics(
    *,
    page_title: str,
    url: str,
    tab_title: str | None = None,
    freshness_seconds: float = 2.0,
    loading_state: str = "complete",
    form_fields: list[dict[str, object]] | None = None,
    validation_messages: list[str] | None = None,
) -> dict[str, object]:
    return {
        "page": {"title": page_title, "url": url},
        "tab": {"title": tab_title or page_title, "index": 2, "active": True},
        "loading_state": loading_state,
        "freshness_seconds": freshness_seconds,
        "form_fields": list(form_fields or []),
        "validation_messages": list(validation_messages or []),
    }


def test_phase7_browser_adapter_enriches_current_context_and_keeps_hidden_dom_out_of_visible_targets(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase7_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_window(
                process_name="chrome",
                title="Security settings - Google Chrome",
                window_handle=901,
            )
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what page am I on?",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "adapter_semantics": {
                "browser": _browser_semantics(
                    page_title="Security settings",
                    url="https://example.test/settings/security",
                    form_fields=[
                        {"field_id": "field-api-token", "label": "API token", "role": "field", "visible": True},
                        {"field_id": "field-admin-token", "label": "Admin token", "role": "field", "visible": False},
                    ],
                    validation_messages=["API token is required"],
                )
            },
        },
    )

    assert response.analysis.adapter_resolution is not None
    assert response.analysis.adapter_resolution.adapter_id == "browser"
    assert response.analysis.current_screen_context.adapter_resolution is not None
    visible_labels = {target.label for target in response.analysis.current_screen_context.semantic_targets}
    assert "API token" in visible_labels
    assert "Admin token" not in visible_labels
    assert response.telemetry["adapter"]["active_adapter"] == "browser"
    assert response.telemetry["adapter"]["fallback_used"] is False
    assert "security settings" in response.assistant_response.lower()


def test_phase7_browser_adapter_refuses_hidden_dom_field_as_action_target(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase7_screen_config(temp_config, action_policy_mode="trusted_action"),
        system_probe=FakeObservationProbe(
            focused_window=_focused_window(
                process_name="chrome",
                title="Admin Console - Google Chrome",
                window_handle=902,
            )
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="click the Admin token field",
        intent=ScreenIntentType.EXECUTE_UI_ACTION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "adapter_semantics": {
                "browser": _browser_semantics(
                    page_title="Admin Console",
                    url="https://example.test/admin",
                    form_fields=[
                        {"field_id": "field-admin-token", "label": "Admin token", "role": "field", "visible": False}
                    ],
                )
            },
        },
    )

    action = response.analysis.action_result

    assert action is not None
    assert action.status.value in {"ambiguous", "failed"}
    assert action.attempt is None
    assert response.telemetry["adapter"]["active_adapter"] == "browser"
    assert response.telemetry["adapter"]["fallback_used"] is True


def test_phase7_browser_adapter_strengthens_page_verification_without_claiming_loading_success(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase7_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_window(
                process_name="chrome",
                title="Security settings - Google Chrome",
                window_handle=903,
            )
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="is this the page I was trying to get to?",
        intent=ScreenIntentType.VERIFY_SCREEN_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [
                {
                    "kind": "screen_awareness",
                    "intent": "guide_navigation",
                    "analysis_result": {
                        "navigation_result": {
                            "step_state": {"status": "ready", "expected_target_label": "Security settings"},
                        }
                    },
                }
            ],
            "adapter_semantics": {
                "browser": _browser_semantics(
                    page_title="Security settings",
                    url="https://example.test/settings/security",
                    loading_state="loading",
                )
            },
        },
    )

    verification = response.analysis.verification_result

    assert verification is not None
    assert verification.completion_status.value != "completed"
    assert response.telemetry["adapter"]["active_adapter"] == "browser"
    assert response.telemetry["verification"]["adapter_used"] is True


def test_phase7_file_explorer_adapter_reports_selected_item_and_path(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase7_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_window(
                process_name="explorer",
                title="Projects - File Explorer",
                window_handle=904,
            )
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what file is selected?",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "adapter_semantics": {
                "file_explorer": {
                    "current_path": "C:\\Users\\kkids\\Documents\\Projects",
                    "selected_item": {"name": "release-notes.md", "kind": "file"},
                    "freshness_seconds": 1.0,
                }
            },
        },
    )

    assert response.analysis.adapter_resolution is not None
    assert response.analysis.adapter_resolution.adapter_id == "file_explorer"
    assert response.analysis.current_screen_context.adapter_resolution is not None
    assert "release-notes.md" in response.assistant_response
    assert "projects" in response.assistant_response.lower()


def test_phase7_adapter_falls_back_honestly_when_browser_semantics_are_stale(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase7_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_window(
                process_name="chrome",
                title="CI Dashboard - Google Chrome",
                window_handle=905,
            )
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what page am I on?",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "adapter_semantics": {
                "browser": _browser_semantics(
                    page_title="CI Dashboard",
                    url="https://example.test/builds",
                    freshness_seconds=3600.0,
                )
            },
        },
    )

    assert response.analysis.adapter_resolution is not None
    assert response.analysis.adapter_resolution.available is False
    assert response.telemetry["adapter"]["active_adapter"] == "browser"
    assert response.telemetry["adapter"]["fallback_used"] is True
    assert response.telemetry["adapter"]["fallback_reason"] == "stale_semantic_state"
