from __future__ import annotations

from uuid import uuid4

from stormhelm.core.tasks.models import TaskCheckpointRecord
from stormhelm.core.tasks.models import TaskRecord
from stormhelm.core.tasks.models import TaskState
from stormhelm.core.tasks.models import TaskStepRecord
from stormhelm.core.tasks.models import TaskStepState
from stormhelm.core.trust import ApprovalState
from stormhelm.core.trust import PermissionScope
from stormhelm.core.trust import TrustActionKind
from stormhelm.core.trust import TrustActionRequest
from stormhelm.core.trust import TrustRepository
from stormhelm.core.trust import TrustService
from stormhelm.core.trust import TrustDecisionOutcome
from stormhelm.shared.time import utc_now_iso


def _software_install_request(
    *,
    request_id: str,
    task_id: str = "task-firefox",
    subject: str = "firefox",
) -> TrustActionRequest:
    suggested_scope = PermissionScope.TASK if task_id else PermissionScope.ONCE
    available_scopes = [PermissionScope.ONCE, PermissionScope.SESSION]
    if task_id:
        available_scopes.insert(1, PermissionScope.TASK)
    return TrustActionRequest(
        request_id=request_id,
        family="software_control",
        action_key="software_control.install",
        subject=subject,
        session_id="default",
        task_id=task_id,
        action_kind=TrustActionKind.SOFTWARE_CONTROL,
        approval_required=True,
        preview_allowed=True,
        suggested_scope=suggested_scope,
        available_scopes=available_scopes,
        operator_justification=f"Installing {subject.title()} may change local software state.",
        operator_message=f"Approval is required before Stormhelm can install {subject.title()}.",
        details={"target_name": subject},
    )


def _restart_trust_service(trust_harness) -> TrustService:
    return TrustService(
        config=trust_harness["trust_service"].config,
        repository=TrustRepository(trust_harness["database"]),
        events=trust_harness["events"],
        session_state=trust_harness["session_state"],
        task_service=trust_harness["task_service"],
    )


