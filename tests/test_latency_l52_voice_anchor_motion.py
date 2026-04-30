from __future__ import annotations

import asyncio
import json
import struct

import pytest
from PySide6 import QtCore
from PySide6 import QtTest

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import build_voice_subsystem
from stormhelm.ui.voice_surface import build_voice_ui_state
from tests.test_qml_shell import _dispose_qt_objects
from tests.test_qml_shell import _load_main_qml_scene
from tests.test_voice_ui_state_payload import _voice_status


def _pcm_frame(level: int, *, samples: int = 16) -> bytes:
    values = [level if index % 2 == 0 else -level for index in range(samples)]
    return struct.pack("<" + "h" * len(values), *values)


def _pcm_section(level: int, *, samples: int = 2400) -> bytes:
    values = [level if index % 2 == 0 else -level for index in range(samples)]
    return struct.pack("<" + "h" * len(values), *values)


def _voice_config() -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        mode="manual",
        spoken_responses_enabled=True,
        debug_mock_provider=True,
        openai=VoiceOpenAIConfig(
            stream_tts_outputs=True,
            tts_live_format="pcm",
            tts_artifact_format="mp3",
            max_tts_chars=240,
        ),
        playback=VoicePlaybackConfig(
            enabled=True,
            provider="mock",
            device="test-device",
            volume=0.5,
            allow_dev_playback=True,
            streaming_enabled=True,
            max_audio_bytes=4096,
            max_duration_ms=5000,
        ),
    )


def _openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        enabled=True,
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model="gpt-5.4-nano",
        planner_model="gpt-5.4-nano",
        reasoning_model="gpt-5.4",
        timeout_seconds=60,
        max_tool_rounds=4,
        max_output_tokens=1200,
        planner_max_output_tokens=900,
        reasoning_max_output_tokens=1400,
        instructions="",
    )


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


def test_pcm_chunk_is_split_into_playback_time_envelope_frames() -> None:
    from stormhelm.core.voice.visualizer import compute_voice_audio_envelope_frames

    pcm = (
        _pcm_section(0)
        + _pcm_section(2400)
        + _pcm_section(17000)
        + _pcm_section(0)
    )

    frames = compute_voice_audio_envelope_frames(
        pcm,
        audio_format="pcm",
        source="playback_output_envelope",
        sample_rate_hz=24000,
        channels=1,
        update_hz=30,
    )

    assert len(frames) >= 10
    drives = [frame.visual_drive for frame in frames]
    center_drives = [frame.envelope.center_blob_scale_drive for frame in frames]
    assert min(drives[:2]) <= 0.08
    assert max(drives) >= 0.8
    assert max(center_drives) >= 0.76
    assert frames[0].audio_offset_ms == 0
    assert frames[-1].audio_offset_ms > frames[0].audio_offset_ms
    assert all(frame.duration_ms > 0 for frame in frames)
    assert "17000" not in str([frame.to_dict() for frame in frames])
    assert "raw_audio_bytes" not in str([frame.to_dict() for frame in frames])


def test_backend_converts_low_rms_into_visible_visual_drive_level() -> None:
    from stormhelm.core.voice.visualizer import compute_voice_audio_envelope

    quiet_speech = compute_voice_audio_envelope(
        _pcm_frame(1200, samples=64),
        audio_format="pcm",
        source="playback_output_envelope",
    )

    assert quiet_speech.rms_level < 0.06
    assert 0.30 <= quiet_speech.visual_drive_level <= 0.45
    assert quiet_speech.visual_drive_peak >= quiet_speech.visual_drive_level
    assert quiet_speech.visual_gain >= 1.0


