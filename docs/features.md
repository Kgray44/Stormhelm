# Feature Inventory

Status values used here: `Implemented`, `Implemented but limited`, `Experimental`, `Scaffolded`, `Planned`, `Needs verification`, `Deprecated / old path`.

## Core Runtime

### Core Orchestrator

- What it does: Accepts chat requests, records conversation history, chooses deterministic routes before provider fallback, executes direct subsystem paths, submits tool work, and returns response contracts with route metadata.
- Use it with: `/chat/send`, UI message submission, Ghost capture, Command Deck prompt composer.
- Inputs: `ChatRequest.message`, `session_id`, `surface_mode`, `active_module`, workspace context, active context, optional explicit tool requests.
- Outputs: Assistant text, `response_contract`, `route_state`, task metadata, tool/job results, events, persisted messages.
- Settings: `openai.*`, `concurrency.*`, `tools.enabled.*`, `safety.*`.
- Edge cases: Legacy slash commands bypass planner. Provider fallback is unavailable when OpenAI is disabled. Some route-v2 work exists in the active worktree but must be verified before treating it as published behavior.
- Sources: `src/stormhelm/core/orchestrator/assistant.py`, `src/stormhelm/core/orchestrator/router.py`, `src/stormhelm/core/orchestrator/planner.py`, `src/stormhelm/core/orchestrator/planner_models.py`, `src/stormhelm/core/container.py`
- Tests: `tests/test_assistant_orchestrator.py`, `tests/test_planner.py`, `tests/test_planner_command_routing_state.py`
- Status: Implemented

### FastAPI Core API

- What it does: Exposes local HTTP endpoints for health, status, chat, history, jobs, events, notes, settings, tools, lifecycle, and snapshots.
- Use it with: `curl`, the PySide UI client, tests, local automation.
- Inputs: JSON request bodies for chat, notes, lifecycle mutations, cleanup execution, and query params for history/events/snapshot.
- Outputs: JSON payloads and server-sent event stream blocks.
- Settings: `network.host`, `network.port`, `event_stream.*`, `lifecycle.*`.
- Edge cases: `/events/stream` tracks replay cursors and sends gap events when replay is not possible. `/lifecycle/core/shutdown` schedules process termination.
- Sources: `src/stormhelm/core/api/app.py`, `src/stormhelm/core/api/schemas.py`
- Tests: `tests/test_events.py`, `tests/test_ui_client_streaming.py`, `tests/test_snapshot_resilience.py`
- Status: Implemented

### Jobs And Tool Execution

- What it does: Runs tool calls through a bounded async queue, tracks status/progress/results, persists tool runs, and publishes job events.
- Use it with: Provider tool calls, deterministic plans that submit tool requests, `/jobs`, tool registry tests.
- Inputs: Tool name, arguments, session/task context, safety classification.
- Outputs: `JobRecord`, `ToolResult`, persisted `tool_runs`, event records.
- Settings: `concurrency.max_workers`, `concurrency.queue_size`, `concurrency.default_job_timeout_seconds`, `concurrency.history_limit`, `tools.enabled.*`.
- Edge cases: Safety can reject disabled tools, shell stubs, disallowed file reads, or approval-gated actions before execution.
- Sources: `src/stormhelm/core/jobs/manager.py`, `src/stormhelm/core/jobs/models.py`, `src/stormhelm/core/tools/executor.py`, `src/stormhelm/core/tools/registry.py`, `src/stormhelm/core/safety/policy.py`
- Tests: `tests/test_job_manager.py`, `tests/test_tool_registry.py`, `tests/test_safety.py`
- Status: Implemented

### Event Streaming

- What it does: Maintains a bounded in-memory event buffer, supports recent/replay/wait operations, exposes `/events` and `/events/stream`, and feeds UI stream state.
- Use it with: UI live updates, debugging, watch surfaces, lifecycle/trust/subsystem events.
- Inputs: `EventRecord` instances from core services and tools.
- Outputs: Recent event lists, SSE `event`, `state`, `gap`, and heartbeat payloads.
- Settings: `event_stream.enabled`, `event_stream.retention_capacity`, `event_stream.replay_limit`, `event_stream.heartbeat_seconds`.
- Edge cases: Late clients can receive a replay gap and must reconcile with `/snapshot`.
- Sources: `src/stormhelm/core/events.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/bridge.py`
- Tests: `tests/test_events.py`, `tests/test_ui_client_streaming.py`, `tests/test_ui_bridge.py`
- Status: Implemented

## Planner And Routing

### Planner / Intent Routing

