from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class NetworkConfig:
    host: str
    port: int


@dataclass(slots=True)
class StorageConfig:
    data_dir: Path
    database_path: Path
    logs_dir: Path
    state_dir: Path
    cache_dir: Path


@dataclass(slots=True)
class LoggingConfig:
    level: str
    file_name: str
    max_file_bytes: int
    backup_count: int


@dataclass(slots=True)
class ConcurrencyConfig:
    max_workers: int
    queue_size: int
    default_job_timeout_seconds: float
    history_limit: int


@dataclass(slots=True)
class StormforgeFogConfig:
    enabled: bool = False
    mode: str = "volumetric"
    quality: str = "medium"
    intensity: float = 0.35
    motion: bool = True
    edge_fog: bool = True
    foreground_wisps: bool = True
    max_foreground_opacity: float = 0.08
    center_clear_strength: float = 0.65
    lower_bias: float = 0.45
    drift_speed: float = 0.055
    drift_direction: str = "right_to_left"
    flow_scale: float = 1.0
    crosswind_wobble: float = 0.18
    rolling_speed: float = 0.035
    wisp_stretch: float = 1.8
    card_clear_strength: float = 0.72
    anchor_clear_radius: float = 0.18
    debug_visible: bool = False
    debug_intensity_multiplier: float = 3.0
    debug_tint: bool = True
    diagnostic_disable_during_speech: bool = False

    def __post_init__(self) -> None:
        mode = str(self.mode or "volumetric").strip().lower()
        self.mode = mode if mode in {"volumetric", "fallback"} else "volumetric"

        quality = str(self.quality or "medium").strip().lower()
        self.quality = quality if quality in {"off", "low", "medium", "high"} else "medium"

        try:
            intensity = float(self.intensity)
        except (TypeError, ValueError):
            intensity = 0.35
        self.intensity = min(1.0, max(0.0, intensity))

        self.enabled = bool(self.enabled)
        self.motion = bool(self.motion)
        self.edge_fog = bool(self.edge_fog)
        self.foreground_wisps = bool(self.foreground_wisps)
        self.max_foreground_opacity = self._clamped_float(
            self.max_foreground_opacity,
            default=0.08,
            minimum=0.0,
            maximum=0.16,
        )
        self.center_clear_strength = self._clamped_float(
            self.center_clear_strength,
            default=0.65,
            minimum=0.0,
            maximum=1.0,
        )
        self.lower_bias = self._clamped_float(
            self.lower_bias,
            default=0.45,
            minimum=0.0,
            maximum=1.0,
        )
        self.drift_speed = self._clamped_float(
            self.drift_speed,
            default=0.055,
            minimum=0.01,
            maximum=0.12,
        )
        direction = str(self.drift_direction or "right_to_left").strip().lower()
        self.drift_direction = (
            direction
            if direction in {"right_to_left", "left_to_right", "still"}
            else "right_to_left"
        )
        self.flow_scale = self._clamped_float(
            self.flow_scale,
            default=1.0,
            minimum=0.2,
            maximum=2.0,
        )
        self.crosswind_wobble = self._clamped_float(
            self.crosswind_wobble,
            default=0.18,
            minimum=0.0,
            maximum=0.4,
        )
        self.rolling_speed = self._clamped_float(
            self.rolling_speed,
            default=0.035,
            minimum=0.005,
            maximum=0.08,
        )
        self.wisp_stretch = self._clamped_float(
            self.wisp_stretch,
            default=1.8,
            minimum=0.8,
            maximum=2.8,
        )
        self.card_clear_strength = self._clamped_float(
            self.card_clear_strength,
            default=0.72,
            minimum=0.0,
            maximum=1.0,
        )
        self.anchor_clear_radius = self._clamped_float(
            self.anchor_clear_radius,
            default=0.18,
            minimum=0.08,
            maximum=0.40,
        )
        self.debug_visible = bool(self.debug_visible)
        self.diagnostic_disable_during_speech = bool(
            self.diagnostic_disable_during_speech
        )
        self.debug_intensity_multiplier = self._clamped_float(
            self.debug_intensity_multiplier,
            default=3.0,
            minimum=1.0,
            maximum=8.0,
        )
        self.debug_tint = bool(self.debug_tint)

    @staticmethod
    def _clamped_float(
        value: Any,
        *,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return min(maximum, max(minimum, parsed))

    @property
    def quality_samples(self) -> int:
        if not self.enabled or self.quality == "off":
            return 0
        return {"low": 8, "medium": 14, "high": 24}.get(self.quality, 14)

    @property
    def drift_direction_vector(self) -> tuple[float, float]:
        if self.drift_direction == "left_to_right":
            return (1.0, 0.05)
        if self.drift_direction == "still":
            return (0.0, 0.0)
        return (-1.0, 0.05)

    def to_qml_map(self) -> dict[str, Any]:
        drift_direction_x, drift_direction_y = self.drift_direction_vector
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "quality": self.quality,
            "intensity": self.intensity,
            "motion": self.motion,
            "edgeFog": self.edge_fog,
            "foregroundWisps": self.foreground_wisps,
            "qualitySamples": self.quality_samples,
            "density": 0.62,
            "driftSpeed": self.drift_speed,
            "driftDirection": self.drift_direction,
            "driftDirectionX": drift_direction_x,
            "driftDirectionY": drift_direction_y,
            "flowScale": self.flow_scale,
            "crosswindWobble": self.crosswind_wobble,
            "rollingSpeed": self.rolling_speed,
            "wispStretch": self.wisp_stretch,
            "noiseScale": 1.12,
            "edgeDensity": 0.88 if self.edge_fog else 0.24,
            "lowerFogBias": self.lower_bias,
            "centerClearRadius": 0.40,
            "centerClearStrength": self.center_clear_strength,
            "foregroundAmount": 0.18 if self.foreground_wisps else 0.0,
            "foregroundOpacityLimit": self.max_foreground_opacity
            if self.foreground_wisps
            else 0.0,
            "opacityLimit": 0.22,
            "protectedCenterX": 0.5,
            "protectedCenterY": 0.58,
            "protectedRadius": 0.36,
            "anchorCenterX": 0.5,
            "anchorCenterY": 0.30,
            "anchorRadius": self.anchor_clear_radius,
            "cardClearStrength": self.card_clear_strength,
            "debugVisible": self.debug_visible,
            "debugIntensityMultiplier": self.debug_intensity_multiplier,
            "debugTint": self.debug_tint,
            "diagnosticDisableDuringSpeech": self.diagnostic_disable_during_speech,
        }


