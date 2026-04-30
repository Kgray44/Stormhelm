from __future__ import annotations

from stormhelm.core.latency import build_latency_trace
from stormhelm.core.provider_fallback import (
    ProviderAuditTiming,
    build_provider_latency_summary,
    sanitize_provider_payload_summary,
)


def test_l9_provider_latency_summary_is_attached_to_latency_trace() -> None:
    summary = build_provider_latency_summary(
        request_id="req-trace",
        provider_call_id="provider-call-trace",
        provider_name="mock",
        route_family="generic_provider",
        fallback_allowed=True,
        fallback_reason="open_ended_reasoning_allowed",
        provider_enabled=True,
        streaming_enabled=True,
        streaming_used=True,
        first_output_ms=42,
        total_provider_ms=84,
    )
    trace = build_latency_trace(
        metadata={"provider_latency_summary": summary.to_dict()},
        stage_timings_ms={"provider_fallback_ms": 84, "total_latency_ms": 100},
        route_family="generic_provider",
        provider_called=True,
    )
    payload = trace.to_summary_dict()

    assert payload["provider_latency_summary"]["provider_call_id"] == "provider-call-trace"
    assert payload["provider_first_output_ms"] == 42
    assert payload["provider_total_ms"] == 84
    assert payload["provider_streaming_used"] is True
    assert payload["native_route_blocked_by_provider"] is False


def test_l9_provider_audit_timing_records_allowed_denied_reason_without_payload() -> None:
    audit = ProviderAuditTiming(
        provider_call_id="provider-audit-1",
        request_id="req-audit",
        provider_name="mock",
        allowed=False,
        denied=True,
        denial_reason="provider_payload_not_safe",
        fallback_reason="unsafe_payload",
        payload_classification="private",
    ).to_dict()

    assert audit["allowed"] is False
    assert audit["denial_reason"] == "provider_payload_not_safe"
    assert audit["payload_redacted"] is True
    assert audit["secrets_logged"] is False
    assert "prompt" not in audit
    assert "api_key" not in audit


def test_l9_provider_payload_sanitizer_redacts_secrets_and_private_text() -> None:
    sanitized = sanitize_provider_payload_summary(
        {
            "prompt": "my private prompt",
            "message": "send this private body",
            "api_key": "sk-secret",
            "safe_mode": "analysis",
        }
    )

    encoded = str(sanitized).lower()
    assert "sk-secret" not in encoded
    assert "private prompt" not in encoded
    assert "send this private body" not in encoded
    assert sanitized["payload_redacted"] is True
    assert "safe_mode" in sanitized["payload_keys"]
