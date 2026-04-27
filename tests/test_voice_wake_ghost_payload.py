from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from stormhelm.core.api.app import create_app
from stormhelm.core.voice.service import build_voice_subsystem
from stormhelm.ui.voice_surface import build_voice_ui_state

from tests.test_voice_wake_service import _openai_config
from tests.test_voice_wake_service import _voice_config


def _service_with_wake_ghost():
    service = build_voice_subsystem(_voice_config(cooldown_ms=0), _openai_config())
    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    event = asyncio.run(service.simulate_wake_event(session_id="voice-session"))
    session = asyncio.run(service.accept_wake_event(event.wake_event_id))
    return service, event, session


def test_wake_ghost_appears_in_backend_derived_ui_state_without_capture_claims() -> (
    None
):
    service, event, session = _service_with_wake_ghost()

    ui_state = build_voice_ui_state(service.status_snapshot())

    assert ui_state["wake_ghost_requested"] is True
    assert ui_state["wake_ghost_active"] is True
    assert ui_state["wake_ghost_status"] == "shown"
    assert ui_state["wake_event_id"] == event.wake_event_id
    assert ui_state["wake_session_id"] == session.wake_session_id
    assert ui_state["wake_phrase"] == "Stormhelm"
    assert ui_state["wake_status_label"] == "Bearing acquired."
    assert ui_state["wake_prompt_text"] == "Ghost ready."
    assert ui_state["voice_current_phase"] == "wake_ghost_active"
    assert ui_state["voice_core_state"] == "wake_ready"
    assert ui_state["capture_started"] is False
    assert ui_state["stt_started"] is False
    assert ui_state["core_routed"] is False
    assert ui_state["truth_flags"]["no_post_wake_capture"] is True
    assert ui_state["truth_flags"]["no_command_from_wake"] is True
    assert ui_state["ghost"]["primary_label"] == "Bearing acquired."
    assert ui_state["ghost"]["secondary_label"] == "Ghost ready."
    assert "voice.cancelWakeGhost" in {
        action["localAction"] for action in ui_state["ghost"]["actions"]
    }
    assert ui_state["last_transcript_preview"] == ""
    assert ui_state["last_core_result_state"] is None
    assert "raw_audio" not in str(ui_state).lower()


def test_wake_ghost_copy_avoids_command_or_listening_claims() -> None:
    service, _, _ = _service_with_wake_ghost()
    ui_state = build_voice_ui_state(service.status_snapshot())
    rendered = str(ui_state).lower()

    forbidden = [
        "always listening",
        "wake command mode",
        "realtime active",
        "i heard you",
        "i understood",
        "listening to your request",
        "command received",
        "routing through core",
        "how can i help",
        "ahoy",
    ]

    for phrase in forbidden:
        assert phrase not in rendered


def test_wake_ghost_cancel_clears_active_ui_state() -> None:
    service, _, session = _service_with_wake_ghost()

    asyncio.run(service.cancel_wake_ghost(session.wake_session_id))
    ui_state = build_voice_ui_state(service.status_snapshot())

    assert ui_state["wake_ghost_active"] is False
    assert ui_state["wake_ghost_status"] == "cancelled"
    assert ui_state["voice_current_phase"] == "ready"
    assert ui_state["voice_core_state"] == "idle"
    assert ui_state["capture_started"] is False
    assert ui_state["core_routed"] is False


def test_wake_ghost_api_status_and_cancel_are_backend_owned(temp_config) -> None:
    temp_config.voice.enabled = True
    temp_config.voice.mode = "manual"
    temp_config.voice.wake.enabled = True
    temp_config.voice.wake.provider = "mock"
    temp_config.voice.wake.allow_dev_wake = True
    temp_config.voice.wake.cooldown_ms = 0

    with TestClient(create_app(temp_config)) as client:
        simulated = client.post(
            "/voice/wake/simulate",
            json={"session_id": "voice-session", "confidence": 0.94},
        ).json()
        accepted = client.post(
            "/voice/wake/accept",
            json={
                "session_id": "voice-session",
                "wake_event_id": simulated["wake_event"]["wake_event_id"],
            },
        ).json()
        status = client.get("/voice/wake/ghost").json()
        cancelled = client.post(
            "/voice/wake/ghost/cancel",
            json={
                "wake_session_id": accepted["wake_session"]["wake_session_id"],
                "reason": "operator_dismissed",
            },
        ).json()

    assert status["action"] == "voice.getWakeGhost"
    assert status["wake_ghost"]["active"] is True
    assert status["wake_ghost"]["openai_used"] is False
    assert cancelled["action"] == "voice.cancelWakeGhost"
    assert cancelled["wake_ghost"]["status"] == "cancelled"
    assert cancelled["voice"]["wake_ghost"]["active"] is False
