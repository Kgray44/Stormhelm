from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from PySide6 import QtCore, QtGui

from stormhelm.config.models import AppConfig
from stormhelm.ui.command_surface_v2 import build_command_surface_model
from stormhelm.ui.ghost_adaptive import (
    GhostAdaptiveManager,
    default_ghost_diagnostics,
    default_ghost_placement,
    default_ghost_style,
)
from stormhelm.ui.voice_surface import build_voice_command_station
from stormhelm.ui.voice_surface import build_voice_ui_state


VISIBLE_MODES = {"ghost", "deck"}
VOICE_STATES = {"idle", "listening", "thinking", "acting", "speaking", "warning"}
DECK_GRID_COLUMNS = 12
DECK_GRID_ROWS = 8
DECK_ANCHOR_NOTCH = (4, 0, 8, 3)


class UiBridge(QtCore.QObject):
    sendMessageRequested = QtCore.Signal(str)
    saveNoteRequested = QtCore.Signal(str, str)
    voiceStartPushToTalkCaptureRequested = QtCore.Signal(dict)
    voiceStopPushToTalkCaptureRequested = QtCore.Signal(dict)
    voiceCancelCaptureRequested = QtCore.Signal(dict)
    voiceSubmitCapturedAudioTurnRequested = QtCore.Signal(dict)
    voiceCaptureAndSubmitTurnRequested = QtCore.Signal(dict)
    voiceListenAndSubmitTurnRequested = QtCore.Signal(dict)
    voiceStopPlaybackRequested = QtCore.Signal(dict)
    voiceStopSpeakingRequested = QtCore.Signal(dict)
    voiceSuppressCurrentResponseRequested = QtCore.Signal(dict)
    voiceMuteSpokenResponsesRequested = QtCore.Signal(dict)
    voiceUnmuteSpokenResponsesRequested = QtCore.Signal(dict)
    voiceSpokenConfirmationRequested = QtCore.Signal(dict)
    voiceReadinessRequested = QtCore.Signal()

    modeChanged = QtCore.Signal()
    assistantStateChanged = QtCore.Signal()
    ghostCaptureChanged = QtCore.Signal()
    statusChanged = QtCore.Signal()
    collectionsChanged = QtCore.Signal()
    visibilityChanged = QtCore.Signal()
    ghostAdaptiveChanged = QtCore.Signal()
    voiceStateChanged = QtCore.Signal()

    def __init__(self, config: AppConfig, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._window: QtGui.QWindow | None = None
        self._mode = "ghost"
        self._assistant_state = "idle"
        self._active_module_key = "chartroom"
        self._active_workspace_section_key = "overview"
        self._hide_to_tray_on_close = config.ui.hide_to_tray_on_close
        self._tray_present = False
        self._connected = False
        self._ui_version_label = config.version_label
        self._core_version_label = "Awaiting signal"
        self._runtime_mode_label = config.runtime.mode
        self._install_mode_label = "Awaiting posture"
        self._environment_label = config.environment
        self._connection_state = "connecting"
        self._status_line = "Standing watch."
        self._local_time_label = self._format_time()
        self._health: dict[str, Any] = {}
        self._status: dict[str, Any] = {}
        self._voice_state: dict[str, Any] = build_voice_ui_state({})
        self._history: list[dict[str, Any]] = []
        self._jobs: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._notes: list[dict[str, Any]] = []
        self._settings: dict[str, Any] = {}
        self._tools: list[dict[str, Any]] = []
        self._command_rail_items: list[dict[str, Any]] = []
        self._workspace_rail_items: list[dict[str, Any]] = []
        self._workspace_sections: list[dict[str, Any]] = []
        self._workspace_canvas: dict[str, Any] = {}
        self._workspace_focus: dict[str, Any] = {}
        self._active_request_state: dict[str, Any] = {}
        self._recent_context_resolutions: list[dict[str, Any]] = []
        self._workspace_state_hint = ""
        self._opened_items: list[dict[str, Any]] = []
        self._active_opened_item_id: str | None = None
        self._active_task: dict[str, Any] = {}
        self._ghost_messages: list[dict[str, Any]] = []
        self._context_cards: list[dict[str, Any]] = []
        self._ghost_primary_card: dict[str, Any] = {}
        self._ghost_action_strip: list[dict[str, Any]] = []
        self._ghost_corner_readouts: list[dict[str, Any]] = []
        self._deck_modules: list[dict[str, Any]] = []
        self._active_deck_module: dict[str, Any] = {}
        self._deck_support_modules: list[dict[str, Any]] = []
        self._deck_panels: list[dict[str, Any]] = []
        self._hidden_deck_panels: list[dict[str, Any]] = []
        self._deck_panel_catalog: list[dict[str, Any]] = []
        self._status_strip_items: list[dict[str, Any]] = []
        self._request_composer: dict[str, Any] = {}
        self._route_inspector: dict[str, Any] = {}
        self._command_stations: list[dict[str, Any]] = []
        self._ghost_capture_active = False
        self._ghost_draft_text = ""
        self._ghost_reveal_target = 1.0
        self._window_exposed = False
        self._ghost_adaptive_style = default_ghost_style()
        self._ghost_placement = default_ghost_placement()
        self._ghost_adaptive_diagnostics = default_ghost_diagnostics()
        self._selection_context: dict[str, Any] = {}
        self._clipboard_context: dict[str, Any] = {}
        self._pending_activity: str | None = None
        self._pending_chat_echo: dict[str, Any] | None = None
        self._pending_chat_anchor_message_id: str | None = None
        self._deck_layout_store_path = (
            Path(self.config.storage.data_dir) / "ui" / "deck_layouts.json"
        )
        self._deck_layout_store = self._load_deck_layout_store()
        self._ghost_adaptive_manager = GhostAdaptiveManager(self)
        self._ghost_adaptive_manager.updated.connect(self.updateGhostAdaptiveState)

        self._clock_timer = QtCore.QTimer(self)
        self._clock_timer.setInterval(30_000)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start()

        self._stream_collections_timer = QtCore.QTimer(self)
        self._stream_collections_timer.setSingleShot(True)
        self._stream_collections_timer.setInterval(75)
        self._stream_collections_timer.timeout.connect(
            self._flush_stream_collections_changed
        )

        self._ghost_hide_timer = QtCore.QTimer(self)
        self._ghost_hide_timer.setSingleShot(True)
        self._ghost_hide_timer.setInterval(320)
        self._ghost_hide_timer.timeout.connect(self._finalize_ghost_hide)

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
    def deck_panels(self) -> list[dict[str, Any]]:
        return list(self._deck_panels)

    @property
    def hidden_deck_panels(self) -> list[dict[str, Any]]:
        return list(self._hidden_deck_panels)

    @property
    def deck_panel_catalog(self) -> list[dict[str, Any]]:
        return list(self._deck_panel_catalog)

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

    @QtCore.Property("QVariantMap", notify=voiceStateChanged)
    def voiceState(self) -> dict[str, Any]:
        return dict(self._voice_state)

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
    def installModeLabel(self) -> str:
        return self._install_mode_label

    @QtCore.Property(str, notify=statusChanged)
    def environmentLabel(self) -> str:
        return self._environment_label

    @QtCore.Property(bool, notify=statusChanged)
    def embeddedBrowserPreviewEnabled(self) -> bool:
        if self._environment_label.strip().lower() == "test":
            return False
        platform_name = ""
        app = QtGui.QGuiApplication.instance()
        if app is not None:
            try:
                platform_name = str(app.platformName() or "")
            except Exception:
                platform_name = ""
        if not platform_name:
            platform_name = str(os.environ.get("QT_QPA_PLATFORM", ""))
        return platform_name.strip().lower() not in {"offscreen", "minimal", "headless"}

    @QtCore.Property(str, notify=statusChanged)
    def localTimeLabel(self) -> str:
        return self._local_time_label

    @QtCore.Property(bool, notify=visibilityChanged)
    def hideToTrayOnClose(self) -> bool:
        return self._hide_to_tray_on_close

    @QtCore.Property(float, notify=visibilityChanged)
    def ghostRevealTarget(self) -> float:
        return self._ghost_reveal_target

    @QtCore.Property("QVariantMap", notify=ghostAdaptiveChanged)
    def ghostAdaptiveStyle(self) -> dict[str, Any]:
        return dict(self._ghost_adaptive_style)

    @QtCore.Property("QVariantMap", notify=ghostAdaptiveChanged)
    def ghostPlacement(self) -> dict[str, Any]:
        return dict(self._ghost_placement)

    @QtCore.Property("QVariantMap", notify=ghostAdaptiveChanged)
    def ghostAdaptiveDiagnostics(self) -> dict[str, Any]:
        return dict(self._ghost_adaptive_diagnostics)

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
        return self._display_history()

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def ghostMessages(self) -> list[dict[str, Any]]:
        return list(self._ghost_messages)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def contextCards(self) -> list[dict[str, Any]]:
        return list(self._context_cards)

    @QtCore.Property("QVariantMap", notify=collectionsChanged)
    def ghostPrimaryCard(self) -> dict[str, Any]:
        return dict(self._ghost_primary_card)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def ghostActionStrip(self) -> list[dict[str, Any]]:
        return list(self._ghost_action_strip)

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
    def deckPanels(self) -> list[dict[str, Any]]:
        return list(self._deck_panels)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def hiddenDeckPanels(self) -> list[dict[str, Any]]:
        return list(self._hidden_deck_panels)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def deckPanelCatalog(self) -> list[dict[str, Any]]:
        return list(self._deck_panel_catalog)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def deckLayoutPresets(self) -> list[dict[str, Any]]:
        return list(self._deck_layout_presets())

    @QtCore.Property(str, notify=collectionsChanged)
    def activeDeckLayoutPreset(self) -> str:
        scope_state = self._ensure_layout_scope_state()
        return (
            str(scope_state.get("preset", self._deck_layout_preset())).strip()
            or self._deck_layout_preset()
        )

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def workspaceSections(self) -> list[dict[str, Any]]:
        return list(self._workspace_sections)

    @QtCore.Property("QVariantMap", notify=collectionsChanged)
    def workspaceCanvas(self) -> dict[str, Any]:
        return dict(self._workspace_canvas)

    @QtCore.Property("QVariantMap", notify=collectionsChanged)
    def requestComposer(self) -> dict[str, Any]:
        return dict(self._request_composer)

    @QtCore.Property("QVariantMap", notify=collectionsChanged)
    def routeInspector(self) -> dict[str, Any]:
        return dict(self._route_inspector)

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def openedItems(self) -> list[dict[str, Any]]:
        return list(self._opened_items)

    @QtCore.Property("QVariantMap", notify=collectionsChanged)
    def activeOpenedItem(self) -> dict[str, Any]:
        return dict(self._get_active_opened_item())

    @QtCore.Property("QVariantList", notify=collectionsChanged)
    def commandRailItems(self) -> list[dict[str, Any]]:
        return list(self._command_rail_items)

    @QtCore.Property("QVariantList", notify=statusChanged)
    def statusStripItems(self) -> list[dict[str, Any]]:
        return self._build_status_strip_items()

    @QtCore.Slot(QtGui.QWindow)
    def attachWindow(self, window: QtGui.QWindow) -> None:
        self._window = window
        self._ghost_adaptive_manager.attach_window(window)
        self._sync_ghost_adaptive_monitoring()

    @QtCore.Slot(str)
    def setMode(self, mode: str) -> None:
        normalized = (mode or "").strip().lower()
        if normalized not in VISIBLE_MODES or normalized == self._mode:
            return
        self._mode = normalized
        if normalized == "ghost":
            self._status_line = (
                "Ghost Mode holding steady."
                if not self._ghost_capture_active
                else "Signal the helm."
            )
        else:
            self._ghost_capture_active = False
            self._ghost_draft_text = ""
            self._status_line = "Command Deck unfolded."
        self.modeChanged.emit()
        self.ghostCaptureChanged.emit()
        self.statusChanged.emit()
        self._sync_ghost_adaptive_monitoring()
        if normalized != "ghost":
            self._activate_deck_window()

    @QtCore.Slot()
    def toggleMode(self) -> None:
        self.setMode("deck" if self._mode == "ghost" else "ghost")

    @QtCore.Slot(str)
    def activateModule(self, key: str) -> None:
        normalized = (key or "").strip().lower()
        if not normalized:
            return
        self._active_module_key = normalized
        self._workspace_state_hint = ""
        self._active_workspace_section_key = self._default_workspace_section_key(
            normalized
        )
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

    @QtCore.Slot()
    def startPushToTalkCapture(self) -> None:
        if self._mode != "ghost":
            self.setMode("ghost")
        self.showWindow()
        self._status_line = "Starting push-to-talk capture."
        self.statusChanged.emit()
        self.voiceStartPushToTalkCaptureRequested.emit(
            {"session_id": "default", "metadata": {"surface": self._mode}}
        )

    @QtCore.Slot(str)
    def stopPushToTalkCapture(self, capture_id: str = "") -> None:
        self._status_line = "Stopping capture."
        self.statusChanged.emit()
        self.voiceStopPushToTalkCaptureRequested.emit(
            {
                "capture_id": str(
                    capture_id or self._voice_state.get("active_capture_id") or ""
                ),
                "reason": "user_released",
            }
        )

    @QtCore.Slot(str)
    def cancelCapture(self, capture_id: str = "") -> None:
        self._status_line = "Cancelling capture."
        self.statusChanged.emit()
        self.voiceCancelCaptureRequested.emit(
            {
                "capture_id": str(
                    capture_id or self._voice_state.get("active_capture_id") or ""
                ),
                "reason": "user_cancelled",
            }
        )

    @QtCore.Slot(str)
    def submitCapturedAudioTurn(self, mode: str = "ghost") -> None:
        normalized_mode = str(mode or self._mode or "ghost").strip().lower() or "ghost"
        self._status_line = "Submitting captured audio through Core."
        self.statusChanged.emit()
        self.voiceSubmitCapturedAudioTurnRequested.emit({"mode": normalized_mode})

    @QtCore.Slot(str, str, bool, bool)
    def captureAndSubmitTurn(
        self,
        capture_id: str = "",
        mode: str = "ghost",
        synthesize_response: bool = False,
        play_response: bool = False,
    ) -> None:
        normalized_mode = str(mode or self._mode or "ghost").strip().lower() or "ghost"
        self._status_line = "Submitting captured audio through Core."
        self.statusChanged.emit()
        self.voiceCaptureAndSubmitTurnRequested.emit(
            {
                "capture_id": str(
                    capture_id or self._voice_state.get("active_capture_id") or ""
                ),
                "mode": normalized_mode,
                "synthesize_response": bool(synthesize_response),
                "play_response": bool(play_response),
            }
        )

    @QtCore.Slot(str, bool)
    def listenAndSubmitTurn(
        self,
        mode: str = "ghost",
        play_response: bool = True,
    ) -> None:
        normalized_mode = str(mode or self._mode or "ghost").strip().lower() or "ghost"
        self._status_line = "Listening for one voice request."
        self.statusChanged.emit()
        self.voiceListenAndSubmitTurnRequested.emit(
            {
                "session_id": "default",
                "mode": normalized_mode,
                "play_response": bool(play_response),
            }
        )

    @QtCore.Slot(str)
    def stopVoicePlayback(self, playback_id: str = "") -> None:
        self._status_line = "Stopping voice playback."
        self.statusChanged.emit()
        self.voiceStopPlaybackRequested.emit(
            {
                "playback_id": str(
                    playback_id or self._voice_state.get("active_playback_id") or ""
                ),
                "reason": "user_requested",
            }
        )

    @QtCore.Slot(str)
    def stopSpeaking(self, playback_id: str = "") -> None:
        self._status_line = "Stopping speech."
        self.statusChanged.emit()
        self.voiceStopSpeakingRequested.emit(
            {
                "playback_id": str(
                    playback_id or self._voice_state.get("active_playback_id") or ""
                ),
                "reason": "user_requested",
            }
        )

    @QtCore.Slot(str)
    def suppressCurrentResponse(self, turn_id: str = "") -> None:
        self._status_line = "Suppressing spoken output."
        self.statusChanged.emit()
        self.voiceSuppressCurrentResponseRequested.emit(
            {
                "turn_id": str(turn_id or self._voice_state.get("turn_id") or ""),
                "reason": "user_requested",
            }
        )

    @QtCore.Slot()
    def muteSpokenResponses(self) -> None:
        self._status_line = "Muting speech."
        self.statusChanged.emit()
        self.voiceMuteSpokenResponsesRequested.emit(
            {"scope": "session", "reason": "user_requested"}
        )

    @QtCore.Slot()
    def unmuteSpokenResponses(self) -> None:
        self._status_line = "Unmuting speech."
        self.statusChanged.emit()
        self.voiceUnmuteSpokenResponsesRequested.emit(
            {"scope": "session", "reason": "user_requested"}
        )

    @QtCore.Slot(str, str, str)
    def submitSpokenConfirmation(
        self, transcript: str, pending_confirmation_id: str = "", task_id: str = ""
    ) -> None:
        phrase = str(transcript or "").strip()
        if not phrase:
            return
        self._status_line = "Checking confirmation."
        self.statusChanged.emit()
        self.voiceSpokenConfirmationRequested.emit(
            {
                "transcript": phrase,
                "session_id": "default",
                "source": "deck",
                "pending_confirmation_id": str(pending_confirmation_id or ""),
                "task_id": str(task_id or ""),
            }
        )

    @QtCore.Slot(str)
    def activateWorkspaceSection(self, key: str) -> None:
        normalized = (key or "").strip().lower()
        if not normalized or normalized == self._active_workspace_section_key:
            return
        self._workspace_state_hint = ""
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
        self._opened_items = [
            item for item in self._opened_items if item.get("itemId") != normalized
        ]
        if self._active_opened_item_id == normalized:
            self._active_opened_item_id = (
                self._opened_items[0]["itemId"] if self._opened_items else None
            )
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    @QtCore.Slot(str, int, int, int, int)
    def updateDeckPanelGrid(
        self, panel_id: str, grid_x: int, grid_y: int, col_span: int, row_span: int
    ) -> None:
        normalized = str(panel_id or "").strip()
        if not normalized:
            return
        previous_panels = self._merged_deck_panel_map()
        layout = self._ensure_layout_scope_state()
        panel_state = layout.setdefault("panels", {}).setdefault(normalized, {})
        panel_state.update(
            {
                "gridX": max(0, int(grid_x)),
                "gridY": max(0, int(grid_y)),
                "colSpan": max(2, int(col_span)),
                "rowSpan": max(2, int(row_span)),
            }
        )
        self._reflow_adjacent_docked_panels(layout, normalized, previous_panels)
        self._persist_deck_layout_store()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    @QtCore.Slot(str, bool)
    def setDeckPanelPinned(self, panel_id: str, pinned: bool) -> None:
        self._set_deck_panel_flag(panel_id, "pinned", pinned)

    @QtCore.Slot(str, bool)
    def setDeckPanelCollapsed(self, panel_id: str, collapsed: bool) -> None:
        self._set_deck_panel_flag(panel_id, "collapsed", collapsed)

    @QtCore.Slot(str, bool)
    def setDeckPanelHidden(self, panel_id: str, hidden: bool) -> None:
        self._set_deck_panel_flag(panel_id, "hidden", hidden)

    @QtCore.Slot(str)
    def restoreDeckPanel(self, panel_id: str) -> None:
        self._set_deck_panel_flag(panel_id, "hidden", False)

    @QtCore.Slot()
    def resetDeckLayout(self) -> None:
        scope = self._deck_layout_scope_key()
        layouts = self._deck_layout_store.setdefault("layouts", {})
        if scope in layouts:
            layouts.pop(scope, None)
            self._persist_deck_layout_store()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    @QtCore.Slot()
    def restoreDeckLayout(self) -> None:
        self._deck_layout_store = self._load_deck_layout_store()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    @QtCore.Slot()
    def saveDeckLayout(self) -> None:
        scope = self._deck_layout_scope_key()
        saved_layouts = self._deck_layout_store.setdefault("saved_layouts", {})
        saved_layouts[scope] = copy.deepcopy(self._ensure_layout_scope_state())
        self._persist_deck_layout_store()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    @QtCore.Slot()
    def restoreSavedDeckLayout(self) -> None:
        scope = self._deck_layout_scope_key()
        saved_layouts = self._deck_layout_store.setdefault("saved_layouts", {})
        saved_state = saved_layouts.get(scope)
        if isinstance(saved_state, dict):
            layouts = self._deck_layout_store.setdefault("layouts", {})
            layouts[scope] = copy.deepcopy(saved_state)
            self._persist_deck_layout_store()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    @QtCore.Slot(str)
    def autoArrangeDeckLayout(self, preset: str = "") -> None:
        scope_state = self._ensure_layout_scope_state()
        scope_state["preset"] = (
            str(preset or self._deck_layout_preset()).strip()
            or self._deck_layout_preset()
        )
        scope_state["panels"] = {}
        self._persist_deck_layout_store()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    @QtCore.Slot(str)
    def setDeckLayoutPreset(self, preset: str) -> None:
        normalized = str(preset or "").strip().lower()
        valid = {entry["key"] for entry in self._deck_layout_presets()}
        if normalized not in valid:
            return
        self.autoArrangeDeckLayout(normalized)

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
        self._pending_chat_anchor_message_id = (
            str(self._history[-1].get("messageId", "")).strip()
            if self._history
            else None
        )
        self._pending_chat_echo = self._build_pending_chat_echo(text)
        self._set_assistant_state("thinking")
        self._status_line = "Plotting a response."
        self.statusChanged.emit()
        self.collectionsChanged.emit()
        self.sendMessageRequested.emit(text)

    @QtCore.Slot(str)
    def performLocalSurfaceAction(self, action_name: str) -> None:
        normalized = str(action_name or "").strip().lower()
        if not normalized:
            return
        if normalized == "voice.startpushtotalkcapture":
            self.startPushToTalkCapture()
            return
        if normalized == "voice.stoppushtotalkcapture":
            self.stopPushToTalkCapture(
                str(self._voice_state.get("active_capture_id") or "")
            )
            return
        if normalized == "voice.cancelcapture":
            self.cancelCapture(str(self._voice_state.get("active_capture_id") or ""))
            return
        if normalized == "voice.submitcapturedaudioturn":
            self.submitCapturedAudioTurn(self._mode)
            return
        if normalized == "voice.captureandsubmitturn":
            self.captureAndSubmitTurn(
                str(self._voice_state.get("active_capture_id") or ""),
                self._mode,
                False,
                False,
            )
            return
        if normalized == "voice.listenandsubmitturn":
            self.listenAndSubmitTurn(self._mode, True)
            return
        if normalized == "voice.stopplayback":
            self.stopVoicePlayback(
                str(self._voice_state.get("active_playback_id") or "")
            )
            return
        if normalized == "voice.stopspeaking":
            self.stopSpeaking(str(self._voice_state.get("active_playback_id") or ""))
            return
        if normalized == "voice.suppresscurrentresponse":
            self.suppressCurrentResponse(str(self._voice_state.get("turn_id") or ""))
            return
        if normalized == "voice.mutespokenresponses":
            self.muteSpokenResponses()
            return
        if normalized == "voice.unmutespokenresponses":
            self.unmuteSpokenResponses()
            return
        if normalized in {"voice.refreshreadiness", "voice.getreadinessreport"}:
            self._status_line = "Refreshing voice readiness."
            self.statusChanged.emit()
            self.voiceReadinessRequested.emit()
            return
        if normalized == "open_route_inspector":
            self.setMode("deck")
            self.restoreDeckPanel("route-inspector")
            return
        if normalized.startswith("open_panel:"):
            panel_id = normalized.split(":", 1)[1].strip()
            if panel_id:
                self.setMode("deck")
                self.restoreDeckPanel(panel_id)
            return
        if normalized.startswith("open_workspace:"):
            _, module_key, *section_parts = normalized.split(":")
            section_key = section_parts[0] if section_parts else ""
            if module_key:
                self.setMode("deck")
                self.activateModule(module_key)
                if section_key:
                    self.activateWorkspaceSection(section_key)

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

    @QtCore.Slot(bool)
    def setTrayPresent(self, enabled: bool) -> None:
        self._tray_present = bool(enabled)
        self.visibilityChanged.emit()

    @QtCore.Slot()
    def showWindow(self) -> None:
        self._ghost_hide_timer.stop()
        was_exposed = self._window_exposed
        self._window_exposed = True
        self._set_ghost_reveal_target(1.0)
        if not was_exposed:
            self.visibilityChanged.emit()
        if self._window is None:
            self._sync_ghost_adaptive_monitoring()
            return
        self._window.show()
        self._window.raise_()
        if self._mode != "ghost":
            self._activate_deck_window()
        self._sync_ghost_adaptive_monitoring()

    def _activate_deck_window(self) -> None:
        if self._window is None:
            return
        self._window.show()
        self._window.raise_()
        self._window.requestActivate()

    @QtCore.Slot()
    def hideWindow(self) -> None:
        was_exposed = self._window_exposed
        self._window_exposed = False
        self._set_ghost_reveal_target(0.0)
        if was_exposed:
            self.visibilityChanged.emit()
        self._sync_ghost_adaptive_monitoring()
        if self._mode == "ghost":
            self._ghost_hide_timer.start()
            return
        if self._window is not None:
            self._window.hide()

    def set_local_identity(self, version_label: str) -> None:
        self._ui_version_label = version_label
        self.statusChanged.emit()

    def shell_presence_payload(self) -> dict[str, Any]:
        window_visible = self._window_exposed and self._ghost_reveal_target > 0.0
        if self._window is not None:
            window_visible = (
                self._window.isVisible() and self._ghost_reveal_target > 0.0
            )
        return {
            "pid": os.getpid(),
            "mode": self._mode,
            "window_visible": window_visible,
            "tray_present": self._tray_present,
            "hide_to_tray_on_close": self._hide_to_tray_on_close,
            "ghost_reveal_target": self._ghost_reveal_target,
        }

    def tray_tooltip_text(self) -> str:
        lifecycle = self._lifecycle_state()
        runtime_state = (
            lifecycle.get("runtime")
            if isinstance(lifecycle.get("runtime"), dict)
            else {}
        )
        restart_policy = (
            lifecycle.get("restart_policy")
            if isinstance(lifecycle.get("restart_policy"), dict)
            else {}
        )
        bootstrap = (
            lifecycle.get("bootstrap")
            if isinstance(lifecycle.get("bootstrap"), dict)
            else {}
        )
        hold_summary = str(
            restart_policy.get("hold_reason")
            or bootstrap.get("lifecycle_hold_reason")
            or ""
        ).strip()
        shell_status = str(runtime_state.get("shell_status", "")).strip().lower()
        if shell_status in {"visible", "hidden", "detached", "stale"}:
            shell_state = shell_status.title()
        else:
            shell_state = (
                "Visible"
                if self.shell_presence_payload().get("window_visible")
                else "Hidden"
            )
        core_status = str(runtime_state.get("core_status", "")).strip().lower()
        if hold_summary or core_status == "held":
            core_label = "Hold"
        else:
            core_label = self.connectionLabel
        return (
            "Stormhelm"
            f" | {self._install_mode_label.title()}"
            f" | Core {core_label}"
            f" | Shell {shell_state}"
        )

    def set_connection_error(self, error: str) -> None:
        self._connected = False
        self._connection_state = "disrupted"
        self._pending_activity = None
        self._pending_chat_echo = None
        self._pending_chat_anchor_message_id = None
        self._set_assistant_state("warning")
        self._status_line = f"Signal disrupted: {error}"
        self.statusChanged.emit()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def set_operation_error(self, error: str) -> None:
        self._pending_activity = None
        self._pending_chat_echo = None
        self._pending_chat_anchor_message_id = None
        self._set_assistant_state("warning")
        self._status_line = f"Operation issue: {error}"
        self.statusChanged.emit()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def set_status_line(self, text: str) -> None:
        self._status_line = text
        self.statusChanged.emit()

    @QtCore.Slot("QVariantMap", "QVariantMap", "QVariantMap")
    def updateGhostAdaptiveState(
        self,
        style: dict[str, Any] | None,
        placement: dict[str, Any] | None,
        diagnostics: dict[str, Any] | None,
    ) -> None:
        updated = False
        if isinstance(style, dict):
            next_style = dict(self._ghost_adaptive_style)
            next_style.update(style)
            if next_style != self._ghost_adaptive_style:
                self._ghost_adaptive_style = next_style
                updated = True
        if isinstance(placement, dict):
            next_placement = dict(self._ghost_placement)
            next_placement.update(placement)
            if next_placement != self._ghost_placement:
                self._ghost_placement = next_placement
                updated = True
        if isinstance(diagnostics, dict):
            next_diagnostics = dict(self._ghost_adaptive_diagnostics)
            next_diagnostics.update(diagnostics)
            if next_diagnostics != self._ghost_adaptive_diagnostics:
                self._ghost_adaptive_diagnostics = next_diagnostics
                updated = True
        if updated:
            self.ghostAdaptiveChanged.emit()

    def apply_health(self, payload: dict[str, Any]) -> None:
        self._health = dict(payload)
        self._connected = payload.get("status") == "ok"
        self._connection_state = "connected" if self._connected else "connecting"
        self._core_version_label = str(
            payload.get(
                "version_label", payload.get("version", self._core_version_label)
            )
        )
        runtime_mode = payload.get("runtime_mode")
        if runtime_mode:
            self._runtime_mode_label = str(runtime_mode)
        install_mode = payload.get("install_mode")
        if install_mode:
            self._install_mode_label = str(install_mode)
        if (
            self._connected
            and self._pending_activity is None
            and self._assistant_state == "warning"
        ):
            self._set_assistant_state("idle")
        self.statusChanged.emit()

    def apply_status(self, payload: dict[str, Any]) -> None:
        self._status = dict(payload)
        self._core_version_label = str(
            payload.get(
                "version_label", payload.get("version", self._core_version_label)
            )
        )
        self._runtime_mode_label = str(
            payload.get("runtime_mode", self._runtime_mode_label)
        )
        lifecycle = payload.get("lifecycle")
        if isinstance(lifecycle, dict):
            install_state = lifecycle.get("install_state")
            if isinstance(install_state, dict):
                self._install_mode_label = str(
                    install_state.get("install_mode", self._install_mode_label)
                )
        self._environment_label = str(
            payload.get("environment", self._environment_label)
        )
        voice_changed = self._refresh_voice_state()
        if voice_changed:
            self._apply_voice_assistant_state()
            self.voiceStateChanged.emit()
        self.statusChanged.emit()

    def apply_snapshot(self, payload: dict[str, Any]) -> None:
        health = payload.get("health")
        status_changed = False
        collections_changed = False
        if isinstance(health, dict):
            status_changed = status_changed or dict(health) != self._health
            self.apply_health(health)

        status = payload.get("status")
        if isinstance(status, dict):
            status_changed = status_changed or dict(status) != self._status
            previous_voice_state = dict(self._voice_state)
            self.apply_status(status)
            if previous_voice_state != self._voice_state:
                collections_changed = True

        history = payload.get("history")
        if isinstance(history, list):
            normalized_history = [
                self._normalize_message(item)
                for item in history
                if isinstance(item, dict)
            ]
            if normalized_history != self._history:
                self._history = normalized_history
                collections_changed = True

        jobs = payload.get("jobs")
        if isinstance(jobs, list):
            normalized_jobs = [dict(item) for item in jobs if isinstance(item, dict)]
            if normalized_jobs != self._jobs:
                self._jobs = normalized_jobs
                collections_changed = True

        events = payload.get("events")
        if isinstance(events, list):
            normalized_events = [
                dict(item) for item in events if isinstance(item, dict)
            ]
            if normalized_events != self._events:
                self._events = normalized_events
                collections_changed = True

        notes = payload.get("notes")
        if isinstance(notes, list):
            normalized_notes = [dict(item) for item in notes if isinstance(item, dict)]
            if normalized_notes != self._notes:
                self._notes = normalized_notes
                collections_changed = True

        settings = payload.get("settings")
        if isinstance(settings, dict):
            normalized_settings = dict(settings)
            if normalized_settings != self._settings:
                self._settings = normalized_settings
                collections_changed = True

        tools = payload.get("tools")
        if isinstance(tools, list):
            normalized_tools = [dict(item) for item in tools if isinstance(item, dict)]
            if normalized_tools != self._tools:
                self._tools = normalized_tools
                collections_changed = True

        active_workspace = payload.get("active_workspace")
        if isinstance(active_workspace, dict):
            collections_changed = (
                self._apply_active_workspace_summary(active_workspace)
                or collections_changed
            )

        active_request_state = payload.get("active_request_state")
        if isinstance(active_request_state, dict):
            normalized_request_state = dict(active_request_state)
            if normalized_request_state != self._active_request_state:
                self._active_request_state = normalized_request_state
                collections_changed = True

        active_task = payload.get("active_task")
        if isinstance(active_task, dict):
            normalized_active_task = dict(active_task)
            if normalized_active_task != self._active_task:
                self._active_task = normalized_active_task
                collections_changed = True

        recent_context_resolutions = payload.get("recent_context_resolutions")
        if isinstance(recent_context_resolutions, list):
            normalized_resolutions = [
                dict(item)
                for item in recent_context_resolutions
                if isinstance(item, dict)
            ]
            if normalized_resolutions != self._recent_context_resolutions:
                self._recent_context_resolutions = normalized_resolutions
                collections_changed = True

        if self._pending_activity == "chat":
            pending_response = self._pending_chat_response_message(self._history)
            if pending_response is not None:
                self._pending_activity = None
                self._pending_chat_echo = None
                self._pending_chat_anchor_message_id = None
                self._set_assistant_state("idle")
                self._status_line = self._message_micro(pending_response)
        elif self._pending_activity == "note":
            self._pending_activity = None
            self._set_assistant_state("idle")
            self._status_line = "Logbook entry secured."

        if collections_changed or (
            status_changed and self._module_requires_live_status_refresh()
        ):
            self._rebuild_surface_models()
            self.collectionsChanged.emit()

    def apply_stream_event(self, payload: dict[str, Any]) -> None:
        event = dict(payload)
        cursor = (
            event.get("cursor")
            if isinstance(event.get("cursor"), int)
            else event.get("event_id")
        )
        if not isinstance(cursor, int):
            return
        normalized_events = [
            dict(item) for item in self._events if isinstance(item, dict)
        ]
        without_duplicate = [
            item
            for item in normalized_events
            if int(item.get("cursor") or item.get("event_id") or -1) != cursor
        ]
        without_duplicate.append(event)
        without_duplicate.sort(
            key=lambda item: int(item.get("cursor") or item.get("event_id") or 0)
        )
        retention_limit = max(
            32, min(256, int(self._event_stream_state().get("capacity", 64) or 64))
        )
        self._events = without_duplicate[-retention_limit:]

        visibility = str(event.get("visibility_scope", "")).strip().lower()
        severity = str(event.get("severity", event.get("level", ""))).strip().lower()
        message = str(event.get("message", "")).strip()
        event_type = str(event.get("event_type") or event.get("type") or "").strip()
        is_voice_event = event_type.startswith("voice.")
        if visibility in {"ghost_hint", "operator_blocking"} and message:
            self._status_line = message
            if (
                severity in {"warning", "error", "critical"}
                and self._pending_activity is None
            ):
                self._set_assistant_state("warning")
            self.statusChanged.emit()

        if is_voice_event:
            if self._apply_voice_state_from_stream_event(event):
                self._apply_voice_assistant_state()
                self.voiceStateChanged.emit()
            return

        if visibility != "internal_only" or self._module_requires_live_status_refresh():
            self._queue_stream_collections_changed()

    def apply_voice_action_result(self, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "voice.action").strip()
        result = (
            payload.get("result") if isinstance(payload.get("result"), dict) else {}
        )
        voice_status = (
            payload.get("voice") if isinstance(payload.get("voice"), dict) else None
        )
        if voice_status is not None:
            next_status = dict(self._status)
            next_status["voice"] = dict(voice_status)
            self._status = next_status
            self._refresh_voice_state()
        readonly_status_action = action in {
            "voice.getReadinessReport",
            "voice.getLastPipelineSummary",
        }
        ok = bool(result.get("ok", False)) or readonly_status_action
        status = (
            str(result.get("status") or result.get("final_status") or "")
            .replace("_", " ")
            .strip()
        )
        error_code = str(result.get("error_code") or "").replace("_", " ").strip()
        if readonly_status_action:
            readiness = (
                self._voice_state.get("readiness")
                if isinstance(self._voice_state.get("readiness"), dict)
                else {}
            )
            self._status_line = str(
                readiness.get("user_facing_reason") or "Voice readiness refreshed."
            )
        elif ok:
            self._status_line = self._voice_success_status_line(action, status)
        else:
            self._status_line = self._voice_failure_status_line(
                action, status, error_code
            )
        self._apply_voice_assistant_state()
        self._rebuild_surface_models()
        self.voiceStateChanged.emit()
        self.statusChanged.emit()
        self.collectionsChanged.emit()

    def apply_stream_state(self, payload: dict[str, Any]) -> None:
        phase = str(payload.get("phase", "")).strip().lower()
        source = str(payload.get("source", "")).strip().lower()
        if source == "client":
            if phase == "connecting":
                self._connection_state = "connecting"
                if self._pending_activity is None:
                    self._status_line = "Reacquiring operational signal."
            elif phase == "reconnecting":
                self._connection_state = "disrupted"
                if self._pending_activity is None:
                    self._status_line = "Operational stream reconnecting."
            elif phase == "stopped" and self._pending_activity is None:
                self._status_line = "Operational stream paused."
        elif phase == "connected":
            self._connection_state = "connected"
        self.statusChanged.emit()

    def apply_stream_gap(self, payload: dict[str, Any]) -> None:
        del payload
        if self._pending_activity is None:
            self._status_line = "Recent event window expired; refreshing from snapshot."
            self.statusChanged.emit()

    def _queue_stream_collections_changed(self) -> None:
        if self._stream_collections_timer.isActive():
            return
        self._stream_collections_timer.start()

    def _flush_stream_collections_changed(self) -> None:
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def _apply_voice_state_from_stream_event(self, event: dict[str, Any]) -> bool:
        event_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        voice_payload = event.get("voice") if isinstance(event.get("voice"), dict) else None
        if voice_payload is None:
            candidate = event_payload.get("voice")
            if isinstance(candidate, dict):
                voice_payload = candidate
        if voice_payload is None:
            status_payload = event_payload.get("status")
            if isinstance(status_payload, dict) and isinstance(status_payload.get("voice"), dict):
                voice_payload = status_payload.get("voice")
        if voice_payload is None:
            metadata_payload = event_payload.get("metadata")
            if isinstance(metadata_payload, dict):
                candidate = metadata_payload.get("voice")
                if isinstance(candidate, dict):
                    voice_payload = candidate
        if voice_payload is None:
            anchor_keys = {
                "voice_anchor_state",
                "speaking_visual_active",
                "voice_motion_intensity",
                "voice_audio_level",
                "voice_audio_level_raw",
                "voice_instant_audio_level",
                "voice_fast_audio_level",
                "voice_smoothed_output_level",
                "voice_visual_drive_level",
                "voice_visual_drive_peak",
                "voice_center_blob_drive",
                "voice_center_blob_scale_drive",
                "voice_center_blob_scale",
                "voice_outer_speaking_motion",
                "voice_visual_gain",
                "audioDriveLevel",
                "voice_audio_reactive_available",
                "voice_audio_reactive_source",
                "voice_anchor_debug",
                "streaming_tts_active",
                "live_playback_active",
                "first_audio_started",
                "active_playback_status",
            }
            direct_voice = {
                key: event_payload.get(key)
                for key in anchor_keys
                if key in event_payload
            }
            voice_payload = direct_voice or None
        if not isinstance(voice_payload, dict) or not voice_payload:
            return False
        next_status = dict(self._status)
        current_voice = (
            dict(next_status.get("voice"))
            if isinstance(next_status.get("voice"), dict)
            else {}
        )
        current_voice.update(voice_payload)
        next_status["voice"] = current_voice
        if next_status == self._status:
            return False
        self._status = next_status
        return self._refresh_voice_state()

    def apply_chat_result(self, payload: dict[str, Any]) -> None:
        user_message = payload.get("user_message")
        assistant_message = payload.get("assistant_message")
        additions: list[dict[str, Any]] = []
        if isinstance(user_message, dict):
            additions.append(self._normalize_message(user_message))
        if isinstance(assistant_message, dict):
            normalized_assistant = self._normalize_message(assistant_message)
            additions.append(normalized_assistant)
            self._status_line = self._message_micro(normalized_assistant)

        if additions:
            self._merge_history_messages(additions)
        active_request_state = payload.get("active_request_state")
        if isinstance(active_request_state, dict):
            self._active_request_state = dict(active_request_state)
        active_task = payload.get("active_task")
        if isinstance(active_task, dict):
            self._active_task = dict(active_task)
        recent_context_resolutions = payload.get("recent_context_resolutions")
        if isinstance(recent_context_resolutions, list):
            self._recent_context_resolutions = [
                dict(item)
                for item in recent_context_resolutions
                if isinstance(item, dict)
            ]
        self._pending_activity = None
        self._pending_chat_echo = None
        self._pending_chat_anchor_message_id = None
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
        if action_type == "workspace_clear":
            self._workspace_focus = {}
            self._workspace_state_hint = ""
            self._opened_items = []
            self._active_opened_item_id = None
            self._active_module_key = "chartroom"
            self._active_workspace_section_key = self._default_workspace_section_key(
                "chartroom"
            )
            self._status_line = "Workspace cleared."
            self.statusChanged.emit()
            self._rebuild_surface_models()
            self.collectionsChanged.emit()
            return
        if action_type == "workspace_focus":
            module = (
                str(action.get("module", self._active_module_key)).strip().lower()
                or self._active_module_key
            )
            state_hint = self._normalize_workspace_state_hint(action.get("state_hint"))
            section = self._resolved_workspace_section(
                module=module,
                section=action.get(
                    "section", self._default_workspace_section_key(module)
                ),
                state_hint=state_hint,
            )
            self._active_module_key = module
            self._workspace_state_hint = state_hint
            self._active_workspace_section_key = (
                section or self._default_workspace_section_key(module)
            )
            self._mode = "deck"
            self._status_line = self._workspace_focus_status_line(
                self._active_module_label(), state_hint
            )
            self.modeChanged.emit()
            self.statusChanged.emit()
            self._rebuild_surface_models()
            self.collectionsChanged.emit()
            return
        if action_type != "workspace_open":
            return

        module = (
            str(action.get("module", self._active_module_key)).strip().lower()
            or self._active_module_key
        )
        section = (
            str(action.get("section", self._default_workspace_section_key(module)))
            .strip()
            .lower()
        )
        item = action.get("item")
        if not isinstance(item, dict):
            return

        normalized_item = self._normalize_workspace_item(
            item, module=module, section=section
        )

        self._upsert_opened_item(normalized_item)
        self._active_module_key = module
        self._workspace_state_hint = ""
        self._active_workspace_section_key = (
            section or self._default_workspace_section_key(module)
        )
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

    def setSelectionContext(self, descriptor: Any) -> None:
        self._selection_context = self._normalize_input_context_descriptor(descriptor)

    def clearSelectionContext(self) -> None:
        self._selection_context = {}

    def setClipboardContext(self, descriptor: Any) -> None:
        self._clipboard_context = self._normalize_input_context_descriptor(descriptor)

    def clearClipboardContext(self) -> None:
        self._clipboard_context = {}

    def input_context_payload(self) -> dict[str, Any]:
        clipboard = dict(self._clipboard_context)
        if not clipboard:
            clipboard = self._clipboard_snapshot()
        return {
            "selection": dict(self._selection_context),
            "clipboard": clipboard,
        }

    def _normalize_input_context_descriptor(self, descriptor: Any) -> dict[str, Any]:
        if isinstance(descriptor, dict):
            kind = str(descriptor.get("kind") or "").strip()
            value = descriptor.get("value")
            preview = str(descriptor.get("preview") or "").strip()
            if not kind and value is None:
                return {}
            if not preview and value is not None:
                preview = " ".join(str(value).split()).strip()[:160]
            return {
                "kind": kind or "text",
                "value": value,
                "preview": preview,
            }
        text = " ".join(str(descriptor or "").split()).strip()
        if not text:
            return {}
        return {
            "kind": "text",
            "value": text,
            "preview": text[:160],
        }

    def _clipboard_snapshot(self) -> dict[str, Any]:
        app = QtGui.QGuiApplication.instance()
        if app is None:
            return {}
        clipboard = app.clipboard()
        if clipboard is None:
            return {}
        text = " ".join(str(clipboard.text() or "").split()).strip()
        if not text:
            return {}
        return {
            "kind": "text",
            "value": text,
            "preview": text[:160],
        }

    def _apply_workspace_restore(self, action: dict[str, Any]) -> None:
        self._restore_workspace_state(action)
        self.modeChanged.emit()
        self.statusChanged.emit()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def _restore_workspace_state(self, action: dict[str, Any]) -> None:
        module = str(action.get("module", "chartroom")).strip().lower() or "chartroom"
        state_hint = self._normalize_workspace_state_hint(action.get("state_hint"))
        section = self._resolved_workspace_section(
            module=module,
            section=action.get("section", self._default_workspace_section_key(module)),
            state_hint=state_hint,
        )
        workspace = action.get("workspace")
        if isinstance(workspace, dict):
            self._workspace_focus = dict(workspace)
        self._workspace_state_hint = state_hint
        items = action.get("items", [])
        self._opened_items = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized_item = self._normalize_workspace_item(
                    item, module=module, section=section
                )
                self._opened_items.append(normalized_item)
        active_item_id = str(action.get("active_item_id", "")).strip()
        if active_item_id and any(
            item.get("itemId") == active_item_id for item in self._opened_items
        ):
            self._active_opened_item_id = active_item_id
        else:
            self._active_opened_item_id = (
                self._opened_items[0]["itemId"] if self._opened_items else None
            )
        self._active_module_key = module
        self._active_workspace_section_key = (
            section or self._default_workspace_section_key(module)
        )
        self._mode = "deck"
        workspace_name = (
            str(self._workspace_focus.get("name", "workspace")).strip() or "workspace"
        )
        self._status_line = f"Holding {workspace_name} in the Deck."

    def _apply_active_workspace_summary(self, summary: dict[str, Any]) -> bool:
        before_state = self._workspace_refresh_signature()
        workspace = summary.get("workspace")
        if not isinstance(workspace, dict) or not workspace:
            return False

        action = (
            summary.get("action") if isinstance(summary.get("action"), dict) else {}
        )
        current_workspace_id = str(self._workspace_focus.get("workspaceId", "")).strip()
        incoming_workspace_id = str(workspace.get("workspaceId", "")).strip()
        if not current_workspace_id and not self._opened_items:
            if action:
                self._restore_workspace_state(action)
                return self._workspace_refresh_signature() != before_state

        if (
            current_workspace_id
            and incoming_workspace_id
            and current_workspace_id != incoming_workspace_id
        ):
            return False

        previous_module = self._active_module_key
        self._workspace_focus = dict(workspace)
        active_item = (
            summary.get("active_item")
            if isinstance(summary.get("active_item"), dict)
            else {}
        )
        opened_items = summary.get("opened_items")
        module = (
            str(
                action.get("module", active_item.get("module", self._active_module_key))
            )
            .strip()
            .lower()
            or self._active_module_key
        )
        candidate_state_hint = self._normalize_workspace_state_hint(
            summary.get("state_hint")
            or action.get("state_hint")
            or workspace.get("stateHint")
            or workspace.get("state_hint")
        )
        state_hint = candidate_state_hint or (
            self._workspace_state_hint if module == previous_module else ""
        )
        section = self._resolved_workspace_section(
            module=module,
            section=action.get(
                "section",
                active_item.get("section", self._active_workspace_section_key),
            ),
            state_hint=state_hint,
        )
        self._active_module_key = module
        self._workspace_state_hint = state_hint
        self._active_workspace_section_key = (
            section or self._default_workspace_section_key(module)
        )

        items_source = (
            opened_items if isinstance(opened_items, list) else action.get("items")
        )
        if isinstance(items_source, list):
            self._opened_items = [
                self._normalize_workspace_item(item, module=module, section=section)
                for item in items_source
                if isinstance(item, dict)
            ]
        active_item_id = (
            str(active_item.get("itemId", "")).strip()
            or str(action.get("active_item_id", "")).strip()
        )
        if active_item_id and any(
            item.get("itemId") == active_item_id for item in self._opened_items
        ):
            self._active_opened_item_id = active_item_id
        elif self._opened_items:
            self._active_opened_item_id = (
                str(self._opened_items[0].get("itemId", "")).strip() or None
            )
        else:
            self._active_opened_item_id = None
        return self._workspace_refresh_signature() != before_state

    def _normalize_workspace_item(
        self, item: dict[str, Any], *, module: str, section: str
    ) -> dict[str, Any]:
        normalized_item = dict(item)
        normalized_item.setdefault("itemId", str(uuid4()))
        normalized_item.setdefault("kind", "text")
        normalized_item.setdefault("viewer", normalized_item.get("kind", "text"))
        normalized_item.setdefault("title", "Untitled")
        normalized_item.setdefault("subtitle", "")
        normalized_item["module"] = (
            str(normalized_item.get("module", module)).strip().lower() or module
        )
        normalized_item["section"] = (
            str(normalized_item.get("section", section)).strip().lower() or section
        )
        return normalized_item

    def _normalize_workspace_state_hint(self, value: Any) -> str:
        normalized = str(value or "").strip().lower().replace("_", "-")
        return normalized

    def _workspace_state_hint_label(self, value: str) -> str:
        normalized = self._normalize_workspace_state_hint(value)
        if not normalized:
            return ""
        return normalized.replace("-", " ").title()

    def _systems_section_from_state_hint(self, state_hint: str) -> str:
        mapping = {
            "machine": "runtime",
            "power": "runtime",
            "power-projection": "runtime",
            "resources": "runtime",
            "network": "network",
            "network-throughput": "network",
            "network-diagnosis": "network",
            "power-diagnosis": "diagnostics",
            "resource-diagnosis": "diagnostics",
            "storage-diagnosis": "diagnostics",
        }
        return mapping.get(self._normalize_workspace_state_hint(state_hint), "")

    def _resolved_workspace_section(
        self, *, module: str, section: Any, state_hint: str = ""
    ) -> str:
        normalized_module = str(module or "").strip().lower() or "chartroom"
        normalized_section = str(section or "").strip().lower()
        if normalized_module == "systems" and normalized_section in {"", "overview"}:
            hinted_section = self._systems_section_from_state_hint(state_hint)
            if hinted_section:
                return hinted_section
        return normalized_section or self._default_workspace_section_key(
            normalized_module
        )

    def _workspace_focus_status_line(
        self, module_label: str, state_hint: str = ""
    ) -> str:
        hint_label = self._workspace_state_hint_label(state_hint)
        if hint_label:
            return f"Holding {module_label} in the Deck: {hint_label}."
        return f"Holding {module_label} in the Deck."

    def _workspace_surface_cluster(self, surface: str) -> dict[str, Any]:
        surface_content = self._workspace_focus.get("surfaceContent", {})
        if not isinstance(surface_content, dict):
            return {}
        cluster = surface_content.get(surface, {})
        return dict(cluster) if isinstance(cluster, dict) else {}

    def _workspace_surface_items(self, surface: str) -> list[dict[str, Any]]:
        cluster = self._workspace_surface_cluster(surface)
        items = cluster.get("items", [])
        return (
            [dict(item) for item in items if isinstance(item, dict)]
            if isinstance(items, list)
            else []
        )

    def _workspace_refresh_signature(self) -> dict[str, Any]:
        return {
            "workspace_focus": copy.deepcopy(self._workspace_focus),
            "workspace_state_hint": self._workspace_state_hint,
            "opened_items": copy.deepcopy(self._opened_items),
            "active_opened_item_id": self._active_opened_item_id,
            "active_module_key": self._active_module_key,
            "active_workspace_section_key": self._active_workspace_section_key,
        }

    def _module_requires_live_status_refresh(self) -> bool:
        return bool(self._bridge_authority_state()) or self._active_module_key in {
            "systems",
            "watch",
            "signals",
        }

    def _refresh_voice_state(self) -> bool:
        next_state = build_voice_ui_state(self._status)
        if next_state == self._voice_state:
            return False
        self._voice_state = next_state
        return True

    def _apply_voice_assistant_state(self) -> None:
        if self._pending_activity is not None or self._ghost_capture_active:
            return
        if (
            not self._voice_surface_visible()
            and self._voice_state.get("voice_core_state") == "warning"
        ):
            return
        core_state = (
            str(self._voice_state.get("voice_core_state") or "").strip().lower()
        )
        if core_state in VOICE_STATES:
            self._set_assistant_state(core_state)

    def _voice_success_status_line(self, action: str, status: str) -> str:
        normalized = action.strip().lower()
        if "startpushtotalkcapture" in normalized:
            return "Recording one utterance."
        if "stoppushtotalkcapture" in normalized:
            return "Capture stopped."
        if "cancelcapture" in normalized:
            return "Capture cancelled."
        if (
            "submitcapturedaudioturn" in normalized
            or "captureandsubmitturn" in normalized
        ):
            return "Routing captured audio through Core."
        if "stopplayback" in normalized:
            return "Playback stop requested."
        if "stopspeaking" in normalized:
            return "Stopped."
        if "suppresscurrentresponse" in normalized:
            return "Response remains available visually."
        if "mutespokenresponses" in normalized:
            return "Speech muted."
        if "unmutespokenresponses" in normalized:
            return "Speech unmuted."
        return f"Voice action {status or 'completed'}."

    def _voice_failure_status_line(
        self, action: str, status: str, error_code: str
    ) -> str:
        normalized = action.strip().lower()
        reason = error_code or status or "unavailable"
        if "capture" in normalized:
            return f"Capture {reason}."
        if "playback" in normalized:
            return f"Playback {reason}."
        if (
            "speaking" in normalized
            or "spokenresponses" in normalized
            or "suppresscurrentresponse" in normalized
        ):
            return f"Speech {reason}."
        return f"Voice action {reason}."

    def _voice_actions_first(
        self, actions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not self._voice_surface_visible():
            return actions
        ghost = (
            self._voice_state.get("ghost")
            if isinstance(self._voice_state.get("ghost"), dict)
            else {}
        )
        voice_actions = [
            dict(item) for item in ghost.get("actions") or [] if isinstance(item, dict)
        ]
        return self._dedupe_surface_actions(voice_actions + actions)[:5]

    def _voice_stations(self, stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self._voice_surface_visible():
            return stations
        station = build_voice_command_station(self._voice_state)
        if self._voice_state.get("active_capture_id"):
            return [station] + [
                item
                for item in stations
                if item.get("stationId") != station["stationId"]
            ][:2]
        return [
            item for item in stations if item.get("stationId") != station["stationId"]
        ] + [station]

    def _voice_surface_visible(self) -> bool:
        voice_status = (
            self._status.get("voice")
            if isinstance(self._status.get("voice"), dict)
            else {}
        )
        if not voice_status:
            return False
        if bool(voice_status.get("enabled")):
            return True
        return any(
            bool(self._voice_state.get(key))
            for key in (
                "capture_enabled",
                "active_capture_id",
                "last_capture_id",
                "last_transcription_id",
                "last_core_result_state",
                "last_synthesis_status",
                "last_playback_status",
            )
        )

    def _dedupe_surface_actions(
        self, actions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for action in actions:
            key = (
                str(action.get("label", "")),
                str(action.get("localAction", action.get("sendText", ""))),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(action)
        return deduped

    def _rebuild_surface_models(self) -> None:
        display_history = self._display_history()
        self._ghost_messages = [
            self._ghost_message_variant(item) for item in display_history[-3:]
        ]
        self._context_cards = self._build_context_cards()
        command_surface = self._build_command_surface()
        self._ghost_primary_card = dict(command_surface.get("ghostPrimaryCard") or {})
        self._ghost_action_strip = self._voice_actions_first(
            list(command_surface.get("ghostActionStrip") or [])
        )
        self._request_composer = dict(command_surface.get("requestComposer") or {})
        self._route_inspector = dict(command_surface.get("routeInspector") or {})
        self._command_stations = self._voice_stations(
            [
                dict(item)
                for item in command_surface.get("deckStations") or []
                if isinstance(item, dict)
            ]
        )
        self._command_rail_items = self._build_command_rail_items()
        self._workspace_sections = self._build_workspace_sections()
        self._workspace_rail_items = self._build_workspace_rail_items()
        self._workspace_canvas = self._build_workspace_canvas()
        self._deck_modules = self._build_deck_modules()
        self._active_deck_module = (
            self._deck_modules[0]
            if self._deck_modules
            else self._build_module(self._active_module_key)
        )
        self._deck_support_modules = self._deck_modules[1:]
        self._deck_panels, self._hidden_deck_panels = self._build_deck_panels()
        self._deck_panel_catalog = self._build_deck_panel_catalog()
        self._ghost_corner_readouts = self._build_ghost_corner_readouts()
        self._status_strip_items = self._build_status_strip_items()

    def _build_command_surface(self) -> dict[str, Any]:
        return build_command_surface_model(
            active_request_state=self._active_request_state,
            active_task=self._active_task,
            recent_context_resolutions=self._recent_context_resolutions,
            latest_message=self._latest_assistant_message(),
            status=self._status,
            workspace_focus=self._workspace_focus,
        )

    def _voice_context_cards(self) -> list[dict[str, Any]]:
        if not self._voice_surface_visible():
            return []
        ghost = (
            self._voice_state.get("ghost")
            if isinstance(self._voice_state.get("ghost"), dict)
            else {}
        )
        title = "Voice Capture"
        body = str(ghost.get("primary_label") or "").strip()
        if not body:
            return []
        subtitle = (
            str(self._voice_state.get("capture_provider_kind") or "voice")
            .replace("_", " ")
            .title()
        )
        return [
            {
                "title": title,
                "subtitle": subtitle,
                "body": body,
                "actions": list(ghost.get("actions") or []),
            }
        ]

    def _build_context_cards(self) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        cards.extend(self._voice_context_cards())
        cards.extend(self._bridge_authority_context_cards())
        lifecycle = self._lifecycle_state()
        bootstrap = (
            lifecycle.get("bootstrap")
            if isinstance(lifecycle.get("bootstrap"), dict)
            else {}
        )
        migration = (
            lifecycle.get("migration")
            if isinstance(lifecycle.get("migration"), dict)
            else {}
        )
        resolution_plan = (
            bootstrap.get("resolution_plan")
            if isinstance(bootstrap.get("resolution_plan"), dict)
            else {}
        )
        resolution_state = (
            bootstrap.get("resolution_state")
            if isinstance(bootstrap.get("resolution_state"), dict)
            else {}
        )
        uninstall_plan = (
            lifecycle.get("uninstall_plan")
            if isinstance(lifecycle.get("uninstall_plan"), dict)
            else {}
        )
        destructive_cleanup_plan = (
            uninstall_plan.get("destructive_cleanup_plan")
            if isinstance(uninstall_plan.get("destructive_cleanup_plan"), dict)
            else {}
        )
        lifecycle_hold = str(
            bootstrap.get("lifecycle_hold_reason") or migration.get("hold_reason") or ""
        ).strip()
        if lifecycle_hold:
            cards.append(
                {
                    "title": "Lifecycle Hold",
                    "subtitle": str(migration.get("status", "hold"))
                    .replace("_", " ")
                    .title(),
                    "body": lifecycle_hold,
                }
            )
        if resolution_plan:
            resolution_body = str(
                resolution_state.get("last_resolution_summary")
                or resolution_plan.get("summary")
                or resolution_plan.get("operator_action_notes")
                or ""
            ).strip()
            if resolution_body:
                cards.append(
                    {
                        "title": "Resolution Option",
                        "subtitle": str(
                            resolution_plan.get("resolution_kind")
                            or ("manual_only" if resolution_plan else "")
                        )
                        .replace("_", " ")
                        .title(),
                        "body": resolution_body,
                    }
                )
        cleanup_body = str(
            destructive_cleanup_plan.get("operator_summary") or ""
        ).strip()
        if cleanup_body:
            cards.append(
                {
                    "title": "Cleanup Confirmation",
                    "subtitle": "Destructive",
                    "body": cleanup_body,
                }
            )
        trust_state = (
            self._active_request_state.get("trust")
            if isinstance(self._active_request_state.get("trust"), dict)
            else {}
        )
        trust_decision = str(trust_state.get("decision", "")).strip().lower()
        trust_message = str(trust_state.get("operator_message", "")).strip()
        trust_scope = str(trust_state.get("suggested_scope", "")).strip()
        if (
            trust_state
            and trust_message
            and trust_decision in {"confirmation_required", "downgraded"}
        ):
            cards.append(
                {
                    "title": "Approval Needed",
                    "subtitle": (
                        trust_scope or str(trust_state.get("approval_state", "pending"))
                    )
                    .replace("_", " ")
                    .title(),
                    "body": trust_message,
                }
            )
        if self._active_task:
            ghost_summary = (
                self._active_task.get("ghostSummary")
                if isinstance(self._active_task.get("ghostSummary"), dict)
                else {}
            )
            title = str(
                ghost_summary.get("title") or self._active_task.get("title") or ""
            ).strip()
            body = str(
                ghost_summary.get("body")
                or self._active_task.get("whereLeftOff")
                or self._active_task.get("latestSummary")
                or ""
            ).strip()
            subtitle = str(
                ghost_summary.get("subtitle") or self._active_task.get("state") or ""
            ).strip()
            if title and body:
                cards.append(
                    {
                        "title": title,
                        "subtitle": subtitle.replace("_", " ").title(),
                        "body": body,
                    }
                )
        for authority_card in self._bridge_authority_ghost_cards():
            if len(cards) >= 2:
                break
            title = str(authority_card.get("title") or "").strip()
            body = str(authority_card.get("body") or "").strip()
            if not title or not body:
                continue
            if any(
                card.get("title") == title and card.get("body") == body
                for card in cards
            ):
                continue
            cards.append(
                {
                    "title": title,
                    "subtitle": str(
                        authority_card.get("subtitle")
                        or authority_card.get("resultState")
                        or ""
                    )
                    .replace("_", " ")
                    .title(),
                    "body": body,
                    "familyId": str(authority_card.get("familyId") or ""),
                    "routeFamily": str(authority_card.get("routeFamily") or ""),
                    "actions": list(authority_card.get("actions") or []),
                }
            )
        latest_message = self._latest_assistant_message()
        if latest_message is not None:
            metadata = (
                latest_message.get("metadata")
                if isinstance(latest_message.get("metadata"), dict)
                else {}
            )
            planner_debug = (
                metadata.get("planner_debug")
                if isinstance(metadata.get("planner_debug"), dict)
                else {}
            )
            software_debug = (
                planner_debug.get("software_control")
                if isinstance(planner_debug.get("software_control"), dict)
                else {}
            )
            if software_debug.get("candidate"):
                result = (
                    software_debug.get("result")
                    if isinstance(software_debug.get("result"), dict)
                    else {}
                )
                trace = (
                    software_debug.get("trace")
                    if isinstance(software_debug.get("trace"), dict)
                    else {}
                )
                status = (
                    str(
                        result.get("status")
                        or trace.get("execution_status")
                        or "software"
                    )
                    .replace("_", " ")
                    .strip()
                )
                subtitle = status.title() if status else "Software"
                body = str(
                    latest_message.get("microResponse")
                    or latest_message.get("fullResponse")
                    or latest_message.get("content")
                    or "Software bearings are ready."
                ).strip()
                cards.append(
                    {
                        "title": self._message_bearing_title(latest_message),
                        "subtitle": subtitle,
                        "body": body,
                    }
                )
                return cards
        latest_job = self._jobs[0] if self._jobs else None
        if latest_job is not None and len(cards) < 2:
            summary = ""
            result = latest_job.get("result")
            if isinstance(result, dict):
                summary = str(result.get("summary", ""))
            if not summary:
                summary = (
                    str(latest_job.get("error", "")) or "Awaiting further bearings."
                )
            cards.append(
                {
                    "title": self._module_label(
                        str(latest_job.get("tool_name", "action"))
                    ),
                    "subtitle": str(latest_job.get("status", "pending")).title(),
                    "body": summary,
                }
            )

        latest_event = self._latest_surface_event()
        if latest_event is not None and len(cards) < 2:
            cards.append(
                {
                    "title": "Signals",
                    "subtitle": str(
                        latest_event.get("severity", latest_event.get("level", "INFO"))
                    )
                    .replace("_", " ")
                    .title(),
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
                "summary": self._workspace_section_summary(
                    self._active_module_key, key
                ),
            }
            for key, label, eyebrow in sections
        ]

    def _build_workspace_canvas(self) -> dict[str, Any]:
        view_kind = self._workspace_canvas_view_kind()
        return {
            "key": self._active_module_key,
            "sectionKey": self._active_workspace_section_key,
            "eyebrow": self._workspace_canvas_eyebrow(),
            "title": self._workspace_canvas_title(),
            "summary": self._workspace_canvas_summary(),
            "body": self._workspace_canvas_body(),
            "chips": self._workspace_canvas_chips(),
            "viewKind": view_kind,
            "stats": self._workspace_canvas_stats(),
            "factGroups": self._workspace_canvas_fact_groups(),
            "networkDisplay": self._network_display_data(),
            "lanes": self._workspace_canvas_watch_lanes(),
            "timeline": self._workspace_canvas_timeline(),
            "items": self._workspace_canvas_items(),
            "highlights": self._workspace_canvas_highlights(),
            "panels": self._workspace_canvas_panels(),
            "taskGroups": self._workspace_canvas_task_groups(),
            "columns": self._workspace_canvas_columns(),
            "openedItems": list(self._opened_items),
            "activeItem": self._get_active_opened_item(),
        }

    def _build_deck_panels(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        blueprints = self._default_deck_panel_specs()
        scope_state = self._ensure_layout_scope_state()
        merged_panels = self._merged_deck_panel_map(scope_state)
        visible: list[dict[str, Any]] = []
        hidden: list[dict[str, Any]] = []

        for blueprint in blueprints:
            panel_id = blueprint["panelId"]
            merged = dict(merged_panels.get(panel_id, blueprint))
            merged["visible"] = not bool(merged.get("hidden", False))
            if merged["hidden"]:
                hidden.append(merged)
            else:
                visible.append(merged)

        return visible, hidden

    def _build_deck_panel_catalog(self) -> list[dict[str, Any]]:
        merged_panels = self._merged_deck_panel_map()
        catalog: list[dict[str, Any]] = []
        for panel_id, panel in merged_panels.items():
            catalog.append(
                {
                    "panelId": panel_id,
                    "title": str(
                        panel.get("title", panel_id.replace("-", " ").title())
                    ),
                    "subtitle": str(panel.get("subtitle", "")),
                    "contentKind": str(panel.get("contentKind", "workspace-section")),
                    "hidden": bool(panel.get("hidden", False)),
                    "collapsed": bool(panel.get("collapsed", False)),
                    "pinned": bool(panel.get("pinned", False)),
                }
            )
        catalog.sort(key=lambda item: (item["hidden"], item["title"].lower()))
        return catalog

    def _default_deck_panel_specs(self) -> list[dict[str, Any]]:
        command_surface_active = bool(self._route_inspector or self._command_stations)
        panels: list[dict[str, Any]] = [
            {
                "panelId": "command-spine",
                "title": "Command Spine",
                "subtitle": "Conversation and command flow",
                "contentKind": "spine",
                "edge": "left",
                "gridX": 0,
                "gridY": 0,
                "colSpan": 3,
                "rowSpan": 8,
                "minCols": 2,
                "minRows": 4,
                "pinned": True,
            },
            {
                "panelId": "workspace-main",
                "title": str(
                    self._workspace_canvas.get("title", self._active_module_label())
                ),
                "subtitle": str(self._workspace_canvas.get("summary", "")),
                "contentKind": "workspace-section",
                "edge": "center",
                "gridX": 3,
                "gridY": 0,
                "colSpan": 5 if command_surface_active else 6,
                "rowSpan": 6,
                "minCols": 4,
                "minRows": 4,
                "canvasData": dict(self._workspace_canvas),
            },
        ]

        if self._route_inspector:
            panels.append(
                {
                    "panelId": "route-inspector",
                    "title": "Route Inspector",
                    "subtitle": str(self._route_inspector.get("subtitle", "")),
                    "contentKind": "route-inspector",
                    "edge": "right",
                    "gridX": 8 if command_surface_active else 9,
                    "gridY": 0,
                    "colSpan": 4 if command_surface_active else 3,
                    "rowSpan": 3 if command_surface_active else 6,
                    "minCols": 2,
                    "minRows": 3,
                    "inspectorData": dict(self._route_inspector),
                }
            )

        for station in self._command_stations:
            panel_id = str(station.get("stationId", "")).strip()
            if not panel_id:
                continue
            layout_slot = str(station.get("layoutSlot", "")).strip().lower()
            if layout_slot == "secondary":
                grid_x, grid_y, col_span, row_span = 8, 5, 4, 3
            elif layout_slot == "tertiary":
                grid_x, grid_y, col_span, row_span = 3, 6, 5, 2
            else:
                grid_x, grid_y, col_span, row_span = 8, 3, 4, 2
            panels.append(
                {
                    "panelId": panel_id,
                    "title": str(
                        station.get("title", panel_id.replace("-", " ").title())
                    ),
                    "subtitle": str(station.get("subtitle", "")),
                    "contentKind": "command-station",
                    "edge": "right" if layout_slot != "tertiary" else "bottom",
                    "gridX": grid_x,
                    "gridY": grid_y,
                    "colSpan": col_span,
                    "rowSpan": row_span,
                    "minCols": 3 if layout_slot == "tertiary" else 2,
                    "minRows": 2,
                    "stationData": dict(station),
                }
            )

        if not command_surface_active and self._active_module_key == "chartroom":
            if self._active_workspace_section_key != "active-thread":
                panels.append(
                    self._workspace_section_panel(
                        "thread-section", "chartroom", "active-thread", "left"
                    )
                )
            if self._active_workspace_section_key != "tasks":
                panels.append(
                    self._workspace_section_panel(
                        "tasks-section", "chartroom", "tasks", "bottom"
                    )
                )
            if self._opened_items and self._active_workspace_section_key not in {
                "opened-items",
                "open-pages",
                "working-set",
            }:
                panels.append(
                    self._workspace_section_panel(
                        "opened-items-section", "chartroom", "opened-items", "right"
                    )
                )
        elif not command_surface_active and self._active_module_key in {
            "files",
            "browser",
        }:
            panels.append(
                self._workspace_section_panel(
                    "tasks-section", "chartroom", "tasks", "bottom"
                )
            )
            if self._opened_items and self._active_workspace_section_key not in {
                "opened-items",
                "open-pages",
                "working-set",
            }:
                section_key = (
                    "references"
                    if self._active_module_key == "browser"
                    else "opened-items"
                )
                panels.append(
                    self._workspace_section_panel(
                        "opened-items-section",
                        self._active_module_key,
                        section_key,
                        "right",
                    )
                )
        elif not command_surface_active and self._active_module_key in {
            "systems",
            "watch",
            "signals",
        }:
            panels.append(
                self._workspace_section_panel(
                    "session-section", "chartroom", "session", "bottom"
                )
            )

        support_modules = (
            [] if command_surface_active else self._deck_support_modules[:3]
        )
        for module in support_modules:
            panels.append(
                {
                    "panelId": f"{module['key']}-module",
                    "title": str(
                        module.get(
                            "title",
                            self._module_label(str(module.get("key", "module"))),
                        )
                    ),
                    "subtitle": str(module.get("headline", "")),
                    "contentKind": "module",
                    "edge": "right",
                    "gridX": 9,
                    "gridY": 0,
                    "colSpan": 3,
                    "rowSpan": 3,
                    "minCols": 2,
                    "minRows": 3,
                    "moduleData": dict(module),
                }
            )

        preview_item = self._get_active_opened_item()
        if (
            not command_surface_active
            and preview_item
            and (
                self._active_module_key in {"files", "browser"}
                or self._active_workspace_section_key
                not in {"opened-items", "open-pages", "working-set"}
            )
        ):
            panels.append(
                {
                    "panelId": "preview-surface",
                    "title": "Preview",
                    "subtitle": str(preview_item.get("title", "Active item")),
                    "contentKind": "preview",
                    "edge": "right",
                    "gridX": 8,
                    "gridY": 0,
                    "colSpan": 4,
                    "rowSpan": 5,
                    "minCols": 3,
                    "minRows": 3,
                    "itemData": dict(preview_item),
                }
            )

        return self._dedupe_panels(panels)

    def _workspace_section_panel(
        self, panel_id: str, module_key: str, section_key: str, edge: str
    ) -> dict[str, Any]:
        canvas_data = self._build_workspace_canvas_for(module_key, section_key)
        return {
            "panelId": panel_id,
            "title": str(
                canvas_data.get("title", self._workspace_section_label(section_key))
            ),
            "subtitle": str(canvas_data.get("summary", "")),
            "contentKind": "workspace-section",
            "edge": edge,
            "gridX": 8 if edge == "right" else 3,
            "gridY": 5 if edge == "bottom" else 0,
            "colSpan": 4 if edge == "right" else 5,
            "rowSpan": 3,
            "minCols": 3,
            "minRows": 3,
            "canvasData": canvas_data,
        }

    def _build_workspace_canvas_for(
        self, module_key: str, section_key: str
    ) -> dict[str, Any]:
        previous_module = self._active_module_key
        previous_section = self._active_workspace_section_key
        self._active_module_key = module_key
        self._active_workspace_section_key = (
            section_key or self._default_workspace_section_key(module_key)
        )
        try:
            return self._build_workspace_canvas()
        finally:
            self._active_module_key = previous_module
            self._active_workspace_section_key = previous_section

    def _dedupe_panels(self, panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for panel in panels:
            panel_id = str(panel.get("panelId", "")).strip()
            if not panel_id or panel_id in seen:
                continue
            seen.add(panel_id)
            deduped.append(panel)
        return deduped

    def _default_panel_layouts(
        self, preset: str, panels: list[dict[str, Any]]
    ) -> dict[str, dict[str, int]]:
        ids = {panel["panelId"] for panel in panels}
        has_command_stations = any(
            str(panel.get("contentKind", "")) == "command-station" for panel in panels
        )
        layout: dict[str, dict[str, int]] = {
            "command-spine": {"gridX": 0, "gridY": 0, "colSpan": 3, "rowSpan": 8},
            "workspace-main": {
                "gridX": 3,
                "gridY": 2,
                "colSpan": 5 if has_command_stations else 6,
                "rowSpan": 5,
            },
            "route-inspector": {
                "gridX": 8 if has_command_stations else 9,
                "gridY": 0,
                "colSpan": 4 if has_command_stations else 3,
                "rowSpan": 3 if has_command_stations else 6,
            },
            "preview-surface": {"gridX": 8, "gridY": 0, "colSpan": 4, "rowSpan": 5},
            "thread-section": {"gridX": 3, "gridY": 6, "colSpan": 3, "rowSpan": 2},
            "tasks-section": {"gridX": 3, "gridY": 6, "colSpan": 5, "rowSpan": 2},
            "session-section": {"gridX": 3, "gridY": 6, "colSpan": 5, "rowSpan": 2},
            "opened-items-section": {
                "gridX": 8,
                "gridY": 5,
                "colSpan": 4,
                "rowSpan": 3,
            },
            "signals-module": {"gridX": 9, "gridY": 0, "colSpan": 3, "rowSpan": 3},
            "watch-module": {"gridX": 9, "gridY": 3, "colSpan": 3, "rowSpan": 3},
            "logbook-module": {"gridX": 8, "gridY": 5, "colSpan": 4, "rowSpan": 3},
            "systems-module": {"gridX": 8, "gridY": 0, "colSpan": 4, "rowSpan": 4},
            "files-module": {"gridX": 8, "gridY": 5, "colSpan": 4, "rowSpan": 3},
        }

        if preset == "systems-focus":
            layout.update(
                {
                    "command-spine": {
                        "gridX": 0,
                        "gridY": 0,
                        "colSpan": 2,
                        "rowSpan": 8,
                    },
                    "workspace-main": {
                        "gridX": 2,
                        "gridY": 2,
                        "colSpan": 7,
                        "rowSpan": 5,
                    },
                    "signals-module": {
                        "gridX": 9,
                        "gridY": 0,
                        "colSpan": 3,
                        "rowSpan": 3,
                    },
                    "watch-module": {
                        "gridX": 9,
                        "gridY": 3,
                        "colSpan": 3,
                        "rowSpan": 3,
                    },
                    "session-section": {
                        "gridX": 2,
                        "gridY": 6,
                        "colSpan": 7,
                        "rowSpan": 2,
                    },
                }
            )
        elif preset == "research-focus":
            layout.update(
                {
                    "command-spine": {
                        "gridX": 0,
                        "gridY": 0,
                        "colSpan": 3,
                        "rowSpan": 4,
                    },
                    "workspace-main": {
                        "gridX": 3,
                        "gridY": 2,
                        "colSpan": 5,
                        "rowSpan": 5,
                    },
                    "preview-surface": {
                        "gridX": 8,
                        "gridY": 0,
                        "colSpan": 4,
                        "rowSpan": 6,
                    },
                    "tasks-section": {
                        "gridX": 0,
                        "gridY": 4,
                        "colSpan": 3,
                        "rowSpan": 4,
                    },
                    "logbook-module": {
                        "gridX": 3,
                        "gridY": 6,
                        "colSpan": 5,
                        "rowSpan": 2,
                    },
                }
            )
        elif preset == "workspace-focus":
            layout.update(
                {
                    "command-spine": {
                        "gridX": 0,
                        "gridY": 0,
                        "colSpan": 3,
                        "rowSpan": 6,
                    },
                    "workspace-main": {
                        "gridX": 3,
                        "gridY": 2,
                        "colSpan": 5,
                        "rowSpan": 4,
                    },
                    "preview-surface": {
                        "gridX": 8,
                        "gridY": 0,
                        "colSpan": 4,
                        "rowSpan": 5,
                    },
                    "tasks-section": {
                        "gridX": 3,
                        "gridY": 5,
                        "colSpan": 5,
                        "rowSpan": 3,
                    },
                    "logbook-module": {
                        "gridX": 8,
                        "gridY": 5,
                        "colSpan": 4,
                        "rowSpan": 3,
                    },
                }
            )

        if has_command_stations:
            for panel in panels:
                if str(panel.get("contentKind", "")) != "command-station":
                    continue
                panel_id = str(panel.get("panelId", ""))
                slot = (
                    str(
                        panel.get("stationData", {}).get("layoutSlot")
                        if isinstance(panel.get("stationData"), dict)
                        else panel.get("layoutSlot", "")
                    )
                    .strip()
                    .lower()
                )
                if slot == "secondary":
                    layout[panel_id] = {
                        "gridX": 8,
                        "gridY": 5,
                        "colSpan": 4,
                        "rowSpan": 3,
                    }
                elif slot == "tertiary":
                    layout[panel_id] = {
                        "gridX": 3,
                        "gridY": 6,
                        "colSpan": 5,
                        "rowSpan": 2,
                    }
                else:
                    layout[panel_id] = {
                        "gridX": 8,
                        "gridY": 3,
                        "colSpan": 4,
                        "rowSpan": 2,
                    }

        return {
            panel_id: values for panel_id, values in layout.items() if panel_id in ids
        }

    def _deck_layout_presets(self) -> list[dict[str, str]]:
        return [
            {"key": "command-focus", "label": "Command"},
            {"key": "workspace-focus", "label": "Workspace"},
            {"key": "systems-focus", "label": "Systems"},
            {"key": "research-focus", "label": "Research"},
        ]

    def _deck_layout_preset(self) -> str:
        if self._active_module_key in {"systems", "watch", "signals"}:
            return "systems-focus"
        if (
            self._active_module_key in {"files", "browser"}
            or self._get_active_opened_item()
        ):
            return "research-focus"
        return "workspace-focus" if self._workspace_focus else "command-focus"

    def _deck_layout_scope_key(self) -> str:
        workspace_id = str(self._workspace_focus.get("workspaceId", "")).strip()
        if workspace_id:
            return f"workspace:{workspace_id}"
        return f"module:{self._active_module_key}"

    def _ensure_layout_scope_state(self) -> dict[str, Any]:
        layouts = self._deck_layout_store.setdefault("layouts", {})
        scope = self._deck_layout_scope_key()
        return layouts.setdefault(
            scope, {"preset": self._deck_layout_preset(), "panels": {}}
        )

    def _merged_deck_panel_map(
        self, scope_state: dict[str, Any] | None = None
    ) -> dict[str, dict[str, Any]]:
        blueprints = self._default_deck_panel_specs()
        active_scope = scope_state or self._ensure_layout_scope_state()
        preset = (
            str(active_scope.get("preset", self._deck_layout_preset())).strip()
            or self._deck_layout_preset()
        )
        default_layout = self._default_panel_layouts(preset, blueprints)
        stored_panels = active_scope.setdefault("panels", {})
        merged: dict[str, dict[str, Any]] = {}
        for blueprint in blueprints:
            panel_id = str(blueprint["panelId"])
            state = stored_panels.get(panel_id, {})
            panel = dict(blueprint)
            panel.update(
                {
                    "gridX": int(
                        state.get(
                            "gridX",
                            default_layout.get(panel_id, {}).get(
                                "gridX", blueprint["gridX"]
                            ),
                        )
                    ),
                    "gridY": int(
                        state.get(
                            "gridY",
                            default_layout.get(panel_id, {}).get(
                                "gridY", blueprint["gridY"]
                            ),
                        )
                    ),
                    "colSpan": int(
                        state.get(
                            "colSpan",
                            default_layout.get(panel_id, {}).get(
                                "colSpan", blueprint["colSpan"]
                            ),
                        )
                    ),
                    "rowSpan": int(
                        state.get(
                            "rowSpan",
                            default_layout.get(panel_id, {}).get(
                                "rowSpan", blueprint["rowSpan"]
                            ),
                        )
                    ),
                    "pinned": bool(state.get("pinned", blueprint.get("pinned", False))),
                    "collapsed": bool(
                        state.get("collapsed", blueprint.get("collapsed", False))
                    ),
                    "hidden": bool(state.get("hidden", blueprint.get("hidden", False))),
                }
            )
            merged[panel_id] = panel
        for panel_id, panel in merged.items():
            if self._constrain_panel_to_anchor_notch(panel):
                self._write_panel_layout_state(active_scope, panel_id, panel)
        return merged

    def _write_panel_layout_state(
        self, layout: dict[str, Any], panel_id: str, panel: dict[str, Any]
    ) -> None:
        panel_state = layout.setdefault("panels", {}).setdefault(panel_id, {})
        panel_state.update(
            {
                "gridX": int(panel["gridX"]),
                "gridY": int(panel["gridY"]),
                "colSpan": int(panel["colSpan"]),
                "rowSpan": int(panel["rowSpan"]),
            }
        )

    def _panel_rect(self, panel: dict[str, Any]) -> tuple[int, int, int, int]:
        left = int(panel.get("gridX", 0))
        top = int(panel.get("gridY", 0))
        width = max(1, int(panel.get("colSpan", 1)))
        height = max(1, int(panel.get("rowSpan", 1)))
        return left, top, left + width, top + height

    def _ranges_overlap(
        self, start_a: int, end_a: int, start_b: int, end_b: int
    ) -> bool:
        return max(start_a, start_b) < min(end_a, end_b)

    def _panel_relation(
        self, target: dict[str, Any], other: dict[str, Any]
    ) -> str | None:
        target_left, target_top, target_right, target_bottom = self._panel_rect(target)
        other_left, other_top, other_right, other_bottom = self._panel_rect(other)
        vertical_link = (
            self._ranges_overlap(target_top, target_bottom, other_top, other_bottom)
            or other_bottom == target_top
            or other_top == target_bottom
        )
        horizontal_link = (
            self._ranges_overlap(target_left, target_right, other_left, other_right)
            or other_right == target_left
            or other_left == target_right
        )
        if other_left >= target_right and vertical_link:
            return "right"
        if other_right <= target_left and vertical_link:
            return "left"
        if other_top >= target_bottom and horizontal_link:
            return "bottom"
        if other_bottom <= target_top and horizontal_link:
            return "top"
        return None

    def _reflow_adjacent_docked_panels(
        self,
        layout: dict[str, Any],
        target_panel_id: str,
        previous_panels: dict[str, dict[str, Any]],
    ) -> None:
        current_panels = self._merged_deck_panel_map(layout)
        target = current_panels.get(target_panel_id)
        previous_target = previous_panels.get(target_panel_id)
        if target is None or previous_target is None:
            return
        target_left, target_top, target_right, target_bottom = self._panel_rect(target)

        for panel_id, panel in current_panels.items():
            if panel_id == target_panel_id or bool(panel.get("hidden", False)):
                continue
            previous_panel = previous_panels.get(panel_id)
            if previous_panel is None or bool(previous_panel.get("hidden", False)):
                continue

            relation = self._panel_relation(previous_target, previous_panel)
            if relation is None:
                continue

            left, top, right, bottom = self._panel_rect(panel)
            min_cols = max(2, int(panel.get("minCols", 2)))
            min_rows = max(2, int(panel.get("minRows", 2)))
            changed = False

            if relation == "right" and left < target_right:
                new_left = min(
                    max(target_right, 0), max(0, DECK_GRID_COLUMNS - min_cols)
                )
                new_right = max(new_left + min_cols, right)
                panel["gridX"] = new_left
                panel["colSpan"] = max(
                    min_cols, min(DECK_GRID_COLUMNS - new_left, new_right - new_left)
                )
                changed = True
            elif relation == "left" and right > target_left:
                new_right = max(min_cols, min(target_left, DECK_GRID_COLUMNS))
                panel["colSpan"] = max(min_cols, new_right - left)
                panel["gridX"] = max(0, new_right - panel["colSpan"])
                changed = True
            elif relation == "bottom" and top < target_bottom:
                new_top = min(max(target_bottom, 0), max(0, DECK_GRID_ROWS - min_rows))
                new_bottom = max(new_top + min_rows, bottom)
                panel["gridY"] = new_top
                panel["rowSpan"] = max(
                    min_rows, min(DECK_GRID_ROWS - new_top, new_bottom - new_top)
                )
                changed = True
            elif relation == "top" and bottom > target_top:
                new_bottom = max(min_rows, min(target_top, DECK_GRID_ROWS))
                panel["rowSpan"] = max(min_rows, new_bottom - top)
                panel["gridY"] = max(0, new_bottom - panel["rowSpan"])
                changed = True

            if changed:
                self._write_panel_layout_state(layout, panel_id, panel)

        for panel_id, panel in current_panels.items():
            if self._constrain_panel_to_anchor_notch(panel):
                self._write_panel_layout_state(layout, panel_id, panel)

    def _constrain_panel_to_anchor_notch(self, panel: dict[str, Any]) -> bool:
        if bool(panel.get("hidden", False)) or not self._panel_overlaps_anchor_notch(
            panel
        ):
            return False

        notch_left, notch_top, notch_right, notch_bottom = DECK_ANCHOR_NOTCH
        col_span = max(2, int(panel.get("colSpan", 2)))
        row_span = max(2, int(panel.get("rowSpan", 2)))
        edge = str(panel.get("edge", "center"))
        changed = False

        if edge == "left":
            new_x = max(0, min(int(panel.get("gridX", 0)), notch_left - col_span))
            changed = new_x != int(panel.get("gridX", 0))
            panel["gridX"] = new_x
        elif edge == "right":
            new_x = min(
                max(notch_right, int(panel.get("gridX", 0))),
                max(0, DECK_GRID_COLUMNS - col_span),
            )
            changed = new_x != int(panel.get("gridX", 0))
            panel["gridX"] = new_x
        else:
            new_y = min(
                max(notch_bottom, int(panel.get("gridY", 0))),
                max(0, DECK_GRID_ROWS - row_span),
            )
            changed = new_y != int(panel.get("gridY", 0))
            panel["gridY"] = new_y

        return changed

    def _panel_overlaps_anchor_notch(self, panel: dict[str, Any]) -> bool:
        left, top, right, bottom = self._panel_rect(panel)
        notch_left, notch_top, notch_right, notch_bottom = DECK_ANCHOR_NOTCH
        return self._ranges_overlap(
            left, right, notch_left, notch_right
        ) and self._ranges_overlap(top, bottom, notch_top, notch_bottom)

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
        return labels.get(
            self._active_module_key, self._active_module_key.replace("-", " ").title()
        )

    def _default_workspace_section_key(self, module_key: str) -> str:
        defaults = {
            "chartroom": "overview",
            "helm": "overview",
            "logbook": "notes",
            "watch": "active-jobs",
            "signals": "live",
            "systems": "overview",
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
        return module_summaries.get(
            section_key, "A restrained supporting surface within the living field."
        )

    def _workspace_canvas_eyebrow(self) -> str:
        return next(
            (
                section["eyebrow"]
                for section in self._workspace_sections
                if section["key"] == self._active_workspace_section_key
            ),
            self._active_module_label(),
        )

    def _workspace_canvas_title(self) -> str:
        active_item = self._get_active_opened_item()
        workspace_named_section = self._active_workspace_section_key in {
            "opened-items",
            "open-pages",
            "references",
            "working-set",
        }
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
        workspace_named_section = self._active_workspace_section_key in {
            "opened-items",
            "open-pages",
            "references",
            "working-set",
        }
        if workspace_named_section and self._workspace_focus.get("summary"):
            return str(self._workspace_focus.get("summary"))
        if active_item and workspace_named_section:
            subtitle = str(active_item.get("subtitle", "")).strip()
            if subtitle:
                return subtitle
        if self._active_module_key == "helm":
            if self._active_workspace_section_key == "safety":
                shell_label = self._shell_command_label().lower()
                return f"Read access stays allowlisted to {self._read_scope_label().lower()}, and shell actions remain {shell_label}."
            background_state = (
                str(self._ghost_adaptive_diagnostics.get("backgroundState", "unknown"))
                .replace("-", " ")
                .strip()
            )
            placement_state = (
                str(self._ghost_placement.get("state", "holding"))
                .replace("_", " ")
                .strip()
            )
            anchor_key = (
                str(self._ghost_placement.get("anchorKey", "center"))
                .replace("-", " ")
                .strip()
            )
            return f"Ghost contrast is {background_state or 'unknown'} and the anchor is {placement_state or 'holding'} toward {anchor_key or 'center'}."
        if (
            self._active_workspace_section_key == "overview"
            and self._workspace_focus.get("summary")
        ):
            return str(self._workspace_focus.get("summary"))
        return self._workspace_section_summary(
            self._active_module_key, self._active_workspace_section_key
        )

    def _workspace_canvas_body(self) -> str:
        active_item = self._get_active_opened_item()
        workspace_named_section = self._active_workspace_section_key in {
            "opened-items",
            "open-pages",
            "references",
            "working-set",
        }
        if workspace_named_section and self._workspace_focus.get("name"):
            active_title = (
                str(active_item.get("title", "active bearings")).strip()
                if active_item
                else "active bearings"
            )
            return f"Holding {active_title} inside the {self._workspace_focus.get('name')} workspace."
        if active_item and workspace_named_section:
            kind = str(active_item.get("kind", "item")).replace("-", " ")
            return f"Holding a {kind} surface inside the current Stormhelm workspace."
        if self._active_module_key == "helm":
            if self._active_workspace_section_key == "safety":
                return f"{self._read_scope_detail()} {self._shell_command_detail()}"
            placement_state = (
                str(self._ghost_placement.get("state", "holding"))
                .replace("_", " ")
                .strip()
            )
            return (
                "Helm is Stormhelm's integrated settings direction: behavior, presence, shortcuts, "
                "and operator-facing control live here. The tray stays quick and light; advanced "
                "control remains backed by config files. Ghost contrast is "
                f"{str(self._ghost_adaptive_diagnostics.get('backgroundState', 'unknown')).replace('-', ' ')} and the anchor is "
                f"{placement_state or 'holding'}."
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
            return (
                "Files keeps the working set, deck-held documents, and native apps hand-off choices aligned "
                "for the current mission."
            )
        if self._active_module_key == "browser":
            return (
                "Browser keeps research pages, references, and supporting sources close to the current workspace "
                "while leaving native browser hand-off available when that is the better surface."
            )
        return "Visual Context remains a reserved tactical surface until screen-aware behavior arrives later."

    def _workspace_canvas_chips(self) -> list[dict[str, str]]:
        active_item = self._get_active_opened_item()
        workspace_named_section = self._active_workspace_section_key in {
            "opened-items",
            "open-pages",
            "references",
            "working-set",
        }
        if active_item and workspace_named_section:
            chips = [
                {
                    "label": "Viewer",
                    "value": str(
                        active_item.get("viewer", active_item.get("kind", "item"))
                    ).title(),
                },
                {"label": "Opened Items", "value": str(len(self._opened_items))},
            ]
            if self._workspace_focus.get("topic"):
                chips.insert(
                    0,
                    {
                        "label": "Workspace",
                        "value": str(self._workspace_focus.get("topic")).title(),
                    },
                )
            if active_item.get("path"):
                chips.append({"label": "Path", "value": str(active_item.get("path"))})
            elif active_item.get("url"):
                chips.append({"label": "Source", "value": str(active_item.get("url"))})
            return chips
        if self._active_module_key == "helm":
            if self._active_workspace_section_key == "safety":
                return [
                    {"label": "Read Scope", "value": self._read_scope_label()},
                    {"label": "Shell Command", "value": self._shell_command_label()},
                    {"label": "Config Fallback", "value": "portable.toml / user.toml"},
                    {
                        "label": "Ghost Contrast",
                        "value": str(
                            self._ghost_adaptive_diagnostics.get(
                                "backgroundState", "unknown"
                            )
                        )
                        .replace("-", " ")
                        .title(),
                    },
                ]
            return [
                {"label": "Ghost Shortcut", "value": self.config.ui.ghost_shortcut},
                {
                    "label": "Tray Close",
                    "value": "Dormant fade"
                    if self._hide_to_tray_on_close
                    else "Window close",
                },
                {"label": "Config Fallback", "value": "portable.toml / user.toml"},
                {
                    "label": "Ghost Contrast",
                    "value": str(
                        self._ghost_adaptive_diagnostics.get(
                            "backgroundState", "unknown"
                        )
                    )
                    .replace("-", " ")
                    .title(),
                },
                {
                    "label": "Ghost Anchor",
                    "value": str(self._ghost_placement.get("anchorKey", "center"))
                    .replace("-", " ")
                    .title(),
                },
            ]
        if self._active_module_key == "systems":
            chips = [
                {"label": "Runtime", "value": self._runtime_mode_label.title()},
                {"label": "Install", "value": self._install_mode_label.title()},
                {"label": "Signal", "value": self.connectionLabel},
                {
                    "label": "Workers",
                    "value": str(
                        self._status.get(
                            "max_workers", self.config.concurrency.max_workers
                        )
                    ),
                },
            ]
            focus_label = self._workspace_state_hint_label(self._workspace_state_hint)
            if focus_label:
                chips.insert(0, {"label": "Focus", "value": focus_label})
            return chips
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
                {
                    "label": "Timeout",
                    "value": f"{self.config.concurrency.default_job_timeout_seconds:g}s",
                },
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

    def _workspace_canvas_view_kind(self) -> str:
        section = self._active_workspace_section_key
        module = self._active_module_key
        if (
            section in {"opened-items", "open-pages", "working-set"}
            and self._opened_items
        ):
            return "workspace-items"
        if section == "session":
            return "session"
        if section == "tasks":
            return "tasks"
        if section == "findings":
            return "findings"
        if module == "systems":
            return "facts"
        if module == "watch":
            if section == "timeline":
                return "signals"
            if section == "tools":
                return "collection"
            return "watch"
        if module == "signals":
            return "signals"
        if module == "logbook":
            return "notes"
        if module in {"files", "browser"}:
            return "collection"
        if module == "chartroom" and section == "active-thread":
            return "thread"
        if module == "chartroom" and section == "references":
            return "collection"
        return "overview"

    def _workspace_canvas_stats(self) -> list[dict[str, str]]:
        if self._active_module_key == "systems":
            provider = self._provider_state()
            power = self._power_state()
            watch = self._watch_state()
            return [
                {
                    "label": "Provider",
                    "value": "Online" if provider.get("configured") else "Offline",
                },
                {"label": "Battery", "value": self._battery_label(power)},
                {
                    "label": "Workers",
                    "value": str(
                        watch.get(
                            "worker_capacity", self.config.concurrency.max_workers
                        )
                    ),
                },
            ]
        if self._active_module_key == "watch":
            if self._active_workspace_section_key == "tools":
                catalog = self._tool_inventory_catalog()
                enabled = sum(1 for tool in catalog if tool["enabled"])
                categories = {tool["category"] for tool in catalog if tool["category"]}
                async_count = sum(
                    1 for tool in catalog if tool["execution_mode"] == "async"
                )
                return [
                    {"label": "Enabled", "value": str(enabled)},
                    {"label": "Categories", "value": str(len(categories))},
                    {"label": "Async", "value": str(async_count)},
                ]
            watch = self._watch_state()
            return [
                {"label": "Active Jobs", "value": str(watch.get("active_jobs", 0))},
                {"label": "Queued", "value": str(watch.get("queued_jobs", 0))},
                {"label": "Failures", "value": str(watch.get("recent_failures", 0))},
            ]
        if self._active_module_key == "files":
            return [
                {"label": "Opened", "value": str(len(self._opened_items))},
                {
                    "label": "Active",
                    "value": self._get_active_opened_item().get("title", "None"),
                },
                {"label": "Deck Surface", "value": "Internal"},
            ]
        if self._active_module_key == "logbook":
            return [
                {"label": "Entries", "value": str(len(self._notes))},
                {
                    "label": "Workspace",
                    "value": str(self._workspace_focus.get("name", "Local memory")),
                },
                {"label": "Carryover", "value": "Retained"},
            ]
        if self._active_module_key == "signals":
            signal_state = self._signal_state()
            signals = (
                signal_state.get("signals", [])
                if isinstance(signal_state.get("signals"), list)
                else []
            )
            alerts = sum(
                1
                for signal in signals
                if isinstance(signal, dict)
                and str(signal.get("severity", "")).lower() in {"warning", "attention"}
            )
            if alerts <= 0:
                alerts = sum(
                    1
                    for event in self._events
                    if str(event.get("level", "")).upper() in {"WARNING", "ERROR"}
                )
            return [
                {"label": "Signal", "value": self.connectionLabel},
                {
                    "label": "Events",
                    "value": str(len(signals) if signals else len(self._events)),
                },
                {"label": "Alerts", "value": str(alerts)},
            ]
        if self._active_workspace_section_key == "session":
            return [
                {"label": "Mode", "value": self.modeTitle},
                {"label": "Module", "value": self._active_module_label()},
                {"label": "Signal", "value": self.connectionLabel},
            ]
        if self._active_workspace_section_key == "tasks":
            task_groups = self._workspace_canvas_task_groups()
            total = sum(len(group.get("entries", [])) for group in task_groups)
            return [
                {"label": "Pending", "value": str(total)},
                {
                    "label": "In Flight",
                    "value": str(self._watch_state().get("active_jobs", 0)),
                },
                {
                    "label": "Queued",
                    "value": str(self._watch_state().get("queued_jobs", 0)),
                },
            ]
        return []

    def _workspace_canvas_fact_groups(self) -> list[dict[str, Any]]:
        if self._active_module_key != "systems":
            return []
        interpretation = self._systems_interpretation_state()
        event_stream = self._event_stream_state()
        machine = self._machine_state()
        power = self._power_state()
        resources = self._resource_state()
        hardware = self._hardware_state()
        storage = self._storage_state()
        location = self._location_state()
        provider = self._provider_state()
        tool_state = self._tool_state()
        drives = (
            storage.get("drives", []) if isinstance(storage.get("drives"), list) else []
        )
        primary_drive = drives[0] if drives else {}
        gpu_items = (
            resources.get("gpu", []) if isinstance(resources.get("gpu"), list) else []
        )
        primary_gpu = gpu_items[0] if gpu_items else {}
        groups: list[dict[str, Any]] = []
        domains = (
            interpretation.get("domains", [])
            if isinstance(interpretation.get("domains"), list)
            else []
        )
        if domains:
            groups.append(
                {
                    "title": "Operational State",
                    "summary": str(
                        interpretation.get(
                            "summary",
                            "Interpreted system condition and recent machine strain.",
                        )
                    ),
                    "rows": [
                        {
                            "label": str(
                                domain.get("label", domain.get("key", "Signal"))
                            ),
                            "value": str(domain.get("headline", "")),
                            "detail": str(domain.get("summary", "")),
                        }
                        for domain in domains[:4]
                        if isinstance(domain, dict)
                    ],
                }
            )
        groups.extend(
            [
                {
                    "title": "Machine",
                    "summary": "Host, operating system, and local bearings.",
                    "rows": [
                        {
                            "label": "Host",
                            "value": str(machine.get("machine_name", "Unknown")),
                            "detail": str(machine.get("system", "")),
                        },
                        {
                            "label": "OS",
                            "value": f"{machine.get('system', '')} {machine.get('release', '')}".strip()
                            or "Unknown",
                            "detail": str(machine.get("platform", "")),
                        },
                        {
                            "label": "Local Time",
                            "value": self._short_time(
                                str(machine.get("local_time", ""))
                            )
                            or self._local_time_label,
                            "detail": str(machine.get("timezone", "Unknown timezone")),
                        },
                        {
                            "label": "Location",
                            "value": self._location_label(location),
                            "detail": self._location_detail(location),
                        },
                        {
                            "label": "Runtime",
                            "value": self._runtime_mode_label.title(),
                            "detail": self._environment_label.title(),
                        },
                    ],
                },
                {
                    "title": "Power and Resources",
                    "summary": "Current energy posture and machine load capacity.",
                    "rows": [
                        {
                            "label": "Battery",
                            "value": self._battery_label(power),
                            "detail": self._power_detail_text(power),
                        },
                        {
                            "label": "CPU",
                            "value": str(
                                (resources.get("cpu") or {}).get("name", "Unknown CPU")
                            ),
                            "detail": self._cpu_detail_text(resources),
                        },
                        {
                            "label": "Memory",
                            "value": self._memory_used_label(resources),
                            "detail": self._memory_detail(resources),
                        },
                        {
                            "label": "GPU",
                            "value": str(primary_gpu.get("name", "Unavailable")),
                            "detail": self._gpu_detail_text(resources),
                        },
                    ],
                },
                {
                    "title": "Storage and Tooling",
                    "summary": "Disk availability, provider posture, and local tool readiness.",
                    "rows": [
                        {
                            "label": "Primary Drive",
                            "value": str(primary_drive.get("drive", "Unavailable")),
                            "detail": self._drive_detail(primary_drive),
                        },
                        {
                            "label": "Telemetry",
                            "value": self._telemetry_status_label(hardware),
                            "detail": self._telemetry_detail_text(hardware),
                        },
                        {
                            "label": "Provider",
                            "value": "Configured"
                            if provider.get("configured")
                            else "Offline",
                            "detail": self._provider_detail(provider),
                        },
                        {
                            "label": "Tools",
                            "value": str(tool_state.get("enabled_count", 0)),
                            "detail": self._tools_detail(tool_state),
                        },
                    ],
                },
            ]
        )
        authority_group = self._bridge_authority_fact_group()
        if authority_group is not None:
            groups.append(authority_group)
        if event_stream:
            buffered = int(event_stream.get("buffered") or 0)
            capacity = int(event_stream.get("capacity") or 0)
            replay_requests = int(event_stream.get("replay_requests") or 0)
            replay_gaps = int(event_stream.get("replay_gap_total") or 0)
            connections = int(event_stream.get("connections_current") or 0)
            earliest_cursor = event_stream.get("earliest_cursor")
            latest_cursor = event_stream.get("latest_cursor")
            groups.append(
                {
                    "title": "Event Spine",
                    "summary": "Recent operational event retention, replay posture, and live stream health.",
                    "rows": [
                        {
                            "label": "Buffered",
                            "value": f"{buffered} / {capacity}"
                            if capacity
                            else str(buffered),
                            "detail": (
                                f"Cursors {earliest_cursor} to {latest_cursor}"
                                if earliest_cursor is not None
                                and latest_cursor is not None
                                else "Awaiting retained event history."
                            ),
                        },
                        {
                            "label": "Replay",
                            "value": f"{latest_cursor or 0} latest",
                            "detail": f"{replay_requests} replays, {replay_gaps} retention gaps",
                        },
                        {
                            "label": "Connections",
                            "value": f"{connections} live",
                            "detail": f"{int(event_stream.get('connections_total') or connections)} total stream openings",
                        },
                        {
                            "label": "Visibility",
                            "value": str(
                                len(event_stream.get("visibility_totals") or {})
                            ),
                            "detail": self._event_stream_visibility_detail(
                                event_stream
                            ),
                        },
                    ],
                }
            )
        return self._filter_system_fact_groups(groups)

    def _filter_system_fact_groups(
        self, groups: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        section = self._active_workspace_section_key
        if section == "overview":
            return groups
        title_map = {
            "runtime": {
                "Machine",
                "Storage and Tooling",
                "Lifecycle",
                "Bridge Authority",
            },
            "diagnostics": {
                "Operational State",
                "Power and Resources",
                "Bridge Authority",
            },
            "jobs": {"Storage and Tooling", "Event Spine", "Bridge Authority"},
            "logs": {"Event Spine", "Bridge Authority"},
            "network": {"Operational State"},
        }
        allowed = title_map.get(section)
        if not allowed:
            return groups
        filtered = [group for group in groups if str(group.get("title", "")) in allowed]
        return filtered or groups[:2]

    def _network_display_data(self) -> dict[str, Any]:
        if self._active_module_key != "systems":
            return {}
        if self._active_workspace_section_key not in {
            "overview",
            "network",
            "diagnostics",
        }:
            return {}
        network = self._network_state()
        if not isinstance(network, dict):
            return {}
        assessment = (
            network.get("assessment", {})
            if isinstance(network.get("assessment"), dict)
            else {}
        )
        quality = (
            network.get("quality", {})
            if isinstance(network.get("quality"), dict)
            else {}
        )
        monitoring = (
            network.get("monitoring", {})
            if isinstance(network.get("monitoring"), dict)
            else {}
        )
        providers = (
            network.get("providers", {})
            if isinstance(network.get("providers"), dict)
            else {}
        )
        throughput = (
            network.get("throughput", {})
            if isinstance(network.get("throughput"), dict)
            else {}
        )
        events = (
            network.get("events", []) if isinstance(network.get("events"), list) else []
        )
        interfaces = (
            network.get("interfaces", [])
            if isinstance(network.get("interfaces"), list)
            else []
        )
        primary = (
            interfaces[0] if interfaces and isinstance(interfaces[0], dict) else {}
        )
        trend_points = (
            network.get("trend_points", [])
            if isinstance(network.get("trend_points"), list)
            else []
        )

        status = str(assessment.get("headline") or "Monitoring").strip() or "Monitoring"
        summary = str(
            assessment.get("summary")
            or "Connected, but Stormhelm is still building quality history."
        ).strip()
        confidence = str(assessment.get("confidence") or "low").strip().title() or "Low"
        evidence = (
            str(assessment.get("evidence_sufficiency") or "gathering")
            .replace("_", " ")
            .strip()
            or "gathering"
        )
        attribution = (
            str(assessment.get("attribution") or "unclear").replace("_", " ").strip()
            or "unclear"
        )
        local_state = (
            providers.get("local_status", {})
            if isinstance(providers.get("local_status"), dict)
            else {}
        )
        upstream_state = (
            providers.get("upstream_path", {})
            if isinstance(providers.get("upstream_path"), dict)
            else {}
        )
        throughput_state = (
            providers.get("observed_throughput", {})
            if isinstance(providers.get("observed_throughput"), dict)
            else {}
        )
        provider_state = (
            providers.get("cloudflare_quality", {})
            if isinstance(providers.get("cloudflare_quality"), dict)
            else {}
        )
        provider_label = (
            str(provider_state.get("label") or "External quality").strip()
            or "External quality"
        )
        provider_mode = (
            str(provider_state.get("state") or "unavailable")
            .replace("_", " ")
            .strip()
            .title()
            or "Unavailable"
        )
        provider_detail = str(
            provider_state.get("comparison_summary")
            or provider_state.get("detail")
            or "External quality enrichment is not available."
        ).strip()
        provider_meta_parts: list[str] = []
        successful_samples = provider_state.get("successful_samples")
        sample_count = provider_state.get("sample_count")
        if successful_samples is not None and sample_count is not None:
            provider_meta_parts.append(f"{successful_samples}/{sample_count} samples")
        provider_age = self._timestamp_age_label(
            provider_state.get("sampled_at")
        ) or self._age_label(provider_state.get("last_sample_age_seconds"))
        if provider_age:
            provider_meta_parts.append(provider_age)
        if provider_state.get("comparison_ready"):
            provider_meta_parts.append("Compared with Stormhelm probes")
        elif provider_state:
            provider_meta_parts.append("Comparison not ready yet")

        return {
            "available": True,
            "hero": {
                "status": status,
                "summary": summary,
                "assessment": self._network_assessment_label(attribution),
                "confidence": f"{confidence} confidence",
                "evidence": "Building recent history"
                if not monitoring.get("history_ready")
                else f"{evidence.title()} evidence",
                "state": self._network_health_state(assessment.get("kind"), monitoring),
            },
            "metrics": [
                self._network_metric(
                    "Latency",
                    quality.get("latency_ms"),
                    "ms",
                    detail=self._network_latency_detail(quality),
                    severity=self._network_metric_severity(
                        "latency", quality.get("latency_ms")
                    ),
                ),
                self._network_metric(
                    "Jitter",
                    quality.get("jitter_ms"),
                    "ms",
                    detail=self._network_jitter_detail(quality),
                    severity=self._network_metric_severity(
                        "jitter", quality.get("jitter_ms")
                    ),
                ),
                self._network_metric(
                    "Loss",
                    quality.get("packet_loss_pct"),
                    "%",
                    detail=self._network_loss_detail(quality),
                    severity=self._network_metric_severity(
                        "loss", quality.get("packet_loss_pct")
                    ),
                ),
                self._network_metric(
                    "Signal",
                    quality.get("signal_strength_dbm")
                    if quality.get("signal_strength_dbm") is not None
                    else quality.get("signal_quality_pct"),
                    "dBm" if quality.get("signal_strength_dbm") is not None else "%",
                    detail="Signal strength unavailable on this adapter"
                    if quality.get("signal_strength_dbm") is None
                    and quality.get("signal_quality_pct") is None
                    else str(
                        primary.get("ssid") or primary.get("profile") or "Active link"
                    ),
                    severity=self._network_metric_severity(
                        "signal",
                        quality.get("signal_strength_dbm")
                        if quality.get("signal_strength_dbm") is not None
                        else quality.get("signal_quality_pct"),
                    ),
                ),
            ],
            "trend": {
                "state": "ready" if trend_points else "building",
                "summary": "Recent quality trend"
                if trend_points
                else "Building recent history",
                "points": trend_points[:18],
            },
            "events": [
                {
                    "title": str(event.get("title") or "Network event"),
                    "detail": str(event.get("detail") or ""),
                    "meta": self._age_label(event.get("seconds_ago")),
                    "severity": str(event.get("severity") or "steady"),
                }
                for event in events[:4]
                if isinstance(event, dict)
            ]
            or [
                {
                    "title": "No recent incident",
                    "detail": "Stormhelm has not seen a recent disconnect, burst loss, or roam event.",
                    "meta": "",
                    "severity": "steady",
                }
            ],
            "provider": {
                "value": provider_label,
                "state": provider_mode,
                "detail": provider_detail,
                "meta": " | ".join(part for part in provider_meta_parts if part),
            },
            "details": [
                {
                    "label": "SSID",
                    "value": str(
                        primary.get("ssid") or primary.get("profile") or "Unavailable"
                    ),
                },
                {"label": "BSSID", "value": str(primary.get("bssid") or "Unavailable")},
                {
                    "label": "Gateway",
                    "value": ", ".join(
                        str(item) for item in (primary.get("gateway") or [])[:2]
                    )
                    or "Unavailable",
                },
                {
                    "label": "DNS",
                    "value": ", ".join(
                        str(item) for item in (primary.get("dns_servers") or [])[:2]
                    )
                    or "Unavailable",
                },
                {
                    "label": "Local IP",
                    "value": ", ".join(
                        str(item) for item in (primary.get("ipv4") or [])[:2]
                    )
                    or "Unavailable",
                },
                {
                    "label": "Throughput",
                    "value": (
                        f"{float(throughput.get('download_mbps')):.2f} down / {float(throughput.get('upload_mbps')):.2f} up Mbps"
                        if isinstance(throughput.get("download_mbps"), (int, float))
                        and isinstance(throughput.get("upload_mbps"), (int, float))
                        else str(
                            throughput.get("detail")
                            or throughput_state.get("detail")
                            or "Unavailable"
                        )
                    ),
                },
                {
                    "label": "Local Source",
                    "value": str(local_state.get("detail") or "Unavailable"),
                },
                {
                    "label": "Upstream Source",
                    "value": str(upstream_state.get("detail") or "Unavailable"),
                },
                {"label": "Provider", "value": provider_label},
                {"label": "Provider State", "value": provider_mode},
                {"label": "Provider Compare", "value": provider_detail},
                {
                    "label": "History",
                    "value": f"{int(monitoring.get('sample_count') or 0)} retained samples",
                },
                {
                    "label": "Sampling",
                    "value": "Diagnostic burst active"
                    if monitoring.get("diagnostic_burst_active")
                    else "Background watch",
                },
                {
                    "label": "Last Update",
                    "value": self._age_label(monitoring.get("last_sample_age_seconds"))
                    or "Just now",
                },
            ],
        }

    def _workspace_canvas_watch_lanes(self) -> list[dict[str, Any]]:
        if self._active_module_key != "watch":
            return []
        section = self._active_workspace_section_key
        if section == "active-jobs":
            return [
                {
                    "title": "In Flight",
                    "summary": "Live operations currently moving across the worker deck.",
                    "entries": self._job_lane_entries({"running"}),
                },
                {
                    "title": "Recently Completed",
                    "summary": "Finished work that can still explain recent replies.",
                    "entries": self._job_lane_entries({"completed"}),
                },
                {
                    "title": "Attention",
                    "summary": "Failures, timeouts, cancellations, or stalled work that need review.",
                    "entries": self._job_lane_entries(
                        {"failed", "timed_out", "cancelled"}
                    ),
                },
            ]
        if section == "queue":
            return [
                {
                    "title": "Queued",
                    "summary": "Work waiting on a worker slot or execution gate.",
                    "entries": self._job_lane_entries({"queued"}),
                },
                {
                    "title": "Pending",
                    "summary": "Requests prepared but not yet running.",
                    "entries": self._job_lane_entries({"pending"}),
                },
                {
                    "title": "Blocked",
                    "summary": "Queued work that needs operator attention before dispatch.",
                    "entries": self._job_lane_entries(
                        {"blocked", "failed", "timed_out"}
                    ),
                },
            ]
        return [
            {
                "title": "In Flight",
                "summary": "Live operations currently moving across the worker deck.",
                "entries": self._job_lane_entries({"running"}),
            },
            {
                "title": "Queued",
                "summary": "Work waiting on a worker slot or execution gate.",
                "entries": self._job_lane_entries({"queued"}),
            },
            {
                "title": "Attention",
                "summary": "Failures, timeouts, cancellations, or stalled work that need review.",
                "entries": self._job_lane_entries({"failed", "timed_out", "cancelled"}),
            },
        ]

    def _workspace_canvas_timeline(self) -> list[dict[str, Any]]:
        if self._active_module_key == "signals":
            return self._signal_timeline_entries()
        if self._active_module_key == "logbook":
            return self._logbook_timeline_entries()
        if (
            self._active_module_key == "watch"
            and self._active_workspace_section_key == "timeline"
        ):
            return self._watch_timeline_entries()
        if (
            self._active_module_key == "chartroom"
            and self._active_workspace_section_key == "active-thread"
        ):
            return [
                {
                    "title": str(message.get("content", ""))[:140] or "No exchange yet",
                    "eyebrow": str(message.get("speaker", "Stormhelm")),
                    "meta": str(message.get("shortTime", "")),
                    "detail": str(message.get("content", "")),
                }
                for message in self._display_history()[-8:]
            ] or [
                {
                    "title": "No active thread yet",
                    "eyebrow": "Chartroom",
                    "meta": "",
                    "detail": "Signal the helm to begin the current exchange.",
                }
            ]
        return []

    def _workspace_canvas_items(self) -> list[dict[str, Any]]:
        if (
            self._active_module_key == "watch"
            and self._active_workspace_section_key == "tools"
        ):
            return self._tool_inventory_items()
        if self._active_module_key == "files":
            surface_items = self._workspace_surface_items("files")
            if surface_items:
                return surface_items
            return self._file_collection_items(
                include_recent=self._active_workspace_section_key == "recent"
            )
        if self._active_module_key == "browser":
            surface_items = self._workspace_surface_items("references")
            if surface_items:
                return surface_items
            return self._reference_items(include_all_browser=True)
        if self._active_module_key == "logbook":
            surface_items = self._workspace_surface_items("logbook")
            if surface_items:
                return surface_items
            return self._logbook_collection_items()
        if self._active_workspace_section_key == "references":
            surface_items = self._workspace_surface_items("references")
            if surface_items:
                return surface_items
            return self._reference_items()
        return []

    def _workspace_canvas_highlights(self) -> list[dict[str, Any]]:
        if self._active_workspace_section_key != "findings":
            return []
        surface_items = self._workspace_surface_items("findings")
        if surface_items:
            return surface_items
        highlights: list[dict[str, Any]] = []
        for note in self._notes[:3]:
            highlights.append(
                {
                    "title": str(note.get("title", "Logbook bearing")),
                    "summary": str(note.get("content", ""))[:140],
                    "source": "Logbook",
                }
            )
        for job in self._jobs[:4]:
            if str(job.get("status", "")).lower() != "completed":
                continue
            detail = ""
            result = job.get("result")
            if isinstance(result, dict):
                detail = str(result.get("summary", ""))
            highlights.append(
                {
                    "title": self._module_label(str(job.get("tool_name", "operation"))),
                    "summary": detail
                    or "Stormhelm completed a recent operation worth retaining.",
                    "source": "Watch",
                }
            )
        for message in reversed(self._display_history()[-4:]):
            if str(message.get("role", "")) != "assistant":
                continue
            highlights.append(
                {
                    "title": "Stormhelm Assessment",
                    "summary": str(message.get("content", ""))[:140],
                    "source": "Active Thread",
                }
            )
        return highlights[:6] or [
            {
                "title": "No findings held yet",
                "summary": "Findings will collect the strongest conclusions, recovered facts, and confirmed outcomes from the current work.",
                "source": "Chartroom",
            }
        ]

    def _workspace_canvas_panels(self) -> list[dict[str, Any]]:
        if self._active_workspace_section_key != "session":
            return []
        surface_items = self._workspace_surface_items("session")
        if surface_items:
            return surface_items
        active_item = self._get_active_opened_item()
        latest_event = self._events[-1] if self._events else {}
        display_history = self._display_history()
        latest_message = display_history[-1] if display_history else {}
        likely_next = str(self._workspace_focus.get("likelyNext", "")).strip()
        return [
            {
                "title": "Current Bearing",
                "summary": str(
                    self._workspace_focus.get("name", self._active_module_label())
                ),
                "detail": str(
                    self._workspace_focus.get(
                        "summary",
                        self._workspace_section_summary(
                            self._active_module_key, "session"
                        ),
                    )
                ),
                "entries": [
                    {
                        "label": "Topic",
                        "value": str(
                            self._workspace_focus.get(
                                "topic", self._active_module_label()
                            )
                        ),
                    },
                    {"label": "Module", "value": self._active_module_label()},
                ],
            },
            {
                "title": "Surface Posture",
                "summary": self.modeTitle,
                "detail": self._status_line,
                "entries": [
                    {
                        "label": "Section",
                        "value": self._workspace_section_label(
                            self._active_workspace_section_key
                        ),
                    },
                    {
                        "label": "Active Item",
                        "value": str(active_item.get("title", "None held")),
                    },
                    {
                        "label": "Likely Next",
                        "value": likely_next or "Hold current course",
                    },
                ],
            },
            {
                "title": "Recent Motion",
                "summary": str(latest_event.get("message", "Quiet sea")),
                "detail": str(
                    latest_message.get("content", "No recent conversational movement.")
                )[:160],
                "entries": [
                    {"label": "Assistant", "value": self._assistant_state.title()},
                    {"label": "Signal", "value": self.connectionLabel},
                ],
            },
        ]

    def _workspace_canvas_task_groups(self) -> list[dict[str, Any]]:
        if self._active_workspace_section_key != "tasks":
            return []
        active_task_groups = (
            self._active_task.get("commandDeck", {}).get("groups", [])
            if isinstance(self._active_task.get("commandDeck"), dict)
            else []
        )
        if isinstance(active_task_groups, list) and active_task_groups:
            return [
                dict(group) for group in active_task_groups if isinstance(group, dict)
            ]
        surface_items = self._workspace_surface_items("tasks")
        if surface_items:
            return surface_items
        next_bearings: list[dict[str, str]] = []
        likely_next = str(self._workspace_focus.get("likelyNext", "")).strip()
        pending_next_steps = self._workspace_focus.get("pendingNextSteps", [])
        if likely_next:
            next_bearings.append(
                {
                    "title": likely_next,
                    "status": "priority",
                    "detail": f"Likely next bearing for {self._workspace_focus.get('name', 'the current workspace')}.",
                }
            )
        if isinstance(pending_next_steps, list):
            for step in pending_next_steps:
                detail = str(step).strip()
                if not detail or detail == likely_next:
                    continue
                next_bearings.append(
                    {
                        "title": detail,
                        "status": "ready",
                        "detail": detail,
                    }
                )
        if self._workspace_focus.get("summary"):
            next_bearings.append(
                {
                    "title": f"Continue {self._workspace_focus.get('name', 'the current workspace')}",
                    "status": "priority",
                    "detail": str(self._workspace_focus.get("summary")),
                },
            )
        if not next_bearings:
            next_bearings = [
                {
                    "title": "Review the active working set",
                    "status": "ready",
                    "detail": "Inspect the opened items and confirm which bearings still belong in the deck.",
                }
            ]
        in_flight = [
            {
                "title": self._module_label(str(job.get("tool_name", "operation"))),
                "status": str(job.get("status", "queued")).lower(),
                "detail": self._job_summary(job),
            }
            for job in self._jobs
            if str(job.get("status", "")).lower() in {"running", "queued"}
        ]
        follow_on = [
            {
                "title": str(event.get("message", "Recent signal")),
                "status": "attention",
                "detail": str(event.get("source", "core")).title(),
            }
            for event in self._events
            if str(event.get("level", "")).upper() in {"WARNING", "ERROR"}
        ]
        return [
            {"title": "Next Bearings", "entries": next_bearings[:4]},
            {
                "title": "In Flight",
                "entries": in_flight[:4]
                or [
                    {
                        "title": "No active jobs",
                        "status": "steady",
                        "detail": "The watch is currently clear.",
                    }
                ],
            },
            {
                "title": "Attention",
                "entries": follow_on[:4]
                or [
                    {
                        "title": "No immediate friction",
                        "status": "steady",
                        "detail": "Stormhelm is not holding unresolved warnings right now.",
                    }
                ],
            },
        ]

    def _system_state(self) -> dict[str, Any]:
        state = self._status.get("system_state", {})
        return state if isinstance(state, dict) else {}

    def _machine_state(self) -> dict[str, Any]:
        machine = self._system_state().get("machine", {})
        return machine if isinstance(machine, dict) else {}

    def _power_state(self) -> dict[str, Any]:
        power = self._system_state().get("power", {})
        return power if isinstance(power, dict) else {}

    def _location_state(self) -> dict[str, Any]:
        location = self._system_state().get("location", {})
        return location if isinstance(location, dict) else {}

    def _resource_state(self) -> dict[str, Any]:
        resources = self._system_state().get("resources", {})
        return resources if isinstance(resources, dict) else {}

    def _hardware_state(self) -> dict[str, Any]:
        hardware = self._system_state().get("hardware", {})
        return hardware if isinstance(hardware, dict) else {}

    def _storage_state(self) -> dict[str, Any]:
        storage = self._system_state().get("storage", {})
        return storage if isinstance(storage, dict) else {}

    def _network_state(self) -> dict[str, Any]:
        network = self._system_state().get("network", {})
        return network if isinstance(network, dict) else {}

    def _provider_state(self) -> dict[str, Any]:
        provider = self._status.get("provider_state", {})
        return provider if isinstance(provider, dict) else {}

    def _tool_state(self) -> dict[str, Any]:
        tools = self._status.get("tool_state", {})
        return tools if isinstance(tools, dict) else {}

    def _tool_catalog(self) -> dict[str, dict[str, Any]]:
        catalog: dict[str, dict[str, Any]] = {}
        for tool in self._tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name", "")).strip()
            if not name:
                continue
            catalog[name] = dict(tool)
        return catalog

    def _enabled_tool_names(self) -> set[str]:
        enabled = self._tool_state().get("enabled_tools", [])
        if not isinstance(enabled, list):
            return set()
        return {str(name).strip() for name in enabled if str(name).strip()}

    def _tool_state_is_explicit(self) -> bool:
        tool_state = self._tool_state()
        return "enabled_tools" in tool_state or "enabled_count" in tool_state

    def _tool_enabled(self, tool_name: str) -> bool:
        enabled_names = self._enabled_tool_names()
        if enabled_names:
            return tool_name in enabled_names
        if self._tool_state_is_explicit():
            return False
        return True

    def _watch_state(self) -> dict[str, Any]:
        watch = self._status.get("watch_state", {})
        return watch if isinstance(watch, dict) else {}

    def _signal_state(self) -> dict[str, Any]:
        signal_state = self._status.get("signal_state", {})
        return signal_state if isinstance(signal_state, dict) else {}

    def _systems_interpretation_state(self) -> dict[str, Any]:
        interpretation = self._status.get("systems_interpretation", {})
        return interpretation if isinstance(interpretation, dict) else {}

    def _event_stream_state(self) -> dict[str, Any]:
        event_stream = self._status.get("event_stream", {})
        return event_stream if isinstance(event_stream, dict) else {}

    def _bridge_authority_state(self) -> dict[str, Any]:
        authority = self._status.get("bridge_authority", {})
        return authority if isinstance(authority, dict) else {}

    def _bridge_authority_ghost_cards(self) -> list[dict[str, Any]]:
        authority = self._bridge_authority_state()
        cards = authority.get("ghostCards", [])
        if not isinstance(cards, list):
            return []
        return [dict(card) for card in cards if isinstance(card, dict)]

    def _software_control_state(self) -> dict[str, Any]:
        state = self._status.get("software_control", {})
        return state if isinstance(state, dict) else {}

    def _software_recovery_state(self) -> dict[str, Any]:
        state = self._status.get("software_recovery", {})
        return state if isinstance(state, dict) else {}

    def _bridge_authority_families(self) -> list[dict[str, Any]]:
        families = self._bridge_authority_state().get("families", [])
        return (
            [family for family in families if isinstance(family, dict)]
            if isinstance(families, list)
            else []
        )

    def _bridge_authority_context_cards(self) -> list[dict[str, Any]]:
        cards = self._bridge_authority_state().get("ghostCards", [])
        if not isinstance(cards, list):
            return []
        normalized: list[dict[str, Any]] = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            title = str(card.get("title", "")).strip()
            body = str(card.get("body", "")).strip()
            if not title or not body:
                continue
            normalized.append(
                {
                    "title": title,
                    "subtitle": str(
                        card.get("subtitle") or card.get("resultState") or ""
                    )
                    .replace("_", " ")
                    .title(),
                    "body": body[:160],
                }
            )
        return normalized

    def _bridge_authority_fact_group(self) -> dict[str, Any] | None:
        authority = self._bridge_authority_state()
        summary = (
            authority.get("summary")
            if isinstance(authority.get("summary"), dict)
            else {}
        )
        if not summary:
            return None
        gaps = (
            authority.get("gapRegister", [])
            if isinstance(authority.get("gapRegister"), list)
            else []
        )
        gap_count = len([gap for gap in gaps if isinstance(gap, dict)])
        gap_detail = "No backend authority gaps are currently reported."
        for gap in gaps:
            if isinstance(gap, dict):
                gap_detail = str(gap.get("summary") or gap.get("detail") or gap_detail)
                break
        return {
            "title": "Bridge Authority",
            "summary": str(summary.get("bridgeReadiness", "unknown"))
            .replace("_", " ")
            .title(),
            "rows": [
                {
                    "label": "Mapped Families",
                    "value": str(summary.get("mappedFamilyCount", 0)),
                    "detail": "Backend-owned command, preview, and inspection families mapped to UI surfaces.",
                },
                {
                    "label": "Commandable",
                    "value": str(summary.get("commandableFamilyCount", 0)),
                    "detail": "Families with backend-backed command authority.",
                },
                {
                    "label": "Previewable",
                    "value": str(summary.get("previewableFamilyCount", 0)),
                    "detail": "Families that can show a backend preview before action.",
                },
                {
                    "label": "Gaps",
                    "value": str(gap_count),
                    "detail": gap_detail,
                },
            ],
        }

    def _bridge_authority_columns(self) -> list[dict[str, Any]]:
        families = self._bridge_authority_families()
        if not families:
            return []
        entries = [
            {
                "primary": str(
                    family.get("label") or family.get("familyId") or "Authority"
                ),
                "secondary": str(family.get("commandAuthority", "unknown"))
                .replace("_", " ")
                .title(),
                "detail": str(
                    family.get("summary") or family.get("degradedReason") or ""
                ),
            }
            for family in families[:8]
        ]
        return [
            self._workspace_column(
                "Authority Map",
                "Backend authority each UI bridge family is allowed to claim.",
                entries,
            )
        ]

    def _lifecycle_state(self) -> dict[str, Any]:
        state = self._status.get("lifecycle", {})
        return state if isinstance(state, dict) else {}

    def lifecycle_state_snapshot(self) -> dict[str, Any]:
        return dict(self._lifecycle_state())

    def lifecycle_restart_hold_summary(self) -> str:
        lifecycle = self._lifecycle_state()
        restart_policy = (
            lifecycle.get("restart_policy")
            if isinstance(lifecycle.get("restart_policy"), dict)
            else {}
        )
        runtime_state = (
            lifecycle.get("runtime")
            if isinstance(lifecycle.get("runtime"), dict)
            else {}
        )
        bootstrap = (
            lifecycle.get("bootstrap")
            if isinstance(lifecycle.get("bootstrap"), dict)
            else {}
        )
        if (
            restart_policy.get("hold_active")
            or str(runtime_state.get("core_status", "")).strip().lower() == "held"
        ):
            return str(
                restart_policy.get("hold_reason")
                or bootstrap.get("lifecycle_hold_reason")
                or "Stormhelm is holding core restart until the operator reviews recent failures."
            ).strip()
        return ""

    def _trust_state(self) -> dict[str, Any]:
        state = self._status.get("trust", {})
        return state if isinstance(state, dict) else {}

    def _battery_label(self, power: dict[str, Any]) -> str:
        if not power.get("available"):
            return "Unavailable"
        percent = power.get("battery_percent")
        if percent is None:
            return "Unknown"
        return f"{percent}%"

    def _cpu_detail(self, resources: dict[str, Any]) -> str:
        cpu = resources.get("cpu", {})
        if not isinstance(cpu, dict):
            return ""
        cores = int(cpu.get("cores") or 0)
        logical = int(cpu.get("logical_processors") or 0)
        parts = []
        if cores:
            parts.append(f"{cores} cores")
        if logical:
            parts.append(f"{logical} threads")
        return " - ".join(parts)

    def _memory_used_label(self, resources: dict[str, Any]) -> str:
        memory = resources.get("memory", {})
        if not isinstance(memory, dict):
            return "Unavailable"
        used = self._format_bytes(memory.get("used_bytes"))
        total = self._format_bytes(memory.get("total_bytes"))
        if used and total:
            return f"{used} / {total}"
        return total or used or "Unavailable"

    def _memory_detail(self, resources: dict[str, Any]) -> str:
        memory = resources.get("memory", {})
        if not isinstance(memory, dict):
            return ""
        free = self._format_bytes(memory.get("free_bytes"))
        return f"{free} free" if free else ""

    def _cpu_load_label(self, resources: dict[str, Any]) -> str:
        cpu = resources.get("cpu", {})
        if not isinstance(cpu, dict):
            return "Unavailable"
        utilization = cpu.get("utilization_percent")
        if isinstance(utilization, (int, float)):
            return f"{float(utilization):.0f}% load"
        return "Unavailable"

    def _gpu_load_label(self, resources: dict[str, Any]) -> str:
        adapters = resources.get("gpu", [])
        if (
            not isinstance(adapters, list)
            or not adapters
            or not isinstance(adapters[0], dict)
        ):
            return "Unavailable"
        utilization = adapters[0].get("utilization_percent")
        if isinstance(utilization, (int, float)):
            return f"{float(utilization):.0f}% load"
        return "Unavailable"

    def _drive_free_label(self, drive: dict[str, Any]) -> str:
        if not isinstance(drive, dict):
            return "Unavailable"
        free = self._format_bytes(drive.get("free_bytes"))
        return f"{free} free" if free else "Unavailable"

    def _drive_detail(self, drive: dict[str, Any]) -> str:
        if not isinstance(drive, dict):
            return ""
        free = self._format_bytes(drive.get("free_bytes"))
        total = self._format_bytes(drive.get("total_bytes"))
        if free and total:
            return f"{free} free of {total}"
        return total or free or ""

    def _network_detail(self, interface: dict[str, Any]) -> str:
        if not isinstance(interface, dict):
            return "No active interface"
        ipv4 = interface.get("ipv4", [])
        if isinstance(ipv4, list) and ipv4:
            return ", ".join(str(value) for value in ipv4[:2])
        return str(interface.get("profile", "No IP"))

    def _battery_detail(self, power: dict[str, Any]) -> str:
        if not power.get("available"):
            return "Battery telemetry unavailable"
        ac_state = str(power.get("ac_line_status", "unknown")).title()
        remaining = self._format_duration(power.get("seconds_remaining"))
        rate = (
            power.get("instant_power_draw_watts")
            or power.get("discharge_rate_watts")
            or power.get("charge_rate_watts")
        )
        rate_text = f"{float(rate):.1f} W" if isinstance(rate, (int, float)) else ""
        if remaining:
            return f"{ac_state} - {remaining} remaining" + (
                f" at {rate_text}" if rate_text else ""
            )
        if rate_text:
            return f"{ac_state} - {rate_text}"
        return ac_state

    def _power_detail_text(self, power: dict[str, Any]) -> str:
        if not power.get("available"):
            return "Battery telemetry unavailable"
        ac_state = (
            "Charging"
            if str(power.get("ac_line_status", "")).strip().lower() == "online"
            else str(power.get("ac_line_status", "unknown")).title()
        )
        remaining = self._format_duration(power.get("seconds_remaining"))
        rate = (
            power.get("rolling_power_draw_watts")
            or power.get("instant_power_draw_watts")
            or power.get("discharge_rate_watts")
            or power.get("charge_rate_watts")
        )
        health = power.get("health_percent")
        detail_parts: list[str] = []
        if isinstance(rate, (int, float)):
            detail_parts.append(
                f"{'avg draw' if power.get('rolling_power_draw_watts') else 'draw'} {float(rate):.1f} W"
            )
        if isinstance(health, (int, float)):
            detail_parts.append(f"health {float(health):.0f}%")
        if remaining:
            detail_parts.insert(0, f"{remaining} remaining")
        if detail_parts:
            return f"{ac_state} - " + " - ".join(detail_parts)
        return ac_state

    def _cpu_detail_text(self, resources: dict[str, Any]) -> str:
        cpu = resources.get("cpu", {})
        if not isinstance(cpu, dict):
            return ""
        thermal = resources.get("thermal", {})
        fans = (
            thermal.get("fans", [])
            if isinstance(thermal, dict) and isinstance(thermal.get("fans"), list)
            else []
        )
        cores = int(cpu.get("cores") or 0)
        logical = int(cpu.get("logical_processors") or 0)
        parts = []
        if cores:
            parts.append(f"{cores} cores")
        if logical:
            parts.append(f"{logical} threads")
        package_temperature = cpu.get("package_temperature_c")
        effective_clock = cpu.get("effective_clock_mhz")
        utilization = cpu.get("utilization_percent")
        if isinstance(package_temperature, (int, float)):
            parts.append(f"{float(package_temperature):.0f} C")
        if isinstance(effective_clock, (int, float)):
            parts.append(f"{float(effective_clock):.0f} MHz")
        if isinstance(utilization, (int, float)):
            parts.append(f"{float(utilization):.0f}% load")
        cpu_fan = next(
            (
                fan
                for fan in fans
                if isinstance(fan, dict) and "cpu" in str(fan.get("label", "")).lower()
            ),
            None,
        )
        if isinstance(cpu_fan, dict):
            if isinstance(cpu_fan.get("rpm"), (int, float)):
                parts.append(f"{float(cpu_fan['rpm']):.0f} RPM")
            elif isinstance(cpu_fan.get("duty_percent"), (int, float)):
                parts.append(f"{float(cpu_fan['duty_percent']):.0f}% fan")
        return " - ".join(parts)

    def _gpu_detail_text(self, resources: dict[str, Any]) -> str:
        adapters = resources.get("gpu", [])
        if not isinstance(adapters, list) or not adapters:
            return "No active GPU telemetry"
        primary = adapters[0] if isinstance(adapters[0], dict) else {}
        thermal = resources.get("thermal", {})
        fans = (
            thermal.get("fans", [])
            if isinstance(thermal, dict) and isinstance(thermal.get("fans"), list)
            else []
        )
        detail_parts: list[str] = []
        if primary.get("driver_version"):
            detail_parts.append(str(primary.get("driver_version")))
        if isinstance(primary.get("temperature_c"), (int, float)):
            detail_parts.append(f"{float(primary['temperature_c']):.0f} C")
        if isinstance(primary.get("utilization_percent"), (int, float)):
            detail_parts.append(f"{float(primary['utilization_percent']):.0f}% load")
        if isinstance(primary.get("power_w"), (int, float)):
            detail_parts.append(f"{float(primary['power_w']):.1f} W")
        if isinstance(primary.get("fan_rpm"), (int, float)):
            detail_parts.append(f"{float(primary['fan_rpm']):.0f} RPM")
        elif isinstance(primary.get("fan_percent"), (int, float)):
            detail_parts.append(f"{float(primary['fan_percent']):.0f}% fan")
        else:
            gpu_fan = next(
                (
                    fan
                    for fan in fans
                    if isinstance(fan, dict)
                    and "gpu" in str(fan.get("label", "")).lower()
                ),
                None,
            )
            if isinstance(gpu_fan, dict):
                if isinstance(gpu_fan.get("rpm"), (int, float)):
                    detail_parts.append(f"{float(gpu_fan['rpm']):.0f} RPM")
                elif isinstance(gpu_fan.get("duty_percent"), (int, float)):
                    detail_parts.append(f"{float(gpu_fan['duty_percent']):.0f}% fan")
        return " - ".join(detail_parts)

    def _telemetry_status_label(self, hardware: dict[str, Any]) -> str:
        capabilities = (
            hardware.get("capabilities", {})
            if isinstance(hardware.get("capabilities"), dict)
            else {}
        )
        if capabilities.get("helper_reachable"):
            return "Helper ready"
        if capabilities.get("helper_installed"):
            return "Fallback"
        return "Unavailable"

    def _telemetry_detail_text(self, hardware: dict[str, Any]) -> str:
        capabilities = (
            hardware.get("capabilities", {})
            if isinstance(hardware.get("capabilities"), dict)
            else {}
        )
        freshness = (
            hardware.get("freshness", {})
            if isinstance(hardware.get("freshness"), dict)
            else {}
        )
        detail_parts: list[str] = []
        if capabilities.get("helper_reachable"):
            enabled_domains = []
            if capabilities.get("cpu_deep_telemetry_available"):
                enabled_domains.append("CPU")
            if capabilities.get("gpu_deep_telemetry_available"):
                enabled_domains.append("GPU")
            if capabilities.get("thermal_sensor_availability"):
                enabled_domains.append("Thermals")
            if capabilities.get("power_current_available"):
                enabled_domains.append("Power")
            if capabilities.get(
                "gigabyte_control_center_available"
            ) or capabilities.get("amd_ryzen_master_available"):
                enabled_domains.append("Vendor")
            if enabled_domains:
                detail_parts.append(", ".join(enabled_domains))
        reason = freshness.get("reason")
        if reason and not capabilities.get("helper_reachable"):
            detail_parts.append(str(reason).replace("_", " "))
        age = self._age_label(freshness.get("sample_age_seconds"))
        if age:
            detail_parts.append(age)
        tier = str(freshness.get("sampling_tier", "")).strip()
        if tier:
            detail_parts.append(f"{tier} tier")
        return (
            " - ".join(detail_parts)
            if detail_parts
            else "No helper telemetry available"
        )

    def _network_detail_text(self, interface: dict[str, Any]) -> str:
        if not isinstance(interface, dict):
            return "No active interface"
        status = str(interface.get("status", "")).strip().lower()
        profile = str(interface.get("profile", "")).strip()
        ipv4 = interface.get("ipv4", [])
        address = (
            ", ".join(str(value) for value in ipv4[:2])
            if isinstance(ipv4, list) and ipv4
            else ""
        )
        if status == "up":
            if profile and address:
                return f"Connected on {profile} Wi-Fi - {address}"
            if address:
                return f"Connected - {address}"
            return "Connected"
        if profile:
            return f"{profile} profile"
        return "No active IP bearing"

    def _network_assessment_label(self, attribution: str) -> str:
        normalized = str(attribution or "").strip().lower()
        if normalized == "local link":
            return "Local link issue likely"
        if normalized == "upstream":
            return "Upstream issue likely"
        if normalized == "dns":
            return "DNS issue suspected"
        if normalized in {"none", "stable"}:
            return "No strong attribution"
        return "Gathering attribution"

    def _network_health_state(self, kind: object, monitoring: dict[str, Any]) -> str:
        normalized = str(kind or "").strip().lower()
        if normalized in {"stable"}:
            return "healthy"
        if normalized in {"insufficient_evidence"} and not monitoring.get(
            "history_ready"
        ):
            return "monitoring"
        if normalized in {
            "local_link_issue",
            "upstream_issue",
            "dns_issue",
            "weak_signal_possible",
        }:
            return "warning"
        if normalized in {"roam_or_ap_handoff"}:
            return "attention"
        return "monitoring"

    def _network_metric(
        self, label: str, value: object, unit: str, *, detail: str, severity: str
    ) -> dict[str, str]:
        return {
            "label": label,
            "value": self._network_metric_value(value, unit),
            "detail": detail,
            "severity": severity,
        }

    def _network_metric_value(self, value: object, unit: str) -> str:
        if value is None or value == "":
            return "—"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if unit == "%":
            return f"{number:.1f}{unit}"
        if unit == "dBm":
            return f"{int(round(number))} {unit}"
        return f"{int(round(number))} {unit}"

    def _network_latency_detail(self, quality: dict[str, Any]) -> str:
        gateway = quality.get("gateway_latency_ms")
        external = quality.get("external_latency_ms")
        if gateway is not None and external is not None:
            return f"Gateway {self._network_metric_value(gateway, 'ms')} · External {self._network_metric_value(external, 'ms')}"
        if gateway is not None:
            return f"Gateway {self._network_metric_value(gateway, 'ms')}"
        if external is not None:
            return f"External {self._network_metric_value(external, 'ms')}"
        return "Waiting for latency samples"

    def _network_jitter_detail(self, quality: dict[str, Any]) -> str:
        gateway = quality.get("gateway_jitter_ms")
        external = quality.get("external_jitter_ms")
        if gateway is not None and external is not None:
            return f"Gateway {self._network_metric_value(gateway, 'ms')} · External {self._network_metric_value(external, 'ms')}"
        if gateway is not None:
            return f"Gateway {self._network_metric_value(gateway, 'ms')}"
        if external is not None:
            return f"External {self._network_metric_value(external, 'ms')}"
        return "Waiting for jitter samples"

    def _network_loss_detail(self, quality: dict[str, Any]) -> str:
        gateway = quality.get("gateway_packet_loss_pct")
        external = quality.get("external_packet_loss_pct")
        if gateway is not None and external is not None:
            return f"Gateway {self._network_metric_value(gateway, '%')} · External {self._network_metric_value(external, '%')}"
        if gateway is not None:
            return f"Gateway {self._network_metric_value(gateway, '%')}"
        if external is not None:
            return f"External {self._network_metric_value(external, '%')}"
        return "No loss history yet"

    def _network_metric_severity(self, metric: str, value: object) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "muted"
        normalized = metric.strip().lower()
        if normalized == "latency":
            return (
                "warning"
                if number >= 120
                else "attention"
                if number >= 60
                else "steady"
            )
        if normalized == "jitter":
            return (
                "warning" if number >= 20 else "attention" if number >= 10 else "steady"
            )
        if normalized == "loss":
            return (
                "warning" if number >= 2.0 else "attention" if number > 0 else "steady"
            )
        if normalized == "signal":
            if number <= -70:
                return "warning"
            if number <= -62:
                return "attention"
            if number <= 45:
                return "warning"
            if number <= 60:
                return "attention"
        return "steady"

    def _age_label(self, seconds: object) -> str:
        try:
            value = int(seconds)
        except (TypeError, ValueError):
            return ""
        if value < 60:
            return f"{value}s ago"
        minutes = value // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        return f"{hours}h ago"

    def _timestamp_age_label(self, value: object) -> str:
        try:
            if value is None or value == "":
                return ""
            timestamp = float(value)
        except (TypeError, ValueError):
            return ""
        delta = max(int(time.time() - timestamp), 0)
        return self._age_label(delta)

    def _location_label(self, location: dict[str, Any]) -> str:
        if not isinstance(location, dict) or not location.get("resolved"):
            return "Unavailable"
        return str(location.get("label") or location.get("name") or "Unknown area")

    def _location_detail(self, location: dict[str, Any]) -> str:
        if not isinstance(location, dict) or not location.get("resolved"):
            return "No current location fix"
        source = str(location.get("source", "")).strip().lower()
        if source == "device_live":
            return "Live device fix"
        if source == "approximate_device":
            return "Approximate device fix"
        if source == "saved_home":
            return "Saved home location"
        if source == "saved_named":
            return "Saved named location"
        if source == "queried_place":
            return "Requested place bearings"
        if source == "ip_estimate":
            return "IP-based estimate"
        return source.replace("_", " ").title() or "Location bearing"

    def _provider_detail(self, provider: dict[str, Any]) -> str:
        if not isinstance(provider, dict) or not provider.get("configured"):
            return "No provider configured"
        planner = str(provider.get("planner_model", "")).strip()
        reasoner = str(provider.get("reasoning_model", "")).strip()
        if planner and reasoner:
            return f"Planner {planner} - Reasoner {reasoner}"
        return planner or reasoner or "Provider ready"

    def _tool_display_name(self, tool: dict[str, Any]) -> str:
        name = str(tool.get("name", "")).strip()
        display_name = str(tool.get("display_name", "")).strip()
        if display_name:
            return display_name
        return self._module_label(name) if name else "Tool"

    def _tool_classification_label(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "read_only":
            return "Read Only"
        if normalized == "action":
            return "Action"
        if normalized == "development":
            return "Development"
        return "General"

    def _tool_category_label(self, value: str) -> str:
        normalized = str(value or "").replace("_", " ").strip()
        return normalized.title() if normalized else "General"

    def _tool_inventory_detail(self, tool: dict[str, Any]) -> str:
        execution_mode = (
            str(tool.get("execution_mode", "sync")).strip().lower() or "sync"
        )
        recent_jobs = [
            job
            for job in self._jobs
            if str(job.get("tool_name", "")).strip()
            == str(tool.get("name", "")).strip()
        ]
        parts = [f"{execution_mode.title()} execution"]
        timeout = tool.get("timeout_seconds")
        if isinstance(timeout, (int, float)) and timeout > 0:
            parts.append(f"timeout {float(timeout):g}s")
        if recent_jobs:
            last_job = recent_jobs[0]
            last_status = (
                str(last_job.get("status", "unknown")).replace("_", " ").strip().lower()
                or "unknown"
            )
            last_time = self._short_time(
                str(
                    last_job.get("finished_at")
                    or last_job.get("started_at")
                    or last_job.get("created_at", "")
                )
            )
            activity = (
                f"{len(recent_jobs)} recent job{'s' if len(recent_jobs) != 1 else ''}"
            )
            if last_time:
                parts.append(f"{activity}; last {last_status} at {last_time}")
            else:
                parts.append(f"{activity}; last {last_status}")
        else:
            parts.append("No recent jobs")
        if not bool(tool.get("enabled", False)):
            parts.append("Disabled in this runtime")
        return ". ".join(parts) + "."

    def _safety_settings(self) -> dict[str, Any]:
        safety = self._settings.get("safety", {})
        return dict(safety) if isinstance(safety, dict) else {}

    def _allowed_read_dirs(self) -> list[str]:
        safety = self._safety_settings()
        configured = safety.get("allowed_read_dirs")
        if isinstance(configured, list):
            paths = [str(path).strip() for path in configured if str(path).strip()]
            if paths:
                return paths
        return [
            str(path)
            for path in self.config.safety.allowed_read_dirs
            if str(path).strip()
        ]

    def _unsafe_test_mode_enabled(self) -> bool:
        safety = self._safety_settings()
        if "unsafe_test_mode" in safety:
            return bool(safety.get("unsafe_test_mode"))
        return bool(getattr(self.config.safety, "unsafe_test_mode", False))

    def _read_scope_label(self) -> str:
        if self._unsafe_test_mode_enabled():
            return "Unrestricted (unsafe test mode)"
        allowed = self._allowed_read_dirs()
        count = len(allowed)
        if count <= 0:
            return "No allowlisted roots"
        return f"{count} allowlisted root{'s' if count != 1 else ''}"

    def _read_scope_detail(self) -> str:
        if self._unsafe_test_mode_enabled():
            return "Unsafe test mode allows reads across the local filesystem for unrestricted testing."
        allowed = self._allowed_read_dirs()
        if not allowed:
            return "Stormhelm does not currently hold any configured read roots."
        shown = ", ".join(allowed[:3])
        if len(allowed) > 3:
            shown = f"{shown}, +{len(allowed) - 3} more"
        return f"Stormhelm can read inside {shown}."

    def _shell_command_label(self) -> str:
        if self._unsafe_test_mode_enabled():
            return "Live execution"
        safety = self._safety_settings()
        if "allow_shell_stub" in safety:
            enabled = bool(safety.get("allow_shell_stub"))
        else:
            enabled = bool(self.config.safety.allow_shell_stub)
        return "Stub only" if enabled else "Disabled"

    def _shell_command_detail(self) -> str:
        if self._unsafe_test_mode_enabled():
            return "Unsafe test mode runs shell commands directly on the local machine."
        if self._shell_command_label() == "Stub only":
            return "Shell requests stay behind the stub gate and do not enable unrestricted execution."
        return "Shell execution stays unavailable unless the safety policy explicitly enables the stub."

    def _screen_awareness_state(self) -> dict[str, Any]:
        state = self._status.get("screen_awareness", {})
        return dict(state) if isinstance(state, dict) else {}

    def _screen_awareness_settings(self) -> dict[str, Any]:
        settings = self._settings.get("screen_awareness", {})
        return dict(settings) if isinstance(settings, dict) else {}

    def _screen_awareness_phase_label(self) -> str:
        state = self._screen_awareness_state()
        settings = self._screen_awareness_settings()
        enabled = bool(
            state.get(
                "enabled", settings.get("enabled", self.config.screen_awareness.enabled)
            )
        )
        phase = (
            str(
                state.get("phase")
                or settings.get("phase")
                or self.config.screen_awareness.phase
            ).strip()
            or "phase?"
        )
        if not enabled:
            return "Disabled"
        if phase.startswith("phase"):
            return f"Phase {phase.replace('phase', '').strip()} active"
        return phase

    def _screen_awareness_policy_mode_label(self) -> str:
        state = self._screen_awareness_state()
        policy_state = state.get("policy_state")
        if isinstance(policy_state, dict):
            raw = str(policy_state.get("action_policy_mode", "")).strip()
            if raw:
                return raw.replace("_", " ").title()
        raw = str(
            self.config.screen_awareness.action_policy_mode or "observe_only"
        ).strip()
        return raw.replace("_", " ").title()

    def _screen_awareness_policy_detail(self) -> str:
        state = self._screen_awareness_state()
        policy_state = state.get("policy_state")
        if isinstance(policy_state, dict):
            summary = str(policy_state.get("summary", "")).strip()
            if summary:
                return summary
        return "Screen-awareness policy follows the backend posture rather than a decorative local toggle."

    def _screen_awareness_trace_label(self) -> str:
        state = self._screen_awareness_state()
        hardening = state.get("hardening")
        if isinstance(hardening, dict) and bool(hardening.get("enabled")):
            count = int(hardening.get("recent_trace_count", 0) or 0)
            return (
                f"{count} recent trace{'s' if count != 1 else ''}"
                if count
                else "Phase 12 ready"
            )
        return "Telemetry only"

    def _screen_awareness_trace_detail(self) -> str:
        state = self._screen_awareness_state()
        hardening = state.get("hardening")
        if isinstance(hardening, dict):
            latest = hardening.get("latest_trace")
            if isinstance(latest, dict):
                slowest_stage = (
                    str(latest.get("slowest_stage", "")).replace("_", " ").strip()
                )
                total_ms = latest.get("total_duration_ms")
                audit_passed = bool(latest.get("audit_passed", True))
                if slowest_stage and total_ms is not None:
                    return (
                        f"Latest screen trace took {total_ms} ms; slowest stage was {slowest_stage}. "
                        f"{'Audit passed.' if audit_passed else 'Audit flagged follow-up.'}"
                    )
            if bool(hardening.get("enabled")):
                return "Truthfulness audits, stage timing, and bounded traces are available when the screen-awareness stack runs."
        return "Telemetry is available, but Phase 12 hardening traces are not active in the current posture."

    def _screen_awareness_guard_label(self) -> str:
        state = self._screen_awareness_state()
        policy_state = state.get("policy_state")
        if isinstance(policy_state, dict) and bool(
            policy_state.get("restricted_domain_guarded", True)
        ):
            return "Restricted domains guarded"
        return "Guard state unknown"

    def _screen_awareness_guard_detail(self) -> str:
        state = self._screen_awareness_state()
        policy_state = state.get("policy_state")
        if isinstance(policy_state, dict):
            confirmation_required = bool(
                policy_state.get("confirmation_required", False)
            )
            if confirmation_required:
                return "Direct actions still require confirmation and protected surfaces remain visible in the policy state."
        return "Restricted-domain gating remains backend-owned so Helm mirrors real behavior instead of promising more than the runtime allows."

    def _tools_detail(self, tool_state: dict[str, Any]) -> str:
        if not isinstance(tool_state, dict):
            return "No enabled tools"
        enabled = [
            str(name).strip()
            for name in tool_state.get("enabled_tools", [])
            if str(name).strip()
        ]
        if not enabled:
            return "No enabled tools"
        catalog = self._tool_catalog()
        labels = [
            self._tool_display_name(catalog.get(name, {"name": name}))
            for name in enabled[:3]
        ]
        detail = ", ".join(label for label in labels if label)
        remaining = max(0, len(enabled) - len(labels))
        if remaining > 0:
            detail = f"{detail}, +{remaining} more"
        return detail or "No enabled tools"

    def _job_lane_entries(self, statuses: set[str]) -> list[dict[str, Any]]:
        entries = [
            {
                "title": self._module_label(str(job.get("tool_name", "operation"))),
                "eyebrow": str(job.get("status", "unknown")).replace("_", " ").title(),
                "meta": self._short_time(
                    str(
                        job.get("finished_at")
                        or job.get("started_at")
                        or job.get("created_at", "")
                    )
                ),
                "detail": self._job_detail(job),
                "severity": self._job_severity(str(job.get("status", ""))),
            }
            for job in self._jobs
            if str(job.get("status", "")).lower() in statuses
        ]
        if entries:
            return entries[:6]
        if "running" in statuses:
            return [
                {
                    "title": "No active jobs",
                    "eyebrow": "Watch",
                    "meta": "",
                    "detail": "The worker deck is clear right now.",
                    "severity": "steady",
                }
            ]
        if "queued" in statuses:
            return [
                {
                    "title": "Queue clear",
                    "eyebrow": "Dispatch",
                    "meta": "",
                    "detail": "Nothing is waiting on a worker slot at the moment.",
                    "severity": "steady",
                }
            ]
        if "completed" in statuses:
            return [
                {
                    "title": "No recent completions",
                    "eyebrow": "Watch",
                    "meta": "",
                    "detail": "Completed tool work will collect here after the next run.",
                    "severity": "steady",
                }
            ]
        if "pending" in statuses:
            return [
                {
                    "title": "No pending work",
                    "eyebrow": "Dispatch",
                    "meta": "",
                    "detail": "No prepared jobs are waiting to enter the queue.",
                    "severity": "steady",
                }
            ]
        return [
            {
                "title": "No held failures",
                "eyebrow": "Attention",
                "meta": "",
                "detail": "Watch is not carrying a recent failure, timeout, or cancellation right now.",
                "severity": "steady",
            }
        ]

    def _signal_timeline_entries(self) -> list[dict[str, Any]]:
        signal_state = self._signal_state()
        signals = (
            signal_state.get("signals", [])
            if isinstance(signal_state.get("signals"), list)
            else []
        )
        if signals:
            interpreted = [
                {
                    "title": str(signal.get("title", "Operational signal")),
                    "eyebrow": str(
                        signal.get("category", signal.get("source", "Signals"))
                    )
                    .replace("_", " ")
                    .title(),
                    "meta": str(signal.get("meta", "")),
                    "detail": str(signal.get("detail", "")),
                    "severity": str(signal.get("severity", "steady")),
                }
                for signal in signals[:8]
                if isinstance(signal, dict)
            ]
            if interpreted:
                return interpreted
        entries = [
            {
                "title": str(event.get("message", "Recent signal")),
                "eyebrow": str(event.get("subsystem", event.get("source", "core")))
                .replace("_", " ")
                .title(),
                "meta": self._short_time(
                    str(event.get("created_at") or event.get("timestamp", ""))
                ),
                "detail": self._event_detail(event),
                "severity": self._event_severity(event),
            }
            for event in self._recent_events(8)
        ]
        for job in self._jobs[:4]:
            status = str(job.get("status", "")).lower()
            if status not in {"completed", "failed", "timed_out", "cancelled"}:
                continue
            entries.append(
                {
                    "title": f"{self._module_label(str(job.get('tool_name', 'operation')))} {status.replace('_', ' ')}",
                    "eyebrow": "Watch",
                    "meta": self._short_time(
                        str(job.get("finished_at") or job.get("created_at", ""))
                    ),
                    "detail": self._job_detail(job),
                    "severity": self._job_severity(status),
                }
            )
        return entries[-8:] or [
            {
                "title": "No recent transition",
                "eyebrow": "Signals",
                "meta": "",
                "detail": "Signals is clear right now; no recent disruption, recovery, or completion is being held.",
                "severity": "steady",
            }
        ]

    def _logbook_timeline_entries(self) -> list[dict[str, Any]]:
        return [
            {
                "title": str(note.get("title", "Untitled note")),
                "eyebrow": "Logbook",
                "meta": self._short_time(str(note.get("created_at", ""))),
                "detail": str(note.get("content", ""))[:160],
            }
            for note in self._notes[:8]
        ] or [
            {
                "title": "No retained notes yet",
                "eyebrow": "Logbook",
                "meta": "",
                "detail": "Write to the logbook to retain local bearings.",
            }
        ]

    def _file_collection_items(
        self, *, include_recent: bool = False
    ) -> list[dict[str, Any]]:
        items = [
            item
            for item in self._opened_items
            if item.get("path") or item.get("viewer") != "browser"
        ]
        if include_recent:
            items = list(self._opened_items)
        collection = [
            {
                "title": str(item.get("title", "Untitled item")),
                "subtitle": str(item.get("viewer", item.get("kind", "item"))).title(),
                "detail": str(item.get("path", item.get("url", ""))),
                "badge": "Active"
                if item.get("itemId") == self._active_opened_item_id
                else "Held",
                "role": str(item.get("summary", "Curated working set item")).strip()
                or "Curated working set item",
            }
            for item in items[:8]
        ]
        return collection or [
            {
                "title": "No files held yet",
                "subtitle": "Working Set",
                "detail": "Ask Stormhelm to open a file in the Deck.",
                "badge": "Empty",
                "role": "Files will explain why each retained item belongs here.",
            }
        ]

    def _reference_items(
        self, *, include_all_browser: bool = False
    ) -> list[dict[str, Any]]:
        items = []
        for item in self._opened_items:
            if item.get("viewer") == "browser":
                items.append(item)
                continue
            if include_all_browser:
                items.append(item)
            elif item.get("summary") or item.get("url"):
                items.append(item)
        collection = [
            {
                "title": str(item.get("title", "Reference")),
                "subtitle": "Deck reference"
                if item.get("viewer") == "browser"
                else str(item.get("viewer", item.get("kind", "item"))).title(),
                "detail": str(item.get("url", item.get("path", ""))),
                "badge": "Active"
                if item.get("itemId") == self._active_opened_item_id
                else "Support",
                "role": str(
                    item.get("summary", "Support material for the current task")
                ).strip()
                or "Support material for the current task",
            }
            for item in items[:8]
        ]
        return collection or [
            {
                "title": "No references gathered yet",
                "subtitle": "Research",
                "detail": "Bring docs, pages, or relevant files into the Deck to seed references.",
                "badge": "Empty",
                "role": "References hold supporting evidence, not the main active thread.",
            }
        ]

    def _logbook_collection_items(self) -> list[dict[str, Any]]:
        collection = [
            {
                "title": str(note.get("title", "Untitled note")),
                "subtitle": self._short_time(str(note.get("created_at", ""))),
                "detail": str(note.get("content", ""))[:160],
                "badge": "Retained",
                "role": "Local mission memory",
            }
            for note in self._notes[:8]
        ]
        if self._workspace_focus.get("summary"):
            collection.insert(
                0,
                {
                    "title": str(
                        self._workspace_focus.get("name", "Current workspace")
                    ),
                    "subtitle": "Where we left off",
                    "detail": str(self._workspace_focus.get("summary")),
                    "badge": "Carryover",
                    "role": "Retained workspace bearing",
                },
            )
        return collection or [
            {
                "title": "No retained memory yet",
                "subtitle": "Logbook",
                "detail": "Saved notes and remembered bearings will gather here.",
                "badge": "Empty",
                "role": "Logbook holds retained context, not raw chat history.",
            }
        ]

    def _format_bytes(self, value: Any) -> str:
        try:
            size = float(value or 0)
        except (TypeError, ValueError):
            return ""
        if size <= 0:
            return ""
        units = ["B", "KB", "MB", "GB", "TB"]
        index = 0
        while size >= 1024 and index < len(units) - 1:
            size /= 1024
            index += 1
        return f"{size:.1f} {units[index]}"

    def _format_duration(self, value: Any) -> str:
        try:
            seconds = int(value or 0)
        except (TypeError, ValueError):
            return ""
        if seconds <= 0:
            return ""
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _workspace_canvas_columns(self) -> list[dict[str, Any]]:
        if self._active_module_key == "helm":
            if self._active_workspace_section_key == "safety":
                return [
                    self._workspace_column(
                        "Access Policy",
                        "Backend-provided read boundaries and shell posture.",
                        [
                            {
                                "primary": "Read Scope",
                                "secondary": self._read_scope_label(),
                                "detail": self._read_scope_detail(),
                            },
                            {
                                "primary": "Shell Command",
                                "secondary": self._shell_command_label(),
                                "detail": self._shell_command_detail(),
                            },
                            {
                                "primary": "Screen Bearings",
                                "secondary": self._screen_awareness_phase_label(),
                                "detail": self._screen_awareness_policy_detail(),
                            },
                            {
                                "primary": "Action Policy",
                                "secondary": self._screen_awareness_policy_mode_label(),
                                "detail": self._screen_awareness_guard_detail(),
                            },
                        ],
                    ),
                    self._workspace_column(
                        "Control Surface",
                        "How policy changes reach the running shell.",
                        [
                            {
                                "primary": "Config Fallback",
                                "secondary": "portable.toml / user.toml",
                                "detail": "Advanced policy still lives in config files for deliberate edits.",
                            },
                            {
                                "primary": "Close Behavior",
                                "secondary": "Fade to tray"
                                if self._hide_to_tray_on_close
                                else "Exit window",
                                "detail": "Quick controls stay in the tray while Helm carries the fuller posture.",
                            },
                            {
                                "primary": "Traceability",
                                "secondary": self._screen_awareness_trace_label(),
                                "detail": self._screen_awareness_trace_detail(),
                            },
                        ],
                    ),
                ]
            return [
                self._workspace_column(
                    "Presence",
                    "How Stormhelm manifests across modes.",
                    [
                        {
                            "primary": "Ghost Mode",
                            "secondary": "Spectral overlay",
                            "detail": "Mouse click-through, keyboard signaling.",
                        },
                        {
                            "primary": "Command Deck",
                            "secondary": "Deeper field",
                            "detail": "A stronger workspace layer unfolding from the anchor.",
                        },
                        {
                            "primary": "Dormant",
                            "secondary": "Background ready",
                            "detail": "Tray-first and silent until summoned.",
                        },
                    ],
                ),
                self._workspace_column(
                    "Control",
                    "Behavior and quick-setting direction.",
                    [
                        {
                            "primary": "Screen Bearings",
                            "secondary": self._screen_awareness_phase_label(),
                            "detail": self._screen_awareness_policy_detail(),
                        },
                        {
                            "primary": "Action Policy",
                            "secondary": self._screen_awareness_policy_mode_label(),
                            "detail": self._screen_awareness_guard_detail(),
                        },
                        {
                            "primary": "Traceability",
                            "secondary": self._screen_awareness_trace_label(),
                            "detail": self._screen_awareness_trace_detail(),
                        },
                        {
                            "primary": "Ghost Shortcut",
                            "secondary": self.config.ui.ghost_shortcut,
                            "detail": "Summons Ghost capture from anywhere.",
                        },
                        {
                            "primary": "Close Behavior",
                            "secondary": "Fade to tray"
                            if self._hide_to_tray_on_close
                            else "Exit window",
                            "detail": "Quick controls stay in the tray.",
                        },
                        {
                            "primary": "Safety",
                            "secondary": "Always gated",
                            "detail": "No unrestricted action surfaces are added here.",
                        },
                    ],
                ),
            ]

        if self._active_module_key == "systems":
            resources = self._resource_state()
            power = self._power_state()
            hardware = self._hardware_state()
            provider = self._provider_state()
            software_control = self._software_control_state()
            software_recovery = self._software_recovery_state()
            lifecycle = self._lifecycle_state()
            trust_state = self._trust_state()
            storage = self._storage_state()
            drives = (
                storage.get("drives", [])
                if isinstance(storage.get("drives"), list)
                else []
            )
            primary_drive = drives[0] if drives else {}
            install_state = (
                lifecycle.get("install_state")
                if isinstance(lifecycle.get("install_state"), dict)
                else {}
            )
            startup_policy = (
                lifecycle.get("startup_policy")
                if isinstance(lifecycle.get("startup_policy"), dict)
                else {}
            )
            startup_registration = (
                startup_policy.get("registration")
                if isinstance(startup_policy.get("registration"), dict)
                else {}
            )
            runtime_state = (
                lifecycle.get("runtime")
                if isinstance(lifecycle.get("runtime"), dict)
                else {}
            )
            bootstrap = (
                lifecycle.get("bootstrap")
                if isinstance(lifecycle.get("bootstrap"), dict)
                else {}
            )
            resolution_plan = (
                bootstrap.get("resolution_plan")
                if isinstance(bootstrap.get("resolution_plan"), dict)
                else {}
            )
            resolution_state = (
                bootstrap.get("resolution_state")
                if isinstance(bootstrap.get("resolution_state"), dict)
                else {}
            )
            uninstall_plan = (
                lifecycle.get("uninstall_plan")
                if isinstance(lifecycle.get("uninstall_plan"), dict)
                else {}
            )
            cleanup_execution = (
                uninstall_plan.get("cleanup_execution")
                if isinstance(uninstall_plan.get("cleanup_execution"), dict)
                else {}
            )
            destructive_cleanup_plan = (
                uninstall_plan.get("destructive_cleanup_plan")
                if isinstance(uninstall_plan.get("destructive_cleanup_plan"), dict)
                else {}
            )
            pending_requests = (
                trust_state.get("pending_requests", [])
                if isinstance(trust_state.get("pending_requests"), list)
                else []
            )
            active_grants = (
                trust_state.get("active_grants", [])
                if isinstance(trust_state.get("active_grants"), list)
                else []
            )
            recent_audit = (
                trust_state.get("recent_audit", [])
                if isinstance(trust_state.get("recent_audit"), list)
                else []
            )
            return [
                self._workspace_column(
                    "Live Telemetry",
                    "Current machine load and capacity bearings.",
                    [
                        {
                            "primary": "CPU Load",
                            "secondary": self._cpu_load_label(resources),
                            "detail": self._cpu_detail_text(resources),
                        },
                        {
                            "primary": "GPU Load",
                            "secondary": self._gpu_load_label(resources),
                            "detail": self._gpu_detail_text(resources),
                        },
                        {
                            "primary": "Memory",
                            "secondary": self._memory_used_label(resources),
                            "detail": self._memory_detail(resources),
                        },
                        {
                            "primary": "Storage",
                            "secondary": self._drive_free_label(primary_drive),
                            "detail": self._drive_detail(primary_drive),
                        },
                    ],
                ),
                self._workspace_column(
                    "Telemetry Support",
                    "Sampling posture and service readiness.",
                    [
                        {
                            "primary": "Battery",
                            "secondary": self._battery_label(power),
                            "detail": self._power_detail_text(power),
                        },
                        {
                            "primary": "Telemetry",
                            "secondary": self._telemetry_status_label(hardware),
                            "detail": self._telemetry_detail_text(hardware),
                        },
                        {
                            "primary": "Provider",
                            "secondary": "Configured"
                            if provider.get("configured")
                            else "Offline",
                            "detail": self._provider_detail(provider),
                        },
                        {
                            "primary": "Runtime",
                            "secondary": self._runtime_mode_label.title(),
                            "detail": self._environment_label.title(),
                        },
                    ],
                ),
                self._workspace_column(
                    "Software Bearings",
                    "Native software control and recovery posture.",
                    [
                        {
                            "primary": "Control Lane",
                            "secondary": "Enabled"
                            if software_control.get("enabled")
                            else "Disabled",
                            "detail": str(
                                (
                                    software_control.get("last_trace", {})
                                    if isinstance(
                                        software_control.get("last_trace"), dict
                                    )
                                    else {}
                                ).get(
                                    "execution_status", "Awaiting a software request."
                                )
                            )
                            .replace("_", " ")
                            .title(),
                        },
                        {
                            "primary": "Route Policy",
                            "secondary": "Package managers"
                            if software_control.get("package_manager_routes_enabled")
                            else "Restricted",
                            "detail": "Browser-guided acquisition is available."
                            if software_control.get("browser_guided_routes_enabled")
                            else "Browser-guided acquisition is disabled.",
                        },
                        {
                            "primary": "Recovery",
                            "secondary": "Cloud advisory off"
                            if not software_recovery.get("cloud_fallback_enabled")
                            else "Cloud advisory ready",
                            "detail": str(
                                (
                                    software_recovery.get("last_trace", {})
                                    if isinstance(
                                        software_recovery.get("last_trace"), dict
                                    )
                                    else {}
                                ).get("status", "No recovery trace yet.")
                            )
                            .replace("_", " ")
                            .title(),
                        },
                    ],
                ),
                self._workspace_column(
                    "Lifecycle",
                    "Install posture, startup truth, and cleanup boundaries.",
                    [
                        {
                            "primary": "Install Mode",
                            "secondary": str(
                                install_state.get(
                                    "install_mode", self._install_mode_label
                                )
                            )
                            .replace("_", " ")
                            .title(),
                            "detail": "Runtime posture is resolved locally from packaged/source evidence.",
                        },
                        {
                            "primary": "Startup",
                            "secondary": "Enabled"
                            if startup_policy.get("startup_enabled")
                            else "Disabled",
                            "detail": str(
                                startup_registration.get(
                                    "operator_summary",
                                    str(
                                        startup_policy.get(
                                            "registration_status", "unavailable"
                                        )
                                    )
                                    .replace("_", " ")
                                    .title(),
                                )
                                or str(
                                    startup_policy.get(
                                        "registration_status", "unavailable"
                                    )
                                )
                                .replace("_", " ")
                                .title()
                            ),
                        },
                        {
                            "primary": "Core / Shell",
                            "secondary": (
                                f"{str(runtime_state.get('core_status', 'unknown')).replace('_', ' ').title()} / "
                                f"{str(runtime_state.get('shell_status', 'unknown')).replace('_', ' ').title()}"
                            ),
                            "detail": (
                                f"Tray {str(runtime_state.get('tray_status', 'unknown')).replace('_', ' ').title()} | "
                                f"{int(runtime_state.get('connected_clients', 0) or 0)} attached shell"
                                f"{'' if int(runtime_state.get('connected_clients', 0) or 0) == 1 else 's'}."
                            ),
                        },
                        {
                            "primary": "Resolution",
                            "secondary": (
                                "Ready"
                                if resolution_plan.get("resolvable")
                                else "Manual"
                                if resolution_plan
                                else "Clear"
                            ),
                            "detail": str(
                                resolution_state.get("last_resolution_summary")
                                or resolution_plan.get("summary")
                                or resolution_plan.get("operator_action_notes")
                                or "Stormhelm is not holding an active lifecycle resolution step."
                            ),
                        },
                        {
                            "primary": "Cleanup",
                            "secondary": "Preserve durable state"
                            if not uninstall_plan.get("remove_durable_state")
                            else "Remove durable state",
                            "detail": str(
                                cleanup_execution.get(
                                    "operator_summary",
                                    destructive_cleanup_plan.get(
                                        "operator_summary",
                                        uninstall_plan.get(
                                            "portable_cleanup_notes",
                                            "Stormhelm will preserve durable state unless the operator explicitly requests deep cleanup.",
                                        ),
                                    ),
                                )
                            ),
                        },
                    ],
                ),
                self._workspace_column(
                    "Trust Bearings",
                    "Approval posture, reusable grants, and recent trust audit.",
                    [
                        {
                            "primary": "Pending Approval",
                            "secondary": str(len(pending_requests)),
                            "detail": (
                                str(
                                    (
                                        pending_requests[0]
                                        if pending_requests
                                        and isinstance(pending_requests[0], dict)
                                        else {}
                                    ).get("operator_message", "No pending approval.")
                                )
                                if pending_requests
                                else "No pending approval."
                            ),
                        },
                        {
                            "primary": "Active Grants",
                            "secondary": str(len(active_grants)),
                            "detail": (
                                str(
                                    (
                                        active_grants[0]
                                        if active_grants
                                        and isinstance(active_grants[0], dict)
                                        else {}
                                    ).get("subject", "No active grants")
                                )
                                if active_grants
                                else "No active grants."
                            ),
                        },
                        {
                            "primary": "Recent Audit",
                            "secondary": str(len(recent_audit)),
                            "detail": (
                                str(
                                    (
                                        recent_audit[0]
                                        if recent_audit
                                        and isinstance(recent_audit[0], dict)
                                        else {}
                                    ).get("summary", "No recent trust audit.")
                                )
                                if recent_audit
                                else "No recent trust audit."
                            ),
                        },
                    ],
                ),
                *self._bridge_authority_columns(),
            ]

        if self._active_module_key == "logbook":
            note_entries = [
                {
                    "primary": str(note.get("title", "Untitled")),
                    "secondary": self._short_time(str(note.get("created_at", ""))),
                    "detail": str(note.get("content", ""))[:120],
                }
                for note in self._notes[:4]
            ] or [
                {
                    "primary": "No entries yet",
                    "secondary": "Logbook",
                    "detail": "Write a note from the side module to seed local memory.",
                }
            ]
            return [
                self._workspace_column(
                    "Entries", "Recent notes held close.", note_entries
                ),
                self._workspace_column(
                    "Direction",
                    "Where memory surfaces are headed.",
                    [
                        {
                            "primary": "Drafts",
                            "secondary": "Reserved",
                            "detail": "Light drafting surfaces will live here.",
                        },
                        {
                            "primary": "Timeline",
                            "secondary": "Reserved",
                            "detail": "Chronological memory review remains a future pass.",
                        },
                        {
                            "primary": "Recall",
                            "secondary": "Local-first",
                            "detail": "Prepared for richer retrieval later without claiming it now.",
                        },
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
            ] or [
                {
                    "primary": "Quiet watch",
                    "secondary": "No recent jobs",
                    "detail": "Tool activity will surface here when the core is busy.",
                }
            ]
            event_entries = [
                {
                    "primary": str(event.get("message", "No recent signal.")),
                    "secondary": str(event.get("severity", event.get("level", "INFO")))
                    .replace("_", " ")
                    .title(),
                    "detail": self._short_time(str(event.get("created_at", ""))),
                }
                for event in self._recent_events_newest_first(4)
            ] or [
                {
                    "primary": "No fresh signal",
                    "secondary": "Standby",
                    "detail": "Watch remains calm until activity resumes.",
                }
            ]
            return [
                self._workspace_column("Jobs", "Recent operational work.", job_entries),
                self._workspace_column(
                    "Timeline", "Latest activity signal.", event_entries
                ),
            ]

        if self._active_module_key == "signals":
            message_entries = [
                {
                    "primary": str(message.get("content", ""))[:88] or "Signal trace",
                    "secondary": str(message.get("speaker", "Stormhelm")),
                    "detail": str(message.get("shortTime", "")),
                }
                for message in self._display_history()[-4:]
            ] or [
                {
                    "primary": "No active signal trace",
                    "secondary": "Standby",
                    "detail": "Recent conversations will surface here.",
                }
            ]
            event_entries = [
                {
                    "primary": str(event.get("message", "No recent signal.")),
                    "secondary": str(event.get("severity", event.get("level", "INFO")))
                    .replace("_", " ")
                    .title(),
                    "detail": str(event.get("created_at", "")),
                }
                for event in self._recent_events_newest_first(4)
            ] or [
                {
                    "primary": "No recent events",
                    "secondary": "Quiet sea",
                    "detail": "Event telemetry will appear here as needed.",
                }
            ]
            return [
                self._workspace_column(
                    "Live Signal",
                    "Recent conversational and operational signal.",
                    message_entries,
                ),
                self._workspace_column(
                    "Events", "System signal and event trace.", event_entries
                ),
            ]

        if self._active_module_key == "files":
            return [
                self._workspace_column(
                    "Working Set",
                    "Held files, safe reads, and hand-off posture for the current mission.",
                    [
                        {
                            "primary": "Safe Reads",
                            "secondary": "Enabled",
                            "detail": "The file reader remains allowlist-bound.",
                        },
                        {
                            "primary": "Deck Working Set",
                            "secondary": "Active",
                            "detail": "Files opened inside Stormhelm stay attached to the current workspace.",
                        },
                        {
                            "primary": "Native Hand-off",
                            "secondary": "Available",
                            "detail": "Stormhelm should still lean on Explorer and default apps when appropriate.",
                        },
                    ],
                )
            ]

        if self._active_module_key == "browser":
            return [
                self._workspace_column(
                    "Research Bearings",
                    "Research pages, cited material, and browser hand-off posture for the active workspace.",
                    [
                        {
                            "primary": "Deck Pages",
                            "secondary": "Held Internally",
                            "detail": "Stormhelm can keep the pages that matter inside the Deck for active work.",
                        },
                        {
                            "primary": "External Browser",
                            "secondary": "Still Available",
                            "detail": "Native browser hand-off remains the better path when the full external surface is needed.",
                        },
                        {
                            "primary": "Sources",
                            "secondary": "Workspace Support",
                            "detail": "References and evidence travel with the workspace instead of disappearing into a tab strip.",
                        },
                    ],
                )
            ]

        if self._active_module_key == "visual-context":
            return [
                self._workspace_column(
                    "Future Context",
                    "This space remains reserved for later screen-aware guidance.",
                    [
                        {
                            "primary": "Focus Surface",
                            "secondary": "Reserved",
                            "detail": "The visual layer is staged but not claimed as implemented.",
                        },
                        {
                            "primary": "Guidance",
                            "secondary": "Future pass",
                            "detail": "Recommendations can later emerge from what Stormhelm sees.",
                        },
                    ],
                )
            ]

        message_entries = [
            {
                "primary": str(message.get("content", ""))[:92]
                or "No conversation yet",
                "secondary": str(message.get("speaker", "Stormhelm")),
                "detail": str(message.get("shortTime", "")),
            }
            for message in self._display_history()[-4:]
        ] or [
            {
                "primary": "Awaiting a bearing",
                "secondary": "Chartroom",
                "detail": "Use Ghost capture or the command spine to start a thread.",
            }
        ]
        note_entries = [
            {
                "primary": str(note.get("title", "Untitled")),
                "secondary": self._short_time(str(note.get("created_at", ""))),
                "detail": str(note.get("content", ""))[:120],
            }
            for note in self._notes[:3]
        ] or [
            {
                "primary": "No nearby notes",
                "secondary": "Logbook",
                "detail": "Saved notes will travel with the workspace here.",
            }
        ]
        signal_entries = [
            {
                "primary": str(event.get("message", "No recent signal.")),
                "secondary": str(event.get("severity", event.get("level", "INFO")))
                .replace("_", " ")
                .title(),
                "detail": self._short_time(str(event.get("created_at", ""))),
            }
            for event in self._recent_events_newest_first(3)
        ] or [
            {
                "primary": "Signal steady",
                "secondary": self.connectionLabel,
                "detail": self._status_line,
            }
        ]
        return [
            self._workspace_column(
                "Active Thread", "The current exchange with Stormhelm.", message_entries
            ),
            self._workspace_column(
                "Logbook", "Notes and retained mission memory.", note_entries
            ),
            self._workspace_column(
                "Signal", "Operational context held alongside the work.", signal_entries
            ),
        ]

    def _workspace_section_label(self, key: str) -> str:
        return key.replace("-", " ").title()

    def _workspace_column(
        self, title: str, summary: str, entries: list[dict[str, Any]]
    ) -> dict[str, Any]:
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
                "body": (
                    "Helm is where behavior, presence, hotkeys, and policy surface in the deck. "
                    f"Read scope is {self._read_scope_label().lower()} and shell command access is {self._shell_command_label().lower()}."
                ),
                "entries": [
                    {
                        "primary": "Screen Bearings",
                        "secondary": self._screen_awareness_phase_label(),
                        "detail": self._screen_awareness_policy_detail(),
                    },
                    {
                        "primary": "Action Policy",
                        "secondary": self._screen_awareness_policy_mode_label(),
                        "detail": self._screen_awareness_guard_detail(),
                    },
                    {
                        "primary": "Traceability",
                        "secondary": self._screen_awareness_trace_label(),
                        "detail": self._screen_awareness_trace_detail(),
                    },
                    {
                        "primary": "Ghost Shortcut",
                        "secondary": self.config.ui.ghost_shortcut,
                        "detail": "Summons Ghost text capture from anywhere.",
                    },
                    {
                        "primary": "Tray Close",
                        "secondary": "Fade to dormant"
                        if self._hide_to_tray_on_close
                        else "Close window",
                        "detail": "Quick controls belong in the tray, not a full settings dashboard.",
                    },
                    {
                        "primary": "Read Scope",
                        "secondary": self._read_scope_label(),
                        "detail": self._read_scope_detail(),
                    },
                    {
                        "primary": "Shell Command",
                        "secondary": self._shell_command_label(),
                        "detail": self._shell_command_detail(),
                    },
                    {
                        "primary": "Config Fallback",
                        "secondary": "portable.toml / user.toml",
                        "detail": "Advanced and power-user behavior remains file-backed.",
                    },
                ],
            }
        if normalized == "logbook":
            return self._build_logbook_module()
        if normalized == "watch":
            return self._build_watch_module()
        if normalized == "signals":
            return self._build_signals_module()
        if normalized == "systems":
            return self._build_systems_module()
        if normalized == "files":
            return self._build_files_module()
        if normalized == "browser":
            browser_items = [
                item for item in self._opened_items if item.get("viewer") == "browser"
            ]
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
                ]
                or [
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
        items = [
            {"label": "Mode", "value": "Ghost" if self._mode == "ghost" else "Deck"},
            {"label": "State", "value": self._assistant_state.title()},
            {"label": "Signal", "value": self.connectionLabel},
            {"label": "Install", "value": self._install_mode_label.title()},
            {"label": "Time", "value": self._local_time_label},
            {"label": "Helm", "value": self._active_module_label()},
            {"label": "Version", "value": self._core_version_label},
        ]
        if self._voice_surface_visible():
            voice_label = (
                str(self._voice_state.get("voice_current_phase") or "unavailable")
                .replace("_", " ")
                .title()
            )
            items.insert(3, {"label": "Voice", "value": voice_label})
        return items

    def _ghost_voice_readout_label(self) -> str:
        if self._voice_state.get("active_capture_id"):
            return "Push-to-talk capture active"
        if not self._voice_state.get("voice_available"):
            return "Voice unavailable"
        if not self._voice_state.get("capture_enabled"):
            return "Capture disabled"
        if not self._voice_state.get("capture_available"):
            return "Provider unavailable"
        return "Push-to-talk ready"

    def _build_ghost_corner_readouts(self) -> list[dict[str, Any]]:
        display_history = self._display_history()
        latest_message = self._latest_assistant_message() or (
            display_history[-1] if display_history else None
        )
        latest_job = self._jobs[0] if self._jobs else None
        latest_note = self._notes[0] if self._notes else None

        bearing_title = "Bearing"
        recent_context = "Standing watch."
        if self._active_task and latest_message is None:
            bearing_title = str(self._active_task.get("title", bearing_title))[:48]
            recent_context = str(
                self._active_task.get("whereLeftOff")
                or self._active_task.get("latestSummary")
                or recent_context
            )[:96]
        elif latest_message is not None:
            bearing_title = self._message_bearing_title(latest_message) or bearing_title
            recent_context = self._message_micro(latest_message)
        elif latest_note is not None:
            recent_context = str(latest_note.get("title", recent_context))

        recent_action = "Deck via tray"
        if self._mode == "deck":
            recent_action = f"{self._module_label(self._active_module_key)} aligned"
        elif latest_job is not None:
            recent_action = self._module_label(
                str(latest_job.get("tool_name", "action"))
            )

        job_secondary = "Spectral watch"
        if latest_job is not None:
            job_secondary = str(latest_job.get("status", "pending")).title()
        elif self._mode == "deck":
            job_secondary = "Command field deepened"

        readouts = [
            {
                "corner": "top_left",
                "label": "Stormhelm",
                "primary": "Ghost Mode" if self._mode == "ghost" else "Command Deck",
                "secondary": self._ghost_voice_readout_label()
                if self._voice_surface_visible()
                else (
                    "Signal capture ready"
                    if self._ghost_capture_active
                    else self._assistant_state.title()
                ),
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
                "primary": bearing_title[:48],
                "secondary": recent_context[:96],
            },
            {
                "corner": "bottom_right",
                "label": "Helm",
                "primary": "Enter sends · Esc clears"
                if self._ghost_capture_active
                else recent_action,
                "secondary": self.config.ui.ghost_shortcut
                if not self._ghost_capture_active
                else job_secondary,
            },
        ]
        authority_cards = self._bridge_authority_context_cards()
        if authority_cards:
            authority_card = authority_cards[0]
            readouts[2] = {
                "corner": "bottom_left",
                "label": "Authority",
                "primary": str(authority_card.get("title", "Authority"))[:48],
                "secondary": str(authority_card.get("body", ""))[:96],
            }
        return readouts

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

    def _build_systems_module(self) -> dict[str, Any]:
        return {
            "key": "systems",
            "kind": "system",
            "title": "Systems",
            "eyebrow": "Core",
            "headline": "Live machine, provider, and runtime bearings",
            "body": "Systems is the machine-state surface: power, compute, storage, signal, and provider posture held in one disciplined watch.",
            "stats": self._workspace_canvas_stats(),
            "sections": self._module_sections_from_fact_groups(
                self._workspace_canvas_fact_groups()
            ),
            "entries": [],
        }

    def _build_watch_module(self) -> dict[str, Any]:
        watch_entries = [
            {
                "primary": self._module_label(str(job.get("tool_name", "operation"))),
                "secondary": str(job.get("status", "queued")).replace("_", " ").title(),
                "detail": self._job_summary(job),
            }
            for job in self._jobs[:5]
        ]
        if not watch_entries:
            watch_state = self._watch_state()
            watch_tasks = (
                watch_state.get("tasks", [])
                if isinstance(watch_state.get("tasks"), list)
                else []
            )
            watch_entries = [
                {
                    "primary": str(task.get("title", "Operation")),
                    "secondary": str(task.get("status", "ready"))
                    .replace("_", " ")
                    .title(),
                    "detail": str(task.get("detail", "")),
                }
                for task in watch_tasks[:5]
                if isinstance(task, dict)
            ]
        if not watch_entries:
            watch_state = self._watch_state()
            completed_recently = int(watch_state.get("completed_recently", 0) or 0)
            recent_failures = int(watch_state.get("recent_failures", 0) or 0)
            watch_entries = [
                {
                    "primary": "Worker deck clear",
                    "secondary": f"{watch_state.get('worker_capacity', self.config.concurrency.max_workers)} workers ready",
                    "detail": "No active jobs or queued work are being held right now.",
                },
                {
                    "primary": "Recent completions",
                    "secondary": str(completed_recently),
                    "detail": (
                        "No recent completions are being held."
                        if completed_recently <= 0
                        else f"{completed_recently} recent completion{'s' if completed_recently != 1 else ''} are still in memory."
                    ),
                },
            ]
            if recent_failures > 0:
                watch_entries.append(
                    {
                        "primary": "Recent failures",
                        "secondary": str(recent_failures),
                        "detail": "Attention still holds recent failed or timed-out work.",
                    }
                )
        return {
            "key": "watch",
            "kind": "jobs",
            "title": "Watch",
            "eyebrow": "Operations",
            "headline": "Worker posture, in-flight jobs, and recent failures",
            "body": "Watch answers what Stormhelm is doing now, what just happened, and where pressure is building across the worker deck.",
            "stats": self._workspace_canvas_stats(),
            "sections": self._workspace_canvas_watch_lanes(),
            "entries": watch_entries,
        }

    def _tool_inventory_catalog(self) -> list[dict[str, Any]]:
        catalog = self._tool_catalog()
        tool_names = set(catalog)
        tool_names.update(self._enabled_tool_names())
        inventory: list[dict[str, Any]] = []
        for name in tool_names:
            metadata = dict(catalog.get(name, {"name": name}))
            metadata.setdefault("display_name", self._module_label(name))
            inventory.append(
                {
                    "name": name,
                    "display_name": self._tool_display_name(metadata),
                    "description": str(metadata.get("description", "")).strip(),
                    "category": str(metadata.get("category", "")).strip(),
                    "classification": str(metadata.get("classification", "")).strip(),
                    "execution_mode": str(
                        metadata.get("execution_mode", "sync")
                    ).strip()
                    or "sync",
                    "timeout_seconds": metadata.get("timeout_seconds"),
                    "enabled": self._tool_enabled(name),
                }
            )
        inventory.sort(
            key=lambda item: (not item["enabled"], item["display_name"].lower())
        )
        return inventory

    def _tool_inventory_items(self) -> list[dict[str, Any]]:
        catalog = self._tool_inventory_catalog()
        if not catalog:
            return [
                {
                    "title": "No tool catalog yet",
                    "badge": "Unavailable",
                    "subtitle": "Watch Tools",
                    "role": "Stormhelm has not received any tool metadata from the backend snapshot yet.",
                    "detail": "A fresh snapshot should repopulate the capability inventory.",
                }
            ]
        return [
            {
                "title": tool["display_name"],
                "badge": self._tool_classification_label(tool["classification"]),
                "subtitle": f"{self._tool_category_label(tool['category'])} - {'Enabled' if tool['enabled'] else 'Disabled'}",
                "role": tool["description"] or "No description available.",
                "detail": self._tool_inventory_detail(tool),
            }
            for tool in catalog
        ]

    def _watch_timeline_entries(self) -> list[dict[str, Any]]:
        if self._jobs:
            catalog = self._tool_catalog()
            return [
                {
                    "title": self._tool_display_name(
                        catalog.get(
                            str(job.get("tool_name", "")).strip(),
                            {"name": str(job.get("tool_name", ""))},
                        )
                    ),
                    "eyebrow": str(job.get("status", "pending"))
                    .replace("_", " ")
                    .title(),
                    "meta": self._short_time(
                        str(
                            job.get("finished_at")
                            or job.get("started_at")
                            or job.get("created_at", "")
                        )
                    ),
                    "detail": self._job_detail(job),
                    "severity": self._job_severity(str(job.get("status", ""))),
                }
                for job in self._jobs[:10]
            ]
        return [
            {
                "title": "No recent jobs",
                "eyebrow": "Watch",
                "meta": "",
                "detail": "Recent tool executions will appear here once the worker deck has movement.",
                "severity": "steady",
            }
        ]

    def _build_files_module(self) -> dict[str, Any]:
        active_title = str(
            self._get_active_opened_item().get("title", "No active item")
        )
        file_items = self._file_collection_items()
        return {
            "key": "files",
            "kind": "workspace",
            "title": "Files",
            "eyebrow": "Working Set",
            "headline": "Curated files and held deck items for the current mission",
            "body": "Files keeps the current working set visible, explains why each item matters, and separates deck-held surfaces from native hand-off decisions.",
            "stats": self._workspace_canvas_stats(),
            "sections": [
                {
                    "title": "Opened Now",
                    "summary": "Items currently held in the deck workspace.",
                    "entries": [
                        {
                            "primary": item["title"],
                            "secondary": item["badge"],
                            "detail": item["role"],
                        }
                        for item in file_items[:4]
                    ],
                },
                {
                    "title": "Active Focus",
                    "summary": "The item currently carrying the main bearing.",
                    "entries": [
                        {
                            "primary": active_title,
                            "secondary": "Deck active item",
                            "detail": str(
                                self._get_active_opened_item().get(
                                    "path",
                                    self._get_active_opened_item().get("url", ""),
                                )
                            ),
                        }
                    ],
                },
                {
                    "title": "Open Posture",
                    "summary": "How Stormhelm should route the next open decision.",
                    "entries": [
                        {
                            "primary": "Internal Deck",
                            "secondary": "Preferred",
                            "detail": "Use the Deck for curated working files and persistent context.",
                        },
                        {
                            "primary": "External Hand-off",
                            "secondary": "Available",
                            "detail": "Use native apps when the task wants the full external surface.",
                        },
                    ],
                },
            ],
            "entries": [
                {
                    "primary": item["title"],
                    "secondary": item["subtitle"],
                    "detail": item["detail"],
                }
                for item in file_items[:5]
            ],
        }

    def _build_logbook_module(self) -> dict[str, Any]:
        note_entries = [
            {
                "primary": item["title"],
                "secondary": item["subtitle"],
                "detail": item["detail"],
            }
            for item in self._logbook_collection_items()[:5]
        ]
        return {
            "key": "logbook",
            "kind": "notes",
            "title": "Logbook",
            "eyebrow": "Memory",
            "headline": "Retained notes, carryover, and trusted local memory",
            "body": "Logbook holds the bearings worth keeping: saved notes, where-we-left-off carryover, and remembered fragments the mission should not lose.",
            "stats": self._workspace_canvas_stats(),
            "sections": [
                {
                    "title": "Retained Notes",
                    "summary": "Saved entries the operator can trust to remain.",
                    "entries": note_entries[:4],
                },
                {
                    "title": "Carryover",
                    "summary": "Where the current workspace last left off.",
                    "entries": [
                        {
                            "primary": str(
                                self._workspace_focus.get("name", "No active workspace")
                            ),
                            "secondary": "Where we left off",
                            "detail": str(
                                self._workspace_focus.get(
                                    "summary",
                                    "Retained workspace summaries will appear here once a workspace is active.",
                                )
                            ),
                        }
                    ],
                },
            ],
            "entries": note_entries,
        }

    def _build_signals_module(self) -> dict[str, Any]:
        timeline = self._signal_timeline_entries()
        alerts = [
            entry
            for entry in timeline
            if str(entry.get("severity", "")).lower() in {"warning", "attention"}
        ]
        return {
            "key": "signals",
            "kind": "events",
            "title": "Signals",
            "eyebrow": "Telemetry",
            "headline": "Interpreted recent outcomes and meaningful transitions",
            "body": "Signals surfaces what mattered recently instead of dumping raw logs: completions, disruptions, status shifts, and signal worth attention.",
            "stats": self._workspace_canvas_stats(),
            "sections": [
                {
                    "title": "High Signal",
                    "summary": "The freshest interpreted outcomes.",
                    "entries": [
                        {
                            "primary": entry["title"],
                            "secondary": entry["eyebrow"]
                            + (f" | {entry['meta']}" if entry.get("meta") else ""),
                            "detail": entry["detail"],
                        }
                        for entry in timeline[:4]
                    ],
                },
                {
                    "title": "Attention",
                    "summary": "Warnings or unusual conditions worth review.",
                    "entries": [
                        {
                            "primary": entry["title"],
                            "secondary": entry["eyebrow"]
                            + (f" | {entry['meta']}" if entry.get("meta") else ""),
                            "detail": entry["detail"],
                        }
                        for entry in alerts[:3]
                    ]
                    or [
                        {
                            "primary": "Signal steady",
                            "secondary": self.connectionLabel,
                            "detail": "No recent warnings are held in Signals.",
                        }
                    ],
                },
            ],
            "entries": [
                {
                    "primary": entry["title"],
                    "secondary": entry["eyebrow"]
                    + (f" | {entry['meta']}" if entry.get("meta") else ""),
                    "detail": entry["detail"],
                }
                for entry in timeline[:5]
            ],
        }

    def _module_sections_from_fact_groups(
        self, groups: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "title": str(group.get("title", "")),
                "summary": str(group.get("summary", "")),
                "entries": [
                    {
                        "primary": str(row.get("label", "")),
                        "secondary": str(row.get("value", "")),
                        "detail": str(row.get("detail", "")),
                    }
                    for row in group.get("rows", [])
                ],
            }
            for group in groups
        ]

    def _placeholder_module(
        self, *, key: str, title: str, eyebrow: str, headline: str, body: str
    ) -> dict[str, Any]:
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
        metadata = (
            payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        )
        return {
            "messageId": str(payload.get("message_id", "")),
            "role": role,
            "speaker": "You" if role == "user" else "Stormhelm",
            "content": content,
            "microResponse": str(metadata.get("micro_response", "")).strip(),
            "fullResponse": str(metadata.get("full_response", content)).strip()
            or content,
            "bearingTitle": str(metadata.get("bearing_title", "")).strip(),
            "nextSuggestion": dict(metadata.get("next_suggestion") or {})
            if isinstance(metadata.get("next_suggestion"), dict)
            else {},
            "metadata": dict(metadata),
            "createdAt": created_at,
            "shortTime": self._short_time(created_at),
        }

    def _build_pending_chat_echo(self, text: str) -> dict[str, Any]:
        created_at = datetime.now().astimezone().isoformat()
        return {
            "messageId": f"pending-user-{uuid4()}",
            "role": "user",
            "speaker": "You",
            "content": text,
            "microResponse": "",
            "fullResponse": text,
            "bearingTitle": "",
            "metadata": {"pending_local_echo": True},
            "createdAt": created_at,
            "shortTime": self._short_time(created_at),
        }

    def _display_history(self) -> list[dict[str, Any]]:
        display = list(self._history)
        if (
            self._pending_chat_echo is not None
            and not self._pending_chat_echo_acknowledged(display)
        ):
            display.append(dict(self._pending_chat_echo))
        return display

    def _pending_chat_suffix(
        self, history: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        anchor_id = str(self._pending_chat_anchor_message_id or "").strip()
        if not anchor_id:
            return list(history)
        for index, message in enumerate(history):
            if str(message.get("messageId", "")).strip() == anchor_id:
                return history[index + 1 :]
        return list(history)

    def _pending_chat_echo_acknowledged(self, history: list[dict[str, Any]]) -> bool:
        if self._pending_chat_echo is None:
            return False
        target = str(self._pending_chat_echo.get("content", "")).strip()
        if not target:
            return False
        for message in self._pending_chat_suffix(history):
            if str(message.get("role", "")).strip().lower() != "user":
                continue
            if str(message.get("content", "")).strip() == target:
                return True
        return False

    def _pending_chat_response_message(
        self, history: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if self._pending_chat_echo is None:
            return None
        target = str(self._pending_chat_echo.get("content", "")).strip()
        if not target:
            return None
        suffix = self._pending_chat_suffix(history)
        acknowledged_index: int | None = None
        for index, message in enumerate(suffix):
            if str(message.get("role", "")).strip().lower() != "user":
                continue
            if str(message.get("content", "")).strip() == target:
                acknowledged_index = index
                break
        if acknowledged_index is None:
            return None
        for message in suffix[acknowledged_index + 1 :]:
            if str(message.get("role", "")).strip().lower() == "assistant":
                return message
        return None

    def _merge_history_messages(self, additions: list[dict[str, Any]]) -> None:
        merged = list(self._history)
        index_by_id = {
            str(message.get("messageId", "")).strip(): index
            for index, message in enumerate(merged)
            if str(message.get("messageId", "")).strip()
        }
        for addition in additions:
            message_id = str(addition.get("messageId", "")).strip()
            if message_id and message_id in index_by_id:
                merged[index_by_id[message_id]] = addition
                continue
            merged.append(addition)
            if message_id:
                index_by_id[message_id] = len(merged) - 1
        self._history = merged

    def _latest_assistant_message(self) -> dict[str, Any] | None:
        for message in reversed(self._display_history()):
            if str(message.get("role", "")).strip().lower() == "assistant":
                return message
        return None

    def _message_micro(self, message: dict[str, Any]) -> str:
        micro = str(message.get("microResponse", "")).strip()
        if micro:
            return micro
        content = " ".join(str(message.get("content", "")).split()).strip()
        if not content:
            return "Standing watch."
        stop = len(content)
        for marker in (". ", "! ", "? "):
            index = content.find(marker)
            if index != -1:
                stop = min(stop, index + 1)
        return content[:stop].strip() or content

    def _message_bearing_title(self, message: dict[str, Any]) -> str:
        title = str(message.get("bearingTitle", "")).strip()
        if title:
            return title
        return "Bearing"

    def _ghost_message_variant(self, message: dict[str, Any]) -> dict[str, Any]:
        variant = dict(message)
        if str(variant.get("role", "")).strip().lower() == "assistant":
            variant["content"] = self._message_micro(message)
        return variant

    def _module_label(self, name: str) -> str:
        labels = {
            "echo": "Echo",
            "clock": "Chronometer",
            "system_info": "Systems",
            "network_diagnosis": "Network",
            "file_reader": "Files",
            "notes_write": "Logbook",
            "shell_command": "Command Gate",
        }
        return labels.get(name, name.replace("_", " ").title())

    def _job_severity(self, status: str) -> str:
        normalized = str(status or "").strip().lower()
        if normalized in {"failed", "timed_out"}:
            return "warning"
        if normalized in {"cancelled"}:
            return "attention"
        return "steady"

    def _event_severity(self, event: dict[str, Any]) -> str:
        explicit = str(event.get("severity", "")).strip().lower()
        if explicit in {"warning", "attention", "steady"}:
            return explicit
        if explicit in {"error", "critical"}:
            return "warning"
        payload = event.get("payload", {})
        if isinstance(payload, dict):
            severity = str(payload.get("severity", "")).strip().lower()
            if severity in {"warning", "attention", "steady"}:
                return severity
        level = str(event.get("level", "INFO")).strip().upper()
        if level in {"ERROR", "WARNING"}:
            return "warning"
        return "steady"

    def _job_summary(self, job: dict[str, Any]) -> str:
        return self._job_detail(job)

    def _job_detail(self, job: dict[str, Any]) -> str:
        status = str(job.get("status", "")).strip().lower()
        summary = ""
        result = job.get("result")
        if isinstance(result, dict) and result.get("summary"):
            summary = str(result["summary"]).strip()
        workflow = {}
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict) and isinstance(data.get("workflow"), dict):
                workflow = dict(data.get("workflow") or {})
        error = str(job.get("error", "")).strip()
        duration = self._job_duration_label(job)
        if status == "running":
            current_step = (
                int(workflow.get("current_step_index", -1)) + 1 if workflow else 0
            )
            total_steps = int(workflow.get("total_steps", 0)) if workflow else 0
            steps = (
                workflow.get("steps") if isinstance(workflow.get("steps"), list) else []
            )
            item_progress = (
                workflow.get("item_progress")
                if isinstance(workflow.get("item_progress"), dict)
                else {}
            )
            if total_steps <= 0 and steps:
                total_steps = len(steps)
            if current_step > 0 and total_steps > 0:
                title = ""
                if 0 < current_step <= len(steps) and isinstance(
                    steps[current_step - 1], dict
                ):
                    title = str(steps[current_step - 1].get("title", "")).strip()
                processed = int(item_progress.get("processed", 0) or 0)
                total_items = int(item_progress.get("total", 0) or 0)
                skipped = int(item_progress.get("skipped", 0) or 0)
                if total_items > 0:
                    item_label = f"{processed} of {total_items} items"
                    if skipped > 0:
                        item_label = f"{item_label}; {skipped} skipped"
                    if title:
                        return f"Running step {current_step} of {total_steps}: {title} ({item_label})."
                    return (
                        f"Running step {current_step} of {total_steps} ({item_label})."
                    )
                if title:
                    return f"Running step {current_step} of {total_steps}: {title}."
                return f"Running step {current_step} of {total_steps}."
            return f"Running now for {duration}." if duration else "Running now."
        if status == "queued":
            return (
                f"Queued for {duration} while Stormhelm waits on a worker."
                if duration
                else "Queued for dispatch."
            )
        if status == "completed":
            if summary and duration:
                return f"Completed in {duration}: {summary}"
            if summary:
                return f"Completed cleanly: {summary}"
            return f"Completed in {duration}." if duration else "Completed cleanly."
        if status in {"failed", "timed_out", "cancelled"}:
            label = {
                "failed": "Failed",
                "timed_out": "Timed out",
                "cancelled": "Cancelled",
            }.get(status, status.replace("_", " ").title())
            if error and duration:
                return f"{label} after {duration}: {error}"
            if error:
                return f"{label}: {error}"
            return f"{label} after {duration}." if duration else f"{label}."
        return summary or error or str(job.get("created_at", "Awaiting output."))

    def _job_duration_label(self, job: dict[str, Any]) -> str:
        status = str(job.get("status", "")).strip().lower()
        created_at = self._parse_time(str(job.get("created_at", "")))
        started_at = self._parse_time(str(job.get("started_at", "")))
        finished_at = self._parse_time(str(job.get("finished_at", "")))
        seconds: int | None = None
        if finished_at is not None and created_at is not None:
            seconds = max(0, int((finished_at - created_at).total_seconds()))
        elif status == "running" and started_at is not None and created_at is not None:
            seconds = max(0, int((started_at - created_at).total_seconds()))
        elif status == "queued" and created_at is not None:
            seconds = 0
        if seconds is None:
            return ""
        if seconds >= 3600:
            hours, remainder = divmod(seconds, 3600)
            minutes = remainder // 60
            return f"{hours}h {minutes}m"
        if seconds >= 60:
            minutes, remainder = divmod(seconds, 60)
            return f"{minutes}m {remainder}s"
        return f"{seconds}s"

    def _event_detail(self, event: dict[str, Any]) -> str:
        level = str(event.get("level", event.get("severity", "INFO"))).strip().upper()
        source = (
            str(event.get("subsystem", event.get("source", "core"))).strip().lower()
        )
        message = str(event.get("message", "")).strip().lower()
        payload = event.get("payload", {})
        if isinstance(payload, dict):
            detail = str(payload.get("detail", "")).strip()
            if detail:
                return detail
            title = str(payload.get("title", "")).strip()
            if title:
                return title
        if source == "core" and "started" in message:
            return "Core came online cleanly."
        if source == "network":
            if "packet-loss" in message:
                return "Network loss was detected in recent probes."
            if "latency spike" in message:
                return "Recent network latency climbed sharply."
            if "reconnect" in message or "restored" in message:
                return "The connection recovered after a recent interruption."
            if "timeout" in message or "stalled" in message:
                return "Network reachability dropped long enough to matter."
        if level == "WARNING":
            return f"{source.title()} signal needs attention."
        if level == "ERROR":
            return f"{source.title()} reported a failure."
        return f"{source.title()} reported a steady operational update."

    def _recent_events(self, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        return [
            dict(event) for event in self._events[-limit:] if isinstance(event, dict)
        ]

    def _recent_events_newest_first(self, limit: int) -> list[dict[str, Any]]:
        return list(reversed(self._recent_events(limit)))

    def _latest_surface_event(self) -> dict[str, Any] | None:
        for event in reversed(self._events):
            if not isinstance(event, dict):
                continue
            visibility = str(event.get("visibility_scope", "")).strip().lower()
            severity = (
                str(event.get("severity", event.get("level", ""))).strip().lower()
            )
            if visibility != "internal_only" or severity in {
                "warning",
                "error",
                "critical",
            }:
                return dict(event)
        return dict(self._events[-1]) if self._events else None

    def _event_stream_visibility_detail(self, event_stream: dict[str, Any]) -> str:
        totals = event_stream.get("visibility_totals")
        if not isinstance(totals, dict) or not totals:
            return "No visibility buckets retained yet."
        ordered = sorted(
            (
                (str(key).replace("_", " ").title(), int(value))
                for key, value in totals.items()
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        return ", ".join(f"{label} {count}" for label, count in ordered[:3])

    def _parse_time(self, value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _set_assistant_state(self, state: str) -> None:
        normalized = (state or "").strip().lower()
        if normalized not in VOICE_STATES or normalized == self._assistant_state:
            return
        self._assistant_state = normalized
        self.assistantStateChanged.emit()

    def _set_ghost_reveal_target(self, value: float) -> None:
        normalized = 1.0 if value >= 1.0 else 0.0 if value <= 0.0 else float(value)
        if normalized == self._ghost_reveal_target:
            return
        self._ghost_reveal_target = normalized
        self.visibilityChanged.emit()

    def _finalize_ghost_hide(self) -> None:
        if self._window is None:
            return
        if self._mode == "ghost" and self._ghost_reveal_target <= 0.0:
            self._window.hide()

    def _refresh_clock(self) -> None:
        self._local_time_label = self._format_time()
        self.statusChanged.emit()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def _sync_ghost_adaptive_monitoring(self) -> None:
        enabled = self._mode == "ghost" and self._ghost_reveal_target > 0.0
        self._ghost_adaptive_manager.set_enabled(enabled)

    def _set_deck_panel_flag(self, panel_id: str, key: str, value: bool) -> None:
        normalized = str(panel_id or "").strip()
        if not normalized:
            return
        layout = self._ensure_layout_scope_state()
        panel_state = layout.setdefault("panels", {}).setdefault(normalized, {})
        panel_state[key] = bool(value)
        self._persist_deck_layout_store()
        self._rebuild_surface_models()
        self.collectionsChanged.emit()

    def _load_deck_layout_store(self) -> dict[str, Any]:
        try:
            if self._deck_layout_store_path.exists():
                payload = json.loads(
                    self._deck_layout_store_path.read_text(encoding="utf-8")
                )
                if isinstance(payload, dict):
                    payload.setdefault("layouts", {})
                    payload.setdefault("saved_layouts", {})
                    return payload
        except Exception:
            pass
        return {"layouts": {}, "saved_layouts": {}}

    def _persist_deck_layout_store(self) -> None:
        try:
            self._deck_layout_store_path.parent.mkdir(parents=True, exist_ok=True)
            self._deck_layout_store_path.write_text(
                json.dumps(self._deck_layout_store, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception:
            return

    def _format_time(self) -> str:
        return datetime.now().strftime("%H:%M")

    def _short_time(self, value: str) -> str:
        if not value:
            return ""
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(
                "%H:%M"
            )
        except ValueError:
            return value
