from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


class InstallMode(str, Enum):
    SOURCE = "source"
    PORTABLE = "portable"
    INSTALLED = "installed"


class RuntimeMode(str, Enum):
    SOURCE = "source"
    PACKAGED = "packaged"


class RegistrationStatus(str, Enum):
    DISABLED = "disabled"
    REGISTERED = "registered"
    NOT_REGISTERED = "not_registered"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class CoreProcessStatus(str, Enum):
    STARTING = "starting"
    ALIVE = "alive"
    STOPPING = "stopping"
    HELD = "held"


class ShellPresenceStatus(str, Enum):
    UNKNOWN = "unknown"
    VISIBLE = "visible"
    HIDDEN = "hidden"
    DETACHED = "detached"
    STALE = "stale"


class TrayPresenceStatus(str, Enum):
    UNKNOWN = "unknown"
    PRESENT = "present"
    ABSENT = "absent"


class MigrationStatus(str, Enum):
    CURRENT = "current"
    REQUIRED = "required"
    COMPLETED = "completed"
    HOLD = "hold"


class OnboardingStatus(str, Enum):
    REQUIRED = "required"
    DEFERRED = "deferred"
    COMPLETED = "completed"


@dataclass(slots=True)
class RuntimePaths:
    install_root: str
    resource_root: str
    user_data_root: str
    state_root: str
    cache_root: str
    log_root: str
    mode_source: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class InstallState:
    install_mode: InstallMode
    runtime_mode: RuntimeMode
    install_channel: str
    install_detected_at: str
    startup_capable: bool
    uninstall_capable: bool
    migration_capable: bool
    mode_source: str
    confidence: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class StartupPolicyState:
    startup_enabled: bool
    start_core_with_windows: bool
    start_shell_with_windows: bool
    tray_only_startup: bool
    ghost_ready_on_startup: bool
    registration_status: RegistrationStatus
    registered_core: bool
    registered_shell: bool
    last_verified_at: str = ""
    failure_reason: str = ""
    mode_supported: bool = False
    mode_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class CoreRuntimeState:
    core_status: CoreProcessStatus
    shell_status: ShellPresenceStatus
    tray_status: TrayPresenceStatus
    connected_clients: int
    last_healthy_at: str
    degraded_mode: bool
    pending_restart_reason: str = ""
    shell_pid: int | None = None
    shell_mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class CrashRecord:
    crash_id: str
    component: str
    version: str
    timestamp: str
    restart_attempted: bool
    restart_outcome: str
    repeated_failure_window: int
    preserved_trace_location: str
    operator_visible_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class RestartPolicyState:
    auto_restart_core: bool
    max_restart_attempts: int
    attempts_in_window: int
    hold_active: bool
    hold_reason: str
    window_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class MigrationState:
    previous_version: str
    target_version: str
    status: MigrationStatus
    migration_required: bool
    migration_started: bool
    migration_completed: bool
    migration_failed: bool
    hold_reason: str = ""
    backup_marker: str = ""
    interrupted_recovery_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class BootstrapEvaluation:
    startup_allowed: bool
    install_state: InstallState
    migration_state: MigrationState
    registration_state: StartupPolicyState
    lifecycle_hold_reason: str
    degraded_launch_reason: str
    onboarding_required: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class OnboardingState:
    status: OnboardingStatus
    startup_preference_chosen: bool
    background_preference_chosen: bool
    trust_setup_state: str

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "OnboardingState":
        data = payload or {}
        return cls(
            status=OnboardingStatus(str(data.get("status", OnboardingStatus.REQUIRED.value))),
            startup_preference_chosen=bool(data.get("startup_preference_chosen", False)),
            background_preference_chosen=bool(data.get("background_preference_chosen", False)),
            trust_setup_state=str(data.get("trust_setup_state", "pending")),
        )


@dataclass(slots=True)
class UninstallPlan:
    remove_binaries: bool
    remove_shortcuts: bool
    remove_startup_registration: bool
    remove_caches: bool
    remove_logs: bool
    remove_durable_state: bool
    portable_cleanup_notes: str
    destructive_confirmation_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class ShellPresenceUpdate:
    pid: int
    mode: str
    window_visible: bool
    tray_present: bool
    hide_to_tray_on_close: bool
    ghost_reveal_target: float
    event: str = "heartbeat"
    observed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ShellPresenceUpdate":
        return cls(
            pid=int(payload.get("pid", 0) or 0),
            mode=str(payload.get("mode", "ghost")),
            window_visible=bool(payload.get("window_visible", False)),
            tray_present=bool(payload.get("tray_present", False)),
            hide_to_tray_on_close=bool(payload.get("hide_to_tray_on_close", False)),
            ghost_reveal_target=float(payload.get("ghost_reveal_target", 0.0) or 0.0),
            event=str(payload.get("event", "heartbeat")),
            observed_at=str(payload.get("observed_at", "")),
        )


@dataclass(slots=True)
class LifecycleSnapshot:
    install_state: InstallState
    runtime_paths: RuntimePaths
    startup_policy: StartupPolicyState
    runtime: CoreRuntimeState
    crash: dict[str, Any]
    restart_policy: RestartPolicyState
    migration: MigrationState
    bootstrap: BootstrapEvaluation
    onboarding: OnboardingState
    uninstall_plan: UninstallPlan

    def to_dict(self) -> dict[str, Any]:
        return {
            "install_state": self.install_state.to_dict(),
            "runtime_paths": self.runtime_paths.to_dict(),
            "startup_policy": self.startup_policy.to_dict(),
            "runtime": self.runtime.to_dict(),
            "crash": _serialize(self.crash),
            "restart_policy": self.restart_policy.to_dict(),
            "migration": self.migration.to_dict(),
            "bootstrap": self.bootstrap.to_dict(),
            "onboarding": self.onboarding.to_dict(),
            "uninstall_plan": self.uninstall_plan.to_dict(),
        }
