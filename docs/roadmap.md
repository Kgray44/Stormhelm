# Roadmap

This roadmap separates current implementation from partial, scaffolded, and planned work. It is not a vision document.

## Implemented Now

| Area | Current implemented behavior | Sources | Tests |
|---|---|---|---|
| FastAPI core | Local health/status/chat/history/jobs/events/notes/settings/tools/lifecycle/snapshot API. | `src/stormhelm/core/api/app.py` | `tests/test_events.py`, `tests/test_snapshot_resilience.py` |
| Core container | Wires config, storage, events, jobs, tools, planner, provider, subsystems, lifecycle, trust, tasks, workspace. | `src/stormhelm/core/container.py` | `tests/test_core_container.py` |
| PySide/QML UI | Ghost, Command Deck, bridge, client, controller, tray, QML surfaces. | `src/stormhelm/ui/*`, `assets/qml/*` | `tests/test_ui_bridge.py`, `tests/test_qml_shell.py`, `tests/test_main_controller.py` |
| Legacy slash commands | `/time`, `/system`, `/battery`, `/storage`, `/network`, `/apps`, `/recent`, `/echo`, `/read`, `/note`, `/shell`, `/open`, `/workspace`. | `src/stormhelm/core/orchestrator/router.py` | `tests/test_assistant_orchestrator.py` |
| Deterministic planner | Natural-language route families and local-first route posture. | `src/stormhelm/core/orchestrator/planner.py`, `src/stormhelm/core/orchestrator/planner_models.py` | `tests/test_planner.py` |
| Built-in tools | Time, system, files, notes, browser/file opens, machine/power/resource/storage/network, apps/windows/system, workspace, workflows/routines, location/weather. | `src/stormhelm/core/tools/builtins/__init__.py` | `tests/test_tool_registry.py` |
| Safety policy | Tool enablement, read allowlists, shell stub gate, software route gates, trust-gated actions. | `src/stormhelm/core/safety/policy.py` | `tests/test_safety.py` |
| Trust service | Approval requests, grants, audit records, expiration/invalidation. | `src/stormhelm/core/trust/service.py` | `tests/test_trust_service.py` |
| SQLite storage | Conversations, notes, tool runs, preferences, workspace, task graph, trust, semantic memory. | `src/stormhelm/core/memory/database.py` | `tests/test_storage.py` |
| Event streaming | Bounded event buffer, replay/gap/heartbeat, UI stream reconciliation. | `src/stormhelm/core/events.py`, `src/stormhelm/ui/client.py` | `tests/test_events.py`, `tests/test_ui_client_streaming.py` |
| Calculations | Local deterministic arithmetic/helpers/explanations/verification traces. | `src/stormhelm/core/calculations` | `tests/test_calculations.py` |
| Screen awareness | Native/context observation, interpretation, grounding, verification, gated action, problem-solving/workflow support. | `src/stormhelm/core/screen_awareness` | `tests/test_screen_awareness_service.py` |
| Software control | Target catalog, source planning, approval gates, verify/launch paths, recovery handoff. | `src/stormhelm/core/software_control` | `tests/test_software_control.py` |
| Software recovery | Local hypotheses, redacted context, bounded recovery plans. | `src/stormhelm/core/software_recovery` | `tests/test_software_recovery.py` |
| Discord relay | Trusted alias preview/dispatch path with provenance, fingerprints, approval, stale/duplicate checks. | `src/stormhelm/core/discord_relay` | `tests/test_discord_relay.py` |
| Durable task graph | Task steps, blockers, evidence, job links, trust signals, where-left-off summaries. | `src/stormhelm/core/tasks` | `tests/test_task_graph.py` |
| Lifecycle/startup | Install/runtime/startup/shell/tray/cleanup/resolution state. | `src/stormhelm/core/lifecycle` | `tests/test_lifecycle_service.py` |

## Implemented But Limited

