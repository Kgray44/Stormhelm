from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from stormhelm.core.events import EventBuffer
from stormhelm.core.memory import (
    MemoryQuery,
    MemoryRetrievalIntent,
    MemorySourceClass,
    SemanticMemoryRepository,
    SemanticMemoryService,
)
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.router import ToolRequest
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.tasks import DurableTaskService, TaskRepository
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository
from stormhelm.core.workspace.service import WorkspaceService


def _build_memory_stack(temp_config) -> tuple[
    SQLiteDatabase,
    SemanticMemoryService,
    ConversationStateStore,
    DurableTaskService,
    WorkspaceService,
]:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    preferences = PreferencesRepository(database)
    memory = SemanticMemoryService(SemanticMemoryRepository(database))
    state = ConversationStateStore(preferences, memory=memory)
    task_service = DurableTaskService(
        repository=TaskRepository(database),
        session_state=state,
        events=EventBuffer(),
        memory=memory,
    )
    workspace_service = WorkspaceService(
        config=temp_config,
        repository=WorkspaceRepository(database),
        notes=NotesRepository(database),
        conversations=ConversationRepository(database),
        preferences=preferences,
        session_state=state,
        indexer=WorkspaceIndexer(temp_config),
        events=EventBuffer(),
        persona=PersonaContract(temp_config),
        memory=memory,
    )
    return database, memory, state, task_service, workspace_service


def _restamp_record(memory: SemanticMemoryService, record_id: str, *, timestamp: str) -> None:
    record = memory.repository.get_record(record_id)
    assert record is not None
    record.created_at = timestamp
    record.updated_at = timestamp
    record.last_validated_at = timestamp
    if "updated_at" in record.structured_fields:
        record.structured_fields["updated_at"] = timestamp
    if "captured_at" in record.structured_fields:
        record.structured_fields["captured_at"] = timestamp
    if "first_seen_at" in record.structured_fields:
        record.structured_fields["first_seen_at"] = timestamp
    if "last_seen_at" in record.structured_fields:
        record.structured_fields["last_seen_at"] = timestamp
    memory.repository.save_record(memory._with_freshness(record))


def _count_family_records(memory: SemanticMemoryService, family: str) -> int:
    with memory.repository.database.connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM memory_records WHERE memory_family = ?",
            (family,),
        ).fetchone()
    return int(row["count"] or 0)


def _count_query_logs(memory: SemanticMemoryService) -> int:
    with memory.repository.database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM memory_query_log").fetchone()
    return int(row["count"] or 0)


def test_memory_family_separation_and_provenance_are_preserved(temp_config) -> None:
    _, memory, state, _, _ = _build_memory_stack(temp_config)

    state.remember_preference("weather", "open_target", "deck")
    memory.remember_environment_observation(
        environment_key="vscode.monitor",
        machine_scope="stormhelm-rig",
        app_scope="vscode",
        observed_pattern="VS Code often opens on monitor 2.",
    )
    memory.remember_semantic_recall(
        summary="Portable packaging fix: regenerate the archive manifest before verifying the zip.",
        canonical_entities=["packaging", "archive", "verification"],
    )

    result = memory.retrieve(
        MemoryQuery(
            query_id="pref-query",
            retrieval_intent=MemoryRetrievalIntent.PREFERENCE_LOOKUP.value,
            semantic_query_text="weather open target preference",
            structured_filters={"preference_key": "weather.open_target"},
            caller_subsystem="tests",
        )
    )

    assert result.matched_records
    top = result.matched_records[0].record
    assert top.memory_family == "preference"
    assert top.source_class == "operator_provided"
    assert top.provenance.origin_surface == "preference_learning"
    assert result.retrieval_trace["familiesSearched"] == ["preference"]

    recent_queries = memory.repository.list_recent_queries(limit=1)
    assert recent_queries
    assert recent_queries[0]["retrieval_intent"] == "preference_lookup"
    assert recent_queries[0]["matched_record_ids"]


