from __future__ import annotations

import asyncio

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.providers import MockPlaybackProvider
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


def _service(events: EventBuffer | None = None, *, complete_immediately: bool = True):
    service = build_voice_subsystem(
        VoiceConfig(
            enabled=True,
            mode="manual",
            spoken_responses_enabled=True,
            playback=VoicePlaybackConfig(
                enabled=True,
                provider="mock",
                device="test-device",
                volume=0.35,
                allow_dev_playback=True,
            ),
        ),
        _openai_config(),
        events=events,
    )
    service.playback_provider = MockPlaybackProvider(
        complete_immediately=complete_immediately,
        playback_latency_ms=7,
    )
    return service


def test_playback_status_snapshot_reports_completed_playback_without_raw_audio() -> None:
    service = _service()
    audio_output = VoiceAudioOutput.from_bytes(b"private playback bytes", format="mp3")

    playback = asyncio.run(service.play_speech_output(audio_output, session_id="voice-session", turn_id="voice-turn"))
    snapshot = service.status_snapshot()

    assert playback.ok is True
    assert snapshot["current_phase"] == "voice4"
    assert snapshot["playback"]["enabled"] is True
    assert snapshot["playback"]["provider"] == "mock"
    assert snapshot["playback"]["available"] is True
    assert snapshot["playback"]["device"] == "test-device"
    assert snapshot["playback"]["volume"] == 0.35
    assert snapshot["playback"]["last_playback_request_id"] == playback.playback_request_id
    assert snapshot["playback"]["last_playback_id"] == playback.playback_id
    assert snapshot["playback"]["last_playback_status"] == "completed"
    assert snapshot["playback"]["last_audio_output_id"] == audio_output.output_id
    assert snapshot["playback"]["last_playback_error"]["code"] is None
    assert snapshot["playback"]["active_playback_id"] is None
    assert snapshot["playback"]["played_locally"] is True
    assert snapshot["playback"]["user_heard_claimed"] is False
    assert snapshot["runtime_truth"]["no_microphone_capture"] is True
    assert snapshot["runtime_truth"]["no_vad"] is True
    assert snapshot["runtime_truth"]["no_realtime"] is True
    assert snapshot["runtime_truth"]["no_continuous_loop"] is True
    assert "private playback bytes" not in str(snapshot)


def test_playback_status_snapshot_reports_active_started_playback() -> None:
    service = _service(complete_immediately=False)
    audio_output = VoiceAudioOutput.from_bytes(b"voice bytes", format="mp3")

    playback = asyncio.run(service.play_speech_output(audio_output, session_id="voice-session"))
    snapshot = service.status_snapshot()

    assert playback.status == "started"
    assert snapshot["playback"]["active_playback_id"] == playback.playback_id
    assert snapshot["playback"]["active_playback_status"] == "started"
    assert snapshot["playback"]["playback_started_at"] == playback.started_at
    assert snapshot["playback"]["playback_completed_at"] is None


def test_playback_events_are_recorded_without_fake_microphone_or_realtime_events() -> None:
    events = EventBuffer(capacity=64)
    service = _service(events=events)
    audio_output = VoiceAudioOutput.from_bytes(b"private event audio", format="mp3")

    playback = asyncio.run(service.play_speech_output(audio_output, session_id="voice-session", turn_id="voice-turn"))
    recent = events.recent(limit=64)
    event_types = [event["event_type"] for event in recent]

    assert playback.ok is True
    assert "voice.playback_request_created" in event_types
    assert "voice.playback_started" in event_types
    assert "voice.playback_completed" in event_types
    assert "voice.playback_failed" not in event_types
    assert "voice.speech_started" not in event_types
    assert "voice.speech_stopped" not in event_types
    assert "voice.wake_detected" not in event_types
    assert "voice.transcription_started" not in event_types

    completed = next(event for event in recent if event["event_type"] == "voice.playback_completed")
    assert completed["payload"]["playback_request_id"] == playback.playback_request_id
    assert completed["payload"]["playback_id"] == playback.playback_id
    assert completed["payload"]["audio_output_id"] == audio_output.output_id
    assert completed["payload"]["device"] == "test-device"
    assert completed["payload"]["status"] == "completed"
    assert "private event audio" not in str(completed["payload"])


def test_playback_blocked_failed_and_stopped_events_are_truthful() -> None:
    events = EventBuffer(capacity=64)
    service = _service(events=events, complete_immediately=False)
    audio_output = VoiceAudioOutput.from_bytes(b"voice bytes", format="mp3")

    blocked = asyncio.run(service.play_speech_output(None, session_id="voice-session"))
    started = asyncio.run(service.play_speech_output(audio_output, session_id="voice-session"))
    stopped = asyncio.run(service.stop_playback(started.playback_id, reason="test_stop"))
    service.playback_provider = MockPlaybackProvider(fail_playback=True, error_code="device_failed")
    failed = asyncio.run(service.play_speech_output(audio_output, session_id="voice-session"))
    event_types = [event["event_type"] for event in events.recent(limit=64)]

    assert blocked.status == "blocked"
    assert stopped.status == "stopped"
    assert failed.status == "failed"
    assert "voice.playback_blocked" in event_types
    assert "voice.playback_stopped" in event_types
    assert "voice.playback_failed" in event_types
