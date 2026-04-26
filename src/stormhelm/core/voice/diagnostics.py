from __future__ import annotations

from typing import Any


def voice_status_snapshot(service: Any) -> dict[str, Any]:
    return service.status_snapshot()
