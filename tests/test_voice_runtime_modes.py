from __future__ import annotations

from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.config.models import VoicePostWakeConfig
from stormhelm.config.models import VoiceRealtimeConfig
from stormhelm.config.models import VoiceVADConfig
from stormhelm.config.models import VoiceWakeConfig
from stormhelm.core.voice.service import build_voice_subsystem
from stormhelm.ui.voice_surface import build_voice_ui_state


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
        "mode": "output_only",
        "manual_input_enabled": True,
        "spoken_responses_enabled": True,
        "debug_mock_provider": False,
        "openai": VoiceOpenAIConfig(
            max_audio_bytes=1024,
            max_audio_seconds=10,
            persist_tts_outputs=True,
        ),
        "playback": VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            allow_dev_playback=True,
        ),
        "capture": VoiceCaptureConfig(enabled=False, provider="local"),
        "wake": VoiceWakeConfig(enabled=False),
        "post_wake": VoicePostWakeConfig(enabled=False),
        "vad": VoiceVADConfig(enabled=False),
        "realtime": VoiceRealtimeConfig(enabled=False),
    }
    values.update(overrides)
    return VoiceConfig(**values)


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


def test_output_only_runtime_mode_ready_requires_tts_and_live_playback() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())

    report = service.runtime_mode_readiness_report().to_dict()

    assert report["selected_mode"] == "output_only"
    assert report["effective_mode"] == "output_only"
    assert report["status"] == "ready"
    assert report["live_playback_available"] is True
    assert report["artifact_persistence_enabled"] is True
    assert report["artifact_persistence_counts_as_live_playback"] is False
    assert report["missing_requirements"] == []
    assert report["required_subcomponents"] == [
        "voice",
        "openai_tts",
        "spoken_responses",
        "live_playback",
    ]
    assert report["expected_subsystem_posture"]["capture"] == "disabled"
    assert report["expected_subsystem_posture"]["wake"] == "disabled"
    assert report["expected_subsystem_posture"]["vad"] == "disabled"
    assert report["expected_subsystem_posture"]["realtime"] == "disabled"
    assert report["provider_availability"]["playback"]["available"] is True
    assert report["truth_flags"]["command_authority"] == "stormhelm_core"


def test_output_only_runtime_mode_blocks_when_playback_disabled() -> None:
    service = build_voice_subsystem(
        _voice_config(playback=VoicePlaybackConfig(enabled=False, provider="local")),
        _openai_config(),
    )

    report = service.runtime_mode_readiness_report().to_dict()
    readiness = service.readiness_report().to_dict()

    assert report["status"] == "blocked"
    assert "output_voice_configured_but_playback_disabled" in report["blocking_reasons"]
    assert "live_playback" in report["missing_requirements"]
    assert report["live_playback_available"] is False
    assert report["next_fix"] == "Enable voice.playback.enabled for output-only live speech."
    assert "output_voice_configured_but_playback_disabled" in readiness["blocking_reasons"]
    assert readiness["overall_status"] == "misconfigured"


def test_output_only_runtime_mode_blocks_when_playback_provider_unavailable() -> None:
    service = build_voice_subsystem(
        _voice_config(
            playback=VoicePlaybackConfig(
                enabled=True,
                provider="mock",
                allow_dev_playback=True,
            )
        ),
        _openai_config(),
    )
    service.playback_provider.available = False  # type: ignore[attr-defined]

    report = service.runtime_mode_readiness_report().to_dict()

    assert report["status"] == "blocked"
    assert "output_voice_configured_but_playback_unavailable" in report["blocking_reasons"]
    assert report["provider_availability"]["playback"]["available"] is False
    assert report["provider_availability"]["playback"]["unavailable_reason"] == "provider_unavailable"
    assert report["next_fix"] == "Fix local playback availability for output-only live speech."


def test_output_only_runtime_mode_reports_contradictory_capture_wake_vad_realtime() -> None:
    service = build_voice_subsystem(
        _voice_config(
            capture=VoiceCaptureConfig(enabled=True, provider="local"),
            wake=VoiceWakeConfig(enabled=True, provider="mock", allow_dev_wake=True),
            post_wake=VoicePostWakeConfig(enabled=True, allow_dev_post_wake=True),
            vad=VoiceVADConfig(enabled=True, provider="mock", allow_dev_vad=True),
            realtime=VoiceRealtimeConfig(enabled=True, provider="mock"),
        ),
        _openai_config(),
    )

    report = service.runtime_mode_readiness_report().to_dict()

    assert report["status"] == "degraded"
    assert report["contradictory_settings"] == [
        "output_only_capture_should_be_disabled",
        "output_only_wake_should_be_disabled",
        "output_only_post_wake_should_be_disabled",
        "output_only_vad_should_be_disabled",
        "output_only_realtime_should_be_disabled",
    ]


def test_push_to_talk_runtime_mode_requires_capture_and_stt() -> None:
    service = build_voice_subsystem(
        _voice_config(
            mode="push_to_talk",
            capture=VoiceCaptureConfig(enabled=True, provider="local"),
        ),
        _openai_config(),
    )
    service.capture_provider = _ReadyCaptureProvider()  # type: ignore[assignment]

    report = service.runtime_mode_readiness_report().to_dict()

    assert report["status"] == "ready"
    assert report["selected_mode"] == "push_to_talk"
    assert "capture" in report["required_subcomponents"]
    assert "openai_stt" in report["required_subcomponents"]
    assert report["provider_availability"]["capture"]["available"] is True
    assert report["expected_subsystem_posture"]["wake"] == "disabled"


def test_realtime_speech_runtime_mode_blocks_direct_tools_enabled() -> None:
    service = build_voice_subsystem(
        _voice_config(
            mode="realtime_speech_core_bridge",
            realtime=VoiceRealtimeConfig(
                enabled=True,
                provider="mock",
                mode="speech_to_speech_core_bridge",
                allow_dev_realtime=True,
                direct_tools_allowed=True,
                core_bridge_required=True,
                speech_to_speech_enabled=True,
                audio_output_from_realtime=True,
            ),
        ),
        _openai_config(),
    )
    service.config.realtime.direct_tools_allowed = True

    report = service.runtime_mode_readiness_report().to_dict()

    assert report["status"] == "blocked"
    assert "realtime_direct_tools_forbidden" in report["blocking_reasons"]
    assert report["provider_availability"]["realtime"]["direct_tools_allowed"] is False
    assert report["truth_flags"]["direct_realtime_tools_allowed"] is False
    assert report["truth_flags"]["command_authority"] == "stormhelm_core"


def test_voice_status_and_ui_payload_include_runtime_mode_coherence() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())

    status = service.status_snapshot()
    payload = build_voice_ui_state({"voice": status})

    assert status["runtime_mode"]["effective_mode"] == "output_only"
    assert status["runtime_mode"]["status"] == "ready"
    assert payload["voice_runtime_mode"] == "output_only"
    assert payload["voice_effective_mode"] == "output_only"
    assert payload["voice_runtime_readiness"]["status"] == "ready"
    assert payload["live_playback_available"] is True
    assert payload["artifact_persistence_enabled"] is True
    assert any(
        section["title"] == "Runtime Mode" for section in payload["deck"]["sections"]
    )
    assert "Always listening" not in str(payload)
    assert "Direct tools active" not in str(payload)
