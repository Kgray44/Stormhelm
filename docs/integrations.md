# Integrations

Stormhelm is local-first, but it has optional or platform-specific integration points. This page documents what is wired now and where fallback/unavailable behavior lives.

## OpenAI Responses API

| Item | Current behavior |
|---|---|
| Default | Disabled. |
| Enable | Set `STORMHELM_OPENAI_ENABLED=true` and `OPENAI_API_KEY` or `STORMHELM_OPENAI_API_KEY`. |
| Provider | `OpenAIResponsesProvider`. |
| Models | Defaults in `config/default.toml`: `gpt-5.4-nano` and `gpt-5.4`. |
| Boundary | Optional fallback; deterministic/local routes should answer, clarify, or refuse before provider fallback. |
| Data sent externally | Prompt/context passed to provider when enabled. |
| Unavailable behavior | Provider is not built or used when disabled/missing key. |

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/container.py`, `src/stormhelm/core/providers/openai_responses.py`, `src/stormhelm/core/providers/base.py`, `src/stormhelm/core/providers/audit.py`
Tests: `tests/test_config_loader.py`, `tests/test_command_eval_provider_audit.py`

## OpenAI Voice STT/TTS

| Item | Current behavior |
|---|---|
| Default | Disabled through `voice.enabled=false`, `voice.mode="disabled"`, and `openai.enabled=false`. |
| Enable | Requires OpenAI enabled, an API key, voice enabled, non-disabled voice mode, and configured voice OpenAI models. |
| STT | Controlled audio input through configured `voice.openai.stt_model`; bounded by audio duration/size/timeouts. |
| TTS | Controlled speech artifact generation through configured `voice.openai.tts_model`, voice, format, speed, and text length limit. |
| Capture/playback | Separate local provider gates; STT/TTS availability does not imply microphone capture or audible playback. |
| Not implemented | Wake word, always-listening, Realtime sessions, VAD, full interruption, and direct voice command authority. |
| Data sent externally | Audio or speech text sent to OpenAI only when the relevant voice/OpenAI path is enabled and invoked. |
| Unavailable behavior | Voice status/action results should report disabled, missing key, blocked, unsupported, timeout, or provider error states. |

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`
Tests: `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_stt_provider.py`, `tests/test_voice_tts_provider.py`

## Discord

| Item | Current behavior |
|---|---|
| Trusted aliases | Configured under `discord_relay.trusted_aliases.*`; default includes `baby`. |
| Local route | `local_client_automation` through Windows clipboard/native input/window probing. |
| Preview | Required by current relay truth contract. |
| Approval | Dispatch is trust-gated. |
| Duplicate/stale checks | Preview fingerprint, TTL, mutation checks, duplicate window. |
| Official bot/webhook | Scaffold adapter exists, but `bot_webhook_routes_enabled=false` by default. |
| Unavailable behavior | Fails with route/adapter/transport-specific state; should not claim delivery without evidence. |

Sources: `config/default.toml`, `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/discord_relay/adapters.py`, `src/stormhelm/core/discord_relay/models.py`, `src/stormhelm/core/adapters/contracts.py`
Tests: `tests/test_discord_relay.py`, `tests/test_adapter_contracts.py`

## Browser And File Surfaces

| Item | Current behavior |
|---|---|
| Deck URL open | Internal Deck browser/opened item action. |
| External URL open | Native external open action; trust/adapter contract can apply. |
| Deck file open | Internal file viewer/opened item action where supported. |
| External file open | Native file handoff; trust/adapter contract can apply. |
| Resolver | Known destinations, search providers, browser targets, direct domains. |
| Unavailable behavior | Falls back to external open/action failure or route clarification depending on request. |

Sources: `src/stormhelm/core/orchestrator/browser_destinations.py`, `src/stormhelm/core/tools/builtins/workspace_actions.py`, `assets/qml/components/BrowserSurface.qml`, `assets/qml/components/FileViewerSurface.qml`, `src/stormhelm/ui/controllers/main_controller.py`
Tests: `tests/test_browser_destination_resolution.py`, `tests/test_main_controller.py`, `tests/test_qml_shell.py`

## Windows APIs And Native Control

| Area | Current behavior |
|---|---|
| Ghost hotkey | Windows hotkey parsing/registration for `Ctrl+Space`. |
| Tray/window | PySide tray and window show/hide behavior. |
| App control | Launch/close/quit/force quit style native app control through system probe/tools. |
| Window control | Native window status/control tools. |
| System control | Lock/sleep/shutdown-like capability surfaces where implemented and contract-backed. |
| Startup | Windows registry startup probe/mutation in lifecycle service. |
| Discord local automation | Windows clipboard and input/window automation route. |

Actions that can change local state are trust-gated or policy-gated.

Sources: `src/stormhelm/ui/ghost_input.py`, `src/stormhelm/ui/tray.py`, `src/stormhelm/ui/windows_effects.py`, `src/stormhelm/core/system/probe.py`, `src/stormhelm/core/tools/builtins/system_state.py`, `src/stormhelm/core/lifecycle/service.py`, `src/stormhelm/core/discord_relay/adapters.py`
Tests: `tests/test_ghost_input.py`, `tests/test_ui_tray.py`, `tests/test_windows_effects.py`, `tests/test_system_probe.py`, `tests/test_lifecycle_service.py`

