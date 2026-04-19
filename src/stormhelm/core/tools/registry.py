from __future__ import annotations

from stormhelm.core.tools.base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> BaseTool:
        try:
            return self._tools[tool_name]
        except KeyError as error:
            raise KeyError(f"Unknown tool: {tool_name}") from error

    def metadata(self) -> list[dict[str, object]]:
        return [tool.metadata() for _, tool in sorted(self._tools.items(), key=lambda item: item[0])]

    def all_tools(self) -> list[BaseTool]:
        return [tool for _, tool in sorted(self._tools.items(), key=lambda item: item[0])]
