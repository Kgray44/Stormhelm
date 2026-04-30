from __future__ import annotations

import asyncio

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.models import VoiceInterruptionIntent
from stormhelm.core.voice.models import VoiceInterruptionRequest
from stormhelm.core.voice.models import VoiceInterruptionResult
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem


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


def _voice_config() -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="manual",
        spoken_responses_enabled=True,
        debug_mock_provider=True,
        openai=VoiceOpenAIConfig(max_tts_chars=240),
        playback=VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            device="test-device",
            volume=0.5,
            allow_dev_playback=True,
            max_audio_bytes=128,
            max_duration_ms=5000,
        ),
        capture=VoiceCaptureConfig(
            enabled=True,
            provider="mock",
            allow_dev_capture=True,
            max_audio_bytes=128,
            max_duration_ms=5000,
        ),
    )


def _service(*, events: EventBuffer | None = None, complete_immediately: bool = True):
    service = build_voice_subsystem(_voice_config(), _openai_config(), events=events)
    service.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")
    service.playback_provider = MockPlaybackProvider(
        complete_immediately=complete_immediately
    )
    return service


def _audio_output() -> VoiceAudioOutput:
    return VoiceAudioOutput.from_bytes(b"voice bytes", format="mp3")


def test_interruption_models_preserve_output_only_truth() -> None:
    request = VoiceInterruptionRequest(
        intent=VoiceInterruptionIntent.STOP_SPEAKING,
        source="ghost",
        session_id="voice-session",
        playback_id="playback-1",
        reason="user_requested",
    )
    result = VoiceInterruptionResult(
        interruption_id=request.interruption_id,
        intent=request.intent,
        status="completed",
        affected_playback_id="playback-1",
        spoken_output_suppressed=True,
    )

    assert request.to_dict()["intent"] == "stop_speaking"
    assert request.allowed_to_interrupt is False
    assert result.to_dict()["core_task_cancelled"] is False
    assert result.to_dict()["core_result_mutated"] is False


def test_stop_speaking_stops_active_playback_without_cancelling_core() -> None:
    events = EventBuffer(capacity=64)
    service = _service(events=events, complete_immediately=False)
    started = asyncio.run(
        service.play_speech_output(_audio_output(), session_id="voice-session")
    )

    interrupted = asyncio.run(
        service.stop_speaking(
            session_id="voice-session",
            playback_id=started.playback_id,
            reason="user_requested",
        )
    )
    snapshot = service.status_snapshot()
    event_types = [event["event_type"] for event in events.recent(limit=64)]

    assert started.status == "started"
    assert interrupted.status == "completed"
    assert interrupted.intent == VoiceInterruptionIntent.STOP_SPEAKING
    assert interrupted.playback_result is not None
    assert interrupted.playback_result.status == "stopped"
    assert interrupted.affected_playback_id == started.playback_id
    assert interrupted.core_task_cancelled is False
    assert interrupted.core_result_mutated is False
    assert snapshot["interruption"]["last_interruption_status"] == "completed"
    assert snapshot["playback"]["active_playback_interruptible"] is False
    assert snapshot["runtime_truth"]["core_task_cancelled_by_voice"] is False
    assert "voice.interruption_requested" in event_types
    assert "voice.interruption_completed" in event_types
    assert "voice.playback_stopped" in event_types
    assert not any("core_task_cancel" in event for event in event_types)


def test_stop_speaking_without_active_playback_is_truthful_noop() -> None:
    service = _service()

    result = asyncio.run(service.stop_speaking(reason="user_requested"))

    assert result.ok is False
    assert result.status == "no_active_playback"
    assert result.error_code == "no_active_playback"
    assert result.core_task_cancelled is False
    assert result.core_result_mutated is False
    assert service.status_snapshot()["interruption"]["last_interruption_status"] == (
        "no_active_playback"
    )


