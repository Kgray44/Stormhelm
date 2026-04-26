from __future__ import annotations

import pytest

from stormhelm.config.models import VoiceConfig
from stormhelm.core.voice.availability import VoiceAvailability
from stormhelm.core.voice.state import VoiceState
from stormhelm.core.voice.state import VoiceStateController
from stormhelm.core.voice.state import VoiceTransitionError


def _availability(*, available: bool = True, reason: str | None = None) -> VoiceAvailability:
    return VoiceAvailability(
        enabled_requested=True,
        openai_enabled=True,
        provider_configured=available,
        provider_name="openai",
        available=available,
        unavailable_reason=reason,
        mode="manual",
        realtime_allowed=False,
        stt_allowed=available,
        tts_allowed=False,
        wake_allowed=False,
        mock_provider_active=True,
    )


def test_voice_state_snapshot_is_disabled_when_config_disabled() -> None:
    controller = VoiceStateController(config=VoiceConfig(enabled=False), availability=_availability())

    snapshot = controller.snapshot()

    assert snapshot.state == VoiceState.DISABLED
    assert snapshot.previous_state is None
    assert snapshot.listening_allowed is False
    assert snapshot.speaking_allowed is False
    assert snapshot.core_bridge_required is True


def test_voice_state_snapshot_is_unavailable_when_provider_requirements_fail() -> None:
    controller = VoiceStateController(
        config=VoiceConfig(enabled=True, mode="manual"),
        availability=_availability(available=False, reason="provider_missing"),
    )

    snapshot = controller.snapshot()

    assert snapshot.state == VoiceState.UNAVAILABLE
    assert snapshot.error_code == "provider_missing"
    assert snapshot.listening_allowed is False


def test_voice_state_snapshot_is_dormant_when_available_but_not_active() -> None:
    controller = VoiceStateController(
        config=VoiceConfig(enabled=True, mode="manual", spoken_responses_enabled=True),
        availability=_availability(available=True),
    )

    snapshot = controller.snapshot()

    assert snapshot.state == VoiceState.DORMANT
    assert snapshot.mode == "manual"
    assert snapshot.speaking_allowed is False
    assert snapshot.listening_allowed is True


def test_voice_state_machine_allows_explicit_legal_transitions() -> None:
    controller = VoiceStateController(config=VoiceConfig(enabled=True, mode="manual"), availability=_availability())

    wake = controller.transition_to(VoiceState.WAKE_DETECTED, event_id="evt-1", source="mock")
    listening = controller.transition_to(VoiceState.LISTENING, event_id="evt-2", turn_id="turn-1")
    transcribing = controller.transition_to(VoiceState.TRANSCRIBING, event_id="evt-3")
    routing = controller.transition_to(VoiceState.CORE_ROUTING, event_id="evt-4")

    assert wake.previous_state == VoiceState.DORMANT
    assert listening.previous_state == VoiceState.WAKE_DETECTED
    assert listening.turn_id == "turn-1"
    assert transcribing.previous_state == VoiceState.LISTENING
    assert routing.state == VoiceState.CORE_ROUTING
    assert routing.last_event_id == "evt-4"


def test_voice_state_machine_rejects_illegal_transition_truthfully() -> None:
    controller = VoiceStateController(config=VoiceConfig(enabled=True, mode="manual"), availability=_availability())

    with pytest.raises(VoiceTransitionError) as exc:
        controller.transition_to(VoiceState.SPEAKING, event_id="evt-bad")

    snapshot = controller.snapshot()
    assert "dormant -> speaking" in str(exc.value)
    assert snapshot.state == VoiceState.ERROR
    assert snapshot.previous_state == VoiceState.DORMANT
    assert snapshot.error_code == "illegal_transition"
