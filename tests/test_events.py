from __future__ import annotations

import threading
import time

from stormhelm.core.events import EventBuffer


def test_event_buffer_publish_builds_canonical_envelope() -> None:
    buffer = EventBuffer(capacity=8)

    event = buffer.publish(
        event_family="job",
        event_type="job.queued",
        session_id="default",
        subsystem="job_manager",
        severity="info",
        subject="job-1",
        visibility_scope="watch_surface",
        retention_class="bounded_recent",
        provenance={"channel": "job_manager", "kind": "direct_system_fact"},
        payload={"job_id": "job-1", "tool_name": "echo"},
        message="Queued job.",
    )

    serialized = event.to_dict()

    assert serialized["event_id"] == 1
    assert serialized["cursor"] == 1
    assert serialized["event_family"] == "job"
    assert serialized["event_type"] == "job.queued"
    assert serialized["timestamp"]
    assert serialized["created_at"] == serialized["timestamp"]
    assert serialized["session_id"] == "default"
    assert serialized["subsystem"] == "job_manager"
    assert serialized["source"] == "job_manager"
    assert serialized["severity"] == "info"
    assert serialized["level"] == "INFO"
    assert serialized["subject"] == "job-1"
    assert serialized["visibility_scope"] == "watch_surface"
    assert serialized["retention_class"] == "bounded_recent"
    assert serialized["payload"]["job_id"] == "job-1"
    assert serialized["provenance"]["channel"] == "job_manager"
    assert serialized["provenance"]["kind"] == "direct_system_fact"


def test_event_buffer_replay_reports_gap_when_requested_cursor_falls_outside_retention() -> None:
    buffer = EventBuffer(capacity=2)
    buffer.publish(message="First event.", source="core", level="INFO")
    buffer.publish(message="Second event.", source="core", level="INFO")
    buffer.publish(message="Third event.", source="core", level="INFO")

    replay = buffer.replay(cursor=0, limit=8)

    assert replay.gap_detected is True
    assert replay.earliest_cursor == 2
    assert replay.latest_cursor == 3
    assert [event.cursor for event in replay.events] == [2, 3]
    assert replay.to_dict()["events"][0]["cursor"] == 2


def test_event_buffer_state_reports_capacity_counts_and_visibility_totals() -> None:
    buffer = EventBuffer(capacity=4)
    buffer.publish(
        event_family="job",
        event_type="job.started",
        subsystem="job_manager",
        severity="info",
        visibility_scope="watch_surface",
        payload={"job_id": "job-1"},
        message="Started job.",
    )
    buffer.publish(
        event_family="network",
        event_type="network.gateway_latency_spike",
        subsystem="network",
        severity="warning",
        visibility_scope="systems_surface",
        payload={"kind": "gateway_latency_spike"},
        message="Gateway latency spike.",
    )

    snapshot = buffer.state_snapshot()

    assert snapshot["capacity"] == 4
    assert snapshot["buffered"] == 2
    assert snapshot["published_total"] == 2
    assert snapshot["expired_total"] == 0
    assert snapshot["family_totals"]["job"] == 1
    assert snapshot["family_totals"]["network"] == 1
    assert snapshot["visibility_totals"]["watch_surface"] == 1
    assert snapshot["visibility_totals"]["systems_surface"] == 1


def test_event_buffer_waits_for_next_event_cursor() -> None:
    buffer = EventBuffer(capacity=4)
    received: list[int] = []

    def publish_later() -> None:
        time.sleep(0.05)
        event = buffer.publish(
            event_family="lifecycle",
            event_type="lifecycle.core.started",
            subsystem="core",
            severity="info",
            visibility_scope="systems_surface",
            payload={"phase": "started"},
            message="Stormhelm core started.",
        )
        received.append(event.cursor)

    thread = threading.Thread(target=publish_later, daemon=True)
    thread.start()
    event = buffer.wait_for_next_event(cursor=0, timeout=1.0)
    thread.join(timeout=1.0)

    assert event is not None
    assert event.cursor == received[0] == 1
