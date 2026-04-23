from __future__ import annotations

import os

from PySide6 import QtWidgets

from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.tray import _build_tray_menu


def _ensure_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_tray_menu_exposes_quit_backend_action(temp_config) -> None:
    _ensure_app()
    bridge = UiBridge(temp_config)
    backend_requests: list[str] = []
    menu = _build_tray_menu(
        bridge,
        request_backend_shutdown=lambda: backend_requests.append("quit-backend"),
    )

    actions = {action.text(): action for action in menu.actions() if action.text()}

    assert "Quit Backend" in actions
    actions["Quit Backend"].trigger()

    assert backend_requests == ["quit-backend"]
