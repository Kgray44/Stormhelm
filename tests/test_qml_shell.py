from __future__ import annotations

import gc
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PySide6 import QtCore, QtGui, QtQml, QtTest, QtWidgets
from PySide6.QtQuickControls2 import QQuickStyle
import pytest
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


def _load_main_qml_scene(
    env: dict[str, str] | None = None,
) -> tuple[
    QtWidgets.QApplication,
    object,
    UiBridge,
    QtQml.QQmlApplicationEngine,
    QtCore.QObject,
]:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env=env or {})
    bridge = UiBridge(workspace_config)
    engine = QtQml.QQmlApplicationEngine()
    engine.rootContext().setContextProperty("stormhelmBridge", bridge)
    engine.rootContext().setContextProperty("stormhelmGhostInput", None)

    qml_path = resolve_main_qml_path(workspace_config)
    engine.load(QtCore.QUrl.fromLocalFile(str(qml_path)))

    assert engine.rootObjects()
    return app, workspace_config, bridge, engine, engine.rootObjects()[0]


def test_main_qml_loads_classic_variant_surfaces_by_default() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene()
    try:
        assert bridge.uiVisualVariant == "classic"
        assert root.findChild(QtCore.QObject, "ghostShell") is not None
        assert root.findChild(QtCore.QObject, "deckShell") is not None
        assert root.findChild(QtCore.QObject, "classicGhostShell") is not None
        assert root.findChild(QtCore.QObject, "classicDeckShell") is not None
        assert root.findChild(QtCore.QObject, "stormforgeGhostShell") is None
        assert root.findChild(QtCore.QObject, "stormforgeDeckShell") is None
        assert root.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer") is None
    finally:
        _dispose_qt_objects(app, engine, root)


def test_main_qml_loads_stormforge_variant_surfaces_from_env() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene(
        {"STORMHELM_UI_VARIANT": "stormforge"}
    )
    try:
        assert bridge.uiVisualVariant == "stormforge"
        assert root.findChild(QtCore.QObject, "ghostShell") is not None
        assert root.findChild(QtCore.QObject, "deckShell") is not None
        assert root.findChild(QtCore.QObject, "stormforgeGhostShell") is not None
        assert root.findChild(QtCore.QObject, "stormforgeDeckShell") is not None
        assert root.findChild(QtCore.QObject, "classicGhostShell") is None
        assert root.findChild(QtCore.QObject, "classicDeckShell") is None
    finally:
        _dispose_qt_objects(app, engine, root)


def test_stormforge_foundation_components_construct_and_style_states() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

