from __future__ import annotations

import asyncio

from stormhelm.config.models import VoicePostWakeConfig
from stormhelm.core.voice.events import VoiceEventType
from stormhelm.core.voice.models import VoicePostWakeListenWindow
from stormhelm.ui.voice_surface import build_voice_ui_state

from tests.test_voice_wake_supervised_loop import _accepted_wake_session
from tests.test_voice_wake_supervised_loop import _service


def test_post_wake_config_defaults_are_disabled_and_bounded() -> None:
    config = VoicePostWakeConfig()

    assert config.enabled is False
    assert config.listen_window_ms == 8000
    assert config.max_utterance_ms == 30000
    assert config.auto_start_capture is True
    assert config.auto_submit_on_capture_complete is True
    assert config.allow_dev_post_wake is False


def test_post_wake_listen_window_model_preserves_stage_truth() -> None:
    window = VoicePostWakeListenWindow(
        wake_event_id="wake-event",
        wake_session_id="wake-session",
        wake_ghost_request_id="wake-ghost",
        session_id="voice-session",
        listen_window_ms=8000,
        max_utterance_ms=30000,
        expires_at="2026-04-27T12:00:08Z",
    )

    assert window.listen_window_id.startswith("voice-listen-window-")
    assert window.status == "active"
    assert window.capture_started is False
    assert window.stt_started is False
    assert window.core_routed is False
    assert window.command_authority_granted is False
    assert window.continuous_listening is False
    assert window.realtime_used is False
    assert window.raw_audio_present is False
    assert window.openai_used is False


def test_accepted_wake_opens_and_cancels_post_wake_listen_without_core_route() -> None:
    service, events, bridge = _service()
    wake_session = _accepted_wake_session(service)

    window = asyncio.run(
        service.open_post_wake_listen_window(
            wake_session.wake_session_id,
            auto_start_capture=False,
        )
    )

    assert window.status == "active"
    assert window.wake_event_id == wake_session.wake_event_id
    assert window.wake_session_id == wake_session.wake_session_id
    assert window.wake_ghost_request_id is not None
    assert window.capture_started is False
    assert service.get_active_post_wake_listen_window().listen_window_id == (
        window.listen_window_id
    )

    cancelled = asyncio.run(
        service.cancel_post_wake_listen_window(
            window.listen_window_id,
            reason="operator_dismissed",
        )
    )

    assert cancelled.status == "cancelled"
    assert cancelled.stop_reason == "operator_dismissed"
    assert cancelled.stt_started is False
    assert cancelled.core_routed is False
    assert bridge.calls == []
    assert service.get_active_post_wake_listen_window() is None

    emitted = [record["event_type"] for record in events.recent()]
    assert VoiceEventType.POST_WAKE_LISTEN_OPENED.value in emitted
    assert VoiceEventType.POST_WAKE_LISTEN_CANCELLED.value in emitted
    assert "voice.transcription_started" not in emitted
    assert "voice.core_request_started" not in emitted


def test_post_wake_capture_uses_existing_capture_boundary_and_metadata() -> None:
    service, events, _bridge = _service()
    wake_session = _accepted_wake_session(service)
    window = asyncio.run(
        service.open_post_wake_listen_window(
            wake_session.wake_session_id,
            auto_start_capture=False,
        )
    )

    capture_session = asyncio.run(
        service.start_post_wake_capture(window.listen_window_id)
    )

    assert capture_session.capture_id is not None
    assert capture_session.metadata["post_wake_listen"]["listen_window_id"] == (
        window.listen_window_id
    )
    assert capture_session.metadata["listen_window_id"] == window.listen_window_id

    capture_result = asyncio.run(
        service.stop_push_to_talk_capture(
            capture_session.capture_id,
            reason="post_wake_bounded_stop",
        )
    )
    completed = service.last_post_wake_listen_window

    assert capture_result.status == "completed"
    assert capture_result.metadata["listen_window_id"] == window.listen_window_id
    assert capture_result.audio_input.metadata["listen_window_id"] == (
        window.listen_window_id
    )
    assert completed.status == "captured"
    assert completed.capture_id == capture_session.capture_id
    assert completed.audio_input_id == capture_result.audio_input.input_id

    emitted = [record["event_type"] for record in events.recent()]
    assert VoiceEventType.POST_WAKE_LISTEN_CAPTURE_STARTED.value in emitted
    assert VoiceEventType.POST_WAKE_LISTEN_CAPTURED.value in emitted


