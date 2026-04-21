from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ContextEntity:
    title: str = ""
    kind: str = ""
    path: str | None = None
    url: str | None = None
    item_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "kind": self.kind,
            "path": self.path,
            "url": self.url,
            "itemId": self.item_id,
        }


@dataclass(slots=True)
class ActiveWorkContext:
    active_goal: str = ""
    workspace: dict[str, Any] = field(default_factory=dict)
    selection: dict[str, Any] = field(default_factory=dict)
    clipboard: dict[str, Any] = field(default_factory=dict)
    recent_entities: list[dict[str, Any]] = field(default_factory=list)
    last_action: str = ""
    current_problem_domain: str = ""
    pending_next_steps: list[str] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_goal": self.active_goal,
            "workspace": dict(self.workspace),
            "selection": dict(self.selection),
            "clipboard": dict(self.clipboard),
            "recent_entities": [dict(item) for item in self.recent_entities],
            "last_action": self.last_action,
            "current_problem_domain": self.current_problem_domain,
            "pending_next_steps": list(self.pending_next_steps),
            "updated_at": self.updated_at,
        }
