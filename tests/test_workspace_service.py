from __future__ import annotations

from pathlib import Path

from stormhelm.core.events import EventBuffer
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository
from stormhelm.core.workspace.service import WorkspaceService


def test_workspace_service_assembles_relevant_local_items(temp_project_root: Path, temp_config) -> None:
    docs_dir = temp_project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    target = docs_dir / "packaging-notes.md"
    target.write_text("Packaging workspace notes", encoding="utf-8")
    (temp_project_root / "README.md").write_text("Stormhelm root", encoding="utf-8")

    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    repository = WorkspaceRepository(database)
    service = WorkspaceService(
        config=temp_config,
        repository=repository,
        notes=notes,
        conversations=conversations,
        preferences=preferences,
        session_state=ConversationStateStore(preferences),
        indexer=WorkspaceIndexer(temp_config),
        events=EventBuffer(),
        persona=PersonaContract(temp_config),
    )

    result = service.assemble_workspace("set up a workspace for packaging", session_id="default")

    assert result["action"]["type"] == "workspace_restore"
    assert result["workspace"]["name"] == "Packaging"
    assert any(item.get("path", "").endswith("packaging-notes.md") for item in result["items"])


def test_workspace_service_restores_recent_workspace_memory(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(name="Stormhelm Packaging", topic="packaging", summary="Portable build work.")
    repository.upsert_item(
        workspace.workspace_id,
        {
            "kind": "browser",
            "viewer": "browser",
            "title": "PyInstaller Docs",
            "url": "https://pyinstaller.org/",
            "module": "browser",
            "section": "open-pages",
        },
    )
    state.set_active_workspace_id("default", workspace.workspace_id)

    result = service.restore_workspace("continue the packaging workspace", session_id="default")

    assert result["workspace"]["name"] == "Stormhelm Packaging"
    assert result["action"]["type"] == "workspace_restore"
    assert result["items"][0]["viewer"] == "browser"


def test_workspace_service_save_snapshot_persists_structured_posture(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Continue the portable packaging work.",
    )
    service.capture_workspace_context(
        session_id="default",
        prompt="Verify the portable archive and confirm first-run behavior.",
        surface_mode="deck",
        active_module="files",
        workspace_context={
            "workspace": {
                **workspace.to_dict(),
                "activeGoal": "Verify the portable packaging output.",
                "pendingNextSteps": [
                    "Verify the portable archive contents.",
                    "Check first-run boot after packaging.",
                ],
                "currentStatus": "verification",
            },
            "module": "files",
            "section": "opened-items",
            "opened_items": [
                {
                    "itemId": "item-readme",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "README.md",
                    "path": str(temp_config.project_root / "README.md"),
                    "summary": "Primary packaging checklist.",
                    "role": "active",
                },
                {
                    "itemId": "item-pyinstaller",
                    "kind": "browser",
                    "viewer": "browser",
                    "title": "PyInstaller Docs",
                    "url": "https://pyinstaller.org/",
                    "summary": "Packaging reference.",
                    "role": "reference",
                },
            ],
            "active_item": {
                "itemId": "item-readme",
                "kind": "markdown",
                "viewer": "markdown",
                "title": "README.md",
                "path": str(temp_config.project_root / "README.md"),
                "summary": "Primary packaging checklist.",
                "role": "active",
            },
        },
    )

    result = service.save_workspace(session_id="default")
    saved_workspace = repository.get_workspace(workspace.workspace_id)
    latest_snapshot = repository.get_latest_snapshot(workspace.workspace_id)
    active_posture = state.get_active_posture("default")

    assert "saved" in result["summary"].lower()
    assert saved_workspace is not None
    assert saved_workspace.active_goal == "Verify the portable packaging output."
    assert saved_workspace.current_status == "verification"
    assert saved_workspace.pending_next_steps == [
        "Verify the portable archive contents.",
        "Check first-run boot after packaging.",
    ]
    assert saved_workspace.where_left_off != ""
    assert latest_snapshot is not None
    assert latest_snapshot.payload["active_item"]["title"] == "README.md"
    assert len(latest_snapshot.payload["opened_items"]) == 2
    assert active_posture["workspace"]["workspaceId"] == workspace.workspace_id
    assert active_posture["active_goal"] == "Verify the portable packaging output."


def test_workspace_service_archive_restore_rename_and_tag_are_real_operations(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(
        name="Stormhelm Packaging",
        topic="packaging",
        summary="Portable packaging and release prep.",
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    state.set_active_posture(
        "default",
        {
            "workspace": workspace.to_dict(),
            "active_goal": "Ship the portable build.",
            "pending_next_steps": ["Verify the portable bundle."],
            "opened_items": [],
            "active_item": {},
        },
    )

    renamed = service.rename_workspace(session_id="default", new_name="Minecraft Server Build")
    tagged = service.tag_workspace(session_id="default", tags=["minecraft", "modding"])
    archived = service.archive_workspace(session_id="default")
    archived_workspace = repository.get_workspace(workspace.workspace_id)
    archived_listing = service.list_workspaces(session_id="default", archived_only=True)

    assert renamed["workspace"]["name"] == "Minecraft Server Build"
    assert "minecraft" in tagged["workspace"]["tags"]
    assert archived_workspace is not None
    assert archived_workspace.archived is True
    assert state.get_active_workspace_id("default") is None
    assert archived_listing["workspaces"][0]["name"] == "Minecraft Server Build"

    restored = service.restore_workspace("minecraft workspace", session_id="default")
    restored_workspace = repository.get_workspace(workspace.workspace_id)

    assert restored["workspace"]["name"] == "Minecraft Server Build"
    assert restored_workspace is not None
    assert restored_workspace.archived is False
    assert state.get_active_workspace_id("default") == workspace.workspace_id


def test_workspace_service_clear_workspace_clears_active_posture_without_deleting_history(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Portable packaging and release prep.",
    )
    repository.upsert_item(
        workspace.workspace_id,
        {
            "kind": "markdown",
            "viewer": "markdown",
            "title": "packaging-notes.md",
            "path": str(temp_config.project_root / "packaging-notes.md"),
            "summary": "Primary packaging checklist.",
        },
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    state.set_active_posture(
        "default",
        {
            "workspace": workspace.to_dict(),
            "opened_items": [
                {
                    "itemId": "item-a",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "packaging-notes.md",
                    "path": str(temp_config.project_root / "packaging-notes.md"),
                }
            ],
            "active_item": {
                "itemId": "item-a",
                "kind": "markdown",
                "viewer": "markdown",
                "title": "packaging-notes.md",
                "path": str(temp_config.project_root / "packaging-notes.md"),
            },
        },
    )

    result = service.clear_workspace(session_id="default")

    assert "cleared" in result["summary"].lower()
    assert state.get_active_workspace_id("default") is None
    assert state.get_active_posture("default") == {}
    assert repository.get_workspace(workspace.workspace_id) is not None
    assert result["action"]["type"] == "workspace_clear"


def test_workspace_service_clear_workspace_reports_when_nothing_is_active(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    result = service.clear_workspace(session_id="default")

    assert result["summary"] == "No active workspace."
    assert result["workspace"] == {}


def test_workspace_service_where_left_off_and_next_steps_use_saved_state(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(
        name="Controls Project",
        topic="controls",
        summary="Continue the controls integration work.",
        active_goal="Finish the controls routing pass.",
        last_completed_action="Restored the controls files into the Deck.",
        pending_next_steps=[
            "Reconnect the device mapping layer.",
            "Verify the follow-up routing in Ghost.",
        ],
        where_left_off="We restored the controls files and still need to reconnect the mapping layer.",
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    state.set_active_posture(
        "default",
        {
            "workspace": workspace.to_dict(),
            "active_goal": workspace.active_goal,
            "last_completed_action": workspace.last_completed_action,
            "pending_next_steps": workspace.pending_next_steps,
            "where_left_off": workspace.where_left_off,
        },
    )

    left_off = service.where_we_left_off(session_id="default")
    next_steps = service.next_steps(session_id="default")

    assert "controls" in left_off["summary"].lower()
    assert "mapping layer" in left_off["summary"].lower()
    assert next_steps["next_steps"] == [
        "Reconnect the device mapping layer.",
        "Verify the follow-up routing in Ghost.",
    ]


def test_workspace_service_uses_fuzzy_workspace_matching_for_typos(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Portable packaging and release prep.",
        pending_next_steps=["Verify the archive output."],
    )
    repository.upsert_item(
        workspace.workspace_id,
        {
            "kind": "text",
            "viewer": "text",
            "title": "packaging-notes.md",
            "path": str(temp_config.project_root / "packaging-notes.md"),
            "summary": "Release checklist.",
        },
    )

    result = service.restore_workspace("open my packging workspace", session_id="default")

    assert result["workspace"]["name"] == "Packaging Workspace"
    assert result["action"]["type"] == "workspace_restore"


def test_workspace_service_returns_targeted_clarification_when_matches_are_close(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    repository.upsert_workspace(
        name="Minecraft Server Build",
        topic="minecraft",
        summary="Server setup and packaging.",
    )
    repository.upsert_workspace(
        name="Minecraft Modding Workspace",
        topic="minecraft",
        summary="Mods, configs, and reference docs.",
    )

    result = service.restore_workspace("open mc workspace", session_id="default")

    assert result["action"]["type"] == "clarify"
    assert "minecraft server build" in result["summary"].lower()
    assert "minecraft modding workspace" in result["summary"].lower()


def test_workspace_service_learns_workspace_aliases_from_successful_restore(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(
        name="Work Order Assistant",
        topic="work order",
        summary="Dispatch, packaging, and reference flow.",
    )
    repository.upsert_item(
        workspace.workspace_id,
        {
            "kind": "browser",
            "viewer": "browser",
            "title": "Dispatch Docs",
            "url": "https://example.test/work-order",
            "summary": "Primary work-order reference.",
        },
    )

    first = service.restore_workspace("bring back the work order setup", session_id="default")
    second = service.restore_workspace("open the work order thing", session_id="default")
    learned = state.resolve_alias("workspace", "work order thing")

    assert first["workspace"]["name"] == "Work Order Assistant"
    assert second["workspace"]["name"] == "Work Order Assistant"
    assert second["action"]["type"] == "workspace_restore"
    assert learned is not None
    assert learned["workspaceId"] == workspace.workspace_id


def test_workspace_service_restores_with_likely_next_bearing(temp_config) -> None:
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(
        name="Controls Project",
        topic="controls",
        summary="Reconnect the controls mapping flow.",
        active_goal="Reconnect the controls mapping layer.",
        pending_next_steps=[
            "Reconnect the device mapping layer.",
            "Verify Ghost follow-up routing.",
        ],
    )
    repository.upsert_item(
        workspace.workspace_id,
        {
            "kind": "text",
            "viewer": "text",
            "title": "controls-map.md",
            "path": str(temp_config.project_root / "controls-map.md"),
            "summary": "Primary mapping plan.",
            "role": "active",
        },
    )

    result = service.restore_workspace("restore the controls project", session_id="default")

    assert result["action"]["type"] == "workspace_restore"
    assert result["workspace"]["likelyNext"] == "Reconnect the device mapping layer."
    assert "likely next bearing" in result["summary"].lower()


def test_workspace_service_assembly_filters_repo_internal_files_for_non_stormhelm_topics(temp_project_root: Path, temp_config) -> None:
    docs_dir = temp_project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    target = docs_dir / "packaging-guide.md"
    target.write_text("Packaging guide", encoding="utf-8")

    dev_dir = temp_project_root / "src" / "stormhelm" / "packaging"
    dev_dir.mkdir(parents=True, exist_ok=True)
    (dev_dir / "runtime.py").write_text("print('packaging')", encoding="utf-8")

    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    repository = WorkspaceRepository(database)
    service = WorkspaceService(
        config=temp_config,
        repository=repository,
        notes=notes,
        conversations=conversations,
        preferences=preferences,
        session_state=ConversationStateStore(preferences),
        indexer=WorkspaceIndexer(temp_config),
        events=EventBuffer(),
        persona=PersonaContract(temp_config),
    )

    result = service.assemble_workspace("set up a workspace for packaging", session_id="default")
    paths = [str(item.get("path", "")) for item in result["items"]]

    assert any(path.endswith("packaging-guide.md") for path in paths)
    assert not any("src\\stormhelm\\packaging\\runtime.py" in path or "src/stormhelm/packaging/runtime.py" in path for path in paths)


def test_workspace_service_assembly_uses_active_workspace_for_vague_topics_and_surfaces_relevance_reason(
    temp_project_root: Path,
    temp_config,
) -> None:
    docs_dir = temp_project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    packaging = docs_dir / "packaging-checklist.md"
    packaging.write_text("Packaging checklist", encoding="utf-8")
    minecraft = docs_dir / "minecraft-server.md"
    minecraft.write_text("Minecraft server notes", encoding="utf-8")

    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Portable packaging and verification work.",
        active_goal="Verify the packaging checklist and archive contents.",
        pending_next_steps=["Open the packaging checklist."],
        tags=["release", "packaging"],
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    state.set_active_posture(
        "default",
        {
            "workspace": workspace.to_dict(),
            "active_goal": workspace.active_goal,
            "pending_next_steps": workspace.pending_next_steps,
            "where_left_off": "We were still verifying the packaging checklist.",
        },
    )

    result = service.assemble_workspace("show me the files for that thing we were doing", session_id="default")
    paths = [str(item.get("path", "")) for item in result["items"]]
    packaging_item = next(item for item in result["items"] if str(item.get("path", "")).endswith("packaging-checklist.md"))

    assert result["workspace"]["topic"] == "packaging"
    assert any(path.endswith("packaging-checklist.md") for path in paths)
    assert not any(path.endswith("minecraft-server.md") for path in paths)
    assert "packaging" in str(packaging_item.get("summary", "")).lower()


def test_workspace_service_applies_research_template_and_distinct_surface_clusters(
    temp_project_root: Path,
    temp_config,
) -> None:
    docs_dir = temp_project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    notes_path = docs_dir / "motor-torque-notes.md"
    notes_path.write_text("Motor torque notes", encoding="utf-8")
    spec_path = docs_dir / "torque-reference.txt"
    spec_path.write_text("Reference material for torque", encoding="utf-8")

    internal_dir = temp_project_root / "src" / "stormhelm" / "research"
    internal_dir.mkdir(parents=True, exist_ok=True)
    (internal_dir / "runtime.py").write_text("print('internal')", encoding="utf-8")

    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    conversations = ConversationRepository(database)
    notes = NotesRepository(database)
    preferences = PreferencesRepository(database)
    repository = WorkspaceRepository(database)
    service = WorkspaceService(
        config=temp_config,
        repository=repository,
        notes=notes,
        conversations=conversations,
        preferences=preferences,
        session_state=ConversationStateStore(preferences),
        indexer=WorkspaceIndexer(temp_config),
        events=EventBuffer(),
        persona=PersonaContract(temp_config),
    )

    result = service.assemble_workspace("create a research workspace for motor torque", session_id="default")
    surface_content = result["workspace"]["surfaceContent"]
    reference_titles = [item["title"] for item in surface_content["references"]["items"]]
    file_titles = [item["title"] for item in surface_content["files"]["items"]]

    assert result["workspace"]["templateKey"] == "research"
    assert result["workspace"]["templateSource"] == "explicit"
    assert result["action"]["module"] == "browser"
    assert result["action"]["section"] == "references"
    assert result["action"]["bearing_title"] == "Research workspace created"
    assert surface_content["references"]["presentationKind"] == "collection"
    assert surface_content["findings"]["presentationKind"] == "highlights"
    assert surface_content["session"]["presentationKind"] == "panels"
    assert surface_content["tasks"]["presentationKind"] == "task-groups"
    assert "motor-torque-notes.md" in reference_titles
    assert "runtime.py" not in file_titles
    assert surface_content["references"]["items"][0]["whyIncluded"]
    assert result["debug"]["template"]["key"] == "research"
    assert result["debug"]["template"]["source"] == "explicit"


def test_workspace_service_restore_uses_saved_posture_over_template_defaults_and_restores_continuity(
    temp_project_root: Path,
    temp_config,
) -> None:
    diagnostics = temp_project_root / "docs" / "wifi-diagnostics.md"
    diagnostics.parent.mkdir(parents=True, exist_ok=True)
    diagnostics.write_text("Wi-Fi diagnostics", encoding="utf-8")

    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(
        name="Wi-Fi Triage",
        topic="wifi diagnostics",
        summary="Investigate intermittent Wi-Fi drops.",
        category="troubleshooting",
        active_goal="Stabilize the local Wi-Fi connection.",
        current_task_state="Investigate packet loss and gateway latency spikes.",
        last_completed_action="Captured the latest Wi-Fi diagnostics snapshot.",
        pending_next_steps=[
            "Compare the gateway and external probe latency.",
            "Check whether the adapter driver changed recently.",
        ],
        where_left_off="We captured the latest Wi-Fi diagnostics and still need to compare gateway and external latency.",
        template_key="troubleshooting",
        template_source="explicit",
        problem_domain="network",
        last_surface_mode="deck",
        last_active_module="systems",
        last_active_section="diagnostics",
    )
    repository.upsert_item(
        workspace.workspace_id,
        {
            "itemId": "item-diagnostics",
            "kind": "markdown",
            "viewer": "markdown",
            "title": "wifi-diagnostics.md",
            "path": str(diagnostics),
            "summary": "Recent Wi-Fi diagnostic log.",
            "role": "active",
            "module": "systems",
            "section": "diagnostics",
        },
    )
    repository.save_snapshot(
        workspace_id=workspace.workspace_id,
        session_id="default",
        summary=workspace.where_left_off,
        payload={
            "workspace": workspace.to_dict(),
            "surface_mode": "deck",
            "active_module": "systems",
            "section": "diagnostics",
            "active_goal": workspace.active_goal,
            "current_task_state": workspace.current_task_state,
            "last_completed_action": workspace.last_completed_action,
            "pending_next_steps": workspace.pending_next_steps,
            "where_left_off": workspace.where_left_off,
            "problem_domain": "network",
            "opened_items": [
                {
                    "itemId": "item-diagnostics",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "wifi-diagnostics.md",
                    "path": str(diagnostics),
                    "summary": "Recent Wi-Fi diagnostic log.",
                    "role": "active",
                    "module": "systems",
                    "section": "diagnostics",
                }
            ],
            "active_item": {
                "itemId": "item-diagnostics",
                "kind": "markdown",
                "viewer": "markdown",
                "title": "wifi-diagnostics.md",
                "path": str(diagnostics),
                "summary": "Recent Wi-Fi diagnostic log.",
                "role": "active",
                "module": "systems",
                "section": "diagnostics",
            },
            "surface_content": {
                "tasks": {
                    "presentationKind": "task-groups",
                    "items": [
                        {
                            "title": "Next Bearings",
                            "entries": [
                                {
                                    "title": "Compare the gateway and external probe latency.",
                                    "status": "priority",
                                    "detail": "Continue the Wi-Fi diagnosis.",
                                }
                            ],
                        }
                    ],
                }
            },
        },
    )

    result = service.restore_workspace("continue where I left off", session_id="default")

    assert result["action"]["module"] == "systems"
    assert result["action"]["section"] == "diagnostics"
    assert result["workspace"]["templateKey"] == "troubleshooting"
    assert result["workspace"]["continuity"]["problemDomain"] == "network"
    assert result["workspace"]["resumeContext"]["source"] == "saved_snapshot"
    assert result["workspace"]["resumeContext"]["usedSavedPosture"] is True
    assert result["workspace"]["capabilities"]["restore_saved_posture"] is True
    assert result["workspace"]["sessionPosture"]["activeModule"] == "systems"


def test_workspace_service_surface_content_keeps_roles_materially_distinct(temp_project_root: Path, temp_config) -> None:
    readme = temp_project_root / "README.md"
    readme.write_text("Workspace readme", encoding="utf-8")

    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
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

    workspace = repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Prepare the portable packaging release.",
        category="project-planning",
        active_goal="Finalize portable packaging verification.",
        last_completed_action="Restored the portable packaging bearings.",
        pending_next_steps=[
            "Verify the portable archive contents.",
            "Check first-run behavior after extraction.",
        ],
        references=[
            {
                "title": "PyInstaller Docs",
                "url": "https://pyinstaller.org/",
                "summary": "Primary packaging reference.",
            }
        ],
        findings=[
            {
                "title": "Archive contents still need verification",
                "summary": "The build completed, but the extracted archive has not been checked yet.",
                "source": "Workspace",
            }
        ],
        session_notes=[
            {
                "title": "Packaging handoff note",
                "content": "Portable verification still needs a first-run pass.",
            }
        ],
        where_left_off="We restored packaging bearings and still need to verify the archive contents.",
        template_key="project-planning",
        template_source="explicit",
    )
    state.set_active_workspace_id("default", workspace.workspace_id)
    service.capture_workspace_context(
        session_id="default",
        prompt="continue the packaging workspace",
        surface_mode="deck",
        active_module="files",
        workspace_context={
            "workspace": workspace.to_dict(),
            "section": "opened-items",
            "opened_items": [
                {
                    "itemId": "item-readme",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "README.md",
                    "path": str(readme),
                    "summary": "Primary packaging checklist.",
                    "role": "active",
                }
            ],
            "active_item": {
                "itemId": "item-readme",
                "kind": "markdown",
                "viewer": "markdown",
                "title": "README.md",
                "path": str(readme),
                "summary": "Primary packaging checklist.",
                "role": "active",
            },
        },
    )

    summary = service.active_workspace_summary("default")
    surface_content = summary["workspace"]["surfaceContent"]

    assert surface_content["opened-items"]["purpose"] == "What is actively in use right now?"
    assert surface_content["references"]["purpose"] == "What supports this work?"
    assert surface_content["findings"]["purpose"] == "What have we learned or confirmed?"
    assert surface_content["session"]["purpose"] == "What is the current work session about?"
    assert surface_content["tasks"]["purpose"] == "What still needs doing?"
    assert surface_content["files"]["purpose"] == "What concrete file assets matter here?"
    assert surface_content["logbook"]["purpose"] == "What has been recorded or remembered?"
    assert surface_content["opened-items"]["items"][0]["title"] == "README.md"
    assert surface_content["references"]["items"][0]["title"] == "PyInstaller Docs"
    assert surface_content["findings"]["items"][0]["title"] == "Archive contents still need verification"
    assert surface_content["logbook"]["items"][0]["title"] == "Packaging handoff note"
