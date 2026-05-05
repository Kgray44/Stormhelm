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
    objectName: "stormforgeP2RProbeWindow"
    width: 940
    height: 640
    visible: true
    color: "#02070b"

    StormforgeGhostShell {
        id: ghost
        objectName: "stormforgeP2RProbeGhost"
        anchors.fill: parent
        statusLine: "Voice cadence probe"
        connectionLabel: "Signal steady"
        timeLabel: "P2R"
        stormforgeFogConfig: ({
            "enabled": true,
            "mode": "volumetric",
            "quality": "medium",
            "motion": true,
            "intensity": 0.35
        })
        messages: [
            {"role": "assistant", "speaker": "Stormhelm", "content": "Render cadence probe is active."}
        ]
        voiceState: ({
            "voice_anchor_state": "speaking",
            "voice_current_phase": "playback_active",
            "speaking_visual_active": true,
            "active_playback_status": "playing",
            "voice_center_blob_scale_drive": 0.58,
            "voice_outer_speaking_motion": 0.42,
            "voice_audio_reactive_available": true,
            "voice_audio_reactive_source": "playback_output_envelope"
        })
    }
}
"""


SHELL_FIELDS = (
    "stormforgeRenderCadenceVersion",
    "voiceVisualSyncVersion",
    "sharedAnimationClockEnabled",
    "visualClockTargetFps",
    "visualClockMinAcceptableFps",
    "visualClockFrameCounter",
    "visualClockFps",
    "visualClockLongFrameCount",
    "visualClockLastFrameGapMs",
    "visualClockMaxFrameGapMs",
    "visualClockCadenceStable",
    "visualClockSpeakingCadenceStable",
    "voiceEventCountDuringSpeaking",
    "voiceEventRateDuringSpeaking",
    "visualVoiceStateApplyCount",
    "anchorPaintFpsDuringSpeaking",
    "fogTickFpsDuringSpeaking",
    "speakingVisualLatencyEstimateMs",
    "rawAudioEventsDoNotRequestPaint",
)

ANCHOR_FIELDS = (
    "sharedVisualClockActive",
    "audioReactiveUsesVisualClock",
    "rawAudioEventsDoNotRequestPaint",
    "visualClockFps",
    "visualClockFrameCounter",
    "speakingPhase",
    "finalSpeakingEnergy",
    "rawLevelUpdateCount",
    "anchorRequestPaintCountPerSecond",
    "speakingEnvelopeUpdateCountPerSecond",
)

FOG_FIELDS = (
    "fogVisualClockVersion",
    "fogTimebaseVersion",
    "fogTimeInputUnit",
    "fogLegacyPhaseUnitsPerSecond",
    "fogSharedClockTimeSec",
    "fogEffectiveDriftSpeed",
    "fogFallbackAnimationActive",
    "fogDoubleDriven",
    "fogUsesSharedVisualClock",
    "fallbackPhaseAnimationDisabledBySharedClock",
    "fogActive",
    "animationRunning",
    "phase",
    "visualClockFrameCounter",
    "visualClockMeasuredFps",
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sample_object(obj: QtCore.QObject, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _json_value(obj.property(field)) for field in fields}


def _set_voice(shell: QtCore.QObject, *, active: bool, level: float) -> None:
    shell.setProperty(
        "voiceState",
        {
            "voice_anchor_state": "speaking" if active else "",
            "voice_current_phase": "playback_active" if active else "idle",
            "speaking_visual_active": active,
            "active_playback_status": "playing" if active else "idle",
            "voice_center_blob_scale_drive": level,
            "voice_outer_speaking_motion": min(1.0, level + 0.10),
            "voice_audio_reactive_available": active,
            "voice_audio_reactive_source": "playback_output_envelope" if active else "unavailable",
        },
    )


def _wait(app: QtWidgets.QApplication, ms: int) -> None:
    app.processEvents()
    QtTest.QTest.qWait(ms)
    app.processEvents()


def _grab(window: QtGui.QWindow, output_path: Path) -> bool:
    image = window.grabWindow()
    if image.isNull():
        return False
    return bool(image.save(str(output_path)))


def run_probe(output_dir: Path) -> dict[str, Any]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    output_dir.mkdir(parents=True, exist_ok=True)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    QQuickStyle.setStyle("Basic")
    engine = QtQml.QQmlApplicationEngine()
    engine.addImportPath(str(ASSETS))
    engine.loadData(
        PROBE_QML.encode("utf-8"),
        QtCore.QUrl.fromLocalFile(str(ASSETS / "StormforgeP2RProbe.qml")),
    )
    if not engine.rootObjects():
        raise RuntimeError("Stormforge P2R cadence probe QML failed to load.")

    window = engine.rootObjects()[0]
    shell = window.findChild(QtCore.QObject, "stormforgeP2RProbeGhost")
    clock = window.findChild(QtCore.QObject, "stormforgeAnimationClock")
    anchor = window.findChild(QtCore.QObject, "stormforgeAnchorCore")
    fog = window.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")
    if shell is None or clock is None or anchor is None or fog is None:
        raise RuntimeError("Probe scene did not expose shell, clock, anchor, and fog objects.")
    anchor.setProperty("renderLoopDiagnosticsEnabled", True)

    samples: list[dict[str, Any]] = []
    elapsed = 0

    def sample(label: str, wait_ms: int) -> None:
        nonlocal elapsed
        _wait(app, wait_ms)
        elapsed += wait_ms
        samples.append(
            {
                "label": label,
                "elapsed_ms": elapsed,
                "shell": _sample_object(shell, SHELL_FIELDS),
                "anchor": _sample_object(anchor, ANCHOR_FIELDS),
                "fog": _sample_object(fog, FOG_FIELDS),
            }
        )

    sample("speaking_warmup", 360)

    for index in range(72):
        level = 0.0 if index % 5 == 0 else min(1.0, 0.18 + (index % 8) * 0.10)
        _set_voice(shell, active=True, level=level)
        app.processEvents()
    sample("speaking_voice_event_churn", 1300)

    sample("speaking_sparse_level_hold", 700)

    _set_voice(shell, active=False, level=0.0)
    sample("released", 1850)

    frame_path = output_dir / "stormforge_p2r_cadence_frame.png"
    frame_captured = _grab(window, frame_path)

    speaking_samples = [sample for sample in samples if sample["label"] != "released"]
    fps_values = [float(sample["shell"]["visualClockFps"]) for sample in speaking_samples if float(sample["shell"]["visualClockFps"]) > 0]
    max_gap_values = [float(sample["shell"]["visualClockMaxFrameGapMs"]) for sample in speaking_samples]
    anchor_paint_values = [
        float(sample["shell"]["anchorPaintFpsDuringSpeaking"]) or float(sample["shell"]["visualClockFps"])
        for sample in speaking_samples
        if float(sample["shell"]["visualClockFps"]) > 0
    ]
    fog_tick_values = [
        float(sample["shell"]["fogTickFpsDuringSpeaking"]) or float(sample["shell"]["visualClockFps"])
        for sample in speaking_samples
        if float(sample["shell"]["visualClockFps"]) > 0
    ]

    summary = {
        "render_cadence_version": samples[-1]["shell"]["stormforgeRenderCadenceVersion"],
        "voice_visual_sync_version": samples[-1]["shell"]["voiceVisualSyncVersion"],
        "offscreen_probe_is_live_proof": False,
        "requires_live_renderer_probe": True,
        "shared_clock_enabled": bool(samples[-1]["shell"]["sharedAnimationClockEnabled"]),
        "target_fps": int(samples[-1]["shell"]["visualClockTargetFps"]),
        "min_acceptable_fps": int(samples[-1]["shell"]["visualClockMinAcceptableFps"]),
        "min_visual_clock_fps_during_speaking": min(fps_values) if fps_values else 0.0,
        "max_visual_clock_gap_ms": max(max_gap_values),
        "anchor_paint_fps_max_during_speaking": max(anchor_paint_values) if anchor_paint_values else 0.0,
        "fog_tick_fps_min_during_speaking": min(fog_tick_values) if fog_tick_values else 0.0,
        "voice_events_during_speaking": int(samples[-1]["shell"]["voiceEventCountDuringSpeaking"]),
        "visual_voice_state_applies": int(samples[-1]["shell"]["visualVoiceStateApplyCount"]),
        "anchor_uses_shared_clock": bool(samples[-1]["anchor"]["sharedVisualClockActive"]),
        "fog_uses_shared_clock": bool(samples[-1]["fog"]["fogUsesSharedVisualClock"]),
        "fog_timebase_version": samples[-1]["fog"]["fogTimebaseVersion"],
        "fog_time_input_unit": samples[-1]["fog"]["fogTimeInputUnit"],
        "fog_legacy_phase_units_per_second": float(samples[-1]["fog"]["fogLegacyPhaseUnitsPerSecond"]),
        "fog_shared_clock_time_sec": float(samples[-1]["fog"]["fogSharedClockTimeSec"]),
        "fog_phase": float(samples[-1]["fog"]["phase"]),
        "fog_effective_drift_speed": float(samples[-1]["fog"]["fogEffectiveDriftSpeed"]),
        "fog_fallback_animation_active": bool(samples[-1]["fog"]["fogFallbackAnimationActive"]),
        "fog_double_driven": bool(samples[-1]["fog"]["fogDoubleDriven"]),
        "raw_audio_events_do_not_request_paint": bool(samples[-1]["shell"]["rawAudioEventsDoNotRequestPaint"]),
        "audio_reactive_uses_visual_clock": bool(samples[-1]["anchor"]["audioReactiveUsesVisualClock"]),
        "frame_captured": frame_captured,
        "frame_path": str(frame_path) if frame_captured else "",
    }
    report = {
        "probe": "stormforge_render_cadence",
        "version": "UI-P2R",
        "artifact_dir": str(output_dir),
        "samples": samples,
        "summary": summary,
    }
    report_path = output_dir / "stormforge_p2r_cadence_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure Stormforge P2R shared-clock cadence under voice event churn.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".artifacts" / "stormforge_render_cadence",
        help="Directory for the cadence report and optional frame capture.",
    )
    args = parser.parse_args()
    report = run_probe(args.output_dir)
    print(json.dumps({"summary": report["summary"], "report_path": report["report_path"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
