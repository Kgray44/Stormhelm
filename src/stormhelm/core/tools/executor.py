from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.shared.result import ExecutionMode
from stormhelm.shared.result import ToolResult


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, *, max_sync_workers: int = 8) -> None:
        self.registry = registry
        self._sync_executor = ThreadPoolExecutor(
            max_workers=max_sync_workers,
            thread_name_prefix="stormhelm-tool",
        )

    async def execute(self, tool_name: str, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        try:
            tool = self.registry.get(tool_name)
            decision = context.safety_policy.authorize_tool(tool.name, tool.classification)
            if not decision.allowed:
                return ToolResult(
                    success=False,
                    summary=f"{tool.display_name} blocked by safety policy.",
                    data={"decision": decision.to_dict()},
                    error=decision.reason,
                )

            validated_arguments = tool.validate(dict(arguments))
            context.events.publish(
                level="INFO",
                source="tool_executor",
                message=f"Executing tool '{tool.name}'.",
                payload={"job_id": context.job_id, "execution_mode": tool.execution_mode.value},
            )

            if tool.execution_mode == ExecutionMode.ASYNC:
                return await tool.execute_async(context, validated_arguments)

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self._sync_executor,
                partial(tool.execute_sync, context, validated_arguments),
            )
        except Exception as error:
            return ToolResult(
                success=False,
                summary=f"Tool '{tool_name}' failed before completion.",
                error=str(error),
                data={"tool_name": tool_name},
            )

    def shutdown(self) -> None:
        self._sync_executor.shutdown(wait=False, cancel_futures=True)
