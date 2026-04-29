from __future__ import annotations

import asyncio
import json
import os
from time import perf_counter
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from stormhelm.config.models import AppConfig
from stormhelm.core.async_routes import AsyncRouteStrategy
from stormhelm.core.async_routes import AsyncRouteHandle
from stormhelm.core.async_routes import RouteProgressStage
from stormhelm.core.async_routes import RouteProgressState
from stormhelm.core.async_routes import classify_async_route_policy
from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import build_execution_report
from stormhelm.core.calculations import CalculationCallerContext
from stormhelm.core.calculations import CalculationInputOrigin
from stormhelm.core.calculations import CalculationOutputMode
from stormhelm.core.calculations import CalculationRequest
from stormhelm.core.calculations import CalculationResultVisibility
from stormhelm.core.calculations import CalculationsSubsystem
from stormhelm.core.context_snapshots import ContextSnapshotFamily
from stormhelm.core.context_snapshots import ContextSnapshotLookup
from stormhelm.core.context_snapshots import ContextSnapshotPolicy
from stormhelm.core.context_snapshots import ContextSnapshotSource
from stormhelm.core.context_snapshots import ContextSnapshotStore
from stormhelm.core.context_snapshots import describe_snapshot_freshness
from stormhelm.core.context.service import ActiveContextService
from stormhelm.core.discord_relay import DiscordRelaySubsystem
from stormhelm.core.events import EventBuffer
from stormhelm.core.judgment.service import JudgmentService
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.latency import attach_latency_metadata
from stormhelm.core.latency import classify_route_latency_policy
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner import PlannerDecision
from stormhelm.core.orchestrator.planner_models import QueryShape
from stormhelm.core.orchestrator.route_triage import FastRouteClassifier
from stormhelm.core.orchestrator.route_triage import RouteTriageResult
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.screen_awareness import ScreenAwarenessSubsystem
from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.providers.base import AssistantProvider, ProviderToolCall
from stormhelm.core.software_control import SoftwareExecutionStatus
from stormhelm.core.software_control import SoftwareOperationRequest
from stormhelm.core.software_control import SoftwareOperationType
from stormhelm.core.software_control import SoftwareControlSubsystem
from stormhelm.core.software_recovery import SoftwareRecoverySubsystem
from stormhelm.core.subsystem_continuations import SubsystemContinuationRequest
from stormhelm.core.subsystem_continuations import SubsystemContinuationRunner
from stormhelm.core.subsystem_continuations import classify_subsystem_continuation
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.core.tasks import DurableTaskService
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository
from stormhelm.core.workspace.service import WorkspaceService
from stormhelm.shared.time import utc_now_iso


STAGE_TIMING_KEYS = (
    "session_create_or_load_ms",
    "history_context_ms",
    "memory_context_ms",
    "minimal_context_ms",
    "route_triage_ms",
    "snapshot_lookup_ms",
    "heavy_context_ms",
    "planner_route_ms",
    "route_handler_ms",
    "provider_call_ms",
    "provider_fallback_ms",
    "workspace_summary_ms",
    "workspace_detail_ms",
    "tool_planning_ms",
    "dry_run_plan_ms",
    "dry_run_executor_ms",
    "status_snapshot_ms",
    "active_request_state_ms",
    "event_collection_ms",
    "job_collection_ms",
    "event_job_snapshot_ms",
    "db_write_ms",
    "response_compose_ms",
    "response_serialization_ms",
    "payload_compaction_ms",
    "total_latency_ms",
    "memoized_summary_hits",
    "context_cache_hits",
    "context_cache_misses",
    "detail_load_deferred",
    "heavy_context_loaded",
    "fast_path_used",
    "planner_candidates_pruned_count",
    "snapshot_hot_path_hit",
    "heavy_context_avoided_by_snapshot",
)

RESPONSE_PROFILES = {
    "ghost_compact",
    "deck_summary",
    "deck_detail",
    "command_eval_compact",
}
_COMPACT_PROFILE_LIST_LIMITS = {
    "ghost_compact": 3,
    "deck_summary": 8,
    "command_eval_compact": 2,
}
_COMPACT_PROFILE_TEXT_LIMITS = {
    "ghost_compact": 360,
    "deck_summary": 900,
    "command_eval_compact": 240,
}


def _record_stage_ms(stage_timings: dict[str, float], key: str, started_at: float) -> None:
    elapsed = round((perf_counter() - started_at) * 1000, 3)
    stage_timings[key] = round(float(stage_timings.get(key, 0.0)) + elapsed, 3)


def _add_route_subspan(route_handler_subspans: dict[str, float], key: str, started_at: float) -> None:
    elapsed = round((perf_counter() - started_at) * 1000, 3)
    route_handler_subspans[key] = round(float(route_handler_subspans.get(key, 0.0)) + elapsed, 3)


def _merge_route_subspans(route_handler_subspans: dict[str, float], values: dict[str, Any]) -> None:
    for key, value in values.items():
        try:
            route_handler_subspans[str(key)] = round(
                float(route_handler_subspans.get(str(key), 0.0)) + float(value or 0.0),
                3,
            )
        except (TypeError, ValueError):
            continue


def _heavy_context_reason_for_triage(
    triage: RouteTriageResult | None,
    *,
    explicit_workspace_context: bool,
) -> str:
    if explicit_workspace_context:
        return "explicit_workspace_context"
    if triage is None:
        return "planner_context_required"
    if triage.needs_screen_context:
        return "screen_context"
    if triage.needs_deictic_context:
        return "deictic_context"
    if triage.needs_workspace_context:
        return "workspace_context"
    if triage.needs_recent_tool_results:
        return "recent_tool_results"
    if triage.needs_semantic_memory:
        return "semantic_memory"
    if not triage.safe_to_short_circuit:
        return "planner_context_required"
    return ""


def _provider_configured(config: AppConfig) -> bool:
    return bool(str(getattr(config.openai, "api_key", "") or "").strip())


def _snapshot_activity(request_cache: dict[str, Any]) -> dict[str, Any]:
    activity = request_cache.get("snapshot_activity")
    if isinstance(activity, dict):
        return activity
    activity = {
        "snapshots_checked": [],
        "snapshots_used": [],
        "snapshots_refreshed": [],
        "snapshots_invalidated": [],
        "snapshot_freshness": {},
        "snapshot_age_ms": {},
        "snapshot_miss_reason": {},
        "freshness_warnings": [],
        "stale_snapshot_used_cautiously": False,
        "snapshot_hot_path_hit": False,
    }
    request_cache["snapshot_activity"] = activity
    return activity


def _record_snapshot_lookup(
    request_cache: dict[str, Any],
    lookup: ContextSnapshotLookup,
    *,
    family: ContextSnapshotFamily,
    used: bool = True,
    warning: str = "",
) -> None:
    activity = _snapshot_activity(request_cache)
    family_value = family.value
    _append_unique(activity["snapshots_checked"], family_value)
    if used:
        _append_unique(activity["snapshots_used"], family_value)
    if lookup.refreshed:
        _append_unique(activity["snapshots_refreshed"], family_value)
    if lookup.miss_reason:
        activity["snapshot_miss_reason"][family_value] = lookup.miss_reason
    if lookup.hot_path_hit:
        activity["snapshot_hot_path_hit"] = True
    if lookup.stale_used_cautiously:
        activity["stale_snapshot_used_cautiously"] = True
    freshness = lookup.snapshot.freshness()
    activity["snapshot_freshness"][family_value] = freshness.state.value
    activity["snapshot_age_ms"][family_value] = freshness.age_ms
    if warning:
        _append_unique(activity["freshness_warnings"], warning)


def _record_snapshot_miss(
    request_cache: dict[str, Any],
    *,
    family: ContextSnapshotFamily,
    reason: str,
) -> None:
    activity = _snapshot_activity(request_cache)
    family_value = family.value
    _append_unique(activity["snapshots_checked"], family_value)
    activity["snapshot_freshness"][family_value] = "unavailable"
    activity["snapshot_miss_reason"][family_value] = reason


def _append_unique(values: list[Any], item: Any) -> None:
    if item not in values:
        values.append(item)


