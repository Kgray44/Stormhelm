# Subsystems

Subsystems own bounded behavior behind planner routes. They should publish truthful status, expose typed inputs/outputs, and avoid claiming work they did not execute or verify.

## Calculations

| Area | Details |
|---|---|
| Purpose | Deterministic local arithmetic and engineering-style helper calculations. |
| Entry points | Planner route, `CalculationsSubsystem.handle_request()`, screen-aware calculation helper. |
| Inputs | Operator text, normalized text, caller context, output mode, optional provenance. |
| Outputs | `CalculationResponse`, result/failure, trace, explanation, verification, response contract. |
| Owned state | Recent in-memory traces. |
| Planner integration | `CalculationsPlannerSeam` detects expressions and follow-ups. |
| UI integration | Route/result state and command card metadata. |
| Trust/safety | No external calls or destructive actions. |
| Verification | Local deterministic verification metadata; unsupported math fails explicitly. |
| Telemetry | Debug traces and status snapshot. |
| Sources | `src/stormhelm/core/calculations/service.py`, `src/stormhelm/core/calculations/planner.py`, `src/stormhelm/core/calculations/models.py`, `src/stormhelm/core/calculations/helpers.py` |
| Tests | `tests/test_calculations.py` |

## Screen Awareness

| Area | Details |
|---|---|
| Purpose | Native/context observation, interpretation, grounding, guidance, verification, workflow continuity, and gated actions. |
| Entry points | Planner route, `ScreenAwarenessSubsystem.handle_request()`, Discord relay disambiguation, screen calculation flow. |
| Inputs | Operator text, surface mode, active module/context, workspace context, native observation, optional provider. |
| Outputs | `ScreenResponse`, limitations, truthfulness audit, action/verification/problem-solving/workflow results. |
| Owned state | Recent trace summaries, deterministic engines, adapter registry. |
| Planner integration | `ScreenAwarenessPlannerSeam` and planner route family. |
| UI integration | Route inspector, command cards, screen-aware result state. |
| Trust/safety | `action_policy_mode=confirm_before_act` by default; restricted domains guarded. |
| Verification | Deterministic verification engine; reports weak/ambiguous evidence. |
| Telemetry | Status snapshot includes capabilities, policy state, hardening, runtime hooks. |
| Sources | `src/stormhelm/core/screen_awareness/service.py`, `src/stormhelm/core/screen_awareness/models.py`, `src/stormhelm/core/screen_awareness/observation.py`, `src/stormhelm/core/screen_awareness/action.py`, `src/stormhelm/core/screen_awareness/verification.py` |
| Tests | `tests/test_screen_awareness_service.py`, `tests/test_screen_awareness_action.py`, `tests/test_screen_awareness_verification.py`, `tests/test_screen_awareness_phase12.py` |

## Software Control

| Area | Details |
|---|---|
| Purpose | Typed software target resolution, source selection, operation planning, verification, launch, and recovery handoff. |
| Entry points | Planner route, `SoftwareControlSubsystem.execute_software_operation()`. |
| Inputs | Operation type, target name, request stage, approval state, session/active module. |
| Outputs | `SoftwareControlResponse`, operation plan/result, verification result, trace, active request state. |
| Owned state | Recent software traces. |
| Planner integration | `SoftwareControlPlannerSeam`, catalog target resolution. |
| UI integration | Software cards, approval prompts, recovery state, route inspector. |
| Trust/safety | Install/update/uninstall/repair require confirmation unless unsafe test mode is enabled. Privileged operations disabled by default. |
| Verification | Local executable probing for verify; prepared-only plans are marked unverified. |
| Telemetry | Status snapshot and debug events. |
| Sources | `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/software_control/planner.py`, `src/stormhelm/core/software_control/catalog.py`, `src/stormhelm/core/software_control/models.py` |
| Tests | `tests/test_software_control.py`, `tests/test_assistant_software_control.py`, `tests/test_ui_bridge_software_contracts.py` |

## Software Recovery

| Area | Details |
|---|---|
| Purpose | Classify software-control failures and prepare bounded recovery steps. |
| Entry points | Software-control handoff and recovery service calls. |
| Inputs | Failure event, operation plan, verification payload, local signals. |
| Outputs | Recovery plan, hypotheses, route switch candidate, result, verification status. |
| Owned state | Recent recovery traces. |
| Planner integration | Invoked after software failures rather than as a broad chat fallback. |
| UI integration | Recovery summaries and route-state support entries. |
| Trust/safety | Redacts diagnostic context before optional cloud fallback. |
| Verification | Recovery results are `unverified` until another check confirms state. |
| Telemetry | Status snapshot with cloud fallback disposition and recent trace. |
| Sources | `src/stormhelm/core/software_recovery/service.py`, `src/stormhelm/core/software_recovery/models.py`, `src/stormhelm/core/software_recovery/cloud.py` |
| Tests | `tests/test_software_recovery.py` |

## Discord Relay

