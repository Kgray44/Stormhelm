from __future__ import annotations

from typing import Any

from stormhelm.core.environment.service import EnvironmentIntelligenceService
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import SafetyClassification, ToolResult


def _environment_service(context: ToolContext) -> EnvironmentIntelligenceService:
    session_state = (
        context.workspace_service.session_state
        if context.workspace_service is not None and hasattr(context.workspace_service, "session_state")
        else ConversationStateStore(context.preferences)
    )
    return EnvironmentIntelligenceService(
        config=context.config,
        session_state=session_state,
        workspace_service=context.workspace_service,
        system_probe=context.system_probe,
        events=context.events,
    )


class BrowserContextTool(BaseTool):
    name = "browser_context"
    display_name = "Browser Context"
    description = "Search the current browser context, reuse an existing page, summarize it, or link it into the active workspace."
    category = "browser"
    classification = SafetyClassification.ACTION

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["find", "recent_page", "summarize", "add_to_workspace", "collect_references"],
                },
                "query": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "operation": str(arguments.get("operation", "")).strip().lower(),
            "query": str(arguments.get("query", "")).strip(),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        result = _environment_service(context).handle_browser_request(
            operation=arguments["operation"],
            query=arguments["query"],
            session_id=arguments["session_id"],
        )
        return ToolResult(
            success=not bool(result.get("error")),
            summary=str(result.get("summary", "")).strip() or "Browser context handled.",
            data=result,
            error=str(result.get("error") or "") or None,
        )


class ActivitySummaryTool(BaseTool):
    name = "activity_summary"
    display_name = "Activity Summary"
    description = "Summarize the recent high-signal activity, completions, failures, and warning-level changes without dumping raw logs."
    category = "operations"
    classification = SafetyClassification.READ_ONLY

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "session_id": {"type": "string"},
                "lookback_minutes": {"type": "integer", "minimum": 1, "maximum": 240},
            },
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        lookback = arguments.get("lookback_minutes")
        return {
            "query": str(arguments.get("query", "")).strip(),
            "session_id": str(arguments.get("session_id", "default")).strip() or "default",
            "lookback_minutes": int(lookback) if isinstance(lookback, (int, float)) else 15,
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        result = _environment_service(context).summarize_recent_activity(
            session_id=arguments["session_id"],
            query=arguments["query"],
            lookback_minutes=arguments["lookback_minutes"],
        )
        return ToolResult(
            success=True,
            summary=str(result.get("summary", "")).strip() or "Recent activity summarized.",
            data=result,
        )