def _workspace_snapshot_payload(summary: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    payload: dict[str, Any] = {}
    for key in (
        "active_item",
        "opened_items",
        "openedItemsSummary",
        "workspace_summary_compact",
        "active_goal",
        "current_task_state",
        "last_completed_action",
        "pending_next_steps",
        "where_left_off",
        "likely_next",
        "detail_load_deferred",
        "workspace",
        "references",
        "referencesSummary",
    ):
        if key in summary:
            payload[key] = summary.get(key)
    for key, value in summary.items():
        if key not in payload:
            payload[key] = value
    return payload


def _subspans_from_direct_jobs(jobs: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    for job in jobs:
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        debug = data.get("debug") if isinstance(data.get("debug"), dict) else {}
        subspans = debug.get("route_handler_subspans") if isinstance(debug.get("route_handler_subspans"), dict) else {}
        _merge_route_subspans(values, subspans)
    return values


def _subspans_from_jobs(jobs: list[Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for job in jobs:
        result = getattr(job, "result", None)
        if not isinstance(result, dict):
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        subspans = data.get("route_handler_subspans") if isinstance(data.get("route_handler_subspans"), dict) else {}
        _merge_route_subspans(values, subspans)
        debug = data.get("debug") if isinstance(data.get("debug"), dict) else {}
        subspans = debug.get("route_handler_subspans") if isinstance(debug.get("route_handler_subspans"), dict) else {}
        _merge_route_subspans(values, subspans)
    return values


class AssistantOrchestrator:
    def __init__(
        self,
        *,
        config: AppConfig,
        conversations: ConversationRepository,
        jobs: JobManager,
        router: IntentRouter,
        events: EventBuffer,
        tool_registry: ToolRegistry,
        session_state: ConversationStateStore,
        planner: DeterministicPlanner,
        persona: PersonaContract,
        workspace_service: WorkspaceService | None = None,
        task_service: DurableTaskService | None = None,
        provider: AssistantProvider | None = None,
        calculations: CalculationsSubsystem | None = None,
        software_control: SoftwareControlSubsystem | None = None,
        software_recovery: SoftwareRecoverySubsystem | None = None,
        screen_awareness: ScreenAwarenessSubsystem | None = None,
        discord_relay: DiscordRelaySubsystem | None = None,
        subsystem_continuations: SubsystemContinuationRunner | None = None,
    ) -> None:
        self.config = config
        self.conversations = conversations
        self.jobs = jobs
        self.router = router
        self.events = events
        self.tool_registry = tool_registry
        self.session_state = session_state
        self.planner = planner
        self.route_triage = FastRouteClassifier()
        self.context_snapshots = ContextSnapshotStore()
        self.persona = persona
        self.workspace_service = workspace_service
        self.task_service = task_service
        self._fallback_workspace_service: WorkspaceService | None = None
        self.provider = provider
        self.calculations = calculations
        self.software_control = software_control
        self.software_recovery = software_recovery
        self.screen_awareness = screen_awareness
        self.discord_relay = discord_relay
        self.subsystem_continuations = subsystem_continuations
        self.active_context_service = ActiveContextService(session_state)
        self.judgment = JudgmentService(config=config, session_state=session_state)

    def _workspace_service_for_tools(self) -> WorkspaceService:
        if self.workspace_service is not None:
            return self.workspace_service
        if self._fallback_workspace_service is None:
            database = SQLiteDatabase(self.config.storage.database_path)
            database.initialize()
            self._fallback_workspace_service = WorkspaceService(
                config=self.config,
                repository=WorkspaceRepository(database),
                notes=NotesRepository(database),
                conversations=ConversationRepository(database),
                preferences=PreferencesRepository(database),
                session_state=self.session_state,
                indexer=WorkspaceIndexer(self.config),
                events=self.events,
                persona=self.persona,
            )
        return self._fallback_workspace_service

    def _compact_runtime_profile(self, profile: str) -> bool:
        return profile in {"ghost_compact", "deck_summary", "command_eval_compact"}

    def _command_eval_dry_run_enabled(self, profile: str) -> bool:
        if profile != "command_eval_compact":
            return False
        return str(os.environ.get("STORMHELM_COMMAND_EVAL_DRY_RUN") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }

    def _workspace_summary_for_request(
        self,
        *,
        session_id: str,
        profile: str,
        request_cache: dict[str, Any],
        stage_timings: dict[str, float],
    ) -> dict[str, Any]:
        if self.workspace_service is None:
            return {}
        cache_key = "workspace_summary_compact" if self._compact_runtime_profile(profile) else "workspace_summary_detail"
        cached = request_cache.get(cache_key)
        if isinstance(cached, dict):
            stage_timings["memoized_summary_hits"] = round(float(stage_timings.get("memoized_summary_hits", 0.0)) + 1.0, 3)
            return cached
        started = perf_counter()
        compact = self._compact_runtime_profile(profile)

        def refresh_workspace_summary() -> dict[str, Any]:
            if compact:
                stage_timings["detail_load_deferred"] = 1.0
                summary = self.workspace_service.active_workspace_summary_compact(session_id)
            else:
                summary = self.workspace_service.active_workspace_summary(session_id)
            return _workspace_snapshot_payload(summary)

        lookup = self.context_snapshots.get_or_refresh(
            ContextSnapshotFamily.ACTIVE_WORKSPACE,
            refresh_fn=refresh_workspace_summary,
            policy=ContextSnapshotPolicy.for_family(ContextSnapshotFamily.ACTIVE_WORKSPACE),
            session_id=session_id,
            source=ContextSnapshotSource.WORKSPACE,
            allow_usable_stale=True,
        )
        _record_snapshot_lookup(
            request_cache,
            lookup,
            family=ContextSnapshotFamily.ACTIVE_WORKSPACE,
            warning=describe_snapshot_freshness(lookup.snapshot) if lookup.stale_used_cautiously else "",
        )
        summary = dict(lookup.snapshot.payload_summary)
        _record_stage_ms(stage_timings, "workspace_summary_ms", started)
        request_cache[cache_key] = summary
        return summary

    def _prepare_context_snapshots(
        self,
        *,
        session_id: str,
        route_triage_result: RouteTriageResult,
        minimal_active_request_state: dict[str, Any],
        request_cache: dict[str, Any],
    ) -> None:
        provider_lookup = self.context_snapshots.get_or_refresh(
            ContextSnapshotFamily.PROVIDER_READINESS,
            refresh_fn=lambda: {
                "enabled": bool(self.config.openai.enabled),
                "configured": _provider_configured(self.config),
                "provider_available": self.provider is not None,
            },
            policy=ContextSnapshotPolicy.for_family(ContextSnapshotFamily.PROVIDER_READINESS),
            source=ContextSnapshotSource.PROVIDER,
        )
        _record_snapshot_lookup(request_cache, provider_lookup, family=ContextSnapshotFamily.PROVIDER_READINESS)

        active_lookup = self.context_snapshots.get_or_refresh(
            ContextSnapshotFamily.ACTIVE_REQUEST_STATE,
            refresh_fn=lambda: minimal_active_request_state,
            policy=ContextSnapshotPolicy.for_family(ContextSnapshotFamily.ACTIVE_REQUEST_STATE),
            session_id=session_id,
            source=ContextSnapshotSource.SESSION_STATE,
        )
        _record_snapshot_lookup(
            request_cache,
            active_lookup,
            family=ContextSnapshotFamily.ACTIVE_REQUEST_STATE,
            used=bool(minimal_active_request_state),
        )

        likely_families = set(route_triage_result.likely_route_families)
        if "software_control" in likely_families:
            catalog_lookup = self.context_snapshots.get_or_refresh(
                ContextSnapshotFamily.SOFTWARE_CATALOG,
                refresh_fn=lambda: {
                    "status": "available_for_planning",
                    "verification_claims": "fresh_probe_required",
                    "package_routes_enabled": bool(self.config.software_control.package_manager_routes_enabled),
                    "browser_guided_routes_enabled": bool(self.config.software_control.browser_guided_routes_enabled),
                },
                policy=ContextSnapshotPolicy.for_family(ContextSnapshotFamily.SOFTWARE_CATALOG),
                source=ContextSnapshotSource.SOFTWARE,
            )
            _record_snapshot_lookup(
                request_cache,
                catalog_lookup,
                family=ContextSnapshotFamily.SOFTWARE_CATALOG,
                warning="software catalog is for planning, not verification",
            )
        if "discord_relay" in likely_families:
            relay_config = getattr(self.config, "discord_relay", None)
            aliases = getattr(relay_config, "trusted_aliases", {}) if relay_config is not None else {}
            alias_lookup = self.context_snapshots.get_or_refresh(
                ContextSnapshotFamily.DISCORD_ALIASES,
                refresh_fn=lambda: {
                    "alias_count": len(aliases) if isinstance(aliases, dict) else 0,
                    "aliases": sorted(str(key) for key in aliases.keys())[:12] if isinstance(aliases, dict) else [],
                    "payload_fingerprint_required": True,
                },
                policy=ContextSnapshotPolicy.for_family(ContextSnapshotFamily.DISCORD_ALIASES),
                source=ContextSnapshotSource.DISCORD,
            )
            _record_snapshot_lookup(request_cache, alias_lookup, family=ContextSnapshotFamily.DISCORD_ALIASES)
        if "screen_awareness" in likely_families:
            screen = self.context_snapshots.get_snapshot(
                ContextSnapshotFamily.SCREEN_CONTEXT,
                session_id=session_id,
                allow_usable_stale=False,
                require_current=True,
            )
            if screen is None:
                _record_snapshot_miss(
                    request_cache,
                    family=ContextSnapshotFamily.SCREEN_CONTEXT,
                    reason="no_fresh_current_observation",
                )
            else:
                _record_snapshot_lookup(
                    request_cache,
                    ContextSnapshotLookup(snapshot=screen, hot_path_hit=True),
                    family=ContextSnapshotFamily.SCREEN_CONTEXT,
                )
        if likely_families & {"task_continuity", "workspace_operations"}:
            task_lookup = self.context_snapshots.get_or_refresh(
                ContextSnapshotFamily.ACTIVE_TASK,
                refresh_fn=lambda: {"status": "last_known", "fresh_check_required_for_claims": True},
                policy=ContextSnapshotPolicy.for_family(ContextSnapshotFamily.ACTIVE_TASK),
                session_id=session_id,
                source=ContextSnapshotSource.RUNTIME,
            )
            _record_snapshot_lookup(request_cache, task_lookup, family=ContextSnapshotFamily.ACTIVE_TASK)
        if "voice_control" in likely_families:
            voice_lookup = self.context_snapshots.get_or_refresh(
                ContextSnapshotFamily.VOICE_READINESS,
                refresh_fn=lambda: {
                    "voice_enabled": bool(self.config.voice.enabled),
                    "playback_enabled": bool(self.config.voice.playback.enabled),
                    "playback_claims": "action_required",
                },
                policy=ContextSnapshotPolicy.for_family(ContextSnapshotFamily.VOICE_READINESS),
                source=ContextSnapshotSource.VOICE,
            )
            _record_snapshot_lookup(request_cache, voice_lookup, family=ContextSnapshotFamily.VOICE_READINESS)

    def _workspace_context_summary_overlay(
        self,
        workspace_context: dict[str, Any] | None,
        *,
        profile: str,
    ) -> dict[str, Any]:
        if not isinstance(workspace_context, dict):
            return {}
        workspace = workspace_context.get("workspace") if isinstance(workspace_context.get("workspace"), dict) else {}
        overlay: dict[str, Any] = {}
        surface_content = workspace.get("surfaceContent") or workspace_context.get("surfaceContent")
        if isinstance(surface_content, dict) and surface_content:
            overlay["surfaceContentSummary"] = self._surface_content_reference_summary(surface_content, profile=profile)
        for source_key, summary_key in (
            ("references", "referencesSummary"),
            ("findings", "findingsSummary"),
            ("sessionNotes", "sessionNotesSummary"),
            ("openedItems", "openedItemsSummary"),
        ):
            value = workspace.get(source_key) if source_key in workspace else workspace_context.get(source_key)
            if isinstance(value, list):
                overlay[summary_key] = self._collection_summary(value, profile=profile)
        opened_items = workspace_context.get("opened_items")
        if isinstance(opened_items, list):
            overlay["openedItemsSummary"] = self._collection_summary(opened_items, profile=profile)
        return overlay

    def _attach_workspace_context_summary_overlay(
        self,
        data: dict[str, Any],
        *,
        request_cache: dict[str, Any],
        profile: str,
    ) -> dict[str, Any]:
        overlay = self._workspace_context_summary_overlay(
            request_cache.get("resolved_workspace_context"),
            profile=profile,
        )
        if not overlay:
            return data
        workspace = data.get("workspace")
        if isinstance(workspace, dict):
            workspace.update(overlay)
        action = data.get("action")
        if isinstance(action, dict) and isinstance(action.get("workspace"), dict):
            action["workspace"].update(overlay)
        return data

    async def _maybe_execute_workspace_requests_directly(
        self,
        requests: list[ToolRequest] | list[ProviderToolCall],
        *,
        session_id: str,
        prompt: str,
        surface_mode: str,
        active_module: str,
        response_profile: str,
        request_cache: dict[str, Any],
        stage_timings: dict[str, float],
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]] | None:
        normalized_requests = [
            (
                request.tool_name if isinstance(request, ToolRequest) else request.name,
                request.arguments,
            )
            for request in requests
        ]
        workspace_tools = {
            "workspace_restore",
            "workspace_assemble",
            "workspace_save",
            "workspace_clear",
            "workspace_archive",
            "workspace_rename",
            "workspace_tag",
            "workspace_list",
            "workspace_where_left_off",
            "workspace_next_steps",
        }
        if not normalized_requests or any(tool_name not in workspace_tools for tool_name, _ in normalized_requests):
            return None

        service = self._workspace_service_for_tools()
        compact_mode = self._compact_runtime_profile(response_profile)
        task_plan = None
        if self.task_service is not None:
            task_plan = self.task_service.begin_execution(
                session_id=session_id,
                prompt=prompt,
                requests=requests,
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=self._workspace_summary_for_request(
                    session_id=session_id,
                    profile=response_profile,
                    request_cache=request_cache,
                    stage_timings=stage_timings,
                ),
            )
        jobs: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        summaries: list[str] = []

        if (
            len(normalized_requests) == 1
            and normalized_requests[0][0] == "workspace_assemble"
            and self._subsystem_continuations_available()
        ):
            queued = await self._queue_workspace_assembly_continuation(
                arguments=dict(normalized_requests[0][1]),
                session_id=session_id,
                prompt=prompt,
                surface_mode=surface_mode,
                active_module=active_module,
                response_profile=response_profile,
                request_cache=request_cache,
                stage_timings=stage_timings,
                task_plan=task_plan,
                compact_mode=compact_mode,
            )
            if queued is not None:
                return queued

        for index, (tool_name, arguments) in enumerate(normalized_requests):
            arguments = dict(arguments)
            if tool_name == "workspace_restore":
                data = service.restore_workspace(str(arguments.get("query", "")), session_id=session_id, compact=compact_mode)
            elif tool_name == "workspace_assemble":
                data = service.assemble_workspace(str(arguments.get("query", "")), session_id=session_id, compact=compact_mode)
            elif tool_name == "workspace_save":
                data = service.save_workspace(session_id=session_id, compact=compact_mode)
            elif tool_name == "workspace_clear":
                data = service.clear_workspace(session_id=session_id)
            elif tool_name == "workspace_archive":
                data = service.archive_workspace(session_id=session_id, query=str(arguments.get("query", "")) or None, compact=compact_mode)
            elif tool_name == "workspace_rename":
                data = service.rename_workspace(session_id=session_id, new_name=str(arguments.get("new_name", "")), compact=compact_mode)
            elif tool_name == "workspace_tag":
                tags = arguments.get("tags", [])
                data = service.tag_workspace(session_id=session_id, tags=list(tags) if isinstance(tags, list) else [], compact=compact_mode)
            elif tool_name == "workspace_list":
                data = service.list_workspaces(
                    session_id=session_id,
                    query=str(arguments.get("query", "")),
                    include_archived=bool(arguments.get("include_archived", False)),
                    archived_only=bool(arguments.get("archived_only", False)),
                    compact=compact_mode,
                )
            elif tool_name == "workspace_where_left_off":
                data = (
                    self.task_service.where_we_left_off(session_id=session_id)
                    if self.task_service is not None
                    else None
                ) or service.where_we_left_off(session_id=session_id, compact=compact_mode)
            else:
                data = (
                    self.task_service.next_steps(session_id=session_id)
                    if self.task_service is not None
                    else None
                ) or service.next_steps(session_id=session_id, compact=compact_mode)
            if tool_name in {
                "workspace_restore",
                "workspace_assemble",
                "workspace_save",
                "workspace_clear",
                "workspace_archive",
                "workspace_rename",
                "workspace_tag",
            }:
                invalidated = self.context_snapshots.invalidate(
                    family=ContextSnapshotFamily.ACTIVE_WORKSPACE,
                    session_id=session_id,
                    reason=f"{tool_name}_workspace_mutation",
                )
                if invalidated:
                    activity = _snapshot_activity(request_cache)
                    _append_unique(activity["snapshots_invalidated"], ContextSnapshotFamily.ACTIVE_WORKSPACE.value)
            if compact_mode and isinstance(data, dict):
                data = self._attach_workspace_context_summary_overlay(
                    data,
                    request_cache=request_cache,
                    profile=response_profile,
                )

            summary = str(data.get("summary", "")).strip() if isinstance(data, dict) else ""
            if summary:
                summaries.append(summary)
            if isinstance(data, dict):
                action = data.get("action")
                if isinstance(action, dict):
                    actions.append(action)
                action_list = data.get("actions")
                if isinstance(action_list, list):
                    actions.extend(item for item in action_list if isinstance(item, dict))
            if task_plan is not None and index < len(task_plan.step_ids) and self.task_service is not None:
                self.task_service.record_direct_tool_result(
                    task_id=task_plan.task_id,
                    step_id=task_plan.step_ids[index],
                    tool_name=tool_name,
                    arguments=dict(arguments),
                    result={"summary": summary, "data": data} if isinstance(data, dict) else {"summary": summary},
                    success=True,
                )
            jobs.append(
                {
                    "job_id": f"direct-{tool_name}",
                    "tool_name": tool_name,
                    "arguments": dict(arguments),
                    "status": "completed",
                    "created_at": "",
                    "started_at": "",
                    "finished_at": "",
                    "result": {
                        "summary": summary,
                        "data": data,
                    },
                    "error": "",
                }
            )
            self.session_state.remember_tool_result(
                session_id,
                tool_name=tool_name,
                arguments=dict(arguments),
                result={"summary": summary, "data": data},
                captured_at="",
            )

        assistant_text = self.persona.report(self._merge_job_summaries([], summaries))
        return assistant_text, jobs, actions

    def _subsystem_continuations_available(self) -> bool:
        if self.subsystem_continuations is None:
            return False
        try:
            self.tool_registry.get("subsystem_continuation")
        except KeyError:
            return False
        return True

    async def _queue_workspace_assembly_continuation(
        self,
        *,
        arguments: dict[str, Any],
        session_id: str,
        prompt: str,
        surface_mode: str,
        active_module: str,
        response_profile: str,
        request_cache: dict[str, Any],
        stage_timings: dict[str, float],
        task_plan: Any,
        compact_mode: bool,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]] | None:
        policy = classify_subsystem_continuation(
            route_family="workspace_operations",
            subsystem="workspace",
            operation_kind="workspace.assemble_deep",
            approved=True,
            verification_required=False,
        )
        if not policy.worker_continuation_expected:
            return None
        inline_started = perf_counter()
        query = str(arguments.get("query", "") or prompt)
        request = SubsystemContinuationRequest.create(
            route_family="workspace_operations",
            subsystem="workspace",
            operation_kind="workspace.assemble_deep",
            stage="queued",
            request_id=f"subsystem-{uuid4().hex}",
            session_id=session_id,
            task_id=task_plan.task_id if task_plan is not None else "",
            source_surface=surface_mode,
            active_module=active_module,
            result_state="queued",
            approval_state="not_required",
            verification_required=False,
            verification_state="not_verified",
            worker_lane=policy.worker_lane,
            priority_level=policy.priority_level,
            payload_summary={"query": query, "compact": compact_mode},
            operator_text_preview=prompt[:220],
            debug={
                "tool_name": "workspace_assemble",
                "response_profile": response_profile,
                "policy": policy.to_dict(),
            },
        )
        self.events.publish(
            event_family="runtime",
            event_type="subsystem.continuation.created",
            severity="info",
            subsystem="workspace",
            session_id=session_id,
            subject=request.continuation_id,
            visibility_scope="watch_surface",
            retention_class="bounded_recent",
            provenance={"channel": "assistant", "kind": "route_progress"},
            message="Workspace assembly continuation created.",
            payload=request.to_dict(),
        )
        job = await self.jobs.submit(
            "subsystem_continuation",
            {"continuation_request": request.to_dict()},
            session_id=session_id,
            task_id=task_plan.task_id if task_plan is not None else None,
            task_step_id=task_plan.step_ids[0] if task_plan is not None and task_plan.step_ids else None,
            priority_lane=policy.worker_lane,
            priority_level=policy.priority_level,
            background_ok=policy.background_ok,
            operator_visible=True,
            can_yield=True,
            starvation_sensitive=False,
            route_family="workspace_operations",
            subsystem="workspace",
            continuation_id=request.continuation_id,
            safe_for_verification=False,
        )
        self.events.publish(
            event_family="runtime",
            event_type="subsystem.continuation.queued",
            severity="info",
            subsystem="workspace",
            session_id=session_id,
            subject=request.continuation_id,
            visibility_scope="watch_surface",
            retention_class="bounded_recent",
            provenance={"channel": "assistant", "kind": "route_progress"},
            message="Workspace assembly continuation queued.",
            payload={
                **request.to_dict(),
                "job_id": job.job_id,
                "completion_claimed": False,
                "verification_claimed": False,
            },
        )
        initial_job = self._initial_async_job_reference(job)
        worker_status = self.jobs.worker_status_snapshot()
        inline_ms = round((perf_counter() - inline_started) * 1000, 3)
        continuation_payload = {
            "subsystem_continuation_created": True,
            "subsystem_continuation_id": request.continuation_id,
            "subsystem_continuation_kind": request.operation_kind,
            "subsystem_continuation_stage": "queued",
            "subsystem_continuation_status": "queued",
            "subsystem_continuation_worker_lane": policy.worker_lane,
            "subsystem_continuation_queue_wait_ms": 0.0,
            "subsystem_continuation_run_ms": 0.0,
            "subsystem_continuation_total_ms": 0.0,
            "subsystem_continuation_progress_event_count": 0,
            "subsystem_continuation_final_result_state": "queued",
            "subsystem_continuation_verification_state": "not_verified",
            "direct_subsystem_async_converted": True,
            "inline_front_half_ms": inline_ms,
            "worker_back_half_ms": 0.0,
            "returned_before_subsystem_completion": True,
            "async_conversion_expected": True,
            "async_conversion_missing_reason": "",
            "worker_lane": policy.worker_lane,
            "worker_priority": policy.priority_level,
            "queue_depth_at_submit": int(initial_job.get("job_timing_summary", {}).get("queue_depth_at_submit") or 0),
            "worker_capacity": int(worker_status.get("worker_capacity") or 0),
            "workers_busy_at_submit": int(worker_status.get("workers_busy") or 0),
            "workers_idle_at_submit": int(worker_status.get("workers_idle") or 0),
            "worker_saturation_percent": float(worker_status.get("worker_saturation_percent") or 0.0),
            "starvation_detected": bool(worker_status.get("starvation_detected")),
        }
        request_cache["subsystem_continuation"] = continuation_payload
        stage_timings["inline_front_half_ms"] = inline_ms
        stage_timings["direct_subsystem_async_converted"] = 1.0
        stage_timings["subsystem_continuation_created"] = 1.0
        stage_timings["returned_before_subsystem_completion"] = 1.0
        stage_timings["job_wait_ms"] = 0.0
        assistant_text = self.persona.report("Queued workspace assembly. I will keep progress visible while it runs.")
        return assistant_text, [initial_job], []

    async def handle_message(
        self,
        message: str,
        session_id: str = "default",
        *,
        surface_mode: str = "ghost",
        active_module: str = "chartroom",
        workspace_context: dict[str, Any] | None = None,
        input_context: dict[str, Any] | None = None,
        response_profile: str | None = None,
    ) -> dict[str, object]:
        request_started = perf_counter()
        request_id = f"chat-{uuid4().hex}"
        stage_timings: dict[str, float] = {key: 0.0 for key in STAGE_TIMING_KEYS}
        request_cache: dict[str, Any] = {}
        provider_called = False
        openai_called = False
        llm_called = False
        embedding_called = False
        fail_fast_reason = ""
        resolved_response_profile, response_profile_reason = self._resolve_response_profile(
            explicit_profile=response_profile,
            surface_mode=surface_mode,
            active_module=active_module,
        )
        stage_started = perf_counter()
        self.conversations.ensure_session(session_id)
        _record_stage_ms(stage_timings, "session_create_or_load_ms", stage_started)

        memory_started = perf_counter()
        self.judgment.observe_operator_turn(session_id, message)
        if self.workspace_service is not None:
            self.workspace_service.capture_workspace_context(
                session_id=session_id,
                prompt=message,
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=workspace_context,
            )
        _record_stage_ms(stage_timings, "memory_context_ms", memory_started)

        db_started = perf_counter()
        user_message = self.conversations.add_message(
            session_id,
            "user",
            message,
            metadata={
                "surface_mode": surface_mode,
                "active_module": active_module,
                "workspace_context": workspace_context or {},
                "input_context": input_context or {},
            },
        )
        _record_stage_ms(stage_timings, "db_write_ms", db_started)

        minimal_context_started = perf_counter()
        minimal_active_request_state = self.session_state.get_active_request_state(session_id)
        _record_stage_ms(stage_timings, "minimal_context_ms", minimal_context_started)

        triage_started = perf_counter()
        route_triage_result = self.route_triage.classify(
            message,
            active_request_state=minimal_active_request_state,
            provider_enabled=bool(self.config.openai.enabled and self.provider is not None),
            provider_configured=_provider_configured(self.config),
            surface_mode=surface_mode,
            active_module=active_module,
        )
        _record_stage_ms(stage_timings, "route_triage_ms", triage_started)
        stage_timings["fast_path_used"] = 1.0 if route_triage_result.safe_to_short_circuit else 0.0
        request_cache["route_triage_result"] = route_triage_result.to_dict()

        snapshot_started = perf_counter()
        self._prepare_context_snapshots(
            session_id=session_id,
            route_triage_result=route_triage_result,
            minimal_active_request_state=minimal_active_request_state,
            request_cache=request_cache,
        )
        _record_stage_ms(stage_timings, "snapshot_lookup_ms", snapshot_started)

        route_started = perf_counter()
        routed = self.router.route(message, surface_mode=surface_mode)
        _record_stage_ms(stage_timings, "planner_route_ms", route_started)

        actions: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        assistant_text = routed.assistant_message
        planner_debug: dict[str, Any] = {}
        route_handler_subspans: dict[str, float] = {}
        planned_decision: PlannerDecision | None = None
        memory_started = perf_counter()
        heavy_context_reason = _heavy_context_reason_for_triage(
            route_triage_result,
            explicit_workspace_context=isinstance(workspace_context, dict) and bool(workspace_context),
        )
        heavy_context_started = perf_counter()
        resolved_workspace_context = workspace_context or (
            self._workspace_summary_for_request(
                session_id=session_id,
                profile=resolved_response_profile,
                request_cache=request_cache,
                stage_timings=stage_timings,
            )
            if self.workspace_service is not None and heavy_context_reason
            else {}
        )
        if heavy_context_reason and (workspace_context or self.workspace_service is not None):
            _record_stage_ms(stage_timings, "heavy_context_ms", heavy_context_started)
            stage_timings["heavy_context_loaded"] = 1.0
        else:
            stage_timings["heavy_context_loaded"] = 0.0
        request_cache["resolved_workspace_context"] = resolved_workspace_context
        command_eval_compact = resolved_response_profile == "command_eval_compact"
        active_state_started = perf_counter()
        turn_context_snapshot = self.session_state.get_turn_context_snapshot(
            session_id,
            max_age_seconds=900,
            prefer_local_memory=command_eval_compact or route_triage_result.safe_to_short_circuit,
        )
        active_posture = (
            dict(turn_context_snapshot.get("active_posture"))
            if isinstance(turn_context_snapshot.get("active_posture"), dict)
            else {}
        )
        active_request_state = (
            dict(turn_context_snapshot.get("active_request_state"))
            if isinstance(turn_context_snapshot.get("active_request_state"), dict)
            else {}
        )
        if not active_request_state and minimal_active_request_state:
            active_request_state = dict(minimal_active_request_state)
        recent_tool_results = [
            dict(item)
            for item in turn_context_snapshot.get("recent_tool_results", [])
            if isinstance(item, dict)
        ]
        recent_context_resolutions = [
            dict(item)
            for item in turn_context_snapshot.get("recent_context_resolutions", [])
            if isinstance(item, dict)
        ]
        learned_preferences = (
            dict(turn_context_snapshot.get("learned_preferences"))
            if isinstance(turn_context_snapshot.get("learned_preferences"), dict)
            else {}
        )
        stage_timings["context_cache_misses"] += 1.0
        _record_stage_ms(stage_timings, "active_request_state_ms", active_state_started)
        active_input_context = dict(input_context) if isinstance(input_context, dict) else {}
        if command_eval_compact and recent_context_resolutions and not active_input_context.get("recent_context_resolutions"):
            active_input_context["recent_context_resolutions"] = recent_context_resolutions[:4]
            stage_timings["context_cache_hits"] += 1.0
        active_context = self.active_context_service.update_from_turn(
            session_id=session_id,
            workspace_context=resolved_workspace_context,
            active_posture=active_posture,
            active_request_state=active_request_state,
            recent_tool_results=recent_tool_results,
            input_context=active_input_context or input_context,
            existing_context=turn_context_snapshot.get("active_context") if isinstance(turn_context_snapshot.get("active_context"), dict) else None,
        )
        _record_stage_ms(stage_timings, "memory_context_ms", memory_started)
        response_judgment: dict[str, Any] = {}

        def set_cached_active_request_state(request_state: dict[str, Any] | None) -> None:
            nonlocal active_request_state
            self.session_state.set_active_request_state(session_id, request_state)
            active_request_state = dict(request_state) if isinstance(request_state, dict) else {}
            invalidated = self.context_snapshots.invalidate(
                family=ContextSnapshotFamily.ACTIVE_REQUEST_STATE,
                session_id=session_id,
                reason="active_request_state_updated",
            )
            if invalidated:
                activity = _snapshot_activity(request_cache)
                _append_unique(activity["snapshots_invalidated"], ContextSnapshotFamily.ACTIVE_REQUEST_STATE.value)
            stage_timings["context_cache_hits"] += 1.0

        def clear_cached_active_request_state() -> None:
            nonlocal active_request_state
            self.session_state.clear_active_request_state(session_id)
            active_request_state = {}
            invalidated = self.context_snapshots.invalidate(
                family=ContextSnapshotFamily.ACTIVE_REQUEST_STATE,
                session_id=session_id,
                reason="active_request_state_cleared",
            )
            invalidated += self.context_snapshots.invalidate(
                family=ContextSnapshotFamily.PENDING_TRUST,
                session_id=session_id,
                reason="active_request_state_cleared",
            )
            if invalidated:
                activity = _snapshot_activity(request_cache)
                _append_unique(activity["snapshots_invalidated"], ContextSnapshotFamily.ACTIVE_REQUEST_STATE.value)
                _append_unique(activity["snapshots_invalidated"], ContextSnapshotFamily.PENDING_TRUST.value)
            stage_timings["context_cache_hits"] += 1.0

        route_handler_started = perf_counter()
        try:
            if routed.tool_calls:
                planner_debug = self._direct_handler_debug(routed.tool_calls, surface_mode=surface_mode)
                assistant_text, jobs, actions = await self._execute_tool_requests(
                    routed.tool_calls,
                    session_id=session_id,
                    prompt=message,
                    surface_mode=surface_mode,
                    active_module=active_module,
                    stage_timings=stage_timings,
                    route_handler_subspans=route_handler_subspans,
                    response_profile=resolved_response_profile,
                    request_cache=request_cache,
                )
                self.session_state.clear_previous_response_id(session_id, role="planner")
                self.session_state.clear_previous_response_id(session_id, role="reasoner")
            elif assistant_text is not None:
                assistant_text = self.persona.report(assistant_text)
            else:
                route_started = perf_counter()
                planned = self.planner.plan(
                    message,
                    session_id=session_id,
                    surface_mode=surface_mode,
                    active_module=active_module,
                    workspace_context=resolved_workspace_context,
                    active_posture=active_posture,
                    active_request_state=active_request_state,
                    recent_tool_results=recent_tool_results,
                    learned_preferences=learned_preferences,
                    active_context=active_context,
                    route_triage_result=route_triage_result,
                    available_tools={
                        tool.name
                        for tool in self.tool_registry.all_tools()
                        if self.config.tools.enabled.is_enabled(tool.name)
                    },
                )
                planned = await self._maybe_apply_browser_search_fallback(
                    planned=planned,
                    message=message,
                    session_id=session_id,
                    surface_mode=surface_mode,
                    active_module=active_module,
                    workspace_context=resolved_workspace_context,
                    active_context=active_context,
                )
                _record_stage_ms(stage_timings, "planner_route_ms", route_started)
                planned_decision = planned
                planner_debug = dict(planned.debug)
                if self._planner_debug_provider_fallback_attempted(planner_debug):
                    provider_called = True
                    openai_called = True
                    llm_called = True
                self._publish_calculation_event(
                    session_id=session_id,
                    calculation_debug=planner_debug.get("calculations"),
                )
                self._publish_screen_awareness_event(
                    session_id=session_id,
                    screen_awareness_debug=planner_debug.get("screen_awareness"),
                )
                if planned.tool_requests:
                    tool_plan_started = perf_counter()
                    pre_action = self.judgment.assess_pre_action(
                        session_id=session_id,
                        message=message,
                        tool_requests=planned.tool_requests,
                        active_context=active_context,
                    )
                    _record_stage_ms(stage_timings, "tool_planning_ms", tool_plan_started)
                    assistant_text, jobs, actions = await self._execute_tool_requests(
                        planned.tool_requests,
                        session_id=session_id,
                        prompt=message,
                        surface_mode=surface_mode,
                        active_module=active_module,
                        stage_timings=stage_timings,
                        route_handler_subspans=route_handler_subspans,
                        response_profile=resolved_response_profile,
                        request_cache=request_cache,
                    )
                    post_action = self.judgment.evaluate_post_action(
                        session_id=session_id,
                        message=message,
                        jobs=jobs,
                        actions=actions,
                        active_context=active_context,
                        active_request_state=planned.active_request_state,
                        pre_action=pre_action,
                    )
                    response_judgment = {
                        "risk_tier": pre_action.risk_tier.value,
                        "decision": pre_action.outcome,
                        "debug": dict(post_action.debug),
                    }
                    if post_action.suppressed_reason:
                        response_judgment["suppressed_reason"] = post_action.suppressed_reason
                    if post_action.next_suggestion is not None:
                        response_judgment["next_suggestion"] = dict(post_action.next_suggestion)
                    if post_action.recovery:
                        response_judgment["recovery"] = True
                    if planned.active_request_state:
                        set_cached_active_request_state(planned.active_request_state)
                        self._learn_from_message(session_id=session_id, message=message, request_state=planned.active_request_state)
                    if self.provider is not None and self.config.openai.enabled and self.planner.should_escalate(
                        message,
                        tool_job_count=len(jobs),
                        actions=actions,
                        planner_text=assistant_text,
                        request_type=planned.request_type,
                        requires_reasoner=planned.requires_reasoner,
                    ):
                        provider_started = perf_counter()
                        provider_called = True
                        openai_called = True
                        llm_called = True
                        assistant_text = await self._run_reasoner_summary(
                            message=message,
                            session_id=session_id,
                            surface_mode=surface_mode,
                            active_module=active_module,
                            workspace_context=resolved_workspace_context,
                            active_context=active_context,
                            jobs=jobs,
                            actions=actions,
                        )
                        _record_stage_ms(stage_timings, "provider_call_ms", provider_started)
                    self.session_state.clear_previous_response_id(session_id, role="planner")
                    self.session_state.clear_previous_response_id(session_id, role="reasoner")
                elif (
                    planned.execution_plan is not None
                    and planned.structured_query is not None
                    and planned.structured_query.query_shape == QueryShape.CALCULATION_REQUEST
                    and planned.execution_plan.plan_type == "calculation_evaluate"
                    and self.calculations is not None
                ):
                    calculation_slots = (
                        planned.structured_query.slots if isinstance(planned.structured_query.slots, dict) else {}
                    )
                    calculation_request_payload = (
                        calculation_slots.get("calculation_request")
                        if isinstance(calculation_slots.get("calculation_request"), dict)
                        else {}
                    )
                    requested_mode = str(
                        calculation_request_payload.get("requested_mode")
                        or calculation_slots.get("requested_mode")
                        or CalculationOutputMode.ANSWER_ONLY.value
                    ).strip()
                    try:
                        calculation_mode = CalculationOutputMode(requested_mode)
                    except ValueError:
                        calculation_mode = CalculationOutputMode.ANSWER_ONLY
                    calculation_request = CalculationRequest(
                        request_id=f"calc-{session_id}",
                        source_surface=surface_mode,
                        raw_input=message,
                        user_visible_text=message,
                        extracted_expression=str(calculation_request_payload.get("extracted_expression") or "").strip() or None,
                        requested_mode=calculation_mode,
                        helper_name=str(calculation_request_payload.get("helper_name") or "").strip() or None,
                        arguments=(
                            dict(calculation_request_payload.get("arguments") or {})
                            if isinstance(calculation_request_payload.get("arguments"), dict)
                            else {}
                        ),
                        missing_arguments=(
                            list(calculation_request_payload.get("missing_arguments") or [])
                            if isinstance(calculation_request_payload.get("missing_arguments"), list)
                            else []
                        ),
                        follow_up_reuse=bool(calculation_request_payload.get("follow_up_reuse", False)),
                        verification_claim=str(calculation_request_payload.get("verification_claim") or "").strip() or None,
                        caller=CalculationCallerContext(
                            subsystem="assistant",
                            caller_intent="planner_direct_calculation",
                            input_origin=(
                                CalculationInputOrigin.REUSED_CONTEXT
                                if bool(calculation_request_payload.get("follow_up_reuse", False))
                                else CalculationInputOrigin.USER_TEXT
                            ),
                            visual_extraction_dependency=False,
                            internal_validation=False,
                            result_visibility=CalculationResultVisibility.USER_FACING,
                            reuse_path="assistant_orchestrator.calculation_request",
                            provenance_stack=[
                                "assistant_orchestrator",
                                "recent_context_reuse"
                                if bool(calculation_request_payload.get("follow_up_reuse", False))
                                else "direct_user_request",
                            ],
                        ),
                    )
                    subsystem_started = perf_counter()
                    calculation_response = self.calculations.execute(
                        session_id=session_id,
                        active_module=active_module,
                        request=calculation_request,
                    )
                    _add_route_subspan(route_handler_subspans, "calculations_execute_ms", subsystem_started)
                    assistant_text = calculation_response.assistant_response
                    self.active_context_service.remember_resolution(
                        session_id,
                        {
                            "kind": "calculation",
                            "query": message,
                            "result": calculation_response.result.to_dict()
                            if calculation_response.result is not None
                            else None,
                            "failure": calculation_response.failure.to_dict()
                            if calculation_response.failure is not None
                            else None,
                            "trace": calculation_response.trace.to_dict(),
                        },
                    )
                    planned.structured_query.slots["response_contract"] = dict(calculation_response.response_contract)
                    calculation_debug = dict(planner_debug.get("calculations") or {})
                    calculation_debug["trace"] = calculation_response.trace.to_dict()
                    calculation_debug["result"] = (
                        calculation_response.result.to_dict() if calculation_response.result is not None else None
                    )
                    calculation_debug["failure"] = (
                        calculation_response.failure.to_dict() if calculation_response.failure is not None else None
                    )
                    planner_debug["calculations"] = calculation_debug
                    self._publish_calculation_event(
                        session_id=session_id,
                        calculation_debug=calculation_debug,
                    )
                elif (
                    planned.execution_plan is not None
                    and planned.structured_query is not None
                    and planned.structured_query.query_shape == QueryShape.SOFTWARE_CONTROL_REQUEST
                    and planned.execution_plan.plan_type == "software_control_execute"
                    and self.software_control is not None
                ):
                    software_slots = (
                        planned.structured_query.slots if isinstance(planned.structured_query.slots, dict) else {}
                    )
                    operation_value = str(software_slots.get("operation_type") or "install").strip().lower()
                    try:
                        operation_type = SoftwareOperationType(operation_value)
                    except ValueError:
                        operation_type = SoftwareOperationType.INSTALL
                    sensitive_task_id = ""
                    if self.task_service is not None:
                        resolver = getattr(self.task_service, "current_sensitive_task_id", None)
                        if callable(resolver):
                            sensitive_task_id = str(resolver(session_id=session_id) or "").strip()
                    if not sensitive_task_id:
                        sensitive_task_id = str(self.session_state.get_active_task_id(session_id) or "").strip()
                    software_request = SoftwareOperationRequest(
                        request_id=f"software-{session_id}",
                        source_surface=surface_mode,
                        raw_input=message,
                        user_visible_text=message,
                        operation_type=operation_type,
                        target_name=str(software_slots.get("target_name") or "").strip() or "software",
                        request_stage=str(software_slots.get("request_stage") or "prepare_plan").strip() or "prepare_plan",
                        follow_up_reuse=bool(software_slots.get("follow_up_reuse", False)),
                        selected_source_route=str(software_slots.get("selected_source_route") or "").strip() or None,
                        task_id=sensitive_task_id or None,
                        trust_request_id=str(software_slots.get("trust_request_id") or "").strip() or None,
                        approval_scope=str(software_slots.get("approval_scope") or "").strip() or None,
                        approval_outcome=str(software_slots.get("approval_outcome") or "").strip() or None,
                    )
                    subsystem_started = perf_counter()
                    software_response = self.software_control.execute_software_operation(
                        session_id=session_id,
                        active_module=active_module,
                        request=software_request,
                    )
                    _add_route_subspan(route_handler_subspans, "software_control_execute_ms", subsystem_started)
                    assistant_text = self.persona.report(software_response.assistant_response)
                    self.active_context_service.remember_resolution(
                        session_id,
                        {
                            "kind": "software_control",
                            "query": message,
                            "result": software_response.result.to_dict()
                            if software_response.result is not None
                            else None,
                            "verification": software_response.verification.to_dict()
                            if software_response.verification is not None
                            else None,
                            "recovery_plan": software_response.recovery_plan.to_dict()
                            if software_response.recovery_plan is not None
                            else None,
                            "recovery_result": software_response.recovery_result.to_dict()
                            if software_response.recovery_result is not None
                            else None,
                            "trace": software_response.trace.to_dict(),
                        },
                    )
                    planned.structured_query.slots["response_contract"] = dict(software_response.response_contract)
                    if software_response.active_request_state is not None:
                        if software_response.active_request_state:
                            set_cached_active_request_state(software_response.active_request_state)
                        elif planned.active_request_state:
                            set_cached_active_request_state(planned.active_request_state)
                            self._learn_from_message(
                                session_id=session_id,
                                message=message,
                                request_state=planned.active_request_state,
                            )
                        else:
                            clear_cached_active_request_state()
                    software_debug = dict(planner_debug.get("software_control") or {})
                    software_debug["result"] = (
                        software_response.result.to_dict() if software_response.result is not None else None
                    )
                    software_debug["trace"] = software_response.trace.to_dict()
                    software_debug["verification"] = (
                        software_response.verification.to_dict() if software_response.verification is not None else None
                    )
                    if software_response.recovery_plan is not None:
                        software_debug["recovery_plan"] = software_response.recovery_plan.to_dict()
                    if software_response.recovery_result is not None:
                        software_debug["recovery_result"] = software_response.recovery_result.to_dict()
                    planner_debug["software_control"] = software_debug
                    self._publish_software_control_event(
                        session_id=session_id,
                        software_debug=software_debug,
                    )
                    if software_response.trace.recovery_invoked:
                        self._publish_software_recovery_event(
                            session_id=session_id,
                            recovery_debug=software_debug,
                        )
                elif (
                    planned.execution_plan is not None
                    and planned.structured_query is not None
                    and planned.structured_query.query_shape == QueryShape.SCREEN_AWARENESS_REQUEST
                    and planned.execution_plan.plan_type in {
                        "screen_awareness_analyze",
                        "screen_awareness_act",
                        "screen_awareness_continue",
                        "screen_awareness_workflow",
                        "screen_awareness_brain",
                        "screen_awareness_power",
                    }
                    and self.screen_awareness is not None
                ):
                    screen_debug = planned.structured_query.slots.get("screen_awareness")
                    debug_payload = dict(screen_debug) if isinstance(screen_debug, dict) else {}
                    intent_value = str(
                        debug_payload.get("intent")
                        or planned.structured_query.requested_action
                        or ScreenIntentType.INSPECT_VISIBLE_STATE.value
                    ).strip()
                    try:
                        screen_intent = ScreenIntentType(intent_value)
                    except ValueError:
                        screen_intent = ScreenIntentType.INSPECT_VISIBLE_STATE
                    subsystem_started = perf_counter()
                    screen_response = self.screen_awareness.handle_request(
                        session_id=session_id,
                        operator_text=message,
                        intent=screen_intent,
                        surface_mode=surface_mode,
                        active_module=active_module,
                        active_context=active_context,
                        workspace_context=resolved_workspace_context,
                    )
                    _add_route_subspan(route_handler_subspans, "screen_awareness_execute_ms", subsystem_started)
                    assistant_text = self.persona.report(screen_response.assistant_response)
                    self.active_context_service.remember_resolution(
                        session_id,
                        {
                            "kind": "screen_awareness",
                            "intent": screen_intent.value,
                            "query": message,
                            "analysis_result": screen_response.analysis.to_dict(),
                            "telemetry": dict(screen_response.telemetry),
                        },
                    )
                    planned.structured_query.slots["response_contract"] = dict(screen_response.response_contract)
                    if planned.active_request_state:
                        set_cached_active_request_state(planned.active_request_state)
                    screen_awareness_debug = dict(planner_debug.get("screen_awareness") or {})
                    screen_awareness_debug["analysis_result"] = screen_response.analysis.to_dict()
                    screen_awareness_debug["telemetry"] = dict(screen_response.telemetry)
                    planner_debug["screen_awareness"] = screen_awareness_debug
                    self._publish_screen_awareness_event(
                        session_id=session_id,
                        screen_awareness_debug=screen_awareness_debug,
                    )
                elif (
                    planned.execution_plan is not None
                    and planned.structured_query is not None
                    and planned.structured_query.query_shape == QueryShape.DISCORD_RELAY_REQUEST
                    and planned.execution_plan.plan_type in {"discord_relay_preview", "discord_relay_dispatch"}
                    and self.discord_relay is not None
                ):
                    subsystem_started = perf_counter()
                    relay_response = self.discord_relay.handle_request(
                        session_id=session_id,
                        operator_text=message,
                        surface_mode=surface_mode,
                        active_module=active_module,
                        active_context=active_context,
                        workspace_context=resolved_workspace_context,
                        request_slots=planned.structured_query.slots,
                    )
                    _add_route_subspan(route_handler_subspans, "discord_relay_execute_ms", subsystem_started)
                    assistant_text = self.persona.report(relay_response.assistant_response)
                    self.active_context_service.remember_resolution(
                        session_id,
                        {
                            "kind": "discord_relay",
                            "query": message,
                            "state": relay_response.state.value,
                            "preview": relay_response.preview.to_dict() if relay_response.preview is not None else None,
                            "attempt": relay_response.attempt.to_dict() if relay_response.attempt is not None else None,
                            "trace": relay_response.trace.to_dict() if relay_response.trace is not None else None,
                        },
                    )
                    planned.structured_query.slots["response_contract"] = dict(relay_response.response_contract)
                    if relay_response.active_request_state is not None:
                        if relay_response.active_request_state:
                            set_cached_active_request_state(relay_response.active_request_state)
                        else:
                            clear_cached_active_request_state()
                    relay_debug = dict(relay_response.debug)
                    if relay_response.trace is not None:
                        relay_debug["trace"] = relay_response.trace.to_dict()
                    if relay_response.preview is not None:
                        relay_debug["preview"] = relay_response.preview.to_dict()
                    if relay_response.attempt is not None:
                        relay_debug["attempt"] = relay_response.attempt.to_dict()
                    planner_debug["discord_relay"] = relay_debug
                    self._publish_discord_relay_event(
                        session_id=session_id,
                        relay_debug=relay_debug,
                    )
                elif planned.assistant_message:
                    if planned.active_request_state:
                        set_cached_active_request_state(planned.active_request_state)
                        self._learn_from_message(session_id=session_id, message=message, request_state=planned.active_request_state)
                    assistant_text = self.persona.report(planned.assistant_message)
                elif (
                    planned.active_request_state
                    and planned.structured_query is not None
                    and planned.structured_query.query_shape == QueryShape.SOFTWARE_CONTROL_REQUEST
                ):
                    set_cached_active_request_state(planned.active_request_state)
                    self._learn_from_message(session_id=session_id, message=message, request_state=planned.active_request_state)
                    target = str(planned.active_request_state.get("subject") or "that software").strip()
                    assistant_text = self.persona.report(
                        f"I prepared the software-control plan for {target}. No external action has run."
                    )
                elif self.provider is not None and self.config.openai.enabled:
                    provider_started = perf_counter()
                    provider_called = True
                    openai_called = True
                    llm_called = True
                    assistant_text, jobs, actions = await self._handle_provider_turn(
                        message=message,
                        session_id=session_id,
                        surface_mode=surface_mode,
                        active_module=active_module,
                        workspace_context=resolved_workspace_context,
                        active_context=active_context,
                    )
                    _record_stage_ms(stage_timings, "provider_fallback_ms", provider_started)
                else:
                    fail_fast_reason = "provider_disabled"
                    assistant_text = self.persona.report(
                        "OpenAI integration is not configured. Set OPENAI_API_KEY in .env or your environment "
                        "and enable [openai].enabled for natural-language assistance, or use explicit safe commands "
                        "like /time, /battery, /storage, /open, or /recent."
                    )
        except Exception as error:
            assistant_text = self.persona.error(str(error))
            self.events.publish(
                event_family="runtime",
                event_type="runtime.assistant_request_failed",
                severity="warning",
                subsystem="assistant",
                session_id=session_id,
                visibility_scope="ghost_hint",
                retention_class="operator_relevant",
                provenance={"channel": "assistant", "kind": "operator_summary"},
                message="Failed to handle assistant request.",
                payload={"error": str(error), "surface_mode": surface_mode, "active_module": active_module},
            )
            jobs = []
            actions = []

        _record_stage_ms(stage_timings, "route_handler_ms", route_handler_started)

        response_started = perf_counter()
        planner_obedience = self._planner_obedience_metadata(
            planned_decision=planned_decision,
            jobs=jobs,
            actions=actions,
            text=assistant_text,
        )
        if planner_obedience:
            planner_debug.update(
                {
                    "actual_tool_names": list(planner_obedience.get("actual_tool_names") or []),
                    "actual_result_mode": str(planner_obedience.get("actual_result_mode") or ""),
                    "planner_authority": dict(planner_obedience),
                }
            )

        response_metadata = self._build_response_metadata(
            text=assistant_text,
            jobs=jobs,
            actions=actions,
            active_module=active_module,
            judgment=response_judgment,
            planner_obedience=planner_obedience,
            planned_decision=planned_decision,
        )
        triage_payload = route_triage_result.to_dict()
        route_family_seams_skipped = planner_debug.get("route_family_seams_skipped")
        route_family_seams_evaluated = planner_debug.get("route_family_seams_evaluated")
        planner_candidates_pruned_count = int(planner_debug.get("planner_candidates_pruned_count") or 0)
        stage_timings["planner_candidates_pruned_count"] = float(planner_candidates_pruned_count)
        planner_debug.setdefault("route_triage", triage_payload)
        planner_debug["heavy_context_loaded"] = bool(stage_timings.get("heavy_context_loaded"))
        planner_debug["heavy_context_reason"] = heavy_context_reason
        snapshot_activity = _snapshot_activity(request_cache)
        heavy_context_avoided_by_snapshot = (
            bool(snapshot_activity.get("snapshot_hot_path_hit"))
            and bool(route_triage_result.safe_to_short_circuit)
            and not bool(stage_timings.get("heavy_context_loaded"))
        )
        snapshot_activity["heavy_context_avoided_by_snapshot"] = heavy_context_avoided_by_snapshot
        snapshot_summary = self.context_snapshots.snapshot_summary()
        snapshot_metadata = {
            "snapshots_checked": list(snapshot_activity.get("snapshots_checked") or []),
            "snapshots_used": list(snapshot_activity.get("snapshots_used") or []),
            "snapshots_refreshed": list(snapshot_activity.get("snapshots_refreshed") or []),
            "snapshots_invalidated": list(snapshot_activity.get("snapshots_invalidated") or []),
            "snapshot_freshness": dict(snapshot_activity.get("snapshot_freshness") or {}),
            "snapshot_age_ms": dict(snapshot_activity.get("snapshot_age_ms") or {}),
            "snapshot_hot_path_hit": bool(snapshot_activity.get("snapshot_hot_path_hit")),
            "snapshot_miss_reason": dict(snapshot_activity.get("snapshot_miss_reason") or {}),
            "heavy_context_avoided_by_snapshot": heavy_context_avoided_by_snapshot,
            "stale_snapshot_used_cautiously": bool(snapshot_activity.get("stale_snapshot_used_cautiously")),
            "invalidation_count": int(snapshot_summary.get("invalidation_count") or 0),
            "freshness_warnings": list(snapshot_activity.get("freshness_warnings") or []),
        }
        stage_timings["snapshot_hot_path_hit"] = 1.0 if snapshot_metadata["snapshot_hot_path_hit"] else 0.0
        stage_timings["heavy_context_avoided_by_snapshot"] = (
            1.0 if snapshot_metadata["heavy_context_avoided_by_snapshot"] else 0.0
        )
        planner_debug["context_snapshots"] = dict(snapshot_metadata)
        response_metadata.update(
            {
                "route_triage_result": triage_payload,
                "fast_path_used": bool(route_triage_result.safe_to_short_circuit),
                "heavy_context_loaded": bool(stage_timings.get("heavy_context_loaded")),
                "heavy_context_reason": heavy_context_reason,
                "candidate_route_families": list(route_triage_result.likely_route_families),
                "skipped_route_families": list(route_triage_result.skipped_route_families),
                "provider_fallback_eligible": bool(route_triage_result.provider_fallback_eligible),
                "provider_fallback_suppressed_reason": (
                    "native_route_triage"
                    if route_triage_result.likely_route_families
                    and not route_triage_result.provider_fallback_eligible
                    and route_triage_result.likely_route_families[0] != "generic_provider"
                    else ""
                ),
                "planner_candidates_pruned_count": planner_candidates_pruned_count,
                "route_family_seams_evaluated": list(route_family_seams_evaluated)
                if isinstance(route_family_seams_evaluated, list)
                else [],
                "route_family_seams_skipped": list(route_family_seams_skipped)
                if isinstance(route_family_seams_skipped, list)
                else [],
                **snapshot_metadata,
            }
        )
        async_route_metadata = (
            request_cache.get("async_route")
            if isinstance(request_cache.get("async_route"), dict)
            else {}
        )
        if async_route_metadata:
            progress_state = (
                async_route_metadata.get("progress_state")
                if isinstance(async_route_metadata.get("progress_state"), dict)
                else {}
            )
            handle = (
                async_route_metadata.get("async_route_handle")
                if isinstance(async_route_metadata.get("async_route_handle"), dict)
                else {}
            )
            planner_debug["async_route"] = dict(async_route_metadata)
            stage_timings.setdefault("progress_event_count", float(async_route_metadata.get("progress_event_count") or 0.0))
            stage_timings["job_required"] = 1.0 if async_route_metadata.get("job_required") else 0.0
            stage_timings["task_required"] = 1.0 if async_route_metadata.get("task_required") else 0.0
            stage_timings["event_progress_required"] = (
                1.0 if async_route_metadata.get("event_progress_required") else 0.0
            )
            response_metadata.update(
                {
                    "async_strategy": str(async_route_metadata.get("async_strategy") or ""),
                    "async_initial_response_returned": bool(
                        async_route_metadata.get("async_initial_response_returned")
                    ),
                    "async_continuation": True,
                    "events_expected": True,
                    "job_required": bool(async_route_metadata.get("job_required")),
                    "task_required": bool(async_route_metadata.get("task_required")),
                    "event_progress_required": bool(async_route_metadata.get("event_progress_required")),
                    "route_continuation_id": str(
                        async_route_metadata.get("route_continuation_id")
                        or progress_state.get("continuation_id")
                        or handle.get("continuation_id")
                        or ""
                    ),
                    "route_progress_stage": str(
                        async_route_metadata.get("route_progress_stage")
                        or progress_state.get("stage")
                        or ""
                    ),
                    "route_progress_status": str(
                        async_route_metadata.get("route_progress_status")
                        or progress_state.get("status")
                        or ""
                    ),
                    "progress_event_count": int(async_route_metadata.get("progress_event_count") or 0),
                    "worker_lane": str(async_route_metadata.get("worker_lane") or ""),
                    "worker_priority": str(async_route_metadata.get("worker_priority") or ""),
                    "queue_depth_at_submit": int(async_route_metadata.get("queue_depth_at_submit") or 0),
                    "queue_wait_ms": float(async_route_metadata.get("queue_wait_ms") or 0.0),
                    "job_start_delay_ms": float(async_route_metadata.get("job_start_delay_ms") or 0.0),
                    "job_run_ms": float(async_route_metadata.get("job_run_ms") or 0.0),
                    "job_total_ms": float(async_route_metadata.get("job_total_ms") or 0.0),
                    "worker_index": async_route_metadata.get("worker_index"),
                    "worker_capacity": int(async_route_metadata.get("worker_capacity") or 0),
                    "workers_busy_at_submit": int(async_route_metadata.get("workers_busy_at_submit") or 0),
                    "workers_idle_at_submit": int(async_route_metadata.get("workers_idle_at_submit") or 0),
                    "worker_saturation_percent": float(
                        async_route_metadata.get("worker_saturation_percent") or 0.0
                    ),
                    "interactive_jobs_waiting": int(async_route_metadata.get("interactive_jobs_waiting") or 0),
                    "background_jobs_running": int(async_route_metadata.get("background_jobs_running") or 0),
                    "background_job_count": int(async_route_metadata.get("background_job_count") or 0),
                    "interactive_job_count": int(async_route_metadata.get("interactive_job_count") or 0),
                    "starvation_detected": bool(async_route_metadata.get("starvation_detected")),
                    "async_worker_utilization_summary": (
                        async_route_metadata.get("async_worker_utilization_summary")
                        if isinstance(async_route_metadata.get("async_worker_utilization_summary"), dict)
                        else {}
                    ),
                    "async_route_handle": handle,
                    "route_progress_state": progress_state,
                    "async_route": dict(async_route_metadata),
                }
            )
        subsystem_continuation_metadata = (
            request_cache.get("subsystem_continuation")
            if isinstance(request_cache.get("subsystem_continuation"), dict)
            else {}
        )
        if subsystem_continuation_metadata:
            planner_debug["subsystem_continuation"] = dict(subsystem_continuation_metadata)
            stage_timings["subsystem_continuation_created"] = (
                1.0 if subsystem_continuation_metadata.get("subsystem_continuation_created") else 0.0
            )
            stage_timings["direct_subsystem_async_converted"] = (
                1.0 if subsystem_continuation_metadata.get("direct_subsystem_async_converted") else 0.0
            )
            stage_timings["returned_before_subsystem_completion"] = (
                1.0 if subsystem_continuation_metadata.get("returned_before_subsystem_completion") else 0.0
            )
            stage_timings.setdefault(
                "inline_front_half_ms",
                float(subsystem_continuation_metadata.get("inline_front_half_ms") or 0.0),
            )
            response_metadata.update(
                {
                    **subsystem_continuation_metadata,
                    "subsystem_continuation": dict(subsystem_continuation_metadata),
                    "async_continuation": True,
                    "events_expected": True,
                    "completion_claimed": False,
                    "verification_claimed": False,
                }
            )
        if not fail_fast_reason:
            fail_fast_reason = self._fail_fast_reason_from_debug(planner_debug, planner_obedience)
        if fail_fast_reason:
            response_metadata["fail_fast_reason"] = fail_fast_reason
        if route_handler_subspans:
            response_metadata["route_handler_subspans"] = dict(route_handler_subspans)
            planner_debug["route_handler_subspans"] = dict(route_handler_subspans)
        _record_stage_ms(stage_timings, "response_compose_ms", response_started)
        _record_stage_ms(stage_timings, "response_serialization_ms", response_started)

        db_started = perf_counter()
        metadata_jobs = (
            jobs
            if resolved_response_profile == "deck_detail"
            else self._compact_jobs_for_profile(jobs, profile=resolved_response_profile)
        )
        metadata_actions = (
            actions
            if resolved_response_profile == "deck_detail"
            else self._compact_actions_for_profile(actions, profile=resolved_response_profile)
        )
        metadata_response = response_metadata
        metadata_planner_debug = planner_debug
        if resolved_response_profile != "deck_detail":
            metadata_response = self._compact_response_metadata(
                response_metadata,
                profile=resolved_response_profile,
                compact_jobs=metadata_jobs,
                compact_actions=metadata_actions,
            )
            metadata_planner_debug = self._compact_planner_debug(planner_debug, profile=resolved_response_profile)
        assistant_message = self.conversations.add_message(
            session_id,
            "assistant",
            assistant_text,
            metadata={
                "actions": metadata_actions,
                "jobs": metadata_jobs,
                "surface_mode": surface_mode,
                "active_module": active_module,
                "planner_debug": metadata_planner_debug,
                "response_profile": resolved_response_profile,
                "response_profile_reason": response_profile_reason,
                **metadata_response,
            },
        )
        _record_stage_ms(stage_timings, "db_write_ms", db_started)
        assistant_message.metadata["stage_timings_ms"] = dict(stage_timings)
        if route_handler_subspans:
            assistant_message.metadata["route_handler_subspans"] = dict(route_handler_subspans)
        planner_debug["stage_timings_ms"] = dict(stage_timings)
        message_planner_debug = (
            assistant_message.metadata.get("planner_debug")
            if isinstance(assistant_message.metadata.get("planner_debug"), dict)
            else {}
        )
        if isinstance(message_planner_debug, dict):
            message_planner_debug["stage_timings_ms"] = dict(stage_timings)
            if route_handler_subspans:
                message_planner_debug["route_handler_subspans"] = dict(route_handler_subspans)
        response_tail_started = perf_counter()
        event_snapshot_started = perf_counter()
        self.events.publish(
            event_family="runtime",
            event_type="runtime.assistant_response_ready",
            severity="info",
            subsystem="assistant",
            session_id=session_id,
            visibility_scope="internal_only",
            retention_class="bounded_recent",
            provenance={"channel": "assistant", "kind": "operator_summary"},
            message=f"Handled message in session '{session_id}'.",
            payload={
                "job_count": len(jobs),
                "action_count": len(actions),
                "surface_mode": surface_mode,
                "active_module": active_module,
            },
        )
        if planner_obedience:
            self.events.publish(
                event_family="runtime",
                event_type="runtime.planner_obedience_evaluated",
                severity="debug",
                subsystem="planner",
                session_id=session_id,
                visibility_scope="internal_only",
                retention_class="ephemeral",
                provenance={"channel": "planner", "kind": "heuristic_status"},
                message="Verified planner obedience for handled message.",
                payload={
                    "session_id": session_id,
                    "query_shape": str(planner_obedience.get("query_shape", "")),
                    "execution_plan_type": str(planner_obedience.get("execution_plan_type", "")),
                    "planned_tool_names": list(planner_obedience.get("planned_tool_names") or []),
                    "actual_tool_names": list(planner_obedience.get("actual_tool_names") or []),
                    "expected_response_mode": str(planner_obedience.get("expected_response_mode", "")),
                    "actual_result_mode": str(planner_obedience.get("actual_result_mode", "")),
                    "authority_enforced": bool(planner_obedience.get("authority_enforced", False)),
                    "compatibility_shim_used": bool(planner_obedience.get("compatibility_shim_used", False)),
                    "legacy_fallback_used": str(planner_obedience.get("legacy_fallback_used", "")),
                },
            )
        judgment_metadata = response_metadata.get("judgment") if isinstance(response_metadata.get("judgment"), dict) else {}
        next_suggestion = response_metadata.get("next_suggestion") if isinstance(response_metadata.get("next_suggestion"), dict) else {}
        if judgment_metadata or next_suggestion:
            self.events.publish(
                event_family="verification",
                event_type="verification.response_judgment",
                severity="debug",
                subsystem="judgment",
                session_id=session_id,
                visibility_scope="internal_only",
                retention_class="ephemeral",
                provenance={"channel": "judgment", "kind": "subsystem_interpretation"},
                message="Evaluated post-action judgment.",
                payload={
                    "session_id": session_id,
                    "risk_tier": str(judgment_metadata.get("risk_tier", "")),
                    "decision": str(judgment_metadata.get("decision", "")),
                    "suppressed_reason": str(judgment_metadata.get("suppressed_reason", "")),
                    "next_suggestion": dict(next_suggestion),
                },
            )
        _record_stage_ms(stage_timings, "event_job_snapshot_ms", event_snapshot_started)

        active_state_started = perf_counter()
        if command_eval_compact:
            active_request_state_payload = dict(active_request_state)
            recent_context_resolutions_payload = list(recent_context_resolutions)
            stage_timings["context_cache_hits"] += 1.0
        else:
            active_request_state_payload = self.session_state.get_active_request_state(session_id)
            recent_context_resolutions_payload = self.session_state.get_recent_context_resolutions(session_id)
        _record_stage_ms(stage_timings, "active_request_state_ms", active_state_started)
        active_task_payload = (
            self._compact_active_task_reference_from_turn(
                session_id=session_id,
                jobs=jobs,
                actions=actions,
                profile=resolved_response_profile,
            )
            if self.task_service is not None and resolved_response_profile == "command_eval_compact"
            else self.task_service.active_task_summary(session_id)
            if self.task_service is not None
            else {}
        )
        _record_stage_ms(stage_timings, "response_serialization_ms", response_tail_started)
        assistant_message.metadata["stage_timings_ms"] = dict(stage_timings)
        planner_debug["stage_timings_ms"] = dict(stage_timings)
        if isinstance(message_planner_debug, dict):
            message_planner_debug["stage_timings_ms"] = dict(stage_timings)
        response_payload = {
            "session_id": session_id,
            "user_message": user_message.to_dict(),
            "assistant_message": assistant_message.to_dict(),
            "job": jobs[0] if jobs else None,
            "jobs": jobs,
            "actions": actions,
            "active_request_state": active_request_state_payload,
            "recent_context_resolutions": recent_context_resolutions_payload,
            "active_task": active_task_payload,
        }
        compaction_started = perf_counter()
        response_payload = self._apply_response_profile(
            response_payload,
            profile=resolved_response_profile,
            reason=response_profile_reason,
        )
        _record_stage_ms(stage_timings, "payload_compaction_ms", compaction_started)
        stage_timings["total_latency_ms"] = round((perf_counter() - request_started) * 1000, 3)
        self._attach_stage_timings_to_response(
            response_payload,
            stage_timings,
            request_id=request_id,
            session_id=session_id,
            surface_mode=surface_mode,
            active_module=active_module,
            provider_called=provider_called,
            openai_called=openai_called,
            llm_called=llm_called,
            embedding_called=embedding_called,
        )
        self._publish_latency_posture_events(response_payload)
        return response_payload

    async def _execute_tool_requests(
        self,
        requests: list[ToolRequest] | list[ProviderToolCall],
        *,
        session_id: str,
        prompt: str,
        surface_mode: str,
        active_module: str,
        stage_timings: dict[str, float] | None = None,
        route_handler_subspans: dict[str, float] | None = None,
        response_profile: str = "deck_detail",
        request_cache: dict[str, Any] | None = None,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        tool_names = [
            request.tool_name if isinstance(request, ToolRequest) else request.name
            for request in requests
        ]
        routine_requested = any(name in {"routine_execute", "routine_save", "trusted_hook_execute", "trusted_hook_register"} for name in tool_names)
        direct_workspace_result = await self._maybe_execute_workspace_requests_directly(
            requests,
            session_id=session_id,
            prompt=prompt,
            surface_mode=surface_mode,
            active_module=active_module,
            response_profile=response_profile,
            request_cache=request_cache if request_cache is not None else {},
            stage_timings=stage_timings if stage_timings is not None else {},
        )
        if direct_workspace_result is not None:
            if route_handler_subspans is not None:
                _merge_route_subspans(route_handler_subspans, _subspans_from_direct_jobs(direct_workspace_result[1]))
            return direct_workspace_result
        if self._command_eval_dry_run_enabled(response_profile):
            inline_result = self._execute_command_eval_dry_run_inline(
                requests,
                session_id=session_id,
                route_handler_subspans=route_handler_subspans,
                stage_timings=stage_timings,
            )
            if inline_result is not None:
                return inline_result
        job_started = perf_counter()
        task_plan = None
        if self.task_service is not None:
            task_graph_started = perf_counter()
            task_plan = self.task_service.begin_execution(
                session_id=session_id,
                prompt=prompt,
                requests=requests,
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=self._workspace_summary_for_request(
                    session_id=session_id,
                    profile=response_profile,
                    request_cache=request_cache if request_cache is not None else {},
                    stage_timings=stage_timings if stage_timings is not None else {},
                )
                if self.workspace_service is not None
                else {},
            )
            if route_handler_subspans is not None:
                _add_route_subspan(
                    route_handler_subspans,
                    "routine_job_create_ms" if routine_requested else "task_graph_ms",
                    task_graph_started,
                )
        async_decision = self._async_route_decision_for_tool_requests(
            requests,
            surface_mode=surface_mode,
            active_module=active_module,
        )
        job_create_started = perf_counter()
        submitted_jobs = await asyncio.gather(
            *[
                self.jobs.submit(
                    request.tool_name if isinstance(request, ToolRequest) else request.name,
                    request.arguments,
                    session_id=session_id,
                    task_id=task_plan.task_id if task_plan is not None else None,
                    task_step_id=task_plan.step_ids[index] if task_plan is not None and index < len(task_plan.step_ids) else None,
                    priority_lane=async_decision.preferred_worker_lane,
                    priority_level=async_decision.priority_level,
                    interactive_deadline_ms=async_decision.interactive_deadline_ms,
                    background_ok=async_decision.background_ok,
                    operator_visible=async_decision.operator_visible,
                    can_yield=async_decision.can_yield,
                    starvation_sensitive=async_decision.starvation_sensitive,
                    route_family=async_decision.route_family,
                    subsystem=async_decision.subsystem,
                    safe_for_verification=async_decision.verification_worker_allowed,
                )
                for index, request in enumerate(requests)
            ]
        )
        if route_handler_subspans is not None:
            _add_route_subspan(
                route_handler_subspans,
                "routine_job_create_ms" if routine_requested else "job_create_ms",
                job_create_started,
            )
        if (
            async_decision.should_return_initial_response
            and async_decision.should_create_job
            and all(isinstance(request, ToolRequest) for request in requests)
        ):
            initial_started = perf_counter()
            initial_jobs = [self._initial_async_job_reference(job) for job in submitted_jobs]
            worker_status = self.jobs.worker_status_snapshot()
            first_job_timing = (
                initial_jobs[0].get("job_timing_summary")
                if initial_jobs and isinstance(initial_jobs[0].get("job_timing_summary"), dict)
                else {}
            )
            progress_state = RouteProgressState.create(
                request_id=f"async-{submitted_jobs[0].job_id if submitted_jobs else uuid4().hex}",
                session_id=session_id,
                route_family=async_decision.route_family,
                subsystem=async_decision.subsystem,
                stage=RouteProgressStage.QUEUED,
                message=self._async_initial_message(async_decision, initial_jobs),
                progress_label="Queued",
                verification_state="verification_pending" if async_decision.verification_required else "not_verified",
                task_id=initial_jobs[0].get("task_id") if initial_jobs else None,
                job_id=initial_jobs[0].get("job_id") if initial_jobs else None,
                budget_label=async_decision.budget_label,
                execution_mode=async_decision.execution_mode,
                worker_lane=async_decision.preferred_worker_lane,
                priority_level=async_decision.priority_level,
                queue_wait_ms=first_job_timing.get("queue_wait_ms") if isinstance(first_job_timing, dict) else None,
                worker_index=initial_jobs[0].get("worker_index") if initial_jobs else None,
                worker_state=str(worker_status.get("starvation_state") or ""),
                job_timing_summary=first_job_timing if isinstance(first_job_timing, dict) else {},
                starvation_warning=bool(worker_status.get("starvation_detected")),
                debug={"tool_names": tool_names},
            )
            for job in submitted_jobs:
                self.jobs.update_job_worker_metadata(
                    job.job_id,
                    continuation_id=progress_state.continuation_id,
                    route_family=async_decision.route_family,
                    subsystem=async_decision.subsystem,
                )
            handle = AsyncRouteHandle(
                continuation_id=progress_state.continuation_id,
                request_id=progress_state.request_id,
                session_id=session_id,
                route_family=async_decision.route_family,
                subsystem=async_decision.subsystem,
                task_id=progress_state.task_id,
                job_id=progress_state.job_id,
                async_strategy=async_decision.async_strategy.value,
                progress_stage=progress_state.stage.value,
                events_expected=True,
                worker_lane=async_decision.preferred_worker_lane,
                priority_level=async_decision.priority_level,
                queue_wait_ms=progress_state.queue_wait_ms,
                worker_index=progress_state.worker_index,
                worker_state=progress_state.worker_state,
                job_timing_summary=progress_state.job_timing_summary,
                starvation_warning=progress_state.starvation_warning,
            )
            async_payload = {
                **async_decision.to_dict(),
                "async_initial_response_returned": True,
                "route_progress_stage": progress_state.stage.value,
                "route_progress_status": progress_state.status.value,
                "route_continuation_id": progress_state.continuation_id,
                "async_route_handle": handle.to_dict(),
                "progress_state": progress_state.to_dict(),
                "job_required": async_decision.should_create_job,
                "task_required": async_decision.should_create_task,
                "event_progress_required": async_decision.should_publish_progress_events,
                "worker_lane": async_decision.preferred_worker_lane,
                "worker_priority": async_decision.priority_level,
                "queue_depth_at_submit": int(worker_status.get("queue_depth") or 0),
                "queue_wait_ms": float(progress_state.queue_wait_ms or 0.0),
                "worker_index": progress_state.worker_index,
                "worker_state": progress_state.worker_state,
                "worker_capacity": int(worker_status.get("worker_capacity") or 0),
                "workers_busy_at_submit": int(worker_status.get("workers_busy") or 0),
                "workers_idle_at_submit": int(worker_status.get("workers_idle") or 0),
                "worker_saturation_percent": float(worker_status.get("worker_saturation_percent") or 0.0),
                "interactive_jobs_waiting": int(worker_status.get("interactive_jobs_waiting") or 0),
                "background_jobs_running": int(worker_status.get("background_jobs_running") or 0),
                "background_job_count": int(worker_status.get("background_job_count") or 0),
                "interactive_job_count": int(worker_status.get("interactive_job_count") or 0),
                "starvation_detected": bool(worker_status.get("starvation_detected")),
                "async_worker_utilization_summary": worker_status,
            }
            if request_cache is not None:
                request_cache["async_route"] = async_payload
            if stage_timings is not None:
                stage_timings["async_initial_response_returned"] = 1.0
                stage_timings["job_wait_ms"] = 0.0
            if route_handler_subspans is not None:
                _add_route_subspan(route_handler_subspans, "async_initial_response_ms", initial_started)
            self._publish_async_route_event(
                event_type="route.async_continuation_started",
                session_id=session_id,
                payload={
                    "request_id": progress_state.request_id,
                    "session_id": session_id,
                    "route_family": async_decision.route_family,
                    "subsystem": async_decision.subsystem,
                    "result_state": progress_state.result_state,
                    "budget_label": async_decision.budget_label,
                    "execution_mode": async_decision.execution_mode,
                    "async_strategy": async_decision.async_strategy.value,
                    "async_continuation": True,
                    "job_id": progress_state.job_id,
                    "task_id": progress_state.task_id,
                    "continuation_id": progress_state.continuation_id,
                    "priority_lane": async_decision.preferred_worker_lane,
                    "priority_level": async_decision.priority_level,
                    "worker_lane": async_decision.preferred_worker_lane,
                    "worker_priority": async_decision.priority_level,
                    "queue_depth_at_submit": int(worker_status.get("queue_depth") or 0),
                    "worker_saturation_percent": float(worker_status.get("worker_saturation_percent") or 0.0),
                    "starvation_detected": bool(worker_status.get("starvation_detected")),
                    "completion_claimed": False,
                    "verification_claimed": False,
                },
            )
            if stage_timings is not None:
                _record_stage_ms(stage_timings, "job_collection_ms", job_started)
            return self.persona.report(progress_state.message), initial_jobs, []
        job_wait_started = perf_counter()
        completed_jobs = await asyncio.gather(*[self.jobs.wait(job.job_id) for job in submitted_jobs])
        if route_handler_subspans is not None:
            _add_route_subspan(
                route_handler_subspans,
                "routine_job_wait_ms" if routine_requested else "job_wait_ms",
                job_wait_started,
            )
            if routine_requested:
                _merge_route_subspans(route_handler_subspans, _subspans_from_jobs(completed_jobs))
        if stage_timings is not None:
            _record_stage_ms(stage_timings, "job_collection_ms", job_started)
        actions: list[dict[str, Any]] = []
        summaries: list[str] = []

        for job in completed_jobs:
            if isinstance(job.result, dict):
                summaries.append(str(job.result.get("summary") or ""))
                data = job.result.get("data")
                if isinstance(data, dict):
                    action = data.get("action")
                    if isinstance(action, dict):
                        actions.append(action)
                    action_list = data.get("actions")
                    if isinstance(action_list, list):
                        actions.extend(item for item in action_list if isinstance(item, dict))
            elif job.error:
                summaries.append(job.error)

            if isinstance(job.result, dict):
                self.session_state.remember_tool_result(
                    session_id,
                    tool_name=job.tool_name,
                    arguments=job.arguments,
                    result=job.result,
                    captured_at=job.finished_at or job.created_at,
                )

        if self.workspace_service is not None:
            self.workspace_service.remember_actions(
                session_id=session_id,
                prompt=prompt,
                actions=actions,
                surface_mode=surface_mode,
                active_module=active_module,
            )
        assistant_text = self.persona.report(self._merge_job_summaries(completed_jobs, summaries))
        return assistant_text, [job.to_dict() for job in completed_jobs], actions

    def _async_route_decision_for_tool_requests(
        self,
        requests: list[ToolRequest] | list[ProviderToolCall],
        *,
        surface_mode: str,
        active_module: str,
    ) -> Any:
        if not requests or not all(isinstance(request, ToolRequest) for request in requests):
            return classify_async_route_policy(route_family="unknown")
        tool_names = [str(request.tool_name or "") for request in requests]
        primary_tool_name = tool_names[0] if tool_names else ""
        route_family = _direct_route_family(primary_tool_name) or "tool_execution"
        subsystem = _direct_route_subsystem(route_family, primary_tool_name) or route_family
        tool_execution_mode = ""
        try:
            tool = self.tool_registry.get(primary_tool_name)
            tool_execution_mode = str(getattr(getattr(tool, "execution_mode", ""), "value", "") or "")
        except KeyError:
            tool = None

        latency_policy = classify_route_latency_policy(
            route_family=route_family,
            subsystem=subsystem,
            request_kind=primary_tool_name,
            surface_mode=surface_mode,
            active_module=active_module,
        )
        return classify_async_route_policy(
            route_family=route_family,
            subsystem=subsystem,
            execution_mode=latency_policy.execution_mode.value,
            budget_label=latency_policy.budget.label,
            request_stage=primary_tool_name,
            surface_mode=surface_mode,
            active_module=active_module,
            fail_fast_reason=latency_policy.fail_fast_reason,
            tool_execution_mode=tool_execution_mode,
            verification_posture="verification_required"
            if route_family in {"software_control", "software_recovery", "screen_awareness", "file_operation"}
            else "",
        )

    def _initial_async_job_reference(self, job: Any) -> dict[str, Any]:
        payload = job.to_dict() if hasattr(job, "to_dict") else {}
        return {
            "job_id": str(payload.get("job_id") or ""),
            "tool_name": str(payload.get("tool_name") or ""),
            "status": str(payload.get("status") or ""),
            "task_id": str(payload.get("task_id") or "") or None,
            "task_step_id": str(payload.get("task_step_id") or "") or None,
            "priority_lane": str(payload.get("priority_lane") or ""),
            "priority_level": str(payload.get("priority_level") or ""),
            "worker_lane": str(payload.get("worker_lane") or ""),
            "worker_priority": str(payload.get("worker_priority") or ""),
            "worker_index": payload.get("worker_index"),
            "queue_wait_ms": payload.get("queue_wait_ms"),
            "job_run_ms": payload.get("job_run_ms"),
            "job_total_ms": payload.get("job_total_ms"),
            "job_timing_summary": dict(payload.get("job_timing_summary") or {}),
            "result": None,
            "error": str(payload.get("error") or ""),
        }

    def _async_initial_message(
        self,
        decision: Any,
        jobs: list[dict[str, Any]],
    ) -> str:
        tool_name = str(jobs[0].get("tool_name") or "work") if jobs else "work"
        route_family = str(getattr(decision, "route_family", "") or "route")
        if getattr(decision, "async_strategy", AsyncRouteStrategy.NONE) == AsyncRouteStrategy.CREATE_JOB_AND_TASK:
            return f"Queued {route_family} work. I will keep progress visible while it runs."
        return f"Queued {tool_name}. I will keep progress visible while it runs."

    def _publish_async_route_event(
        self,
        *,
        event_type: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> None:
        self.events.publish(
            event_family="route",
            event_type=event_type,
            severity="info",
            subsystem=str(payload.get("subsystem") or "route"),
            session_id=session_id,
            subject=str(payload.get("continuation_id") or payload.get("job_id") or ""),
            visibility_scope="watch_surface",
            retention_class="bounded_recent",
            provenance={"channel": "assistant", "kind": "route_progress"},
            message="Route async continuation started.",
            payload=self._compact_value(payload, profile="ghost_compact"),
        )

    def _execute_command_eval_dry_run_inline(
        self,
        requests: list[ToolRequest] | list[ProviderToolCall],
        *,
        session_id: str,
        route_handler_subspans: dict[str, float] | None,
        stage_timings: dict[str, float] | None,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]] | None:
        if not requests:
            return None
        started = perf_counter()
        jobs: list[dict[str, Any]] = []
        summaries: list[str] = []
        for index, request in enumerate(requests):
            tool_name = request.tool_name if isinstance(request, ToolRequest) else request.name
            arguments = dict(request.arguments)
            job_id = f"inline-dry-run-{uuid4().hex[:12]}"
            created_at = utc_now_iso()
            subspans: dict[str, float] = {"dry_run_plan_ms": 0.0}
            result: dict[str, Any]
            status = "completed"
            error = ""
            plan_started = perf_counter()
            try:
                lookup_started = perf_counter()
                tool = self.tool_registry.get(tool_name)
                _add_route_subspan(subspans, "dry_run_tool_lookup_ms", lookup_started)
                validate_started = perf_counter()
                validated_arguments = tool.validate(arguments)
                assessment = tool.adapter_route_assessment(validated_arguments)
                _add_route_subspan(subspans, "dry_run_argument_validation_ms", validate_started)
                if assessment.contract_required and not assessment.healthy:
                    status = "failed"
                    error = "adapter_contract_blocked"
                    summary = (
                        f"Dry-run blocked: {tool.display_name} is not valid contract-backed adapter work. "
                        "No external action was performed."
                    )
                    result = {
                        "success": False,
                        "summary": summary,
                        "error": error,
                        "data": {
                            "dry_run": True,
                            "dry_run_compact": True,
                            "detail_load_deferred": True,
                            "adapter_contract_status": assessment.to_dict(),
                            "tool_name": tool.name,
                            "dry_run_executor_ms": round((perf_counter() - plan_started) * 1000, 3),
                            "route_handler_subspans": dict(subspans),
                        },
                        "adapter_contract": {},
                        "adapter_execution": {},
                    }
                else:
                    contract = assessment.selected_contract
                    execution = (
                        build_execution_report(
                            contract,
                            success=True,
                            observed_outcome=ClaimOutcome.PREVIEW,
                            evidence=["Compact dry-run validated the route and suppressed execution."],
                            verification_observed="dry_run",
                        ).to_dict()
                        if contract is not None
                        else {
                            "adapter_id": "",
                            "success": True,
                            "claim_ceiling": "preview",
                            "approval_required": False,
                            "preview_required": False,
                            "rollback_available": False,
                            "evidence": ["Compact dry-run validated the tool call and suppressed execution."],
                            "verification_observed": "dry_run",
                            "failure_kind": None,
                        }
                    )
                    summary = f"Dry-run only: would execute {tool.display_name}. No external action was performed."
                    result = {
                        "success": True,
                        "summary": summary,
                        "error": None,
                        "data": {
                            "dry_run": True,
                            "dry_run_compact": True,
                            "detail_load_deferred": True,
                            "tool_name": tool.name,
                            "display_name": tool.display_name,
                            "classification": tool.classification.value,
                            "execution_mode": tool.execution_mode.value,
                            "validated_arguments": validated_arguments,
                            "adapter_contract_status": assessment.to_dict(),
                            "approval_required": bool(contract and contract.approval.required),
                            "preview_required": bool(contract and contract.approval.preview_required),
                            "dry_run_executor_ms": round((perf_counter() - plan_started) * 1000, 3),
                            "route_handler_subspans": dict(subspans),
                        },
                        "adapter_contract": contract.to_dict() if contract is not None else {},
                        "adapter_execution": execution,
                    }
            except Exception as exc:
                status = "failed"
                error = str(exc)
                summary = f"Dry-run failed before '{tool_name}' could be validated. No external action was performed."
                result = {
                    "success": False,
                    "summary": summary,
                    "error": error,
                    "data": {
                        "dry_run": True,
                        "dry_run_compact": True,
                        "detail_load_deferred": True,
                        "tool_name": tool_name,
                        "dry_run_executor_ms": round((perf_counter() - plan_started) * 1000, 3),
                        "route_handler_subspans": dict(subspans),
                    },
                    "adapter_contract": {},
                    "adapter_execution": {},
                }
            _add_route_subspan(subspans, "dry_run_plan_ms", plan_started)
            if isinstance(result.get("data"), dict):
                result["data"]["route_handler_subspans"] = dict(subspans)
                result["data"]["dry_run_executor_ms"] = round((perf_counter() - plan_started) * 1000, 3)
            if route_handler_subspans is not None:
                _merge_route_subspans(route_handler_subspans, subspans)
            finished_at = utc_now_iso()
            job = {
                "job_id": job_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "status": status,
                "created_at": created_at,
                "started_at": created_at,
                "finished_at": finished_at,
                "task_id": "",
                "task_step_id": "",
                "result": result,
                "error": error,
            }
            jobs.append(job)
            summaries.append(summary)
            self.session_state.remember_tool_result(
                session_id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                captured_at=finished_at,
            )
            del index
        elapsed = round((perf_counter() - started) * 1000, 3)
        if stage_timings is not None:
            stage_timings["dry_run_plan_ms"] = round(float(stage_timings.get("dry_run_plan_ms", 0.0)) + elapsed, 3)
            stage_timings["detail_load_deferred"] = 1.0
        return self.persona.report(" ".join(summaries).strip()), jobs, []

    async def _run_reasoner_summary(
        self,
        *,
        message: str,
        session_id: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
        active_context: dict[str, Any] | None,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
    ) -> str:
        if self.provider is None or not self.config.openai.enabled:
            return self.persona.report(self._merge_job_summaries([], [action.get("type", "") for action in actions]))
        reasoning_response = await self.provider.generate(
            instructions=self._build_provider_instructions(
                role="reasoner",
                surface_mode=surface_mode,
                active_module=active_module,
                workspace_context=workspace_context,
            ),
            input_items=self._build_reasoning_payload(
                session_id=session_id,
                message=message,
                jobs=jobs,
                actions=actions,
                workspace_context=workspace_context,
                active_context=active_context,
            ),
            previous_response_id=self.session_state.get_previous_response_id(session_id, role="reasoner"),
            tools=[],
            model=self.config.openai.reasoning_model,
            max_output_tokens=self.config.openai.reasoning_max_output_tokens,
        )
        if reasoning_response.response_id:
            self.session_state.set_previous_response_id(session_id, reasoning_response.response_id, role="reasoner")
        if reasoning_response.output_text:
            return self.persona.report(reasoning_response.output_text)
        return self.persona.report(self._merge_job_summaries([], [action.get("type", "") for action in actions]))

    async def _maybe_apply_browser_search_fallback(
        self,
        *,
        planned: PlannerDecision,
        message: str,
        session_id: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
        active_context: dict[str, Any] | None,
    ) -> PlannerDecision:
        del session_id, message, surface_mode, active_module, workspace_context, active_context
        if self.provider is None or not self.config.openai.enabled:
            return planned
        if planned.structured_query is None or planned.execution_plan is None:
            return planned
        if planned.structured_query.query_shape.value != "search_browser_destination":
            return planned
        if planned.request_type != "browser_search" or planned.tool_requests:
            return planned
        slots = planned.structured_query.slots if isinstance(planned.structured_query.slots, dict) else {}
        if str(slots.get("browser_search_failure_reason") or "").strip() != "search_provider_unresolved":
            return planned
        if not planned.assistant_message:
            return planned

        provider_phrase = str(
            slots.get("search_provider")
            or slots.get("requested_search_provider_phrase")
            or slots.get("browser_search_request", {}).get("provider_phrase")
            or ""
        ).strip()
        search_query = str(slots.get("search_query") or "").strip()
        browser_target = str(slots.get("browser_preference") or "").strip()
        open_target = str(slots.get("open_target") or "external").strip() or "external"
        fallback_model = self._browser_search_fallback_model()
        fallback_metadata: dict[str, Any] = {
            "attempted": True,
            "used": False,
            "model": fallback_model,
            "provider_phrase": provider_phrase,
        }

        result = await self.provider.generate(
            instructions=(
                "Resolve an unresolved browser-search provider into one credible http or https URL. "
                "Return exactly one browser_search_fallback_resolve function call. "
                "Prefer a native search URL when obvious; otherwise return a Google site: search URL. "
                "If no credible URL can be inferred, return resolved_url as an empty string."
            ),
            input_items=json.dumps(
                {
                    "provider_phrase": provider_phrase,
                    "search_query": search_query,
                    "browser_target": browser_target,
                    "open_target": open_target,
                }
            ),
            previous_response_id=None,
            tools=[self._browser_search_fallback_tool_definition()],
            model=fallback_model,
            max_output_tokens=self.config.openai.planner_max_output_tokens,
        )

        tool_call = next((call for call in result.tool_calls if call.name == "browser_search_fallback_resolve"), None)
        if tool_call is None:
            fallback_metadata["failure"] = "no_tool_call"
            slots["browser_search_fallback"] = fallback_metadata
            self._refresh_planned_debug(planned)
            return planned

        arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
        resolved_url = str(arguments.get("resolved_url") or "").strip()
        if not self._is_http_url(resolved_url):
            fallback_metadata["failure"] = "invalid_url"
            fallback_metadata["reason"] = str(arguments.get("reason") or "").strip()
            slots["browser_search_fallback"] = fallback_metadata
            self._refresh_planned_debug(planned)
            return planned

        title = str(arguments.get("title") or self._default_browser_search_title(provider_phrase)).strip()
        resolution_kind = str(arguments.get("resolution_kind") or "fallback_url").strip() or "fallback_url"
        fallback_provider_phrase = str(arguments.get("provider_phrase") or provider_phrase).strip() or provider_phrase
        reason = str(arguments.get("reason") or "").strip()
        resolver = getattr(self.planner, "_browser_destination_resolver", None)
        if resolver is not None and hasattr(resolver, "response_contract_for_search_title"):
            response_contract = resolver.response_contract_for_search_title(title, open_target=open_target)
        else:
            if open_target == "deck":
                response_contract = {
                    "bearing_title": f"{title} queued",
                    "micro_response": f"Queued {title} for the Deck browser.",
                    "full_response": f"Queued {title} for the Deck browser.",
                }
            else:
                response_contract = {
                    "bearing_title": f"{title} requested",
                    "micro_response": f"Requested that {title} open externally.",
                    "full_response": f"Requested that {title} open externally.",
                }
        tool_name = "deck_open_url" if open_target == "deck" else "external_open_url"
        tool_arguments: dict[str, Any] = {
            "url": resolved_url,
            "label": title,
            "response_contract": dict(response_contract),
        }
        if tool_name == "external_open_url" and browser_target and browser_target != "default":
            tool_arguments["browser_target"] = browser_target

        planned.tool_requests = [ToolRequest(tool_name, dict(tool_arguments))]
        planned.assistant_message = None
        planned.execution_plan.tool_name = tool_name
        planned.execution_plan.tool_arguments = dict(tool_arguments)
        planned.execution_plan.assistant_message = None

        slots["response_contract"] = dict(response_contract)
        slots["browser_open_plan"] = {
            "tool_name": tool_name,
            "tool_arguments": dict(tool_arguments),
            "response_contract": dict(response_contract),
            "open_target": open_target,
        }
        slots["browser_search_fallback"] = {
            **fallback_metadata,
            "used": True,
            "resolution_kind": resolution_kind,
            "provider_phrase": fallback_provider_phrase,
            "resolved_url": resolved_url,
            "reason": reason,
        }

        if hasattr(self.planner, "_active_request_state_from_structured_query"):
            planned.active_request_state = self.planner._active_request_state_from_structured_query(
                planned.structured_query,
                planned.execution_plan,
            )
        self._refresh_planned_debug(planned)
        return planned

    def _browser_search_fallback_model(self) -> str:
        return "gpt-5.4-nano"

    def _browser_search_fallback_tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": "browser_search_fallback_resolve",
            "description": "Resolve a browser-search provider phrase into a credible URL to open.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resolved_url": {"type": "string"},
                    "title": {"type": "string"},
                    "resolution_kind": {"type": "string"},
                    "provider_phrase": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["resolved_url", "title", "resolution_kind", "provider_phrase", "reason"],
                "additionalProperties": False,
            },
        }

    def _planner_debug_provider_fallback_attempted(self, planner_debug: dict[str, Any]) -> bool:
        return self._nested_debug_flag(planner_debug, "browser_search_fallback", "attempted")

    def _fail_fast_reason_from_debug(
        self,
        planner_debug: dict[str, Any],
        planner_obedience: dict[str, Any],
    ) -> str:
        unsupported = planner_debug.get("unsupported_reason") if isinstance(planner_debug, dict) else {}
        if isinstance(unsupported, dict) and unsupported.get("code"):
            return str(unsupported.get("code") or "").strip()
        if str(planner_obedience.get("expected_response_mode") or "").strip() == "unsupported":
            return "unsupported_route"
        return ""

    def _nested_debug_flag(self, value: Any, match_key: str, child_key: str) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key) == match_key and isinstance(item, dict) and bool(item.get(child_key)):
                    return True
                if self._nested_debug_flag(item, match_key, child_key):
                    return True
        elif isinstance(value, list):
            return any(self._nested_debug_flag(item, match_key, child_key) for item in value)
        return False

    def _refresh_planned_debug(self, planned: PlannerDecision) -> None:
        if planned.structured_query is not None:
            planned.debug["structured_query"] = planned.structured_query.to_dict()
        if planned.execution_plan is not None:
            planned.debug["execution_plan"] = planned.execution_plan.to_dict()

    def _default_browser_search_title(self, provider_phrase: str) -> str:
        phrase = " ".join(str(provider_phrase or "").split()).strip()
        if not phrase:
            return "Search"
        if "." in phrase:
            return f"{phrase} search"
        return f"{phrase[:1].upper()}{phrase[1:]} search"

    def _is_http_url(self, candidate: str) -> bool:
        parsed = urlparse(str(candidate or "").strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    async def _handle_provider_turn(
        self,
        *,
        message: str,
        session_id: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
        active_context: dict[str, Any] | None,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        tool_definitions = [
            tool.response_tool_definition()
            for tool in self.tool_registry.all_tools()
            if self.config.tools.enabled.is_enabled(tool.name)
        ]
        resolved_workspace_context = workspace_context or (
            self.workspace_service.active_workspace_summary(session_id) if self.workspace_service is not None else {}
        )
        instructions = self._build_provider_instructions(
            role="planner",
            surface_mode=surface_mode,
            active_module=active_module,
            workspace_context=resolved_workspace_context,
        )
        previous_response_id = self.session_state.get_previous_response_id(session_id, role="planner")
        input_items: str | list[dict[str, Any]] = self._build_provider_input_items(
            session_id=session_id,
            message=message,
            active_context=active_context,
        )
        initial_context_items = list(input_items) if isinstance(input_items, list) else []
        all_actions: list[dict[str, Any]] = []
        all_jobs: list[dict[str, Any]] = []
        final_text = ""
        latest_response_id = previous_response_id

        for _ in range(max(1, self.config.openai.max_tool_rounds)):
            result = await self.provider.generate(
                instructions=instructions,
                input_items=input_items,
                previous_response_id=previous_response_id,
                tools=tool_definitions,
                model=self.config.openai.planner_model,
                max_output_tokens=self.config.openai.planner_max_output_tokens,
            )
            latest_response_id = result.response_id or latest_response_id
            if result.output_text:
                final_text = result.output_text

            if not result.tool_calls:
                break

            tool_text, jobs, actions = await self._execute_tool_requests(
                result.tool_calls,
                session_id=session_id,
                prompt=message,
                surface_mode=surface_mode,
                active_module=active_module,
            )
            all_jobs.extend(jobs)
            all_actions.extend(actions)
            function_outputs = [
                {
                    "type": "function_call_output",
                    "call_id": tool_call.call_id,
                    "output": json.dumps(job.get("result") or {"success": False, "error": job.get("error", "unknown_tool_failure")}),
                }
                for tool_call, job in zip(result.tool_calls, jobs, strict=False)
            ]
            input_items = [*initial_context_items, *function_outputs] if initial_context_items else function_outputs
            previous_response_id = result.response_id
            if not final_text:
                final_text = tool_text
        else:
            if not final_text:
                final_text = self.persona.report("Stormhelm reached the current tool round limit before finalizing a response.")

        self.session_state.set_previous_response_id(session_id, latest_response_id, role="planner")
        if self.planner.should_escalate(message, tool_job_count=len(all_jobs), actions=all_actions, planner_text=final_text):
            reasoning_response = await self.provider.generate(
                instructions=self._build_provider_instructions(
                    role="reasoner",
                    surface_mode=surface_mode,
                    active_module=active_module,
                    workspace_context=resolved_workspace_context,
                ),
                input_items=self._build_reasoning_payload(
                    session_id=session_id,
                    message=message,
                    jobs=all_jobs,
                    actions=all_actions,
                    workspace_context=resolved_workspace_context,
                    active_context=active_context,
                ),
                previous_response_id=self.session_state.get_previous_response_id(session_id, role="reasoner"),
                tools=[],
                model=self.config.openai.reasoning_model,
                max_output_tokens=self.config.openai.reasoning_max_output_tokens,
            )
            if reasoning_response.response_id:
                self.session_state.set_previous_response_id(
                    session_id,
                    reasoning_response.response_id,
                    role="reasoner",
                )
            if reasoning_response.output_text:
                final_text = reasoning_response.output_text
        if not final_text:
            final_text = self._merge_job_summaries([], [action.get("type", "") for action in all_actions]) or "Standing by."
        return self.persona.report(final_text), all_jobs, all_actions

    def _build_provider_instructions(
        self,
        *,
        role: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None,
    ) -> str:
        instructions = self.persona.build_provider_instructions(
            role=role,
            surface_mode=surface_mode,
            active_module=active_module,
            workspace_context=workspace_context,
        )
        dynamic_rules = [
            "Use deck_open_url and deck_open_file when the operator explicitly asks to open content inside Stormhelm or when the current surface is Deck.",
            "Use external_open_url and external_open_file when Ghost is active unless the operator explicitly asks for internal Deck viewing.",
            "Stormhelm's own bounded 8-worker scheduler is the authority for concurrency, timeouts, cancellation, and result merging.",
            "You may request multiple specialized tools in one response when that materially improves the result.",
            "Keep visible replies concise and information-dense.",
        ]
        return "\n\n".join(part for part in [instructions, "\n".join(dynamic_rules)] if part)

    def _build_reasoning_payload(
        self,
        *,
        session_id: str,
        message: str,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        workspace_context: dict[str, Any] | None,
        active_context: dict[str, Any] | None,
    ) -> str:
        payload = {
            "previous_user_message": self._previous_user_message(session_id=session_id, current_message=message),
            "operator_message": message,
            "workspace_context": workspace_context or {},
            "active_context": active_context or {},
            "tool_jobs": jobs,
            "actions": actions,
        }
        return json.dumps(payload)

    def _build_provider_input_items(
        self,
        *,
        session_id: str,
        message: str,
        active_context: dict[str, Any] | None,
    ) -> str | list[dict[str, Any]]:
        current_message = (message or "").strip()
        previous_user_message = self._previous_user_message(session_id=session_id, current_message=current_message)
        context_items = self._build_context_input_items(active_context)
        if not previous_user_message and not context_items:
            return current_message
        items: list[dict[str, Any]] = []
        if previous_user_message:
            items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Previous user message: {previous_user_message}",
                        }
                    ],
                }
            )
        items.extend(context_items)
        items.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": current_message,
                    }
                ],
            }
        )
        return items

    def _build_context_input_items(self, active_context: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(active_context, dict):
            return []
        items: list[dict[str, Any]] = []
        for source_name in ("selection", "clipboard"):
            descriptor = active_context.get(source_name)
            if not isinstance(descriptor, dict):
                continue
            value = descriptor.get("value")
            if value in (None, ""):
                continue
            kind = str(descriptor.get("kind") or "text").strip() or "text"
            items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Resolved context source: {source_name} ({kind})\n{value}",
                        }
                    ],
                }
            )
        return items

    def _previous_user_message(self, *, session_id: str, current_message: str) -> str | None:
        list_messages = getattr(self.conversations, "list_messages", None)
        if not callable(list_messages):
            return None
        try:
            messages = list_messages(session_id=session_id, limit=8)
        except Exception:
            return None
        user_messages: list[str] = []
        for record in messages:
            role = getattr(record, "role", None)
            content = getattr(record, "content", None)
            if role != "user":
                continue
            normalized = " ".join(str(content or "").split()).strip()
            if normalized:
                user_messages.append(normalized)
        if not user_messages:
            return None
        current_normalized = " ".join(current_message.split()).strip()
        if len(user_messages) >= 2 and user_messages[-1] == current_normalized:
            return user_messages[-2]
        if user_messages[-1] != current_normalized:
            return user_messages[-1]
        return None

    def _merge_job_summaries(self, completed_jobs: list[dict[str, Any]] | list[Any], summaries: list[str]) -> str:
        cleaned = [summary.strip() for summary in summaries if summary and summary.strip()]
        if cleaned:
            if len(cleaned) == 1:
                return cleaned[0]
            return " ".join(cleaned[:2])
        if completed_jobs:
            return "Stormhelm completed the requested work."
        return "Standing by."

    def _build_response_metadata(
        self,
        *,
        text: str,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        active_module: str,
        judgment: dict[str, Any] | None = None,
        planner_obedience: dict[str, Any] | None = None,
        planned_decision: PlannerDecision | None = None,
    ) -> dict[str, Any]:
        planner_contract = self._planner_response_contract(planned_decision)
        action_contract = next(
            (
                action
                for action in actions
                if isinstance(action, dict)
                and (
                    action.get("bearing_title")
                    or action.get("micro_response")
                    or action.get("full_response")
                )
            ),
            planner_contract,
        )
        full_response = str(action_contract.get("full_response") or self.persona.report(text)).strip()
        metadata: dict[str, Any] = {
            "bearing_title": str(
                action_contract.get("bearing_title")
                or self._bearing_title(jobs=jobs, actions=actions, active_module=active_module, text=full_response)
            ).strip(),
            "micro_response": str(action_contract.get("micro_response") or self._micro_response(full_response)).strip(),
            "full_response": full_response,
        }
        action_adapter_contract = action_contract.get("adapter_contract")
        action_adapter_execution = action_contract.get("adapter_execution")
        job_adapter_contract = next(
            (
                (job.get("result") or {}).get("adapter_contract")
                for job in jobs
                if isinstance(job, dict)
                and isinstance(job.get("result"), dict)
                and isinstance((job.get("result") or {}).get("adapter_contract"), dict)
            ),
            {},
        )
        job_adapter_execution = next(
            (
                (job.get("result") or {}).get("adapter_execution")
                for job in jobs
                if isinstance(job, dict)
                and isinstance(job.get("result"), dict)
                and isinstance((job.get("result") or {}).get("adapter_execution"), dict)
            ),
            {},
        )
        if isinstance(action_adapter_contract, dict):
            metadata["adapter_contract"] = dict(action_adapter_contract)
        elif isinstance(job_adapter_contract, dict) and job_adapter_contract:
            metadata["adapter_contract"] = dict(job_adapter_contract)
        elif (
            planned_decision is not None
            and planned_decision.capability_plan is not None
            and isinstance(planned_decision.capability_plan.selected_adapter, dict)
        ):
            metadata["adapter_contract"] = dict(planned_decision.capability_plan.selected_adapter)
        if isinstance(action_adapter_execution, dict):
            metadata["adapter_execution"] = dict(action_adapter_execution)
        elif isinstance(job_adapter_execution, dict) and job_adapter_execution:
            metadata["adapter_execution"] = dict(job_adapter_execution)
        elif (
            planned_decision is not None
            and planned_decision.capability_plan is not None
            and planned_decision.capability_plan.max_claimable_outcome
        ):
            metadata["adapter_execution"] = {
                "claim_ceiling": planned_decision.capability_plan.max_claimable_outcome,
                "approval_required": planned_decision.capability_plan.approval_required,
                "preview_required": False,
                "rollback_available": planned_decision.capability_plan.rollback_available,
            }
        if (
            planned_decision is not None
            and planned_decision.capability_plan is not None
            and planned_decision.capability_plan.candidate_adapters
        ):
            metadata["candidate_adapters"] = list(planned_decision.capability_plan.candidate_adapters)
        judgment = judgment or {}
        next_suggestion = judgment.get("next_suggestion")
        if isinstance(next_suggestion, dict):
            metadata["next_suggestion"] = dict(next_suggestion)
        if judgment:
            metadata["judgment"] = {
                "risk_tier": str(judgment.get("risk_tier", "")),
                "decision": str(judgment.get("decision", "")),
                "suppressed_reason": str(judgment.get("suppressed_reason", "")),
                "recovery": bool(judgment.get("recovery", False)),
                "debug": dict(judgment.get("debug") or {}) if isinstance(judgment.get("debug"), dict) else {},
            }
        if planner_obedience:
            metadata["planner_obedience"] = dict(planner_obedience)
        if planned_decision is not None and planned_decision.route_state is not None:
            metadata["route_state"] = planned_decision.route_state.to_dict()
        return metadata

    def _publish_screen_awareness_event(
        self,
        *,
        session_id: str,
        screen_awareness_debug: object,
    ) -> None:
        debug_events_enabled = False
        if self.screen_awareness is not None:
            debug_events_enabled = self.screen_awareness.config.debug_events_enabled
        elif hasattr(self.config, "screen_awareness"):
            debug_events_enabled = bool(self.config.screen_awareness.debug_events_enabled)
        if not debug_events_enabled:
            return
        if not isinstance(screen_awareness_debug, dict) or not screen_awareness_debug.get("candidate"):
            return
        disposition = str(screen_awareness_debug.get("disposition") or "").strip()
        message = "Screen-awareness request detected."
        if disposition == "phase0_scaffold":
            message = "Screen-awareness request routed to the Phase 0 scaffold."
        elif disposition == "phase1_analyze":
            message = "Screen-awareness request routed to Phase 1 observe-and-describe analysis."
        elif disposition == "phase2_ground":
            message = "Screen-awareness request routed to Phase 2 grounding and disambiguation."
        elif disposition == "phase3_guide":
            message = "Screen-awareness request routed to Phase 3 guided navigation."
        elif disposition == "phase4_verify":
            message = "Screen-awareness request routed to Phase 4 verification and change intelligence."
        elif disposition == "phase5_act":
            message = "Screen-awareness request routed to Phase 5 direct UI action execution."
        elif disposition == "phase6_continue":
            message = "Screen-awareness request routed to Phase 6 workflow continuity and recovery."
        elif disposition == "phase8_problem_solve":
            message = "Screen-awareness request routed to Phase 8 problem solving and teaching."
        elif disposition == "phase9_workflow_reuse":
            message = "Screen-awareness request routed to Phase 9 workflow learning and reuse."
        elif disposition == "phase10_brain_integration":
            message = "Screen-awareness request routed to Phase 10 brain integration and long-term intelligence."
        elif disposition == "phase11_power":
            message = "Screen-awareness request routed to Phase 11 multi-monitor, accessibility, and power features."
        elif disposition in {"feature_disabled", "routing_disabled"}:
            message = "Screen-awareness request detected but not activated."
        self.events.publish(
            event_family="screen_awareness",
            event_type=f"screen_awareness.{disposition or 'routed'}",
            severity="debug",
            subsystem="screen_awareness",
            session_id=session_id,
            visibility_scope="deck_context",
            retention_class="bounded_recent",
            provenance={"channel": "screen_awareness", "kind": "subsystem_interpretation"},
            message=message,
            payload={
                "session_id": session_id,
                "disposition": disposition,
                "intent": str(screen_awareness_debug.get("intent") or ""),
                "route_confidence": float(screen_awareness_debug.get("route_confidence") or 0.0),
                "feature_enabled": bool(screen_awareness_debug.get("feature_enabled", False)),
                "planner_routing_enabled": bool(screen_awareness_debug.get("planner_routing_enabled", False)),
                "input_signals": dict(screen_awareness_debug.get("input_signals") or {})
                if isinstance(screen_awareness_debug.get("input_signals"), dict)
                else {},
                "analysis_result": dict(screen_awareness_debug.get("analysis_result") or {})
                if isinstance(screen_awareness_debug.get("analysis_result"), dict)
                else {},
                "telemetry": dict(screen_awareness_debug.get("telemetry") or {})
                if isinstance(screen_awareness_debug.get("telemetry"), dict)
                else {},
            },
        )

    def _publish_software_control_event(
        self,
        *,
        session_id: str,
        software_debug: object,
    ) -> None:
        debug_events_enabled = False
        if self.software_control is not None:
            debug_events_enabled = self.software_control.config.debug_events_enabled
        elif hasattr(self.config, "software_control"):
            debug_events_enabled = bool(self.config.software_control.debug_events_enabled)
        if not debug_events_enabled:
            return
        if not isinstance(software_debug, dict) or not software_debug.get("candidate"):
            return
        result = software_debug.get("result") if isinstance(software_debug.get("result"), dict) else {}
        trace = software_debug.get("trace") if isinstance(software_debug.get("trace"), dict) else {}
        self.events.publish(
            event_family="tool",
            event_type="tool.software_control_routed",
            severity="debug",
            subsystem="software_control",
            session_id=session_id,
            visibility_scope="internal_only",
            retention_class="ephemeral",
            provenance={"channel": "software_control", "kind": "subsystem_interpretation"},
            message="Software-control request handled.",
            payload={
                "session_id": session_id,
                "operation_type": str(software_debug.get("operation_type") or ""),
                "target_name": str(software_debug.get("target_name") or ""),
                "status": str((result.get("status") or trace.get("execution_status") or "")).strip(),
                "route_selected": str(trace.get("route_selected") or ""),
                "recovery_invoked": bool(trace.get("recovery_invoked", False)),
                "trace": dict(trace),
            },
        )

    def _publish_software_recovery_event(
        self,
        *,
        session_id: str,
        recovery_debug: object,
    ) -> None:
        debug_events_enabled = False
        if self.software_recovery is not None:
            debug_events_enabled = self.software_recovery.config.debug_events_enabled
        elif hasattr(self.config, "software_recovery"):
            debug_events_enabled = bool(self.config.software_recovery.debug_events_enabled)
        if not debug_events_enabled:
            return
        if not isinstance(recovery_debug, dict):
            return
        recovery_plan = recovery_debug.get("recovery_plan") if isinstance(recovery_debug.get("recovery_plan"), dict) else {}
        recovery_result = recovery_debug.get("recovery_result") if isinstance(recovery_debug.get("recovery_result"), dict) else {}
        if not recovery_plan and not recovery_result:
            return
        self.events.publish(
            event_family="runtime",
            event_type="runtime.software_recovery_engaged",
            severity="debug",
            subsystem="software_recovery",
            session_id=session_id,
            visibility_scope="internal_only",
            retention_class="ephemeral",
            provenance={"channel": "software_recovery", "kind": "subsystem_interpretation"},
            message="Software recovery route engaged.",
            payload={
                "session_id": session_id,
                "failure_category": str((recovery_plan.get("failure_category") or recovery_debug.get("failure_category") or "")).strip(),
                "cloud_fallback_disposition": str(recovery_plan.get("cloud_fallback_disposition") or "").strip(),
                "route_switched_to": str(recovery_result.get("route_switched_to") or "").strip(),
                "recovery_plan": dict(recovery_plan),
                "recovery_result": dict(recovery_result),
            },
        )

    def _publish_discord_relay_event(
        self,
        *,
        session_id: str,
        relay_debug: object,
    ) -> None:
        debug_events_enabled = False
        if self.discord_relay is not None:
            debug_events_enabled = self.discord_relay.config.debug_events_enabled
        elif hasattr(self.config, "discord_relay"):
            debug_events_enabled = bool(self.config.discord_relay.debug_events_enabled)
        if not debug_events_enabled:
            return
        if not isinstance(relay_debug, dict):
            return
        trace = relay_debug.get("trace") if isinstance(relay_debug.get("trace"), dict) else {}
        preview = relay_debug.get("preview") if isinstance(relay_debug.get("preview"), dict) else {}
        attempt = relay_debug.get("attempt") if isinstance(relay_debug.get("attempt"), dict) else {}
        if not trace and not preview and not attempt:
            return
        self.events.publish(
            event_family="discord_relay",
            event_type=f"discord_relay.{str((attempt.get('state') or trace.get('state') or 'updated')).strip().lower() or 'updated'}",
            severity="debug",
            subsystem="discord_relay",
            session_id=session_id,
            visibility_scope="deck_context",
            retention_class="bounded_recent",
            provenance={"channel": "discord_relay", "kind": "subsystem_interpretation"},
            message="Discord relay request handled.",
            payload={
                "session_id": session_id,
                "state": str((attempt.get("state") or trace.get("state") or "")).strip(),
                "route_mode": str((attempt.get("route_mode") or preview.get("route_mode") or trace.get("route_mode") or "")).strip(),
                "payload_kind": str((preview.get("payload") or {}).get("kind") if isinstance(preview.get("payload"), dict) else trace.get("payload_kind") or "").strip(),
                "destination_alias": str((preview.get("destination") or {}).get("alias") if isinstance(preview.get("destination"), dict) else trace.get("destination_alias") or "").strip(),
                "preview": dict(preview),
                "attempt": dict(attempt),
            },
        )

    def _publish_calculation_event(
        self,
        *,
        session_id: str,
        calculation_debug: object,
    ) -> None:
        debug_events_enabled = False
        if self.calculations is not None:
            debug_events_enabled = self.calculations.config.debug_events_enabled
        elif hasattr(self.config, "calculations"):
            debug_events_enabled = bool(self.config.calculations.debug_events_enabled)
        if not debug_events_enabled:
            return
        if not isinstance(calculation_debug, dict) or not calculation_debug.get("candidate"):
            return
        trace = calculation_debug.get("trace") if isinstance(calculation_debug.get("trace"), dict) else {}
        failure = calculation_debug.get("failure") if isinstance(calculation_debug.get("failure"), dict) else {}
        message = "Calculation request detected."
        if trace.get("parse_success") is True and trace.get("result"):
            message = "Calculation request resolved through the deterministic local lane."
        elif failure:
            message = "Calculation request failed honestly in the deterministic local lane."
        self.events.publish(
            event_family="verification",
            event_type=(
                "verification.calculation_succeeded"
                if trace.get("parse_success") is True and trace.get("result")
                else "verification.calculation_failed"
                if failure
                else "verification.calculation_detected"
            ),
            severity="debug",
            subsystem="calculations",
            session_id=session_id,
            visibility_scope="deck_context",
            retention_class="bounded_recent",
            provenance={"channel": "calculations", "kind": "subsystem_interpretation"},
            message=message,
            payload={
                "session_id": session_id,
                "disposition": str(calculation_debug.get("disposition") or ""),
                "route_confidence": float(calculation_debug.get("route_confidence") or 0.0),
                "extracted_expression": str(calculation_debug.get("extracted_expression") or ""),
                "trace": dict(trace),
                "failure": dict(failure),
                "result": dict(calculation_debug.get("result") or {})
                if isinstance(calculation_debug.get("result"), dict)
                else {},
            },
        )

    def _planner_response_contract(self, planned_decision: PlannerDecision | None) -> dict[str, Any]:
        if planned_decision is None or planned_decision.structured_query is None:
            return {}
        slots = planned_decision.structured_query.slots if isinstance(planned_decision.structured_query.slots, dict) else {}
        if planned_decision.unsupported_reason is not None:
            contract = slots.get("unsupported_response_contract")
            if isinstance(contract, dict):
                return dict(contract)
        contract = slots.get("response_contract")
        if isinstance(contract, dict):
            return dict(contract)
        return {}

    def _planner_obedience_metadata(
        self,
        *,
        planned_decision: PlannerDecision | None,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        text: str,
    ) -> dict[str, Any]:
        if planned_decision is None:
            return {}
        planned_tool_names = [request.tool_name for request in planned_decision.tool_requests]
        actual_tool_names = [
            str(job.get("tool_name", "")).strip()
            for job in jobs
            if isinstance(job, dict) and str(job.get("tool_name", "")).strip()
        ]
        expected_response_mode = str(planned_decision.response_mode or "").strip()
        actual_result_mode = self._actual_result_mode(
            planned_decision=planned_decision,
            jobs=jobs,
            actions=actions,
            text=text,
        )
        legacy_fallback = ""
        semantic_debug = planned_decision.debug.get("semantic_parse_proposal") if isinstance(planned_decision.debug, dict) else {}
        if isinstance(semantic_debug, dict):
            legacy_fallback = str(semantic_debug.get("fallback_path") or "").strip()
        compatibility_shim_used = bool(
            planned_decision.execution_plan is not None and planned_decision.execution_plan.plan_type == "compatibility_shim"
        )
        tool_dispatch_match = planned_tool_names == actual_tool_names if (planned_tool_names or actual_tool_names) else True
        response_mode_match = expected_response_mode == actual_result_mode if expected_response_mode else not actual_result_mode

        final_result_type = "assistant_message"
        if actual_tool_names:
            final_result_type = "tool_result"
        if expected_response_mode == "unsupported":
            final_result_type = "unsupported"
        elif expected_response_mode == "clarification":
            final_result_type = "clarification"
        elif expected_response_mode == "workspace_result":
            final_result_type = "workspace_result"
        elif expected_response_mode == "search_result":
            final_result_type = "search_result"
        elif expected_response_mode == "action_result":
            final_result_type = "action_result"
        elif expected_response_mode == "calculation_result":
            final_result_type = "calculation_result"
        elif expected_response_mode in {"numeric_metric", "status_summary", "identity_summary", "diagnostic_summary", "history_summary", "forecast_summary"}:
            final_result_type = expected_response_mode

        return {
            "query_shape": planned_decision.structured_query.query_shape.value if planned_decision.structured_query is not None else "",
            "execution_plan_type": str(planned_decision.execution_plan.plan_type if planned_decision.execution_plan is not None else ""),
            "planned_tool_names": planned_tool_names,
            "actual_tool_names": actual_tool_names,
            "expected_response_mode": expected_response_mode,
            "actual_result_mode": actual_result_mode,
            "final_result_type": final_result_type,
            "tool_dispatch_match": tool_dispatch_match,
            "response_mode_match": response_mode_match,
            "authority_enforced": tool_dispatch_match and response_mode_match,
            "compatibility_shim_used": compatibility_shim_used,
            "legacy_fallback_used": legacy_fallback,
        }

    def _direct_handler_debug(self, tool_requests: list[ToolRequest], *, surface_mode: str) -> dict[str, Any]:
        tool_chain = [request.tool_name for request in tool_requests]
        primary_tool = tool_chain[0] if tool_chain else ""
        route_family = _direct_route_family(primary_tool)
        subsystem = _direct_route_subsystem(route_family, primary_tool)
        return {
            "routing_engine": "direct_handler",
            "direct_handler_typed": True,
            "direct_handler_reason": "explicit_direct_command_or_fast_status_path",
            "route_family": route_family,
            "subsystem": subsystem,
            "tool_chain": tool_chain,
            "surface_mode": surface_mode,
            "generic_provider_gate_reason": "native_direct_handler_selected",
            "legacy_fallback_used": False,
            "route_spine_used": False,
        }

    def _actual_result_mode(
        self,
        *,
        planned_decision: PlannerDecision,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        text: str,
    ) -> str:
        del actions, text
        if not jobs:
            return str(planned_decision.response_mode or "").strip()
        primary_job = jobs[0] if isinstance(jobs[0], dict) else {}
        tool_name = str(primary_job.get("tool_name", "")).strip().lower()
        arguments = primary_job.get("arguments") if isinstance(primary_job.get("arguments"), dict) else {}

        if tool_name in {"clock", "network_status", "power_status", "storage_status", "location_status", "saved_locations", "active_apps", "recent_files"}:
            return "status_summary"
        if tool_name == "network_throughput":
            return "numeric_metric"
        if tool_name == "machine_status":
            focus = str(arguments.get("focus", "")).strip().lower()
            return "identity_summary" if focus == "identity" else "status_summary"
        if tool_name in {"network_diagnosis", "power_diagnosis", "resource_diagnosis", "storage_diagnosis"}:
            return str(planned_decision.response_mode or "diagnostic_summary")
        if tool_name == "resource_status":
            query_kind = str(arguments.get("query_kind", "")).strip().lower()
            if query_kind == "identity":
                return "identity_summary"
            if query_kind == "diagnostic":
                return "diagnostic_summary"
            return "numeric_metric"
        if tool_name == "weather_current":
            return str(planned_decision.response_mode or "forecast_summary")
        if tool_name == "desktop_search":
            return "search_result"
        if tool_name in {
            "workspace_restore",
            "workspace_assemble",
            "workspace_save",
            "workspace_clear",
            "workspace_archive",
            "workspace_rename",
            "workspace_tag",
            "workspace_list",
            "workspace_where_left_off",
            "workspace_next_steps",
        }:
            return "workspace_result"
        if tool_name in {
            "app_control",
            "window_control",
            "system_control",
            "workflow_execute",
            "repair_action",
            "routine_execute",
            "routine_save",
            "trusted_hook_execute",
            "trusted_hook_register",
            "maintenance_action",
            "file_operation",
            "browser_context",
            "activity_summary",
            "context_action",
            "save_location",
            "external_open_url",
            "deck_open_url",
            "external_open_file",
            "deck_open_file",
        }:
            return str(planned_decision.response_mode or "action_result")
        return str(planned_decision.response_mode or "").strip()

    def _micro_response(self, text: str) -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return "Standing by."
        stop = len(cleaned)
        for marker in (". ", "! ", "? "):
            index = cleaned.find(marker)
            if index != -1:
                stop = min(stop, index + 1)
        micro = cleaned[:stop].strip()
        if len(micro) > 96:
            micro = micro[:95].rstrip(" ,;:") + "…"
        return micro or cleaned[:96]

    def _bearing_title(
        self,
        *,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        active_module: str,
        text: str,
    ) -> str:
        tool_name = str(jobs[0].get("tool_name", "")).strip().lower() if jobs else ""
        action_type = str(actions[0].get("type", "")).strip().lower() if actions else ""
        if tool_name or action_type:
            title_map = {
                "power_status": "Power",
                "power_projection": "Power",
                "power_diagnosis": "Power",
                "clock": "Time",
                "machine_status": "Machine",
                "resource_status": "Resources",
                "resource_diagnosis": "Resources",
                "storage_status": "Storage",
                "storage_diagnosis": "Storage",
                "network_status": "Network",
                "network_throughput": "Network",
                "network_diagnosis": "Network",
                "weather_current": "Weather",
                "location_status": "Location",
                "saved_locations": "Location",
                "save_location": "Location",
                "active_apps": "Applications",
                "browser_context": "Browser",
                "activity_summary": "Activity",
                "app_control": "Applications",
                "context_action": "Context",
                "desktop_search": "Search",
                "workflow_execute": "Workflow",
                "repair_action": "Repair",
                "routine_execute": "Routine",
                "routine_save": "Routine",
                "trusted_hook_register": "Hook",
                "trusted_hook_execute": "Hook",
                "file_operation": "Files",
                "maintenance_action": "Maintenance",
                "recent_files": "Files",
                "workspace_restore": "Workspace",
                "workspace_assemble": "Workspace",
                "workspace_save": "Workspace",
                "workspace_clear": "Workspace",
                "workspace_archive": "Workspace",
                "workspace_rename": "Workspace",
                "workspace_tag": "Workspace",
                "workspace_list": "Workspace",
                "workspace_where_left_off": "Workspace",
                "workspace_next_steps": "Workspace",
                "workspace_open": "Reference",
                "workspace_focus": "Systems" if active_module == "systems" else "Deck",
                "open_external": "External",
            }
            title = title_map.get(tool_name) or title_map.get(action_type)
            if title:
                return title
        lowered = text.lower()
        if "weather" in lowered or "forecast" in lowered:
            return "Weather"
        if "battery" in lowered or "power" in lowered:
            return "Power"
        if "network" in lowered or "wi-fi" in lowered or "wifi" in lowered:
            return "Network"
        if "workspace" in lowered:
            return "Workspace"
        if "location" in lowered:
            return "Location"
        if active_module == "systems":
            return "Systems"
        return "Bearing"

    def _resolve_response_profile(
        self,
        *,
        explicit_profile: str | None,
        surface_mode: str,
        active_module: str,
    ) -> tuple[str, str]:
        explicit = str(explicit_profile or "").strip().lower()
        if explicit in RESPONSE_PROFILES:
            return explicit, "explicit_request"
        environment_profile = str(os.environ.get("STORMHELM_RESPONSE_PROFILE") or "").strip().lower()
        if environment_profile in RESPONSE_PROFILES:
            return environment_profile, "environment"
        if str(os.environ.get("STORMHELM_COMMAND_EVAL_DRY_RUN") or "").strip().lower() in {"1", "true", "yes"}:
            return "command_eval_compact", "command_eval_dry_run"
        ghost_default = str(os.environ.get("STORMHELM_GHOST_COMPACT_DEFAULT") or "").strip().lower()
        if ghost_default in {"1", "true", "yes"} and str(surface_mode or "").strip().lower() == "ghost":
            return "ghost_compact", "ghost_compact_default"
        del active_module
        return "deck_detail", "backward_compatible_default"

    def _apply_response_profile(
        self,
        payload: dict[str, Any],
        *,
        profile: str,
        reason: str,
    ) -> dict[str, Any]:
        normalized_profile = profile if profile in RESPONSE_PROFILES else "deck_detail"
        if normalized_profile == "deck_detail":
            diagnostics = self._payload_profile_diagnostics(payload, profile=normalized_profile, reason=reason)
            payload["response_profile"] = normalized_profile
            payload["payload_diagnostics"] = diagnostics
            assistant_message = payload.get("assistant_message")
            metadata = assistant_message.get("metadata") if isinstance(assistant_message, dict) and isinstance(assistant_message.get("metadata"), dict) else None
            if isinstance(metadata, dict):
                metadata["response_profile"] = normalized_profile
                metadata["response_profile_reason"] = reason
                metadata["payload_diagnostics"] = diagnostics
            return payload

        compact_payload = dict(payload)
        compact_payload["user_message"] = self._compact_user_message(
            compact_payload.get("user_message"),
            profile=normalized_profile,
        )
        compact_jobs = self._compact_jobs_for_profile(
            compact_payload.get("jobs") if isinstance(compact_payload.get("jobs"), list) else [],
            profile=normalized_profile,
        )
        compact_actions = self._compact_actions_for_profile(
            compact_payload.get("actions") if isinstance(compact_payload.get("actions"), list) else [],
            profile=normalized_profile,
        )
        compact_payload["jobs"] = compact_jobs
        compact_payload["job"] = self._compact_job_reference(compact_jobs[0]) if compact_jobs else None
        compact_payload["actions"] = compact_actions
        compact_payload["active_request_state"] = self._compact_active_request_state(
            compact_payload.get("active_request_state"),
            profile=normalized_profile,
        )
        compact_payload["recent_context_resolutions"] = self._compact_recent_context_resolutions(
            compact_payload.get("recent_context_resolutions"),
            profile=normalized_profile,
        )
        compact_payload["active_task"] = self._compact_active_task(
            compact_payload.get("active_task"),
            profile=normalized_profile,
        )

        assistant_message = compact_payload.get("assistant_message")
        if isinstance(assistant_message, dict):
            compact_message = dict(assistant_message)
            metadata = compact_message.get("metadata") if isinstance(compact_message.get("metadata"), dict) else {}
            compact_metadata = self._compact_response_metadata(
                metadata,
                profile=normalized_profile,
                compact_jobs=compact_jobs,
                compact_actions=compact_actions,
            )
            compact_metadata["response_profile"] = normalized_profile
            compact_metadata["response_profile_reason"] = reason
            compact_message["metadata"] = compact_metadata
            compact_payload["assistant_message"] = compact_message

        diagnostics = self._payload_profile_diagnostics(compact_payload, profile=normalized_profile, reason=reason)
        diagnostics["compacted"] = True
        diagnostics["summarized_sections"] = [
            "assistant_message.metadata.jobs",
            "assistant_message.metadata.actions",
            "jobs",
            "job",
            "actions",
            "active_request_state",
            "active_task",
        ]
        diagnostics["omitted_sections"] = [
            "full_planner_capability_specs",
            "deck_detail_workspace_item_arrays",
            "duplicated_full_job_result_graphs",
        ]
        compact_payload["response_profile"] = normalized_profile
        compact_payload["payload_diagnostics"] = diagnostics
        assistant_message = compact_payload.get("assistant_message")
        metadata = assistant_message.get("metadata") if isinstance(assistant_message, dict) and isinstance(assistant_message.get("metadata"), dict) else None
        if isinstance(metadata, dict):
            metadata["payload_diagnostics"] = diagnostics
        return compact_payload

    def _attach_stage_timings_to_response(
        self,
        payload: dict[str, Any],
        stage_timings: dict[str, float],
        *,
        request_id: str | None = None,
        session_id: str = "",
        surface_mode: str = "",
        active_module: str = "",
        provider_called: bool | None = None,
        openai_called: bool | None = None,
        llm_called: bool | None = None,
        embedding_called: bool | None = None,
        voice_involved: bool = False,
    ) -> None:
        assistant_message = payload.get("assistant_message") if isinstance(payload.get("assistant_message"), dict) else {}
        metadata = assistant_message.get("metadata") if isinstance(assistant_message.get("metadata"), dict) else {}
        if isinstance(metadata, dict):
            metadata["stage_timings_ms"] = dict(stage_timings)
            attach_latency_metadata(
                metadata,
                stage_timings_ms=stage_timings,
                request_id=request_id,
                session_id=session_id or str(payload.get("session_id") or ""),
                surface_mode=surface_mode or str(metadata.get("surface_mode") or ""),
                active_module=active_module or str(metadata.get("active_module") or ""),
                provider_called=provider_called,
                openai_called=openai_called,
                llm_called=llm_called,
                embedding_called=embedding_called,
                voice_involved=voice_involved,
                job_count=len(payload.get("jobs") or []) if isinstance(payload.get("jobs"), list) else None,
            )
            planner_debug = metadata.get("planner_debug") if isinstance(metadata.get("planner_debug"), dict) else {}
            if isinstance(planner_debug, dict):
                if payload.get("response_profile") == "command_eval_compact":
                    planner_debug.pop("stage_timings_ms", None)
                    planner_debug.pop("latency_trace", None)
                    planner_debug["stage_timings_ref"] = "assistant_message.metadata.stage_timings_ms"
                    planner_debug["latency_trace_ref"] = "assistant_message.metadata.latency_trace"
                    if "route_handler_subspans" in metadata:
                        planner_debug.pop("route_handler_subspans", None)
                        planner_debug["route_handler_subspans_ref"] = "assistant_message.metadata.route_handler_subspans"
                else:
                    planner_debug["stage_timings_ms"] = dict(stage_timings)

    def _publish_latency_posture_events(self, payload: dict[str, Any]) -> None:
        assistant_message = payload.get("assistant_message") if isinstance(payload.get("assistant_message"), dict) else {}
        metadata = assistant_message.get("metadata") if isinstance(assistant_message.get("metadata"), dict) else {}
        if not isinstance(metadata, dict):
            return
        first_feedback = metadata.get("first_feedback") if isinstance(metadata.get("first_feedback"), dict) else {}
        if not first_feedback:
            return
        execution_mode = str(metadata.get("execution_mode") or first_feedback.get("execution_mode") or "")
        if execution_mode not in {"plan_first", "async_first", "provider_wait", "unsupported", "clarification"}:
            return
        partial = metadata.get("partial_response") if isinstance(metadata.get("partial_response"), dict) else {}
        event_payload = {
            "request_id": str(first_feedback.get("request_id") or ""),
            "session_id": str(first_feedback.get("session_id") or payload.get("session_id") or ""),
            "route_family": str(first_feedback.get("route_family") or ""),
            "subsystem": str(first_feedback.get("subsystem") or ""),
            "result_state": str(first_feedback.get("result_state") or ""),
            "budget_label": str(first_feedback.get("budget_label") or ""),
            "latency_trace_id": str(first_feedback.get("latency_trace_id") or ""),
            "execution_mode": execution_mode,
            "async_continuation": bool(first_feedback.get("async_continuation", False)),
            "partial_response_returned": bool(partial.get("partial_response_returned", False)),
            "completion_claimed": False,
            "verification_claimed": False,
            "message_preview": str(first_feedback.get("message_preview") or "")[:160],
            "task_id": str(first_feedback.get("task_id") or ""),
            "job_id": str(first_feedback.get("job_id") or ""),
            "fail_fast_reason": str(metadata.get("fail_fast_reason") or ""),
        }
        session_id = str(event_payload.get("session_id") or "default")
        self.events.publish(
            event_family="runtime",
            event_type="latency.first_feedback_ready",
            severity="debug",
            subsystem="latency",
            session_id=session_id,
            visibility_scope="internal_only",
            retention_class="bounded_recent",
            provenance={"channel": "assistant", "kind": "latency_posture"},
            message="Latency first-feedback posture is available.",
            payload=event_payload,
        )
        if event_payload["partial_response_returned"]:
            self.events.publish(
                event_family="runtime",
                event_type="route.partial_response_returned",
                severity="debug",
                subsystem="latency",
                session_id=session_id,
                visibility_scope="internal_only",
                retention_class="bounded_recent",
                provenance={"channel": "assistant", "kind": "latency_posture"},
                message="Route returned a truthful partial response posture.",
                payload=event_payload,
            )

    def _compact_response_metadata(
        self,
        metadata: dict[str, Any],
        *,
        profile: str,
        compact_jobs: list[dict[str, Any]],
        compact_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in (
            "bearing_title",
            "micro_response",
            "full_response",
            "spoken_response",
            "verification_state",
            "surface_mode",
            "active_module",
            "response_profile",
            "response_profile_reason",
            "fail_fast_reason",
            "result_state",
            "fast_path_used",
            "heavy_context_loaded",
            "heavy_context_reason",
            "provider_fallback_eligible",
            "provider_fallback_suppressed_reason",
            "planner_candidates_pruned_count",
            "snapshot_hot_path_hit",
            "heavy_context_avoided_by_snapshot",
            "stale_snapshot_used_cautiously",
            "invalidation_count",
            "async_strategy",
            "async_initial_response_returned",
            "async_continuation",
            "events_expected",
            "route_continuation_id",
            "route_progress_stage",
            "route_progress_status",
            "progress_event_count",
            "job_required",
            "task_required",
            "event_progress_required",
            "worker_lane",
            "worker_priority",
            "queue_depth_at_submit",
            "queue_wait_ms",
            "job_start_delay_ms",
            "job_run_ms",
            "job_total_ms",
            "worker_index",
            "worker_capacity",
            "workers_busy_at_submit",
            "workers_idle_at_submit",
            "worker_saturation_percent",
            "interactive_jobs_waiting",
            "background_jobs_running",
            "background_job_count",
            "interactive_job_count",
            "starvation_detected",
        ):
            if key in metadata:
                compact[key] = self._compact_scalar(metadata.get(key), profile=profile)
        for key in (
            "adapter_contract",
            "adapter_execution",
            "judgment",
            "next_suggestion",
            "planner_obedience",
            "route_state",
            "route_handler_subspans",
            "stage_timings_ms",
            "api_timings_ms",
            "voice_core_result",
            "route_triage_result",
            "snapshot_freshness",
            "snapshot_age_ms",
            "snapshot_miss_reason",
            "async_route_handle",
            "route_progress_state",
            "async_route",
            "async_worker_utilization_summary",
            "subsystem_continuation",
        ):
            if isinstance(metadata.get(key), dict):
                compact[key] = self._compact_value(metadata.get(key), profile=profile)
        for key in (
            "candidate_route_families",
            "skipped_route_families",
            "route_family_seams_evaluated",
            "route_family_seams_skipped",
            "snapshots_checked",
            "snapshots_used",
            "snapshots_refreshed",
            "snapshots_invalidated",
            "freshness_warnings",
        ):
            if isinstance(metadata.get(key), list):
                if key.startswith("snapshots_") or key == "freshness_warnings":
                    compact[key] = [str(item)[:160] for item in metadata.get(key, [])[:16]]
                else:
                    compact[key] = self._compact_value(metadata.get(key), profile=profile)
        planner_debug = metadata.get("planner_debug")
        if isinstance(planner_debug, dict):
            compact["planner_debug"] = self._compact_planner_debug(planner_debug, profile=profile)
        if profile == "command_eval_compact":
            compact["jobsSummary"] = {
                "total_count": len(compact_jobs),
                "tools": [str(job.get("tool_name") or "") for job in compact_jobs],
            }
            compact["actionsSummary"] = {
                "total_count": len(compact_actions),
                "types": [str(action.get("type") or "") for action in compact_actions],
            }
        else:
            compact["jobs"] = compact_jobs
            compact["actions"] = compact_actions
        return compact

    def _compact_job_reference(self, job: dict[str, Any]) -> dict[str, Any]:
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        return {
            "job_id": str(job.get("job_id") or ""),
            "tool_name": str(job.get("tool_name") or ""),
            "status": str(job.get("status") or ""),
            "summary": str(result.get("summary") or ""),
        }

    def _compact_user_message(self, value: object, *, profile: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        compact: dict[str, Any] = {}
        for key in ("message_id", "session_id", "role", "content", "created_at"):
            if key in value:
                compact[key] = self._compact_scalar(value.get(key), profile=profile)
        metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
        if metadata:
            compact_metadata: dict[str, Any] = {}
            for key in ("surface_mode", "active_module"):
                if key in metadata:
                    compact_metadata[key] = self._compact_scalar(metadata.get(key), profile=profile)
            for key in ("workspace_context", "input_context"):
                if key in metadata:
                    compact_metadata[f"{key}_summary"] = self._collection_summary(metadata.get(key), profile=profile)
            compact["metadata"] = compact_metadata
        return compact

    def _compact_planner_debug(self, debug: dict[str, Any], *, profile: str) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in (
            "routing_engine",
            "direct_handler_typed",
            "direct_handler_reason",
            "route_family",
            "subsystem",
            "tool_chain",
            "surface_mode",
            "response_mode",
            "generic_provider_gate_reason",
            "legacy_fallback_used",
            "route_spine_used",
            "actual_tool_names",
            "actual_result_mode",
            "route_handler_subspans",
            "stage_timings_ms",
            "native_decline_reasons",
            "selected_route_spec",
            "candidate_specs_considered",
            "route_triage",
            "heavy_context_loaded",
            "heavy_context_reason",
            "provider_fallback_suppressed_reason",
            "planner_candidates_pruned_count",
            "route_family_seams_evaluated",
            "route_family_seams_skipped",
            "context_snapshots",
            "async_route",
            "subsystem_continuation",
        ):
            if key in debug:
                compact[key] = self._compact_value(debug.get(key), profile=profile)

        structured = debug.get("structured_query")
        if isinstance(structured, dict):
            compact["structured_query"] = self._compact_structured_query(structured, profile=profile)
        intent_frame = debug.get("intent_frame")
        if isinstance(intent_frame, dict):
            compact["intent_frame"] = self._compact_value(intent_frame, profile=profile)
        routing = debug.get("routing")
        if isinstance(routing, dict):
            compact["routing"] = self._compact_value(routing, profile=profile)
        planner_authority = debug.get("planner_authority")
        if isinstance(planner_authority, dict):
            compact["planner_authority"] = self._compact_value(planner_authority, profile=profile)

        planner_v2 = debug.get("planner_v2")
        if isinstance(planner_v2, dict):
            compact["planner_v2"] = self._compact_planner_v2_trace(planner_v2, profile=profile)
        for key in ("calculations", "software_control", "software_recovery", "screen_awareness", "discord_relay"):
            if isinstance(debug.get(key), dict):
                compact[key] = self._compact_value(debug.get(key), profile=profile)
        return compact

    def _compact_planner_v2_trace(self, trace: dict[str, Any], *, profile: str) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in (
            "authoritative",
            "routing_engine",
            "legacy_fallback_used",
            "normalized_request",
            "policy_decision",
            "result_state_draft",
            "plan_draft",
            "intent_frame",
            "stage_order",
        ):
            if key in trace:
                compact[key] = self._compact_value(trace.get(key), profile=profile)
        context_binding = trace.get("context_binding")
        if isinstance(context_binding, dict):
            compact["context_binding"] = self._compact_context_binding(context_binding, profile=profile)
        route_decision = trace.get("route_decision")
        if isinstance(route_decision, dict):
            compact["route_decision"] = self._compact_value(
                {
                    key: route_decision.get(key)
                    for key in (
                        "routing_engine",
                        "selected_route_spec",
                        "candidate_specs_considered",
                        "generic_provider_gate_reason",
                        "native_decline_reasons",
                        "planner_v2_decline_reason",
                        "legacy_family",
                        "legacy_family_scheduled_for_migration",
                        "migration_priority",
                        "route_family",
                        "subsystem",
                        "tool_name",
                    )
                    if key in route_decision
                },
                profile=profile,
            )
        capability_specs = trace.get("capability_specs")
        if isinstance(capability_specs, list):
            compact["capability_specs_summary"] = {
                "total_count": len(capability_specs),
                "displayed_count": 0,
                "omitted_count": len(capability_specs),
                "reason": "capability_spec_catalog_omitted_from_compact_response",
            }
        return compact

    def _compact_context_binding(self, binding: dict[str, Any], *, profile: str) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in (
            "context_reference",
            "context_type",
            "context_source",
            "status",
            "label",
            "freshness",
            "ambiguity",
            "missing_preconditions",
        ):
            if key in binding:
                compact[key] = self._compact_value(binding.get(key), profile=profile)
        if isinstance(binding.get("candidate_bindings"), list):
            bounded = self._compact_list(binding["candidate_bindings"], profile=profile)
            compact["candidate_bindings"] = bounded["items"]
            compact["candidate_bindingsSummary"] = bounded["summary"]
        value = binding.get("value")
        if profile == "command_eval_compact" and isinstance(value, dict):
            if isinstance(value.get("active_request_state"), dict):
                compact["active_request_state_ref"] = "payload.active_request_state"
                compact["valueSummary"] = self._collection_summary(value, profile=profile)
            else:
                compact["value"] = self._compact_value(value, profile=profile)
        elif value is not None:
            compact["value"] = self._compact_value(value, profile=profile)
        return compact

    def _compact_structured_query(self, structured_query: dict[str, Any], *, profile: str) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in (
            "query_shape",
            "domain",
            "execution_type",
            "requested_action",
            "output_mode",
            "output_type",
            "confidence",
            "diagnostic_mode",
            "current_context_reference",
            "comparison_target",
        ):
            if key in structured_query:
                compact[key] = self._compact_value(structured_query.get(key), profile=profile)
        slots = structured_query.get("slots")
        if isinstance(slots, dict):
            compact["slots"] = self._compact_value(slots, profile=profile)
        return compact

    def _compact_jobs_for_profile(self, jobs: object, *, profile: str) -> list[dict[str, Any]]:
        if not isinstance(jobs, list):
            return []
        return [self._compact_job_for_profile(job, profile=profile) for job in jobs if isinstance(job, dict)]

    def _compact_job_for_profile(self, job: dict[str, Any], *, profile: str) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in (
            "job_id",
            "tool_name",
            "arguments",
            "status",
            "created_at",
            "started_at",
            "finished_at",
            "error",
            "session_id",
            "task_id",
            "task_step_id",
        ):
            if key in job:
                compact[key] = self._compact_value(job.get(key), profile=profile)
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        if result:
            compact_result: dict[str, Any] = {}
            for key in ("success", "summary", "error", "adapter_contract", "adapter_execution"):
                if key in result:
                    compact_result[key] = self._compact_value(result.get(key), profile=profile)
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            if data:
                compact_result["data"] = self._compact_tool_data(data, profile=profile)
            compact["result"] = compact_result
        return compact

    def _compact_tool_data(self, data: dict[str, Any], *, profile: str) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in (
            "dry_run",
            "dry_run_compact",
            "detail_load_deferred",
            "tool_name",
            "display_name",
            "classification",
            "execution_mode",
            "validated_arguments",
            "approval_required",
            "preview_required",
            "dry_run_executor_ms",
            "route_handler_subspans",
            "adapter_contract_status",
            "payloadGuardrails",
            "payload_guardrails",
            "debug",
            "summary",
        ):
            if key in data:
                compact[key] = self._compact_value(data.get(key), profile=profile)
        for key in ("action", "actions"):
            if key == "action" and isinstance(data.get(key), dict):
                compact[key] = self._compact_action_for_profile(data[key], profile=profile)
            elif key == "actions" and isinstance(data.get(key), list):
                compact[key] = self._compact_actions_for_profile(data[key], profile=profile)
        for key in (
            "workspace",
            "workspace_summary_compact",
            "openedItemsSummary",
            "referencesSummary",
            "snapshot",
            "memory",
            "workspaces",
            "items",
            "next_steps",
        ):
            if key in data:
                compact[key] = self._compact_value(data.get(key), profile=profile)
        return compact

    def _compact_actions_for_profile(self, actions: object, *, profile: str) -> list[dict[str, Any]]:
        if not isinstance(actions, list):
            return []
        return [self._compact_action_for_profile(action, profile=profile) for action in actions if isinstance(action, dict)]

    def _compact_action_for_profile(self, action: dict[str, Any], *, profile: str) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        keep_keys = (
            "type",
            "target",
            "module",
            "section",
            "label",
            "url",
            "path",
            "browser_target",
            "browserTarget",
            "workspace_id",
            "workspaceId",
            "active_item_id",
            "bearing_title",
            "micro_response",
            "full_response",
            "approval_required",
            "preview_required",
            "localAction",
            "sendText",
        )
        if profile == "command_eval_compact":
            keep_keys = tuple(key for key in keep_keys if key not in {"full_response", "sendText"})
        for key in keep_keys:
            if key in action:
                compact[key] = self._compact_value(action.get(key), profile=profile)
        if profile == "command_eval_compact" and "full_response" in action:
            compact["full_response_summary"] = self._collection_summary(action.get("full_response"), profile=profile)
        if isinstance(action.get("workspace"), dict):
            compact["workspace"] = (
                self._workspace_reference_for_profile(action["workspace"], profile=profile)
                if profile == "command_eval_compact"
                else self._compact_workspace_payload_for_profile(action["workspace"], profile=profile)
            )
        if isinstance(action.get("items"), list):
            bounded = self._compact_list(action["items"], profile=profile, item_kind="workspace_item")
            if profile != "command_eval_compact":
                compact["items"] = bounded["items"]
            compact["itemsSummary"] = bounded["summary"]
        if isinstance(action.get("active_item"), dict):
            compact["active_item"] = self._compact_workspace_item_for_profile(action["active_item"], profile=profile)
        return compact

    def _compact_active_request_state(self, value: object, *, profile: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        compact: dict[str, Any] = {}
        for key in (
            "captured_at",
            "context_freshness",
            "context_reusable",
            "context_source",
            "family",
            "query_shape",
            "request_type",
            "subject",
            "source_text",
            "target_summary",
            "risk_level",
            "approval_posture",
            "pending_confirmation_id",
            "pending_preview_id",
        ):
            if key in value:
                compact[key] = self._compact_value(value.get(key), profile=profile)
        for key in ("route", "parameters", "trust"):
            if isinstance(value.get(key), dict):
                compact[key] = self._compact_value(value.get(key), profile=profile)
        structured = value.get("structured_query")
        if isinstance(structured, dict):
            compact["structured_query"] = self._compact_structured_query(structured, profile=profile)
        return compact

    def _compact_recent_context_resolutions(self, value: object, *, profile: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        bounded = self._compact_list(value, profile=profile)
        return [item for item in bounded["items"] if isinstance(item, dict)]

    def _compact_active_task_reference_from_turn(
        self,
        *,
        session_id: str,
        jobs: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        profile: str,
    ) -> dict[str, Any]:
        tool_names = [str(job.get("tool_name") or "") for job in jobs if isinstance(job, dict) and job.get("tool_name")]
        job_states = [str(job.get("status") or "") for job in jobs if isinstance(job, dict) and job.get("status")]
        result_states: list[str] = []
        for job in jobs:
            result = job.get("result") if isinstance(job, dict) and isinstance(job.get("result"), dict) else {}
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            if bool(data.get("dry_run")):
                result_states.append("dry_run")
            elif result.get("success") is True:
                result_states.append("completed")
            elif result.get("success") is False:
                result_states.append("failed")
        return {
            "session_id": session_id,
            "summary_omitted": True,
            "omitted_reason": "command_eval_compact_defers_full_active_task_summary",
            "response_profile": profile,
            "jobsSummary": {
                "total_count": len(jobs),
                "tools": tool_names,
                "states": job_states,
                "result_states": result_states,
            },
            "actionsSummary": {
                "total_count": len(actions),
                "types": [str(action.get("type") or "") for action in actions if isinstance(action, dict)],
            },
        }

    def _compact_active_task(self, value: object, *, profile: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        compact: dict[str, Any] = {}
        for key in (
            "taskId",
            "task_id",
            "title",
            "summary",
            "status",
            "resultState",
            "result_state",
            "activeStepId",
            "active_step_id",
            "createdAt",
            "updatedAt",
            "payloadGuardrails",
            "payload_guardrails",
            "ghostSummary",
        ):
            if key in value:
                compact[key] = self._compact_value(value.get(key), profile=profile)
        for key in ("continuity", "trust", "approval", "verification"):
            if isinstance(value.get(key), dict):
                compact[key] = self._compact_value(value.get(key), profile=profile)
        for key in ("steps", "evidence", "events", "actions"):
            if isinstance(value.get(key), list):
                bounded = self._compact_list(value[key], profile=profile)
                compact[key] = bounded["items"]
                compact[f"{key}Summary"] = bounded["summary"]
        compact.setdefault("payload_summary", self._collection_summary(value, profile=profile))
        return compact

    def _compact_workspace_payload_for_profile(self, value: dict[str, Any], *, profile: str) -> dict[str, Any]:
        if profile == "command_eval_compact":
            return self._workspace_reference_for_profile(value, profile=profile)
        compact: dict[str, Any] = {}
        for key in (
            "workspaceId",
            "name",
            "topic",
            "summary",
            "title",
            "status",
            "category",
            "templateKey",
            "templateTitle",
            "templateSource",
            "templateConfidence",
            "problemDomain",
            "activeGoal",
            "currentTaskState",
            "lastCompletedAction",
            "lastSurfaceMode",
            "lastActiveModule",
            "lastActiveSection",
            "whereLeftOff",
            "likelyNext",
            "pinned",
            "archived",
            "lastSnapshotAt",
            "payloadGuardrails",
        ):
            if key in value:
                compact[key] = self._compact_value(value.get(key), profile=profile)
        for key in ("pendingNextSteps", "references", "findings", "sessionNotes", "items", "openedItems"):
            if isinstance(value.get(key), list):
                bounded = self._compact_list(value[key], profile=profile, item_kind="workspace_item")
                compact[key] = bounded["items"]
                compact[f"{key}Summary"] = bounded["summary"]
            elif key in value:
                compact[key] = self._compact_value(value.get(key), profile=profile)
        if isinstance(value.get("continuity"), dict):
            compact["continuity"] = self._compact_value(value["continuity"], profile=profile)
        if isinstance(value.get("sessionPosture"), dict):
            compact["sessionPosture"] = self._compact_value(value["sessionPosture"], profile=profile)
        if isinstance(value.get("capabilities"), dict):
            compact["capabilities"] = self._compact_value(value["capabilities"], profile=profile)
        if isinstance(value.get("surfaceContent"), dict):
            compact["surfaceContentSummary"] = self._surface_content_summary(value["surfaceContent"], profile=profile)
        if isinstance(value.get("memoryContext"), dict):
            compact["memoryContextSummary"] = self._collection_summary(value["memoryContext"], profile=profile)
        if isinstance(value.get("resumeContext"), dict):
            compact["resumeContext"] = self._compact_value(value["resumeContext"], profile=profile)
        return compact

    def _workspace_reference_for_profile(self, value: dict[str, Any], *, profile: str) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in (
            "workspaceId",
            "name",
            "topic",
            "summary",
            "title",
            "status",
            "category",
            "templateKey",
            "templateTitle",
            "problemDomain",
            "activeGoal",
            "currentTaskState",
            "lastCompletedAction",
            "whereLeftOff",
            "likelyNext",
            "pinned",
            "archived",
            "payloadGuardrails",
            "payload_guardrails",
            "surfaceContentSummary",
            "referencesSummary",
            "findingsSummary",
            "sessionNotesSummary",
            "openedItemsSummary",
            "workspaceSummaryCompact",
            "detailLoadDeferred",
        ):
            if key in value:
                compact[key] = self._compact_scalar(value.get(key), profile=profile)
        for key in (
            "pendingNextSteps",
            "references",
            "findings",
            "sessionNotes",
            "items",
            "openedItems",
            "memoryContext",
            "resumeContext",
            "continuity",
            "sessionPosture",
            "capabilities",
        ):
            if key in value:
                summary_key = f"{key}Summary"
                if summary_key not in compact:
                    compact[summary_key] = self._collection_summary(value.get(key), profile=profile)
        if isinstance(value.get("surfaceContent"), dict):
            compact["surfaceContentSummary"] = self._surface_content_reference_summary(value["surfaceContent"], profile=profile)
        compact.setdefault("payload_summary", self._collection_summary(value, profile=profile))
        return compact

    def _surface_content_reference_summary(self, value: dict[str, Any], *, profile: str) -> dict[str, Any]:
        surfaces: list[dict[str, Any]] = []
        for surface_name, cluster in value.items():
            if not isinstance(cluster, dict):
                continue
            items = cluster.get("items") if isinstance(cluster.get("items"), list) else []
            surfaces.append(
                {
                    "surface": str(cluster.get("surface") or surface_name),
                    "title": self._compact_scalar(cluster.get("title") or surface_name, profile=profile),
                    "presentationKind": str(cluster.get("presentationKind") or ""),
                    "item_count": len(items),
                }
            )
        return {"surface_count": len(surfaces), "surfaces": surfaces}

    def _surface_content_summary(self, value: dict[str, Any], *, profile: str) -> dict[str, Any]:
        surfaces: list[dict[str, Any]] = []
        for surface_name, cluster in value.items():
            if not isinstance(cluster, dict):
                continue
            items = cluster.get("items") if isinstance(cluster.get("items"), list) else []
            bounded = self._compact_list(items, profile=profile, item_kind="workspace_item")
            surfaces.append(
                {
                    "surface": str(cluster.get("surface") or surface_name),
                    "title": str(cluster.get("title") or surface_name),
                    "purpose": self._compact_scalar(cluster.get("purpose"), profile=profile),
                    "presentationKind": str(cluster.get("presentationKind") or ""),
                    "items": bounded["items"],
                    "itemsSummary": bounded["summary"],
                }
            )
        return {"surface_count": len(surfaces), "surfaces": surfaces}

    def _compact_value(self, value: Any, *, profile: str, depth: int = 0) -> Any:
        if depth > 5:
            return {"truncated": True, "reason": "compact_profile_depth_limit"}
        if isinstance(value, dict):
            if "workspaceId" in value or "surfaceContent" in value:
                return self._compact_workspace_payload_for_profile(value, profile=profile)
            if any(key in value for key in ("itemId", "url", "path", "viewer")) and not any(
                key in value for key in ("route_decision", "structured_query")
            ):
                return self._compact_workspace_item_for_profile(value, profile=profile)
            compact: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key)
                if normalized_key in {"capability_specs"} and isinstance(item, list):
                    compact[f"{normalized_key}_summary"] = {
                        "total_count": len(item),
                        "displayed_count": 0,
                        "omitted_count": len(item),
                        "reason": "large_catalog_omitted_from_compact_response",
                    }
                    continue
                if normalized_key in {"embedding", "vector", "raw_audio", "raw", "content_blob"}:
                    compact[f"{normalized_key}_omitted"] = True
                    continue
                if isinstance(item, list):
                    bounded = self._compact_list(item, profile=profile)
                    compact[normalized_key] = bounded["items"]
                    if bounded["summary"].get("truncated"):
                        compact[f"{normalized_key}Summary"] = bounded["summary"]
                    continue
                compact[normalized_key] = self._compact_value(item, profile=profile, depth=depth + 1)
            return compact
        if isinstance(value, list):
            bounded = self._compact_list(value, profile=profile)
            return bounded["items"] + ([{"summary": bounded["summary"]}] if bounded["summary"].get("truncated") else [])
        return self._compact_scalar(value, profile=profile)

    def _compact_workspace_item_for_profile(self, item: dict[str, Any], *, profile: str) -> dict[str, Any]:
        text_limit = _COMPACT_PROFILE_TEXT_LIMITS.get(profile, 600)
        compact: dict[str, Any] = {}
        for key in (
            "itemId",
            "id",
            "kind",
            "viewer",
            "title",
            "subtitle",
            "module",
            "section",
            "url",
            "path",
            "summary",
            "detail",
            "badge",
            "role",
            "source",
            "score",
            "status",
        ):
            if key in item:
                value = item.get(key)
                compact[key] = value[:text_limit] if isinstance(value, str) else value
        for key in ("inclusionReasons", "whyIncluded", "surfaceLinks"):
            if isinstance(item.get(key), list):
                bounded = self._compact_list(item[key], profile=profile)
                compact[key] = bounded["items"]
                if bounded["summary"].get("truncated"):
                    compact[f"{key}Summary"] = bounded["summary"]
        if not compact.get("itemId"):
            identity = str(item.get("itemId") or item.get("url") or item.get("path") or item.get("title") or "").strip()
            if identity:
                compact["itemId"] = identity[:text_limit]
        return compact

    def _compact_list(self, value: list[Any], *, profile: str, item_kind: str = "") -> dict[str, Any]:
        limit = _COMPACT_PROFILE_LIST_LIMITS.get(profile, 8)
        items: list[Any] = []
        for item in value[:limit]:
            if item_kind == "workspace_item" and isinstance(item, dict):
                items.append(self._compact_workspace_item_for_profile(item, profile=profile))
            else:
                items.append(self._compact_value(item, profile=profile, depth=1))
        total_count = len(value)
        return {
            "items": items,
            "summary": {
                "total_count": total_count,
                "displayed_count": len(items),
                "omitted_count": max(0, total_count - len(items)),
                "truncated": total_count > len(items),
                "limit": limit,
            },
        }

    def _compact_scalar(self, value: Any, *, profile: str) -> Any:
        if isinstance(value, str):
            limit = _COMPACT_PROFILE_TEXT_LIMITS.get(profile, 600)
            return value if len(value) <= limit else value[: max(0, limit - 3)].rstrip() + "..."
        return value

    def _collection_summary(self, value: Any, *, profile: str) -> dict[str, Any]:
        try:
            payload_bytes = len(json.dumps(value, default=str, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            payload_bytes = 0
        summary: dict[str, Any] = {"estimated_bytes": payload_bytes}
        if isinstance(value, dict):
            summary["top_level_keys"] = sorted(str(key) for key in value.keys())[:24]
            for key, item in value.items():
                if isinstance(item, list):
                    summary[f"{key}_count"] = len(item)
                elif isinstance(item, dict):
                    summary[f"{key}_keys"] = sorted(str(child) for child in item.keys())[:12]
        elif isinstance(value, list):
            limit = _COMPACT_PROFILE_LIST_LIMITS.get(profile, 8)
            summary["total_count"] = len(value)
            summary["displayed_count"] = min(len(value), limit)
            summary["omitted_count"] = max(0, len(value) - limit)
            summary["truncated"] = len(value) > limit
            summary["limit"] = limit
        return summary

    def _payload_profile_diagnostics(self, payload: dict[str, Any], *, profile: str, reason: str) -> dict[str, Any]:
        try:
            estimated_bytes = len(json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            estimated_bytes = 0
        return {
            "response_profile": profile,
            "profile_selection_reason": reason,
            "estimated_response_json_bytes": estimated_bytes,
            "payload_guardrail_preserved": True,
        }

    def _learn_from_message(
        self,
        *,
        session_id: str,
        message: str,
        request_state: dict[str, Any],
    ) -> None:
        lower = normalize_phrase(message)
        family = str(request_state.get("family") or "").strip().lower()
        if family not in {"weather", "location"} and not any(token in lower for token in {"weather", "forecast", "location"}):
            return
        open_target = self._explicit_open_target(lower)
        if open_target is not None:
            self.session_state.remember_preference("weather", "open_target", open_target)
        location_mode = self._explicit_location_mode(lower)
        if location_mode is not None:
            self.session_state.remember_preference("weather", "location_mode", location_mode)

    def _explicit_open_target(self, lower: str) -> str | None:
        if any(phrase in lower for phrase in {"do not open", "don't open", "just answer", "without opening"}):
            return "none"
        if any(phrase in lower for phrase in {"in the deck", "inside the deck", "show it in the deck", "show it internally"}):
            return "deck"
        if any(phrase in lower for phrase in {"open externally", "open it externally", "in the browser"}):
            return "external"
        return None

    def _explicit_location_mode(self, lower: str) -> str | None:
        if any(token in lower for token in {"use my home location", "home location", "saved home"}):
            return "home"
        if any(token in lower for token in {"use my current location", "current location"}):
            return "current"
        return None


def _direct_route_family(tool_name: str) -> str:
    return {
        "clock": "time",
        "system_info": "machine",
        "power_status": "power",
        "storage_status": "storage",
        "network_status": "network",
        "active_apps": "app_control",
        "recent_files": "machine",
        "echo": "development",
        "file_reader": "file",
        "notes_write": "notes",
        "shell_command": "terminal",
        "workspace_save": "workspace_operations",
        "workspace_clear": "workspace_operations",
        "workspace_archive": "workspace_operations",
        "workspace_list": "workspace_operations",
        "workspace_where_left_off": "task_continuity",
        "workspace_next_steps": "task_continuity",
        "workspace_restore": "workspace_operations",
        "workspace_rename": "workspace_operations",
        "workspace_tag": "workspace_operations",
        "deck_open_url": "browser_destination",
        "external_open_url": "browser_destination",
        "deck_open_file": "file",
        "external_open_file": "file",
    }.get(str(tool_name or "").strip(), "")


def _direct_route_subsystem(route_family: str, tool_name: str) -> str:
    if tool_name in {"browser_context"}:
        return "context"
    return {
        "app_control": "system",
        "browser_destination": "browser",
        "development": "development",
        "file": "files",
        "machine": "system",
        "network": "system",
        "notes": "workspace",
        "power": "system",
        "storage": "system",
        "task_continuity": "workspace",
        "terminal": "terminal",
        "time": "system",
        "workspace_operations": "workspace",
    }.get(str(route_family or "").strip(), "")
