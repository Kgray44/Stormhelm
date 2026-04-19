from __future__ import annotations

import asyncio

import pytest

from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.jobs.models import JobStatus
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import NotesRepository, PreferencesRepository, ToolRunRepository
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.shared.paths import ensure_runtime_directories
from stormhelm.shared.result import ExecutionMode, ToolResult


class SlowEchoTool(BaseTool):
    name = "echo"
    display_name = "Slow Echo"
    description = "Async test tool."
    execution_mode = ExecutionMode.ASYNC

    async def execute_async(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        await asyncio.sleep(float(arguments.get("delay", 0.05)))
        return ToolResult(success=True, summary="Completed slow echo.", data={"delay": arguments.get("delay", 0.05)})


def test_job_manager_completes_job(temp_config) -> None:
    async def scenario() -> None:
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
        registry.register(SlowEchoTool())
        executor = ToolExecutor(registry)
        events = EventBuffer()
        safety = SafetyPolicy(temp_config)
        tool_runs = ToolRunRepository(database)
        notes = NotesRepository(database)
        preferences = PreferencesRepository(database)

        manager = JobManager(
            config=temp_config,
            executor=executor,
            context_factory=lambda job_id: ToolContext(
                job_id=job_id,
                config=temp_config,
                events=events,
                notes=notes,
                preferences=preferences,
                safety_policy=safety,
            ),
            tool_runs=tool_runs,
            events=events,
        )

        await manager.start()
        job = await manager.submit_and_wait("echo", {"delay": 0.01})
        await manager.stop()

        assert job.status == JobStatus.COMPLETED

    asyncio.run(scenario())


def test_job_manager_cancels_running_job(temp_config) -> None:
    async def scenario() -> None:
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
        registry.register(SlowEchoTool())
        executor = ToolExecutor(registry)
        events = EventBuffer()
        safety = SafetyPolicy(temp_config)
        tool_runs = ToolRunRepository(database)
        notes = NotesRepository(database)
        preferences = PreferencesRepository(database)

        manager = JobManager(
            config=temp_config,
            executor=executor,
            context_factory=lambda job_id: ToolContext(
                job_id=job_id,
                config=temp_config,
                events=events,
                notes=notes,
                preferences=preferences,
                safety_policy=safety,
            ),
            tool_runs=tool_runs,
            events=events,
        )

        await manager.start()
        job = await manager.submit("echo", {"delay": 0.5})
        await asyncio.sleep(0.05)
        assert manager.cancel(job.job_id) is True
        finished = await manager.wait(job.job_id)
        await manager.stop()

        assert finished.status == JobStatus.CANCELLED

    asyncio.run(scenario())


def test_job_manager_rejects_full_queue(temp_config) -> None:
    async def scenario() -> None:
        temp_config.concurrency.queue_size = 1
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
        registry.register(SlowEchoTool())
        executor = ToolExecutor(registry)
        events = EventBuffer()
        safety = SafetyPolicy(temp_config)
        tool_runs = ToolRunRepository(database)
        notes = NotesRepository(database)
        preferences = PreferencesRepository(database)

        manager = JobManager(
            config=temp_config,
            executor=executor,
            context_factory=lambda job_id: ToolContext(
                job_id=job_id,
                config=temp_config,
                events=events,
                notes=notes,
                preferences=preferences,
                safety_policy=safety,
            ),
            tool_runs=tool_runs,
            events=events,
        )

        first_job = await manager.submit("echo", {"delay": 0.25})
        with pytest.raises(RuntimeError, match="job queue is full"):
            await manager.submit("echo", {"delay": 0.25})
        assert first_job.status == JobStatus.QUEUED

    asyncio.run(scenario())
