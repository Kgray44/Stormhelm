from __future__ import annotations

from pathlib import Path
from typing import Any

from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


class FileReaderTool(BaseTool):
    name = "file_reader"
    display_name = "File Reader"
    description = "Safely read a text file from an allowlisted directory."

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = str(arguments.get("path", "")).strip()
        if not path:
            raise ValueError("File reader requires a 'path'.")
        return {"path": path}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        decision = context.safety_policy.can_read_path(arguments["path"])
        if not decision.allowed:
            return ToolResult(
                success=False,
                summary="File read blocked by allowlist policy.",
                data={"decision": decision.to_dict()},
                error=decision.reason,
            )

        path = Path(arguments["path"]).expanduser().resolve()
        if not path.exists() or not path.is_file():
            return ToolResult(
                success=False,
                summary="File does not exist.",
                data={"path": str(path)},
                error="missing_file",
            )

        max_bytes = context.config.tools.max_file_read_bytes
        raw_text = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(raw_text.encode("utf-8")) > max_bytes
        content = raw_text[:max_bytes] if truncated else raw_text
        return ToolResult(
            success=True,
            summary=f"Read {len(content)} characters from {path.name}.",
            data={
                "path": str(path),
                "content": content,
                "truncated": truncated,
            },
        )

