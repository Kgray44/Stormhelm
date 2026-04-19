from __future__ import annotations

from PySide6 import QtCore

from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.controllers.main_controller import MainController


class DummyClient(QtCore.QObject):
    error_occurred = QtCore.Signal(str, str)
    snapshot_received = QtCore.Signal(dict)
    health_received = QtCore.Signal(dict)
    chat_received = QtCore.Signal(dict)
    note_saved = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.sent_messages: list[str] = []
        self.sent_payloads: list[dict[str, str]] = []
        self.saved_notes: list[tuple[str, str]] = []
        self.snapshot_calls = 0

    def fetch_snapshot(self) -> None:
        self.snapshot_calls += 1

    def send_message(
        self,
        message: str,
        session_id: str = "default",
        *,
        surface_mode: str = "ghost",
        active_module: str = "chartroom",
        workspace_context: dict[str, object] | None = None,
    ) -> None:
        self.sent_messages.append(message)
        self.sent_payloads.append(
            {
                "message": message,
                "session_id": session_id,
                "surface_mode": surface_mode,
                "active_module": active_module,
                "workspace_context": workspace_context or {},
            }
        )

    def save_note(self, title: str, content: str) -> None:
        self.saved_notes.append((title, content))


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
