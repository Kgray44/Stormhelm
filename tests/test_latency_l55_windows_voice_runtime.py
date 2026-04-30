from __future__ import annotations

import asyncio
import json
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.voice.models import VoiceLivePlaybackRequest
from stormhelm.core.voice.providers import LocalPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem
from stormhelm.ui.voice_surface import build_voice_ui_state


class FakeWindowsSpeakerStreamBackend:
    dependency_name = "fake_winmm_waveout"

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.stream_feed_calls: list[dict[str, object]] = []

    def get_availability(self, config: VoiceConfig) -> dict[str, object]:
        return {
            "provider": "local",
            "backend": "winmm_waveout",
            "platform": "win32",
            "dependency": "winmm",
            "dependency_available": True,
            "device": config.playback.device,
            "device_available": self.available,
            "platform_supported": True,
            "available": self.available,
            "unavailable_reason": None if self.available else "device_unavailable",
        }

    def start_stream(self, *, request: VoiceLivePlaybackRequest) -> dict[str, object]:
        return {
            "status": "started",
            "backend": "winmm_waveout",
            "streaming_supported": True,
            "audible_playback": self.available,
            "user_heard_claimed": False,
        }

    def feed_stream_chunk(
        self,
        playback_stream_id: str,
        data: bytes,
        *,
        chunk_index: int | None = None,
    ) -> dict[str, object]:
        self.stream_feed_calls.append(
            {
                "playback_stream_id": playback_stream_id,
                "chunk_index": chunk_index,
                "size_bytes": len(data),
            }
        )
        return {
            "ok": True,
            "status": "playing",
            "playback_started": True,
            "audible_playback": True,
            "user_heard_claimed": True,
        }

    def complete_stream(self, playback_stream_id: str) -> dict[str, object]:
        return {
            "status": "completed",
            "audible_playback": True,
            "user_heard_claimed": True,
            "raw_audio_present": False,
        }

    def cancel_stream(
        self,
        playback_stream_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> dict[str, object]:
        return {
            "status": "cancelled",
            "audible_playback": True,
            "user_heard_claimed": True,
            "raw_audio_present": False,
            "cancel_reason": reason,
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


def _voice_config(*, playback_provider: str = "local") -> VoiceConfig:
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
            max_audio_bytes=512,
            max_audio_seconds=4,
        ),
        playback=VoicePlaybackConfig(
            enabled=True,
            provider=playback_provider,
            device="default",
            allow_dev_playback=True,
            streaming_enabled=True,
            max_audio_bytes=512,
        ),
    )


def _speaker_service(*, backend: FakeWindowsSpeakerStreamBackend | None = None) -> Any:
    voice_config = _voice_config()
    service = build_voice_subsystem(voice_config, _openai_config())
    service.provider = MockVoiceProvider(
        tts_audio_bytes=b"first-second-third-fourth",
        tts_stream_chunk_size=6,
    )
    service.playback_provider = LocalPlaybackProvider(
        config=voice_config,
        backend=backend or FakeWindowsSpeakerStreamBackend(),
    )
    return service


