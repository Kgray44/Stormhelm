from __future__ import annotations

import os


APP_NAME = "Stormhelm"
API_PROTOCOL_VERSION = 1
DEFAULT_RELEASE_CHANNEL = "dev"
__version__ = "0.1.1"


def current_release_channel(env: dict[str, str] | None = None) -> str:
    values = env or os.environ
    return values.get("STORMHELM_RELEASE_CHANNEL", DEFAULT_RELEASE_CHANNEL).strip() or DEFAULT_RELEASE_CHANNEL


def format_version_label(version: str, channel: str) -> str:
    normalized = channel.strip().lower()
    if normalized in {"", "release", "stable"}:
        return version
    return f"{version} ({channel})"
