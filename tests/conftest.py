from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from stormhelm.config.loader import load_config
from stormhelm.core.events import EventBuffer
from stormhelm.core.memory.database import SQLiteDatabase
from stormhelm.core.memory.repositories import PreferencesRepository
from stormhelm.core.orchestrator.session_state import ConversationStateStore
from stormhelm.core.tasks import DurableTaskService, TaskRepository
from stormhelm.core.trust import TrustRepository, TrustService


@pytest.fixture()
def workspace_temp_dir() -> Path:
    root = Path.cwd() / ".tmp" / "test-artifacts" / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def temp_project_root(workspace_temp_dir: Path) -> Path:
    config_dir = workspace_temp_dir / "config"
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
hide_to_tray_on_close = true
ghost_shortcut = "Ctrl+Space"

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
    return workspace_temp_dir


@pytest.fixture()
def temp_config(temp_project_root: Path):
    return load_config(project_root=temp_project_root, env={})


@pytest.fixture()
def trust_harness(temp_config):
    database = SQLiteDatabase(temp_config.storage.database_path)
    database.initialize()
    preferences = PreferencesRepository(database)
    session_state = ConversationStateStore(preferences)
    events = EventBuffer(capacity=128)
    task_service = DurableTaskService(
        repository=TaskRepository(database),
        session_state=session_state,
        events=events,
    )
    trust_service = TrustService(
        config=temp_config.trust,
        repository=TrustRepository(database),
        events=events,
        session_state=session_state,
        task_service=task_service,
    )
    return {
        "database": database,
        "events": events,
        "session_state": session_state,
        "task_service": task_service,
        "trust_service": trust_service,
    }
