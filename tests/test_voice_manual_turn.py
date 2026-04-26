from __future__ import annotations

import asyncio
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.core.container import build_container
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.service import build_voice_subsystem


class RecordingCoreBridge:
    def __init__(
        self,
        *,
        result_state: str = "completed",
        route_family: str = "clock",
        subsystem: str = "tools",
        spoken_summary: str = "Bearing acquired.",
        visual_summary: str = "The time is 10:15.",
        raise_error: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result_state = result_state
        self.route_family = route_family
        self.subsystem = subsystem
        self.spoken_summary = spoken_summary
        self.visual_summary = visual_summary
        self.raise_error = raise_error

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
        if self.raise_error is not None:
            raise self.raise_error
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
                        "trust_posture": "none",
                        "verification_posture": "not_verified",
                        "speak_allowed": True,
                        "continue_listening": False,
                    },
                    "route_state": {
                        "winner": {
                            "route_family": self.route_family,
                            "query_shape": "current_status",
                            "clarification_needed": self.result_state == "clarification_required",
                        }
                    },
                },
            },
            "jobs": [],
            "actions": [],
            "active_request_state": {},
            "active_task": {},
        }


def _openai_config(*, enabled: bool = True, api_key: str | None = "test-key") -> OpenAIConfig:
    return OpenAIConfig(
        enabled=enabled,
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        model="gpt-5.4-nano",
        planner_model="gpt-5.4-nano",
        reasoning_model="gpt-5.4",
        timeout_seconds=60,
        max_tool_rounds=4,
        max_output_tokens=1200,
        planner_max_output_tokens=900,
        reasoning_max_output_tokens=1400,
        instructions="",
    )


def _voice_config(**overrides: Any) -> VoiceConfig:
    values = {
        "enabled": True,
        "mode": "manual",
        "manual_input_enabled": True,
        "spoken_responses_enabled": True,
        "debug_mock_provider": True,
    }
    values.update(overrides)
    return VoiceConfig(**values)


def test_submit_manual_voice_turn_creates_traceable_turn_and_calls_core_boundary() -> None:
    events = EventBuffer(capacity=32)
    service = build_voice_subsystem(_voice_config(), _openai_config(), events=events)
    bridge = RecordingCoreBridge(route_family="clock", subsystem="tools")
    service.attach_core_bridge(bridge)

    result = asyncio.run(
        service.submit_manual_voice_turn(
            "  what time is it?  ",
            mode="ghost",
            session_id="voice-session",
            metadata={"active_module": "systems", "workspace_context": {"module": "watch"}},
        )
    )

    assert result.ok is True
    assert result.turn is not None
    assert result.turn.source == "manual_voice"
    assert result.turn.transcript == "what time is it?"
    assert result.turn.normalized_transcript == "what time is it?"
    assert result.turn.core_bridge_required is True
    assert result.core_request is not None
    assert result.core_request.source == "voice"
    assert result.core_request.voice_mode == "manual"
    assert result.core_result is not None
    assert result.core_result.result_state == "completed"
    assert result.core_result.route_family == "clock"
    assert result.core_result.subsystem == "tools"
    assert result.spoken_response is not None
    assert result.spoken_response.should_speak is True
    assert result.spoken_response.spoken_text == "Bearing acquired."
    assert result.audio_playback_started is False
    assert result.no_real_audio is True
    assert [state["state"] for state in result.state_transitions] == [
        "dormant",
        "manual_input_received",
        "core_routing",
        "thinking",
        "speaking_ready",
        "dormant",
    ]

    assert bridge.calls == [
        {
            "message": "what time is it?",
            "session_id": "voice-session",
            "surface_mode": "ghost",
            "active_module": "systems",
            "workspace_context": {"module": "watch"},
            "input_context": {
                "source": "manual_voice",
                "voice": result.core_request.to_core_metadata(),
                "manual_transcript": True,
                "no_real_audio": True,
            },
        }
    ]


def test_manual_voice_turn_rejects_empty_transcripts_without_core_call() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    bridge = RecordingCoreBridge()
    service.attach_core_bridge(bridge)

    empty = asyncio.run(service.submit_manual_voice_turn("", session_id="voice-session"))
    whitespace = asyncio.run(service.submit_manual_voice_turn("   \n\t  ", session_id="voice-session"))

    assert empty.ok is False
    assert empty.error_code == "empty_transcript"
    assert whitespace.ok is False
    assert whitespace.error_code == "empty_transcript"
    assert bridge.calls == []


