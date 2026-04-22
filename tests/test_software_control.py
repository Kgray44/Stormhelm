from __future__ import annotations

import shutil
from uuid import uuid4

from stormhelm.core.tasks.models import TaskCheckpointRecord
from stormhelm.core.tasks.models import TaskRecord
from stormhelm.core.tasks.models import TaskState
from stormhelm.core.tasks.models import TaskStepRecord
from stormhelm.core.tasks.models import TaskStepState
from stormhelm.core.software_control import SoftwareExecutionStatus
from stormhelm.core.software_control import SoftwareOperationRequest
from stormhelm.core.software_control import SoftwareOperationType
from stormhelm.core.software_control import build_software_control_subsystem
from stormhelm.core.software_recovery import build_software_recovery_subsystem
from stormhelm.core.trust import TrustRepository
from stormhelm.core.trust import TrustService
from stormhelm.shared.time import utc_now_iso


def _save_task(trust_harness, *, task_id: str, state: TaskState = TaskState.IN_PROGRESS) -> None:
    timestamp = utc_now_iso()
    checkpoint_status = "pending" if state == TaskState.VERIFICATION else "completed"
    trust_harness["task_service"].repository.save_task(
        TaskRecord(
            task_id=task_id,
            session_id="default",
            title=f"Task {task_id}",
            summary="Synthetic software-control trust task.",
            goal="Verify software trust scope handling.",
            state=state.value,
            created_at=timestamp,
            updated_at=timestamp,
            started_at=timestamp,
            finished_at=timestamp if state == TaskState.COMPLETED else "",
            active_step_id="" if state == TaskState.COMPLETED else f"{task_id}-step",
            steps=[
                TaskStepRecord(
                    step_id=f"{task_id}-step",
                    task_id=task_id,
                    sequence_index=0,
                    title="Synthetic step",
                    state=TaskStepState.COMPLETED.value
                    if state == TaskState.COMPLETED
                    else TaskStepState.IN_PROGRESS.value,
                    started_at=timestamp,
                    finished_at=timestamp if state == TaskState.COMPLETED else "",
                )
            ],
            checkpoints=[
                TaskCheckpointRecord(
                    checkpoint_id=str(uuid4()),
                    task_id=task_id,
                    label="Verify outcome",
                    status=checkpoint_status,
                    summary="",
                    created_at=timestamp,
                    completed_at=timestamp if checkpoint_status == "completed" else "",
                )
            ],
        )
    )
    trust_harness["session_state"].set_active_task_id("default", task_id)


def _restart_trust_service(trust_harness) -> TrustService:
    return TrustService(
        config=trust_harness["trust_service"].config,
        repository=TrustRepository(trust_harness["database"]),
        events=trust_harness["events"],
        session_state=trust_harness["session_state"],
        task_service=trust_harness["task_service"],
    )


def test_software_control_prefers_trusted_package_manager_sources_before_browser_routes(temp_config) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    target = software.resolve_software_target("install firefox")
    sources = software.discover_software_sources(target)

    assert target is not None
    assert [source.kind.value for source in sources[:2]] == ["package_manager", "package_manager"]
    assert sources[0].route == "winget"
    assert sources[-1].kind.value == "browser_guided"


def test_software_control_builds_truthful_install_plan_with_confirmation_gate(temp_config) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    target = software.resolve_software_target("install firefox")
    sources = software.discover_software_sources(target)
    plan = software.plan_software_operation(
        operation_type=SoftwareOperationType.INSTALL,
        target=target,
        sources=sources,
    )

    assert plan.target.canonical_name == "firefox"
    assert plan.selected_source is not None
    assert plan.selected_source.route == "winget"
    assert plan.presentation_depth == "ghost"
    assert plan.requires_command_deck is False
    assert [step.status.value for step in plan.steps[:4]] == [
        "found",
        "uncertain",
        "prepared",
        "waiting_confirmation",
    ]


