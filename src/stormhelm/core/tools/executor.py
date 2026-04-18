from __future__ import annotations

from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.shared.result import ToolResult


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(self, tool_name: str, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        tool = self.registry.get(tool_name)
        decision = context.safety_policy.authorize_tool(tool.name, tool.classification)
        if not decision.allowed:
            return ToolResult(
                success=False,
                summary=f"{tool.display_name} blocked by safety policy.",
                data={"decision": decision.to_dict()},
                error=decision.reason,
            )

        context.events.publish(
            level="INFO",
            source="tool_executor",
            message=f"Executing tool '{tool.name}'.",
            payload={"job_id": context.job_id},
        )
        return await tool.execute(context, arguments)

