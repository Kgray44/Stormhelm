from __future__ import annotations

import asyncio
from pathlib import Path

from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
from stormhelm.core.jobs.models import JobRecord, JobStatus
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import (
    ConversationRepository,
    NotesRepository,
    PreferencesRepository,
    ToolRunRepository,
)
from stormhelm.core.orchestrator.assistant import AssistantOrchestrator
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tasks import DurableTaskService
from stormhelm.core.tasks import TaskRepository
from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.core.tools.executor import ToolExecutor
from stormhelm.core.tools.registry import ToolRegistry
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository
from stormhelm.core.workspace.service import WorkspaceService
from stormhelm.shared.result import ExecutionMode, ToolResult


class WorkflowEchoTool(BaseTool):
    name = "workflow_execute"
    display_name = "Workflow Echo"
    description = "Async workflow test tool."
    execution_mode = ExecutionMode.ASYNC

    async def execute_async(self, context: ToolContext, arguments: dict[str, object]) -> ToolResult:
        await asyncio.sleep(float(arguments.get("delay", 0.01)))
        return ToolResult(
            success=True,
            summary="Workflow step completed cleanly.",
            data={"verification_summary": "Workflow output is ready for verification."},
        )


def _build_task_service(temp_config) -> tuple[
    SQLiteDatabase,
    PreferencesRepository,
    ConversationStateStore,
    DurableTaskService,
]:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    preferences = PreferencesRepository(database)
    state = ConversationStateStore(preferences)
    service = DurableTaskService(
        repository=TaskRepository(database),
        session_state=state,
        events=EventBuffer(),
    )
    return database, preferences, state, service


def _build_workspace_service(temp_config, database: SQLiteDatabase, preferences: PreferencesRepository, state: ConversationStateStore) -> WorkspaceService:
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    return WorkspaceService(
        config=temp_config,
        repository=WorkspaceRepository(database),
        notes=notes,
        conversations=conversations,
        preferences=preferences,
        session_state=state,
        indexer=WorkspaceIndexer(temp_config),
        events=EventBuffer(),
        persona=PersonaContract(temp_config),
    )


def test_task_service_persists_durable_graph_and_flags_stale_resume_state(temp_project_root: Path, temp_config) -> None:
    artifact = temp_project_root / "build" / "portable.zip"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("portable artifact", encoding="utf-8")

    database, preferences, state, service = _build_task_service(temp_config)
    workspace_service = _build_workspace_service(temp_config, database, preferences, state)
    workspace = workspace_service.repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Portable package verification.",
    )
    state.set_active_workspace_id("default", workspace.workspace_id)

    plan = service.begin_execution(
        session_id="default",
        prompt="Package the portable build and verify the result",
        requests=[
            ToolRequest("file_operation", {"path": str(artifact), "operation": "package"}),
            ToolRequest("maintenance_action", {"action": "verify"}),
        ],
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={"workspace": workspace.to_dict()},
    )

    assert plan is not None

    service.record_direct_tool_result(
        task_id=plan.task_id,
        step_id=plan.step_ids[0],
        tool_name="file_operation",
        arguments={"path": str(artifact), "operation": "package"},
        result={
            "summary": "Portable package created.",
            "data": {
                "artifacts": [{"kind": "file", "label": "Portable archive", "locator": str(artifact)}],
            },
        },
        success=True,
    )

    persisted = DurableTaskService(
        repository=TaskRepository(database),
        session_state=state,
        events=EventBuffer(),
    )
    active = persisted.active_task_summary("default")

    assert active["taskId"] == plan.task_id
    assert active["steps"][0]["state"] == "completed"
    assert active["steps"][1]["state"] in {"pending", "ready"}
    assert active["nextSteps"]
    assert "verify" in " ".join(active["nextSteps"]).lower()
    assert active["resumeAssessment"]["status"] == "resumable"

    artifact.unlink()

    stale = persisted.active_task_summary("default")

    assert stale["resumeAssessment"]["status"] == "stale"
    assert stale["resumeAssessment"]["canResume"] is False
    assert any(str(item).endswith("portable.zip") for item in stale["resumeAssessment"]["missingArtifacts"])
    assert stale["artifacts"][0]["existsState"] == "missing"


