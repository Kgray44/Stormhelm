from __future__ import annotations

import json
from uuid import uuid4

from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.models import (
    ChatMessageRecord,
    MemoryMatch,
    MemoryProvenance,
    MemoryQuery,
    MemoryRecord,
    MemoryResult,
    NoteRecord,
    SessionRecord,
)
from stormhelm.shared.json_safety import decode_json_dict, decode_json_list, decode_json_value
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
                metadata=decode_json_dict(
                    row["metadata_json"],
                    context=f"chat_messages.metadata_json[{row['message_id']}]",
                ),
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
        return {
            row["preference_key"]: decode_json_value(
                row["value_json"],
                context=f"preferences.value_json[{row['preference_key']}]",
            )
            for row in rows
        }


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


class SemanticMemoryRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save_record(self, record: MemoryRecord) -> MemoryRecord:
        existing = self.get_by_dedupe_key(record.dedupe_key) if record.dedupe_key else None
        memory_id = existing.memory_id if existing is not None else record.memory_id
        created_at = existing.created_at if existing is not None else (record.created_at or utc_now_iso())
        updated_at = record.updated_at or utc_now_iso()
        payload = MemoryRecord(
            memory_id=memory_id,
            dedupe_key=record.dedupe_key,
            memory_family=record.memory_family,
            source_class=record.source_class,
            title=record.title,
            summary=record.summary,
            normalized_content=record.normalized_content,
            structured_fields=dict(record.structured_fields),
            provenance=record.provenance,
            confidence=float(record.confidence),
            freshness_state=record.freshness_state,
            created_at=created_at,
            updated_at=updated_at,
            last_validated_at=record.last_validated_at,
            retention_policy=record.retention_policy,
            sensitivity_level=record.sensitivity_level,
            related_session_id=record.related_session_id,
            related_task_ids=list(record.related_task_ids),
            related_workspace_ids=list(record.related_workspace_ids),
            related_artifact_refs=list(record.related_artifact_refs),
            tags=list(record.tags),
            semantic_tokens=list(record.semantic_tokens),
            last_accessed_at=record.last_accessed_at,
            access_count=int(record.access_count),
            archived=bool(record.archived),
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_records(
                    memory_id, dedupe_key, memory_family, source_class, title, summary, normalized_content,
                    structured_fields_json, provenance_json, confidence, freshness_state, created_at, updated_at,
                    last_validated_at, retention_policy, sensitivity_level, related_session_id, related_task_ids_json,
                    related_workspace_ids_json, related_artifact_refs_json, tags_json, semantic_tokens_json,
                    last_accessed_at, access_count, archived
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    dedupe_key = excluded.dedupe_key,
                    memory_family = excluded.memory_family,
                    source_class = excluded.source_class,
                    title = excluded.title,
                    summary = excluded.summary,
                    normalized_content = excluded.normalized_content,
                    structured_fields_json = excluded.structured_fields_json,
                    provenance_json = excluded.provenance_json,
                    confidence = excluded.confidence,
                    freshness_state = excluded.freshness_state,
                    updated_at = excluded.updated_at,
                    last_validated_at = excluded.last_validated_at,
                    retention_policy = excluded.retention_policy,
                    sensitivity_level = excluded.sensitivity_level,
                    related_session_id = excluded.related_session_id,
                    related_task_ids_json = excluded.related_task_ids_json,
                    related_workspace_ids_json = excluded.related_workspace_ids_json,
                    related_artifact_refs_json = excluded.related_artifact_refs_json,
                    tags_json = excluded.tags_json,
                    semantic_tokens_json = excluded.semantic_tokens_json,
                    last_accessed_at = excluded.last_accessed_at,
                    access_count = excluded.access_count,
                    archived = excluded.archived
                """,
                (
                    payload.memory_id,
                    payload.dedupe_key,
                    payload.memory_family,
                    payload.source_class,
                    payload.title,
                    payload.summary,
                    payload.normalized_content,
                    json.dumps(payload.structured_fields),
                    json.dumps(payload.provenance.to_dict()),
                    payload.confidence,
                    payload.freshness_state,
                    payload.created_at,
                    payload.updated_at,
                    payload.last_validated_at,
                    payload.retention_policy,
                    payload.sensitivity_level,
                    payload.related_session_id,
                    json.dumps(payload.related_task_ids),
                    json.dumps(payload.related_workspace_ids),
                    json.dumps(payload.related_artifact_refs),
                    json.dumps(payload.tags),
                    json.dumps(payload.semantic_tokens),
                    payload.last_accessed_at,
                    payload.access_count,
                    1 if payload.archived else 0,
                ),
            )
        return self.get_record(payload.memory_id) or payload

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT memory_id, dedupe_key, memory_family, source_class, title, summary, normalized_content,
                       structured_fields_json, provenance_json, confidence, freshness_state, created_at, updated_at,
                       last_validated_at, retention_policy, sensitivity_level, related_session_id, related_task_ids_json,
                       related_workspace_ids_json, related_artifact_refs_json, tags_json, semantic_tokens_json,
                       last_accessed_at, access_count, archived
                FROM memory_records
                WHERE memory_id = ?
                """,
                (memory_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_by_dedupe_key(self, dedupe_key: str) -> MemoryRecord | None:
        if not dedupe_key:
            return None
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT memory_id, dedupe_key, memory_family, source_class, title, summary, normalized_content,
                       structured_fields_json, provenance_json, confidence, freshness_state, created_at, updated_at,
                       last_validated_at, retention_policy, sensitivity_level, related_session_id, related_task_ids_json,
                       related_workspace_ids_json, related_artifact_refs_json, tags_json, semantic_tokens_json,
                       last_accessed_at, access_count, archived
                FROM memory_records
                WHERE dedupe_key = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (dedupe_key,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_records(
        self,
        *,
        families: list[str] | None = None,
        related_session_id: str | None = None,
        include_archived: bool = False,
        limit: int = 200,
    ) -> list[MemoryRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if families:
            placeholders = ", ".join("?" for _ in families)
            clauses.append(f"memory_family IN ({placeholders})")
            params.extend(families)
        if related_session_id:
            clauses.append("related_session_id = ?")
            params.append(related_session_id)
        if not include_archived:
            clauses.append("archived = 0")
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT memory_id, dedupe_key, memory_family, source_class, title, summary, normalized_content,
                       structured_fields_json, provenance_json, confidence, freshness_state, created_at, updated_at,
                       last_validated_at, retention_policy, sensitivity_level, related_session_id, related_task_ids_json,
                       related_workspace_ids_json, related_artifact_refs_json, tags_json, semantic_tokens_json,
                       last_accessed_at, access_count, archived
                FROM memory_records
                {where_clause}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def mark_accessed(self, memory_id: str, *, accessed_at: str | None = None) -> None:
        timestamp = accessed_at or utc_now_iso()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE memory_records
                SET last_accessed_at = ?, access_count = access_count + 1
                WHERE memory_id = ?
                """,
                (timestamp, memory_id),
            )

    def delete_records_before(self, *, family: str, cutoff: str) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM memory_records
                WHERE memory_family = ? AND updated_at < ?
                """,
                (family, cutoff),
            )
        return int(cursor.rowcount or 0)

    def trim_records(self, *, family: str, limit: int) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM memory_records
                WHERE memory_id IN (
                    SELECT memory_id
                    FROM memory_records
                    WHERE memory_family = ?
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (family, max(int(limit), 0)),
            )
        return int(cursor.rowcount or 0)

    def count_by_family(self) -> dict[str, int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT memory_family, COUNT(*) AS count
                FROM memory_records
                WHERE archived = 0
                GROUP BY memory_family
                ORDER BY memory_family
                """
            ).fetchall()
        return {str(row["memory_family"]): int(row["count"]) for row in rows}

    def log_query(self, query: MemoryQuery, result: MemoryResult) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_query_log(
                    query_id, retrieval_intent, requested_families_json, caller_subsystem, semantic_query_text,
                    structured_filters_json, scope_constraints_json, matched_record_ids_json, family_distribution_json,
                    filtered_out_counts_json, retrieval_trace_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query.query_id,
                    query.retrieval_intent,
                    json.dumps(query.requested_families),
                    query.caller_subsystem,
                    query.semantic_query_text,
                    json.dumps(query.structured_filters),
                    json.dumps(query.scope_constraints),
                    json.dumps([match.record.memory_id for match in result.matched_records]),
                    json.dumps(result.family_distribution),
                    json.dumps(result.filtered_out_counts),
                    json.dumps(result.retrieval_trace),
                    utc_now_iso(),
                ),
            )

    def update_query_trace(self, query_id: str, retrieval_trace: dict[str, object]) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE memory_query_log
                SET retrieval_trace_json = ?
                WHERE query_id = ?
                """,
                (json.dumps(retrieval_trace), query_id),
            )

    def delete_query_logs_before(self, *, cutoff: str) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM memory_query_log
                WHERE created_at < ?
                """,
                (cutoff,),
            )
        return int(cursor.rowcount or 0)

    def trim_query_log(self, *, limit: int) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM memory_query_log
                WHERE query_id IN (
                    SELECT query_id
                    FROM memory_query_log
                    ORDER BY created_at DESC, query_id DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (max(int(limit), 0),),
            )
        return int(cursor.rowcount or 0)

    def list_recent_queries(self, *, limit: int = 25) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT query_id, retrieval_intent, requested_families_json, caller_subsystem, semantic_query_text,
                       structured_filters_json, scope_constraints_json, matched_record_ids_json, family_distribution_json,
                       filtered_out_counts_json, retrieval_trace_json, created_at
                FROM memory_query_log
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "query_id": row["query_id"],
                "retrieval_intent": row["retrieval_intent"],
                "requested_families": decode_json_list(
                    row["requested_families_json"],
                    context=f"memory_query_log.requested_families_json[{row['query_id']}]",
                ),
                "caller_subsystem": row["caller_subsystem"],
                "semantic_query_text": row["semantic_query_text"],
                "structured_filters": decode_json_dict(
                    row["structured_filters_json"],
                    context=f"memory_query_log.structured_filters_json[{row['query_id']}]",
                ),
                "scope_constraints": decode_json_dict(
                    row["scope_constraints_json"],
                    context=f"memory_query_log.scope_constraints_json[{row['query_id']}]",
                ),
                "matched_record_ids": decode_json_list(
                    row["matched_record_ids_json"],
                    context=f"memory_query_log.matched_record_ids_json[{row['query_id']}]",
                ),
                "family_distribution": decode_json_dict(
                    row["family_distribution_json"],
                    context=f"memory_query_log.family_distribution_json[{row['query_id']}]",
                ),
                "filtered_out_counts": decode_json_dict(
                    row["filtered_out_counts_json"],
                    context=f"memory_query_log.filtered_out_counts_json[{row['query_id']}]",
                ),
                "retrieval_trace": decode_json_dict(
                    row["retrieval_trace_json"],
                    context=f"memory_query_log.retrieval_trace_json[{row['query_id']}]",
                ),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _row_to_record(self, row) -> MemoryRecord:
        provenance = decode_json_dict(row["provenance_json"], context=f"memory_records.provenance_json[{row['memory_id']}]")
        return MemoryRecord(
            memory_id=row["memory_id"],
            dedupe_key=row["dedupe_key"],
            memory_family=row["memory_family"],
            source_class=row["source_class"],
            title=row["title"],
            summary=row["summary"],
            normalized_content=row["normalized_content"],
            structured_fields=decode_json_dict(
                row["structured_fields_json"],
                context=f"memory_records.structured_fields_json[{row['memory_id']}]",
            ),
            provenance=MemoryProvenance(
                origin_subsystem=str(provenance.get("originSubsystem") or ""),
                origin_surface=str(provenance.get("originSurface") or ""),
                operator_provided=bool(provenance.get("operatorProvided", False)),
                inferred=bool(provenance.get("inferred", False)),
                verification_state=str(provenance.get("verificationState") or "unverified"),
                source_artifact_refs=[
                    str(value).strip()
                    for value in provenance.get("sourceArtifactRefs", [])
                    if str(value).strip()
                ]
                if isinstance(provenance.get("sourceArtifactRefs"), list)
                else [],
                source_event_refs=[
                    str(value).strip()
                    for value in provenance.get("sourceEventRefs", [])
                    if str(value).strip()
                ]
                if isinstance(provenance.get("sourceEventRefs"), list)
                else [],
                source_task_ref=str(provenance.get("sourceTaskRef") or ""),
                source_workspace_ref=str(provenance.get("sourceWorkspaceRef") or ""),
                source_session_ref=str(provenance.get("sourceSessionRef") or ""),
            ),
            confidence=float(row["confidence"] or 0.0),
            freshness_state=row["freshness_state"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_validated_at=row["last_validated_at"],
            retention_policy=row["retention_policy"],
            sensitivity_level=row["sensitivity_level"],
            related_session_id=row["related_session_id"],
            related_task_ids=[
                str(value).strip()
                for value in decode_json_list(
                    row["related_task_ids_json"],
                    context=f"memory_records.related_task_ids_json[{row['memory_id']}]",
                )
                if str(value).strip()
            ],
            related_workspace_ids=[
                str(value).strip()
                for value in decode_json_list(
                    row["related_workspace_ids_json"],
                    context=f"memory_records.related_workspace_ids_json[{row['memory_id']}]",
                )
                if str(value).strip()
            ],
            related_artifact_refs=[
                str(value).strip()
                for value in decode_json_list(
                    row["related_artifact_refs_json"],
                    context=f"memory_records.related_artifact_refs_json[{row['memory_id']}]",
                )
                if str(value).strip()
            ],
            tags=[
                str(value).strip()
                for value in decode_json_list(
                    row["tags_json"],
                    context=f"memory_records.tags_json[{row['memory_id']}]",
                )
                if str(value).strip()
            ],
            semantic_tokens=[
                str(value).strip()
                for value in decode_json_list(
                    row["semantic_tokens_json"],
                    context=f"memory_records.semantic_tokens_json[{row['memory_id']}]",
                )
                if str(value).strip()
            ],
            last_accessed_at=row["last_accessed_at"],
            access_count=int(row["access_count"] or 0),
            archived=bool(row["archived"]),
        )
