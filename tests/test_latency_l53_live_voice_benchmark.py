from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.config.models import VoicePostWakeConfig
from stormhelm.config.models import VoiceWakeConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.latency import build_latency_trace
from stormhelm.core.orchestrator.command_eval.report import _kraken_latency_report
from stormhelm.core.voice.models import VoiceLivePlaybackRequest
from stormhelm.core.voice.providers import MockCaptureProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.providers import NullStreamingPlaybackProvider
from stormhelm.core.voice.service import build_voice_subsystem

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


def _voice_config(*, playback_provider: str = "null_stream") -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="manual",
        manual_input_enabled=True,
        spoken_responses_enabled=True,
        debug_mock_provider=True,
        openai=VoiceOpenAIConfig(
            stream_tts_outputs=True,
            tts_live_format="pcm",
            tts_artifact_format="mp3",
            max_audio_bytes=128,
            max_audio_seconds=4,
        ),
        playback=VoicePlaybackConfig(
            enabled=True,
            provider=playback_provider,
            device="null-stream",
            allow_dev_playback=True,
            streaming_enabled=True,
            max_audio_bytes=128,
        ),
        capture=VoiceCaptureConfig(
            enabled=True,
            provider="mock",
            device="test-mic",
            allow_dev_capture=True,
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
    )


def _streaming_service() -> tuple[Any, EventBuffer]:
    events = EventBuffer(capacity=128)
    service = build_voice_subsystem(_voice_config(), _openai_config(), events=events)
    service.provider = MockVoiceProvider(
        stt_transcript="what time is it?",
        stt_confidence=0.91,
        tts_audio_bytes=b"first-output-chunk-second-output-chunk",
        tts_stream_chunk_size=10,
    )
    service.capture_provider = MockCaptureProvider(
        capture_audio_bytes=b"captured wake loop audio",
        duration_ms=800,
    )
    service.playback_provider = NullStreamingPlaybackProvider()
    service.attach_core_bridge(
        RecordingCoreBridge(
            route_family="clock",
            subsystem="tools",
            spoken_summary="The time is 10:15.",
            visual_summary="The time is 10:15.",
        )
    )
    return service, events


def _accepted_wake_session(service: Any) -> Any:
    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    wake = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.93)
    )
    return asyncio.run(service.accept_wake_event(wake.wake_event_id))


def test_null_streaming_playback_sink_accepts_chunks_without_user_heard_claim() -> None:
    provider = NullStreamingPlaybackProvider()
    session = provider.start_stream(
        VoiceLivePlaybackRequest(
            speech_request_id="voice-speech-test",
            provider="null_stream",
            device="null-stream",
            audio_format="pcm",
            session_id="voice-session",
            turn_id="turn-1",
            allowed_to_play=True,
        )
    )
    first = provider.feed_stream_chunk(session.playback_stream_id, b"audio-1")
    second = provider.feed_stream_chunk(session.playback_stream_id, b"audio-2")
    completed = provider.complete_stream(session.playback_stream_id)
    payload = completed.to_dict()

    assert session.status == "started"
    assert first.ok is True
    assert first.playback_started is True
    assert first.metadata["sink_kind"] == "null_stream"
    assert first.metadata["null_sink_first_accept_ms"] >= 0
    assert second.chunk_index == 1
    assert completed.ok is True
    assert completed.status == "completed"
    assert completed.provider == "null_stream"
    assert completed.user_heard_claimed is False
    assert completed.metadata["sink_kind"] == "null_stream"
    assert completed.metadata["first_output_start_ms"] >= 0
    assert completed.metadata["raw_audio_logged"] is False
    assert "audio-1" not in str(payload)
    assert "raw_audio_bytes" not in str(payload).lower()


def test_build_voice_subsystem_can_select_null_stream_sink() -> None:
    service = build_voice_subsystem(
        _voice_config(playback_provider="null_stream"),
        _openai_config(),
    )

    assert service.playback_provider.name == "null_stream"
    assert service.playback_provider.get_availability()["sink_kind"] == "null_stream"


def test_wake_loop_play_response_uses_core_approved_streaming_to_null_sink() -> None:
    service, events = _streaming_service()
    wake_session = _accepted_wake_session(service)

    result = asyncio.run(
        service.run_wake_supervised_voice_loop(
            wake_session.wake_session_id,
            synthesize_response=True,
            play_response=True,
        )
    )
    payloads = [record["payload"] for record in events.recent(limit=128)]

    assert result.ok is True
    assert result.final_status == "completed"
    assert result.wake_loop_streaming_output_used is True
    assert result.wake_loop_streaming_miss_reason == ""
    assert result.streaming_transport_kind == "mock_stream"
    assert result.sink_kind == "null_stream"
    assert result.first_output_start_ms is not None
    assert result.first_chunk_before_complete is True
    assert result.truth_flags["wake_alone_authorizes_speech"] is False
    assert result.truth_flags["stt_final_authorizes_speech"] is False
    assert result.truth_flags["null_sink_started_is_user_heard_audio"] is False
    assert service.last_synthesis_result is None
    assert service.last_streaming_tts_result is not None
    assert service.last_live_playback_result is not None
    assert any(
        payload.get("event_type") == "voice.playback_stream_completed"
        and payload.get("provider") == "null_stream"
        for payload in payloads
    )
    assert "first-output-chunk" not in str(result.to_dict())