@dataclass(slots=True)
class StormforgeVoiceDiagnosticsConfig:
    anchor_visualizer_mode: str = "auto"
    anchor_renderer: str = "legacy_blob_reference"

    def __post_init__(self) -> None:
        mode = str(self.anchor_visualizer_mode or "auto").strip().lower()
        mode = mode.replace("-", "_").replace(" ", "_")
        self.anchor_visualizer_mode = (
            mode
            if mode
            in {
                "auto",
                "off",
                "procedural",
                "envelope_timeline",
                "constant_test_wave",
            }
            else "auto"
        )
        renderer = str(self.anchor_renderer or "legacy_blob_reference").strip().lower()
        renderer = renderer.replace("-", "_").replace(" ", "_")
        if renderer in {"legacy_blob", "legacy_blob_reference"}:
            self.anchor_renderer = "legacy_blob_reference"
        elif renderer in {"legacy_blob_fast", "legacy_blob_fast_candidate"}:
            self.anchor_renderer = "legacy_blob_fast_candidate"
        elif renderer in {"legacy_blob_qsg", "legacy_blob_qsg_candidate"}:
            self.anchor_renderer = "legacy_blob_qsg_candidate"
        elif renderer == "ar3_split":
            self.anchor_renderer = "ar3_split"
        else:
            self.anchor_renderer = "legacy_blob_reference"

    def to_qml_map(self) -> dict[str, Any]:
        return {
            "anchorVisualizerMode": self.anchor_visualizer_mode,
            "anchorRenderer": self.anchor_renderer,
            "liveIsolationVersion": "UI-VOICE-LIVE-ISO",
        }


@dataclass(slots=True)
class UIConfig:
    poll_interval_ms: int
    hide_to_tray_on_close: bool
    ghost_shortcut: str
    visual_variant: str = "classic"
    stormforge_fog: StormforgeFogConfig = field(default_factory=StormforgeFogConfig)
    stormforge_voice_diagnostics: StormforgeVoiceDiagnosticsConfig = field(
        default_factory=StormforgeVoiceDiagnosticsConfig
    )


@dataclass(slots=True)
class LifecycleConfig:
    startup_enabled: bool = False
    start_core_with_windows: bool = False
    start_shell_with_windows: bool = False
    tray_only_startup: bool = True
    ghost_ready_on_startup: bool = True
    background_core_resident: bool = True
    auto_restart_core: bool = True
    max_core_restart_attempts: int = 2
    restart_failure_window_seconds: float = 300.0
    shell_heartbeat_interval_seconds: float = 15.0
    shell_stale_after_seconds: float = 45.0
    core_restart_backoff_ms: int = 750


@dataclass(slots=True)
class EventStreamConfig:
    enabled: bool = True
    retention_capacity: int = 500
    replay_limit: int = 128
    heartbeat_seconds: float = 15.0


@dataclass(slots=True)
class LocationConfig:
    allow_approximate_lookup: bool
    lookup_timeout_seconds: float
    home_label: str | None
    home_city: str | None
    home_region: str | None
    home_country: str | None
    home_latitude: float | None
    home_longitude: float | None
    home_timezone: str | None


@dataclass(slots=True)
class WeatherConfig:
    enabled: bool
    units: str
    provider_base_url: str
    timeout_seconds: float


@dataclass(slots=True)
class HardwareTelemetryConfig:
    enabled: bool
    helper_timeout_seconds: float
    provider_timeout_seconds: float
    idle_cache_ttl_seconds: float
    active_cache_ttl_seconds: float
    burst_cache_ttl_seconds: float
    elevated_helper_enabled: bool
    elevated_helper_timeout_seconds: float
    elevated_helper_cooldown_seconds: float
    hwinfo_enabled: bool
    hwinfo_executable_path: str | None


