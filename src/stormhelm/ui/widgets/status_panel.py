from __future__ import annotations

from PySide6 import QtWidgets


class StatusPanel(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)

        title = QtWidgets.QLabel("Core Status")
        title.setStyleSheet("font-size: 12pt; font-weight: 600;")

        self.ui_version_value = QtWidgets.QLabel("-")
        self.core_version_value = QtWidgets.QLabel("-")
        self.connection_value = QtWidgets.QLabel("Disconnected")
        self.environment_value = QtWidgets.QLabel("-")
        self.runtime_mode_value = QtWidgets.QLabel("-")
        self.workers_value = QtWidgets.QLabel("-")
        self.jobs_value = QtWidgets.QLabel("-")
        self.data_dir_value = QtWidgets.QLabel("-")
        self.data_dir_value.setWordWrap(True)
        self.install_root_value = QtWidgets.QLabel("-")
        self.install_root_value.setWordWrap(True)

        form = QtWidgets.QFormLayout()
        form.addRow("UI Version", self.ui_version_value)
        form.addRow("Core Version", self.core_version_value)
        form.addRow("Connection", self.connection_value)
        form.addRow("Environment", self.environment_value)
        form.addRow("Runtime Mode", self.runtime_mode_value)
        form.addRow("Max Workers", self.workers_value)
        form.addRow("Recent Jobs", self.jobs_value)
        form.addRow("Data Dir", self.data_dir_value)
        form.addRow("Install Root", self.install_root_value)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(title)
        layout.addLayout(form)

    def set_local_identity(self, version_label: str) -> None:
        self.ui_version_value.setText(version_label)

    def set_snapshot(self, snapshot: dict, connected: bool = True) -> None:
        self.connection_value.setText("Connected" if connected else "Disconnected")
        self.core_version_value.setText(str(snapshot.get("version_label", snapshot.get("version", "-"))))
        self.environment_value.setText(str(snapshot.get("environment", "-")))
        self.runtime_mode_value.setText(str(snapshot.get("runtime_mode", "-")))
        self.workers_value.setText(str(snapshot.get("max_workers", "-")))
        self.jobs_value.setText(str(snapshot.get("recent_jobs", "-")))
        self.data_dir_value.setText(str(snapshot.get("data_dir", "-")))
        self.install_root_value.setText(str(snapshot.get("install_root", "-")))

    def set_connection_error(self, error: str) -> None:
        self.connection_value.setText(f"Error: {error}")
