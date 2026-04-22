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
    state: DiscordDispatchState = DiscordDispatchState.READY
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
