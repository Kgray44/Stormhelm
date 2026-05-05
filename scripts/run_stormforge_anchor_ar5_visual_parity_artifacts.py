from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtQml, QtWidgets
from PySide6.QtQuickControls2 import QQuickStyle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_stormforge_anchor_ar4_visual_parity_artifacts import (  # noqa: E402
    _compose_grid,
    _drain,
    _grab,
    _image_difference,
    _set_anchor_state,
)


OUTPUT_DIR = PROJECT_ROOT / ".artifacts" / "voice_ar5_visual_parity"
REFERENCE_RENDERER = "legacy_blob_reference"
CANDIDATE_RENDERER = "legacy_blob_qsg_candidate"


def _write_report(captures: dict[str, QtGui.QImage]) -> None:
    differences = {
        name: _image_difference(image)
        for name, image in captures.items()
        if name.startswith("legacy_vs_new_")
    }
    report = {
        "probe": "stormforge_anchor_ar5_visual_parity",
        "renderer_modes": {
            "reference": REFERENCE_RENDERER,
            "candidate": CANDIDATE_RENDERER,
            "default": REFERENCE_RENDERER,
            "candidate_promoted_to_default": False,
        },
        "visual_parity_status": "needs_human_review",
        "known_visual_differences": (
            "Automated QSG candidate captures are generated for review. Any "
            "noticeable visual difference should be treated as a renderer bug."
        ),
        "human_review_notes": (
            "Default remains legacy_blob_reference until human review accepts "
            "the candidate as a visual clone."
        ),
        "implementation_note": (
            "legacy_blob_qsg_candidate uses the cached static frame path plus a "
            "scene-graph Shape clone of the official legacy blob aperture "
            "instead of the full legacy Canvas paint path for voice frames."
        ),
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
        "# Stormforge Anchor AR5 Visual Parity",
        "",
        f"- Reference renderer: `{REFERENCE_RENDERER}`",
        f"- Candidate renderer: `{CANDIDATE_RENDERER}`",
        f"- Default renderer: `{REFERENCE_RENDERER}`",
        "- Visual parity status: `needs_human_review`",
        "- Privacy: scalar-only harness metadata, raw_audio_present=false",
        "",
        "## Difference Summary",
    ]
    for name, diff in differences.items():
        lines.append(
            f"- {name}: mean_abs_rgb_difference="
            f"{diff.get('mean_abs_rgb_difference')}, "
            f"max_abs_rgb_difference={diff.get('max_abs_rgb_difference')}"
        )
    lines.extend(
        [
            "",
            "## Review Notes",
            "- Treat visible differences as renderer bugs, not design choices.",
            "- The candidate is not the default.",
        ]
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
                objectName: "ar5ReferenceAnchor"
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
                objectName: "ar5CandidateAnchor"
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
        QtCore.QUrl.fromLocalFile(str(OUTPUT_DIR / "StormforgeAnchorAR5VisualParity.qml")),
    )
    if not engine.rootObjects():
        for error in engine.warnings():
            print(error, file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]
    anchors = [
        window.findChild(QtCore.QObject, "ar5ReferenceAnchor"),
        window.findChild(QtCore.QObject, "ar5CandidateAnchor"),
    ]
    if any(anchor is None for anchor in anchors):
        print("Stormforge anchor parity harness did not create both anchors", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _drain(app, 160)

    captures: dict[str, QtGui.QImage] = {}
    for filename, state, energy, active in [
        ("legacy_vs_new_idle.png", "idle", 0.0, False),
        ("legacy_vs_new_speaking_low.png", "speaking", 0.22, True),
        ("legacy_vs_new_speaking_high.png", "speaking", 0.88, True),
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
    captures["legacy_vs_new_state_set.png"] = _compose_grid(
        state_images,
        columns=2,
        cell_size=QtCore.QSize(720, 360),
    )

    sequence_images: list[QtGui.QImage] = []
    for energy in [0.0, 0.18, 0.42, 0.72, 0.94]:
        _set_anchor_state(app, anchors, state="speaking", energy=energy, active=True, frames=16)
        sequence_images.append(_grab(window))
    captures["legacy_vs_new_blob_sequence.png"] = _compose_grid(
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
