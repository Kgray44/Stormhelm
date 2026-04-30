from __future__ import annotations

import asyncio
import time
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.latency import build_latency_trace
from stormhelm.core.voice.evaluation import VoiceLatencyBreakdown
from stormhelm.core.voice.models import VoiceInterruptionIntent
from stormhelm.core.voice.models import VoiceLivePlaybackRequest
from stormhelm.core.voice.models import VoiceLivePlaybackSession
from stormhelm.core.voice.models import VoicePlaybackPrewarmRequest
from stormhelm.core.voice.models import VoiceProviderPrewarmRequest
from stormhelm.core.voice.models import VoiceSpeechRequest
from stormhelm.core.voice.models import VoiceStreamingTTSResult
from stormhelm.core.voice.models import VoiceStreamingTTSRequest
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.providers import NullStreamingPlaybackProvider
from stormhelm.core.voice.providers import LocalPlaybackProvider
from stormhelm.core.voice.providers import OpenAIVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem
from tests.test_voice_playback_provider import FakeStreamingSpeakerBackend


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
        "spoken_responses_enabled": True,
        "debug_mock_provider": True,
        "openai": VoiceOpenAIConfig(
            stream_tts_outputs=True,
            tts_live_format="pcm",
            tts_artifact_format="mp3",
            max_tts_chars=240,
        ),
        "playback": VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            device="test-device",
            volume=0.5,
            allow_dev_playback=True,
            streaming_enabled=True,
            max_audio_bytes=128,
            max_duration_ms=5000,
        ),
    }
    values.update(overrides)
    return VoiceConfig(**values)


def _speech_request(
    text: str = "Core approved this spoken sentence.",
) -> VoiceSpeechRequest:
    return VoiceSpeechRequest(
        source="core_spoken_summary",
        text=text,
        persona_mode="ghost",
        speech_length_hint="short",
        provider="mock",
        model="mock-tts",
        voice="mock-voice",
        format="pcm",
        allowed_to_synthesize=True,
        session_id="voice-session",
        turn_id="voice-turn-1",
        result_state_source="completed",
    )


def _service(*, events: EventBuffer | None = None):
    service = build_voice_subsystem(_voice_config(), _openai_config(), events=events)
    service.provider = MockVoiceProvider(
        tts_audio_bytes=b"first-second-third", tts_stream_chunk_size=5
    )
    service.playback_provider = MockPlaybackProvider(complete_immediately=False)
    return service


class UnsupportedStreamingPlaybackProvider(MockPlaybackProvider):
    provider_name = "local"
    name = "local"

    def start_stream(
        self, request: VoiceLivePlaybackRequest
    ) -> VoiceLivePlaybackSession:
        return VoiceLivePlaybackSession(
            playback_stream_id=request.playback_stream_id,
            playback_request_id=request.playback_request_id,
            provider="local",
            device=request.device,
            audio_format=request.audio_format,
            status="unsupported",
            session_id=request.session_id,
            turn_id=request.turn_id,
            tts_stream_id=request.tts_stream_id,
            speech_request_id=request.speech_request_id,
            error_code="streaming_playback_backend_unsupported",
            error_message="Live streaming playback is unsupported by this backend.",
            user_heard_claimed=False,
        )


class RecordingNullPlaybackProvider(NullStreamingPlaybackProvider):
    def __init__(self) -> None:
        super().__init__(complete_immediately=False)
        self.feed_times: list[float] = []

    def feed_stream_chunk(self, playback_stream_id: str, data: bytes, *, chunk_index: int | None = None):
        self.feed_times.append(time.perf_counter())
        return super().feed_stream_chunk(
            playback_stream_id,
            data,
            chunk_index=chunk_index,
        )


