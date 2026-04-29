from __future__ import annotations

from enum import Enum
from typing import Any

from stormhelm.core.events import EventBuffer
from stormhelm.core.events import EventFamily
from stormhelm.core.events import EventRecord
from stormhelm.core.events import EventRetentionClass
from stormhelm.core.events import EventSeverity
from stormhelm.core.events import EventVisibilityScope
from stormhelm.shared.time import utc_now_iso


class VoiceEventType(str, Enum):
    AVAILABILITY_CHANGED = "voice.availability_changed"
    STATE_CHANGED = "voice.state_changed"
    CAPTURE_REQUEST_CREATED = "voice.capture_request_created"
    CAPTURE_BLOCKED = "voice.capture_blocked"
    CAPTURE_STARTED = "voice.capture_started"
    CAPTURE_STOPPED = "voice.capture_stopped"
    CAPTURE_CANCELLED = "voice.capture_cancelled"
    CAPTURE_TIMEOUT = "voice.capture_timeout"
    CAPTURE_FAILED = "voice.capture_failed"
    CAPTURE_AUDIO_CREATED = "voice.capture_audio_created"
    WAKE_READINESS_CHANGED = "voice.wake_readiness_changed"
    WAKE_MONITORING_STARTED = "voice.wake_monitoring_started"
    WAKE_MONITORING_STOPPED = "voice.wake_monitoring_stopped"
    AUDIO_INPUT_RECEIVED = "voice.audio_input_received"
    AUDIO_VALIDATION_FAILED = "voice.audio_validation_failed"
    MANUAL_TURN_RECEIVED = "voice.manual_turn_received"
    WAKE_DETECTED = "voice.wake_detected"
    WAKE_REJECTED = "voice.wake_rejected"
    WAKE_SESSION_STARTED = "voice.wake_session_started"
    WAKE_SESSION_EXPIRED = "voice.wake_session_expired"
    WAKE_SESSION_CANCELLED = "voice.wake_session_cancelled"
    WAKE_ERROR = "voice.wake_error"
    WAKE_GHOST_REQUESTED = "voice.wake_ghost_requested"
    WAKE_GHOST_SHOWN = "voice.wake_ghost_shown"
    WAKE_GHOST_EXPIRED = "voice.wake_ghost_expired"
    WAKE_GHOST_CANCELLED = "voice.wake_ghost_cancelled"
    WAKE_GHOST_FAILED = "voice.wake_ghost_failed"
    WAKE_SUPERVISED_LOOP_STARTED = "voice.wake_supervised_loop_started"
    WAKE_SUPERVISED_LOOP_COMPLETED = "voice.wake_supervised_loop_completed"
    WAKE_SUPERVISED_LOOP_FAILED = "voice.wake_supervised_loop_failed"
    WAKE_SUPERVISED_LOOP_BLOCKED = "voice.wake_supervised_loop_blocked"
    POST_WAKE_LISTEN_OPENED = "voice.post_wake_listen_opened"
    POST_WAKE_LISTEN_STARTED = "voice.post_wake_listen_started"
    POST_WAKE_LISTEN_CAPTURE_STARTED = "voice.post_wake_listen_capture_started"
    POST_WAKE_LISTEN_CAPTURED = "voice.post_wake_listen_captured"
    POST_WAKE_LISTEN_SUBMITTED = "voice.post_wake_listen_submitted"
    POST_WAKE_LISTEN_EXPIRED = "voice.post_wake_listen_expired"
    POST_WAKE_LISTEN_CANCELLED = "voice.post_wake_listen_cancelled"
    POST_WAKE_LISTEN_FAILED = "voice.post_wake_listen_failed"
    VAD_READINESS_CHANGED = "voice.vad_readiness_changed"
    VAD_DETECTION_STARTED = "voice.vad_detection_started"
    VAD_DETECTION_STOPPED = "voice.vad_detection_stopped"
    SPEECH_ACTIVITY_STARTED = "voice.speech_activity_started"
    SPEECH_ACTIVITY_STOPPED = "voice.speech_activity_stopped"
    SILENCE_TIMEOUT = "voice.silence_timeout"
    VAD_ERROR = "voice.vad_error"
    LISTENING_STARTED = "voice.listening_started"
    LISTENING_STOPPED = "voice.listening_stopped"
    SPEECH_STARTED = "voice.speech_started"
    SPEECH_STOPPED = "voice.speech_stopped"
    TRANSCRIPTION_STARTED = "voice.transcription_started"
    TRANSCRIPTION_COMPLETED = "voice.transcription_completed"
    TRANSCRIPTION_FAILED = "voice.transcription_failed"
    CORE_REQUEST_STARTED = "voice.core_request_started"
    CORE_REQUEST_COMPLETED = "voice.core_request_completed"
    SPOKEN_RESPONSE_PREPARED = "voice.spoken_response_prepared"
    SPEECH_REQUEST_CREATED = "voice.speech_request_created"
    SPEECH_REQUEST_BLOCKED = "voice.speech_request_blocked"
    PROVIDER_PREWARMED = "voice.provider_prewarmed"
    PLAYBACK_PREWARMED = "voice.playback_prewarmed"
    SYNTHESIS_STARTED = "voice.synthesis_started"
    SYNTHESIS_COMPLETED = "voice.synthesis_completed"
    SYNTHESIS_FAILED = "voice.synthesis_failed"
    TTS_STREAM_STARTED = "voice.tts_stream_started"
    TTS_FIRST_CHUNK_RECEIVED = "voice.tts_first_chunk_received"
    TTS_STREAM_COMPLETED = "voice.tts_stream_completed"
    AUDIO_OUTPUT_CREATED = "voice.audio_output_created"
    PLAYBACK_REQUEST_CREATED = "voice.playback_request_created"
    PLAYBACK_BLOCKED = "voice.playback_blocked"
    PLAYBACK_STARTED = "voice.playback_started"
    PLAYBACK_COMPLETED = "voice.playback_completed"
    PLAYBACK_FAILED = "voice.playback_failed"
    PLAYBACK_STOPPED = "voice.playback_stopped"
    PLAYBACK_STREAM_STARTED = "voice.playback_stream_started"
    PLAYBACK_STREAM_COMPLETED = "voice.playback_stream_completed"
    PLAYBACK_STREAM_FAILED = "voice.playback_stream_failed"
    INTERRUPTION_RECEIVED = "voice.interruption_received"
    INTERRUPTION_CLASSIFIED = "voice.interruption_classified"
    INTERRUPTION_RESOLVED = "voice.interruption_resolved"
    INTERRUPTION_REQUESTED = "voice.interruption_requested"
    INTERRUPTION_COMPLETED = "voice.interruption_completed"
    INTERRUPTION_BLOCKED = "voice.interruption_blocked"
    INTERRUPTION_FAILED = "voice.interruption_failed"
    BARGE_IN_DETECTED = "voice.barge_in_detected"
    OUTPUT_INTERRUPTED = "voice.output_interrupted"
    CAPTURE_INTERRUPTED = "voice.capture_interrupted"
    LISTEN_WINDOW_INTERRUPTED = "voice.listen_window_interrupted"
    CONFIRMATION_INTERRUPTED = "voice.confirmation_interrupted"
    CORE_CANCELLATION_REQUESTED = "voice.core_cancellation_requested"
    CORRECTION_ROUTED = "voice.correction_routed"
    SPEECH_SUPPRESSED = "voice.speech_suppressed"
    SPOKEN_OUTPUT_MUTED = "voice.spoken_output_muted"
    SPOKEN_OUTPUT_UNMUTED = "voice.spoken_output_unmuted"
    SPOKEN_CONFIRMATION_RECEIVED = "voice.spoken_confirmation_received"
    SPOKEN_CONFIRMATION_CLASSIFIED = "voice.spoken_confirmation_classified"
    SPOKEN_CONFIRMATION_BOUND = "voice.spoken_confirmation_bound"
    SPOKEN_CONFIRMATION_ACCEPTED = "voice.spoken_confirmation_accepted"
    SPOKEN_CONFIRMATION_REJECTED = "voice.spoken_confirmation_rejected"
    SPOKEN_CONFIRMATION_EXPIRED = "voice.spoken_confirmation_expired"
    SPOKEN_CONFIRMATION_AMBIGUOUS = "voice.spoken_confirmation_ambiguous"
    SPOKEN_CONFIRMATION_CONSUMED = "voice.spoken_confirmation_consumed"
    SPOKEN_CONFIRMATION_FAILED = "voice.spoken_confirmation_failed"
    REALTIME_READINESS_CHANGED = "voice.realtime_readiness_changed"
    REALTIME_SESSION_CREATED = "voice.realtime_session_created"
    REALTIME_SESSION_STARTED = "voice.realtime_session_started"
    REALTIME_SESSION_ACTIVE = "voice.realtime_session_active"
    REALTIME_SESSION_CLOSED = "voice.realtime_session_closed"
    REALTIME_SESSION_EXPIRED = "voice.realtime_session_expired"
    REALTIME_SESSION_CANCELLED = "voice.realtime_session_cancelled"
    REALTIME_SESSION_FAILED = "voice.realtime_session_failed"
    REALTIME_PARTIAL_TRANSCRIPT = "voice.realtime_partial_transcript"
    REALTIME_FINAL_TRANSCRIPT = "voice.realtime_final_transcript"
    REALTIME_TURN_CREATED = "voice.realtime_turn_created"
    REALTIME_TURN_SUBMITTED_TO_CORE = "voice.realtime_turn_submitted_to_core"
    REALTIME_TURN_COMPLETED = "voice.realtime_turn_completed"
    REALTIME_TURN_FAILED = "voice.realtime_turn_failed"
    REALTIME_SPEECH_SESSION_CREATED = "voice.realtime_speech_session_created"
    REALTIME_SPEECH_SESSION_STARTED = "voice.realtime_speech_session_started"
    REALTIME_SPEECH_SESSION_ACTIVE = "voice.realtime_speech_session_active"
    REALTIME_SPEECH_SESSION_CLOSED = "voice.realtime_speech_session_closed"
    REALTIME_SPEECH_SESSION_FAILED = "voice.realtime_speech_session_failed"
    REALTIME_CORE_BRIDGE_CALL_STARTED = "voice.realtime_core_bridge_call_started"
    REALTIME_CORE_BRIDGE_CALL_COMPLETED = "voice.realtime_core_bridge_call_completed"
    REALTIME_CORE_BRIDGE_CALL_FAILED = "voice.realtime_core_bridge_call_failed"
    REALTIME_RESPONSE_GATED = "voice.realtime_response_gated"
    REALTIME_SPOKEN_RESPONSE_ALLOWED = "voice.realtime_spoken_response_allowed"
    REALTIME_SPOKEN_RESPONSE_BLOCKED = "voice.realtime_spoken_response_blocked"
    REALTIME_AUDIO_OUTPUT_STARTED = "voice.realtime_audio_output_started"
    REALTIME_AUDIO_OUTPUT_STOPPED = "voice.realtime_audio_output_stopped"
    REALTIME_AUDIO_OUTPUT_COMPLETED = "voice.realtime_audio_output_completed"
    REALTIME_DIRECT_TOOL_BLOCKED = "voice.realtime_direct_tool_blocked"
    SPEAKING_STARTED = "voice.speaking_started"
    SPEAKING_COMPLETED = "voice.speaking_completed"
    INTERRUPTED = "voice.interrupted"
    TURN_COMPLETED = "voice.turn_completed"
    TURN_FAILED = "voice.turn_failed"
    ERROR = "voice.error"


