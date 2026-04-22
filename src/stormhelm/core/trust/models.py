from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {str(key): _serialize(item) for key, item in asdict(value).items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class ApprovalState(StrEnum):
    NOT_REQUIRED = "not_required"
    PREVIEW_ONLY = "preview_only"
    PENDING_OPERATOR_CONFIRMATION = "pending_operator_confirmation"
    APPROVED_ONCE = "approved_once"
    APPROVED_FOR_SESSION = "approved_for_session"
    APPROVED_FOR_TASK = "approved_for_task"
    DENIED = "denied"
    EXPIRED = "expired"
    REVOKED = "revoked"


class PermissionScope(StrEnum):
    ONCE = "once"
    SESSION = "session"
    TASK = "task"


class TrustDecisionOutcome(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    DOWNGRADED = "downgraded"
    CONFIRMATION_REQUIRED = "confirmation_required"


class TrustActionKind(StrEnum):
    TOOL = "tool"
    SOFTWARE_CONTROL = "software_control"
    DISCORD_RELAY = "discord_relay"
    RECOVERY = "recovery"
    VERIFICATION = "verification"


@dataclass(slots=True)
class TrustActionRequest:
    request_id: str
    family: str
    action_key: str
    subject: str
    session_id: str
    task_id: str = ""
    action_kind: TrustActionKind = TrustActionKind.TOOL
    approval_required: bool = True
    preview_allowed: bool = False
    suggested_scope: PermissionScope = PermissionScope.ONCE
    available_scopes: list[PermissionScope] = field(default_factory=lambda: [PermissionScope.ONCE])
    operator_justification: str = ""
    operator_message: str = ""
    verification_label: str = ""
    recovery_label: str = ""
    task_binding_label: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class ApprovalRequest:
    approval_request_id: str
    action_request_id: str
    family: str
    action_key: str
    subject: str
    session_id: str
    task_id: str = ""
    action_kind: TrustActionKind = TrustActionKind.TOOL
    state: ApprovalState = ApprovalState.PENDING_OPERATOR_CONFIRMATION
    suggested_scope: PermissionScope = PermissionScope.ONCE
    available_scopes: list[PermissionScope] = field(default_factory=lambda: [PermissionScope.ONCE])
    operator_justification: str = ""
    operator_message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""
    resolved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class PermissionGrant:
    grant_id: str
    approval_request_id: str
    family: str
    action_key: str
    subject: str
    session_id: str
    task_id: str = ""
    scope: PermissionScope = PermissionScope.ONCE
    state: ApprovalState = ApprovalState.APPROVED_ONCE
    operator_justification: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    granted_at: str = ""
    expires_at: str = ""
    revoked_at: str = ""
    revoked_reason: str = ""
    last_used_at: str = ""
    use_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class AuditRecord:
    audit_id: str
    event_kind: str
    family: str
    action_key: str
    subject: str
    session_id: str
    task_id: str = ""
    approval_request_id: str = ""
    grant_id: str = ""
    approval_state: ApprovalState = ApprovalState.NOT_REQUIRED
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass(slots=True)
class TrustDecision:
    outcome: TrustDecisionOutcome
    approval_state: ApprovalState
    reason: str
    operator_message: str
    action_request: TrustActionRequest
    approval_request: ApprovalRequest | None = None
    grant: PermissionGrant | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.outcome == TrustDecisionOutcome.ALLOWED

    def to_dict(self) -> dict[str, Any]:
        payload = _serialize(self)
        payload["allowed"] = self.allowed
        payload["decision"] = self.outcome.value
        return payload


@dataclass(slots=True)
class TrustPostureSummary:
    enabled: bool
    active_grants: list[PermissionGrant] = field(default_factory=list)
    pending_requests: list[ApprovalRequest] = field(default_factory=list)
    recent_audit: list[AuditRecord] = field(default_factory=list)
    active_task_id: str = ""
    ghost_card: dict[str, Any] = field(default_factory=dict)
    deck_groups: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "active_task_id": self.active_task_id,
            "active_grant_count": len(self.active_grants),
            "pending_request_count": len(self.pending_requests),
            "active_grants": [grant.to_dict() for grant in self.active_grants],
            "pending_requests": [request.to_dict() for request in self.pending_requests],
            "recent_audit": [record.to_dict() for record in self.recent_audit],
            "ghost_card": dict(self.ghost_card),
            "deck_groups": [dict(group) for group in self.deck_groups],
        }
