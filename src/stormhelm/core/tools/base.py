from __future__ import annotations

import asyncio
from abc import ABC
from dataclasses import dataclass, field
from typing import Any

from stormhelm.config.models import AppConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.memory.repositories import NotesRepository, PreferencesRepository
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.shared.result import ExecutionMode, SafetyClassification, ToolResult


@dataclass(slots=True)
class ToolContext:
    job_id: str
    config: AppConfig
    events: EventBuffer
    notes: NotesRepository
    preferences: PreferencesRepository
    safety_policy: SafetyPolicy
    cancellation_requested: asyncio.Event = field(default_factory=asyncio.Event)


class BaseTool(ABC):
    name: str = "base"
    display_name: str = "Base Tool"
    description: str = ""
    classification: SafetyClassification = SafetyClassification.READ_ONLY
    execution_mode: ExecutionMode = ExecutionMode.SYNC
    timeout_seconds: float | None = None

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "classification": self.classification.value,
            "execution_mode": self.execution_mode.value,
            "timeout_seconds": self.timeout_seconds,
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

