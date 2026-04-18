from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from stormhelm.shared.time import utc_now_iso


@dataclass(slots=True)
class EventRecord:
    event_id: int
    timestamp: str
    level: str
    source: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "payload": self.payload,
        }


class EventBuffer:
    def __init__(self, capacity: int = 500) -> None:
        self._events: deque[EventRecord] = deque(maxlen=capacity)
        self._lock = Lock()
        self._next_id = 1

    def publish(
        self,
        *,
        level: str,
        source: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> EventRecord:
        with self._lock:
            event = EventRecord(
                event_id=self._next_id,
                timestamp=utc_now_iso(),
                level=level.upper(),
                source=source,
                message=message,
                payload=payload or {},
            )
            self._next_id += 1
            self._events.append(event)
            return event

    def recent(self, *, since_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            items = [event.to_dict() for event in self._events if event.event_id > since_id]
        return items[-limit:]

