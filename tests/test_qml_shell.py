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
        assert idle.property("visualTuningVersion") == "UI-P2A.6.1"
        assert idle.property("idlePresenceHotfixVersion") == "UI-P2A.4A"
        assert idle.property("stateStabilityVersion") == "UI-P2A.6"
        assert idle.property("organicMotionVersion") == "UI-P2A.6.1"
        assert idle.property("blobMotionSweetSpotVersion") == "UI-P2A.6.1"
        assert idle.property("organicMotionAmplitudeVersion") == "UI-P2A.6.1"
        assert idle.property("anchorMotionArchitecture") == "organic_blob_hybrid"
        assert bool(idle.property("blobCoreEnabled")) is True
        assert int(idle.property("blobPointCount")) >= 24
        assert bool(idle.property("organicBlobMotionActive")) is True
        assert bool(idle.property("uniformScalePulseDisabled")) is True
        assert 0.080 <= float(idle.property("organicMotionAmplitude")) <= 0.095
        assert 0.080 <= float(idle.property("blobDeformationStrength")) <= 0.095
        assert 0.066 <= float(idle.property("blobBaseDeformationStrength")) <= 0.078
        assert 0.165 <= float(idle.property("blobSpeakingDeformationStrength")) <= 0.185
        assert int(idle.property("blobPrimaryCycleMs")) >= 7500
        assert int(idle.property("blobSecondaryCycleMs")) >= 12000
        assert int(idle.property("blobDriftCycleMs")) >= 18000
        assert bool(idle.property("idleUniformScalePulseDisabled")) is True
        assert bool(idle.property("idleOrganicMotionActive")) is True
        assert int(idle.property("idlePrimaryCycleMs")) >= 7000
        assert int(idle.property("idleSecondaryCycleMs")) >= 11000
        assert int(idle.property("idleDriftCycleMs")) >= 17000
        assert bool(idle.property("ringFragmentsActive")) is True
        assert 2 <= int(idle.property("ringFragmentCount")) <= 4
        assert int(idle.property("ringFragmentMinCycleMs")) >= 18000
        assert bool(idle.property("speakingAnimationStable")) is True
        assert int(idle.property("speakingGraceMs")) >= 120
        assert bool(idle.property("visualStateStable")) is True
        assert bool(idle.property("animationPhaseDoesNotResetOnSameState")) is True
        assert idle.property("signatureSilhouette") == "helm_crown_lens_aperture"
        assert idle.property("centerLensSignature") == "organic_blob_core"
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
        assert bool(idle.property("idleOrganicMotionActive")) is True
        assert 0.0 <= float(idle.property("idleBreathValue")) <= 1.0
        assert float(idle.property("idlePulseMin")) > 0.0
        assert float(idle.property("idlePulseMax")) > float(idle.property("idlePulseMin"))
        assert int(idle.property("stateTransitionDurationMs")) >= 260
        assert int(idle.property("stateMinimumDwellMs")) >= 80
        assert idle.property("anchorVisibilityStatus") == "visible_idle_floor"
        assert idle.property("stateVisualSignature") == "powered_watch"
        assert idle.property("stateGeometrySignature") == "closed_watch_crown"
        assert idle.property("centerStateSignature") == "calm_organic_core"
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
        assert listening.property("centerStateSignature") == "receptive_organic_core"
        assert transcribing.property("resolvedState") == "transcribing"
        assert transcribing.property("motionProfile") == "listening_wave"
        assert transcribing.property("stateGeometrySignature") == "segmented_processing_aperture"
        assert transcribing.property("centerStateSignature") == "segmented_processing_blob"
        assert speaking.property("resolvedState") == "speaking"
        assert speaking.property("normalizedState") == "speaking"
        assert speaking.property("resolvedLabel") == "Speaking"
        assert speaking.property("motionProfile") == "radiating"
        assert speaking.property("stateVisualSignature") == "playback_radiance"
        assert speaking.property("stateGeometrySignature") == "response_aperture_radiance"
        assert speaking.property("centerStateSignature") == "radiant_voice_blob"
        assert speaking.property("audioReactiveSource") == "playback_output_envelope"
        assert float(speaking.property("rawSpeakingLevel")) == pytest.approx(0.67)
        assert float(speaking.property("effectiveSpeakingLevel")) == pytest.approx(float(speaking.property("finalSpeakingEnergy")))
        assert 0.0 < float(speaking.property("effectiveSpeakingLevel")) < float(speaking.property("rawSpeakingLevel"))
        assert float(speaking.property("speakingEnvelopeSmoothed")) > 0.0
        assert bool(speaking.property("visualSpeakingActive")) is True
        assert bool(speaking.property("speakingPhaseContinuous")) is True
        assert bool(speaking.property("speakingStateFlapGuardEnabled")) is True
        assert requested.property("resolvedState") == "thinking"
        assert requested.property("normalizedState") == "thinking"
        assert requested.property("visualState") == "thinking"
        assert requested.property("resolvedLabel") == "Thinking"
        assert requested.property("motionProfile") == "orbit"
        assert requested.property("stateGeometrySignature") == "internal_orbit_aperture"
        assert requested.property("centerStateSignature") == "slow_internal_blob"
        assert thinking.property("resolvedState") == "thinking"
        assert thinking.property("motionProfile") == "orbit"
        assert thinking.property("stateVisualSignature") == "orbital_bearing"
        assert thinking.property("stateGeometrySignature") == "internal_orbit_aperture"
        assert thinking.property("centerStateSignature") == "slow_internal_blob"
        assert acting.property("resolvedState") == "acting"
        assert acting.property("motionProfile") == "directional_trace"
        assert acting.property("stateVisualSignature") == "bearing_trace"
        assert acting.property("stateGeometrySignature") == "directional_helm_trace"
        assert acting.property("centerStateSignature") == "bearing_directed_blob"
        assert approval.property("resolvedState") == "approval_required"
        assert approval.property("resolvedLabel") == "Approval required"
        assert approval.property("motionProfile") == "approval_halo"
        assert approval.property("stateVisualSignature") == "approval_bezel"
        assert approval.property("stateGeometrySignature") == "brass_clamp_bezel"
        assert approval.property("centerStateSignature") == "brass_bound_blob"
        assert blocked.property("resolvedState") == "blocked"
        assert blocked.property("stateVisualSignature") == "warning_bezel"
        assert blocked.property("stateGeometrySignature") == "amber_boundary_clamp"
        assert blocked.property("centerStateSignature") == "amber_bound_blob"
        assert failed.property("resolvedState") == "failed"
        assert failed.property("stateVisualSignature") == "failure_bezel"
        assert failed.property("stateGeometrySignature") == "diagnostic_break_segment"
        assert failed.property("centerStateSignature") == "diagnostic_blob_break"
        assert mock.property("resolvedState") == "mock_dev"
        assert mock.property("stateVisualSignature") == "development_trace"
        assert mock.property("stateGeometrySignature") == "synthetic_trace_aperture"
        assert mock.property("centerStateSignature") == "synthetic_violet_blob"
        assert unavailable.property("resolvedState") == "unavailable"
        assert unavailable.property("normalizedState") == "unavailable"
        assert unavailable.property("visualState") == "unavailable"
        assert unavailable.property("motionProfile") == "muted"
        assert unavailable.property("stateVisualSignature") == "offline_muted"
        assert unavailable.property("stateGeometrySignature") == "dimmed_lens"
        assert unavailable.property("centerStateSignature") == "nearly_dark_lens"
        assert unavailable.property("anchorVisibilityStatus") == "visible_unavailable_floor"
        assert bool(unavailable.property("idleMotionActive")) is False
        assert bool(unavailable.property("idleOrganicMotionActive")) is False
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
        assert float(anchor_host.property("width")) >= 248.0
        assert anchor_core.property("idlePerceptualPresenceVersion") == "UI-P2A.6.5A"
        assert float(anchor_core.property("minimumRingOpacity")) >= 0.38
        assert float(anchor_core.property("minimumCenterLensOpacity")) >= 0.50
        assert float(anchor_core.property("minimumBearingTickOpacity")) >= 0.26
        assert float(anchor_core.property("minimumSignalPointOpacity")) >= 0.48
        assert float(anchor_core.property("minimumLabelOpacity")) >= 0.70
        assert float(anchor_core.property("idleActiveAlphaFloor")) >= 0.95
        assert bool(anchor_core.property("visible")) is True
        assert float(anchor_host.property("opacity")) > 0.0
        assert float(anchor_core.property("opacity")) > 0.0
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_ghost_p2a66_voice_offline_keeps_anchor_identity_visible() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeGhostShell {
    objectName: "voiceOfflineGhostShell"
    width: 900
    height: 620
    stormforgeFogConfig: {"enabled": false}
    assistantState: "idle"
    statusLine: "Voice offline"
    routeInspector: {"routeState": "idle", "statusLabel": "Ready"}
    voiceState: {
        "voice_current_phase": "unavailable",
        "voice_anchor_state": "unavailable",
        "voice_available": false,
        "available": false,
        "unavailable_reason": "capture_disabled",
        "active_playback_status": "idle",
        "speaking_visual_active": false
    }
}
""".strip()

    shell = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeGhostP2A66VoiceOfflineHarness.qml"
                    )
                ),
            )
            shell = component.create()
            app.processEvents()
            QtTest.QTest.qWait(160)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert shell is not None
        assert [message for message in messages if "Stormforge" in message] == []

        host = shell.findChild(QtCore.QObject, "stormforgeAnchorHost")
        anchor = shell.findChild(QtCore.QObject, "stormforgeAnchorCore")
        assert host is not None
        assert anchor is not None

        assert shell.property("ghostTone") in {"idle", "ready"}
        assert shell.property("ghostToneSource") != "voice_state"
        assert host.property("resolvedState") in {"idle", "ready"}
        assert anchor.property("resolvedState") in {"idle", "ready"}
        assert anchor.property("neverVanishInvariantVersion") == "UI-P2A.6.6"
        assert anchor.property("resolvedSublabel") == "Voice offline"
        assert anchor.property("voiceAvailabilityState") == "capture_disabled"
        assert bool(anchor.property("voiceOfflineDoesNotHideAnchor")) is True
        assert bool(anchor.property("finalVisibilityFloorApplied")) is True
        assert bool(anchor.property("finalAnchorVisible")) is True
        assert float(anchor.property("finalBlobOpacity")) >= 0.54
        assert float(anchor.property("finalRingOpacity")) >= 0.38
        assert float(anchor.property("finalCenterGlowOpacity")) >= 0.30
        assert float(anchor.property("finalSignalPointOpacity")) >= 0.48
        assert float(anchor.property("finalBearingTickOpacity")) >= 0.26
        assert bool(anchor.property("uniformScalePulseDisabled")) is True
        assert anchor.property("anchorMotionArchitecture") == "organic_blob_hybrid"
    finally:
        _dispose_qt_objects(app, shell, engine)


def test_stormforge_ghost_p2a66_voice_capture_and_lifecycle_advisory_cards_do_not_dominate_anchor() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeGhostShell {
    objectName: "voiceCaptureCardGhostShell"
    width: 900
    height: 620
    stormforgeFogConfig: {"enabled": false}
    assistantState: "idle"
    statusLine: "Standing watch."
    routeInspector: {"routeState": "idle", "statusLabel": "Ready"}
    contextCards: [
        {
            "title": "Voice Capture",
            "subtitle": "Unavailable",
            "body": "Capture disabled.",
            "resultState": "unavailable"
        },
        {
            "title": "Lifecycle Hold",
            "subtitle": "Hold",
            "body": "Install posture changed from portable to source; review lifecycle boundaries before continuing.",
            "resultState": "hold"
        }
    ]
    voiceState: {
        "voice_anchor": {"state_label": "Idle"},
        "voice_current_phase": "unavailable",
        "voice_anchor_state": "unavailable",
        "voice_available": false,
        "available": false,
        "unavailable_reason": "capture_disabled",
        "active_playback_status": "idle",
        "speaking_visual_active": false
    }
}
""".strip()

    shell = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeGhostP2A66VoiceCaptureCardHarness.qml"
                    )
                ),
            )
            shell = component.create()
            app.processEvents()
            QtTest.QTest.qWait(160)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert shell is not None
        assert [message for message in messages if "Stormforge" in message] == []

        host = shell.findChild(QtCore.QObject, "stormforgeAnchorHost")
        anchor = shell.findChild(QtCore.QObject, "stormforgeAnchorCore")
        assert host is not None
        assert anchor is not None

        assert shell.property("ghostTone") == "ready"
        assert shell.property("ghostToneSource") == "route_or_assistant_state"
        assert host.property("resolvedState") == "ready"
        assert anchor.property("resolvedState") == "ready"
        assert anchor.property("resolvedLabel") == "Idle"
        assert anchor.property("resolvedSublabel") == "Voice offline"
        assert anchor.property("voiceAvailabilityState") == "capture_disabled"
        assert bool(anchor.property("voiceOfflineDoesNotHideAnchor")) is True
        assert bool(anchor.property("finalAnchorVisible")) is True
        assert float(anchor.property("finalBlobOpacity")) >= 0.54
        assert bool(anchor.property("uniformScalePulseDisabled")) is True
    finally:
        _dispose_qt_objects(app, shell, engine)


def test_stormforge_ghost_p2a66_lifecycle_advisory_does_not_suppress_speaking() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeGhostShell {
    objectName: "speakingWithLifecycleAdvisoryGhostShell"
    width: 900
    height: 620
    stormforgeFogConfig: {"enabled": false}
    assistantState: "idle"
    routeInspector: {"routeState": "idle", "statusLabel": "Ready"}
    contextCards: [
        {
            "title": "Voice Capture",
            "subtitle": "Unavailable",
            "body": "Capture disabled.",
            "resultState": "unavailable"
        },
        {
            "title": "Lifecycle Hold",
            "subtitle": "Hold",
            "body": "Install posture changed from portable to source; review lifecycle boundaries before continuing.",
            "resultState": "hold"
        }
    ]
    voiceState: {
        "voice_anchor": {"state_label": "Speaking"},
        "voice_current_phase": "playback_active",
        "voice_anchor_state": "speaking",
        "voice_available": false,
        "available": false,
        "unavailable_reason": "capture_disabled",
        "active_playback_status": "playing",
        "speaking_visual_active": true,
        "voice_center_blob_scale_drive": 0.72,
        "voice_outer_speaking_motion": 0.52
    }
}
""".strip()

    shell = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeGhostP2A66SpeakingAdvisoryHarness.qml"
                    )
                ),
            )
            shell = component.create()
            app.processEvents()
            QtTest.QTest.qWait(160)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert shell is not None
        assert [message for message in messages if "Stormforge" in message] == []

        host = shell.findChild(QtCore.QObject, "stormforgeAnchorHost")
        anchor = shell.findChild(QtCore.QObject, "stormforgeAnchorCore")
        assert host is not None
        assert anchor is not None

        assert shell.property("ghostTone") == "speaking"
        assert shell.property("ghostToneSource") == "speaking_playback_state"
        assert host.property("resolvedState") == "speaking"
        assert anchor.property("resolvedState") == "speaking"
        assert anchor.property("resolvedLabel") == "Speaking"
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert bool(anchor.property("finalAnchorVisible")) is True
        assert bool(anchor.property("uniformScalePulseDisabled")) is True
    finally:
        _dispose_qt_objects(app, shell, engine)


def test_stormforge_ghost_p2a67_lifecycle_boundary_warning_does_not_override_live_speaking() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeGhostShell {
    objectName: "speakingWithBoundaryAdvisoryGhostShell"
    width: 900
    height: 620
    stormforgeFogConfig: {"enabled": false}
    assistantState: "warning"
    statusLine: "Held at boundary."
    routeInspector: {
        "routeState": "hold",
        "statusLabel": "Held at boundary",
        "title": "Lifecycle Hold",
        "reason": "Install posture changed from portable to source; review lifecycle boundaries before continuing."
    }
    primaryCard: {
        "title": "Lifecycle Hold",
        "subtitle": "Hold",
        "body": "Install posture changed from portable to source; review lifecycle boundaries before continuing.",
        "resultState": "hold"
    }
    voiceState: {
        "voice_anchor": {"state_label": "Speaking"},
        "voice_current_phase": "playback_active",
        "voice_anchor_state": "speaking",
        "active_playback_status": "playing",
        "speaking_visual_active": true,
        "voice_center_blob_scale_drive": 0.74,
        "voice_outer_speaking_motion": 0.56
    }
}
""".strip()

    shell = None
    try:
        with _capture_qt_messages() as messages:
            component.setData(
                harness_qml.encode("utf-8"),
                QtCore.QUrl.fromLocalFile(
                    str(
                        workspace_config.runtime.assets_dir
                        / "qml"
                        / "StormforgeGhostP2A67SpeakingBoundaryHarness.qml"
                    )
                ),
            )
            shell = component.create()
            app.processEvents()
            QtTest.QTest.qWait(180)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert shell is not None
        assert [message for message in messages if "Stormforge" in message] == []

        host = shell.findChild(QtCore.QObject, "stormforgeAnchorHost")
        anchor = shell.findChild(QtCore.QObject, "stormforgeAnchorCore")
        assert host is not None
        assert anchor is not None

        assert shell.property("ghostTone") == "speaking"
        assert shell.property("ghostToneSource") == "speaking_playback_state"
        assert host.property("resolvedState") == "speaking"
        assert anchor.property("resolvedState") == "speaking"
        assert anchor.property("visualState") == "speaking"
        assert anchor.property("resolvedLabel") == "Speaking"
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert bool(anchor.property("speakingPhaseContinuous")) is True
    finally:
        _dispose_qt_objects(app, shell, engine)


