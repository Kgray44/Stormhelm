from __future__ import annotations

import asyncio
from typing import Any

from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceRealtimeConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice import VoiceInterruptionRequest
from stormhelm.core.voice.service import build_voice_subsystem
from stormhelm.ui.voice_surface import build_voice_ui_state

from tests.test_voice_manual_turn import _openai_config


class RealtimeCoreBridge:
    def __init__(
        self,
        *,
        result_state: str = "completed",
        route_family: str = "software_control",
        subsystem: str = "apps",
        spoken_summary: str = "Core approved response.",
        visual_summary: str = "Core approved response.",
        speak_allowed: bool = True,
        trust_posture: str = "none",
        verification_posture: str = "not_verified",
        task_id: str | None = "task-1",
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result_state = result_state
        self.route_family = route_family
        self.subsystem = subsystem
        self.spoken_summary = spoken_summary
        self.visual_summary = visual_summary
        self.speak_allowed = speak_allowed
        self.trust_posture = trust_posture
        self.verification_posture = verification_posture
        self.task_id = task_id

    async def handle_message(
        self,
        message: str,
        session_id: str = "default",
        *,
        surface_mode: str = "ghost",
        active_module: str = "chartroom",
        workspace_context: dict[str, Any] | None = None,
        input_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "message": message,
                "session_id": session_id,
                "surface_mode": surface_mode,
                "active_module": active_module,
                "workspace_context": workspace_context,
                "input_context": input_context,
            }
        )
        return {
            "session_id": session_id,
            "assistant_message": {
                "content": self.visual_summary,
                "metadata": {
                    "spoken_summary": self.spoken_summary,
                    "micro_response": self.spoken_summary,
                    "full_response": self.visual_summary,
                    "voice_core_result": {
                        "result_state": self.result_state,
                        "route_family": self.route_family,
                        "subsystem": self.subsystem,
                        "trust_posture": self.trust_posture,
                        "verification_posture": self.verification_posture,
                        "task_id": self.task_id,
                        "speak_allowed": self.speak_allowed,
                        "continue_listening": False,
                    },
                    "route_state": {
                        "winner": {
                            "route_family": self.route_family,
                            "clarification_needed": self.result_state
                            == "clarification_required",
                        }
                    },
                },
            },
            "jobs": [],
            "actions": [],
            "active_request_state": {},
            "active_task": {"task_id": self.task_id} if self.task_id else {},
        }


def _speech_config(*, enabled: bool = True, allow_dev: bool = True) -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="manual",
        manual_input_enabled=True,
        spoken_responses_enabled=True,
        debug_mock_provider=True,
        realtime=VoiceRealtimeConfig(
            enabled=enabled,
            provider="mock",
            mode="speech_to_speech_core_bridge",
            model="gpt-realtime",
            voice="stormhelm_default",
            turn_detection="server_vad",
            semantic_vad_enabled=False,
            max_session_ms=60_000,
            max_turn_ms=30_000,
            allow_dev_realtime=allow_dev,
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=True,
            audio_output_from_realtime=True,
            require_core_for_commands=True,
            allow_smalltalk_without_core=False,
        ),
    )


def _service(
    *,
    bridge: RealtimeCoreBridge | None = None,
    enabled: bool = True,
    allow_dev: bool = True,
):
    events = EventBuffer(capacity=256)
    service = build_voice_subsystem(
        _speech_config(enabled=enabled, allow_dev=allow_dev),
        _openai_config(),
        events=events,
    )
    core_bridge = bridge or RealtimeCoreBridge()
    service.attach_core_bridge(core_bridge)
    return service, events, core_bridge


def test_realtime_speech_config_is_explicit_and_keeps_voice18_defaults() -> None:
    defaults = VoiceConfig()

    assert defaults.realtime.enabled is False
    assert defaults.realtime.mode == "transcription_bridge"
    assert defaults.realtime.speech_to_speech_enabled is False
    assert defaults.realtime.audio_output_from_realtime is False
    assert defaults.realtime.direct_tools_allowed is False
    assert defaults.realtime.core_bridge_required is True

    speech = _speech_config().realtime
    assert speech.mode == "speech_to_speech_core_bridge"
    assert speech.speech_to_speech_enabled is True
    assert speech.audio_output_from_realtime is True
    assert speech.require_core_for_commands is True
    assert speech.allow_smalltalk_without_core is False
    assert speech.direct_tools_allowed is False


