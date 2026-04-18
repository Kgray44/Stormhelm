from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.logging import configure_logging
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import (
    ConversationRepository,
    NotesRepository,
    PreferencesRepository,
    ToolRunRepository,
)
from stormhelm.core.orchestrator.assistant import AssistantOrchestrator
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.shared.paths import ensure_runtime_directories


@dataclass(slots=True)
class CoreContainer:
    config: AppConfig
    events: EventBuffer
    database: SQLiteDatabase
    conversations: ConversationRepository
    notes: NotesRepository
    preferences: PreferencesRepository
    tool_runs: ToolRunRepository
    safety: SafetyPolicy
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    jobs: JobManager
    assistant: AssistantOrchestrator

    async def start(self) -> None:
        ensure_runtime_directories(
            [
                self.config.storage.data_dir,
                self.config.storage.logs_dir,
                self.config.storage.database_path.parent,
            ]
        )
        configure_logging(self.config)
        self.database.initialize()
        self.conversations.ensure_session()
        await self.jobs.start()
        self.events.publish(
            level="INFO",
            source="core",
            message="Stormhelm core started.",
            payload={"data_dir": str(self.config.storage.data_dir)},
        )

    async def stop(self) -> None:
        self.events.publish(level="INFO", source="core", message="Stormhelm core shutting down.")
        await self.jobs.stop()

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "app_name": self.config.app_name,
            "environment": self.config.environment,
            "debug": self.config.debug,
            "api_base_url": self.config.api_base_url,
            "data_dir": str(self.config.storage.data_dir),
            "database_path": str(self.config.storage.database_path),
            "max_workers": self.config.concurrency.max_workers,
            "tool_count": len(self.tool_registry.metadata()),
            "recent_jobs": len(self.jobs.list_jobs(limit=25)),
        }


def build_container(config: AppConfig | None = None) -> CoreContainer:
    app_config = config or load_config()
    database = SQLiteDatabase(app_config.storage.database_path)
    events = EventBuffer()
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    tool_runs = ToolRunRepository(database)
    safety = SafetyPolicy(app_config)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)
    jobs = JobManager(
        config=app_config,
        executor=executor,
        context_factory=lambda job_id: ToolContext(
            job_id=job_id,
            config=app_config,
            events=events,
            notes=notes,
            preferences=preferences,
            safety_policy=safety,
        ),
        tool_runs=tool_runs,
        events=events,
    )
    assistant = AssistantOrchestrator(
        conversations=conversations,
        jobs=jobs,
        router=IntentRouter(),
        events=events,
    )
    return CoreContainer(
        config=app_config,
        events=events,
        database=database,
        conversations=conversations,
        notes=notes,
        preferences=preferences,
        tool_runs=tool_runs,
        safety=safety,
        tool_registry=registry,
        tool_executor=executor,
        jobs=jobs,
        assistant=assistant,
    )