- What it does: Classifies natural-language requests into route families, produces route state, builds plans, and keeps native-capable requests out of generic provider fallback when a local subsystem owns the request.
- Use it with: Natural-language chat, Ghost requests, Command Deck requests.
- Inputs: Raw text, normalized text, surface mode, active module, workspace context, active request state, active context.
- Outputs: Route candidates, selected winner, tool/subsystem plan, route telemetry, clarification or unsupported states.
- Settings: Feature flags under `calculations`, `screen_awareness`, `software_control`, `web_retrieval`, `discord_relay`, `openai.enabled`.
- Edge cases: Route-v2 files and command-evaluation harnesses are present in the active worktree, but several are not tracked by `git ls-files`; treat them as needs-verification before publishing route-v2 guarantees.
- Sources: `src/stormhelm/core/orchestrator/planner.py`, `src/stormhelm/core/orchestrator/planner_models.py`, `src/stormhelm/core/orchestrator/router.py`, `src/stormhelm/core/orchestrator/browser_destinations.py`, `src/stormhelm/core/web_retrieval/service.py`
- Tests: `tests/test_planner.py`, `tests/test_planner_phase3c.py`, `tests/test_planner_structured_pipeline.py`, `tests/test_browser_destination_resolution.py`, `tests/test_web_retrieval_planner.py`
- Status: Implemented but limited

### Legacy Slash Commands

- What it does: Handles explicit slash commands for common local functions before planner/provider logic.
- Use it with: `/time`, `/system`, `/battery`, `/storage`, `/network`, `/apps`, `/recent`, `/echo`, `/read`, `/note`, `/shell`, `/open`, `/workspace`.
- Inputs: Slash command text.
- Outputs: Direct tool requests, direct responses, workspace actions, unsupported-command guidance.
- Settings: `tools.enabled.*`, `safety.allowed_read_dirs`, `safety.allow_shell_stub`.
- Edge cases: `/shell` is blocked unless shell stub safety is explicitly enabled. File reads stay allowlist-gated.
- Sources: `src/stormhelm/core/orchestrator/router.py`, `src/stormhelm/core/safety/policy.py`, `src/stormhelm/core/tools/builtins/shell_stub.py`, `src/stormhelm/core/tools/builtins/file_reader.py`
- Tests: `tests/test_assistant_orchestrator.py`, `tests/test_safety.py`
- Status: Implemented

### Fuzzy Language Evaluation

- What it does: Provides corpus-based route evaluation support for checking fuzzy utterance handling.
- Use it with: Route correctness testing and remediation passes.
- Inputs: Fuzzy evaluation cases and route-family expectations.
- Outputs: Evaluation results, provider audit signals, route correctness checks.
- Settings: Test/evaluation harness settings are code-driven, not exposed as runtime config.
- Edge cases: Some newer command-evaluation files in the active worktree are not tracked; the tracked fuzzy-eval package is the safer published reference.
- Sources: `src/stormhelm/core/orchestrator/fuzzy_eval/corpus.py`, `src/stormhelm/core/orchestrator/fuzzy_eval/models.py`, `src/stormhelm/core/orchestrator/fuzzy_eval/runner.py`
- Tests: `tests/test_fuzzy_language_evaluation.py`
- Status: Implemented but limited

## UI And Bridge

### Ghost Mode

- What it does: Provides a lightweight quick-request surface with capture, draft text, adaptive style/placement, command cards, corner readouts, and brief result state.
- Use it with: `Ctrl+Space`, quick local requests, short commands, external handoffs.
- Inputs: Keyboard capture, bridge state, command surface model, stream/chat results, adaptive background samples.
- Outputs: Submitted chat requests, Ghost messages/cards/actions/readouts, adaptive placement/style state.
- Settings: `ui.ghost_shortcut`, `ui.hide_to_tray_on_close`, bridge mode state.
- Edge cases: Ghost renders state but must not become backend authority. Adaptive background sampling is UI-only.
- Sources: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/ghost_input.py`, `src/stormhelm/ui/ghost_adaptive.py`, `assets/qml/components/GhostShell.qml`, `assets/qml/components/SignalStrip.qml`
- Tests: `tests/test_ghost_input.py`, `tests/test_ghost_adaptive.py`, `tests/test_qml_shell.py`, `tests/test_ui_bridge.py`
- Status: Implemented

### Command Deck

- What it does: Provides the deeper workspace shell with command spine, route inspector, deck panels, workspace canvas, opened items, transcript, browser/file surfaces, notes, and status panels.
- Use it with: Longer tasks, workspace review, route inspection, internal browsing/file viewing, layout management.
- Inputs: Bridge surface models, workspace state, opened item state, chat history, route state, status snapshots.
- Outputs: UI actions back to bridge/client, local surface actions, layout persistence, opened workspace items.
- Settings: `ui.poll_interval_ms`, `ui.hide_to_tray_on_close`, deck layout store under runtime state.
- Edge cases: UI panels can open surfaces and submit actions, but execution authority remains in the core or controller.
- Sources: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/controllers/main_controller.py`, `assets/qml/components/CommandDeckShell.qml`, `assets/qml/components/DeckPanelWorkspace.qml`, `assets/qml/components/WorkspaceCanvas.qml`
- Tests: `tests/test_main_controller.py`, `tests/test_main_controller_batch2_contracts.py`, `tests/test_ui_bridge_batch2_contracts.py`, `tests/test_qml_shell.py`
- Status: Implemented

