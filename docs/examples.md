# Examples

These examples describe current implemented behavior and its limits.

## Quick Ghost Mode Request

Request:

```text
what time is it
```

Expected flow:

1. Ghost captures text and submits it through `UiBridge`.
2. Core receives `/chat/send`.
3. Legacy command/planner chooses a local time route.
4. Result is rendered as a short Ghost response.

Expected result state: completed local tool response.

Sources: `src/stormhelm/ui/ghost_input.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/core/orchestrator/router.py`, `src/stormhelm/core/tools/builtins/clock.py`
Tests: `tests/test_ghost_input.py`, `tests/test_assistant_orchestrator.py`, `tests/test_tool_registry.py`

## Command Deck Workspace

Request:

```text
where did we leave off
```

Expected flow:

1. Command Deck submits request.
2. Planner routes to continuity/workspace/task state.
3. Durable task/workspace services return persisted summary when available.
4. Deck renders continuity and workspace context.

Expected result state: completed if durable state exists; truthful empty/uncertain state if not.

Sources: `assets/qml/components/CommandDeckShell.qml`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/core/tasks/service.py`, `src/stormhelm/core/workspace/service.py`
Tests: `tests/test_task_graph.py`, `tests/test_workspace_service.py`, `tests/test_ui_bridge.py`

## Software Install Dry-Run / Planning

Request:

```text
install firefox
```

Expected flow:

1. Planner routes to software control.
2. Catalog target is resolved if known.
3. Sources are discovered from configured package-manager/vendor/browser-guided routes.
4. A plan is built with checkpoints.
5. Trust approval is requested before execution.
6. If execution adapter is unavailable, response hands off to recovery rather than claiming install success.

Expected result state: prepared / needs approval / possibly recovery handoff. Not completed unless execution and verification actually happen.

Sources: `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/software_control/catalog.py`, `src/stormhelm/core/trust/service.py`, `src/stormhelm/core/software_recovery/service.py`
Tests: `tests/test_software_control.py`, `tests/test_assistant_software_control.py`, `tests/test_software_recovery.py`

## Calculation

Request:

```text
what is 18 * 42
```

Expected flow:

1. Planner routes to calculations.
2. Expression is normalized and parsed locally.
3. Evaluator returns a decimal result.
4. Formatter builds a concise response.
5. Trace/verification metadata is attached.

Expected result state: completed deterministic calculation.

Sources: `src/stormhelm/core/calculations/planner.py`, `src/stormhelm/core/calculations/service.py`, `src/stormhelm/core/calculations/parser.py`, `src/stormhelm/core/calculations/evaluator.py`
Tests: `tests/test_calculations.py`

## Screen-Awareness Question

Request:

```text
what am I looking at
```

Expected flow:

1. Planner routes to screen awareness when enabled.
2. Native/current context observation runs.
3. Deterministic interpretation and response composer produce a summary.
4. Limitations/confidence are included when evidence is weak.

Expected result state: completed with evidence, or uncertain/limited if observation is unavailable.

Sources: `src/stormhelm/core/screen_awareness/service.py`, `src/stormhelm/core/screen_awareness/observation.py`, `src/stormhelm/core/screen_awareness/interpretation.py`, `src/stormhelm/core/screen_awareness/response.py`
Tests: `tests/test_screen_awareness_service.py`, `tests/test_screen_awareness_phase12.py`

## Screen-Aware Action Requiring Confirmation

Request:

```text
click the submit button
```

Expected flow:

1. Planner routes to screen awareness action.
2. Target grounding tries to identify the visible control.
3. Action policy checks `confirm_before_act`.
4. If confirmation is required, Stormhelm returns gated state instead of clicking.
5. Verification runs only after an attempted action.

Expected result state: needs approval/gated by default.

Sources: `config/default.toml`, `src/stormhelm/core/screen_awareness/action.py`, `src/stormhelm/core/screen_awareness/service.py`, `src/stormhelm/core/screen_awareness/verification.py`
Tests: `tests/test_screen_awareness_action.py`, `tests/test_screen_awareness_verification.py`

## Discord Relay Preview

Request:

```text
send this to Baby
```

Expected flow:

1. Relay resolves trusted alias `Baby`.
2. Payload candidates are collected from active selection, active workspace item, clipboard, and recent entities.
3. If `this` requires current context, stale recent candidates are suppressed.
4. Preview is built with fingerprint/provenance.
5. Trust prompt is attached.
6. Dispatch only happens after approval and valid pending preview.

Expected result state: ready / needs approval. Not sent during preview.

Sources: `config/default.toml`, `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/discord_relay/models.py`, `src/stormhelm/core/trust/service.py`
Tests: `tests/test_discord_relay.py`, `tests/test_trust_service.py`

## Discord Relay Dispatch

Follow-up after a valid preview:

```text
approve once and send it
```

Expected flow:

1. Trust service resolves the pending approval request.
2. Preview is revalidated against TTL/fingerprint/context.
3. Duplicate-send guard runs.
4. Adapter contract is checked.
5. Local Discord adapter attempts navigation/send.
6. Response reports stage-specific result; no false delivery claim.

Expected result state: completed only if adapter attempt does not fail; verification strength may still be limited.

Sources: `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/discord_relay/adapters.py`, `src/stormhelm/core/adapters/contracts.py`, `src/stormhelm/core/trust/service.py`
Tests: `tests/test_discord_relay.py`, `tests/test_adapter_contracts.py`

## Voice Push-To-Talk Status

Request:

```text
start voice capture
```

Expected flow:

1. UI or API sends an explicit voice capture action.
2. Core checks voice availability and capture gates.
3. `VoiceService` starts capture only when enabled and allowed.
4. Voice status/action result reports active, blocked, unavailable, or provider failure state.

Expected result state: blocked by default; active only when voice capture settings and provider dependencies allow it.

Sources: `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`
Tests: `tests/test_voice_availability.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_bridge_controls.py`

## Voice Turn From Controlled Audio

Request:

```text
submit captured voice
```

Expected flow:

1. Explicit capture or controlled audio metadata is submitted.
2. STT runs only when provider/config limits pass.
3. The transcript becomes a voice-originated core request.
4. The normal orchestrator/planner path handles the request.
5. Optional TTS/playback stays separate and does not change command authority.

Expected result state: completed only if transcription and core handling complete; otherwise blocked/failed/unavailable with provider or config reason.

Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/bridge.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/orchestrator/assistant.py`
Tests: `tests/test_voice_audio_turn.py`, `tests/test_voice_core_bridge_contracts.py`, `tests/test_voice_stt_provider.py`