def test_stormforge_anchor_p2a69_speaking_audio_reactivity_is_sixty_five_percent_stronger() -> None:
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
    objectName: "speakingBoostAnchor"
    width: 230
    height: 270
    state: "speaking"
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "speaking",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_center_blob_scale_drive": 0.58,
        "voice_audio_level": 0.62,
        "voice_outer_speaking_motion": 0.54,
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "playback_output_envelope"
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorP2A69SpeakingBoostHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(220)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("normalizedState") == "speaking"
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert anchor.property("speakingAudioReactiveStrengthVersion") == "UI-P2A.6.9"
        assert float(anchor.property("speakingAudioReactiveStrengthBoost")) == pytest.approx(2.475)
        assert float(anchor.property("speakingExpressionBoost")) == pytest.approx(1.92)
        assert anchor.property("ringFragmentVisibilityVersion") == "UI-P2A.6.8"
        assert float(anchor.property("ringFragmentOpacity")) >= 0.23
        assert float(anchor.property("idleFragmentOpacityFloor")) >= 0.40
        assert bool(anchor.property("uniformScalePulseDisabled")) is True
        assert anchor.property("anchorMotionArchitecture") == "organic_blob_hybrid"
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_l02_prefers_playback_envelope_over_raw_level() -> None:
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
    objectName: "playbackEnvelopeAnchor"
    width: 230
    height: 270
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_center_blob_scale_drive": 0.04,
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "streaming_chunk_envelope",
        "playback_envelope_available": true,
        "playback_envelope_supported": true,
        "playback_envelope_source": "playback_pcm",
        "playback_envelope_energy": 0.72,
        "playback_envelope_sample_rate_hz": 60,
        "playback_envelope_latency_ms": 80,
        "playback_envelope_window_mode": "playback_time",
        "playback_envelope_query_time_ms": 16,
        "playback_visual_time_ms": 16,
        "playback_envelope_samples_recent": [
            {"sample_time_ms": 0, "smoothed_energy": 0.18, "energy": 0.20, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 16, "smoothed_energy": 0.46, "energy": 0.50, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 32, "smoothed_energy": 0.72, "energy": 0.78, "source": "pcm_playback", "valid": true}
        ],
        "speaking_visual_sync_mode": "playback_envelope"
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL02PlaybackEnvelopeHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(220)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("playbackEnvelopeVersion") == "Voice-L0.2.1"
        assert bool(anchor.property("playbackEnvelopeAvailable")) is True
        assert anchor.property("playbackEnvelopeSource") == "playback_pcm"
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is True
        assert float(anchor.property("envelopeCrossfadeAlpha")) > 0.20
        assert anchor.property("speakingVisualSyncMode") == "playback_envelope"
        assert bool(anchor.property("envelopeInterpolationActive")) is True
        assert float(anchor.property("playbackEnvelopeEnergy")) > 0.25
        assert float(anchor.property("finalSpeakingEnergy")) > float(anchor.property("rawSpeakingLevel"))
        assert bool(anchor.property("rawLevelDirectGeometryDriveDisabled")) is True
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_ar1_uses_pcm_stream_meter_voice_energy() -> None:
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
    objectName: "ar1PcmMeterAnchor"
    width: 230
    height: 270
    voiceState: ({
        "playback_id": "ar1-qml-meter",
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_visual_available": true,
        "voice_visual_active": true,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.72,
        "voice_visual_playback_id": "ar1-qml-meter",
        "voice_visual_latest_age_ms": 4
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorAR1PcmMeterHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("qmlAnchorReactiveChainVersion") == "Voice-AR-DIAG"
        assert anchor.property("qmlReceivedVoiceVisualSource") == "pcm_stream_meter"
        assert anchor.property("qmlReceivedPlaybackId") == "ar1-qml-meter"
        assert float(anchor.property("qmlReceivedVoiceVisualEnergy")) == pytest.approx(0.72)
        assert anchor.property("qmlSpeakingEnergySource") == "pcm_stream_meter"
        assert float(anchor.property("finalSpeakingEnergy")) > 0.0
        assert bool(anchor.property("uniformScalePulseDisabled")) is True
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_ar1_idle_ignores_voice_visual_energy() -> None:
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
    objectName: "ar1IdleAnchor"
    width: 230
    height: 270
    voiceState: ({
        "voice_anchor_state": "idle",
        "voice_current_phase": "idle",
        "speaking_visual_active": false,
        "active_playback_status": "idle",
        "voice_visual_available": true,
        "voice_visual_active": false,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.95,
        "voice_visual_playback_id": "ar1-idle",
        "voice_visual_latest_age_ms": 4
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorAR1IdleHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(180)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("qmlReceivedVoiceVisualSource") == "pcm_stream_meter"
        assert float(anchor.property("qmlReceivedVoiceVisualEnergy")) == pytest.approx(0.95)
        assert anchor.property("qmlSpeakingEnergySource") == "none"
        assert float(anchor.property("finalSpeakingEnergy")) == pytest.approx(0.0)
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_ar5_uses_voice_state_when_hot_visual_state_is_stale() -> None:
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
    objectName: "ar5StaleHotVisualAnchor"
    width: 230
    height: 270
    voiceState: ({
        "playback_id": "ar5-stale-hot",
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_visual_available": true,
        "voice_visual_active": true,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.68,
        "voice_visual_playback_id": "ar5-stale-hot",
        "voice_visual_latest_age_ms": 6
    })
    voiceVisualState: ({
        "playback_id": "ar5-stale-hot",
        "voice_visual_active": false,
        "voice_visual_energy": 0.0,
        "voice_visual_source": "unavailable",
        "voice_visual_latest_age_ms": 0
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorAR5StaleHotVisualHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert anchor is not None

        for frame in range(1, 18):
            anchor.setProperty("visualClockWallTimeMs", 1000 + frame * 16)
            anchor.setProperty("visualClockDeltaMs", 16)
            anchor.setProperty("visualClockFrameCounter", frame)
            app.processEvents()

        assert anchor.property("qmlReceivedVoiceVisualSource") == "pcm_stream_meter"
        assert bool(anchor.property("qmlVoiceVisualActive")) is True
        assert float(anchor.property("qmlReceivedVoiceVisualEnergy")) == pytest.approx(0.68)
        assert float(anchor.property("targetVoiceVisualEnergy")) == pytest.approx(0.68)
        assert anchor.property("qmlSpeakingEnergySource") == "pcm_stream_meter"
        assert float(anchor.property("finalSpeakingEnergy")) > 0.20
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_ghost_ar5_merge_uses_live_voice_state_when_hot_pcm_row_is_stale() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeGhostShell {
    objectName: "ar5StalePcmHotGhost"
    width: 900
    height: 620
    stormforgeFogConfig: {"enabled": false}
    assistantState: "idle"
    statusLine: "Speaking"
    voiceState: ({
        "playback_id": "ar5-stale-pcm-hot",
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_visual_available": true,
        "voice_visual_active": true,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.64,
        "voice_visual_playback_id": "ar5-stale-pcm-hot",
        "voice_visual_latest_age_ms": 4
    })
    voiceVisualState: ({
        "playback_id": "ar5-stale-pcm-hot",
        "voice_visual_active": false,
        "voice_visual_energy": 0.0,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_latest_age_ms": 0
    })
    readonly property var exposedMergedVoiceVisualState: mergedVoiceVisualState()
    readonly property bool exposedMergedVoiceVisualActive: valueBool(exposedMergedVoiceVisualState.voice_visual_active)
    readonly property real exposedMergedVoiceVisualEnergy: Number(exposedMergedVoiceVisualState.voice_visual_energy || 0)
    readonly property string exposedMergedVoiceVisualSource: valueText(exposedMergedVoiceVisualState.voice_visual_source)
}
""".strip()

    shell = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeGhostAR5StalePcmHotHarness.qml"
                )
            ),
        )
        shell = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert shell is not None

        assert shell.property("exposedMergedVoiceVisualSource") == "pcm_stream_meter"
        assert bool(shell.property("exposedMergedVoiceVisualActive")) is True
        assert float(shell.property("exposedMergedVoiceVisualEnergy")) == pytest.approx(0.64)
    finally:
        _dispose_qt_objects(app, shell, engine)


def test_stormforge_ghost_ar6_terminal_state_wins_over_stale_active_broad_state() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeGhostShell {
    objectName: "ar6TerminalWinsGhost"
    width: 900
    height: 620
    stormforgeFogConfig: {"enabled": false}
    assistantState: "idle"
    statusLine: "Speaking"
    visualVoiceState: ({
        "authoritativeVoiceStateVersion": "AR6",
        "playback_id": "ar6-terminal",
        "activePlaybackId": "ar6-terminal",
        "activePlaybackStatus": "playing",
        "authoritativePlaybackId": "ar6-terminal",
        "authoritativePlaybackStatus": "playing",
        "authoritativeVoiceVisualActive": true,
        "authoritativeVoiceVisualEnergy": 0.61,
        "authoritativeStateSequence": 20,
        "authoritativeStateSource": "pcm_stream_meter",
        "voice_visual_available": true,
        "voice_visual_active": true,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.61,
        "voice_visual_playback_id": "ar6-terminal",
        "speaking_visual_active": true
    })
    voiceVisualState: ({
        "authoritativeVoiceStateVersion": "AR6",
        "playback_id": "ar6-terminal",
        "activePlaybackId": "",
        "activePlaybackStatus": "completed",
        "authoritativePlaybackId": "ar6-terminal",
        "authoritativePlaybackStatus": "completed",
        "authoritativeVoiceVisualActive": false,
        "authoritativeVoiceVisualEnergy": 0.0,
        "authoritativeStateSequence": 21,
        "authoritativeStateSource": "pcm_stream_meter",
        "voice_visual_available": true,
        "voice_visual_active": false,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.0,
        "voice_visual_playback_id": "ar6-terminal",
        "speaking_visual_active": false,
        "speakingExitedReason": "terminal_completed",
        "raw_audio_present": false
    })
    readonly property var exposedMergedVoiceVisualState: mergedVoiceVisualState()
    readonly property bool exposedMergedVoiceVisualActive: valueBool(exposedMergedVoiceVisualState.voice_visual_active)
    readonly property bool exposedAuthoritativeVisualActive: valueBool(exposedMergedVoiceVisualState.authoritativeVoiceVisualActive)
    readonly property real exposedMergedVoiceVisualEnergy: Number(exposedMergedVoiceVisualState.voice_visual_energy || 0)
    readonly property string exposedMergedPlaybackStatus: valueText(exposedMergedVoiceVisualState.authoritativePlaybackStatus)
    readonly property bool exposedSupportsSpeaking: voiceSupportsSpeakingFor(exposedMergedVoiceVisualState)
}
""".strip()

    shell = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeGhostAR6TerminalWinsHarness.qml"
                )
            ),
        )
        shell = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert shell is not None

        assert shell.property("exposedMergedPlaybackStatus") == "completed"
        assert bool(shell.property("exposedMergedVoiceVisualActive")) is False
        assert bool(shell.property("exposedAuthoritativeVisualActive")) is False
        assert float(shell.property("exposedMergedVoiceVisualEnergy")) == pytest.approx(0.0)
        assert bool(shell.property("exposedSupportsSpeaking")) is False
    finally:
        _dispose_qt_objects(app, shell, engine)


def test_stormforge_anchor_ar6_authoritative_visual_state_wins_over_stale_broad_state() -> None:
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
    objectName: "ar6AuthorityAnchor"
    width: 230
    height: 270
    voiceState: ({
        "playback_id": "ar6-authority",
        "voice_anchor_state": "idle",
        "voice_current_phase": "idle",
        "speaking_visual_active": false,
        "active_playback_status": "playing",
        "voice_visual_available": true,
        "voice_visual_active": false,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.0,
        "voice_visual_playback_id": "ar6-authority",
        "voice_visual_latest_age_ms": 6
    })
    voiceVisualState: ({
        "authoritativeVoiceStateVersion": "AR6",
        "activePlaybackId": "ar6-authority",
        "activePlaybackStatus": "playing",
        "authoritativePlaybackId": "ar6-authority",
        "authoritativePlaybackStatus": "playing",
        "authoritativeVoiceVisualActive": true,
        "authoritativeVoiceVisualEnergy": 0.74,
        "authoritativeStateSequence": 44,
        "authoritativeStateSource": "pcm_stream_meter",
        "playback_id": "ar6-authority",
        "voice_visual_playback_id": "ar6-authority",
        "voice_visual_available": true,
        "voice_visual_active": true,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.74,
        "voice_visual_latest_age_ms": 5,
        "speaking_visual_active": true,
        "staleBroadSnapshotIgnored": true,
        "raw_audio_present": false
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorAR6AuthorityHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert anchor is not None

        for frame in range(1, 18):
            anchor.setProperty("visualClockWallTimeMs", 1000 + frame * 16)
            anchor.setProperty("visualClockDeltaMs", 16)
            anchor.setProperty("visualClockFrameCounter", frame)
            app.processEvents()

        assert anchor.property("authoritativeVoiceStateVersion") == "AR6"
        assert int(anchor.property("authoritativeStateSequence")) == 44
        assert anchor.property("qmlReceivedPlaybackId") == "ar6-authority"
        assert anchor.property("qmlReceivedVoiceVisualSource") == "pcm_stream_meter"
        assert bool(anchor.property("qmlVoiceVisualActive")) is True
        assert float(anchor.property("qmlReceivedVoiceVisualEnergy")) == pytest.approx(0.74)
        assert anchor.property("resolvedState") == "speaking"
        assert float(anchor.property("finalSpeakingEnergy")) > 0.20
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_ar6_releases_on_authoritative_terminal_state() -> None:
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
    objectName: "ar6ReleaseAnchor"
    width: 230
    height: 270
    voiceVisualState: ({
        "authoritativeVoiceStateVersion": "AR6",
        "activePlaybackId": "ar6-release",
        "activePlaybackStatus": "playing",
        "authoritativePlaybackId": "ar6-release",
        "authoritativePlaybackStatus": "playing",
        "authoritativeVoiceVisualActive": true,
        "authoritativeVoiceVisualEnergy": 0.70,
        "authoritativeStateSequence": 10,
        "authoritativeStateSource": "pcm_stream_meter",
        "playback_id": "ar6-release",
        "voice_visual_active": true,
        "voice_visual_available": true,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.70,
        "voice_visual_latest_age_ms": 3,
        "speaking_visual_active": true
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorAR6ReleaseHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert anchor is not None

        for frame in range(1, 12):
            anchor.setProperty("visualClockWallTimeMs", 1000 + frame * 16)
            anchor.setProperty("visualClockDeltaMs", 16)
            anchor.setProperty("visualClockFrameCounter", frame)
            app.processEvents()
        assert anchor.property("resolvedState") == "speaking"

        anchor.setProperty(
            "voiceVisualState",
            {
                "authoritativeVoiceStateVersion": "AR6",
                "activePlaybackId": "",
                "activePlaybackStatus": "completed",
                "authoritativePlaybackId": "ar6-release",
                "authoritativePlaybackStatus": "completed",
                "authoritativeVoiceVisualActive": False,
                "authoritativeVoiceVisualEnergy": 0.0,
                "authoritativeStateSequence": 11,
                "authoritativeStateSource": "pcm_stream_meter",
                "playback_id": "ar6-release",
                "voice_visual_playback_id": "ar6-release",
                "voice_visual_active": False,
                "voice_visual_available": True,
                "voice_visual_source": "pcm_stream_meter",
                "voice_visual_energy": 0.0,
                "voice_visual_latest_age_ms": 4,
                "speaking_visual_active": False,
                "speakingExitedReason": "terminal_completed",
                "releaseTailMs": 700,
                "raw_audio_present": False,
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(900)
        app.processEvents()

        assert bool(anchor.property("qmlVoiceVisualActive")) is False
        assert anchor.property("voicePlaybackStatus") == "completed"
        assert anchor.property("resolvedState") in {"idle", "ready"}
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_ar2_enters_speaking_from_pcm_meter_active() -> None:
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
    objectName: "ar2PromptEntryAnchor"
    width: 230
    height: 270
    voiceState: ({
        "voice_anchor_state": "idle",
        "voice_current_phase": "idle",
        "speaking_visual_active": false,
        "active_playback_status": "requested",
        "voice_visual_available": true,
        "voice_visual_active": true,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.68,
        "voice_visual_playback_id": "ar2-entry",
        "voice_visual_latest_age_ms": 4
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorAR2PromptEntryHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("rawDerivedVisualState") == "speaking"
        assert bool(anchor.property("anchorSpeakingVisualActive")) is True
        assert anchor.property("qmlSpeakingEnergySource") == "pcm_stream_meter"
        assert float(anchor.property("anchorSpeakingStartDelayMs")) < 250.0
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_ar2_pcm_meter_energy_has_meaningful_range_and_release() -> None:
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
    objectName: "ar2EnergyRangeAnchor"
    width: 230
    height: 270
}
""".strip()

    active_state = {
        "voice_anchor_state": "idle",
        "voice_current_phase": "idle",
        "speaking_visual_active": False,
        "active_playback_status": "playing",
        "voice_visual_available": True,
        "voice_visual_active": True,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.92,
        "voice_visual_playback_id": "ar2-range",
        "voice_visual_latest_age_ms": 4,
    }
    inactive_state = {
        **active_state,
        "active_playback_status": "completed",
        "voice_visual_active": False,
        "voice_visual_energy": 0.0,
    }

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorAR2EnergyRangeHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert anchor is not None

        anchor.setProperty("voiceState", active_state)
        for frame in range(1, 25):
            anchor.setProperty("visualClockWallTimeMs", 1000 + frame * 16)
            anchor.setProperty("visualClockDeltaMs", 16)
            anchor.setProperty("visualClockFrameCounter", frame)
            app.processEvents()

        assert float(anchor.property("targetVoiceVisualEnergy")) == pytest.approx(0.92)
        assert float(anchor.property("finalSpeakingEnergy")) > 0.25
        assert float(anchor.property("finalEnergyCompressionRatio")) > 0.25
        assert anchor.property("finalSpeakingEnergyClampReason") == ""
        assert bool(anchor.property("localSpeakingFrameClockActive")) is True
        assert anchor.property("effectiveAnchorRenderer") == "legacy_blob_reference"
        assert anchor.property("anchorRendererArchitectureVersion") == "Voice-AR4-legacy-blob-reference"
        assert anchor.property("anchorRendererArchitecture") == "legacy_blob_reference_canvas"
        assert bool(anchor.property("staticFrameLayerEnabled")) is False
        assert bool(anchor.property("dynamicCoreLayerEnabled")) is False
        assert bool(anchor.property("fullFrameVoiceCanvasRepaintDisabled")) is False
        assert float(anchor.property("blobScaleDrive")) > 0.20
        assert float(anchor.property("blobDeformationDrive")) > 0.14
        assert float(anchor.property("blobRadiusScale")) > 1.04
        assert float(anchor.property("radianceDrive")) > 0.20
        assert float(anchor.property("ringDrive")) > 0.25
        assert float(anchor.property("visualAmplitudeCompressionRatio")) > 0.20

        mid_speech_silence_state = {
            **active_state,
            "voice_visual_active": False,
            "voice_visual_energy": 0.0,
            "active_playback_status": "playing",
        }
        anchor.setProperty("voiceState", mid_speech_silence_state)
        for frame in range(25, 38):
            anchor.setProperty("visualClockWallTimeMs", 1000 + frame * 16)
            anchor.setProperty("visualClockDeltaMs", 16)
            anchor.setProperty("visualClockFrameCounter", frame)
            app.processEvents()

        assert anchor.property("anchorCurrentVisualState") == "speaking"
        assert bool(anchor.property("anchorSpeakingVisualActive")) is True

        anchor.setProperty("voiceState", inactive_state)
        for frame in range(38, 108):
            anchor.setProperty("visualClockWallTimeMs", 1000 + frame * 16)
            anchor.setProperty("visualClockDeltaMs", 16)
            anchor.setProperty("visualClockFrameCounter", frame)
            app.processEvents()

        assert bool(anchor.property("anchorSpeakingVisualActive")) is False
        assert float(anchor.property("finalSpeakingEnergy")) < 0.02
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_ar3_renderer_split_keeps_voice_frames_off_static_canvas() -> None:
    workspace_config = load_config(project_root=Path.cwd(), env={})
    core_source = (
        workspace_config.runtime.assets_dir
        / "qml"
        / "variants"
        / "stormforge"
        / "StormforgeAnchorCore.qml"
    ).read_text(encoding="utf-8")
    frame_source = (
        workspace_config.runtime.assets_dir
        / "qml"
        / "variants"
        / "stormforge"
        / "StormforgeAnchorFrame.qml"
    ).read_text(encoding="utf-8")
    dynamic_source = (
        workspace_config.runtime.assets_dir
        / "qml"
        / "variants"
        / "stormforge"
        / "StormforgeAnchorDynamicCore.qml"
    ).read_text(encoding="utf-8")

    request_body = core_source.split("function requestAnchorPaint()", 1)[1].split("function flushAnchorPaint()", 1)[0]
    flush_body = core_source.split("function flushAnchorPaint()", 1)[1].split("function requestStaticFramePaint()", 1)[0]

    assert "StormforgeAnchorFrame" in core_source
    assert "StormforgeAnchorDynamicCore" in core_source
    assert 'property string anchorRenderer: "legacy_blob_reference"' in core_source
    assert "visible: root.legacyBlobRendererActive" in core_source
    assert "visible: root.ar3SplitRendererActive" in core_source
    assert "anchorFrameLayer.requestFramePaint()" not in request_body
    assert "anchorFrameLayer.requestFramePaint()" not in flush_body
    assert "anchorDynamicLayer.requestDynamicPaint()" in flush_body
    assert "anchorCanvas.requestPaint()" in flush_body
    assert 'rendererRole: "stormforge_anchor_static_frame"' in frame_source
    assert 'rendererRole: "stormforge_anchor_dynamic_core_shape_renderer"' in dynamic_source
    assert "canvasFreeDynamicRenderer: true" in dynamic_source
    assert "blobScaleDrive" in dynamic_source
    assert "blobDeformationDrive" in dynamic_source
    assert "radianceDrive" in dynamic_source


def test_stormforge_anchor_ar4_defaults_to_legacy_blob_reference_renderer() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)
    component.setData(
        b"""
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {
    objectName: "legacyBlobDefaultAnchor"
    width: 230
    height: 270
    voiceVisualState: ({
        "voice_visual_available": true,
        "voice_visual_active": true,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.80,
        "voice_visual_playback_id": "ar3r-default",
        "voice_visual_latest_age_ms": 1,
        "active_playback_status": "playing"
    })
}
""",
        QtCore.QUrl.fromLocalFile(str(workspace_config.runtime.assets_dir / "qml" / "AR3RDefaultRenderer.qml")),
    )
    root = component.create()
    try:
        assert root is not None, [error.toString() for error in component.errors()]
        for frame in range(1, 14):
            root.setProperty("visualClockWallTimeMs", 1000 + frame * 16)
            root.setProperty("visualClockDeltaMs", 16)
            root.setProperty("visualClockFrameCounter", frame)
            app.processEvents()

        assert root.property("effectiveAnchorRenderer") == "legacy_blob_reference"
        assert root.property("anchorRendererArchitecture") == "legacy_blob_reference_canvas"
        assert bool(root.property("staticFrameLayerEnabled")) is False
        assert bool(root.property("dynamicCoreLayerEnabled")) is False
        assert bool(root.property("fullFrameVoiceCanvasRepaintDisabled")) is False
        assert float(root.property("blobScaleDrive")) > 0.20
        assert float(root.property("blobDeformationDrive")) > 0.14
        assert float(root.property("radianceDrive")) > 0.20
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_ar4_fast_candidate_uses_legacy_blob_canvas() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)
    component.setData(
        b"""
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {
    objectName: "legacyBlobFastCandidateAnchor"
    width: 230
    height: 270
    anchorRenderer: "legacy_blob_fast_candidate"
    voiceVisualState: ({
        "voice_visual_available": true,
        "voice_visual_active": true,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.80,
        "voice_visual_playback_id": "ar4-fast-candidate",
        "voice_visual_latest_age_ms": 1,
        "active_playback_status": "playing"
    })
}
""",
        QtCore.QUrl.fromLocalFile(str(workspace_config.runtime.assets_dir / "qml" / "AR4FastCandidateRenderer.qml")),
    )
    root = component.create()
    try:
        assert root is not None, [error.toString() for error in component.errors()]
        for frame in range(1, 14):
            root.setProperty("visualClockWallTimeMs", 1000 + frame * 16)
            root.setProperty("visualClockDeltaMs", 16)
            root.setProperty("visualClockFrameCounter", frame)
            app.processEvents()

        assert root.property("effectiveAnchorRenderer") == "legacy_blob_fast_candidate"
        assert root.property("anchorRendererArchitecture") == "legacy_blob_fast_candidate_canvas"
        assert bool(root.property("legacyBlobFastCandidateActive")) is True
        assert bool(root.property("legacyBlobRendererActive")) is True
        assert bool(root.property("ar3SplitRendererActive")) is False
        assert bool(root.property("staticFrameLayerEnabled")) is False
        assert bool(root.property("dynamicCoreLayerEnabled")) is False
        assert bool(root.property("fullFrameVoiceCanvasRepaintDisabled")) is False
        assert float(root.property("blobScaleDrive")) > 0.20
        assert float(root.property("blobDeformationDrive")) > 0.14
        assert float(root.property("radianceDrive")) > 0.20
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_ar5_qsg_candidate_uses_split_scenegraph_path() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)
    component.setData(
        b"""
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {
    objectName: "legacyBlobQsgCandidateAnchor"
    width: 230
    height: 270
    anchorRenderer: "legacy_blob_qsg_candidate"
    voiceVisualState: ({
        "authoritativeVoiceStateVersion": "AR6",
        "authoritativePlaybackId": "ar5-qsg-candidate",
        "authoritativePlaybackStatus": "playing",
        "authoritativeVoiceVisualActive": true,
        "authoritativeVoiceVisualEnergy": 0.86,
        "authoritativeStateSource": "pcm_stream_meter",
        "voice_visual_available": true,
        "voice_visual_active": false,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.0,
        "voice_visual_playback_id": "ar5-qsg-candidate",
        "voice_visual_latest_age_ms": 1,
        "active_playback_status": "playing"
    })
}
""",
        QtCore.QUrl.fromLocalFile(str(workspace_config.runtime.assets_dir / "qml" / "AR5QsgCandidateRenderer.qml")),
    )
    root = component.create()
    try:
        assert root is not None, [error.toString() for error in component.errors()]
        for frame in range(1, 18):
            root.setProperty("visualClockWallTimeMs", 1000 + frame * 16)
            root.setProperty("visualClockDeltaMs", 16)
            root.setProperty("visualClockFrameCounter", frame)
            app.processEvents()

        assert root.property("effectiveAnchorRenderer") == "legacy_blob_qsg_candidate"
        assert root.property("anchorRendererArchitecture") == "legacy_blob_qsg_candidate_cached_frame_qsg_dynamic"
        assert root.property("authoritativeVoiceStateVersion") == "AR6"
        assert bool(root.property("voiceVisualActive")) is True
        assert float(root.property("voiceVisualEnergy")) == pytest.approx(0.86)
        assert bool(root.property("legacyBlobRendererActive")) is False
        assert bool(root.property("qsgCandidateRendererActive")) is True
        assert bool(root.property("staticFrameLayerEnabled")) is True
        assert bool(root.property("dynamicCoreLayerEnabled")) is True
        assert bool(root.property("fullFrameVoiceCanvasRepaintDisabled")) is True
        assert root.property("currentAnchorPlaybackId") == "ar5-qsg-candidate"
        assert root.property("anchorAcceptedPlaybackId") == "ar5-qsg-candidate"
        assert root.property("anchorSpeakingEntryPlaybackId") == "ar5-qsg-candidate"
        assert root.property("finalSpeakingEnergyPlaybackId") == "ar5-qsg-candidate"
        assert root.property("blobDrivePlaybackId") == "ar5-qsg-candidate"
        assert root.property("qsgReflectionParityVersion") == "AR10"
        assert root.property("qsgReflectionShape") == "legacy_glint"
        assert bool(root.property("qsgReflectionRoundedRectDisabled")) is True
        assert bool(root.property("qsgReflectionUsesLegacyGeometry")) is True
        assert bool(root.property("qsgReflectionAnimated")) is True
        assert bool(root.property("qsgReflectionClipInsideBlob")) is True
        assert abs(float(root.property("qsgReflectionOffsetX"))) > 0.001
        assert abs(float(root.property("qsgReflectionOffsetY"))) > 0.001
        assert float(root.property("qsgReflectionOpacity")) > 0.0
        assert float(root.property("qsgReflectionSoftness")) > 0.0
        assert root.property("qsgBlobEdgeFeatherVersion") == "AR10"
        assert bool(root.property("qsgBlobEdgeFeatherEnabled")) is True
        assert bool(root.property("qsgBlobEdgeFeatherMatchesLegacySoftness")) is True
        assert float(root.property("qsgBlobEdgeFeatherOpacity")) > 0.0
        assert float(root.property("blobScaleDrive")) > 0.25
        assert float(root.property("blobDeformationDrive")) > 0.16
        assert float(root.property("radianceDrive")) > 0.25
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_ar5_qsg_candidate_has_no_full_legacy_canvas_path() -> None:
    workspace_config = load_config(project_root=Path.cwd(), env={})
    stormforge_dir = workspace_config.runtime.assets_dir / "qml" / "variants" / "stormforge"
    core_source = (stormforge_dir / "StormforgeAnchorCore.qml").read_text(encoding="utf-8")
    qsg_source = (stormforge_dir / "StormforgeAnchorLegacyBlobQsgCore.qml").read_text(encoding="utf-8")

    flush_body = core_source.split("function flushAnchorPaint()", 1)[1].split("function requestStaticFramePaint()", 1)[0]
    assert "root.qsgCandidateRendererActive" in flush_body
    assert "anchorLegacyBlobQsgLayer.requestDynamicPaint()" in flush_body
    assert "Canvas" not in qsg_source
    assert "StormforgeAnchorDynamicCore" not in qsg_source
    assert 'rendererRole: "stormforge_anchor_legacy_blob_qsg_candidate"' in qsg_source
    assert "legacyBlobCloneRenderer: true" in qsg_source
    assert 'officialLegacyBlobReferenceSource: "legacy_blob_reference_center_aperture"' in qsg_source
    assert "canvasFreeDynamicRenderer: true" in qsg_source
    assert "qsgRendererPlaybackId" in qsg_source
    assert "qsgRendererPaintedPlaybackId" in qsg_source
    assert 'qsgReflectionParityVersion: "AR10"' in qsg_source
    assert 'qsgReflectionShape: "legacy_glint"' in qsg_source
    assert "qsgReflectionRoundedRectDisabled: true" in qsg_source
    assert 'qsgBlobEdgeFeatherVersion: "AR10"' in qsg_source
    assert "qsgBlobEdgeFeatherEnabled: true" in qsg_source
    assert "legacyGlintArcPathString" in qsg_source
    assert "PathSvg" in qsg_source
    assert "width: root.blobRadiusPx * 0.56" not in qsg_source
    assert "height: root.blobRadiusPx * 0.18" not in qsg_source
    assert "blobPathString" in qsg_source
    assert "blobScaleDrive" in qsg_source
    assert "blobDeformationDrive" in qsg_source


def test_stormforge_anchor_voice_visual_active_holds_speaking_visual_state() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)
    component.setData(
        b"""
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {
    objectName: "voiceVisualHoldAnchor"
    width: 230
    height: 270
    anchorRenderer: "legacy_blob_reference"
    visualizerDiagnosticMode: "pcm_stream_meter"
    voiceVisualState: ({
        "voice_visual_available": true,
        "voice_visual_active": true,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": 0.74,
        "voice_visual_playback_id": "voice-visual-hold",
        "voice_visual_latest_age_ms": 8
    })
}
""",
        QtCore.QUrl.fromLocalFile(str(workspace_config.runtime.assets_dir / "qml" / "VoiceVisualHold.qml")),
    )
    root = component.create()
    try:
        assert root is not None, [error.toString() for error in component.errors()]
        for _ in range(8):
            app.processEvents()

        assert bool(root.property("visualSpeakingActive")) is True
        assert root.property("visualState") == "speaking"

        root.setProperty("visualState", "idle")
        root.setProperty("latchedVisualState", "idle")
        root.setProperty("visualSpeakingActive", True)
        root.advanceAnimationFrame(16, 1000)
        for _ in range(8):
            app.processEvents()

        assert root.property("latchedVisualState") == "speaking"
        assert root.property("visualState") == "speaking"
    finally:
        _dispose_qt_objects(app, engine, root)


def test_stormforge_anchor_ar3r_keeps_ar3_split_renderer_available() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)
    component.setData(
        b"""
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {
    objectName: "ar3SplitRendererAnchor"
    width: 230
    height: 270
    anchorRenderer: "ar3_split"
}
""",
        QtCore.QUrl.fromLocalFile(str(workspace_config.runtime.assets_dir / "qml" / "AR3RSplitRenderer.qml")),
    )
    root = component.create()
    try:
        assert root is not None, [error.toString() for error in component.errors()]
        assert root.property("effectiveAnchorRenderer") == "ar3_split"
        assert root.property("anchorRendererArchitecture") == "static_nautical_frame_cached_dynamic_voice_core"
        assert bool(root.property("staticFrameLayerEnabled")) is True
        assert bool(root.property("dynamicCoreLayerEnabled")) is True
        assert bool(root.property("fullFrameVoiceCanvasRepaintDisabled")) is True
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_l02_uses_procedural_fallback_only_when_envelope_unavailable() -> None:
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
    objectName: "fallbackEnvelopeAnchor"
    width: 230
    height: 270
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "playback_envelope_available": false,
        "playback_envelope_supported": false,
        "playback_envelope_fallback_reason": "pcm_unavailable_for_mci_file",
        "voice_audio_reactive_available": false,
        "voice_audio_reactive_source": "unavailable"
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL02FallbackEnvelopeHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(220)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("playbackEnvelopeVersion") == "Voice-L0.2.1"
        assert bool(anchor.property("playbackEnvelopeAvailable")) is False
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is False
        assert bool(anchor.property("proceduralFallbackActive")) is True
        assert anchor.property("envelopeFallbackReason") == "pcm_unavailable_for_mci_file"
        assert float(anchor.property("finalSpeakingEnergy")) > 0.0

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "",
                "voice_current_phase": "idle",
                "speaking_visual_active": False,
                "active_playback_status": "idle",
                "playback_envelope_available": False,
                "playback_envelope_supported": False,
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(
            int(anchor.property("speakingLatchMs"))
            + int(anchor.property("stateMinimumDwellMs"))
            + 320
        )
        app.processEvents()

        assert bool(anchor.property("proceduralFallbackActive")) is False
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_l021_falls_back_when_envelope_is_empty_or_stale() -> None:
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
    objectName: "staleEnvelopeFallbackAnchor"
    width: 230
    height: 270
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "playback_envelope_available": true,
        "playback_envelope_supported": true,
        "playback_envelope_source": "playback_pcm",
        "playback_envelope_energy": 0.0,
        "playback_envelope_sample_rate_hz": 60,
        "playback_envelope_sample_age_ms": 900,
        "playback_envelope_samples_recent": [],
        "voice_audio_reactive_available": false,
        "voice_audio_reactive_source": "unavailable"
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL021StaleEnvelopeFallbackHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("playbackEnvelopeVersion") == "Voice-L0.2.1"
        assert bool(anchor.property("qmlPlaybackEnvelopeSupported")) is True
        assert bool(anchor.property("qmlPlaybackEnvelopeAvailable")) is True
        assert bool(anchor.property("qmlPlaybackEnvelopeUsable")) is False
        assert int(anchor.property("qmlPlaybackEnvelopeSampleCount")) == 0
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is False
        assert bool(anchor.property("proceduralFallbackActive")) is True
        assert anchor.property("qmlSpeakingEnergySource") == "procedural_fallback"
        assert anchor.property("proceduralFallbackReason") == "playback_envelope_empty"
        assert bool(anchor.property("envelopeUnavailableFallbackWorks")) is True
        assert bool(anchor.property("finalSpeakingEnergyNonZeroDuringFallback")) is True
        assert float(anchor.property("qmlFinalSpeakingEnergy")) > 0.04
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_l021_quiet_playback_envelope_still_has_visible_speaking_motion() -> None:
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
    objectName: "quietPlaybackEnvelopeAnchor"
    width: 230
    height: 270
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_center_blob_scale_drive": 0.0,
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "playback_pcm",
        "playback_envelope_supported": true,
        "playback_envelope_available": true,
        "playback_envelope_usable": true,
        "playback_envelope_source": "playback_pcm",
        "playback_envelope_energy": 0.18,
        "playback_envelope_sample_rate_hz": 60,
        "playback_envelope_latency_ms": 80,
        "playback_envelope_sample_age_ms": 10,
        "playback_envelope_sample_count": 8,
        "playback_envelope_window_mode": "playback_time",
        "playback_envelope_query_time_ms": 316,
        "playback_visual_time_ms": 316,
        "playback_envelope_samples_recent": [
            {"sample_time_ms": 300, "smoothed_energy": 0.14, "energy": 0.16, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 316, "smoothed_energy": 0.16, "energy": 0.18, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 333, "smoothed_energy": 0.18, "energy": 0.20, "source": "pcm_playback", "valid": true}
        ]
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL021QuietEnvelopeHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(460)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("playbackEnvelopeVersion") == "Voice-L0.2.1"
        assert anchor.property("playbackEnvelopeVisualDriveVersion") == "Voice-L0.2.1A"
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is True
        assert bool(anchor.property("proceduralFallbackActive")) is False
        assert bool(anchor.property("envelopeBackedProceduralBaseEnabled")) is True
        assert anchor.property("qmlSpeakingEnergySource") == "playback_envelope"
        assert float(anchor.property("playbackEnvelopeEnergy")) > 0.10
        assert float(anchor.property("playbackEnvelopeVisualDrive")) > float(anchor.property("playbackEnvelopeEnergy"))
        assert float(anchor.property("proceduralSpeechEnergy")) > 0.0
        assert float(anchor.property("qmlFinalSpeakingEnergy")) > 0.20
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_l03_expands_quiet_playback_envelope_dynamics() -> None:
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
    objectName: "quietEnvelopeDynamicsAnchor"
    width: 230
    height: 270
}
""".strip()

    def voice_state(energy: float, sample_time_ms: int) -> dict:
        return {
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": True,
            "active_playback_status": "playing",
            "voice_center_blob_scale_drive": 0.0,
            "voice_audio_reactive_available": True,
            "voice_audio_reactive_source": "playback_pcm",
            "playback_envelope_supported": True,
            "playback_envelope_available": True,
            "playback_envelope_usable": True,
            "playback_envelope_source": "playback_pcm",
            "playback_envelope_energy": energy,
            "playback_envelope_sample_rate_hz": 60,
            "playback_envelope_latency_ms": 80,
            "playback_envelope_sample_age_ms": 8,
            "playback_envelope_sample_count": 8,
            "playback_envelope_window_mode": "playback_time",
            "playback_envelope_query_time_ms": sample_time_ms,
            "playback_visual_time_ms": sample_time_ms,
            "playback_envelope_samples_recent": [
                {
                    "sample_time_ms": sample_time_ms - 33,
                    "smoothed_energy": max(0.0, energy - 0.008),
                    "energy": max(0.0, energy - 0.004),
                    "source": "pcm_playback",
                    "valid": True,
                },
                {
                    "sample_time_ms": sample_time_ms - 16,
                    "smoothed_energy": energy,
                    "energy": energy,
                    "source": "pcm_playback",
                    "valid": True,
                },
                {
                    "sample_time_ms": sample_time_ms,
                    "smoothed_energy": energy,
                    "energy": energy,
                    "source": "pcm_playback",
                    "valid": True,
                },
            ],
        }

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL03QuietEnvelopeDynamicsHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert anchor is not None

        anchor.setProperty("voiceState", voice_state(0.14, 300))
        app.processEvents()
        QtTest.QTest.qWait(220)
        app.processEvents()
        low_final = float(anchor.property("finalSpeakingEnergy"))

        anchor.setProperty("voiceState", voice_state(0.18, 520))
        app.processEvents()
        QtTest.QTest.qWait(220)
        app.processEvents()
        high_final = float(anchor.property("finalSpeakingEnergy"))
        high_expanded = float(anchor.property("envelopeExpandedEnergy"))

        anchor.setProperty("voiceState", voice_state(0.145, 760))
        app.processEvents()
        QtTest.QTest.qWait(220)
        app.processEvents()
        low_again_final = float(anchor.property("finalSpeakingEnergy"))

        assert anchor.property("envelopeDynamicsVersion") == "Voice-L0.3"
        assert bool(anchor.property("envelopeDrivesVisualDynamics")) is True
        assert bool(anchor.property("speakingPlateauSuppressionEnabled")) is True
        assert bool(anchor.property("centerUniformSpeakingScaleDisabled")) is True
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is True
        assert 0.13 <= float(anchor.property("envelopeRecentMin")) <= 0.15
        assert float(anchor.property("envelopeRecentMax")) >= 0.17
        assert float(anchor.property("envelopeDynamicRange")) >= 0.025
        assert high_expanded >= 0.24
        assert high_final > low_final + 0.045
        assert high_final > low_again_final + 0.030
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_l03_flat_envelope_does_not_create_fake_strong_dynamics() -> None:
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
    objectName: "flatEnvelopeDynamicsAnchor"
    width: 230
    height: 270
}
""".strip()

    def flat_state(sample_time_ms: int) -> dict:
        return {
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": True,
            "active_playback_status": "playing",
            "voice_audio_reactive_available": True,
            "voice_audio_reactive_source": "playback_pcm",
            "playback_envelope_supported": True,
            "playback_envelope_available": True,
            "playback_envelope_usable": True,
            "playback_envelope_source": "playback_pcm",
            "playback_envelope_energy": 0.16,
            "playback_envelope_sample_rate_hz": 60,
            "playback_envelope_latency_ms": 80,
            "playback_envelope_sample_age_ms": 6,
            "playback_envelope_sample_count": 8,
            "playback_envelope_window_mode": "playback_time",
            "playback_envelope_query_time_ms": sample_time_ms,
            "playback_visual_time_ms": sample_time_ms,
            "playback_envelope_samples_recent": [
                {"sample_time_ms": sample_time_ms - 33, "smoothed_energy": 0.16, "energy": 0.16, "source": "pcm_playback", "valid": True},
                {"sample_time_ms": sample_time_ms - 16, "smoothed_energy": 0.16, "energy": 0.16, "source": "pcm_playback", "valid": True},
                {"sample_time_ms": sample_time_ms, "smoothed_energy": 0.16, "energy": 0.16, "source": "pcm_playback", "valid": True},
            ],
        }

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL03FlatEnvelopeHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert anchor is not None

        for index in range(5):
            anchor.setProperty("voiceState", flat_state(300 + index * 180))
            app.processEvents()
            QtTest.QTest.qWait(140)
            app.processEvents()

        assert anchor.property("envelopeDynamicsVersion") == "Voice-L0.3"
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is True
        assert float(anchor.property("envelopeDynamicRange")) <= 0.012
        assert float(anchor.property("envelopeExpandedEnergy")) <= 0.12
        assert float(anchor.property("envelopeTransientEnergy")) <= 0.10
        assert float(anchor.property("finalSpeakingEnergy")) < 0.36
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_l04_uses_fallback_for_unaligned_pcm_tail() -> None:
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
    objectName: "unalignedEnvelopeTailAnchor"
    width: 230
    height: 270
    voiceState: ({
        "playback_id": "playback-tail-cache",
        "active_playback_stream_id": "playback-tail-cache",
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "stormhelm_playback_meter",
        "playback_envelope_supported": true,
        "playback_envelope_available": true,
        "playback_envelope_usable": true,
        "playback_envelope_source": "playback_pcm",
        "playback_envelope_energy": 0.011,
        "playback_envelope_sample_rate_hz": 60,
        "playback_envelope_latency_ms": 80,
        "playback_envelope_sample_age_ms": 0,
        "playback_envelope_sample_count": 8,
        "playback_envelope_window_mode": "latest",
        "latest_voice_energy_time_ms": 7233,
        "playback_envelope_samples_recent": [
            {"sample_time_ms": 7120, "smoothed_energy": 0.011, "energy": 0.012, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 7136, "smoothed_energy": 0.011, "energy": 0.012, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 7152, "smoothed_energy": 0.011, "energy": 0.012, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 7168, "smoothed_energy": 0.011, "energy": 0.012, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 7184, "smoothed_energy": 0.011, "energy": 0.012, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 7200, "smoothed_energy": 0.011, "energy": 0.012, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 7216, "smoothed_energy": 0.011, "energy": 0.012, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 7233, "smoothed_energy": 0.011, "energy": 0.012, "source": "pcm_playback", "valid": true}
        ]
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL04UnalignedTailHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("sourceLatchVersion") == "Voice-L0.4"
        assert bool(anchor.property("playbackEnvelopeAvailable")) is True
        assert bool(anchor.property("playbackEnvelopeUsable")) is False
        assert bool(anchor.property("playbackEnvelopeTimebaseAligned")) is False
        assert anchor.property("playbackEnvelopeUsableReason") == "playback_envelope_unaligned"
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is False
        assert bool(anchor.property("proceduralFallbackActive")) is True
        assert anchor.property("qmlSpeakingEnergySource") == "procedural_fallback"
        assert float(anchor.property("finalSpeakingEnergy")) > 0.04
        assert anchor.property("resolvedSublabel") == "Stormhelm voice motion"
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_l04_crossfades_aligned_envelope_without_source_flap() -> None:
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
    objectName: "sourceLatchAnchor"
    width: 230
    height: 270
}
""".strip()

    def unaligned_state() -> dict:
        return {
            "playback_id": "playback-l04",
            "active_playback_stream_id": "playback-l04",
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": True,
            "active_playback_status": "playing",
            "voice_audio_reactive_available": True,
            "voice_audio_reactive_source": "stormhelm_playback_meter",
            "playback_envelope_supported": True,
            "playback_envelope_available": True,
            "playback_envelope_usable": True,
            "playback_envelope_source": "playback_pcm",
            "playback_envelope_energy": 0.011,
            "playback_envelope_sample_age_ms": 0,
            "playback_envelope_sample_count": 8,
            "playback_envelope_window_mode": "latest",
            "latest_voice_energy_time_ms": 7233,
            "playback_envelope_samples_recent": [
                {"sample_time_ms": 7200 + index * 16, "smoothed_energy": 0.011, "energy": 0.012, "source": "pcm_playback", "valid": True}
                for index in range(8)
            ],
        }

    def aligned_state(query_ms: int, energy: float) -> dict:
        return {
            "playback_id": "playback-l04",
            "active_playback_stream_id": "playback-l04",
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": True,
            "active_playback_status": "playing",
            "voice_audio_reactive_available": True,
            "voice_audio_reactive_source": "playback_pcm",
            "playback_envelope_supported": True,
            "playback_envelope_available": True,
            "playback_envelope_usable": True,
            "playback_envelope_source": "playback_pcm",
            "playback_envelope_energy": energy,
            "playback_envelope_sample_rate_hz": 60,
            "playback_envelope_latency_ms": 80,
            "playback_envelope_sample_age_ms": 8,
            "playback_envelope_sample_count": 8,
            "playback_envelope_window_mode": "playback_time",
            "playback_envelope_query_time_ms": query_ms,
            "playback_visual_time_ms": query_ms,
            "latest_voice_energy_time_ms": query_ms,
            "playback_envelope_samples_recent": [
                {"sample_time_ms": query_ms - 48, "smoothed_energy": max(0.0, energy - 0.04), "energy": max(0.0, energy - 0.03), "source": "pcm_playback", "valid": True},
                {"sample_time_ms": query_ms - 32, "smoothed_energy": max(0.0, energy - 0.02), "energy": max(0.0, energy - 0.01), "source": "pcm_playback", "valid": True},
                {"sample_time_ms": query_ms - 16, "smoothed_energy": energy, "energy": energy, "source": "pcm_playback", "valid": True},
                {"sample_time_ms": query_ms, "smoothed_energy": energy, "energy": energy, "source": "pcm_playback", "valid": True},
            ],
        }

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL04SourceLatchHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert anchor is not None

        anchor.setProperty("voiceState", unaligned_state())
        app.processEvents()
        QtTest.QTest.qWait(220)
        app.processEvents()
        fallback_energy = float(anchor.property("finalSpeakingEnergy"))

        anchor.setProperty("voiceState", aligned_state(220, 0.18))
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()
        blended_energy = float(anchor.property("finalSpeakingEnergy"))

        anchor.setProperty("voiceState", aligned_state(480, 0.24))
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert anchor.property("sourceLatchVersion") == "Voice-L0.4"
        assert bool(anchor.property("sourceFlapGuardEnabled")) is True
        assert int(anchor.property("speakingEnergySourceSwitchCount")) == 0
        assert int(anchor.property("visualizerSourceSwitchCount")) == 0
        assert anchor.property("visualizerSourceStrategy") == "procedural_speaking"
        assert bool(anchor.property("visualizerSourceLocked")) is True
        assert bool(anchor.property("playbackEnvelopeTimebaseAligned")) is True
        assert float(anchor.property("envelopeCrossfadeAlpha")) == pytest.approx(0.0)
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is False
        assert anchor.property("qmlSpeakingEnergySource") == "procedural_fallback"
        assert blended_energy >= fallback_energy - 0.025
        assert float(anchor.property("finalSpeakingEnergy")) > 0.04
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_l06_locks_procedural_when_envelope_timeline_is_late() -> None:
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
    objectName: "timelineSourceLockAnchor"
    width: 230
    height: 270
}
""".strip()

    def warming_state() -> dict:
        return {
            "playback_id": "playback-l06-procedural",
            "active_playback_stream_id": "playback-l06-procedural",
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": True,
            "active_playback_status": "playing",
            "voice_audio_reactive_available": True,
            "voice_audio_reactive_source": "stormhelm_playback_meter",
            "playback_envelope_supported": True,
            "playback_envelope_available": True,
            "playback_envelope_usable": False,
            "playback_envelope_source": "playback_pcm",
            "playback_envelope_sample_count": 0,
            "envelope_timeline_available": False,
            "visualizer_source_switching_disabled": True,
        }

    def late_timeline_state() -> dict:
        samples = [
            {"t_ms": 160 + index * 16, "energy": 0.18 + index * 0.02}
            for index in range(8)
        ]
        return {
            "playback_id": "playback-l06-procedural",
            "active_playback_stream_id": "playback-l06-procedural",
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": True,
            "active_playback_status": "playing",
            "voice_audio_reactive_available": True,
            "voice_audio_reactive_source": "playback_pcm",
            "playback_envelope_supported": True,
            "playback_envelope_available": True,
            "playback_envelope_usable": True,
            "playback_envelope_source": "playback_pcm",
            "playback_envelope_sample_rate_hz": 60,
            "playback_envelope_sample_age_ms": 8,
            "playback_envelope_sample_count": len(samples),
            "playback_visual_time_ms": 208,
            "playback_envelope_window_mode": "playback_time",
            "playback_envelope_query_time_ms": 208,
            "playback_envelope_samples_recent": [
                {"sample_time_ms": sample["t_ms"], "smoothed_energy": sample["energy"], "energy": sample["energy"], "source": "pcm_playback", "valid": True}
                for sample in samples
            ],
            "envelopeTimelineSamples": samples,
            "envelope_timeline_available": True,
            "visualizer_source_strategy": "playback_envelope_timeline",
            "visualizer_source_locked": True,
            "visualizer_source_switch_count": 0,
            "visualizer_source_switching_disabled": True,
        }

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL06TimelineSourceLockHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert anchor is not None

        anchor.setProperty("voiceState", warming_state())
        app.processEvents()
        QtTest.QTest.qWait(180)
        app.processEvents()
        fallback_energy = float(anchor.property("finalSpeakingEnergy"))

        anchor.setProperty("voiceState", late_timeline_state())
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert anchor.property("timelineVisualizerVersion") == "Voice-L0.6"
        assert anchor.property("visualizerSourceStrategy") == "procedural_speaking"
        assert bool(anchor.property("visualizerSourceLocked")) is True
        assert anchor.property("visualizerSourcePlaybackId") == "playback-l06-procedural"
        assert int(anchor.property("visualizerSourceSwitchCount")) == 0
        assert bool(anchor.property("visualizerSourceSwitchingDisabled")) is True
        assert anchor.property("qmlSpeakingEnergySource") == "procedural_fallback"
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is False
        assert anchor.property("resolvedSublabel") == "Stormhelm voice motion"
        assert float(anchor.property("finalSpeakingEnergy")) >= fallback_energy - 0.025
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_l06_uses_timeline_when_locked_from_start() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    samples = [
        {"t_ms": 160 + index * 16, "energy": 0.18 + index * 0.03}
        for index in range(8)
    ]
    harness_qml = f"""
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {{
    objectName: "timelineEnvelopeAnchor"
    width: 230
    height: 270
    voiceState: ({{
        "playback_id": "playback-l06-envelope",
        "active_playback_stream_id": "playback-l06-envelope",
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "playback_pcm",
        "playback_envelope_supported": true,
        "playback_envelope_available": true,
        "playback_envelope_usable": true,
        "playback_envelope_source": "playback_pcm",
        "playback_envelope_sample_rate_hz": 60,
        "playback_envelope_sample_age_ms": 6,
        "playback_envelope_sample_count": {len(samples)},
        "playback_visual_time_ms": 208,
        "playback_envelope_window_mode": "playback_time",
        "playback_envelope_query_time_ms": 208,
        "playback_envelope_samples_recent": [
            {{"sample_time_ms": 160, "smoothed_energy": 0.18, "energy": 0.18, "source": "pcm_playback", "valid": true}},
            {{"sample_time_ms": 176, "smoothed_energy": 0.21, "energy": 0.21, "source": "pcm_playback", "valid": true}},
            {{"sample_time_ms": 192, "smoothed_energy": 0.24, "energy": 0.24, "source": "pcm_playback", "valid": true}},
            {{"sample_time_ms": 208, "smoothed_energy": 0.34, "energy": 0.34, "source": "pcm_playback", "valid": true}}
        ],
        "envelopeTimelineSamples": {samples},
        "envelope_timeline_available": true,
        "visualizer_source_strategy": "playback_envelope_timeline",
        "visualizer_source_locked": true,
        "visualizer_source_playback_id": "playback-l06-envelope",
        "visualizer_source_switch_count": 0,
        "visualizer_source_switching_disabled": true
    }})
}}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL06TimelineEnvelopeHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("visualizerSourceStrategy") == "playback_envelope_timeline"
        assert anchor.property("qmlSpeakingEnergySource") == "playback_envelope"
        assert anchor.property("resolvedSublabel") == "Playback envelope"
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is True
        assert float(anchor.property("playbackEnvelopeEnergy")) > 0.18
        assert float(anchor.property("finalSpeakingEnergy")) > 0.08
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_live_iso_forced_visualizer_modes() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    speaking_state = """
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_audio_reactive_available": false,
        "voice_audio_reactive_source": "unavailable",
        "visualizer_source_strategy": "procedural_speaking",
        "visualizer_source_locked": true,
        "visualizer_source_switch_count": 0
    """.strip()
    harness_qml = f"""
import QtQuick 2.15
import "variants/stormforge"

Item {{
    width: 760
    height: 280

    StormforgeAnchorCore {{
        objectName: "visualizerOffAnchor"
        width: 230
        height: 270
        visualizerDiagnosticMode: "off"
        voiceState: ({{ {speaking_state} }})
    }}

    StormforgeAnchorCore {{
        objectName: "constantWaveAnchor"
        x: 250
        width: 230
        height: 270
        visualizerDiagnosticMode: "constant_test_wave"
        voiceState: ({{ {speaking_state} }})
    }}

    StormforgeAnchorCore {{
        objectName: "missingTimelineAnchor"
        x: 500
        width: 230
        height: 270
        visualizerDiagnosticMode: "envelope_timeline"
        voiceState: ({{
            {speaking_state},
            "playback_envelope_supported": true,
            "playback_envelope_available": true,
            "playback_envelope_usable": false,
            "playback_envelope_source": "playback_pcm",
            "playback_envelope_samples_recent": []
        }})
    }}
}}
""".strip()

    root = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorLiveIsoModesHarness.qml"
                )
            ),
        )
        root = component.create()
        app.processEvents()
        QtTest.QTest.qWait(360)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        off_anchor = root.findChild(QtCore.QObject, "visualizerOffAnchor")
        wave_anchor = root.findChild(QtCore.QObject, "constantWaveAnchor")
        missing_anchor = root.findChild(QtCore.QObject, "missingTimelineAnchor")
        assert off_anchor is not None
        assert wave_anchor is not None
        assert missing_anchor is not None

        assert off_anchor.property("liveVoiceIsolationVersion") == "UI-VOICE-LIVE-ISO"
        assert off_anchor.property("effectiveAnchorVisualizerMode") == "off"
        assert bool(off_anchor.property("forcedVisualizerModeHonored")) is True
        assert off_anchor.property("visualizerStrategySelectedBy") == "qml_override"
        assert off_anchor.property("visualizerSourceStrategy") == "off"
        assert bool(off_anchor.property("anchorReactiveAnimationDisabledByMode")) is True
        assert off_anchor.property("qmlSpeakingEnergySource") == "none"
        assert float(off_anchor.property("qmlFinalSpeakingEnergy")) == pytest.approx(0.0, abs=0.025)

        assert wave_anchor.property("effectiveAnchorVisualizerMode") == "constant_test_wave"
        assert bool(wave_anchor.property("forcedVisualizerModeHonored")) is True
        assert wave_anchor.property("visualizerStrategySelectedBy") == "qml_override"
        assert wave_anchor.property("visualizerSourceStrategy") == "constant_test_wave"
        assert wave_anchor.property("qmlSpeakingEnergySource") == "constant_test_wave"
        assert bool(wave_anchor.property("anchorUsesPlaybackEnvelope")) is False
        assert float(wave_anchor.property("qmlFinalSpeakingEnergy")) > 0.08

        assert missing_anchor.property("effectiveAnchorVisualizerMode") == "envelope_timeline"
        assert bool(missing_anchor.property("forcedVisualizerModeHonored")) is True
        assert missing_anchor.property("visualizerStrategySelectedBy") == "qml_override"
        assert missing_anchor.property("visualizerSourceStrategy") == "playback_envelope_timeline"
        assert bool(missing_anchor.property("anchorVisualizerModeUnavailable")) is True
        assert missing_anchor.property("anchorVisualizerModeUnavailableReason") == "envelope_timeline_unavailable"
        assert missing_anchor.property("forcedVisualizerModeUnavailableReason") == "envelope_timeline_unavailable"
        assert missing_anchor.property("qmlSpeakingEnergySource") == "playback_envelope"
        assert float(missing_anchor.property("qmlFinalSpeakingEnergy")) == pytest.approx(0.0, abs=0.035)
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_fog_diagnostic_disable_during_speech() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeGhostShell {
    objectName: "fogDiagnosticSpeechShell"
    width: 820
    height: 620
    stormforgeFogConfig: ({
        "enabled": true,
        "mode": "volumetric",
        "quality": "medium",
        "diagnosticDisableDuringSpeech": true
    })
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing"
    })
}
""".strip()

    shell = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeFogLiveIsoDisableDuringSpeechHarness.qml"
                )
            ),
        )
        shell = component.create()
        app.processEvents()
        QtTest.QTest.qWait(180)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert shell is not None
        fog = shell.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")
        assert fog is not None
        assert bool(shell.property("stormforgeFogDiagnosticDisableDuringSpeech")) is True
        assert bool(shell.property("stormforgeFogDisabledDuringSpeech")) is True
        assert bool(fog.property("active")) is False

        shell.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "idle",
                "voice_current_phase": "idle",
                "speaking_visual_active": False,
                "active_playback_status": "idle",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(180)
        app.processEvents()

        assert bool(shell.property("stormforgeFogDisabledDuringSpeech")) is False
        assert bool(fog.property("active")) is True
    finally:
        _dispose_qt_objects(app, shell, engine)


def test_stormforge_anchor_l05_applies_latency_to_envelope_sample_time() -> None:
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
    objectName: "syncCalibratedAnchor"
    width: 230
    height: 270
    voiceState: ({
        "playback_id": "playback-l05",
        "active_playback_stream_id": "playback-l05",
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "playback_pcm",
        "playback_envelope_supported": true,
        "playback_envelope_available": true,
        "playback_envelope_usable": true,
        "playback_envelope_source": "playback_pcm",
        "playback_envelope_energy": 0.78,
        "playback_envelope_sample_rate_hz": 60,
        "playback_envelope_latency_ms": 100,
        "estimated_output_latency_ms": 100,
        "envelope_visual_offset_ms": 0,
        "playback_envelope_sample_age_ms": 4,
        "playback_envelope_sample_count": 4,
        "playback_visual_time_ms": 300,
        "playback_envelope_window_mode": "playback_time",
        "playback_envelope_query_time_ms": 200,
        "playback_envelope_latest_time_ms": 300,
        "playback_envelope_samples_recent": [
            {"sample_time_ms": 180, "smoothed_energy": 0.72, "energy": 0.72, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 200, "smoothed_energy": 0.78, "energy": 0.78, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 220, "smoothed_energy": 0.74, "energy": 0.74, "source": "pcm_playback", "valid": true},
            {"sample_time_ms": 300, "smoothed_energy": 0.08, "energy": 0.08, "source": "pcm_playback", "valid": true}
        ]
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL05SyncCalibrationHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("envelopeSyncCalibrationVersion") == "Voice-L0.5"
        assert float(anchor.property("qmlPlaybackVisualTimeMs")) == pytest.approx(300.0)
        assert float(anchor.property("qmlEnvelopeSampleTimeMs")) == pytest.approx(200.0)
        assert float(anchor.property("qmlEnvelopeTimeOffsetAppliedMs")) == pytest.approx(-100.0)
        assert float(anchor.property("qmlEstimatedOutputLatencyMs")) == pytest.approx(100.0)
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is True
        assert float(anchor.property("playbackEnvelopeEnergy")) > 0.25
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_l05_visual_offset_shifts_envelope_sample_time() -> None:
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
    objectName: "syncOffsetAnchor"
    width: 230
    height: 270
}
""".strip()

    def voice_state(offset_ms: int, query_ms: int) -> dict:
        return {
            "playback_id": "playback-l05-offset",
            "active_playback_stream_id": "playback-l05-offset",
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": True,
            "active_playback_status": "playing",
            "voice_audio_reactive_available": True,
            "voice_audio_reactive_source": "playback_pcm",
            "playback_envelope_supported": True,
            "playback_envelope_available": True,
            "playback_envelope_usable": True,
            "playback_envelope_source": "playback_pcm",
            "playback_envelope_energy": 0.24,
            "playback_envelope_sample_rate_hz": 60,
            "playback_envelope_latency_ms": 100,
            "estimated_output_latency_ms": 100,
            "envelope_visual_offset_ms": offset_ms,
            "playback_envelope_sample_age_ms": 4,
            "playback_envelope_sample_count": 5,
            "playback_visual_time_ms": 300,
            "playback_envelope_window_mode": "playback_time",
            "playback_envelope_query_time_ms": query_ms,
            "playback_envelope_samples_recent": [
                {"sample_time_ms": query_ms - 32, "smoothed_energy": 0.18, "energy": 0.18, "source": "pcm_playback", "valid": True},
                {"sample_time_ms": query_ms - 16, "smoothed_energy": 0.20, "energy": 0.20, "source": "pcm_playback", "valid": True},
                {"sample_time_ms": query_ms, "smoothed_energy": 0.24, "energy": 0.24, "source": "pcm_playback", "valid": True},
                {"sample_time_ms": query_ms + 16, "smoothed_energy": 0.22, "energy": 0.22, "source": "pcm_playback", "valid": True},
                {"sample_time_ms": query_ms + 32, "smoothed_energy": 0.20, "energy": 0.20, "source": "pcm_playback", "valid": True},
            ],
        }

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorL05OffsetHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        assert component.isReady(), component.errors()
        assert anchor is not None

        anchor.setProperty("voiceState", voice_state(0, 200))
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()
        assert float(anchor.property("qmlEnvelopeSampleTimeMs")) == pytest.approx(200.0)
        assert float(anchor.property("qmlEnvelopeTimeOffsetAppliedMs")) == pytest.approx(-100.0)

        anchor.setProperty("voiceState", voice_state(-40, 240))
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()
        assert float(anchor.property("qmlEnvelopeSampleTimeMs")) == pytest.approx(240.0)
        assert float(anchor.property("qmlEnvelopeTimeOffsetAppliedMs")) == pytest.approx(-60.0)

        anchor.setProperty("voiceState", voice_state(40, 160))
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()
        assert float(anchor.property("qmlEnvelopeSampleTimeMs")) == pytest.approx(160.0)
        assert float(anchor.property("qmlEnvelopeTimeOffsetAppliedMs")) == pytest.approx(-140.0)
        assert bool(anchor.property("visualSpeakingActive")) is True
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_p2a67_speaking_onset_smooths_startup_flicker() -> None:
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
    objectName: "speakingOnsetAnchor"
    width: 230
    height: 270
    state: ""
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorP2A67SpeakingOnsetHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(140)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("visualState") == "idle"

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "speaking",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 0.0,
                "voice_audio_level": 0.0,
                "voice_outer_speaking_motion": 0.0,
                "voice_audio_reactive_available": True,
                "voice_audio_reactive_source": "playback_output_envelope",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(96)
        app.processEvents()

        assert anchor.property("speakingOnsetStabilityVersion") == "UI-P2A.6.7"
        assert anchor.property("normalizedState") == "speaking"
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert bool(anchor.property("speakingOnsetGuardActive")) is True
        assert 1200 <= int(anchor.property("speakingOnsetGuardMs")) <= 1800
        assert 500 <= int(anchor.property("speakingAttackMs")) <= 800
        assert 600 <= int(anchor.property("speakingReleaseMs")) <= 1000
        assert anchor.property("speakingPhaseSource") == "continuous_time"
        assert bool(anchor.property("speakingPhaseResetOnUpdate")) is False
        assert bool(anchor.property("speakingDroppedToIdleDuringOnset")) is False
        assert float(anchor.property("speakingEnvelopeSmoothed")) >= 0.0

        phase_at_start = float(anchor.property("speakingPhase"))
        envelope_at_zero = float(anchor.property("speakingEnvelopeSmoothed"))

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "speaking",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 1.0,
                "voice_audio_level": 1.0,
                "voice_outer_speaking_motion": 1.0,
                "voice_audio_reactive_available": True,
                "voice_audio_reactive_source": "playback_output_envelope",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(96)
        app.processEvents()

        envelope_after_spike = float(anchor.property("speakingEnvelopeSmoothed"))
        assert bool(anchor.property("speakingOnsetGuardActive")) is True
        assert anchor.property("visualState") == "speaking"
        assert envelope_after_spike > envelope_at_zero
        assert envelope_after_spike <= 0.32
        assert float(anchor.property("speakingTargetEnvelope")) <= 0.52
        assert float(anchor.property("speakingPhase")) > phase_at_start

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "",
                "voice_current_phase": "",
                "speaking_visual_active": False,
                "active_playback_status": "",
                "voice_center_blob_scale_drive": 0.0,
                "voice_audio_level": 0.0,
                "voice_outer_speaking_motion": 0.0,
                "voice_audio_reactive_available": True,
                "voice_audio_reactive_source": "playback_output_envelope",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(420)
        app.processEvents()

        assert anchor.property("rawDerivedVisualState") == "idle"
        assert anchor.property("normalizedState") == "speaking"
        assert anchor.property("visualState") == "speaking"
        assert bool(anchor.property("speakingOnsetGuardActive")) is True
        assert bool(anchor.property("speakingStartupFlickerSuppressed")) is True
        assert bool(anchor.property("speakingDroppedToIdleDuringOnset")) is False
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert float(anchor.property("speakingEnvelopeSmoothed")) >= envelope_after_spike * 0.55

        phase_before_repeat = float(anchor.property("speakingPhase"))
        serial_before_repeat = int(anchor.property("visualStateChangeSerial"))
        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "speaking",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 0.42,
                "voice_audio_level": 0.44,
                "voice_outer_speaking_motion": 0.36,
                "voice_audio_reactive_available": True,
                "voice_audio_reactive_source": "playback_output_envelope",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()

        assert anchor.property("visualState") == "speaking"
        assert int(anchor.property("visualStateChangeSerial")) == serial_before_repeat
        assert float(anchor.property("speakingPhase")) > phase_before_repeat

        anchor.setProperty("state", "approval_required")
        app.processEvents()
        QtTest.QTest.qWait(30)
        app.processEvents()
        assert anchor.property("visualState") == "approval_required"
        assert anchor.property("stateLatchReason") == "prompt_source"
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_p2a67r_speaking_render_loop_paint_requests_are_bounded() -> None:
    workspace_config = load_config(project_root=Path.cwd(), env={})
    source = (
        workspace_config.runtime.assets_dir
        / "qml"
        / "variants"
        / "stormforge"
        / "StormforgeAnchorCore.qml"
    ).read_text(encoding="utf-8")

    assert 'renderLoopRegressionGuardVersion: "UI-P2A.6.7R"' in source
    assert "requestPaintCoalescingEnabled: true" in source
    assert "voiceEventDirectPaintDisabled: true" in source

    raw_speaking_handler = source.split("onRawSpeakingLevelChanged:", 1)[1].split(
        "\n    onTransitionProgressChanged:",
        1,
    )[0]
    assert "requestAnchorPaint" not in raw_speaking_handler
    assert "anchorCanvas.requestPaint()" not in raw_speaking_handler
    assert "onEffectiveSpeakingLevelChanged: requestAnchorPaint" not in source
    assert "onEffectiveAudioLevelChanged: requestAnchorPaint" not in source
    assert "onEffectiveIntensityChanged: requestAnchorPaint" not in source
    assert "Timer {\n        id: paintCoalesceTimer" in source


def test_stormforge_anchor_p2a68_decouples_raw_levels_from_geometry_driver() -> None:
    workspace_config = load_config(project_root=Path.cwd(), env={})
    source = (
        workspace_config.runtime.assets_dir
        / "qml"
        / "variants"
        / "stormforge"
        / "StormforgeAnchorCore.qml"
    ).read_text(encoding="utf-8")

    assert 'reactiveEnvelopeVersion: "UI-P2A.6.8"' in source
    assert "audioReactiveDecoupled: true" in source
    assert "reactiveEnvelopeContinuous: true" in source
    assert "proceduralSpeechSynthEnabled: true" in source
    assert "rawLevelDirectGeometryDriveDisabled: true" in source
    assert "missingRawLevelUsesProceduralSpeechEnergy: true" in source
    assert "speakingEnergyJitterGuardEnabled: true" in source
    assert "property real reactiveLevelTarget" in source
    assert "property real reactiveEnvelope" in source
    assert "property real proceduralSpeechEnergy" in source
    assert "property real finalSpeakingEnergy" in source

    raw_speaking_handler = source.split("onRawSpeakingLevelChanged:", 1)[1].split(
        "\n    onTransitionProgressChanged:",
        1,
    )[0]
    assert "reactiveLevelTarget" in raw_speaking_handler
    assert "rawLevelUpdateCount" in raw_speaking_handler
    assert "speakingEnvelopeSmoothed =" not in raw_speaking_handler
    assert "finalSpeakingEnergy =" not in raw_speaking_handler
    assert "requestAnchorPaint" not in raw_speaking_handler
    assert "anchorCanvas.requestPaint()" not in raw_speaking_handler

    assert "var speakLevel = root.finalSpeakingEnergy" in source
    assert "var speakingTarget = backendSpeakingNow ? root.rawSpeakingLevel" not in source
    assert "root.speakingEnvelopeSmoothed = Math.max(0.012, Math.min(root.rawSpeakingLevel" not in source


def test_stormforge_anchor_p2a68_chunky_levels_use_continuous_visual_envelope() -> None:
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
    objectName: "decoupledReactiveAnchor"
    width: 230
    height: 270
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_center_blob_scale_drive": 0.76,
        "voice_outer_speaking_motion": 0.52,
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "playback_output_envelope"
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorP2A68EnvelopeHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("reactiveEnvelopeVersion") == "UI-P2A.6.8"
        assert bool(anchor.property("audioReactiveDecoupled")) is True
        assert bool(anchor.property("reactiveEnvelopeContinuous")) is True
        assert bool(anchor.property("proceduralSpeechSynthEnabled")) is True
        assert bool(anchor.property("rawLevelDirectGeometryDriveDisabled")) is True
        assert bool(anchor.property("missingRawLevelUsesProceduralSpeechEnergy")) is True
        assert bool(anchor.property("speakingEnergyJitterGuardEnabled")) is True
        assert anchor.property("visualState") == "speaking"
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert float(anchor.property("rawSpeakingLevel")) == pytest.approx(0.76)
        assert float(anchor.property("reactiveLevelTarget")) == pytest.approx(0.76)
        assert float(anchor.property("reactiveEnvelope")) > 0.0
        assert float(anchor.property("proceduralSpeechEnergy")) > 0.0
        initial_energy = float(anchor.property("finalSpeakingEnergy"))
        initial_phase = float(anchor.property("speakingPhase"))
        assert initial_energy > 0.04

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "playback_active",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 0.0,
                "voice_outer_speaking_motion": 0.0,
                "voice_audio_reactive_available": True,
                "voice_audio_reactive_source": "playback_output_envelope",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(90)
        app.processEvents()

        zero_gap_energy = float(anchor.property("finalSpeakingEnergy"))
        assert float(anchor.property("rawSpeakingLevel")) == pytest.approx(0.0)
        assert float(anchor.property("reactiveLevelTarget")) == pytest.approx(0.0)
        assert float(anchor.property("proceduralSpeechEnergy")) > 0.0
        assert zero_gap_energy >= initial_energy * 0.55
        assert float(anchor.property("speakingPhase")) > initial_phase

        phase_before_burst = float(anchor.property("speakingPhase"))
        energy_before_burst = float(anchor.property("finalSpeakingEnergy"))
        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "playback_active",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 1.0,
                "voice_outer_speaking_motion": 1.0,
                "voice_audio_reactive_available": True,
                "voice_audio_reactive_source": "playback_output_envelope",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(70)
        app.processEvents()

        burst_energy = float(anchor.property("finalSpeakingEnergy"))
        assert float(anchor.property("reactiveLevelTarget")) == pytest.approx(1.0)
        assert burst_energy <= energy_before_burst + 0.16
        assert float(anchor.property("speakingPhase")) > phase_before_burst
        assert int(anchor.property("rawLevelUpdateCount")) >= 2

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "",
                "voice_current_phase": "idle",
                "speaking_visual_active": False,
                "active_playback_status": "idle",
                "voice_center_blob_scale_drive": 0.0,
                "voice_outer_speaking_motion": 0.0,
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(int(anchor.property("speakingLatchMs")) + int(anchor.property("stateMinimumDwellMs")) + 420)
        app.processEvents()

        assert anchor.property("normalizedState") == "idle"
        assert anchor.property("visualState") == "idle"
        assert bool(anchor.property("visualSpeakingActive")) is False
        assert float(anchor.property("proceduralSpeechEnergy")) == pytest.approx(0.0)
        assert float(anchor.property("finalSpeakingEnergy")) < initial_energy
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_p2r_shared_animation_clock_contract_is_declared() -> None:
    workspace_config = load_config(project_root=Path.cwd(), env={})
    stormforge_dir = workspace_config.runtime.assets_dir / "qml" / "variants" / "stormforge"
    clock_source = (stormforge_dir / "StormforgeAnimationClock.qml").read_text(encoding="utf-8")
    shell_source = (stormforge_dir / "StormforgeGhostShell.qml").read_text(encoding="utf-8")
    host_source = (stormforge_dir / "StormforgeAnchorHost.qml").read_text(encoding="utf-8")
    anchor_source = (stormforge_dir / "StormforgeAnchorCore.qml").read_text(encoding="utf-8")
    fog_source = (stormforge_dir / "StormforgeVolumetricFogLayer.qml").read_text(encoding="utf-8")

    assert 'renderCadenceVersion: "UI-P2R"' in clock_source
    assert "property int targetFps: 60" in clock_source
    assert "property int minAcceptableFps: 30" in clock_source
    assert "property real animationTimeMs" in clock_source
    assert "property real deltaTimeMs" in clock_source
    assert "signal frameTick" in clock_source
    assert "longFrameCount" in clock_source
    assert "cadenceStable" in clock_source
    assert "speakingCadenceStable" in clock_source

    assert "StormforgeAnimationClock" in shell_source
    assert 'objectName: "stormforgeAnimationClock"' in shell_source
    assert "visualVoiceState" in shell_source
    assert "applyPendingVoiceStateForVisualFrame" in shell_source
    assert "voiceState: root.visualVoiceState" in shell_source
    assert "voiceVisualSyncVersion" in shell_source

    assert "visualClockAnimationTimeMs" in host_source
    assert "visualClockFrameCounter" in host_source
    assert "visualClockAnimationTimeMs" in anchor_source
    assert "advanceAnimationFrame" in anchor_source
    assert "running: root.visible && root.animationRunning && !root.sharedVisualClockActive" in anchor_source
    assert "audioReactiveUsesVisualClock" in anchor_source
    assert "rawAudioEventsDoNotRequestPaint" in anchor_source
    assert "root.flushAnchorPaint()" in anchor_source

    assert "visualClockAnimationTimeSec" in fog_source
    assert "fogUsesSharedVisualClock" in fog_source
    assert "phaseAnimation.running" in fog_source
    assert "root.fogUsesSharedVisualClock ? root.sharedClockPhase : root.fallbackPhase" in fog_source


def test_stormforge_p2r1_fog_timebase_contract_scales_shared_clock_seconds() -> None:
    workspace_config = load_config(project_root=Path.cwd(), env={})
    stormforge_dir = workspace_config.runtime.assets_dir / "qml" / "variants" / "stormforge"
    fog_source = (stormforge_dir / "StormforgeVolumetricFogLayer.qml").read_text(encoding="utf-8")

    assert 'fogTimebaseVersion: "UI-P2R.1"' in fog_source
    assert 'fogTimeInputUnit: "seconds"' in fog_source
    assert "fogLegacyPhaseUnitsPerSecond: 10000.0 / 520000.0" in fog_source
    assert "fogSharedClockTimeSec" in fog_source
    assert "fogEffectiveDriftSpeed" in fog_source
    assert "fogFallbackAnimationActive" in fog_source
    assert "fogDoubleDriven" in fog_source
    assert "root.fogUsesSharedVisualClock ? root.sharedClockPhase : root.fallbackPhase" in fog_source


def test_stormforge_p2r1_fog_shared_clock_phase_uses_legacy_speed_scale() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeVolumetricFogLayer {
    objectName: "p2r1FogTimebase"
    width: 640
    height: 360
    visualClockAnimationTimeSec: 10.0
    visualClockFrameCounter: 600
    visualClockMeasuredFps: 60.0
    config: ({
        "enabled": true,
        "mode": "volumetric",
        "quality": "medium",
        "motion": true,
        "driftSpeed": 0.08
    })
}
""".strip()

    fog = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeP2R1FogTimebaseHarness.qml"
                )
            ),
        )
        fog = component.create()
        app.processEvents()

        assert component.isReady(), component.errors()
        assert fog is not None
        legacy_units_per_second = 10000.0 / 520000.0
        assert bool(fog.property("fogUsesSharedVisualClock")) is True
        assert fog.property("fogTimebaseVersion") == "UI-P2R.1"
        assert fog.property("fogTimeInputUnit") == "seconds"
        assert float(fog.property("fogSharedClockTimeSec")) == pytest.approx(10.0)
        assert float(fog.property("fogLegacyPhaseUnitsPerSecond")) == pytest.approx(legacy_units_per_second)
        assert float(fog.property("phase")) == pytest.approx(10.0 * legacy_units_per_second)
        assert float(fog.property("fogEffectiveDriftSpeed")) == pytest.approx(0.08)
        assert bool(fog.property("fogFallbackAnimationActive")) is False
        assert bool(fog.property("fogDoubleDriven")) is False
    finally:
        _dispose_qt_objects(app, fog, engine)


def test_stormforge_p2r1_live_probe_uses_frame_swapped_and_marks_offscreen_nonfinal() -> None:
    offscreen_probe = (Path.cwd() / "scripts" / "run_stormforge_render_cadence_probe.py").read_text(
        encoding="utf-8"
    )
    live_probe = (Path.cwd() / "scripts" / "run_stormforge_live_renderer_probe.py").read_text(
        encoding="utf-8"
    )

    assert '"offscreen_probe_is_live_proof": False' in offscreen_probe
    assert '"requires_live_renderer_probe": True' in offscreen_probe
    assert "fogTimebaseVersion" in offscreen_probe
    assert "fogDoubleDriven" in offscreen_probe

    assert "window.frameSwapped.connect" in live_probe
    assert "live_renderer_cadence_report.json" in live_probe
    assert "live_frame_intervals.csv" in live_probe
    assert "live_voice_update_churn_report.json" in live_probe
    assert "fog_timebase_report.json" in live_probe
    assert '"desktop_qquickwindow_frame_swapped"' in live_probe
    assert '"production_app_attached": False' in live_probe


def test_stormforge_p2r_shared_clock_drives_anchor_and_fog_during_voice_churn() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeGhostShell {
    objectName: "p2rClockGhost"
    width: 920
    height: 620
    stormforgeFogConfig: ({
        "enabled": true,
        "mode": "volumetric",
        "quality": "medium",
        "motion": true,
        "intensity": 0.35
    })
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_center_blob_scale_drive": 0.54,
        "voice_outer_speaking_motion": 0.40,
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "playback_output_envelope"
    })
}
""".strip()

    shell = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeP2RClockHarness.qml"
                )
            ),
        )
        shell = component.create()
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert shell is not None
        clock = shell.findChild(QtCore.QObject, "stormforgeAnimationClock")
        host = shell.findChild(QtCore.QObject, "stormforgeAnchorHost")
        anchor = shell.findChild(QtCore.QObject, "stormforgeAnchorCore")
        fog = shell.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")
        assert clock is not None
        assert host is not None
        assert anchor is not None
        assert fog is not None

        assert shell.property("stormforgeRenderCadenceVersion") == "UI-P2R"
        assert shell.property("voiceVisualSyncVersion") == "UI-P2R"
        assert bool(shell.property("sharedAnimationClockEnabled")) is True
        assert int(shell.property("visualClockTargetFps")) == 60
        assert int(shell.property("visualClockMinAcceptableFps")) == 30
        assert bool(anchor.property("sharedVisualClockActive")) is True
        assert bool(anchor.property("audioReactiveUsesVisualClock")) is True
        assert bool(anchor.property("rawAudioEventsDoNotRequestPaint")) is True
        assert bool(fog.property("fogUsesSharedVisualClock")) is True
        assert bool(fog.property("fallbackPhaseAnimationDisabledBySharedClock")) is True

        start_frame = int(shell.property("visualClockFrameCounter"))
        start_phase = float(anchor.property("speakingPhase"))
        start_fog_phase = float(fog.property("phase"))
        start_raw_updates = int(anchor.property("rawLevelUpdateCount"))

        for index in range(48):
            level = 0.0 if index % 4 == 0 else min(1.0, 0.20 + (index % 7) * 0.11)
            shell.setProperty(
                "voiceState",
                {
                    "voice_anchor_state": "speaking",
                    "voice_current_phase": "playback_active",
                    "speaking_visual_active": True,
                    "active_playback_status": "playing",
                    "voice_center_blob_scale_drive": level,
                    "voice_outer_speaking_motion": min(1.0, level + 0.08),
                    "voice_audio_reactive_available": True,
                    "voice_audio_reactive_source": "playback_output_envelope",
                },
            )
            app.processEvents()

        QtTest.QTest.qWait(1250)
        app.processEvents()

        assert int(shell.property("visualClockFrameCounter")) > start_frame + 25
        assert float(anchor.property("speakingPhase")) > start_phase
        assert float(fog.property("phase")) > start_fog_phase
        assert int(anchor.property("rawLevelUpdateCount")) > start_raw_updates
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert float(anchor.property("finalSpeakingEnergy")) > 0.0
        assert int(shell.property("voiceEventRateDuringSpeaking")) > 0
        assert int(shell.property("visualVoiceStateApplyCount")) <= int(shell.property("visualClockFrameCounter"))
        assert int(anchor.property("anchorRequestPaintCountPerSecond")) <= 70
        assert int(anchor.property("speakingEnvelopeUpdateCountPerSecond")) <= 70
        assert float(shell.property("anchorPaintFpsDuringSpeaking")) <= 70.0
        assert float(shell.property("fogTickFpsDuringSpeaking")) >= 30.0
        assert bool(shell.property("rawAudioEventsDoNotRequestPaint")) is True
    finally:
        _dispose_qt_objects(app, shell, engine)


