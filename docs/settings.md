# Settings Reference

Stormhelm loads typed config from TOML, `.env`, environment variables, and runtime path detection. Defaults are in `config/default.toml`; model defaults and missing-key behavior are in `src/stormhelm/config/models.py` and `src/stormhelm/config/loader.py`.

## Load Order

| Order | Source | Notes |
|---|---|---|
| 1 | `config/default.toml` | Required defaults. |
| 2 | local development TOML copied from `config/development.toml.example` | Optional local dev override when present. |
| 3 | Portable/user config | Used by packaged/runtime path logic. |
| 4 | Explicit config path | Used when caller supplies one. |
| 5 | `.env` | Parsed as key/value pairs. |
| 6 | Process environment | Overrides prior values. |

Sources: `src/stormhelm/config/loader.py`, `config/default.toml`, `config/development.toml.example`, `config/development-live-browser.toml.example`
Tests: `tests/test_config_loader.py`

## Live Browser Integration Profile

`config/development-live-browser.toml.example` is a local diagnostic profile for live Obscura CLI, Obscura CDP, and Playwright semantic observation checks. It is not loaded by default. It keeps browser actions, form fill, login, cookies, screenshots, visible-screen verification, and truth verification disabled.

Live-test environment gates:

| Env var | Meaning |
|---|---|
| `STORMHELM_LIVE_BROWSER_TESTS` | Master gate. Must be `true` before live checks run. |
| `STORMHELM_ENABLE_LIVE_OBSCURA` | Enables the Obscura CLI smoke path. |
| `STORMHELM_ENABLE_LIVE_OBSCURA_CDP` | Enables the Obscura CDP compatibility/smoke path. |
| `STORMHELM_ENABLE_LIVE_PLAYWRIGHT` | Enables Playwright readiness checks. |
| `STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH` | Allows the live Playwright semantic smoke to launch an isolated temporary browser context. |
| `STORMHELM_OBSCURA_BINARY` | Obscura binary name/path for live checks. |
| `STORMHELM_LIVE_BROWSER_TEST_URL` | Optional public URL for Obscura provider smoke checks. |

Run `scripts/setup_live_browser_dependencies.ps1 -CheckOnly` to inspect optional local dependencies, then `scripts/run_live_browser_checks.ps1` or `python -m stormhelm.core.live_browser_integration` for a bounded JSON report. The setup helper installs Playwright only when explicit install flags are supplied and installs Obscura only when `-InstallObscura` is paired with `-DownloadLatestObscuraRelease`, a local zip path, or an explicit official `h4ckf0r0day/obscura` GitHub release URL. Normal CI should leave these gates unset; `tests/test_live_browser_provider_smoke.py` skips by default.

Sources: `src/stormhelm/core/live_browser_integration.py`, `scripts/setup_live_browser_dependencies.ps1`, `scripts/run_live_browser_checks.ps1`, `config/development-live-browser.toml.example`
Tests: `tests/test_live_browser_integration.py`, `tests/test_live_browser_provider_smoke.py`

## Live Camera Kraken Profile

The live Camera Awareness Kraken is hardware-gated and not part of normal CI. It must use a real local camera for camera-required rows when `--require-real-camera` is supplied. Mock camera providers and synthetic frames do not count as a live pass.

| Env var | Meaning |
|---|---|
| `STORMHELM_LIVE_CAMERA_TESTS` | Master gate. Must be `true` unless the runner is invoked with `--enable-live-camera`. |
| `STORMHELM_ENABLE_LIVE_CAMERA` | Allows the runner to attempt real local camera capture. |
| `STORMHELM_CAMERA_REQUIRE_REAL_DEVICE` | Requires real hardware evidence; mock capture is a blocking failure. |
| `STORMHELM_CAMERA_DEVICE_INDEX` | Selects the camera from the available local devices. |
| `STORMHELM_CAMERA_CAPTURE_TIMEOUT_MS` | Bounds each still-capture attempt. |
| `STORMHELM_CAMERA_SAVE_ARTIFACTS` | Saves bounded local test artifacts only when explicitly enabled; default is false. |

Example:

```powershell
$env:STORMHELM_LIVE_CAMERA_TESTS='true'
$env:STORMHELM_ENABLE_LIVE_CAMERA='true'
$env:STORMHELM_CAMERA_REQUIRE_REAL_DEVICE='true'
python scripts\run_camera_awareness_kraken.py --output-dir .artifacts\kraken\camera-awareness-live-01 --require-real-camera --enable-live-camera
```

Missing hardware, permission denial, device busy, capture timeout, empty frames, disabled config, or privacy blocks are reported as typed unavailable/blocked states. A listed device is not considered working unless a frame is captured. Raw frames are not included in events/status/reports by default.

Sources: `src/stormhelm/core/kraken/camera_awareness_live.py`, `scripts/run_camera_awareness_kraken.py`, `src/stormhelm/core/camera_awareness/providers.py`
Tests: `tests/test_camera_awareness_live_kraken.py`

## Core Settings

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `app_name` | string | `Stormhelm` | No | any string | TOML | Loader/model fallback. |
| `release_channel` | string | `dev` | No | any string | TOML/env | Loader/model fallback. |
| `environment` | string | `development` | No | any string | TOML/env | Loader/model fallback. |
| `debug` | bool | `true` | No | bool | TOML/env | Parsed as bool; invalid env parse can fail config load. |
| `network.host` | string | `127.0.0.1` | No | local host/IP | TOML/env | Defaults local-only. |
| `network.port` | int | `8765` | No | TCP port | TOML/env | Defaults `8765`. |

Env overrides: `STORMHELM_ENV`, `STORMHELM_DEBUG`, `STORMHELM_RELEASE_CHANNEL`, `STORMHELM_CORE_HOST`, `STORMHELM_CORE_PORT`.

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/config/models.py`
Tests: `tests/test_config_loader.py`

## Storage And Logging

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `storage.data_dir` | path/string | empty | No | path | TOML/env | Empty resolves under `%LOCALAPPDATA%\Stormhelm`. |
| `storage.database_path` | path/string | empty | No | path | TOML | Empty resolves under runtime data dir. |
| `storage.logs_dir` | path/string | empty | No | path | TOML | Empty resolves under runtime logs dir. |
| `storage.state_dir` | path/string | empty | No | path | TOML | Empty resolves under runtime state dir. |
| `logging.level` | string | `DEBUG` | No | Python logging level | TOML | Used by logging setup. |
| `logging.file_name` | string | `stormhelm.log` | No | filename | TOML | Used under logs dir. |
| `logging.max_file_bytes` | int | `1000000` | No | positive int | TOML | Rotating log threshold. |
| `logging.backup_count` | int | `3` | No | nonnegative int | TOML | Rotating log retention. |

Env override: `STORMHELM_DATA_DIR`.

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/app/logging.py`, `src/stormhelm/shared/paths.py`
Tests: `tests/test_config_loader.py`, `tests/test_storage.py`

## Concurrency And UI

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `concurrency.max_workers` | int | `8` | No | positive int | TOML/env | Job manager worker count. |
| `concurrency.queue_size` | int | `128` | No | positive int | TOML | Bounded job queue size. |
| `concurrency.default_job_timeout_seconds` | number | `20` | No | positive number | TOML/env | Tool job timeout fallback. |
| `concurrency.history_limit` | int | `500` | No | positive int | TOML | In-memory job history limit. |
| `ui.poll_interval_ms` | int | `1500` | No | positive int | TOML | UI polling interval. |
| `ui.hide_to_tray_on_close` | bool | `true` | No | bool | TOML | Close can hide shell instead of quitting. |
| `ui.ghost_shortcut` | string | `Ctrl+Space` | No | parseable hotkey | TOML | Used by Windows hotkey proxy. |