@dataclass(slots=True)
class PlaywrightBrowserAdapterConfig:
    enabled: bool = False
    provider: str = "playwright"
    mode: str = "semantic_observation"
    allow_browser_launch: bool = False
    allow_connect_existing: bool = False
    allow_actions: bool = False
    allow_click: bool = False
    allow_focus: bool = False
    allow_type_text: bool = False
    allow_check: bool = False
    allow_uncheck: bool = False
    allow_select_option: bool = False
    allow_scroll: bool = False
    allow_scroll_to_target: bool = False
    allow_task_plans: bool = False
    allow_form_fill: bool = False
    allow_form_submit: bool = False
    allow_login: bool = False
    allow_cookies: bool = False
    allow_user_profile: bool = False
    allow_payment: bool = False
    allow_screenshots: bool = False
    allow_dev_adapter: bool = False
    allow_dev_actions: bool = False
    allow_dev_type_text: bool = False
    allow_dev_choice_controls: bool = False
    allow_dev_scroll: bool = False
    allow_dev_task_plans: bool = False
    max_session_seconds: int = 120
    navigation_timeout_seconds: int = 12000
    observation_timeout_seconds: int = 8000
    max_scroll_attempts: int = 5
    scroll_step_pixels: int = 700
    scroll_timeout_seconds: float = 8.0
    max_scroll_distance_pixels: int = 5000
    max_task_steps: int = 5
    stop_on_unverified_step: bool = True
    stop_on_partial_step: bool = True
    stop_on_ambiguous_step: bool = True
    stop_on_unexpected_navigation: bool = True
    debug_events_enabled: bool = True


@dataclass(slots=True)
class ScreenAwarenessBrowserAdaptersConfig:
    playwright: PlaywrightBrowserAdapterConfig = field(default_factory=PlaywrightBrowserAdapterConfig)


@dataclass(slots=True)
class ScreenAwarenessConfig:
    enabled: bool = True
    phase: str = "phase12"
    planner_routing_enabled: bool = True
    debug_events_enabled: bool = True
    observation_enabled: bool = True
    interpretation_enabled: bool = True
    grounding_enabled: bool = True
    guidance_enabled: bool = True
    action_enabled: bool = True
    action_policy_mode: str = "confirm_before_act"
    verification_enabled: bool = True
    memory_enabled: bool = True
    adapters_enabled: bool = True
    problem_solving_enabled: bool = True
    workflow_learning_enabled: bool = True
    brain_integration_enabled: bool = True
    power_features_enabled: bool = True
    screen_capture_enabled: bool = True
    screen_capture_scope: str = "active_window"
    screen_capture_ocr_enabled: bool = True
    screen_capture_provider_vision_enabled: bool = False
    screen_capture_store_raw_images: bool = False
    browser_adapters: ScreenAwarenessBrowserAdaptersConfig = field(default_factory=ScreenAwarenessBrowserAdaptersConfig)

    def _phase_at_least(self, minimum_phase: int) -> bool:
        phase_name = str(self.phase or "").strip().lower()
        phase_order = {
            "phase0": 0,
            "phase1": 1,
            "phase2": 2,
            "phase3": 3,
            "phase4": 4,
            "phase5": 5,
            "phase6": 6,
            "phase7": 7,
            "phase8": 8,
            "phase9": 9,
            "phase10": 10,
            "phase11": 11,
            "phase12": 12,
        }
        return phase_order.get(phase_name, 0) >= minimum_phase

    def capability_flags(self) -> dict[str, bool]:
        return {
            "observation_enabled": self.observation_enabled and self._phase_at_least(1),
            "interpretation_enabled": self.interpretation_enabled
            and self._phase_at_least(1),
            "grounding_enabled": self.grounding_enabled and self._phase_at_least(2),
            "guidance_enabled": self.guidance_enabled and self._phase_at_least(3),
            "action_enabled": self.action_enabled and self._phase_at_least(5),
            "verification_enabled": self.verification_enabled
            and self._phase_at_least(4),
            "memory_enabled": self.memory_enabled,
            "continuity_enabled": self.memory_enabled and self._phase_at_least(6),
            "adapters_enabled": self.adapters_enabled and self._phase_at_least(7),
            "problem_solving_enabled": self.problem_solving_enabled
            and self._phase_at_least(8),
            "workflow_learning_enabled": self.workflow_learning_enabled
            and self._phase_at_least(9),
            "brain_integration_enabled": self.brain_integration_enabled
            and self._phase_at_least(10),
            "power_features_enabled": self.power_features_enabled
            and self._phase_at_least(11),
            "hardening_enabled": self._phase_at_least(12),
            "screen_capture_enabled": self.screen_capture_enabled
            and self._phase_at_least(12),
            "screen_capture_ocr_enabled": self.screen_capture_ocr_enabled
            and self.screen_capture_enabled
            and self._phase_at_least(12),
            "screen_capture_provider_vision_enabled": self.screen_capture_provider_vision_enabled
            and self.screen_capture_enabled
            and self._phase_at_least(12),
        }


