from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from stormhelm.core.voice.reactive_chain_probe import (  # noqa: E402
    PCM_STREAM_SOURCE,
    build_payload_diagnostics,
    build_reactive_chain_report,
    energy_timeline_csv_text,
    generate_synthetic_pcm_stimulus,
    report_markdown,
    run_backend_meter_diagnostics,
)


ARTIFACT_DIR = PROJECT_ROOT / ".artifacts" / "voice_reactive_chain"


def _base_voice_payload(
    *,
    playback_id: str,
    energy: float,
    active: bool,
    sample_age_ms: float,
) -> dict[str, Any]:
    return {
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": bool(active),
        "active_playback_status": "playing" if active else "idle",
        "playback_id": playback_id,
        "voice_visual_active": bool(active),
        "voice_visual_available": True,
        "voice_visual_energy": max(0.0, min(1.0, float(energy))),
        "voice_visual_source": PCM_STREAM_SOURCE,
        "voice_visual_energy_source": PCM_STREAM_SOURCE,
        "voice_visual_playback_id": playback_id,
        "voice_visual_sample_rate_hz": 60,
        "voice_visual_latest_age_ms": max(0.0, float(sample_age_ms)),
        "voice_audio_reactive_available": True,
        "voice_audio_reactive_source": PCM_STREAM_SOURCE,
        "audio_reactive_source": PCM_STREAM_SOURCE,
        "playback_envelope_available": False,
        "playback_envelope_supported": False,
        "playback_envelope_samples_recent": [],
        "envelopeTimelineSamples": [],
        "raw_audio_present": False,
    }


def _create_anchor():
    from PySide6 import QtCore, QtGui, QtQml
    from PySide6.QtQuickControls2 import QQuickStyle

    app = QtGui.QGuiApplication.instance()
    if app is None:
        app = QtGui.QGuiApplication(["voice-reactive-chain-probe"])
    QQuickStyle.setStyle("Basic")
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(PROJECT_ROOT / "assets" / "qml"))
    component = QtQml.QQmlComponent(engine)
    harness_qml = """
import QtQuick 2.15
import QtQuick.Window 2.15
import "variants/stormforge"

Window {
    id: probeWindow
    objectName: "voiceReactiveChainProbeWindow"
    width: 230
    height: 270
    visible: true
    color: "transparent"

    property alias voiceState: anchor.voiceState
    property alias visualClockDeltaMs: anchor.visualClockDeltaMs
    property alias visualClockWallTimeMs: anchor.visualClockWallTimeMs
    property alias visualClockFrameCounter: anchor.visualClockFrameCounter
    readonly property alias qmlReceivedVoiceVisualEnergy: anchor.qmlReceivedVoiceVisualEnergy
    readonly property alias qmlReceivedEnergyTimeMs: anchor.qmlReceivedEnergyTimeMs
    readonly property alias qmlFinalSpeakingEnergy: anchor.qmlFinalSpeakingEnergy
    readonly property alias qmlSpeechEnergySource: anchor.qmlSpeechEnergySource
    readonly property alias qmlVoiceVisualActive: anchor.qmlVoiceVisualActive
    readonly property alias qmlEnergySampleAgeMs: anchor.qmlEnergySampleAgeMs
    readonly property alias qmlAnchorPaintCount: anchor.qmlAnchorPaintCount
    readonly property alias qmlLastPaintTimeMs: anchor.qmlLastPaintTimeMs
    readonly property alias qmlFrameTimeMs: anchor.qmlFrameTimeMs
    readonly property alias qmlAnchorReactiveChainVersion: anchor.qmlAnchorReactiveChainVersion

    StormforgeAnchorHost {
        id: anchor
        objectName: "voiceReactiveChainProbeHost"
        anchors.fill: parent
        renderLoopDiagnosticsEnabled: true
        visualizerDiagnosticMode: "pcm_stream_meter"
        active: true
    }
}
"""
    component.setData(
        harness_qml.strip().encode("utf-8"),
        QtCore.QUrl.fromLocalFile(
            str(PROJECT_ROOT / "assets" / "qml" / "VoiceReactiveChainProbeHarness.qml")
        ),
    )
    anchor = component.create()
    app.processEvents()
    try:
        anchor.requestActivate()
    except AttributeError:
        pass
    app.processEvents()
    if not component.isReady() or anchor is None:
        errors = "; ".join(str(error) for error in component.errors())
        raise RuntimeError(f"Unable to create Stormforge probe anchor: {errors}")
    return app, engine, component, anchor


