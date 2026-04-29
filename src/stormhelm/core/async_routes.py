from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any
from uuid import uuid4

from stormhelm.core.latency import LatencyBudget
from stormhelm.core.latency import RouteExecutionMode
from stormhelm.core.latency import safe_latency_value
from stormhelm.core.worker_utilization import WorkerRoutePolicy
from stormhelm.core.worker_utilization import classify_worker_route_policy
from stormhelm.shared.time import utc_now_iso


class AsyncRouteStrategy(str, Enum):
    NONE = "none"
    INITIAL_RESPONSE_ONLY = "initial_response_only"
    PLAN_THEN_RETURN = "plan_then_return"
    CREATE_JOB = "create_job"
    CREATE_TASK = "create_task"
    CREATE_JOB_AND_TASK = "create_job_and_task"
    WAIT_FOR_FAST_COMPLETION = "wait_for_fast_completion"
    FAIL_FAST_UNAVAILABLE = "fail_fast_unavailable"
    APPROVAL_REQUIRED_BEFORE_JOB = "approval_required_before_job"
    UNSUPPORTED_ASYNC = "unsupported_async"


class RouteProgressStage(str, Enum):
    ACKNOWLEDGED = "acknowledged"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    APPROVAL_REQUIRED = "approval_required"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    VERIFICATION_PENDING = "verification_pending"
    COMPLETED_UNVERIFIED = "completed_unverified"
    VERIFIED = "verified"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class RouteProgressStatus(str, Enum):
    ACTIVE = "active"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AsyncRouteDecision:
    route_family: str
    subsystem: str = ""
    async_strategy: AsyncRouteStrategy = AsyncRouteStrategy.NONE
    should_return_initial_response: bool = False
    should_create_job: bool = False
    should_create_task: bool = False
    should_publish_progress_events: bool = False
    expected_initial_result_state: str = "completed"
    expected_final_result_state: str = "completed_unverified"
    requires_approval_before_execution: bool = False
    verification_required: bool = False
    max_initial_response_ms: float | None = None
    continue_reason: str = ""
    budget_label: str = "ghost_interactive"
    execution_mode: str = RouteExecutionMode.INSTANT.value
    completion_claimed: bool = False
    verification_claimed: bool = False
    preferred_worker_lane: str = "interactive"
    priority_level: str = "interactive"
    background_ok: bool = False
    operator_visible: bool = True
    can_yield: bool = False
    interactive_deadline_ms: float | None = None
    max_queue_wait_ms: float | None = None
    starvation_sensitive: bool = False
    can_use_background_refresh: bool = False
    fanout_allowed: bool = False
    verification_worker_allowed: bool = False
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return safe_latency_value(asdict(self))


