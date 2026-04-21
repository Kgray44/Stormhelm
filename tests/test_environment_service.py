from __future__ import annotations

from pathlib import Path

from stormhelm.core.context.service import ActiveContextService
from stormhelm.core.environment.service import EnvironmentIntelligenceService
from stormhelm.core.events import EventBuffer
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import ConversationRepository, NotesRepository, PreferencesRepository
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository
from stormhelm.core.workspace.service import WorkspaceService


class FakeBrowserProbe:
    def __init__(self) -> None:
        self.focus_requests: list[str] = []

    def control_capabilities(self) -> dict[str, object]:
        return {
            "search": {
                "browser_tabs": False,
                "windows": True,
                "recent_files": True,
                "workspace_files": True,
            },
            "window": {
                "focus": True,
            },
        }

    def window_status(self) -> dict[str, object]:
        focused = {
            "process_name": "chrome",
            "window_title": "PyInstaller Docs - Google Chrome",
            "window_handle": 401,
            "pid": 1440,
            "monitor_index": 1,
            "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "is_focused": True,
            "minimized": False,
        }
        windows = [
            focused,
            {
                "process_name": "msedge",
                "window_title": "Packet Loss Guide - Microsoft Edge",
                "window_handle": 402,
                "pid": 1550,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
                "is_focused": False,
                "minimized": False,
            },
            {
                "process_name": "code",
                "window_title": "Stormhelm - Visual Studio Code",
                "window_handle": 403,
                "pid": 1660,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Microsoft VS Code\\Code.exe",
                "is_focused": False,
                "minimized": False,
            },
        ]
        return {
            "focused_window": focused,
            "windows": windows,
            "monitors": [{"index": 1, "device_name": "\\\\.\\DISPLAY1", "is_primary": True}],
        }

    def window_control(self, *, action: str, app_name: str | None = None, target_mode: str | None = None, **_: object) -> dict[str, object]:
        self.focus_requests.append(str(app_name or ""))
        return {
            "success": True,
            "action": action,
            "process_name": "msedge",
            "window_title": str(app_name or ""),
            "target_mode": target_mode,
        }

    def machine_status(self) -> dict[str, object]:
        return {"machine_name": "Stormhelm-Test", "platform": "Windows-Test", "timezone": "America/New_York"}

    def power_status(self) -> dict[str, object]:
        return {
            "available": True,
            "ac_line_status": "offline",
            "battery_percent": 54,
            "seconds_remaining": 7200,
            "power_source": "battery",
        }

    def resource_status(self) -> dict[str, object]:
        return {
            "cpu": {"logical_processors": 16},
            "memory": {"total_bytes": 32 * 1024**3, "used_bytes": 12 * 1024**3, "free_bytes": 20 * 1024**3},
            "gpu": [{"name": "Test GPU"}],
        }

    def storage_status(self) -> dict[str, object]:
        return {"drives": [{"drive": "C:\\", "total_bytes": 400 * 1024**3, "free_bytes": 140 * 1024**3}]}

    def network_status(self) -> dict[str, object]:
        return {
            "assessment": {
                "kind": "stable",
                "headline": "Stable",
                "summary": "No strong network issue is visible.",
                "confidence": "moderate",
            }
        }

    def resolve_location(self, *, mode: str = "auto", allow_home_fallback: bool = True) -> dict[str, object]:
        del mode, allow_home_fallback
        return {
            "resolved": True,
            "source": "approximate",
            "label": "Queens, New York",
            "latitude": 40.7282,
            "longitude": -73.7949,
            "timezone": "America/New_York",
            "approximate": True,
        }


def _build_workspace_service(temp_config) -> tuple[WorkspaceService, ConversationStateStore, WorkspaceRepository, PreferencesRepository]:
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
    return service, state, repository, preferences


