from __future__ import annotations

from stormhelm.core.latency_gates import build_latency_gate_report


def test_l10_release_posture_passes_when_blocking_gates_pass() -> None:
    report = build_latency_gate_report(
        [{"test_id": "native", "actual_route_family": "calculations", "total_latency_ms": 40, "provider_called": False}],
        profile="focused_hot_path_profile",
    )

    assert report["release_posture"]["posture"] in {"pass", "pass_with_warnings"}
    assert report["release_posture"]["hard_timeout_count"] == 0


def test_l10_release_posture_blocks_hard_timeout() -> None:
    report = build_latency_gate_report(
        [{"test_id": "timeout", "status": "hard_timeout", "actual_route_family": "hard_timeout", "total_latency_ms": 60000}],
        profile="full_kraken_profile",
    )

    assert report["release_posture"]["posture"] == "blocked_timeout"


def test_l10_release_posture_blocks_unknown_severe_outlier() -> None:
    report = build_latency_gate_report(
        [{"test_id": "forty-second-row", "actual_route_family": "calculations", "total_latency_ms": 41000, "provider_called": False}],
        profile="full_kraken_profile",
    )

    assert report["release_posture"]["posture"] == "blocked_unknown_outlier"
    assert report["outlier_investigation"][0]["classification"] == "unclassified"


def test_l10_invalid_run_when_required_profile_data_missing() -> None:
    report = build_latency_gate_report([], profile="focused_hot_path_profile")

    assert report["release_posture"]["posture"] == "not_enough_samples"
