from __future__ import annotations

import asyncio

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.config.models import VoicePostWakeConfig
from stormhelm.config.models import VoiceVADConfig
from stormhelm.config.models import VoiceWakeConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem
from stormhelm.ui.voice_surface import build_voice_ui_state

from tests.test_voice_manual_turn import RecordingCoreBridge


def _openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        enabled=True,
        api_key="test-key",
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


def _voice_config(*, vad_enabled: bool = False) -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="manual",
        spoken_responses_enabled=True,
        debug_mock_provider=True,
        capture=VoiceCaptureConfig(
            enabled=True,
            provider="mock",
            allow_dev_capture=True,
        ),
        playback=VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            allow_dev_playback=True,
            max_audio_bytes=128,
        ),
        wake=VoiceWakeConfig(
            enabled=True,
            provider="mock",
            wake_phrase="Stormhelm",
            confidence_threshold=0.75,
            cooldown_ms=0,
            max_wake_session_ms=15000,
            allow_dev_wake=True,
        ),
        post_wake=VoicePostWakeConfig(
            enabled=True,
            listen_window_ms=8000,
            max_utterance_ms=30000,
            auto_start_capture=True,
            auto_submit_on_capture_complete=True,
            allow_dev_post_wake=True,
        ),
        vad=VoiceVADConfig(
            enabled=vad_enabled,
            provider="mock",
            allow_dev_vad=True,
            auto_finalize_capture=True,
        ),
    )


def _service(
    *,
    transcript: str = "what time is it?",
    core_result_state: str = "completed",
    spoken_summary: str = "The time is 10:15.",
    vad_enabled: bool = False,
) -> tuple[object, EventBuffer, RecordingCoreBridge]:
    events = EventBuffer(capacity=128)
    service = build_voice_subsystem(
        _voice_config(vad_enabled=vad_enabled),
        _openai_config(),
        events=events,
    )
    service.provider = MockVoiceProvider(
        stt_transcript=transcript,
        tts_audio_bytes=b"voice bytes",
    )
    service.playback_provider = MockPlaybackProvider(complete_immediately=True)
    bridge = RecordingCoreBridge(
        result_state=core_result_state,
        route_family="clock",
        subsystem="tools",
        spoken_summary=spoken_summary,
        visual_summary=spoken_summary,
    )
    service.attach_core_bridge(bridge)
    return service, events, bridge


def _accepted_wake_session(service: object) -> object:
    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    wake = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.93)
    )
    return asyncio.run(service.accept_wake_event(wake.wake_event_id))


def test_wake_supervised_loop_happy_path_returns_to_idle_with_stage_truth() -> None:
    service, events, bridge = _service()
    wake_session = _accepted_wake_session(service)

    result = asyncio.run(
        service.run_wake_supervised_voice_loop(
            wake_session.wake_session_id,
            synthesize_response=True,
            play_response=True,
        )
    )

    assert result.ok is True
    assert result.final_status == "completed"
    assert result.wake_status == "active"
    assert result.ghost_status == "shown"
    assert result.listen_status == "submitted"
    assert result.capture_status == "completed"
    assert result.transcription_status == "completed"
    assert result.core_result_state == "completed"
    assert result.spoken_response_status == "prepared"
    assert result.synthesis_status == "succeeded"
    assert result.playback_status == "completed"
    assert result.last_successful_stage == "playback"
    assert result.failed_stage is None
    assert result.wake_event_id == wake_session.wake_event_id
    assert result.wake_session_id == wake_session.wake_session_id
    assert result.wake_ghost_request_id is not None
    assert result.listen_window_id.startswith("voice-listen-window-")
    assert result.capture_id is not None
    assert result.audio_input_id is not None
    assert result.transcription_id is not None
    assert result.voice_turn_id is not None
    assert result.speech_request_id is not None
    assert result.synthesis_id is not None
    assert result.playback_id is not None
    assert result.transcript_preview == "what time is it?"
    assert result.spoken_preview == "The time is 10:15."
    assert result.truth_flags["wake_local"] is True
    assert result.truth_flags["openai_wake_detection"] is False
    assert result.truth_flags["cloud_wake_detection"] is False
    assert result.truth_flags["continuous_listening"] is False
    assert result.truth_flags["realtime_used"] is False
    assert result.truth_flags["command_authority"] == "stormhelm_core"
    assert result.truth_flags["user_heard_claimed"] is False
    assert result.truth_flags["core_task_cancelled_by_voice"] is False
    assert bridge.calls and bridge.calls[0]["message"] == "what time is it?"
    assert service.get_active_wake_session() is None
    assert service.get_active_wake_ghost_request() is None

    snapshot = service.status_snapshot()
    loop_status = snapshot["wake_supervised_loop"]
    assert loop_status["enabled"] is True
    assert loop_status["last_loop_result"]["loop_id"] == result.loop_id
    assert loop_status["last_loop_result"]["final_status"] == "completed"
    assert (
        snapshot["runtime_truth"]["wake_supervised_loop_handles_one_bounded_request"]
        is True
    )
    assert snapshot["runtime_truth"]["continuous_listening"] is False
    assert snapshot["post_wake_listen"]["last_listen_window_status"] == "submitted"
    assert snapshot["runtime_truth"]["post_wake_listen_window_backfilled"] is True
    assert snapshot["planned_not_implemented"]["post_wake_capture"] == (
        "bounded_post_wake_listen_window_backfilled"
    )

    ui_state = build_voice_ui_state({"voice": snapshot})
    assert ui_state["wake_supervised_loop_enabled"] is True
    assert ui_state["last_wake_loop_final_status"] == "completed"
    assert ui_state["truth_flags"]["continuous_listening"] is False
    assert ui_state["truth_flags"]["cloud_wake_detection"] is False
    assert ui_state["truth_flags"]["realtime_used"] is False
    assert ui_state["truth_flags"]["command_authority"] == "stormhelm_core"
    assert "Wake Loop" in [section["title"] for section in ui_state["deck"]["sections"]]

    event_payloads = [record["payload"] for record in events.recent()]
    loop_payloads = [
        payload
        for payload in event_payloads
        if payload["event_type"].startswith("voice.wake_supervised_loop")
    ]
    assert [payload["event_type"] for payload in loop_payloads] == [
        "voice.wake_supervised_loop_started",
        "voice.wake_supervised_loop_completed",
    ]
    assert {payload["correlation_id"] for payload in loop_payloads} == {result.loop_id}
    assert "raw_audio" not in str(result.to_dict()).lower()
    assert "test-key" not in str(result.to_dict())


