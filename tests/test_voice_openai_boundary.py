from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.core.voice.models import VoiceAudioInput
from stormhelm.core.voice.models import VoiceSpeechRequest
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.providers import OpenAIVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge


REPO_ROOT = Path(__file__).resolve().parents[1]


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
        "manual_input_enabled": True,
        "spoken_responses_enabled": True,
        "debug_mock_provider": True,
        "openai": VoiceOpenAIConfig(max_audio_bytes=1024, max_audio_seconds=10),
    }
    values.update(overrides)
    return VoiceConfig(**values)


def _audio() -> VoiceAudioInput:
    return VoiceAudioInput.from_bytes(
        b"fake wav bytes",
        filename="voice-turn.wav",
        mime_type="audio/wav",
        duration_ms=1200,
    )


def test_openai_stt_provider_is_transcript_only_even_if_payload_mentions_routing() -> None:
    async def fake_post(
        *,
        url: str,
        headers: dict[str, str],
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
        timeout: float,
    ) -> dict[str, object]:
        del url, headers, data, files, timeout
        return {
            "text": "open downloads",
            "route_family": "software_control",
            "subsystem": "dangerous_action",
            "result_state": "completed",
            "approval_state": "approved",
            "tool": "delete_everything",
        }

    provider = OpenAIVoiceProvider(
        config=VoiceConfig(
            enabled=True,
            debug_mock_provider=False,
            openai=VoiceOpenAIConfig(stt_model="gpt-4o-mini-transcribe"),
        ),
        openai_config=_openai_config(),
        post_transcription=fake_post,
    )

    result = asyncio.run(provider.transcribe_audio(_audio()))
    payload = result.to_dict()

    assert result.ok is True
    assert result.transcript == "open downloads"
    assert result.source == "openai_stt"
    for forbidden in {
        "route_family",
        "subsystem",
        "result_state",
        "approval_state",
        "tool",
        "action",
    }:
        assert forbidden not in payload


def test_audio_voice_turn_routes_openai_transcript_through_core_bridge_only() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.provider = MockVoiceProvider(stt_transcript="open downloads")
    bridge = RecordingCoreBridge(
        route_family="desktop_search",
        subsystem="desktop_search",
        spoken_summary="Downloads is ready.",
    )
    service.attach_core_bridge(bridge)

    result = asyncio.run(
        service.submit_audio_voice_turn(_audio(), session_id="voice-session")
    )

    assert result.ok is True
    assert result.transcription_result is not None
    assert result.transcription_result.transcript == "open downloads"
    assert result.core_request is not None
    assert result.core_request.voice_mode == "stt"
    assert result.core_result is not None
    assert result.core_result.route_family == "desktop_search"
    assert bridge.calls[0]["message"] == "open downloads"
    assert bridge.calls[0]["input_context"]["voice"]["voice_mode"] == "stt"
    assert bridge.calls[0]["input_context"]["controlled_audio_transcript"] is True


def test_openai_tts_provider_speaks_exact_requested_text_without_rewriting() -> None:
    requests: list[dict[str, object]] = []

    async def fake_post(
        *,
        url: str,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
    ) -> bytes:
        del url, headers, timeout
        requests.append(json)
        return b"fake voice bytes"

    provider = OpenAIVoiceProvider(
        config=VoiceConfig(
            enabled=True,
            spoken_responses_enabled=True,
            debug_mock_provider=False,
            openai=VoiceOpenAIConfig(
                tts_model="gpt-4o-mini-tts",
                tts_voice="cedar",
                tts_format="mp3",
            ),
        ),
        openai_config=_openai_config(),
        post_speech=fake_post,
    )
    request = VoiceSpeechRequest(
        source="core_spoken_summary",
        text="Confirmation is required before Stormhelm can act.",
        persona_mode="ghost",
        speech_length_hint="short",
        provider="openai",
        model="gpt-4o-mini-tts",
        voice="cedar",
        format="mp3",
        result_state_source="requires_confirmation",
        allowed_to_synthesize=True,
    )

    result = asyncio.run(provider.synthesize_speech(request))

    assert result.ok is True
    assert requests[0]["input"] == request.text
    assert result.speech_request is not None
    assert result.speech_request.text_hash == request.text_hash
    assert "done" not in requests[0]["input"].lower()
    assert "verified" not in requests[0]["input"].lower()


