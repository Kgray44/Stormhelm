# Screen Awareness Playwright Browser Adapter

This page defines the Playwright-backed browser semantic adapter for Stormhelm. Addition 1 turns the scaffold into runtime readiness plus mock semantic observation for backend/UI plumbing. Addition 1.1 audits and hardens that behavior through the runtime config, container, Screen Awareness service, bounded events, status snapshots, and Command Deck payload path. Addition 2.2 adds opt-in live semantic smoke diagnostics. Playwright Addition 2 adds real, bounded semantic snapshot extraction from isolated temporary Playwright browser contexts when explicit dev/runtime gates and local dependencies are present. Playwright Addition 3 deepens semantic target grounding, candidate ranking, ambiguity handling, form/dialog summaries, and guidance text while remaining observation/guidance-only. Playwright Addition 3.1 hardens observation and grounding for messy real-world page structures without adding browser actions. Playwright Addition 4 adds verification-only before/after semantic comparison without executing browser actions. Playwright Addition 4.1 adds backend-owned browser action previews and trust-gated plan scaffolds. Playwright Addition 5 adds the first execution path for trust-gated click and focus only, still inside isolated temporary Playwright contexts and still followed by semantic before/after comparison. Playwright Addition 5.1 hardens that path against stale plans, target drift, exact trust-binding mistakes, locator ambiguity, cleanup failures, and verification ambiguity. Playwright Addition 5.2 unifies the implementation with the canonical Screen Awareness pipeline so Playwright is a provider/adapter/executor seam, not a second Screen Awareness authority.

## Purpose

Playwright may become a browser-specific semantic adapter for Screen Awareness. Its job is to provide structured browser/page semantics: accessibility-style snapshots, DOM summaries, visible control lists, role/name/label based grounding candidates, current URL, title, and guidance hints.

It is not command authority. Stormhelm Core remains command authority, Screen Awareness owns observation and grounding, adapter contracts define claim ceilings, trust gates decide whether actions may proceed, verification decides what changed, and Ghost/Deck render backend-owned state only.

## Addition 1 Runtime Posture

Addition 1 implements:

- backend-owned readiness state
- optional dependency detection for the Python `playwright` package
- optional, bounded browser-engine availability checks when a safe checker is provided
- a dev-gated mock semantic observation provider
- deterministic grounding against mock observations
- guidance text for found, ambiguous, and missing mock targets
- bounded status/snapshot summaries
- bounded Screen Awareness events for readiness, mock observation, grounding, and guidance

It still does not install Playwright, require Playwright in CI, connect to user browser sessions, click, type, scroll, fill forms, submit forms, log in, read/write cookies, download files, bypass CAPTCHA/anti-bot systems, verify visible screen state, or verify source truth.

Addition 1.1 verifies the in-scope behavior is reachable through normal backend-owned paths. Disabled config returns disabled readiness and blocks mock observations with an explicit unavailable observation. Enabled, dev-gated mock mode can be reached through the runtime container and Screen Awareness service. Mock grounding emits separate completed, ambiguous, and no-match event states, and guidance remains compact and non-action. Future action and verification seams return typed `unsupported` results.

Addition 2.2 keeps normal runtime behavior unchanged and adds live diagnostics only when `STORMHELM_LIVE_BROWSER_TESTS=true` and `STORMHELM_ENABLE_LIVE_PLAYWRIGHT=true`. Playwright Addition 2 moves the real live semantic extraction into `PlaywrightBrowserSemanticAdapter.observe_live_browser_page(...)`. The live semantic smoke launches only when `STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH=true`, uses an isolated temporary browser context, never attaches to the user's signed-in browser profile, extracts bounded URL/title/control/form/dialog/text summaries, runs grounding/guidance, closes the browser, clears temporary cookies, and keeps `action_supported = false`.

