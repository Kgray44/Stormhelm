from __future__ import annotations

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.core.container import build_container
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_core_container import FakeOperationalProbe


def _openai_config(*, enabled: bool = False, api_key: str | None = None) -> OpenAIConfig:
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


def test_voice_status_snapshot_reports_disabled_unavailable_and_mock_truthfully() -> None:
    service = build_voice_subsystem(
        config=VoiceConfig(enabled=False, debug_mock_provider=True),
        openai_config=_openai_config(enabled=False),
    )

    snapshot = service.status_snapshot()

    assert snapshot["phase"] == "voice0"
    assert snapshot["enabled"] is False
    assert snapshot["openai"]["enabled"] is False
    assert snapshot["provider"]["name"] == "openai"
    assert snapshot["provider"]["availability"]["available"] is False
    assert snapshot["provider"]["availability"]["unavailable_reason"] == "voice_disabled"
    assert snapshot["state"]["state"] == "disabled"
    assert snapshot["mock_provider_active"] is True
    assert snapshot["realtime_enabled"] is False
    assert snapshot["wake_enabled"] is False
    assert snapshot["spoken_responses_enabled"] is False
    assert snapshot["last_error"]["code"] is None
    assert snapshot["last_event"] is None


def test_voice_status_snapshot_reports_available_openai_configuration_without_claiming_audio_runtime() -> None:
    service = build_voice_subsystem(
        config=VoiceConfig(
            enabled=True,
            mode="manual",
            spoken_responses_enabled=True,
            wake_word_enabled=True,
            realtime_enabled=True,
        ),
        openai_config=_openai_config(enabled=True, api_key="test-key"),
    )

    snapshot = service.status_snapshot()

    assert snapshot["enabled"] is True
    assert snapshot["openai"]["configured"] is True
    assert snapshot["provider"]["availability"]["available"] is True
    assert snapshot["state"]["state"] == "dormant"
    assert snapshot["capabilities"]["real_microphone_capture"] is False
    assert snapshot["capabilities"]["openai_stt_provider"] is True
    assert snapshot["capabilities"]["controlled_audio_transcription"] is True
    assert snapshot["runtime_truth"]["no_microphone_capture"] is True
    assert snapshot["runtime_truth"]["no_live_stt"] is True
    assert snapshot["capabilities"]["openai_tts_provider"] is True
    assert snapshot["capabilities"]["controlled_tts_synthesis"] is True
    assert snapshot["capabilities"]["real_openai_tts"] is True
    assert snapshot["runtime_truth"]["controlled_tts_audio_artifacts_only"] is True
    assert snapshot["runtime_truth"]["no_audio_playback"] is True
    assert snapshot["capabilities"]["openai_realtime_sessions"] is False


def test_core_container_status_snapshot_includes_voice_surface(temp_config) -> None:
    container = build_container(temp_config)
    container.system_probe = FakeOperationalProbe()  # type: ignore[assignment]

    snapshot = container.status_snapshot()

    assert "voice" in snapshot
    assert snapshot["voice"]["phase"] == "voice0"
    assert snapshot["voice"]["provider"]["availability"]["unavailable_reason"] == "voice_disabled"
    assert snapshot["voice"]["state"]["core_bridge_required"] is True
