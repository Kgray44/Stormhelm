from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Callable, Mapping

from stormhelm.config.models import (
    AppConfig,
    CalculationsConfig,
    ConcurrencyConfig,
    DiscordRelayConfig,
    DiscordTrustedAliasConfig,
    default_discord_trusted_aliases,
    EventStreamConfig,
    HardwareTelemetryConfig,
    LifecycleConfig,
    LocationConfig,
    LoggingConfig,
    NetworkConfig,
    OpenAIConfig,
    ScreenAwarenessConfig,
    SoftwareControlConfig,
    SoftwareRecoveryConfig,
    TrustConfig,
    WeatherConfig,
    RuntimePathConfig,
    SafetyConfig,
    StorageConfig,
    ToolConfig,
    ToolEnablementConfig,
    UIConfig,
    VoiceConfig,
    VoiceCaptureConfig,
    VoiceConfirmationConfig,
    VoiceOpenAIConfig,
    VoicePlaybackConfig,
    VoicePostWakeConfig,
    VoiceRealtimeConfig,
    VoiceVADConfig,
    VoiceWakeConfig,
)
from stormhelm.shared.paths import default_data_dir
from stormhelm.shared.runtime import RuntimeDiscovery, discover_runtime
from stormhelm.version import (
    API_PROTOCOL_VERSION,
    APP_NAME,
    __version__,
    current_release_channel,
)


ConfigDict = dict[str, Any]


def load_config(
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    project_root: Path | None = None,
) -> AppConfig:
    runtime = _resolve_runtime(project_root)
    root = _resolve_root(project_root, runtime)
    config_data = _read_toml(runtime.resource_root / "config" / "default.toml")

    for override_path in _initial_override_candidates(
        runtime=runtime,
        root=root,
        config_path=config_path,
    ):
        if override_path.exists():
            config_data = _deep_merge(config_data, _read_toml(override_path))

    env_values = dict(_parse_env_file(root / ".env"))
    env_values.update(os.environ)
    if env is not None:
        env_values.update(env)

    config_data = _apply_env_overrides(config_data, env_values)

    provisional_app_name = str(config_data.get("app_name", APP_NAME))
    provisional_data_dir = _resolve_data_dir(config_data, root, provisional_app_name)
    user_config_path = provisional_data_dir / "config" / "user.toml"
    if user_config_path.exists():
        config_data = _deep_merge(config_data, _read_toml(user_config_path))
        config_data = _apply_env_overrides(config_data, env_values)

    app_config = _build_app_config(config_data, root, runtime, env_values)
    if app_config.safety.unsafe_test_mode:
        _apply_unsafe_test_mode_overrides(app_config, root=root)
    return app_config


