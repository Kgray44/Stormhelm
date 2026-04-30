from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SubsystemLatencyMode(str, Enum):
    INSTANT = "instant"
    PLAN_FIRST = "plan_first"
    ASYNC_FIRST = "async_first"
    CACHED_STATUS = "cached_status"
    LIVE_PROBE = "live_probe"


@dataclass(frozen=True, slots=True)
class SubsystemCachePolicy:
    cache_policy_id: str
    subsystem_id: str
    data_kind: str
    ttl_ms: float
    refresh_triggers: tuple[str, ...]
    invalidation_triggers: tuple[str, ...]
    stale_allowed: bool
    stale_label_required: bool
    max_stale_age_ms: float | None = None
    safe_for_planning: bool = False
    safe_for_verification: bool = False
    safe_for_user_display: bool = True
    unsafe_payload_fields: tuple[str, ...] = (
        "raw_audio",
        "raw_screenshot",
        "private_message_body",
        "discord_payload",
        "approval_payload",
        "secret",
        "token",
    )
    provenance_required: bool = True
    confidence_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SubsystemLatencyProfile:
    subsystem_id: str
    route_family: str
    hot_path_name: str
    latency_mode: SubsystemLatencyMode
    target_p50_ms: float
    target_p95_ms: float
    soft_ceiling_ms: float
    hard_ceiling_ms: float
    cache_policy_id: str = ""
    async_policy_id: str = ""
    requires_trust: bool = False
    requires_verification: bool = False
    provider_fallback_allowed: bool = False
    heavy_context_allowed: bool = False
    stale_data_allowed: bool = False
    stale_data_label_required: bool = False
    trace_stage_names: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["latency_mode"] = self.latency_mode.value
        return payload


@dataclass(frozen=True, slots=True)
class SubsystemHotPathDecision:
    subsystem_id: str
    route_family: str
    hot_path_name: str
    latency_mode: SubsystemLatencyMode
    cache_policy_id: str = ""
    cache_hit: bool = False
    cache_age_ms: float | None = None
    stale: bool = False
    async_continuation: bool = False
    live_probe_started: bool = False
    requires_trust: bool = False
    requires_verification: bool = False
    provider_fallback_used: bool = False
    heavy_context_used: bool = False
    stale_data_label_required: bool = False
    freshness_label_required: bool = False
    result_claim: str = ""
    execution_claim: str = ""
    delivery_claim_allowed: bool = False
    cloud_vision_used: bool = False
    truth_clamp_applied: bool = False
    deep_restore_deferred: bool = False
    memory_retrieval_used: bool = False
    planner_fast_path_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["latency_mode"] = self.latency_mode.value
        return payload


_UNSAFE_FIELDS = (
    "raw_audio",
    "raw_screenshot",
    "private_message_body",
    "discord_payload",
    "approval_payload",
    "secret",
    "token",
)


