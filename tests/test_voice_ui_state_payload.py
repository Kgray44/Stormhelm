from __future__ import annotations

from stormhelm.ui.bridge import UiBridge
from stormhelm.ui.voice_surface import build_voice_ui_state


def _voice_status(**overrides):
    base = {
        "enabled": True,
        "mode": "push_to_talk",
        "state": {"state": "dormant"},
        "availability": {
            "available": True,
            "provider_name": "openai",
            "mock_provider_active": False,
            "unavailable_reason": None,
        },
        "openai": {"enabled": True},
        "provider": {"name": "openai"},
        "capture": {
            "enabled": True,
            "available": True,
            "provider": "mock",
            "mode": "push_to_talk",
            "device": "test-mic",
            "active_capture_id": None,
            "active_capture_status": None,
            "active_capture_started_at": None,
            "last_capture_id": None,
            "last_capture_status": None,
            "last_capture_duration_ms": None,
            "last_capture_size_bytes": None,
            "last_capture_error": {"code": None, "message": None},
            "last_capture_cleanup_warning": None,
            "last_capture_audio_input_metadata": None,
            "mock_provider_active": True,
            "no_wake_word": True,
            "no_vad": True,
            "no_realtime": True,
            "no_continuous_loop": True,
            "always_listening": False,
        },
        "stt": {
            "enabled": True,
            "provider": "mock",
            "model": "mock-stt",
            "last_transcription_id": None,
            "last_transcription_state": None,
            "last_transcript_preview": None,
        },
        "manual_turns": {
            "last_core_result_state": None,
            "last_route_family": None,
            "last_subsystem": None,
            "last_trust_posture": None,
            "last_verification_posture": None,
            "last_spoken_response_candidate": None,
        },
        "tts": {
            "enabled": True,
            "spoken_responses_enabled": True,
            "last_synthesis_state": None,
            "last_spoken_text_preview": None,
        },
        "playback": {
            "enabled": False,
            "available": False,
            "last_playback_status": None,
        },
        "runtime_truth": {
            "no_wake_word": True,
            "no_vad": True,
            "no_realtime": True,
            "no_continuous_loop": True,
            "always_listening": False,
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return {"voice": base}


def test_voice_ui_state_payload_exposes_active_push_to_talk_capture() -> None:
    status = _voice_status(
        capture={
            "active_capture_id": "capture-1",
            "active_capture_status": "recording",
            "active_capture_started_at": "2026-04-26T12:00:00Z",
        }
    )

    payload = build_voice_ui_state(status)

    assert payload["voice_available"] is True
    assert payload["voice_core_state"] == "listening"
    assert payload["capture_enabled"] is True
    assert payload["capture_available"] is True
    assert payload["capture_provider_kind"] == "mock"
    assert payload["capture_mode"] == "push_to_talk"
    assert payload["active_capture_id"] == "capture-1"
    assert payload["active_capture_status"] == "recording"
    assert payload["ghost"]["primary_label"] == "Recording one utterance."
    assert payload["ghost"]["primary_action"] == "voice.stopPushToTalkCapture"
    assert payload["truth_flags"]["no_wake_word"] is True
    assert payload["truth_flags"]["no_vad"] is True
    assert payload["truth_flags"]["no_realtime"] is True
    assert payload["truth_flags"]["always_listening"] is False
    assert payload["truth_flags"]["microphone_capture_requires_explicit_start"] is True


def test_voice_ui_state_payload_bounds_text_and_excludes_raw_audio() -> None:
    long_transcript = "route this captured phrase " * 20
    status = _voice_status(
        stt={
            "last_transcription_id": "transcription-1",
            "last_transcription_state": "succeeded",
            "last_transcript_preview": long_transcript,
        },
        manual_turns={
            "last_core_result_state": "requires_confirmation",
            "last_route_family": "software_control",
            "last_subsystem": "software_control",
            "last_trust_posture": "confirmation_required",
            "last_verification_posture": "not_verified",
            "last_spoken_response_candidate": {
                "spoken_text": "I need confirmation before proceeding with that control request.",
                "audio_bytes": "secret bytes must not surface",
            },
        },
        capture={
            "last_capture_audio_input_metadata": {
                "input_id": "audio-1",
                "filename": "utterance.wav",
                "mime_type": "audio/wav",
                "size_bytes": 512,
                "data": "raw captured bytes",
                "bytes": "also raw",
            }
        },
    )

    payload = build_voice_ui_state(status)

    assert payload["last_transcription_id"] == "transcription-1"
    assert len(payload["last_transcript_preview"]) <= 96
    assert payload["last_core_result_state"] == "requires_confirmation"
    assert payload["last_route_family"] == "software_control"
    assert (
        payload["last_spoken_response_preview"]
        == "I need confirmation before proceeding with that control request."
    )
    assert "audio_bytes" not in str(payload)
    assert "raw captured bytes" not in str(payload)
    assert "also raw" not in str(payload)


def test_voice_ui_state_payload_clears_active_capture_when_backend_reports_stop() -> (
    None
):
    status = _voice_status(
        capture={
            "active_capture_id": None,
            "active_capture_status": None,
            "last_capture_id": "capture-1",
            "last_capture_status": "completed",
            "last_capture_duration_ms": 1400,
            "last_capture_size_bytes": 12000,
        },
        stt={
            "last_transcription_state": "succeeded",
            "last_transcript_preview": "Open downloads.",
        },
        manual_turns={
            "last_core_result_state": "completed",
            "last_route_family": "software_control",
        },
    )

    payload = build_voice_ui_state(status)

    assert payload["voice_core_state"] == "idle"
    assert payload["active_capture_id"] is None
    assert payload["last_capture_status"] == "completed"
    assert payload["ghost"]["primary_label"] == "Capture stopped."
    capture_section = next(
        section
        for section in payload["deck"]["sections"]
        if section["title"] == "Capture"
    )
    assert capture_section["entries"][0]["primary"] == "Capture Provider"


def test_voice_ui_state_payload_uses_warning_for_disabled_or_unavailable_capture() -> (
    None
):
    disabled = build_voice_ui_state(
        _voice_status(
            capture={
                "enabled": False,
                "available": False,
                "unavailable_reason": "capture_disabled",
            }
        )
    )
    unavailable = build_voice_ui_state(
        _voice_status(
            availability={"available": False, "unavailable_reason": "openai_disabled"},
            openai={"enabled": False},
            capture={
                "enabled": True,
                "available": False,
                "unavailable_reason": "provider_unavailable",
            },
        )
    )

    assert disabled["voice_core_state"] == "warning"
    assert disabled["ghost"]["primary_label"] == "Capture disabled."
    assert unavailable["voice_core_state"] == "warning"
    assert unavailable["unavailable_reason"] == "openai_disabled"
    assert unavailable["ghost"]["primary_label"] == "Voice unavailable."


def test_voice_ui_state_payload_includes_readiness_and_stage_summary() -> None:
    status = _voice_status(
        readiness={
            "overall_status": "degraded",
            "user_facing_reason": "Playback is unavailable, but response audio can be prepared.",
            "blocking_reasons": ["playback_disabled"],
            "warnings": ["mock_provider_active"],
            "next_setup_action": "Enable playback only if local output is intended.",
        },
        stt={
            "last_transcription_id": "transcription-1",
            "last_transcription_state": "transcribing",
            "last_transcript_preview": "route the captured phrase through core",
        },
        manual_turns={
            "last_core_result_state": None,
            "last_route_family": None,
            "last_subsystem": None,
        },
    )

    payload = build_voice_ui_state(status)

    assert payload["readiness"]["overall_status"] == "degraded"
    assert payload["readiness"]["blocking_reasons"] == ["playback_disabled"]
    assert payload["pipeline_summary"]["stage"] == "transcribing"
    assert payload["pipeline_summary"]["last_successful_stage"] == "capture"
    assert (
        payload["pipeline_summary"]["transcript_preview"]
        == "route the captured phrase through core"
    )
    assert any(
        section["title"] == "Readiness" for section in payload["deck"]["sections"]
    )
    assert any(section["title"] == "Stages" for section in payload["deck"]["sections"])


def test_voice_ui_state_payload_exposes_bounded_playback_envelope_samples() -> None:
    samples = [
        {
            "playback_id": "playback-envelope-bridge",
            "sample_time_ms": index * 16,
            "monotonic_time_ms": 900_000 + index * 16,
            "rms": 0.12 + index * 0.01,
            "peak": 0.24 + index * 0.01,
            "energy": 0.18 + index * 0.02,
            "smoothed_energy": 0.20 + index * 0.02,
            "sample_rate": 24000,
            "channels": 1,
            "source": "pcm_playback",
            "valid": True,
        }
        for index in range(12)
    ]
    playback_envelope = {
        "playback_id": "playback-envelope-bridge",
        "envelope_supported": True,
        "envelope_available": True,
        "envelope_source": "playback_pcm",
        "envelope_sample_rate_hz": 60,
        "latest_voice_energy": 0.62,
        "latest_voice_energy_time_ms": 176,
        "estimated_output_latency_ms": 80,
        "envelope_visual_offset_ms": 0,
        "playback_visual_time_ms": 176,
        "playback_envelope_time_offset_applied_ms": -80,
        "envelope_sync_calibration_version": "Voice-L0.5",
        "playback_envelope_window_mode": "playback_time",
        "playback_envelope_query_time_ms": 176,
        "envelope_samples_recent": samples,
        "samples_dropped": 4,
        "raw_audio_present": False,
    }
    status = _voice_status(
        playback={
            "enabled": True,
            "available": True,
            "active_playback_status": "playing",
            "playback_streaming_active": True,
            "playback_envelope": playback_envelope,
        },
        voice_output_envelope={
            "source": "streaming_chunk_envelope",
            "smoothed_level": 0.08,
            "speech_energy": 0.08,
            "center_blob_scale_drive": 0.08,
            "audio_reactive_available": True,
            "raw_audio_present": False,
        },
    )

    payload = build_voice_ui_state(status)

    assert payload["speaking_visual_active"] is True
    assert payload["playback_envelope_available"] is True
    assert payload["playback_envelope_supported"] is True
    assert payload["playback_envelope_source"] == "playback_pcm"
    assert payload["playback_envelope_energy"] == 0.62
    assert payload["playback_envelope_sample_rate_hz"] == 60
    assert payload["playback_envelope_latency_ms"] == 80
    assert payload["estimated_output_latency_ms"] == 80
    assert payload["envelope_visual_offset_ms"] == 0
    assert payload["playback_visual_time_ms"] == 176
    assert payload["playback_envelope_time_offset_applied_ms"] == -80
    assert payload["envelope_sync_calibration_version"] == "Voice-L0.5"
    assert len(payload["playback_envelope_samples_recent"]) <= 8
    assert payload["voice_audio_reactive_source"] == "playback_pcm"
    assert payload["voice_anchor"]["speaking_visual_sync_mode"] == "playback_envelope"
    assert payload["voice_anchor"]["anchor_uses_playback_envelope"] is True
    assert payload["voice_anchor"]["playback_envelope_available"] is True
    assert payload["voice_anchor"]["estimated_output_latency_ms"] == 80
    assert payload["voice_anchor"]["envelope_visual_offset_ms"] == 0
    assert payload["voice_anchor"]["playback_visual_time_ms"] == 176
    assert payload["voice_anchor"]["playback_envelope_time_offset_applied_ms"] == -80
    assert payload["voice_anchor"]["envelope_interpolation_active"] is True
    assert payload["voice_anchor"]["procedural_fallback_active"] is False
    serialized = str(payload)
    assert "raw_audio_bytes" not in serialized
    assert "data': b" not in serialized
    assert "Always listening" not in str(payload)
    assert "Wake ready" not in str(payload)
    assert "Realtime active" not in str(payload)


def test_voice_ui_state_payload_exposes_pcm_stream_meter_as_scalar_truth() -> None:
    status = _voice_status(
        playback={
            "enabled": True,
            "available": True,
            "active_playback_status": "playing",
            "active_playback_id": "meter-playback-1",
            "playback_streaming_active": True,
        },
        voice_visual_active=True,
        voice_visual_available=True,
        voice_visual_energy=0.44,
        voice_visual_source="pcm_stream_meter",
        voice_visual_energy_source="pcm_stream_meter",
        voice_visual_playback_id="meter-playback-1",
        voice_visual_sample_rate_hz=60,
        voice_visual_started_at_ms=123456,
        voice_visual_latest_age_ms=12,
        raw_audio_present=False,
    )

    payload = build_voice_ui_state(status)

    assert payload["speaking_visual_active"] is True
    assert payload["voice_visual_active"] is True
    assert payload["voice_visual_available"] is True
    assert payload["voice_visual_energy"] == 0.44
    assert payload["voice_visual_source"] == "pcm_stream_meter"
    assert payload["voice_visual_energy_source"] == "pcm_stream_meter"
    assert payload["voice_visual_playback_id"] == "meter-playback-1"
    assert payload["voice_visual_sample_rate_hz"] == 60
    assert payload["voice_visual_latest_age_ms"] == 12
    assert payload["voice_audio_reactive_source"] == "pcm_stream_meter"
    assert payload["playback_envelope_samples_recent"] == []
    assert payload["envelopeTimelineSamples"] == []
    assert payload["voice_anchor"]["anchor_uses_playback_envelope"] is False
    assert payload["voice_anchor"]["speaking_visual_sync_mode"] == "pcm_stream_meter"
    assert payload["voice_anchor"]["visualizerSourceStrategy"] == "pcm_stream_meter"
    assert payload["voice_anchor"]["raw_audio_present"] is False
    serialized = str(payload)
    assert "raw_audio_bytes" not in serialized
    assert "data': b" not in serialized


def test_bridge_voice_visual_hot_path_uses_lightweight_scalar_channel(temp_config) -> None:
    bridge = UiBridge(temp_config)
    full_voice_updates: list[bool] = []
    visual_updates: list[dict] = []
    collection_updates: list[bool] = []
    bridge.voiceStateChanged.connect(lambda: full_voice_updates.append(True))
    bridge.voiceVisualStateChanged.connect(lambda: visual_updates.append(bridge.voiceVisualState))
    bridge.collectionsChanged.connect(lambda: collection_updates.append(True))
    initial_voice_state = bridge.voiceState

    bridge.apply_stream_event(
        {
            "cursor": 91_001,
            "event_type": "voice.visualizer_update",
            "visibility_scope": "internal_only",
            "payload": {
                "metadata": {"visualizer_only": True},
                "voice": {
                    "voice_visual_active": True,
                    "voice_visual_available": True,
                    "voice_visual_energy": 0.73,
                    "voice_visual_source": "pcm_stream_meter",
                    "voice_visual_playback_id": "bridge-ar2",
                    "active_playback_status": "playing",
                    "speaking_visual_active": True,
                    "payload_time_ms": 1234.0,
                    "raw_audio_present": False,
                },
            },
        }
    )

    assert full_voice_updates == []
    assert collection_updates == []
    assert bridge.voiceState == initial_voice_state
    assert visual_updates
    assert {
        "playback_id",
        "voice_visual_active",
        "voice_visual_energy",
        "voice_visual_source",
        "voice_visual_sequence",
        "authoritativeVoiceStateVersion",
        "authoritativeVoiceVisualActive",
        "authoritativeVoiceVisualEnergy",
        "authoritativePlaybackId",
        "authoritativePlaybackStatus",
        "activePlaybackId",
        "activePlaybackStatus",
        "raw_audio_present",
    } <= set(visual_updates[-1])
    assert visual_updates[-1]["playback_id"] == "bridge-ar2"
    assert visual_updates[-1]["voice_visual_energy"] == 0.73
    assert visual_updates[-1]["voice_visual_source"] == "pcm_stream_meter"
    assert visual_updates[-1]["voice_visual_active"] is True
    assert visual_updates[-1]["authoritativeVoiceStateVersion"] == "AR6"
    assert visual_updates[-1]["authoritativeVoiceVisualActive"] is True
    assert visual_updates[-1]["authoritativeVoiceVisualEnergy"] == 0.73
    assert visual_updates[-1]["activePlaybackStatus"] == "playing"
    assert visual_updates[-1]["raw_audio_present"] is False

    bridge.apply_stream_event(
        {
            "cursor": 91_002,
            "event_type": "voice.visualizer_update",
            "visibility_scope": "internal_only",
            "payload": {
                "metadata": {"visualizer_only": True},
                "voice": {
                    "voice_visual_active": False,
                    "voice_visual_energy": 0.0,
                    "voice_visual_playback_id": "bridge-ar2",
                    "payload_time_ms": 1267.0,
                    "raw_audio_present": False,
                },
            },
        }
    )

    latest_visual = bridge.voiceVisualState
    assert latest_visual["voice_visual_active"] is True
    assert latest_visual["voice_visual_energy"] == 0.0
    assert latest_visual["voice_visual_source"] == "pcm_stream_meter"
    assert latest_visual["playback_id"] == "bridge-ar2"
    assert latest_visual["speaking_visual_active"] is True
    assert full_voice_updates == []
    assert collection_updates == []


def test_bridge_voice_visual_active_does_not_flicker_false_while_playback_active(
    temp_config,
) -> None:
    bridge = UiBridge(temp_config)
    bridge._voice_visual_state = {
        "playback_id": "bridge-ar3-live",
        "voice_visual_active": True,
        "voice_visual_energy": 0.38,
        "voice_visual_source": "pcm_stream_meter",
        "raw_audio_present": False,
    }

    next_visual = bridge._extract_voice_visual_state(
        {
            "voice_visual_active": False,
            "voice_visual_energy": 0.0,
            "voice_visual_source": "pcm_stream_meter",
            "voice_visual_playback_id": "bridge-ar3-live",
            "active_playback_status": "playing",
            "raw_audio_present": False,
        }
    )

    assert next_visual["voice_visual_active"] is True
    assert next_visual["voice_visual_energy"] == 0.0
    assert next_visual["voice_visual_source"] == "pcm_stream_meter"
    assert next_visual["playback_id"] == "bridge-ar3-live"
    assert next_visual["raw_audio_present"] is False


def test_bridge_authority_ignores_broad_snapshot_that_clears_hot_path(
    temp_config,
) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_stream_event(
        {
            "cursor": 91_101,
            "event_type": "voice.visualizer_update",
            "payload": {
                "metadata": {"visualizer_only": True},
                "voice": {
                    "voice_visual_active": True,
                    "voice_visual_available": True,
                    "voice_visual_energy": 0.66,
                    "voice_visual_source": "pcm_stream_meter",
                    "voice_visual_playback_id": "bridge-ar6",
                    "active_playback_status": "playing",
                    "voice_visual_sequence": 12,
                    "raw_audio_present": False,
                },
            },
        }
    )

    bridge.apply_status(
        {
            "voice": {
                "enabled": True,
                "available": True,
                "availability": {"available": True},
                "playback": {
                    "active_playback_id": "bridge-ar6",
                    "active_playback_status": "playing",
                },
                "voice_visual_active": False,
                "voice_visual_available": True,
                "voice_visual_energy": 0.0,
                "voice_visual_source": "pcm_stream_meter",
                "voice_visual_playback_id": "bridge-ar6",
                "voice_visual_sequence": 11,
                "raw_audio_present": False,
            }
        }
    )

    visual = bridge.voiceVisualState
    state = bridge.voiceState
    assert visual["authoritativeVoiceStateVersion"] == "AR6"
    assert visual["voice_visual_active"] is True
    assert visual["voice_visual_energy"] == 0.66
    assert visual["staleBroadSnapshotIgnored"] is True
    assert visual["lastIgnoredUpdateSource"] == "broad_snapshot"
    assert state["authoritativeVoiceVisualActive"] is True
    assert state["voice_visual_active"] is True
    assert state["hotPathAcceptedCount"] == 1


def test_bridge_authority_accepts_matching_terminal_event(
    temp_config,
) -> None:
    bridge = UiBridge(temp_config)
    bridge.apply_stream_event(
        {
            "cursor": 91_201,
            "event_type": "voice.playback_started",
            "payload": {"playback_id": "bridge-ar6-terminal"},
        }
    )
    bridge.apply_stream_event(
        {
            "cursor": 91_202,
            "event_type": "voice.visualizer_update",
            "payload": {
                "metadata": {"visualizer_only": True},
                "voice": {
                    "voice_visual_active": True,
                    "voice_visual_energy": 0.44,
                    "voice_visual_source": "pcm_stream_meter",
                    "voice_visual_playback_id": "bridge-ar6-terminal",
                    "active_playback_status": "playing",
                    "raw_audio_present": False,
                },
            },
        }
    )

    bridge.apply_stream_event(
        {
            "cursor": 91_203,
            "event_type": "voice.playback_completed",
            "payload": {"playback_id": "bridge-ar6-terminal"},
        }
    )

    visual = bridge.voiceVisualState
    assert visual["authoritativeVoiceVisualActive"] is False
    assert visual["speaking_visual_active"] is False
    assert visual["authoritativePlaybackId"] == "bridge-ar6-terminal"
    assert visual["authoritativePlaybackStatus"] == "completed"
    assert visual["terminalEventAcceptedCount"] == 1
    assert visual["speakingExitedReason"] == "terminal_completed"


def test_voice_ui_state_payload_reports_visual_meter_unavailable_reason() -> None:
    payload = build_voice_ui_state(
        _voice_status(
            playback={
                "enabled": True,
                "available": True,
                "active_playback_status": "idle",
            },
            voice_visual_active=False,
            voice_visual_available=False,
            voice_visual_energy=0.0,
            voice_visual_source="pcm_stream_meter",
            voice_visual_disabled_reason="visual_meter_disabled",
            raw_audio_present=False,
        )
    )

    assert payload["voice_visual_active"] is False
    assert payload["voice_visual_available"] is False
    assert payload["voice_visual_energy"] == 0.0
    assert payload["voice_visual_source"] == "pcm_stream_meter"
    assert payload["voice_visual_disabled_reason"] == "visual_meter_disabled"
    assert payload["voice_anchor"]["voice_visual_disabled_reason"] == (
        "visual_meter_disabled"
    )


def test_voice_ui_state_payload_mirrors_authoritative_ar6_visual_status() -> None:
    payload = build_voice_ui_state(
        _voice_status(
            playback={
                "enabled": True,
                "available": True,
                "active_playback_id": "authoritative-playback-1",
                "active_playback_status": "playing",
            },
            voice_visual_active=False,
            voice_visual_available=True,
            voice_visual_energy=0.0,
            voice_visual_source="pcm_stream_meter",
            voice_visual_playback_id="authoritative-playback-1",
            authoritativeVoiceStateVersion="AR6",
            authoritativePlaybackId="authoritative-playback-1",
            authoritativePlaybackStatus="playing",
            authoritativeVoiceVisualActive=True,
            authoritativeVoiceVisualEnergy=0.71,
            authoritativeStateSource="hot_path",
            lastAcceptedUpdateSource="hot_path",
            staleBroadSnapshotIgnoredCount=3,
            terminalEventAcceptedCount=0,
            raw_audio_present=False,
        )
    )

    assert payload["authoritativeVoiceStateVersion"] == "AR6"
    assert payload["authoritativePlaybackId"] == "authoritative-playback-1"
    assert payload["authoritativePlaybackStatus"] == "playing"
    assert payload["authoritativeVoiceVisualActive"] is True
    assert payload["authoritativeVoiceVisualEnergy"] == 0.71
    assert payload["authoritativeStateSource"] == "hot_path"
    assert payload["lastAcceptedUpdateSource"] == "hot_path"
    assert payload["staleBroadSnapshotIgnoredCount"] == 3
    assert payload["terminalEventAcceptedCount"] == 0
    assert payload["voice_visual_active"] is True
    assert payload["voice_visual_energy"] == 0.71
    assert payload["voice_visual_playback_id"] == "authoritative-playback-1"
    assert payload["legacy_voice_visual_active"] is False
    assert payload["legacy_voice_visual_energy"] == 0.0
    assert "raw_audio_bytes" not in str(payload)
    assert payload["voice_anchor"]["raw_audio_present"] is False


def test_voice_ui_state_payload_treats_latest_tail_envelope_as_unusable() -> None:
    samples = [
        {
            "playback_id": "playback-tail-cache",
            "sample_time_ms": 7200 + index * 16,
            "monotonic_time_ms": 920_000 + index * 16,
            "rms": 0.02,
            "peak": 0.04,
            "energy": 0.012,
            "smoothed_energy": 0.011,
            "sample_rate": 24000,
            "channels": 1,
            "source": "pcm_playback",
            "valid": True,
        }
        for index in range(8)
    ]
    playback_envelope = {
        "playback_id": "playback-tail-cache",
        "envelope_supported": True,
        "envelope_available": True,
        "envelope_source": "playback_pcm",
        "envelope_sample_rate_hz": 60,
        "latest_voice_energy": 0.011,
        "latest_voice_energy_time_ms": 7233,
        "estimated_output_latency_ms": 80,
        "playback_envelope_window_mode": "latest",
        "playback_envelope_query_time_ms": None,
        "playback_envelope_sample_age_ms": 0,
        "envelope_samples_recent": samples,
        "raw_audio_present": False,
    }
    status = _voice_status(
        playback={
            "enabled": True,
            "available": True,
            "active_playback_status": "playing",
            "active_playback_id": "playback-tail-cache",
            "playback_streaming_active": True,
            "playback_envelope": playback_envelope,
        },
        voice_output_envelope={
            "source": "stormhelm_playback_meter",
            "smoothed_level": 0.12,
            "speech_energy": 0.12,
            "center_blob_scale_drive": 0.10,
            "audio_reactive_available": True,
            "raw_audio_present": False,
        },
    )

    payload = build_voice_ui_state(status)

    assert payload["speaking_visual_active"] is True
    assert payload["playback_envelope_available"] is True
    assert payload["playback_envelope_usable"] is False
    assert payload["playback_envelope_timebase_aligned"] is False
    assert payload["playback_envelope_usable_reason"] == "playback_envelope_unaligned"
    assert payload["voice_anchor"]["anchor_uses_playback_envelope"] is False
    assert payload["voice_anchor"]["procedural_fallback_active"] is True
    assert (
        payload["voice_anchor"]["speaking_visual_sync_mode"]
        == "procedural_fallback"
    )


def test_voice_ui_state_payload_keeps_playback_time_envelope_window_centered() -> None:
    samples = [
        {
            "playback_id": "playback-centered-window",
            "sample_time_ms": 300 + index * 16,
            "monotonic_time_ms": 930_000 + index * 16,
            "rms": 0.09,
            "peak": 0.18,
            "energy": 0.16 + index * 0.004,
            "smoothed_energy": 0.15 + index * 0.004,
            "sample_rate": 24000,
            "channels": 1,
            "source": "pcm_playback",
            "valid": True,
        }
        for index in range(12)
    ]
    playback_envelope = {
        "playback_id": "playback-centered-window",
        "envelope_supported": True,
        "envelope_available": True,
        "envelope_source": "playback_pcm",
        "envelope_sample_rate_hz": 60,
        "latest_voice_energy": 0.166,
        "latest_voice_energy_time_ms": 332,
        "estimated_output_latency_ms": 80,
        "playback_envelope_window_mode": "playback_time",
        "playback_envelope_query_time_ms": 332,
        "playback_envelope_sample_age_ms": 0,
        "envelope_samples_recent": samples,
        "raw_audio_present": False,
    }
    status = _voice_status(
        playback={
            "enabled": True,
            "available": True,
            "active_playback_status": "playing",
            "active_playback_id": "playback-centered-window",
            "playback_streaming_active": True,
            "playback_envelope": playback_envelope,
        },
        voice_output_envelope={
            "source": "stormhelm_playback_meter",
            "smoothed_level": 0.12,
            "speech_energy": 0.12,
            "audio_reactive_available": True,
            "raw_audio_present": False,
        },
    )

    payload = build_voice_ui_state(status)
    sample_times = [
        sample["sample_time_ms"]
        for sample in payload["playback_envelope_samples_recent"]
    ]

    assert payload["playback_envelope_usable"] is True
    assert payload["playback_envelope_timebase_aligned"] is True
    assert min(sample_times) <= 332 <= max(sample_times)
    assert payload["voice_anchor"]["anchor_uses_playback_envelope"] is True


def test_voice_ui_state_payload_exposes_calibrated_envelope_query_fields() -> None:
    samples = [
        {
            "playback_id": "playback-sync-calibrated",
            "sample_time_ms": 180 + index * 16,
            "monotonic_time_ms": 940_000 + index * 16,
            "rms": 0.12,
            "peak": 0.24,
            "energy": 0.18,
            "smoothed_energy": 0.20,
            "sample_rate": 24000,
            "channels": 1,
            "source": "pcm_playback",
            "valid": True,
        }
        for index in range(8)
    ]
    playback_envelope = {
        "playback_id": "playback-sync-calibrated",
        "envelope_supported": True,
        "envelope_available": True,
        "envelope_source": "playback_pcm",
        "envelope_sample_rate_hz": 60,
        "latest_voice_energy": 0.20,
        "latest_voice_energy_time_ms": 212,
        "estimated_output_latency_ms": 120,
        "envelope_visual_offset_ms": -40,
        "playback_visual_time_ms": 292,
        "playback_envelope_time_offset_applied_ms": -80,
        "playback_envelope_window_mode": "playback_time",
        "playback_envelope_query_time_ms": 212,
        "playback_envelope_sample_age_ms": 6,
        "envelope_samples_recent": samples,
        "raw_audio_present": False,
    }
    status = _voice_status(
        playback={
            "enabled": True,
            "available": True,
            "active_playback_status": "playing",
            "active_playback_id": "playback-sync-calibrated",
            "playback_streaming_active": True,
            "playback_envelope": playback_envelope,
        },
        voice_output_envelope={
            "source": "stormhelm_playback_meter",
            "smoothed_level": 0.12,
            "speech_energy": 0.12,
            "audio_reactive_available": True,
            "raw_audio_present": False,
        },
    )

    payload = build_voice_ui_state(status)

    assert payload["playback_visual_time_ms"] == 292
    assert payload["playback_envelope_query_time_ms"] == 212
    assert payload["estimated_output_latency_ms"] == 120
    assert payload["envelope_visual_offset_ms"] == -40
    assert payload["playback_envelope_time_offset_applied_ms"] == -80
    assert payload["voice_anchor"]["playback_envelope_usable"] is True
    assert payload["voice_anchor"]["playback_envelope_timebase_aligned"] is True


def test_voice_ui_state_payload_exposes_locked_envelope_timeline_strategy() -> None:
    timeline = [
        {"t_ms": index * 16, "energy": 0.16 + index * 0.025}
        for index in range(8)
    ]
    playback_envelope = {
        "playback_id": "timeline-strategy",
        "envelope_supported": True,
        "envelope_available": True,
        "envelope_source": "playback_pcm",
        "envelope_sample_rate_hz": 60,
        "latest_voice_energy": 0.28,
        "latest_voice_energy_time_ms": 64,
        "playback_envelope_window_mode": "playback_time",
        "playback_envelope_query_time_ms": 64,
        "playback_envelope_alignment_delta_ms": 0,
        "playback_envelope_alignment_tolerance_ms": 260,
        "playback_envelope_alignment_status": "aligned",
        "playback_envelope_sample_age_ms": 4,
        "envelope_samples_recent": [
            {
                "sample_time_ms": sample["t_ms"],
                "energy": sample["energy"],
                "smoothed_energy": sample["energy"],
                "source": "pcm_playback",
                "valid": True,
            }
            for sample in timeline
        ],
        "envelope_timeline_samples": timeline,
        "envelope_timeline_available": True,
        "envelope_timeline_sample_rate_hz": 60,
        "visualizer_source_strategy": "playback_envelope_timeline",
        "visualizer_source_locked": True,
        "visualizer_source_playback_id": "timeline-strategy",
        "visualizer_source_switch_count": 0,
        "visualizer_source_switching_disabled": True,
        "envelope_timeline_ready_at_playback_start": True,
        "requested_anchor_visualizer_mode": "envelope_timeline",
        "effective_anchor_visualizer_mode": "envelope_timeline",
        "forced_visualizer_mode_honored": True,
        "visualizer_strategy_selected_by": "config",
        "raw_audio_present": False,
    }
    payload = build_voice_ui_state(
        _voice_status(
            playback={
                "enabled": True,
                "available": True,
                "active_playback_status": "playing",
                "active_playback_id": "timeline-strategy",
                "playback_streaming_active": True,
                "playback_envelope": playback_envelope,
            },
            voice_output_envelope={
                "source": "stormhelm_playback_meter",
                "smoothed_level": 0.12,
                "speech_energy": 0.12,
                "audio_reactive_available": True,
                "raw_audio_present": False,
            },
        )
    )

    assert payload["visualizerSourceStrategy"] == "playback_envelope_timeline"
    assert payload["visualizerSourceLocked"] is True
    assert payload["visualizerSourcePlaybackId"] == "timeline-strategy"
    assert payload["visualizerSourceSwitchCount"] == 0
    assert payload["visualizerSourceSwitchingDisabled"] is True
    assert payload["envelopeTimelineReadyAtPlaybackStart"] is True
    assert payload["playback_envelope_alignment_delta_ms"] == 0
    assert payload["playback_envelope_alignment_tolerance_ms"] == 260
    assert payload["playback_envelope_alignment_status"] == "aligned"
    assert payload["requestedAnchorVisualizerMode"] == "envelope_timeline"
    assert payload["effectiveAnchorVisualizerMode"] == "envelope_timeline"
    assert payload["forcedVisualizerModeHonored"] is True
    assert payload["visualizerStrategySelectedBy"] == "config"
    assert payload["envelope_timeline_available"] is True
    assert payload["envelopeTimelineSamples"] == [
        {"t_ms": sample["t_ms"], "energy": round(sample["energy"], 4)}
        for sample in timeline
    ]
    assert payload["voice_anchor"]["visualizerSourceStrategy"] == (
        "playback_envelope_timeline"
    )
    serialized = str(payload)
    assert "raw_audio_bytes" not in serialized
    assert "data': b" not in serialized


def test_voice_ui_state_payload_uses_timeline_samples_when_recent_samples_absent() -> None:
    timeline = [
        {"t_ms": 0, "energy": 0.10},
        {"t_ms": 16, "energy": 0.18},
        {"t_ms": 32, "energy": 0.24},
        {"t_ms": 48, "energy": 0.20},
        {"t_ms": 64, "energy": 0.30},
    ]
    playback_envelope = {
        "playback_id": "timeline-only-bridge",
        "envelope_supported": True,
        "envelope_available": True,
        "envelope_source": "playback_pcm",
        "envelope_sample_rate_hz": 60,
        "latest_voice_energy": 0.0,
        "latest_voice_energy_time_ms": 64,
        "playback_envelope_window_mode": "latest",
        "playback_envelope_query_time_ms": 64,
        "playback_envelope_sample_age_ms": 0,
        "envelope_samples_recent": [],
        "envelope_timeline_samples": timeline,
        "envelope_timeline_available": True,
        "visualizer_source_strategy": "playback_envelope_timeline",
        "visualizer_source_locked": True,
        "visualizer_source_playback_id": "timeline-only-bridge",
        "visualizer_source_switch_count": 0,
        "visualizer_source_switching_disabled": True,
        "requested_anchor_visualizer_mode": "envelope_timeline",
        "effective_anchor_visualizer_mode": "envelope_timeline",
        "forced_visualizer_mode_honored": True,
        "visualizer_strategy_selected_by": "config",
        "raw_audio_present": False,
    }

    payload = build_voice_ui_state(
        _voice_status(
            playback={
                "enabled": True,
                "available": True,
                "active_playback_status": "playing",
                "active_playback_id": "timeline-only-bridge",
                "playback_streaming_active": True,
                "playback_envelope": playback_envelope,
            },
            voice_output_envelope={
                "source": "stormhelm_playback_meter",
                "smoothed_level": 0.12,
                "speech_energy": 0.12,
                "audio_reactive_available": True,
                "raw_audio_present": False,
            },
        )
    )

    assert payload["playback_envelope_window_mode"] == "playback_time"
    assert payload["playback_envelope_alignment_status"] == "aligned"
    assert payload["playback_envelope_sample_count"] == len(timeline)
    assert payload["playback_envelope_usable"] is True
    assert payload["playback_envelope_energy"] > 0.0
    assert payload["voice_anchor"]["anchor_uses_playback_envelope"] is True
    assert payload["voice_anchor"]["envelope_interpolation_active"] is True


def test_voice_ui_state_payload_honors_forced_constant_visualizer_mode(
    monkeypatch,
) -> None:
    monkeypatch.setenv("STORMHELM_ANCHOR_VISUALIZER_MODE", "constant_test_wave")

    payload = build_voice_ui_state(
        _voice_status(
            playback={
                "enabled": True,
                "available": True,
                "active_playback_status": "playing",
                "active_playback_id": "forced-constant",
                "playback_streaming_active": True,
                "playback_envelope": {
                    "playback_id": "forced-constant",
                    "envelope_supported": True,
                    "envelope_available": True,
                    "envelope_source": "playback_pcm",
                    "latest_voice_energy": 0.0,
                    "playback_envelope_sample_count": 0,
                    "envelope_samples_recent": [],
                    "raw_audio_present": False,
                },
            },
            voice_output_envelope={
                "source": "stormhelm_playback_meter",
                "smoothed_level": 0.12,
                "speech_energy": 0.12,
                "audio_reactive_available": True,
                "raw_audio_present": False,
            },
        )
    )

    assert payload["visualizerSourceStrategy"] == "constant_test_wave"
    assert payload["requestedAnchorVisualizerMode"] == "constant_test_wave"
    assert payload["effectiveAnchorVisualizerMode"] == "constant_test_wave"
    assert payload["forcedVisualizerModeHonored"] is True
    assert payload["visualizerStrategySelectedBy"] == "config"


def test_voice_ui_state_payload_reports_cancelled_capture_without_stale_recording() -> (
    None
):
    payload = build_voice_ui_state(
        _voice_status(
            capture={
                "active_capture_id": None,
                "active_capture_status": None,
                "last_capture_id": "capture-1",
                "last_capture_status": "cancelled",
            }
        )
    )

    assert payload["pipeline_summary"]["stage"] == "cancelled"
    assert payload["ghost"]["primary_label"] == "Capture cancelled."
    assert payload["voice_core_state"] == "idle"
    assert "Recording one utterance." not in str(payload["ghost"])
