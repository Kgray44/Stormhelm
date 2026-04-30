from __future__ import annotations

from stormhelm.core.latency_gates import build_latency_gate_report


def test_l10_unexpected_provider_call_in_native_route_blocks_release() -> None:
    report = build_latency_gate_report(
        [
            {
                "test_id": "native-provider-hijack",
                "actual_route_family": "calculations",
                "provider_called": True,
                "provider_call_count": 1,
                "total_latency_ms": 50,
            }
        ],
        profile="focused_hot_path_profile",
    )

    assert report["provider_fallback_metrics"]["unexpected_provider_native_call_count"] == 1
    assert report["release_posture"]["posture"] == "blocked_provider_native_hijack"


def test_l10_provider_timing_is_separated_from_native_timing() -> None:
    report = build_latency_gate_report(
        [
            {"test_id": "native", "actual_route_family": "calculations", "total_latency_ms": 20, "provider_called": False},
            {
                "test_id": "provider",
                "actual_route_family": "generic_provider",
                "total_latency_ms": 2400,
                "provider_called": True,
                "provider_call_count": 1,
                "provider_first_output_ms": 900,
                "provider_total_ms": 2200,
            },
        ],
        profile="provider_profile",
    )

    assert report["provider_fallback_metrics"]["provider_first_output_ms"]["p95"] == 900
    assert report["lane_summary"]["native_local_overall"]["count"] == 1
    assert report["lane_summary"]["provider_fallback"]["count"] == 1


def test_l10_live_provider_timing_is_not_run_when_not_executed() -> None:
    report = build_latency_gate_report([], profile="provider_profile", live_provider_run=False)

    assert report["provider_fallback_metrics"]["live_provider_timing_status"] == "not_run"


def test_l10_mock_provider_timing_not_mislabeled_live() -> None:
    report = build_latency_gate_report(
        [{"test_id": "provider-mock", "actual_route_family": "generic_provider", "provider_called": True, "provider_first_output_ms": 1, "provider_total_ms": 4, "provider_timing_mode": "mock"}],
        profile="provider_profile",
    )

    assert report["provider_fallback_metrics"]["provider_timing_mode"] == "mock"
    assert report["provider_fallback_metrics"]["live_provider_timing_status"] == "not_run"
