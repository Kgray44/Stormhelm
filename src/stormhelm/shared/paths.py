from __future__ import annotations

import os
from pathlib import Path

from stormhelm.shared.runtime import find_project_root

def project_root() -> Path:
    return find_project_root()


def default_data_dir(app_name: str) -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / app_name
    return Path.home() / "AppData" / "Local" / app_name


def ensure_runtime_directories(paths: list[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
