from __future__ import annotations

import json
from pathlib import Path

from stormhelm.config.loader import load_config
from stormhelm.core.container import build_container
from stormhelm.core.events import EventBuffer
from stormhelm.core.lifecycle import LifecycleController, ShellPresenceUpdate


def _packaged_config(
    *,
    workspace_temp_dir: Path,
    install_root: Path,
    resource_root: Path | None = None,
    portable: bool = False,
) -> object:
    bundle_root = resource_root or install_root
    (install_root / "config").mkdir(parents=True, exist_ok=True)
    (bundle_root / "assets").mkdir(parents=True, exist_ok=True)
    config = load_config(project_root=workspace_temp_dir, env={})
    config.project_root = install_root.resolve()
    config.runtime.mode = "packaged"
    config.runtime.is_frozen = True
    config.runtime.install_root = install_root.resolve()
    config.runtime.resource_root = bundle_root.resolve()
    config.runtime.assets_dir = (bundle_root / "assets").resolve()
    config.runtime.portable_config_path = (install_root / "config" / "portable.toml").resolve()
    config.runtime.core_executable_path = (install_root / "stormhelm-core.exe").resolve()
    storage_root = (workspace_temp_dir / "runtime").resolve()
    config.storage.data_dir = storage_root / "data"
    config.storage.logs_dir = storage_root / "logs"
    config.storage.state_dir = storage_root / "state"
    config.storage.cache_dir = storage_root / "cache"
    config.storage.database_path = storage_root / "stormhelm.db"
    config.runtime.state_dir = config.storage.state_dir
    config.runtime.core_state_path = config.storage.state_dir / "core-state.json"
    config.runtime.first_run_marker_path = config.storage.state_dir / "first-run.json"
    config.runtime.lifecycle_state_path = config.storage.state_dir / "lifecycle-state.json"
    config.runtime.core_session_path = config.storage.state_dir / "core-session.json"
    config.runtime.shell_session_path = config.storage.state_dir / "shell-session.json"
    if portable:
        (install_root / "config" / "portable.toml").write_text(
            """
[network]
port = 9911
            """.strip(),
            encoding="utf-8",
        )
    return config


def test_lifecycle_controller_reports_source_mode_and_cleanup_boundaries(temp_config) -> None:
    controller = LifecycleController(temp_config, events=EventBuffer(capacity=32))

    bootstrap = controller.bootstrap()
    snapshot = controller.status_snapshot()

    assert bootstrap.onboarding_required is True
    assert snapshot["install_state"]["install_mode"] == "source"
    assert snapshot["install_state"]["startup_capable"] is False
    assert snapshot["runtime_paths"]["user_data_root"] == str(temp_config.storage.data_dir)
    assert snapshot["uninstall_plan"]["remove_durable_state"] is False
    assert snapshot["uninstall_plan"]["destructive_confirmation_required"] is True


def test_lifecycle_controller_detects_portable_and_installed_packaged_postures(workspace_temp_dir: Path) -> None:
    portable_root = workspace_temp_dir / "portable-build"
    installed_root = (
        workspace_temp_dir / "AppData" / "Local" / "Programs" / "Stormhelm"
    )

    portable_config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=portable_root,
        portable=True,
    )
    installed_config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=installed_root,
        portable=False,
    )

    portable = LifecycleController(portable_config, events=EventBuffer(capacity=32))
    installed = LifecycleController(installed_config, events=EventBuffer(capacity=32))

    assert portable.status_snapshot()["install_state"]["install_mode"] == "portable"
    assert installed.status_snapshot()["install_state"]["install_mode"] == "installed"


def test_lifecycle_controller_tracks_crash_history_and_safe_version_updates(temp_config) -> None:
    temp_config.runtime.lifecycle_state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_config.runtime.lifecycle_state_path.write_text(
        json.dumps(
            {
                "last_version": "0.0.1",
                "last_protocol_version": temp_config.protocol_version,
                "last_install_mode": "source",
                "startup_policy": {
                    "startup_enabled": False,
                    "start_core_with_windows": False,
                    "start_shell_with_windows": False,
                    "tray_only_startup": False,
                    "ghost_ready_on_startup": False,
                },
                "onboarding": {
                    "status": "deferred",
                    "startup_preference_chosen": False,
                    "background_preference_chosen": True,
                    "trust_setup_state": "deferred",
                },
            }
        ),
        encoding="utf-8",
    )
    temp_config.runtime.core_session_path.write_text(
        json.dumps({"component": "core", "pid": 2222, "started_at": "2026-04-20T10:00:00Z"}),
        encoding="utf-8",
    )

    controller = LifecycleController(temp_config, events=EventBuffer(capacity=32))
    bootstrap = controller.bootstrap()
    snapshot = controller.status_snapshot()

    assert bootstrap.migration_state.migration_required is True
    assert bootstrap.migration_state.status in {"required", "completed"}
    assert snapshot["crash"]["recent"][0]["component"] == "core"
    assert snapshot["restart_policy"]["attempts_in_window"] >= 1