@dataclass(slots=True)
class RouteProgressState:
    continuation_id: str
    request_id: str
    session_id: str
    route_family: str
    subsystem: str = ""
    task_id: str | None = None
    job_id: str | None = None
    stage: RouteProgressStage = RouteProgressStage.ACKNOWLEDGED
    status: RouteProgressStatus = RouteProgressStatus.ACTIVE
    created_at: str = ""
    updated_at: str = ""
    expires_at: str | None = None
    message: str = ""
    progress_label: str = ""
    progress_percent: float | None = None
    verification_state: str = "not_verified"
    trust_state: str = ""
    result_state: str = "acknowledged"
    completion_claimed: bool = False
    verification_claimed: bool = False
    current_blocker: str | None = None
    next_expected_event: str | None = None
    latency_trace_id: str = ""
    budget_label: str = "ghost_interactive"
    execution_mode: str = RouteExecutionMode.INSTANT.value
    worker_lane: str = "interactive"
    priority_level: str = "interactive"
    queue_wait_ms: float | None = None
    worker_index: int | None = None
    worker_state: str = ""
    job_timing_summary: dict[str, Any] = field(default_factory=dict)
    starvation_warning: bool = False
    debug: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        session_id: str,
        route_family: str,
        subsystem: str = "",
        stage: RouteProgressStage | str = RouteProgressStage.ACKNOWLEDGED,
        message: str = "",
        progress_label: str = "",
        progress_percent: float | None = None,
        verification_state: str = "not_verified",
        trust_state: str = "",
        result_state: str | None = None,
        task_id: str | None = None,
        job_id: str | None = None,
        latency_trace_id: str = "",
        budget_label: str = "ghost_interactive",
        execution_mode: str = RouteExecutionMode.INSTANT.value,
        worker_lane: str = "interactive",
        priority_level: str = "interactive",
        queue_wait_ms: float | None = None,
        worker_index: int | None = None,
        worker_state: str = "",
        job_timing_summary: dict[str, Any] | None = None,
        starvation_warning: bool = False,
        completion_claimed: bool = False,
        verification_claimed: bool = False,
        current_blocker: str | None = None,
        next_expected_event: str | None = None,
        debug: dict[str, Any] | None = None,
    ) -> "RouteProgressState":
        resolved_stage = _coerce_stage(stage)
        timestamp = utc_now_iso()
        return cls(
            continuation_id=f"route-cont-{uuid4().hex}",
            request_id=str(request_id or ""),
            session_id=str(session_id or "default"),
            route_family=str(route_family or "unknown"),
            subsystem=str(subsystem or ""),
            task_id=task_id,
            job_id=job_id,
            stage=resolved_stage,
            status=_status_for_stage(resolved_stage),
            created_at=timestamp,
            updated_at=timestamp,
            message=str(message or "")[:500],
            progress_label=str(progress_label or "")[:160],
            progress_percent=_bounded_percent(progress_percent),
            verification_state=str(verification_state or "not_verified"),
            trust_state=str(trust_state or ""),
            result_state=str(result_state or resolved_stage.value),
            completion_claimed=bool(completion_claimed),
            verification_claimed=bool(verification_claimed),
            current_blocker=current_blocker,
            next_expected_event=next_expected_event,
            latency_trace_id=str(latency_trace_id or ""),
            budget_label=str(budget_label or "ghost_interactive"),
            execution_mode=str(execution_mode or RouteExecutionMode.INSTANT.value),
            worker_lane=str(worker_lane or "interactive"),
            priority_level=str(priority_level or "interactive"),
            queue_wait_ms=_bounded_ms(queue_wait_ms),
            worker_index=worker_index,
            worker_state=str(worker_state or ""),
            job_timing_summary=dict(job_timing_summary or {}),
            starvation_warning=bool(starvation_warning),
            debug=dict(debug or {}),
        ).truthful()

    def truthful(self) -> "RouteProgressState":
        if self.stage not in {RouteProgressStage.COMPLETED_UNVERIFIED, RouteProgressStage.VERIFIED}:
            self.completion_claimed = False
        if self.stage != RouteProgressStage.VERIFIED:
            self.verification_claimed = False
        if self.stage == RouteProgressStage.COMPLETED_UNVERIFIED:
            self.verification_claimed = False
        if self.stage == RouteProgressStage.VERIFIED:
            self.completion_claimed = True
            self.verification_claimed = True
        return self

    def to_dict(self) -> dict[str, Any]:
        self.truthful()
        payload = asdict(self)
        payload["stage"] = self.stage.value
        payload["status"] = self.status.value
        return safe_latency_value(payload)


@dataclass(frozen=True, slots=True)
class AsyncRouteHandle:
    continuation_id: str
    request_id: str
    session_id: str
    route_family: str
    subsystem: str = ""
    task_id: str | None = None
    job_id: str | None = None
    async_strategy: str = AsyncRouteStrategy.NONE.value
    progress_stage: str = RouteProgressStage.ACKNOWLEDGED.value
    events_expected: bool = False
    latency_trace_id: str = ""
    worker_lane: str = "interactive"
    priority_level: str = "interactive"
    queue_wait_ms: float | None = None
    worker_index: int | None = None
    worker_state: str = ""
    job_timing_summary: dict[str, Any] = field(default_factory=dict)
    starvation_warning: bool = False

    def to_dict(self) -> dict[str, Any]:
        return safe_latency_value(asdict(self))


@dataclass(frozen=True, slots=True)
class AsyncRouteContinuation:
    handle: AsyncRouteHandle
    progress_state: RouteProgressState
    decision: AsyncRouteDecision

    def to_dict(self) -> dict[str, Any]:
        return safe_latency_value(
            {
                "handle": self.handle.to_dict(),
                "progress_state": self.progress_state.to_dict(),
                "decision": self.decision.to_dict(),
            }
        )


@dataclass(frozen=True, slots=True)
class RouteContinuationSummary:
    continuation_id: str
    route_family: str
    async_strategy: str
    stage: str
    status: str
    job_id: str | None = None
    task_id: str | None = None
    events_expected: bool = False
    completion_claimed: bool = False
    verification_claimed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return safe_latency_value(asdict(self))


