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
        return {
            "assistant_message": {
                "message_id": "assistant-voice-1",
                "role": "assistant",
                "content": self.content,
                "metadata": {
                    "bearing_title": "Weather",
                    "micro_response": "Weather is clear.",
                    "full_response": self.content,
                },
            },
            "jobs": [],
            "actions": [],
        }


class _FakeVoice:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self.synth_calls: list[dict[str, object]] = []
        self.play_calls: list[dict[str, object]] = []
        self.played = threading.Event()

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

    def status_snapshot(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled,
            "playback": {
                "enabled": self.config.playback.enabled,
                "user_heard_claimed": False,
            },
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
    assert "voice_output" not in payload["assistant_message"]["metadata"]
