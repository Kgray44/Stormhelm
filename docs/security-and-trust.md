# Security And Trust

Stormhelm is local-first by default, but it can still affect local files, apps, windows, external surfaces, Discord, software workflows, and optional API providers. Treat safety/trust state as backend-owned.

## Local-First Behavior

| Area | Local by default? | Notes |
|---|---|---|
| Core API | Yes | FastAPI binds to `127.0.0.1` by default. |
| UI | Yes | PySide/QML local process. |
| Storage | Yes | SQLite and runtime JSON under local paths. |
| Calculations | Yes | Deterministic local parser/evaluator/helpers. |
| Routing | Yes | Deterministic planner and slash router. |
| Tools | Yes | Built-in local tools unless provider/integration explicitly used. |
| Voice state/control | Yes | Voice status, capture controls, and UI state are local. OpenAI STT/TTS is external only when enabled/invoked. |
| Web retrieval | External public web when used | HTTP and optional Obscura retrieval only fetch public `http`/`https` URLs after safety validation. Private/local/file/credential URLs are blocked by default. |
| OpenAI | No, external | Disabled by default; enabling sends prompt/context to configured API. |
| Weather | External provider | Weather tool uses configured provider URL when used. |
| Discord relay | External effect | Local client automation can send material outside Stormhelm after preview/trust. |

Sources: `config/default.toml`, `src/stormhelm/core/api/app.py`, `src/stormhelm/core/container.py`, `src/stormhelm/core/calculations/service.py`, `src/stormhelm/core/providers/openai_responses.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/discord_relay/service.py`
Tests: `tests/test_config_loader.py`, `tests/test_calculations.py`, `tests/test_voice_availability.py`, `tests/test_discord_relay.py`

## Secrets And API Keys

| Secret | How it is read | Guidance |
|---|---|---|
| `OPENAI_API_KEY` | `.env` or process environment. | Required only when OpenAI is enabled. Do not commit real keys. |
| `STORMHELM_OPENAI_API_KEY` | `.env` or process environment. | Alternative OpenAI key env var. Do not commit real keys. |
| Voice OpenAI key | Same OpenAI key variables. | Required for provider-backed STT/TTS only when OpenAI voice paths are enabled. |
| Discord session | User's local Discord client/session. | Stormhelm does not document a token/self-bot flow; local automation depends on the user's client state. |

OpenAI config can also include an `api_key` value in TOML, but environment variables are safer. Do not put real secrets in `config/default.toml`, `.env.example`, docs, or committed test fixtures.

Sources: `src/stormhelm/config/loader.py`, `config/default.toml`, `src/stormhelm/core/providers/openai_responses.py`
Tests: `tests/test_config_loader.py`

## Approval Model

Trust state uses typed approval requests, grants, scopes, expirations, and audit records.

| Scope | Intended behavior |
|---|---|
| Once | Permit one action attempt. |
| Task | Permit action while bound to the current task. |
| Session | Permit action during the current session until TTL/invalidated. |

Approval requests can be invalidated by expiry, runtime mismatch, task mismatch, or stale state. UI prompts reflect trust state but do not create grants by themselves.

Sources: `src/stormhelm/core/trust/models.py`, `src/stormhelm/core/trust/service.py`, `src/stormhelm/core/trust/repository.py`, `src/stormhelm/core/safety/policy.py`
Tests: `tests/test_trust_service.py`, `tests/test_safety.py`

## Trust-Gated Actions

`SafetyPolicy` explicitly trust-gates these tool names when a trust service/context is available:

| Tool/action family | Why it is gated |
|---|---|
| `shell_command` | Shell execution can change machine state. |
| `app_control`, `window_control` | Can launch/close/change apps/windows. |
| `workflow_execute`, `repair_action`, `routine_execute` | Can execute local workflows or repairs. |
| `trusted_hook_register`, `trusted_hook_execute` | Can register/execute trusted hooks. |
| `file_operation`, `maintenance_action` | Can change local files/system state. |
| `external_open_url`, `external_open_file` | Hands work to native external surfaces. |
| `workspace_archive`, `workspace_clear` | Can hide/remove workspace state. |

Sources: `src/stormhelm/core/safety/policy.py`, `src/stormhelm/core/tools/builtins/__init__.py`
Tests: `tests/test_safety.py`, `tests/test_tool_registry.py`

## Public Web Retrieval

Web retrieval is read-only and does not require trust approval by default, but it is still an external network path. It uses a public URL safety gate before any provider runs and re-checks final URLs after redirects.

