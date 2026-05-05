from __future__ import annotations

import argparse
import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtQml, QtTest, QtWidgets
from PySide6.QtQuickControls2 import QQuickStyle


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "qml"
OUTPUT_DIR = ROOT / ".artifacts" / "ui_voice_live_iso"
REPORT_JSON = OUTPUT_DIR / "voice_visualizer_ab_report.json"
REPORT_MD = OUTPUT_DIR / "voice_visualizer_ab_report.md"
FRAME_CSV = OUTPUT_DIR / "voice_visualizer_ab_frame_intervals.csv"


PROBE_QML = r"""
import QtQuick 2.15
import QtQuick.Window 2.15
import "variants/stormforge"

Window {
    id: win
    objectName: "stormforgeVoiceVisualizerAbProbeWindow"
    title: "Stormforge voice visualizer A/B isolation"
    width: 940
    height: 640
    visible: true
    color: "#02070b"

    StormforgeGhostShell {
        id: ghost
        objectName: "stormforgeVoiceVisualizerAbProbeGhost"
        anchors.fill: parent
        statusLine: "Voice visualizer A/B isolation"
        connectionLabel: "UI-VOICE-LIVE-ISO"
        timeLabel: "Diagnostic"
        stormforgeFogConfig: ({
            "enabled": false,
            "mode": "volumetric",
            "quality": "medium",
            "diagnosticDisableDuringSpeech": false
        })
        stormforgeVoiceDiagnosticsConfig: ({
            "anchorVisualizerMode": "off",
            "liveIsolationVersion": "UI-VOICE-LIVE-ISO"
        })
        messages: [
            {"role": "assistant", "speaker": "Stormhelm", "content": "A/B isolation is measuring visualizer cadence."}
        ]
        voiceState: ({
            "voice_anchor_state": "idle",
            "voice_current_phase": "idle",
            "speaking_visual_active": false,
            "active_playback_status": "idle"
        })
    }
}
"""


CASES = [
    {
        "case": "A",
        "name": "fog_off_visualizer_off",
        "fog_enabled": False,
        "visualizer_mode": "off",
        "expected": "If this stutters, the problem is not anchor reactive animation or fog.",
    },
    {
        "case": "B",
        "name": "fog_off_constant_test_wave",
        "fog_enabled": False,
        "visualizer_mode": "constant_test_wave",
        "expected": "If this is smooth, Anchor local animation can be smooth during speaking.",
    },
    {
        "case": "C",
        "name": "fog_off_procedural",
        "fog_enabled": False,
        "visualizer_mode": "procedural",
        "expected": "If this stutters, suspect speaking-state churn or Anchor paint path.",
    },
    {
        "case": "D",
        "name": "fog_off_envelope_timeline",
        "fog_enabled": False,
        "visualizer_mode": "envelope_timeline",
        "expected": "If only this stutters, suspect envelope/timeline sampling.",
    },
    {
        "case": "E",
        "name": "fog_on_procedural",
        "fog_enabled": True,
        "visualizer_mode": "procedural",
        "expected": "Compares fog load against procedural speaking.",
    },
    {
        "case": "F",
        "name": "fog_on_envelope_timeline",
        "fog_enabled": True,
        "visualizer_mode": "envelope_timeline",
        "expected": "Full intended Stormforge speaking path.",
    },
]


def _json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _wait(app: QtWidgets.QApplication, ms: int) -> None:
    app.processEvents()
    QtTest.QTest.qWait(ms)
    app.processEvents()


def _timeline_samples(count: int = 120, step_ms: int = 16) -> list[dict[str, float]]:
    samples: list[dict[str, float]] = []
    for index in range(count):
        syllable = math.sin(index * 0.42) * 0.5 + 0.5
        phrase = math.sin(index * 0.09 + 0.8) * 0.5 + 0.5
        burst = 0.18 if index in {12, 13, 30, 31, 55, 56, 82, 83} else 0.0
        energy = min(1.0, 0.13 + syllable * 0.18 + phrase * 0.08 + burst)
        samples.append({"t_ms": float(index * step_ms), "energy": round(energy, 4)})
    return samples


