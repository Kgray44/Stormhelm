from __future__ import annotations

import gc
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PySide6 import QtCore, QtGui, QtQml, QtTest, QtWidgets
from PySide6.QtQuickControls2 import QQuickStyle
import shiboken6

from stormhelm.config.loader import load_config
from stormhelm.ui.app import resolve_main_qml_path
from stormhelm.ui.bridge import UiBridge


def _ensure_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@contextmanager
def _capture_qt_messages() -> Iterator[list[str]]:
    messages: list[str] = []

    def handler(
        mode: QtCore.QtMsgType,
        context: QtCore.QMessageLogContext,
        message: str,
    ) -> None:
        del mode, context
        messages.append(str(message))

    previous_handler = QtCore.qInstallMessageHandler(handler)
    try:
        yield messages
    finally:
        QtCore.qInstallMessageHandler(previous_handler)


def _drain_qt_cleanup(app: QtWidgets.QApplication, *, wait_ms: int = 0) -> None:
    app.processEvents()
    if wait_ms > 0:
        QtTest.QTest.qWait(wait_ms)
        app.processEvents()
    app.processEvents()


def _dispose_qt_objects(app: QtWidgets.QApplication, *objects: QtCore.QObject | QtGui.QWindow | None) -> None:
    def key_for(obj: QtCore.QObject | QtGui.QWindow) -> int:
        try:
            return int(shiboken6.getCppPointer(obj)[0])
        except Exception:
            return id(obj)

    seen: set[int] = set()
    engines: list[QtQml.QQmlEngine] = []
    windows: list[QtGui.QWindow] = []
    others: list[QtCore.QObject] = []
    engine_root_keys: set[int] = set()

    for obj in objects:
        if obj is None or not shiboken6.isValid(obj):
            continue
        object_key = key_for(obj)
        if object_key in seen:
            continue
        seen.add(object_key)
        if isinstance(obj, QtQml.QQmlEngine):
            engines.append(obj)
        elif isinstance(obj, QtGui.QWindow):
            windows.append(obj)
        else:
            others.append(obj)

    for engine in engines:
        if not shiboken6.isValid(engine):
            continue
        root_objects_getter = getattr(engine, "rootObjects", None)
        if not callable(root_objects_getter):
            continue
        for root_object in root_objects_getter():
            if root_object is None or not shiboken6.isValid(root_object):
                continue
            engine_root_keys.add(key_for(root_object))

    for window in list(app.topLevelWindows()):
        if not shiboken6.isValid(window):
            continue
        object_key = key_for(window)
        if object_key in seen:
            continue
        seen.add(object_key)
        windows.append(window)

    for engine in engines:
        try:
            engine.rootContext().setContextProperty("stormhelmBridge", None)
            engine.rootContext().setContextProperty("stormhelmGhostInput", None)
        except Exception:
            pass
        try:
            engine.collectGarbage()
            engine.clearComponentCache()
        except Exception:
            pass

    for window in windows:
        if shiboken6.isValid(window):
            window.close()

    _drain_qt_cleanup(app, wait_ms=10)

    delete_later_queue: list[QtCore.QObject] = []
    delete_later_queue.extend(others)
    delete_later_queue.extend(window for window in windows if key_for(window) not in engine_root_keys)
    delete_later_queue.extend(engines)

    for obj in delete_later_queue:
        if shiboken6.isValid(obj):
            obj.deleteLater()

    _drain_qt_cleanup(app, wait_ms=20)
    gc.collect()
    _drain_qt_cleanup(app, wait_ms=20)


def _load_main_qml_scene() -> tuple[
    QtWidgets.QApplication,
    object,
    UiBridge,
    QtQml.QQmlApplicationEngine,
    QtCore.QObject,
]:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    bridge = UiBridge(workspace_config)
    engine = QtQml.QQmlApplicationEngine()
    engine.rootContext().setContextProperty("stormhelmBridge", bridge)
    engine.rootContext().setContextProperty("stormhelmGhostInput", None)

    qml_path = resolve_main_qml_path(workspace_config)
    engine.load(QtCore.QUrl.fromLocalFile(str(qml_path)))

    assert engine.rootObjects()
    return app, workspace_config, bridge, engine, engine.rootObjects()[0]


