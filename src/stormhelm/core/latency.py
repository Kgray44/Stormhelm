from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from stormhelm.core.subsystem_latency import subsystem_latency_trace_fields


class RouteExecutionMode(str, Enum):
    INSTANT = "instant"
    PLAN_FIRST = "plan_first"
    ASYNC_FIRST = "async_first"
    PROVIDER_WAIT = "provider_wait"
    UNSUPPORTED = "unsupported"
    CLARIFICATION = "clarification"


class RouteLatencyPosture(str, Enum):
    INSTANT = "instant"
    CACHED_FAST = "cached_fast"
    BOUNDED_LIVE = "bounded_live"
    ASYNC_CONTINUATION = "async_continuation"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"


LATENCY_COUNTER_KEYS = {
    "memoized_summary_hits",
    "context_cache_hits",
    "context_cache_misses",
    "detail_load_deferred",
    "job_count",
    "event_count",
    "heavy_context_loaded",
    "fast_path_used",
    "planner_candidates_pruned_count",
    "snapshot_hot_path_hit",
    "heavy_context_avoided_by_snapshot",
    "invalidation_count",
    "async_initial_response_returned",
    "progress_event_count",
    "job_required",
    "task_required",
    "event_progress_required",
    "queue_depth_at_submit",
    "workers_busy_at_submit",
    "workers_idle_at_submit",
    "interactive_jobs_waiting",
    "background_jobs_running",
    "background_job_count",
    "interactive_job_count",
    "worker_capacity",
    "subsystem_continuation_created",
    "subsystem_continuation_progress_event_count",
    "direct_subsystem_async_converted",
    "returned_before_subsystem_completion",
    "async_conversion_expected",
}

LATENCY_AGGREGATE_KEYS = {
    "total_latency_ms",
    "http_boundary_ms",
    "http_client_wait_ms",
    "endpoint_dispatch_ms",
    "job_total_ms",
    "inline_front_half_ms",
    "worker_back_half_ms",
    "subsystem_continuation_queue_wait_ms",
    "subsystem_continuation_run_ms",
    "subsystem_continuation_total_ms",
    "continuation_queue_wait_ms",
    "continuation_run_ms",
    "continuation_total_ms",
    "core_result_to_tts_start_ms",
    "tts_start_to_first_chunk_ms",
    "first_chunk_to_playback_start_ms",
    "first_chunk_to_sink_accept_ms",
    "core_result_to_first_audio_ms",
    "core_result_to_first_output_start_ms",
    "request_to_first_audio_ms",
    "first_output_start_ms",
    "null_sink_first_accept_ms",
    "voice_first_audio_ms",
    "voice_core_to_first_audio_ms",
    "voice_tts_first_chunk_ms",
    "voice_playback_start_ms",
    "voice_first_output_start_ms",
    "voice_null_sink_first_accept_ms",
}

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "secret",
    "token",
    "password",
    "credential",
    "raw_audio",
    "generated_audio",
    "audio_bytes",
    "audio_chunk",
    "pcm",
    "wav_bytes",
    "mp3_bytes",
)


@dataclass(frozen=True, slots=True)
class LatencyBudget:
    label: str
    target_ms: float
    soft_ceiling_ms: float
    hard_ceiling_ms: float | None = None
    async_continuation_expected: bool = False
    target_first_feedback_ms: float | None = None
    target_total_ms: float | None = None
    target_initial_plan_ms: float | None = None
    target_ack_ms: float | None = None
    target_core_result_ms: float | None = None
    target_first_audio_ms: float | None = None

    @classmethod
    def for_label(cls, label: str | None) -> "LatencyBudget":
        normalized = str(label or "").strip().lower() or "ghost_interactive"
        budget = LATENCY_BUDGETS.get(normalized)
        if budget is not None:
            return budget
        return LATENCY_BUDGETS["ghost_interactive"]

    def evaluate(self, total_ms: float | int | None) -> "LatencyBudgetResult":
        total = _safe_float(total_ms)
        return LatencyBudgetResult(
            budget_label=self.label,
            target_ms=self.target_ms,
            soft_ceiling_ms=self.soft_ceiling_ms,
            hard_ceiling_ms=self.hard_ceiling_ms,
            budget_exceeded=total > self.soft_ceiling_ms,
            hard_ceiling_exceeded=(
                self.hard_ceiling_ms is not None and total > self.hard_ceiling_ms
            ),
            async_continuation_expected=self.async_continuation_expected,
        )

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class LatencyBudgetResult:
    budget_label: str
    target_ms: float
    soft_ceiling_ms: float
    hard_ceiling_ms: float | None
    budget_exceeded: bool
    hard_ceiling_exceeded: bool
    async_continuation_expected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True, slots=True)
class RouteFamilyLatencyContract:
    route_family: str
    latency_posture: RouteLatencyPosture
    hot_path_budget_ms: float
    live_probe_budget_ms: float = 0.0
    cache_family: str = ""
    cache_ttl_ms: float = 0.0
    stale_allowed: bool = False
    async_continuation_allowed: bool = False
    worker_lane: str = "interactive"
    detail_profile_required: str = ""
    verification_required: bool = False
    no_fake_data_rule: str = "No fabricated values; return unsupported, cached, or deferred state when data is unavailable."

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["latency_posture"] = self.latency_posture.value
        return _json_ready(payload)


def _route_contract(
    route_family: str,
    latency_posture: RouteLatencyPosture,
    hot_path_budget_ms: float,
    *,
    live_probe_budget_ms: float = 0.0,
    cache_family: str = "",
    cache_ttl_ms: float = 0.0,
    stale_allowed: bool = False,
    async_continuation_allowed: bool = False,
    worker_lane: str = "interactive",
    detail_profile_required: str = "",
    verification_required: bool = False,
    no_fake_data_rule: str = "",
) -> RouteFamilyLatencyContract:
    return RouteFamilyLatencyContract(
        route_family=route_family,
        latency_posture=latency_posture,
        hot_path_budget_ms=hot_path_budget_ms,
        live_probe_budget_ms=live_probe_budget_ms,
        cache_family=cache_family,
        cache_ttl_ms=cache_ttl_ms,
        stale_allowed=stale_allowed,
        async_continuation_allowed=async_continuation_allowed,
        worker_lane=worker_lane,
        detail_profile_required=detail_profile_required,
        verification_required=verification_required,
        no_fake_data_rule=no_fake_data_rule
        or "No fabricated values; return unsupported, cached, or deferred state when data is unavailable.",
    )


ROUTE_FAMILY_LATENCY_CONTRACTS: dict[str, RouteFamilyLatencyContract] = {
    "calculations": _route_contract("calculations", RouteLatencyPosture.INSTANT, 250.0),
    "browser_destination": _route_contract("browser_destination", RouteLatencyPosture.INSTANT, 250.0),
    "time": _route_contract("time", RouteLatencyPosture.INSTANT, 250.0),
    "weather": _route_contract(
        "weather",
        RouteLatencyPosture.BOUNDED_LIVE,
        1500.0,
        live_probe_budget_ms=750.0,
        cache_family="weather",
        cache_ttl_ms=600_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="background_refresh",
    ),
    "location": _route_contract(
        "location",
        RouteLatencyPosture.CACHED_FAST,
        500.0,
        live_probe_budget_ms=250.0,
        cache_family="location",
        cache_ttl_ms=600_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="background_refresh",
    ),
    "power": _route_contract(
        "power",
        RouteLatencyPosture.CACHED_FAST,
        500.0,
        live_probe_budget_ms=150.0,
        cache_family="system_power",
        cache_ttl_ms=30_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="background_refresh",
    ),
    "network": _route_contract(
        "network",
        RouteLatencyPosture.CACHED_FAST,
        500.0,
        live_probe_budget_ms=150.0,
        cache_family="system_network",
        cache_ttl_ms=30_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="background_refresh",
    ),
    "resources": _route_contract(
        "resources",
        RouteLatencyPosture.CACHED_FAST,
        500.0,
        live_probe_budget_ms=150.0,
        cache_family="system_resources",
        cache_ttl_ms=30_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="background_refresh",
    ),
    "storage": _route_contract(
        "storage",
        RouteLatencyPosture.CACHED_FAST,
        500.0,
        live_probe_budget_ms=150.0,
        cache_family="system_storage",
        cache_ttl_ms=30_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="background_refresh",
    ),
    "machine": _route_contract(
        "machine",
        RouteLatencyPosture.CACHED_FAST,
        500.0,
        cache_family="machine_status",
        cache_ttl_ms=60_000.0,
        stale_allowed=True,
    ),
    "hardware_telemetry": _route_contract(
        "hardware_telemetry",
        RouteLatencyPosture.ASYNC_CONTINUATION,
        500.0,
        live_probe_budget_ms=150.0,
        cache_family="hardware_telemetry",
        cache_ttl_ms=30_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="background_refresh",
        detail_profile_required="deck_detail",
    ),
    "workspace_operations": _route_contract(
        "workspace_operations",
        RouteLatencyPosture.ASYNC_CONTINUATION,
        750.0,
        cache_family="workspace_summary",
        cache_ttl_ms=120_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="normal",
        detail_profile_required="deck_summary",
    ),
    "task_continuity": _route_contract(
        "task_continuity",
        RouteLatencyPosture.CACHED_FAST,
        500.0,
        cache_family="task_continuity",
        cache_ttl_ms=120_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="background_refresh",
    ),
    "file_operation": _route_contract(
        "file_operation",
        RouteLatencyPosture.ASYNC_CONTINUATION,
        500.0,
        async_continuation_allowed=True,
        worker_lane="normal",
        verification_required=True,
        detail_profile_required="deck_summary",
    ),
    "desktop_search": _route_contract(
        "desktop_search",
        RouteLatencyPosture.ASYNC_CONTINUATION,
        500.0,
        cache_family="desktop_search",
        cache_ttl_ms=120_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="normal",
        detail_profile_required="deck_summary",
    ),
    "app_control": _route_contract(
        "app_control",
        RouteLatencyPosture.BOUNDED_LIVE,
        750.0,
        live_probe_budget_ms=500.0,
        async_continuation_allowed=True,
        verification_required=True,
    ),
    "window_control": _route_contract(
        "window_control",
        RouteLatencyPosture.BOUNDED_LIVE,
        750.0,
        live_probe_budget_ms=500.0,
        async_continuation_allowed=True,
        verification_required=True,
    ),
    "system_control": _route_contract(
        "system_control",
        RouteLatencyPosture.BOUNDED_LIVE,
        750.0,
        live_probe_budget_ms=500.0,
        async_continuation_allowed=True,
        verification_required=True,
    ),
    "software_control": _route_contract(
        "software_control",
        RouteLatencyPosture.ASYNC_CONTINUATION,
        750.0,
        async_continuation_allowed=True,
        worker_lane="normal",
        verification_required=True,
        detail_profile_required="deck_summary",
    ),
    "software_recovery": _route_contract(
        "software_recovery",
        RouteLatencyPosture.ASYNC_CONTINUATION,
        750.0,
        async_continuation_allowed=True,
        worker_lane="normal",
        verification_required=True,
        detail_profile_required="deck_summary",
    ),
    "discord_relay": _route_contract(
        "discord_relay",
        RouteLatencyPosture.ASYNC_CONTINUATION,
        500.0,
        async_continuation_allowed=True,
        worker_lane="normal",
        verification_required=True,
    ),
    "screen_awareness": _route_contract(
        "screen_awareness",
        RouteLatencyPosture.CLARIFICATION,
        500.0,
        cache_family="screen_awareness",
        cache_ttl_ms=5_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="normal",
        verification_required=True,
        no_fake_data_rule="Never impersonate pixels or clipboard-only evidence as live screen data.",
    ),
    "trust_approvals": _route_contract(
        "trust_approvals",
        RouteLatencyPosture.INSTANT,
        250.0,
        verification_required=True,
    ),
    "voice_control": _route_contract("voice_control", RouteLatencyPosture.INSTANT, 250.0),
    "generic_provider": _route_contract(
        "generic_provider",
        RouteLatencyPosture.ASYNC_CONTINUATION,
        1500.0,
        live_probe_budget_ms=1000.0,
        async_continuation_allowed=True,
        worker_lane="normal",
        no_fake_data_rule="Provider fallback cannot claim native status data or invent unavailable facts.",
    ),
    "unsupported": _route_contract(
        "unsupported",
        RouteLatencyPosture.UNSUPPORTED,
        250.0,
        no_fake_data_rule="Return unsupported state instead of fabricating capability or data.",
    ),
    "context_clarification": _route_contract(
        "context_clarification",
        RouteLatencyPosture.CLARIFICATION,
        250.0,
    ),
    "semantic_memory": _route_contract(
        "semantic_memory",
        RouteLatencyPosture.ASYNC_CONTINUATION,
        750.0,
        cache_family="semantic_memory",
        cache_ttl_ms=120_000.0,
        stale_allowed=True,
        async_continuation_allowed=True,
        worker_lane="normal",
    ),
}

_ROUTE_FAMILY_CONTRACT_ALIASES = {
    "clock": "time",
    "native_unsupported": "unsupported",
    "clarification": "context_clarification",
    "file": "file_operation",
    "files": "file_operation",
    "provider": "generic_provider",
    "provider_fallback": "generic_provider",
    "recent_files": "task_continuity",
    "resource": "resources",
    "system": "machine",
    "system_overview": "machine",
    "tool_execution": "unsupported",
    "terminal": "unsupported",
    "shell_command": "unsupported",
}


def get_route_latency_contract(route_family: str | None) -> RouteFamilyLatencyContract:
    family = str(route_family or "unsupported").strip().lower() or "unsupported"
    family = _ROUTE_FAMILY_CONTRACT_ALIASES.get(family, family)
    return ROUTE_FAMILY_LATENCY_CONTRACTS.get(
        family,
        _route_contract(
            family,
            RouteLatencyPosture.UNSUPPORTED,
            250.0,
            no_fake_data_rule="Unknown route family has no live hot-path authority.",
        ),
    )