_CACHE_POLICIES: dict[str, SubsystemCachePolicy] = {
    "calculations_helper_registry_cache": SubsystemCachePolicy(
        cache_policy_id="calculations_helper_registry_cache",
        subsystem_id="calculations",
        data_kind="helper_registry_metadata",
        ttl_ms=86_400_000.0,
        refresh_triggers=("process_start", "calculation_helper_version_change"),
        invalidation_triggers=("calculation_helper_version_change",),
        stale_allowed=False,
        stale_label_required=False,
        safe_for_planning=True,
        safe_for_verification=True,
        unsafe_payload_fields=_UNSAFE_FIELDS,
    ),
    "browser_known_destination_cache": SubsystemCachePolicy(
        cache_policy_id="browser_known_destination_cache",
        subsystem_id="browser_destination",
        data_kind="known_destination_alias_index",
        ttl_ms=86_400_000.0,
        refresh_triggers=("process_start", "destination_catalog_change"),
        invalidation_triggers=("destination_catalog_change",),
        stale_allowed=False,
        stale_label_required=False,
        safe_for_planning=True,
        unsafe_payload_fields=_UNSAFE_FIELDS,
    ),
    "software_target_catalog_cache": SubsystemCachePolicy(
        cache_policy_id="software_target_catalog_cache",
        subsystem_id="software_control",
        data_kind="target_catalog_and_manager_availability",
        ttl_ms=300_000.0,
        refresh_triggers=("process_start", "software_catalog_refresh"),
        invalidation_triggers=("software_catalog_refresh", "package_manager_change"),
        stale_allowed=True,
        stale_label_required=True,
        max_stale_age_ms=900_000.0,
        safe_for_planning=True,
        safe_for_verification=False,
        unsafe_payload_fields=_UNSAFE_FIELDS,
    ),
    "software_verification_hint_cache": SubsystemCachePolicy(
        cache_policy_id="software_verification_hint_cache",
        subsystem_id="software_control",
        data_kind="path_registry_install_hints",
        ttl_ms=60_000.0,
        refresh_triggers=("software_probe_complete", "verification_requested"),
        invalidation_triggers=("software_install_attempted", "software_update_attempted", "software_uninstall_attempted"),
        stale_allowed=True,
        stale_label_required=True,
        max_stale_age_ms=300_000.0,
        safe_for_planning=True,
        safe_for_verification=False,
        unsafe_payload_fields=_UNSAFE_FIELDS,
    ),
    "discord_alias_fingerprint_cache": SubsystemCachePolicy(
        cache_policy_id="discord_alias_fingerprint_cache",
        subsystem_id="discord_relay",
        data_kind="trusted_aliases_client_readiness_payload_fingerprints",
        ttl_ms=300_000.0,
        refresh_triggers=("process_start", "discord_alias_update", "discord_client_probe"),
        invalidation_triggers=("discord_alias_update", "discord_client_state_change"),
        stale_allowed=True,
        stale_label_required=True,
        max_stale_age_ms=900_000.0,
        safe_for_planning=True,
        safe_for_verification=False,
        unsafe_payload_fields=_UNSAFE_FIELDS,
    ),
    "screen_observation_snapshot_cache": SubsystemCachePolicy(
        cache_policy_id="screen_observation_snapshot_cache",
        subsystem_id="screen_awareness",
        data_kind="focused_window_ranked_observation_snapshot",
        ttl_ms=5_000.0,
        refresh_triggers=("window_focus_changed", "screen_snapshot_captured"),
        invalidation_triggers=("window_focus_changed", "screen_capture_failed"),
        stale_allowed=True,
        stale_label_required=True,
        max_stale_age_ms=30_000.0,
        safe_for_planning=True,
        safe_for_verification=False,
        unsafe_payload_fields=_UNSAFE_FIELDS,
    ),
    "workspace_continuity_summary_cache": SubsystemCachePolicy(
        cache_policy_id="workspace_continuity_summary_cache",
        subsystem_id="workspace_tasks_memory",
        data_kind="active_task_workspace_summary",
        ttl_ms=60_000.0,
        refresh_triggers=("task_event", "workspace_event", "memory_summary_refresh"),
        invalidation_triggers=("task_event", "workspace_root_change"),
        stale_allowed=True,
        stale_label_required=True,
        max_stale_age_ms=600_000.0,
        safe_for_planning=True,
        safe_for_verification=False,
        unsafe_payload_fields=_UNSAFE_FIELDS,
    ),
    "network_status_snapshot_cache": SubsystemCachePolicy(
        cache_policy_id="network_status_snapshot_cache",
        subsystem_id="network_hardware_system",
        data_kind="network_hardware_system_status_snapshot",
        ttl_ms=10_000.0,
        refresh_triggers=("background_telemetry_tick", "live_probe_complete"),
        invalidation_triggers=("adapter_change", "network_probe_failed"),
        stale_allowed=True,
        stale_label_required=True,
        max_stale_age_ms=600_000.0,
        safe_for_planning=True,
        safe_for_verification=False,
        unsafe_payload_fields=_UNSAFE_FIELDS,
    ),
}