def test_lifecycle_controller_holds_when_install_mode_changes_between_runs(workspace_temp_dir: Path) -> None:
    install_root = workspace_temp_dir / "AppData" / "Local" / "Programs" / "Stormhelm"
    config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=install_root,
        portable=False,
    )
    config.runtime.lifecycle_state_path.parent.mkdir(parents=True, exist_ok=True)
    config.runtime.lifecycle_state_path.write_text(
        json.dumps(
            {
                "last_version": "1.0.0",
                "last_protocol_version": config.protocol_version,
                "last_install_mode": "portable",
                "onboarding": {
                    "status": "completed",
                    "startup_preference_chosen": True,
                    "background_preference_chosen": True,
                    "trust_setup_state": "completed",
                },
            }
        ),
        encoding="utf-8",
    )

    controller = LifecycleController(config, events=EventBuffer(capacity=32))
    bootstrap = controller.bootstrap()
    snapshot = controller.status_snapshot()

    assert bootstrap.lifecycle_hold_reason
    assert snapshot["migration"]["status"] == "hold"
    assert snapshot["bootstrap"]["startup_allowed"] is False


def test_lifecycle_controller_tracks_shell_and_tray_presence(temp_config) -> None:
    controller = LifecycleController(temp_config, events=EventBuffer(capacity=32))
    controller.bootstrap()

    controller.record_shell_presence(
        ShellPresenceUpdate(
            pid=4100,
            mode="ghost",
            window_visible=False,
            tray_present=True,
            hide_to_tray_on_close=True,
            ghost_reveal_target=0.0,
            event="attach",
        )
    )

    attached = controller.status_snapshot()

    assert attached["runtime"]["shell_status"] == "hidden"
    assert attached["runtime"]["tray_status"] == "present"
    assert attached["runtime"]["connected_clients"] == 1

    controller.record_shell_detached(pid=4100)

    detached = controller.status_snapshot()

    assert detached["runtime"]["shell_status"] == "detached"
    assert detached["runtime"]["connected_clients"] == 0


def test_lifecycle_controller_reports_startup_truth_without_overclaiming(temp_config) -> None:
    temp_config.lifecycle.startup_enabled = True
    temp_config.lifecycle.start_core_with_windows = True
    temp_config.lifecycle.start_shell_with_windows = False

    controller = LifecycleController(
        temp_config,
        events=EventBuffer(capacity=32),
        startup_registration_probe=lambda *_args, **_kwargs: {
            "registered_core": False,
            "registered_shell": False,
            "failure_reason": "",
        },
    )
    controller.bootstrap()
    snapshot = controller.status_snapshot()

    assert snapshot["startup_policy"]["startup_enabled"] is True
    assert snapshot["startup_policy"]["registration_status"] == "not_registered"
    assert snapshot["startup_policy"]["registered_core"] is False
    assert snapshot["startup_policy"]["registered_shell"] is False


