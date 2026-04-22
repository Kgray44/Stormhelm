from __future__ import annotations

from stormhelm.ui.client import CoreApiClient


def test_core_api_client_parses_stream_events_and_tracks_cursor() -> None:
    client = CoreApiClient("http://stormhelm.test")
    states: list[dict] = []
    events: list[dict] = []
    gaps: list[dict] = []
    client.stream_state_received.connect(states.append)
    client.stream_event_received.connect(events.append)
    client.stream_gap_received.connect(gaps.append)

    client._process_stream_bytes(
        (
            b"event: stormhelm.stream_state\n"
            b"data: {\"status\":\"connected\",\"transport\":\"sse\",\"reconnect_attempts\":0}\n\n"
            b"id: 9\n"
            b"event: stormhelm.event\n"
            b"data: {\"cursor\":9,\"event_id\":9,\"event_family\":\"job\",\"event_type\":\"job.completed\",\"severity\":\"info\",\"subsystem\":\"job_manager\"}\n\n"
        )
    )

    assert states[0]["status"] == "connected"
    assert events[0]["cursor"] == 9
    assert events[0]["event_family"] == "job"
    assert client.last_event_cursor == 9
    assert gaps == []


def test_core_api_client_emits_replay_gap_from_stream_control_frame() -> None:
    client = CoreApiClient("http://stormhelm.test")
    gaps: list[dict] = []
    client.stream_gap_received.connect(gaps.append)

    client._process_stream_bytes(
        (
            b"event: stormhelm.replay_gap\n"
            b"data: {\"expired\":true,\"requested_cursor\":2,\"earliest_cursor\":6,\"latest_cursor\":8,\"dropped_event_count\":3}\n\n"
        )
    )

    assert gaps == [
        {
            "expired": True,
            "requested_cursor": 2,
            "earliest_cursor": 6,
            "latest_cursor": 8,
            "dropped_event_count": 3,
        }
    ]
