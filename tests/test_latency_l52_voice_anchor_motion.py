from __future__ import annotations

import struct

import pytest
from PySide6 import QtCore
from PySide6 import QtTest

from stormhelm.ui.voice_surface import build_voice_ui_state
from tests.test_qml_shell import _dispose_qt_objects
from tests.test_qml_shell import _load_main_qml_scene
from tests.test_voice_ui_state_payload import _voice_status


def test_audio_envelope_computes_bounded_levels_without_exposing_audio() -> None:
    from stormhelm.core.voice.visualizer import compute_voice_audio_envelope

    quiet_pcm = struct.pack("<hhhh", 120, -120, 80, -80)
    loud_pcm = struct.pack("<hhhh", 16000, -16000, 14000, -14000)

    quiet = compute_voice_audio_envelope(
        quiet_pcm,
        audio_format="pcm",
        source="streaming_chunk_envelope",
    )
    loud = compute_voice_audio_envelope(
        loud_pcm,
        audio_format="pcm",
        source="playback_output_envelope",
        previous=quiet,
    )

    assert 0.0 <= quiet.rms_level <= 1.0
    assert 0.0 <= loud.rms_level <= 1.0
    assert loud.rms_level > quiet.rms_level
    assert loud.peak_level > quiet.peak_level
    assert loud.smoothed_level > quiet.smoothed_level
    assert loud.speech_energy > quiet.speech_energy
    assert loud.source == "playback_output_envelope"
    payload = loud.to_dict()
    assert payload["raw_audio_present"] is False
    assert "16000" not in str(payload)
    assert "raw_audio_bytes" not in str(payload)


def test_voice_anchor_state_machine_distinguishes_preparing_speaking_and_muted() -> None:
    from stormhelm.core.voice.visualizer import build_voice_anchor_payload

    base = _voice_status()["voice"]
    idle = build_voice_anchor_payload(base)
    preparing = build_voice_anchor_payload(
        {
            **base,
            "tts": {
                **base["tts"],
                "streaming_tts_enabled": True,
                "streaming_tts_status": "started",
            },
            "playback": {
                **base["playback"],
                "first_audio_pending": True,
                "first_audio_started": False,
            },
        }
    )
    speaking = build_voice_anchor_payload(
        {
            **base,
            "voice_output_envelope": {
                "source": "playback_output_envelope",
                "rms_level": 0.42,
                "peak_level": 0.74,
                "smoothed_level": 0.62,
                "speech_energy": 0.68,
                "update_hz": 30,
                "raw_audio_present": False,
            },
            "playback": {
                **base["playback"],
                "active_playback_status": "playing",
                "live_playback_status": "playing",
                "first_audio_started": True,
            },
        }
    )
    muted = build_voice_anchor_payload(
        {
            **base,
            "voice_output_envelope": {
                "source": "playback_output_envelope",
                "rms_level": 0.7,
                "peak_level": 0.8,
                "smoothed_level": 0.72,
                "speech_energy": 0.75,
                "raw_audio_present": False,
            },
            "playback": {
                **base["playback"],
                "active_playback_status": "playing",
                "first_audio_started": True,
            },
            "interruption": {
                "spoken_output_muted": True,
                "last_interruption_status": "completed",
            },
        }
    )

    assert idle["state"] == "idle"
    assert idle["motion_intensity"] < 0.2
    assert preparing["state"] == "preparing_speech"
    assert preparing["speaking_visual_active"] is False
    assert speaking["state"] == "speaking"
    assert speaking["speaking_visual_active"] is True
    assert speaking["audio_reactive_available"] is True
    assert speaking["motion_intensity"] >= idle["motion_intensity"] + 0.35
    assert speaking["user_heard_claimed"] is False
    assert muted["state"] == "muted"
    assert muted["speaking_visual_active"] is False
    assert muted["motion_intensity"] < 0.12


def test_voice_anchor_visualizer_source_ladder_labels_fallbacks_honestly() -> None:
    from stormhelm.core.voice.visualizer import build_voice_anchor_payload

    base = _voice_status()["voice"]
    precomputed = build_voice_anchor_payload(
        {
            **base,
            "tts": {
                **base["tts"],
                "precomputed_artifact_envelope": {
                    "source": "precomputed_artifact_envelope",
                    "rms_level": 0.31,
                    "peak_level": 0.62,
                    "smoothed_level": 0.44,
                    "speech_energy": 0.5,
                    "raw_audio_present": False,
                },
            },
            "playback": {
                **base["playback"],
                "active_playback_status": "playing",
                "first_audio_started": True,
            },
        }
    )
    synthetic = build_voice_anchor_payload(
        {
            **base,
            "playback": {
                **base["playback"],
                "active_playback_status": "playing",
                "first_audio_started": True,
            },
        }
    )
    unavailable = build_voice_anchor_payload(base)

    assert precomputed["audio_reactive_source"] == "precomputed_artifact_envelope"
    assert precomputed["audio_reactive_available"] is True
    assert synthetic["audio_reactive_source"] == "synthetic_fallback_envelope"
    assert synthetic["audio_reactive_available"] is False
    assert synthetic["synthetic_fallback"] is True
    assert unavailable["audio_reactive_source"] == "unavailable"
    assert unavailable["audio_reactive_available"] is False
    assert unavailable["speaking_visual_active"] is False


