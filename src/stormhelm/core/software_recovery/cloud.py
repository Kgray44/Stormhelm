from __future__ import annotations

import re
from typing import Any


_WINDOWS_USER_PATH_PATTERN = re.compile(r"[A-Za-z]:\\Users\\[^\s\"']+(?:\\[^\s\"']+)*")
_TOKEN_PATTERN = re.compile(r"\b[a-z]{2}-[A-Za-z0-9_-]+\b", re.IGNORECASE)


def redact_diagnostic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): redact_diagnostic_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_diagnostic_value(item) for item in value]
    if not isinstance(value, str):
        return value
    redacted = _WINDOWS_USER_PATH_PATTERN.sub("<redacted_path>", value)
    redacted = _TOKEN_PATTERN.sub("<redacted_token>", redacted)
    return redacted