Item {
    width: 760
    height: 520

    StormforgeTokens {
        id: stormforgeTokens
        objectName: "stormforgeTokens"
    }

    StormforgeGlassPanel {
        objectName: "stormforgePanel"
        width: 320
        height: 96
        elevation: 2
    }

    StormforgeCard {
        objectName: "stormforgeCard"
        y: 110
        width: 320
        height: 96
        stateTone: "verified"
    }

    StormforgeStatusChip {
        objectName: "stormforgeStatusChip"
        y: 218
        label: "Signal steady"
        stateTone: "listening"
    }

    StormforgeResultBadge {
        objectName: "stormforgeResultBadge"
        y: 260
        label: "Blocked"
        resultState: "blocked"
    }

    StormforgeButton {
        objectName: "stormforgeButton"
        y: 304
        text: "Open"
        stateTone: "active"
    }

    StormforgeIconButton {
        objectName: "stormforgeIconButton"
        x: 110
        y: 304
        iconText: "?"
        accessibleName: "Help"
    }

    StormforgeSectionHeader {
        objectName: "stormforgeSectionHeader"
        x: 360
        title: "Watch"
        subtitle: "Runtime signal"
    }

    StormforgeEmptyState {
        objectName: "stormforgeEmptyState"
        x: 360
        y: 70
        title: "No signal"
        body: "Nothing is surfaced yet."
    }

    StormforgeLoadingState {
        objectName: "stormforgeLoadingState"
        x: 360
        y: 150
        label: "Reading"
    }

    StormforgeErrorState {
        objectName: "stormforgeErrorState"
        x: 360
        y: 220
        title: "Blocked"
        body: "Permission is required."
    }

    StormforgeDivider {
        objectName: "stormforgeDivider"
        y: 350
        width: 320
    }

    StormforgeRail {
        objectName: "stormforgeRail"
        x: 360
        y: 310
        width: 150
        height: 110
    }

    StormforgeListRow {
        objectName: "stormforgeListRow"
        x: 520
        y: 310
        width: 210
        title: "Route"
        subtitle: "Planner"
        stateTone: "running"
    }

    StormforgeMetricLabel {
        objectName: "stormforgeMetricLabel"
        x: 520
        y: 380
        label: "Latency"
        value: "42 ms"
    }

    StormforgeActionStrip {
        objectName: "stormforgeActionStrip"
        x: 360
        y: 440
        width: 360
        actions: [
            {"label": "Inspect", "state": "planned"},
            {"label": "Approve", "state": "approval_required"}
        ]
    }
}
""".strip()

    root = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeFoundationHarness.qml"
                    )
                ),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(40)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        import_errors = [message for message in messages if "Stormforge" in message]
        assert import_errors == []

        tokens = root.findChild(QtCore.QObject, "stormforgeTokens")
        panel = root.findChild(QtCore.QObject, "stormforgePanel")
        status_chip = root.findChild(QtCore.QObject, "stormforgeStatusChip")
        result_badge = root.findChild(QtCore.QObject, "stormforgeResultBadge")
        action_strip = root.findChild(QtCore.QObject, "stormforgeActionStrip")

        assert tokens is not None
        assert panel is not None
        assert status_chip is not None
        assert result_badge is not None
        assert action_strip is not None
        assert tokens.property("foundationVersion") == "UI-P1"
        assert int(tokens.property("space3")) > 0
        assert panel.property("surfaceRole") == "glass_panel"
        assert status_chip.property("resolvedTone") == "listening"
        assert result_badge.property("resolvedTone") == "blocked"
        assert int(action_strip.property("actionCount")) == 2
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_core_constructs_representative_states_truthfully() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

Item {
    width: 980
    height: 620

    Grid {
        columns: 4
        spacing: 16

        StormforgeAnchorCore {
            objectName: "idleAnchor"
            width: 180
            height: width
            state: ""
        }

        StormforgeAnchorCore {
            objectName: "readyAnchor"
            width: 180
            height: width
            state: "ready"
        }

        StormforgeAnchorCore {
            objectName: "unknownAnchor"
            width: 180
            height: width
            state: "future_backend_state_without_visual_contract"
            assistantState: ""
            voiceState: ({})
        }

        StormforgeAnchorCore {
            objectName: "listeningAnchor"
            width: 180
            height: width
            state: "listening"
            audioLevel: 0.42
            active: true
        }

        StormforgeAnchorCore {
            objectName: "transcribingAnchor"
            width: 180
            height: width
            state: "transcribing"
            audioLevel: 0.18
            active: true
        }

        StormforgeAnchorCore {
            objectName: "speakingAnchor"
            width: 180
            height: width
            voiceState: {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "playback_active",
                "speaking_visual_active": true,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 0.67,
                "voice_outer_speaking_motion": 0.48,
                "voice_audio_reactive_available": true,
                "voice_audio_reactive_source": "playback_output_envelope"
            }
        }

        StormforgeAnchorCore {
            objectName: "requestedPlaybackAnchor"
            width: 180
            height: width
            voiceState: {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "synthesizing",
                "speaking_visual_active": false,
                "active_playback_status": "requested"
            }
        }

        StormforgeAnchorCore {
            objectName: "thinkingAnchor"
            width: 180
            height: width
            state: "routing"
        }

        StormforgeAnchorCore {
            objectName: "actingAnchor"
            width: 180
            height: width
            state: "executing"
        }

        StormforgeAnchorCore {
            objectName: "approvalAnchor"
            width: 180
            height: width
            state: "approval_required"
            warning: true
        }

        StormforgeAnchorCore {
            objectName: "blockedAnchor"
            width: 180
            height: width
            state: "blocked"
        }

        StormforgeAnchorCore {
            objectName: "failedAnchor"
            width: 180
            height: width
            state: "failed"
        }

        StormforgeAnchorCore {
            objectName: "mockAnchor"
            width: 180
            height: width
            state: "mock_dev"
        }

        StormforgeAnchorCore {
            objectName: "unavailableAnchor"
            width: 180
            height: width
            state: "listening"
            disabled: true
        }
    }
}
""".strip()

    root = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeAnchorHarness.qml"
                    )
                ),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(80)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        assert [message for message in messages if "StormforgeAnchor" in message] == []

        idle = root.findChild(QtCore.QObject, "idleAnchor")
        ready = root.findChild(QtCore.QObject, "readyAnchor")
        unknown = root.findChild(QtCore.QObject, "unknownAnchor")
        listening = root.findChild(QtCore.QObject, "listeningAnchor")
        transcribing = root.findChild(QtCore.QObject, "transcribingAnchor")
        speaking = root.findChild(QtCore.QObject, "speakingAnchor")
        requested = root.findChild(QtCore.QObject, "requestedPlaybackAnchor")
        thinking = root.findChild(QtCore.QObject, "thinkingAnchor")
        acting = root.findChild(QtCore.QObject, "actingAnchor")
        approval = root.findChild(QtCore.QObject, "approvalAnchor")
        blocked = root.findChild(QtCore.QObject, "blockedAnchor")
        failed = root.findChild(QtCore.QObject, "failedAnchor")
        mock = root.findChild(QtCore.QObject, "mockAnchor")
        unavailable = root.findChild(QtCore.QObject, "unavailableAnchor")

        assert idle is not None
        assert ready is not None
        assert unknown is not None
        assert listening is not None
        assert transcribing is not None
        assert speaking is not None
        assert requested is not None
        assert thinking is not None
        assert acting is not None
        assert approval is not None
        assert blocked is not None
        assert failed is not None
        assert mock is not None
        assert unavailable is not None

        assert idle.property("resolvedState") == "idle"
        assert idle.property("normalizedState") == "idle"
        assert idle.property("visualState") == "idle"
        assert idle.property("resolvedLabel") == "Ready"
        assert idle.property("motionProfile") == "breathing"
        assert idle.property("visualTuningVersion") == "UI-P2A.5"
        assert idle.property("idlePresenceHotfixVersion") == "UI-P2A.4A"
        assert idle.property("stateStabilityVersion") == "UI-P2A.5"
        assert idle.property("signatureSilhouette") == "helm_crown_lens_aperture"
        assert idle.property("centerLensSignature") == "living_helm_lens"
        assert int(idle.property("bearingTickCount")) == 40
        assert float(idle.property("visualSoftness")) >= 0.45
        assert int(idle.property("presenceDepthLayerCount")) >= 6
        assert int(idle.property("nauticalDetailCount")) >= 7
        assert int(idle.property("signatureFeatureCount")) >= 4
        assert int(idle.property("centerLensLayerCount")) >= 6
        assert int(idle.property("centerApertureSegmentCount")) == 4
        assert 0.28 <= float(idle.property("centerLensRadiusRatio")) <= 0.40
        assert float(idle.property("instrumentGlassOpacity")) > 0.0
        assert float(idle.property("depthShadowOpacity")) > 0.0
        assert float(idle.property("centerApertureStrength")) > float(idle.property("instrumentGlassOpacity"))
        assert float(idle.property("centerPearlStrength")) > float(idle.property("centerApertureStrength"))
        assert float(idle.property("headingMarkerStrength")) > 0.0
        assert float(idle.property("outerClampStrength")) > 0.0
        assert float(idle.property("minimumRingOpacity")) >= 0.14
        assert float(idle.property("minimumCenterLensOpacity")) >= 0.14
        assert float(idle.property("minimumBearingTickOpacity")) >= 0.10
        assert float(idle.property("minimumSignalPointOpacity")) >= 0.16
        assert float(idle.property("minimumLabelOpacity")) >= 0.70
        assert float(idle.property("visualPresenceFloor")) >= 0.10
        assert float(idle.property("anchorVisibleFloor")) == pytest.approx(float(idle.property("visualPresenceFloor")))
        assert float(idle.property("lensVisibleFloor")) == pytest.approx(float(idle.property("minimumCenterLensOpacity")))
        assert float(idle.property("ringVisibleFloor")) == pytest.approx(float(idle.property("minimumRingOpacity")))
        assert bool(idle.property("idleMotionActive")) is True
        assert 0.0 <= float(idle.property("idleBreathValue")) <= 1.0
        assert float(idle.property("idlePulseMin")) > 0.0
        assert float(idle.property("idlePulseMax")) > float(idle.property("idlePulseMin"))
        assert int(idle.property("stateTransitionDurationMs")) >= 260
        assert int(idle.property("stateMinimumDwellMs")) >= 80
        assert idle.property("anchorVisibilityStatus") == "visible_idle_floor"
        assert idle.property("stateVisualSignature") == "powered_watch"
        assert idle.property("stateGeometrySignature") == "closed_watch_crown"
        assert idle.property("centerStateSignature") == "calm_helm_lens"
        assert float(idle.property("motionSpeedScale")) < float(listening.property("motionSpeedScale"))
        assert ready.property("resolvedState") == "ready"
        assert ready.property("normalizedState") == "ready"
        assert ready.property("visualState") == "ready"
        assert ready.property("anchorVisibilityStatus") == "visible_idle_floor"
        assert bool(ready.property("idleMotionActive")) is True
        assert float(ready.property("minimumRingOpacity")) >= float(idle.property("minimumRingOpacity"))
        assert float(ready.property("minimumCenterLensOpacity")) >= float(idle.property("minimumCenterLensOpacity"))
        assert float(ready.property("minimumBearingTickOpacity")) >= float(idle.property("minimumBearingTickOpacity"))
        assert float(ready.property("minimumSignalPointOpacity")) >= float(idle.property("minimumSignalPointOpacity"))
        assert unknown.property("resolvedState") == "idle"
        assert unknown.property("normalizedState") == "idle"
        assert unknown.property("visualState") == "idle"
        assert unknown.property("normalizedStateFallback") == "idle"
        assert unknown.property("anchorVisibilityStatus") == "visible_idle_floor"
        assert bool(unknown.property("idleMotionActive")) is True
        assert float(unknown.property("visualPresenceFloor")) >= 0.10
        assert listening.property("resolvedState") == "listening"
        assert listening.property("resolvedLabel") == "Listening"
        assert listening.property("motionProfile") == "listening_wave"
        assert listening.property("stateVisualSignature") == "receive_wave"
        assert listening.property("stateGeometrySignature") == "open_receive_aperture"
        assert listening.property("centerStateSignature") == "receptive_open_aperture"
        assert transcribing.property("resolvedState") == "transcribing"
        assert transcribing.property("motionProfile") == "listening_wave"
        assert transcribing.property("stateGeometrySignature") == "segmented_processing_aperture"
        assert transcribing.property("centerStateSignature") == "segmented_processing_lens"
        assert speaking.property("resolvedState") == "speaking"
        assert speaking.property("normalizedState") == "speaking"
        assert speaking.property("resolvedLabel") == "Speaking"
        assert speaking.property("motionProfile") == "radiating"
        assert speaking.property("stateVisualSignature") == "playback_radiance"
        assert speaking.property("stateGeometrySignature") == "response_aperture_radiance"
        assert speaking.property("centerStateSignature") == "radiant_voice_lens"
        assert speaking.property("audioReactiveSource") == "playback_output_envelope"
        assert float(speaking.property("effectiveSpeakingLevel")) == pytest.approx(0.67)
        assert requested.property("resolvedState") == "thinking"
        assert requested.property("normalizedState") == "thinking"
        assert requested.property("visualState") == "thinking"
        assert requested.property("resolvedLabel") == "Thinking"
        assert requested.property("motionProfile") == "orbit"
        assert requested.property("stateGeometrySignature") == "internal_orbit_aperture"
        assert requested.property("centerStateSignature") == "slow_internal_iris"
        assert thinking.property("resolvedState") == "thinking"
        assert thinking.property("motionProfile") == "orbit"
        assert thinking.property("stateVisualSignature") == "orbital_bearing"
        assert thinking.property("stateGeometrySignature") == "internal_orbit_aperture"
        assert thinking.property("centerStateSignature") == "slow_internal_iris"
        assert acting.property("resolvedState") == "acting"
        assert acting.property("motionProfile") == "directional_trace"
        assert acting.property("stateVisualSignature") == "bearing_trace"
        assert acting.property("stateGeometrySignature") == "directional_helm_trace"
        assert acting.property("centerStateSignature") == "bearing_directed_lens"
        assert approval.property("resolvedState") == "approval_required"
        assert approval.property("resolvedLabel") == "Approval required"
        assert approval.property("motionProfile") == "approval_halo"
        assert approval.property("stateVisualSignature") == "approval_bezel"
        assert approval.property("stateGeometrySignature") == "brass_clamp_bezel"
        assert approval.property("centerStateSignature") == "brass_locked_lens"
        assert blocked.property("resolvedState") == "blocked"
        assert blocked.property("stateVisualSignature") == "warning_bezel"
        assert blocked.property("stateGeometrySignature") == "amber_boundary_clamp"
        assert blocked.property("centerStateSignature") == "amber_bound_lens"
        assert failed.property("resolvedState") == "failed"
        assert failed.property("stateVisualSignature") == "failure_bezel"
        assert failed.property("stateGeometrySignature") == "diagnostic_break_segment"
        assert failed.property("centerStateSignature") == "fractured_diagnostic_lens"
        assert mock.property("resolvedState") == "mock_dev"
        assert mock.property("stateVisualSignature") == "development_trace"
        assert mock.property("stateGeometrySignature") == "synthetic_trace_aperture"
        assert mock.property("centerStateSignature") == "synthetic_violet_lens"
        assert unavailable.property("resolvedState") == "unavailable"
        assert unavailable.property("normalizedState") == "unavailable"
        assert unavailable.property("visualState") == "unavailable"
        assert unavailable.property("motionProfile") == "muted"
        assert unavailable.property("stateVisualSignature") == "offline_muted"
        assert unavailable.property("stateGeometrySignature") == "dimmed_lens"
        assert unavailable.property("centerStateSignature") == "nearly_dark_lens"
        assert unavailable.property("anchorVisibilityStatus") == "visible_unavailable_floor"
        assert bool(unavailable.property("idleMotionActive")) is False
        assert 0.04 <= float(unavailable.property("minimumRingOpacity")) < float(idle.property("minimumRingOpacity"))
        assert 0.04 <= float(unavailable.property("minimumCenterLensOpacity")) < float(idle.property("minimumCenterLensOpacity"))
        assert 0.03 <= float(unavailable.property("minimumBearingTickOpacity")) < float(idle.property("minimumBearingTickOpacity"))
        assert 0.04 <= float(unavailable.property("minimumSignalPointOpacity")) < float(idle.property("minimumSignalPointOpacity"))
        assert unavailable.property("animationRunning") is False
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_ghost_idle_anchor_keeps_presence_floor() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

