from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import threading
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

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
    VoiceInterruptionControlRequest,
    VoicePlaybackControlRequest,
    VoiceRealtimeControlRequest,
    VoiceSpokenConfirmationControlRequest,
    VoiceWakeControlRequest,
)
from stormhelm.core.container import CoreContainer, build_container
from stormhelm.core.latency import attach_latency_metadata
from stormhelm.core.latency import build_partial_response_posture
from stormhelm.core.latency import classify_route_latency_policy
from stormhelm.core.voice import VoiceInterruptionRequest
from stormhelm.core.voice import VoiceSpokenConfirmationRequest
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
    voice_output_tasks: set[asyncio.Task[None]] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container
        await container.start()
        _remember_runtime_voice_gate_snapshot(container, publish=True)
        try:
            yield
        finally:
            for task in list(voice_output_tasks):
                task.cancel()
            if voice_output_tasks:
                await asyncio.gather(*voice_output_tasks, return_exceptions=True)
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
            "runtime_identity": {
                "pid": os.getpid(),
                "python_executable": sys.executable,
                "python_prefix": sys.prefix,
                "python_base_prefix": sys.base_prefix,
                "using_virtualenv": sys.prefix != sys.base_prefix,
                "working_directory": os.getcwd(),
                "project_root": str(current.config.project_root),
            },
        }

    def _payload_bytes(payload: object) -> int:
        try:
            return len(json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"))
        except (TypeError, ValueError):
            return 0

    def _largest_sections(payload: dict[str, object], *, limit: int = 8) -> list[dict[str, object]]:
        sections: list[dict[str, object]] = []
        for key, value in payload.items():
            section = str(key)
            if section.startswith("snapshot_") or section.startswith("status_"):
                continue
            sections.append({"section": section, "bytes": _payload_bytes(value)})
        sections.sort(key=lambda item: int(item.get("bytes") or 0), reverse=True)
        return sections[: max(0, limit)]

    def _finish_status_instrumentation(
        payload: dict[str, object],
        *,
        started_at: float,
        profile: str,
        deferred_sections: list[str] | tuple[str, ...] = (),
    ) -> dict[str, object]:
        payload["status_profile"] = str(payload.get("status_profile") or profile)
        payload.setdefault("status_sections_ms", {})
        existing_deferred = payload.get("status_deferred_sections")
        if isinstance(existing_deferred, list):
            deferred = [str(item) for item in existing_deferred]
        else:
            deferred = []
        for section in deferred_sections:
            if section not in deferred:
                deferred.append(str(section))
        payload["status_deferred_sections"] = deferred
        payload["status_total_ms"] = round((perf_counter() - started_at) * 1000, 3)
        payload["status_payload_bytes"] = 0
        payload["status_payload_bytes"] = _payload_bytes(payload)
        payload["status_payload_bytes"] = _payload_bytes(payload)
        return payload

    def _finish_snapshot_instrumentation(
        payload: dict[str, object],
        *,
        started_at: float,
        profile: str,
        deferred_sections: list[str] | tuple[str, ...] = (),
    ) -> dict[str, object]:
        payload["snapshot_profile"] = str(payload.get("snapshot_profile") or profile)
        existing_deferred = payload.get("snapshot_deferred_sections")
        if isinstance(existing_deferred, list):
            deferred = [str(item) for item in existing_deferred]
        else:
            deferred = []
        for section in deferred_sections:
            if section not in deferred:
                deferred.append(str(section))
        payload["snapshot_deferred_sections"] = deferred
        payload["snapshot_largest_sections"] = _largest_sections(payload)
        payload["snapshot_total_ms"] = round((perf_counter() - started_at) * 1000, 3)
        payload["snapshot_payload_bytes"] = 0
        payload["snapshot_payload_bytes"] = _payload_bytes(payload)
        payload["snapshot_payload_bytes"] = _payload_bytes(payload)
        return payload

    def _assistant_voice_text(result: dict[str, object]) -> str:
        assistant_message = (
            result.get("assistant_message") if isinstance(result, dict) else {}
        )
        if not isinstance(assistant_message, dict):
            return ""
        metadata = assistant_message.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        for candidate in (
            metadata.get("spoken_response"),
            metadata.get("micro_response"),
            assistant_message.get("content"),
        ):
            text = str(candidate or "").strip()
            if text:
                return text
        return ""

    def _runtime_voice_gate_snapshot(current: CoreContainer) -> dict[str, object]:
        voice_snapshot = getattr(current.voice, "runtime_voice_gate_snapshot", None)
        if callable(voice_snapshot):
            try:
                snapshot = voice_snapshot()
                if isinstance(snapshot, dict):
                    return dict(snapshot)
            except TypeError:
                pass
        voice_config = current.voice.config
        current_config = getattr(current, "config", None)
        openai_config = getattr(current_config, "openai", None)
        env_path = getattr(current_config, "project_root", None)
        env_loaded = bool(env_path and (env_path / ".env").exists())
        return {
            "env_loaded": env_loaded,
            "openai_key_present": bool(getattr(openai_config, "api_key", None)),
            "openai_enabled": bool(getattr(openai_config, "enabled", False)),
            "voice_enabled": bool(voice_config.enabled),
            "voice_mode": str(voice_config.mode or "").strip().lower(),
            "spoken_responses_enabled": bool(voice_config.spoken_responses_enabled),
            "typed_response_speech_enabled": bool(
                voice_config.enabled
                and voice_config.spoken_responses_enabled
                and voice_config.playback.enabled
            ),
            "playback_enabled": bool(voice_config.playback.enabled),
            "playback_provider": str(voice_config.playback.provider or "").strip().lower(),
            "streaming_playback_enabled": bool(voice_config.playback.streaming_enabled),
            "openai_stream_tts_outputs": bool(voice_config.openai.stream_tts_outputs),
            "live_format": str(voice_config.openai.tts_live_format or "").strip().lower(),
            "dev_playback_allowed": bool(voice_config.playback.allow_dev_playback),
            "debug_mock_provider": bool(voice_config.debug_mock_provider),
            "raw_secret_logged": False,
            "raw_audio_logged": False,
        }

    def _remember_runtime_voice_gate_snapshot(
        current: CoreContainer,
        *,
        publish: bool = False,
    ) -> dict[str, object]:
        snapshot = _runtime_voice_gate_snapshot(current)
        remember = getattr(current.voice, "remember_runtime_gate_snapshot", None)
        if callable(remember):
            remember(snapshot)
        if publish:
            current.events.publish(
                event_family="voice",
                event_type="voice.runtime_gate_snapshot",
                severity="debug",
                subsystem="voice",
                message="VOICE_RUNTIME_GATE_SNAPSHOT",
                payload=dict(snapshot),
            )
        return snapshot

    def _voice_output_disabled_reasons(
        current: CoreContainer,
        gate_snapshot: dict[str, object] | None = None,
    ) -> list[str]:
        gate = gate_snapshot or _runtime_voice_gate_snapshot(current)
        reasons: list[str] = []
        if not gate.get("voice_enabled"):
            reasons.append("voice_disabled")
        if str(gate.get("voice_mode") or "").strip().lower() == "disabled":
            reasons.append("voice_mode_disabled")
        if not gate.get("spoken_responses_enabled"):
            reasons.append("spoken_responses_disabled")
        if not gate.get("playback_enabled"):
            reasons.append("playback_disabled")
        if not gate.get("debug_mock_provider"):
            if not gate.get("openai_enabled"):
                reasons.append("openai_disabled")
            if not gate.get("openai_key_present"):
                reasons.append("openai_key_missing")
        if getattr(current.voice, "spoken_output_muted", False):
            reasons.append("spoken_output_muted")
        return reasons

    def _voice_output_enabled(
        current: CoreContainer,
        gate_snapshot: dict[str, object] | None = None,
    ) -> bool:
        return not _voice_output_disabled_reasons(current, gate_snapshot)

    def _voice_speak_decision(
        current: CoreContainer,
        result: dict[str, object],
        *,
        session_id: str,
        surface_mode: str,
        active_module: str,
        gate_snapshot: dict[str, object],
        text: str,
        skipped_reason: str | None,
        disabled_reasons: list[str] | None = None,
        voice_service_called: bool = False,
        voice_service_status: str | None = None,
        voice_service_error_code: str | None = None,
        user_heard_claimed: bool = False,
    ) -> dict[str, object]:
        assistant_message = (
            result.get("assistant_message") if isinstance(result, dict) else {}
        )
        metadata = (
            assistant_message.get("metadata")
            if isinstance(assistant_message, dict)
            and isinstance(assistant_message.get("metadata"), dict)
            else {}
        )
        latency_trace = (
            metadata.get("latency_trace") if isinstance(metadata, dict) else {}
        )
        request_id = (
            latency_trace.get("request_id")
            if isinstance(latency_trace, dict)
            else None
        )
        response_text = (
            assistant_message.get("content") if isinstance(assistant_message, dict) else ""
        )
        speakable = bool(text and skipped_reason is None)
        return {
            "request_id": request_id,
            "session_id": session_id,
            "prompt_source": "typed_ui",
            "surface_mode": surface_mode,
            "active_module": active_module,
            "response_has_text": bool(str(response_text or "").strip()),
            "response_text_chars": len(str(response_text or "")),
            "approved_spoken_text_present": bool(text),
            "approved_spoken_text_chars": len(text),
            "speakable": speakable,
            "skipped_reason": skipped_reason,
            "disabled_reasons": list(disabled_reasons or []),
            "voice_service_called": bool(voice_service_called),
            "voice_service_status": voice_service_status,
            "voice_service_error_code": voice_service_error_code,
            "playback_provider": gate_snapshot.get("playback_provider"),
            "streaming_requested": bool(
                gate_snapshot.get("openai_stream_tts_outputs")
                and gate_snapshot.get("streaming_playback_enabled")
            ),
            "openai_stream_tts_outputs": bool(gate_snapshot.get("openai_stream_tts_outputs")),
            "streaming_playback_enabled": bool(gate_snapshot.get("streaming_playback_enabled")),
            "live_format": gate_snapshot.get("live_format"),
            "user_heard_claimed": bool(user_heard_claimed),
            "raw_secret_logged": False,
            "raw_audio_logged": False,
        }

    def _voice_output_user_heard_claimed(
        current: CoreContainer,
        result_object: object | None = None,
    ) -> bool:
        playback_result = getattr(result_object, "playback_result", None)
        if bool(getattr(result_object, "user_heard_claimed", False)):
            return True
        if playback_result is not None and bool(
            getattr(playback_result, "user_heard_claimed", False)
        ):
            return True
        for attribute in (
            "last_live_playback_result",
            "last_playback_result",
            "last_live_playback_session",
        ):
            value = getattr(current.voice, attribute, None)
            if value is not None and bool(getattr(value, "user_heard_claimed", False)):
                return True
            metadata = getattr(value, "metadata", None)
            if isinstance(metadata, dict) and metadata.get("user_heard_claimed") is True:
                return True
        return False

    def _remember_voice_speak_decision(
        current: CoreContainer,
        decision: dict[str, object],
        *,
        severity: str = "debug",
    ) -> None:
        remember = getattr(current.voice, "remember_assistant_speak_decision", None)
        if callable(remember):
            remember(decision)
        current.events.publish(
            event_family="voice",
            event_type="voice.speak_decision",
            severity=severity,
            subsystem="voice",
            session_id=str(decision.get("session_id") or "default"),
            message="VOICE_SPEAK_DECISION",
            payload=dict(decision),
        )

    def _attach_voice_output_metadata(
        result: dict[str, object],
        *,
        scheduled: bool,
        decision: dict[str, object],
        mode: str,
        playback_requested: bool,
        streaming_requested: bool,
    ) -> None:
        assistant_message = result.get("assistant_message")
        if not isinstance(assistant_message, dict):
            return
        metadata = assistant_message.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            return
        metadata["voice_output"] = {
            "scheduled": scheduled,
            "source": "assistant_response",
            "mode": mode,
            "playback_requested": playback_requested,
            "streaming_requested": streaming_requested,
            "output_mode": "streaming" if streaming_requested else "buffered",
            "completion_claimed": False,
            "verification_claimed": False,
            "user_heard_claimed": bool(decision.get("user_heard_claimed")),
            "decision": dict(decision),
        }

    def _schedule_assistant_voice_output(
        current: CoreContainer,
        result: dict[str, object],
        *,
        session_id: str,
        surface_mode: str,
        active_module: str,
    ) -> None:
        gate_snapshot = _remember_runtime_voice_gate_snapshot(current)
        disabled_reasons = _voice_output_disabled_reasons(current, gate_snapshot)
        text = _assistant_voice_text(result)
        streaming_requested = bool(
            gate_snapshot.get("openai_stream_tts_outputs")
            and gate_snapshot.get("streaming_playback_enabled")
        )
        if disabled_reasons:
            decision = _voice_speak_decision(
                current,
                result,
                session_id=session_id,
                surface_mode=surface_mode,
                active_module=active_module,
                gate_snapshot=gate_snapshot,
                text=text,
                skipped_reason="voice_output_disabled",
                disabled_reasons=disabled_reasons,
            )
            _attach_voice_output_metadata(
                result,
                scheduled=False,
                decision=decision,
                mode=str(gate_snapshot.get("voice_mode") or current.voice.config.mode),
                playback_requested=False,
                streaming_requested=streaming_requested,
            )
            _remember_voice_speak_decision(current, decision)
            return
        if not text:
            decision = _voice_speak_decision(
                current,
                result,
                session_id=session_id,
                surface_mode=surface_mode,
                active_module=active_module,
                gate_snapshot=gate_snapshot,
                text=text,
                skipped_reason="empty_spoken_text",
            )
            _attach_voice_output_metadata(
                result,
                scheduled=False,
                decision=decision,
                mode=str(gate_snapshot.get("voice_mode") or current.voice.config.mode),
                playback_requested=False,
                streaming_requested=streaming_requested,
            )
            _remember_voice_speak_decision(current, decision)
            return

        decision = _voice_speak_decision(
            current,
            result,
            session_id=session_id,
            surface_mode=surface_mode,
            active_module=active_module,
            gate_snapshot=gate_snapshot,
            text=text,
            skipped_reason=None,
            voice_service_called=True,
        )
        _attach_voice_output_metadata(
            result,
            scheduled=True,
            decision=decision,
            mode=str(gate_snapshot.get("voice_mode") or current.voice.config.mode),
            playback_requested=True,
            streaming_requested=streaming_requested,
        )
        _remember_voice_speak_decision(current, decision)

        async def _run_voice_output() -> None:
            try:
                prewarm = getattr(current.voice, "prewarm_voice_output", None)
                if (
                    callable(prewarm)
                    and current.voice.config.playback.prewarm_enabled
                    and current.voice.config.spoken_responses_enabled
                ):
                    prewarm(session_id=session_id)
                if streaming_requested and callable(
                    getattr(current.voice, "stream_core_approved_spoken_text", None)
                ):
                    streaming_result = await current.voice.stream_core_approved_spoken_text(
                        text,
                        speak_allowed=True,
                        source="assistant_response",
                        persona_mode=surface_mode or "ghost",
                        session_id=session_id,
                        metadata={
                            "active_module": active_module,
                            "assistant_response_voice_output": True,
                            "voice_stream_used_by_normal_path": True,
                            "prompt_source": "typed_ui",
                        },
                    )
                    result_decision = _voice_speak_decision(
                        current,
                        result,
                        session_id=session_id,
                        surface_mode=surface_mode,
                        active_module=active_module,
                        gate_snapshot=gate_snapshot,
                        text=text,
                        skipped_reason=None,
                        voice_service_called=True,
                        voice_service_status=getattr(streaming_result, "status", None),
                        voice_service_error_code=getattr(
                            streaming_result, "error_code", None
                        ),
                        user_heard_claimed=_voice_output_user_heard_claimed(
                            current,
                            streaming_result,
                        ),
                    )
                    _remember_voice_speak_decision(
                        current,
                        result_decision,
                        severity="info"
                        if result_decision.get("user_heard_claimed")
                        else "debug",
                    )
                    return
                synthesis = await current.voice.synthesize_speech_text(
                    text,
                    source="assistant_response",
                    persona_mode=surface_mode or "ghost",
                    session_id=session_id,
                    metadata={
                        "active_module": active_module,
                        "assistant_response_voice_output": True,
                        "prompt_source": "typed_ui",
                    },
                )
                if synthesis.ok:
                    playback = await current.voice.play_speech_output(
                        synthesis,
                        session_id=session_id,
                        metadata={
                            "active_module": active_module,
                            "assistant_response_voice_output": True,
                            "prompt_source": "typed_ui",
                        },
                    )
                    result_decision = _voice_speak_decision(
                        current,
                        result,
                        session_id=session_id,
                        surface_mode=surface_mode,
                        active_module=active_module,
                        gate_snapshot=gate_snapshot,
                        text=text,
                        skipped_reason=None,
                        voice_service_called=True,
                        voice_service_status=getattr(playback, "status", None),
                        voice_service_error_code=getattr(playback, "error_code", None),
                        user_heard_claimed=_voice_output_user_heard_claimed(
                            current,
                            playback,
                        ),
                    )
                    _remember_voice_speak_decision(current, result_decision)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failed_decision = _voice_speak_decision(
                    current,
                    result,
                    session_id=session_id,
                    surface_mode=surface_mode,
                    active_module=active_module,
                    gate_snapshot=gate_snapshot,
                    text=text,
                    skipped_reason=None,
                    voice_service_called=True,
                    voice_service_status="failed",
                    voice_service_error_code="assistant_voice_output_failed",
                    user_heard_claimed=False,
                )
                _remember_voice_speak_decision(current, failed_decision, severity="error")
                current.events.publish(
                    event_family="voice",
                    event_type="voice.assistant_output_failed",
                    severity="error",
                    subsystem="voice",
                    session_id=session_id,
                    message="Assistant response voice output failed.",
                    payload={
                        "source": "assistant_response",
                        "error_code": "assistant_voice_output_failed",
                        "error_message": str(error),
                        "raw_audio_present": False,
                        "user_heard_claimed": False,
                    },
                )

        def _run_voice_output_in_thread() -> None:
            asyncio.run(_run_voice_output())

        task = asyncio.create_task(asyncio.to_thread(_run_voice_output_in_thread))
        voice_output_tasks.add(task)
        task.add_done_callback(voice_output_tasks.discard)

    @app.get("/health")
    def health(request: Request) -> dict[str, object]:
        return _health_payload(request)

    @app.get("/status")
    def status(request: Request, detail: str = "") -> dict[str, object]:
        status_started = perf_counter()
        current = _current_container(request)
        if str(detail or "").strip().lower() in {"full", "detail", "debug"}:
            snapshot = current.status_snapshot()
            snapshot.setdefault("status_profile", "full_status")
            return _finish_status_instrumentation(
                snapshot,
                started_at=status_started,
                profile="full_status",
            )
        fast_status = getattr(current, "status_snapshot_fast", None)
        if callable(fast_status):
            snapshot = fast_status()
            return _finish_status_instrumentation(
                snapshot,
                started_at=status_started,
                profile="fast_status",
                deferred_sections=(
                    "bridge_authority",
                    "workspace",
                    "active_task",
                    "active_request_state",
                    "system_detail",
                    "deck_detail",
                ),
            )
        snapshot = current.status_snapshot()
        return _finish_status_instrumentation(
            snapshot,
            started_at=status_started,
            profile="full_status",
        )

    @app.post("/chat/send")
    async def send_chat(payload: ChatRequest, request: Request) -> Response:
        current = _current_container(request)
        endpoint_started = perf_counter()
        result = await current.assistant.handle_message(
            payload.message,
            payload.session_id,
            surface_mode=payload.surface_mode,
            active_module=payload.active_module,
            workspace_context=payload.workspace_context,
            input_context=payload.input_context,
            response_profile=payload.response_profile,
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
            stage_timings["total_latency_ms"] = round(
                endpoint_dispatch_ms + stage_timings["endpoint_return_to_asgi_ms"],
                3,
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
            attach_latency_metadata(
                metadata,
                stage_timings_ms=stage_timings,
                request_id=(
                    metadata.get("latency_trace", {}).get("request_id")
                    if isinstance(metadata.get("latency_trace"), dict)
                    else None
                ),
                session_id=payload.session_id,
                surface_mode=payload.surface_mode,
                active_module=payload.active_module,
                job_count=len(result.get("jobs") or []) if isinstance(result.get("jobs"), list) else None,
            )
        if isinstance(result, dict):
            _schedule_assistant_voice_output(
                current,
                result,
                session_id=payload.session_id,
                surface_mode=payload.surface_mode,
                active_module=payload.active_module,
            )
        return _compact_json_response(result)

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

    def _compact_json_response(payload: object) -> Response:
        body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        return Response(content=body, media_type="application/json")

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
        normalized_result = (
            result_payload
            if isinstance(result_payload, dict)
            else {"ok": False, "status": "failed"}
        )
        voice_status = current.voice.status_snapshot()
        fail_fast_reason = _voice_fail_fast_reason(action, normalized_result, voice_status)
        result_state = str(
            normalized_result.get("status")
            or normalized_result.get("state")
            or ("blocked" if fail_fast_reason else "completed_unverified")
        )
        policy = classify_route_latency_policy(
            route_family="voice_control",
            subsystem="voice",
            request_kind=action,
            surface_mode="voice",
            result_state=result_state,
            fail_fast_reason=fail_fast_reason,
        )
        partial_response = build_partial_response_posture(
            route_family="voice_control",
            subsystem="voice",
            assistant_message=str(
                normalized_result.get("message")
                or normalized_result.get("error_message")
                or ""
            ),
            result_state=result_state,
            verification_state="unverified",
            latency_trace_id="",
            policy=policy,
            budget_exceeded=False,
            async_continuation=False,
            continue_reason=fail_fast_reason,
        )
        return {
            "action": action,
            "result": normalized_result,
            "voice": voice_status,
            "latency_policy": policy.to_dict(),
            "budget_result": policy.budget.evaluate(0).to_dict(),
            "execution_mode": policy.execution_mode.value,
            "partial_response": partial_response,
            "partial_response_returned": bool(partial_response.get("partial_response_returned")),
            "async_expected": bool(policy.async_expected),
            "fail_fast_reason": fail_fast_reason,
        }

    def _voice_fail_fast_reason(
        action: str, result_payload: dict[str, object], voice_status: dict[str, object]
    ) -> str:
        status = str(result_payload.get("status") or result_payload.get("state") or "").lower()
        ok = result_payload.get("ok")
        if ok is True and status not in {"blocked", "failed", "unavailable"}:
            return ""
        action_key = action.lower()
        if any(part in action_key for part in ("playback", "speaking", "spoken", "output")):
            playback = voice_status.get("playback") if isinstance(voice_status.get("playback"), dict) else {}
            if playback and playback.get("enabled") is False:
                return "playback_disabled"
            if playback and playback.get("available") is False:
                return str(playback.get("unavailable_reason") or "playback_unavailable")
        provider = voice_status.get("provider") if isinstance(voice_status.get("provider"), dict) else {}
        availability = provider.get("availability") if isinstance(provider.get("availability"), dict) else {}
        if availability and availability.get("available") is False:
            return str(availability.get("unavailable_reason") or "voice_unavailable")
        if status in {"blocked", "failed", "unavailable"}:
            return str(
                result_payload.get("error_code")
                or result_payload.get("unavailable_reason")
                or result_payload.get("reason")
                or "voice_unavailable"
            )
        return ""

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

    @app.get("/voice/confirmation/status")
    async def voice_spoken_confirmation_status(request: Request) -> dict[str, object]:
        current = _current_container(request)
        status = current.voice.status_snapshot()
        return {
            "action": "voice.getSpokenConfirmationStatus",
            "spoken_confirmation": status.get("spoken_confirmation", {}),
            "voice": status,
        }

    @app.post("/voice/confirmation/submit")
    async def submit_voice_spoken_confirmation(
        payload: VoiceSpokenConfirmationControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript=payload.transcript,
                normalized_phrase=payload.normalized_phrase,
                session_id=payload.session_id,
                turn_id=payload.turn_id,
                source=payload.source or "api",
                pending_confirmation_id=payload.pending_confirmation_id,
                task_id=payload.task_id,
                route_family=payload.route_family,
                metadata=payload.metadata,
            )
        )
        return _voice_action_response("voice.handleSpokenConfirmation", result, current)

    @app.get("/voice/wake/readiness")
    async def voice_wake_readiness(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return {
            "action": "voice.getWakeReadiness",
            "wake_readiness": current.voice.wake_readiness_report().to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.get("/voice/vad/readiness")
    async def voice_vad_readiness(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return {
            "action": "voice.getVADReadiness",
            "vad_readiness": current.voice.vad_readiness_report().to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.get("/voice/realtime/readiness")
    async def voice_realtime_readiness(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return {
            "action": "voice.getRealtimeReadiness",
            "realtime_readiness": current.voice.realtime_readiness_report().to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/realtime/start")
    async def start_voice_realtime_session(
        payload: VoiceRealtimeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.start_realtime_session(
            session_id=payload.session_id,
            source=payload.source,
            listen_window_id=payload.listen_window_id,
            capture_id=payload.capture_id,
        )
        return {
            "action": "voice.startRealtimeSession",
            "realtime_session": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/realtime/stop")
    async def stop_voice_realtime_session(
        payload: VoiceRealtimeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.close_realtime_session(
            payload.realtime_session_id,
            reason=payload.reason or "closed",
        )
        return {
            "action": "voice.stopRealtimeSession",
            "realtime_session": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/realtime/partial")
    async def simulate_voice_realtime_partial(
        payload: VoiceRealtimeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.simulate_realtime_partial_transcript(
            payload.transcript,
            realtime_session_id=payload.realtime_session_id,
            listen_window_id=payload.listen_window_id,
            capture_id=payload.capture_id,
        )
        return {
            "action": "voice.simulateRealtimePartialTranscript",
            "realtime_transcript_event": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/realtime/final")
    async def simulate_voice_realtime_final(
        payload: VoiceRealtimeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.simulate_realtime_final_transcript(
            payload.transcript,
            realtime_session_id=payload.realtime_session_id,
            listen_window_id=payload.listen_window_id,
            capture_id=payload.capture_id,
            mode=payload.mode or "ghost",
            metadata=payload.metadata,
        )
        return {
            "action": "voice.simulateRealtimeFinalTranscript",
            "realtime_turn_result": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/vad/speech-started")
    async def simulate_voice_speech_started(
        payload: VoiceCaptureControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.simulate_speech_started(
            capture_id=payload.capture_id
        )
        return {
            "action": "voice.simulateSpeechStarted",
            "activity_event": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/vad/speech-stopped")
    async def simulate_voice_speech_stopped(
        payload: VoiceCaptureControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.simulate_speech_stopped(
            capture_id=payload.capture_id
        )
        return {
            "action": "voice.simulateSpeechStopped",
            "activity_event": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.get("/voice/wake/ghost")
    async def voice_wake_ghost(request: Request) -> dict[str, object]:
        current = _current_container(request)
        return {
            "action": "voice.getWakeGhost",
            "wake_ghost": current.voice.status_snapshot()["wake_ghost"],
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/wake/ghost/cancel")
    async def cancel_voice_wake_ghost(
        payload: VoiceWakeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.cancel_wake_ghost(
            payload.wake_session_id,
            reason=payload.reason or "operator_dismissed",
        )
        return {
            "action": "voice.cancelWakeGhost",
            "wake_ghost": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/wake/loop")
    async def run_voice_wake_supervised_loop(
        payload: VoiceWakeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.run_wake_supervised_voice_loop(
            payload.wake_session_id,
            mode=payload.mode or "ghost",
            synthesize_response=payload.synthesize_response,
            play_response=payload.play_response,
            finalize_with_vad=payload.finalize_with_vad,
        )
        return {
            "action": "voice.runWakeSupervisedLoop",
            "wake_supervised_loop": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/wake/start")
    async def start_voice_wake_monitoring(
        payload: VoiceWakeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.start_wake_monitoring(
            session_id=payload.session_id
        )
        return _voice_action_response("voice.startWakeMonitoring", result, current)

    @app.post("/voice/wake/stop")
    async def stop_voice_wake_monitoring(
        payload: VoiceWakeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.stop_wake_monitoring(session_id=payload.session_id)
        return _voice_action_response("voice.stopWakeMonitoring", result, current)

    @app.post("/voice/wake/simulate")
    async def simulate_voice_wake(
        payload: VoiceWakeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.simulate_wake_event(
            session_id=payload.session_id,
            confidence=payload.confidence,
            source=payload.source or "mock",
        )
        return {
            "action": "voice.simulateWake",
            "wake_event": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/wake/accept")
    async def accept_voice_wake(
        payload: VoiceWakeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.accept_wake_event(
            payload.wake_event_id,
            session_id=payload.session_id,
        )
        return {
            "action": "voice.acceptWake",
            "wake_session": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/wake/reject")
    async def reject_voice_wake(
        payload: VoiceWakeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.reject_wake_event(
            payload.wake_event_id,
            reason=payload.reason or "false_positive",
        )
        return {
            "action": "voice.rejectWake",
            "wake_event": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/wake/cancel")
    async def cancel_voice_wake_session(
        payload: VoiceWakeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.cancel_wake_session(
            payload.wake_session_id,
            reason=payload.reason or "user_cancelled",
        )
        return {
            "action": "voice.cancelWakeSession",
            "wake_session": result.to_dict(),
            "voice": current.voice.status_snapshot(),
        }

    @app.post("/voice/wake/expire")
    async def expire_voice_wake_session(
        payload: VoiceWakeControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.expire_wake_session(payload.wake_session_id)
        return {
            "action": "voice.expireWakeSession",
            "wake_session": result.to_dict(),
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

    @app.post("/voice/capture/listen-turn")
    async def listen_and_submit_voice_turn(
        payload: VoiceCaptureControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.listen_and_submit_turn(
            session_id=payload.session_id,
            mode=payload.mode or "ghost",
            synthesize_response=payload.synthesize_response,
            play_response=payload.play_response,
            metadata=payload.metadata,
        )
        return _voice_action_response("voice.listenAndSubmitTurn", result, current)

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

    @app.post("/voice/diagnostics/local-pcm-fixture")
    async def play_voice_local_pcm_fixture(
        payload: dict[str, object], request: Request
    ) -> dict[str, object]:
        if str(os.environ.get("STORMHELM_VOICE_AR1_LIVE_DIAG", "")).lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            raise HTTPException(
                status_code=403,
                detail="Voice AR1 live diagnostics are disabled.",
            )
        current = _current_container(request)
        result = current.voice.run_local_pcm_voice_fixture(
            session_id=str(payload.get("session_id") or "voice-ar1-local-fixture"),
            turn_id=str(payload.get("turn_id") or "") or None,
            prompt=str(payload.get("prompt") or ""),
        )
        return dict(result)

    @app.post("/voice/output/stop-speaking")
    async def stop_voice_speaking(
        payload: VoiceInterruptionControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.stop_speaking(
            session_id=payload.session_id,
            playback_id=payload.playback_id,
            reason=payload.reason or "user_requested",
        )
        return _voice_action_response("voice.stopSpeaking", result, current)

    @app.post("/voice/output/suppress-current-response")
    async def suppress_current_voice_response(
        payload: VoiceInterruptionControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.suppress_current_response(
            session_id=payload.session_id,
            turn_id=payload.turn_id,
            reason=payload.reason or "user_requested",
        )
        return _voice_action_response("voice.suppressCurrentResponse", result, current)

    @app.post("/voice/output/mute")
    async def mute_spoken_voice_output(
        payload: VoiceInterruptionControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.set_spoken_output_muted(
            True,
            session_id=payload.session_id,
            scope=payload.scope or "session",
            reason=payload.reason or "user_requested",
        )
        return _voice_action_response("voice.muteSpokenResponses", result, current)

    @app.post("/voice/output/unmute")
    async def unmute_spoken_voice_output(
        payload: VoiceInterruptionControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.set_spoken_output_muted(
            False,
            session_id=payload.session_id,
            scope=payload.scope or "session",
            reason=payload.reason or "user_requested",
        )
        return _voice_action_response("voice.unmuteSpokenResponses", result, current)

    @app.post("/voice/interruption/handle")
    async def handle_voice_interruption(
        payload: VoiceInterruptionControlRequest, request: Request
    ) -> dict[str, object]:
        current = _current_container(request)
        result = await current.voice.handle_voice_interruption(
            VoiceInterruptionRequest(
                intent=payload.intent or "unknown",
                transcript=payload.transcript,
                normalized_phrase=payload.normalized_phrase,
                source="api",
                session_id=payload.session_id,
                turn_id=payload.turn_id,
                playback_id=payload.playback_id,
                capture_id=payload.capture_id,
                listen_window_id=payload.listen_window_id,
                realtime_session_id=payload.realtime_session_id,
                pending_confirmation_id=payload.pending_confirmation_id,
                active_loop_id=payload.active_loop_id,
                reason=payload.reason or "user_requested",
                muted_scope=payload.scope or "session",
                metadata=payload.metadata,
            )
        )
        return _voice_action_response("voice.handleInterruption", result, current)

    def _limit_snapshot_text(value: object, limit: int) -> object:
        if not isinstance(value, str):
            return value
        if len(value) <= limit:
            return value
        return value[:limit].rstrip() + "..."

    def _compact_ghost_history_message(message: object) -> dict[str, object]:
        payload = message.to_dict() if hasattr(message, "to_dict") else dict(message)
        metadata = (
            payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        )
        compact_metadata: dict[str, object] = {}
        for key in (
            "bearing_title",
            "micro_response",
            "response_profile",
            "response_profile_reason",
            "route_family",
            "result_state",
        ):
            if key in metadata:
                compact_metadata[key] = _limit_snapshot_text(metadata.get(key), 360)
        route_state = metadata.get("route_state")
        if isinstance(route_state, dict):
            winner = route_state.get("winner")
            compact_metadata["route_state"] = {
                "winner": {
                    "route_family": winner.get("route_family"),
                    "confidence": winner.get("confidence"),
                }
                if isinstance(winner, dict)
                else None,
                "summary_omitted": True,
                "detail_load_deferred": True,
            }
        voice_output = metadata.get("voice_output")
        if isinstance(voice_output, dict):
            compact_metadata["voice_output"] = {
                "scheduled": bool(voice_output.get("scheduled")),
                "playback_requested": bool(voice_output.get("playback_requested")),
                "streaming_requested": bool(voice_output.get("streaming_requested")),
            }
        return {
            "message_id": payload.get("message_id"),
            "role": payload.get("role"),
            "content": _limit_snapshot_text(payload.get("content"), 1200),
            "created_at": payload.get("created_at"),
            "metadata": compact_metadata,
        }

    @app.get("/snapshot")
    def snapshot(
        request: Request,
        session_id: str = "default",
        profile: str = "ghost_light",
        event_since_id: int = 0,
        event_limit: int = 100,
        job_limit: int = 50,
        note_limit: int = 50,
        history_limit: int = 100,
        compact: bool = False,
    ) -> dict[str, object]:
        snapshot_started = perf_counter()
        current = _current_container(request)
        if compact:
            payload = {
                "snapshot_profile": "command_eval_compact",
                "session_id": session_id,
                "health": {"ok": True},
                "active_request_state": current.assistant.session_state.get_active_request_state(
                    session_id
                ),
                "recent_context_resolutions": current.assistant.session_state.get_recent_context_resolutions(
                    session_id
                ),
                "active_workspace": {
                    "workspace_id": current.assistant.session_state.get_active_workspace_id(
                        session_id
                    )
                    or "",
                    "summary_omitted": True,
                    "omitted_reason": "command_eval_compact_snapshot",
                    "detail_load_deferred": True,
                },
                "active_task": {
                    "session_id": session_id,
                    "summary_omitted": True,
                    "omitted_reason": "command_eval_compact_snapshot",
                },
            }
            return _finish_snapshot_instrumentation(
                payload,
                started_at=snapshot_started,
                profile="command_eval_compact",
                deferred_sections=("status", "settings", "tools", "history", "deck_detail"),
            )
        normalized_profile = str(profile or "ghost_light").strip().lower()
        if normalized_profile in {"ghost", "ghost_light", "light", "default"}:
            event_cap = max(0, min(int(event_limit or 0), 12))
            job_cap = max(0, min(int(job_limit or 0), 8))
            note_cap = max(0, min(int(note_limit or 0), 0))
            history_cap = max(0, min(int(history_limit or 0), 12))
            payload = {
                "snapshot_profile": "ghost_light",
                "session_id": session_id,
                "detail_load_deferred": True,
                "deferred_reason": "ghost_hot_path_avoids_deck_detail",
                "health": _health_payload(request),
                "status": current.status_snapshot_fast(session_id=session_id),
                "jobs": current.jobs.list_jobs(limit=job_cap),
                "events": current.events.recent(
                    since_id=event_since_id, limit=event_cap
                ),
                "notes": [
                    note.to_dict() for note in current.notes.list_notes(limit=note_cap)
                ],
                "history": [
                    _compact_ghost_history_message(message)
                    for message in current.conversations.list_messages(
                        session_id=session_id, limit=history_cap
                    )
                ],
                "active_workspace": current._status_active_workspace_light(session_id),
                "active_request_state": current._hot_path_compact_value(
                    current.assistant.session_state.get_active_request_state(
                        session_id
                    ),
                    max_depth=3,
                    list_limit=6,
                    text_limit=400,
                ),
                "recent_context_resolutions": current._hot_path_compact_value(
                    current.assistant.session_state.get_recent_context_resolutions(
                        session_id
                    ),
                    max_depth=3,
                    list_limit=4,
                    text_limit=300,
                ),
                "active_task": current._status_active_task_summary(session_id),
            }
            return _finish_snapshot_instrumentation(
                payload,
                started_at=snapshot_started,
                profile="ghost_light",
                deferred_sections=(
                    "deck_detail",
                    "settings",
                    "tools",
                    "workspace_detail",
                    "system_detail",
                    "weather_detail",
                ),
            )
        if normalized_profile in {"deck_summary", "summary"}:
            event_cap = max(0, min(int(event_limit or 0), 32))
            job_cap = max(0, min(int(job_limit or 0), 20))
            note_cap = max(0, min(int(note_limit or 0), 12))
            history_cap = max(0, min(int(history_limit or 0), 32))
            payload = {
                "snapshot_profile": "deck_summary",
                "session_id": session_id,
                "detail_load_deferred": True,
                "deferred_reason": "deck_summary_defers_full_detail_payload",
                "health": _health_payload(request),
                "status": current.status_snapshot_fast(session_id=session_id),
                "jobs": current.jobs.list_jobs(limit=job_cap),
                "events": current.events.recent(
                    since_id=event_since_id, limit=event_cap
                ),
                "notes": [
                    note.to_dict() for note in current.notes.list_notes(limit=note_cap)
                ],
                "settings_summary": {
                    "environment": current.config.environment,
                    "runtime_mode": current.config.runtime.mode,
                    "api_base_url": current.config.api_base_url,
                    "detail_load_deferred": True,
                },
                "history": [
                    _compact_ghost_history_message(message)
                    for message in current.conversations.list_messages(
                        session_id=session_id, limit=history_cap
                    )
                ],
                "tools_summary": {
                    "tool_count": current._tool_count_fast(),
                    "detail_load_deferred": True,
                },
                "active_workspace": current._status_active_workspace_light(session_id),
                "active_request_state": current._hot_path_compact_value(
                    current.assistant.session_state.get_active_request_state(
                        session_id
                    ),
                    max_depth=3,
                    list_limit=8,
                    text_limit=600,
                ),
                "recent_context_resolutions": current._hot_path_compact_value(
                    current.assistant.session_state.get_recent_context_resolutions(
                        session_id
                    ),
                    max_depth=3,
                    list_limit=8,
                    text_limit=400,
                ),
                "active_task": current._status_active_task_summary(session_id),
            }
            return _finish_snapshot_instrumentation(
                payload,
                started_at=snapshot_started,
                profile="deck_summary",
                deferred_sections=("deck_detail", "workspace_detail", "system_detail"),
            )
        payload = {
            "snapshot_profile": "deck_detail",
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
            "active_workspace": current.assistant.workspace_service.active_workspace_summary_compact(
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
        return _finish_snapshot_instrumentation(
            payload,
            started_at=snapshot_started,
            profile="deck_detail",
        )

    return app
