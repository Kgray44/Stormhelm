from __future__ import annotations

from typing import Any

from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.core.workflows.service import WorkflowPowerService
from stormhelm.shared.result import ToolResult


class DesktopSearchTool(BaseTool):
    name = "desktop_search"
    display_name = "Desktop Search"
    description = "Search files, apps, and windows deterministically, then open or focus the strongest match when requested."
    category = "workflow"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "domains": {"type": "array", "items": {"type": "string"}},
                "action": {"type": "string", "enum": ["search", "open"], "default": "search"},
                "open_target": {"type": "string", "enum": ["deck", "external"], "default": "deck"},
                "latest_only": {"type": "boolean", "default": False},
                "file_extensions": {"type": "array", "items": {"type": "string"}},
                "folder_hint": {"type": "string"},
                "prefer_folders": {"type": "boolean", "default": False},
                "session_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 12},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        domains = arguments.get("domains")
        return {
            "query": str(arguments.get("query", "")).strip(),
            "domains": [str(item).strip().lower() for item in domains if str(item).strip()] if isinstance(domains, list) else None,
            "action": str(arguments.get("action", "search")).strip().lower() or "search",
            "open_target": str(arguments.get("open_target", "deck")).strip().lower() or "deck",
            "latest_only": bool(arguments.get("latest_only", False)),
            "file_extensions": [str(item).strip().lower() for item in arguments.get("file_extensions", []) if str(item).strip()]
            if isinstance(arguments.get("file_extensions"), list)
            else None,
            "folder_hint": str(arguments.get("folder_hint", "")).strip() or None,
            "prefer_folders": bool(arguments.get("prefer_folders", False)),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
            "limit": max(1, min(int(arguments.get("limit", 8) or 8), 12)),
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        return WorkflowPowerService(context).desktop_search(**arguments)


class WorkflowExecuteTool(BaseTool):
    name = "workflow_execute"
    display_name = "Workflow Execute"
    description = "Execute a structured multi-step setup or workflow chain."
    category = "workflow"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workflow_kind": {"type": "string"},
                "query": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["workflow_kind"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_kind": str(arguments.get("workflow_kind", "")).strip().lower(),
            "query": str(arguments.get("query", "")).strip(),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        return WorkflowPowerService(context).execute_workflow(**arguments)


class RepairActionTool(BaseTool):
    name = "repair_action"
    display_name = "Repair Action"
    description = "Run deterministic repair and recovery chains like connectivity checks, DNS flushes, and relaunch flows."
    category = "workflow"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repair_kind": {"type": "string"},
                "target": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["repair_kind"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "repair_kind": str(arguments.get("repair_kind", "")).strip().lower(),
            "target": str(arguments.get("target", "")).strip(),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        return WorkflowPowerService(context).repair_action(**arguments)
