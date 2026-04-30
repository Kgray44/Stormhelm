from __future__ import annotations

from PySide6 import QtCore
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from stormhelm.core.api.app import create_app
from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.controllers.main_controller import MainController


class _VoiceClient(QtCore.QObject):
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
        self.started: list[dict[str, object]] = []
        self.stopped: list[dict[str, object]] = []
        self.cancelled: list[dict[str, object]] = []
        self.submitted: list[dict[str, object]] = []
        self.capture_turns: list[dict[str, object]] = []
        self.listen_turns: list[dict[str, object]] = []
        self.playback_stops: list[dict[str, object]] = []
        self.readiness_fetches = 0
        self.snapshot_calls = 0

    def fetch_snapshot(self) -> None:
        self.snapshot_calls += 1

    def fetch_voice_readiness(self) -> None:
        self.readiness_fetches += 1

    def start_voice_capture(self, payload: dict[str, object] | None = None) -> None:
        self.started.append(dict(payload or {}))

    def stop_voice_capture(self, payload: dict[str, object] | None = None) -> None:
        self.stopped.append(dict(payload or {}))

    def cancel_voice_capture(self, payload: dict[str, object] | None = None) -> None:
        self.cancelled.append(dict(payload or {}))

    def submit_captured_audio_turn(
        self, payload: dict[str, object] | None = None
    ) -> None:
        self.submitted.append(dict(payload or {}))

    def capture_and_submit_voice_turn(
        self, payload: dict[str, object] | None = None
    ) -> None:
        self.capture_turns.append(dict(payload or {}))

    def listen_and_submit_voice_turn(
        self, payload: dict[str, object] | None = None
    ) -> None:
        self.listen_turns.append(dict(payload or {}))

    def stop_voice_playback(self, payload: dict[str, object] | None = None) -> None:
        self.playback_stops.append(dict(payload or {}))


def test_bridge_voice_control_slots_emit_backend_action_requests(temp_config) -> None:
    bridge = UiBridge(temp_config)
    starts: list[dict] = []
    stops: list[dict] = []
    cancels: list[dict] = []
    capture_turns: list[dict] = []
    listen_turns: list[dict] = []

    bridge.voiceStartPushToTalkCaptureRequested.connect(starts.append)
    bridge.voiceStopPushToTalkCaptureRequested.connect(stops.append)
    bridge.voiceCancelCaptureRequested.connect(cancels.append)
    bridge.voiceCaptureAndSubmitTurnRequested.connect(capture_turns.append)
    bridge.voiceListenAndSubmitTurnRequested.connect(listen_turns.append)

    bridge.startPushToTalkCapture()
    bridge.stopPushToTalkCapture("capture-1")
    bridge.cancelCapture("capture-1")
    bridge.captureAndSubmitTurn("capture-1", "deck", True, True)
    bridge.listenAndSubmitTurn("deck", True)

    assert starts == [{"session_id": "default", "metadata": {"surface": "ghost"}}]
    assert stops == [{"capture_id": "capture-1", "reason": "user_released"}]
    assert cancels == [{"capture_id": "capture-1", "reason": "user_cancelled"}]
    assert capture_turns == [
        {
            "capture_id": "capture-1",
            "mode": "deck",
            "synthesize_response": True,
            "play_response": True,
        }
    ]
    assert listen_turns == [
        {"session_id": "default", "mode": "deck", "play_response": True}
    ]
    assert bridge.statusLine in {
        "Starting push-to-talk capture.",
        "Stopping capture.",
        "Cancelling capture.",
        "Submitting captured audio through Core.",
        "Listening for one voice request.",
    }


