from __future__ import annotations

import asyncio
from typing import Callable
from uuid import uuid4

from stormhelm.config.models import AppConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.models import JobRecord, JobStatus
from stormhelm.core.memory.repositories import ToolRunRepository
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.shared.time import utc_now_iso


ToolContextFactory = Callable[[str], ToolContext]


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
        self._queue: asyncio.Queue[JobRecord] = asyncio.Queue(maxsize=config.concurrency.queue_size)
        self._workers: list[asyncio.Task[None]] = []
        self._completion_futures: dict[str, asyncio.Future[JobRecord]] = {}
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._jobs: dict[str, JobRecord] = {}

    async def start(self) -> None:
        if self._workers:
            return
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
        for job in self._jobs.values():
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.finished_at = utc_now_iso()
                job.error = "cancelled_on_shutdown"
                self._finalize(job)

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

    async def submit(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        timeout_seconds: float | None = None,
        task_id: str | None = None,
        task_step_id: str | None = None,
    ) -> JobRecord:
        timeout = timeout_seconds or self.config.concurrency.default_job_timeout_seconds
        job = JobRecord.queued(
            str(uuid4()),
            tool_name,
            dict(arguments),
            timeout,
            task_id=task_id,
            task_step_id=task_step_id,
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
            payload={"job_id": job.job_id, "tool_name": tool_name, "status": job.status.value},
        )
        loop = asyncio.get_running_loop()
        self._completion_futures[job.job_id] = loop.create_future()
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull as error:
            job.status = JobStatus.FAILED
            job.finished_at = utc_now_iso()
            job.error = "job_queue_full"
            self._finalize(job)
            raise RuntimeError("Stormhelm job queue is full.") from error
        return job

    async def submit_and_wait(
        self,
        tool_name: str,
        arguments: dict[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> JobRecord:
        job = await self.submit(tool_name, arguments, timeout_seconds=timeout_seconds)
        return await self.wait(job.job_id)

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
        active_task = self._active_tasks.get(job_id)
        if active_task is not None:
            active_task.cancel()
            return True

        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.CANCELLED
            job.finished_at = utc_now_iso()
            job.error = "cancelled_before_start"
            self._finalize(job)
            return True
        return False

    def list_jobs(self, limit: int = 100) -> list[dict[str, object]]:
        jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
        return [job.to_dict() for job in jobs[:limit]]

    async def _worker_loop(self, worker_index: int) -> None:
        while True:
            job = await self._queue.get()
            try:
                if job.status == JobStatus.CANCELLED:
                    continue
                task = asyncio.create_task(self._execute_job(job, worker_index))
                self._active_tasks[job.job_id] = task
                await task
            finally:
                self._active_tasks.pop(job.job_id, None)
                self._queue.task_done()

    async def _execute_job(self, job: JobRecord, worker_index: int) -> None:
        context = self.context_factory(job.job_id)
        loop = asyncio.get_running_loop()
        context.progress_callback = lambda payload: loop.call_soon_threadsafe(self._update_progress, job.job_id, payload)
        job.started_at = utc_now_iso()
        job.status = JobStatus.RUNNING
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
            payload={"job_id": job.job_id, "tool_name": job.tool_name, "worker_index": worker_index, "status": job.status.value},
        )
        try:
            result = await asyncio.wait_for(
                self.executor.execute(job.tool_name, job.arguments, context),
                timeout=job.timeout_seconds,
            )
            job.status = JobStatus.COMPLETED if result.success else JobStatus.FAILED
            job.result = result.to_dict()
            job.error = result.error
        except asyncio.TimeoutError:
            context.cancellation_requested.set()
            job.status = JobStatus.TIMED_OUT
            job.error = f"Job exceeded timeout of {job.timeout_seconds} seconds."
        except asyncio.CancelledError:
            context.cancellation_requested.set()
            job.status = JobStatus.CANCELLED
            job.error = "cancelled_during_execution"
        except Exception as error:
            job.status = JobStatus.FAILED
            job.error = str(error)
        finally:
            job.finished_at = utc_now_iso()
            self._finalize(job)

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
                "job_id": job.job_id,
                "status": job.status.value,
                "tool_name": job.tool_name,
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
        job.result = dict(payload)
        self._persist(job)
        self._notify_observer("on_job_progress", job, dict(payload))

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
