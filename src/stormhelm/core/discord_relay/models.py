from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class DiscordDestinationKind(StrEnum):
    PERSONAL_DM = "personal_dm"
    GROUP_DM = "group_dm"
    CHANNEL = "channel"
    SERVER_CHANNEL = "server_channel"


class DiscordRouteMode(StrEnum):
    LOCAL_CLIENT_AUTOMATION = "local_client_automation"
    OFFICIAL_BOT_WEBHOOK = "official_bot_webhook"


class DiscordDispatchState(StrEnum):
    UNRESOLVED = "unresolved"
    READY = "ready"
    STARTED = "started"
    VERIFIED = "verified"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    PREVIEW_READY = "preview_ready"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_EXPIRED = "approval_expired"
    DISPATCH_READY = "dispatch_ready"
    DISPATCH_NOT_IMPLEMENTED = "dispatch_not_implemented"
    DISPATCH_UNAVAILABLE = "dispatch_unavailable"
    DISPATCH_BLOCKED = "dispatch_blocked"
    DISPATCH_ATTEMPTING = "dispatch_attempting"
    DISPATCH_ATTEMPTED_UNVERIFIED = "dispatch_attempted_unverified"
    DISPATCH_FAILED = "dispatch_failed"
    SENT_UNVERIFIED = "sent_unverified"
    SENT_VERIFIED = "sent_verified"
    CANCELLED = "cancelled"


class DiscordLocalDispatchStepName(StrEnum):
    CAPABILITY_CHECK = "capability_check"
    FOCUS_CLIENT = "focus_client"
    IDENTIFY_DISCORD_SURFACE = "identify_discord_surface"
    NAVIGATE_RECIPIENT_DM = "navigate_recipient_dm"
    LOCATE_MESSAGE_INPUT = "locate_message_input"
    INSERT_PAYLOAD = "insert_payload"
    PERFORM_SEND_GESTURE = "perform_send_gesture"
    VERIFY_MESSAGE_VISIBLE = "verify_message_visible"


class DiscordLocalDispatchStepStatus(StrEnum):
    NOT_STARTED = "not_started"
    SKIPPED = "skipped"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"


class DiscordPayloadKind(StrEnum):
    PAGE_LINK = "page_link"
    FILE = "file"
    SELECTED_TEXT = "selected_text"
    NOTE_ARTIFACT = "note_artifact"
    CLIPBOARD_TEXT = "clipboard_text"
    SCREENSHOT_CANDIDATE = "screenshot_candidate"


class DiscordPolicyOutcome(StrEnum):
    ALLOWED = "allowed"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