def test_job_manager_observer_updates_durable_task_state(temp_config) -> None:
    async def scenario() -> None:
        database = SQLiteDatabase(temp_config.storage.database_path)
        database.initialize()
        preferences = PreferencesRepository(database)
        state = ConversationStateStore(preferences)
        events = EventBuffer()
        tasks = DurableTaskService(
            repository=TaskRepository(database),
            session_state=state,
            events=events,
        )
        registry = ToolRegistry()
        registry.register(WorkflowEchoTool())
        executor = ToolExecutor(registry)
        notes = NotesRepository(database)
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
                task_service=tasks,
            ),
            tool_runs=tool_runs,
            events=events,
            observer=tasks,
        )

        plan = tasks.begin_execution(
            session_id="default",
            prompt="Run the workflow and hold the step state durably",
            requests=[ToolRequest("workflow_execute", {"delay": 0.01})],
            surface_mode="ghost",
            active_module="chartroom",
            workspace_context={},
        )

        assert plan is not None

        await manager.start()
        try:
            job = await manager.submit(
                "workflow_execute",
                {"delay": 0.01},
                task_id=plan.task_id,
                task_step_id=plan.step_ids[0],
            )
            await manager.wait(job.job_id)
        finally:
            await manager.stop()
            executor.shutdown()

        active = tasks.active_task_summary("default")

        assert active["taskId"] == plan.task_id
        assert active["steps"][0]["jobId"] == job.job_id
        assert active["steps"][0]["state"] == "completed"
        assert active["evidenceSummary"]
        assert active["resumeAssessment"]["status"] in {"verification", "completed", "resumable"}

    asyncio.run(scenario())


def test_assistant_continuity_prefers_durable_task_state_over_workspace_memory(temp_config) -> None:
    async def scenario() -> None:
        database = SQLiteDatabase(temp_config.storage.database_path)
        database.initialize()
        events = EventBuffer()
        conversations = ConversationRepository(database)
        notes = NotesRepository(database)
        preferences = PreferencesRepository(database)
        state = ConversationStateStore(preferences)
        workspace_service = WorkspaceService(
            config=temp_config,
            repository=WorkspaceRepository(database),
            notes=notes,
            conversations=conversations,
            preferences=preferences,
            session_state=state,
            indexer=WorkspaceIndexer(temp_config),
            events=events,
            persona=PersonaContract(temp_config),
        )
        tasks = DurableTaskService(
            repository=TaskRepository(database),
            session_state=state,
            events=events,
        )
        workspace = workspace_service.repository.upsert_workspace(
            name="Packaging Workspace",
            topic="packaging",
            summary="Portable build and verification.",
            where_left_off="Old workspace memory said to reopen the README.",
            pending_next_steps=["Read the old notes."],
        )
        state.set_active_workspace_id("default", workspace.workspace_id)
        workspace_service.capture_workspace_context(
            session_id="default",
            prompt="Continue packaging",
            surface_mode="deck",
            active_module="files",
            workspace_context={"workspace": workspace.to_dict()},
        )

        plan = tasks.begin_execution(
            session_id="default",
            prompt="Package the portable build and verify the result",
            requests=[
                ToolRequest("file_operation", {"path": str(temp_config.project_root / "dist" / "portable.zip")}),
                ToolRequest("maintenance_action", {"action": "verify"}),
            ],
            surface_mode="deck",
            active_module="chartroom",
            workspace_context={"workspace": workspace.to_dict()},
        )
        assert plan is not None
        tasks.record_direct_tool_result(
            task_id=plan.task_id,
            step_id=plan.step_ids[0],
            tool_name="file_operation",
            arguments={"path": str(temp_config.project_root / "dist" / "portable.zip")},
            result={"summary": "Portable package created."},
            success=True,
        )

        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        jobs = JobManager(
            config=temp_config,
            executor=executor,
            context_factory=lambda job_id: ToolContext(
                job_id=job_id,
                config=temp_config,
                events=events,
                notes=notes,
                preferences=preferences,
                safety_policy=SafetyPolicy(temp_config),
                workspace_service=workspace_service,
                task_service=tasks,
            ),
            tool_runs=ToolRunRepository(database),
            events=events,
            observer=tasks,
        )
        assistant = AssistantOrchestrator(
            config=temp_config,
            conversations=conversations,
            jobs=jobs,
            router=IntentRouter(),
            events=events,
            tool_registry=registry,
            session_state=state,
            planner=DeterministicPlanner(
                calculations_config=temp_config.calculations,
                screen_awareness_config=temp_config.screen_awareness,
                discord_relay_config=temp_config.discord_relay,
            ),
            persona=PersonaContract(temp_config),
            workspace_service=workspace_service,
            task_service=tasks,
        )

        await jobs.start()
        try:
            payload = await assistant.handle_message(
                "where did we leave off?",
                session_id="default",
                surface_mode="ghost",
                active_module="chartroom",
            )
        finally:
            await jobs.stop()
            executor.shutdown()

        assert payload["jobs"][0]["tool_name"] == "workspace_where_left_off"
        assert "portable" in payload["assistant_message"]["content"].lower()
        assert "verify" in payload["assistant_message"]["content"].lower()
        assert payload["active_task"]["taskId"] == plan.task_id

    asyncio.run(scenario())


