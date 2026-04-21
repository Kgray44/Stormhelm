from __future__ import annotations

import json
from uuid import uuid4

from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.workspace.models import WorkspaceItemRecord, WorkspaceRecord, WorkspaceSnapshotRecord
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
        title: str = "",
        status: str = "",
        category: str = "",
        template_key: str = "",
        template_source: str = "",
        problem_domain: str = "",
        active_goal: str = "",
        current_task_state: str = "",
        last_completed_action: str = "",
        last_surface_mode: str = "",
        last_active_module: str = "",
        last_active_section: str = "",
        pending_next_steps: list[str] | None = None,
        references: list[dict[str, object]] | None = None,
        findings: list[dict[str, object]] | None = None,
        session_notes: list[dict[str, object]] | None = None,
        where_left_off: str = "",
        pinned: bool = False,
        archived: bool = False,
        archived_at: str = "",
        last_snapshot_at: str = "",
        tags: list[str] | None = None,
        workspace_id: str | None = None,
    ) -> WorkspaceRecord:
        timestamp = utc_now_iso()
        workspace = WorkspaceRecord(
            workspace_id=workspace_id or str(uuid4()),
            name=name.strip() or "Unnamed Workspace",
            topic=topic.strip() or name.strip() or "workspace",
            summary=summary.strip(),
            title=title.strip() or name.strip() or "Unnamed Workspace",
            status=status.strip(),
            category=category.strip(),
            template_key=template_key.strip(),
            template_source=template_source.strip(),
            problem_domain=problem_domain.strip(),
            active_goal=active_goal.strip(),
            current_task_state=current_task_state.strip(),
            last_completed_action=last_completed_action.strip(),
            last_surface_mode=last_surface_mode.strip(),
            last_active_module=last_active_module.strip(),
            last_active_section=last_active_section.strip(),
            pending_next_steps=list(pending_next_steps or []),
            references=list(references or []),
            findings=list(findings or []),
            session_notes=list(session_notes or []),
            where_left_off=where_left_off.strip(),
            pinned=bool(pinned),
            archived=bool(archived),
            archived_at=archived_at.strip(),
            last_snapshot_at=last_snapshot_at.strip(),
            tags=list(tags or []),
            created_at=timestamp,
            updated_at=timestamp,
            last_opened_at=timestamp,
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workspaces(
                    workspace_id, name, topic, summary, title, status, category, template_key, template_source,
                    problem_domain, active_goal, current_task_state, last_completed_action, last_surface_mode,
                    last_active_module, last_active_section, pending_next_steps_json, references_json, findings_json,
                    session_notes_json, where_left_off, pinned, archived, archived_at, last_snapshot_at,
                    tags_json, created_at, updated_at, last_opened_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id) DO UPDATE SET
                    name = excluded.name,
                    topic = excluded.topic,
                    summary = excluded.summary,
                    title = excluded.title,
                    status = excluded.status,
                    category = excluded.category,
                    template_key = excluded.template_key,
                    template_source = excluded.template_source,
                    problem_domain = excluded.problem_domain,
                    active_goal = excluded.active_goal,
                    current_task_state = excluded.current_task_state,
                    last_completed_action = excluded.last_completed_action,
                    last_surface_mode = excluded.last_surface_mode,
                    last_active_module = excluded.last_active_module,
                    last_active_section = excluded.last_active_section,
                    pending_next_steps_json = excluded.pending_next_steps_json,
                    references_json = excluded.references_json,
                    findings_json = excluded.findings_json,
                    session_notes_json = excluded.session_notes_json,
                    where_left_off = excluded.where_left_off,
                    pinned = excluded.pinned,
                    archived = excluded.archived,
                    archived_at = excluded.archived_at,
                    last_snapshot_at = excluded.last_snapshot_at,
                    tags_json = excluded.tags_json,
                    updated_at = excluded.updated_at,
                    last_opened_at = excluded.last_opened_at
                """,
                (
                    workspace.workspace_id,
                    workspace.name,
                    workspace.topic,
                    workspace.summary,
                    workspace.title,
                    workspace.status,
                    workspace.category,
                    workspace.template_key,
                    workspace.template_source,
                    workspace.problem_domain,
                    workspace.active_goal,
                    workspace.current_task_state,
                    workspace.last_completed_action,
                    workspace.last_surface_mode,
                    workspace.last_active_module,
                    workspace.last_active_section,
                    json.dumps(workspace.pending_next_steps),
                    json.dumps(workspace.references),
                    json.dumps(workspace.findings),
                    json.dumps(workspace.session_notes),
                    workspace.where_left_off,
                    1 if workspace.pinned else 0,
                    1 if workspace.archived else 0,
                    workspace.archived_at,
                    workspace.last_snapshot_at,
                    json.dumps(workspace.tags),
                    workspace.created_at,
                    workspace.updated_at,
                    workspace.last_opened_at,
                ),
            )
            row = self._select_workspace_row(connection, workspace.workspace_id)
        return self._row_to_workspace(row)

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        with self.database.connect() as connection:
            row = self._select_workspace_row(connection, workspace_id)
        return self._row_to_workspace(row) if row else None

    def search_workspaces(
        self,
        query: str,
        limit: int = 5,
        *,
        include_archived: bool = False,
        archived_only: bool = False,
    ) -> list[WorkspaceRecord]:
        pattern = f"%{query.strip().lower()}%"
        if archived_only:
            archive_clause = "WHERE archived = 1"
        elif include_archived:
            archive_clause = "WHERE 1 = 1"
        else:
            archive_clause = "WHERE archived = 0"
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT workspace_id, name, topic, summary, title, status, category, template_key, template_source,
                       problem_domain, active_goal, current_task_state, last_completed_action, last_surface_mode,
                       last_active_module, last_active_section, pending_next_steps_json, references_json, findings_json,
                       session_notes_json, where_left_off, pinned, archived, archived_at, last_snapshot_at,
                       tags_json, created_at, updated_at, last_opened_at
                FROM workspaces
                """
                + archive_clause
                + """
                  AND (
                    lower(name) LIKE ? OR lower(topic) LIKE ? OR lower(summary) LIKE ? OR lower(tags_json) LIKE ?
                    OR lower(title) LIKE ? OR lower(active_goal) LIKE ? OR lower(where_left_off) LIKE ?
                  )
                ORDER BY COALESCE(last_opened_at, updated_at) DESC, updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, pattern, pattern, pattern, pattern, pattern, limit),
            ).fetchall()
        return [self._row_to_workspace(row) for row in rows]

    def list_workspaces(
        self,
        *,
        limit: int = 20,
        include_archived: bool = False,
        archived_only: bool = False,
    ) -> list[WorkspaceRecord]:
        if archived_only:
            clause = "WHERE archived = 1"
        elif include_archived:
            clause = ""
        else:
            clause = "WHERE archived = 0"
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT workspace_id, name, topic, summary, title, status, category, template_key, template_source,
                       problem_domain, active_goal, current_task_state, last_completed_action, last_surface_mode,
                       last_active_module, last_active_section, pending_next_steps_json, references_json, findings_json,
                       session_notes_json, where_left_off, pinned, archived, archived_at, last_snapshot_at,
                       tags_json, created_at, updated_at, last_opened_at
                FROM workspaces
                """
                + clause
                + """
                ORDER BY pinned DESC, COALESCE(last_opened_at, updated_at) DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_workspace(row) for row in rows]

    def touch_workspace(self, workspace_id: str) -> None:
        timestamp = utc_now_iso()
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE workspaces SET updated_at = ?, last_opened_at = ? WHERE workspace_id = ?",
                (timestamp, timestamp, workspace_id),
            )

    def rename_workspace(self, workspace_id: str, new_name: str) -> WorkspaceRecord | None:
        clean_name = new_name.strip()
        if not clean_name:
            return self.get_workspace(workspace_id)
        timestamp = utc_now_iso()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE workspaces
                SET name = ?, title = ?, updated_at = ?, last_opened_at = ?
                WHERE workspace_id = ?
                """,
                (clean_name, clean_name, timestamp, timestamp, workspace_id),
            )
            row = self._select_workspace_row(connection, workspace_id)
        return self._row_to_workspace(row) if row else None

    def set_tags(self, workspace_id: str, tags: list[str]) -> WorkspaceRecord | None:
        timestamp = utc_now_iso()
        clean_tags = [tag.strip() for tag in tags if tag and tag.strip()]
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE workspaces
                SET tags_json = ?, updated_at = ?, last_opened_at = ?
                WHERE workspace_id = ?
                """,
                (json.dumps(clean_tags), timestamp, timestamp, workspace_id),
            )
            row = self._select_workspace_row(connection, workspace_id)
        return self._row_to_workspace(row) if row else None

    def set_archived(self, workspace_id: str, archived: bool) -> WorkspaceRecord | None:
        timestamp = utc_now_iso()
        archived_at = timestamp if archived else ""
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE workspaces
                SET archived = ?, archived_at = ?, updated_at = ?, last_opened_at = ?
                WHERE workspace_id = ?
                """,
                (1 if archived else 0, archived_at, timestamp, timestamp, workspace_id),
            )
            row = self._select_workspace_row(connection, workspace_id)
        return self._row_to_workspace(row) if row else None

    def save_snapshot(
        self,
        *,
        workspace_id: str,
        session_id: str,
        summary: str,
        payload: dict[str, object],
    ) -> WorkspaceSnapshotRecord:
        snapshot = WorkspaceSnapshotRecord(
            snapshot_id=str(uuid4()),
            workspace_id=workspace_id,
            session_id=session_id,
            summary=summary.strip(),
            payload=dict(payload),
            created_at=utc_now_iso(),
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workspace_snapshots(snapshot_id, workspace_id, session_id, summary, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.workspace_id,
                    snapshot.session_id,
                    snapshot.summary,
                    json.dumps(snapshot.payload),
                    snapshot.created_at,
                ),
            )
            connection.execute(
                """
                UPDATE workspaces
                SET last_snapshot_at = ?, updated_at = ?, last_opened_at = ?
                WHERE workspace_id = ?
                """,
                (snapshot.created_at, snapshot.created_at, snapshot.created_at, workspace_id),
            )
        return snapshot

    def get_latest_snapshot(self, workspace_id: str) -> WorkspaceSnapshotRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot_id, workspace_id, session_id, summary, payload_json, created_at
                FROM workspace_snapshots
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
        return self._row_to_snapshot(row) if row else None

    def link_note(self, workspace_id: str, note_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workspace_note_links(link_id, workspace_id, note_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid4()), workspace_id, note_id, utc_now_iso()),
            )

    def list_linked_notes(self, workspace_id: str, limit: int = 12) -> list[str]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT note_id
                FROM workspace_note_links
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (workspace_id, limit),
            ).fetchall()
        return [str(row["note_id"]) for row in rows]

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
            title=row["title"],
            status=row["status"],
            category=row["category"],
            template_key=row["template_key"],
            template_source=row["template_source"],
            problem_domain=row["problem_domain"],
            active_goal=row["active_goal"],
            current_task_state=row["current_task_state"],
            last_completed_action=row["last_completed_action"],
            last_surface_mode=row["last_surface_mode"],
            last_active_module=row["last_active_module"],
            last_active_section=row["last_active_section"],
            pending_next_steps=json.loads(row["pending_next_steps_json"]),
            references=json.loads(row["references_json"]),
            findings=json.loads(row["findings_json"]),
            session_notes=json.loads(row["session_notes_json"]),
            where_left_off=row["where_left_off"],
            pinned=bool(row["pinned"]),
            archived=bool(row["archived"]),
            archived_at=row["archived_at"],
            last_snapshot_at=row["last_snapshot_at"],
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

    def _row_to_snapshot(self, row) -> WorkspaceSnapshotRecord:
        return WorkspaceSnapshotRecord(
            snapshot_id=row["snapshot_id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            summary=row["summary"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )

    def _select_workspace_row(self, connection, workspace_id: str):
        return connection.execute(
            """
            SELECT workspace_id, name, topic, summary, title, status, category, template_key, template_source,
                   problem_domain, active_goal, current_task_state, last_completed_action, last_surface_mode,
                   last_active_module, last_active_section, pending_next_steps_json, references_json, findings_json,
                   session_notes_json, where_left_off, pinned, archived, archived_at, last_snapshot_at,
                   tags_json, created_at, updated_at, last_opened_at
            FROM workspaces
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
