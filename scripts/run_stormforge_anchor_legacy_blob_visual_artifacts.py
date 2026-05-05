from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtQml, QtTest, QtWidgets
from PySide6.QtQuickControls2 import QQuickStyle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / ".artifacts" / "voice_ar3r_visual_revert"


def _voice_visual_state(state: str, energy: float = 0.0, *, active: bool = False) -> dict[str, object]:
    playback = "playing" if active else "idle"
    return {
        "playback_id": f"ar3r-visual-{state}",
        "voice_anchor_state": state,
        "voice_current_phase": "playback_active" if active else state,
        "speaking_visual_active": bool(active),
        "active_playback_status": playback,
        "voice_visual_available": True,
        "voice_visual_active": bool(active),
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": float(energy),
        "voice_visual_playback_id": f"ar3r-visual-{state}",
        "voice_visual_latest_age_ms": 3,
        "raw_audio_present": False,
    }


def _drain(app: QtWidgets.QApplication, ms: int = 60) -> None:
    app.processEvents()
    QtTest.QTest.qWait(ms)
    app.processEvents()


def _set_anchor_state(
    app: QtWidgets.QApplication,
    anchor: QtCore.QObject,
    *,
    renderer: str,
    state: str,
    energy: float = 0.0,
    active: bool = False,
    frames: int = 24,
) -> None:
    anchor.setProperty("anchorRenderer", renderer)
    anchor.setProperty("assistantState", state)
    anchor.setProperty("voiceState", {"voice_anchor_state": state, "raw_audio_present": False})
    anchor.setProperty("voiceVisualState", _voice_visual_state(state, energy, active=active))
    for frame in range(1, frames + 1):
        anchor.setProperty("visualClockWallTimeMs", 1000 + frame * 16)
        anchor.setProperty("visualClockDeltaMs", 16)
        anchor.setProperty("visualClockFrameCounter", frame)
        app.processEvents()
    _drain(app, 120)


def _grab(window: QtGui.QWindow) -> QtGui.QImage:
    image = window.grabWindow()
    if image.isNull():
        raise RuntimeError("QQuickWindow.grabWindow returned a null image")
    return image


def _compose_grid(images: list[QtGui.QImage], columns: int, cell_size: QtCore.QSize) -> QtGui.QImage:
    rows = (len(images) + columns - 1) // columns
    output = QtGui.QImage(
        columns * cell_size.width(),
        rows * cell_size.height(),
        QtGui.QImage.Format_ARGB32,
    )
    output.fill(QtGui.QColor("#02070b"))
    painter = QtGui.QPainter(output)
    try:
        for index, image in enumerate(images):
            x = (index % columns) * cell_size.width()
            y = (index // columns) * cell_size.height()
            painter.drawImage(QtCore.QRect(x, y, cell_size.width(), cell_size.height()), image)
    finally:
        painter.end()
    return output


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QQuickStyle.setStyle("Basic")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    engine = QtQml.QQmlApplicationEngine()
    engine.addImportPath(str(PROJECT_ROOT / "assets" / "qml"))
    qml = f"""
import QtQuick 2.15
import "file:///{(PROJECT_ROOT / "assets" / "qml" / "variants" / "stormforge").as_posix()}"

Window {{
    id: rootWindow
    width: 360
    height: 360
    visible: true
    color: "#02070b"

    StormforgeAnchorCore {{
        id: anchor
        objectName: "ar3rLegacyBlobArtifactAnchor"
        anchors.centerIn: parent
        width: 260
        height: 260
        compact: true
        anchorRenderer: "legacy_blob"
        visualizerDiagnosticMode: "pcm_stream_meter"
        renderLoopDiagnosticsEnabled: true
    }}
}}
"""
    engine.loadData(
        qml.encode("utf-8"),
        QtCore.QUrl.fromLocalFile(str(OUTPUT_DIR / "StormforgeAnchorAR3RVisualArtifacts.qml")),
    )
    if not engine.rootObjects():
        for error in engine.warnings():
            print(error, file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]
    anchor = window.findChild(QtCore.QObject, "ar3rLegacyBlobArtifactAnchor")
    if anchor is None:
        print("Stormforge anchor artifact harness did not create the anchor", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _drain(app, 160)

    captures: dict[str, QtGui.QImage] = {}
    _set_anchor_state(app, anchor, renderer="legacy_blob", state="idle", energy=0.0, active=False)
    captures["anchor_legacy_blob_idle.png"] = _grab(window)
    _set_anchor_state(app, anchor, renderer="legacy_blob", state="speaking", energy=0.22, active=True)
    captures["anchor_legacy_blob_speaking_low_energy.png"] = _grab(window)
    _set_anchor_state(app, anchor, renderer="legacy_blob", state="speaking", energy=0.88, active=True)
    captures["anchor_legacy_blob_speaking_high_energy.png"] = _grab(window)

    state_images: list[QtGui.QImage] = []
    for state, energy, active in [
        ("idle", 0.0, False),
        ("listening", 0.0, False),
        ("thinking", 0.0, False),
        ("acting", 0.0, False),
        ("speaking", 0.72, True),
        ("approval_required", 0.0, False),
        ("blocked", 0.0, False),
        ("failed", 0.0, False),
        ("unavailable", 0.0, False),
        ("mock_dev", 0.0, False),
    ]:
        _set_anchor_state(app, anchor, renderer="legacy_blob", state=state, energy=energy, active=active, frames=18)
        state_images.append(_grab(window))
    captures["anchor_legacy_blob_state_set.png"] = _compose_grid(
        state_images,
        columns=5,
        cell_size=QtCore.QSize(360, 360),
    )

    comparison_images: list[QtGui.QImage] = []
    for renderer in ["ar3_split", "legacy_blob"]:
        _set_anchor_state(app, anchor, renderer=renderer, state="speaking", energy=0.82, active=True, frames=24)
        comparison_images.append(_grab(window))
    captures["before_after_ar3_vs_legacy_blob.png"] = _compose_grid(
        comparison_images,
        columns=2,
        cell_size=QtCore.QSize(360, 360),
    )

    for filename, image in captures.items():
        image.save(str(OUTPUT_DIR / filename))

    engine.clearComponentCache()
    print(str(OUTPUT_DIR))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
