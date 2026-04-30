from __future__ import annotations

from stormhelm.core.subsystem_latency import SubsystemLatencyMode
from stormhelm.core.subsystem_latency import classify_subsystem_hot_path
from stormhelm.core.subsystem_latency import get_subsystem_latency_profile


def test_screen_simple_context_uses_fresh_snapshot_without_cloud_vision() -> None:
    profile = get_subsystem_latency_profile("screen_awareness")
    decision = classify_subsystem_hot_path(
        subsystem_id="screen_awareness",
        route_family="screen_awareness",
        operation="simple_context",
        metadata={"cache_hit": True, "cache_age_ms": 320.0, "cloud_vision_allowed": False},
    )

    assert profile.latency_mode == SubsystemLatencyMode.CACHED_STATUS
    assert decision.cache_hit is True
    assert decision.heavy_context_used is False
    assert decision.provider_fallback_used is False
    assert decision.cloud_vision_used is False
    assert decision.freshness_label_required is True


def test_clipboard_only_evidence_is_not_screen_truth() -> None:
    decision = classify_subsystem_hot_path(
        subsystem_id="screen_awareness",
        route_family="screen_awareness",
        operation="simple_context",
        metadata={"evidence_source": "clipboard", "cache_hit": True},
    )

    assert decision.result_claim == "clipboard_hint_not_screen_truth"
    assert decision.truth_clamp_applied is True