Playwright Addition 3 keeps the same launch and dependency posture, but makes grounding more useful once a semantic observation exists. It ranks controls by role, accessible name, label, visible text, safe value summaries, state terms such as disabled/required/checked, ordinal hints such as first/second, dialog/alert text, and simple nearby ordering context. Candidate records include bounded evidence terms, mismatch terms, source provider, source observation id, claim ceiling, confidence, and ambiguity reason.

Playwright Addition 3.1 extends that behavior for real-world markup. Live semantic extraction now records readonly state, placeholder/nearby-label fallbacks, aria label sources, icon/nested-button names when exposed by the semantic layer, large-control truncation, partial observation limitations, iframe limitations, cross-origin iframe limitations, and shadow-DOM limitations. Grounding adds deterministic synonym and negation handling such as e-mail/email, search/find, field/input/textbox, dropdown/select/combobox, not disabled, not required, readonly, and last-item ordinal hints. Form summaries include multiple form/form-like groups, inferred form-like regions, readonly fields, unchecked required checkboxes/radios, possible submit/continue controls, and sensitive-field redaction.

Playwright Addition 4 compares two already-captured `BrowserSemanticObservation` snapshots. It detects bounded semantic changes such as URL/title changes, controls added/removed, enabled/required/readonly/checked/expanded state changes, safe value-summary changes, links added/removed, warnings/dialogs added/removed, form summary changes, and observation limitation changes. Expected outcomes can be classified as `supported`, `unsupported`, `partial`, `ambiguous`, `unverifiable`, `stale_basis`, `insufficient_basis`, or `failed`. This is comparison evidence only; it is not action completion, visible-screen verification, or source-truth verification.

Readiness states:

- `disabled`: config is off; this is normal.
- `dev_gate_required`: config is enabled but `allow_dev_adapter` is false.
- `dependency_missing`: live runtime was requested but the Python package is unavailable.
- `browsers_missing`: a safe engine check was provided and reported missing engines.
- `mock_ready`: dev-gated mock observation is available without Playwright installed.
- `runtime_ready`: live runtime prerequisites are present; Playwright Addition 2 can run isolated semantic observation only if browser launch is explicitly allowed.
- `unavailable`: config requested unsupported scaffold behavior.
- `failed`: a bounded readiness check raised an exception.

## Relationship To Screen Awareness

Screen Awareness remains the owning subsystem for:

- observation
- interpretation
- grounding
- guidance
- action planning
- verification
- workflow continuity and learning

The Playwright adapter is an optional semantic input. It returns observations and grounding candidates to Screen Awareness. The planner and UI must not call Playwright directly.

## Addition 5.2 Canonical Path

Addition 5.2 makes the ownership map explicit:

| Concern | Canonical owner | Playwright role |
|---|---|---|
| Top-level request handling/status | `ScreenAwarenessSubsystem` | Exposes bounded readiness and latest provider summaries through subsystem status. |
| Adapter resolution | `SemanticAdapterRegistry` and `BrowserSemanticAdapter` | Converts `BrowserSemanticObservation` into the canonical `adapter_semantics["browser"]` payload. |
| Grounding | `DeterministicGroundingEngine` | Supplies browser controls as `AppSemanticTarget` / adapter-semantic candidates. |
| Guidance/navigation | `DeterministicNavigationEngine` plus response composition | Supplies provider detail and provenance, but does not own user-facing route authority. |
| Action planning/gating/result language | `DeterministicActionEngine` and Screen Awareness service | Executes scoped click/focus through the provider seam and maps results into canonical `ActionExecutionResult` summaries. |
| Approval/grants/audit | `TrustService` | Requests/evaluates exact grants; Playwright does not create a parallel approval path. |
| Verification | Screen Awareness semantic comparison/verification | Supplies before/after observations; comparison remains bounded semantic evidence only. |
| UI | Command surface from backend status | Renders canonical state plus Playwright provenance; UI does not infer execution state. |

