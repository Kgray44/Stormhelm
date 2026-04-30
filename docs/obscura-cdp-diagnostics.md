# Obscura CDP Diagnostics

Obscura CDP mode is optional, disabled by default, and limited to backend-owned localhost headless page diagnostics and, only when supported by the installed binary, headless page inspection. It does not click, type, scroll, submit forms, reuse logged-in browser context, read/write cookies, bypass CAPTCHA or anti-bot controls, observe the user's visible screen, or verify webpage claims as true.

## Configure

Set `web_retrieval.obscura.cdp.enabled = true` and point `web_retrieval.obscura.cdp.binary_path` at the installed Obscura binary if it is not on `PATH`. The CDP host must remain `127.0.0.1`, `localhost`, or `::1`; public network binds are rejected. `port = 0` uses a dynamic local port.

## Manual Probe

Run one of these from the repo root:

```powershell
python -m stormhelm.core.web_retrieval.obscura_cdp_probe
scripts/smoke_obscura_cdp.ps1
scripts/smoke_obscura_cdp.ps1 -Url https://example.com -Output logs/reports/obscura-cdp-smoke.json
scripts/run_live_browser_checks.ps1 -Enable -ObscuraCdp -Url https://example.com
```

The probe checks binary discovery, optional `--version`, localhost `obscura serve`, endpoint reachability, `/json/version`, `/json/list` or `/json`, browser/page websocket discovery, protocol fields when exposed, navigation support, and cleanup. The optional `-Url` path runs a separate safe public URL inspection only when page navigation is supported and records counts/status only.

`scripts/run_live_browser_checks.ps1` wraps the same compatibility posture into the broader opt-in live browser integration report. It still requires `STORMHELM_LIVE_BROWSER_TESTS=true` through the script's `-Enable` switch or the environment, and it does not run in normal CI.

Compatibility levels:

- `ready`: version and page websocket endpoint behavior looks usable.
- `partial`: page inspection can likely proceed, but nonessential endpoint details are missing.
- `diagnostic_only`: a CDP endpoint was discovered, but the installed Obscura release does not support the navigation/page-inspection path Stormhelm needs.
- `unsupported`: required endpoint or websocket data is missing, malformed, unreachable, or host/scheme mismatched.
- `failed`: binary discovery, process startup, or the probe itself failed.

Common failure reasons include `binary_missing`, `permission_denied`, `process_exited_immediately`, `dynamic_port_unavailable`, `endpoint_unreachable`, `malformed_json`, `non_json_response`, `page_websocket_missing`, `endpoint_host_mismatch`, and `cdp_navigation_unsupported`.

The official Windows `h4ckf0r0day/obscura` v0.1.1 release observed on April 30, 2026 exposed `/json/version`, `/json/list`, browser websocket, and page websocket endpoints, but `Page.navigate` returned `No page for session`. Stormhelm classifies that shape as diagnostic-only, does not select CDP for page extraction, and recommends the working Obscura CLI provider for rendered page evidence.

## Safety Boundaries

Diagnostics are bounded and redacted. They expose status, counts, compatibility level, protocol version, optional domain availability, startup/navigation/cleanup states, and the `headless_cdp_page_evidence` claim ceiling. They do not expose raw DOM text, full HTML, cookies, credentials, screenshots, huge stdout/stderr, visible-screen claims, or truth-verification claims.

Playwright, Puppeteer, CDP input actions, Chromium fallback, login/session reuse, credential handling, CAPTCHA/anti-bot bypass, browser open replacement, screen-awareness replacement, and long-term raw page storage remain intentionally deferred.
