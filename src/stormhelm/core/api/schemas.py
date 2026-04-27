from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = "default"
    surface_mode: str = "ghost"
    active_module: str = "chartroom"
    workspace_context: dict[str, Any] = Field(default_factory=dict)
    input_context: dict[str, Any] = Field(default_factory=dict)


class NoteCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    session_id: str = "default"
    workspace_id: str = ""


class ShellPresenceRequest(BaseModel):
    pid: int = Field(..., ge=0)
    mode: str = "ghost"
    window_visible: bool = False
    tray_present: bool = False
    hide_to_tray_on_close: bool = False
    ghost_reveal_target: float = 0.0
    event: str = "heartbeat"
    observed_at: str = ""


class StartupPolicyMutationRequest(BaseModel):
    startup_enabled: bool = False
    start_core_with_windows: bool = False
    start_shell_with_windows: bool = False
    tray_only_startup: bool = True
    ghost_ready_on_startup: bool = True


class LifecycleResolutionRequest(BaseModel):
    plan_id: str = ""
    resolution_kind: str = ""
    confirmation_kind: str = ""
    confirmed_summary: str = ""


class DestructiveCleanupConfirmationRequest(BaseModel):
    plan_id: str = ""
    operation: str = ""
    confirmation_kind: str = ""
    confirmed_summary: str = ""
    confirmed_at: str = ""
    destructive_intent: bool = False


class CleanupExecutionRequest(BaseModel):
    remove_startup_registration: bool = False
    remove_logs: bool = False
    remove_caches: bool = False
    remove_durable_state: bool = False
    destructive_confirmation_received: bool = False
    destructive_confirmation: DestructiveCleanupConfirmationRequest | None = None


class VoiceCaptureControlRequest(BaseModel):
    capture_id: str | None = None
    session_id: str = "default"
    mode: str = "ghost"
    reason: str = "user_released"
    synthesize_response: bool = False
    play_response: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoicePlaybackControlRequest(BaseModel):
    playback_id: str | None = None
    reason: str = "user_requested"
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceInterruptionControlRequest(BaseModel):
    intent: str | None = None
    transcript: str = Field("", max_length=500)
    normalized_phrase: str = ""
    session_id: str = "default"
    turn_id: str | None = None
    playback_id: str | None = None
    capture_id: str | None = None
    listen_window_id: str | None = None
    realtime_session_id: str | None = None
    pending_confirmation_id: str | None = None
    active_loop_id: str | None = None
    reason: str = "user_requested"
    scope: str = "session"
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceRealtimeControlRequest(BaseModel):
    session_id: str = "default"
    realtime_session_id: str | None = None
    listen_window_id: str | None = None
    capture_id: str | None = None
    transcript: str = Field("", max_length=2000)
    source: str = "test"
    mode: str = "ghost"
    reason: str = "user_requested"
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceWakeControlRequest(BaseModel):
    session_id: str = "default"
    wake_event_id: str | None = None
    wake_session_id: str | None = None
    confidence: float | None = None
    mode: str = "ghost"
    synthesize_response: bool = False
    play_response: bool = False
    finalize_with_vad: bool = False
    reason: str = "user_requested"
    source: str = "mock"
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceSpokenConfirmationControlRequest(BaseModel):
    transcript: str = Field("", max_length=500)
    normalized_phrase: str = ""
    session_id: str = "default"
    turn_id: str | None = None
    source: str = "api"
    pending_confirmation_id: str | None = None
    task_id: str | None = None
    route_family: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventsResponse(BaseModel):
    events: list[dict[str, Any]]
    cursor: int | None = None
    earliest_cursor: int | None = None
    latest_cursor: int | None = None
    gap_detected: bool = False


class JobsResponse(BaseModel):
    jobs: list[dict[str, Any]]


class NotesResponse(BaseModel):
    notes: list[dict[str, Any]]