def test_software_control_hands_adapter_failure_to_recovery_with_route_switch(temp_config) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    response = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-1",
            source_surface="ghost",
            raw_input="continue installing firefox",
            user_visible_text="continue installing firefox",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="confirm_execution",
            follow_up_reuse=True,
        ),
    )

    assert response.result is not None
    assert response.result.status == SoftwareExecutionStatus.RECOVERY_IN_PROGRESS
    assert response.recovery_plan is not None
    assert response.recovery_result is not None
    assert response.trace.recovery_invoked is True
    assert response.recovery_result.route_switched_to == "vendor_installer"


def test_software_control_resolves_minecraft_to_trusted_local_routes(temp_config) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    target = software.resolve_software_target("download and install minecraft")
    sources = software.discover_software_sources(target)

    assert target is not None
    assert target.canonical_name == "minecraft"
    assert sources
    assert sources[0].route == "winget"
    assert sources[0].locator == "Mojang.MinecraftLauncher"


def test_software_control_does_not_offer_unverified_browser_route_when_trusted_sources_only(temp_config) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    target = software.resolve_software_target("install some made up tool")
    sources = software.discover_software_sources(target)

    assert target is not None
    assert target.canonical_name == "some made up tool"
    assert sources == []


def test_software_control_verifies_local_install_state_without_confirmation(temp_config, monkeypatch) -> None:
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
    )

    original_which = shutil.which

    def fake_which(name: str) -> str | None:
        if name == "git":
            return r"C:\Program Files\Git\cmd\git.exe"
        return original_which(name)

    monkeypatch.setattr("stormhelm.core.software_control.service.shutil.which", fake_which)

    response = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-verify-1",
            source_surface="ghost",
            raw_input="check if git is installed",
            user_visible_text="check if git is installed",
            operation_type=SoftwareOperationType.VERIFY,
            target_name="git",
            request_stage="prepare_plan",
            follow_up_reuse=False,
        ),
    )

    assert response.result is not None
    assert response.result.status == SoftwareExecutionStatus.VERIFIED
    assert response.verification is not None
    assert response.verification.status.value == "verified"
    assert response.active_request_state == {}
    assert "installed" in response.assistant_response.lower()


def test_software_control_preview_attaches_trust_state_for_sensitive_operations(temp_config, trust_harness) -> None:
    _save_task(trust_harness, task_id="task-firefox")
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
        trust_service=trust_harness["trust_service"],
    )

    response = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-trust-preview-1",
            source_surface="ghost",
            raw_input="install firefox",
            user_visible_text="install firefox",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="prepare_plan",
            follow_up_reuse=False,
            task_id="task-firefox",
        ),
    )

    assert response.result is not None
    assert response.result.status == SoftwareExecutionStatus.PREPARED
    assert response.active_request_state is not None
    assert response.active_request_state["trust"]["decision"] == "downgraded"
    assert response.active_request_state["trust"]["suggested_scope"] == "task"
    assert response.active_request_state["trust"]["request_id"] != ""
    assert response.active_request_state["task_id"] == "task-firefox"
    assert response.active_request_state["trust"]["task_id"] == "task-firefox"
    assert "approval is required" in response.assistant_response.lower()


def test_software_control_reuses_granted_task_scope_for_follow_up_execution(temp_config, trust_harness) -> None:
    _save_task(trust_harness, task_id="task-firefox")
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
        trust_service=trust_harness["trust_service"],
    )

    preview = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-trust-confirm-1",
            source_surface="ghost",
            raw_input="install firefox",
            user_visible_text="install firefox",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="prepare_plan",
            follow_up_reuse=False,
            task_id="task-firefox",
        ),
    )

    request_id = str(preview.active_request_state["trust"]["request_id"])
    confirmed = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-trust-confirm-2",
            source_surface="ghost",
            raw_input="yes, allow for this task",
            user_visible_text="yes, allow for this task",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="confirm_execution",
            follow_up_reuse=True,
            task_id="task-firefox",
            trust_request_id=request_id,
            approval_scope="task",
            approval_outcome="approve",
        ),
    )
    reused = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-trust-confirm-3",
            source_surface="ghost",
            raw_input="install firefox",
            user_visible_text="install firefox",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="prepare_plan",
            follow_up_reuse=False,
            task_id="task-firefox",
        ),
    )

    assert confirmed.result is not None
    assert confirmed.result.status == SoftwareExecutionStatus.RECOVERY_IN_PROGRESS
    assert confirmed.debug["trust"]["decision"] == "allowed"
    assert confirmed.debug["trust"]["approval_state"] == "approved_for_task"
    assert reused.result is not None
    assert reused.result.status == SoftwareExecutionStatus.RECOVERY_IN_PROGRESS
    assert reused.debug["trust"]["decision"] == "allowed"


