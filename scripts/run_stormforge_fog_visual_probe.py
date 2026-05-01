from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtQml, QtTest, QtWidgets
from PySide6.QtQuickControls2 import QQuickStyle


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "qml"


GHOST_QML = r"""
import QtQuick 2.15
import QtQuick.Window 2.15
import "variants/stormforge"

Window {
    id: win
    objectName: "stormforgeFogProofWindow"
    width: 1000
    height: 680
    visible: true
    color: "#02070b"

    StormforgeGhostShell {
        id: ghost
        objectName: "stormforgeFogProofGhost"
        anchors.fill: parent
        statusLine: "Awaiting approval."
        connectionLabel: "Signal steady"
        timeLabel: "14:12"
        stormforgeFogConfig: ({FOG_CONFIG})
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
            {"title": "Verification pending", "subtitle": "Truth", "body": "No install claim yet.", "resultState": "unverified"}
        ]
        actionStrip: [
            {"label": "Open Deck", "localAction": "open_deck", "state": "planned"},
            {"label": "Cancel", "sendText": "cancel", "state": "blocked"}
        ]
        voiceState: {
            "voice_current_phase": "listening",
            "voice_anchor_state": "listening",
            "speaking_visual_active": false,
            "voice_audio_reactive_available": false
        }
    }
}
"""


def fog_config(*, enabled: bool, debug_visible: bool = False) -> str:
    return (
        "{"
        f'"enabled": {str(enabled).lower()},'
        '"mode": "volumetric",'
        '"quality": "medium",'
        '"intensity": 0.35,'
        '"motion": true,'
        '"edgeFog": true,'
        '"foregroundWisps": true,'
        '"qualitySamples": 14,'
        '"density": 0.62,'
        '"driftSpeed": 0.055,'
        '"driftDirection": "right_to_left",'
        '"driftDirectionX": -1.0,'
        '"driftDirectionY": 0.05,'
        '"flowScale": 1.0,'
        '"crosswindWobble": 0.18,'
        '"rollingSpeed": 0.035,'
        '"wispStretch": 1.8,'
        '"noiseScale": 1.12,'
        '"edgeDensity": 0.88,'
        '"lowerFogBias": 0.45,'
        '"centerClearRadius": 0.40,'
        '"centerClearStrength": 0.65,'
        '"foregroundAmount": 0.18,'
        '"foregroundOpacityLimit": 0.08,'
        '"opacityLimit": 0.22,'
        '"protectedCenterX": 0.50,'
        '"protectedCenterY": 0.58,'
        '"protectedRadius": 0.36,'
        '"anchorCenterX": 0.50,'
        '"anchorCenterY": 0.30,'
        '"anchorRadius": 0.18,'
        '"cardClearStrength": 0.72,'
        f'"debugVisible": {str(debug_visible).lower()},'
        '"debugIntensityMultiplier": 3.0,'
        '"debugTint": true'
        "}"
    )


def make_window(enabled: bool, debug_visible: bool) -> tuple[QtQml.QQmlEngine, QtQml.QQmlComponent, QtGui.QWindow]:
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(ASSETS))
    component = QtQml.QQmlComponent(engine)
    qml = GHOST_QML.replace("{FOG_CONFIG}", fog_config(enabled=enabled, debug_visible=debug_visible))
    component.setData(
        qml.encode("utf-8"),
        QtCore.QUrl.fromLocalFile(str(ASSETS / "StormforgeFogProofHarness.qml")),
    )
    if not component.isReady():
        raise RuntimeError([error.toString() for error in component.errors()])
    window = component.create()
    if window is None:
        raise RuntimeError([error.toString() for error in component.errors()])
    QtQml.QQmlEngine.setObjectOwnership(window, QtQml.QQmlEngine.ObjectOwnership.CppOwnership)
    window.raise_()
    window.requestActivate()
    app = QtWidgets.QApplication.instance()
    for _ in range(12):
        app.processEvents()
        QtTest.QTest.qWait(50)
    return engine, component, window


