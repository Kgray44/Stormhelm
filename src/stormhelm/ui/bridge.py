from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6 import QtCore, QtGui

from stormhelm.config.models import AppConfig


VISIBLE_MODES = {"ghost", "deck"}
VOICE_STATES = {"idle", "listening", "thinking", "acting", "speaking", "warning"}


class UiBridge(QtCore.QObject):
    sendMessageRequested = QtCore.Signal(str)
    saveNoteRequested = QtCore.Signal(str, str)

    modeChanged = QtCore.Signal()
    assistantStateChanged = QtCore.Signal()
    ghostCaptureChanged = QtCore.Signal()
    statusChanged = QtCore.Signal()
    collectionsChanged = QtCore.Signal()
    visibilityChanged = QtCore.Signal()

    def __init__(self, config: AppConfig, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._window: QtGui.QWindow | None = None
        self._mode = "ghost"
        self._assistant_state = "idle"
        self._active_module_key = "chartroom"
        self._active_workspace_section_key = "overview"
        self._hide_to_tray_on_close = config.ui.hide_to_tray_on_close
        self._connected = False
        self._ui_version_label = config.version_label
        self._core_version_label = "Awaiting signal"
        self._runtime_mode_label = config.runtime.mode
        self._environment_label = config.environment
        self._connection_state = "connecting"
        self._status_line = "Standing watch."
        self._local_time_label = self._format_time()
        self._health: dict[str, Any] = {}
        self._status: dict[str, Any] = {}
        self._history: list[dict[str, Any]] = []
        self._jobs: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._notes: list[dict[str, Any]] = []
        self._settings: dict[str, Any] = {}
        self._command_rail_items: list[dict[str, Any]] = []
        self._workspace_rail_items: list[dict[str, Any]] = []
        self._workspace_sections: list[dict[str, Any]] = []
        self._workspace_canvas: dict[str, Any] = {}
        self._workspace_focus: dict[str, Any] = {}
        self._opened_items: list[dict[str, Any]] = []
        self._active_opened_item_id: str | None = None
        self._ghost_messages: list[dict[str, Any]] = []
        self._context_cards: list[dict[str, Any]] = []
        self._ghost_corner_readouts: list[dict[str, Any]] = []
        self._deck_modules: list[dict[str, Any]] = []
        self._active_deck_module: dict[str, Any] = {}
        self._deck_support_modules: list[dict[str, Any]] = []
        self._status_strip_items: list[dict[str, Any]] = []
        self._ghost_capture_active = False
        self._ghost_draft_text = ""
        self._pending_activity: str | None = None

        self._clock_timer = QtCore.QTimer(self)
        self._clock_timer.setInterval(30_000)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start()

        self._rebuild_surface_models()

    @property
    def mode_value(self) -> str:
        return self._mode

    @property
    def assistant_state_value(self) -> str:
        return self._assistant_state

    @property
    def active_module_key(self) -> str:
        return self._active_module_key

    @property
    def command_rail_items(self) -> list[dict[str, Any]]:
        return list(self._command_rail_items)

    @property
    def connection_state(self) -> str:
        return self._connection_state

    @property
    def ghost_messages(self) -> list[dict[str, Any]]:
        return list(self._ghost_messages)

    @property
    def context_cards(self) -> list[dict[str, Any]]:
        return list(self._context_cards)

    @property
    def deck_modules(self) -> list[dict[str, Any]]:
        return list(self._deck_modules)

    @property
    def ghost_corner_readouts(self) -> list[dict[str, Any]]:
        return list(self._ghost_corner_readouts)

    @property
    def workspace_rail_items(self) -> list[dict[str, Any]]:
        return list(self._workspace_rail_items)

    @property
    def active_deck_module(self) -> dict[str, Any]:
        return dict(self._active_deck_module)

    @property
    def deck_support_modules(self) -> list[dict[str, Any]]:
        return list(self._deck_support_modules)

    @property
    def workspace_sections(self) -> list[dict[str, Any]]:
        return list(self._workspace_sections)

    @property
    def workspace_canvas(self) -> dict[str, Any]:
        return dict(self._workspace_canvas)

    @property
    def opened_items(self) -> list[dict[str, Any]]:
        return list(self._opened_items)

    @property
    def active_opened_item(self) -> dict[str, Any]:
        return dict(self._get_active_opened_item())

    @property
    def ghost_capture_active(self) -> bool:
        return self._ghost_capture_active

    @property
    def ghost_draft_text(self) -> str:
        return self._ghost_draft_text

    @QtCore.Property(str, notify=modeChanged)
    def mode(self) -> str:
        return self._mode

    @QtCore.Property(str, notify=assistantStateChanged)
    def assistantState(self) -> str:
        return self._assistant_state

    @QtCore.Property(str, notify=statusChanged)
    def windowTitle(self) -> str:
        mode_label = "Ghost Mode" if self._mode == "ghost" else "Command Deck"
        return f"Stormhelm | {mode_label}"

    @QtCore.Property(str, notify=statusChanged)
    def modeTitle(self) -> str:
        return "Ghost Mode" if self._mode == "ghost" else "Command Deck"

    @QtCore.Property(str, notify=statusChanged)
    def modeSubtitle(self) -> str:
        if self._mode == "ghost":
            return "A spectral command veil for fast bearings and light orchestration."
        if self._active_module_key == "helm":
            return "Helm holds Stormhelm behavior, presence, and control surfaces."
        if self._active_module_key == "systems":
            return "Systems keeps runtime, diagnostics, and technical state on watch."
        return "An immersive chartroom for deeper work with Stormhelm."

    @QtCore.Property(str, notify=statusChanged)
    def statusLine(self) -> str:
        return self._status_line

    @QtCore.Property(str, notify=statusChanged)
    def connectionLabel(self) -> str:
        labels = {
            "connecting": "Acquiring signal",
            "connected": "Signal steady",
            "disrupted": "Signal disrupted",
        }
        return labels.get(self._connection_state, self._connection_state.title())

    @QtCore.Property(str, notify=statusChanged)
    def uiVersionLabel(self) -> str:
        return self._ui_version_label

    @QtCore.Property(str, notify=statusChanged)
    def coreVersionLabel(self) -> str:
        return self._core_version_label

    @QtCore.Property(str, notify=statusChanged)
    def runtimeModeLabel(self) -> str:
        return self._runtime_mode_label

    @QtCore.Property(str, notify=statusChanged)
    def environmentLabel(self) -> str:
        return self._environment_label

    @QtCore.Property(str, notify=statusChanged)
    def localTimeLabel(self) -> str:
        return self._local_time_label

    @QtCore.Property(bool, notify=visibilityChanged)
    def hideToTrayOnClose(self) -> bool:
        return self._hide_to_tray_on_close

    @QtCore.Property(bool, notify=ghostCaptureChanged)
    def ghostCaptureActive(self) -> bool:
        return self._ghost_capture_active

    @QtCore.Property(str, notify=ghostCaptureChanged)
    def ghostDraftText(self) -> str:
        return self._ghost_draft_text

    @QtCore.Property(str, notify=statusChanged)
    def ghostShortcutLabel(self) -> str:
        return self.config.ui.ghost_shortcut

    @QtCore.Property(str, notify=statusChanged)
    def ghostInputHint(self) -> str:
        if self._ghost_capture_active:
            return "Enter sends · Esc clears"
        return f"{self.config.ui.ghost_shortcut} to signal the helm"

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def messages(self) -> list[dict[str, Any]]:
        return list(self._history)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def ghostMessages(self) -> list[dict[str, Any]]:
        return list(self._ghost_messages)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def contextCards(self) -> list[dict[str, Any]]:
        return list(self._context_cards)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def deckModules(self) -> list[dict[str, Any]]:
        return list(self._deck_modules)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def ghostCornerReadouts(self) -> list[dict[str, Any]]:
        return list(self._ghost_corner_readouts)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def workspaceRailItems(self) -> list[dict[str, Any]]:
        return list(self._workspace_rail_items)

    @QtCore.Property("QVariantMap", notify=collectionsChanged)
    def activeDeckModule(self) -> dict[str, Any]:
        return dict(self._active_deck_module)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def deckSupportModules(self) -> list[dict[str, Any]]:
        return list(self._deck_support_modules)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def workspaceSections(self) -> list[dict[str, Any]]:
        return list(self._workspace_sections)

    @QtCore.Property("QVariantMap", notify=collectionsChanged)
    def workspaceCanvas(self) -> dict[str, Any]:
        return dict(self._workspace_canvas)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def openedItems(self) -> list[dict[str, Any]]:
        return list(self._opened_items)

    @QtCore.Property("QVariantMap", notify=collectionsChanged)
    def activeOpenedItem(self) -> dict[str, Any]:
        return dict(self._get_active_opened_item())

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def commandRailItems(self) -> list[dict[str, Any]]:
        return list(self._command_rail_items)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def statusStripItems(self) -> list[dict[str, Any]]:
        return list(self._status_strip_items)

    @QtCore.Slot(QtGui.QWindow)
    def attachWindow(self, window: QtGui.QWindow) -> None:
        self._window = window

    @QtCore.Slot(str)
    def setMode(self, mode: str) -> None:
        normalized = (mode or "").strip().lower()
        if normalized not in VISIBLE_MODES or normalized == self._mode:
            return
        self._mode = normalized
        if normalized == "ghost":
            self._status_line = "Ghost Mode holding steady." if not self._ghost_capture_active else "Signal the helm."
        else:
            self._ghost_capture_active = False
            self._ghost_draft_text = ""
            self._status_line = "Command Deck unfolded."
        self.modeChanged.emit()
        self.ghostCaptureChanged.emit()
        self.statusChanged.emit()

    @QtCore.Slot()
    def toggleMode(self) -> None:
        self.setMode("deck" if self._mode == "ghost" else "ghost")

    @QtCore.Slot(str)
    def activateModule(self, key: str) -> None:
        normalized = (key or "").strip().lower()
        if not normalized:
            return
        self._active_module_key = normalized
        self._active_workspace_section_key = self._default_workspace_section_key(normalized)
        self._rebuild_surface_models()
        self.statusChanged.emit()
        self.collectionsChanged.emit()

    @QtCore.Slot(bool)
    def setComposerFocus(self, focused: bool) -> None:
        if self._pending_activity is not None or self._ghost_capture_active:
            return
        self._set_assistant_state("listening" if focused else "idle")

    @QtCore.Slot()
    def beginGhostCapture(self) -> None:
        if self._mode != "ghost":
            self.setMode("ghost")
        self.showWindow()
        self._ghost_capture_active = True
        self._status_line = "Signal the helm."
        if self._pending_activity is None:
            self._set_assistant_state("listening")
        self.ghostCaptureChanged.emit()
        self.statusChanged.emit()
        self.collectionsChanged.emit()

    @QtCore.Slot()
    def cancelGhostCapture(self) -> None:
        if self._ghost_draft_text:
            self._ghost_draft_text = ""
            self._status_line = "Signal cleared."
            self.ghostCaptureChanged.emit()
            self.statusChanged.emit()
            return
        if not self._ghost_capture_active:
            return
        self._ghost_capture_active = False
        if self._pending_activity is None:
            self._set_assistant_state("idle")
        self._status_line = "Ghost Mode holding steady."
        self.ghostCaptureChanged.emit()
        self.statusChanged.emit()
        if self._mode == "ghost":
            self.hideWindow()

    @QtCore.Slot()
    def backspaceGhostDraft(self) -> None:
        if not self._ghost_capture_active or not self._ghost_draft_text:
            return
        self._ghost_draft_text = self._ghost_draft_text[:-1]
        self.ghostCaptureChanged.emit()

    @QtCore.Slot(str)
    def appendGhostDraft(self, text: str) -> None:
        if not text:
            return
        if not self._ghost_capture_active:
            self.beginGhostCapture()
        self._ghost_draft_text += text
        self.ghostCaptureChanged.emit()

    @QtCore.Slot()
    def submitGhostDraft(self) -> None:
        draft = self._ghost_draft_text.strip()
        if not draft:
            self.cancelGhostCapture()
            return
        self._ghost_capture_active = False
        self._ghost_draft_text = ""
        self.ghostCaptureChanged.emit()
        self.sendMessage(draft)

    @QtCore.Slot(str)
    def activateWorkspaceSection(self, key: str) -> None:
        normalized = (key or "").strip().lower()
        if not normalized or normalized == self._active_workspace_section_key:
            return
        self._active_workspace_section_key = normalized
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    @QtCore.Slot(str)
    def activateOpenedItem(self, item_id: str) -> None:
        normalized = (item_id or "").strip()
        if not normalized or normalized == self._active_opened_item_id:
            return
        if not any(item.get("itemId") == normalized for item in self._opened_items):
            return
        self._active_opened_item_id = normalized
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    @QtCore.Slot(str)
    def closeOpenedItem(self, item_id: str) -> None:
        normalized = (item_id or "").strip()
        if not normalized:
            return
        self._opened_items = [item for item in self._opened_items if item.get("itemId") != normalized]
        if self._active_opened_item_id == normalized:
            self._active_opened_item_id = self._opened_items[0]["itemId"] if self._opened_items else None
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    @QtCore.Slot(str)
    def sendMessage(self, message: str) -> None:
        text = (message or "").strip()
        if not text:
            return
        if self._ghost_capture_active:
            self._ghost_capture_active = False
            self._ghost_draft_text = ""
            self.ghostCaptureChanged.emit()
        self._pending_activity = "chat"
        self._set_assistant_state("thinking")
        self._status_line = "Plotting a response."
        self.statusChanged.emit()
        self.sendMessageRequested.emit(text)

    @QtCore.Slot(str, str)
    def saveNote(self, title: str, content: str) -> None:
        note_title = (title or "").strip()
        note_content = (content or "").strip()
        if not note_title or not note_content:
            return
        self._pending_activity = "note"
        self._set_assistant_state("acting")
        self._status_line = "Marking the logbook."
        self.statusChanged.emit()
        self.saveNoteRequested.emit(note_title, note_content)

    @QtCore.Slot(result=bool)
    def handleCloseRequest(self) -> bool:
        if not self._hide_to_tray_on_close:
            return False
        self.hideWindow()
        self._status_line = "Stormhelm faded back to dormant watch."
        self.statusChanged.emit()
        return True

    @QtCore.Slot(bool)
    def setHideToTrayOnClose(self, enabled: bool) -> None:
        self._hide_to_tray_on_close = enabled
        self.visibilityChanged.emit()

    @QtCore.Slot()
    def showWindow(self) -> None:
        if self._window is None:
            return
        self._window.show()
        self._window.raise_()
        if self._mode != "ghost":
            self._window.requestActivate()

    @QtCore.Slot()
    def hideWindow(self) -> None:
        if self._window is not None:
            self._window.hide()

    def set_local_identity(self, version_label: str) -> None:
        self._ui_version_label = version_label
        self.statusChanged.emit()

    def set_connection_error(self, error: str) -> None:
        self._connected = False
        self._connection_state = "disrupted"
        self._pending_activity = None
        self._set_assistant_state("warning")
        self._status_line = f"Signal disrupted: {error}"
        self.statusChanged.emit()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def set_status_line(self, text: str) -> None:
        self._status_line = text
        self.statusChanged.emit()

    def apply_health(self, payload: dict[str, Any]) -> None:
        self._health = dict(payload)
        self._connected = payload.get("status") == "ok"
        self._connection_state = "connected" if self._connected else "connecting"
        self._core_version_label = str(payload.get("version_label", payload.get("version", self._core_version_label)))
        runtime_mode = payload.get("runtime_mode")
        if runtime_mode:
            self._runtime_mode_label = str(runtime_mode)
        if self._connected and self._pending_activity is None and self._assistant_state == "warning":
            self._set_assistant_state("idle")
        self.statusChanged.emit()

    def apply_status(self, payload: dict[str, Any]) -> None:
        self._status = dict(payload)
        self._core_version_label = str(payload.get("version_label", payload.get("version", self._core_version_label)))
        self._runtime_mode_label = str(payload.get("runtime_mode", self._runtime_mode_label))
        self._environment_label = str(payload.get("environment", self._environment_label))
        self.statusChanged.emit()

    def apply_snapshot(self, payload: dict[str, Any]) -> None:
        health = payload.get("health")
        if isinstance(health, dict):
            self.apply_health(health)

        status = payload.get("status")
        if isinstance(status, dict):
            self.apply_status(status)

        history = payload.get("history")
        if isinstance(history, list):
            self._history = [self._normalize_message(item) for item in history if isinstance(item, dict)]

        jobs = payload.get("jobs")
        if isinstance(jobs, list):
            self._jobs = [dict(item) for item in jobs if isinstance(item, dict)]

        events = payload.get("events")
        if isinstance(events, list):
            self._events = [dict(item) for item in events if isinstance(item, dict)]

        notes = payload.get("notes")
        if isinstance(notes, list):
            self._notes = [dict(item) for item in notes if isinstance(item, dict)]

        settings = payload.get("settings")
        if isinstance(settings, dict):
            self._settings = dict(settings)

        if self._pending_activity == "chat":
            self._pending_activity = None
            self._set_assistant_state("idle")
            if self._history:
                self._status_line = str(self._history[-1].get("content", "Bearing logged."))
        elif self._pending_activity == "note":
            self._pending_activity = None
            self._set_assistant_state("idle")
            self._status_line = "Logbook entry secured."

        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def apply_chat_result(self, payload: dict[str, Any]) -> None:
        user_message = payload.get("user_message")
        assistant_message = payload.get("assistant_message")
        additions: list[dict[str, Any]] = []
        if isinstance(user_message, dict):
            additions.append(self._normalize_message(user_message))
        if isinstance(assistant_message, dict):
            additions.append(self._normalize_message(assistant_message))
            self._status_line = str(assistant_message.get("content", "Bearing logged."))

        if additions:
            self._history.extend(additions)
        self._pending_activity = None
        self._set_assistant_state("idle")
        self._rebuild_surface_models()
        self.statusChanged.emit()
        self.collectionsChanged.emit()

    def note_saved(self, payload: dict[str, Any]) -> None:
        del payload
        self._pending_activity = None
        self._set_assistant_state("idle")
        self._status_line = "Logbook entry secured."
        self._rebuild_surface_models()
        self.statusChanged.emit()
        self.collectionsChanged.emit()

    def apply_action(self, action: dict[str, Any]) -> None:
        action_type = str(action.get("type", "")).strip().lower()
        if action_type == "workspace_restore":
            self._apply_workspace_restore(action)
            return
        if action_type != "workspace_open":
            return

        module = str(action.get("module", self._active_module_key)).strip().lower() or self._active_module_key
        section = str(action.get("section", self._default_workspace_section_key(module))).strip().lower()
        item = action.get("item")
        if not isinstance(item, dict):
            return

        normalized_item = dict(item)
        normalized_item.setdefault("itemId", str(uuid4()))
        normalized_item.setdefault("kind", "text")
        normalized_item.setdefault("viewer", normalized_item.get("kind", "text"))
        normalized_item.setdefault("title", "Untitled")
        normalized_item.setdefault("subtitle", "")
        normalized_item["module"] = module

        self._upsert_opened_item(normalized_item)
        self._active_module_key = module
        self._active_workspace_section_key = section or self._default_workspace_section_key(module)
        self._mode = "deck"
        self._status_line = f"Holding {normalized_item['title']} in the Deck."
        self.modeChanged.emit()
        self.statusChanged.emit()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def workspace_context_payload(self) -> dict[str, Any]:
        return {
            "workspace": dict(self._workspace_focus),
            "module": self._active_module_key,
            "section": self._active_workspace_section_key,
            "opened_items": [dict(item) for item in self._opened_items[:8]],
            "active_item": self._get_active_opened_item(),
        }

    def _apply_workspace_restore(self, action: dict[str, Any]) -> None:
        module = str(action.get("module", "chartroom")).strip().lower() or "chartroom"
        section = str(action.get("section", self._default_workspace_section_key(module))).strip().lower()
        workspace = action.get("workspace")
        if isinstance(workspace, dict):
            self._workspace_focus = dict(workspace)
        items = action.get("items", [])
        self._opened_items = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized_item = dict(item)
                normalized_item.setdefault("itemId", str(uuid4()))
                normalized_item.setdefault("kind", "text")
                normalized_item.setdefault("viewer", normalized_item.get("kind", "text"))
                normalized_item.setdefault("title", "Untitled")
                normalized_item.setdefault("subtitle", "")
                normalized_item["module"] = str(normalized_item.get("module", module)).strip().lower() or module
                self._opened_items.append(normalized_item)
        active_item_id = str(action.get("active_item_id", "")).strip()
        if active_item_id and any(item.get("itemId") == active_item_id for item in self._opened_items):
            self._active_opened_item_id = active_item_id
        else:
            self._active_opened_item_id = self._opened_items[0]["itemId"] if self._opened_items else None
        self._active_module_key = module
        self._active_workspace_section_key = section or self._default_workspace_section_key(module)
        self._mode = "deck"
        workspace_name = str(self._workspace_focus.get("name", "workspace")).strip() or "workspace"
        self._status_line = f"Holding {workspace_name} in the Deck."
        self.modeChanged.emit()
        self.statusChanged.emit()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def _rebuild_surface_models(self) -> None:
        self._ghost_messages = self._history[-3:]
        self._context_cards = self._build_context_cards()
        self._command_rail_items = self._build_command_rail_items()
        self._workspace_sections = self._build_workspace_sections()
        self._workspace_rail_items = self._build_workspace_rail_items()
        self._workspace_canvas = self._build_workspace_canvas()
        self._deck_modules = self._build_deck_modules()
        self._active_deck_module = self._deck_modules[0] if self._deck_modules else self._build_module(self._active_module_key)
        self._deck_support_modules = self._deck_modules[1:]
        self._ghost_corner_readouts = self._build_ghost_corner_readouts()
        self._status_strip_items = self._build_status_strip_items()

    def _build_context_cards(self) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        latest_job = self._jobs[0] if self._jobs else None
        if latest_job is not None:
            summary = ""
            result = latest_job.get("result")
            if isinstance(result, dict):
                summary = str(result.get("summary", ""))
            if not summary:
                summary = str(latest_job.get("error", "")) or "Awaiting further bearings."
            cards.append(
                {
                    "title": self._module_label(str(latest_job.get("tool_name", "action"))),
                    "subtitle": str(latest_job.get("status", "pending")).title(),
                    "body": summary,
                }
            )

        latest_event = self._events[0] if self._events else None
        if latest_event is not None and len(cards) < 2:
            cards.append(
                {
                    "title": "Signals",
                    "subtitle": str(latest_event.get("level", "INFO")).title(),
                    "body": str(latest_event.get("message", "No recent signal.")),
                }
            )

        if self._notes and len(cards) < 2:
            latest_note = self._notes[0]
            cards.append(
                {
                    "title": "Logbook",
                    "subtitle": f"{len(self._notes)} entries",
                    "body": str(latest_note.get("content", ""))[:120],
                }
            )
        return cards

    def _build_command_rail_items(self) -> list[dict[str, Any]]:
        keys = [
            ("chartroom", "Chartroom"),
            ("helm", "Helm"),
            ("logbook", "Logbook"),
            ("watch", "Watch"),
            ("signals", "Signals"),
            ("systems", "Systems"),
            ("files", "Files"),
            ("browser", "Browser"),
            ("visual-context", "Visual Context"),
        ]
        return [
            {
                "key": key,
                "label": label,
                "active": key == self._active_module_key,
            }
            for key, label in keys
        ]

    def _build_workspace_rail_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for section in self._workspace_sections:
            items.append(
                {
                    "key": section["key"],
                    "label": section["label"],
                    "active": section["key"] == self._active_workspace_section_key,
                    "eyebrow": section["eyebrow"],
                    "summary": section["summary"],
                }
            )
        return items

    def _build_workspace_sections(self) -> list[dict[str, Any]]:
        mapping: dict[str, list[tuple[str, str, str]]] = {
            "chartroom": [
                ("overview", "Overview", "Workspace"),
                ("active-thread", "Active Thread", "Command"),
                ("opened-items", "Opened Items", "Canvas"),
                ("references", "References", "Research"),
                ("findings", "Findings", "Research"),
                ("session", "Session", "Context"),
                ("tasks", "Tasks", "Plan"),
            ],
            "helm": [
                ("overview", "Overview", "Helm"),
                ("presence", "Presence", "Behavior"),
                ("hotkeys", "Hotkeys", "Input"),
                ("behavior", "Behavior", "Assistant"),
                ("safety", "Safety", "Control"),
                ("storage", "Storage", "Runtime"),
            ],
            "logbook": [
                ("overview", "Overview", "Memory"),
                ("notes", "Notes", "Entries"),
                ("drafts", "Drafts", "Writing"),
                ("timeline", "Timeline", "History"),
                ("memory", "Memory", "Recall"),
            ],
            "watch": [
                ("overview", "Overview", "Activity"),
                ("active-jobs", "Active Jobs", "Queue"),
                ("timeline", "Timeline", "History"),
                ("tools", "Tools", "Operations"),
                ("queue", "Queue", "Dispatch"),
            ],
            "signals": [
                ("overview", "Overview", "Signals"),
                ("live", "Live Signal", "Telemetry"),
                ("alerts", "Alerts", "Warnings"),
                ("timeline", "Timeline", "History"),
                ("sources", "Sources", "Origin"),
            ],
            "systems": [
                ("overview", "Overview", "Systems"),
                ("runtime", "Runtime", "Core"),
                ("diagnostics", "Diagnostics", "Watch"),
                ("jobs", "Jobs", "Workers"),
                ("logs", "Logs", "Trace"),
                ("network", "Network", "Connection"),
            ],
            "files": [
                ("overview", "Overview", "Files"),
                ("opened-items", "Opened Items", "Working Set"),
                ("working-set", "Working Set", "Canvas"),
                ("recent", "Recent Files", "History"),
                ("handoff", "Hand-off", "External"),
            ],
            "browser": [
                ("overview", "Overview", "Browser"),
                ("references", "References", "Research"),
                ("sources", "Sources", "Evidence"),
                ("open-pages", "Open Pages", "Context"),
                ("handoff", "Hand-off", "External"),
            ],
            "visual-context": [
                ("overview", "Overview", "Visual"),
                ("focus-surface", "Focus Surface", "Context"),
                ("findings", "Findings", "Analysis"),
                ("guidance", "Guidance", "Steps"),
                ("trace", "Trace", "Evidence"),
            ],
        }
        sections = mapping.get(self._active_module_key, mapping["chartroom"])
        return [
            {
                "key": key,
                "label": label,
                "eyebrow": eyebrow,
                "summary": self._workspace_section_summary(self._active_module_key, key),
            }
            for key, label, eyebrow in sections
        ]

    def _build_workspace_canvas(self) -> dict[str, Any]:
        return {
            "key": self._active_module_key,
            "sectionKey": self._active_workspace_section_key,
            "eyebrow": self._workspace_canvas_eyebrow(),
            "title": self._workspace_canvas_title(),
            "summary": self._workspace_canvas_summary(),
            "body": self._workspace_canvas_body(),
            "chips": self._workspace_canvas_chips(),
            "columns": self._workspace_canvas_columns(),
            "openedItems": list(self._opened_items),
            "activeItem": self._get_active_opened_item(),
        }

    def _active_module_label(self) -> str:
        labels = {
            "chartroom": "Chartroom",
            "helm": "Helm",
            "logbook": "Logbook",
            "watch": "Watch",
            "signals": "Signals",
            "systems": "Systems",
            "files": "Files",
            "browser": "Browser",
            "visual-context": "Visual Context",
        }
        return labels.get(self._active_module_key, self._active_module_key.replace("-", " ").title())

    def _default_workspace_section_key(self, module_key: str) -> str:
        defaults = {
            "chartroom": "overview",
            "helm": "overview",
            "logbook": "notes",
            "watch": "active-jobs",
            "signals": "live",
            "systems": "runtime",
            "files": "opened-items",
            "browser": "references",
            "visual-context": "focus-surface",
        }
        return defaults.get(module_key, "overview")

    def _workspace_section_summary(self, module_key: str, section_key: str) -> str:
        summaries: dict[str, dict[str, str]] = {
            "chartroom": {
                "overview": "Stormhelm's current command field and active bearings.",
                "active-thread": "The live exchange with Stormhelm and the current line of work.",
                "opened-items": "Relevant materials gathered into the present workspace.",
                "references": "External context and source material held nearby.",
                "findings": "Conclusions, observations, and extracted signal worth keeping.",
                "session": "The current task posture, mode, and retained context.",
                "tasks": "Open tasks and the next bearings to plot.",
            },
            "helm": {
                "overview": "User-facing behavior, presence, and configuration direction.",
                "presence": "How Stormhelm manifests across dormant, Ghost, and Deck states.",
                "hotkeys": "Keyboard summon and signaling affordances.",
                "behavior": "Assistant stance, deck behavior, and interaction preferences.",
                "safety": "Permission boundaries and action control policy.",
                "storage": "Where settings, notes, logs, and runtime state live.",
            },
            "logbook": {
                "overview": "Local memory surfaces and working notes.",
                "notes": "Recent notes and draft fragments held close to the mission.",
                "drafts": "Structured writing-in-progress and uncommitted fragments.",
                "timeline": "Chronological memory and recent note activity.",
                "memory": "Longer-horizon memory direction and future recall structure.",
            },
            "watch": {
                "overview": "Operational activity and recent work at a glance.",
                "active-jobs": "Tasks currently in flight or recently completed.",
                "timeline": "The sequence of recent actions and outcomes.",
                "tools": "Which tools have been active and how they resolved.",
                "queue": "Dispatch posture, worker pressure, and pending work.",
            },
            "signals": {
                "overview": "Signal health, events, and recent communications.",
                "live": "The freshest operational signal crossing the helm.",
                "alerts": "Warnings, interruptions, or unusual conditions.",
                "timeline": "Recent events in chronological order.",
                "sources": "Where signals are originating and how they are flowing.",
            },
            "systems": {
                "overview": "Technical runtime posture and supporting diagnostics.",
                "runtime": "Core state, versioning, and packaged/source runtime bearings.",
                "diagnostics": "The most relevant health and troubleshooting signal.",
                "jobs": "Worker pool behavior and tool execution pressure.",
                "logs": "Recent trace, logging destinations, and inspection paths.",
                "network": "Local API reachability and signal continuity.",
            },
            "files": {
                "overview": "Curated file surfaces for the current mission.",
                "opened-items": "The most relevant files already gathered into view.",
                "working-set": "The current set of files under active attention.",
                "recent": "Recently touched documents and safe reads.",
                "handoff": "Where Stormhelm should defer to native Windows tooling.",
            },
            "browser": {
                "overview": "Research and references kept close without becoming a browser clone.",
                "references": "Primary research bearings and cited material.",
                "sources": "Source provenance and evidence trails.",
                "open-pages": "Pages the workspace is conceptually holding onto.",
                "handoff": "Where the default browser remains the preferred surface.",
            },
            "visual-context": {
                "overview": "Reserved tactical space for future visual awareness.",
                "focus-surface": "The place where relevant on-screen context will later appear.",
                "findings": "Extracted observations from visual context.",
                "guidance": "Next-step assistance shaped by what Stormhelm can see later.",
                "trace": "Evidence and visual breadcrumbs for later phases.",
            },
        }
        module_summaries = summaries.get(module_key, summaries["chartroom"])
        return module_summaries.get(section_key, "A restrained supporting surface within the living field.")

    def _workspace_canvas_eyebrow(self) -> str:
        return next(
            (section["eyebrow"] for section in self._workspace_sections if section["key"] == self._active_workspace_section_key),
            self._active_module_label(),
        )

    def _workspace_canvas_title(self) -> str:
        active_item = self._get_active_opened_item()
        workspace_named_section = self._active_workspace_section_key in {"opened-items", "open-pages", "references", "working-set"}
        if workspace_named_section and self._workspace_focus.get("name"):
            return str(self._workspace_focus.get("name"))
        if active_item and workspace_named_section:
            return str(active_item.get("title", self._active_module_label()))
        if self._active_workspace_section_key == "overview":
            if self._workspace_focus.get("name"):
                return str(self._workspace_focus.get("name"))
            return self._active_module_label()
        return self._workspace_section_label(self._active_workspace_section_key)

    def _workspace_canvas_summary(self) -> str:
        active_item = self._get_active_opened_item()
        workspace_named_section = self._active_workspace_section_key in {"opened-items", "open-pages", "references", "working-set"}
        if workspace_named_section and self._workspace_focus.get("summary"):
            return str(self._workspace_focus.get("summary"))
        if active_item and workspace_named_section:
            subtitle = str(active_item.get("subtitle", "")).strip()
            if subtitle:
                return subtitle
        if self._active_workspace_section_key == "overview" and self._workspace_focus.get("summary"):
            return str(self._workspace_focus.get("summary"))
        return self._workspace_section_summary(self._active_module_key, self._active_workspace_section_key)

    def _workspace_canvas_body(self) -> str:
        active_item = self._get_active_opened_item()
        workspace_named_section = self._active_workspace_section_key in {"opened-items", "open-pages", "references", "working-set"}
        if workspace_named_section and self._workspace_focus.get("name"):
            active_title = str(active_item.get("title", "active bearings")).strip() if active_item else "active bearings"
            return f"Holding {active_title} inside the {self._workspace_focus.get('name')} workspace."
        if active_item and workspace_named_section:
            kind = str(active_item.get("kind", "item")).replace("-", " ")
            return f"Holding a {kind} surface inside the current Stormhelm workspace."
        if self._active_module_key == "helm":
            return (
                "Helm is Stormhelm's integrated settings direction: behavior, presence, shortcuts, "
                "and operator-facing control live here. The tray stays quick and light; advanced "
                "control remains backed by config files."
            )
        if self._active_module_key == "systems":
            return (
                "Systems is intentionally technical. It keeps runtime bearings, diagnostics, logs, "
                "and worker health visible without turning the deck into an admin console."
            )
        if self._active_module_key == "chartroom":
            return (
                "The Chartroom holds the main collaboration flow, but it no longer owns the whole "
                "deck. Stormhelm's command spine supports the work while the broader canvas carries it."
            )
        if self._active_module_key == "logbook":
            return "The Logbook keeps notes and memory close to the mission without taking over the deck."
        if self._active_module_key == "watch":
            return "Watch keeps live operational work visible in a restrained, supporting posture."
        if self._active_module_key == "signals":
            return "Signals surfaces the most meaningful recent signal without becoming a debug wall."
        if self._active_module_key == "files":
            return "Files remains a scaffold for curated working sets and native hand-offs in later phases."
        if self._active_module_key == "browser":
            return "Browser remains a future research surface. For now, Stormhelm prepares the structure."
        return "Visual Context remains a reserved tactical surface until screen-aware behavior arrives later."

    def _workspace_canvas_chips(self) -> list[dict[str, str]]:
        active_item = self._get_active_opened_item()
        workspace_named_section = self._active_workspace_section_key in {"opened-items", "open-pages", "references", "working-set"}
        if active_item and workspace_named_section:
            chips = [
                {"label": "Viewer", "value": str(active_item.get("viewer", active_item.get("kind", "item"))).title()},
                {"label": "Opened Items", "value": str(len(self._opened_items))},
            ]
            if self._workspace_focus.get("topic"):
                chips.insert(0, {"label": "Workspace", "value": str(self._workspace_focus.get("topic")).title()})
            if active_item.get("path"):
                chips.append({"label": "Path", "value": str(active_item.get("path"))})
            elif active_item.get("url"):
                chips.append({"label": "Source", "value": str(active_item.get("url"))})
            return chips
        if self._active_module_key == "helm":
            return [
                {"label": "Ghost Shortcut", "value": self.config.ui.ghost_shortcut},
                {"label": "Tray Close", "value": "Dormant fade" if self._hide_to_tray_on_close else "Window close"},
                {"label": "Config Fallback", "value": "portable.toml / user.toml"},
            ]
        if self._active_module_key == "systems":
            return [
                {"label": "Runtime", "value": self._runtime_mode_label.title()},
                {"label": "Signal", "value": self.connectionLabel},
                {"label": "Workers", "value": str(self._status.get("max_workers", self.config.concurrency.max_workers))},
            ]
        if self._active_module_key == "signals":
            return [
                {"label": "Mode", "value": self.modeTitle},
                {"label": "Connection", "value": self.connectionLabel},
                {"label": "Events", "value": str(len(self._events))},
            ]
        if self._active_module_key == "watch":
            return [
                {"label": "Recent Jobs", "value": str(len(self._jobs))},
                {"label": "Workers", "value": str(self.config.concurrency.max_workers)},
                {"label": "Timeout", "value": f"{self.config.concurrency.default_job_timeout_seconds:g}s"},
            ]
        if self._active_module_key == "logbook":
            return [
                {"label": "Entries", "value": str(len(self._notes))},
                {"label": "Mode", "value": self.modeTitle},
                {"label": "Memory", "value": "Local-first"},
            ]
        return [
            {"label": "Mode", "value": self.modeTitle},
            {"label": "State", "value": self._assistant_state.title()},
            {"label": "Signal", "value": self.connectionLabel},
        ]

    def _workspace_canvas_columns(self) -> list[dict[str, Any]]:
        if self._active_module_key == "helm":
            return [
                self._workspace_column(
                    "Presence",
                    "How Stormhelm manifests across modes.",
                    [
                        {"primary": "Ghost Mode", "secondary": "Spectral overlay", "detail": "Mouse click-through, keyboard signaling."},
                        {"primary": "Command Deck", "secondary": "Deeper field", "detail": "A stronger workspace layer unfolding from the anchor."},
                        {"primary": "Dormant", "secondary": "Background ready", "detail": "Tray-first and silent until summoned."},
                    ],
                ),
                self._workspace_column(
                    "Control",
                    "Behavior and quick-setting direction.",
                    [
                        {"primary": "Ghost Shortcut", "secondary": self.config.ui.ghost_shortcut, "detail": "Summons Ghost capture from anywhere."},
                        {"primary": "Close Behavior", "secondary": "Fade to tray" if self._hide_to_tray_on_close else "Exit window", "detail": "Quick controls stay in the tray."},
                        {"primary": "Safety", "secondary": "Always gated", "detail": "No unrestricted action surfaces are added here."},
                    ],
                ),
            ]

        if self._active_module_key == "systems":
            allowed_dirs = self._settings.get("safety", {}).get("allowed_read_dirs", []) if isinstance(self._settings, dict) else []
            return [
                self._workspace_column(
                    "Runtime",
                    "Technical bearings for the core service.",
                    [
                        {"primary": "Version", "secondary": self._core_version_label, "detail": self._environment_label.title()},
                        {"primary": "Runtime Mode", "secondary": self._runtime_mode_label.title(), "detail": self.modeTitle},
                        {"primary": "Connection", "secondary": self.connectionLabel, "detail": self._status_line},
                    ],
                ),
                self._workspace_column(
                    "Diagnostics",
                    "Worker and policy state.",
                    [
                        {"primary": "Workers", "secondary": str(self._status.get("max_workers", self.config.concurrency.max_workers)), "detail": f"Recent jobs: {len(self._jobs)}"},
                        {"primary": "Allowed Reads", "secondary": str(len(allowed_dirs)), "detail": ", ".join(str(path) for path in allowed_dirs[:2]) or "No allowlist loaded."},
                        {"primary": "Logs", "secondary": str(self.config.storage.logs_dir.name if hasattr(self.config, 'storage') else 'logs'), "detail": str(self.config.storage.logs_dir)},
                    ],
                ),
            ]

        if self._active_module_key == "logbook":
            note_entries = [
                {
                    "primary": str(note.get("title", "Untitled")),
                    "secondary": self._short_time(str(note.get("created_at", ""))),
                    "detail": str(note.get("content", ""))[:120],
                }
                for note in self._notes[:4]
            ] or [{"primary": "No entries yet", "secondary": "Logbook", "detail": "Write a note from the side module to seed local memory."}]
            return [
                self._workspace_column("Entries", "Recent notes held close.", note_entries),
                self._workspace_column(
                    "Direction",
                    "Where memory surfaces are headed.",
                    [
                        {"primary": "Drafts", "secondary": "Reserved", "detail": "Light drafting surfaces will live here."},
                        {"primary": "Timeline", "secondary": "Reserved", "detail": "Chronological memory review remains a future pass."},
                        {"primary": "Recall", "secondary": "Local-first", "detail": "Prepared for richer retrieval later without claiming it now."},
                    ],
                ),
            ]

        if self._active_module_key == "watch":
            job_entries = [
                {
                    "primary": self._module_label(str(job.get("tool_name", "Tool"))),
                    "secondary": str(job.get("status", "pending")).title(),
                    "detail": self._job_summary(job),
                }
                for job in self._jobs[:4]
            ] or [{"primary": "Quiet watch", "secondary": "No recent jobs", "detail": "Tool activity will surface here when the core is busy."}]
            event_entries = [
                {
                    "primary": str(event.get("message", "No recent signal.")),
                    "secondary": str(event.get("level", "INFO")).title(),
                    "detail": self._short_time(str(event.get("created_at", ""))),
                }
                for event in self._events[:4]
            ] or [{"primary": "No fresh signal", "secondary": "Standby", "detail": "Watch remains calm until activity resumes."}]
            return [
                self._workspace_column("Jobs", "Recent operational work.", job_entries),
                self._workspace_column("Timeline", "Latest activity signal.", event_entries),
            ]

        if self._active_module_key == "signals":
            message_entries = [
                {
                    "primary": str(message.get("content", ""))[:88] or "Signal trace",
                    "secondary": str(message.get("speaker", "Stormhelm")),
                    "detail": str(message.get("shortTime", "")),
                }
                for message in self._history[-4:]
            ] or [{"primary": "No active signal trace", "secondary": "Standby", "detail": "Recent conversations will surface here."}]
            event_entries = [
                {
                    "primary": str(event.get("message", "No recent signal.")),
                    "secondary": str(event.get("level", "INFO")).title(),
                    "detail": str(event.get("created_at", "")),
                }
                for event in self._events[:4]
            ] or [{"primary": "No recent events", "secondary": "Quiet sea", "detail": "Event telemetry will appear here as needed."}]
            return [
                self._workspace_column("Live Signal", "Recent conversational and operational signal.", message_entries),
                self._workspace_column("Events", "System signal and event trace.", event_entries),
            ]

        if self._active_module_key == "files":
            return [
                self._workspace_column(
                    "Working Set",
                    "Curated files will gather here later.",
                    [
                        {"primary": "Safe Reads", "secondary": "Enabled", "detail": "The file reader remains allowlist-bound."},
                        {"primary": "Native Hand-off", "secondary": "Preferred", "detail": "Stormhelm should still lean on Explorer and default apps when appropriate."},
                    ],
                )
            ]

        if self._active_module_key == "browser":
            return [
                self._workspace_column(
                    "Research Bearings",
                    "Reference work remains intentionally lightweight in this phase.",
                    [
                        {"primary": "External Browser", "secondary": "Current path", "detail": "Stormhelm opens and accompanies the native browser instead of replacing it yet."},
                        {"primary": "Sources", "secondary": "Future surface", "detail": "A fuller cited workspace will arrive in a later pass."},
                    ],
                )
            ]

        if self._active_module_key == "visual-context":
            return [
                self._workspace_column(
                    "Future Context",
                    "This space remains reserved for later screen-aware guidance.",
                    [
                        {"primary": "Focus Surface", "secondary": "Reserved", "detail": "The visual layer is staged but not claimed as implemented."},
                        {"primary": "Guidance", "secondary": "Future pass", "detail": "Recommendations can later emerge from what Stormhelm sees."},
                    ],
                )
            ]

        message_entries = [
            {
                "primary": str(message.get("content", ""))[:92] or "No conversation yet",
                "secondary": str(message.get("speaker", "Stormhelm")),
                "detail": str(message.get("shortTime", "")),
            }
            for message in self._history[-4:]
        ] or [{"primary": "Awaiting a bearing", "secondary": "Chartroom", "detail": "Use Ghost capture or the command spine to start a thread."}]
        note_entries = [
            {
                "primary": str(note.get("title", "Untitled")),
                "secondary": self._short_time(str(note.get("created_at", ""))),
                "detail": str(note.get("content", ""))[:120],
            }
            for note in self._notes[:3]
        ] or [{"primary": "No nearby notes", "secondary": "Logbook", "detail": "Saved notes will travel with the workspace here."}]
        signal_entries = [
            {
                "primary": str(event.get("message", "No recent signal.")),
                "secondary": str(event.get("level", "INFO")).title(),
                "detail": self._short_time(str(event.get("created_at", ""))),
            }
            for event in self._events[:3]
        ] or [{"primary": "Signal steady", "secondary": self.connectionLabel, "detail": self._status_line}]
        return [
            self._workspace_column("Active Thread", "The current exchange with Stormhelm.", message_entries),
            self._workspace_column("Logbook", "Notes and retained mission memory.", note_entries),
            self._workspace_column("Signal", "Operational context held alongside the work.", signal_entries),
        ]

    def _workspace_section_label(self, key: str) -> str:
        return key.replace("-", " ").title()

    def _workspace_column(self, title: str, summary: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "title": title,
            "summary": summary,
            "entries": entries,
        }

    def _build_deck_modules(self) -> list[dict[str, Any]]:
        if self._active_module_key == "chartroom":
            return [self._build_module(key) for key in ("logbook", "signals", "watch")]

        primary = self._build_module(self._active_module_key)
        companion_keys = self._companion_module_keys(self._active_module_key)
        modules = [primary]
        for key in companion_keys:
            if key != self._active_module_key:
                modules.append(self._build_module(key))
            if len(modules) == 3:
                break
        return modules

    def _build_module(self, key: str) -> dict[str, Any]:
        normalized = (key or "").strip().lower()
        if normalized == "helm":
            return {
                "key": "helm",
                "kind": "settings",
                "title": "Helm",
                "eyebrow": "Configuration",
                "headline": "Stormhelm behavior, presence, and settings direction",
                "body": "Helm is where behavior, presence, hotkeys, and user-facing configuration will live. The tray stays reserved for quick controls, while config files remain the advanced fallback.",
                "entries": [
                    {"primary": "Ghost Shortcut", "secondary": self.config.ui.ghost_shortcut, "detail": "Summons Ghost text capture from anywhere."},
                    {"primary": "Tray Close", "secondary": "Fade to dormant" if self._hide_to_tray_on_close else "Close window", "detail": "Quick controls belong in the tray, not a full settings dashboard."},
                    {"primary": "Config Fallback", "secondary": "portable.toml / user.toml", "detail": "Advanced and power-user behavior remains file-backed."},
                ],
            }
        if normalized == "logbook":
            return {
                "key": "logbook",
                "kind": "notes",
                "title": "Logbook",
                "eyebrow": "Memory",
                "headline": "Local notes and bearings",
                "body": "Keep brief local notes close to the current task.",
                "entries": [
                    {
                        "primary": str(note.get("title", "Untitled")),
                        "secondary": str(note.get("created_at", "")),
                        "detail": str(note.get("content", "")),
                    }
                    for note in self._notes[:4]
                ],
            }
        if normalized == "watch":
            return {
                "key": "watch",
                "kind": "jobs",
                "title": "Watch",
                "eyebrow": "Activity",
                "headline": "Recent tool actions",
                "body": "Operational work remains visible without becoming the whole deck.",
                "entries": [
                    {
                        "primary": self._module_label(str(job.get("tool_name", "Tool"))),
                        "secondary": str(job.get("status", "pending")).title(),
                        "detail": self._job_summary(job),
                    }
                    for job in self._jobs[:4]
                ],
            }
        if normalized == "signals":
            return {
                "key": "signals",
                "kind": "events",
                "title": "Signals",
                "eyebrow": "Telemetry",
                "headline": "Recent operational signal",
                "body": "A restrained log of what Stormhelm is doing beneath the surface.",
                "entries": [
                    {
                        "primary": str(event.get("message", "No recent signal.")),
                        "secondary": str(event.get("level", "INFO")).title(),
                        "detail": str(event.get("created_at", "")),
                    }
                    for event in self._events[:4]
                ],
            }
        if normalized == "systems":
            allowed_dirs = self._settings.get("safety", {}).get("allowed_read_dirs", []) if isinstance(self._settings, dict) else []
            return {
                "key": "systems",
                "kind": "system",
                "title": "Systems",
                "eyebrow": "Core",
                "headline": "Runtime, diagnostics, and technical state",
                "body": "Systems stays technical: runtime health, jobs, logs, diagnostics, and connection state.",
                "entries": [
                    {"primary": "Connection", "secondary": self.connectionLabel, "detail": self._status_line},
                    {"primary": "Runtime", "secondary": self._runtime_mode_label.title(), "detail": self._environment_label.title()},
                    {"primary": "Workers", "secondary": str(self._status.get("max_workers", self.config.concurrency.max_workers)), "detail": f"Recent jobs: {self._status.get('recent_jobs', len(self._jobs))}"},
                    {"primary": "Safe Reads", "secondary": str(len(allowed_dirs)), "detail": ", ".join(str(path) for path in allowed_dirs[:2]) or "No allowlist loaded."},
                ],
            }
        if normalized == "files":
            active_item = self._get_active_opened_item()
            entries = [
                {
                    "primary": str(item.get("title", "Untitled")),
                    "secondary": str(item.get("viewer", item.get("kind", "item"))).title(),
                    "detail": str(item.get("path", item.get("url", ""))),
                }
                for item in self._opened_items[:4]
            ]
            return {
                "key": "files",
                "kind": "workspace",
                "title": "Files",
                "eyebrow": "Workspace",
                "headline": "Curated file viewing inside the current Deck workspace",
                "body": "Stormhelm can now hold text, image, and PDF files inside the Deck without becoming a file explorer clone.",
                "entries": entries or [
                    {
                        "primary": "No files held yet",
                        "secondary": "Working set",
                        "detail": "Ask Stormhelm to open a safe local file in the Deck to populate this surface.",
                    }
                ],
                "activeTitle": str(active_item.get("title", "")),
            }
        if normalized == "browser":
            browser_items = [item for item in self._opened_items if item.get("viewer") == "browser"]
            return {
                "key": "browser",
                "kind": "workspace",
                "title": "Browser",
                "eyebrow": "Research",
                "headline": "Deck browsing for docs, references, and active research pages",
                "body": "Stormhelm now keeps task-relevant pages inside the Deck when that helps the current workspace, while Ghost can still hand off to the external browser.",
                "entries": [
                    {
                        "primary": str(item.get("title", "Reference")),
                        "secondary": "Deck page",
                        "detail": str(item.get("url", "")),
                    }
                    for item in browser_items[:4]
                ] or [
                    {
                        "primary": "No deck pages held yet",
                        "secondary": "Research surface",
                        "detail": "Ask Stormhelm to open a page in the Deck to seed this workspace.",
                    }
                ],
            }
        if normalized == "visual-context":
            return self._placeholder_module(
                key="visual-context",
                title="Visual Context",
                eyebrow="Tactical",
                headline="Screen-aware guidance is staged, not implemented.",
                body="UI-A reserves a place for visual context without claiming screen-awareness behavior that does not exist yet.",
            )
        return self._placeholder_module(
            key="chartroom",
            title="Chartroom",
            eyebrow="Workspace",
            headline="The main collaboration surface holds the chartroom.",
            body="Use the rail to pull supporting modules alongside the central conversation and command flow.",
        )

    def _build_status_strip_items(self) -> list[dict[str, Any]]:
        return [
            {"label": "Mode", "value": "Ghost" if self._mode == "ghost" else "Deck"},
            {"label": "State", "value": self._assistant_state.title()},
            {"label": "Signal", "value": self.connectionLabel},
            {"label": "Time", "value": self._local_time_label},
            {"label": "Helm", "value": self._active_module_label()},
            {"label": "Version", "value": self._core_version_label},
        ]

    def _build_ghost_corner_readouts(self) -> list[dict[str, Any]]:
        latest_message = self._history[-1] if self._history else None
        latest_job = self._jobs[0] if self._jobs else None
        latest_note = self._notes[0] if self._notes else None

        recent_context = "Standing watch."
        if latest_message is not None:
            recent_context = str(latest_message.get("content", recent_context))
        elif latest_note is not None:
            recent_context = str(latest_note.get("title", recent_context))

        recent_action = "Deck via tray"
        if self._mode == "deck":
            recent_action = f"{self._module_label(self._active_module_key)} aligned"
        elif latest_job is not None:
            recent_action = self._module_label(str(latest_job.get("tool_name", "action")))

        job_secondary = "Spectral watch"
        if latest_job is not None:
            job_secondary = str(latest_job.get("status", "pending")).title()
        elif self._mode == "deck":
            job_secondary = "Command field deepened"

        return [
            {
                "corner": "top_left",
                "label": "Stormhelm",
                "primary": "Ghost Mode" if self._mode == "ghost" else "Command Deck",
                "secondary": "Signal capture ready" if self._ghost_capture_active else self._assistant_state.title(),
            },
            {
                "corner": "top_right",
                "label": "Signal",
                "primary": self.connectionLabel,
                "secondary": self._local_time_label,
            },
            {
                "corner": "bottom_left",
                "label": "Bearing",
                "primary": recent_context[:72],
                "secondary": self._status_line[:72],
            },
            {
                "corner": "bottom_right",
                "label": "Helm",
                "primary": "Enter sends · Esc clears" if self._ghost_capture_active else recent_action,
                "secondary": self.config.ui.ghost_shortcut if not self._ghost_capture_active else job_secondary,
            },
        ]

    def _companion_module_keys(self, active_key: str) -> list[str]:
        if active_key == "chartroom":
            return ["logbook", "watch", "systems"]
        if active_key in {"helm", "logbook", "watch", "signals", "systems"}:
            ordered = [active_key, "signals", "systems", "logbook", "watch", "helm"]
            deduped: list[str] = []
            for key in ordered:
                if key not in deduped:
                    deduped.append(key)
            return deduped[:3]
        return [active_key, "logbook", "signals"]

    def _placeholder_module(self, *, key: str, title: str, eyebrow: str, headline: str, body: str) -> dict[str, Any]:
        return {
            "key": key,
            "kind": "placeholder",
            "title": title,
            "eyebrow": eyebrow,
            "headline": headline,
            "body": body,
            "entries": [],
        }

    def _upsert_opened_item(self, item: dict[str, Any]) -> None:
        item_id = str(item.get("itemId", "")).strip()
        if not item_id:
            item_id = str(uuid4())
            item["itemId"] = item_id
        updated_items: list[dict[str, Any]] = []
        found = False
        for existing in self._opened_items:
            if existing.get("itemId") == item_id:
                updated_items.append(item)
                found = True
            else:
                updated_items.append(existing)
        if not found:
            updated_items.insert(0, item)
        self._opened_items = updated_items[:12]
        self._active_opened_item_id = item_id

    def _get_active_opened_item(self) -> dict[str, Any]:
        if self._active_opened_item_id:
            for item in self._opened_items:
                if item.get("itemId") == self._active_opened_item_id:
                    return dict(item)
        return dict(self._opened_items[0]) if self._opened_items else {}

    def _normalize_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        role = str(payload.get("role", "assistant"))
        content = str(payload.get("content", ""))
        created_at = str(payload.get("created_at", ""))
        return {
            "messageId": str(payload.get("message_id", "")),
            "role": role,
            "speaker": "You" if role == "user" else "Stormhelm",
            "content": content,
            "createdAt": created_at,
            "shortTime": self._short_time(created_at),
        }

    def _module_label(self, name: str) -> str:
        labels = {
            "echo": "Echo",
            "clock": "Chronometer",
            "system_info": "Systems",
            "file_reader": "Files",
            "notes_write": "Logbook",
            "shell_command": "Command Gate",
        }
        return labels.get(name, name.replace("_", " ").title())

    def _job_summary(self, job: dict[str, Any]) -> str:
        result = job.get("result")
        if isinstance(result, dict) and result.get("summary"):
            return str(result["summary"])
        if job.get("error"):
            return str(job["error"])
        return str(job.get("created_at", "Awaiting output."))

    def _set_assistant_state(self, state: str) -> None:
        normalized = (state or "").strip().lower()
        if normalized not in VOICE_STATES or normalized == self._assistant_state:
            return
        self._assistant_state = normalized
        self.assistantStateChanged.emit()

    def _refresh_clock(self) -> None:
        self._local_time_label = self._format_time()
        self.statusChanged.emit()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def _format_time(self) -> str:
        return datetime.now().strftime("%H:%M")

    def _short_time(self, value: str) -> str:
        if not value:
            return ""
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%H:%M")
        except ValueError:
            return value