def test_mock_realtime_speech_session_starts_with_core_bridge_tool_only() -> None:
    service, events, _bridge = _service()

    readiness = service.realtime_readiness_report()
    assert readiness.realtime_mode == "speech_to_speech_core_bridge"
    assert readiness.realtime_available is True
    assert readiness.speech_to_speech_enabled is True
    assert readiness.audio_output_from_realtime is True
    assert readiness.direct_tools_allowed is False

    session = asyncio.run(
        service.start_realtime_session(session_id="voice-session", source="test")
    )

    assert session.status == "active"
    assert session.mode == "speech_to_speech_core_bridge"
    assert session.voice == "stormhelm_default"
    assert session.speech_to_speech_enabled is True
    assert session.audio_output_from_realtime is True
    assert session.core_bridge_tool_enabled is True
    assert session.direct_action_tools_exposed is False
    assert session.direct_tools_allowed is False

    event_types = [record["event_type"] for record in events.recent(limit=256)]
    assert "voice.realtime_speech_session_started" in event_types
    assert "voice.realtime_direct_tool_enabled" not in event_types


def test_realtime_session_instructions_require_core_for_actions() -> None:
    service, _events, _bridge = _service()

    instructions = service.realtime_session_instructions()

    assert "Stormhelm's voice surface" in instructions
    assert "stormhelm_core_request" in instructions
    assert "Do not execute actions directly" in instructions
    assert "Do not approve actions directly" in instructions
    assert "Do not verify outcomes directly" in instructions
    assert "If unsure whether a request is an action, call Core" in instructions
    assert "pirate" in instructions.lower()


def test_realtime_core_bridge_request_uses_existing_core_boundary_and_preserves_result() -> None:
    bridge = RealtimeCoreBridge(
        result_state="completed",
        route_family="software_control",
        subsystem="apps",
        spoken_summary="Opened the settings panel.",
        verification_posture="verified",
    )
    service, events, _bridge = _service(bridge=bridge)
    session = asyncio.run(service.start_realtime_session(session_id="voice-session"))

    result = asyncio.run(
        service.stormhelm_core_request(
            transcript="open settings",
            realtime_session_id=session.realtime_session_id,
            realtime_turn_id="rt-turn-1",
            session_id="voice-session",
            metadata={
                "provider_injected_route_family": "file_delete",
                "provider_injected_action": "delete_file",
            },
        )
    )

    assert result.status == "completed"
    assert result.core_bridge_tool_name == "stormhelm_core_request"
    assert result.core_request_id is not None
    assert result.result_state == "completed"
    assert result.route_family == "software_control"
    assert result.subsystem == "apps"
    assert result.verification_posture == "verified"
    assert result.spoken_summary == "Opened the settings panel."
    assert result.direct_tools_allowed is False
    assert result.direct_action_tools_exposed is False
    assert bridge.calls and bridge.calls[-1]["message"] == "open settings"
    voice_meta = bridge.calls[-1]["input_context"]["voice"]
    assert voice_meta["source"] == "realtime_speech"
    assert voice_meta["core_bridge_tool_name"] == "stormhelm_core_request"
    assert voice_meta["provider_injected_route_family_ignored"] is True

    event_types = [record["event_type"] for record in events.recent(limit=256)]
    assert "voice.realtime_core_bridge_call_started" in event_types
    assert "voice.realtime_core_bridge_call_completed" in event_types


def test_realtime_response_gating_preserves_confirmation_and_blocks_no_speech() -> None:
    confirmation_bridge = RealtimeCoreBridge(
        result_state="requires_confirmation",
        spoken_summary="Confirmation required. Say confirm to proceed.",
        trust_posture="approval_required",
    )
    service, events, _bridge = _service(bridge=confirmation_bridge)
    session = asyncio.run(service.start_realtime_session(session_id="voice-session"))

    call = asyncio.run(
        service.stormhelm_core_request(
            transcript="install the update",
            realtime_session_id=session.realtime_session_id,
            realtime_turn_id="rt-turn-2",
            session_id="voice-session",
        )
    )
    gate = service.gate_realtime_spoken_response(call)

    assert gate.status == "allowed"
    assert gate.result_state == "requires_confirmation"
    assert gate.spoken_summary_source == "core"
    assert gate.spoken_text == "Confirmation required. Say confirm to proceed."
    assert gate.action_executed is False
    assert "completed" not in gate.spoken_text.lower()

    blocked_bridge = RealtimeCoreBridge(
        result_state="completed",
        spoken_summary="Hidden visual result.",
        speak_allowed=False,
    )
    blocked_service, _blocked_events, _blocked_bridge = _service(bridge=blocked_bridge)
    blocked_session = asyncio.run(
        blocked_service.start_realtime_session(session_id="voice-session")
    )
    blocked_call = asyncio.run(
        blocked_service.stormhelm_core_request(
            transcript="show the secret",
            realtime_session_id=blocked_session.realtime_session_id,
            session_id="voice-session",
        )
    )
    blocked_gate = blocked_service.gate_realtime_spoken_response(blocked_call)

    assert blocked_gate.status == "blocked"
    assert blocked_gate.speak_allowed is False
    assert blocked_gate.spoken_text == ""
    assert blocked_gate.reason == "core_speak_not_allowed"

    event_types = [record["event_type"] for record in events.recent(limit=256)]
    assert "voice.realtime_response_gated" in event_types
    assert "voice.realtime_spoken_response_allowed" in event_types


