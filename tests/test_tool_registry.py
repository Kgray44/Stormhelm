from __future__ import annotations

import asyncio

from stormhelm.core.events import EventBuffer
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import NotesRepository, PreferencesRepository
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.shared.paths import ensure_runtime_directories


def test_tool_registry_executes_echo_tool(temp_config) -> None:
    ensure_runtime_directories(
        [
            temp_config.storage.data_dir,
            temp_config.storage.logs_dir,
            temp_config.storage.database_path.parent,
        ]
    )
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()

    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)
    context = ToolContext(
        job_id="test-job",
        config=temp_config,
        events=EventBuffer(),
        notes=NotesRepository(database),
        preferences=PreferencesRepository(database),
        safety_policy=SafetyPolicy(temp_config),
    )

    result = asyncio.run(executor.execute("echo", {"text": "hello"}, context))

    assert any(tool["name"] == "clock" for tool in registry.metadata())
    assert result.success is True
    assert result.data["text"] == "hello"

