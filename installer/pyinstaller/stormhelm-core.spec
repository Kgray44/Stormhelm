from pathlib import Path


project_root = Path.cwd()
src_root = project_root / "src"

a = Analysis(
    [str(src_root / "stormhelm" / "entrypoints" / "core.py")],
    pathex=[str(src_root)],
    binaries=[],
    datas=[
        (str(project_root / "config"), "config"),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
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
    name="stormhelm-core",
    console=False,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
)
