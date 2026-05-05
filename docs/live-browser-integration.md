# Live Browser Integration Checks

Stormhelm live browser provider checks are explicit local diagnostics for Obscura CLI, Obscura CDP, and Playwright semantic observation. They are disabled by default, skipped in normal CI, and do not change the default production posture.

These checks prove live provider paths can run when a developer intentionally enables them. The live browser diagnostic profile does not enable click/focus/type/choice/scroll action gates; action execution remains a separate Screen Awareness path requiring explicit config and trust approval.

## Scope

Implemented in this pass:

- `config/development-live-browser.toml.example` as an opt-in local profile.
- `scripts/setup_live_browser_dependencies.ps1` as a check-only optional dependency helper.
- `scripts/run_live_browser_checks.ps1` as a bounded runner.
- `python -m stormhelm.core.live_browser_integration` as the structured report backend.
- pytest markers for opt-in live slices: `live_browser`, `live_obscura`, `live_obscura_cdp`, and `live_playwright`.
- A loopback fixture server for deterministic Playwright semantic observation smokes.

Still out of scope:

- enabling live providers by default
- requiring Obscura or Playwright in normal CI
- typing/action execution in the live diagnostic profile, scrolling, form filling, form submission, login, cookies/session reuse, downloads, payment flows, CAPTCHA/anti-bot bypass, user-profile reuse, visible-screen verification, truth verification, workflow replay, and arbitrary public-site clicking/typing

## Environment Gates

The master gate is required:

```powershell
$env:STORMHELM_LIVE_BROWSER_TESTS = "true"
```

Provider gates:

```powershell
$env:STORMHELM_ENABLE_LIVE_OBSCURA = "true"
$env:STORMHELM_ENABLE_LIVE_OBSCURA_CDP = "true"
$env:STORMHELM_ENABLE_LIVE_PLAYWRIGHT = "true"
$env:STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH = "true"
$env:STORMHELM_OBSCURA_BINARY = "obscura"
$env:STORMHELM_LIVE_BROWSER_TEST_URL = "https://example.com"
```

Without `STORMHELM_LIVE_BROWSER_TESTS=true`, live tests skip. Missing dependencies report `binary_missing`, `dependency_missing`, or `browsers_missing` in the live report instead of failing normal CI.

## Optional Dependency Setup

The live browser dependencies are optional. Stormhelm does not install Obscura or Playwright during normal setup, and normal CI should not require them.

Run the check-only helper first:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_live_browser_dependencies.ps1 -CheckOnly -ReportPath reports\live_browser_integration\addition-2.5-checkonly-dependencies.json
```

Obscura setup:

- Official release discovery uses `https://api.github.com/repos/h4ckf0r0day/obscura/releases/latest` and selects a Windows zip asset from the official `h4ckf0r0day/obscura` GitHub Releases page.
- Install or build Obscura using the Obscura project's own release/source instructions when you do not want helper-assisted release discovery.
- Put `obscura.exe` on `PATH`, or keep it in a local tools folder and pass `-ObscuraBinary` to the live runner.
- The dependency helper never downloads or installs Obscura automatically. It installs only when `-InstallObscura` is present.
- To discover and download the latest official Windows release explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_live_browser_dependencies.ps1 -InstallObscura -DownloadLatestObscuraRelease -ObscuraInstallDir "$env:LOCALAPPDATA\Stormhelm\tools\obscura" -SetStormhelmObscuraBinary -ReportPath reports\live_browser_integration\addition-2.6-setup-obscura.json
```

- If the release contains multiple matching Windows zip assets, pass `-ObscuraAssetName "<asset.zip>"` to choose one explicitly.
- To install a specific release tag, pass `-ObscuraReleaseTag "<tag>"` with `-DownloadLatestObscuraRelease`.
- Prefer a local zip when you have one:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_live_browser_dependencies.ps1 -InstallObscura -ObscuraZipPath "C:\path\to\obscura-windows.zip" -ObscuraInstallDir "$env:LOCALAPPDATA\Stormhelm\tools\obscura" -ReportPath reports\live_browser_integration\addition-2.5-setup-obscura.json
```

