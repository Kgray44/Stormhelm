# Data Model

This page documents the model families that matter for users, developers, and UI contract work. It is not a generated schema dump; use the source files for exact fields.

## Config Models

| Family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| `AppConfig` | Root runtime config. | App identity, network, storage, logging, concurrency, UI, lifecycle, event stream, location/weather, telemetry, screen awareness, calculations, software, recovery, trust, Discord, OpenAI, voice, safety, tools, runtime paths. | `load_config()` | Core container, UI, tools, subsystems. | Built from TOML/env at startup; not stored in SQLite. | `src/stormhelm/config/models.py`, `src/stormhelm/config/loader.py` | `tests/test_config_loader.py`, `tests/test_voice_config.py` |
| Section configs | Typed config for each subsystem. | Section-specific booleans, timeouts, TTLs, models, feature flags. | Config loader | Subsystem constructors. | Same as `AppConfig`. | `src/stormhelm/config/models.py`, `config/default.toml` | `tests/test_config_loader.py` |
| `RuntimePathConfig` | Resolved source/install/resource/user/state paths. | mode, frozen status, roots, assets, config, state/db/log/session paths. | Config loader | Core, UI, lifecycle, storage. | Derived at startup. | `src/stormhelm/config/models.py`, `src/stormhelm/shared/paths.py` | `tests/test_config_loader.py`, `tests/test_runtime_state.py` |

## API Payloads

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| `ChatRequest` | Submit assistant work. | message, session, surface, active module, workspace/input context, explicit requests. | UI/client/API callers. | `AssistantOrchestrator`. | User/assistant messages are persisted. | `src/stormhelm/core/api/schemas.py`, `src/stormhelm/core/api/app.py` | `tests/test_assistant_orchestrator.py` |
| `NoteCreateRequest` | Create note. | title, content, session/workspace. | UI/API callers. | Notes repository. | Stored in SQLite `notes`. | `src/stormhelm/core/api/schemas.py`, `src/stormhelm/core/memory/repositories.py` | `tests/test_storage.py` |
| Lifecycle request models | Mutate shell/startup/cleanup/lifecycle state. | Shell presence, startup policy, cleanup targets, confirmations. | UI/client/API callers. | Lifecycle controller. | Runtime JSON state and events. | `src/stormhelm/core/api/schemas.py`, `src/stormhelm/core/lifecycle/models.py` | `tests/test_lifecycle_service.py`, `tests/test_ui_lifecycle_bridge.py` |
| Voice control request models | Mutate explicit voice capture/playback state. | Capture source/session/action metadata, playback stop request metadata. | UI/client/API callers. | `VoiceService`. | Status and events are runtime state; audio persistence is disabled by default. | `src/stormhelm/core/api/schemas.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/models.py` | `tests/test_voice_bridge_controls.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_playback_service.py` |
| Response wrappers | Return jobs/events/notes. | Lists of model dictionaries. | FastAPI endpoints. | UI/client/API callers. | Source state lives in repositories or event buffer. | `src/stormhelm/core/api/schemas.py`, `src/stormhelm/core/api/app.py` | `tests/test_events.py`, `tests/test_storage.py` |

## Events

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| `EventRecord` | Typed event for runtime/diagnostics/UI. | id, timestamp, family, severity, visibility, retention, source, summary, payload, provenance. | Core services, tools, jobs, lifecycle, trust, subsystems. | `/events`, `/events/stream`, UI bridge. | In-memory bounded buffer; not the SQLite source of truth. | `src/stormhelm/core/events.py` | `tests/test_events.py`, `tests/test_ui_client_streaming.py` |
| `EventBuffer` | Bounded replay and stream coordination. | retention deque, replay limit, subscribers. | Core container. | FastAPI event endpoints and UI client. | In-memory per process. | `src/stormhelm/core/events.py`, `src/stormhelm/core/api/app.py` | `tests/test_events.py` |

