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
    AUDIO_INPUT_RECEIVED = "voice.audio_input_received"
    AUDIO_VALIDATION_FAILED = "voice.audio_validation_failed"
    MANUAL_TURN_RECEIVED = "voice.manual_turn_received"
    WAKE_DETECTED = "voice.wake_detected"
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
    SYNTHESIS_STARTED = "voice.synthesis_started"
    SYNTHESIS_COMPLETED = "voice.synthesis_completed"
    SYNTHESIS_FAILED = "voice.synthesis_failed"
    AUDIO_OUTPUT_CREATED = "voice.audio_output_created"
    PLAYBACK_REQUEST_CREATED = "voice.playback_request_created"
    PLAYBACK_BLOCKED = "voice.playback_blocked"
    PLAYBACK_STARTED = "voice.playback_started"
    PLAYBACK_COMPLETED = "voice.playback_completed"
    PLAYBACK_FAILED = "voice.playback_failed"
    PLAYBACK_STOPPED = "voice.playback_stopped"
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
    duration_ms: int | None = None,
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
        "duration_ms": duration_ms,
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
    duration_ms: int | None = None,
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
            duration_ms=duration_ms,
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