@dataclass(slots=True)
class LatencyStage:
    name: str
    started_at_monotonic: float | None = None
    ended_at_monotonic: float | None = None
    duration_ms: float = 0.0
    subsystem: str | None = None
    route_family: str | None = None
    status: str = "completed"
    budget_ms: float | None = None
    exceeded_budget: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        duration_ms = _safe_float(self.duration_ms)
        budget_ms = None if self.budget_ms is None else _safe_float(self.budget_ms)
        payload = {
            "name": self.name,
            "started_at_monotonic": self.started_at_monotonic,
            "ended_at_monotonic": self.ended_at_monotonic,
            "duration_ms": duration_ms,
            "subsystem": self.subsystem,
            "route_family": self.route_family,
            "status": self.status,
            "budget_ms": budget_ms,
            "exceeded_budget": bool(
                self.exceeded_budget
                or (budget_ms is not None and duration_ms > budget_ms)
            ),
            "metadata": safe_latency_value(self.metadata),
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(slots=True)
class LatencyTrace:
    trace_id: str = ""
    request_id: str = ""
    session_id: str = ""
    surface_mode: str = ""
    active_module: str = ""
    route_family: str | None = None
    subsystem: str | None = None
    request_kind: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    total_ms: float = 0.0
    budget: LatencyBudget | None = None
    stages: list[LatencyStage] = field(default_factory=list)
    stage_timings_ms: dict[str, float] = field(default_factory=dict)
    async_continuation: bool = False
    provider_called: bool = False
    openai_called: bool = False
    llm_called: bool = False
    embedding_called: bool = False
    voice_involved: bool = False
    job_count: int = 0
    event_count: int = 0
    execution_plan_type: str | None = None
    query_shape: str | None = None
    result_state: str | None = None
    trust_posture: str | None = None
    verification_posture: str | None = None
    provider_fallback_used: bool = False
    provider_eligibility: dict[str, Any] = field(default_factory=dict)
    provider_latency_summary: dict[str, Any] = field(default_factory=dict)
    provider_audit_timing: dict[str, Any] = field(default_factory=dict)
    subsystem_id: str = ""
    hot_path_name: str = ""
    latency_mode: str = ""
    cache_hit: bool = False
    cache_age_ms: float | None = None
    cache_policy_id: str = ""
    live_probe_started: bool = False
    heavy_context_used: bool = False
    planner_fast_path_used: bool = False
    route_handler_ms: float | None = None
    execution_mode: str | None = None
    async_expected: bool = False
    first_feedback_ms: float | None = None
    partial_response_returned: bool = False
    budget_exceeded_continuing: bool = False
    fail_fast_reason: str = ""
    route_triage_ms: float = 0.0
    route_triage_result: dict[str, Any] = field(default_factory=dict)
    triage_confidence: float = 0.0
    triage_reason_codes: list[str] = field(default_factory=list)
    likely_route_families: list[str] = field(default_factory=list)
    skipped_route_families: list[str] = field(default_factory=list)
    heavy_context_loaded: bool = False
    heavy_context_reason: str = ""
    fast_path_used: bool = False
    short_circuit_route_family: str | None = None
    provider_fallback_eligible: bool = False
    provider_fallback_suppressed_reason: str = ""
    planner_candidates_pruned_count: int = 0
    route_family_seams_evaluated: list[str] = field(default_factory=list)
    route_family_seams_skipped: list[str] = field(default_factory=list)
    snapshots_checked: list[str] = field(default_factory=list)
    snapshots_used: list[str] = field(default_factory=list)
    snapshots_refreshed: list[str] = field(default_factory=list)
    snapshots_invalidated: list[str] = field(default_factory=list)
    snapshot_freshness: dict[str, str] = field(default_factory=dict)
    snapshot_age_ms: dict[str, float] = field(default_factory=dict)
    snapshot_hot_path_hit: bool = False
    snapshot_miss_reason: dict[str, str] = field(default_factory=dict)
    heavy_context_avoided_by_snapshot: bool = False
    stale_snapshot_used_cautiously: bool = False
    invalidation_count: int = 0
    freshness_warnings: list[str] = field(default_factory=list)
    async_strategy: str = ""
    async_initial_response_returned: bool = False
    route_continuation_id: str = ""
    async_route_handle: dict[str, Any] = field(default_factory=dict)
    route_progress_state: dict[str, Any] = field(default_factory=dict)
    route_progress_stage: str = ""
    route_progress_status: str = ""
    progress_event_count: int = 0
    job_required: bool = False
    task_required: bool = False
    event_progress_required: bool = False
    worker_lane: str = ""
    worker_priority: str = ""
    queue_depth_at_submit: int = 0
    queue_wait_ms: float = 0.0
    job_start_delay_ms: float = 0.0
    job_run_ms: float = 0.0
    job_total_ms: float = 0.0
    worker_index: int | None = None
    workers_busy_at_submit: int = 0
    workers_idle_at_submit: int = 0
    worker_saturation_percent: float = 0.0
    interactive_jobs_waiting: int = 0
    background_jobs_running: int = 0
    background_job_count: int = 0
    interactive_job_count: int = 0
    starvation_detected: bool = False
    worker_capacity: int = 0
    async_worker_utilization_summary: dict[str, Any] = field(default_factory=dict)
    scheduler_strategy: str = ""
    scheduler_pressure_state: str = ""
    scheduler_pressure_reasons: list[str] = field(default_factory=list)
    protected_interactive_capacity: int = 0
    background_capacity_limit: int = 0
    protected_capacity_wait_reason: str = ""
    queue_wait_budget_ms: float | None = None
    queue_wait_budget_exceeded: bool = False
    subsystem_cap_key: str = ""
    subsystem_cap_limit: int | None = None
    subsystem_cap_wait_ms: float = 0.0
    retry_policy: str = ""
    retry_count: int = 0
    retry_max_attempts: int = 0
    retry_backoff_ms: float = 0.0
    retry_last_error: str = ""
    attempt_count: int = 0
    cancellation_state: str = ""
    yield_state: str = ""
    restart_recovery_state: str = ""
    subsystem_continuation_created: bool = False
    subsystem_continuation_id: str = ""
    subsystem_continuation_kind: str = ""
    subsystem_continuation_stage: str = ""
    subsystem_continuation_status: str = ""
    subsystem_continuation_worker_lane: str = ""
    subsystem_continuation_queue_wait_ms: float = 0.0
    subsystem_continuation_run_ms: float = 0.0
    subsystem_continuation_total_ms: float = 0.0
    subsystem_continuation_progress_event_count: int = 0
    subsystem_continuation_final_result_state: str = ""
    subsystem_continuation_verification_state: str = ""
    subsystem_continuation_handler: str = ""
    subsystem_continuation_handler_implemented: bool = False
    subsystem_continuation_handler_missing_reason: str = ""
    continuation_progress_stages: list[str] = field(default_factory=list)
    continuation_verification_required: bool = False
    continuation_verification_attempted: bool = False
    continuation_verification_evidence_count: int = 0
    continuation_result_limitations: list[str] = field(default_factory=list)
    continuation_truth_clamps_applied: list[str] = field(default_factory=list)
    direct_subsystem_async_converted: bool = False
    inline_front_half_ms: float = 0.0
    worker_back_half_ms: float = 0.0
    returned_before_subsystem_completion: bool = False
    async_conversion_expected: bool = False
    async_conversion_missing_reason: str = ""
    voice_streaming_tts_enabled: bool = False
    voice_first_audio_ms: float = 0.0
    voice_core_to_first_audio_ms: float = 0.0
    voice_tts_first_chunk_ms: float = 0.0
    voice_playback_start_ms: float = 0.0
    voice_first_chunk_to_sink_accept_ms: float = 0.0
    voice_first_output_start_ms: float = 0.0
    voice_null_sink_first_accept_ms: float = 0.0
    voice_streaming_transport_kind: str = ""
    voice_sink_kind: str = ""
    voice_first_chunk_before_complete: bool = False
    voice_stream_used_by_normal_path: bool = False
    voice_streaming_miss_reason: str = ""
    voice_live_openai_voice_smoke_run: bool = False
    voice_live_openai_first_chunk_ms: float = 0.0
    voice_wake_loop_streaming_output_used: bool = False
    voice_wake_loop_streaming_miss_reason: str = ""
    voice_realtime_deferred_to_l6: bool = False
    voice_realtime_session_creation_attempted: bool = False
    voice_raw_audio_logged: bool = False
    voice_user_heard_claimed: bool = False
    voice_live_format: str = ""
    voice_streaming_fallback_used: bool = False
    voice_prewarm_used: bool = False
    voice_partial_playback: bool = False
    voice_anchor_state: str = ""
    voice_speaking_visual_active: bool = False
    voice_audio_reactive_source: str = ""
    voice_audio_reactive_available: bool = False
    voice_anchor_motion_intensity: float = 0.0
    voice_anchor_audio_level: float = 0.0
    voice_visualizer_update_hz: int = 0
    voice_anchor_user_heard_claimed: bool = False
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.trace_id:
            self.trace_id = f"latency-{uuid4().hex}"
        if not self.request_id:
            self.request_id = self.trace_id
        policy = classify_route_latency_policy(
            route_family=self.route_family,
            subsystem=self.subsystem,
            request_kind=self.request_kind,
            execution_plan_type=self.execution_plan_type,
            surface_mode=self.surface_mode,
            active_module=self.active_module,
            result_state=self.result_state,
            fail_fast_reason=self.fail_fast_reason,
        )
        if self.budget is None:
            self.budget = policy.budget
        if self.execution_mode is None:
            self.execution_mode = policy.execution_mode.value
        if not self.async_expected:
            self.async_expected = policy.async_expected
        if not self.stage_timings_ms and self.stages:
            self.stage_timings_ms = {
                stage.name: _safe_float(stage.duration_ms)
                for stage in self.stages
            }

    @property
    def longest_stage(self) -> str:
        return self._longest_stage_pair()[0]

    @property
    def longest_stage_ms(self) -> float:
        return self._longest_stage_pair()[1]

    def budget_result(self) -> LatencyBudgetResult:
        budget = self.budget or LatencyBudget.for_label(None)
        return budget.evaluate(self.total_ms)

    def to_summary_dict(self) -> dict[str, Any]:
        budget = self.budget or LatencyBudget.for_label(None)
        result = self.budget_result()
        policy = classify_route_latency_policy(
            route_family=self.route_family,
            subsystem=self.subsystem,
            request_kind=self.request_kind,
            execution_plan_type=self.execution_plan_type,
            surface_mode=self.surface_mode,
            active_module=self.active_module,
            result_state=self.result_state,
            fail_fast_reason=self.fail_fast_reason,
        )
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "surface_mode": self.surface_mode,
            "active_module": self.active_module,
            "route_family": self.route_family,
            "subsystem": self.subsystem,
            "request_kind": self.request_kind,
            "total_ms": _safe_float(self.total_ms),
            "budget_label": budget.label,
            "budget_target_ms": budget.target_ms,
            "budget_soft_ceiling_ms": budget.soft_ceiling_ms,
            "budget_hard_ceiling_ms": budget.hard_ceiling_ms,
            "budget_exceeded": result.budget_exceeded,
            "hard_ceiling_exceeded": result.hard_ceiling_exceeded,
            "longest_stage": self.longest_stage,
            "longest_stage_ms": self.longest_stage_ms,
            "latency_posture": _coerce_latency_posture(policy.latency_posture).value,
            "hot_path_budget_ms": policy.hot_path_budget_ms,
            "live_probe_budget_ms": policy.live_probe_budget_ms,
            "cache_family": policy.cache_family,
            "cache_ttl_ms": policy.cache_ttl_ms,
            "stale_allowed": bool(policy.stale_allowed),
            "async_continuation_allowed": bool(policy.async_continuation_allowed),
            "no_fake_data_rule": policy.no_fake_data_rule,
            "subsystem_id": self.subsystem_id,
            "hot_path_name": self.hot_path_name,
            "latency_mode": self.latency_mode,
            "cache_hit": bool(self.cache_hit),
            "cache_age_ms": self.cache_age_ms,
            "cache_policy_id": self.cache_policy_id,
            "live_probe_started": bool(self.live_probe_started),
            "heavy_context_used": bool(self.heavy_context_used),
            "planner_fast_path_used": bool(self.planner_fast_path_used),
            "route_handler_ms": self.route_handler_ms,
            "execution_mode": self.execution_mode,
            "async_expected": bool(self.async_expected),
            "first_feedback_ms": self.first_feedback_ms,
            "partial_response_returned": bool(self.partial_response_returned),
            "budget_exceeded_continuing": bool(self.budget_exceeded_continuing),
            "fail_fast_reason": self.fail_fast_reason,
            "route_triage_ms": _safe_float(self.route_triage_ms),
            "route_triage_result": safe_latency_value(self.route_triage_result),
            "triage_confidence": _safe_float(self.triage_confidence),
            "triage_reason_codes": list(self.triage_reason_codes[:12]),
            "likely_route_families": list(self.likely_route_families[:12]),
            "skipped_route_families": list(self.skipped_route_families[:16]),
            "heavy_context_loaded": bool(self.heavy_context_loaded),
            "heavy_context_reason": self.heavy_context_reason,
            "fast_path_used": bool(self.fast_path_used),
            "short_circuit_route_family": self.short_circuit_route_family,
            "provider_fallback_eligible": bool(self.provider_fallback_eligible),
            "provider_fallback_suppressed_reason": self.provider_fallback_suppressed_reason,
            "planner_candidates_pruned_count": int(self.planner_candidates_pruned_count or 0),
            "route_family_seams_evaluated": list(self.route_family_seams_evaluated[:12]),
            "route_family_seams_skipped": list(self.route_family_seams_skipped[:12]),
            "snapshots_checked": list(self.snapshots_checked[:16]),
            "snapshots_used": list(self.snapshots_used[:16]),
            "snapshots_refreshed": list(self.snapshots_refreshed[:16]),
            "snapshots_invalidated": list(self.snapshots_invalidated[:16]),
            "snapshot_freshness": safe_latency_value(self.snapshot_freshness),
            "snapshot_age_ms": _rounded_float_dict(self.snapshot_age_ms),
            "snapshot_hot_path_hit": bool(self.snapshot_hot_path_hit),
            "snapshot_miss_reason": safe_latency_value(self.snapshot_miss_reason),
            "heavy_context_avoided_by_snapshot": bool(self.heavy_context_avoided_by_snapshot),
            "stale_snapshot_used_cautiously": bool(self.stale_snapshot_used_cautiously),
            "invalidation_count": int(self.invalidation_count or 0),
            "freshness_warnings": list(self.freshness_warnings[:10]),
            "async_continuation": bool(self.async_continuation),
            "async_strategy": self.async_strategy,
            "async_initial_response_returned": bool(self.async_initial_response_returned),
            "route_continuation_id": self.route_continuation_id,
            "async_route_handle": safe_latency_value(self.async_route_handle),
            "route_progress_state": safe_latency_value(self.route_progress_state),
            "route_progress_stage": self.route_progress_stage,
            "route_progress_status": self.route_progress_status,
            "progress_event_count": int(self.progress_event_count or 0),
            "job_required": bool(self.job_required),
            "task_required": bool(self.task_required),
            "event_progress_required": bool(self.event_progress_required),
            "worker_lane": self.worker_lane,
            "worker_priority": self.worker_priority,
            "queue_depth_at_submit": int(self.queue_depth_at_submit or 0),
            "queue_wait_ms": _safe_float(self.queue_wait_ms),
            "job_start_delay_ms": _safe_float(self.job_start_delay_ms),
            "job_run_ms": _safe_float(self.job_run_ms),
            "job_total_ms": _safe_float(self.job_total_ms),
            "worker_index": self.worker_index,
            "worker_capacity": int(self.worker_capacity or 0),
            "workers_busy_at_submit": int(self.workers_busy_at_submit or 0),
            "workers_idle_at_submit": int(self.workers_idle_at_submit or 0),
            "worker_saturation_percent": _safe_float(self.worker_saturation_percent),
            "interactive_jobs_waiting": int(self.interactive_jobs_waiting or 0),
            "background_jobs_running": int(self.background_jobs_running or 0),
            "background_job_count": int(self.background_job_count or 0),
            "interactive_job_count": int(self.interactive_job_count or 0),
            "starvation_detected": bool(self.starvation_detected),
            "async_worker_utilization_summary": safe_latency_value(self.async_worker_utilization_summary),
            "scheduler_strategy": self.scheduler_strategy,
            "scheduler_pressure_state": self.scheduler_pressure_state,
            "scheduler_pressure_reasons": list(self.scheduler_pressure_reasons[:8]),
            "protected_interactive_capacity": int(self.protected_interactive_capacity or 0),
            "background_capacity_limit": int(self.background_capacity_limit or 0),
            "protected_capacity_wait_reason": self.protected_capacity_wait_reason,
            "queue_wait_budget_ms": (
                None if self.queue_wait_budget_ms is None else _safe_float(self.queue_wait_budget_ms)
            ),
            "queue_wait_budget_exceeded": bool(self.queue_wait_budget_exceeded),
            "subsystem_cap_key": self.subsystem_cap_key,
            "subsystem_cap_limit": self.subsystem_cap_limit,
            "subsystem_cap_wait_ms": _safe_float(self.subsystem_cap_wait_ms),
            "retry_policy": self.retry_policy,
            "retry_count": int(self.retry_count or 0),
            "retry_max_attempts": int(self.retry_max_attempts or 0),
            "retry_backoff_ms": _safe_float(self.retry_backoff_ms),
            "retry_last_error": self.retry_last_error,
            "attempt_count": int(self.attempt_count or 0),
            "cancellation_state": self.cancellation_state,
            "yield_state": self.yield_state,
            "restart_recovery_state": self.restart_recovery_state,
            "subsystem_continuation_created": bool(self.subsystem_continuation_created),
            "subsystem_continuation_id": self.subsystem_continuation_id,
            "subsystem_continuation_kind": self.subsystem_continuation_kind,
            "subsystem_continuation_stage": self.subsystem_continuation_stage,
            "subsystem_continuation_status": self.subsystem_continuation_status,
            "subsystem_continuation_worker_lane": self.subsystem_continuation_worker_lane,
            "subsystem_continuation_queue_wait_ms": _safe_float(self.subsystem_continuation_queue_wait_ms),
            "subsystem_continuation_run_ms": _safe_float(self.subsystem_continuation_run_ms),
            "subsystem_continuation_total_ms": _safe_float(self.subsystem_continuation_total_ms),
            "subsystem_continuation_progress_event_count": int(self.subsystem_continuation_progress_event_count or 0),
            "subsystem_continuation_final_result_state": self.subsystem_continuation_final_result_state,
            "subsystem_continuation_verification_state": self.subsystem_continuation_verification_state,
            "subsystem_continuation_handler": self.subsystem_continuation_handler,
            "subsystem_continuation_handler_implemented": bool(self.subsystem_continuation_handler_implemented),
            "subsystem_continuation_handler_missing_reason": self.subsystem_continuation_handler_missing_reason,
            "continuation_progress_stages": list(self.continuation_progress_stages[:16]),
            "continuation_verification_required": bool(self.continuation_verification_required),
            "continuation_verification_attempted": bool(self.continuation_verification_attempted),
            "continuation_verification_evidence_count": int(self.continuation_verification_evidence_count or 0),
            "continuation_result_limitations": list(self.continuation_result_limitations[:12]),
            "continuation_truth_clamps_applied": list(self.continuation_truth_clamps_applied[:12]),
            "direct_subsystem_async_converted": bool(self.direct_subsystem_async_converted),
            "inline_front_half_ms": _safe_float(self.inline_front_half_ms),
            "worker_back_half_ms": _safe_float(self.worker_back_half_ms),
            "returned_before_subsystem_completion": bool(self.returned_before_subsystem_completion),
            "async_conversion_expected": bool(self.async_conversion_expected),
            "async_conversion_missing_reason": self.async_conversion_missing_reason,
            "voice_streaming_tts_enabled": bool(self.voice_streaming_tts_enabled),
            "voice_first_audio_ms": _safe_float(self.voice_first_audio_ms),
            "voice_core_to_first_audio_ms": _safe_float(self.voice_core_to_first_audio_ms),
            "voice_tts_first_chunk_ms": _safe_float(self.voice_tts_first_chunk_ms),
            "voice_playback_start_ms": _safe_float(self.voice_playback_start_ms),
            "voice_first_chunk_to_sink_accept_ms": _safe_float(
                self.voice_first_chunk_to_sink_accept_ms
            ),
            "voice_first_output_start_ms": _safe_float(
                self.voice_first_output_start_ms
            ),
            "voice_null_sink_first_accept_ms": _safe_float(
                self.voice_null_sink_first_accept_ms
            ),
            "voice_streaming_transport_kind": self.voice_streaming_transport_kind,
            "voice_sink_kind": self.voice_sink_kind,
            "voice_first_chunk_before_complete": bool(self.voice_first_chunk_before_complete),
            "voice_stream_used_by_normal_path": bool(self.voice_stream_used_by_normal_path),
            "voice_streaming_miss_reason": self.voice_streaming_miss_reason,
            "voice_live_openai_voice_smoke_run": bool(
                self.voice_live_openai_voice_smoke_run
            ),
            "voice_live_openai_first_chunk_ms": _safe_float(
                self.voice_live_openai_first_chunk_ms
            ),
            "voice_wake_loop_streaming_output_used": bool(
                self.voice_wake_loop_streaming_output_used
            ),
            "voice_wake_loop_streaming_miss_reason": (
                self.voice_wake_loop_streaming_miss_reason
            ),
            "voice_realtime_deferred_to_l6": bool(self.voice_realtime_deferred_to_l6),
            "voice_realtime_session_creation_attempted": bool(
                self.voice_realtime_session_creation_attempted
            ),
            "voice_user_heard_claimed": bool(self.voice_user_heard_claimed),
            "voice_live_format": self.voice_live_format,
            "voice_streaming_fallback_used": bool(self.voice_streaming_fallback_used),
            "voice_prewarm_used": bool(self.voice_prewarm_used),
            "voice_partial_playback": bool(self.voice_partial_playback),
            "voice_anchor_state": self.voice_anchor_state,
            "voice_speaking_visual_active": bool(self.voice_speaking_visual_active),
            "voice_audio_reactive_source": self.voice_audio_reactive_source,
            "voice_audio_reactive_available": bool(
                self.voice_audio_reactive_available
            ),
            "voice_anchor_motion_intensity": _safe_float(
                self.voice_anchor_motion_intensity
            ),
            "voice_anchor_audio_level": _safe_float(self.voice_anchor_audio_level),
            "voice_visualizer_update_hz": int(self.voice_visualizer_update_hz or 0),
            "voice_anchor_user_heard_claimed": bool(
                self.voice_anchor_user_heard_claimed
            ),
            "provider_called": bool(self.provider_called),
            "openai_called": bool(self.openai_called),
            "llm_called": bool(self.llm_called),
            "embedding_called": bool(self.embedding_called),
            "voice_involved": bool(self.voice_involved),
            "job_count": int(self.job_count or 0),
            "event_count": int(self.event_count or 0),
            "execution_plan_type": self.execution_plan_type,
            "query_shape": self.query_shape,
            "result_state": self.result_state,
            "trust_posture": self.trust_posture,
            "verification_posture": self.verification_posture,
            "provider_fallback_used": bool(self.provider_fallback_used),
            "provider_eligibility": safe_latency_value(self.provider_eligibility),
            "provider_latency_summary": safe_latency_value(
                self.provider_latency_summary
            ),
            "provider_audit_timing": safe_latency_value(self.provider_audit_timing),
            "provider_fallback_allowed": bool(
                self.provider_eligibility.get("provider_fallback_allowed")
                or self.provider_latency_summary.get("fallback_allowed")
            ),
            "provider_fallback_blocked_reason": str(
                self.provider_eligibility.get("provider_fallback_blocked_reason")
                or ""
            ),
            "provider_fallback_reason": str(
                self.provider_eligibility.get("provider_fallback_reason")
                or self.provider_latency_summary.get("fallback_reason")
                or ""
            ),
            "provider_name": str(self.provider_latency_summary.get("provider_name") or ""),
            "provider_model_name": str(
                self.provider_latency_summary.get("model_name") or ""
            ),
            "provider_streaming_enabled": bool(
                self.provider_latency_summary.get("streaming_enabled")
            ),
            "provider_streaming_used": bool(
                self.provider_latency_summary.get("streaming_used")
            ),
            "provider_cancellation_supported": bool(
                self.provider_latency_summary.get("cancellation_supported")
            ),
            "provider_first_byte_ms": _optional_safe_float(
                self.provider_latency_summary.get("first_byte_ms")
            ),
            "provider_first_token_ms": _optional_safe_float(
                self.provider_latency_summary.get("first_token_ms")
            ),
            "provider_first_output_ms": _optional_safe_float(
                self.provider_latency_summary.get("first_output_ms")
            ),
            "provider_total_ms": _optional_safe_float(
                self.provider_latency_summary.get("total_provider_ms")
            ),
            "provider_total_user_visible_ms": _optional_safe_float(
                self.provider_latency_summary.get("total_user_visible_ms")
            ),
            "provider_timeout_ms": _optional_safe_float(
                self.provider_latency_summary.get("timeout_ms")
            ),
            "provider_timeout_hit": bool(
                self.provider_latency_summary.get("timeout_hit")
            ),
            "provider_cancelled": bool(self.provider_latency_summary.get("cancelled")),
            "provider_failure_code": str(
                self.provider_latency_summary.get("failure_code") or ""
            ),
            "provider_budget_label": str(
                self.provider_latency_summary.get("provider_budget_label") or ""
            ),
            "provider_budget_exceeded": bool(
                self.provider_latency_summary.get("provider_budget_exceeded")
            ),
            "provider_partial_result_count": int(
                _safe_float(self.provider_latency_summary.get("partial_result_count"))
            ),
            "native_route_blocked_by_provider": bool(
                self.provider_latency_summary.get("native_route_blocked_by_provider")
            ),
            "provider_payload_redacted": bool(
                self.provider_latency_summary.get("payload_redacted", True)
            ),
            "provider_secrets_logged": bool(
                self.provider_latency_summary.get("secrets_logged")
            ),
            "warnings": list(self.warnings[:10]),
        }

    def to_dict(self) -> dict[str, Any]:
        budget = self.budget or LatencyBudget.for_label(None)
        budget_result = self.budget_result()
        payload = {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "budget_result": budget_result.to_dict(),
            "budget": budget.to_dict(),
            "stage_timings_ms": _rounded_float_dict(self.stage_timings_ms),
            "stages": [stage.to_dict() for stage in self.stages[:64]],
            **self.to_summary_dict(),
        }
        return _json_ready(payload)

    def _longest_stage_pair(self) -> tuple[str, float]:
        candidates: list[tuple[str, float]] = []
        for stage in self.stages:
            if stage.name in LATENCY_COUNTER_KEYS or stage.name in LATENCY_AGGREGATE_KEYS:
                continue
            duration = _safe_float(stage.duration_ms)
            if duration >= 0:
                candidates.append((stage.name, duration))
        if not candidates:
            for name, value in self.stage_timings_ms.items():
                if name in LATENCY_COUNTER_KEYS or name in LATENCY_AGGREGATE_KEYS:
                    continue
                duration = _safe_float(value)
                if duration >= 0:
                    candidates.append((str(name), duration))
        if not candidates:
            return "", 0.0
        return max(candidates, key=lambda item: item[1])


