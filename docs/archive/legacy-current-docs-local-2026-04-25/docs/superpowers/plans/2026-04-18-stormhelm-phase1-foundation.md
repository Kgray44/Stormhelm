# Stormhelm Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a packaging-ready Phase 1 Stormhelm foundation with a separate background core, a PySide6 dashboard shell, safe starter tools, SQLite persistence, and a bounded concurrent job manager.

**Architecture:** Use a service-first design where the core owns orchestration, safety, tools, jobs, and storage behind a localhost API. Keep the UI as a thin client with reusable panels, a controller, and tray-friendly lifecycle behavior.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, PySide6, SQLite, asyncio, pytest

---

### Task 1: Project Skeleton and Config Layer

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `config/default.toml`
- Create: `config/development.toml.example`
- Create: `src/stormhelm/config/models.py`
- Create: `src/stormhelm/config/loader.py`
- Create: `src/stormhelm/shared/paths.py`

- [ ] Define typed config dataclasses for network, storage, safety, tools, logging, concurrency, and UI settings.
- [ ] Load TOML defaults and environment overrides from `STORMHELM_*`.
- [ ] Resolve runtime data paths so install files and user data stay separate.
- [ ] Add tests for config loading and path resolution.

### Task 2: Storage and Event Infrastructure

**Files:**
- Create: `src/stormhelm/core/events.py`
- Create: `src/stormhelm/core/memory/database.py`
- Create: `src/stormhelm/core/memory/models.py`
- Create: `src/stormhelm/core/memory/repositories.py`
- Create: `tests/test_storage.py`

- [ ] Create the SQLite schema for sessions, messages, notes, tool runs, and preferences.
- [ ] Implement repositories for conversations, notes, preferences, and tool run history.
- [ ] Add an in-memory event buffer for the debug panel.
- [ ] Add tests that initialize a temp database and verify repository behavior.

### Task 3: Safety and Tool Runtime

**Files:**
- Create: `src/stormhelm/shared/result.py`
- Create: `src/stormhelm/core/safety/policy.py`
- Create: `src/stormhelm/core/tools/base.py`
- Create: `src/stormhelm/core/tools/registry.py`
- Create: `src/stormhelm/core/tools/executor.py`
- Create: `src/stormhelm/core/tools/builtins/*.py`
- Create: `tests/test_tool_registry.py`
- Create: `tests/test_safety.py`

- [ ] Define shared tool result objects and safety classifications.
- [ ] Implement a centralized safety policy with allowlisted file access and explicit action gating.
- [ ] Implement builtin tools: clock, system info, file reader, notes writer, echo, and shell stub.
- [ ] Add tests for registry behavior, safe execution, and blocked paths.

### Task 4: Job Manager and Orchestrator

**Files:**
- Create: `src/stormhelm/core/jobs/models.py`
- Create: `src/stormhelm/core/jobs/manager.py`
- Create: `src/stormhelm/core/orchestrator/router.py`
- Create: `src/stormhelm/core/orchestrator/assistant.py`
- Create: `tests/test_job_manager.py`

- [ ] Implement bounded queue workers with timeout, cancellation, and isolated failure handling.
- [ ] Persist recent tool run data for each job state transition.
- [ ] Add a simple text router that maps Phase 1 commands into safe tools.
- [ ] Add tests for job submission, completion, and cancellation behavior.

### Task 5: Core Service API and Bootstrap

**Files:**
- Create: `src/stormhelm/core/container.py`
- Create: `src/stormhelm/core/logging.py`
- Create: `src/stormhelm/core/api/schemas.py`
- Create: `src/stormhelm/core/api/app.py`
- Create: `src/stormhelm/core/service.py`
- Create: `src/stormhelm/entrypoints/core.py`

- [ ] Build the service container that wires config, storage, safety, jobs, tools, and orchestration together.
- [ ] Expose health, status, chat, jobs, events, notes, and settings endpoints.
- [ ] Configure file logging under the runtime data directory.
- [ ] Add a clean core entrypoint.

### Task 6: PySide6 UI Shell

**Files:**
- Create: `assets/styles/stormhelm.qss`
- Create: `assets/icons/stormhelm.svg`
- Create: `src/stormhelm/app/launcher.py`
- Create: `src/stormhelm/ui/client.py`
- Create: `src/stormhelm/ui/widgets/*.py`
- Create: `src/stormhelm/ui/main_window.py`
- Create: `src/stormhelm/ui/tray.py`
- Create: `src/stormhelm/ui/controllers/main_controller.py`
- Create: `src/stormhelm/ui/app.py`
- Create: `src/stormhelm/entrypoints/ui.py`

- [ ] Build a tray-ready main window with chat, status, jobs, logs, notes, and settings views.
- [ ] Implement a local API client for the UI.
- [ ] Auto-launch or reconnect to the core when the UI starts.
- [ ] Keep UI lifecycle separate from the core lifecycle.

### Task 7: Packaging and Release Placeholders

**Files:**
- Create: `scripts/run_core.ps1`
- Create: `scripts/run_ui.ps1`
- Create: `scripts/package_portable.ps1`
- Create: `scripts/package_installer.ps1`
- Create: `installer/pyinstaller/stormhelm-core.spec`
- Create: `installer/pyinstaller/stormhelm-ui.spec`
- Create: `installer/inno/Stormhelm.iss`
- Create: `docs/packaging.md`

- [ ] Add PowerShell launch helpers for development.
- [ ] Add PyInstaller placeholders for separate core and UI executables.
- [ ] Add an Inno Setup placeholder for later installer work.
- [ ] Document the packaging strategy clearly.

