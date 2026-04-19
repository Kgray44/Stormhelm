from __future__ import annotations

from typing import Any

from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


class WorkspaceRestoreTool(BaseTool):
    name = "workspace_restore"
    display_name = "Workspace Restore"
    description = "Restore a remembered Stormhelm workspace into the Deck using persistent memory and indexed local bearings."
    category = "workspace"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The workspace or project to restore."},
                "session_id": {"type": "string", "description": "Stormhelm session identifier."},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("workspace_restore requires a non-empty query.")
        return {
            "query": query,
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if context.workspace_service is None:
            return ToolResult(success=False, summary="Workspace memory is unavailable.", error="workspace_service_unavailable")
        result = context.workspace_service.restore_workspace(arguments["query"], session_id=arguments["session_id"])
        return ToolResult(success=True, summary=result["summary"], data=result)


class WorkspaceAssembleTool(BaseTool):
    name = "workspace_assemble"
    display_name = "Workspace Assemble"
    description = "Assemble a fresh Deck workspace from remembered context, notes, and local relevant files."
    category = "workspace"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The topic or project to assemble."},
                "session_id": {"type": "string", "description": "Stormhelm session identifier."},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("workspace_assemble requires a non-empty query.")
        return {
            "query": query,
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if context.workspace_service is None:
            return ToolResult(success=False, summary="Workspace memory is unavailable.", error="workspace_service_unavailable")
        result = context.workspace_service.assemble_workspace(arguments["query"], session_id=arguments["session_id"])
        return ToolResult(success=True, summary=result["summary"], data=result)