def test_realtime_direct_tool_attempt_is_blocked_and_not_executed() -> None:
    service, events, bridge = _service()
    session = asyncio.run(service.start_realtime_session(session_id="voice-session"))

    result = service.block_realtime_direct_tool_attempt(
        "install_software",
        realtime_session_id=session.realtime_session_id,
        realtime_turn_id="rt-turn-3",
        arguments={"package": "danger"},
    )

    assert result["status"] == "blocked"
    assert result["tool_name"] == "install_software"
    assert result["direct_tools_allowed"] is False
    assert result["action_executed"] is False
    assert result["core_task_cancelled"] is False
    assert bridge.calls == []

    event_types = [record["event_type"] for record in events.recent(limit=256)]
    assert "voice.realtime_direct_tool_blocked" in event_types
    assert "voice.tool_execution_started" not in event_types


def test_realtime_spoken_confirmation_still_uses_voice16_binding() -> None:
    service, _events, bridge = _service()
    session = asyncio.run(service.start_realtime_session(session_id="voice-session"))

    result = asyncio.run(
        service.stormhelm_core_request(
            transcript="yes",
            realtime_session_id=session.realtime_session_id,
            realtime_turn_id="rt-turn-4",
            session_id="voice-session",
        )
    )

    assert result.status == "no_pending_confirmation"
    assert result.result_state == "no_pending_confirmation"
    assert result.action_executed is False
    assert result.core_task_cancelled_by_realtime is False
    assert bridge.calls == []
    assert service.last_spoken_confirmation_result is not None
    assert service.last_spoken_confirmation_result.status == "no_pending_confirmation"


def test_realtime_cancel_task_routes_through_core_and_does_not_cancel_directly() -> None:
    service, _events, bridge = _service(
        bridge=RealtimeCoreBridge(
            result_state="pending_core_decision",
            spoken_summary="I routed that cancellation through Core.",
        )
    )
    session = asyncio.run(service.start_realtime_session(session_id="voice-session"))

    result = asyncio.run(
        service.stormhelm_core_request(
            transcript="cancel the task",
            realtime_session_id=session.realtime_session_id,
            realtime_turn_id="rt-turn-5",
            session_id="voice-session",
        )
    )

    assert result.status == "completed"
    assert result.result_state == "pending_core_decision"
    assert result.core_task_cancelled_by_realtime is False
    assert result.core_result_mutated_by_realtime is False
    assert bridge.calls and bridge.calls[-1]["message"] == "cancel the task"

    interruption = asyncio.run(
        service.handle_voice_interruption(
            VoiceInterruptionRequest(
                transcript="stop talking",
                source="openai_realtime",
                session_id="voice-session",
                realtime_session_id=session.realtime_session_id,
            )
        )
    )
    assert interruption.core_task_cancelled is False
    assert interruption.core_result_mutated is False


def test_realtime_speech_status_and_ui_payload_are_truthful() -> None:
    service, _events, _bridge = _service()
    session = asyncio.run(service.start_realtime_session(session_id="voice-session"))
    call = asyncio.run(
        service.stormhelm_core_request(
            transcript="show status",
            realtime_session_id=session.realtime_session_id,
            realtime_turn_id="rt-turn-6",
            session_id="voice-session",
        )
    )
    gate = service.gate_realtime_spoken_response(call)

    snapshot = service.status_snapshot()
    realtime = snapshot["realtime"]
    assert realtime["mode"] == "speech_to_speech_core_bridge"
    assert realtime["speech_to_speech_enabled"] is True
    assert realtime["audio_output_from_realtime"] is True
    assert realtime["core_bridge_tool_enabled"] is True
    assert realtime["direct_tools_allowed"] is False
    assert realtime["direct_action_tools_exposed"] is False
    assert realtime["last_core_bridge_call_id"] == call.core_bridge_call_id
    assert realtime["last_core_result_state"] == "completed"
    assert realtime["last_spoken_summary_source"] == gate.spoken_summary_source
    assert "test-key" not in str(realtime)

    ui_state = build_voice_ui_state({"voice": snapshot})
    assert ui_state["realtime_mode"] == "speech_to_speech_core_bridge"
    assert ui_state["truth_flags"]["speech_to_speech_enabled"] is True
    assert ui_state["truth_flags"]["direct_realtime_tools_allowed"] is False
    text = str(ui_state).lower()
    assert "always listening" not in text
    assert "cloud wake" not in text
    assert "direct tools active" not in text
