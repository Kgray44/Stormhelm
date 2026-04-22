"""Persistence and semantic memory layer for Stormhelm."""

from typing import TYPE_CHECKING

from stormhelm.core.memory.models import (
    MemoryFamily,
    MemoryFreshnessState,
    MemoryProvenance,
    MemoryQuery,
    MemoryRecord,
    MemoryResult,
    MemoryRetrievalIntent,
    MemorySourceClass,
)
from stormhelm.core.memory.repositories import SemanticMemoryRepository

if TYPE_CHECKING:
    from stormhelm.core.memory.service import SemanticMemoryService

__all__ = [
    "MemoryFamily",
    "MemoryFreshnessState",
    "MemoryProvenance",
    "MemoryQuery",
    "MemoryRecord",
    "MemoryResult",
    "MemoryRetrievalIntent",
    "MemorySourceClass",
    "SemanticMemoryRepository",
    "SemanticMemoryService",
]


def __getattr__(name: str) -> object:
    if name == "SemanticMemoryService":
        from stormhelm.core.memory.service import SemanticMemoryService

        return SemanticMemoryService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
