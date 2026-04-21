from __future__ import annotations

from pathlib import Path
from typing import Any

from stormhelm.core.context.service import ActiveContextService
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


class ContextActionTool(BaseTool):
    name = "context_action"
    display_name = "Context Action"
    description = "Use the current active selection, clipboard, or recent work context as a deterministic source for opening, task extraction, and context inspection."
    category = "context"

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["inspect", "open", "extract_tasks", "restore_context"]},
                "source": {"type": "string", "enum": ["selection", "clipboard"]},
                "session_id": {"type": "string"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "operation": str(arguments.get("operation", "")).strip().lower(),
            "source": str(arguments.get("source", "")).strip().lower() or None,
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        session_state = ConversationStateStore(context.preferences)
        active_context = ActiveContextService(session_state).snapshot(arguments["session_id"])
        operation = arguments["operation"]
        source_name = arguments.get("source")

        if operation == "inspect":
            summary = self._context_summary(active_context)
            return ToolResult(
                success=True,
                summary=summary,
                data={"context": active_context},
            )

        if operation == "restore_context":
            return self._restore_context(active_context)

        descriptor = self._resolve_descriptor(active_context, source_name)
        if descriptor is None:
            return ToolResult(
                success=False,
                summary="No usable context source was available.",
                data={"reason": "missing_context_source", "requested_source": source_name},
            )

        if operation == "open":
            return self._open_descriptor(descriptor)
        if operation == "extract_tasks":
            return self._extract_tasks(descriptor)

        return ToolResult(
            success=False,
            summary="The requested context operation is not supported.",
            data={"reason": "unsupported_operation", "operation": operation},
        )

    def _resolve_descriptor(self, active_context: dict[str, Any], source_name: str | None) -> dict[str, Any] | None:
        for key in ([source_name] if source_name else []) + ["selection", "clipboard"]:
            if not key:
                continue
            descriptor = active_context.get(key)
            if isinstance(descriptor, dict) and descriptor.get("value") not in (None, ""):
                return descriptor
        return None

    def _open_descriptor(self, descriptor: dict[str, Any]) -> ToolResult:
        kind = str(descriptor.get("kind") or "text").strip().lower()
        value = descriptor.get("value")
        if kind == "url" and isinstance(value, str):
            return ToolResult(
                success=True,
                summary="Opened the copied link.",
                data={
                    "action": {
                        "type": "open_external",
                        "kind": "url",
                        "url": value,
                        "title": value,
                    }
                },
            )
        if kind in {"file_path", "paths"}:
            if isinstance(value, list) and value:
                candidate = str(value[0]).strip()
            else:
                candidate = str(value or "").strip()
            if candidate:
                return ToolResult(
                    success=True,
                    summary=f"Opened {Path(candidate).name or candidate}.",
                    data={
                        "action": {
                            "type": "open_external",
                            "kind": "file",
                            "path": candidate,
                            "title": Path(candidate).name or candidate,
                        }
                    },
                )
        return ToolResult(
            success=False,
            summary="The current context source cannot be opened directly.",
            data={"reason": "unsupported_open_source", "kind": kind},
        )

    def _extract_tasks(self, descriptor: dict[str, Any]) -> ToolResult:
        raw_value = descriptor.get("value")
        text = str(raw_value or "").strip()
        if not text:
            return ToolResult(
                success=False,
                summary="The current context source does not contain usable text.",
                data={"reason": "missing_text"},
            )
        tasks = []
        for line in text.splitlines():
            cleaned = line.strip(" -*\t")
            if cleaned:
                tasks.append({"title": cleaned})
        if not tasks:
            tasks = [{"title": text}]
        return ToolResult(
            success=True,
            summary="Created tasks from the current context.",
            data={"tasks": tasks, "source": descriptor.get("kind", "text")},
        )

    def _restore_context(self, active_context: dict[str, Any]) -> ToolResult:
        workspace = active_context.get("workspace") if isinstance(active_context.get("workspace"), dict) else {}
        recent_entities = active_context.get("recent_entities") if isinstance(active_context.get("recent_entities"), list) else []
        if not workspace and not recent_entities:
            return ToolResult(
                success=False,
                summary="I don't have enough recent context for that.",
                data={"reason": "insufficient_context"},
            )
        return ToolResult(
            success=True,
            summary=self._context_summary(active_context),
            data={"context": active_context},
        )

    def _context_summary(self, active_context: dict[str, Any]) -> str:
        workspace = active_context.get("workspace") if isinstance(active_context.get("workspace"), dict) else {}
        active_goal = str(active_context.get("active_goal") or "").strip()
        workspace_name = str(workspace.get("name") or workspace.get("topic") or "").strip()
        if active_goal and workspace_name:
            return f"Current context: {active_goal} in {workspace_name}."
        if active_goal:
            return f"Current context: {active_goal}."
        if workspace_name:
            return f"Current context: {workspace_name}."
        return "Current context is available."
