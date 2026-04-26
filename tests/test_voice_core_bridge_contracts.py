from __future__ import annotations

from stormhelm.core.voice.bridge import VoiceCoreRequest
from stormhelm.core.voice.bridge import VoiceCoreResult


def test_voice_core_request_shape_requires_core_bridge() -> None:
    request = VoiceCoreRequest(
        transcript="open downloads",
        session_id="session-1",
        turn_id="turn-1",
        voice_mode="manual",
        interaction_mode="ghost",
        screen_context_permission="not_requested",
        metadata={"confidence": "unknown"},
    )

    assert request.source == "voice"
    assert request.core_bridge_required is True
    assert request.transcript == "open downloads"
    assert request.confirmation_intent is None
    assert request.interrupt_intent is None
    assert request.to_core_metadata()["source"] == "voice"
    assert request.to_core_metadata()["core_bridge_required"] is True


def test_voice_core_result_preserves_route_trust_and_verification_posture() -> None:
    result = VoiceCoreResult(
        result_state="pending_approval",
        spoken_summary="I need confirmation before changing installed software.",
        visual_summary="Install request is waiting for approval.",
        route_family="software",
        subsystem="software_control",
        trust_posture="approval_required",
        verification_posture="not_started",
        task_id="task-1",
        followup_binding={"approval_id": "approval-1"},
        speak_allowed=True,
        continue_listening=False,
        provenance={"source": "core"},
    )

    payload = result.to_dict()

    assert payload["result_state"] == "pending_approval"
    assert payload["trust_posture"] == "approval_required"
    assert payload["verification_posture"] == "not_started"
    assert payload["speak_allowed"] is True


def test_confirmation_intent_is_represented_but_not_executed_by_voice_layer() -> None:
    request = VoiceCoreRequest(
        transcript="yes",
        session_id="session-1",
        turn_id="turn-2",
        voice_mode="manual",
        interaction_mode="ghost",
        screen_context_permission="not_requested",
        confirmation_intent="confirm_current_prompt",
    )

    assert request.confirmation_intent == "confirm_current_prompt"
    assert not hasattr(request, "execute")
    assert not hasattr(request, "execute_tool")
    assert not hasattr(request, "run_tool")
