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


OUTPUT_DIR = PROJECT_ROOT / ".artifacts" / "voice_ar10_qsg_reflection_parity"
REFERENCE_RENDERER = "legacy_blob_reference"
QSG_RENDERER = "legacy_blob_qsg_candidate"
VALID_VISUAL_STATUSES = {"pending_review", "approved", "rejected"}
VALID_VISUAL_APPROVALS = {"pending", "approved", "rejected"}


def _normalize_visual_status(value: str) -> str:
    status = str(value or "pending_review").strip().lower()
    status = status.replace("-", "_").replace(" ", "_")
    if status == "pending":
        status = "pending_review"
    if status not in VALID_VISUAL_STATUSES:
        raise ValueError(
            f"visual status must be one of {sorted(VALID_VISUAL_STATUSES)}, got {value!r}"
        )
    return status


def _normalize_visual_approval(value: str) -> str:
    approval = str(value or "pending").strip().lower()
    approval = approval.replace("-", "_").replace(" ", "_")
    if approval == "pending_review":
        approval = "pending"
    if approval not in VALID_VISUAL_APPROVALS:
        raise ValueError(
            f"visual approval must be one of {sorted(VALID_VISUAL_APPROVALS)}, got {value!r}"
        )
    return approval


def _visual_status_from_approval(value: str) -> str:
    approval = _normalize_visual_approval(value)
    return "pending_review" if approval == "pending" else approval