`ScreenAwarenessSubsystem.resolve_playwright_browser_semantics(...)` and `build_playwright_canonical_context(...)` are the bridge methods. They turn a Playwright semantic observation into the same browser adapter resolution and semantic targets used by other screen-aware flows. `map_playwright_browser_action_execution_result(...)` turns a browser-specific execution result into canonical action status such as `verified_success`, `attempted_unverified`, `planned`, `blocked`, `ambiguous`, or `failed`.

What remains Playwright-specific:

- isolated browser launch and cleanup
- bounded semantic snapshot extraction
- browser-specific locator resolution for click/focus
- browser-specific target fingerprint/drift checks
- browser-specific before/after observation capture

What is not Playwright-specific:

- planner route authority
- semantic adapter registry ownership
- canonical grounding language
- trust approval and grant consumption
- canonical action-result vocabulary
- status/Deck/Ghost authority

The scaffold seam is `PlaywrightBrowserSemanticAdapter` with these operations:

- `get_readiness()`
- `observe_mock_browser_page(context)`
- `observe_live_browser_page(url, fixture_mode=False, context_options=None)`
- `observe_browser_page(context)`
- `get_semantic_snapshot(context)`
- `adapter_semantics_payload(observation)` to feed canonical `adapter_semantics["browser"]`
- `ground_target(target_phrase, observation)`
- `produce_guidance_step(candidate)`
- `compare_semantic_observations(before, after, expected=None)`
- `verify_semantic_change(request, before=..., after=...)`
- `preview_semantic_action(observation, target_phrase, action_phrase)` preview only
- `build_semantic_action_plan(preview)` preview only
- `request_semantic_action_execution(plan, url=..., trust_service=...)` approval/check path for click/focus only
- `execute_semantic_action(plan, url=..., trust_service=...)` gated click/focus execution only
- `get_latest_playwright_action_execution_summary()`
- `build_action_preview(candidate)` compatibility preview, still non-executable
- `verify_after_action(before, after, expected_change)` future action verification only, still unsupported

Current runtime posture is disabled unless explicitly enabled and dev-gated. With `allow_dev_adapter = true`, the mock provider can produce labeled mock observations for tests and UI plumbing without Playwright installed. With `enabled = true`, `allow_dev_adapter = true`, `allow_browser_launch = true`, an installed Playwright package, and installed browser engine, the adapter can launch an isolated temporary browser context for semantic observation. Semantic before/after comparison operates only on observations that already exist. Addition 4.1 can build `BrowserSemanticActionPreview` and `BrowserSemanticActionPlan` objects from grounded semantic targets. Addition 5 executes only `click` and `focus` when `allow_actions = true`, `allow_dev_actions = true`, and the specific `allow_click` or `allow_focus` gate is enabled, and only after the existing trust service grants approval. Addition 5.1 revalidates plan freshness and target fingerprint before trust/launch, re-resolves the target in an execution-time observation, blocks locator ambiguity or role/selector disagreement, records cleanup status, and treats unusable after-observation evidence as `completed_unverified` rather than success. Typing, scrolling, form fill/submit, login, cookies, user-profile attachment, payment, CAPTCHA, visible-screen verification, and truth verification remain unsupported.

## Relationship To Web Retrieval And Obscura

Obscura remains the Web Retrieval path for public page extraction:

- HTTP extraction
- Obscura CLI rendering
- Obscura CDP headless page evidence
- rendered text, links, title, final URL, network and console summaries

Playwright is complementary, not a replacement. Its future role is browser/web-app semantic grounding and guided navigation. It must not replace Obscura, `browser_destination/open`, or existing Screen Awareness.

## Adapter Boundaries

Adapter id: `screen_awareness.browser.playwright`

Trust tier: `local_browser_semantic_adapter`

Claim ceilings: `browser_semantic_observation`, `browser_semantic_observation_comparison`, `browser_semantic_action_preview`, and runtime-gated `browser_semantic_action_execution`

