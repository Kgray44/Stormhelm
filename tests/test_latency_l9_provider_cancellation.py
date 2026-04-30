from __future__ import annotations

from stormhelm.core.provider_fallback import ProviderCallRegistry


def test_l9_active_provider_call_can_be_cancelled_when_supported() -> None:
    registry = ProviderCallRegistry()
    call = registry.start_call(
        request_id="req-cancel",
        provider_call_id="provider-call-cancel",
        cancellation_supported=True,
    )

    result = registry.cancel_call(call.provider_call_id, reason="operator_cancelled")

    assert result.cancellation_supported is True
    assert result.cancellation_attempted is True
    assert result.cancellation_succeeded is True
    assert result.final_provider_state == "cancelled"
    assert result.request_id == "req-cancel"


def test_l9_unsupported_provider_cancellation_reports_unsupported() -> None:
    registry = ProviderCallRegistry()
    call = registry.start_call(
        request_id="req-cancel-unsupported",
        provider_call_id="provider-call-unsupported",
        cancellation_supported=False,
    )

    result = registry.cancel_call(call.provider_call_id, reason="operator_cancelled")

    assert result.cancellation_supported is False
    assert result.cancellation_attempted is False
    assert result.cancellation_succeeded is False
    assert result.final_provider_state == "running"
    assert result.user_visible_message == "Provider cancellation is not supported."


def test_l9_completion_before_cancel_is_reported_honestly() -> None:
    registry = ProviderCallRegistry()
    call = registry.start_call(
        request_id="req-completed-before-cancel",
        provider_call_id="provider-call-complete",
        cancellation_supported=True,
    )
    registry.complete_call(call.provider_call_id)

    result = registry.cancel_call(call.provider_call_id, reason="operator_cancelled")

    assert result.cancellation_attempted is False
    assert result.cancellation_succeeded is False
    assert result.final_provider_state == "completed_before_cancel"


def test_l9_cancellation_does_not_cancel_unrelated_provider_call() -> None:
    registry = ProviderCallRegistry()
    registry.start_call(
        request_id="req-one",
        provider_call_id="provider-call-one",
        cancellation_supported=True,
    )
    call_two = registry.start_call(
        request_id="req-two",
        provider_call_id="provider-call-two",
        cancellation_supported=True,
    )

    registry.cancel_call("provider-call-one", reason="operator_cancelled")

    assert registry.call_state(call_two.provider_call_id) == "running"