def test_windows_speaker_streaming_truth_reaches_status_and_ui_surface() -> None:
    service = _speaker_service()
    service.remember_runtime_gate_snapshot(
        {
            "env_loaded": True,
            "openai_key_present": True,
            "openai_enabled": True,
            "voice_enabled": True,
            "spoken_responses_enabled": True,
            "playback_enabled": True,
            "playback_provider": "local",
            "raw_secret_logged": False,
        }
    )
    service.remember_assistant_speak_decision(
        {
            "session_id": "voice-session",
            "prompt_source": "typed_ui",
            "approved_spoken_text_present": True,
            "voice_service_called": True,
            "skipped_reason": None,
            "raw_secret_logged": False,
            "raw_audio_logged": False,
        }
    )

    result = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved this Windows speaker response.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-speaker",
            core_result_completed_ms=20,
            request_started_ms=0,
            metadata={"assistant_response_voice_output": True},
        )
    )
    status = service.status_snapshot()
    ui_state = build_voice_ui_state({"voice": status})
    serialized = json.dumps(status) + json.dumps(ui_state)

    assert result.playback_result is not None
    assert result.playback_result.user_heard_claimed is True
    assert status["playback"]["provider"] == "local"
    assert status["playback"]["speaker_backend_available"] is True
    assert status["playback"]["user_heard_claimed"] is True
    assert status["runtime_truth"]["user_heard_claimed"] is True
    assert status["runtime_gate_snapshot"]["env_loaded"] is True
    assert status["last_voice_speak_decision"]["prompt_source"] == "typed_ui"
    assert ui_state["playback_provider"] == "local"
    assert ui_state["speaker_backend_available"] is True
    assert ui_state["user_heard_claimed"] is True
    assert ui_state["voice_runtime_gate_snapshot"]["openai_key_present"] is True
    assert ui_state["last_voice_speak_decision"]["voice_service_called"] is True
    assert ui_state["voice_anchor_truth_flags"]["user_heard_claimed"] is True
    assert "first-second-third" not in serialized
    assert "raw_audio_present\": true" not in serialized.lower()


def test_windows_speaker_unavailable_degrades_without_user_heard_claim() -> None:
    service = _speaker_service(backend=FakeWindowsSpeakerStreamBackend(available=False))

    result = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved this response but speaker output is unavailable.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-unavailable-speaker",
        )
    )
    status = service.status_snapshot()
    ui_state = build_voice_ui_state({"voice": status})

    assert result.ok is False
    assert result.playback_result is not None
    assert result.playback_result.status == "unavailable"
    assert result.playback_result.user_heard_claimed is False
    assert status["playback"]["available"] is False
    assert status["playback"]["speaker_backend_available"] is False
    assert status["playback"]["user_heard_claimed"] is False
    assert status["playback"]["unavailable_reason"] == "device_unavailable"
    assert ui_state["speaker_backend_available"] is False
    assert ui_state["user_heard_claimed"] is False


def test_voice_doctor_reads_local_env_without_leaking_secret(temp_project_root) -> None:
    env_file = temp_project_root / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=present-test-value",
                "STORMHELM_OPENAI_ENABLED=1",
                "STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE=1",
                "STORMHELM_VOICE_ENABLED=1",
                "STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED=1",
                "STORMHELM_VOICE_DEBUG_MOCK_PROVIDER=false",
                "STORMHELM_VOICE_OPENAI_STREAM_TTS_OUTPUTS=true",
                "STORMHELM_VOICE_OPENAI_TTS_LIVE_FORMAT=pcm",
                "STORMHELM_VOICE_PLAYBACK_ENABLED=true",
                "STORMHELM_VOICE_PLAYBACK_PROVIDER=local",
                "STORMHELM_VOICE_PLAYBACK_ALLOW_DEV_PLAYBACK=true",
                "STORMHELM_VOICE_PLAYBACK_STREAMING_ENABLED=true",
            ]
        ),
        encoding="utf-8",
    )

    from scripts.voice_doctor import build_voice_doctor_report

    report = build_voice_doctor_report(project_root=temp_project_root)
    serialized = json.dumps(report, sort_keys=True)

    assert report["env_loaded"] is True
    assert report["OPENAI_API_KEY"] == "present"
    assert report["STORMHELM_OPENAI_ENABLED"] == "enabled"
    assert report["STORMHELM_RUN_LIVE_OPENAI_VOICE_SMOKE"] == "enabled"
    assert report["STORMHELM_VOICE_ENABLED"] == "enabled"
    assert report["STORMHELM_VOICE_SPOKEN_RESPONSES_ENABLED"] == "enabled"
    assert report["STORMHELM_VOICE_PLAYBACK_PROVIDER"] == "local"
    assert report["live_smoke_gate"] == "enabled"
    assert report["ordinary_runtime_requires_live_smoke_gate"] is False
    assert report["raw_secret_logged"] is False
    assert report["raw_audio_logged"] is False
    assert report["env_tracked_by_git"] is False
    assert "present-test-value" not in serialized
