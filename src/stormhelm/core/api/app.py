from __future__ import annotations

import asyncio
import json
import os
import signal
import threading
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from stormhelm.config.models import AppConfig
from stormhelm.core.api.schemas import (
    ChatRequest,
    CleanupExecutionRequest,
    LifecycleResolutionRequest,
    EventsResponse,
    JobsResponse,
    NoteCreateRequest,
    NotesResponse,
    ShellPresenceRequest,
    StartupPolicyMutationRequest,
    VoiceCaptureControlRequest,
    VoicePlaybackControlRequest,
)
from stormhelm.core.container import CoreContainer, build_container
from stormhelm.core.lifecycle import ShellPresenceUpdate
from stormhelm.version import __version__


def _schedule_process_shutdown(delay_seconds: float = 0.15) -> None:
    timer = threading.Timer(delay_seconds, _terminate_current_process)
    timer.daemon = True
    timer.start()


def _terminate_current_process() -> None:
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        os._exit(0)


def create_app(config: AppConfig | None = None) -> FastAPI:
    container = build_container(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container
        await container.start()
        try:
            yield
        finally:
            await container.stop()

    app = FastAPI(title="Stormhelm Core", version=__version__, lifespan=lifespan)
    app.state.container = container

    def _current_container(request: Request) -> CoreContainer:
        return request.app.state.container

    def _health_payload(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return {
            "status": "ok",
            "version": __version__,
            "version_label": current.config.version_label,
            "app_name": current.config.app_name,
            "protocol_version": current.config.protocol_version,
            "max_workers": current.config.concurrency.max_workers,
            "runtime_mode": current.config.runtime.mode,
            "install_mode": current.lifecycle.install_state.install_mode.value,
            "pid": os.getpid(),
        }

    @app.get("/health")
    def health(request: Request) -> dict[str, object]:
        return _health_payload(request)

    @app.get("/status")
    def status(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return current.status_snapshot()

    @app.post("/chat/send")
    async def send_chat(payload: ChatRequest, request: Request) -> dict[str, object]:
        current = _current_container(request)
        endpoint_started = perf_counter()
        result = await current.assistant.handle_message(
            payload.message,
            payload.session_id,
            surface_mode=payload.surface_mode,
            active_module=payload.active_module,
            workspace_context=payload.workspace_context,
            input_context=payload.input_context,
        )
        endpoint_dispatch_ms = round((perf_counter() - endpoint_started) * 1000, 3)
        return_started = perf_counter()
        assistant_message = (
            result.get("assistant_message") if isinstance(result, dict) else {}
        )
        metadata = (
            assistant_message.get("metadata")
            if isinstance(assistant_message, dict)
            else {}
        )
        if isinstance(metadata, dict):
            stage_timings = (
                metadata.get("stage_timings_ms")
                if isinstance(metadata.get("stage_timings_ms"), dict)
                else {}
            )
            stage_timings = dict(stage_timings)
            stage_timings["endpoint_dispatch_ms"] = endpoint_dispatch_ms
            stage_timings["asgi_request_receive_ms"] = 0.0
            stage_timings["server_response_write_ms"] = 0.0
            stage_timings["endpoint_return_to_asgi_ms"] = round(
                (perf_counter() - return_started) * 1000, 3
            )
            metadata["stage_timings_ms"] = stage_timings
            metadata["api_timings_ms"] = {
                "asgi_request_receive_ms": 0.0,
                "endpoint_dispatch_ms": endpoint_dispatch_ms,
                "endpoint_return_to_asgi_ms": stage_timings[
                    "endpoint_return_to_asgi_ms"
                ],
                "server_response_write_ms": 0.0,
            }
        return result

    @app.get("/chat/history")
    def chat_history(
        request: Request, session_id: str = "default", limit: int = 100
    ) -> dict[str, object]:
        current = _current_container(request)
        items = [
            message.to_dict()
            for message in current.conversations.list_messages(
                session_id=session_id, limit=limit
            )
        ]
        return {"messages": items}

    @app.get("/jobs", response_model=JobsResponse)
    def list_jobs(request: Request, limit: int = 100) -> dict[str, object]:
        current = _current_container(request)
        return {"jobs": current.jobs.list_jobs(limit=limit)}

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, request: Request) -> dict[str, object]:
        current = _current_container(request)
        cancelled = current.jobs.cancel(job_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="Unknown job id.")
        return {"job_id": job_id, "cancelled": True}

    @app.get("/events", response_model=EventsResponse)
    def list_events(
        request: Request,
        since_id: int = 0,
        cursor: int | None = None,
        limit: int = 100,
        session_id: str = "default",
    ) -> dict[str, object]:
        current = _current_container(request)
        replay = current.events.replay(
            cursor=cursor if cursor is not None else since_id,
            limit=limit,
            session_id=session_id,
        )
        return {
            "events": [event.to_dict() for event in replay.events],
            "cursor": replay.next_cursor,
            "earliest_cursor": replay.earliest_cursor,
            "latest_cursor": replay.latest_cursor,
            "gap_detected": replay.gap_detected,
        }

    def _encode_sse(event_name: str, payload: dict[str, object]) -> str:
        return f"event: {event_name}\ndata: {json.dumps(payload, separators=(',', ':'), default=str)}\n\n"

    @app.get("/events/stream")
    async def stream_events(
        request: Request,
        session_id: str = "default",
        cursor: int = 0,
        replay_limit: int | None = None,
        heartbeat_seconds: float | None = None,
    ) -> StreamingResponse:
        current = _current_container(request)
        effective_replay_limit = max(
            1, int(replay_limit or current.config.event_stream.replay_limit)
        )
        effective_heartbeat_seconds = max(
            1.0,
            float(heartbeat_seconds or current.config.event_stream.heartbeat_seconds),
        )

        async def event_stream():
            current_cursor = max(0, int(cursor))
            connection = current.events.register_stream()
            try:
                replay = current.events.replay(
                    cursor=current_cursor,
                    limit=effective_replay_limit,
                    session_id=session_id,
                )
                yield _encode_sse(
                    "stormhelm.stream_state",
                    {
                        "phase": "connected",
                        "source": "core",
                        "session_id": session_id,
                        "requested_cursor": current_cursor,
                        "earliest_cursor": replay.earliest_cursor,
                        "latest_cursor": replay.latest_cursor,
                        "gap_detected": replay.gap_detected,
                        "returned_count": replay.returned_count,
                        "connections_current": connection["connections_current"],
                    },
                )
                if replay.gap_detected:
                    yield _encode_sse(
                        "stormhelm.replay_gap",
                        {
                            "source": "core",
                            "session_id": session_id,
                            "requested_cursor": current_cursor,
                            "earliest_cursor": replay.earliest_cursor,
                            "latest_cursor": replay.latest_cursor,
                            "reason": "cursor_outside_retention_window",
                        },
                    )
                for event in replay.events:
                    current_cursor = event.cursor
                    yield _encode_sse("stormhelm.event", event.to_dict())

                while True:
                    if await request.is_disconnected():
                        break
                    next_event = await asyncio.to_thread(
                        current.events.wait_for_next_event,
                        cursor=current_cursor,
                        timeout=effective_heartbeat_seconds,
                        session_id=session_id,
                    )
                    if next_event is None:
                        state = current.events.state_snapshot()
                        yield _encode_sse(
                            "stormhelm.stream_state",
                            {
                                "phase": "heartbeat",
                                "source": "core",
                                "session_id": session_id,
                                "current_cursor": current_cursor,
                                "latest_cursor": state["latest_cursor"],
                                "connections_current": state["connections_current"],
                            },
                        )
                        continue

                    replay = current.events.replay(
                        cursor=current_cursor,
                        limit=effective_replay_limit,
                        session_id=session_id,
                    )
                    if replay.gap_detected:
                        yield _encode_sse(
                            "stormhelm.replay_gap",
                            {
                                "source": "core",
                                "session_id": session_id,
                                "requested_cursor": current_cursor,
                                "earliest_cursor": replay.earliest_cursor,
                                "latest_cursor": replay.latest_cursor,
                                "reason": "cursor_outside_retention_window",
                            },
                        )
                    for event in replay.events:
                        current_cursor = event.cursor
                        yield _encode_sse("stormhelm.event", event.to_dict())
            finally:
                current.events.unregister_stream()

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/notes", response_model=NotesResponse)
    def list_notes(request: Request, limit: int = 50) -> dict[str, object]:
        current = _current_container(request)
        return {
            "notes": [note.to_dict() for note in current.notes.list_notes(limit=limit)]
        }

    @app.post("/notes")
    def create_note(payload: NoteCreateRequest, request: Request) -> dict[str, object]:
        current = _current_container(request)
        note = current.notes.create_note(payload.title, payload.content)
        if payload.workspace_id:
            current.assistant.workspace_service.link_note_to_active_workspace(
                session_id=payload.session_id,
                note_id=note.note_id,
                workspace_id=payload.workspace_id,
            )
        current.events.publish(
            level="INFO", source="api", message=f"Saved note '{note.title}'."
        )
        return note.to_dict()

    @app.get("/settings")
    def settings(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return current.config.to_dict()

    @app.get("/tools")
    def list_tools(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return {"tools": current.tool_registry.metadata()}

    @app.post("/lifecycle/shell")
    def report_shell_presence(
        payload: ShellPresenceRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        update = ShellPresenceUpdate.from_dict(payload.model_dump())
        if update.event == "detach":
            current.lifecycle.record_shell_detached(pid=update.pid)
        else:
            current.lifecycle.record_shell_presence(update)
        return {"runtime": current.lifecycle.status_snapshot().get("runtime", {})}

    @app.post("/lifecycle/startup")
    def update_startup_registration(
        payload: StartupPolicyMutationRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        policy = current.lifecycle.configure_startup_policy(
            startup_enabled=payload.startup_enabled,
            start_core_with_windows=payload.start_core_with_windows,
            start_shell_with_windows=payload.start_shell_with_windows,
            tray_only_startup=payload.tray_only_startup,
            ghost_ready_on_startup=payload.ghost_ready_on_startup,
        )
        return {
            "startup_policy": policy.to_dict(),
            "bootstrap": current.lifecycle.status_snapshot().get("bootstrap", {}),
        }

    @app.post("/lifecycle/resolution/plan")
    def prepare_lifecycle_resolution_plan(request: Request) -> dict[str, object]:
        current = _current_container(request)
        plan = current.lifecycle.prepare_resolution_plan()
        return {
            "resolution_plan": plan.to_dict(),
            "bootstrap": current.lifecycle.status_snapshot().get("bootstrap", {}),
        }

    @app.post("/lifecycle/resolution")
    def execute_lifecycle_resolution(
        payload: LifecycleResolutionRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        resolution = current.lifecycle.resolve_lifecycle_hold(
            plan_id=payload.plan_id,
            resolution_kind=payload.resolution_kind,
            confirmation_kind=payload.confirmation_kind,
            confirmed_summary=payload.confirmed_summary,
        )
        return {
            "resolution_state": resolution.to_dict(),
            "bootstrap": current.lifecycle.status_snapshot().get("bootstrap", {}),
            "migration": current.lifecycle.status_snapshot().get("migration", {}),
        }

    @app.post("/lifecycle/cleanup/plan")
    def prepare_lifecycle_cleanup_plan(
        payload: CleanupExecutionRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        plan = current.lifecycle.prepare_cleanup_plan(
            remove_startup_registration=payload.remove_startup_registration,
            remove_logs=payload.remove_logs,
            remove_caches=payload.remove_caches,
            remove_durable_state=payload.remove_durable_state,
        )
        return {
            "destructive_cleanup_plan": plan.to_dict(),
            "uninstall_plan": current.lifecycle.status_snapshot().get(
                "uninstall_plan", {}
            ),
        }

    @app.post("/lifecycle/cleanup")
    def execute_lifecycle_cleanup(
        payload: CleanupExecutionRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        cleanup = current.lifecycle.execute_cleanup(
            remove_startup_registration=payload.remove_startup_registration,
            remove_logs=payload.remove_logs,
            remove_caches=payload.remove_caches,
            remove_durable_state=payload.remove_durable_state,
            destructive_confirmation_received=payload.destructive_confirmation_received,
            destructive_confirmation=(
                payload.destructive_confirmation.model_dump()
                if payload.destructive_confirmation is not None
                else None
            ),
        )
        return {
            "cleanup_execution": cleanup.to_dict(),
            "uninstall_plan": current.lifecycle.status_snapshot().get(
                "uninstall_plan", {}
            ),
        }

    @app.post("/lifecycle/core/shutdown")
    def shutdown_core(request: Request) -> dict[str, object]:
        current = _current_container(request)
        current.events.publish(
            level="WARNING",
            source="api",
            message="Operator requested a backend shutdown from the shell tray.",
        )
        _schedule_process_shutdown()
        return {
            "status": "shutting_down",
            "pid": os.getpid(),
            "runtime": current.lifecycle.status_snapshot().get("runtime", {}),
        }

    def _voice_action_response(
        action: str, result: object, current: CoreContainer
    ) -> dict[str, object]:
        result_payload = result.to_dict() if hasattr(result, "to_dict") else result
        return {
            "action": action,
            "result": result_payload
            if isinstance(result_payload, dict)
            else {"ok": False, "status": "failed"},
            "voice": current.voice.status_snapshot(),
        }

    @app.get("/voice/readiness")
    async def voice_readiness(request: Request) -> dict[str, object]:
        current = _current_container(request)
        status = current.voice.status_snapshot()
        return {
            "action": "voice.getReadinessReport",
            "readiness": current.voice.readiness_report().to_dict(),
            "pipeline_summary": current.voice.pipeline_stage_summary().to_dict(),
            "voice": status,
        }

    @app.get("/voice/pipeline")
    async def voice_pipeline(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return {
            "action": "voice.getLastPipelineSummary",
            "pipeline_summary": current.voice.pipeline_stage_summary().to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/capture/start")
    async def start_voice_capture(
        payload: VoiceCaptureControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.start_push_to_talk_capture(
            session_id=payload.session_id,
            metadata=payload.metadata,
        )
        return _voice_action_response("voice.startPushToTalkCapture", result, current)

    @app.post("/voice/capture/stop")
    async def stop_voice_capture(
        payload: VoiceCaptureControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.stop_push_to_talk_capture(
            payload.capture_id,
            reason=payload.reason or "user_released",
        )
        return _voice_action_response("voice.stopPushToTalkCapture", result, current)

    @app.post("/voice/capture/cancel")
    async def cancel_voice_capture(
        payload: VoiceCaptureControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.cancel_capture(
            payload.capture_id,
            reason=payload.reason or "user_cancelled",
        )
        return _voice_action_response("voice.cancelCapture", result, current)

    @app.post("/voice/capture/submit")
    async def submit_captured_audio_turn(
        payload: VoiceCaptureControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        capture_result = current.voice.last_capture_result
        if capture_result is None:
            return _voice_action_response(
                "voice.submitCapturedAudioTurn",
                {
                    "ok": False,
                    "status": "blocked",
                    "error_code": "no_completed_capture",
                    "error_message": "No completed capture is available to submit.",
                },
                current,
            )
        result = await current.voice.submit_captured_audio_turn(
            capture_result,
            mode=payload.mode or "ghost",
            session_id=payload.session_id,
            metadata=payload.metadata,
        )
        return _voice_action_response("voice.submitCapturedAudioTurn", result, current)

    @app.post("/voice/capture/turn")
    async def capture_and_submit_voice_turn(
        payload: VoiceCaptureControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.capture_and_submit_turn(
            payload.capture_id,
            mode=payload.mode or "ghost",
            synthesize_response=payload.synthesize_response,
            play_response=payload.play_response,
        )
        return _voice_action_response("voice.captureAndSubmitTurn", result, current)

    @app.post("/voice/playback/stop")
    async def stop_voice_playback(
        payload: VoicePlaybackControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.stop_playback(
            payload.playback_id,
            reason=payload.reason or "user_requested",
        )
        return _voice_action_response("voice.stopPlayback", result, current)

    @app.get("/snapshot")
    def snapshot(
        request: Request,
        session_id: str = "default",
        event_since_id: int = 0,
        event_limit: int = 100,
        job_limit: int = 50,
        note_limit: int = 50,
        history_limit: int = 100,
    ) -> dict[str, object]:
        current = _current_container(request)
        return {
            "health": _health_payload(request),
            "status": current.status_snapshot(),
            "jobs": current.jobs.list_jobs(limit=job_limit),
            "events": current.events.recent(since_id=event_since_id, limit=event_limit),
            "notes": [
                note.to_dict() for note in current.notes.list_notes(limit=note_limit)
            ],
            "settings": current.config.to_dict(),
            "history": [
                message.to_dict()
                for message in current.conversations.list_messages(
                    session_id=session_id, limit=history_limit
                )
            ],
            "tools": current.tool_registry.metadata(),
            "active_workspace": current.assistant.workspace_service.active_workspace_summary(
                session_id
            ),
            "active_request_state": current.assistant.session_state.get_active_request_state(
                session_id
            ),
            "recent_context_resolutions": current.assistant.session_state.get_recent_context_resolutions(
                session_id
            ),
            "active_task": current.task_service.active_task_summary(session_id),
        }

    return app