Declared observation capabilities:

- `browser.semantic_observe`
- `browser.extract_accessibility_snapshot`
- `browser.extract_dom_summary`
- `browser.locate_element_by_role`
- `browser.locate_element_by_text`
- `browser.locate_element_by_label`
- `browser.report_current_url`
- `browser.report_title`
- `browser.report_visible_controls`

Declared preview-only capabilities:

- `browser.action.preview`
- `browser.action.plan_preview`

Runtime-gated execution capabilities:

- `browser.input.click`
- `browser.input.focus`

These are available only when the Playwright adapter is enabled, browser launch is allowed, action gates are enabled, the specific click/focus gate is enabled, the dev action gate is enabled, Playwright runtime readiness passes, a grounded target remains fresh, safe, unchanged, and unambiguous, and the trust service grants approval bound to the exact action kind and target fingerprint. They are disabled in default config and in the live browser diagnostic profile.

Not declared in this phase:

- `browser.input.type`
- `browser.input.scroll`
- `browser.form.fill`
- `browser.form.submit`
- `browser.login`
- `browser.cookies.read`
- `browser.cookies.write`
- `browser.payment`
- `browser.download`
- `browser.visible_screen_verify`
- `browser.truth_verify`
- `browser.unrestricted_control`

## Observation Model

`BrowserSemanticObservation` is the scaffold observation payload. It carries page URL/title, context kind, controls, text regions, forms, landmarks, tables, dialogs, alerts, limitations, confidence, and claim ceiling. It is bounded semantic evidence, not raw full DOM storage.

`BrowserSemanticControl` describes visible-ish controls by role/name/label/text, optional selector hint, optional bounding hint, enabled/visible/checked/expanded/required states, value summary, risk hint, and confidence. Sensitive values must be suppressed or summarized.

Mock observations use `provider = "playwright_mock"` and `browser_context_kind = "mock"`. They may include fixture data such as the Example Checkout page with a Continue button, Email field, I agree checkbox, Privacy Policy link, and Session expired alert. This is only mock/dev evidence and must not be described as a real browser page.

Live isolated observations use `provider = "playwright_live_semantic"` and `browser_context_kind = "isolated_playwright_context"`. They extract bounded control, form, dialog/alert, and text-region summaries from a Playwright-controlled temporary context. Password fields and other sensitive inputs are represented by type/risk/value summaries only; values are not copied into observations, events, status, or Deck payloads. If iframes, cross-origin frames, shadow DOM, very large control lists, or incomplete page loading are detected, the observation carries explicit limitations such as `iframe_context_limited`, `cross_origin_iframe_not_observed`, `shadow_dom_context_limited`, `large_control_list_truncated`, and `partial_semantic_observation`.

## Grounding Model

`BrowserGroundingCandidate` links an operator phrase to a semantic control. It includes match reason, confidence, evidence terms, mismatch terms, source observation id, source provider, claim ceiling, ambiguity reason, and explicit scaffold flags:

- `action_supported = false`
- `verification_supported = false`

Ambiguity stays explicit. Two matching controls should produce a candidate list and an ambiguity reason, not an action.

Matching supports exact accessible name, role/name, label, visible text, safe placeholder/value summaries, state terms, ordinal hints, dialog/alert context, simple nearby ordering context, and simple fuzzy contains matching for both mock and live isolated observations. Addition 3.1 adds deterministic synonym and negation handling for common page vocabulary without using LLM reasoning for target selection. Hidden controls are not treated as visible grounding targets. A stale observation reduces confidence and adds `stale_observation` / `observation_may_be_stale` metadata. Grounding returns candidates only. It never clicks or types.

Examples:

- "the Continue button" -> role/name match for the Continue button.
- "the email field" or "the field labeled Email" -> label/name match for the Email field.
- "the disabled submit button" -> button named Submit with disabled state evidence.
- "the required field" -> required visible fields, ranked by semantic order.
- "the second link" -> ordinal match among visible links.
- "the thing that says Session expired" -> dialog/alert/text match from the semantic snapshot.