def test_visual_drive_dynamic_range_is_not_high_narrow_band() -> None:
    from stormhelm.core.voice.visualizer import compute_voice_audio_envelope

    silence = compute_voice_audio_envelope(
        _pcm_frame(0, samples=64),
        audio_format="pcm",
        source="playback_output_envelope",
    )
    quiet = compute_voice_audio_envelope(
        _pcm_frame(1800, samples=64),
        audio_format="pcm",
        source="playback_output_envelope",
        previous=silence,
    )
    normal = compute_voice_audio_envelope(
        _pcm_frame(7000, samples=64),
        audio_format="pcm",
        source="playback_output_envelope",
        previous=quiet,
    )
    loud = compute_voice_audio_envelope(
        _pcm_frame(24000, samples=64),
        audio_format="pcm",
        source="playback_output_envelope",
        previous=normal,
    )

    assert silence.visual_drive_level <= 0.08
    assert silence.center_blob_drive <= 0.05
    assert 0.20 <= quiet.visual_drive_level <= 0.40
    assert 0.15 <= quiet.center_blob_drive <= 0.38
    assert 0.45 <= normal.visual_drive_level <= 0.75
    assert 0.40 <= normal.center_blob_drive <= 0.72
    assert loud.visual_drive_level >= 0.80
    assert loud.center_blob_drive >= 0.76
    assert loud.visual_drive_level - quiet.visual_drive_level >= 0.45


def test_fast_center_blob_scale_drive_follows_fake_level_sequence() -> None:
    from stormhelm.core.voice.visualizer import compute_voice_audio_envelope

    levels = [0.0, 0.2, 0.8, 0.1, 1.0, 0.0]
    previous = None
    envelopes = []
    for level in levels:
        envelope = compute_voice_audio_envelope(
            _pcm_frame(int(level * 32767), samples=64),
            audio_format="pcm",
            source="playback_output_envelope",
            previous=previous,
        )
        envelopes.append(envelope)
        previous = envelope

    drives = [envelope.center_blob_scale_drive for envelope in envelopes]
    scales = [envelope.center_blob_scale for envelope in envelopes]

    assert drives[0] == pytest.approx(0.0)
    assert scales[0] == pytest.approx(1.0)
    assert drives[1] > drives[0] + 0.35
    assert drives[2] > drives[1] + 0.2
    assert drives[3] < drives[2] - 0.15
    assert drives[4] > drives[3] + 0.25
    assert drives[5] < 0.12
    assert scales[4] > scales[1] + 0.1
    assert scales[5] == pytest.approx(1.0, abs=0.04)


def test_streaming_playback_chunks_publish_changing_voice_envelope_fields() -> None:
    events = EventBuffer()
    service = build_voice_subsystem(_voice_config(), _openai_config(), events=events)
    quiet = _pcm_frame(180)
    loud = _pcm_frame(19000)
    silence = _pcm_frame(0)
    service.provider = MockVoiceProvider(
        tts_audio_bytes=quiet + loud + silence,
        tts_stream_chunk_size=len(quiet),
    )
    service.playback_provider = MockPlaybackProvider(complete_immediately=False)

    result = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Core approved envelope-reactive speech.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-envelope",
            core_result_completed_ms=12,
            request_started_ms=0,
        )
    )

    assert result.ok is True
    chunk_events = [
        event
        for event in events.recent(limit=80)
        if event.get("event_type") == "voice.tts_stream_chunk"
    ]
    assert len(chunk_events) >= 3
    voice_updates = [
        event["payload"]["metadata"]["voice"]
        for event in chunk_events
        if isinstance(event.get("payload"), dict)
        and isinstance(event["payload"].get("metadata"), dict)
        and isinstance(event["payload"]["metadata"].get("voice"), dict)
    ]
    assert len(voice_updates) >= 3
    levels = [float(update["voice_smoothed_output_level"]) for update in voice_updates]
    visual_drives = [float(update["voice_visual_drive_level"]) for update in voice_updates]
    center_drives = [float(update["voice_center_blob_drive"]) for update in voice_updates]
    assert levels[1] > levels[0] + 0.25
    assert levels[-1] < levels[1]
    assert visual_drives[1] > visual_drives[0] + 0.35
    assert visual_drives[-1] < visual_drives[1]
    assert center_drives[1] > center_drives[0] + 0.35
    assert center_drives[-1] < center_drives[1]
    assert voice_updates[1]["voice_audio_reactive_source"] == "playback_output_envelope"
    assert voice_updates[1]["voice_audio_reactive_available"] is True
    assert "19000" not in str(chunk_events)
    assert "raw_audio_bytes" not in str(chunk_events)
    assert "data': b" not in str(chunk_events)

    snapshot = service.status_snapshot_fast()
    assert snapshot["voice_smoothed_output_level"] < 0.12
    assert snapshot["voice_visual_drive_level"] == pytest.approx(0.0)
    assert snapshot["voice_center_blob_drive"] == pytest.approx(0.0)
    assert snapshot["speaking_visual_active"] is False