def test_stormforge_anchor_p2a67r_speaking_render_cadence_diagnostics_are_bounded() -> None:
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
    objectName: "renderCadenceAnchor"
    width: 220
    height: 260
    renderLoopDiagnosticsEnabled: true
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "speaking",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "playback_output_envelope",
        "voice_center_blob_scale_drive": 0.30,
        "voice_outer_speaking_motion": 0.22
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorP2A67RRenderCadenceHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("renderLoopRegressionGuardVersion") == "UI-P2A.6.7R"
        assert bool(anchor.property("requestPaintCoalescingEnabled")) is True
        assert bool(anchor.property("voiceEventDirectPaintDisabled")) is True
        assert 16 <= int(anchor.property("paintCoalesceIntervalMs")) <= 33
        assert int(anchor.property("anchorFrameTimerIntervalMs")) >= 32

        for index in range(40):
            level = 0.18 + (index % 5) * 0.12
            anchor.setProperty(
                "voiceState",
                {
                    "voice_anchor_state": "speaking",
                    "voice_current_phase": "speaking",
                    "speaking_visual_active": True,
                    "active_playback_status": "playing",
                    "voice_audio_reactive_available": True,
                    "voice_audio_reactive_source": "playback_output_envelope",
                    "voice_center_blob_scale_drive": level,
                    "voice_outer_speaking_motion": min(1.0, level + 0.10),
                },
            )
            app.processEvents()

        QtTest.QTest.qWait(1250)
        app.processEvents()

        assert anchor.property("visualState") == "speaking"
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert bool(anchor.property("animationCadenceWarning")) is False
        assert int(anchor.property("anchorRequestPaintCountPerSecond")) <= 70
        assert int(anchor.property("speakingEnvelopeUpdateCountPerSecond")) <= 70
        assert int(anchor.property("speakingUpdateCountPerSecond")) <= 90
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_ghost_p2a67r_speaking_with_fog_keeps_anchor_cadence_bounded() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeGhostShell {
    objectName: "speakingFogCadenceGhostShell"
    width: 900
    height: 620
    stormforgeFogConfig: {
        "enabled": true,
        "mode": "volumetric",
        "quality": "medium",
        "intensity": 0.35
    }
    voiceState: {
        "voice_anchor": {"state_label": "Speaking"},
        "voice_anchor_state": "speaking",
        "voice_current_phase": "speaking",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "playback_output_envelope",
        "voice_center_blob_scale_drive": 0.34,
        "voice_outer_speaking_motion": 0.26
    }
}
""".strip()

    shell = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeGhostP2A67RFogSpeakingCadenceHarness.qml"
                )
            ),
        )
        shell = component.create()
        app.processEvents()
        QtTest.QTest.qWait(160)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert shell is not None
        anchor = shell.findChild(QtCore.QObject, "stormforgeAnchorCore")
        fog = shell.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")
        assert anchor is not None
        assert fog is not None
        anchor.setProperty("renderLoopDiagnosticsEnabled", True)

        for index in range(36):
            level = 0.20 + (index % 6) * 0.10
            shell.setProperty(
                "voiceState",
                {
                    "voice_anchor": {"state_label": "Speaking"},
                    "voice_anchor_state": "speaking",
                    "voice_current_phase": "speaking",
                    "speaking_visual_active": True,
                    "active_playback_status": "playing",
                    "voice_audio_reactive_available": True,
                    "voice_audio_reactive_source": "playback_output_envelope",
                    "voice_center_blob_scale_drive": level,
                    "voice_outer_speaking_motion": min(1.0, level + 0.12),
                },
            )
            app.processEvents()

        QtTest.QTest.qWait(1250)
        app.processEvents()

        assert fog.property("active") is True
        assert fog.property("animationRunning") is True
        assert anchor.property("visualState") == "speaking"
        assert bool(anchor.property("animationCadenceWarning")) is False
        assert int(anchor.property("anchorFrameTimerIntervalMs")) >= 32
        assert int(anchor.property("anchorRequestPaintCountPerSecond")) <= 70
        assert int(anchor.property("speakingEnvelopeUpdateCountPerSecond")) <= 70
    finally:
        _dispose_qt_objects(app, shell, engine)


def test_stormforge_anchor_p2a66_explicit_unavailable_is_dim_but_structural() -> None:
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
    objectName: "explicitUnavailableAnchor"
    width: 260
    height: 292
    state: "unavailable"
    voiceState: ({
        "voice_current_phase": "idle",
        "voice_anchor_state": "",
        "active_playback_status": "idle",
        "speaking_visual_active": false
    })
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
                        / "StormforgeAnchorP2A66UnavailableHarness.qml"
                    )
                ),
            )
            anchor = component.create()
            app.processEvents()
            QtTest.QTest.qWait(160)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert [message for message in messages if "StormforgeAnchor" in message] == []

        assert anchor.property("resolvedState") == "unavailable"
        assert anchor.property("neverVanishInvariantVersion") == "UI-P2A.6.6"
        assert anchor.property("anchorVisibilityStatus") == "visible_unavailable_floor"
        assert anchor.property("resolvedSublabel") != "Voice offline"
        assert bool(anchor.property("finalVisibilityFloorApplied")) is True
        assert bool(anchor.property("finalAnchorVisible")) is True
        assert float(anchor.property("finalAnchorOpacityFloor")) >= 0.50
        assert float(anchor.property("finalBlobOpacity")) >= 0.28
        assert float(anchor.property("finalRingOpacity")) >= 0.20
        assert float(anchor.property("finalCenterGlowOpacity")) >= 0.14
        assert float(anchor.property("finalSignalPointOpacity")) >= 0.22
        assert float(anchor.property("finalBearingTickOpacity")) >= 0.16
        assert bool(anchor.property("uniformScalePulseDisabled")) is True
        assert anchor.property("anchorMotionArchitecture") == "organic_blob_hybrid"
    finally:
        _dispose_qt_objects(app, anchor, engine)


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


def test_stormforge_anchor_mode_switches_keep_motion_timebase_continuous() -> None:
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
    objectName: "continuityAnchor"
    width: 230
    height: 270
    state: ""
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorTransitionContinuityHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(140)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("modeTransitionContinuityVersion") == "UI-P2A.6.7"
        assert bool(anchor.property("modeTransitionEasingEnabled")) is True
        assert bool(anchor.property("stateFeatureCrossfadeEnabled")) is True
        assert bool(anchor.property("colorTransitionSmoothingEnabled")) is True
        assert bool(anchor.property("animationTimebaseContinuous")) is True
        assert bool(anchor.property("transitionDoesNotResetAnchor")) is True
        assert float(anchor.property("transitionContinuityFloor")) >= 0.25
        assert 0.0 <= float(anchor.property("stateFeatureAlpha")) <= 1.0
        assert float(anchor.property("organicCadenceSpeedupFactor")) == pytest.approx(1.20)
        assert int(anchor.property("blobPrimaryCycleMs")) == 8000
        assert int(anchor.property("blobSecondaryCycleMs")) == 12800
        assert int(anchor.property("blobDriftCycleMs")) == 19600

        phase0 = float(anchor.property("phase"))
        orbit0 = float(anchor.property("orbit"))
        wave0 = float(anchor.property("wavePhase"))
        organic0 = float(anchor.property("organicMotionTimeMs"))
        fragment0 = float(anchor.property("ringFragmentPhase"))

        anchor.setProperty("state", "routing")
        app.processEvents()
        QtTest.QTest.qWait(int(anchor.property("stateMinimumDwellMs")) + 120)
        app.processEvents()

        assert anchor.property("visualState") == "thinking"
        assert anchor.property("previousVisualState") == "idle"
        assert anchor.property("transitionFromState") == "idle"
        assert anchor.property("transitionToState") == "thinking"
        assert float(anchor.property("organicMotionTimeMs")) > organic0
        assert float(anchor.property("ringFragmentPhase")) > fragment0
        assert float(anchor.property("phase")) >= phase0
        assert float(anchor.property("orbit")) >= orbit0
        assert float(anchor.property("wavePhase")) >= wave0
        assert bool(anchor.property("stateTransitionActive")) is True
        assert float(anchor.property("stateFeatureAlpha")) >= float(anchor.property("transitionContinuityFloor"))

        organic1 = float(anchor.property("organicMotionTimeMs"))
        fragment1 = float(anchor.property("ringFragmentPhase"))
        orbit1 = float(anchor.property("orbit"))
        anchor.setProperty("state", "executing")
        app.processEvents()
        QtTest.QTest.qWait(90)
        app.processEvents()

        assert anchor.property("visualState") == "acting"
        assert anchor.property("previousVisualState") == "thinking"
        assert anchor.property("transitionFromState") == "thinking"
        assert anchor.property("transitionToState") == "acting"
        assert float(anchor.property("organicMotionTimeMs")) > organic1
        assert float(anchor.property("ringFragmentPhase")) > fragment1
        assert float(anchor.property("orbit")) >= orbit1
        assert bool(anchor.property("stateTransitionActive")) is True

        organic2 = float(anchor.property("organicMotionTimeMs"))
        fragment2 = float(anchor.property("ringFragmentPhase"))
        anchor.setProperty("state", "")
        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "playback_active",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 0.70,
                "voice_outer_speaking_motion": 0.55,
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(140)
        app.processEvents()

        assert anchor.property("visualState") == "speaking"
        assert anchor.property("previousVisualState") == "acting"
        assert anchor.property("transitionFromState") == "acting"
        assert anchor.property("transitionToState") == "speaking"
        assert float(anchor.property("organicMotionTimeMs")) > organic2
        assert float(anchor.property("ringFragmentPhase")) > fragment2
        assert float(anchor.property("speakingEnvelopeSmoothed")) > 0.0
        assert bool(anchor.property("speakingPhaseContinuous")) is True
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_blob_hybrid_idle_motion_replaces_uniform_scale_pulse() -> None:
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
    objectName: "organicIdleAnchor"
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
                        / "StormforgeAnchorOrganicIdleHarness.qml"
                    )
                ),
            )
            anchor = component.create()
            app.processEvents()
            QtTest.QTest.qWait(120)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert [message for message in messages if "StormforgeAnchor" in message] == []

        first_time = float(anchor.property("organicMotionTimeMs"))
        first_phase = float(anchor.property("phase"))
        first_organic = float(anchor.property("idleOrganicValue"))
        QtTest.QTest.qWait(180)
        app.processEvents()

        assert anchor.property("organicMotionVersion") == "UI-P2A.6.1"
        assert anchor.property("blobMotionSweetSpotVersion") == "UI-P2A.6.1"
        assert anchor.property("anchorMotionArchitecture") == "organic_blob_hybrid"
        assert anchor.property("visualState") == "idle"
        assert bool(anchor.property("blobCoreEnabled")) is True
        assert int(anchor.property("blobPointCount")) >= 24
        assert bool(anchor.property("organicBlobMotionActive")) is True
        assert bool(anchor.property("uniformScalePulseDisabled")) is True
        assert 0.080 <= float(anchor.property("organicMotionAmplitude")) <= 0.095
        assert 0.080 <= float(anchor.property("blobDeformationStrength")) <= 0.095
        assert int(anchor.property("blobPrimaryCycleMs")) >= 7500
        assert int(anchor.property("blobSecondaryCycleMs")) >= 12000
        assert int(anchor.property("blobDriftCycleMs")) >= 18000
        assert bool(anchor.property("idleUniformScalePulseDisabled")) is True
        assert bool(anchor.property("idleOrganicMotionActive")) is True
        assert bool(anchor.property("ringFragmentsActive")) is True
        assert int(anchor.property("ringFragmentCount")) == 4
        assert int(anchor.property("ringFragmentMinCycleMs")) >= 18000
        assert int(anchor.property("ringFragmentMaxCycleMs")) >= 40000
        assert int(anchor.property("idlePrimaryCycleMs")) >= 7000
        assert int(anchor.property("idleSecondaryCycleMs")) >= 11000
        assert int(anchor.property("idleDriftCycleMs")) >= 17000
        assert float(anchor.property("organicMotionTimeMs")) > first_time
        assert float(anchor.property("phase")) >= first_phase
        assert 0.0 <= float(anchor.property("idleOrganicValue")) <= 1.0
        assert abs(float(anchor.property("idleOrganicValue")) - first_organic) < 0.35
        assert float(anchor.property("idleUniformScaleAmplitude")) == pytest.approx(0.0)
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_blob_hybrid_state_diagnostics_are_truthful() -> None:
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
    height: 280

    StormforgeAnchorCore {
        objectName: "unknownBlobAnchor"
        width: 220
        height: 260
        state: "state_that_does_not_exist"
    }

    StormforgeAnchorCore {
        objectName: "unsupportedSpeakingAnchor"
        x: 250
        width: 220
        height: 260
        voiceState: ({
            "voice_anchor_state": "speaking",
            "voice_current_phase": "speaking",
            "speaking_visual_active": false,
            "active_playback_status": "idle",
            "voice_center_blob_scale_drive": 0.9
        })
    }

    StormforgeAnchorCore {
        objectName: "supportedSpeakingAnchor"
        x: 500
        width: 220
        height: 260
        voiceState: ({
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": true,
            "active_playback_status": "playing",
            "voice_center_blob_scale_drive": 0.65,
            "voice_outer_speaking_motion": 0.42
        })
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
                    / "StormforgeAnchorBlobHybridTruthHarness.qml"
                )
            ),
        )
        root = component.create()
        app.processEvents()
        QtTest.QTest.qWait(180)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None

        unknown = root.findChild(QtCore.QObject, "unknownBlobAnchor")
        unsupported = root.findChild(QtCore.QObject, "unsupportedSpeakingAnchor")
        supported = root.findChild(QtCore.QObject, "supportedSpeakingAnchor")

        assert unknown is not None
        assert unsupported is not None
        assert supported is not None

        assert unknown.property("normalizedState") == "idle"
        assert unknown.property("visualState") == "idle"
        assert bool(unknown.property("organicBlobMotionActive")) is True
        assert float(unknown.property("visualPresenceFloor")) >= 0.10

        assert unsupported.property("normalizedState") != "speaking"
        assert bool(unsupported.property("visualSpeakingActive")) is False
        assert float(unsupported.property("speakingEnvelopeSmoothed")) == pytest.approx(0.0)

        assert supported.property("normalizedState") == "speaking"
        assert bool(supported.property("visualSpeakingActive")) is True
        assert float(supported.property("speakingEnvelopeSmoothed")) > 0.0
        assert bool(supported.property("speakingPhaseContinuous")) is True
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_blob_motion_sweet_spot_is_bounded() -> None:
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
    objectName: "sweetSpotAnchor"
    width: 220
    height: 260
    state: "idle"
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorBlobSweetSpotHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(180)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("anchorMotionArchitecture") == "organic_blob_hybrid"
        assert anchor.property("blobMotionSweetSpotVersion") == "UI-P2A.6.1"
        assert anchor.property("organicMotionAmplitudeVersion") == "UI-P2A.6.1"
        assert bool(anchor.property("uniformScalePulseDisabled")) is True
        assert float(anchor.property("idleUniformScaleAmplitude")) == pytest.approx(0.0)
        assert 0.080 <= float(anchor.property("organicMotionAmplitude")) <= 0.095
        assert 0.080 <= float(anchor.property("blobDeformationStrength")) <= 0.095
        assert int(anchor.property("blobPrimaryCycleMs")) >= 7500
        assert int(anchor.property("blobSecondaryCycleMs")) >= 12000
        assert int(anchor.property("blobDriftCycleMs")) >= 18000
        assert int(anchor.property("ringFragmentMinCycleMs")) >= 18000
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_aperture_shimmer_is_animated_and_bounded() -> None:
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
    objectName: "shimmerMotionAnchor"
    width: 220
    height: 260
    state: "idle"
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorShimmerMotionHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("anchorMotionArchitecture") == "organic_blob_hybrid"
        assert anchor.property("apertureShimmerMotionVersion") == "UI-P2A.6.3"
        assert bool(anchor.property("apertureShimmerAnimated")) is True
        assert bool(anchor.property("apertureShimmerUsesIndependentPhase")) is True
        assert bool(anchor.property("uniformScalePulseDisabled")) is True

        assert 9000 <= int(anchor.property("apertureShimmerDriftCycleMs")) <= 19000
        assert 14000 <= int(anchor.property("apertureShimmerSecondaryCycleMs")) <= 29000
        assert 0.075 <= float(anchor.property("apertureShimmerOpacityMin")) < float(anchor.property("apertureShimmerOpacityMax")) <= 0.23

        first_x = float(anchor.property("apertureShimmerOffsetX"))
        first_y = float(anchor.property("apertureShimmerOffsetY"))
        first_opacity = float(anchor.property("apertureShimmerOpacity"))
        first_phase = float(anchor.property("apertureShimmerPhase"))

        QtTest.QTest.qWait(420)
        app.processEvents()

        second_x = float(anchor.property("apertureShimmerOffsetX"))
        second_y = float(anchor.property("apertureShimmerOffsetY"))
        second_opacity = float(anchor.property("apertureShimmerOpacity"))
        second_phase = float(anchor.property("apertureShimmerPhase"))

        assert second_phase > first_phase
        assert abs(second_x - first_x) + abs(second_y - first_y) > 0.0005
        assert 0.075 <= first_opacity <= 0.23
        assert 0.075 <= second_opacity <= 0.23
        assert abs(second_opacity - first_opacity) < 0.10
        assert float(anchor.property("idleUniformScaleAmplitude")) == pytest.approx(0.0)
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_presence_speaking_and_shimmer_tuning_is_bounded() -> None:
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
    width: 520
    height: 280

    StormforgeAnchorCore {
        objectName: "presenceIdleAnchor"
        width: 220
        height: 260
        state: "idle"
    }

    StormforgeAnchorCore {
        objectName: "presenceSpeakingAnchor"
        x: 260
        width: 220
        height: 260
        voiceState: ({
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": true,
            "active_playback_status": "playing",
            "voice_center_blob_scale_drive": 0.78,
            "voice_outer_speaking_motion": 0.62,
            "voice_audio_reactive_available": true,
            "voice_audio_reactive_source": "playback_output_envelope"
        })
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
                    / "StormforgeAnchorPresenceTuningHarness.qml"
                )
            ),
        )
        root = component.create()
        app.processEvents()
        QtTest.QTest.qWait(240)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        idle = root.findChild(QtCore.QObject, "presenceIdleAnchor")
        speaking = root.findChild(QtCore.QObject, "presenceSpeakingAnchor")
        assert idle is not None
        assert speaking is not None

        assert idle.property("anchorMotionArchitecture") == "organic_blob_hybrid"
        assert idle.property("anchorPresenceTuningVersion") == "UI-P2A.6.3"
        assert bool(idle.property("apertureShimmerVisibleTarget")) is True
        assert bool(idle.property("speakingExpressionPronounced")) is True
        assert bool(idle.property("uniformScalePulseDisabled")) is True
        assert float(idle.property("idleUniformScaleAmplitude")) == pytest.approx(0.0)

        assert 1.10 <= float(idle.property("anchorPresenceBoost")) <= 1.20
        assert float(idle.property("speakingExpressionBoost")) == pytest.approx(1.92)
        assert float(idle.property("speakingAudioReactiveStrengthBoost")) == pytest.approx(2.475)
        assert 1.35 <= float(idle.property("shimmerLegibilityBoost")) <= 1.60
        assert 0.075 <= float(idle.property("apertureShimmerOpacityMin")) < 0.10
        assert 0.20 <= float(idle.property("apertureShimmerOpacityMax")) <= 0.23
        assert float(idle.property("minimumCenterLensOpacity")) >= 0.18
        assert idle.property("ringFragmentVisibilityVersion") == "UI-P2A.6.8"
        assert float(idle.property("ringFragmentOpacity")) >= 0.23
        assert float(idle.property("blobSpeakingDeformationStrength")) >= 0.165

        assert speaking.property("normalizedState") == "speaking"
        assert speaking.property("visualState") == "speaking"
        assert bool(speaking.property("visualSpeakingActive")) is True
        assert bool(speaking.property("speakingAnimationStable")) is True
        assert bool(speaking.property("speakingPhaseContinuous")) is True
        assert bool(speaking.property("speakingStateFlapGuardEnabled")) is True
        assert float(speaking.property("speakingEnvelopeSmoothed")) > 0.0
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_speaking_envelope_is_smoothed_and_graceful() -> None:
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
    objectName: "speakingStabilityAnchor"
    width: 220
    height: 260
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_center_blob_scale_drive": 0.82,
        "voice_outer_speaking_motion": 0.58,
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "playback_output_envelope"
    })
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
                        / "StormforgeAnchorSpeakingStabilityHarness.qml"
                    )
                ),
            )
            anchor = component.create()
            app.processEvents()
            QtTest.QTest.qWait(220)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert [message for message in messages if "StormforgeAnchor" in message] == []

        assert anchor.property("normalizedState") == "speaking"
        assert anchor.property("visualState") == "speaking"
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert bool(anchor.property("speakingAnimationStable")) is True
        assert bool(anchor.property("speakingPhaseContinuous")) is True
        assert bool(anchor.property("speakingStateFlapGuardEnabled")) is True
        assert int(anchor.property("speakingGraceMs")) >= 120
        assert float(anchor.property("rawSpeakingLevel")) == pytest.approx(0.82)
        smoothed_before = float(anchor.property("speakingEnvelopeSmoothed"))
        phase_before = float(anchor.property("speakingPhase"))
        serial_before = int(anchor.property("visualStateChangeSerial"))
        assert 0.0 < smoothed_before <= 0.82

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "playback_active",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 0.22,
                "voice_outer_speaking_motion": 0.31,
                "voice_audio_reactive_available": True,
                "voice_audio_reactive_source": "playback_output_envelope",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(80)
        app.processEvents()

        assert anchor.property("visualState") == "speaking"
        assert int(anchor.property("visualStateChangeSerial")) == serial_before
        assert float(anchor.property("speakingPhase")) > phase_before
        assert float(anchor.property("speakingEnvelopeSmoothed")) > 0.0
        assert float(anchor.property("speakingEnvelopeSmoothed")) <= smoothed_before

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "",
                "voice_current_phase": "idle",
                "speaking_visual_active": False,
                "active_playback_status": "idle",
                "voice_center_blob_scale_drive": 0.0,
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(40)
        app.processEvents()

        assert anchor.property("rawDerivedVisualState") == "idle"
        assert anchor.property("latchedVisualState") == "speaking"
        assert anchor.property("normalizedState") == "speaking"
        assert anchor.property("visualState") == "speaking"
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert bool(anchor.property("speakingLatched")) is True
        assert anchor.property("stateLatchReason") == "micro_flicker_hold"
        assert float(anchor.property("speakingEnvelopeSmoothed")) > 0.0

        phase_after_flicker = float(anchor.property("speakingPhase"))
        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "playback_active",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 0.44,
                "voice_outer_speaking_motion": 0.33,
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(80)
        app.processEvents()

        assert anchor.property("visualState") == "speaking"
        assert float(anchor.property("speakingPhase")) > phase_after_flicker
        assert float(anchor.property("speakingEnvelopeSmoothed")) > 0.0

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "",
                "voice_current_phase": "idle",
                "speaking_visual_active": False,
                "active_playback_status": "idle",
                "voice_center_blob_scale_drive": 0.0,
            },
        )
        app.processEvents()

        QtTest.QTest.qWait(int(anchor.property("speakingLatchMs")) + int(anchor.property("stateMinimumDwellMs")) + 320)
        app.processEvents()

        assert anchor.property("visualState") == "idle"
        assert anchor.property("normalizedState") == "idle"
        assert bool(anchor.property("visualSpeakingActive")) is False
        assert float(anchor.property("speakingEnvelopeSmoothed")) < smoothed_before
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_p2a64_state_aliases_cadence_and_speaking_attack() -> None:
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
    height: 640

    StormforgeAnchorCore {
        objectName: "planningAliasAnchor"
        width: 220
        height: 260
        state: "planning"
    }

    StormforgeAnchorCore {
        objectName: "runningAliasAnchor"
        x: 240
        width: 220
        height: 260
        state: "running"
    }

    StormforgeAnchorCore {
        objectName: "trustPendingAliasAnchor"
        x: 480
        width: 220
        height: 260
        state: "trust_pending"
    }

    StormforgeAnchorCore {
        objectName: "speakingAttackAnchor"
        x: 720
        width: 220
        height: 260
        voiceState: ({
            "voice_anchor_state": "",
            "voice_current_phase": "idle",
            "speaking_visual_active": false,
            "active_playback_status": "idle",
            "voice_center_blob_scale_drive": 0.0,
            "voice_outer_speaking_motion": 0.0
        })
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
                        / "StormforgeAnchorP2A64Harness.qml"
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

        planning = root.findChild(QtCore.QObject, "planningAliasAnchor")
        running = root.findChild(QtCore.QObject, "runningAliasAnchor")
        trust_pending = root.findChild(QtCore.QObject, "trustPendingAliasAnchor")
        speaking = root.findChild(QtCore.QObject, "speakingAttackAnchor")

        assert planning is not None
        assert running is not None
        assert trust_pending is not None
        assert speaking is not None

        assert planning.property("anchorStateBindingVersion") == "UI-P2A.6.4"
        assert planning.property("statePrecedenceVersion") == "UI-P2A.6.4"
        assert planning.property("organicCadenceVersion") == "UI-P2A.6.4"
        assert float(planning.property("organicCadenceSpeedupFactor")) == pytest.approx(1.20)
        assert bool(planning.property("uniformScalePulseDisabled")) is True
        assert planning.property("anchorMotionArchitecture") == "organic_blob_hybrid"
        assert planning.property("normalizedState") == "thinking"
        assert planning.property("resolvedState") == "thinking"
        assert planning.property("derivedAnchorVisualState") == "thinking"
        assert planning.property("anchorVisualStateSource") in {
            "explicit_state",
            "route_or_assistant_state",
        }
        assert int(planning.property("blobPrimaryCycleMs")) == 8000
        assert int(planning.property("blobSecondaryCycleMs")) == 12800
        assert int(planning.property("blobDriftCycleMs")) == 19600
        assert int(planning.property("apertureShimmerDriftCycleMs")) == 10000
        assert int(planning.property("apertureShimmerSecondaryCycleMs")) == 15600

        assert running.property("normalizedState") == "acting"
        assert running.property("derivedAnchorVisualState") == "acting"
        assert trust_pending.property("normalizedState") == "approval_required"
        assert trust_pending.property("derivedAnchorVisualState") == "approval_required"

        assert bool(speaking.property("speakingAttackSmoothingEnabled")) is True
        assert bool(speaking.property("speakingStartupStable")) is True
        assert int(speaking.property("speakingAttackMs")) >= 300
        assert int(speaking.property("speakingAttackMs")) <= 700
        assert int(speaking.property("speakingReleaseMs")) >= 300
        assert bool(speaking.property("speakingPhaseContinuous")) is True
        assert bool(speaking.property("speakingStateFlapGuardEnabled")) is True

        speaking.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "playback_active",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 0.92,
                "voice_outer_speaking_motion": 0.86,
                "voice_audio_reactive_available": True,
                "voice_audio_reactive_source": "playback_output_envelope",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(90)
        app.processEvents()

        early_smoothed = float(speaking.property("speakingEnvelopeSmoothed"))
        early_phase = float(speaking.property("speakingPhase"))
        serial = int(speaking.property("visualStateChangeSerial"))

        assert speaking.property("normalizedState") == "speaking"
        assert speaking.property("visualState") == "speaking"
        assert bool(speaking.property("visualSpeakingActive")) is True
        assert early_smoothed > 0.0
        assert early_smoothed < float(speaking.property("rawSpeakingLevel")) * 0.65

        speaking.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "playback_active",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 0.74,
                "voice_outer_speaking_motion": 0.63,
                "voice_audio_reactive_available": True,
                "voice_audio_reactive_source": "playback_output_envelope",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(90)
        app.processEvents()

        assert speaking.property("visualState") == "speaking"
        assert int(speaking.property("visualStateChangeSerial")) == serial
        assert float(speaking.property("speakingPhase")) > early_phase
        assert float(speaking.property("speakingEnvelopeSmoothed")) > 0.0
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_p2a65_idle_floors_and_speaking_latch_survive_micro_flicker() -> None:
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
    objectName: "latchAnchor"
    width: 240
    height: 280
    voiceState: ({
        "voice_anchor_state": "",
        "voice_current_phase": "idle",
        "speaking_visual_active": false,
        "active_playback_status": "idle",
        "voice_center_blob_scale_drive": 0.0,
        "voice_outer_speaking_motion": 0.0
    })
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
                        / "StormforgeAnchorP2A65LatchHarness.qml"
                    )
                ),
            )
            anchor = component.create()
            app.processEvents()
            QtTest.QTest.qWait(120)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert [message for message in messages if "StormforgeAnchor" in message] == []

        assert anchor.property("visualStateLatchVersion") == "UI-P2A.6.5"
        assert anchor.property("idlePerceptualPresenceVersion") == "UI-P2A.6.5A"
        assert bool(anchor.property("idlePresenceFloorEnabled")) is True
        assert bool(anchor.property("idleAnchorVisible")) is True
        assert float(anchor.property("idleBlobOpacityFloor")) >= 0.54
        assert float(anchor.property("idleRingOpacityFloor")) >= 0.38
        assert float(anchor.property("idleCenterGlowFloor")) >= 0.30
        assert float(anchor.property("idleFragmentOpacityFloor")) >= 0.35
        assert float(anchor.property("idleActiveAlphaFloor")) >= 0.95
        assert anchor.property("rawDerivedVisualState") == "idle"
        assert anchor.property("latchedVisualState") == "idle"
        assert anchor.property("normalizedState") == "idle"
        assert bool(anchor.property("uniformScalePulseDisabled")) is True
        assert anchor.property("anchorMotionArchitecture") == "organic_blob_hybrid"

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "speaking",
                "voice_current_phase": "playback_active",
                "speaking_visual_active": True,
                "active_playback_status": "playing",
                "voice_center_blob_scale_drive": 0.88,
                "voice_outer_speaking_motion": 0.72,
                "voice_audio_reactive_available": True,
                "voice_audio_reactive_source": "playback_output_envelope",
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(160)
        app.processEvents()

        assert anchor.property("rawDerivedVisualState") == "speaking"
        assert anchor.property("latchedVisualState") == "speaking"
        assert anchor.property("normalizedState") == "speaking"
        assert anchor.property("visualState") == "speaking"
        assert bool(anchor.property("rawSpeakingActive")) is True
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert bool(anchor.property("speakingLatched")) is False
        assert int(anchor.property("speakingLatchMs")) >= 900
        assert int(anchor.property("speakingLatchMs")) <= 1400
        phase_before_flicker = float(anchor.property("speakingPhase"))
        serial_before_flicker = int(anchor.property("visualStateChangeSerial"))

        anchor.setProperty(
            "voiceState",
            {
                "voice_anchor_state": "",
                "voice_current_phase": "idle",
                "speaking_visual_active": False,
                "active_playback_status": "idle",
                "voice_center_blob_scale_drive": 0.0,
                "voice_outer_speaking_motion": 0.0,
            },
        )
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert anchor.property("rawDerivedVisualState") == "idle"
        assert anchor.property("latchedVisualState") == "speaking"
        assert anchor.property("normalizedState") == "speaking"
        assert anchor.property("visualState") == "speaking"
        assert bool(anchor.property("rawSpeakingActive")) is False
        assert bool(anchor.property("speakingLatched")) is True
        assert bool(anchor.property("visualSpeakingActive")) is True
        assert anchor.property("stateLatchReason") == "micro_flicker_hold"
        assert int(anchor.property("visualStateChangeSerial")) == serial_before_flicker
        assert float(anchor.property("speakingPhase")) > phase_before_flicker
        assert bool(anchor.property("speakingDroppedToIdleDuringActive")) is False

        QtTest.QTest.qWait(int(anchor.property("speakingLatchMs")) + int(anchor.property("stateMinimumDwellMs")) + 340)
        app.processEvents()

        assert anchor.property("rawDerivedVisualState") == "idle"
        assert anchor.property("latchedVisualState") == "idle"
        assert anchor.property("normalizedState") == "idle"
        assert anchor.property("visualState") == "idle"
        assert bool(anchor.property("visualSpeakingActive")) is False
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_anchor_p2a65_holds_thinking_and_acting_through_short_idle_gaps() -> None:
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
    width: 520
    height: 320

    StormforgeAnchorCore {
        objectName: "thinkingLatchAnchor"
        width: 220
        height: 260
        state: "routing"
    }

    StormforgeAnchorCore {
        objectName: "actingLatchAnchor"
        x: 260
        width: 220
        height: 260
        state: "executing"
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
                    / "StormforgeAnchorP2A65ActiveLatchHarness.qml"
                )
            ),
        )
        root = component.create()
        app.processEvents()
        QtTest.QTest.qWait(160)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None

        thinking = root.findChild(QtCore.QObject, "thinkingLatchAnchor")
        acting = root.findChild(QtCore.QObject, "actingLatchAnchor")
        assert thinking is not None
        assert acting is not None

        assert thinking.property("normalizedState") == "thinking"
        assert acting.property("normalizedState") == "acting"
        assert int(thinking.property("thinkingLatchMs")) >= 500
        assert int(acting.property("actingLatchMs")) >= 600

        thinking.setProperty("state", "")
        acting.setProperty("state", "")
        app.processEvents()
        QtTest.QTest.qWait(260)
        app.processEvents()

        assert thinking.property("rawDerivedVisualState") == "idle"
        assert thinking.property("latchedVisualState") == "thinking"
        assert thinking.property("visualState") == "thinking"
        assert thinking.property("stateLatchReason") == "micro_flicker_hold"
        assert acting.property("rawDerivedVisualState") == "idle"
        assert acting.property("latchedVisualState") == "acting"
        assert acting.property("visualState") == "acting"
        assert acting.property("stateLatchReason") == "micro_flicker_hold"

        QtTest.QTest.qWait(max(int(thinking.property("thinkingLatchMs")), int(acting.property("actingLatchMs"))) + 360)
        app.processEvents()

        assert thinking.property("latchedVisualState") == "idle"
        assert thinking.property("visualState") == "idle"
        assert acting.property("latchedVisualState") == "idle"
        assert acting.property("visualState") == "idle"
    finally:
        _dispose_qt_objects(app, root, engine)


def test_stormforge_anchor_p2a65_prompt_states_override_speaking_latch() -> None:
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
    objectName: "promptOverrideAnchor"
    width: 220
    height: 260
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_center_blob_scale_drive": 0.70,
        "voice_outer_speaking_motion": 0.50
    })
}
""".strip()

    anchor = None
    try:
        component.setData(
            harness_qml.encode("utf-8"),
            QtCore.QUrl.fromLocalFile(
                str(
                    workspace_config.runtime.assets_dir
                    / "qml"
                    / "StormforgeAnchorP2A65PromptHarness.qml"
                )
            ),
        )
        anchor = component.create()
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()

        assert component.isReady(), component.errors()
        assert anchor is not None
        assert anchor.property("visualState") == "speaking"

        anchor.setProperty("state", "approval_required")
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()

        assert anchor.property("rawDerivedVisualState") == "approval_required"
        assert anchor.property("latchedVisualState") == "approval_required"
        assert anchor.property("visualState") == "approval_required"
        assert anchor.property("stateLatchReason") == "prompt_source"

        anchor.setProperty("state", "failed")
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()

        assert anchor.property("rawDerivedVisualState") == "failed"
        assert anchor.property("latchedVisualState") == "failed"
        assert anchor.property("visualState") == "failed"
        assert anchor.property("stateLatchReason") == "prompt_source"
    finally:
        _dispose_qt_objects(app, anchor, engine)


