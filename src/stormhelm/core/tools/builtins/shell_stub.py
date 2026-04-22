from __future__ import annotations

from typing import Any

from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import build_execution_report
from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import SafetyClassification, ToolResult


class ShellCommandStubTool(BaseTool):
    name = "shell_command"
    display_name = "Shell Command Stub"
    description = "Demonstrate strict action-tool gating without enabling shell execution."
    category = "system"
    classification = SafetyClassification.ACTION

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command that was requested.",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = str(arguments.get("command", "")).strip()
        if not command:
            raise ValueError("Shell stub requires a 'command'.")
        return {"command": command}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        contract = self.resolve_adapter_contract(arguments)
        execution = build_execution_report(
            contract,
            success=False,
            observed_outcome=ClaimOutcome.PREVIEW,
            evidence=["Captured the requested command without running it."],
            failure_kind="manual_approval_required",
        ) if contract is not None else None
        return ToolResult(
            success=False,
            summary="Shell execution is intentionally disabled in Phase 1.",
            data={"requested_command": arguments["command"]},
            error="manual_approval_required",
            adapter_contract=contract.to_dict() if contract is not None else {},
            adapter_execution=execution.to_dict() if execution is not None else {},
        )