def test_lifecycle_controller_applies_and_verifies_startup_registration_when_supported(
    workspace_temp_dir: Path,
) -> None:
    install_root = workspace_temp_dir / "AppData" / "Local" / "Programs" / "Stormhelm"
    config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=install_root,
        portable=False,
    )
    registry_state = {"core": False, "shell": False}

    controller = LifecycleController(
        config,
        events=EventBuffer(capacity=32),
        startup_registration_probe=lambda *_args, **_kwargs: {
            "registered_core": registry_state["core"],
            "registered_shell": registry_state["shell"],
            "failure_reason": "",
        },
        startup_registration_mutator=lambda _config, _install, policy, _commands: (
            registry_state.update(
                {
                    "core": bool(policy.startup_enabled and policy.start_core_with_windows),
                    "shell": bool(policy.startup_enabled and policy.start_shell_with_windows),
                }
            )
            or {"attempted": True, "blocked_reason": "", "failure_reason": "", "mutation_source": "test_registry"}
        ),
    )
    controller.bootstrap()

    updated = controller.configure_startup_policy(
        startup_enabled=True,
        start_core_with_windows=True,
        start_shell_with_windows=True,
        tray_only_startup=True,
        ghost_ready_on_startup=True,
    )
    snapshot = controller.status_snapshot()

    assert updated.registration_status == "registered"
    assert snapshot["startup_policy"]["registration"]["requested_state"] == "requested"
    assert snapshot["startup_policy"]["registration"]["attempted_state"] == "attempted"
    assert snapshot["startup_policy"]["registration"]["applied_state"] == "applied"
    assert snapshot["startup_policy"]["registration"]["verified_state"] == "verified"
    assert snapshot["startup_policy"]["registered_core"] is True
    assert snapshot["startup_policy"]["registered_shell"] is True


def test_lifecycle_controller_reports_startup_as_applied_until_verification_catches_up(
    workspace_temp_dir: Path,
) -> None:
    install_root = workspace_temp_dir / "AppData" / "Local" / "Programs" / "Stormhelm"
    config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=install_root,
        portable=False,
    )

    controller = LifecycleController(
        config,
        events=EventBuffer(capacity=32),
        startup_registration_probe=lambda *_args, **_kwargs: {
            "registered_core": False,
            "registered_shell": False,
            "failure_reason": "probe_unavailable",
        },
        startup_registration_mutator=lambda *_args, **_kwargs: {
            "attempted": True,
            "blocked_reason": "",
            "failure_reason": "",
            "mutation_source": "test_registry",
        },
    )
    controller.bootstrap()

    snapshot = controller.configure_startup_policy(
        startup_enabled=True,
        start_core_with_windows=True,
        start_shell_with_windows=False,
        tray_only_startup=True,
        ghost_ready_on_startup=True,
    ).to_dict()

    assert snapshot["registration_status"] == "applied"
    assert snapshot["registration"]["applied_state"] == "applied"
    assert snapshot["registration"]["verified_state"] == "unknown"
    assert snapshot["registered_core"] is False


def test_lifecycle_controller_blocks_startup_mutation_in_portable_mode_without_overclaiming(
    workspace_temp_dir: Path,
) -> None:
    portable_root = workspace_temp_dir / "portable-build"
    mutation_calls: list[str] = []
    config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=portable_root,
        portable=True,
    )

    controller = LifecycleController(
        config,
        events=EventBuffer(capacity=32),
        startup_registration_probe=lambda *_args, **_kwargs: {
            "registered_core": False,
            "registered_shell": False,
            "failure_reason": "",
        },
        startup_registration_mutator=lambda *_args, **_kwargs: mutation_calls.append("mutate")
        or {"attempted": True, "blocked_reason": "", "failure_reason": "", "mutation_source": "test_registry"},
    )
    controller.bootstrap()

    updated = controller.configure_startup_policy(
        startup_enabled=True,
        start_core_with_windows=True,
        start_shell_with_windows=False,
        tray_only_startup=True,
        ghost_ready_on_startup=True,
    )

    assert mutation_calls == []
    assert updated.registration_status == "blocked"
    assert updated.registration.blocked_reason
    assert updated.registered_core is False


def test_lifecycle_controller_marks_startup_verification_stale_when_probe_cannot_refresh(temp_config) -> None:
    temp_config.runtime.lifecycle_state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_config.runtime.lifecycle_state_path.write_text(
        json.dumps(
            {
                "last_version": temp_config.version,
                "last_protocol_version": temp_config.protocol_version,
                "last_install_mode": "source",
                "startup_policy": {
                    "startup_enabled": True,
                    "start_core_with_windows": True,
                    "start_shell_with_windows": False,
                    "tray_only_startup": True,
                    "ghost_ready_on_startup": True,
                },
                "startup_registration": {
                    "requested_state": "requested",
                    "attempted_state": "attempted",
                    "applied_state": "applied",
                    "verified_state": "verified",
                    "last_verified_at": "2026-01-01T00:00:00Z",
                    "verification_source": "registry_probe",
                },
            }
        ),
        encoding="utf-8",
    )

    controller = LifecycleController(
        temp_config,
        events=EventBuffer(capacity=32),
        startup_registration_probe=lambda *_args, **_kwargs: {
            "registered_core": False,
            "registered_shell": False,
            "failure_reason": "probe_unavailable",
        },
    )
    snapshot = controller.status_snapshot()

    assert snapshot["startup_policy"]["registration_status"] == "stale"
    assert snapshot["startup_policy"]["registration"]["verified_state"] == "stale"


