from __future__ import annotations

import asyncio
from time import perf_counter

from stormhelm.core.async_routes import AsyncRouteStrategy
from stormhelm.core.async_routes import RouteProgressStage
from stormhelm.core.async_routes import RouteProgressState
from stormhelm.core.async_routes import classify_async_route_policy
from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.jobs.models import JobStatus
from stormhelm.core.latency import build_latency_trace
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import NotesRepository
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.core.memory.repositories import ToolRunRepository
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import BaseTool
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.shared.result import ExecutionMode
from stormhelm.shared.result import ToolResult

from test_assistant_orchestrator import FakeSystemProbe
from test_assistant_orchestrator import _build_assistant_with_workspace


class SlowProgressTool(BaseTool):
    name = "echo"
    display_name = "Slow Progress"
    description = "Async progress test tool."
    execution_mode = ExecutionMode.ASYNC

    async def execute_async(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        context.report_progress(
            {
                "stage": "running",
                "progress_percent": 40,
                "summary": "Halfway through the slow test.",
                "authorization": "Bearer should-not-leak",
                "raw_audio": b"not audio",
            }
        )
        await asyncio.sleep(float(arguments.get("delay", 0.05)))
        return ToolResult(
            success=True,
            summary="Slow progress complete.",
            data={"progress_percent": 100},
        )


def _job_manager_for_tool(temp_config, tool: BaseTool) -> tuple[JobManager, ToolExecutor, EventBuffer]:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    registry = ToolRegistry()
    registry.register(tool)
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


def test_async_route_policy_marks_async_first_routes_as_job_and_task_continuations() -> None:
    decision = classify_async_route_policy(
        route_family="software_control",
        subsystem="software_control",
        execution_mode="async_first",
        budget_label="long_task",
        request_stage="execute_approved",
        trust_posture="approved",
        verification_posture="verification_required",
    )

    assert decision.async_strategy == AsyncRouteStrategy.CREATE_JOB_AND_TASK
    assert decision.should_return_initial_response is True
    assert decision.should_create_job is True
    assert decision.should_create_task is True
    assert decision.should_publish_progress_events is True
    assert decision.expected_initial_result_state == "queued"
    assert decision.expected_final_result_state == "verification_pending"
    assert decision.completion_claimed is False
    assert decision.verification_claimed is False


def test_route_progress_state_serializes_without_false_completion_or_verification_claims() -> None:
    progress = RouteProgressState.create(
        request_id="request-1",
        session_id="session-1",
        route_family="software_control",
        subsystem="software_control",
        stage=RouteProgressStage.RUNNING,
        message="Installing is running, not complete.",
        progress_percent=25,
        verification_state="verification_pending",
        completion_claimed=True,
        verification_claimed=True,
        debug={"api_key": "secret", "raw_audio": b"abc"},
    )

    payload = progress.to_dict()

    assert payload["stage"] == "running"
    assert payload["status"] == "active"
    assert payload["completion_claimed"] is False
    assert payload["verification_claimed"] is False
    assert payload["debug"]["api_key"] == "<redacted>"
    assert payload["debug"]["raw_audio"] == "<redacted>"


def test_latency_trace_carries_l4_async_progress_fields() -> None:
    trace = build_latency_trace(
        metadata={
            "route_family": "workflow",
            "subsystem": "workflow",
            "async_route": {
                "async_strategy": "create_job",
                "async_initial_response_returned": True,
                "route_progress_stage": "queued",
                "route_progress_status": "active",
                "route_continuation_id": "route-cont-1",
                "async_route_handle": {
                    "continuation_id": "route-cont-1",
                    "job_id": "job-1",
                    "events_expected": True,
                },
                "progress_state": {
                    "stage": "queued",
                    "status": "active",
                    "completion_claimed": False,
                    "verification_claimed": False,
                    "authorization": "Bearer hidden",
                },
                "job_required": True,
                "task_required": True,
                "event_progress_required": True,
            },
        },
        stage_timings_ms={
            "job_create_ms": 9.0,
            "async_initial_response_returned": 1.0,
            "progress_event_count": 2.0,
        },
        request_id="request-l4",
        session_id="session-l4",
    )

    summary = trace.to_summary_dict()

    assert summary["async_strategy"] == "create_job"
    assert summary["async_initial_response_returned"] is True
    assert summary["async_continuation"] is True
    assert summary["route_progress_stage"] == "queued"
    assert summary["progress_event_count"] == 2
    assert summary["job_required"] is True
    assert summary["task_required"] is True
    assert summary["event_progress_required"] is True
    assert summary["route_progress_state"]["authorization"] == "<redacted>"


def test_job_progress_callback_publishes_bounded_progress_event(temp_config) -> None:
    async def scenario() -> None:
        manager, executor, events = _job_manager_for_tool(temp_config, SlowProgressTool())
        await manager.start()
        try:
            job = await manager.submit("echo", {"delay": 0.01}, session_id="l4-progress")
            finished = await manager.wait(job.job_id)
        finally:
            await manager.stop()
            executor.shutdown()

        progress_events = [
            event.to_dict()
            for event in events.replay(cursor=0, session_id="l4-progress").events
            if event.event_type == "job.progress"
        ]

        assert finished.status == JobStatus.COMPLETED
        assert progress_events
        payload = progress_events[0]["payload"]
        assert payload["job_id"] == job.job_id
        assert payload["tool_name"] == "echo"
        assert payload["status"] in {"queued", "running"}
        assert payload["progress"]["progress_percent"] == 40
        assert payload["progress"]["authorization"] == "<redacted>"
        assert payload["progress"]["raw_audio"] == "<redacted>"

    asyncio.run(scenario())


def test_async_tool_request_returns_initial_route_handle_without_waiting(temp_config) -> None:
    async def scenario() -> None:
        assistant, jobs, executor, _, _ = _build_assistant_with_workspace(
            temp_config,
            system_probe=FakeSystemProbe(),
        )
        assistant.tool_registry._tools["echo"] = SlowProgressTool()
        request_cache: dict[str, object] = {}
        stage_timings: dict[str, float] = {}
        route_subspans: dict[str, float] = {}

        await jobs.start()
        started = perf_counter()
        try:
            assistant_text, submitted_jobs, actions = await assistant._execute_tool_requests(
                [ToolRequest("echo", {"delay": 0.25})],
                session_id="l4-async",
                prompt="run the slow progress test",
                surface_mode="ghost",
                active_module="chartroom",
                stage_timings=stage_timings,
                route_handler_subspans=route_subspans,
                response_profile="ghost_compact",
                request_cache=request_cache,
            )
            elapsed_ms = (perf_counter() - started) * 1000
            finished = await jobs.wait(str(submitted_jobs[0]["job_id"]))
        finally:
            await jobs.stop()
            executor.shutdown()

        assert elapsed_ms < 150
        assert submitted_jobs[0]["status"] in {"queued", "running"}
        assert submitted_jobs[0]["result"] is None
        assert actions == []
        assert finished.status == JobStatus.COMPLETED
        assert "queued" in assistant_text.lower() or "running" in assistant_text.lower()
        assert request_cache["async_route"]["async_strategy"] == "create_job"
        assert request_cache["async_route"]["progress_state"]["completion_claimed"] is False
        assert request_cache["async_route"]["progress_state"]["verification_claimed"] is False
        assert stage_timings["async_initial_response_returned"] == 1.0
        assert stage_timings["job_wait_ms"] == 0.0

    asyncio.run(scenario())


def test_kraken_l4_report_includes_async_strategy_and_progress_counts() -> None:
    from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
    from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
    from stormhelm.core.orchestrator.command_eval.models import CoreObservation
    from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
    from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary

    case = CommandEvalCase(
        case_id="l4-row-1",
        message="run a workflow",
        expected=ExpectedBehavior(route_family="workflow", subsystem="workflow"),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=420.0,
        ui_response="Queued workflow progress.",
        actual_route_family="workflow",
        actual_subsystem="workflow",
        result_state="queued",
        job_states=("queued",),
        stage_timings_ms={
            "planner_route_ms": 50.0,
            "job_create_ms": 10.0,
            "async_initial_response_returned": 1.0,
        },
        latency_summary={
            "execution_mode": "async_first",
            "async_strategy": "create_job",
            "async_initial_response_returned": True,
            "route_progress_stage": "queued",
            "route_progress_status": "active",
            "progress_event_count": 2,
            "job_required": True,
            "task_required": True,
            "event_progress_required": True,
            "longest_stage": "planner_route_ms",
            "longest_stage_ms": 50.0,
        },
        budget_result={
            "budget_label": "long_task",
            "target_ms": 500.0,
            "soft_ceiling_ms": 1500.0,
            "hard_ceiling_ms": 10000.0,
            "budget_exceeded": False,
            "hard_ceiling_exceeded": False,
            "async_continuation_expected": True,
        },
    )
    result = CommandEvalResult(case=case, observation=observation, assertions={})

    row = result.to_dict()
    report = build_checkpoint_summary([result])["kraken_latency_report"]

    assert row["async_strategy"] == "create_job"
    assert row["async_initial_response_returned"] is True
    assert row["route_progress_stage"] == "queued"
    assert row["progress_event_count"] == 2
    assert report["async_initial_response_count"] == 1
    assert report["progress_event_count"] == 2
    assert report["by_async_strategy"]["create_job"]["p95"] == 420.0
