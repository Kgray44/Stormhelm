from __future__ import annotations

from typing import Any

from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import attach_contract_metadata
from stormhelm.core.adapters import build_execution_report
from stormhelm.core.power.service import LongTailPowerService
from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import SafetyClassification, ToolResult


class RoutineExecuteTool(BaseTool):
    name = "routine_execute"
    display_name = "Routine Execute"
    description = "Run a saved routine or built-in recipe deterministically."
    category = "power"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "routine_name": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["routine_name"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "routine_name": str(arguments.get("routine_name", "")).strip(),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        return LongTailPowerService(context).execute_routine(**arguments)


class RoutineSaveTool(BaseTool):
    name = "routine_save"
    display_name = "Routine Save"
    description = "Save a reusable routine backed by deterministic built-in actions."
    category = "power"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "routine_name": {"type": "string"},
                "execution_kind": {"type": "string"},
                "parameters": {"type": "object"},
                "description": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["routine_name", "execution_kind", "parameters"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "routine_name": str(arguments.get("routine_name", "")).strip(),
            "execution_kind": str(arguments.get("execution_kind", "")).strip().lower(),
            "parameters": dict(arguments.get("parameters") or {}),
            "description": str(arguments.get("description", "")).strip(),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        return LongTailPowerService(context).save_routine(**arguments)


class TrustedHookRegisterTool(BaseTool):
    name = "trusted_hook_register"
    display_name = "Trusted Hook Register"
    description = "Register a trusted local script or executable hook for explicit later use."
    category = "power"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hook_name": {"type": "string"},
                "command_path": {"type": "string"},
                "arguments": {"type": "array", "items": {"type": "string"}},
                "working_directory": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["hook_name", "command_path"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "hook_name": str(arguments.get("hook_name", "")).strip(),
            "command_path": str(arguments.get("command_path", "")).strip(),
            "arguments": [str(item).strip() for item in arguments.get("arguments", []) if str(item).strip()]
            if isinstance(arguments.get("arguments"), list)
            else [],
            "working_directory": str(arguments.get("working_directory", "")).strip() or None,
            "description": str(arguments.get("description", "")).strip(),
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        return LongTailPowerService(context).register_trusted_hook(**arguments)


class TrustedHookExecuteTool(BaseTool):
    name = "trusted_hook_execute"
    display_name = "Trusted Hook Execute"
    description = "Run an explicitly registered trusted local hook."
    category = "power"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hook_name": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["hook_name"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "hook_name": str(arguments.get("hook_name", "")).strip(),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        return LongTailPowerService(context).execute_trusted_hook(**arguments)


class FileOperationTool(BaseTool):
    name = "file_operation"
    display_name = "File Operation"
    description = "Run bounded deterministic file and folder operations with preview support."
    category = "power"
    classification = SafetyClassification.ACTION

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {"type": "string"},
                "source_paths": {"type": "array", "items": {"type": "string"}},
                "target_directory": {"type": "string"},
                "destination_directory": {"type": "string"},
                "target_mode": {"type": "string"},
                "dry_run": {"type": "boolean"},
                "older_than_days": {"type": "integer"},
                "pattern": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "operation": str(arguments.get("operation", "")).strip().lower(),
            "source_paths": [str(item).strip() for item in arguments.get("source_paths", []) if str(item).strip()]
            if isinstance(arguments.get("source_paths"), list)
            else None,
            "target_directory": str(arguments.get("target_directory", "")).strip() or None,
            "destination_directory": str(arguments.get("destination_directory", "")).strip() or None,
            "target_mode": str(arguments.get("target_mode", "explicit")).strip().lower() or "explicit",
            "dry_run": bool(arguments.get("dry_run", False)),
            "older_than_days": int(arguments.get("older_than_days")) if isinstance(arguments.get("older_than_days"), (int, float)) else None,
            "pattern": str(arguments.get("pattern", "")).strip(),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        result = LongTailPowerService(context).file_operation(**arguments)
        contract = self.resolve_adapter_contract(arguments)
        if contract is None:
            return result
        execution = build_execution_report(
            contract,
            success=result.success,
            observed_outcome=ClaimOutcome.PREVIEW if bool(arguments.get("dry_run")) else ClaimOutcome.COMPLETED,
            evidence=[
                "Generated a dry-run preview for the requested file operation."
                if bool(arguments.get("dry_run"))
                else "Completed the requested bounded file operation."
            ],
            failure_kind=result.error if not result.success else None,
        )
        result.adapter_contract = contract.to_dict()
        result.adapter_execution = execution.to_dict()
        if isinstance(result.data, dict):
            action = result.data.get("action")
            if isinstance(action, dict):
                result.data["action"] = attach_contract_metadata(action, contract=contract, execution=execution)
            action_list = result.data.get("actions")
            if isinstance(action_list, list):
                result.data["actions"] = [
                    attach_contract_metadata(item, contract=contract, execution=execution) if isinstance(item, dict) else item
                    for item in action_list
                ]
        return result


class MaintenanceActionTool(BaseTool):
    name = "maintenance_action"
    display_name = "Maintenance Action"
    description = "Run bounded maintenance and cleanup actions with structured progress and summaries."
    category = "power"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "maintenance_kind": {"type": "string"},
                "target_directory": {"type": "string"},
                "older_than_days": {"type": "integer"},
                "dry_run": {"type": "boolean"},
                "session_id": {"type": "string"},
            },
            "required": ["maintenance_kind"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "maintenance_kind": str(arguments.get("maintenance_kind", "")).strip().lower(),
            "target_directory": str(arguments.get("target_directory", "")).strip() or None,
            "older_than_days": int(arguments.get("older_than_days")) if isinstance(arguments.get("older_than_days"), (int, float)) else None,
            "dry_run": bool(arguments.get("dry_run", False)),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        return LongTailPowerService(context).maintenance_action(**arguments)