def test_controller_routes_voice_bridge_requests_to_client_only(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = _VoiceClient()
    MainController(config=temp_config, bridge=bridge, client=client)

    bridge.startPushToTalkCapture()
    bridge.stopPushToTalkCapture("capture-1")
    bridge.cancelCapture("capture-1")
    bridge.captureAndSubmitTurn("capture-1", "ghost", False, False)
    bridge.listenAndSubmitTurn("ghost", True)
    bridge.stopVoicePlayback("playback-1")

    assert client.started == [
        {"session_id": "default", "metadata": {"surface": "ghost"}}
    ]
    assert client.stopped == [{"capture_id": "capture-1", "reason": "user_released"}]
    assert client.cancelled == [{"capture_id": "capture-1", "reason": "user_cancelled"}]
    assert client.capture_turns == [
        {
            "capture_id": "capture-1",
            "mode": "ghost",
            "synthesize_response": False,
            "play_response": False,
        }
    ]
    assert client.listen_turns == [
        {"session_id": "default", "mode": "ghost", "play_response": True}
    ]
    assert client.playback_stops == [
        {"playback_id": "playback-1", "reason": "user_requested"}
    ]


def test_l6_voice_listen_turn_api_route_is_exposed(temp_config) -> None:
    paths = {
        route.path
        for route in create_app(temp_config).routes
        if isinstance(route, APIRoute)
    }

    assert "/voice/capture/listen-turn" in paths


def test_bridge_voice_action_result_updates_from_backend_status_without_raw_audio(
    temp_config,
) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_voice_action_result(
        {
            "action": "voice.startPushToTalkCapture",
            "result": {"ok": True, "capture_id": "capture-1", "status": "recording"},
            "voice": {
                "enabled": True,
                "availability": {"available": True, "provider_name": "openai"},
                "state": {"state": "capturing"},
                "openai": {"enabled": True},
                "capture": {
                    "enabled": True,
                    "available": True,
                    "provider": "mock",
                    "mode": "push_to_talk",
                    "device": "test-mic",
                    "active_capture_id": "capture-1",
                    "active_capture_status": "recording",
                    "last_capture_audio_input_metadata": {"data": "raw bytes"},
                    "mock_provider_active": True,
                    "always_listening": False,
                    "no_wake_word": True,
                    "no_vad": True,
                    "no_realtime": True,
                    "no_continuous_loop": True,
                },
                "runtime_truth": {
                    "always_listening": False,
                    "no_wake_word": True,
                    "no_vad": True,
                    "no_realtime": True,
                    "no_continuous_loop": True,
                },
            },
        }
    )

    assert bridge.voiceState["active_capture_id"] == "capture-1"
    assert bridge.voiceState["voice_core_state"] == "listening"
    assert bridge.assistant_state_value == "listening"
    assert "raw bytes" not in str(bridge.voiceState)


def test_bridge_voice_state_from_snapshot_surfaces_truth_flags_and_compact_deck_station(
    temp_config,
) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "voice": {
                    "enabled": True,
                    "availability": {"available": True, "provider_name": "openai"},
                    "state": {"state": "dormant"},
                    "openai": {"enabled": True},
                    "capture": {
                        "enabled": True,
                        "available": True,
                        "provider": "local",
                        "mode": "push_to_talk",
                        "device": "default",
                        "active_capture_id": None,
                        "active_capture_status": None,
                        "last_capture_id": "capture-1",
                        "last_capture_status": "completed",
                        "last_capture_audio_input_metadata": {
                            "input_id": "audio-1",
                            "size_bytes": 256,
                        },
                        "always_listening": False,
                        "no_wake_word": True,
                        "no_vad": True,
                        "no_realtime": True,
                        "no_continuous_loop": True,
                    },
                    "stt": {
                        "last_transcript_preview": "Open downloads.",
                        "last_transcription_state": "succeeded",
                    },
                    "manual_turns": {
                        "last_core_result_state": "completed",
                        "last_route_family": "software_control",
                    },
                    "tts": {
                        "last_synthesis_state": "succeeded",
                        "last_spoken_text_preview": "I can open Downloads after confirmation.",
                    },
                    "playback": {"last_playback_status": "completed"},
                    "runtime_truth": {
                        "always_listening": False,
                        "no_wake_word": True,
                        "no_vad": True,
                        "no_realtime": True,
                        "no_continuous_loop": True,
                    },
                }
            }
        }
    )

    assert bridge.voiceState["capture_provider_kind"] == "local"
    assert bridge.voiceState["truth_flags"]["always_listening"] is False
    assert bridge.voiceState["truth_flags"]["no_wake_word"] is True
    assert any(item["label"] == "Voice" for item in bridge.statusStripItems)
    station = next(
        panel
        for panel in bridge.deckPanels
        if panel.get("panelId") == "voice-capture-station"
    )
    assert station["contentKind"] == "command-station"
    assert "Wake active" not in str(bridge.voiceState)
    assert "Realtime active" not in str(bridge.voiceState)


def test_voice_api_control_routes_are_backend_owned(temp_config) -> None:
    route_paths = {
        route.path
        for route in create_app(temp_config).routes
        if isinstance(route, APIRoute)
    }

    assert "/voice/capture/start" in route_paths
    assert "/voice/capture/stop" in route_paths
    assert "/voice/capture/cancel" in route_paths
    assert "/voice/capture/submit" in route_paths
    assert "/voice/capture/turn" in route_paths
    assert "/voice/playback/stop" in route_paths
    assert "/voice/readiness" in route_paths
    assert "/voice/pipeline" in route_paths


def test_voice_api_start_capture_returns_typed_blocked_result_when_disabled(
    temp_config,
) -> None:
    with TestClient(create_app(temp_config)) as client:
        response = client.post("/voice/capture/start", json={})

    payload = response.json()
    assert response.status_code == 200
    assert payload["action"] == "voice.startPushToTalkCapture"
    assert payload["result"]["ok"] is False
    assert payload["result"]["status"] == "blocked"
    assert payload["voice"]["capture"]["enabled"] is False
    assert payload["voice"]["capture"]["no_wake_word"] is True


def test_voice_api_readiness_returns_safe_report_and_pipeline_summary(
    temp_config,
) -> None:
    with TestClient(create_app(temp_config)) as client:
        readiness_response = client.get("/voice/readiness")
        pipeline_response = client.get("/voice/pipeline")

    readiness_payload = readiness_response.json()
    pipeline_payload = pipeline_response.json()

    assert readiness_response.status_code == 200
    assert pipeline_response.status_code == 200
    assert readiness_payload["action"] == "voice.getReadinessReport"
    assert readiness_payload["readiness"]["overall_status"] == "disabled"
    assert readiness_payload["readiness"]["truth_flags"]["no_realtime"] is True
    assert readiness_payload["readiness"]["api_key_present"] is False
    assert "test-key" not in str(readiness_payload["readiness"])
    assert pipeline_payload["action"] == "voice.getLastPipelineSummary"
    assert pipeline_payload["pipeline_summary"]["stage"] in {"idle", "blocked"}


def test_bridge_refresh_readiness_action_uses_status_refresh_without_provider_calls(
    temp_config,
) -> None:
    bridge = UiBridge(temp_config)
    client = _VoiceClient()
    MainController(config=temp_config, bridge=bridge, client=client)

    bridge.performLocalSurfaceAction("voice.refreshReadiness")

    assert client.readiness_fetches == 1
    assert client.started == []
    assert client.capture_turns == []