def qml_value(obj: QtCore.QObject, key: str) -> Any:
    value = obj.property(key)
    if hasattr(value, "toVariant"):
        return value.toVariant()
    return value


def diagnostics(window: QtGui.QWindow) -> dict[str, Any]:
    fog = window.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")
    atmosphere = window.findChild(QtCore.QObject, "stormforgeGhostAtmosphereSlot")
    if fog is None:
        return {"missing": "stormforgeVolumetricFogLayer"}
    keys = [
        "fogEnabledRequested",
        "fogActive",
        "fogVisible",
        "shaderEnabled",
        "fallbackEnabled",
        "quality",
        "qualitySamples",
        "intensity",
        "effectiveOpacity",
        "animationRunning",
        "layerWidth",
        "layerHeight",
        "zLayer",
        "renderMode",
        "maskStrengths",
        "disabledReason",
        "debugVisible",
        "debugIntensityMultiplier",
        "motionControls",
        "driftDirection",
        "driftDirectionX",
        "driftDirectionY",
        "flowScale",
        "crosswindWobble",
        "rollingSpeed",
        "wispStretch",
    ]
    data = {key: qml_value(fog, key) for key in keys}
    if atmosphere is not None:
        data["atmosphereFogActive"] = qml_value(atmosphere, "fogActive")
        data["atmosphereVisible"] = qml_value(atmosphere, "visible")
        data["atmosphereZ"] = qml_value(atmosphere, "z")
    return data


