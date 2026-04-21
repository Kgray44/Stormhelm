from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stormhelm.core.events import EventBuffer
from stormhelm.core.safety.policy import SafetyPolicy
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.tools.builtins.long_tail_power import (
    FileOperationTool,
    MaintenanceActionTool,
    RoutineExecuteTool,
    RoutineSaveTool,
    TrustedHookExecuteTool,
    TrustedHookRegisterTool,
)


class _DummyNotesRepository:
    def create_note(self, title: str, content: str):  # pragma: no cover - not used here
        return {"title": title, "content": content}


class _DummyPreferencesRepository:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_all(self) -> dict[str, object]:
        return dict(self.values)

    def set_preference(self, key: str, value: object) -> None:
        self.values[key] = value


def _context(temp_config) -> ToolContext:
    return ToolContext(
        job_id="long-tail-test",
        config=temp_config,
        events=EventBuffer(),
        notes=_DummyNotesRepository(),
        preferences=_DummyPreferencesRepository(),
        safety_policy=SafetyPolicy(temp_config),
    )


def _set_file_age(path: Path, *, days_old: int, hour: int = 9, minute: int = 0) -> None:
    dt = datetime.now(timezone.utc).replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(days=days_old)
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


def test_file_operation_dry_run_previews_date_based_rename_without_mutating_files(temp_config, workspace_temp_dir: Path) -> None:
    screenshots_dir = workspace_temp_dir / "Screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    first = screenshots_dir / "Screenshot 1.png"
    second = screenshots_dir / "Screenshot 2.png"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    _set_file_age(first, days_old=12, hour=8, minute=30)
    _set_file_age(second, days_old=11, hour=14, minute=45)

    result = asyncio.run(
        FileOperationTool().execute(
            _context(temp_config),
            {
                "operation": "rename_by_date",
                "source_paths": [str(first), str(second)],
                "dry_run": True,
            },
        )
    )

    assert result.success is True
    assert result.data["file_operation"]["dry_run"] is True
    assert len(result.data["file_operation"]["preview"]) == 2
    assert Path(result.data["file_operation"]["preview"][0]["destination_path"]).name.startswith("20")
    assert first.exists()
    assert second.exists()


def test_maintenance_action_downloads_cleanup_moves_old_installer_clutter_and_reports_counts(
    temp_config,
    workspace_temp_dir: Path,
) -> None:
    downloads_dir = workspace_temp_dir / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    old_installer = downloads_dir / "gpu-driver.exe"
    keep_note = downloads_dir / "notes.txt"
    keep_recent = downloads_dir / "fresh-tool.zip"
    old_installer.write_text("binary", encoding="utf-8")
    keep_note.write_text("notes", encoding="utf-8")
    keep_recent.write_text("zip", encoding="utf-8")
    _set_file_age(old_installer, days_old=14)
    _set_file_age(keep_note, days_old=14)
    _set_file_age(keep_recent, days_old=0)

    result = asyncio.run(
        MaintenanceActionTool().execute(
            _context(temp_config),
            {
                "maintenance_kind": "downloads_cleanup",
                "target_directory": str(downloads_dir),
                "older_than_days": 7,
                "dry_run": True,
                "session_id": "default",
            },
        )
    )

    assert result.success is True
    preview = result.data["maintenance"]["preview"]
    assert any(item["destination_path"].endswith("gpu-driver.exe") for item in preview)
    assert old_installer.exists()
    assert keep_note.exists()
    assert keep_recent.exists()
    assert result.data["workflow"]["item_progress"]["total"] == 1


def test_routine_save_and_execute_persists_saved_routine(temp_config, workspace_temp_dir: Path) -> None:
    downloads_dir = workspace_temp_dir / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    old_installer = downloads_dir / "chipset-driver.msi"
    old_installer.write_text("binary", encoding="utf-8")
    _set_file_age(old_installer, days_old=9)
    context = _context(temp_config)

    save_result = asyncio.run(
        RoutineSaveTool().execute(
            context,
            {
                "routine_name": "cleanup routine",
                "execution_kind": "maintenance",
                    "parameters": {
                        "maintenance_kind": "downloads_cleanup",
                        "target_directory": str(downloads_dir),
                        "older_than_days": 7,
                        "dry_run": True,
                    },
                "description": "Weekly Downloads cleanup.",
                "session_id": "default",
            },
        )
    )

    run_result = asyncio.run(
        RoutineExecuteTool().execute(
            _context(temp_config),
            {
                "routine_name": "cleanup routine",
                "session_id": "default",
            },
        )
    )

    assert save_result.success is True
    assert run_result.success is True
    assert run_result.data["routine"]["source_type"] == "saved"
    assert run_result.data["maintenance"]["preview"][0]["destination_path"].endswith("chipset-driver.msi")
    assert old_installer.exists()
    assert run_result.data["workflow"]["status"] == "completed"


def test_trusted_hook_register_and_execute_runs_custom_script(temp_config, workspace_temp_dir: Path) -> None:
    hook_script = workspace_temp_dir / "collect-logs.cmd"
    marker = workspace_temp_dir / "hook-output.txt"
    hook_script.write_text(f'@echo off\r\necho hook-ran> "{marker}"\r\n', encoding="utf-8")
    register_context = _context(temp_config)

    register_result = asyncio.run(
        TrustedHookRegisterTool().execute(
            register_context,
            {
                "hook_name": "project log collector",
                "command_path": str(hook_script),
                "arguments": [],
                "working_directory": str(workspace_temp_dir),
                "description": "Collect the local project logs.",
            },
        )
    )

    execute_result = asyncio.run(
        TrustedHookExecuteTool().execute(
            _context(temp_config),
            {
                "hook_name": "project log collector",
                "session_id": "default",
            },
        )
    )

    assert register_result.success is True
    assert execute_result.success is True
    assert marker.exists()
    assert execute_result.data["hook"]["source_type"] == "custom"
