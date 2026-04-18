from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class NetworkConfig:
    host: str
    port: int


@dataclass(slots=True)
class StorageConfig:
    data_dir: Path
    database_path: Path
    logs_dir: Path


@dataclass(slots=True)
class LoggingConfig:
    level: str
    file_name: str


@dataclass(slots=True)
class ConcurrencyConfig:
    max_workers: int
    queue_size: int
    default_job_timeout_seconds: float


@dataclass(slots=True)
class UIConfig:
    poll_interval_ms: int
    hide_to_tray_on_close: bool


@dataclass(slots=True)
class SafetyConfig:
    allowed_read_dirs: list[Path]
    allow_shell_stub: bool


@dataclass(slots=True)
class ToolEnablementConfig:
    clock: bool = True
    system_info: bool = True
    file_reader: bool = True
    notes_write: bool = True
    echo: bool = True
    shell_command: bool = False

    def is_enabled(self, tool_name: str) -> bool:
        return getattr(self, tool_name, False)


@dataclass(slots=True)
class ToolConfig:
    enabled: ToolEnablementConfig = field(default_factory=ToolEnablementConfig)
    max_file_read_bytes: int = 32768


@dataclass(slots=True)
class AppConfig:
    app_name: str
    environment: str
    debug: bool
    project_root: Path
    network: NetworkConfig
    storage: StorageConfig
    logging: LoggingConfig
    concurrency: ConcurrencyConfig
    ui: UIConfig
    safety: SafetyConfig
    tools: ToolConfig

    @property
    def api_base_url(self) -> str:
        return f"http://{self.network.host}:{self.network.port}"

    @property
    def log_file_path(self) -> Path:
        return self.storage.logs_dir / self.logging.file_name

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


def _serialize(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if is_dataclass(value):
        return _serialize(asdict(value))
    return value

