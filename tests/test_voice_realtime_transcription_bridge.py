from __future__ import annotations

import asyncio

from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceRealtimeConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice import VoiceInterruptionRequest
from stormhelm.core.voice.providers import MockRealtimeProvider
from stormhelm.core.voice.providers import UnavailableRealtimeProvider
from stormhelm.core.voice.service import build_voice_subsystem
from stormhelm.ui.voice_surface import build_voice_ui_state

from tests.test_voice_manual_turn import RecordingCoreBridge
from tests.test_voice_manual_turn import _openai_config


def _voice_config(*, enabled: bool = True, allow_dev: bool = True) -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="manual",
        manual_input_enabled=True,
        debug_mock_provider=True,
        realtime=VoiceRealtimeConfig(
            enabled=enabled,
            provider="mock",
            mode="transcription_bridge",
            model="gpt-realtime",
            turn_detection="server_vad",
            semantic_vad_enabled=False,
            max_session_ms=60_000,
            max_turn_ms=30_000,
            allow_dev_realtime=allow_dev,
            direct_tools_allowed=False,
            core_bridge_required=True,
            audio_output_enabled=False,
        ),
    )


def _service(*, enabled: bool = True, allow_dev: bool = True):
    events = EventBuffer(capacity=128)
    service = build_voice_subsystem(
        _voice_config(enabled=enabled, allow_dev=allow_dev),
        _openai_config(),
        events=events,
    )
    bridge = RecordingCoreBridge(
        result_state="completed",
        route_family="clock",
        subsystem="tools",
        spoken_summary="Core handled the realtime transcript.",
        visual_summary="Core handled the realtime transcript.",
    )
    service.attach_core_bridge(bridge)
    return service, events, bridge


def test_realtime_config_defaults_are_disabled_transcription_bridge_only() -> None:
    config = VoiceConfig()

    assert config.realtime.enabled is False
    assert config.realtime.provider == "openai"
    assert config.realtime.mode == "transcription_bridge"
    assert config.realtime.model == "gpt-realtime"
    assert config.realtime.turn_detection == "server_vad"
    assert config.realtime.semantic_vad_enabled is False
    assert config.realtime.direct_tools_allowed is False
    assert config.realtime.core_bridge_required is True
    assert config.realtime.audio_output_enabled is False


def test_realtime_readiness_distinguishes_disabled_and_unavailable() -> None:
    service, _events, _bridge = _service(enabled=False)

    readiness = service.realtime_readiness_report()

    assert readiness.realtime_enabled is False
    assert readiness.realtime_available is False
    assert readiness.realtime_mode == "transcription_bridge"
    assert readiness.direct_tools_allowed is False
    assert readiness.core_bridge_required is True
    assert readiness.speech_to_speech_enabled is False
    assert readiness.audio_output_from_realtime is False
    assert readiness.wake_detection_local_only is True
    assert "realtime_disabled" in readiness.blocking_reasons
    assert service.status_snapshot()["realtime"]["enabled"] is False


def test_mock_realtime_provider_session_lifecycle_is_bounded_and_toolless() -> None:
    service, events, _bridge = _service()

    assert isinstance(service.realtime_provider, MockRealtimeProvider)
    session = asyncio.run(
        service.start_realtime_session(
            session_id="voice-session",
            source="test",
            listen_window_id="listen-1",
        )
    )

    assert session.status == "active"
    assert session.mode == "transcription_bridge"
    assert session.source == "test"
    assert session.listen_window_id == "listen-1"
    assert session.direct_tools_allowed is False
    assert session.core_bridge_required is True
    assert session.speech_to_speech_enabled is False
    assert session.audio_output_enabled is False
    assert service.get_active_realtime_session() == session

    closed = asyncio.run(service.close_realtime_session(session.realtime_session_id))
    assert closed.status == "closed"
    assert service.get_active_realtime_session() is None

    event_types = [record["event_type"] for record in events.recent(limit=128)]
    assert "voice.realtime_session_created" in event_types
    assert "voice.realtime_session_started" in event_types
    assert "voice.realtime_session_closed" in event_types
    assert "voice.realtime_tool_execution" not in event_types


def test_unavailable_realtime_provider_reports_typed_reason_without_fallback() -> None:
    service, _events, _bridge = _service(enabled=True, allow_dev=False)

    assert isinstance(service.realtime_provider, UnavailableRealtimeProvider)
    readiness = service.realtime_readiness_report()

    assert readiness.realtime_available is False
    assert readiness.realtime_provider_kind == "unavailable"
    assert "dev_realtime_not_allowed" in readiness.blocking_reasons