| Boundary | Current behavior |
|---|---|
| URL schemes | Only `http` and `https` public URLs are accepted; unsupported schemes are blocked. |
| Local/private targets | Localhost, loopback, private/link-local IPs, IPv4/IPv6 encoding tricks, `.local`, and file URLs are blocked by default. |
| Redirects | A public-looking URL cannot redirect into localhost/private/file/credential territory. |
| Credentials | Credential-bearing URLs are blocked and credentials are redacted from errors. |
| Providers | HTTP extraction is enabled by default; Obscura CLI and Obscura CDP are optional and disabled by default. |
| Output limits | URL length, text, and optional HTML are bounded by config limits. |
| Events | Events include provider/status/counts/claim ceiling, not raw page text or HTML. |
| CDP lifecycle | Managed Obscura CDP binds to localhost only, starts only for CDP provider requests, probes readiness, caps session lifetime/page count, and stops after inspection. |
| Claim ceiling | HTTP/CLI results are rendered page evidence only. CDP results are `headless_cdp_page_evidence` only. Stormhelm does not independently check source claims and does not treat extraction as the user's visible screen. |
| Out of scope | Logged-in browser context, cookies/session reuse, form submission, clicking, typing, scrolling, credentials, CAPTCHA/anti-bot bypass, stealth bypass behavior, Playwright/Puppeteer integration, visible-screen verification, and webpage truth verification. |

Sources: `src/stormhelm/core/web_retrieval/safety.py`, `src/stormhelm/core/web_retrieval/service.py`, `src/stormhelm/core/web_retrieval/obscura_provider.py`, `src/stormhelm/core/web_retrieval/cdp.py`, `src/stormhelm/core/web_retrieval/cdp_provider.py`, `src/stormhelm/core/adapters/contracts.py`, `config/default.toml`
Tests: `tests/test_web_retrieval_safety.py`, `tests/test_web_retrieval_service.py`, `tests/test_web_retrieval_providers.py`, `tests/test_web_retrieval_cdp.py`, `tests/test_adapter_contracts.py`

## Destructive Action Rules

| Action | Boundary |
|---|---|
| File read | Allowed only under `safety.allowed_read_dirs`. |
| File operation | Trust-gated action tool. |
| Workspace clear/archive | Trust-gated action tool. |
| Shell | Disabled stub by default. |
| Software install/update/uninstall/repair | Plan and trust approval before action; privileged routes disabled by default. |
| Lifecycle cleanup | Requires cleanup plan and confirmation payload. |
| Screen action | Confirm-before-act by default. |
| Discord dispatch | Preview, fingerprint, trust approval, and duplicate/stale checks. |
| Voice capture/playback/wake | Disabled by default; explicit controls only; capture/playback/wake have separate gates and do not bypass trust/safety for commands. |

Sources: `src/stormhelm/core/safety/policy.py`, `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/lifecycle/service.py`, `src/stormhelm/core/screen_awareness/action.py`, `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/voice/service.py`
Tests: `tests/test_safety.py`, `tests/test_software_control.py`, `tests/test_lifecycle_service.py`, `tests/test_screen_awareness_action.py`, `tests/test_discord_relay.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_playback_service.py`

## Screen-Awareness Privacy

Current posture:

- Screen awareness is enabled by default in config.
- It uses native/current context and deterministic engines.
- Clipboard-only evidence must not impersonate the current screen.
- Provider visual augmentation is available only when a provider exists.
- Action is policy-gated and defaults to `confirm_before_act`.
- Truthfulness/audit fields should surface low confidence, missing prior observation, and unsupported evidence.

What should not happen:

- Do not claim full visual certainty from clipboard or stale context.
- Do not execute screen actions silently under default policy.
- Do not send screen context to OpenAI unless provider-backed augmentation/fallback is explicitly enabled and used.

Sources: `config/default.toml`, `src/stormhelm/core/screen_awareness/service.py`, `src/stormhelm/core/screen_awareness/observation.py`, `src/stormhelm/core/screen_awareness/action.py`, `src/stormhelm/core/screen_awareness/verification.py`
Tests: `tests/test_screen_awareness_phase12.py`, `tests/test_screen_awareness_action.py`, `tests/test_screen_awareness_verification.py`

## Discord Relay Boundaries

Current posture:

- Trusted aliases are configured, not inferred from arbitrary user strings.
- Preview before send is enabled.
- Dispatch is trust-gated.
- The relay records payload provenance and preview fingerprints.
- Stale previews are invalidated.
- Duplicate sends are suppressed within a short window.
- Secret-looking payloads can be blocked by policy.
- Official bot/webhook routes are disabled by default.

Self-bot/token boundary:

- The code uses local client automation and an official scaffold adapter; docs should not direct users to self-bot token flows.

Sources: `config/default.toml`, `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/discord_relay/adapters.py`, `src/stormhelm/core/discord_relay/models.py`
Tests: `tests/test_discord_relay.py`

## Voice Privacy Boundaries

Current posture:

