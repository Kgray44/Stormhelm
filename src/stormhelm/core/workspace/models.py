from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkspaceRecord:
    workspace_id: str
    name: str
    topic: str
    summary: str
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    last_opened_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspaceId": self.workspace_id,
            "name": self.name,
            "topic": self.topic,
            "summary": self.summary,
            "tags": list(self.tags),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "lastOpenedAt": self.last_opened_at,
        }


@dataclass(slots=True)
class WorkspaceItemRecord:
    item_id: str
    workspace_id: str
    item_key: str
    kind: str
    viewer: str
    title: str
    subtitle: str
    module_key: str
    section_key: str
    url: str
    path: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    opened_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    last_opened_at: str = ""

    def to_action_item(self) -> dict[str, Any]:
        payload = dict(self.metadata)
        payload.setdefault("itemId", self.item_id)
        payload.setdefault("kind", self.kind)
        payload.setdefault("viewer", self.viewer)
        payload.setdefault("title", self.title)
        payload.setdefault("subtitle", self.subtitle)
        payload.setdefault("module", self.module_key)
        if self.url:
            payload.setdefault("url", self.url)
        if self.path:
            payload.setdefault("path", self.path)
        if self.summary:
            payload.setdefault("summary", self.summary)
        return payload