def test_partial_realtime_transcript_updates_status_only_and_does_not_route_core() -> None:
    service, events, bridge = _service()
    session = asyncio.run(service.start_realtime_session(session_id="voice-session"))

    event = asyncio.run(
        service.simulate_realtime_partial_transcript(
            "open firefox",
            realtime_session_id=session.realtime_session_id,
            listen_window_id="listen-1",
        )
    )

    assert event.is_partial is True
    assert event.is_final is False
    assert event.core_routed is False
    assert event.raw_audio_present is False
    assert event.command_authority is False
    assert bridge.calls == []
    snapshot = service.status_snapshot()["realtime"]
    assert snapshot["partial_transcript_preview"] == "open firefox"
    assert snapshot["active_realtime_session_id"] == session.realtime_session_id

    event_types = [record["event_type"] for record in events.recent(limit=128)]
    assert "voice.realtime_partial_transcript" in event_types
    assert "voice.core_request_started" not in event_types


def test_final_realtime_transcript_creates_voice_turn_and_routes_through_core() -> None:
    service, events, bridge = _service()
    session = asyncio.run(
        service.start_realtime_session(
            session_id="voice-session",
            source="post_wake",
            listen_window_id="listen-1",
        )
    )

    result = asyncio.run(
        service.simulate_realtime_final_transcript(
            "what time is it?",
            realtime_session_id=session.realtime_session_id,
            listen_window_id="listen-1",
        )
    )

    assert result.final_status == "completed"
    assert result.voice_turn_id is not None
    assert result.core_result_state == "completed"
    assert result.route_family == "clock"
    assert bridge.calls and bridge.calls[-1]["message"] == "what time is it?"
    assert service.last_manual_turn_result is not None
    assert service.last_manual_turn_result.turn is not None
    assert service.last_manual_turn_result.turn.source == "mock_realtime"
    assert service.last_manual_turn_result.realtime_invoked is True
    assert service.last_manual_turn_result.stt_invoked is False

    event_types = [record["event_type"] for record in events.recent(limit=128)]
    assert "voice.realtime_final_transcript" in event_types
    assert "voice.realtime_turn_submitted_to_core" in event_types
    assert "voice.realtime_turn_completed" in event_types
    assert "voice.realtime_tool_execution" not in event_types


def test_final_realtime_yes_without_pending_confirmation_does_not_execute() -> None:
    service, _events, bridge = _service()
    session = asyncio.run(service.start_realtime_session(session_id="voice-session"))

    result = asyncio.run(
        service.simulate_realtime_final_transcript(
            "yes",
            realtime_session_id=session.realtime_session_id,
        )
    )

    assert result.final_status == "no_pending_confirmation"
    assert result.core_result_state == "no_pending_confirmation"
    assert result.action_executed is False
    assert result.core_task_cancelled_by_realtime is False
    assert bridge.calls == []
    assert service.last_spoken_confirmation_result is not None
    assert service.last_spoken_confirmation_result.status == "no_pending_confirmation"


def test_realtime_cancel_interruption_closes_session_without_task_cancellation() -> None:
    service, _events, bridge = _service()
    session = asyncio.run(service.start_realtime_session(session_id="voice-session"))

    result = asyncio.run(
        service.handle_voice_interruption(
            VoiceInterruptionRequest(
                transcript="cancel this request",
                source="openai_realtime",
                session_id="voice-session",
                realtime_session_id=session.realtime_session_id,
            )
        )
    )

    assert result.status == "completed"
    assert result.realtime_session_cancelled is True
    assert result.affected_realtime_session_id == session.realtime_session_id
    assert result.core_task_cancelled is False
    assert result.core_result_mutated is False
    assert service.get_active_realtime_session() is None
    assert bridge.calls == []


def test_realtime_status_and_ui_payload_say_transcription_bridge_only() -> None:
    service, _events, _bridge = _service()
    session = asyncio.run(service.start_realtime_session(session_id="voice-session"))
    asyncio.run(
        service.simulate_realtime_partial_transcript(
            "show the plan",
            realtime_session_id=session.realtime_session_id,
        )
    )

    snapshot = service.status_snapshot()
    realtime = snapshot["realtime"]
    assert realtime["enabled"] is True
    assert realtime["mode"] == "transcription_bridge"
    assert realtime["direct_tools_allowed"] is False
    assert realtime["core_bridge_required"] is True
    assert realtime["speech_to_speech_enabled"] is False
    assert realtime["audio_output_from_realtime"] is False
    assert realtime["raw_audio_present"] is False
    assert realtime["no_cloud_wake_detection"] is True
    assert "test-key" not in str(realtime)

    ui_state = build_voice_ui_state({"voice": snapshot})
    assert ui_state["realtime_enabled"] is True
    assert ui_state["realtime_mode"] == "transcription_bridge"
    assert ui_state["active_realtime_session_id"] == session.realtime_session_id
    assert ui_state["truth_flags"]["realtime_transcription_bridge_only"] is True
    assert ui_state["truth_flags"]["speech_to_speech_enabled"] is False
    assert ui_state["truth_flags"]["direct_realtime_tools_allowed"] is False
    assert "Realtime" in [section["title"] for section in ui_state["deck"]["sections"]]
    forbidden = str(ui_state).lower()
    assert "always listening" not in forbidden
    assert "speaking through realtime" not in forbidden