def test_task_service_suppresses_duplicate_equivalent_requests(temp_config) -> None:
    _, _, _, service = _build_task_service(temp_config)

    first = service.begin_execution(
        session_id="default",
        prompt="Package the portable build and verify the result",
        requests=[
            ToolRequest("file_operation", {"path": str(temp_config.project_root / "dist" / "portable.zip"), "operation": "package"}),
            ToolRequest("maintenance_action", {"action": "verify"}),
        ],
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={"workspace": {"workspaceId": "ws-package"}},
    )
    second = service.begin_execution(
        session_id="default",
        prompt="Package the portable build and verify the result",
        requests=[
            ToolRequest("file_operation", {"path": str(temp_config.project_root / "dist" / "portable.zip"), "operation": "package"}),
            ToolRequest("maintenance_action", {"action": "verify"}),
        ],
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={"workspace": {"workspaceId": "ws-package"}},
    )

    assert first is not None
    assert second is not None
    assert second.task_id == first.task_id
    assert len(service.repository.list_recent_tasks("default", limit=4)) == 1

    active = service.active_task_summary("default")

    assert active["continuity"]["duplicateSuppression"]["status"] == "reused"
    assert active["continuity"]["duplicateSuppression"]["taskId"] == first.task_id


def test_task_service_prefers_recent_workspace_task_when_old_task_has_expired(temp_project_root: Path, temp_config) -> None:
    _, _, state, service = _build_task_service(temp_config)
    old_artifact = temp_project_root / "dist" / "old-portable.zip"
    fresh_artifact = temp_project_root / "dist" / "fresh-portable.zip"
    old_artifact.parent.mkdir(parents=True, exist_ok=True)
    old_artifact.write_text("old", encoding="utf-8")
    fresh_artifact.write_text("fresh", encoding="utf-8")

    old_plan = service.begin_execution(
        session_id="default",
        prompt="Package the old portable build and verify the result",
        requests=[
            ToolRequest("file_operation", {"path": str(old_artifact), "operation": "package"}),
            ToolRequest("maintenance_action", {"action": "verify"}),
        ],
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={"workspace": {"workspaceId": "ws-old"}},
    )
    assert old_plan is not None
    service.record_direct_tool_result(
        task_id=old_plan.task_id,
        step_id=old_plan.step_ids[0],
        tool_name="file_operation",
        arguments={"path": str(old_artifact), "operation": "package"},
        result={"summary": "Old portable package created."},
        success=True,
    )

    old_task = service.repository.get_task(old_plan.task_id)
    assert old_task is not None
    old_timestamp = "2025-01-15T10:00:00Z"
    old_task.created_at = old_timestamp
    old_task.updated_at = old_timestamp
    old_task.started_at = old_timestamp
    for step in old_task.steps:
        step.started_at = old_timestamp
        if step.state == "completed":
            step.finished_at = old_timestamp
    for checkpoint in old_task.checkpoints:
        checkpoint.created_at = old_timestamp
        if checkpoint.completed_at:
            checkpoint.completed_at = old_timestamp
    for artifact in old_task.artifacts:
        artifact.created_at = old_timestamp
    for evidence in old_task.evidence:
        evidence.created_at = old_timestamp
    for link in old_task.job_links:
        link.created_at = old_timestamp
        link.updated_at = old_timestamp
    service.repository.save_task(old_task)

    fresh_plan = service.begin_execution(
        session_id="default",
        prompt="Package the fresh portable build and verify the result",
        requests=[
            ToolRequest("file_operation", {"path": str(fresh_artifact), "operation": "package"}),
            ToolRequest("maintenance_action", {"action": "verify"}),
        ],
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={"workspace": {"workspaceId": "ws-fresh"}},
    )
    assert fresh_plan is not None
    service.record_direct_tool_result(
        task_id=fresh_plan.task_id,
        step_id=fresh_plan.step_ids[0],
        tool_name="file_operation",
        arguments={"path": str(fresh_artifact), "operation": "package"},
        result={"summary": "Fresh portable package created."},
        success=True,
    )

    state.set_active_workspace_id("default", "ws-fresh")
    state.set_active_task_id("default", old_plan.task_id)

    active = service.active_task_summary("default")

    assert active["taskId"] == fresh_plan.task_id
    assert active["continuity"]["source"] == "recent_durable_task"
    assert active["continuity"]["selectionReason"] == "matched_active_workspace"


