from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = "default"
    surface_mode: str = "ghost"
    active_module: str = "chartroom"
    workspace_context: dict[str, Any] = Field(default_factory=dict)


class NoteCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)


class EventsResponse(BaseModel):
    events: list[dict[str, Any]]


class JobsResponse(BaseModel):
    jobs: list[dict[str, Any]]


class NotesResponse(BaseModel):
    notes: list[dict[str, Any]]