_PROFILES: dict[str, SubsystemLatencyProfile] = {
    "calculations": SubsystemLatencyProfile(
        subsystem_id="calculations",
        route_family="calculations",
        hot_path_name="direct_deterministic_calculation",
        latency_mode=SubsystemLatencyMode.INSTANT,
        target_p50_ms=100.0,
        target_p95_ms=150.0,
        soft_ceiling_ms=250.0,
        hard_ceiling_ms=500.0,
        cache_policy_id="calculations_helper_registry_cache",
        provider_fallback_allowed=False,
        heavy_context_allowed=False,
        trace_stage_names=("route_triage_ms", "calculation_parse_ms", "calculation_eval_ms", "route_handler_ms"),
        notes="Obvious deterministic math stays local; explanations are lazy unless requested.",
    ),
    "browser_destination": SubsystemLatencyProfile(
        subsystem_id="browser_destination",
        route_family="browser_destination",
        hot_path_name="browser_open_ack",
        latency_mode=SubsystemLatencyMode.PLAN_FIRST,
        target_p50_ms=300.0,
        target_p95_ms=500.0,
        soft_ceiling_ms=750.0,
        hard_ceiling_ms=1_500.0,
        cache_policy_id="browser_known_destination_cache",
        async_policy_id="browser_external_open_async_status",
        provider_fallback_allowed=False,
        heavy_context_allowed=False,
        trace_stage_names=("route_triage_ms", "browser_destination_resolve_ms", "route_handler_ms", "first_feedback_ms"),
        notes="Destination resolution and open acknowledgement are separate from page-load verification.",
    ),
    "software_control": SubsystemLatencyProfile(
        subsystem_id="software_control",
        route_family="software_control",
        hot_path_name="software_plan_ack",
        latency_mode=SubsystemLatencyMode.PLAN_FIRST,
        target_p50_ms=1_000.0,
        target_p95_ms=1_500.0,
        soft_ceiling_ms=2_000.0,
        hard_ceiling_ms=4_000.0,
        cache_policy_id="software_target_catalog_cache",
        async_policy_id="software_execution_verify_async",
        requires_trust=True,
        requires_verification=True,
        provider_fallback_allowed=False,
        heavy_context_allowed=False,
        stale_data_allowed=True,
        stale_data_label_required=True,
        trace_stage_names=("route_triage_ms", "software_catalog_lookup_ms", "software_plan_ms", "first_feedback_ms"),
        notes="Plan/approval returns before execution; cached hints never become install success.",
    ),
    "discord_relay": SubsystemLatencyProfile(
        subsystem_id="discord_relay",
        route_family="discord_relay",
        hot_path_name="discord_preview_first",
        latency_mode=SubsystemLatencyMode.PLAN_FIRST,
        target_p50_ms=1_200.0,
        target_p95_ms=1_800.0,
        soft_ceiling_ms=2_500.0,
        hard_ceiling_ms=5_000.0,
        cache_policy_id="discord_alias_fingerprint_cache",
        async_policy_id="discord_dispatch_async_trust_gate",
        requires_trust=True,
        requires_verification=True,
        provider_fallback_allowed=False,
        heavy_context_allowed=False,
        stale_data_allowed=True,
        stale_data_label_required=True,
        trace_stage_names=("route_triage_ms", "discord_alias_lookup_ms", "discord_preview_ms", "first_feedback_ms"),
        notes="Preview is cheap and non-dispatching; dispatch remains approval-gated.",
    ),
    "screen_awareness": SubsystemLatencyProfile(
        subsystem_id="screen_awareness",
        route_family="screen_awareness",
        hot_path_name="screen_simple_context_snapshot",
        latency_mode=SubsystemLatencyMode.CACHED_STATUS,
        target_p50_ms=1_000.0,
        target_p95_ms=1_500.0,
        soft_ceiling_ms=2_000.0,
        hard_ceiling_ms=4_000.0,
        cache_policy_id="screen_observation_snapshot_cache",
        async_policy_id="screen_full_verification_async",
        requires_verification=True,
        provider_fallback_allowed=False,
        heavy_context_allowed=True,
        stale_data_allowed=True,
        stale_data_label_required=True,
        trace_stage_names=("route_triage_ms", "screen_snapshot_lookup_ms", "screen_simple_context_ms", "first_feedback_ms"),
        notes="Fresh ranked observations answer simple questions; full verification is progressive.",
    ),
    "workspace_tasks_memory": SubsystemLatencyProfile(
        subsystem_id="workspace_tasks_memory",
        route_family="task_continuity",
        hot_path_name="workspace_continuity_summary",
        latency_mode=SubsystemLatencyMode.CACHED_STATUS,
        target_p50_ms=1_000.0,
        target_p95_ms=1_500.0,
        soft_ceiling_ms=2_000.0,
        hard_ceiling_ms=4_000.0,
        cache_policy_id="workspace_continuity_summary_cache",
        async_policy_id="workspace_deep_restore_async",
        provider_fallback_allowed=False,
        heavy_context_allowed=True,
        stale_data_allowed=True,
        stale_data_label_required=True,
        trace_stage_names=("route_triage_ms", "workspace_summary_lookup_ms", "memory_retrieval_ms", "first_feedback_ms"),
        notes="Continuity summaries are bounded and provenance-bearing; deep restore is deferred.",
    ),
    "network_hardware_system": SubsystemLatencyProfile(
        subsystem_id="network_hardware_system",
        route_family="network",
        hot_path_name="network_cached_status",
        latency_mode=SubsystemLatencyMode.CACHED_STATUS,
        target_p50_ms=250.0,
        target_p95_ms=500.0,
        soft_ceiling_ms=1_000.0,
        hard_ceiling_ms=2_000.0,
        cache_policy_id="network_status_snapshot_cache",
        async_policy_id="network_live_probe_async",
        provider_fallback_allowed=False,
        heavy_context_allowed=False,
        stale_data_allowed=True,
        stale_data_label_required=True,
        trace_stage_names=("route_triage_ms", "status_snapshot_ms", "live_probe_submit_ms", "first_feedback_ms"),
        notes="Cached status is immediate and labeled; deeper probes continue asynchronously.",
    ),
}


