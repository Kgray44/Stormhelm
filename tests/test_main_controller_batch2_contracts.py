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
        input_context: dict[str, object] | None = None,
    ) -> None:
        del message, session_id, surface_mode, active_module, workspace_context, input_context

    def save_note(self, title: str, content: str, *, session_id: str = "default", workspace_id: str = "") -> None:
        del title, content, session_id, workspace_id


def test_main_controller_keeps_signal_steady_for_operational_errors(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._handle_health(
        {
            "status": "ok",
            "version": temp_config.version,
            "version_label": temp_config.version_label,
            "runtime_mode": "source",
        }
    )

    controller._handle_error("/jobs/job-42/cancel", "Unknown job id.")

    assert bridge.connection_state == "connected"
    assert bridge.statusLine == "Operation issue: /jobs/job-42/cancel: Unknown job id."


def test_main_controller_marks_transport_failures_as_signal_disrupted(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller._handle_health(
        {
            "status": "ok",
            "version": temp_config.version,
            "version_label": temp_config.version_label,
            "runtime_mode": "source",
        }
    )

    controller._handle_error("/chat/send", "Connection refused")

    assert bridge.connection_state == "disrupted"
    assert bridge.statusLine == "Signal disrupted: /chat/send: Connection refused"


def test_main_controller_snapshot_errors_release_single_flight_guard(temp_config) -> None:
    bridge = UiBridge(temp_config)
    client = DummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    controller.poll()
    assert client.snapshot_calls == 1

    controller._handle_error("/snapshot?session_id=default", "Connection refused")
    controller.poll()

    assert client.snapshot_calls == 2
    assert bridge.connection_state == "disrupted"
