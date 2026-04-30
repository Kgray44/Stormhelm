from __future__ import annotations

from stormhelm.ui.bridge import UiBridge


def test_l9_provider_running_event_updates_ghost_compact_state(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_stream_event(
        {
            "cursor": 9101,
            "event_id": 9101,
            "event_family": "provider",
            "event_type": "provider_request_started",
            "severity": "info",
            "subsystem": "provider_fallback",
            "visibility_scope": "ghost_hint",
            "message": "Provider fallback running.",
            "payload": {
                "request_id": "req-provider-ui",
                "route_family": "generic_provider",
                "provider_fallback_state": "running",
                "fallback_reason": "open_ended_reasoning_allowed",
            },
        }
    )

    assert bridge.statusLine == "Provider fallback running."
    assert bridge.ghostPrimaryCard["routeLabel"] == "Provider Fallback"
    assert bridge.ghostPrimaryCard["resultState"] == "provider_running"
    assert "req-provider-ui" not in str(bridge.ghostPrimaryCard)


def test_l9_provider_timeout_event_updates_ghost_without_raw_payload_dump(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_stream_event(
        {
            "cursor": 9102,
            "event_id": 9102,
            "event_family": "provider",
            "event_type": "provider_timeout",
            "severity": "warning",
            "subsystem": "provider_fallback",
            "visibility_scope": "ghost_hint",
            "message": "Provider fallback timed out.",
            "payload": {
                "request_id": "req-provider-timeout",
                "route_family": "generic_provider",
                "provider_fallback_state": "timed_out",
                "failure_code": "provider_timeout_first_output",
                "raw_prompt": "very private prompt body",
            },
        }
    )

    assert bridge.statusLine == "Provider fallback timed out."
    assert bridge.ghostPrimaryCard["resultState"] == "timeout"
    assert "very private prompt body" not in str(bridge.ghostPrimaryCard)


def test_l9_provider_details_appear_in_deck_trace_not_ghost_debug(temp_config) -> None:
    bridge = UiBridge(temp_config)

    bridge.apply_stream_event(
        {
            "cursor": 9103,
            "event_id": 9103,
            "event_family": "provider",
            "event_type": "provider_first_output",
            "severity": "info",
            "subsystem": "provider_fallback",
            "visibility_scope": "deck_context",
            "message": "Provider first output received.",
            "payload": {
                "request_id": "req-provider-deck",
                "route_family": "generic_provider",
                "provider_fallback_state": "partial_result",
                "provider_budget_label": "provider_fallback",
                "first_output_ms": 88,
                "total_provider_ms": 0,
                "streaming_used": True,
                "fallback_reason": "open_ended_reasoning_allowed",
                "payload_summary": {"redacted": True},
            },
        }
    )

    trace = {entry["label"]: entry["value"] for entry in bridge.routeInspector["trace"]}
    assert trace["Provider State"] == "Partial Result"
    assert trace["Provider Budget"] == "provider_fallback"
    assert trace["First Output"] == "88 ms"
    assert "payload_summary" not in str(bridge.ghostPrimaryCard)