def test_single_long_playback_chunk_delivers_multiple_playback_time_envelope_updates() -> None:
    events = EventBuffer(capacity=256)
    service = build_voice_subsystem(_voice_config(), _openai_config(), events=events)
    pcm = (
        _pcm_section(0, samples=2400)
        + _pcm_section(2600, samples=2400)
        + _pcm_section(18500, samples=2400)
        + _pcm_section(0, samples=2400)
    )
    service.provider = MockVoiceProvider(
        tts_audio_bytes=pcm,
        tts_stream_chunk_size=len(pcm),
    )
    service.playback_provider = MockPlaybackProvider(complete_immediately=False)

    result = asyncio.run(
        service.stream_core_approved_spoken_text(
            "Bearing acquired. Stormhelm voice reactivity test.",
            speak_allowed=True,
            session_id="voice-session",
            turn_id="voice-turn-long-envelope",
            core_result_completed_ms=12,
            request_started_ms=0,
        )
    )

    assert result.ok is True
    chunk_events = [
        event
        for event in events.recent(limit=256)
        if event.get("event_type") == "voice.tts_stream_chunk"
    ]
    voice_updates = [
        event["payload"]["metadata"]["voice"]
        for event in chunk_events
        if isinstance(event.get("payload"), dict)
        and isinstance(event["payload"].get("metadata"), dict)
        and isinstance(event["payload"]["metadata"].get("voice"), dict)
    ]
    center_drives = [
        float(update["voice_center_blob_scale_drive"])
        for update in voice_updates
    ]

    assert len(voice_updates) >= 10
    frame_events = [
        event
        for event in chunk_events
        if isinstance(event.get("payload"), dict)
        and isinstance(event["payload"].get("metadata"), dict)
        and isinstance(event["payload"]["metadata"].get("audio_envelope_frame"), dict)
    ]
    assert len(frame_events) >= 10
    assert min(center_drives[:3]) <= 0.08
    assert max(center_drives) >= 0.76
    assert center_drives[-1] <= 0.12
    assert all(update["voice_audio_reactive_source"] == "playback_output_envelope" for update in voice_updates[:-1])
    assert "raw_audio_bytes" not in str(chunk_events)
    assert "data': b" not in str(chunk_events)

    snapshot = service.status_snapshot_fast()
    assert snapshot["voice_visualizer_envelope_frames_generated"] >= len(frame_events)
    assert snapshot["voice_visualizer_envelope_frames_published"] >= len(frame_events)
    assert snapshot["voice_visualizer_queue_depth"] == 0
    assert snapshot["voice_visualizer"]["raw_audio_present"] is False


