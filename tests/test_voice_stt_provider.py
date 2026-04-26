from __future__ import annotations

import asyncio

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.core.voice.models import VoiceAudioInput
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


def test_voice_audio_input_keeps_raw_audio_out_of_metadata() -> None:
    audio = VoiceAudioInput.from_bytes(
        b"fake wav bytes",
        filename="sample.wav",
        mime_type="audio/wav",
        duration_ms=900,
        metadata={"fixture": "unit"},
    )

    metadata = audio.to_metadata()

    assert audio.source == "bytes"
    assert audio.size_bytes == len(b"fake wav bytes")
    assert metadata["filename"] == "sample.wav"
    assert metadata["duration_ms"] == 900
    assert metadata["transient"] is True
    assert "data" not in metadata
    assert "raw_audio" not in metadata
    assert "file_path" not in metadata


def test_mock_stt_provider_returns_configured_transcript_and_metadata() -> None:
    provider = MockVoiceProvider(stt_transcript="open downloads", stt_confidence=0.82)
    audio = VoiceAudioInput.from_bytes(b"fake wav bytes", filename="turn.wav", mime_type="audio/wav")

    result = provider.transcribe_audio(audio)

    assert result.ok is True
    assert result.provider == "mock"
    assert result.model == "mock-stt"
    assert result.source == "mock_stt"
    assert result.transcript == "open downloads"
    assert result.confidence == 0.82
    assert result.usable_for_core_turn is True
    assert result.error_code is None


def test_mock_stt_provider_preserves_empty_error_timeout_and_uncertainty() -> None:
    audio = VoiceAudioInput.from_bytes(b"fake wav bytes", filename="turn.wav", mime_type="audio/wav")

    empty = MockVoiceProvider(stt_transcript="  ").transcribe_audio(audio)
    timeout = MockVoiceProvider(stt_timeout=True).transcribe_audio(audio)
    uncertain = MockVoiceProvider(stt_transcript="open downloads", stt_uncertain=True).transcribe_audio(audio)

    assert empty.ok is False
    assert empty.error_code == "empty_transcript"
    assert empty.usable_for_core_turn is False
    assert timeout.ok is False
    assert timeout.error_code == "provider_timeout"
    assert uncertain.ok is True
    assert uncertain.transcription_uncertain is True
    assert uncertain.usable_for_core_turn is True


def test_openai_stt_provider_uses_configured_model_without_network_until_called() -> None:
    provider = OpenAIVoiceProvider(
        config=VoiceConfig(
            enabled=True,
            mode="manual",
            debug_mock_provider=False,
            openai=VoiceOpenAIConfig(stt_model="gpt-4o-transcribe", transcription_language="en"),
        ),
        openai_config=_openai_config(),
    )

    assert provider.name == "openai"
    assert provider.is_mock is False
    assert provider.network_call_count == 0
    assert provider.stt_model == "gpt-4o-transcribe"


def test_openai_stt_provider_posts_to_audio_transcriptions_with_sanitized_result() -> None:
    requests: list[dict[str, object]] = []

    async def fake_post(*, url: str, headers: dict[str, str], data: dict[str, str], files: dict[str, tuple[str, bytes, str]], timeout: float):
        requests.append({"url": url, "headers": headers, "data": data, "files": files, "timeout": timeout})
        return {"text": "what time is it?", "language": "en", "duration": 1.1}

    provider = OpenAIVoiceProvider(
        config=VoiceConfig(
            enabled=True,
            mode="manual",
            debug_mock_provider=False,
            openai=VoiceOpenAIConfig(
                stt_model="gpt-4o-mini-transcribe",
                transcription_language="en",
                transcription_prompt="Stormhelm command vocabulary.",
                timeout_seconds=12,
            ),
        ),
        openai_config=_openai_config(),
        post_transcription=fake_post,
    )
    audio = VoiceAudioInput.from_bytes(b"fake wav bytes", filename="turn.wav", mime_type="audio/wav")

    result = asyncio.run(provider.transcribe_audio(audio))

    assert result.ok is True
    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini-transcribe"
    assert result.source == "openai_stt"
    assert result.transcript == "what time is it?"
    assert result.language == "en"
    assert result.raw_provider_metadata["response_keys"] == ["duration", "language", "text"]
    assert provider.network_call_count == 1
    assert requests[0]["url"] == "https://api.openai.com/v1/audio/transcriptions"
    assert requests[0]["data"] == {
        "model": "gpt-4o-mini-transcribe",
        "response_format": "json",
        "language": "en",
        "prompt": "Stormhelm command vocabulary.",
    }
    assert requests[0]["files"] == {"file": ("turn.wav", b"fake wav bytes", "audio/wav")}