Item {
    width: 960
    height: 680

    StormforgeGhostShell {
        objectName: "idleGhostShell"
        anchors.fill: parent
        stormforgeFogConfig: {"enabled": false}
        voiceState: ({})
        statusLine: "Standing watch."
    }
}
""".strip()

    root = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeGhostIdleAnchorHarness.qml"
                    )
                ),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(80)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        assert [message for message in messages if "Stormforge" in message] == []

        anchor_host = root.findChild(QtCore.QObject, "stormforgeAnchorHost")
        anchor_core = root.findChild(QtCore.QObject, "stormforgeAnchorCore")
        assert anchor_host is not None
        assert anchor_core is not None
        assert anchor_host.property("resolvedState") == "idle"
        assert anchor_core.property("resolvedState") == "idle"
        assert anchor_core.property("anchorVisibilityStatus") == "visible_idle_floor"
        assert float(anchor_core.property("minimumRingOpacity")) >= 0.14
        assert float(anchor_core.property("minimumCenterLensOpacity")) >= 0.14
        assert float(anchor_core.property("minimumBearingTickOpacity")) >= 0.10
        assert float(anchor_core.property("minimumSignalPointOpacity")) >= 0.16
        assert float(anchor_core.property("minimumLabelOpacity")) >= 0.70
        assert bool(anchor_core.property("visible")) is True
        assert float(anchor_host.property("opacity")) > 0.0
        assert float(anchor_core.property("opacity")) > 0.0
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_aliases_normalize_to_stable_visual_states() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

Item {
    width: 1080
    height: 520

    Grid {
        columns: 5
        spacing: 12

        StormforgeAnchorCore { objectName: "signalAlias"; width: 150; height: 190; state: "signal_acquired" }
        StormforgeAnchorCore { objectName: "ghostReadyAlias"; width: 150; height: 190; state: "ghost_ready" }
        StormforgeAnchorCore { objectName: "captureAlias"; width: 150; height: 190; state: "capture_active" }
        StormforgeAnchorCore { objectName: "routingAlias"; width: 150; height: 190; state: "routing" }
        StormforgeAnchorCore { objectName: "executingAlias"; width: 150; height: 190; state: "executing" }
        StormforgeAnchorCore {
            objectName: "speakingRequestedOnly"
            width: 150; height: 190
            voiceState: ({
                "voice_anchor_state": "speaking",
                "voice_current_phase": "requested",
                "speaking_visual_active": false,
                "active_playback_status": "requested"
            })
        }
        StormforgeAnchorCore {
            objectName: "speakingSupported"
            width: 150; height: 190
            voiceState: ({
                "voice_anchor_state": "speaking",
                "voice_current_phase": "playback_active",
                "speaking_visual_active": true,
                "active_playback_status": "playing"
            })
        }
        StormforgeAnchorCore { objectName: "approvalAlias"; width: 150; height: 190; state: "requires_approval" }
        StormforgeAnchorCore { objectName: "warningAlias"; width: 150; height: 190; state: "warning" }
        StormforgeAnchorCore { objectName: "errorAlias"; width: 150; height: 190; state: "error" }
        StormforgeAnchorCore { objectName: "disabledAlias"; width: 150; height: 190; state: "disabled" }
        StormforgeAnchorCore { objectName: "devAlias"; width: 150; height: 190; state: "dev" }
        StormforgeAnchorCore { objectName: "unknownAlias"; width: 150; height: 190; state: "new_backend_hint" }
        StormforgeAnchorCore { objectName: "inactiveWord"; width: 150; height: 190; state: "inactive" }
    }
}
""".strip()

    root = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeAnchorAliasHarness.qml"
                    )
                ),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(120)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        assert [message for message in messages if "StormforgeAnchor" in message] == []

        expected = {
            "signalAlias": "wake_detected",
            "ghostReadyAlias": "wake_detected",
            "captureAlias": "capturing",
            "routingAlias": "thinking",
            "executingAlias": "acting",
            "speakingRequestedOnly": "thinking",
            "speakingSupported": "speaking",
            "approvalAlias": "approval_required",
            "warningAlias": "blocked",
            "errorAlias": "failed",
            "disabledAlias": "unavailable",
            "devAlias": "mock_dev",
            "unknownAlias": "idle",
            "inactiveWord": "idle",
        }
        for object_name, state_name in expected.items():
            anchor = root.findChild(QtCore.QObject, object_name)
            assert anchor is not None, object_name
            assert anchor.property("normalizedState") == state_name
            assert anchor.property("resolvedState") == state_name
            assert anchor.property("visualState") == state_name
            assert anchor.property("anchorVisibilityStatus") != ""
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_visual_state_latches_transient_noncritical_changes() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {
    objectName: "transitionAnchor"
    width: 220
    height: 260
    state: ""
}
""".strip()

    anchor = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeAnchorTransitionHarness.qml"
                    )
                ),
            )
            anchor = component.create()
            app.processEvents()
            QtTest.QTest.qWait(80)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert [message for message in messages if "StormforgeAnchor" in message] == []

        assert anchor.property("normalizedState") == "idle"
        assert anchor.property("visualState") == "idle"
        initial_serial = int(anchor.property("visualStateChangeSerial"))
        dwell_ms = int(anchor.property("stateMinimumDwellMs"))
        transition_ms = int(anchor.property("stateTransitionDurationMs"))

        anchor.setProperty("state", "routing")
        app.processEvents()
        QtTest.QTest.qWait(20)
        app.processEvents()
        assert anchor.property("normalizedState") == "thinking"
        assert anchor.property("visualState") == "idle"
        assert anchor.property("pendingVisualState") == "thinking"
        assert int(anchor.property("visualStateChangeSerial")) == initial_serial

        QtTest.QTest.qWait(dwell_ms + 40)
        app.processEvents()
        assert anchor.property("visualState") == "thinking"
        assert anchor.property("previousVisualState") == "idle"
        changed_serial = int(anchor.property("visualStateChangeSerial"))
        assert changed_serial > initial_serial

        anchor.setProperty("state", "routing")
        app.processEvents()
        QtTest.QTest.qWait(30)
        app.processEvents()
        assert int(anchor.property("visualStateChangeSerial")) == changed_serial

        anchor.setProperty("state", "failed")
        app.processEvents()
        QtTest.QTest.qWait(20)
        app.processEvents()
        assert anchor.property("normalizedState") == "failed"
        assert anchor.property("visualState") == "failed"
        assert anchor.property("pendingVisualState") == ""
        assert int(anchor.property("visualStateChangeSerial")) > changed_serial

        QtTest.QTest.qWait(transition_ms + 40)
        app.processEvents()
        assert anchor.property("stateTransitionActive") is False
        assert float(anchor.property("transitionProgress")) == pytest.approx(1.0)
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_main_qml_stormforge_variant_uses_foundation_shells_without_replacing_classic() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene(
        {"STORMHELM_UI_VARIANT": "stormforge"}
    )
    try:
        assert bridge.uiVisualVariant == "stormforge"
        stormforge_ghost = root.findChild(QtCore.QObject, "stormforgeGhostShell")
        stormforge_deck = root.findChild(QtCore.QObject, "stormforgeDeckShell")
        classic_ghost = root.findChild(QtCore.QObject, "classicGhostShell")
        classic_deck = root.findChild(QtCore.QObject, "classicDeckShell")
        shared_center = root.findChild(QtCore.QObject, "sharedGhostCenterCluster")

        assert stormforge_ghost is not None
        assert stormforge_deck is not None
        assert classic_ghost is None
        assert classic_deck is None
        assert shared_center is not None
        assert shared_center.property("visible") is False
        assert stormforge_ghost.property("stormforgeFoundationReady") is True
        assert stormforge_deck.property("stormforgeFoundationReady") is True
        assert root.findChild(QtCore.QObject, "stormforgeGhostFoundationPanel") is not None
        assert root.findChild(QtCore.QObject, "stormforgeDeckFoundationPanel") is not None
    finally:
        _dispose_qt_objects(app, engine, root)


def test_main_qml_stormforge_ghost_loads_with_volumetric_fog_disabled() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene(
        {"STORMHELM_UI_VARIANT": "stormforge"}
    )
    try:
        assert bridge.uiVisualVariant == "stormforge"
        fog = root.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")
        atmosphere = root.findChild(QtCore.QObject, "stormforgeGhostAtmosphereSlot")
        anchor_core = root.findChild(QtCore.QObject, "stormforgeAnchorCore")
        assert fog is not None
        assert atmosphere is not None
        assert anchor_core is not None
        assert fog.property("rendererType") == "shader"
        assert fog.property("fogMode") == "volumetric"
        assert fog.property("active") is False
        assert fog.property("animationRunning") is False
        assert int(fog.property("qualitySamples")) == 0
        assert bool(fog.property("visible")) is False
        assert atmosphere.property("fogActive") is False
        assert bool(atmosphere.property("visible")) is False
    finally:
        _dispose_qt_objects(app, engine, root)


def test_main_qml_stormforge_ghost_loads_with_volumetric_fog_enabled() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene(
        {
            "STORMHELM_UI_VARIANT": "stormforge",
            "STORMHELM_STORMFORGE_FOG": "1",
        }
    )
    try:
        assert bridge.uiVisualVariant == "stormforge"
        fog = root.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")
        atmosphere = root.findChild(QtCore.QObject, "stormforgeGhostAtmosphereSlot")
        fallback = root.findChild(QtCore.QObject, "stormforgeFogFallbackLayer")
        assert fog is not None
        assert atmosphere is not None
        assert fallback is None
        assert fog.property("rendererType") == "shader"
        assert fog.property("fogMode") == "volumetric"
        assert fog.property("quality") == "medium"
        assert fog.property("active") is True
        assert fog.property("animationRunning") is True
        assert int(fog.property("qualitySamples")) == 14
        assert float(fog.property("intensity")) == pytest.approx(0.35)
        assert bool(fog.property("visible")) is True
        assert atmosphere.property("fogActive") is True
        assert bool(atmosphere.property("visible")) is True
    finally:
        _dispose_qt_objects(app, engine, root)


def test_stormforge_volumetric_fog_layer_exposes_production_readability_controls() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

Item {
    width: 960
    height: 680

    StormforgeVolumetricFogLayer {
        id: fog
        objectName: "productionFogLayer"
        anchors.fill: parent
        config: {
            "enabled": true,
            "mode": "volumetric",
            "quality": "high",
            "intensity": 0.42,
            "motion": true,
            "edgeFog": true,
            "foregroundWisps": true,
            "qualitySamples": 24,
            "density": 0.62,
            "driftSpeed": 0.055,
            "driftDirection": "right_to_left",
            "driftDirectionX": -1.0,
            "driftDirectionY": 0.05,
            "flowScale": 1.0,
            "crosswindWobble": 0.18,
            "rollingSpeed": 0.035,
            "wispStretch": 1.8,
            "noiseScale": 1.12,
            "edgeDensity": 0.88,
            "lowerFogBias": 0.45,
            "centerClearRadius": 0.40,
            "centerClearStrength": 0.70,
            "foregroundAmount": 0.18,
            "foregroundOpacityLimit": 0.06,
            "opacityLimit": 0.22,
            "protectedCenterX": 0.50,
            "protectedCenterY": 0.58,
            "protectedRadius": 0.36,
            "anchorCenterX": 0.50,
            "anchorCenterY": 0.30,
            "anchorRadius": 0.18,
            "cardClearStrength": 0.78
        }
    }
}
""".strip()

    root = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeFogProductionHarness.qml"
                    )
                ),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(40)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        assert [message for message in messages if "StormforgeVolumetricFog" in message] == []

        fog = root.findChild(QtCore.QObject, "productionFogLayer")
        assert fog is not None
        assert fog.property("active") is True
        assert int(fog.property("qualitySamples")) == 24
        assert float(fog.property("driftSpeed")) == pytest.approx(0.055)
        assert fog.property("driftDirection") == "right_to_left"
        assert float(fog.property("driftDirectionX")) == pytest.approx(-1.0)
        assert float(fog.property("driftDirectionY")) == pytest.approx(0.05)
        assert float(fog.property("flowScale")) == pytest.approx(1.0)
        assert float(fog.property("crosswindWobble")) == pytest.approx(0.18)
        assert float(fog.property("rollingSpeed")) == pytest.approx(0.035)
        assert float(fog.property("wispStretch")) == pytest.approx(1.8)
        assert float(fog.property("protectedCenterX")) == pytest.approx(0.50)
        assert float(fog.property("protectedCenterY")) == pytest.approx(0.58)
        assert float(fog.property("protectedRadius")) == pytest.approx(0.36)
        assert float(fog.property("anchorRadius")) == pytest.approx(0.18)
        assert float(fog.property("cardClearStrength")) == pytest.approx(0.78)
        assert float(fog.property("foregroundOpacityLimit")) == pytest.approx(0.06)
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_volumetric_fog_layer_exposes_activation_diagnostics_and_debug_visible_mode() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