def test_voice_ui_state_exposes_backend_anchor_payload_and_truth_flags() -> None:
    status = _voice_status(
        voice_anchor={
            "state": "speaking",
            "state_label": "Speaking",
            "speaking_visual_active": True,
            "motion_intensity": 0.78,
            "audio_reactive_available": True,
            "audio_reactive_source": "playback_output_envelope",
            "output_level_rms": 0.52,
            "output_level_peak": 0.81,
            "smoothed_output_level": 0.67,
            "speech_energy": 0.72,
            "visualizer_update_hz": 30,
            "raw_audio_present": False,
            "user_heard_claimed": False,
        }
    )

    payload = build_voice_ui_state(status)

    assert payload["voice_anchor_state"] == "speaking"
    assert payload["speaking_visual_active"] is True
    assert payload["voice_motion_intensity"] == pytest.approx(0.78)
    assert payload["voice_smoothed_output_level"] == pytest.approx(0.67)
    assert payload["voice_audio_reactive_available"] is True
    assert payload["voice_anchor_truth_flags"]["user_heard_claimed"] is False
    assert payload["voice_anchor_truth_flags"]["speaking_visual_is_not_completion"] is True
    assert "raw audio" not in str(payload).lower()
    assert "generated_audio_bytes" not in str(payload).lower()


def test_latency_trace_exposes_voice_anchor_visualizer_fields() -> None:
    from stormhelm.core.latency import build_latency_trace

    trace = build_latency_trace(
        metadata={
            "voice_latency": {
                "voice_anchor": {
                    "state": "speaking",
                    "speaking_visual_active": True,
                    "motion_intensity": 0.73,
                    "audio_reactive_source": "streaming_chunk_envelope",
                    "audio_reactive_available": True,
                    "smoothed_output_level": 0.59,
                    "visualizer_update_hz": 30,
                    "user_heard_claimed": False,
                    "raw_audio_present": False,
                }
            }
        },
        stage_timings_ms={"total_ms": 10.0},
        route_family="voice_control",
        subsystem="voice",
        voice_involved=True,
    )

    payload = trace.to_dict()

    assert payload["voice_anchor_state"] == "speaking"
    assert payload["voice_speaking_visual_active"] is True
    assert payload["voice_audio_reactive_source"] == "streaming_chunk_envelope"
    assert payload["voice_audio_reactive_available"] is True
    assert payload["voice_anchor_motion_intensity"] == pytest.approx(0.73)
    assert payload["voice_anchor_audio_level"] == pytest.approx(0.59)
    assert payload["voice_anchor_user_heard_claimed"] is False
    assert "raw_audio" not in str(payload).lower()


def test_main_qml_binds_voice_core_to_backend_voice_anchor_state() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene()
    try:
        bridge.apply_snapshot(
            {
                "status": _voice_status(
                    voice_anchor={
                        "state": "speaking",
                        "state_label": "Speaking",
                        "speaking_visual_active": True,
                        "motion_intensity": 0.82,
                        "audio_reactive_available": True,
                        "audio_reactive_source": "playback_output_envelope",
                        "output_level_rms": 0.48,
                        "output_level_peak": 0.77,
                        "smoothed_output_level": 0.66,
                        "speech_energy": 0.7,
                        "visualizer_update_hz": 30,
                        "raw_audio_present": False,
                        "user_heard_claimed": False,
                    }
                )
            }
        )
        app.processEvents()
        QtTest.QTest.qWait(60)
        app.processEvents()

        voice_core = root.findChild(QtCore.QObject, "ghostVoiceCore")
        assert voice_core is not None
        assert voice_core.property("anchorState") == "speaking"
        assert voice_core.property("speakingActive") is True
        assert float(voice_core.property("motionIntensity")) == pytest.approx(0.82)
        assert float(voice_core.property("audioLevel")) == pytest.approx(0.66)
        assert voice_core.property("audioReactiveAvailable") is True
        assert voice_core.property("idleLoopMode") == "continuous_time"
        first_phase = float(voice_core.property("phase"))
        QtTest.QTest.qWait(120)
        app.processEvents()
        assert float(voice_core.property("phase")) > first_phase
    finally:
        _dispose_qt_objects(app, root, engine, bridge)
