# Stormhelm Release Checklist

This checklist is for the Phase 1.2.x portable-release workflow.

It is intentionally strict: do not mark Stormhelm release-ready until each applicable item has been verified on a normal local Windows machine.

## 1. Environment

- Confirm `.venv` exists and uses a supported CPython build.
- Confirm packaging dependency is available:
  - `.\.venv\Scripts\python.exe -m PyInstaller --version`
- Confirm the workspace is clean enough for packaging:
  - `git status --short`

## 2. Portable Build

- Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_portable.ps1
```

- Confirm the script exits successfully.
- Confirm the output folder exists:
  - `release\portable\Stormhelm-<version>-windows-x64\`
- Confirm the output zip exists if zip generation was not skipped.

## 3. Artifact Structure

Expected contents of the portable folder:

- `stormhelm-ui.exe`
- `stormhelm-core.exe`
- `README.md`
- `LICENSE`
- `BUILD-INFO.json`
- `Launch Stormhelm.bat`
- `config\default.toml`
- `config\portable.toml.example`

Notes:

- The current PyInstaller specs build one-file executables.
- Because of that, a separate Qt DLL or platform-plugin folder is not expected in the release root.
- Qt runtime files are embedded into the one-file package and unpack at runtime.

## 4. First-Run Verification

- Use a clean user-data location if possible.
- Launch `stormhelm-ui.exe` from the portable folder.
- Confirm the UI either connects to an existing core or launches the sibling `stormhelm-core.exe`.
- Confirm user-data initialization succeeds without writing into the portable install folder.

Expected default user-data root:

- `%LOCALAPPDATA%\Stormhelm`

Expected first-run outputs:

- log files under the user-data logs directory
- runtime state file under the user-data runtime directory
- SQLite database under the user-data data directory

## 5. Portable Runtime Smoke Test

Verify all of the following from the packaged app:

- UI main window opens
- status panel shows a version label
- core health and snapshot data load
- simple chat/tool call works:
  - `echo`
  - or `clock`
- notes write succeeds
- safe file read succeeds for an allowed path
- closing the window does not conceptually destroy the architecture

## 6. Failure Handling

- If a required folder cannot be created, confirm the error is visible in logs or UI messaging.
- If the sibling core cannot be found, confirm the UI reports that clearly.
- If config overrides are invalid, confirm the startup path fails loudly and predictably.

## 7. Installer Boundary

Do not call the installer phase complete until all of the following also exist:

- final `.ico` branding assets
- a successful Inno Setup compile
- shortcut behavior decisions
- startup-with-Windows design and validation
- upgrade path testing
- uninstall cleanup testing
- signed binaries and installer, if distributing to end users

## 8. Commit Readiness

- Confirm no build artifacts are tracked:
  - `build/`
  - `dist/`
  - `release/`
  - `.venv/`
- Confirm docs match current reality.
- Confirm `git diff --stat` is reasonable and understandable.
- Commit only source, scripts, config templates, and docs.
