from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from stormhelm.config.models import AppConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.lifecycle.models import (
    BootstrapEvaluation,
    CleanupExecutionState,
    CoreProcessStatus,
    CoreRuntimeState,
    CrashRecord,
    DestructiveCleanupPlan,
    InstallMode,
    InstallState,
    LifecycleActionRecord,
    LifecycleHoldReasonKind,
    LifecycleHoldState,
    LifecycleResolutionPlan,
    LifecycleResolutionState,
    LifecycleSnapshot,
    MigrationState,
    MigrationStatus,
    MutationTruthState,
    OnboardingState,
    OnboardingStatus,
    RegistrationStatus,
    RestartPolicyState,
    RuntimeMode,
    RuntimePaths,
    ShellPresenceState,
    ShellPresenceStatus,
    ShellPresenceUpdate,
    StartupPolicyState,
    StartupRegistrationState,
    TrayPresenceStatus,
    UninstallPlan,
)
from stormhelm.shared.time import utc_now_iso


STARTUP_VERIFICATION_STALE_AFTER_SECONDS = 600.0
DESTRUCTIVE_CONFIRMATION_STALE_AFTER_SECONDS = 300.0

StartupRegistrationProbe = Callable[[AppConfig, InstallState, StartupPolicyState, dict[str, str]], dict[str, Any]]
StartupRegistrationMutator = Callable[[AppConfig, InstallState, StartupPolicyState, dict[str, str]], dict[str, Any]]


