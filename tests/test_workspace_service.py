from __future__ import annotations

from pathlib import Path

from stormhelm.core.events import EventBuffer
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository
from stormhelm.core.workspace.service import WorkspaceService


def test_workspace_service_assembles_relevant_local_items(temp_project_root: Path, temp_config) -> None:
    docs_dir = temp_project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    target = docs_dir / "packaging-notes.md"
    target.write_text("Packaging workspace notes", encoding="utf-8")
    (temp_project_root / "README.md").write_text("Stormhelm root", encoding="utf-8")

    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    repository = WorkspaceRepository(database)
    service = WorkspaceService(
        config=temp_config,
        repository=repository,
        notes=notes,
        conversations=conversations,
        preferences=preferences,
        session_state=ConversationStateStore(preferences),
        indexer=WorkspaceIndexer(temp_config),
        events=EventBuffer(),
        persona=PersonaContract(temp_config),
    )

    result = service.assemble_workspace("set up a workspace for packaging", session_id="default")

    assert result["action"]["type"] == "workspace_restore"
    assert result["workspace"]["name"] == "Packaging"
    assert any(item.get("path", "").endswith("packaging-notes.md") for item in result["items"])


def test_workspace_service_restores_recent_workspace_memory(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    repository = WorkspaceRepository(database)
    state = ConversationStateStore(preferences)
    service = WorkspaceService(
        config=temp_config,
        repository=repository,
        notes=notes,
        conversations=conversations,
        preferences=preferences,
        session_state=state,
        indexer=WorkspaceIndexer(temp_config),
        events=EventBuffer(),
        persona=PersonaContract(temp_config),
    )

    workspace = repository.upsert_workspace(name="Stormhelm Packaging", topic="packaging", summary="Portable build work.")
    repository.upsert_item(
        workspace.workspace_id,
        {
            "kind": "browser",
            "viewer": "browser",
            "title": "PyInstaller Docs",
            "url": "https://pyinstaller.org/",
            "module": "browser",
            "section": "open-pages",
        },
    )
    state.set_active_workspace_id("default", workspace.workspace_id)

    result = service.restore_workspace("continue the packaging workspace", session_id="default")

    assert result["workspace"]["name"] == "Stormhelm Packaging"
    assert result["action"]["type"] == "workspace_restore"
    assert result["items"][0]["viewer"] == "browser"
