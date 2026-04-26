# Troubleshooting

Start with live state, not guesses:

```powershell
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/status
curl http://127.0.0.1:8765/snapshot
curl http://127.0.0.1:8765/events
```

Sources: `src/stormhelm/core/api/app.py`, `src/stormhelm/core/container.py`, `src/stormhelm/core/events.py`  
Tests: `tests/test_core_container.py`, `tests/test_events.py`, `tests/test_snapshot_resilience.py`

## App Will Not Start

| Field | Details |
|---|---|
| Symptom | Core script exits, UI does not open, or `curl /health` fails. |
| Likely cause | Missing venv/dependencies, wrong Python alias, port conflict, config parse error, stale resident process. |
| Debug command/log | `.\.venv\Scripts\python.exe -m stormhelm.entrypoints.core`, `curl http://127.0.0.1:8765/health`, check logs under runtime logs dir. |
| Fix | Reinstall deps, use explicit venv interpreter, check `STORMHELM_CORE_PORT`, inspect config, restart resident core. |
| Source area | `scripts/run_core.ps1`, `src/stormhelm/entrypoints/core.py`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/api/app.py` |

Tests: `tests/test_launcher.py`, `tests/test_config_loader.py`

## Core Not Connected

| Field | Details |
|---|---|
| Symptom | UI shows disconnected or stale status. |
| Likely cause | Core not running, wrong host/port, event stream reconnect loop, backend restart. |
| Debug command/log | `curl http://127.0.0.1:8765/health`, `curl http://127.0.0.1:8765/status`, UI client error logs. |
| Fix | Start core, verify `network.host`/`network.port`, use `/snapshot` to reconcile, restart UI if stream state is wedged. |
| Source area | `src/stormhelm/ui/client.py`, `src/stormhelm/ui/controllers/main_controller.py`, `src/stormhelm/core/api/app.py` |

Tests: `tests/test_ui_client_streaming.py`, `tests/test_main_controller.py`

## UI Bridge Missing State

| Field | Details |
|---|---|
| Symptom | Ghost/Deck panels are empty or route inspector does not update. |
| Likely cause | `/snapshot` missing fields, event stream gap, bridge model mismatch, command surface shape changed. |
| Debug command/log | `curl http://127.0.0.1:8765/snapshot`, focused bridge tests. |
| Fix | Update `UiBridge` shaping with backend payload, preserve backend authority, add/repair bridge contract test. |
| Source area | `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/command_surface_v2.py`, `src/stormhelm/core/container.py` |

Tests: `tests/test_ui_bridge.py`, `tests/test_ui_bridge_authority_contracts.py`, `tests/test_command_surface.py`

## Route Goes To Wrong Subsystem

| Field | Details |
|---|---|
| Symptom | A calculation/browser/software/screen/relay request becomes generic provider text or wrong native route. |
| Likely cause | Planner route scoring/regression, missing route family guard, context binding failure, feature flag disabled. |
| Debug command/log | Inspect chat response `route_state`; run focused planner tests. |
| Fix | Fix planner/subsystem seam, add wrong-route regression test, verify command surface route state. |
| Source area | `src/stormhelm/core/orchestrator/planner.py`, `src/stormhelm/core/orchestrator/planner_models.py`, subsystem planner files. |

Tests: `tests/test_planner.py`, `tests/test_fuzzy_language_evaluation.py`, `tests/test_browser_destination_resolution.py`

## Software Install Routes Incorrectly

| Field | Details |
|---|---|
| Symptom | Install/update/uninstall claims success, skips approval, or chooses an untrusted source. |
| Likely cause | Software-control planner/service bug, trust state mismatch, unsafe test mode, source filtering regression. |
| Debug command/log | Check `/settings`, route state, software response debug payload. |
| Fix | Confirm `software_control.trusted_sources_only=true`, `privileged_operations_allowed=false`, approval state present, and execution status is not mislabeled. |
| Source area | `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/software_control/catalog.py`, `src/stormhelm/core/safety/policy.py`, `src/stormhelm/core/trust/service.py` |

Tests: `tests/test_software_control.py`, `tests/test_assistant_software_control.py`, `tests/test_trust_service.py`

## OpenAI Disabled Or Missing Key

| Field | Details |
|---|---|
| Symptom | Generic provider fallback unavailable or provider-backed requests do not run. |
| Likely cause | `openai.enabled=false`, missing `OPENAI_API_KEY`, missing `STORMHELM_OPENAI_ENABLED=true`. |
| Debug command/log | `curl http://127.0.0.1:8765/settings`, inspect provider status in `/status`. |
| Fix | Set key in environment or `.env`, set enable flag, restart core. Do not commit keys. |
| Source area | `src/stormhelm/config/loader.py`, `src/stormhelm/core/container.py`, `src/stormhelm/core/providers/openai_responses.py` |

Tests: `tests/test_config_loader.py`, `tests/test_command_eval_provider_audit.py`

## QML Crash Or Load Failure

