from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


class ClockTool(BaseTool):
    name = "clock"
    display_name = "Clock"
    description = "Return local and UTC time information."

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        local_now = datetime.now().astimezone()
        utc_now = datetime.now(timezone.utc)
        return ToolResult(
            success=True,
            summary=f"Local time is {local_now.strftime('%Y-%m-%d %H:%M:%S')}.",
            data={
                "local_time": local_now.isoformat(),
                "utc_time": utc_now.isoformat(),
                "timezone": str(local_now.tzinfo),
            },
        )