Env overrides: `STORMHELM_MAX_CONCURRENT_JOBS`, `STORMHELM_DEFAULT_JOB_TIMEOUT_SECONDS`.

Sources: `config/default.toml`, `src/stormhelm/config/models.py`, `src/stormhelm/core/jobs/manager.py`, `src/stormhelm/ui/ghost_input.py`
Tests: `tests/test_job_manager.py`, `tests/test_ghost_input.py`, `tests/test_ui_tray.py`

## Lifecycle / Startup

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `lifecycle.startup_enabled` | bool | model default | No | bool | model/env/user config | Controls startup registration posture. |
| `lifecycle.start_core_with_windows` | bool | model default | No | bool | model/env/user config | Startup command generation. |
| `lifecycle.start_shell_with_windows` | bool | model default | No | bool | model/env/user config | Startup command generation. |
| `lifecycle.tray_only_startup` | bool | model default | No | bool | model/env/user config | Shell startup behavior. |
| `lifecycle.ghost_ready_on_startup` | bool | model default | No | bool | model/env/user config | Startup UX posture. |
| `lifecycle.background_core_resident` | bool | model default | No | bool | model/env/user config | Core residency posture. |
| `lifecycle.auto_restart_core` | bool | model default | No | bool | model/env/user config | UI recovery behavior. |
| `lifecycle.max_core_restart_attempts` | int | model default | No | int | model/env/user config | Restart guard. |
| `lifecycle.restart_failure_window_seconds` | number | model default | No | seconds | model/env/user config | Crash/restart window. |
| `lifecycle.shell_heartbeat_interval_seconds` | number | model default | No | seconds | model/env/user config | Shell heartbeat cadence. |
| `lifecycle.shell_stale_after_seconds` | number | model default | No | seconds | model/env/user config | Shell stale detection. |
| `lifecycle.core_restart_backoff_ms` | int | model default | No | milliseconds | model/env/user config | Restart delay. |

Env overrides: `STORMHELM_STARTUP_ENABLED`, `STORMHELM_START_CORE_WITH_WINDOWS`, `STORMHELM_START_SHELL_WITH_WINDOWS`, `STORMHELM_TRAY_ONLY_STARTUP`, `STORMHELM_GHOST_READY_ON_STARTUP`, `STORMHELM_BACKGROUND_CORE_RESIDENT`, `STORMHELM_AUTO_RESTART_CORE`, `STORMHELM_MAX_CORE_RESTART_ATTEMPTS`, `STORMHELM_RESTART_FAILURE_WINDOW_SECONDS`, `STORMHELM_SHELL_HEARTBEAT_INTERVAL_SECONDS`, `STORMHELM_SHELL_STALE_AFTER_SECONDS`, `STORMHELM_CORE_RESTART_BACKOFF_MS`.

Sources: `src/stormhelm/config/models.py`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/lifecycle/service.py`
Tests: `tests/test_lifecycle_service.py`, `tests/test_main_controller_lifecycle.py`

## Event Stream

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `event_stream.enabled` | bool | `true` | No | bool | TOML | Enables event stream surfaces. |
| `event_stream.retention_capacity` | int | `500` | No | positive int | TOML | Bounded in-memory buffer. |
| `event_stream.replay_limit` | int | `128` | No | positive int | TOML | Replay window. |
| `event_stream.heartbeat_seconds` | number | `15.0` | No | seconds | TOML | SSE heartbeat interval. |

Sources: `config/default.toml`, `src/stormhelm/core/events.py`, `src/stormhelm/core/api/app.py`
Tests: `tests/test_events.py`, `tests/test_ui_client_streaming.py`

## Location And Weather

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `location.allow_approximate_lookup` | bool | `true` | No | bool | TOML/env | Allows approximate lookup when no home location is configured. |
| `location.lookup_timeout_seconds` | number | `5` | No | seconds | TOML/env | Provider timeout. |
| `location.home_label` | string | empty | No | string | TOML/env | Used when configured. |
| `location.home_city` | string | empty | No | string | TOML/env | Used when configured. |
| `location.home_region` | string | empty | No | string | TOML/env | Used when configured. |
| `location.home_country` | string | empty | No | string | TOML/env | Used when configured. |
| `location.home_latitude` | number/string | empty | No | latitude | TOML/env | Empty means not configured. |
| `location.home_longitude` | number/string | empty | No | longitude | TOML/env | Empty means not configured. |
| `location.home_timezone` | string | empty | No | timezone id | TOML/env | Empty means not configured. |
| `weather.enabled` | bool | `true` | No | bool | TOML/env | Enables weather tool. |
| `weather.units` | string | `imperial` | No | `imperial`, provider-supported units | TOML/env | Passed to weather tool/provider logic. |
| `weather.provider_base_url` | string | `https://api.open-meteo.com/v1` | No | URL | TOML/env | Default Open-Meteo API base. |
| `weather.timeout_seconds` | number | `6` | No | seconds | TOML/env | Weather request timeout. |

Env overrides: `STORMHELM_HOME_LABEL`, `STORMHELM_HOME_CITY`, `STORMHELM_HOME_REGION`, `STORMHELM_HOME_COUNTRY`, `STORMHELM_HOME_LATITUDE`, `STORMHELM_HOME_LONGITUDE`, `STORMHELM_HOME_TIMEZONE`, `STORMHELM_ALLOW_APPROXIMATE_LOCATION`, `STORMHELM_LOCATION_LOOKUP_TIMEOUT_SECONDS`, `STORMHELM_WEATHER_ENABLED`, `STORMHELM_WEATHER_UNITS`, `STORMHELM_WEATHER_BASE_URL`, `STORMHELM_WEATHER_TIMEOUT_SECONDS`.

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/tools/builtins/system_state.py`
Tests: `tests/test_long_tail_power.py`, `tests/test_tool_registry.py`

## Hardware Telemetry

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `hardware_telemetry.enabled` | bool | `true` | No | bool | TOML/env | Enables telemetry status path. |
| `hardware_telemetry.helper_timeout_seconds` | number | `12.0` | No | seconds | TOML/env | Helper timeout. |
| `hardware_telemetry.provider_timeout_seconds` | number | `5.0` | No | seconds | TOML/env | Provider timeout. |
| `hardware_telemetry.idle_cache_ttl_seconds` | number | `30` | No | seconds | TOML/env | Idle cache TTL. |
| `hardware_telemetry.active_cache_ttl_seconds` | number | `8` | No | seconds | TOML/env | Active cache TTL. |
| `hardware_telemetry.burst_cache_ttl_seconds` | number | `2` | No | seconds | TOML/env | Burst cache TTL. |
| `hardware_telemetry.elevated_helper_enabled` | bool | `false` | No | bool | TOML/env | Elevated helper disabled by default. |
| `hardware_telemetry.elevated_helper_timeout_seconds` | number | `20.0` | No | seconds | TOML/env | Elevated helper timeout. |
| `hardware_telemetry.elevated_helper_cooldown_seconds` | number | `120.0` | No | seconds | TOML/env | Cooldown between attempts. |
| `hardware_telemetry.hwinfo_enabled` | bool | `true` | No | bool | TOML/env | Allows HWiNFO path when configured. |
| `hardware_telemetry.hwinfo_executable_path` | string | empty | No | file path | TOML/env | Empty means auto/none. |

Env overrides are the `STORMHELM_HARDWARE_TELEMETRY_*` keys shown in `loader.py`.

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/system/hardware_telemetry.py`
Tests: `tests/test_hardware_telemetry.py`

