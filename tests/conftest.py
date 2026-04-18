from __future__ import annotations

from pathlib import Path

import pytest

from stormhelm.config.loader import load_config


@pytest.fixture()
def temp_project_root(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "default.toml").write_text(
        """
app_name = "Stormhelm"
environment = "test"
debug = true

[network]
host = "127.0.0.1"
port = 8765

[storage]
data_dir = "${PROJECT_ROOT}/.runtime"

[logging]
level = "DEBUG"
file_name = "stormhelm.log"

[concurrency]
max_workers = 4
queue_size = 16
default_job_timeout_seconds = 1

[ui]
poll_interval_ms = 50
hide_to_tray_on_close = false

[safety]
allowed_read_dirs = ["${PROJECT_ROOT}"]
allow_shell_stub = false

[tools]
max_file_read_bytes = 2048

[tools.enabled]
clock = true
system_info = true
file_reader = true
notes_write = true
echo = true
shell_command = false
        """.strip(),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def temp_config(temp_project_root: Path):
    return load_config(project_root=temp_project_root, env={})