### Bridge / UI State

- What it does: Converts core health/status/snapshot/chat/stream payloads into QML properties and action surfaces.
- Use it with: All QML surfaces and the main controller.
- Inputs: `/health`, `/status`, `/snapshot`, `/chat/send`, `/events/stream`, local UI actions.
- Outputs: QML properties for status, messages, route inspector, command surface, deck panels, opened items, workspace sections, adaptive Ghost state.
- Settings: Config-derived version/runtime labels, UI settings, stream state.
- Edge cases: Bridge can render pending approvals and stale/gap states but must not decide backend truth.
- Sources: `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/command_surface_v2.py`
- Tests: `tests/test_ui_bridge.py`, `tests/test_ui_bridge_authority_contracts.py`, `tests/test_ui_bridge_batch3_contracts.py`, `tests/test_command_surface.py`
- Status: Implemented

## Subsystems

### Calculations

- What it does: Handles deterministic arithmetic, engineering helpers, output formatting, verification claims, explanations, and recent traces.
- Use it with: Natural-language calculation requests, screen-aware numeric solving, direct subsystem calls from the orchestrator.
- Inputs: Operator text, normalized expression, caller context, optional screen-origin evidence.
- Outputs: Calculation result/failure, formatted answer, explanation, verification, trace, response contract.
- Settings: `calculations.enabled`, `calculations.planner_routing_enabled`, `calculations.debug_events_enabled`.
- Edge cases: Ambiguous or unsupported math returns structured failure instead of provider guesswork. Helper coverage is bounded to implemented helper matchers.
- Sources: `src/stormhelm/core/calculations/service.py`, `src/stormhelm/core/calculations/planner.py`, `src/stormhelm/core/calculations/models.py`, `src/stormhelm/core/calculations/helpers.py`
- Tests: `tests/test_calculations.py`
- Status: Implemented

### Screen Awareness

