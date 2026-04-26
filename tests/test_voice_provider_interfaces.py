from __future__ import annotations

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.core.voice.providers import AudioInputProvider
from stormhelm.core.voice.providers import AudioOutputProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.providers import OpenAIVoiceProviderStub
from stormhelm.core.voice.providers import RealtimeVoiceProvider
from stormhelm.core.voice.providers import SpeechToTextProvider
from stormhelm.core.voice.providers import TextToSpeechProvider
from stormhelm.core.voice.providers import VoiceProvider
from stormhelm.core.voice.providers import WakeWordProvider


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


def test_mock_voice_provider_satisfies_all_voice_interfaces() -> None:
    provider = MockVoiceProvider()

    assert isinstance(provider, VoiceProvider)
    assert isinstance(provider, SpeechToTextProvider)
    assert isinstance(provider, TextToSpeechProvider)
    assert isinstance(provider, RealtimeVoiceProvider)
    assert isinstance(provider, WakeWordProvider)
    assert isinstance(provider, AudioInputProvider)
    assert isinstance(provider, AudioOutputProvider)
    assert provider.is_mock is True
    assert provider.get_availability().mock_provider_active is True


def test_mock_voice_provider_reports_mock_operations_without_real_audio() -> None:
    provider = MockVoiceProvider()

    session = provider.create_session()
    transcript = provider.transcribe_audio(b"")
    speech = provider.synthesize_speech("Bearing acquired.")

    assert session.ok is True
    assert session.status == "mock"
    assert transcript.status == "mock"
    assert transcript.payload["transcript"] == ""
    assert speech.status == "mock"
    assert speech.payload["audio_playback_started"] is False


def test_openai_voice_provider_stub_never_makes_network_calls_in_voice0() -> None:
    provider = OpenAIVoiceProviderStub(config=VoiceConfig(enabled=True, mode="manual"), openai_config=_openai_config())

    result = provider.transcribe_audio(b"fake-audio")
    tts = provider.synthesize_speech("Short response.")
    realtime = provider.create_session()

    assert result.ok is False
    assert result.status == "not_implemented"
    assert result.error_code == "not_implemented"
    assert tts.status == "not_implemented"
    assert realtime.status == "not_implemented"
    assert provider.network_call_count == 0
