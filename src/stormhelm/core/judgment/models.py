from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionRiskTier(str, Enum):
    SAFE = "safe"
    CAUTION = "caution"
    HIGH = "high"


@dataclass(slots=True)
class GuardrailDecision:
    risk_tier: ActionRiskTier = ActionRiskTier.SAFE
    outcome: str = "act_direct"
    notice: str = ""
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SuggestionCandidate:
    key: str
    title: str
    command: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "command": self.command,
            "reason": self.reason,
        }


@dataclass(slots=True)
class PostActionJudgmentResult:
    next_suggestion: dict[str, Any] | None = None
    suppressed_reason: str | None = None
    recovery: bool = False
    debug: dict[str, Any] = field(default_factory=dict)
