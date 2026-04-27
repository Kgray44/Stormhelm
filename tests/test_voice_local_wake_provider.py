from __future__ import annotations

import asyncio
import inspect
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceWakeConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.providers import LocalWakeWordProvider
from stormhelm.core.voice.providers import MockWakeWordProvider
from stormhelm.core.voice.providers import UnavailableWakeBackend
from stormhelm.core.voice.service import build_voice_subsystem

from tests.test_voice_manual_turn import RecordingCoreBridge


class FakeWakeBackend:
    backend_name = "fake-local"
    dependency_name = "fakewake"
    platform_name = "test-platform"

    def __init__(
        self,
        *,
        available: bool = True,
        unavailable_reason: str | None = None,
        platform_supported: bool | None = True,
        device_available: bool | None = True,
        permission_state: str = "granted",
        permission_error: str | None = None,
    ) -> None:
        self.available = available
        self.unavailable_reason = unavailable_reason
        self.platform_supported = platform_supported
        self.device_available = device_available
        self.permission_state = permission_state
        self.permission_error = permission_error
        self.start_call_count = 0
        self.stop_call_count = 0
        self.openai_call_count = 0
        self.cloud_call_count = 0

    def get_availability(self, config: VoiceWakeConfig) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "dependency": self.dependency_name,
            "dependency_available": self.available,
            "platform_supported": self.platform_supported,
            "device": config.device,
            "device_available": self.device_available,
            "permission_state": self.permission_state,
            "permission_error": self.permission_error,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "uses_real_microphone": False,
        }

    def start(
        self,
        config: VoiceWakeConfig,
        on_wake: Any | None = None,
    ) -> dict[str, Any]:
        del on_wake
        self.start_call_count += 1
        return {
            "backend": self.backend_name,
            "device": config.device,
            "uses_real_microphone": False,
        }

    def stop(self, handle: dict[str, Any]) -> dict[str, Any]:
        assert handle["backend"] == self.backend_name
        self.stop_call_count += 1
        return {"backend": self.backend_name}


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


def _voice_config(**wake_overrides: Any) -> VoiceConfig:
    wake_values = {
        "enabled": True,
        "provider": "local",
        "wake_phrase": "Stormhelm",
        "confidence_threshold": 0.75,
        "cooldown_ms": 2500,
        "max_wake_session_ms": 15000,
        "false_positive_window_ms": 3000,
        "allow_dev_wake": True,
        "device": "test-mic",
        "backend": "fake-local",
    }
    wake_values.update(wake_overrides)
    return VoiceConfig(
        enabled=True,
        mode="manual",
        debug_mock_provider=True,
        wake=VoiceWakeConfig(**wake_values),
    )


def test_local_wake_provider_reports_dependency_missing_without_mock_fallback() -> None:
    provider = LocalWakeWordProvider(
        config=_voice_config().wake,
        backend=UnavailableWakeBackend(reason="dependency_missing"),
    )

    availability = provider.get_availability()
    result = provider.start_wake_monitoring()

    assert availability["provider"] == "local"
    assert availability["provider_kind"] == "local"
    assert availability["available"] is False
    assert availability["unavailable_reason"] == "dependency_missing"
    assert availability["mock_provider_active"] is False
    assert availability["openai_used"] is False
    assert availability["cloud_used"] is False
    assert availability["raw_audio_present"] is False
    assert result.ok is False
    assert result.error_code == "dependency_missing"


def test_local_wake_provider_reports_typed_unavailable_reasons() -> None:
    cases = [
        ("unsupported_platform", {"platform_supported": False}),
        ("device_unavailable", {"device_available": False}),
        (
            "permission_denied",
            {"permission_state": "denied", "permission_error": "permission denied"},
        ),
        ("provider_not_configured", {}),
        ("backend_unavailable", {}),
    ]

    for reason, backend_values in cases:
        backend = FakeWakeBackend(
            available=False,
            unavailable_reason=reason,
            **backend_values,
        )
        provider = LocalWakeWordProvider(config=_voice_config().wake, backend=backend)

        availability = provider.get_availability()
        result = provider.start_wake_monitoring()

        assert availability["available"] is False
        assert availability["unavailable_reason"] == reason
        assert result.ok is False
        assert result.error_code == reason
        assert availability["provider_kind"] == "local"
        assert availability["mock_provider_active"] is False


def test_local_wake_service_uses_local_provider_without_silent_mock_fallback() -> None:
    disabled = build_voice_subsystem(
        _voice_config(enabled=False, allow_dev_wake=True),
        _openai_config(),
    )
    blocked = build_voice_subsystem(
        _voice_config(enabled=True, allow_dev_wake=False),
        _openai_config(),
    )

    assert isinstance(disabled.wake_provider, LocalWakeWordProvider)
    assert not isinstance(disabled.wake_provider, MockWakeWordProvider)
    assert disabled.wake_readiness_report().blocking_reasons == ["wake_disabled"]
    assert blocked.wake_readiness_report().blocking_reasons == ["dev_wake_not_allowed"]


def test_local_wake_provider_starts_and_stops_fake_backend_when_explicitly_enabled() -> (
    None
):
    backend = FakeWakeBackend()
    provider = LocalWakeWordProvider(config=_voice_config().wake, backend=backend)

    started = provider.start_wake_monitoring()
    second = provider.start_wake_monitoring()
    stopped = provider.stop_wake_monitoring()
    second_stop = provider.stop_wake_monitoring()

    assert started.ok is True
    assert started.status == "monitoring_local"
    assert started.payload["provider_kind"] == "local"
    assert started.payload["backend"] == "fake-local"
    assert second.ok is False
    assert second.error_code == "monitoring_already_active"
    assert stopped.ok is True
    assert stopped.status == "stopped"
    assert second_stop.ok is False
    assert second_stop.error_code == "no_active_wake_monitoring"
    assert backend.start_call_count == 1
    assert backend.stop_call_count == 1


