# Testing And Evaluation

Stormhelm has unit, integration, UI bridge, QML, subsystem, safety, and route-evaluation tests. Use focused runs while developing, then a full suite before publishing.

## Full Suite

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

When import paths are suspicious, pin the local source tree:

```powershell
$env:PYTHONPATH = "C:\Stormhelm\src"
.\.venv\Scripts\python.exe -m pytest -q
```

Sources: `pyproject.toml`, `tests/conftest.py`
Tests: all files under `tests/`

## Test Families

| Family | Purpose | Command | Sources covered |
|---|---|---|---|
| Config/startup | Config loader, launcher, lifecycle, runtime state. | `.\.venv\Scripts\python.exe -m pytest tests/test_config_loader.py tests/test_launcher.py tests/test_runtime_state.py tests/test_lifecycle_service.py -q` | `src/stormhelm/config`, `src/stormhelm/app`, `src/stormhelm/core/lifecycle` |
| Core container/API | Container wiring, snapshots, events. | `.\.venv\Scripts\python.exe -m pytest tests/test_core_container.py tests/test_events.py tests/test_snapshot_resilience.py -q` | `src/stormhelm/core/container.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/core/events.py` |
| Jobs/tools/safety | Tool registry, executor, jobs, safety policy. | `.\.venv\Scripts\python.exe -m pytest tests/test_tool_registry.py tests/test_job_manager.py tests/test_safety.py -q` | `src/stormhelm/core/tools`, `src/stormhelm/core/jobs`, `src/stormhelm/core/safety` |
| Planner/routing | Planner behavior and assistant orchestration. | `.\.venv\Scripts\python.exe -m pytest tests/test_planner.py tests/test_planner_command_routing_state.py tests/test_assistant_orchestrator.py -q` | `src/stormhelm/core/orchestrator` |
| Browser routes | Destination/direct-domain/search resolution. | `.\.venv\Scripts\python.exe -m pytest tests/test_browser_destination_resolution.py -q` | `src/stormhelm/core/orchestrator/browser_destinations.py` |
| Fuzzy evaluation | Fuzzy utterance route correctness. | `.\.venv\Scripts\python.exe -m pytest tests/test_fuzzy_language_evaluation.py -q` | `src/stormhelm/core/orchestrator/fuzzy_eval` |
| UI bridge/QML | Bridge contracts, QML shell, controller/client. | `.\.venv\Scripts\python.exe -m pytest tests/test_ui_bridge.py tests/test_qml_shell.py tests/test_main_controller.py tests/test_ui_client_streaming.py -q` | `src/stormhelm/ui`, `assets/qml` |
| Calculations | Local math parser/evaluator/helpers. | `.\.venv\Scripts\python.exe -m pytest tests/test_calculations.py -q` | `src/stormhelm/core/calculations` |
| Screen awareness | Observation, action, verification, grounding, problem solving. | `.\.venv\Scripts\python.exe -m pytest tests/test_screen_awareness_service.py tests/test_screen_awareness_action.py tests/test_screen_awareness_verification.py -q` | `src/stormhelm/core/screen_awareness` |
| Software control/recovery | Software plan, verification, approval/recovery handoff. | `.\.venv\Scripts\python.exe -m pytest tests/test_software_control.py tests/test_assistant_software_control.py tests/test_software_recovery.py -q` | `src/stormhelm/core/software_control`, `src/stormhelm/core/software_recovery` |
| Discord relay | Alias/payload/preview/dispatch boundaries. | `.\.venv\Scripts\python.exe -m pytest tests/test_discord_relay.py -q` | `src/stormhelm/core/discord_relay` |
| Voice | Config, availability, manual/audio turns, STT/TTS, capture, playback, events, diagnostics, UI bridge state. | `.\.venv\Scripts\python.exe -m pytest tests/test_voice_config.py tests/test_voice_availability.py tests/test_voice_state.py tests/test_voice_events.py -q` | `src/stormhelm/core/voice`, `src/stormhelm/ui/bridge.py` |
| Trust/tasks/memory/workspace | Durable state and retrieval. | `.\.venv\Scripts\python.exe -m pytest tests/test_trust_service.py tests/test_task_graph.py tests/test_semantic_memory.py tests/test_workspace_service.py -q` | `src/stormhelm/core/trust`, `core/tasks`, `core/memory`, `core/workspace` |
| System/network/telemetry | Native/system state and diagnostics. | `.\.venv\Scripts\python.exe -m pytest tests/test_system_probe.py tests/test_network_monitor.py tests/test_network_analysis.py tests/test_hardware_telemetry.py -q` | `src/stormhelm/core/system`, `core/network` |

## Command / Fuzzy Evaluation

