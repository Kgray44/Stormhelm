# Stormhelm

Stormhelm is a local-first desktop AI assistant for Windows designed from day one as two separate parts:

1. a background core service that owns orchestration, storage, sessions, tools, logs, and safety
2. a PySide6 desktop shell that acts as a control panel, chat client, dashboard, and tray-ready frontend

Phase 1 intentionally does not try to build the full always-on voice assistant yet. It establishes the architecture, packaging posture, and a working text-based MVP that can grow into voice, browser automation, app control, memory retrieval, and computer-use workflows later.

Phase 1 integration now adds:

- OpenAI Responses API integration through a modular provider layer
- model-driven tool calling with Stormhelm-owned 8-worker execution and fan-out
- first real Deck browser surface
- first real Deck file viewers for text, markdown, images, and PDFs
- opened-item workspace behavior inside the existing Deck shell

## Phase 1 Goals

- clean background-core-first architecture
- separate UI and core processes
- bounded concurrent job execution with room for 8+ tool workers
- SQLite-backed local history, notes, preferences, and tool run storage
- safe starter tools with explicit safety classifications
- polished Qt shell with chat, status, activity, logs, notes, and settings surfaces
- packaging-ready structure for portable builds and installer workflows

## Repo Layout

```text
assets/                 Icons and Qt stylesheets
config/                 Default and example config files
docs/                   Architecture, roadmap, packaging, design, and plan docs
installer/              PyInstaller and Inno Setup placeholders
scripts/                Dev and packaging helper scripts
src/stormhelm/          Application source code
tests/                  Basic unit tests for Phase 1 foundations
```

## Architecture Summary

### Background Core

- FastAPI service bound to `127.0.0.1`
- owns orchestration, sessions, job manager, safety, tools, persistence, and logs
- can keep running even when the UI is closed
- exposes a local HTTP API for chat, status, jobs, logs, notes, and settings
- integrates with OpenAI Responses API through a provider abstraction instead of wiring model logic into UI code
- keeps tool execution under Stormhelm's own bounded scheduler so multi-tool fan-out, cancellation, timeout handling, and job tracking remain local

### Desktop UI

- PySide6 control shell
- QML-first Ghost Mode and Command Deck shells built around one shared visual anchor
- Ghost Mode remains mouse click-through and supports keyboard signaling with `Ctrl+Space`
- Command Deck uses a larger workspace canvas, a slimmer command spine, a global bottom rail, and workspace-local left navigation
- Command Deck can now hold opened web pages and opened files inside the workspace canvas
- Helm is the direction for user-facing behavior/configuration surfaces
- Systems remains the direction for runtime, diagnostics, and technical state
- tray-ready close behavior so the UI can hide without conceptually destroying the assistant

### Storage

- SQLite for conversations, notes, tool runs, and preferences
- log files written under the user data directory
- install files kept separate from user data for clean uninstall behavior later

## Quick Start

### 1. Install Python

Stormhelm targets Python 3.11 or newer on Windows.

### 2. Create a virtual environment

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev,packaging]
```

### 3. Review config

- copy `.env.example` if you want environment overrides
- copy `config/development.toml.example` to `config/development.toml` for local tweaks
- set `OPENAI_API_KEY` and `STORMHELM_OPENAI_ENABLED=true` if you want natural-language model routing through the Responses API

### 4. Run the core

```powershell
.\scripts\run_core.ps1
```

### 5. Run the UI

```powershell
.\scripts\run_ui.ps1
```

The UI will attempt to connect to the core on `127.0.0.1:8765` and can auto-start it when launched from source or from packaged binaries.

### Ghost Shortcut

- Press `Ctrl+Space` to summon Ghost text capture.
- Type directly into the Ghost signal strip.
- Press `Enter` to send or `Esc` to clear and dismiss.

## Portable Build

Create a portable release folder with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_portable.ps1
```

The release output is written under `release/portable/Stormhelm-<version>-windows-x64/`.

## Safe Phase 1 Tooling

- `clock` for local and UTC time
- `system_info` for platform and runtime details
- `file_reader` for allowlisted text file reads only
- `notes_write` for SQLite-backed notes
- `echo` for development validation
- `shell_command` stub that demonstrates permission gating without enabling unrestricted shell execution
- `deck_open_url` and `external_open_url` for clean internal-vs-external browsing decisions
- `deck_open_file` and `external_open_file` for safe allowlisted file opens inside the Deck or native Windows hand-off

## Integration Behaviors

- Ghost is still for quick orchestration and external hand-offs.
- Deck is now where internal web pages and internal file viewing live.
- Natural-language requests can use the OpenAI provider when enabled.
- Explicit commands still work even without OpenAI configured, including `/time`, `/system`, `/read <path>`, and `/open [deck|external] <url-or-path>`.

## Configuration

Stormhelm uses:

- `config/default.toml` for defaults
- optional environment overrides from `.env`
- a packaging-friendly runtime path strategy that keeps user data under `%LOCALAPPDATA%\Stormhelm` by default

Key settings include:

- allowed read directories
- per-tool enablement
- max concurrent jobs
- default job timeout
- debug logging level
- UI poll interval

## Tests

Phase 1 includes basic tests for:

- config loading
- storage and repositories
- tool registration and execution
- safety gating
- job manager behavior

Run them with:

```powershell
pytest -q
```

If your environment blocks SQLite writes in the sandbox, run the suite from a normal local PowerShell session instead of an isolated shell.

## Documentation

- [Architecture Overview](docs/architecture-overview.md)
- [Packaging Strategy](docs/packaging.md)
- [Release Checklist](docs/release-checklist.md)
- [Phase 1.2 Architecture Review](docs/phase1-2-review.md)
- [Roadmap](docs/roadmap.md)
- [Phase 1 Design Spec](docs/superpowers/specs/2026-04-18-stormhelm-phase1-design.md)
- [Phase 1 Implementation Plan](docs/superpowers/plans/2026-04-18-stormhelm-phase1-foundation.md)

## Voice and Future Expansion

Voice is not implemented in Phase 1, but the architecture leaves clean insertion points for:

- wake word and microphone pipeline components inside the core
- speech-to-text and text-to-speech adapters
- automation schedulers
- browser and desktop control tools
- semantic memory and retrieval layers
- future screen/computer-use agents
