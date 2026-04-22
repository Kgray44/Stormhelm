from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from stormhelm.shared.time import utc_now_iso


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(slots=True)
class JobRecord:
    job_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: JobStatus
    created_at: str
    timeout_seconds: float
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    cancel_requested: bool = False
    task_id: str | None = None
    task_step_id: str | None = None

    @classmethod
    def queued(
        cls,
        job_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
        *,
        task_id: str | None = None,
        task_step_id: str | None = None,
    ) -> "JobRecord":
        return cls(
            job_id=job_id,
            tool_name=tool_name,
            arguments=arguments,
            status=JobStatus.QUEUED,
            created_at=utc_now_iso(),
            timeout_seconds=timeout_seconds,
            task_id=task_id,
            task_step_id=task_step_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status.value,
            "created_at": self.created_at,
            "timeout_seconds": self.timeout_seconds,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "task_id": self.task_id,
            "task_step_id": self.task_step_id,
        }
