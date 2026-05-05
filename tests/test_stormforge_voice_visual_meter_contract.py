from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtCore, QtQml, QtTest
from PySide6.QtQuickControls2 import QQuickStyle

from stormhelm.config.loader import load_config
from tests.test_qml_shell import _dispose_qt_objects, _ensure_app


def test_stormforge_anchor_uses_pcm_stream_meter_scalar_contract() -> None:
    source = (
        Path.cwd()
        / "assets"
        / "qml"
        / "variants"
        / "stormforge"
        / "StormforgeAnchorCore.qml"
    ).read_text(encoding="utf-8")

    assert "voice_visual_energy" in source
    assert "voiceVisualEnergy" in source
    assert "pcm_stream_meter" in source
    assert "voiceVisualActive" in source
    assert "root.voiceVisualEnergy" in source
    assert "Playback envelope warming" not in source
    assert "stormhelm_playback_meter" not in source


def test_stormforge_anchor_keeps_legacy_timeline_out_of_meter_production_path() -> None:
    source = (
        Path.cwd()
        / "assets"
        / "qml"
        / "variants"
        / "stormforge"
        / "StormforgeAnchorCore.qml"
    ).read_text(encoding="utf-8")

    meter_branch = source.index('root.visualizerSourceStrategy === "pcm_stream_meter"')
    timeline_sample = source.index("samplePlaybackEnvelopeEnergy")

    assert meter_branch < timeline_sample
    assert 'normalized === "pcm_stream_meter"' in source
    assert 'return "pcm_stream_meter"' in source
    assert "uniformScalePulseDisabled: true" in source
    assert "centerUniformSpeakingScaleDisabled: true" in source


def _create_stormforge_anchor(harness_qml: str):
    app = _ensure_app()
    QQuickStyle.setStyle("Basic")
    workspace_config = load_config(project_root=Path.cwd(), env={})
    engine = QtQml.QQmlEngine()
    engine.addImportPath(str(workspace_config.runtime.assets_dir / "qml"))
    component = QtQml.QQmlComponent(engine)
    component.setData(
        harness_qml.strip().encode("utf-8"),
        QtCore.QUrl.fromLocalFile(
            str(
                workspace_config.runtime.assets_dir
                / "qml"
                / "StormforgeVoiceVisualMeterHarness.qml"
            )
        ),
    )
    anchor = component.create()
    app.processEvents()
    QtTest.QTest.qWait(180)
    app.processEvents()
    assert component.isReady(), component.errors()
    assert anchor is not None
    return app, engine, component, anchor


def test_stormforge_anchor_meter_energy_drives_speaking_without_timeline() -> None:
    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {
    objectName: "pcmMeterAnchor"
    width: 230
    height: 270
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "playback_id": "meter-qml-1",
        "voice_visual_active": true,
        "voice_visual_available": true,
        "voice_visual_energy": 0.64,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy_source": "pcm_stream_meter",
        "voice_visual_playback_id": "meter-qml-1",
        "voice_visual_sample_rate_hz": 60,
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "pcm_stream_meter",
        "playback_envelope_available": false,
        "playback_envelope_supported": false,
        "playback_envelope_samples_recent": [],
        "envelopeTimelineSamples": []
    })
}
"""
    app, engine, component, anchor = _create_stormforge_anchor(harness_qml)
    try:
        assert anchor.property("voiceVisualSource") == "pcm_stream_meter"
        assert bool(anchor.property("voiceVisualActive")) is True
        assert float(anchor.property("voiceVisualEnergy")) == pytest.approx(0.64)
        assert anchor.property("visualizerSourceStrategy") == "pcm_stream_meter"
        assert anchor.property("qmlSpeakingEnergySource") == "pcm_stream_meter"
        assert float(anchor.property("finalSpeakingEnergy")) > 0.05
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is False
        assert bool(anchor.property("playbackEnvelopeTimelineActive")) is False
        assert anchor.property("resolvedSublabel") == "PCM stream meter"
        assert bool(anchor.property("uniformScalePulseDisabled")) is True
    finally:
        _dispose_qt_objects(app, anchor, component, engine)


def test_stormforge_anchor_idle_ignores_stale_voice_visual_energy() -> None:
    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {
    objectName: "idleMeterAnchor"
    width: 230
    height: 270
    voiceState: ({
        "voice_anchor_state": "idle",
        "speaking_visual_active": false,
        "active_playback_status": "idle",
        "voice_visual_active": false,
        "voice_visual_available": true,
        "voice_visual_energy": 0.92,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy_source": "pcm_stream_meter"
    })
}
"""
    app, engine, component, anchor = _create_stormforge_anchor(harness_qml)
    try:
        assert bool(anchor.property("voiceVisualActive")) is False
        assert anchor.property("visualizerSourceStrategy") == "none"
        assert float(anchor.property("finalSpeakingEnergy")) == pytest.approx(0.0)
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is False
    finally:
        _dispose_qt_objects(app, anchor, component, engine)