- Use a release URL only when you have an explicit trusted zip URL:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_live_browser_dependencies.ps1 -InstallObscura -ObscuraReleaseUrl "https://github.com/h4ckf0r0day/obscura/releases/download/<tag>/<asset>.zip" -ObscuraInstallDir "$env:LOCALAPPDATA\Stormhelm\tools\obscura" -ReportPath reports\live_browser_integration\addition-2.6-setup-obscura.json
```

- Explicit release URLs must be HTTPS GitHub release asset URLs from `h4ckf0r0day/obscura`.
- Avoid PATH mutation by passing the installed binary explicitly to live checks:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_live_browser_checks.ps1 -Enable -Obscura -ObscuraBinary "$env:LOCALAPPDATA\Stormhelm\tools\obscura\obscura.exe" -Url "https://example.com"
```

- `-SetStormhelmObscuraBinary` sets `STORMHELM_OBSCURA_BINARY` for the user environment only when explicitly requested.
- `-AddObscuraToUserPath` mutates the user `PATH` only when explicitly requested.
- Verify the binary path directly before running Stormhelm checks:

```powershell
$env:STORMHELM_OBSCURA_BINARY = "C:\path\to\obscura.exe"
& $env:STORMHELM_OBSCURA_BINARY --version
```

If you are validating CDP manually, start only a localhost server and stop it afterward:

```powershell
& $env:STORMHELM_OBSCURA_BINARY serve --port 9222
```

The official Windows release observed during Addition 2.6 accepted `serve --port <port>` and listened on `127.0.0.1`; it did not accept a `--host` flag.

Playwright setup for local diagnostics:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_live_browser_dependencies.ps1 -InstallPlaywrightPackage -InstallPlaywrightChromium -ReportPath reports\live_browser_integration\addition-2.4-setup-playwright.json
```

Those flags explicitly run the local Python equivalent of:

```powershell
python -m pip install playwright
python -m playwright install chromium
```

The helper does not attach to a user browser profile, does not enable actions, and does not change Stormhelm defaults.

## Running The Checks

Run all selected checks:

```powershell
.\scripts\run_live_browser_checks.ps1 -Enable -Obscura -ObscuraCdp -Playwright -Url "https://example.com"
```

If your PowerShell execution policy blocks local scripts, use the explicit bypass form for this one process:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_live_browser_checks.ps1 -Enable -Obscura -ObscuraCdp -Playwright -Url "https://example.com"
```

Allow the Playwright live semantic smoke to launch an isolated temporary browser context:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_live_browser_checks.ps1 -Enable -Playwright -AllowPlaywrightBrowserLaunch
```

Readiness-only and per-provider report examples:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_live_browser_checks.ps1 -Enable -Obscura -Url "https://example.com" -Output reports\live_browser_integration\addition-2.5-live-obscura-cli.json
powershell -ExecutionPolicy Bypass -File .\scripts\run_live_browser_checks.ps1 -Enable -ObscuraCdp -Url "https://example.com" -Output reports\live_browser_integration\addition-2.5-live-obscura-cdp.json
powershell -ExecutionPolicy Bypass -File .\scripts\run_live_browser_checks.ps1 -Enable -Playwright -Output reports\live_browser_integration\addition-2.4-live-playwright-readiness.json
powershell -ExecutionPolicy Bypass -File .\scripts\run_live_browser_checks.ps1 -Enable -Playwright -AllowPlaywrightBrowserLaunch -Output reports\live_browser_integration\addition-2.4-live-playwright-smoke.json
```

Run the Python backend directly:

```powershell
$env:STORMHELM_LIVE_BROWSER_TESTS = "true"
$env:STORMHELM_ENABLE_LIVE_PLAYWRIGHT = "true"
$env:STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH = "true"
$env:PYTHONPATH = "C:\Stormhelm\src"
python -m stormhelm.core.live_browser_integration --output reports\live_browser_integration\manual.json
```

Use `-Strict` or `--strict` when you want enabled missing/incompatible providers to exit nonzero.

Reports are written to `reports/live_browser_integration/` by the PowerShell script unless `-Output` is supplied.

## Report Statuses

The JSON report uses these statuses:

- `passed`: the enabled live check produced bounded evidence.
- `skipped`: the gate or required public test URL was not provided.
- `unavailable`: dependency or binary is missing.
- `partial`: optional capability is missing, extraction was partial, or one enabled provider is diagnostic-only while another enabled provider passed.
- `incompatible`: the live endpoint shape is not compatible enough to proceed.
- `failed`: a live check ran and failed.

Report sections include Obscura CLI, Obscura CDP, Playwright readiness, Playwright semantic observation, cleanup status, claim ceilings, safety gates, action-capability posture, and limitations. Reports redact raw output and omit full DOM, full HTML, cookies, credentials, and huge page text.

## Provider Behavior

Obscura CLI live smoke:

- detects the configured binary
- validates a public URL
- runs the existing Obscura CLI web retrieval provider
- reports rendered page evidence only
- keeps the claim ceiling at `rendered_page_evidence`

Obscura CDP live smoke:

- starts/probes through the existing compatibility probe
- binds to `127.0.0.1`
- classifies `/json/version`, `/json/list`, `/json`, websocket discovery, and cleanup
- treats endpoint discovery as diagnostics until navigation/page inspection support is proven
- optionally inspects a public URL only when compatible enough for navigation
- keeps the claim ceiling at `headless_cdp_page_evidence`
- reports `diagnostic_only` / `cdp_navigation_unsupported` when endpoints exist but page navigation is not supported, and recommends the Obscura CLI extraction path instead

Playwright readiness and semantic smoke:

- detects the optional Python package
- checks browser engine availability without requiring CI installation
- launches only when `STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH=true`
- uses an isolated temporary browser context, not the user's profile
- calls the Screen Awareness Playwright adapter's real semantic snapshot path
- extracts bounded URL/title/control/link/form/dialog summaries and runs semantic grounding/guidance
- ranks grounding candidates with bounded evidence/mismatch terms, preserves ambiguity, reports closest-match guidance, handles common synonyms/negation, and surfaces partial-observation limitations without executing actions
- can compare two already-captured isolated semantic observations for verification-only evidence without using Playwright to create the state transition
- keeps Addition 5 click/focus execution gates off in the live diagnostic profile unless a separate test/dev config explicitly enables them
- clears temporary cookies/storage and closes the context/browser after observation
- keeps the claim ceiling at `browser_semantic_observation`

## Dependency Setup Notes

Obscura:

- Put the `obscura` binary on `PATH`, or pass `-ObscuraBinary "C:\path\to\obscura.exe"` to the script.
- The helper supports `-ObscuraBinaryPath "C:\path\to\obscura.exe"` for check-only reporting.
- Setup reports include `obscura_release_repo`, `obscura_release_tag`, `obscura_release_name`, `obscura_asset_name`, `obscura_asset_url_redacted_or_bounded`, `download_attempted`, `download_status`, `download_path`, `extraction_status`, `binary_candidates_found`, `obscura_binary_path`, `binary_found`, `install_mode`, `install_dir`, `added_to_path`, `stormhelm_obscura_binary_set`, `version_status`, `version_output_bounded`, `checksum_status`, `install_status`, `error_code`, and `bounded_error_message`.
- Missing Obscura is reported as `status = "unavailable"` with `error_code = "binary_missing"` and `details.binary_found = false`.
- CDP incompatibility is not hidden. If the binary starts but does not expose compatible localhost CDP endpoints or rejects the navigation path needed for page inspection, the report should say `partial`, `incompatible`, or `failed` with endpoint details. Endpoint discovery alone is not reported as page-inspection support.

Playwright:

- The Python package is optional. Install it only for local live diagnostics, for example with `python -m pip install playwright`.
- Browser engines are optional. For Chromium semantic smoke diagnostics, install the engine with `python -m playwright install chromium`.
- Missing package is reported as `status = "unavailable"`, `error_code = "dependency_missing"`, and `details.dependency_installed = false`.
- Missing browser engine is reported as `browsers_missing`; this remains a local diagnostic failure, not a normal CI failure.

## Observed Local Validation

On the April 30, 2026 local Addition 2.3 baseline run:

- non-live baseline returned `overall_status = "skipped"` with action capabilities disabled
- direct `.\scripts\run_live_browser_checks.ps1` was blocked by local PowerShell execution policy, so the documented bypass form was used
- Obscura was not found on `PATH`, and both Obscura CLI/CDP checks reported `binary_missing`
- the Python `playwright` package was not installed, so readiness and semantic smoke reported `dependency_missing`
- no Obscura, Playwright, Chromium, or Chrome child process remained after the checks

These are truthful unavailable states, not live provider success.

On the April 30, 2026 local Addition 2.4 validation run:

- `scripts/setup_live_browser_dependencies.ps1 -CheckOnly` wrote `reports/live_browser_integration/addition-2.4-checkonly-dependencies.json`.
- The helper was then run with explicit `-InstallPlaywrightPackage -InstallPlaywrightChromium` flags and wrote `reports/live_browser_integration/addition-2.4-setup-playwright.json`.
- Playwright readiness passed with `dependency_installed = true`, `browser_engines_available = true`, `browser_launch_allowed = false`, and action capabilities disabled.
- Playwright semantic smoke passed with an isolated temporary browser context, fixture page title `Stormhelm Fixture Form`, four controls, guidance `I found the Continue button.`, cleanup status `closed`, and claim ceiling `browser_semantic_observation`.
- Obscura remained unavailable on this machine, so Obscura CLI and CDP reports still showed `binary_missing`.
- A combined all-gates report showed Playwright passing while Obscura CLI/CDP stayed unavailable; that mixed state is expected until an Obscura binary is installed/configured.
- No Obscura, Playwright, Chromium, or Chrome child process remained after the checks.

Report files from this run:

- `reports/live_browser_integration/addition-2.4-checkonly-dependencies.json`
- `reports/live_browser_integration/addition-2.4-setup-playwright.json`
- `reports/live_browser_integration/addition-2.4-non-live-baseline.json`
- `reports/live_browser_integration/addition-2.4-live-obscura-cli.json`
- `reports/live_browser_integration/addition-2.4-live-obscura-cdp.json`
- `reports/live_browser_integration/addition-2.4-live-playwright-readiness.json`
- `reports/live_browser_integration/addition-2.4-live-playwright-smoke.json`
- `reports/live_browser_integration/addition-2.4-live-all-gates.json`

On the April 30, 2026 local Addition 2.5 validation run:

- `scripts/setup_live_browser_dependencies.ps1 -CheckOnly` wrote `reports/live_browser_integration/addition-2.5-checkonly-dependencies.json`.
- No `obscura` command was found on `PATH`, and no Obscura zip/binary was found in the checked local Downloads or Stormhelm tools folders.
- An explicit setup attempt without a zip or URL wrote `reports/live_browser_integration/addition-2.5-setup-obscura.json` with `install_status = "failed"` and `error_code = "install_source_missing"`.
- Obscura CLI and CDP live reports remained `unavailable` with `error_code = "binary_missing"`.
- Playwright remained installed from Addition 2.4; this pass did not change Playwright defaults or action posture.

Manual next step for Obscura success is to provide either a local Obscura Windows zip through `-ObscuraZipPath`, an explicit trusted release zip URL through `-ObscuraReleaseUrl`, or an existing binary through `-ObscuraBinaryPath` / `-ObscuraBinary`.

Report files from this run:

- `reports/live_browser_integration/addition-2.5-checkonly-dependencies.json`
- `reports/live_browser_integration/addition-2.5-setup-obscura.json`
- `reports/live_browser_integration/addition-2.5-live-obscura-cli.json`
- `reports/live_browser_integration/addition-2.5-live-obscura-cdp.json`

On the April 30, 2026 local Addition 2.6 validation run:

- Official release discovery selected `h4ckf0r0day/obscura` release `v0.1.1`, asset `obscura-x86_64-windows.zip`.
- The helper downloaded and extracted the asset to `C:\Users\kkids\AppData\Local\Stormhelm\tools\obscura`.
- The resolved binary was `C:\Users\kkids\AppData\Local\Stormhelm\tools\obscura\obscura.exe`.
- `obscura --version` is not supported by this release; the setup report marks this as `version_unknown` with `binary_executable = true`, not as installation failure.
- Obscura CLI live smoke passed against `https://example.com` with `rendered_page_evidence`, bounded text/link counts, and action capabilities disabled.
- Obscura CDP startup/discovery improved after matching the release's `serve --port` syntax. `/json/version`, `/json/list`, browser websocket, and page websocket were discovered and cleanup was graceful.
- Obscura CDP navigation remained incompatible: `Page.navigate` returned `No page for session`, reported as `cdp_navigation_unsupported`. Stormhelm does not fake CDP extraction success in this state.
- Combined all-gates reported Obscura CLI passed, Obscura CDP incompatible, and Playwright readiness/semantic smoke passed. Claim ceilings remained `rendered_page_evidence`, `headless_cdp_page_evidence`, and `browser_semantic_observation`.
- No Obscura, Playwright, Chromium, or Chrome child process remained after the checks.

Report files from this run:

- `reports/live_browser_integration/addition-2.6-checkonly-dependencies.json`
- `reports/live_browser_integration/addition-2.6-setup-obscura.json`
- `reports/live_browser_integration/addition-2.6-live-obscura-cli.json`
- `reports/live_browser_integration/addition-2.6-live-obscura-cdp.json`
- `reports/live_browser_integration/addition-2.6-live-all-gates.json`

On the April 30, 2026 local Addition 2.7 calibration run:

- Obscura CLI live smoke still passed against `https://example.com`; this remains the recommended Obscura extraction path for this tested release.
- Obscura CDP still discovered `/json/version`, `/json/list`, browser websocket, and page websocket endpoints, but navigation/page inspection remained unsupported with `error_code = "cdp_navigation_unsupported"`.
- Stormhelm now reports that CDP shape as `compatibility_level = "diagnostic_only"`, `details.compatible = false`, `navigation_supported = false`, `page_inspection_supported = false`, and `recommended_fallback_provider = "obscura_cli"`.
- Combined all-gates now reports `overall_status = "partial"` instead of collapsing the run into a vague failure when Obscura CLI and Playwright pass while CDP is diagnostic-only.
- Playwright readiness and semantic smoke still passed with action capabilities disabled and claim ceiling `browser_semantic_observation`.

Report files from this run:

- `reports/live_browser_integration/addition-2.7-live-obscura-cli.json`
- `reports/live_browser_integration/addition-2.7-live-obscura-cdp.json`
- `reports/live_browser_integration/addition-2.7-live-playwright-smoke.json`
- `reports/live_browser_integration/addition-2.7-live-all-gates.json`

On the April 30, 2026 local Playwright Addition 2 validation run:

- Playwright readiness passed with `dependency_installed = true`, `browser_engines_available = true`, and `browser_launch_allowed = true`.
- The semantic observation smoke passed through `semantic_extraction_path = "screen_awareness.playwright_adapter"`, proving the live runner uses the Screen Awareness Playwright adapter instead of an inline placeholder.
- The adapter launched an isolated temporary browser context, did not use a user profile, extracted fixture title `Stormhelm Fixture Form`, four controls, one link, bounded form/dialog counts, and guidance `I found the Continue button.`.
- Cleanup status was `closed`, `action_capabilities_disabled = true`, and the claim ceiling remained `browser_semantic_observation`.

Report file from this run:

- `reports/live_browser_integration/addition-playwright-2-live-semantic-snapshot.json`

On the April 30, 2026 local Playwright Addition 3 validation run:

- Playwright readiness still passed with `dependency_installed = true`, `browser_engines_available = true`, and `browser_launch_allowed = true`.
- The semantic observation smoke still passed through `semantic_extraction_path = "screen_awareness.playwright_adapter"`.
- The adapter used an isolated temporary browser context, did not use a user profile, extracted fixture title `Stormhelm Fixture Form`, four controls, one link, and produced guidance `I found the Continue button.`.
- Cleanup status was `closed`, `action_capabilities_disabled = true`, and the claim ceiling remained `browser_semantic_observation`.

Report file from this run:

- `reports/live_browser_integration/addition-playwright-3-live-guidance.json`

On the April 30, 2026 local Playwright Addition 3.1 validation run:

- Playwright readiness still passed with `dependency_installed = true`, `browser_engines_available = true`, and `browser_launch_allowed = true`.
- The semantic observation smoke passed through `semantic_extraction_path = "screen_awareness.playwright_adapter"`.
- The adapter used an isolated temporary browser context, did not use a user profile, extracted fixture title `Stormhelm Fixture Form`, four controls, one link, and produced bounded grounding/guidance.
- Cleanup status was `closed`, `action_capabilities_disabled = true`, and the claim ceiling remained `browser_semantic_observation`.

Report file from this run:

- `reports/live_browser_integration/addition-playwright-3.1-live-robustness.json`

On the April 30, 2026 local Playwright Addition 4 validation run:

- Two fixture URLs were loaded in isolated temporary Playwright contexts: a dialog/warning fixture and a form fixture.
- No click/type/scroll/form action was used to create the before/after state; the state transition came from loading separate fixture pages.
- Semantic comparison returned `comparison_status = "supported"` for `expected_change_kind = "warning_removed"` with user message `The semantic snapshots support that the warning disappeared.`
- Cleanup status was `closed`, `action_capabilities_disabled = true`, and the comparison claim ceiling was `browser_semantic_observation_comparison`.

Report file from this run:

- `reports/live_browser_integration/addition-playwright-4-live-verification-only.json`

On the April 30, 2026 local Playwright Addition 5 validation run:

- A local fixture page was served on `127.0.0.1` and loaded through isolated temporary Playwright contexts.
- Click/focus action gates were enabled only inside the explicit smoke harness, not in the live browser diagnostic profile.
- The click target was the fixture `Continue` button. Trust approval used a once grant, the Playwright click command was issued, the warning disappeared, and semantic before/after comparison returned `verified_supported`.
- The focus target was the fixture `Email` field. Trust approval used a once grant, the Playwright focus command was issued, no typing occurred, and the result was `completed_unverified` because the semantic snapshots did not provide enough focus-state evidence.
- Cleanup status was `closed`, `user_profile_used = false`, and forbidden capabilities for typing, scrolling, form submit, login, cookies, and user profiles stayed false in the live diagnostic profile.

Report file from this run:

- `reports/live_browser_integration/addition-playwright-5-live-click-focus.json`

On the April 30, 2026 Playwright Addition 5.1 hardening pass:

- The click/focus execution path was hardened in fake-backed normal-CI tests for stale plans, target-fingerprint drift, denied approvals, expired grants, consumed once grants, cross-action approval mismatch, locator ambiguity, role/selector disagreement, after-observation failure classification, cleanup status, and bounded event sequence.
- No new live public-site action path was added. Live action smoke remains fixture-only and opt-in when run manually.

On the Addition 6 safe-field typing pass:

- The live browser diagnostic profile still keeps action execution disabled; it does not enable `browser.input.type_text`.
- Safe-field typing is covered by the Screen Awareness action execution path and fake-backed fixture tests unless a future dedicated fixture live smoke is run.
- Any live typing smoke must use an isolated fixture/local page, explicit type gates, exact trust approval, redacted text handling, and no form submission, login, cookies, profiles, payment, CAPTCHA, or public-site typing.
- Playwright command return is not treated as success; semantic before/after evidence must support the expected outcome or the result remains partial, unsupported, ambiguous, or `completed_unverified`.
- A live fixture rerun closed contexts and browsers before the Playwright manager exited, eliminating the previous `Event loop is closed! Is Playwright already stopped?` cleanup warning.

Report file from this run:

- `reports/live_browser_integration/addition-playwright-5.1-live-click-focus-hardening.json`
- `reports/live_browser_integration/addition-playwright-6-live-type-safe-field.json`

On the Addition 6.1 safe-field typing hardening pass:

- A local `127.0.0.1` fixture smoke used explicit type gates and a temporary isolated Playwright context.
- Safe-field replace typing returned `verified_supported`, with only `[redacted text, 31 chars]` in the report.
- Readonly and disabled fields blocked with `target_readonly` and `target_disabled`; password/sensitive typing blocked before browser launch with `sensitive_text_blocked`.
- The fixture submit counter stayed `0`; no Enter/form-submit path was used.
- The report declares only `browser.input.type_text` for the gated smoke and keeps scroll, form submit, login, cookies, profiles, payment, visible-screen verification, truth verification, and workflow replay forbidden.

