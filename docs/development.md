# Development

This page is for working on Stormhelm from source.

## Environment Setup

```powershell
cd C:\Stormhelm
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev,packaging]
```

If the Windows Store `python`/`py` aliases are unreliable on your machine, use the explicit venv interpreter after creation:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .[dev,packaging]
```

Sources: `pyproject.toml`, `scripts/run_core.ps1`, `scripts/run_ui.ps1`  
Tests: `tests/test_launcher.py`

## Run The App

Core:

```powershell
.\scripts\run_core.ps1
```

UI:

```powershell
.\scripts\run_ui.ps1
```

Combined dev helper:

```powershell
.\scripts\dev_launch.ps1
```

Useful health checks:

```powershell
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/status
curl http://127.0.0.1:8765/snapshot
```

Sources: `scripts/run_core.ps1`, `scripts/run_ui.ps1`, `scripts/dev_launch.ps1`, `src/stormhelm/core/api/app.py`  
Tests: `tests/test_core_container.py`, `tests/test_snapshot_resilience.py`

## Run Tests

Full suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Focused examples:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config_loader.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_planner.py tests/test_assistant_orchestrator.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_ui_bridge.py tests/test_qml_shell.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_software_control.py tests/test_discord_relay.py -q
```

When running from unusual shells or worktrees, pin the local source tree:

```powershell
$env:PYTHONPATH = "C:\Stormhelm\src"
.\.venv\Scripts\python.exe -m pytest tests/test_config_loader.py -q
```

Sources: `pyproject.toml`, `tests/conftest.py`  
Tests: all tests under `tests/`

## Build / Package

Portable build:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_portable.ps1
```

Installer build:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_installer.ps1
```

Installer packaging requires Inno Setup (`ISCC.exe`). Verify packaged builds manually on a clean Windows environment before release.

Sources: `scripts/package_portable.ps1`, `scripts/package_installer.ps1`, `pyproject.toml`  
Tests: `tests/test_launcher.py`; manual package verification still needed

## Config Development

Use a local development TOML file copied from `config/development.toml.example` for local overrides and `.env` for secrets/feature flags.

```powershell
Copy-Item config\development.toml.example config\development.toml
```

OpenAI example:

```powershell
$env:STORMHELM_OPENAI_ENABLED = "true"
$env:OPENAI_API_KEY = "<your key>"
```

Do not commit real keys.

Sources: `config/default.toml`, `config/development.toml.example`, `src/stormhelm/config/loader.py`  
Tests: `tests/test_config_loader.py`

## Add A New Route Family

1. Add typed route metadata to planner models if existing fields are not enough.
2. Add route detection and route-state output to `DeterministicPlanner`.
3. Prefer a subsystem-owned planner seam when the feature has nontrivial rules.
4. Add execution handling in `AssistantOrchestrator`.
5. Add UI route/result rendering in `command_surface_v2.py` only after backend route state exists.
6. Add focused tests for routing, execution, route state, and wrong-route cases.

Minimum source areas:

- `src/stormhelm/core/orchestrator/planner_models.py`
- `src/stormhelm/core/orchestrator/planner.py`
- `src/stormhelm/core/orchestrator/assistant.py`
- `src/stormhelm/ui/command_surface_v2.py`
- `tests/test_planner.py`
- feature-specific tests

Sources: `src/stormhelm/core/orchestrator/planner.py`, `src/stormhelm/core/orchestrator/planner_models.py`, `src/stormhelm/core/orchestrator/assistant.py`, `src/stormhelm/ui/command_surface_v2.py`  
Tests: `tests/test_planner.py`, `tests/test_command_surface.py`

## Add A New Adapter

1. Define an adapter contract with approval, verification, rollback, and trust-tier metadata.
2. Register the contract or bind it to a tool route.
3. Make safety policy route through the contract.
4. Add execution metadata using adapter execution reports.
5. Add tests that fail closed when the adapter route is unhealthy.

Minimum source areas:

- `src/stormhelm/core/adapters/contracts.py`
- `src/stormhelm/core/tools/executor.py`
- `src/stormhelm/core/safety/policy.py`
- feature-specific adapter/service files
- `tests/test_adapter_contracts.py`

Sources: `src/stormhelm/core/adapters/contracts.py`, `src/stormhelm/core/tools/executor.py`, `src/stormhelm/core/safety/policy.py`  
Tests: `tests/test_adapter_contracts.py`, `tests/test_safety.py`

## Add A New Setting

1. Add the field to `src/stormhelm/config/models.py`.
2. Add default TOML in `config/default.toml` if it should be visible/configurable.
3. Add loader parsing in `src/stormhelm/config/loader.py`.
4. Add environment override if needed.
5. Thread the config into the subsystem through `CoreContainer`.
6. Add config loader tests.
7. Update [settings.md](settings.md).

Sources: `src/stormhelm/config/models.py`, `src/stormhelm/config/loader.py`, `config/default.toml`, `src/stormhelm/core/container.py`  
Tests: `tests/test_config_loader.py`

## Add A New UI Surface

1. Decide which backend state owns the truth.
2. Add/extend a core status/snapshot/chat payload if necessary.
3. Shape QML-facing state in `UiBridge`.
4. Build QML component under `assets/qml/components`.
5. Wire it in `assets/qml/Main.qml` or an existing shell component.
6. Route actions through `UiBridge` and `CoreApiClient` or `MainController`.
7. Add bridge/QML/controller tests.

Minimum source areas:

- `src/stormhelm/ui/bridge.py`
- `src/stormhelm/ui/client.py`
- `src/stormhelm/ui/controllers/main_controller.py`
- `assets/qml/Main.qml`
- `assets/qml/components/<Surface>.qml`
- `tests/test_ui_bridge.py`
- `tests/test_qml_shell.py`

Sources: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/controllers/main_controller.py`, `assets/qml/Main.qml`  
Tests: `tests/test_ui_bridge.py`, `tests/test_main_controller.py`, `tests/test_qml_shell.py`

## Add A Tool

1. Implement a `BaseTool` subclass with descriptor/schema and `execute_sync` or async behavior.
2. Register it in `register_builtin_tools`.
3. Add a `ToolEnablementConfig` flag if it can be disabled.
4. Add safety policy behavior if it reads files, calls external surfaces, or changes local state.
5. Add planner/provider integration only after the tool contract is stable.
6. Add registry, safety, and execution tests.

Sources: `src/stormhelm/core/tools/base.py`, `src/stormhelm/core/tools/builtins/__init__.py`, `src/stormhelm/core/tools/executor.py`, `src/stormhelm/config/models.py`, `src/stormhelm/core/safety/policy.py`  
Tests: `tests/test_tool_registry.py`, `tests/test_safety.py`, `tests/test_job_manager.py`

## Working With Dirty Worktrees

Stormhelm often has active work in source/tests. Before broad edits:

```powershell
git status --short
git ls-files docs src/stormhelm tests config scripts pyproject.toml README.md
```

Do not assume untracked route/eval files are published behavior until they are intentionally added. When documenting features, mark active-worktree seams as needs verification if they are not tracked by `git ls-files`.

Sources: Git worktree state, `src/stormhelm/core/orchestrator/planner.py` imports, tracked source list  
Tests: Not applicable
