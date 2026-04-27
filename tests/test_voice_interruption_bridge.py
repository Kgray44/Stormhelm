from __future__ import annotations

from PySide6 import QtCore
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from stormhelm.core.api.app import create_app
from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.controllers.main_controller import MainController
from stormhelm.ui.voice_surface import build_voice_ui_state


class _VoiceInterruptionClient(QtCore.QObject):
    error_occurred = QtCore.Signal(str, str)
    snapshot_received = QtCore.Signal(dict)
    health_received = QtCore.Signal(dict)
    chat_received = QtCore.Signal(dict)
    note_saved = QtCore.Signal(dict)
    voice_action_received = QtCore.Signal(dict)
    stream_event_received = QtCore.Signal(dict)
    stream_state_received = QtCore.Signal(dict)
    stream_gap_received = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.stop_speaking_calls: list[dict[str, object]] = []
        self.suppression_calls: list[dict[str, object]] = []
        self.mute_calls: list[dict[str, object]] = []
        self.unmute_calls: list[dict[str, object]] = []
        self.playback_stops: list[dict[str, object]] = []
        self.snapshot_calls = 0

    def fetch_snapshot(self) -> None:
        self.snapshot_calls += 1

    def stop_voice_speaking(self, payload: dict[str, object] | None = None) -> None:
        self.stop_speaking_calls.append(dict(payload or {}))

    def suppress_current_voice_response(
        self, payload: dict[str, object] | None = None
    ) -> None:
        self.suppression_calls.append(dict(payload or {}))

    def mute_spoken_responses(self, payload: dict[str, object] | None = None) -> None:
        self.mute_calls.append(dict(payload or {}))

    def unmute_spoken_responses(self, payload: dict[str, object] | None = None) -> None:
        self.unmute_calls.append(dict(payload or {}))

    def stop_voice_playback(self, payload: dict[str, object] | None = None) -> None:
        self.playback_stops.append(dict(payload or {}))


def test_bridge_voice9_slots_emit_backend_interruption_requests(temp_config) -> None:
    bridge = UiBridge(temp_config)
    stops: list[dict] = []
    suppressions: list[dict] = []
    mutes: list[dict] = []
    unmutes: list[dict] = []

    bridge.voiceStopSpeakingRequested.connect(stops.append)
    bridge.voiceSuppressCurrentResponseRequested.connect(suppressions.append)
    bridge.voiceMuteSpokenResponsesRequested.connect(mutes.append)
    bridge.voiceUnmuteSpokenResponsesRequested.connect(unmutes.append)

    bridge.stopSpeaking("playback-1")
    bridge.suppressCurrentResponse("turn-1")
    bridge.muteSpokenResponses()
    bridge.unmuteSpokenResponses()

    assert stops == [{"playback_id": "playback-1", "reason": "user_requested"}]
    assert suppressions == [{"turn_id": "turn-1", "reason": "user_requested"}]
    assert mutes == [{"scope": "session", "reason": "user_requested"}]
    assert unmutes == [{"scope": "session", "reason": "user_requested"}]


def test_controller_routes_voice9_requests_to_client_only(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = _VoiceInterruptionClient()
    MainController(config=temp_config, bridge=bridge, client=client)

    bridge.stopSpeaking("playback-1")
    bridge.suppressCurrentResponse("turn-1")
    bridge.muteSpokenResponses()
    bridge.unmuteSpokenResponses()

    assert client.stop_speaking_calls == [
        {"playback_id": "playback-1", "reason": "user_requested"}
    ]
    assert client.suppression_calls == [
        {"turn_id": "turn-1", "reason": "user_requested"}
    ]
    assert client.mute_calls == [{"scope": "session", "reason": "user_requested"}]
    assert client.unmute_calls == [{"scope": "session", "reason": "user_requested"}]
    assert client.playback_stops == []


def test_voice9_api_routes_are_backend_owned(temp_config) -> None:
    route_paths = {
        route.path
        for route in create_app(temp_config).routes
        if isinstance(route, APIRoute)
    }

    assert "/voice/output/stop-speaking" in route_paths
    assert "/voice/output/suppress-current-response" in route_paths
    assert "/voice/output/mute" in route_paths
    assert "/voice/output/unmute" in route_paths
    assert "/voice/interruption/handle" in route_paths


def test_voice9_api_stop_speaking_returns_typed_noop_result(temp_config) -> None:
    with TestClient(create_app(temp_config)) as client:
        response = client.post("/voice/output/stop-speaking", json={})

    payload = response.json()
    assert response.status_code == 200
    assert payload["action"] == "voice.stopSpeaking"
    assert payload["result"]["status"] == "no_active_playback"
    assert payload["result"]["core_task_cancelled"] is False
    assert payload["result"]["core_result_mutated"] is False
    assert payload["voice"]["interruption"]["last_interruption_status"] == (
        "no_active_playback"
    )


def test_voice_ui_state_payload_surfaces_mute_and_interruption_truth() -> None:
    payload = build_voice_ui_state(
        {
            "voice": {
                "enabled": True,
                "availability": {"available": True, "provider_name": "openai"},
                "state": {"state": "speaking"},
                "openai": {"enabled": True},
                "capture": {"enabled": True, "available": True},
                "stt": {},
                "manual_turns": {"last_core_result_state": "completed"},
                "tts": {
                    "enabled": True,
                    "spoken_responses_enabled": True,
                    "last_spoken_text_preview": "Response remains available visually.",
                },
                "playback": {
                    "enabled": True,
                    "available": True,
                    "active_playback_id": "playback-1",
                    "active_playback_status": "started",
                    "last_playback_status": "started",
                },
                "interruption": {
                    "spoken_output_muted": True,
                    "muted_scope": "session",
                    "last_interruption_intent": "stop_speaking",
                    "last_interruption_status": "completed",
                    "core_task_cancelled_by_voice": False,
                    "core_result_mutated_by_voice": False,
                },
                "runtime_truth": {
                    "no_wake_word": True,
                    "no_vad": True,
                    "no_realtime": True,
                    "no_continuous_loop": True,
                    "always_listening": False,
                },
            }
        }
    )

    assert payload["spoken_output_muted"] is True
    assert payload["active_playback_interruptible"] is True
    assert payload["ghost"]["primary_action"] == "voice.stopSpeaking"
    assert any(
        action["localAction"] == "voice.unmuteSpokenResponses"
        for action in payload["ghost"]["actions"]
    )
    assert payload["interruption"]["core_task_cancelled_by_voice"] is False
    assert payload["interruption"]["core_result_mutated_by_voice"] is False
    assert "Task cancelled" not in str(payload)
    assert "Barge" not in str(payload)