@dataclass(slots=True)
class DiscordRelayCapability:
    route_mode: DiscordRouteMode
    preview_supported: bool = True
    dispatch_supported: bool = False
    verification_supported: bool = False
    requires_trust_approval: bool = True
    uses_discord_api_user_token: bool = False
    uses_discord_user_token: bool = False
    uses_self_bot: bool = False
    uses_local_client: bool = False
    adapter_kind: str = "unavailable"
    unavailable_reason: str | None = None
    route_constraint: str = "unsupported"
    can_preview: bool = True
    can_dispatch: bool = False
    can_verify_send: bool = False
    can_focus_client: bool = False
    can_launch_client: bool = False
    can_identify_discord_surface: bool = False
    can_navigate_dm: bool = False
    can_locate_message_input: bool = False
    can_insert_text: bool = False
    can_press_send: bool = False
    can_verify_sent_message: bool = False
    can_report_failure: bool = True
    rollback_posture: str = "none"
    trust_requirements: list[str] = field(default_factory=lambda: ["explicit_approval"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_mode": self.route_mode.value,
            "preview_supported": self.preview_supported,
            "dispatch_supported": self.dispatch_supported,
            "verification_supported": self.verification_supported,
            "requires_trust_approval": self.requires_trust_approval,
            "uses_discord_api_user_token": self.uses_discord_api_user_token,
            "uses_discord_user_token": self.uses_discord_user_token,
            "uses_self_bot": self.uses_self_bot,
            "uses_local_client": self.uses_local_client,
            "adapter_kind": self.adapter_kind,
            "unavailable_reason": self.unavailable_reason,
            "route_constraint": self.route_constraint,
            "can_preview": self.can_preview,
            "can_dispatch": self.can_dispatch,
            "can_verify_send": self.can_verify_send,
            "can_focus_client": self.can_focus_client,
            "can_launch_client": self.can_launch_client,
            "can_identify_discord_surface": self.can_identify_discord_surface,
            "can_navigate_dm": self.can_navigate_dm,
            "can_locate_message_input": self.can_locate_message_input,
            "can_insert_text": self.can_insert_text,
            "can_press_send": self.can_press_send,
            "can_verify_sent_message": self.can_verify_sent_message,
            "can_report_failure": self.can_report_failure,
            "rollback_posture": self.rollback_posture,
            "trust_requirements": list(self.trust_requirements),
        }


@dataclass(slots=True)
class DiscordLocalDispatchStep:
    step_id: str
    relay_request_id: str
    step_name: DiscordLocalDispatchStepName | str
    status: DiscordLocalDispatchStepStatus | str
    started_at: float | None = None
    completed_at: float | None = None
    adapter_kind: str = "unavailable"
    capability_required: str | None = None
    capability_declared: bool = False
    evidence_summary: str | None = None
    failure_reason: str | None = None
    safe_to_continue: bool = False

    def to_dict(self) -> dict[str, Any]:
        step_name = self.step_name.value if isinstance(self.step_name, StrEnum) else str(self.step_name)
        status = self.status.value if isinstance(self.status, StrEnum) else str(self.status)
        return {
            "step_id": self.step_id,
            "relay_request_id": self.relay_request_id,
            "step_name": step_name,
            "status": status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "adapter_kind": self.adapter_kind,
            "capability_required": self.capability_required,
            "capability_declared": self.capability_declared,
            "evidence_summary": self.evidence_summary,
            "failure_reason": self.failure_reason,
            "safe_to_continue": self.safe_to_continue,
        }


@dataclass(slots=True)
class DiscordLocalDispatchResult:
    relay_request_id: str
    recipient_alias: str
    route_mode: DiscordRouteMode = DiscordRouteMode.LOCAL_CLIENT_AUTOMATION
    adapter_kind: str = "unavailable"
    route_constraint: str = "unsupported"
    dispatch_supported: bool = False
    verification_supported: bool = False
    target_identity_verified: bool = False
    steps: list[DiscordLocalDispatchStep] = field(default_factory=list)
    final_send_gesture_performed: bool = False
    message_inserted: bool = False
    payload_copied_to_clipboard: bool = False
    payload_pasted: bool = False
    payload_typed: bool = False
    payload_visible_confirmed: bool = False
    clipboard_temporarily_used: bool = False
    verification_attempted: bool = False
    verification_evidence_present: bool = False
    verification_evidence_source: str | None = None
    verification_confidence: str | None = None
    result_state: DiscordDispatchState = DiscordDispatchState.DISPATCH_UNAVAILABLE
    sent_claimed: bool = False
    verified_claimed: bool = False
    user_message: str = ""
    failure_step: str | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "relay_request_id": self.relay_request_id,
            "recipient_alias": self.recipient_alias,
            "route_mode": self.route_mode.value,
            "adapter_kind": self.adapter_kind,
            "route_constraint": self.route_constraint,
            "dispatch_supported": self.dispatch_supported,
            "verification_supported": self.verification_supported,
            "target_identity_verified": self.target_identity_verified,
            "steps": [step.to_dict() for step in self.steps],
            "final_send_gesture_performed": self.final_send_gesture_performed,
            "message_inserted": self.message_inserted,
            "payload_copied_to_clipboard": self.payload_copied_to_clipboard,
            "payload_pasted": self.payload_pasted,
            "payload_typed": self.payload_typed,
            "payload_visible_confirmed": self.payload_visible_confirmed,
            "clipboard_temporarily_used": self.clipboard_temporarily_used,
            "verification_attempted": self.verification_attempted,
            "verification_evidence_present": self.verification_evidence_present,
            "verification_evidence_source": self.verification_evidence_source,
            "verification_confidence": self.verification_confidence,
            "result_state": self.result_state.value,
            "sent_claimed": self.sent_claimed,
            "verified_claimed": self.verified_claimed,
            "user_message": self.user_message,
            "failure_step": self.failure_step,
            "failure_reason": self.failure_reason,
        }


@dataclass(slots=True)
class DiscordDestination:
    alias: str
    label: str
    destination_kind: DiscordDestinationKind
    route_mode: DiscordRouteMode
    navigation_mode: str = "quick_switch"
    search_query: str | None = None
    thread_uri: str | None = None
    trusted: bool = True
    matched_alias: str | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "label": self.label,
            "destination_kind": self.destination_kind.value,
            "route_mode": self.route_mode.value,
            "navigation_mode": self.navigation_mode,
            "search_query": self.search_query,
            "thread_uri": self.thread_uri,
            "trusted": self.trusted,
            "matched_alias": self.matched_alias,
            "confidence": self.confidence,
        }

    def to_alias_target(self) -> dict[str, object]:
        return {
            "alias": self.alias,
            "label": self.label,
            "destination_kind": self.destination_kind.value,
            "route_mode": self.route_mode.value,
            "navigation_mode": self.navigation_mode,
            "search_query": self.search_query or "",
            "thread_uri": self.thread_uri or "",
            "trusted": self.trusted,
        }


