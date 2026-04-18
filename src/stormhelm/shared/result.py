from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SafetyClassification(str, Enum):
    READ_ONLY = "read_only"
    ACTION = "action"
    DEVELOPMENT = "development"


class ExecutionMode(str, Enum):
    SYNC = "sync"
    ASYNC = "async"


@dataclass(slots=True)
class SafetyDecision:
    allowed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass(slots=True)
class ToolResult:
    success: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "summary": self.summary,
            "data": self.data,
            "error": self.error,
        }
