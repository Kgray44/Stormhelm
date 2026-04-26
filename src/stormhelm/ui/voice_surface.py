from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


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


def build_voice_ui_state(status: dict[str, Any] | None) -> dict[str, Any]:
    """Build the compact, safe voice state consumed by Ghost and the Deck."""

    voice = _voice_status(status)
    availability = _dict(voice.get("availability"))
    provider = _dict(voice.get("provider"))
    openai = _dict(voice.get("openai"))
    capture = _dict(voice.get("capture"))
    stt = _dict(voice.get("stt"))
    manual = _dict(voice.get("manual_turns"))
    tts = _dict(voice.get("tts"))
    playback = _dict(voice.get("playback"))
    runtime_truth = _dict(voice.get("runtime_truth"))
    readiness = _readiness_payload(_dict(voice.get("readiness")))

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
    current_phase = _current_phase(
        voice_available=voice_available,
        unavailable_reason=unavailable_reason,
        voice_state=voice_state,
        capture_enabled=capture_enabled,
        capture_available=capture_available,
        active_capture_status=active_capture_status or "",
        stt_state=_text(stt.get("last_transcription_state")),
        core_state=_text(manual.get("last_core_result_state")),
        tts_state=_text(tts.get("last_synthesis_state")),
        playback_state=_text(
            playback.get("active_playback_status")
            or playback.get("last_playback_status")
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
        current_phase=current_phase,
        transcript_preview=transcript_preview,
        spoken_preview=spoken_preview,
    )
    audio_metadata = _sanitize(capture.get("last_capture_audio_input_metadata"))
    truth_flags = _truth_flags(capture, runtime_truth)
    ghost = _ghost_payload(
        voice_available=voice_available,
        unavailable_reason=unavailable_reason,
        capture_enabled=capture_enabled,
        capture_available=capture_available,
        active_capture_id=active_capture_id,
        active_capture_status=active_capture_status,
        last_capture_status=_text(capture.get("last_capture_status")),
        current_phase=current_phase,
        transcript_preview=transcript_preview,
        spoken_preview=spoken_preview,
    )
    deck = _deck_payload(
        capture=capture,
        stt=stt,
        manual=manual,
        tts=tts,
        playback=playback,
        readiness=readiness,
        pipeline_summary=pipeline_summary,
        capture_provider=capture_provider,
        provider_kind=provider_kind,
        capture_available=capture_available,
        audio_metadata=audio_metadata,
        truth_flags=truth_flags,
    )

    return {
        "voice_available": voice_available,
        "voice_state": voice_state or ("dormant" if voice_available else "unavailable"),
        "voice_current_phase": current_phase,
        "voice_core_state": core_state,
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
    current_phase: str,
    transcript_preview: str,
    spoken_preview: str,
) -> dict[str, Any]:
    supplied = _sanitize(voice.get("pipeline_summary"))
    if isinstance(supplied, dict) and supplied:
        supplied.setdefault("transcript_preview", transcript_preview)
        supplied.setdefault("spoken_preview", spoken_preview)
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
    if playback_status == "completed":
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
    if playback_status == "completed":
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
    stt_state: str,
    core_state: str,
    tts_state: str,
    playback_state: str,
) -> str:
    if not voice_available or unavailable_reason:
        return "unavailable"
    if not capture_enabled:
        return "capture_disabled"
    if not capture_available:
        return "provider_unavailable"
    if active_capture_status in {"started", "recording", "capturing"}:
        return "capturing"
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
    if tts_state in {"succeeded", "completed", "prepared"}:
        return "response_prepared"
    if playback_state in {"started", "playing"}:
        return "playback_active"
    if playback_state == "completed":
        return "playback_completed"
    return "ready"


def _voice_core_state(phase: str) -> str:
    if phase == "capturing":
        return "listening"
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
    last_capture_status: str,
    current_phase: str,
    transcript_preview: str,
    spoken_preview: str,
) -> dict[str, Any]:
    if not voice_available or unavailable_reason:
        label = "Voice unavailable."
        detail = unavailable_reason or "Voice is not available."
        actions: list[dict[str, Any]] = []
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
        actions = [_action("Stop playback", "voice.stopPlayback")]
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
            transcript_preview or "Captured audio is ready for the backend pipeline."
        )
        actions = [
            _action("Submit through Core", "voice.submitCapturedAudioTurn"),
            _action("Start capture", "voice.startPushToTalkCapture"),
        ]
    else:
        label = "Start capture"
        detail = "Explicit push-to-talk capture only."
        actions = [_action("Start capture", "voice.startPushToTalkCapture")]
    primary_action = actions[0]["localAction"] if actions else None
    return {
        "primary_label": label,
        "secondary_label": "Push-to-talk capture only",
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
    pipeline_summary: dict[str, Any],
    capture_provider: str,
    provider_kind: str,
    capture_available: bool,
    audio_metadata: Any,
    truth_flags: dict[str, Any],
) -> dict[str, Any]:
    sections = [
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
                    "Not implemented"
                    if truth_flags.get("no_realtime")
                    else "Available",
                ),
                _entry(
                    "Always Listening",
                    "False" if not truth_flags.get("always_listening") else "True",
                ),
                _entry("Audio Metadata", "Bounded", str(audio_metadata or {})),
            ],
        },
    ]
    return {"sections": sections}


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