def test_stormforge_anchor_procedural_test_fallback_stays_explicit() -> None:
    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {
    objectName: "proceduralTestAnchor"
    width: 230
    height: 270
    visualizerDiagnosticMode: "procedural_test"
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "voice_visual_active": false,
        "voice_visual_available": false,
        "voice_visual_energy": 0.0,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_disabled_reason": "visual_meter_disabled"
    })
}
"""
    app, engine, component, anchor = _create_stormforge_anchor(harness_qml)
    try:
        assert anchor.property("effectiveAnchorVisualizerMode") == "procedural_test"
        assert anchor.property("visualizerSourceStrategy") == "procedural_speaking"
        assert bool(anchor.property("proceduralFallbackActive")) is True
        assert float(anchor.property("finalSpeakingEnergy")) > 0.0
        assert bool(anchor.property("anchorUsesPlaybackEnvelope")) is False
    finally:
        _dispose_qt_objects(app, anchor, component, engine)


def test_stormforge_anchor_exposes_reactive_chain_qml_diagnostics() -> None:
    source = (
        Path.cwd()
        / "assets"
        / "qml"
        / "variants"
        / "stormforge"
        / "StormforgeAnchorCore.qml"
    ).read_text(encoding="utf-8")

    for diagnostic_name in [
        "qmlReceivedVoiceVisualEnergy",
        "qmlReceivedEnergyTimeMs",
        "qmlReceivedVoiceVisualSource",
        "qmlReceivedPlaybackId",
        "qmlFinalSpeakingEnergy",
        "finalSpeakingEnergyUpdatedAtMs",
        "qmlSpeechEnergySource",
        "qmlVoiceVisualActive",
        "qmlEnergySampleAgeMs",
        "qmlAnchorPaintCount",
        "qmlAnchorRequestPaintCount",
        "qmlLastPaintTimeMs",
        "qmlFrameTimeMs",
        "anchorSpeakingVisualActive",
        "anchorCurrentVisualState",
        "anchorMotionMode",
        "anchorEnergyToPaintLatencyMs",
        "anchorStaleEnergyReason",
        "anchorReleaseReason",
        "anchorSpeakingEnteredAtMs",
        "anchorSpeakingExitedAtMs",
        "qmlAnchorReactiveChainVersion",
    ]:
        assert diagnostic_name in source

    harness_qml = """
import QtQuick 2.15
import "variants/stormforge"

StormforgeAnchorCore {
    objectName: "reactiveChainDiagnosticAnchor"
    width: 230
    height: 270
    renderLoopDiagnosticsEnabled: true
    voiceState: ({
        "voice_anchor_state": "speaking",
        "voice_current_phase": "playback_active",
        "speaking_visual_active": true,
        "active_playback_status": "playing",
        "playback_id": "qml-diag-1",
        "voice_visual_active": true,
        "voice_visual_available": true,
        "voice_visual_energy": 0.58,
        "voice_visual_source": "pcm_stream_meter",
        "voice_visual_energy_source": "pcm_stream_meter",
        "voice_visual_playback_id": "qml-diag-1",
        "voice_visual_sample_rate_hz": 60,
        "voice_visual_latest_age_ms": 12,
        "voice_audio_reactive_available": true,
        "voice_audio_reactive_source": "pcm_stream_meter",
        "playback_envelope_available": false,
        "playback_envelope_supported": false,
        "playback_envelope_samples_recent": [],
        "envelopeTimelineSamples": []
    })
}
"""
    app, engine, component, anchor = _create_stormforge_anchor(harness_qml)
    try:
        assert anchor.property("qmlAnchorReactiveChainVersion") == "Voice-AR-DIAG"
        assert float(anchor.property("qmlReceivedVoiceVisualEnergy")) == pytest.approx(0.58)
        assert bool(anchor.property("qmlVoiceVisualActive")) is True
        assert anchor.property("qmlReceivedVoiceVisualSource") == "pcm_stream_meter"
        assert anchor.property("qmlReceivedPlaybackId") == "qml-diag-1"
        assert anchor.property("qmlSpeechEnergySource") == "pcm_stream_meter"
        assert float(anchor.property("qmlFinalSpeakingEnergy")) > 0.0
        assert float(anchor.property("finalSpeakingEnergyUpdatedAtMs")) > 0.0
        assert float(anchor.property("qmlEnergySampleAgeMs")) == pytest.approx(12.0)
        assert float(anchor.property("qmlReceivedEnergyTimeMs")) > 0.0
        assert float(anchor.property("qmlFrameTimeMs")) > 0.0
        assert int(anchor.property("qmlAnchorPaintCount")) >= 0
        assert int(anchor.property("qmlAnchorRequestPaintCount")) >= 0
        assert float(anchor.property("qmlLastPaintTimeMs")) >= 0.0
        assert bool(anchor.property("anchorSpeakingVisualActive")) is True
        assert anchor.property("anchorCurrentVisualState") == "speaking"
        assert anchor.property("anchorMotionMode")
        assert float(anchor.property("anchorEnergyToPaintLatencyMs")) >= 0.0
        assert anchor.property("anchorStaleEnergyReason") == ""
        assert float(anchor.property("anchorSpeakingEnteredAtMs")) > 0.0
    finally:
        _dispose_qt_objects(app, anchor, component, engine)