class DelayedProgressiveMockVoiceProvider(MockVoiceProvider):
    def __init__(self) -> None:
        super().__init__(
            tts_audio_bytes=b"first-second-third-fourth",
            tts_stream_chunk_size=6,
        )
        self.progressive_callback_times: list[float] = []
        self.accumulated_completed_at: float | None = None
        self.progressive_completed_at: float | None = None

    async def stream_speech(self, request: VoiceStreamingTTSRequest) -> VoiceStreamingTTSResult:
        await asyncio.sleep(0.03)
        result = await MockVoiceProvider.stream_speech_progressive(self, request, None)
        self.accumulated_completed_at = time.perf_counter()
        return result

    async def stream_speech_progressive(
        self,
        request: VoiceStreamingTTSRequest,
        on_chunk,
    ) -> VoiceStreamingTTSResult:
        async def delayed_callback(chunk):
            await asyncio.sleep(0.01)
            await on_chunk(chunk)
            self.progressive_callback_times.append(time.perf_counter())

        result = await MockVoiceProvider.stream_speech_progressive(
            self,
            request,
            delayed_callback,
        )
        self.progressive_completed_at = time.perf_counter()
        return result


def test_service_feeds_null_sink_progressively_before_provider_completion() -> None:
    service = _service()
    provider = DelayedProgressiveMockVoiceProvider()
    playback = RecordingNullPlaybackProvider()
    service.provider = provider
    service.playback_provider = playback

    result = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved progressive speech.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-progressive",
            core_result_completed_ms=20,
            request_started_ms=0,
        )
    )

    assert result.ok is True
    assert provider.progressive_callback_times
    assert provider.progressive_completed_at is not None
    assert playback.feed_times
    assert playback.feed_times[0] < provider.progressive_completed_at
    assert result.first_chunk_before_complete is True
    assert result.latency.first_output_start_ms is not None
    assert result.latency.stream_complete_ms is not None
    assert result.latency.first_output_start_ms < result.latency.stream_complete_ms
    assert result.latency.null_sink_first_accept_ms is not None
    assert result.playback_result is not None
    assert result.playback_result.user_heard_claimed is False


def test_service_feeds_local_speaker_sink_progressively_and_claims_real_output() -> None:
    service = _service()
    provider = DelayedProgressiveMockVoiceProvider()
    speaker_backend = FakeStreamingSpeakerBackend()
    playback = LocalPlaybackProvider(
        config=_voice_config(
            playback=VoicePlaybackConfig(
                enabled=True,
                provider="local",
                device="test-device",
                volume=0.5,
                allow_dev_playback=True,
                streaming_enabled=True,
            )
        ),
        backend=speaker_backend,
    )
    service.provider = provider
    service.playback_provider = playback

    result = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved progressive speaker speech.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-progressive-speaker",
            core_result_completed_ms=20,
            request_started_ms=0,
        )
    )
    payload = result.to_dict()

    assert result.ok is True
    assert provider.progressive_completed_at is not None
    assert speaker_backend.stream_feed_calls
    assert provider.progressive_callback_times[0] < provider.progressive_completed_at
    assert result.playback_result is not None
    assert result.playback_result.provider == "local"
    assert result.playback_result.user_heard_claimed is True
    assert result.latency.user_heard_claimed is True
    assert payload["user_heard_claimed"] is True
    assert result.latency.first_output_start_ms is not None
    assert result.latency.stream_complete_ms is not None
    assert result.latency.first_output_start_ms < result.latency.stream_complete_ms


def test_streaming_tts_models_are_bounded_and_redact_audio_bytes() -> None:
    provider = MockVoiceProvider(
        tts_audio_bytes=b"private streaming bytes",
        tts_stream_chunk_size=7,
    )
    request = VoiceStreamingTTSRequest.from_speech_request(
        _speech_request("Approved text only."),
        live_format="pcm",
        artifact_format="mp3",
    )

    result = asyncio.run(provider.stream_speech(request))
    payload = result.to_dict()

    assert result.ok is True
    assert result.streaming_started is True
    assert result.streaming_completed is True
    assert result.total_chunks >= 2
    assert result.first_chunk_at is not None
    assert result.final_chunk_at is not None
    assert payload["raw_audio_present"] is False
    assert all(chunk["raw_audio_present"] is False for chunk in payload["chunks"])
    assert "private streaming bytes" not in str(payload)
    assert "data': b" not in str(payload)


