from __future__ import annotations

import json

from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.tasks.models import (
    TaskArtifactRecord,
    TaskBlockerRecord,
    TaskCheckpointRecord,
    TaskDependencyRecord,
    TaskEvidenceRecord,
    TaskJobLinkRecord,
    TaskRecord,
    TaskStepRecord,
)
from stormhelm.shared.json_safety import decode_json_dict


class TaskRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save_task(self, task: TaskRecord) -> TaskRecord:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks(
                    task_id, session_id, workspace_id, title, summary, goal, origin, state, recovery_state,
                    latest_summary, evidence_summary, where_left_off, active_step_id, last_completed_step_id,
                    hooks_json, metadata_json, created_at, updated_at, started_at, finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    workspace_id = excluded.workspace_id,
                    title = excluded.title,
                    summary = excluded.summary,
                    goal = excluded.goal,
                    origin = excluded.origin,
                    state = excluded.state,
                    recovery_state = excluded.recovery_state,
                    latest_summary = excluded.latest_summary,
                    evidence_summary = excluded.evidence_summary,
                    where_left_off = excluded.where_left_off,
                    active_step_id = excluded.active_step_id,
                    last_completed_step_id = excluded.last_completed_step_id,
                    hooks_json = excluded.hooks_json,
                    metadata_json = excluded.metadata_json,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at
                """,
                (
                    task.task_id,
                    task.session_id,
                    task.workspace_id,
                    task.title,
                    task.summary,
                    task.goal,
                    task.origin,
                    task.state,
                    task.recovery_state,
                    task.latest_summary,
                    task.evidence_summary,
                    task.where_left_off,
                    task.active_step_id,
                    task.last_completed_step_id,
                    json.dumps(task.hooks),
                    json.dumps(task.metadata),
                    task.created_at,
                    task.updated_at,
                    task.started_at,
                    task.finished_at,
                ),
            )

            for table_name in (
                "task_steps",
                "task_dependencies",
                "task_blockers",
                "task_checkpoints",
                "task_artifacts",
                "task_evidence",
                "task_job_links",
            ):
                connection.execute(f"DELETE FROM {table_name} WHERE task_id = ?", (task.task_id,))

            for step in task.steps:
                connection.execute(
                    """
                    INSERT INTO task_steps(
                        step_id, task_id, sequence_index, title, detail, tool_name, tool_arguments_json,
                        state, summary, started_at, finished_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        step.step_id,
                        step.task_id,
                        step.sequence_index,
                        step.title,
                        step.detail,
                        step.tool_name,
                        json.dumps(step.tool_arguments),
                        step.state,
                        step.summary,
                        step.started_at,
                        step.finished_at,
                    ),
                )

            for dependency in task.dependencies:
                connection.execute(
                    """
                    INSERT INTO task_dependencies(
                        dependency_id, task_id, step_id, depends_on_step_id, dependency_kind
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        dependency.dependency_id,
                        dependency.task_id,
                        dependency.step_id,
                        dependency.depends_on_step_id,
                        dependency.dependency_kind,
                    ),
                )

            for blocker in task.blockers:
                connection.execute(
                    """
                    INSERT INTO task_blockers(
                        blocker_id, task_id, step_id, kind, title, detail, status, recovery_hint, created_at, resolved_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        blocker.blocker_id,
                        blocker.task_id,
                        blocker.step_id,
                        blocker.kind,
                        blocker.title,
                        blocker.detail,
                        blocker.status,
                        blocker.recovery_hint,
                        blocker.created_at,
                        blocker.resolved_at,
                    ),
                )

            for checkpoint in task.checkpoints:
                connection.execute(
                    """
                    INSERT INTO task_checkpoints(
                        checkpoint_id, task_id, step_id, label, status, summary, created_at, completed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        checkpoint.checkpoint_id,
                        checkpoint.task_id,
                        checkpoint.step_id,
                        checkpoint.label,
                        checkpoint.status,
                        checkpoint.summary,
                        checkpoint.created_at,
                        checkpoint.completed_at,
                    ),
                )

            for artifact in task.artifacts:
                connection.execute(
                    """
                    INSERT INTO task_artifacts(
                        artifact_id, task_id, step_id, kind, label, locator, required_for_resume,
                        exists_state, metadata_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact.artifact_id,
                        artifact.task_id,
                        artifact.step_id,
                        artifact.kind,
                        artifact.label,
                        artifact.locator,
                        1 if artifact.required_for_resume else 0,
                        artifact.exists_state,
                        json.dumps(artifact.metadata),
                        artifact.created_at,
                    ),
                )

            for evidence in task.evidence:
                connection.execute(
                    """
                    INSERT INTO task_evidence(
                        evidence_id, task_id, step_id, kind, summary, source, metadata_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence.evidence_id,
                        evidence.task_id,
                        evidence.step_id,
                        evidence.kind,
                        evidence.summary,
                        evidence.source,
                        json.dumps(evidence.metadata),
                        evidence.created_at,
                    ),
                )

            for link in task.job_links:
                connection.execute(
                    """
                    INSERT INTO task_job_links(
                        link_id, task_id, step_id, job_id, tool_name, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        link.link_id,
                        link.task_id,
                        link.step_id,
                        link.job_id,
                        link.tool_name,
                        link.status,
                        link.created_at,
                        link.updated_at,
                    ),
                )

        return self.get_task(task.task_id) or task

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT task_id, session_id, workspace_id, title, summary, goal, origin, state, recovery_state,
                       latest_summary, evidence_summary, where_left_off, active_step_id, last_completed_step_id,
                       hooks_json, metadata_json, created_at, updated_at, started_at, finished_at
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            task = self._row_to_task(row)
            task.steps = self._steps(connection, task.task_id)
            task.dependencies = self._dependencies(connection, task.task_id)
            task.blockers = self._blockers(connection, task.task_id)
            task.checkpoints = self._checkpoints(connection, task.task_id)
            task.artifacts = self._artifacts(connection, task.task_id)
            task.evidence = self._evidence(connection, task.task_id)
            task.job_links = self._job_links(connection, task.task_id)
        return task

    def latest_task(self, session_id: str) -> TaskRecord | None:
        return self._latest_by_state(session_id=session_id, terminal=None)

    def latest_active_task(self, session_id: str) -> TaskRecord | None:
        return self._latest_by_state(session_id=session_id, terminal=False)

    def list_recent_tasks(self, session_id: str, limit: int = 8) -> list[TaskRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT task_id
                FROM tasks
                WHERE session_id = ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        results: list[TaskRecord] = []
        for row in rows:
            task = self.get_task(str(row["task_id"]))
            if task is not None:
                results.append(task)
        return results

    def _latest_by_state(self, *, session_id: str, terminal: bool | None) -> TaskRecord | None:
        clauses = ["session_id = ?"]
        params: list[object] = [session_id]
        if terminal is False:
            clauses.append("state NOT IN ('completed', 'failed', 'cancelled')")
        elif terminal is True:
            clauses.append("state IN ('completed', 'failed', 'cancelled')")
        where_clause = " AND ".join(clauses)
        with self.database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT task_id
                FROM tasks
                WHERE {where_clause}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        if row is None:
            return None
        return self.get_task(str(row["task_id"]))

    def _steps(self, connection, task_id: str) -> list[TaskStepRecord]:
        rows = connection.execute(
            """
            SELECT step_id, task_id, sequence_index, title, detail, tool_name, tool_arguments_json,
                   state, summary, started_at, finished_at
            FROM task_steps
            WHERE task_id = ?
            ORDER BY sequence_index ASC
            """,
            (task_id,),
        ).fetchall()
        return [
            TaskStepRecord(
                step_id=row["step_id"],
                task_id=row["task_id"],
                sequence_index=int(row["sequence_index"]),
                title=row["title"],
                detail=row["detail"],
                tool_name=row["tool_name"],
                tool_arguments=decode_json_dict(
                    row["tool_arguments_json"],
                    context=f"task_steps.tool_arguments_json[{row['step_id']}]",
                ),
                state=row["state"],
                summary=row["summary"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
            )
            for row in rows
        ]

    def _dependencies(self, connection, task_id: str) -> list[TaskDependencyRecord]:
        rows = connection.execute(
            """
            SELECT dependency_id, task_id, step_id, depends_on_step_id, dependency_kind
            FROM task_dependencies
            WHERE task_id = ?
            ORDER BY rowid ASC
            """,
            (task_id,),
        ).fetchall()
        return [
            TaskDependencyRecord(
                dependency_id=row["dependency_id"],
                task_id=row["task_id"],
                step_id=row["step_id"],
                depends_on_step_id=row["depends_on_step_id"],
                dependency_kind=row["dependency_kind"],
            )
            for row in rows
        ]

    def _blockers(self, connection, task_id: str) -> list[TaskBlockerRecord]:
        rows = connection.execute(
            """
            SELECT blocker_id, task_id, step_id, kind, title, detail, status, recovery_hint, created_at, resolved_at
            FROM task_blockers
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
            (task_id,),
        ).fetchall()
        return [
            TaskBlockerRecord(
                blocker_id=row["blocker_id"],
                task_id=row["task_id"],
                step_id=row["step_id"],
                kind=row["kind"],
                title=row["title"],
                detail=row["detail"],
                status=row["status"],
                recovery_hint=row["recovery_hint"],
                created_at=row["created_at"],
                resolved_at=row["resolved_at"],
            )
            for row in rows
        ]

    def _checkpoints(self, connection, task_id: str) -> list[TaskCheckpointRecord]:
        rows = connection.execute(
            """
            SELECT checkpoint_id, task_id, step_id, label, status, summary, created_at, completed_at
            FROM task_checkpoints
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
            (task_id,),
        ).fetchall()
        return [
            TaskCheckpointRecord(
                checkpoint_id=row["checkpoint_id"],
                task_id=row["task_id"],
                step_id=row["step_id"],
                label=row["label"],
                status=row["status"],
                summary=row["summary"],
                created_at=row["created_at"],
                completed_at=row["completed_at"],
            )
            for row in rows
        ]

    def _artifacts(self, connection, task_id: str) -> list[TaskArtifactRecord]:
        rows = connection.execute(
            """
            SELECT artifact_id, task_id, step_id, kind, label, locator, required_for_resume,
                   exists_state, metadata_json, created_at
            FROM task_artifacts
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
            (task_id,),
        ).fetchall()
        return [
            TaskArtifactRecord(
                artifact_id=row["artifact_id"],
                task_id=row["task_id"],
                step_id=row["step_id"],
                kind=row["kind"],
                label=row["label"],
                locator=row["locator"],
                required_for_resume=bool(row["required_for_resume"]),
                exists_state=row["exists_state"],
                metadata=decode_json_dict(
                    row["metadata_json"],
                    context=f"task_artifacts.metadata_json[{row['artifact_id']}]",
                ),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _evidence(self, connection, task_id: str) -> list[TaskEvidenceRecord]:
        rows = connection.execute(
            """
            SELECT evidence_id, task_id, step_id, kind, summary, source, metadata_json, created_at
            FROM task_evidence
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
            (task_id,),
        ).fetchall()
        return [
            TaskEvidenceRecord(
                evidence_id=row["evidence_id"],
                task_id=row["task_id"],
                step_id=row["step_id"],
                kind=row["kind"],
                summary=row["summary"],
                source=row["source"],
                metadata=decode_json_dict(
                    row["metadata_json"],
                    context=f"task_evidence.metadata_json[{row['evidence_id']}]",
                ),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _job_links(self, connection, task_id: str) -> list[TaskJobLinkRecord]:
        rows = connection.execute(
            """
            SELECT link_id, task_id, step_id, job_id, tool_name, status, created_at, updated_at
            FROM task_job_links
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
            (task_id,),
        ).fetchall()
        return [
            TaskJobLinkRecord(
                link_id=row["link_id"],
                task_id=row["task_id"],
                step_id=row["step_id"],
                job_id=row["job_id"],
                tool_name=row["tool_name"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def _row_to_task(self, row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            title=row["title"],
            summary=row["summary"],
            goal=row["goal"],
            origin=row["origin"],
            state=row["state"],
            recovery_state=row["recovery_state"],
            latest_summary=row["latest_summary"],
            evidence_summary=row["evidence_summary"],
            where_left_off=row["where_left_off"],
            active_step_id=row["active_step_id"],
            last_completed_step_id=row["last_completed_step_id"],
            hooks=decode_json_dict(row["hooks_json"], context=f"tasks.hooks_json[{row['task_id']}]"),
            metadata=decode_json_dict(row["metadata_json"], context=f"tasks.metadata_json[{row['task_id']}]"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
