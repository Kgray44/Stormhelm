from __future__ import annotations

import asyncio

from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.models import VoiceWakeGhostRequest
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge
from tests.test_voice_wake_service import _openai_config
from tests.test_voice_wake_service import _voice_config


def test_accepted_wake_session_creates_wake_ghost_request_without_side_effects() -> (
    None
):
    events = EventBuffer(capacity=64)
    service = build_voice_subsystem(
        _voice_config(cooldown_ms=0), _openai_config(), events=events
    )
    bridge = RecordingCoreBridge()
    service.attach_core_bridge(bridge)

    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    event = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.93)
    )
    session = asyncio.run(service.accept_wake_event(event.wake_event_id))
    ghost = service.get_active_wake_ghost_request()

    assert isinstance(ghost, VoiceWakeGhostRequest)
    assert ghost.status == "shown"
    assert ghost.wake_event_id == event.wake_event_id
    assert ghost.wake_session_id == session.wake_session_id
    assert ghost.session_id == "voice-session"
    assert ghost.requested_mode == "ghost"
    assert ghost.wake_phrase == "Stormhelm"
    assert ghost.confidence == 0.93
    assert ghost.capture_started is False
    assert ghost.stt_started is False
    assert ghost.core_routed is False
    assert ghost.voice_turn_created is False
    assert ghost.command_authority_granted is False
    assert ghost.openai_used is False
    assert ghost.raw_audio_present is False
    assert service.capture_provider.get_active_capture() is None
    assert service.provider.network_call_count == 0
    assert bridge.calls == []

    emitted = [record["event_type"] for record in events.recent()]
    assert "voice.wake_ghost_requested" in emitted
    assert "voice.wake_ghost_shown" in emitted
    assert "voice.capture_started" not in emitted
    assert "voice.transcription_started" not in emitted
    assert "voice.core_request_started" not in emitted
    assert "voice.synthesis_started" not in emitted
    assert "voice.playback_started" not in emitted


def test_rejected_and_cooldown_wake_do_not_create_wake_ghost_request() -> None:
    service = build_voice_subsystem(_voice_config(cooldown_ms=2500), _openai_config())
    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))

    low = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.2)
    )
    low_session = asyncio.run(service.accept_wake_event(low.wake_event_id))
    accepted = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.95)
    )
    accepted_session = asyncio.run(service.accept_wake_event(accepted.wake_event_id))
    cooldown = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.96)
    )
    cooldown_session = asyncio.run(service.accept_wake_event(cooldown.wake_event_id))

    assert low.rejected_reason == "low_confidence"
    assert low_session.status == "rejected"
    assert accepted.rejected_reason is None
    assert accepted_session.status == "active"
    assert cooldown.rejected_reason == "cooldown_active"
    assert cooldown_session.status == "rejected"
    assert service.last_wake_ghost_request is not None
    assert service.last_wake_ghost_request.wake_event_id == accepted.wake_event_id
    assert service.get_active_wake_ghost_request() is not None
    assert (
        service.get_active_wake_ghost_request().wake_event_id == accepted.wake_event_id
    )


def test_wake_ghost_expires_and_cancels_with_wake_session() -> None:
    service = build_voice_subsystem(_voice_config(cooldown_ms=0), _openai_config())
    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))

    event = asyncio.run(service.simulate_wake_event(session_id="voice-session"))
    session = asyncio.run(service.accept_wake_event(event.wake_event_id))
    expired = asyncio.run(service.expire_wake_session(session.wake_session_id))

    assert expired.status == "expired"
    assert service.get_active_wake_ghost_request() is None
    assert service.last_wake_ghost_request is not None
    assert service.last_wake_ghost_request.status == "expired"
    assert service.last_wake_ghost_request.capture_started is False
    assert service.last_wake_ghost_request.core_routed is False

    second = asyncio.run(service.simulate_wake_event(session_id="voice-session"))
    second_session = asyncio.run(service.accept_wake_event(second.wake_event_id))
    cancelled = asyncio.run(
        service.cancel_wake_ghost(
            second_session.wake_session_id,
            reason="operator_dismissed",
        )
    )

    assert cancelled.status == "cancelled"
    assert cancelled.reason == "operator_dismissed"
    assert service.get_active_wake_ghost_request() is None
    assert service.active_wake_session is None
    assert service.last_wake_session is not None
    assert service.last_wake_session.status == "cancelled"


def test_wake_ghost_status_snapshot_preserves_presentation_truth() -> None:
    service = build_voice_subsystem(_voice_config(cooldown_ms=0), _openai_config())
    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    event = asyncio.run(service.simulate_wake_event(session_id="voice-session"))
    session = asyncio.run(service.accept_wake_event(event.wake_event_id))

    snapshot = service.status_snapshot()
    wake_ghost = snapshot["wake_ghost"]

    assert wake_ghost["active"] is True
    assert wake_ghost["status"] == "shown"
    assert wake_ghost["wake_event_id"] == event.wake_event_id
    assert wake_ghost["wake_session_id"] == session.wake_session_id
    assert wake_ghost["wake_status_label"] == "Bearing acquired."
    assert wake_ghost["capture_started"] is False
    assert wake_ghost["stt_started"] is False
    assert wake_ghost["core_routed"] is False
    assert wake_ghost["voice_turn_created"] is False
    assert wake_ghost["no_post_wake_capture"] is True
    assert wake_ghost["no_vad"] is True
    assert wake_ghost["no_realtime"] is True
    assert wake_ghost["no_command_from_wake"] is True
    assert wake_ghost["openai_used"] is False
    assert "raw_audio" not in str(wake_ghost).lower()
