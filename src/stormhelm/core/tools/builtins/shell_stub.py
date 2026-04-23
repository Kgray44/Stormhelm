from __future__ import annotations

import subprocess
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
        if context.config.safety.unsafe_test_mode:
            return self._execute_live_command(context, arguments["command"])

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

    def _execute_live_command(self, context: ToolContext, command: str) -> ToolResult:
        timeout_seconds = max(1.0, float(context.config.concurrency.default_job_timeout_seconds))
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=str(context.config.project_root),
            )
        except subprocess.TimeoutExpired as error:
            return ToolResult(
                success=False,
                summary=f"Shell command timed out after {timeout_seconds:.0f} seconds.",
                data={
                    "command": command,
                    "stdout": error.stdout or "",
                    "stderr": error.stderr or "",
                    "exit_code": None,
                    "timed_out": True,
                },
                error="timeout",
            )
        except Exception as error:
            return ToolResult(
                success=False,
                summary="Shell command could not be started.",
                data={
                    "command": command,
                    "stdout": "",
                    "stderr": "",
                    "exit_code": None,
                },
                error=str(error),
            )

        success = completed.returncode == 0
        summary = (
            f"Shell command completed with exit code {completed.returncode}."
            if success
            else f"Shell command exited with code {completed.returncode}."
        )
        return ToolResult(
            success=success,
            summary=summary,
            data={
                "command": command,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "exit_code": completed.returncode,
                "timed_out": False,
            },
            error=None if success else completed.stderr.strip() or f"exit_code:{completed.returncode}",
        )
