from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.models import JobRecord
from stormhelm.core.memory import MemoryQuery, MemoryRetrievalIntent, SemanticMemoryRepository, SemanticMemoryService
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.tasks.models import (
    TaskArtifactRecord,
    TaskBlockerRecord,
    TaskCheckpointRecord,
    TaskDependencyRecord,
    TaskEvidenceRecord,
    TaskExecutionPlan,
    TaskJobLinkRecord,
    TaskRecord,
    TaskResumeAssessment,
    TaskResumeStatus,
    TaskState,
    TaskStepRecord,
    TaskStepState,
)
from stormhelm.core.tasks.repository import TaskRepository
from stormhelm.shared.time import utc_now_iso


_TRACKED_TOOL_NAMES = {
    "workflow_execute",
    "repair_action",
    "routine_execute",
    "routine_save",
    "trusted_hook_execute",
    "trusted_hook_register",
    "file_operation",
    "maintenance_action",
    "workspace_restore",
    "workspace_assemble",
    "workspace_save",
    "workspace_archive",
    "workspace_rename",
    "workspace_tag",
}
_VERIFICATION_TOOL_NAMES = {
    "workflow_execute",
    "repair_action",
    "routine_execute",
    "trusted_hook_execute",
    "file_operation",
    "maintenance_action",
}
_CONTINUITY_PHRASES = {
    "continue",
    "resume",
    "where did we leave off",
    "what were we doing",
    "pick back up",
}
_ACTIVE_STEP_STATES = {
    TaskStepState.PENDING.value,
    TaskStepState.READY.value,
    TaskStepState.QUEUED.value,
    TaskStepState.IN_PROGRESS.value,
    TaskStepState.BLOCKED.value,
}
_TERMINAL_TASK_STATES = {
    TaskState.COMPLETED.value,
    TaskState.FAILED.value,
    TaskState.CANCELLED.value,
}
_TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "timed_out"}
_JOB_STATUS_RANK = {
    TaskStepState.PENDING.value: 0,
    TaskStepState.READY.value: 1,
    TaskStepState.QUEUED.value: 2,
    TaskStepState.IN_PROGRESS.value: 3,
    TaskStepState.BLOCKED.value: 4,
    TaskStepState.COMPLETED.value: 5,
    TaskStepState.FAILED.value: 5,
    TaskStepState.CANCELLED.value: 5,
    "queued": 2,
    "in_progress": 3,
    "completed": 5,
    "failed": 5,
    "cancelled": 5,
    "timed_out": 5,
}
_DUPLICATE_SUPPRESSION_WINDOW_SECONDS = 300
_TASK_ARCHIVE_AFTER_SECONDS = 7 * 24 * 60 * 60
_TASK_EXPIRE_AFTER_SECONDS = 14 * 24 * 60 * 60