Item {
    width: 960
    height: 680

    StormforgeVolumetricFogLayer {
        id: fog
        objectName: "diagnosticFogLayer"
        width: parent.width
        height: parent.height
        z: 4
        config: {
            "enabled": true,
            "mode": "volumetric",
            "quality": "medium",
            "intensity": 0.35,
            "motion": true,
            "qualitySamples": 14,
            "debugVisible": true,
            "debugIntensityMultiplier": 3.0,
            "debugTint": true,
            "centerClearStrength": 0.65,
            "cardClearStrength": 0.72,
            "protectedRadius": 0.36,
            "anchorRadius": 0.18
        }
    }
}
""".strip()

    root = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeFogDiagnosticsHarness.qml"
                )
            ),
        )
        root = component.create()
        app.processEvents()
        QtTest.QTest.qWait(50)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None

        fog = root.findChild(QtCore.QObject, "diagnosticFogLayer")
        assert fog is not None
        assert fog.property("fogEnabledRequested") is True
        assert fog.property("fogActive") is True
        assert fog.property("fogVisible") is True
        assert fog.property("shaderEnabled") is True
        assert fog.property("fallbackEnabled") is False
        assert fog.property("renderMode") == "debug_visible"
        assert fog.property("disabledReason") == ""
        assert int(fog.property("qualitySamples")) == 14
        assert float(fog.property("effectiveOpacity")) > 0.0
        assert int(fog.property("layerWidth")) == 960
        assert int(fog.property("layerHeight")) == 680
        assert float(fog.property("zLayer")) == pytest.approx(4.0)
        assert fog.property("debugVisible") is True

        mask_strengths = fog.property("maskStrengths")
        if hasattr(mask_strengths, "toVariant"):
            mask_strengths = mask_strengths.toVariant()
        assert mask_strengths["centerClearStrength"] == pytest.approx(0.65)
        assert mask_strengths["cardClearStrength"] == pytest.approx(0.72)
        assert mask_strengths["protectedRadius"] == pytest.approx(0.36)
        assert mask_strengths["anchorRadius"] == pytest.approx(0.18)

        motion_controls = fog.property("motionControls")
        if hasattr(motion_controls, "toVariant"):
            motion_controls = motion_controls.toVariant()
        assert motion_controls["driftDirection"] == "right_to_left"
        assert motion_controls["driftDirectionX"] == pytest.approx(-1.0)
        assert motion_controls["flowScale"] == pytest.approx(1.0)
        assert motion_controls["wispStretch"] == pytest.approx(1.8)

        debug_probe = root.findChild(QtCore.QObject, "stormforgeFogDebugVisibleProbe")
        assert debug_probe is not None
        assert bool(debug_probe.property("visible")) is True
        assert float(debug_probe.property("opacity")) > 0.0
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_volumetric_fog_layer_reports_disabled_reason_for_zero_geometry() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

Item {
    StormforgeVolumetricFogLayer {
        id: fog
        objectName: "zeroSizeFogLayer"
        width: 0
        height: 0
        config: {
            "enabled": true,
            "mode": "volumetric",
            "quality": "medium",
            "qualitySamples": 14
        }
    }
}
""".strip()

    root = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeFogZeroSizeHarness.qml"
                )
            ),
        )
        root = component.create()
        app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None

        fog = root.findChild(QtCore.QObject, "zeroSizeFogLayer")
        assert fog is not None
        assert fog.property("fogEnabledRequested") is True
        assert fog.property("fogActive") is False
        assert fog.property("shaderEnabled") is False
        assert fog.property("disabledReason") == "zero_geometry"
        assert int(fog.property("qualitySamples")) == 0
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_fog_visual_probe_captures_motion_artifacts() -> None:
    script_source = Path("scripts/run_stormforge_fog_visual_probe.py").read_text(
        encoding="utf-8"
    )

    assert "ghost_fog_on_t0.png" in script_source
    assert "ghost_fog_on_t1.png" in script_source
    assert "fog_motion_diff.png" in script_source
    assert '"on_t0_vs_on_t1"' in script_source
    assert '"motion_shader_capture_was_distinguishable"' in script_source
    assert '"motion_direction_estimate"' in script_source
    assert '"estimated_horizontal_shift_pixels"' in script_source


