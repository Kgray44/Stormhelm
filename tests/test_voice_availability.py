from __future__ import annotations

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.core.voice.availability import compute_voice_availability


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


def test_voice_availability_is_false_when_voice_disabled() -> None:
    availability = compute_voice_availability(VoiceConfig(enabled=False), _openai_config())

    assert availability.available is False
    assert availability.enabled_requested is False
    assert availability.unavailable_reason == "voice_disabled"
    assert availability.stt_allowed is False
    assert availability.tts_allowed is False
    assert availability.wake_allowed is False
    assert availability.realtime_allowed is False


def test_voice_availability_is_false_when_openai_disabled() -> None:
    availability = compute_voice_availability(
        VoiceConfig(enabled=True, mode="manual"),
        _openai_config(enabled=False),
    )

    assert availability.available is False
    assert availability.openai_enabled is False
    assert availability.unavailable_reason == "openai_disabled"
    assert availability.stt_allowed is False
    assert availability.tts_allowed is False
    assert availability.wake_allowed is False
    assert availability.realtime_allowed is False


def test_voice_availability_reports_missing_or_unsupported_provider() -> None:
    missing = compute_voice_availability(
        VoiceConfig(enabled=True, provider="", mode="manual"),
        _openai_config(),
    )
    unsupported = compute_voice_availability(
        VoiceConfig(enabled=True, provider="local_tts", mode="manual"),
        _openai_config(),
    )

    assert missing.available is False
    assert missing.unavailable_reason == "provider_missing"
    assert unsupported.available is False
    assert unsupported.unavailable_reason == "unsupported_provider"
    assert unsupported.provider_name == "local_tts"


def test_voice_availability_requires_openai_api_key_and_models() -> None:
    missing_key = compute_voice_availability(
        VoiceConfig(enabled=True, mode="manual"),
        _openai_config(api_key=None),
    )
    blank_model = compute_voice_availability(
        VoiceConfig(enabled=True, mode="manual", openai=VoiceOpenAIConfig(stt_model="")),
        _openai_config(),
    )

    assert missing_key.available is False
    assert missing_key.provider_configured is False
    assert missing_key.unavailable_reason == "api_key_missing"
    assert blank_model.available is False
    assert blank_model.provider_configured is False
    assert blank_model.unavailable_reason == "provider_not_configured"


def test_voice_availability_is_true_only_for_enabled_openai_provider() -> None:
    availability = compute_voice_availability(
        VoiceConfig(
            enabled=True,
            provider="openai",
            mode="manual",
            wake_word_enabled=True,
            spoken_responses_enabled=True,
            realtime_enabled=True,
            debug_mock_provider=True,
        ),
        _openai_config(),
    )

    assert availability.available is True
    assert availability.unavailable_reason is None
    assert availability.provider_configured is True
    assert availability.provider_name == "openai"
    assert availability.realtime_allowed is True
    assert availability.stt_allowed is True
    assert availability.tts_allowed is True
    assert availability.wake_allowed is True
    assert availability.mock_provider_active is True