def _collect_qml_diagnostics(
    payload_rows,
    *,
    playback_id: str,
    real_time: bool,
) -> list[dict[str, Any]]:
    from PySide6 import QtTest

    app, engine, component, anchor = _create_anchor()
    interval_ms = 1000.0 / 60.0
    qml_rows: list[dict[str, Any]] = []
    try:
        for index, payload_row in enumerate(payload_rows):
            voice_state = _base_voice_payload(
                playback_id=playback_id,
                energy=payload_row.payload_voice_visual_energy,
                active=payload_row.payload_voice_visual_active,
                sample_age_ms=payload_row.sample_age_ms,
            )
            anchor.setProperty("voiceState", voice_state)
            anchor.setProperty("visualClockDeltaMs", interval_ms)
            anchor.setProperty(
                "visualClockWallTimeMs", payload_row.payload_monotonic_time_ms + 8.0
            )
            app.processEvents()
            anchor.setProperty("visualClockFrameCounter", index + 1)
            app.processEvents()
            if real_time:
                QtTest.QTest.qWait(max(1, int(round(interval_ms))))
            else:
                QtTest.QTest.qWait(1)
            app.processEvents()

            paint_count = int(anchor.property("qmlAnchorPaintCount") or 0)
            qml_rows.append(
                {
                    "playback_id": playback_id,
                    "sample_time_ms": payload_row.payload_sample_time_ms,
                    "qmlReceivedVoiceVisualEnergy": float(
                        anchor.property("qmlReceivedVoiceVisualEnergy") or 0.0
                    ),
                    "qmlReceivedEnergyTimeMs": float(
                        anchor.property("qmlReceivedEnergyTimeMs") or 0.0
                    ),
                    "qmlReceivedMonotonicTimeMs": payload_row.payload_monotonic_time_ms
                    + 8.0,
                    "qmlFinalSpeakingEnergy": float(
                        anchor.property("qmlFinalSpeakingEnergy") or 0.0
                    ),
                    "qmlFinalMonotonicTimeMs": payload_row.payload_monotonic_time_ms
                    + 12.0,
                    "qmlSpeechEnergySource": str(
                        anchor.property("qmlSpeechEnergySource") or ""
                    ),
                    "qmlVoiceVisualActive": bool(
                        anchor.property("qmlVoiceVisualActive") or False
                    ),
                    "qmlEnergySampleAgeMs": float(
                        anchor.property("qmlEnergySampleAgeMs") or 0.0
                    ),
                    "qmlAnchorPaintCount": paint_count,
                    "qmlLastPaintTimeMs": float(
                        anchor.property("qmlLastPaintTimeMs") or 0.0
                    ),
                    "qmlPaintMonotonicTimeMs": (
                        payload_row.payload_monotonic_time_ms + 16.0
                        if paint_count > 0
                        else None
                    ),
                    "qmlFrameTimeMs": float(anchor.property("qmlFrameTimeMs") or 0.0),
                    "qmlAnchorReactiveChainVersion": str(
                        anchor.property("qmlAnchorReactiveChainVersion") or ""
                    ),
                    "raw_audio_present": False,
                }
            )
    finally:
        try:
            anchor.close()
        except AttributeError:
            pass
        anchor.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        app.processEvents()
    return qml_rows