def test_lifecycle_controller_clarifies_migration_hold_with_actionable_next_step(workspace_temp_dir: Path) -> None:
    install_root = workspace_temp_dir / "AppData" / "Local" / "Programs" / "Stormhelm"
    config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=install_root,
        portable=False,
    )
    config.runtime.lifecycle_state_path.parent.mkdir(parents=True, exist_ok=True)
    config.runtime.lifecycle_state_path.write_text(
        json.dumps(
            {
                "last_version": "1.0.0",
                "last_protocol_version": config.protocol_version,
                "last_install_mode": "portable",
                "onboarding": {
                    "status": "completed",
                    "startup_preference_chosen": True,
                    "background_preference_chosen": True,
                    "trust_setup_state": "completed",
                },
            }
        ),
        encoding="utf-8",
    )

    controller = LifecycleController(config, events=EventBuffer(capacity=32))
    snapshot = controller.bootstrap().to_dict()

    assert snapshot["migration_state"]["hold_reason"]
    assert snapshot["migration_state"]["hold_reason_kind"] == "install_mode_changed"
    assert snapshot["migration_state"]["operator_action_needed"]
    assert snapshot["hold_state"]["hold_active"] is True
    assert snapshot["hold_state"]["operator_action_needed"]


def test_lifecycle_controller_executes_nondestructive_cleanup_without_touching_durable_state(
    workspace_temp_dir: Path,
) -> None:
    install_root = workspace_temp_dir / "AppData" / "Local" / "Programs" / "Stormhelm"
    config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=install_root,
        portable=False,
    )
    config.storage.logs_dir.mkdir(parents=True, exist_ok=True)
    config.storage.cache_dir.mkdir(parents=True, exist_ok=True)
    config.storage.data_dir.mkdir(parents=True, exist_ok=True)
    (config.storage.logs_dir / "stormhelm.log").write_text("log", encoding="utf-8")
    (config.storage.cache_dir / "cache.tmp").write_text("cache", encoding="utf-8")
    durable_path = config.storage.data_dir / "durable-state.json"
    durable_path.write_text("durable", encoding="utf-8")

    registry_state = {"core": True, "shell": False}
    controller = LifecycleController(
        config,
        events=EventBuffer(capacity=32),
        startup_registration_probe=lambda *_args, **_kwargs: {
            "registered_core": registry_state["core"],
            "registered_shell": registry_state["shell"],
            "failure_reason": "",
        },
        startup_registration_mutator=lambda _config, _install, policy, _commands: (
            registry_state.update(
                {
                    "core": bool(policy.startup_enabled and policy.start_core_with_windows),
                    "shell": bool(policy.startup_enabled and policy.start_shell_with_windows),
                }
            )
            or {"attempted": True, "blocked_reason": "", "failure_reason": "", "mutation_source": "test_registry"}
        ),
    )
    controller.bootstrap()

    result = controller.execute_cleanup(
        remove_startup_registration=True,
        remove_logs=True,
        remove_caches=True,
        remove_durable_state=False,
        destructive_confirmation_received=False,
    )
    snapshot = controller.status_snapshot()

    assert result.execution_outcome == "completed"
    assert durable_path.exists() is True
    assert (config.storage.logs_dir / "stormhelm.log").exists() is False
    assert (config.storage.cache_dir / "cache.tmp").exists() is False
    assert snapshot["uninstall_plan"]["cleanup_execution"]["preserve_targets"] == ["durable_state"]


def test_lifecycle_controller_blocks_destructive_cleanup_without_confirmation(temp_config) -> None:
    temp_config.storage.data_dir.mkdir(parents=True, exist_ok=True)
    durable_path = temp_config.storage.data_dir / "durable-state.json"
    durable_path.write_text("durable", encoding="utf-8")

    controller = LifecycleController(temp_config, events=EventBuffer(capacity=32))
    controller.bootstrap()

    result = controller.execute_cleanup(
        remove_durable_state=True,
        destructive_confirmation_received=False,
    )

    assert result.execution_outcome == "blocked"
    assert durable_path.exists() is True
    assert "confirmation" in result.operator_summary.lower()