def test_stormforge_ghost_p2a64_binds_existing_state_to_anchor_visuals() -> None:
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
    height: 820

    StormforgeGhostShell {
        objectName: "thinkingGhostShell"
        width: 360
        height: 380
        stormforgeFogConfig: {"enabled": false}
        assistantState: "routing"
        routeInspector: {
            "routeState": "routing",
            "statusLabel": "Routing native action"
        }
        voiceState: {
            "voice_anchor_state": "",
            "voice_current_phase": "idle",
            "speaking_visual_active": false,
            "active_playback_status": "idle"
        }
    }

    StormforgeGhostShell {
        objectName: "actingGhostShell"
        x: 360
        width: 360
        height: 380
        stormforgeFogConfig: {"enabled": false}
        assistantState: "idle"
        routeInspector: {
            "routeState": "executing",
            "statusLabel": "Executing native action"
        }
        voiceState: {
            "voice_anchor_state": "",
            "voice_current_phase": "idle",
            "speaking_visual_active": false,
            "active_playback_status": "idle"
        }
    }

    StormforgeGhostShell {
        objectName: "approvalGhostShell"
        y: 400
        width: 360
        height: 380
        stormforgeFogConfig: {"enabled": false}
        primaryCard: {
            "title": "Approval Required",
            "resultState": "approval_required"
        }
        voiceState: {
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": true,
            "active_playback_status": "playing",
            "voice_center_blob_scale_drive": 0.78,
            "voice_outer_speaking_motion": 0.58
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
                        / "StormforgeGhostP2A64BindingHarness.qml"
                    )
                ),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(180)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        assert [message for message in messages if "StormforgeGhost" in message] == []

        thinking_shell = root.findChild(QtCore.QObject, "thinkingGhostShell")
        acting_shell = root.findChild(QtCore.QObject, "actingGhostShell")
        approval_shell = root.findChild(QtCore.QObject, "approvalGhostShell")

        assert thinking_shell is not None
        assert acting_shell is not None
        assert approval_shell is not None

        thinking_anchor = thinking_shell.findChild(QtCore.QObject, "stormforgeAnchorCore")
        thinking_host = thinking_shell.findChild(QtCore.QObject, "stormforgeAnchorHost")
        acting_anchor = acting_shell.findChild(QtCore.QObject, "stormforgeAnchorCore")
        acting_host = acting_shell.findChild(QtCore.QObject, "stormforgeAnchorHost")
        approval_anchor = approval_shell.findChild(QtCore.QObject, "stormforgeAnchorCore")
        approval_host = approval_shell.findChild(QtCore.QObject, "stormforgeAnchorHost")

        assert thinking_anchor is not None
        assert thinking_host is not None
        assert acting_anchor is not None
        assert acting_host is not None
        assert approval_anchor is not None
        assert approval_host is not None

        assert thinking_shell.property("ghostTone") == "thinking"
        assert thinking_host.property("resolvedState") == "thinking"
        assert thinking_host.property("derivedAnchorVisualState") == "thinking"
        assert thinking_host.property("anchorVisualStateSource") == "route_or_assistant_state"
        assert thinking_anchor.property("normalizedState") == "thinking"

        assert acting_shell.property("ghostTone") == "acting"
        assert acting_host.property("resolvedState") == "acting"
        assert acting_host.property("derivedAnchorVisualState") == "acting"
        assert acting_host.property("anchorVisualStateSource") == "route_or_assistant_state"
        assert acting_anchor.property("normalizedState") == "acting"

        assert approval_shell.property("ghostTone") == "approval_required"
        assert approval_host.property("resolvedState") == "approval_required"
        assert approval_host.property("derivedAnchorVisualState") == "approval_required"
        assert approval_anchor.property("normalizedState") == "approval_required"
        assert approval_anchor.property("visualState") == "approval_required"
    finally:
        _dispose_qt_objects(app, root, engine)