def test_fake_envelope_sequence_drives_visual_drive_and_motion_then_stop_damps() -> None:
    from stormhelm.core.voice.visualizer import build_voice_anchor_payload
    from stormhelm.core.voice.visualizer import compute_voice_audio_envelope

    base = _voice_status()["voice"]
    playback = {
        **base["playback"],
        "active_playback_status": "playing",
        "live_playback_status": "playing",
        "first_audio_started": True,
    }
    quiet = compute_voice_audio_envelope(
        _pcm_frame(220),
        audio_format="pcm",
        source="playback_output_envelope",
    )
    loud = compute_voice_audio_envelope(
        _pcm_frame(21000),
        audio_format="pcm",
        source="playback_output_envelope",
        previous=quiet,
    )

    quiet_anchor = build_voice_anchor_payload(
        {**base, "voice_output_envelope": quiet.to_dict(), "playback": playback}
    )
    loud_anchor = build_voice_anchor_payload(
        {**base, "voice_output_envelope": loud.to_dict(), "playback": playback}
    )
    stopped_anchor = build_voice_anchor_payload(
        {
            **base,
            "voice_output_envelope": {
                "source": "unavailable",
                "rms_level": 0.0,
                "peak_level": 0.0,
                "smoothed_level": 0.0,
                "speech_energy": 0.0,
                "raw_audio_present": False,
            },
            "playback": {
                **base["playback"],
                "active_playback_status": "stopped",
                "live_playback_status": "stopped",
                "first_audio_started": False,
            },
            "interruption": {
                "last_interruption_status": "completed",
                "last_interruption_intent": "stop_speaking",
                "playback_stopped": True,
            },
        }
    )

    assert loud_anchor["smoothed_output_level"] > quiet_anchor["smoothed_output_level"] + 0.25
    assert loud_anchor["visual_drive_level"] > quiet_anchor["visual_drive_level"] + 0.25
    assert loud_anchor["center_blob_drive"] > quiet_anchor["center_blob_drive"] + 0.25
    assert loud_anchor["motion_intensity"] > quiet_anchor["motion_intensity"] + 0.2
    assert stopped_anchor["speaking_visual_active"] is False
    assert stopped_anchor["motion_intensity"] < quiet_anchor["motion_intensity"]
    assert stopped_anchor["smoothed_output_level"] == pytest.approx(0.0)
    assert stopped_anchor["visual_drive_level"] == pytest.approx(0.0)
    assert stopped_anchor["center_blob_drive"] == pytest.approx(0.0)


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
                "visual_drive_level": 0.74,
                "visual_drive_peak": 0.82,
                "center_blob_drive": 0.63,
                "outer_speaking_motion": 0.78,
                "visual_gain": 1.85,
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
    assert speaking["visual_drive_level"] == pytest.approx(0.74)
    assert speaking["center_blob_drive"] == pytest.approx(0.63)
    assert speaking["outer_speaking_motion"] == pytest.approx(0.78)
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
    assert synthetic["visual_drive_level"] > 0.0
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
            "visual_drive_level": 0.84,
            "visual_drive_peak": 0.91,
            "center_blob_drive": 0.77,
            "outer_speaking_motion": 0.86,
            "visual_gain": 1.85,
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
    assert payload["voice_visual_drive_level"] == pytest.approx(0.84)
    assert payload["voice_visual_drive_peak"] == pytest.approx(0.91)
    assert payload["voice_center_blob_drive"] == pytest.approx(0.77)
    assert payload["voice_outer_speaking_motion"] == pytest.approx(0.86)
    assert payload["voice_visual_gain"] == pytest.approx(1.85)
    assert payload["voice_anchor_debug"]["source"] == "playback_output_envelope"
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
                        "visual_drive_level": 0.79,
                        "visual_drive_peak": 0.86,
                        "center_blob_drive": 0.69,
                        "center_blob_scale_drive": 0.69,
                        "center_blob_scale": 1.2208,
                        "outer_speaking_motion": 0.82,
                        "visual_gain": 1.85,
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
        assert float(voice_core.property("visualDriveLevel")) == pytest.approx(0.79)
        assert float(voice_core.property("centerBlobDrive")) == pytest.approx(0.69)
        assert float(voice_core.property("centerBlobScaleDrive")) == pytest.approx(0.69)
        assert float(voice_core.property("centerBlobScale")) == pytest.approx(1.2208)
        assert float(voice_core.property("audioDriveLevel")) == pytest.approx(0.69)
        assert float(voice_core.property("audioReactiveLayerShare")) >= 0.6
        assert float(voice_core.property("speakingBaseMotion")) < 0.12
        assert voice_core.property("audioReactiveAvailable") is True
        assert voice_core.property("idleLoopMode") == "continuous_time"
        first_phase = float(voice_core.property("phase"))
        QtTest.QTest.qWait(120)
        app.processEvents()
        assert float(voice_core.property("phase")) > first_phase
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