def _save_captures(output_dir: Path, captures: dict[str, QtGui.QImage]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, image in captures.items():
        image.save(str(output_dir / filename))


def _artifact_paths(output_dir: Path, captures: dict[str, QtGui.QImage]) -> dict[str, str]:
    return {name: str((output_dir / name).resolve()) for name in sorted(captures)}


def _reflection_closeup(image: QtGui.QImage) -> QtGui.QImage:
    cell_width = image.width() // 2
    cell_height = image.height()
    crop_size = min(152, cell_width, cell_height)
    y = max(0, (cell_height - crop_size) // 2)
    left_x = max(0, (cell_width - crop_size) // 2)
    right_x = cell_width + left_x
    output = QtGui.QImage(crop_size * 2, crop_size, QtGui.QImage.Format_ARGB32)
    output.fill(QtGui.QColor("#02070b"))
    painter = QtGui.QPainter(output)
    try:
        painter.drawImage(
            QtCore.QRect(0, 0, crop_size, crop_size),
            image.copy(left_x, y, crop_size, crop_size),
        )
        painter.drawImage(
            QtCore.QRect(crop_size, 0, crop_size, crop_size),
            image.copy(right_x, y, crop_size, crop_size),
        )
    finally:
        painter.end()
    return output


def _build_qml() -> bytes:
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
                objectName: "ar10ReferenceAnchor"
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
                objectName: "ar10QsgAnchor"
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
    closeups: dict[str, QtGui.QImage] = {}
    for filename, state, energy, active, frames in [
        ("legacy_vs_qsg_idle.png", "idle", 0.0, False, 36),
        ("legacy_vs_qsg_speaking_low.png", "speaking", 0.24, True, 36),
        ("legacy_vs_qsg_speaking_high.png", "speaking", 0.88, True, 36),
    ]:
        _set_anchor_state(app, anchors, state=state, energy=energy, active=active, frames=frames)
        image = _grab(window)
        captures[filename] = image
        closeup_name = filename.replace("legacy_vs_qsg_", "legacy_vs_qsg_reflection_closeup_")
        closeups[closeup_name] = _reflection_closeup(image)

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
    sequence_closeups: list[QtGui.QImage] = []
    for energy in [0.0, 0.16, 0.36, 0.58, 0.82, 0.96, 0.42, 0.12]:
        _set_anchor_state(app, anchors, state="speaking", energy=energy, active=True, frames=16)
        image = _grab(window)
        sequence_images.append(image)
        sequence_closeups.append(_reflection_closeup(image))
    captures["legacy_vs_qsg_blob_sequence.png"] = _compose_grid(
        sequence_images,
        columns=2,
        cell_size=QtCore.QSize(720, 360),
    )
    captures["legacy_vs_qsg_reflection_sequence.png"] = _compose_grid(
        sequence_closeups,
        columns=2,
        cell_size=QtCore.QSize(sequence_closeups[0].width(), sequence_closeups[0].height()),
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
    captures.update(closeups)
    return captures


def _write_report(
    output_dir: Path,
    captures: dict[str, QtGui.QImage],
    qsg_anchor: QtCore.QObject,
    *,
    visual_status: str,
    human_approval: str,
    visual_approval: str = "pending",
    visual_approval_reason: str = "",
) -> dict[str, Any]:
    differences = {
        name: _image_difference(image)
        for name, image in captures.items()
        if name.startswith("legacy_vs_qsg_")
    }
    reflection_diagnostics = {
        "qsgReflectionParityVersion": qsg_anchor.property("qsgReflectionParityVersion"),
        "qsgReflectionShape": qsg_anchor.property("qsgReflectionShape"),
        "qsgReflectionRoundedRectDisabled": bool(
            qsg_anchor.property("qsgReflectionRoundedRectDisabled")
        ),
        "qsgReflectionUsesLegacyGeometry": bool(
            qsg_anchor.property("qsgReflectionUsesLegacyGeometry")
        ),
        "qsgReflectionAnimated": bool(qsg_anchor.property("qsgReflectionAnimated")),
        "qsgReflectionOffsetX": float(qsg_anchor.property("qsgReflectionOffsetX") or 0.0),
        "qsgReflectionOffsetY": float(qsg_anchor.property("qsgReflectionOffsetY") or 0.0),
        "qsgReflectionOpacity": float(qsg_anchor.property("qsgReflectionOpacity") or 0.0),
        "qsgReflectionSoftness": float(qsg_anchor.property("qsgReflectionSoftness") or 0.0),
        "qsgReflectionClipInsideBlob": bool(
            qsg_anchor.property("qsgReflectionClipInsideBlob")
        ),
        "qsgBlobEdgeFeatherVersion": qsg_anchor.property("qsgBlobEdgeFeatherVersion"),
        "qsgBlobEdgeFeatherEnabled": bool(qsg_anchor.property("qsgBlobEdgeFeatherEnabled")),
        "qsgBlobEdgeFeatherMatchesLegacySoftness": bool(
            qsg_anchor.property("qsgBlobEdgeFeatherMatchesLegacySoftness")
        ),
        "qsgBlobEdgeFeatherOpacity": float(
            qsg_anchor.property("qsgBlobEdgeFeatherOpacity") or 0.0
        ),
        "raw_audio_present": False,
    }
    visual_differences: list[str] = []
    if not reflection_diagnostics["qsgReflectionRoundedRectDisabled"]:
        visual_differences.append("rounded_rect_reflection_visible")
    if reflection_diagnostics["qsgReflectionShape"] != "legacy_glint":
        visual_differences.append("reflection_shape_mismatch")
    if not reflection_diagnostics["qsgReflectionAnimated"]:
        visual_differences.append("reflection_animation_mismatch")
    if not reflection_diagnostics["qsgReflectionClipInsideBlob"]:
        visual_differences.append("center_glass_highlight_mismatch")
    if not reflection_diagnostics["qsgBlobEdgeFeatherEnabled"]:
        visual_differences.append("center_glass_highlight_mismatch")

    gate = qsg_candidate_promotion_gate(
        visual_status=visual_status,
        live_report={"renderer_comparison": [], "raw_audio_present": False},
        human_approval=human_approval,
        visual_differences=visual_differences,
    )
    visual_gate_open = (
        visual_approval == "approved"
        and visual_status == "approved"
        and bool(str(human_approval or "").strip())
        and not visual_differences
    )
    live_gate_open = False
    top_level_reasons = ["live_kraken_validation_required"]
    if visual_status != "approved":
        top_level_reasons.append("visual_status_not_approved")
    if not str(human_approval or "").strip():
        top_level_reasons.append("human_approval_missing")
    top_level_reasons.extend(visual_differences)

    report = sanitize_kraken_payload(
        {
            "probe": "stormforge_anchor_ar10_reflection_parity",
            "renderer_modes": {
                "reference": REFERENCE_RENDERER,
                "candidate": QSG_RENDERER,
                "default": REFERENCE_RENDERER,
                "candidate_promoted_to_default": False,
            },
            "qsg_candidate_visual_status": visual_status,
            "qsg_visual_approval": visual_approval,
            "qsg_visual_approval_reason": visual_approval_reason,
            "qsg_default_eligible_visual_gate": bool(visual_gate_open),
            "qsg_default_eligible_live_gate": bool(live_gate_open),
            "qsg_default_eligible_final": False,
            "qsg_candidate_default_eligible": False,
            "qsg_candidate_rejection_reason": ";".join(sorted(set(top_level_reasons))),
            "qsg_candidate_visual_differences": visual_differences,
            "visual_parity_status": visual_status,
            "visual_parity_gate": gate,
            "reflection_diagnostics": reflection_diagnostics,
            "differences": differences,
            "artifacts": _artifact_paths(output_dir, captures),
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
        "# Stormforge Anchor AR10 Reflection Parity",
        "",
        f"- Reference renderer: `{REFERENCE_RENDERER}`",
        f"- Candidate renderer: `{QSG_RENDERER}`",
        f"- Default renderer: `{REFERENCE_RENDERER}`",
        f"- QSG visual status: `{visual_status}`",
        f"- QSG visual approval: `{visual_approval}`",
        f"- QSG visual approval reason: `{visual_approval_reason}`",
        f"- QSG default eligible visual gate: `{visual_gate_open}`",
        f"- QSG default eligible live gate: `{live_gate_open}`",
        "- QSG default eligible final: `false`",
        "- QSG default eligible: `false`",
        f"- Rejection reason: `{report.get('qsg_candidate_rejection_reason')}`",
        "- Privacy: scalar-only metadata, raw_audio_present=false",
        "",
        "## Reflection Diagnostics",
    ]
    for key, value in reflection_diagnostics.items():
        if key != "raw_audio_present":
            lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Artifacts"])
    for name, path in report["artifacts"].items():
        lines.append(f"- `{name}`: `{path}`")
    (output_dir / "visual_parity_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    roi_lines = [
        "# Reflection ROI Diff Report",
        "",
        "- ROI is a center crop of the reference/candidate blob area.",
        "- Diff metrics are RGB-only and are for triage; human review remains the gate.",
        "",
    ]
    for name, diff in differences.items():
        if "reflection_closeup" in name or "reflection_sequence" in name:
            roi_lines.append(
                f"- `{name}`: mean_abs_rgb_difference="
                f"{diff.get('mean_abs_rgb_difference')}, "
                f"max_abs_rgb_difference={diff.get('max_abs_rgb_difference')}"
            )
    roi_lines.append("\n- raw_audio_present=false")
    (output_dir / "reflection_roi_diff_report.md").write_text(
        "\n".join(roi_lines) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate AR10 QSG reflection parity artifacts against legacy_blob_reference."
    )
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument(
        "--visual-status",
        choices=sorted(VALID_VISUAL_STATUSES),
        default="pending_review",
    )
    parser.add_argument(
        "--visual-approval",
        choices=sorted(VALID_VISUAL_APPROVALS),
        default=None,
        help="Explicit AR11 human approval state: pending, approved, or rejected.",
    )
    parser.add_argument("--visual-approval-reason", default="")
    parser.add_argument("--human-approval", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    visual_approval = _normalize_visual_approval(
        args.visual_approval if args.visual_approval is not None else args.visual_status
    )
    visual_status = _visual_status_from_approval(visual_approval)
    human_approval = (
        args.human_approval
        or (args.visual_approval_reason if visual_approval == "approved" else "")
    )
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QQuickStyle.setStyle("Basic")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    engine = QtQml.QQmlApplicationEngine()
    engine.addImportPath(str(PROJECT_ROOT / "assets" / "qml"))
    output_dir.mkdir(parents=True, exist_ok=True)
    engine.loadData(
        _build_qml(),
        QtCore.QUrl.fromLocalFile(str(output_dir / "StormforgeAnchorAR10ReflectionParity.qml")),
    )
    if not engine.rootObjects():
        for error in engine.warnings():
            print(error, file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]
    anchors = [
        window.findChild(QtCore.QObject, "ar10ReferenceAnchor"),
        window.findChild(QtCore.QObject, "ar10QsgAnchor"),
    ]
    if any(anchor is None for anchor in anchors):
        print("Stormforge AR10 reflection harness did not create both anchors", file=sys.stderr)
        return 1

    captures = _capture_visuals(app, window, anchors)
    _save_captures(output_dir, captures)
    report = _write_report(
        output_dir,
        captures,
        anchors[1],
        visual_status=visual_status,
        human_approval=human_approval,
        visual_approval=visual_approval,
        visual_approval_reason=args.visual_approval_reason,
    )

    engine.clearComponentCache()
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "visual_status": report.get("qsg_candidate_visual_status"),
                "visual_approval": report.get("qsg_visual_approval"),
                "qsg_candidate_default_eligible": report.get("qsg_candidate_default_eligible"),
                "rejection_reason": report.get("qsg_candidate_rejection_reason"),
                "report": str(output_dir / "visual_parity_report.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
