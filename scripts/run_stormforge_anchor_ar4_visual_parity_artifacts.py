from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtQml, QtTest, QtWidgets
from PySide6.QtQuickControls2 import QQuickStyle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / ".artifacts" / "voice_ar4_visual_parity"
REFERENCE_RENDERER = "legacy_blob_reference"
CANDIDATE_RENDERER = "legacy_blob_fast_candidate"
CANVAS_COST_MAP = {
    "static_or_rarely_changing": [
        "outer nautical glass disc",
        "static ring outlines",
        "bearing ticks",
        "quadrant marks",
        "helm crown",
        "compass needle scaffolding",
        "sonar and horizon markings",
        "etched ring segments",
    ],
    "low_frequency_animated": [
        "idle ring softness and breathing",
        "slow ring fragments",
        "state-tinted clamps and transition crossfades",
        "compass needle drift",
        "horizon drift",
    ],
    "high_frequency_voice_reactive": [
        "organic center blob expansion",
        "organic blob deformation",
        "speaking radiance",
        "audio-driven glow",
        "shimmer and glint motion",
        "speaking waveform/radiance arcs",
        "blob/ring/radiance scalar diagnostics",
    ],
    "current_reference_bottleneck": (
        "The approved legacy renderer repaints all of these in one Canvas on "
        "each voice frame. AR4 keeps it as the reference because the previous "
        "split renderer failed visual review."
    ),
    "raw_audio_present": False,
}


def _voice_visual_state(
    state: str,
    energy: float = 0.0,
    *,
    active: bool = False,
) -> dict[str, object]:
    playback = "playing" if active else "idle"
    return {
        "playback_id": f"ar4-visual-{state}",
        "voice_anchor_state": state,
        "voice_current_phase": "playback_active" if active else state,
        "speaking_visual_active": bool(active),
        "active_playback_status": playback,
        "voice_visual_available": True,
        "voice_visual_active": bool(active),
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy": float(energy),
        "voice_visual_playback_id": f"ar4-visual-{state}",
        "voice_visual_latest_age_ms": 3,
        "raw_audio_present": False,
    }


def _drain(app: QtWidgets.QApplication, ms: int = 60) -> None:
    app.processEvents()
    QtTest.QTest.qWait(ms)
    app.processEvents()


def _set_anchor_state(
    app: QtWidgets.QApplication,
    anchors: list[QtCore.QObject],
    *,
    state: str,
    energy: float = 0.0,
    active: bool = False,
    frames: int = 24,
) -> None:
    for anchor in anchors:
        anchor.setProperty("assistantState", state)
        anchor.setProperty("voiceState", {"voice_anchor_state": state, "raw_audio_present": False})
        anchor.setProperty("voiceVisualState", _voice_visual_state(state, energy, active=active))
    for frame in range(1, frames + 1):
        wall_time = 1000 + frame * 16
        for anchor in anchors:
            anchor.setProperty("visualClockWallTimeMs", wall_time)
            anchor.setProperty("visualClockDeltaMs", 16)
            anchor.setProperty("visualClockFrameCounter", frame)
        app.processEvents()
    _drain(app, 120)


def _grab(window: QtGui.QWindow) -> QtGui.QImage:
    image = window.grabWindow()
    if image.isNull():
        raise RuntimeError("QQuickWindow.grabWindow returned a null image")
    return image


def _compose_grid(
    images: list[QtGui.QImage],
    columns: int,
    cell_size: QtCore.QSize,
) -> QtGui.QImage:
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


def _image_difference(image: QtGui.QImage) -> dict[str, Any]:
    width = image.width() // 2
    height = image.height()
    if width <= 0 or height <= 0:
        return {
            "mean_abs_rgb_difference": None,
            "max_abs_rgb_difference": None,
            "pixel_count": 0,
            "raw_audio_present": False,
        }
    left = image.copy(0, 0, width, height)
    right = image.copy(width, 0, width, height)
    total = 0.0
    max_diff = 0
    count = width * height * 3
    for y in range(height):
        for x in range(width):
            a = left.pixelColor(x, y)
            b = right.pixelColor(x, y)
            dr = abs(a.red() - b.red())
            dg = abs(a.green() - b.green())
            db = abs(a.blue() - b.blue())
            total += dr + dg + db
            max_diff = max(max_diff, dr, dg, db)
    return {
        "mean_abs_rgb_difference": round(total / max(1, count), 6),
        "max_abs_rgb_difference": max_diff,
        "pixel_count": width * height,
        "raw_audio_present": False,
    }


