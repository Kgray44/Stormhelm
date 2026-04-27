from __future__ import annotations

import asyncio

from stormhelm.core.voice.events import VoiceEventType
from stormhelm.ui.voice_surface import build_voice_ui_state

from tests.test_voice_spoken_confirmation import _create_pending
from tests.test_voice_wake_supervised_loop import _accepted_wake_session
from tests.test_voice_wake_supervised_loop import _service


def _payloads_for(events, event_type: str) -> list[dict[str, object]]:
    return [
        record["payload"]
        for record in events.recent(limit=128)
        if record["event_type"] == event_type
    ]


def _accepted_default_session_wake(service):
    asyncio.run(service.start_wake_monitoring(session_id="default"))
    wake = asyncio.run(
        service.simulate_wake_event(session_id="default", confidence=0.93)
    )
    return asyncio.run(service.accept_wake_event(wake.wake_event_id))


def test_voice14_vad_stops_when_post_wake_listen_window_expires() -> None:
    service, events, bridge = _service(vad_enabled=True)
    wake_session = _accepted_default_session_wake(service)
    window = asyncio.run(
        service.open_post_wake_listen_window(
            wake_session.wake_session_id,
            auto_start_capture=False,
        )
    )
    capture = asyncio.run(service.start_post_wake_capture(window.listen_window_id))

    active_vad = service.get_active_vad_session()
    assert active_vad is not None
    assert active_vad.listen_window_id == window.listen_window_id

    expired = asyncio.run(
        service.expire_post_wake_listen_window(
            window.listen_window_id,
            reason="operator_test_timeout",
        )
    )

    assert expired.status == "expired"
    assert expired.capture_id == capture.capture_id
    assert service.get_active_vad_session() is None
    assert service.last_capture_result.status == "cancelled"
    assert bridge.calls == []
    emitted = [record["event_type"] for record in events.recent(limit=128)]
    assert VoiceEventType.VAD_DETECTION_STOPPED.value in emitted
    assert VoiceEventType.POST_WAKE_LISTEN_EXPIRED.value in emitted
    assert "voice.transcription_started" not in emitted
    assert "voice.core_request_started" not in emitted


def test_voice15_wake_loop_correlates_listen_window_across_later_stage_events() -> None:
    service, events, _bridge = _service(vad_enabled=True)
    wake_session = _accepted_default_session_wake(service)

    result = asyncio.run(
        service.run_wake_supervised_voice_loop(
            wake_session.wake_session_id,
            finalize_with_vad=True,
            synthesize_response=True,
            play_response=True,
        )
    )

    assert result.ok is True
    assert result.listen_window_id is not None
    correlated_event_types = {
        "voice.capture_started",
        "voice.vad_detection_started",
        "voice.speech_activity_started",
        "voice.speech_activity_stopped",
        "voice.capture_stopped",
        "voice.capture_audio_created",
        "voice.audio_input_received",
        "voice.transcription_started",
        "voice.transcription_completed",
        "voice.core_request_started",
        "voice.core_request_completed",
        "voice.spoken_response_prepared",
    }
    correlated = [
        record["payload"]
        for record in events.recent(limit=128)
        if record["event_type"] in correlated_event_types
    ]

    assert correlated
    for payload in correlated:
        assert payload["listen_window_id"] == result.listen_window_id
        assert payload["privacy"]["no_raw_audio"] is True
        assert "raw_audio_bytes" not in str(payload.get("metadata", {})).lower()
    loop_payloads = _payloads_for(events, "voice.wake_supervised_loop_completed")
    assert loop_payloads
    assert loop_payloads[-1]["listen_window_id"] == result.listen_window_id