def test_stormforge_ghost_fog_fallback_is_explicit_and_non_volumetric() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

Item {
    width: 920
    height: 640

    StormforgeGhostShell {
        objectName: "fallbackFogShell"
        anchors.fill: parent
        stormforgeFogConfig: {
            "enabled": true,
            "mode": "fallback",
            "quality": "medium",
            "intensity": 0.35,
            "motion": true
        }
    }
}
""".strip()

    root = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeFogFallbackHarness.qml"
                    )
                ),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(50)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        assert [message for message in messages if "StormforgeFog" in message] == []

        volumetric = root.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")
        fallback = root.findChild(QtCore.QObject, "stormforgeFogFallbackLayer")
        atmosphere_slot = root.findChild(QtCore.QObject, "stormforgeGhostAtmosphereSlot")

        assert volumetric is not None
        assert volumetric.property("fogMode") == "fallback"
        assert volumetric.property("active") is False
        assert fallback is not None
        assert fallback.property("rendererType") == "fallback"
        assert fallback.property("active") is True
        assert fallback.property("animationRunning") is True
        assert atmosphere_slot is not None
        assert atmosphere_slot.property("fogActive") is True
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_ghost_shell_uses_distinct_low_density_composition() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

Item {
    width: 960
    height: 680

    StormforgeGhostShell {
        id: ghost
        objectName: "stormforgeGhostHarnessShell"
        anchors.fill: parent
        coreBottom: 328
        messages: [
            {"role": "user", "speaker": "You", "content": "Open the installer"},
            {"role": "assistant", "speaker": "Stormhelm", "content": "Approval is required before changing this machine."},
            {"role": "assistant", "speaker": "Stormhelm", "content": "I can hold here until you confirm."}
        ]
        primaryCard: {
            "title": "Approval Required",
            "subtitle": "Software control",
            "body": "Installing software changes this machine.",
            "resultState": "approval_required",
            "routeLabel": "Software"
        }
        contextCards: [
            {"title": "Plan ready", "subtitle": "Installer", "body": "Review before execution.", "resultState": "planned"},
            {"title": "Verification pending", "subtitle": "Truth", "body": "No install claim yet.", "resultState": "unverified"},
            {"title": "Extra card", "body": "This should stay out of Ghost density.", "resultState": "stale"}
        ]
        actionStrip: [
            {"label": "Open Deck", "localAction": "open_deck", "state": "planned"},
            {"label": "Cancel", "sendText": "cancel", "state": "blocked"}
        ]
        statusLine: "Awaiting approval."
        connectionLabel: "Signal steady"
        timeLabel: "14:12"
        voiceState: {
            "voice_current_phase": "listening",
            "voice_anchor_state": "listening",
            "speaking_visual_active": false
        }
    }
}
""".strip()

    root = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeGhostHarness.qml"
                    )
                ),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(60)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        assert [message for message in messages if "StormforgeGhost" in message] == []

        shell = root.findChild(QtCore.QObject, "stormforgeGhostHarnessShell")
        backdrop = root.findChild(QtCore.QObject, "stormforgeGhostBackdrop")
        stage = root.findChild(QtCore.QObject, "stormforgeGhostStage")
        anchor_host = root.findChild(QtCore.QObject, "stormforgeAnchorHost")
        anchor_core = root.findChild(QtCore.QObject, "stormforgeAnchorCore")
        status_line = root.findChild(QtCore.QObject, "stormforgeGhostStatusLine")
        transcript = root.findChild(QtCore.QObject, "stormforgeGhostTranscript")
        card_stack = root.findChild(QtCore.QObject, "stormforgeGhostCardStack")
        context_region = root.findChild(QtCore.QObject, "stormforgeGhostContextRegion")
        permission_prompt = root.findChild(QtCore.QObject, "stormforgeGhostPermissionPrompt")
        action_region = root.findChild(QtCore.QObject, "stormforgeGhostActionRegion")
        action_strip = root.findChild(QtCore.QObject, "stormforgeGhostActionStrip")
        atmosphere_slot = root.findChild(QtCore.QObject, "stormforgeGhostAtmosphereSlot")
        fog = root.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")

        assert shell is not None
        assert shell.property("stormforgeGhostComposition") == "UI-P2S"
        assert backdrop is not None
        assert stage is not None
        assert anchor_host is not None
        assert anchor_core is not None
        assert status_line is not None
        assert transcript is not None
        assert card_stack is not None
        assert context_region is not None
        assert permission_prompt is not None
        assert action_region is not None
        assert action_strip is not None
        assert atmosphere_slot is not None
        assert anchor_host.property("anchorHostMode") == "core"
        assert anchor_host.property("finalAnchorImplemented") is True
        assert float(anchor_host.property("width")) >= 180.0
        assert float(anchor_host.property("height")) > float(anchor_host.property("width"))
        assert anchor_host.property("resolvedState") == "approval_required"
        assert anchor_core.property("resolvedState") == "approval_required"
        assert anchor_core.property("motionProfile") == "approval_halo"
        assert status_line.property("stateTone") == "approval_required"
        assert int(transcript.property("visibleMessageCount")) == 2
        assert int(card_stack.property("visibleCardCount")) == 2
        assert int(context_region.property("visibleCardCount")) == 2
        assert permission_prompt.property("promptTone") == "approval_required"
        assert action_region.property("actionCount") == 2
        assert int(action_strip.property("actionCount")) == 2
        assert atmosphere_slot.property("fogImplemented") is True
        assert atmosphere_slot.property("fogActive") is False
        assert fog is not None
        assert fog.property("active") is False
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_ghost_shell_does_not_import_classic_or_deck_fog() -> None:
    shell_source = (
        Path.cwd()
        / "assets"
        / "qml"
        / "variants"
        / "stormforge"
        / "StormforgeGhostShell.qml"
    ).read_text(encoding="utf-8")

    assert "ClassicGhostShell" not in shell_source
    assert 'import "../classic"' not in shell_source
    assert "StormforgeAnchorHost" in shell_source
    assert "StormforgeVoiceCore" not in shell_source
    assert "StormforgeVolumetricFogLayer" in shell_source
    assert "StormforgeFogFallbackLayer" in shell_source
    assert "CommandDeck" not in shell_source
    assert "Particle" not in shell_source


