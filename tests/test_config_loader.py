from __future__ import annotations

from pathlib import Path

import pytest

from stormhelm.config.loader import load_config
from stormhelm.shared.runtime import RuntimeDiscovery


def test_load_config_applies_environment_overrides(temp_project_root: Path) -> None:
    runtime_dir = temp_project_root / "custom-runtime"
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_CORE_PORT": "9001",
            "STORMHELM_MAX_CONCURRENT_JOBS": "12",
            "STORMHELM_DATA_DIR": str(runtime_dir),
            "STORMHELM_OPENAI_ENABLED": "true",
            "STORMHELM_OPENAI_MODEL": "gpt-5.4-mini",
            "STORMHELM_OPENAI_PLANNER_MODEL": "gpt-5.4-mini",
            "STORMHELM_OPENAI_REASONING_MODEL": "gpt-5.4",
            "STORMHELM_UI_VARIANT": "stormforge",
            "STORMHELM_HOME_LABEL": "Brooklyn Home",
            "STORMHELM_HOME_LATITUDE": "40.6782",
            "STORMHELM_HOME_LONGITUDE": "-73.9442",
            "OPENAI_API_KEY": "test-key",
        },
    )

    assert config.network.port == 9001
    assert config.concurrency.max_workers == 12
    assert config.storage.data_dir == runtime_dir.resolve()
    assert config.storage.database_path == (runtime_dir / "stormhelm.db").resolve()
    assert config.storage.state_dir == (runtime_dir / "state").resolve()
    assert config.runtime.assets_dir == (temp_project_root / "assets").resolve()
    assert config.runtime.user_config_path == (runtime_dir / "config" / "user.toml").resolve()
    assert config.openai.enabled is True
    assert config.openai.model == "gpt-5.4-mini"
    assert config.openai.planner_model == "gpt-5.4-mini"
    assert config.openai.reasoning_model == "gpt-5.4"
    assert config.openai.api_key == "test-key"
    assert config.ui.visual_variant == "stormforge"
    assert config.location.home_label == "Brooklyn Home"
    assert config.location.home_latitude == pytest.approx(40.6782)
    assert config.location.home_longitude == pytest.approx(-73.9442)
    assert config.hardware_telemetry.enabled is True
    assert config.hardware_telemetry.helper_timeout_seconds == pytest.approx(12.0)
    assert config.hardware_telemetry.provider_timeout_seconds == pytest.approx(5.0)
    assert config.hardware_telemetry.active_cache_ttl_seconds == pytest.approx(8)
    assert config.hardware_telemetry.elevated_helper_enabled is False
    assert config.hardware_telemetry.elevated_helper_timeout_seconds == pytest.approx(20.0)
    assert config.hardware_telemetry.elevated_helper_cooldown_seconds == pytest.approx(120.0)


def test_load_config_defaults_to_nano_planner_and_full_reasoner(temp_project_root: Path) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.openai.planner_model == "gpt-5.4-nano"
    assert config.openai.reasoning_model == "gpt-5.4"
    assert config.ui.visual_variant == "classic"
    assert config.hardware_telemetry.enabled is True
    assert config.hardware_telemetry.helper_timeout_seconds == pytest.approx(12.0)
    assert config.hardware_telemetry.provider_timeout_seconds == pytest.approx(5.0)
    assert config.hardware_telemetry.hwinfo_enabled is True
    assert config.hardware_telemetry.hwinfo_executable_path is None
    assert config.hardware_telemetry.elevated_helper_enabled is False
    assert config.hardware_telemetry.elevated_helper_timeout_seconds == pytest.approx(20.0)
    assert config.hardware_telemetry.elevated_helper_cooldown_seconds == pytest.approx(120.0)


def test_load_config_invalid_ui_visual_variant_falls_back_to_classic(
    temp_project_root: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="stormhelm.config.loader")

    config = load_config(
        project_root=temp_project_root,
        env={"STORMHELM_UI_VARIANT": "fogbank"},
    )

    assert config.ui.visual_variant == "classic"
    assert "Unknown Stormhelm UI visual variant 'fogbank'" in caplog.text