def test_rejected_wake_supervised_loop_does_not_listen_or_route_core() -> None:
    service, events, bridge = _service()
    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    low = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.2)
    )
    rejected = asyncio.run(service.accept_wake_event(low.wake_event_id))

    result = asyncio.run(
        service.run_wake_supervised_voice_loop(rejected.wake_session_id)
    )

    assert result.ok is False
    assert result.final_status == "wake_rejected"
    assert result.stopped_stage == "wake"
    assert result.blocked_stage == "wake"
    assert result.listen_status == "skipped"
    assert result.capture_status == "skipped"
    assert result.transcription_status == "skipped"
    assert result.core_result_state is None
    assert result.synthesis_status == "skipped"
    assert result.playback_status == "skipped"
    assert bridge.calls == []
    emitted = [record["event_type"] for record in events.recent()]
    assert "voice.listening_started" not in emitted
    assert "voice.capture_started" not in emitted
    assert "voice.transcription_started" not in emitted
    assert "voice.core_request_started" not in emitted


def test_wake_supervised_loop_can_use_vad_to_finalize_capture_without_vad_routing_core() -> (
    None
):
    service, events, bridge = _service(vad_enabled=True)
    wake_session = _accepted_wake_session(service)

    result = asyncio.run(
        service.run_wake_supervised_voice_loop(
            wake_session.wake_session_id,
            finalize_with_vad=True,
        )
    )

    assert result.ok is True
    assert result.final_status == "completed"
    assert result.vad_status == "speech_stopped"
    assert result.capture_status == "completed"
    assert result.transcription_status == "completed"
    assert result.core_result_state == "completed"
    assert bridge.calls and bridge.calls[0]["message"] == "what time is it?"

    event_types = [record["event_type"] for record in events.recent()]
    assert "voice.speech_activity_started" in event_types
    assert "voice.speech_activity_stopped" in event_types
    assert "voice.silence_timeout" in event_types
    assert event_types.index("voice.speech_activity_stopped") < event_types.index(
        "voice.transcription_started"
    )
    assert result.truth_flags["vad_command_authority"] is False
    assert result.truth_flags["vad_semantic_completion_claimed"] is False


def test_muted_wake_supervised_loop_preserves_core_result_and_skips_speech_output() -> (
    None
):
    service, _events, bridge = _service(spoken_summary="Response prepared.")
    wake_session = _accepted_wake_session(service)
    asyncio.run(
        service.set_spoken_output_muted(
            True,
            session_id="voice-session",
            reason="operator_requested",
        )
    )

    result = asyncio.run(
        service.run_wake_supervised_voice_loop(
            wake_session.wake_session_id,
            synthesize_response=True,
            play_response=True,
        )
    )

    assert result.ok is True
    assert result.final_status == "suppressed_or_muted"
    assert result.core_result_state == "completed"
    assert result.spoken_response_status == "prepared"
    assert result.synthesis_status == "blocked"
    assert result.playback_status == "skipped"
    assert result.stopped_stage == "tts"
    assert result.current_blocker == "spoken_output_muted"
    assert result.truth_flags["core_task_cancelled_by_voice"] is False
    assert result.truth_flags["core_result_mutated_by_voice"] is False
    assert service.provider.tts_call_count == 0
    assert service.playback_provider.playback_call_count == 0
    assert bridge.calls and bridge.calls[0]["message"] == "what time is it?"