def test_software_control_refreshes_restart_stale_follow_up_with_new_request(temp_config, trust_harness) -> None:
    _save_task(trust_harness, task_id="task-firefox")
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
        trust_service=trust_harness["trust_service"],
    )

    preview = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-restart-refresh-1",
            source_surface="ghost",
            raw_input="install firefox",
            user_visible_text="install firefox",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="prepare_plan",
            follow_up_reuse=False,
            task_id="task-firefox",
        ),
    )
    original_request_id = str(preview.active_request_state["trust"]["request_id"])

    restarted = _restart_trust_service(trust_harness)
    restarted_software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
        trust_service=restarted,
    )
    refreshed = restarted_software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-restart-refresh-2",
            source_surface="ghost",
            raw_input="continue",
            user_visible_text="continue",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="confirm_execution",
            follow_up_reuse=True,
            task_id="task-firefox",
            trust_request_id=original_request_id,
            approval_scope="task",
            approval_outcome="approve",
        ),
    )
    repeated = restarted_software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-restart-refresh-3",
            source_surface="ghost",
            raw_input="install firefox",
            user_visible_text="install firefox",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="prepare_plan",
            follow_up_reuse=False,
            task_id="task-firefox",
        ),
    )

    assert refreshed.result is not None
    assert refreshed.result.status == SoftwareExecutionStatus.PREPARED
    assert refreshed.active_request_state is not None
    assert refreshed.active_request_state["trust"]["request_id"] != original_request_id
    assert repeated.active_request_state is not None
    assert repeated.active_request_state["trust"]["request_id"] == refreshed.active_request_state["trust"]["request_id"]
    requested_events = [
        record
        for record in restarted.repository.list_recent_audit(session_id="default", limit=20)
        if record.event_kind == "approval.requested"
    ]
    assert len(requested_events) == 2


def test_software_control_prevents_cross_task_follow_up_reuse(temp_config, trust_harness) -> None:
    _save_task(trust_harness, task_id="task-alpha")
    _save_task(trust_harness, task_id="task-beta")
    recovery = build_software_recovery_subsystem(
        temp_config.software_recovery,
        openai_enabled=temp_config.openai.enabled,
    )
    software = build_software_control_subsystem(
        temp_config.software_control,
        recovery=recovery,
        trust_service=trust_harness["trust_service"],
    )

    preview = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-cross-task-1",
            source_surface="ghost",
            raw_input="install firefox",
            user_visible_text="install firefox",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="prepare_plan",
            follow_up_reuse=False,
            task_id="task-alpha",
        ),
    )
    original_request_id = str(preview.active_request_state["trust"]["request_id"])

    response = software.execute_software_operation(
        session_id="default",
        active_module="chartroom",
        request=SoftwareOperationRequest(
            request_id="soft-cross-task-2",
            source_surface="ghost",
            raw_input="continue",
            user_visible_text="continue",
            operation_type=SoftwareOperationType.INSTALL,
            target_name="firefox",
            request_stage="confirm_execution",
            follow_up_reuse=True,
            task_id="task-beta",
            trust_request_id=original_request_id,
            approval_scope="task",
            approval_outcome="approve",
        ),
    )

    assert response.result is not None
    assert response.result.status == SoftwareExecutionStatus.PREPARED
    assert response.active_request_state is not None
    assert response.active_request_state["task_id"] == "task-beta"
    assert response.active_request_state["trust"]["request_id"] != original_request_id
