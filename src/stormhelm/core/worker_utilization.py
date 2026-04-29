from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import Enum
from typing import Any

from stormhelm.core.latency import safe_latency_value


class WorkerLane(str, Enum):
    INTERACTIVE = "interactive"
    NORMAL = "normal"
    BACKGROUND = "background"


class WorkerPriorityLevel(str, Enum):
    CRITICAL_INTERACTIVE = "critical_interactive"
    INTERACTIVE = "interactive"
    NORMAL = "normal"
    BACKGROUND = "background"
    MAINTENANCE = "maintenance"


class WorkerStarvationState(str, Enum):
    NO_STARVATION = "no_starvation"
    SATURATED = "saturated"
    INTERACTIVE_WAITING = "interactive_waiting"
    BACKGROUND_PRESSURE = "background_pressure"
    QUEUE_BACKLOG = "queue_backlog"


class SchedulerPressureState(str, Enum):
    NOMINAL = "nominal"
    BUSY = "busy"
    SATURATED = "saturated"
    INTERACTIVE_WAITING = "interactive_waiting"
    BACKGROUND_THROTTLED = "background_throttled"
    BACKGROUND_PRESSURE = "background_pressure"
    SUBSYSTEM_CAP_PRESSURE = "subsystem_cap_pressure"
    QUEUE_BACKLOG = "queue_backlog"
    QUEUE_WAIT_BUDGET_EXCEEDED = "queue_wait_budget_exceeded"


class RetryPolicy(str, Enum):
    NO_RETRY = "no_retry"
    SAFE_READ_RETRY = "safe_read_retry"
    MANUAL_RETRY_REQUIRED = "manual_retry_required"


class CancellationState(str, Enum):
    NOT_REQUESTED = "not_requested"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED_BEFORE_START = "cancelled_before_start"
    CANCELLED_DURING_EXECUTION = "cancelled_during_execution"


class YieldState(str, Enum):
    NOT_REQUESTED = "not_requested"
    CAN_YIELD = "can_yield"
    YIELDED = "yielded"


class RestartRecoveryState(str, Enum):
    NOT_INTERRUPTED = "not_interrupted"
    INTERRUPTED_QUEUED_JOB = "interrupted_queued_job"
    INTERRUPTED_RUNNING_JOB = "interrupted_running_job"
    OPERATOR_CONFIRMATION_REQUIRED = "operator_confirmation_required"


@dataclass(frozen=True, slots=True)
class WorkerRoutePolicy:
    use_worker: bool
    priority_lane: WorkerLane = WorkerLane.NORMAL
    priority_level: WorkerPriorityLevel = WorkerPriorityLevel.NORMAL
    inline_reason: str = ""
    background_ok: bool = False
    operator_visible: bool = True
    can_yield: bool = False
    starvation_sensitive: bool = False
    interactive_deadline_ms: float | None = None
    max_queue_wait_ms: float | None = None
    safe_for_verification: bool = False
    debug: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return safe_latency_value(asdict(self))


@dataclass(frozen=True, slots=True)
class SchedulerPolicy:
    scheduler_strategy: str = "priority_lane_with_caps"
    protected_interactive_capacity: int = 1
    background_capacity_limit: int = 0
    subsystem_concurrency_caps: dict[str, int] | None = None
    interactive_queue_wait_budget_ms: float = 250.0
    normal_queue_wait_budget_ms: float = 1000.0
    background_queue_wait_budget_ms: float = 5000.0
    retry_backoff_ms: float = 100.0
    retry_max_attempts: int = 1

    def resolved_background_limit(self, worker_capacity: int) -> int:
        capacity = max(0, int(worker_capacity or 0))
        if capacity <= 1:
            return capacity
        explicit = int(self.background_capacity_limit or 0)
        if explicit > 0:
            return min(capacity, explicit)
        return max(1, capacity - max(0, int(self.protected_interactive_capacity or 0)))

    def cap_for(self, key: str | None) -> int | None:
        if not key:
            return None
        caps = self.subsystem_concurrency_caps or DEFAULT_SUBSYSTEM_CONCURRENCY_CAPS
        cap = caps.get(str(key))
        return int(cap) if cap is not None else None

    def queue_wait_budget_for(self, lane: WorkerLane | str | None) -> float | None:
        lane_value = coerce_worker_lane(lane)
        if lane_value == WorkerLane.INTERACTIVE:
            return self.interactive_queue_wait_budget_ms
        if lane_value == WorkerLane.BACKGROUND:
            return self.background_queue_wait_budget_ms
        return self.normal_queue_wait_budget_ms

    def to_dict(self) -> dict[str, Any]:
        return safe_latency_value(asdict(self))


DEFAULT_SUBSYSTEM_CONCURRENCY_CAPS: dict[str, int] = {
    "discord_relay.dispatch_approved_preview": 1,
    "software_control.execute_approved_operation": 1,
    "software_control.verify_operation": 1,
    "software_recovery.run_recovery_plan": 1,
    "screen_awareness.verify_change": 1,
    "screen_awareness.run_action": 1,
    "screen_awareness.run_workflow": 1,
    "workspace.restore_deep": 1,
    "network.run_live_diagnosis": 1,
    "background_refresh": 1,
}