## Screen Awareness

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `screen_awareness.enabled` | bool | `true` | No | bool | TOML/env | Disables subsystem if false. |
| `screen_awareness.phase` | string | `phase12` | No | string | TOML/env | Status label and hardening behavior. |
| `screen_awareness.planner_routing_enabled` | bool | `true` | No | bool | TOML/env | Allows planner route to subsystem. |
| `screen_awareness.debug_events_enabled` | bool | `true` | No | bool | TOML/env | Enables debug event posture. |
| `screen_awareness.observation_enabled` | bool | `true` | No | bool | TOML/env | Native observation flag. |
| `screen_awareness.interpretation_enabled` | bool | `true` | No | bool | TOML/env | Interpretation flag. |
| `screen_awareness.grounding_enabled` | bool | `true` | No | bool | TOML/env | Grounding flag. |
| `screen_awareness.guidance_enabled` | bool | `true` | No | bool | TOML/env | Guidance flag. |
| `screen_awareness.action_enabled` | bool | `true` | No | bool | TOML/env | Action engine flag. |
| `screen_awareness.action_policy_mode` | string | `confirm_before_act` | No | `observe_only`, `confirm_before_act`, other enum values in models | TOML/env | Invalid values fall back in service logic. |
| `screen_awareness.verification_enabled` | bool | `true` | No | bool | TOML/env | Verification flag. |
| `screen_awareness.memory_enabled` | bool | `true` | No | bool | TOML/env | Memory integration flag. |
| `screen_awareness.adapters_enabled` | bool | `true` | No | bool | TOML/env | Semantic adapters flag. |
| `screen_awareness.problem_solving_enabled` | bool | `true` | No | bool | TOML/env | Problem solving flag. |
| `screen_awareness.workflow_learning_enabled` | bool | `true` | No | bool | TOML/env | Workflow learning flag. |
| `screen_awareness.brain_integration_enabled` | bool | `true` | No | bool | TOML/env | Brain integration flag. |
| `screen_awareness.power_features_enabled` | bool | `true` | No | bool | TOML/env | Power features flag. |
| `screen_awareness.browser_adapters.playwright.enabled` | bool | `false` | No | bool | TOML/env | Optional Playwright browser semantic adapter scaffold; disabled by default. |
| `screen_awareness.browser_adapters.playwright.provider` | string | `playwright` | No | `playwright` | TOML | Provider label only; no dependency required in normal CI. |
| `screen_awareness.browser_adapters.playwright.mode` | string | `semantic_observation` | No | `semantic_observation` | TOML | Observation/grounding scaffold mode. |
| `screen_awareness.browser_adapters.playwright.allow_browser_launch` | bool | `false` | No | bool | TOML/env | Browser launch is not allowed by default. When enabled with the dev gate, Playwright may launch an isolated temporary context for semantic observation or explicitly gated browser actions. |
| `screen_awareness.browser_adapters.playwright.allow_connect_existing` | bool | `false` | No | bool | TOML/env | Connecting to real user browser sessions is not allowed by default. |
| `screen_awareness.browser_adapters.playwright.allow_actions` | bool | `false` | No | bool | TOML/env | Master action-execution gate. Click/focus/type_text still require their specific gates, the dev action gate, isolated launch readiness, and trust approval. |
| `screen_awareness.browser_adapters.playwright.allow_click` | bool | `false` | No | bool | TOML/env | Enables runtime declaration and execution of trust-gated click only when all other Playwright action gates pass, a fresh target fingerprint is still valid, and the locator is unambiguous. |
| `screen_awareness.browser_adapters.playwright.allow_focus` | bool | `false` | No | bool | TOML/env | Enables runtime declaration and execution of trust-gated focus only when all other Playwright action gates pass, a fresh target fingerprint is still valid, and the locator is unambiguous. |
| `screen_awareness.browser_adapters.playwright.allow_type_text` | bool | `false` | No | bool | TOML/env | Enables runtime declaration and execution of trust-gated safe-field `type_text` only when `allow_dev_type_text` and all other Playwright action gates pass. Disabled by default. |
| `screen_awareness.browser_adapters.playwright.allow_check` | bool | `false` | No | bool | TOML/env | Enables runtime declaration and execution of trust-gated safe checkbox/radio check only when `allow_dev_choice_controls` and all other Playwright action gates pass. Disabled by default. |
| `screen_awareness.browser_adapters.playwright.allow_uncheck` | bool | `false` | No | bool | TOML/env | Enables runtime declaration and execution of trust-gated safe checkbox uncheck only when `allow_dev_choice_controls` and all other Playwright action gates pass. Disabled by default. |
| `screen_awareness.browser_adapters.playwright.allow_select_option` | bool | `false` | No | bool | TOML/env | Enables runtime declaration and execution of trust-gated safe dropdown/select option changes only when `allow_dev_choice_controls` and all other Playwright action gates pass. Disabled by default. |
| `screen_awareness.browser_adapters.playwright.allow_scroll` | bool | `false` | No | bool | TOML/env | Enables runtime declaration and execution of trust-gated bounded page scrolling only when `allow_dev_scroll` and all other Playwright action gates pass. Disabled by default. |
| `screen_awareness.browser_adapters.playwright.allow_scroll_to_target` | bool | `false` | No | bool | TOML/env | Enables trust-gated bounded scroll-to-target when `allow_dev_scroll` and all other Playwright action gates pass. Disabled by default. |
| `screen_awareness.browser_adapters.playwright.allow_task_plans` | bool | `false` | No | bool | TOML/env | Enables runtime declaration and execution of trust-gated safe multi-step browser task plans only when `allow_dev_task_plans`, all master action gates, and every required primitive step gate pass. Disabled by default; tampered, expired, reordered, or approval-mismatched plans fail closed. |
| `screen_awareness.browser_adapters.playwright.allow_form_fill` | bool | `false` | No | bool | TOML/env | Form fill remains unsupported. |
| `screen_awareness.browser_adapters.playwright.allow_form_submit` | bool | `false` | No | bool | TOML/env | Form submission remains unsupported. |
| `screen_awareness.browser_adapters.playwright.allow_login` | bool | `false` | No | bool | TOML/env | Login handling remains unsupported. |
| `screen_awareness.browser_adapters.playwright.allow_cookies` | bool | `false` | No | bool | TOML/env | Cookie/session access remains unsupported. |
| `screen_awareness.browser_adapters.playwright.allow_user_profile` | bool | `false` | No | bool | TOML/env | User profile attachment remains unsupported; isolated temporary contexts are the only live path. |
| `screen_awareness.browser_adapters.playwright.allow_payment` | bool | `false` | No | bool | TOML/env | Payment handling remains unsupported. |
| `screen_awareness.browser_adapters.playwright.allow_screenshots` | bool | `false` | No | bool | TOML/env | Screenshots are not enabled or treated as visible-screen truth in this scaffold. |
| `screen_awareness.browser_adapters.playwright.allow_dev_adapter` | bool | `false` | No | bool | TOML/env | Required before mock/dev readiness can become `mock_ready`; disabled by default. |
| `screen_awareness.browser_adapters.playwright.allow_dev_actions` | bool | `false` | No | bool | TOML/env | Required in addition to `allow_actions` and the specific click/focus/type gate before browser action execution can run. |
| `screen_awareness.browser_adapters.playwright.allow_dev_type_text` | bool | `false` | No | bool | TOML/env | Additional dev gate for safe-field `type_text`; prevents accidental typing even if `allow_type_text` is set. |
| `screen_awareness.browser_adapters.playwright.allow_dev_choice_controls` | bool | `false` | No | bool | TOML/env | Additional dev gate for safe checkbox/radio/dropdown choice controls; prevents accidental choice execution even if an individual choice gate is set. |
| `screen_awareness.browser_adapters.playwright.allow_dev_scroll` | bool | `false` | No | bool | TOML/env | Additional dev gate for bounded scroll and scroll-to-target; prevents accidental page scrolling even if an individual scroll gate is set. |
| `screen_awareness.browser_adapters.playwright.allow_dev_task_plans` | bool | `false` | No | bool | TOML/env | Additional dev gate for safe multi-step browser task plans; prevents accidental sequencing even if individual primitive gates are set. Addition 9.1 adds hardening under the same gates and does not add new config fields. |
| `screen_awareness.browser_adapters.playwright.max_session_seconds` | int | `120` | No | positive int | TOML | Session cap for future long-lived phases; Addition 2 closes each isolated observation context immediately. |
| `screen_awareness.browser_adapters.playwright.navigation_timeout_seconds` | int | `12000` | No | milliseconds | TOML | Navigation timeout for isolated semantic observation. |
| `screen_awareness.browser_adapters.playwright.observation_timeout_seconds` | int | `8000` | No | milliseconds | TOML | Semantic observation timeout budget for future expansion; extraction remains bounded by fixed list/text caps and a short stabilization wait. |
| `screen_awareness.browser_adapters.playwright.max_scroll_attempts` | int | `5` | No | positive bounded int | TOML/env | Maximum bounded attempts for scroll-to-target before returning not-found or partial evidence. |
| `screen_awareness.browser_adapters.playwright.scroll_step_pixels` | int | `700` | No | positive int | TOML/env | Default wheel distance for bounded scroll actions. |
| `screen_awareness.browser_adapters.playwright.scroll_timeout_seconds` | float | `8.0` | No | positive seconds | TOML/env | Overall scroll action timing budget for future live smoke/reporting. |
| `screen_awareness.browser_adapters.playwright.max_scroll_distance_pixels` | int | `5000` | No | positive int | TOML/env | Maximum per-plan scroll distance bound used to clamp requested scroll amounts. |
| `screen_awareness.browser_adapters.playwright.max_task_steps` | int | `5` | No | positive bounded int | TOML/env | Maximum number of steps in a safe browser task plan. Longer plans are blocked instead of split or guessed. |
| `screen_awareness.browser_adapters.playwright.stop_on_unverified_step` | bool | `true` | No | bool | TOML/env | Stops a task plan when a step completes without sufficient semantic verification. |
| `screen_awareness.browser_adapters.playwright.stop_on_partial_step` | bool | `true` | No | bool | TOML/env | Stops a task plan when a step returns partial evidence by default. |
| `screen_awareness.browser_adapters.playwright.stop_on_ambiguous_step` | bool | `true` | No | bool | TOML/env | Stops a task plan when a step becomes ambiguous. |
| `screen_awareness.browser_adapters.playwright.stop_on_unexpected_navigation` | bool | `true` | No | bool | TOML/env | Stops a task plan when a step causes unexpected navigation or submit-like evidence. |
| `screen_awareness.browser_adapters.playwright.debug_events_enabled` | bool | `true` | No | bool | TOML/env | Allows bounded readiness/mock/live observation/grounding/guidance/cleanup events. |