Tracked fuzzy evaluation support:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_fuzzy_language_evaluation.py -q
```

Route correctness tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_planner.py tests/test_planner_phase3c.py tests/test_planner_structured_pipeline.py -q
```

Active worktree note: additional command-evaluation and planner-v2 files may exist locally but were not all listed by `git ls-files` during this documentation rewrite. Treat those as active development until intentionally added.

Sources: `src/stormhelm/core/orchestrator/fuzzy_eval/corpus.py`, `src/stormhelm/core/orchestrator/fuzzy_eval/runner.py`, `src/stormhelm/core/orchestrator/planner.py`
Tests: `tests/test_fuzzy_language_evaluation.py`, `tests/test_planner.py`

## Route Correctness Testing

Route tests should cover:

- Correct route family.
- Wrong-route near misses.
- Deictic/follow-up context.
- Provider fallback blocking when native route owns the request.
- Clarification when evidence is insufficient.
- Route state and UI command-surface metadata.

Sources: `src/stormhelm/core/orchestrator/planner.py`, `src/stormhelm/core/orchestrator/planner_models.py`, `src/stormhelm/ui/command_surface_v2.py`
Tests: `tests/test_planner.py`, `tests/test_planner_command_routing_state.py`, `tests/test_command_surface.py`

## Truthfulness / Verification Testing

Use these suites when changing claims, verification, or safety boundaries:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_calculations.py tests/test_screen_awareness_verification.py tests/test_software_control.py tests/test_discord_relay.py tests/test_trust_service.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_voice_availability.py tests/test_voice_core_bridge_contracts.py tests/test_voice_capture_service.py tests/test_voice_playback_service.py -q
```

Truthfulness checks should verify:

- Prepared-only work is not labeled completed.
- Discord delivery is not claimed without dispatch/verification evidence.
- Screen responses expose source limitations.
- Software install/update/uninstall/repair stays approval-gated.
- Recovery results remain unverified unless checked.
- Voice disabled/unavailable modes are reported truthfully.
- TTS artifact generation is not described as audible playback.
- Voice providers do not bypass core routing, trust, or safety boundaries.

Sources: `src/stormhelm/core/calculations/models.py`, `src/stormhelm/core/screen_awareness/models.py`, `src/stormhelm/core/software_control/models.py`, `src/stormhelm/core/discord_relay/models.py`, `src/stormhelm/core/trust/models.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/service.py`
Tests: `tests/test_calculations.py`, `tests/test_screen_awareness_verification.py`, `tests/test_software_control.py`, `tests/test_discord_relay.py`, `tests/test_trust_service.py`, `tests/test_voice_availability.py`, `tests/test_voice_core_bridge_contracts.py`

## UI Bridge Contract Tests

Run after changing bridge, command surface, route metadata, stream payloads, software/trust cards, or QML properties:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_ui_bridge.py `
  tests/test_ui_bridge_authority_contracts.py `
  tests/test_ui_bridge_software_contracts.py `
  tests/test_ui_client_streaming.py `
  tests/test_voice_ui_state_payload.py `
  tests/test_command_surface.py `
  -q
```

Sources: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/command_surface_v2.py`, `src/stormhelm/ui/voice_surface.py`
Tests: listed above

## QML Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_qml_shell.py tests/test_shader_assets.py -q
```

QML tests are the first stop for component load issues, property mismatches, shader asset problems, and shell regressions.

Sources: `assets/qml/Main.qml`, `assets/qml/components/*.qml`, `assets/qml/shaders/*.frag`
Tests: `tests/test_qml_shell.py`, `tests/test_shader_assets.py`

## Golden Fixtures

No separate golden-fixture directory was identified in the tracked tree during this rewrite. The route/eval cases appear to be code/test-driven.

Sources: `tests/`, `src/stormhelm/core/orchestrator/fuzzy_eval`
Tests: `tests/test_fuzzy_language_evaluation.py`

## Known Failing Or Flaky Tests

No current failing/flaky list is committed in the new docs. If a test is known-red, document it here with:

- exact command
- observed failure
- root cause or suspected source area
- date observed
- whether the failure was accepted for a publish

Do not silently weaken tests to make a route or UI claim pass.

Sources: `tests/`
Tests: Not applicable

## Docs Checks

Basic source-reference check:

```powershell
$docs = Get-ChildItem docs -Filter *.md -Recurse
$paths = Select-String -Path $docs.FullName -Pattern '`([^`]+)`' -AllMatches |
  ForEach-Object { $_.Matches.Value.Trim('`') } |
  Where-Object { $_ -match '^(src|tests|config|scripts|assets|docs|pyproject\.toml|README\.md)' } |
  Sort-Object -Unique
$missing = foreach ($path in $paths) { if (-not (Test-Path $path)) { $path } }
$missing
```

This is a blunt check. It will not validate wildcard references like `assets/qml/components/*.qml`.