| Area | Limitation | Sources | Tests |
|---|---|---|---|
| OpenAI provider | Disabled by default; requires API key and enable flag. | `src/stormhelm/core/providers/openai_responses.py`, `config/default.toml` | `tests/test_config_loader.py` |
| Software install/update/uninstall/repair | Plans and approval gates exist; package-manager execution adapter is not fully wired in this pass. | `src/stormhelm/core/software_control/service.py` | `tests/test_software_control.py` |
| Screen awareness | Bounded native/context observation; not full autonomous computer use. Provider visual augmentation only when provider exists. | `src/stormhelm/core/screen_awareness/service.py` | `tests/test_screen_awareness_phase12.py` |
| Discord relay | Local client automation depends on user session/window state; official bot/webhook disabled by default. | `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/discord_relay/adapters.py` | `tests/test_discord_relay.py` |
| Native app/window/system control | Windows-oriented and adapter/result limited. Sensitive actions are trust-gated. | `src/stormhelm/core/system/probe.py`, `src/stormhelm/core/tools/builtins/system_state.py` | `tests/test_system_probe.py` |
| Hardware telemetry | Helper/provider availability and optional HWiNFO configuration affect detail. Elevated helper disabled by default. | `src/stormhelm/core/system/hardware_telemetry.py` | `tests/test_hardware_telemetry.py` |
| Packaging | Scripts exist; installer/portable output still needs clean-machine manual verification. | `scripts/package_portable.ps1`, `scripts/package_installer.ps1` | `tests/test_launcher.py` |
| Semantic memory | Local service and SQLite records exist; no external vector store configured by default. | `src/stormhelm/core/memory/service.py` | `tests/test_semantic_memory.py` |

## Scaffolded / Partially Wired

| Area | Current state | Sources | Tests |
|---|---|---|---|
| Official Discord bot/webhook | Scaffold adapter exists, config disables routes. | `src/stormhelm/core/discord_relay/adapters.py`, `config/default.toml` | `tests/test_discord_relay.py` |
| Shell command | Stub tool exists but is disabled by default and safety-gated. | `src/stormhelm/core/tools/builtins/shell_stub.py`, `src/stormhelm/core/safety/policy.py` | `tests/test_safety.py` |
| Voice UI | QML `VoiceCore` component exists, but no backend voice pipeline was found in tracked source. | `assets/qml/components/VoiceCore.qml` | `tests/test_qml_shell.py` |
| Route-v2 / command eval active worktree | Some active files/tests existed locally during rewrite but were not all listed by `git ls-files`; verify before publishing them as repo behavior. | active worktree under `src/stormhelm/core/orchestrator` and `tests` | Needs verification |
| Installer polish/signing | Packaging scripts exist; signing/notarization-style release hardening is not documented as implemented. | `scripts/package_installer.ps1` | Manual verification needed |

## Planned Next

| Area | Proposed next work | Why |
|---|---|---|
| Publish route-v2 intentionally | Add/verify active route-v2 files and tests or remove references from runtime imports. | Avoid docs/tests describing files not in Git. |
| Software execution adapters | Wire package-manager/vendor/browser-guided execution with trust, verification, and rollback metadata. | Software control is currently plan-heavy. |
| Provider fallback audit | Make provider call audit/reporting easy to inspect in UI/docs. | External API boundaries need strong evidence. |
| UI approval controls | Keep approval state backend-owned while making once/task/session choices ergonomic. | Trust flow is central to safety. |
| Docs link/source checker | Add a repeatable docs check for source paths and internal links. | Prevent doc drift. |
| Packaging verification checklist | Convert manual packaging checks into repeatable smoke tests where possible. | Portable/installer release confidence. |

## Long-Term

| Area | Direction |
|---|---|
| Voice pipeline | Wake word, STT, TTS, permissions, voice routing, and voice UX once backend ownership is designed and implemented. |
| Richer screen perception | More reliable visual grounding with explicit privacy controls and provider boundaries. |
| Durable workflow automation | More complete task execution, rollback, verification, and recovery with typed adapter contracts. |
| Semantic retrieval | Stronger retrieval ranking, retention controls, and provenance UI. |
| Release engineering | Installer signing, update channel, clean uninstall, crash reporting posture. |

## Explicit Non-Goals

| Non-goal | Reason |
|---|---|
| Brochure docs as primary docs | The docs should remain practical, source-referenced, and command-oriented. |
| UI-only success states | UI must render backend truth, not invent it. |
| Unrestricted shell by default | Local machine safety boundary. |
| Self-bot Discord token workflows | Not documented or recommended; current path is local client automation plus future official route scaffolding. |
| Silent screen control | Screen actions are gated and must be evidence/verification aware. |
| Provider-first routing | Local deterministic routes should own local-capable work. |
| Claiming planned voice as implemented | Voice remains planned/scaffolded until backend source/tests exist. |