## Jobs And Tools

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| `JobRecord` | Tracks tool execution lifecycle. | job id, status, tool name, args, session/task, timestamps, result/error/progress. | `JobManager`. | API, UI, tasks, events. | Persisted as tool run records and kept in memory history. | `src/stormhelm/core/jobs/models.py`, `src/stormhelm/core/jobs/manager.py` | `tests/test_job_manager.py` |
| `ToolDescriptor` / `ToolResult` | Tool registry and execution contract. | name, description, schema, safety classification, result payload/error. | Built-in tools and executor. | Planner/provider/jobs/safety. | Tool run results persisted through repository. | `src/stormhelm/core/tools/base.py`, `src/stormhelm/core/tools/registry.py`, `src/stormhelm/core/tools/executor.py` | `tests/test_tool_registry.py` |
| `SafetyDecision` | Safety authorization output. | allowed, reason, details, approval state, operator message. | `SafetyPolicy`. | Tool executor, software subsystem, UI route state. | Included in debug/metadata; trust decisions persist separately. | `src/stormhelm/shared/result.py`, `src/stormhelm/core/safety/policy.py` | `tests/test_safety.py` |

## Planner And Route Models

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Request/route models | Represent query shape, decomposition, target candidates, bindings, route candidates, winner posture, telemetry. | query shape, response mode, route posture, confidence, candidate metadata, deictic binding, unsupported/clarification reasons. | Planner. | Orchestrator, UI route inspector, command surface. | Included in chat metadata and UI snapshot; not a standalone DB table. | `src/stormhelm/core/orchestrator/planner_models.py`, `src/stormhelm/core/orchestrator/planner.py` | `tests/test_planner.py`, `tests/test_planner_command_routing_state.py` |
| Browser destination models | Resolve known destinations/search/direct domains. | destination kind, target URL/search plan/browser target. | Browser resolver. | Planner/open tools/UI actions. | Not persisted except resulting messages/workspace actions. | `src/stormhelm/core/orchestrator/browser_destinations.py` | `tests/test_browser_destination_resolution.py` |
| Fuzzy evaluation models | Evaluation cases/results for route correctness. | utterance, expected family, observed route, pass/fail metadata. | Eval runner/tests. | Tests/developers. | Test-only artifacts. | `src/stormhelm/core/orchestrator/fuzzy_eval/models.py` | `tests/test_fuzzy_language_evaluation.py` |

## Calculations

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Calculation request/trace/result | Deterministic math execution and evidence. | route disposition, input origin, normalized expression, output mode, result/failure, explanation, verification, trace. | Calculations planner/service. | Orchestrator, UI command surface, screen awareness. | Recent traces are in-memory; chat metadata may persist summaries. | `src/stormhelm/core/calculations/models.py`, `src/stormhelm/core/calculations/service.py` | `tests/test_calculations.py` |
| Parser AST | Safe arithmetic AST. | number/unary/binary nodes and tokens. | Parser. | Evaluator/explanations. | Not persisted. | `src/stormhelm/core/calculations/parser.py`, `src/stormhelm/core/calculations/evaluator.py` | `tests/test_calculations.py` |

## Screen Awareness

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Screen response/analysis | Represents observation, interpretation, grounding, guidance, limitations, truth state, recovery state, and response contract. | intent, source type, confidence, limitations, audit findings, latency trace, verification/action/continuity/problem-solving results. | `ScreenAwarenessSubsystem`. | Orchestrator/UI/tasks. | Recent trace summaries are in-memory; chat metadata can persist response/debug payload. | `src/stormhelm/core/screen_awareness/models.py`, `src/stormhelm/core/screen_awareness/service.py` | `tests/test_screen_awareness_service.py`, `tests/test_screen_awareness_phase12.py` |
| Verification/action models | Record action gates, execution status, comparison, evidence, completion state. | action status, gate reason, verification outcome, evidence channels, confidence. | Action/verification engines. | Screen subsystem/UI/tasks. | Not separately stored unless copied into task evidence/chat metadata. | `src/stormhelm/core/screen_awareness/action.py`, `src/stormhelm/core/screen_awareness/verification.py`, `src/stormhelm/core/screen_awareness/models.py` | `tests/test_screen_awareness_action.py`, `tests/test_screen_awareness_verification.py` |