def classify_async_route_policy(
    *,
    route_family: str | None = None,
    subsystem: str | None = None,
    execution_mode: str | RouteExecutionMode | None = None,
    budget_label: str | None = None,
    request_stage: str | None = None,
    trust_posture: str | None = None,
    verification_posture: str | None = None,
    surface_mode: str | None = None,
    active_module: str | None = None,
    fail_fast_reason: str | None = None,
    tool_execution_mode: str | None = None,
) -> AsyncRouteDecision:
    family = str(route_family or "unknown").strip().lower() or "unknown"
    subsystem_key = str(subsystem or "").strip().lower()
    mode = _coerce_execution_mode(execution_mode)
    budget = LatencyBudget.for_label(budget_label)
    stage = str(request_stage or "").strip().lower()
    trust = str(trust_posture or "").strip().lower()
    verification = str(verification_posture or "").strip().lower()
    tool_mode = str(tool_execution_mode or "").strip().lower()
    debug = {
        "surface_mode": str(surface_mode or ""),
        "active_module": str(active_module or ""),
        "request_stage": stage,
        "trust_posture": trust,
        "verification_posture": verification,
        "tool_execution_mode": tool_mode,
    }
    worker_policy = classify_worker_route_policy(
        route_family=family,
        subsystem=subsystem_key,
        request_kind=stage,
        execution_mode=mode.value,
    )
    worker_fields = _worker_decision_fields(worker_policy)
    inline_worker_fields = _worker_decision_fields(worker_policy, force_inline=True)

    if str(fail_fast_reason or "").strip():
        return AsyncRouteDecision(
            route_family=family,
            subsystem=subsystem_key,
            async_strategy=AsyncRouteStrategy.FAIL_FAST_UNAVAILABLE,
            should_return_initial_response=True,
            expected_initial_result_state="blocked",
            expected_final_result_state="blocked",
            continue_reason=str(fail_fast_reason or "").strip(),
            budget_label=budget.label,
            execution_mode=RouteExecutionMode.UNSUPPORTED.value,
            **inline_worker_fields,
            debug=debug,
        )

    if mode in {RouteExecutionMode.UNSUPPORTED, RouteExecutionMode.CLARIFICATION}:
        return AsyncRouteDecision(
            route_family=family,
            subsystem=subsystem_key,
            async_strategy=AsyncRouteStrategy.UNSUPPORTED_ASYNC
            if mode == RouteExecutionMode.UNSUPPORTED
            else AsyncRouteStrategy.INITIAL_RESPONSE_ONLY,
            should_return_initial_response=True,
            expected_initial_result_state="blocked",
            expected_final_result_state="blocked",
            continue_reason=mode.value,
            budget_label=budget.label,
            execution_mode=mode.value,
            **inline_worker_fields,
            debug=debug,
        )

    if "approval" in stage and "approved" not in trust:
        return AsyncRouteDecision(
            route_family=family,
            subsystem=subsystem_key,
            async_strategy=AsyncRouteStrategy.APPROVAL_REQUIRED_BEFORE_JOB,
            should_return_initial_response=True,
            should_publish_progress_events=True,
            expected_initial_result_state="approval_required",
            expected_final_result_state="queued",
            requires_approval_before_execution=True,
            verification_required=True,
            max_initial_response_ms=_max_initial_response_ms(budget),
            continue_reason="approval_required_before_job",
            budget_label=budget.label,
            execution_mode=mode.value,
            **inline_worker_fields,
            debug=debug,
        )

    if tool_mode == "async":
        return AsyncRouteDecision(
            route_family=family,
            subsystem=subsystem_key,
            async_strategy=AsyncRouteStrategy.CREATE_JOB,
            should_return_initial_response=True,
            should_create_job=True,
            should_publish_progress_events=True,
            expected_initial_result_state="queued",
            expected_final_result_state="completed_unverified",
            verification_required=_verification_required(verification),
            max_initial_response_ms=_max_initial_response_ms(budget),
            continue_reason="async_tool_job",
            budget_label=budget.label,
            execution_mode=RouteExecutionMode.ASYNC_FIRST.value,
            **worker_fields,
            debug=debug,
        )

    if mode == RouteExecutionMode.ASYNC_FIRST or budget.async_continuation_expected:
        strategy = (
            AsyncRouteStrategy.CREATE_JOB_AND_TASK
            if family in _TASK_BACKED_ASYNC_FAMILIES
            else AsyncRouteStrategy.CREATE_JOB
        )
        return AsyncRouteDecision(
            route_family=family,
            subsystem=subsystem_key,
            async_strategy=strategy,
            should_return_initial_response=True,
            should_create_job=True,
            should_create_task=strategy == AsyncRouteStrategy.CREATE_JOB_AND_TASK,
            should_publish_progress_events=True,
            expected_initial_result_state="queued",
            expected_final_result_state="verification_pending"
            if _verification_required(verification) or family in _VERIFYING_FAMILIES
            else "completed_unverified",
            verification_required=_verification_required(verification) or family in _VERIFYING_FAMILIES,
            max_initial_response_ms=_max_initial_response_ms(budget),
            continue_reason="async_expected",
            budget_label=budget.label,
            execution_mode=mode.value,
            **worker_fields,
            debug=debug,
        )

    if mode == RouteExecutionMode.PLAN_FIRST:
        return AsyncRouteDecision(
            route_family=family,
            subsystem=subsystem_key,
            async_strategy=AsyncRouteStrategy.PLAN_THEN_RETURN,
            should_return_initial_response=True,
            should_publish_progress_events=True,
            expected_initial_result_state="planning",
            expected_final_result_state="plan_ready",
            max_initial_response_ms=_max_initial_response_ms(budget),
            continue_reason="plan_first",
            budget_label=budget.label,
            execution_mode=mode.value,
            **inline_worker_fields,
            debug=debug,
        )

    if mode == RouteExecutionMode.PROVIDER_WAIT:
        return AsyncRouteDecision(
            route_family=family,
            subsystem=subsystem_key,
            async_strategy=AsyncRouteStrategy.WAIT_FOR_FAST_COMPLETION,
            should_return_initial_response=False,
            expected_initial_result_state="planning",
            expected_final_result_state="completed_unverified",
            budget_label=budget.label,
            execution_mode=mode.value,
            **inline_worker_fields,
            debug=debug,
        )

    return AsyncRouteDecision(
        route_family=family,
        subsystem=subsystem_key,
        async_strategy=AsyncRouteStrategy.NONE,
        should_return_initial_response=False,
        expected_initial_result_state="completed",
        expected_final_result_state="completed_unverified",
        budget_label=budget.label,
        execution_mode=mode.value,
        completion_claimed=True,
        **inline_worker_fields,
        debug=debug,
    )