| Field | Details |
|---|---|
| Symptom | UI exits, QML warnings/errors, component not found, shader issues. |
| Likely cause | QML property mismatch, missing component, shader asset issue, Qt module issue. |
| Debug command/log | Run UI from PowerShell and capture warnings; run QML tests. |
| Fix | Repair QML/bridge property names together, avoid hidden backend assumptions in QML, run shader asset tests. |
| Source area | `assets/qml/Main.qml`, `assets/qml/components/*.qml`, `src/stormhelm/ui/bridge.py` |

Tests: `tests/test_qml_shell.py`, `tests/test_shader_assets.py`

## Packaging Issue

| Field | Details |
|---|---|
| Symptom | Portable build missing assets/config, installer script fails, packaged app cannot start. |
| Likely cause | PyInstaller packaging config, missing Inno Setup, missing copied asset/config path, runtime path mismatch. |
| Debug command/log | `powershell -ExecutionPolicy Bypass -File .\scripts\package_portable.ps1`, package logs/output folder. |
| Fix | Verify `release/portable/Stormhelm-<version>-windows-x64`, ensure assets/config copied, install/configure Inno Setup for installer. |
| Source area | `scripts/package_portable.ps1`, `scripts/package_installer.ps1`, `src/stormhelm/config/loader.py` |

Tests: `tests/test_launcher.py`; manual package verification needed

## Config Issue

| Field | Details |
|---|---|
| Symptom | Core fails during startup or effective settings differ from expectation. |
| Likely cause | Invalid TOML/env type, stale `.env`, env override beating TOML, unsafe test mode enabled. |
| Debug command/log | `curl http://127.0.0.1:8765/settings`, run config tests. |
| Fix | Inspect `config/default.toml`, the optional local development TOML copied from `config/development.toml.example`, `.env`, and relevant `STORMHELM_*` env vars. |
| Source area | `src/stormhelm/config/loader.py`, `src/stormhelm/config/models.py`, `config/default.toml` |

Tests: `tests/test_config_loader.py`

## Windows Startup Issue

| Field | Details |
|---|---|
| Symptom | Stormhelm does not start with Windows or startup state looks stale. |
| Likely cause | Registry registration mismatch, stale shell heartbeat, packaged/source path mismatch. |
| Debug command/log | `/snapshot` lifecycle section, lifecycle tests. |
| Fix | Use lifecycle startup API/UI path to reconfigure, verify startup commands, restart shell. |
| Source area | `src/stormhelm/core/lifecycle/service.py`, `src/stormhelm/core/lifecycle/models.py`, `src/stormhelm/ui/controllers/main_controller.py` |

Tests: `tests/test_lifecycle_service.py`, `tests/test_ui_lifecycle_bridge.py`

## Stale State Or Traces

| Field | Details |
|---|---|
| Symptom | UI shows old route/task/trust/event state after backend restart or stream gap. |
| Likely cause | Event replay gap, stale runtime JSON, bridge not reconciling snapshot, resident process. |
| Debug command/log | `/events`, `/events/stream`, `/snapshot`, runtime state files. |
| Fix | Force snapshot reconciliation, restart UI/core, inspect runtime state path before deleting anything. |
| Source area | `src/stormhelm/core/events.py`, `src/stormhelm/core/runtime_state.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/bridge.py` |

Tests: `tests/test_events.py`, `tests/test_snapshot_resilience.py`, `tests/test_runtime_state.py`

## Tests Failing

| Field | Details |
|---|---|
| Symptom | Focused or full pytest run fails. |
| Likely cause | Importing installed package instead of local source, missing optional runtime dependency, active worktree mismatch, QML environment issue. |
| Debug command/log | `$env:PYTHONPATH="C:\Stormhelm\src"; .\.venv\Scripts\python.exe -m pytest <test> -q -vv` |
| Fix | Pin `PYTHONPATH`, run focused tests, separate source failure from environment/QML/offscreen failures, document known-red tests if accepted. |
| Source area | `pyproject.toml`, `tests/conftest.py`, failing module path. |

Tests: whichever test fails

## Discord Relay Fails

| Field | Details |
|---|---|
| Symptom | Preview cannot resolve payload, dispatch fails, wrong-thread refusal, duplicate blocked. |
| Likely cause | No current payload, stale preview, Discord client unavailable, adapter contract unhealthy, trust approval missing. |
| Debug command/log | Chat response debug payload, relay trace, `/settings` relay flags. |
| Fix | Refresh preview, ensure current selection/workspace item exists, approve dispatch, verify local Discord client session. |
| Source area | `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/discord_relay/adapters.py`, `src/stormhelm/core/trust/service.py` |

Tests: `tests/test_discord_relay.py`

## Screen-Awareness Answer Looks Overconfident

| Field | Details |
|---|---|
| Symptom | Screen response omits limitations or treats clipboard as live screen. |
| Likely cause | Observation/provenance regression or response composer bug. |
| Debug command/log | Screen response debug payload and truthfulness audit. |
| Fix | Restore source-channel distinction, limitations, and confidence reporting. |
| Source area | `src/stormhelm/core/screen_awareness/observation.py`, `src/stormhelm/core/screen_awareness/service.py`, `src/stormhelm/core/screen_awareness/verification.py` |

Tests: `tests/test_screen_awareness_phase12.py`, `tests/test_screen_awareness_verification.py`
