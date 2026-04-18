# Stormhelm Packaging and Release Strategy

## Packaging Targets

Stormhelm is being designed for two Windows distribution modes:

1. portable/developer build
2. installer-backed normal-user build

Phase 1 prepares the structure for both without attempting to finish the final release pipeline.

## Recommended Strategy

### Build Layer

Use PyInstaller to create two Windows executables:

- `stormhelm-core.exe`
- `stormhelm-ui.exe`

Why PyInstaller first:

- mature support for Python desktop apps
- friendly to FastAPI/Uvicorn and PySide6 when configured explicitly
- simple path to portable zip builds
- works well as a stepping stone before a more opinionated installer

### Installer Layer

Use Inno Setup for a Windows installer in a later phase.

Why:

- reliable Windows installer experience
- easy creation of Start Menu and Desktop shortcuts
- can register uninstall metadata cleanly
- can later add optional "start Stormhelm when Windows starts" behavior

## Data Separation

Install files should remain separate from user state.

Planned defaults:

- app binaries under `Program Files\Stormhelm` for installer builds
- user state under `%LOCALAPPDATA%\Stormhelm`

User state includes:

- SQLite database
- logs
- config overrides
- assistant notes and history

This separation keeps uninstall and upgrade behavior predictable.

## Entry Structure

The repo already separates:

- `stormhelm.entrypoints.core`
- `stormhelm.entrypoints.ui`

That allows packaged binaries to mirror the architecture directly rather than collapsing back into a single window-first executable.

## Portable Build Notes

Portable build expectations:

- keep binaries and bundled assets together
- launch the UI executable manually
- UI can spawn the sibling core executable if the core is not already running
- store user data in `%LOCALAPPDATA%\Stormhelm` even for portable mode unless explicitly overridden

## Installer Build Notes

Later installer responsibilities:

- install binaries and assets
- create shortcuts
- optionally register startup-with-Windows behavior
- optionally create a tray-first startup mode
- clean uninstall of installed files without deleting user data unless explicitly chosen

## Current Placeholders

- `installer/pyinstaller/*.spec`
- `installer/inno/Stormhelm.iss`
- `scripts/package_portable.ps1`
- `scripts/package_installer.ps1`

These are intentionally included in Phase 1 so release workflows have a home from day one.