def test_load_config_defaults_stormforge_fog_to_disabled_medium_volumetric(
    temp_project_root: Path,
) -> None:
    config = load_config(project_root=temp_project_root, env={})
    fog = config.ui.stormforge_fog

    assert fog.enabled is False
    assert fog.mode == "volumetric"
    assert fog.quality == "medium"
    assert fog.intensity == pytest.approx(0.35)
    assert fog.motion is True
    assert fog.edge_fog is True
    assert fog.foreground_wisps is True
    assert fog.max_foreground_opacity == pytest.approx(0.08)
    assert fog.center_clear_strength == pytest.approx(0.65)
    assert fog.lower_bias == pytest.approx(0.45)
    assert fog.drift_speed == pytest.approx(0.055)
    assert fog.drift_direction == "right_to_left"
    assert fog.flow_scale == pytest.approx(1.0)
    assert fog.crosswind_wobble == pytest.approx(0.18)
    assert fog.rolling_speed == pytest.approx(0.035)
    assert fog.wisp_stretch == pytest.approx(1.8)
    assert fog.card_clear_strength == pytest.approx(0.72)
    assert fog.anchor_clear_radius == pytest.approx(0.18)
    assert fog.debug_visible is False
    assert fog.debug_intensity_multiplier == pytest.approx(3.0)
    assert fog.debug_tint is True
    assert fog.quality_samples == 0
    assert fog.to_qml_map()["driftDirection"] == "right_to_left"
    assert fog.to_qml_map()["driftDirectionX"] == pytest.approx(-1.0)
    assert fog.to_qml_map()["driftDirectionY"] == pytest.approx(0.05)


def test_load_config_applies_stormforge_fog_environment_override(
    temp_project_root: Path,
) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={"STORMHELM_STORMFORGE_FOG": "1"},
    )
    fog = config.ui.stormforge_fog

    assert fog.enabled is True
    assert fog.mode == "volumetric"
    assert fog.quality == "medium"
    assert fog.quality_samples == 14


def test_load_config_applies_stormforge_fog_debug_environment_override(
    temp_project_root: Path,
) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_STORMFORGE_FOG": "1",
            "STORMHELM_STORMFORGE_FOG_DEBUG_VISIBLE": "true",
        },
    )
    fog = config.ui.stormforge_fog

    assert fog.enabled is True
    assert fog.debug_visible is True
    assert fog.to_qml_map()["debugVisible"] is True


def test_load_config_applies_stormforge_live_voice_isolation_overrides(
    temp_project_root: Path,
) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_ANCHOR_VISUALIZER_MODE": "constant_test_wave",
            "STORMHELM_STORMFORGE_FOG": "1",
            "STORMHELM_STORMFORGE_FOG_DIAGNOSTIC_DISABLE_DURING_SPEECH": "true",
        },
    )

    assert config.ui.stormforge_voice_diagnostics.anchor_visualizer_mode == (
        "constant_test_wave"
    )
    assert config.ui.stormforge_voice_diagnostics.to_qml_map() == {
        "anchorVisualizerMode": "constant_test_wave",
        "anchorRenderer": "legacy_blob_reference",
        "liveIsolationVersion": "UI-VOICE-LIVE-ISO",
    }
    assert config.ui.stormforge_fog.enabled is True
    assert config.ui.stormforge_fog.diagnostic_disable_during_speech is True
    assert (
        config.ui.stormforge_fog.to_qml_map()["diagnosticDisableDuringSpeech"]
        is True
    )


def test_load_config_defaults_stormforge_anchor_renderer_to_legacy_blob_reference(
    temp_project_root: Path,
) -> None:
    config = load_config(project_root=temp_project_root, env={})

    diagnostics = config.ui.stormforge_voice_diagnostics
    assert diagnostics.anchor_renderer == "legacy_blob_reference"
    assert diagnostics.to_qml_map()["anchorRenderer"] == "legacy_blob_reference"


def test_load_config_applies_stormforge_anchor_renderer_environment_override(
    temp_project_root: Path,
) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={"STORMHELM_STORMFORGE_ANCHOR_RENDERER": "ar3-split"},
    )

    diagnostics = config.ui.stormforge_voice_diagnostics
    assert diagnostics.anchor_renderer == "ar3_split"
    assert diagnostics.to_qml_map()["anchorRenderer"] == "ar3_split"


def test_load_config_applies_stormforge_legacy_blob_fast_candidate_override(
    temp_project_root: Path,
) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={"STORMHELM_STORMFORGE_ANCHOR_RENDERER": "legacy-blob-fast-candidate"},
    )

    diagnostics = config.ui.stormforge_voice_diagnostics
    assert diagnostics.anchor_renderer == "legacy_blob_fast_candidate"
    assert diagnostics.to_qml_map()["anchorRenderer"] == "legacy_blob_fast_candidate"


