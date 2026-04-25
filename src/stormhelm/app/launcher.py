from __future__ import annotations

import os
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from stormhelm.config.models import AppConfig

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008


def ensure_core_running(config: AppConfig, wait_seconds: float = 8.0) -> bool:
    if core_is_available(config):
        return False

    command = build_core_command(config)
    creationflags = build_core_creationflags()

    child_env = dict()
    child_env.update(
        {
            "STORMHELM_ENV": config.environment,
            "STORMHELM_DEBUG": "true" if config.debug else "false",
            "STORMHELM_CORE_HOST": config.network.host,
            "STORMHELM_CORE_PORT": str(config.network.port),
            "STORMHELM_DATA_DIR": str(config.storage.data_dir),
            "STORMHELM_RELEASE_CHANNEL": config.release_channel,
        }
    )

    subprocess.Popen(
        command,
        cwd=str(config.runtime.install_root),
        creationflags=creationflags,
        close_fds=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, **child_env},
    )

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if core_is_available(config):
            return True
        time.sleep(0.25)

    raise RuntimeError(
        "Stormhelm core did not become available in time. "
        f"Expected endpoint: {config.api_base_url} | "
        f"Core log: {config.core_log_file_path}"
    )


def core_is_available(config: AppConfig) -> bool:
    try:
        with urlopen(f"{config.api_base_url}/health", timeout=1.0) as response:
            return response.status == 200
    except URLError:
        return False
    except Exception:
        return False


def build_core_command(config: AppConfig) -> list[str]:
    if config.runtime.is_frozen:
        executable = config.runtime.core_executable_path
        if not executable.exists():
            raise RuntimeError(
                "Packaged Stormhelm UI could not find the sibling core executable at "
                f"'{executable}'. Build the portable release so both binaries ship together."
            )
        return [str(executable)]
    return [sys.executable, "-m", "stormhelm.entrypoints.core"]


def build_core_creationflags() -> int:
    if not sys.platform.startswith("win"):
        return 0
    return DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
