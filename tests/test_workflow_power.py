from __future__ import annotations

import asyncio
from pathlib import Path

from stormhelm.core.events import EventBuffer
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins.workflow_power import DesktopSearchTool, RepairActionTool, WorkflowExecuteTool


class _DummyNotesRepository:
    def create_note(self, title: str, content: str):  # pragma: no cover - not used in this test
        return {"title": title, "content": content}


class _DummyPreferencesRepository:
    def get_all(self) -> dict[str, object]:
        return {}

    def set_preference(self, key: str, value: object) -> None:  # pragma: no cover - not used in this test
        return None


class _FakeIndexer:
    def search_files(self, query: str, limit: int = 8) -> list[dict[str, object]]:
        del query, limit
        return [
            {
                "title": "motor-torque.pdf",
                "path": "C:\\Stormhelm\\docs\\motor-torque.pdf",
                "url": "file:///C:/Stormhelm/docs/motor-torque.pdf",
                "kind": "pdf",
                "viewer": "pdf",
                "score": 0.96,
                "summary": "Latest matching PDF.",
                "metadata": {"reasons": ["Matched file type", "Most recent candidate"]},
            }
        ]


class _FakeWorkspaceService:
    def __init__(self) -> None:
        self.indexer = _FakeIndexer()

    def assemble_workspace(self, query: str, *, session_id: str) -> dict[str, object]:
        del session_id
        return {
            "summary": f"Assembled workspace for {query}.",
            "workspace": {"workspaceId": "ws-writing", "name": "Writing Workspace", "topic": "writing"},
            "items": [
                {
                    "itemId": "item-1",
                    "kind": "markdown",
                    "viewer": "markdown",
                    "title": "draft.md",
                    "subtitle": "Draft",
                    "module": "files",
                    "section": "opened-items",
                    "path": "C:\\Stormhelm\\draft.md",
                    "url": "file:///C:/Stormhelm/draft.md",
                }
            ],
            "likely_next": "Continue the draft",
        }

    def restore_workspace(self, query: str, *, session_id: str) -> dict[str, object]:
        del query, session_id
        return {
            "summary": "Restored the active workspace.",
            "workspace": {"workspaceId": "ws-current", "name": "Current Workspace", "topic": "current work"},
            "items": [],
            "likely_next": "Resume the active task",
        }


class _FakeSystemProbe:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def active_apps(self) -> dict[str, object]:
        return {
            "applications": [
                {
                    "process_name": "code",
                    "window_title": "Stormhelm - Visual Studio Code",
                    "window_handle": 100,
                    "pid": 4321,
                    "path": "C:\\Program Files\\Microsoft VS Code\\Code.exe",
                }
            ]
        }

    def recent_files(self, limit: int = 12) -> dict[str, object]:
        del limit
        return {
            "files": [
                {
                    "path": "C:\\Stormhelm\\docs\\motor-torque.pdf",
                    "name": "motor-torque.pdf",
                    "modified_at": "2026-04-20T10:00:00+00:00",
                    "size_bytes": 2048,
                }
            ]
        }

    def window_status(self) -> dict[str, object]:
        return {
            "focused_window": {"window_title": "Stormhelm - Visual Studio Code", "process_name": "code", "window_handle": 100},
            "windows": [
                {"window_title": "Stormhelm - Visual Studio Code", "process_name": "code", "window_handle": 100, "pid": 4321}
            ],
            "monitors": [{"index": 1}],
        }

    def app_control(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("app_control", dict(kwargs)))
        return {"success": True, **kwargs}

    def window_control(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("window_control", dict(kwargs)))
        return {"success": True, **kwargs}

    def network_diagnosis(self, *, focus: str = "overview", diagnostic_burst: bool = False) -> dict[str, object]:
        self.calls.append(("network_diagnosis", {"focus": focus, "diagnostic_burst": diagnostic_burst}))
        return {
            "assessment": {
                "headline": "Local Wi-Fi instability likely",
                "summary": "Gateway jitter and loss bursts suggest a local link problem.",
                "confidence": "moderate",
            }
        }

    def flush_dns_cache(self) -> dict[str, object]:
        self.calls.append(("flush_dns_cache", {}))
        return {"success": True, "action": "flush_dns"}

    def restart_network_adapter(self) -> dict[str, object]:
        self.calls.append(("restart_network_adapter", {}))
        return {"success": False, "action": "restart_network_adapter", "reason": "unsupported"}

    def restart_explorer_shell(self) -> dict[str, object]:
        self.calls.append(("restart_explorer_shell", {}))
        return {"success": True, "action": "restart_explorer_shell"}

    def control_capabilities(self) -> dict[str, object]:
        return {
            "search": {
                "workspace_files": True,
                "recent_files": True,
                "apps": True,
                "windows": True,
                "browser_tabs": False,
                "notes": False,
            },
            "repair": {
                "connectivity_checks": True,
                "flush_dns": True,
                "restart_network_adapter": False,
                "restart_explorer": True,
                "relaunch_app": True,
            },
        }


