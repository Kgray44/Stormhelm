from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from stormhelm.core.intelligence.language import fuzzy_ratio, normalize_lookup_phrase, normalize_phrase
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.power.models import RecipeDefinition, RoutineDefinition, TrustedHookDefinition
from stormhelm.core.power.store import PowerRegistryStore
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.workflows.service import WorkflowPowerService
from stormhelm.shared.result import ToolResult


DOWNLOAD_CLUTTER_EXTENSIONS = {".exe", ".msi", ".zip", ".rar", ".7z", ".iso", ".cab"}
SCREENSHOT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
TRUSTED_HOOK_EXTENSIONS = {".bat", ".cmd", ".ps1", ".py", ".exe"}


class LongTailPowerService:
    def __init__(self, context: ToolContext) -> None:
        self.context = context
        self.persona = PersonaContract(context.config)
        self.workflow_service = WorkflowPowerService(context)
        self.registry = PowerRegistryStore(context.config)

    def capabilities(self) -> dict[str, object]:
        return {
            "saved_routines": True,
            "scheduled_routines": False,
            "trusted_hooks": True,
            "script_hooks": True,
            "batch_file_rename": True,
            "batch_file_move": True,
            "batch_file_copy": True,
            "archive_operations": True,
            "duplicate_detection": True,
            "dry_run_preview": True,
            "maintenance_cleanup": True,
            "watch_progress": True,
        }

    def save_routine(
        self,
        *,
        routine_name: str,
        execution_kind: str,
        parameters: dict[str, Any],
        description: str,
        session_id: str,
    ) -> ToolResult:
        del session_id
        name = self._normalized_title(routine_name)
        if not name:
            return ToolResult(success=False, summary="Routine name is required.", error="missing_routine_name")
        kind = str(execution_kind or "").strip().lower()
        if kind not in {"workflow", "repair", "maintenance", "file_operation", "maintenance_recipe", "trusted_hook"}:
            return ToolResult(success=False, summary="That routine type is not available here yet.", error="unsupported_routine_kind")
        definition = RoutineDefinition(
            name=name,
            title=name.title(),
            description=str(description or "").strip() or f"Reusable {kind.replace('_', ' ')} routine.",
            execution_kind=kind,
            parameters=dict(parameters or {}),
            metadata={"saved_at": datetime.now(timezone.utc).isoformat()},
        )
        self.registry.save_routine(definition)
        return ToolResult(
            success=True,
            summary=f"Saved {name}.",
            data={"routine": definition.to_dict(), "capabilities": self.capabilities()},
        )

    def execute_routine(self, *, routine_name: str, session_id: str) -> ToolResult:
        saved = self.registry.get_routine(routine_name)
        recipe = self._resolve_recipe(routine_name) if saved is None else None
        if saved is None and recipe is None:
            return ToolResult(success=False, summary="That routine is not available here.", error="unknown_routine")
        if saved is not None:
            result = self._dispatch_execution(
                execution_kind=saved.execution_kind,
                parameters=saved.parameters,
                session_id=session_id,
            )
            result.data["routine"] = saved.to_dict()
            result.data["capabilities"] = self.capabilities()
            return result
        assert recipe is not None
        result = self._dispatch_execution(
            execution_kind=recipe.execution_kind,
            parameters=recipe.parameters,
            session_id=session_id,
        )
        result.data["routine"] = {
            "name": recipe.name,
            "title": recipe.title,
            "description": recipe.description,
            "execution_kind": recipe.execution_kind,
            "parameters": dict(recipe.parameters),
            "source_type": recipe.source_type,
            "guardrail": recipe.guardrail,
            "schedule_mode": recipe.schedule_mode,
        }
        result.data["capabilities"] = self.capabilities()
        return result

    def register_trusted_hook(
        self,
        *,
        hook_name: str,
        command_path: str,
        arguments: list[str] | None,
        working_directory: str | None,
        description: str,
    ) -> ToolResult:
        name = self._normalized_title(hook_name)
        path = Path(str(command_path or "").strip())
        if not name:
            return ToolResult(success=False, summary="Hook name is required.", error="missing_hook_name")
        if not path.exists():
            return ToolResult(success=False, summary="That hook target was not found.", error="hook_target_missing")
        if path.suffix.lower() not in TRUSTED_HOOK_EXTENSIONS:
            return ToolResult(success=False, summary="That hook type is not supported here.", error="unsupported_hook_type")
        hook = TrustedHookDefinition(
            name=name,
            title=name.title(),
            command_path=str(path),
            arguments=[str(item).strip() for item in (arguments or []) if str(item).strip()],
            working_directory=str(working_directory or path.parent),
            description=str(description or "").strip() or f"Trusted hook for {name}.",
            metadata={"registered_at": datetime.now(timezone.utc).isoformat()},
        )
        self.registry.save_hook(hook)
        return ToolResult(
            success=True,
            summary=f"Registered trusted hook {name}.",
            data={"hook": hook.to_dict(), "capabilities": self.capabilities()},
        )

    def execute_trusted_hook(self, *, hook_name: str, session_id: str) -> ToolResult:
        del session_id
        hook = self.registry.get_hook(hook_name)
        if hook is None:
            return ToolResult(success=False, summary="That trusted hook is not registered here.", error="unknown_trusted_hook")
        command = self._hook_command(hook)
        self.context.report_progress(
            {
                "summary": f"Running trusted hook {hook.title}.",
                "data": {
                    "workflow": self._workflow_payload(
                        title=hook.title,
                        kind="trusted_hook",
                        summary=f"Running trusted hook {hook.title}.",
                        current_step_index=0,
                        total_steps=1,
                        step_title="Execute trusted hook",
                    )
                },
            }
        )
        completed = subprocess.run(
            command,
            cwd=hook.working_directory or None,
            capture_output=True,
            text=True,
            timeout=max(int(hook.timeout_seconds), 1),
            shell=False,
        )
        success = completed.returncode == 0
        summary = f"Ran trusted hook {hook.title}." if success else f"Trusted hook {hook.title} failed."
        workflow = self._workflow_payload(
            title=hook.title,
            kind="trusted_hook",
            status="completed" if success else "failed",
            summary=summary,
            current_step_index=0,
            total_steps=1,
            step_title="Execute trusted hook",
        )
        return ToolResult(
            success=success,
            summary=summary,
            error=None if success else f"exit_{completed.returncode}",
            data={
                "hook": hook.to_dict(),
                "workflow": workflow,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "capabilities": self.capabilities(),
            },
        )

    def file_operation(
        self,
        *,
        operation: str,
        source_paths: list[str] | None,
        target_directory: str | None,
        destination_directory: str | None,
        target_mode: str,
        dry_run: bool,
        older_than_days: int | None,
        pattern: str,
        session_id: str,
    ) -> ToolResult:
        del session_id
        return self._file_operation_impl(
            operation=operation,
            source_paths=source_paths or [],
            target_directory=target_directory,
            destination_directory=destination_directory,
            target_mode=target_mode,
            dry_run=dry_run,
            older_than_days=older_than_days,
            pattern=pattern,
        )

    def maintenance_action(
        self,
        *,
        maintenance_kind: str,
        target_directory: str | None,
        older_than_days: int | None,
        dry_run: bool,
        session_id: str,
    ) -> ToolResult:
        del session_id
        return self._maintenance_action_impl(
            maintenance_kind=maintenance_kind,
            target_directory=target_directory,
            older_than_days=older_than_days,
            dry_run=dry_run,
        )

    def _dispatch_execution(self, *, execution_kind: str, parameters: dict[str, Any], session_id: str) -> ToolResult:
        if execution_kind == "workflow":
            return self.workflow_service.execute_workflow(
                workflow_kind=str(parameters.get("workflow_kind", "")).strip(),
                query=str(parameters.get("query", "")).strip(),
                session_id=session_id,
            )
        if execution_kind == "repair":
            return self.workflow_service.repair_action(
                repair_kind=str(parameters.get("repair_kind", "")).strip(),
                target=str(parameters.get("target", "")).strip(),
                session_id=session_id,
            )
        if execution_kind == "maintenance":
            return self._maintenance_action_impl(
                maintenance_kind=str(parameters.get("maintenance_kind", "")).strip(),
                target_directory=self._optional_string(parameters.get("target_directory")),
                older_than_days=self._optional_int(parameters.get("older_than_days")),
                dry_run=bool(parameters.get("dry_run", False)),
            )
        if execution_kind == "file_operation":
            return self._file_operation_impl(
                operation=str(parameters.get("operation", "")).strip(),
                source_paths=[str(item) for item in parameters.get("source_paths", []) if str(item).strip()],
                target_directory=self._optional_string(parameters.get("target_directory")),
                destination_directory=self._optional_string(parameters.get("destination_directory")),
                target_mode=str(parameters.get("target_mode", "explicit")).strip() or "explicit",
                dry_run=bool(parameters.get("dry_run", False)),
                older_than_days=self._optional_int(parameters.get("older_than_days")),
                pattern=str(parameters.get("pattern", "")).strip(),
            )
        if execution_kind == "maintenance_recipe":
            recipe_kind = str(parameters.get("recipe_kind", "")).strip().lower()
            if recipe_kind == "cleanup_routine":
                return self._run_cleanup_routine()
        if execution_kind == "trusted_hook":
            return self.execute_trusted_hook(hook_name=str(parameters.get("hook_name", "")).strip(), session_id=session_id)
        return ToolResult(success=False, summary="That routine action is not available here yet.", error="unsupported_routine_dispatch")

    def _run_cleanup_routine(self) -> ToolResult:
        steps = [
            ("Clean Downloads clutter", self._maintenance_action_impl, {"maintenance_kind": "downloads_cleanup", "target_directory": None, "older_than_days": 14, "dry_run": False}),
            ("Archive older screenshots", self._maintenance_action_impl, {"maintenance_kind": "archive_old_screenshots", "target_directory": None, "older_than_days": 14, "dry_run": False}),
        ]
        changed_total = 0
        skipped_total = 0
        partial = False
        completed_steps: list[dict[str, Any]] = []
        for index, (title, runner, kwargs) in enumerate(steps):
            self.context.report_progress(
                {
                    "summary": f"Running cleanup routine step {index + 1} of {len(steps)}.",
                    "data": {
                        "workflow": self._workflow_payload(
                            title="Cleanup routine",
                            kind="routine",
                            summary=f"Running cleanup routine step {index + 1} of {len(steps)}.",
                            current_step_index=index,
                            total_steps=len(steps),
                            step_title=title,
                        )
                    },
                }
            )
            result = runner(**kwargs)
            if not result.success:
                partial = True
            workflow = result.data.get("workflow", {}) if isinstance(result.data, dict) else {}
            item_progress = workflow.get("item_progress", {}) if isinstance(workflow, dict) else {}
            changed_total += int(item_progress.get("changed", 0) or 0)
            skipped_total += int(item_progress.get("skipped", 0) or 0)
            completed_steps.append(
                {
                    "title": title,
                    "status": "completed" if result.success else "failed",
                    "summary": result.summary,
                }
            )
        summary = "Ran the cleanup routine."
        if changed_total:
            summary = f"Ran the cleanup routine and changed {changed_total} items."
        if skipped_total:
            summary = f"{summary.rstrip('.')} Skipped {skipped_total} items."
        workflow = self._workflow_payload(
            title="Cleanup routine",
            kind="routine",
            status="completed",
            summary=summary,
            current_step_index=len(steps) - 1,
            total_steps=len(steps),
            step_title=completed_steps[-1]["title"] if completed_steps else "",
            steps=completed_steps,
            processed=len(steps),
            total=len(steps),
            changed=changed_total,
            skipped=skipped_total,
            partial=partial,
        )
        return ToolResult(success=True, summary=summary, data={"workflow": workflow, "capabilities": self.capabilities()})

    def _maintenance_action_impl(
        self,
        *,
        maintenance_kind: str,
        target_directory: str | None,
        older_than_days: int | None,
        dry_run: bool,
    ) -> ToolResult:
        kind = str(maintenance_kind or "").strip().lower()
        if kind == "downloads_cleanup":
            root = Path(target_directory) if target_directory else self._default_downloads_dir()
            return self._archive_matching_files(
                title="Downloads cleanup",
                root=root,
                matcher=lambda path: path.suffix.lower() in DOWNLOAD_CLUTTER_EXTENSIONS,
                dry_run=dry_run,
                older_than_days=older_than_days or 14,
                archive_label="Downloads Cleanup",
                kind="maintenance",
            )
        if kind == "archive_old_screenshots":
            root = Path(target_directory) if target_directory else self._default_screenshots_dir()
            return self._archive_matching_files(
                title="Screenshots archive",
                root=root,
                matcher=lambda path: path.suffix.lower() in SCREENSHOT_EXTENSIONS,
                dry_run=dry_run,
                older_than_days=older_than_days or 14,
                archive_label="Screenshots",
                kind="maintenance",
            )
        if kind == "find_stale_large_files":
            root = Path(target_directory) if target_directory else self._default_downloads_dir()
            candidates = self._stale_large_files(root=root, older_than_days=older_than_days or 30)
            summary = f"Found {len(candidates)} stale large file{'s' if len(candidates) != 1 else ''}."
            return ToolResult(
                success=True,
                summary=summary,
                data={
                    "maintenance": {
                        "maintenance_kind": kind,
                        "target_directory": str(root),
                        "candidates": candidates,
                        "dry_run": True,
                    },
                    "workflow": self._workflow_payload(
                        title="Find stale large files",
                        kind="maintenance",
                        status="completed",
                        summary=summary,
                        current_step_index=0,
                        total_steps=1,
                        step_title="Scan for stale large files",
                        processed=len(candidates),
                        total=len(candidates),
                        changed=0,
                        skipped=0,
                    ),
                    "capabilities": self.capabilities(),
                },
            )
        return ToolResult(success=False, summary="That maintenance action is not available here yet.", error="unsupported_maintenance_action")

    def _file_operation_impl(
        self,
        *,
        operation: str,
        source_paths: list[str],
        target_directory: str | None,
        destination_directory: str | None,
        target_mode: str,
        dry_run: bool,
        older_than_days: int | None,
        pattern: str,
    ) -> ToolResult:
        op = str(operation or "").strip().lower()
        if op == "create_folder":
            target = Path(destination_directory or target_directory or self.context.config.project_root)
            if not dry_run:
                target.mkdir(parents=True, exist_ok=True)
            summary = f"Created {target.name}." if not dry_run else f"Would create {target.name}."
            return ToolResult(
                success=True,
                summary=summary,
                data={
                    "file_operation": {
                        "operation": op,
                        "dry_run": dry_run,
                        "preview": [{"destination_path": str(target), "action": "create_folder"}],
                        "changes": {"created_paths": [str(target)] if not dry_run else []},
                    },
                    "workflow": self._workflow_payload(
                        title="Create folder",
                        kind="file_operation",
                        status="completed",
                        summary=summary,
                        current_step_index=0,
                        total_steps=1,
                        step_title="Create folder",
                        processed=1,
                        total=1,
                        changed=0 if dry_run else 1,
                        skipped=0,
                    ),
                    "capabilities": self.capabilities(),
                },
            )

        sources = self._resolve_source_paths(source_paths=source_paths, target_directory=target_directory, target_mode=target_mode)
        if not sources and op != "find_duplicates":
            return ToolResult(success=False, summary="No matching files were available for that operation.", error="no_file_targets")

        if op == "rename_by_date":
            return self._rename_by_date(sources=sources, dry_run=dry_run, pattern=pattern)
        if op in {"move", "copy", "archive"}:
            destination_root = Path(destination_directory) if destination_directory else self._default_archive_root(sources[0].parent if sources else self.context.config.project_root, "Files")
            mover = shutil.copy2 if op == "copy" else shutil.move
            return self._relocate_files(title=op.replace("_", " ").title(), kind="file_operation", action=op, sources=sources, destination_root=destination_root, dry_run=dry_run, mover=mover)
        if op == "group_by_type":
            root = Path(destination_directory) if destination_directory else (Path(target_directory) if target_directory else sources[0].parent)
            preview: list[dict[str, Any]] = []
            changed_paths: list[str] = []
            skipped: list[dict[str, Any]] = []
            for index, source in enumerate(sources, start=1):
                if not source.exists() or not source.is_file():
                    skipped.append({"source_path": str(source), "reason": "missing"})
                    continue
                bucket = source.suffix.lstrip(".").upper() or "MISC"
                destination = self._unique_destination(root / bucket / source.name)
                preview.append({"source_path": str(source), "destination_path": str(destination), "action": "group_by_type"})
                self._report_item_progress(title="Group files by type", kind="file_operation", step_title="Group files by type", processed=index, total=len(sources), changed=len(changed_paths), skipped=len(skipped))
                if dry_run:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
                changed_paths.append(str(destination))
            summary = f"Prepared {len(preview)} file move{'s' if len(preview) != 1 else ''} by type." if dry_run else f"Grouped {len(changed_paths)} file{'s' if len(changed_paths) != 1 else ''} by type."
            return ToolResult(
                success=True,
                summary=summary,
                data={
                    "file_operation": {
                        "operation": op,
                        "dry_run": dry_run,
                        "preview": preview,
                        "changes": {"changed_paths": changed_paths, "skipped": skipped},
                    },
                    "workflow": self._workflow_payload(
                        title="Group files by type",
                        kind="file_operation",
                        status="completed",
                        summary=summary,
                        current_step_index=0,
                        total_steps=1,
                        step_title="Group files by type",
                        processed=len(preview),
                        total=len(sources),
                        changed=len(changed_paths),
                        skipped=len(skipped),
                    ),
                    "capabilities": self.capabilities(),
                },
            )
        if op == "find_duplicates":
            root = Path(target_directory) if target_directory else self.context.config.project_root
            duplicates = self._find_duplicates(root)
            summary = f"Found {len(duplicates)} duplicate group{'s' if len(duplicates) != 1 else ''}."
            return ToolResult(
                success=True,
                summary=summary,
                data={
                    "file_operation": {
                        "operation": op,
                        "dry_run": True,
                        "duplicate_groups": duplicates,
                    },
                    "workflow": self._workflow_payload(
                        title="Find duplicates",
                        kind="file_operation",
                        status="completed",
                        summary=summary,
                        current_step_index=0,
                        total_steps=1,
                        step_title="Find duplicates",
                        processed=len(duplicates),
                        total=len(duplicates),
                        changed=0,
                        skipped=0,
                    ),
                    "capabilities": self.capabilities(),
                },
            )
        return ToolResult(success=False, summary="That file operation is not available here yet.", error="unsupported_file_operation")

    def _rename_by_date(self, *, sources: list[Path], dry_run: bool, pattern: str) -> ToolResult:
        preview: list[dict[str, Any]] = []
        changed_paths: list[str] = []
        skipped: list[dict[str, Any]] = []
        total = len(sources)
        for index, source in enumerate(sources, start=1):
            if not source.exists() or not source.is_file():
                skipped.append({"source_path": str(source), "reason": "missing"})
                continue
            stamp = datetime.fromtimestamp(source.stat().st_mtime, timezone.utc)
            prefix = pattern or stamp.strftime("%Y-%m-%d_%H%M%S")
            safe_stem = self._safe_name(source.stem)
            destination = self._unique_destination(source.with_name(f"{prefix}_{safe_stem}{source.suffix}"))
            preview.append({"source_path": str(source), "destination_path": str(destination), "action": "rename_by_date"})
            self._report_item_progress(
                title="Rename files by date",
                kind="file_operation",
                step_title="Rename files by date",
                processed=index,
                total=total,
                changed=len(changed_paths),
                skipped=len(skipped),
            )
            if dry_run:
                continue
            source.rename(destination)
            changed_paths.append(str(destination))
        summary = f"Prepared {len(preview)} date-based rename{'s' if len(preview) != 1 else ''}." if dry_run else f"Renamed {len(changed_paths)} file{'s' if len(changed_paths) != 1 else ''}."
        return ToolResult(
            success=True,
            summary=summary,
            data={
                "file_operation": {
                    "operation": "rename_by_date",
                    "dry_run": dry_run,
                    "preview": preview,
                    "changes": {"changed_paths": changed_paths, "skipped": skipped},
                },
                "workflow": self._workflow_payload(
                    title="Rename files by date",
                    kind="file_operation",
                    status="completed",
                    summary=summary,
                    current_step_index=0,
                    total_steps=1,
                    step_title="Rename files by date",
                    processed=len(preview),
                    total=total,
                    changed=len(changed_paths),
                    skipped=len(skipped),
                ),
                "capabilities": self.capabilities(),
            },
        )

    def _relocate_files(
        self,
        *,
        title: str,
        kind: str,
        action: str,
        sources: list[Path],
        destination_root: Path,
        dry_run: bool,
        mover,
    ) -> ToolResult:
        preview: list[dict[str, Any]] = []
        changed_paths: list[str] = []
        skipped: list[dict[str, Any]] = []
        total = len(sources)
        for index, source in enumerate(sources, start=1):
            if not source.exists() or not source.is_file():
                skipped.append({"source_path": str(source), "reason": "missing"})
                continue
            destination = self._unique_destination(destination_root / source.name)
            preview.append({"source_path": str(source), "destination_path": str(destination), "action": action})
            self._report_item_progress(title=title, kind=kind, step_title=title, processed=index, total=total, changed=len(changed_paths), skipped=len(skipped))
            if dry_run:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                if mover is shutil.copy2:
                    mover(str(source), str(destination))
                else:
                    source.replace(destination)
                changed_paths.append(str(destination))
            except OSError as error:
                skipped.append({"source_path": str(source), "reason": str(error)})
        summary = f"Prepared {len(preview)} file change{'s' if len(preview) != 1 else ''}." if dry_run else f"{title} moved {len(changed_paths)} file{'s' if len(changed_paths) != 1 else ''}."
        return ToolResult(
            success=True,
            summary=summary,
            data={
                "file_operation": {
                    "operation": action,
                    "dry_run": dry_run,
                    "preview": preview,
                    "changes": {"changed_paths": changed_paths, "skipped": skipped},
                },
                "workflow": self._workflow_payload(
                    title=title,
                    kind=kind,
                    status="completed",
                    summary=summary,
                    current_step_index=0,
                    total_steps=1,
                    step_title=title,
                    processed=len(preview),
                    total=total,
                    changed=len(changed_paths),
                    skipped=len(skipped),
                ),
                "capabilities": self.capabilities(),
            },
        )

    def _archive_matching_files(
        self,
        *,
        title: str,
        root: Path,
        matcher,
        dry_run: bool,
        older_than_days: int,
        archive_label: str,
        kind: str,
    ) -> ToolResult:
        candidates = self._candidate_files(root, matcher=matcher, older_than_days=older_than_days)
        archive_root = self._default_archive_root(root, archive_label)
        preview: list[dict[str, Any]] = []
        archived_paths: list[str] = []
        skipped: list[dict[str, Any]] = []
        total = len(candidates)
        for index, source in enumerate(candidates, start=1):
            destination = self._unique_destination(archive_root / source.name)
            preview.append({"source_path": str(source), "destination_path": str(destination), "action": "archive"})
            self._report_item_progress(title=title, kind=kind, step_title=title, processed=index, total=total, changed=len(archived_paths), skipped=len(skipped))
            if dry_run:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                source.replace(destination)
                archived_paths.append(str(destination))
            except OSError as error:
                skipped.append({"source_path": str(source), "reason": str(error)})
        if dry_run:
            summary = f"Prepared {len(preview)} file archive{'s' if len(preview) != 1 else ''}."
        elif archived_paths:
            summary = f"Archived {len(archived_paths)} file{'s' if len(archived_paths) != 1 else ''}."
        else:
            summary = "No matching files needed cleanup."
        return ToolResult(
            success=True,
            summary=summary,
            data={
                "maintenance": {
                    "maintenance_kind": normalize_phrase(title),
                    "target_directory": str(root),
                    "dry_run": dry_run,
                    "preview": preview,
                    "changes": {"archived_paths": archived_paths, "skipped": skipped},
                },
                "workflow": self._workflow_payload(
                    title=title,
                    kind=kind,
                    status="completed",
                    summary=summary,
                    current_step_index=0,
                    total_steps=1,
                    step_title=title,
                    processed=len(preview),
                    total=total,
                    changed=len(archived_paths),
                    skipped=len(skipped),
                ),
                "capabilities": self.capabilities(),
            },
        )

    def _candidate_files(self, root: Path, *, matcher, older_than_days: int) -> list[Path]:
        if not root.exists() or not root.is_dir():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(older_than_days, 0))
        results: list[Path] = []
        for path in sorted(root.iterdir()):
            if not path.is_file():
                continue
            if not matcher(path):
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified > cutoff:
                continue
            results.append(path)
        return results

    def _find_duplicates(self, root: Path) -> list[dict[str, Any]]:
        if not root.exists() or not root.is_dir():
            return []
        by_size: dict[int, list[Path]] = {}
        for path in root.rglob("*"):
            if path.is_file():
                by_size.setdefault(path.stat().st_size, []).append(path)
        groups: list[dict[str, Any]] = []
        for size_bytes, paths in by_size.items():
            if len(paths) < 2:
                continue
            hashes: dict[str, list[Path]] = {}
            for path in paths:
                digest = hashlib.sha1(path.read_bytes()).hexdigest()
                hashes.setdefault(digest, []).append(path)
            for digest, dupes in hashes.items():
                if len(dupes) < 2:
                    continue
                groups.append({"size_bytes": size_bytes, "digest": digest, "paths": [str(path) for path in dupes]})
        return groups

    def _stale_large_files(self, *, root: Path, older_than_days: int, min_size_mb: int = 50) -> list[dict[str, Any]]:
        if not root.exists() or not root.is_dir():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(older_than_days, 0))
        minimum_bytes = min_size_mb * 1024 * 1024
        results: list[dict[str, Any]] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            if stat.st_size < minimum_bytes or modified > cutoff:
                continue
            results.append({"path": str(path), "size_bytes": stat.st_size, "modified_at": modified.isoformat()})
        return sorted(results, key=lambda item: (int(item["size_bytes"]), str(item["modified_at"])), reverse=True)[:12]

    def _report_item_progress(
        self,
        *,
        title: str,
        kind: str,
        step_title: str,
        processed: int,
        total: int,
        changed: int,
        skipped: int,
    ) -> None:
        self.context.report_progress(
            {
                "summary": f"{title}: {processed} of {total} items processed.",
                "data": {
                    "workflow": self._workflow_payload(
                        title=title,
                        kind=kind,
                        summary=f"{title}: {processed} of {total} items processed.",
                        current_step_index=0,
                        total_steps=1,
                        step_title=step_title,
                        processed=processed,
                        total=total,
                        changed=changed,
                        skipped=skipped,
                    )
                },
            }
        )

    def _workflow_payload(
        self,
        *,
        title: str,
        kind: str,
        summary: str,
        current_step_index: int,
        total_steps: int,
        step_title: str,
        status: str = "running",
        processed: int = 0,
        total: int = 0,
        changed: int = 0,
        skipped: int = 0,
        partial: bool = False,
        steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "kind": kind,
            "title": title,
            "status": status,
            "current_step_index": current_step_index,
            "completed_steps": min(current_step_index, total_steps),
            "total_steps": total_steps,
            "partial": partial,
            "summary": summary,
            "steps": list(steps or [{"title": step_title, "status": status}]),
            "item_progress": {
                "processed": processed,
                "total": total,
                "changed": changed,
                "skipped": skipped,
            },
        }

    def _resolve_recipe(self, routine_name: str) -> RecipeDefinition | None:
        normalized = normalize_lookup_phrase(routine_name) or normalize_phrase(routine_name)
        if not normalized:
            return None
        recipes = self._recipe_catalog()
        exact = recipes.get(normalized)
        if exact is not None:
            return exact
        best_key = ""
        best_score = 0.0
        for key in recipes:
            score = fuzzy_ratio(normalized, key)
            if score > best_score:
                best_key = key
                best_score = score
        if best_key and best_score >= 0.86:
            return recipes[best_key]
        return None

    def _recipe_catalog(self) -> dict[str, RecipeDefinition]:
        recipes = [
            RecipeDefinition(
                name="cleanup routine",
                title="Cleanup Routine",
                description="Archive older Downloads clutter and screenshots.",
                execution_kind="maintenance_recipe",
                parameters={"recipe_kind": "cleanup_routine"},
            ),
            RecipeDefinition(
                name="network health check",
                title="Network Health Check",
                description="Run the deterministic connectivity check workflow.",
                execution_kind="repair",
                parameters={"repair_kind": "connectivity_checks", "target": "network"},
            ),
            RecipeDefinition(
                name="normal setup",
                title="Normal Setup",
                description="Restore the current work context.",
                execution_kind="workflow",
                parameters={"workflow_kind": "current_work_context", "query": "open my current work context"},
            ),
            RecipeDefinition(
                name="writing setup",
                title="Writing Setup",
                description="Restore the writing workflow.",
                execution_kind="workflow",
                parameters={"workflow_kind": "writing_setup", "query": "set up my writing environment"},
            ),
        ]
        return {(normalize_lookup_phrase(recipe.name) or normalize_phrase(recipe.name)): recipe for recipe in recipes}

    def _resolve_source_paths(self, *, source_paths: list[str], target_directory: str | None, target_mode: str) -> list[Path]:
        if source_paths:
            return [Path(item) for item in source_paths if str(item).strip()]
        if target_directory:
            root = Path(target_directory)
            if root.exists() and root.is_dir():
                return [path for path in sorted(root.iterdir()) if path.is_file()]
        mode = str(target_mode or "").strip().lower()
        if mode == "screenshots_default":
            root = self._default_screenshots_dir()
            if root.exists():
                return [path for path in sorted(root.iterdir()) if path.is_file()]
        if mode == "downloads_default":
            root = self._default_downloads_dir()
            if root.exists():
                return [path for path in sorted(root.iterdir()) if path.is_file()]
        return []

    def _default_archive_root(self, root: Path, label: str) -> Path:
        month_label = datetime.now().strftime("%Y-%m")
        return root / "Stormhelm Archive" / label / month_label

    def _default_downloads_dir(self) -> Path:
        home = Path(os.environ.get("USERPROFILE") or Path.home())
        return home / "Downloads"

    def _default_screenshots_dir(self) -> Path:
        home = Path(os.environ.get("USERPROFILE") or Path.home())
        return home / "Pictures" / "Screenshots"

    def _hook_command(self, hook: TrustedHookDefinition) -> list[str]:
        path = Path(hook.command_path)
        suffix = path.suffix.lower()
        if suffix in {".bat", ".cmd"}:
            return [os.environ.get("COMSPEC", "cmd.exe"), "/c", str(path), *hook.arguments]
        if suffix == ".ps1":
            return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path), *hook.arguments]
        if suffix == ".py":
            return [sys.executable, str(path), *hook.arguments]
        return [str(path), *hook.arguments]

    def _unique_destination(self, destination: Path) -> Path:
        if not destination.exists():
            return destination
        stem = destination.stem
        suffix = destination.suffix
        counter = 2
        while True:
            candidate = destination.with_name(f"{stem}-{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _normalized_title(self, value: str) -> str:
        normalized = " ".join(str(value or "").split()).strip()
        return normalized.strip(" .,:;!?")

    def _safe_name(self, value: str) -> str:
        text = normalize_phrase(value).replace(" ", "-").strip("-")
        return text or "file"

    def _optional_string(self, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _optional_int(self, value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
