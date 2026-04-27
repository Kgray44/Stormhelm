from __future__ import annotations

import asyncio

from stormhelm.core.events import EventBuffer
from stormhelm.core.voice import VoiceInterruptionIntent
from stormhelm.core.voice import VoiceInterruptionRequest
from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.ui.voice_surface import build_voice_ui_state

from tests.test_voice_spoken_confirmation import _create_pending
from tests.test_voice_wake_supervised_loop import _accepted_wake_session
from tests.test_voice_wake_supervised_loop import _service


def _audio_output() -> VoiceAudioOutput:
    return VoiceAudioOutput.from_bytes(b"voice bytes", format="mp3")


def test_interruption_classifier_is_context_sensitive() -> None:
    service, _events, _bridge = _service()

    assert (
        service.classify_voice_interruption("stop talking").intent
        == VoiceInterruptionIntent.STOP_OUTPUT_ONLY
    )
    assert (
        service.classify_voice_interruption(
            "cancel this request",
            context={"active_listen_window": True},
        ).intent
        == VoiceInterruptionIntent.CANCEL_LISTEN_WINDOW
    )
    assert (
        service.classify_voice_interruption(
            "no",
            context={"pending_confirmation": True},
        ).intent
        == VoiceInterruptionIntent.REJECT_PENDING_CONFIRMATION
    )
    assert (
        service.classify_voice_interruption("show me the plan").intent
        == VoiceInterruptionIntent.SHOW_PLAN
    )
    assert (
        service.classify_voice_interruption("cancel the task").intent
        == VoiceInterruptionIntent.CORE_ROUTED_CANCEL_REQUEST
    )
    assert (
        service.classify_voice_interruption("actually open the docs instead").intent
        == VoiceInterruptionIntent.CORRECTION
    )
    assert (
        service.classify_voice_interruption("sort of maybe").intent
        == VoiceInterruptionIntent.UNCLEAR
    )


def test_stop_talking_barge_in_stops_output_only_without_core_cancellation() -> None:
    events = EventBuffer(capacity=128)
    service, _unused_events, _bridge = _service()
    service.events = events
    service.playback_provider = MockPlaybackProvider(complete_immediately=False)
    started = asyncio.run(
        service.play_speech_output(_audio_output(), session_id="voice-session")
    )

    result = asyncio.run(
        service.handle_voice_interruption(
            VoiceInterruptionRequest(
                transcript="stop talking",
                source="wake_loop",
                session_id="voice-session",
                playback_id=started.playback_id,
                active_loop_id="loop-1",
            )
        )
    )

    assert result.status == "completed"
    assert result.intent == VoiceInterruptionIntent.STOP_OUTPUT_ONLY
    assert result.output_stopped is True
    assert result.affected_playback_id == started.playback_id
    assert result.core_task_cancelled is False
    assert result.core_result_mutated is False

    event_types = [record["event_type"] for record in events.recent(limit=128)]
    assert "voice.interruption_received" in event_types
    assert "voice.interruption_classified" in event_types
    assert "voice.output_interrupted" in event_types
    assert "voice.interruption_completed" in event_types
    assert "voice.core_task_cancelled" not in event_types


def test_cancel_listen_barge_in_closes_listen_capture_and_vad_without_stt_or_core() -> None:
    service, events, bridge = _service(vad_enabled=True)
    wake_session = _accepted_wake_session(service)
    window = asyncio.run(
        service.open_post_wake_listen_window(
            wake_session.wake_session_id,
            auto_start_capture=False,
        )
    )
    capture = asyncio.run(service.start_post_wake_capture(window.listen_window_id))
    asyncio.run(service.simulate_speech_started(capture_id=capture.capture_id))

    result = asyncio.run(
        service.handle_voice_interruption(
            VoiceInterruptionRequest(
                transcript="cancel this request",
                source="wake_loop",
                session_id="voice-session",
                listen_window_id=window.listen_window_id,
                capture_id=capture.capture_id,
                active_loop_id="loop-1",
            )
        )
    )

    assert result.status == "completed"
    assert result.intent == VoiceInterruptionIntent.CANCEL_LISTEN_WINDOW
    assert result.listen_window_cancelled is True
    assert result.capture_cancelled is True
    assert result.affected_listen_window_id == window.listen_window_id
    assert result.affected_capture_id == capture.capture_id
    assert service.get_active_post_wake_listen_window() is None
    assert service.get_active_vad_session() is None
    assert bridge.calls == []

    event_types = [record["event_type"] for record in events.recent(limit=128)]
    assert "voice.listen_window_interrupted" in event_types
    assert "voice.capture_interrupted" in event_types
    assert "voice.transcription_started" not in event_types
    assert "voice.core_request_started" not in event_types


