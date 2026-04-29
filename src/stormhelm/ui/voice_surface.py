from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stormhelm.core.voice.visualizer import build_voice_anchor_payload


_RAW_AUDIO_KEYS = {
    "audio_bytes",
    "bytes",
    "bytes_data",
    "data",
    "raw_audio",
    "raw_audio_bytes",
    "raw_bytes",
    "content",
    "payload",
}
_SECRET_KEYS = {
    "api_key",
    "authorization",
    "credential",
    "secret",
    "token",
}
_TRUTH_KEYS = {
    "no_wake_word": True,
    "no_vad": True,
    "no_realtime": True,
    "no_continuous_loop": True,
    "always_listening": False,
}
_WAKE_LOOP_CARD_STATUSES = {
    "listen_timeout",
    "capture_cancelled",
    "capture_failed",
    "transcription_failed",
    "empty_transcript",
    "core_clarification_required",
    "core_confirmation_required",
    "core_blocked",
    "core_failed",
    "tts_disabled",
    "tts_failed",
    "playback_unavailable",
    "playback_failed",
    "playback_stopped",
    "suppressed_or_muted",
}


def build_voice_ui_state(status: dict[str, Any] | None) -> dict[str, Any]:
    """Build the compact, safe voice state consumed by Ghost and the Deck."""

    voice = _voice_status(status)
    availability = _dict(voice.get("availability"))
    provider = _dict(voice.get("provider"))
    if not availability:
        availability = _dict(provider.get("availability"))
    openai = _dict(voice.get("openai"))
    capture = _dict(voice.get("capture"))
    wake = _dict(voice.get("wake"))
    post_wake = _dict(voice.get("post_wake_listen"))
    vad = _dict(voice.get("vad"))
    realtime = _dict(voice.get("realtime"))
    stt = _dict(voice.get("stt"))
    manual = _dict(voice.get("manual_turns"))
    tts = _dict(voice.get("tts"))
    playback = _dict(voice.get("playback"))
    interruption = _dict(voice.get("interruption"))
    confirmation = _dict(voice.get("spoken_confirmation"))
    runtime_truth = _dict(voice.get("runtime_truth"))
    readiness = _readiness_payload(_dict(voice.get("readiness")))
    runtime_mode = _runtime_mode_payload(
        _dict(voice.get("runtime_mode") or readiness.get("runtime_mode"))
    )
    wake_supervised_loop = _dict(voice.get("wake_supervised_loop"))

    voice_available = bool(availability.get("available", voice.get("available", False)))
    unavailable_reason = _text(
        availability.get("unavailable_reason") or voice.get("unavailable_reason")
    )
    voice_state = _text(
        _dict(voice.get("state")).get("state")
        or voice.get("voice_state")
        or voice.get("state")
    )
    capture_enabled = bool(capture.get("enabled", False))
    capture_available = bool(capture.get("available", False))
    active_capture_id = _text(capture.get("active_capture_id")) or None
    active_capture_status = _text(capture.get("active_capture_status")) or None
    capture_provider = _text(
        capture.get("provider")
        or provider.get("name")
        or availability.get("provider_name")
    )
    provider_kind = _provider_kind(capture_provider, capture)
    active_playback_id = _text(playback.get("active_playback_id")) or None
    active_playback_status = _text(playback.get("active_playback_status")) or None
    wake_ghost = _dict(voice.get("wake_ghost") or wake.get("ghost"))
    wake_ghost_active = bool(wake_ghost.get("active", False))
    current_phase = _current_phase(
        voice_available=voice_available,
        unavailable_reason=unavailable_reason,
        voice_state=voice_state,
        capture_enabled=capture_enabled,
        capture_available=capture_available,
        active_capture_status=active_capture_status or "",
        active_listen_window_status=_text(
            post_wake.get("active_listen_window_status")
        ),
        wake_ghost_active=wake_ghost_active,
        wake_ghost_status=_text(wake_ghost.get("status")),
        wake_loop_stage=_text(wake_supervised_loop.get("active_loop_stage")),
        stt_state=_text(stt.get("last_transcription_state")),
        core_state=_text(manual.get("last_core_result_state")),
        tts_state=_text(tts.get("last_synthesis_state")),
        playback_state=_text(
            active_playback_status or playback.get("last_playback_status")
        ),
    )
    core_state = _voice_core_state(current_phase)
    spoken_response = _dict(manual.get("last_spoken_response_candidate"))
    spoken_preview = _preview(
        spoken_response.get("spoken_text")
        or spoken_response.get("spokenText")
        or tts.get("last_spoken_text_preview")
        or manual.get("last_spoken_response_preview"),
        limit=96,
    )
    transcript_preview = _preview(
        stt.get("last_transcript_preview") or manual.get("last_transcript_preview"),
        limit=96,
    )
    pipeline_summary = _pipeline_summary(
        voice=voice,
        capture=capture,
        stt=stt,
        manual=manual,
        tts=tts,
        playback=playback,
        interruption=interruption,
        confirmation=confirmation,
        current_phase=current_phase,
        transcript_preview=transcript_preview,
        spoken_preview=spoken_preview,
    )
    audio_metadata = _sanitize(capture.get("last_capture_audio_input_metadata"))
    truth_flags = _truth_flags(capture, runtime_truth)
    truth_flags["no_cloud_wake_audio"] = bool(
        wake.get("no_cloud_wake_audio")
        if "no_cloud_wake_audio" in wake
        else runtime_truth.get("no_cloud_wake_audio", True)
    )
    truth_flags["openai_wake_detection"] = bool(
        wake.get("openai_wake_detection")
        if "openai_wake_detection" in wake
        else runtime_truth.get("openai_wake_detection", False)
    )
    truth_flags["cloud_wake_detection"] = bool(
        wake.get("cloud_wake_detection")
        if "cloud_wake_detection" in wake
        else runtime_truth.get("cloud_wake_detection", False)
    )
    truth_flags["wake_detection_is_not_command_authority"] = bool(
        runtime_truth.get("wake_detection_is_not_command_authority", True)
    )
    truth_flags["no_post_wake_capture"] = bool(
        wake_ghost.get("no_post_wake_capture", True)
    )
    truth_flags["no_command_from_wake"] = bool(
        wake_ghost.get("no_command_from_wake", True)
    )
    truth_flags["vad_semantic_completion_claimed"] = bool(
        vad.get("semantic_completion_claimed", False)
    )
    truth_flags["vad_command_authority"] = bool(vad.get("command_authority", False))
    truth_flags["realtime_vad"] = bool(vad.get("realtime_vad", False))
    truth_flags["speech_activity_is_not_intent"] = True
    truth_flags["wake_supervised_loop_one_bounded_request"] = bool(
        wake_supervised_loop.get("enabled", False)
    )
    truth_flags["listen_window_does_not_route_core"] = bool(
        post_wake.get(
            "listen_window_does_not_route_core",
            runtime_truth.get("listen_window_does_not_route_core", True),
        )
    )
    truth_flags["continuous_listening"] = bool(
        wake_supervised_loop.get(
            "continuous_listening",
            runtime_truth.get("continuous_listening", False),
        )
    )
    truth_flags["cloud_wake_detection"] = bool(
        wake_supervised_loop.get(
            "cloud_wake_detection", truth_flags.get("cloud_wake_detection", False)
        )
    )
    truth_flags["realtime_used"] = bool(
        wake_supervised_loop.get("realtime_used", False)
    )
    truth_flags["realtime_transcription_bridge_only"] = bool(
        realtime.get("mode") == "transcription_bridge"
        or runtime_truth.get("realtime_transcription_bridge_only", False)
    )
    truth_flags["speech_to_speech_enabled"] = bool(
        realtime.get("speech_to_speech_enabled", False)
    )
    truth_flags["realtime_speech_to_speech_core_bridge"] = bool(
        realtime.get("speech_to_speech_core_bridge", False)
        or runtime_truth.get("realtime_speech_to_speech_core_bridge", False)
    )
    truth_flags["direct_realtime_tools_allowed"] = bool(
        realtime.get("direct_tools_allowed", False)
    )
    truth_flags["command_authority"] = _text(
        wake_supervised_loop.get("command_authority")
        or realtime.get("command_authority")
        or runtime_truth.get("command_authority")
        or "stormhelm_core"
    )
    truth_flags["spoken_yes_is_not_global_permission"] = bool(
        runtime_truth.get("spoken_yes_is_not_global_permission", True)
    )
    truth_flags["spoken_confirmation_is_not_command_authority"] = bool(
        runtime_truth.get("spoken_confirmation_is_not_command_authority", True)
    )
    truth_flags["confirmation_accepted_does_not_mean_action_completed"] = bool(
        runtime_truth.get(
            "confirmation_accepted_does_not_mean_action_completed", True
        )
    )
    ghost = _ghost_payload(
        voice_available=voice_available,
        unavailable_reason=unavailable_reason,
        capture_enabled=capture_enabled,
        capture_available=capture_available,
        active_capture_id=active_capture_id,
        active_capture_status=active_capture_status,
        active_playback_id=active_playback_id,
        spoken_output_muted=bool(interruption.get("spoken_output_muted")),
        last_capture_status=_text(capture.get("last_capture_status")),
        current_phase=current_phase,
        transcript_preview=transcript_preview,
        spoken_preview=spoken_preview,
        wake_ghost=wake_ghost,
        post_wake=post_wake,
        wake_supervised_loop=wake_supervised_loop,
        confirmation=confirmation,
        realtime=realtime,
    )
    deck = _deck_payload(
        capture=capture,
        stt=stt,
        manual=manual,
        tts=tts,
        playback=playback,
        readiness=readiness,
        runtime_mode=runtime_mode,
        pipeline_summary=pipeline_summary,
        capture_provider=capture_provider,
        provider_kind=provider_kind,
        capture_available=capture_available,
        audio_metadata=audio_metadata,
        truth_flags=truth_flags,
        interruption=interruption,
        wake=wake,
        post_wake=post_wake,
        wake_supervised_loop=wake_supervised_loop,
        confirmation=confirmation,
        realtime=realtime,
    )
    voice_anchor = build_voice_anchor_payload(voice)
    anchor_truth_flags = {
        "user_heard_claimed": False,
        "playback_started_does_not_mean_user_heard": True,
        "speaking_visual_is_not_completion": True,
        "speaking_visual_is_not_verification": True,
    }

    return {
        "voice_available": voice_available,
        "voice_state": voice_state or ("dormant" if voice_available else "unavailable"),
        "voice_current_phase": current_phase,
        "voice_core_state": core_state,
        "voice_anchor": voice_anchor,
        "voice_anchor_state": voice_anchor.get("state", "idle"),
        "speaking_visual_active": bool(
            voice_anchor.get("speaking_visual_active", False)
        ),
        "voice_motion_intensity": voice_anchor.get("motion_intensity", 0.0),
        "voice_audio_level": voice_anchor.get("output_level_rms", 0.0),
        "voice_output_level_peak": voice_anchor.get("output_level_peak", 0.0),
        "voice_smoothed_output_level": voice_anchor.get("smoothed_output_level", 0.0),
        "voice_speech_energy": voice_anchor.get("speech_energy", 0.0),
        "voice_audio_reactive_available": bool(
            voice_anchor.get("audio_reactive_available", False)
        ),
        "voice_audio_reactive_source": voice_anchor.get(
            "audio_reactive_source", "unavailable"
        ),
        "voice_visualizer_update_hz": voice_anchor.get("visualizer_update_hz", 30),
        "voice_visualizer_last_update_at": voice_anchor.get(
            "visualizer_last_update_at"
        ),
        "voice_anchor_truth_flags": anchor_truth_flags,
        "provider_name": _text(
            availability.get("provider_name")
            or provider.get("name")
            or voice.get("provider_name")
        ),
        "provider_mock_active": bool(
            availability.get("mock_provider_active")
            or provider.get("mock_provider_active")
            or capture.get("mock_provider_active")
        ),
        "openai_enabled": bool(openai.get("enabled", False)),
        "unavailable_reason": unavailable_reason or None,
        "capture_enabled": capture_enabled,
        "capture_available": capture_available,
        "capture_provider": capture_provider,
        "capture_provider_kind": provider_kind,
        "capture_mode": _text(capture.get("mode") or "push_to_talk"),
        "capture_device": _text(capture.get("device")),
        "active_capture_id": active_capture_id,
        "active_capture_status": active_capture_status,
        "active_capture_started_at": _text(capture.get("active_capture_started_at"))
        or None,
        "active_capture_elapsed_ms": _elapsed_ms(
            capture.get("active_capture_started_at")
        ),
        "last_capture_id": _text(capture.get("last_capture_id")) or None,
        "last_capture_status": _text(capture.get("last_capture_status")) or None,
        "last_capture_duration_ms": capture.get("last_capture_duration_ms"),
        "last_capture_size_bytes": capture.get("last_capture_size_bytes"),
        "last_capture_error": _sanitize(capture.get("last_capture_error")),
        "last_capture_cleanup_warning": _text(
            capture.get("last_capture_cleanup_warning")
        )
        or None,
        "last_capture_audio_metadata": audio_metadata,
        "vad_enabled": bool(vad.get("enabled", False)),
        "vad_available": bool(vad.get("available", False)),
        "vad_provider": _text(vad.get("provider")) or None,
        "vad_provider_kind": _text(vad.get("provider_kind")) or None,
        "vad_active": bool(vad.get("active", False)),
        "active_vad_session_id": _text(vad.get("active_vad_session_id")) or None,
        "vad_active_capture_id": _text(vad.get("active_capture_id")) or None,
        "vad_active_listen_window_id": _text(vad.get("active_listen_window_id"))
        or None,
        "vad_last_activity_status": _text(
            vad.get("last_speech_activity_status")
            or _dict(vad.get("last_activity_event")).get("status")
        )
        or None,
        "vad_silence_ms": vad.get("silence_ms"),
        "vad_semantic_completion_claimed": bool(
            vad.get("semantic_completion_claimed", False)
        ),
        "vad_command_authority": bool(vad.get("command_authority", False)),
        "realtime_vad": bool(vad.get("realtime_vad", False)),
        "realtime_enabled": bool(realtime.get("enabled", False)),
        "realtime_available": bool(realtime.get("available", False)),
        "realtime_provider": _text(realtime.get("provider")) or None,
        "realtime_provider_kind": _text(realtime.get("provider_kind")) or None,
        "realtime_mode": _text(realtime.get("mode")) or None,
        "active_realtime_session_id": _text(
            realtime.get("active_realtime_session_id")
        )
        or None,
        "active_realtime_turn_id": _text(realtime.get("active_realtime_turn_id"))
        or None,
        "realtime_partial_transcript_preview": _preview(
            realtime.get("partial_transcript_preview"), limit=96
        ),
        "realtime_final_transcript_preview": _preview(
            realtime.get("final_transcript_preview"), limit=96
        ),
        "last_transcription_id": _text(stt.get("last_transcription_id")) or None,
        "last_transcription_status": _text(stt.get("last_transcription_state")) or None,
        "last_transcript_preview": transcript_preview,
        "last_core_result_state": _text(manual.get("last_core_result_state")) or None,
        "last_route_family": _text(manual.get("last_route_family")) or None,
        "last_subsystem": _text(manual.get("last_subsystem")) or None,
        "last_trust_posture": _text(manual.get("last_trust_posture")) or None,
        "last_verification_posture": _text(manual.get("last_verification_posture"))
        or None,
        "last_spoken_response_preview": spoken_preview,
        "last_synthesis_status": _text(tts.get("last_synthesis_state")) or None,
        "last_playback_status": _text(playback.get("last_playback_status")) or None,
        "voice_runtime_mode": runtime_mode.get("selected_mode"),
        "voice_effective_mode": runtime_mode.get("effective_mode"),
        "voice_runtime_readiness": runtime_mode,
        "live_playback_available": bool(runtime_mode.get("live_playback_available")),
        "artifact_persistence_enabled": bool(
            runtime_mode.get("artifact_persistence_enabled")
        ),
        "spoken_confirmation_enabled": bool(confirmation.get("enabled", False)),
        "pending_confirmation_count": int(
            confirmation.get("pending_confirmation_count") or 0
        ),
        "last_spoken_confirmation_status": _text(confirmation.get("last_status"))
        or None,
        "last_spoken_confirmation_intent": _text(
            _dict(confirmation.get("last_intent")).get("intent")
        )
        or None,
        "last_pending_confirmation_id": _text(
            confirmation.get("last_pending_confirmation_id")
        )
        or None,
        "spoken_confirmation_requires_pending_binding": bool(
            confirmation.get("confirmation_requires_pending_binding", True)
        ),
        "confirmation_accepted_does_not_execute_action": bool(
            confirmation.get("confirmation_accepted_does_not_execute_action", True)
        ),
        "wake_enabled": bool(wake.get("enabled", False)),
        "wake_available": bool(wake.get("available", False)),
        "wake_provider": _text(wake.get("provider")) or None,
        "wake_provider_kind": _text(wake.get("provider_kind")) or None,
        "wake_backend": _text(wake.get("wake_backend")) or None,
        "wake_device": _text(wake.get("device")) or None,
        "wake_dependency_available": wake.get("dependency_available"),
        "wake_device_available": wake.get("device_available"),
        "wake_permission_state": _text(wake.get("permission_state")) or None,
        "wake_monitoring_active": bool(wake.get("monitoring_active", False)),
        "last_wake_event": _sanitize(wake.get("last_wake_event")),
        "active_wake_session": _sanitize(wake.get("active_wake_session")),
        "wake_ghost_requested": bool(wake_ghost.get("requested", False)),
        "wake_ghost_active": wake_ghost_active,
        "wake_ghost_status": _text(wake_ghost.get("status")) or None,
        "wake_ghost_request_id": _text(wake_ghost.get("wake_ghost_request_id")) or None,
        "wake_event_id": _text(wake_ghost.get("wake_event_id")) or None,
        "wake_session_id": _text(wake_ghost.get("wake_session_id")) or None,
        "wake_phrase": _text(wake_ghost.get("wake_phrase")) or None,
        "wake_confidence": wake_ghost.get("wake_confidence"),
        "wake_status_label": _text(wake_ghost.get("wake_status_label")) or None,
        "wake_prompt_text": _text(wake_ghost.get("wake_prompt_text")) or None,
        "wake_expires_at": _text(wake_ghost.get("expires_at")) or None,
        "wake_timeout_ms": wake_ghost.get("wake_timeout_ms"),
        "capture_started": bool(wake_ghost.get("capture_started", False)),
        "stt_started": bool(wake_ghost.get("stt_started", False)),
        "core_routed": bool(wake_ghost.get("core_routed", False)),
        "no_post_wake_capture": bool(wake_ghost.get("no_post_wake_capture", True)),
        "no_vad": bool(wake_ghost.get("no_vad", True)),
        "no_realtime": bool(wake_ghost.get("no_realtime", True)),
        "no_command_from_wake": bool(wake_ghost.get("no_command_from_wake", True)),
        "post_wake_listen_enabled": bool(post_wake.get("enabled", False)),
        "post_wake_listen_ready": bool(post_wake.get("ready", False)),
        "active_listen_window_id": _text(post_wake.get("active_listen_window_id"))
        or None,
        "active_listen_window_status": _text(
            post_wake.get("active_listen_window_status")
        )
        or None,
        "active_listen_window_expires_at": _text(
            post_wake.get("active_listen_window_expires_at")
        )
        or None,
        "last_listen_window_id": _text(post_wake.get("last_listen_window_id")) or None,
        "last_listen_window_status": _text(post_wake.get("last_listen_window_status"))
        or None,
        "last_listen_window_stop_reason": _text(
            post_wake.get("last_listen_window_stop_reason")
        )
        or None,
        "listen_window_capture_id": _text(post_wake.get("listen_window_capture_id"))
        or None,
        "listen_window_audio_input_id": _text(
            post_wake.get("listen_window_audio_input_id")
        )
        or None,
        "wake_supervised_loop_enabled": bool(wake_supervised_loop.get("enabled")),
        "wake_supervised_loop_ready": bool(
            wake_supervised_loop.get("wake_supervised_loop_ready")
        ),
        "active_wake_loop_id": _text(wake_supervised_loop.get("active_loop_id"))
        or None,
        "active_wake_loop_stage": _text(wake_supervised_loop.get("active_loop_stage"))
        or None,
        "last_wake_loop_final_status": _text(wake_supervised_loop.get("final_status"))
        or None,
        "last_wake_loop_failed_stage": _text(wake_supervised_loop.get("failed_stage"))
        or None,
        "last_wake_loop_stopped_stage": _text(wake_supervised_loop.get("stopped_stage"))
        or None,
        "active_playback_id": active_playback_id,
        "active_playback_status": active_playback_status,
        "active_playback_interruptible": bool(
            playback.get("active_playback_interruptible")
            or active_playback_status in {"started", "playing"}
        ),
        "spoken_output_muted": bool(interruption.get("spoken_output_muted")),
        "muted_scope": _text(interruption.get("muted_scope")) or None,
        "current_response_suppressed": bool(
            interruption.get("current_response_suppressed")
        ),
        "interruption": _interruption_payload(interruption),
        "truth_flags": truth_flags,
        "readiness": readiness,
        "pipeline_summary": pipeline_summary,
        "ghost": ghost,
        "deck": deck,
    }


