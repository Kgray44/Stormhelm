from __future__ import annotations

import asyncio

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
from stormhelm.core.worker_utilization import WorkerLane
from stormhelm.core.worker_utilization import WorkerPriorityLevel
from stormhelm.core.worker_utilization import classify_worker_route_policy
from stormhelm.shared.result import ExecutionMode
from stormhelm.shared.result import ToolResult


class ProgressTool(BaseTool):
    name = "echo"
    display_name = "Worker Progress"
    description = "Async worker utilization test tool."
    execution_mode = ExecutionMode.ASYNC

    async def execute_async(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        context.report_progress(
            {
                "stage": "running",
                "progress_percent": 25,
                "summary": "Worker progress checkpoint.",
                "api_key": "sk-should-not-leak",
                "authorization": "Bearer should-not-leak",
                "raw_audio": b"not audio",
            }
        )
        await asyncio.sleep(float(arguments.get("delay", 0.02)))
        return ToolResult(success=True, summary="Worker progress complete.")


def _job_manager(temp_config, *, max_workers: int = 1) -> tuple[JobManager, ToolExecutor, EventBuffer]:
    temp_config.concurrency.max_workers = max_workers
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    registry = ToolRegistry()
    registry.register(ProgressTool())
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


def test_worker_metadata_timing_status_and_progress_events_are_visible_and_redacted(temp_config) -> None:
    async def scenario() -> None:
        manager, executor, events = _job_manager(temp_config, max_workers=1)
        await manager.start()
        try:
            background = await manager.submit(
                "echo",
                {"delay": 0.08},
                session_id="l41-workers",
                priority_lane=WorkerLane.BACKGROUND,
                priority_level=WorkerPriorityLevel.MAINTENANCE,
                route_family="background_preparation",
                subsystem="provider_readiness",
                continuation_id="route-cont-bg",
                latency_trace_id="latency-bg",
                background_ok=True,
                operator_visible=False,
                can_yield=True,
            )
            await asyncio.sleep(0.02)
            interactive = await manager.submit(
                "echo",
                {"delay": 0.01},
                session_id="l41-workers",
                priority_lane=WorkerLane.INTERACTIVE,
                priority_level=WorkerPriorityLevel.CRITICAL_INTERACTIVE,
                route_family="voice_control",
                subsystem="voice",
                interactive_deadline_ms=250,
                starvation_sensitive=True,
            )
            busy_snapshot = manager.worker_status_snapshot()
            finished_background = await manager.wait(background.job_id)
            finished_interactive = await manager.wait(interactive.job_id)
        finally:
            await manager.stop()
            executor.shutdown()

        progress_events = [
            event.to_dict()
            for event in events.replay(cursor=0, session_id="l41-workers").events
            if event.event_type == "job.progress"
        ]

        assert background.to_dict()["priority_lane"] == "background"
        assert background.to_dict()["priority_level"] == "maintenance"
        assert background.to_dict()["route_family"] == "background_preparation"
        assert background.to_dict()["subsystem"] == "provider_readiness"
        assert background.to_dict()["continuation_id"] == "route-cont-bg"
        assert background.to_dict()["latency_trace_id"] == "latency-bg"
        assert finished_background.status == JobStatus.COMPLETED
        assert finished_background.worker_index == 1
        assert finished_background.queue_wait_ms >= 0
        assert finished_background.job_run_ms > 0
        assert finished_background.job_total_ms >= finished_background.job_run_ms
        assert finished_interactive.priority_lane.value == "interactive"
        assert busy_snapshot["worker_capacity"] == 1
        assert busy_snapshot["workers_busy"] == 1
        assert busy_snapshot["queue_depth"] >= 1
        assert busy_snapshot["queue_depth_by_lane"]["interactive"] >= 1
        assert busy_snapshot["active_jobs_by_lane"]["background"] >= 1
        assert busy_snapshot["interactive_jobs_waiting"] >= 1
        assert busy_snapshot["background_jobs_running"] >= 1
        assert busy_snapshot["starvation_detected"] is True
        assert busy_snapshot["starvation_state"] in {"interactive_waiting", "background_pressure", "saturated"}
        assert progress_events
        payload = progress_events[0]["payload"]
        assert payload["priority_lane"] == "background"
        assert payload["priority_level"] == "maintenance"
        assert payload["queue_wait_ms"] >= 0
        assert "worker_index" in payload
        assert payload["completion_claimed"] is False
        assert payload["verification_claimed"] is False
        assert payload["progress"]["api_key"] == "<redacted>"
        assert payload["progress"]["authorization"] == "<redacted>"
        assert payload["progress"]["raw_audio"] == "<redacted>"

    asyncio.run(scenario())


def test_background_refresh_hook_uses_background_lane_without_verification_authority(temp_config) -> None:
    async def scenario() -> None:
        manager, executor, _ = _job_manager(temp_config, max_workers=1)
        await manager.start()
        try:
            job = await manager.submit_background_refresh(
                "echo",
                {"delay": 0.01},
                session_id="l41-background",
                subsystem="provider_readiness",
                route_family="route_family_status",
            )
            finished = await manager.wait(job.job_id)
        finally:
            await manager.stop()
            executor.shutdown()

        payload = finished.to_dict()
        assert payload["priority_lane"] == "background"
        assert payload["priority_level"] == "maintenance"
        assert payload["background_ok"] is True
        assert payload["operator_visible"] is False
        assert payload["safe_for_verification"] is False
        assert payload["status"] == "completed"

    asyncio.run(scenario())


def test_inline_fast_path_policy_keeps_tiny_truth_off_the_worker_queue() -> None:
    inline_cases = [
        ("calculations", "calculate"),
        ("trust_approvals", "confirm"),
        ("voice_control", "stop_speaking"),
        ("browser_destination", "direct_url"),
    ]

    for route_family, request_kind in inline_cases:
        policy = classify_worker_route_policy(route_family=route_family, request_kind=request_kind)
        assert policy.use_worker is False
        assert policy.priority_lane == WorkerLane.INTERACTIVE
        assert policy.inline_reason

    worker_policy = classify_worker_route_policy(
        route_family="software_control",
        request_kind="execute_approved",
        execution_mode="async_first",
    )
    assert worker_policy.use_worker is True
    assert worker_policy.priority_lane == WorkerLane.NORMAL
    assert worker_policy.priority_level == WorkerPriorityLevel.NORMAL


def test_interactive_jobs_start_before_background_jobs_when_both_are_queued(temp_config) -> None:
    async def scenario() -> None:
        manager, executor, events = _job_manager(temp_config, max_workers=1)
        background = await manager.submit(
            "echo",
            {"delay": 0.01},
            session_id="l41-priority",
            priority_lane=WorkerLane.BACKGROUND,
            priority_level=WorkerPriorityLevel.MAINTENANCE,
            route_family="background_preparation",
            subsystem="software_catalog",
            background_ok=True,
            operator_visible=False,
            can_yield=True,
        )
        interactive = await manager.submit(
            "echo",
            {"delay": 0.01},
            session_id="l41-priority",
            priority_lane=WorkerLane.INTERACTIVE,
            priority_level=WorkerPriorityLevel.CRITICAL_INTERACTIVE,
            route_family="voice_control",
            subsystem="voice",
            interactive_deadline_ms=250,
            starvation_sensitive=True,
        )
        await manager.start()
        try:
            finished_interactive = await manager.wait(interactive.job_id)
            finished_background = await manager.wait(background.job_id)
        finally:
            await manager.stop()
            executor.shutdown()

        started_events = [
            event.to_dict()
            for event in events.replay(cursor=0, session_id="l41-priority").events
            if event.event_type == "job.started"
        ]

        assert finished_interactive.status == JobStatus.COMPLETED
        assert finished_background.status == JobStatus.COMPLETED
        assert started_events[0]["payload"]["job_id"] == interactive.job_id
        assert started_events[0]["payload"]["priority_lane"] == "interactive"
        assert started_events[1]["payload"]["job_id"] == background.job_id
        assert started_events[1]["payload"]["priority_lane"] == "background"

    asyncio.run(scenario())


def test_latency_trace_carries_worker_utilization_fields() -> None:
    trace = build_latency_trace(
        metadata={
            "route_family": "workflow",
            "worker_lane": "normal",
            "worker_priority": "normal",
            "queue_depth_at_submit": 3,
            "workers_busy_at_submit": 2,
            "workers_idle_at_submit": 6,
            "worker_saturation_percent": 25.0,
            "interactive_jobs_waiting": 1,
            "background_jobs_running": 1,
            "starvation_detected": True,
            "worker_capacity": 8,
            "async_worker_utilization_summary": {
                "queue_depth": 3,
                "api_key": "secret",
            },
        },
        stage_timings_ms={
            "queue_wait_ms": 12.0,
            "job_start_delay_ms": 12.0,
            "job_run_ms": 40.0,
            "job_total_ms": 52.0,
        },
    )

    summary = trace.to_summary_dict()

    assert summary["worker_lane"] == "normal"
    assert summary["worker_priority"] == "normal"
    assert summary["queue_depth_at_submit"] == 3
    assert summary["queue_wait_ms"] == 12.0
    assert summary["job_run_ms"] == 40.0
    assert summary["job_total_ms"] == 52.0
    assert summary["interactive_jobs_waiting"] == 1
    assert summary["background_jobs_running"] == 1
    assert summary["starvation_detected"] is True
    assert summary["async_worker_utilization_summary"]["api_key"] == "<redacted>"


def test_kraken_worker_report_includes_queue_and_lane_aggregates() -> None:
    case = CommandEvalCase(
        case_id="l41-worker-row",
        message="run a workflow",
        expected=ExpectedBehavior(route_family="workflow", subsystem="workflow"),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=250.0,
        ui_response="Queued workflow progress.",
        actual_route_family="workflow",
        actual_subsystem="workflow",
        result_state="queued",
        latency_summary={
            "execution_mode": "async_first",
            "async_strategy": "create_job",
            "worker_lane": "normal",
            "worker_priority": "normal",
            "queue_depth_at_submit": 2,
            "queue_wait_ms": 15.0,
            "job_start_delay_ms": 15.0,
            "job_run_ms": 50.0,
            "job_total_ms": 65.0,
            "worker_index": 1,
            "worker_capacity": 8,
            "workers_busy_at_submit": 2,
            "workers_idle_at_submit": 6,
            "worker_saturation_percent": 25.0,
            "starvation_detected": False,
            "interactive_jobs_waiting": 0,
            "background_jobs_running": 1,
            "background_job_count": 1,
            "interactive_job_count": 0,
        },
    )
    result = CommandEvalResult(case=case, observation=observation, assertions={})

    row = result.to_dict()
    report = build_checkpoint_summary([result])["kraken_latency_report"]

    assert row["worker_lane"] == "normal"
    assert row["worker_priority"] == "normal"
    assert row["queue_wait_ms"] == 15.0
    assert row["job_run_ms"] == 50.0
    assert report["queue_wait_ms"]["p95"] == 15.0
    assert report["job_run_ms"]["p95"] == 50.0
    assert report["job_total_ms"]["p95"] == 65.0
    assert report["worker_lane_counts"]["normal"] == 1
    assert report["async_strategy_by_worker_lane"]["create_job"]["normal"]["count"] == 1