def test_load_config_applies_stormforge_legacy_blob_qsg_candidate_override(
    temp_project_root: Path,
) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={"STORMHELM_STORMFORGE_ANCHOR_RENDERER": "legacy-blob-qsg-candidate"},
    )

    diagnostics = config.ui.stormforge_voice_diagnostics
    assert diagnostics.anchor_renderer == "legacy_blob_qsg_candidate"
    assert diagnostics.to_qml_map()["anchorRenderer"] == "legacy_blob_qsg_candidate"


def test_load_config_keeps_legacy_blob_as_reference_alias(
    temp_project_root: Path,
) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={"STORMHELM_STORMFORGE_ANCHOR_RENDERER": "legacy_blob"},
    )

    assert config.ui.stormforge_voice_diagnostics.anchor_renderer == (
        "legacy_blob_reference"
    )


def test_load_config_normalizes_invalid_stormforge_fog_values(
    temp_project_root: Path,
) -> None:
    config_path = temp_project_root / "stormforge-fog.toml"
    config_path.write_text(
        """
[ui.stormforge.fog]
enabled = true
mode = "smoke_machine"
quality = "cinema"
intensity = 8.0
motion = false
edge_fog = false
foreground_wisps = false
max_foreground_opacity = 4.0
center_clear_strength = -2.0
lower_bias = 7.0
drift_speed = 9.0
drift_direction = "sideways"
flow_scale = 99.0
crosswind_wobble = -4.0
rolling_speed = 9.0
wisp_stretch = 99.0
card_clear_strength = -1.0
anchor_clear_radius = 2.0
debug_visible = true
debug_intensity_multiplier = 99.0
debug_tint = false
""".strip(),
        encoding="utf-8",
    )

    config = load_config(
        project_root=temp_project_root,
        config_path=config_path,
        env={},
    )
    fog = config.ui.stormforge_fog

    assert fog.enabled is True
    assert fog.mode == "volumetric"
    assert fog.quality == "medium"
    assert fog.intensity == pytest.approx(1.0)
    assert fog.motion is False
    assert fog.edge_fog is False
    assert fog.foreground_wisps is False
    assert fog.max_foreground_opacity == pytest.approx(0.16)
    assert fog.center_clear_strength == pytest.approx(0.0)
    assert fog.lower_bias == pytest.approx(1.0)
    assert fog.drift_speed == pytest.approx(0.12)
    assert fog.drift_direction == "right_to_left"
    assert fog.flow_scale == pytest.approx(2.0)
    assert fog.crosswind_wobble == pytest.approx(0.0)
    assert fog.rolling_speed == pytest.approx(0.08)
    assert fog.wisp_stretch == pytest.approx(2.8)
    assert fog.card_clear_strength == pytest.approx(0.0)
    assert fog.anchor_clear_radius == pytest.approx(0.40)
    assert fog.debug_visible is True
    assert fog.debug_intensity_multiplier == pytest.approx(8.0)
    assert fog.debug_tint is False
    assert fog.quality_samples == 14