def test_stale_environment_memory_is_worded_conservatively_and_tracks_conflict(temp_config) -> None:
    _, memory, _, _, _ = _build_memory_stack(temp_config)
    stale_at = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    memory.remember_environment_observation(
        environment_key="explorer.monitor",
        machine_scope="stormhelm-rig",
        app_scope="explorer",
        observed_pattern="Explorer opens on the left monitor after boot.",
        created_at=stale_at,
        last_seen_at=stale_at,
    )

    result = memory.retrieve(
        MemoryQuery(
            query_id="env-query",
            retrieval_intent=MemoryRetrievalIntent.ENVIRONMENT_LOOKUP.value,
            semantic_query_text="explorer monitor",
            structured_filters={"current_values": {"observed_pattern": "Explorer now opens on the right monitor."}},
            caller_subsystem="tests",
        )
    )

    assert result.matched_records
    top = result.matched_records[0]
    assert top.record.memory_family == "environment"
    assert top.record.freshness_state in {"stale", "expired"}
    assert top.current_evidence_conflicts == ["observed_pattern"]
    assert "stale" in result.safe_user_visible_summary.lower()


def test_stale_preference_conflicting_with_current_instruction_is_suppressed_with_trace(temp_config) -> None:
    _, memory, state, _, _ = _build_memory_stack(temp_config)
    state.remember_preference("weather", "open_target", "deck")
    record = memory.repository.get_by_dedupe_key("preference:weather:open_target")
    assert record is not None

    stale_at = (datetime.now(timezone.utc) - timedelta(days=420)).isoformat()
    _restamp_record(memory, record.memory_id, timestamp=stale_at)

    result = memory.retrieve(
        MemoryQuery(
            query_id="stale-pref-conflict",
            retrieval_intent=MemoryRetrievalIntent.PREFERENCE_LOOKUP.value,
            semantic_query_text="weather open target preference",
            structured_filters={
                "preference_key": "weather.open_target",
                "current_values": {"value": "ghost"},
            },
            caller_subsystem="tests",
        )
    )

    assert result.matched_records == []
    assert result.filtered_out_counts["current_evidence_suppressed"] == 1
    assert result.retrieval_trace["suppressedPreview"]
    suppressed = result.retrieval_trace["suppressedPreview"][0]
    assert suppressed["family"] == "preference"
    assert "preference_conflicts_with_current_evidence" in suppressed["reasons"]


def test_stale_environment_note_conflicting_with_runtime_state_is_suppressed_with_trace(temp_config) -> None:
    _, memory, _, _, _ = _build_memory_stack(temp_config)
    stale_at = (datetime.now(timezone.utc) - timedelta(days=240)).isoformat()
    memory.remember_environment_observation(
        environment_key="explorer.monitor",
        machine_scope="stormhelm-rig",
        app_scope="explorer",
        observed_pattern="Explorer opens on the left monitor after boot.",
        created_at=stale_at,
        last_seen_at=stale_at,
        revalidation_needed=True,
    )

    result = memory.retrieve(
        MemoryQuery(
            query_id="stale-env-conflict",
            retrieval_intent=MemoryRetrievalIntent.ENVIRONMENT_LOOKUP.value,
            semantic_query_text="explorer monitor runtime state",
            structured_filters={
                "environment_key": "explorer.monitor",
                "current_values": {"observed_pattern": "Explorer now opens on the right monitor after the latest update."},
            },
            caller_subsystem="tests",
        )
    )

    assert result.matched_records == []
    assert result.filtered_out_counts["current_evidence_suppressed"] == 1
    suppressed = result.retrieval_trace["suppressedPreview"][0]
    assert suppressed["family"] == "environment"
    assert "environment_conflicts_with_runtime_state" in suppressed["reasons"]