def test_manual_voice_turn_blocks_when_voice_disabled() -> None:
    service = build_voice_subsystem(VoiceConfig(enabled=False), _openai_config())
    service.attach_core_bridge(RecordingCoreBridge())

    result = asyncio.run(service.submit_manual_voice_turn("what time is it?", session_id="voice-session"))

    assert result.ok is False
    assert result.error_code == "voice_disabled"
    assert result.turn is None


def test_manual_voice_turn_blocks_unavailable_provider_without_mock_override() -> None:
    service = build_voice_subsystem(
        _voice_config(debug_mock_provider=False),
        _openai_config(enabled=False, api_key=None),
    )
    service.attach_core_bridge(RecordingCoreBridge())

    result = asyncio.run(service.submit_manual_voice_turn("what time is it?", session_id="voice-session"))

    assert result.ok is False
    assert result.error_code == "openai_disabled"
    assert result.turn is None


def test_manual_voice_turn_allows_mock_dev_override_without_openai_calls() -> None:
    service = build_voice_subsystem(
        _voice_config(debug_mock_provider=True),
        _openai_config(enabled=False, api_key=None),
    )
    bridge = RecordingCoreBridge()
    service.attach_core_bridge(bridge)

    result = asyncio.run(service.submit_manual_voice_turn("what time is it?", session_id="voice-session"))

    assert result.ok is True
    assert result.turn is not None
    assert result.turn.metadata["manual_dev_override"] is True
    assert result.provider_network_call_count == 0
    assert bridge.calls[0]["message"] == "what time is it?"


def test_manual_voice_turn_requires_core_bridge() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())

    result = asyncio.run(service.submit_manual_voice_turn("what time is it?", session_id="voice-session"))

    assert result.ok is False
    assert result.error_code == "core_bridge_missing"
    assert result.core_result is not None
    assert result.core_result.result_state == "failed"


def test_manual_voice_turn_preserves_bridge_failures_truthfully() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.attach_core_bridge(RecordingCoreBridge(raise_error=RuntimeError("core offline")))

    result = asyncio.run(service.submit_manual_voice_turn("what time is it?", session_id="voice-session"))

    assert result.ok is False
    assert result.error_code == "core_bridge_failed"
    assert result.core_result is not None
    assert result.core_result.result_state == "failed"
    assert "core offline" in str(result.core_result.error_code or result.error_message)
    assert result.voice_state_after is not None
    assert result.voice_state_after["state"] == "error"


def test_manual_voice_turn_moves_to_awaiting_confirmation_when_core_requires_it() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.attach_core_bridge(
        RecordingCoreBridge(
            result_state="requires_confirmation",
            route_family="software_control",
            subsystem="software_control",
            spoken_summary="Confirmation is required before Stormhelm can act.",
        )
    )

    result = asyncio.run(service.submit_manual_voice_turn("install minecraft", session_id="voice-session"))

    assert result.ok is True
    assert result.core_result is not None
    assert result.core_result.result_state == "requires_confirmation"
    assert result.voice_state_after is not None
    assert result.voice_state_after["state"] == "awaiting_confirmation"
    assert "confirmation" in result.spoken_response.spoken_text.lower()


def test_manual_voice_turn_preserves_clarification_without_rewriting_success() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.attach_core_bridge(
        RecordingCoreBridge(
            result_state="clarification_required",
            route_family="files",
            subsystem="planner",
            spoken_summary="I need one more bearing before acting.",
        )
    )

    result = asyncio.run(service.submit_manual_voice_turn("open that", session_id="voice-session"))

    assert result.ok is True
    assert result.core_result.result_state == "clarification_required"
    assert "done" not in result.spoken_response.spoken_text.lower()
    assert "all set" not in result.spoken_response.spoken_text.lower()
    assert "one more bearing" in result.spoken_response.spoken_text.lower()


def test_manual_voice_turn_routes_through_real_assistant_boundary(temp_config) -> None:
    temp_config.voice.enabled = True
    temp_config.voice.mode = "manual"
    temp_config.voice.spoken_responses_enabled = True
    temp_config.openai.enabled = True
    temp_config.openai.api_key = "test-key"
    container = build_container(temp_config)

    result = asyncio.run(container.voice.submit_manual_voice_turn("2+2", session_id="voice-session"))

    assert result.ok is True
    assert result.core_request is not None
    assert result.core_request.transcript == "2+2"
    assert result.core_result is not None
    assert result.core_result.route_family == "calculations"
    assert result.core_result.subsystem == "calculations"
    assert result.core_result.result_state == "completed"
    assert result.provider_network_call_count == 0
