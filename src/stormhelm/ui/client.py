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
    stream_event_received = QtCore.Signal(dict)
    stream_state_received = QtCore.Signal(dict)
    stream_gap_received = QtCore.Signal(dict)

    def __init__(self, base_url: str, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.base_url = base_url.rstrip("/")
        self.manager = QtNetwork.QNetworkAccessManager(self)
        self._stream_reply: QtNetwork.QNetworkReply | None = None
        self._stream_buffer = ""
        self._stream_requested_session_id = "default"
        self._stream_last_cursor: int | None = None
        self._stream_reconnect_attempt = 0
        self._stream_manual_stop = False
        self._stream_reconnect_timer = QtCore.QTimer(self)
        self._stream_reconnect_timer.setSingleShot(True)
        self._stream_reconnect_timer.timeout.connect(self._reconnect_event_stream)

    def fetch_health(self) -> None:
        self._send_json("GET", "/health", None, self.health_received.emit)

    @property
    def last_event_cursor(self) -> int | None:
        return self._stream_last_cursor

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

    def start_event_stream(self, *, session_id: str = "default", cursor: int | None = None) -> None:
        self._stream_requested_session_id = str(session_id or "default").strip() or "default"
        self._stream_manual_stop = False
        self._stream_reconnect_timer.stop()
        if cursor is not None:
            self._stream_last_cursor = max(0, int(cursor))
        self._stop_stream_reply()
        self._emit_client_stream_state("connecting", cursor=self._stream_last_cursor)
        self._open_event_stream(cursor=self._stream_last_cursor)

    def stop_event_stream(self) -> None:
        self._stream_manual_stop = True
        self._stream_reconnect_timer.stop()
        self._stop_stream_reply()
        self._emit_client_stream_state("stopped", cursor=self._stream_last_cursor)

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
        input_context: dict[str, object] | None = None,
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
                "input_context": input_context or {},
            },
            self.chat_received.emit,
        )

    def save_note(self, title: str, content: str, *, session_id: str = "default", workspace_id: str = "") -> None:
        self._send_json(
            "POST",
            "/notes",
            {
                "title": title,
                "content": content,
                "session_id": session_id,
                "workspace_id": workspace_id,
            },
            self.note_saved.emit,
        )

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

    def _open_event_stream(self, *, cursor: int | None) -> None:
        query = f"?session_id={self._stream_requested_session_id}"
        if cursor is not None:
            query += f"&cursor={max(0, int(cursor))}"
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(f"{self.base_url}/events/stream{query}"))
        request.setRawHeader(b"Accept", b"text/event-stream")
        request.setRawHeader(b"Cache-Control", b"no-cache")
        reply = self.manager.get(request)
        self._stream_reply = reply
        reply.readyRead.connect(lambda reply=reply: self._handle_stream_ready_read(reply))
        reply.finished.connect(lambda reply=reply: self._handle_stream_finished(reply))

    def _handle_stream_ready_read(self, reply: QtNetwork.QNetworkReply) -> None:
        if reply is not self._stream_reply:
            return
        self._consume_stream_chunk(bytes(reply.readAll()))

    def _handle_stream_finished(self, reply: QtNetwork.QNetworkReply) -> None:
        if reply is not self._stream_reply:
            return
        self._consume_stream_chunk(bytes(reply.readAll()))
        error = reply.error()
        error_text = reply.errorString()
        self._stream_reply = None
        reply.deleteLater()
        if self._stream_manual_stop:
            return
        self._schedule_stream_reconnect(error_text if error_text else "stream closed")

    def _schedule_stream_reconnect(self, reason: str) -> None:
        self._stream_reconnect_attempt += 1
        delay_ms = min(5_000, 750 * self._stream_reconnect_attempt)
        self._emit_client_stream_state(
            "reconnecting",
            cursor=self._stream_last_cursor,
            reason=reason,
            reconnect_attempt=self._stream_reconnect_attempt,
        )
        self._stream_reconnect_timer.start(delay_ms)

    def _reconnect_event_stream(self) -> None:
        if self._stream_manual_stop:
            return
        self._emit_client_stream_state(
            "connecting",
            cursor=self._stream_last_cursor,
            reconnect_attempt=self._stream_reconnect_attempt,
        )
        self._open_event_stream(cursor=self._stream_last_cursor)

    def _stop_stream_reply(self) -> None:
        reply = self._stream_reply
        self._stream_reply = None
        self._stream_buffer = ""
        if reply is None:
            return
        reply.abort()
        reply.deleteLater()

    def _consume_stream_chunk(self, raw: bytes) -> None:
        if not raw:
            return
        self._stream_buffer += raw.decode("utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")
        while "\n\n" in self._stream_buffer:
            block, self._stream_buffer = self._stream_buffer.split("\n\n", 1)
            self._process_stream_block(block)

    def _process_stream_bytes(self, raw: bytes) -> None:
        self._consume_stream_chunk(raw)

    def _process_stream_block(self, block: str) -> None:
        if not block.strip():
            return
        event_name = "message"
        data_lines: list[str] = []
        for raw_line in block.split("\n"):
            line = raw_line.strip("\n")
            if not line or line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.partition(":")[2].strip() or "message"
                continue
            if line.startswith("data:"):
                data_lines.append(line.partition(":")[2].lstrip())
        if not data_lines:
            return
        try:
            payload = json.loads("\n".join(data_lines))
        except Exception as error:
            self.error_occurred.emit("/events/stream", f"Malformed stream frame: {error}")
            return

        if event_name == "stormhelm.event":
            cursor = payload.get("cursor")
            if isinstance(cursor, int):
                self._stream_last_cursor = cursor
            self.stream_event_received.emit(payload)
            return

        if event_name == "stormhelm.replay_gap":
            self.stream_gap_received.emit(payload)
            return

        latest_cursor = payload.get("latest_cursor")
        if isinstance(latest_cursor, int) and self._stream_last_cursor is None:
            self._stream_last_cursor = latest_cursor
        if payload.get("phase") == "connected":
            self._stream_reconnect_attempt = 0
        self.stream_state_received.emit(payload)

    def _emit_client_stream_state(
        self,
        phase: str,
        *,
        cursor: int | None,
        reason: str = "",
        reconnect_attempt: int | None = None,
    ) -> None:
        self.stream_state_received.emit(
            {
                "phase": phase,
                "source": "client",
                "session_id": self._stream_requested_session_id,
                "cursor": cursor,
                "reason": reason,
                "reconnect_attempt": reconnect_attempt if reconnect_attempt is not None else self._stream_reconnect_attempt,
            }
        )

    def _handle_reply(
        self,
        reply: QtNetwork.QNetworkReply,
        callback: Callable[[dict], None],
        purpose: str,
    ) -> None:
        try:
            if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
                raw = bytes(reply.readAll()).decode("utf-8")
                self.error_occurred.emit(purpose, self._error_message_from_body(raw) or reply.errorString())
                return

            raw = bytes(reply.readAll()).decode("utf-8")
            payload = json.loads(raw) if raw else {}
            callback(payload)
        except Exception as error:  # pragma: no cover - defensive UI path
            self.error_occurred.emit(purpose, str(error))
        finally:
            reply.deleteLater()

    def _error_message_from_body(self, raw: str) -> str:
        if not raw:
            return ""
        try:
            payload = json.loads(raw)
        except Exception:
            return ""
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str):
                return detail.strip()
            if isinstance(detail, list):
                messages = [self._error_message_from_detail_item(item) for item in detail]
                return "; ".join(message for message in messages if message)
        return ""

    def _error_message_from_detail_item(self, item: object) -> str:
        if isinstance(item, str):
            return item.strip()
        if not isinstance(item, dict):
            return ""
        message = str(item.get("msg", "")).strip()
        location = item.get("loc")
        if not message:
            return ""
        if isinstance(location, list):
            path = ".".join(str(part).strip() for part in location if str(part).strip())
            if path:
                return f"{path}: {message}"
        return message
