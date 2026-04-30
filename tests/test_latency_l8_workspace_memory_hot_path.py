from __future__ import annotations

from stormhelm.core.subsystem_latency import SubsystemLatencyMode
from stormhelm.core.subsystem_latency import classify_subsystem_hot_path
from stormhelm.core.subsystem_latency import get_subsystem_latency_profile


def test_workspace_continuity_summary_uses_cache_and_defers_deep_restore() -> None:
    profile = get_subsystem_latency_profile("workspace_tasks_memory")
    decision = classify_subsystem_hot_path(
        subsystem_id="workspace_tasks_memory",
        route_family="task_continuity",
        operation="continuity_summary",
        metadata={"cache_hit": True, "cache_age_ms": 900.0},
    )

    assert profile.target_p50_ms <= 1000
    assert decision.latency_mode == SubsystemLatencyMode.CACHED_STATUS
    assert decision.cache_hit is True
    assert decision.async_continuation is False
    assert decision.deep_restore_deferred is True
    assert decision.stale_data_label_required is True


def test_memory_retrieval_is_route_gated_for_unrelated_hot_paths() -> None:
    decision = classify_subsystem_hot_path(
        subsystem_id="workspace_tasks_memory",
        route_family="calculations",
        operation="unrelated_native_hot_path",
        metadata={"memory_retrieval_requested": False},
    )

    assert decision.memory_retrieval_used is False
    assert decision.heavy_context_used is False
    assert decision.provider_fallback_used is False
