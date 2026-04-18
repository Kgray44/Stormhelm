from __future__ import annotations

from PySide6 import QtWidgets


class ActivityPanel(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Job", "Tool", "Status", "Created", "Finished", "Summary"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.table)

    def set_jobs(self, jobs: list[dict]) -> None:
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            summary = ""
            result = job.get("result") or {}
            if isinstance(result, dict):
                summary = str(result.get("summary", ""))
            if not summary:
                summary = str(job.get("error", ""))

            values = [
                str(job.get("job_id", ""))[:8],
                str(job.get("tool_name", "")),
                str(job.get("status", "")),
                str(job.get("created_at", "")),
                str(job.get("finished_at", "")),
                summary,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QtWidgets.QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