def test_streaming_tts_failure_before_and_after_first_chunk_are_typed() -> None:
    before = MockVoiceProvider(tts_stream_error_code="stream_failed").stream_speech(
        VoiceStreamingTTSRequest.from_speech_request(_speech_request())
    )
    after = MockVoiceProvider(
        tts_audio_bytes=b"chunk-one-chunk-two",
        tts_stream_chunk_size=5,
        tts_stream_fail_after_chunks=1,
        tts_stream_error_code="stream_interrupted",
    ).stream_speech(VoiceStreamingTTSRequest.from_speech_request(_speech_request()))

    before_result = asyncio.run(before)
    after_result = asyncio.run(after)

    assert before_result.ok is False
    assert before_result.status == "failed"
    assert before_result.first_chunk_at is None
    assert before_result.partial_audio is False
    assert after_result.ok is False
    assert after_result.status == "partial_failed"
    assert after_result.first_chunk_at is not None
    assert after_result.partial_audio is True


def test_live_playback_stream_accepts_chunks_and_never_claims_user_heard() -> None:
    provider = MockPlaybackProvider(complete_immediately=False)
    session = provider.start_stream(
        VoiceLivePlaybackRequest(
            speech_request_id="voice-speech-test",
            provider="mock",
            device="test-device",
            audio_format="pcm",
            session_id="voice-session",
            turn_id="voice-turn",
            allowed_to_play=True,
        )
    )
    chunk_1 = provider.feed_stream_chunk(session.playback_stream_id, b"abc")
    chunk_2 = provider.feed_stream_chunk(session.playback_stream_id, b"def")
    completed = provider.complete_stream(session.playback_stream_id)

    assert isinstance(session, VoiceLivePlaybackSession)
    assert session.status == "started"
    assert chunk_1.ok is True
    assert chunk_1.playback_started is True
    assert chunk_2.chunk_index == 1
    assert completed.ok is True
    assert completed.status == "completed"
    assert completed.partial_playback is False
    assert completed.user_heard_claimed is False
    assert "abcdef" not in str(completed.to_dict())


def test_prewarm_paths_do_not_start_tts_or_playback() -> None:
    service = _service()

    prewarm = service.prewarm_voice_output(session_id="voice-session")
    status = service.status_snapshot()

    assert prewarm.provider_result is not None
    assert prewarm.playback_result is not None
    assert prewarm.provider_result.tts_called is False
    assert prewarm.playback_result.playback_started is False
    assert service.provider.tts_call_count == 0
    assert service.playback_provider.playback_call_count == 0
    assert status["tts"]["provider_prewarmed"] is True
    assert status["playback"]["playback_prewarmed"] is True


def test_openai_provider_prewarm_builds_request_shell_without_network_or_secret_leak() -> None:
    provider = OpenAIVoiceProvider(
        config=_voice_config(
            debug_mock_provider=False,
            openai=VoiceOpenAIConfig(
                stream_tts_outputs=True,
                tts_live_format="pcm",
                tts_artifact_format="mp3",
                tts_model="gpt-4o-mini-tts",
                tts_voice="cedar",
            ),
        ),
        openai_config=_openai_config(api_key="secret-test-key"),
    )

    result = provider.prewarm_speech_provider(
        VoiceProviderPrewarmRequest(session_id="voice-session")
    )
    payload = result.to_dict()

    assert result.ok is True
    assert result.client_prepared is True
    assert result.tts_called is False
    assert provider.network_call_count == 0
    assert payload["api_key_present"] is True
    assert "secret-test-key" not in str(payload)


def test_streaming_pipeline_waits_for_approved_text_and_speak_allowed() -> None:
    service = _service()

    blocked = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core did not approve speech.",
            speak_allowed=False,
            session_id="voice-session",
            turn_id="voice-turn-1",
        )
    )
    spoken = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved this spoken sentence.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-2",
            core_result_completed_ms=20,
            request_started_ms=0,
        )
    )

    assert blocked.ok is False
    assert blocked.status == "blocked"
    assert blocked.error_code == "speak_not_allowed"
    assert service.provider.tts_call_count == 1
    assert spoken.ok is True
    assert spoken.streaming_enabled is True
    assert spoken.first_audio_available is True
    assert spoken.playback_result is not None
    assert spoken.playback_result.user_heard_claimed is False
    assert spoken.completion_claimed is False
    assert spoken.verification_claimed is False
    assert spoken.latency.core_result_to_first_audio_ms is not None
    assert spoken.latency.tts_start_to_first_chunk_ms is not None


