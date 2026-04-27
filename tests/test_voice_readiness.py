from __future__ import annotations

from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.voice.service import build_voice_subsystem


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
        max_output_tokens=2048,
        planner_max_output_tokens=1024,
        reasoning_max_output_tokens=2048,
        instructions="test",
    )


def _voice_config(**overrides: Any) -> VoiceConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "mode": "manual",
        "manual_input_enabled": True,
        "spoken_responses_enabled": True,
        "debug_mock_provider": False,
        "openai": VoiceOpenAIConfig(max_audio_bytes=1024, max_audio_seconds=10),
        "capture": VoiceCaptureConfig(enabled=False, provider="local"),
        "playback": VoicePlaybackConfig(enabled=False, provider="local"),
    }
    values.update(overrides)
    return VoiceConfig(**values)


class _UnavailableCaptureProvider:
    name = "local"
    is_mock = False

    def get_availability(self) -> dict[str, Any]:
        return {
            "provider": "local",
            "available": False,
            "unavailable_reason": "dependency_missing",
            "dependency_available": False,
            "device_available": None,
        }


class _ReadyCaptureProvider:
    name = "local"
    is_mock = False

    def get_availability(self) -> dict[str, Any]:
        return {
            "provider": "local",
            "available": True,
            "dependency_available": True,
            "device_available": True,
        }


def test_voice_readiness_reports_disabled_state_with_truth_flags() -> None:
    service = build_voice_subsystem(
        VoiceConfig(enabled=False),
        _openai_config(enabled=False, api_key=None),
    )

    readiness = service.readiness_report().to_dict()

    assert readiness["overall_status"] == "disabled"
    assert readiness["voice_enabled"] is False
    assert readiness["manual_transcript_ready"] is False
    assert "voice_disabled" in readiness["blocking_reasons"]
    assert readiness["next_setup_action"] == "Enable voice in configuration."
    assert readiness["truth_flags"]["no_wake_word"] is True
    assert readiness["truth_flags"]["no_vad"] is True
    assert readiness["truth_flags"]["no_realtime"] is True
    assert readiness["truth_flags"]["always_listening"] is False
    assert readiness["truth_flags"]["microphone_requires_explicit_start"] is True


def test_voice_readiness_reports_missing_openai_api_key_without_exposing_secret() -> (
    None
):
    service = build_voice_subsystem(
        _voice_config(),
        _openai_config(enabled=True, api_key=None),
    )

    snapshot = service.status_snapshot()
    readiness = snapshot["readiness"]

    assert readiness["overall_status"] == "misconfigured"
    assert readiness["openai_enabled"] is True
    assert readiness["api_key_present"] is False
    assert "api_key_missing" in readiness["blocking_reasons"]
    assert readiness["next_setup_action"] == "Configure an OpenAI API key."
    assert "test-key" not in str(readiness)
    assert "api_key" not in readiness["credential_status"].lower()


def test_voice_readiness_distinguishes_manual_only_and_disabled_capture() -> None:
    service = build_voice_subsystem(
        _voice_config(
            capture=VoiceCaptureConfig(enabled=False, provider="local"),
            playback=VoicePlaybackConfig(enabled=False, provider="local"),
        ),
        _openai_config(),
    )

    readiness = service.readiness_report().to_dict()

    assert readiness["overall_status"] == "degraded"
    assert readiness["manual_transcript_ready"] is True
    assert readiness["stt_ready"] is True
    assert readiness["tts_ready"] is True
    assert readiness["capture_ready"] is False
    assert readiness["local_capture_ready"] is False
    assert readiness["playback_ready"] is False
    assert "capture_disabled" in readiness["warnings"]
    assert "playback_disabled" in readiness["warnings"]
    assert readiness["next_setup_action"] == "Enable capture for push-to-talk."


def test_voice_readiness_reports_local_capture_dependency_missing() -> None:
    service = build_voice_subsystem(
        _voice_config(capture=VoiceCaptureConfig(enabled=True, provider="local")),
        _openai_config(),
    )
    service.capture_provider = _UnavailableCaptureProvider()  # type: ignore[assignment]

    readiness = service.readiness_report().to_dict()

    assert readiness["overall_status"] == "degraded"
    assert readiness["capture_ready"] is False
    assert readiness["local_capture_ready"] is False
    assert "capture_dependency_missing" in readiness["blocking_reasons"]
    assert (
        readiness["next_setup_action"] == "Install or enable the local capture backend."
    )


def test_voice_readiness_reports_push_to_talk_ready_with_fake_local_backend() -> None:
    service = build_voice_subsystem(
        _voice_config(
            capture=VoiceCaptureConfig(enabled=True, provider="local"),
            playback=VoicePlaybackConfig(enabled=True, provider="mock"),
        ),
        _openai_config(),
    )
    service.capture_provider = _ReadyCaptureProvider()  # type: ignore[assignment]

    readiness = service.readiness_report().to_dict()

    assert readiness["overall_status"] in {"ready", "degraded"}
    assert readiness["capture_ready"] is True
    assert readiness["local_capture_ready"] is True
    assert readiness["manual_transcript_ready"] is True
    assert readiness["stt_ready"] is True
    assert readiness["tts_ready"] is True
    assert readiness["blocking_reasons"] == []
    assert readiness["user_facing_reason"] == "Push-to-talk ready."
