from __future__ import annotations

import hashlib
import logging
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


LOGGER = logging.getLogger(__name__)


class SQLiteDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._effective_path: Path | None = None

    @property
    def effective_path(self) -> Path:
        return self._effective_path or self.path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        target_path = self._resolve_connection_path()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(target_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA foreign_keys=ON;")
            connection.execute("PRAGMA busy_timeout=5000;")
            try:
                connection.execute("PRAGMA journal_mode=WAL;")
            except sqlite3.DatabaseError:
                connection.execute("PRAGMA journal_mode=DELETE;")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id)
                );

                CREATE TABLE IF NOT EXISTS notes (
                    note_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_runs (
                    job_id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    input_json TEXT NOT NULL,
                    result_json TEXT,
                    error_text TEXT
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    preference_key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    template_key TEXT NOT NULL DEFAULT '',
                    template_source TEXT NOT NULL DEFAULT '',
                    problem_domain TEXT NOT NULL DEFAULT '',
                    active_goal TEXT NOT NULL DEFAULT '',
                    current_task_state TEXT NOT NULL DEFAULT '',
                    last_completed_action TEXT NOT NULL DEFAULT '',
                    last_surface_mode TEXT NOT NULL DEFAULT '',
                    last_active_module TEXT NOT NULL DEFAULT '',
                    last_active_section TEXT NOT NULL DEFAULT '',
                    pending_next_steps_json TEXT NOT NULL DEFAULT '[]',
                    references_json TEXT NOT NULL DEFAULT '[]',
                    findings_json TEXT NOT NULL DEFAULT '[]',
                    session_notes_json TEXT NOT NULL DEFAULT '[]',
                    where_left_off TEXT NOT NULL DEFAULT '',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    archived_at TEXT NOT NULL DEFAULT '',
                    last_snapshot_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_opened_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspace_items (
                    item_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    viewer TEXT NOT NULL,
                    title TEXT NOT NULL,
                    subtitle TEXT NOT NULL,
                    module_key TEXT NOT NULL,
                    section_key TEXT NOT NULL,
                    url TEXT NOT NULL,
                    path TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    opened_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_opened_at TEXT NOT NULL,
                    UNIQUE(workspace_id, item_key),
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
                );

                CREATE TABLE IF NOT EXISTS workspace_activity (
                    activity_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
                );

                CREATE TABLE IF NOT EXISTS workspace_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id)
                );

                CREATE TABLE IF NOT EXISTS workspace_note_links (
                    link_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    note_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(workspace_id),
                    FOREIGN KEY(note_id) REFERENCES notes(note_id)
                );
                """
            )
            self._migrate_workspace_tables(connection)

    def _migrate_workspace_tables(self, connection: sqlite3.Connection) -> None:
        workspace_columns = self._column_names(connection, "workspaces")
        for definition in [
            ("title", "TEXT NOT NULL DEFAULT ''"),
            ("status", "TEXT NOT NULL DEFAULT ''"),
            ("category", "TEXT NOT NULL DEFAULT ''"),
            ("template_key", "TEXT NOT NULL DEFAULT ''"),
            ("template_source", "TEXT NOT NULL DEFAULT ''"),
            ("problem_domain", "TEXT NOT NULL DEFAULT ''"),
            ("active_goal", "TEXT NOT NULL DEFAULT ''"),
            ("current_task_state", "TEXT NOT NULL DEFAULT ''"),
            ("last_completed_action", "TEXT NOT NULL DEFAULT ''"),
            ("last_surface_mode", "TEXT NOT NULL DEFAULT ''"),
            ("last_active_module", "TEXT NOT NULL DEFAULT ''"),
            ("last_active_section", "TEXT NOT NULL DEFAULT ''"),
            ("pending_next_steps_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("references_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("findings_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("session_notes_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("where_left_off", "TEXT NOT NULL DEFAULT ''"),
            ("pinned", "INTEGER NOT NULL DEFAULT 0"),
            ("archived", "INTEGER NOT NULL DEFAULT 0"),
            ("archived_at", "TEXT NOT NULL DEFAULT ''"),
            ("last_snapshot_at", "TEXT NOT NULL DEFAULT ''"),
        ]:
            self._ensure_column(connection, "workspaces", workspace_columns, *definition)

    def _column_names(self, connection: sqlite3.Connection, table_name: str) -> set[str]:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row[1]) for row in rows}

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        existing_columns: set[str],
        column_name: str,
        column_definition: str,
    ) -> None:
        if column_name in existing_columns:
            return
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
        existing_columns.add(column_name)

    def _resolve_connection_path(self) -> Path:
        if self._effective_path is not None:
            return self._effective_path

        preferred = self.path
        try:
            self._probe_path(preferred)
            self._effective_path = preferred
            return preferred
        except sqlite3.DatabaseError as error:
            fallback = self._fallback_path()
            LOGGER.warning(
                "Primary SQLite path '%s' is unavailable (%s). Falling back to '%s'.",
                preferred,
                error,
                fallback,
            )
            self._probe_path(fallback)
            self._effective_path = fallback
            return fallback

    def _probe_path(self, candidate: Path) -> None:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(candidate, check_same_thread=False) as connection:
            connection.execute("PRAGMA journal_mode=DELETE;")
            connection.execute("CREATE TABLE IF NOT EXISTS __stormhelm_probe (id INTEGER PRIMARY KEY)")
            connection.execute("DELETE FROM __stormhelm_probe;")
            connection.execute("DROP TABLE IF EXISTS __stormhelm_probe;")
            connection.commit()

    def _fallback_path(self) -> Path:
        digest = hashlib.sha1(str(self.path).encode("utf-8")).hexdigest()[:12]
        return Path(tempfile.gettempdir()) / "stormhelm-runtime" / digest / self.path.name
