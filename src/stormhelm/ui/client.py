from __future__ import annotations

import json
from typing import Callable

from PySide6 import QtCore, QtNetwork


class CoreApiClient(QtCore.QObject):
    error_occurred = QtCore.Signal(str, str)
    snapshot_received = QtCore.Signal(dict)
    health_received = QtCore.Signal(dict)
    status_received = QtCore.Signal(dict)
    chat_received = QtCore.Signal(dict)
    history_received = QtCore.Signal(list)
    jobs_received = QtCore.Signal(list)
    events_received = QtCore.Signal(list)
    notes_received = QtCore.Signal(list)
    settings_received = QtCore.Signal(dict)
    note_saved = QtCore.Signal(dict)

    def __init__(self, base_url: str, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.base_url = base_url.rstrip("/")
        self.manager = QtNetwork.QNetworkAccessManager(self)

    def fetch_health(self) -> None:
        self._send_json("GET", "/health", None, self.health_received.emit)

    def fetch_status(self) -> None:
        self._send_json("GET", "/status", None, self.status_received.emit)

    def fetch_history(self, session_id: str = "default", limit: int = 100) -> None:
        self._send_json(
            "GET",
            f"/chat/history?session_id={session_id}&limit={limit}",
            None,
            lambda payload: self.history_received.emit(payload.get("messages", [])),
        )

    def fetch_jobs(self, limit: int = 50) -> None:
        self._send_json("GET", f"/jobs?limit={limit}", None, lambda payload: self.jobs_received.emit(payload.get("jobs", [])))

    def fetch_events(self, since_id: int = 0, limit: int = 100) -> None:
        self._send_json(
            "GET",
            f"/events?since_id={since_id}&limit={limit}",
            None,
            lambda payload: self.events_received.emit(payload.get("events", [])),
        )

    def fetch_notes(self, limit: int = 50) -> None:
        self._send_json("GET", f"/notes?limit={limit}", None, lambda payload: self.notes_received.emit(payload.get("notes", [])))

    def fetch_settings(self) -> None:
        self._send_json("GET", "/settings", None, self.settings_received.emit)

    def fetch_snapshot(
        self,
        *,
        session_id: str = "default",
        event_since_id: int = 0,
        event_limit: int = 100,
        job_limit: int = 50,
        note_limit: int = 50,
        history_limit: int = 100,
    ) -> None:
        self._send_json(
            "GET",
            (
                "/snapshot"
                f"?session_id={session_id}"
                f"&event_since_id={event_since_id}"
                f"&event_limit={event_limit}"
                f"&job_limit={job_limit}"
                f"&note_limit={note_limit}"
                f"&history_limit={history_limit}"
            ),
            None,
            self.snapshot_received.emit,
        )

    def send_message(
        self,
        message: str,
        session_id: str = "default",
        *,
        surface_mode: str = "ghost",
        active_module: str = "chartroom",
        workspace_context: dict[str, object] | None = None,
    ) -> None:
        self._send_json(
            "POST",
            "/chat/send",
            {
                "message": message,
                "session_id": session_id,
                "surface_mode": surface_mode,
                "active_module": active_module,
                "workspace_context": workspace_context or {},
            },
            self.chat_received.emit,
        )

    def save_note(self, title: str, content: str) -> None:
        self._send_json("POST", "/notes", {"title": title, "content": content}, self.note_saved.emit)

    def _send_json(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None,
        callback: Callable[[dict], None],
    ) -> None:
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(f"{self.base_url}{path}"))
        request.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, "application/json")

        if method == "GET":
            reply = self.manager.get(request)
        else:
            data = json.dumps(payload or {}).encode("utf-8")
            reply = self.manager.post(request, QtCore.QByteArray(data))

        reply.finished.connect(lambda reply=reply, cb=callback, purpose=path: self._handle_reply(reply, cb, purpose))

    def _handle_reply(
        self,
        reply: QtNetwork.QNetworkReply,
        callback: Callable[[dict], None],
        purpose: str,
    ) -> None:
        try:
            if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
                self.error_occurred.emit(purpose, reply.errorString())
                return

            raw = bytes(reply.readAll()).decode("utf-8")
            payload = json.loads(raw) if raw else {}
            callback(payload)
        except Exception as error:  # pragma: no cover - defensive UI path
            self.error_occurred.emit(purpose, str(error))
        finally:
            reply.deleteLater()
