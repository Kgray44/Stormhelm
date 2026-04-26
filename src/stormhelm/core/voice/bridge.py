from __future__ import annotations

from dataclasses import asdict, dataclass, field
from uuid import uuid4
from typing import Any

from stormhelm.shared.time import utc_now_iso


@dataclass(slots=True, frozen=True)
class VoiceCoreRequest:
    transcript: str
    session_id: str
    turn_id: str
    source: str = "voice"
    voice_mode: str = "manual"
    user_id: str | None = None
    interaction_mode: str = "ghost"
    screen_context_permission: str = "not_requested"
    confirmation_intent: str | None = None
    interrupt_intent: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: f"voice-core-{uuid4().hex[:12]}")
    created_at: str = field(default_factory=utc_now_iso)
    core_bridge_required: bool = True

    def to_core_metadata(self) -> dict[str, Any]:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "request_id": self.request_id,
                "source": self.source,
                "voice_mode": self.voice_mode,
                "session_id": self.session_id,
                "turn_id": self.turn_id,
                "interaction_mode": self.interaction_mode,
                "screen_context_permission": self.screen_context_permission,
                "confirmation_intent": self.confirmation_intent,
                "interrupt_intent": self.interrupt_intent,
                "core_bridge_required": self.core_bridge_required,
                "created_at": self.created_at,
            }
        )
        if self.user_id:
            metadata["user_id"] = self.user_id
        return metadata

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceCoreResult:
    result_state: str
    spoken_summary: str
    visual_summary: str
    route_family: str | None
    subsystem: str | None
    trust_posture: str | None
    verification_posture: str | None
    task_id: str | None
    followup_binding: dict[str, Any] = field(default_factory=dict)
    speak_allowed: bool = False
    continue_listening: bool = False
    error_code: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VoiceCoreBridgeError(RuntimeError):
    pass


async def submit_voice_core_request(core_bridge: Any, request: VoiceCoreRequest) -> VoiceCoreResult:
    handler = getattr(core_bridge, "handle_message", None)
    if not callable(handler):
        raise VoiceCoreBridgeError("core_bridge_missing_handle_message")

    metadata = request.to_core_metadata()
    workspace_context = metadata.get("workspace_context") if isinstance(metadata.get("workspace_context"), dict) else None
    active_module = str(metadata.get("active_module") or "chartroom").strip() or "chartroom"
    voice_mode = str(request.voice_mode or "manual").strip().lower() or "manual"
    if voice_mode == "manual":
        input_context = {
            "source": "manual_voice",
            "voice": metadata,
            "manual_transcript": True,
            "no_real_audio": True,
        }
    else:
        turn_source = str(metadata.get("turn_source") or f"voice_{voice_mode}").strip() or f"voice_{voice_mode}"
        input_context = {
            "source": turn_source,
            "voice": metadata,
            "controlled_audio_transcript": voice_mode == "stt",
            "manual_transcript": False,
            "no_real_audio": True,
            "no_microphone_capture": True,
        }
    payload = await handler(
        request.transcript,
        session_id=request.session_id,
        surface_mode=request.interaction_mode,
        active_module=active_module,
        workspace_context=workspace_context,
        input_context=input_context,
    )
    return voice_core_result_from_core_payload(payload)


