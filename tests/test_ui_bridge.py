from __future__ import annotations

from stormhelm.ui.bridge import UiBridge


def test_ui_bridge_defaults_to_ghost_mode_and_tracks_rail_state(temp_config) -> None:
    bridge = UiBridge(temp_config)

    assert bridge.mode_value == "ghost"
    assert bridge.assistant_state_value == "idle"
    assert bridge.active_module_key == "chartroom"
    assert any(item["key"] == "chartroom" and item["active"] for item in bridge.command_rail_items)

    bridge.setMode("deck")
    bridge.activateModule("signals")

    assert bridge.mode_value == "deck"
    assert bridge.active_module_key == "signals"
    assert any(item["key"] == "signals" and item["active"] for item in bridge.command_rail_items)


def test_ui_bridge_applies_snapshot_to_context_cards_and_modules(temp_config) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
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
                "recent_jobs": 1,
                "data_dir": str(temp_config.storage.data_dir),
                "install_root": str(temp_config.runtime.install_root),
            },
            "history": [
                {
                    "message_id": "1",
                    "role": "assistant",
                    "content": "Bearing acquired.",
                    "created_at": "2026-04-18T12:00:00Z",
                }
            ],
            "jobs": [
                {
                    "job_id": "job-1",
                    "tool_name": "echo",
                    "status": "completed",
                    "created_at": "2026-04-18T12:00:01Z",
                    "finished_at": "2026-04-18T12:00:02Z",
                    "result": {"summary": "Echoed test payload."},
                }
            ],
            "events": [
                {
                    "event_id": 7,
                    "level": "INFO",
                    "source": "core",
                    "message": "Stormhelm core started.",
                    "created_at": "2026-04-18T12:00:00Z",
                }
            ],
            "notes": [
                {
                    "note_id": "note-1",
                    "title": "Bearing",
                    "content": "Marked safe harbor.",
                    "created_at": "2026-04-18T12:01:00Z",
                }
            ],
            "settings": {
                "safety": {"allowed_read_dirs": [str(temp_config.project_root)]},
            },
        }
    )

    assert bridge.connection_state == "connected"
    assert bridge.ghost_messages[0]["content"] == "Bearing acquired."
    assert any(card["title"] == "Echo" for card in bridge.context_cards)

    modules = {module["key"]: module for module in bridge.deck_modules}
    assert modules["logbook"]["kind"] == "notes"
    assert modules["logbook"]["entries"][0]["primary"] == "Bearing"
    assert modules["watch"]["kind"] == "jobs"
    assert bridge.workspaceCanvas["columns"][0]["title"] == "Active Thread"


def test_ui_bridge_close_requests_hide_when_tray_behavior_is_enabled(temp_config) -> None:
    bridge = UiBridge(temp_config)

    assert bridge.handleCloseRequest() is True

    bridge.setHideToTrayOnClose(False)

    assert bridge.handleCloseRequest() is False


def test_ui_bridge_exposes_ghost_instrumentation_and_active_context(temp_config) -> None:
    bridge = UiBridge(temp_config)

    corners = {item["corner"]: item for item in bridge.ghostCornerReadouts}

    assert set(corners) == {"top_left", "top_right", "bottom_left", "bottom_right"}
    assert corners["top_left"]["label"] == "Stormhelm"
    assert "Deck" in corners["bottom_right"]["primary"]

    bridge.activateModule("signals")

    assert any(item["key"] == "live" and item["active"] for item in bridge.workspaceRailItems)
    assert any(item["key"] == "signals" and item["active"] for item in bridge.commandRailItems)
    assert bridge.activeDeckModule["key"] == "signals"


def test_ui_bridge_uses_warning_state_for_connection_errors(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.set_connection_error("offline")

    assert bridge.connection_state == "disrupted"
    assert bridge.assistant_state_value == "warning"


def test_ui_bridge_ghost_capture_tracks_draft_and_submission(temp_config) -> None:
    bridge = UiBridge(temp_config)
    sent_messages: list[str] = []
    bridge.sendMessageRequested.connect(sent_messages.append)

    bridge.beginGhostCapture()
    bridge.appendGhostDraft("Plot safe harbor")

    assert bridge.ghostCaptureActive is True
    assert bridge.ghostDraftText == "Plot safe harbor"
    assert bridge.ghostInputHint == "Enter sends · Esc clears"

    bridge.submitGhostDraft()

    assert sent_messages == ["Plot safe harbor"]
    assert bridge.ghostCaptureActive is False
    assert bridge.ghostDraftText == ""
    assert bridge.assistant_state_value == "thinking"


def test_ui_bridge_workspace_sections_and_canvas_follow_active_destination(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.activateModule("helm")

    assert bridge.workspaceSections[0]["key"] == "overview"
    assert any(section["key"] == "hotkeys" for section in bridge.workspaceSections)
    assert bridge.workspaceCanvas["key"] == "helm"
    assert bridge.workspaceCanvas["title"] == "Helm"
    assert any(chip["label"] == "Ghost Shortcut" for chip in bridge.workspaceCanvas["chips"])

    bridge.activateWorkspaceSection("safety")

    assert bridge.workspaceCanvas["sectionKey"] == "safety"
    assert bridge.workspaceCanvas["eyebrow"] == "Control"


def test_ui_bridge_workspace_open_actions_create_opened_items(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_action(
        {
            "type": "workspace_open",
            "module": "browser",
            "section": "open-pages",
            "item": {
                "itemId": "page-1",
                "kind": "browser",
                "viewer": "browser",
                "title": "OpenAI Docs",
                "url": "https://platform.openai.com/docs",
            },
        }
    )

    assert bridge.mode_value == "deck"
    assert bridge.active_module_key == "browser"
    assert bridge.activeOpenedItem["itemId"] == "page-1"
    assert bridge.workspaceCanvas["activeItem"]["viewer"] == "browser"
    assert bridge.workspaceCanvas["openedItems"][0]["title"] == "OpenAI Docs"


def test_ui_bridge_workspace_restore_replaces_opened_items_and_tracks_focus(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_action(
        {
            "type": "workspace_restore",
            "module": "files",
            "section": "opened-items",
            "workspace": {
                "workspaceId": "ws-stormhelm",
                "name": "Stormhelm Internals",
                "topic": "stormhelm internals",
                "summary": "Continue the advanced internals buildout.",
            },
            "items": [
                {
                    "itemId": "item-a",
                    "kind": "text",
                    "viewer": "text",
                    "title": "README.md",
                    "path": "C:/Stormhelm/README.md",
                    "content": "# Stormhelm",
                },
                {
                    "itemId": "item-b",
                    "kind": "browser",
                    "viewer": "browser",
                    "title": "OpenAI Docs",
                    "url": "https://platform.openai.com/docs",
                },
            ],
            "active_item_id": "item-b",
        }
    )

    assert bridge.mode_value == "deck"
    assert bridge.active_module_key == "files"
    assert bridge.workspaceCanvas["title"] == "Stormhelm Internals"
    assert bridge.activeOpenedItem["itemId"] == "item-b"
    assert len(bridge.workspaceCanvas["openedItems"]) == 2
