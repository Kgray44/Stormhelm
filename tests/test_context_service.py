from __future__ import annotations

from stormhelm.core.context.service import ActiveContextService
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.core.orchestrator.session_state import ConversationStateStore


def _service(temp_config) -> ActiveContextService:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    preferences = PreferencesRepository(database)
    session_state = ConversationStateStore(preferences)
    return ActiveContextService(session_state)


def test_active_context_service_classifies_clipboard_url_and_code(temp_config) -> None:
    service = _service(temp_config)

    url_snapshot = service.classify_clipboard("https://example.com/docs?q=stormhelm")
    code_snapshot = service.classify_clipboard("def hello(name):\n    return f'hello {name}'\n")

    assert url_snapshot["kind"] == "url"
    assert url_snapshot["value"] == "https://example.com/docs?q=stormhelm"
    assert code_snapshot["kind"] == "code"
    assert "def hello" in code_snapshot["preview"]


def test_active_context_service_prefers_selection_and_tracks_recent_entities(temp_config) -> None:
    service = _service(temp_config)

    service.update_from_turn(
        session_id="default",
        workspace_context={
            "workspace": {"workspaceId": "ws-1", "name": "Packaging Workspace", "topic": "packaging"},
            "opened_items": [
                {"itemId": "item-1", "title": "README.md", "path": "C:/Stormhelm/README.md", "kind": "markdown"},
                {"itemId": "item-2", "title": "notes.txt", "path": "C:/Stormhelm/notes.txt", "kind": "text"},
            ],
            "active_item": {"itemId": "item-2", "title": "notes.txt", "path": "C:/Stormhelm/notes.txt", "kind": "text"},
        },
        active_posture={
            "active_goal": "Finish packaging cleanup",
            "pending_next_steps": ["Verify installer", "Update release notes"],
            "last_completed_action": "Collected packaging notes.",
        },
        active_request_state={"family": "workspace", "request_type": "workspace_restore"},
        recent_tool_results=[],
        input_context={
            "selection": {"kind": "text", "value": "selected notes block", "preview": "selected notes block"},
            "clipboard": {"kind": "url", "value": "https://example.com/packaging", "preview": "https://example.com/packaging"},
        },
    )

    snapshot = service.snapshot("default")

    assert snapshot["active_goal"] == "Finish packaging cleanup"
    assert snapshot["workspace"]["workspaceId"] == "ws-1"
    assert snapshot["selection"]["kind"] == "text"
    assert snapshot["clipboard"]["kind"] == "url"
    assert snapshot["recent_entities"][0]["title"] == "notes.txt"
    assert snapshot["recent_entities"][1]["title"] == "README.md"
