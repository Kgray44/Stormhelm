from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from time import monotonic
from typing import Any


RenderConfirmed = bool | str
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]+"),
    re.compile(r"bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]?\s*[A-Za-z0-9._\-\s]+", re.IGNORECASE),
)
_UNSAFE_TERMS = ("raw_audio", "generated_audio", "screenshot", "discord payload")
_MAX_RENDER_TEXT = 120


def ui_monotonic_ms() -> float:
    return round(monotonic() * 1000.0, 3)


def ui_wall_time() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class UiLatencyMark:
    request_id: str | None
    event_id: str | None
    event_type: str | None
    route_family: str | None
    subsystem: str | None
    surface: str
    mark_name: str
    monotonic_ms: float
    wall_time: str
    source: str
    sequence_number: int | None = None
    stale: bool = False
    render_confirmed: RenderConfirmed = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "route_family": self.route_family,
            "subsystem": self.subsystem,
            "surface": self.surface,
            "mark_name": self.mark_name,
            "monotonic_ms": self.monotonic_ms,
            "wall_time": self.wall_time,
            "source": self.source,
            "sequence_number": self.sequence_number,
            "stale": self.stale,
            "render_confirmed": self.render_confirmed,
        }


def sanitized_render_value(value: Any) -> str:
    text = "" if value is None else str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    for term in _UNSAFE_TERMS:
        text = re.sub(re.escape(term), "[redacted]", text, flags=re.IGNORECASE)
    text = " ".join(text.split())
    if len(text) > _MAX_RENDER_TEXT:
        text = text[: _MAX_RENDER_TEXT - 1].rstrip() + "..."
    return text


@dataclass(slots=True)
class UiRenderConfirmation:
    confirmation_id: str
    surface: str
    model_revision: int
    visible_state_key: str
    rendered_at_monotonic_ms: float
    rendered_at_wall_time: str
    render_confirmed: bool
    render_confirmation_status: str
    confirmation_source: str
    request_id: str | None = None
    event_id: str | None = None
    event_type: str | None = None
    qml_component_id: str | None = None
    visible_state_value: Any = None
    stale: bool = False
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "confirmation_id": sanitized_render_value(self.confirmation_id),
            "request_id": sanitized_render_value(self.request_id) or None,
            "event_id": sanitized_render_value(self.event_id) or None,
            "event_type": sanitized_render_value(self.event_type) or None,
            "surface": sanitized_render_value(self.surface),
            "model_revision": int(self.model_revision),
            "qml_component_id": sanitized_render_value(self.qml_component_id) or None,
            "visible_state_key": sanitized_render_value(self.visible_state_key),
            "visible_state_value": sanitized_render_value(self.visible_state_value) or None,
            "rendered_at_monotonic_ms": self.rendered_at_monotonic_ms,
            "rendered_at_wall_time": self.rendered_at_wall_time,
            "render_confirmed": bool(self.render_confirmed),
            "render_confirmation_status": sanitized_render_value(self.render_confirmation_status),
            "confirmation_source": sanitized_render_value(self.confirmation_source),
            "stale": bool(self.stale),
            "reason": sanitized_render_value(self.reason) or None,
        }


@dataclass(slots=True)
class UiEventRenderLatencySummary:
    request_id: str | None
    event_id: str | None
    event_type: str | None
    surface: str = "bridge"
    event_received_at_monotonic_ms: float | None = None
    event_parsed_at_monotonic_ms: float | None = None
    bridge_update_at_monotonic_ms: float | None = None
    model_notify_at_monotonic_ms: float | None = None
    render_confirmed_at_monotonic_ms: float | None = None
    received_to_bridge_update_ms: float | None = None
    bridge_update_to_model_notify_ms: float | None = None
    model_notify_to_render_confirmed_ms: float | None = None
    received_to_render_confirmed_ms: float | None = None
    model_notify_to_render_visible_ms: float | None = None
    received_to_render_visible_ms: float | None = None
    render_confirmation_status: str = "unknown"
    render_confirmation_source: str = ""
    used_polling_fallback: bool = False
    used_snapshot_reconciliation: bool = False
    gap_recovered: bool = False
    reconnect_gap_recovered: bool = False
    duplicate_ignored_count: int = 0
    out_of_order_ignored_count: int = 0
    render_confirmed: RenderConfirmed = "unknown"
    model_revision: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "surface": self.surface,
            "model_revision": self.model_revision,
            "event_received_at_monotonic_ms": self.event_received_at_monotonic_ms,
            "event_parsed_at_monotonic_ms": self.event_parsed_at_monotonic_ms,
            "bridge_update_at_monotonic_ms": self.bridge_update_at_monotonic_ms,
            "model_notify_at_monotonic_ms": self.model_notify_at_monotonic_ms,
            "render_confirmed_at_monotonic_ms": self.render_confirmed_at_monotonic_ms,
            "received_to_bridge_update_ms": self.received_to_bridge_update_ms,
            "bridge_update_to_model_notify_ms": self.bridge_update_to_model_notify_ms,
            "model_notify_to_render_confirmed_ms": self.model_notify_to_render_confirmed_ms,
            "received_to_render_confirmed_ms": self.received_to_render_confirmed_ms,
            "model_notify_to_render_visible_ms": self.model_notify_to_render_visible_ms,
            "received_to_render_visible_ms": self.received_to_render_visible_ms,
            "render_confirmation_status": self.render_confirmation_status,
            "render_confirmation_source": self.render_confirmation_source,
            "used_polling_fallback": self.used_polling_fallback,
            "used_snapshot_reconciliation": self.used_snapshot_reconciliation,
            "gap_recovered": self.gap_recovered,
            "reconnect_gap_recovered": self.reconnect_gap_recovered,
            "duplicate_ignored_count": self.duplicate_ignored_count,
            "out_of_order_ignored_count": self.out_of_order_ignored_count,
            "render_confirmed": self.render_confirmed,
        }
