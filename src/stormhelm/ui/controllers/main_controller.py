from __future__ import annotations

from PySide6 import QtCore

from stormhelm.app.launcher import ensure_core_running
from stormhelm.config.models import AppConfig
from stormhelm.ui.client import CoreApiClient
from stormhelm.ui.main_window import MainWindow


class MainController(QtCore.QObject):
    def __init__(self, *, config: AppConfig, window: MainWindow, client: CoreApiClient) -> None:
        super().__init__(window)
        self.config = config
        self.window = window
        self.client = client
        self.last_event_id = 0
        self._core_online = False

        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setInterval(self.config.ui.poll_interval_ms)
        self.refresh_timer.timeout.connect(self.poll)

        self.window.chat_panel.message_submitted.connect(self._send_message)
        self.window.notes_panel.save_requested.connect(self._save_note)

        self.client.error_occurred.connect(self._handle_error)
        self.client.health_received.connect(self._handle_health)
        self.client.status_received.connect(self._handle_status)
        self.client.chat_received.connect(self._handle_chat)
        self.client.history_received.connect(self.window.chat_panel.set_messages)
        self.client.jobs_received.connect(self.window.activity_panel.set_jobs)
        self.client.events_received.connect(self._handle_events)
        self.client.notes_received.connect(self.window.notes_panel.set_notes)
        self.client.settings_received.connect(self.window.settings_panel.set_settings)
        self.client.note_saved.connect(self._handle_note_saved)

    def start(self) -> None:
        self.window.set_hide_to_tray_enabled(self.config.ui.hide_to_tray_on_close)
        try:
            started = ensure_core_running(self.config)
            self.window.statusBar().showMessage(
                "Stormhelm core launched." if started else "Connected to running Stormhelm core.",
                4000,
            )
        except Exception as error:
            self.window.status_panel.set_connection_error(str(error))
            self.window.statusBar().showMessage(f"Core startup issue: {error}", 6000)

        self.poll()
        self.refresh_timer.start()

    def poll(self) -> None:
        self.client.fetch_health()
        self.client.fetch_status()
        self.client.fetch_jobs()
        self.client.fetch_events(self.last_event_id)
        self.client.fetch_notes()
        self.client.fetch_settings()
        self.client.fetch_history()

    def _send_message(self, message: str) -> None:
        self.window.statusBar().showMessage("Sending message to Stormhelm core...", 2000)
        self.client.send_message(message)

    def _save_note(self, title: str, content: str) -> None:
        self.window.statusBar().showMessage("Saving note...", 2000)
        self.client.save_note(title, content)

    def _handle_error(self, purpose: str, error: str) -> None:
        self._core_online = False
        self.window.status_panel.set_connection_error(error)
        self.window.statusBar().showMessage(f"{purpose}: {error}", 5000)

    def _handle_health(self, payload: dict) -> None:
        if payload.get("status") == "ok" and not self._core_online:
            self._core_online = True
            self.window.statusBar().showMessage("Stormhelm core online.", 2000)

    def _handle_status(self, payload: dict) -> None:
        self.window.status_panel.set_snapshot(payload, connected=True)

    def _handle_chat(self, payload: dict) -> None:
        user_message = payload.get("user_message")
        assistant_message = payload.get("assistant_message")
        if isinstance(user_message, dict):
            self.window.chat_panel.append_message(
                str(user_message.get("role", "user")),
                str(user_message.get("content", "")),
                str(user_message.get("created_at", "")),
            )
        if isinstance(assistant_message, dict):
            self.window.chat_panel.append_message(
                str(assistant_message.get("role", "assistant")),
                str(assistant_message.get("content", "")),
                str(assistant_message.get("created_at", "")),
            )
        self.window.statusBar().showMessage("Assistant response received.", 3000)
        self.client.fetch_jobs()
        self.client.fetch_events(self.last_event_id)

    def _handle_events(self, events: list[dict]) -> None:
        if not events:
            return
        self.last_event_id = max(self.last_event_id, max(int(event.get("event_id", 0)) for event in events))
        self.window.log_panel.append_events(events)

    def _handle_note_saved(self, payload: dict) -> None:
        self.window.statusBar().showMessage(f"Saved note '{payload.get('title', 'Untitled')}'.", 3000)
        self.window.notes_panel.clear_editor()
        self.client.fetch_notes()