## Guidance Model

Guidance may say a semantic target was found, that multiple controls match, that the closest available candidate is weak, or that the target was not found in the latest isolated semantic snapshot. It must not claim action execution.

Allowed Ghost-style labels:

- "I found the button."
- "I found three matching buttons: Continue, Cancel, and Submit. Which one do you mean?"
- "I did not find a Submit button. The closest match is Continue."
- "The page has a visible Search field."
- "That target is ambiguous."
- "I can guide you to it."
- "Action would require confirmation."

Forbidden labels:

- "Clicked."
- "Submitted."
- "Verified."
- "I saw your screen."
- "Logged in."
- "I can bypass this."

## Action Model

Addition 4.1 defines action planning so Stormhelm can show the likely target, action kind, risk level, approval requirement, capability required, and expected before/after semantic comparison. Preview capability remains non-execution: `browser.action.preview` and `browser.action.plan_preview`.

Preview models:

- `BrowserSemanticActionPreview` has claim ceiling `browser_semantic_action_preview`, risk level, required trust scope, expected outcome templates, and limitations. `action_supported_now` may be true only for click/focus when the runtime gates are active; `executable_now` remains false until a trust grant is present.
- `BrowserSemanticActionPlan` stores a bounded target candidate summary, redacted action arguments, preconditions, capability required, `adapter_capability_declared`, `result_state = preview_only | unsupported | ambiguous | blocked`, and a verification request template.

Supported preview classifications include `click`, `focus`, `type_text`, `select_option`, `check`, `uncheck`, `scroll_to`, `submit_form`, and `unsupported`. Sensitive text is redacted. Login, password, payment, CAPTCHA, cookie, and user-profile contexts are blocked/deferred.

Addition 5 execution models:

- `BrowserSemanticActionExecutionRequest` binds plan id, preview id, observation id, target candidate id, action kind, optional trust/grant ids, session/task id, expected outcome, source provider, and created time.
- `BrowserSemanticActionExecutionResult` records exact status, whether a Playwright action command was attempted and completed, before/after observation ids, semantic comparison result id, verification status, trust scope, cleanup status, provider, risk, limitations, bounded errors, and claim ceiling `browser_semantic_action_execution`.

Supported execution kinds in Addition 5:

- `click`
- `focus`

Execution requires all of these:

- the adapter contract declares the capability
- the trust gate approves it
- Screen Awareness grounds the target
- a preview is shown
- result state distinguishes attempted, completed, and verified
- verification is bounded and truthful

Execution uses a new isolated temporary Playwright browser context, does not attach to the user's browser, captures a semantic before snapshot, performs the approved click/focus command through a bounded locator, captures an after snapshot, compares the snapshots, clears temporary cookies/storage, and closes the context/browser before the Playwright manager exits. Addition 5.1 blocks execution before launch for stale plans, tampered plan targets, denied approvals, expired or consumed grants, and action/target mismatches. After launch it blocks target drift, hidden/disabled/sensitive targets, role/selector disagreement, zero-match locators, and multi-match locators unless a later phase adds an explicit safe ordinal binding. Playwright command return is never treated as verification by itself.

Unsupported execution kinds return typed `unsupported` or `blocked` results. Typing, scrolling, form fill/submit, login, cookies, user profiles, downloads, payments, CAPTCHA/anti-bot handling, arbitrary JavaScript click, visible-screen verification, truth verification, and workflow replay remain unavailable.

## Verification Model

Addition 4 implements verification-only semantic comparison for Playwright browser observations. The typed request is `BrowserSemanticVerificationRequest`, and the typed result is `BrowserSemanticVerificationResult` with claim ceiling `browser_semantic_observation_comparison`.

The comparison engine can answer bounded questions such as:

