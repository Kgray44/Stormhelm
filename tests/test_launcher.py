from __future__ import annotations

import pytest

from stormhelm.app.launcher import build_core_command


def test_build_core_command_uses_module_mode_from_source(temp_config) -> None:
    command = build_core_command(temp_config)
    assert command[1:] == ["-m", "stormhelm.entrypoints.core"]


def test_build_core_command_requires_sibling_packaged_core(temp_config, workspace_temp_dir) -> None:
    temp_config.runtime.is_frozen = True
    temp_config.runtime.core_executable_path = workspace_temp_dir / "stormhelm-core.exe"

    with pytest.raises(RuntimeError, match="could not find the sibling core executable"):
        build_core_command(temp_config)
