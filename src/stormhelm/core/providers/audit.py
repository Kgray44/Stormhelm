from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


_AUDIT_LOCK = threading.Lock()


class ProviderCallBlockedError(RuntimeError):
    """Raised when command-eval mode blocks a provider/model call."""


def record_provider_call(
    *,
    provider_name: str,
    provider_type: str,
    source: str,
    purpose: str,
    model_name: str = "",
    openai_called: bool = False,
    llm_called: bool = False,
    embedding_called: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    allowed = _truthy(os.environ.get("STORMHELM_COMMAND_EVAL_PROVIDER_ALLOWED"))
    block_disallowed = _truthy(os.environ.get("STORMHELM_COMMAND_EVAL_BLOCK_PROVIDER_CALLS"))
    blocked = bool(block_disallowed and not allowed)
    record = {
        "timestamp": time.time(),
        "provider_name": str(provider_name or "").strip(),
        "provider_type": str(provider_type or "").strip(),
        "source": str(source or "").strip(),
        "purpose": str(purpose or "").strip(),
        "model_name": str(model_name or "").strip(),
        "openai_called": bool(openai_called),
        "llm_called": bool(llm_called),
        "embedding_called": bool(embedding_called),
        "provider_call_allowed": bool(allowed),
        "provider_call_violation": bool(not allowed),
        "blocked": blocked,
        "metadata": dict(metadata or {}),
    }
    _write_audit_record(record)
    if blocked:
        raise ProviderCallBlockedError("provider call blocked by command-eval provider audit")
    return record


def _write_audit_record(record: dict[str, Any]) -> None:
    path_value = str(os.environ.get("STORMHELM_COMMAND_EVAL_PROVIDER_AUDIT_PATH") or "").strip()
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, sort_keys=True, default=str)
    with _AUDIT_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "allowed"}
