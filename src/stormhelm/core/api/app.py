from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from stormhelm.config.models import AppConfig
from stormhelm.core.api.schemas import ChatRequest, EventsResponse, JobsResponse, NoteCreateRequest, NotesResponse
from stormhelm.core.container import CoreContainer, build_container
from stormhelm.version import __version__


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
        return await current.assistant.handle_message(
            payload.message,
            payload.session_id,
            surface_mode=payload.surface_mode,
            active_module=payload.active_module,
            workspace_context=payload.workspace_context,
            input_context=payload.input_context,
        )

    @app.get("/chat/history")
    def chat_history(request: Request, session_id: str = "default", limit: int = 100) -> dict[str, object]:
        current = _current_container(request)
        items = [message.to_dict() for message in current.conversations.list_messages(session_id=session_id, limit=limit)]
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
    def list_events(request: Request, since_id: int = 0, limit: int = 100) -> dict[str, object]:
        current = _current_container(request)
        return {"events": current.events.recent(since_id=since_id, limit=limit)}

    @app.get("/notes", response_model=NotesResponse)
    def list_notes(request: Request, limit: int = 50) -> dict[str, object]:
        current = _current_container(request)
        return {"notes": [note.to_dict() for note in current.notes.list_notes(limit=limit)]}

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
        current.events.publish(level="INFO", source="api", message=f"Saved note '{note.title}'.")
        return note.to_dict()

    @app.get("/settings")
    def settings(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return current.config.to_dict()

    @app.get("/tools")
    def list_tools(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return {"tools": current.tool_registry.metadata()}

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
            "notes": [note.to_dict() for note in current.notes.list_notes(limit=note_limit)],
            "settings": current.config.to_dict(),
            "history": [
                message.to_dict()
                for message in current.conversations.list_messages(session_id=session_id, limit=history_limit)
            ],
            "tools": current.tool_registry.metadata(),
            "active_workspace": current.assistant.workspace_service.active_workspace_summary(session_id),
            "active_request_state": current.assistant.session_state.get_active_request_state(session_id),
            "recent_context_resolutions": current.assistant.session_state.get_recent_context_resolutions(session_id),
        }

    return app
