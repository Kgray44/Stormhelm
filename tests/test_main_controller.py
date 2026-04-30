from __future__ import annotations

from PySide6 import QtCore
from PySide6 import QtGui

from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.controllers.main_controller import MainController


class DummyClient(QtCore.QObject):
    error_occurred = QtCore.Signal(str, str)
    snapshot_received = QtCore.Signal(dict)
    health_received = QtCore.Signal(dict)
    status_received = QtCore.Signal(dict)
    chat_received = QtCore.Signal(dict)
    note_saved = QtCore.Signal(dict)
    stream_event_received = QtCore.Signal(dict)
    stream_state_received = QtCore.Signal(dict)
    stream_gap_received = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.sent_messages: list[str] = []
        self.sent_payloads: list[dict[str, str]] = []
        self.saved_notes: list[dict[str, str]] = []
        self.health_calls = 0
        self.status_calls = 0
        self.snapshot_calls = 0
        self.snapshot_requests: list[dict[str, object]] = []
        self.started_streams: list[dict[str, object]] = []
        self.stopped_streams = 0

    def fetch_health(self) -> None:
        self.health_calls += 1

    def fetch_status(self) -> None:
        self.status_calls += 1

    def fetch_snapshot(self, **kwargs: object) -> None:
        self.snapshot_calls += 1
        self.snapshot_requests.append(dict(kwargs))

    def start_event_stream(self, *, session_id: str = "default", cursor: int | None = None) -> None:
        self.started_streams.append({"session_id": session_id, "cursor": cursor})

    def stop_event_stream(self) -> None:
        self.stopped_streams += 1

    def send_message(
        self,
        message: str,
        session_id: str = "default",
        *,
        surface_mode: str = "ghost",
        active_module: str = "chartroom",
        workspace_context: dict[str, object] | None = None,
        input_context: dict[str, object] | None = None,
        response_profile: str | None = None,
    ) -> None:
        self.sent_messages.append(message)
        self.sent_payloads.append(
            {
                "message": message,
                "session_id": session_id,
                "surface_mode": surface_mode,
                "active_module": active_module,
                "workspace_context": workspace_context or {},
                "input_context": input_context or {},
                "response_profile": response_profile,
            }
        )

    def save_note(self, title: str, content: str, *, session_id: str = "default", workspace_id: str = "") -> None:
        self.saved_notes.append(
            {
                "title": title,
                "content": content,
                "session_id": session_id,
                "workspace_id": workspace_id,
            }
        )