class LifecycleController:
    def __init__(
        self,
        config: AppConfig,
        *,
        events: EventBuffer | None = None,
        startup_registration_probe: StartupRegistrationProbe | None = None,
        startup_registration_mutator: StartupRegistrationMutator | None = None,
    ) -> None:
        self.config = config
        self.events = events
        self._startup_registration_probe = startup_registration_probe or _default_startup_registration_probe
        self._startup_registration_mutator = startup_registration_mutator or _default_startup_registration_mutator
        self._persisted = self._load_json(self.config.runtime.lifecycle_state_path)
        self._recent_crashes = [self._crash_from_dict(item) for item in self._persisted.get("recent_crashes", [])]
        self._startup_registration = StartupRegistrationState.from_dict(self._persisted.get("startup_registration"))
        self._resolution_state = LifecycleResolutionState.from_dict(self._persisted.get("resolution_state"))
        self._destructive_cleanup_plan = DestructiveCleanupPlan.from_dict(self._persisted.get("destructive_cleanup_plan"))
        self._cleanup_execution = CleanupExecutionState.from_dict(self._persisted.get("cleanup_execution"))
        self._shell_presence_meta = self._load_shell_presence_meta()
        self._shell_presence = self._load_shell_presence()
        self._last_healthy_at = str(self._persisted.get("last_healthy_at", "")).strip()
        self._reconcile_pending_restart_resolution()
        self._install_state = self._build_install_state()
        self._runtime_paths = self._build_runtime_paths()
        self._startup_policy = self._build_startup_policy()
        self._migration_state = self._build_migration_state()
        self._onboarding = self._build_onboarding_state()
        self._bootstrapped = False
        self._bootstrap = self._build_bootstrap_evaluation()
        self._shell_detached = self._shell_presence is None

    @property
    def install_state(self) -> InstallState:
        return self._install_state

    def bootstrap(self) -> BootstrapEvaluation:
        now = utc_now_iso()
        self._install_state = self._build_install_state(detected_at=now)
        self._runtime_paths = self._build_runtime_paths()
        self._record_previous_session_crashes()
        self._startup_policy = self._build_startup_policy(verified_at=now)
        self._migration_state = self._build_migration_state()
        self._onboarding = self._build_onboarding_state()
        hold_state = self._build_hold_state()
        resolution_plan = self._build_resolution_plan(hold_state)
        resolution_state = self._sync_resolution_state(resolution_plan)

        warnings: list[str] = []
        if self._migration_state.migration_required and self._migration_state.status == MigrationStatus.COMPLETED:
            warnings.append(
                f"Version changed from {self._migration_state.previous_version} to {self._migration_state.target_version}."
            )
        if self._onboarding.status != OnboardingStatus.COMPLETED:
            warnings.append("Lifecycle onboarding still needs operator review.")
        if self._startup_policy.registration.operator_summary and self._startup_policy.registration_status in {
            RegistrationStatus.APPLIED,
            RegistrationStatus.BLOCKED,
            RegistrationStatus.FAILED,
            RegistrationStatus.STALE,
        }:
            warnings.append(self._startup_policy.registration.operator_summary)
        if resolution_state.last_resolution_summary and resolution_state.follow_up_required:
            warnings.append(resolution_state.last_resolution_summary)

        self._bootstrap = BootstrapEvaluation(
            startup_allowed=not hold_state.hold_active,
            install_state=self._install_state,
            migration_state=self._migration_state,
            registration_state=self._startup_policy,
            lifecycle_hold_reason=hold_state.hold_summary,
            degraded_launch_reason="restart_hold" if hold_state.hold_reason_kind == LifecycleHoldReasonKind.RESTART_REPEATED_FAILURES else "",
            onboarding_required=self._onboarding.status != OnboardingStatus.COMPLETED,
            warnings=warnings,
            hold_state=hold_state,
            resolution_plan=resolution_plan,
            resolution_state=resolution_state,
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

    def configure_startup_policy(
        self,
        *,
        startup_enabled: bool,
        start_core_with_windows: bool,
        start_shell_with_windows: bool,
        tray_only_startup: bool,
        ghost_ready_on_startup: bool,
    ) -> StartupPolicyState:
        self._install_state = self._build_install_state()
        normalized_enabled = bool(startup_enabled and (start_core_with_windows or start_shell_with_windows))
        desired_policy = {
            "startup_enabled": normalized_enabled,
            "start_core_with_windows": bool(normalized_enabled and start_core_with_windows),
            "start_shell_with_windows": bool(normalized_enabled and start_shell_with_windows),
            "tray_only_startup": bool(tray_only_startup),
            "ghost_ready_on_startup": bool(ghost_ready_on_startup),
        }
        now = utc_now_iso()
        registration = StartupRegistrationState.from_dict(self._persisted.get("startup_registration"))
        registration.requested_state = MutationTruthState.REQUESTED
        registration.attempted_state = MutationTruthState.UNKNOWN
        registration.applied_state = MutationTruthState.UNKNOWN
        registration.verified_state = MutationTruthState.UNKNOWN
        registration.blocked_reason = ""
        registration.failure_reason = ""
        registration.last_attempted_at = now
        registration.requested_core = desired_policy["start_core_with_windows"]
        registration.requested_shell = desired_policy["start_shell_with_windows"]
        registration.operator_summary = "Stormhelm recorded a startup mutation request."

        provisional_policy = StartupPolicyState(
            startup_enabled=desired_policy["startup_enabled"],
            start_core_with_windows=desired_policy["start_core_with_windows"],
            start_shell_with_windows=desired_policy["start_shell_with_windows"],
            tray_only_startup=desired_policy["tray_only_startup"],
            ghost_ready_on_startup=desired_policy["ghost_ready_on_startup"],
            registration_status=RegistrationStatus.NOT_REGISTERED,
            registered_core=False,
            registered_shell=False,
            mode_supported=bool(self._install_state.startup_capable),
            mode_reason="",
            registration=registration,
        )
        commands = self._startup_commands(provisional_policy)
        mode_supported = bool(self._install_state.startup_capable)

        if desired_policy["startup_enabled"] and not mode_supported:
            registration.attempted_state = MutationTruthState.BLOCKED
            registration.applied_state = MutationTruthState.BLOCKED
            registration.blocked_reason = "Startup registration requires installed packaged mode on Windows."
            registration.operator_summary = registration.blocked_reason
        elif not mode_supported and not desired_policy["startup_enabled"]:
            registration.operator_summary = "Stormhelm recorded the disabled startup request, but this posture cannot verify Windows registration."
        else:
            mutation = self._startup_registration_mutator(self.config, self._install_state, provisional_policy, commands)
            attempted = bool(mutation.get("attempted", False))
            registration.mutation_source = str(mutation.get("mutation_source", "")).strip()
            registration.blocked_reason = str(mutation.get("blocked_reason", "")).strip()
            registration.failure_reason = str(mutation.get("failure_reason", "")).strip()
            if attempted:
                registration.attempted_state = MutationTruthState.ATTEMPTED
            if registration.blocked_reason:
                registration.applied_state = MutationTruthState.BLOCKED
                registration.operator_summary = registration.blocked_reason
            elif registration.failure_reason:
                registration.applied_state = MutationTruthState.FAILED
                registration.operator_summary = registration.failure_reason
            elif attempted:
                registration.applied_state = MutationTruthState.APPLIED
                registration.operator_summary = "Stormhelm applied the startup mutation and is verifying the result."

        self._persisted["startup_policy"] = desired_policy
        self._persisted["startup_registration"] = registration.to_dict()
        self._startup_policy = self._build_startup_policy(verified_at=now)
        self._startup_registration = self._startup_policy.registration
        self._persisted["startup_registration"] = self._startup_registration.to_dict()
        self._persist_state()
        self._publish_startup_policy_event()
        return self._startup_policy

    def prepare_resolution_plan(self) -> LifecycleResolutionPlan:
        self._install_state = self._build_install_state()
        self._migration_state = self._build_migration_state()
        plan = self._build_resolution_plan(self._build_hold_state())
        self._resolution_state = self._sync_resolution_state(plan)
        self._persisted["resolution_state"] = self._resolution_state.to_dict()
        self._persist_state()
        return plan

    def resolve_lifecycle_hold(
        self,
        *,
        plan_id: str,
        resolution_kind: str,
        confirmation_kind: str,
        confirmed_summary: str,
    ) -> LifecycleResolutionState:
        now = utc_now_iso()
        self._install_state = self._build_install_state()
        self._migration_state = self._build_migration_state()
        hold_state = self._build_hold_state()
        plan = self._build_resolution_plan(hold_state)
        action = LifecycleActionRecord(
            action_kind="lifecycle_resolution",
            requested_at=now,
            attempted_at=now,
            initiated_by="operator",
            confirmation_kind=confirmation_kind,
            outcome="blocked",
        )
        state = self._sync_resolution_state(plan)
        state.resolution_requested = True
        state.last_action = action

        if not plan.plan_id or not plan.resolvable:
            state.resolution_failed = True
            state.follow_up_required = True
            state.last_resolution_summary = (
                hold_state.operator_action_needed
                or "Stormhelm cannot safely resolve this lifecycle hold automatically."
            )
            action.truth_summary = state.last_resolution_summary
            self._resolution_state = state
            self._persisted["resolution_state"] = state.to_dict()
            self._persist_state()
            return state

        if plan.plan_id != str(plan_id or "").strip() or plan.resolution_kind != str(resolution_kind or "").strip():
            state.resolution_failed = True
            state.follow_up_required = True
            state.last_resolution_summary = "Stormhelm blocked lifecycle resolution because the requested plan no longer matches the active hold."
            action.truth_summary = state.last_resolution_summary
            self._resolution_state = state
            self._persisted["resolution_state"] = state.to_dict()
            self._persist_state()
            return state

        if (
            plan.required_confirmation_kind != str(confirmation_kind or "").strip()
            or plan.summary != str(confirmed_summary or "").strip()
        ):
            state.resolution_failed = True
            state.follow_up_required = True
            state.last_resolution_summary = "Stormhelm blocked lifecycle resolution because the confirmation did not match the active resolution plan."
            action.truth_summary = state.last_resolution_summary
            self._resolution_state = state
            self._persisted["resolution_state"] = state.to_dict()
            self._persist_state()
            return state

        state.resolution_attempted = True
        stored_migration = dict(self._persisted.get("migration_state", {}))
        stored_migration["last_attempted_at"] = now
        action.completed_at = now

        if plan.hold_kind == LifecycleHoldReasonKind.INSTALL_MODE_CHANGED:
            self._persisted["last_install_mode"] = self._install_state.install_mode.value
            stored_migration["interrupted_recovery_state"] = ""
            self._persisted["migration_state"] = stored_migration
            state.resolution_completed = True
            state.resolution_failed = False
            state.resolution_partial = False
            state.resolution_abandoned = False
            state.restart_pending = False
            state.follow_up_required = False
            state.last_resolution_summary = "Stormhelm acknowledged the install boundary and preserved durable lifecycle state."
            action.outcome = "completed"
            action.truth_summary = state.last_resolution_summary
        elif plan.hold_kind == LifecycleHoldReasonKind.PROTOCOL_NEWER:
            self._persisted["last_protocol_version"] = self.config.protocol_version
            self._persisted["startup_registration"] = StartupRegistrationState().to_dict()
            self._persisted["shell_presence"] = {}
            self._persisted["recent_crashes"] = []
            stored_migration["interrupted_recovery_state"] = "restart_required_after_protocol_clear"
            self._persisted["migration_state"] = stored_migration
            self._startup_registration = StartupRegistrationState()
            self._shell_presence_meta = {}
            self._recent_crashes = []
            state.resolution_completed = False
            state.resolution_failed = False
            state.resolution_partial = True
            state.resolution_abandoned = False
            state.restart_pending = True
            state.follow_up_required = True
            state.last_resolution_summary = (
                "Stormhelm cleared incompatible lifecycle metadata, but a restart is still required before startup can continue."
            )
            action.outcome = "partial"
            action.truth_summary = state.last_resolution_summary
        else:
            state.resolution_failed = True
            state.follow_up_required = True
            state.last_resolution_summary = "Stormhelm cannot safely execute the requested lifecycle resolution."
            action.outcome = "failed"
            action.truth_summary = state.last_resolution_summary

        state.last_action = action
        self._resolution_state = state
        self._migration_state = self._build_migration_state()
        self._persisted["resolution_state"] = state.to_dict()
        self._persist_state()
        self._publish_resolution_event()
        return state

    def prepare_cleanup_plan(
        self,
        *,
        remove_startup_registration: bool = False,
        remove_logs: bool = False,
        remove_caches: bool = False,
        remove_durable_state: bool = False,
    ) -> DestructiveCleanupPlan:
        if not remove_durable_state:
            self._destructive_cleanup_plan = DestructiveCleanupPlan()
            self._persisted["destructive_cleanup_plan"] = self._destructive_cleanup_plan.to_dict()
            self._persist_state()
            return self._destructive_cleanup_plan
        plan = self._build_destructive_cleanup_plan(
            remove_startup_registration=remove_startup_registration,
            remove_logs=remove_logs,
            remove_caches=remove_caches,
            remove_durable_state=remove_durable_state,
        )
        self._destructive_cleanup_plan = plan
        self._persisted["destructive_cleanup_plan"] = plan.to_dict()
        self._persist_state()
        return plan

    def execute_cleanup(
        self,
        *,
        remove_startup_registration: bool = False,
        remove_logs: bool = False,
        remove_caches: bool = False,
        remove_durable_state: bool = False,
        destructive_confirmation_received: bool = False,
        destructive_confirmation: dict[str, Any] | None = None,
    ) -> CleanupExecutionState:
        now = utc_now_iso()
        removal_targets = self._requested_cleanup_targets(
            remove_startup_registration=remove_startup_registration,
            remove_logs=remove_logs,
            remove_caches=remove_caches,
            remove_durable_state=remove_durable_state,
        )
        cleanup = CleanupExecutionState(
            cleanup_intent="cleanup" if removal_targets else "preserve_only",
            destructive_confirmation_required=bool(remove_durable_state),
            destructive_confirmation_received=bool(destructive_confirmation_received),
            removal_targets=removal_targets,
            preserve_targets=["durable_state"] if not remove_durable_state else [],
            execution_attempted=False,
            execution_outcome="not_requested" if not removal_targets else "pending",
            destructive=bool(remove_durable_state),
            partial=False,
            attempted_targets=[],
            removed_targets=[],
            preserved_targets=self._preserved_cleanup_targets(
                remove_startup_registration=remove_startup_registration,
                remove_logs=remove_logs,
                remove_caches=remove_caches,
                remove_durable_state=remove_durable_state,
            ),
            failed_targets=[],
            skipped_targets=[],
            restart_required=False,
            operator_summary="No cleanup mutation was requested." if not removal_targets else "",
            last_action=LifecycleActionRecord(
                action_kind="cleanup_execution",
                requested_at=now,
                initiated_by="operator",
                confirmation_kind="destructive_cleanup_plan" if remove_durable_state else "",
                outcome="not_requested" if not removal_targets else "pending",
            ),
        )
        if not removal_targets:
            self._cleanup_execution = cleanup
            self._persisted["cleanup_execution"] = cleanup.to_dict()
            self._persist_state()
            return cleanup

        if remove_durable_state:
            valid_confirmation, confirmation_reason, plan = self._validate_destructive_cleanup_confirmation(
                destructive_confirmation_received=destructive_confirmation_received,
                destructive_confirmation=destructive_confirmation,
                remove_startup_registration=remove_startup_registration,
                remove_logs=remove_logs,
                remove_caches=remove_caches,
                remove_durable_state=remove_durable_state,
            )
            self._destructive_cleanup_plan = plan
            self._persisted["destructive_cleanup_plan"] = plan.to_dict()
            cleanup.last_action.outcome = "blocked"
            if not valid_confirmation:
                cleanup.execution_outcome = "blocked"
                cleanup.operator_summary = confirmation_reason
                cleanup.last_action.truth_summary = cleanup.operator_summary
                self._cleanup_execution = cleanup
                self._persisted["cleanup_execution"] = cleanup.to_dict()
                self._persist_state()
                self._publish_cleanup_event()
                return cleanup
            cleanup.destructive_confirmation_received = True
            cleanup.last_action.outcome = "attempted"
            plan.confirmation_consumed_at = now
            self._destructive_cleanup_plan = plan
            self._persisted["destructive_cleanup_plan"] = plan.to_dict()

        cleanup.execution_attempted = True
        cleanup.last_action.attempted_at = now
        exact_targets = self._exact_cleanup_targets(
            remove_startup_registration=remove_startup_registration,
            remove_logs=remove_logs,
            remove_caches=remove_caches,
            remove_durable_state=remove_durable_state,
        )
        cleanup.attempted_targets = list(exact_targets)

        if remove_startup_registration:
            updated = self.configure_startup_policy(
                startup_enabled=False,
                start_core_with_windows=False,
                start_shell_with_windows=False,
                tray_only_startup=self._startup_policy.tray_only_startup,
                ghost_ready_on_startup=self._startup_policy.ghost_ready_on_startup,
            )
            if updated.registration_status in {RegistrationStatus.DISABLED, RegistrationStatus.STALE}:
                cleanup.removed_targets.append("startup_registration")
            else:
                cleanup.failed_targets.append("startup_registration")

        if remove_logs:
            self._apply_directory_cleanup_result(
                label="logs_contents",
                root=self.config.storage.logs_dir,
                cleanup=cleanup,
            )
        if remove_caches:
            self._apply_directory_cleanup_result(
                label="cache_contents",
                root=self.config.storage.cache_dir,
                cleanup=cleanup,
            )
        if remove_durable_state:
            self._apply_directory_cleanup_result(
                label="data_dir_contents",
                root=self.config.storage.data_dir,
                cleanup=cleanup,
            )
            self._apply_file_cleanup_result(
                label="database_file",
                path=self.config.storage.database_path,
                cleanup=cleanup,
            )

        if cleanup.failed_targets and cleanup.removed_targets:
            cleanup.execution_outcome = "partial"
            cleanup.partial = True
            cleanup.operator_summary = (
                "Stormhelm removed the confirmed cleanup targets it could and reported the remaining failures exactly."
            )
        elif cleanup.failed_targets:
            cleanup.execution_outcome = "failed"
            cleanup.partial = False
            cleanup.operator_summary = "Stormhelm could not complete the requested cleanup."
        else:
            cleanup.execution_outcome = "completed"
            cleanup.partial = False
            cleanup.operator_summary = (
                "Stormhelm completed the requested cleanup and preserved the targets outside the confirmed scope."
            )

        cleanup.last_action.completed_at = utc_now_iso()
        cleanup.last_action.outcome = cleanup.execution_outcome
        cleanup.last_action.truth_summary = cleanup.operator_summary
        self._cleanup_execution = cleanup
        self._persisted["cleanup_execution"] = cleanup.to_dict()
        self._persist_state()
        self._publish_cleanup_event()
        return cleanup

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
        self._shell_presence_meta = {
            "last_heartbeat_at": observed_at,
            "detach_kind": "",
            "detach_reason": "",
        }
        self._write_json(self.config.runtime.shell_session_path, update.to_dict())
        self._persist_state()

    def record_shell_detached(self, pid: int | None = None) -> None:
        current = self._load_shell_presence()
        if current is not None and pid is not None and current.pid != pid:
            return
        self._shell_presence = None
        self._shell_detached = True
        self._shell_presence_meta = {
            "last_heartbeat_at": current.observed_at if current is not None else "",
            "detach_kind": "clean",
            "detach_reason": "Shell reported a clean detach.",
        }
        self.config.runtime.shell_session_path.unlink(missing_ok=True)
        self._persist_state()

    def status_snapshot(self) -> dict[str, Any]:
        now = utc_now_iso()
        self._install_state = self._build_install_state()
        self._runtime_paths = self._build_runtime_paths()
        self._startup_policy = self._build_startup_policy(verified_at=now)
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
        if not (start_core or start_shell):
            startup_enabled = False

        mode_supported = bool(self._install_state.startup_capable)
        desired_core = bool(startup_enabled and start_core)
        desired_shell = bool(startup_enabled and start_shell)
        registration = StartupRegistrationState.from_dict(self._persisted.get("startup_registration"))
        registration.requested_core = desired_core
        registration.requested_shell = desired_shell
        if startup_enabled and registration.requested_state == MutationTruthState.NOT_REQUESTED:
            registration.requested_state = MutationTruthState.REQUESTED
        if not startup_enabled and not registration.last_attempted_at and not registration.last_verified_at:
            registration.requested_state = MutationTruthState.NOT_REQUESTED

        if not mode_supported:
            if self._registration_is_stale(registration.last_verified_at):
                registration.verified_state = MutationTruthState.STALE
                registration.failure_reason = registration.failure_reason or (
                    "Stormhelm cannot refresh startup verification from the current posture."
                )
                registration.operator_summary = (
                    "Startup verification is stale because the current posture cannot refresh Windows registration."
                )
                registration_status = RegistrationStatus.STALE
            elif startup_enabled:
                if registration.blocked_reason:
                    registration.operator_summary = registration.blocked_reason
                    registration_status = RegistrationStatus.BLOCKED
                else:
                    registration.operator_summary = "Startup is requested, but the current posture cannot apply or verify Windows registration."
                    registration_status = RegistrationStatus.NOT_REGISTERED
            else:
                registration_status = RegistrationStatus.DISABLED
            self._startup_registration = registration
            return StartupPolicyState(
                startup_enabled=startup_enabled,
                start_core_with_windows=start_core,
                start_shell_with_windows=start_shell,
                tray_only_startup=tray_only,
                ghost_ready_on_startup=ghost_ready,
                registration_status=registration_status,
                registered_core=False,
                registered_shell=False,
                last_verified_at=registration.last_verified_at,
                failure_reason=registration.failure_reason or registration.blocked_reason,
                mode_supported=False,
                mode_reason="Startup registration requires installed packaged mode on Windows.",
                registration=registration,
            )

        probe = self._startup_registration_probe(
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
                registration=registration,
            ),
            self._startup_commands(
                StartupPolicyState(
                    startup_enabled=startup_enabled,
                    start_core_with_windows=start_core,
                    start_shell_with_windows=start_shell,
                    tray_only_startup=tray_only,
                    ghost_ready_on_startup=ghost_ready,
                    registration_status=RegistrationStatus.NOT_REGISTERED,
                    registered_core=False,
                    registered_shell=False,
                    registration=registration,
                )
            ),
        )
        registered_core = bool(probe.get("registered_core", False))
        registered_shell = bool(probe.get("registered_shell", False))
        probe_failure = str(probe.get("failure_reason", "")).strip()
        if probe_failure and not registration.failure_reason:
            registration.failure_reason = probe_failure
        verification_source = str(probe.get("verification_source", "")).strip() or "startup_registration_probe"
        desired_matches_actual = registered_core == desired_core and registered_shell == desired_shell

        if not probe_failure:
            registration.last_verified_at = verified_at or utc_now_iso()
            registration.verification_source = verification_source
            if desired_matches_actual:
                registration.verified_state = MutationTruthState.VERIFIED
                if startup_enabled:
                    registration.operator_summary = "Windows startup registration matches the requested posture."
                    registration_status = RegistrationStatus.REGISTERED
                else:
                    registration.operator_summary = "Windows startup registration is cleared."
                    registration_status = RegistrationStatus.DISABLED
            elif not startup_enabled and (registered_core or registered_shell):
                registration.verified_state = MutationTruthState.FAILED
                registration.failure_reason = "Windows startup registration still exists even though startup is disabled."
                registration.operator_summary = registration.failure_reason
                registration_status = RegistrationStatus.FAILED
            elif registration.blocked_reason:
                registration.verified_state = MutationTruthState.UNKNOWN
                registration.operator_summary = registration.blocked_reason
                registration_status = RegistrationStatus.BLOCKED
            elif registration.applied_state == MutationTruthState.APPLIED:
                registration.verified_state = MutationTruthState.FAILED
                registration.failure_reason = (
                    registration.failure_reason
                    or "Stormhelm applied startup registration, but Windows verification did not match the requested posture."
                )
                registration.operator_summary = registration.failure_reason
                registration_status = RegistrationStatus.FAILED
            else:
                registration.verified_state = MutationTruthState.UNKNOWN
                registration.operator_summary = "Startup is requested, but Windows registration does not match yet."
                registration_status = RegistrationStatus.NOT_REGISTERED
        else:
            if self._registration_is_stale(registration.last_verified_at):
                registration.verified_state = MutationTruthState.STALE
                registration.operator_summary = "Startup verification is stale; Stormhelm cannot confirm the current Windows registration."
                registration_status = RegistrationStatus.STALE
            elif registration.applied_state == MutationTruthState.APPLIED:
                registration.verified_state = MutationTruthState.UNKNOWN
                registration.operator_summary = "Startup registration was applied, but verification is currently unavailable."
                registration_status = RegistrationStatus.APPLIED
            elif registration.blocked_reason:
                registration.operator_summary = registration.blocked_reason
                registration_status = RegistrationStatus.BLOCKED
            elif registration.failure_reason:
                registration.operator_summary = registration.failure_reason
                registration_status = RegistrationStatus.FAILED
            elif startup_enabled:
                registration.operator_summary = "Startup is requested, but verification is currently unavailable."
                registration_status = RegistrationStatus.NOT_REGISTERED
            else:
                registration_status = RegistrationStatus.DISABLED

        self._startup_registration = registration
        return StartupPolicyState(
            startup_enabled=startup_enabled,
            start_core_with_windows=start_core,
            start_shell_with_windows=start_shell,
            tray_only_startup=tray_only,
            ghost_ready_on_startup=ghost_ready,
            registration_status=registration_status,
            registered_core=registered_core if not probe_failure else False,
            registered_shell=registered_shell if not probe_failure else False,
            last_verified_at=registration.last_verified_at,
            failure_reason=registration.failure_reason or registration.blocked_reason,
            mode_supported=True,
            mode_reason="",
            registration=registration,
        )

    def _build_migration_state(self) -> MigrationState:
        stored_migration = self._persisted.get("migration_state", {})
        previous_version = str(self._persisted.get("last_version", "")).strip()
        previous_protocol = int(self._persisted.get("last_protocol_version", 0) or 0)
        previous_install_mode = str(self._persisted.get("last_install_mode", "")).strip()
        interrupted_recovery_state = str(stored_migration.get("interrupted_recovery_state", ""))
        if interrupted_recovery_state == "restart_required_after_protocol_clear":
            hold_reason = "Stormhelm cleared incompatible lifecycle metadata, but a restart is still required before startup can continue."
            return MigrationState(
                previous_version=previous_version,
                target_version=self.config.version,
                status=MigrationStatus.HOLD,
                migration_required=True,
                migration_started=True,
                migration_completed=False,
                migration_failed=False,
                hold_reason=hold_reason,
                interrupted_recovery_state=interrupted_recovery_state,
                hold_reason_kind=LifecycleHoldReasonKind.PROTOCOL_NEWER,
                operator_action_needed="Restart Stormhelm to finish applying the cleared compatibility state.",
                actionable_summary="Compatibility recovery is waiting for a restart.",
                can_retry=False,
                retry_kind="restart_required",
                last_attempted_at=str(stored_migration.get("last_attempted_at", "")),
            )
        if previous_install_mode and previous_install_mode != self._install_state.install_mode.value:
            hold_reason = (
                f"Install posture changed from {previous_install_mode} to {self._install_state.install_mode.value}; "
                "review lifecycle boundaries before continuing."
            )
            return MigrationState(
                previous_version=previous_version,
                target_version=self.config.version,
                status=MigrationStatus.HOLD,
                migration_required=True,
                migration_started=False,
                migration_completed=False,
                migration_failed=False,
                hold_reason=hold_reason,
                interrupted_recovery_state=interrupted_recovery_state,
                hold_reason_kind=LifecycleHoldReasonKind.INSTALL_MODE_CHANGED,
                operator_action_needed=(
                    "Review the install-mode boundary, confirm whether startup registration should be re-applied, "
                    "and relaunch once the boundary change is understood."
                ),
                actionable_summary="Stormhelm is holding because the install posture changed between runs.",
                can_retry=False,
                retry_kind="operator_review",
                last_attempted_at=str(stored_migration.get("last_attempted_at", "")),
            )
        if previous_protocol and previous_protocol > self.config.protocol_version:
            hold_reason = "State was last written by a newer Stormhelm protocol version."
            return MigrationState(
                previous_version=previous_version,
                target_version=self.config.version,
                status=MigrationStatus.HOLD,
                migration_required=True,
                migration_started=False,
                migration_completed=False,
                migration_failed=False,
                hold_reason=hold_reason,
                interrupted_recovery_state=interrupted_recovery_state,
                hold_reason_kind=LifecycleHoldReasonKind.PROTOCOL_NEWER,
                operator_action_needed=(
                    "Reopen Stormhelm with a build that understands the newer protocol, or clear only the incompatible lifecycle state after review."
                ),
                actionable_summary="Stormhelm is holding because the stored lifecycle protocol is newer than this build.",
                can_retry=False,
                retry_kind="upgrade_build",
                last_attempted_at=str(stored_migration.get("last_attempted_at", "")),
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
                actionable_summary=f"Stormhelm updated from {previous_version} to {self.config.version}.",
                last_attempted_at=str(stored_migration.get("last_attempted_at", "")),
            )
        return MigrationState(
            previous_version=previous_version,
            target_version=self.config.version,
            status=MigrationStatus.CURRENT,
            migration_required=False,
            migration_started=False,
            migration_completed=False,
            migration_failed=False,
            interrupted_recovery_state=interrupted_recovery_state,
            last_attempted_at=str(stored_migration.get("last_attempted_at", "")),
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
        hold_state = self._build_hold_state()
        shell_presence_state = ShellPresenceState(
            shell_attached=False,
            last_heartbeat_at=str(self._shell_presence_meta.get("last_heartbeat_at", "")),
            heartbeat_fresh=False,
            detach_kind=str(self._shell_presence_meta.get("detach_kind", "")),
            detach_reason=str(self._shell_presence_meta.get("detach_reason", "")),
            controller_reconnect_allowed=not hold_state.hold_active,
        )
        if shell_presence is not None:
            shell_pid = shell_presence.pid
            shell_mode = shell_presence.mode
            shell_presence_state.last_heartbeat_at = shell_presence.observed_at
            age = _age_seconds(shell_presence.observed_at)
            if age is not None and age > self.config.lifecycle.shell_stale_after_seconds:
                shell_status = ShellPresenceStatus.STALE
                tray_status = TrayPresenceStatus.STALE if shell_presence.tray_present else TrayPresenceStatus.ABSENT
                shell_presence_state.detach_kind = "heartbeat_stale"
                shell_presence_state.detach_reason = "Shell heartbeat is stale; tray presence may no longer reflect reality."
                shell_presence_state.heartbeat_fresh = False
            else:
                shell_status = ShellPresenceStatus.VISIBLE if shell_presence.window_visible else ShellPresenceStatus.HIDDEN
                tray_status = TrayPresenceStatus.PRESENT if shell_presence.tray_present else TrayPresenceStatus.ABSENT
                connected_clients = 1
                shell_presence_state.shell_attached = True
                shell_presence_state.heartbeat_fresh = True
                shell_presence_state.detach_kind = ""
                shell_presence_state.detach_reason = ""
        core_status = CoreProcessStatus.HELD if hold_state.hold_active else CoreProcessStatus.ALIVE
        return CoreRuntimeState(
            core_status=core_status,
            shell_status=shell_status,
            tray_status=tray_status,
            connected_clients=connected_clients,
            last_healthy_at=self._last_healthy_at or utc_now_iso(),
            degraded_mode=hold_state.hold_active,
            pending_restart_reason=hold_state.hold_summary,
            shell_pid=shell_pid,
            shell_mode=shell_mode,
            shell_presence=shell_presence_state,
        )

    def _build_restart_policy(self) -> RestartPolicyState:
        core_attempts_in_window = 0
        shell_failures_in_window = 0
        for record in self._recent_crashes:
            if not _is_within_failure_window(record.timestamp, self.config.lifecycle.restart_failure_window_seconds):
                continue
            if record.component == "core":
                core_attempts_in_window += 1
            elif record.component == "shell":
                shell_failures_in_window += 1
        hold_active = core_attempts_in_window >= self.config.lifecycle.max_core_restart_attempts > 0
        hold_reason = (
            "Stormhelm observed repeated core failures in the recent restart window."
            if hold_active
            else ""
        )
        last_core_crash = next((record for record in self._recent_crashes if record.component == "core"), None)
        last_shell_crash = next((record for record in self._recent_crashes if record.component == "shell"), None)
        dual_failure_detected = bool(last_core_crash and last_shell_crash) and _is_within_failure_window(
            last_shell_crash.timestamp,
            self.config.lifecycle.restart_failure_window_seconds,
        )
        return RestartPolicyState(
            auto_restart_core=self.config.lifecycle.auto_restart_core,
            max_restart_attempts=self.config.lifecycle.max_core_restart_attempts,
            attempts_in_window=core_attempts_in_window,
            hold_active=hold_active,
            hold_reason=hold_reason,
            window_seconds=self.config.lifecycle.restart_failure_window_seconds,
            restart_policy="bounded",
            restart_attempts_in_window=core_attempts_in_window,
            repeated_failure_window=self.config.lifecycle.restart_failure_window_seconds,
            hold_after_repeated_failures=hold_active,
            last_restart_reason=last_core_crash.operator_visible_summary if last_core_crash else "",
            last_restart_outcome=last_core_crash.restart_outcome if last_core_crash else "",
            last_healthy_at=getattr(self, "_last_healthy_at", "") or "",
            shell_failures_in_window=shell_failures_in_window,
            dual_failure_detected=dual_failure_detected,
        )

    def _build_hold_state(self) -> LifecycleHoldState:
        restart_policy = self._build_restart_policy()
        if self._migration_state.status == MigrationStatus.HOLD:
            return LifecycleHoldState(
                hold_active=True,
                hold_reason_kind=self._migration_state.hold_reason_kind,
                hold_summary=self._migration_state.hold_reason,
                operator_action_needed=self._migration_state.operator_action_needed,
                can_retry=self._migration_state.can_retry,
                retry_kind=self._migration_state.retry_kind,
                degraded_launch_allowed=False,
            )
        if restart_policy.hold_active:
            return LifecycleHoldState(
                hold_active=True,
                hold_reason_kind=LifecycleHoldReasonKind.RESTART_REPEATED_FAILURES,
                hold_summary=restart_policy.hold_reason,
                operator_action_needed="Inspect the most recent core crash, then retry after the repeated-failure window or after operator review.",
                can_retry=True,
                retry_kind="restart_after_review",
                degraded_launch_allowed=False,
            )
        return LifecycleHoldState()

    def _build_uninstall_plan(self) -> UninstallPlan:
        install_mode = self._install_state.install_mode
        registration_uncertain = self._startup_policy.registration.verified_state in {
            MutationTruthState.UNKNOWN,
            MutationTruthState.STALE,
        }
        cleanup_notes = (
            self._cleanup_execution.operator_summary
            or self._destructive_cleanup_plan.operator_summary
            or (
                "Portable cleanup should remove only the extracted folder unless the operator explicitly requests durable-state removal."
                if install_mode == InstallMode.PORTABLE
                else "Default cleanup should preserve durable state and remove only application-managed runtime integrations."
            )
        )
        return UninstallPlan(
            remove_binaries=install_mode != InstallMode.SOURCE,
            remove_shortcuts=install_mode == InstallMode.INSTALLED,
            remove_startup_registration=bool(
                self._startup_policy.registered_core
                or self._startup_policy.registered_shell
                or registration_uncertain
            ),
            remove_caches=False,
            remove_logs=False,
            remove_durable_state=False,
            portable_cleanup_notes=cleanup_notes,
            destructive_confirmation_required=True,
            destructive_cleanup_plan=self._destructive_cleanup_plan,
            cleanup_execution=self._cleanup_execution,
        )

    def _build_bootstrap_evaluation(self) -> BootstrapEvaluation:
        hold_state = self._build_hold_state()
        resolution_plan = self._build_resolution_plan(hold_state)
        resolution_state = self._sync_resolution_state(resolution_plan)
        warnings = list(self._bootstrap.warnings) if self._bootstrapped else []
        return BootstrapEvaluation(
            startup_allowed=not hold_state.hold_active,
            install_state=self._install_state,
            migration_state=self._migration_state,
            registration_state=self._startup_policy,
            lifecycle_hold_reason=hold_state.hold_summary,
            degraded_launch_reason="restart_hold" if hold_state.hold_reason_kind == LifecycleHoldReasonKind.RESTART_REPEATED_FAILURES else "",
            onboarding_required=self._onboarding.status != OnboardingStatus.COMPLETED,
            warnings=warnings,
            hold_state=hold_state,
            resolution_plan=resolution_plan,
            resolution_state=resolution_state,
        )

    def _build_resolution_plan(self, hold_state: LifecycleHoldState | None = None) -> LifecycleResolutionPlan:
        active_hold = hold_state or self._build_hold_state()
        existing_plan = self._resolution_state.active_plan
        if not active_hold.hold_active:
            return LifecycleResolutionPlan()

        if active_hold.hold_reason_kind == LifecycleHoldReasonKind.INSTALL_MODE_CHANGED:
            resolution_kind = "acknowledge_install_mode_change"
            return LifecycleResolutionPlan(
                plan_id=existing_plan.plan_id
                if existing_plan.hold_kind == LifecycleHoldReasonKind.INSTALL_MODE_CHANGED
                and existing_plan.resolution_kind == resolution_kind
                else uuid4().hex,
                hold_kind=LifecycleHoldReasonKind.INSTALL_MODE_CHANGED,
                resolution_kind=resolution_kind,
                summary="Acknowledge the install boundary and preserve durable state.",
                preconditions=[
                    "The current install posture must still match the active hold.",
                    "The operator must confirm the install boundary summary before Stormhelm mutates the hold state.",
                ],
                required_confirmation_kind="acknowledge_resolution_plan",
                preserve_targets=["durable_state"],
                clear_targets=["migration_hold_marker"],
                restart_required=False,
                retry_allowed=False,
                operator_action_notes=active_hold.operator_action_needed,
                resolvable=True,
            )

        if active_hold.hold_reason_kind == LifecycleHoldReasonKind.PROTOCOL_NEWER:
            resolution_kind = "clear_incompatible_lifecycle_state"
            return LifecycleResolutionPlan(
                plan_id=existing_plan.plan_id
                if existing_plan.hold_kind == LifecycleHoldReasonKind.PROTOCOL_NEWER
                and existing_plan.resolution_kind == resolution_kind
                else uuid4().hex,
                hold_kind=LifecycleHoldReasonKind.PROTOCOL_NEWER,
                resolution_kind=resolution_kind,
                summary="Clear incompatible lifecycle metadata and preserve durable state.",
                preconditions=[
                    "The stored lifecycle protocol must still be newer than this build.",
                    "Stormhelm must bind the operator confirmation to this exact compatibility-clearing plan.",
                ],
                required_confirmation_kind="acknowledge_resolution_plan",
                preserve_targets=["durable_state"],
                clear_targets=["startup_registration_state", "shell_presence_state", "recent_crashes"],
                restart_required=True,
                retry_allowed=False,
                operator_action_notes="Stormhelm can clear only the incompatible lifecycle metadata. Durable task and memory state stay preserved.",
                resolvable=True,
            )

        return LifecycleResolutionPlan(
            plan_id=uuid4().hex,
            hold_kind=active_hold.hold_reason_kind,
            resolution_kind="manual_only",
            summary=active_hold.hold_summary or "This lifecycle hold still requires manual operator review.",
            preconditions=["Manual review is still required before Stormhelm can continue."],
            required_confirmation_kind="manual_only",
            preserve_targets=["durable_state"],
            clear_targets=[],
            restart_required=False,
            retry_allowed=active_hold.can_retry,
            operator_action_notes=active_hold.operator_action_needed,
            resolvable=False,
        )

    def _sync_resolution_state(self, plan: LifecycleResolutionPlan) -> LifecycleResolutionState:
        state = self._resolution_state
        if not plan.plan_id and not state.restart_pending:
            state.active_plan = LifecycleResolutionPlan()
            if not state.resolution_failed:
                state.follow_up_required = False
            return state
        state.active_plan = plan
        if plan.plan_id and not state.resolution_completed and not state.restart_pending:
            state.follow_up_required = state.follow_up_required or bool(plan.plan_id)
        return state

    def _build_destructive_cleanup_plan(
        self,
        *,
        remove_startup_registration: bool,
        remove_logs: bool,
        remove_caches: bool,
        remove_durable_state: bool,
    ) -> DestructiveCleanupPlan:
        del remove_durable_state
        return DestructiveCleanupPlan(
            plan_id=uuid4().hex,
            destructive_targets=["data_dir_contents", "database_file"],
            preserved_targets=self._preserved_cleanup_targets(
                remove_startup_registration=remove_startup_registration,
                remove_logs=remove_logs,
                remove_caches=remove_caches,
                remove_durable_state=True,
            ),
            required_confirmation="destructive_cleanup_plan",
            confirmation_bound_operation=self._cleanup_operation_signature(
                remove_startup_registration=remove_startup_registration,
                remove_logs=remove_logs,
                remove_caches=remove_caches,
                remove_durable_state=True,
            ),
            confirmation_expires_at=(
                datetime.now(timezone.utc) + timedelta(seconds=DESTRUCTIVE_CONFIRMATION_STALE_AFTER_SECONDS)
            ).isoformat().replace("+00:00", "Z"),
            confirmation_consumed_at="",
            restart_required=False,
            operator_summary="Destructive cleanup needs fresh confirmation for durable local state removal.",
        )

    def _cleanup_operation_signature(
        self,
        *,
        remove_startup_registration: bool,
        remove_logs: bool,
        remove_caches: bool,
        remove_durable_state: bool,
    ) -> str:
        return (
            "destructive_cleanup"
            f"|startup={int(bool(remove_startup_registration))}"
            f"|logs={int(bool(remove_logs))}"
            f"|caches={int(bool(remove_caches))}"
            f"|durable={int(bool(remove_durable_state))}"
        )

    def _requested_cleanup_targets(
        self,
        *,
        remove_startup_registration: bool,
        remove_logs: bool,
        remove_caches: bool,
        remove_durable_state: bool,
    ) -> list[str]:
        return [
            target
            for target, enabled in (
                ("startup_registration", remove_startup_registration),
                ("logs", remove_logs),
                ("caches", remove_caches),
                ("durable_state", remove_durable_state),
            )
            if enabled
        ]

    def _exact_cleanup_targets(
        self,
        *,
        remove_startup_registration: bool,
        remove_logs: bool,
        remove_caches: bool,
        remove_durable_state: bool,
    ) -> list[str]:
        targets: list[str] = []
        if remove_startup_registration:
            targets.append("startup_registration")
        if remove_logs:
            targets.append("logs_contents")
        if remove_caches:
            targets.append("cache_contents")
        if remove_durable_state:
            targets.extend(["data_dir_contents", "database_file"])
        return targets

    def _preserved_cleanup_targets(
        self,
        *,
        remove_startup_registration: bool,
        remove_logs: bool,
        remove_caches: bool,
        remove_durable_state: bool,
    ) -> list[str]:
        preserved = ["lifecycle_state", "first_run_marker"]
        if not remove_startup_registration:
            preserved.append("startup_registration")
        if not remove_logs:
            preserved.append("logs_contents")
        if not remove_caches:
            preserved.append("cache_contents")
        if not remove_durable_state:
            preserved.extend(["data_dir_contents", "database_file"])
        return preserved

    def _validate_destructive_cleanup_confirmation(
        self,
        *,
        destructive_confirmation_received: bool,
        destructive_confirmation: dict[str, Any] | None,
        remove_startup_registration: bool,
        remove_logs: bool,
        remove_caches: bool,
        remove_durable_state: bool,
    ) -> tuple[bool, str, DestructiveCleanupPlan]:
        del remove_durable_state
        expected_operation = self._cleanup_operation_signature(
            remove_startup_registration=remove_startup_registration,
            remove_logs=remove_logs,
            remove_caches=remove_caches,
            remove_durable_state=True,
        )
        plan = self._destructive_cleanup_plan
        if not plan.plan_id:
            plan = self._build_destructive_cleanup_plan(
                remove_startup_registration=remove_startup_registration,
                remove_logs=remove_logs,
                remove_caches=remove_caches,
                remove_durable_state=True,
            )
            return False, plan.operator_summary, plan
        if plan.confirmation_bound_operation != expected_operation:
            return (
                False,
                "Stormhelm blocked destructive cleanup because the confirmed plan no longer matches the requested scope.",
                plan,
            )
        if plan.confirmation_consumed_at:
            return False, "Stormhelm blocked destructive cleanup because that confirmation has already been consumed.", plan
        expires_at = _parse_iso(plan.confirmation_expires_at)
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            return False, "Stormhelm blocked destructive cleanup because the confirmation is no longer fresh.", plan
        if not destructive_confirmation_received or not isinstance(destructive_confirmation, dict):
            return False, plan.operator_summary, plan
        confirmed_at = str(destructive_confirmation.get("confirmed_at", "")).strip()
        if confirmed_at and (age := _age_seconds(confirmed_at)) is not None and age > DESTRUCTIVE_CONFIRMATION_STALE_AFTER_SECONDS:
            return False, "Stormhelm blocked destructive cleanup because the confirmation is no longer fresh.", plan
        if not bool(destructive_confirmation.get("destructive_intent", False)):
            return False, "Stormhelm blocked destructive cleanup because explicit destructive intent was not confirmed.", plan
        if str(destructive_confirmation.get("plan_id", "")).strip() != plan.plan_id:
            return False, "Stormhelm blocked destructive cleanup because the confirmation was bound to a different plan.", plan
        if str(destructive_confirmation.get("operation", "")).strip() != plan.confirmation_bound_operation:
            return False, "Stormhelm blocked destructive cleanup because the confirmation no longer matches the requested scope.", plan
        if str(destructive_confirmation.get("confirmation_kind", "")).strip() != plan.required_confirmation:
            return False, "Stormhelm blocked destructive cleanup because the confirmation kind did not match the active plan.", plan
        if str(destructive_confirmation.get("confirmed_summary", "")).strip() != plan.operator_summary:
            return False, "Stormhelm blocked destructive cleanup because the confirmation summary did not match the active plan.", plan
        return True, "", plan

    def _apply_directory_cleanup_result(self, *, label: str, root: Path, cleanup: CleanupExecutionState) -> None:
        if not root.exists():
            cleanup.skipped_targets.append(label)
            return
        failures = self._clear_directory_contents(root)
        if failures:
            cleanup.failed_targets.append(label)
            return
        cleanup.removed_targets.append(label)

    def _apply_file_cleanup_result(self, *, label: str, path: Path, cleanup: CleanupExecutionState) -> None:
        if not path.exists():
            cleanup.skipped_targets.append(label)
            return
        try:
            path.unlink(missing_ok=True)
        except Exception:
            cleanup.failed_targets.append(label)
            return
        cleanup.removed_targets.append(label)

    def _reconcile_pending_restart_resolution(self) -> None:
        stored_migration = self._persisted.get("migration_state", {})
        interrupted_recovery_state = str(stored_migration.get("interrupted_recovery_state", ""))
        if interrupted_recovery_state != "restart_required_after_protocol_clear":
            return
        if self.config.runtime.core_session_path.exists():
            return
        self._resolution_state.restart_pending = False
        self._resolution_state.follow_up_required = False
        self._resolution_state.resolution_partial = False
        self._resolution_state.resolution_completed = True
        self._resolution_state.last_resolution_summary = "Stormhelm resumed after the required lifecycle restart."
        self._resolution_state.last_action.completed_at = self._resolution_state.last_action.completed_at or utc_now_iso()
        self._resolution_state.last_action.outcome = "completed"
        self._resolution_state.last_action.truth_summary = self._resolution_state.last_resolution_summary
        stored_migration["interrupted_recovery_state"] = ""
        self._persisted["migration_state"] = stored_migration

    def _record_previous_session_crashes(self) -> None:
        if self.config.runtime.core_session_path.exists():
            self._load_json(self.config.runtime.core_session_path)
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
            self._shell_presence_meta = {
                "last_heartbeat_at": str(payload.get("observed_at", payload.get("started_at", ""))),
                "detach_kind": "unexpected_exit",
                "detach_reason": "The shell stopped unexpectedly before it reported a clean detach.",
            }
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

    def _publish_startup_policy_event(self) -> None:
        if self.events is None:
            return
        self.events.publish(
            event_family="lifecycle",
            event_type="lifecycle.startup.registration.updated",
            subsystem="lifecycle",
            severity="info" if self._startup_policy.registration_status in {RegistrationStatus.REGISTERED, RegistrationStatus.DISABLED} else "warning",
            visibility_scope="systems_surface",
            message=self._startup_policy.registration.operator_summary or "Startup registration state updated.",
            payload=self._startup_policy.to_dict(),
        )

    def _publish_cleanup_event(self) -> None:
        if self.events is None:
            return
        self.events.publish(
            event_family="lifecycle",
            event_type="lifecycle.cleanup.executed",
            subsystem="lifecycle",
            severity="info" if self._cleanup_execution.execution_outcome in {"completed", "partial"} else "warning",
            visibility_scope="systems_surface",
            message=self._cleanup_execution.operator_summary,
            payload=self._cleanup_execution.to_dict(),
        )

    def _publish_resolution_event(self) -> None:
        if self.events is None:
            return
        self.events.publish(
            event_family="lifecycle",
            event_type="lifecycle.resolution.updated",
            subsystem="lifecycle",
            severity="info" if not self._resolution_state.follow_up_required else "warning",
            visibility_scope="systems_surface",
            message=self._resolution_state.last_resolution_summary or "Lifecycle resolution state updated.",
            payload=self._resolution_state.to_dict(),
        )

    def _startup_commands(self, policy: StartupPolicyState | None = None) -> dict[str, str]:
        active_policy = policy or self._startup_policy
        if self.config.runtime.is_frozen:
            core_parts = [str(self.config.runtime.core_executable_path)]
            shell_parts = [str(self.config.runtime.install_root / "stormhelm-ui.exe")]
        else:
            core_parts = [sys.executable, "-m", "stormhelm.entrypoints.core"]
            shell_parts = [sys.executable, "-m", "stormhelm.entrypoints.ui"]

        if active_policy.tray_only_startup:
            shell_parts.append("--start-hidden")
        elif active_policy.ghost_ready_on_startup:
            shell_parts.extend(["--startup-mode", "ghost"])

        return {
            "core": subprocess.list2cmdline(core_parts),
            "shell": subprocess.list2cmdline(shell_parts),
        }

    def _persist_state(self) -> None:
        preserve_previous_boundary = (
            self._migration_state.status == MigrationStatus.HOLD
            and not self._resolution_state.resolution_completed
            and not self._resolution_state.resolution_partial
        )
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
                "last_healthy_at": self._last_healthy_at,
                "startup_policy": {
                    "startup_enabled": self._startup_policy.startup_enabled,
                    "start_core_with_windows": self._startup_policy.start_core_with_windows,
                    "start_shell_with_windows": self._startup_policy.start_shell_with_windows,
                    "tray_only_startup": self._startup_policy.tray_only_startup,
                    "ghost_ready_on_startup": self._startup_policy.ghost_ready_on_startup,
                },
                "startup_registration": self._startup_registration.to_dict(),
                "resolution_state": self._resolution_state.to_dict(),
                "shell_presence": self._shell_presence_meta,
                "destructive_cleanup_plan": self._destructive_cleanup_plan.to_dict(),
                "cleanup_execution": self._cleanup_execution.to_dict(),
                "migration_state": {
                    "interrupted_recovery_state": self._migration_state.interrupted_recovery_state,
                    "last_attempted_at": self._migration_state.last_attempted_at,
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

    def _load_shell_presence_meta(self) -> dict[str, str]:
        payload = self._persisted.get("shell_presence", {})
        if not isinstance(payload, dict):
            return {}
        return {
            "last_heartbeat_at": str(payload.get("last_heartbeat_at", "")),
            "detach_kind": str(payload.get("detach_kind", "")),
            "detach_reason": str(payload.get("detach_reason", "")),
        }

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

    def _registration_is_stale(self, last_verified_at: str) -> bool:
        age = _age_seconds(last_verified_at)
        return age is not None and age > STARTUP_VERIFICATION_STALE_AFTER_SECONDS

    def _clear_directory_contents(self, root: Path) -> list[str]:
        failures: list[str] = []
        if not root.exists():
            return failures
        for child in root.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
            except Exception as error:
                failures.append(f"Could not remove {child}: {error}")
        return failures


def _default_startup_registration_probe(
    config: AppConfig,
    install_state: InstallState,
    policy: StartupPolicyState,
    commands: dict[str, str],
) -> dict[str, Any]:
    del config, install_state, policy, commands
    if not sys.platform.startswith("win"):
        return {
            "registered_core": False,
            "registered_shell": False,
            "failure_reason": "unsupported_platform",
            "verification_source": "unsupported_platform",
        }
    try:
        import winreg  # type: ignore

        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as handle:
            core_value = _safe_query_run_value(handle, "StormhelmCore")
            shell_value = _safe_query_run_value(handle, "StormhelmUI")
    except FileNotFoundError:
        core_value = ""
        shell_value = ""
    except Exception as error:  # pragma: no cover - depends on host registry
        return {
            "registered_core": False,
            "registered_shell": False,
            "failure_reason": str(error),
            "verification_source": "windows_run_key",
        }
    return {
        "registered_core": bool(core_value),
        "registered_shell": bool(shell_value),
        "failure_reason": "",
        "verification_source": "windows_run_key",
    }


def _default_startup_registration_mutator(
    config: AppConfig,
    install_state: InstallState,
    policy: StartupPolicyState,
    commands: dict[str, str],
) -> dict[str, Any]:
    del config, install_state
    if not sys.platform.startswith("win"):
        return {"attempted": False, "blocked_reason": "unsupported_platform", "mutation_source": "unsupported_platform"}
    try:
        import winreg  # type: ignore

        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key) as handle:
            if policy.startup_enabled and policy.start_core_with_windows:
                winreg.SetValueEx(handle, "StormhelmCore", 0, winreg.REG_SZ, commands["core"])
            else:
                _safe_delete_run_value(handle, "StormhelmCore")
            if policy.startup_enabled and policy.start_shell_with_windows:
                winreg.SetValueEx(handle, "StormhelmUI", 0, winreg.REG_SZ, commands["shell"])
            else:
                _safe_delete_run_value(handle, "StormhelmUI")
        return {"attempted": True, "blocked_reason": "", "failure_reason": "", "mutation_source": "windows_run_key"}
    except PermissionError as error:  # pragma: no cover - depends on host registry
        return {"attempted": True, "blocked_reason": str(error), "failure_reason": "", "mutation_source": "windows_run_key"}
    except Exception as error:  # pragma: no cover - depends on host registry
        return {"attempted": True, "blocked_reason": "", "failure_reason": str(error), "mutation_source": "windows_run_key"}


def _safe_query_run_value(handle: Any, name: str) -> str:
    try:
        value, _ = handle.QueryValueEx(name)
        return str(value or "")
    except Exception:
        return ""


def _safe_delete_run_value(handle: Any, name: str) -> None:
    try:
        handle.DeleteValue(name)
    except Exception:
        return


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
