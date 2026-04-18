from __future__ import annotations

from PySide6 import QtWidgets


class LogPanel(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.output)

    def append_events(self, events: list[dict]) -> None:
        for event in events:
            line = (
                f"[{event.get('timestamp', '')}] "
                f"{event.get('level', ''):<7} "
                f"{event.get('source', '')}: "
                f"{event.get('message', '')}"
            )
            self.output.appendPlainText(line)
        scrollbar = self.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

