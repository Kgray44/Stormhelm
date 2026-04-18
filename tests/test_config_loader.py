from __future__ import annotations

from pathlib import Path

from stormhelm.config.loader import load_config


def test_load_config_applies_environment_overrides(temp_project_root: Path) -> None:
    runtime_dir = temp_project_root / "custom-runtime"
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_CORE_PORT": "9001",
            "STORMHELM_MAX_CONCURRENT_JOBS": "12",
            "STORMHELM_DATA_DIR": str(runtime_dir),
        },
    )

    assert config.network.port == 9001
    assert config.concurrency.max_workers == 12
    assert config.storage.data_dir == runtime_dir.resolve()
    assert config.storage.database_path == (runtime_dir / "stormhelm.db").resolve()

