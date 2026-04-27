from __future__ import annotations

from stormhelm.config.models import VoiceVADConfig
from stormhelm.core.voice.models import VoiceActivityEvent
from stormhelm.core.voice.models import VoiceVADSession
from stormhelm.core.voice.providers import MockVADProvider
from stormhelm.core.voice.providers import UnavailableVADProvider


def _vad_config(**overrides) -> VoiceVADConfig:
    values = {
        "enabled": True,
        "provider": "mock",
        "allow_dev_vad": True,
        "silence_ms": 900,
    }
    values.update(overrides)
    return VoiceVADConfig(**values)


def test_mock_vad_provider_reports_mock_status_without_openai_or_audio() -> None:
    provider = MockVADProvider(config=_vad_config())
    availability = provider.get_availability()

    assert availability["available"] is True
    assert availability["provider"] == "mock"
    assert availability["provider_kind"] == "mock"
    assert availability["mock_provider_active"] is True
    assert availability["openai_used"] is False
    assert availability["raw_audio_present"] is False
    assert availability["semantic_completion_claimed"] is False
    assert availability["command_authority"] is False
    assert availability["realtime_vad"] is False


def test_mock_vad_session_and_activity_events_are_audio_only() -> None:
    provider = MockVADProvider(config=_vad_config())

    session = provider.start_detection(
        capture_id="capture-1", session_id="voice-session"
    )
    started = provider.simulate_speech_started(confidence=0.82)
    stopped = provider.simulate_speech_stopped(confidence=0.44, duration_ms=810)

    assert isinstance(session, VoiceVADSession)
    assert session.status == "active"
    assert session.capture_id == "capture-1"
    assert isinstance(started, VoiceActivityEvent)
    assert started.status == "speech_started"
    assert started.capture_id == "capture-1"
    assert stopped.status == "speech_stopped"
    assert stopped.semantic_completion_claimed is False
    assert stopped.command_intent_claimed is False
    assert stopped.core_routed is False
    assert stopped.raw_audio_present is False


def test_unavailable_vad_provider_reports_typed_reason() -> None:
    provider = UnavailableVADProvider(
        config=_vad_config(provider="local"),
        unavailable_reason="dependency_missing",
    )

    availability = provider.get_availability()
    session = provider.start_detection(capture_id="capture-1")

    assert availability["available"] is False
    assert availability["provider_kind"] == "unavailable"
    assert availability["unavailable_reason"] == "dependency_missing"
    assert session.status == "failed"
    assert session.error_code == "dependency_missing"
