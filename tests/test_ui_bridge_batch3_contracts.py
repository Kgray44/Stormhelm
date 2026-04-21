from __future__ import annotations

from stormhelm.ui.bridge import UiBridge


def test_ui_bridge_rebinds_matching_active_workspace_summary_on_refresh(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_action(
        {
            "type": "workspace_restore",
            "module": "files",
            "section": "opened-items",
            "workspace": {
                "workspaceId": "ws-research",
                "name": "Research Workspace",
                "topic": "research",
                "summary": "Hold active references and findings together.",
            },
            "items": [
                {
                    "itemId": "file-1",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "draft-notes.md",
                    "path": "C:/Stormhelm/draft-notes.md",
                    "module": "files",
                    "section": "opened-items",
                }
            ],
            "active_item_id": "file-1",
        }
    )

    refreshed_workspace = {
        "workspace": {
            "workspaceId": "ws-research",
            "name": "Research Workspace",
            "topic": "research",
            "summary": "Recovered browser bearings should remain visible after reconnect.",
        },
        "opened_items": [
            {
                "itemId": "page-1",
                "kind": "browser",
                "viewer": "browser",
                "title": "OpenAI Platform Docs",
                "url": "https://platform.openai.com/docs",
                "module": "browser",
                "section": "open-pages",
            }
        ],
        "active_item": {
            "itemId": "page-1",
            "kind": "browser",
            "viewer": "browser",
            "title": "OpenAI Platform Docs",
            "url": "https://platform.openai.com/docs",
            "module": "browser",
            "section": "open-pages",
        },
        "action": {
            "type": "workspace_restore",
            "module": "browser",
            "section": "open-pages",
            "workspace": {
                "workspaceId": "ws-research",
                "name": "Research Workspace",
                "topic": "research",
                "summary": "Recovered browser bearings should remain visible after reconnect.",
            },
            "items": [
                {
                    "itemId": "page-1",
                    "kind": "browser",
                    "viewer": "browser",
                    "title": "OpenAI Platform Docs",
                    "url": "https://platform.openai.com/docs",
                    "module": "browser",
                    "section": "open-pages",
                }
            ],
            "active_item_id": "page-1",
        },
    }

    bridge.apply_snapshot({"active_workspace": refreshed_workspace})

    assert bridge.active_module_key == "browser"
    assert bridge.workspaceCanvas["sectionKey"] == "open-pages"
    assert [item["itemId"] for item in bridge.opened_items] == ["page-1"]
    assert bridge.activeOpenedItem["itemId"] == "page-1"
    assert bridge.workspace_context_payload()["workspace"]["summary"] == (
        "Recovered browser bearings should remain visible after reconnect."
    )


def test_ui_bridge_does_not_replace_another_workspace_during_refresh(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_action(
        {
            "type": "workspace_restore",
            "module": "files",
            "section": "opened-items",
            "workspace": {
                "workspaceId": "ws-writing",
                "name": "Writing Workspace",
                "topic": "writing",
                "summary": "Hold the active draft locally.",
            },
            "items": [
                {
                    "itemId": "file-1",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "draft.md",
                    "path": "C:/Stormhelm/draft.md",
                    "module": "files",
                    "section": "opened-items",
                }
            ],
            "active_item_id": "file-1",
        }
    )

    bridge.apply_snapshot(
        {
            "active_workspace": {
                "workspace": {
                    "workspaceId": "ws-other",
                    "name": "Other Workspace",
                    "topic": "research",
                    "summary": "This summary should not displace the current workspace.",
                },
                "opened_items": [
                    {
                        "itemId": "page-1",
                        "kind": "browser",
                        "viewer": "browser",
                        "title": "External Docs",
                        "url": "https://example.com/docs",
                        "module": "browser",
                        "section": "open-pages",
                    }
                ],
                "active_item": {
                    "itemId": "page-1",
                    "kind": "browser",
                    "viewer": "browser",
                    "title": "External Docs",
                    "url": "https://example.com/docs",
                    "module": "browser",
                    "section": "open-pages",
                },
                "action": {
                    "type": "workspace_restore",
                    "module": "browser",
                    "section": "open-pages",
                    "workspace": {
                        "workspaceId": "ws-other",
                        "name": "Other Workspace",
                        "topic": "research",
                        "summary": "This summary should not displace the current workspace.",
                    },
                    "items": [
                        {
                            "itemId": "page-1",
                            "kind": "browser",
                            "viewer": "browser",
                            "title": "External Docs",
                            "url": "https://example.com/docs",
                            "module": "browser",
                            "section": "open-pages",
                        }
                    ],
                    "active_item_id": "page-1",
                },
            }
        }
    )

    assert bridge.active_module_key == "files"
    assert bridge.workspaceCanvas["sectionKey"] == "opened-items"
    assert [item["itemId"] for item in bridge.opened_items] == ["file-1"]
    assert bridge.activeOpenedItem["itemId"] == "file-1"
    assert bridge.workspace_context_payload()["workspace"]["workspaceId"] == "ws-writing"


def test_ui_bridge_routes_system_focus_from_state_hint_and_surfaces_it(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_action(
        {
            "type": "workspace_focus",
            "module": "systems",
            "section": "overview",
            "state_hint": "network-throughput",
        }
    )

    assert bridge.active_module_key == "systems"
    assert bridge.workspaceCanvas["sectionKey"] == "network"
    assert any(
        chip["label"] == "Focus" and chip["value"] == "Network Throughput"
        for chip in bridge.workspaceCanvas["chips"]
    )
    assert "Network Throughput" in bridge.statusLine


def test_ui_bridge_browser_workspace_does_not_full_refresh_on_status_only_poll(temp_config) -> None:
    bridge = UiBridge(temp_config)
    changes: list[str] = []
    bridge.collectionsChanged.connect(lambda: changes.append("collections"))

    initial_payload = {
        "health": {
            "status": "ok",
            "version": temp_config.version,
            "version_label": temp_config.version_label,
            "runtime_mode": "source",
        },
        "status": {
            "version": temp_config.version,
            "version_label": temp_config.version_label,
            "environment": temp_config.environment,
            "runtime_mode": "source",
            "max_workers": temp_config.concurrency.max_workers,
            "recent_jobs": 0,
            "system_state": {
                "machine": {"machine_name": "STORMHELM-RIG"},
                "power": {"available": True, "battery_percent": 86, "ac_line_status": "online"},
                "resources": {"cpu": {"name": "AMD Ryzen"}, "memory": {"total_bytes": 1, "used_bytes": 1, "free_bytes": 0}, "gpu": []},
                "storage": {"drives": []},
                "network": {"interfaces": [{"interface_alias": "Wi-Fi"}]},
            },
            "provider_state": {"enabled": False, "configured": False},
            "tool_state": {"enabled_count": 0, "enabled_tools": []},
            "watch_state": {"active_jobs": 0, "queued_jobs": 0, "recent_failures": 0, "completed_recently": 0},
        },
        "history": [
            {
                "message_id": "assistant-1",
                "role": "assistant",
                "content": "Ready.",
                "created_at": "2026-04-21T18:00:00Z",
            }
        ],
        "active_workspace": {
            "workspace": {
                "workspaceId": "ws-browser",
                "name": "Browser Workspace",
                "topic": "research",
                "summary": "Hold references in the Deck.",
            },
            "opened_items": [
                {
                    "itemId": "page-1",
                    "kind": "browser",
                    "viewer": "browser",
                    "title": "OpenAI Docs",
                    "url": "https://platform.openai.com/docs",
                    "module": "browser",
                    "section": "open-pages",
                }
            ],
            "active_item": {
                "itemId": "page-1",
                "kind": "browser",
                "viewer": "browser",
                "title": "OpenAI Docs",
                "url": "https://platform.openai.com/docs",
                "module": "browser",
                "section": "open-pages",
            },
            "action": {
                "type": "workspace_restore",
                "module": "browser",
                "section": "open-pages",
                "workspace": {
                    "workspaceId": "ws-browser",
                    "name": "Browser Workspace",
                    "topic": "research",
                    "summary": "Hold references in the Deck.",
                },
                "items": [
                    {
                        "itemId": "page-1",
                        "kind": "browser",
                        "viewer": "browser",
                        "title": "OpenAI Docs",
                        "url": "https://platform.openai.com/docs",
                        "module": "browser",
                        "section": "open-pages",
                    }
                ],
                "active_item_id": "page-1",
            },
        },
    }

    bridge.apply_snapshot(initial_payload)
    changes.clear()

    refreshed_payload = {
        **initial_payload,
        "status": {
            **initial_payload["status"],
            "recent_jobs": 1,
            "watch_state": {"active_jobs": 1, "queued_jobs": 0, "recent_failures": 0, "completed_recently": 0},
            "system_state": {
                **initial_payload["status"]["system_state"],
                "network": {"interfaces": [{"interface_alias": "Wi-Fi"}], "quality": {"latency_ms": 24}},
            },
        },
    }

    bridge.apply_snapshot(refreshed_payload)

    assert changes == []
    assert bridge.active_module_key == "browser"
    assert bridge.activeOpenedItem["itemId"] == "page-1"
