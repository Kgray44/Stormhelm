from __future__ import annotations

import os
from pathlib import Path

from PySide6 import QtCore, QtQml, QtTest, QtWidgets
from PySide6.QtQuickControls2 import QQuickStyle

from stormhelm.config.loader import load_config
from stormhelm.ui.app import resolve_main_qml_path
from stormhelm.ui.bridge import UiBridge


def _ensure_app() -> QtWidgets.QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_main_qml_exposes_shared_atmospheric_layers() -> None:
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
    QtTest.QTest.qWait(520)
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
    deck_shell = root.findChild(QtCore.QObject, "deckShell")
    assert deck_shell is not None
    assert bridge.workspaceCanvas["activeItem"]["viewer"] == "browser"