def test_unsupported_live_playback_does_not_claim_first_audio_started() -> None:
    service = _service()
    service.playback_provider = UnsupportedStreamingPlaybackProvider(
        complete_immediately=False
    )

    result = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved this spoken sentence.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-unsupported-playback",
            core_result_completed_ms=20,
            request_started_ms=0,
        )
    )
    payload = result.to_dict()

    assert result.ok is False
    assert result.status == "unsupported"
    assert result.first_audio_available is False
    assert result.error_code == "streaming_playback_backend_unsupported"
    assert result.latency.first_audio_available is False
    assert result.latency.first_output_start_ms is None
    assert payload["user_heard_claimed"] is False


def test_streaming_failure_before_first_audio_uses_explicit_buffered_fallback() -> None:
    service = _service()
    service.provider.tts_stream_error_code = "stream_failed_before_audio"

    result = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved fallback speech.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-fallback",
        )
    )
    payload = result.to_dict()

    assert result.fallback_used is True
    assert result.tts_result is not None
    assert result.tts_result.status == "failed"
    assert result.buffered_synthesis_result is not None
    assert result.buffered_synthesis_result.ok is True
    assert result.buffered_playback_result is not None
    assert result.buffered_playback_result.user_heard_claimed is False
    assert result.latency.fallback_used is True
    assert "first-second-third" not in str(payload)


def test_streaming_failure_after_partial_playback_does_not_replay_from_start() -> None:
    service = _service()
    service.provider.tts_stream_fail_after_chunks = 1
    service.provider.tts_stream_error_code = "stream_failed_after_partial"

    result = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved partial speech.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-partial",
        )
    )

    assert result.ok is False
    assert result.fallback_used is False
    assert result.buffered_synthesis_result is None
    assert result.playback_result is not None
    assert result.playback_result.status == "cancelled"
    assert result.playback_result.partial_playback is True
    assert result.partial_playback is True


def test_stop_speaking_cancels_active_stream_without_cancelling_core_task() -> None:
    service = _service()
    started = service.playback_provider.start_stream(
        VoiceLivePlaybackRequest(
            speech_request_id="voice-speech-test",
            provider="mock",
            device="test-device",
            audio_format="pcm",
            session_id="voice-session",
            allowed_to_play=True,
        )
    )

    result = asyncio.run(
        service.stop_speaking(
            session_id="voice-session",
            playback_id=started.playback_stream_id,
            reason="user_requested",
        )
    )

    assert result.status == "completed"
    assert result.core_task_cancelled is False
    assert result.core_result_mutated is False
    assert result.playback_result is not None
    assert result.playback_result.status == "cancelled"
    assert result.playback_result.partial_playback is False
    assert result.playback_result.user_heard_claimed is False


def test_stop_speaking_suppresses_pending_stream_before_playback_starts() -> None:
    service = _service()
    request = _speech_request("Core approved pending streaming speech.")
    service.last_speech_request = request
    service.last_streaming_tts_request = VoiceStreamingTTSRequest.from_speech_request(
        request,
        live_format="pcm",
        artifact_format="mp3",
    )

    result = asyncio.run(
        service.stop_speaking(session_id="voice-session", reason="user_requested")
    )

    assert result.status == "completed"
    assert result.spoken_output_suppressed is True
    assert result.output_stopped is True
    assert result.core_task_cancelled is False
    assert result.core_result_mutated is False
    assert service.current_response_suppressed is True
    assert service._speech_output_block_reason(None) == "current_response_suppressed"


def test_stream_cancelled_before_feed_does_not_claim_first_audio_started() -> None:
    service = _service()

    class SuppressingVoiceProvider(MockVoiceProvider):
        async def stream_speech_progressive(
            self,
            request: VoiceStreamingTTSRequest,
            on_chunk,
        ):
            service.current_response_suppressed = True
            return await super().stream_speech_progressive(request, on_chunk)

    service.provider = SuppressingVoiceProvider(
        tts_audio_bytes=b"first-second-third",
        tts_stream_chunk_size=5,
    )

    result = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved but operator stopped speech.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-cancel-before-feed",
            core_result_completed_ms=20,
            request_started_ms=0,
        )
    )

    assert result.status == "cancelled"
    assert result.first_audio_available is False
    assert result.partial_playback is False
    assert result.latency.first_audio_available is False
    assert result.latency.first_output_start_ms is None
    assert result.playback_result is not None
    assert result.playback_result.user_heard_claimed is False


