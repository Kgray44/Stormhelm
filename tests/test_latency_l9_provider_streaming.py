from __future__ import annotations

from stormhelm.core.provider_fallback import (
    ProviderFallbackState,
    run_mock_provider_stream,
)


def test_l9_streaming_provider_emits_first_output_partial_and_completed_events() -> None:
    result = run_mock_provider_stream(
        request_id="req-stream",
        provider_call_id="provider-stream-1",
        chunks=("first safe bearing", "second safe bearing"),
    )

    event_types = [event["event_type"] for event in result.events]
    assert event_types == [
        "provider_request_started",
        "provider_first_output",
        "provider_partial_output",
        "provider_stream_completed",
    ]
    assert result.summary.streaming_used is True
    assert result.summary.fallback_state == ProviderFallbackState.COMPLETED.value


def test_l9_provider_partial_output_is_not_final_or_verification() -> None:
    result = run_mock_provider_stream(
        request_id="req-partial",
        provider_call_id="provider-stream-2",
        chunks=("partial only",),
        complete=False,
    )

    partial_events = [
        event for event in result.events if event["event_type"] == "provider_first_output"
    ]
    assert partial_events
    payload = partial_events[0]["payload"]
    assert payload["is_final"] is False
    assert payload["verification_claimed"] is False
    assert payload["tool_execution_allowed"] is False
    assert result.summary.fallback_state == ProviderFallbackState.PARTIAL_RESULT.value


def test_l9_stream_failure_produces_typed_failure_event() -> None:
    result = run_mock_provider_stream(
        request_id="req-stream-failed",
        provider_call_id="provider-stream-3",
        chunks=("first",),
        fail_at_chunk=1,
    )

    assert result.events[-1]["event_type"] == "provider_failed"
    assert result.events[-1]["payload"]["failure_code"] == "provider_stream_failed"
    assert result.summary.fallback_state == ProviderFallbackState.FAILED.value