- "did the warning disappear?"
- "did the Continue button become enabled?"
- "did the page URL/title change?"
- "did a dialog appear?"
- "did the Email field become required?"
- "did the checkbox become checked?"
- "did a link appear?"

Strict statuses:

- `supported`: semantic snapshot evidence supports the expected change.
- `unsupported`: semantic snapshot evidence suggests the expected change did not occur.
- `partial`: related evidence exists, but stale/partial/limited observations prevent a strong claim.
- `ambiguous`: multiple plausible semantic targets or interpretations remain.
- `unverifiable`: the observations do not contain enough evidence.
- `stale_basis`: one or both observations are too old to rely on.
- `insufficient_basis`: before or after observation is missing.
- `failed`: comparison failed internally.

Allowed wording includes "The semantic snapshots support that the warning disappeared" and "The Continue button appears to have become enabled." It must not say an action succeeded, that the user-visible browser was observed, or that the website's claims are true.

## Trust And Approval Posture

Observation is disabled by default and does not require approval. Action previews do not create trust grants. Addition 5 click/focus execution always requires the existing trust service to approve a bound request. The approval request is scoped to the action kind, target summary, target fingerprint, plan/session/task binding, risk level, expected outcome, provider, and claim ceiling. A preview is not approval, stale or ambiguous targets are blocked, denied approvals remain blocked for the same action key, expired grants require fresh approval, and once grants are consumed through the trust audit path. Focus is low risk when the target is non-sensitive. Click is medium risk for ordinary fixture/test buttons or links. Password, login, payment, CAPTCHA, cookie, profile, hidden, disabled, or sensitive contexts are blocked/deferred.

## Ghost And Deck Behavior

Ghost remains compact and uses observation/guidance wording only. It may say "I found the Email field.", "Two matching controls found.", "The target is ambiguous.", "This is a mock browser observation.", or "This came from an isolated browser observation." It must not display raw DOM, full snapshots, credentials, hidden values, or action claims.

For semantic comparison, Ghost may say "The warning appears to have disappeared.", "I cannot verify that from these snapshots.", or "The comparison is ambiguous." It must not say "Done", "Clicked", "Typed", "Submitted", or "I saw your browser."

For action previews, Ghost may say "Action preview ready.", "Execution is not enabled yet.", or "Target is ambiguous." It must not show an execute action or claim that anything was performed.

For Addition 5/5.1 click/focus execution, Ghost remains compact. It may say "Approval required.", "Click blocked: target changed.", "Click blocked: target is ambiguous.", "Click verified by semantic comparison.", "The click was attempted, but I could not verify the expected change.", or "Focus attempted; focus state could not be verified." It must not say "Done" alone, "I saw your screen", "I used your browser", "Typed", "Submitted", or "Logged in."

Command Deck may show:

- adapter readiness
- page URL/title
- semantic snapshot summary
- controls by role
- grounding candidates
- candidate ranking confidence and evidence terms
- candidate mismatch terms and partial-observation limitations
- ambiguity reasons
- bounded form/page summaries
- claim ceiling
- limitations
- mock observation summary
- live isolated observation summary
- last grounding summary
- latest semantic comparison status and bounded change evidence
- latest action preview/plan summary with target candidate, action kind, risk, future approval requirement, capability required, `executable_now = false`, expected semantic comparison, limitations, and claim ceiling
- latest click/focus execution summary with action kind, trust/approval state, before/after observation ids, verification status, cleanup status, comparison summary, limitations, and claim ceiling

Deck must not expose cookies, credentials, hidden form values, sensitive field contents, raw full DOM by default, huge snapshots, or active controls for unsupported action kinds.

## Safety And Privacy Rules

