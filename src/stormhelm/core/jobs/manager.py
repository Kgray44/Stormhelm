from __future__ import annotations

import asyncio
from collections import Counter
from time import perf_counter
from typing import Callable
from uuid import uuid4

from stormhelm.config.models import AppConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.models import JobRecord, JobStatus
from stormhelm.core.latency import safe_latency_value
from stormhelm.core.memory.repositories import ToolRunRepository
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.worker_utilization import CancellationState
from stormhelm.core.worker_utilization import RestartRecoveryState
from stormhelm.core.worker_utilization import RetryPolicy
from stormhelm.core.worker_utilization import SchedulerPolicy
from stormhelm.core.worker_utilization import SchedulerPressureState
from stormhelm.core.worker_utilization import WorkerLane
from stormhelm.core.worker_utilization import WorkerPriorityLevel
from stormhelm.core.worker_utilization import WorkerStarvationState
from stormhelm.core.worker_utilization import coerce_retry_policy
from stormhelm.core.worker_utilization import coerce_worker_lane
from stormhelm.core.worker_utilization import coerce_worker_priority
from stormhelm.core.worker_utilization import worker_priority_sort_key


ToolContextFactory = Callable[[str], ToolContext]


def _lane_counter(jobs: list[JobRecord]) -> Counter[str]:
    counts: Counter[str] = Counter({lane.value: 0 for lane in WorkerLane})
    for job in jobs:
        counts[job.priority_lane.value] += 1
    return counts


