from __future__ import annotations

from PySide6 import QtGui, QtWidgets

from stormhelm.ui.widgets.activity_panel import ActivityPanel
from stormhelm.ui.widgets.chat_panel import ChatPanel
from stormhelm.ui.widgets.log_panel import LogPanel
from stormhelm.ui.widgets.notes_panel import NotesPanel
from stormhelm.ui.widgets.settings_panel import SettingsPanel
from stormhelm.ui.widgets.status_panel import StatusPanel


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, *, version_label: str = "") -> None:
        super().__init__()
        self._hide_to_tray = True
        self.tray_icon: QtWidgets.QSystemTrayIcon | None = None

        title = "Stormhelm Control Shell"
        if version_label:
            title = f"{title} {version_label}"
        self.setWindowTitle(title)
        self.resize(1360, 860)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        self.chat_panel = ChatPanel()
        self.status_panel = StatusPanel()
        self.activity_panel = ActivityPanel()
        self.log_panel = LogPanel()
        self.notes_panel = NotesPanel()
        self.settings_panel = SettingsPanel()

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.activity_panel, "Tool Activity")
        tabs.addTab(self.log_panel, "Debug Log")
        tabs.addTab(self.notes_panel, "Memory")
        tabs.addTab(self.settings_panel, "Settings")

        right_column = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        right_layout.addWidget(self.status_panel)
        right_layout.addWidget(tabs, 1)

        split = QtWidgets.QSplitter()
        split.addWidget(self.chat_panel)
        split.addWidget(right_column)
        split.setSizes([720, 520])

        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(split)

        self.statusBar().showMessage("Stormhelm UI ready.")

    def set_hide_to_tray_enabled(self, enabled: bool) -> None:
        self._hide_to_tray = enabled

    def set_tray_icon(self, tray_icon: QtWidgets.QSystemTrayIcon) -> None:
        self.tray_icon = tray_icon

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._hide_to_tray and self.tray_icon is not None and self.tray_icon.isVisible():
            self.hide()
            self.statusBar().showMessage("Stormhelm UI hidden. Core remains available in the background.", 4000)
            event.ignore()
            return
        super().closeEvent(event)
