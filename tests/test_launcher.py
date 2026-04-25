from __future__ import annotations

import pytest

from stormhelm.app.launcher import (
    CREATE_NEW_PROCESS_GROUP,
    CREATE_NO_WINDOW,
    DETACHED_PROCESS,
    build_core_command,
    build_core_creationflags,
)


def test_build_core_command_uses_module_mode_from_source(temp_config) -> None:
    command = build_core_command(temp_config)
    assert command[1:] == ["-m", "stormhelm.entrypoints.core"]


def test_build_core_command_requires_sibling_packaged_core(temp_config, workspace_temp_dir) -> None:
    temp_config.runtime.is_frozen = True
    temp_config.runtime.core_executable_path = workspace_temp_dir / "stormhelm-core.exe"

    with pytest.raises(RuntimeError, match="could not find the sibling core executable"):
        build_core_command(temp_config)


def test_build_core_creationflags_hide_backend_console_on_windows(monkeypatch) -> None:
    monkeypatch.setattr("stormhelm.app.launcher.sys.platform", "win32")

    flags = build_core_creationflags()

    assert flags & CREATE_NO_WINDOW
    assert flags & DETACHED_PROCESS
    assert flags & CREATE_NEW_PROCESS_GROUP
