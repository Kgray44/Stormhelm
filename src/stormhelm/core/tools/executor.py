from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import build_execution_report
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
            validated_arguments = tool.validate(dict(arguments))
            contract_assessment = tool.adapter_route_assessment(validated_arguments)
            if contract_assessment.contract_required and not contract_assessment.healthy:
                return ToolResult(
                    success=False,
                    summary=f"{tool.display_name} is unavailable because this route is not valid contract-backed adapter work.",
                    error="Adapter contract enforcement blocked this route.",
                    data={"adapter_contract_status": contract_assessment.to_dict()},
                )
            contract = contract_assessment.selected_contract
            decision = context.safety_policy.authorize_tool(
                tool.name,
                tool.classification,
                context=context,
                arguments=validated_arguments,
                adapter_contract=contract,
            )
            if not decision.allowed:
                return ToolResult(
                    success=False,
                    summary=f"{tool.display_name} blocked by safety policy.",
                    data={"decision": decision.to_dict()},
                    error=decision.operator_message or decision.reason,
                )

            context.events.publish(
                event_family="tool",
                event_type="tool.execution_started",
                severity="info",
                subsystem="tool_executor",
                subject=context.job_id,
                visibility_scope="watch_surface",
                retention_class="operator_relevant",
                provenance={"channel": "tool_executor", "kind": "direct_system_fact"},
                message=f"Executing tool '{tool.name}'.",
                payload={
                    "job_id": context.job_id,
                    "tool_name": tool.name,
                    "execution_mode": tool.execution_mode.value,
                    "adapter_id": getattr(contract, "adapter_id", None),
                },
            )

            if tool.execution_mode == ExecutionMode.ASYNC:
                result = await tool.execute_async(context, validated_arguments)
            else:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    self._sync_executor,
                    partial(tool.execute_sync, context, validated_arguments),
                )

            if contract is not None and not result.adapter_contract:
                result.adapter_contract = contract.to_dict()
            if contract is not None and not result.adapter_execution:
                fallback_execution = build_execution_report(
                    contract,
                    success=result.success,
                    observed_outcome=ClaimOutcome.NONE if not result.success else ClaimOutcome.INITIATED,
                    failure_kind=result.error if not result.success else None,
                )
                result.adapter_execution = fallback_execution.to_dict()
            return result
        except Exception as error:
            return ToolResult(
                success=False,
                summary=f"Tool '{tool_name}' failed before completion.",
                error=str(error),
                data={"tool_name": tool_name},
            )

    def shutdown(self) -> None:
        self._sync_executor.shutdown(wait=False, cancel_futures=True)
