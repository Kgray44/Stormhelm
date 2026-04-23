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


def _enum_value(enum_cls: type[Enum], raw: Any, default: Enum) -> Enum:
    try:
        return enum_cls(raw)  # type: ignore[arg-type]
    except Exception:
        return default


class InstallMode(str, Enum):
    SOURCE = "source"
    PORTABLE = "portable"
    INSTALLED = "installed"


class RuntimeMode(str, Enum):
    SOURCE = "source"
    PACKAGED = "packaged"


class MutationTruthState(str, Enum):
    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    ATTEMPTED = "attempted"
    APPLIED = "applied"
    VERIFIED = "verified"
    BLOCKED = "blocked"
    FAILED = "failed"
    STALE = "stale"
    UNKNOWN = "unknown"


class RegistrationStatus(str, Enum):
    DISABLED = "disabled"
    REGISTERED = "registered"
    NOT_REGISTERED = "not_registered"
    APPLIED = "applied"
    BLOCKED = "blocked"
    FAILED = "failed"
    STALE = "stale"
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
    STALE = "stale"


class MigrationStatus(str, Enum):
    CURRENT = "current"
    REQUIRED = "required"
    COMPLETED = "completed"
    HOLD = "hold"


class OnboardingStatus(str, Enum):
    REQUIRED = "required"
    DEFERRED = "deferred"
    COMPLETED = "completed"


class LifecycleHoldReasonKind(str, Enum):
    NONE = "none"
    INSTALL_MODE_CHANGED = "install_mode_changed"
    PROTOCOL_NEWER = "protocol_newer"
    RESTART_REPEATED_FAILURES = "restart_repeated_failures"
    STARTUP_VERIFICATION_FAILED = "startup_verification_failed"
    STARTUP_BLOCKED = "startup_blocked"
    UNKNOWN = "unknown"


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
class StartupRegistrationState:
    requested_state: MutationTruthState = MutationTruthState.NOT_REQUESTED
    attempted_state: MutationTruthState = MutationTruthState.UNKNOWN
    applied_state: MutationTruthState = MutationTruthState.UNKNOWN
    verified_state: MutationTruthState = MutationTruthState.UNKNOWN
    blocked_reason: str = ""
    failure_reason: str = ""
    last_attempted_at: str = ""
    last_verified_at: str = ""
    verification_source: str = ""
    requested_core: bool = False
    requested_shell: bool = False
    mutation_source: str = ""
    operator_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "StartupRegistrationState":
        data = payload or {}
        return cls(
            requested_state=_enum_value(
                MutationTruthState,
                str(data.get("requested_state", MutationTruthState.NOT_REQUESTED.value)),
                MutationTruthState.NOT_REQUESTED,
            ),
            attempted_state=_enum_value(
                MutationTruthState,
                str(data.get("attempted_state", MutationTruthState.UNKNOWN.value)),
                MutationTruthState.UNKNOWN,
            ),
            applied_state=_enum_value(
                MutationTruthState,
                str(data.get("applied_state", MutationTruthState.UNKNOWN.value)),
                MutationTruthState.UNKNOWN,
            ),
            verified_state=_enum_value(
                MutationTruthState,
                str(data.get("verified_state", MutationTruthState.UNKNOWN.value)),
                MutationTruthState.UNKNOWN,
            ),
            blocked_reason=str(data.get("blocked_reason", "")),
            failure_reason=str(data.get("failure_reason", "")),
            last_attempted_at=str(data.get("last_attempted_at", "")),
            last_verified_at=str(data.get("last_verified_at", "")),
            verification_source=str(data.get("verification_source", "")),
            requested_core=bool(data.get("requested_core", False)),
            requested_shell=bool(data.get("requested_shell", False)),
            mutation_source=str(data.get("mutation_source", "")),
            operator_summary=str(data.get("operator_summary", "")),
        )


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
    registration: StartupRegistrationState = field(default_factory=StartupRegistrationState)

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class ShellPresenceState:
    shell_attached: bool = False
    last_heartbeat_at: str = ""
    heartbeat_fresh: bool = False
    detach_kind: str = ""
    detach_reason: str = ""
    controller_reconnect_allowed: bool = True

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
    shell_presence: ShellPresenceState = field(default_factory=ShellPresenceState)

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
    restart_policy: str = "bounded"
    restart_attempts_in_window: int = 0
    repeated_failure_window: float = 0.0
    hold_after_repeated_failures: bool = False
    last_restart_reason: str = ""
    last_restart_outcome: str = ""
    last_healthy_at: str = ""
    shell_failures_in_window: int = 0
    dual_failure_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class LifecycleHoldState:
    hold_active: bool = False
    hold_reason_kind: LifecycleHoldReasonKind = LifecycleHoldReasonKind.NONE
    hold_summary: str = ""
    operator_action_needed: str = ""
    can_retry: bool = False
    retry_kind: str = ""
    degraded_launch_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}


