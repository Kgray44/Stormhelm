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

Sources: `src/stormhelm/config/loader.py`, `config/default.toml`, `config/development.toml.example`  
Tests: `tests/test_config_loader.py`

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

Sources: `config/default.toml`, `src/stormhelm/config/models.py`, `src/stormhelm/core/screen_awareness/service.py`  
Tests: `tests/test_screen_awareness_service.py`, `tests/test_screen_awareness_action.py`, `tests/test_screen_awareness_verification.py`

## Calculations

| Key | Type | Default | Required | Valid values | Read from | Behavior if missing/invalid |
|---|---|---|---|---|---|---|
| `calculations.enabled` | bool | `true` | No | bool | TOML/env | Disables subsystem if false. |
| `calculations.planner_routing_enabled` | bool | `true` | No | bool | TOML/env | Allows planner routing. |
| `calculations.debug_events_enabled` | bool | `true` | No | bool | TOML/env | Enables debug status/events. |

Env overrides: `STORMHELM_CALCULATIONS_ENABLED`, `STORMHELM_CALCULATIONS_PLANNER_ROUTING_ENABLED`, `STORMHELM_CALCULATIONS_DEBUG_EVENTS_ENABLED`.

Sources: `config/default.toml`, `src/stormhelm/core/calculations/service.py`  
Tests: `tests/test_calculations.py`

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
