from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtGui, QtWidgets

from stormhelm.config.models import AppConfig
from stormhelm.ui.bridge import UiBridge


def create_tray_icon(
    bridge: UiBridge,
    config: AppConfig,
    *,
    request_backend_shutdown: Callable[[], None] | None = None,
) -> QtWidgets.QSystemTrayIcon:
    tray = QtWidgets.QSystemTrayIcon()
    tray.setIcon(_load_icon(config))
    tray.setToolTip(bridge.tray_tooltip_text())
    bridge.setTrayPresent(True)
    menu = _build_tray_menu(bridge, request_backend_shutdown=request_backend_shutdown)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: _handle_tray_click(reason, bridge))
    bridge.statusChanged.connect(lambda: tray.setToolTip(bridge.tray_tooltip_text()))
    bridge.visibilityChanged.connect(lambda: tray.setToolTip(bridge.tray_tooltip_text()))
    bridge.modeChanged.connect(lambda: tray.setToolTip(bridge.tray_tooltip_text()))
    tray.show()
    return tray


def _build_tray_menu(
    bridge: UiBridge,
    *,
    request_backend_shutdown: Callable[[], None] | None = None,
) -> QtWidgets.QMenu:
    menu = QtWidgets.QMenu()
    ghost_action = menu.addAction("Open Ghost Mode")
    ghost_action.triggered.connect(lambda: _show_window(bridge, "ghost"))

    deck_action = menu.addAction("Open Command Deck")
    deck_action.triggered.connect(lambda: _show_window(bridge, "deck"))

    menu.addSeparator()
    hide_action = menu.addAction("Fade To Dormant")
    hide_action.triggered.connect(bridge.hideWindow)

    menu.addSeparator()
    backend_action = menu.addAction("Quit Backend")
    if request_backend_shutdown is not None:
        backend_action.triggered.connect(request_backend_shutdown)
    else:
        backend_action.setEnabled(False)

    quit_action = menu.addAction("Quit UI")
    quit_action.triggered.connect(_quit_ui)
    return menu


def _handle_tray_click(reason: QtWidgets.QSystemTrayIcon.ActivationReason, bridge: UiBridge) -> None:
    if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
        _show_window(bridge, "ghost")


def _show_window(bridge: UiBridge, mode: str) -> None:
    bridge.setMode(mode)
    bridge.showWindow()


def _quit_ui() -> None:
    QtWidgets.QApplication.instance().quit()


def _load_icon(config: AppConfig) -> QtGui.QIcon:
    icon_path = config.runtime.assets_dir / "icons" / "stormhelm.svg"
    if icon_path.exists():
        return QtGui.QIcon(str(icon_path))
    style = QtWidgets.QApplication.instance().style()
    return style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)