def test_main_qml_audio_level_changes_speaking_motion_and_stop_damps() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene()
    try:
        voice_core = root.findChild(QtCore.QObject, "ghostVoiceCore")
        assert voice_core is not None

        def apply_anchor(level: float, drive: float, motion: float, *, active: bool = True) -> None:
            bridge.apply_snapshot(
                {
                    "status": _voice_status(
                        voice_anchor={
                            "state": "speaking" if active else "interrupted",
                            "state_label": "Speaking" if active else "Interrupted",
                            "speaking_visual_active": active,
                            "motion_intensity": motion,
                            "audio_reactive_available": active,
                            "audio_reactive_source": "playback_output_envelope"
                            if active
                            else "unavailable",
                            "output_level_rms": level,
                            "output_level_peak": min(1.0, level + 0.12),
                            "smoothed_output_level": level,
                            "speech_energy": level,
                            "visual_drive_level": drive,
                            "visual_drive_peak": min(1.0, drive + 0.1),
                            "center_blob_drive": drive,
                            "outer_speaking_motion": max(0.12, drive),
                            "visual_gain": 1.85,
                            "visualizer_update_hz": 30,
                            "raw_audio_present": False,
                            "user_heard_claimed": False,
                        }
                    )
                }
            )
            app.processEvents()
            QtTest.QTest.qWait(80)
            app.processEvents()

        apply_anchor(0.08, 0.32, 0.46)
        quiet_amplitude = float(voice_core.property("displayAmplitude"))
        quiet_audio_level = float(voice_core.property("audioLevel"))
        quiet_drive_level = float(voice_core.property("audioDriveLevel"))

        apply_anchor(0.86, 0.92, 0.92)
        loud_amplitude = float(voice_core.property("displayAmplitude"))
        loud_audio_level = float(voice_core.property("audioLevel"))
        loud_drive_level = float(voice_core.property("audioDriveLevel"))

        apply_anchor(0.0, 0.0, 0.06, active=False)
        stopped_amplitude = float(voice_core.property("displayAmplitude"))

        assert quiet_audio_level == pytest.approx(0.08)
        assert quiet_drive_level == pytest.approx(0.32)
        assert loud_audio_level == pytest.approx(0.86)
        assert loud_drive_level == pytest.approx(0.92)
        assert loud_amplitude > quiet_amplitude + 0.14
        assert voice_core.property("speakingActive") is False
        assert float(voice_core.property("audioLevel")) == pytest.approx(0.0)
        assert float(voice_core.property("audioDriveLevel")) == pytest.approx(0.0)
        assert stopped_amplitude < quiet_amplitude
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


def test_main_qml_center_blob_has_no_major_preset_speaking_motion_when_audio_zero() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene()
    try:
        voice_core = root.findChild(QtCore.QObject, "ghostVoiceCore")
        assert voice_core is not None
        bridge.apply_snapshot(
            {
                "status": _voice_status(
                    voice_anchor={
                        "state": "speaking",
                        "state_label": "Speaking",
                        "speaking_visual_active": True,
                        "motion_intensity": 0.95,
                        "audio_reactive_available": True,
                        "audio_reactive_source": "playback_output_envelope",
                        "output_level_rms": 0.0,
                        "output_level_peak": 0.0,
                        "smoothed_output_level": 0.0,
                        "speech_energy": 0.0,
                        "visual_drive_level": 0.0,
                        "visual_drive_peak": 0.0,
                        "center_blob_drive": 0.0,
                        "outer_speaking_motion": 0.16,
                        "visual_gain": 1.85,
                        "visualizer_update_hz": 30,
                        "raw_audio_present": False,
                        "user_heard_claimed": False,
                    }
                )
            }
        )
        app.processEvents()
        QtTest.QTest.qWait(120)
        app.processEvents()

        assert voice_core.property("speakingActive") is True
        assert float(voice_core.property("audioDriveLevel")) == pytest.approx(0.0)
        assert float(voice_core.property("centerBlobDriveLevel")) == pytest.approx(0.0)
        assert float(voice_core.property("centerBlobScale")) == pytest.approx(1.0, abs=0.015)
        assert float(voice_core.property("centerBlobLift")) == pytest.approx(0.0, abs=0.015)
        assert float(voice_core.property("centerBlobWobble")) <= 0.015
        assert float(voice_core.property("outerRingCarrierAmplitude")) > 0.0
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


