from __future__ import annotations

from stormhelm.config.loader import load_config
from stormhelm.ui.bridge import UiBridge


def test_ui_bridge_watch_timeline_section_surfaces_job_history(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "watch_state": {
                    "active_jobs": 0,
                    "queued_jobs": 0,
                    "recent_failures": 1,
                }
            },
            "jobs": [
                {
                    "job_id": "job-echo",
                    "tool_name": "echo",
                    "status": "completed",
                    "created_at": "2026-04-21T19:10:00Z",
                    "finished_at": "2026-04-21T19:10:04Z",
                    "result": {"summary": "Echoed the diagnostic payload."},
                },
                {
                    "job_id": "job-network",
                    "tool_name": "network_status",
                    "status": "failed",
                    "created_at": "2026-04-21T19:08:00Z",
                    "finished_at": "2026-04-21T19:08:12Z",
                    "error": "Adapter query timed out.",
                },
            ],
        }
    )

    bridge.activateModule("watch")
    bridge.activateWorkspaceSection("timeline")

    assert bridge.workspaceCanvas["viewKind"] == "signals"
    assert bridge.workspaceCanvas["timeline"][0]["title"] == "Echo"
    assert "echoed the diagnostic payload" in bridge.workspaceCanvas["timeline"][0]["detail"].lower()
    assert bridge.workspaceCanvas["timeline"][1]["title"] == "Network Status"
    assert "adapter query timed out" in bridge.workspaceCanvas["timeline"][1]["detail"].lower()


def test_ui_bridge_watch_tools_section_surfaces_backend_tool_catalog(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "tool_state": {
                    "enabled_count": 2,
                    "enabled_tools": ["echo", "machine_status"],
                },
                "watch_state": {
                    "active_jobs": 0,
                    "queued_jobs": 0,
                    "recent_failures": 0,
                },
            },
            "jobs": [
                {
                    "job_id": "job-echo",
                    "tool_name": "echo",
                    "status": "completed",
                    "created_at": "2026-04-21T19:10:00Z",
                    "finished_at": "2026-04-21T19:10:02Z",
                    "result": {"summary": "Echoed the request."},
                }
            ],
            "tools": [
                {
                    "name": "echo",
                    "display_name": "Echo",
                    "description": "Echo text back for development and diagnostics.",
                    "category": "development",
                    "classification": "read_only",
                    "execution_mode": "sync",
                    "timeout_seconds": None,
                },
                {
                    "name": "machine_status",
                    "display_name": "Machine Status",
                    "description": "Inspect host identity and local machine bearings.",
                    "category": "system",
                    "classification": "read_only",
                    "execution_mode": "sync",
                    "timeout_seconds": None,
                },
                {
                    "name": "shell_command",
                    "display_name": "Shell Command Stub",
                    "description": "Demonstrate strict action-tool gating without enabling shell execution.",
                    "category": "system",
                    "classification": "action",
                    "execution_mode": "sync",
                    "timeout_seconds": None,
                },
            ],
        }
    )

    bridge.activateModule("watch")
    bridge.activateWorkspaceSection("tools")

    assert bridge.workspaceCanvas["viewKind"] == "collection"
    items = {item["title"]: item for item in bridge.workspaceCanvas["items"]}
    assert "Echo" in items
    assert "Enabled" in items["Echo"]["subtitle"]
    assert "1 recent job" in items["Echo"]["detail"]
    assert "Shell Command Stub" in items
    assert "Disabled" in items["Shell Command Stub"]["subtitle"]


def test_ui_bridge_helm_safety_section_reflects_backend_policy_settings(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "settings": {
                "safety": {
                    "allowed_read_dirs": [
                        str(temp_config.project_root),
                        str(temp_config.project_root / "docs"),
                    ],
                    "allow_shell_stub": False,
                }
            }
        }
    )

    bridge.activateModule("helm")
    bridge.activateWorkspaceSection("safety")

    entries = [
        entry
        for column in bridge.workspaceCanvas["columns"]
        for entry in column.get("entries", [])
    ]
    assert any(entry["primary"] == "Read Scope" and entry["secondary"] == "2 allowlisted roots" for entry in entries)
    assert any(entry["primary"] == "Shell Command" and entry["secondary"] == "Disabled" for entry in entries)
    assert any(chip["label"] == "Read Scope" and chip["value"] == "2 allowlisted roots" for chip in bridge.workspaceCanvas["chips"])


def test_ui_bridge_helm_safety_section_surfaces_unsafe_test_mode_labels(temp_project_root) -> None:
    unsafe_config = load_config(
        project_root=temp_project_root,
        env={"STORMHELM_UNSAFE_TEST_MODE": "true"},
    )
    bridge = UiBridge(unsafe_config)
    bridge.apply_snapshot(
        {
            "settings": {
                "safety": {
                    "unsafe_test_mode": True,
                    "allowed_read_dirs": [str(unsafe_config.safety.allowed_read_dirs[0])],
                    "allow_shell_stub": True,
                }
            }
        }
    )

    bridge.activateModule("helm")
    bridge.activateWorkspaceSection("safety")

    entries = [
        entry
        for column in bridge.workspaceCanvas["columns"]
        for entry in column.get("entries", [])
    ]
    assert any(
        entry["primary"] == "Read Scope" and entry["secondary"] == "Unrestricted (unsafe test mode)"
        for entry in entries
    )
    assert any(entry["primary"] == "Shell Command" and entry["secondary"] == "Live execution" for entry in entries)