## Software Control And Recovery

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Software operation models | Represent target, source, plan steps, operation result, verification, trace, response. | operation type, target, source route, trust level, checkpoints, execution/verification status, install state. | Software control service/planner/catalog. | Orchestrator/UI/trust/recovery. | Recent traces in-memory; response metadata can persist in chat/task evidence. | `src/stormhelm/core/software_control/models.py`, `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/software_control/catalog.py` | `tests/test_software_control.py`, `tests/test_assistant_software_control.py` |
| Recovery models | Represent failure event, hypotheses, plan, result, trace. | category, context, selected hypothesis, route switch, cloud fallback disposition, redacted context. | Software recovery service. | Software control/orchestrator/UI/tasks. | Recent traces in-memory. | `src/stormhelm/core/software_recovery/models.py`, `src/stormhelm/core/software_recovery/service.py` | `tests/test_software_recovery.py` |

## Discord Relay

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Discord relay models | Represent destination, payload candidate, policy decision, preview, dispatch attempt, trace, response. | alias, destination kind, route mode, payload kind, provenance, fingerprint, dispatch state, policy outcome, verification strength. | Discord relay subsystem. | Orchestrator/UI/trust/adapter contracts. | Recent traces in-memory; destination aliases stored in conversation state. | `src/stormhelm/core/discord_relay/models.py`, `src/stormhelm/core/discord_relay/service.py` | `tests/test_discord_relay.py` |

## Trust

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Approval/trust models | Represent action requests, pending approvals, permission grants, audit records, decisions, posture summary. | request id, action key, subject, session/task, approval state, scope, expiry, details, operator messages. | Trust service/safety/subsystems. | UI command surface, safety policy, software/relay/tasks. | Stored in SQLite trust tables. | `src/stormhelm/core/trust/models.py`, `src/stormhelm/core/trust/service.py`, `src/stormhelm/core/trust/repository.py` | `tests/test_trust_service.py`, `tests/test_safety.py` |