def test_stop_speaking_after_progressive_first_chunk_marks_partial_output() -> None:
    service = _service()
    first_chunk_fed = asyncio.Event()
    release_stream = asyncio.Event()

    class PausingProgressiveProvider(MockVoiceProvider):
        async def stream_speech_progressive(
            self,
            request: VoiceStreamingTTSRequest,
            on_chunk,
        ) -> VoiceStreamingTTSResult:
            async def pausing_callback(chunk):
                await on_chunk(chunk)
                if chunk.chunk_index == 0:
                    first_chunk_fed.set()
                    await release_stream.wait()

            return await MockVoiceProvider.stream_speech_progressive(
                self,
                request,
                pausing_callback,
            )

    service.provider = PausingProgressiveProvider(
        tts_audio_bytes=b"first-second-third",
        tts_stream_chunk_size=5,
    )
    service.playback_provider = RecordingNullPlaybackProvider()

    async def scenario():
        stream_task = asyncio.create_task(
            service.stream_core_approved_spoken_text(
                "Core approved interruptible speech.",
                speak_allowed=True,
                session_id="voice-session",
                turn_id="voice-turn-stop-after-first",
                core_result_completed_ms=20,
                request_started_ms=0,
            )
        )
        await asyncio.wait_for(first_chunk_fed.wait(), timeout=1)
        stop_result = await service.stop_speaking(
            session_id="voice-session",
            reason="user_requested",
        )
        release_stream.set()
        return stop_result, await stream_task

    stop_result, stream_result = asyncio.run(scenario())

    assert stop_result.core_task_cancelled is False
    assert stop_result.core_result_mutated is False
    assert stream_result.status == "cancelled"
    assert stream_result.first_audio_available is True
    assert stream_result.partial_playback is True
    assert stream_result.playback_result is not None
    assert stream_result.playback_result.partial_playback is True
    assert stream_result.playback_result.user_heard_claimed is False


def test_mute_blocks_new_streaming_speech() -> None:
    service = _service()

    muted = asyncio.run(
        service.set_spoken_output_muted(True, scope="session", reason="operator_mute")
    )
    blocked = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Approved but muted.",
            speak_allowed=True,
            session_id="voice-session",
        )
    )

    assert muted.intent == VoiceInterruptionIntent.MUTE_SPOKEN_RESPONSES
    assert blocked.ok is False
    assert blocked.status == "blocked"
    assert blocked.error_code == "spoken_output_muted"
    assert service.provider.tts_call_count == 0


def test_voice_first_audio_latency_summary_and_trace_fields_are_serializable() -> None:
    breakdown = VoiceLatencyBreakdown.from_marks(
        {
            "wake": 0,
            "ghost": 20,
            "stt_complete": 120,
            "core_bridge_complete": 200,
            "spoken_render_complete": 230,
            "tts_started": 240,
            "first_tts_chunk_received": 310,
            "playback_started": 360,
            "playback_completed": 620,
        },
        budget_label="voice_hot_path",
    )
    summary = breakdown.to_latency_summary(request_id="voice-request", session_id="s")
    trace = build_latency_trace(
        metadata={
            "voice_streaming_tts_enabled": True,
            "voice_live_format": "pcm",
            "voice_first_audio_ms": summary["request_to_first_audio_ms"],
            "voice_core_to_first_audio_ms": summary["core_result_to_first_audio_ms"],
            "voice_tts_first_chunk_ms": summary["tts_start_to_first_chunk_ms"],
            "voice_playback_start_ms": summary["first_chunk_to_playback_start_ms"],
            "voice_prewarm_used": True,
            "voice_streaming_fallback_used": False,
            "voice_partial_playback": False,
        },
        stage_timings_ms=breakdown.stage_timings_ms,
        request_id="voice-request",
        session_id="s",
        surface_mode="voice",
        route_family="voice_control",
        subsystem="voice",
        voice_involved=True,
    )
    payload = trace.to_summary_dict()

    assert summary["streaming_enabled"] is True
    assert summary["first_audio_available"] is True
    assert summary["user_heard_claimed"] is False
    assert payload["voice_streaming_tts_enabled"] is True
    assert payload["voice_live_format"] == "pcm"
    assert payload["voice_first_audio_ms"] == summary["request_to_first_audio_ms"]
