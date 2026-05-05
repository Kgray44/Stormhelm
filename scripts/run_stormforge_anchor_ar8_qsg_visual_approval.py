from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtQml, QtWidgets
from PySide6.QtQuickControls2 import QQuickStyle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_stormforge_anchor_ar4_visual_parity_artifacts import (  # noqa: E402
    _compose_grid,
    _drain,
    _grab,
    _image_difference,
    _set_anchor_state,
)
from stormhelm.core.voice.live_kraken_probe import (  # noqa: E402
    assert_no_raw_audio_payload,
    qsg_candidate_promotion_gate,
    sanitize_kraken_payload,
)


OUTPUT_DIR = PROJECT_ROOT / ".artifacts" / "voice_ar8_qsg_visual_approval"
REFERENCE_RENDERER = "legacy_blob_reference"
QSG_RENDERER = "legacy_blob_qsg_candidate"
VALID_VISUAL_STATUSES = {"pending_review", "approved", "rejected"}


def _normalize_visual_status(value: str) -> str:
    status = str(value or "pending_review").strip().lower()
    if status not in VALID_VISUAL_STATUSES:
        raise ValueError(
            f"visual status must be one of {sorted(VALID_VISUAL_STATUSES)}, got {value!r}"
        )
    return status


def _save_captures(output_dir: Path, captures: dict[str, QtGui.QImage]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, image in captures.items():
        image.save(str(output_dir / filename))


def _artifact_paths(output_dir: Path, captures: dict[str, QtGui.QImage]) -> dict[str, str]:
    return {
        name: str((output_dir / name).resolve())
        for name in sorted(captures)
    }


def _write_report(
    output_dir: Path,
    captures: dict[str, QtGui.QImage],
    *,
    visual_status: str,
    human_approval: str,
) -> dict[str, Any]:
    differences = {
        name: _image_difference(image)
        for name, image in captures.items()
        if name.startswith("legacy_vs_qsg_")
    }
    visual_notes = [
        "QSG must be treated as a visual clone of legacy_blob_reference.",
        "Visible differences should be handled as renderer bugs, not design choices.",
        "Default remains legacy_blob_reference until human review explicitly approves QSG.",
    ]
    gate = qsg_candidate_promotion_gate(
        visual_status=visual_status,
        live_report={"renderer_comparison": [], "raw_audio_present": False},
        human_approval=human_approval,
        visual_differences=visual_notes,
    )
    top_level_reasons = ["live_kraken_validation_required"]
    if visual_status != "approved":
        top_level_reasons.append("visual_status_not_approved")
    if not str(human_approval or "").strip():
        top_level_reasons.append("human_approval_missing")
    report = sanitize_kraken_payload(
        {
            "probe": "stormforge_anchor_ar8_qsg_visual_approval",
            "renderer_modes": {
                "reference": REFERENCE_RENDERER,
                "candidate": QSG_RENDERER,
                "default": REFERENCE_RENDERER,
                "candidate_promoted_to_default": False,
            },
            "qsg_candidate_visual_status": visual_status,
            "qsg_candidate_default_eligible": False,
            "qsg_candidate_rejection_reason": ";".join(sorted(top_level_reasons)),
            "qsg_candidate_visual_differences": visual_notes,
            "visual_parity_status": visual_status,
            "visual_parity_gate": gate,
            "differences": differences,
            "artifacts": _artifact_paths(output_dir, captures),
            "required_live_validation": {
                "anchorPaintFpsDuringSpeaking": ">=30",
                "dynamicCorePaintFpsDuringSpeaking": ">=30",
                "renderCadenceDuringSpeakingStable": True,
                "requestPaintStormDetected": False,
                "state_lifetime_classifications_clean": True,
                "raw_audio_present": False,
            },
            "default_renderer_after_pass": REFERENCE_RENDERER,
            "raw_audio_present": False,
        }
    )
    assert_no_raw_audio_payload(report)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "visual_parity_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        "# Stormforge Anchor AR8 QSG Visual Approval",
        "",
        f"- Reference renderer: `{REFERENCE_RENDERER}`",
        f"- Candidate renderer: `{QSG_RENDERER}`",
        f"- Default renderer: `{REFERENCE_RENDERER}`",
        f"- QSG visual status: `{visual_status}`",
        "- QSG default eligible: `false`",
        f"- Rejection reason: `{report.get('qsg_candidate_rejection_reason')}`",
        "- Privacy: scalar-only metadata, raw_audio_present=false",
        "",
        "## Artifacts",
    ]
    for name, path in report["artifacts"].items():
        if name == "raw_audio_present":
            continue
        lines.append(f"- `{name}`: `{path}`")
    lines.extend(["", "## Image Diff Metrics"])
    for name, diff in differences.items():
        lines.append(
            f"- `{name}`: mean_abs_rgb_difference="
            f"{diff.get('mean_abs_rgb_difference')}, "
            f"max_abs_rgb_difference={diff.get('max_abs_rgb_difference')}"
        )
    lines.extend(
        [
            "",
            "## Review Gate",
            "- QSG is not promoted by this artifact package.",
            "- Human approval plus a clean live Kraken run are both required before default promotion.",
            "- Sync classifications are reported separately and are not visual parity approval.",
        ]
    )
    (output_dir / "visual_parity_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return report


def _build_qml(output_dir: Path) -> bytes:
    stormforge_dir = PROJECT_ROOT / "assets" / "qml" / "variants" / "stormforge"
    return f"""
import QtQuick 2.15
import "file:///{stormforge_dir.as_posix()}"

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
                objectName: "ar8ReferenceAnchor"
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
                id: qsgAnchor
                objectName: "ar8QsgAnchor"
                anchors.centerIn: parent
                width: 260
                height: 260
                compact: true
                anchorRenderer: "{QSG_RENDERER}"
                visualizerDiagnosticMode: "pcm_stream_meter"
                renderLoopDiagnosticsEnabled: true
            }}
        }}
    }}
}}
""".encode("utf-8")


def _capture_visuals(
    app: QtWidgets.QApplication,
    window: QtGui.QWindow,
    anchors: list[QtCore.QObject],
) -> dict[str, QtGui.QImage]:
    _drain(app, 160)
    captures: dict[str, QtGui.QImage] = {}
    for filename, state, energy, active, frames in [
        ("legacy_vs_qsg_idle.png", "idle", 0.0, False, 36),
        ("legacy_vs_qsg_speaking_low.png", "speaking", 0.24, True, 36),
        ("legacy_vs_qsg_speaking_high.png", "speaking", 0.88, True, 36),
    ]:
        _set_anchor_state(app, anchors, state=state, energy=energy, active=active, frames=frames)
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
        _set_anchor_state(app, anchors, state=state, energy=energy, active=active, frames=24)
        state_images.append(_grab(window))
    captures["legacy_vs_qsg_state_set.png"] = _compose_grid(
        state_images,
        columns=2,
        cell_size=QtCore.QSize(720, 360),
    )

    sequence_images: list[QtGui.QImage] = []
    for energy in [0.0, 0.16, 0.36, 0.58, 0.82, 0.96, 0.42, 0.12]:
        _set_anchor_state(app, anchors, state="speaking", energy=energy, active=True, frames=16)
        sequence_images.append(_grab(window))
    captures["legacy_vs_qsg_blob_sequence.png"] = _compose_grid(
        sequence_images,
        columns=2,
        cell_size=QtCore.QSize(720, 360),
    )

    motion_images: list[QtGui.QImage] = []
    for state, energy, active in [
        ("idle", 0.0, False),
        ("idle", 0.0, False),
        ("speaking", 0.35, True),
        ("speaking", 0.75, True),
        ("acting", 0.0, False),
        ("thinking", 0.0, False),
        ("listening", 0.0, False),
        ("speaking", 0.55, True),
    ]:
        _set_anchor_state(app, anchors, state=state, energy=energy, active=active, frames=18)
        motion_images.append(_grab(window))
    captures["legacy_vs_qsg_motion_contact_sheet.png"] = _compose_grid(
        motion_images,
        columns=2,
        cell_size=QtCore.QSize(720, 360),
    )
    return captures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate AR8 QSG visual approval artifacts against legacy_blob_reference."
    )
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument(
        "--visual-status",
        choices=sorted(VALID_VISUAL_STATUSES),
        default="pending_review",
    )
    parser.add_argument("--human-approval", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    visual_status = _normalize_visual_status(args.visual_status)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QQuickStyle.setStyle("Basic")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    engine = QtQml.QQmlApplicationEngine()
    engine.addImportPath(str(PROJECT_ROOT / "assets" / "qml"))
    output_dir.mkdir(parents=True, exist_ok=True)
    engine.loadData(
        _build_qml(output_dir),
        QtCore.QUrl.fromLocalFile(str(output_dir / "StormforgeAnchorAR8QsgVisualApproval.qml")),
    )
    if not engine.rootObjects():
        for error in engine.warnings():
            print(error, file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]
    anchors = [
        window.findChild(QtCore.QObject, "ar8ReferenceAnchor"),
        window.findChild(QtCore.QObject, "ar8QsgAnchor"),
    ]
    if any(anchor is None for anchor in anchors):
        print("Stormforge AR8 visual approval harness did not create both anchors", file=sys.stderr)
        return 1

    captures = _capture_visuals(app, window, anchors)
    _save_captures(output_dir, captures)
    report = _write_report(
        output_dir,
        captures,
        visual_status=visual_status,
        human_approval=args.human_approval,
    )

    engine.clearComponentCache()
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "visual_status": report.get("qsg_candidate_visual_status"),
                "qsg_candidate_default_eligible": report.get("qsg_candidate_default_eligible"),
                "report": str(output_dir / "visual_parity_report.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