def test_variant_ghost_shell_p2a64_forwards_stormforge_state_mapping_without_classic_bindings() -> None:
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)

    harness_qml = """
import QtQuick 2.15
import "components"

Item {
    width: 900
    height: 760

    VariantGhostShell {
        objectName: "variantStormforgeGhost"
        width: 440
        height: 360
        visualVariant: "stormforge"
        stormforgeFogConfig: {"enabled": false}
        assistantState: "routing"
        routeInspector: {
            "routeState": "executing",
            "statusLabel": "Executing native action"
        }
        voiceState: {
            "voice_anchor_state": "",
            "voice_current_phase": "idle",
            "speaking_visual_active": false,
            "active_playback_status": "idle"
        }
    }

    VariantGhostShell {
        objectName: "variantClassicGhost"
        x: 460
        width: 440
        height: 360
        visualVariant: "classic"
        assistantState: "routing"
        routeInspector: {
            "routeState": "executing",
            "statusLabel": "Executing native action"
        }
        voiceState: {
            "voice_anchor_state": "",
            "voice_current_phase": "idle",
            "speaking_visual_active": false,
            "active_playback_status": "idle"
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
                        / "VariantGhostShellP2A64Harness.qml"
                    )
                ),
            )
            root = component.create()
            app.processEvents()
            QtTest.QTest.qWait(180)
            app.processEvents()

        assert component.isReady(), component.errors()
        assert root is not None
        assert [message for message in messages if "Cannot assign to non-existent property" in message] == []

        stormforge_wrapper = root.findChild(QtCore.QObject, "variantStormforgeGhost")
        stormforge_shell = root.findChild(QtCore.QObject, "stormforgeGhostShell")
        stormforge_host = stormforge_wrapper.findChild(QtCore.QObject, "stormforgeAnchorHost")
        stormforge_anchor = stormforge_wrapper.findChild(QtCore.QObject, "stormforgeAnchorCore")
        classic_wrapper = root.findChild(QtCore.QObject, "variantClassicGhost")
        classic_shell = root.findChild(QtCore.QObject, "classicGhostShell")

        assert stormforge_wrapper is not None
        assert stormforge_shell is not None
        assert stormforge_host is not None
        assert stormforge_anchor is not None
        assert classic_wrapper is not None
        assert classic_shell is not None

        assert stormforge_shell.property("ghostTone") == "acting"
        assert stormforge_host.property("resolvedState") == "acting"
        assert stormforge_host.property("anchorVisualStateSource") == "route_or_assistant_state"
        assert stormforge_anchor.property("anchorStateBindingVersion") == "UI-P2A.6.4"
        assert stormforge_anchor.property("normalizedState") == "acting"
        assert classic_wrapper.findChild(QtCore.QObject, "stormforgeAnchorCore") is None
    finally:
        _dispose_qt_objects(app, root, engine)


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
        anchor_core = root.findChild(QtCore.QObject, "stormforgeAnchorCore")
        assert anchor_core is not None
        assert anchor_core.property("effectiveAnchorRenderer") == "legacy_blob_reference"
        assert anchor_core.property("anchorRendererArchitecture") == "legacy_blob_reference_canvas"
    finally:
        _dispose_qt_objects(app, engine, root)


def test_main_qml_stormforge_ghost_shows_draft_as_user_types() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene(
        {"STORMHELM_UI_VARIANT": "stormforge"}
    )
    try:
        bridge.appendGhostDraft("Chart a safe course")
        app.processEvents()
        QtTest.QTest.qWait(80)
        app.processEvents()

        transcript = root.findChild(QtCore.QObject, "stormforgeGhostTranscript")
        draft_line = root.findChild(QtCore.QObject, "stormforgeGhostDraftLine")

        assert bridge.ghostCaptureActive is True
        assert bridge.ghostDraftText == "Chart a safe course"
        assert transcript is not None
        assert draft_line is not None
        assert transcript.property("draftVisible") is True
        assert transcript.property("visibleDraftText") == "Chart a safe course"
        assert "Chart a safe course" in str(draft_line.property("text"))
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
        assert float(anchor_host.property("width")) >= 248.0
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