- What it does: Observes native/current context, interprets visible state, resolves semantic adapters, grounds targets, composes guidance, verifies outcomes, supports gated actions, records truthfulness/audit traces, and exposes a disabled-by-default Playwright browser semantic adapter with runtime readiness, mock semantic observation, opt-in real isolated semantic snapshot extraction, richer target grounding/ranking, bounded form/dialog summaries, guidance-only browser/web-app navigation help, verification-only before/after semantic comparison, action preview/action-plan scaffolds, trust-gated click/focus execution, trust-gated safe-field `type_text`, trust-gated safe checkbox/radio/dropdown choice controls, and trust-gated bounded scroll/scroll-to-target only when explicit runtime gates and approval pass.
- Use it with: Requests about the current screen, before/after verification, visible error/problem solving, screen-aware calculations, guided navigation.
- Inputs: Operator text, active context, workspace context, native observation, optional provider augmentation.
- Outputs: Screen response, interpretation, grounding, navigation/action/verification result, limitations, recovery state, trace summary.
- Settings: `screen_awareness.*`, especially `enabled`, `planner_routing_enabled`, `action_policy_mode`, `verification_enabled`, and `screen_awareness.browser_adapters.playwright.*`.
- Edge cases: Clipboard-only evidence is not treated as the live screen. Actions default to `confirm_before_act`. Provider visual augmentation is available only if a provider is configured. Playwright is disabled by default, dev-gated for mock observations, no dependency required in CI, and has no browser launch/connect by default. Live Playwright semantic checks require `STORMHELM_LIVE_BROWSER_TESTS=true`, provider gates, `allow_browser_launch = true`, and an isolated temporary browser context. The live path extracts bounded semantic controls/forms/dialogs/text summaries, redacts sensitive field values, clears temporary context state, ranks grounding candidates by semantic evidence, preserves ambiguity, labels stale observations, reports iframe/shadow-DOM/large-page partial limitations, handles common label/state synonyms, summarizes form-like structures, and can compare two snapshots as semantic evidence only. Addition 5 can execute only click/focus from a grounded plan when `allow_actions`, `allow_dev_actions`, and the specific click/focus gate are enabled and trust approval is granted; it then captures after-observation and runs semantic comparison. Addition 6 adds only `type_text` into safe, non-sensitive text/search fields when `allow_type_text` and `allow_dev_type_text` are also enabled; it binds approval to the text fingerprint, redacts raw text from reporting surfaces, and verifies only bounded value-summary changes when available. Addition 7 adds only safe `check`, `uncheck`, and `select_option` when `allow_dev_choice_controls` plus the specific choice gate are enabled; approval binds to action, target, expected checked state, and option fingerprint. Addition 8 adds only bounded `scroll` and `scroll_to_target` when `allow_dev_scroll` plus the specific scroll gate are enabled; approval binds to action, direction, amount, max attempts, and target phrase, target search is bounded, already-visible targets are no-op evidence, target-not-found/ambiguous outcomes remain truthful, and no click/type/select/submit side effects are issued. Addition 7.1 blocks target type changes, option value/ordinal drift, stale ordinals, duplicate/missing/disabled/sensitive options, and legal/payment/CAPTCHA/delete/security choice contexts; it reports already-correct checkbox/dropdown states as no-op evidence, prevents Enter/form-submit behavior, and treats unexpected submit/navigation/warnings as not success. Addition 6.1 keeps typing replace-only, blocks append/add-more modes, expands sensitive field and text detection, proves raw sentinel text is absent from status/events/Deck/audit/reporting surfaces, prevents Enter/submission behavior, and distinguishes unchanged fields from unverifiable summaries. Addition 5.1/6.1/7.1/8 block stale plans, target drift, locator ambiguity, mismatched/denied/expired/consumed grants, sensitive/readonly/hidden/disabled targets, changed text/options/scroll arguments, and unusable after-observations without treating Playwright command return as success. Addition 5.2 maps Playwright observations into `SemanticAdapterRegistry` browser semantics, lets `DeterministicGroundingEngine` consume those targets, and maps Playwright execution results into canonical Screen Awareness action summaries for Ghost/Deck. Addition 5.3 hardens this canonical path with route-pressure and source-audit tests so planner/UI code cannot execute Playwright directly and provider-local provenance remains secondary to canonical state. Form submit/login/cookie/user-profile/payment/CAPTCHA/download actions remain unsupported, arbitrary public-site automation remains unsupported, and Playwright never claims visible-screen or truth verification.
- Sources: `src/stormhelm/core/screen_awareness/service.py`, `src/stormhelm/core/screen_awareness/observation.py`, `src/stormhelm/core/screen_awareness/verification.py`, `src/stormhelm/core/screen_awareness/action.py`, `src/stormhelm/core/screen_awareness/browser_playwright.py`, `src/stormhelm/core/screen_awareness/models.py`
- Tests: `tests/test_screen_awareness_service.py`, `tests/test_screen_awareness_phase12.py`, `tests/test_screen_awareness_verification.py`, `tests/test_screen_awareness_action.py`, `tests/test_screen_awareness_playwright_adapter_scaffold.py`, `tests/test_screen_awareness_playwright_adapter_integration.py`, `tests/test_screen_awareness_playwright_canonical_kraken.py`, `tests/test_screen_awareness_playwright_live_semantic.py`, `tests/test_screen_awareness_playwright_grounding_guidance.py`, `tests/test_screen_awareness_playwright_grounding_robustness.py`, `tests/test_screen_awareness_playwright_semantic_verification.py`, `tests/test_screen_awareness_playwright_action_preview.py`, `tests/test_screen_awareness_playwright_click_focus_execution.py`, `tests/test_live_browser_integration.py`, `tests/test_live_browser_provider_smoke.py`
- Status: Implemented but limited

### Web Retrieval

- What it does: Safely extracts public webpage text, links, optional rendered evidence through a baseline HTTP provider or optional Obscura CLI provider, and optional Obscura CDP headless page inspection only when the installed CDP endpoint proves navigation/page-inspection support. Addition 2.2 adds opt-in live integration checks for local Obscura CLI/CDP compatibility. This is evidence extraction, not browser control.
- Use it with: Natural-language requests like "summarize/read/extract links/render this public URL", "render this page" when a current page URL is available, or explicit CDP requests such as "use Obscura CDP to inspect this URL". It does not replace browser open/search routing.
- Inputs: Public `http`/`https` URLs, intent, provider preference, include-links/include-html flags.
- Outputs: `WebEvidenceBundle`, `RenderedWebPage`, extracted links, provider trace, typed failures, compact Ghost state, and a richer Command Deck evidence station.
- Settings: `web_retrieval.*`, `web_retrieval.http.*`, `web_retrieval.obscura.*`, `web_retrieval.obscura.cdp.*`, `tools.enabled.web_retrieval_fetch`.
- Edge cases: Private/local/file/credential URLs, localhost aliases, odd loopback encodings, control-character URLs, overlong URLs, and redirects into blocked targets are blocked by the public URL safety gate. Obscura CLI and Obscura CDP are disabled by default and report `binary_missing`, `startup_failed`, `endpoint_unreachable`, `protocol_probe_failed`, `endpoint_incompatible`, `cdp_navigation_unsupported`, `timeout`, `process_error`, `partial`, `provider_unavailable`, `diagnostic_only`, or fallback states truthfully. CDP endpoint discovery is not enough to claim page inspection support; if navigation is unsupported, Stormhelm does not select CDP for extraction and recommends Obscura CLI. CDP binds to localhost, starts only on explicit provider use, stops after inspection/diagnostics, and has the strict `headless_cdp_page_evidence` claim ceiling. The manual compatibility probe and live browser integration runner check binary/version/startup/endpoint/websocket/navigation/cleanup behavior without running in normal CI. Extracted content is page evidence only; Stormhelm does not independently check the source's claims, does not claim it is the user's visible screen, does not use logged-in context/cookies, and does not click/type/submit forms.
- Sources: `src/stormhelm/core/web_retrieval/*`, `src/stormhelm/core/live_browser_integration.py`, `src/stormhelm/core/tools/builtins/web_retrieval.py`, `src/stormhelm/core/orchestrator/planner.py`, `src/stormhelm/core/orchestrator/intent_frame.py`, `src/stormhelm/ui/command_surface_v2.py`
- Tests: `tests/test_web_retrieval_config.py`, `tests/test_web_retrieval_safety.py`, `tests/test_web_retrieval_models.py`, `tests/test_web_retrieval_providers.py`, `tests/test_web_retrieval_service.py`, `tests/test_web_retrieval_planner.py`, `tests/test_web_retrieval_ui.py`, `tests/test_web_retrieval_cdp.py`, `tests/test_web_retrieval_cdp_reliability.py`, `tests/test_live_browser_integration.py`, `tests/test_live_browser_provider_smoke.py`
- Status: Implemented but limited