def _context(temp_config) -> ToolContext:
    return ToolContext(
        job_id="workflow-test",
        config=temp_config,
        events=EventBuffer(),
        notes=_DummyNotesRepository(),
        preferences=_DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
        system_probe=_FakeSystemProbe(),
        workspace_service=_FakeWorkspaceService(),
    )


def _folder_context(temp_config) -> ToolContext:
    return ToolContext(
        job_id="workflow-folder-test",
        config=temp_config,
        events=EventBuffer(),
        notes=_DummyNotesRepository(),
        preferences=_DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
        system_probe=None,
        workspace_service=None,
    )


def test_desktop_search_can_find_latest_pdf_and_prepare_open_action(temp_config) -> None:
    context = _context(temp_config)
    tool = DesktopSearchTool()

    result = asyncio.run(
        tool.execute(
            context,
            {
                "query": "latest pdf",
                "domains": ["files"],
                "action": "open",
                "open_target": "deck",
                "latest_only": True,
                "file_extensions": [".pdf"],
                "session_id": "default",
            },
        )
    )

    assert result.success is True
    assert result.data["search"]["results"][0]["title"] == "motor-torque.pdf"
    assert result.data["actions"][0]["type"] == "workspace_open"


def test_desktop_search_resolves_documents_folder_and_opens_best_match(monkeypatch, temp_config, workspace_temp_dir: Path) -> None:
    home = workspace_temp_dir / "home"
    documents = home / "Documents"
    documents.mkdir(parents=True, exist_ok=True)
    target = documents / "Stormhelm Docs.pdf"
    target.write_bytes(b"%PDF-1.7\n")

    monkeypatch.setattr("stormhelm.core.workflows.service.Path.home", lambda: home)
    temp_config.safety.allowed_read_dirs = [documents.resolve()]
    context = _folder_context(temp_config)
    tool = DesktopSearchTool()

    result = asyncio.run(
        tool.execute(
            context,
            {
                "query": "the Stormhelm docs in Documents",
                "domains": ["files"],
                "action": "open",
                "open_target": "external",
                "folder_hint": "Documents",
                "prefer_folders": False,
                "session_id": "default",
            },
        )
    )

    assert result.success is True
    assert result.data["search"]["known_folder"]["label"] == "Documents"
    assert result.data["search"]["access_status"]["state"] == "resolved_and_accessible"
    assert result.data["search"]["decision"]["state"] == "accessible_single_strong_match"
    assert result.data["search"]["decision"]["chosen_candidate"]["path"] == str(target.resolve())
    assert result.data["actions"][0]["type"] == "open_external"
    assert result.data["actions"][0]["path"] == str(target.resolve())


def test_desktop_search_reports_inaccessible_known_folder_precisely(monkeypatch, temp_config, workspace_temp_dir: Path) -> None:
    home = workspace_temp_dir / "home"
    documents = home / "Documents"
    documents.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("stormhelm.core.workflows.service.Path.home", lambda: home)
    temp_config.safety.allowed_read_dirs = [temp_config.project_root.resolve()]
    context = _folder_context(temp_config)
    tool = DesktopSearchTool()

    result = asyncio.run(
        tool.execute(
            context,
            {
                "query": "Stormhelm docs in Documents",
                "domains": ["files"],
                "action": "open",
                "open_target": "external",
                "folder_hint": "Documents",
                "prefer_folders": False,
                "session_id": "default",
            },
        )
    )

    assert result.success is False
    assert result.error == "folder_inaccessible"
    assert result.summary == "Documents isn't accessible from the current execution scope."
    assert result.data["search"]["access_status"]["state"] == "resolved_but_inaccessible"
    assert result.data["action"]["bearing_title"] == "Documents inaccessible"