def test_task_service_distinguishes_waiting_states_from_resumable_pause(temp_project_root: Path, temp_config) -> None:
    _, _, state, service = _build_task_service(temp_config)
    artifact = temp_project_root / "dist" / "portable.zip"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("portable", encoding="utf-8")

    paused_plan = service.begin_execution(
        session_id="default",
        prompt="Package the portable build and verify the result",
        requests=[
            ToolRequest("file_operation", {"path": str(artifact), "operation": "package"}),
            ToolRequest("maintenance_action", {"action": "verify"}),
        ],
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={},
    )
    assert paused_plan is not None
    service.record_direct_tool_result(
        task_id=paused_plan.task_id,
        step_id=paused_plan.step_ids[0],
        tool_name="file_operation",
        arguments={"path": str(artifact), "operation": "package"},
        result={"summary": "Portable package created."},
        success=True,
    )

    paused = service.active_task_summary("default")

    assert paused["state"] == "paused"
    assert paused["resumeAssessment"]["status"] == "resumable"

    operator_plan = service.begin_execution(
        session_id="default",
        prompt="Open the trusted hook and wait for approval",
        requests=[ToolRequest("trusted_hook_execute", {"hook": "dangerous_action"})],
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
    )
    assert operator_plan is not None
    service.record_trust_pending(
        task_id=operator_plan.task_id,
        request={"approval_request_id": "approval-1", "subject": "dangerous_action"},
        decision={"approval_state": "pending", "operator_message": "Need an operator approval before continuing."},
    )
    state.set_active_task_id("default", operator_plan.task_id)

    operator = service.active_task_summary("default")

    assert operator["state"] == "blocked"
    assert operator["resumeAssessment"]["status"] == "waiting_operator"

    environment_plan = service.begin_execution(
        session_id="default",
        prompt="Reconnect the browser workspace",
        requests=[ToolRequest("workspace_restore", {"workspace_id": "ws-env"})],
        surface_mode="deck",
        active_module="browser",
        workspace_context={"workspace": {"workspaceId": "ws-env"}},
    )
    assert environment_plan is not None
    service.record_recovery_signal(
        environment_plan.task_id,
        "The browser tab is gone, so Stormhelm is waiting for the environment to come back.",
        source="environment",
    )
    state.set_active_task_id("default", environment_plan.task_id)

    waiting_environment = service.active_task_summary("default")

    assert waiting_environment["state"] == "blocked"
    assert waiting_environment["resumeAssessment"]["status"] == "waiting_environment"


