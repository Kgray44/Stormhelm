# Stormhelm Packaging and Release Strategy

## Packaging Targets

Stormhelm is prepared for two Windows distribution modes:

1. a portable release folder for developers and early testers
2. a later Inno Setup installer for normal end users

## Source Of Truth

Versioning now comes from `src/stormhelm/version.py`.

That version feeds:

- package metadata in `pyproject.toml`
- UI version display
- core API health/status metadata
- portable release folder naming
- installer version defines

## Portable Release Workflow

### Expected output

`scripts/package_portable.ps1` builds and assembles:

`release/portable/Stormhelm-<version>-windows-x64/`

Contents:

- `stormhelm-ui.exe`
- `stormhelm-core.exe`
- `README.md`
- `LICENSE`
- `BUILD-INFO.json`
- `Launch Stormhelm.bat`
- `config/default.toml`
- `config/portable.toml.example`

The current PyInstaller specs build one-file executables, so the release root should not contain a separate Qt runtime tree. `stormhelm-ui.exe` and `stormhelm-core.exe` are expected to be sibling binaries in the release folder.

### Build command

From `C:\Stormhelm`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_portable.ps1
```

Optional flags:

- `-SkipDependencyInstall`
- `-SkipZip`

### What the script does

1. Uses the workspace virtual environment.
2. Installs or verifies PyInstaller dependencies.
3. Builds `stormhelm-core.exe` from `installer/pyinstaller/stormhelm-core.spec`.
4. Builds `stormhelm-ui.exe` from `installer/pyinstaller/stormhelm-ui.spec`.
5. Assembles a portable release folder under `release/portable/`.

If a previous release folder or zip is locked, the script now fails loudly instead of reusing stale artifacts.

### Runtime expectations

- The packaged UI looks for a sibling `stormhelm-core.exe` when frozen.
- Bundled default config and assets are embedded into the binaries by PyInstaller.
- User data still goes to `%LOCALAPPDATA%\Stormhelm` by default.
- Optional portable overrides can live beside the binaries in `config/portable.toml`.
- Logs, runtime state, and the SQLite database should land under the user-data root, not inside the release folder.

## Why The Runtime Layout Changed

Phase 1 assumed the source tree was always present. Phase 1.2 now distinguishes:

- source root
- install root
- bundled resource root
- user data root
- user config path
- runtime state path

That separation is what makes the same codebase behave correctly in source mode, portable mode, and later installer mode.

## PyInstaller Notes

The current specs are designed around two separate executables:

- `stormhelm-core.exe`
- `stormhelm-ui.exe`

Each executable embeds the resources it needs:

- core bundles config defaults
- UI bundles config defaults plus UI assets

This keeps the background-core-first architecture intact after packaging instead of collapsing Stormhelm back into a single-window executable.

## Installer Preparation

The Inno Setup scaffold now expects a portable release folder as input:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_installer.ps1
```

If Inno Setup is installed, the script can invoke `ISCC.exe`.
If it is not installed, the script prints the exact compile command needed later.

## What Still Remains For Installer Phase

Phase 1.2 does not finish the installer. The next installer-focused pass should add:

- final application icon assets (`.ico`)
- signed binaries and installer
- startup-with-Windows registration
- Start Menu and Desktop shortcut policy choices
- tray-first launch mode decisions
- installer upgrade path testing
- uninstall behavior validation
- optional per-user vs per-machine install strategy

## Verification Boundary

The portable build scripts and specs are now real and exercised, but final PyInstaller executable mutation is blocked by this shell environment's Windows resource restrictions. A normal unsandboxed Windows terminal should be used for the final binary verification pass.

## Exact Local Verification Steps

From `C:\Stormhelm` on a normal local Windows terminal:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_portable.ps1
Start-Process .\release\portable\Stormhelm-<version>-windows-x64\stormhelm-ui.exe
```

Then verify:

1. the UI opens from the packaged output
2. the UI detects or launches the sibling packaged core
3. the status panel loads version and core state
4. `%LOCALAPPDATA%\Stormhelm` receives logs, runtime state, and the SQLite database
5. `echo`, `clock`, notes write, and an allowlisted file read all succeed

Use [Release Checklist](release-checklist.md) as the verification gate before tagging a portable build.

If the build stops before PyInstaller starts because the previous portable folder cannot be removed, close Explorer windows or running processes that may be holding files in `release\portable\Stormhelm-<version>-windows-x64`, delete that folder, and rerun the script.
