from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository
from stormhelm.shared.paths import ensure_runtime_directories


def test_storage_round_trip_for_messages_and_notes(temp_config) -> None:
    ensure_runtime_directories(
        [
            temp_config.storage.data_dir,
            temp_config.storage.logs_dir,
            temp_config.storage.database_path.parent,
        ]
    )
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()

    conversations = ConversationRepository(database)
    notes = NotesRepository(database)

    conversations.ensure_session()
    conversations.add_message("default", "user", "Hello Stormhelm")
    conversations.add_message("default", "assistant", "Hello operator")
    notes.create_note("Reminder", "Keep the architecture modular.")

    messages = conversations.list_messages()
    saved_notes = notes.list_notes()

    assert [item.content for item in messages] == ["Hello Stormhelm", "Hello operator"]
    assert saved_notes[0].title == "Reminder"


def test_sqlite_database_falls_back_when_primary_path_is_unavailable(monkeypatch, workspace_temp_dir: Path) -> None:
    database = SQLiteDatabase(workspace_temp_dir / "stormhelm.db")
    original_probe = SQLiteDatabase._probe_path

    def flaky_probe(self: SQLiteDatabase, candidate: Path) -> None:
        if candidate == database.path:
            raise sqlite3.OperationalError("disk I/O error")
        original_probe(self, candidate)

    monkeypatch.setattr(SQLiteDatabase, "_probe_path", flaky_probe)

    database.initialize()

    assert database.effective_path != database.path
    assert Path(tempfile.gettempdir()) in database.effective_path.parents