INLINE_FAST_ROUTE_FAMILIES = {
    "calculations",
    "trust_approvals",
    "voice_control",
    "browser_destination",
    "context_clarification",
}
INLINE_FAST_REQUEST_KINDS = {
    "calculate",
    "calculation",
    "confirm",
    "approve",
    "reject",
    "cancel",
    "stop_speaking",
    "stop_talking",
    "playback_stop",
    "direct_url",
    "route_triage",
    "snapshot_lookup",
    "clarification",
}
WORKER_SUITABLE_FAMILIES = {
    "software_control",
    "software_recovery",
    "discord_relay",
    "screen_awareness",
    "workspace_operations",
    "workflow",
    "network",
    "hardware_telemetry",
    "semantic_memory",
    "file_operation",
    "maintenance",
}
BACKGROUND_FAMILIES = {
    "background_preparation",
    "route_family_status",
    "provider_readiness",
    "voice_readiness",
    "voice_playback_readiness",
    "network_status",
    "hardware_telemetry",
    "software_catalog",
    "snapshot_prune",
}


def classify_worker_route_policy(
    *,
    route_family: str | None = None,
    subsystem: str | None = None,
    request_kind: str | None = None,
    execution_mode: str | None = None,
    background_ok: bool | None = None,
) -> WorkerRoutePolicy:
    family = str(route_family or "").strip().lower()
    kind = str(request_kind or "").strip().lower()
    mode = str(execution_mode or "").strip().lower()
    background_allowed = bool(background_ok)
    debug = {
        "route_family": family,
        "subsystem": str(subsystem or "").strip().lower(),
        "request_kind": kind,
        "execution_mode": mode,
    }
    if family in BACKGROUND_FAMILIES or background_allowed:
        return WorkerRoutePolicy(
            use_worker=True,
            priority_lane=WorkerLane.BACKGROUND,
            priority_level=WorkerPriorityLevel.MAINTENANCE,
            inline_reason="",
            background_ok=True,
            operator_visible=False,
            can_yield=True,
            starvation_sensitive=False,
            max_queue_wait_ms=5000.0,
            safe_for_verification=False,
            debug=debug,
        )
    if family in INLINE_FAST_ROUTE_FAMILIES or kind in INLINE_FAST_REQUEST_KINDS:
        return WorkerRoutePolicy(
            use_worker=False,
            priority_lane=WorkerLane.INTERACTIVE,
            priority_level=WorkerPriorityLevel.INTERACTIVE,
            inline_reason="cheap_deterministic_hot_path",
            background_ok=False,
            operator_visible=True,
            can_yield=False,
            starvation_sensitive=True,
            interactive_deadline_ms=250.0,
            max_queue_wait_ms=0.0,
            safe_for_verification=False,
            debug=debug,
        )
    if mode == "async_first" or family in WORKER_SUITABLE_FAMILIES:
        return WorkerRoutePolicy(
            use_worker=True,
            priority_lane=WorkerLane.NORMAL,
            priority_level=WorkerPriorityLevel.NORMAL,
            background_ok=False,
            operator_visible=True,
            can_yield=False,
            starvation_sensitive=True,
            max_queue_wait_ms=1000.0,
            safe_for_verification=family
            in {"software_control", "software_recovery", "screen_awareness", "workflow"},
            debug=debug,
        )
    return WorkerRoutePolicy(
        use_worker=False,
        priority_lane=WorkerLane.INTERACTIVE,
        priority_level=WorkerPriorityLevel.INTERACTIVE,
        inline_reason="no_worker_suitable_shape",
        background_ok=False,
        operator_visible=True,
        can_yield=False,
        starvation_sensitive=True,
        interactive_deadline_ms=250.0,
        max_queue_wait_ms=0.0,
        safe_for_verification=False,
        debug=debug,
    )


def coerce_worker_lane(value: WorkerLane | str | None) -> WorkerLane:
    if isinstance(value, WorkerLane):
        return value
    try:
        return WorkerLane(str(value or "").strip().lower())
    except ValueError:
        return WorkerLane.NORMAL


def coerce_worker_priority(value: WorkerPriorityLevel | str | None) -> WorkerPriorityLevel:
    if isinstance(value, WorkerPriorityLevel):
        return value
    try:
        return WorkerPriorityLevel(str(value or "").strip().lower())
    except ValueError:
        return WorkerPriorityLevel.NORMAL


def coerce_retry_policy(value: RetryPolicy | str | None) -> RetryPolicy:
    if isinstance(value, RetryPolicy):
        return value
    try:
        return RetryPolicy(str(value or "").strip().lower())
    except ValueError:
        return RetryPolicy.NO_RETRY


def subsystem_cap_key_for(*, route_family: str | None = None, subsystem: str | None = None) -> str:
    subsystem_value = str(subsystem or "").strip().lower()
    if "." in subsystem_value:
        return subsystem_value
    family_value = str(route_family or "").strip().lower()
    if "." in family_value:
        return family_value
    return subsystem_value or family_value


def worker_priority_sort_key(
    lane: WorkerLane | str | None,
    priority: WorkerPriorityLevel | str | None,
) -> int:
    priority_value = coerce_worker_priority(priority)
    lane_value = coerce_worker_lane(lane)
    priority_weights = {
        WorkerPriorityLevel.CRITICAL_INTERACTIVE: 0,
        WorkerPriorityLevel.INTERACTIVE: 1,
        WorkerPriorityLevel.NORMAL: 3,
        WorkerPriorityLevel.BACKGROUND: 6,
        WorkerPriorityLevel.MAINTENANCE: 8,
    }
    lane_offsets = {
        WorkerLane.INTERACTIVE: 0,
        WorkerLane.NORMAL: 2,
        WorkerLane.BACKGROUND: 5,
    }
    return priority_weights.get(priority_value, 3) + lane_offsets.get(lane_value, 2)