class JobManager:
    def __init__(
        self,
        *,
        config: AppConfig,
        executor: ToolExecutor,
        context_factory: ToolContextFactory,
        tool_runs: ToolRunRepository,
        events: EventBuffer,
        observer: object | None = None,
    ) -> None:
        self.config = config
        self.executor = executor
        self.context_factory = context_factory
        self.tool_runs = tool_runs
        self.events = events
        self.observer = observer
        protected = 1 if int(config.concurrency.max_workers or 0) > 1 else 0
        self.scheduler_policy = SchedulerPolicy(protected_interactive_capacity=protected)
        self._pending_jobs: list[tuple[int, int, JobRecord]] = []
        self._queue_condition = asyncio.Condition()
        self._workers: list[asyncio.Task[None]] = []
        self._completion_futures: dict[str, asyncio.Future[JobRecord]] = {}
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._jobs: dict[str, JobRecord] = {}
        self._starting_job_ids: set[str] = set()
        self._submit_sequence = 0
        self._stopping = False

    async def start(self) -> None:
        if self._workers:
            return
        self._stopping = False
        for index in range(self.config.concurrency.max_workers):
            self._workers.append(asyncio.create_task(self._worker_loop(index + 1)))
        self.events.publish(
            event_family="lifecycle",
            event_type="lifecycle.job_manager.started",
            severity="info",
            subsystem="job_manager",
            visibility_scope="systems_surface",
            retention_class="operator_relevant",
            message=f"Started {len(self._workers)} job workers.",
            payload={"worker_count": len(self._workers)},
        )

    async def stop(self) -> None:
        self._stopping = True
        for job in self._jobs.values():
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.cancellation_state = CancellationState.CANCELLED_BEFORE_START.value
                job.restart_recovery_state = RestartRecoveryState.INTERRUPTED_QUEUED_JOB.value
                job.mark_finished()
                job.error = "cancelled_on_shutdown"
                self._finalize(job)
        self._pending_jobs.clear()

        for job_id in list(self._active_tasks):
            job = self._jobs.get(job_id)
            if job is not None:
                job.restart_recovery_state = RestartRecoveryState.INTERRUPTED_RUNNING_JOB.value
        for task in self._active_tasks.values():
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)

        for task in self._workers:
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._active_tasks.clear()
        self._starting_job_ids.clear()
        self._stopping = False

    async def submit(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        session_id: str = "default",
        timeout_seconds: float | None = None,
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
        max_queue_wait_ms: float | None = None,
        subsystem_cap_key: str | None = None,
        subsystem_cap_limit: int | None = None,
        retry_policy: RetryPolicy | str | None = None,
        retry_max_attempts: int | None = None,
        retry_backoff_ms: float | None = None,
    ) -> JobRecord:
        timeout = timeout_seconds or self.config.concurrency.default_job_timeout_seconds
        submit_started = perf_counter()
        submit_snapshot = self.worker_status_snapshot(now_monotonic=submit_started)
        lane = coerce_worker_lane(priority_lane)
        priority = coerce_worker_priority(priority_level)
        retry = coerce_retry_policy(retry_policy)
        queue_wait_budget = (
            float(max_queue_wait_ms)
            if max_queue_wait_ms is not None
            else self.scheduler_policy.queue_wait_budget_for(lane)
        )
        capacity = int(self.config.concurrency.max_workers or 0)
        background_limit = self.scheduler_policy.resolved_background_limit(capacity)
        cap_key = subsystem_cap_key
        cap_limit = (
            int(subsystem_cap_limit)
            if subsystem_cap_limit is not None
            else self.scheduler_policy.cap_for(cap_key or subsystem)
        )
        job = JobRecord.queued(
            str(uuid4()),
            tool_name,
            dict(arguments),
            timeout,
            session_id=session_id,
            task_id=task_id,
            task_step_id=task_step_id,
            priority_lane=lane,
            priority_level=priority,
            interactive_deadline_ms=interactive_deadline_ms,
            background_ok=background_ok,
            operator_visible=operator_visible,
            can_yield=can_yield,
            starvation_sensitive=starvation_sensitive,
            route_family=route_family,
            subsystem=subsystem,
            continuation_id=continuation_id,
            latency_trace_id=latency_trace_id,
            safe_for_verification=safe_for_verification,
            queue_depth_at_submit=int(submit_snapshot.get("queue_depth") or 0),
            worker_capacity_at_submit=int(submit_snapshot.get("worker_capacity") or 0),
            workers_busy_at_submit=int(submit_snapshot.get("workers_busy") or 0),
            workers_idle_at_submit=int(submit_snapshot.get("workers_idle") or 0),
            worker_saturation_percent_at_submit=float(submit_snapshot.get("worker_saturation_percent") or 0.0),
            scheduler_strategy=self.scheduler_policy.scheduler_strategy,
            protected_interactive_capacity=int(self.scheduler_policy.protected_interactive_capacity or 0),
            background_capacity_limit=background_limit,
            queue_wait_budget_ms=queue_wait_budget,
            subsystem_cap_key=cap_key,
            subsystem_cap_limit=cap_limit,
            retry_policy=retry,
            retry_max_attempts=(
                int(retry_max_attempts)
                if retry_max_attempts is not None
                else (
                    max(2, int(self.scheduler_policy.retry_max_attempts or 1))
                    if retry == RetryPolicy.SAFE_READ_RETRY
                    else 1
                )
            ),
            retry_backoff_ms=(
                float(retry_backoff_ms)
                if retry_backoff_ms is not None
                else (self.scheduler_policy.retry_backoff_ms if retry == RetryPolicy.SAFE_READ_RETRY else 0.0)
            ),
            created_at_monotonic=submit_started,
        )
        self._jobs[job.job_id] = job
        self._persist(job)
        self._notify_observer("on_job_queued", job)
        self.events.publish(
            event_family="job",
            event_type="job.queued",
            severity="info",
            subsystem="job_manager",
            subject=job.job_id,
            visibility_scope="watch_surface",
            retention_class="operator_relevant",
            provenance={"channel": "job_manager", "kind": "direct_system_fact"},
            message=f"Queued job {job.job_id} for tool '{tool_name}'.",
            payload=self._job_event_payload(job),
        )
        loop = asyncio.get_running_loop()
        self._completion_futures[job.job_id] = loop.create_future()
        if self._queued_job_count() > int(self.config.concurrency.queue_size or 0):
            job.status = JobStatus.FAILED
            job.mark_finished()
            job.error = "job_queue_full"
            self._finalize(job)
            raise RuntimeError("Stormhelm job queue is full.")
        self._submit_sequence += 1
        async with self._queue_condition:
            self._pending_jobs.append(
                (
                    worker_priority_sort_key(job.priority_lane, job.priority_level),
                    self._submit_sequence,
                    job,
                )
            )
            self._queue_condition.notify_all()
        return job

    async def submit_and_wait(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        session_id: str = "default",
        timeout_seconds: float | None = None,
    ) -> JobRecord:
        job = await self.submit(tool_name, arguments, session_id=session_id, timeout_seconds=timeout_seconds)
        return await self.wait(job.job_id)

    async def submit_background_refresh(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        session_id: str = "default",
        subsystem: str = "",
        route_family: str = "background_preparation",
        timeout_seconds: float | None = None,
    ) -> JobRecord:
        return await self.submit(
            tool_name,
            arguments,
            session_id=session_id,
            timeout_seconds=timeout_seconds,
            priority_lane=WorkerLane.BACKGROUND,
            priority_level=WorkerPriorityLevel.MAINTENANCE,
            background_ok=True,
            operator_visible=False,
            can_yield=True,
            starvation_sensitive=False,
            route_family=route_family,
            subsystem=subsystem,
            safe_for_verification=False,
        )

    async def wait(self, job_id: str) -> JobRecord:
        job = self._jobs.get(job_id)
        if job is not None and job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return job
        future = self._completion_futures[job_id]
        return await future

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False

        job.cancel_requested = True
        job.cancellation_state = CancellationState.CANCEL_REQUESTED.value
        active_task = self._active_tasks.get(job_id)
        if active_task is not None:
            active_task.cancel()
            return True

        if job.status == JobStatus.QUEUED:
            self._remove_pending_job(job_id)
            job.status = JobStatus.CANCELLED
            job.cancellation_state = CancellationState.CANCELLED_BEFORE_START.value
            job.mark_finished()
            job.error = "cancelled_before_start"
            self._finalize(job)
            return True
        return False

    def list_jobs(self, limit: int = 100) -> list[dict[str, object]]:
        jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
        return [job.to_dict() for job in jobs[:limit]]

    def _queued_job_count(self) -> int:
        return sum(1 for job in self._jobs.values() if job.status == JobStatus.QUEUED)

    def _remove_pending_job(self, job_id: str) -> None:
        self._pending_jobs = [item for item in self._pending_jobs if item[2].job_id != job_id]

    async def _worker_loop(self, worker_index: int) -> None:
        while True:
            job = await self._next_eligible_job()
            try:
                if job.status == JobStatus.CANCELLED:
                    self._starting_job_ids.discard(job.job_id)
                    continue
                task = asyncio.create_task(self._execute_job(job, worker_index))
                self._active_tasks[job.job_id] = task
                await task
            finally:
                self._active_tasks.pop(job.job_id, None)
                async with self._queue_condition:
                    self._queue_condition.notify_all()

    async def _next_eligible_job(self) -> JobRecord:
        async with self._queue_condition:
            while True:
                selected = self._select_eligible_pending_index()
                if selected is not None:
                    _, _, job = self._pending_jobs.pop(selected)
                    self._starting_job_ids.add(job.job_id)
                    return job
                await self._queue_condition.wait()

    def _select_eligible_pending_index(self) -> int | None:
        now = perf_counter()
        candidates = sorted(enumerate(self._pending_jobs), key=lambda item: (item[1][0], item[1][1]))
        first_blocked_reason = ""
        for index, (_, _, job) in candidates:
            if job.status != JobStatus.QUEUED:
                continue
            eligible, reason = self._job_is_eligible_to_start(job, now_monotonic=now)
            if eligible:
                job.scheduler_pressure_state = self.worker_status_snapshot(now_monotonic=now).get(
                    "scheduler_pressure_state",
                    SchedulerPressureState.NOMINAL.value,
                )
                return index
            first_blocked_reason = first_blocked_reason or reason
        if first_blocked_reason:
            for _, (_, _, job) in candidates:
                if job.status == JobStatus.QUEUED:
                    job.protected_capacity_wait_reason = first_blocked_reason
                    break
        return None

    def _job_is_eligible_to_start(self, job: JobRecord, *, now_monotonic: float) -> tuple[bool, str]:
        active = self._active_or_starting_jobs()
        active_background = sum(1 for item in active if item.priority_lane == WorkerLane.BACKGROUND)
        if job.priority_lane == WorkerLane.BACKGROUND:
            background_limit = self.scheduler_policy.resolved_background_limit(self.config.concurrency.max_workers)
            job.background_capacity_limit = background_limit
            if background_limit > 0 and active_background >= background_limit:
                job.protected_capacity_wait_reason = "protected_interactive_capacity"
                return False, "protected_interactive_capacity"

        cap_key = job.subsystem_cap_key
        cap_limit = job.subsystem_cap_limit
        if cap_limit is None:
            cap_limit = self.scheduler_policy.cap_for(cap_key)
            job.subsystem_cap_limit = cap_limit
        if cap_key and cap_limit is not None and cap_limit > 0:
            active_for_cap = sum(1 for item in active if item.subsystem_cap_key == cap_key)
            if active_for_cap >= cap_limit:
                if not job.subsystem_cap_wait_started_at_monotonic:
                    job.subsystem_cap_wait_started_at_monotonic = now_monotonic
                job.subsystem_cap_wait_ms = round(
                    max(0.0, (now_monotonic - job.subsystem_cap_wait_started_at_monotonic) * 1000),
                    3,
                )
                return False, "subsystem_cap"
        return True, ""

    async def _execute_job(self, job: JobRecord, worker_index: int) -> None:
        context = self.context_factory(job.job_id)
        context.session_id = job.session_id
        context.task_id = str(job.task_id or "")
        context.task_step_id = str(job.task_step_id or "")
        loop = asyncio.get_running_loop()
        context.progress_callback = lambda payload: loop.call_soon_threadsafe(self._update_progress, job.job_id, payload)
        job.mark_started(worker_index=worker_index, now_monotonic=perf_counter())
        job.status = JobStatus.RUNNING
        self._starting_job_ids.discard(job.job_id)
        self._persist(job)
        self._notify_observer("on_job_started", job)
        self.events.publish(
            event_family="job",
            event_type="job.started",
            severity="info",
            subsystem="job_manager",
            subject=job.job_id,
            visibility_scope="watch_surface",
            retention_class="operator_relevant",
            provenance={"channel": "job_manager", "kind": "direct_system_fact"},
            message=f"Worker {worker_index} started job {job.job_id}.",
            payload=self._job_event_payload(job),
        )
        try:
            while True:
                job.attempt_count += 1
                result = await asyncio.wait_for(
                    self.executor.execute(job.tool_name, job.arguments, context),
                    timeout=job.timeout_seconds,
                )
                job.result = result.to_dict()
                job.error = result.error
                if result.success:
                    job.status = JobStatus.COMPLETED
                    break
                if not self._should_retry(job):
                    job.status = JobStatus.FAILED
                    break
                job.retry_count += 1
                job.retry_last_error = str(result.error or result.summary or "tool_failed")
                self.events.publish(
                    event_family="job",
                    event_type="job.retry_scheduled",
                    severity="warning",
                    subsystem="job_manager",
                    subject=job.job_id,
                    visibility_scope="watch_surface",
                    retention_class="bounded_recent",
                    provenance={"channel": "job_manager", "kind": "direct_system_fact"},
                    message=f"Job {job.job_id} scheduled retry {job.retry_count}.",
                    payload={
                        **self._job_event_payload(job),
                        "completion_claimed": False,
                        "verification_claimed": False,
                    },
                )
                await asyncio.sleep(max(0.0, float(job.retry_backoff_ms or 0.0)) / 1000.0)
        except asyncio.TimeoutError:
            context.cancellation_requested.set()
            job.status = JobStatus.TIMED_OUT
            job.error = f"Job exceeded timeout of {job.timeout_seconds} seconds."
        except asyncio.CancelledError:
            context.cancellation_requested.set()
            job.status = JobStatus.CANCELLED
            job.cancellation_state = CancellationState.CANCELLED_DURING_EXECUTION.value
            job.error = (
                "interrupted_on_shutdown"
                if job.restart_recovery_state == RestartRecoveryState.INTERRUPTED_RUNNING_JOB.value
                else "cancelled_during_execution"
            )
        except Exception as error:
            job.status = JobStatus.FAILED
            job.error = str(error)
        finally:
            self._starting_job_ids.discard(job.job_id)
            job.mark_finished(now_monotonic=perf_counter())
            self._finalize(job)

    def _active_or_starting_jobs(self) -> list[JobRecord]:
        return [
            item
            for item in self._jobs.values()
            if item.status == JobStatus.RUNNING or item.job_id in self._starting_job_ids
        ]

    def _should_retry(self, job: JobRecord) -> bool:
        if job.retry_policy != RetryPolicy.SAFE_READ_RETRY:
            return False
        if job.cancel_requested:
            return False
        return int(job.attempt_count or 0) < max(1, int(job.retry_max_attempts or 1))

    def _finalize(self, job: JobRecord) -> None:
        self._persist(job)
        self._notify_observer("on_job_finished", job)
        self.events.publish(
            event_family="job",
            event_type=f"job.{job.status.value}",
            severity="info" if job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED} else "warning",
            subsystem="job_manager",
            subject=job.job_id,
            visibility_scope="watch_surface",
            retention_class="operator_relevant",
            provenance={"channel": "job_manager", "kind": "direct_system_fact"},
            message=f"Job {job.job_id} finished with status '{job.status.value}'.",
            payload={
                **self._job_event_payload(job),
                "result_summary": str(job.result.get("summary", "")).strip() if isinstance(job.result, dict) else "",
                "error": job.error,
            },
        )
        future = self._completion_futures.pop(job.job_id, None)
        if future is not None and not future.done():
            future.set_result(job)
        self._prune_finished_jobs()

    def _update_progress(self, job_id: str, payload: dict[str, object]) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return
        progress = safe_latency_value(dict(payload))
        job.result = dict(progress) if isinstance(progress, dict) else {"progress": progress}
        self._persist(job)
        self._notify_observer("on_job_progress", job, dict(job.result or {}))
        self.events.publish(
            event_family="job",
            event_type="job.progress",
            severity="debug",
            subsystem="job_manager",
            session_id=job.session_id,
            subject=job.job_id,
            visibility_scope="watch_surface",
            retention_class="bounded_recent",
            provenance={"channel": "job_manager", "kind": "direct_system_fact"},
            message=f"Job {job.job_id} reported progress.",
            payload={
                **self._job_event_payload(job),
                "progress": dict(job.result or {}),
                "completion_claimed": False,
                "verification_claimed": False,
            },
        )

    def update_job_worker_metadata(self, job_id: str, **metadata: object) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        for key in (
            "route_family",
            "subsystem",
            "continuation_id",
            "latency_trace_id",
        ):
            if key in metadata:
                setattr(job, key, str(metadata.get(key) or ""))
        if "priority_lane" in metadata:
            job.priority_lane = coerce_worker_lane(metadata.get("priority_lane"))
            job.worker_lane = job.priority_lane.value
        if "priority_level" in metadata:
            job.priority_level = coerce_worker_priority(metadata.get("priority_level"))
            job.worker_priority = job.priority_level.value
        if "interactive_deadline_ms" in metadata:
            value = metadata.get("interactive_deadline_ms")
            job.interactive_deadline_ms = float(value) if value is not None else None
        if "background_ok" in metadata:
            job.background_ok = bool(metadata.get("background_ok"))
        if "operator_visible" in metadata:
            job.operator_visible = bool(metadata.get("operator_visible"))
        if "can_yield" in metadata:
            job.can_yield = bool(metadata.get("can_yield"))
        if "starvation_sensitive" in metadata:
            job.starvation_sensitive = bool(metadata.get("starvation_sensitive"))
        if "safe_for_verification" in metadata:
            job.safe_for_verification = bool(metadata.get("safe_for_verification"))
        if "max_queue_wait_ms" in metadata or "queue_wait_budget_ms" in metadata:
            value = metadata.get("max_queue_wait_ms", metadata.get("queue_wait_budget_ms"))
            job.queue_wait_budget_ms = float(value) if value is not None else None
        if "subsystem_cap_key" in metadata:
            job.subsystem_cap_key = str(metadata.get("subsystem_cap_key") or "")
        if "subsystem_cap_limit" in metadata:
            value = metadata.get("subsystem_cap_limit")
            job.subsystem_cap_limit = int(value) if value is not None else None
        if "retry_policy" in metadata:
            job.retry_policy = coerce_retry_policy(metadata.get("retry_policy"))
        if "retry_max_attempts" in metadata:
            job.retry_max_attempts = max(1, int(metadata.get("retry_max_attempts") or 1))
        if "retry_backoff_ms" in metadata:
            job.retry_backoff_ms = float(metadata.get("retry_backoff_ms") or 0.0)
        self._persist(job)
        return True

    def worker_status_snapshot(self, *, now_monotonic: float | None = None) -> dict[str, object]:
        now = float(now_monotonic if now_monotonic is not None else perf_counter())
        capacity = max(0, int(self.config.concurrency.max_workers or 0))
        queued = [job for job in self._jobs.values() if job.status == JobStatus.QUEUED]
        active = [job for job in self._jobs.values() if job.status == JobStatus.RUNNING]
        queue_depth_by_lane = _lane_counter(queued)
        active_jobs_by_lane = _lane_counter(active)
        active_subsystem_counts: Counter[str] = Counter()
        queued_subsystem_counts: Counter[str] = Counter()
        for job in active:
            if job.subsystem_cap_key:
                active_subsystem_counts[job.subsystem_cap_key] += 1
        for job in queued:
            if job.subsystem_cap_key:
                queued_subsystem_counts[job.subsystem_cap_key] += 1
        workers_busy = min(capacity, max(len(self._active_tasks), len(active)))
        workers_idle = max(0, capacity - workers_busy)
        oldest_age = 0.0
        if queued:
            oldest_age = max(
                0.0,
                max(
                    (now - (job.queued_at_monotonic or job.created_at_monotonic or now)) * 1000
                    for job in queued
                ),
            )
        interactive_jobs_waiting = queue_depth_by_lane[WorkerLane.INTERACTIVE.value]
        background_jobs_running = active_jobs_by_lane[WorkerLane.BACKGROUND.value]
        background_job_count = (
            queue_depth_by_lane[WorkerLane.BACKGROUND.value]
            + active_jobs_by_lane[WorkerLane.BACKGROUND.value]
        )
        interactive_job_count = (
            queue_depth_by_lane[WorkerLane.INTERACTIVE.value]
            + active_jobs_by_lane[WorkerLane.INTERACTIVE.value]
        )
        saturation = round((workers_busy / capacity) * 100, 3) if capacity else 0.0
        background_limit = self.scheduler_policy.resolved_background_limit(capacity)
        protected_capacity_blocked_jobs = 0
        if active_jobs_by_lane[WorkerLane.BACKGROUND.value] >= background_limit > 0:
            protected_capacity_blocked_jobs = queue_depth_by_lane[WorkerLane.BACKGROUND.value]
        subsystem_cap_blocked_jobs = 0
        for job in queued:
            cap_key = job.subsystem_cap_key
            cap_limit = job.subsystem_cap_limit
            if cap_limit is None:
                cap_limit = self.scheduler_policy.cap_for(cap_key)
            if cap_key and cap_limit is not None and active_subsystem_counts[cap_key] >= cap_limit:
                subsystem_cap_blocked_jobs += 1
        queue_wait_budget_exceeded_jobs = 0
        for job in queued:
            budget = job.queue_wait_budget_ms
            if budget is None:
                continue
            queued_basis = job.queued_at_monotonic or job.created_at_monotonic or now
            if max(0.0, (now - queued_basis) * 1000) > budget:
                queue_wait_budget_exceeded_jobs += 1
                job.queue_wait_budget_exceeded = True
        starvation_state = WorkerStarvationState.NO_STARVATION
        if interactive_jobs_waiting and background_jobs_running:
            starvation_state = WorkerStarvationState.BACKGROUND_PRESSURE
        elif interactive_jobs_waiting and workers_busy >= capacity and capacity > 0:
            starvation_state = WorkerStarvationState.INTERACTIVE_WAITING
        elif workers_busy >= capacity and queued and capacity > 0:
            starvation_state = WorkerStarvationState.SATURATED
        elif len(queued) > max(capacity * 2, self.config.concurrency.queue_size // 2):
            starvation_state = WorkerStarvationState.QUEUE_BACKLOG
        pressure_reasons: list[str] = []
        pressure_state = SchedulerPressureState.NOMINAL
        if queue_wait_budget_exceeded_jobs:
            pressure_state = SchedulerPressureState.QUEUE_WAIT_BUDGET_EXCEEDED
            pressure_reasons.append("queue_wait_budget_exceeded")
        elif subsystem_cap_blocked_jobs:
            pressure_state = SchedulerPressureState.SUBSYSTEM_CAP_PRESSURE
            pressure_reasons.append("subsystem_cap")
        elif starvation_state == WorkerStarvationState.BACKGROUND_PRESSURE:
            pressure_state = SchedulerPressureState.BACKGROUND_PRESSURE
            pressure_reasons.append("background_pressure")
        elif starvation_state == WorkerStarvationState.INTERACTIVE_WAITING:
            pressure_state = SchedulerPressureState.INTERACTIVE_WAITING
            pressure_reasons.append("interactive_waiting")
        elif starvation_state == WorkerStarvationState.SATURATED:
            pressure_state = SchedulerPressureState.SATURATED
            pressure_reasons.append("saturated")
        elif protected_capacity_blocked_jobs:
            pressure_state = SchedulerPressureState.BACKGROUND_THROTTLED
            pressure_reasons.append("protected_interactive_capacity")
        elif starvation_state == WorkerStarvationState.QUEUE_BACKLOG:
            pressure_state = SchedulerPressureState.QUEUE_BACKLOG
            pressure_reasons.append("queue_backlog")
        elif active:
            pressure_state = SchedulerPressureState.BUSY
            pressure_reasons.append("busy")
        return {
            "scheduler_strategy": self.scheduler_policy.scheduler_strategy,
            "scheduler_pressure_state": pressure_state.value,
            "scheduler_pressure_reasons": pressure_reasons,
            "protected_interactive_capacity": int(self.scheduler_policy.protected_interactive_capacity or 0),
            "background_capacity_limit": background_limit,
            "worker_capacity": capacity,
            "workers_busy": workers_busy,
            "workers_idle": workers_idle,
            "active_jobs": len(active),
            "queued_jobs": len(queued),
            "queue_depth": len(queued),
            "queue_depth_by_lane": dict(queue_depth_by_lane),
            "active_jobs_by_lane": dict(active_jobs_by_lane),
            "active_subsystem_counts": dict(active_subsystem_counts),
            "queued_subsystem_counts": dict(queued_subsystem_counts),
            "protected_capacity_blocked_jobs": protected_capacity_blocked_jobs,
            "subsystem_cap_blocked_jobs": subsystem_cap_blocked_jobs,
            "queue_wait_budget_exceeded_jobs": queue_wait_budget_exceeded_jobs,
            "oldest_queued_job_age_ms": round(oldest_age, 3),
            "worker_saturation_percent": saturation,
            "interactive_jobs_waiting": interactive_jobs_waiting,
            "background_jobs_running": background_jobs_running,
            "background_job_count": background_job_count,
            "interactive_job_count": interactive_job_count,
            "starvation_detected": starvation_state != WorkerStarvationState.NO_STARVATION,
            "starvation_state": starvation_state.value,
            "retry_waiting_jobs": sum(1 for job in active if job.retry_count > 0),
            "cancellation_requested_jobs": sum(1 for job in self._jobs.values() if job.cancel_requested),
        }

    def _job_event_payload(self, job: JobRecord) -> dict[str, object]:
        status = self.worker_status_snapshot()
        return safe_latency_value(
            {
                "job_id": job.job_id,
                "tool_name": job.tool_name,
                "status": job.status.value,
                "task_id": job.task_id,
                "task_step_id": job.task_step_id,
                **job.worker_metadata(),
                **job.timing_summary(),
                "worker_index": job.worker_index,
                "worker_lane": job.worker_lane or job.priority_lane.value,
                "worker_priority": job.worker_priority or job.priority_level.value,
                "worker_capacity": status.get("worker_capacity"),
                "workers_busy": status.get("workers_busy"),
                "workers_idle": status.get("workers_idle"),
                "queue_depth": status.get("queue_depth"),
                "worker_saturation_percent": status.get("worker_saturation_percent"),
                "scheduler_strategy": status.get("scheduler_strategy"),
                "scheduler_pressure_state": status.get("scheduler_pressure_state"),
                "scheduler_pressure_reasons": status.get("scheduler_pressure_reasons"),
                "protected_interactive_capacity": status.get("protected_interactive_capacity"),
                "background_capacity_limit": status.get("background_capacity_limit"),
                "protected_capacity_blocked_jobs": status.get("protected_capacity_blocked_jobs"),
                "subsystem_cap_blocked_jobs": status.get("subsystem_cap_blocked_jobs"),
                "queue_wait_budget_exceeded_jobs": status.get("queue_wait_budget_exceeded_jobs"),
                "interactive_jobs_waiting": status.get("interactive_jobs_waiting"),
                "background_jobs_running": status.get("background_jobs_running"),
                "starvation_detected": status.get("starvation_detected"),
                "starvation_state": status.get("starvation_state"),
            }
        )

    def _persist(self, job: JobRecord) -> None:
        self.tool_runs.upsert_run(
            job_id=job.job_id,
            tool_name=job.tool_name,
            status=job.status.value,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            input_payload=job.arguments,
            result_payload=job.result,
            error_text=job.error,
        )

    def _prune_finished_jobs(self) -> None:
        retention_limit = max(self.config.concurrency.history_limit, self.config.concurrency.queue_size)
        finished_jobs = [
            job
            for job in self._jobs.values()
            if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}
        ]
        if len(finished_jobs) <= retention_limit:
            return
        removable = sorted(finished_jobs, key=lambda item: item.finished_at or item.created_at)
        for job in removable[: len(finished_jobs) - retention_limit]:
            self._jobs.pop(job.job_id, None)

    def _notify_observer(self, method_name: str, *args: object) -> None:
        if self.observer is None:
            return
        callback = getattr(self.observer, method_name, None)
        if not callable(callback):
            return
        try:
            callback(*args)
        except Exception:
            return