@dataclass(frozen=True, slots=True)
class RouteLatencyPolicy:
    route_family: str
    budget: LatencyBudget
    execution_mode: RouteExecutionMode
    async_expected: bool = False
    partial_response_allowed: bool = False
    fail_fast_reason: str = ""
    latency_posture: RouteLatencyPosture | str | None = None
    hot_path_budget_ms: float | None = None
    live_probe_budget_ms: float | None = None
    cache_family: str = ""
    cache_ttl_ms: float | None = None
    stale_allowed: bool | None = None
    async_continuation_allowed: bool | None = None
    worker_lane: str = ""
    detail_profile_required: str = ""
    verification_required: bool | None = None
    no_fake_data_rule: str = ""

    def __post_init__(self) -> None:
        contract = get_route_latency_contract(self.route_family)
        posture = _coerce_latency_posture(self.latency_posture, fallback=contract.latency_posture)
        if self.execution_mode == RouteExecutionMode.UNSUPPORTED:
            posture = RouteLatencyPosture.UNSUPPORTED
        elif self.execution_mode == RouteExecutionMode.CLARIFICATION:
            posture = RouteLatencyPosture.CLARIFICATION
        elif self.execution_mode == RouteExecutionMode.ASYNC_FIRST:
            posture = RouteLatencyPosture.ASYNC_CONTINUATION
        object.__setattr__(self, "latency_posture", posture)
        if self.hot_path_budget_ms is None:
            object.__setattr__(self, "hot_path_budget_ms", contract.hot_path_budget_ms)
        if self.live_probe_budget_ms is None:
            object.__setattr__(self, "live_probe_budget_ms", contract.live_probe_budget_ms)
        if not self.cache_family:
            object.__setattr__(self, "cache_family", contract.cache_family)
        if self.cache_ttl_ms is None:
            object.__setattr__(self, "cache_ttl_ms", contract.cache_ttl_ms)
        if self.stale_allowed is None:
            object.__setattr__(self, "stale_allowed", contract.stale_allowed)
        if self.async_continuation_allowed is None:
            object.__setattr__(
                self,
                "async_continuation_allowed",
                contract.async_continuation_allowed or self.async_expected,
            )
        if not self.worker_lane:
            object.__setattr__(self, "worker_lane", contract.worker_lane)
        if not self.detail_profile_required:
            object.__setattr__(self, "detail_profile_required", contract.detail_profile_required)
        if self.verification_required is None:
            object.__setattr__(self, "verification_required", contract.verification_required)
        if not self.no_fake_data_rule:
            object.__setattr__(self, "no_fake_data_rule", contract.no_fake_data_rule)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_family": self.route_family,
            "latency_posture": _coerce_latency_posture(self.latency_posture).value,
            "hot_path_budget_ms": self.hot_path_budget_ms,
            "live_probe_budget_ms": self.live_probe_budget_ms,
            "cache_family": self.cache_family,
            "cache_ttl_ms": self.cache_ttl_ms,
            "stale_allowed": bool(self.stale_allowed),
            "async_continuation_allowed": bool(self.async_continuation_allowed),
            "worker_lane": self.worker_lane,
            "detail_profile_required": self.detail_profile_required,
            "verification_required": bool(self.verification_required),
            "no_fake_data_rule": self.no_fake_data_rule,
            "budget": self.budget.to_dict(),
            "budget_label": self.budget.label,
            "execution_mode": self.execution_mode.value,
            "async_expected": self.async_expected,
            "partial_response_allowed": self.partial_response_allowed,
            "fail_fast_reason": self.fail_fast_reason,
        }


def _coerce_latency_posture(
    value: RouteLatencyPosture | str | None,
    *,
    fallback: RouteLatencyPosture = RouteLatencyPosture.UNSUPPORTED,
) -> RouteLatencyPosture:
    if isinstance(value, RouteLatencyPosture):
        return value
    if value is None or value == "":
        return fallback
    try:
        return RouteLatencyPosture(str(value).strip())
    except ValueError:
        return fallback


@dataclass(frozen=True, slots=True)
class RouteLatencySummary:
    route_family: str | None
    subsystem: str | None
    total_ms: float
    longest_stage: str
    longest_stage_ms: float
    budget_result: LatencyBudgetResult
    provider_called: bool = False
    async_continuation: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["budget_result"] = self.budget_result.to_dict()
        return _json_ready(payload)


@dataclass(frozen=True, slots=True)
class VoiceLatencySummary:
    request_id: str
    session_id: str
    total_ms: float
    longest_stage: str
    longest_stage_ms: float
    budget_result: LatencyBudgetResult
    stage_timings_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["budget_result"] = self.budget_result.to_dict()
        return _json_ready(payload)


@dataclass(frozen=True, slots=True)
class KrakenLatencyReport:
    total_latency_ms: dict[str, Any]
    by_route_family: dict[str, dict[str, Any]]
    by_longest_stage: dict[str, dict[str, Any]]
    budget_exceeded_count: int
    hard_timeout_count: int
    provider_call_count: int
    top_10_slowest_rows: list[dict[str, Any]]
    top_route_handler_offenders: list[dict[str, Any]]
    top_planner_offenders: list[dict[str, Any]]
    top_response_serialization_offenders: list[dict[str, Any]]
    known_slow_lanes: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