def test_synthesize_turn_response_does_not_mutate_or_strengthen_core_result() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.provider = MockVoiceProvider(tts_audio_bytes=b"voice bytes")
    bridge = RecordingCoreBridge(
        result_state="requires_confirmation",
        route_family="software_control",
        subsystem="software_control",
        spoken_summary="Confirmation is required before Stormhelm can act.",
    )
    service.attach_core_bridge(bridge)
    turn_result = asyncio.run(
        service.submit_manual_voice_turn("install minecraft", session_id="voice-session")
    )
    before_core = turn_result.core_result.to_dict()

    synthesis = asyncio.run(
        service.synthesize_turn_response(turn_result, session_id="voice-session")
    )

    assert synthesis.ok is True
    assert turn_result.core_result.to_dict() == before_core
    assert synthesis.speech_request is not None
    assert synthesis.speech_request.text == "Confirmation is required before Stormhelm can act."
    assert "done" not in synthesis.speech_request.text.lower()
    assert "verified" not in synthesis.speech_request.text.lower()
    assert len(bridge.calls) == 1


def test_voice_status_exposes_openai_voice_boundary_law() -> None:
    service = build_voice_subsystem(_voice_config(), _openai_config())
    snapshot = service.status_snapshot()

    assert snapshot["runtime_truth"]["openai_voice_boundary_law"] == "stt_tts_only"
    assert snapshot["runtime_truth"]["openai_stt_transcript_provider_only"] is True
    assert snapshot["runtime_truth"]["openai_tts_speech_rendering_provider_only"] is True
    assert snapshot["truthfulness_contract"]["openai_voice_not_command_authority"] is True
    assert snapshot["truthfulness_contract"]["openai_realtime_requires_core_bridge"] is True
    assert snapshot["readiness"]["truth_flags"]["openai_voice_boundary_law"] == "stt_tts_only"
    assert snapshot["readiness"]["truth_flags"]["openai_voice_not_command_authority"] is True


def test_static_openai_voice_calls_stay_in_provider_boundary() -> None:
    voice_files = [
        path
        for path in (REPO_ROOT / "src" / "stormhelm" / "core" / "voice").rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    raw_endpoint_hits: list[Path] = []
    forbidden_hits: list[tuple[Path, str]] = []
    forbidden_tokens = [
        "/responses",
        "chat.completions",
        "client.responses",
        "responses.create",
        "OpenAIResponsesProvider",
        "openai_responses",
    ]
    for path in voice_files:
        text = path.read_text(encoding="utf-8")
        if "/audio/transcriptions" in text or "/audio/speech" in text:
            raw_endpoint_hits.append(path.relative_to(REPO_ROOT))
        for token in forbidden_tokens:
            if token in text:
                forbidden_hits.append((path.relative_to(REPO_ROOT), token))

    assert raw_endpoint_hits == [Path("src/stormhelm/core/voice/providers.py")]
    assert forbidden_hits == []


def test_bridge_and_ui_do_not_import_openai_clients_or_voice_providers_directly() -> None:
    checked = [
        REPO_ROOT / "src" / "stormhelm" / "ui" / "bridge.py",
        REPO_ROOT / "src" / "stormhelm" / "ui" / "client.py",
        REPO_ROOT / "src" / "stormhelm" / "ui" / "controllers" / "main_controller.py",
        REPO_ROOT / "src" / "stormhelm" / "ui" / "voice_surface.py",
        REPO_ROOT / "src" / "stormhelm" / "core" / "api" / "app.py",
    ]
    forbidden_tokens = [
        "OpenAIVoiceProvider",
        "httpx.AsyncClient",
        "/audio/transcriptions",
        "/audio/speech",
        "openai_responses",
        "OpenAIResponsesProvider",
    ]

    hits: list[tuple[Path, str]] = []
    for path in checked:
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                hits.append((path.relative_to(REPO_ROOT), token))

    assert hits == []