Readiness statuses include `disabled`, `dev_gate_required`, `dependency_missing`, `browsers_missing`, `mock_ready`, `runtime_ready`, `unavailable`, and `failed`. `mock_ready` does not mean Stormhelm observed a real browser; it means the dev-gated mock provider can produce fixture-backed semantic observations for tests and diagnostics. `runtime_ready` allows real isolated semantic observation only when Playwright is installed, browser engines are available/checkable, `enabled = true`, `allow_dev_adapter = true`, and `allow_browser_launch = true`.

Env overrides include `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ENABLED`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_ACTIONS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_CLICK`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_FOCUS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_TYPE_TEXT`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_TYPE_TEXT`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_CHECK`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_UNCHECK`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SELECT_OPTION`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_CHOICE_CONTROLS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SCROLL`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SCROLL_TO_TARGET`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_SCROLL`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_TASK_PLANS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_TASK_PLANS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_MAX_TASK_STEPS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_UNVERIFIED_STEP`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_PARTIAL_STEP`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_AMBIGUOUS_STEP`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_UNEXPECTED_NAVIGATION`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_MAX_SCROLL_ATTEMPTS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_SCROLL_STEP_PIXELS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_SCROLL_TIMEOUT_SECONDS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_MAX_SCROLL_DISTANCE_PIXELS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_CONNECT_EXISTING`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_ADAPTER`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_ACTIONS`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_FORM_FILL`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_FORM_SUBMIT`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_LOGIN`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_COOKIES`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_USER_PROFILE`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_PAYMENT`, `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SCREENSHOTS`, and `STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_DEBUG_EVENTS_ENABLED`. Live semantic observation diagnostics also require `STORMHELM_LIVE_BROWSER_TESTS=true`, `STORMHELM_ENABLE_LIVE_PLAYWRIGHT=true`, and `STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH=true`; they use an isolated temporary browser context, redact sensitive field values, clear temporary cookies, report iframe/shadow-DOM/large-page limitations when detected, and still expose no action capabilities. Addition 5/6.1/7.1/8/9 click/focus/type/choice/scroll/task-plan execution is not enabled by the live diagnostic profile; it requires explicit runtime config gates plus trust approval, blocks stale plans/target drift/option drift/ambiguous locators, records cleanup status, redacts typed text and option values, blocks append typing as unsupported, prevents form submission, classifies no-op choice and already-visible scroll target states truthfully, bounds scroll-to-target attempts, binds ordered task-plan steps, and still does not expose form/login/cookie/profile/payment/download/workflow-replay capabilities. Addition 4 before/after comparison uses existing observations and does not require a separate action or browser-control setting.

