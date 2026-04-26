# Usage Workflows

## First Run From Source

```powershell
cd C:\Stormhelm
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev,packaging]
```

Start the core:

```powershell
.\scripts\run_core.ps1
```

Start the UI:

```powershell
.\scripts\run_ui.ps1
```

Confirm the core is alive:

```powershell
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/settings
```

Sources: `scripts/run_core.ps1`, `scripts/run_ui.ps1`, `src/stormhelm/core/api/app.py`, `src/stormhelm/config/loader.py`  
Tests: `tests/test_config_loader.py`, `tests/test_launcher.py`

## Launching Stormhelm

For development, use the scripts because they set `PYTHONPATH=src` and the expected working directory:

```powershell
.\scripts\run_core.ps1
.\scripts\run_ui.ps1
```

For a combined developer launch:

```powershell
.\scripts\dev_launch.ps1
```

Installed console scripts are declared as:

```powershell
stormhelm-core
stormhelm-ui
stormhelm-telemetry-helper
```

Sources: `pyproject.toml`, `scripts/dev_launch.ps1`, `src/stormhelm/entrypoints/core.py`, `src/stormhelm/entrypoints/ui.py`, `src/stormhelm/entrypoints/telemetry_helper.py`  
Tests: `tests/test_launcher.py`

## Using Ghost Mode

Default shortcut:

```text
Ctrl+Space
```

Workflow:

1. Press `Ctrl+Space`.
2. Type a short request.
3. Press `Enter` to send or `Esc` to cancel.

Examples:

```text
what time is it
what is 18 * 42
open youtube history
send this to Baby
```

Ghost is a quick request and response surface. It renders backend state from `UiBridge`, command-surface models, stream events, and chat results. It does not own execution decisions.

Sources: `src/stormhelm/ui/ghost_input.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/command_surface_v2.py`, `assets/qml/components/GhostShell.qml`, `assets/qml/components/SignalStrip.qml`  
Tests: `tests/test_ghost_input.py`, `tests/test_ghost_adaptive.py`, `tests/test_ui_bridge.py`, `tests/test_command_surface.py`

## Using Command Deck

Command Deck is for longer work: route inspection, workspace context, opened pages/files, notes, diagnostics, layout, and status panels.

Typical flow:

```text
open this in the deck
show network status
where did we leave off
show the route
```

The Deck can:

- Submit messages through `stormhelmBridge.sendMessage`.
- Open and close workspace items.
- Render browser/file surfaces.
- Save notes.
- Change deck layout locally.
- Display route inspector and command surface state.

It should not:

- Invent backend success.
- Execute destructive actions without core/trust approval.
- Treat UI-only preview state as proof that a backend action happened.

Sources: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/controllers/main_controller.py`, `assets/qml/Main.qml`, `assets/qml/components/CommandDeckShell.qml`, `assets/qml/components/DeckPanelWorkspace.qml`, `assets/qml/components/RouteInspectorSurface.qml`  
Tests: `tests/test_main_controller.py`, `tests/test_ui_bridge_authority_contracts.py`, `tests/test_qml_shell.py`

## Running Commands Through The API

Send a chat request:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/chat/send `
  -ContentType 'application/json' `
  -Body '{"message":"/time","session_id":"default","surface_mode":"deck","active_module":"helm"}'
```

Read recent events:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/events
```

Read a snapshot:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/snapshot
```

Sources: `src/stormhelm/core/api/app.py`, `src/stormhelm/core/api/schemas.py`, `src/stormhelm/core/orchestrator/assistant.py`  
Tests: `tests/test_assistant_orchestrator.py`, `tests/test_events.py`, `tests/test_snapshot_resilience.py`

## Software-Control Flows

Verify a known app:

```text
verify chrome is installed
```

Launch a known app:

```text
launch discord
```

Prepare an install plan:

```text
install firefox
```

Expected current behavior:

- Verification can probe local executable paths.
- Launch can use native app control when the adapter is available.
- Install/update/uninstall/repair builds a typed plan and asks for approval.
- Package-manager execution is not fully wired in this pass; the subsystem can hand off to software recovery instead of pretending success.