def test_task_service_tolerates_replayed_and_out_of_order_job_events(temp_config) -> None:
    _, _, _, service = _build_task_service(temp_config)

    plan = service.begin_execution(
        session_id="default",
        prompt="Run the workflow once and keep the lifecycle sane",
        requests=[ToolRequest("workflow_execute", {"delay": 0.01})],
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
    )
    assert plan is not None

    job = JobRecord(
        job_id="job-1",
        tool_name="workflow_execute",
        arguments={"delay": 0.01},
        status=JobStatus.COMPLETED,
        created_at="2026-04-22T10:00:00Z",
        timeout_seconds=30.0,
        started_at="2026-04-22T10:00:01Z",
        finished_at="2026-04-22T10:00:02Z",
        result={"summary": "Workflow finished once."},
        session_id="default",
        task_id=plan.task_id,
        task_step_id=plan.step_ids[0],
    )

    service.on_job_queued(job)
    service.on_job_started(job)
    service.on_job_finished(job)
    service.on_job_progress(job, {"summary": "Late progress should not overwrite the durable result."})
    service.on_job_started(job)
    service.on_job_queued(job)
    service.on_job_finished(job)

    task = service.repository.get_task(plan.task_id)
    assert task is not None

    assert task.steps[0].state == "completed"
    assert task.steps[0].summary == "Workflow finished once."
    assert len(task.job_links) == 1
    assert len([entry for entry in task.evidence if entry.kind == "summary"]) == 1

    active = service.active_task_summary("default")

    assert active["continuity"]["lifecycle"]["droppedCount"] >= 1


def test_task_service_keeps_execution_finished_separate_from_verified_completion(temp_project_root: Path, temp_config) -> None:
    _, _, _, service = _build_task_service(temp_config)
    artifact = temp_project_root / "dist" / "portable.zip"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("portable", encoding="utf-8")

    plan = service.begin_execution(
        session_id="default",
        prompt="Package the portable build",
        requests=[ToolRequest("file_operation", {"path": str(artifact), "operation": "package"})],
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={},
    )
    assert plan is not None

    service.record_direct_tool_result(
        task_id=plan.task_id,
        step_id=plan.step_ids[0],
        tool_name="file_operation",
        arguments={"path": str(artifact), "operation": "package"},
        result={"summary": "Portable package created."},
        success=True,
    )

    active = service.active_task_summary("default")
    where_left_off = service.where_we_left_off(session_id="default")

    assert active["state"] == "verification"
    assert active["resumeAssessment"]["status"] == "verification"
    assert "verification" in active["resumeAssessment"]["summary"].lower()
    assert where_left_off is not None
    assert "complete." not in where_left_off["summary"].lower()
    assert "verification" in where_left_off["summary"].lower() or "finished" in where_left_off["summary"].lower()


def test_task_service_keeps_surface_payloads_on_the_same_task_story(temp_project_root: Path, temp_config) -> None:
    _, _, _, service = _build_task_service(temp_config)
    artifact = temp_project_root / "dist" / "portable.zip"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("portable", encoding="utf-8")

    plan = service.begin_execution(
        session_id="default",
        prompt="Package the portable build and verify the result",
        requests=[
            ToolRequest("file_operation", {"path": str(artifact), "operation": "package"}),
            ToolRequest("maintenance_action", {"action": "verify"}),
        ],
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={"workspace": {"workspaceId": "ws-package"}},
    )
    assert plan is not None

    service.record_direct_tool_result(
        task_id=plan.task_id,
        step_id=plan.step_ids[0],
        tool_name="file_operation",
        arguments={"path": str(artifact), "operation": "package"},
        result={"summary": "Portable package created."},
        success=True,
    )

    active = service.active_task_summary("default")
    where_left_off = service.where_we_left_off(session_id="default")
    next_steps = service.next_steps(session_id="default")

    assert where_left_off is not None
    assert next_steps is not None
    assert active["taskId"] == where_left_off["task"]["taskId"] == next_steps["task"]["taskId"]
    assert active["continuity"]["source"] == where_left_off["task"]["continuity"]["source"] == next_steps["task"]["continuity"]["source"]
    assert active["ghostSummary"]["title"] == where_left_off["task"]["ghostSummary"]["title"]
    assert active["commandDeck"]["groups"][0]["entries"][0]["title"] == next_steps["task"]["commandDeck"]["groups"][0]["entries"][0]["title"]
