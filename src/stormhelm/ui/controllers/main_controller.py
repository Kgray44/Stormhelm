from __future__ import annotations

from PySide6 import QtCore, QtGui

from stormhelm.app.launcher import ensure_core_running
from stormhelm.config.models import AppConfig
from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.client import CoreApiClient


class MainController(QtCore.QObject):
    def __init__(self, *, config: AppConfig, bridge: UiBridge, client: CoreApiClient) -> None:
        super().__init__(bridge)
        self.config = config
        self.bridge = bridge
        self.client = client
        self._core_online = False
        self._core_recovery_attempts = 0
        self._core_recovery_scheduled = False
        self._snapshot_in_flight = False
        self._snapshot_refresh_queued = False
        self._stream_last_cursor: int | None = None
        self._manual_backend_shutdown_requested = False

        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setInterval(self.config.ui.poll_interval_ms)
        self.refresh_timer.timeout.connect(self.poll)
        self.presence_timer = QtCore.QTimer(self)
        self.presence_timer.setInterval(max(1000, int(self.config.lifecycle.shell_heartbeat_interval_seconds * 1000)))
        self.presence_timer.timeout.connect(self._report_shell_presence)
        self.core_recovery_timer = QtCore.QTimer(self)
        self.core_recovery_timer.setSingleShot(True)
        self.core_recovery_timer.timeout.connect(self._attempt_core_recovery)

        self.bridge.sendMessageRequested.connect(self._send_message)
        self.bridge.saveNoteRequested.connect(self._save_note)
        self.bridge.modeChanged.connect(self._report_shell_presence)
        self.bridge.visibilityChanged.connect(self._report_shell_presence)

        self.client.error_occurred.connect(self._handle_error)
        self.client.snapshot_received.connect(self._handle_snapshot)
        self.client.health_received.connect(self._handle_health)
        self.client.chat_received.connect(self._handle_chat)
        self.client.note_saved.connect(self._handle_note_saved)
        if hasattr(self.client, "stream_event_received"):
            self.client.stream_event_received.connect(self._handle_stream_event)
        if hasattr(self.client, "stream_state_received"):
            self.client.stream_state_received.connect(self._handle_stream_state)
        if hasattr(self.client, "stream_gap_received"):
            self.client.stream_gap_received.connect(self._handle_stream_gap)

    def start(self) -> None:
        self.bridge.setHideToTrayOnClose(self.config.ui.hide_to_tray_on_close)
        self.bridge.set_local_identity(self.config.version_label)
        try:
            started = ensure_core_running(self.config)
            if not started:
                self.bridge.set_status_line("Standing watch.")
            self.client.fetch_health()
            if hasattr(self.client, "start_event_stream"):
                self.client.start_event_stream(session_id="default", cursor=self._stream_last_cursor)
        except Exception as error:
            self.bridge.set_connection_error(str(error))
            self.bridge.set_status_line(f"Core startup issue: {error}")

        self.poll()
        self.refresh_timer.start()
        self.presence_timer.start()
        self._report_shell_presence()
        application = QtCore.QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self._handle_app_about_to_quit, QtCore.Qt.ConnectionType.UniqueConnection)

    def poll(self) -> None:
        self._request_snapshot()

    def _handle_local_mode_command(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if normalized == "/deck":
            self.bridge.showWindow()
            self.bridge.setMode("deck")
            return True
        if normalized == "/ghost":
            self.bridge.showWindow()
            self.bridge.setMode("ghost")
            return True
        return False

    def _send_message(self, message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        if self._handle_local_mode_command(text):
            return
        self.client.send_message(
            text,
            surface_mode=self.bridge.mode_value,
            active_module=self.bridge.active_module_key,
            workspace_context=self.bridge.workspace_context_payload(),
            input_context=self.bridge.input_context_payload(),
        )

    def _save_note(self, title: str, content: str) -> None:
        workspace = self.bridge.workspace_context_payload().get("workspace", {})
        workspace_id = str(workspace.get("workspaceId", "")) if isinstance(workspace, dict) else ""
        self.client.save_note(title, content, session_id="default", workspace_id=workspace_id)

    def _handle_error(self, purpose: str, error: str) -> None:
        if str(purpose).startswith("/snapshot"):
            self._complete_snapshot_request()
        if self._is_connection_disruption(purpose, error):
            self._core_online = False
            if self._manual_backend_shutdown_requested:
                self.bridge.set_connection_error("Backend stopped from tray for local testing.")
                return
            self.bridge.set_connection_error(f"{purpose}: {error}")
            self._schedule_core_recovery(error)
            return
        self.bridge.set_operation_error(f"{purpose}: {error}")

    def _handle_health(self, payload: dict) -> None:
        if payload.get("status") == "ok" and self._manual_backend_shutdown_requested:
            self._manual_backend_shutdown_requested = False
        if payload.get("status") == "ok" and not self._core_online:
            self._core_online = True
            self._core_recovery_attempts = 0
            self._core_recovery_scheduled = False
            self.bridge.set_status_line("Standing watch.")
        self.bridge.apply_health(payload)

    def _handle_chat(self, payload: dict) -> None:
        self._apply_actions(payload.get("actions", []))
        self.bridge.apply_chat_result(payload)
        self._request_snapshot(force=True)

    def _handle_note_saved(self, payload: dict) -> None:
        self.bridge.note_saved(payload)
        self._request_snapshot(force=True)

    def _handle_snapshot(self, payload: dict) -> None:
        self._complete_snapshot_request()
        if self._manual_backend_shutdown_requested:
            self._manual_backend_shutdown_requested = False
            self._core_online = True
            self._core_recovery_attempts = 0
            self._core_recovery_scheduled = False
            self.bridge.set_status_line("Standing watch.")
        self.bridge.apply_snapshot(payload)
        self._stream_last_cursor = self._latest_cursor_from_snapshot(payload) or self._stream_last_cursor

    def _handle_stream_event(self, payload: dict) -> None:
        cursor = payload.get("cursor")
        if isinstance(cursor, int):
            self._stream_last_cursor = cursor
        self.bridge.apply_stream_event(payload)
        if self._event_requires_snapshot_reconciliation(payload):
            self._request_snapshot(force=True)

    def _handle_stream_state(self, payload: dict) -> None:
        cursor = payload.get("cursor")
        if isinstance(cursor, int):
            if self._stream_last_cursor is None:
                self._stream_last_cursor = cursor
            else:
                self._stream_last_cursor = max(self._stream_last_cursor, cursor)
        self.bridge.apply_stream_state(payload)

    def _handle_stream_gap(self, payload: dict) -> None:
        self.bridge.apply_stream_gap(payload)
        self._request_snapshot(force=True)

    def _apply_actions(self, actions: object) -> None:
        if not isinstance(actions, list):
            return
        for action in actions:
            if not isinstance(action, dict):
                continue
            if action.get("type") == "open_external":
                self._open_external(action)
                continue
            self.bridge.apply_action(action)

    def _open_external(self, action: dict) -> None:
        target = str(action.get("url") or action.get("path") or "").strip()
        if not target:
            return
        browser_target = str(action.get("browser_target", "")).strip().lower()
        browser_command = str(action.get("browser_command", "")).strip()
        if browser_target and str(action.get("kind", "url")).strip().lower() == "url":
            self._open_in_browser_target(browser_target, target, browser_command=browser_command or None)
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(target))

    def _open_in_browser_target(self, browser_target: str, url: str, *, browser_command: str | None = None) -> None:
        browser_commands = {
            "msedge": "msedge",
            "edge": "msedge",
            "microsoft edge": "msedge",
            "chrome": "chrome",
            "google chrome": "chrome",
            "firefox": "firefox",
            "brave": "brave",
            "opera": "opera",
            "vivaldi": "vivaldi",
        }
        command = browser_command or browser_commands.get((browser_target or "").strip().lower())
        if not command or not QtCore.QProcess.startDetached(command, [url]):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))

    def _request_snapshot(self, *, force: bool = False) -> None:
        if self._snapshot_in_flight:
            if force:
                self._snapshot_refresh_queued = True
            return
        self._snapshot_in_flight = True
        self.client.fetch_snapshot()

    def _complete_snapshot_request(self) -> None:
        self._snapshot_in_flight = False
        if not self._snapshot_refresh_queued:
            return
        self._snapshot_refresh_queued = False
        self._request_snapshot()

    def _is_connection_disruption(self, purpose: str, error: str) -> bool:
        normalized_purpose = str(purpose or "").strip().lower()
        if normalized_purpose.startswith("/snapshot") or normalized_purpose.startswith("/health"):
            return True
        normalized_error = str(error or "").strip().lower()
        disruption_markers = (
            "connection refused",
            "connection closed",
            "connection timed out",
            "host not found",
            "network unreachable",
            "timed out",
            "timeout",
            "remote host closed",
        )
        return any(marker in normalized_error for marker in disruption_markers)

    def _latest_cursor_from_snapshot(self, payload: dict) -> int | None:
        events = payload.get("events")
        if not isinstance(events, list):
            return None
        latest = max(
            (
                int(item.get("cursor") or item.get("event_id") or 0)
                for item in events
                if isinstance(item, dict) and isinstance(item.get("cursor") or item.get("event_id"), int)
            ),
            default=0,
        )
        return latest or None

    def _event_requires_snapshot_reconciliation(self, payload: dict) -> bool:
        visibility = str(payload.get("visibility_scope", "")).strip().lower()
        if visibility in {"watch_surface", "systems_surface", "deck_context", "ghost_hint", "operator_blocking"}:
            return True
        severity = str(payload.get("severity", "")).strip().lower()
        return severity in {"warning", "error", "critical"}

    def _report_shell_presence(self) -> None:
        if not hasattr(self.client, "report_shell_presence"):
            return
        report = self.bridge.shell_presence_payload()
        self.client.report_shell_presence(report)

    def request_backend_shutdown(self) -> None:
        if not hasattr(self.client, "shutdown_backend"):
            self.bridge.set_operation_error("Backend shutdown is unavailable in this shell build.")
            return
        self._manual_backend_shutdown_requested = True
        self._core_online = False
        self._core_recovery_scheduled = False
        self.core_recovery_timer.stop()
        self.bridge.set_status_line("Backend shutdown requested from the tray.")
        self.client.shutdown_backend()

    def _handle_app_about_to_quit(self) -> None:
        if hasattr(self.client, "report_shell_detached"):
            self.client.report_shell_detached(self.bridge.shell_presence_payload().get("pid"), sync=True)
        if hasattr(self.client, "stop_event_stream"):
            self.client.stop_event_stream()

    def _schedule_core_recovery(self, error: str) -> None:
        if not self.config.lifecycle.auto_restart_core:
            return
        hold_summary = ""
        if hasattr(self.bridge, "lifecycle_restart_hold_summary"):
            hold_summary = str(self.bridge.lifecycle_restart_hold_summary() or "").strip()
        if hold_summary:
            self.bridge.set_status_line(f"Core restart hold: {hold_summary}")
            return
        if self._core_recovery_scheduled:
            return
        if self._core_recovery_attempts >= self.config.lifecycle.max_core_restart_attempts:
            self.bridge.set_status_line(f"Core restart hold: {error}")
            return
        self._core_recovery_scheduled = True
        self.core_recovery_timer.start(max(0, int(self.config.lifecycle.core_restart_backoff_ms)))

    def _attempt_core_recovery(self) -> None:
        self._core_recovery_scheduled = False
        self._core_recovery_attempts += 1
        try:
            ensure_core_running(self.config)
        except Exception as error:
            self.bridge.set_status_line(f"Core restart issue: {error}")
            if self._core_recovery_attempts < self.config.lifecycle.max_core_restart_attempts:
                self._schedule_core_recovery(str(error))
            return
        if hasattr(self.client, "fetch_health"):
            self.client.fetch_health()
        self._request_snapshot(force=True)
        if hasattr(self.client, "start_event_stream"):
            self.client.start_event_stream(session_id="default", cursor=self._stream_last_cursor)
