from __future__ import annotations

import asyncio
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge


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


def _voice_config(**overrides: Any) -> VoiceConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "mode": "manual",
        "manual_input_enabled": True,
        "spoken_responses_enabled": True,
        "debug_mock_provider": True,
        "openai": VoiceOpenAIConfig(max_tts_chars=240),
    }
    values.update(overrides)
    return VoiceConfig(**values)


def test_synthesize_turn_response_uses_existing_spoken_candidate_without_rerouting() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")
    bridge = RecordingCoreBridge(route_family="clock", subsystem="tools", spoken_summary="The time is 10:15.")
    service.attach_core_bridge(bridge)
    turn_result = asyncio.run(service.submit_manual_voice_turn("what time is it?", session_id="voice-session"))

    synthesis = asyncio.run(service.synthesize_turn_response(turn_result, session_id="voice-session"))

    assert synthesis.ok is True
    assert synthesis.status == "succeeded"
    assert synthesis.speech_request is not None
    assert synthesis.speech_request.text == "The time is 10:15."
    assert synthesis.speech_request.turn_id == turn_result.turn.turn_id
    assert synthesis.speech_request.session_id == "voice-session"
    assert synthesis.audio_output is not None
    assert synthesis.audio_output.size_bytes == len(b"voice bytes")
    assert synthesis.playable is False
    assert synthesis.persisted is False
    assert len(bridge.calls) == 1
    assert turn_result.core_result.result_state == "completed"


def test_synthesize_turn_response_blocks_when_spoken_response_is_not_allowed() -> None:
    service = build_voice_subsystem(
        _voice_config(spoken_responses_enabled=False),
        _openai_config(),
    )
    service.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")
    service.attach_core_bridge(RecordingCoreBridge(spoken_summary="Bearing acquired."))
    turn_result = asyncio.run(service.submit_manual_voice_turn("what time is it?", session_id="voice-session"))

    synthesis = asyncio.run(service.synthesize_turn_response(turn_result, session_id="voice-session"))

    assert synthesis.ok is False
    assert synthesis.status == "blocked"
    assert synthesis.error_code == "spoken_response_not_allowed"
    assert synthesis.audio_output is None
    assert service.provider.tts_call_count == 0


def test_synthesize_speech_text_blocks_empty_long_and_raw_debug_text() -> None:
    service = build_voice_subsystem(_voice_config(openai=VoiceOpenAIConfig(max_tts_chars=32)), _openai_config())
    service.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")

    empty = asyncio.run(service.synthesize_speech_text("  ", source="manual_test", session_id="voice-session"))
    long = asyncio.run(service.synthesize_speech_text("x" * 80, source="manual_test", session_id="voice-session"))
    raw = asyncio.run(service.synthesize_speech_text("```python\nprint('debug')\n```", source="manual_test", session_id="voice-session"))

    assert empty.error_code == "empty_speech_text"
    assert long.error_code == "text_too_long"
    assert raw.error_code == "unsafe_speech_text"
    assert service.provider.tts_call_count == 0


def test_synthesize_speech_text_blocks_when_voice_or_openai_unavailable_without_mock_override() -> None:
    disabled = build_voice_subsystem(VoiceConfig(enabled=False, spoken_responses_enabled=True), _openai_config())
    disabled.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")
    unavailable = build_voice_subsystem(
        _voice_config(debug_mock_provider=False),
        _openai_config(enabled=False, api_key=None),
    )
    unavailable.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")

    disabled_result = asyncio.run(disabled.synthesize_speech_text("Bearing acquired.", source="manual_test"))
    unavailable_result = asyncio.run(unavailable.synthesize_speech_text("Bearing acquired.", source="manual_test"))

    assert disabled_result.error_code == "voice_disabled"
    assert unavailable_result.error_code == "openai_disabled"
    assert disabled.provider.tts_call_count == 0
    assert unavailable.provider.tts_call_count == 0


def test_requires_confirmation_and_blocked_wording_are_preserved_for_synthesis() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")
    service.attach_core_bridge(
        RecordingCoreBridge(
            result_state="requires_confirmation",
            route_family="software_control",
            subsystem="software_control",
            spoken_summary="Confirmation is required before Stormhelm can act.",
        )
    )
    turn_result = asyncio.run(service.submit_manual_voice_turn("install minecraft", session_id="voice-session"))

    synthesis = asyncio.run(service.synthesize_turn_response(turn_result, session_id="voice-session"))

    assert synthesis.ok is True
    assert synthesis.speech_request is not None
    assert "confirmation" in synthesis.speech_request.text.lower()
    assert "done" not in synthesis.speech_request.text.lower()
    assert "all set" not in synthesis.speech_request.text.lower()
    assert "that worked" not in synthesis.speech_request.text.lower()
