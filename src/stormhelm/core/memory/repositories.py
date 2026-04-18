from __future__ import annotations

import json
from uuid import uuid4

from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.models import ChatMessageRecord, NoteRecord, SessionRecord
from stormhelm.shared.time import utc_now_iso


class ConversationRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def ensure_session(self, session_id: str = "default", title: str = "Primary Session") -> SessionRecord:
        timestamp = utc_now_iso()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_sessions(session_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at
                """,
                (session_id, title, timestamp, timestamp),
            )
            row = connection.execute(
                "SELECT session_id, title, created_at, updated_at FROM conversation_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return SessionRecord(**dict(row))

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> ChatMessageRecord:
        message = ChatMessageRecord(
            message_id=str(uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            created_at=utc_now_iso(),
            metadata=metadata or {},
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO chat_messages(message_id, session_id, role, content, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message.message_id,
                    message.session_id,
                    message.role,
                    message.content,
                    message.created_at,
                    json.dumps(message.metadata),
                ),
            )
            connection.execute(
                "UPDATE conversation_sessions SET updated_at = ? WHERE session_id = ?",
                (message.created_at, session_id),
            )
        return message

    def list_messages(self, session_id: str = "default", limit: int = 100) -> list[ChatMessageRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT message_id, session_id, role, content, created_at, metadata_json
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [
            ChatMessageRecord(
                message_id=row["message_id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in reversed(rows)
        ]


class NotesRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def create_note(self, title: str, content: str) -> NoteRecord:
        timestamp = utc_now_iso()
        note = NoteRecord(
            note_id=str(uuid4()),
            title=title.strip(),
            content=content.strip(),
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO notes(note_id, title, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (note.note_id, note.title, note.content, note.created_at, note.updated_at),
            )
        return note

    def list_notes(self, limit: int = 50) -> list[NoteRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT note_id, title, content, created_at, updated_at
                FROM notes
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [NoteRecord(**dict(row)) for row in rows]


class PreferencesRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def set_preference(self, key: str, value: object) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO preferences(preference_key, value_json)
                VALUES (?, ?)
                ON CONFLICT(preference_key) DO UPDATE SET value_json = excluded.value_json
                """,
                (key, json.dumps(value)),
            )

    def get_all(self) -> dict[str, object]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT preference_key, value_json FROM preferences ORDER BY preference_key"
            ).fetchall()
        return {row["preference_key"]: json.loads(row["value_json"]) for row in rows}


class ToolRunRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def upsert_run(
        self,
        *,
        job_id: str,
        tool_name: str,
        status: str,
        created_at: str,
        started_at: str | None,
        finished_at: str | None,
        input_payload: dict[str, object],
        result_payload: dict[str, object] | None,
        error_text: str | None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_runs(job_id, tool_name, status, created_at, started_at, finished_at, input_json, result_json, error_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    tool_name = excluded.tool_name,
                    status = excluded.status,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    input_json = excluded.input_json,
                    result_json = excluded.result_json,
                    error_text = excluded.error_text
                """,
                (
                    job_id,
                    tool_name,
                    status,
                    created_at,
                    started_at,
                    finished_at,
                    json.dumps(input_payload),
                    json.dumps(result_payload) if result_payload is not None else None,
                    error_text,
                ),
            )

    def list_recent(self, limit: int = 100) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id, tool_name, status, created_at, started_at, finished_at, input_json, result_json, error_text
                FROM tool_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "job_id": row["job_id"],
                "tool_name": row["tool_name"],
                "status": row["status"],
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "input_payload": json.loads(row["input_json"]),
                "result_payload": json.loads(row["result_json"]) if row["result_json"] else None,
                "error_text": row["error_text"],
            }
            for row in rows
        ]