def build_voice_command_station(voice_state: dict[str, Any] | None) -> dict[str, Any]:
    state = dict(voice_state or {})
    ghost = _dict(state.get("ghost"))
    deck = _dict(state.get("deck"))
    chips = [
        _chip(
            "Capture",
            "Ready" if state.get("capture_available") else "Unavailable",
            "live" if state.get("capture_available") else "warning",
        ),
        _chip(
            "Provider",
            _title(_text(state.get("capture_provider_kind")) or "Unavailable"),
        ),
        _chip("Mode", "Push To Talk"),
    ]
    if state.get("active_capture_id"):
        chips.insert(0, _chip("State", "Recording", "attention"))
    elif state.get("last_spoken_confirmation_status"):
        chips.insert(
            0,
            _chip(
                "Confirmation",
                _title(_text(state.get("last_spoken_confirmation_status"))),
                "steady",
            ),
        )
    elif state.get("last_core_result_state"):
        chips.insert(
            0,
            _chip("Core", _title(_text(state.get("last_core_result_state"))), "steady"),
        )
    actions = []
    for action in ghost.get("actions") or []:
        if isinstance(action, dict):
            actions.append(dict(action))
    return {
        "stationId": "voice-capture-station",
        "stationFamily": "voice_capture",
        "eyebrow": "Voice",
        "title": "Voice Capture",
        "subtitle": _text(ghost.get("secondary_label"))
        or "Explicit push-to-talk capture only",
        "summary": _text(ghost.get("primary_label"))
        or "Voice status is backend-derived.",
        "body": _text(ghost.get("detail"))
        or "Stormhelm only records after explicit start and routes captured transcripts through Core.",
        "statusLabel": _title(_text(state.get("voice_current_phase"))),
        "resultState": "active"
        if state.get("active_capture_id")
        else ("blocked" if not state.get("capture_available") else "prepared"),
        "chips": chips,
        "sections": list(deck.get("sections") or []),
        "invalidations": [],
        "actions": actions,
        "layoutSlot": "secondary" if state.get("active_capture_id") else "tertiary",
    }


