from __future__ import annotations

from pathlib import Path

import pytest

from stormhelm.config.loader import load_config
from stormhelm.shared.runtime import RuntimeDiscovery


def test_load_config_applies_environment_overrides(temp_project_root: Path) -> None:
    runtime_dir = temp_project_root / "custom-runtime"
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_CORE_PORT": "9001",
            "STORMHELM_MAX_CONCURRENT_JOBS": "12",
            "STORMHELM_DATA_DIR": str(runtime_dir),
            "STORMHELM_OPENAI_ENABLED": "true",
            "STORMHELM_OPENAI_MODEL": "gpt-5.4-mini",
            "STORMHELM_OPENAI_PLANNER_MODEL": "gpt-5.4-mini",
            "STORMHELM_OPENAI_REASONING_MODEL": "gpt-5.4",
            "STORMHELM_HOME_LABEL": "Brooklyn Home",
            "STORMHELM_HOME_LATITUDE": "40.6782",
            "STORMHELM_HOME_LONGITUDE": "-73.9442",
            "OPENAI_API_KEY": "test-key",
        },
    )

    assert config.network.port == 9001
    assert config.concurrency.max_workers == 12
    assert config.storage.data_dir == runtime_dir.resolve()
    assert config.storage.database_path == (runtime_dir / "stormhelm.db").resolve()
    assert config.storage.state_dir == (runtime_dir / "state").resolve()
    assert config.runtime.assets_dir == (temp_project_root / "assets").resolve()
    assert config.runtime.user_config_path == (runtime_dir / "config" / "user.toml").resolve()
    assert config.openai.enabled is True
    assert config.openai.model == "gpt-5.4-mini"
    assert config.openai.planner_model == "gpt-5.4-mini"
    assert config.openai.reasoning_model == "gpt-5.4"
    assert config.openai.api_key == "test-key"
    assert config.location.home_label == "Brooklyn Home"
    assert config.location.home_latitude == pytest.approx(40.6782)
    assert config.location.home_longitude == pytest.approx(-73.9442)
    assert config.hardware_telemetry.enabled is True
    assert config.hardware_telemetry.helper_timeout_seconds == pytest.approx(12.0)
    assert config.hardware_telemetry.provider_timeout_seconds == pytest.approx(5.0)
    assert config.hardware_telemetry.active_cache_ttl_seconds == pytest.approx(8)


def test_load_config_defaults_to_nano_planner_and_full_reasoner(temp_project_root: Path) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.openai.planner_model == "gpt-5.4-nano"
    assert config.openai.reasoning_model == "gpt-5.4"
    assert config.hardware_telemetry.enabled is True
    assert config.hardware_telemetry.helper_timeout_seconds == pytest.approx(12.0)
    assert config.hardware_telemetry.provider_timeout_seconds == pytest.approx(5.0)
    assert config.hardware_telemetry.hwinfo_enabled is True
    assert config.hardware_telemetry.hwinfo_executable_path is None


def test_load_config_applies_hardware_telemetry_environment_overrides(temp_project_root: Path) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_HARDWARE_TELEMETRY_ENABLED": "false",
            "STORMHELM_HARDWARE_TELEMETRY_TIMEOUT_SECONDS": "4.5",
            "STORMHELM_HARDWARE_TELEMETRY_PROVIDER_TIMEOUT_SECONDS": "1.75",
            "STORMHELM_HARDWARE_TELEMETRY_IDLE_CACHE_TTL_SECONDS": "40",
            "STORMHELM_HARDWARE_TELEMETRY_ACTIVE_CACHE_TTL_SECONDS": "10",
            "STORMHELM_HARDWARE_TELEMETRY_BURST_CACHE_TTL_SECONDS": "1.5",
            "STORMHELM_HARDWARE_TELEMETRY_HWINFO_ENABLED": "false",
            "STORMHELM_HARDWARE_TELEMETRY_HWINFO_PATH": "C:/Tools/HWiNFO64.EXE",
        },
    )

    assert config.hardware_telemetry.enabled is False
    assert config.hardware_telemetry.helper_timeout_seconds == pytest.approx(4.5)
    assert config.hardware_telemetry.provider_timeout_seconds == pytest.approx(1.75)
    assert config.hardware_telemetry.idle_cache_ttl_seconds == pytest.approx(40)
    assert config.hardware_telemetry.active_cache_ttl_seconds == pytest.approx(10)
    assert config.hardware_telemetry.burst_cache_ttl_seconds == pytest.approx(1.5)
    assert config.hardware_telemetry.hwinfo_enabled is False
    assert config.hardware_telemetry.hwinfo_executable_path == "C:/Tools/HWiNFO64.EXE"


def test_load_config_uses_install_root_when_packaged(monkeypatch: pytest.MonkeyPatch, workspace_temp_dir: Path) -> None:
    install_root = workspace_temp_dir / "portable"
    resource_root = workspace_temp_dir / "bundle"
    data_dir = workspace_temp_dir / "userdata"

    (resource_root / "config").mkdir(parents=True, exist_ok=True)
    (resource_root / "assets").mkdir(parents=True, exist_ok=True)
    (install_root / "config").mkdir(parents=True, exist_ok=True)

    (resource_root / "config" / "default.toml").write_text(
        """
app_name = "Stormhelm"
release_channel = "dev"
environment = "packaged-test"
debug = false

[network]
host = "127.0.0.1"
port = 8765

[storage]
data_dir = ""

[logging]
level = "INFO"
file_name = "stormhelm.log"

[concurrency]
max_workers = 8
queue_size = 128
default_job_timeout_seconds = 20
history_limit = 500

[ui]
poll_interval_ms = 1500
hide_to_tray_on_close = true
ghost_shortcut = "Ctrl+Space"

[safety]
allowed_read_dirs = ["${PROJECT_ROOT}"]
allow_shell_stub = false

[tools]
max_file_read_bytes = 32768

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
    (install_root / "config" / "portable.toml").write_text(
        """
[network]
port = 9911
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "stormhelm.config.loader.discover_runtime",
        lambda: RuntimeDiscovery(
            is_frozen=True,
            mode="packaged",
            source_root=None,
            install_root=install_root,
            resource_root=resource_root,
        ),
    )
    monkeypatch.setattr(
        "stormhelm.config.loader._parse_env_file",
        lambda path: {},
    )

    config = load_config(env={"STORMHELM_DATA_DIR": str(data_dir)})

    assert config.runtime.mode == "packaged"
    assert config.project_root == install_root.resolve()
    assert config.runtime.install_root == install_root.resolve()
    assert config.runtime.resource_root == resource_root.resolve()
    assert config.runtime.assets_dir == (resource_root / "assets").resolve()
    assert config.runtime.portable_config_path == (install_root / "config" / "portable.toml").resolve()
    assert config.network.port == 9911
    assert config.storage.data_dir == data_dir.resolve()
    assert config.safety.allowed_read_dirs == [install_root.resolve()]
