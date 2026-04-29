from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.api.app import create_app
from stormhelm.core.latency import build_latency_trace
from stormhelm.core.orchestrator.command_eval.report import _kraken_latency_report
from stormhelm.core.voice.models import VoiceSpeechRequest
from stormhelm.core.voice.models import VoiceStreamingTTSRequest
from stormhelm.core.voice.providers import MockCaptureProvider
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.providers import OpenAIVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge


class _FakeAssistant:
    async def handle_message(self, *args: Any, **kwargs: Any) -> dict[str, object]:
        return {
            "assistant_message": {
                "message_id": "assistant-voice-1",
                "role": "assistant",
                "content": "Weather is clear.",
                "metadata": {
                    "bearing_title": "Weather",
                    "micro_response": "Weather is clear.",
                    "full_response": "Weather is clear.",
                },
            },
            "jobs": [],
            "actions": [],
        }


class _FakeVoice:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self.synth_calls: list[dict[str, object]] = []
        self.play_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []
        self.played = threading.Event()
        self.streamed = threading.Event()

    async def synthesize_speech_text(self, text: str, **kwargs: Any) -> Any:
        self.synth_calls.append({"text": text, **kwargs})
        return SimpleNamespace(ok=True, synthesis_id="synthesis-chat-1")

    async def play_speech_output(self, synthesis: Any, **kwargs: Any) -> Any:
        self.play_calls.append({"synthesis": synthesis, **kwargs})
        self.played.set()
        return SimpleNamespace(ok=True, status="completed", user_heard_claimed=False)

    async def stream_core_approved_spoken_text(self, text: str, **kwargs: Any) -> Any:
        self.stream_calls.append({"text": text, **kwargs})
        self.streamed.set()
        return SimpleNamespace(
            ok=True,
            status="completed",
            streaming_enabled=True,
            first_audio_available=True,
            streaming_transport_kind="mock_stream",
            user_heard_claimed=False,
        )

    def prewarm_voice_output(self, **kwargs: Any) -> Any:
        return SimpleNamespace(ok=True, status="prepared", prewarm_ms=0)

    def status_snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled,
            "tts": {
                "streaming_enabled": self.config.openai.stream_tts_outputs,
                "streaming_transport_kind": "mock_stream"
                if self.stream_calls
                else None,
            },
            "playback": {
                "enabled": self.config.playback.enabled,
                "streaming_enabled": self.config.playback.streaming_enabled,
                "user_heard_claimed": False,
            },
        }


class _FakeEvents:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []

    def publish(self, **payload: object) -> None:
        self.published.append(dict(payload))


class _FakeContainer:
    def __init__(self, voice: _FakeVoice) -> None:
        self.voice = voice
        self.assistant = _FakeAssistant()
        self.events = _FakeEvents()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _openai_config(
    *, enabled: bool = True, api_key: str | None = "test-key"
) -> OpenAIConfig:
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
    values: dict[str, Any] = {
        "enabled": True,
        "mode": "manual",
        "manual_input_enabled": True,
        "spoken_responses_enabled": True,
        "debug_mock_provider": True,
        "openai": VoiceOpenAIConfig(
            stream_tts_outputs=True,
            tts_live_format="pcm",
            tts_artifact_format="mp3",
            max_audio_bytes=128,
            max_audio_seconds=4,
        ),
        "playback": VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            device="test-device",
            allow_dev_playback=True,
            streaming_enabled=True,
            max_audio_bytes=128,
        ),
        "capture": VoiceCaptureConfig(
            enabled=True,
            provider="mock",
            device="test-mic",
            allow_dev_capture=True,
            max_audio_bytes=128,
        ),
    }
    values.update(overrides)
    return VoiceConfig(**values)


def _speech_request(text: str = "Core approved this sentence.") -> VoiceSpeechRequest:
    return VoiceSpeechRequest(
        source="core_spoken_summary",
        text=text,
        persona_mode="ghost",
        speech_length_hint="short",
        provider="openai",
        model="gpt-4o-mini-tts",
        voice="onyx",
        format="pcm",
        allowed_to_synthesize=True,
        session_id="voice-session",
        turn_id="voice-turn-1",
        result_state_source="completed",
    )


def _service() -> Any:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.provider = MockVoiceProvider(
        stt_transcript="what time is it?",
        stt_confidence=0.91,
        tts_audio_bytes=b"first-second-third-fourth",
        tts_stream_chunk_size=6,
    )
    service.capture_provider = MockCaptureProvider(
        capture_audio_bytes=b"captured voice",
        duration_ms=900,
    )
    service.playback_provider = MockPlaybackProvider(complete_immediately=False)
    service.attach_core_bridge(
        RecordingCoreBridge(
            route_family="clock",
            subsystem="tools",
            spoken_summary="The time is 10:15.",
        )
    )
    return service


def test_openai_streaming_transport_labels_true_stream_and_buffered_projection() -> None:
    request = VoiceStreamingTTSRequest.from_speech_request(
        _speech_request(),
        live_format="pcm",
        artifact_format="mp3",
    )
    true_provider = OpenAIVoiceProvider(
        config=_voice_config(debug_mock_provider=False),
        openai_config=_openai_config(),
        post_speech_stream=lambda **kwargs: [b"one", b"two", b"three"],
    )
    buffered_provider = OpenAIVoiceProvider(
        config=_voice_config(debug_mock_provider=False),
        openai_config=_openai_config(),
        post_speech=lambda **kwargs: b"buffered audio",
    )

    true_result = asyncio.run(true_provider.stream_speech(request))
    buffered_result = asyncio.run(buffered_provider.stream_speech(request))

    assert true_result.ok is True
    assert true_result.streaming_transport_kind == "true_http_stream"
    assert true_result.first_chunk_before_complete is True
    assert true_result.total_chunks == 3
    assert true_result.bytes_total_summary_only == len(b"onetwothree")
    assert buffered_result.ok is True
    assert buffered_result.streaming_transport_kind == "buffered_chunk_projection"
    assert buffered_result.first_chunk_before_complete is False
    assert "buffered audio" not in str(buffered_result.to_dict())


