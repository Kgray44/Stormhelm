from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from stormhelm.config.models import TrustConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.trust.models import (
    ApprovalRequest,
    ApprovalState,
    AuditRecord,
    PermissionGrant,
    PermissionScope,
    TrustActionRequest,
    TrustDecision,
    TrustDecisionOutcome,
    TrustPostureSummary,
)
from stormhelm.core.trust.repository import TrustRepository
from stormhelm.shared.time import utc_now_iso


_SESSION_SCOPE_LABEL = {
    PermissionScope.ONCE: "once",
    PermissionScope.SESSION: "this session",
    PermissionScope.TASK: "this task",
}

_APPROVED_STATE_FOR_SCOPE = {
    PermissionScope.ONCE: ApprovalState.APPROVED_ONCE,
    PermissionScope.SESSION: ApprovalState.APPROVED_FOR_SESSION,
    PermissionScope.TASK: ApprovalState.APPROVED_FOR_TASK,
}

_RUNTIME_SESSION_DETAIL_KEY = "runtime_session_id"
_EXPIRY_REASON_DETAIL_KEY = "expiry_reason"
_TASK_BINDING_REASON_DETAIL_KEY = "task_binding_reason"


def _parse_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso_after(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, float(seconds)))).isoformat()


class TrustService:
    def __init__(
        self,
        *,
        config: TrustConfig,
        repository: TrustRepository,
        events: EventBuffer,
        session_state: ConversationStateStore | None = None,
        task_service: object | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.events = events
        self.session_state = session_state
        self.task_service = task_service
        self._runtime_session_id = uuid4().hex

    def status_snapshot(self, *, session_id: str = "default", active_task_id: str = "") -> dict[str, Any]:
        return self.summarize_posture(session_id=session_id, active_task_id=active_task_id).to_dict()

    def summarize_posture(self, *, session_id: str, active_task_id: str = "") -> TrustPostureSummary:
        self._expire_stale_state(session_id=session_id)
        pending_requests = self.repository.list_pending_requests(session_id=session_id)
        all_grants = self.repository.list_grants(session_id=session_id)
        active_grants = [
            grant
            for grant in all_grants
            if self._grant_state(grant, task_id=active_task_id) in {
                ApprovalState.APPROVED_ONCE,
                ApprovalState.APPROVED_FOR_SESSION,
                ApprovalState.APPROVED_FOR_TASK,
            }
        ]
        recent_audit = self.repository.list_recent_audit(
            session_id=session_id,
            limit=max(1, int(self.config.audit_recent_limit)),
        )

        ghost_card: dict[str, Any] = {}
        if pending_requests:
            request = pending_requests[0]
            ghost_card = {
                "title": "Approval Needed",
                "subtitle": request.subject or request.family,
                "body": request.operator_message or request.operator_justification,
            }
        elif active_grants:
            grant = active_grants[0]
            ghost_card = {
                "title": "Trust Steady",
                "subtitle": grant.subject or grant.family,
                "body": f"Using an active {_SESSION_SCOPE_LABEL.get(grant.scope, 'bounded')} grant for {grant.action_key}.",
            }

        deck_groups = [
            {
                "title": "Pending Approval",
                "entries": [
                    {
                        "title": request.subject or request.family,
                        "status": request.state.value,
                        "detail": request.operator_message or request.operator_justification,
                    }
                    for request in pending_requests[:4]
                ]
                or [
                    {
                        "title": "No pending approval",
                        "status": "steady",
                        "detail": "Stormhelm is not waiting on an operator trust decision right now.",
                    }
                ],
            },
            {
                "title": "Active Grants",
                "entries": [
                    {
                        "title": grant.subject or grant.family,
                        "status": grant.state.value,
                        "detail": f"{grant.action_key} allowed for {_SESSION_SCOPE_LABEL.get(grant.scope, grant.scope.value)}.",
                    }
                    for grant in active_grants[:4]
                ]
                or [
                    {
                        "title": "No active grants",
                        "status": "steady",
                        "detail": "Stormhelm is not holding a reusable sensitive-action grant right now.",
                    }
                ],
            },
            {
                "title": "Recent Trust",
                "entries": [
                    {
                        "title": record.summary or record.event_kind,
                        "status": record.approval_state.value,
                        "detail": record.family,
                    }
                    for record in recent_audit[:4]
                ]
                or [
                    {
                        "title": "No recent trust audit",
                        "status": "steady",
                        "detail": "Meaningful trust actions will appear here when they occur.",
                    }
                ],
            },
        ]

        return TrustPostureSummary(
            enabled=self.config.enabled,
            active_grants=active_grants,
            pending_requests=pending_requests,
            recent_audit=recent_audit,
            active_task_id=active_task_id,
            ghost_card=ghost_card,
            deck_groups=deck_groups,
        )

    def evaluate_action(self, action_request: TrustActionRequest) -> TrustDecision:
        if not self.config.enabled or not action_request.approval_required:
            return TrustDecision(
                outcome=TrustDecisionOutcome.ALLOWED,
                approval_state=ApprovalState.NOT_REQUIRED,
                reason="Approval is not required for this action.",
                operator_message=action_request.operator_message or "Approval is not required for this action.",
                action_request=action_request,
            )

        self._expire_stale_state(session_id=action_request.session_id)
        matched_grant, prior_state = self._matching_grant(action_request)
        if matched_grant is not None:
            grant_state = self._grant_state(matched_grant, task_id=action_request.task_id)
            if matched_grant.state != grant_state:
                matched_grant.state = grant_state
                self.repository.save_grant(matched_grant)
            return TrustDecision(
                outcome=TrustDecisionOutcome.ALLOWED,
                approval_state=grant_state,
                reason=f"Using an active {_SESSION_SCOPE_LABEL.get(matched_grant.scope, matched_grant.scope.value)} grant.",
                operator_message=(
                    f"Using the existing {_SESSION_SCOPE_LABEL.get(matched_grant.scope, matched_grant.scope.value)} grant "
                    f"for {action_request.subject or action_request.family}."
                ),
                action_request=action_request,
                grant=matched_grant,
                details={"grant_id": matched_grant.grant_id},
            )

        denied_request = self.repository.latest_denied_request(
            session_id=action_request.session_id,
            family=action_request.family,
            action_key=action_request.action_key,
            subject=action_request.subject,
            task_id=action_request.task_id,
        )
        if denied_request is not None and not self._request_expired(denied_request):
            decision = TrustDecision(
                outcome=TrustDecisionOutcome.BLOCKED,
                approval_state=ApprovalState.DENIED,
                reason="The operator denied this request.",
                operator_message=denied_request.operator_message or f"Denied {action_request.subject or action_request.family}.",
                action_request=action_request,
                approval_request=denied_request,
            )
            self._record_task_trust_denied(task_id=denied_request.task_id, request=denied_request)
            return decision

        request = self.repository.latest_pending_request(
            session_id=action_request.session_id,
            family=action_request.family,
            action_key=action_request.action_key,
            subject=action_request.subject,
            task_id=action_request.task_id,
        )
        request_created = False
        if request is None or self._request_expired(request):
            request_details = self._runtime_bound_details(action_request.details)
            if action_request.task_id:
                request_details[_TASK_BINDING_REASON_DETAIL_KEY] = self._task_binding_status(action_request.task_id).get("reason", "")
            request = ApprovalRequest(
                approval_request_id=f"trust-{uuid4()}",
                action_request_id=action_request.request_id,
                family=action_request.family,
                action_key=action_request.action_key,
                subject=action_request.subject,
                session_id=action_request.session_id,
                task_id=action_request.task_id,
                action_kind=action_request.action_kind,
                state=ApprovalState.PENDING_OPERATOR_CONFIRMATION,
                suggested_scope=action_request.suggested_scope,
                available_scopes=list(action_request.available_scopes),
                operator_justification=action_request.operator_justification,
                operator_message=action_request.operator_message,
                details=request_details,
                created_at=utc_now_iso(),
                updated_at=utc_now_iso(),
                expires_at=_iso_after(self.config.pending_request_ttl_seconds),
            )
            self.repository.save_approval_request(request)
            self._audit(
                event_kind="approval.requested",
                approval_state=ApprovalState.PENDING_OPERATOR_CONFIRMATION,
                action_request=action_request,
                summary=request.operator_message or request.operator_justification or "Approval requested.",
                approval_request_id=request.approval_request_id,
                details={"suggested_scope": request.suggested_scope.value},
            )
            self._publish_approval_event(
                event_type="approval.requested",
                severity="warning",
                session_id=action_request.session_id,
                subject=action_request.subject,
                message=request.operator_message or "Approval requested before continuing.",
                payload={
                    "family": action_request.family,
                    "action_key": action_request.action_key,
                    "approval_request_id": request.approval_request_id,
                    "suggested_scope": request.suggested_scope.value,
                    "available_scopes": [scope.value for scope in request.available_scopes],
                },
                visibility_scope="operator_blocking",
            )
            request_created = True

        if action_request.preview_allowed:
            if request_created:
                self._audit(
                    event_kind="approval.preview_only",
                    approval_state=ApprovalState.PREVIEW_ONLY,
                    action_request=action_request,
                    summary=f"Held {action_request.action_key} at preview until approval is granted.",
                    approval_request_id=request.approval_request_id,
                )
            approval_state = prior_state or ApprovalState.PREVIEW_ONLY
            operator_message = action_request.operator_message or "Prepared a preview only. Approval is still required to continue."
            if prior_state == ApprovalState.EXPIRED:
                operator_message = "The earlier grant expired, so I held the action at preview until you approve it again."
            elif prior_state == ApprovalState.REVOKED:
                operator_message = "That grant was revoked, so I held the action at preview until you approve it again."
            decision = TrustDecision(
                outcome=TrustDecisionOutcome.DOWNGRADED,
                approval_state=approval_state,
                reason="Approval is still required before execution, so Stormhelm stayed at preview.",
                operator_message=operator_message,
                action_request=action_request,
                approval_request=request,
            )
            self._record_task_trust_pending(task_id=action_request.task_id, request=request, decision=decision)
            return decision

        approval_state = prior_state or ApprovalState.PENDING_OPERATOR_CONFIRMATION
        operator_message = request.operator_message or "Approval is required before continuing."
        if prior_state == ApprovalState.EXPIRED:
            operator_message = "The earlier grant expired. Approval is required before continuing."
        elif prior_state == ApprovalState.REVOKED:
            operator_message = "That grant was revoked. Approval is required before continuing."
        decision = TrustDecision(
            outcome=TrustDecisionOutcome.CONFIRMATION_REQUIRED,
            approval_state=approval_state,
            reason="Approval is required before Stormhelm can continue.",
            operator_message=operator_message,
            action_request=action_request,
            approval_request=request,
        )
        self._record_task_trust_pending(task_id=action_request.task_id, request=request, decision=decision)
        return decision

    def respond_to_request(
        self,
        *,
        approval_request_id: str,
        decision: str,
        session_id: str,
        scope: PermissionScope | None = None,
        task_id: str = "",
    ) -> TrustDecision:
        request = self.repository.get_approval_request(approval_request_id)
        if request is None:
            action_request = TrustActionRequest(
                request_id="missing-request",
                family="trust",
                action_key="trust.missing_request",
                subject=approval_request_id,
                session_id=session_id,
                task_id=task_id,
                approval_required=False,
                operator_message="That approval prompt is no longer active. Ask again and I will refresh it.",
            )
            return TrustDecision(
                outcome=TrustDecisionOutcome.CONFIRMATION_REQUIRED,
                approval_state=ApprovalState.EXPIRED,
                reason="Pending approval request not found.",
                operator_message=action_request.operator_message,
                action_request=action_request,
            )

        action_request = TrustActionRequest(
            request_id=request.action_request_id,
            family=request.family,
            action_key=request.action_key,
            subject=request.subject,
            session_id=session_id,
            task_id=task_id or request.task_id,
            action_kind=request.action_kind,
            suggested_scope=request.suggested_scope,
            available_scopes=list(request.available_scopes),
            operator_justification=request.operator_justification,
            operator_message=request.operator_message,
            details=dict(request.details),
        )
        requested_task_id = str(task_id or "").strip()
        if request.task_id and requested_task_id and request.task_id != requested_task_id:
            self._expire_request(request, reason="task_mismatch")
            action_request.task_id = requested_task_id
            action_request.details = self._runtime_bound_details(action_request.details)
            action_request.details[_TASK_BINDING_REASON_DETAIL_KEY] = "task_mismatch"
            return TrustDecision(
                outcome=TrustDecisionOutcome.CONFIRMATION_REQUIRED,
                approval_state=ApprovalState.EXPIRED,
                reason="The pending approval request belonged to a different task.",
                operator_message="That approval prompt belonged to a different task. Ask again and I will refresh it.",
                action_request=action_request,
                approval_request=request,
            )
        if self._request_expired(request):
            self._expire_request(
                request,
                reason=self._request_invalidation_reason(request) or "ttl_expired",
            )
            return TrustDecision(
                outcome=TrustDecisionOutcome.CONFIRMATION_REQUIRED,
                approval_state=ApprovalState.EXPIRED,
                reason="The pending approval request expired.",
                operator_message="That approval prompt expired. Ask again and I will refresh it.",
                action_request=action_request,
                approval_request=request,
            )

        normalized_decision = str(decision or "approve").strip().lower()
        if normalized_decision in {"deny", "denied", "reject", "cancel", "blocked"}:
            request.state = ApprovalState.DENIED
            request.updated_at = utc_now_iso()
            request.resolved_at = request.updated_at
            self.repository.save_approval_request(request)
            self._audit(
                event_kind="approval.denied",
                approval_state=ApprovalState.DENIED,
                action_request=action_request,
                summary=f"Denied {request.action_key} for {request.subject or request.family}.",
                approval_request_id=request.approval_request_id,
            )
            self._publish_approval_event(
                event_type="approval.denied",
                severity="warning",
                session_id=session_id,
                subject=request.subject,
                message=f"Denied {request.subject or request.family}.",
                payload={"approval_request_id": request.approval_request_id, "family": request.family},
                visibility_scope="ghost_hint",
            )
            self._record_task_trust_denied(task_id=request.task_id, request=request)
            return TrustDecision(
                outcome=TrustDecisionOutcome.BLOCKED,
                approval_state=ApprovalState.DENIED,
                reason="The operator denied this request.",
                operator_message=f"Denied {request.subject or request.family}.",
                action_request=action_request,
                approval_request=request,
            )

        grant_scope = scope or request.suggested_scope
        grant_state = _APPROVED_STATE_FOR_SCOPE.get(grant_scope, ApprovalState.APPROVED_ONCE)
        timestamp = utc_now_iso()
        grant = PermissionGrant(
            grant_id=f"grant-{uuid4()}",
            approval_request_id=request.approval_request_id,
            family=request.family,
            action_key=request.action_key,
            subject=request.subject,
            session_id=session_id,
            task_id=request.task_id if grant_scope == PermissionScope.TASK else "",
            scope=grant_scope,
            state=grant_state,
            operator_justification=request.operator_justification,
            details=self._runtime_bound_details(request.details),
            granted_at=timestamp,
            expires_at=self._grant_expiry(grant_scope),
        )
        request.state = grant_state
        request.updated_at = timestamp
        request.resolved_at = timestamp
        self.repository.save_approval_request(request)
        self.repository.save_grant(grant)
        self._audit(
            event_kind="approval.granted",
            approval_state=grant_state,
            action_request=action_request,
            summary=f"Granted {request.action_key} for {_SESSION_SCOPE_LABEL.get(grant_scope, grant_scope.value)}.",
            approval_request_id=request.approval_request_id,
            grant_id=grant.grant_id,
            details={"scope": grant_scope.value},
        )
        self._publish_approval_event(
            event_type="approval.granted",
            severity="info",
            session_id=session_id,
            subject=request.subject,
            message=f"Granted {request.subject or request.family} for {_SESSION_SCOPE_LABEL.get(grant_scope, grant_scope.value)}.",
            payload={
                "approval_request_id": request.approval_request_id,
                "grant_id": grant.grant_id,
                "scope": grant_scope.value,
                "family": request.family,
            },
            visibility_scope="deck_context",
        )
        self._record_task_trust_granted(task_id=request.task_id, request=request, grant=grant)
        return TrustDecision(
            outcome=TrustDecisionOutcome.ALLOWED,
            approval_state=grant_state,
            reason=f"Granted for {_SESSION_SCOPE_LABEL.get(grant_scope, grant_scope.value)}.",
            operator_message=f"Granted for {_SESSION_SCOPE_LABEL.get(grant_scope, grant_scope.value)}.",
            action_request=action_request,
            approval_request=request,
            grant=grant,
        )

    def mark_action_executed(
        self,
        *,
        action_request: TrustActionRequest,
        grant: PermissionGrant | None,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> PermissionGrant | None:
        grant_state = grant.state if grant is not None else ApprovalState.NOT_REQUIRED
        if grant is not None:
            updated = replace(grant)
            updated.last_used_at = utc_now_iso()
            updated.use_count = int(updated.use_count or 0) + 1
            if updated.scope == PermissionScope.ONCE:
                updated.state = ApprovalState.EXPIRED
                updated.expires_at = updated.last_used_at
            self.repository.save_grant(updated)
            grant = updated
        self._audit(
            event_kind="approval.action_executed",
            approval_state=grant_state,
            action_request=action_request,
            summary=summary,
            grant_id=grant.grant_id if grant is not None else "",
            details=details or {},
        )
        return grant

    def revoke_matching_grants(
        self,
        *,
        session_id: str,
        family: str,
        action_key: str,
        subject: str,
        reason: str = "revoked_by_operator",
    ) -> int:
        count = 0
        for grant in self.repository.find_active_grants(
            session_id=session_id,
            family=family,
            action_key=action_key,
            subject=subject,
        ):
            active_state = self._grant_state(grant, task_id=grant.task_id)
            if active_state not in {
                ApprovalState.APPROVED_ONCE,
                ApprovalState.APPROVED_FOR_SESSION,
                ApprovalState.APPROVED_FOR_TASK,
            }:
                continue
            grant.state = ApprovalState.REVOKED
            grant.revoked_at = utc_now_iso()
            grant.revoked_reason = reason
            self.repository.save_grant(grant)
            count += 1
            self._audit(
                event_kind="approval.revoked",
                approval_state=ApprovalState.REVOKED,
                action_request=TrustActionRequest(
                    request_id=f"revoke-{grant.grant_id}",
                    family=family,
                    action_key=action_key,
                    subject=subject,
                    session_id=session_id,
                    task_id=grant.task_id,
                    approval_required=False,
                ),
                summary=f"Revoked {action_key} for {subject or family}.",
                grant_id=grant.grant_id,
                details={"reason": reason},
            )
        return count

    def attach_request_state(
        self,
        base_state: dict[str, object] | None,
        *,
        decision: TrustDecision,
    ) -> dict[str, object]:
        state = dict(base_state or {})
        task_id = ""
        if decision.grant is not None and decision.grant.task_id:
            task_id = decision.grant.task_id
        elif decision.approval_request is not None and decision.approval_request.task_id:
            task_id = decision.approval_request.task_id
        else:
            task_id = decision.action_request.task_id
        trust_payload = {
            "decision": decision.outcome.value,
            "approval_state": decision.approval_state.value,
            "reason": decision.reason,
            "operator_message": decision.operator_message,
            "request_id": decision.approval_request.approval_request_id if decision.approval_request is not None else "",
            "grant_id": decision.grant.grant_id if decision.grant is not None else "",
            "grant_scope": decision.grant.scope.value if decision.grant is not None else "",
            "action_key": decision.action_request.action_key,
            "subject": decision.action_request.subject,
            "task_id": task_id,
            "runtime_session_id": self._runtime_session_id,
            "suggested_scope": (
                decision.approval_request.suggested_scope.value
                if decision.approval_request is not None
                else decision.action_request.suggested_scope.value
            ),
            "available_scopes": [
                scope.value
                for scope in (
                    decision.approval_request.available_scopes
                    if decision.approval_request is not None
                    else decision.action_request.available_scopes
                )
            ],
            "justification": decision.action_request.operator_justification,
        }
        if decision.approval_request is not None:
            trust_payload["expires_at"] = decision.approval_request.expires_at
        if decision.grant is not None:
            trust_payload["grant_expires_at"] = decision.grant.expires_at
        state["trust"] = trust_payload
        state["task_id"] = task_id
        state["runtime_session_id"] = self._runtime_session_id
        return state

    def _matching_grant(
        self,
        action_request: TrustActionRequest,
    ) -> tuple[PermissionGrant | None, ApprovalState | None]:
        grants = self.repository.find_active_grants(
            session_id=action_request.session_id,
            family=action_request.family,
            action_key=action_request.action_key,
            subject=action_request.subject,
        )
        prior_state: ApprovalState | None = None
        ordered = sorted(
            grants,
            key=lambda item: item.granted_at,
            reverse=True,
        )
        ordered = sorted(
            ordered,
            key=lambda item: (
                0 if item.scope == PermissionScope.TASK else 1 if item.scope == PermissionScope.SESSION else 2,
            ),
        )
        for grant in ordered:
            state = self._grant_state(grant, task_id=action_request.task_id)
            if state in {
                ApprovalState.APPROVED_ONCE,
                ApprovalState.APPROVED_FOR_SESSION,
                ApprovalState.APPROVED_FOR_TASK,
            }:
                if grant.scope == PermissionScope.TASK and action_request.task_id and grant.task_id != action_request.task_id:
                    continue
                return grant, None
            if prior_state is None and state in {ApprovalState.EXPIRED, ApprovalState.REVOKED}:
                prior_state = state
        return None, prior_state

    def _grant_state(self, grant: PermissionGrant, *, task_id: str = "") -> ApprovalState:
        if grant.state == ApprovalState.EXPIRED:
            return ApprovalState.EXPIRED
        invalidation_reason = self._grant_invalidation_reason(grant, task_id=task_id)
        if invalidation_reason == "revoked":
            return ApprovalState.REVOKED
        if invalidation_reason:
            return ApprovalState.EXPIRED
        return _APPROVED_STATE_FOR_SCOPE.get(grant.scope, ApprovalState.APPROVED_ONCE)

    def _request_expired(self, request: ApprovalRequest) -> bool:
        return bool(self._request_invalidation_reason(request))

    def _grant_expiry(self, scope: PermissionScope) -> str:
        if scope == PermissionScope.ONCE:
            return _iso_after(self.config.once_grant_ttl_seconds)
        if scope == PermissionScope.SESSION:
            return _iso_after(self.config.session_grant_ttl_seconds)
        return ""

    def _expire_stale_state(self, *, session_id: str) -> None:
        for grant in self.repository.list_grants(session_id=session_id):
            invalidation_reason = self._grant_invalidation_reason(grant, task_id=grant.task_id)
            state = (
                ApprovalState.REVOKED
                if invalidation_reason == "revoked"
                else ApprovalState.EXPIRED
                if invalidation_reason
                else self._grant_state(grant, task_id=grant.task_id)
            )
            if state == grant.state:
                continue
            if state == ApprovalState.EXPIRED:
                grant.state = ApprovalState.EXPIRED
                if not grant.expires_at:
                    grant.expires_at = utc_now_iso()
                grant.details = dict(grant.details)
                grant.details[_EXPIRY_REASON_DETAIL_KEY] = invalidation_reason
                self.repository.save_grant(grant)
                self._audit(
                    event_kind="approval.expired",
                    approval_state=ApprovalState.EXPIRED,
                    action_request=TrustActionRequest(
                        request_id=f"expire-{grant.grant_id}",
                        family=grant.family,
                        action_key=grant.action_key,
                        subject=grant.subject,
                        session_id=grant.session_id,
                        task_id=grant.task_id,
                        approval_required=False,
                    ),
                    summary=f"Expired {grant.action_key} for {grant.subject or grant.family}.",
                    grant_id=grant.grant_id,
                    details={"reason": invalidation_reason, "scope": grant.scope.value},
                )

        for request in self.repository.list_pending_requests(session_id=session_id):
            invalidation_reason = self._request_invalidation_reason(request)
            if not invalidation_reason:
                continue
            self._expire_request(request, reason=invalidation_reason)

    def _runtime_bound_details(self, details: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(details or {})
        payload[_RUNTIME_SESSION_DETAIL_KEY] = self._runtime_session_id
        return payload

    def _runtime_binding_mismatch(self, details: dict[str, Any] | None) -> bool:
        runtime_session_id = str((details or {}).get(_RUNTIME_SESSION_DETAIL_KEY) or "").strip()
        return runtime_session_id != self._runtime_session_id

    def _task_binding_status(self, task_id: str) -> dict[str, Any]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return {"valid": False, "reason": "missing"}
        if self.task_service is None:
            return {"valid": True, "reason": "task_service_unavailable"}
        callback = getattr(self.task_service, "trust_binding_status", None)
        if not callable(callback):
            return {"valid": True, "reason": "task_service_unavailable"}
        result = callback(task_id=normalized_task_id)
        if isinstance(result, dict):
            return dict(result)
        return {"valid": False, "reason": "missing"}

    def _request_invalidation_reason(self, request: ApprovalRequest) -> str:
        if request.state == ApprovalState.EXPIRED:
            return "expired_state"
        expires_at = _parse_timestamp(request.expires_at)
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            return "ttl_expired"
        if self._runtime_binding_mismatch(request.details):
            return "runtime_restarted"
        if request.task_id:
            binding = self._task_binding_status(request.task_id)
            if binding.get("valid") is not True:
                return str(binding.get("reason") or "task_invalid")
        return ""

    def _grant_invalidation_reason(self, grant: PermissionGrant, *, task_id: str = "") -> str:
        if grant.state == ApprovalState.REVOKED or grant.revoked_at:
            return "revoked"
        expires_at = _parse_timestamp(grant.expires_at)
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            return "ttl_expired"
        if grant.scope in {PermissionScope.ONCE, PermissionScope.SESSION} and self._runtime_binding_mismatch(grant.details):
            return "runtime_restarted"
        if grant.scope == PermissionScope.ONCE and int(grant.use_count or 0) >= 1:
            return "once_consumed"
        if grant.scope == PermissionScope.TASK:
            if not grant.task_id or not task_id or grant.task_id != task_id:
                return "task_mismatch"
            binding = self._task_binding_status(grant.task_id)
            if binding.get("valid") is not True:
                return str(binding.get("reason") or "task_invalid")
        return ""

    def _expire_request(self, request: ApprovalRequest, *, reason: str) -> None:
        if request.state == ApprovalState.EXPIRED:
            return
        request.state = ApprovalState.EXPIRED
        request.updated_at = utc_now_iso()
        request.resolved_at = request.updated_at
        request.details = dict(request.details)
        request.details[_EXPIRY_REASON_DETAIL_KEY] = reason
        self.repository.save_approval_request(request)
        self._audit(
            event_kind="approval.expired",
            approval_state=ApprovalState.EXPIRED,
            action_request=TrustActionRequest(
                request_id=f"expire-{request.approval_request_id}",
                family=request.family,
                action_key=request.action_key,
                subject=request.subject,
                session_id=request.session_id,
                task_id=request.task_id,
                approval_required=False,
            ),
            summary=f"Expired pending approval for {request.subject or request.family}.",
            approval_request_id=request.approval_request_id,
            details={"reason": reason},
        )

    def _audit(
        self,
        *,
        event_kind: str,
        approval_state: ApprovalState,
        action_request: TrustActionRequest,
        summary: str,
        approval_request_id: str = "",
        grant_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.repository.save_audit_record(
            AuditRecord(
                audit_id=f"audit-{uuid4()}",
                event_kind=event_kind,
                family=action_request.family,
                action_key=action_request.action_key,
                subject=action_request.subject,
                session_id=action_request.session_id,
                task_id=action_request.task_id,
                approval_request_id=approval_request_id,
                grant_id=grant_id,
                approval_state=approval_state,
                summary=summary,
                details=dict(details or {}),
                created_at=utc_now_iso(),
            )
        )

    def _publish_approval_event(
        self,
        *,
        event_type: str,
        severity: str,
        session_id: str,
        subject: str,
        message: str,
        payload: dict[str, Any],
        visibility_scope: str,
    ) -> None:
        if not self.config.debug_events_enabled:
            return
        self.events.publish(
            event_family="approval",
            event_type=event_type,
            severity=severity,
            subsystem="trust",
            session_id=session_id,
            subject=subject,
            visibility_scope=visibility_scope,
            retention_class="operator_relevant",
            provenance={"channel": "trust", "kind": "direct_system_fact"},
            message=message,
            payload=dict(payload),
        )

    def _record_task_trust_pending(self, *, task_id: str, request: ApprovalRequest, decision: TrustDecision) -> None:
        if not task_id or self.task_service is None:
            return
        callback = getattr(self.task_service, "record_trust_pending", None)
        if callable(callback):
            callback(task_id=task_id, request=request.to_dict(), decision=decision.to_dict())

    def _record_task_trust_granted(
        self,
        *,
        task_id: str,
        request: ApprovalRequest,
        grant: PermissionGrant,
    ) -> None:
        if not task_id or self.task_service is None:
            return
        callback = getattr(self.task_service, "record_trust_granted", None)
        if callable(callback):
            callback(task_id=task_id, request=request.to_dict(), grant=grant.to_dict())

    def _record_task_trust_denied(self, *, task_id: str, request: ApprovalRequest) -> None:
        if not task_id or self.task_service is None:
            return
        callback = getattr(self.task_service, "record_trust_denied", None)
        if callable(callback):
            callback(task_id=task_id, request=request.to_dict())
