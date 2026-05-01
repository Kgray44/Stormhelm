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
| Live browser integration checks | Local diagnostics plus explicit public URL checks | Disabled unless `STORMHELM_LIVE_BROWSER_TESTS=true`; used to probe local Obscura/Playwright dependencies and the isolated Playwright semantic snapshot path without enabling action execution by default. |
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
| CDP diagnostics | Compatibility reports expose binary found/version, endpoint states, websocket availability, protocol version, optional domain availability, startup/navigation/cleanup status, and claim ceiling. They do not expose raw page content, cookies, credentials, full HTML, or huge process output. |
| Live integration | `scripts/run_live_browser_checks.ps1` and `python -m stormhelm.core.live_browser_integration` are opt-in only. They report passed/skipped/unavailable/partial/failed/incompatible states and keep action capabilities disabled. |
| Claim ceiling | HTTP/CLI results are rendered page evidence only. CDP results are `headless_cdp_page_evidence` only. Stormhelm does not independently check source claims and does not treat extraction as the user's visible screen. |
| Out of scope | Logged-in browser context, cookies/session reuse, form submission, clicking, typing, scrolling, credentials, CAPTCHA/anti-bot bypass, stealth bypass behavior, Playwright/Puppeteer integration, visible-screen verification, and webpage truth verification. |

Sources: `src/stormhelm/core/web_retrieval/safety.py`, `src/stormhelm/core/web_retrieval/service.py`, `src/stormhelm/core/web_retrieval/obscura_provider.py`, `src/stormhelm/core/web_retrieval/cdp.py`, `src/stormhelm/core/web_retrieval/cdp_provider.py`, `src/stormhelm/core/web_retrieval/obscura_cdp_probe.py`, `src/stormhelm/core/live_browser_integration.py`, `src/stormhelm/core/adapters/contracts.py`, `config/default.toml`, `config/development-live-browser.toml.example`
Tests: `tests/test_web_retrieval_safety.py`, `tests/test_web_retrieval_service.py`, `tests/test_web_retrieval_providers.py`, `tests/test_web_retrieval_cdp.py`, `tests/test_web_retrieval_cdp_reliability.py`, `tests/test_live_browser_integration.py`, `tests/test_adapter_contracts.py`

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
- The Playwright browser semantic adapter lives under Screen Awareness, is disabled by default, and is capped by strict claim ceilings: `browser_semantic_observation`, `browser_semantic_observation_comparison`, `browser_semantic_action_preview`, and runtime-gated `browser_semantic_action_execution`.
- Addition 1/1.1 readiness distinguishes disabled, dev-gated, dependency-missing, browser-engine-missing, mock-ready, runtime-ready, unavailable, and failed states without requiring Playwright in normal CI.
- Mock Playwright observations are labeled `playwright_mock`, require the dev adapter gate, and exist only for tests/diagnostics/UI plumbing. They are not real browser state.
- Disabled or unavailable Playwright config blocks mock observation and reports an unavailable mock observation instead of fabricating browser state.
- Playwright Addition 2 can extract bounded URL/title/control/form/dialog/text summaries from an isolated temporary browser context only when explicit dev/runtime gates and local dependencies are present. Playwright Addition 3 can rank semantic grounding candidates, report ambiguity, produce closest-match guidance, and create bounded form/dialog summaries from those observations. Playwright Addition 3.1 hardens messy-label/state extraction, synonym/negation grounding, iframe/shadow-DOM/large-page limitation reporting, and form-like summaries while preserving sensitive-value redaction. Playwright Addition 4 can compare two semantic observations and classify expected outcomes as supported, unsupported, partial, ambiguous, stale, insufficient, or unverifiable evidence. Playwright Addition 4.1 can create action previews and action plans with risk/trust/expected-check metadata. Playwright Addition 5 can execute only click/focus under explicit `allow_actions`, `allow_dev_actions`, and per-action gates, after trust approval, in an isolated temporary context, and then performs semantic before/after comparison. Playwright Addition 6 adds only trust-gated `type_text` into safe, non-sensitive text/search fields when `allow_type_text` and `allow_dev_type_text` are also enabled; raw text is held only for immediate in-memory execution and is redacted from persistent/reporting surfaces. Playwright Addition 7 adds only trust-gated safe choice controls when `allow_dev_choice_controls` plus `allow_check`, `allow_uncheck`, or `allow_select_option` are enabled; approval binds to the exact action, target, expected checked state, and dropdown option fingerprint. It blocks hidden/disabled/stale/ambiguous/sensitive/legal-consent/payment/delete/security choice targets, blocks duplicate/missing/disabled options, prevents form submission, and treats unexpected submit/navigation as not success. Playwright Addition 8 adds only trust-gated bounded `scroll` and `scroll_to_target` when `allow_dev_scroll` plus `allow_scroll` or `allow_scroll_to_target` are enabled; approval binds to direction, amount, target phrase, and attempt bounds. It blocks login/payment/CAPTCHA/security/profile-like page contexts, never clicks/types/selects/submits after scrolling, stops after configured attempts, and treats target-not-found or ambiguous target evidence as bounded partial/ambiguous results rather than success. Playwright Addition 7.1 strengthens choice controls by binding dropdown selections to the preview-time label/value-summary/ordinal fingerprint, blocking option drift and stale ordinals, reporting already-correct checkbox/dropdown states as no-op evidence without action attempts, expanding legal/payment/CAPTCHA/delete choice blocking, and downgrading unexpected warnings to partial. Playwright Addition 6.1 hardens typing with exact text-fingerprint approval binding, replay-resistant serialized plans, replace-only typing, sensitive/login/payment/CAPTCHA/file/readonly/disabled/hidden target blocking, locator ambiguity blocking, form-submit prevention, and field-state verification that distinguishes `verified_supported`, `verified_unsupported`, `partial`, and `completed_unverified`. Playwright Addition 5.1/6.1/7.1/8 block stale plans, target drift, mismatched or denied approvals, consumed/expired grants, locator ambiguity, changed text/option/scroll fingerprints, readonly/disabled/hidden/sensitive targets, and unusable after-observation evidence instead of overclaiming action success. Playwright Addition 5.2 keeps those features inside the canonical Screen Awareness spine: Playwright observations convert to `SemanticAdapterRegistry` browser payloads, canonical grounding consumes those adapter targets, TrustService remains the grant authority, and `DeterministicActionEngine` owns the canonical action-result vocabulary. Playwright Addition 5.3 adds adversarial regression tests for that architecture: route boundaries, source-audit checks, canonical result mapping, Deck/Ghost canonical state, and injected trust/cleanup usage. It does not attach to the user's signed-in browser profile and still does not expose form-submit/login/cookie/profile/payment/CAPTCHA execution capabilities.

