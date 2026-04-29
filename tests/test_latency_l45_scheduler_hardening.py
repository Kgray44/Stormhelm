from __future__ import annotations

import asyncio
from collections import Counter

from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.jobs.models import JobStatus
from stormhelm.core.latency import build_latency_trace
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import NotesRepository
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.core.memory.repositories import ToolRunRepository
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import BaseTool
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.core.worker_utilization import RetryPolicy
from stormhelm.core.worker_utilization import SchedulerPressureState
from stormhelm.core.worker_utilization import WorkerLane
from stormhelm.core.worker_utilization import WorkerPriorityLevel
from stormhelm.shared.result import ExecutionMode
from stormhelm.shared.result import ToolResult


class ControlledTool(BaseTool):
    name = "echo"
    display_name = "Controlled"
    description = "Scheduler hardening test tool."
    execution_mode = ExecutionMode.ASYNC

    started_by_job: list[str] = []
    attempt_count_by_job: Counter[str] = Counter()

    @classmethod
    def reset(cls) -> None:
        cls.started_by_job.clear()
        cls.attempt_count_by_job.clear()

    async def execute_async(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        self.__class__.started_by_job.append(context.job_id)
        self.__class__.attempt_count_by_job[context.job_id] += 1
        await asyncio.sleep(float(arguments.get("delay", 0.02)))
        fail_attempts = int(arguments.get("fail_attempts", 0) or 0)
        if self.__class__.attempt_count_by_job[context.job_id] <= fail_attempts:
            return ToolResult(success=False, summary="Transient test failure.", error="transient_failure")
        return ToolResult(
            success=True,
            summary="Completed controlled tool.",
            data={"attempts": self.__class__.attempt_count_by_job[context.job_id]},
        )


def _job_manager(temp_config, *, max_workers: int = 2) -> tuple[JobManager, ToolExecutor, EventBuffer]:
    temp_config.concurrency.max_workers = max_workers
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    registry = ToolRegistry()
    ControlledTool.reset()
    registry.register(ControlledTool())
    executor = ToolExecutor(registry)
    events = EventBuffer()
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    tool_runs = ToolRunRepository(database)
    safety = SafetyPolicy(temp_config)
    manager = JobManager(
        config=temp_config,
        executor=executor,
        context_factory=lambda job_id: ToolContext(
            job_id=job_id,
            config=temp_config,
            events=events,
            notes=notes,
            preferences=preferences,
            safety_policy=safety,
        ),
        tool_runs=tool_runs,
        events=events,
    )
    return manager, executor, events


def test_l45_background_jobs_do_not_consume_protected_interactive_capacity(temp_config) -> None:
    async def scenario() -> None:
        manager, executor, events = _job_manager(temp_config, max_workers=2)
        background_a = await manager.submit(
            "echo",
            {"delay": 0.08},
            session_id="l45-capacity",
            priority_lane=WorkerLane.BACKGROUND,
            priority_level=WorkerPriorityLevel.MAINTENANCE,
            route_family="background_preparation",
            subsystem="software_catalog",
            background_ok=True,
            can_yield=True,
        )
        background_b = await manager.submit(
            "echo",
            {"delay": 0.08},
            session_id="l45-capacity",
            priority_lane=WorkerLane.BACKGROUND,
            priority_level=WorkerPriorityLevel.MAINTENANCE,
            route_family="background_preparation",
            subsystem="provider_readiness",
            background_ok=True,
            can_yield=True,
        )
        await manager.start()
        try:
            await asyncio.sleep(0.03)
            while len(ControlledTool.started_by_job) < 1:
                await asyncio.sleep(0.005)
            protected_snapshot = manager.worker_status_snapshot()
            interactive = await manager.submit(
                "echo",
                {"delay": 0.01},
                session_id="l45-capacity",
                priority_lane=WorkerLane.INTERACTIVE,
                priority_level=WorkerPriorityLevel.CRITICAL_INTERACTIVE,
                route_family="voice_control",
                subsystem="voice",
                interactive_deadline_ms=250,
                starvation_sensitive=True,
            )
            finished_interactive = await manager.wait(interactive.job_id)
            finished_a = await manager.wait(background_a.job_id)
            finished_b = await manager.wait(background_b.job_id)
        finally:
            await manager.stop()
            executor.shutdown()

        started_events = [
            event.to_dict()
            for event in events.replay(cursor=0, session_id="l45-capacity").events
            if event.event_type == "job.started"
        ]
        started_lanes = [event["payload"]["priority_lane"] for event in started_events[:3]]

        assert protected_snapshot["protected_interactive_capacity"] >= 1
        assert protected_snapshot["background_jobs_running"] == 1
        assert protected_snapshot["queued_jobs"] >= 1
        assert protected_snapshot["scheduler_pressure_state"] in {"nominal", "background_throttled"}
        assert finished_interactive.status == JobStatus.COMPLETED
        assert finished_a.status == JobStatus.COMPLETED
        assert finished_b.status == JobStatus.COMPLETED
        assert started_lanes[:2] == ["background", "interactive"]

    asyncio.run(scenario())


def test_l45_per_subsystem_cap_keeps_duplicate_slow_stage_queued(temp_config) -> None:
    async def scenario() -> None:
        manager, executor, _ = _job_manager(temp_config, max_workers=2)
        verify_a = await manager.submit(
            "echo",
            {"delay": 0.08},
            session_id="l45-subsystem-cap",
            priority_lane=WorkerLane.NORMAL,
            priority_level=WorkerPriorityLevel.NORMAL,
            route_family="software_control",
            subsystem="software_control.verify_operation",
        )
        verify_b = await manager.submit(
            "echo",
            {"delay": 0.08},
            session_id="l45-subsystem-cap",
            priority_lane=WorkerLane.NORMAL,
            priority_level=WorkerPriorityLevel.NORMAL,
            route_family="software_control",
            subsystem="software_control.verify_operation",
        )
        await manager.start()
        try:
            while len(ControlledTool.started_by_job) < 1:
                await asyncio.sleep(0.005)
            capped_snapshot = manager.worker_status_snapshot()
            finished_a = await manager.wait(verify_a.job_id)
            finished_b = await manager.wait(verify_b.job_id)
        finally:
            await manager.stop()
            executor.shutdown()

        assert capped_snapshot["active_subsystem_counts"]["software_control.verify_operation"] == 1
        assert capped_snapshot["subsystem_cap_blocked_jobs"] >= 1
        assert capped_snapshot["scheduler_pressure_state"] == SchedulerPressureState.SUBSYSTEM_CAP_PRESSURE.value
        assert finished_a.subsystem_cap_key == "software_control.verify_operation"
        assert finished_b.subsystem_cap_key == "software_control.verify_operation"
        assert finished_b.subsystem_cap_wait_ms > 0
        assert finished_a.status == JobStatus.COMPLETED
        assert finished_b.status == JobStatus.COMPLETED

    asyncio.run(scenario())


def test_l45_queue_wait_budget_and_pressure_fields_are_reported(temp_config) -> None:
    async def scenario() -> None:
        manager, executor, _ = _job_manager(temp_config, max_workers=1)
        await manager.start()
        try:
            running = await manager.submit(
                "echo",
                {"delay": 0.12},
                session_id="l45-pressure",
                priority_lane=WorkerLane.NORMAL,
                priority_level=WorkerPriorityLevel.NORMAL,
                route_family="workflow",
                subsystem="workflow",
            )
            while running.status != JobStatus.RUNNING:
                await asyncio.sleep(0.005)
            waiting = await manager.submit(
                "echo",
                {"delay": 0.01},
                session_id="l45-pressure",
                priority_lane=WorkerLane.INTERACTIVE,
                priority_level=WorkerPriorityLevel.CRITICAL_INTERACTIVE,
                route_family="voice_control",
                subsystem="voice",
                interactive_deadline_ms=250,
                starvation_sensitive=True,
                max_queue_wait_ms=1.0,
            )
            await asyncio.sleep(0.03)
            pressure_snapshot = manager.worker_status_snapshot()
            finished_waiting = await manager.wait(waiting.job_id)
            finished_running = await manager.wait(running.job_id)
        finally:
            await manager.stop()
            executor.shutdown()

        assert pressure_snapshot["queue_wait_budget_exceeded_jobs"] >= 1
        assert pressure_snapshot["scheduler_pressure_state"] in {
            SchedulerPressureState.INTERACTIVE_WAITING.value,
            SchedulerPressureState.QUEUE_WAIT_BUDGET_EXCEEDED.value,
        }
        assert finished_waiting.queue_wait_budget_ms == 1.0
        assert finished_waiting.queue_wait_budget_exceeded is True
        assert finished_running.status == JobStatus.COMPLETED
        assert finished_waiting.status == JobStatus.COMPLETED

    asyncio.run(scenario())


def test_l45_safe_retry_policy_retries_without_touching_no_retry_jobs(temp_config) -> None:
    async def scenario() -> None:
        manager, executor, _ = _job_manager(temp_config, max_workers=1)
        await manager.start()
        try:
            retryable = await manager.submit(
                "echo",
                {"delay": 0.01, "fail_attempts": 1},
                session_id="l45-retry",
                priority_lane=WorkerLane.NORMAL,
                priority_level=WorkerPriorityLevel.NORMAL,
                route_family="network",
                subsystem="network.run_live_diagnosis",
                retry_policy=RetryPolicy.SAFE_READ_RETRY,
                retry_max_attempts=2,
                retry_backoff_ms=1,
            )
            no_retry = await manager.submit(
                "echo",
                {"delay": 0.01, "fail_attempts": 1},
                session_id="l45-retry",
                priority_lane=WorkerLane.NORMAL,
                priority_level=WorkerPriorityLevel.NORMAL,
                route_family="discord_relay",
                subsystem="discord_relay.dispatch_approved_preview",
                retry_policy=RetryPolicy.NO_RETRY,
            )
            finished_retryable = await manager.wait(retryable.job_id)
            finished_no_retry = await manager.wait(no_retry.job_id)
        finally:
            await manager.stop()
            executor.shutdown()

        assert finished_retryable.status == JobStatus.COMPLETED
        assert finished_retryable.retry_count == 1
        assert finished_retryable.retry_policy == RetryPolicy.SAFE_READ_RETRY
        assert finished_no_retry.status == JobStatus.FAILED
        assert finished_no_retry.retry_count == 0
        assert finished_no_retry.retry_policy == RetryPolicy.NO_RETRY

    asyncio.run(scenario())


def test_l45_cancellation_and_shutdown_truth_states_are_serialized(temp_config) -> None:
    async def scenario() -> None:
        manager, executor, _ = _job_manager(temp_config, max_workers=1)
        blocker = await manager.submit(
            "echo",
            {"delay": 0.12},
            session_id="l45-cancel",
            priority_lane=WorkerLane.NORMAL,
            priority_level=WorkerPriorityLevel.NORMAL,
            route_family="workflow",
            subsystem="workflow",
        )
        queued = await manager.submit(
            "echo",
            {"delay": 0.01},
            session_id="l45-cancel",
            priority_lane=WorkerLane.NORMAL,
            priority_level=WorkerPriorityLevel.NORMAL,
            route_family="workflow",
            subsystem="workflow",
        )
        assert manager.cancel(queued.job_id) is True
        cancelled = await manager.wait(queued.job_id)
        await manager.start()
        try:
            while blocker.status != JobStatus.RUNNING:
                await asyncio.sleep(0.005)
            await manager.stop()
        finally:
            executor.shutdown()

        cancelled_payload = cancelled.to_dict()
        interrupted_payload = blocker.to_dict()
        assert cancelled_payload["status"] == "cancelled"
        assert cancelled_payload["cancel_requested"] is True
        assert cancelled_payload["cancellation_state"] == "cancelled_before_start"
        assert interrupted_payload["status"] == "cancelled"
        assert interrupted_payload["restart_recovery_state"] == "interrupted_running_job"
        assert interrupted_payload["completion_claimed"] is False
        assert interrupted_payload["verification_claimed"] is False

    asyncio.run(scenario())


def test_l45_latency_trace_and_kraken_rows_include_scheduler_hardening_fields() -> None:
    trace = build_latency_trace(
        metadata={
            "route_family": "workflow",
            "worker_lane": "normal",
            "worker_priority": "normal",
            "scheduler_strategy": "priority_lane_with_caps",
            "scheduler_pressure_state": "queue_wait_budget_exceeded",
            "scheduler_pressure_reasons": ["interactive_waiting"],
            "protected_interactive_capacity": 1,
            "background_capacity_limit": 1,
            "subsystem_cap_key": "software_control.verify_operation",
            "subsystem_cap_limit": 1,
            "subsystem_cap_wait_ms": 14.0,
            "queue_wait_budget_ms": 10.0,
            "queue_wait_budget_exceeded": True,
            "retry_policy": "safe_read_retry",
            "retry_count": 1,
            "retry_backoff_ms": 25.0,
            "cancellation_state": "not_requested",
            "yield_state": "not_requested",
            "restart_recovery_state": "not_interrupted",
        },
        stage_timings_ms={"queue_wait_ms": 15.0, "job_run_ms": 30.0, "job_total_ms": 45.0},
    )

    summary = trace.to_summary_dict()
    case = CommandEvalCase(
        case_id="l45-row",
        message="run verification",
        expected=ExpectedBehavior(route_family="workflow", subsystem="workflow"),
    )
    result = CommandEvalResult(
        case=case,
        observation=CoreObservation(
            case_id=case.case_id,
            input_boundary="POST /chat/send",
            latency_ms=100.0,
            ui_response="Queued verification.",
            actual_route_family="workflow",
            actual_subsystem="workflow",
            result_state="queued",
            latency_summary=summary,
        ),
        assertions={},
    )
    row = result.to_dict()
    kraken = build_checkpoint_summary([result])["kraken_latency_report"]

    assert summary["scheduler_strategy"] == "priority_lane_with_caps"
    assert summary["queue_wait_budget_exceeded"] is True
    assert summary["retry_policy"] == "safe_read_retry"
    assert row["scheduler_pressure_state"] == "queue_wait_budget_exceeded"
    assert row["subsystem_cap_key"] == "software_control.verify_operation"
    assert row["retry_count"] == 1
    assert kraken["scheduler_strategy_counts"]["priority_lane_with_caps"] == 1
    assert kraken["queue_wait_budget_exceeded_count"] == 1
    assert kraken["subsystem_cap_wait_ms"]["p95"] == 14.0
    assert kraken["retry_policy_counts"]["safe_read_retry"] == 1
