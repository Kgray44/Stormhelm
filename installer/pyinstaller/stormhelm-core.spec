# Phase 1 placeholder spec for building stormhelm-core.exe
# Run with: pyinstaller installer/pyinstaller/stormhelm-core.spec

block_cipher = None

a = Analysis(
    ["src/stormhelm/entrypoints/core.py"],
    pathex=["src"],
    binaries=[],
    datas=[("config", "config")],
    hiddenimports=["uvicorn.logging", "uvicorn.loops.auto"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="stormhelm-core",
    console=True,
)