LATENCY_BUDGETS: dict[str, LatencyBudget] = {
    "ghost_interactive": LatencyBudget(
        "ghost_interactive",
        1500.0,
        2500.0,
        5000.0,
        target_first_feedback_ms=250.0,
        target_total_ms=1500.0,
    ),
    "voice_hot_path": LatencyBudget(
        "voice_hot_path",
        3000.0,
        4000.0,
        8000.0,
        target_first_feedback_ms=250.0,
        target_core_result_ms=1500.0,
        target_first_audio_ms=3000.0,
    ),
    "deck_work": LatencyBudget(
        "deck_work",
        2500.0,
        5000.0,
        10000.0,
        target_first_feedback_ms=500.0,
        target_initial_plan_ms=2500.0,
    ),
    "long_task": LatencyBudget(
        "long_task",
        500.0,
        1500.0,
        10000.0,
        True,
        target_ack_ms=500.0,
        target_initial_plan_ms=2000.0,
    ),
    "provider_fallback": LatencyBudget(
        "provider_fallback",
        3000.0,
        6000.0,
        12000.0,
        target_first_feedback_ms=750.0,
        target_total_ms=3000.0,
    ),
    "background_job": LatencyBudget(
        "background_job",
        5000.0,
        15000.0,
        30000.0,
        True,
        target_ack_ms=500.0,
    ),
    "test_eval": LatencyBudget(
        "test_eval",
        2500.0,
        5000.0,
        10000.0,
        target_first_feedback_ms=250.0,
    ),
}

STAGE_BUDGETS_MS: dict[str, float] = {
    "planner_route_ms": 1000.0,
    "route_handler_ms": 2500.0,
    "provider_call_ms": 6000.0,
    "provider_fallback_ms": 6000.0,
    "db_write_ms": 500.0,
    "response_compose_ms": 500.0,
    "response_serialization_ms": 500.0,
    "payload_compaction_ms": 500.0,
    "endpoint_dispatch_ms": 5000.0,
    "endpoint_return_to_asgi_ms": 500.0,
}


def classify_latency_budget(
    *,
    surface_mode: str | None = None,
    active_module: str | None = None,
    route_family: str | None = None,
    request_kind: str | None = None,
    provider_called: bool = False,
    voice_involved: bool = False,
) -> LatencyBudget:
    kind = str(request_kind or "").strip().lower()
    family = str(route_family or "").strip().lower()
    surface = str(surface_mode or "").strip().lower()
    module = str(active_module or "").strip().lower()
    if kind in LATENCY_BUDGETS:
        return LatencyBudget.for_label(kind)
    if voice_involved or family == "voice_control":
        return LatencyBudget.for_label("voice_hot_path")
    if provider_called or family == "generic_provider":
        return LatencyBudget.for_label("provider_fallback")
    if kind in {"background_job", "background"}:
        return LatencyBudget.for_label("background_job")
    if kind in {"long_task", "async_continuation"}:
        return LatencyBudget.for_label("long_task")
    if surface == "deck" or module in {"deck", "command_deck"}:
        return LatencyBudget.for_label("deck_work")
    return LatencyBudget.for_label("ghost_interactive")


def classify_route_latency_policy(
    *,
    route_family: str | None = None,
    subsystem: str | None = None,
    request_kind: str | None = None,
    execution_plan_type: str | None = None,
    surface_mode: str | None = None,
    active_module: str | None = None,
    result_state: str | None = None,
    fail_fast_reason: str | None = None,
) -> RouteLatencyPolicy:
    family = str(route_family or "unknown").strip().lower() or "unknown"
    subsystem_key = str(subsystem or "").strip().lower()
    kind = str(request_kind or "").strip().lower()
    plan = str(execution_plan_type or "").strip().lower()
    state = str(result_state or "").strip().lower()
    fail_fast = str(fail_fast_reason or "").strip()

    if fail_fast:
        if family == "generic_provider":
            budget = LatencyBudget.for_label("provider_fallback")
        elif family == "voice_control":
            budget = LatencyBudget.for_label("voice_hot_path")
        else:
            budget = LatencyBudget.for_label("ghost_interactive")
        return RouteLatencyPolicy(
            route_family=family,
            budget=budget,
            execution_mode=RouteExecutionMode.UNSUPPORTED,
            partial_response_allowed=True,
            fail_fast_reason=fail_fast,
        )
    if family in {"unsupported", "native_unsupported"} or state in {"unsupported", "blocked"}:
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("ghost_interactive"),
            execution_mode=RouteExecutionMode.UNSUPPORTED,
            partial_response_allowed=True,
        )
    if family == "context_clarification" or state == "clarification":
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("ghost_interactive"),
            execution_mode=RouteExecutionMode.CLARIFICATION,
            partial_response_allowed=True,
        )
    if family == "generic_provider":
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("provider_fallback"),
            execution_mode=RouteExecutionMode.PROVIDER_WAIT,
            partial_response_allowed=True,
        )
    if family in {"calculations", "browser_destination", "time", "trust_approvals"}:
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("ghost_interactive"),
            execution_mode=RouteExecutionMode.INSTANT,
        )
    if family == "voice_control":
        budget_label = "voice_hot_path" if str(surface_mode or "").lower() == "voice" else "ghost_interactive"
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label(budget_label),
            execution_mode=RouteExecutionMode.INSTANT,
        )
    if family == "software_control":
        execution_like = any(
            marker in f"{kind} {plan} {state}"
            for marker in ("software_execution", "execute_approved", "running", "queued", "verification_pending")
        )
        if execution_like:
            return RouteLatencyPolicy(
                route_family=family,
                budget=LatencyBudget.for_label("long_task"),
                execution_mode=RouteExecutionMode.ASYNC_FIRST,
                async_expected=True,
                partial_response_allowed=True,
            )
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("ghost_interactive"),
            execution_mode=RouteExecutionMode.PLAN_FIRST,
            partial_response_allowed=True,
        )
    if family == "software_recovery":
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("long_task"),
            execution_mode=RouteExecutionMode.ASYNC_FIRST,
            async_expected=True,
            partial_response_allowed=True,
        )
    if family == "discord_relay":
        if "dispatch" in plan or "dispatch" in kind:
            return RouteLatencyPolicy(
                route_family=family,
                budget=LatencyBudget.for_label("long_task"),
                execution_mode=RouteExecutionMode.ASYNC_FIRST,
                async_expected=True,
                partial_response_allowed=True,
            )
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("ghost_interactive"),
            execution_mode=RouteExecutionMode.PLAN_FIRST,
            partial_response_allowed=True,
        )
    if family == "screen_awareness":
        if any(marker in f"{kind} {plan}" for marker in ("action", "verify", "verification", "workflow", "continue")):
            return RouteLatencyPolicy(
                route_family=family,
                budget=LatencyBudget.for_label("long_task"),
                execution_mode=RouteExecutionMode.ASYNC_FIRST,
                async_expected=True,
                partial_response_allowed=True,
            )
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("ghost_interactive"),
            execution_mode=RouteExecutionMode.INSTANT,
        )
    if family in {"workspace_operations", "task_continuity", "semantic_memory"}:
        if any(marker in f"{kind} {plan}" for marker in ("assemble", "restore", "deep", "scan", "index")):
            return RouteLatencyPolicy(
                route_family=family,
                budget=LatencyBudget.for_label("long_task"),
                execution_mode=RouteExecutionMode.ASYNC_FIRST,
                async_expected=True,
                partial_response_allowed=True,
            )
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("ghost_interactive"),
            execution_mode=RouteExecutionMode.INSTANT,
        )
    if family in {"desktop_search", "file_operation", "hardware_telemetry"}:
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("long_task"),
            execution_mode=RouteExecutionMode.ASYNC_FIRST,
            async_expected=True,
            partial_response_allowed=True,
        )
    if family in {"network", "machine", "system_control", "storage", "power", "resources"}:
        live_probe = any(marker in f"{kind} {plan} {subsystem_key}" for marker in ("probe", "diagnostic", "scan", "live"))
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("long_task" if live_probe else "ghost_interactive"),
            execution_mode=RouteExecutionMode.ASYNC_FIRST if live_probe else RouteExecutionMode.INSTANT,
            async_expected=live_probe,
            partial_response_allowed=live_probe,
        )
    if family in {"terminal", "shell_command"}:
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("ghost_interactive"),
            execution_mode=RouteExecutionMode.UNSUPPORTED,
            partial_response_allowed=True,
            fail_fast_reason="shell_command_disabled",
        )
    if str(active_module or "").strip().lower() in {"deck", "command_deck"}:
        return RouteLatencyPolicy(
            route_family=family,
            budget=LatencyBudget.for_label("deck_work"),
            execution_mode=RouteExecutionMode.PLAN_FIRST,
            partial_response_allowed=True,
        )
    return RouteLatencyPolicy(
        route_family=family,
        budget=LatencyBudget.for_label("ghost_interactive"),
        execution_mode=RouteExecutionMode.INSTANT,
    )