def _voice_status(status: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(status or {})
    voice = payload.get("voice")
    return dict(voice) if isinstance(voice, dict) else payload


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _readiness_payload(readiness: dict[str, Any]) -> dict[str, Any]:
    if not readiness:
        return {
            "overall_status": "unavailable",
            "user_facing_reason": "Voice readiness is unavailable.",
            "blocking_reasons": [],
            "warnings": [],
            "next_setup_action": None,
            "truth_flags": _truth_flags({}, {}),
        }
    payload = _sanitize(readiness)
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("blocking_reasons", [])
    payload.setdefault("warnings", [])
    payload.setdefault("truth_flags", _truth_flags({}, {}))
    payload.setdefault("user_facing_reason", "")
    payload.setdefault("next_setup_action", None)
    return payload


def _runtime_mode_payload(runtime_mode: dict[str, Any]) -> dict[str, Any]:
    payload = _sanitize(runtime_mode)
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("selected_mode", "disabled")
    payload.setdefault("effective_mode", payload.get("selected_mode") or "disabled")
    payload.setdefault("status", "unavailable")
    payload.setdefault("blocking_reasons", [])
    payload.setdefault("warnings", [])
    payload.setdefault("missing_requirements", [])
    payload.setdefault("contradictory_settings", [])
    payload.setdefault("user_facing_summary", "")
    payload.setdefault("next_fix", None)
    payload.setdefault("live_playback_available", False)
    payload.setdefault("artifact_persistence_enabled", False)
    payload.setdefault("artifact_persistence_counts_as_live_playback", False)
    return payload


def _interruption_payload(interruption: dict[str, Any]) -> dict[str, Any]:
    payload = _sanitize(interruption)
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("spoken_output_muted", False)
    payload.setdefault("current_response_suppressed", False)
    payload.setdefault("last_interruption_id", None)
    payload.setdefault("last_interruption_intent", None)
    payload.setdefault("last_interruption_status", None)
    payload.setdefault("output_interrupted", False)
    payload.setdefault("capture_interrupted", False)
    payload.setdefault("listen_window_interrupted", False)
    payload.setdefault("confirmation_interrupted", False)
    payload.setdefault("core_cancellation_requested", False)
    payload.setdefault("correction_routed", False)
    payload.setdefault("ambiguity_reason", None)
    payload.setdefault("core_task_cancelled_by_voice", False)
    payload.setdefault("core_result_mutated_by_voice", False)
    payload.setdefault("user_heard_claimed", False)
    return payload


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _preview(value: Any, *, limit: int) -> str:
    compact = " ".join(_text(value).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return None
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _RAW_AUDIO_KEYS or normalized in _SECRET_KEYS:
                continue
            if any(token in normalized for token in {"raw_audio", "raw_bytes"}):
                continue
            if any(token in normalized for token in _SECRET_KEYS):
                continue
            clean[str(key)] = _sanitize(item, depth=depth + 1)
        return clean
    if isinstance(value, list):
        return [_sanitize(item, depth=depth + 1) for item in value[:16]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return _preview(value, limit=160)
        return value
    return _text(value)


def _provider_kind(provider: str, capture: dict[str, Any]) -> str:
    if capture.get("mock_provider_active") or provider == "mock":
        return "mock"
    normalized = provider.lower()
    if not capture.get("available") and normalized not in {"local", "mock", "stub"}:
        return "unavailable"
    if normalized in {"local", "mock", "stub"}:
        return normalized
    if normalized in {"", "unavailable"}:
        return "unavailable"
    return normalized


def _pipeline_summary(
    *,
    voice: dict[str, Any],
    capture: dict[str, Any],
    stt: dict[str, Any],
    manual: dict[str, Any],
    tts: dict[str, Any],
    playback: dict[str, Any],
    interruption: dict[str, Any],
    confirmation: dict[str, Any],
    current_phase: str,
    transcript_preview: str,
    spoken_preview: str,
) -> dict[str, Any]:
    supplied = _sanitize(voice.get("pipeline_summary"))
    if isinstance(supplied, dict) and supplied:
        supplied.setdefault("transcript_preview", transcript_preview)
        supplied.setdefault("spoken_preview", spoken_preview)
        supplied.setdefault(
            "output_suppressed",
            bool(
                interruption.get("current_response_suppressed")
                or interruption.get("spoken_output_muted")
            ),
        )
        supplied.setdefault("muted", bool(interruption.get("spoken_output_muted")))
        supplied.setdefault("spoken_confirmation_status", confirmation.get("last_status"))
        return supplied
    capture_status = (
        _text(
            capture.get("active_capture_status") or capture.get("last_capture_status")
        )
        or None
    )
    transcription_status = _text(stt.get("last_transcription_state")) or None
    core_state = _text(manual.get("last_core_result_state")) or None
    synthesis_status = _text(tts.get("last_synthesis_state")) or None
    playback_status = (
        _text(
            playback.get("active_playback_status")
            or playback.get("last_playback_status")
        )
        or None
    )
    stage = _stage_from_status(
        current_phase=current_phase,
        capture_status=capture_status,
        transcription_status=transcription_status,
        core_state=core_state,
        synthesis_status=synthesis_status,
        playback_status=playback_status,
    )
    return {
        "stage": stage,
        "capture_status": capture_status,
        "transcription_status": transcription_status,
        "core_result_state": core_state,
        "synthesis_status": synthesis_status,
        "playback_status": playback_status,
        "current_blocker": _current_blocker(capture, stt, tts, playback),
        "last_successful_stage": _last_successful_stage(
            stage,
            capture_status,
            transcription_status,
            core_state,
            synthesis_status,
            playback_status,
        ),
        "failed_stage": _failed_stage(
            capture_status,
            transcription_status,
            core_state,
            synthesis_status,
            playback_status,
        ),
        "transcript_preview": transcript_preview,
        "spoken_preview": spoken_preview,
        "route_family": _text(manual.get("last_route_family")) or None,
        "subsystem": _text(manual.get("last_subsystem")) or None,
        "trust_posture": _text(manual.get("last_trust_posture")) or None,
        "verification_posture": _text(manual.get("last_verification_posture")) or None,
        "final_status": _text(interruption.get("last_interruption_status")) or stage,
        "output_stopped": _text(interruption.get("last_interruption_intent"))
        in {"stop_playback", "stop_speaking", "stop_output_only"},
        "output_suppressed": bool(
            interruption.get("current_response_suppressed")
            or interruption.get("spoken_output_muted")
        ),
        "playback_stopped": playback_status == "stopped",
        "muted": bool(interruption.get("spoken_output_muted")),
        "no_active_playback": _text(interruption.get("last_interruption_status"))
        in {"no_active_playback", "no_active_output"},
        "spoken_confirmation_status": _text(confirmation.get("last_status")) or None,
        "spoken_confirmation_intent": _text(
            _dict(confirmation.get("last_intent")).get("intent")
        )
        or None,
        "confirmation_accepted_does_not_mean_action_completed": bool(
            confirmation.get("confirmation_accepted_does_not_execute_action", True)
        ),
        "timestamps": {},
    }


def _stage_from_status(
    *,
    current_phase: str,
    capture_status: str | None,
    transcription_status: str | None,
    core_state: str | None,
    synthesis_status: str | None,
    playback_status: str | None,
) -> str:
    if capture_status in {"started", "recording", "capturing"}:
        return "capturing"
    if capture_status == "cancelled":
        return "cancelled"
    if current_phase in {"transcribing", "core_routing", "playback_active"}:
        return {
            "transcribing": "transcribing",
            "core_routing": "core_routing",
            "playback_active": "playing",
        }[current_phase]
    if transcription_status in {"started", "transcribing", "in_progress"}:
        return "transcribing"
    if core_state in {"routing", "thinking"}:
        return "core_routing"
    if synthesis_status in {"started", "synthesizing", "in_progress"}:
        return "synthesizing"
    if playback_status in {"started", "playing"}:
        return "playing"
    if any(
        status in {"failed", "timeout"}
        for status in (
            capture_status,
            transcription_status,
            synthesis_status,
            playback_status,
        )
    ):
        return "failed"
    if any(
        status in {"blocked", "unavailable"}
        for status in (
            capture_status,
            transcription_status,
            core_state,
            synthesis_status,
            playback_status,
        )
    ):
        return "blocked"
    if playback_status in {"completed", "stopped"}:
        return "completed"
    if synthesis_status in {"succeeded", "completed"}:
        return "audio_prepared"
    if core_state:
        return "response_prepared"
    if capture_status in {"completed", "stopped"}:
        return "completed"
    return "idle" if current_phase == "ready" else current_phase


def _last_successful_stage(
    stage: str,
    capture_status: str | None,
    transcription_status: str | None,
    core_state: str | None,
    synthesis_status: str | None,
    playback_status: str | None,
) -> str | None:
    if playback_status in {"completed", "stopped"}:
        return "playback"
    if synthesis_status in {"succeeded", "completed"}:
        return "tts"
    if core_state:
        return "core"
    if transcription_status in {"succeeded", "completed"}:
        return "stt"
    if capture_status in {"completed", "stopped"} or stage == "transcribing":
        return "capture"
    return None


def _failed_stage(
    capture_status: str | None,
    transcription_status: str | None,
    core_state: str | None,
    synthesis_status: str | None,
    playback_status: str | None,
) -> str | None:
    if capture_status in {"failed", "timeout", "blocked", "unavailable"}:
        return "capture"
    if transcription_status in {"failed", "blocked", "unavailable"}:
        return "stt"
    if core_state in {"failed", "blocked", "unavailable"}:
        return "core"
    if synthesis_status in {"failed", "blocked", "unavailable"}:
        return "tts"
    if playback_status in {"failed", "blocked", "unavailable"}:
        return "playback"
    return None


def _current_blocker(
    capture: dict[str, Any],
    stt: dict[str, Any],
    tts: dict[str, Any],
    playback: dict[str, Any],
) -> str | None:
    for block in (
        _dict(capture.get("last_capture_error")).get("code"),
        _dict(stt.get("last_transcription_error")).get("code"),
        _dict(tts.get("last_synthesis_error")).get("code"),
        _dict(playback.get("last_playback_error")).get("code"),
    ):
        text = _text(block)
        if text:
            return text
    return None


def _current_phase(
    *,
    voice_available: bool,
    unavailable_reason: str,
    voice_state: str,
    capture_enabled: bool,
    capture_available: bool,
    active_capture_status: str,
    active_listen_window_status: str,
    wake_ghost_active: bool,
    wake_ghost_status: str,
    wake_loop_stage: str,
    stt_state: str,
    core_state: str,
    tts_state: str,
    playback_state: str,
) -> str:
    if not voice_available or unavailable_reason:
        return "unavailable"
    if active_capture_status in {"started", "recording", "capturing"}:
        return "capturing"
    if active_listen_window_status in {"active", "pending"}:
        return "post_wake_listening"
    if active_listen_window_status == "capturing":
        return "capturing"
    if wake_loop_stage in {"listening", "capturing"}:
        return "capturing"
    if wake_loop_stage == "transcribing":
        return "transcribing"
    if wake_loop_stage in {"core", "routing"}:
        return "core_routing"
    if wake_loop_stage in {"synthesizing", "response"}:
        return "response_prepared"
    if wake_loop_stage == "playing":
        return "playback_active"
    if wake_loop_stage in {"wake", "ghost"}:
        return "wake_ghost_active"
    if wake_ghost_active or wake_ghost_status == "shown":
        return "wake_ghost_active"
    if wake_ghost_status in {"expired", "cancelled"}:
        return "ready"
    if not capture_enabled:
        return "capture_disabled"
    if not capture_available:
        return "provider_unavailable"
    if voice_state in {"transcribing"} or stt_state in {
        "started",
        "transcribing",
        "in_progress",
    }:
        return "transcribing"
    if voice_state in {"core_routing", "thinking"} or core_state in {
        "routing",
        "thinking",
    }:
        return "core_routing"
    if playback_state in {"started", "playing"}:
        return "playback_active"
    if playback_state == "completed":
        return "playback_completed"
    if tts_state in {"succeeded", "completed", "prepared"}:
        return "response_prepared"
    return "ready"


def _voice_core_state(phase: str) -> str:
    if phase in {"capturing", "post_wake_listening"}:
        return "listening"
    if phase == "wake_ghost_active":
        return "wake_ready"
    if phase in {"transcribing", "core_routing"}:
        return "thinking"
    if phase == "playback_active":
        return "speaking"
    if phase in {"unavailable", "capture_disabled", "provider_unavailable"}:
        return "warning"
    return "idle"


def _truth_flags(
    capture: dict[str, Any], runtime_truth: dict[str, Any]
) -> dict[str, Any]:
    flags = {
        key: runtime_truth.get(key, default) for key, default in _TRUTH_KEYS.items()
    }
    for key, default in _TRUTH_KEYS.items():
        if key in capture:
            flags[key] = capture.get(key)
        elif key not in flags:
            flags[key] = default
    flags["microphone_capture_requires_explicit_start"] = True
    return flags


def _ghost_payload(
    *,
    voice_available: bool,
    unavailable_reason: str,
    capture_enabled: bool,
    capture_available: bool,
    active_capture_id: str | None,
    active_capture_status: str | None,
    active_playback_id: str | None,
    spoken_output_muted: bool,
    last_capture_status: str,
    current_phase: str,
    transcript_preview: str,
    spoken_preview: str,
    wake_ghost: dict[str, Any],
    post_wake: dict[str, Any],
    wake_supervised_loop: dict[str, Any],
    confirmation: dict[str, Any],
    realtime: dict[str, Any],
) -> dict[str, Any]:
    if not voice_available or unavailable_reason:
        label = "Voice unavailable."
        detail = unavailable_reason or "Voice is not available."
        actions: list[dict[str, Any]] = []
    elif current_phase == "wake_ghost_active":
        label = _text(wake_ghost.get("wake_status_label")) or "Bearing acquired."
        detail = _text(wake_ghost.get("wake_prompt_text")) or "Ghost ready."
        actions = [_action("Dismiss", "voice.cancelWakeGhost")]
    elif current_phase == "post_wake_listening":
        label = "Waiting for your request."
        detail = "One bounded post-wake request window is open."
        actions = [_action("Cancel", "voice.cancelPostWakeListen")]
    elif not capture_enabled:
        label = "Capture disabled."
        detail = "Push-to-talk capture is disabled."
        actions = []
    elif not capture_available:
        label = "Provider unavailable."
        detail = "Capture provider unavailable."
        actions = []
    elif active_capture_id and active_capture_status in {
        "started",
        "recording",
        "capturing",
    }:
        label = "Recording one utterance."
        detail = "Release or stop to produce a bounded audio input."
        actions = [
            _action("Stop capture", "voice.stopPushToTalkCapture"),
            _action("Cancel", "voice.cancelCapture"),
        ]
    elif current_phase == "transcribing":
        label = "Transcribing captured audio."
        detail = transcript_preview or "Captured audio is moving through STT."
        actions = []
    elif current_phase == "core_routing":
        label = "Routing through Core."
        detail = (
            transcript_preview
            or "Captured transcript is passing through Stormhelm Core."
        )
        actions = []
    elif current_phase == "response_prepared":
        label = "Response ready."
        detail = spoken_preview or "Spoken response preview is prepared."
        actions = []
    elif current_phase == "playback_active":
        label = "Playing response."
        detail = "Playback is active; this does not claim the user heard it."
        actions = [_action("Stop speaking", "voice.stopSpeaking")]
        if active_playback_id:
            actions.append(_action("Stop playback", "voice.stopPlayback"))
    else:
        confirmation_label, confirmation_detail = _confirmation_label_detail(
            confirmation
        )
        if confirmation_label:
            label = confirmation_label
            detail = confirmation_detail
            actions = []
        elif _text(wake_supervised_loop.get("final_status")) in _WAKE_LOOP_CARD_STATUSES:
            label = _wake_loop_label(wake_supervised_loop)
            detail = _wake_loop_detail(wake_supervised_loop)
            actions = [_action("Start capture", "voice.startPushToTalkCapture")]
        elif last_capture_status == "cancelled":
            label = "Capture cancelled."
            detail = "Capture stopped without routing audio."
            actions = [_action("Start capture", "voice.startPushToTalkCapture")]
        elif last_capture_status in {"failed", "timeout"}:
            label = "Capture failed."
            detail = "Captured audio was not routed."
            actions = [_action("Start capture", "voice.startPushToTalkCapture")]
        elif last_capture_status in {"completed", "stopped"}:
            label = "Capture stopped."
            detail = (
                transcript_preview
                or "Captured audio is ready for the backend pipeline."
            )
            actions = [
                _action("Submit through Core", "voice.submitCapturedAudioTurn"),
                _action("Start capture", "voice.startPushToTalkCapture"),
            ]
        else:
            label = "Start capture"
            detail = "Explicit push-to-talk capture only."
            actions = [_action("Start capture", "voice.startPushToTalkCapture")]
    if spoken_output_muted:
        actions.append(_action("Unmute voice", "voice.unmuteSpokenResponses"))
    elif current_phase not in {"unavailable", "capture_disabled"}:
        actions.append(_action("Mute voice", "voice.muteSpokenResponses"))
    primary_action = actions[0]["localAction"] if actions else None
    return {
        "primary_label": label,
        "secondary_label": detail
        if current_phase == "wake_ghost_active" or confirmation.get("last_status")
        else "Push-to-talk capture only",
        "detail": _preview(detail, limit=140),
        "primary_action": primary_action,
        "actions": actions,
    }


def _deck_payload(
    *,
    capture: dict[str, Any],
    stt: dict[str, Any],
    manual: dict[str, Any],
    tts: dict[str, Any],
    playback: dict[str, Any],
    readiness: dict[str, Any],
    runtime_mode: dict[str, Any],
    pipeline_summary: dict[str, Any],
    capture_provider: str,
    provider_kind: str,
    capture_available: bool,
    audio_metadata: Any,
    truth_flags: dict[str, Any],
    interruption: dict[str, Any],
    wake: dict[str, Any],
    post_wake: dict[str, Any],
    wake_supervised_loop: dict[str, Any],
    confirmation: dict[str, Any],
    realtime: dict[str, Any],
) -> dict[str, Any]:
    sections = [
        {
            "title": "Runtime Mode",
            "entries": [
                _entry(
                    "Mode",
                    _title(_text(runtime_mode.get("effective_mode"))),
                    _text(runtime_mode.get("user_facing_summary")),
                ),
                _entry(
                    "Live Playback",
                    "Available"
                    if runtime_mode.get("live_playback_available")
                    else "Unavailable",
                    "TTS artifacts are not counted as live playback.",
                ),
                _entry(
                    "Next Fix",
                    _text(runtime_mode.get("next_fix")) or "None",
                ),
            ],
        },
        {
            "title": "Readiness",
            "entries": [
                _entry(
                    "Overall",
                    _title(_text(readiness.get("overall_status"))),
                    _text(readiness.get("user_facing_reason")),
                ),
                _entry(
                    "Next Setup",
                    _text(readiness.get("next_setup_action")) or "None",
                ),
                _entry(
                    "Blockers",
                    ", ".join(
                        str(item) for item in readiness.get("blocking_reasons") or []
                    )
                    or "None",
                ),
                _entry(
                    "Warnings",
                    ", ".join(str(item) for item in readiness.get("warnings") or [])
                    or "None",
                ),
            ],
        },
        {
            "title": "Stages",
            "entries": [
                _entry("Current Stage", _title(_text(pipeline_summary.get("stage")))),
                _entry(
                    "Capture",
                    _text(pipeline_summary.get("capture_status")) or "None",
                ),
                _entry(
                    "STT",
                    _text(pipeline_summary.get("transcription_status")) or "None",
                    _text(pipeline_summary.get("transcript_preview")),
                ),
                _entry(
                    "Core Bridge",
                    _text(pipeline_summary.get("core_result_state")) or "None",
                    _text(pipeline_summary.get("route_family")),
                ),
                _entry(
                    "Output",
                    _text(pipeline_summary.get("synthesis_status")) or "None",
                    _text(pipeline_summary.get("playback_status")),
                ),
            ],
        },
        {
            "title": "Capture",
            "entries": [
                _entry(
                    "Capture Provider",
                    _title(provider_kind),
                    capture_provider or "unavailable",
                ),
                _entry(
                    "Capture State",
                    "Available" if capture_available else "Unavailable",
                    _text(capture.get("unavailable_reason")),
                ),
                _entry(
                    "Device",
                    _text(capture.get("device")) or "default",
                    _text(capture.get("mode")) or "push_to_talk",
                ),
                _entry(
                    "Active Capture",
                    _text(capture.get("active_capture_status")) or "None",
                    _text(capture.get("active_capture_id")),
                ),
                _entry(
                    "Last Capture",
                    _text(capture.get("last_capture_status")) or "None",
                    _text(capture.get("last_capture_id")),
                ),
            ],
        },
        {
            "title": "Pipeline",
            "entries": [
                _entry(
                    "Transcription",
                    _text(stt.get("last_transcription_state")) or "None",
                    _preview(stt.get("last_transcript_preview"), limit=88),
                ),
                _entry(
                    "Core Result",
                    _text(manual.get("last_core_result_state")) or "None",
                    _text(manual.get("last_route_family")),
                ),
                _entry(
                    "Trust",
                    _text(manual.get("last_trust_posture")) or "None",
                    _text(manual.get("last_verification_posture")),
                ),
                _entry(
                    "Synthesis",
                    _text(tts.get("last_synthesis_state")) or "None",
                    _preview(tts.get("last_spoken_text_preview"), limit=88),
                ),
                _entry(
                    "Playback",
                    _text(playback.get("last_playback_status")) or "None",
                    _text(playback.get("active_playback_status")),
                ),
            ],
        },
        {
            "title": "Confirmation",
            "entries": [
                _entry(
                    "Enabled",
                    "True" if confirmation.get("enabled") else "False",
                    "Voice confirmation must bind to a pending trust prompt.",
                ),
                _entry(
                    "Pending",
                    str(int(confirmation.get("pending_confirmation_count") or 0)),
                    _text(confirmation.get("last_pending_confirmation_id")),
                ),
                _entry(
                    "Last Intent",
                    _title(
                        _text(_dict(confirmation.get("last_intent")).get("intent"))
                        or "None"
                    ),
                    _text(_dict(confirmation.get("last_intent")).get("matched_phrase_family")),
                ),
                _entry(
                    "Last Status",
                    _title(_text(confirmation.get("last_status")) or "None"),
                    _text(_dict(confirmation.get("last_result")).get("reason")),
                ),
                _entry(
                    "Binding",
                    "Valid"
                    if _dict(confirmation.get("last_binding")).get("valid")
                    else "Not valid",
                    _text(_dict(confirmation.get("last_binding")).get("invalid_reason")),
                ),
                _entry(
                    "Strength",
                    _text(
                        _dict(confirmation.get("last_binding")).get(
                            "provided_confirmation_strength"
                        )
                    )
                    or "None",
                    _text(
                        _dict(confirmation.get("last_binding")).get(
                            "required_confirmation_strength"
                        )
                    ),
                ),
                _entry(
                    "Authority",
                    "Stormhelm Core",
                    "Confirmation accepted is not action completed.",
                ),
            ],
        },
        {
            "title": "Interruption",
            "entries": [
                _entry(
                    "Speech Output",
                    "Muted" if interruption.get("spoken_output_muted") else "Unmuted",
                    _text(interruption.get("muted_scope")),
                ),
                _entry(
                    "Last Intent",
                    _text(interruption.get("last_interruption_intent")) or "None",
                    _text(interruption.get("last_interruption_status")),
                ),
                _entry(
                    "Affected Surface",
                    ", ".join(
                        label
                        for label, active in [
                            ("output", interruption.get("output_interrupted")),
                            ("capture", interruption.get("capture_interrupted")),
                            ("listen", interruption.get("listen_window_interrupted")),
                            (
                                "confirmation",
                                interruption.get("confirmation_interrupted"),
                            ),
                            ("correction", interruption.get("correction_routed")),
                        ]
                        if active
                    )
                    or "None",
                    "Task state unchanged"
                    if not interruption.get("core_task_cancelled_by_voice")
                    else "",
                ),
                _entry(
                    "Core Cancellation Request",
                    "Routed"
                    if interruption.get("core_cancellation_requested")
                    else "None",
                    "Core owns task state",
                ),
                _entry(
                    "Core Task Cancelled",
                    "False"
                    if not interruption.get("core_task_cancelled_by_voice")
                    else "True",
                ),
                _entry(
                    "Core Result Changed",
                    "False"
                    if not interruption.get("core_result_mutated_by_voice")
                    else "True",
                ),
            ],
        },
        {
            "title": "Wake Foundation",
            "entries": [
                _entry(
                    "Wake Provider",
                    _title(_text(wake.get("provider_kind")) or "Unavailable"),
                    _text(wake.get("provider")) or "None",
                ),
                _entry(
                    "Wake State",
                    "Monitoring" if wake.get("monitoring_active") else "Inactive",
                    "Mock provider active"
                    if wake.get("mock_provider_active")
                    else _text(wake.get("unavailable_reason")),
                ),
                _entry(
                    "Wake Backend",
                    _text(wake.get("wake_backend")) or "None",
                    _text(wake.get("device")) or "No device configured",
                ),
                _entry(
                    "Wake Permission",
                    _title(_text(wake.get("permission_state")) or "Unknown"),
                    _text(wake.get("permission_error")),
                ),
                _entry(
                    "Last Wake",
                    _text(_dict(wake.get("last_wake_event")).get("status")) or "None",
                    _text(_dict(wake.get("last_wake_event")).get("rejected_reason")),
                ),
                _entry(
                    "Ghost",
                    _title(_text(_dict(wake.get("ghost")).get("status")) or "None"),
                    _text(_dict(wake.get("ghost")).get("wake_status_label")),
                ),
                _entry(
                    "Authority",
                    "Core unchanged",
                    "Wake does not start capture or route commands.",
                ),
            ],
        },
        {
            "title": "Post-Wake Listen",
            "entries": [
                _entry(
                    "Readiness",
                    "Ready" if post_wake.get("ready") else "Not ready",
                    "Bounded request window, not command authority.",
                ),
                _entry(
                    "Active Window",
                    _text(post_wake.get("active_listen_window_status")) or "None",
                    _text(post_wake.get("active_listen_window_id")),
                ),
                _entry(
                    "Last Window",
                    _text(post_wake.get("last_listen_window_status")) or "None",
                    _text(post_wake.get("last_listen_window_id")),
                ),
                _entry(
                    "Capture",
                    _text(post_wake.get("listen_window_capture_id")) or "None",
                    _text(post_wake.get("listen_window_audio_input_id")),
                ),
                _entry(
                    "Authority",
                    "Core unchanged",
                    "Listen windows do not route commands by themselves.",
                ),
            ],
        },
        {
            "title": "Wake Loop",
            "entries": [
                _entry(
                    "Readiness",
                    "Ready"
                    if wake_supervised_loop.get("wake_supervised_loop_ready")
                    else "Not ready",
                    ", ".join(
                        str(item)
                        for item in wake_supervised_loop.get("missing_capabilities")
                        or []
                    )
                    or "One bounded request, then Dormant.",
                ),
                _entry(
                    "Active Loop",
                    _text(wake_supervised_loop.get("active_loop_stage")) or "None",
                    _text(wake_supervised_loop.get("active_loop_id")),
                ),
                _entry(
                    "Last Final Status",
                    _title(_text(wake_supervised_loop.get("final_status")) or "None"),
                    _text(wake_supervised_loop.get("failed_stage"))
                    or _text(wake_supervised_loop.get("stopped_stage")),
                ),
                _entry(
                    "Authority",
                    _text(wake_supervised_loop.get("command_authority"))
                    or "stormhelm_core",
                    "Wake, capture, STT, TTS, and playback are not command authority.",
                ),
            ],
        },
        {
            "title": "Realtime",
            "entries": [
                _entry(
                    "Mode",
                    _text(realtime.get("mode")) or "transcription_bridge",
                    "Core bridge required."
                    if realtime.get("mode") == "speech_to_speech_core_bridge"
                    else "Transcription bridge only.",
                ),
                _entry(
                    "Provider",
                    _title(_text(realtime.get("provider_kind")) or "Unavailable"),
                    _text(realtime.get("provider")) or "None",
                ),
                _entry(
                    "Active Session",
                    _text(realtime.get("active_realtime_session_id")) or "None",
                    _text(realtime.get("last_realtime_session_status")) or "",
                ),
                _entry(
                    "Transcript",
                    _preview(
                        realtime.get("partial_transcript_preview")
                        or realtime.get("final_transcript_preview"),
                        limit=88,
                    )
                    or "None",
                    "Final transcripts route through Core.",
                ),
                _entry(
                    "Direct Tools",
                    "No" if not realtime.get("direct_tools_allowed") else "Yes",
                    "Core bridge required.",
                ),
                _entry(
                    "Core Bridge",
                    "Required" if realtime.get("core_bridge_required", True) else "Off",
                    "stormhelm_core_request",
                ),
                _entry(
                    "Speech To Speech",
                    "No"
                    if not realtime.get("speech_to_speech_enabled")
                    else "Yes",
                    "Realtime audio output gated by Core."
                    if realtime.get("speech_to_speech_enabled")
                    else "Existing TTS/playback remains separate.",
                ),
                _entry(
                    "Last Core Result",
                    _text(realtime.get("last_core_result_state")) or "None",
                    _text(realtime.get("last_spoken_summary_source")) or "",
                ),
            ],
        },
        {
            "title": "Truth",
            "entries": [
                _entry(
                    "Wake Word",
                    "Not implemented"
                    if truth_flags.get("no_wake_word")
                    else "Available",
                ),
                _entry(
                    "VAD",
                    "Not implemented" if truth_flags.get("no_vad") else "Available",
                ),
                _entry(
                    "Realtime",
                    "Speech Core bridge"
                    if truth_flags.get("realtime_speech_to_speech_core_bridge")
                    else (
                        "Transcription bridge"
                        if truth_flags.get("realtime_transcription_bridge_only")
                        else "Not active"
                    ),
                ),
                _entry(
                    "Continuous Command Mode",
                    "False" if not truth_flags.get("always_listening") else "True",
                ),
                _entry("Audio Metadata", "Bounded", str(audio_metadata or {})),
            ],
        },
    ]
    return {"sections": sections}


def _confirmation_label_detail(confirmation: dict[str, Any]) -> tuple[str, str]:
    result = _dict(confirmation.get("last_result"))
    status = _text(confirmation.get("last_status") or result.get("status"))
    if not status:
        return "", ""
    message = _text(result.get("user_message"))
    reason = _text(result.get("reason"))
    mapping = {
        "confirmed": (
            "Confirmation accepted.",
            "Action execution remains with Core and trust.",
        ),
        "rejected": ("Confirmation rejected.", message or "Pending approval was denied."),
        "cancelled": (
            "Confirmation rejected.",
            message or "Pending approval was cancelled.",
        ),
        "expired": (
            "Confirmation expired.",
            message or "That confirmation is no longer fresh.",
        ),
        "stale": (
            "Confirmation expired.",
            message or "That confirmation is no longer fresh.",
        ),
        "binding_failed": (
            "That confirmation no longer matches the current action.",
            message or reason or "No action was approved.",
        ),
        "ambiguous": (
            "I need a clearer confirmation.",
            message or "The pending approval remains unchanged.",
        ),
        "no_pending_confirmation": (
            "No pending confirmation.",
            message or "No action was approved.",
        ),
        "shown": ("I can show the plan.", message or "Pending approval remains open."),
        "waiting": ("Waiting.", message or "Pending approval remains open."),
        "unsupported": ("No pending confirmation.", message or "No action was approved."),
    }
    return mapping.get(status, ("Confirmation required.", message or reason))


def _wake_loop_label(wake_supervised_loop: dict[str, Any]) -> str:
    status = _text(wake_supervised_loop.get("final_status"))
    return {
        "listen_timeout": "Capture timed out.",
        "capture_cancelled": "Capture cancelled.",
        "capture_failed": "Capture failed.",
        "transcription_failed": "Transcription failed.",
        "empty_transcript": "No transcript.",
        "core_clarification_required": "Clarification required.",
        "core_confirmation_required": "Confirmation required.",
        "core_blocked": "Request blocked.",
        "core_failed": "Core route failed.",
        "tts_disabled": "Response prepared.",
        "tts_failed": "Speech synthesis failed.",
        "playback_unavailable": "Playback unavailable.",
        "playback_failed": "Playback failed.",
        "playback_stopped": "Playback stopped.",
        "suppressed_or_muted": "Response prepared.",
    }.get(status, "Returning to Dormant.")


def _wake_loop_detail(wake_supervised_loop: dict[str, Any]) -> str:
    result = _dict(wake_supervised_loop.get("last_loop_result"))
    blocker = _text(
        wake_supervised_loop.get("current_blocker") or result.get("current_blocker")
    )
    spoken_preview = _text(result.get("spoken_preview"))
    transcript_preview = _text(result.get("transcript_preview"))
    status = _text(wake_supervised_loop.get("final_status"))
    if status == "suppressed_or_muted":
        return "Response remains available visually."
    if status in {
        "tts_disabled",
        "tts_failed",
        "playback_unavailable",
        "playback_failed",
        "playback_stopped",
    }:
        return spoken_preview or blocker or "Core result remains available."
    if status in {
        "core_clarification_required",
        "core_confirmation_required",
        "core_blocked",
    }:
        return spoken_preview or blocker or "Core result state is preserved."
    if status in {"transcription_failed", "empty_transcript"}:
        return blocker or "Captured audio was not routed through Core."
    return transcript_preview or blocker or "Wake loop stood down."


def _entry(primary: str, secondary: str = "", detail: str = "") -> dict[str, str]:
    return {
        "primary": primary,
        "secondary": _preview(secondary, limit=72),
        "detail": _preview(detail, limit=120),
    }


def _chip(label: str, value: str, tone: str = "steady") -> dict[str, str]:
    return {"label": label, "value": value, "tone": tone}


def _action(label: str, local_action: str) -> dict[str, Any]:
    return {
        "label": label,
        "category": "voice",
        "localAction": local_action,
        "authority": "backend_voice_service",
    }


def _title(value: str) -> str:
    text = _text(value).replace("_", " ")
    return text.title() if text else ""


def _elapsed_ms(started_at: Any) -> int | None:
    raw = _text(started_at)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(
            0, int((now - parsed.astimezone(timezone.utc)).total_seconds() * 1000)
        )
    except ValueError:
        return None