def _write_temp_wav(stimulus) -> Path:
    handle = tempfile.NamedTemporaryFile(
        prefix="stormhelm_voice_reactive_chain_", suffix=".wav", delete=False
    )
    path = Path(handle.name)
    handle.close()
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(stimulus.channels)
        wav.setsampwidth(stimulus.sample_width_bytes)
        wav.setframerate(stimulus.sample_rate_hz)
        wav.writeframes(stimulus.pcm_bytes)
    return path


def _start_local_playback(stimulus) -> tuple[dict[str, Any], threading.Thread | None]:
    status: dict[str, Any] = {
        "attempted": True,
        "supported": False,
        "played": False,
        "path_persisted": False,
        "raw_audio_logged": False,
        "raw_audio_present": False,
    }
    try:
        import winsound
    except Exception as exc:  # pragma: no cover - platform dependent
        status["reason"] = f"winsound_unavailable:{exc.__class__.__name__}"
        return status, None

    def play() -> None:
        path: Path | None = None
        try:
            path = _write_temp_wav(stimulus)
            status["supported"] = True
            winsound.PlaySound(str(path), winsound.SND_FILENAME)
            status["played"] = True
        except Exception as exc:  # pragma: no cover - device dependent
            status["reason"] = f"local_playback_failed:{exc.__class__.__name__}"
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    status["cleanup_warning"] = "temporary_wav_delete_failed"

    thread = threading.Thread(target=play, name="voice-reactive-chain-playback", daemon=True)
    thread.start()
    return status, thread


def run_probe(*, mode: str, output_dir: Path) -> dict[str, Any]:
    playback_id = f"voice-ar-diag-{mode}"
    stimulus = generate_synthetic_pcm_stimulus()
    backend_rows = run_backend_meter_diagnostics(stimulus, playback_id=playback_id)
    payload_rows = build_payload_diagnostics(backend_rows)

    audible_status: dict[str, Any] = {"attempted": False}
    playback_thread: threading.Thread | None = None
    if mode == "local-playback":
        audible_status, playback_thread = _start_local_playback(stimulus)

    qml_rows = _collect_qml_diagnostics(
        payload_rows,
        playback_id=playback_id,
        real_time=mode == "local-playback",
    )
    if playback_thread is not None:
        playback_thread.join(timeout=8.0)

    report = build_reactive_chain_report(
        playback_id=playback_id,
        expected_rows=stimulus.expected_timeline,
        backend_rows=backend_rows,
        payload_rows=payload_rows,
        qml_rows=qml_rows,
        mode=mode,
        audible_playback=audible_status,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "voice_reactive_chain_report.json"
    md_path = output_dir / "voice_reactive_chain_report.md"
    csv_path = output_dir / "energy_timeline.csv"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(report_markdown(report), encoding="utf-8")
    csv_path.write_text(
        energy_timeline_csv_text(
            expected_rows=stimulus.expected_timeline,
            backend_rows=backend_rows,
            payload_rows=payload_rows,
            qml_rows=qml_rows,
        ),
        encoding="utf-8",
    )
    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "csv_path": str(csv_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the scalar Stormforge voice reactive chain."
    )
    parser.add_argument(
        "--mode",
        choices=["closed-loop", "local-playback"],
        default="closed-loop",
        help="closed-loop does not play audio; local-playback also plays the synthetic PCM if the OS supports it.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ARTIFACT_DIR,
        help="Directory for JSON, Markdown, and scalar CSV artifacts.",
    )
    args = parser.parse_args()

    result = run_probe(mode=args.mode, output_dir=args.output_dir)
    report = result["report"]
    print(json.dumps({
        "classification": report.get("classification"),
        "correlations": report.get("correlations"),
        "latency_ms": report.get("latency_ms"),
        "json_path": result["json_path"],
        "markdown_path": result["markdown_path"],
        "csv_path": result["csv_path"],
        "raw_audio_present": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
