from __future__ import annotations

from stormhelm.core.subsystem_latency import SubsystemLatencyMode
from stormhelm.core.subsystem_latency import classify_subsystem_hot_path
from stormhelm.core.subsystem_latency import get_subsystem_latency_profile


def test_network_status_returns_cached_status_with_freshness_not_live_claim() -> None:
    profile = get_subsystem_latency_profile("network_hardware_system")
    decision = classify_subsystem_hot_path(
        subsystem_id="network_hardware_system",
        route_family="network",
        operation="status",
        metadata={"cache_hit": True, "cache_age_ms": 1500.0},
    )

    assert profile.latency_mode == SubsystemLatencyMode.CACHED_STATUS
    assert decision.cache_hit is True
    assert decision.latency_mode == SubsystemLatencyMode.CACHED_STATUS
    assert decision.live_probe_started is False
    assert decision.result_claim == "cached_status_with_freshness"
    assert decision.freshness_label_required is True


def test_deeper_network_check_starts_live_probe_async() -> None:
    decision = classify_subsystem_hot_path(
        subsystem_id="network_hardware_system",
        route_family="network",
        operation="deep_probe",
        metadata={"cache_hit": False},
    )

    assert decision.latency_mode == SubsystemLatencyMode.ASYNC_FIRST
    assert decision.live_probe_started is True
    assert decision.async_continuation is True
    assert decision.result_claim == "live_probe_pending"
    assert decision.provider_fallback_used is False