def test_task_resume_retrieval_prefers_task_memory_over_semantic_neighbor(temp_project_root: Path, temp_config) -> None:
    artifact = temp_project_root / "dist" / "portable.zip"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("artifact", encoding="utf-8")

    _, memory, state, task_service, workspace_service = _build_memory_stack(temp_config)
    workspace = workspace_service.repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Portable packaging verification work.",
    )
    state.set_active_workspace_id("default", workspace.workspace_id)

    plan = task_service.begin_execution(
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

    task_service.record_direct_tool_result(
        task_id=plan.task_id,
        step_id=plan.step_ids[0],
        tool_name="file_operation",
        arguments={"path": str(artifact), "operation": "package"},
        result={"summary": "Portable package created cleanly."},
        success=True,
    )
    memory.remember_semantic_recall(
        summary="A prior packaging fix reused the archive verification lane.",
        canonical_entities=["packaging", "archive", "verification"],
    )

    result = memory.retrieve(
        MemoryQuery(
            query_id="task-query",
            retrieval_intent=MemoryRetrievalIntent.TASK_RESUME.value,
            semantic_query_text="package portable build verify result",
            scope_constraints={"task_id": plan.task_id, "workspace_id": workspace.workspace_id, "session_id": "default"},
            caller_subsystem="tests",
        )
    )

    assert result.matched_records
    assert result.matched_records[0].record.memory_family == "task"
    assert plan.task_id in result.matched_records[0].record.related_task_ids


def test_task_resume_trace_marks_workspace_disagreement_and_prefers_task_memory(temp_project_root: Path, temp_config) -> None:
    artifact = temp_project_root / "dist" / "portable.zip"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("artifact", encoding="utf-8")

    _, memory, state, task_service, workspace_service = _build_memory_stack(temp_config)
    workspace = workspace_service.repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Packaging workspace notes say to reopen the README and refresh the release copy.",
        where_left_off="Reopen the README and refresh the release copy before touching packaging again.",
        pending_next_steps=["Reopen the README", "Refresh the release copy"],
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    workspace_service.capture_workspace_context(
        session_id="default",
        prompt="Continue the packaging workspace",
        surface_mode="deck",
        active_module="files",
        workspace_context={"workspace": workspace.to_dict()},
    )

    plan = task_service.begin_execution(
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

    task_service.record_direct_tool_result(
        task_id=plan.task_id,
        step_id=plan.step_ids[0],
        tool_name="file_operation",
        arguments={"path": str(artifact), "operation": "package"},
        result={"summary": "Portable package created cleanly and the next step is verification."},
        success=True,
    )

    result = memory.retrieve(
        MemoryQuery(
            query_id="task-workspace-disagreement",
            retrieval_intent=MemoryRetrievalIntent.TASK_RESUME.value,
            semantic_query_text="package portable build verify result",
            scope_constraints={"task_id": plan.task_id, "workspace_id": workspace.workspace_id, "session_id": "default"},
            caller_subsystem="tests",
        )
    )

    assert result.matched_records
    assert result.matched_records[0].record.memory_family == "task"
    assert result.retrieval_trace["familyConflicts"]
    conflict = result.retrieval_trace["familyConflicts"][0]
    assert conflict["preferredFamily"] == "task"
    assert conflict["demotedFamily"] == "workspace"


def test_workspace_restore_retrieval_prefers_workspace_memory_over_general_recall(temp_project_root: Path, temp_config) -> None:
    notes_path = temp_project_root / "docs" / "controls-map.md"
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text("Controls mapping plan", encoding="utf-8")

    _, memory, state, _, workspace_service = _build_memory_stack(temp_config)
    workspace = workspace_service.repository.upsert_workspace(
        name="Controls Project",
        topic="controls",
        summary="Reconnect the controls mapping flow.",
        active_goal="Reconnect the controls mapping layer.",
        pending_next_steps=["Reconnect the device mapping layer."],
        where_left_off="We restored the controls files and still need to reconnect the mapping layer.",
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    workspace_service.capture_workspace_context(
        session_id="default",
        prompt="Continue the controls project",
        surface_mode="deck",
        active_module="files",
        workspace_context={
            "workspace": workspace.to_dict(),
            "opened_items": [
                {
                    "itemId": "controls-map",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "controls-map.md",
                    "path": str(notes_path),
                    "summary": "Primary mapping plan.",
                    "role": "active",
                }
            ],
            "active_item": {
                "itemId": "controls-map",
                "kind": "markdown",
                "viewer": "markdown",
                "title": "controls-map.md",
                "path": str(notes_path),
                "summary": "Primary mapping plan.",
                "role": "active",
            },
        },
    )
    memory.remember_semantic_recall(
        summary="A prior controls issue also involved mapping layers and follow-up routing.",
        canonical_entities=["controls", "mapping", "routing"],
    )

    result = memory.retrieve(
        MemoryQuery(
            query_id="workspace-query",
            retrieval_intent=MemoryRetrievalIntent.WORKSPACE_RESTORE.value,
            semantic_query_text="restore controls mapping workspace",
            scope_constraints={"workspace_id": workspace.workspace_id, "session_id": "default"},
            caller_subsystem="tests",
        )
    )

    assert result.matched_records
    assert result.matched_records[0].record.memory_family == "workspace"
    assert workspace.workspace_id in result.matched_records[0].record.related_workspace_ids


def test_workspace_restore_trace_marks_task_disagreement_and_prefers_workspace_memory(temp_project_root: Path, temp_config) -> None:
    notes_path = temp_project_root / "docs" / "controls-map.md"
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.write_text("Controls mapping plan", encoding="utf-8")

    _, memory, state, task_service, workspace_service = _build_memory_stack(temp_config)
    workspace = workspace_service.repository.upsert_workspace(
        name="Controls Project",
        topic="controls",
        summary="Reconnect the controls mapping flow.",
        active_goal="Reconnect the controls mapping layer.",
        pending_next_steps=["Reconnect the device mapping layer."],
        where_left_off="Restore the controls workspace and reopen the mapping notes.",
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    workspace_service.capture_workspace_context(
        session_id="default",
        prompt="Continue the controls project",
        surface_mode="deck",
        active_module="files",
        workspace_context={
            "workspace": workspace.to_dict(),
            "opened_items": [
                {
                    "itemId": "controls-map",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "controls-map.md",
                    "path": str(notes_path),
                    "summary": "Primary mapping plan.",
                    "role": "active",
                }
            ],
            "active_item": {
                "itemId": "controls-map",
                "kind": "markdown",
                "viewer": "markdown",
                "title": "controls-map.md",
                "path": str(notes_path),
                "summary": "Primary mapping plan.",
                "role": "active",
            },
        },
    )

    plan = task_service.begin_execution(
        session_id="default",
        prompt="Reconnect device routing while controls map stays open",
        requests=[ToolRequest("maintenance_action", {"action": "reconnect routing"})],
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={"workspace": workspace.to_dict()},
    )
    assert plan is not None

    task_service.record_direct_tool_result(
        task_id=plan.task_id,
        step_id=plan.step_ids[0],
        tool_name="maintenance_action",
        arguments={"action": "reconnect routing"},
        result={"summary": "Routing reconnect started; verify the transport layer next."},
        success=True,
    )

    result = memory.retrieve(
        MemoryQuery(
            query_id="workspace-task-disagreement",
            retrieval_intent=MemoryRetrievalIntent.WORKSPACE_RESTORE.value,
            semantic_query_text="restore controls mapping workspace",
            scope_constraints={"workspace_id": workspace.workspace_id, "session_id": "default"},
            caller_subsystem="tests",
        )
    )

    assert result.matched_records
    assert result.matched_records[0].record.memory_family == "workspace"
    assert result.retrieval_trace["familyConflicts"]
    conflict = result.retrieval_trace["familyConflicts"][0]
    assert conflict["preferredFamily"] == "workspace"
    assert conflict["demotedFamily"] == "task"


def test_semantic_recall_wrong_scope_is_suppressed_even_when_lexically_similar(temp_config) -> None:
    _, memory, _, _, _ = _build_memory_stack(temp_config)
    memory.remember_semantic_recall(
        summary="Discord relay dispatch routing fix for channel handshake failure.",
        canonical_entities=["discord", "relay", "dispatch", "routing"],
        linked_workspaces=["workspace-other"],
    )
    memory.remember_semantic_recall(
        summary="Current relay workspace notes for the handshake sequence.",
        canonical_entities=["discord", "relay", "workspace"],
        linked_workspaces=["workspace-current"],
    )

    result = memory.retrieve(
        MemoryQuery(
            query_id="semantic-scope-hardening",
            retrieval_intent=MemoryRetrievalIntent.SEMANTIC_RECALL.value,
            semantic_query_text="discord relay dispatch routing bug",
            scope_constraints={"workspace_id": "workspace-current"},
            caller_subsystem="tests",
        )
    )

    assert result.matched_records
    assert result.matched_records[0].record.related_workspace_ids == ["workspace-current"]
    suppressed = result.retrieval_trace["suppressedPreview"]
    assert suppressed
    assert any(
        entry["family"] == "semantic_recall"
        and "scope_mismatch" in entry["reasons"]
        and float(entry["semanticAlignment"]["fuzzy"]) >= 0.6
        for entry in suppressed
    )


def test_preference_lookup_does_not_overpromote_single_inference(temp_config) -> None:
    _, memory, _, _, _ = _build_memory_stack(temp_config)

    memory.remember_preference(
        "weather",
        "location_mode",
        "home",
        source_class=MemorySourceClass.INFERRED.value,
    )
    assert memory.preference_value("weather", "location_mode", minimum_count=2) is None

    memory.remember_preference("weather", "location_mode", "home")
    memory.remember_preference("weather", "location_mode", "home")

    assert memory.preference_value("weather", "location_mode", minimum_count=2) == "home"


def test_write_policy_rejects_low_value_semantic_memory_and_records_trace(temp_config) -> None:
    _, memory, state, _, _ = _build_memory_stack(temp_config)

    rejected = memory.remember_semantic_recall(summary="ok")
    assert rejected is None

    state.remember_preference("weather", "open_target", "deck")
    result = memory.retrieve(
        MemoryQuery(
            query_id="trace-query",
            retrieval_intent=MemoryRetrievalIntent.PREFERENCE_LOOKUP.value,
            semantic_query_text="deck preference",
            structured_filters={"preference_key": "weather.open_target"},
            caller_subsystem="tests",
        )
    )

    assert result.retrieval_trace["rankingPreview"]
    recent_query = memory.repository.list_recent_queries(limit=1)[0]
    assert recent_query["retrieval_trace"]["rankingPreview"]


def test_session_memory_retention_prunes_old_records_and_keeps_recent_window_bounded(temp_config) -> None:
    _, memory, _, _, _ = _build_memory_stack(temp_config)
    memory.remember_context_resolution("default", {"summary": "Initial context resolution", "detail": "Initial detail"})
    first_record = memory.repository.list_records(
        families=["session"],
        related_session_id="default",
        limit=1,
    )[0]
    stale_at = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    _restamp_record(memory, first_record.memory_id, timestamp=stale_at)

    memory.remember_context_resolution("default", {"summary": "Trigger session prune", "detail": "Fresh detail"})
    for index in range(72):
        memory.remember_context_resolution(
            "default",
            {"summary": f"Recent context resolution {index}", "detail": f"detail {index}"},
        )

    assert _count_family_records(memory, "session") <= 64
    with memory.repository.database.connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM memory_records WHERE memory_family = 'session' AND updated_at < ?",
            ((datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),),
        ).fetchone()
    assert int(row["count"] or 0) == 0


def test_query_log_retention_prunes_old_entries_and_keeps_recent_window_bounded(temp_config) -> None:
    _, memory, state, _, _ = _build_memory_stack(temp_config)
    state.remember_preference("weather", "open_target", "deck")

    memory.retrieve(
        MemoryQuery(
            query_id="old-query",
            retrieval_intent=MemoryRetrievalIntent.PREFERENCE_LOOKUP.value,
            semantic_query_text="weather open target preference",
            structured_filters={"preference_key": "weather.open_target"},
            caller_subsystem="tests",
        )
    )
    stale_at = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
    with memory.repository.database.connect() as connection:
        connection.execute(
            "UPDATE memory_query_log SET created_at = ? WHERE query_id = ?",
            (stale_at, "old-query"),
        )

    for index in range(72):
        memory.retrieve(
            MemoryQuery(
                query_id=f"query-{index}",
                retrieval_intent=MemoryRetrievalIntent.PREFERENCE_LOOKUP.value,
                semantic_query_text="weather open target preference",
                structured_filters={"preference_key": "weather.open_target"},
                caller_subsystem="tests",
            )
        )

    recent_query = memory.repository.list_recent_queries(limit=1)[0]
    assert _count_query_logs(memory) <= 64
    assert recent_query["retrieval_trace"]["retentionCleanup"]["queryLogPruned"] >= 1