@pytest.mark.parametrize(
    ("quality", "samples"),
    [
        ("off", 0),
        ("low", 8),
        ("medium", 14),
        ("high", 24),
    ],
)
def test_load_config_stormforge_fog_quality_modes(
    temp_project_root: Path,
    quality: str,
    samples: int,
) -> None:
    config_path = temp_project_root / f"stormforge-fog-{quality}.toml"
    config_path.write_text(
        f"""
[ui.stormforge.fog]
enabled = true
quality = "{quality}"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(
        project_root=temp_project_root,
        config_path=config_path,
        env={},
    )

    assert config.ui.stormforge_fog.quality == quality
    assert config.ui.stormforge_fog.quality_samples == samples


def test_load_config_applies_hardware_telemetry_environment_overrides(temp_project_root: Path) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_HARDWARE_TELEMETRY_ENABLED": "false",
            "STORMHELM_HARDWARE_TELEMETRY_TIMEOUT_SECONDS": "4.5",
            "STORMHELM_HARDWARE_TELEMETRY_PROVIDER_TIMEOUT_SECONDS": "1.75",
            "STORMHELM_HARDWARE_TELEMETRY_IDLE_CACHE_TTL_SECONDS": "40",
            "STORMHELM_HARDWARE_TELEMETRY_ACTIVE_CACHE_TTL_SECONDS": "10",
            "STORMHELM_HARDWARE_TELEMETRY_BURST_CACHE_TTL_SECONDS": "1.5",
            "STORMHELM_HARDWARE_TELEMETRY_ELEVATED_HELPER_ENABLED": "false",
            "STORMHELM_HARDWARE_TELEMETRY_ELEVATED_HELPER_TIMEOUT_SECONDS": "30",
            "STORMHELM_HARDWARE_TELEMETRY_ELEVATED_HELPER_COOLDOWN_SECONDS": "300",
            "STORMHELM_HARDWARE_TELEMETRY_HWINFO_ENABLED": "false",
            "STORMHELM_HARDWARE_TELEMETRY_HWINFO_PATH": "C:/Tools/HWiNFO64.EXE",
        },
    )

    assert config.hardware_telemetry.enabled is False
    assert config.hardware_telemetry.helper_timeout_seconds == pytest.approx(4.5)
    assert config.hardware_telemetry.provider_timeout_seconds == pytest.approx(1.75)
    assert config.hardware_telemetry.idle_cache_ttl_seconds == pytest.approx(40)
    assert config.hardware_telemetry.active_cache_ttl_seconds == pytest.approx(10)
    assert config.hardware_telemetry.burst_cache_ttl_seconds == pytest.approx(1.5)
    assert config.hardware_telemetry.elevated_helper_enabled is False
    assert config.hardware_telemetry.elevated_helper_timeout_seconds == pytest.approx(30)
    assert config.hardware_telemetry.elevated_helper_cooldown_seconds == pytest.approx(300)
    assert config.hardware_telemetry.hwinfo_enabled is False
    assert config.hardware_telemetry.hwinfo_executable_path == "C:/Tools/HWiNFO64.EXE"


def test_load_config_defaults_screen_awareness_to_phase12_hardening_and_power_flags(temp_project_root: Path) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.screen_awareness.phase == "phase12"
    assert config.screen_awareness.enabled is True
    assert config.screen_awareness.planner_routing_enabled is True
    assert config.screen_awareness.debug_events_enabled is True
    assert config.screen_awareness.observation_enabled is True
    assert config.screen_awareness.interpretation_enabled is True
    assert config.screen_awareness.grounding_enabled is True
    assert config.screen_awareness.guidance_enabled is True
    assert config.screen_awareness.action_enabled is True
    assert config.screen_awareness.action_policy_mode == "confirm_before_act"
    assert config.screen_awareness.verification_enabled is True
    assert config.screen_awareness.memory_enabled is True
    assert config.screen_awareness.adapters_enabled is True
    assert config.screen_awareness.problem_solving_enabled is True
    assert config.screen_awareness.workflow_learning_enabled is True
    assert config.screen_awareness.brain_integration_enabled is True
    assert config.screen_awareness.power_features_enabled is True
    assert config.screen_awareness.screen_capture_enabled is True
    assert config.screen_awareness.screen_capture_scope == "active_window"
    assert config.screen_awareness.screen_capture_ocr_enabled is True
    assert config.screen_awareness.screen_capture_provider_vision_enabled is False
    assert config.screen_awareness.screen_capture_store_raw_images is False
    assert config.screen_awareness.capability_flags()["screen_capture_enabled"] is True
    assert config.screen_awareness.capability_flags()["screen_capture_ocr_enabled"] is True
    assert config.screen_awareness.capability_flags()["hardening_enabled"] is True


def test_load_config_defaults_playwright_click_focus_execution_disabled(temp_project_root: Path) -> None:
    config = load_config(project_root=temp_project_root, env={})
    playwright = config.screen_awareness.browser_adapters.playwright

    assert playwright.enabled is False
    assert playwright.allow_actions is False
    assert playwright.allow_click is False
    assert playwright.allow_focus is False
    assert playwright.allow_type_text is False
    assert playwright.allow_check is False
    assert playwright.allow_uncheck is False
    assert playwright.allow_select_option is False
    assert playwright.allow_scroll is False
    assert playwright.allow_scroll_to_target is False
    assert playwright.allow_task_plans is False
    assert playwright.allow_form_fill is False
    assert playwright.allow_form_submit is False
    assert playwright.allow_login is False
    assert playwright.allow_cookies is False
    assert playwright.allow_user_profile is False
    assert playwright.allow_payment is False
    assert playwright.allow_dev_actions is False
    assert playwright.allow_dev_type_text is False
    assert playwright.allow_dev_choice_controls is False
    assert playwright.allow_dev_scroll is False
    assert playwright.allow_dev_task_plans is False
    assert playwright.max_scroll_attempts == 5
    assert playwright.scroll_step_pixels == 700
    assert playwright.scroll_timeout_seconds == 8.0
    assert playwright.max_scroll_distance_pixels == 5000
    assert playwright.max_task_steps == 5
    assert playwright.stop_on_unverified_step is True
    assert playwright.stop_on_partial_step is True
    assert playwright.stop_on_ambiguous_step is True
    assert playwright.stop_on_unexpected_navigation is True


def test_load_config_applies_playwright_click_focus_execution_environment_overrides(temp_project_root: Path) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ENABLED": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_ADAPTER": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_ACTIONS": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_ACTIONS": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_CLICK": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_FOCUS": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_TYPE_TEXT": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_TYPE_TEXT": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_CHECK": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_UNCHECK": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SELECT_OPTION": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_CHOICE_CONTROLS": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SCROLL": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_SCROLL_TO_TARGET": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_SCROLL": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_TASK_PLANS": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_DEV_TASK_PLANS": "true",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_MAX_SCROLL_ATTEMPTS": "4",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_SCROLL_STEP_PIXELS": "650",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_SCROLL_TIMEOUT_SECONDS": "6.5",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_MAX_SCROLL_DISTANCE_PIXELS": "2600",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_MAX_TASK_STEPS": "3",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_UNVERIFIED_STEP": "false",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_PARTIAL_STEP": "false",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_AMBIGUOUS_STEP": "false",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_STOP_ON_UNEXPECTED_NAVIGATION": "false",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_FORM_SUBMIT": "false",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_USER_PROFILE": "false",
            "STORMHELM_SCREEN_AWARENESS_PLAYWRIGHT_ALLOW_PAYMENT": "false",
        },
    )
    playwright = config.screen_awareness.browser_adapters.playwright

    assert playwright.enabled is True
    assert playwright.allow_dev_adapter is True
    assert playwright.allow_browser_launch is True
    assert playwright.allow_actions is True
    assert playwright.allow_dev_actions is True
    assert playwright.allow_click is True
    assert playwright.allow_focus is True
    assert playwright.allow_type_text is True
    assert playwright.allow_dev_type_text is True
    assert playwright.allow_check is True
    assert playwright.allow_uncheck is True
    assert playwright.allow_select_option is True
    assert playwright.allow_dev_choice_controls is True
    assert playwright.allow_scroll is True
    assert playwright.allow_scroll_to_target is True
    assert playwright.allow_dev_scroll is True
    assert playwright.allow_task_plans is True
    assert playwright.allow_dev_task_plans is True
    assert playwright.max_scroll_attempts == 4
    assert playwright.scroll_step_pixels == 650
    assert playwright.scroll_timeout_seconds == 6.5
    assert playwright.max_scroll_distance_pixels == 2600
    assert playwright.max_task_steps == 3
    assert playwright.stop_on_unverified_step is False
    assert playwright.stop_on_partial_step is False
    assert playwright.stop_on_ambiguous_step is False
    assert playwright.stop_on_unexpected_navigation is False
    assert playwright.allow_form_submit is False
    assert playwright.allow_user_profile is False
    assert playwright.allow_payment is False


def test_load_config_defaults_calculations_to_enabled_local_routing(temp_project_root: Path) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.calculations.enabled is True
    assert config.calculations.planner_routing_enabled is True
    assert config.calculations.debug_events_enabled is True


def test_load_config_applies_calculations_environment_overrides(temp_project_root: Path) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_CALCULATIONS_ENABLED": "false",
            "STORMHELM_CALCULATIONS_PLANNER_ROUTING_ENABLED": "false",
            "STORMHELM_CALCULATIONS_DEBUG_EVENTS_ENABLED": "false",
        },
    )

    assert config.calculations.enabled is False
    assert config.calculations.planner_routing_enabled is False
    assert config.calculations.debug_events_enabled is False


def test_load_config_defaults_software_control_and_recovery_to_native_local_first(temp_project_root: Path) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.software_control.enabled is True
    assert config.software_control.planner_routing_enabled is True
    assert config.software_control.package_manager_routes_enabled is True
    assert config.software_control.vendor_installer_routes_enabled is True
    assert config.software_control.browser_guided_routes_enabled is True
    assert config.software_control.privileged_operations_allowed is False
    assert config.software_recovery.enabled is True
    assert config.software_recovery.local_troubleshooting_enabled is True
    assert config.software_recovery.cloud_fallback_enabled is False
    assert config.software_recovery.cloud_fallback_model == "gpt-5.4-nano"
    assert config.software_recovery.redaction_enabled is True


def test_load_config_applies_software_control_and_recovery_environment_overrides(temp_project_root: Path) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_SOFTWARE_CONTROL_ENABLED": "false",
            "STORMHELM_SOFTWARE_CONTROL_PLANNER_ROUTING_ENABLED": "false",
            "STORMHELM_SOFTWARE_CONTROL_PACKAGE_MANAGER_ROUTES_ENABLED": "false",
            "STORMHELM_SOFTWARE_CONTROL_BROWSER_GUIDED_ROUTES_ENABLED": "false",
            "STORMHELM_SOFTWARE_RECOVERY_CLOUD_FALLBACK_ENABLED": "true",
            "STORMHELM_SOFTWARE_RECOVERY_MAX_RETRY_ATTEMPTS": "3",
            "STORMHELM_SOFTWARE_RECOVERY_CLOUD_FALLBACK_MODEL": "gpt-5.4-nano",
        },
    )

    assert config.software_control.enabled is False
    assert config.software_control.planner_routing_enabled is False
    assert config.software_control.package_manager_routes_enabled is False
    assert config.software_control.browser_guided_routes_enabled is False
    assert config.software_recovery.cloud_fallback_enabled is True
    assert config.software_recovery.max_retry_attempts == 3
    assert config.software_recovery.cloud_fallback_model == "gpt-5.4-nano"


def test_load_config_applies_screen_awareness_environment_overrides(temp_project_root: Path) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_SCREEN_AWARENESS_ENABLED": "true",
            "STORMHELM_SCREEN_AWARENESS_PHASE": "phase6",
            "STORMHELM_SCREEN_AWARENESS_PLANNER_ROUTING_ENABLED": "true",
            "STORMHELM_SCREEN_AWARENESS_DEBUG_EVENTS_ENABLED": "false",
            "STORMHELM_SCREEN_AWARENESS_ACTION_POLICY_MODE": "trusted_action",
            "STORMHELM_SCREEN_AWARENESS_VERIFICATION_ENABLED": "false",
            "STORMHELM_SCREEN_AWARENESS_MEMORY_ENABLED": "true",
            "STORMHELM_SCREEN_AWARENESS_PROBLEM_SOLVING_ENABLED": "false",
            "STORMHELM_SCREEN_AWARENESS_WORKFLOW_LEARNING_ENABLED": "false",
            "STORMHELM_SCREEN_AWARENESS_BRAIN_INTEGRATION_ENABLED": "false",
            "STORMHELM_SCREEN_AWARENESS_POWER_FEATURES_ENABLED": "false",
        },
    )

    assert config.screen_awareness.enabled is True
    assert config.screen_awareness.phase == "phase6"
    assert config.screen_awareness.planner_routing_enabled is True
    assert config.screen_awareness.debug_events_enabled is False
    assert config.screen_awareness.action_policy_mode == "trusted_action"
    assert config.screen_awareness.verification_enabled is False
    assert config.screen_awareness.memory_enabled is True
    assert config.screen_awareness.problem_solving_enabled is False
    assert config.screen_awareness.workflow_learning_enabled is False
    assert config.screen_awareness.brain_integration_enabled is False
    assert config.screen_awareness.power_features_enabled is False


def test_load_config_enables_unsafe_test_mode_overrides(temp_project_root: Path) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={"STORMHELM_UNSAFE_TEST_MODE": "true"},
    )

    filesystem_root = Path(temp_project_root.anchor or temp_project_root.root or "/").resolve()

    assert config.safety.unsafe_test_mode is True
    assert config.safety.allow_shell_stub is True
    assert config.safety.allowed_read_dirs == [filesystem_root]
    assert config.tools.enabled.shell_command is True
    assert config.software_control.privileged_operations_allowed is True
    assert config.software_control.trusted_sources_only is False
    assert config.screen_awareness.action_policy_mode == "trusted_action"


def test_load_config_defaults_discord_relay_to_enabled_baby_alias(temp_project_root: Path) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.discord_relay.enabled is True
    assert config.discord_relay.planner_routing_enabled is True
    assert config.discord_relay.preview_before_send is True
    assert "baby" in config.discord_relay.trusted_aliases
    assert config.discord_relay.trusted_aliases["baby"].label == "Baby"
    assert config.discord_relay.trusted_aliases["baby"].route_mode == "local_client_automation"


def test_load_config_applies_discord_relay_environment_overrides(temp_project_root: Path) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_DISCORD_RELAY_ENABLED": "false",
            "STORMHELM_DISCORD_RELAY_PLANNER_ROUTING_ENABLED": "false",
            "STORMHELM_DISCORD_RELAY_DEBUG_EVENTS_ENABLED": "false",
            "STORMHELM_DISCORD_RELAY_SCREEN_DISAMBIGUATION_ENABLED": "false",
            "STORMHELM_DISCORD_RELAY_PREVIEW_BEFORE_SEND": "false",
            "STORMHELM_DISCORD_RELAY_VERIFICATION_ENABLED": "false",
            "STORMHELM_DISCORD_RELAY_LOCAL_DM_ROUTE_ENABLED": "false",
            "STORMHELM_DISCORD_RELAY_BOT_WEBHOOK_ROUTES_ENABLED": "true",
        },
    )

    assert config.discord_relay.enabled is False
    assert config.discord_relay.planner_routing_enabled is False
    assert config.discord_relay.debug_events_enabled is False
    assert config.discord_relay.screen_disambiguation_enabled is False
    assert config.discord_relay.preview_before_send is False
    assert config.discord_relay.verification_enabled is False
    assert config.discord_relay.local_dm_route_enabled is False
    assert config.discord_relay.bot_webhook_routes_enabled is True


def test_load_config_uses_install_root_when_packaged(monkeypatch: pytest.MonkeyPatch, workspace_temp_dir: Path) -> None:
    install_root = workspace_temp_dir / "portable"
    resource_root = workspace_temp_dir / "bundle"
    data_dir = workspace_temp_dir / "userdata"

    (resource_root / "config").mkdir(parents=True, exist_ok=True)
    (resource_root / "assets").mkdir(parents=True, exist_ok=True)
    (install_root / "config").mkdir(parents=True, exist_ok=True)

    (resource_root / "config" / "default.toml").write_text(
        """
app_name = "Stormhelm"
release_channel = "dev"
environment = "packaged-test"
debug = false

[network]
host = "127.0.0.1"
port = 8765

[storage]
data_dir = ""

[logging]
level = "INFO"
file_name = "stormhelm.log"

[concurrency]
max_workers = 8
queue_size = 128
default_job_timeout_seconds = 20
history_limit = 500

[ui]
poll_interval_ms = 1500
hide_to_tray_on_close = true
ghost_shortcut = "Ctrl+Space"

[safety]
allowed_read_dirs = ["${PROJECT_ROOT}"]
allow_shell_stub = false

[tools]
max_file_read_bytes = 32768

[tools.enabled]
clock = true
system_info = true
file_reader = true
notes_write = true
echo = true
shell_command = false
        """.strip(),
        encoding="utf-8",
    )
    (install_root / "config" / "portable.toml").write_text(
        """
[network]
port = 9911
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "stormhelm.config.loader.discover_runtime",
        lambda: RuntimeDiscovery(
            is_frozen=True,
            mode="packaged",
            source_root=None,
            install_root=install_root,
            resource_root=resource_root,
        ),
    )
    monkeypatch.setattr(
        "stormhelm.config.loader._parse_env_file",
        lambda path: {},
    )

    config = load_config(env={"STORMHELM_DATA_DIR": str(data_dir)})

    assert config.runtime.mode == "packaged"
    assert config.project_root == install_root.resolve()
    assert config.runtime.install_root == install_root.resolve()
    assert config.runtime.resource_root == resource_root.resolve()
    assert config.runtime.assets_dir == (resource_root / "assets").resolve()
    assert config.runtime.portable_config_path == (install_root / "config" / "portable.toml").resolve()
    assert config.network.port == 9911
    assert config.storage.data_dir == data_dir.resolve()
    assert config.safety.allowed_read_dirs == [install_root.resolve()]
