from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Callable, Mapping

from stormhelm.config.models import (
    AppConfig,
    ConcurrencyConfig,
    LoggingConfig,
    NetworkConfig,
    SafetyConfig,
    StorageConfig,
    ToolConfig,
    ToolEnablementConfig,
    UIConfig,
)
from stormhelm.shared.paths import default_data_dir, project_root as discover_project_root


ConfigDict = dict[str, Any]


def load_config(
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    project_root: Path | None = None,
) -> AppConfig:
    root = (project_root or discover_project_root()).resolve()
    config_data = _read_toml(root / "config" / "default.toml")

    override_path = Path(config_path).resolve() if config_path else root / "config" / "development.toml"
    if override_path.exists():
        config_data = _deep_merge(config_data, _read_toml(override_path))

    env_values = dict(_parse_env_file(root / ".env"))
    env_values.update(os.environ)
    if env is not None:
        env_values.update(env)

    config_data = _apply_env_overrides(config_data, env_values)
    return _build_app_config(config_data, root)


def _build_app_config(data: ConfigDict, root: Path) -> AppConfig:
    app_name = str(data.get("app_name", "Stormhelm"))
    environment = str(data.get("environment", "development"))
    debug = bool(data.get("debug", True))

    network_data = data.get("network", {})
    host = str(network_data.get("host", "127.0.0.1"))
    port = int(network_data.get("port", 8765))

    storage_data = data.get("storage", {})
    data_dir = _expand_path(storage_data.get("data_dir") or "", root, None) or default_data_dir(app_name)
    logs_dir = _expand_path(storage_data.get("logs_dir") or "", root, data_dir) or (data_dir / "logs")
    database_path = _expand_path(storage_data.get("database_path") or "", root, data_dir) or (data_dir / "stormhelm.db")

    logging_data = data.get("logging", {})
    logging_config = LoggingConfig(
        level=str(logging_data.get("level", "DEBUG" if debug else "INFO")),
        file_name=str(logging_data.get("file_name", "stormhelm.log")),
    )

    concurrency_data = data.get("concurrency", {})
    concurrency_config = ConcurrencyConfig(
        max_workers=int(concurrency_data.get("max_workers", 8)),
        queue_size=int(concurrency_data.get("queue_size", 128)),
        default_job_timeout_seconds=float(concurrency_data.get("default_job_timeout_seconds", 20)),
    )

    ui_data = data.get("ui", {})
    ui_config = UIConfig(
        poll_interval_ms=int(ui_data.get("poll_interval_ms", 1500)),
        hide_to_tray_on_close=bool(ui_data.get("hide_to_tray_on_close", True)),
    )

    safety_data = data.get("safety", {})
    allowed_dirs = [
        _expand_path(value, root, data_dir) or root
        for value in safety_data.get("allowed_read_dirs", [str(root), "~/Documents"])
    ]
    safety_config = SafetyConfig(
        allowed_read_dirs=allowed_dirs,
        allow_shell_stub=bool(safety_data.get("allow_shell_stub", False)),
    )

    tool_data = data.get("tools", {})
    enabled_data = tool_data.get("enabled", {})
    tool_config = ToolConfig(
        enabled=ToolEnablementConfig(
            clock=bool(enabled_data.get("clock", True)),
            system_info=bool(enabled_data.get("system_info", True)),
            file_reader=bool(enabled_data.get("file_reader", True)),
            notes_write=bool(enabled_data.get("notes_write", True)),
            echo=bool(enabled_data.get("echo", True)),
            shell_command=bool(enabled_data.get("shell_command", False)),
        ),
        max_file_read_bytes=int(tool_data.get("max_file_read_bytes", 32768)),
    )

    return AppConfig(
        app_name=app_name,
        environment=environment,
        debug=debug,
        project_root=root,
        network=NetworkConfig(host=host, port=port),
        storage=StorageConfig(
            data_dir=data_dir,
            database_path=database_path,
            logs_dir=logs_dir,
        ),
        logging=logging_config,
        concurrency=concurrency_config,
        ui=ui_config,
        safety=safety_config,
        tools=tool_config,
    )


def _read_toml(path: Path) -> ConfigDict:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _deep_merge(base: ConfigDict, override: ConfigDict) -> ConfigDict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


def _apply_env_overrides(data: ConfigDict, env: Mapping[str, str]) -> ConfigDict:
    merged = dict(data)
    overrides: dict[str, tuple[str, Callable[[str], Any]]] = {
        "STORMHELM_ENV": ("environment", str),
        "STORMHELM_DEBUG": ("debug", _parse_bool),
        "STORMHELM_CORE_HOST": ("network.host", str),
        "STORMHELM_CORE_PORT": ("network.port", int),
        "STORMHELM_DATA_DIR": ("storage.data_dir", str),
        "STORMHELM_MAX_CONCURRENT_JOBS": ("concurrency.max_workers", int),
        "STORMHELM_DEFAULT_JOB_TIMEOUT_SECONDS": ("concurrency.default_job_timeout_seconds", float),
    }

    for env_key, (path, parser) in overrides.items():
        raw_value = env.get(env_key)
        if raw_value is None or raw_value == "":
            continue
        _set_nested_value(merged, path, parser(raw_value))

    return merged


def _set_nested_value(target: ConfigDict, dotted_path: str, value: Any) -> None:
    current = target
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _expand_path(raw: str | None, root: Path, data_dir: Path | None) -> Path | None:
    if not raw:
        return None

    expanded = raw.replace("${PROJECT_ROOT}", str(root))
    if data_dir is not None:
        expanded = expanded.replace("${DATA_DIR}", str(data_dir))
    return Path(expanded).expanduser().resolve()


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}
