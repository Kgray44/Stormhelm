# Phase 1 placeholder spec for building stormhelm-ui.exe
# Run with: pyinstaller installer/pyinstaller/stormhelm-ui.spec

block_cipher = None

a = Analysis(
    ["src/stormhelm/entrypoints/ui.py"],
    pathex=["src"],
    binaries=[],
    datas=[("assets", "assets"), ("config", "config")],
    hiddenimports=["PySide6.QtSvg"],
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
    name="stormhelm-ui",
    console=False,
)