Sources: `config/default.toml`, `src/stormhelm/config/models.py`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/screen_awareness/service.py`, `src/stormhelm/core/screen_awareness/browser_playwright.py`
Tests: `tests/test_screen_awareness_service.py`, `tests/test_screen_awareness_action.py`, `tests/test_screen_awareness_verification.py`, `tests/test_screen_awareness_playwright_adapter_scaffold.py`, `tests/test_screen_awareness_playwright_adapter_integration.py`, `tests/test_screen_awareness_playwright_live_semantic.py`, `tests/test_screen_awareness_playwright_grounding_robustness.py`, `tests/test_screen_awareness_playwright_semantic_verification.py`, `tests/test_screen_awareness_playwright_task_plans.py`

## Calculations

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `calculations.enabled` | bool | `true` | No | bool | TOML/env | Disables subsystem if false. |
| `calculations.planner_routing_enabled` | bool | `true` | No | bool | TOML/env | Allows planner routing. |
| `calculations.debug_events_enabled` | bool | `true` | No | bool | TOML/env | Enables debug status/events. |

Env overrides: `STORMHELM_CALCULATIONS_ENABLED`, `STORMHELM_CALCULATIONS_PLANNER_ROUTING_ENABLED`, `STORMHELM_CALCULATIONS_DEBUG_EVENTS_ENABLED`.

Sources: `config/default.toml`, `src/stormhelm/core/calculations/service.py`
Tests: `tests/test_calculations.py`

## Web Retrieval

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `web_retrieval.enabled` | bool | `true` | No | bool | TOML/env | Disables public web retrieval if false. |
| `web_retrieval.planner_routing_enabled` | bool | `true` | No | bool | TOML/env | Allows summarize/read/render/extract URL requests to route here. |
| `web_retrieval.debug_events_enabled` | bool | `true` | No | bool | TOML/env | Emits compact retrieval events without raw page text/html. |
| `web_retrieval.default_provider` | string | `auto` | No | `auto`, `http`, `obscura`, `obscura_cdp` | TOML/env | Selects provider order; `auto` starts with HTTP unless rendering is requested. CDP is selected for extraction only when readiness proves page-inspection support, or by explicit CDP requests that may return diagnostic-only/fallback state. |
| `web_retrieval.max_url_count` | int | `8` | No | positive int | TOML/env | Caps URLs per request. |
| `web_retrieval.max_url_chars` | int | `4096` | No | positive int | TOML/env | Blocks extremely long URLs before provider dispatch. |
| `web_retrieval.max_parallel_pages` | int | `3` | No | positive int | TOML/env | Provider concurrency ceiling for future parallel retrieval. |
| `web_retrieval.timeout_seconds` | number | `12.0` | No | seconds | TOML/env | Overall retrieval timeout default. |
| `web_retrieval.max_text_chars` | int | `60000` | No | positive int | TOML/env | Caps extracted text stored in result payloads. |
| `web_retrieval.max_html_chars` | int | `250000` | No | positive int | TOML/env | Caps optional extracted HTML. |
| `web_retrieval.respect_robots` | bool | `true` | No | bool | TOML | Policy flag for providers that can honor robots metadata. |
| `web_retrieval.allow_private_network_urls` | bool | `false` | No | bool | TOML/env | Blocks local/private/loopback URLs by default. |
| `web_retrieval.allow_file_urls` | bool | `false` | No | bool | TOML | File URLs remain outside public web retrieval. |
| `web_retrieval.allow_logged_in_context` | bool | `false` | No | bool | TOML | Logged-in browser context is not supported in this addition. |
| `web_retrieval.http.enabled` | bool | `true` | No | bool | TOML/env | Enables static HTTP extraction baseline. |
| `web_retrieval.http.timeout_seconds` | number | `8.0` | No | seconds | TOML/env | HTTP provider timeout. |
| `web_retrieval.obscura.enabled` | bool | `false` | No | bool | TOML/env | Optional Obscura CLI provider; disabled by default. |
| `web_retrieval.obscura.binary_path` | string | `obscura` | No | executable path/name | TOML/env | Missing binary reports `binary_missing` instead of silently falling back. |
| `web_retrieval.obscura.allow_cdp_server` | bool | `false` | No | bool | TOML | Legacy CLI flag; managed CDP settings live under `web_retrieval.obscura.cdp`. |
| `web_retrieval.obscura.stealth_enabled` | bool | `false` | No | bool | TOML | Anti-bot/stealth behavior is not enabled. |
| `web_retrieval.obscura.allow_js_eval` | bool | `false` | No | bool | TOML | Arbitrary JS eval is out of scope. |
| `web_retrieval.obscura.max_concurrency` | int | `3` | No | positive int | TOML/env | Obscura concurrency ceiling. |
| `web_retrieval.obscura.cdp.enabled` | bool | `false` | No | bool | TOML/env | Enables optional managed Obscura CDP sessions. Disabled by default. |
| `web_retrieval.obscura.cdp.binary_path` | string | `obscura` | No | executable path/name | TOML/env | Binary used for `obscura serve`; missing binary reports `binary_missing`. |
| `web_retrieval.obscura.cdp.host` | string | `127.0.0.1` | No | localhost only | TOML/env | CDP server must bind locally; public binds are rejected. |
| `web_retrieval.obscura.cdp.port` | int | `0` | No | `0` or local port | TOML/env | `0` chooses a dynamic local port. |
| `web_retrieval.obscura.cdp.startup_timeout_seconds` | number | `8.0` | No | seconds | TOML | Maximum wait for compatible localhost CDP endpoints such as `/json/version`, `/json/list`, or `/json`. |
| `web_retrieval.obscura.cdp.shutdown_timeout_seconds` | number | `4.0` | No | seconds | TOML | Graceful stop wait before forced cleanup. |
| `web_retrieval.obscura.cdp.navigation_timeout_seconds` | number | `12.0` | No | seconds | TOML | CDP navigation/load wait bound. |
| `web_retrieval.obscura.cdp.max_session_seconds` | number | `120.0` | No | seconds | TOML | Maximum session lifetime; no persistent background browser. |
| `web_retrieval.obscura.cdp.max_pages_per_session` | int | `8` | No | positive int | TOML/env | Page inspection limit per session. |
| `web_retrieval.obscura.cdp.max_dom_text_chars` | int | `60000` | No | positive int | TOML | DOM text output cap. |
| `web_retrieval.obscura.cdp.max_html_chars` | int | `250000` | No | positive int | TOML | HTML excerpt cap. |
| `web_retrieval.obscura.cdp.max_links` | int | `500` | No | positive int | TOML | Link output cap. |
| `web_retrieval.obscura.cdp.allow_runtime_eval` | bool | `false` | No | bool | TOML | Runtime evaluation remains disabled; user-supplied JS is not exposed. |
| `web_retrieval.obscura.cdp.allow_input_domain` | bool | `false` | No | bool | TOML | CDP click/type/keyboard/mouse operations are not enabled. |
| `web_retrieval.obscura.cdp.allow_cookies` | bool | `false` | No | bool | TOML | Cookie/session access is disabled. |
| `web_retrieval.obscura.cdp.allow_logged_in_context` | bool | `false` | No | bool | TOML | Logged-in browser context is not supported. |
| `web_retrieval.obscura.cdp.allow_screenshots` | bool | `false` | No | bool | TOML | Screenshots are not a visible-screen truth source in this phase. |
| `web_retrieval.obscura.cdp.debug_events_enabled` | bool | `true` | No | bool | TOML | Emits bounded lifecycle/extraction events without raw DOM text or HTML. |
| `web_retrieval.chromium.enabled` | bool | `false` | No | bool | TOML | Chromium provider is a future placeholder. |
| `web_retrieval.chromium.fallback_enabled` | bool | `true` | No | bool | TOML | Future fallback flag; no Chromium implementation in this pass. |

Env overrides include `STORMHELM_WEB_RETRIEVAL_ENABLED`, `STORMHELM_WEB_RETRIEVAL_DEFAULT_PROVIDER`, `STORMHELM_WEB_RETRIEVAL_MAX_URL_COUNT`, `STORMHELM_WEB_RETRIEVAL_MAX_URL_CHARS`, `STORMHELM_WEB_RETRIEVAL_ALLOW_PRIVATE_NETWORK_URLS`, `STORMHELM_WEB_RETRIEVAL_HTTP_ENABLED`, `STORMHELM_OBSCURA_ENABLED`, `STORMHELM_OBSCURA_BINARY_PATH`, `STORMHELM_OBSCURA_MAX_CONCURRENCY`, `STORMHELM_OBSCURA_CDP_ENABLED`, `STORMHELM_OBSCURA_CDP_BINARY_PATH`, `STORMHELM_OBSCURA_CDP_HOST`, `STORMHELM_OBSCURA_CDP_PORT`, and `STORMHELM_OBSCURA_CDP_MAX_PAGES_PER_SESSION`.

Run `python -m stormhelm.core.web_retrieval.obscura_cdp_probe`, `scripts/smoke_obscura_cdp.ps1`, or the consolidated `scripts/run_live_browser_checks.ps1` for opt-in compatibility reports. Compatibility levels are `ready` when version/page websocket/navigation behavior is usable, `partial` when page inspection can proceed with missing nonessential endpoint details, `diagnostic_only` when endpoints are discovered but navigation/page inspection is unsupported, `unsupported` when required endpoint data is absent or mismatched, and `failed` when binary/startup/probe execution fails. A live smoke can report `cdp_navigation_unsupported` if endpoint discovery succeeds but the installed Obscura release rejects `Page.navigate`; Stormhelm then keeps CDP out of normal extraction selection and recommends Obscura CLI. These probes are manual, localhost-only, bounded, and not part of normal CI.

Sources: `config/default.toml`, `config/development-live-browser.toml.example`, `src/stormhelm/config/models.py`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/web_retrieval/service.py`, `src/stormhelm/core/live_browser_integration.py`
Tests: `tests/test_web_retrieval_config.py`, `tests/test_web_retrieval_safety.py`, `tests/test_web_retrieval_service.py`, `tests/test_live_browser_integration.py`

