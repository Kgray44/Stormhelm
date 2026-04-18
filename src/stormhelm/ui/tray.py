from __future__ import annotations

from pathlib import Path

from PySide6 import QtGui, QtWidgets

from stormhelm.config.models import AppConfig


def create_tray_icon(window: QtWidgets.QMainWindow, config: AppConfig) -> QtWidgets.QSystemTrayIcon:
    tray = QtWidgets.QSystemTrayIcon(window)
    tray.setIcon(_load_icon(window, config))
    tray.setToolTip("Stormhelm")

    menu = QtWidgets.QMenu(window)
    open_action = menu.addAction("Open Stormhelm")
    open_action.triggered.connect(lambda: _show_window(window))

    hide_action = menu.addAction("Hide Window")
    hide_action.triggered.connect(window.hide)

    menu.addSeparator()
    quit_action = menu.addAction("Quit UI")
    quit_action.triggered.connect(lambda: _quit_ui(window))

    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: _handle_tray_click(reason, window))
    tray.show()
    return tray


def _handle_tray_click(reason: QtWidgets.QSystemTrayIcon.ActivationReason, window: QtWidgets.QMainWindow) -> None:
    if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
        _show_window(window)


def _show_window(window: QtWidgets.QMainWindow) -> None:
    window.showNormal()
    window.raise_()
    window.activateWindow()


def _quit_ui(window: QtWidgets.QMainWindow) -> None:
    if hasattr(window, "set_hide_to_tray_enabled"):
        window.set_hide_to_tray_enabled(False)
    QtWidgets.QApplication.instance().quit()


def _load_icon(window: QtWidgets.QMainWindow, config: AppConfig) -> QtGui.QIcon:
    icon_path = Path(config.project_root) / "assets" / "icons" / "stormhelm.svg"
    if icon_path.exists():
        return QtGui.QIcon(str(icon_path))
    return window.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon)
