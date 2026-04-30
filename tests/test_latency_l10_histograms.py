from __future__ import annotations

from stormhelm.core.latency_gates import build_route_family_histograms


def test_l10_histogram_computes_percentiles_and_max() -> None:
    rows = [
        {"actual_route_family": "calculations", "total_latency_ms": value, "status": "passed"}
        for value in [10, 20, 30, 40, 50]
    ]

    histograms = build_route_family_histograms(rows, group_by=("route_family",), low_sample_threshold=3)
    stats = histograms["route_family=calculations"]

    assert stats["count"] == 5
    assert stats["p50"] == 30
    assert stats["p90"] == 46
    assert stats["p95"] == 48
    assert stats["p99"] == 49.6
    assert stats["max"] == 50
    assert stats["low_confidence"] is False


def test_l10_histograms_group_by_route_family_and_lane() -> None:
    rows = [
        {"actual_route_family": "calculations", "lane_id": "native_hot_path", "total_latency_ms": 20},
        {"actual_route_family": "generic_provider", "lane_id": "provider_fallback", "total_latency_ms": 2000, "provider_called": True},
    ]

    histograms = build_route_family_histograms(rows, group_by=("route_family", "lane_id"), low_sample_threshold=2)

    assert set(histograms) == {
        "route_family=calculations|lane_id=native_hot_path",
        "route_family=generic_provider|lane_id=provider_fallback",
    }
    assert histograms["route_family=generic_provider|lane_id=provider_fallback"]["provider_call_count"] == 1
    assert histograms["route_family=calculations|lane_id=native_hot_path"]["low_confidence"] is True


def test_l10_histograms_track_budget_provider_async_and_correctness_counts() -> None:
    rows = [
        {"actual_route_family": "software_control", "total_latency_ms": 1000, "budget_exceeded": True, "async_continuation": True},
        {"actual_route_family": "software_control", "total_latency_ms": 1500, "provider_called": True, "status": "failed"},
        {"actual_route_family": "software_control", "total_latency_ms": 3000, "classification": "unclassified"},
    ]

    stats = build_route_family_histograms(rows, group_by=("route_family",))["route_family=software_control"]

    assert stats["budget_exceeded_count"] == 1
    assert stats["provider_call_count"] == 1
    assert stats["async_continuation_count"] == 1
    assert stats["correctness_failure_count"] == 1
    assert stats["unknown_classification_count"] == 1
