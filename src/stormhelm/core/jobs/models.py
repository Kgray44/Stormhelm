from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from enum import Enum
from typing import Any

from stormhelm.shared.time import utc_now_iso
from stormhelm.core.worker_utilization import CancellationState
from stormhelm.core.worker_utilization import RestartRecoveryState
from stormhelm.core.worker_utilization import RetryPolicy
from stormhelm.core.worker_utilization import WorkerLane
from stormhelm.core.worker_utilization import WorkerPriorityLevel
from stormhelm.core.worker_utilization import YieldState
from stormhelm.core.worker_utilization import coerce_retry_policy
from stormhelm.core.worker_utilization import coerce_worker_lane
from stormhelm.core.worker_utilization import coerce_worker_priority
from stormhelm.core.worker_utilization import subsystem_cap_key_for as infer_subsystem_cap_key


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(slots=True)
class JobRecord:
    job_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: JobStatus
    created_at: str
    timeout_seconds: float
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    cancel_requested: bool = False
    session_id: str = "default"
    task_id: str | None = None
    task_step_id: str | None = None
    queued_at: str | None = None
    priority_lane: WorkerLane = WorkerLane.NORMAL
    priority_level: WorkerPriorityLevel = WorkerPriorityLevel.NORMAL
    interactive_deadline_ms: float | None = None
    background_ok: bool = False
    operator_visible: bool = True
    can_yield: bool = False
    starvation_sensitive: bool = False
    route_family: str = ""
    subsystem: str = ""
    continuation_id: str = ""
    latency_trace_id: str = ""
    safe_for_verification: bool = False
    completion_claimed: bool = False
    verification_claimed: bool = False
    queue_depth_at_submit: int = 0
    worker_capacity_at_submit: int = 0
    workers_busy_at_submit: int = 0
    workers_idle_at_submit: int = 0
    worker_saturation_percent_at_submit: float = 0.0
    scheduler_strategy: str = "priority_lane_with_caps"
    scheduler_pressure_state: str = "nominal"
    scheduler_pressure_reasons: list[str] = field(default_factory=list)
    protected_interactive_capacity: int = 0
    background_capacity_limit: int = 0
    protected_capacity_wait_reason: str = ""
    queue_wait_budget_ms: float | None = None
    queue_wait_budget_exceeded: bool = False
    subsystem_cap_key: str = ""
    subsystem_cap_limit: int | None = None
    subsystem_cap_wait_ms: float = 0.0
    subsystem_cap_wait_started_at_monotonic: float = 0.0
    retry_policy: RetryPolicy = RetryPolicy.NO_RETRY
    retry_count: int = 0
    retry_max_attempts: int = 1
    retry_backoff_ms: float = 0.0
    retry_last_error: str = ""
    attempt_count: int = 0
    cancellation_state: str = CancellationState.NOT_REQUESTED.value
    yield_state: str = YieldState.NOT_REQUESTED.value
    restart_recovery_state: str = RestartRecoveryState.NOT_INTERRUPTED.value
    worker_index: int | None = None
    worker_lane: str = ""
    worker_priority: str = ""
    queue_wait_ms: float = 0.0
    job_start_delay_ms: float = 0.0
    job_run_ms: float = 0.0
    job_total_ms: float = 0.0
    created_at_monotonic: float = 0.0
    queued_at_monotonic: float = 0.0
    started_at_monotonic: float = 0.0
    finished_at_monotonic: float = 0.0

    @classmethod
    def queued(
        cls,
        job_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
        *,
        session_id: str = "default",
        task_id: str | None = None,
        task_step_id: str | None = None,
        priority_lane: WorkerLane | str | None = None,
        priority_level: WorkerPriorityLevel | str | None = None,
        interactive_deadline_ms: float | None = None,
        background_ok: bool = False,
        operator_visible: bool = True,
        can_yield: bool = False,
        starvation_sensitive: bool = False,
        route_family: str | None = None,
        subsystem: str | None = None,
        continuation_id: str | None = None,
        latency_trace_id: str | None = None,
        safe_for_verification: bool = False,
        completion_claimed: bool = False,
        verification_claimed: bool = False,
        queue_depth_at_submit: int = 0,
        worker_capacity_at_submit: int = 0,
        workers_busy_at_submit: int = 0,
        workers_idle_at_submit: int = 0,
        worker_saturation_percent_at_submit: float = 0.0,
        scheduler_strategy: str = "priority_lane_with_caps",
        protected_interactive_capacity: int = 0,
        background_capacity_limit: int = 0,
        queue_wait_budget_ms: float | None = None,
        subsystem_cap_key: str | None = None,
        subsystem_cap_limit: int | None = None,
        retry_policy: RetryPolicy | str | None = None,
        retry_max_attempts: int = 1,
        retry_backoff_ms: float = 0.0,
        created_at_monotonic: float | None = None,
    ) -> "JobRecord":
        created_at = utc_now_iso()
        monotonic_now = float(created_at_monotonic if created_at_monotonic is not None else perf_counter())
        lane = coerce_worker_lane(priority_lane)
        priority = coerce_worker_priority(priority_level)
        retry = coerce_retry_policy(retry_policy)
        cap_key = str(subsystem_cap_key or infer_subsystem_cap_key(route_family=route_family, subsystem=subsystem))
        return cls(
            job_id=job_id,
            tool_name=tool_name,
            arguments=arguments,
            status=JobStatus.QUEUED,
            created_at=created_at,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            task_id=task_id,
            task_step_id=task_step_id,
            queued_at=created_at,
            priority_lane=lane,
            priority_level=priority,
            interactive_deadline_ms=interactive_deadline_ms,
            background_ok=bool(background_ok),
            operator_visible=bool(operator_visible),
            can_yield=bool(can_yield),
            starvation_sensitive=bool(starvation_sensitive),
            route_family=str(route_family or ""),
            subsystem=str(subsystem or ""),
            continuation_id=str(continuation_id or ""),
            latency_trace_id=str(latency_trace_id or ""),
            safe_for_verification=bool(safe_for_verification),
            completion_claimed=bool(completion_claimed),
            verification_claimed=bool(verification_claimed),
            queue_depth_at_submit=int(queue_depth_at_submit or 0),
            worker_capacity_at_submit=int(worker_capacity_at_submit or 0),
            workers_busy_at_submit=int(workers_busy_at_submit or 0),
            workers_idle_at_submit=int(workers_idle_at_submit or 0),
            worker_saturation_percent_at_submit=round(float(worker_saturation_percent_at_submit or 0.0), 3),
            scheduler_strategy=str(scheduler_strategy or "priority_lane_with_caps"),
            protected_interactive_capacity=int(protected_interactive_capacity or 0),
            background_capacity_limit=int(background_capacity_limit or 0),
            queue_wait_budget_ms=(
                round(float(queue_wait_budget_ms), 3)
                if queue_wait_budget_ms is not None
                else None
            ),
            subsystem_cap_key=cap_key,
            subsystem_cap_limit=int(subsystem_cap_limit) if subsystem_cap_limit is not None else None,
            retry_policy=retry,
            retry_max_attempts=max(1, int(retry_max_attempts or 1)),
            retry_backoff_ms=round(float(retry_backoff_ms or 0.0), 3),
            yield_state=YieldState.CAN_YIELD.value if can_yield else YieldState.NOT_REQUESTED.value,
            worker_lane=lane.value,
            worker_priority=priority.value,
            created_at_monotonic=monotonic_now,
            queued_at_monotonic=monotonic_now,
        )

    def mark_started(self, *, worker_index: int, now_monotonic: float | None = None) -> None:
        now = float(now_monotonic if now_monotonic is not None else perf_counter())
        self.started_at = utc_now_iso()
        self.started_at_monotonic = now
        self.worker_index = int(worker_index)
        self.worker_lane = self.priority_lane.value
        self.worker_priority = self.priority_level.value
        basis = self.queued_at_monotonic or self.created_at_monotonic or now
        self.queue_wait_ms = round(max(0.0, (now - basis) * 1000), 3)
        self.job_start_delay_ms = self.queue_wait_ms
        if self.queue_wait_budget_ms is not None:
            self.queue_wait_budget_exceeded = self.queue_wait_ms > self.queue_wait_budget_ms
        if self.subsystem_cap_wait_started_at_monotonic:
            self.subsystem_cap_wait_ms = round(
                max(0.0, (now - self.subsystem_cap_wait_started_at_monotonic) * 1000),
                3,
            )

    def mark_finished(self, *, now_monotonic: float | None = None) -> None:
        now = float(now_monotonic if now_monotonic is not None else perf_counter())
        self.finished_at = utc_now_iso()
        self.finished_at_monotonic = now
        if self.started_at_monotonic:
            self.job_run_ms = round(max(0.0, (now - self.started_at_monotonic) * 1000), 3)
        basis = self.created_at_monotonic or self.queued_at_monotonic or now
        self.job_total_ms = round(max(0.0, (now - basis) * 1000), 3)
        if not self.queue_wait_ms and self.started_at_monotonic:
            queued_basis = self.queued_at_monotonic or self.created_at_monotonic or self.started_at_monotonic
            self.queue_wait_ms = round(max(0.0, (self.started_at_monotonic - queued_basis) * 1000), 3)
            self.job_start_delay_ms = self.queue_wait_ms
        if self.queue_wait_budget_ms is not None:
            self.queue_wait_budget_exceeded = self.queue_wait_ms > self.queue_wait_budget_ms

    def worker_metadata(self) -> dict[str, Any]:
        return {
            "priority_lane": self.priority_lane.value,
            "priority_level": self.priority_level.value,
            "interactive_deadline_ms": self.interactive_deadline_ms,
            "background_ok": self.background_ok,
            "operator_visible": self.operator_visible,
            "can_yield": self.can_yield,
            "starvation_sensitive": self.starvation_sensitive,
            "route_family": self.route_family,
            "subsystem": self.subsystem,
            "continuation_id": self.continuation_id,
            "latency_trace_id": self.latency_trace_id,
            "safe_for_verification": self.safe_for_verification,
            "completion_claimed": self.completion_claimed,
            "verification_claimed": self.verification_claimed,
            "scheduler_strategy": self.scheduler_strategy,
            "scheduler_pressure_state": self.scheduler_pressure_state,
            "scheduler_pressure_reasons": list(self.scheduler_pressure_reasons[:8]),
            "protected_interactive_capacity": self.protected_interactive_capacity,
            "background_capacity_limit": self.background_capacity_limit,
            "protected_capacity_wait_reason": self.protected_capacity_wait_reason,
            "queue_wait_budget_ms": self.queue_wait_budget_ms,
            "queue_wait_budget_exceeded": self.queue_wait_budget_exceeded,
            "subsystem_cap_key": self.subsystem_cap_key,
            "subsystem_cap_limit": self.subsystem_cap_limit,
            "subsystem_cap_wait_ms": self.subsystem_cap_wait_ms,
            "retry_policy": self.retry_policy.value,
            "retry_count": self.retry_count,
            "retry_max_attempts": self.retry_max_attempts,
            "retry_backoff_ms": self.retry_backoff_ms,
            "retry_last_error": self.retry_last_error,
            "attempt_count": self.attempt_count,
            "cancellation_state": self.cancellation_state,
            "yield_state": self.yield_state,
            "restart_recovery_state": self.restart_recovery_state,
        }

    def timing_summary(self) -> dict[str, Any]:
        return {
            "queue_wait_ms": self.queue_wait_ms,
            "job_start_delay_ms": self.job_start_delay_ms,
            "job_run_ms": self.job_run_ms,
            "job_total_ms": self.job_total_ms,
            "worker_index": self.worker_index,
            "worker_lane": self.worker_lane or self.priority_lane.value,
            "worker_priority": self.worker_priority or self.priority_level.value,
            "queue_depth_at_submit": self.queue_depth_at_submit,
            "worker_capacity_at_submit": self.worker_capacity_at_submit,
            "workers_busy_at_submit": self.workers_busy_at_submit,
            "workers_idle_at_submit": self.workers_idle_at_submit,
            "worker_saturation_percent_at_submit": self.worker_saturation_percent_at_submit,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status.value,
            "created_at": self.created_at,
            "queued_at": self.queued_at or self.created_at,
            "timeout_seconds": self.timeout_seconds,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "task_step_id": self.task_step_id,
            **self.worker_metadata(),
            **self.timing_summary(),
            "worker_capacity": self.worker_capacity_at_submit,
            "workers_busy_at_submit": self.workers_busy_at_submit,
            "workers_idle_at_submit": self.workers_idle_at_submit,
            "worker_saturation_percent": self.worker_saturation_percent_at_submit,
            "job_timing_summary": self.timing_summary(),
        }