def test_cancel_post_wake_listen_window_clears_active_capture() -> None:
    service, events, _bridge = _service()
    wake_session = _accepted_wake_session(service)
    window = asyncio.run(
        service.open_post_wake_listen_window(
            wake_session.wake_session_id,
            auto_start_capture=False,
        )
    )
    capture_session = asyncio.run(
        service.start_post_wake_capture(window.listen_window_id)
    )

    cancelled = asyncio.run(
        service.cancel_post_wake_listen_window(
            window.listen_window_id,
            reason="operator_cancelled_listen",
        )
    )

    assert cancelled.status == "cancelled"
    assert cancelled.capture_id == capture_session.capture_id
    assert service._active_capture() is None
    assert service.last_capture_result.status == "cancelled"
    assert service.last_capture_result.metadata["listen_window_id"] == (
        window.listen_window_id
    )
    assert cancelled.stt_started is False
    assert cancelled.core_routed is False
    emitted = [record["event_type"] for record in events.recent()]
    assert VoiceEventType.POST_WAKE_LISTEN_CANCELLED.value in emitted
    assert "voice.transcription_started" not in emitted
    assert "voice.core_request_started" not in emitted


def test_vad_events_bind_to_post_wake_listen_window() -> None:
    service, events, _bridge = _service(vad_enabled=True)
    wake_session = _accepted_wake_session(service)
    window = asyncio.run(
        service.open_post_wake_listen_window(
            wake_session.wake_session_id,
            auto_start_capture=False,
        )
    )
    capture_session = asyncio.run(
        service.start_post_wake_capture(window.listen_window_id)
    )

    asyncio.run(service.simulate_speech_started(capture_id=capture_session.capture_id))
    asyncio.run(service.simulate_speech_stopped(capture_id=capture_session.capture_id))

    activity_payloads = [
        record["payload"]
        for record in events.recent()
        if record["event_type"] in {"voice.speech_activity_started", "voice.speech_activity_stopped"}
    ]

    assert activity_payloads
    assert {payload["listen_window_id"] for payload in activity_payloads} == {
        window.listen_window_id
    }
    assert service.last_post_wake_listen_window.status == "captured"
    assert service.last_post_wake_listen_window.core_routed is False


def test_wake_supervised_loop_uses_concrete_post_wake_listen_window() -> None:
    service, events, bridge = _service(vad_enabled=True)
    wake_session = _accepted_wake_session(service)

    result = asyncio.run(
        service.run_wake_supervised_voice_loop(
            wake_session.wake_session_id,
            finalize_with_vad=True,
        )
    )

    assert result.ok is True
    assert result.listen_window_id is not None
    assert service.last_post_wake_listen_window.listen_window_id == result.listen_window_id
    assert service.last_post_wake_listen_window.status == "submitted"
    assert service.last_post_wake_listen_window.stt_started is True
    assert service.last_post_wake_listen_window.core_routed is True
    assert bridge.calls and bridge.calls[0]["message"] == "what time is it?"

    emitted = [record["event_type"] for record in events.recent()]
    assert emitted.index(VoiceEventType.POST_WAKE_LISTEN_OPENED.value) < emitted.index(
        "voice.capture_started"
    )
    assert VoiceEventType.POST_WAKE_LISTEN_SUBMITTED.value in emitted
    assert "voice.realtime_started" not in emitted


def test_post_wake_listen_status_and_ui_payload_distinguish_listen_from_capture() -> None:
    service, _events, _bridge = _service()
    wake_session = _accepted_wake_session(service)

    window = asyncio.run(
        service.open_post_wake_listen_window(
            wake_session.wake_session_id,
            auto_start_capture=False,
        )
    )

    snapshot = service.status_snapshot()
    post_wake = snapshot["post_wake_listen"]
    assert post_wake["enabled"] is True
    assert post_wake["ready"] is True
    assert post_wake["active_listen_window_id"] == window.listen_window_id
    assert post_wake["active_listen_window_status"] == "active"
    assert post_wake["listen_window_capture_id"] is None
    assert post_wake["listen_window_does_not_route_core"] is True
    assert post_wake["continuous_listening"] is False

    ui_state = build_voice_ui_state({"voice": snapshot})
    assert ui_state["post_wake_listen_enabled"] is True
    assert ui_state["post_wake_listen_ready"] is True
    assert ui_state["active_listen_window_id"] == window.listen_window_id
    assert ui_state["active_listen_window_status"] == "active"
    assert ui_state["truth_flags"]["listen_window_does_not_route_core"] is True
    assert ui_state["truth_flags"]["continuous_listening"] is False
    assert ui_state["truth_flags"]["realtime_used"] is False
    assert "always listening" not in str(ui_state).lower()

    cancelled = asyncio.run(
        service.cancel_post_wake_listen_window(window.listen_window_id)
    )
    cancelled_ui = build_voice_ui_state({"voice": service.status_snapshot()})
    assert cancelled.status == "cancelled"
    assert cancelled_ui["active_listen_window_id"] is None
    assert cancelled_ui["last_listen_window_status"] == "cancelled"
