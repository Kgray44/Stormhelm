from __future__ import annotations

from typing import Any

from stormhelm.core.subsystem_continuations import SubsystemContinuationRequest
from stormhelm.shared.result import ExecutionMode
from stormhelm.shared.result import SafetyClassification
from stormhelm.shared.result import ToolResult

from ..base import BaseTool
from ..base import ToolContext


class SubsystemContinuationTool(BaseTool):
    name = "subsystem_continuation"
    display_name = "Subsystem Continuation"
    description = "Runs an approved subsystem continuation request through the worker layer."
    category = "internal"
    classification = SafetyClassification.READ_ONLY
    execution_mode = ExecutionMode.ASYNC
    timeout_seconds = 30.0

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "continuation_request": {"type": "object"},
            },
            "required": ["continuation_request"],
            "additionalProperties": True,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = arguments.get("continuation_request")
        if not isinstance(payload, dict):
            raise ValueError("subsystem_continuation requires continuation_request.")
        return {"continuation_request": dict(payload)}

    async def execute_async(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        runner = context.continuation_runner
        request = SubsystemContinuationRequest.from_dict(dict(arguments["continuation_request"]))
        if runner is None:
            return ToolResult(
                success=False,
                summary="Continuation runner is unavailable.",
                data={
                    "subsystem_continuation_result": {
                        "continuation_id": request.continuation_id,
                        "route_family": request.route_family,
                        "subsystem": request.subsystem,
                        "operation_kind": request.operation_kind,
                        "status": "blocked",
                        "result_state": "blocked",
                        "verification_state": request.verification_state,
                        "completion_claimed": False,
                        "verification_claimed": False,
                        "error_code": "continuation_runner_unavailable",
                    }
                },
                error="continuation_runner_unavailable",
            )
        result = await runner.run(request, context)
        payload = result.to_dict()
        success = str(payload.get("status") or "") not in {"failed", "blocked", "cancelled"}
        return ToolResult(
            success=success,
            summary=str(payload.get("summary") or "Subsystem continuation updated."),
            data={"subsystem_continuation_result": payload},
            error=(str(payload.get("error_message") or "") or None) if not success else None,
        )