@dataclass(slots=True)
class CameraAwarenessCaptureConfig:
    provider: str = "mock"
    mode: str = "single_still"
    default_device_id: str | None = None
    requested_resolution: str = "1280x720"
    timeout_seconds: float = 5.0
    max_artifact_bytes: int = 10485760


@dataclass(slots=True)
class CameraAwarenessVisionConfig:
    provider: str = "mock"
    model: str = "mock-vision"
    timeout_seconds: float = 10.0
    detail: str = "auto"
    max_image_bytes: int = 8_000_000
    request_timeout_ms: int = 30_000
    allow_cloud_vision: bool = False
    require_confirmation_for_cloud: bool = True


@dataclass(slots=True)
class CameraAwarenessPrivacyConfig:
    confirm_before_capture: bool = True
    persist_images_by_default: bool = False
    require_source_provenance: bool = True
    redact_raw_image_from_events: bool = True


@dataclass(slots=True)
class CameraAwarenessDevConfig:
    mock_capture_enabled: bool = True
    mock_vision_enabled: bool = True
    mock_image_fixture: str = "resistor"
    save_debug_images: bool = False


@dataclass(slots=True)
class CameraAwarenessConfig:
    enabled: bool = False
    planner_routing_enabled: bool = True
    debug_events_enabled: bool = True
    default_capture_mode: str = "single_still"
    default_storage_mode: str = "ephemeral"
    auto_discard_after_seconds: int = 300
    allow_cloud_vision: bool = False
    allow_background_capture: bool = False
    allow_task_artifact_save: bool = False
    allow_session_permission: bool = False
    capture: CameraAwarenessCaptureConfig = field(default_factory=CameraAwarenessCaptureConfig)
    vision: CameraAwarenessVisionConfig = field(default_factory=CameraAwarenessVisionConfig)
    privacy: CameraAwarenessPrivacyConfig = field(default_factory=CameraAwarenessPrivacyConfig)
    dev: CameraAwarenessDevConfig = field(default_factory=CameraAwarenessDevConfig)


@dataclass(slots=True)
class CalculationsConfig:
    enabled: bool = True
    planner_routing_enabled: bool = True
    debug_events_enabled: bool = True


@dataclass(slots=True)
class SoftwareControlConfig:
    enabled: bool = True
    planner_routing_enabled: bool = True
    debug_events_enabled: bool = True
    package_manager_routes_enabled: bool = True
    vendor_installer_routes_enabled: bool = True
    browser_guided_routes_enabled: bool = True
    privileged_operations_allowed: bool = False
    trusted_sources_only: bool = True
    unsafe_test_mode: bool = False


@dataclass(slots=True)
class SoftwareRecoveryConfig:
    enabled: bool = True
    debug_events_enabled: bool = True
    local_troubleshooting_enabled: bool = True
    max_retry_attempts: int = 2
    max_recovery_steps: int = 4
    cloud_fallback_enabled: bool = False
    cloud_fallback_model: str = "gpt-5.4-nano"
    redaction_enabled: bool = True


@dataclass(slots=True)
class TrustConfig:
    enabled: bool = True
    debug_events_enabled: bool = True
    session_grant_ttl_seconds: float = 14400.0
    once_grant_ttl_seconds: float = 900.0
    pending_request_ttl_seconds: float = 3600.0
    audit_recent_limit: int = 24


@dataclass(slots=True)
class WebRetrievalHttpConfig:
    enabled: bool = True
    timeout_seconds: float = 8.0


@dataclass(slots=True)
class WebRetrievalObscuraCDPConfig:
    enabled: bool = False
    binary_path: str = "obscura"
    host: str = "127.0.0.1"
    port: int = 0
    startup_timeout_seconds: float = 8.0
    shutdown_timeout_seconds: float = 4.0
    navigation_timeout_seconds: float = 12.0
    max_session_seconds: float = 120.0
    max_pages_per_session: int = 8
    max_dom_text_chars: int = 60000
    max_html_chars: int = 250000
    max_links: int = 500
    allow_runtime_eval: bool = False
    allow_input_domain: bool = False
    allow_cookies: bool = False
    allow_logged_in_context: bool = False
    allow_screenshots: bool = False
    debug_events_enabled: bool = True


@dataclass(slots=True)
class WebRetrievalObscuraConfig:
    enabled: bool = False
    binary_path: str = "obscura"
    mode: str = "cli"
    allow_cdp_server: bool = False
    serve_port: int = 9222
    stealth_enabled: bool = False
    obey_robots: bool = True
    workers: int = 1
    max_concurrency: int = 3
    wait_until: str = "networkidle0"
    dump_format: str = "text"
    allow_js_eval: bool = False
    max_eval_chars: int = 2000
    cdp: WebRetrievalObscuraCDPConfig = field(default_factory=WebRetrievalObscuraCDPConfig)


@dataclass(slots=True)
class WebRetrievalChromiumConfig:
    enabled: bool = False
    fallback_enabled: bool = True