def test_main_qml_exposes_shared_atmospheric_layers() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene()
    try:
        background = root.findChild(QtCore.QObject, "stormBackground")
        sea_fog = root.findChild(QtCore.QObject, "stormSeaFogField")
        deck_glass = root.findChild(QtCore.QObject, "stormDeckGlassField")
        fog_far = root.findChild(QtCore.QObject, "stormSeaFogFar")
        fog_mid = root.findChild(QtCore.QObject, "stormSeaFogMid")
        fog_near = root.findChild(QtCore.QObject, "stormSeaFogNear")
        old_anchor_mist = root.findChild(QtCore.QObject, "stormAnchorMist")
        old_background_mist = root.findChild(QtCore.QObject, "stormMistField")
        old_glass = root.findChild(QtCore.QObject, "stormGlassField")
        foreground_mist = root.findChild(QtCore.QObject, "stormForegroundMist")
        assert background is not None
        assert sea_fog is not None
        assert deck_glass is not None
        assert sea_fog.property("fogRenderer") == "particle-shader"
        assert fog_far is not None
        assert fog_mid is not None
        assert fog_near is not None
        assert old_anchor_mist is None
        assert old_background_mist is None
        assert old_glass is None
        assert foreground_mist is not None
        assert sea_fog.property("rendererType") == "shader"
        ghost_density = float(sea_fog.property("densityScale"))
        ghost_phase = float(sea_fog.property("phase"))
        ghost_base_tint = float(sea_fog.property("baseTintOpacity"))
        ghost_top_veil = float(sea_fog.property("topVeilOpacity"))
        ghost_glass_strength = float(deck_glass.property("materialStrength"))
        ghost_far_opacity = float(fog_far.property("layerOpacity"))
        ghost_mid_opacity = float(fog_mid.property("layerOpacity"))
        ghost_near_opacity = float(fog_near.property("layerOpacity"))
        ghost_foreground = float(foreground_mist.property("mistStrength"))
        initial_foreground_phase = float(foreground_mist.property("phase"))
        assert 0.50 <= ghost_density < 0.9
        assert ghost_base_tint < 0.02
        assert ghost_top_veil < 0.02
        assert ghost_far_opacity < ghost_mid_opacity
        assert ghost_near_opacity <= ghost_mid_opacity
        assert ghost_foreground == 0.0
        assert ghost_glass_strength == 0.0
        assert float(background.property("topVeilStrength")) < 0.03
        assert float(foreground_mist.property("z")) < 12.0
        QtTest.QTest.qWait(180)
        app.processEvents()
        assert float(sea_fog.property("phase")) != ghost_phase
        assert float(foreground_mist.property("phase")) != initial_foreground_phase

        bridge.setMode("deck")
        app.processEvents()
        QtTest.QTest.qWait(900)
        app.processEvents()

        assert float(sea_fog.property("deckProgress")) > 0.95
        assert float(sea_fog.property("densityScale")) > ghost_density
        assert float(sea_fog.property("baseTintOpacity")) > ghost_base_tint
        assert float(sea_fog.property("topVeilOpacity")) > ghost_top_veil
        assert float(deck_glass.property("materialStrength")) > ghost_glass_strength
        assert float(fog_far.property("layerOpacity")) > ghost_far_opacity
        assert float(fog_mid.property("layerOpacity")) > ghost_mid_opacity
        assert float(fog_near.property("layerOpacity")) > ghost_near_opacity
        assert float(foreground_mist.property("mistStrength")) > ghost_foreground
        assert float(foreground_mist.property("mistStrength")) < 0.02
        assert float(background.property("topVeilStrength")) < 0.05
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


