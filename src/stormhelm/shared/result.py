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
    approval_state: str = ""
    decision: str = ""
    operator_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "details": self.details,
            "approval_state": self.approval_state,
            "decision": self.decision,
            "operator_message": self.operator_message,
        }


@dataclass(slots=True)
class ToolResult:
    success: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    adapter_contract: dict[str, Any] = field(default_factory=dict)
    adapter_execution: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "summary": self.summary,
            "data": self.data,
            "error": self.error,
            "adapter_contract": self.adapter_contract,
            "adapter_execution": self.adapter_execution,
        }
