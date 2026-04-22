from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
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
from stormhelm.core.network import CloudflareQualityProvider, NetworkMonitor
from stormhelm.core.operations.service import OperationalAwarenessService
from stormhelm.core.calculations import CalculationsSubsystem
from stormhelm.core.calculations import build_calculations_subsystem
from stormhelm.core.discord_relay import DiscordRelaySubsystem
from stormhelm.core.discord_relay import build_discord_relay_subsystem
from stormhelm.core.orchestrator.assistant import AssistantOrchestrator
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.providers.openai_responses import OpenAIResponsesProvider
from stormhelm.core.runtime_state import RuntimeBootstrapResult, clear_runtime_state, initialize_runtime_state
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.screen_awareness import ScreenAwarenessSubsystem
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
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
    system_probe: SystemProbe
    conversations: ConversationRepository
    notes: NotesRepository
    preferences: PreferencesRepository
    tool_runs: ToolRunRepository
    safety: SafetyPolicy
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    jobs: JobManager
    assistant: AssistantOrchestrator
    calculations: CalculationsSubsystem
    screen_awareness: ScreenAwarenessSubsystem
    discord_relay: DiscordRelaySubsystem
    network_monitor: NetworkMonitor | None = None
    runtime_bootstrap: RuntimeBootstrapResult | None = None
    operational_awareness: OperationalAwarenessService = field(default_factory=OperationalAwarenessService)
    _system_state_cache: dict[str, Any] | None = None
    _system_state_cached_at: float = 0.0

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
        if self.network_monitor is not None:
            self.network_monitor.start()
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
        if self.network_monitor is not None:
            self.network_monitor.stop()
        await self.jobs.stop()
        self.tool_executor.shutdown()
        clear_runtime_state(self.config)

    def status_snapshot(self) -> dict[str, Any]:
        jobs = self.jobs.list_jobs(limit=64)
        system_state = self._system_state_snapshot()
        recent_events = self.events.recent(limit=32)
        watch_state = self._watch_state_snapshot(jobs)
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
            "recent_jobs": len(jobs[:25]),
            "system_state": system_state,
            "systems_interpretation": self.operational_awareness.build_systems_interpretation(system_state).to_dict(),
            "signal_state": {
                "signals": [
                    signal.to_dict()
                    for signal in self.operational_awareness.build_signals(
                        events=recent_events,
                        jobs=jobs,
                        system_state=system_state,
                    )
                ]
            },
            "calculations": self.calculations.status_snapshot(),
            "screen_awareness": self.screen_awareness.status_snapshot(),
            "discord_relay": self.discord_relay.status_snapshot(),
            "provider_state": self._provider_state_snapshot(),
            "tool_state": self._tool_state_snapshot(),
            "watch_state": watch_state,
            "first_run": bool(self.runtime_bootstrap and self.runtime_bootstrap.first_run),
        }

    def _system_state_snapshot(self) -> dict[str, Any]:
        now = monotonic()
        if self._system_state_cache is not None and (now - self._system_state_cached_at) < 15.0:
            return dict(self._system_state_cache)

        snapshot = {
            "machine": self.system_probe.machine_status(),
            "power": self.system_probe.power_status(),
            "resources": self.system_probe.resource_status(),
            "hardware": self.system_probe.hardware_telemetry_snapshot(sampling_tier="active"),
            "storage": self.system_probe.storage_status(),
            "network": self.system_probe.network_status(),
            "location": self.system_probe.resolve_location(),
        }
        completed_at = monotonic()
        self._system_state_cache = snapshot
        self._system_state_cached_at = completed_at
        return snapshot

    def _provider_state_snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.config.openai.enabled,
            "configured": bool(self.config.openai.api_key),
            "planner_model": self.config.openai.planner_model,
            "reasoning_model": self.config.openai.reasoning_model,
            "timeout_seconds": self.config.openai.timeout_seconds,
            "max_tool_rounds": self.config.openai.max_tool_rounds,
        }

    def _tool_state_snapshot(self) -> dict[str, Any]:
        enabled_tools = [
            metadata["name"]
            for metadata in self.tool_registry.metadata()
            if self.config.tools.enabled.is_enabled(str(metadata.get("name", "")))
        ]
        return {
            "enabled_count": len(enabled_tools),
            "enabled_tools": enabled_tools,
        }

    def _watch_state_snapshot(self, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        return self.operational_awareness.build_watch_snapshot(
            jobs=jobs,
            worker_capacity=self.config.concurrency.max_workers,
            default_timeout_seconds=self.config.concurrency.default_job_timeout_seconds,
        ).to_dict()


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
    system_probe = SystemProbe(app_config, preferences=preferences)
    safety = SafetyPolicy(app_config)
    network_monitor = NetworkMonitor(
        probe=system_probe,
        events=events,
        cloudflare_provider=CloudflareQualityProvider(enabled=True, timeout_seconds=2.5),
        history_path=app_config.storage.state_dir / "network-history.json",
    )
    system_probe.attach_network_monitor(network_monitor)
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry, max_sync_workers=app_config.concurrency.max_workers)
    provider = OpenAIResponsesProvider(app_config.openai) if app_config.openai.enabled else None
    calculations = build_calculations_subsystem(app_config.calculations)
    screen_awareness = build_screen_awareness_subsystem(
        app_config.screen_awareness,
        system_probe=system_probe,
        provider=provider,
        calculations=calculations,
    )
    discord_relay = build_discord_relay_subsystem(
        app_config.discord_relay,
        session_state=session_state,
        system_probe=system_probe,
        observation_source=screen_awareness.native_observer,
    )
    planner = DeterministicPlanner(
        calculations_config=app_config.calculations,
        calculations_seam=calculations.planner_seam,
        screen_awareness_config=app_config.screen_awareness,
        screen_awareness_seam=screen_awareness.planner_seam,
        discord_relay_config=app_config.discord_relay,
    )
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
        calculations=calculations,
        screen_awareness=screen_awareness,
        discord_relay=discord_relay,
    )
    return CoreContainer(
        config=app_config,
        events=events,
        database=database,
        system_probe=system_probe,
        conversations=conversations,
        notes=notes,
        preferences=preferences,
        tool_runs=tool_runs,
        safety=safety,
        tool_registry=registry,
        tool_executor=executor,
        jobs=jobs,
        assistant=assistant,
        calculations=calculations,
        screen_awareness=screen_awareness,
        discord_relay=discord_relay,
        network_monitor=network_monitor,
    )
