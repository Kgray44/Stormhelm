from __future__ import annotations

import html

from PySide6 import QtCore, QtGui, QtWidgets


class ChatPanel(QtWidgets.QFrame):
    message_submitted = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)

        title = QtWidgets.QLabel("Assistant Chat")
        title.setStyleSheet("font-size: 15pt; font-weight: 600;")

        hint = QtWidgets.QLabel("Phase 1 commands: /time, /system, /echo, /read, /note, /shell")
        hint.setProperty("muted", True)

        self.history_view = QtWidgets.QTextBrowser()
        self.history_view.setOpenExternalLinks(False)

        self.input_box = QtWidgets.QPlainTextEdit()
        self.input_box.setPlaceholderText("Type a message or a safe Phase 1 command...")
        self.input_box.setFixedHeight(90)
        self.input_box.installEventFilter(self)

        self.send_button = QtWidgets.QPushButton("Send")
        self.send_button.clicked.connect(self._submit_message)

        footer = QtWidgets.QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.send_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.history_view, 1)
        layout.addWidget(self.input_box)
        layout.addLayout(footer)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.input_box and event.type() == QtCore.QEvent.Type.KeyPress:
            key_event = event  # type: ignore[assignment]
            if isinstance(key_event, QtGui.QKeyEvent):
                if key_event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter) and key_event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
                    self._submit_message()
                    return True
        return super().eventFilter(watched, event)

    def set_messages(self, messages: list[dict]) -> None:
        self.history_view.clear()
        for message in messages:
            self.append_message(message.get("role", "assistant"), message.get("content", ""), message.get("created_at", ""))

    def append_message(self, role: str, text: str, created_at: str = "") -> None:
        speaker = "You" if role == "user" else "Stormhelm"
        stamp = f"<span style='color:#89a1bd;font-size:8pt'>{html.escape(created_at)}</span>" if created_at else ""
        escaped = html.escape(text).replace("\n", "<br>")
        self.history_view.append(f"<div><b>{speaker}</b> {stamp}<br>{escaped}</div><hr>")
        scrollbar = self.history_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _submit_message(self) -> None:
        message = self.input_box.toPlainText().strip()
        if not message:
            return
        self.input_box.clear()
        self.message_submitted.emit(message)

