from __future__ import annotations

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