_ROUTE_FAMILY_TO_SUBSYSTEM = {
    "calculations": "calculations",
    "browser_destination": "browser_destination",
    "software_control": "software_control",
    "discord_relay": "discord_relay",
    "screen_awareness": "screen_awareness",
    "task_continuity": "workspace_tasks_memory",
    "workspace_operations": "workspace_tasks_memory",
    "memory": "workspace_tasks_memory",
    "workspace_tasks_memory": "workspace_tasks_memory",
    "network": "network_hardware_system",
    "hardware": "network_hardware_system",
    "system": "network_hardware_system",
    "resource_status": "network_hardware_system",
    "network_hardware_system": "network_hardware_system",
}


def list_subsystem_latency_profiles() -> tuple[SubsystemLatencyProfile, ...]:
    return tuple(_PROFILES.values())


def list_subsystem_cache_policies() -> tuple[SubsystemCachePolicy, ...]:
    return tuple(_CACHE_POLICIES.values())


def get_subsystem_latency_profile(identifier: str | None) -> SubsystemLatencyProfile:
    key = _resolve_subsystem_id(identifier)
    if key not in _PROFILES:
        raise KeyError(f"Unknown L8 subsystem latency profile: {identifier}")
    return _PROFILES[key]


def get_subsystem_cache_policy(cache_policy_id: str) -> SubsystemCachePolicy:
    try:
        return _CACHE_POLICIES[cache_policy_id]
    except KeyError as error:
        raise KeyError(f"Unknown L8 subsystem cache policy: {cache_policy_id}") from error


