from __future__ import annotations

from stormhelm.core.subsystem_latency import SubsystemLatencyMode
from stormhelm.core.subsystem_latency import classify_subsystem_hot_path
from stormhelm.core.subsystem_latency import get_subsystem_cache_policy
from stormhelm.core.subsystem_latency import get_subsystem_latency_profile
from stormhelm.core.subsystem_latency import list_subsystem_latency_profiles


REQUIRED_L8_SUBSYSTEMS = {
    "calculations",
    "browser_destination",
    "software_control",
    "discord_relay",
    "screen_awareness",
    "workspace_tasks_memory",
    "network_hardware_system",
}


def test_l8_required_subsystems_have_explicit_profiles_and_cache_policies() -> None:
    profiles = {profile.subsystem_id: profile for profile in list_subsystem_latency_profiles()}

    assert REQUIRED_L8_SUBSYSTEMS.issubset(profiles)
    for subsystem_id in REQUIRED_L8_SUBSYSTEMS:
        profile = profiles[subsystem_id]
        assert profile.route_family
        assert profile.hot_path_name
        assert profile.target_p50_ms > 0
        assert profile.target_p95_ms >= profile.target_p50_ms
        assert profile.soft_ceiling_ms >= profile.target_p95_ms
        assert profile.hard_ceiling_ms >= profile.soft_ceiling_ms
        assert profile.trace_stage_names
        assert profile.provider_fallback_allowed is False
        assert profile.heavy_context_allowed is False or subsystem_id in {
            "screen_awareness",
            "workspace_tasks_memory",
        }
        assert profile.cache_policy_id

        policy = get_subsystem_cache_policy(profile.cache_policy_id)
        assert policy.cache_policy_id == profile.cache_policy_id
        assert policy.subsystem_id == subsystem_id
        assert policy.ttl_ms >= 0
        assert policy.provenance_required is True
        assert policy.stale_label_required is policy.stale_allowed
        assert {"raw_audio", "raw_screenshot", "private_message_body"}.issubset(
            set(policy.unsafe_payload_fields)
        )


def test_l8_profiles_match_required_latency_shapes() -> None:
    calculations = get_subsystem_latency_profile("calculations")
    browser = get_subsystem_latency_profile("browser_destination")
    software = get_subsystem_latency_profile("software_control")
    discord = get_subsystem_latency_profile("discord_relay")
    screen = get_subsystem_latency_profile("screen_awareness")
    workspace = get_subsystem_latency_profile("workspace_tasks_memory")
    network = get_subsystem_latency_profile("network_hardware_system")

    assert calculations.latency_mode == SubsystemLatencyMode.INSTANT
    assert calculations.target_p50_ms <= 100
    assert calculations.provider_fallback_allowed is False
    assert calculations.heavy_context_allowed is False

    assert browser.latency_mode == SubsystemLatencyMode.PLAN_FIRST
    assert browser.target_p50_ms <= 300
    assert browser.async_policy_id == "browser_external_open_async_status"

    assert software.latency_mode == SubsystemLatencyMode.PLAN_FIRST
    assert software.target_p50_ms <= 1000
    assert software.requires_trust is True
    assert software.requires_verification is True

    assert discord.latency_mode == SubsystemLatencyMode.PLAN_FIRST
    assert discord.target_p50_ms <= 1200
    assert discord.requires_trust is True

    assert screen.latency_mode == SubsystemLatencyMode.CACHED_STATUS
    assert screen.stale_data_allowed is True
    assert screen.stale_data_label_required is True

    assert workspace.latency_mode == SubsystemLatencyMode.CACHED_STATUS
    assert workspace.async_policy_id == "workspace_deep_restore_async"

    assert network.latency_mode == SubsystemLatencyMode.CACHED_STATUS
    assert network.async_policy_id == "network_live_probe_async"


def test_l8_hot_path_decisions_distinguish_cached_status_from_live_probe() -> None:
    cached_status = classify_subsystem_hot_path(
        subsystem_id="network_hardware_system",
        route_family="network",
        operation="status",
        metadata={"cache_hit": True, "cache_age_ms": 220.0},
    )
    live_probe = classify_subsystem_hot_path(
        subsystem_id="network_hardware_system",
        route_family="network",
        operation="deep_probe",
        metadata={"cache_hit": False},
    )

    assert cached_status.latency_mode == SubsystemLatencyMode.CACHED_STATUS
    assert cached_status.cache_hit is True
    assert cached_status.cache_age_ms == 220.0
    assert cached_status.live_probe_started is False
    assert cached_status.async_continuation is False

    assert live_probe.latency_mode == SubsystemLatencyMode.ASYNC_FIRST
    assert live_probe.live_probe_started is True
    assert live_probe.async_continuation is True
    assert live_probe.cache_hit is False
    assert live_probe.stale_data_label_required is True


def test_l8_verification_cache_policy_is_stricter_than_display_status_cache() -> None:
    display_policy = get_subsystem_cache_policy("network_status_snapshot_cache")
    verification_policy = get_subsystem_cache_policy("software_verification_hint_cache")

    assert display_policy.safe_for_user_display is True
    assert display_policy.safe_for_verification is False
    assert display_policy.stale_allowed is True

    assert verification_policy.safe_for_verification is False
    assert verification_policy.stale_allowed is True
    assert verification_policy.stale_label_required is True
    assert verification_policy.ttl_ms < display_policy.max_stale_age_ms