- Voice is disabled by default.
- Local wake provider support is disabled by default and requires explicit wake and dev gates plus an available local backend.
- Wake-to-Ghost is presentation only. There is no post-wake capture window, always-listening command mode, semantic VAD, or Realtime session.
- VAD is disabled by default, mock/dev gated, and detects audio activity only during an explicit capture/listen window. Speech stopped does not mean the request was understood.
- Dormant wake audio is not sent to OpenAI or cloud services.
- Capture is explicit and has a separate `voice.capture.enabled` gate plus development capture gate.
- Generated TTS artifacts and captured audio are transient by default.
- OpenAI STT/TTS sends audio/text externally only when OpenAI and the relevant voice path are enabled and invoked.
- Voice providers do not execute tools or lower approval requirements.
- Playback completion is not proof that the user heard audio.

What should not happen:

- Do not treat microphone capture as active unless capture state says it is active.
- Do not persist raw/generated audio unless the explicit persistence settings are changed.
- Do not claim continuous command listening, Realtime, post-wake capture, command understanding, or direct voice command execution from wake-to-Ghost presentation or VAD activity.

Sources: `config/default.toml`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/bridge.py`
Tests: `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_playback_service.py`, `tests/test_voice_core_bridge_contracts.py`, `tests/test_voice_wake_service.py`, `tests/test_voice_local_wake_provider.py`, `tests/test_voice_wake_ghost_service.py`, `tests/test_voice_wake_ghost_payload.py`, `tests/test_voice_vad_service.py`

## Software Installation Safety

Current posture:

- Trusted sources only by default.
- Package-manager/vendor/browser-guided routes are separately configurable.
- Privileged software operations are disabled by default.
- Install/update/uninstall/repair require confirmation unless unsafe test mode is enabled.
- Prepared plans are not success claims.
- Verification is explicit and can be `unverified` or `uncertain`.
- Recovery can propose bounded route switches but marks results unverified until checked.

Sources: `config/default.toml`, `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/software_recovery/service.py`, `src/stormhelm/core/safety/policy.py`
Tests: `tests/test_software_control.py`, `tests/test_software_recovery.py`, `tests/test_safety.py`

## Data Retention

| Data | Retention behavior |
|---|---|
| Events | In-memory bounded by `event_stream.retention_capacity` and `replay_limit`. |
| Conversations | Stored in SQLite. |
| Notes | Stored in SQLite. |
| Tool runs | Stored in SQLite and job history bounded in memory. |
| Workspace state | Stored in SQLite. |
| Task graph | Stored in SQLite. |
| Trust approvals/grants/audit | Stored in SQLite with TTL/invalidation logic. |
| Semantic memory/query logs | Stored in SQLite with service-managed pruning/freshness. |
| Lifecycle/core state | Runtime JSON state files. |
| Voice captured/generated audio | Transient by default; persistence flags are false in default config. |
| Voice status/events | Runtime status and bounded event stream; not a separate SQLite voice table in the current model. |

Sources: `src/stormhelm/core/events.py`, `src/stormhelm/core/memory/database.py`, `src/stormhelm/core/memory/repositories.py`, `src/stormhelm/core/memory/service.py`, `src/stormhelm/core/runtime_state.py`, `src/stormhelm/core/lifecycle/service.py`, `src/stormhelm/core/voice/service.py`, `config/default.toml`
Tests: `tests/test_events.py`, `tests/test_storage.py`, `tests/test_semantic_memory.py`, `tests/test_runtime_state.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_tts_provider.py`

## Telemetry Boundaries

Telemetry/watch/debug state is local unless an explicitly enabled external provider is used. Hardware telemetry may call helper/provider logic, but elevated helper use is disabled by default. Event stream is local to the core process.

Sources: `src/stormhelm/core/system/hardware_telemetry.py`, `src/stormhelm/core/events.py`, `src/stormhelm/core/container.py`, `config/default.toml`
Tests: `tests/test_hardware_telemetry.py`, `tests/test_events.py`

## Never Sent Externally Unless Enabled

Stormhelm should not send these externally by default:

- Chat prompt/context to OpenAI.
- Screen context for provider visual augmentation.
- Audio/transcript/text for voice STT/TTS.
- Software troubleshooting context to cloud fallback.
- Local file contents from file reader.
- Semantic memory records.
- Task/workspace state.

Exceptions require explicit provider/integration enablement or user-initiated external action. Weather requests and Discord sends are external by their nature when used.

Sources: `config/default.toml`, `src/stormhelm/core/providers/openai_responses.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/software_recovery/service.py`, `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/tools/builtins/file_reader.py`
Tests: `tests/test_config_loader.py`, `tests/test_voice_stt_provider.py`, `tests/test_voice_tts_provider.py`, `tests/test_software_recovery.py`, `tests/test_discord_relay.py`, `tests/test_safety.py`

## Unsafe Test Mode

`STORMHELM_UNSAFE_TEST_MODE=true` enables test-only behavior that broadens read/action/software gates and should not be used as normal runtime posture.

Sources: `src/stormhelm/config/loader.py`, `src/stormhelm/core/safety/policy.py`
Tests: `tests/test_config_loader.py`, `tests/test_safety.py`