_TASK_BACKED_ASYNC_FAMILIES = {
    "software_control",
    "software_recovery",
    "workflow",
    "routine",
    "workspace_operations",
    "screen_awareness",
    "discord_relay",
    "file_operation",
    "maintenance",
}
_VERIFYING_FAMILIES = {
    "software_control",
    "software_recovery",
    "screen_awareness",
    "file_operation",
    "maintenance",
    "workflow",
}


def _coerce_stage(stage: RouteProgressStage | str) -> RouteProgressStage:
    if isinstance(stage, RouteProgressStage):
        return stage
    try:
        return RouteProgressStage(str(stage or "").strip())
    except ValueError:
        return RouteProgressStage.ACKNOWLEDGED


def _coerce_execution_mode(value: str | RouteExecutionMode | None) -> RouteExecutionMode:
    if isinstance(value, RouteExecutionMode):
        return value
    try:
        return RouteExecutionMode(str(value or "").strip())
    except ValueError:
        return RouteExecutionMode.INSTANT


def _status_for_stage(stage: RouteProgressStage) -> RouteProgressStatus:
    if stage == RouteProgressStage.VERIFIED or stage == RouteProgressStage.COMPLETED_UNVERIFIED:
        return RouteProgressStatus.COMPLETE
    if stage == RouteProgressStage.FAILED:
        return RouteProgressStatus.FAILED
    if stage == RouteProgressStage.BLOCKED or stage == RouteProgressStage.APPROVAL_REQUIRED:
        return RouteProgressStatus.BLOCKED
    if stage == RouteProgressStage.CANCELLED:
        return RouteProgressStatus.CANCELLED
    return RouteProgressStatus.ACTIVE


def _bounded_percent(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(100.0, round(float(value), 3)))
    except (TypeError, ValueError):
        return None


def _bounded_ms(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, round(float(value), 3))
    except (TypeError, ValueError):
        return None


def _worker_decision_fields(
    policy: WorkerRoutePolicy,
    *,
    force_inline: bool = False,
) -> dict[str, Any]:
    if force_inline:
        return {
            "preferred_worker_lane": "interactive",
            "priority_level": "interactive",
            "background_ok": False,
            "operator_visible": True,
            "can_yield": False,
            "interactive_deadline_ms": policy.interactive_deadline_ms or 250.0,
            "max_queue_wait_ms": 0.0,
            "starvation_sensitive": True,
            "can_use_background_refresh": False,
            "fanout_allowed": False,
            "verification_worker_allowed": False,
        }
    return {
        "preferred_worker_lane": policy.priority_lane.value,
        "priority_level": policy.priority_level.value,
        "background_ok": bool(policy.background_ok),
        "operator_visible": bool(policy.operator_visible),
        "can_yield": bool(policy.can_yield),
        "interactive_deadline_ms": policy.interactive_deadline_ms,
        "max_queue_wait_ms": policy.max_queue_wait_ms,
        "starvation_sensitive": bool(policy.starvation_sensitive),
        "can_use_background_refresh": bool(policy.background_ok),
        "fanout_allowed": False,
        "verification_worker_allowed": bool(policy.safe_for_verification),
    }


def _max_initial_response_ms(budget: LatencyBudget) -> float | None:
    return (
        budget.target_ack_ms
        or budget.target_first_feedback_ms
        or budget.target_initial_plan_ms
        or budget.target_ms
    )


def _verification_required(verification_posture: str) -> bool:
    text = str(verification_posture or "").strip().lower()
    return any(marker in text for marker in {"required", "pending", "verify", "verification"})