def _voice_state(active: bool, *, playback_id: str, mode: str, tick: int) -> dict[str, Any]:
    if not active:
        return {
            "voice_anchor_state": "idle",
            "voice_current_phase": "idle",
            "speaking_visual_active": False,
            "active_playback_status": "idle",
        }
    state: dict[str, Any] = {
        "playback_id": playback_id,
        "active_playback_id": playback_id,
        "active_playback_stream_id": playback_id,
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": True,
        "active_playback_status": "playing",
        "voice_audio_reactive_available": mode == "envelope_timeline",
        "voice_audio_reactive_source": "playback_pcm" if mode == "envelope_timeline" else "diagnostic",
        "voice_center_blob_scale_drive": 0.0,
        "visualizer_source_switch_count": 0,
        "raw_audio_present": False,
    }
    if mode == "envelope_timeline":
        samples = _timeline_samples()
        query_time = min(samples[-1]["t_ms"], float(tick * 16))
        state.update(
            {
                "playback_envelope_supported": True,
                "playback_envelope_available": True,
                "playback_envelope_usable": True,
                "playback_envelope_source": "playback_pcm",
                "playback_envelope_sample_rate_hz": 60,
                "playback_envelope_sample_count": len(samples),
                "playback_envelope_sample_age_ms": 0,
                "playback_envelope_window_mode": "playback_time",
                "playback_envelope_query_time_ms": query_time,
                "playback_visual_time_ms": query_time,
                "envelopeTimelineSamples": samples,
                "envelope_timeline_available": True,
                "envelope_timeline_sample_rate_hz": 60,
                "envelope_timeline_sample_count": len(samples),
                "visualizer_source_strategy": "playback_envelope_timeline",
                "visualizer_source_locked": True,
                "visualizer_source_playback_id": playback_id,
            }
        )
    return state


def _sample_case(
    *,
    case: dict[str, Any],
    shell: QtCore.QObject,
    anchor: QtCore.QObject,
    fog: QtCore.QObject | None,
    frame_swaps: list[tuple[str, float]],
    started: float,
    ended: float,
) -> dict[str, Any]:
    case_swaps = [stamp for name, stamp in frame_swaps if name == case["name"]]
    intervals = [
        (right - left) * 1000.0 for left, right in zip(case_swaps, case_swaps[1:])
    ]
    duration = max(0.001, ended - started)
    long_33 = sum(1 for value in intervals if value > 33.0)
    long_50 = sum(1 for value in intervals if value > 50.0)
    final_min = _float(anchor.property("finalSpeakingEnergyMinDuringSpeaking"))
    final_max = _float(anchor.property("finalSpeakingEnergyMaxDuringSpeaking"))
    return {
        "case": case["case"],
        "name": case["name"],
        "fog_enabled": case["fog_enabled"],
        "visualizer_mode_requested": case["visualizer_mode"],
        "current_visualizer_mode": _json_value(shell.property("currentAnchorVisualizerMode")),
        "qmlSpeakingEnergySource": _json_value(shell.property("qmlSpeakingEnergySource")),
        "chosen_l06_visualizer_strategy": _json_value(shell.property("chosenL06VisualizerStrategy")),
        "envelope_timeline_ready_at_playback_start": _bool(
            shell.property("envelopeTimelineReadyAtPlaybackStart")
        ),
        "anchor_visualizer_unavailable": _bool(anchor.property("anchorVisualizerModeUnavailable")),
        "anchor_visualizer_unavailable_reason": _json_value(
            anchor.property("anchorVisualizerModeUnavailableReason")
        ),
        "finalSpeakingEnergyMin": round(final_min, 4),
        "finalSpeakingEnergyMax": round(final_max, 4),
        "visual_energy_range": round(max(0.0, final_max - final_min), 4),
        "frameSwappedCount": len(case_swaps),
        "frameSwappedFps": round(len(case_swaps) / duration, 2),
        "maxFrameGapMs": round(max(intervals) if intervals else 0.0, 3),
        "longFramesOver33Ms": long_33,
        "longFramesOver50Ms": long_50,
        "voicePayloadUpdatesPerSecond": _json_value(
            shell.property("voicePayloadUpdatesPerSecond")
        ),
        "voiceSurfaceUpdatesPerSecond": _json_value(
            shell.property("voiceSurfaceUpdatesPerSecond")
        ),
        "visualVoiceStateApplyRateDuringSpeaking": _json_value(
            shell.property("visualVoiceStateApplyRateDuringSpeaking")
        ),
        "anchorPaintCountPerSecond": _json_value(
            anchor.property("anchorPaintCountPerSecond")
        ),
        "anchorRequestPaintCountPerSecond": _json_value(
            anchor.property("anchorRequestPaintCountPerSecond")
        ),
        "sharedAnimationClockFps": _json_value(shell.property("visualClockFps")),
        "sharedAnimationClockMaxGapMs": _json_value(
            shell.property("visualClockMaxFrameGapMs")
        ),
        "sharedAnimationClockLongFrames": _json_value(
            shell.property("visualClockLongFrameCount")
        ),
        "fogActive": _json_value(fog.property("active")) if fog else None,
        "fogDisabledReason": _json_value(fog.property("disabledReason")) if fog else None,
        "subjective_result": "not_recorded",
        "expected_interpretation": case["expected"],
    }


