from __future__ import annotations

import inspect

from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from stormhelm.core.api.app import create_app
from stormhelm.core.events import EventBuffer
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository
from stormhelm.core.workspace.service import WorkspaceService


_SNAPSHOT_PARAMS = {
    "session_id": "default",
    "event_since_id": 0,
    "event_limit": 100,
    "job_limit": 50,
    "note_limit": 50,
    "history_limit": 100,
}


def _database(temp_config) -> SQLiteDatabase:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    return database


def _workspace_service(temp_config) -> tuple[
    SQLiteDatabase,
    ConversationRepository,
    PreferencesRepository,
    WorkspaceRepository,
    ConversationStateStore,
    WorkspaceService,
]:
    database = _database(temp_config)
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    repository = WorkspaceRepository(database)
    state = ConversationStateStore(preferences)
    service = WorkspaceService(
        config=temp_config,
        repository=repository,
        notes=notes,
        conversations=conversations,
        preferences=preferences,
        session_state=state,
        indexer=WorkspaceIndexer(temp_config),
        events=EventBuffer(),
        persona=PersonaContract(temp_config),
    )
    return database, conversations, preferences, repository, state, service


def _route_endpoint_map() -> dict[str, object]:
    app = create_app()
    return {
        route.path: route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute)
    }


def test_snapshot_exact_request_handles_legacy_workspace_posture(temp_config) -> None:
    database = _database(temp_config)
    preferences = PreferencesRepository(database)
    state = ConversationStateStore(preferences)
    repository = WorkspaceRepository(database)
    workspace = repository.upsert_workspace(
        name="Docs Workspace",
        topic="docs",
        summary="Hold the Stormhelm docs.",
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    state.set_active_posture(
        "default",
        {
            "workspace": "legacy-string-workspace",
            "active_goal": "Keep the docs workspace on watch.",
        },
    )

    with TestClient(create_app(temp_config)) as client:
        response = client.get("/snapshot", params=_SNAPSHOT_PARAMS)

    assert response.status_code == 200
    assert response.json()["active_workspace"]["workspace"]["workspaceId"] == workspace.workspace_id


def test_snapshot_and_status_routes_use_sync_handlers_for_threadpool_isolation() -> None:
    endpoints = _route_endpoint_map()

    for path in (
        "/health",
        "/status",
        "/chat/history",
        "/jobs",
        "/events",
        "/notes",
        "/settings",
        "/tools",
        "/lifecycle/core/shutdown",
        "/snapshot",
    ):
        assert inspect.iscoroutinefunction(endpoints[path]) is False

    assert inspect.iscoroutinefunction(endpoints["/chat/send"]) is True


def test_core_shutdown_route_schedules_process_exit_without_blocking_response(temp_config, monkeypatch) -> None:
    scheduled: list[str] = []
    monkeypatch.setattr(
        "stormhelm.core.api.app._schedule_process_shutdown",
        lambda: scheduled.append("shutdown"),
    )

    with TestClient(create_app(temp_config)) as client:
        response = client.post("/lifecycle/core/shutdown")

    assert response.status_code == 200
    assert response.json()["status"] == "shutting_down"
    assert scheduled == ["shutdown"]


def test_snapshot_tolerates_malformed_preference_rows(temp_config) -> None:
    database = _database(temp_config)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO preferences(preference_key, value_json) VALUES (?, ?)",
            ("assistant.session.default.active_posture", '{"broken"'),
        )

    with TestClient(create_app(temp_config)) as client:
        response = client.get("/snapshot", params=_SNAPSHOT_PARAMS)

    assert response.status_code == 200
    assert response.json()["active_workspace"] == {}


def test_snapshot_history_tolerates_malformed_message_metadata(temp_config) -> None:
    database = _database(temp_config)
    conversations = ConversationRepository(database)
    conversations.ensure_session("default")
    message = conversations.add_message("default", "user", "hello", metadata={"ok": True})
    with database.connect() as connection:
        connection.execute(
            "UPDATE chat_messages SET metadata_json = ? WHERE message_id = ?",
            ('{"broken"', message.message_id),
        )

    with TestClient(create_app(temp_config)) as client:
        response = client.get("/snapshot", params=_SNAPSHOT_PARAMS)

    assert response.status_code == 200
    history = response.json()["history"]
    hello = next(item for item in history if item["message_id"] == message.message_id)
    assert hello["metadata"] == {}


def test_snapshot_active_workspace_tolerates_malformed_item_metadata(temp_config) -> None:
    database = _database(temp_config)
    preferences = PreferencesRepository(database)
    state = ConversationStateStore(preferences)
    repository = WorkspaceRepository(database)
    workspace = repository.upsert_workspace(
        name="Docs Workspace",
        topic="docs",
        summary="Hold the Stormhelm docs.",
    )
    item = repository.upsert_item(
        workspace.workspace_id,
        {
            "kind": "markdown",
            "viewer": "markdown",
            "title": "README.md",
            "path": str(temp_config.project_root / "README.md"),
            "summary": "Primary documentation.",
        },
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE workspace_items SET metadata_json = ? WHERE item_id = ?",
            ('{"broken"', item.item_id),
        )
    state.set_active_workspace_id("default", workspace.workspace_id)

    with TestClient(create_app(temp_config)) as client:
        response = client.get("/snapshot", params=_SNAPSHOT_PARAMS)

    assert response.status_code == 200
    opened_items = response.json()["active_workspace"]["opened_items"]
    assert opened_items[0]["itemId"] == item.item_id
    assert opened_items[0]["title"] == "README.md"


def test_workspace_service_save_workspace_tolerates_legacy_workspace_posture(temp_config) -> None:
    _, _, _, repository, state, service = _workspace_service(temp_config)
    workspace = repository.upsert_workspace(
        name="Docs Workspace",
        topic="docs",
        summary="Hold the Stormhelm docs.",
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    state.set_active_posture(
        "default",
        {
            "workspace": "legacy-string-workspace",
            "active_goal": "Keep the docs workspace on watch.",
            "opened_items": [],
            "active_item": {},
            "pending_next_steps": ["Review the docs snapshot."],
        },
    )

    result = service.save_workspace(session_id="default")
    latest_snapshot = repository.get_latest_snapshot(workspace.workspace_id)
    active_posture = state.get_active_posture("default")

    assert "saved" in result["summary"].lower()
    assert latest_snapshot is not None
    assert latest_snapshot.payload["workspace"]["workspaceId"] == workspace.workspace_id
    assert active_posture["workspace"]["workspaceId"] == workspace.workspace_id
    assert active_posture["pending_next_steps"] == ["Review the docs snapshot."]
