from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.api.app import create_app


class _FakeAssistant:
    def __init__(self, content: str = "Current weather is clear.") -> None:
        self.content = content

    async def handle_message(self, *args, **kwargs) -> dict[str, object]:
        metadata = {
            "bearing_title": "Weather",
            "micro_response": "Weather is clear.",
            "full_response": self.content,
        }
        if not self.content:
            metadata = {}
        return {
            "assistant_message": {
                "message_id": "assistant-voice-1",
                "role": "assistant",
                "content": self.content,
                "metadata": metadata,
            },
            "jobs": [],
            "actions": [],
        }


class _FakeVoice:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self.synth_calls: list[dict[str, object]] = []
        self.play_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []
        self.speak_decisions: list[dict[str, object]] = []
        self.played = threading.Event()
        self.stream_entered = threading.Event()
        self.stream_block_seconds = 0.0

    def remember_assistant_speak_decision(self, decision: dict[str, object]) -> None:
        self.speak_decisions.append(dict(decision))

    def runtime_voice_gate_snapshot(self) -> dict[str, object]:
        return {
            "env_loaded": True,
            "openai_key_present": True,
            "openai_enabled": True,
            "voice_enabled": self.config.enabled,
            "spoken_responses_enabled": self.config.spoken_responses_enabled,
            "playback_enabled": self.config.playback.enabled,
            "playback_provider": self.config.playback.provider,
            "streaming_playback_enabled": self.config.playback.streaming_enabled,
            "openai_stream_tts_outputs": self.config.openai.stream_tts_outputs,
            "live_format": self.config.openai.tts_live_format,
            "dev_playback_allowed": self.config.playback.allow_dev_playback,
            "raw_secret_logged": False,
        }

    async def synthesize_speech_text(self, text: str, **kwargs):
        self.synth_calls.append({"text": text, **kwargs})
        return SimpleNamespace(ok=True, synthesis_id="synthesis-chat-1")

    async def play_speech_output(self, synthesis, **kwargs):
        self.play_calls.append({"synthesis": synthesis, **kwargs})
        self.played.set()
        return SimpleNamespace(
            ok=True,
            status="completed",
            user_heard_claimed=False,
            core_result_mutated=False,
        )

    async def stream_core_approved_spoken_text(self, text: str, **kwargs):
        self.stream_calls.append({"text": text, **kwargs})
        self.stream_entered.set()
        if self.stream_block_seconds:
            time.sleep(self.stream_block_seconds)
        self.played.set()
        return SimpleNamespace(
            ok=True,
            status="completed",
            playback_result=SimpleNamespace(
                ok=True,
                status="completed",
                user_heard_claimed=True,
            ),
            user_heard_claimed=True,
            first_audio_latency=SimpleNamespace(to_dict=lambda: {"first_audio_available": True}),
        )

    def status_snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled,
            "playback": {
                "enabled": self.config.playback.enabled,
                "user_heard_claimed": False,
            },
            "runtime_gate_snapshot": self.runtime_voice_gate_snapshot(),
            "last_voice_speak_decision": self.speak_decisions[-1]
            if self.speak_decisions
            else None,
        }


class _FakeEvents:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []

    def publish(self, **payload):
        self.published.append(dict(payload))


