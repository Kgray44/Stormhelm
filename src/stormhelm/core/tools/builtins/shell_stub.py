from __future__ import annotations

from typing import Any

from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import SafetyClassification, ToolResult


class ShellCommandStubTool(BaseTool):
    name = "shell_command"
    display_name = "Shell Command Stub"
    description = "Demonstrate strict action-tool gating without enabling shell execution."
    classification = SafetyClassification.ACTION

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = str(arguments.get("command", "")).strip()
        if not command:
            raise ValueError("Shell stub requires a 'command'.")
        return {"command": command}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=False,
            summary="Shell execution is intentionally disabled in Phase 1.",
            data={"requested_command": arguments["command"]},
            error="manual_approval_required",
        )
