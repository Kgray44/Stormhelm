# Commands And Route Surfaces

Stormhelm has two command surfaces:

- Legacy slash commands in `IntentRouter`.
- Natural-language route families in `DeterministicPlanner` and subsystem planner seams.

The assistant path tries deterministic/local behavior before optional OpenAI fallback.

Sources: `src/stormhelm/core/orchestrator/router.py`, `src/stormhelm/core/orchestrator/planner.py`, `src/stormhelm/core/orchestrator/assistant.py`
Tests: `tests/test_assistant_orchestrator.py`, `tests/test_planner.py`, `tests/test_planner_command_routing_state.py`

## CLI / Process Commands

| Command | Purpose | Source | Tests |
|---|---|---|---|
| `.\scripts\run_core.ps1` | Start FastAPI core from source. | `scripts/run_core.ps1` | `tests/test_launcher.py` |
| `.\scripts\run_ui.ps1` | Start PySide/QML UI from source. | `scripts/run_ui.ps1` | `tests/test_launcher.py` |
| `.\scripts\dev_launch.ps1` | Development launch helper. | `scripts/dev_launch.ps1` | `tests/test_launcher.py` |
| `stormhelm-core` | Installed console script for the core. | `pyproject.toml`, `src/stormhelm/entrypoints/core.py` | `tests/test_launcher.py` |
| `stormhelm-ui` | Installed console script for the UI. | `pyproject.toml`, `src/stormhelm/entrypoints/ui.py` | `tests/test_launcher.py` |
| `stormhelm-telemetry-helper` | Installed console script for telemetry helper. | `pyproject.toml`, `src/stormhelm/entrypoints/telemetry_helper.py` | `tests/test_hardware_telemetry.py` |
| `.\scripts\package_portable.ps1` | Build a portable release. | `scripts/package_portable.ps1` | Needs manual package verification |
| `.\scripts\package_installer.ps1` | Build installer using Inno Setup after portable build. | `scripts/package_installer.ps1` | Needs manual installer verification |

## Local API Commands

| API | Method | Purpose | Source |
|---|---|---|---|
| `/health` | GET | Core health/version/runtime path. | `src/stormhelm/core/api/app.py` |
| `/status` | GET | Core container status snapshot. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/container.py` |
| `/chat/send` | POST | Submit chat/command request. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/orchestrator/assistant.py` |
| `/chat/history` | GET | Read persisted conversation messages. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/memory/repositories.py` |
| `/jobs` | GET | List jobs. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/jobs/manager.py` |
| `/jobs/{job_id}/cancel` | POST | Cancel a queued/running job if possible. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/jobs/manager.py` |
| `/events` | GET | Read recent/replayed events. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/events.py` |
| `/events/stream` | GET | Server-sent event stream. | `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/client.py` |
| `/notes` | GET/POST | Read/create notes. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/memory/repositories.py` |
| `/settings` | GET | Effective config snapshot. | `src/stormhelm/core/api/app.py`, `src/stormhelm/config/models.py` |
| `/tools` | GET | Registered tool descriptors. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/tools/registry.py` |
| `/snapshot` | GET | Full UI-facing state snapshot. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/container.py` |
| `/voice/capture/start` | POST | Start an explicit push-to-talk capture if voice capture gates allow it. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/capture/stop` | POST | Stop active capture and return capture result metadata. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/capture/cancel` | POST | Cancel active capture. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/capture/submit` | POST | Submit captured audio metadata through the controlled STT/Core/TTS path. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/capture/turn` | POST | Run a supervised capture-and-submit turn. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/playback/stop` | POST | Stop provider-owned playback state if supported. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/wake/readiness` | GET | Return wake readiness, including local provider/backend availability, without starting monitoring. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/wake/start` | POST | Start wake monitoring only when explicit wake/provider gates and local/mock provider availability allow it. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/wake/stop` | POST | Stop active wake monitoring without changing capture or Core task state. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/wake/simulate` | POST | Simulate a mock/dev wake event when wake gates allow it. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/wake/cancel` | POST | Cancel the active/mock wake session without capture or Core routing. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/wake/expire` | POST | Expire the active/mock wake session without capture or Core routing. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/wake/ghost` | GET | Return wake-to-Ghost presentation state without starting capture or routing Core. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/wake/ghost/cancel` | POST | Dismiss wake Ghost presentation and cancel the wake session only. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/vad/readiness` | GET | Return VAD readiness without starting detection. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/vad/speech-started` | POST | Simulate/mock speech activity start for an active capture/listen window. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |
| `/voice/vad/speech-stopped` | POST | Simulate/mock speech activity stop and optional capture finalization. | `src/stormhelm/core/api/app.py`, `src/stormhelm/core/voice/service.py` |

Tests: `tests/test_events.py`, `tests/test_ui_client_streaming.py`, `tests/test_snapshot_resilience.py`, `tests/test_storage.py`, `tests/test_voice_bridge_controls.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_playback_service.py`, `tests/test_voice_wake_service.py`, `tests/test_voice_local_wake_provider.py`, `tests/test_voice_wake_ghost_payload.py`, `tests/test_voice_vad_service.py`