- disabled by default
- no Playwright dependency required in normal CI
- mock provider requires the dev adapter gate
- live semantic checks require `STORMHELM_LIVE_BROWSER_TESTS=true`
- no browser launch by default
- live smoke browser launch requires `STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH=true`
- no connecting to real user browser sessions by default
- no persistent user profile; live smoke uses an isolated temporary context
- no login, cookies, session reuse, or credential collection
- no payment or checkout automation
- no CAPTCHA or anti-bot bypass
- no hidden browser sessions
- no persistent raw DOM memory by default
- click/focus execution disabled by default and available only with explicit action gates plus exact trust approval
- stale plans, target drift, locator ambiguity, denied approval, consumed grants, and unusable after-observation evidence fail closed or return bounded `completed_unverified`
- no typing, scrolling, form fill/submit, login, cookies/session reuse, user-profile attachment, payment, CAPTCHA/anti-bot handling, arbitrary public-site clicking, or unrestricted browser automation
- no visible-screen or truth-verification claims

## Phased Roadmap

1. Playwright Addition 1: runtime readiness and mock semantic observation.
2. Playwright Addition 2.2: opt-in live integration diagnostics for readiness and isolated semantic observation smoke.
3. Playwright Addition 2: real isolated semantic snapshot extraction behind explicit dev/runtime gates.
4. Playwright Addition 3: semantic target grounding, ranking, form/dialog summaries, and guided navigation text.
5. Playwright Addition 4: verification-only before/after semantic comparison.
6. Playwright Addition 4.1: action preview and trust-gated action plan scaffold.
7. Playwright Addition 5: trust-gated click/focus execution with semantic before/after comparison.
8. Playwright Addition 5.1: click/focus hardening for stale plans, target drift, trust binding, locator ambiguity, cleanup, and verification ambiguity.
9. Playwright Addition 5.2: canonical Screen Awareness path unification.
10. Playwright Addition 5.3: adversarial canonical-path regression tests for routing, provenance, trust, action-result mapping, UI state, and duplicate-path audits.
11. Playwright Addition 6: trust-gated typing/form assistance.
12. Playwright Addition 7: workflow replay with task and trust binding.

## Explicit Non-Goals

- live Playwright browser automation in normal/default runtime paths
- browser launch outside explicit Playwright dev/runtime gates
- connecting to real user browser sessions
- user-profile attachment or persistent browser context
- typing
- scrolling
- form filling
- form submission
- login
- cookies/session reuse
- credential handling
- payment/checkout
- CAPTCHA/anti-bot bypass
- visible-screen verification
- truth verification
- workflow replay
- arbitrary public-site clicking
- replacing Obscura
- replacing browser destination/open behavior
- replacing Screen Awareness

## Test Strategy