def _build_app_config(
    data: ConfigDict,
    root: Path,
    runtime: RuntimeDiscovery,
    env_values: Mapping[str, str],
) -> AppConfig:
    app_name = str(data.get("app_name", APP_NAME))
    environment = str(data.get("environment", "development"))
    debug = bool(data.get("debug", True))
    release_channel = (
        str(data.get("release_channel", current_release_channel())).strip()
        or current_release_channel()
    )

    network_data = data.get("network", {})
    host = str(network_data.get("host", "127.0.0.1"))
    port = int(network_data.get("port", 8765))

    data_dir = _resolve_data_dir(data, root, app_name)
    storage_data = data.get("storage", {})
    logs_dir = _expand_path(storage_data.get("logs_dir") or "", root, data_dir) or (
        data_dir / "logs"
    )
    database_path = _expand_path(
        storage_data.get("database_path") or "", root, data_dir
    ) or (data_dir / "stormhelm.db")
    state_dir = _expand_path(storage_data.get("state_dir") or "", root, data_dir) or (
        data_dir / "state"
    )
    cache_dir = _expand_path(storage_data.get("cache_dir") or "", root, data_dir) or (
        data_dir / "cache"
    )

    logging_data = data.get("logging", {})
    logging_config = LoggingConfig(
        level=str(logging_data.get("level", "DEBUG" if debug else "INFO")),
        file_name=str(logging_data.get("file_name", "stormhelm.log")),
        max_file_bytes=int(logging_data.get("max_file_bytes", 1_000_000)),
        backup_count=int(logging_data.get("backup_count", 3)),
    )

    concurrency_data = data.get("concurrency", {})
    concurrency_config = ConcurrencyConfig(
        max_workers=int(concurrency_data.get("max_workers", 8)),
        queue_size=int(concurrency_data.get("queue_size", 128)),
        default_job_timeout_seconds=float(
            concurrency_data.get("default_job_timeout_seconds", 20)
        ),
        history_limit=int(concurrency_data.get("history_limit", 500)),
    )

    ui_data = data.get("ui", {})
    ui_config = UIConfig(
        poll_interval_ms=int(ui_data.get("poll_interval_ms", 1500)),
        hide_to_tray_on_close=bool(ui_data.get("hide_to_tray_on_close", True)),
        ghost_shortcut=str(ui_data.get("ghost_shortcut", "Ctrl+Space")),
    )

    lifecycle_data = data.get("lifecycle", {})
    lifecycle_config = LifecycleConfig(
        startup_enabled=bool(lifecycle_data.get("startup_enabled", False)),
        start_core_with_windows=bool(
            lifecycle_data.get("start_core_with_windows", False)
        ),
        start_shell_with_windows=bool(
            lifecycle_data.get("start_shell_with_windows", False)
        ),
        tray_only_startup=bool(lifecycle_data.get("tray_only_startup", True)),
        ghost_ready_on_startup=bool(lifecycle_data.get("ghost_ready_on_startup", True)),
        background_core_resident=bool(
            lifecycle_data.get("background_core_resident", True)
        ),
        auto_restart_core=bool(lifecycle_data.get("auto_restart_core", True)),
        max_core_restart_attempts=int(
            lifecycle_data.get("max_core_restart_attempts", 2)
        ),
        restart_failure_window_seconds=float(
            lifecycle_data.get("restart_failure_window_seconds", 300.0)
        ),
        shell_heartbeat_interval_seconds=float(
            lifecycle_data.get("shell_heartbeat_interval_seconds", 15.0)
        ),
        shell_stale_after_seconds=float(
            lifecycle_data.get("shell_stale_after_seconds", 45.0)
        ),
        core_restart_backoff_ms=int(lifecycle_data.get("core_restart_backoff_ms", 750)),
    )

    event_stream_data = data.get("event_stream", {})
    event_stream_config = EventStreamConfig(
        enabled=bool(event_stream_data.get("enabled", True)),
        retention_capacity=int(event_stream_data.get("retention_capacity", 500)),
        replay_limit=int(event_stream_data.get("replay_limit", 128)),
        heartbeat_seconds=float(event_stream_data.get("heartbeat_seconds", 15.0)),
    )

    location_data = data.get("location", {})
    location_config = LocationConfig(
        allow_approximate_lookup=bool(
            location_data.get("allow_approximate_lookup", True)
        ),
        lookup_timeout_seconds=float(location_data.get("lookup_timeout_seconds", 5)),
        home_label=str(location_data.get("home_label", "")).strip() or None,
        home_city=str(location_data.get("home_city", "")).strip() or None,
        home_region=str(location_data.get("home_region", "")).strip() or None,
        home_country=str(location_data.get("home_country", "")).strip() or None,
        home_latitude=_parse_optional_float(location_data.get("home_latitude")),
        home_longitude=_parse_optional_float(location_data.get("home_longitude")),
        home_timezone=str(location_data.get("home_timezone", "")).strip() or None,
    )

    weather_data = data.get("weather", {})
    weather_config = WeatherConfig(
        enabled=bool(weather_data.get("enabled", True)),
        units=str(weather_data.get("units", "imperial")).strip() or "imperial",
        provider_base_url=str(
            weather_data.get("provider_base_url", "https://api.open-meteo.com/v1")
        ).rstrip("/"),
        timeout_seconds=float(weather_data.get("timeout_seconds", 6)),
    )

    hardware_telemetry_data = data.get("hardware_telemetry", {})
    hardware_telemetry_config = HardwareTelemetryConfig(
        enabled=bool(hardware_telemetry_data.get("enabled", True)),
        helper_timeout_seconds=float(
            hardware_telemetry_data.get("helper_timeout_seconds", 12.0)
        ),
        provider_timeout_seconds=float(
            hardware_telemetry_data.get("provider_timeout_seconds", 5.0)
        ),
        idle_cache_ttl_seconds=float(
            hardware_telemetry_data.get("idle_cache_ttl_seconds", 30)
        ),
        active_cache_ttl_seconds=float(
            hardware_telemetry_data.get("active_cache_ttl_seconds", 8)
        ),
        burst_cache_ttl_seconds=float(
            hardware_telemetry_data.get("burst_cache_ttl_seconds", 2)
        ),
        elevated_helper_enabled=bool(
            hardware_telemetry_data.get("elevated_helper_enabled", False)
        ),
        elevated_helper_timeout_seconds=float(
            hardware_telemetry_data.get("elevated_helper_timeout_seconds", 20.0)
        ),
        elevated_helper_cooldown_seconds=float(
            hardware_telemetry_data.get("elevated_helper_cooldown_seconds", 120.0)
        ),
        hwinfo_enabled=bool(hardware_telemetry_data.get("hwinfo_enabled", True)),
        hwinfo_executable_path=str(
            hardware_telemetry_data.get("hwinfo_executable_path", "")
        ).strip()
        or None,
    )

    screen_awareness_data = data.get("screen_awareness", {})
    screen_awareness_config = ScreenAwarenessConfig(
        enabled=bool(screen_awareness_data.get("enabled", True)),
        phase=str(screen_awareness_data.get("phase", "phase12")).strip() or "phase12",
        planner_routing_enabled=bool(
            screen_awareness_data.get("planner_routing_enabled", True)
        ),
        debug_events_enabled=bool(
            screen_awareness_data.get("debug_events_enabled", True)
        ),
        observation_enabled=bool(
            screen_awareness_data.get("observation_enabled", True)
        ),
        interpretation_enabled=bool(
            screen_awareness_data.get("interpretation_enabled", True)
        ),
        grounding_enabled=bool(screen_awareness_data.get("grounding_enabled", True)),
        guidance_enabled=bool(screen_awareness_data.get("guidance_enabled", True)),
        action_enabled=bool(screen_awareness_data.get("action_enabled", True)),
        action_policy_mode=str(
            screen_awareness_data.get("action_policy_mode", "confirm_before_act")
        ).strip()
        or "confirm_before_act",
        verification_enabled=bool(
            screen_awareness_data.get("verification_enabled", True)
        ),
        memory_enabled=bool(screen_awareness_data.get("memory_enabled", True)),
        adapters_enabled=bool(screen_awareness_data.get("adapters_enabled", True)),
        problem_solving_enabled=bool(
            screen_awareness_data.get("problem_solving_enabled", True)
        ),
        workflow_learning_enabled=bool(
            screen_awareness_data.get("workflow_learning_enabled", True)
        ),
        brain_integration_enabled=bool(
            screen_awareness_data.get("brain_integration_enabled", True)
        ),
        power_features_enabled=bool(
            screen_awareness_data.get("power_features_enabled", True)
        ),
    )

    calculations_data = data.get("calculations", {})
    calculations_config = CalculationsConfig(
        enabled=bool(calculations_data.get("enabled", True)),
        planner_routing_enabled=bool(
            calculations_data.get("planner_routing_enabled", True)
        ),
        debug_events_enabled=bool(calculations_data.get("debug_events_enabled", True)),
    )

    software_control_data = data.get("software_control", {})
    software_control_config = SoftwareControlConfig(
        enabled=bool(software_control_data.get("enabled", True)),
        planner_routing_enabled=bool(
            software_control_data.get("planner_routing_enabled", True)
        ),
        debug_events_enabled=bool(
            software_control_data.get("debug_events_enabled", True)
        ),
        package_manager_routes_enabled=bool(
            software_control_data.get("package_manager_routes_enabled", True)
        ),
        vendor_installer_routes_enabled=bool(
            software_control_data.get("vendor_installer_routes_enabled", True)
        ),
        browser_guided_routes_enabled=bool(
            software_control_data.get("browser_guided_routes_enabled", True)
        ),
        privileged_operations_allowed=bool(
            software_control_data.get("privileged_operations_allowed", False)
        ),
        trusted_sources_only=bool(
            software_control_data.get("trusted_sources_only", True)
        ),
        unsafe_test_mode=bool(software_control_data.get("unsafe_test_mode", False)),
    )

    software_recovery_data = data.get("software_recovery", {})
    software_recovery_config = SoftwareRecoveryConfig(
        enabled=bool(software_recovery_data.get("enabled", True)),
        debug_events_enabled=bool(
            software_recovery_data.get("debug_events_enabled", True)
        ),
        local_troubleshooting_enabled=bool(
            software_recovery_data.get("local_troubleshooting_enabled", True)
        ),
        max_retry_attempts=int(software_recovery_data.get("max_retry_attempts", 2)),
        max_recovery_steps=int(software_recovery_data.get("max_recovery_steps", 4)),
        cloud_fallback_enabled=bool(
            software_recovery_data.get("cloud_fallback_enabled", False)
        ),
        cloud_fallback_model=(
            str(
                software_recovery_data.get("cloud_fallback_model", "gpt-5.4-nano")
            ).strip()
            or "gpt-5.4-nano"
        ),
        redaction_enabled=bool(software_recovery_data.get("redaction_enabled", True)),
    )

    trust_data = data.get("trust", {})
    trust_config = TrustConfig(
        enabled=bool(trust_data.get("enabled", True)),
        debug_events_enabled=bool(trust_data.get("debug_events_enabled", True)),
        session_grant_ttl_seconds=float(
            trust_data.get("session_grant_ttl_seconds", 14400.0)
        ),
        once_grant_ttl_seconds=float(trust_data.get("once_grant_ttl_seconds", 900.0)),
        pending_request_ttl_seconds=float(
            trust_data.get("pending_request_ttl_seconds", 3600.0)
        ),
        audit_recent_limit=int(trust_data.get("audit_recent_limit", 24)),
    )

    discord_relay_data = data.get("discord_relay", {})
    trusted_aliases_data = (
        discord_relay_data.get("trusted_aliases")
        if isinstance(discord_relay_data.get("trusted_aliases"), dict)
        else {}
    )
    trusted_aliases: dict[str, DiscordTrustedAliasConfig] = (
        default_discord_trusted_aliases()
    )
    for alias_key, alias_payload in trusted_aliases_data.items():
        if not isinstance(alias_payload, dict):
            continue
        normalized_alias = str(alias_payload.get("alias") or alias_key).strip()
        if not normalized_alias:
            continue
        trusted_aliases[normalized_alias.lower()] = DiscordTrustedAliasConfig(
            alias=normalized_alias,
            label=str(
                alias_payload.get("label")
                or alias_payload.get("display_name")
                or normalized_alias
            ).strip()
            or normalized_alias,
            destination_kind=str(
                alias_payload.get("destination_kind", "personal_dm")
            ).strip()
            or "personal_dm",
            route_mode=str(
                alias_payload.get("route_mode", "local_client_automation")
            ).strip()
            or "local_client_automation",
            navigation_mode=str(
                alias_payload.get("navigation_mode", "quick_switch")
            ).strip()
            or "quick_switch",
            search_query=str(alias_payload.get("search_query", "")).strip() or None,
            thread_uri=str(alias_payload.get("thread_uri", "")).strip() or None,
            trusted=bool(alias_payload.get("trusted", True)),
            confirmation_policy=str(
                alias_payload.get("confirmation_policy", "preview_required")
            ).strip()
            or "preview_required",
            attachment_policy=str(
                alias_payload.get("attachment_policy", "allow")
            ).strip()
            or "allow",
        )
    discord_relay_config = DiscordRelayConfig(
        enabled=bool(discord_relay_data.get("enabled", True)),
        planner_routing_enabled=bool(
            discord_relay_data.get("planner_routing_enabled", True)
        ),
        debug_events_enabled=bool(discord_relay_data.get("debug_events_enabled", True)),
        screen_disambiguation_enabled=bool(
            discord_relay_data.get("screen_disambiguation_enabled", True)
        ),
        preview_before_send=bool(discord_relay_data.get("preview_before_send", True)),
        verification_enabled=bool(discord_relay_data.get("verification_enabled", True)),
        local_dm_route_enabled=bool(
            discord_relay_data.get("local_dm_route_enabled", True)
        ),
        bot_webhook_routes_enabled=bool(
            discord_relay_data.get("bot_webhook_routes_enabled", False)
        ),
        trusted_aliases=trusted_aliases,
    )

    openai_data = data.get("openai", {})
    openai_config = OpenAIConfig(
        enabled=bool(openai_data.get("enabled", False)),
        api_key=(
            str(
                env_values.get("OPENAI_API_KEY")
                or env_values.get("STORMHELM_OPENAI_API_KEY")
                or ""
            ).strip()
            or str(openai_data.get("api_key", "")).strip()
            or None
        ),
        base_url=str(openai_data.get("base_url", "https://api.openai.com/v1")).rstrip(
            "/"
        ),
        model=str(openai_data.get("model", "gpt-5.4-nano")).strip() or "gpt-5.4-nano",
        planner_model=str(
            openai_data.get("planner_model", openai_data.get("model", "gpt-5.4-nano"))
        ).strip()
        or "gpt-5.4-nano",
        reasoning_model=str(openai_data.get("reasoning_model", "gpt-5.4")).strip()
        or "gpt-5.4",
        timeout_seconds=float(openai_data.get("timeout_seconds", 60)),
        max_tool_rounds=int(openai_data.get("max_tool_rounds", 4)),
        max_output_tokens=int(openai_data.get("max_output_tokens", 1200)),
        planner_max_output_tokens=int(
            openai_data.get(
                "planner_max_output_tokens", openai_data.get("max_output_tokens", 900)
            )
        ),
        reasoning_max_output_tokens=int(
            openai_data.get(
                "reasoning_max_output_tokens",
                openai_data.get("max_output_tokens", 1400),
            )
        ),
        instructions=str(openai_data.get("instructions", "")).strip(),
    )

    voice_data = data.get("voice", {})
    voice_openai_data = (
        voice_data.get("openai", {})
        if isinstance(voice_data.get("openai"), dict)
        else {}
    )
    voice_playback_data = (
        voice_data.get("playback", {})
        if isinstance(voice_data.get("playback"), dict)
        else {}
    )
    voice_capture_data = (
        voice_data.get("capture", {})
        if isinstance(voice_data.get("capture"), dict)
        else {}
    )
    voice_wake_data = (
        voice_data.get("wake", {}) if isinstance(voice_data.get("wake"), dict) else {}
    )
    voice_post_wake_data = (
        voice_data.get("post_wake", {})
        if isinstance(voice_data.get("post_wake"), dict)
        else {}
    )
    voice_vad_data = (
        voice_data.get("vad", {}) if isinstance(voice_data.get("vad"), dict) else {}
    )
    voice_realtime_data = (
        voice_data.get("realtime", {})
        if isinstance(voice_data.get("realtime"), dict)
        else {}
    )
    voice_confirmation_data = (
        voice_data.get("confirmation", {})
        if isinstance(voice_data.get("confirmation"), dict)
        else {}
    )
    voice_config = VoiceConfig(
        enabled=bool(voice_data.get("enabled", False)),
        provider=str(voice_data.get("provider", "openai")).strip().lower() or "openai",
        mode=str(voice_data.get("mode", "disabled")).strip().lower() or "disabled",
        wake_word_enabled=bool(voice_data.get("wake_word_enabled", False)),
        spoken_responses_enabled=bool(
            voice_data.get("spoken_responses_enabled", False)
        ),
        manual_input_enabled=bool(voice_data.get("manual_input_enabled", True)),
        realtime_enabled=bool(voice_data.get("realtime_enabled", False)),
        debug_mock_provider=bool(voice_data.get("debug_mock_provider", True)),
        openai=VoiceOpenAIConfig(
            stt_model=str(
                voice_openai_data.get("stt_model", "gpt-4o-mini-transcribe")
            ).strip()
            or "gpt-4o-mini-transcribe",
            transcription_language=str(
                voice_openai_data.get("transcription_language", "")
            ).strip()
            or None,
            transcription_prompt=str(
                voice_openai_data.get("transcription_prompt", "")
            ).strip()
            or None,
            timeout_seconds=float(voice_openai_data.get("timeout_seconds", 60)),
            max_audio_seconds=float(voice_openai_data.get("max_audio_seconds", 30)),
            max_audio_bytes=int(
                voice_openai_data.get("max_audio_bytes", 25 * 1024 * 1024)
            ),
            tts_model=str(voice_openai_data.get("tts_model", "gpt-4o-mini-tts")).strip()
            or "gpt-4o-mini-tts",
            tts_voice=str(voice_openai_data.get("tts_voice", "cedar")).strip()
            or "cedar",
            tts_format=str(voice_openai_data.get("tts_format", "mp3")).strip().lower()
            or "mp3",
            tts_speed=float(voice_openai_data.get("tts_speed", 1.0)),
            max_tts_chars=int(voice_openai_data.get("max_tts_chars", 600)),
            output_audio_dir=str(voice_openai_data.get("output_audio_dir", "")).strip()
            or None,
            persist_tts_outputs=bool(
                voice_openai_data.get("persist_tts_outputs", False)
            ),
            realtime_model=str(
                voice_openai_data.get("realtime_model", "gpt-realtime")
            ).strip()
            or "gpt-realtime",
            vad_mode=str(voice_openai_data.get("vad_mode", "server_vad")).strip()
            or "server_vad",
        ),
        playback=VoicePlaybackConfig(
            enabled=bool(voice_playback_data.get("enabled", False)),
            provider=str(voice_playback_data.get("provider", "local")).strip().lower()
            or "local",
            device=str(voice_playback_data.get("device", "default")).strip()
            or "default",
            volume=float(voice_playback_data.get("volume", 1.0)),
            allow_dev_playback=bool(
                voice_playback_data.get("allow_dev_playback", False)
            ),
            max_audio_bytes=int(voice_playback_data.get("max_audio_bytes", 10_000_000)),
            max_duration_ms=int(voice_playback_data.get("max_duration_ms", 120_000)),
            delete_transient_after_playback=bool(
                voice_playback_data.get("delete_transient_after_playback", True)
            ),
        ),
        capture=VoiceCaptureConfig(
            enabled=bool(voice_capture_data.get("enabled", False)),
            provider=str(voice_capture_data.get("provider", "local")).strip().lower()
            or "local",
            mode=str(voice_capture_data.get("mode", "push_to_talk")).strip().lower()
            or "push_to_talk",
            device=str(voice_capture_data.get("device", "default")).strip()
            or "default",
            sample_rate=int(voice_capture_data.get("sample_rate", 16000)),
            channels=int(voice_capture_data.get("channels", 1)),
            format=str(voice_capture_data.get("format", "wav")).strip().lower()
            or "wav",
            max_duration_ms=int(voice_capture_data.get("max_duration_ms", 30_000)),
            max_audio_bytes=int(voice_capture_data.get("max_audio_bytes", 10_000_000)),
            auto_stop_on_max_duration=bool(
                voice_capture_data.get("auto_stop_on_max_duration", True)
            ),
            persist_captured_audio=bool(
                voice_capture_data.get("persist_captured_audio", False)
            ),
            delete_transient_after_turn=bool(
                voice_capture_data.get("delete_transient_after_turn", True)
            ),
            allow_dev_capture=bool(voice_capture_data.get("allow_dev_capture", False)),
        ),
        wake=VoiceWakeConfig(
            enabled=bool(voice_wake_data.get("enabled", False)),
            provider=str(voice_wake_data.get("provider", "mock")).strip().lower()
            or "mock",
            wake_phrase=str(voice_wake_data.get("wake_phrase", "Stormhelm")).strip()
            or "Stormhelm",
            device=str(voice_wake_data.get("device", "default")).strip() or "default",
            sample_rate=int(voice_wake_data.get("sample_rate", 16000)),
            backend=str(voice_wake_data.get("backend", "unavailable")).strip().lower()
            or "unavailable",
            model_path=str(voice_wake_data.get("model_path", "")).strip() or None,
            sensitivity=float(voice_wake_data.get("sensitivity", 0.5)),
            confidence_threshold=float(
                voice_wake_data.get("confidence_threshold", 0.75)
            ),
            cooldown_ms=int(voice_wake_data.get("cooldown_ms", 2500)),
            max_wake_session_ms=int(voice_wake_data.get("max_wake_session_ms", 15000)),
            false_positive_window_ms=int(
                voice_wake_data.get("false_positive_window_ms", 3000)
            ),
            allow_dev_wake=bool(voice_wake_data.get("allow_dev_wake", False)),
        ),
        post_wake=VoicePostWakeConfig(
            enabled=bool(voice_post_wake_data.get("enabled", False)),
            listen_window_ms=int(
                voice_post_wake_data.get("listen_window_ms", 8000)
            ),
            max_utterance_ms=int(
                voice_post_wake_data.get("max_utterance_ms", 30000)
            ),
            auto_start_capture=bool(
                voice_post_wake_data.get("auto_start_capture", True)
            ),
            auto_submit_on_capture_complete=bool(
                voice_post_wake_data.get("auto_submit_on_capture_complete", True)
            ),
            allow_dev_post_wake=bool(
                voice_post_wake_data.get("allow_dev_post_wake", False)
            ),
        ),
        vad=VoiceVADConfig(
            enabled=bool(voice_vad_data.get("enabled", False)),
            provider=str(voice_vad_data.get("provider", "mock")).strip().lower()
            or "mock",
            silence_ms=int(voice_vad_data.get("silence_ms", 900)),
            speech_start_threshold=float(
                voice_vad_data.get("speech_start_threshold", 0.5)
            ),
            speech_stop_threshold=float(
                voice_vad_data.get("speech_stop_threshold", 0.35)
            ),
            min_speech_ms=int(voice_vad_data.get("min_speech_ms", 250)),
            max_utterance_ms=int(voice_vad_data.get("max_utterance_ms", 30000)),
            pre_roll_ms=int(voice_vad_data.get("pre_roll_ms", 250)),
            post_roll_ms=int(voice_vad_data.get("post_roll_ms", 250)),
            allow_dev_vad=bool(voice_vad_data.get("allow_dev_vad", False)),
            auto_finalize_capture=bool(
                voice_vad_data.get("auto_finalize_capture", True)
            ),
        ),
        realtime=VoiceRealtimeConfig(
            enabled=bool(voice_realtime_data.get("enabled", False)),
            provider=str(voice_realtime_data.get("provider", "openai")).strip().lower()
            or "openai",
            mode=str(
                voice_realtime_data.get("mode", "transcription_bridge")
            ).strip().lower()
            or "transcription_bridge",
            model=str(
                voice_realtime_data.get(
                    "model", voice_openai_data.get("realtime_model", "gpt-realtime")
                )
            ).strip()
            or "gpt-realtime",
            voice=str(
                voice_realtime_data.get("voice", "stormhelm_default")
            ).strip()
            or "stormhelm_default",
            turn_detection=str(
                voice_realtime_data.get(
                    "turn_detection", voice_openai_data.get("vad_mode", "server_vad")
                )
            ).strip().lower()
            or "server_vad",
            semantic_vad_enabled=bool(
                voice_realtime_data.get("semantic_vad_enabled", False)
            ),
            max_session_ms=int(voice_realtime_data.get("max_session_ms", 60_000)),
            max_turn_ms=int(voice_realtime_data.get("max_turn_ms", 30_000)),
            allow_dev_realtime=bool(
                voice_realtime_data.get("allow_dev_realtime", False)
            ),
            direct_tools_allowed=bool(
                voice_realtime_data.get("direct_tools_allowed", False)
            ),
            core_bridge_required=bool(
                voice_realtime_data.get("core_bridge_required", True)
            ),
            audio_output_enabled=bool(
                voice_realtime_data.get("audio_output_enabled", False)
            ),
            speech_to_speech_enabled=bool(
                voice_realtime_data.get("speech_to_speech_enabled", False)
            ),
            audio_output_from_realtime=bool(
                voice_realtime_data.get("audio_output_from_realtime", False)
            ),
            require_core_for_commands=bool(
                voice_realtime_data.get("require_core_for_commands", True)
            ),
            allow_smalltalk_without_core=bool(
                voice_realtime_data.get("allow_smalltalk_without_core", False)
            ),
        ),
        confirmation=VoiceConfirmationConfig(
            enabled=bool(voice_confirmation_data.get("enabled", True)),
            max_confirmation_age_ms=int(
                voice_confirmation_data.get("max_confirmation_age_ms", 30_000)
            ),
            allow_soft_yes_for_low_risk=bool(
                voice_confirmation_data.get("allow_soft_yes_for_low_risk", True)
            ),
            require_strong_phrase_for_destructive=bool(
                voice_confirmation_data.get(
                    "require_strong_phrase_for_destructive", True
                )
            ),
            consume_once=bool(voice_confirmation_data.get("consume_once", True)),
            reject_on_task_switch=bool(
                voice_confirmation_data.get("reject_on_task_switch", True)
            ),
            reject_on_payload_change=bool(
                voice_confirmation_data.get("reject_on_payload_change", True)
            ),
            reject_on_session_restart=bool(
                voice_confirmation_data.get("reject_on_session_restart", True)
            ),
        ),
    )

    safety_data = data.get("safety", {})
    allowed_dirs = [
        _expand_path(value, root, data_dir) or root
        for value in safety_data.get("allowed_read_dirs", [str(root), "~/Documents"])
    ]
    safety_config = SafetyConfig(
        allowed_read_dirs=allowed_dirs,
        allow_shell_stub=bool(safety_data.get("allow_shell_stub", False)),
        unsafe_test_mode=bool(safety_data.get("unsafe_test_mode", False)),
    )

    tool_data = data.get("tools", {})
    enabled_data = tool_data.get("enabled", {})
    tool_config = ToolConfig(
        enabled=ToolEnablementConfig(
            clock=bool(enabled_data.get("clock", True)),
            system_info=bool(enabled_data.get("system_info", True)),
            file_reader=bool(enabled_data.get("file_reader", True)),
            notes_write=bool(enabled_data.get("notes_write", True)),
            echo=bool(enabled_data.get("echo", True)),
            browser_context=bool(enabled_data.get("browser_context", True)),
            activity_summary=bool(enabled_data.get("activity_summary", True)),
            shell_command=bool(enabled_data.get("shell_command", False)),
            deck_open_url=bool(enabled_data.get("deck_open_url", True)),
            external_open_url=bool(enabled_data.get("external_open_url", True)),
            deck_open_file=bool(enabled_data.get("deck_open_file", True)),
            external_open_file=bool(enabled_data.get("external_open_file", True)),
            machine_status=bool(enabled_data.get("machine_status", True)),
            power_status=bool(enabled_data.get("power_status", True)),
            power_projection=bool(enabled_data.get("power_projection", True)),
            resource_status=bool(enabled_data.get("resource_status", True)),
            storage_status=bool(enabled_data.get("storage_status", True)),
            network_status=bool(enabled_data.get("network_status", True)),
            network_throughput=bool(enabled_data.get("network_throughput", True)),
            network_diagnosis=bool(enabled_data.get("network_diagnosis", True)),
            active_apps=bool(enabled_data.get("active_apps", True)),
            app_control=bool(enabled_data.get("app_control", True)),
            window_status=bool(enabled_data.get("window_status", True)),
            window_control=bool(enabled_data.get("window_control", True)),
            system_control=bool(enabled_data.get("system_control", True)),
            control_capabilities=bool(enabled_data.get("control_capabilities", True)),
            recent_files=bool(enabled_data.get("recent_files", True)),
            location_status=bool(enabled_data.get("location_status", True)),
            saved_locations=bool(enabled_data.get("saved_locations", True)),
            save_location=bool(enabled_data.get("save_location", True)),
            weather_current=bool(enabled_data.get("weather_current", True)),
            context_action=bool(enabled_data.get("context_action", True)),
            workspace_restore=bool(enabled_data.get("workspace_restore", True)),
            workspace_assemble=bool(enabled_data.get("workspace_assemble", True)),
            workspace_save=bool(enabled_data.get("workspace_save", True)),
            workspace_clear=bool(enabled_data.get("workspace_clear", True)),
            workspace_archive=bool(enabled_data.get("workspace_archive", True)),
            workspace_rename=bool(enabled_data.get("workspace_rename", True)),
            workspace_tag=bool(enabled_data.get("workspace_tag", True)),
            workspace_list=bool(enabled_data.get("workspace_list", True)),
            workspace_where_left_off=bool(
                enabled_data.get("workspace_where_left_off", True)
            ),
            workspace_next_steps=bool(enabled_data.get("workspace_next_steps", True)),
        ),
        max_file_read_bytes=int(tool_data.get("max_file_read_bytes", 32768)),
    )

    return AppConfig(
        app_name=app_name,
        version=__version__,
        protocol_version=API_PROTOCOL_VERSION,
        release_channel=release_channel,
        environment=environment,
        debug=debug,
        project_root=root,
        runtime=RuntimePathConfig(
            mode=runtime.mode,
            is_frozen=runtime.is_frozen,
            source_root=runtime.source_root,
            install_root=runtime.install_root,
            resource_root=runtime.resource_root,
            assets_dir=runtime.resource_root / "assets",
            bundled_config_dir=runtime.resource_root / "config",
            portable_config_path=runtime.install_root / "config" / "portable.toml",
            user_config_path=data_dir / "config" / "user.toml",
            state_dir=state_dir,
            core_state_path=state_dir / "core-state.json",
            first_run_marker_path=state_dir / "first-run.json",
            lifecycle_state_path=state_dir / "lifecycle-state.json",
            core_session_path=state_dir / "core-session.json",
            shell_session_path=state_dir / "shell-session.json",
            core_executable_path=runtime.install_root / "stormhelm-core.exe",
        ),
        network=NetworkConfig(host=host, port=port),
        storage=StorageConfig(
            data_dir=data_dir,
            database_path=database_path,
            logs_dir=logs_dir,
            state_dir=state_dir,
            cache_dir=cache_dir,
        ),
        logging=logging_config,
        concurrency=concurrency_config,
        ui=ui_config,
        lifecycle=lifecycle_config,
        event_stream=event_stream_config,
        location=location_config,
        weather=weather_config,
        hardware_telemetry=hardware_telemetry_config,
        screen_awareness=screen_awareness_config,
        calculations=calculations_config,
        software_control=software_control_config,
        software_recovery=software_recovery_config,
        trust=trust_config,
        discord_relay=discord_relay_config,
        openai=openai_config,
        voice=voice_config,
        safety=safety_config,
        tools=tool_config,
    )


