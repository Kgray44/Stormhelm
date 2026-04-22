from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from time import sleep

from stormhelm.config.models import AppConfig
from stormhelm.shared.time import utc_now_iso

_RUNTIME_STATE_UNLINK_RETRIES = 5
_RUNTIME_STATE_UNLINK_DELAY_SECONDS = 0.05
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeBootstrapResult:
    first_run: bool
    first_run_record: dict[str, object]
    core_state_record: dict[str, object]


def initialize_runtime_state(config: AppConfig, *, install_mode: str | None = None) -> RuntimeBootstrapResult:
    first_run = not config.runtime.first_run_marker_path.exists()
    first_run_record = _load_json(config.runtime.first_run_marker_path)
    if first_run:
        first_run_record = {
            "created_at": utc_now_iso(),
            "version": config.version,
            "release_channel": config.release_channel,
            "mode": config.runtime.mode,
            "install_mode": install_mode or "",
        }
        _write_json(config.runtime.first_run_marker_path, first_run_record)

    core_state_record = {
        "pid": os.getpid(),
        "started_at": utc_now_iso(),
        "version": config.version,
        "release_channel": config.release_channel,
        "protocol_version": config.protocol_version,
        "mode": config.runtime.mode,
        "install_mode": install_mode or "",
        "api_base_url": config.api_base_url,
        "install_root": str(config.runtime.install_root),
        "resource_root": str(config.runtime.resource_root),
        "data_dir": str(config.storage.data_dir),
    }
    _write_json(config.runtime.core_state_path, core_state_record)
    return RuntimeBootstrapResult(
        first_run=first_run,
        first_run_record=first_run_record,
        core_state_record=core_state_record,
    )


def clear_runtime_state(config: AppConfig) -> None:
    for attempt in range(_RUNTIME_STATE_UNLINK_RETRIES + 1):
        try:
            config.runtime.core_state_path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt >= _RUNTIME_STATE_UNLINK_RETRIES:
                logger.warning(
                    "Leaving stale runtime state file in place because it remained locked during shutdown: %s",
                    config.runtime.core_state_path,
                )
                return
            sleep(_RUNTIME_STATE_UNLINK_DELAY_SECONDS * (attempt + 1))


def _load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