def _write_report(captures: dict[str, QtGui.QImage]) -> None:
    differences = {
        name: _image_difference(image)
        for name, image in captures.items()
        if name.startswith("legacy_vs_candidate_")
    }
    report = {
        "probe": "stormforge_anchor_ar4_visual_parity",
        "renderer_modes": {
            "reference": REFERENCE_RENDERER,
            "candidate": CANDIDATE_RENDERER,
            "default": REFERENCE_RENDERER,
            "ar3_split_default": False,
        },
        "visual_parity_status": "needs_human_review",
        "visual_differences_noticed": (
            "Automated side-by-side captures are generated. Candidate is not "
            "promoted until the approved legacy blob look is manually accepted."
        ),
        "candidate_implementation_note": (
            "legacy_blob_fast_candidate currently preserves the approved legacy "
            "Canvas visual behavior for parity review; performance must be "
            "validated separately before it can become default."
        ),
        "canvas_cost_map": CANVAS_COST_MAP,
        "differences": differences,
        "artifacts": sorted(captures),
        "raw_audio_present": False,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "visual_parity_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        "# Stormforge Anchor AR4 Visual Parity",
        "",
        f"- Reference renderer: `{REFERENCE_RENDERER}`",
        f"- Candidate renderer: `{CANDIDATE_RENDERER}`",
        f"- Default renderer: `{REFERENCE_RENDERER}`",
        "- Visual parity status: `needs_human_review`",
        "- Privacy: scalar-only harness metadata, raw_audio_present=false",
        "",
        "## Canvas Cost Map",
        "- Static/rare: outer glass disc, ring outlines, bearing ticks, quadrant marks, helm crown, compass scaffolding, sonar/horizon markings, etched segments",
        "- Low frequency: idle breathing, slow ring fragments, state-tinted clamps, transition crossfades, compass/horizon drift",
        "- High frequency: organic blob expansion/deformation, speaking radiance, audio glow, shimmer/glint, speaking waveform/radiance arcs",
        "- Current reference bottleneck: all three groups still repaint in one approved legacy Canvas each voice frame",
        "",
        "## Difference Summary",
    ]
    for name, diff in differences.items():
        lines.append(
            f"- {name}: mean_abs_rgb_difference="
            f"{diff.get('mean_abs_rgb_difference')}, "
            f"max_abs_rgb_difference={diff.get('max_abs_rgb_difference')}"
        )
    (OUTPUT_DIR / "visual_parity_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


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
    width: 720
    height: 360
    visible: true
    color: "#02070b"

    Row {{
        anchors.fill: parent

        Item {{
            width: 360
            height: 360
            StormforgeAnchorCore {{
                id: referenceAnchor
                objectName: "ar4ReferenceAnchor"
                anchors.centerIn: parent
                width: 260
                height: 260
                compact: true
                anchorRenderer: "{REFERENCE_RENDERER}"
                visualizerDiagnosticMode: "pcm_stream_meter"
                renderLoopDiagnosticsEnabled: true
            }}
        }}

        Item {{
            width: 360
            height: 360
            StormforgeAnchorCore {{
                id: candidateAnchor
                objectName: "ar4CandidateAnchor"
                anchors.centerIn: parent
                width: 260
                height: 260
                compact: true
                anchorRenderer: "{CANDIDATE_RENDERER}"
                visualizerDiagnosticMode: "pcm_stream_meter"
                renderLoopDiagnosticsEnabled: true
            }}
        }}
    }}
}}
"""
    engine.loadData(
        qml.encode("utf-8"),
        QtCore.QUrl.fromLocalFile(str(OUTPUT_DIR / "StormforgeAnchorAR4VisualParity.qml")),
    )
    if not engine.rootObjects():
        for error in engine.warnings():
            print(error, file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]
    anchors = [
        window.findChild(QtCore.QObject, "ar4ReferenceAnchor"),
        window.findChild(QtCore.QObject, "ar4CandidateAnchor"),
    ]
    if any(anchor is None for anchor in anchors):
        print("Stormforge anchor parity harness did not create both anchors", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _drain(app, 160)

    captures: dict[str, QtGui.QImage] = {}
    for filename, state, energy, active in [
        ("legacy_vs_candidate_idle.png", "idle", 0.0, False),
        ("legacy_vs_candidate_speaking_low.png", "speaking", 0.22, True),
        ("legacy_vs_candidate_speaking_high.png", "speaking", 0.88, True),
    ]:
        _set_anchor_state(app, anchors, state=state, energy=energy, active=active)
        captures[filename] = _grab(window)

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
        _set_anchor_state(app, anchors, state=state, energy=energy, active=active, frames=18)
        state_images.append(_grab(window))
    captures["legacy_vs_candidate_state_set.png"] = _compose_grid(
        state_images,
        columns=2,
        cell_size=QtCore.QSize(720, 360),
    )

    sequence_images: list[QtGui.QImage] = []
    for energy in [0.0, 0.18, 0.42, 0.72, 0.94]:
        _set_anchor_state(app, anchors, state="speaking", energy=energy, active=True, frames=16)
        sequence_images.append(_grab(window))
    captures["legacy_vs_candidate_blob_sequence.png"] = _compose_grid(
        sequence_images,
        columns=1,
        cell_size=QtCore.QSize(720, 360),
    )

    for filename, image in captures.items():
        image.save(str(OUTPUT_DIR / filename))
    _write_report(captures)

    engine.clearComponentCache()
    print(str(OUTPUT_DIR))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