@dataclass(slots=True)
class LifecycleActionRecord:
    action_kind: str = ""
    requested_at: str = ""
    attempted_at: str = ""
    completed_at: str = ""
    initiated_by: str = "operator"
    confirmation_kind: str = ""
    outcome: str = "not_requested"
    truth_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "LifecycleActionRecord":
        data = payload or {}
        return cls(
            action_kind=str(data.get("action_kind", "")),
            requested_at=str(data.get("requested_at", "")),
            attempted_at=str(data.get("attempted_at", "")),
            completed_at=str(data.get("completed_at", "")),
            initiated_by=str(data.get("initiated_by", "operator")),
            confirmation_kind=str(data.get("confirmation_kind", "")),
            outcome=str(data.get("outcome", "not_requested")),
            truth_summary=str(data.get("truth_summary", "")),
        )


@dataclass(slots=True)
class LifecycleResolutionPlan:
    plan_id: str = ""
    hold_kind: LifecycleHoldReasonKind = LifecycleHoldReasonKind.NONE
    resolution_kind: str = ""
    summary: str = ""
    preconditions: list[str] = field(default_factory=list)
    required_confirmation_kind: str = ""
    preserve_targets: list[str] = field(default_factory=list)
    clear_targets: list[str] = field(default_factory=list)
    restart_required: bool = False
    retry_allowed: bool = False
    operator_action_notes: str = ""
    resolvable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "LifecycleResolutionPlan":
        data = payload or {}
        preconditions = data.get("preconditions", [])
        preserve_targets = data.get("preserve_targets", [])
        clear_targets = data.get("clear_targets", [])
        return cls(
            plan_id=str(data.get("plan_id", "")),
            hold_kind=_enum_value(
                LifecycleHoldReasonKind,
                str(data.get("hold_kind", LifecycleHoldReasonKind.NONE.value)),
                LifecycleHoldReasonKind.NONE,
            ),
            resolution_kind=str(data.get("resolution_kind", "")),
            summary=str(data.get("summary", "")),
            preconditions=[str(item) for item in preconditions] if isinstance(preconditions, list) else [],
            required_confirmation_kind=str(data.get("required_confirmation_kind", "")),
            preserve_targets=[str(item) for item in preserve_targets] if isinstance(preserve_targets, list) else [],
            clear_targets=[str(item) for item in clear_targets] if isinstance(clear_targets, list) else [],
            restart_required=bool(data.get("restart_required", False)),
            retry_allowed=bool(data.get("retry_allowed", False)),
            operator_action_notes=str(data.get("operator_action_notes", "")),
            resolvable=bool(data.get("resolvable", False)),
        )


@dataclass(slots=True)
class LifecycleResolutionState:
    resolution_requested: bool = False
    resolution_attempted: bool = False
    resolution_completed: bool = False
    resolution_failed: bool = False
    resolution_partial: bool = False
    resolution_abandoned: bool = False
    last_resolution_summary: str = ""
    restart_pending: bool = False
    follow_up_required: bool = False
    active_plan: LifecycleResolutionPlan = field(default_factory=LifecycleResolutionPlan)
    last_action: LifecycleActionRecord = field(default_factory=LifecycleActionRecord)

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "LifecycleResolutionState":
        data = payload or {}
        return cls(
            resolution_requested=bool(data.get("resolution_requested", False)),
            resolution_attempted=bool(data.get("resolution_attempted", False)),
            resolution_completed=bool(data.get("resolution_completed", False)),
            resolution_failed=bool(data.get("resolution_failed", False)),
            resolution_partial=bool(data.get("resolution_partial", False)),
            resolution_abandoned=bool(data.get("resolution_abandoned", False)),
            last_resolution_summary=str(data.get("last_resolution_summary", "")),
            restart_pending=bool(data.get("restart_pending", False)),
            follow_up_required=bool(data.get("follow_up_required", False)),
            active_plan=LifecycleResolutionPlan.from_dict(data.get("active_plan")),
            last_action=LifecycleActionRecord.from_dict(data.get("last_action")),
        )


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
    hold_reason_kind: LifecycleHoldReasonKind = LifecycleHoldReasonKind.NONE
    operator_action_needed: str = ""
    actionable_summary: str = ""
    can_retry: bool = False
    retry_kind: str = ""
    last_attempted_at: str = ""

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
    hold_state: LifecycleHoldState = field(default_factory=LifecycleHoldState)
    resolution_plan: LifecycleResolutionPlan = field(default_factory=LifecycleResolutionPlan)
    resolution_state: LifecycleResolutionState = field(default_factory=LifecycleResolutionState)

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
            status=_enum_value(
                OnboardingStatus,
                str(data.get("status", OnboardingStatus.REQUIRED.value)),
                OnboardingStatus.REQUIRED,
            ),
            startup_preference_chosen=bool(data.get("startup_preference_chosen", False)),
            background_preference_chosen=bool(data.get("background_preference_chosen", False)),
            trust_setup_state=str(data.get("trust_setup_state", "pending")),
        )