def test_pending_confirmation_no_delegates_to_voice16_without_task_cancellation(
    trust_harness,
) -> None:
    service, events, _bridge = _service()
    service.events = events
    service.attach_trust_service(trust_harness["trust_service"])
    pending = _create_pending(
        trust_harness,
        request_id="voice-interruption-confirm-1",
        task_id="task-alpha",
        payload_hash="payload-alpha",
    )

    result = asyncio.run(
        service.handle_voice_interruption(
            VoiceInterruptionRequest(
                transcript="no",
                source="wake_loop",
                session_id="default",
                pending_confirmation_id=pending.approval_request_id,
                metadata={"task_id": "task-alpha", "payload_hash": "payload-alpha"},
            )
        )
    )

    assert result.status == "completed"
    assert result.intent == VoiceInterruptionIntent.REJECT_PENDING_CONFIRMATION
    assert result.confirmation_rejected is True
    assert result.affected_confirmation_id == pending.approval_request_id
    assert result.core_task_cancelled is False
    assert result.core_result_mutated is False
    assert service.last_spoken_confirmation_result is not None
    assert service.last_spoken_confirmation_result.status in {"rejected", "cancelled"}

    event_types = [record["event_type"] for record in events.recent(limit=128)]
    assert "voice.confirmation_interrupted" in event_types
    assert "voice.spoken_confirmation_rejected" in event_types
    assert "voice.core_task_cancelled" not in event_types


def test_core_cancellation_request_routes_through_core_without_direct_task_cancel() -> None:
    service, events, bridge = _service()

    result = asyncio.run(
        service.handle_voice_interruption(
            VoiceInterruptionRequest(
                transcript="cancel the task",
                source="wake_loop",
                session_id="voice-session",
                active_loop_id="loop-1",
            )
        )
    )

    assert result.status == "routed_to_core"
    assert result.intent == VoiceInterruptionIntent.CORE_ROUTED_CANCEL_REQUEST
    assert result.core_request_id is not None
    assert result.core_task_cancelled is False
    assert result.core_result_mutated is False
    assert bridge.calls and bridge.calls[-1]["message"] == "cancel the task"
    assert bridge.calls[-1]["input_context"]["voice"]["voice_interruption"]["intent"] == (
        "core_routed_cancel_request"
    )

    event_types = [record["event_type"] for record in events.recent(limit=128)]
    assert "voice.core_cancellation_requested" in event_types
    assert "voice.interruption_completed" in event_types


def test_correction_routes_as_new_voice_turn_and_preserves_prior_result() -> None:
    service, events, bridge = _service()
    first = asyncio.run(
        service.submit_manual_voice_turn(
            "open firefox",
            session_id="voice-session",
            metadata={"active_module": "deck"},
        )
    )

    result = asyncio.run(
        service.handle_voice_interruption(
            VoiceInterruptionRequest(
                transcript="actually open the docs instead",
                source="push_to_talk",
                session_id="voice-session",
            )
        )
    )

    assert result.status == "routed_to_core"
    assert result.intent == VoiceInterruptionIntent.CORRECTION
    assert result.routed_as_correction is True
    assert result.core_result_mutated is False
    assert first.core_result is not None
    assert bridge.calls[-1]["message"] == "actually open the docs instead"
    assert bridge.calls[-1]["input_context"]["voice"]["voice_interruption"]["intent"] == (
        "correction"
    )

    event_types = [record["event_type"] for record in events.recent(limit=128)]
    assert "voice.correction_routed" in event_types


def test_interruption_status_and_ui_payload_do_not_overclaim_task_cancellation() -> None:
    service, _events, _bridge = _service()

    asyncio.run(
        service.handle_voice_interruption(
            VoiceInterruptionRequest(
                transcript="cancel the task",
                source="test",
                session_id="voice-session",
            )
        )
    )

    snapshot = service.status_snapshot()
    interruption = snapshot["interruption"]
    ui_state = build_voice_ui_state({"voice": snapshot})

    assert interruption["last_interruption_intent"] == "core_routed_cancel_request"
    assert interruption["core_cancellation_requested"] is True
    assert interruption["core_task_cancelled_by_voice"] is False
    assert interruption["core_result_mutated_by_voice"] is False
    assert ui_state["interruption"]["core_task_cancelled_by_voice"] is False
    assert ui_state["interruption"]["core_result_mutated_by_voice"] is False
    assert "Task cancelled" not in str(ui_state)
    assert "Realtime active" not in str(ui_state)
    assert "Always listening" not in str(ui_state)