### Software Control

- What it does: Resolves known software targets, discovers trusted sources, builds typed operation plans, gates install/update/uninstall/repair, verifies local install state for some apps, and launches via native app control when possible.
- Use it with: Requests like install/update/uninstall/repair/verify/launch software.
- Inputs: Operator text, operation type, target name, request stage, approval state, active module/session.
- Outputs: Software plan, checkpoints, verification, trace, response contract, pending approval state or recovery handoff.
- Settings: `software_control.*`, `safety.unsafe_test_mode`, trust settings.
- Edge cases: Package-manager execution is not fully wired in this pass; install/update/uninstall/repair can produce a prepared plan and then hand off to recovery when the execution adapter is unavailable.
- Sources: `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/software_control/planner.py`, `src/stormhelm/core/software_control/catalog.py`, `src/stormhelm/core/software_control/models.py`
- Tests: `tests/test_software_control.py`, `tests/test_assistant_software_control.py`, `tests/test_ui_bridge_software_contracts.py`
- Status: Implemented but limited

### Software Recovery

- What it does: Classifies software-control failures, builds redacted troubleshooting context, proposes local recovery steps, optionally uses cloud advisory fallback when enabled, and returns unverified recovery results.
- Use it with: Failed software routes, adapter mismatch, verification mismatch, unresolved targets.
- Inputs: Failure event, operation plan, verification payload, local signals.
- Outputs: Recovery hypotheses, plan steps, route switch candidate, result, verification status.
- Settings: `software_recovery.*`, `openai.enabled` for cloud fallback.
- Edge cases: Cloud fallback is disabled by default. Recovery prepares bounded next steps; it does not claim final repair unless verified elsewhere.
- Sources: `src/stormhelm/core/software_recovery/service.py`, `src/stormhelm/core/software_recovery/cloud.py`, `src/stormhelm/core/software_recovery/models.py`
- Tests: `tests/test_software_recovery.py`
- Status: Implemented but limited

### Discord Relay / Dispatch

- What it does: Resolves trusted Discord aliases, selects current payloads, builds previews, binds fingerprints, blocks stale/duplicate/sensitive sends, asks for trust approval, and can dispatch through local client automation.
- Use it with: Requests like "send this to Baby" after a current page/file/text/note is available.
- Inputs: Destination alias, active context, workspace context, selected/clipboard/recent payload candidates, preview stage, dispatch stage, trust decision.
- Outputs: Preview, dispatch attempt, trace, active request state, adapter execution metadata.
- Settings: `discord_relay.*`, `discord_relay.trusted_aliases.*`, trust settings.
- Edge cases: Official bot/webhook routes are disabled by default. Local dispatch depends on the user's Discord client/session and can fail at navigation/send/verification stages. Preview expires and can be invalidated by payload mutation.
- Sources: `src/stormhelm/core/discord_relay/service.py`, `src/stormhelm/core/discord_relay/adapters.py`, `src/stormhelm/core/discord_relay/models.py`, `config/default.toml`
- Tests: `tests/test_discord_relay.py`
- Status: Implemented but limited

### Durable Task Graph / Continuity