class DurableTaskService:
    def __init__(
        self,
        *,
        repository: TaskRepository,
        session_state: ConversationStateStore,
        events: EventBuffer,
        memory: SemanticMemoryService | None = None,
    ) -> None:
        self.repository = repository
        self.session_state = session_state
        self.events = events
        self.memory = memory or SemanticMemoryService(SemanticMemoryRepository(repository.database))

    def begin_execution(
        self,
        *,
        session_id: str,
        prompt: str,
        requests: list[Any],
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
    ) -> TaskExecutionPlan | None:
        normalized_requests = self._normalize_requests(requests)
        if not normalized_requests or not self._should_track(normalized_requests):
            return None

        workspace_id = self._workspace_id(workspace_context)
        fingerprint = self._continuity_fingerprint(prompt, normalized_requests, workspace_id)
        if self._looks_like_resume(prompt):
            resolution = self._resolve_continuity_task(session_id)
            existing = resolution["task"] if isinstance(resolution.get("task"), TaskRecord) else None
            if existing is not None:
                self._record_duplicate_suppression(
                    existing,
                    fingerprint=fingerprint,
                    status="resume",
                    task_id=existing.task_id,
                )
                saved_existing = self.repository.save_task(existing)
                self._sync_task_memory(saved_existing)
                self.session_state.set_active_task_id(session_id, saved_existing.task_id)
                return TaskExecutionPlan(task_id=saved_existing.task_id, step_ids=[step.step_id for step in saved_existing.steps])

        duplicate = self._find_equivalent_task(session_id=session_id, fingerprint=fingerprint)
        if duplicate is not None:
            self._refresh_task(duplicate)
            self._record_duplicate_suppression(
                duplicate,
                fingerprint=fingerprint,
                status="reused",
                task_id=duplicate.task_id,
            )
            saved_duplicate = self.repository.save_task(duplicate)
            self._sync_task_memory(saved_duplicate)
            self.session_state.set_active_task_id(session_id, saved_duplicate.task_id)
            return TaskExecutionPlan(task_id=saved_duplicate.task_id, step_ids=[step.step_id for step in saved_duplicate.steps])

        timestamp = utc_now_iso()
        task_id = str(uuid4())
        steps = [
            TaskStepRecord(
                step_id=str(uuid4()),
                task_id=task_id,
                sequence_index=index,
                title=self._step_title(tool_name, arguments),
                detail=self._step_detail(tool_name, arguments),
                tool_name=tool_name,
                tool_arguments=dict(arguments),
                state=TaskStepState.READY.value if index == 0 else TaskStepState.PENDING.value,
            )
            for index, (tool_name, arguments) in enumerate(normalized_requests)
        ]
        dependencies = [
            TaskDependencyRecord(
                dependency_id=str(uuid4()),
                task_id=task_id,
                step_id=steps[index].step_id,
                depends_on_step_id=steps[index - 1].step_id,
            )
            for index in range(1, len(steps))
            if len(steps) > 1 and self._is_explicitly_sequential(normalized_requests[index - 1][0], normalized_requests[index][0])
        ]
        checkpoints = [
            TaskCheckpointRecord(
                checkpoint_id=str(uuid4()),
                task_id=task_id,
                label="Plan captured",
                status="completed",
                summary="Stormhelm stored the durable task outline before execution started.",
                created_at=timestamp,
                completed_at=timestamp,
            )
        ]
        if any(tool_name in _VERIFICATION_TOOL_NAMES for tool_name, _ in normalized_requests):
            checkpoints.append(
                TaskCheckpointRecord(
                    checkpoint_id=str(uuid4()),
                    task_id=task_id,
                    label="Verify outcome",
                    status="pending",
                    summary="Confirm the changed state before considering the task finished.",
                    created_at=timestamp,
                )
            )
        task = TaskRecord(
            task_id=task_id,
            session_id=session_id,
            workspace_id=workspace_id,
            title=self._task_title(prompt, normalized_requests),
            summary=self._task_summary(prompt, normalized_requests),
            goal=prompt.strip(),
            origin="assistant_tool_execution",
            state=TaskState.PLANNED.value,
            hooks={
                "approvals": {"implemented": False, "status": "deferred"},
                "memory": {
                    "implemented": True,
                    "status": "active",
                    "families": ["task", "semantic_recall"],
                },
            },
            metadata={
                "surfaceMode": surface_mode,
                "activeModule": active_module,
                "requestCount": len(normalized_requests),
                "continuity": {
                    "fingerprint": fingerprint,
                    "duplicateSuppression": {
                        "status": "created",
                        "fingerprint": fingerprint,
                        "taskId": task_id,
                        "matchedTaskId": "",
                        "recordedAt": timestamp,
                    },
                },
            },
            created_at=timestamp,
            updated_at=timestamp,
            steps=steps,
            dependencies=dependencies,
            checkpoints=checkpoints,
        )
        self._refresh_task(task)
        saved_task = self.repository.save_task(task)
        self._sync_task_memory(saved_task)
        self.session_state.set_active_task_id(session_id, task_id)
        self.events.publish(
            event_family="task",
            event_type="task.created",
            subsystem="tasks",
            severity="info",
            visibility_scope="deck_context",
            retention_class="operator_relevant",
            subject=task_id,
            message=f"Tracked task '{task.title}'.",
            payload={"task_id": task_id, "state": task.state, "workspace_id": workspace_id},
        )
        return TaskExecutionPlan(task_id=task_id, step_ids=[step.step_id for step in steps])

    def record_direct_tool_result(
        self,
        *,
        task_id: str,
        step_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        success: bool,
        error: str | None = None,
    ) -> TaskRecord | None:
        task = self.repository.get_task(task_id)
        if task is None:
            return None
        step = self._step_by_id(task, step_id)
        if step is None:
            return None
        timestamp = utc_now_iso()
        step.tool_name = tool_name
        step.tool_arguments = dict(arguments)
        step.started_at = step.started_at or timestamp
        step.finished_at = timestamp
        summary = str(result.get("summary") or error or "").strip()
        step.summary = summary
        step.state = TaskStepState.COMPLETED.value if success else TaskStepState.FAILED.value
        self._resolve_blockers_for_step(task, step_id, resolved_at=timestamp)
        if not success:
            self._append_blocker(
                task,
                step_id=step_id,
                kind="recovery",
                title=f"{self._tool_label(tool_name)} needs recovery",
                detail=error or summary or "Stormhelm could not finish that step cleanly.",
                recovery_hint="Re-run the failed step after checking the last durable result.",
                created_at=timestamp,
            )
        else:
            self._record_artifacts(task, step_id=step_id, tool_name=tool_name, arguments=arguments, payload=result)
            self._record_evidence(task, step_id=step_id, tool_name=tool_name, payload=result, created_at=timestamp)
            verification_summary = self._verification_summary(result)
            if verification_summary:
                self._apply_verification_summary(task, verification_summary, source=tool_name, created_at=timestamp)
        self._refresh_task(task)
        saved = self.repository.save_task(task)
        self._sync_task_memory(saved)
        return saved

    def record_verification_summary(self, task_id: str, summary: str, *, source: str = "verification") -> TaskRecord | None:
        task = self.repository.get_task(task_id)
        if task is None:
            return None
        timestamp = utc_now_iso()
        self._apply_verification_summary(task, summary, source=source, created_at=timestamp)
        self._refresh_task(task)
        saved = self.repository.save_task(task)
        self._sync_task_memory(saved)
        return saved

    def record_recovery_signal(self, task_id: str, summary: str, *, source: str = "recovery") -> TaskRecord | None:
        task = self.repository.get_task(task_id)
        if task is None:
            return None
        timestamp = utc_now_iso()
        active_step = self._current_step(task)
        self._append_blocker(
            task,
            step_id=active_step.step_id if active_step is not None else "",
            kind=source,
            title="Recovery attention required",
            detail=summary.strip(),
            recovery_hint="Resume after reconciling the stale or failing state.",
            created_at=timestamp,
        )
        self._refresh_task(task)
        saved = self.repository.save_task(task)
        self._sync_task_memory(saved)
        return saved

    def record_trust_pending(self, *, task_id: str, request: dict[str, Any], decision: dict[str, Any]) -> TaskRecord | None:
        task = self.repository.get_task(task_id)
        if task is None:
            return None
        timestamp = utc_now_iso()
        trust_state = task.hooks.get("approvals") if isinstance(task.hooks.get("approvals"), dict) else {}
        trust_state.update(
            {
                "implemented": True,
                "status": "pending",
                "approvalState": str(decision.get("approval_state") or ""),
                "requestId": str(request.get("approval_request_id") or ""),
                "subject": str(request.get("subject") or ""),
                "operatorMessage": str(
                    (
                        decision.get("operator_message")
                        or request.get("operator_message")
                        or request.get("operator_justification")
                        or ""
                    )
                ).strip(),
            }
        )
        task.hooks["approvals"] = trust_state
        blocker_title = "Approval required"
        blocker_detail = trust_state["operatorMessage"] or "Stormhelm is waiting for an approval decision before continuing."
        existing_open = next(
            (
                blocker
                for blocker in task.blockers
                if blocker.kind == "approval" and blocker.status == "open"
            ),
            None,
        )
        if existing_open is None:
            self._append_blocker(
                task,
                step_id=task.active_step_id,
                kind="approval",
                title=blocker_title,
                detail=blocker_detail,
                recovery_hint="Reply with allow once, allow for this task, allow for this session, or deny.",
                created_at=timestamp,
            )
        else:
            existing_open.title = blocker_title
            existing_open.detail = blocker_detail
        self._refresh_task(task)
        saved = self.repository.save_task(task)
        self._sync_task_memory(saved)
        return saved

    def record_trust_granted(self, *, task_id: str, request: dict[str, Any], grant: dict[str, Any]) -> TaskRecord | None:
        task = self.repository.get_task(task_id)
        if task is None:
            return None
        timestamp = utc_now_iso()
        task.hooks["approvals"] = {
            "implemented": True,
            "status": "granted",
            "approvalState": str(grant.get("state") or ""),
            "requestId": str(request.get("approval_request_id") or ""),
            "grantId": str(grant.get("grant_id") or ""),
            "scope": str(grant.get("scope") or ""),
            "subject": str(grant.get("subject") or ""),
        }
        for blocker in task.blockers:
            if blocker.kind == "approval" and blocker.status == "open":
                blocker.status = "resolved"
                blocker.resolved_at = timestamp
        task.checkpoints.append(
            TaskCheckpointRecord(
                checkpoint_id=str(uuid4()),
                task_id=task.task_id,
                step_id=task.active_step_id,
                label="Approval recorded",
                status="completed",
                summary=(
                    f"Granted {grant.get('action_key') or request.get('action_key') or 'action'} "
                    f"for {grant.get('scope') or 'once'}."
                ),
                created_at=timestamp,
                completed_at=timestamp,
            )
        )
        self._refresh_task(task)
        saved = self.repository.save_task(task)
        self._sync_task_memory(saved)
        return saved

    def record_trust_denied(self, *, task_id: str, request: dict[str, Any]) -> TaskRecord | None:
        task = self.repository.get_task(task_id)
        if task is None:
            return None
        timestamp = utc_now_iso()
        task.hooks["approvals"] = {
            "implemented": True,
            "status": "denied",
            "approvalState": "denied",
            "requestId": str(request.get("approval_request_id") or ""),
            "subject": str(request.get("subject") or ""),
        }
        blocker_detail = str(request.get("operator_message") or request.get("operator_justification") or "").strip()
        existing_open = next(
            (
                blocker
                for blocker in task.blockers
                if blocker.kind == "approval" and blocker.status == "open"
            ),
            None,
        )
        if existing_open is None:
            self._append_blocker(
                task,
                step_id=task.active_step_id,
                kind="approval",
                title="Approval denied",
                detail=blocker_detail or "Stormhelm cannot continue because approval was denied.",
                recovery_hint="Request a new approval if the action should continue later.",
                created_at=timestamp,
            )
        else:
            existing_open.title = "Approval denied"
            existing_open.detail = blocker_detail or existing_open.detail
        self._refresh_task(task)
        saved = self.repository.save_task(task)
        self._sync_task_memory(saved)
        return saved

    def active_task_summary(self, session_id: str) -> dict[str, Any]:
        resolution = self._resolve_continuity_task(session_id)
        task = resolution["task"] if isinstance(resolution.get("task"), TaskRecord) else None
        if task is None:
            return {}
        resume = self._resume_assessment(task)
        payload = task.to_dict(resume_assessment=resume)
        current_step = self._current_step(task)
        payload["currentStep"] = current_step.to_dict(job_links=task.job_links) if current_step is not None else {}
        payload["nextSteps"] = [step.title for step in self._next_steps(task)]
        payload["ghostSummary"] = self._ghost_summary(task, resume=resume)
        payload["commandDeck"] = {"groups": self._task_groups(task)}
        payload["continuity"] = self._continuity_payload(task, resume=resume, resolution=resolution)
        memory_context = self._task_memory_context(task)
        if memory_context:
            payload["memoryContext"] = memory_context
        return payload

    def where_we_left_off(self, *, session_id: str) -> dict[str, Any] | None:
        resolution = self._resolve_continuity_task(session_id)
        task = resolution["task"] if isinstance(resolution.get("task"), TaskRecord) else None
        if task is None:
            return None
        resume = self._resume_assessment(task)
        summary = task.where_left_off or self._where_left_off(task, resume=resume)
        return {
            "summary": summary,
            "task": self.active_task_summary(session_id),
            "memory": self._task_memory_context(task),
            "action": {
                "type": "workspace_focus",
                "module": "chartroom",
                "section": "tasks",
                "state_hint": "task_continuity",
            },
        }

    def next_steps(self, *, session_id: str) -> dict[str, Any] | None:
        resolution = self._resolve_continuity_task(session_id)
        task = resolution["task"] if isinstance(resolution.get("task"), TaskRecord) else None
        if task is None:
            return None
        resume = self._resume_assessment(task)
        next_steps = [step.title for step in self._next_steps(task)]
        if resume.status == TaskResumeStatus.STALE.value:
            summary = f"{task.title} cannot resume yet because Stormhelm lost a required artifact. {resume.summary}"
        elif resume.status in {TaskResumeStatus.EXPIRED.value, TaskResumeStatus.ARCHIVED.value}:
            summary = resume.summary
        elif next_steps:
            summary = f"Next for {task.title}: {next_steps[0]}."
        else:
            summary = resume.summary
        return {
            "summary": summary,
            "task": self.active_task_summary(session_id),
            "memory": self._task_memory_context(task),
            "action": {
                "type": "workspace_focus",
                "module": "chartroom",
                "section": "tasks",
                "state_hint": "task_plan",
            },
        }

    def trust_binding_status(self, *, task_id: str) -> dict[str, Any]:
        task = self.repository.get_task(task_id)
        if task is None:
            return {
                "task_id": task_id,
                "valid": False,
                "reason": "missing",
                "task_state": "",
                "resume_status": TaskResumeStatus.MISSING.value,
                "summary": "Stormhelm does not have durable task state for that trust binding anymore.",
            }

        saved = self._refresh_and_persist_task(task)
        resume = self._resume_assessment(saved)
        valid = self._trust_binding_resumable(saved, resume=resume)
        return {
            "task_id": saved.task_id,
            "valid": valid,
            "reason": self._trust_binding_reason(saved, resume=resume),
            "task_state": saved.state,
            "resume_status": resume.status,
            "summary": resume.summary,
        }

    def current_sensitive_task_id(self, *, session_id: str) -> str:
        active_task_id = str(self.session_state.get_active_task_id(session_id) or "").strip()
        if active_task_id:
            binding = self.trust_binding_status(task_id=active_task_id)
            if binding.get("valid") is True:
                return active_task_id
            self.session_state.clear_active_task_id(session_id)

        resolution = self._resolve_continuity_task(session_id)
        fallback = resolution["task"] if isinstance(resolution.get("task"), TaskRecord) else None
        if fallback is None:
            return ""
        binding = self.trust_binding_status(task_id=fallback.task_id)
        if binding.get("valid") is True:
            self.session_state.set_active_task_id(session_id, fallback.task_id)
            return fallback.task_id
        self.session_state.clear_active_task_id(session_id)
        return ""

    def watch_tasks(self, session_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        tasks = self.repository.list_recent_tasks(session_id, limit=limit)
        watch_items: list[dict[str, Any]] = []
        for task in tasks:
            current = self._current_step(task)
            detail = current.summary if current is not None and current.summary else task.latest_summary or task.where_left_off
            watch_items.append(
                {
                    "title": task.title,
                    "status": task.state,
                    "detail": detail,
                    "severity": "attention" if task.state in {TaskState.BLOCKED.value, TaskState.FAILED.value} else "steady",
                    "meta": current.title if current is not None else "",
                }
            )
        return watch_items

    def on_job_queued(self, job: JobRecord) -> None:
        self._update_from_job(job, state=TaskStepState.QUEUED.value, summary=f"Queued {self._tool_label(job.tool_name)}.")

    def on_job_started(self, job: JobRecord) -> None:
        self._update_from_job(job, state=TaskStepState.IN_PROGRESS.value, summary=f"Running {self._tool_label(job.tool_name)}.")

    def on_job_progress(self, job: JobRecord, payload: dict[str, Any]) -> None:
        summary = str(payload.get("summary") or payload.get("detail") or f"{self._tool_label(job.tool_name)} reported progress.").strip()
        self._update_from_job(job, state=TaskStepState.IN_PROGRESS.value, summary=summary, payload=payload)

    def on_job_finished(self, job: JobRecord) -> None:
        task = self._task_for_job(job)
        if task is None:
            return
        step = self._step_by_id(task, str(job.task_step_id or ""))
        if step is None:
            return
        timestamp = job.finished_at or utc_now_iso()
        status = str(job.status.value if hasattr(job.status, "value") else job.status).strip().lower()
        accepted, reason = self._should_apply_job_event(
            task,
            job=job,
            incoming_status=status,
            allow_same_status=False,
        )
        if not accepted:
            self._record_lifecycle_decision(task, job=job, incoming_status=status, applied=False, reason=reason, recorded_at=timestamp)
            self.repository.save_task(task)
            return
        step.started_at = step.started_at or (job.started_at or job.created_at)
        step.finished_at = timestamp
        summary = ""
        if isinstance(job.result, dict):
            summary = str(job.result.get("summary") or "").strip()
        if not summary:
            summary = str(job.error or "").strip()
        step.summary = summary
        self._resolve_blockers_for_step(task, step.step_id, resolved_at=timestamp)
        if status == "completed":
            step.state = TaskStepState.COMPLETED.value
            self._record_artifacts(task, step_id=step.step_id, tool_name=job.tool_name, arguments=job.arguments, payload=job.result or {})
            self._record_evidence(task, step_id=step.step_id, tool_name=job.tool_name, payload=job.result or {}, created_at=timestamp)
            verification_summary = self._verification_summary(job.result or {})
            if verification_summary:
                self._apply_verification_summary(task, verification_summary, source=job.tool_name, created_at=timestamp)
        elif status in {"cancelled", "timed_out"}:
            step.state = TaskStepState.BLOCKED.value
            self._append_blocker(
                task,
                step_id=step.step_id,
                kind="recovery",
                title=f"{self._tool_label(job.tool_name)} was interrupted",
                detail=summary or "Stormhelm was interrupted during that step.",
                recovery_hint="Resume by re-running the interrupted step.",
                created_at=timestamp,
            )
        else:
            step.state = TaskStepState.FAILED.value
            self._append_blocker(
                task,
                step_id=step.step_id,
                kind="recovery",
                title=f"{self._tool_label(job.tool_name)} failed",
                detail=summary or "Stormhelm could not finish that step.",
                recovery_hint="Review the failure and recover before resuming.",
                created_at=timestamp,
            )
        self._upsert_job_link(task, job=job, status=status, updated_at=timestamp)
        self._refresh_task(task)
        self._record_lifecycle_decision(task, job=job, incoming_status=status, applied=True, reason="applied", recorded_at=timestamp)
        saved = self.repository.save_task(task)
        self._sync_task_memory(saved)

    def _update_from_job(
        self,
        job: JobRecord,
        *,
        state: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        task = self._task_for_job(job)
        if task is None:
            return
        step = self._step_by_id(task, str(job.task_step_id or ""))
        if step is None:
            return
        timestamp = utc_now_iso()
        accepted, reason = self._should_apply_job_event(
            task,
            job=job,
            incoming_status=state,
            allow_same_status=payload is not None,
        )
        if not accepted:
            self._record_lifecycle_decision(task, job=job, incoming_status=state, applied=False, reason=reason, recorded_at=timestamp)
            self.repository.save_task(task)
            return
        step.state = state
        step.started_at = step.started_at or (job.started_at or job.created_at or timestamp)
        step.summary = summary.strip()
        self._upsert_job_link(task, job=job, status=state, updated_at=timestamp)
        if payload:
            self._record_evidence(
                task,
                step_id=step.step_id,
                tool_name=job.tool_name,
                payload={"summary": step.summary, "data": payload},
                created_at=timestamp,
                replace_kind="progress",
            )
        self._refresh_task(task)
        self._record_lifecycle_decision(task, job=job, incoming_status=state, applied=True, reason="applied", recorded_at=timestamp)
        saved = self.repository.save_task(task)
        self._sync_task_memory(saved)

    def _task_for_job(self, job: JobRecord) -> TaskRecord | None:
        task_id = str(getattr(job, "task_id", "") or "").strip()
        step_id = str(getattr(job, "task_step_id", "") or "").strip()
        if not task_id or not step_id:
            return None
        return self.repository.get_task(task_id)

    def _should_track(self, requests: list[tuple[str, dict[str, Any]]]) -> bool:
        if len(requests) > 1:
            return True
        tool_name = requests[0][0]
        return tool_name in _TRACKED_TOOL_NAMES

    def _normalize_requests(self, requests: list[Any]) -> list[tuple[str, dict[str, Any]]]:
        normalized: list[tuple[str, dict[str, Any]]] = []
        for request in requests:
            tool_name = str(getattr(request, "tool_name", getattr(request, "name", "")) or "").strip()
            arguments = getattr(request, "arguments", {}) if hasattr(request, "arguments") else {}
            if not tool_name:
                continue
            normalized.append((tool_name, dict(arguments) if isinstance(arguments, dict) else {}))
        return normalized

    def _looks_like_resume(self, prompt: str) -> bool:
        lower = str(prompt or "").strip().lower()
        return any(phrase in lower for phrase in _CONTINUITY_PHRASES)

    def _workspace_id(self, workspace_context: dict[str, Any] | None) -> str:
        if not isinstance(workspace_context, dict):
            return ""
        workspace = workspace_context.get("workspace")
        if not isinstance(workspace, dict):
            return ""
        return str(workspace.get("workspaceId") or workspace.get("workspace_id") or "").strip()

    def _task_title(self, prompt: str, requests: list[tuple[str, dict[str, Any]]]) -> str:
        text = " ".join(str(prompt or "").split()).strip().rstrip(".")
        if text:
            return text[:96]
        return self._tool_label(requests[0][0])

    def _task_summary(self, prompt: str, requests: list[tuple[str, dict[str, Any]]]) -> str:
        if prompt.strip():
            return f"Stormhelm is tracking durable progress for: {prompt.strip()}"
        labels = ", ".join(self._tool_label(tool_name) for tool_name, _ in requests[:3])
        return f"Stormhelm is tracking durable progress across {labels}."

    def _tool_label(self, tool_name: str) -> str:
        labels = {
            "workflow_execute": "Workflow",
            "repair_action": "Repair",
            "routine_execute": "Routine",
            "routine_save": "Routine Save",
            "trusted_hook_execute": "Trusted Hook",
            "trusted_hook_register": "Trusted Hook",
            "file_operation": "Files",
            "maintenance_action": "Maintenance",
            "workspace_restore": "Workspace Restore",
            "workspace_assemble": "Workspace Assemble",
            "workspace_save": "Workspace Save",
            "workspace_archive": "Workspace Archive",
            "workspace_rename": "Workspace Rename",
            "workspace_tag": "Workspace Tag",
        }
        return labels.get(tool_name, tool_name.replace("_", " ").title())

    def _step_title(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "maintenance_action":
            action = str(arguments.get("action") or "").strip()
            if action:
                return action.replace("_", " ").title()
        if tool_name == "file_operation":
            operation = str(arguments.get("operation") or "").strip()
            if operation:
                return operation.replace("_", " ").title()
        return self._tool_label(tool_name)

    def _step_detail(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if "path" in arguments:
            return f"Path: {arguments['path']}"
        if "url" in arguments:
            return f"URL: {arguments['url']}"
        if tool_name.startswith("workspace_"):
            return "Workspace continuity step."
        return f"Tool step: {self._tool_label(tool_name)}"

    def _is_explicitly_sequential(self, first_tool: str, second_tool: str) -> bool:
        workspace_tools = {"workspace_restore", "workspace_assemble", "workspace_save", "workspace_archive", "workspace_rename", "workspace_tag"}
        return first_tool in workspace_tools or second_tool in workspace_tools

    def _step_by_id(self, task: TaskRecord, step_id: str) -> TaskStepRecord | None:
        for step in task.steps:
            if step.step_id == step_id:
                return step
        return None

    def _current_step(self, task: TaskRecord) -> TaskStepRecord | None:
        if task.active_step_id:
            step = self._step_by_id(task, task.active_step_id)
            if step is not None:
                return step
        for step in task.steps:
            if step.state in _ACTIVE_STEP_STATES:
                return step
        return task.steps[-1] if task.steps else None

    def _next_steps(self, task: TaskRecord) -> list[TaskStepRecord]:
        completed_ids = {step.step_id for step in task.steps if step.state == TaskStepState.COMPLETED.value}
        ready: list[TaskStepRecord] = []
        for step in task.steps:
            if step.state not in _ACTIVE_STEP_STATES:
                continue
            requirements = [
                dependency.depends_on_step_id
                for dependency in task.dependencies
                if dependency.step_id == step.step_id
            ]
            if all(requirement in completed_ids for requirement in requirements):
                ready.append(step)
        return ready

    def _refresh_task(self, task: TaskRecord) -> None:
        timestamp = utc_now_iso()
        task.updated_at = timestamp
        self._refresh_artifact_states(task)
        current = self._current_step(task)
        open_blockers = [blocker for blocker in task.blockers if blocker.status == "open"]
        task.last_completed_step_id = next(
            (step.step_id for step in reversed(task.steps) if step.state == TaskStepState.COMPLETED.value),
            "",
        )
        task.active_step_id = current.step_id if current is not None and current.state in _ACTIVE_STEP_STATES else ""
        completed_count = sum(1 for step in task.steps if step.state == TaskStepState.COMPLETED.value)
        has_live_execution = any(step.state in {TaskStepState.QUEUED.value, TaskStepState.IN_PROGRESS.value} for step in task.steps)
        has_failed = any(step.state == TaskStepState.FAILED.value for step in task.steps)
        has_blocked = any(step.state == TaskStepState.BLOCKED.value for step in task.steps)
        verify_pending = any(checkpoint.label == "Verify outcome" and checkpoint.status != "completed" for checkpoint in task.checkpoints)
        if not task.started_at and (completed_count or has_live_execution):
            task.started_at = timestamp

        if open_blockers or has_blocked:
            task.state = TaskState.BLOCKED.value
            task.recovery_state = self._recovery_state_for_blockers(open_blockers)
        elif has_failed:
            task.state = TaskState.FAILED.value
            task.recovery_state = "required"
        elif has_live_execution:
            task.state = TaskState.IN_PROGRESS.value
            task.recovery_state = ""
        elif task.steps and all(step.state == TaskStepState.COMPLETED.value for step in task.steps):
            task.state = TaskState.VERIFICATION.value if verify_pending else TaskState.COMPLETED.value
            task.recovery_state = "verification_pending" if task.state == TaskState.VERIFICATION.value else ""
            if task.state == TaskState.COMPLETED.value:
                task.finished_at = task.finished_at or timestamp
        elif completed_count:
            task.state = TaskState.PAUSED.value
            task.recovery_state = "resumable"
        else:
            task.state = TaskState.PLANNED.value
            task.recovery_state = ""

        task.latest_summary = self._latest_summary(task)
        task.evidence_summary = self._evidence_summary(task)
        resume = self._resume_assessment(task)
        task.where_left_off = self._where_left_off(task, resume=resume)
        self._write_continuity_metadata(task, resume=resume)

    def _latest_summary(self, task: TaskRecord) -> str:
        current = self._current_step(task)
        if current is not None and current.summary:
            return current.summary
        if task.evidence:
            return task.evidence[-1].summary
        if task.blockers:
            open_blocker = next((blocker for blocker in reversed(task.blockers) if blocker.status == "open"), task.blockers[-1])
            return open_blocker.detail or open_blocker.title
        return task.summary

    def _evidence_summary(self, task: TaskRecord) -> str:
        summaries = [entry.summary for entry in task.evidence if entry.summary.strip()]
        if summaries:
            return " | ".join(summaries[-3:])
        completed = [step.summary for step in task.steps if step.state == TaskStepState.COMPLETED.value and step.summary]
        return " | ".join(completed[-3:])

    def _where_left_off(self, task: TaskRecord, *, resume: TaskResumeAssessment) -> str:
        if resume.status == TaskResumeStatus.ARCHIVED.value:
            return f"{task.title} is archived and no longer counts as live continuity. {resume.summary}"
        if resume.status == TaskResumeStatus.EXPIRED.value:
            return f"{task.title} still has a task record, but it is too old to treat as active continuity. {resume.summary}"
        current = self._current_step(task)
        if resume.status == TaskResumeStatus.STALE.value:
            return f"Stormhelm left off on {task.title} but a required artifact is missing. {resume.summary}"
        if resume.status == TaskResumeStatus.WAITING_OPERATOR.value:
            return f"Stormhelm is waiting for operator approval on {task.title}. {resume.summary}"
        if resume.status == TaskResumeStatus.WAITING_ENVIRONMENT.value:
            return f"Stormhelm is waiting for the environment before {task.title} can continue. {resume.summary}"
        if resume.status == TaskResumeStatus.BLOCKED.value:
            return f"{task.title} is blocked. {resume.summary}"
        if resume.status == TaskResumeStatus.VERIFICATION.value:
            return f"Execution finished for {task.title}, but verification is still pending."
        if current is not None and current.state in {TaskStepState.QUEUED.value, TaskStepState.IN_PROGRESS.value}:
            return f"Stormhelm was in the middle of {current.title} when execution stopped. {resume.summary}"
        if current is not None and current.state in {TaskStepState.PENDING.value, TaskStepState.READY.value}:
            previous = next((step for step in reversed(task.steps) if step.state == TaskStepState.COMPLETED.value), None)
            if previous is not None:
                return f"Stormhelm paused after {previous.title} and can resume with {current.title}."
            return f"Stormhelm planned {current.title} next."
        if task.state == TaskState.COMPLETED.value:
            return f"{task.title} is complete."
        if task.latest_summary:
            return task.latest_summary
        return task.summary

    def _resume_assessment(self, task: TaskRecord) -> TaskResumeAssessment:
        timestamp = utc_now_iso()
        posture = self._task_posture(task)
        if posture["status"] == TaskResumeStatus.ARCHIVED.value:
            return TaskResumeAssessment(
                status=TaskResumeStatus.ARCHIVED.value,
                summary="Stormhelm archived this old task record, so it no longer outranks fresher continuity.",
                can_resume=False,
                checked_at=timestamp,
                next_steps=[step.title for step in self._next_steps(task)],
                recovery_advice=["Start a fresh task if this work should continue again."],
            )
        if posture["status"] == TaskResumeStatus.EXPIRED.value:
            return TaskResumeAssessment(
                status=TaskResumeStatus.EXPIRED.value,
                summary="The durable task record still exists, but its live continuity has expired.",
                can_resume=False,
                checked_at=timestamp,
                next_steps=[step.title for step in self._next_steps(task)],
                recovery_advice=["Reconfirm the real state before resuming this old task."],
            )
        missing_artifacts = [
            artifact.locator
            for artifact in task.artifacts
            if artifact.required_for_resume and artifact.locator and artifact.kind == "file" and artifact.exists_state == "missing"
        ]
        if missing_artifacts:
            return TaskResumeAssessment(
                status=TaskResumeStatus.STALE.value,
                summary="One or more required local artifacts are missing from the recorded task state.",
                can_resume=False,
                checked_at=timestamp,
                next_steps=[step.title for step in self._next_steps(task)],
                missing_artifacts=missing_artifacts,
                recovery_advice=["Recreate or locate the missing artifact before resuming."],
            )
        open_blockers = [blocker for blocker in task.blockers if blocker.status == "open"]
        if open_blockers:
            blocker_status = self._blocker_resume_status(open_blockers[-1])
            return TaskResumeAssessment(
                status=blocker_status,
                summary=open_blockers[-1].detail or open_blockers[-1].title,
                can_resume=False,
                checked_at=timestamp,
                next_steps=[step.title for step in self._next_steps(task)],
                blocking_reasons=[blocker.title for blocker in open_blockers],
                recovery_advice=[blocker.recovery_hint for blocker in open_blockers if blocker.recovery_hint],
            )
        if task.state == TaskState.VERIFICATION.value:
            return TaskResumeAssessment(
                status=TaskResumeStatus.VERIFICATION.value,
                summary="Execution finished, but Stormhelm still expects verification before calling the task done.",
                can_resume=True,
                checked_at=timestamp,
                next_steps=["Verify outcome"],
            )
        if task.state == TaskState.COMPLETED.value:
            return TaskResumeAssessment(
                status=TaskResumeStatus.COMPLETED.value,
                summary="The recorded task state is complete.",
                can_resume=False,
                checked_at=timestamp,
            )
        next_steps = [step.title for step in self._next_steps(task)]
        if not task.steps:
            return TaskResumeAssessment(
                status=TaskResumeStatus.MISSING.value,
                summary="Stormhelm does not have durable step state for this task.",
                can_resume=False,
                checked_at=timestamp,
            )
        return TaskResumeAssessment(
            status=TaskResumeStatus.RESUMABLE.value,
            summary="Stormhelm has enough durable state to resume honestly.",
            can_resume=True,
            checked_at=timestamp,
            next_steps=next_steps,
        )

    def _ghost_summary(self, task: TaskRecord, *, resume: TaskResumeAssessment) -> dict[str, Any]:
        current = self._current_step(task)
        subtitle = self._resume_label(resume.status) or str(task.state).replace("_", " ").title()
        if current is not None and current.state in {
            TaskStepState.PENDING.value,
            TaskStepState.READY.value,
            TaskStepState.QUEUED.value,
            TaskStepState.IN_PROGRESS.value,
        }:
            subtitle = current.title
        return {
            "title": task.title,
            "subtitle": subtitle,
            "body": resume.summary,
        }

    def _task_groups(self, task: TaskRecord) -> list[dict[str, Any]]:
        next_entries = [
            {"title": step.title, "status": step.state, "detail": step.summary or step.detail}
            for step in self._next_steps(task)[:4]
        ] or [{"title": "No pending steps", "status": "steady", "detail": "Stormhelm is not holding another ready step right now."}]
        in_flight = [
            {"title": step.title, "status": step.state, "detail": step.summary or step.detail}
            for step in task.steps
            if step.state in {TaskStepState.QUEUED.value, TaskStepState.IN_PROGRESS.value}
        ] or [{"title": "No active execution", "status": "steady", "detail": "No task step is currently running."}]
        attention = [
            {"title": blocker.title, "status": blocker.status, "detail": blocker.detail or blocker.recovery_hint}
            for blocker in task.blockers
            if blocker.status == "open"
        ] or [{"title": "No open blockers", "status": "steady", "detail": "Task continuity is clear."}]
        return [
            {"title": "Next Bearings", "entries": next_entries},
            {"title": "In Flight", "entries": in_flight},
            {"title": "Attention", "entries": attention},
        ]

    def _continuity_candidate_score(self, task: TaskRecord, *, active_workspace_id: str) -> tuple[int, int, str, str]:
        state_priority = {
            TaskState.IN_PROGRESS.value: 6,
            TaskState.BLOCKED.value: 5,
            TaskState.VERIFICATION.value: 5,
            TaskState.PAUSED.value: 4,
            TaskState.PLANNED.value: 3,
            TaskState.COMPLETED.value: 2,
            TaskState.FAILED.value: 1,
            TaskState.CANCELLED.value: 0,
        }
        return (
            1 if active_workspace_id and task.workspace_id == active_workspace_id else 0,
            state_priority.get(task.state, 0),
            self._task_last_activity_at(task),
            task.created_at,
        )

    def _continuity_fingerprint(self, prompt: str, requests: list[tuple[str, dict[str, Any]]], workspace_id: str) -> str:
        normalized_prompt = " ".join(str(prompt or "").split()).strip().lower()
        normalized_requests = [
            {"tool": tool_name, "arguments": arguments}
            for tool_name, arguments in requests
        ]
        return json.dumps(
            {
                "prompt": normalized_prompt,
                "workspace_id": workspace_id,
                "requests": normalized_requests,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def _find_equivalent_task(self, *, session_id: str, fingerprint: str) -> TaskRecord | None:
        for task in self.repository.list_recent_tasks(session_id, limit=12):
            self._refresh_task(task)
            continuity = task.metadata.get("continuity") if isinstance(task.metadata.get("continuity"), dict) else {}
            if str(continuity.get("fingerprint") or "").strip() != fingerprint:
                continue
            posture = self._task_posture(task)
            if posture["status"] in {TaskResumeStatus.ARCHIVED.value, TaskResumeStatus.EXPIRED.value}:
                continue
            last_activity_at = self._task_last_activity_at(task)
            is_recent = self._seconds_since(last_activity_at) <= _DUPLICATE_SUPPRESSION_WINDOW_SECONDS
            if task.state not in _TERMINAL_TASK_STATES or is_recent:
                return task
        return None

    def _continuity_payload(
        self,
        task: TaskRecord,
        *,
        resume: TaskResumeAssessment,
        resolution: dict[str, Any],
    ) -> dict[str, Any]:
        continuity = task.metadata.get("continuity") if isinstance(task.metadata.get("continuity"), dict) else {}
        posture = self._task_posture(task)
        return {
            "source": str(resolution.get("source") or "none"),
            "selectionReason": str(resolution.get("selectionReason") or ""),
            "resumeStatus": resume.status,
            "resumeReason": resume.summary,
            "posture": posture,
            "duplicateSuppression": dict(continuity.get("duplicateSuppression") or {}),
            "lifecycle": dict(continuity.get("lifecycle") or {}),
        }

    def _resolve_continuity_task(self, session_id: str) -> dict[str, Any]:
        active_task_id = self.session_state.get_active_task_id(session_id)
        if active_task_id:
            task = self.repository.get_task(active_task_id)
            if task is not None:
                self._refresh_task(task)
                posture = self._task_posture(task)
                if posture["status"] not in {TaskResumeStatus.ARCHIVED.value, TaskResumeStatus.EXPIRED.value}:
                    saved = self.repository.save_task(task)
                    self._sync_task_memory(saved)
                    return {
                        "task": saved,
                        "source": "active_durable_task",
                        "selectionReason": "session_active_task",
                    }
            self.session_state.clear_active_task_id(session_id)

        active_workspace_id = str(self.session_state.get_active_workspace_id(session_id) or "").strip()
        candidates: list[tuple[tuple[int, int, str, str], TaskRecord]] = []
        for task in self.repository.list_recent_tasks(session_id, limit=12):
            self._refresh_task(task)
            posture = self._task_posture(task)
            if posture["status"] in {TaskResumeStatus.ARCHIVED.value, TaskResumeStatus.EXPIRED.value}:
                continue
            candidates.append((self._continuity_candidate_score(task, active_workspace_id=active_workspace_id), task))
        if not candidates:
            return {
                "task": None,
                "source": "none",
                "selectionReason": "no_relevant_durable_task",
            }

        _, selected = max(candidates, key=lambda item: item[0])
        saved = self.repository.save_task(selected)
        self._sync_task_memory(saved)
        self.session_state.set_active_task_id(session_id, saved.task_id)
        return {
            "task": saved,
            "source": "recent_durable_task",
            "selectionReason": "matched_active_workspace" if active_workspace_id and saved.workspace_id == active_workspace_id else "most_recent_live_task",
        }

    def _refresh_and_persist_task(self, task: TaskRecord) -> TaskRecord:
        self._refresh_task(task)
        saved = self.repository.save_task(task)
        self._sync_task_memory(saved)
        return saved

    def _write_continuity_metadata(self, task: TaskRecord, *, resume: TaskResumeAssessment) -> None:
        continuity = task.metadata.get("continuity") if isinstance(task.metadata.get("continuity"), dict) else {}
        posture = self._task_posture(task)
        continuity["posture"] = posture
        continuity["resume"] = {
            "status": resume.status,
            "summary": resume.summary,
            "checkedAt": resume.checked_at,
        }
        if "fingerprint" not in continuity:
            continuity["fingerprint"] = self._continuity_fingerprint(task.goal or task.title, self._normalize_requests_from_task(task), task.workspace_id)
        task.metadata["continuity"] = continuity

    def _normalize_requests_from_task(self, task: TaskRecord) -> list[tuple[str, dict[str, Any]]]:
        return [(step.tool_name, dict(step.tool_arguments)) for step in task.steps]

    def _record_duplicate_suppression(self, task: TaskRecord, *, fingerprint: str, status: str, task_id: str) -> None:
        continuity = task.metadata.get("continuity") if isinstance(task.metadata.get("continuity"), dict) else {}
        continuity["fingerprint"] = fingerprint
        continuity["duplicateSuppression"] = {
            "status": status,
            "fingerprint": fingerprint,
            "taskId": task_id,
            "matchedTaskId": task.task_id,
            "recordedAt": utc_now_iso(),
        }
        task.metadata["continuity"] = continuity

    def _record_lifecycle_decision(
        self,
        task: TaskRecord,
        *,
        job: JobRecord,
        incoming_status: str,
        applied: bool,
        reason: str,
        recorded_at: str,
    ) -> None:
        continuity = task.metadata.get("continuity") if isinstance(task.metadata.get("continuity"), dict) else {}
        lifecycle = continuity.get("lifecycle") if isinstance(continuity.get("lifecycle"), dict) else {}
        lifecycle["lastDecision"] = {
            "jobId": job.job_id,
            "stepId": str(job.task_step_id or ""),
            "incomingStatus": incoming_status,
            "applied": applied,
            "reason": reason,
            "recordedAt": recorded_at,
        }
        lifecycle["droppedCount"] = int(lifecycle.get("droppedCount") or 0) + (0 if applied else 1)
        continuity["lifecycle"] = lifecycle
        task.metadata["continuity"] = continuity

    def _should_apply_job_event(
        self,
        task: TaskRecord,
        *,
        job: JobRecord,
        incoming_status: str,
        allow_same_status: bool,
    ) -> tuple[bool, str]:
        link = self._job_link_for(task, job.job_id)
        if link is None:
            return True, "new_lifecycle"
        current_status = str(link.status or "").strip().lower()
        if current_status in _TERMINAL_JOB_STATUSES:
            return False, "terminal_job_replay"
        current_rank = _JOB_STATUS_RANK.get(current_status, -1)
        incoming_rank = _JOB_STATUS_RANK.get(incoming_status, -1)
        if incoming_rank < current_rank:
            return False, "out_of_order_lifecycle"
        if incoming_rank == current_rank and not allow_same_status:
            return False, "duplicate_lifecycle"
        return True, "applied"

    def _job_link_for(self, task: TaskRecord, job_id: str) -> TaskJobLinkRecord | None:
        for link in task.job_links:
            if link.job_id == job_id:
                return link
        return None

    def _refresh_artifact_states(self, task: TaskRecord) -> None:
        for artifact in task.artifacts:
            if artifact.kind != "file" or not artifact.locator:
                continue
            artifact.exists_state = "present" if Path(artifact.locator).exists() else "missing"

    def _recovery_state_for_blockers(self, blockers: list[TaskBlockerRecord]) -> str:
        if not blockers:
            return "required"
        status = self._blocker_resume_status(blockers[-1])
        if status == TaskResumeStatus.WAITING_OPERATOR.value:
            return "waiting_operator"
        if status == TaskResumeStatus.WAITING_ENVIRONMENT.value:
            return "waiting_environment"
        return "required"

    def _blocker_resume_status(self, blocker: TaskBlockerRecord) -> str:
        kind = str(blocker.kind or "").strip().lower()
        if kind == "approval":
            return TaskResumeStatus.WAITING_OPERATOR.value
        if kind in {"environment", "workspace", "dependency", "external"}:
            return TaskResumeStatus.WAITING_ENVIRONMENT.value
        return TaskResumeStatus.BLOCKED.value

    def _resume_label(self, status: str) -> str:
        labels = {
            TaskResumeStatus.WAITING_OPERATOR.value: "Waiting For Operator",
            TaskResumeStatus.WAITING_ENVIRONMENT.value: "Waiting For Environment",
            TaskResumeStatus.VERIFICATION.value: "Verification",
            TaskResumeStatus.STALE.value: "Stale",
            TaskResumeStatus.EXPIRED.value: "Expired",
            TaskResumeStatus.ARCHIVED.value: "Archived",
        }
        return labels.get(status, status.replace("_", " ").title())

    def _task_posture(self, task: TaskRecord) -> dict[str, Any]:
        last_activity_at = self._task_last_activity_at(task)
        age_seconds = self._seconds_since(last_activity_at)
        if task.state in _TERMINAL_TASK_STATES and age_seconds >= _TASK_ARCHIVE_AFTER_SECONDS:
            return {
                "status": TaskResumeStatus.ARCHIVED.value,
                "reason": "terminal_task_aged_out",
                "lastActivityAt": last_activity_at,
            }
        if age_seconds >= _TASK_EXPIRE_AFTER_SECONDS:
            return {
                "status": TaskResumeStatus.EXPIRED.value,
                "reason": "inactive_task_aged_out",
                "lastActivityAt": last_activity_at,
            }
        return {
            "status": "active",
            "reason": "recent_task_activity",
            "lastActivityAt": last_activity_at,
        }

    def _task_last_activity_at(self, task: TaskRecord) -> str:
        candidates = [task.finished_at, task.started_at]
        for step in task.steps:
            candidates.extend([step.started_at, step.finished_at])
        for blocker in task.blockers:
            candidates.extend([blocker.created_at, blocker.resolved_at])
        for checkpoint in task.checkpoints:
            candidates.extend([checkpoint.created_at, checkpoint.completed_at])
        for artifact in task.artifacts:
            candidates.append(artifact.created_at)
        for evidence in task.evidence:
            candidates.append(evidence.created_at)
        for link in task.job_links:
            candidates.extend([link.created_at, link.updated_at])
        valid = [candidate for candidate in candidates if candidate]
        if valid:
            return max(valid)
        if task.created_at:
            return task.created_at
        return utc_now_iso()

    def _seconds_since(self, timestamp: str) -> int:
        parsed = self._parse_timestamp(timestamp)
        if parsed is None:
            return 0
        return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))

    def _parse_timestamp(self, timestamp: str) -> datetime | None:
        value = str(timestamp or "").strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _trust_binding_resumable(self, task: TaskRecord, *, resume: TaskResumeAssessment) -> bool:
        if task.state in {TaskState.COMPLETED.value, TaskState.FAILED.value, TaskState.CANCELLED.value}:
            return False
        return resume.status in {
            TaskResumeStatus.RESUMABLE.value,
            TaskResumeStatus.VERIFICATION.value,
            TaskResumeStatus.BLOCKED.value,
            TaskResumeStatus.WAITING_OPERATOR.value,
            TaskResumeStatus.WAITING_ENVIRONMENT.value,
        }

    def _trust_binding_reason(self, task: TaskRecord, *, resume: TaskResumeAssessment) -> str:
        if task.state == TaskState.COMPLETED.value or resume.status == TaskResumeStatus.COMPLETED.value:
            return "completed"
        if task.state == TaskState.FAILED.value:
            return "failed"
        if task.state == TaskState.CANCELLED.value:
            return "cancelled"
        if resume.status == TaskResumeStatus.STALE.value:
            return "stale"
        if resume.status == TaskResumeStatus.MISSING.value:
            return "missing"
        if resume.status == TaskResumeStatus.WAITING_OPERATOR.value:
            return "waiting_operator"
        if resume.status == TaskResumeStatus.WAITING_ENVIRONMENT.value:
            return "waiting_environment"
        if resume.status == TaskResumeStatus.BLOCKED.value:
            return "blocked"
        if resume.status == TaskResumeStatus.VERIFICATION.value:
            return "verification"
        if resume.status == TaskResumeStatus.EXPIRED.value:
            return "expired"
        if resume.status == TaskResumeStatus.ARCHIVED.value:
            return "archived"
        return "resumable"

    def _sync_task_memory(self, task: TaskRecord) -> None:
        next_steps = [step.title for step in self._next_steps(task)]
        self.memory.sync_task_memory(task, next_steps=next_steps)

    def _task_memory_context(self, task: TaskRecord) -> dict[str, Any]:
        result = self.memory.retrieve(
            MemoryQuery(
                query_id=str(uuid4()),
                retrieval_intent=MemoryRetrievalIntent.TASK_RESUME.value,
                semantic_query_text=" ".join(
                    part
                    for part in [
                        task.title,
                        task.goal,
                        task.latest_summary,
                        task.where_left_off,
                    ]
                    if part
                ),
                scope_constraints={
                    "task_id": task.task_id,
                    "workspace_id": task.workspace_id,
                    "session_id": task.session_id,
                },
                caller_subsystem="tasks",
            )
        )
        return result.to_dict()

    def _append_blocker(
        self,
        task: TaskRecord,
        *,
        step_id: str,
        kind: str,
        title: str,
        detail: str,
        recovery_hint: str,
        created_at: str,
    ) -> None:
        for blocker in task.blockers:
            if (
                blocker.step_id == step_id
                and blocker.kind == kind
                and blocker.title == title
                and blocker.detail == detail
                and blocker.status == "open"
            ):
                return
        task.blockers.append(
            TaskBlockerRecord(
                blocker_id=str(uuid4()),
                task_id=task.task_id,
                step_id=step_id,
                kind=kind,
                title=title,
                detail=detail,
                status="open",
                recovery_hint=recovery_hint,
                created_at=created_at,
            )
        )

    def _resolve_blockers_for_step(self, task: TaskRecord, step_id: str, *, resolved_at: str) -> None:
        for blocker in task.blockers:
            if blocker.step_id == step_id and blocker.status == "open":
                blocker.status = "resolved"
                blocker.resolved_at = resolved_at

    def _upsert_job_link(self, task: TaskRecord, *, job: JobRecord, status: str, updated_at: str) -> None:
        for link in task.job_links:
            if link.job_id == job.job_id:
                current_status = str(link.status or "").strip().lower()
                incoming_status = str(status or "").strip().lower()
                if current_status in _TERMINAL_JOB_STATUSES:
                    return
                if _JOB_STATUS_RANK.get(incoming_status, -1) < _JOB_STATUS_RANK.get(current_status, -1):
                    return
                link.status = status
                link.updated_at = updated_at
                return
        task.job_links.append(
            TaskJobLinkRecord(
                link_id=str(uuid4()),
                task_id=task.task_id,
                step_id=str(job.task_step_id or ""),
                job_id=job.job_id,
                tool_name=job.tool_name,
                status=status,
                created_at=job.created_at or updated_at,
                updated_at=updated_at,
            )
        )

    def _record_artifacts(
        self,
        task: TaskRecord,
        *,
        step_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        candidates: list[tuple[str, str, str]] = []
        path_value = str(arguments.get("path") or "").strip()
        url_value = str(arguments.get("url") or "").strip()
        if path_value:
            candidates.append(("file", path_value, Path(path_value).name or self._tool_label(tool_name)))
        if url_value:
            candidates.append(("url", url_value, self._tool_label(tool_name)))
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if isinstance(data, dict):
            artifact_items = data.get("artifacts")
            if isinstance(artifact_items, list):
                for item in artifact_items:
                    if not isinstance(item, dict):
                        continue
                    locator = str(item.get("locator") or item.get("path") or item.get("url") or "").strip()
                    if not locator:
                        continue
                    candidates.append((str(item.get("kind") or "file"), locator, str(item.get("label") or locator)))
            workspace = data.get("workspace")
            if isinstance(workspace, dict):
                workspace_id = str(workspace.get("workspaceId") or workspace.get("workspace_id") or "").strip()
                if workspace_id:
                    task.workspace_id = workspace_id
                    candidates.append(("workspace", workspace_id, str(workspace.get("name") or "Workspace")))
        existing = {(artifact.kind, artifact.locator, artifact.step_id) for artifact in task.artifacts}
        timestamp = utc_now_iso()
        for kind, locator, label in candidates:
            identity = (kind, locator, step_id)
            if identity in existing:
                continue
            task.artifacts.append(
                TaskArtifactRecord(
                    artifact_id=str(uuid4()),
                    task_id=task.task_id,
                    step_id=step_id,
                    kind=kind,
                    label=label,
                    locator=locator,
                    required_for_resume=(kind == "file"),
                    exists_state="present" if kind != "file" or Path(locator).exists() else "missing",
                    created_at=timestamp,
                )
            )
            existing.add(identity)

    def _record_evidence(
        self,
        task: TaskRecord,
        *,
        step_id: str,
        tool_name: str,
        payload: dict[str, Any],
        created_at: str,
        replace_kind: str | None = None,
    ) -> None:
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            return
        kind = replace_kind or "summary"
        if replace_kind is not None:
            task.evidence = [
                entry
                for entry in task.evidence
                if not (entry.step_id == step_id and entry.kind == replace_kind)
            ]
        elif any(
            entry.step_id == step_id
            and entry.kind == kind
            and entry.summary == summary
            and entry.source == tool_name
            for entry in task.evidence
        ):
            return
        task.evidence.append(
            TaskEvidenceRecord(
                evidence_id=str(uuid4()),
                task_id=task.task_id,
                step_id=step_id,
                kind=kind,
                summary=summary,
                source=tool_name,
                metadata={"data": dict(payload.get("data") or {}) if isinstance(payload.get("data"), dict) else {}},
                created_at=created_at,
            )
        )

    def _apply_verification_summary(
        self,
        task: TaskRecord,
        summary: str,
        *,
        source: str,
        created_at: str,
    ) -> None:
        normalized_summary = summary.strip()
        if any(
            entry.kind == "verification"
            and entry.summary == normalized_summary
            and entry.source == source
            for entry in task.evidence
        ):
            return
        task.evidence.append(
            TaskEvidenceRecord(
                evidence_id=str(uuid4()),
                task_id=task.task_id,
                kind="verification",
                summary=normalized_summary,
                source=source,
                created_at=created_at,
            )
        )
        for checkpoint in task.checkpoints:
            if checkpoint.label == "Verify outcome" and checkpoint.status != "completed":
                checkpoint.status = "completed"
                checkpoint.summary = normalized_summary
                checkpoint.completed_at = created_at

    def _verification_summary(self, payload: dict[str, Any]) -> str:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if isinstance(data, dict):
            summary = str(data.get("verification_summary") or data.get("verificationSummary") or "").strip()
            if summary:
                return summary
        return ""