def test_stormforge_ghost_merge_ownership_boundaries_are_clean() -> None:
    stormforge_dir = Path.cwd() / "assets" / "qml" / "variants" / "stormforge"
    shell_source = (stormforge_dir / "StormforgeGhostShell.qml").read_text(encoding="utf-8")
    stage_source = (stormforge_dir / "StormforgeGhostStage.qml").read_text(encoding="utf-8")
    host_source = (stormforge_dir / "StormforgeAnchorHost.qml").read_text(encoding="utf-8")
    core_source = (stormforge_dir / "StormforgeAnchorCore.qml").read_text(encoding="utf-8")

    assert "StormforgeAnchorHost" in shell_source
    assert "StormforgeAnchorCore {" not in shell_source
    assert "StormforgeVoiceCore" not in shell_source
    assert "StormforgeVolumetricFogLayer" not in stage_source
    assert "StormforgeAnchorCore" not in stage_source

    assert 'componentRole: "stormforge_anchor_host"' in host_source
    assert "ownsAnchorAnimation: false" in host_source
    assert "StormforgeAnchorCore" in host_source
    assert "Canvas" not in host_source
    assert "NumberAnimation" not in host_source
    assert "Timer" not in host_source

    assert 'componentRole: "stormforge_anchor_core"' in core_source
    assert "Canvas" in core_source
    assert "Timer" in core_source
    assert "StormforgeGhostStage" not in core_source
    assert "StormforgeVolumetricFogLayer" not in core_source


