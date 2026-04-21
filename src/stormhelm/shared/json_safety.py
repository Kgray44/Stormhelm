from __future__ import annotations

import json
import logging
from typing import Any


LOGGER = logging.getLogger(__name__)


def decode_json_value(raw: object, *, context: str, default: Any = None) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list, int, float, bool)) and not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        LOGGER.warning("Failed to decode %s; using fallback. %s", context, exc)
        return default


def decode_json_dict(raw: object, *, context: str) -> dict[str, Any]:
    value = decode_json_value(raw, context=context, default={})
    if isinstance(value, dict):
        return dict(value)
    if value not in ({}, None):
        LOGGER.warning("Expected %s to decode to an object; received %s. Using empty object.", context, type(value).__name__)
    return {}


def decode_json_list(raw: object, *, context: str) -> list[Any]:
    value = decode_json_value(raw, context=context, default=[])
    if isinstance(value, list):
        return list(value)
    if value not in ([], None):
        LOGGER.warning("Expected %s to decode to a list; received %s. Using empty list.", context, type(value).__name__)
    return []