Report file from this run:

- `reports/live_browser_integration/addition-playwright-6.1-live-type-hardening.json`

On the Addition 7/7.1 safe choice-control pass:

- The normal live browser diagnostic profile still keeps choice action execution disabled; it does not enable `browser.input.check`, `browser.input.uncheck`, or `browser.input.select_option`.
- Safe choice-control execution is covered by the Screen Awareness action execution path and fake-backed fixture tests unless a dedicated fixture live smoke is run.
- Any live choice smoke must use an isolated fixture/local page, explicit choice gates, exact TrustService approval, bounded/redacted option summaries, no form submission, no login/cookies/profiles/payment/CAPTCHA, and no public-site automation.
- Checkbox/radio/dropdown command return is not treated as success; semantic before/after evidence must support the expected checked or selected state, and unexpected submit/navigation is not success.
- Addition 7.1 specifically requires target and option revalidation immediately before execution. Missing, disabled, hidden, type-changed, sensitive, duplicate, drifted, or stale-ordinal targets/options block before Playwright changes a control.
- Already-correct checkbox/dropdown states are reported as no-op evidence with `action_attempted = false`. Unexpected warning/dialog additions downgrade the result instead of becoming `verified_supported`.
- Optional local fixture smoke `reports/live_browser_integration/addition-playwright-7.1-live-choice-hardening.json` covered safe checkbox check, dropdown select, already-selected no-op, disabled checkbox block, sensitive terms block, option-drift block, cleanup closure, and forbidden capability absence.

On the Addition 8 bounded scroll pass:

- The normal live browser diagnostic profile still keeps scroll action execution disabled; it does not enable `browser.input.scroll` or `browser.input.scroll_to_target`.
- Safe scroll execution is covered by the Screen Awareness action execution path and fake-backed fixture tests unless a dedicated fixture live smoke is run.
- Any live scroll smoke must use an isolated fixture/local page, explicit scroll gates, exact TrustService approval, bounded direction/amount/max-attempt metadata, no user profile, no cookies, no public-site automation, and no click/type/select/submit chain after scrolling.
- `scroll_to_target` stops when the target is already present, found within bounded attempts, not found within the limit, ambiguous, or sensitive. Target-not-found and ambiguous outcomes are not success.
- Semantic before/after observations and safe scroll-position evidence support `verified_supported`; Playwright wheel command return alone is not verification.
- Optional local fixture smoke `reports/live_browser_integration/addition-playwright-8-live-scroll.json` covered a below-fold target with `verified_supported`, a bounded target-not-found result, a sensitive/login-payment page block before launch, no forbidden capabilities, no submit side effect, and no lingering browser-like processes.

On the Addition 8.1 browser interaction regression pass:

- The normal live browser diagnostic profile still keeps every action gate disabled; it does not enable click, focus, type, choice, or scroll execution.
- Cross-action fake-backed regression tests cover approval isolation, tampered target/action metadata, sensitive page-context blocking, no-submit invariants, redaction sentinels, canonical status mapping, and bounded UI/status payloads across the full implemented interaction ladder.
- Optional combined fixture smoke `reports/live_browser_integration/addition-playwright-8.1-live-interaction-kraken.json` used only local `127.0.0.1` fixture pages, explicit per-action gates, exact TrustService approval, no user profile/cookies/public-site automation, no form submission, and cleanup closure before reporting success. The local run covered click, safe-field typing, checkbox, dropdown select, scroll-to-target, sensitive-page blocking, forbidden capability absence, and raw typed text absence.

On the Addition 9 safe task-plan pass:

- The normal live browser diagnostic profile still keeps task-plan execution disabled; it does not enable `browser.task.safe_sequence`.
- Fake-backed tests cover explicit safe sequence construction, whole-plan approval binding, per-step execution through the existing safe primitives, conservative stop policy, final verification, redaction invariants, and no-submit proof.
- Any optional live task-plan smoke must use a local isolated fixture page, explicit task-plan and primitive gates, exact TrustService approval for the ordered plan, no user profile/cookies/public-site automation, no form submission, cleanup closure, and a report that omits raw typed text and hidden values.
- Safe task plans are not workflow replay or learned macros; they are bounded one-shot sequences of already-supported primitives.