@dataclass(slots=True)
class WebRetrievalConfig:
    enabled: bool = True
    planner_routing_enabled: bool = True
    debug_events_enabled: bool = True
    default_provider: str = "auto"
    max_url_count: int = 8
    max_url_chars: int = 4096
    max_parallel_pages: int = 3
    timeout_seconds: float = 12.0
    max_text_chars: int = 60000
    max_html_chars: int = 250000
    cache_snapshots: bool = True
    respect_robots: bool = True
    allow_private_network_urls: bool = False
    allow_file_urls: bool = False
    allow_logged_in_context: bool = False
    http: WebRetrievalHttpConfig = field(default_factory=WebRetrievalHttpConfig)
    obscura: WebRetrievalObscuraConfig = field(default_factory=WebRetrievalObscuraConfig)
    chromium: WebRetrievalChromiumConfig = field(default_factory=WebRetrievalChromiumConfig)


def default_discord_trusted_aliases() -> dict[str, "DiscordTrustedAliasConfig"]:
    return {
        "baby": DiscordTrustedAliasConfig(
            alias="Baby",
            label="Baby",
            destination_kind="personal_dm",
            route_mode="local_client_automation",
            navigation_mode="quick_switch",
            search_query="Baby",
            thread_uri=None,
            trusted=True,
            confirmation_policy="preview_required",
            attachment_policy="allow",
        )
    }


@dataclass(slots=True)
class DiscordTrustedAliasConfig:
    alias: str
    label: str
    destination_kind: str = "personal_dm"
    route_mode: str = "local_client_automation"
    navigation_mode: str = "quick_switch"
    search_query: str | None = None
    thread_uri: str | None = None
    trusted: bool = True
    confirmation_policy: str = "preview_required"
    attachment_policy: str = "allow"


@dataclass(slots=True)
class DiscordRelayConfig:
    enabled: bool = True
    planner_routing_enabled: bool = True
    debug_events_enabled: bool = True
    screen_disambiguation_enabled: bool = True
    preview_before_send: bool = True
    verification_enabled: bool = True
    local_dm_route_enabled: bool = True
    bot_webhook_routes_enabled: bool = False
    trusted_aliases: dict[str, DiscordTrustedAliasConfig] = field(
        default_factory=default_discord_trusted_aliases
    )


@dataclass(slots=True)
class OpenAIConfig:
    enabled: bool
    api_key: str | None
    base_url: str
    model: str
    planner_model: str
    reasoning_model: str
    timeout_seconds: float
    max_tool_rounds: int
    max_output_tokens: int
    planner_max_output_tokens: int
    reasoning_max_output_tokens: int
    instructions: str


@dataclass(slots=True)
class ProviderFallbackConfig:
    enabled: bool = False
    allow_streaming: bool = True
    allow_partial_progress: bool = True
    allow_cancellation: bool = True
    target_first_output_ms: float = 1500.0
    soft_first_output_ms: float = 3000.0
    hard_first_output_ms: float = 6000.0
    target_total_ms: float = 4000.0
    soft_total_ms: float = 8000.0
    hard_total_ms: float = 12000.0
    allow_for_native_routes: bool = False
    allow_speculative_provider_calls: bool = False
    log_prompt_payloads: bool = False
    audit_timing: bool = True
    surface_partial_in_ghost: bool = True
    surface_details_in_deck: bool = True


@dataclass(slots=True)
class VoiceOpenAIConfig:
    stt_model: str = "gpt-4o-mini-transcribe"
    transcription_language: str | None = None
    transcription_prompt: str | None = None
    timeout_seconds: float = 60.0
    max_audio_seconds: float = 30.0
    max_audio_bytes: int = 25 * 1024 * 1024
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "onyx"
    tts_format: str = "mp3"
    stream_tts_outputs: bool = False
    tts_live_format: str = "pcm"
    tts_artifact_format: str = "mp3"
    streaming_fallback_to_buffered: bool = True
    tts_speed: float = 1.0
    max_tts_chars: int = 600
    output_audio_dir: str | None = None
    persist_tts_outputs: bool = False
    realtime_model: str = "gpt-realtime"
    vad_mode: str = "server_vad"


@dataclass(slots=True)
class VoicePlaybackConfig:
    enabled: bool = False
    provider: str = "local"
    device: str = "default"
    volume: float = 1.0
    allow_dev_playback: bool = False
    streaming_enabled: bool = False
    streaming_fallback_to_file: bool = True
    prewarm_enabled: bool = True
    streaming_min_preroll_ms: int = 350
    streaming_min_preroll_chunks: int = 2
    streaming_min_preroll_bytes: int = 0
    streaming_max_preroll_wait_ms: int = 1200
    playback_stable_after_ms: int = 180
    max_audio_bytes: int = 10_000_000
    max_duration_ms: int = 120_000
    delete_transient_after_playback: bool = True


