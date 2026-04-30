from __future__ import annotations

from stormhelm.core.subsystem_latency import SubsystemLatencyMode
from stormhelm.core.subsystem_latency import classify_subsystem_hot_path
from stormhelm.core.subsystem_latency import get_subsystem_cache_policy
from stormhelm.core.subsystem_latency import get_subsystem_latency_profile


def test_discord_preview_is_fast_trust_gated_and_not_dispatch() -> None:
    profile = get_subsystem_latency_profile("discord_relay")
    decision = classify_subsystem_hot_path(
        subsystem_id="discord_relay",
        route_family="discord_relay",
        operation="preview",
        metadata={"cache_hit": True, "cache_age_ms": 80.0, "payload_fingerprint_checked": True},
    )

    assert profile.target_p50_ms <= 1200
    assert profile.requires_trust is True
    assert decision.latency_mode == SubsystemLatencyMode.PLAN_FIRST
    assert decision.hot_path_name == "discord_preview_first"
    assert decision.execution_claim == "preview_only_not_dispatched"
    assert decision.provider_fallback_used is False
    assert decision.async_continuation is False


def test_discord_dispatch_remains_async_and_approval_gated() -> None:
    policy = get_subsystem_cache_policy("discord_alias_fingerprint_cache")
    decision = classify_subsystem_hot_path(
        subsystem_id="discord_relay",
        route_family="discord_relay",
        operation="dispatch",
        metadata={"cache_hit": True, "cache_age_ms": policy.ttl_ms / 2},
    )

    assert decision.async_continuation is True
    assert decision.requires_trust is True
    assert decision.requires_verification is True
    assert decision.execution_claim == "dispatch_async_gated"
    assert decision.delivery_claim_allowed is False
