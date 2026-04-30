from __future__ import annotations

from stormhelm.core.provider_fallback import (
    ProviderFallbackState,
    ProviderFailureCode,
    build_provider_latency_summary,
    default_provider_latency_budget,
)


def test_l9_provider_budget_has_strict_first_output_and_total_ceilings() -> None:
    budget = default_provider_latency_budget()

    assert budget.label == "provider_fallback"
    assert budget.target_first_output_ms == 1500
    assert budget.soft_first_output_ms == 3000
    assert budget.hard_first_output_ms == 6000
    assert budget.target_total_ms == 4000
    assert budget.soft_total_ms == 8000
    assert budget.hard_total_ms == 12000
    assert budget.stream_required_when_available is True


def test_l9_first_output_hard_timeout_is_typed_and_not_completed() -> None:
    summary = build_provider_latency_summary(
        request_id="req-first-timeout",
        provider_call_id="provider-call-1",
        provider_name="mock",
        route_family="generic_provider",
        fallback_allowed=True,
        provider_enabled=True,
        first_output_ms=6500,
        total_provider_ms=6500,
    )

    assert summary.timeout_hit is True
    assert summary.failure_code == ProviderFailureCode.TIMEOUT_FIRST_OUTPUT.value
    assert summary.fallback_state == ProviderFallbackState.TIMED_OUT.value
    assert summary.provider_budget_exceeded is True


def test_l9_total_hard_timeout_is_typed_after_first_output() -> None:
    summary = build_provider_latency_summary(
        request_id="req-total-timeout",
        provider_call_id="provider-call-2",
        provider_name="mock",
        route_family="generic_provider",
        fallback_allowed=True,
        provider_enabled=True,
        first_output_ms=800,
        total_provider_ms=13000,
    )

    assert summary.timeout_hit is True
    assert summary.failure_code == ProviderFailureCode.TIMEOUT_TOTAL.value
    assert summary.fallback_state == ProviderFallbackState.TIMED_OUT.value


def test_l9_soft_budget_keeps_partial_state_without_fake_completion() -> None:
    summary = build_provider_latency_summary(
        request_id="req-soft",
        provider_call_id="provider-call-3",
        provider_name="mock",
        route_family="generic_provider",
        fallback_allowed=True,
        provider_enabled=True,
        streaming_used=True,
        first_output_ms=3500,
        total_provider_ms=5000,
        partial_result_count=2,
    )

    assert summary.timeout_hit is False
    assert summary.provider_budget_exceeded is True
    assert summary.fallback_state == ProviderFallbackState.PARTIAL_RESULT.value
    assert summary.partial_result_count == 2
