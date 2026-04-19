from __future__ import annotations

import asyncio

from stormhelm.core.events import EventBuffer
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry


class DummyNotesRepository:
    def create_note(self, title: str, content: str):  # pragma: no cover - not used in this test
        raise NotImplementedError


class DummyPreferencesRepository:
    def set_preference(self, key: str, value: object) -> None:  # pragma: no cover - not used in this test
        return None


def test_tool_registry_executes_echo_tool(temp_config) -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=DummyNotesRepository(),
        preferences=DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
    )

    result = asyncio.run(executor.execute("echo", {"text": "hello"}, context))

    assert any(tool["name"] == "clock" for tool in registry.metadata())
    assert any(tool["name"] == "deck_open_url" and tool["category"] == "browser" for tool in registry.metadata())
    assert any(tool["name"] == "workspace_restore" and tool["category"] == "workspace" for tool in registry.metadata())
    assert any(tool["name"] == "machine_status" and tool["category"] == "system" for tool in registry.metadata())
    assert result.success is True
    assert result.data["text"] == "hello"