def _save_task(trust_harness, *, task_id: str, state: TaskState) -> None:
    timestamp = utc_now_iso()
    checkpoint_status = "pending" if state == TaskState.VERIFICATION else "completed"
    trust_harness["task_service"].repository.save_task(
        TaskRecord(
            task_id=task_id,
            session_id="default",
            title=f"Task {task_id}",
            summary="Synthetic trust test task.",
            goal="Verify trust binding behavior.",
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


def test_trust_service_reuses_pending_request_without_prompt_spam(trust_harness) -> None:
    trust = trust_harness["trust_service"]
    repository = trust_harness["trust_service"].repository

    first = trust.evaluate_action(_software_install_request(request_id="trust-1", task_id=""))
    second = trust.evaluate_action(_software_install_request(request_id="trust-2", task_id=""))

    assert first.outcome == TrustDecisionOutcome.DOWNGRADED
    assert second.outcome == TrustDecisionOutcome.DOWNGRADED
    assert first.approval_request is not None
    assert second.approval_request is not None
    assert second.approval_request.approval_request_id == first.approval_request.approval_request_id
    assert len(repository.list_pending_requests(session_id="default")) == 1
    requested_events = [
        record
        for record in repository.list_recent_audit(session_id="default", limit=10)
        if record.event_kind == "approval.requested"
    ]
    assert len(requested_events) == 1


def test_trust_service_binds_task_grants_and_expires_once_grants_after_execution(trust_harness) -> None:
    trust = trust_harness["trust_service"]
    _save_task(trust_harness, task_id="task-alpha", state=TaskState.IN_PROGRESS)
    _save_task(trust_harness, task_id="task-beta", state=TaskState.IN_PROGRESS)

    pending = trust.evaluate_action(_software_install_request(request_id="grant-task-1", task_id="task-alpha"))
    assert pending.approval_request is not None

    granted = trust.respond_to_request(
        approval_request_id=pending.approval_request.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.TASK,
        task_id="task-alpha",
    )
    same_task = trust.evaluate_action(_software_install_request(request_id="grant-task-2", task_id="task-alpha"))
    other_task = trust.evaluate_action(_software_install_request(request_id="grant-task-3", task_id="task-beta"))

    assert granted.approval_state == ApprovalState.APPROVED_FOR_TASK
    assert same_task.outcome == TrustDecisionOutcome.ALLOWED
    assert same_task.grant is not None
    assert same_task.grant.scope == PermissionScope.TASK
    assert other_task.outcome == TrustDecisionOutcome.DOWNGRADED
    assert other_task.approval_request is not None
    assert other_task.approval_request.approval_request_id != pending.approval_request.approval_request_id

    pending_once = trust.evaluate_action(_software_install_request(request_id="grant-once-1", task_id=""))
    assert pending_once.approval_request is not None
    granted_once = trust.respond_to_request(
        approval_request_id=pending_once.approval_request.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
        task_id="",
    )
    consumed_once = trust.mark_action_executed(
        action_request=_software_install_request(request_id="grant-once-1", task_id=""),
        grant=granted_once.grant,
        summary="Executed a once-scoped approval.",
    )
    requires_refresh = trust.evaluate_action(
        TrustActionRequest(
            request_id="grant-once-2",
            family="software_control",
            action_key="software_control.install",
            subject="firefox",
            session_id="default",
            task_id="",
            action_kind=TrustActionKind.SOFTWARE_CONTROL,
            approval_required=True,
            preview_allowed=False,
            suggested_scope=PermissionScope.ONCE,
            available_scopes=[PermissionScope.ONCE, PermissionScope.SESSION],
            operator_justification="Installing Firefox may change local software state.",
            operator_message="Approval is required before Stormhelm can install Firefox.",
            details={"target_name": "firefox"},
        )
    )

    assert consumed_once is not None
    assert consumed_once.state == ApprovalState.EXPIRED
    assert requires_refresh.outcome == TrustDecisionOutcome.CONFIRMATION_REQUIRED
    assert requires_refresh.approval_state == ApprovalState.EXPIRED


def test_trust_service_invalidates_restart_bound_pending_requests_and_dedupes_refresh(trust_harness) -> None:
    trust = trust_harness["trust_service"]
    original = trust.evaluate_action(_software_install_request(request_id="restart-pending-1", task_id="", subject="firefox"))
    assert original.approval_request is not None

    restarted = _restart_trust_service(trust_harness)
    refreshed = restarted.evaluate_action(_software_install_request(request_id="restart-pending-2", task_id="", subject="firefox"))
    repeated = restarted.evaluate_action(_software_install_request(request_id="restart-pending-3", task_id="", subject="firefox"))

    assert refreshed.outcome == TrustDecisionOutcome.DOWNGRADED
    assert repeated.outcome == TrustDecisionOutcome.DOWNGRADED
    assert refreshed.approval_request is not None
    assert repeated.approval_request is not None
    assert refreshed.approval_request.approval_request_id != original.approval_request.approval_request_id
    assert repeated.approval_request.approval_request_id == refreshed.approval_request.approval_request_id
    expired = restarted.repository.get_approval_request(original.approval_request.approval_request_id)
    assert expired is not None
    assert expired.state == ApprovalState.EXPIRED
    requested_events = [
        record
        for record in restarted.repository.list_recent_audit(session_id="default", limit=20)
        if record.event_kind == "approval.requested"
    ]
    assert len(requested_events) == 2


def test_trust_service_invalidates_once_and_session_grants_after_restart(trust_harness) -> None:
    trust = trust_harness["trust_service"]

    session_pending = trust.evaluate_action(_software_install_request(request_id="restart-session-1", task_id="", subject="git"))
    assert session_pending.approval_request is not None
    trust.respond_to_request(
        approval_request_id=session_pending.approval_request.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.SESSION,
        task_id="",
    )

    once_pending = trust.evaluate_action(_software_install_request(request_id="restart-once-1", task_id="", subject="obs"))
    assert once_pending.approval_request is not None
    trust.respond_to_request(
        approval_request_id=once_pending.approval_request.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.ONCE,
        task_id="",
    )

    restarted = _restart_trust_service(trust_harness)
    session_refresh = restarted.evaluate_action(_software_install_request(request_id="restart-session-2", task_id="", subject="git"))
    once_refresh = restarted.evaluate_action(_software_install_request(request_id="restart-once-2", task_id="", subject="obs"))

    assert session_refresh.outcome == TrustDecisionOutcome.DOWNGRADED
    assert once_refresh.outcome == TrustDecisionOutcome.DOWNGRADED
    assert session_refresh.approval_state == ApprovalState.EXPIRED
    assert once_refresh.approval_state == ApprovalState.EXPIRED


def test_trust_service_keeps_task_grants_valid_across_restart_but_expires_after_task_completion(trust_harness) -> None:
    trust = trust_harness["trust_service"]
    _save_task(trust_harness, task_id="task-restart", state=TaskState.IN_PROGRESS)

    pending = trust.evaluate_action(_software_install_request(request_id="task-restart-1", task_id="task-restart"))
    assert pending.approval_request is not None
    trust.respond_to_request(
        approval_request_id=pending.approval_request.approval_request_id,
        decision="approve",
        session_id="default",
        scope=PermissionScope.TASK,
        task_id="task-restart",
    )

    restarted = _restart_trust_service(trust_harness)
    preserved = restarted.evaluate_action(_software_install_request(request_id="task-restart-2", task_id="task-restart"))
    assert preserved.outcome == TrustDecisionOutcome.ALLOWED
    assert preserved.approval_state == ApprovalState.APPROVED_FOR_TASK

    _save_task(trust_harness, task_id="task-restart", state=TaskState.COMPLETED)
    expired = restarted.evaluate_action(_software_install_request(request_id="task-restart-3", task_id="task-restart"))

    assert expired.outcome == TrustDecisionOutcome.DOWNGRADED
    assert expired.approval_state == ApprovalState.EXPIRED
