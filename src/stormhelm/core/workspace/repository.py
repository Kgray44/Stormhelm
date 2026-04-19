from __future__ import annotations

import json
from uuid import uuid4

from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.workspace.models import WorkspaceItemRecord, WorkspaceRecord
from stormhelm.shared.time import utc_now_iso


class WorkspaceRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def upsert_workspace(
        self,
        *,
        name: str,
        topic: str,
        summary: str = "",
        tags: list[str] | None = None,
        workspace_id: str | None = None,
    ) -> WorkspaceRecord:
        timestamp = utc_now_iso()
        workspace = WorkspaceRecord(
            workspace_id=workspace_id or str(uuid4()),
            name=name.strip() or "Unnamed Workspace",
            topic=topic.strip() or name.strip() or "workspace",
            summary=summary.strip(),
            tags=list(tags or []),
            created_at=timestamp,
            updated_at=timestamp,
            last_opened_at=timestamp,
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workspaces(workspace_id, name, topic, summary, tags_json, created_at, updated_at, last_opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    name = excluded.name,
                    topic = excluded.topic,
                    summary = excluded.summary,
                    tags_json = excluded.tags_json,
                    updated_at = excluded.updated_at,
                    last_opened_at = excluded.last_opened_at
                """,
                (
                    workspace.workspace_id,
                    workspace.name,
                    workspace.topic,
                    workspace.summary,
                    json.dumps(workspace.tags),
                    workspace.created_at,
                    workspace.updated_at,
                    workspace.last_opened_at,
                ),
            )
            row = connection.execute(
                """
                SELECT workspace_id, name, topic, summary, tags_json, created_at, updated_at, last_opened_at
                FROM workspaces
                WHERE workspace_id = ?
                """,
                (workspace.workspace_id,),
            ).fetchone()
        return self._row_to_workspace(row)

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT workspace_id, name, topic, summary, tags_json, created_at, updated_at, last_opened_at
                FROM workspaces
                WHERE workspace_id = ?
                """,
                (workspace_id,),
            ).fetchone()
        return self._row_to_workspace(row) if row else None

    def search_workspaces(self, query: str, limit: int = 5) -> list[WorkspaceRecord]:
        pattern = f"%{query.strip().lower()}%"
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT workspace_id, name, topic, summary, tags_json, created_at, updated_at, last_opened_at
                FROM workspaces
                WHERE lower(name) LIKE ? OR lower(topic) LIKE ? OR lower(summary) LIKE ? OR lower(tags_json) LIKE ?
                ORDER BY COALESCE(last_opened_at, updated_at) DESC, updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, pattern, pattern, limit),
            ).fetchall()
        return [self._row_to_workspace(row) for row in rows]

    def upsert_item(self, workspace_id: str, item: dict[str, object], *, score: float = 0.0) -> WorkspaceItemRecord:
        timestamp = utc_now_iso()
        item_id = str(item.get("itemId") or uuid4())
        item_key = str(item.get("url") or item.get("path") or item.get("title") or item_id)
        payload = dict(item)
        payload.setdefault("itemId", item_id)
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workspace_items(
                    item_id, workspace_id, item_key, kind, viewer, title, subtitle, module_key, section_key,
                    url, path, summary, metadata_json, score, opened_count, created_at, updated_at, last_opened_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, item_key) DO UPDATE SET
                    kind = excluded.kind,
                    viewer = excluded.viewer,
                    title = excluded.title,
                    subtitle = excluded.subtitle,
                    module_key = excluded.module_key,
                    section_key = excluded.section_key,
                    url = excluded.url,
                    path = excluded.path,
                    summary = excluded.summary,
                    metadata_json = excluded.metadata_json,
                    score = excluded.score,
                    opened_count = workspace_items.opened_count + 1,
                    updated_at = excluded.updated_at,
                    last_opened_at = excluded.last_opened_at
                """,
                (
                    item_id,
                    workspace_id,
                    item_key,
                    str(item.get("kind", "text")),
                    str(item.get("viewer", item.get("kind", "text"))),
                    str(item.get("title", "Untitled")),
                    str(item.get("subtitle", "")),
                    str(item.get("module", "chartroom")),
                    str(item.get("section", "working-set")),
                    str(item.get("url", "")),
                    str(item.get("path", "")),
                    str(item.get("summary", "")),
                    json.dumps(payload),
                    float(score),
                    1,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                """
                SELECT item_id, workspace_id, item_key, kind, viewer, title, subtitle, module_key, section_key,
                       url, path, summary, metadata_json, score, opened_count, created_at, updated_at, last_opened_at
                FROM workspace_items
                WHERE workspace_id = ? AND item_key = ?
                """,
                (workspace_id, item_key),
            ).fetchone()
        return self._row_to_item(row)

    def list_items(self, workspace_id: str, limit: int = 12) -> list[WorkspaceItemRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT item_id, workspace_id, item_key, kind, viewer, title, subtitle, module_key, section_key,
                       url, path, summary, metadata_json, score, opened_count, created_at, updated_at, last_opened_at
                FROM workspace_items
                WHERE workspace_id = ?
                ORDER BY COALESCE(last_opened_at, updated_at) DESC, score DESC
                LIMIT ?
                """,
                (workspace_id, limit),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def record_activity(
        self,
        *,
        workspace_id: str,
        session_id: str,
        activity_type: str,
        description: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workspace_activity(activity_id, workspace_id, session_id, activity_type, description, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    workspace_id,
                    session_id,
                    activity_type,
                    description,
                    json.dumps(payload or {}),
                    utc_now_iso(),
                ),
            )

    def _row_to_workspace(self, row) -> WorkspaceRecord:
        return WorkspaceRecord(
            workspace_id=row["workspace_id"],
            name=row["name"],
            topic=row["topic"],
            summary=row["summary"],
            tags=json.loads(row["tags_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_opened_at=row["last_opened_at"],
        )

    def _row_to_item(self, row) -> WorkspaceItemRecord:
        return WorkspaceItemRecord(
            item_id=row["item_id"],
            workspace_id=row["workspace_id"],
            item_key=row["item_key"],
            kind=row["kind"],
            viewer=row["viewer"],
            title=row["title"],
            subtitle=row["subtitle"],
            module_key=row["module_key"],
            section_key=row["section_key"],
            url=row["url"],
            path=row["path"],
            summary=row["summary"],
            metadata=json.loads(row["metadata_json"]),
            score=float(row["score"]),
            opened_count=int(row["opened_count"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_opened_at=row["last_opened_at"],
        )
