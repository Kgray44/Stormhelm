from __future__ import annotations

from stormhelm.ui.bridge import UiBridge


def test_ui_bridge_surfaces_concise_software_control_card_from_latest_assistant_metadata(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_chat_result(
        {
            "assistant_message": {
                "message_id": "assistant-1",
                "role": "assistant",
                "content": (
                    "Prepared a local install plan for Firefox. Source: winget. "
                    "I have not installed anything yet."
                ),
                "created_at": "2026-04-22T17:10:00Z",
                "metadata": {
                    "bearing_title": "Software Plan",
                    "micro_response": "Prepared a local install plan for Firefox.",
                    "full_response": (
                        "Prepared a local install plan for Firefox. Source: winget. "
                        "I have not installed anything yet."
                    ),
                    "planner_debug": {
                        "software_control": {
                            "candidate": True,
                            "operation_type": "install",
                            "target_name": "firefox",
                            "result": {"status": "prepared"},
                            "trace": {"execution_status": "prepared"},
                        }
                    },
                },
            }
        }
    )

    assert bridge.contextCards[0]["title"] == "Software Plan"
    assert bridge.contextCards[0]["subtitle"] == "Prepared"
    assert "Firefox" in bridge.contextCards[0]["body"]


def test_ui_bridge_includes_software_bearings_in_systems_workspace_columns(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "version": temp_config.version,
                "version_label": temp_config.version_label,
                "environment": temp_config.environment,
                "runtime_mode": temp_config.runtime.mode,
                "system_state": {
                    "machine": {},
                    "power": {},
                    "resources": {},
                    "hardware": {},
                    "storage": {"drives": []},
                    "network": {},
                    "location": {},
                },
                "provider_state": {"enabled": False, "configured": False},
                "tool_state": {"enabled_count": 0, "enabled_tools": []},
                "watch_state": {"tasks": []},
                "software_control": {
                    "phase": "software1",
                    "enabled": True,
                    "planner_routing_enabled": True,
                    "package_manager_routes_enabled": True,
                    "browser_guided_routes_enabled": True,
                    "privileged_operations_allowed": False,
                    "last_trace": {
                        "target_name": "firefox",
                        "operation_type": "install",
                        "execution_status": "prepared",
                    },
                },
                "software_recovery": {
                    "phase": "recovery1",
                    "enabled": True,
                    "cloud_fallback_enabled": False,
                    "last_trace": {
                        "failure_category": "adapter_mismatch",
                        "status": "ready",
                    },
                },
            }
        }
    )

    bridge.apply_action({"type": "workspace_focus", "module": "systems", "section": "overview"})

    assert any(column["title"] == "Software Bearings" for column in bridge.workspaceCanvas["columns"])

