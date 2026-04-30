from __future__ import annotations

from stormhelm.core.latency_gates import classify_latency_outliers


def test_l10_max_outlier_includes_slowest_stage() -> None:
    outliers = classify_latency_outliers(
        [
            {
                "test_id": "slow-route",
                "actual_route_family": "calculations",
                "total_latency_ms": 4200,
                "longest_stage": "route_handler_ms",
                "longest_stage_ms": 3900,
                "budget_label": "instant",
                "budget_exceeded": True,
            }
        ],
        lane_id="native_local_overall",
        threshold_ms=2000,
        p95_ms=1500,
    )

    assert outliers[0]["longest_stage"] == "route_handler_ms"
    assert outliers[0]["longest_stage_ms"] == 3900
    assert outliers[0]["p95_delta_ms"] == 2700


def test_l10_provider_outlier_classified_provider_latency() -> None:
    outliers = classify_latency_outliers(
        [{"test_id": "provider", "actual_route_family": "generic_provider", "provider_called": True, "total_latency_ms": 9000}],
        lane_id="provider_fallback",
        threshold_ms=3000,
        p95_ms=3000,
    )

    assert outliers[0]["classification"] == "provider_latency"


def test_l10_hard_timeout_classified_separately() -> None:
    outliers = classify_latency_outliers(
        [{"test_id": "timeout", "status": "hard_timeout", "actual_route_family": "hard_timeout", "total_latency_ms": 60000}],
        lane_id="full_kraken_suite",
        threshold_ms=5000,
        p95_ms=3000,
    )

    assert outliers[0]["classification"] == "hard_timeout"


def test_l10_correctness_failure_not_hidden_as_latency_failure() -> None:
    outliers = classify_latency_outliers(
        [{"test_id": "wrong-route", "status": "failed", "failure_category": "wrong_route_family", "actual_route_family": "generic_provider", "total_latency_ms": 100}],
        lane_id="command_eval_correctness_latency",
        threshold_ms=50,
        p95_ms=50,
    )

    assert outliers[0]["classification"] == "correctness_failure"


def test_l10_route_handler_slow_classification_is_specific() -> None:
    outliers = classify_latency_outliers(
        [{"test_id": "handler", "actual_route_family": "screen_awareness", "total_latency_ms": 2500, "longest_stage": "route_handler_ms"}],
        lane_id="native_local_overall",
        threshold_ms=2000,
        p95_ms=1200,
    )

    assert outliers[0]["classification"] == "route_handler_slow"