def build_partial_response_posture(
    *,
    route_family: str | None,
    subsystem: str | None,
    assistant_message: str,
    result_state: str | None,
    verification_state: str | None,
    latency_trace_id: str,
    policy: RouteLatencyPolicy,
    budget_exceeded: bool = False,
    async_continuation: bool = False,
    continue_reason: str = "",
    task_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    state = _normalized_result_state(result_state, policy)
    verification = str(verification_state or "not_verified").strip() or "not_verified"
    completion_claimed = _completion_claimed(state)
    verification_claimed = verification == "verified" or state == "verified"
    partial_returned = bool(policy.partial_response_allowed and not completion_claimed)
    failed = state == "failed"
    return safe_latency_value(
        {
            "result_state": state,
            "route_family": route_family,
            "subsystem": subsystem,
            "assistant_message": str(assistant_message or "")[:500],
            "task_id": task_id,
            "job_id": job_id,
            "events_expected": bool(partial_returned or async_continuation or policy.async_expected),
            "async_continuation": bool(async_continuation or policy.async_expected),
            "async_expected": bool(policy.async_expected),
            "verification_state": verification,
            "completion_claimed": completion_claimed,
            "verification_claimed": verification_claimed,
            "latency_trace_id": latency_trace_id,
            "budget_label": policy.budget.label,
            "budget_exceeded": bool(budget_exceeded),
            "budget_exceeded_continuing": bool(budget_exceeded and (partial_returned or async_continuation or policy.async_expected)),
            "partial_response_returned": partial_returned,
            "continue_reason": continue_reason,
            "execution_mode": policy.execution_mode.value,
            "failed": failed,
        }
    )


def build_latency_trace(
    *,
    metadata: dict[str, Any] | None = None,
    stage_timings_ms: dict[str, Any] | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    session_id: str = "",
    surface_mode: str = "",
    active_module: str = "",
    route_family: str | None = None,
    subsystem: str | None = None,
    request_kind: str | None = None,
    total_ms: float | None = None,
    budget_label: str | None = None,
    provider_called: bool | None = None,
    openai_called: bool | None = None,
    llm_called: bool | None = None,
    embedding_called: bool | None = None,
    voice_involved: bool = False,
    job_count: int | None = None,
    event_count: int | None = None,
    async_continuation: bool | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> LatencyTrace:
    metadata = metadata if isinstance(metadata, dict) else {}
    timings = _rounded_float_dict(stage_timings_ms or {})
    existing_trace = (
        metadata.get("latency_trace")
        if isinstance(metadata.get("latency_trace"), dict)
        else {}
    )
    attribution = _route_attribution(metadata)
    route_family = route_family or attribution.get("route_family")
    subsystem = subsystem or attribution.get("subsystem")
    request_kind = request_kind or attribution.get("request_kind")
    provider_called = (
        bool(provider_called)
        if provider_called is not None
        else _provider_flag(metadata, "provider_called")
    )
    openai_called = (
        bool(openai_called)
        if openai_called is not None
        else _provider_flag(metadata, "openai_called") or provider_called
    )
    llm_called = (
        bool(llm_called)
        if llm_called is not None
        else _provider_flag(metadata, "llm_called") or provider_called
    )
    embedding_called = (
        bool(embedding_called)
        if embedding_called is not None
        else _provider_flag(metadata, "embedding_called")
    )
    job_count = int(job_count if job_count is not None else _metadata_count(metadata, "jobs"))
    event_count = int(event_count if event_count is not None else _safe_float(timings.get("event_count")))
    if async_continuation is None:
        async_continuation = bool(
            attribution.get("async_continuation")
            or _metadata_async_continuation(metadata)
        )
    if total_ms is None:
        total_ms = _trace_total_ms(timings)
    fail_fast_reason = str(metadata.get("fail_fast_reason") or "").strip()
    policy = classify_route_latency_policy(
        route_family=route_family,
        subsystem=subsystem,
        request_kind=request_kind,
        execution_plan_type=attribution.get("execution_plan_type"),
        surface_mode=surface_mode or str(metadata.get("surface_mode") or ""),
        active_module=active_module or str(metadata.get("active_module") or ""),
        result_state=attribution.get("result_state"),
        fail_fast_reason=fail_fast_reason,
    )
    budget = LatencyBudget.for_label(budget_label) if budget_label else policy.budget
    if budget_label is None and policy.route_family == "unknown":
        budget = classify_latency_budget(
        surface_mode=surface_mode or str(metadata.get("surface_mode") or ""),
        active_module=active_module or str(metadata.get("active_module") or ""),
        route_family=route_family,
        request_kind=request_kind,
        provider_called=provider_called,
        voice_involved=voice_involved,
        )
    stages = stages_from_stage_timings(
        timings,
        route_family=route_family,
        subsystem=subsystem,
    )
    l2_trace = _l2_trace_metadata(metadata, timings, existing_trace)
    l3_trace = _l3_trace_metadata(metadata, timings, existing_trace)
    l4_trace = _l4_trace_metadata(metadata, timings, existing_trace)
    l41_trace = _l41_trace_metadata(metadata, timings, existing_trace)
    l42_trace = _l42_trace_metadata(metadata, timings, existing_trace)
    l5_voice_trace = _l5_voice_trace_metadata(metadata, timings, existing_trace)
    l9_provider_trace = _l9_provider_trace_metadata(metadata, existing_trace)
    provider_fallback_used = bool(
        attribution.get("provider_fallback_used")
        or (provider_called and route_family == "generic_provider")
        or bool(l9_provider_trace["provider_latency_summary"])
    )
    async_continuation_used = bool(
        async_continuation
        or l4_trace["async_initial_response_returned"]
        or l42_trace["returned_before_subsystem_completion"]
    )
    l8_trace = subsystem_latency_trace_fields(
        route_family=route_family,
        subsystem=subsystem,
        request_kind=request_kind,
        metadata=metadata,
        stage_timings_ms=timings,
        provider_fallback_used=provider_fallback_used,
        heavy_context_used=bool(l2_trace["heavy_context_loaded"]),
        async_continuation=async_continuation_used,
    )
    return LatencyTrace(
        trace_id=str(trace_id or existing_trace.get("trace_id") or ""),
        request_id=str(request_id or existing_trace.get("request_id") or ""),
        session_id=session_id or str(existing_trace.get("session_id") or ""),
        surface_mode=surface_mode or str(metadata.get("surface_mode") or ""),
        active_module=active_module or str(metadata.get("active_module") or ""),
        route_family=route_family,
        subsystem=subsystem,
        request_kind=request_kind,
        started_at=started_at or existing_trace.get("started_at"),
        completed_at=completed_at or existing_trace.get("completed_at"),
        total_ms=_safe_float(total_ms),
        budget=budget,
        stages=stages,
        stage_timings_ms=timings,
        async_continuation=async_continuation_used,
        provider_called=bool(provider_called),
        openai_called=bool(openai_called),
        llm_called=bool(llm_called),
        embedding_called=bool(embedding_called),
        voice_involved=bool(voice_involved),
        job_count=job_count,
        event_count=event_count,
        execution_plan_type=attribution.get("execution_plan_type"),
        query_shape=attribution.get("query_shape"),
        result_state=attribution.get("result_state"),
        trust_posture=attribution.get("trust_posture"),
        verification_posture=attribution.get("verification_posture"),
        provider_fallback_used=provider_fallback_used,
        provider_eligibility=l9_provider_trace["provider_eligibility"],
        provider_latency_summary=l9_provider_trace["provider_latency_summary"],
        provider_audit_timing=l9_provider_trace["provider_audit_timing"],
        subsystem_id=str(l8_trace.get("subsystem_id") or ""),
        hot_path_name=str(l8_trace.get("hot_path_name") or ""),
        latency_mode=str(l8_trace.get("latency_mode") or ""),
        cache_hit=bool(l8_trace.get("cache_hit")),
        cache_age_ms=l8_trace.get("cache_age_ms"),
        cache_policy_id=str(l8_trace.get("cache_policy_id") or ""),
        live_probe_started=bool(l8_trace.get("live_probe_started")),
        heavy_context_used=bool(l8_trace.get("heavy_context_used")),
        planner_fast_path_used=bool(l8_trace.get("planner_fast_path_used")),
        route_handler_ms=l8_trace.get("route_handler_ms"),
        execution_mode=l4_trace["execution_mode"] or policy.execution_mode.value,
        async_expected=bool(
            policy.async_expected
            or l4_trace["async_initial_response_returned"]
            or l42_trace["async_conversion_expected"]
        ),
        first_feedback_ms=(
            l8_trace.get("first_feedback_ms")
            if l8_trace.get("first_feedback_ms") is not None
            else _first_feedback_ms(timings, policy)
        ),
        fail_fast_reason=fail_fast_reason or policy.fail_fast_reason,
        route_triage_ms=l2_trace["route_triage_ms"],
        route_triage_result=l2_trace["route_triage_result"],
        triage_confidence=l2_trace["triage_confidence"],
        triage_reason_codes=l2_trace["triage_reason_codes"],
        likely_route_families=l2_trace["likely_route_families"],
        skipped_route_families=l2_trace["skipped_route_families"],
        heavy_context_loaded=l2_trace["heavy_context_loaded"],
        heavy_context_reason=l2_trace["heavy_context_reason"],
        fast_path_used=l2_trace["fast_path_used"],
        short_circuit_route_family=l2_trace["short_circuit_route_family"],
        provider_fallback_eligible=l2_trace["provider_fallback_eligible"],
        provider_fallback_suppressed_reason=l2_trace["provider_fallback_suppressed_reason"],
        planner_candidates_pruned_count=l2_trace["planner_candidates_pruned_count"],
        route_family_seams_evaluated=l2_trace["route_family_seams_evaluated"],
        route_family_seams_skipped=l2_trace["route_family_seams_skipped"],
        snapshots_checked=l3_trace["snapshots_checked"],
        snapshots_used=l3_trace["snapshots_used"],
        snapshots_refreshed=l3_trace["snapshots_refreshed"],
        snapshots_invalidated=l3_trace["snapshots_invalidated"],
        snapshot_freshness=l3_trace["snapshot_freshness"],
        snapshot_age_ms=l3_trace["snapshot_age_ms"],
        snapshot_hot_path_hit=l3_trace["snapshot_hot_path_hit"],
        snapshot_miss_reason=l3_trace["snapshot_miss_reason"],
        heavy_context_avoided_by_snapshot=l3_trace["heavy_context_avoided_by_snapshot"],
        stale_snapshot_used_cautiously=l3_trace["stale_snapshot_used_cautiously"],
        invalidation_count=l3_trace["invalidation_count"],
        freshness_warnings=l3_trace["freshness_warnings"],
        async_strategy=l4_trace["async_strategy"],
        async_initial_response_returned=l4_trace["async_initial_response_returned"],
        route_continuation_id=l4_trace["route_continuation_id"],
        async_route_handle=l4_trace["async_route_handle"],
        route_progress_state=l4_trace["route_progress_state"],
        route_progress_stage=l4_trace["route_progress_stage"],
        route_progress_status=l4_trace["route_progress_status"],
        progress_event_count=l4_trace["progress_event_count"],
        job_required=l4_trace["job_required"],
        task_required=l4_trace["task_required"],
        event_progress_required=l4_trace["event_progress_required"],
        worker_lane=l41_trace["worker_lane"],
        worker_priority=l41_trace["worker_priority"],
        queue_depth_at_submit=l41_trace["queue_depth_at_submit"],
        queue_wait_ms=l41_trace["queue_wait_ms"],
        job_start_delay_ms=l41_trace["job_start_delay_ms"],
        job_run_ms=l41_trace["job_run_ms"],
        job_total_ms=l41_trace["job_total_ms"],
        worker_index=l41_trace["worker_index"],
        worker_capacity=l41_trace["worker_capacity"],
        workers_busy_at_submit=l41_trace["workers_busy_at_submit"],
        workers_idle_at_submit=l41_trace["workers_idle_at_submit"],
        worker_saturation_percent=l41_trace["worker_saturation_percent"],
        interactive_jobs_waiting=l41_trace["interactive_jobs_waiting"],
        background_jobs_running=l41_trace["background_jobs_running"],
        background_job_count=l41_trace["background_job_count"],
        interactive_job_count=l41_trace["interactive_job_count"],
        starvation_detected=l41_trace["starvation_detected"],
        async_worker_utilization_summary=l41_trace["async_worker_utilization_summary"],
        scheduler_strategy=l41_trace["scheduler_strategy"],
        scheduler_pressure_state=l41_trace["scheduler_pressure_state"],
        scheduler_pressure_reasons=l41_trace["scheduler_pressure_reasons"],
        protected_interactive_capacity=l41_trace["protected_interactive_capacity"],
        background_capacity_limit=l41_trace["background_capacity_limit"],
        protected_capacity_wait_reason=l41_trace["protected_capacity_wait_reason"],
        queue_wait_budget_ms=l41_trace["queue_wait_budget_ms"],
        queue_wait_budget_exceeded=l41_trace["queue_wait_budget_exceeded"],
        subsystem_cap_key=l41_trace["subsystem_cap_key"],
        subsystem_cap_limit=l41_trace["subsystem_cap_limit"],
        subsystem_cap_wait_ms=l41_trace["subsystem_cap_wait_ms"],
        retry_policy=l41_trace["retry_policy"],
        retry_count=l41_trace["retry_count"],
        retry_max_attempts=l41_trace["retry_max_attempts"],
        retry_backoff_ms=l41_trace["retry_backoff_ms"],
        retry_last_error=l41_trace["retry_last_error"],
        attempt_count=l41_trace["attempt_count"],
        cancellation_state=l41_trace["cancellation_state"],
        yield_state=l41_trace["yield_state"],
        restart_recovery_state=l41_trace["restart_recovery_state"],
        subsystem_continuation_created=l42_trace["subsystem_continuation_created"],
        subsystem_continuation_id=l42_trace["subsystem_continuation_id"],
        subsystem_continuation_kind=l42_trace["subsystem_continuation_kind"],
        subsystem_continuation_stage=l42_trace["subsystem_continuation_stage"],
        subsystem_continuation_status=l42_trace["subsystem_continuation_status"],
        subsystem_continuation_worker_lane=l42_trace["subsystem_continuation_worker_lane"],
        subsystem_continuation_queue_wait_ms=l42_trace["subsystem_continuation_queue_wait_ms"],
        subsystem_continuation_run_ms=l42_trace["subsystem_continuation_run_ms"],
        subsystem_continuation_total_ms=l42_trace["subsystem_continuation_total_ms"],
        subsystem_continuation_progress_event_count=l42_trace["subsystem_continuation_progress_event_count"],
        subsystem_continuation_final_result_state=l42_trace["subsystem_continuation_final_result_state"],
        subsystem_continuation_verification_state=l42_trace["subsystem_continuation_verification_state"],
        subsystem_continuation_handler=l42_trace["subsystem_continuation_handler"],
        subsystem_continuation_handler_implemented=l42_trace["subsystem_continuation_handler_implemented"],
        subsystem_continuation_handler_missing_reason=l42_trace["subsystem_continuation_handler_missing_reason"],
        continuation_progress_stages=l42_trace["continuation_progress_stages"],
        continuation_verification_required=l42_trace["continuation_verification_required"],
        continuation_verification_attempted=l42_trace["continuation_verification_attempted"],
        continuation_verification_evidence_count=l42_trace["continuation_verification_evidence_count"],
        continuation_result_limitations=l42_trace["continuation_result_limitations"],
        continuation_truth_clamps_applied=l42_trace["continuation_truth_clamps_applied"],
        direct_subsystem_async_converted=l42_trace["direct_subsystem_async_converted"],
        inline_front_half_ms=l42_trace["inline_front_half_ms"],
        worker_back_half_ms=l42_trace["worker_back_half_ms"],
        returned_before_subsystem_completion=l42_trace["returned_before_subsystem_completion"],
        async_conversion_expected=l42_trace["async_conversion_expected"],
        async_conversion_missing_reason=l42_trace["async_conversion_missing_reason"],
        voice_streaming_tts_enabled=l5_voice_trace["voice_streaming_tts_enabled"],
        voice_first_audio_ms=l5_voice_trace["voice_first_audio_ms"],
        voice_core_to_first_audio_ms=l5_voice_trace["voice_core_to_first_audio_ms"],
        voice_tts_first_chunk_ms=l5_voice_trace["voice_tts_first_chunk_ms"],
        voice_playback_start_ms=l5_voice_trace["voice_playback_start_ms"],
        voice_first_chunk_to_sink_accept_ms=l5_voice_trace[
            "voice_first_chunk_to_sink_accept_ms"
        ],
        voice_first_output_start_ms=l5_voice_trace["voice_first_output_start_ms"],
        voice_null_sink_first_accept_ms=l5_voice_trace[
            "voice_null_sink_first_accept_ms"
        ],
        voice_streaming_transport_kind=l5_voice_trace["voice_streaming_transport_kind"],
        voice_sink_kind=l5_voice_trace["voice_sink_kind"],
        voice_first_chunk_before_complete=l5_voice_trace["voice_first_chunk_before_complete"],
        voice_stream_used_by_normal_path=l5_voice_trace["voice_stream_used_by_normal_path"],
        voice_streaming_miss_reason=l5_voice_trace["voice_streaming_miss_reason"],
        voice_live_openai_voice_smoke_run=l5_voice_trace[
            "voice_live_openai_voice_smoke_run"
        ],
        voice_live_openai_first_chunk_ms=l5_voice_trace[
            "voice_live_openai_first_chunk_ms"
        ],
        voice_wake_loop_streaming_output_used=l5_voice_trace[
            "voice_wake_loop_streaming_output_used"
        ],
        voice_wake_loop_streaming_miss_reason=l5_voice_trace[
            "voice_wake_loop_streaming_miss_reason"
        ],
        voice_realtime_deferred_to_l6=l5_voice_trace["voice_realtime_deferred_to_l6"],
        voice_realtime_session_creation_attempted=l5_voice_trace[
            "voice_realtime_session_creation_attempted"
        ],
        voice_raw_audio_logged=l5_voice_trace["voice_raw_audio_logged"],
        voice_user_heard_claimed=l5_voice_trace["voice_user_heard_claimed"],
        voice_live_format=l5_voice_trace["voice_live_format"],
        voice_streaming_fallback_used=l5_voice_trace["voice_streaming_fallback_used"],
        voice_prewarm_used=l5_voice_trace["voice_prewarm_used"],
        voice_partial_playback=l5_voice_trace["voice_partial_playback"],
        voice_anchor_state=l5_voice_trace["voice_anchor_state"],
        voice_speaking_visual_active=l5_voice_trace["voice_speaking_visual_active"],
        voice_audio_reactive_source=l5_voice_trace["voice_audio_reactive_source"],
        voice_audio_reactive_available=l5_voice_trace[
            "voice_audio_reactive_available"
        ],
        voice_anchor_motion_intensity=l5_voice_trace[
            "voice_anchor_motion_intensity"
        ],
        voice_anchor_audio_level=l5_voice_trace["voice_anchor_audio_level"],
        voice_visualizer_update_hz=l5_voice_trace["voice_visualizer_update_hz"],
        voice_anchor_user_heard_claimed=l5_voice_trace[
            "voice_anchor_user_heard_claimed"
        ],
        warnings=[
            str(item)
            for item in (
                metadata.get("warnings")
                if isinstance(metadata.get("warnings"), list)
                else []
            )
        ][:10],
    )


def attach_latency_metadata(
    metadata: dict[str, Any],
    *,
    stage_timings_ms: dict[str, Any],
    request_id: str | None = None,
    session_id: str = "",
    surface_mode: str = "",
    active_module: str = "",
    provider_called: bool | None = None,
    openai_called: bool | None = None,
    llm_called: bool | None = None,
    embedding_called: bool | None = None,
    voice_involved: bool = False,
    job_count: int | None = None,
    event_count: int | None = None,
    async_continuation: bool | None = None,
    completed_at: str | None = None,
) -> LatencyTrace:
    trace = build_latency_trace(
        metadata=metadata,
        stage_timings_ms=stage_timings_ms,
        request_id=request_id,
        session_id=session_id,
        surface_mode=surface_mode,
        active_module=active_module,
        provider_called=provider_called,
        openai_called=openai_called,
        llm_called=llm_called,
        embedding_called=embedding_called,
        voice_involved=voice_involved,
        job_count=job_count,
        event_count=event_count,
        async_continuation=async_continuation,
        completed_at=completed_at,
    )
    policy = classify_route_latency_policy(
        route_family=trace.route_family,
        subsystem=trace.subsystem,
        request_kind=trace.request_kind,
        execution_plan_type=trace.execution_plan_type,
        surface_mode=trace.surface_mode,
        active_module=trace.active_module,
        result_state=trace.result_state,
        fail_fast_reason=trace.fail_fast_reason or str(metadata.get("fail_fast_reason") or ""),
    )
    budget_result = trace.budget_result()
    partial = build_partial_response_posture(
        route_family=trace.route_family,
        subsystem=trace.subsystem,
        assistant_message=str(
            metadata.get("micro_response")
            or metadata.get("full_response")
            or metadata.get("spoken_response")
            or ""
        ),
        result_state=trace.result_state,
        verification_state=trace.verification_posture,
        latency_trace_id=trace.trace_id,
        policy=policy,
        budget_exceeded=budget_result.budget_exceeded,
        async_continuation=bool(async_continuation if async_continuation is not None else trace.async_continuation),
        continue_reason=_continue_reason(policy, budget_result, trace.fail_fast_reason),
        job_id=_first_job_id(metadata),
        task_id=_first_task_id(metadata),
    )
    if trace.async_initial_response_returned:
        handle = trace.async_route_handle if isinstance(trace.async_route_handle, dict) else {}
        progress = trace.route_progress_state if isinstance(trace.route_progress_state, dict) else {}
        partial.update(
            {
                "result_state": trace.route_progress_stage or progress.get("result_state") or "queued",
                "assistant_message": str(
                    progress.get("message")
                    or metadata.get("micro_response")
                    or metadata.get("full_response")
                    or ""
                )[:500],
                "task_id": handle.get("task_id") or progress.get("task_id") or partial.get("task_id"),
                "job_id": handle.get("job_id") or progress.get("job_id") or partial.get("job_id"),
                "events_expected": True,
                "async_continuation": True,
                "async_expected": True,
                "completion_claimed": False,
                "verification_claimed": False,
                "partial_response_returned": True,
                "continue_reason": trace.async_strategy or partial.get("continue_reason") or "async_continuation",
                "execution_mode": trace.execution_mode,
                "failed": False,
            }
        )
    if trace.subsystem_continuation_created:
        partial.update(
            {
                "result_state": trace.subsystem_continuation_stage or "queued",
                "events_expected": True,
                "async_continuation": True,
                "async_expected": True,
                "completion_claimed": False,
                "verification_claimed": False,
                "partial_response_returned": True,
                "continue_reason": "subsystem_continuation",
                "failed": False,
            }
        )
    first_feedback = {
        "request_id": trace.request_id,
        "session_id": trace.session_id,
        "route_family": trace.route_family,
        "subsystem": trace.subsystem,
        "result_state": partial["result_state"],
        "budget_label": policy.budget.label,
        "latency_trace_id": trace.trace_id,
        "execution_mode": policy.execution_mode.value,
        "first_feedback_ms": trace.first_feedback_ms,
        "async_continuation": partial["async_continuation"],
        "completion_claimed": False,
        "verification_claimed": False,
        "message_preview": str(partial.get("assistant_message") or "")[:160],
        "task_id": partial.get("task_id"),
        "job_id": partial.get("job_id"),
    }
    if not trace.async_strategy:
        trace.execution_mode = policy.execution_mode.value
    trace.async_expected = bool(
        policy.async_expected
        or trace.async_expected
        or trace.async_initial_response_returned
        or trace.async_conversion_expected
    )
    trace.partial_response_returned = bool(partial.get("partial_response_returned"))
    trace.budget_exceeded_continuing = bool(partial.get("budget_exceeded_continuing"))
    trace.fail_fast_reason = trace.fail_fast_reason or policy.fail_fast_reason
    trace_payload = trace.to_dict()
    metadata["latency_policy"] = policy.to_dict()
    metadata["execution_mode"] = trace.execution_mode
    metadata["async_expected"] = bool(trace.async_expected)
    metadata["async_continuation"] = bool(trace.async_continuation)
    metadata["async_strategy"] = trace.async_strategy
    metadata["async_initial_response_returned"] = bool(trace.async_initial_response_returned)
    metadata["route_continuation_id"] = trace.route_continuation_id
    metadata["route_progress_stage"] = trace.route_progress_stage
    metadata["route_progress_status"] = trace.route_progress_status
    metadata["progress_event_count"] = int(trace.progress_event_count or 0)
    metadata["job_required"] = bool(trace.job_required)
    metadata["task_required"] = bool(trace.task_required)
    metadata["event_progress_required"] = bool(trace.event_progress_required)
    metadata["worker_lane"] = trace.worker_lane
    metadata["worker_priority"] = trace.worker_priority
    metadata["queue_depth_at_submit"] = int(trace.queue_depth_at_submit or 0)
    metadata["queue_wait_ms"] = _safe_float(trace.queue_wait_ms)
    metadata["job_start_delay_ms"] = _safe_float(trace.job_start_delay_ms)
    metadata["job_run_ms"] = _safe_float(trace.job_run_ms)
    metadata["job_total_ms"] = _safe_float(trace.job_total_ms)
    metadata["worker_index"] = trace.worker_index
    metadata["worker_capacity"] = int(trace.worker_capacity or 0)
    metadata["workers_busy_at_submit"] = int(trace.workers_busy_at_submit or 0)
    metadata["workers_idle_at_submit"] = int(trace.workers_idle_at_submit or 0)
    metadata["worker_saturation_percent"] = _safe_float(trace.worker_saturation_percent)
    metadata["interactive_jobs_waiting"] = int(trace.interactive_jobs_waiting or 0)
    metadata["background_jobs_running"] = int(trace.background_jobs_running or 0)
    metadata["background_job_count"] = int(trace.background_job_count or 0)
    metadata["interactive_job_count"] = int(trace.interactive_job_count or 0)
    metadata["starvation_detected"] = bool(trace.starvation_detected)
    if trace.async_worker_utilization_summary:
        metadata["async_worker_utilization_summary"] = safe_latency_value(
            trace.async_worker_utilization_summary
        )
    metadata["scheduler_strategy"] = trace.scheduler_strategy
    metadata["scheduler_pressure_state"] = trace.scheduler_pressure_state
    metadata["scheduler_pressure_reasons"] = list(trace.scheduler_pressure_reasons[:8])
    metadata["protected_interactive_capacity"] = int(trace.protected_interactive_capacity or 0)
    metadata["background_capacity_limit"] = int(trace.background_capacity_limit or 0)
    metadata["protected_capacity_wait_reason"] = trace.protected_capacity_wait_reason
    metadata["queue_wait_budget_ms"] = (
        None if trace.queue_wait_budget_ms is None else _safe_float(trace.queue_wait_budget_ms)
    )
    metadata["queue_wait_budget_exceeded"] = bool(trace.queue_wait_budget_exceeded)
    metadata["subsystem_cap_key"] = trace.subsystem_cap_key
    metadata["subsystem_cap_limit"] = trace.subsystem_cap_limit
    metadata["subsystem_cap_wait_ms"] = _safe_float(trace.subsystem_cap_wait_ms)
    metadata["retry_policy"] = trace.retry_policy
    metadata["retry_count"] = int(trace.retry_count or 0)
    metadata["retry_max_attempts"] = int(trace.retry_max_attempts or 0)
    metadata["retry_backoff_ms"] = _safe_float(trace.retry_backoff_ms)
    metadata["retry_last_error"] = trace.retry_last_error
    metadata["attempt_count"] = int(trace.attempt_count or 0)
    metadata["cancellation_state"] = trace.cancellation_state
    metadata["yield_state"] = trace.yield_state
    metadata["restart_recovery_state"] = trace.restart_recovery_state
    metadata["subsystem_continuation_created"] = bool(trace.subsystem_continuation_created)
    metadata["subsystem_continuation_id"] = trace.subsystem_continuation_id
    metadata["subsystem_continuation_kind"] = trace.subsystem_continuation_kind
    metadata["subsystem_continuation_stage"] = trace.subsystem_continuation_stage
    metadata["subsystem_continuation_status"] = trace.subsystem_continuation_status
    metadata["subsystem_continuation_worker_lane"] = trace.subsystem_continuation_worker_lane
    metadata["subsystem_continuation_queue_wait_ms"] = _safe_float(trace.subsystem_continuation_queue_wait_ms)
    metadata["subsystem_continuation_run_ms"] = _safe_float(trace.subsystem_continuation_run_ms)
    metadata["subsystem_continuation_total_ms"] = _safe_float(trace.subsystem_continuation_total_ms)
    metadata["subsystem_continuation_progress_event_count"] = int(
        trace.subsystem_continuation_progress_event_count or 0
    )
    metadata["subsystem_continuation_final_result_state"] = trace.subsystem_continuation_final_result_state
    metadata["subsystem_continuation_verification_state"] = trace.subsystem_continuation_verification_state
    metadata["direct_subsystem_async_converted"] = bool(trace.direct_subsystem_async_converted)
    metadata["inline_front_half_ms"] = _safe_float(trace.inline_front_half_ms)
    metadata["worker_back_half_ms"] = _safe_float(trace.worker_back_half_ms)
    metadata["returned_before_subsystem_completion"] = bool(trace.returned_before_subsystem_completion)
    metadata["async_conversion_expected"] = bool(trace.async_conversion_expected)
    metadata["async_conversion_missing_reason"] = trace.async_conversion_missing_reason
    metadata["voice_streaming_tts_enabled"] = bool(trace.voice_streaming_tts_enabled)
    metadata["voice_first_audio_ms"] = _safe_float(trace.voice_first_audio_ms)
    metadata["voice_core_to_first_audio_ms"] = _safe_float(trace.voice_core_to_first_audio_ms)
    metadata["voice_tts_first_chunk_ms"] = _safe_float(trace.voice_tts_first_chunk_ms)
    metadata["voice_playback_start_ms"] = _safe_float(trace.voice_playback_start_ms)
    metadata["voice_first_chunk_to_sink_accept_ms"] = _safe_float(
        trace.voice_first_chunk_to_sink_accept_ms
    )
    metadata["voice_first_output_start_ms"] = _safe_float(
        trace.voice_first_output_start_ms
    )
    metadata["voice_null_sink_first_accept_ms"] = _safe_float(
        trace.voice_null_sink_first_accept_ms
    )
    metadata["voice_streaming_transport_kind"] = trace.voice_streaming_transport_kind
    metadata["voice_sink_kind"] = trace.voice_sink_kind
    metadata["voice_first_chunk_before_complete"] = bool(trace.voice_first_chunk_before_complete)
    metadata["voice_stream_used_by_normal_path"] = bool(trace.voice_stream_used_by_normal_path)
    metadata["voice_streaming_miss_reason"] = trace.voice_streaming_miss_reason
    metadata["voice_live_openai_voice_smoke_run"] = bool(
        trace.voice_live_openai_voice_smoke_run
    )
    metadata["voice_live_openai_first_chunk_ms"] = _safe_float(
        trace.voice_live_openai_first_chunk_ms
    )
    metadata["voice_wake_loop_streaming_output_used"] = bool(
        trace.voice_wake_loop_streaming_output_used
    )
    metadata["voice_wake_loop_streaming_miss_reason"] = (
        trace.voice_wake_loop_streaming_miss_reason
    )
    metadata["voice_realtime_deferred_to_l6"] = bool(
        trace.voice_realtime_deferred_to_l6
    )
    metadata["voice_realtime_session_creation_attempted"] = bool(
        trace.voice_realtime_session_creation_attempted
    )
    metadata["voice_user_heard_claimed"] = bool(trace.voice_user_heard_claimed)
    metadata["voice_live_format"] = trace.voice_live_format
    metadata["voice_streaming_fallback_used"] = bool(trace.voice_streaming_fallback_used)
    metadata["voice_prewarm_used"] = bool(trace.voice_prewarm_used)
    metadata["voice_partial_playback"] = bool(trace.voice_partial_playback)
    metadata["voice_anchor_state"] = trace.voice_anchor_state
    metadata["voice_speaking_visual_active"] = bool(trace.voice_speaking_visual_active)
    metadata["voice_audio_reactive_source"] = trace.voice_audio_reactive_source
    metadata["voice_audio_reactive_available"] = bool(
        trace.voice_audio_reactive_available
    )
    metadata["voice_anchor_motion_intensity"] = _safe_float(
        trace.voice_anchor_motion_intensity
    )
    metadata["voice_anchor_audio_level"] = _safe_float(trace.voice_anchor_audio_level)
    metadata["voice_visualizer_update_hz"] = int(trace.voice_visualizer_update_hz or 0)
    metadata["voice_anchor_user_heard_claimed"] = bool(
        trace.voice_anchor_user_heard_claimed
    )
    if trace.async_route_handle:
        metadata["async_route_handle"] = safe_latency_value(trace.async_route_handle)
    if trace.route_progress_state:
        metadata["route_progress_state"] = safe_latency_value(trace.route_progress_state)
    metadata["first_feedback_ms"] = trace.first_feedback_ms
    metadata["first_feedback"] = safe_latency_value(first_feedback)
    metadata["partial_response"] = partial
    metadata["partial_response_returned"] = bool(partial.get("partial_response_returned"))
    metadata["budget_exceeded_continuing"] = bool(partial.get("budget_exceeded_continuing"))
    if trace.fail_fast_reason:
        metadata["fail_fast_reason"] = trace.fail_fast_reason
    metadata["latency_trace"] = trace_payload
    metadata["latency_summary"] = trace.to_summary_dict()
    metadata["budget_result"] = trace_payload["budget_result"]
    return trace


def stages_from_stage_timings(
    stage_timings_ms: dict[str, Any],
    *,
    route_family: str | None = None,
    subsystem: str | None = None,
) -> list[LatencyStage]:
    stages: list[LatencyStage] = []
    for name, value in stage_timings_ms.items():
        key = str(name)
        if key in LATENCY_COUNTER_KEYS:
            continue
        duration_ms = _safe_float(value)
        budget_ms = STAGE_BUDGETS_MS.get(key)
        stages.append(
            LatencyStage(
                name=key,
                duration_ms=duration_ms,
                subsystem=subsystem,
                route_family=route_family,
                budget_ms=budget_ms,
                exceeded_budget=bool(budget_ms is not None and duration_ms > budget_ms),
            )
        )
    return stages


def _normalized_result_state(result_state: str | None, policy: RouteLatencyPolicy) -> str:
    state = str(result_state or "").strip()
    if state:
        if state in {"action_result", "assistant_message"} and policy.execution_mode == RouteExecutionMode.PLAN_FIRST:
            return "plan_ready"
        return state
    if policy.fail_fast_reason or policy.execution_mode == RouteExecutionMode.UNSUPPORTED:
        return "blocked"
    if policy.execution_mode == RouteExecutionMode.CLARIFICATION:
        return "blocked"
    if policy.execution_mode == RouteExecutionMode.ASYNC_FIRST:
        return "queued"
    if policy.execution_mode == RouteExecutionMode.PLAN_FIRST:
        return "planning"
    if policy.execution_mode == RouteExecutionMode.PROVIDER_WAIT:
        return "planning"
    return "completed"


def _completion_claimed(result_state: str) -> bool:
    return result_state in {
        "completed",
        "verified",
        "calculation_result",
        "numeric_metric",
        "status_summary",
        "identity_summary",
        "diagnostic_summary",
        "history_summary",
        "forecast_summary",
    }


def _continue_reason(
    policy: RouteLatencyPolicy,
    budget_result: LatencyBudgetResult,
    fail_fast_reason: str,
) -> str:
    if fail_fast_reason:
        return fail_fast_reason
    if budget_result.budget_exceeded and policy.async_expected:
        return "budget_exceeded_continuing"
    if policy.async_expected:
        return "async_expected"
    if policy.execution_mode == RouteExecutionMode.PLAN_FIRST:
        return "plan_first"
    if policy.execution_mode == RouteExecutionMode.PROVIDER_WAIT:
        return "provider_wait"
    return ""


def _first_feedback_ms(timings: dict[str, float], policy: RouteLatencyPolicy) -> float | None:
    if not timings:
        return None
    if policy.execution_mode == RouteExecutionMode.ASYNC_FIRST:
        keys = ("session_create_or_load_ms", "memory_context_ms", "planner_route_ms")
    elif policy.execution_mode in {RouteExecutionMode.PLAN_FIRST, RouteExecutionMode.PROVIDER_WAIT, RouteExecutionMode.CLARIFICATION, RouteExecutionMode.UNSUPPORTED}:
        keys = ("session_create_or_load_ms", "memory_context_ms", "planner_route_ms")
    else:
        keys = ("planner_route_ms",)
    value = sum(_safe_float(timings.get(key)) for key in keys)
    return round(value, 3)


def _first_job_id(metadata: dict[str, Any]) -> str | None:
    jobs = metadata.get("jobs") if isinstance(metadata.get("jobs"), list) else []
    for job in jobs:
        if isinstance(job, dict) and job.get("job_id"):
            return str(job.get("job_id"))
    return None


def _first_task_id(metadata: dict[str, Any]) -> str | None:
    active_task = metadata.get("active_task") if isinstance(metadata.get("active_task"), dict) else {}
    for key in ("task_id", "id"):
        if active_task.get(key):
            return str(active_task.get(key))
    return None


def safe_latency_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "<truncated>"
    if isinstance(value, bytes | bytearray | memoryview):
        return "<bytes:redacted>"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return safe_latency_value(value.to_dict(), depth=depth + 1)
    if hasattr(value, "__dataclass_fields__"):
        return safe_latency_value(asdict(value), depth=depth + 1)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 240:
                sanitized["<truncated_keys>"] = len(value) - 240
                break
            key_text = str(key)
            if _unsafe_key(key_text):
                sanitized[key_text] = "<redacted>"
            else:
                sanitized[key_text] = safe_latency_value(item, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        safe_items = [safe_latency_value(item, depth=depth + 1) for item in items[:20]]
        if len(items) > 20:
            safe_items.append({"truncated_count": len(items) - 20})
        return safe_items
    if isinstance(value, str):
        if _looks_like_bearer(value):
            return "<redacted>"
        if len(value) > 500:
            return value[:500] + "...<truncated>"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _route_attribution(metadata: dict[str, Any]) -> dict[str, Any]:
    route_state = metadata.get("route_state") if isinstance(metadata.get("route_state"), dict) else {}
    planner_debug = metadata.get("planner_debug") if isinstance(metadata.get("planner_debug"), dict) else {}
    planner_obedience = (
        metadata.get("planner_obedience")
        if isinstance(metadata.get("planner_obedience"), dict)
        else {}
    )
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    planner_v2 = planner_debug.get("planner_v2") if isinstance(planner_debug.get("planner_v2"), dict) else {}
    route_decision = (
        planner_v2.get("route_decision")
        if isinstance(planner_v2.get("route_decision"), dict)
        else {}
    )
    structured_query = (
        planner_debug.get("structured_query")
        if isinstance(planner_debug.get("structured_query"), dict)
        else {}
    )
    execution_plan = (
        planner_debug.get("execution_plan")
        if isinstance(planner_debug.get("execution_plan"), dict)
        else {}
    )
    route_family = (
        metadata.get("route_family")
        or winner.get("route_family")
        or planner_debug.get("route_family")
        or route_decision.get("selected_route_family")
        or route_decision.get("selected_route_spec")
        or planner_obedience.get("route_family")
    )
    subsystem = (
        metadata.get("subsystem")
        or winner.get("subsystem")
        or planner_debug.get("subsystem")
        or route_decision.get("subsystem")
        or planner_obedience.get("actual_subsystem")
    )
    query_shape = (
        planner_obedience.get("query_shape")
        or structured_query.get("query_shape")
        or route_decision.get("query_shape")
    )
    execution_plan_type = (
        planner_obedience.get("execution_plan_type")
        or execution_plan.get("plan_type")
        or route_decision.get("execution_plan_type")
    )
    result_state = (
        metadata.get("result_state")
        or planner_obedience.get("actual_result_mode")
        or metadata.get("verification_state")
    )
    provider_fallback_used = bool(
        winner.get("provider_fallback_reason")
        or route_family == "generic_provider"
        or _nested_truthy(planner_debug, "browser_search_fallback", "used")
    )
    jobs = metadata.get("jobs") if isinstance(metadata.get("jobs"), list) else []
    async_continuation = any(
        str(job.get("status") or "").strip().lower()
        not in {"", "completed", "failed", "cancelled", "canceled"}
        for job in jobs
        if isinstance(job, dict)
    )
    return {
        "route_family": str(route_family) if route_family else None,
        "subsystem": str(subsystem) if subsystem else None,
        "request_kind": str(query_shape or execution_plan_type) if (query_shape or execution_plan_type) else None,
        "query_shape": str(query_shape) if query_shape else None,
        "execution_plan_type": str(execution_plan_type) if execution_plan_type else None,
        "result_state": str(result_state) if result_state else None,
        "trust_posture": str(
            (metadata.get("judgment") or {}).get("risk_tier")
            if isinstance(metadata.get("judgment"), dict)
            else ""
        )
        or None,
        "verification_posture": str(metadata.get("verification_state") or "")
        or None,
        "provider_fallback_used": provider_fallback_used,
        "async_continuation": async_continuation,
    }


def _l2_trace_metadata(
    metadata: dict[str, Any],
    timings: dict[str, float],
    existing_trace: dict[str, Any],
) -> dict[str, Any]:
    planner_debug = metadata.get("planner_debug") if isinstance(metadata.get("planner_debug"), dict) else {}
    triage = metadata.get("route_triage_result") if isinstance(metadata.get("route_triage_result"), dict) else {}
    if not triage and isinstance(planner_debug.get("route_triage"), dict):
        triage = dict(planner_debug.get("route_triage") or {})
    if not triage and isinstance(existing_trace.get("route_triage_result"), dict):
        triage = dict(existing_trace.get("route_triage_result") or {})

    likely = _string_list(
        metadata.get("candidate_route_families")
        or metadata.get("likely_route_families")
        or triage.get("likely_route_families")
        or existing_trace.get("likely_route_families")
    )
    skipped = _string_list(
        metadata.get("skipped_route_families")
        or triage.get("skipped_route_families")
        or triage.get("excluded_route_families")
        or existing_trace.get("skipped_route_families")
    )
    seams_evaluated = _string_list(
        metadata.get("route_family_seams_evaluated")
        or planner_debug.get("route_family_seams_evaluated")
        or existing_trace.get("route_family_seams_evaluated")
    )
    seams_skipped = _string_list(
        metadata.get("route_family_seams_skipped")
        or planner_debug.get("route_family_seams_skipped")
        or existing_trace.get("route_family_seams_skipped")
    )
    provider_suppressed = str(
        metadata.get("provider_fallback_suppressed_reason")
        or planner_debug.get("provider_fallback_suppressed_reason")
        or existing_trace.get("provider_fallback_suppressed_reason")
        or ""
    )
    heavy_loaded = _truthy_value(
        metadata.get("heavy_context_loaded"),
        fallback=(
            planner_debug.get("heavy_context_loaded")
            if "heavy_context_loaded" in planner_debug
            else timings.get("heavy_context_loaded") or existing_trace.get("heavy_context_loaded")
        ),
    )
    fast_path = _truthy_value(
        metadata.get("fast_path_used"),
        fallback=timings.get("fast_path_used") or existing_trace.get("fast_path_used") or triage.get("safe_to_short_circuit"),
    )
    return {
        "route_triage_ms": _safe_float(
            timings.get("route_triage_ms")
            or triage.get("elapsed_ms")
            or existing_trace.get("route_triage_ms")
        ),
        "route_triage_result": safe_latency_value(triage) if triage else {},
        "triage_confidence": _safe_float(triage.get("confidence") or existing_trace.get("triage_confidence")),
        "triage_reason_codes": _string_list(triage.get("reason_codes") or existing_trace.get("triage_reason_codes")),
        "likely_route_families": likely,
        "skipped_route_families": skipped,
        "heavy_context_loaded": heavy_loaded,
        "heavy_context_reason": str(
            metadata.get("heavy_context_reason")
            or planner_debug.get("heavy_context_reason")
            or existing_trace.get("heavy_context_reason")
            or ""
        ),
        "fast_path_used": fast_path,
        "short_circuit_route_family": (
            str(triage.get("short_circuit_route_family") or existing_trace.get("short_circuit_route_family"))
            if (triage.get("short_circuit_route_family") or existing_trace.get("short_circuit_route_family"))
            else None
        ),
        "provider_fallback_eligible": _truthy_value(
            metadata.get("provider_fallback_eligible"),
            fallback=triage.get("provider_fallback_eligible") or existing_trace.get("provider_fallback_eligible"),
        ),
        "provider_fallback_suppressed_reason": provider_suppressed,
        "planner_candidates_pruned_count": int(
            _safe_float(
                metadata.get("planner_candidates_pruned_count")
                or planner_debug.get("planner_candidates_pruned_count")
                or timings.get("planner_candidates_pruned_count")
                or existing_trace.get("planner_candidates_pruned_count")
            )
        ),
        "route_family_seams_evaluated": seams_evaluated,
        "route_family_seams_skipped": seams_skipped,
    }


def _l9_provider_trace_metadata(
    metadata: dict[str, Any],
    existing_trace: dict[str, Any],
) -> dict[str, Any]:
    provider_eligibility = _dict_payload(
        metadata.get("provider_eligibility")
        or metadata.get("provider_fallback_eligibility")
        or existing_trace.get("provider_eligibility")
    )
    provider_latency_summary = _dict_payload(
        metadata.get("provider_latency_summary")
        or metadata.get("provider_fallback_summary")
        or existing_trace.get("provider_latency_summary")
    )
    provider_audit_timing = _dict_payload(
        metadata.get("provider_audit_timing")
        or metadata.get("provider_fallback_audit_timing")
        or existing_trace.get("provider_audit_timing")
    )
    return {
        "provider_eligibility": safe_latency_value(provider_eligibility),
        "provider_latency_summary": safe_latency_value(provider_latency_summary),
        "provider_audit_timing": safe_latency_value(provider_audit_timing),
    }


def _l3_trace_metadata(
    metadata: dict[str, Any],
    timings: dict[str, float],
    existing_trace: dict[str, Any],
) -> dict[str, Any]:
    planner_debug = metadata.get("planner_debug") if isinstance(metadata.get("planner_debug"), dict) else {}
    snapshot_debug = (
        planner_debug.get("context_snapshots")
        if isinstance(planner_debug.get("context_snapshots"), dict)
        else {}
    )

    def selected(key: str) -> Any:
        if key in metadata:
            return metadata.get(key)
        if key in snapshot_debug:
            return snapshot_debug.get(key)
        return existing_trace.get(key)

    return {
        "snapshots_checked": _string_list(selected("snapshots_checked")),
        "snapshots_used": _string_list(selected("snapshots_used")),
        "snapshots_refreshed": _string_list(selected("snapshots_refreshed")),
        "snapshots_invalidated": _string_list(selected("snapshots_invalidated")),
        "snapshot_freshness": _string_dict(selected("snapshot_freshness")),
        "snapshot_age_ms": _float_dict(selected("snapshot_age_ms")),
        "snapshot_hot_path_hit": _truthy_value(
            selected("snapshot_hot_path_hit"),
            fallback=timings.get("snapshot_hot_path_hit"),
        ),
        "snapshot_miss_reason": _string_dict(selected("snapshot_miss_reason")),
        "heavy_context_avoided_by_snapshot": _truthy_value(
            selected("heavy_context_avoided_by_snapshot"),
            fallback=timings.get("heavy_context_avoided_by_snapshot"),
        ),
        "stale_snapshot_used_cautiously": _truthy_value(selected("stale_snapshot_used_cautiously")),
        "invalidation_count": int(
            _safe_float(
                selected("invalidation_count")
                or timings.get("invalidation_count")
            )
        ),
        "freshness_warnings": _string_list(selected("freshness_warnings"), limit=12),
    }


def _l4_trace_metadata(
    metadata: dict[str, Any],
    timings: dict[str, float],
    existing_trace: dict[str, Any],
) -> dict[str, Any]:
    planner_debug = metadata.get("planner_debug") if isinstance(metadata.get("planner_debug"), dict) else {}
    async_debug = (
        metadata.get("async_route")
        if isinstance(metadata.get("async_route"), dict)
        else planner_debug.get("async_route")
        if isinstance(planner_debug.get("async_route"), dict)
        else {}
    )

    def selected(key: str) -> Any:
        if key in metadata:
            return metadata.get(key)
        if key in async_debug:
            return async_debug.get(key)
        return existing_trace.get(key)

    handle = selected("async_route_handle")
    if not isinstance(handle, dict):
        handle = async_debug.get("handle") if isinstance(async_debug.get("handle"), dict) else {}
    progress = selected("route_progress_state")
    if not isinstance(progress, dict):
        progress = async_debug.get("progress_state") if isinstance(async_debug.get("progress_state"), dict) else {}
    strategy = str(
        selected("async_strategy")
        or async_debug.get("async_strategy")
        or existing_trace.get("async_strategy")
        or ""
    )
    return {
        "async_strategy": strategy,
        "async_initial_response_returned": _truthy_value(
            selected("async_initial_response_returned"),
            fallback=timings.get("async_initial_response_returned"),
        ),
        "route_continuation_id": str(
            selected("route_continuation_id")
            or progress.get("continuation_id")
            or handle.get("continuation_id")
            or ""
        ),
        "async_route_handle": safe_latency_value(handle if isinstance(handle, dict) else {}),
        "route_progress_state": safe_latency_value(progress if isinstance(progress, dict) else {}),
        "route_progress_stage": str(
            selected("route_progress_stage")
            or progress.get("stage")
            or handle.get("progress_stage")
            or ""
        ),
        "route_progress_status": str(
            selected("route_progress_status")
            or progress.get("status")
            or ""
        ),
        "progress_event_count": int(
            _safe_float(
                selected("progress_event_count")
                or timings.get("progress_event_count")
            )
        ),
        "job_required": _truthy_value(selected("job_required"), fallback=timings.get("job_required")),
        "task_required": _truthy_value(selected("task_required"), fallback=timings.get("task_required")),
        "event_progress_required": _truthy_value(
            selected("event_progress_required"),
            fallback=timings.get("event_progress_required"),
        ),
        "execution_mode": str(selected("execution_mode") or progress.get("execution_mode") or ""),
    }


def _l41_trace_metadata(
    metadata: dict[str, Any],
    timings: dict[str, float],
    existing_trace: dict[str, Any],
) -> dict[str, Any]:
    first_job = _first_job_metadata(metadata)
    worker_summary = (
        metadata.get("async_worker_utilization_summary")
        if isinstance(metadata.get("async_worker_utilization_summary"), dict)
        else existing_trace.get("async_worker_utilization_summary")
        if isinstance(existing_trace.get("async_worker_utilization_summary"), dict)
        else {}
    )

    def selected(key: str) -> Any:
        if key in metadata:
            return metadata.get(key)
        if key in first_job:
            return first_job.get(key)
        if key in worker_summary:
            return worker_summary.get(key)
        return existing_trace.get(key)

    worker_index_value = selected("worker_index")
    worker_index = int(_safe_float(worker_index_value)) if worker_index_value not in {None, ""} else None
    return {
        "worker_lane": str(selected("worker_lane") or selected("priority_lane") or ""),
        "worker_priority": str(selected("worker_priority") or selected("priority_level") or ""),
        "queue_depth_at_submit": int(_safe_float(selected("queue_depth_at_submit"))),
        "queue_wait_ms": _safe_float(selected("queue_wait_ms") or timings.get("queue_wait_ms")),
        "job_start_delay_ms": _safe_float(
            selected("job_start_delay_ms") or timings.get("job_start_delay_ms")
        ),
        "job_run_ms": _safe_float(selected("job_run_ms") or timings.get("job_run_ms")),
        "job_total_ms": _safe_float(selected("job_total_ms") or timings.get("job_total_ms")),
        "worker_index": worker_index,
        "worker_capacity": int(_safe_float(selected("worker_capacity") or selected("worker_capacity_at_submit"))),
        "workers_busy_at_submit": int(_safe_float(selected("workers_busy_at_submit"))),
        "workers_idle_at_submit": int(_safe_float(selected("workers_idle_at_submit"))),
        "worker_saturation_percent": _safe_float(selected("worker_saturation_percent")),
        "interactive_jobs_waiting": int(_safe_float(selected("interactive_jobs_waiting"))),
        "background_jobs_running": int(_safe_float(selected("background_jobs_running"))),
        "background_job_count": int(_safe_float(selected("background_job_count"))),
        "interactive_job_count": int(_safe_float(selected("interactive_job_count"))),
        "starvation_detected": _truthy_value(selected("starvation_detected")),
        "async_worker_utilization_summary": safe_latency_value(worker_summary),
        "scheduler_strategy": str(selected("scheduler_strategy") or ""),
        "scheduler_pressure_state": str(selected("scheduler_pressure_state") or ""),
        "scheduler_pressure_reasons": list(selected("scheduler_pressure_reasons") or []),
        "protected_interactive_capacity": int(_safe_float(selected("protected_interactive_capacity"))),
        "background_capacity_limit": int(_safe_float(selected("background_capacity_limit"))),
        "protected_capacity_wait_reason": str(selected("protected_capacity_wait_reason") or ""),
        "queue_wait_budget_ms": (
            _safe_float(selected("queue_wait_budget_ms"))
            if selected("queue_wait_budget_ms") not in {None, ""}
            else None
        ),
        "queue_wait_budget_exceeded": _truthy_value(selected("queue_wait_budget_exceeded")),
        "subsystem_cap_key": str(selected("subsystem_cap_key") or ""),
        "subsystem_cap_limit": (
            int(_safe_float(selected("subsystem_cap_limit")))
            if selected("subsystem_cap_limit") not in {None, ""}
            else None
        ),
        "subsystem_cap_wait_ms": _safe_float(selected("subsystem_cap_wait_ms")),
        "retry_policy": str(selected("retry_policy") or ""),
        "retry_count": int(_safe_float(selected("retry_count"))),
        "retry_max_attempts": int(_safe_float(selected("retry_max_attempts"))),
        "retry_backoff_ms": _safe_float(selected("retry_backoff_ms")),
        "retry_last_error": str(selected("retry_last_error") or ""),
        "attempt_count": int(_safe_float(selected("attempt_count"))),
        "cancellation_state": str(selected("cancellation_state") or ""),
        "yield_state": str(selected("yield_state") or ""),
        "restart_recovery_state": str(selected("restart_recovery_state") or ""),
    }


def _l42_trace_metadata(
    metadata: dict[str, Any],
    timings: dict[str, float],
    existing_trace: dict[str, Any],
) -> dict[str, Any]:
    planner_debug = metadata.get("planner_debug") if isinstance(metadata.get("planner_debug"), dict) else {}
    continuation_debug = (
        metadata.get("subsystem_continuation")
        if isinstance(metadata.get("subsystem_continuation"), dict)
        else planner_debug.get("subsystem_continuation")
        if isinstance(planner_debug.get("subsystem_continuation"), dict)
        else {}
    )

    def selected(key: str) -> Any:
        if key in metadata:
            return metadata.get(key)
        if key in continuation_debug:
            return continuation_debug.get(key)
        return existing_trace.get(key)

    queue_wait = _safe_float(
        selected("subsystem_continuation_queue_wait_ms")
        or selected("continuation_queue_wait_ms")
        or timings.get("subsystem_continuation_queue_wait_ms")
        or timings.get("continuation_queue_wait_ms")
    )
    run_ms = _safe_float(
        selected("subsystem_continuation_run_ms")
        or selected("continuation_run_ms")
        or timings.get("subsystem_continuation_run_ms")
        or timings.get("continuation_run_ms")
    )
    total_ms = _safe_float(
        selected("subsystem_continuation_total_ms")
        or selected("continuation_total_ms")
        or timings.get("subsystem_continuation_total_ms")
        or timings.get("continuation_total_ms")
    )
    worker_back_half_ms = _safe_float(selected("worker_back_half_ms") or run_ms or total_ms)
    return {
        "subsystem_continuation_created": _truthy_value(
            selected("subsystem_continuation_created"),
            fallback=timings.get("subsystem_continuation_created"),
        ),
        "subsystem_continuation_id": str(
            selected("subsystem_continuation_id")
            or selected("continuation_id")
            or ""
        ),
        "subsystem_continuation_kind": str(
            selected("subsystem_continuation_kind")
            or selected("operation_kind")
            or ""
        ),
        "subsystem_continuation_stage": str(
            selected("subsystem_continuation_stage")
            or selected("stage")
            or ""
        ),
        "subsystem_continuation_status": str(
            selected("subsystem_continuation_status")
            or selected("status")
            or ""
        ),
        "subsystem_continuation_worker_lane": str(
            selected("subsystem_continuation_worker_lane")
            or selected("worker_lane")
            or ""
        ),
        "subsystem_continuation_queue_wait_ms": queue_wait,
        "subsystem_continuation_run_ms": run_ms,
        "subsystem_continuation_total_ms": total_ms,
        "subsystem_continuation_progress_event_count": int(
            _safe_float(
                selected("subsystem_continuation_progress_event_count")
                or selected("continuation_progress_event_count")
                or timings.get("subsystem_continuation_progress_event_count")
            )
        ),
        "subsystem_continuation_final_result_state": str(
            selected("subsystem_continuation_final_result_state")
            or selected("continuation_final_result_state")
            or selected("result_state")
            or ""
        ),
        "subsystem_continuation_verification_state": str(
            selected("subsystem_continuation_verification_state")
            or selected("continuation_verification_state")
            or selected("verification_state")
            or ""
        ),
        "subsystem_continuation_handler": str(
            selected("subsystem_continuation_handler")
            or selected("handler")
            or selected("operation_kind")
            or ""
        ),
        "subsystem_continuation_handler_implemented": _truthy_value(
            selected("subsystem_continuation_handler_implemented"),
            fallback=selected("handler_implemented"),
        ),
        "subsystem_continuation_handler_missing_reason": str(
            selected("subsystem_continuation_handler_missing_reason")
            or selected("handler_missing_reason")
            or ""
        ),
        "continuation_progress_stages": _string_list(selected("continuation_progress_stages"), limit=16),
        "continuation_verification_required": _truthy_value(selected("continuation_verification_required")),
        "continuation_verification_attempted": _truthy_value(selected("continuation_verification_attempted")),
        "continuation_verification_evidence_count": int(
            _safe_float(selected("continuation_verification_evidence_count"))
        ),
        "continuation_result_limitations": _string_list(selected("continuation_result_limitations"), limit=12),
        "continuation_truth_clamps_applied": _string_list(selected("continuation_truth_clamps_applied"), limit=12),
        "direct_subsystem_async_converted": _truthy_value(
            selected("direct_subsystem_async_converted"),
            fallback=timings.get("direct_subsystem_async_converted"),
        ),
        "inline_front_half_ms": _safe_float(
            selected("inline_front_half_ms")
            or timings.get("inline_front_half_ms")
        ),
        "worker_back_half_ms": worker_back_half_ms,
        "returned_before_subsystem_completion": _truthy_value(
            selected("returned_before_subsystem_completion"),
            fallback=timings.get("returned_before_subsystem_completion"),
        ),
        "async_conversion_expected": _truthy_value(
            selected("async_conversion_expected"),
            fallback=timings.get("async_conversion_expected"),
        ),
        "async_conversion_missing_reason": str(selected("async_conversion_missing_reason") or ""),
    }


def _l5_voice_trace_metadata(
    metadata: dict[str, Any],
    timings: dict[str, float],
    existing_trace: dict[str, Any],
) -> dict[str, Any]:
    voice_debug = (
        metadata.get("voice_latency")
        if isinstance(metadata.get("voice_latency"), dict)
        else metadata.get("voice_first_audio")
        if isinstance(metadata.get("voice_first_audio"), dict)
        else {}
    )
    voice_anchor = (
        metadata.get("voice_anchor")
        if isinstance(metadata.get("voice_anchor"), dict)
        else voice_debug.get("voice_anchor")
        if isinstance(voice_debug.get("voice_anchor"), dict)
        else existing_trace.get("voice_anchor")
        if isinstance(existing_trace.get("voice_anchor"), dict)
        else {}
    )

    def selected(key: str) -> Any:
        if key in metadata:
            return metadata.get(key)
        if key in voice_debug:
            return voice_debug.get(key)
        if key in voice_anchor:
            return voice_anchor.get(key)
        if key in timings:
            return timings.get(key)
        return existing_trace.get(key)

    return {
        "voice_streaming_tts_enabled": _truthy_value(
            selected("voice_streaming_tts_enabled")
            or selected("streaming_enabled")
        ),
        "voice_first_audio_ms": _safe_float(
            selected("voice_first_audio_ms")
            or selected("request_to_first_audio_ms")
        ),
        "voice_core_to_first_audio_ms": _safe_float(
            selected("voice_core_to_first_audio_ms")
            or selected("core_result_to_first_audio_ms")
        ),
        "voice_tts_first_chunk_ms": _safe_float(
            selected("voice_tts_first_chunk_ms")
            or selected("tts_start_to_first_chunk_ms")
            or selected("first_tts_chunk_received_ms")
        ),
        "voice_playback_start_ms": _safe_float(
            selected("voice_playback_start_ms")
            or selected("first_chunk_to_playback_start_ms")
        ),
        "voice_first_chunk_to_sink_accept_ms": _safe_float(
            selected("voice_first_chunk_to_sink_accept_ms")
            or selected("first_chunk_to_sink_accept_ms")
            or selected("first_chunk_to_playback_start_ms")
        ),
        "voice_first_output_start_ms": _safe_float(
            selected("voice_first_output_start_ms")
            or selected("first_output_start_ms")
            or selected("request_to_first_audio_ms")
        ),
        "voice_null_sink_first_accept_ms": _safe_float(
            selected("voice_null_sink_first_accept_ms")
            or selected("null_sink_first_accept_ms")
        ),
        "voice_streaming_transport_kind": str(
            selected("voice_streaming_transport_kind")
            or selected("streaming_transport_kind")
            or ""
        ),
        "voice_sink_kind": str(selected("voice_sink_kind") or selected("sink_kind") or ""),
        "voice_first_chunk_before_complete": _truthy_value(
            selected("voice_first_chunk_before_complete")
            or selected("first_chunk_before_complete")
        ),
        "voice_stream_used_by_normal_path": _truthy_value(
            selected("voice_stream_used_by_normal_path")
            or selected("stream_used_by_normal_path")
        ),
        "voice_streaming_miss_reason": str(
            selected("voice_streaming_miss_reason")
            or selected("streaming_miss_reason")
            or ""
        ),
        "voice_live_openai_voice_smoke_run": _truthy_value(
            selected("voice_live_openai_voice_smoke_run")
            or selected("live_openai_voice_smoke_run")
        ),
        "voice_live_openai_first_chunk_ms": _safe_float(
            selected("voice_live_openai_first_chunk_ms")
            or selected("live_openai_first_chunk_ms")
        ),
        "voice_wake_loop_streaming_output_used": _truthy_value(
            selected("voice_wake_loop_streaming_output_used")
            or selected("wake_loop_streaming_output_used")
        ),
        "voice_wake_loop_streaming_miss_reason": str(
            selected("voice_wake_loop_streaming_miss_reason")
            or selected("wake_loop_streaming_miss_reason")
            or ""
        ),
        "voice_realtime_deferred_to_l6": _truthy_value(
            selected("voice_realtime_deferred_to_l6")
            or selected("realtime_deferred_to_l6")
        ),
        "voice_realtime_session_creation_attempted": _truthy_value(
            selected("voice_realtime_session_creation_attempted")
            or selected("realtime_session_creation_attempted")
        ),
        "voice_raw_audio_logged": _truthy_value(
            selected("voice_raw_audio_logged") or selected("raw_audio_logged")
        ),
        "voice_user_heard_claimed": _truthy_value(
            selected("voice_user_heard_claimed") or selected("user_heard_claimed")
        ),
        "voice_live_format": str(
            selected("voice_live_format") or selected("live_format") or ""
        ),
        "voice_streaming_fallback_used": _truthy_value(
            selected("voice_streaming_fallback_used")
            or selected("fallback_used")
        ),
        "voice_prewarm_used": _truthy_value(
            selected("voice_prewarm_used") or selected("prewarm_used")
        ),
        "voice_partial_playback": _truthy_value(
            selected("voice_partial_playback") or selected("partial_playback")
        ),
        "voice_anchor_state": str(
            selected("voice_anchor_state") or voice_anchor.get("state") or ""
        ),
        "voice_speaking_visual_active": _truthy_value(
            selected("voice_speaking_visual_active")
            or selected("speaking_visual_active")
        ),
        "voice_audio_reactive_source": str(
            selected("voice_audio_reactive_source")
            or selected("audio_reactive_source")
            or ""
        ),
        "voice_audio_reactive_available": _truthy_value(
            selected("voice_audio_reactive_available")
            or selected("audio_reactive_available")
        ),
        "voice_anchor_motion_intensity": _safe_float(
            selected("voice_anchor_motion_intensity")
            or selected("motion_intensity")
        ),
        "voice_anchor_audio_level": _safe_float(
            selected("voice_anchor_audio_level")
            or selected("smoothed_output_level")
            or selected("output_level_rms")
        ),
        "voice_visualizer_update_hz": int(
            _safe_float(
                selected("voice_visualizer_update_hz")
                or selected("visualizer_update_hz")
                or selected("update_hz")
            )
            or 0
        ),
        "voice_anchor_user_heard_claimed": _truthy_value(
            selected("voice_anchor_user_heard_claimed")
            or selected("user_heard_claimed")
        ),
    }


def _first_job_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    jobs = metadata.get("jobs")
    if isinstance(jobs, list):
        for job in jobs:
            if isinstance(job, dict):
                return job
    job = metadata.get("job")
    if isinstance(job, dict):
        return job
    return {}


def _string_list(value: Any, *, limit: int = 24) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in list(value)[:limit] if str(item or "").strip()]


def _string_dict(value: Any, *, limit: int = 32) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in list(value.items())[:limit]:
        text = str(item or "").strip()
        if text:
            result[str(key)] = text[:160]
    return result


def _float_dict(value: Any, *, limit: int = 32) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, item in list(value.items())[:limit]:
        result[str(key)] = _safe_float(item)
    return result


def _truthy_value(value: Any, *, fallback: Any = None) -> bool:
    selected = fallback if value is None else value
    if isinstance(selected, str):
        return selected.strip().lower() in {"1", "true", "yes", "on"}
    return bool(selected)


def _provider_flag(metadata: dict[str, Any], key: str) -> bool:
    if bool(metadata.get(key)):
        return True
    planner_debug = metadata.get("planner_debug") if isinstance(metadata.get("planner_debug"), dict) else {}
    if bool(planner_debug.get(key)):
        return True
    return False


def _metadata_count(metadata: dict[str, Any], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        summary = value.get("total_count")
        if summary is not None:
            return int(_safe_float(summary))
    summary = metadata.get(f"{key}Summary")
    if isinstance(summary, dict):
        return int(_safe_float(summary.get("total_count")))
    return 0


def _metadata_async_continuation(metadata: dict[str, Any]) -> bool:
    for key in ("jobs", "actions"):
        items = metadata.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").strip().lower()
            if status and status not in {"completed", "failed", "cancelled", "canceled"}:
                return True
    return False


def _trace_total_ms(timings: dict[str, float]) -> float:
    for key in ("total_latency_ms", "endpoint_dispatch_ms", "http_boundary_ms"):
        if _safe_float(timings.get(key)) > 0:
            return _safe_float(timings.get(key))
    return round(
        sum(
            _safe_float(value)
            for key, value in timings.items()
            if key not in LATENCY_COUNTER_KEYS
        ),
        3,
    )


def _rounded_float_dict(values: dict[str, Any]) -> dict[str, float]:
    rounded: dict[str, float] = {}
    for key, value in values.items():
        try:
            rounded[str(key)] = round(float(value or 0.0), 3)
        except (TypeError, ValueError):
            continue
    return rounded


def _json_ready(value: Any) -> Any:
    return safe_latency_value(value)


def _dict_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        payload = value.to_dict()
        return dict(payload) if isinstance(payload, dict) else {}
    if hasattr(value, "__dataclass_fields__"):
        payload = asdict(value)
        return dict(payload) if isinstance(payload, dict) else {}
    return {}


def _safe_float(value: Any) -> float:
    try:
        return round(float(value or 0.0), 3)
    except (TypeError, ValueError):
        return 0.0


def _optional_safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return round(float(text), 3)
    except (TypeError, ValueError):
        return None


def _unsafe_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _looks_like_bearer(value: str) -> bool:
    lowered = value.lower().strip()
    return lowered.startswith("bearer ") or "authorization:" in lowered


def _nested_truthy(value: Any, match_key: str, child_key: str) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) == match_key and isinstance(item, dict) and bool(item.get(child_key)):
                return True
            if _nested_truthy(item, match_key, child_key):
                return True
    elif isinstance(value, list):
        return any(_nested_truthy(item, match_key, child_key) for item in value)
    return False
