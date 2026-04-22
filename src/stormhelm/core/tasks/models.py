from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskState(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    PAUSED = "paused"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStepState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskResumeStatus(str, Enum):
    RESUMABLE = "resumable"
    BLOCKED = "blocked"
    STALE = "stale"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    MISSING = "missing"


@dataclass(slots=True)
class TaskDependencyRecord:
    dependency_id: str
    task_id: str
    step_id: str
    depends_on_step_id: str
    dependency_kind: str = "finish_to_start"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependencyId": self.dependency_id,
            "taskId": self.task_id,
            "stepId": self.step_id,
            "dependsOnStepId": self.depends_on_step_id,
            "dependencyKind": self.dependency_kind,
        }


@dataclass(slots=True)
class TaskBlockerRecord:
    blocker_id: str
    task_id: str
    step_id: str = ""
    kind: str = "recovery"
    title: str = ""
    detail: str = ""
    status: str = "open"
    recovery_hint: str = ""
    created_at: str = ""
    resolved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "blockerId": self.blocker_id,
            "taskId": self.task_id,
            "stepId": self.step_id,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "status": self.status,
            "recoveryHint": self.recovery_hint,
            "createdAt": self.created_at,
            "resolvedAt": self.resolved_at,
        }


@dataclass(slots=True)
class TaskCheckpointRecord:
    checkpoint_id: str
    task_id: str
    step_id: str = ""
    label: str = ""
    status: str = "pending"
    summary: str = ""
    created_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpointId": self.checkpoint_id,
            "taskId": self.task_id,
            "stepId": self.step_id,
            "label": self.label,
            "status": self.status,
            "summary": self.summary,
            "createdAt": self.created_at,
            "completedAt": self.completed_at,
        }


@dataclass(slots=True)
class TaskArtifactRecord:
    artifact_id: str
    task_id: str
    step_id: str = ""
    kind: str = "file"
    label: str = ""
    locator: str = ""
    required_for_resume: bool = True
    exists_state: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "taskId": self.task_id,
            "stepId": self.step_id,
            "kind": self.kind,
            "label": self.label,
            "locator": self.locator,
            "requiredForResume": self.required_for_resume,
            "existsState": self.exists_state,
            "metadata": dict(self.metadata),
            "createdAt": self.created_at,
        }


@dataclass(slots=True)
class TaskEvidenceRecord:
    evidence_id: str
    task_id: str
    step_id: str = ""
    kind: str = "summary"
    summary: str = ""
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidenceId": self.evidence_id,
            "taskId": self.task_id,
            "stepId": self.step_id,
            "kind": self.kind,
            "summary": self.summary,
            "source": self.source,
            "metadata": dict(self.metadata),
            "createdAt": self.created_at,
        }


@dataclass(slots=True)
class TaskJobLinkRecord:
    link_id: str
    task_id: str
    step_id: str
    job_id: str
    tool_name: str = ""
    status: str = "queued"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "linkId": self.link_id,
            "taskId": self.task_id,
            "stepId": self.step_id,
            "jobId": self.job_id,
            "toolName": self.tool_name,
            "status": self.status,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(slots=True)
class TaskStepRecord:
    step_id: str
    task_id: str
    sequence_index: int
    title: str
    detail: str = ""
    tool_name: str = ""
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    state: str = TaskStepState.PENDING.value
    summary: str = ""
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self, *, job_links: list[TaskJobLinkRecord] | None = None) -> dict[str, Any]:
        latest_job = None
        if job_links:
            for link in reversed(job_links):
                if link.step_id == self.step_id:
                    latest_job = link
                    break
        return {
            "stepId": self.step_id,
            "taskId": self.task_id,
            "sequenceIndex": self.sequence_index,
            "title": self.title,
            "detail": self.detail,
            "toolName": self.tool_name,
            "toolArguments": dict(self.tool_arguments),
            "state": self.state,
            "summary": self.summary,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "jobId": latest_job.job_id if latest_job is not None else "",
            "jobStatus": latest_job.status if latest_job is not None else "",
        }


@dataclass(slots=True)
class TaskResumeAssessment:
    status: str
    summary: str
    can_resume: bool
    checked_at: str
    next_steps: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    missing_artifacts: list[str] = field(default_factory=list)
    recovery_advice: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "canResume": self.can_resume,
            "checkedAt": self.checked_at,
            "nextSteps": list(self.next_steps),
            "blockingReasons": list(self.blocking_reasons),
            "missingArtifacts": list(self.missing_artifacts),
            "recoveryAdvice": list(self.recovery_advice),
        }


@dataclass(slots=True)
class TaskExecutionPlan:
    task_id: str
    step_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    session_id: str
    workspace_id: str = ""
    title: str = ""
    summary: str = ""
    goal: str = ""
    origin: str = ""
    state: str = TaskState.PLANNED.value
    recovery_state: str = ""
    latest_summary: str = ""
    evidence_summary: str = ""
    where_left_off: str = ""
    active_step_id: str = ""
    last_completed_step_id: str = ""
    hooks: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    steps: list[TaskStepRecord] = field(default_factory=list)
    dependencies: list[TaskDependencyRecord] = field(default_factory=list)
    blockers: list[TaskBlockerRecord] = field(default_factory=list)
    checkpoints: list[TaskCheckpointRecord] = field(default_factory=list)
    artifacts: list[TaskArtifactRecord] = field(default_factory=list)
    evidence: list[TaskEvidenceRecord] = field(default_factory=list)
    job_links: list[TaskJobLinkRecord] = field(default_factory=list)

    def to_dict(self, *, resume_assessment: TaskResumeAssessment | None = None) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "sessionId": self.session_id,
            "workspaceId": self.workspace_id,
            "title": self.title,
            "summary": self.summary,
            "goal": self.goal,
            "origin": self.origin,
            "state": self.state,
            "recoveryState": self.recovery_state,
            "latestSummary": self.latest_summary,
            "evidenceSummary": self.evidence_summary,
            "whereLeftOff": self.where_left_off,
            "activeStepId": self.active_step_id,
            "lastCompletedStepId": self.last_completed_step_id,
            "hooks": dict(self.hooks),
            "metadata": dict(self.metadata),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "steps": [step.to_dict(job_links=self.job_links) for step in self.steps],
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "checkpoints": [checkpoint.to_dict() for checkpoint in self.checkpoints],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "evidence": [entry.to_dict() for entry in self.evidence],
            "jobLinks": [link.to_dict() for link in self.job_links],
            "resumeAssessment": resume_assessment.to_dict() if resume_assessment is not None else {},
        }