## Slash Commands

| Slash command | Route family | Subsystem/tool | Expected behavior | Approval? | Verification |
|---|---|---|---|---|---|
| `/time` | legacy_command | `clock` | Return local/UTC time. | No | Tool result |
| `/system` | legacy_command | `system_info` | Return platform/runtime info. | No | Tool result |
| `/battery` | legacy_command | `power_status` | Return battery/power summary. | No | Tool result |
| `/storage` | legacy_command | `storage_status` | Return storage summary. | No | Tool result |
| `/network` | legacy_command | `network_status` | Return network state. | No | Tool result |
| `/apps` | legacy_command | `active_apps` | Return active app/window info. | No | Tool result |
| `/recent` | legacy_command | `recent_files` | Return recent files. | No | Tool result |
| `/echo hello` | legacy_command | `echo` | Echo test payload. | No | Tool result |
| `/read C:\path\file.txt` | legacy_command | `file_reader` | Read allowlisted file content. | No, but path-gated | Safety allowlist |
| `/note title: body` | legacy_command | `notes_write` | Persist a note. | No | SQLite write result |
| `/shell dir` | legacy_command | `shell_command` | Blocked by default because shell stub is disabled. | Yes/config gate | Safety policy |
| `/open deck https://example.com` | legacy_command | `deck_open_url` | Open URL inside Deck. | No | UI action |
| `/open external https://example.com` | legacy_command | `external_open_url` | Hand URL to native browser. | Trust-gated action | Adapter/safety |
| `/workspace save` | legacy_command | workspace tools | Save workspace state. | No | Tool result |
| `/workspace clear` | legacy_command | `workspace_clear` | Clear workspace. | Trust-gated action | Safety/trust |

Sources: `src/stormhelm/core/orchestrator/router.py`, `src/stormhelm/core/tools/builtins/__init__.py`, `src/stormhelm/core/safety/policy.py`
Tests: `tests/test_assistant_orchestrator.py`, `tests/test_safety.py`, `tests/test_tool_registry.py`

## Natural-Language Routes

| User request | Route family | Subsystem | Expected behavior | Approval? | Verification |
|---|---|---|---|---|---|
| `what is 18 * 42` | calculations | Calculations | Local parse/evaluate/format. | No | Calculation trace |
| `what is the voltage divider for 10k and 5k on 12v` | calculations | Calculations helper | Run implemented helper. | No | Calculation trace |
| `summarize https://example.com/docs` | web_retrieval | Web retrieval tool | Validate public URL, extract public page evidence with HTTP or optional Obscura. | No | Provider trace and evidence bundle |
| `extract links from https://example.com/docs` | web_retrieval | Web retrieval tool | Extract bounded links/text evidence without opening the browser. | No | Provider trace and link counts |
| `render this page` | web_retrieval | Web retrieval tool | Extract rendered page evidence only when current page URL context exists. | No | Attempted providers, fallback, final URL safety |
| `use Obscura CDP to inspect https://example.com/docs` | web_retrieval | Obscura CDP provider | Start a bounded localhost headless CDP session, inspect title/final URL/DOM text/links/metadata, then stop it. | No | CDP session trace and `headless_cdp_page_evidence` |
| `show me network summary for this public page https://example.com/docs` | web_retrieval | Obscura CDP provider | Route only when extraction/inspection is requested; does not open or control the visible browser. | No | Bounded network/console summary |
| `open youtube history` | browser_destination | Browser/open tools | Resolve destination/search and open according to surface. | External open may be trust-gated | Action/tool metadata |
| `open chrome` | app_control/software_control | System/app control or software launch | Launch known app if adapter available. | Action may be trust-gated | Native result/pid when available |
| `close notepad` | app_control | SystemProbe app control | Resolve the visible app/window, send a graceful close request, and verify closed vs confirmation-required vs failed. | Trust-gated | `close_result_state`, target/window trace |
| `force quit notepad` | app_control | SystemProbe app control | Destructive fallback after explicit approval; not used for graceful close. | Yes | Native result/failure reason |
| `install firefox` | software_control | Software control | Resolve target, prepare plan, ask approval; current execution adapter may be unavailable. | Yes | Prepared-only or recovery trace |
| `verify chrome is installed` | software_control | Software control | Probe known launch paths. | No | Local executable probe |
| `fix that failed install` | software_recovery | Software recovery | Classify failure and prepare bounded recovery. | Maybe, if action follows | Recovery result is unverified unless checked |
| `what am I looking at` | screen_awareness | Screen awareness | Observe/interpret current context, state limitations. | No | Evidence/confidence |
| `click the submit button` | screen_awareness_action | Screen awareness action | Ground target and gate action under policy. | Default yes | Verification outcome |
| `send this to Baby` | discord_relay | Discord relay | Resolve alias, choose current payload, preview and ask approval. | Yes before dispatch | Preview fingerprint, dispatch attempt |
| `where did we leave off` | task_continuity/workspace | Durable task/workspace | Return persisted task/workspace resume summary. | No | Stored task/workspace state |
| `start voice capture` | voice_control | Voice service | Start explicit push-to-talk capture only if voice and capture gates allow it. | Config/dev gate, not trust approval | Voice status/action result |
| `stop voice capture` | voice_control | Voice service | Stop active capture and report captured-audio metadata. | No extra approval | Voice capture result |
| `submit captured voice` | voice_control | Voice service | Send captured audio through controlled transcription and the existing core boundary. | Provider/key/config required | Voice turn result and core route metadata |
| `stop voice playback` | voice_control | Voice service | Stop playback-provider state when enabled/supported. | No extra approval | Playback result |
| `turn on always-listening voice` | unsupported/voice_control | Voice service | Refuse or explain unavailable wake/continuous mode. | No | Truthful unavailable state |
| `what failed recently` | watch_runtime | Events/status | Surface recent events, jobs, lifecycle/system state. | No | Status/event snapshot |
| `what's the weather` | weather | Weather tool | Use configured weather provider and location. | No | Tool/provider result |
| `remember this workspace` | workspace_operations | Workspace service/tools | Save or assemble workspace state. | Maybe for archive/clear | Tool result |
| `delete this file` | file_operation | File operation tool | Trust-gated local file operation, if routed and supported. | Yes | Tool result, adapter contract |
| `use OpenAI to answer this` | generic_provider | OpenAI provider | Provider call only when enabled/key present. | No action approval, but external API required | Provider response/audit |
| `do something unsupported` | unsupported | Planner/orchestrator | Refuse or clarify truthfully. | No | Unsupported reason |