On the Addition 9.1 safe task-plan hardening pass:

- The normal live browser diagnostic profile still keeps task-plan execution disabled and adds no new live action capability.
- Fake-backed tests cover tampered ordered plans, primitive-vs-plan approval crossover, consumed/expired/denied grant replay, mid-plan drift stops, skipped later steps, route-boundary preservation, redaction sentinels, and no-submit invariants.
- Any optional live hardening smoke must remain fixture-only and show a verified safe plan, a blocked tampered plan, a mid-plan drift stop, unchanged submit counter, raw text absence, closed cleanup, and forbidden capability absence.

## Troubleshooting

| Symptom | Report status/code | What to check |
|---|---|---|
| PowerShell refuses to run the script | script does not start | Use `powershell -ExecutionPolicy Bypass -File ...` for the diagnostic run. |
| Unsure what is installed | dependency helper report | Run `scripts/setup_live_browser_dependencies.ps1 -CheckOnly` and inspect the bounded JSON report. |
| Obscura CLI unavailable | `binary_missing` | Confirm `obscura` is on `PATH` or pass `-ObscuraBinary`. |
| GitHub release cannot be queried | `release_discovery_failed` | Check network/GitHub availability or use an explicit local zip. |
| Official release has no Windows zip | `windows_asset_missing` | Inspect release assets and pass a local zip if one exists elsewhere. |
| Multiple Windows assets match | `multiple_assets_matched` | Pass `-ObscuraAssetName` with the exact official asset name. |
| Release download fails | `download_failed` | Confirm the official GitHub asset URL and local network access. |
| Extraction fails | `extraction_failed` | Confirm the downloaded file is a zip and the install directory is writable. |
| Obscura zip missing | `zip_missing` | Provide a real `-ObscuraZipPath` or use an explicit trusted `-ObscuraReleaseUrl`. |
| Obscura binary cannot be launched | `binary_not_executable` | Confirm the extracted file is the Windows executable/script and not a README or nested archive. |
| Obscura version cannot be read | `version_unknown` | The binary may still be present; run the live smoke to classify provider compatibility. |
| Obscura CDP starts but no compatible endpoint | `partial`, `incompatible`, or `cdp_incompatible` | Inspect `/json/version`, `/json/list`, websocket discovery, and cleanup fields. Do not treat this as extraction success. |
| Obscura CDP endpoint is discovered but navigation fails | `cdp_navigation_unsupported` | The release exposed CDP endpoints but rejected `Page.navigate`; treat CDP inspection as incompatible until the provider binary supports navigation. |
| CDP endpoint never responds | `endpoint_unreachable` | Check binary compatibility, local firewall/process startup, and that CDP binds to `127.0.0.1`. |
| CDP cleanup warning | `cleanup_failed` or non-empty cleanup status | Check the reported process id before terminating anything manually. |
| Playwright unavailable | `dependency_missing` | Install the optional Python package only for local diagnostics. |
| Browser engine missing | `browsers_missing` | Run `python -m playwright install chromium` if local semantic smoke is desired. |
| Public URL smoke skipped | `public_url_required` | Set `STORMHELM_LIVE_BROWSER_TEST_URL` or pass `-Url`. |
| Cleanup concern | non-empty cleanup warning/status | Check the reported process id before terminating anything manually. |

## Safety Notes

Local fixture pages bind to `127.0.0.1`. Public web retrieval safety still blocks localhost/private/file/credential URLs by default; the fixture server is used for Playwright semantic observation diagnostics, not to weaken web retrieval safety defaults.

If an Obscura CDP process appears to remain after a failed manual smoke, inspect running `obscura` processes and terminate only the process id reported in the bounded live report. The managed CDP probe and provider both attempt graceful cleanup before forced cleanup.

## Normal CI

Normal CI should run the non-live slices. The live smoke file is marked and skipped unless the master environment gate is set:

```powershell
pytest tests\test_live_browser_provider_smoke.py -q
```

Expected default result is one skipped test.
