from typing import TYPE_CHECKING

from stormhelm.core.tasks.models import (
    TaskExecutionPlan,
    TaskRecord,
    TaskResumeAssessment,
    TaskResumeStatus,
    TaskState,
    TaskStepRecord,
    TaskStepState,
)
from stormhelm.core.tasks.repository import TaskRepository

if TYPE_CHECKING:
    from stormhelm.core.tasks.service import DurableTaskService

__all__ = [
    "DurableTaskService",
    "TaskExecutionPlan",
    "TaskRecord",
    "TaskRepository",
    "TaskResumeAssessment",
    "TaskResumeStatus",
    "TaskState",
    "TaskStepRecord",
    "TaskStepState",
]


def __getattr__(name: str) -> object:
    if name == "DurableTaskService":
        from stormhelm.core.tasks.service import DurableTaskService

        return DurableTaskService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
