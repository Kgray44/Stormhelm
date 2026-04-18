from __future__ import annotations

import json

from PySide6 import QtWidgets


class SettingsPanel(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.output)

    def set_settings(self, settings: dict) -> None:
        self.output.setPlainText(json.dumps(settings, indent=2))
