from __future__ import annotations

from stormhelm.ui.bridge import UiBridge


def test_ui_bridge_surfaces_lifecycle_runtime_truth_in_systems_canvas(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "version": temp_config.version,
                "version_label": temp_config.version_label,
                "environment": temp_config.environment,
                "runtime_mode": "packaged",
                "lifecycle": {
                    "install_state": {
                        "install_mode": "portable",
                        "startup_capable": False,
                    },
                    "startup_policy": {
                        "startup_enabled": False,
                        "registration_status": "unavailable",
                        "registered_core": False,
                        "registered_shell": False,
                    },
                    "runtime": {
                        "core_status": "alive",
                        "shell_status": "hidden",
                        "tray_status": "present",
                        "connected_clients": 1,
                    },
                    "migration": {
                        "status": "current",
                        "migration_required": False,
                        "hold_reason": "",
                    },
                    "bootstrap": {
                        "startup_allowed": True,
                        "lifecycle_hold_reason": "",
                        "onboarding_required": True,
                        "warnings": [],
                    },
                    "uninstall_plan": {
                        "remove_binaries": True,
                        "remove_startup_registration": False,
                        "remove_logs": False,
                        "remove_caches": False,
                        "remove_durable_state": False,
                        "destructive_confirmation_required": True,
                    },
                },
            },
            "settings": {
                "safety": {"allowed_read_dirs": [str(temp_config.project_root)]},
            },
        }
    )

    bridge.activateModule("systems")

    lifecycle_column = next(column for column in bridge.workspaceCanvas["columns"] if column["title"] == "Lifecycle")
    entries = {entry["primary"]: entry for entry in lifecycle_column["entries"]}

    assert entries["Install Mode"]["secondary"] == "Portable"
    assert entries["Startup"]["secondary"] == "Disabled"
    assert entries["Core / Shell"]["secondary"] == "Alive / Hidden"
    assert "preserve durable state" in entries["Cleanup"]["detail"].lower()


def test_ui_bridge_surfaces_lifecycle_hold_as_a_context_card(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "version": temp_config.version,
                "version_label": temp_config.version_label,
                "environment": temp_config.environment,
                "runtime_mode": "packaged",
                "lifecycle": {
                    "install_state": {"install_mode": "installed", "startup_capable": True},
                    "startup_policy": {
                        "startup_enabled": True,
                        "registration_status": "registered",
                        "registered_core": True,
                        "registered_shell": False,
                    },
                    "runtime": {
                        "core_status": "alive",
                        "shell_status": "visible",
                        "tray_status": "present",
                        "connected_clients": 1,
                    },
                    "migration": {
                        "status": "hold",
                        "migration_required": True,
                        "hold_reason": "Portable-to-installed review is required before startup can continue cleanly.",
                    },
                    "bootstrap": {
                        "startup_allowed": False,
                        "lifecycle_hold_reason": "Portable-to-installed review is required before startup can continue cleanly.",
                        "onboarding_required": False,
                        "warnings": ["Install posture changed."],
                    },
                    "uninstall_plan": {
                        "remove_binaries": True,
                        "remove_startup_registration": True,
                        "remove_logs": False,
                        "remove_caches": False,
                        "remove_durable_state": False,
                        "destructive_confirmation_required": True,
                    },
                },
            },
            "settings": {
                "safety": {"allowed_read_dirs": [str(temp_config.project_root)]},
            },
        }
    )

    titles = {card["title"] for card in bridge.contextCards}

    assert "Lifecycle Hold" in titles


def test_ui_bridge_tray_tooltip_degrades_when_lifecycle_state_is_stale_or_held(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "version": temp_config.version,
                "version_label": temp_config.version_label,
                "environment": temp_config.environment,
                "runtime_mode": "packaged",
                "lifecycle": {
                    "install_state": {"install_mode": "installed", "startup_capable": True},
                    "startup_policy": {
                        "startup_enabled": True,
                        "registration_status": "stale",
                        "registered_core": False,
                        "registered_shell": False,
                        "registration": {
                            "requested_state": "requested",
                            "attempted_state": "attempted",
                            "applied_state": "applied",
                            "verified_state": "stale",
                        },
                    },
                    "runtime": {
                        "core_status": "held",
                        "shell_status": "stale",
                        "tray_status": "stale",
                        "connected_clients": 0,
                    },
                    "migration": {
                        "status": "hold",
                        "migration_required": True,
                        "hold_reason": "Repeated failures need operator review before restart can continue.",
                    },
                    "bootstrap": {
                        "startup_allowed": False,
                        "lifecycle_hold_reason": "Repeated failures need operator review before restart can continue.",
                        "onboarding_required": False,
                        "warnings": [],
                        "hold_state": {
                            "hold_active": True,
                            "hold_reason_kind": "restart_repeated_failures",
                            "hold_summary": "Repeated failures need operator review before restart can continue.",
                        },
                    },
                    "uninstall_plan": {
                        "remove_binaries": True,
                        "remove_startup_registration": True,
                        "remove_logs": False,
                        "remove_caches": False,
                        "remove_durable_state": False,
                        "destructive_confirmation_required": True,
                    },
                },
            }
        }
    )

    tooltip = bridge.tray_tooltip_text()

    assert "hold" in tooltip.lower()
    assert "stale" in tooltip.lower()