- What it does: Tracks multi-step task state, job links, blockers, checkpoints, artifacts, evidence, trust pending/granted/denied events, and "where left off" summaries.
- Use it with: Tool execution, task continuity requests, workspace resume, trust-bound tasks.
- Inputs: Execution plans, job events, verification/recovery/trust signals, session/workspace context.
- Outputs: Task records, active task summary, next steps, resume assessment, task memory sync.
- Settings: Database/runtime path settings; no standalone task feature flag in default config.
- Edge cases: Continuity is persisted, but workspace fallback must not impersonate durable task state.
- Sources: `src/stormhelm/core/tasks/service.py`, `src/stormhelm/core/tasks/models.py`, `src/stormhelm/core/tasks/repository.py`, `src/stormhelm/core/memory/database.py`
- Tests: `tests/test_task_graph.py`, `tests/test_snapshot_resilience.py`
- Status: Implemented

### Approvals / Trust / Audit

- What it does: Creates approval requests, grants once/task/session permissions with TTLs, expires stale state, records audit entries, and attaches request state for UI.
- Use it with: Software execution, Discord relay dispatch, trust-gated tools, external handoff, file operations, maintenance actions.
- Inputs: `TrustActionRequest`, approval/denial decisions, task/session/runtime binding.
- Outputs: `TrustDecision`, `ApprovalRequest`, `PermissionGrant`, `AuditRecord`, UI request state.
- Settings: `trust.enabled`, `trust.session_grant_ttl_seconds`, `trust.once_grant_ttl_seconds`, `trust.pending_request_ttl_seconds`, `trust.audit_recent_limit`.
- Edge cases: Grants can be invalidated by expiry, runtime/task mismatch, or stale pending requests.
- Sources: `src/stormhelm/core/trust/service.py`, `src/stormhelm/core/trust/models.py`, `src/stormhelm/core/trust/repository.py`, `src/stormhelm/core/safety/policy.py`
- Tests: `tests/test_trust_service.py`, `tests/test_safety.py`
- Status: Implemented

### Adapter Contracts

- What it does: Describes adapter trust tier, approval, rollback, verification, tool bindings, route assessment, and execution metadata.
- Use it with: Safety policy, tool executor, Discord relay route assessment, web retrieval, system/app/file/external action tools.
- Inputs: Adapter contract declarations and tool arguments.
- Outputs: Contract snapshots, route assessments, attached metadata, execution reports.
- Settings: No standalone config; used by safety/tool execution.
- Edge cases: A route can be blocked if no healthy contract-backed adapter is available. The Obscura CLI web adapter has a strict `rendered_page_evidence` ceiling. The Obscura CDP adapter has a strict `headless_cdp_page_evidence` ceiling. The Playwright browser semantic adapter has strict `browser_semantic_observation`, `browser_semantic_observation_comparison`, `browser_semantic_action_preview`, and runtime-gated `browser_semantic_action_execution` ceilings. Playwright click/focus/safe-field type/safe choice/bounded-scroll capability is disabled by default and available only when runtime gates plus exact trust approval pass; stale or drifted targets, changed text/option/scroll fingerprints, stale option ordinals, sensitive fields/choice controls/pages, target-not-found/ambiguous scroll outcomes, unexpected submit/navigation/warnings, and ambiguous locators fail closed or downgrade. None can claim independent truth checking, visible-screen state, logged-in account state, form-submit/cookie capability, or unverified action success.
- Sources: `src/stormhelm/core/adapters/contracts.py`, `src/stormhelm/core/tools/executor.py`, `src/stormhelm/core/safety/policy.py`
- Tests: `tests/test_adapter_contracts.py`
- Status: Implemented

### Semantic Memory / Retrieval

- What it does: Stores provenance-bearing memory records, query logs, suppressed previews, freshness state, and family-aware retrieval metadata.
- Use it with: Context recall, task memory sync, workspace/session memory, semantic retrieval.
- Inputs: Memory records, task summaries, workspace/session scope, query text.
- Outputs: Ranked memory records, freshness/confidence metadata, suppressed preview information.
- Settings: Database path, runtime storage paths; retention behavior is service-owned.
- Edge cases: Retrieval is local and heuristic; no external vector service is configured in default settings.
- Sources: `src/stormhelm/core/memory/service.py`, `src/stormhelm/core/memory/models.py`, `src/stormhelm/core/memory/repositories.py`, `src/stormhelm/core/memory/database.py`
- Tests: `tests/test_semantic_memory.py`, `tests/test_storage.py`
- Status: Implemented but limited

### Lifecycle / Startup / Install Management

- What it does: Tracks install/runtime/startup/shell/tray state, bootstrap evaluation, cleanup plans, lifecycle holds, startup registry mutation, and backend shutdown.
- Use it with: Startup settings, tray behavior, packaged builds, cleanup/uninstall preparation, UI recovery.
- Inputs: Shell presence reports, startup policy mutations, cleanup target requests, lifecycle resolution requests.
- Outputs: Lifecycle snapshot, startup commands, cleanup plan/execution state, hold/resolution state, crash records.
- Settings: `lifecycle.*`, storage/runtime paths, UI tray settings.
- Edge cases: Startup registration is Windows registry based. Cleanup execution requires confirmation payloads and preserves configured targets.
- Sources: `src/stormhelm/core/lifecycle/service.py`, `src/stormhelm/core/lifecycle/models.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/controllers/main_controller.py`
- Tests: `tests/test_lifecycle_service.py`, `tests/test_main_controller_lifecycle.py`, `tests/test_ui_lifecycle_bridge.py`
- Status: Implemented

