from __future__ import annotations

import os
import platform
from typing import Any

from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import ToolResult


class SystemInfoTool(BaseTool):
    name = "system_info"
    display_name = "System Info"
    description = "Return safe local platform information."

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        data = {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "cpu_count": os.cpu_count(),
        }
        return ToolResult(success=True, summary=f"Running on {data['platform']}.", data=data)

