from __future__ import annotations

import asyncio
from abc import ABC
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable

from stormhelm.config.models import AppConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.memory.repositories import NotesRepository, PreferencesRepository
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.shared.result import ExecutionMode, SafetyClassification, ToolResult

if TYPE_CHECKING:
    from stormhelm.core.system.probe import SystemProbe
    from stormhelm.core.tasks.service import DurableTaskService
    from stormhelm.core.workspace.service import WorkspaceService


@dataclass(slots=True)
class ToolContext:
    job_id: str
    config: AppConfig
    events: EventBuffer
    notes: NotesRepository
    preferences: PreferencesRepository
    safety_policy: SafetyPolicy
    system_probe: SystemProbe | None = None
    workspace_service: WorkspaceService | None = None
    task_service: DurableTaskService | None = None
    progress_callback: Callable[[dict[str, Any]], None] | None = None
    cancellation_requested: asyncio.Event = field(default_factory=asyncio.Event)

    def report_progress(self, payload: dict[str, Any]) -> None:
        if callable(self.progress_callback):
            self.progress_callback(dict(payload))


class BaseTool(ABC):
    name: str = "base"
    display_name: str = "Base Tool"
    description: str = ""
    category: str = "general"
    classification: SafetyClassification = SafetyClassification.READ_ONLY
    execution_mode: ExecutionMode = ExecutionMode.SYNC
    timeout_seconds: float | None = None

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "classification": self.classification.value,
            "execution_mode": self.execution_mode.value,
            "timeout_seconds": self.timeout_seconds,
        }

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    def response_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameter_schema(),
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return arguments

    async def execute(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        validated = self.validate(arguments)
        if self.execution_mode == ExecutionMode.ASYNC:
            return await self.execute_async(context, validated)
        return await asyncio.to_thread(self.execute_sync, context, validated)

    async def execute_async(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(f"{self.name} does not implement async execution.")

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError(f"{self.name} does not implement sync execution.")