## Voice

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Voice config models | Represent disabled-by-default voice, OpenAI voice, capture, and playback settings. | enable flags, provider/mode, manual/spoken/realtime truth flags, STT/TTS models, audio limits, persistence flags, capture/playback gates. | Config loader. | Core container, voice availability, voice service/providers, UI status. | Loaded at startup; not stored in SQLite. | `src/stormhelm/config/models.py`, `src/stormhelm/config/loader.py`, `config/default.toml` | `tests/test_voice_config.py`, `tests/test_voice_availability.py` |
| Voice availability/state | Explain whether voice is available and expose current runtime voice status. | availability boolean/reasons, provider/mode, truth flags, active capture, last transcription/Core/TTS/playback results. | `compute_voice_availability()`, `VoiceStateController`, `VoiceService.status_snapshot()`. | `/status`, `/snapshot`, UI bridge, troubleshooting. | In-memory runtime state; status snapshots are derived. | `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/state.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_availability.py`, `tests/test_voice_state.py`, `tests/test_voice_diagnostics.py` |
| Voice turn models | Represent speech-derived turns entering the core boundary. | audio/text source, transcript, request id, core request/result, spoken response, provider metadata, errors. | Voice service and providers. | Assistant orchestrator, response renderer, UI diagnostics. | Message history persists through normal chat persistence when a core turn is submitted. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/bridge.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_manual_turn.py`, `tests/test_voice_audio_turn.py`, `tests/test_voice_core_bridge_contracts.py` |
| Voice provider models | Represent STT/TTS/capture/playback requests and results. | audio metadata, transcript text, speech request, generated audio output, capture session/result, playback result, provider/model/latency/error fields. | Provider implementations and `VoiceService`. | Diagnostics, events, UI, tests. | Captured/generated audio is transient by default unless persistence flags are changed. | `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py` | `tests/test_voice_stt_provider.py`, `tests/test_voice_tts_provider.py`, `tests/test_voice_capture_provider.py`, `tests/test_voice_playback_provider.py` |
| Voice events | Publish voice lifecycle and diagnostics events. | event type, action/session ids, provider state, result/error payloads. | `publish_voice_event()` and voice service actions. | Event buffer, UI stream, troubleshooting. | In-memory bounded event buffer. | `src/stormhelm/core/voice/events.py`, `src/stormhelm/core/events.py` | `tests/test_voice_events.py`, `tests/test_voice_capture_diagnostics_events.py`, `tests/test_voice_playback_diagnostics_events.py` |

## Task Graph

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Task records | Durable execution/continuity graph. | task state, steps, dependencies, blockers, checkpoints, artifacts, evidence, job links, resume assessment. | Durable task service and job/trust callbacks. | Orchestrator, workspace, UI, semantic memory. | Stored in SQLite task tables. | `src/stormhelm/core/tasks/models.py`, `src/stormhelm/core/tasks/service.py`, `src/stormhelm/core/tasks/repository.py` | `tests/test_task_graph.py` |

## Workspace And Context

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Workspace records | Saved/opened workspace state, items, activity, snapshots, note links. | workspace id, title, items, item state, activity, tags, snapshots. | Workspace service/tools/UI bridge. | Command Deck, workspace tools, task continuity. | Stored in SQLite workspace tables. | `src/stormhelm/core/workspace/models.py`, `src/stormhelm/core/workspace/service.py`, `src/stormhelm/core/workspace/repository.py`, `src/stormhelm/core/memory/database.py` | `tests/test_workspace_service.py` |
| Context/environment records | Browser/activity/current context intelligence. | active context, browser context, activity summary, environment snapshots. | Context/environment services and tools. | Planner, Discord relay, screen awareness, workspace. | Service-dependent; some state is snapshot-only. | `src/stormhelm/core/context/models.py`, `src/stormhelm/core/context/service.py`, `src/stormhelm/core/environment/models.py`, `src/stormhelm/core/environment/service.py` | `tests/test_context_service.py`, `tests/test_environment_service.py` |

## Semantic Memory

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Memory records/query logs | Local semantic memory with family, provenance, freshness, confidence, suppression metadata. | family, content, summary, evidence, scope, timestamps, confidence, freshness, suppressed preview. | Semantic memory service, task sync. | Planner/context/task continuity. | Stored in SQLite `memory_records` and `memory_query_log`. | `src/stormhelm/core/memory/models.py`, `src/stormhelm/core/memory/service.py`, `src/stormhelm/core/memory/database.py` | `tests/test_semantic_memory.py` |

## Lifecycle

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Lifecycle models | Install/runtime/startup/shell/tray/cleanup/uninstall state. | install mode, runtime mode, startup policy, shell presence, restart policy, hold state, cleanup plan/result. | Lifecycle controller and API. | UI bridge, main controller, status/snapshot endpoints. | Runtime JSON files under state path. | `src/stormhelm/core/lifecycle/models.py`, `src/stormhelm/core/lifecycle/service.py` | `tests/test_lifecycle_service.py`, `tests/test_ui_lifecycle_bridge.py` |

## UI-Facing State

| Model family | Purpose | Fields | Producers | Consumers | Persistence behavior | Source files | Tests |
|---|---|---|---|---|---|---|---|
| Bridge properties | QML-facing presentation state. | messages, ghost cards, deck modules/panels, route inspector, workspace canvas, opened items, status strips, adaptive Ghost state, voice state. | `UiBridge` from health/status/snapshot/chat/stream payloads. | QML components. | Deck layout may persist in runtime state; most UI state derives from core snapshots. | `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/command_surface_v2.py`, `src/stormhelm/ui/voice_surface.py`, `assets/qml/Main.qml` | `tests/test_ui_bridge.py`, `tests/test_command_surface.py`, `tests/test_voice_ui_state_payload.py`, `tests/test_qml_shell.py` |

## SQLite Schema

| Table family | Tables |
|---|---|
| Conversations | `conversation_sessions`, `chat_messages` |
| Notes/tools/preferences | `notes`, `tool_runs`, `preferences` |
| Workspace | `workspaces`, `workspace_items`, `workspace_activity`, `workspace_snapshots`, `workspace_note_links` |
| Tasks | `tasks`, `task_steps`, `task_dependencies`, `task_blockers`, `task_checkpoints`, `task_artifacts`, `task_evidence`, `task_job_links` |
| Trust | `trust_approval_requests`, `trust_permission_grants`, `trust_audit_records` |
| Memory | `memory_records`, `memory_query_log` |

Sources: `src/stormhelm/core/memory/database.py`
Tests: `tests/test_storage.py`, `tests/test_task_graph.py`, `tests/test_trust_service.py`, `tests/test_semantic_memory.py`, `tests/test_workspace_service.py`
