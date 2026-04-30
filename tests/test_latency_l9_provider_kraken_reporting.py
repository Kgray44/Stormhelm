from __future__ import annotations

from stormhelm.core.orchestrator.command_eval.report import _kraken_latency_report


def test_l9_kraken_separates_provider_latency_from_native_latency() -> None:
    rows = [
        {
            "test_id": "native-calc",
            "prompt": "2+2",
            "expected_route_family": "calculations",
            "actual_route_family": "calculations",
            "total_latency_ms": 30,
            "provider_called": False,
            "provider_call_count": 0,
            "provider_fallback_used": False,
            "provider_first_output_ms": None,
            "provider_total_ms": None,
        },
        {
            "test_id": "provider-open-ended",
            "prompt": "think broadly about naval metaphors",
            "expected_route_family": "generic_provider",
            "actual_route_family": "generic_provider",
            "total_latency_ms": 2200,
            "provider_called": True,
            "provider_call_count": 1,
            "provider_fallback_allowed": True,
            "provider_name": "mock",
            "provider_model_name": "mock-model",
            "provider_first_output_ms": 900,
            "provider_total_ms": 2100,
            "provider_streaming_used": True,
            "provider_partial_result_count": 1,
        },
    ]

    report = _kraken_latency_report(rows)  # type: ignore[arg-type]

    assert report["provider_calls_total"] == 1
    assert report["provider_calls_by_route_family"] == {"generic_provider": 1}
    assert report["provider_first_output_ms"]["p95"] == 900
    assert report["provider_total_ms"]["p95"] == 2100
    assert report["provider_latency_excluded_from_native_p95"] is True
    assert report["native_routes_with_unexpected_provider_calls"] == []


def test_l9_kraken_flags_unexpected_provider_call_on_native_route() -> None:
    rows = [
        {
            "test_id": "native-browser",
            "prompt": "open example.com",
            "expected_route_family": "browser_destination",
            "actual_route_family": "browser_destination",
            "total_latency_ms": 100,
            "provider_called": True,
            "provider_call_count": 1,
            "provider_first_output_ms": 25,
            "provider_total_ms": 50,
        }
    ]

    report = _kraken_latency_report(rows)  # type: ignore[arg-type]

    assert report["native_routes_with_unexpected_provider_calls"] == ["native-browser"]
    assert report["provider_blocked_by_native_route_count"] == 0