def grab(window: QtGui.QWindow, path: Path) -> QtGui.QImage:
    app = QtWidgets.QApplication.instance()
    app.processEvents()
    image = window.grabWindow()
    target_size = QtCore.QSize(int(window.width()), int(window.height()))
    if image.size() != target_size:
        image = image.scaled(
            target_size,
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
    image.save(str(path))
    return image


def image_bytes(image: QtGui.QImage) -> tuple[int, int, int, bytes]:
    converted = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    return (
        converted.width(),
        converted.height(),
        converted.bytesPerLine(),
        converted.constBits().tobytes(),
    )


def compare_images(first: QtGui.QImage, second: QtGui.QImage, diff_path: Path | None = None) -> dict[str, Any]:
    first_width, first_height, first_bpl, first_data = image_bytes(first)
    second_width, second_height, second_bpl, second_data = image_bytes(second)
    if (first_width, first_height) != (second_width, second_height):
        return {
            "size": [first_width, first_height],
            "second_size": [second_width, second_height],
            "mean_abs_rgba": None,
            "significant_pixels": None,
            "error": "image_size_mismatch",
        }

    total = first_width * first_height
    channel_sum = [0, 0, 0, 0]
    significant_pixels = 0
    diff_image = (
        QtGui.QImage(first_width, first_height, QtGui.QImage.Format.Format_RGBA8888)
        if diff_path is not None
        else None
    )

    for y in range(first_height):
        first_offset = y * first_bpl
        second_offset = y * second_bpl
        for x in range(first_width):
            first_index = first_offset + x * 4
            second_index = second_offset + x * 4
            dr = abs(first_data[first_index] - second_data[second_index])
            dg = abs(first_data[first_index + 1] - second_data[second_index + 1])
            db = abs(first_data[first_index + 2] - second_data[second_index + 2])
            da = abs(first_data[first_index + 3] - second_data[second_index + 3])
            channel_sum[0] += dr
            channel_sum[1] += dg
            channel_sum[2] += db
            channel_sum[3] += da
            if dr + dg + db + da > 12:
                significant_pixels += 1
            if diff_image is not None:
                diff_image.setPixelColor(
                    x,
                    y,
                    QtGui.QColor(
                        min(255, dr * 10),
                        min(255, dg * 10),
                        min(255, db * 10),
                        255,
                    ),
                )

    if diff_image is not None:
        diff_image.save(str(diff_path))

    return {
        "size": [first_width, first_height],
        "mean_abs_rgba": [round(value / total, 4) for value in channel_sum],
        "significant_pixels": significant_pixels,
    }


def estimate_fog_motion_direction(
    off_image: QtGui.QImage,
    on_t0_image: QtGui.QImage,
    on_t1_image: QtGui.QImage,
) -> dict[str, Any]:
    off_width, off_height, off_bpl, off_data = image_bytes(off_image)
    t0_width, t0_height, t0_bpl, t0_data = image_bytes(on_t0_image)
    t1_width, t1_height, t1_bpl, t1_data = image_bytes(on_t1_image)
    if (off_width, off_height) != (t0_width, t0_height) or (off_width, off_height) != (
        t1_width,
        t1_height,
    ):
        return {
            "estimated_direction": "unknown",
            "estimated_horizontal_shift_pixels": 0,
            "error": "image_size_mismatch",
        }

    candidates = range(-80, 82, 2)
    best_shift = 0
    best_score: float | None = None
    best_samples = 0
    for shift in candidates:
        score = 0
        samples = 0
        for y in range(0, off_height, 4):
            off_row = y * off_bpl
            t0_row = y * t0_bpl
            t1_row = y * t1_bpl
            for x in range(0, off_width, 4):
                t0_x = x - shift
                if t0_x < 0 or t0_x >= off_width:
                    continue
                off_t0_index = off_row + t0_x * 4
                t0_index = t0_row + t0_x * 4
                off_t1_index = off_row + x * 4
                t1_index = t1_row + x * 4
                t0_fog = (
                    abs(t0_data[t0_index] - off_data[off_t0_index])
                    + abs(t0_data[t0_index + 1] - off_data[off_t0_index + 1])
                    + abs(t0_data[t0_index + 2] - off_data[off_t0_index + 2])
                )
                t1_fog = (
                    abs(t1_data[t1_index] - off_data[off_t1_index])
                    + abs(t1_data[t1_index + 1] - off_data[off_t1_index + 1])
                    + abs(t1_data[t1_index + 2] - off_data[off_t1_index + 2])
                )
                if t0_fog + t1_fog <= 18:
                    continue
                score += abs(t1_fog - t0_fog)
                samples += 1
        if samples == 0:
            continue
        normalized_score = score / samples
        if best_score is None or normalized_score < best_score:
            best_score = normalized_score
            best_shift = shift
            best_samples = samples

    if best_shift < -2:
        direction = "right_to_left"
    elif best_shift > 2:
        direction = "left_to_right"
    else:
        direction = "stationary_or_ambiguous"

    return {
        "estimated_direction": direction,
        "estimated_horizontal_shift_pixels": best_shift,
        "score": round(best_score, 4) if best_score is not None else None,
        "sampled_pixels": best_samples,
    }


def capture_case(output_dir: Path, name: str, *, enabled: bool, debug_visible: bool) -> tuple[dict[str, Any], QtGui.QImage]:
    engine, component, window = make_window(enabled, debug_visible)
    try:
        image = grab(window, output_dir / name)
        return diagnostics(window), image
    finally:
        window.close()
        del component
        engine.deleteLater()


def wait_for_motion(milliseconds: int) -> None:
    app = QtWidgets.QApplication.instance()
    remaining = max(0, milliseconds)
    while remaining > 0:
        step = min(remaining, 50)
        app.processEvents()
        QtTest.QTest.qWait(step)
        remaining -= step
    app.processEvents()


def capture_motion_case(
    output_dir: Path,
    *,
    motion_wait_ms: int,
) -> tuple[dict[str, Any], QtGui.QImage, dict[str, Any], QtGui.QImage]:
    engine, component, window = make_window(enabled=True, debug_visible=False)
    try:
        t0_image = grab(window, output_dir / "ghost_fog_on_t0.png")
        t0_image.save(str(output_dir / "ghost_fog_on.png"))
        t0_diagnostics = diagnostics(window)
        wait_for_motion(motion_wait_ms)
        t1_image = grab(window, output_dir / "ghost_fog_on_t1.png")
        t1_diagnostics = diagnostics(window)
        return t0_diagnostics, t0_image, t1_diagnostics, t1_image
    finally:
        window.close()
        del component
        engine.deleteLater()


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Stormforge Ghost fog proof screenshots.")
    parser.add_argument(
        "--capture-mode",
        choices=("desktop", "offscreen"),
        default="desktop",
        help="desktop uses the real Qt window path; offscreen is useful for CI/debug overlay proof.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".tmp" / "stormforge-fog-proof",
    )
    parser.add_argument(
        "--motion-wait-ms",
        type=int,
        default=8000,
        help="Elapsed real desktop time between enabled fog motion captures.",
    )
    args = parser.parse_args()

    if args.capture_mode == "offscreen":
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    else:
        os.environ.pop("QT_QPA_PLATFORM", None)
        os.environ.setdefault("QSG_RHI_BACKEND", "opengl")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    QQuickStyle.setStyle("Basic")

    off_diagnostics, off_image = capture_case(
        args.output_dir,
        "ghost_fog_off.png",
        enabled=False,
        debug_visible=False,
    )
    on_t0_diagnostics, on_t0_image, on_t1_diagnostics, on_t1_image = capture_motion_case(
        args.output_dir,
        motion_wait_ms=args.motion_wait_ms,
    )
    debug_diagnostics, debug_image = capture_case(
        args.output_dir,
        "ghost_fog_debug_visible.png",
        enabled=True,
        debug_visible=True,
    )

    off_on_diff = compare_images(
        off_image,
        on_t0_image,
        diff_path=args.output_dir / "fog_diff.png",
    )
    motion_diff = compare_images(
        on_t0_image,
        on_t1_image,
        diff_path=args.output_dir / "fog_motion_diff.png",
    )
    off_debug_diff = compare_images(
        off_image,
        debug_image,
        diff_path=args.output_dir / "fog_debug_diff.png",
    )
    normal_shader_distinguishable = bool(
        off_on_diff.get("significant_pixels")
        and off_on_diff["significant_pixels"] > 1000
    )
    debug_visible_distinguishable = bool(
        off_debug_diff.get("significant_pixels")
        and off_debug_diff["significant_pixels"] > 1000
    )
    motion_distinguishable = bool(
        motion_diff.get("significant_pixels")
        and motion_diff["significant_pixels"] > 1000
    )
    motion_direction_estimate = estimate_fog_motion_direction(
        off_image,
        on_t0_image,
        on_t1_image,
    )

    result = {
        "capture_mode": args.capture_mode,
        "renderer_hint": os.environ.get("QSG_RHI_BACKEND", ""),
        "motion_wait_ms": args.motion_wait_ms,
        "shader_pixels_captured": normal_shader_distinguishable,
        "debug_visible_pixels_captured": debug_visible_distinguishable,
        "normal_shader_capture_was_distinguishable": normal_shader_distinguishable,
        "motion_shader_capture_was_distinguishable": motion_distinguishable,
        "motion_direction_estimate": motion_direction_estimate,
        "debug_visible_used_for_proof": (
            not normal_shader_distinguishable and debug_visible_distinguishable
        ),
        "diagnostics": {
            "off": off_diagnostics,
            "on_t0": on_t0_diagnostics,
            "on_t1": on_t1_diagnostics,
            "debug_visible": debug_diagnostics,
        },
        "diffs": {
            "off_vs_on": off_on_diff,
            "on_t0_vs_on_t1": motion_diff,
            "off_vs_debug_visible": off_debug_diff,
        },
        "screenshots": {
            "ghost_fog_off": str((args.output_dir / "ghost_fog_off.png").resolve()),
            "ghost_fog_on": str((args.output_dir / "ghost_fog_on.png").resolve()),
            "ghost_fog_on_t0": str((args.output_dir / "ghost_fog_on_t0.png").resolve()),
            "ghost_fog_on_t1": str((args.output_dir / "ghost_fog_on_t1.png").resolve()),
            "ghost_fog_debug_visible": str((args.output_dir / "ghost_fog_debug_visible.png").resolve()),
            "fog_diff": str((args.output_dir / "fog_diff.png").resolve()),
            "fog_motion_diff": str((args.output_dir / "fog_motion_diff.png").resolve()),
            "fog_debug_diff": str((args.output_dir / "fog_debug_diff.png").resolve()),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