## Software Control And Recovery

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `software_control.enabled` | bool | `true` | No | bool | TOML/env | Disables subsystem if false. |
| `software_control.planner_routing_enabled` | bool | `true` | No | bool | TOML/env | Allows planner routing. |
| `software_control.debug_events_enabled` | bool | `true` | No | bool | TOML/env | Enables debug status/events. |
| `software_control.package_manager_routes_enabled` | bool | `true` | No | bool | TOML/env | Allows winget/chocolatey route planning. |
| `software_control.vendor_installer_routes_enabled` | bool | `true` | No | bool | TOML/env | Allows vendor installer route planning. |
| `software_control.browser_guided_routes_enabled` | bool | `true` | No | bool | TOML/env | Allows browser-guided acquisition planning. |
| `software_control.privileged_operations_allowed` | bool | `false` | No | bool | TOML/env | Blocks elevated software routes by default. |
| `software_control.trusted_sources_only` | bool | `true` | No | bool | TOML/env | Filters unverified sources. |
| `software_recovery.enabled` | bool | `true` | No | bool | TOML/env | Enables recovery subsystem. |
| `software_recovery.local_troubleshooting_enabled` | bool | `true` | No | bool | TOML/env | Enables local recovery hypotheses. |
| `software_recovery.max_retry_attempts` | int | `2` | No | nonnegative int | TOML/env | Bounded retry planning. |
| `software_recovery.max_recovery_steps` | int | `4` | No | positive int | TOML/env | Caps returned steps. |
| `software_recovery.cloud_fallback_enabled` | bool | `false` | No | bool | TOML/env | Cloud advisory disabled by default. |
| `software_recovery.cloud_fallback_model` | string | `gpt-5.4-nano` | No | provider model | TOML/env | Used only if cloud fallback and OpenAI enabled. |
| `software_recovery.redaction_enabled` | bool | `true` | No | bool | TOML/env | Redacts diagnostic context before cloud fallback. |

Sources: `config/default.toml`, `src/stormhelm/core/software_control/service.py`, `src/stormhelm/core/software_recovery/service.py`, `src/stormhelm/core/safety/policy.py`
Tests: `tests/test_software_control.py`, `tests/test_software_recovery.py`, `tests/test_assistant_software_control.py`

## Trust

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `trust.enabled` | bool | `true` | No | bool | TOML | Disables trust service if false. |
| `trust.debug_events_enabled` | bool | `true` | No | bool | TOML | Debug event posture. |
| `trust.session_grant_ttl_seconds` | number | `14400.0` | No | seconds | TOML | Session grant expiry. |
| `trust.once_grant_ttl_seconds` | number | `900.0` | No | seconds | TOML | Once grant expiry. |
| `trust.pending_request_ttl_seconds` | number | `3600.0` | No | seconds | TOML | Pending approval expiry. |
| `trust.audit_recent_limit` | int | `24` | No | positive int | TOML | Recent audit snapshot limit. |

Sources: `config/default.toml`, `src/stormhelm/core/trust/service.py`, `src/stormhelm/core/trust/models.py`
Tests: `tests/test_trust_service.py`

## Discord Relay

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `discord_relay.enabled` | bool | `true` | No | bool | TOML/env | Disables relay if false. |
| `discord_relay.planner_routing_enabled` | bool | `true` | No | bool | TOML/env | Allows planner routing. |
| `discord_relay.debug_events_enabled` | bool | `true` | No | bool | TOML/env | Debug posture. |
| `discord_relay.screen_disambiguation_enabled` | bool | `true` | No | bool | TOML/env | Allows screen context as secondary disambiguation. |
| `discord_relay.preview_before_send` | bool | `true` | No | bool | TOML/env | Preview required by current truth contract. |
| `discord_relay.verification_enabled` | bool | `true` | No | bool | TOML/env | Enables limited verification metadata. |
| `discord_relay.local_dm_route_enabled` | bool | `true` | No | bool | TOML/env | Enables local client DM route. |
| `discord_relay.bot_webhook_routes_enabled` | bool | `false` | No | bool | TOML/env | Official bot/webhook route disabled by default. |
| `discord_relay.trusted_aliases.<name>.alias` | string | `Baby` for `baby` | No | string | TOML | Alias resolution. |
| `discord_relay.trusted_aliases.<name>.route_mode` | string | `local_client_automation` | No | enum string | TOML | Route mode. |
| `discord_relay.trusted_aliases.<name>.trusted` | bool | `true` | No | bool | TOML | Trusted alias flag. |

Sources: `config/default.toml`, `src/stormhelm/config/models.py`, `src/stormhelm/core/discord_relay/service.py`
Tests: `tests/test_discord_relay.py`

## OpenAI

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `openai.enabled` | bool | `false` | No | bool | TOML/env | Provider is not built unless enabled and usable. |
| `OPENAI_API_KEY` | secret string | empty | Required only when enabled | API key | `.env`/env | Missing key prevents provider-backed behavior. |
| `STORMHELM_OPENAI_API_KEY` | secret string | empty | Alternative key env | API key | `.env`/env | Used if `OPENAI_API_KEY` not set. |
| `openai.base_url` | string | `https://api.openai.com/v1` | No | URL | TOML/env | Used by Responses provider. |
| `openai.model` | string | `gpt-5.4-nano` | No | model name | TOML/env | Default response model. |
| `openai.planner_model` | string | `gpt-5.4-nano` | No | model name | TOML/env | Planner/provider model setting. |
| `openai.reasoning_model` | string | `gpt-5.4` | No | model name | TOML/env | Reasoning model setting. |
| `openai.timeout_seconds` | number | `60` | No | seconds | TOML/env | HTTP timeout. |
| `openai.max_tool_rounds` | int | `4` | No | positive int | TOML/env | Provider tool-call loop cap. |
| `openai.max_output_tokens` | int | `1200` | No | positive int | TOML/env | Output cap. |
| `openai.planner_max_output_tokens` | int | `900` | No | positive int | TOML/env | Planner output cap. |
| `openai.reasoning_max_output_tokens` | int | `1400` | No | positive int | TOML/env | Reasoning output cap. |
| `openai.instructions` | string | multiline default | No | text | TOML | System instructions for provider. |