## Package Managers And Software Sources

| Source kind | Current behavior |
|---|---|
| `winget` | Can be selected as a trusted package-manager source when catalog entry has a winget id and package-manager routes are enabled. Execution adapter is not fully wired in this pass. |
| `chocolatey` | Same as winget for catalog source resolution. |
| Vendor installer | Can be selected when catalog has vendor URL and vendor routes are enabled. |
| Browser-guided | Can be selected when enabled and source passes trusted-source filtering. |
| Privileged operations | Disabled by default through `software_control.privileged_operations_allowed=false`. |

Sources: `src/stormhelm/core/software_control/catalog.py`, `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/safety/policy.py`, `config/default.toml`
Tests: `tests/test_software_control.py`, `tests/test_safety.py`

## Qt / QML / PySide

| Item | Current behavior |
|---|---|
| UI runtime | PySide6 application loads `assets/qml/Main.qml`. |
| Context properties | `stormhelmBridge` and `stormhelmGhostInput`. |
| Surfaces | Ghost, Command Deck, command cards, route inspector, workspace canvas, browser/file/network/status surfaces. |
| Shader assets | QML shader assets are present and tested. |
| Unavailable behavior | QML load failure prevents UI startup; core can still run separately. |

Sources: `src/stormhelm/ui/app.py`, `assets/qml/Main.qml`, `assets/qml/components/*.qml`, `assets/qml/shaders/*.frag`
Tests: `tests/test_qml_shell.py`, `tests/test_shader_assets.py`

## Storage / SQLite

| Item | Current behavior |
|---|---|
| Engine | SQLite database under resolved runtime data path. |
| Stores | Conversations, notes, tool runs, preferences, workspace, task graph, trust, memory. |
| Runtime state | JSON state files for lifecycle/core/session/layout-like state. |
| Unavailable behavior | Startup/storage tests should surface DB/path failures; UI state may be incomplete if storage is unavailable. |

Sources: `src/stormhelm/core/memory/database.py`, `src/stormhelm/core/memory/repositories.py`, `src/stormhelm/core/runtime_state.py`, `src/stormhelm/shared/paths.py`
Tests: `tests/test_storage.py`, `tests/test_runtime_state.py`, `tests/test_snapshot_resilience.py`

## Weather And Location

| Item | Current behavior |
|---|---|
| Weather provider | Default base URL is Open-Meteo. |
| Location | Home location fields and approximate lookup settings. |
| Units | Default `imperial`. |
| Unavailable behavior | Weather/location tools should return bounded failure or unavailable state rather than provider fantasy. |

Sources: `config/default.toml`, `src/stormhelm/core/tools/builtins/system_state.py`, `src/stormhelm/config/loader.py`
Tests: `tests/test_long_tail_power.py`, `tests/test_tool_registry.py`

## Hardware Telemetry

| Item | Current behavior |
|---|---|
| Helper | `stormhelm-telemetry-helper` entrypoint. |
| Cache TTLs | Idle/active/burst cache settings. |
| Elevated helper | Disabled by default. |
| HWiNFO | Enabled flag and executable path setting exist. |
| Unavailable behavior | Telemetry status should report helper/provider availability rather than blocking core startup. |

Sources: `src/stormhelm/core/system/hardware_telemetry.py`, `src/stormhelm/entrypoints/telemetry_helper.py`, `config/default.toml`
Tests: `tests/test_hardware_telemetry.py`

## Packaging Integrations

| Item | Current behavior |
|---|---|
| PyInstaller | Portable build script uses PyInstaller package output. |
| Inno Setup | Installer script expects `ISCC.exe` when building installer. |
| Assets/config | Portable script copies runtime resources/config. |
| Unavailable behavior | Installer build fails or is skipped if Inno Setup is not available. |

Sources: `scripts/package_portable.ps1`, `scripts/package_installer.ps1`, `pyproject.toml`
Tests: `tests/test_launcher.py`, manual packaging verification needed

## Optional / Unavailable Integrations

| Integration | Status | Notes |
|---|---|---|
| Voice wake word / always-listening / Realtime / VAD | Planned | The voice foundation exists, but these modes are unavailable and must be reported as such. |
| Voice local capture/playback | Implemented but limited | Provider boundaries exist, disabled by default, and gated for development/local dependency readiness. |
| External vector database | Not configured | Semantic memory uses local SQLite/service logic. |
| Official Discord bot/webhook | Scaffolded | Disabled by default. |
| Unrestricted shell | Scaffolded/disabled | Shell command tool is a disabled stub by default. |
| Full autonomous computer use | Not implemented | Screen awareness/action is bounded and policy-gated. |

Sources: `docs/archive/phase-documents.md`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/memory/database.py`, `src/stormhelm/core/discord_relay/adapters.py`, `src/stormhelm/core/tools/builtins/shell_stub.py`, `src/stormhelm/core/screen_awareness/action.py`
Tests: `tests/test_voice_availability.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_playback_service.py`, `tests/test_discord_relay.py`, `tests/test_safety.py`, `tests/test_screen_awareness_action.py`
