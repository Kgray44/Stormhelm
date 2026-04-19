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
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.providers.openai_responses import OpenAIResponsesProvider
from stormhelm.core.runtime_state import RuntimeBootstrapResult, clear_runtime_state, initialize_runtime_state
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.system.probe import SystemProbe
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository
from stormhelm.core.workspace.service import WorkspaceService
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
    runtime_bootstrap: RuntimeBootstrapResult | None = None

    async def start(self) -> None:
        ensure_runtime_directories(
            [
                self.config.storage.data_dir,
                self.config.storage.logs_dir,
                self.config.storage.state_dir,
                self.config.storage.database_path.parent,
            ]
        )
        logger = configure_logging(self.config)
        logger.info("Starting Stormhelm core.")
        self.runtime_bootstrap = initialize_runtime_state(self.config)
        self.database.initialize()
        self.conversations.ensure_session()
        await self.jobs.start()
        self.events.publish(
            level="INFO",
            source="core",
            message="Stormhelm core started.",
            payload={
                "data_dir": str(self.config.storage.data_dir),
                "version": self.config.version,
                "mode": self.config.runtime.mode,
                "first_run": bool(self.runtime_bootstrap and self.runtime_bootstrap.first_run),
            },
        )
        if self.runtime_bootstrap.first_run:
            self.events.publish(
                level="INFO",
                source="core",
                message="Initialized Stormhelm runtime directories for first run.",
                payload=self.runtime_bootstrap.first_run_record,
            )

    async def stop(self) -> None:
        self.events.publish(level="INFO", source="core", message="Stormhelm core shutting down.")
        await self.jobs.stop()
        self.tool_executor.shutdown()
        clear_runtime_state(self.config)

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "app_name": self.config.app_name,
            "version": self.config.version,
            "version_label": self.config.version_label,
            "protocol_version": self.config.protocol_version,
            "release_channel": self.config.release_channel,
            "environment": self.config.environment,
            "debug": self.config.debug,
            "api_base_url": self.config.api_base_url,
            "data_dir": str(self.config.storage.data_dir),
            "database_path": str(self.database.effective_path),
            "logs_dir": str(self.config.storage.logs_dir),
            "state_dir": str(self.config.storage.state_dir),
            "runtime_mode": self.config.runtime.mode,
            "install_root": str(self.config.runtime.install_root),
            "resource_root": str(self.config.runtime.resource_root),
            "max_workers": self.config.concurrency.max_workers,
            "tool_count": len(self.tool_registry.metadata()),
            "recent_jobs": len(self.jobs.list_jobs(limit=25)),
            "first_run": bool(self.runtime_bootstrap and self.runtime_bootstrap.first_run),
        }


def build_container(config: AppConfig | None = None) -> CoreContainer:
    app_config = config or load_config()
    database = SQLiteDatabase(app_config.storage.database_path)
    events = EventBuffer()
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    tool_runs = ToolRunRepository(database)
    session_state = ConversationStateStore(preferences)
    persona = PersonaContract(app_config)
    planner = DeterministicPlanner()
    safety = SafetyPolicy(app_config)
    system_probe = SystemProbe(app_config)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry, max_sync_workers=app_config.concurrency.max_workers)
    provider = OpenAIResponsesProvider(app_config.openai) if app_config.openai.enabled else None
    workspace_repository = WorkspaceRepository(database)
    workspace_service = WorkspaceService(
        config=app_config,
        repository=workspace_repository,
        notes=notes,
        conversations=conversations,
        preferences=preferences,
        session_state=session_state,
        indexer=WorkspaceIndexer(app_config),
        events=events,
        persona=persona,
    )
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
            system_probe=system_probe,
            workspace_service=workspace_service,
        ),
        tool_runs=tool_runs,
        events=events,
    )
    assistant = AssistantOrchestrator(
        config=app_config,
        conversations=conversations,
        jobs=jobs,
        router=IntentRouter(),
        events=events,
        tool_registry=registry,
        session_state=session_state,
        planner=planner,
        persona=persona,
        workspace_service=workspace_service,
        provider=provider,
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
