from __future__ import annotations

from stormhelm.core.tools.base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> BaseTool:
        try:
            return self._tools[tool_name]
        except KeyError as error:
            raise KeyError(f"Unknown tool: {tool_name}") from error

    def metadata(self) -> list[dict[str, object]]:
        return [tool.metadata() for tool in self._tools.values()]