def test_desktop_search_reports_no_strong_match_after_searching_folder(monkeypatch, temp_config, workspace_temp_dir: Path) -> None:
    home = workspace_temp_dir / "home"
    documents = home / "Documents"
    documents.mkdir(parents=True, exist_ok=True)
    (documents / "budget.xlsx").write_text("spreadsheet", encoding="utf-8")

    monkeypatch.setattr("stormhelm.core.workflows.service.Path.home", lambda: home)
    temp_config.safety.allowed_read_dirs = [documents.resolve()]
    context = _folder_context(temp_config)
    tool = DesktopSearchTool()

    result = asyncio.run(
        tool.execute(
            context,
            {
                "query": "Stormhelm docs in Documents",
                "domains": ["files"],
                "action": "open",
                "open_target": "external",
                "folder_hint": "Documents",
                "prefer_folders": False,
                "session_id": "default",
            },
        )
    )

    assert result.success is False
    assert result.error == "no_strong_folder_match"
    assert result.summary == "I searched Documents but found no strong match for Stormhelm docs."
    assert result.data["search"]["decision"]["state"] == "accessible_no_strong_match"
    assert result.data["action"]["bearing_title"] == "No strong match"


def test_desktop_search_reports_multiple_strong_matches_with_brief_clarification(monkeypatch, temp_config, workspace_temp_dir: Path) -> None:
    home = workspace_temp_dir / "home"
    documents = home / "Documents"
    documents.mkdir(parents=True, exist_ok=True)
    (documents / "Stormhelm Docs.pdf").write_bytes(b"%PDF-1.7\n")
    (documents / "Stormhelm Documentation.docx").write_text("docx placeholder", encoding="utf-8")

    monkeypatch.setattr("stormhelm.core.workflows.service.Path.home", lambda: home)
    temp_config.safety.allowed_read_dirs = [documents.resolve()]
    context = _folder_context(temp_config)
    tool = DesktopSearchTool()

    result = asyncio.run(
        tool.execute(
            context,
            {
                "query": "Stormhelm docs in Documents",
                "domains": ["files"],
                "action": "open",
                "open_target": "external",
                "folder_hint": "Documents",
                "prefer_folders": False,
                "session_id": "default",
            },
        )
    )

    assert result.success is False
    assert result.error == "multiple_strong_folder_matches"
    assert result.data["search"]["decision"]["state"] == "accessible_multiple_strong_matches"
    assert "Stormhelm Docs.pdf" in result.summary
    assert "Stormhelm Documentation.docx" in result.summary
    assert result.data["action"]["bearing_title"] == "Need file clarified"


def test_desktop_search_prefers_folder_matches_when_request_is_folder_oriented(monkeypatch, temp_config, workspace_temp_dir: Path) -> None:
    home = workspace_temp_dir / "home"
    pictures = home / "Pictures"
    screenshots = pictures / "Screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    (pictures / "screenshots.png").write_bytes(b"image")

    monkeypatch.setattr("stormhelm.core.workflows.service.Path.home", lambda: home)
    temp_config.safety.allowed_read_dirs = [pictures.resolve()]
    context = _folder_context(temp_config)
    tool = DesktopSearchTool()

    result = asyncio.run(
        tool.execute(
            context,
            {
                "query": "the screenshots folder in Pictures",
                "domains": ["files"],
                "action": "open",
                "open_target": "external",
                "folder_hint": "Pictures",
                "prefer_folders": True,
                "session_id": "default",
            },
        )
    )

    assert result.success is True
    assert result.data["search"]["decision"]["chosen_candidate"]["is_dir"] is True
    assert result.data["search"]["decision"]["chosen_candidate"]["path"] == str(screenshots.resolve())
    assert result.data["actions"][0]["type"] == "open_external"
    assert result.data["actions"][0]["path"] == str(screenshots.resolve())


def test_repair_action_runs_supported_steps_and_reports_partial_completion(temp_config) -> None:
    context = _context(temp_config)
    tool = RepairActionTool()

    result = asyncio.run(
        tool.execute(
            context,
            {
                "repair_kind": "network_repair",
                "target": "wi-fi",
                "session_id": "default",
            },
        )
    )

    assert result.success is True
    assert result.data["workflow"]["partial"] is True
    assert result.data["workflow"]["steps"][0]["status"] == "completed"
    assert result.data["workflow"]["steps"][-1]["status"] == "failed"


def test_workflow_execute_builds_structured_writing_setup(temp_config) -> None:
    context = _context(temp_config)
    progress_updates: list[dict[str, object]] = []
    context.progress_callback = progress_updates.append
    tool = WorkflowExecuteTool()

    result = asyncio.run(
        tool.execute(
            context,
            {
                "workflow_kind": "writing_setup",
                "query": "set up my writing environment",
                "session_id": "default",
            },
        )
    )

    assert result.success is True
    assert result.data["workflow"]["kind"] == "writing_setup"
    assert result.data["workflow"]["steps"][0]["status"] == "completed"
    assert result.data["actions"][0]["type"] == "workspace_focus"
    assert progress_updates