def classify_subsystem_hot_path(
    *,
    subsystem_id: str | None = None,
    route_family: str | None = None,
    operation: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SubsystemHotPathDecision:
    metadata = metadata if isinstance(metadata, dict) else {}
    profile = get_subsystem_latency_profile(subsystem_id or route_family)
    route = route_family or profile.route_family
    op = _normalize_operation(operation or metadata.get("l8_operation") or metadata.get("operation") or metadata.get("request_kind"))
    cache_policy_id = profile.cache_policy_id
    policy = get_subsystem_cache_policy(cache_policy_id)
    cache_age = _optional_float(metadata.get("cache_age_ms"))
    cache_hit = bool(metadata.get("cache_hit", profile.latency_mode == SubsystemLatencyMode.CACHED_STATUS))
    stale = bool(
        metadata.get("stale")
        or (
            cache_age is not None
            and policy.ttl_ms >= 0
            and cache_age > policy.ttl_ms
            and policy.stale_allowed
        )
    )
    latency_mode = profile.latency_mode
    hot_path_name = profile.hot_path_name
    async_continuation = False
    live_probe_started = False
    result_claim = ""
    execution_claim = ""
    delivery_claim_allowed = False
    truth_clamp = False
    deep_restore_deferred = False
    memory_retrieval_used = bool(metadata.get("memory_retrieval_used"))
    cloud_vision_used = bool(metadata.get("cloud_vision_used"))
    heavy_context_used = bool(metadata.get("heavy_context_used") or metadata.get("heavy_context_loaded"))

    if profile.subsystem_id == "calculations":
        cache_hit = True
        hot_path_name = "deterministic_calculation_helper" if op == "helper" else "direct_deterministic_calculation"
        result_claim = "deterministic_local_result"
    elif profile.subsystem_id == "browser_destination":
        hot_path_name = "browser_open_ack"
        result_claim = "open_requested_not_load_verified"
        execution_claim = "external_load_not_blocking"
    elif profile.subsystem_id == "software_control":
        if op in {"install", "update", "uninstall", "repair", "execute"}:
            hot_path_name = "software_plan_ack"
            async_continuation = True
            execution_claim = "plan_approval_execution_verify_separate"
        elif op in {"verify", "verify_installed", "check_installed"}:
            cache_policy_id = "software_verification_hint_cache"
            hot_path_name = "software_cached_verification_hint"
            latency_mode = SubsystemLatencyMode.CACHED_STATUS
            result_claim = "cached_hint_not_verified_success"
        else:
            hot_path_name = "software_plan_ack"
    elif profile.subsystem_id == "discord_relay":
        if op == "dispatch":
            hot_path_name = "discord_dispatch_async_gated"
            async_continuation = True
            execution_claim = "dispatch_async_gated"
        else:
            hot_path_name = "discord_preview_first"
            execution_claim = "preview_only_not_dispatched"
        delivery_claim_allowed = False
    elif profile.subsystem_id == "screen_awareness":
        hot_path_name = "screen_simple_context_snapshot"
        result_claim = "screen_snapshot_with_freshness"
        cloud_vision_used = bool(metadata.get("cloud_vision_used") and metadata.get("cloud_vision_allowed"))
        if str(metadata.get("evidence_source") or "").strip().lower() == "clipboard":
            result_claim = "clipboard_hint_not_screen_truth"
            truth_clamp = True
    elif profile.subsystem_id == "workspace_tasks_memory":
        hot_path_name = "workspace_continuity_summary"
        deep_restore_deferred = True
        if route not in {"task_continuity", "workspace_operations", "memory", "workspace_tasks_memory"}:
            memory_retrieval_used = False
            heavy_context_used = False
    elif profile.subsystem_id == "network_hardware_system":
        if op in {"deep_probe", "live_probe", "diagnosis", "throughput", "speed_test"}:
            hot_path_name = "network_live_probe_async"
            latency_mode = SubsystemLatencyMode.ASYNC_FIRST
            async_continuation = True
            live_probe_started = True
            result_claim = "live_probe_pending"
            cache_hit = bool(metadata.get("cache_hit", False))
        else:
            hot_path_name = "network_cached_status"
            latency_mode = SubsystemLatencyMode.CACHED_STATUS
            result_claim = "cached_status_with_freshness"

    provider_fallback_used = bool(metadata.get("provider_fallback_used"))
    if not profile.provider_fallback_allowed:
        provider_fallback_used = False
    final_policy = get_subsystem_cache_policy(cache_policy_id)
    stale = bool(
        metadata.get("stale")
        or (
            cache_age is not None
            and final_policy.ttl_ms >= 0
            and cache_age > final_policy.ttl_ms
            and final_policy.stale_allowed
        )
    )

    return SubsystemHotPathDecision(
        subsystem_id=profile.subsystem_id,
        route_family=route,
        hot_path_name=hot_path_name,
        latency_mode=latency_mode,
        cache_policy_id=cache_policy_id,
        cache_hit=cache_hit,
        cache_age_ms=cache_age,
        stale=stale,
        async_continuation=async_continuation or bool(metadata.get("async_continuation")),
        live_probe_started=live_probe_started,
        requires_trust=profile.requires_trust,
        requires_verification=profile.requires_verification,
        provider_fallback_used=provider_fallback_used,
        heavy_context_used=heavy_context_used,
        stale_data_label_required=profile.stale_data_label_required or stale,
        freshness_label_required=profile.stale_data_label_required or profile.stale_data_allowed,
        result_claim=result_claim,
        execution_claim=execution_claim,
        delivery_claim_allowed=delivery_claim_allowed,
        cloud_vision_used=cloud_vision_used,
        truth_clamp_applied=truth_clamp,
        deep_restore_deferred=deep_restore_deferred,
        memory_retrieval_used=memory_retrieval_used,
        planner_fast_path_used=bool(metadata.get("planner_fast_path_used") or metadata.get("fast_path_used")),
    )


def subsystem_latency_trace_fields(
    *,
    route_family: str | None,
    subsystem: str | None,
    request_kind: str | None,
    metadata: dict[str, Any],
    stage_timings_ms: dict[str, float],
    provider_fallback_used: bool,
    heavy_context_used: bool,
    async_continuation: bool,
) -> dict[str, Any]:
    try:
        decision = classify_subsystem_hot_path(
            subsystem_id=subsystem,
            route_family=route_family,
            operation=request_kind,
            metadata={
                **metadata,
                "provider_fallback_used": provider_fallback_used,
                "heavy_context_used": heavy_context_used,
                "async_continuation": async_continuation,
            },
        )
    except KeyError:
        return {
            "subsystem_id": str(subsystem or route_family or ""),
            "hot_path_name": "",
            "latency_mode": "",
            "cache_hit": False,
            "cache_age_ms": None,
            "cache_policy_id": "",
            "live_probe_started": False,
            "heavy_context_used": heavy_context_used,
            "planner_fast_path_used": bool(metadata.get("fast_path_used")),
            "route_handler_ms": _optional_float(stage_timings_ms.get("route_handler_ms")),
            "first_feedback_ms": _optional_float(stage_timings_ms.get("first_feedback_ms")),
        }
    return {
        "subsystem_id": decision.subsystem_id,
        "hot_path_name": decision.hot_path_name,
        "latency_mode": decision.latency_mode.value,
        "cache_hit": decision.cache_hit,
        "cache_age_ms": decision.cache_age_ms,
        "cache_policy_id": decision.cache_policy_id,
        "live_probe_started": decision.live_probe_started,
        "heavy_context_used": decision.heavy_context_used,
        "planner_fast_path_used": decision.planner_fast_path_used,
        "route_handler_ms": _optional_float(stage_timings_ms.get("route_handler_ms")),
        "first_feedback_ms": _optional_float(stage_timings_ms.get("first_feedback_ms")),
        "stale_data_label_required": decision.stale_data_label_required,
        "freshness_label_required": decision.freshness_label_required,
        "result_claim": decision.result_claim,
        "execution_claim": decision.execution_claim,
    }


def _resolve_subsystem_id(identifier: str | None) -> str:
    key = str(identifier or "").strip().lower()
    if key in _PROFILES:
        return key
    return _ROUTE_FAMILY_TO_SUBSYSTEM.get(key, key)


def _normalize_operation(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None
