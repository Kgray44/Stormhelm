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
class UIConfig:
    poll_interval_ms: int
    hide_to_tray_on_close: bool
    ghost_shortcut: str


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
            "interpretation_enabled": self.interpretation_enabled and self._phase_at_least(1),
            "grounding_enabled": self.grounding_enabled and self._phase_at_least(2),
            "guidance_enabled": self.guidance_enabled and self._phase_at_least(3),
            "action_enabled": self.action_enabled and self._phase_at_least(5),
            "verification_enabled": self.verification_enabled and self._phase_at_least(4),
            "memory_enabled": self.memory_enabled,
            "continuity_enabled": self.memory_enabled and self._phase_at_least(6),
            "adapters_enabled": self.adapters_enabled and self._phase_at_least(7),
            "problem_solving_enabled": self.problem_solving_enabled and self._phase_at_least(8),
            "workflow_learning_enabled": self.workflow_learning_enabled and self._phase_at_least(9),
            "brain_integration_enabled": self.brain_integration_enabled and self._phase_at_least(10),
            "power_features_enabled": self.power_features_enabled and self._phase_at_least(11),
            "hardening_enabled": self._phase_at_least(12),
        }


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
    trusted_aliases: dict[str, DiscordTrustedAliasConfig] = field(default_factory=default_discord_trusted_aliases)


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
class SafetyConfig:
    allowed_read_dirs: list[Path]
    allow_shell_stub: bool


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
    event_stream: EventStreamConfig
    location: LocationConfig
    weather: WeatherConfig
    hardware_telemetry: HardwareTelemetryConfig
    screen_awareness: ScreenAwarenessConfig
    calculations: CalculationsConfig
    software_control: SoftwareControlConfig
    software_recovery: SoftwareRecoveryConfig
    trust: TrustConfig
    discord_relay: DiscordRelayConfig
    openai: OpenAIConfig
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
        return self.storage.logs_dir / _build_log_file_name(self.logging.file_name, "core")

    @property
    def ui_log_file_path(self) -> Path:
        return self.storage.logs_dir / _build_log_file_name(self.logging.file_name, "ui")

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
