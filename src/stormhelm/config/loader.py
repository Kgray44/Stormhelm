from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any, Callable, Mapping

from stormhelm.config.models import (
    AppConfig,
    CameraAwarenessCaptureConfig,
    CameraAwarenessConfig,
    CameraAwarenessDevConfig,
    CameraAwarenessPrivacyConfig,
    CameraAwarenessVisionConfig,
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
    ProviderFallbackConfig,
    ScreenAwarenessConfig,
    SoftwareControlConfig,
    SoftwareRecoveryConfig,
    TrustConfig,
    WebRetrievalChromiumConfig,
    WebRetrievalConfig,
    WebRetrievalHttpConfig,
    WebRetrievalObscuraCDPConfig,
    WebRetrievalObscuraConfig,
    WeatherConfig,
    RuntimePathConfig,
    SafetyConfig,
    StorageConfig,
    StormforgeFogConfig,
    StormforgeVoiceDiagnosticsConfig,
    PlaywrightBrowserAdapterConfig,
    ScreenAwarenessBrowserAdaptersConfig,
    ToolConfig,
    ToolEnablementConfig,
    UIConfig,
    VoiceConfig,
    VoiceCaptureConfig,
    VoiceConfirmationConfig,
    VoiceOpenAIConfig,
    VoicePlaybackConfig,
    VoiceVisualMeterConfig,
    VoiceVisualSyncConfig,
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
DEFAULT_UI_VISUAL_VARIANT = "classic"
VALID_UI_VISUAL_VARIANTS = frozenset({"classic", "stormforge"})
_LOGGER = logging.getLogger(__name__)


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
    ui_stormforge_data = (
        ui_data.get("stormforge", {}) if isinstance(ui_data.get("stormforge"), dict) else {}
    )
    ui_stormforge_fog_data = (
        ui_stormforge_data.get("fog", {})
        if isinstance(ui_stormforge_data.get("fog"), dict)
        else {}
    )
    ui_stormforge_voice_diagnostics_data = (
        ui_stormforge_data.get("voice_diagnostics", {})
        if isinstance(ui_stormforge_data.get("voice_diagnostics"), dict)
        else {}
    )
    ui_config = UIConfig(
        poll_interval_ms=int(ui_data.get("poll_interval_ms", 1500)),
        hide_to_tray_on_close=bool(ui_data.get("hide_to_tray_on_close", True)),
        ghost_shortcut=str(ui_data.get("ghost_shortcut", "Ctrl+Space")),
        visual_variant=_normalize_ui_visual_variant(
            ui_data.get("visual_variant", DEFAULT_UI_VISUAL_VARIANT)
        ),
        stormforge_fog=StormforgeFogConfig(
            enabled=_coerce_config_bool(ui_stormforge_fog_data.get("enabled"), False),
            mode=str(ui_stormforge_fog_data.get("mode", "volumetric")),
            quality=str(ui_stormforge_fog_data.get("quality", "medium")),
            intensity=ui_stormforge_fog_data.get("intensity", 0.35),
            motion=_coerce_config_bool(ui_stormforge_fog_data.get("motion"), True),
            edge_fog=_coerce_config_bool(
                ui_stormforge_fog_data.get("edge_fog"),
                True,
            ),
            foreground_wisps=_coerce_config_bool(
                ui_stormforge_fog_data.get("foreground_wisps"),
                True,
            ),
            max_foreground_opacity=ui_stormforge_fog_data.get(
                "max_foreground_opacity",
                0.08,
            ),
            center_clear_strength=ui_stormforge_fog_data.get(
                "center_clear_strength",
                0.65,
            ),
            lower_bias=ui_stormforge_fog_data.get("lower_bias", 0.45),
            drift_speed=ui_stormforge_fog_data.get("drift_speed", 0.055),
            drift_direction=str(
                ui_stormforge_fog_data.get("drift_direction", "right_to_left")
            ),
            flow_scale=ui_stormforge_fog_data.get("flow_scale", 1.0),
            crosswind_wobble=ui_stormforge_fog_data.get(
                "crosswind_wobble",
                0.18,
            ),
            rolling_speed=ui_stormforge_fog_data.get("rolling_speed", 0.035),
            wisp_stretch=ui_stormforge_fog_data.get("wisp_stretch", 1.8),
            card_clear_strength=ui_stormforge_fog_data.get(
                "card_clear_strength",
                0.72,
            ),
            anchor_clear_radius=ui_stormforge_fog_data.get(
                "anchor_clear_radius",
                0.18,
            ),
            debug_visible=_coerce_config_bool(
                ui_stormforge_fog_data.get("debug_visible"),
                False,
            ),
            debug_intensity_multiplier=ui_stormforge_fog_data.get(
                "debug_intensity_multiplier",
                3.0,
            ),
            debug_tint=_coerce_config_bool(
                ui_stormforge_fog_data.get("debug_tint"),
                True,
            ),
            diagnostic_disable_during_speech=_coerce_config_bool(
                ui_stormforge_fog_data.get("diagnostic_disable_during_speech"),
                False,
            ),
        ),
        stormforge_voice_diagnostics=StormforgeVoiceDiagnosticsConfig(
            anchor_visualizer_mode=str(
                ui_stormforge_voice_diagnostics_data.get(
                    "anchor_visualizer_mode",
                    "auto",
                )
            ),
            anchor_renderer=str(
                ui_stormforge_voice_diagnostics_data.get(
                    "anchor_renderer",
                    ui_stormforge_data.get(
                        "anchor_renderer", "legacy_blob_reference"
                    ),
                )
            ),
            qsg_visual_approval=str(
                ui_stormforge_voice_diagnostics_data.get(
                    "qsg_visual_approval",
                    "pending",
                )
            ),
            qsg_visual_approval_reason=str(
                ui_stormforge_voice_diagnostics_data.get(
                    "qsg_visual_approval_reason",
                    "",
                )
            ),
        ),
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
    screen_awareness_browser_adapters_data = (
        screen_awareness_data.get("browser_adapters", {})
        if isinstance(screen_awareness_data.get("browser_adapters"), dict)
        else {}
    )
    screen_awareness_playwright_data = (
        screen_awareness_browser_adapters_data.get("playwright", {})
        if isinstance(screen_awareness_browser_adapters_data.get("playwright"), dict)
        else {}
    )
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
        screen_capture_enabled=bool(
            screen_awareness_data.get("screen_capture_enabled", True)
        ),
        screen_capture_scope=str(
            screen_awareness_data.get("screen_capture_scope", "active_window")
        ).strip()
        or "active_window",
        screen_capture_ocr_enabled=bool(
            screen_awareness_data.get("screen_capture_ocr_enabled", True)
        ),
        screen_capture_provider_vision_enabled=bool(
            screen_awareness_data.get("screen_capture_provider_vision_enabled", False)
        ),
        screen_capture_store_raw_images=bool(
            screen_awareness_data.get("screen_capture_store_raw_images", False)
        ),
        browser_adapters=ScreenAwarenessBrowserAdaptersConfig(
            playwright=PlaywrightBrowserAdapterConfig(
                enabled=bool(screen_awareness_playwright_data.get("enabled", False)),
                provider=str(screen_awareness_playwright_data.get("provider", "playwright")).strip() or "playwright",
                mode=str(screen_awareness_playwright_data.get("mode", "semantic_observation")).strip() or "semantic_observation",
                allow_browser_launch=bool(screen_awareness_playwright_data.get("allow_browser_launch", False)),
                allow_connect_existing=bool(screen_awareness_playwright_data.get("allow_connect_existing", False)),
                allow_actions=bool(screen_awareness_playwright_data.get("allow_actions", False)),
                allow_click=bool(screen_awareness_playwright_data.get("allow_click", False)),
                allow_focus=bool(screen_awareness_playwright_data.get("allow_focus", False)),
                allow_type_text=bool(screen_awareness_playwright_data.get("allow_type_text", False)),
                allow_check=bool(screen_awareness_playwright_data.get("allow_check", False)),
                allow_uncheck=bool(screen_awareness_playwright_data.get("allow_uncheck", False)),
                allow_select_option=bool(screen_awareness_playwright_data.get("allow_select_option", False)),
                allow_scroll=bool(screen_awareness_playwright_data.get("allow_scroll", False)),
                allow_scroll_to_target=bool(screen_awareness_playwright_data.get("allow_scroll_to_target", False)),
                allow_task_plans=bool(screen_awareness_playwright_data.get("allow_task_plans", False)),
                allow_form_fill=bool(screen_awareness_playwright_data.get("allow_form_fill", False)),
                allow_form_submit=bool(screen_awareness_playwright_data.get("allow_form_submit", False)),
                allow_login=bool(screen_awareness_playwright_data.get("allow_login", False)),
                allow_cookies=bool(screen_awareness_playwright_data.get("allow_cookies", False)),
                allow_user_profile=bool(screen_awareness_playwright_data.get("allow_user_profile", False)),
                allow_payment=bool(screen_awareness_playwright_data.get("allow_payment", False)),
                allow_screenshots=bool(screen_awareness_playwright_data.get("allow_screenshots", False)),
                allow_dev_adapter=bool(screen_awareness_playwright_data.get("allow_dev_adapter", False)),
                allow_dev_actions=bool(screen_awareness_playwright_data.get("allow_dev_actions", False)),
                allow_dev_type_text=bool(screen_awareness_playwright_data.get("allow_dev_type_text", False)),
                allow_dev_choice_controls=bool(screen_awareness_playwright_data.get("allow_dev_choice_controls", False)),
                allow_dev_scroll=bool(screen_awareness_playwright_data.get("allow_dev_scroll", False)),
                allow_dev_task_plans=bool(screen_awareness_playwright_data.get("allow_dev_task_plans", False)),
                max_session_seconds=int(screen_awareness_playwright_data.get("max_session_seconds", 120)),
                navigation_timeout_seconds=int(screen_awareness_playwright_data.get("navigation_timeout_seconds", 12000)),
                observation_timeout_seconds=int(screen_awareness_playwright_data.get("observation_timeout_seconds", 8000)),
                max_scroll_attempts=int(screen_awareness_playwright_data.get("max_scroll_attempts", 5)),
                scroll_step_pixels=int(screen_awareness_playwright_data.get("scroll_step_pixels", 700)),
                scroll_timeout_seconds=float(screen_awareness_playwright_data.get("scroll_timeout_seconds", 8.0)),
                max_scroll_distance_pixels=int(screen_awareness_playwright_data.get("max_scroll_distance_pixels", 5000)),
                max_task_steps=int(screen_awareness_playwright_data.get("max_task_steps", 5)),
                stop_on_unverified_step=bool(screen_awareness_playwright_data.get("stop_on_unverified_step", True)),
                stop_on_partial_step=bool(screen_awareness_playwright_data.get("stop_on_partial_step", True)),
                stop_on_ambiguous_step=bool(screen_awareness_playwright_data.get("stop_on_ambiguous_step", True)),
                stop_on_unexpected_navigation=bool(screen_awareness_playwright_data.get("stop_on_unexpected_navigation", True)),
                debug_events_enabled=bool(screen_awareness_playwright_data.get("debug_events_enabled", True)),
            )
        ),
    )

    camera_awareness_data = data.get("camera_awareness", {})
    camera_capture_data = (
        camera_awareness_data.get("capture", {})
        if isinstance(camera_awareness_data.get("capture"), dict)
        else {}
    )
    camera_vision_data = (
        camera_awareness_data.get("vision", {})
        if isinstance(camera_awareness_data.get("vision"), dict)
        else {}
    )
    camera_privacy_data = (
        camera_awareness_data.get("privacy", {})
        if isinstance(camera_awareness_data.get("privacy"), dict)
        else {}
    )
    camera_dev_data = (
        camera_awareness_data.get("dev", {})
        if isinstance(camera_awareness_data.get("dev"), dict)
        else {}
    )
    camera_awareness_config = CameraAwarenessConfig(
        enabled=bool(camera_awareness_data.get("enabled", False)),
        planner_routing_enabled=bool(
            camera_awareness_data.get("planner_routing_enabled", True)
        ),
        debug_events_enabled=bool(
            camera_awareness_data.get("debug_events_enabled", True)
        ),
        default_capture_mode=str(
            camera_awareness_data.get("default_capture_mode", "single_still")
        ).strip()
        or "single_still",
        default_storage_mode=str(
            camera_awareness_data.get("default_storage_mode", "ephemeral")
        ).strip()
        or "ephemeral",
        auto_discard_after_seconds=int(
            camera_awareness_data.get("auto_discard_after_seconds", 300)
        ),
        allow_cloud_vision=bool(
            camera_awareness_data.get("allow_cloud_vision", False)
        ),
        allow_background_capture=bool(
            camera_awareness_data.get("allow_background_capture", False)
        ),
        allow_task_artifact_save=bool(
            camera_awareness_data.get("allow_task_artifact_save", False)
        ),
        allow_session_permission=bool(
            camera_awareness_data.get("allow_session_permission", False)
        ),
        capture=CameraAwarenessCaptureConfig(
            provider=str(camera_capture_data.get("provider", "mock")).strip().lower()
            or "mock",
            mode=str(camera_capture_data.get("mode", "single_still")).strip()
            or "single_still",
            default_device_id=str(
                camera_capture_data.get("default_device_id", "")
            ).strip()
            or None,
            requested_resolution=str(
                camera_capture_data.get("requested_resolution", "1280x720")
            ).strip()
            or "1280x720",
            timeout_seconds=float(camera_capture_data.get("timeout_seconds", 5.0)),
            max_artifact_bytes=int(
                camera_capture_data.get("max_artifact_bytes", 10485760)
            ),
        ),
        vision=CameraAwarenessVisionConfig(
            provider=str(camera_vision_data.get("provider", "mock")).strip().lower()
            or "mock",
            model=str(camera_vision_data.get("model", "mock-vision")).strip()
            or "mock-vision",
            timeout_seconds=float(camera_vision_data.get("timeout_seconds", 10.0)),
            detail=str(camera_vision_data.get("detail", "auto")).strip().lower()
            or "auto",
            max_image_bytes=int(camera_vision_data.get("max_image_bytes", 8_000_000)),
            request_timeout_ms=int(
                camera_vision_data.get("request_timeout_ms", 30_000)
            ),
            allow_cloud_vision=bool(
                camera_vision_data.get("allow_cloud_vision", False)
            ),
            require_confirmation_for_cloud=bool(
                camera_vision_data.get("require_confirmation_for_cloud", True)
            ),
        ),
        privacy=CameraAwarenessPrivacyConfig(
            confirm_before_capture=bool(
                camera_privacy_data.get("confirm_before_capture", True)
            ),
            persist_images_by_default=bool(
                camera_privacy_data.get("persist_images_by_default", False)
            ),
            require_source_provenance=bool(
                camera_privacy_data.get("require_source_provenance", True)
            ),
            redact_raw_image_from_events=bool(
                camera_privacy_data.get("redact_raw_image_from_events", True)
            ),
        ),
        dev=CameraAwarenessDevConfig(
            mock_capture_enabled=bool(
                camera_dev_data.get("mock_capture_enabled", True)
            ),
            mock_vision_enabled=bool(
                camera_dev_data.get("mock_vision_enabled", True)
            ),
            mock_image_fixture=str(
                camera_dev_data.get("mock_image_fixture", "resistor")
            ).strip()
            or "resistor",
            save_debug_images=bool(camera_dev_data.get("save_debug_images", False)),
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

    web_retrieval_data = data.get("web_retrieval", {})
    web_retrieval_http_data = (
        web_retrieval_data.get("http", {})
        if isinstance(web_retrieval_data.get("http"), dict)
        else {}
    )
    web_retrieval_obscura_data = (
        web_retrieval_data.get("obscura", {})
        if isinstance(web_retrieval_data.get("obscura"), dict)
        else {}
    )
    web_retrieval_obscura_cdp_data = (
        web_retrieval_obscura_data.get("cdp", {})
        if isinstance(web_retrieval_obscura_data.get("cdp"), dict)
        else {}
    )
    web_retrieval_chromium_data = (
        web_retrieval_data.get("chromium", {})
        if isinstance(web_retrieval_data.get("chromium"), dict)
        else {}
    )
    web_retrieval_config = WebRetrievalConfig(
        enabled=bool(web_retrieval_data.get("enabled", True)),
        planner_routing_enabled=bool(
            web_retrieval_data.get("planner_routing_enabled", True)
        ),
        debug_events_enabled=bool(
            web_retrieval_data.get("debug_events_enabled", True)
        ),
        default_provider=str(
            web_retrieval_data.get("default_provider", "auto")
        ).strip().lower()
        or "auto",
        max_url_count=int(web_retrieval_data.get("max_url_count", 8)),
        max_url_chars=int(web_retrieval_data.get("max_url_chars", 4096)),
        max_parallel_pages=int(web_retrieval_data.get("max_parallel_pages", 3)),
        timeout_seconds=float(web_retrieval_data.get("timeout_seconds", 12.0)),
        max_text_chars=int(web_retrieval_data.get("max_text_chars", 60000)),
        max_html_chars=int(web_retrieval_data.get("max_html_chars", 250000)),
        cache_snapshots=bool(web_retrieval_data.get("cache_snapshots", True)),
        respect_robots=bool(web_retrieval_data.get("respect_robots", True)),
        allow_private_network_urls=bool(
            web_retrieval_data.get("allow_private_network_urls", False)
        ),
        allow_file_urls=bool(web_retrieval_data.get("allow_file_urls", False)),
        allow_logged_in_context=bool(
            web_retrieval_data.get("allow_logged_in_context", False)
        ),
        http=WebRetrievalHttpConfig(
            enabled=bool(web_retrieval_http_data.get("enabled", True)),
            timeout_seconds=float(
                web_retrieval_http_data.get("timeout_seconds", 8.0)
            ),
        ),
        obscura=WebRetrievalObscuraConfig(
            enabled=bool(web_retrieval_obscura_data.get("enabled", False)),
            binary_path=str(
                web_retrieval_obscura_data.get("binary_path", "obscura")
            ).strip()
            or "obscura",
            mode=str(web_retrieval_obscura_data.get("mode", "cli")).strip().lower()
            or "cli",
            allow_cdp_server=bool(
                web_retrieval_obscura_data.get("allow_cdp_server", False)
            ),
            serve_port=int(web_retrieval_obscura_data.get("serve_port", 9222)),
            stealth_enabled=bool(
                web_retrieval_obscura_data.get("stealth_enabled", False)
            ),
            obey_robots=bool(web_retrieval_obscura_data.get("obey_robots", True)),
            workers=int(web_retrieval_obscura_data.get("workers", 1)),
            max_concurrency=int(
                web_retrieval_obscura_data.get("max_concurrency", 3)
            ),
            wait_until=str(
                web_retrieval_obscura_data.get("wait_until", "networkidle0")
            ).strip()
            or "networkidle0",
            dump_format=str(
                web_retrieval_obscura_data.get("dump_format", "text")
            ).strip().lower()
            or "text",
            allow_js_eval=bool(
                web_retrieval_obscura_data.get("allow_js_eval", False)
            ),
            max_eval_chars=int(web_retrieval_obscura_data.get("max_eval_chars", 2000)),
            cdp=WebRetrievalObscuraCDPConfig(
                enabled=bool(web_retrieval_obscura_cdp_data.get("enabled", False)),
                binary_path=str(
                    web_retrieval_obscura_cdp_data.get(
                        "binary_path",
                        web_retrieval_obscura_data.get("binary_path", "obscura"),
                    )
                ).strip()
                or "obscura",
                host=str(web_retrieval_obscura_cdp_data.get("host", "127.0.0.1")).strip()
                or "127.0.0.1",
                port=int(web_retrieval_obscura_cdp_data.get("port", 0)),
                startup_timeout_seconds=float(
                    web_retrieval_obscura_cdp_data.get("startup_timeout_seconds", 8.0)
                ),
                shutdown_timeout_seconds=float(
                    web_retrieval_obscura_cdp_data.get("shutdown_timeout_seconds", 4.0)
                ),
                navigation_timeout_seconds=float(
                    web_retrieval_obscura_cdp_data.get("navigation_timeout_seconds", 12.0)
                ),
                max_session_seconds=float(
                    web_retrieval_obscura_cdp_data.get("max_session_seconds", 120.0)
                ),
                max_pages_per_session=int(
                    web_retrieval_obscura_cdp_data.get("max_pages_per_session", 8)
                ),
                max_dom_text_chars=int(
                    web_retrieval_obscura_cdp_data.get("max_dom_text_chars", 60000)
                ),
                max_html_chars=int(
                    web_retrieval_obscura_cdp_data.get("max_html_chars", 250000)
                ),
                max_links=int(web_retrieval_obscura_cdp_data.get("max_links", 500)),
                allow_runtime_eval=bool(
                    web_retrieval_obscura_cdp_data.get("allow_runtime_eval", False)
                ),
                allow_input_domain=bool(
                    web_retrieval_obscura_cdp_data.get("allow_input_domain", False)
                ),
                allow_cookies=bool(
                    web_retrieval_obscura_cdp_data.get("allow_cookies", False)
                ),
                allow_logged_in_context=bool(
                    web_retrieval_obscura_cdp_data.get("allow_logged_in_context", False)
                ),
                allow_screenshots=bool(
                    web_retrieval_obscura_cdp_data.get("allow_screenshots", False)
                ),
                debug_events_enabled=bool(
                    web_retrieval_obscura_cdp_data.get("debug_events_enabled", True)
                ),
            ),
        ),
        chromium=WebRetrievalChromiumConfig(
            enabled=bool(web_retrieval_chromium_data.get("enabled", False)),
            fallback_enabled=bool(
                web_retrieval_chromium_data.get("fallback_enabled", True)
            ),
        ),
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

    provider_fallback_data = data.get("provider_fallback", {})
    provider_fallback_config = ProviderFallbackConfig(
        enabled=bool(provider_fallback_data.get("enabled", False)),
        allow_streaming=bool(provider_fallback_data.get("allow_streaming", True)),
        allow_partial_progress=bool(
            provider_fallback_data.get("allow_partial_progress", True)
        ),
        allow_cancellation=bool(
            provider_fallback_data.get("allow_cancellation", True)
        ),
        target_first_output_ms=float(
            provider_fallback_data.get("target_first_output_ms", 1500)
        ),
        soft_first_output_ms=float(
            provider_fallback_data.get("soft_first_output_ms", 3000)
        ),
        hard_first_output_ms=float(
            provider_fallback_data.get("hard_first_output_ms", 6000)
        ),
        target_total_ms=float(provider_fallback_data.get("target_total_ms", 4000)),
        soft_total_ms=float(provider_fallback_data.get("soft_total_ms", 8000)),
        hard_total_ms=float(provider_fallback_data.get("hard_total_ms", 12000)),
        allow_for_native_routes=bool(
            provider_fallback_data.get("allow_for_native_routes", False)
        ),
        allow_speculative_provider_calls=bool(
            provider_fallback_data.get("allow_speculative_provider_calls", False)
        ),
        log_prompt_payloads=bool(
            provider_fallback_data.get("log_prompt_payloads", False)
        ),
        audit_timing=bool(provider_fallback_data.get("audit_timing", True)),
        surface_partial_in_ghost=bool(
            provider_fallback_data.get("surface_partial_in_ghost", True)
        ),
        surface_details_in_deck=bool(
            provider_fallback_data.get("surface_details_in_deck", True)
        ),
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
    voice_visual_sync_data = (
        voice_data.get("visual_sync", {})
        if isinstance(voice_data.get("visual_sync"), dict)
        else {}
    )
    voice_visual_meter_data = (
        voice_data.get("visual_meter", {})
        if isinstance(voice_data.get("visual_meter"), dict)
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
            tts_voice=str(voice_openai_data.get("tts_voice", "onyx")).strip()
            or "onyx",
            tts_format=str(voice_openai_data.get("tts_format", "mp3")).strip().lower()
            or "mp3",
            stream_tts_outputs=bool(
                voice_openai_data.get("stream_tts_outputs", False)
            ),
            tts_live_format=str(
                voice_openai_data.get("tts_live_format", "pcm")
            ).strip().lower()
            or "pcm",
            tts_artifact_format=str(
                voice_openai_data.get("tts_artifact_format", "mp3")
            ).strip().lower()
            or "mp3",
            streaming_fallback_to_buffered=bool(
                voice_openai_data.get("streaming_fallback_to_buffered", True)
            ),
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
            streaming_enabled=bool(
                voice_playback_data.get("streaming_enabled", False)
            ),
            streaming_fallback_to_file=bool(
                voice_playback_data.get("streaming_fallback_to_file", True)
            ),
            prewarm_enabled=bool(voice_playback_data.get("prewarm_enabled", True)),
            streaming_min_preroll_ms=int(
                voice_playback_data.get("streaming_min_preroll_ms", 350)
            ),
            streaming_min_preroll_chunks=int(
                voice_playback_data.get("streaming_min_preroll_chunks", 2)
            ),
            streaming_min_preroll_bytes=int(
                voice_playback_data.get("streaming_min_preroll_bytes", 0)
            ),
            streaming_max_preroll_wait_ms=int(
                voice_playback_data.get("streaming_max_preroll_wait_ms", 1200)
            ),
            playback_stable_after_ms=int(
                voice_playback_data.get("playback_stable_after_ms", 180)
            ),
            streaming_jitter_buffer_ms=int(
                voice_playback_data.get("streaming_jitter_buffer_ms", 120)
            ),
            streaming_min_buffer_ms=int(
                voice_playback_data.get("streaming_min_buffer_ms", 80)
            ),
            streaming_max_buffer_ms=int(
                voice_playback_data.get("streaming_max_buffer_ms", 400)
            ),
            streaming_underrun_recovery=str(
                voice_playback_data.get(
                    "streaming_underrun_recovery",
                    "hold_or_silence",
                )
            ).strip()
            or "hold_or_silence",
            max_audio_bytes=int(voice_playback_data.get("max_audio_bytes", 10_000_000)),
            max_duration_ms=int(voice_playback_data.get("max_duration_ms", 120_000)),
            delete_transient_after_playback=bool(
                voice_playback_data.get("delete_transient_after_playback", True)
            ),
        ),
        visual_sync=VoiceVisualSyncConfig(
            enabled=voice_visual_sync_data.get("enabled", True),
            envelope_visual_offset_ms=voice_visual_sync_data.get(
                "envelope_visual_offset_ms", 0
            ),
            estimated_output_latency_ms=voice_visual_sync_data.get(
                "estimated_output_latency_ms", 120
            ),
            debug_show_sync=voice_visual_sync_data.get("debug_show_sync", False),
        ),
        visual_meter=VoiceVisualMeterConfig(
            enabled=voice_visual_meter_data.get("enabled", True),
            sample_rate_hz=voice_visual_meter_data.get("sample_rate_hz", 60),
            startup_preroll_ms=voice_visual_meter_data.get(
                "startup_preroll_ms", 350
            ),
            attack_ms=voice_visual_meter_data.get("attack_ms", 60),
            release_ms=voice_visual_meter_data.get("release_ms", 160),
            noise_floor=voice_visual_meter_data.get("noise_floor", 0.015),
            gain=voice_visual_meter_data.get("gain", 2.0),
            max_startup_wait_ms=voice_visual_meter_data.get(
                "max_startup_wait_ms", 800
            ),
            visual_offset_ms=voice_visual_meter_data.get("visual_offset_ms", 0),
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
            web_retrieval_fetch=bool(
                enabled_data.get("web_retrieval_fetch", True)
            ),
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
        camera_awareness=camera_awareness_config,
        calculations=calculations_config,
        software_control=software_control_config,
        software_recovery=software_recovery_config,
        trust=trust_config,
        web_retrieval=web_retrieval_config,
        discord_relay=discord_relay_config,
        openai=openai_config,
        provider_fallback=provider_fallback_config,
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
        "STORMHELM_UI_VARIANT": ("ui.visual_variant", str),
        "STORMHELM_STORMFORGE_FOG": (
            "ui.stormforge.fog.enabled",
            _parse_bool,
        ),
        "STORMHELM_STORMFORGE_FOG_QUALITY": (
            "ui.stormforge.fog.quality",
            str,
        ),
        "STORMHELM_STORMFORGE_FOG_DEBUG_VISIBLE": (
            "ui.stormforge.fog.debug_visible",
            _parse_bool,
        ),
        "STORMHELM_STORMFORGE_FOG_DIAGNOSTIC_DISABLE_DURING_SPEECH": (
            "ui.stormforge.fog.diagnostic_disable_during_speech",
            _parse_bool,
        ),
        "STORMHELM_ANCHOR_VISUALIZER_MODE": (
            "ui.stormforge.voice_diagnostics.anchor_visualizer_mode",
            str,
        ),
        "STORMHELM_STORMFORGE_ANCHOR_RENDERER": (
            "ui.stormforge.voice_diagnostics.anchor_renderer",
            str,
        ),
        "STORMHELM_STORMFORGE_QSG_VISUAL_APPROVAL": (
            "ui.stormforge.voice_diagnostics.qsg_visual_approval",
            str,
        ),
        "STORMHELM_STORMFORGE_QSG_VISUAL_APPROVAL_REASON": (
            "ui.stormforge.voice_diagnostics.qsg_visual_approval_reason",
            str,
        ),
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
        "STORMHELM_CAMERA_AWARENESS_ENABLED": (
            "camera_awareness.enabled",
            _parse_bool,
        ),
        "STORMHELM_CAMERA_AWARENESS_PLANNER_ROUTING_ENABLED": (
            "camera_awareness.planner_routing_enabled",
            _parse_bool,
        ),
        "STORMHELM_CAMERA_AWARENESS_ALLOW_CLOUD_VISION": (
            "camera_awareness.allow_cloud_vision",
            _parse_bool,
        ),
        "STORMHELM_CAMERA_AWARENESS_ALLOW_BACKGROUND_CAPTURE": (
            "camera_awareness.allow_background_capture",
            _parse_bool,
        ),
        "STORMHELM_CAMERA_AWARENESS_CAPTURE_PROVIDER": (
            "camera_awareness.capture.provider",
            str,
        ),
        "STORMHELM_CAMERA_AWARENESS_VISION_PROVIDER": (
            "camera_awareness.vision.provider",
            str,
        ),
        "STORMHELM_CAMERA_AWARENESS_VISION_MODEL": (
            "camera_awareness.vision.model",
            str,
        ),
        "STORMHELM_CAMERA_AWARENESS_VISION_DETAIL": (
            "camera_awareness.vision.detail",
            str,
        ),
        "STORMHELM_CAMERA_AWARENESS_VISION_MAX_IMAGE_BYTES": (
            "camera_awareness.vision.max_image_bytes",
            int,
        ),
        "STORMHELM_CAMERA_AWARENESS_VISION_REQUIRE_CONFIRMATION_FOR_CLOUD": (
            "camera_awareness.vision.require_confirmation_for_cloud",
            _parse_bool,
        ),
        "STORMHELM_CAMERA_AWARENESS_VISION_ALLOW_CLOUD": (
            "camera_awareness.vision.allow_cloud_vision",
            _parse_bool,
        ),
        "STORMHELM_WEB_RETRIEVAL_ENABLED": (
            "web_retrieval.enabled",
            _parse_bool,
        ),
        "STORMHELM_WEB_RETRIEVAL_PLANNER_ROUTING_ENABLED": (
            "web_retrieval.planner_routing_enabled",
            _parse_bool,
        ),
        "STORMHELM_WEB_RETRIEVAL_DEBUG_EVENTS_ENABLED": (
            "web_retrieval.debug_events_enabled",
            _parse_bool,
        ),
        "STORMHELM_WEB_RETRIEVAL_DEFAULT_PROVIDER": (
            "web_retrieval.default_provider",
            str,
        ),
        "STORMHELM_WEB_RETRIEVAL_MAX_URL_COUNT": (
            "web_retrieval.max_url_count",
            int,
        ),
        "STORMHELM_WEB_RETRIEVAL_MAX_URL_CHARS": (
            "web_retrieval.max_url_chars",
            int,
        ),
        "STORMHELM_WEB_RETRIEVAL_MAX_PARALLEL_PAGES": (
            "web_retrieval.max_parallel_pages",
            int,
        ),
        "STORMHELM_WEB_RETRIEVAL_TIMEOUT_SECONDS": (
            "web_retrieval.timeout_seconds",
            float,
        ),
        "STORMHELM_WEB_RETRIEVAL_MAX_TEXT_CHARS": (
            "web_retrieval.max_text_chars",
            int,
        ),
        "STORMHELM_WEB_RETRIEVAL_MAX_HTML_CHARS": (
            "web_retrieval.max_html_chars",
            int,
        ),
        "STORMHELM_WEB_RETRIEVAL_ALLOW_PRIVATE_NETWORK_URLS": (
            "web_retrieval.allow_private_network_urls",
            _parse_bool,
        ),
        "STORMHELM_WEB_RETRIEVAL_HTTP_ENABLED": (
            "web_retrieval.http.enabled",
            _parse_bool,
        ),
        "STORMHELM_WEB_RETRIEVAL_HTTP_TIMEOUT_SECONDS": (
            "web_retrieval.http.timeout_seconds",
            float,
        ),
        "STORMHELM_OBSCURA_ENABLED": (
            "web_retrieval.obscura.enabled",
            _parse_bool,
        ),
        "STORMHELM_OBSCURA_BINARY_PATH": (
            "web_retrieval.obscura.binary_path",
            str,
        ),
        "STORMHELM_OBSCURA_MAX_CONCURRENCY": (
            "web_retrieval.obscura.max_concurrency",
            int,
        ),
        "STORMHELM_OBSCURA_CDP_ENABLED": (
            "web_retrieval.obscura.cdp.enabled",
            _parse_bool,
        ),
        "STORMHELM_OBSCURA_CDP_BINARY_PATH": (
            "web_retrieval.obscura.cdp.binary_path",
            str,
        ),
        "STORMHELM_OBSCURA_CDP_HOST": (
            "web_retrieval.obscura.cdp.host",
            str,
        ),
        "STORMHELM_OBSCURA_CDP_PORT": (
            "web_retrieval.obscura.cdp.port",
            int,
        ),
        "STORMHELM_OBSCURA_CDP_MAX_PAGES_PER_SESSION": (
            "web_retrieval.obscura.cdp.max_pages_per_session",
            int,
        ),
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
        "STORMHELM_VOICE_SPEAK_TYPED_RESPONSES": (
            "voice.spoken_responses_enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_MANUAL_INPUT_ENABLED": (
            "voice.manual_input_enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_PUSH_TO_TALK_ENABLED": (
            "voice.manual_input_enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_REALTIME_ENABLED": ("voice.realtime_enabled", _parse_bool),
        "STORMHELM_VOICE_DEBUG_MOCK_PROVIDER": (
            "voice.debug_mock_provider",
            _parse_bool,
        ),
        "STORMHELM_VOICE_INPUT_PROVIDER": ("voice.provider", str),
        "STORMHELM_VOICE_STT_PROVIDER": ("voice.provider", str),
        "STORMHELM_VOICE_INPUT_ENABLED": ("voice.capture.enabled", _parse_bool),
        "STORMHELM_VOICE_MICROPHONE_ENABLED": (
            "voice.capture.enabled",
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
        "STORMHELM_VOICE_PLAYBACK_STREAMING_ENABLED": (
            "voice.playback.streaming_enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_PLAYBACK_STREAMING_FALLBACK_TO_FILE": (
            "voice.playback.streaming_fallback_to_file",
            _parse_bool,
        ),
        "STORMHELM_VOICE_PLAYBACK_PREWARM_ENABLED": (
            "voice.playback.prewarm_enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_PLAYBACK_STREAMING_MIN_PREROLL_MS": (
            "voice.playback.streaming_min_preroll_ms",
            int,
        ),
        "STORMHELM_VOICE_PLAYBACK_STREAMING_MIN_PREROLL_CHUNKS": (
            "voice.playback.streaming_min_preroll_chunks",
            int,
        ),
        "STORMHELM_VOICE_PLAYBACK_STREAMING_MIN_PREROLL_BYTES": (
            "voice.playback.streaming_min_preroll_bytes",
            int,
        ),
        "STORMHELM_VOICE_PLAYBACK_STREAMING_MAX_PREROLL_WAIT_MS": (
            "voice.playback.streaming_max_preroll_wait_ms",
            int,
        ),
        "STORMHELM_VOICE_PLAYBACK_STABLE_AFTER_MS": (
            "voice.playback.playback_stable_after_ms",
            int,
        ),
        "STORMHELM_VOICE_PLAYBACK_STREAMING_JITTER_BUFFER_MS": (
            "voice.playback.streaming_jitter_buffer_ms",
            int,
        ),
        "STORMHELM_VOICE_PLAYBACK_STREAMING_MIN_BUFFER_MS": (
            "voice.playback.streaming_min_buffer_ms",
            int,
        ),
        "STORMHELM_VOICE_PLAYBACK_STREAMING_MAX_BUFFER_MS": (
            "voice.playback.streaming_max_buffer_ms",
            int,
        ),
        "STORMHELM_VOICE_PLAYBACK_STREAMING_UNDERRUN_RECOVERY": (
            "voice.playback.streaming_underrun_recovery",
            str,
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
        "STORMHELM_VOICE_VISUAL_SYNC_ENABLED": (
            "voice.visual_sync.enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_VISUAL_OFFSET_MS": (
            "voice.visual_sync.envelope_visual_offset_ms",
            int,
        ),
        "STORMHELM_VOICE_VISUAL_SYNC_OFFSET_MS": (
            "voice.visual_sync.envelope_visual_offset_ms",
            int,
        ),
        "STORMHELM_VOICE_VISUAL_ESTIMATED_OUTPUT_LATENCY_MS": (
            "voice.visual_sync.estimated_output_latency_ms",
            int,
        ),
        "STORMHELM_VOICE_ESTIMATED_OUTPUT_LATENCY_MS": (
            "voice.visual_sync.estimated_output_latency_ms",
            int,
        ),
        "STORMHELM_VOICE_VISUAL_SYNC_DEBUG": (
            "voice.visual_sync.debug_show_sync",
            _parse_bool,
        ),
        "STORMHELM_VOICE_VISUAL_METER_ENABLED": (
            "voice.visual_meter.enabled",
            _parse_bool,
        ),
        "STORMHELM_VOICE_VISUAL_METER_SAMPLE_RATE_HZ": (
            "voice.visual_meter.sample_rate_hz",
            int,
        ),
        "STORMHELM_VOICE_VISUAL_METER_STARTUP_PREROLL_MS": (
            "voice.visual_meter.startup_preroll_ms",
            int,
        ),
        "STORMHELM_VOICE_VISUAL_METER_ATTACK_MS": (
            "voice.visual_meter.attack_ms",
            int,
        ),
        "STORMHELM_VOICE_VISUAL_METER_RELEASE_MS": (
            "voice.visual_meter.release_ms",
            int,
        ),
        "STORMHELM_VOICE_VISUAL_METER_NOISE_FLOOR": (
            "voice.visual_meter.noise_floor",
            float,
        ),
        "STORMHELM_VOICE_VISUAL_METER_GAIN": (
            "voice.visual_meter.gain",
            float,
        ),
        "STORMHELM_VOICE_VISUAL_METER_MAX_STARTUP_WAIT_MS": (
            "voice.visual_meter.max_startup_wait_ms",
            int,
        ),
        "STORMHELM_VOICE_VISUAL_METER_OFFSET_MS": (
            "voice.visual_meter.visual_offset_ms",
            int,
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
        "STORMHELM_VOICE_ENDPOINT_SILENCE_MS": ("voice.vad.silence_ms", int),
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
        "STORMHELM_VOICE_STT_MODEL": ("voice.openai.stt_model", str),
        "STORMHELM_VOICE_OPENAI_TRANSCRIPTION_LANGUAGE": (
            "voice.openai.transcription_language",
            str,
        ),
        "STORMHELM_VOICE_INPUT_LANGUAGE": (
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
        "STORMHELM_VOICE_OPENAI_STREAM_TTS_OUTPUTS": (
            "voice.openai.stream_tts_outputs",
            _parse_bool,
        ),
        "STORMHELM_VOICE_OPENAI_TTS_LIVE_FORMAT": (
            "voice.openai.tts_live_format",
            str,
        ),
        "STORMHELM_VOICE_OPENAI_TTS_ARTIFACT_FORMAT": (
            "voice.openai.tts_artifact_format",
            str,
        ),
        "STORMHELM_VOICE_OPENAI_STREAMING_FALLBACK_TO_BUFFERED": (
            "voice.openai.streaming_fallback_to_buffered",
            _parse_bool,
        ),
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
        "STORMHELM_SCREEN_AWARENESS_SCREEN_CAPTURE_ENABLED": (
            "screen_awareness.screen_capture_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_CAPTURE_ENABLED": (
            "screen_awareness.screen_capture_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_SCREEN_CAPTURE_SCOPE": (
            "screen_awareness.screen_capture_scope",
            str,
        ),
        "STORMHELM_SCREEN_CAPTURE_SCOPE": (
            "screen_awareness.screen_capture_scope",
            str,
        ),
        "STORMHELM_SCREEN_AWARENESS_SCREEN_CAPTURE_OCR_ENABLED": (
            "screen_awareness.screen_capture_ocr_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_CAPTURE_OCR_ENABLED": (
            "screen_awareness.screen_capture_ocr_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PROVIDER_VISION_ENABLED": (
            "screen_awareness.screen_capture_provider_vision_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_CAPTURE_PROVIDER_VISION_ENABLED": (
            "screen_awareness.screen_capture_provider_vision_enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_STORE_RAW_IMAGES": (
            "screen_awareness.screen_capture_store_raw_images",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_CAPTURE_STORE_RAW_IMAGES": (
            "screen_awareness.screen_capture_store_raw_images",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ENABLED": (
            "screen_awareness.browser_adapters.playwright.enabled",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_ACTIONS": (
            "screen_awareness.browser_adapters.playwright.allow_actions",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_CLICK": (
            "screen_awareness.browser_adapters.playwright.allow_click",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_FOCUS": (
            "screen_awareness.browser_adapters.playwright.allow_focus",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_TYPE_TEXT": (
            "screen_awareness.browser_adapters.playwright.allow_type_text",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_CHECK": (
            "screen_awareness.browser_adapters.playwright.allow_check",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_UNCHECK": (
            "screen_awareness.browser_adapters.playwright.allow_uncheck",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SELECT_OPTION": (
            "screen_awareness.browser_adapters.playwright.allow_select_option",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_TYPE_TEXT": (
            "screen_awareness.browser_adapters.playwright.allow_dev_type_text",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_CHOICE_CONTROLS": (
            "screen_awareness.browser_adapters.playwright.allow_dev_choice_controls",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SCROLL": (
            "screen_awareness.browser_adapters.playwright.allow_scroll",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SCROLL_TO_TARGET": (
            "screen_awareness.browser_adapters.playwright.allow_scroll_to_target",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_TASK_PLANS": (
            "screen_awareness.browser_adapters.playwright.allow_task_plans",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_SCROLL": (
            "screen_awareness.browser_adapters.playwright.allow_dev_scroll",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_TASK_PLANS": (
            "screen_awareness.browser_adapters.playwright.allow_dev_task_plans",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_MAX_SCROLL_ATTEMPTS": (
            "screen_awareness.browser_adapters.playwright.max_scroll_attempts",
            int,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_SCROLL_STEP_PIXELS": (
            "screen_awareness.browser_adapters.playwright.scroll_step_pixels",
            int,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_SCROLL_TIMEOUT_SECONDS": (
            "screen_awareness.browser_adapters.playwright.scroll_timeout_seconds",
            float,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_MAX_SCROLL_DISTANCE_PIXELS": (
            "screen_awareness.browser_adapters.playwright.max_scroll_distance_pixels",
            int,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_MAX_TASK_STEPS": (
            "screen_awareness.browser_adapters.playwright.max_task_steps",
            int,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_UNVERIFIED_STEP": (
            "screen_awareness.browser_adapters.playwright.stop_on_unverified_step",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_PARTIAL_STEP": (
            "screen_awareness.browser_adapters.playwright.stop_on_partial_step",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_AMBIGUOUS_STEP": (
            "screen_awareness.browser_adapters.playwright.stop_on_ambiguous_step",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_UNEXPECTED_NAVIGATION": (
            "screen_awareness.browser_adapters.playwright.stop_on_unexpected_navigation",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_ACTIONS": (
            "screen_awareness.browser_adapters.playwright.allow_dev_actions",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH": (
            "screen_awareness.browser_adapters.playwright.allow_browser_launch",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_CONNECT_EXISTING": (
            "screen_awareness.browser_adapters.playwright.allow_connect_existing",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_ADAPTER": (
            "screen_awareness.browser_adapters.playwright.allow_dev_adapter",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_FORM_FILL": (
            "screen_awareness.browser_adapters.playwright.allow_form_fill",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_FORM_SUBMIT": (
            "screen_awareness.browser_adapters.playwright.allow_form_submit",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_LOGIN": (
            "screen_awareness.browser_adapters.playwright.allow_login",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_COOKIES": (
            "screen_awareness.browser_adapters.playwright.allow_cookies",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_USER_PROFILE": (
            "screen_awareness.browser_adapters.playwright.allow_user_profile",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_PAYMENT": (
            "screen_awareness.browser_adapters.playwright.allow_payment",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SCREENSHOTS": (
            "screen_awareness.browser_adapters.playwright.allow_screenshots",
            _parse_bool,
        ),
        "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_DEBUG_EVENTS_ENABLED": (
            "screen_awareness.browser_adapters.playwright.debug_events_enabled",
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

    max_utterance_seconds = env.get("STORMHELM_VOICE_MAX_UTTERANCE_SECONDS")
    if max_utterance_seconds not in {None, ""}:
        max_utterance_ms = _parse_seconds_to_ms(str(max_utterance_seconds))
        _set_nested_value(merged, "voice.capture.max_duration_ms", max_utterance_ms)
        _set_nested_value(merged, "voice.vad.max_utterance_ms", max_utterance_ms)
        _set_nested_value(
            merged, "voice.openai.max_audio_seconds", float(max_utterance_ms) / 1000.0
        )
    if _parse_bool(str(env.get("STORMHELM_VOICE_MICROPHONE_ENABLED") or "")):
        _set_nested_value(merged, "voice.capture.enabled", True)
        _set_nested_value(merged, "voice.capture.allow_dev_capture", True)

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


def _normalize_ui_visual_variant(raw: Any) -> str:
    requested = str(raw or DEFAULT_UI_VISUAL_VARIANT).strip().lower()
    if requested in VALID_UI_VISUAL_VARIANTS:
        return requested
    _LOGGER.warning(
        "Unknown Stormhelm UI visual variant '%s'; falling back to '%s'. Valid variants: %s.",
        raw,
        DEFAULT_UI_VISUAL_VARIANT,
        ", ".join(sorted(VALID_UI_VISUAL_VARIANTS)),
    )
    return DEFAULT_UI_VISUAL_VARIANT


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _coerce_config_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(raw)


def _parse_seconds_to_ms(raw: str) -> int:
    try:
        seconds = float(str(raw).strip())
    except (TypeError, ValueError):
        seconds = 0.0
    return max(1, int(seconds * 1000))


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
