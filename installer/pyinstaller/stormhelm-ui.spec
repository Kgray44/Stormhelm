from pathlib import Path


project_root = Path.cwd()
src_root = project_root / "src"

a = Analysis(
    [str(src_root / "stormhelm" / "entrypoints" / "ui.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=[
        (str(project_root / "assets"), "assets"),
        (str(project_root / "config"), "config"),
    ],
    hiddenimports=[
        "PySide6.QtNetwork",
        "PySide6.QtSvg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="stormhelm-ui",
    console=False,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
)
