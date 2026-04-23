from __future__ import annotations

import os

from PySide6 import QtCore, QtTest, QtWidgets

from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.controllers.main_controller import MainController


def _ensure_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class LifecycleDummyClient(QtCore.QObject):
    error_occurred = QtCore.Signal(str, str)
    snapshot_received = QtCore.Signal(dict)
    health_received = QtCore.Signal(dict)
    chat_received = QtCore.Signal(dict)
    note_saved = QtCore.Signal(dict)
    stream_event_received = QtCore.Signal(dict)
    stream_state_received = QtCore.Signal(dict)
    stream_gap_received = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.health_calls = 0
        self.snapshot_calls = 0
        self.presence_reports: list[dict[str, object]] = []
        self.detach_calls: list[int | None] = []
        self.shutdown_backend_calls = 0

    def fetch_health(self) -> None:
        self.health_calls += 1

    def fetch_snapshot(self) -> None:
        self.snapshot_calls += 1

    def start_event_stream(self, *, session_id: str = "default", cursor: int | None = None) -> None:
        return None

    def stop_event_stream(self) -> None:
        return None

    def report_shell_presence(self, payload: dict[str, object]) -> None:
        self.presence_reports.append(dict(payload))

    def report_shell_detached(self, pid: int | None = None, *, sync: bool = False) -> None:
        self.detach_calls.append(pid)

    def shutdown_backend(self) -> None:
        self.shutdown_backend_calls += 1

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
        return None

    def save_note(self, title: str, content: str, *, session_id: str = "default", workspace_id: str = "") -> None:
        return None


def test_main_controller_reports_shell_presence_and_restarts_core_after_disconnect(monkeypatch, temp_config) -> None:
    app = _ensure_app()
    temp_config.lifecycle.auto_restart_core = True
    temp_config.lifecycle.max_core_restart_attempts = 1
    temp_config.lifecycle.core_restart_backoff_ms = 0

    bridge = UiBridge(temp_config)
    client = LifecycleDummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    restart_attempts: list[str] = []
    monkeypatch.setattr(
        "stormhelm.ui.controllers.main_controller.ensure_core_running",
        lambda config: restart_attempts.append("restart") or True,
    )

    controller._report_shell_presence()

    assert client.presence_reports[-1]["window_visible"] is False

    bridge.showWindow()
    app.processEvents()

    assert client.presence_reports[-1]["window_visible"] is True

    controller._core_online = True
    controller._handle_error("/health", "connection refused")
    QtTest.QTest.qWait(5)
    app.processEvents()

    assert restart_attempts == ["restart"]
    assert client.health_calls == 1


def test_main_controller_skips_core_restart_when_backend_hold_is_active(monkeypatch, temp_config) -> None:
    app = _ensure_app()
    temp_config.lifecycle.auto_restart_core = True
    temp_config.lifecycle.max_core_restart_attempts = 2
    temp_config.lifecycle.core_restart_backoff_ms = 0

    bridge = UiBridge(temp_config)
    bridge.apply_snapshot(
        {
            "status": {
                "version": temp_config.version,
                "version_label": temp_config.version_label,
                "environment": temp_config.environment,
                "runtime_mode": "packaged",
                "lifecycle": {
                    "install_state": {"install_mode": "installed", "startup_capable": True},
                    "startup_policy": {
                        "startup_enabled": True,
                        "registration_status": "registered",
                        "registered_core": True,
                        "registered_shell": False,
                    },
                    "runtime": {
                        "core_status": "held",
                        "shell_status": "detached",
                        "tray_status": "absent",
                        "connected_clients": 0,
                    },
                    "restart_policy": {
                        "hold_active": True,
                        "hold_reason": "Stormhelm observed repeated core failures in the recent restart window.",
                    },
                    "migration": {
                        "status": "hold",
                        "migration_required": True,
                        "hold_reason": "Stormhelm observed repeated core failures in the recent restart window.",
                    },
                    "bootstrap": {
                        "startup_allowed": False,
                        "lifecycle_hold_reason": "Stormhelm observed repeated core failures in the recent restart window.",
                        "onboarding_required": False,
                    },
                },
            }
        }
    )
    client = LifecycleDummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    restart_attempts: list[str] = []
    monkeypatch.setattr(
        "stormhelm.ui.controllers.main_controller.ensure_core_running",
        lambda config: restart_attempts.append("restart") or True,
    )

    controller._core_online = True
    controller._handle_error("/health", "connection refused")
    QtTest.QTest.qWait(5)
    app.processEvents()

    assert restart_attempts == []
    assert client.health_calls == 0
    assert "hold" in bridge.statusLine.lower()


def test_main_controller_manual_backend_shutdown_does_not_schedule_recovery(monkeypatch, temp_config) -> None:
    app = _ensure_app()
    temp_config.lifecycle.auto_restart_core = True
    temp_config.lifecycle.max_core_restart_attempts = 2
    temp_config.lifecycle.core_restart_backoff_ms = 0

    bridge = UiBridge(temp_config)
    client = LifecycleDummyClient()
    controller = MainController(config=temp_config, bridge=bridge, client=client)

    restart_attempts: list[str] = []
    monkeypatch.setattr(
        "stormhelm.ui.controllers.main_controller.ensure_core_running",
        lambda config: restart_attempts.append("restart") or True,
    )

    controller.request_backend_shutdown()
    controller._handle_error("/health", "connection refused")
    QtTest.QTest.qWait(5)
    app.processEvents()

    assert client.shutdown_backend_calls == 1
    assert restart_attempts == []
    assert "backend" in bridge.statusLine.lower()
