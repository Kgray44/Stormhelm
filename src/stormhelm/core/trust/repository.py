from __future__ import annotations

import json
from typing import Any

from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.trust.models import (
    ApprovalRequest,
    ApprovalState,
    AuditRecord,
    PermissionGrant,
    PermissionScope,
    TrustActionKind,
)
from stormhelm.shared.json_safety import decode_json_dict, decode_json_value


class TrustRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save_approval_request(self, request: ApprovalRequest) -> ApprovalRequest:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO trust_approval_requests(
                    approval_request_id,
                    action_request_id,
                    family,
                    action_key,
                    subject,
                    session_id,
                    task_id,
                    action_kind,
                    state,
                    suggested_scope,
                    available_scopes_json,
                    operator_justification,
                    operator_message,
                    details_json,
                    created_at,
                    updated_at,
                    expires_at,
                    resolved_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(approval_request_id) DO UPDATE SET
                    state = excluded.state,
                    suggested_scope = excluded.suggested_scope,
                    available_scopes_json = excluded.available_scopes_json,
                    operator_justification = excluded.operator_justification,
                    operator_message = excluded.operator_message,
                    details_json = excluded.details_json,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    resolved_at = excluded.resolved_at
                """,
                (
                    request.approval_request_id,
                    request.action_request_id,
                    request.family,
                    request.action_key,
                    request.subject,
                    request.session_id,
                    request.task_id,
                    request.action_kind.value,
                    request.state.value,
                    request.suggested_scope.value,
                    json.dumps([scope.value for scope in request.available_scopes]),
                    request.operator_justification,
                    request.operator_message,
                    json.dumps(request.details),
                    request.created_at,
                    request.updated_at,
                    request.expires_at,
                    request.resolved_at,
                ),
            )
        return request

    def get_approval_request(self, approval_request_id: str) -> ApprovalRequest | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT approval_request_id, action_request_id, family, action_key, subject, session_id, task_id,
                       action_kind, state, suggested_scope, available_scopes_json, operator_justification,
                       operator_message, details_json, created_at, updated_at, expires_at, resolved_at
                FROM trust_approval_requests
                WHERE approval_request_id = ?
                """,
                (approval_request_id,),
            ).fetchone()
        return self._approval_request_from_row(row) if row is not None else None

    def latest_pending_request(
        self,
        *,
        session_id: str,
        family: str,
        action_key: str,
        subject: str,
        task_id: str = "",
    ) -> ApprovalRequest | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT approval_request_id, action_request_id, family, action_key, subject, session_id, task_id,
                       action_kind, state, suggested_scope, available_scopes_json, operator_justification,
                       operator_message, details_json, created_at, updated_at, expires_at, resolved_at
                FROM trust_approval_requests
                WHERE session_id = ?
                  AND family = ?
                  AND action_key = ?
                  AND subject = ?
                  AND COALESCE(task_id, '') = ?
                  AND state = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (
                    session_id,
                    family,
                    action_key,
                    subject,
                    task_id,
                    ApprovalState.PENDING_OPERATOR_CONFIRMATION.value,
                ),
            ).fetchone()
        return self._approval_request_from_row(row) if row is not None else None

    def list_pending_requests(self, *, session_id: str) -> list[ApprovalRequest]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT approval_request_id, action_request_id, family, action_key, subject, session_id, task_id,
                       action_kind, state, suggested_scope, available_scopes_json, operator_justification,
                       operator_message, details_json, created_at, updated_at, expires_at, resolved_at
                FROM trust_approval_requests
                WHERE session_id = ? AND state = ?
                ORDER BY created_at DESC
                """,
                (session_id, ApprovalState.PENDING_OPERATOR_CONFIRMATION.value),
            ).fetchall()
        return [self._approval_request_from_row(row) for row in rows]

    def save_grant(self, grant: PermissionGrant) -> PermissionGrant:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO trust_permission_grants(
                    grant_id,
                    approval_request_id,
                    family,
                    action_key,
                    subject,
                    session_id,
                    task_id,
                    scope,
                    state,
                    operator_justification,
                    details_json,
                    granted_at,
                    expires_at,
                    revoked_at,
                    revoked_reason,
                    last_used_at,
                    use_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(grant_id) DO UPDATE SET
                    state = excluded.state,
                    operator_justification = excluded.operator_justification,
                    details_json = excluded.details_json,
                    expires_at = excluded.expires_at,
                    revoked_at = excluded.revoked_at,
                    revoked_reason = excluded.revoked_reason,
                    last_used_at = excluded.last_used_at,
                    use_count = excluded.use_count
                """,
                (
                    grant.grant_id,
                    grant.approval_request_id,
                    grant.family,
                    grant.action_key,
                    grant.subject,
                    grant.session_id,
                    grant.task_id,
                    grant.scope.value,
                    grant.state.value,
                    grant.operator_justification,
                    json.dumps(grant.details),
                    grant.granted_at,
                    grant.expires_at,
                    grant.revoked_at,
                    grant.revoked_reason,
                    grant.last_used_at,
                    grant.use_count,
                ),
            )
        return grant

    def list_grants(self, *, session_id: str) -> list[PermissionGrant]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT grant_id, approval_request_id, family, action_key, subject, session_id, task_id, scope,
                       state, operator_justification, details_json, granted_at, expires_at, revoked_at,
                       revoked_reason, last_used_at, use_count
                FROM trust_permission_grants
                WHERE session_id = ?
                ORDER BY granted_at DESC
                """,
                (session_id,),
            ).fetchall()
        return [self._grant_from_row(row) for row in rows]

    def find_active_grants(
        self,
        *,
        session_id: str,
        family: str,
        action_key: str,
        subject: str,
    ) -> list[PermissionGrant]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT grant_id, approval_request_id, family, action_key, subject, session_id, task_id, scope,
                       state, operator_justification, details_json, granted_at, expires_at, revoked_at,
                       revoked_reason, last_used_at, use_count
                FROM trust_permission_grants
                WHERE session_id = ?
                  AND family = ?
                  AND action_key = ?
                  AND subject = ?
                ORDER BY granted_at DESC
                """,
                (session_id, family, action_key, subject),
            ).fetchall()
        return [self._grant_from_row(row) for row in rows]

    def save_audit_record(self, record: AuditRecord) -> AuditRecord:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO trust_audit_records(
                    audit_id,
                    event_kind,
                    family,
                    action_key,
                    subject,
                    session_id,
                    task_id,
                    approval_request_id,
                    grant_id,
                    approval_state,
                    summary,
                    details_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.audit_id,
                    record.event_kind,
                    record.family,
                    record.action_key,
                    record.subject,
                    record.session_id,
                    record.task_id,
                    record.approval_request_id,
                    record.grant_id,
                    record.approval_state.value,
                    record.summary,
                    json.dumps(record.details),
                    record.created_at,
                ),
            )
        return record

    def list_recent_audit(self, *, session_id: str, limit: int = 24) -> list[AuditRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT audit_id, event_kind, family, action_key, subject, session_id, task_id,
                       approval_request_id, grant_id, approval_state, summary, details_json, created_at
                FROM trust_audit_records
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [self._audit_from_row(row) for row in rows]

    def _approval_request_from_row(self, row: Any) -> ApprovalRequest:
        scopes = decode_json_value(
            row["available_scopes_json"],
            context=f"trust_approval_requests.available_scopes_json[{row['approval_request_id']}]",
        )
        if not isinstance(scopes, list):
            scopes = []
        return ApprovalRequest(
            approval_request_id=row["approval_request_id"],
            action_request_id=row["action_request_id"],
            family=row["family"],
            action_key=row["action_key"],
            subject=row["subject"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            action_kind=TrustActionKind(str(row["action_kind"] or TrustActionKind.TOOL.value)),
            state=ApprovalState(str(row["state"] or ApprovalState.PENDING_OPERATOR_CONFIRMATION.value)),
            suggested_scope=PermissionScope(str(row["suggested_scope"] or PermissionScope.ONCE.value)),
            available_scopes=[
                PermissionScope(str(scope))
                for scope in scopes
                if str(scope) in {item.value for item in PermissionScope}
            ]
            or [PermissionScope.ONCE],
            operator_justification=row["operator_justification"],
            operator_message=row["operator_message"],
            details=decode_json_dict(
                row["details_json"],
                context=f"trust_approval_requests.details_json[{row['approval_request_id']}]",
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            resolved_at=row["resolved_at"],
        )

    def _grant_from_row(self, row: Any) -> PermissionGrant:
        return PermissionGrant(
            grant_id=row["grant_id"],
            approval_request_id=row["approval_request_id"],
            family=row["family"],
            action_key=row["action_key"],
            subject=row["subject"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            scope=PermissionScope(str(row["scope"] or PermissionScope.ONCE.value)),
            state=ApprovalState(str(row["state"] or ApprovalState.APPROVED_ONCE.value)),
            operator_justification=row["operator_justification"],
            details=decode_json_dict(
                row["details_json"],
                context=f"trust_permission_grants.details_json[{row['grant_id']}]",
            ),
            granted_at=row["granted_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
            revoked_reason=row["revoked_reason"],
            last_used_at=row["last_used_at"],
            use_count=int(row["use_count"] or 0),
        )

    def _audit_from_row(self, row: Any) -> AuditRecord:
        return AuditRecord(
            audit_id=row["audit_id"],
            event_kind=row["event_kind"],
            family=row["family"],
            action_key=row["action_key"],
            subject=row["subject"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            approval_request_id=row["approval_request_id"],
            grant_id=row["grant_id"],
            approval_state=ApprovalState(str(row["approval_state"] or ApprovalState.NOT_REQUIRED.value)),
            summary=row["summary"],
            details=decode_json_dict(
                row["details_json"],
                context=f"trust_audit_records.details_json[{row['audit_id']}]",
            ),
            created_at=row["created_at"],
        )