def test_local_wake_service_processes_fake_backend_wake_without_capture_or_core() -> (
    None
):
    backend = FakeWakeBackend()
    events = EventBuffer(capacity=64)
    service = build_voice_subsystem(
        _voice_config(cooldown_ms=0), _openai_config(), events=events
    )
    service.wake_provider = LocalWakeWordProvider(
        config=service.config.wake, backend=backend
    )
    bridge = RecordingCoreBridge()
    service.attach_core_bridge(bridge)

    started = asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    event = asyncio.run(
        service.record_wake_candidate(session_id="voice-session", confidence=0.93)
    )
    session = asyncio.run(service.accept_wake_event(event.wake_event_id))

    assert started.ok is True
    assert event.provider == "local"
    assert event.provider_kind == "local"
    assert event.source == "local"
    assert event.backend == "fake-local"
    assert event.device == "test-mic"
    assert event.openai_used is False
    assert event.cloud_used is False
    assert event.raw_audio_present is False
    assert session.status == "active"
    assert session.capture_started is False
    assert session.core_routed is False
    assert service.capture_provider.get_active_capture() is None
    assert service.provider.network_call_count == 0
    assert backend.openai_call_count == 0
    assert backend.cloud_call_count == 0
    assert bridge.calls == []

    emitted = [record["event_type"] for record in events.recent()]
    wake_detected = [
        record
        for record in events.recent()
        if record["event_type"] == "voice.wake_detected"
    ][0]
    assert "voice.wake_monitoring_started" in emitted
    assert "voice.wake_detected" in emitted
    assert "voice.wake_session_started" in emitted
    assert "voice.capture_started" not in emitted
    assert "voice.transcription_started" not in emitted
    assert "voice.core_request_started" not in emitted
    assert wake_detected["payload"]["backend"] == "fake-local"
    assert wake_detected["payload"]["device"] == "test-mic"
    assert wake_detected["payload"]["cloud_used"] is False
    assert wake_detected["payload"]["openai_used"] is False
    assert wake_detected["payload"]["raw_audio_present"] is False


def test_local_wake_service_start_stop_truthful_for_no_active_monitoring() -> None:
    backend = FakeWakeBackend()
    service = build_voice_subsystem(_voice_config(), _openai_config())
    service.wake_provider = LocalWakeWordProvider(
        config=service.config.wake, backend=backend
    )

    stopped_before_start = asyncio.run(service.stop_wake_monitoring())
    started = asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    stopped = asyncio.run(service.stop_wake_monitoring(session_id="voice-session"))

    assert stopped_before_start.ok is False
    assert stopped_before_start.error_code == "no_active_wake_monitoring"
    assert started.ok is True
    assert stopped.ok is True
    assert service.status_snapshot()["wake"]["monitoring_active"] is False


def test_local_wake_confidence_cooldown_and_status_privacy_are_truthful() -> None:
    backend = FakeWakeBackend()
    service = build_voice_subsystem(_voice_config(cooldown_ms=2500), _openai_config())
    service.wake_provider = LocalWakeWordProvider(
        config=service.config.wake, backend=backend
    )

    asyncio.run(service.start_wake_monitoring(session_id="voice-session"))
    low = asyncio.run(
        service.record_wake_candidate(session_id="voice-session", confidence=0.2)
    )
    accepted = asyncio.run(
        service.record_wake_candidate(session_id="voice-session", confidence=0.95)
    )
    cooldown = asyncio.run(
        service.record_wake_candidate(session_id="voice-session", confidence=0.96)
    )
    snapshot = service.status_snapshot()["wake"]

    assert low.rejected_reason == "low_confidence"
    assert accepted.rejected_reason is None
    assert cooldown.rejected_reason == "cooldown_active"
    assert cooldown.cooldown_active is True
    assert snapshot["provider"] == "local"
    assert snapshot["provider_kind"] == "local"
    assert snapshot["wake_backend"] == "fake-local"
    assert snapshot["dependency_available"] is True
    assert snapshot["device"] == "test-mic"
    assert snapshot["device_available"] is True
    assert snapshot["permission_state"] == "granted"
    assert snapshot["no_cloud_wake_audio"] is True
    assert snapshot["openai_wake_detection"] is False
    assert snapshot["cloud_wake_detection"] is False
    assert snapshot["command_routing_from_wake"] is False
    assert "raw_audio" not in str(snapshot.get("last_wake_event", {})).lower()


def test_local_wake_static_boundary_has_no_openai_or_realtime_calls() -> None:
    source = inspect.getsource(LocalWakeWordProvider)

    forbidden = [
        "audio.transcriptions",
        "audio.speech",
        "chat.completions",
        "responses.create",
        "realtime.connect",
        "OpenAI(",
    ]

    for token in forbidden:
        assert token not in source


def test_mock_wake_provider_behavior_still_uses_voice10_mock_path() -> None:
    provider = MockWakeWordProvider(
        config=_voice_config(provider="mock", backend="mock").wake
    )

    availability = provider.get_availability()
    event = provider.simulate_wake(session_id="voice-session", confidence=0.91)

    assert availability["provider_kind"] == "mock"
    assert availability["mock_provider_active"] is True
    assert event.provider == "mock"
    assert event.provider_kind == "mock"
    assert event.openai_used is False