@dataclass(slots=True)
class VoiceVisualSyncConfig:
    enabled: bool = True
    envelope_visual_offset_ms: int = 0
    estimated_output_latency_ms: int = 120
    debug_show_sync: bool = False

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        try:
            offset = int(round(float(self.envelope_visual_offset_ms)))
        except (TypeError, ValueError):
            offset = 0
        self.envelope_visual_offset_ms = max(-500, min(500, offset))
        try:
            latency = int(round(float(self.estimated_output_latency_ms)))
        except (TypeError, ValueError):
            latency = 120
        self.estimated_output_latency_ms = max(0, min(500, latency))
        self.debug_show_sync = bool(self.debug_show_sync)


@dataclass(slots=True)
class VoiceVisualMeterConfig:
    enabled: bool = True
    sample_rate_hz: int = 60
    startup_preroll_ms: int = 350
    attack_ms: int = 60
    release_ms: int = 160
    noise_floor: float = 0.015
    gain: float = 2.0
    max_startup_wait_ms: int = 800
    visual_offset_ms: int = 0

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.sample_rate_hz = max(30, min(60, int(self.sample_rate_hz or 60)))
        self.startup_preroll_ms = max(
            0, min(500, int(self.startup_preroll_ms or 350))
        )
        self.attack_ms = max(1, min(500, int(self.attack_ms or 60)))
        self.release_ms = max(1, min(1000, int(self.release_ms or 160)))
        try:
            noise_floor = float(self.noise_floor)
        except (TypeError, ValueError):
            noise_floor = 0.015
        self.noise_floor = max(0.0, min(0.5, noise_floor))
        try:
            gain = float(self.gain)
        except (TypeError, ValueError):
            gain = 2.0
        self.gain = max(0.01, min(12.0, gain))
        self.max_startup_wait_ms = max(
            0, min(5000, int(self.max_startup_wait_ms or 800))
        )
        try:
            visual_offset = int(round(float(self.visual_offset_ms)))
        except (TypeError, ValueError):
            visual_offset = 0
        self.visual_offset_ms = max(-300, min(300, visual_offset))


@dataclass(slots=True)
class VoiceCaptureConfig:
    enabled: bool = False
    provider: str = "local"
    mode: str = "push_to_talk"
    device: str = "default"
    sample_rate: int = 16000
    channels: int = 1
    format: str = "wav"
    max_duration_ms: int = 30_000
    max_audio_bytes: int = 10_000_000
    auto_stop_on_max_duration: bool = True
    persist_captured_audio: bool = False
    delete_transient_after_turn: bool = True
    allow_dev_capture: bool = False


@dataclass(slots=True)
class VoiceWakeConfig:
    enabled: bool = False
    provider: str = "mock"
    wake_phrase: str = "Stormhelm"
    device: str = "default"
    sample_rate: int = 16000
    backend: str = "unavailable"
    model_path: str | None = None
    sensitivity: float = 0.5
    confidence_threshold: float = 0.75
    cooldown_ms: int = 2500
    max_wake_session_ms: int = 15000
    false_positive_window_ms: int = 3000
    allow_dev_wake: bool = False

    def __post_init__(self) -> None:
        self.provider = str(self.provider or "mock").strip().lower() or "mock"
        self.wake_phrase = str(self.wake_phrase or "Stormhelm").strip() or "Stormhelm"
        self.device = str(self.device or "default").strip() or "default"
        self.backend = (
            str(self.backend or "unavailable").strip().lower() or "unavailable"
        )
        self.model_path = (
            str(self.model_path).strip() if self.model_path is not None else None
        ) or None
        self.sample_rate = max(1, int(self.sample_rate or 16000))
        try:
            sensitivity = float(self.sensitivity)
        except (TypeError, ValueError):
            sensitivity = 0.5
        self.sensitivity = min(1.0, max(0.0, sensitivity))
        try:
            threshold = float(self.confidence_threshold)
        except (TypeError, ValueError):
            threshold = 0.75
        self.confidence_threshold = min(1.0, max(0.0, threshold))
        self.cooldown_ms = max(0, int(self.cooldown_ms or 0))
        self.max_wake_session_ms = max(1, int(self.max_wake_session_ms or 1))
        self.false_positive_window_ms = max(0, int(self.false_positive_window_ms or 0))


@dataclass(slots=True)
class VoicePostWakeConfig:
    enabled: bool = False
    listen_window_ms: int = 8000
    max_utterance_ms: int = 30_000
    auto_start_capture: bool = True
    auto_submit_on_capture_complete: bool = True
    allow_dev_post_wake: bool = False

    def __post_init__(self) -> None:
        self.listen_window_ms = max(1, int(self.listen_window_ms or 8000))
        self.max_utterance_ms = max(1, int(self.max_utterance_ms or 30_000))
        self.auto_start_capture = bool(self.auto_start_capture)
        self.auto_submit_on_capture_complete = bool(
            self.auto_submit_on_capture_complete
        )
        self.allow_dev_post_wake = bool(self.allow_dev_post_wake)


