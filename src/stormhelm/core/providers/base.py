from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ProviderTurnResult:
    response_id: str | None
    output_text: str
    tool_calls: list[ProviderToolCall] = field(default_factory=list)
    raw_response: dict[str, Any] = field(default_factory=dict)


class AssistantProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        *,
        instructions: str,
        input_items: str | list[dict[str, Any]],
        previous_response_id: str | None,
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_output_tokens: int | None = None,
    ) -> ProviderTurnResult:
        raise NotImplementedError