def test_main_qml_force_audio_drive_controls_center_blob_visualizer_sequence() -> None:
    app, _, bridge, engine, root = _load_main_qml_scene()
    try:
        voice_core = root.findChild(QtCore.QObject, "ghostVoiceCore")
        assert voice_core is not None
        bridge.apply_snapshot(
            {
                "status": _voice_status(
                    voice_anchor={
                        "state": "speaking",
                        "state_label": "Speaking",
                        "speaking_visual_active": True,
                        "motion_intensity": 0.5,
                        "audio_reactive_available": True,
                        "audio_reactive_source": "playback_output_envelope",
                        "output_level_rms": 0.0,
                        "output_level_peak": 0.0,
                        "smoothed_output_level": 0.0,
                        "speech_energy": 0.0,
                        "visual_drive_level": 0.0,
                        "visual_drive_peak": 0.0,
                        "center_blob_drive": 0.0,
                        "outer_speaking_motion": 0.12,
                        "visual_gain": 1.85,
                        "visualizer_update_hz": 30,
                        "raw_audio_present": False,
                        "user_heard_claimed": False,
                    }
                )
            }
        )
        app.processEvents()

        levels = [0.0, 0.2, 0.8, 0.1, 1.0, 0.0]
        scales: list[float] = []
        lifts: list[float] = []
        glows: list[float] = []
        wobbles: list[float] = []
        for level in levels:
            assert voice_core.setProperty("forceAudioDriveLevel", level)
            app.processEvents()
            QtTest.QTest.qWait(40)
            app.processEvents()
            scales.append(float(voice_core.property("centerBlobScale")))
            lifts.append(float(voice_core.property("centerBlobLift")))
            glows.append(float(voice_core.property("centerBlobGlow")))
            wobbles.append(float(voice_core.property("centerBlobWobble")))

        assert scales[0] == pytest.approx(1.0, abs=0.015)
        assert scales[1] > scales[0] + 0.05
        assert scales[2] > scales[1] + 0.15
        assert scales[3] < scales[2] - 0.18
        assert scales[4] > scales[2] + 0.05
        assert scales[5] == pytest.approx(1.0, abs=0.015)
        assert glows[4] > glows[0] + 0.3
        assert all(abs(lift) <= 0.001 for lift in lifts)
        assert all(abs(wobble) <= 0.001 for wobble in wobbles)
    finally:
        _dispose_qt_objects(app, root, engine, bridge)


def test_ui_bridge_forwards_nested_stream_visual_drive_updates(temp_config) -> None:
    from stormhelm.ui.bridge import UiBridge

    bridge = UiBridge(temp_config)
    bridge.apply_stream_event(
        {
            "cursor": 225,
            "event_type": "voice.tts_stream_chunk",
            "visibility_scope": "watch_surface",
            "severity": "info",
            "message": "Voice chunk envelope updated.",
            "payload": {
                "metadata": {
                    "voice": {
                        "enabled": True,
                        "voice_output_envelope": {
                            "source": "playback_output_envelope",
                            "rms_level": 0.18,
                            "peak_level": 0.42,
                            "smoothed_level": 0.36,
                            "speech_energy": 0.4,
                            "visual_drive_level": 0.58,
                            "visual_drive_peak": 0.68,
                            "center_blob_drive": 0.49,
                            "center_blob_scale_drive": 0.49,
                            "center_blob_scale": 1.1568,
                            "outer_speaking_motion": 0.61,
                            "visual_gain": 1.85,
                            "raw_audio_present": False,
                        },
                        "playback": {
                            "active_playback_status": "playing",
                            "live_playback_status": "playing",
                            "first_audio_started": True,
                        },
                    }
                }
            },
        }
    )

    assert bridge.voiceState["voice_anchor_state"] == "speaking"
    assert bridge.voiceState["voice_smoothed_output_level"] == pytest.approx(0.36)
    assert bridge.voiceState["voice_visual_drive_level"] == pytest.approx(0.58)
    assert bridge.voiceState["voice_visual_drive_peak"] == pytest.approx(0.68)
    assert bridge.voiceState["voice_center_blob_drive"] == pytest.approx(0.49)
    assert bridge.voiceState["voice_center_blob_scale_drive"] == pytest.approx(0.49)
    assert bridge.voiceState["voice_center_blob_scale"] == pytest.approx(1.1568)
    assert bridge.voiceState["voice_outer_speaking_motion"] == pytest.approx(0.61)


