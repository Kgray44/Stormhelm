from __future__ import annotations

import asyncio
from typing import Any

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceCaptureConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceWakeConfig
from stormhelm.core.api.app import create_app
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.models import VoiceWakeEvent
from stormhelm.core.voice.models import VoiceWakeSession
from stormhelm.core.voice.providers import MockWakeWordProvider
from stormhelm.core.voice.providers import UnavailableWakeWordProvider
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge


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


def _voice_config(**wake_overrides: Any) -> VoiceConfig:
    wake_values = {
        "enabled": True,
        "provider": "mock",
        "wake_phrase": "Stormhelm",
        "confidence_threshold": 0.75,
        "cooldown_ms": 2500,
        "max_wake_session_ms": 15000,
        "false_positive_window_ms": 3000,
        "allow_dev_wake": True,
    }
    wake_values.update(wake_overrides)
    return VoiceConfig(
        enabled=True,
        mode="manual",
        debug_mock_provider=True,
        capture=VoiceCaptureConfig(provider="mock", allow_dev_capture=True),
        wake=VoiceWakeConfig(**wake_values),
    )


def test_mock_wake_provider_reports_mock_status_without_real_audio_or_openai() -> None:
    provider = MockWakeWordProvider(config=_voice_config().wake)
    availability = provider.get_availability()

    assert availability["available"] is True
    assert availability["provider"] == "mock"
    assert availability["provider_kind"] == "mock"
    assert availability["mock_provider_active"] is True
    assert availability["real_microphone_monitoring"] is False
    assert availability["openai_used"] is False
    assert availability["raw_audio_present"] is False

    event = provider.simulate_wake(session_id="voice-session", confidence=0.91)

    assert isinstance(event, VoiceWakeEvent)
    assert event.provider == "mock"
    assert event.provider_kind == "mock"
    assert event.wake_phrase == "Stormhelm"
    assert event.confidence == 0.91
    assert event.raw_audio_present is False
    assert event.openai_used is False


def test_unavailable_wake_provider_reports_typed_reason() -> None:
    provider = UnavailableWakeWordProvider(
        config=_voice_config(provider="local").wake,
        unavailable_reason="real_wake_not_implemented",
    )

    availability = provider.get_availability()
    result = provider.start_wake_monitoring()

    assert availability["available"] is False
    assert availability["provider_kind"] == "unavailable"
    assert availability["unavailable_reason"] == "real_wake_not_implemented"
    assert result.ok is False
    assert result.error_code == "real_wake_not_implemented"


def test_wake_readiness_distinguishes_disabled_available_and_monitoring() -> None:
    disabled = build_voice_subsystem(
        _voice_config(enabled=False),
        _openai_config(),
    )
    disabled_report = disabled.wake_readiness_report().to_dict()

    assert disabled_report["wake_enabled"] is False
    assert disabled_report["wake_available"] is False
    assert disabled_report["wake_monitoring_active"] is False
    assert disabled_report["blocking_reasons"] == ["wake_disabled"]
    assert disabled_report["no_cloud_wake_audio"] is True
    assert disabled_report["openai_wake_detection"] is False
    assert disabled_report["always_listening"] is False

    service = build_voice_subsystem(_voice_config(), _openai_config())
    ready = service.wake_readiness_report().to_dict()

    assert ready["wake_enabled"] is True
    assert ready["wake_provider"] == "mock"
    assert ready["wake_provider_kind"] == "mock"
    assert ready["wake_available"] is True
    assert ready["wake_monitoring_active"] is False

    started = asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    monitoring = service.wake_readiness_report().to_dict()

    assert started.ok is True
    assert monitoring["wake_monitoring_active"] is True
    assert monitoring["warnings"] == ["mock_wake_provider_active"]


def test_mock_wake_event_lifecycle_does_not_route_capture_or_call_openai() -> None:
    events = EventBuffer(capacity=64)
    service = build_voice_subsystem(
        _voice_config(cooldown_ms=0), _openai_config(), events=events
    )
    bridge = RecordingCoreBridge()
    service.attach_core_bridge(bridge)

    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    event = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.93)
    )
    session = asyncio.run(service.accept_wake_event(event.wake_event_id))

    assert event.accepted is False
    assert event.rejected_reason is None
    assert event.openai_used is False
    assert event.raw_audio_present is False
    assert isinstance(session, VoiceWakeSession)
    assert session.status == "active"
    assert session.capture_started is False
    assert session.core_routed is False
    assert session.created_ghost_request is False
    assert service.capture_provider.start_call_count == 0
    assert service.provider.network_call_count == 0
    assert bridge.calls == []

    emitted = [record["event_type"] for record in events.recent()]
    assert "voice.wake_monitoring_started" in emitted
    assert "voice.wake_detected" in emitted
    assert "voice.wake_session_started" in emitted
    assert "voice.capture_started" not in emitted
    assert "voice.transcription_started" not in emitted
    assert "voice.core_request_started" not in emitted