@dataclass(slots=True)
class VoiceVADConfig:
    enabled: bool = False
    provider: str = "mock"
    silence_ms: int = 900
    speech_start_threshold: float = 0.5
    speech_stop_threshold: float = 0.35
    min_speech_ms: int = 250
    max_utterance_ms: int = 30_000
    pre_roll_ms: int = 250
    post_roll_ms: int = 250
    allow_dev_vad: bool = False
    auto_finalize_capture: bool = True

    def __post_init__(self) -> None:
        self.provider = str(self.provider or "mock").strip().lower() or "mock"
        self.silence_ms = max(0, int(self.silence_ms or 0))
        self.min_speech_ms = max(0, int(self.min_speech_ms or 0))
        self.max_utterance_ms = max(1, int(self.max_utterance_ms or 1))
        self.pre_roll_ms = max(0, int(self.pre_roll_ms or 0))
        self.post_roll_ms = max(0, int(self.post_roll_ms or 0))
        try:
            start_threshold = float(self.speech_start_threshold)
        except (TypeError, ValueError):
            start_threshold = 0.5
        try:
            stop_threshold = float(self.speech_stop_threshold)
        except (TypeError, ValueError):
            stop_threshold = 0.35
        self.speech_start_threshold = min(1.0, max(0.0, start_threshold))
        self.speech_stop_threshold = min(1.0, max(0.0, stop_threshold))


@dataclass(slots=True)
class VoiceRealtimeConfig:
    enabled: bool = False
    provider: str = "openai"
    mode: str = "transcription_bridge"
    model: str = "gpt-realtime"
    voice: str = "stormhelm_default"
    turn_detection: str = "server_vad"
    semantic_vad_enabled: bool = False
    max_session_ms: int = 60_000
    max_turn_ms: int = 30_000
    allow_dev_realtime: bool = False
    direct_tools_allowed: bool = False
    core_bridge_required: bool = True
    audio_output_enabled: bool = False
    speech_to_speech_enabled: bool = False
    audio_output_from_realtime: bool = False
    require_core_for_commands: bool = True
    allow_smalltalk_without_core: bool = False

    def __post_init__(self) -> None:
        self.provider = str(self.provider or "openai").strip().lower() or "openai"
        mode = str(self.mode or "transcription_bridge").strip().lower()
        self.mode = (
            mode
            if mode in {"transcription_bridge", "speech_to_speech_core_bridge"}
            else "unsupported"
        )
        self.model = str(self.model or "gpt-realtime").strip() or "gpt-realtime"
        self.voice = str(self.voice or "stormhelm_default").strip() or "stormhelm_default"
        self.turn_detection = (
            str(self.turn_detection or "server_vad").strip().lower() or "server_vad"
        )
        self.semantic_vad_enabled = bool(self.semantic_vad_enabled)
        self.max_session_ms = max(1, int(self.max_session_ms or 60_000))
        self.max_turn_ms = max(1, int(self.max_turn_ms or 30_000))
        self.allow_dev_realtime = bool(self.allow_dev_realtime)
        self.direct_tools_allowed = False
        self.core_bridge_required = True
        self.require_core_for_commands = True
        self.allow_smalltalk_without_core = bool(self.allow_smalltalk_without_core)
        if self.mode == "speech_to_speech_core_bridge":
            self.speech_to_speech_enabled = bool(self.speech_to_speech_enabled)
            self.audio_output_from_realtime = bool(
                self.audio_output_from_realtime or self.audio_output_enabled
            )
            self.audio_output_enabled = self.audio_output_from_realtime
        else:
            self.speech_to_speech_enabled = False
            self.audio_output_from_realtime = False
            self.audio_output_enabled = False


@dataclass(slots=True)
class VoiceConfirmationConfig:
    enabled: bool = True
    max_confirmation_age_ms: int = 30_000
    allow_soft_yes_for_low_risk: bool = True
    require_strong_phrase_for_destructive: bool = True
    consume_once: bool = True
    reject_on_task_switch: bool = True
    reject_on_payload_change: bool = True
    reject_on_session_restart: bool = True

    def __post_init__(self) -> None:
        self.max_confirmation_age_ms = max(
            1, int(self.max_confirmation_age_ms or 30_000)
        )


@dataclass(slots=True)
class VoiceConfig:
    enabled: bool = False
    provider: str = "openai"
    mode: str = "disabled"
    wake_word_enabled: bool = False
    spoken_responses_enabled: bool = False
    manual_input_enabled: bool = True
    realtime_enabled: bool = False
    debug_mock_provider: bool = True
    openai: VoiceOpenAIConfig = field(default_factory=VoiceOpenAIConfig)
    playback: VoicePlaybackConfig = field(default_factory=VoicePlaybackConfig)
    visual_sync: VoiceVisualSyncConfig = field(default_factory=VoiceVisualSyncConfig)
    visual_meter: VoiceVisualMeterConfig = field(default_factory=VoiceVisualMeterConfig)
    capture: VoiceCaptureConfig = field(default_factory=VoiceCaptureConfig)
    wake: VoiceWakeConfig = field(default_factory=VoiceWakeConfig)
    post_wake: VoicePostWakeConfig = field(default_factory=VoicePostWakeConfig)
    vad: VoiceVADConfig = field(default_factory=VoiceVADConfig)
    realtime: VoiceRealtimeConfig = field(default_factory=VoiceRealtimeConfig)
    confirmation: VoiceConfirmationConfig = field(default_factory=VoiceConfirmationConfig)