def test_envelope_probe_report_serializes_safely(tmp_path) -> None:
    from scripts.voice_anchor_reactivity_probe import write_probe_report

    samples = [
        {
            "elapsed_ms": 0.0,
            "voice_anchor_state": "speaking",
            "speaking_visual_active": True,
            "voice_motion_intensity": 0.12,
            "voice_audio_level": 0.0,
            "voice_smoothed_output_level": 0.0,
            "voice_visual_drive_level": 0.03,
            "voice_visual_drive_peak": 0.05,
            "voice_center_blob_drive": 0.02,
            "voice_center_blob_scale_drive": 0.02,
            "voice_center_blob_scale": 1.0064,
            "voice_outer_speaking_motion": 0.12,
            "voice_audio_reactive_available": True,
            "voice_audio_reactive_source": "playback_output_envelope",
            "streaming_tts_active": True,
            "live_playback_active": True,
            "first_audio_started": True,
            "active_playback_status": "playing",
            "audioDriveLevel": 0.34,
            "voice_visualizer_envelope_frames_generated": 10,
            "voice_visualizer_envelope_frames_published": 10,
            "voice_visualizer_queue_depth": 1,
            "voice_visualizer_frame_worker_active": True,
            "ui_bridge_update_count": 1,
        },
        {
            "elapsed_ms": 90.0,
            "voice_anchor_state": "speaking",
            "speaking_visual_active": True,
            "voice_motion_intensity": 0.88,
            "voice_audio_level": 0.28,
            "voice_smoothed_output_level": 0.56,
            "voice_visual_drive_level": 0.86,
            "voice_visual_drive_peak": 0.93,
            "voice_center_blob_drive": 0.8,
            "voice_center_blob_scale_drive": 0.8,
            "voice_center_blob_scale": 1.256,
            "voice_outer_speaking_motion": 0.86,
            "voice_audio_reactive_available": True,
            "voice_audio_reactive_source": "playback_output_envelope",
            "streaming_tts_active": True,
            "live_playback_active": True,
            "first_audio_started": True,
            "active_playback_status": "playing",
            "audioDriveLevel": 0.86,
            "voice_visualizer_envelope_frames_generated": 12,
            "voice_visualizer_envelope_frames_published": 12,
            "voice_visualizer_queue_depth": 0,
            "voice_visualizer_frame_worker_active": False,
            "ui_bridge_update_count": 2,
        },
    ]

    summary = write_probe_report(
        output_dir=tmp_path,
        prompt="Say bearing acquired.",
        samples=samples,
        poll_errors=[],
        trigger_result=None,
    )

    summary_payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    samples_payload = (tmp_path / "samples.jsonl").read_text(encoding="utf-8")
    markdown = (tmp_path / "summary.md").read_text(encoding="utf-8")

    assert summary_payload["sample_count"] == 2
    assert summary_payload["speaking_sample_count"] == 2
    assert summary_payload["envelope_frames_produced"] == 2
    assert summary_payload["envelope_frames_published"] == 2
    assert summary_payload["ui_updates_delivered"] == 2
    assert summary_payload["backend_envelope_frames_generated_total"] == 12
    assert summary_payload["backend_envelope_frames_published_total"] == 12
    assert summary_payload["source"] == "playback_output_envelope"
    assert summary_payload["visual_drive"]["max"] == pytest.approx(0.86)
    assert summary_payload["center_blob_drive"]["max"] == pytest.approx(0.8)
    assert summary_payload["center_blob_scale_drive"]["max"] == pytest.approx(0.8)
    assert summary_payload["center_blob_scale"]["max"] == pytest.approx(1.256)
    assert summary_payload["center_blob_drive_fell_near_neutral"] is True
    assert summary_payload["center_blob_drive_rose_for_louder_speech"] is True
    assert summary_payload["visual_drive_fell_near_neutral"] is True
    assert summary_payload["visual_drive_rose_for_louder_speech"] is True
    assert summary_payload["raw_audio_logged"] is False
    assert summary_payload["raw_audio_included"] is False
    assert summary["classification"] == []
    assert "raw_audio_bytes" not in samples_payload
    assert "audio_bytes" not in samples_payload
    assert "data': b" not in samples_payload
    assert "Envelope frames produced: 2" in markdown
    assert "UI updates delivered: 2" in markdown
    assert "Center drive fell near neutral: True" in markdown
    assert "Center drive rose for louder speech: True" in markdown
    assert "playback_output_envelope" in markdown
