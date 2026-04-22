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


class WorkspaceSaveTool(BaseTool):
    name = "workspace_save"
    display_name = "Workspace Save"
    description = "Save the current active Stormhelm workspace and snapshot the current task posture."
    category = "workspace"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Stormhelm session identifier."},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"session_id": str(arguments.get("session_id", "default")).strip() or "default"}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if context.workspace_service is None:
            return ToolResult(success=False, summary="Workspace memory is unavailable.", error="workspace_service_unavailable")
        result = context.workspace_service.save_workspace(session_id=arguments["session_id"])
        return ToolResult(success=True, summary=result["summary"], data=result)


class WorkspaceClearTool(BaseTool):
    name = "workspace_clear"
    display_name = "Workspace Clear"
    description = "Clear the active workspace posture from the current Deck session without deleting retained history."
    category = "workspace"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Stormhelm session identifier."},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"session_id": str(arguments.get("session_id", "default")).strip() or "default"}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if context.workspace_service is None:
            return ToolResult(success=False, summary="Workspace clearing not available yet.", error="workspace_service_unavailable")
        result = context.workspace_service.clear_workspace(session_id=arguments["session_id"])
        return ToolResult(success=True, summary=result["summary"], data=result)


class WorkspaceArchiveTool(BaseTool):
    name = "workspace_archive"
    display_name = "Workspace Archive"
    description = "Archive the active workspace, preserving it for later restore."
    category = "workspace"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional workspace selector."},
                "session_id": {"type": "string", "description": "Stormhelm session identifier."},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "query": str(arguments.get("query", "")).strip(),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if context.workspace_service is None:
            return ToolResult(success=False, summary="Workspace memory is unavailable.", error="workspace_service_unavailable")
        result = context.workspace_service.archive_workspace(
            session_id=arguments["session_id"],
            query=arguments["query"] or None,
        )
        return ToolResult(success=True, summary=result["summary"], data=result)


class WorkspaceRenameTool(BaseTool):
    name = "workspace_rename"
    display_name = "Workspace Rename"
    description = "Rename the active workspace."
    category = "workspace"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "new_name": {"type": "string", "description": "The new workspace name."},
                "session_id": {"type": "string", "description": "Stormhelm session identifier."},
            },
            "required": ["new_name"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        new_name = str(arguments.get("new_name", "")).strip()
        if not new_name:
            raise ValueError("workspace_rename requires a non-empty new_name.")
        return {
            "new_name": new_name,
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if context.workspace_service is None:
            return ToolResult(success=False, summary="Workspace memory is unavailable.", error="workspace_service_unavailable")
        result = context.workspace_service.rename_workspace(
            session_id=arguments["session_id"],
            new_name=arguments["new_name"],
        )
        return ToolResult(success=True, summary=result["summary"], data=result)


class WorkspaceTagTool(BaseTool):
    name = "workspace_tag"
    display_name = "Workspace Tag"
    description = "Attach tags to the active workspace."
    category = "workspace"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags to attach to the workspace.",
                },
                "session_id": {"type": "string", "description": "Stormhelm session identifier."},
            },
            "required": ["tags"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        tags = arguments.get("tags")
        if not isinstance(tags, list):
            raise ValueError("workspace_tag requires a tags array.")
        cleaned = [str(tag).strip() for tag in tags if str(tag).strip()]
        if not cleaned:
            raise ValueError("workspace_tag requires at least one tag.")
        return {
            "tags": cleaned,
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if context.workspace_service is None:
            return ToolResult(success=False, summary="Workspace memory is unavailable.", error="workspace_service_unavailable")
        result = context.workspace_service.tag_workspace(
            session_id=arguments["session_id"],
            tags=arguments["tags"],
        )
        return ToolResult(success=True, summary=result["summary"], data=result)


class WorkspaceListTool(BaseTool):
    name = "workspace_list"
    display_name = "Workspace List"
    description = "List recent or archived workspace bearings."
    category = "workspace"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional search phrase."},
                "archived_only": {"type": "boolean", "description": "Whether to show archived workspaces only."},
                "include_archived": {"type": "boolean", "description": "Whether to include archived workspaces."},
                "session_id": {"type": "string", "description": "Stormhelm session identifier."},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "query": str(arguments.get("query", "")).strip(),
            "archived_only": bool(arguments.get("archived_only", False)),
            "include_archived": bool(arguments.get("include_archived", False)),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if context.workspace_service is None:
            return ToolResult(success=False, summary="Workspace memory is unavailable.", error="workspace_service_unavailable")
        result = context.workspace_service.list_workspaces(
            session_id=arguments["session_id"],
            query=arguments["query"],
            archived_only=arguments["archived_only"],
            include_archived=arguments["include_archived"],
        )
        return ToolResult(success=True, summary=result["summary"], data=result)


class WorkspaceWhereLeftOffTool(BaseTool):
    name = "workspace_where_left_off"
    display_name = "Workspace Where Left Off"
    description = "Report what the active workspace was doing and where work paused."
    category = "workspace"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Stormhelm session identifier."},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"session_id": str(arguments.get("session_id", "default")).strip() or "default"}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if context.task_service is not None:
            task_result = context.task_service.where_we_left_off(session_id=arguments["session_id"])
            if isinstance(task_result, dict):
                return ToolResult(success=True, summary=task_result["summary"], data=task_result)
        if context.workspace_service is None:
            return ToolResult(success=False, summary="Workspace memory is unavailable.", error="workspace_service_unavailable")
        result = context.workspace_service.where_we_left_off(session_id=arguments["session_id"])
        return ToolResult(success=True, summary=result["summary"], data=result)


class WorkspaceNextStepsTool(BaseTool):
    name = "workspace_next_steps"
    display_name = "Workspace Next Steps"
    description = "Report the pending next steps for the active workspace."
    category = "workspace"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Stormhelm session identifier."},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"session_id": str(arguments.get("session_id", "default")).strip() or "default"}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if context.task_service is not None:
            task_result = context.task_service.next_steps(session_id=arguments["session_id"])
            if isinstance(task_result, dict):
                return ToolResult(success=True, summary=task_result["summary"], data=task_result)
        if context.workspace_service is None:
            return ToolResult(success=False, summary="Workspace memory is unavailable.", error="workspace_service_unavailable")
        result = context.workspace_service.next_steps(session_id=arguments["session_id"])
        return ToolResult(success=True, summary=result["summary"], data=result)
