from __future__ import annotations

import pytest

from stormhelm.core.latency_gates import (
    LatencyGate,
    LatencyGateResult,
    LatencyGateSeverity,
    LatencyGateStatistic,
    LatencyReleasePosture,
    determine_release_posture,
)


def test_l10_latency_gate_serializes_and_evaluates_p95_failure() -> None:
    gate = LatencyGate(
        gate_id="native.local.p95",
        lane_id="native_local_overall",
        metric_name="total_latency_ms",
        statistic=LatencyGateStatistic.P95,
        threshold_ms=2000,
        severity=LatencyGateSeverity.RELEASE_BLOCKING,
        applies_to="focused_suite",
    )

    result = gate.evaluate(
        values=[120, 400, 2600, 3100],
        sample_rows=[
            {"test_id": "fast", "total_latency_ms": 120},
            {"test_id": "slow", "total_latency_ms": 3100},
        ],
    )

    assert gate.to_dict()["gate_id"] == "native.local.p95"
    assert result.passed is False
    assert result.blocking_release is True
    assert result.observed_value > result.threshold_value
    assert result.to_dict()["severity"] == "release_blocking"


def test_l10_release_posture_is_pass_with_warnings_for_warning_only() -> None:
    warning = LatencyGateResult(
        gate_id="native.max.warning",
        lane_id="native_local_overall",
        passed=False,
        severity=LatencyGateSeverity.WARNING.value,
        observed_value=5100,
        threshold_value=5000,
        sample_count=10,
        message="Native max exceeded warning threshold.",
    )

    posture = determine_release_posture([warning], hard_timeout_count=0)

    assert posture["posture"] == LatencyReleasePosture.PASS_WITH_WARNINGS.value
    assert posture["gates_warned"] == 1
    assert posture["gates_failed"] == 0


def test_l10_release_blocking_gate_blocks_release_posture() -> None:
    failure = LatencyGateResult(
        gate_id="native.local.p95",
        lane_id="native_local_overall",
        passed=False,
        severity=LatencyGateSeverity.RELEASE_BLOCKING.value,
        observed_value=3000,
        threshold_value=2000,
        sample_count=20,
        message="Native p95 regressed.",
    )

    posture = determine_release_posture([failure], hard_timeout_count=0)

    assert posture["posture"] == LatencyReleasePosture.BLOCKED_LATENCY_REGRESSION.value
    assert posture["blocking_reasons"] == ["native.local.p95: Native p95 regressed."]


def test_l10_not_enough_samples_is_explicit_warning() -> None:
    gate = LatencyGate(
        gate_id="native.local.p95",
        lane_id="native_local_overall",
        metric_name="total_latency_ms",
        statistic=LatencyGateStatistic.P95,
        threshold_ms=2000,
        min_sample_count=5,
        severity=LatencyGateSeverity.FAIL,
        applies_to="focused_suite",
    )

    result = gate.evaluate(values=[100, 200], sample_rows=[])

    assert result.passed is False
    assert result.severity == LatencyGateSeverity.WARNING.value
    assert "Not enough samples" in result.message
