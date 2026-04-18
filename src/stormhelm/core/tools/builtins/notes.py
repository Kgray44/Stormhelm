from __future__ import annotations

from typing import Any

from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


class NotesWriteTool(BaseTool):
    name = "notes_write"
    display_name = "Notes Writer"
    description = "Persist a note to local Stormhelm memory storage."

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        title = str(arguments.get("title", "")).strip()
        content = str(arguments.get("content", "")).strip()
        if not title:
            raise ValueError("Notes writer requires a 'title'.")
        if not content:
            raise ValueError("Notes writer requires 'content'.")
        return {"title": title, "content": content}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        note = context.notes.create_note(arguments["title"], arguments["content"])
        return ToolResult(
            success=True,
            summary=f"Saved note '{note.title}'.",
            data=note.to_dict(),
        )