Sources: `src/stormhelm/core/orchestrator/planner.py`, `src/stormhelm/core/orchestrator/browser_destinations.py`, `src/stormhelm/core/web_retrieval/service.py`, `src/stormhelm/core/calculations/service.py`, `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/screen_awareness/service.py`, `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/tasks/service.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/ui/client.py`
Tests: `tests/test_planner.py`, `tests/test_browser_destination_resolution.py`, `tests/test_web_retrieval_planner.py`, `tests/test_web_retrieval_service.py`, `tests/test_calculations.py`, `tests/test_software_control.py`, `tests/test_screen_awareness_service.py`, `tests/test_discord_relay.py`, `tests/test_task_graph.py`, `tests/test_voice_bridge_controls.py`, `tests/test_voice_core_bridge_contracts.py`

## Route State And Result State

Stormhelm surfaces route state to the UI so a user can see what family handled a request, what stage the result is in, and whether a trust/clarification/recovery state is pending.

Expected result-state families include:

| State | Meaning | Source |
|---|---|---|
| `ready` / prepared | Plan or preview is ready but execution may not have started. | `src/stormhelm/ui/command_surface_v2.py`, `src/stormhelm/core/software_control/service.py` |
| `needs_approval` | Trust gate is waiting for user decision. | `src/stormhelm/core/trust/service.py`, `src/stormhelm/ui/command_surface_v2.py` |
| `clarification` | Planner/subsystem could not choose truthfully. | `src/stormhelm/core/orchestrator/planner.py`, `src/stormhelm/core/discord_relay/service.py` |
| `blocked` | Safety, trust, policy, adapter, or config blocked the action. | `src/stormhelm/core/safety/policy.py`, `src/stormhelm/core/adapters/contracts.py` |
| `extracted` / `partial` | Public web evidence was extracted or partially extracted; weak extraction is labeled partial or low-confidence. | `src/stormhelm/core/web_retrieval/service.py`, `src/stormhelm/ui/command_surface_v2.py` |
| `fallback_used` | Obscura or another selected provider failed/unavailable and the final evidence came from fallback. | `src/stormhelm/core/web_retrieval/service.py`, `src/stormhelm/ui/command_surface_v2.py` |
| `provider_unavailable` / `timeout` / `unsupported` | No fake success: missing binaries, process timeouts, and unsupported content types stay typed. | `src/stormhelm/core/web_retrieval/service.py`, `src/stormhelm/core/web_retrieval/*_provider.py` |
| `blocked` with `redirect_target_blocked` | A public starting URL redirected to a blocked local/private/file/credential target; extracted text/html is not returned. | `src/stormhelm/core/web_retrieval/service.py`, `src/stormhelm/core/web_retrieval/cdp_provider.py` |
| `completed` | Tool/subsystem reports completion. | `src/stormhelm/core/tools/executor.py`, subsystem services |
| `unverified` / `uncertain` | Stormhelm has not verified the state strongly enough to claim success. | `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/screen_awareness/verification.py` |

Tests: `tests/test_command_surface.py`, `tests/test_ui_bridge_software_contracts.py`, `tests/test_trust_service.py`