| Area | Details |
|---|---|
| Purpose | Preview and optionally dispatch supported payloads to trusted Discord destinations. |
| Entry points | Planner route, `DiscordRelaySubsystem.handle_request()`. |
| Inputs | Destination alias, active/workspace context, payload hint, request stage, pending preview, trust decision. |
| Outputs | `DiscordRelayResponse`, preview, attempt, trace, active request state, adapter execution metadata. |
| Owned state | Recent traces, recent dispatch fingerprints, trusted/session aliases. |
| Planner integration | Route family and pending preview/dispatch active request state. |
| UI integration | Preview cards, approval prompts, stale/duplicate state, route inspector. |
| Trust/safety | Preview before send, trust approval before dispatch, duplicate suppression, secret-pattern policy block. |
| Verification | Local client route has limited focus/send verification; no false delivery claims. |
| Telemetry | Status snapshot and dispatch traces. |
| Sources | `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/discord_relay/adapters.py`, `src/stormhelm/core/discord_relay/models.py` |
| Tests | `tests/test_discord_relay.py` |

## Voice

| Area | Details |
|---|---|
| Purpose | Bounded voice input/output surface for manual turns, controlled audio STT, controlled TTS artifacts, explicit capture, playback boundaries, diagnostics, and events. |
| Entry points | `VoiceService`, `/voice/capture/start`, `/voice/capture/stop`, `/voice/capture/cancel`, `/voice/capture/submit`, `/voice/capture/turn`, `/voice/playback/stop`, UI bridge voice actions. |
| Inputs | Manual transcript text, controlled audio metadata, capture/playback control requests, provider configuration, OpenAI key/config when enabled. |
| Outputs | `VoiceTurnResult`, transcription/synthesis/capture/playback results, voice status snapshot, events, UI voice state. |
| Owned state | In-memory voice runtime state and recent diagnostics; captured/generated audio is transient by default. |
| Planner integration | Voice-derived text re-enters the core bridge/orchestrator path. Capture/playback controls are action surfaces, not planner-owned command authority. |
| UI integration | Ghost/Deck voice state and explicit controls through `UiBridge`, `CoreApiClient`, and `MainController`. |
| Trust/safety | Disabled by default. No wake word, always-listening, Realtime, VAD, direct provider tool execution, or trust bypass. Capture/playback have separate gates. |
| Verification | Availability and action results report blocked/unavailable/provider states; playback does not prove the user heard audio. |
| Telemetry | Voice events, diagnostics, and `/status` voice snapshot. |
| Sources | `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/events.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py` |
| Tests | `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_manual_turn.py`, `tests/test_voice_audio_turn.py`, `tests/test_voice_events.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_playback_service.py`, `tests/test_voice_core_bridge_contracts.py` |

## Trust

| Area | Details |
|---|---|
| Purpose | Approval requests, grants, expiration, invalidation, and audit records for sensitive actions. |
| Entry points | Safety policy, software control, Discord relay, trust route handling. |
| Inputs | `TrustActionRequest`, approval/denial decisions, scopes, task/session/runtime binding. |
| Outputs | `TrustDecision`, active request state, grants, audit records, posture summary. |
| Owned state | SQLite trust tables. |
| Planner integration | Pending approvals and follow-up approval utterances. |
| UI integration | Approval prompts and trust state in command surface. |
| Trust/safety | This is the trust boundary. |
| Verification | Expiry/runtime/task binding checks keep grants from becoming stale authority. |
| Telemetry | Approval events and audit records. |
| Sources | `src/stormhelm/core/trust/service.py`, `src/stormhelm/core/trust/models.py`, `src/stormhelm/core/trust/repository.py` |
| Tests | `tests/test_trust_service.py` |

## Durable Tasks

| Area | Details |
|---|---|
| Purpose | Track multi-step work, blockers, evidence, checkpoints, artifacts, job links, and resume summaries. |
| Entry points | Assistant execution plans, job manager callbacks, trust/software/recovery signals, continuity routes. |
| Inputs | Prompt, tool requests, job events, verification summaries, trust events. |
| Outputs | Task records, active summary, "where left off", next steps, watch task list. |
| Owned state | SQLite task graph tables and task memory sync. |
| Planner integration | Task continuity and resume requests. |
| UI integration | Continuity cards, workspace/watch surfaces. |
| Trust/safety | Tracks trust pending/granted/denied as task blockers/evidence. |
| Verification | Records verification summaries but does not invent success. |
| Telemetry | Task status in snapshot/status. |
| Sources | `src/stormhelm/core/tasks/service.py`, `src/stormhelm/core/tasks/models.py`, `src/stormhelm/core/tasks/repository.py` |
| Tests | `tests/test_task_graph.py`, `tests/test_snapshot_resilience.py` |

## Workspace

