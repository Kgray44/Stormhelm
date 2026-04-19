from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.ghost_input import GhostInputProxy, WindowsHotkeyWindow, parse_windows_hotkey


def _ensure_app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_parse_windows_hotkey_supports_ctrl_space() -> None:
    modifiers, virtual_key = parse_windows_hotkey("Ctrl+Space")

    assert modifiers == 0x0002
    assert virtual_key == 0x20


def test_ghost_input_proxy_routes_keyboard_text_to_bridge(temp_config) -> None:
    _ensure_app()
    bridge = UiBridge(temp_config)
    sent_messages: list[str] = []
    bridge.sendMessageRequested.connect(sent_messages.append)
    proxy = GhostInputProxy(bridge)

    proxy.begin_capture()
    proxy.keyPressEvent(QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key_H, QtCore.Qt.NoModifier, "h"))
    proxy.keyPressEvent(QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key_I, QtCore.Qt.NoModifier, "i"))
    proxy.keyPressEvent(QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key_Backspace, QtCore.Qt.NoModifier))
    proxy.keyPressEvent(QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier))

    assert sent_messages == ["h"]
    assert bridge.ghostCaptureActive is False
    assert bridge.ghostDraftText == ""


def test_ghost_input_proxy_expands_to_screen_sized_capture_surface(temp_config) -> None:
    _ensure_app()
    bridge = UiBridge(temp_config)
    proxy = GhostInputProxy(bridge)

    proxy.begin_capture()
    geometry = proxy.frameGeometry()

    assert geometry.width() > 100
    assert geometry.height() > 100
    assert proxy.isVisible() is True


def test_ghost_input_proxy_escape_clears_then_dismisses(temp_config) -> None:
    _ensure_app()
    bridge = UiBridge(temp_config)
    proxy = GhostInputProxy(bridge)

    proxy.begin_capture()
    proxy.keyPressEvent(QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key_A, QtCore.Qt.NoModifier, "a"))
    proxy.keyPressEvent(QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier))

    assert bridge.ghostCaptureActive is True
    assert bridge.ghostDraftText == ""

    proxy.keyPressEvent(QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier))

    assert bridge.ghostCaptureActive is False


def test_windows_hotkey_window_dispatches_matching_hotkey_signal() -> None:
    _ensure_app()
    window = WindowsHotkeyWindow("Ctrl+Space", register_hotkey=False)
    activations: list[str] = []
    window.activated.connect(lambda: activations.append("hit"))

    assert window._process_message(0x0312, window.hotkey_id) is True
    assert activations == ["hit"]
    assert window._process_message(0x0312, window.hotkey_id + 1) is False