def test_stormforge_ghost_merge_z_layers_and_fog_slot_contract() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

Item {
    width: 960
    height: 680

    StormforgeGhostShell {
        id: ghost
        objectName: "mergeGhostShell"
        anchors.fill: parent
        stormforgeFogConfig: {
            "enabled": true,
            "mode": "volumetric",
            "quality": "medium",
            "intensity": 0.35
        }
        primaryCard: {
            "title": "Plan ready",
            "body": "No execution claim yet.",
            "resultState": "planned"
        }
        voiceState: {
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": true,
            "active_playback_status": "playing"
        }
    }
}
""".strip()

    root = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeGhostMergeHarness.qml"
                    )
                ),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(80)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        assert [message for message in messages if "Stormforge" in message] == []

        stage = root.findChild(QtCore.QObject, "stormforgeGhostStage")
        atmosphere = root.findChild(QtCore.QObject, "stormforgeGhostAtmosphereSlot")
        instrumentation = root.findChild(QtCore.QObject, "stormforgeGhostInstrumentationLayer")
        anchor_host = root.findChild(QtCore.QObject, "stormforgeAnchorHost")
        anchor_core = root.findChild(QtCore.QObject, "stormforgeAnchorCore")
        status_line = root.findChild(QtCore.QObject, "stormforgeGhostStatusLine")
        card_stack = root.findChild(QtCore.QObject, "stormforgeGhostCardStack")
        action_region = root.findChild(QtCore.QObject, "stormforgeGhostActionRegion")
        fog = root.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")

        assert stage is not None
        assert atmosphere is not None
        assert instrumentation is not None
        assert anchor_host is not None
        assert anchor_core is not None
        assert status_line is not None
        assert card_stack is not None
        assert action_region is not None
        assert fog is not None

        assert int(stage.property("layerBackdrop")) < int(stage.property("layerAtmosphere"))
        assert int(stage.property("layerAtmosphere")) < int(stage.property("layerInstrumentation"))
        assert int(stage.property("layerInstrumentation")) < int(stage.property("layerAnchor"))
        assert int(stage.property("layerAnchor")) < int(stage.property("layerTranscript"))
        assert int(stage.property("layerTranscript")) < int(stage.property("layerCards"))
        assert int(stage.property("layerCards")) < int(stage.property("layerActions"))
        assert int(stage.property("layerActions")) < int(stage.property("layerForegroundAtmosphere"))

        assert float(atmosphere.property("z")) < float(stage.property("z"))
        assert float(instrumentation.property("z")) == float(stage.property("layerInstrumentation"))
        assert float(anchor_host.property("z")) == float(stage.property("layerAnchor"))
        assert float(status_line.property("z")) == float(stage.property("layerTranscript"))
        assert float(card_stack.property("z")) == float(stage.property("layerCards"))
        assert float(action_region.property("z")) == float(stage.property("layerActions"))
        assert anchor_host.property("ownsAnchorAnimation") is False
        assert anchor_core.property("finalAnchorImplemented") is True
        assert atmosphere.property("fogActive") is True
        assert fog.property("active") is True
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_ghost_docs_match_merge_ownership_contract() -> None:
    docs = (Path.cwd() / "docs" / "ui-surfaces.md").read_text(encoding="utf-8")
    required_phrases = [
        "UI-P2M merge seam contract",
        "`StormforgeGhostStage.qml` owns Ghost stage layer constants",
        "`StormforgeAnchorHost.qml` owns anchor placement and integration",
        "`StormforgeAnchorCore.qml` owns anchor identity, state animation",
        "`stormforgeGhostAtmosphereSlot` remains the only Ghost shell fog host",
        "`ownsAnchorAnimation: false`",
    ]

    for phrase in required_phrases:
        assert phrase in docs


def _wait_for_render_confirmation(
    app: QtWidgets.QApplication,
    bridge: UiBridge,
    surface: str,
    *,
    status: str = "confirmed",
    timeout_ms: int = 1200,
) -> dict[str, object]:
    deadline = QtCore.QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired():
        app.processEvents()
        QtTest.QTest.qWait(25)
        for confirmation in reversed(bridge.uiRenderConfirmations):
            if (
                confirmation.get("surface") == surface
                and confirmation.get("render_confirmation_status") == status
            ):
                return confirmation
    raise AssertionError(
        f"Missing render confirmation for {surface}; confirmations={bridge.uiRenderConfirmations[-8:]}"
    )


def _l71_route_event(cursor: int) -> dict[str, object]:
    return {
        "cursor": cursor,
        "event_id": cursor,
        "event_family": "route",
        "event_type": "route.selected",
        "severity": "info",
        "subsystem": "planner",
        "visibility_scope": "ghost_hint",
        "message": "Route selected.",
        "payload": {
            "request_id": "qml-l71-route",
            "route_family": "software_control",
            "subject": "Calculator",
            "stage": "route_selected",
            "summary": "Software route selected.",
        },
    }


def test_main_qml_emits_l71_render_confirmations_for_live_surfaces() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene()
    try:
        bridge.apply_stream_event(_l71_route_event(91_001))
        ghost_confirmation = _wait_for_render_confirmation(
            app,
            bridge,
            "ghost_primary",
        )
        assert ghost_confirmation["confirmation_source"] == "qml_component"
        assert ghost_confirmation["event_id"] == "91001"

        bridge.apply_stream_event(
            {
                "cursor": 91_002,
                "event_id": 91_002,
                "event_family": "voice",
                "event_type": "voice.synthesis_started",
                "severity": "info",
                "subsystem": "voice",
                "visibility_scope": "deck_context",
                "message": "TTS started.",
                "payload": {
                    "turn_id": "qml-l71-voice",
                    "speech_request_id": "speech-qml-l71",
                    "status": "started",
                },
            }
        )
        voice_confirmation = _wait_for_render_confirmation(
            app,
            bridge,
            "voice_core",
        )
        assert voice_confirmation["visible_state_value"] == "synthesizing"
        assert bridge.voiceState.get("active_playback_status") is None

        bridge.setMode("deck")
        QtTest.QTest.qWait(420)
        app.processEvents()
        bridge.apply_stream_state(
            {"source": "client", "phase": "reconnecting", "cursor": 91_003}
        )
        deck_confirmation = _wait_for_render_confirmation(
            app,
            bridge,
            "deck_event_spine",
        )
        assert "reconnecting" in str(deck_confirmation["visible_state_value"])
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


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