def test_lifecycle_controller_resolves_install_mode_hold_with_a_typed_resolution_plan(
    workspace_temp_dir: Path,
) -> None:
    install_root = workspace_temp_dir / "AppData" / "Local" / "Programs" / "Stormhelm"
    config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=install_root,
        portable=False,
    )
    config.runtime.lifecycle_state_path.parent.mkdir(parents=True, exist_ok=True)
    config.runtime.lifecycle_state_path.write_text(
        json.dumps(
            {
                "last_version": "1.0.0",
                "last_protocol_version": config.protocol_version,
                "last_install_mode": "portable",
                "onboarding": {
                    "status": "completed",
                    "startup_preference_chosen": True,
                    "background_preference_chosen": True,
                    "trust_setup_state": "completed",
                },
            }
        ),
        encoding="utf-8",
    )

    controller = LifecycleController(config, events=EventBuffer(capacity=32))
    bootstrap = controller.bootstrap().to_dict()
    plan = bootstrap["resolution_plan"]

    assert plan["hold_kind"] == "install_mode_changed"
    assert plan["resolution_kind"] == "acknowledge_install_mode_change"
    assert plan["restart_required"] is False
    assert plan["required_confirmation_kind"] == "acknowledge_resolution_plan"
    assert "durable_state" in plan["preserve_targets"]

    resolution = controller.resolve_lifecycle_hold(
        plan_id=plan["plan_id"],
        resolution_kind=plan["resolution_kind"],
        confirmation_kind=plan["required_confirmation_kind"],
        confirmed_summary=plan["summary"],
    )
    snapshot = controller.status_snapshot()

    assert resolution.resolution_completed is True
    assert resolution.resolution_partial is False
    assert snapshot["migration"]["status"] == "current"
    assert snapshot["bootstrap"]["startup_allowed"] is True
    assert snapshot["bootstrap"]["resolution_state"]["resolution_completed"] is True


def test_lifecycle_controller_keeps_protocol_resolution_honest_until_restart(
    workspace_temp_dir: Path,
) -> None:
    install_root = workspace_temp_dir / "AppData" / "Local" / "Programs" / "Stormhelm"
    config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=install_root,
        portable=False,
    )
    config.runtime.lifecycle_state_path.parent.mkdir(parents=True, exist_ok=True)
    config.runtime.lifecycle_state_path.write_text(
        json.dumps(
            {
                "last_version": config.version,
                "last_protocol_version": config.protocol_version + 1,
                "last_install_mode": "installed",
                "onboarding": {
                    "status": "completed",
                    "startup_preference_chosen": True,
                    "background_preference_chosen": True,
                    "trust_setup_state": "completed",
                },
            }
        ),
        encoding="utf-8",
    )

    controller = LifecycleController(config, events=EventBuffer(capacity=32))
    bootstrap = controller.bootstrap().to_dict()
    plan = bootstrap["resolution_plan"]

    assert plan["hold_kind"] == "protocol_newer"
    assert plan["restart_required"] is True

    resolution = controller.resolve_lifecycle_hold(
        plan_id=plan["plan_id"],
        resolution_kind=plan["resolution_kind"],
        confirmation_kind=plan["required_confirmation_kind"],
        confirmed_summary=plan["summary"],
    )
    held_snapshot = controller.status_snapshot()

    assert resolution.resolution_completed is False
    assert resolution.resolution_partial is True
    assert resolution.restart_pending is True
    assert held_snapshot["bootstrap"]["startup_allowed"] is False
    assert "restart" in held_snapshot["bootstrap"]["resolution_state"]["last_resolution_summary"].lower()

    controller.shutdown()

    resumed = LifecycleController(config, events=EventBuffer(capacity=32))
    resumed_snapshot = resumed.bootstrap().to_dict()

    assert resumed_snapshot["migration_state"]["status"] == "current"
    assert resumed_snapshot["startup_allowed"] is True