### Settings / Config

- What it does: Loads default TOML, optional development/portable/user config, `.env`, environment overrides, runtime paths, and dataclass config models.
- Use it with: Local development, packaged runtime, tests, feature flags.
- Inputs: `config/default.toml`, an optional local development TOML file copied from `config/development.toml.example`, portable/user config files, `.env`, process environment.
- Outputs: `AppConfig` and runtime path config.
- Settings: See [settings.md](settings.md).
- Edge cases: `STORMHELM_UNSAFE_TEST_MODE=true` widens several gates for tests and should not be used as normal runtime posture.
- Sources: `src/stormhelm/config/loader.py`, `src/stormhelm/config/models.py`, `config/default.toml`, `config/development.toml.example`
- Tests: `tests/test_config_loader.py`
- Status: Implemented

### Telemetry / Watch / Debug Surfaces

- What it does: Publishes status snapshots, event stream state, operational awareness, network monitor state, hardware telemetry, lifecycle state, route traces, and recent subsystem traces.
- Use it with: `/status`, `/snapshot`, Command Deck Systems/Watch panels, troubleshooting.
- Inputs: Core container state, network monitor samples, events, subsystem status snapshots.
- Outputs: Status/snapshot JSON, UI panels, stream reconciliation.
- Settings: `hardware_telemetry.*`, `event_stream.*`, `network.*`, `logging.*`.
- Edge cases: Hardware telemetry may depend on helper/provider availability and optional HWiNFO configuration.
- Sources: `src/stormhelm/core/container.py`, `src/stormhelm/core/system/hardware_telemetry.py`, `src/stormhelm/core/network/monitor.py`, `src/stormhelm/core/operations/service.py`, `src/stormhelm/ui/bridge.py`
- Tests: `tests/test_hardware_telemetry.py`, `tests/test_network_monitor.py`, `tests/test_operational_awareness.py`, `tests/test_ui_bridge_batch3_contracts.py`
- Status: Implemented but limited

### Voice Input / Output

