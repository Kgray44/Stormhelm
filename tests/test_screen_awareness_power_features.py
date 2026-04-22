from __future__ import annotations

from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import ScreenSensitivityLevel
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem


class Phase11Probe:
    def __init__(
        self,
        *,
        focused_window: dict[str, object] | None = None,
        windows: list[dict[str, object]] | None = None,
        monitors: list[dict[str, object]] | None = None,
        notifications: list[dict[str, object]] | None = None,
    ) -> None:
        self._focused_window = focused_window
        self._windows = list(windows or ([focused_window] if focused_window else []))
        self._monitors = list(
            monitors
            or [
                {
                    "index": 1,
                    "device_name": "\\\\.\\DISPLAY1",
                    "is_primary": True,
                    "bounds": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                    "scale": 1.0,
                }
            ]
        )
        self._notifications = list(notifications or [])

    def window_status(self) -> dict[str, object]:
        return {
            "focused_window": self._focused_window,
            "windows": list(self._windows),
            "monitors": list(self._monitors),
            "notifications": list(self._notifications),
        }


def _phase11_screen_config(temp_config):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase11"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.debug_events_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
    temp_config.screen_awareness.adapters_enabled = True
    temp_config.screen_awareness.problem_solving_enabled = True
    temp_config.screen_awareness.workflow_learning_enabled = True
    temp_config.screen_awareness.brain_integration_enabled = True
    temp_config.screen_awareness.power_features_enabled = True
    temp_config.screen_awareness.action_policy_mode = "confirm_before_act"
    return temp_config.screen_awareness


def test_phase11_builds_multi_monitor_workspace_map_and_accessibility_summary(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase11_screen_config(temp_config),
        system_probe=Phase11Probe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Release Form - Google Chrome",
                "window_handle": 9311,
                "pid": 1440,
                "monitor_index": 2,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            },
            windows=[
                {
                    "process_name": "chrome",
                    "window_title": "Release Form - Google Chrome",
                    "window_handle": 9311,
                    "pid": 1440,
                    "monitor_index": 2,
                    "is_focused": True,
                    "minimized": False,
                    "bounds": {"x": 1940, "y": 80, "width": 1200, "height": 900},
                },
                {
                    "process_name": "excel",
                    "window_title": "Deploy Checklist.xlsx - Excel",
                    "window_handle": 9440,
                    "pid": 2010,
                    "monitor_index": 1,
                    "is_focused": False,
                    "minimized": False,
                    "bounds": {"x": 80, "y": 60, "width": 1400, "height": 920},
                },
            ],
            monitors=[
                {
                    "index": 1,
                    "device_name": "\\\\.\\DISPLAY1",
                    "is_primary": True,
                    "bounds": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                    "scale": 1.0,
                },
                {
                    "index": 2,
                    "device_name": "\\\\.\\DISPLAY2",
                    "is_primary": False,
                    "bounds": {"x": 1920, "y": 0, "width": 2560, "height": 1440},
                    "scale": 1.25,
                },
            ],
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="which display is that on",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-phase11-1", "title": "Release Workflow"},
            "module": "browser",
            "section": "form",
            "active_item": {
                "itemId": "release-form",
                "title": "Release Form",
                "kind": "form",
                "focused": True,
            },
            "opened_items": [
                {
                    "itemId": "button-continue",
                    "title": "Continue",
                    "kind": "button",
                    "pane": "footer",
                    "enabled": True,
                    "monitor_id": "\\\\.\\DISPLAY2",
                    "bounds": {"x": 3000, "y": 1220, "width": 180, "height": 44},
                }
            ],
        },
        active_context={
            "selection": {},
            "clipboard": {},
            "accessibility": {
                "focused_label": "Continue",
                "focused_role": "button",
                "enabled": True,
                "focus_path": ["Release Form", "Footer", "Continue"],
                "keyboard_hint": "Press Tab until Continue, then Enter.",
            },
        },
    )

    power = response.analysis.power_features_result

    assert power is not None
    assert power.monitor_topology is not None
    assert len(power.monitor_topology.monitors) == 2
    assert power.monitor_topology.active_monitor_id == "\\\\.\\DISPLAY2"
    assert power.workspace_map is not None
    assert len(power.workspace_map.windows) == 2
    assert power.accessibility_summary is not None
    assert power.focus_context is not None
    assert response.analysis.current_screen_context.monitor_topology is not None
    assert response.analysis.current_screen_context.workspace_map is not None
    assert response.analysis.current_screen_context.accessibility_summary is not None
    assert response.telemetry["power_features"]["requested"] is True
    assert response.telemetry["power_features"]["monitor_count"] == 2
    assert response.telemetry["power_features"]["workspace_window_count"] == 2
    assert "display" in response.assistant_response.lower() or "monitor" in response.assistant_response.lower()
    assert "continue" in response.assistant_response.lower()


