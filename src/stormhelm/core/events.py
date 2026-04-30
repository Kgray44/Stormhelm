from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum
from threading import Condition
from time import monotonic
from typing import Any

from stormhelm.shared.time import utc_now_iso


class EventFamily(str, Enum):
    RUNTIME = "runtime"
    JOB = "job"
    TASK = "task"
    TOOL = "tool"
    APPROVAL = "approval"
    VERIFICATION = "verification"
    WORKSPACE = "workspace"
    SYSTEM_SIGNAL = "system_signal"
    NETWORK = "network"
    SCREEN_AWARENESS = "screen_awareness"
    DISCORD_RELAY = "discord_relay"
    WEB_RETRIEVAL = "web_retrieval"
    VOICE = "voice"
    LIFECYCLE = "lifecycle"


class EventSeverity(str, Enum):
    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventVisibilityScope(str, Enum):
    INTERNAL_ONLY = "internal_only"
    WATCH_SURFACE = "watch_surface"
    SYSTEMS_SURFACE = "systems_surface"
    GHOST_HINT = "ghost_hint"
    DECK_CONTEXT = "deck_context"
    OPERATOR_BLOCKING = "operator_blocking"


class EventRetentionClass(str, Enum):
    EPHEMERAL = "ephemeral"
    BOUNDED_RECENT = "bounded_recent"
    OPERATOR_RELEVANT = "operator_relevant"
    BOOTSTRAP_ASSIST = "bootstrap_assist"


@dataclass(slots=True)
class EventProvenance:
    channel: str
    kind: str
    detail: str = ""
    inferred: bool = False
    degraded: bool = False
    ambiguous: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "kind": self.kind,
            "detail": self.detail,
            "inferred": self.inferred,
            "degraded": self.degraded,
            "ambiguous": self.ambiguous,
            "evidence": dict(self.evidence),
        }


@dataclass(slots=True)
class EventRecord:
    event_id: int
    cursor: int
    event_family: str
    event_type: str
    timestamp: str
    subsystem: str
    severity: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    subject: str | None = None
    provenance: EventProvenance = field(
        default_factory=lambda: EventProvenance(channel="core", kind="direct_system_fact")
    )
    visibility_scope: str = EventVisibilityScope.INTERNAL_ONLY.value
    retention_class: str = EventRetentionClass.BOUNDED_RECENT.value

    @property
    def created_at(self) -> str:
        return self.timestamp

    @property
    def level(self) -> str:
        return self.severity.upper()

    @property
    def source(self) -> str:
        return self.subsystem

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "cursor": self.cursor,
            "event_family": self.event_family,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "created_at": self.timestamp,
            "session_id": self.session_id,
            "subsystem": self.subsystem,
            "source": self.subsystem,
            "severity": self.severity,
            "level": self.level,
            "subject": self.subject,
            "message": self.message,
            "payload": dict(self.payload),
            "provenance": self.provenance.to_dict(),
            "visibility_scope": self.visibility_scope,
            "retention_class": self.retention_class,
        }


@dataclass(slots=True)
class ReplayWindow:
    requested_cursor: int
    earliest_cursor: int | None
    latest_cursor: int
    gap_detected: bool
    events: list[EventRecord] = field(default_factory=list)
    returned_count: int = 0
    available_count: int = 0
    truncated: bool = False

    @property
    def next_cursor(self) -> int:
        if not self.events:
            return self.requested_cursor
        return self.events[-1].cursor

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_cursor": self.requested_cursor,
            "earliest_cursor": self.earliest_cursor,
            "latest_cursor": self.latest_cursor,
            "gap_detected": self.gap_detected,
            "returned_count": self.returned_count,
            "available_count": self.available_count,
            "truncated": self.truncated,
            "next_cursor": self.next_cursor,
            "events": [event.to_dict() for event in self.events],
        }