- What it does: Provides a disabled-by-default voice subsystem with typed manual voice turns, Windows manual microphone-to-Core-to-speaker conversations, typed-response spoken output, OpenAI streaming TTS to progressive Windows local speaker playback, controlled audio STT, controlled TTS artifact generation, explicit push-to-talk capture state, playback-provider boundaries, output interruption, wake readiness/mock events, a local wake provider boundary, wake-to-Ghost presentation state, VAD/end-of-speech, diagnostics, events, and Ghost/Deck bridge actions. Speech-derived requests enter the existing core/orchestrator boundary; voice providers do not execute tools directly.
- Use it with: `VoiceService`, `/chat/send` typed assistant output when spoken responses are enabled, `/voice/capture/listen-turn`, `/voice/output/stop-speaking`, `/voice/capture/start`, `/voice/capture/stop`, `/voice/capture/cancel`, `/voice/capture/submit`, `/voice/capture/turn`, `/voice/playback/stop`, `/voice/wake/readiness`, `/voice/wake/simulate`, `/voice/vad/readiness`, Ghost/Deck voice actions, `/status` voice diagnostics, `scripts/voice_doctor.py`, `scripts/voice_typed_response_smoke.py`, `scripts/voice_input_smoke.py`, and `scripts/voice_conversation_smoke.py`.
- Inputs: Typed prompts, manual transcript text, explicit user-triggered microphone listen sessions, controlled audio metadata, explicit capture start/stop/cancel/submit controls, mock wake event controls, local wake backend state when explicitly configured, mock VAD activity controls during active capture/listen windows, configured provider state, and optional mock-provider test behavior.
- Outputs: `VoiceTurnResult`, `VoiceTranscriptionResult`, `VoiceSpeechSynthesisResult`, `VoiceStreamingTTSResult`, `VoiceLivePlaybackResult`, `VoicePlaybackResult`, `VoiceCaptureResult`, `VoiceWakeEvent`, `VoiceWakeSession`, `VoiceWakeGhostRequest`, `VoiceActivityEvent`, `VoiceVADSession`, voice events, `VOICE_SPEAK_DECISION` diagnostics, status snapshot fields, and compact UI voice state.
- Settings: `voice.*`, `voice.openai.*`, `voice.playback.*`, `voice.capture.*`, `voice.wake.*`, `voice.vad.*`, `openai.enabled`, `OPENAI_API_KEY` or `STORMHELM_OPENAI_API_KEY`.
- Edge cases: Disabled by default. Availability requires voice enabled, non-disabled mode, OpenAI provider config, OpenAI enabled, an API key, and configured models. Windows microphone input requires explicit listen/capture gates, the local capture provider, and a usable default input device. Windows progressive speaker playback requires `voice.playback.provider=local`, streaming playback enabled, dev playback allowed, and a usable default Windows output device. Local wake also requires explicit wake gates and an available local backend. Wake-to-Ghost is presentation only. VAD detects audio activity only and can help finalize capture; it is not semantic completion or command authority. Always-listening command mode, continuous listening, robust always-on local wake word, unbounded Realtime sessions, non-Windows microphone/speaker streaming, and independent voice command authority are not implemented. Wake does not start capture, route Core, call OpenAI, or use cloud services. Playback start is speaker-provider state, not task completion or proof from an independent human-heard sensor.
- Sources: `src/stormhelm/core/voice/service.py`, `src/stormhelm/core/voice/models.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/availability.py`, `src/stormhelm/core/voice/events.py`, `src/stormhelm/core/api/app.py`, `src/stormhelm/ui/bridge.py`, `src/stormhelm/ui/client.py`, `src/stormhelm/ui/controllers/main_controller.py`, `src/stormhelm/ui/voice_surface.py`, `config/default.toml`, `docs/voice-0-foundation.md`
- Tests: `tests/test_voice_l6_manual_conversation.py`, `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_manual_turn.py`, `tests/test_voice_audio_turn.py`, `tests/test_voice_stt_provider.py`, `tests/test_voice_tts_provider.py`, `tests/test_voice_playback_service.py`, `tests/test_voice_core_bridge_contracts.py`, `tests/test_voice_events.py`, `tests/test_voice_state.py`, `tests/test_voice_ui_state_payload.py`, `tests/test_voice_bridge_controls.py`, `tests/test_voice_wake_config.py`, `tests/test_voice_wake_service.py`, `tests/test_voice_local_wake_provider.py`, `tests/test_voice_wake_ghost_service.py`, `tests/test_voice_wake_ghost_payload.py`, `tests/test_voice_vad_config.py`, `tests/test_voice_vad_provider.py`, `tests/test_voice_vad_service.py`, `tests/test_latency_l5_voice_streaming_first_audio.py`, `tests/test_latency_l55_windows_voice_runtime.py`
- Status: Implemented for Windows manual voice conversations and Windows typed-response spoken output; limited for wake/Realtime and unsupported for non-Windows microphone/speaker streaming

### Packaging / Build Tooling

- What it does: Provides source launch scripts, PyInstaller portable packaging, optional Inno Setup installer packaging, and report rendering helpers.
- Use it with: Development startup, portable build creation, installer build preparation.
- Inputs: Python environment, package metadata, config/assets, optional Inno Setup path.
- Outputs: Core/UI build artifacts, portable release folder, zip, optional installer.
- Settings: `pyproject.toml`, scripts parameters, runtime path config.
- Edge cases: Installer build requires `ISCC.exe`. Packaging output should be verified on a clean Windows environment before release.
- Sources: `pyproject.toml`, `scripts/run_core.ps1`, `scripts/run_ui.ps1`, `scripts/dev_launch.ps1`, `scripts/package_portable.ps1`, `scripts/package_installer.ps1`
- Tests: `tests/test_launcher.py`, `tests/test_shader_assets.py`
- Status: Implemented but limited

## Planned Or Scaffolded

### Official Discord Bot / Webhook Routes

- What it does: Scaffolded adapter path exists, but default config disables bot/webhook routing.
- Use it with: Future relay route work.
- Inputs: Not enabled by default.
- Outputs: Unavailable unless implemented/enabled.
- Settings: `discord_relay.bot_webhook_routes_enabled=false`.
- Edge cases: Do not document official bot delivery as available current behavior.
- Sources: `src/stormhelm/core/discord_relay/adapters.py`, `src/stormhelm/core/discord_relay/service.py`, `config/default.toml`
- Tests: `tests/test_discord_relay.py`
- Status: Scaffolded

### Unrestricted Shell / Computer Control

- What it does: Not implemented as unrestricted shell access. The current shell tool is a disabled stub and trust-gated action tools are bounded.
- Use it with: Tests and future design work only.
- Inputs: `/shell` command or `shell_command` tool request.
- Outputs: Blocked unless safety config enables the stub.
- Settings: `tools.enabled.shell_command=false`, `safety.allow_shell_stub=false`.
- Edge cases: Unsafe test mode can bypass gates; do not use it for normal operation.
- Sources: `src/stormhelm/core/tools/builtins/shell_stub.py`, `src/stormhelm/core/safety/policy.py`, `config/default.toml`
- Tests: `tests/test_safety.py`
- Status: Scaffolded
