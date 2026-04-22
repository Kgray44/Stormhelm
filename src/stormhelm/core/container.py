from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.core.adapters import default_adapter_contract_registry
from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.lifecycle import LifecycleController
from stormhelm.core.logging import configure_logging
from stormhelm.core.memory import SemanticMemoryRepository, SemanticMemoryService
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
from stormhelm.core.software_control import SoftwareControlSubsystem
from stormhelm.core.software_control import build_software_control_subsystem
from stormhelm.core.software_recovery import SoftwareRecoverySubsystem
from stormhelm.core.software_recovery import build_software_recovery_subsystem
from stormhelm.core.runtime_state import RuntimeBootstrapResult, clear_runtime_state, initialize_runtime_state
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.screen_awareness import ScreenAwarenessSubsystem
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.core.system.probe import SystemProbe
from stormhelm.core.tasks import DurableTaskService, TaskRepository
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.core.trust import TrustRepository, TrustService
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
    memory: SemanticMemoryService
    safety: SafetyPolicy
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    jobs: JobManager
    assistant: AssistantOrchestrator
    calculations: CalculationsSubsystem
    software_control: SoftwareControlSubsystem
    software_recovery: SoftwareRecoverySubsystem
    screen_awareness: ScreenAwarenessSubsystem
    discord_relay: DiscordRelaySubsystem
    task_service: DurableTaskService
    trust: TrustService
    lifecycle: LifecycleController
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
        lifecycle_bootstrap = self.lifecycle.bootstrap()
        self.runtime_bootstrap = initialize_runtime_state(
            self.config,
            install_mode=self.lifecycle.install_state.install_mode.value,
        )
        self.database.initialize()
        self.conversations.ensure_session()
        await self.jobs.start()
        if self.network_monitor is not None:
            self.network_monitor.start()
        self.events.publish(
            event_family="lifecycle",
            event_type="lifecycle.core.started",
            severity="info",
            subsystem="core",
            visibility_scope="systems_surface",
            retention_class="bootstrap_assist",
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
                event_family="lifecycle",
                event_type="lifecycle.runtime.initialized",
                severity="info",
                subsystem="core",
                visibility_scope="systems_surface",
                retention_class="bootstrap_assist",
                message="Initialized Stormhelm runtime directories for first run.",
                payload=self.runtime_bootstrap.first_run_record,
            )
        if lifecycle_bootstrap.lifecycle_hold_reason:
            self.events.publish(
                event_family="lifecycle",
                event_type="lifecycle.bootstrap.hold",
                severity="warning",
                subsystem="lifecycle",
                visibility_scope="operator_blocking",
                retention_class="bootstrap_assist",
                message=lifecycle_bootstrap.lifecycle_hold_reason,
                payload=lifecycle_bootstrap.to_dict(),
            )

    async def stop(self) -> None:
        self.events.publish(
            event_family="lifecycle",
            event_type="lifecycle.core.stopping",
            severity="info",
            subsystem="core",
            visibility_scope="systems_surface",
            retention_class="bootstrap_assist",
            message="Stormhelm core shutting down.",
        )
        if self.network_monitor is not None:
            self.network_monitor.stop()
        await self.jobs.stop()
        self.tool_executor.shutdown()
        self.lifecycle.shutdown()
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
            "software_control": self.software_control.status_snapshot(),
            "software_recovery": self.software_recovery.status_snapshot(),
            "screen_awareness": self.screen_awareness.status_snapshot(),
            "discord_relay": self.discord_relay.status_snapshot(),
            "trust": self.trust.status_snapshot(
                session_id="default",
                active_task_id=str(self.assistant.session_state.get_active_task_id("default") or ""),
            ),
            "provider_state": self._provider_state_snapshot(),
            "tool_state": self._tool_state_snapshot(),
            "watch_state": watch_state,
            "active_task": self.task_service.active_task_summary("default"),
            "memory": self.memory.status_snapshot(),
            "event_stream": self.events.state_snapshot(),
            "first_run": bool(self.runtime_bootstrap and self.runtime_bootstrap.first_run),
            "lifecycle": self.lifecycle.status_snapshot(),
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
        metadata_list = self.tool_registry.metadata()
        contract_registry_snapshot = default_adapter_contract_registry().snapshot()
        enabled_tools = [
            metadata["name"]
            for metadata in metadata_list
            if self.config.tools.enabled.is_enabled(str(metadata.get("name", "")))
        ]
        contract_bound_tools: dict[str, list[str]] = {}
        adapter_families: set[str] = set()
        adapter_ids: set[str] = set()
        for metadata in metadata_list:
            contracts = metadata.get("adapter_contracts")
            if not isinstance(contracts, list) or not contracts:
                continue
            adapter_ids_for_tool: list[str] = []
            for contract in contracts:
                if not isinstance(contract, dict):
                    continue
                adapter_id = str(contract.get("adapter_id") or "").strip()
                family = str(contract.get("family") or "").strip()
                if adapter_id:
                    adapter_ids_for_tool.append(adapter_id)
                    adapter_ids.add(adapter_id)
                if family:
                    adapter_families.add(family)
            if adapter_ids_for_tool:
                contract_bound_tools[str(metadata.get("name") or "")] = adapter_ids_for_tool
        return {
            "enabled_count": len(enabled_tools),
            "enabled_tools": enabled_tools,
            "adapter_contract_count": len(adapter_ids),
            "healthy_adapter_contract_count": int(contract_registry_snapshot.get("healthy_contract_count", len(adapter_ids))),
            "adapter_contract_validation_failures": int(contract_registry_snapshot.get("validation_failure_count", 0)),
            "adapter_families": sorted(adapter_families),
            "contract_bound_tools": contract_bound_tools,
            "adapter_contract_binding_modes": dict(contract_registry_snapshot.get("tool_binding_modes") or {}),
        }

    def _watch_state_snapshot(self, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        snapshot = self.operational_awareness.build_watch_snapshot(
            jobs=jobs,
            worker_capacity=self.config.concurrency.max_workers,
            default_timeout_seconds=self.config.concurrency.default_job_timeout_seconds,
        ).to_dict()
        task_watch = self.task_service.watch_tasks("default")
        if task_watch:
            snapshot["tasks"] = task_watch
        return snapshot


def build_container(config: AppConfig | None = None) -> CoreContainer:
    app_config = config or load_config()
    database = SQLiteDatabase(app_config.storage.database_path)
    database.initialize()
    events = EventBuffer(capacity=max(64, app_config.event_stream.retention_capacity))
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    tool_runs = ToolRunRepository(database)
    memory = SemanticMemoryService(SemanticMemoryRepository(database))
    session_state = ConversationStateStore(preferences, memory=memory)
    persona = PersonaContract(app_config)
    system_probe = SystemProbe(app_config, preferences=preferences)
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
    lifecycle = LifecycleController(app_config, events=events)
    provider = OpenAIResponsesProvider(app_config.openai) if app_config.openai.enabled else None
    calculations = build_calculations_subsystem(app_config.calculations)
    workspace_repository = WorkspaceRepository(database)
    task_service = DurableTaskService(
        repository=TaskRepository(database),
        session_state=session_state,
        events=events,
        memory=memory,
    )
    trust = TrustService(
        config=app_config.trust,
        repository=TrustRepository(database),
        events=events,
        session_state=session_state,
        task_service=task_service,
    )
    safety = SafetyPolicy(app_config, trust_service=trust)
    software_recovery = build_software_recovery_subsystem(
        app_config.software_recovery,
        openai_enabled=app_config.openai.enabled,
    )
    software_control = build_software_control_subsystem(
        app_config.software_control,
        recovery=software_recovery,
        safety=safety,
        system_probe=system_probe,
        trust_service=trust,
    )
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
        trust_service=trust,
    )
    planner = DeterministicPlanner(
        calculations_config=app_config.calculations,
        calculations_seam=calculations.planner_seam,
        software_control_config=app_config.software_control,
        software_control_seam=software_control.planner_seam,
        screen_awareness_config=app_config.screen_awareness,
        screen_awareness_seam=screen_awareness.planner_seam,
        discord_relay_config=app_config.discord_relay,
    )
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
        memory=memory,
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
            task_service=task_service,
            trust_service=trust,
        ),
        tool_runs=tool_runs,
        events=events,
        observer=task_service,
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
        task_service=task_service,
        provider=provider,
        calculations=calculations,
        software_control=software_control,
        software_recovery=software_recovery,
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
        memory=memory,
        safety=safety,
        tool_registry=registry,
        tool_executor=executor,
        jobs=jobs,
        assistant=assistant,
        calculations=calculations,
        software_control=software_control,
        software_recovery=software_recovery,
        screen_awareness=screen_awareness,
        discord_relay=discord_relay,
        task_service=task_service,
        trust=trust,
        lifecycle=lifecycle,
        network_monitor=network_monitor,
    )
