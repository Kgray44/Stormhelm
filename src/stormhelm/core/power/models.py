from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RecipeDefinition:
    name: str
    title: str
    description: str
    execution_kind: str
    parameters: dict[str, Any] = field(default_factory=dict)
    source_type: str = "built_in"
    guardrail: str = "caution"
    schedule_mode: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "execution_kind": self.execution_kind,
            "parameters": dict(self.parameters),
            "source_type": self.source_type,
            "guardrail": self.guardrail,
            "schedule_mode": self.schedule_mode,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecipeDefinition:
        return cls(
            name=str(data.get("name", "")).strip(),
            title=str(data.get("title", "")).strip(),
            description=str(data.get("description", "")).strip(),
            execution_kind=str(data.get("execution_kind", "")).strip(),
            parameters=dict(data.get("parameters") or {}),
            source_type=str(data.get("source_type", "built_in")).strip() or "built_in",
            guardrail=str(data.get("guardrail", "caution")).strip() or "caution",
            schedule_mode=str(data.get("schedule_mode", "manual")).strip() or "manual",
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(slots=True)
class RoutineDefinition:
    name: str
    title: str
    description: str
    execution_kind: str
    parameters: dict[str, Any] = field(default_factory=dict)
    source_type: str = "saved"
    guardrail: str = "caution"
    schedule_mode: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "execution_kind": self.execution_kind,
            "parameters": dict(self.parameters),
            "source_type": self.source_type,
            "guardrail": self.guardrail,
            "schedule_mode": self.schedule_mode,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoutineDefinition:
        return cls(
            name=str(data.get("name", "")).strip(),
            title=str(data.get("title", "")).strip(),
            description=str(data.get("description", "")).strip(),
            execution_kind=str(data.get("execution_kind", "")).strip(),
            parameters=dict(data.get("parameters") or {}),
            source_type=str(data.get("source_type", "saved")).strip() or "saved",
            guardrail=str(data.get("guardrail", "caution")).strip() or "caution",
            schedule_mode=str(data.get("schedule_mode", "manual")).strip() or "manual",
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(slots=True)
class TrustedHookDefinition:
    name: str
    title: str
    command_path: str
    arguments: list[str] = field(default_factory=list)
    working_directory: str | None = None
    description: str = ""
    source_type: str = "custom"
    guardrail: str = "explicit"
    timeout_seconds: float = 60.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "command_path": self.command_path,
            "arguments": list(self.arguments),
            "working_directory": self.working_directory,
            "description": self.description,
            "source_type": self.source_type,
            "guardrail": self.guardrail,
            "timeout_seconds": float(self.timeout_seconds),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrustedHookDefinition:
        return cls(
            name=str(data.get("name", "")).strip(),
            title=str(data.get("title", "")).strip(),
            command_path=str(data.get("command_path", "")).strip(),
            arguments=[str(item).strip() for item in data.get("arguments", []) if str(item).strip()],
            working_directory=str(data.get("working_directory", "")).strip() or None,
            description=str(data.get("description", "")).strip(),
            source_type=str(data.get("source_type", "custom")).strip() or "custom",
            guardrail=str(data.get("guardrail", "explicit")).strip() or "explicit",
            timeout_seconds=float(data.get("timeout_seconds", 60.0) or 60.0),
            metadata=dict(data.get("metadata") or {}),
        )