def test_wake_alone_does_not_start_streaming_output() -> None:
    service, _events = _streaming_service()
    wake_session = _accepted_wake_session(service)

    assert wake_session.status == "active"
    assert service.last_streaming_tts_result is None
    snapshot = service.status_snapshot()
    loop_status = snapshot["wake_supervised_loop"]
    assert loop_status["wake_loop_streaming_output_used"] is False
    assert loop_status["wake_loop_streaming_miss_reason"] == "not_started"


def test_l53_trace_and_kraken_report_expose_sink_and_wake_streaming_fields() -> None:
    trace = build_latency_trace(
        metadata={
            "voice_first_audio": {
                "streaming_enabled": True,
                "streaming_transport_kind": "true_http_stream",
                "request_to_first_audio_ms": 88,
                "core_result_to_first_audio_ms": 71,
                "tts_start_to_first_chunk_ms": 44,
                "first_chunk_to_playback_start_ms": 6,
                "first_chunk_to_sink_accept_ms": 6,
                "first_output_start_ms": 88,
                "null_sink_first_accept_ms": 6,
                "sink_kind": "null_stream",
                "live_openai_voice_smoke_run": True,
                "wake_loop_streaming_output_used": True,
                "wake_loop_streaming_miss_reason": "",
                "realtime_deferred_to_l6": True,
                "realtime_session_creation_attempted": False,
                "raw_audio_logged": False,
                "user_heard_claimed": False,
            }
        },
        stage_timings_ms={},
        request_id="voice-request",
        session_id="voice-session",
        surface_mode="voice",
        route_family="voice_control",
        subsystem="voice",
        voice_involved=True,
    )
    row = trace.to_summary_dict()
    report = _kraken_latency_report([row])

    assert row["voice_sink_kind"] == "null_stream"
    assert row["voice_first_output_start_ms"] == 88
    assert row["voice_null_sink_first_accept_ms"] == 6
    assert row["voice_live_openai_voice_smoke_run"] is True
    assert row["voice_wake_loop_streaming_output_used"] is True
    assert row["voice_realtime_deferred_to_l6"] is True
    assert row["voice_user_heard_claimed"] is False
    assert report["voice_sink_kind_counts"] == {"null_stream": 1}
    assert report["voice_wake_loop_streaming_output_used_count"] == 1
    assert report["voice_live_openai_smoke_run_count"] == 1
    assert report["voice_realtime_deferred_to_l6_count"] == 1


def test_live_smoke_modes_are_opt_in_and_null_sink_artifacts_are_bounded(
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    from scripts.voice_first_audio_smoke import run_live_openai_stream_smoke
    from scripts.voice_first_audio_smoke import run_mock_stream_smoke

    monkeypatch.delenv("STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    live = run_live_openai_stream_smoke(tmp_path / "live", env=os.environ)
    mock = run_mock_stream_smoke(tmp_path / "mock", sink_kind="null_stream")
    summary = json.loads(
        (tmp_path / "mock" / "voice_first_audio_smoke_summary.json").read_text()
    )
    events = (tmp_path / "mock" / "voice_first_audio_smoke_events.jsonl").read_text()

    assert live["summary"]["status"] == "skipped"
    assert live["summary"]["mode"] == "openai-stream"
    assert "STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE=1" in live["summary"]["reason"]
    assert mock["summary"]["sink_kind_counts"]["null_stream"] >= 1
    assert summary["first_output_start_ms"]["count"] >= 1
    assert summary["null_sink_first_accept_ms"]["count"] >= 1
    assert summary["raw_audio_logged"] is False
    assert summary["user_heard_claimed"] is False
    assert "first-output" not in events
    assert "raw_audio_bytes" not in events.lower()


def test_live_smoke_env_loader_reads_local_env_without_revealing_api_key(
    tmp_path: Any,
) -> None:
    from scripts.voice_first_audio_smoke import load_smoke_env
    from scripts.voice_first_audio_smoke import smoke_env_status

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=sk-test-secret-do-not-print",
                "STORMHELM_OPENAI_ENABLED=1",
                "STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE=1",
            ]
        ),
        encoding="utf-8",
    )

    env = load_smoke_env(base_env={}, env_file=env_file)
    status = smoke_env_status(env)

    assert env["OPENAI_API_KEY"] == "sk-test-secret-do-not-print"
    assert status == {
        "OPENAI_API_KEY": "present",
        "STORMHELM_OPENAI_ENABLED": "enabled",
        "STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE": "enabled",
        "raw_secret_logged": False,
    }
    assert "sk-test-secret" not in json.dumps(status)


def test_live_openai_smoke_requires_openai_enabled_gate(tmp_path: Any) -> None:
    from scripts.voice_first_audio_smoke import run_live_openai_stream_smoke

    result = run_live_openai_stream_smoke(
        tmp_path / "live",
        env={
            "OPENAI_API_KEY": "sk-test-secret-do-not-print",
            "STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE": "1",
        },
    )

    assert result["summary"]["status"] == "skipped"
    assert "STORMHELM_OPENAI_ENABLED=1" in result["summary"]["reason"]
    assert "sk-test-secret" not in json.dumps(result["summary"])
