from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6 import QtCore, QtGui, QtWidgets

from stormhelm.ui.bridge import UiBridge


LOGGER = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312


def parse_windows_hotkey(shortcut: str) -> tuple[int, int]:
    parts = [part.strip().lower() for part in shortcut.split("+") if part.strip()]
    if not parts:
        raise ValueError("Hotkey shortcut cannot be empty.")

    modifiers = 0
    key_name = parts[-1]
    for part in parts[:-1]:
        if part in {"ctrl", "control"}:
            modifiers |= MOD_CONTROL
        elif part == "alt":
            modifiers |= MOD_ALT
        elif part == "shift":
            modifiers |= MOD_SHIFT
        elif part in {"win", "meta", "super"}:
            modifiers |= MOD_WIN
        else:
            raise ValueError(f"Unsupported hotkey modifier '{part}'.")

    if key_name == "space":
        return modifiers, 0x20
    if len(key_name) == 1 and key_name.isalpha():
        return modifiers, ord(key_name.upper())
    if len(key_name) == 1 and key_name.isdigit():
        return modifiers, ord(key_name)
    if key_name.startswith("f") and key_name[1:].isdigit():
        number = int(key_name[1:])
        if 1 <= number <= 24:
            return modifiers, 0x6F + number

    raise ValueError(f"Unsupported hotkey key '{key_name}'.")


class GhostInputProxy(QtWidgets.QWidget):
    def __init__(self, bridge: UiBridge, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self.setWindowFlag(QtCore.Qt.WindowType.Tool, True)
        self.setWindowFlag(QtCore.Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("background: transparent;")
        self.resize(2, 2)
        self.hide()
        self._bridge.ghostCaptureChanged.connect(self._sync_visibility)

    @QtCore.Slot()
    def beginCapture(self) -> None:
        self._bridge.beginGhostCapture()
        self._arm_capture_surface()

    def begin_capture(self) -> None:
        self.beginCapture()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        key = event.key()
        if key == QtCore.Qt.Key.Key_Escape:
            self._bridge.cancelGhostCapture()
            event.accept()
            return
        if key in {QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter} and not (event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier):
            self._bridge.submitGhostDraft()
            event.accept()
            return
        if key == QtCore.Qt.Key.Key_Backspace:
            self._bridge.backspaceGhostDraft()
            event.accept()
            return

        text = event.text()
        if text and not (event.modifiers() & (QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.AltModifier | QtCore.Qt.KeyboardModifier.MetaModifier)):
            self._bridge.appendGhostDraft(text)
            event.accept()
            return

        super().keyPressEvent(event)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        super().focusOutEvent(event)
        if self._bridge.ghost_capture_active:
            QtCore.QTimer.singleShot(0, self._reacquire_capture)

    def _screen(self) -> QtGui.QScreen | None:
        window = getattr(self._bridge, "_window", None)
        if isinstance(window, QtGui.QWindow) and window.screen() is not None:
            return window.screen()
        focus_window = QtGui.QGuiApplication.focusWindow()
        if focus_window is not None and focus_window.screen() is not None:
            return focus_window.screen()
        screen = QtGui.QGuiApplication.primaryScreen()
        return screen

    def _position_proxy(self) -> None:
        screen = self._screen()
        if screen is None:
            self.setGeometry(0, 0, 2, 2)
            return
        self.setGeometry(screen.geometry())

    def _arm_capture_surface(self) -> None:
        self._position_proxy()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(QtCore.Qt.FocusReason.ActiveWindowFocusReason)
        self.grabKeyboard()

    @QtCore.Slot()
    def _reacquire_capture(self) -> None:
        if self._bridge.ghost_capture_active:
            self._arm_capture_surface()

    @QtCore.Slot()
    def _sync_visibility(self) -> None:
        if self._bridge.ghost_capture_active:
            self._arm_capture_surface()
        else:
            self.releaseKeyboard()
            self.hide()


class WindowsHotkeyWindow(QtWidgets.QWidget):
    activated = QtCore.Signal()

    def __init__(self, shortcut: str, parent: QtWidgets.QWidget | None = None, *, register_hotkey: bool = True) -> None:
        super().__init__(parent)
        self._hotkey_id = 0x5348
        self._shortcut = shortcut
        self._enabled = not register_hotkey
        self._registered = False
        self._user32 = ctypes.windll.user32 if sys.platform.startswith("win") else None
        self.setWindowFlag(QtCore.Qt.WindowType.Tool, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.resize(1, 1)
        self.hide()

        if self._user32 is None or not register_hotkey:
            return

        modifiers, virtual_key = parse_windows_hotkey(shortcut)
        self.winId()
        if not self._user32.RegisterHotKey(int(self.winId()), self._hotkey_id, modifiers, virtual_key):
            raise RuntimeError(f"Stormhelm could not register global hotkey '{shortcut}'.")
        self._enabled = True
        self._registered = True

    @property
    def hotkey_id(self) -> int:
        return self._hotkey_id

    def _process_message(self, message_id: int, w_param: int) -> bool:
        if not self._enabled and self._user32 is not None:
            return False
        if message_id == WM_HOTKEY and w_param == self._hotkey_id:
            self.activated.emit()
            return True
        return False

    def nativeEvent(self, event_type: bytes | bytearray | memoryview | str, message: int) -> tuple[bool, int]:
        del event_type
        msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
        handled = self._process_message(int(msg.message), int(msg.wParam))
        return handled, 0

    def close(self) -> None:
        if not self._registered or self._user32 is None:
            super().close()
            return
        self._user32.UnregisterHotKey(int(self.winId()), self._hotkey_id)
        self._enabled = False
        self._registered = False
        super().close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # pragma: no cover - defensive cleanup
            LOGGER.debug("Ignoring hotkey listener cleanup failure.", exc_info=True)