def _read_toml(path: Path) -> ConfigDict:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _deep_merge(base: ConfigDict, override: ConfigDict) -> ConfigDict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


def _apply_env_overrides(data: ConfigDict, env: Mapping[str, str]) -> ConfigDict:
    merged = dict(data)
    overrides: dict[str, tuple[str, Callable[[str], Any]]] = {
        "STORMHELM_ENV": ("environment", str),
        "STORMHELM_DEBUG": ("debug", _parse_bool),
        "STORMHELM_RELEASE_CHANNEL": ("release_channel", str),
        "STORMHELM_CORE_HOST": ("network.host", str),
        "STORMHELM_CORE_PORT": ("network.port", int),
        "STORMHELM_DATA_DIR": ("storage.data_dir", str),
        "STORMHELM_MAX_CONCURRENT_JOBS": ("concurrency.max_workers", int),
        "STORMHELM_DEFAULT_JOB_TIMEOUT_SECONDS": (
            "concurrency.default_job_timeout_seconds",
            float,
        ),
        "STORMHELM_STARTUP_ENABLED": ("lifecycle.startup_enabled", _parse_bool),
        "STORMHELM_START_CORE_WITH_WINDOWS": (
            "lifecycle.start_core_with_windows",
            _parse_bool,
        ),
        "STORMHELM_START_SHELL_WITH_WINDOWS": (
            "lifecycle.start_shell_with_windows",
            _parse_bool,
        ),
        "STORMHELM_TRAY_ONLY_STARTUP": ("lifecycle.tray_only_startup", _parse_bool),
        "STORMHELM_GHOST_READY_ON_STARTUP": (
            "lifecycle.ghost_ready_on_startup",
            _parse_bool,
        ),
        "STORMHELM_BACKGROUND_CORE_RESIDENT": (
            "lifecycle.background_core_resident",
            _parse_bool,
        ),
        "STORMHELM_AUTO_RESTART_CORE": ("lifecycle.auto_restart_core", _parse_bool),
        "STORMHELM_MAX_CORE_RESTART_ATTEMPTS": (
            "lifecycle.max_core_restart_attempts",
            int,
        ),
        "STORMHELM_RESTART_FAILURE_WINDOW_SECONDS": (
            "lifecycle.restart_failure_window_seconds",
            float,
        ),
        "STORMHELM_SHELL_HEARTBEAT_INTERVAL_SECONDS": (
            "lifecycle.shell_heartbeat_interval_seconds",
            float,
        ),
        "STORMHELM_SHELL_STALE_AFTER_SECONDS": (
            "lifecycle.shell_stale_after_seconds",
            float,
        ),
        "STORMHELM_CORE_RESTART_BACKOFF_MS": ("lifecycle.core_restart_backoff_ms", int),
        "STORMHELM_OPENAI_ENABLED": ("openai.enabled", _parse_bool),
        "STORMHELM_OPENAI_BASE_URL": ("openai.base_url", str),
        "STORMHELM_OPENAI_MODEL": ("openai.model", str),
        "STORMHELM_OPENAI_PLANNER_MODEL": ("openai.planner_model", str),
        "STORMHELM_OPENAI_REASONING_MODEL": ("openai.reasoning_model", str),
        "STORMHELM_OPENAI_TIMEOUT_SECONDS": ("openai.timeout_seconds", float),
        "STORMHELM_OPENAI_MAX_TOOL_ROUNDS": ("openai.max_tool_rounds", int),
        "STORMHELM_OPENAI_MAX_OUTPUT_TOKENS": ("openai.max_output_tokens", int),
        "STORMHELM_OPENAI_PLANNER_MAX_OUTPUT_TOKENS": (
            "openai.planner_max_output_tokens",
            int,
        ),
        "STORMHELM_OPENAI_REASONING_MAX_OUTPUT_TOKENS": (
            "openai.reasoning_max_output_tokens",
            int,
        ),
        "STORMHELM_VOICE_ENABLED": ("voice.enabled", _parse_bool),
        "STORMHELM_VOICE_PROVIDER": ("voice.provider", str),
        "STORMHELM_VOICE_MODE": ("voice.mode", str),
        "STORMHELM_VOICE_WAKE_WORD_ENABLED": ("voice.wake_word_enabled", _parse_bool),
        "STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED": (
            "voice.spoken_responses_enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_MANUAL_INPUT_ENABLED": (
            "voice.manual_input_enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_ENABLED": ("voice.realtime_enabled", _parse_bool),
        "STORMHELM_VOICE_DEBUG_MOCK_PROVIDER": (
            "voice.debug_mock_provider",
            _parse_bool,
        ),
        "STORMHELM_VOICE_PLAYBACK_ENABLED": ("voice.playback.enabled", _parse_bool),
        "STORMHELM_VOICE_PLAYBACK_PROVIDER": ("voice.playback.provider", str),
        "STORMHELM_VOICE_PLAYBACK_DEVICE": ("voice.playback.device", str),
        "STORMHELM_VOICE_PLAYBACK_VOLUME": ("voice.playback.volume", float),
        "STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK": (
            "voice.playback.allow_dev_playback",
            _parse_bool,
        ),
        "STORMHELM_VOICE_PLAYBACK_MAX_AUDIO_BYTES": (
            "voice.playback.max_audio_bytes",
            int,
        ),
        "STORMHELM_VOICE_PLAYBACK_MAX_DURATION_MS": (
            "voice.playback.max_duration_ms",
            int,
        ),
        "STORMHELM_VOICE_PLAYBACK_DELETE_TRANSIENT_AFTER_PLAYBACK": (
            "voice.playback.delete_transient_after_playback",
            _parse_bool,
        ),
        "STORMHELM_VOICE_CAPTURE_ENABLED": ("voice.capture.enabled", _parse_bool),
        "STORMHELM_VOICE_CAPTURE_PROVIDER": ("voice.capture.provider", str),
        "STORMHELM_VOICE_CAPTURE_MODE": ("voice.capture.mode", str),
        "STORMHELM_VOICE_CAPTURE_DEVICE": ("voice.capture.device", str),
        "STORMHELM_VOICE_CAPTURE_SAMPLE_RATE": ("voice.capture.sample_rate", int),
        "STORMHELM_VOICE_CAPTURE_CHANNELS": ("voice.capture.channels", int),
        "STORMHELM_VOICE_CAPTURE_FORMAT": ("voice.capture.format", str),
        "STORMHELM_VOICE_CAPTURE_MAX_DURATION_MS": (
            "voice.capture.max_duration_ms",
            int,
        ),
        "STORMHELM_VOICE_CAPTURE_MAX_AUDIO_BYTES": (
            "voice.capture.max_audio_bytes",
            int,
        ),
        "STORMHELM_VOICE_CAPTURE_AUTO_STOP_ON_MAX_DURATION": (
            "voice.capture.auto_stop_on_max_duration",
            _parse_bool,
        ),
        "STORMHELM_VOICE_CAPTURE_PERSIST_CAPTURED_AUDIO": (
            "voice.capture.persist_captured_audio",
            _parse_bool,
        ),
        "STORMHELM_VOICE_CAPTURE_DELETE_TRANSIENT_AFTER_TURN": (
            "voice.capture.delete_transient_after_turn",
            _parse_bool,
        ),
        "STORMHELM_VOICE_CAPTURE_ALLOW_DEV_CAPTURE": (
            "voice.capture.allow_dev_capture",
            _parse_bool,
        ),
        "STORMHELM_VOICE_WAKE_ENABLED": ("voice.wake.enabled", _parse_bool),
        "STORMHELM_VOICE_WAKE_PROVIDER": ("voice.wake.provider", str),
        "STORMHELM_VOICE_WAKE_PHRASE": ("voice.wake.wake_phrase", str),
        "STORMHELM_VOICE_WAKE_DEVICE": ("voice.wake.device", str),
        "STORMHELM_VOICE_WAKE_SAMPLE_RATE": ("voice.wake.sample_rate", int),
        "STORMHELM_VOICE_WAKE_BACKEND": ("voice.wake.backend", str),
        "STORMHELM_VOICE_WAKE_MODEL_PATH": ("voice.wake.model_path", str),
        "STORMHELM_VOICE_WAKE_SENSITIVITY": ("voice.wake.sensitivity", float),
        "STORMHELM_VOICE_WAKE_CONFIDENCE_THRESHOLD": (
            "voice.wake.confidence_threshold",
            float,
        ),
        "STORMHELM_VOICE_WAKE_COOLDOWN_MS": ("voice.wake.cooldown_ms", int),
        "STORMHELM_VOICE_WAKE_MAX_WAKE_SESSION_MS": (
            "voice.wake.max_wake_session_ms",
            int,
        ),
        "STORMHELM_VOICE_WAKE_FALSE_POSITIVE_WINDOW_MS": (
            "voice.wake.false_positive_window_ms",
            int,
        ),
        "STORMHELM_VOICE_WAKE_ALLOW_DEV_WAKE": (
            "voice.wake.allow_dev_wake",
            _parse_bool,
        ),
        "STORMHELM_VOICE_POST_WAKE_ENABLED": (
            "voice.post_wake.enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_POST_WAKE_LISTEN_WINDOW_MS": (
            "voice.post_wake.listen_window_ms",
            int,
        ),
        "STORMHELM_VOICE_POST_WAKE_MAX_UTTERANCE_MS": (
            "voice.post_wake.max_utterance_ms",
            int,
        ),
        "STORMHELM_VOICE_POST_WAKE_AUTO_START_CAPTURE": (
            "voice.post_wake.auto_start_capture",
            _parse_bool,
        ),
        "STORMHELM_VOICE_POST_WAKE_AUTO_SUBMIT_ON_CAPTURE_COMPLETE": (
            "voice.post_wake.auto_submit_on_capture_complete",
            _parse_bool,
        ),
        "STORMHELM_VOICE_POST_WAKE_ALLOW_DEV_POST_WAKE": (
            "voice.post_wake.allow_dev_post_wake",
            _parse_bool,
        ),
        "STORMHELM_VOICE_VAD_ENABLED": ("voice.vad.enabled", _parse_bool),
        "STORMHELM_VOICE_VAD_PROVIDER": ("voice.vad.provider", str),
        "STORMHELM_VOICE_VAD_SILENCE_MS": ("voice.vad.silence_ms", int),
        "STORMHELM_VOICE_VAD_SPEECH_START_THRESHOLD": (
            "voice.vad.speech_start_threshold",
            float,
        ),
        "STORMHELM_VOICE_VAD_SPEECH_STOP_THRESHOLD": (
            "voice.vad.speech_stop_threshold",
            float,
        ),
        "STORMHELM_VOICE_VAD_MIN_SPEECH_MS": ("voice.vad.min_speech_ms", int),
        "STORMHELM_VOICE_VAD_MAX_UTTERANCE_MS": (
            "voice.vad.max_utterance_ms",
            int,
        ),
        "STORMHELM_VOICE_VAD_PRE_ROLL_MS": ("voice.vad.pre_roll_ms", int),
        "STORMHELM_VOICE_VAD_POST_ROLL_MS": ("voice.vad.post_roll_ms", int),
        "STORMHELM_VOICE_VAD_ALLOW_DEV_VAD": (
            "voice.vad.allow_dev_vad",
            _parse_bool,
        ),
        "STORMHELM_VOICE_VAD_AUTO_FINALIZE_CAPTURE": (
            "voice.vad.auto_finalize_capture",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_BRIDGE_ENABLED": (
            "voice.realtime.enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_PROVIDER": ("voice.realtime.provider", str),
        "STORMHELM_VOICE_REALTIME_MODE": ("voice.realtime.mode", str),
        "STORMHELM_VOICE_REALTIME_MODEL": ("voice.realtime.model", str),
        "STORMHELM_VOICE_REALTIME_VOICE": ("voice.realtime.voice", str),
        "STORMHELM_VOICE_REALTIME_TURN_DETECTION": (
            "voice.realtime.turn_detection",
            str,
        ),
        "STORMHELM_VOICE_REALTIME_SEMANTIC_VAD_ENABLED": (
            "voice.realtime.semantic_vad_enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_MAX_SESSION_MS": (
            "voice.realtime.max_session_ms",
            int,
        ),
        "STORMHELM_VOICE_REALTIME_MAX_TURN_MS": (
            "voice.realtime.max_turn_ms",
            int,
        ),
        "STORMHELM_VOICE_REALTIME_ALLOW_DEV_REALTIME": (
            "voice.realtime.allow_dev_realtime",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_DIRECT_TOOLS_ALLOWED": (
            "voice.realtime.direct_tools_allowed",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_CORE_BRIDGE_REQUIRED": (
            "voice.realtime.core_bridge_required",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_AUDIO_OUTPUT_ENABLED": (
            "voice.realtime.audio_output_enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_SPEECH_TO_SPEECH_ENABLED": (
            "voice.realtime.speech_to_speech_enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_AUDIO_OUTPUT_FROM_REALTIME": (
            "voice.realtime.audio_output_from_realtime",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_REQUIRE_CORE_FOR_COMMANDS": (
            "voice.realtime.require_core_for_commands",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_ALLOW_SMALLTALK_WITHOUT_CORE": (
            "voice.realtime.allow_smalltalk_without_core",
            _parse_bool,
        ),
        "STORMHELM_VOICE_OPENAI_STT_MODEL": ("voice.openai.stt_model", str),
        "STORMHELM_VOICE_OPENAI_TRANSCRIPTION_LANGUAGE": (
            "voice.openai.transcription_language",
            str,
        ),
        "STORMHELM_VOICE_OPENAI_TRANSCRIPTION_PROMPT": (
            "voice.openai.transcription_prompt",
            str,
        ),
        "STORMHELM_VOICE_OPENAI_TIMEOUT_SECONDS": (
            "voice.openai.timeout_seconds",
            float,
        ),
        "STORMHELM_VOICE_OPENAI_MAX_AUDIO_SECONDS": (
            "voice.openai.max_audio_seconds",
            float,
        ),
        "STORMHELM_VOICE_OPENAI_MAX_AUDIO_BYTES": ("voice.openai.max_audio_bytes", int),
        "STORMHELM_VOICE_OPENAI_TTS_MODEL": ("voice.openai.tts_model", str),
        "STORMHELM_VOICE_OPENAI_TTS_VOICE": ("voice.openai.tts_voice", str),
        "STORMHELM_VOICE_OPENAI_TTS_FORMAT": ("voice.openai.tts_format", str),
        "STORMHELM_VOICE_OPENAI_TTS_SPEED": ("voice.openai.tts_speed", float),
        "STORMHELM_VOICE_OPENAI_MAX_TTS_CHARS": ("voice.openai.max_tts_chars", int),
        "STORMHELM_VOICE_OPENAI_OUTPUT_AUDIO_DIR": (
            "voice.openai.output_audio_dir",
            str,
        ),
        "STORMHELM_VOICE_OPENAI_PERSIST_TTS_OUTPUTS": (
            "voice.openai.persist_tts_outputs",
            _parse_bool,
        ),
        "STORMHELM_VOICE_OPENAI_REALTIME_MODEL": ("voice.openai.realtime_model", str),
        "STORMHELM_VOICE_OPENAI_VAD_MODE": ("voice.openai.vad_mode", str),
        "STORMHELM_HOME_LABEL": ("location.home_label", str),
        "STORMHELM_HOME_CITY": ("location.home_city", str),
        "STORMHELM_HOME_REGION": ("location.home_region", str),
        "STORMHELM_HOME_COUNTRY": ("location.home_country", str),
        "STORMHELM_HOME_LATITUDE": ("location.home_latitude", float),
        "STORMHELM_HOME_LONGITUDE": ("location.home_longitude", float),
        "STORMHELM_HOME_TIMEZONE": ("location.home_timezone", str),
        "STORMHELM_ALLOW_APPROXIMATE_LOCATION": (
            "location.allow_approximate_lookup",
            _parse_bool,
        ),
        "STORMHELM_LOCATION_LOOKUP_TIMEOUT_SECONDS": (
            "location.lookup_timeout_seconds",
            float,
        ),
        "STORMHELM_WEATHER_ENABLED": ("weather.enabled", _parse_bool),
        "STORMHELM_WEATHER_UNITS": ("weather.units", str),
        "STORMHELM_WEATHER_BASE_URL": ("weather.provider_base_url", str),
        "STORMHELM_WEATHER_TIMEOUT_SECONDS": ("weather.timeout_seconds", float),
        "STORMHELM_HARDWARE_TELEMETRY_ENABLED": (
            "hardware_telemetry.enabled",
            _parse_bool,
        ),
        "STORMHELM_HARDWARE_TELEMETRY_TIMEOUT_SECONDS": (
            "hardware_telemetry.helper_timeout_seconds",
            float,
        ),
        "STORMHELM_HARDWARE_TELEMETRY_PROVIDER_TIMEOUT_SECONDS": (
            "hardware_telemetry.provider_timeout_seconds",
            float,
        ),
        "STORMHELM_HARDWARE_TELEMETRY_IDLE_CACHE_TTL_SECONDS": (
            "hardware_telemetry.idle_cache_ttl_seconds",
            float,
        ),
        "STORMHELM_HARDWARE_TELEMETRY_ACTIVE_CACHE_TTL_SECONDS": (
            "hardware_telemetry.active_cache_ttl_seconds",
            float,
        ),
        "STORMHELM_HARDWARE_TELEMETRY_BURST_CACHE_TTL_SECONDS": (
            "hardware_telemetry.burst_cache_ttl_seconds",
            float,
        ),
        "STORMHELM_HARDWARE_TELEMETRY_ELEVATED_HELPER_ENABLED": (
            "hardware_telemetry.elevated_helper_enabled",
            _parse_bool,
        ),
        "STORMHELM_HARDWARE_TELEMETRY_ELEVATED_HELPER_TIMEOUT_SECONDS": (
            "hardware_telemetry.elevated_helper_timeout_seconds",
            float,
        ),
        "STORMHELM_HARDWARE_TELEMETRY_ELEVATED_HELPER_COOLDOWN_SECONDS": (
            "hardware_telemetry.elevated_helper_cooldown_seconds",
            float,
        ),
        "STORMHELM_HARDWARE_TELEMETRY_HWINFO_ENABLED": (
            "hardware_telemetry.hwinfo_enabled",
            _parse_bool,
        ),
        "STORMHELM_HARDWARE_TELEMETRY_HWINFO_PATH": (
            "hardware_telemetry.hwinfo_executable_path",
            str,
        ),
        "STORMHELM_SCREEN_AWARENESS_ENABLED": ("screen_awareness.enabled", _parse_bool),
        "STORMHELM_SCREEN_AWARENESS_PHASE": ("screen_awareness.phase", str),
        "STORMHELM_SCREEN_AWARENESS_PLANNER_ROUTING_ENABLED": (
            "screen_awareness.planner_routing_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_DEBUG_EVENTS_ENABLED": (
            "screen_awareness.debug_events_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_OBSERVATION_ENABLED": (
            "screen_awareness.observation_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_INTERPRETATION_ENABLED": (
            "screen_awareness.interpretation_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_GROUNDING_ENABLED": (
            "screen_awareness.grounding_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_GUIDANCE_ENABLED": (
            "screen_awareness.guidance_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_ACTION_ENABLED": (
            "screen_awareness.action_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_ACTION_POLICY_MODE": (
            "screen_awareness.action_policy_mode",
            str,
        ),
        "STORMHELM_SCREEN_AWARENESS_VERIFICATION_ENABLED": (
            "screen_awareness.verification_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_MEMORY_ENABLED": (
            "screen_awareness.memory_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_ADAPTERS_ENABLED": (
            "screen_awareness.adapters_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PROBLEM_SOLVING_ENABLED": (
            "screen_awareness.problem_solving_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_WORKFLOW_LEARNING_ENABLED": (
            "screen_awareness.workflow_learning_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_BRAIN_INTEGRATION_ENABLED": (
            "screen_awareness.brain_integration_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_POWER_FEATURES_ENABLED": (
            "screen_awareness.power_features_enabled",
            _parse_bool,
        ),
        "STORMHELM_CALCULATIONS_ENABLED": ("calculations.enabled", _parse_bool),
        "STORMHELM_CALCULATIONS_PLANNER_ROUTING_ENABLED": (
            "calculations.planner_routing_enabled",
            _parse_bool,
        ),
        "STORMHELM_CALCULATIONS_DEBUG_EVENTS_ENABLED": (
            "calculations.debug_events_enabled",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_CONTROL_ENABLED": ("software_control.enabled", _parse_bool),
        "STORMHELM_SOFTWARE_CONTROL_PLANNER_ROUTING_ENABLED": (
            "software_control.planner_routing_enabled",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_CONTROL_DEBUG_EVENTS_ENABLED": (
            "software_control.debug_events_enabled",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_CONTROL_PACKAGE_MANAGER_ROUTES_ENABLED": (
            "software_control.package_manager_routes_enabled",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_CONTROL_VENDOR_INSTALLER_ROUTES_ENABLED": (
            "software_control.vendor_installer_routes_enabled",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_CONTROL_BROWSER_GUIDED_ROUTES_ENABLED": (
            "software_control.browser_guided_routes_enabled",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_CONTROL_PRIVILEGED_OPERATIONS_ALLOWED": (
            "software_control.privileged_operations_allowed",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_CONTROL_TRUSTED_SOURCES_ONLY": (
            "software_control.trusted_sources_only",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_RECOVERY_ENABLED": (
            "software_recovery.enabled",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_RECOVERY_DEBUG_EVENTS_ENABLED": (
            "software_recovery.debug_events_enabled",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_RECOVERY_LOCAL_TROUBLESHOOTING_ENABLED": (
            "software_recovery.local_troubleshooting_enabled",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_RECOVERY_MAX_RETRY_ATTEMPTS": (
            "software_recovery.max_retry_attempts",
            int,
        ),
        "STORMHELM_SOFTWARE_RECOVERY_MAX_RECOVERY_STEPS": (
            "software_recovery.max_recovery_steps",
            int,
        ),
        "STORMHELM_SOFTWARE_RECOVERY_CLOUD_FALLBACK_ENABLED": (
            "software_recovery.cloud_fallback_enabled",
            _parse_bool,
        ),
        "STORMHELM_SOFTWARE_RECOVERY_CLOUD_FALLBACK_MODEL": (
            "software_recovery.cloud_fallback_model",
            str,
        ),
        "STORMHELM_SOFTWARE_RECOVERY_REDACTION_ENABLED": (
            "software_recovery.redaction_enabled",
            _parse_bool,
        ),
        "STORMHELM_DISCORD_RELAY_ENABLED": ("discord_relay.enabled", _parse_bool),
        "STORMHELM_DISCORD_RELAY_PLANNER_ROUTING_ENABLED": (
            "discord_relay.planner_routing_enabled",
            _parse_bool,
        ),
        "STORMHELM_DISCORD_RELAY_DEBUG_EVENTS_ENABLED": (
            "discord_relay.debug_events_enabled",
            _parse_bool,
        ),
        "STORMHELM_DISCORD_RELAY_SCREEN_DISAMBIGUATION_ENABLED": (
            "discord_relay.screen_disambiguation_enabled",
            _parse_bool,
        ),
        "STORMHELM_DISCORD_RELAY_PREVIEW_BEFORE_SEND": (
            "discord_relay.preview_before_send",
            _parse_bool,
        ),
        "STORMHELM_DISCORD_RELAY_VERIFICATION_ENABLED": (
            "discord_relay.verification_enabled",
            _parse_bool,
        ),
        "STORMHELM_DISCORD_RELAY_LOCAL_DM_ROUTE_ENABLED": (
            "discord_relay.local_dm_route_enabled",
            _parse_bool,
        ),
        "STORMHELM_DISCORD_RELAY_BOT_WEBHOOK_ROUTES_ENABLED": (
            "discord_relay.bot_webhook_routes_enabled",
            _parse_bool,
        ),
        "STORMHELM_UNSAFE_TEST_MODE": ("safety.unsafe_test_mode", _parse_bool),
    }

    for env_key, (path, parser) in overrides.items():
        raw_value = env.get(env_key)
        if raw_value is None or raw_value == "":
            continue
        _set_nested_value(merged, path, parser(raw_value))

    return merged


def _set_nested_value(target: ConfigDict, dotted_path: str, value: Any) -> None:
    current = target
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _expand_path(raw: str | None, root: Path, data_dir: Path | None) -> Path | None:
    if not raw:
        return None

    expanded = raw.replace("${PROJECT_ROOT}", str(root))
    if data_dir is not None:
        expanded = expanded.replace("${DATA_DIR}", str(data_dir))
    return Path(expanded).expanduser().resolve()


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_optional_float(raw: Any) -> float | None:
    if raw in {None, ""}:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _resolve_runtime(project_root: Path | None) -> RuntimeDiscovery:
    if project_root is not None:
        root = Path(project_root).resolve()
        return RuntimeDiscovery(
            is_frozen=False,
            mode="source",
            source_root=root,
            install_root=root,
            resource_root=root,
        )
    return discover_runtime()


def _resolve_root(project_root: Path | None, runtime: RuntimeDiscovery) -> Path:
    if project_root is not None:
        return Path(project_root).resolve()
    if runtime.source_root is not None:
        return runtime.source_root.resolve()
    return runtime.install_root.resolve()


def _initial_override_candidates(
    *,
    runtime: RuntimeDiscovery,
    root: Path,
    config_path: Path | None,
) -> list[Path]:
    candidates: list[Path] = []
    if runtime.mode == "source":
        candidates.append(root / "config" / "development.toml")
    candidates.append(runtime.install_root / "config" / "portable.toml")
    if config_path is not None:
        candidates.append(Path(config_path).resolve())
    return candidates


def _resolve_data_dir(data: ConfigDict, root: Path, app_name: str) -> Path:
    storage_data = data.get("storage", {})
    return _expand_path(
        storage_data.get("data_dir") or "", root, None
    ) or default_data_dir(app_name)


def _apply_unsafe_test_mode_overrides(config: AppConfig, *, root: Path) -> None:
    filesystem_root = _filesystem_root(root)
    config.safety.allow_shell_stub = True
    config.safety.allowed_read_dirs = [filesystem_root]
    config.tools.enabled.shell_command = True
    config.software_control.package_manager_routes_enabled = True
    config.software_control.vendor_installer_routes_enabled = True
    config.software_control.browser_guided_routes_enabled = True
    config.software_control.privileged_operations_allowed = True
    config.software_control.trusted_sources_only = False
    config.software_control.unsafe_test_mode = True
    config.screen_awareness.action_policy_mode = "trusted_action"


def _filesystem_root(root: Path) -> Path:
    return Path(root.anchor or root.root or "/").resolve()
