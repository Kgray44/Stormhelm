from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtQml, QtWidgets, QtWebEngineQuick
from PySide6.QtQuickControls2 import QQuickStyle

from stormhelm.app.logging import configure_application_logging, install_exception_logging
from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.client import CoreApiClient
from stormhelm.ui.controllers.main_controller import MainController
from stormhelm.ui.ghost_input import GhostInputProxy, WindowsHotkeyWindow
from stormhelm.ui.tray import create_tray_icon
from stormhelm.ui.windows_effects import apply_stormhelm_material, apply_window_interaction_mode


def resolve_main_qml_path(config: AppConfig) -> Path:
    return config.runtime.assets_dir / "qml" / "Main.qml"


def _apply_window_behavior(window: QtGui.QWindow, bridge: UiBridge) -> None:
    ghost_mode = bridge.mode_value == "ghost"
    window.setFlag(QtCore.Qt.WindowType.FramelessWindowHint, True)
    window.setFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, ghost_mode)
    if hasattr(QtCore.Qt.WindowType, "WindowTransparentForInput"):
        window.setFlag(QtCore.Qt.WindowType.WindowTransparentForInput, ghost_mode)
    if hasattr(QtCore.Qt.WindowType, "WindowDoesNotAcceptFocus"):
        window.setFlag(QtCore.Qt.WindowType.WindowDoesNotAcceptFocus, ghost_mode)
    window.show()
    apply_window_interaction_mode(window, ghost_mode=ghost_mode)
    apply_stormhelm_material(window, ghost_mode=ghost_mode)


def run_ui(config: AppConfig | None = None) -> int:
    app_config = config or load_config()
    logger = configure_application_logging(app_config, "ui")
    install_exception_logging(logger, "ui")
    QQuickStyle.setStyle("Basic")
    QtWebEngineQuick.QtWebEngineQuick.initialize()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setApplicationName(app_config.app_name)
    app.setOrganizationName("Stormhelm")
    app.setQuitOnLastWindowClosed(False)
    logger.info("Launching Stormhelm UI in %s mode.", app_config.runtime.mode)

    bridge = UiBridge(app_config, parent=app)
    client = CoreApiClient(app_config.api_base_url, parent=bridge)
    controller = MainController(config=app_config, bridge=bridge, client=client)
    ghost_input_proxy = GhostInputProxy(bridge)
    hotkey_window: WindowsHotkeyWindow | None = None

    if QtCore.QSysInfo.productType() == "windows":
        try:
            hotkey_window = WindowsHotkeyWindow(app_config.ui.ghost_shortcut)
            hotkey_window.activated.connect(ghost_input_proxy.beginCapture)
            logger.info("Registered Ghost shortcut: %s", app_config.ui.ghost_shortcut)
        except Exception as exc:  # pragma: no cover - depends on local Windows hotkey state
            logger.warning("Could not register Ghost shortcut %s: %s", app_config.ui.ghost_shortcut, exc)

    engine = QtQml.QQmlApplicationEngine()
    engine.rootContext().setContextProperty("stormhelmBridge", bridge)
    engine.rootContext().setContextProperty("stormhelmGhostInput", ghost_input_proxy)
    qml_path = resolve_main_qml_path(app_config)
    if not qml_path.exists():
        raise RuntimeError(f"Stormhelm UI could not find its QML shell at '{qml_path}'.")
    engine.load(QtCore.QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        raise RuntimeError("Stormhelm UI failed to load the QML shell.")

    root = engine.rootObjects()[0]
    if isinstance(root, QtGui.QWindow):
        bridge.attachWindow(root)
        _apply_window_behavior(root, bridge)
        bridge.modeChanged.connect(lambda: _apply_window_behavior(root, bridge))

    tray_icon = create_tray_icon(bridge, app_config)
    controller.start()
    bridge.showWindow()
    exit_code = app.exec()
    if hotkey_window is not None:
        hotkey_window.close()
    ghost_input_proxy.hide()
    return exit_code