What should not happen:

- Do not claim full visual certainty from clipboard or stale context.
- Do not execute screen actions silently under default policy.
- Do not send screen context to OpenAI unless provider-backed augmentation/fallback is explicitly enabled and used.
- Do not use Playwright to connect to user browser sessions, type into sensitive fields, append text, fill forms, submit forms, log in, read/write cookies, download files, handle payments, bypass CAPTCHA/anti-bot controls, verify visible screen state, or verify source truth. Click/focus/safe-field `type_text`/safe choice-control/bounded-scroll execution exists only after explicit runtime gates and exact trust approval, only in isolated temporary contexts, and only with bounded semantic before/after comparison. Playwright command completion alone is not verification. Arbitrary public-site clicking/typing/choice-changing/scrolling and unrestricted browser automation remain out of scope.

Sources: `config/default.toml`, `src/stormhelm/core/screen_awareness/service.py`, `src/stormhelm/core/screen_awareness/observation.py`, `src/stormhelm/core/screen_awareness/action.py`, `src/stormhelm/core/screen_awareness/verification.py`, `src/stormhelm/core/screen_awareness/browser_playwright.py`, `src/stormhelm/core/live_browser_integration.py`, `docs/screen-awareness-playwright-adapter.md`, `docs/live-browser-integration.md`
Tests: `tests/test_screen_awareness_phase12.py`, `tests/test_screen_awareness_action.py`, `tests/test_screen_awareness_verification.py`, `tests/test_screen_awareness_playwright_adapter_scaffold.py`, `tests/test_screen_awareness_playwright_adapter_integration.py`, `tests/test_screen_awareness_playwright_canonical_kraken.py`, `tests/test_screen_awareness_playwright_live_semantic.py`, `tests/test_screen_awareness_playwright_grounding_guidance.py`, `tests/test_screen_awareness_playwright_grounding_robustness.py`, `tests/test_screen_awareness_playwright_semantic_verification.py`, `tests/test_screen_awareness_playwright_action_preview.py`, `tests/test_screen_awareness_playwright_click_focus_execution.py`, `tests/test_live_browser_integration.py`

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