def test_main_qml_load_does_not_emit_deck_panel_workspace_reference_errors() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    bridge = UiBridge(workspace_config)
    engine = QtQml.QQmlApplicationEngine()
    engine.rootContext().setContextProperty("stormhelmBridge", bridge)
    engine.rootContext().setContextProperty("stormhelmGhostInput", None)
    root = None
    try:
        qml_path = resolve_main_qml_path(workspace_config)
        with _capture_qt_messages() as messages:
            engine.load(QtCore.QUrl.fromLocalFile(str(qml_path)))
            app.processEvents()
            QtTest.QTest.qWait(60)
            app.processEvents()

        assert engine.rootObjects()
        reference_errors = [
            message
            for message in messages
            if "DeckPanelWorkspace.qml" in message and "ReferenceError: index is not defined" in message
        ]
        assert reference_errors == []
        root = engine.rootObjects()[0]
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


def test_message_bubble_handles_messages_without_next_suggestion() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    engine.rootContext().setContextProperty(
        "messageData",
        {
            "role": "assistant",
            "speaker": "Stormhelm",
            "shortTime": "",
            "content": "Holding the line.",
        },
    )
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "components"

Item {
    width: 420
    height: 180

    MessageBubble {
        anchors.fill: parent
        message: messageData
    }
}
""".strip()

    root = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(str(workspace_config.runtime.assets_dir / "qml" / "MessageBubbleHarness.qml")),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(20)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        type_errors = [
            message
            for message in messages
            if "MessageBubble.qml:79: TypeError" in message
        ]
        assert type_errors == []
    finally:
        _dispose_qt_objects(app, root, engine)


def test_main_qml_supports_workspace_opened_items_surfaces() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    bridge = UiBridge(workspace_config)
    bridge.apply_action(
        {
            "type": "workspace_open",
            "module": "browser",
            "section": "open-pages",
            "item": {
                "itemId": "page-1",
                "kind": "browser",
                "viewer": "browser",
                "title": "OpenAI Docs",
                "url": "https://platform.openai.com/docs",
            },
        }
    )
    engine = QtQml.QQmlApplicationEngine()
    engine.rootContext().setContextProperty("stormhelmBridge", bridge)
    engine.rootContext().setContextProperty("stormhelmGhostInput", None)

    qml_path = resolve_main_qml_path(workspace_config)
    engine.load(QtCore.QUrl.fromLocalFile(str(qml_path)))

    assert engine.rootObjects()
    root = engine.rootObjects()[0]
    try:
        deck_shell = root.findChild(QtCore.QObject, "deckShell")
        panel_workspace = root.findChild(QtCore.QObject, "deckPanelWorkspace")
        hidden_rail = root.findChild(QtCore.QObject, "deckHiddenRail")
        assert deck_shell is not None
        assert panel_workspace is not None
        assert hidden_rail is not None
        assert bridge.workspaceCanvas["activeItem"]["viewer"] == "browser"
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


def test_main_qml_binds_ghost_adaptive_style_and_positioning() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene()
    try:
        ghost_shell = root.findChild(QtCore.QObject, "ghostShell")
        voice_core = root.findChild(QtCore.QObject, "ghostVoiceCore")
        field_strip = root.findChild(QtCore.QObject, "ghostFieldStrip")

        assert ghost_shell is not None
        assert voice_core is not None
        assert field_strip is not None
        assert float(ghost_shell.property("adaptiveTone")) == 0.0

        bridge.updateGhostAdaptiveState(
            {
                "tone": 0.22,
                "surfaceOpacity": 0.83,
                "edgeOpacity": 0.31,
                "lineOpacity": 0.1,
                "textContrast": 0.18,
                "secondaryTextContrast": 0.12,
                "glowBoost": 0.14,
                "anchorGlowBoost": 0.24,
                "anchorStrokeBoost": 0.32,
                "anchorFillBoost": 0.17,
                "anchorBackdropOpacity": 0.18,
                "shadowOpacity": 0.18,
                "backdropOpacity": 0.16,
                "backgroundState": "bright",
            },
            {
                "anchorKey": "right",
                "state": "repositioning",
                "offsetX": 88.0,
                "offsetY": -22.0,
                "currentScore": 0.34,
                "bestScore": 0.63,
            },
            {
                "supported": True,
                "backgroundState": "bright",
                "brightness": 0.82,
                "motion": 0.15,
                "edgeDensity": 0.28,
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(20)
        app.processEvents()

        assert float(ghost_shell.property("adaptiveTone")) == 0.22
        assert float(ghost_shell.property("contentOffsetX")) == 88.0
        assert float(voice_core.property("adaptiveGlowBoost")) == 0.14
        assert float(voice_core.property("adaptiveAnchorStrokeBoost")) == 0.32
        assert float(voice_core.property("adaptiveAnchorFillBoost")) == 0.17
        assert float(voice_core.property("adaptiveAnchorBackdropOpacity")) == 0.18
        assert float(field_strip.property("adaptiveSurfaceOpacity")) == 0.83
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


def test_main_qml_exposes_deck_panel_launcher_and_layout_presets() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    bridge = UiBridge(workspace_config)
    bridge.setMode("deck")
    engine = QtQml.QQmlApplicationEngine()
    engine.rootContext().setContextProperty("stormhelmBridge", bridge)
    engine.rootContext().setContextProperty("stormhelmGhostInput", None)

    qml_path = resolve_main_qml_path(workspace_config)
    engine.load(QtCore.QUrl.fromLocalFile(str(qml_path)))

    assert engine.rootObjects()
    root = engine.rootObjects()[0]
    try:
        launcher = root.findChild(QtCore.QObject, "deckPanelLauncher")
        preset_row = root.findChild(QtCore.QObject, "deckLayoutPresetRow")

        assert launcher is not None
        assert preset_row is not None
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


def test_main_qml_surfaces_command_card_and_route_inspector() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene()
    try:
        bridge.apply_snapshot(
            {
                "history": [
                    {
                        "message_id": "assistant-route-1",
                        "role": "assistant",
                        "content": "Relay preview is ready for Baby once you approve it.",
                        "created_at": "2026-04-23T12:00:00Z",
                        "metadata": {
                            "bearing_title": "Relay Preview",
                            "micro_response": "Relay preview ready for Baby.",
                            "route_state": {
                                "winner": {
                                    "route_family": "discord_relay",
                                    "query_shape": "discord_relay_request",
                                    "posture": "clear_winner",
                                    "status": "preview_ready",
                                    "clarification_needed": False,
                                },
                                "deictic_binding": {
                                    "resolved": True,
                                    "selected_source": "selection",
                                    "selected_target": {
                                        "source": "selection",
                                        "target_type": "text",
                                        "label": "Selected launch notes",
                                        "freshness": "current",
                                    },
                                },
                            },
                        },
                    }
                ],
                "active_request_state": {
                    "family": "discord_relay",
                    "subject": "Baby",
                    "request_type": "discord_relay_dispatch",
                    "query_shape": "discord_relay_request",
                    "route": {"tool_name": "", "response_mode": "action_result", "route_mode": "local_client_automation"},
                    "parameters": {
                        "destination_alias": "Baby",
                        "payload_hint": "selected_text",
                        "request_stage": "preview",
                    },
                    "trust": {
                        "decision": "confirmation_required",
                        "approval_state": "pending_operator_confirmation",
                        "available_scopes": ["once", "session"],
                    },
                },
            }
        )
        app.processEvents()
        QtTest.QTest.qWait(60)
        app.processEvents()

        ghost_shell = root.findChild(QtCore.QObject, "ghostShell")
        ghost_card = root.findChild(QtCore.QObject, "ghostPrimaryCommandCard")
        ghost_actions = root.findChild(QtCore.QObject, "ghostActionStrip")

        assert ghost_shell is not None
        assert ghost_card is not None
        assert ghost_actions is not None
        assert ghost_shell.property("primaryCard")["title"] == "Relay Preview"

        bridge.setMode("deck")
        app.processEvents()
        QtTest.QTest.qWait(60)
        app.processEvents()

        panel_workspace = root.findChild(QtCore.QObject, "deckPanelWorkspace")
        assert panel_workspace is not None
        panel_ids = {
            str(panel["panelId"])
            for panel in panel_workspace.property("panels")
        }
        assert "route-inspector" in panel_ids
        assert "relay-station" in panel_ids
        assert "trust-station" in panel_ids
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


def test_qml_scene_disposal_releases_window_and_qt_objects() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    bridge = UiBridge(workspace_config)
    engine = QtQml.QQmlApplicationEngine()
    engine.rootContext().setContextProperty("stormhelmBridge", bridge)
    engine.rootContext().setContextProperty("stormhelmGhostInput", None)

    qml_path = resolve_main_qml_path(workspace_config)
    engine.load(QtCore.QUrl.fromLocalFile(str(qml_path)))

    assert engine.rootObjects()
    root = engine.rootObjects()[0]

    _dispose_qt_objects(app, root, engine, bridge)

    assert not shiboken6.isValid(root)
    assert not shiboken6.isValid(engine)
    assert not shiboken6.isValid(bridge)
    assert app.topLevelWindows() == []


def test_main_qml_repeated_scene_load_and_dispose_keeps_command_station_surfaces_stable() -> None:
    app = _ensure_app()
    for _ in range(3):
        _, _, bridge, engine, root = _load_main_qml_scene()
        try:
            bridge.apply_snapshot(
                {
                    "history": [
                        {
                            "message_id": "assistant-recovery-loop",
                            "role": "assistant",
                            "content": "Firefox recovery remains live.",
                            "created_at": "2026-04-23T12:40:00Z",
                            "metadata": {
                                "bearing_title": "Software Recovery",
                                "micro_response": "Firefox recovery is still live.",
                                "next_suggestion": {
                                    "title": "Retry Recovery",
                                    "command": "retry the firefox recovery",
                                },
                                "route_state": {
                                    "winner": {
                                        "route_family": "software_control",
                                        "query_shape": "software_control_request",
                                        "posture": "conditional_winner",
                                        "status": "recovery_ready",
                                        "clarification_needed": False,
                                    },
                                    "deictic_binding": {
                                        "resolved": True,
                                        "selected_source": "active_preview",
                                        "selected_target": {
                                            "source": "active_preview",
                                            "target_type": "software_target",
                                            "label": "Firefox",
                                            "freshness": "current",
                                        },
                                    },
                                },
                            },
                        }
                    ],
                    "status": {
                        "watch_state": {
                            "active_jobs": 1,
                            "queued_jobs": 1,
                            "recent_failures": 1,
                            "health": "degraded",
                        }
                    },
                    "active_task": {
                        "taskId": "task-loop",
                        "title": "Repair Firefox install",
                        "state": "paused",
                        "continuity": {
                            "posture": "resumable",
                            "freshness": "current",
                            "active_step": "Recover package state",
                            "next_step": "Retry the recovery flow.",
                            "resumable": True,
                        },
                    },
                    "active_request_state": {
                        "family": "software_control",
                        "subject": "firefox",
                        "query_shape": "software_control_request",
                        "parameters": {
                            "operation_type": "install",
                            "target_name": "firefox",
                            "request_stage": "recovery_ready",
                        },
                    },
                }
            )
            bridge.setMode("deck")
            app.processEvents()
            QtTest.QTest.qWait(40)
            app.processEvents()

            panel_workspace = root.findChild(QtCore.QObject, "deckPanelWorkspace")
            assert panel_workspace is not None
            panel_ids = {
                str(panel["panelId"])
                for panel in panel_workspace.property("panels")
            }
            assert "software-recovery-station" in panel_ids
            assert "runtime-station" in panel_ids
            assert "continuity-station" in panel_ids
        finally:
            _dispose_qt_objects(app, root, engine, bridge)
        assert app.topLevelWindows() == []