Sources: `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/software_control/catalog.py`, `src/stormhelm/core/software_control/planner.py`, `src/stormhelm/core/software_recovery/service.py`  
Tests: `tests/test_software_control.py`, `tests/test_assistant_software_control.py`, `tests/test_software_recovery.py`

## Calculation Examples

```text
what is 18 * 42
calculate 12.5% of 480
what is the voltage divider for 10k and 5k on 12v
what is the parallel resistance of 10k and 10k
```

The calculation subsystem runs locally with deterministic parsing, helpers, explanations, traces, and verification metadata. Unsupported or ambiguous requests return structured failures.

Sources: `src/stormhelm/core/calculations/service.py`, `src/stormhelm/core/calculations/helpers.py`, `src/stormhelm/core/calculations/parser.py`, `src/stormhelm/core/calculations/evaluator.py`  
Tests: `tests/test_calculations.py`

## Screen-Awareness Examples

```text
what am I looking at
what changed on the screen
why is this button disabled
solve the calculation on my screen
click the visible submit button
```

Expected current behavior:

- Stormhelm prefers native/current visible context when available.
- Clipboard-only evidence is not treated as the screen.
- Action requests are governed by `screen_awareness.action_policy_mode`.
- The default policy is `confirm_before_act`.
- Verification is deterministic and evidence-limited; it will say when the basis is weak.

Sources: `src/stormhelm/core/screen_awareness/service.py`, `src/stormhelm/core/screen_awareness/observation.py`, `src/stormhelm/core/screen_awareness/action.py`, `src/stormhelm/core/screen_awareness/verification.py`  
Tests: `tests/test_screen_awareness_service.py`, `tests/test_screen_awareness_action.py`, `tests/test_screen_awareness_verification.py`, `tests/test_screen_awareness_phase12.py`

## Discord Relay Preview

Default config includes one trusted alias:

```toml
[discord_relay.trusted_aliases.baby]
alias = "Baby"
route_mode = "local_client_automation"
```

Example:

```text
send this to Baby
```

Expected current behavior:

- Stormhelm resolves the trusted alias.
- It chooses a current payload from active selection, active workspace item, clipboard, or recent entities.
- It suppresses stale recent artifacts when the request says "this".
- It builds a preview with a fingerprint.
- It asks for trust approval before dispatch.
- Dispatch uses the local Discord client route when enabled and available.

Sources: `config/default.toml`, `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/discord_relay/adapters.py`, `src/stormhelm/core/trust/service.py`  
Tests: `tests/test_discord_relay.py`, `tests/test_trust_service.py`

## Safe / Dry-Run Behavior

Several paths prepare or preview before acting:

| Request type | Safe behavior |
|---|---|
| Software install/update/uninstall/repair | Plan and approval gate before execution. Current package-manager execution may hand off to recovery instead of running. |
| Discord relay | Preview, fingerprint, trust prompt, stale preview invalidation, duplicate suppression. |
| File reads | Allowed only under configured read directories. |
| File operations / workspace clear/archive | Trust-gated action tools. |
| Shell | Disabled stub by default. |
| Screen action | Confirm-before-act by default. |

Sources: `src/stormhelm/core/safety/policy.py`, `src/stormhelm/core/trust/service.py`, `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/screen_awareness/action.py`  
Tests: `tests/test_safety.py`, `tests/test_trust_service.py`, `tests/test_software_control.py`, `tests/test_discord_relay.py`, `tests/test_screen_awareness_action.py`

## Troubleshooting Flow

Start with live state:

```powershell
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/status
curl http://127.0.0.1:8765/snapshot
```

Then check focused areas:

```powershell
curl http://127.0.0.1:8765/settings
curl http://127.0.0.1:8765/tools
curl http://127.0.0.1:8765/events
```

Run focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config_loader.py tests/test_safety.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_ui_bridge.py tests/test_ui_client_streaming.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_planner.py tests/test_assistant_orchestrator.py -q
```

Sources: `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/client.py`, `tests/conftest.py`  
Tests: `tests/test_config_loader.py`, `tests/test_safety.py`, `tests/test_ui_bridge.py`, `tests/test_planner.py`