def test_environment_service_finds_matching_browser_context_and_reuses_existing_window(temp_config) -> None:
    workspace_service, state, _, _ = _build_workspace_service(temp_config)
    probe = FakeBrowserProbe()
    service = EnvironmentIntelligenceService(
        config=temp_config,
        session_state=state,
        workspace_service=workspace_service,
        system_probe=probe,
        events=EventBuffer(),
    )

    result = service.handle_browser_request(
        operation="find",
        query="bring up the page about packet loss",
        session_id="default",
    )

    assert result["match"]["title"] == "Packet Loss Guide"
    assert probe.focus_requests
    assert "packet loss guide" in probe.focus_requests[-1].lower()
    assert result["browserContext"]["reuseDecision"]["reusedExisting"] is True


def test_environment_service_adds_current_browser_page_to_workspace_references_with_reasons(temp_config) -> None:
    workspace_service, state, repository, preferences = _build_workspace_service(temp_config)
    workspace = repository.upsert_workspace(
        name="Packaging Workspace",
        topic="packaging",
        summary="Portable packaging and release work.",
        active_goal="Finish the packaging pass.",
    )
    workspace_service.capture_workspace_context(
        session_id="default",
        prompt="Continue the packaging work.",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={
            "workspace": workspace.to_dict(),
            "module": "chartroom",
            "section": "session",
            "opened_items": [],
            "active_item": {},
        },
    )
    ActiveContextService(state).update_from_turn(
        session_id="default",
        workspace_context=workspace_service.active_workspace_summary("default"),
        active_posture=state.get_active_posture("default"),
        active_request_state={},
        recent_tool_results=[],
        input_context={},
    )
    probe = FakeBrowserProbe()
    service = EnvironmentIntelligenceService(
        config=temp_config,
        session_state=state,
        workspace_service=workspace_service,
        system_probe=probe,
        events=EventBuffer(),
    )

    result = service.handle_browser_request(
        operation="add_to_workspace",
        query="add this page to the workspace",
        session_id="default",
    )
    active_workspace = workspace_service.active_workspace_summary("default")
    references = active_workspace["workspace"]["surfaceContent"]["references"]["items"]

    assert result["action"]["type"] == "workspace_restore"
    assert any(item.get("title") == "PyInstaller Docs" for item in references)
    added = next(item for item in references if item.get("title") == "PyInstaller Docs")
    reasons = added.get("inclusionReasons", [])
    assert any(reason.get("code") == "active_browser_context" for reason in reasons)
    assert any(reason.get("code") == "active_workspace_match" for reason in reasons)


def test_environment_service_summarizes_recent_activity_with_priority_bands_and_noise_suppression(temp_config) -> None:
    workspace_service, state, _, _ = _build_workspace_service(temp_config)
    events = EventBuffer()
    probe = FakeBrowserProbe()
    service = EnvironmentIntelligenceService(
        config=temp_config,
        session_state=state,
        workspace_service=workspace_service,
        system_probe=probe,
        events=events,
    )

    events.publish(
        level="WARNING",
        source="job_manager",
        message="Job repair-1 finished with status 'failed'.",
        payload={"job_id": "repair-1", "status": "failed", "tool_name": "repair_action", "error": "adapter_not_found"},
    )
    events.publish(
        level="INFO",
        source="job_manager",
        message="Job workflow-1 finished with status 'completed'.",
        payload={
            "job_id": "workflow-1",
            "status": "completed",
            "tool_name": "workflow_execute",
            "result_summary": "Diagnostics setup completed.",
        },
    )
    events.publish(
        level="INFO",
        source="job_manager",
        message="Queued job clock-1 for tool 'clock'.",
        payload={"job_id": "clock-1", "tool_name": "clock"},
    )

    result = service.summarize_recent_activity(session_id="default", query="what did I miss?")

    assert result["activitySummary"]["highPriority"]
    assert result["activitySummary"]["summaryWorthy"]
    assert result["activitySummary"]["suppressedCount"] >= 1
    assert "failed" in result["summary"].lower()