def test_phase11_translates_visible_ui_text_and_extracts_structured_entities_truthfully(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase11_screen_config(temp_config),
        system_probe=Phase11Probe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Installer - Google Chrome",
                "window_handle": 8811,
                "pid": 1550,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="translate this installer prompt",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-phase11-2", "title": "Installer"},
            "active_item": {"itemId": "installer", "title": "Installer", "kind": "dialog"},
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "Guardar cambios. Version 2.4.1. Error CODE-731 a las 14:32.",
                "preview": "Guardar cambios. Version 2.4.1. Error CODE-731 a las 14:32.",
            },
            "clipboard": {},
            "accessibility": {
                "focused_label": "Guardar cambios",
                "focused_role": "button",
                "enabled": True,
            },
        },
    )

    power = response.analysis.power_features_result

    assert power is not None
    assert power.translations
    assert power.translations[0].source_text == "Guardar cambios"
    assert "save" in power.translations[0].translated_text.lower()
    assert power.extracted_entities is not None
    entity_types = {entity.entity_type for entity in power.extracted_entities.entities}
    assert {"version", "error_code", "time"} <= entity_types
    assert response.analysis.current_screen_context.visible_translations
    assert response.analysis.current_screen_context.extracted_entity_set is not None
    assert response.telemetry["power_features"]["translation_count"] >= 1
    assert response.telemetry["power_features"]["entity_count"] >= 3
    assert "guardar cambios" in response.assistant_response.lower()
    assert "save" in response.assistant_response.lower()
    assert "verified" not in response.assistant_response.lower()


def test_phase11_builds_truthful_overlay_instruction_from_grounded_warning(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase11_screen_config(temp_config),
        system_probe=Phase11Probe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Permissions - Google Chrome",
                "window_handle": 7821,
                "pid": 1660,
                "monitor_index": 2,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            },
            monitors=[
                {
                    "index": 1,
                    "device_name": "\\\\.\\DISPLAY1",
                    "is_primary": True,
                    "bounds": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                    "scale": 1.0,
                },
                {
                    "index": 2,
                    "device_name": "\\\\.\\DISPLAY2",
                    "is_primary": False,
                    "bounds": {"x": 1920, "y": 0, "width": 2560, "height": 1440},
                    "scale": 1.25,
                },
            ],
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="highlight the warning",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-phase11-3", "title": "Installer Permissions"},
            "active_item": {"itemId": "perm-dialog", "title": "Administrator permission required", "kind": "warning"},
            "opened_items": [
                {
                    "itemId": "warning-permission",
                    "title": "Administrator permission required",
                    "kind": "warning",
                    "pane": "dialog",
                    "enabled": True,
                    "monitor_id": "\\\\.\\DISPLAY2",
                    "bounds": {"x": 2600, "y": 420, "width": 540, "height": 180},
                }
            ],
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "Administrator permission required",
                "preview": "Administrator permission required",
            },
            "clipboard": {},
            "notifications": [
                {
                    "title": "Administrator permission required",
                    "body": "Approve the request to continue.",
                    "app_identity": "installer",
                    "severity": "warning",
                    "kind": "permission_prompt",
                    "monitor_id": "\\\\.\\DISPLAY2",
                },
                {
                    "title": "Calendar reminder",
                    "body": "Standup in 10 minutes.",
                    "app_identity": "calendar",
                    "severity": "info",
                    "kind": "toast",
                    "monitor_id": "\\\\.\\DISPLAY1",
                },
            ],
        },
    )

    power = response.analysis.power_features_result

    assert power is not None
    assert power.overlay_instructions
    assert power.overlay_instructions[0].anchor.monitor_id == "\\\\.\\DISPLAY2"
    assert power.overlay_instructions[0].anchor.precision in {"grounded", "candidate"}
    assert response.telemetry["power_features"]["overlay_instruction_count"] >= 1
    assert response.telemetry["power_features"]["notification_count"] == 2
    assert response.telemetry["power_features"]["blocker_notification_count"] == 1
    assert "highlight" in response.assistant_response.lower() or "warning" in response.assistant_response.lower()
    assert "verified" not in response.assistant_response.lower()


def test_phase11_notification_query_distinguishes_blockers_from_background_noise(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase11_screen_config(temp_config),
        system_probe=Phase11Probe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Deploy Dashboard - Google Chrome",
                "window_handle": 7111,
                "pid": 1770,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            },
            notifications=[
                {
                    "title": "Battery low",
                    "body": "Plug in soon.",
                    "app_identity": "system",
                    "severity": "warning",
                    "kind": "system_warning",
                    "monitor_id": "\\\\.\\DISPLAY1",
                },
                {
                    "title": "Sync complete",
                    "body": "Background upload finished.",
                    "app_identity": "drive",
                    "severity": "info",
                    "kind": "toast",
                    "monitor_id": "\\\\.\\DISPLAY1",
                },
            ],
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what notification just appeared",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={"workspace": {"workspaceId": "ws-phase11-4", "title": "Deploy Dashboard"}},
        active_context={"selection": {}, "clipboard": {}},
    )

    power = response.analysis.power_features_result

    assert power is not None
    assert len(power.notification_events) == 2
    assert power.notification_events[0].blocker is True
    assert power.notification_events[1].blocker is False
    assert response.analysis.current_screen_context.notification_events
    assert response.telemetry["power_features"]["notification_count"] == 2
    assert response.telemetry["power_features"]["blocker_notification_count"] == 1
    assert "battery" in response.assistant_response.lower() or "notification" in response.assistant_response.lower()
