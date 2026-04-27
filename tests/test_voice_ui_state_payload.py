from __future__ import annotations

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
    assert "Always listening" not in str(payload)
    assert "Wake ready" not in str(payload)
    assert "Realtime active" not in str(payload)


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