@dataclass(slots=True)
class DestructiveCleanupPlan:
    plan_id: str = ""
    destructive_targets: list[str] = field(default_factory=list)
    preserved_targets: list[str] = field(default_factory=list)
    required_confirmation: str = ""
    confirmation_bound_operation: str = ""
    confirmation_expires_at: str = ""
    confirmation_consumed_at: str = ""
    restart_required: bool = False
    operator_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "DestructiveCleanupPlan":
        data = payload or {}
        destructive_targets = data.get("destructive_targets", [])
        preserved_targets = data.get("preserved_targets", [])
        return cls(
            plan_id=str(data.get("plan_id", "")),
            destructive_targets=[str(item) for item in destructive_targets] if isinstance(destructive_targets, list) else [],
            preserved_targets=[str(item) for item in preserved_targets] if isinstance(preserved_targets, list) else [],
            required_confirmation=str(data.get("required_confirmation", "")),
            confirmation_bound_operation=str(data.get("confirmation_bound_operation", "")),
            confirmation_expires_at=str(data.get("confirmation_expires_at", "")),
            confirmation_consumed_at=str(data.get("confirmation_consumed_at", "")),
            restart_required=bool(data.get("restart_required", False)),
            operator_summary=str(data.get("operator_summary", "")),
        )


@dataclass(slots=True)
class CleanupExecutionState:
    cleanup_intent: str = ""
    destructive_confirmation_required: bool = True
    destructive_confirmation_received: bool = False
    removal_targets: list[str] = field(default_factory=list)
    preserve_targets: list[str] = field(default_factory=lambda: ["durable_state"])
    execution_attempted: bool = False
    execution_outcome: str = "not_requested"
    destructive: bool = False
    partial: bool = False
    attempted_targets: list[str] = field(default_factory=list)
    removed_targets: list[str] = field(default_factory=list)
    preserved_targets: list[str] = field(default_factory=list)
    failed_targets: list[str] = field(default_factory=list)
    skipped_targets: list[str] = field(default_factory=list)
    restart_required: bool = False
    operator_summary: str = ""
    last_action: LifecycleActionRecord = field(default_factory=LifecycleActionRecord)

    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CleanupExecutionState":
        data = payload or {}
        removal_targets = data.get("removal_targets", [])
        preserve_targets = data.get("preserve_targets", ["durable_state"])
        attempted_targets = data.get("attempted_targets", [])
        removed_targets = data.get("removed_targets", [])
        preserved_targets = data.get("preserved_targets", [])
        failed_targets = data.get("failed_targets", [])
        skipped_targets = data.get("skipped_targets", [])
        return cls(
            cleanup_intent=str(data.get("cleanup_intent", "")),
            destructive_confirmation_required=bool(data.get("destructive_confirmation_required", True)),
            destructive_confirmation_received=bool(data.get("destructive_confirmation_received", False)),
            removal_targets=[str(item) for item in removal_targets] if isinstance(removal_targets, list) else [],
            preserve_targets=[str(item) for item in preserve_targets] if isinstance(preserve_targets, list) else [],
            execution_attempted=bool(data.get("execution_attempted", False)),
            execution_outcome=str(data.get("execution_outcome", "not_requested")),
            destructive=bool(data.get("destructive", False)),
            partial=bool(data.get("partial", False)),
            attempted_targets=[str(item) for item in attempted_targets] if isinstance(attempted_targets, list) else [],
            removed_targets=[str(item) for item in removed_targets] if isinstance(removed_targets, list) else [],
            preserved_targets=[str(item) for item in preserved_targets] if isinstance(preserved_targets, list) else [],
            failed_targets=[str(item) for item in failed_targets] if isinstance(failed_targets, list) else [],
            skipped_targets=[str(item) for item in skipped_targets] if isinstance(skipped_targets, list) else [],
            restart_required=bool(data.get("restart_required", False)),
            operator_summary=str(data.get("operator_summary", "")),
            last_action=LifecycleActionRecord.from_dict(data.get("last_action")),
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
    destructive_cleanup_plan: DestructiveCleanupPlan = field(default_factory=DestructiveCleanupPlan)
    cleanup_execution: CleanupExecutionState = field(default_factory=CleanupExecutionState)

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
