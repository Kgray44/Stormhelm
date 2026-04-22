from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from stormhelm.config.models import AppConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.lifecycle.models import (
    BootstrapEvaluation,
    CoreProcessStatus,
    CoreRuntimeState,
    CrashRecord,
    InstallMode,
    InstallState,
    LifecycleSnapshot,
    MigrationState,
    MigrationStatus,
    OnboardingState,
    OnboardingStatus,
    RegistrationStatus,
    RestartPolicyState,
    RuntimeMode,
    RuntimePaths,
    ShellPresenceStatus,
    ShellPresenceUpdate,
    StartupPolicyState,
    TrayPresenceStatus,
    UninstallPlan,
)
from stormhelm.shared.time import utc_now_iso


StartupRegistrationProbe = Callable[[AppConfig, InstallState, StartupPolicyState, dict[str, str]], dict[str, Any]]


class LifecycleController:
    def __init__(
        self,
        config: AppConfig,
        *,
        events: EventBuffer | None = None,
        startup_registration_probe: StartupRegistrationProbe | None = None,
    ) -> None:
        self.config = config
        self.events = events
        self._startup_registration_probe = startup_registration_probe or _default_startup_registration_probe
        self._persisted = self._load_json(self.config.runtime.lifecycle_state_path)
        self._recent_crashes = [self._crash_from_dict(item) for item in self._persisted.get("recent_crashes", [])]
        self._shell_presence = self._load_shell_presence()
        self._install_state = self._build_install_state()
        self._runtime_paths = self._build_runtime_paths()
        self._startup_policy = self._build_startup_policy()
        self._migration_state = self._build_migration_state()
        self._onboarding = self._build_onboarding_state()
        self._bootstrapped = False
        self._bootstrap = self._build_bootstrap_evaluation()
        self._last_healthy_at = ""
        self._shell_detached = self._shell_presence is None

    @property
    def install_state(self) -> InstallState:
        return self._install_state

    def bootstrap(self) -> BootstrapEvaluation:
        now = utc_now_iso()
        self._install_state = self._build_install_state(detected_at=now)
        self._runtime_paths = self._build_runtime_paths()
        self._startup_policy = self._build_startup_policy(verified_at=now)
        self._migration_state = self._build_migration_state()
        self._onboarding = self._build_onboarding_state()

        self._record_previous_session_crashes()
        restart_policy = self._build_restart_policy()
        lifecycle_hold_reason = self._migration_state.hold_reason
        if not lifecycle_hold_reason and restart_policy.hold_active:
            lifecycle_hold_reason = restart_policy.hold_reason

        warnings: list[str] = []
        if self._migration_state.migration_required and self._migration_state.status == MigrationStatus.COMPLETED:
            warnings.append(
                f"Version changed from {self._migration_state.previous_version} to {self._migration_state.target_version}."
            )
        if self._onboarding.status != OnboardingStatus.COMPLETED:
            warnings.append("Lifecycle onboarding still needs operator review.")

        self._bootstrap = BootstrapEvaluation(
            startup_allowed=not lifecycle_hold_reason,
            install_state=self._install_state,
            migration_state=self._migration_state,
            registration_state=self._startup_policy,
            lifecycle_hold_reason=lifecycle_hold_reason,
            degraded_launch_reason="restart_hold" if restart_policy.hold_active else "",
            onboarding_required=self._onboarding.status != OnboardingStatus.COMPLETED,
            warnings=warnings,
        )
        self._bootstrapped = True
        self._last_healthy_at = now

        self._write_json(
            self.config.runtime.core_session_path,
            {
                "component": "core",
                "pid": os.getpid(),
                "started_at": now,
                "version": self.config.version,
                "install_mode": self._install_state.install_mode.value,
                "runtime_mode": self._install_state.runtime_mode.value,
            },
        )
        self._persist_state()
        self._publish_bootstrap_events()
        return self._bootstrap

    def shutdown(self) -> None:
        self.config.runtime.core_session_path.unlink(missing_ok=True)
        self._persisted["last_clean_shutdown_at"] = utc_now_iso()
        self._persist_state()

    def record_shell_presence(self, update: ShellPresenceUpdate) -> None:
        observed_at = update.observed_at or utc_now_iso()
        update = ShellPresenceUpdate(
            pid=update.pid,
            mode=update.mode,
            window_visible=update.window_visible,
            tray_present=update.tray_present,
            hide_to_tray_on_close=update.hide_to_tray_on_close,
            ghost_reveal_target=update.ghost_reveal_target,
            event=update.event,
            observed_at=observed_at,
        )
        previous = self._load_shell_presence()
        if previous is not None and previous.pid != update.pid:
            self._append_crash_record(
                component="shell",
                timestamp=previous.observed_at or utc_now_iso(),
                operator_summary="The shell stopped unexpectedly before it reported a clean detach.",
            )
        self._shell_presence = update
        self._shell_detached = False
        self._write_json(self.config.runtime.shell_session_path, update.to_dict())
        self._persist_state()

    def record_shell_detached(self, pid: int | None = None) -> None:
        current = self._load_shell_presence()
        if current is not None and pid is not None and current.pid != pid:
            return
        self._shell_presence = None
        self._shell_detached = True
        self.config.runtime.shell_session_path.unlink(missing_ok=True)
        self._persist_state()

    def status_snapshot(self) -> dict[str, Any]:
        self._install_state = self._build_install_state()
        self._runtime_paths = self._build_runtime_paths()
        self._startup_policy = self._build_startup_policy()
        self._migration_state = self._build_migration_state()
        self._onboarding = self._build_onboarding_state()
        self._bootstrap = self._build_bootstrap_evaluation()
        snapshot = LifecycleSnapshot(
            install_state=self._install_state,
            runtime_paths=self._runtime_paths,
            startup_policy=self._startup_policy,
            runtime=self._build_runtime_state(),
            crash={
                "recent": [record.to_dict() for record in self._recent_crashes[:5]],
                "recent_count": len(self._recent_crashes),
            },
            restart_policy=self._build_restart_policy(),
            migration=self._migration_state,
            bootstrap=self._bootstrap,
            onboarding=self._onboarding,
            uninstall_plan=self._build_uninstall_plan(),
        )
        return snapshot.to_dict()

    def _build_install_state(self, *, detected_at: str | None = None) -> InstallState:
        install_root = self.config.runtime.install_root.resolve()
        runtime_mode = (
            RuntimeMode.SOURCE if self.config.runtime.mode == RuntimeMode.SOURCE.value else RuntimeMode.PACKAGED
        )
        if runtime_mode == RuntimeMode.SOURCE:
            return InstallState(
                install_mode=InstallMode.SOURCE,
                runtime_mode=runtime_mode,
                install_channel=self.config.release_channel,
                install_detected_at=detected_at or utc_now_iso(),
                startup_capable=False,
                uninstall_capable=False,
                migration_capable=False,
                mode_source="runtime_mode",
                confidence="explicit",
                notes=["Source checkout posture keeps startup registration and uninstall outside Stormhelm."],
            )

        portable_config_present = self.config.runtime.portable_config_path.exists()
        if portable_config_present:
            install_mode = InstallMode.PORTABLE
            mode_source = "portable_config"
            confidence = "explicit"
            notes = ["Portable posture inferred from portable.toml in the install root."]
        elif _looks_installed(install_root):
            install_mode = InstallMode.INSTALLED
            mode_source = "install_root_heuristic"
            confidence = "heuristic"
            notes = ["Packaged build is running from a common Windows install location."]
        else:
            install_mode = InstallMode.PORTABLE
            mode_source = "install_root_heuristic"
            confidence = "heuristic"
            notes = ["Packaged build is running outside common Windows install locations, so portable posture is assumed."]

        startup_capable = install_mode == InstallMode.INSTALLED and sys.platform.startswith("win")
        return InstallState(
            install_mode=install_mode,
            runtime_mode=runtime_mode,
            install_channel=self.config.release_channel,
            install_detected_at=detected_at or utc_now_iso(),
            startup_capable=startup_capable,
            uninstall_capable=True,
            migration_capable=True,
            mode_source=mode_source,
            confidence=confidence,
            notes=notes,
        )

    def _build_runtime_paths(self) -> RuntimePaths:
        return RuntimePaths(
            install_root=str(self.config.runtime.install_root),
            resource_root=str(self.config.runtime.resource_root),
            user_data_root=str(self.config.storage.data_dir),
            state_root=str(self.config.storage.state_dir),
            cache_root=str(self.config.storage.cache_dir),
            log_root=str(self.config.storage.logs_dir),
            mode_source=self._install_state.mode_source,
            confidence=self._install_state.confidence,
        )

    def _build_startup_policy(self, *, verified_at: str | None = None) -> StartupPolicyState:
        stored_policy = self._persisted.get("startup_policy", {})
        startup_enabled = bool(stored_policy.get("startup_enabled", self.config.lifecycle.startup_enabled))
        start_core = bool(stored_policy.get("start_core_with_windows", self.config.lifecycle.start_core_with_windows))
        start_shell = bool(stored_policy.get("start_shell_with_windows", self.config.lifecycle.start_shell_with_windows))
        tray_only = bool(stored_policy.get("tray_only_startup", self.config.lifecycle.tray_only_startup))
        ghost_ready = bool(stored_policy.get("ghost_ready_on_startup", self.config.lifecycle.ghost_ready_on_startup))
        mode_supported = bool(self._install_state.startup_capable)

        if not startup_enabled:
            return StartupPolicyState(
                startup_enabled=False,
                start_core_with_windows=start_core,
                start_shell_with_windows=start_shell,
                tray_only_startup=tray_only,
                ghost_ready_on_startup=ghost_ready,
                registration_status=RegistrationStatus.DISABLED,
                registered_core=False,
                registered_shell=False,
                last_verified_at=verified_at or "",
                mode_supported=mode_supported,
                mode_reason="" if mode_supported else "Startup registration is unavailable in the current posture.",
            )

        if not mode_supported:
            return StartupPolicyState(
                startup_enabled=True,
                start_core_with_windows=start_core,
                start_shell_with_windows=start_shell,
                tray_only_startup=tray_only,
                ghost_ready_on_startup=ghost_ready,
                registration_status=RegistrationStatus.NOT_REGISTERED,
                registered_core=False,
                registered_shell=False,
                last_verified_at=verified_at or "",
                failure_reason="Current install posture does not support Windows startup registration.",
                mode_supported=False,
                mode_reason="Startup registration requires installed packaged mode on Windows.",
            )

        registration_probe = self._startup_registration_probe(
            self.config,
            self._install_state,
            StartupPolicyState(
                startup_enabled=startup_enabled,
                start_core_with_windows=start_core,
                start_shell_with_windows=start_shell,
                tray_only_startup=tray_only,
                ghost_ready_on_startup=ghost_ready,
                registration_status=RegistrationStatus.NOT_REGISTERED,
                registered_core=False,
                registered_shell=False,
            ),
            self._startup_commands(),
        )
        registered_core = bool(registration_probe.get("registered_core", False))
        registered_shell = bool(registration_probe.get("registered_shell", False))
        failure_reason = str(registration_probe.get("failure_reason", "")).strip()
        expected_core = not start_core or registered_core
        expected_shell = not start_shell or registered_shell
        if failure_reason and not (registered_core or registered_shell):
            registration_status = RegistrationStatus.BLOCKED
        elif expected_core and expected_shell:
            registration_status = RegistrationStatus.REGISTERED
        else:
            registration_status = RegistrationStatus.NOT_REGISTERED
        return StartupPolicyState(
            startup_enabled=startup_enabled,
            start_core_with_windows=start_core,
            start_shell_with_windows=start_shell,
            tray_only_startup=tray_only,
            ghost_ready_on_startup=ghost_ready,
            registration_status=registration_status,
            registered_core=registered_core,
            registered_shell=registered_shell,
            last_verified_at=verified_at or "",
            failure_reason=failure_reason,
            mode_supported=True,
            mode_reason="",
        )

    def _build_migration_state(self) -> MigrationState:
        previous_version = str(self._persisted.get("last_version", "")).strip()
        previous_protocol = int(self._persisted.get("last_protocol_version", 0) or 0)
        previous_install_mode = str(self._persisted.get("last_install_mode", "")).strip()
        if previous_install_mode and previous_install_mode != self._install_state.install_mode.value:
            return MigrationState(
                previous_version=previous_version,
                target_version=self.config.version,
                status=MigrationStatus.HOLD,
                migration_required=True,
                migration_started=False,
                migration_completed=False,
                migration_failed=False,
                hold_reason=(
                    f"Install posture changed from {previous_install_mode} to {self._install_state.install_mode.value}; "
                    "review lifecycle boundaries before continuing."
                ),
            )
        if previous_protocol and previous_protocol > self.config.protocol_version:
            return MigrationState(
                previous_version=previous_version,
                target_version=self.config.version,
                status=MigrationStatus.HOLD,
                migration_required=True,
                migration_started=False,
                migration_completed=False,
                migration_failed=False,
                hold_reason="State was last written by a newer Stormhelm protocol version.",
            )
        if previous_version and previous_version != self.config.version:
            return MigrationState(
                previous_version=previous_version,
                target_version=self.config.version,
                status=MigrationStatus.COMPLETED,
                migration_required=True,
                migration_started=True,
                migration_completed=True,
                migration_failed=False,
            )
        return MigrationState(
            previous_version=previous_version,
            target_version=self.config.version,
            status=MigrationStatus.CURRENT,
            migration_required=False,
            migration_started=False,
            migration_completed=False,
            migration_failed=False,
        )

    def _build_onboarding_state(self) -> OnboardingState:
        if self._persisted.get("onboarding"):
            return OnboardingState.from_dict(self._persisted.get("onboarding"))
        first_run = not self.config.runtime.first_run_marker_path.exists()
        if first_run:
            return OnboardingState(
                status=OnboardingStatus.REQUIRED,
                startup_preference_chosen=bool(self.config.lifecycle.startup_enabled),
                background_preference_chosen=True,
                trust_setup_state="pending",
            )
        return OnboardingState(
            status=OnboardingStatus.DEFERRED,
            startup_preference_chosen=bool(self.config.lifecycle.startup_enabled),
            background_preference_chosen=True,
            trust_setup_state="deferred",
        )

    def _build_runtime_state(self) -> CoreRuntimeState:
        shell_presence = self._load_shell_presence()
        shell_status = ShellPresenceStatus.DETACHED if self._shell_detached else ShellPresenceStatus.UNKNOWN
        tray_status = TrayPresenceStatus.ABSENT
        connected_clients = 0
        shell_pid: int | None = None
        shell_mode = ""
        if shell_presence is not None:
            shell_pid = shell_presence.pid
            shell_mode = shell_presence.mode
            age = _age_seconds(shell_presence.observed_at)
            if age is not None and age > self.config.lifecycle.shell_stale_after_seconds:
                shell_status = ShellPresenceStatus.STALE
                tray_status = TrayPresenceStatus.PRESENT if shell_presence.tray_present else TrayPresenceStatus.ABSENT
            else:
                shell_status = ShellPresenceStatus.VISIBLE if shell_presence.window_visible else ShellPresenceStatus.HIDDEN
                tray_status = TrayPresenceStatus.PRESENT if shell_presence.tray_present else TrayPresenceStatus.ABSENT
                connected_clients = 1
        core_status = CoreProcessStatus.HELD if self._build_restart_policy().hold_active or self._migration_state.hold_reason else CoreProcessStatus.ALIVE
        return CoreRuntimeState(
            core_status=core_status,
            shell_status=shell_status,
            tray_status=tray_status,
            connected_clients=connected_clients,
            last_healthy_at=self._last_healthy_at or utc_now_iso(),
            degraded_mode=bool(self._migration_state.hold_reason or self._build_restart_policy().hold_active),
            pending_restart_reason=self._migration_state.hold_reason or self._build_restart_policy().hold_reason,
            shell_pid=shell_pid,
            shell_mode=shell_mode,
        )

    def _build_restart_policy(self) -> RestartPolicyState:
        attempts_in_window = 0
        for record in self._recent_crashes:
            if record.component != "core":
                continue
            if _is_within_failure_window(record.timestamp, self.config.lifecycle.restart_failure_window_seconds):
                attempts_in_window += 1
        hold_active = attempts_in_window >= self.config.lifecycle.max_core_restart_attempts > 0
        hold_reason = (
            "Stormhelm observed repeated core failures in the recent restart window."
            if hold_active
            else ""
        )
        return RestartPolicyState(
            auto_restart_core=self.config.lifecycle.auto_restart_core,
            max_restart_attempts=self.config.lifecycle.max_core_restart_attempts,
            attempts_in_window=attempts_in_window,
            hold_active=hold_active,
            hold_reason=hold_reason,
            window_seconds=self.config.lifecycle.restart_failure_window_seconds,
        )

    def _build_uninstall_plan(self) -> UninstallPlan:
        install_mode = self._install_state.install_mode
        return UninstallPlan(
            remove_binaries=install_mode != InstallMode.SOURCE,
            remove_shortcuts=install_mode == InstallMode.INSTALLED,
            remove_startup_registration=bool(
                self._startup_policy.registered_core
                or self._startup_policy.registered_shell
                or self._startup_policy.startup_enabled
            ),
            remove_caches=False,
            remove_logs=False,
            remove_durable_state=False,
            portable_cleanup_notes=(
                "Portable cleanup should remove only the extracted folder unless the operator explicitly requests durable-state removal."
                if install_mode == InstallMode.PORTABLE
                else "Default cleanup should preserve durable state and remove only application-managed runtime integrations."
            ),
            destructive_confirmation_required=True,
        )

    def _build_bootstrap_evaluation(self) -> BootstrapEvaluation:
        restart_policy = self._build_restart_policy()
        lifecycle_hold_reason = self._migration_state.hold_reason or restart_policy.hold_reason
        return BootstrapEvaluation(
            startup_allowed=not lifecycle_hold_reason,
            install_state=self._install_state,
            migration_state=self._migration_state,
            registration_state=self._startup_policy,
            lifecycle_hold_reason=lifecycle_hold_reason,
            degraded_launch_reason="restart_hold" if restart_policy.hold_active else "",
            onboarding_required=self._onboarding.status != OnboardingStatus.COMPLETED,
            warnings=list(self._bootstrap.warnings) if self._bootstrapped else [],
        )

    def _record_previous_session_crashes(self) -> None:
        if self.config.runtime.core_session_path.exists():
            payload = self._load_json(self.config.runtime.core_session_path)
            self._append_crash_record(
                component="core",
                timestamp=utc_now_iso(),
                operator_summary="The core stopped unexpectedly before the last shutdown was recorded.",
            )
            self.config.runtime.core_session_path.unlink(missing_ok=True)
        if self.config.runtime.shell_session_path.exists():
            payload = self._load_json(self.config.runtime.shell_session_path)
            self._append_crash_record(
                component="shell",
                timestamp=utc_now_iso(),
                operator_summary="The shell stopped unexpectedly before it reported a clean detach.",
            )
            self.config.runtime.shell_session_path.unlink(missing_ok=True)
            self._shell_presence = None
            self._shell_detached = True

    def _append_crash_record(self, *, component: str, timestamp: str, operator_summary: str) -> None:
        record = CrashRecord(
            crash_id=uuid4().hex,
            component=component,
            version=self.config.version,
            timestamp=timestamp or utc_now_iso(),
            restart_attempted=self.config.lifecycle.auto_restart_core and component == "core",
            restart_outcome="pending" if component == "core" else "n/a",
            repeated_failure_window=self.config.lifecycle.max_core_restart_attempts,
            preserved_trace_location=str(self.config.core_log_file_path if component == "core" else self.config.ui_log_file_path),
            operator_visible_summary=operator_summary,
        )
        self._recent_crashes.insert(0, record)
        self._recent_crashes = self._recent_crashes[:16]

    def _publish_bootstrap_events(self) -> None:
        if self.events is None:
            return
        self.events.publish(
            event_family="lifecycle",
            event_type="lifecycle.install_state.resolved",
            subsystem="lifecycle",
            severity="info",
            visibility_scope="systems_surface",
            message=f"Install posture resolved as {self._install_state.install_mode.value}.",
            payload=self._install_state.to_dict(),
        )
        for record in self._recent_crashes[:1]:
            self.events.publish(
                event_family="lifecycle",
                event_type=f"lifecycle.{record.component}.previous_crash_detected",
                subsystem="lifecycle",
                severity="warning",
                visibility_scope="systems_surface",
                message=record.operator_visible_summary,
                payload=record.to_dict(),
            )
        if self._migration_state.status == MigrationStatus.COMPLETED:
            self.events.publish(
                event_family="lifecycle",
                event_type="lifecycle.runtime.updated",
                subsystem="lifecycle",
                severity="info",
                visibility_scope="systems_surface",
                message=f"Stormhelm updated from {self._migration_state.previous_version} to {self._migration_state.target_version}.",
                payload=self._migration_state.to_dict(),
            )
        if self._bootstrap.lifecycle_hold_reason:
            self.events.publish(
                event_family="lifecycle",
                event_type="lifecycle.runtime.hold",
                subsystem="lifecycle",
                severity="warning",
                visibility_scope="operator_blocking",
                message=self._bootstrap.lifecycle_hold_reason,
                payload=self._bootstrap.to_dict(),
            )

    def _startup_commands(self) -> dict[str, str]:
        if self.config.runtime.is_frozen:
            core_command = str(self.config.runtime.core_executable_path)
            shell_command = str(self.config.runtime.install_root / "stormhelm-ui.exe")
        else:
            core_command = f'"{sys.executable}" -m stormhelm.entrypoints.core'
            shell_command = f'"{sys.executable}" -m stormhelm.entrypoints.ui'
        return {"core": core_command, "shell": shell_command}

    def _persist_state(self) -> None:
        preserve_previous_boundary = self._migration_state.status == MigrationStatus.HOLD
        last_version = (
            str(self._persisted.get("last_version", "")).strip() or self.config.version
            if preserve_previous_boundary
            else self.config.version
        )
        last_protocol_version = (
            int(self._persisted.get("last_protocol_version", 0) or 0) or self.config.protocol_version
            if preserve_previous_boundary
            else self.config.protocol_version
        )
        last_install_mode = (
            str(self._persisted.get("last_install_mode", "")).strip() or self._install_state.install_mode.value
            if preserve_previous_boundary
            else self._install_state.install_mode.value
        )
        self._persisted.update(
            {
                "last_version": last_version,
                "last_protocol_version": last_protocol_version,
                "last_install_mode": last_install_mode,
                "last_runtime_mode": self._install_state.runtime_mode.value,
                "startup_policy": {
                    "startup_enabled": self._startup_policy.startup_enabled,
                    "start_core_with_windows": self._startup_policy.start_core_with_windows,
                    "start_shell_with_windows": self._startup_policy.start_shell_with_windows,
                    "tray_only_startup": self._startup_policy.tray_only_startup,
                    "ghost_ready_on_startup": self._startup_policy.ghost_ready_on_startup,
                },
                "onboarding": self._onboarding.to_dict(),
                "recent_crashes": [record.to_dict() for record in self._recent_crashes[:16]],
            }
        )
        self._write_json(self.config.runtime.lifecycle_state_path, self._persisted)

    def _crash_from_dict(self, payload: dict[str, Any]) -> CrashRecord:
        return CrashRecord(
            crash_id=str(payload.get("crash_id", uuid4().hex)),
            component=str(payload.get("component", "core")),
            version=str(payload.get("version", "")),
            timestamp=str(payload.get("timestamp", utc_now_iso())),
            restart_attempted=bool(payload.get("restart_attempted", False)),
            restart_outcome=str(payload.get("restart_outcome", "")),
            repeated_failure_window=int(payload.get("repeated_failure_window", 0) or 0),
            preserved_trace_location=str(payload.get("preserved_trace_location", "")),
            operator_visible_summary=str(payload.get("operator_visible_summary", "")),
        )

    def _load_shell_presence(self) -> ShellPresenceUpdate | None:
        payload = self._load_json(self.config.runtime.shell_session_path)
        if not payload:
            return None
        try:
            return ShellPresenceUpdate.from_dict(payload)
        except Exception:
            return None

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _default_startup_registration_probe(
    config: AppConfig,
    install_state: InstallState,
    policy: StartupPolicyState,
    commands: dict[str, str],
) -> dict[str, Any]:
    del config, install_state, commands
    if not sys.platform.startswith("win"):
        return {"registered_core": False, "registered_shell": False, "failure_reason": "unsupported_platform"}
    try:
        import winreg  # type: ignore

        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as handle:
            core_value = _safe_query_run_value(handle, "StormhelmCore")
            shell_value = _safe_query_run_value(handle, "StormhelmUI")
    except Exception as error:  # pragma: no cover - depends on host registry
        return {"registered_core": False, "registered_shell": False, "failure_reason": str(error)}
    return {
        "registered_core": bool(core_value) if policy.start_core_with_windows else False,
        "registered_shell": bool(shell_value) if policy.start_shell_with_windows else False,
        "failure_reason": "",
    }


def _safe_query_run_value(handle: Any, name: str) -> str:
    try:
        value, _ = handle.QueryValueEx(name)
        return str(value or "")
    except Exception:
        return ""


def _looks_installed(path: Path) -> bool:
    normalized_parts = [part.strip().lower() for part in path.parts]
    joined = "/".join(normalized_parts)
    install_markers = (
        "appdata/local/programs",
        "program files",
        "program files (x86)",
    )
    if any(marker in joined for marker in install_markers):
        return True
    candidates: list[Path] = []
    for env_name in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw).resolve())
    for candidate in candidates:
        try:
            path.relative_to(candidate)
            return True
        except ValueError:
            continue
    return False


def _age_seconds(value: str) -> float | None:
    timestamp = _parse_iso(value)
    if timestamp is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds())


def _is_within_failure_window(timestamp: str, window_seconds: float) -> bool:
    parsed = _parse_iso(timestamp)
    if parsed is None:
        return False
    return parsed >= datetime.now(timezone.utc) - timedelta(seconds=max(0.0, float(window_seconds)))


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