class EventBuffer:
    def __init__(self, capacity: int = 500) -> None:
        self._capacity = max(1, int(capacity))
        self._events: deque[EventRecord] = deque(maxlen=self._capacity)
        self._condition = Condition()
        self._next_cursor = 1
        self._published_total = 0
        self._expired_total = 0
        self._replay_requests = 0
        self._replay_gap_total = 0
        self._connections_current = 0
        self._connections_total = 0
        self._family_totals: Counter[str] = Counter()
        self._visibility_totals: Counter[str] = Counter()
        self._severity_totals: Counter[str] = Counter()

    def publish(
        self,
        *,
        level: str | None = None,
        source: str | None = None,
        message: str,
        payload: dict[str, Any] | None = None,
        event_family: str | EventFamily | None = None,
        event_type: str | None = None,
        timestamp: str | None = None,
        session_id: str | None = None,
        subsystem: str | None = None,
        severity: str | EventSeverity | None = None,
        subject: str | None = None,
        provenance: EventProvenance | dict[str, Any] | None = None,
        visibility_scope: str | EventVisibilityScope | None = None,
        retention_class: str | EventRetentionClass | None = None,
    ) -> EventRecord:
        normalized_payload = dict(payload or {})
        resolved_subsystem = str(subsystem or source or "core").strip().lower() or "core"
        resolved_family = self._resolve_event_family(
            event_family=event_family,
            event_type=event_type,
            subsystem=resolved_subsystem,
            payload=normalized_payload,
            message=message,
        )
        resolved_severity = self._coerce_enum(
            severity or level or EventSeverity.INFO.value,
            EventSeverity,
            fallback=EventSeverity.INFO,
        ).value
        resolved_type = self._resolve_event_type(
            event_type=event_type,
            event_family=resolved_family,
            subsystem=resolved_subsystem,
            payload=normalized_payload,
            message=message,
        )
        resolved_visibility = self._coerce_enum(
            visibility_scope or self._default_visibility(
                event_family=resolved_family,
                event_type=resolved_type,
                subsystem=resolved_subsystem,
                severity=resolved_severity,
            ),
            EventVisibilityScope,
            fallback=EventVisibilityScope.INTERNAL_ONLY,
        ).value
        resolved_retention = self._coerce_enum(
            retention_class or self._default_retention(resolved_visibility, resolved_severity),
            EventRetentionClass,
            fallback=EventRetentionClass.BOUNDED_RECENT,
        ).value
        resolved_provenance = self._normalize_provenance(
            provenance=provenance,
            subsystem=resolved_subsystem,
            event_family=resolved_family,
            event_type=resolved_type,
        )

        with self._condition:
            if len(self._events) >= self._capacity:
                self._expired_total += 1

            cursor = self._next_cursor
            event = EventRecord(
                event_id=cursor,
                cursor=cursor,
                event_family=resolved_family,
                event_type=resolved_type,
                timestamp=timestamp or utc_now_iso(),
                session_id=str(session_id).strip() or None if session_id is not None else None,
                subsystem=resolved_subsystem,
                severity=resolved_severity,
                subject=str(subject).strip() or None if subject is not None else None,
                message=str(message).strip() or "Stormhelm event",
                payload=normalized_payload,
                provenance=resolved_provenance,
                visibility_scope=resolved_visibility,
                retention_class=resolved_retention,
            )
            self._next_cursor += 1
            self._published_total += 1
            self._family_totals[resolved_family] += 1
            self._visibility_totals[resolved_visibility] += 1
            self._severity_totals[resolved_severity] += 1
            self._events.append(event)
            self._condition.notify_all()
            return event

    def recent(
        self,
        *,
        since_id: int = 0,
        limit: int = 100,
        cursor: int | None = None,
        session_id: str | None = None,
        visibility_scope: str | list[str] | None = None,
        families: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        effective_cursor = cursor if cursor is not None else since_id
        if int(effective_cursor or 0) <= 0:
            visibility_filters = self._normalize_string_filters(visibility_scope)
            family_filters = self._normalize_string_filters(families)
            with self._condition:
                matching_events = [
                    event.to_dict()
                    for event in self._events
                    if self._matches_filters(
                        event,
                        session_id=session_id,
                        visibility_filters=visibility_filters,
                        family_filters=family_filters,
                    )
                ]
            return matching_events[-max(0, int(limit)) :]
        replay = self.replay(
            cursor=effective_cursor,
            limit=limit,
            session_id=session_id,
            visibility_scope=visibility_scope,
            families=families,
        )
        return [event.to_dict() for event in replay.events]

    def replay(
        self,
        *,
        cursor: int = 0,
        limit: int = 100,
        session_id: str | None = None,
        visibility_scope: str | list[str] | None = None,
        families: list[str] | None = None,
    ) -> ReplayWindow:
        requested_cursor = max(0, int(cursor or 0))
        visibility_filters = self._normalize_string_filters(visibility_scope)
        family_filters = self._normalize_string_filters(families)

        with self._condition:
            self._replay_requests += 1
            earliest_cursor = self._events[0].cursor if self._events else None
            latest_cursor = self._events[-1].cursor if self._events else requested_cursor
            gap_detected = earliest_cursor is not None and requested_cursor < (earliest_cursor - 1)
            if gap_detected:
                self._replay_gap_total += 1
            matching_events = [
                event
                for event in self._events
                if event.cursor > requested_cursor
                and self._matches_filters(
                    event,
                    session_id=session_id,
                    visibility_filters=visibility_filters,
                    family_filters=family_filters,
                )
            ]

        available_count = len(matching_events)
        bounded_limit = max(0, int(limit))
        truncated = bounded_limit > 0 and len(matching_events) > bounded_limit
        if bounded_limit > 0:
            matching_events = matching_events[:bounded_limit]

        return ReplayWindow(
            requested_cursor=requested_cursor,
            earliest_cursor=earliest_cursor,
            latest_cursor=latest_cursor,
            gap_detected=gap_detected,
            events=list(matching_events),
            returned_count=len(matching_events),
            available_count=available_count,
            truncated=truncated,
        )

    def wait_for_next_event(
        self,
        *,
        cursor: int,
        timeout: float = 15.0,
        session_id: str | None = None,
        visibility_scope: str | list[str] | None = None,
        families: list[str] | None = None,
    ) -> EventRecord | None:
        visibility_filters = self._normalize_string_filters(visibility_scope)
        family_filters = self._normalize_string_filters(families)
        target_cursor = max(0, int(cursor or 0))
        deadline = monotonic() + max(0.0, float(timeout))

        with self._condition:
            while True:
                for event in self._events:
                    if event.cursor <= target_cursor:
                        continue
                    if not self._matches_filters(
                        event,
                        session_id=session_id,
                        visibility_filters=visibility_filters,
                        family_filters=family_filters,
                    ):
                        continue
                    return event

                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)

    def register_stream(self) -> dict[str, int]:
        with self._condition:
            self._connections_current += 1
            self._connections_total += 1
            return {
                "connections_current": self._connections_current,
                "connections_total": self._connections_total,
            }

    def unregister_stream(self) -> dict[str, int]:
        with self._condition:
            if self._connections_current > 0:
                self._connections_current -= 1
            return {
                "connections_current": self._connections_current,
                "connections_total": self._connections_total,
            }

    def state_snapshot(self) -> dict[str, Any]:
        with self._condition:
            earliest_cursor = self._events[0].cursor if self._events else None
            latest_cursor = self._events[-1].cursor if self._events else 0
            return {
                "capacity": self._capacity,
                "buffered": len(self._events),
                "published_total": self._published_total,
                "expired_total": self._expired_total,
                "earliest_cursor": earliest_cursor,
                "latest_cursor": latest_cursor,
                "replay_requests": self._replay_requests,
                "replay_gap_total": self._replay_gap_total,
                "connections_current": self._connections_current,
                "connections_total": self._connections_total,
                "family_totals": dict(self._family_totals),
                "visibility_totals": dict(self._visibility_totals),
                "severity_totals": dict(self._severity_totals),
            }

    def _matches_filters(
        self,
        event: EventRecord,
        *,
        session_id: str | None,
        visibility_filters: set[str] | None,
        family_filters: set[str] | None,
    ) -> bool:
        if session_id and event.session_id not in {None, "", session_id}:
            return False
        if visibility_filters and event.visibility_scope not in visibility_filters:
            return False
        if family_filters and event.event_family not in family_filters:
            return False
        return True

    def _normalize_string_filters(
        self,
        values: str | list[str] | None,
    ) -> set[str] | None:
        if values is None:
            return None
        if isinstance(values, str):
            normalized = str(values).strip().lower()
            return {normalized} if normalized else None
        normalized_values = {
            str(value).strip().lower()
            for value in values
            if str(value).strip()
        }
        return normalized_values or None

    def _normalize_provenance(
        self,
        *,
        provenance: EventProvenance | dict[str, Any] | None,
        subsystem: str,
        event_family: str,
        event_type: str,
    ) -> EventProvenance:
        if isinstance(provenance, EventProvenance):
            return provenance
        if isinstance(provenance, dict):
            return EventProvenance(
                channel=str(provenance.get("channel") or subsystem).strip() or subsystem,
                kind=str(provenance.get("kind") or self._default_provenance_kind(event_family, subsystem)).strip()
                or self._default_provenance_kind(event_family, subsystem),
                detail=str(provenance.get("detail") or "").strip(),
                inferred=bool(provenance.get("inferred", False)),
                degraded=bool(provenance.get("degraded", False)),
                ambiguous=bool(provenance.get("ambiguous", False)),
                evidence=dict(provenance.get("evidence") or {}) if isinstance(provenance.get("evidence"), dict) else {},
            )
        return EventProvenance(
            channel=subsystem,
            kind=self._default_provenance_kind(event_family, subsystem),
            detail=f"{subsystem} published {event_type}.",
        )

    def _default_provenance_kind(self, event_family: str, subsystem: str) -> str:
        if event_family in {
            EventFamily.LIFECYCLE.value,
            EventFamily.JOB.value,
            EventFamily.TOOL.value,
            EventFamily.APPROVAL.value,
        }:
            return "direct_system_fact"
        if subsystem in {"assistant", "planner"}:
            return "operator_summary"
        if subsystem in {"judgment", "screen_awareness", "discord_relay", "web_retrieval", "network", "voice"}:
            return "subsystem_interpretation"
        return "heuristic_status"

    def _default_visibility(
        self,
        *,
        event_family: str,
        event_type: str,
        subsystem: str,
        severity: str,
    ) -> str:
        if severity in {EventSeverity.ERROR.value, EventSeverity.CRITICAL.value}:
            return EventVisibilityScope.OPERATOR_BLOCKING.value
        if subsystem in {"planner", "judgment"}:
            return EventVisibilityScope.INTERNAL_ONLY.value
        if event_family == EventFamily.JOB.value:
            return EventVisibilityScope.WATCH_SURFACE.value
        if event_family in {
            EventFamily.NETWORK.value,
            EventFamily.SYSTEM_SIGNAL.value,
            EventFamily.LIFECYCLE.value,
        }:
            return EventVisibilityScope.SYSTEMS_SURFACE.value
        if event_family == EventFamily.APPROVAL.value:
            return EventVisibilityScope.DECK_CONTEXT.value
        if event_type.endswith(".failed") or event_type.endswith(".warning"):
            return EventVisibilityScope.GHOST_HINT.value
        if event_family in {
            EventFamily.VERIFICATION.value,
            EventFamily.SCREEN_AWARENESS.value,
            EventFamily.DISCORD_RELAY.value,
            EventFamily.WEB_RETRIEVAL.value,
            EventFamily.VOICE.value,
            EventFamily.WORKSPACE.value,
        }:
            return EventVisibilityScope.DECK_CONTEXT.value
        return EventVisibilityScope.INTERNAL_ONLY.value if subsystem == "assistant" else EventVisibilityScope.DECK_CONTEXT.value

    def _default_retention(self, visibility_scope: str, severity: str) -> str:
        if visibility_scope in {
            EventVisibilityScope.GHOST_HINT.value,
            EventVisibilityScope.OPERATOR_BLOCKING.value,
            EventVisibilityScope.WATCH_SURFACE.value,
            EventVisibilityScope.SYSTEMS_SURFACE.value,
        }:
            return EventRetentionClass.OPERATOR_RELEVANT.value
        if severity in {EventSeverity.TRACE.value, EventSeverity.DEBUG.value}:
            return EventRetentionClass.EPHEMERAL.value
        return EventRetentionClass.BOUNDED_RECENT.value

    def _resolve_event_family(
        self,
        *,
        event_family: str | EventFamily | None,
        event_type: str | None,
        subsystem: str,
        payload: dict[str, Any],
        message: str,
    ) -> str:
        if event_family is not None:
            return self._coerce_enum(event_family, EventFamily, fallback=EventFamily.RUNTIME).value

        event_type_text = str(event_type or "").strip().lower()
        if event_type_text:
            prefix = event_type_text.split(".", 1)[0]
            try:
                return EventFamily(prefix).value
            except ValueError:
                pass

        family_map = {
            "core": EventFamily.LIFECYCLE,
            "job_manager": EventFamily.JOB,
            "tasks": EventFamily.TASK,
            "tool_executor": EventFamily.TOOL,
            "trust": EventFamily.APPROVAL,
            "assistant": EventFamily.RUNTIME,
            "planner": EventFamily.RUNTIME,
            "judgment": EventFamily.RUNTIME,
            "network": EventFamily.NETWORK,
            "calculations": EventFamily.VERIFICATION,
            "screen_awareness": EventFamily.SCREEN_AWARENESS,
            "discord_relay": EventFamily.DISCORD_RELAY,
            "web_retrieval": EventFamily.WEB_RETRIEVAL,
            "voice": EventFamily.VOICE,
            "workspace": EventFamily.WORKSPACE,
            "api": EventFamily.WORKSPACE,
        }
        if subsystem in family_map:
            return family_map[subsystem].value

        lowered_message = str(message or "").strip().lower()
        if "network" in lowered_message:
            return EventFamily.NETWORK.value
        if "verification" in lowered_message:
            return EventFamily.VERIFICATION.value
        if payload.get("job_id"):
            return EventFamily.JOB.value
        return EventFamily.RUNTIME.value

    def _resolve_event_type(
        self,
        *,
        event_type: str | None,
        event_family: str,
        subsystem: str,
        payload: dict[str, Any],
        message: str,
    ) -> str:
        if str(event_type or "").strip():
            return str(event_type).strip().lower()

        lowered_message = str(message or "").strip().lower()
        if event_family == EventFamily.LIFECYCLE.value:
            if subsystem == "core" and "started" in lowered_message:
                return "lifecycle.core.started"
            if subsystem == "core" and "shutting down" in lowered_message:
                return "lifecycle.core.stopping"
            if subsystem == "job_manager" and "started" in lowered_message:
                return "lifecycle.job_manager.started"
            return f"lifecycle.{subsystem}.updated"

        if event_family == EventFamily.JOB.value:
            status = str(payload.get("status") or "").strip().lower()
            if status in {"completed", "failed", "timed_out", "cancelled"}:
                return f"job.{status}"
            if "queued" in lowered_message:
                return "job.queued"
            if "started" in lowered_message:
                return "job.started"
            return "job.updated"

        if event_family == EventFamily.TOOL.value:
            return "tool.execution_started" if "executing" in lowered_message else "tool.updated"

        if event_family == EventFamily.APPROVAL.value:
            state = str(payload.get("state") or payload.get("approval_state") or "").strip().lower()
            if state:
                return f"approval.{state}"
            return "approval.updated"

        if event_family == EventFamily.NETWORK.value:
            kind = str(payload.get("kind") or "").strip().lower()
            return f"network.{kind}" if kind else "network.signal"

        if event_family == EventFamily.SCREEN_AWARENESS.value:
            disposition = str(payload.get("disposition") or "").strip().lower()
            return f"screen_awareness.{disposition}" if disposition else "screen_awareness.routed"

        if event_family == EventFamily.DISCORD_RELAY.value:
            state = str(payload.get("state") or "").strip().lower()
            if state:
                return f"discord_relay.{state}"
            if payload.get("preview"):
                return "discord_relay.preview_ready"
            return "discord_relay.updated"

        if event_family == EventFamily.WEB_RETRIEVAL.value:
            state = str(payload.get("status") or payload.get("state") or "").strip().lower()
            if state:
                return f"web_retrieval.{state}"
            return "web_retrieval.updated"

        if event_family == EventFamily.VOICE.value:
            state = str(payload.get("state") or "").strip().lower()
            if state:
                return f"voice.{state}"
            return "voice.updated"

        if event_family == EventFamily.VERIFICATION.value:
            trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
            failure = payload.get("failure") if isinstance(payload.get("failure"), dict) else {}
            if trace.get("parse_success") is True and trace.get("result"):
                return "verification.calculation_succeeded"
            if failure:
                return "verification.calculation_failed"
            return "verification.calculation_detected"

        if event_family == EventFamily.WORKSPACE.value:
            if "saved note" in lowered_message:
                return "workspace.note_saved"
            return "workspace.updated"

        if subsystem == "assistant" and "handled message" in lowered_message:
            return "runtime.assistant_response_ready"
        if subsystem == "planner":
            return "runtime.planner_obedience_evaluated"
        if subsystem == "judgment":
            return "runtime.judgment_evaluated"
        return "runtime.updated"

    def _coerce_enum[TEnum: Enum](
        self,
        value: object,
        enum_type: type[TEnum],
        *,
        fallback: TEnum,
    ) -> TEnum:
        if isinstance(value, enum_type):
            return value
        normalized = str(value or "").strip().lower()
        try:
            return enum_type(normalized)
        except ValueError:
            return fallback