Normal CI uses config, contract, model, fake readiness, mock observation, mock grounding, guidance, status, Deck model, fake-backed live semantic extraction, and event tests only. No live Playwright dependency is required. Addition 2.2 adds `tests/test_live_browser_provider_smoke.py`, which is marked `live_browser` and skipped unless the explicit environment gate is set. Playwright Addition 2 adds `tests/test_screen_awareness_playwright_live_semantic.py` for isolated-context policy, semantic normalization, sensitive-value redaction, grounding/guidance, events, status, and Deck payloads without requiring the real Playwright package in normal CI. Playwright Addition 3 adds `tests/test_screen_awareness_playwright_grounding_guidance.py` for richer target grounding, ranking, ambiguity, closest-match behavior, stale observation downgrades, form/dialog summaries, and Deck candidate evidence. Playwright Addition 3.1 adds `tests/test_screen_awareness_playwright_grounding_robustness.py` for messy labels/states, embedded-context limitations, dynamic stabilization, synonyms/negation, form-like summaries, live-event evidence bounding, and Deck limitation payloads.
Playwright Addition 4 adds `tests/test_screen_awareness_playwright_semantic_verification.py` for typed comparison models, URL/title/control/dialog/link/form/limitation change detection, expected-outcome statuses, stale/partial/ambiguous basis handling, bounded events, status propagation, Deck payloads, sensitive redaction, and action-disabled preservation.
Playwright Addition 4.1 adds `tests/test_screen_awareness_playwright_action_preview.py` for typed action previews/plans, action-kind classification, redaction, risk/trust posture, expected outcome templates, bounded events, Deck payloads, preview-only adapter contract declarations, and proof that execution capabilities remain absent.
Playwright Addition 5 adds `tests/test_screen_awareness_playwright_click_focus_execution.py` for typed execution models, config gates, approval-required behavior, approved fixture click/focus execution through the Screen Awareness service path, isolated context cleanup, semantic before/after verification, bounded events, Deck payloads, and proof that type/scroll/form/login/cookie/profile actions remain unsupported. Playwright Addition 5.1 extends that same file with stale-plan blocking, target-fingerprint binding, denied/expired/consumed approval handling, cross-action grant isolation, locator ambiguity and role/selector disagreement blockers, after-observation failure classification, cleanup status, and event sequence checks. Playwright Addition 5.3 adds `tests/test_screen_awareness_playwright_canonical_kraken.py` to keep Playwright inside canonical Screen Awareness: Playwright observations must resolve through `BrowserSemanticAdapter`, browser controls must become canonical adapter-semantic targets, generic grounding must consume those targets, planner/UI code must not call Playwright execution directly, route boundaries must keep web retrieval/browser-open/Discord relay separate, canonical action status must lead Deck/Ghost summaries, and Playwright must use injected `TrustService` plus provider-local cleanup rather than a parallel trust authority.

Focused scaffold tests:

- config defaults disabled
- readiness disabled and dependency not imported
- dev gate required
- missing dependency handled without exception
- mock readiness without Playwright dependency
- mock observation creation and serialization
- exact, role/name, label, text, ambiguity, and no-match grounding
- guidance for found and ambiguous targets
- no-match grounding and guidance
- config -> container -> service -> status reachability
- service-owned event emission and Command Deck payload propagation
- bounded status/snapshot summaries
- bounded event payloads
- Command Deck model surfaces readiness/mock summaries without browser action controls
- fake-backed live semantic snapshot tests for isolated context policy, bounded extraction, sensitive-value redaction, grounding/guidance, live events, status, and Deck summaries
- semantic grounding tests for disabled/required/checked state, ordinal hints, dialog/alert text, nearby context, closest-match behavior, stale observation confidence, form summaries, and redaction
- robustness tests for aria/placeholder/nearby label normalization, readonly state, not-disabled/not-required grounding, last ordinal grounding, iframe/shadow limitations, large-page truncation, form-like grouping, unchecked required controls, and bounded event/Deck payloads
- semantic comparison tests for supported, unsupported, partial, ambiguous, stale, insufficient-basis, and redacted before/after outcomes
- action preview tests for non-executable click/type/select/check/submit planning, blocked sensitive contexts, ambiguous targets, unsupported requests, redaction, and bounded Deck/events
- click/focus execution tests for approval gates, isolated context policy, stale plans, target drift, trust-binding exactness, locator ambiguity, disabled/sensitive target blockers, after-observation capture/failure handling, semantic comparison, trust audit use, cleanup status, bounded events, and Deck status
- canonical-path regression tests for Playwright-to-`BrowserSemanticAdapter` resolution, canonical target provenance, generic grounding, planner/UI no-direct-execution audits, Screen Awareness route ownership for browser-control requests, web retrieval/browser destination/Discord route preservation, provider-to-canonical action-result mapping, and injected trust/cleanup proof
- static contract keeps observation/preview/comparison posture while runtime status declares click/focus only when gates are enabled
- click/focus action execution capabilities are declared only by runtime-gated status, disabled by default, and absent for type/scroll/form/login/cookie/profile/payment/CAPTCHA/screen/truth capabilities
- claim ceiling is `browser_semantic_observation`
- Screen Awareness status lists the disabled adapter
- planner does not route click/type/form/login requests to Playwright