@dataclass(slots=True)
class SafetyConfig:
    allowed_read_dirs: list[Path]
    allow_shell_stub: bool
    unsafe_test_mode: bool = False


@dataclass(slots=True)
class ToolEnablementConfig:
    clock: bool = True
    system_info: bool = True
    file_reader: bool = True
    notes_write: bool = True
    echo: bool = True
    browser_context: bool = True
    activity_summary: bool = True
    shell_command: bool = False
    deck_open_url: bool = True
    external_open_url: bool = True
    deck_open_file: bool = True
    external_open_file: bool = True
    machine_status: bool = True
    power_status: bool = True
    power_projection: bool = True
    power_diagnosis: bool = True
    resource_status: bool = True
    resource_diagnosis: bool = True
    storage_status: bool = True
    storage_diagnosis: bool = True
    network_status: bool = True
    network_throughput: bool = True
    network_diagnosis: bool = True
    active_apps: bool = True
    app_control: bool = True
    window_status: bool = True
    window_control: bool = True
    system_control: bool = True
    control_capabilities: bool = True
    desktop_search: bool = True
    workflow_execute: bool = True
    repair_action: bool = True
    routine_execute: bool = True
    routine_save: bool = True
    trusted_hook_register: bool = True
    trusted_hook_execute: bool = True
    file_operation: bool = True
    maintenance_action: bool = True
    context_action: bool = True
    recent_files: bool = True
    location_status: bool = True
    saved_locations: bool = True
    save_location: bool = True
    weather_current: bool = True
    subsystem_continuation: bool = True
    workspace_restore: bool = True
    workspace_assemble: bool = True
    workspace_save: bool = True
    workspace_clear: bool = True
    workspace_archive: bool = True
    workspace_rename: bool = True
    workspace_tag: bool = True
    workspace_list: bool = True
    workspace_where_left_off: bool = True
    workspace_next_steps: bool = True
    web_retrieval_fetch: bool = True

    def is_enabled(self, tool_name: str) -> bool:
        return getattr(self, tool_name, False)


@dataclass(slots=True)
class ToolConfig:
    enabled: ToolEnablementConfig = field(default_factory=ToolEnablementConfig)
    max_file_read_bytes: int = 32768


@dataclass(slots=True)
class RuntimePathConfig:
    mode: str
    is_frozen: bool
    source_root: Path | None
    install_root: Path
    resource_root: Path
    assets_dir: Path
    bundled_config_dir: Path
    portable_config_path: Path
    user_config_path: Path
    state_dir: Path
    core_state_path: Path
    first_run_marker_path: Path
    lifecycle_state_path: Path
    core_session_path: Path
    shell_session_path: Path
    core_executable_path: Path


@dataclass(slots=True)
class AppConfig:
    app_name: str
    version: str
    protocol_version: int
    release_channel: str
    environment: str
    debug: bool
    project_root: Path
    runtime: RuntimePathConfig
    network: NetworkConfig
    storage: StorageConfig
    logging: LoggingConfig
    concurrency: ConcurrencyConfig
    ui: UIConfig
    lifecycle: LifecycleConfig
    event_stream: EventStreamConfig
    location: LocationConfig
    weather: WeatherConfig
    hardware_telemetry: HardwareTelemetryConfig
    screen_awareness: ScreenAwarenessConfig
    camera_awareness: CameraAwarenessConfig
    calculations: CalculationsConfig
    software_control: SoftwareControlConfig
    software_recovery: SoftwareRecoveryConfig
    trust: TrustConfig
    web_retrieval: WebRetrievalConfig
    discord_relay: DiscordRelayConfig
    openai: OpenAIConfig
    provider_fallback: ProviderFallbackConfig
    voice: VoiceConfig
    safety: SafetyConfig
    tools: ToolConfig

    @property
    def api_base_url(self) -> str:
        return f"http://{self.network.host}:{self.network.port}"

    @property
    def log_file_path(self) -> Path:
        return self.core_log_file_path

    @property
    def core_log_file_path(self) -> Path:
        return self.storage.logs_dir / _build_log_file_name(
            self.logging.file_name, "core"
        )

    @property
    def ui_log_file_path(self) -> Path:
        return self.storage.logs_dir / _build_log_file_name(
            self.logging.file_name, "ui"
        )

    @property
    def version_label(self) -> str:
        if self.release_channel.lower() in {"", "release", "stable"}:
            return self.version
        return f"{self.version} ({self.release_channel})"

    def to_dict(self) -> dict[str, Any]:
        data = _serialize(asdict(self))
        openai = data.get("openai")
        if isinstance(openai, dict) and openai.get("api_key"):
            openai["api_key"] = "***configured***"
        return data


def _build_log_file_name(base_name: str, process_name: str) -> str:
    path = Path(base_name)
    if path.suffix:
        return f"{path.stem}-{process_name}{path.suffix}"
    return f"{base_name}-{process_name}.log"


def _serialize(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if is_dataclass(value):
        return _serialize(asdict(value))
    return value
