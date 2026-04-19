from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _find_qsb() -> str | None:
    local_tool = Path(sys.executable).resolve().parent / "pyside6-qsb.exe"
    if local_tool.exists():
        return str(local_tool)
    return shutil.which("pyside6-qsb") or shutil.which("pyside6-qsb.exe")


def _assert_shader_pack_has_hlsl(shader_path: Path) -> None:
    qsb = _find_qsb()
    if qsb is None:
        pytest.skip("pyside6-qsb is not available in PATH.")

    if not shader_path.exists():
        pytest.fail(f"Missing baked shader asset: {shader_path}")

    result = subprocess.run(
        [qsb, "-d", str(shader_path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "HLSL 50" in result.stdout


def _assert_shader_uses_premultiplied_alpha(shader_path: Path) -> None:
    assert shader_path.exists(), f"Missing shader source: {shader_path}"
    source = shader_path.read_text(encoding="utf-8")
    assert "tint * alpha" in source or "color * alpha" in source


def test_ship_glass_shader_pack_includes_hlsl_target() -> None:
    _assert_shader_pack_has_hlsl(Path.cwd() / "assets" / "qml" / "shaders" / "ship_glass.frag.qsb")


def test_nautical_mist_shader_packs_include_hlsl_target() -> None:
    _assert_shader_pack_has_hlsl(Path.cwd() / "assets" / "qml" / "shaders" / "foreground_mist.frag.qsb")


def test_sea_fog_shader_pack_includes_hlsl_target() -> None:
    _assert_shader_pack_has_hlsl(Path.cwd() / "assets" / "qml" / "shaders" / "sea_fog.frag.qsb")


def test_active_fog_shaders_use_premultiplied_alpha() -> None:
    _assert_shader_uses_premultiplied_alpha(Path.cwd() / "assets" / "qml" / "shaders" / "sea_fog.frag")
    _assert_shader_uses_premultiplied_alpha(Path.cwd() / "assets" / "qml" / "shaders" / "foreground_mist.frag")
