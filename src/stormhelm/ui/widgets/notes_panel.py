from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class NotesPanel(QtWidgets.QFrame):
    save_requested = QtCore.Signal(str, str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self._notes: dict[str, dict] = {}

        self.notes_list = QtWidgets.QListWidget()
        self.notes_list.currentItemChanged.connect(self._load_selected_note)

        self.title_edit = QtWidgets.QLineEdit()
        self.title_edit.setPlaceholderText("Note title")

        self.content_edit = QtWidgets.QPlainTextEdit()
        self.content_edit.setPlaceholderText("Write a note to local Stormhelm memory...")

        save_button = QtWidgets.QPushButton("Save Note")
        save_button.clicked.connect(self._save_note)

        editor_layout = QtWidgets.QVBoxLayout()
        editor_layout.addWidget(self.title_edit)
        editor_layout.addWidget(self.content_edit, 1)
        editor_layout.addWidget(save_button)

        split = QtWidgets.QSplitter()
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.notes_list)
        right = QtWidgets.QWidget()
        right.setLayout(editor_layout)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([180, 320])

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(split)

    def set_notes(self, notes: list[dict]) -> None:
        self._notes = {note["note_id"]: note for note in notes if "note_id" in note}
        self.notes_list.clear()
        for note in notes:
            item = QtWidgets.QListWidgetItem(note.get("title", "Untitled"))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, note.get("note_id"))
            self.notes_list.addItem(item)

    def clear_editor(self) -> None:
        self.title_edit.clear()
        self.content_edit.clear()

    def _load_selected_note(self, current: QtWidgets.QListWidgetItem | None, previous: QtWidgets.QListWidgetItem | None) -> None:
        del previous
        if current is None:
            return
        note_id = current.data(QtCore.Qt.ItemDataRole.UserRole)
        note = self._notes.get(note_id)
        if note is None:
            return
        self.title_edit.setText(str(note.get("title", "")))
        self.content_edit.setPlainText(str(note.get("content", "")))

    def _save_note(self) -> None:
        title = self.title_edit.text().strip()
        content = self.content_edit.toPlainText().strip()
        if not title or not content:
            return
        self.save_requested.emit(title, content)

