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


PROBE_QML = r"""
import QtQuick 2.15
import QtQuick.Window 2.15
import "variants/stormforge"

Window {
    id: win
    objectName: "stormforgeReactiveEnvelopeProbeWindow"
    width: 360
    height: 420
    visible: true
    color: "#02070b"

    StormforgeAnchorCore {
        id: anchor
        objectName: "stormforgeReactiveEnvelopeProbeCore"
        width: 260
        height: 306
        anchors.centerIn: parent
        voiceState: ({
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": true,
            "active_playback_status": "playing",
            "voice_center_blob_scale_drive": 0.72,
            "voice_outer_speaking_motion": 0.50,
            "voice_audio_reactive_available": true,
            "voice_audio_reactive_source": "playback_output_envelope"
        })
    }
}
"""


SAMPLE_PROPERTIES = (
    "rawPlaybackLevel",
    "rawSpeakingLevel",
    "reactiveLevelTarget",
    "reactiveEnvelope",
    "proceduralSpeechEnergy",
    "visualSpeechEnergy",
    "finalSpeakingEnergy",
    "speakingEnvelopeSmoothed",
    "outerMotionSmoothed",
    "speakingPhase",
    "visualSpeakingActive",
    "rawLevelUpdateCount",
    "audioReactiveDecoupled",
    "reactiveEnvelopeVersion",
    "reactiveEnvelopeContinuous",
    "proceduralSpeechSynthEnabled",
    "rawLevelDirectGeometryDriveDisabled",
    "missingRawLevelUsesProceduralSpeechEnergy",
    "speakingEnergyJitterGuardEnabled",
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _set_voice(anchor: QtCore.QObject, *, active: bool, level: float, outer: float | None = None) -> None:
    anchor.setProperty(
        "voiceState",
        {
            "voice_anchor_state": "speaking" if active else "",
            "voice_current_phase": "playback_active" if active else "idle",
            "speaking_visual_active": active,
            "active_playback_status": "playing" if active else "idle",
            "voice_center_blob_scale_drive": level,
            "voice_outer_speaking_motion": level if outer is None else outer,
            "voice_audio_reactive_available": active,
            "voice_audio_reactive_source": "playback_output_envelope" if active else "unavailable",
        },
    )


def _wait(app: QtWidgets.QApplication, ms: int) -> None:
    app.processEvents()
    QtTest.QTest.qWait(ms)
    app.processEvents()


def _sample(anchor: QtCore.QObject, label: str, elapsed_ms: int) -> dict[str, Any]:
    data = {"label": label, "elapsed_ms": elapsed_ms}
    for name in SAMPLE_PROPERTIES:
        data[name] = _json_value(anchor.property(name))
    return data


def _grab(window: QtGui.QWindow, output_path: Path) -> bool:
    image = window.grabWindow()
    if image.isNull():
        return False
    return bool(image.save(str(output_path)))


def _energy_delta(samples: list[dict[str, Any]]) -> float:
    values = [float(sample["finalSpeakingEnergy"]) for sample in samples]
    if len(values) < 2:
        return 0.0
    return max(abs(values[index] - values[index - 1]) for index in range(1, len(values)))


def run_probe(output_dir: Path) -> dict[str, Any]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    output_dir.mkdir(parents=True, exist_ok=True)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    QQuickStyle.setStyle("Basic")
    engine = QtQml.QQmlApplicationEngine()
    engine.addImportPath(str(ASSETS))
    engine.loadData(
        PROBE_QML.encode("utf-8"),
        QtCore.QUrl.fromLocalFile(str(ASSETS / "StormforgeReactiveEnvelopeProbe.qml")),
    )
    if not engine.rootObjects():
        raise RuntimeError("Stormforge reactive envelope probe QML failed to load.")

    window = engine.rootObjects()[0]
    anchor = window.findChild(QtCore.QObject, "stormforgeReactiveEnvelopeProbeCore")
    if anchor is None:
        raise RuntimeError("StormforgeAnchorCore was not found in the probe scene.")

    samples: list[dict[str, Any]] = []
    frames: list[str] = []
    elapsed = 0

    def wait_and_sample(label: str, ms: int) -> dict[str, Any]:
        nonlocal elapsed
        _wait(app, ms)
        elapsed += ms
        sample = _sample(anchor, label, elapsed)
        samples.append(sample)
        return sample

    wait_and_sample("speaking_active_raw_level", 260)
    frame0 = output_dir / "reactive_speaking_frame_0.png"
    if _grab(window, frame0):
        frames.append(str(frame0))

    _set_voice(anchor, active=True, level=0.0, outer=0.0)
    wait_and_sample("raw_zero_gap_while_speaking", 120)
    frame1 = output_dir / "reactive_speaking_frame_1.png"
    if _grab(window, frame1):
        frames.append(str(frame1))

    _set_voice(anchor, active=True, level=1.0, outer=1.0)
    wait_and_sample("raw_burst_spike", 90)

    wait_and_sample("missing_raw_updates_hold", 420)
    frame2 = output_dir / "reactive_speaking_frame_2.png"
    if _grab(window, frame2):
        frames.append(str(frame2))

    _set_voice(anchor, active=True, level=0.46, outer=0.36)
    wait_and_sample("stable_speaking_level", 220)

    _set_voice(anchor, active=False, level=0.0, outer=0.0)
    release_wait = int(anchor.property("speakingLatchMs")) + int(anchor.property("stateMinimumDwellMs")) + 520
    wait_and_sample("released_after_speaking", release_wait)

    speaking_samples = [sample for sample in samples if sample["label"] != "released_after_speaking"]
    phases = [float(sample["speakingPhase"]) for sample in samples]
    report = {
        "probe": "stormforge_reactive_envelope",
        "version": "UI-P2A.6.8",
        "artifact_dir": str(output_dir),
        "frames": frames,
        "samples": samples,
        "summary": {
            "audio_reactive_decoupled": bool(samples[0]["audioReactiveDecoupled"]),
            "reactive_envelope_version": samples[0]["reactiveEnvelopeVersion"],
            "procedural_speech_synth_enabled": bool(samples[0]["proceduralSpeechSynthEnabled"]),
            "raw_level_direct_geometry_drive_disabled": bool(samples[0]["rawLevelDirectGeometryDriveDisabled"]),
            "missing_raw_level_uses_procedural_speech_energy": bool(samples[0]["missingRawLevelUsesProceduralSpeechEnergy"]),
            "speaking_energy_jitter_guard_enabled": bool(samples[0]["speakingEnergyJitterGuardEnabled"]),
            "final_energy_min_while_speaking": min(float(sample["finalSpeakingEnergy"]) for sample in speaking_samples),
            "final_energy_max_while_speaking": max(float(sample["finalSpeakingEnergy"]) for sample in speaking_samples),
            "max_final_energy_delta_while_speaking": _energy_delta(speaking_samples),
            "max_final_energy_delta_including_release": _energy_delta(samples),
            "phase_monotonic": all(phases[index] >= phases[index - 1] for index in range(1, len(phases))),
            "final_energy_nonzero_while_speaking": all(float(sample["finalSpeakingEnergy"]) > 0.0 for sample in speaking_samples),
            "released_to_idle": not bool(samples[-1]["visualSpeakingActive"]),
            "released_energy": float(samples[-1]["finalSpeakingEnergy"]),
            "raw_level_update_count": int(samples[-1]["rawLevelUpdateCount"]),
        },
    }

    sequence_report = output_dir / "reactive_speaking_sequence_report.json"
    sequence_report.write_text(json.dumps(report, indent=2), encoding="utf-8")

    chunky_report = {
        "probe": "simulated_chunky_level_response",
        "version": "UI-P2A.6.8",
        "sequence": [
            {"step": sample["label"], "raw": sample["rawSpeakingLevel"], "target": sample["reactiveLevelTarget"], "reactive": sample["reactiveEnvelope"], "final": sample["finalSpeakingEnergy"]}
            for sample in samples
        ],
        "summary": report["summary"],
    }
    chunky_path = output_dir / "simulated_chunky_level_response_report.json"
    chunky_path.write_text(json.dumps(chunky_report, indent=2), encoding="utf-8")
    report["sequence_report"] = str(sequence_report)
    report["chunky_response_report"] = str(chunky_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Render and sample Stormforge Anchor reactive envelope behavior.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".artifacts" / "stormforge_reactive_envelope",
        help="Directory for PNG frames and JSON reports.",
    )
    args = parser.parse_args()
    report = run_probe(args.output_dir)
    print(json.dumps({"summary": report["summary"], "artifact_dir": report["artifact_dir"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
