from __future__ import annotations

from stormhelm.core.subsystem_latency import SubsystemLatencyMode
from stormhelm.core.subsystem_latency import classify_subsystem_hot_path
from stormhelm.core.subsystem_latency import get_subsystem_cache_policy
from stormhelm.core.subsystem_latency import get_subsystem_latency_profile


def test_software_install_is_plan_first_trust_gated_and_async() -> None:
    profile = get_subsystem_latency_profile("software_control")
    decision = classify_subsystem_hot_path(
        subsystem_id="software_control",
        route_family="software_control",
        operation="install",
        metadata={"cache_hit": True, "cache_age_ms": 450.0},
    )

    assert profile.latency_mode == SubsystemLatencyMode.PLAN_FIRST
    assert profile.requires_trust is True
    assert profile.requires_verification is True
    assert decision.hot_path_name == "software_plan_ack"
    assert decision.async_continuation is True
    assert decision.live_probe_started is False
    assert decision.provider_fallback_used is False


def test_software_verification_hint_cache_is_labeled_not_success() -> None:
    policy = get_subsystem_cache_policy("software_verification_hint_cache")
    decision = classify_subsystem_hot_path(
        subsystem_id="software_control",
        route_family="software_control",
        operation="verify_installed",
        metadata={"cache_hit": True, "cache_age_ms": policy.ttl_ms + 1},
    )

    assert policy.safe_for_verification is False
    assert decision.cache_hit is True
    assert decision.stale is True
    assert decision.stale_data_label_required is True
    assert decision.result_claim == "cached_hint_not_verified_success"