Env overrides are `STORMHELM_OPENAI_*` keys plus `OPENAI_API_KEY`. Do not commit real keys to `.env`, `.env.example`, or docs.

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/providers/openai_responses.py`, `src/stormhelm/core/providers/audit.py`
Tests: `tests/test_config_loader.py`, `tests/test_command_eval_provider_audit.py`

## Voice

Voice is disabled by default. Enabling voice does not enable wake word, always-listening, Realtime, or independent command execution. It only enables the bounded voice surfaces implemented by `VoiceService` when the provider and feature gates allow them.

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `voice.enabled` | bool | `false` | No | bool | TOML/env | Voice status remains unavailable if false. |
| `voice.provider` | string | `openai` | No | `openai`, mock/test provider names in code | TOML/env | Availability fails if unsupported for the selected path. |
| `voice.mode` | string | `disabled` | No | `disabled`, `manual_only`, `output_only`, `push_to_talk`, `wake_supervised`, `realtime_transcription`, `realtime_speech_core_bridge` | TOML/env | Runtime mode readiness reports blocked/degraded states when required subcomponents do not match the mode. |
| `voice.wake_word_enabled` | bool | `false` | No | bool | TOML/env | Legacy truth flag; Voice-11 uses `[voice.wake]` for the provider boundary. |
| `voice.spoken_responses_enabled` | bool | `false` | No | bool | TOML/env | Allows spoken-response/TTS posture when provider gates pass. |
| `voice.manual_input_enabled` | bool | `true` | No | bool | TOML/env | Enables manual transcript voice-turn path. |
| `voice.realtime_enabled` | bool | `false` | No | bool | TOML/env | Legacy truth flag; concrete Realtime behavior is controlled by `[voice.realtime]`. |
| `voice.debug_mock_provider` | bool | `true` | No | bool | TOML/env | Allows deterministic mock-provider behavior for tests/dev diagnostics. |

Env overrides: `STORMHELM_VOICE_ENABLED`, `STORMHELM_VOICE_PROVIDER`, `STORMHELM_VOICE_MODE`, `STORMHELM_VOICE_WAKE_WORD_ENABLED`, `STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED`, `STORMHELM_VOICE_MANUAL_INPUT_ENABLED`, `STORMHELM_VOICE_REALTIME_ENABLED`, `STORMHELM_VOICE_DEBUG_MOCK_PROVIDER`.

Runtime mode readiness is derived by `VoiceService` and exposed in `voice.runtime_mode` status/UI payloads. It distinguishes configured, enabled, available, active, mocked, unavailable, blocked-by-config, and blocked-by-provider states for TTS, playback, capture, wake, VAD, Realtime, Core bridge, and trust/confirmation.

Common mode blockers:

| Mode | Blocking state | Direct fix |
|---|---|---|
| `output_only` | `output_voice_configured_but_playback_disabled` | Enable `voice.playback.enabled`. |
| `output_only` | `output_voice_configured_but_playback_unavailable` | Fix local playback provider/device availability. |
| `output_only` | `output_voice_configured_but_tts_unavailable` | Enable OpenAI/TTS config and API key. |
| `push_to_talk` | `push_to_talk_capture_disabled` or `push_to_talk_capture_unavailable` | Enable/fix `[voice.capture]`. |
| `wake_supervised` | wake/post-wake/capture/STT/Core bridge unavailable | Enable the missing local wake/listen/capture/STT/Core seam. |
| `realtime_speech_core_bridge` | `realtime_direct_tools_forbidden` | Keep `voice.realtime.direct_tools_allowed=false`; direct tools are never a valid fix. |

`voice.openai.persist_tts_outputs=true` is artifact/debug behavior. It does not count as live playback for `output_only`.

Sources: `config/default.toml`, `src/stormhelm/config/models.py`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/availability.py`
Tests: `tests/test_voice_config.py`, `tests/test_voice_availability.py`, `tests/test_voice_runtime_modes.py`

## Voice OpenAI

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `voice.openai.stt_model` | string | `gpt-4o-mini-transcribe` | Required for OpenAI STT | model id | TOML/env | Availability/diagnostics can report missing model. |
| `voice.openai.transcription_language` | string | empty | No | language hint | TOML/env | Empty sends no explicit language hint. |
| `voice.openai.transcription_prompt` | string | empty | No | prompt text | TOML/env | Empty sends no transcription prompt. |
| `voice.openai.timeout_seconds` | number | `60` | No | seconds | TOML/env | Bounds OpenAI voice calls. |
| `voice.openai.max_audio_seconds` | number | `30` | No | seconds | TOML/env | Controlled audio above the limit is rejected. |
| `voice.openai.max_audio_bytes` | int | `26214400` | No | positive bytes | TOML/env | Controlled audio above the limit is rejected. |
| `voice.openai.tts_model` | string | `gpt-4o-mini-tts` | Required for OpenAI TTS | model id | TOML/env | TTS diagnostics can report missing model. |
| `voice.openai.tts_voice` | string | `onyx` | No | provider-supported voice | TOML/env | Unsupported voices return provider errors. |
| `voice.openai.tts_format` | string | `mp3` | No | provider-supported format | TOML/env | Used for generated speech artifacts. |
| `voice.openai.tts_speed` | number | `1.0` | No | provider-supported range | TOML/env | Used for speech synthesis requests. |
| `voice.openai.max_tts_chars` | int | `600` | No | positive int | TOML/env | Long spoken text is blocked. |
| `voice.openai.output_audio_dir` | path/string | empty | No | path | TOML/env | Empty means transient/default output handling. |
| `voice.openai.persist_tts_outputs` | bool | `false` | No | bool | TOML/env | Generated audio is not retained by default; persisted artifacts do not count as live playback. |
| `voice.openai.realtime_model` | string | `gpt-realtime` | No | model id | TOML/env | Stored for future Realtime; not a live Realtime claim. |
| `voice.openai.vad_mode` | string | `server_vad` | No | provider mode label | TOML/env | Stored for future VAD; VAD is not implemented. |

Env overrides use the `STORMHELM_VOICE_OPENAI_*` prefix shown in `src/stormhelm/config/loader.py`.

Sources: `config/default.toml`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`
Tests: `tests/test_voice_config.py`, `tests/test_voice_stt_provider.py`, `tests/test_voice_tts_provider.py`, `tests/test_voice_audio_turn.py`

## Voice Wake Foundation

Voice wake settings define the disabled-by-default wake foundation and Voice-11 local provider boundary. Local wake must be explicitly enabled, dev-gated, and backed by an available local backend. Dormant wake audio is not sent to OpenAI or cloud services.

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `voice.wake.enabled` | bool | `false` | No | bool | TOML/env | Wake readiness reports disabled if false. |
| `voice.wake.provider` | string | `mock` | No | `mock`, `local`, unavailable/stub labels | TOML/env | Local provider remains unavailable unless the explicit gates and backend pass. |
| `voice.wake.wake_phrase` | string | `Stormhelm` | No | non-empty phrase | TOML/env | Empty values normalize to `Stormhelm`. |
| `voice.wake.device` | string | `default` | No | device label | TOML/env | Passed to local wake backend when available. |
| `voice.wake.sample_rate` | int | `16000` | No | positive int | TOML/env | Passed to local wake backend. |
| `voice.wake.backend` | string | `unavailable` | No | backend label | TOML/env | Names the optional local backend; missing dependencies report unavailable. |
| `voice.wake.model_path` | string | empty | No | local path or empty | TOML/env | Optional local wake model path for future/optional backends. |
| `voice.wake.sensitivity` | number | `0.5` | No | `0.0` to `1.0` | TOML/env | Backend hint only; values outside range are clamped. |
| `voice.wake.confidence_threshold` | number | `0.75` | No | `0.0` to `1.0` | TOML/env | Values outside range are clamped. |
| `voice.wake.cooldown_ms` | int | `2500` | No | non-negative milliseconds | TOML/env | Repeated mock wake events inside cooldown are rejected. |
| `voice.wake.max_wake_session_ms` | int | `15000` | No | positive milliseconds | TOML/env | Bounds the temporary wake session. |
| `voice.wake.false_positive_window_ms` | int | `3000` | No | non-negative milliseconds | TOML/env | Stored for false-positive diagnostics and future phases. |
| `voice.wake.allow_dev_wake` | bool | `false` | No | bool | TOML/env | Mock wake simulation is blocked unless explicitly allowed. |

Env overrides use `STORMHELM_VOICE_WAKE_*`.

Sources: `config/default.toml`, `src/stormhelm/config/models.py`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`
Tests: `tests/test_voice_wake_config.py`, `tests/test_voice_wake_service.py`, `tests/test_voice_local_wake_provider.py`

