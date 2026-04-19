from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_MARKERS = ("pyproject.toml", "config/default.toml")


@dataclass(slots=True)
class RuntimeDiscovery:
    is_frozen: bool
    mode: str
    source_root: Path | None
    install_root: Path
    resource_root: Path


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if all((candidate / marker).exists() for marker in PROJECT_MARKERS):
            return candidate

    raise RuntimeError(f"Unable to discover the Stormhelm project root from '{current}'.")


def discover_runtime() -> RuntimeDiscovery:
    is_frozen = bool(getattr(sys, "frozen", False))
    if is_frozen:
        install_root = Path(sys.executable).resolve().parent
        resource_root = Path(getattr(sys, "_MEIPASS", install_root)).resolve()
        return RuntimeDiscovery(
            is_frozen=True,
            mode="packaged",
            source_root=None,
            install_root=install_root,
            resource_root=resource_root,
        )

    source_root = find_project_root()
    return RuntimeDiscovery(
        is_frozen=False,
        mode="source",
        source_root=source_root,
        install_root=source_root,
        resource_root=source_root,
    )