@dataclass(slots=True)
class DiscordPayloadCandidate:
    kind: DiscordPayloadKind
    summary: str
    provenance: str
    confidence: float
    title: str | None = None
    url: str | None = None
    path: str | None = None
    text: str | None = None
    preview_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    screen_awareness_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "summary": self.summary,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "title": self.title,
            "url": self.url,
            "path": self.path,
            "text": self.text,
            "preview_text": self.preview_text,
            "metadata": _serialize(self.metadata),
            "warnings": list(self.warnings),
            "screen_awareness_used": self.screen_awareness_used,
        }


@dataclass(slots=True)
class DiscordPolicyDecision:
    outcome: DiscordPolicyOutcome
    warnings: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    requires_confirmation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "warnings": list(self.warnings),
            "blocks": list(self.blocks),
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass(slots=True)
class DiscordDispatchPreview:
    destination: DiscordDestination
    payload: DiscordPayloadCandidate
    route_mode: DiscordRouteMode
    note_text: str | None
    policy: DiscordPolicyDecision
    state: DiscordDispatchState = DiscordDispatchState.PREVIEW_READY
    screen_awareness_used: bool = False
    ambiguity_reason: str | None = None
    candidate_summaries: list[str] = field(default_factory=list)
    fingerprint: dict[str, Any] = field(default_factory=dict)
    created_at: float | None = None
    expires_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination": self.destination.to_dict(),
            "payload": self.payload.to_dict(),
            "route_mode": self.route_mode.value,
            "note_text": self.note_text,
            "policy": self.policy.to_dict(),
            "state": self.state.value,
            "screen_awareness_used": self.screen_awareness_used,
            "ambiguity_reason": self.ambiguity_reason,
            "candidate_summaries": list(self.candidate_summaries),
            "fingerprint": _serialize(self.fingerprint),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass(slots=True)
class DiscordDispatchAttempt:
    state: DiscordDispatchState
    route_mode: DiscordRouteMode
    route_basis: str
    verification_evidence: list[str] = field(default_factory=list)
    verification_strength: str = "none"
    failure_reason: str | None = None
    send_summary: str | None = None
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "route_mode": self.route_mode.value,
            "route_basis": self.route_basis,
            "verification_evidence": list(self.verification_evidence),
            "verification_strength": self.verification_strength,
            "failure_reason": self.failure_reason,
            "send_summary": self.send_summary,
            "debug": _serialize(self.debug),
        }


@dataclass(slots=True)
class DiscordRelayTrace:
    utterance: str
    stage: str
    destination_alias: str | None
    route_mode: str | None
    payload_kind: str | None
    state: DiscordDispatchState
    policy_outcome: DiscordPolicyOutcome | None = None
    screen_awareness_used: bool = False
    preview_fingerprint: str | None = None
    invalidation_reason: str | None = None
    duplicate_suppressed: bool = False
    wrong_thread_refusal: bool = False
    verification_strength: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "utterance": self.utterance,
            "stage": self.stage,
            "destination_alias": self.destination_alias,
            "route_mode": self.route_mode,
            "payload_kind": self.payload_kind,
            "state": self.state.value,
            "policy_outcome": self.policy_outcome.value if self.policy_outcome is not None else None,
            "screen_awareness_used": self.screen_awareness_used,
            "preview_fingerprint": self.preview_fingerprint,
            "invalidation_reason": self.invalidation_reason,
            "duplicate_suppressed": self.duplicate_suppressed,
            "wrong_thread_refusal": self.wrong_thread_refusal,
            "verification_strength": self.verification_strength,
        }


@dataclass(slots=True)
class DiscordRelayResponse:
    assistant_response: str
    response_contract: dict[str, Any]
    state: DiscordDispatchState
    preview: DiscordDispatchPreview | None = None
    attempt: DiscordDispatchAttempt | None = None
    trace: DiscordRelayTrace | None = None
    debug: dict[str, Any] = field(default_factory=dict)
    active_request_state: dict[str, object] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "assistant_response": self.assistant_response,
            "response_contract": _serialize(self.response_contract),
            "state": self.state.value,
            "preview": self.preview.to_dict() if self.preview is not None else None,
            "attempt": self.attempt.to_dict() if self.attempt is not None else None,
            "trace": self.trace.to_dict() if self.trace is not None else None,
            "debug": _serialize(self.debug),
            "active_request_state": _serialize(self.active_request_state),
        }