## Recovery Flow

Request after failed software route:

```text
try another safe route
```

Expected flow:

1. Software control passes failure category/context to recovery.
2. Recovery builds local hypotheses.
3. Redaction runs before optional cloud fallback.
4. Recovery returns bounded plan and route-switch candidate.
5. Result remains unverified until a follow-up check confirms state.

Expected result state: recovery prepared / unverified.

Sources: `src/stormhelm/core/software_recovery/service.py`, `src/stormhelm/core/software_recovery/cloud.py`, `src/stormhelm/core/software_control/service.py`
Tests: `tests/test_software_recovery.py`, `tests/test_software_control.py`

## Approval-Required Action

Request:

```text
clear this workspace
```

Expected flow:

1. Planner/tool route identifies workspace clear.
2. Safety policy sees trust-gated action.
3. Trust service creates or reuses pending approval request.
4. UI renders approval prompt.
5. Action runs only after valid approval.

Expected result state: needs approval before execution.

Sources: `src/stormhelm/core/safety/policy.py`, `src/stormhelm/core/trust/service.py`, `src/stormhelm/core/tools/builtins/workspace_memory.py`, `src/stormhelm/ui/command_surface_v2.py`
Tests: `tests/test_safety.py`, `tests/test_trust_service.py`, `tests/test_workspace_service.py`

## Ambiguous Request Requiring Clarification

Request:

```text
send this to Baby
```

Context: multiple equally plausible current payload candidates.

Expected behavior:

- Stormhelm asks which payload to send.
- It lists choices when available.
- It does not choose a payload just to avoid asking.

Sources: `src/stormhelm/core/discord_relay/service.py`
Tests: `tests/test_discord_relay.py`

## Unsupported Request Handled Truthfully

Request:

```text
turn on always-listening voice mode
```

Expected behavior:

- Stormhelm should say always-listening is not implemented.
- It can point to the bounded voice user guide and explain that voice is disabled by default.
- It should not start microphone capture unless an explicit capture action and capture gates allow it.
- It should not imply wake word, Realtime, VAD, or continuous microphone behavior.

Sources: `docs/voice.md`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/service.py`, `docs/roadmap.md`
Tests: `tests/test_voice_availability.py`, `tests/test_voice_capture_service.py`

## OpenAI Provider Fallback

Request:

```text
answer this with the provider
```

Expected behavior with default config:

- Provider fallback is unavailable because OpenAI is disabled.
- Stormhelm should say it needs provider configuration if the request requires it.

Enablement example:

```powershell
$env:STORMHELM_OPENAI_ENABLED = "true"
$env:OPENAI_API_KEY = "<your key>"
.\scripts\run_core.ps1
```

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/providers/openai_responses.py`
Tests: `tests/test_config_loader.py`, `tests/test_command_eval_provider_audit.py`