def test_lifecycle_controller_executes_destructive_cleanup_only_with_a_fresh_bound_plan(
    workspace_temp_dir: Path,
) -> None:
    install_root = workspace_temp_dir / "AppData" / "Local" / "Programs" / "Stormhelm"
    config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=install_root,
        portable=False,
    )
    config.storage.logs_dir.mkdir(parents=True, exist_ok=True)
    config.storage.data_dir.mkdir(parents=True, exist_ok=True)
    config.storage.database_path.parent.mkdir(parents=True, exist_ok=True)
    (config.storage.logs_dir / "stormhelm.log").write_text("log", encoding="utf-8")
    durable_path = config.storage.data_dir / "durable-state.json"
    durable_path.write_text("durable", encoding="utf-8")
    config.storage.database_path.write_text("db", encoding="utf-8")

    controller = LifecycleController(config, events=EventBuffer(capacity=32))
    controller.bootstrap()
    plan = controller.prepare_cleanup_plan(
        remove_logs=True,
        remove_durable_state=True,
    )

    result = controller.execute_cleanup(
        remove_logs=True,
        remove_durable_state=True,
        destructive_confirmation_received=True,
        destructive_confirmation={
            "plan_id": plan.plan_id,
            "operation": plan.confirmation_bound_operation,
            "confirmation_kind": plan.required_confirmation,
            "confirmed_summary": plan.operator_summary,
            "destructive_intent": True,
        },
    )
    snapshot = controller.status_snapshot()

    assert result.execution_outcome == "completed"
    assert result.destructive is True
    assert "logs_contents" in result.removed_targets
    assert "data_dir_contents" in result.removed_targets
    assert "database_file" in result.removed_targets
    assert "lifecycle_state" in result.preserved_targets
    assert durable_path.exists() is False
    assert config.storage.database_path.exists() is False
    assert snapshot["uninstall_plan"]["cleanup_execution"]["destructive"] is True


def test_lifecycle_controller_rejects_stale_or_reused_destructive_confirmation(
    workspace_temp_dir: Path,
) -> None:
    install_root = workspace_temp_dir / "AppData" / "Local" / "Programs" / "Stormhelm"
    config = _packaged_config(
        workspace_temp_dir=workspace_temp_dir,
        install_root=install_root,
        portable=False,
    )
    config.storage.data_dir.mkdir(parents=True, exist_ok=True)
    config.storage.database_path.parent.mkdir(parents=True, exist_ok=True)
    (config.storage.data_dir / "durable-state.json").write_text("durable", encoding="utf-8")
    config.storage.database_path.write_text("db", encoding="utf-8")

    controller = LifecycleController(config, events=EventBuffer(capacity=32))
    controller.bootstrap()
    plan = controller.prepare_cleanup_plan(remove_durable_state=True)

    stale = controller.execute_cleanup(
        remove_durable_state=True,
        destructive_confirmation_received=True,
        destructive_confirmation={
            "plan_id": plan.plan_id,
            "operation": plan.confirmation_bound_operation,
            "confirmation_kind": plan.required_confirmation,
            "confirmed_summary": plan.operator_summary,
            "destructive_intent": True,
            "confirmed_at": "2026-01-01T00:00:00Z",
        },
    )

    assert stale.execution_outcome == "blocked"
    assert "fresh" in stale.operator_summary.lower()

    fresh_plan = controller.prepare_cleanup_plan(remove_durable_state=True)
    completed = controller.execute_cleanup(
        remove_durable_state=True,
        destructive_confirmation_received=True,
        destructive_confirmation={
            "plan_id": fresh_plan.plan_id,
            "operation": fresh_plan.confirmation_bound_operation,
            "confirmation_kind": fresh_plan.required_confirmation,
            "confirmed_summary": fresh_plan.operator_summary,
            "destructive_intent": True,
        },
    )
    reused = controller.execute_cleanup(
        remove_durable_state=True,
        destructive_confirmation_received=True,
        destructive_confirmation={
            "plan_id": fresh_plan.plan_id,
            "operation": fresh_plan.confirmation_bound_operation,
            "confirmation_kind": fresh_plan.required_confirmation,
            "confirmed_summary": fresh_plan.operator_summary,
            "destructive_intent": True,
        },
    )

    assert completed.execution_outcome == "completed"
    assert reused.execution_outcome == "blocked"
    assert "consumed" in reused.operator_summary.lower()


def test_core_container_status_snapshot_exposes_lifecycle_runtime_state(temp_config) -> None:
    container = build_container(temp_config)

    snapshot = container.status_snapshot()

    assert "lifecycle" in snapshot
    assert snapshot["lifecycle"]["install_state"]["install_mode"] == "source"