def test_voice16_post_wake_yes_confirms_fresh_pending_prompt_with_listen_provenance(
    trust_harness,
) -> None:
    service, events, bridge = _service(transcript="yes")
    service.attach_trust_service(trust_harness["trust_service"])
    pending = _create_pending(
        trust_harness,
        request_id="voice-post-wake-confirm",
        task_id="task-alpha",
        risk_level="low",
        required_strength="weak_ack",
        payload_hash="payload-alpha",
    )
    wake_session = _accepted_default_session_wake(service)

    result = asyncio.run(
        service.run_wake_supervised_voice_loop(wake_session.wake_session_id)
    )

    assert result.core_result_state == "confirmation_accepted"
    assert result.truth_flags["command_authority"] == "stormhelm_core"
    assert bridge.calls == []
    confirmation = service.last_spoken_confirmation_result
    assert confirmation is not None
    assert confirmation.status == "confirmed"
    assert confirmation.consumed_confirmation is True
    assert confirmation.action_executed is False
    assert confirmation.core_task_cancelled is False
    assert confirmation.core_result_mutated is False
    assert confirmation.metadata["request"]["metadata"]["post_wake_listen"][
        "listen_window_id"
    ] == result.listen_window_id

    for event_name in {
        "voice.spoken_confirmation_received",
        "voice.spoken_confirmation_classified",
        "voice.spoken_confirmation_bound",
        "voice.spoken_confirmation_accepted",
        "voice.spoken_confirmation_consumed",
    }:
        payloads = _payloads_for(events, event_name)
        assert payloads, event_name
        assert payloads[-1]["listen_window_id"] == result.listen_window_id
        if event_name in {
            "voice.spoken_confirmation_bound",
            "voice.spoken_confirmation_accepted",
            "voice.spoken_confirmation_consumed",
        }:
            assert (
                payloads[-1]["pending_confirmation_id"]
                == pending.approval_request_id
            )
        assert payloads[-1]["action_executed"] is False


def test_voice16_post_wake_yes_without_pending_confirmation_does_not_gain_authority() -> None:
    service, events, bridge = _service(transcript="yes")
    wake_session = _accepted_wake_session(service)

    result = asyncio.run(
        service.run_wake_supervised_voice_loop(wake_session.wake_session_id)
    )

    assert result.core_result_state == "no_pending_confirmation"
    assert bridge.calls == []
    confirmation = service.last_spoken_confirmation_result
    assert confirmation is not None
    assert confirmation.status == "no_pending_confirmation"
    assert confirmation.action_executed is False
    assert confirmation.core_task_cancelled is False
    assert confirmation.core_result_mutated is False
    rejected = _payloads_for(events, "voice.spoken_confirmation_rejected")
    assert rejected
    assert rejected[-1]["listen_window_id"] == result.listen_window_id
    assert rejected[-1].get("pending_confirmation_id") is None


def test_voice16_consumed_confirmation_cannot_be_reused_by_new_listen_window(
    trust_harness,
) -> None:
    service, _events, bridge = _service(transcript="confirm")
    service.attach_trust_service(trust_harness["trust_service"])
    pending = _create_pending(
        trust_harness,
        request_id="voice-post-wake-consume-once",
        task_id="task-alpha",
        payload_hash="payload-alpha",
        required_strength="explicit_confirm",
    )

    first_wake = _accepted_default_session_wake(service)
    first = asyncio.run(
        service.run_wake_supervised_voice_loop(first_wake.wake_session_id)
    )
    second_wake = _accepted_default_session_wake(service)
    second = asyncio.run(
        service.run_wake_supervised_voice_loop(second_wake.wake_session_id)
    )

    assert first.listen_window_id != second.listen_window_id
    assert first.core_result_state == "confirmation_accepted"
    assert second.core_result_state in {
        "confirmation_stale",
        "no_pending_confirmation",
        "confirmation_blocked",
    }
    assert service.last_spoken_confirmation_result is not None
    assert service.last_spoken_confirmation_result.consumed_confirmation is False
    assert bridge.calls == []


def test_cross_phase_payload_copy_keeps_listen_window_as_bounded_stage() -> None:
    payload = build_voice_ui_state(
        {
            "voice": {
                "availability": {"available": True, "provider_name": "openai"},
                "state": {"state": "idle"},
                "capture": {"enabled": True, "available": True},
                "post_wake_listen": {
                    "enabled": True,
                    "ready": True,
                    "active": True,
                    "active_listen_window_id": "listen-1",
                    "active_listen_window_status": "active",
                    "active_listen_window_expires_at": "2026-04-27T12:00:08Z",
                    "last_listen_window_id": "listen-1",
                    "last_listen_window_status": "active",
                    "last_listen_window_stop_reason": None,
                    "listen_window_capture_id": None,
                    "listen_window_audio_input_id": None,
                    "listen_window_does_not_route_core": True,
                    "continuous_listening": False,
                },
                "runtime_truth": {
                    "continuous_listening": False,
                    "realtime_used": False,
                    "listen_window_does_not_route_core": True,
                },
            }
        }
    )

    assert payload["ghost"]["primary_label"] == "Waiting for your request."
    assert payload["active_listen_window_id"] == "listen-1"
    assert payload["truth_flags"]["listen_window_does_not_route_core"] is True
    rendered = str(payload).lower()
    for forbidden in {
        "always listening",
        "realtime active",
        "command received",
        "i understood",
        "done",
        "verified",
    }:
        assert forbidden not in rendered