def test_suppress_current_response_blocks_tts_without_calling_provider() -> None:
    service = _service()

    suppression = asyncio.run(
        service.suppress_current_response(turn_id="turn-1", reason="user_requested")
    )
    synthesis = asyncio.run(
        service.synthesize_speech_text(
            "Bearing acquired.", session_id="voice-session", turn_id="turn-1"
        )
    )
    snapshot = service.status_snapshot()

    assert suppression.status == "completed"
    assert suppression.spoken_output_suppressed is True
    assert synthesis.ok is False
    assert synthesis.status == "blocked"
    assert synthesis.error_code == "current_response_suppressed"
    assert service.provider.tts_call_count == 0
    assert snapshot["tts"]["current_response_suppressed"] is True
    assert snapshot["pipeline_summary"]["output_suppressed"] is True


def test_suppression_after_tts_skips_playback_and_keeps_audio_metadata() -> None:
    service = _service()
    synthesis = asyncio.run(
        service.synthesize_speech_text(
            "Bearing acquired.", session_id="voice-session", turn_id="turn-1"
        )
    )

    suppression = asyncio.run(service.suppress_current_response(turn_id="turn-1"))
    playback = asyncio.run(service.play_speech_output(synthesis))
    summary = service.pipeline_stage_summary().to_dict()

    assert synthesis.ok is True
    assert suppression.status == "completed"
    assert playback.ok is False
    assert playback.status == "blocked"
    assert playback.error_code == "current_response_suppressed"
    assert service.playback_provider.playback_call_count == 0
    assert summary["output_suppressed"] is True
    assert summary["core_result_state"] is None


def test_muting_spoken_output_blocks_future_synthesis_until_unmuted() -> None:
    service = _service()

    muted = asyncio.run(
        service.set_spoken_output_muted(True, scope="session", reason="operator_mute")
    )
    blocked = asyncio.run(service.synthesize_speech_text("Bearing acquired."))
    unmuted = asyncio.run(service.set_spoken_output_muted(False, scope="session"))
    allowed = asyncio.run(service.synthesize_speech_text("Bearing acquired."))
    snapshot = service.status_snapshot()

    assert muted.status == "completed"
    assert muted.intent == VoiceInterruptionIntent.MUTE_SPOKEN_RESPONSES
    assert blocked.error_code == "spoken_output_muted"
    assert unmuted.intent == VoiceInterruptionIntent.UNMUTE_SPOKEN_RESPONSES
    assert allowed.ok is True
    assert snapshot["interruption"]["spoken_output_muted"] is False
    assert snapshot["capture"]["enabled"] is True


def test_unmuting_spoken_output_clears_stale_current_response_suppression() -> None:
    service = _service()

    suppressed = asyncio.run(
        service.suppress_current_response(session_id="voice-session")
    )
    blocked = asyncio.run(service.synthesize_speech_text("Bearing acquired."))
    unmuted = asyncio.run(
        service.set_spoken_output_muted(False, scope="session", reason="trace_reset")
    )
    allowed = asyncio.run(service.synthesize_speech_text("Bearing acquired."))
    snapshot = service.status_snapshot()

    assert suppressed.status == "completed"
    assert blocked.error_code == "current_response_suppressed"
    assert unmuted.intent == VoiceInterruptionIntent.UNMUTE_SPOKEN_RESPONSES
    assert allowed.ok is True
    assert snapshot["interruption"]["current_response_suppressed"] is False


def test_cancel_capture_interruption_does_not_cancel_core_task() -> None:
    service = _service()
    session = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))

    result = asyncio.run(
        service.interrupt_voice_output(
            VoiceInterruptionRequest(
                intent=VoiceInterruptionIntent.CANCEL_CAPTURE,
                source="ghost",
                session_id="voice-session",
                capture_id=session.capture_id,
                reason="user_cancelled",
            )
        )
    )

    assert result.status == "completed"
    assert result.capture_result is not None
    assert result.capture_result.status == "cancelled"
    assert result.affected_capture_id == session.capture_id
    assert result.core_task_cancelled is False
    assert result.core_result_mutated is False


def test_unknown_interruption_intent_is_unsupported() -> None:
    service = _service()

    result = asyncio.run(
        service.interrupt_voice_output(
            VoiceInterruptionRequest(intent="unknown", source="test")
        )
    )

    assert result.status == "unsupported"
    assert result.error_code == "unsupported_interruption_intent"
    assert result.core_task_cancelled is False