| Area | Details |
|---|---|
| Purpose | Save, restore, assemble, list, rename, tag, archive, and summarize workspaces and opened items. |
| Entry points | Workspace tools, UI bridge workspace actions, `/workspace` commands. |
| Inputs | Workspace id/title/items/state, note links, activity. |
| Outputs | Workspace records, snapshots, active canvas state, continuity summaries. |
| Owned state | SQLite workspace tables. |
| Planner integration | Workspace operation route family and continuity support. |
| UI integration | Workspace rail/canvas/opened items. |
| Trust/safety | Clear/archive actions are trust-gated. File reads/opens are safety-gated. |
| Verification | Persistence result and stored snapshots. |
| Telemetry | Status/snapshot workspace sections. |
| Sources | `src/stormhelm/core/workspace/service.py`, `src/stormhelm/core/workspace/models.py`, `src/stormhelm/core/workspace/repository.py`, `src/stormhelm/core/tools/builtins/workspace_memory.py` |
| Tests | `tests/test_workspace_service.py` |

## Semantic Memory

| Area | Details |
|---|---|
| Purpose | Store and retrieve local memory records with family, provenance, freshness, confidence, and suppression metadata. |
| Entry points | Memory service, task sync, context recall routes. |
| Inputs | Memory content, scope, metadata, query text. |
| Outputs | Ranked records, query log, suppressed previews, freshness annotations. |
| Owned state | SQLite memory tables. |
| Planner integration | Context recall and continuity support. |
| UI integration | Command surface memory summaries. |
| Trust/safety | Local storage; external vector service is not configured by default. |
| Verification | Heuristic local retrieval; should report uncertainty. |
| Telemetry | Memory status snapshot. |
| Sources | `src/stormhelm/core/memory/service.py`, `src/stormhelm/core/memory/models.py`, `src/stormhelm/core/memory/database.py` |
| Tests | `tests/test_semantic_memory.py` |

## Lifecycle

| Area | Details |
|---|---|
| Purpose | Track install/runtime/startup/shell/tray state, lifecycle holds, cleanup, restart policy, and backend shutdown. |
| Entry points | Lifecycle API endpoints, UI client/controller, startup scripts. |
| Inputs | Shell presence, startup policy mutations, cleanup target requests, resolution requests. |
| Outputs | Lifecycle snapshot, cleanup plan/result, startup commands, hold/resolution state. |
| Owned state | Runtime JSON state under configured state dir. |
| Planner integration | Runtime/watch/lifecycle route surfaces. |
| UI integration | Tray, status, Systems views, recovery controls. |
| Trust/safety | Cleanup execution requires confirmation details. Startup mutations are explicit API actions. |
| Verification | Startup registry probe/mutator state and shell heartbeat state. |
| Telemetry | Lifecycle events and status snapshot. |
| Sources | `src/stormhelm/core/lifecycle/service.py`, `src/stormhelm/core/lifecycle/models.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/controllers/main_controller.py` |
| Tests | `tests/test_lifecycle_service.py`, `tests/test_ui_lifecycle_bridge.py`, `tests/test_main_controller_lifecycle.py` |

## System / Network / Operations

| Area | Details |
|---|---|
| Purpose | Local machine, power, resource, storage, network, app/window/system control, operational diagnostics. |
| Entry points | Built-in tools, planner route families, status snapshots. |
| Inputs | Tool arguments, system probe state, network monitor samples. |
| Outputs | Tool results, diagnostics, active apps/windows, network status/throughput/diagnosis. |
| Owned state | Network monitor runtime state and operational awareness snapshots. |
| Planner integration | System route families and tool plans. |
| UI integration | Systems/watch/status panels. |
| Trust/safety | Control actions are trust-gated; status tools are read-only. |
| Verification | Native result payloads and failure reasons where available. |
| Telemetry | Status/snapshot and event stream. |
| Sources | `src/stormhelm/core/tools/builtins/system_state.py`, `src/stormhelm/core/system/probe.py`, `src/stormhelm/core/network/monitor.py`, `src/stormhelm/core/operations/service.py` |
| Tests | `tests/test_system_probe.py`, `tests/test_network_monitor.py`, `tests/test_network_analysis.py`, `tests/test_operational_awareness.py` |

## Provider Layer

| Area | Details |
|---|---|
| Purpose | Optional OpenAI Responses API fallback behind a provider abstraction. |
| Entry points | Assistant provider fallback when enabled/configured. |
| Inputs | Messages, model settings, tool definitions/results. |
| Outputs | Provider text and tool calls. |
| Owned state | Provider call audit files when audit is enabled by environment. |
| Planner integration | Should be fallback, not the owner of native-capable route families. |
| UI integration | Assistant response only. |
| Trust/safety | Requires API key and sends prompt data externally when enabled. |
| Verification | Provider responses are not local verification. |
| Telemetry | Provider audit hooks. |
| Sources | `src/stormhelm/core/providers/base.py`, `src/stormhelm/core/providers/openai_responses.py`, `src/stormhelm/core/providers/audit.py` |
| Tests | `tests/test_config_loader.py`, `tests/test_command_eval_provider_audit.py` |
