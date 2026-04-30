from __future__ import annotations

import pytest

from stormhelm.core.latency_gates import (
    KnownSlowLane,
    classify_latency_outliers,
)


def test_l10_active_known_slow_lane_can_explain_matching_outlier() -> None:
    slow_lane = KnownSlowLane(
        slow_lane_id="ksl-active",
        route_family="software_control",
        lane_id="native_local_overall",
        reason="Package-manager verification is intentionally async.",
        expected_latency_ms=3000,
        max_accepted_latency_ms=6000,
        mitigation_plan="Keep plan ack fast and move live verification to async continuation.",
        created_at="2026-04-30T00:00:00Z",
        expires_at="2026-05-30T00:00:00Z",
        regression_test_reference="tests/test_latency_l8_software_hot_path.py",
    )

    outliers = classify_latency_outliers(
        [{"test_id": "software-slow", "actual_route_family": "software_control", "total_latency_ms": 4500}],
        lane_id="native_local_overall",
        threshold_ms=2000,
        p95_ms=1200,
        known_slow_lanes=[slow_lane],
        now="2026-04-30T12:00:00Z",
    )

    assert outliers[0]["classification"] == "known_slow_lane_active"
    assert outliers[0]["known_slow_lane_match"] == "ksl-active"


def test_l10_expired_known_slow_lane_fails_classification() -> None:
    slow_lane = KnownSlowLane(
        slow_lane_id="ksl-expired",
        route_family="software_control",
        lane_id="native_local_overall",
        reason="Old temporary allowance.",
        expected_latency_ms=3000,
        max_accepted_latency_ms=6000,
        mitigation_plan="Renew only with current evidence.",
        created_at="2026-03-01T00:00:00Z",
        expires_at="2026-04-01T00:00:00Z",
    )

    outliers = classify_latency_outliers(
        [{"test_id": "software-expired", "actual_route_family": "software_control", "total_latency_ms": 4500}],
        lane_id="native_local_overall",
        threshold_ms=2000,
        p95_ms=1200,
        known_slow_lanes=[slow_lane],
        now="2026-04-30T12:00:00Z",
    )

    assert outliers[0]["classification"] == "known_slow_lane_expired"


def test_l10_known_slow_lane_without_expiration_is_rejected() -> None:
    with pytest.raises(ValueError, match="expires_at"):
        KnownSlowLane(
            slow_lane_id="immortal",
            route_family="software_control",
            lane_id="native_local_overall",
            reason="No immortal known slow lanes.",
            expected_latency_ms=3000,
            max_accepted_latency_ms=6000,
            mitigation_plan="Add an expiration.",
            created_at="2026-04-30T00:00:00Z",
            expires_at="",
        )


def test_l10_known_slow_lane_without_mitigation_is_rejected() -> None:
    with pytest.raises(ValueError, match="mitigation_plan"):
        KnownSlowLane(
            slow_lane_id="no-plan",
            route_family="software_control",
            lane_id="native_local_overall",
            reason="Missing mitigation is not acceptable.",
            expected_latency_ms=3000,
            max_accepted_latency_ms=6000,
            mitigation_plan="",
            created_at="2026-04-30T00:00:00Z",
            expires_at="2026-05-30T00:00:00Z",
        )


def test_l10_unknown_outlier_remains_visible_and_blocking() -> None:
    outliers = classify_latency_outliers(
        [{"test_id": "mystery", "actual_route_family": "calculations", "total_latency_ms": 41000}],
        lane_id="native_local_overall",
        threshold_ms=5000,
        p95_ms=1000,
        known_slow_lanes=[],
        now="2026-04-30T12:00:00Z",
    )

    assert outliers[0]["classification"] == "unclassified"
    assert outliers[0]["recommended_action"] == "Investigate and classify before release."