def _write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# Stormforge Voice Visualizer A/B Isolation Report",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Probe version: `{report['probe_version']}`",
        f"- Live audible voice playback exercised: `{report['live_audible_voice_playback_exercised']}`",
        f"- Report caveat: {report['report_caveat']}",
        "",
        "| Case | Fog | Mode | Source | Energy Range | FPS | >33ms | >50ms | Subjective |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for case in report["cases"]:
        lines.append(
            "| {case} | {fog} | `{mode}` | `{source}` | {energy:.4f} | {fps:.2f} | {l33} | {l50} | {subjective} |".format(
                case=case["case"],
                fog="on" if case["fog_enabled"] else "off",
                mode=case["visualizer_mode_requested"],
                source=case["qmlSpeakingEnergySource"],
                energy=case["visual_energy_range"],
                fps=case["frameSwappedFps"],
                l33=case["longFramesOver33Ms"],
                l50=case["longFramesOver50Ms"],
                subjective=case["subjective_result"],
            )
        )
    lines.extend(
        [
            "",
            "## Manual Live Scoring Needed",
            "",
            "Run the same six cases around an audible Stormhelm spoken response. Fill `subjective_result` as `smooth`, `stutter`, `freeze`, or `no_animation` before treating this as root-cause proof.",
            "",
            "Suggested launch overrides:",
            "",
            "```powershell",
            "$env:STORMHELM_UI_VARIANT='stormforge'",
            "$env:STORMHELM_STORMFORGE_FOG='0' # or 1",
            "$env:STORMHELM_ANCHOR_VISUALIZER_MODE='constant_test_wave'",
            "```",
        ]
    )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_probe(duration_ms: int, voice_event_interval_ms: int) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    QQuickStyle.setStyle("Basic")
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(ASSETS))
    component = QtQml.QQmlComponent(engine)
    component.setData(
        PROBE_QML.encode("utf-8"),
        QtCore.QUrl.fromLocalFile(str(ASSETS / "StormforgeVoiceVisualizerAbProbe.qml")),
    )
    window = component.create()
    if not component.isReady() or window is None:
        raise RuntimeError(f"Could not create probe window: {component.errors()}")
    shell = window.findChild(QtCore.QObject, "stormforgeVoiceVisualizerAbProbeGhost")
    if shell is None:
        raise RuntimeError("Probe Ghost shell was not created.")
    anchor = shell.findChild(QtCore.QObject, "stormforgeAnchorCore")
    if anchor is None:
        raise RuntimeError("Probe anchor was not created.")
    fog = shell.findChild(QtCore.QObject, "stormforgeVolumetricFogLayer")
    frame_swaps: list[tuple[str, float]] = []
    current_case = {"name": "idle"}

    def on_frame_swapped() -> None:
        frame_swaps.append((str(current_case["name"]), time.perf_counter()))

    if isinstance(window, QtGui.QWindow):
        window.frameSwapped.connect(on_frame_swapped)

    _wait(app, 300)
    case_reports: list[dict[str, Any]] = []
    frame_rows: list[dict[str, Any]] = []

    for case in CASES:
        current_case["name"] = case["name"]
        playback_id = f"ab-{case['case'].lower()}-{int(time.time() * 1000)}"
        shell.setProperty(
            "stormforgeFogConfig",
            {
                "enabled": bool(case["fog_enabled"]),
                "mode": "volumetric",
                "quality": "medium",
                "diagnosticDisableDuringSpeech": False,
            },
        )
        shell.setProperty(
            "stormforgeVoiceDiagnosticsConfig",
            {
                "anchorVisualizerMode": case["visualizer_mode"],
                "liveIsolationVersion": "UI-VOICE-LIVE-ISO",
            },
        )
        shell.setProperty("voiceState", _voice_state(False, playback_id=playback_id, mode=case["visualizer_mode"], tick=0))
        _wait(app, 180)
        started = time.perf_counter()
        tick = 0
        while (time.perf_counter() - started) * 1000.0 < duration_ms:
            shell.setProperty(
                "voiceState",
                _voice_state(
                    True,
                    playback_id=playback_id,
                    mode=str(case["visualizer_mode"]),
                    tick=tick,
                ),
            )
            _wait(app, voice_event_interval_ms)
            tick += max(1, int(round(voice_event_interval_ms / 16.0)))
        ended = time.perf_counter()
        case_reports.append(
            _sample_case(
                case=case,
                shell=shell,
                anchor=anchor,
                fog=fog,
                frame_swaps=frame_swaps,
                started=started,
                ended=ended,
            )
        )
        current_case["name"] = "idle"
        shell.setProperty("voiceState", _voice_state(False, playback_id=playback_id, mode=case["visualizer_mode"], tick=tick))
        _wait(app, 180)

    for case_name in {case["name"] for case in CASES}:
        stamps = [stamp for name, stamp in frame_swaps if name == case_name]
        origin = stamps[0] if stamps else 0.0
        previous = None
        for index, stamp in enumerate(stamps):
            frame_rows.append(
                {
                    "case": case_name,
                    "index": index,
                    "timestamp_ms": round((stamp - origin) * 1000.0, 3),
                    "interval_ms": round((stamp - previous) * 1000.0, 3) if previous else 0.0,
                }
            )
            previous = stamp

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe_version": "UI-VOICE-LIVE-ISO",
        "live_audible_voice_playback_exercised": False,
        "visible_qquickwindow_probe": True,
        "raw_audio_exposed": False,
        "report_caveat": "This run exercises a visible desktop QML probe with simulated speaking state, not a real audible Stormhelm TTS response.",
        "cases": case_reports,
        "root_cause_conclusion": "not_identified_until_manual_live_subjective_results_are_recorded",
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report)
    with FRAME_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("case", "index", "timestamp_ms", "interval_ms"))
        writer.writeheader()
        writer.writerows(frame_rows)
    window.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-ms", type=int, default=1400)
    parser.add_argument("--voice-event-interval-ms", type=int, default=55)
    args = parser.parse_args()
    report = run_probe(
        duration_ms=max(400, args.duration_ms),
        voice_event_interval_ms=max(16, args.voice_event_interval_ms),
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