def voice_core_result_from_core_payload(payload: dict[str, Any]) -> VoiceCoreResult:
    assistant_message = payload.get("assistant_message") if isinstance(payload.get("assistant_message"), dict) else {}
    metadata = assistant_message.get("metadata") if isinstance(assistant_message.get("metadata"), dict) else {}
    explicit = metadata.get("voice_core_result") if isinstance(metadata.get("voice_core_result"), dict) else {}
    route_state = metadata.get("route_state") if isinstance(metadata.get("route_state"), dict) else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    planner_debug = metadata.get("planner_debug") if isinstance(metadata.get("planner_debug"), dict) else {}
    planner_obedience = metadata.get("planner_obedience") if isinstance(metadata.get("planner_obedience"), dict) else {}
    jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    active_task = payload.get("active_task") if isinstance(payload.get("active_task"), dict) else {}

    result_state = str(explicit.get("result_state") or "").strip()
    if not result_state:
        result_state = _infer_result_state(
            explicit=explicit,
            winner=winner,
            planner_obedience=planner_obedience,
            jobs=jobs,
            actions=actions,
        )

    route_family = (
        str(explicit.get("route_family") or "").strip()
        or str(winner.get("route_family") or "").strip()
        or _route_family_from_jobs(jobs)
        or None
    )
    subsystem = str(explicit.get("subsystem") or "").strip() or _subsystem_from_route_family(route_family)
    spoken_summary = str(explicit.get("spoken_summary") or metadata.get("spoken_summary") or metadata.get("micro_response") or "").strip()
    visual_summary = str(explicit.get("visual_summary") or metadata.get("full_response") or assistant_message.get("content") or "").strip()
    task_id = str(explicit.get("task_id") or active_task.get("taskId") or active_task.get("task_id") or "").strip() or None

    return VoiceCoreResult(
        result_state=result_state,
        spoken_summary=spoken_summary,
        visual_summary=visual_summary,
        route_family=route_family,
        subsystem=subsystem,
        trust_posture=str(explicit.get("trust_posture") or _trust_posture_from_payload(payload, metadata)).strip() or None,
        verification_posture=str(explicit.get("verification_posture") or _verification_posture_from_payload(metadata)).strip() or None,
        task_id=task_id,
        followup_binding=dict(explicit.get("followup_binding") or {}),
        speak_allowed=bool(explicit.get("speak_allowed", True)),
        continue_listening=bool(explicit.get("continue_listening", False)),
        error_code=str(explicit.get("error_code") or "").strip() or None,
        provenance={
            "source": "stormhelm_core",
            "raw_core_result_reference": {
                "has_assistant_message": bool(assistant_message),
                "job_count": len(jobs),
                "action_count": len(actions),
                "planner_debug_keys": sorted(planner_debug.keys()),
            },
        },
    )


def _infer_result_state(
    *,
    explicit: dict[str, Any],
    winner: dict[str, Any],
    planner_obedience: dict[str, Any],
    jobs: list[Any],
    actions: list[Any],
) -> str:
    del explicit, actions
    actual_result_mode = str(planner_obedience.get("actual_result_mode") or planner_obedience.get("expected_response_mode") or "").strip()
    if bool(winner.get("clarification_needed")) or actual_result_mode == "clarification":
        return "clarification_required"
    if actual_result_mode == "unsupported":
        return "blocked"
    if any(isinstance(job, dict) and str(job.get("status") or "").strip().lower() == "failed" for job in jobs):
        return "failed"
    return "completed"


def _route_family_from_jobs(jobs: list[Any]) -> str | None:
    for job in jobs:
        if not isinstance(job, dict):
            continue
        tool_name = str(job.get("tool_name") or "").strip()
        if tool_name:
            return tool_name
    return None


def _subsystem_from_route_family(route_family: str | None) -> str | None:
    family = str(route_family or "").strip()
    if not family:
        return None
    if family in {"calculations", "software_control", "screen_awareness", "discord_relay", "trust_approvals"}:
        return family
    if family in {"clock", "system_info", "network_status", "power_status", "resource_status"}:
        return "tools"
    return family


def _trust_posture_from_payload(payload: dict[str, Any], metadata: dict[str, Any]) -> str:
    active_request_state = payload.get("active_request_state") if isinstance(payload.get("active_request_state"), dict) else {}
    if active_request_state:
        return "active_request_bound"
    judgment = metadata.get("judgment") if isinstance(metadata.get("judgment"), dict) else {}
    if str(judgment.get("decision") or "").strip():
        return str(judgment.get("decision") or "")
    return "none"


def _verification_posture_from_payload(metadata: dict[str, Any]) -> str:
    adapter_execution = metadata.get("adapter_execution") if isinstance(metadata.get("adapter_execution"), dict) else {}
    claim_ceiling = str(adapter_execution.get("claim_ceiling") or "").strip()
    if claim_ceiling:
        return claim_ceiling
    return "not_verified"