## Voice Capture And Playback

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `voice.capture.enabled` | bool | `false` | No | bool | TOML/env | Push-to-talk capture is blocked if false. |
| `voice.capture.provider` | string | `local` | No | implemented provider label | TOML/env | Local capture still requires dev gate/dependencies. |
| `voice.capture.mode` | string | `push_to_talk` | No | implemented mode label | TOML/env | Current surface is explicit capture, not continuous listening. |
| `voice.capture.device` | string | `default` | No | device label | TOML/env | Passed to local capture backend when available. |
| `voice.capture.sample_rate` | int | `16000` | No | positive int | TOML/env | Used by local capture backend. |
| `voice.capture.channels` | int | `1` | No | positive int | TOML/env | Used by local capture backend. |
| `voice.capture.format` | string | `wav` | No | supported format | TOML/env | Current local capture writes WAV metadata. |
| `voice.capture.max_duration_ms` | int | `30000` | No | positive milliseconds | TOML/env | Bounds capture duration. |
| `voice.capture.max_audio_bytes` | int | `10000000` | No | positive bytes | TOML/env | Bounds captured audio. |
| `voice.capture.auto_stop_on_max_duration` | bool | `true` | No | bool | TOML/env | Enables duration guard. |
| `voice.capture.persist_captured_audio` | bool | `false` | No | bool | TOML/env | Captured audio is not retained by default. |
| `voice.capture.delete_transient_after_turn` | bool | `true` | No | bool | TOML/env | Transient captured audio may be deleted after a turn. |
| `voice.capture.allow_dev_capture` | bool | `false` | No | bool | TOML/env | Local capture remains blocked unless explicitly allowed. |
| `voice.playback.enabled` | bool | `false` | No | bool | TOML/env | Playback is blocked if false. |
| `voice.playback.provider` | string | `local` | No | implemented provider label | TOML/env | Local playback is a provider boundary, not a heard-audio guarantee. |
| `voice.playback.device` | string | `default` | No | device label | TOML/env | Passed to playback backend where supported. |
| `voice.playback.volume` | number | `1.0` | No | provider-supported range | TOML/env | Used by playback requests. |
| `voice.playback.allow_dev_playback` | bool | `false` | No | bool | TOML/env | Local playback remains blocked unless explicitly allowed. |
| `voice.playback.max_audio_bytes` | int | `10000000` | No | positive bytes | TOML/env | Blocks oversized playback artifacts. |
| `voice.playback.max_duration_ms` | int | `120000` | No | positive milliseconds | TOML/env | Bounds playback request duration. |
| `voice.playback.delete_transient_after_playback` | bool | `true` | No | bool | TOML/env | Transient generated audio may be deleted after playback. |

Env overrides use `STORMHELM_VOICE_CAPTURE_*` and `STORMHELM_VOICE_PLAYBACK_*`.

Sources: `config/default.toml`, `src/stormhelm/config/models.py`, `src/stormhelm/config/loader.py`, `src/stormhelm/core/voice/providers.py`, `src/stormhelm/core/voice/service.py`
Tests: `tests/test_voice_config.py`, `tests/test_voice_capture_service.py`, `tests/test_voice_playback_service.py`, `tests/test_voice_capture_provider.py`, `tests/test_voice_playback_provider.py`

## Safety

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `safety.allowed_read_dirs` | list[path] | project root, `~/Documents` | No | paths | TOML | File reads outside these dirs are blocked. |
| `safety.allow_shell_stub` | bool | `false` | No | bool | TOML | Shell stub blocked by default. |
| `safety.unsafe_test_mode` | bool | `false` | No | bool | TOML/env | If true, widens read/action/software gates for tests. |

Env override: `STORMHELM_UNSAFE_TEST_MODE`.

Sources: `config/default.toml`, `src/stormhelm/core/safety/policy.py`, `src/stormhelm/config/loader.py`
Tests: `tests/test_safety.py`, `tests/test_config_loader.py`

## Tool Enablement

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `tools.max_file_read_bytes` | int | `32768` | No | positive int | TOML | File reader byte limit. |
| `tools.enabled.clock` | bool | `true` | No | bool | TOML/model | Enables `clock`. |
| `tools.enabled.system_info` | bool | `true` | No | bool | TOML/model | Enables `system_info`. |
| `tools.enabled.file_reader` | bool | `true` | No | bool | TOML/model | Enables allowlisted file reads. |
| `tools.enabled.notes_write` | bool | `true` | No | bool | TOML/model | Enables note writes. |
| `tools.enabled.echo` | bool | `true` | No | bool | TOML/model | Enables echo. |
| `tools.enabled.browser_context` | bool | `true` | No | bool | model default | Enables browser context tool. |
| `tools.enabled.activity_summary` | bool | `true` | No | bool | model default | Enables activity summary tool. |
| `tools.enabled.web_retrieval_fetch` | bool | `true` | No | bool | TOML/model | Enables public webpage evidence extraction tool. |
| `tools.enabled.shell_command` | bool | `false` | No | bool | TOML/model | Tool disabled by default. |
| `tools.enabled.deck_open_url` / `external_open_url` | bool | `true` | No | bool | TOML/model | Internal/external URL actions. |
| `tools.enabled.deck_open_file` / `external_open_file` | bool | `true` | No | bool | TOML/model | Internal/external file actions. |
| `tools.enabled.machine_status` | bool | `true` | No | bool | TOML/model | Machine status. |
| `tools.enabled.power_status`, `power_projection`, `power_diagnosis` | bool | `true` | No | bool | TOML/model | Power tools. |
| `tools.enabled.resource_status`, `resource_diagnosis` | bool | `true` | No | bool | TOML/model | Resource tools. |
| `tools.enabled.storage_status`, `storage_diagnosis` | bool | `true` | No | bool | TOML/model | Storage tools. |
| `tools.enabled.network_status`, `network_throughput`, `network_diagnosis` | bool | `true` | No | bool | TOML/model | Network tools. |
| `tools.enabled.active_apps`, `app_control`, `window_status`, `window_control`, `system_control`, `control_capabilities` | bool | `true` | No | bool | TOML/model | Native control/status tools. |
| `tools.enabled.desktop_search` | bool | `true` | No | bool | model default | Desktop search tool. |
| `tools.enabled.workflow_execute`, `repair_action`, `routine_execute`, `routine_save` | bool | `true` | No | bool | model default | Workflow/routine tools. |
| `tools.enabled.trusted_hook_register`, `trusted_hook_execute` | bool | `true` | No | bool | model default | Trusted hook tools. |
| `tools.enabled.file_operation`, `maintenance_action`, `context_action` | bool | `true` | No | bool | model default | Action tools, often trust-gated. |
| `tools.enabled.recent_files` | bool | `true` | No | bool | TOML/model | Recent files. |
| `tools.enabled.location_status`, `saved_locations`, `save_location`, `weather_current` | bool | `true` | No | bool | TOML/model | Location/weather tools. |
| `tools.enabled.workspace_*` | bool | `true` | No | bool | TOML/model | Workspace restore/assemble/save/clear/archive/rename/tag/list/continuity. |

Sources: `config/default.toml`, `src/stormhelm/config/models.py`, `src/stormhelm/core/tools/builtins/__init__.py`, `src/stormhelm/core/safety/policy.py`
Tests: `tests/test_tool_registry.py`, `tests/test_safety.py`
