from __future__ import annotations

import asyncio

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.core.voice.models import VoiceSpeechRequest
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.providers import OpenAIVoiceProvider


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


def _speech_request(text: str = "Bearing acquired.") -> VoiceSpeechRequest:
    return VoiceSpeechRequest(
        source="core_spoken_summary",
        text=text,
        persona_mode="ghost",
        speech_length_hint="short",
        provider="mock",
        model="mock-tts",
        voice="mock-voice",
        format="mp3",
        allowed_to_synthesize=True,
        session_id="voice-session",
        turn_id="voice-turn-1",
    )


def test_voice_speech_request_metadata_is_bounded_and_traceable() -> None:
    request = _speech_request()
    metadata = request.to_metadata()

    assert request.speech_request_id.startswith("voice-speech-")
    assert request.text_hash
    assert metadata["text_preview"] == "Bearing acquired."
    assert metadata["text_hash"] == request.text_hash
    assert "text" not in metadata
    assert metadata["allowed_to_synthesize"] is True


def test_mock_tts_provider_returns_fake_audio_output_without_playback() -> None:
    provider = MockVoiceProvider(tts_audio_bytes=b"fake mp3 bytes")
    request = _speech_request()

    result = provider.synthesize_speech(request)

    assert result.ok is True
    assert result.status == "succeeded"
    assert result.provider == "mock"
    assert result.model == "mock-tts"
    assert result.voice == "mock-voice"
    assert result.format == "mp3"
    assert result.audio_output is not None
    assert result.audio_output.size_bytes == len(b"fake mp3 bytes")
    assert result.audio_output.transient is True
    assert result.playable is False
    assert result.persisted is False
    assert result.to_dict()["audio_output"]["size_bytes"] == len(b"fake mp3 bytes")
    assert "fake mp3 bytes" not in str(result.to_dict())


def test_mock_tts_provider_preserves_error_timeout_and_unsupported_voice() -> None:
    request = _speech_request()

    timeout = MockVoiceProvider(tts_timeout=True).synthesize_speech(request)
    error = MockVoiceProvider(tts_error_code="provider_unavailable", tts_error_message="provider offline").synthesize_speech(request)
    unsupported = MockVoiceProvider(tts_unsupported_voice=True).synthesize_speech(request)

    assert timeout.ok is False
    assert timeout.error_code == "provider_timeout"
    assert error.ok is False
    assert error.error_code == "provider_unavailable"
    assert unsupported.ok is False
    assert unsupported.error_code == "unsupported_voice"


def test_openai_tts_provider_uses_configured_model_voice_and_format_without_network_until_called() -> None:
    provider = OpenAIVoiceProvider(
        config=VoiceConfig(
            enabled=True,
            mode="manual",
            spoken_responses_enabled=True,
            debug_mock_provider=False,
            openai=VoiceOpenAIConfig(tts_model="gpt-4o-mini-tts", tts_voice="cedar", tts_format="wav"),
        ),
        openai_config=_openai_config(),
    )

    assert provider.name == "openai"
    assert provider.is_mock is False
    assert provider.tts_model == "gpt-4o-mini-tts"
    assert provider.tts_voice == "cedar"
    assert provider.tts_format == "wav"
    assert provider.network_call_count == 0


def test_openai_tts_provider_posts_to_audio_speech_with_sanitized_result() -> None:
    requests: list[dict[str, object]] = []

    async def fake_post(*, url: str, headers: dict[str, str], json: dict[str, object], timeout: float):
        requests.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return b"fake openai audio"

    provider = OpenAIVoiceProvider(
        config=VoiceConfig(
            enabled=True,
            mode="manual",
            spoken_responses_enabled=True,
            debug_mock_provider=False,
            openai=VoiceOpenAIConfig(
                tts_model="gpt-4o-mini-tts",
                tts_voice="marin",
                tts_format="mp3",
                tts_speed=0.95,
                timeout_seconds=11,
            ),
        ),
        openai_config=_openai_config(),
        post_speech=fake_post,
    )
    request = VoiceSpeechRequest(
        source="core_spoken_summary",
        text="Core reports the request completed. Verification is not claimed here.",
        persona_mode="ghost",
        speech_length_hint="short",
        provider="openai",
        model="gpt-4o-mini-tts",
        voice="marin",
        format="mp3",
        allowed_to_synthesize=True,
    )

    result = asyncio.run(provider.synthesize_speech(request))

    assert result.ok is True
    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini-tts"
    assert result.voice == "marin"
    assert result.format == "mp3"
    assert result.audio_output is not None
    assert result.audio_output.size_bytes == len(b"fake openai audio")
    assert result.raw_provider_metadata["response_kind"] == "bytes"
    assert provider.network_call_count == 1
    assert requests[0]["url"] == "https://api.openai.com/v1/audio/speech"
    assert requests[0]["json"] == {
        "model": "gpt-4o-mini-tts",
        "input": "Core reports the request completed. Verification is not claimed here.",
        "voice": "marin",
        "response_format": "mp3",
        "speed": 0.95,
    }
    assert "fake openai audio" not in str(result.to_dict())