class _FakeContainer:
    def __init__(self, voice: _FakeVoice) -> None:
        self.voice = voice
        self.assistant = _FakeAssistant()
        self.events = _FakeEvents()
        self.config = SimpleNamespace(
            version_label="test",
            app_name="Stormhelm Test",
            protocol_version="test",
            concurrency=SimpleNamespace(max_workers=1),
            runtime=SimpleNamespace(mode="source"),
            project_root="C:/Stormhelm",
        )
        self.lifecycle = SimpleNamespace(
            install_state=SimpleNamespace(install_mode=SimpleNamespace(value="source"))
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _voice_config(*, enabled: bool = True) -> VoiceConfig:
    return VoiceConfig(
        enabled=enabled,
        mode="output_only" if enabled else "disabled",
        spoken_responses_enabled=enabled,
        debug_mock_provider=True,
        openai=VoiceOpenAIConfig(tts_voice="onyx"),
        playback=VoicePlaybackConfig(
            enabled=enabled,
            provider="mock",
            allow_dev_playback=True,
        ),
    )


def _streaming_voice_config(*, enabled: bool = True) -> VoiceConfig:
    config = _voice_config(enabled=enabled)
    config.openai.stream_tts_outputs = True
    config.openai.tts_live_format = "pcm"
    config.playback.streaming_enabled = True
    config.playback.provider = "local"
    return config


def test_chat_send_schedules_assistant_voice_output_when_output_voice_enabled(
    monkeypatch,
    temp_config,
) -> None:
    voice = _FakeVoice(_voice_config(enabled=True))
    container = _FakeContainer(voice)
    monkeypatch.setattr("stormhelm.core.api.app.build_container", lambda config=None: container)

    with TestClient(create_app(temp_config)) as client:
        response = client.post("/chat/send", json={"message": "what is the weather"})
        assert voice.played.wait(2)

    payload = response.json()
    assert response.status_code == 200
    assert voice.synth_calls[0]["text"] == "Weather is clear."
    assert voice.synth_calls[0]["source"] == "assistant_response"
    assert voice.synth_calls[0]["session_id"] == "default"
    assert voice.play_calls[0]["session_id"] == "default"
    metadata = payload["assistant_message"]["metadata"]
    assert metadata["voice_output"]["scheduled"] is True
    assert metadata["voice_output"]["playback_requested"] is True
    assert metadata["voice_output"]["user_heard_claimed"] is False


def test_chat_send_streams_typed_response_and_records_speak_decision(
    monkeypatch,
    temp_config,
) -> None:
    voice = _FakeVoice(_streaming_voice_config(enabled=True))
    container = _FakeContainer(voice)
    monkeypatch.setattr("stormhelm.core.api.app.build_container", lambda config=None: container)

    with TestClient(create_app(temp_config)) as client:
        response = client.post(
            "/chat/send",
            json={
                "message": "what time is it",
                "session_id": "typed-voice",
                "surface_mode": "ghost",
                "active_module": "ghost",
            },
        )
        assert voice.played.wait(2)

    payload = response.json()
    decision = voice.speak_decisions[-1]
    metadata = payload["assistant_message"]["metadata"]

    assert response.status_code == 200
    assert voice.stream_calls
    assert voice.stream_calls[0]["text"] == "Weather is clear."
    assert voice.stream_calls[0]["source"] == "assistant_response"
    assert voice.stream_calls[0]["metadata"]["prompt_source"] == "typed_ui"
    assert voice.synth_calls == []
    assert decision["prompt_source"] == "typed_ui"
    assert decision["response_has_text"] is True
    assert decision["approved_spoken_text_present"] is True
    assert decision["speakable"] is True
    assert decision["voice_service_called"] is True
    assert decision["skipped_reason"] is None
    assert decision["playback_provider"] == "local"
    assert decision["raw_secret_logged"] is False
    assert decision["raw_audio_logged"] is False
    assert metadata["voice_output"]["decision"]["voice_service_called"] is True
    assert metadata["voice_output"]["decision"]["approved_spoken_text_present"] is True


def test_chat_send_records_skip_reason_when_typed_response_has_no_spoken_text(
    monkeypatch,
    temp_config,
) -> None:
    voice = _FakeVoice(_streaming_voice_config(enabled=True))
    container = _FakeContainer(voice)
    container.assistant = _FakeAssistant(content="")
    monkeypatch.setattr("stormhelm.core.api.app.build_container", lambda config=None: container)

    with TestClient(create_app(temp_config)) as client:
        response = client.post(
            "/chat/send",
            json={"message": "empty answer", "session_id": "typed-empty"},
        )
        time.sleep(0.1)

    payload = response.json()
    decision = voice.speak_decisions[-1]

    assert response.status_code == 200
    assert voice.stream_calls == []
    assert voice.synth_calls == []
    assert decision["prompt_source"] == "typed_ui"
    assert decision["response_has_text"] is False
    assert decision["approved_spoken_text_present"] is False
    assert decision["speakable"] is False
    assert decision["voice_service_called"] is False
    assert decision["skipped_reason"] == "empty_spoken_text"
    assert payload["assistant_message"]["metadata"]["voice_output"]["scheduled"] is False
    assert (
        payload["assistant_message"]["metadata"]["voice_output"]["decision"][
            "skipped_reason"
        ]
        == "empty_spoken_text"
    )


def test_chat_send_does_not_schedule_voice_output_when_voice_disabled(
    monkeypatch,
    temp_config,
) -> None:
    voice = _FakeVoice(_voice_config(enabled=False))
    container = _FakeContainer(voice)
    monkeypatch.setattr("stormhelm.core.api.app.build_container", lambda config=None: container)

    with TestClient(create_app(temp_config)) as client:
        response = client.post("/chat/send", json={"message": "what is the weather"})
        time.sleep(0.1)

    payload = response.json()
    assert response.status_code == 200
    assert voice.synth_calls == []
    assert voice.play_calls == []
    decision = voice.speak_decisions[-1]
    assert decision["speakable"] is False
    assert decision["voice_service_called"] is False
    assert decision["skipped_reason"] == "voice_output_disabled"
    assert payload["assistant_message"]["metadata"]["voice_output"]["scheduled"] is False


def test_voice_output_background_work_does_not_block_core_health(
    monkeypatch,
    temp_config,
) -> None:
    voice = _FakeVoice(_streaming_voice_config(enabled=True))
    voice.stream_block_seconds = 0.55
    container = _FakeContainer(voice)
    monkeypatch.setattr("stormhelm.core.api.app.build_container", lambda config=None: container)

    with TestClient(create_app(temp_config)) as client:
        response = client.post(
            "/chat/send",
            json={"message": "what time is it", "session_id": "typed-voice"},
        )
        assert response.status_code == 200
        assert voice.stream_entered.wait(1)
        started = time.perf_counter()
        health = client.get("/health")
        health_wall = time.perf_counter() - started
        assert voice.played.wait(2)

    assert health.status_code == 200
    assert health_wall < 0.25