def test_main_controller_intercepts_local_deck_command(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._send_message("/deck")

    assert bridge.mode_value == "deck"
    assert bridge.statusLine == "Command Deck unfolded."
    assert client.sent_messages == []


def test_main_controller_intercepts_local_ghost_command(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)
    bridge.setMode("deck")

    controller._send_message("/ghost")

    assert bridge.mode_value == "ghost"
    assert bridge.statusLine == "Ghost Mode holding steady."
    assert client.sent_messages == []


def test_main_controller_still_sends_normal_messages(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._send_message("plot a safe course")

    assert client.sent_messages == ["plot a safe course"]
    assert client.sent_payloads[0]["surface_mode"] == "ghost"
    assert client.sent_payloads[0]["active_module"] == "chartroom"
    assert client.sent_payloads[0]["response_profile"] == "ghost_compact"


def test_main_controller_sends_workspace_and_input_context(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    bridge.setSelectionContext(
        {
            "kind": "text",
            "value": "selected packaging notes",
            "preview": "selected packaging notes",
        }
    )
    bridge.setClipboardContext(
        {
            "kind": "url",
            "value": "https://example.com/packaging",
            "preview": "https://example.com/packaging",
        }
    )

    controller._send_message("use this in the workspace")

    assert client.sent_payloads[0]["workspace_context"]["module"] == "chartroom"
    assert client.sent_payloads[0]["input_context"]["selection"]["kind"] == "text"
    assert client.sent_payloads[0]["input_context"]["clipboard"]["kind"] == "url"


def test_main_controller_does_not_auto_restore_workspace_from_snapshot_on_startup(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._handle_snapshot(
        {
            "active_workspace": {
                "action": {
                    "type": "workspace_restore",
                    "module": "files",
                    "section": "opened-items",
                    "workspace": {
                        "workspaceId": "ws-packaging",
                        "name": "Packaging Workspace",
                        "topic": "packaging",
                        "summary": "Continue the portable packaging work.",
                    },
                    "items": [
                        {
                            "itemId": "item-readme",
                            "kind": "markdown",
                            "viewer": "markdown",
                            "title": "README.md",
                            "path": "C:/Stormhelm/README.md",
                        }
                    ],
                    "active_item_id": "item-readme",
                }
            }
        }
    )

    assert bridge.mode_value == "ghost"
    assert bridge.active_module_key == "chartroom"
    assert bridge.workspaceCanvas["title"] == "Chartroom"
    assert bridge.activeOpenedItem == {}


def test_main_controller_poll_is_single_flight_until_snapshot_returns(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller.poll()
    controller.poll()

    assert client.status_calls == 2
    assert client.snapshot_calls == 0


def test_main_controller_status_updates_do_not_request_snapshot(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller.poll()
    controller._handle_status(
        {
            "status_profile": "fast_status",
            "voice": {
                "voice_anchor": {
                    "state": "speaking",
                    "speaking_visual_active": True,
                },
                "live_playback_active": True,
            },
        }
    )

    assert client.status_calls == 1
    assert client.snapshot_calls == 0
    assert bridge.voiceState.get("voice_anchor_state") == "speaking"


def test_main_controller_requests_ghost_light_snapshot_after_chat(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._handle_chat(
        {
            "assistant_message": {
                "message_id": "assistant-ghost-light",
                "role": "assistant",
                "content": "Ready.",
                "created_at": "2026-04-20T18:10:00Z",
                "metadata": {
                    "bearing_title": "Ready",
                    "micro_response": "Ready.",
                    "full_response": "Ready.",
                },
            }
        }
    )

    assert client.snapshot_calls == 1
    assert client.snapshot_requests[0]["profile"] == "ghost_light"
    assert client.snapshot_requests[0]["event_limit"] <= 12


def test_main_controller_requests_deck_summary_only_when_deck_is_active(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)
    bridge.setMode("deck")

    controller._request_snapshot(force=True)

    assert client.snapshot_calls == 1
    assert client.snapshot_requests[0]["profile"] == "deck_summary"


def test_main_controller_chat_queues_one_refresh_behind_inflight_snapshot(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._request_snapshot()
    assert client.snapshot_calls == 1

    controller._handle_chat(
        {
            "assistant_message": {
                "message_id": "assistant-1",
                "role": "assistant",
                "content": "Ready.",
                "created_at": "2026-04-20T18:10:00Z",
                "metadata": {
                    "bearing_title": "Ready",
                    "micro_response": "Ready.",
                    "full_response": "Ready.",
                },
            }
        }
    )

    assert client.snapshot_calls == 1

    controller._handle_snapshot({})

    assert client.snapshot_calls == 2


def test_main_controller_snapshot_single_flight_when_explicitly_requested(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._request_snapshot()
    controller._request_snapshot()
    assert client.snapshot_calls == 1

    controller._handle_snapshot({})
    controller._request_snapshot()

    assert client.snapshot_calls == 2


def test_main_controller_start_requests_health_before_snapshot(monkeypatch, temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    monkeypatch.setattr("stormhelm.ui.controllers.main_controller.ensure_core_running", lambda config: False)

    controller.start()

    assert client.health_calls == 1
    assert client.snapshot_calls == 1
    assert client.started_streams == [{"session_id": "default", "cursor": None}]


def test_main_controller_requests_snapshot_when_live_event_needs_reconciliation(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._handle_stream_event(
        {
            "cursor": 14,
            "event_id": 14,
            "event_family": "job",
            "event_type": "job.completed",
            "severity": "info",
            "subsystem": "job_manager",
            "visibility_scope": "watch_surface",
            "message": "Workspace restore completed.",
            "payload": {"job_id": "job-14", "status": "completed"},
        }
    )

    assert client.snapshot_calls == 1


def test_main_controller_requests_snapshot_when_stream_gap_is_reported(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._handle_stream_gap(
        {
            "requested_cursor": 4,
            "earliest_cursor": 10,
            "latest_cursor": 14,
            "reason": "cursor_outside_retention_window",
        }
    )

    assert client.snapshot_calls == 1


def test_main_controller_opens_external_url_in_requested_browser(monkeypatch, temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)
    targeted_launches: list[tuple[str, str]] = []
    default_launches: list[str] = []

    monkeypatch.setattr(
        controller,
        "_open_in_browser_target",
        lambda browser_target, url, browser_command=None: targeted_launches.append((browser_target, url, browser_command)),
        raising=False,
    )
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", lambda url: default_launches.append(url.toString()))

    controller._handle_chat(
        {
            "actions": [
                {
                    "type": "open_external",
                    "kind": "url",
                    "url": "https://github.com/search?q=issue+templates",
                    "title": "GitHub search",
                    "browser_target": "firefox",
                }
            ],
            "assistant_message": {
                "message_id": "assistant-browser-1",
                "role": "assistant",
                "content": "Requested that GitHub search open externally.",
                "created_at": "2026-04-21T19:10:00Z",
                "metadata": {
                    "bearing_title": "GitHub search requested",
                    "micro_response": "Requested that GitHub search open externally.",
                    "full_response": "Requested that GitHub search open externally.",
                },
            },
        }
    )

    assert targeted_launches == [("firefox", "https://github.com/search?q=issue+templates", None)]
    assert default_launches == []


def test_main_controller_uses_explicit_browser_command_when_provided(monkeypatch, temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)
    launches: list[tuple[str, list[str]]] = []
    default_launches: list[str] = []

    monkeypatch.setattr(QtCore.QProcess, "startDetached", lambda command, arguments: launches.append((command, list(arguments))) or True)
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", lambda url: default_launches.append(url.toString()))

    controller._open_external(
        {
            "type": "open_external",
            "kind": "url",
            "url": "https://docs.python.org/",
            "title": "docs.python.org",
            "browser_target": "firefox",
            "browser_command": "C:/Program Files/Mozilla Firefox/firefox.exe",
        }
    )

    assert launches == [("C:/Program Files/Mozilla Firefox/firefox.exe", ["https://docs.python.org/"])]
    assert default_launches == []


def test_main_controller_falls_back_to_default_browser_when_explicit_target_launch_fails(monkeypatch, temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)
    launches: list[tuple[str, list[str]]] = []
    default_launches: list[str] = []

    monkeypatch.setattr(QtCore.QProcess, "startDetached", lambda command, arguments: launches.append((command, list(arguments))) or False)
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", lambda url: default_launches.append(url.toString()))

    controller._open_in_browser_target("firefox", "https://docs.python.org/")

    assert launches == [("firefox", ["https://docs.python.org/"])]
    assert default_launches == ["https://docs.python.org/"]
