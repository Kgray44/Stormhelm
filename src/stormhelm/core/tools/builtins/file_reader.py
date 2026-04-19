from __future__ import annotations

from pathlib import Path
from typing import Any

from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


class FileReaderTool(BaseTool):
    name = "file_reader"
    display_name = "File Reader"
    description = "Safely read a text file from an allowlisted directory."
    category = "files"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to an allowlisted text file."},
            },
            "required": ["path"],
            "additionalProperties": False,
        }

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
        raw_bytes = path.read_bytes()
        truncated = len(raw_bytes) > max_bytes
        content_bytes = raw_bytes[:max_bytes]
        content = content_bytes.decode("utf-8", errors="replace")
        return ToolResult(
            success=True,
            summary=f"Read {len(content_bytes)} bytes from {path.name}.",
            data={
                "path": str(path),
                "content": content,
                "truncated": truncated,
                "bytes_read": len(content_bytes),
            },
        )