def test_chat_send_uses_streaming_for_core_approved_assistant_voice_output(
    monkeypatch: Any,
    temp_config: Any,
) -> None:
    voice = _FakeVoice(_voice_config())
    container = _FakeContainer(voice)
    monkeypatch.setattr(
        "stormhelm.core.api.app.build_container",
        lambda config=None: container,
    )

    with TestClient(create_app(temp_config)) as client:
        response = client.post("/chat/send", json={"message": "what is the weather"})
        assert voice.streamed.wait(2)

    payload = response.json()
    metadata = payload["assistant_message"]["metadata"]
    voice_output = metadata["voice_output"]

    assert response.status_code == 200
    assert voice.stream_calls[0]["text"] == "Weather is clear."
    assert voice.stream_calls[0]["speak_allowed"] is True
    assert voice.stream_calls[0]["source"] == "assistant_response"
    assert voice.synth_calls == []
    assert voice.play_calls == []
    assert voice_output["scheduled"] is True
    assert voice_output["streaming_requested"] is True
    assert voice_output["output_mode"] == "streaming"
    assert voice_output["completion_claimed"] is False
    assert voice_output["verification_claimed"] is False
    assert voice_output["user_heard_claimed"] is False


def test_capture_audio_turn_play_response_uses_streaming_output_when_enabled() -> None:
    service = _service()

    session = asyncio.run(service.start_push_to_talk_capture(session_id="voice-session"))
    result = asyncio.run(
        service.capture_and_submit_turn(
            session.capture_id,
            mode="ghost",
            synthesize_response=False,
            play_response=True,
        )
    )

    assert result.final_status == "completed"
    assert result.streaming_output_result is not None
    assert result.streaming_output_result.streaming_enabled is True
    assert result.streaming_output_result.tts_result is not None
    assert result.streaming_output_result.tts_result.streaming_transport_kind == "mock_stream"
    assert result.streaming_output_result.playback_result is not None
    assert result.streaming_output_result.playback_result.user_heard_claimed is False
    assert service.last_streaming_tts_result is not None
    assert service.last_live_playback_result is not None
    assert service.last_synthesis_result is None


def test_voice_status_and_trace_expose_l51_streaming_reality_fields() -> None:
    service = _service()
    output = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved this spoken sentence.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-1",
            core_result_completed_ms=20,
            request_started_ms=0,
        )
    )
    status = service.status_snapshot()
    trace = build_latency_trace(
        metadata={
            "voice_first_audio": output.latency.to_dict()
            | {
                "voice_streaming_tts_enabled": True,
                "voice_streaming_transport_kind": output.streaming_transport_kind,
                "voice_stream_used_by_normal_path": True,
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
    payload = trace.to_summary_dict()

    assert status["tts"]["streaming_transport_kind"] == "mock_stream"
    assert status["tts"]["streaming_tts_status"] == "completed"
    assert status["tts"]["first_audio_ms"] == output.latency.request_to_first_audio_ms
    assert status["playback"]["live_playback_supported"] is True
    assert status["playback"]["live_playback_status"] == "completed"
    assert status["playback"]["user_heard_claimed"] is False
    assert payload["voice_streaming_transport_kind"] == "mock_stream"
    assert payload["voice_stream_used_by_normal_path"] is True
    assert payload["voice_first_audio_ms"] == output.latency.request_to_first_audio_ms


def test_kraken_report_counts_streaming_transport_and_normal_path_misses() -> None:
    report = _kraken_latency_report(
        [
            {
                "case_id": "voice-stream",
                "route_family": "voice_control",
                "total_latency_ms": 100,
                "voice_streaming_tts_enabled": True,
                "voice_streaming_transport_kind": "mock_stream",
                "voice_stream_used_by_normal_path": True,
                "voice_first_audio_ms": 42,
            },
            {
                "case_id": "voice-buffered",
                "route_family": "voice_control",
                "total_latency_ms": 120,
                "voice_streaming_tts_enabled": True,
                "voice_streaming_transport_kind": "buffered_chunk_projection",
                "voice_stream_used_by_normal_path": False,
                "voice_streaming_miss_reason": "pipeline_still_buffered",
            },
        ]
    )

    assert report["voice_streaming_transport_kind_counts"] == {
        "buffered_chunk_projection": 1,
        "mock_stream": 1,
    }
    assert report["voice_streaming_path_used_count"] == 1
    assert report["voice_buffered_projection_count"] == 1
    assert report["normal_path_streaming_miss_count"] == 1


def test_mock_first_audio_smoke_harness_writes_bounded_artifacts(tmp_path: Any) -> None:
    from scripts.voice_first_audio_smoke import run_mock_stream_smoke

    result = run_mock_stream_smoke(output_dir=tmp_path)
    summary = json.loads((tmp_path / "voice_first_audio_smoke_summary.json").read_text())
    report = (tmp_path / "voice_first_audio_smoke_report.md").read_text()
    events = (tmp_path / "voice_first_audio_smoke_events.jsonl").read_text()

    assert result["summary"]["scenario_count"] >= 5
    assert summary["streaming_transport_kind_counts"]["mock_stream"] >= 1
    assert summary["first_audio_ms"]["max"] >= 0
    assert summary["partial_playback_count"] >= 1
    assert summary["interruption_count"] >= 1
    assert "raw_audio" not in report.lower()
    assert "first-second-third" not in events