def build_voice_event_payload(
    *,
    event_type: VoiceEventType | str,
    correlation_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    capture_request_id: str | None = None,
    capture_id: str | None = None,
    provider: str | None = None,
    mode: str | None = None,
    state: str | None = None,
    task_id: str | None = None,
    input_id: str | None = None,
    transcription_id: str | None = None,
    speech_request_id: str | None = None,
    synthesis_id: str | None = None,
    audio_output_id: str | None = None,
    playback_request_id: str | None = None,
    playback_id: str | None = None,
    interruption_id: str | None = None,
    wake_event_id: str | None = None,
    wake_session_id: str | None = None,
    wake_ghost_request_id: str | None = None,
    vad_session_id: str | None = None,
    activity_event_id: str | None = None,
    spoken_confirmation_intent_id: str | None = None,
    spoken_confirmation_request_id: str | None = None,
    spoken_confirmation_result_id: str | None = None,
    pending_confirmation_id: str | None = None,
    listen_window_id: str | None = None,
    realtime_session_id: str | None = None,
    realtime_turn_id: str | None = None,
    realtime_event_id: str | None = None,
    wake_phrase: str | None = None,
    intent: str | None = None,
    muted_scope: str | None = None,
    action_id: str | None = None,
    required_strength: str | None = None,
    provided_strength: str | None = None,
    binding_valid: bool | None = None,
    invalid_reason: str | None = None,
    consumed: bool | None = None,
    action_executed: bool | None = None,
    provider_kind: str | None = None,
    backend: str | None = None,
    core_task_cancelled: bool | None = None,
    core_result_mutated: bool | None = None,
    spoken_output_suppressed: bool | None = None,
    confidence: float | None = None,
    accepted: bool | None = None,
    rejected_reason: str | None = None,
    cooldown_active: bool | None = None,
    false_positive_candidate: bool | None = None,
    openai_used: bool | None = None,
    cloud_used: bool | None = None,
    raw_audio_present: bool | None = None,
    is_partial: bool | None = None,
    is_final: bool | None = None,
    direct_tools_allowed: bool | None = None,
    core_bridge_required: bool | None = None,
    speech_to_speech_enabled: bool | None = None,
    audio_output_from_realtime: bool | None = None,
    duration_ms: int | None = None,
    silence_ms: int | None = None,
    size_bytes: int | None = None,
    model: str | None = None,
    voice: str | None = None,
    format: str | None = None,
    device: str | None = None,
    status: str | None = None,
    ui_mode: str | None = None,
    error_code: str | None = None,
    result_state: str | None = None,
    route_family: str | None = None,
    subsystem: str | None = None,
    source: str = "voice",
    privacy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_type = (
        event_type.value if isinstance(event_type, VoiceEventType) else str(event_type)
    )
    payload: dict[str, Any] = {
        "event_type": resolved_type,
        "timestamp": utc_now_iso(),
        "source": source,
        "privacy": dict(privacy or {}),
        "metadata": dict(metadata or {}),
    }
    for key, value in {
        "correlation_id": correlation_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "capture_request_id": capture_request_id,
        "capture_id": capture_id,
        "provider": provider,
        "mode": mode,
        "state": state,
        "task_id": task_id,
        "input_id": input_id,
        "transcription_id": transcription_id,
        "speech_request_id": speech_request_id,
        "synthesis_id": synthesis_id,
        "audio_output_id": audio_output_id,
        "playback_request_id": playback_request_id,
        "playback_id": playback_id,
        "interruption_id": interruption_id,
        "wake_event_id": wake_event_id,
        "wake_session_id": wake_session_id,
        "wake_ghost_request_id": wake_ghost_request_id,
        "vad_session_id": vad_session_id,
        "activity_event_id": activity_event_id,
        "spoken_confirmation_intent_id": spoken_confirmation_intent_id,
        "spoken_confirmation_request_id": spoken_confirmation_request_id,
        "spoken_confirmation_result_id": spoken_confirmation_result_id,
        "pending_confirmation_id": pending_confirmation_id,
        "listen_window_id": listen_window_id,
        "realtime_session_id": realtime_session_id,
        "realtime_turn_id": realtime_turn_id,
        "realtime_event_id": realtime_event_id,
        "wake_phrase": wake_phrase,
        "intent": intent,
        "muted_scope": muted_scope,
        "action_id": action_id,
        "required_strength": required_strength,
        "provided_strength": provided_strength,
        "binding_valid": binding_valid,
        "invalid_reason": invalid_reason,
        "consumed": consumed,
        "action_executed": action_executed,
        "provider_kind": provider_kind,
        "backend": backend,
        "core_task_cancelled": core_task_cancelled,
        "core_result_mutated": core_result_mutated,
        "spoken_output_suppressed": spoken_output_suppressed,
        "confidence": confidence,
        "accepted": accepted,
        "rejected_reason": rejected_reason,
        "cooldown_active": cooldown_active,
        "false_positive_candidate": false_positive_candidate,
        "openai_used": openai_used,
        "cloud_used": cloud_used,
        "raw_audio_present": raw_audio_present,
        "is_partial": is_partial,
        "is_final": is_final,
        "direct_tools_allowed": direct_tools_allowed,
        "core_bridge_required": core_bridge_required,
        "speech_to_speech_enabled": speech_to_speech_enabled,
        "audio_output_from_realtime": audio_output_from_realtime,
        "duration_ms": duration_ms,
        "silence_ms": silence_ms,
        "size_bytes": size_bytes,
        "model": model,
        "voice": voice,
        "format": format,
        "device": device,
        "status": status,
        "ui_mode": ui_mode,
        "error_code": error_code,
        "result_state": result_state,
        "route_family": route_family,
        "subsystem": subsystem,
    }.items():
        if value is not None:
            payload[key] = value
    return payload


def publish_voice_event(
    events: EventBuffer,
    event_type: VoiceEventType,
    *,
    message: str,
    correlation_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    capture_request_id: str | None = None,
    capture_id: str | None = None,
    provider: str | None = None,
    mode: str | None = None,
    state: str | None = None,
    task_id: str | None = None,
    input_id: str | None = None,
    transcription_id: str | None = None,
    speech_request_id: str | None = None,
    synthesis_id: str | None = None,
    audio_output_id: str | None = None,
    playback_request_id: str | None = None,
    playback_id: str | None = None,
    interruption_id: str | None = None,
    wake_event_id: str | None = None,
    wake_session_id: str | None = None,
    wake_ghost_request_id: str | None = None,
    vad_session_id: str | None = None,
    activity_event_id: str | None = None,
    spoken_confirmation_intent_id: str | None = None,
    spoken_confirmation_request_id: str | None = None,
    spoken_confirmation_result_id: str | None = None,
    pending_confirmation_id: str | None = None,
    listen_window_id: str | None = None,
    realtime_session_id: str | None = None,
    realtime_turn_id: str | None = None,
    realtime_event_id: str | None = None,
    wake_phrase: str | None = None,
    intent: str | None = None,
    muted_scope: str | None = None,
    action_id: str | None = None,
    required_strength: str | None = None,
    provided_strength: str | None = None,
    binding_valid: bool | None = None,
    invalid_reason: str | None = None,
    consumed: bool | None = None,
    action_executed: bool | None = None,
    provider_kind: str | None = None,
    backend: str | None = None,
    core_task_cancelled: bool | None = None,
    core_result_mutated: bool | None = None,
    spoken_output_suppressed: bool | None = None,
    confidence: float | None = None,
    accepted: bool | None = None,
    rejected_reason: str | None = None,
    cooldown_active: bool | None = None,
    false_positive_candidate: bool | None = None,
    openai_used: bool | None = None,
    cloud_used: bool | None = None,
    raw_audio_present: bool | None = None,
    is_partial: bool | None = None,
    is_final: bool | None = None,
    direct_tools_allowed: bool | None = None,
    core_bridge_required: bool | None = None,
    speech_to_speech_enabled: bool | None = None,
    audio_output_from_realtime: bool | None = None,
    duration_ms: int | None = None,
    silence_ms: int | None = None,
    size_bytes: int | None = None,
    model: str | None = None,
    voice: str | None = None,
    format: str | None = None,
    device: str | None = None,
    status: str | None = None,
    ui_mode: str | None = None,
    error_code: str | None = None,
    result_state: str | None = None,
    route_family: str | None = None,
    subsystem: str | None = None,
    source: str = "voice",
    severity: str | EventSeverity = EventSeverity.INFO,
    privacy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> EventRecord:
    return events.publish(
        event_family=EventFamily.VOICE,
        event_type=event_type.value,
        subsystem="voice",
        severity=severity,
        visibility_scope=EventVisibilityScope.DECK_CONTEXT,
        retention_class=EventRetentionClass.BOUNDED_RECENT,
        session_id=session_id,
        message=message,
        payload=build_voice_event_payload(
            event_type=event_type,
            correlation_id=correlation_id,
            session_id=session_id,
            turn_id=turn_id,
            capture_request_id=capture_request_id,
            capture_id=capture_id,
            provider=provider,
            mode=mode,
            state=state,
            task_id=task_id,
            input_id=input_id,
            transcription_id=transcription_id,
            speech_request_id=speech_request_id,
            synthesis_id=synthesis_id,
            audio_output_id=audio_output_id,
            playback_request_id=playback_request_id,
            playback_id=playback_id,
            interruption_id=interruption_id,
            wake_event_id=wake_event_id,
            wake_session_id=wake_session_id,
            wake_ghost_request_id=wake_ghost_request_id,
            vad_session_id=vad_session_id,
            activity_event_id=activity_event_id,
            spoken_confirmation_intent_id=spoken_confirmation_intent_id,
            spoken_confirmation_request_id=spoken_confirmation_request_id,
            spoken_confirmation_result_id=spoken_confirmation_result_id,
            pending_confirmation_id=pending_confirmation_id,
            listen_window_id=listen_window_id,
            realtime_session_id=realtime_session_id,
            realtime_turn_id=realtime_turn_id,
            realtime_event_id=realtime_event_id,
            wake_phrase=wake_phrase,
            intent=intent,
            muted_scope=muted_scope,
            action_id=action_id,
            required_strength=required_strength,
            provided_strength=provided_strength,
            binding_valid=binding_valid,
            invalid_reason=invalid_reason,
            consumed=consumed,
            action_executed=action_executed,
            provider_kind=provider_kind,
            backend=backend,
            core_task_cancelled=core_task_cancelled,
            core_result_mutated=core_result_mutated,
            spoken_output_suppressed=spoken_output_suppressed,
            confidence=confidence,
            accepted=accepted,
            rejected_reason=rejected_reason,
            cooldown_active=cooldown_active,
            false_positive_candidate=false_positive_candidate,
            openai_used=openai_used,
            cloud_used=cloud_used,
            raw_audio_present=raw_audio_present,
            is_partial=is_partial,
            is_final=is_final,
            direct_tools_allowed=direct_tools_allowed,
            core_bridge_required=core_bridge_required,
            speech_to_speech_enabled=speech_to_speech_enabled,
            audio_output_from_realtime=audio_output_from_realtime,
            duration_ms=duration_ms,
            silence_ms=silence_ms,
            size_bytes=size_bytes,
            model=model,
            voice=voice,
            format=format,
            device=device,
            status=status,
            ui_mode=ui_mode,
            error_code=error_code,
            result_state=result_state,
            route_family=route_family,
            subsystem=subsystem,
            source=source,
            privacy=privacy,
            metadata=metadata,
        ),
    )
