from __future__ import annotations

import argparse
import csv
import json
import os
import time
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
    objectName: "stormforgeP2R1LiveProbeWindow"
    title: "Stormforge live renderer cadence probe"
    width: 940
    height: 640
    visible: true
    color: "#02070b"

    StormforgeGhostShell {
        id: ghost
        objectName: "stormforgeP2R1LiveProbeGhost"
        anchors.fill: parent
        statusLine: "Live renderer cadence probe"
        connectionLabel: "Frame-swapped diagnostics"
        timeLabel: "P2R.1"
        stormforgeFogConfig: ({
            "enabled": true,
            "mode": "volumetric",
            "quality": "medium",
            "motion": true,
            "intensity": 0.35,
            "driftSpeed": 0.08
        })
        messages: [
            {"role": "assistant", "speaker": "Stormhelm", "content": "Live renderer probe is measuring desktop frame swaps."}
        ]
        voiceState: ({
            "voice_anchor_state": "",
            "voice_current_phase": "idle",
            "speaking_visual_active": false,
            "active_playback_status": "idle",
            "voice_center_blob_scale_drive": 0.0,
            "voice_outer_speaking_motion": 0.0,
            "voice_audio_reactive_available": false,
            "voice_audio_reactive_source": "unavailable"
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


def _intervals_ms(timestamps: list[float]) -> list[float]:
    return [(right - left) * 1000.0 for left, right in zip(timestamps, timestamps[1:])]


def _write_frame_csv(
    path: Path,
    frame_swaps: list[float],
    speaking_start: float,
    speaking_end: float,
) -> None:
    origin = frame_swaps[0] if frame_swaps else speaking_start
    intervals = [0.0] + _intervals_ms(frame_swaps)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("index", "timestamp_ms", "interval_ms", "during_speaking"),
        )
        writer.writeheader()
        for index, (timestamp, interval) in enumerate(zip(frame_swaps, intervals)):
            writer.writerow(
                {
                    "index": index,
                    "timestamp_ms": round((timestamp - origin) * 1000.0, 3),
                    "interval_ms": round(interval, 3),
                    "during_speaking": speaking_start <= timestamp <= speaking_end,
                }
            )


def _write_markdown_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Stormforge Live Renderer Cadence Report",
        "",
        f"- Probe version: `{summary['liveRendererProbeVersion']}`",
        f"- Mode: `{summary['live_renderer_probe_mode']}`",
        f"- FrameSwapped available: `{summary['frameSwappedAvailable']}`",
        f"- Live frame-swapped FPS during speaking: `{summary['liveFrameSwapsPerSecond']:.2f}`",
        f"- Max live frame gap during speaking: `{summary['maxLiveFrameGapMs']:.2f} ms`",
        f"- Long frames >33 ms: `{summary['longFrameCountOver33MsDuringSpeaking']}`",
        f"- Severe frames >50 ms: `{summary['severeFrameCountOver50MsDuringSpeaking']}`",
        f"- Very severe frames >100 ms: `{summary['verySevereFrameCountOver100MsDuringSpeaking']}`",
        f"- Voice payload updates/sec: `{summary['liveVoicePayloadUpdatesPerSecond']:.2f}`",
        f"- Visual voice applies: `{summary['visualVoiceStateApplyCount']}`",
        f"- Anchor paint FPS during speaking: `{summary['liveAnchorPaintsPerSecond']:.2f}`",
        f"- Fog tick FPS during speaking: `{summary['liveFogTickFpsDuringSpeaking']:.2f}`",
        f"- Fog timebase: `{summary['fogTimebaseVersion']}` / `{summary['fogTimeInputUnit']}`",
        f"- Fog double-driven: `{summary['fogDoubleDriven']}`",
        f"- Renderer cadence stable: `{summary['liveRendererCadenceStable']}`",
        "",
        "This probe uses a visible desktop `QQuickWindow` and `frameSwapped` timestamps. It is stronger than offscreen `grabWindow` cadence, but it is still a probe window rather than an attachment to an already-running production Stormhelm UI process.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_probe(
    output_dir: Path,
    *,
    duration_ms: int,
    voice_event_interval_ms: int,
    sample_interval_ms: int,
    allow_offscreen: bool,
) -> dict[str, Any]:
    if not allow_offscreen and os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        del os.environ["QT_QPA_PLATFORM"]
    output_dir.mkdir(parents=True, exist_ok=True)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    QQuickStyle.setStyle("Basic")
    engine = QtQml.QQmlApplicationEngine()
    engine.addImportPath(str(ASSETS))
    engine.loadData(
        PROBE_QML.encode("utf-8"),
        QtCore.QUrl.fromLocalFile(str(ASSETS / "StormforgeP2R1LiveRendererProbe.qml")),
    )
    if not engine.rootObjects():
        raise RuntimeError("Stormforge P2R.1 live renderer probe QML failed to load.")

    window = engine.rootObjects()[0]
    shell = window.findChild(QtCore.QObject, "stormforgeP2R1LiveProbeGhost")
    anchor = window.findChild(QtCore.QObject, "stormforgeAnchorCore")
    fog = window.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")
    if shell is None or anchor is None or fog is None:
        raise RuntimeError("Probe scene did not expose shell, anchor, and fog objects.")
    anchor.setProperty("renderLoopDiagnosticsEnabled", True)
    window.show()

    frame_swaps: list[float] = []
    frame_swapped_available = False
    frame_swapped_error = ""
    try:
        window.frameSwapped.connect(lambda: frame_swaps.append(time.perf_counter()))
        frame_swapped_available = True
    except Exception as exc:  # pragma: no cover - depends on Qt backend bindings.
        frame_swapped_error = str(exc)

    _wait(app, 600)

    voice_event_count = 0
    level_index = 0

    def emit_voice_event() -> None:
        nonlocal voice_event_count, level_index
        level = 0.0 if level_index % 5 == 0 else min(1.0, 0.18 + (level_index % 8) * 0.10)
        _set_voice(shell, active=True, level=level)
        voice_event_count += 1
        level_index += 1

    voice_timer = QtCore.QTimer()
    voice_timer.setInterval(max(1, voice_event_interval_ms))
    voice_timer.timeout.connect(emit_voice_event)

    samples: list[dict[str, Any]] = []
    speaking_start = time.perf_counter()
    _set_voice(shell, active=True, level=0.42)
    voice_event_count += 1
    voice_timer.start()
    deadline = speaking_start + duration_ms / 1000.0
    while time.perf_counter() < deadline:
        _wait(app, sample_interval_ms)
        samples.append(
            {
                "elapsed_ms": round((time.perf_counter() - speaking_start) * 1000.0, 3),
                "shell": _sample_object(shell, SHELL_FIELDS),
                "anchor": _sample_object(anchor, ANCHOR_FIELDS),
                "fog": _sample_object(fog, FOG_FIELDS),
            }
        )
    voice_timer.stop()
    speaking_end = time.perf_counter()

    _set_voice(shell, active=False, level=0.0)
    _wait(app, 800)

    speaking_swaps = [timestamp for timestamp in frame_swaps if speaking_start <= timestamp <= speaking_end]
    speaking_intervals = _intervals_ms(speaking_swaps)
    speaking_duration = max(0.001, speaking_end - speaking_start)
    fps = len(speaking_swaps) / speaking_duration
    max_gap = max(speaking_intervals) if speaking_intervals else 0.0
    long_33 = sum(1 for interval in speaking_intervals if interval > 33.0)
    severe_50 = sum(1 for interval in speaking_intervals if interval > 50.0)
    very_severe_100 = sum(1 for interval in speaking_intervals if interval > 100.0)
    last_sample = samples[-1] if samples else {
        "shell": _sample_object(shell, SHELL_FIELDS),
        "anchor": _sample_object(anchor, ANCHOR_FIELDS),
        "fog": _sample_object(fog, FOG_FIELDS),
    }
    live_anchor_paints = float(last_sample["shell"]["anchorPaintFpsDuringSpeaking"] or 0.0)
    live_fog_ticks = float(last_sample["shell"]["fogTickFpsDuringSpeaking"] or 0.0)

    frame_path = output_dir / "live_renderer_probe_frame.png"
    frame_captured = _grab(window, frame_path)
    frame_csv_path = output_dir / "live_frame_intervals.csv"
    _write_frame_csv(frame_csv_path, frame_swaps, speaking_start, speaking_end)

    summary = {
        "liveRendererProbeVersion": "UI-P2R.1",
        "live_renderer_probe_mode": "desktop_qquickwindow_frame_swapped",
        "production_app_attached": False,
        "qt_qpa_platform": os.environ.get("QT_QPA_PLATFORM", ""),
        "frameSwappedAvailable": frame_swapped_available,
        "frameSwappedError": frame_swapped_error,
        "speakingDurationMs": round(speaking_duration * 1000.0, 3),
        "liveFrameSwapsDuringSpeaking": len(speaking_swaps),
        "liveFrameSwapsPerSecond": fps,
        "maxLiveFrameGapMs": max_gap,
        "longFrameCountOver33MsDuringSpeaking": long_33,
        "severeFrameCountOver50MsDuringSpeaking": severe_50,
        "verySevereFrameCountOver100MsDuringSpeaking": very_severe_100,
        "liveRendererCadenceStable": bool(frame_swapped_available and fps >= 30.0 and severe_50 == 0),
        "liveVoicePayloadUpdates": voice_event_count,
        "liveVoicePayloadUpdatesPerSecond": voice_event_count / speaking_duration,
        "visualVoiceStateApplyCount": int(last_sample["shell"]["visualVoiceStateApplyCount"] or 0),
        "visualVoiceStateAppliesPerSecond": int(last_sample["shell"]["visualVoiceStateApplyCount"] or 0) / speaking_duration,
        "liveSurfaceModelRebuildsAvailable": False,
        "liveSurfaceModelRebuildsPerSecond": None,
        "liveGhostBindingUpdatesAvailable": False,
        "liveGhostBindingUpdatesPerSecond": None,
        "liveAnchorPaintsPerSecond": live_anchor_paints,
        "liveFogTickFpsDuringSpeaking": live_fog_ticks,
        "visualClockFps": float(last_sample["shell"]["visualClockFps"] or 0.0),
        "visualClockMaxFrameGapMs": float(last_sample["shell"]["visualClockMaxFrameGapMs"] or 0.0),
        "anchorUsesSharedClock": bool(last_sample["anchor"]["sharedVisualClockActive"]),
        "fogUsesSharedClock": bool(last_sample["fog"]["fogUsesSharedVisualClock"]),
        "rawAudioEventsDoNotRequestPaint": bool(last_sample["shell"]["rawAudioEventsDoNotRequestPaint"]),
        "audioReactiveUsesVisualClock": bool(last_sample["anchor"]["audioReactiveUsesVisualClock"]),
        "speakingVisualLatencyEstimateMs": float(last_sample["shell"]["speakingVisualLatencyEstimateMs"] or 0.0),
        "fogTimebaseVersion": last_sample["fog"]["fogTimebaseVersion"],
        "fogTimeInputUnit": last_sample["fog"]["fogTimeInputUnit"],
        "fogLegacyPhaseUnitsPerSecond": float(last_sample["fog"]["fogLegacyPhaseUnitsPerSecond"] or 0.0),
        "fogSharedClockTimeSec": float(last_sample["fog"]["fogSharedClockTimeSec"] or 0.0),
        "fogPhase": float(last_sample["fog"]["phase"] or 0.0),
        "fogEffectiveDriftSpeed": float(last_sample["fog"]["fogEffectiveDriftSpeed"] or 0.0),
        "fogFallbackAnimationActive": bool(last_sample["fog"]["fogFallbackAnimationActive"]),
        "fogDoubleDriven": bool(last_sample["fog"]["fogDoubleDriven"]),
        "frameCaptured": frame_captured,
        "framePath": str(frame_path) if frame_captured else "",
        "frameIntervalsCsvPath": str(frame_csv_path),
    }

    report = {
        "probe": "stormforge_live_renderer_cadence",
        "version": "UI-P2R.1",
        "artifact_dir": str(output_dir),
        "summary": summary,
        "samples": samples,
    }
    report_path = output_dir / "live_renderer_cadence_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_markdown_report(output_dir / "live_renderer_cadence_report.md", summary)

    voice_churn_report = {
        "version": "UI-P2R.1",
        "liveVoicePayloadUpdates": voice_event_count,
        "liveVoicePayloadUpdatesPerSecond": summary["liveVoicePayloadUpdatesPerSecond"],
        "visualVoiceStateApplyCount": summary["visualVoiceStateApplyCount"],
        "visualVoiceStateAppliesPerSecond": summary["visualVoiceStateAppliesPerSecond"],
        "liveSurfaceModelRebuildsAvailable": False,
        "liveSurfaceModelRebuildsPerSecond": None,
        "note": "The standalone desktop renderer probe can measure Ghost voice-state churn and visual-state applies, but not production bridge surface-model rebuilds.",
    }
    churn_path = output_dir / "live_voice_update_churn_report.json"
    churn_path.write_text(json.dumps(voice_churn_report, indent=2), encoding="utf-8")

    fog_report = {
        "version": "UI-P2R.1",
        "fogTimebaseVersion": summary["fogTimebaseVersion"],
        "fogTimeInputUnit": summary["fogTimeInputUnit"],
        "fogLegacyPhaseUnitsPerSecond": summary["fogLegacyPhaseUnitsPerSecond"],
        "fogSharedClockTimeSec": summary["fogSharedClockTimeSec"],
        "fogPhase": summary["fogPhase"],
        "fogEffectiveDriftSpeed": summary["fogEffectiveDriftSpeed"],
        "fogFallbackAnimationActive": summary["fogFallbackAnimationActive"],
        "fogDoubleDriven": summary["fogDoubleDriven"],
    }
    fog_path = output_dir / "fog_timebase_report.json"
    fog_path.write_text(json.dumps(fog_report, indent=2), encoding="utf-8")

    report["report_path"] = str(report_path)
    report["churn_report_path"] = str(churn_path)
    report["fog_report_path"] = str(fog_path)
    window.close()
    app.processEvents()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure Stormforge desktop renderer cadence with frameSwapped timestamps during simulated voice churn.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / ".artifacts" / "stormforge_live_renderer",
        help="Directory for live renderer reports and frame interval CSV.",
    )
    parser.add_argument("--duration-ms", type=int, default=3600, help="Speaking/churn measurement duration.")
    parser.add_argument("--voice-event-interval-ms", type=int, default=18, help="Synthetic voice payload interval.")
    parser.add_argument("--sample-interval-ms", type=int, default=80, help="QML diagnostic sample interval.")
    parser.add_argument(
        "--allow-offscreen",
        action="store_true",
        help="Do not remove QT_QPA_PLATFORM=offscreen. This is for CI only and is not live renderer proof.",
    )
    args = parser.parse_args()
    report = run_probe(
        args.output_dir,
        duration_ms=args.duration_ms,
        voice_event_interval_ms=args.voice_event_interval_ms,
        sample_interval_ms=args.sample_interval_ms,
        allow_offscreen=args.allow_offscreen,
    )
    print(
        json.dumps(
            {
                "summary": report["summary"],
                "report_path": report["report_path"],
                "churn_report_path": report["churn_report_path"],
                "fog_report_path": report["fog_report_path"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
