from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from stormhelm.config.models import AppConfig


def ensure_core_running(config: AppConfig, wait_seconds: float = 8.0) -> bool:
    if core_is_available(config):
        return False

    command = build_core_command()
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = 0x00000008 | 0x00000200

    subprocess.Popen(
        command,
        cwd=str(config.project_root),
        creationflags=creationflags,
        close_fds=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if core_is_available(config):
            return True
        time.sleep(0.25)

    raise RuntimeError("Stormhelm core did not become available in time.")


def core_is_available(config: AppConfig) -> bool:
    try:
        with urlopen(f"{config.api_base_url}/health", timeout=1.0) as response:
            return response.status == 200
    except URLError:
        return False
    except Exception:
        return False


def build_core_command() -> list[str]:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).with_name("stormhelm-core.exe")
        return [str(executable)]
    return [sys.executable, "-m", "stormhelm.entrypoints.core"]

