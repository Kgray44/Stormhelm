from __future__ import annotations

from typing import Any

from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


class EchoTool(BaseTool):
    name = "echo"
    display_name = "Echo"
    description = "Echo text back for development and diagnostics."

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        text = str(arguments.get("text", "")).strip()
        if not text:
            raise ValueError("Echo tool requires a non-empty 'text' field.")
        return {"text": text}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=True,
            summary=f"Echoed {len(arguments['text'])} characters.",
            data={"text": arguments["text"]},
        )

