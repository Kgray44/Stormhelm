from __future__ import annotations

from typing import Any

from stormhelm.core.camera_awareness.models import ROUTE_FAMILY_CAMERA_AWARENESS
from stormhelm.core.camera_awareness.models import serialize_camera_value
from stormhelm.core.events import (
    EventBuffer,
    EventFamily,
    EventRetentionClass,
    EventSeverity,
    EventVisibilityScope,
)


_RAW_IMAGE_PAYLOAD_KEYS = frozenset(
    {
        "raw_image",
        "image_bytes",
        "image_base64",
        "image_url",
        "data_url",
        "provider_request",
        "provider_request_body",
        "provider_response",
        "provider_raw_response",
        "raw_provider_response",
        "request_body",
        "unbounded_provider_response",
        "encoded_image",
    }
)
_RAW_IMAGE_TEXT_MARKERS = ("data:image", "base64,")
_REDACTED_IMAGE_PAYLOAD = "[redacted-camera-image-payload]"


class CameraTelemetryEmitter:
    def __init__(self, events: EventBuffer | None = None, *, enabled: bool = True) -> None:
        self.events = events
        self.enabled = enabled

    def emit(
        self,
        event_type: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> None:
        if not self.enabled or self.events is None:
            return
        safe_payload = self._safe_payload(payload or {})
        self.events.publish(
            event_family=EventFamily.CAMERA_AWARENESS,
            event_type=event_type,
            subsystem=ROUTE_FAMILY_CAMERA_AWARENESS,
            severity=EventSeverity.DEBUG,
            visibility_scope=EventVisibilityScope.DECK_CONTEXT,
            retention_class=EventRetentionClass.EPHEMERAL,
            message=message,
            payload=safe_payload,
            session_id=session_id,
        )

    def _safe_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        safe = {
            "route_family": ROUTE_FAMILY_CAMERA_AWARENESS,
            "raw_image_included": False,
            "raw_image_persisted": False,
            "cloud_upload_performed": False,
            "real_camera_used": False,
        }
        for key, value in payload.items():
            if str(key).lower() in _RAW_IMAGE_PAYLOAD_KEYS:
                continue
            safe[str(key)] = self._safe_value(value)
        safe["raw_image_included"] = False
        safe["cloud_upload_performed"] = bool(safe.get("cloud_upload_performed") is True)
        safe["real_camera_used"] = bool(safe.get("real_camera_used") is True)
        return safe

    def _safe_value(self, value: Any) -> Any:
        serialized = serialize_camera_value(value)
        if isinstance(serialized, dict):
            return {
                str(key): self._safe_value(item)
                for key, item in serialized.items()
                if str(key).lower() not in _RAW_IMAGE_PAYLOAD_KEYS
            }
        if isinstance(serialized, list):
            return [self._safe_value(item) for item in serialized]
        if isinstance(serialized, str):
            return _redact_image_payload_text(serialized)
        return serialized


def _redact_image_payload_text(value: str) -> str:
    text = str(value)
    lowered = text.lower()
    if any(marker in lowered for marker in _RAW_IMAGE_TEXT_MARKERS):
        return _REDACTED_IMAGE_PAYLOAD
    return text