def test_wake_rejection_low_confidence_and_cooldown_are_truthful() -> None:
    service = build_voice_subsystem(_voice_config(cooldown_ms=2500), _openai_config())
    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))

    low = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.2)
    )
    accepted = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.95)
    )
    cooldown = asyncio.run(
        service.simulate_wake_event(session_id="voice-session", confidence=0.96)
    )
    rejected = asyncio.run(
        service.reject_wake_event(accepted.wake_event_id, reason="false_positive")
    )

    assert low.accepted is False
    assert low.rejected_reason == "low_confidence"
    assert accepted.rejected_reason is None
    assert cooldown.cooldown_active is True
    assert cooldown.rejected_reason == "cooldown_active"
    assert rejected.accepted is False
    assert rejected.rejected_reason == "false_positive"


def test_wake_session_can_expire_and_cancel_without_starting_capture_or_core() -> None:
    service = build_voice_subsystem(_voice_config(cooldown_ms=0), _openai_config())
    service.attach_core_bridge(RecordingCoreBridge())
    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))

    event = asyncio.run(service.simulate_wake_event(session_id="voice-session"))
    session = asyncio.run(service.accept_wake_event(event.wake_event_id))
    expired = asyncio.run(service.expire_wake_session(session.wake_session_id))

    second_event = asyncio.run(service.simulate_wake_event(session_id="voice-session"))
    second_session = asyncio.run(service.accept_wake_event(second_event.wake_event_id))
    cancelled = asyncio.run(
        service.cancel_wake_session(
            second_session.wake_session_id, reason="user_cancelled"
        )
    )

    assert expired.status == "expired"
    assert expired.capture_started is False
    assert expired.core_routed is False
    assert cancelled.status == "cancelled"
    assert cancelled.error_code == "user_cancelled"
    assert cancelled.capture_started is False
    assert cancelled.core_routed is False


def test_wake_status_snapshot_contains_truthful_metadata_without_audio() -> None:
    service = build_voice_subsystem(_voice_config(cooldown_ms=0), _openai_config())
    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    event = asyncio.run(service.simulate_wake_event(session_id="voice-session"))
    session = asyncio.run(service.accept_wake_event(event.wake_event_id))

    snapshot = service.status_snapshot()
    wake = snapshot["wake"]

    assert wake["enabled"] is True
    assert wake["provider"] == "mock"
    assert wake["provider_kind"] == "mock"
    assert wake["available"] is True
    assert wake["monitoring_active"] is True
    assert wake["last_wake_event"]["wake_event_id"] == event.wake_event_id
    assert wake["active_wake_session"]["wake_session_id"] == session.wake_session_id
    assert wake["no_cloud_wake_audio"] is True
    assert wake["openai_wake_detection"] is False
    assert wake["always_listening"] is False
    assert "raw_audio" not in str(wake).lower()
    assert "fake wav bytes" not in str(wake).lower()


def test_voice10_api_routes_are_backend_owned_and_do_not_call_openai(
    temp_config,
) -> None:
    temp_config.voice.enabled = True
    temp_config.voice.wake.enabled = True
    temp_config.voice.wake.provider = "mock"
    temp_config.voice.wake.allow_dev_wake = True
    temp_config.voice.wake.cooldown_ms = 0
    temp_config.openai.enabled = False
    temp_config.openai.api_key = None

    route_paths = {
        route.path
        for route in create_app(temp_config).routes
        if isinstance(route, APIRoute)
    }
    assert "/voice/wake/readiness" in route_paths
    assert "/voice/wake/simulate" in route_paths
    assert "/voice/wake/cancel" in route_paths
    assert "/voice/wake/expire" in route_paths

    with TestClient(create_app(temp_config)) as client:
        readiness = client.get("/voice/wake/readiness").json()
        simulated = client.post(
            "/voice/wake/simulate", json={"confidence": 0.94}
        ).json()

    assert readiness["action"] == "voice.getWakeReadiness"
    assert readiness["wake_readiness"]["openai_wake_detection"] is False
    assert simulated["action"] == "voice.simulateWake"
    assert simulated["wake_event"]["openai_used"] is False
    assert simulated["voice"]["wake"]["last_wake_event"]["openai_used"] is False
