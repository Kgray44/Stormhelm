from __future__ import annotations

import asyncio
from pathlib import Path

from stormhelm.core.events import EventBuffer
from stormhelm.core.jobs.manager import JobManager
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
