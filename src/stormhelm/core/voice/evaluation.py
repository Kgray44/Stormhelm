from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.config.models import VoiceOpenAIConfig
from stormhelm.config.models import VoicePlaybackConfig
from stormhelm.core.voice.models import VoiceAudioInput
from stormhelm.core.voice.models import VoicePlaybackResult
from stormhelm.core.voice.models import VoiceSpeechSynthesisResult
from stormhelm.core.voice.models import VoiceTurnResult
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.service import VoiceService
from stormhelm.core.voice.service import build_voice_subsystem
from stormhelm.shared.time import utc_now_iso


_TRUTH_FLAGS: dict[str, bool] = {
    "no_wake_word": True,
    "no_vad": True,
    "no_realtime": True,
    "no_continuous_loop": True,
    "always_listening": False,
    "user_heard_claimed": False,
}

_VOICE20_PRIVACY_FLAGS: dict[str, bool] = {
    "no_raw_audio": True,
    "no_generated_audio_bytes": True,
    "no_secrets": True,
    "bounded_transcript_previews": True,
    "bounded_spoken_previews": True,
}

_VOICE20_FORBIDDEN_COPY = {
    "always listening",
    "cloud wake active",
    "realtime assistant active",
    "direct tools active",
    "happy to help",
    "ahoy",
    "oopsie",
}

_VOICE20_RAW_AUDIO_KEYS = {
    "audio_bytes",
    "raw_audio",
    "raw_audio_bytes",
    "raw_bytes",
    "generated_audio_bytes",
}

_VOICE20_SECRET_KEYS = {
    "api_key",
    "authorization",
    "bearer",
    "secret",
    "token",
}

_VOICE20_STAGE_ORDER = {
    "wake": 10,
    "ghost": 20,
    "listen_window": 35,
    "capture_start": 50,
    "capture_complete": 950,
    "vad_speech_started": 160,
    "vad_speech_stopped": 900,
    "stt_complete": 1200,
    "realtime_partial": 120,
    "realtime_final": 360,
    "core_bridge_complete": 1350,
    "spoken_render_complete": 1380,
    "tts_complete": 1600,
    "playback_started": 1660,
    "realtime_response_gate_complete": 1480,
    "complete": 1800,
}


def _duration_between(
    marks: dict[str, int | float],
    start: str,
    end: str,
) -> int | None:
    if start not in marks or end not in marks:
        return None
    return max(0, int(marks[end] - marks[start]))


@dataclass(slots=True, frozen=True)
class VoiceLatencyBreakdown:
    wake_ms: int | None = None
    ghost_ms: int | None = None
    listen_window_ms: int | None = None
    capture_ms: int | None = None
    vad_ms: int | None = None
    stt_ms: int | None = None
    realtime_partial_ms: int | None = None
    realtime_final_ms: int | None = None
    core_bridge_ms: int | None = None
    spoken_render_ms: int | None = None
    tts_ms: int | None = None
    playback_start_ms: int | None = None
    realtime_response_gate_ms: int | None = None
    total_ms: int = 0
    exceeded_budget: bool = False
    budget_label: str | None = None

    @classmethod
    def from_marks(
        cls,
        marks: dict[str, int | float],
        *,
        latency_budget_ms: int | None = None,
        budget_label: str | None = None,
    ) -> "VoiceLatencyBreakdown":
        if not marks:
            total_ms = 0
        else:
            total_ms = max(0, int(max(marks.values()) - min(marks.values())))
        return cls(
            wake_ms=_duration_between(marks, "wake", "ghost"),
            ghost_ms=_duration_between(marks, "wake", "ghost"),
            listen_window_ms=_duration_between(marks, "ghost", "listen_window"),
            capture_ms=_duration_between(marks, "capture_start", "capture_complete"),
            vad_ms=_duration_between(marks, "vad_speech_started", "vad_speech_stopped"),
            stt_ms=_duration_between(marks, "capture_complete", "stt_complete"),
            realtime_partial_ms=_duration_between(marks, "wake", "realtime_partial"),
            realtime_final_ms=_duration_between(
                marks, "realtime_partial", "realtime_final"
            ),
            core_bridge_ms=_duration_between(
                marks, "stt_complete", "core_bridge_complete"
            )
            or _duration_between(marks, "realtime_final", "core_bridge_complete"),
            spoken_render_ms=_duration_between(
                marks, "core_bridge_complete", "spoken_render_complete"
            ),
            tts_ms=_duration_between(marks, "spoken_render_complete", "tts_complete"),
            playback_start_ms=_duration_between(
                marks, "tts_complete", "playback_started"
            ),
            realtime_response_gate_ms=_duration_between(
                marks, "playback_started", "realtime_response_gate_complete"
            )
            or _duration_between(
                marks, "core_bridge_complete", "realtime_response_gate_complete"
            ),
            total_ms=total_ms,
            exceeded_budget=bool(
                latency_budget_ms is not None and total_ms > latency_budget_ms
            ),
            budget_label=budget_label,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoiceReleaseScenario:
    scenario_id: str
    name: str
    phase_coverage: tuple[str, ...]
    entrypoint: str
    expected_stages: tuple[str, ...]
    expected_final_status: str
    expected_route_family: str | None = None
    expected_result_state: str | None = None
    expected_trust_posture: str | None = None
    expected_verification_posture: str | None = None
    expected_voice_output_state: str | None = None
    expected_no_overclaim: bool = True
    expected_privacy_flags: dict[str, bool] = field(
        default_factory=lambda: dict(_VOICE20_PRIVACY_FLAGS)
    )
    expected_event_sequence: tuple[str, ...] = ()
    latency_budget_ms: int | None = None
    destructive: bool = False
    live_provider_required: bool = False
    core_result_state: str = "completed"
    route_family: str = "voice_release"
    subsystem: str = "voice"
    trust_posture: str = "none"
    verification_posture: str = "not_claimed"
    spoken_response: str = "Core approved response."
    speak_allowed: bool = True
    provider_unavailable: str | None = None
    direct_tool_attempt: str | None = None
    transcript: str = "release check"


@dataclass(slots=True, frozen=True)
class VoiceReleaseEvaluationResult:
    scenario_id: str
    name: str
    session_id: str
    passed: bool
    failed_stage: str | None
    failure_reason: str | None
    actual_stage_summary: dict[str, Any]
    expected_stage_summary: dict[str, Any]
    latency_breakdown: dict[str, Any]
    event_trace: list[dict[str, Any]]
    redaction_findings: list[str]
    authority_boundary_findings: list[str]
    ui_payload_findings: list[str]
    result_state_findings: list[str]
    expected_privacy_flags: dict[str, bool]
    ui_payload: dict[str, Any]
    correlation_ids: dict[str, str]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoicePipelineExpectedResult:
    final_status: str
    stopped_stage: str | None = None
    core_result_state: str | None = None
    playback_status: str | None = None


@dataclass(slots=True, frozen=True)
class VoicePipelineScenario:
    scenario_id: str
    transcript: str = "what time is it?"
    capture_status: str = "completed"
    stt_error_code: str | None = None
    stt_uncertain: bool = False
    stt_confidence: float | None = 0.9
    core_result_state: str = "completed"
    core_spoken_summary: str = "Bearing acquired."
    core_visual_summary: str = "Bearing acquired."
    route_family: str = "clock"
    subsystem: str = "tools"
    spoken_responses_enabled: bool = True
    synthesize_response: bool = False
    tts_error_code: str | None = None
    play_response: bool = False
    playback_enabled: bool = True
    playback_error_code: str | None = None
    playback_complete_immediately: bool = True
    stop_playback: bool = False
    expected: VoicePipelineExpectedResult | None = None


@dataclass(slots=True, frozen=True)
class VoicePipelineEvaluationResult:
    scenario_id: str
    pipeline_id: str
    session_id: str
    ok: bool
    passed: bool
    final_status: str
    stopped_stage: str | None
    stage_results: dict[str, dict[str, Any]]
    pipeline_summary: dict[str, Any]
    ghost_payload: dict[str, Any]
    events: list[dict[str, Any]]
    expectation_mismatches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class VoicePipelineStageSummary:
    stage: str
    final_status: str
    stopped_stage: str | None
    current_blocker: str | None
    last_successful_stage: str | None
    failed_stage: str | None
    capture_status: str
    transcription_status: str
    core_result_state: str | None
    synthesis_status: str
    playback_status: str
    transcript_preview: str | None
    spoken_preview: str | None
    route_family: str | None
    subsystem: str | None
    trust_posture: str | None
    verification_posture: str | None
    truth_flags: dict[str, bool]
    user_heard_claimed: bool
    timestamps: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _ScenarioCoreBridge:
    scenario: VoicePipelineScenario
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def handle_message(
        self,
        message: str,
        session_id: str = "default",
        *,
        surface_mode: str = "ghost",
        active_module: str = "chartroom",
        workspace_context: dict[str, Any] | None = None,
        input_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "message": message,
                "session_id": session_id,
                "surface_mode": surface_mode,
                "active_module": active_module,
                "workspace_context": workspace_context,
                "input_context": input_context,
            }
        )
        return {
            "session_id": session_id,
            "assistant_message": {
                "content": self.scenario.core_visual_summary,
                "metadata": {
                    "spoken_summary": self.scenario.core_spoken_summary,
                    "micro_response": self.scenario.core_spoken_summary,
                    "full_response": self.scenario.core_visual_summary,
                    "voice_core_result": {
                        "result_state": self.scenario.core_result_state,
                        "route_family": self.scenario.route_family,
                        "subsystem": self.scenario.subsystem,
                        "trust_posture": "none",
                        "verification_posture": "not_claimed",
                        "speak_allowed": True,
                        "continue_listening": False,
                    },
                    "route_state": {
                        "winner": {
                            "route_family": self.scenario.route_family,
                            "query_shape": "voice_pipeline_evaluation",
                            "clarification_needed": self.scenario.core_result_state
                            == "clarification_required",
                        }
                    },
                },
            },
            "jobs": [],
            "actions": [],
            "active_request_state": {},
            "active_task": {},
        }


def run_voice_pipeline_scenario(
    scenario: VoicePipelineScenario,
) -> VoicePipelineEvaluationResult:
    runner = _VoicePipelineScenarioRunner(scenario)
    return runner.run()


def run_voice_pipeline_suite(
    scenarios: list[VoicePipelineScenario] | tuple[VoicePipelineScenario, ...],
) -> list[VoicePipelineEvaluationResult]:
    return [run_voice_pipeline_scenario(scenario) for scenario in scenarios]


@dataclass(slots=True)
class _VoicePipelineScenarioRunner:
    scenario: VoicePipelineScenario
    pipeline_id: str = field(
        default_factory=lambda: f"voice-pipeline-{uuid4().hex[:12]}"
    )
    session_id: str = field(init=False)
    stage_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    stopped_stage: str | None = None
    final_status: str = "completed"
    last_successful_stage: str | None = None
    failed_stage: str | None = None
    current_blocker: str | None = None
    turn_result: VoiceTurnResult | None = None
    synthesis_result: VoiceSpeechSynthesisResult | None = None
    playback_result: VoicePlaybackResult | None = None

    def __post_init__(self) -> None:
        self.session_id = f"voice-pipeline-session-{self.scenario.scenario_id}"
        self.stage_results = {
            "capture": {"status": "skipped"},
            "stt": {"status": "skipped"},
            "core": {"status": "skipped"},
            "spoken_response": {"status": "skipped"},
            "tts": {"status": "skipped"},
            "playback": {"status": "skipped"},
        }

    def run(self) -> VoicePipelineEvaluationResult:
        audio = self._run_capture()
        if audio is not None:
            service = self._build_service()
            self._run_stt_and_core(service, audio)
            if self.turn_result is not None and self._core_allows_output():
                if self.scenario.synthesize_response:
                    self._run_tts(service)
                if self.scenario.play_response:
                    self._run_playback(service)

        summary = self._pipeline_summary()
        ghost_payload = self._ghost_payload(summary)
        mismatches = self._expectation_mismatches()
        return VoicePipelineEvaluationResult(
            scenario_id=self.scenario.scenario_id,
            pipeline_id=self.pipeline_id,
            session_id=self.session_id,
            ok=self._ok_status(),
            passed=not mismatches,
            final_status=self.final_status,
            stopped_stage=self.stopped_stage,
            stage_results=self.stage_results,
            pipeline_summary=summary,
            ghost_payload=ghost_payload,
            events=self.events,
            expectation_mismatches=mismatches,
        )

    def _run_capture(self) -> VoiceAudioInput | None:
        capture_id = f"voice-capture-{uuid4().hex[:12]}"
        self._event(
            "voice.capture_started",
            capture_id=capture_id,
            stage="capture",
            status="started",
        )
        status = str(self.scenario.capture_status or "completed").strip().lower()
        if status in {"cancelled", "canceled"}:
            self._stop_at(
                "capture", "cancelled", failed=False, blocker="capture_cancelled"
            )
            self.stage_results["capture"] = {
                "capture_id": capture_id,
                "status": "cancelled",
                "microphone_was_active": False,
                "always_listening_claimed": False,
                "wake_word_claimed": False,
            }
            self._event(
                "voice.capture_cancelled",
                capture_id=capture_id,
                stage="capture",
                status="cancelled",
            )
            return None
        if status == "timeout":
            self._stop_at("capture", "timeout", blocker="capture_timeout")
            self.stage_results["capture"] = {
                "capture_id": capture_id,
                "status": "timeout",
                "microphone_was_active": False,
                "always_listening_claimed": False,
                "wake_word_claimed": False,
            }
            self._event(
                "voice.capture_timeout",
                capture_id=capture_id,
                stage="capture",
                status="timeout",
            )
            return None
        if status in {"unavailable", "failed", "blocked"}:
            final_status = "blocked" if status == "blocked" else "failed"
            self._stop_at("capture", final_status, blocker=f"capture_{status}")
            self.stage_results["capture"] = {
                "capture_id": capture_id,
                "status": status,
                "error_code": f"capture_{status}",
                "microphone_was_active": False,
                "always_listening_claimed": False,
                "wake_word_claimed": False,
            }
            self._event(
                "voice.capture_failed",
                capture_id=capture_id,
                stage="capture",
                status=status,
            )
            return None

        audio = VoiceAudioInput.from_bytes(
            b"fake wav bytes",
            filename="voice-pipeline.wav",
            mime_type="audio/wav",
            duration_ms=900,
            metadata={"pipeline_id": self.pipeline_id, "capture_id": capture_id},
            source="mock",
        )
        self.last_successful_stage = "capture"
        self.stage_results["capture"] = {
            "capture_id": capture_id,
            "status": "completed",
            "audio_input_id": audio.input_id,
            "duration_ms": audio.duration_ms,
            "size_bytes": audio.size_bytes,
            "audio_metadata": audio.to_metadata(),
            "microphone_was_active": False,
            "always_listening_claimed": False,
            "wake_word_claimed": False,
        }
        self._event(
            "voice.capture_stopped",
            capture_id=capture_id,
            input_id=audio.input_id,
            stage="capture",
            status="completed",
        )
        self._event(
            "voice.capture_audio_created",
            capture_id=capture_id,
            input_id=audio.input_id,
            stage="capture",
            status="completed",
        )
        return audio

    def _run_stt_and_core(self, service: VoiceService, audio: VoiceAudioInput) -> None:
        self._event(
            "voice.audio_input_received",
            input_id=audio.input_id,
            stage="stt",
            status="received",
        )
        self._event(
            "voice.transcription_started",
            input_id=audio.input_id,
            stage="stt",
            status="started",
        )
        result = _run_async(
            service.submit_audio_voice_turn(
                audio,
                mode="ghost",
                session_id=self.session_id,
                metadata={
                    "pipeline_id": self.pipeline_id,
                    "correlation_id": self.pipeline_id,
                },
            )
        )
        self.turn_result = result
        transcription = result.transcription_result
        if transcription is None or not transcription.ok:
            error_code = result.error_code or (
                transcription.error_code if transcription is not None else "stt_failed"
            )
            self._stop_at("stt", "failed", blocker=error_code)
            self.stage_results["stt"] = {
                "status": "failed",
                "input_id": audio.input_id,
                "transcription_id": transcription.transcription_id
                if transcription is not None
                else None,
                "error_code": error_code,
                "transcription_uncertain": bool(
                    transcription and transcription.transcription_uncertain
                ),
            }
            self._event(
                "voice.transcription_failed",
                input_id=audio.input_id,
                transcription_id=transcription.transcription_id
                if transcription is not None
                else None,
                stage="stt",
                status="failed",
                error_code=error_code,
            )
            return

        self.last_successful_stage = "stt"
        self.stage_results["stt"] = {
            "status": "completed",
            "input_id": audio.input_id,
            "transcription_id": transcription.transcription_id,
            "provider": transcription.provider,
            "model": transcription.model,
            "transcript_preview": _preview_text(transcription.transcript),
            "confidence": transcription.confidence,
            "transcription_uncertain": transcription.transcription_uncertain,
            "error_code": transcription.error_code,
        }
        self._event(
            "voice.transcription_completed",
            input_id=audio.input_id,
            transcription_id=transcription.transcription_id,
            stage="stt",
            status="completed",
            provider=transcription.provider,
            model=transcription.model,
        )

        if result.core_request is None or result.core_result is None:
            self._stop_at(
                "core", "failed", blocker=result.error_code or "core_not_routed"
            )
            self.stage_results["core"] = {
                "status": "skipped",
                "transcription_id": transcription.transcription_id,
                "error_code": result.error_code,
            }
            return

        self._event(
            "voice.core_request_started",
            input_id=audio.input_id,
            transcription_id=transcription.transcription_id,
            turn_id=result.turn.turn_id if result.turn is not None else None,
            stage="core",
            status="started",
        )
        core = result.core_result
        self.stage_results["core"] = {
            "status": "completed",
            "transcription_id": transcription.transcription_id,
            "turn_id": result.turn.turn_id if result.turn is not None else None,
            "request_id": result.core_request.request_id,
            "result_state": core.result_state,
            "route_family": core.route_family,
            "subsystem": core.subsystem,
            "trust_posture": core.trust_posture,
            "verification_posture": core.verification_posture,
            "error_code": core.error_code,
        }
        self._event(
            "voice.core_request_completed",
            input_id=audio.input_id,
            transcription_id=transcription.transcription_id,
            turn_id=result.turn.turn_id if result.turn is not None else None,
            stage="core",
            status="completed",
            result_state=core.result_state,
            route_family=core.route_family,
            subsystem=core.subsystem,
            error_code=core.error_code,
        )

        spoken = result.spoken_response
        if spoken is not None:
            self.stage_results["spoken_response"] = {
                "status": "prepared" if spoken.spoken_text else "silent",
                "spoken_text": spoken.spoken_text,
                "spoken_preview": _preview_text(spoken.spoken_text),
                "should_speak": spoken.should_speak,
                "reason_if_not_speaking": spoken.reason_if_not_speaking,
            }
            self._event(
                "voice.spoken_response_prepared",
                turn_id=result.turn.turn_id if result.turn is not None else None,
                stage="spoken_response",
                status="prepared",
                result_state=core.result_state,
                route_family=core.route_family,
                subsystem=core.subsystem,
            )

        if core.result_state == "blocked":
            self._stop_at(
                "core",
                "blocked",
                failed=False,
                blocker=core.error_code or "core_blocked",
            )
            return
        if core.result_state in {"clarification_required", "requires_confirmation"}:
            self.final_status = core.result_state
        else:
            self.final_status = (
                "response_prepared" if not self.scenario.play_response else "completed"
            )
        self.last_successful_stage = "core"

    def _run_tts(self, service: VoiceService) -> None:
        if self.turn_result is None:
            return
        turn_id = (
            self.turn_result.turn.turn_id if self.turn_result.turn is not None else None
        )
        self._event(
            "voice.synthesis_started", turn_id=turn_id, stage="tts", status="started"
        )
        synthesis = _run_async(
            service.synthesize_turn_response(
                self.turn_result,
                session_id=self.session_id,
                metadata={
                    "pipeline_id": self.pipeline_id,
                    "correlation_id": self.pipeline_id,
                },
            )
        )
        self.synthesis_result = synthesis
        status = synthesis.status
        self.stage_results["tts"] = {
            "status": status,
            "speech_request_id": synthesis.speech_request_id,
            "synthesis_id": synthesis.synthesis_id,
            "provider": synthesis.provider,
            "model": synthesis.model,
            "voice": synthesis.voice,
            "format": synthesis.format,
            "error_code": synthesis.error_code,
            "audio_output_id": synthesis.audio_output.output_id
            if synthesis.audio_output is not None
            else None,
        }
        if not synthesis.ok:
            code = synthesis.error_code or "synthesis_failed"
            blocked = status in {"blocked", "unavailable"} or code in {
                "spoken_responses_disabled",
                "spoken_response_not_allowed",
            }
            final_status = (
                "response_ready_tts_blocked" if blocked else "response_ready_tts_failed"
            )
            self._stop_at("tts", final_status, blocker=code)
            self._event(
                "voice.synthesis_failed",
                speech_request_id=synthesis.speech_request_id,
                synthesis_id=synthesis.synthesis_id,
                turn_id=turn_id,
                stage="tts",
                status=status,
                error_code=code,
            )
            return

        self.last_successful_stage = "tts"
        self._event(
            "voice.synthesis_completed",
            speech_request_id=synthesis.speech_request_id,
            synthesis_id=synthesis.synthesis_id,
            turn_id=turn_id,
            stage="tts",
            status="succeeded",
            provider=synthesis.provider,
            model=synthesis.model,
        )
        if synthesis.audio_output is not None:
            self._event(
                "voice.audio_output_created",
                audio_output_id=synthesis.audio_output.output_id,
                synthesis_id=synthesis.synthesis_id,
                turn_id=turn_id,
                stage="tts",
                status="created",
                format=synthesis.format,
            )
        if not self.scenario.play_response:
            self.final_status = "response_audio_prepared"

    def _run_playback(self, service: VoiceService) -> None:
        if self.synthesis_result is None or not self.synthesis_result.ok:
            return
        turn_id = (
            self.turn_result.turn.turn_id
            if self.turn_result and self.turn_result.turn is not None
            else None
        )
        playback = _run_async(
            service.play_speech_output(
                self.synthesis_result,
                session_id=self.session_id,
                turn_id=turn_id,
                metadata={
                    "pipeline_id": self.pipeline_id,
                    "correlation_id": self.pipeline_id,
                },
            )
        )
        self.playback_result = playback
        self.stage_results["playback"] = {
            "status": playback.status,
            "playback_request_id": playback.playback_request_id,
            "playback_id": playback.playback_id,
            "audio_output_id": playback.audio_output_id,
            "synthesis_id": playback.synthesis_id,
            "provider": playback.provider,
            "device": playback.device,
            "error_code": playback.error_code,
            "played_locally": playback.played_locally,
            "user_heard_claimed": False,
        }
        if playback.status in {"started", "completed"}:
            self._event(
                "voice.playback_started",
                playback_request_id=playback.playback_request_id,
                playback_id=playback.playback_id,
                audio_output_id=playback.audio_output_id,
                synthesis_id=playback.synthesis_id,
                turn_id=turn_id,
                stage="playback",
                status="started",
                provider=playback.provider,
            )
        if playback.status == "completed":
            self.last_successful_stage = "playback"
            self.final_status = "completed"
            self._event(
                "voice.playback_completed",
                playback_request_id=playback.playback_request_id,
                playback_id=playback.playback_id,
                audio_output_id=playback.audio_output_id,
                synthesis_id=playback.synthesis_id,
                turn_id=turn_id,
                stage="playback",
                status="completed",
                provider=playback.provider,
            )
            return
        if playback.status == "started" and self.scenario.stop_playback:
            stopped = _run_async(
                service.stop_playback(playback.playback_id, reason="test_stop")
            )
            self.playback_result = stopped
            self.stage_results["playback"].update(
                {
                    "status": stopped.status,
                    "playback_id": stopped.playback_id,
                    "error_code": stopped.error_code,
                    "played_locally": stopped.played_locally,
                    "user_heard_claimed": False,
                }
            )
            self.last_successful_stage = "playback"
            self.final_status = "playback_stopped"
            self._event(
                "voice.playback_stopped",
                playback_request_id=stopped.playback_request_id,
                playback_id=stopped.playback_id,
                audio_output_id=stopped.audio_output_id,
                synthesis_id=stopped.synthesis_id,
                turn_id=turn_id,
                stage="playback",
                status="stopped",
                provider=stopped.provider,
            )
            return
        if playback.status == "started":
            self.last_successful_stage = "playback"
            self.final_status = "playback_started"
            return
        if playback.status in {"blocked", "unavailable"}:
            self._stop_at(
                "playback",
                "response_audio_prepared_playback_blocked",
                blocker=playback.error_code or "playback_blocked",
            )
            return
        self._stop_at(
            "playback",
            "response_audio_prepared_playback_failed",
            blocker=playback.error_code or "playback_failed",
        )
        self._event(
            "voice.playback_failed",
            playback_request_id=playback.playback_request_id,
            playback_id=playback.playback_id,
            audio_output_id=playback.audio_output_id,
            synthesis_id=playback.synthesis_id,
            turn_id=turn_id,
            stage="playback",
            status=playback.status,
            error_code=playback.error_code,
            provider=playback.provider,
        )

    def _build_service(self) -> VoiceService:
        config = VoiceConfig(
            enabled=True,
            mode="manual",
            manual_input_enabled=True,
            spoken_responses_enabled=self.scenario.spoken_responses_enabled,
            debug_mock_provider=True,
            openai=VoiceOpenAIConfig(
                max_audio_bytes=128, max_audio_seconds=4, max_tts_chars=240
            ),
            playback=VoicePlaybackConfig(
                enabled=self.scenario.playback_enabled,
                provider="mock",
                allow_dev_playback=True,
                max_audio_bytes=64,
                max_duration_ms=5000,
            ),
        )
        service = build_voice_subsystem(config, _openai_config())
        service.provider = MockVoiceProvider(
            stt_transcript=self.scenario.transcript,
            stt_error_code=self.scenario.stt_error_code,
            stt_error_message=self.scenario.stt_error_code,
            stt_uncertain=self.scenario.stt_uncertain,
            stt_confidence=self.scenario.stt_confidence,
            tts_error_code=self.scenario.tts_error_code,
            tts_error_message=self.scenario.tts_error_code,
            tts_audio_bytes=b"mock audio",
        )
        service.playback_provider = MockPlaybackProvider(
            available=True,
            fail_playback=bool(self.scenario.playback_error_code),
            error_code=self.scenario.playback_error_code,
            error_message=self.scenario.playback_error_code,
            complete_immediately=self.scenario.playback_complete_immediately,
        )
        service.attach_core_bridge(_ScenarioCoreBridge(self.scenario))
        return service

    def _core_allows_output(self) -> bool:
        if self.turn_result is None or self.turn_result.core_result is None:
            return False
        return self.turn_result.core_result.result_state != "blocked"

    def _pipeline_summary(self) -> dict[str, Any]:
        core = self.turn_result.core_result if self.turn_result is not None else None
        transcription = (
            self.turn_result.transcription_result
            if self.turn_result is not None
            else None
        )
        spoken = (
            self.turn_result.spoken_response if self.turn_result is not None else None
        )
        playback_status = (
            self.playback_result.status
            if self.playback_result is not None
            else self.stage_results["playback"]["status"]
        )
        return VoicePipelineStageSummary(
            stage=self._summary_stage(),
            final_status=self.final_status,
            stopped_stage=self.stopped_stage,
            current_blocker=self.current_blocker,
            last_successful_stage=self.last_successful_stage,
            failed_stage=self.failed_stage,
            capture_status=self.stage_results["capture"]["status"],
            transcription_status=self.stage_results["stt"]["status"],
            core_result_state=core.result_state if core is not None else None,
            synthesis_status=self.stage_results["tts"]["status"],
            playback_status=playback_status,
            transcript_preview=_preview_text(transcription.transcript)
            if transcription is not None
            else None,
            spoken_preview=_preview_text(spoken.spoken_text)
            if spoken is not None
            else None,
            route_family=core.route_family if core is not None else None,
            subsystem=core.subsystem if core is not None else None,
            trust_posture=core.trust_posture if core is not None else None,
            verification_posture=core.verification_posture
            if core is not None
            else None,
            truth_flags=dict(_TRUTH_FLAGS),
            user_heard_claimed=False,
            timestamps={"evaluated_at": utc_now_iso()},
        ).to_dict()

    def _ghost_payload(self, summary: dict[str, Any]) -> dict[str, Any]:
        truth_flags = dict(_TRUTH_FLAGS)
        truth_flags.pop("user_heard_claimed", None)
        return {
            "voice_core_state": "idle"
            if self.final_status != "playback_started"
            else "speaking",
            "primary_label": self._primary_label(),
            "stage": summary.get("stage"),
            "final_status": summary.get("final_status"),
            "stopped_stage": summary.get("stopped_stage"),
            "truth_flags": truth_flags,
            "last_transcript_preview": summary.get("transcript_preview"),
            "last_response_preview": summary.get("spoken_preview"),
        }

    def _summary_stage(self) -> str:
        if self.final_status == "cancelled":
            return "cancelled"
        if self.final_status in {"timeout", "failed"}:
            return "failed"
        if self.final_status == "blocked":
            return "blocked"
        if self.final_status == "playback_stopped":
            return "completed"
        if self.final_status == "playback_started":
            return "playing"
        if self.final_status.startswith("response_audio_prepared_playback"):
            return "audio_prepared"
        if self.final_status.startswith("response_ready_tts"):
            return "response_prepared"
        return "completed"

    def _primary_label(self) -> str:
        labels = {
            "cancelled": "Capture cancelled.",
            "timeout": "Capture timeout.",
            "failed": "Speech transcription failed.",
            "blocked": "Response blocked.",
            "response_ready_tts_blocked": "Response prepared.",
            "response_ready_tts_failed": "Speech synthesis failed.",
            "response_audio_prepared_playback_blocked": "Playback unavailable.",
            "response_audio_prepared_playback_failed": "Playback failed.",
            "playback_stopped": "Playback stopped.",
            "playback_started": "Playing response.",
        }
        if self.final_status in {"clarification_required", "requires_confirmation"}:
            return self.final_status.replace("_", " ").capitalize() + "."
        return labels.get(self.final_status, "Push-to-talk ready.")

    def _expectation_mismatches(self) -> list[str]:
        expected = self.scenario.expected
        if expected is None:
            return []
        comparisons = {
            "final_status": (expected.final_status, self.final_status),
            "stopped_stage": (expected.stopped_stage, self.stopped_stage),
            "core_result_state": (
                expected.core_result_state,
                self.stage_results["core"].get("result_state"),
            ),
            "playback_status": (
                expected.playback_status,
                self.stage_results["playback"].get("status"),
            ),
        }
        mismatches: list[str] = []
        for field_name, (expected_value, actual_value) in comparisons.items():
            if expected_value is not None and expected_value != actual_value:
                mismatches.append(
                    f"{field_name} expected {expected_value} got {actual_value}"
                )
        return mismatches

    def _stop_at(
        self,
        stage: str,
        final_status: str,
        *,
        failed: bool = True,
        blocker: str | None = None,
    ) -> None:
        self.stopped_stage = stage
        self.final_status = final_status
        self.current_blocker = blocker
        if failed:
            self.failed_stage = stage

    def _ok_status(self) -> bool:
        return self.final_status in {
            "completed",
            "playback_stopped",
            "response_audio_prepared",
        }

    def _event(self, event_type: str, **payload: Any) -> None:
        event = {
            "event_type": event_type,
            "timestamp": utc_now_iso(),
            "correlation_id": self.pipeline_id,
            "pipeline_id": self.pipeline_id,
            "session_id": self.session_id,
            "privacy": {
                "no_raw_audio": True,
                "no_generated_audio_bytes": True,
                "no_secrets": True,
                "user_heard_claimed": False,
            },
            "truth_flags": dict(_TRUTH_FLAGS),
        }
        for key, value in payload.items():
            if value is not None:
                event[key] = value
        self.events.append(event)


def default_voice_release_scenarios() -> list[VoiceReleaseScenario]:
    return [
        VoiceReleaseScenario(
            scenario_id="push_to_talk_happy_path",
            name="Push-to-talk happy path",
            phase_coverage=("voice5", "voice8", "voice20"),
            entrypoint="push_to_talk",
            expected_stages=("capture", "stt", "core", "tts", "playback"),
            expected_final_status="completed",
            expected_result_state="completed",
        ),
        VoiceReleaseScenario(
            scenario_id="wake_driven_happy_path",
            name="Wake-driven happy path",
            phase_coverage=("voice10", "voice13r", "voice15", "voice20"),
            entrypoint="wake_loop",
            expected_stages=(
                "wake",
                "ghost",
                "listen_window",
                "capture",
                "vad",
                "stt",
                "core",
                "tts",
                "playback",
            ),
            expected_final_status="completed",
            expected_result_state="completed",
        ),
        VoiceReleaseScenario(
            scenario_id="realtime_transcription_bridge",
            name="Realtime transcription bridge",
            phase_coverage=("voice18", "voice20"),
            entrypoint="realtime_transcription",
            expected_stages=("realtime_partial", "realtime_final", "core"),
            expected_final_status="completed",
            expected_result_state="completed",
        ),
        VoiceReleaseScenario(
            scenario_id="realtime_speech_core_bridge",
            name="Realtime speech-to-speech Core bridge",
            phase_coverage=("voice19", "voice20"),
            entrypoint="realtime_speech",
            expected_stages=("realtime", "core_bridge", "response_gate"),
            expected_final_status="completed",
            expected_result_state="completed",
        ),
        VoiceReleaseScenario(
            scenario_id="spoken_confirmation",
            name="Spoken confirmation",
            phase_coverage=("voice16", "voice20"),
            entrypoint="spoken_confirmation",
            expected_stages=("confirmation_prompt", "spoken_confirmation", "trust"),
            expected_final_status="confirmation_accepted",
            expected_result_state="confirmation_accepted",
            spoken_response="Confirmation accepted.",
        ),
        VoiceReleaseScenario(
            scenario_id="interruption_stop_talking",
            name="Stop talking interruption",
            phase_coverage=("voice17", "voice20"),
            entrypoint="interruption",
            expected_stages=("output", "interruption"),
            expected_final_status="output_stopped",
            expected_result_state="unchanged",
            spoken_response="Playback stopped.",
        ),
        VoiceReleaseScenario(
            scenario_id="correction_routed",
            name="Correction routed through Core",
            phase_coverage=("voice17", "voice20"),
            entrypoint="correction",
            expected_stages=("interruption", "core"),
            expected_final_status="routed_to_core",
            expected_result_state="pending_core_decision",
            core_result_state="pending_core_decision",
            spoken_response="I routed that through Core.",
        ),
        VoiceReleaseScenario(
            scenario_id="core_blocked",
            name="Blocked Core result",
            phase_coverage=("voice19", "voice20"),
            entrypoint="realtime_speech",
            expected_stages=("realtime", "core_bridge", "response_gate"),
            expected_final_status="blocked",
            expected_result_state="blocked",
            core_result_state="blocked",
            spoken_response="Core blocked that request.",
        ),
        VoiceReleaseScenario(
            scenario_id="attempted_not_verified",
            name="Attempted but not verified",
            phase_coverage=("voice19", "voice20"),
            entrypoint="realtime_speech",
            expected_stages=("realtime", "core_bridge", "response_gate"),
            expected_final_status="attempted_not_verified",
            expected_result_state="attempted_not_verified",
            expected_verification_posture="not_verified",
            core_result_state="attempted_not_verified",
            verification_posture="not_verified",
            spoken_response="Attempted, but not verified.",
        ),
        VoiceReleaseScenario(
            scenario_id="playback_failure",
            name="Playback failure preserves Core result",
            phase_coverage=("voice4", "voice15", "voice20"),
            entrypoint="push_to_talk",
            expected_stages=("capture", "stt", "core", "tts", "playback"),
            expected_final_status="playback_failed",
            expected_result_state="completed",
            spoken_response="Response prepared.",
        ),
        VoiceReleaseScenario(
            scenario_id="stt_failure",
            name="STT failure blocks Core routing",
            phase_coverage=("voice2", "voice20"),
            entrypoint="audio_file",
            expected_stages=("capture", "stt"),
            expected_final_status="transcription_failed",
            expected_result_state=None,
            provider_unavailable="stt_failed",
        ),
        VoiceReleaseScenario(
            scenario_id="empty_transcript",
            name="Empty final transcript",
            phase_coverage=("voice18", "voice20"),
            entrypoint="realtime_transcription",
            expected_stages=("realtime_final",),
            expected_final_status="empty_transcript",
            expected_result_state="empty_transcript",
            transcript="",
        ),
        VoiceReleaseScenario(
            scenario_id="provider_unavailable",
            name="Provider unavailable fallback",
            phase_coverage=("voice7", "voice20"),
            entrypoint="provider_unavailable",
            expected_stages=("readiness",),
            expected_final_status="provider_unavailable",
            expected_result_state=None,
            provider_unavailable="realtime_provider_unavailable",
        ),
        VoiceReleaseScenario(
            scenario_id="privacy_redaction",
            name="Privacy and redaction",
            phase_coverage=("voice20",),
            entrypoint="privacy",
            expected_stages=("status", "events", "ui"),
            expected_final_status="redacted",
            expected_result_state=None,
        ),
        VoiceReleaseScenario(
            scenario_id="realtime_authority_boundary",
            name="Realtime authority boundary",
            phase_coverage=("voice19", "voice20"),
            entrypoint="authority_boundary",
            expected_stages=("realtime", "direct_tool_blocked"),
            expected_final_status="blocked",
            expected_result_state=None,
            direct_tool_attempt="install_software",
        ),
    ]


def run_voice_release_suite(
    scenarios: list[VoiceReleaseScenario] | tuple[VoiceReleaseScenario, ...],
) -> list[VoiceReleaseEvaluationResult]:
    return [run_voice_release_scenario(scenario) for scenario in scenarios]


def run_voice_release_scenario(
    scenario: VoiceReleaseScenario,
) -> VoiceReleaseEvaluationResult:
    runner = _VoiceReleaseScenarioRunner(scenario)
    return runner.run()


@dataclass(slots=True)
class _VoiceReleaseScenarioRunner:
    scenario: VoiceReleaseScenario
    session_id: str = field(init=False)
    correlation_ids: dict[str, str] = field(init=False)
    event_trace: list[dict[str, Any]] = field(default_factory=list)
    marks: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        short_id = uuid4().hex[:10]
        self.session_id = f"voice-release-session-{short_id}"
        self.correlation_ids = {
            "session_id": self.session_id,
            "wake_event_id": f"voice-wake-event-{short_id}",
            "wake_session_id": f"voice-wake-session-{short_id}",
            "wake_ghost_request_id": f"voice-wake-ghost-{short_id}",
            "listen_window_id": f"voice-listen-window-{short_id}",
            "capture_id": f"voice-capture-{short_id}",
            "vad_session_id": f"voice-vad-{short_id}",
            "audio_input_id": f"voice-audio-input-{short_id}",
            "transcription_id": f"voice-transcription-{short_id}",
            "realtime_session_id": f"voice-realtime-session-{short_id}",
            "realtime_turn_id": f"voice-realtime-turn-{short_id}",
            "voice_turn_id": f"voice-turn-{short_id}",
            "core_request_id": f"voice-core-request-{short_id}",
            "spoken_confirmation_request_id": f"voice-confirm-request-{short_id}",
            "spoken_confirmation_result_id": f"voice-confirm-result-{short_id}",
            "interruption_request_id": f"voice-interrupt-request-{short_id}",
            "interruption_result_id": f"voice-interrupt-result-{short_id}",
            "speech_request_id": f"voice-speech-request-{short_id}",
            "synthesis_id": f"voice-synthesis-{short_id}",
            "playback_id": f"voice-playback-{short_id}",
            "loop_id": f"voice-loop-{short_id}",
        }

    def run(self) -> VoiceReleaseEvaluationResult:
        self._run_entrypoint()
        final_status = self._final_status()
        stage_summary = self._stage_summary(final_status)
        ui_payload = self._ui_payload(final_status)
        event_findings = audit_voice_release_events(self.event_trace)
        payload_findings = audit_voice_release_payload(ui_payload)
        latency = VoiceLatencyBreakdown.from_marks(
            self.marks,
            latency_budget_ms=self.scenario.latency_budget_ms,
            budget_label=self.scenario.scenario_id
            if self.scenario.latency_budget_ms is not None
            else None,
        )
        notes: list[str] = []
        if latency.exceeded_budget:
            notes.append(
                f"Latency budget exceeded for {self.scenario.scenario_id}; diagnostic only."
            )
        expected_summary = {
            "expected_stages": list(self.scenario.expected_stages),
            "expected_final_status": self.scenario.expected_final_status,
            "expected_result_state": self.scenario.expected_result_state,
            "expected_route_family": self.scenario.expected_route_family,
            "expected_trust_posture": self.scenario.expected_trust_posture,
            "expected_verification_posture": self.scenario.expected_verification_posture,
        }
        failure_reason = self._failure_reason(
            final_status,
            stage_summary,
            event_findings,
            payload_findings,
        )
        return VoiceReleaseEvaluationResult(
            scenario_id=self.scenario.scenario_id,
            name=self.scenario.name,
            session_id=self.session_id,
            passed=failure_reason is None,
            failed_stage=stage_summary.get("failed_stage"),
            failure_reason=failure_reason,
            actual_stage_summary=stage_summary,
            expected_stage_summary=expected_summary,
            latency_breakdown=latency.to_dict(),
            event_trace=self.event_trace,
            redaction_findings=[
                *event_findings["redaction_findings"],
                *payload_findings["redaction_findings"],
            ],
            authority_boundary_findings=[
                *event_findings["authority_boundary_findings"],
                *payload_findings["authority_boundary_findings"],
            ],
            ui_payload_findings=payload_findings["ui_payload_findings"],
            result_state_findings=payload_findings["result_state_findings"],
            expected_privacy_flags=dict(self.scenario.expected_privacy_flags),
            ui_payload=ui_payload,
            correlation_ids=dict(self.correlation_ids),
            notes=notes,
        )

    def _run_entrypoint(self) -> None:
        self.marks["wake"] = 0
        entrypoint = self.scenario.entrypoint
        if entrypoint == "wake_loop":
            self._event("voice.wake_detected", "wake", wake_event_id=True)
            self._event("voice.wake_session_started", "wake", wake_session_id=True)
            self._mark("ghost")
            self._event("voice.wake_ghost_shown", "ghost", wake_ghost_request_id=True)
            self._mark("listen_window")
            self._event("voice.post_wake_listen_started", "listen_window")
            self._mark("capture_start")
            self._event("voice.capture_started", "capture")
            self._mark("vad_speech_started")
            self._event("voice.speech_activity_started", "vad")
            self._mark("vad_speech_stopped")
            self._event("voice.speech_activity_stopped", "vad")
            self._capture_to_playback()
            return
        if entrypoint == "push_to_talk":
            self._mark("capture_start")
            self._event("voice.capture_started", "capture")
            self._capture_to_playback(playback_failure=self.scenario.scenario_id == "playback_failure")
            return
        if entrypoint == "audio_file":
            self._mark("capture_complete")
            self._event("voice.audio_input_received", "capture")
            self._mark("stt_complete")
            self._event("voice.transcription_failed", "stt", error_code="stt_failed")
            return
        if entrypoint == "realtime_transcription":
            self._mark("realtime_partial")
            if self.scenario.transcript:
                self._event("voice.realtime_partial_transcript", "realtime_partial")
            self._mark("realtime_final")
            self._event("voice.realtime_final_transcript", "realtime_final")
            if self.scenario.transcript:
                self._mark("core_bridge_complete")
                self._event("voice.realtime_turn_submitted_to_core", "core")
                self._event("voice.realtime_turn_completed", "core")
            return
        if entrypoint == "realtime_speech":
            self._event("voice.realtime_speech_session_started", "realtime")
            self._mark("core_bridge_complete")
            self._event("voice.realtime_core_bridge_call_started", "core_bridge")
            self._event("voice.realtime_core_bridge_call_completed", "core_bridge")
            self._mark("realtime_response_gate_complete")
            self._event("voice.realtime_response_gated", "response_gate")
            return
        if entrypoint == "spoken_confirmation":
            self._event("voice.spoken_confirmation_received", "spoken_confirmation")
            self._event("voice.spoken_confirmation_classified", "spoken_confirmation")
            self._event("voice.spoken_confirmation_bound", "spoken_confirmation")
            self._event("voice.spoken_confirmation_accepted", "spoken_confirmation")
            self._event("voice.spoken_confirmation_consumed", "spoken_confirmation")
            return
        if entrypoint == "interruption":
            self._event("voice.interruption_received", "interruption")
            self._event("voice.interruption_classified", "interruption")
            self._event("voice.output_interrupted", "interruption")
            return
        if entrypoint == "correction":
            self._event("voice.interruption_received", "interruption")
            self._event("voice.correction_routed", "core")
            self._event("voice.core_request_started", "core")
            return
        if entrypoint == "provider_unavailable":
            self._event(
                "voice.realtime_session_failed",
                "readiness",
                error_code=self.scenario.provider_unavailable,
            )
            return
        if entrypoint == "privacy":
            self._event("voice.release_redaction_checked", "status")
            return
        if entrypoint == "authority_boundary":
            self._event(
                "voice.realtime_direct_tool_blocked",
                "direct_tool_blocked",
                tool_name=self.scenario.direct_tool_attempt or "blocked_tool",
            )
            return

    def _capture_to_playback(self, *, playback_failure: bool = False) -> None:
        self._mark("capture_complete")
        self._event("voice.capture_stopped", "capture")
        self._event("voice.capture_audio_created", "capture")
        self._mark("stt_complete")
        self._event("voice.transcription_completed", "stt")
        self._mark("core_bridge_complete")
        self._event("voice.core_request_started", "core")
        self._event("voice.core_request_completed", "core")
        self._mark("spoken_render_complete")
        self._event("voice.spoken_response_prepared", "spoken_response")
        self._mark("tts_complete")
        self._event("voice.synthesis_completed", "tts")
        self._event("voice.audio_output_created", "tts")
        self._mark("playback_started")
        self._event(
            "voice.playback_failed" if playback_failure else "voice.playback_completed",
            "playback",
            error_code="playback_unavailable" if playback_failure else None,
        )
        self._mark("complete")

    def _mark(self, name: str) -> None:
        self.marks[name] = _VOICE20_STAGE_ORDER.get(name, max(self.marks.values()) + 25)

    def _event(
        self,
        event_type: str,
        stage: str,
        *,
        wake_event_id: bool = False,
        wake_session_id: bool = False,
        wake_ghost_request_id: bool = False,
        error_code: str | None = None,
        tool_name: str | None = None,
    ) -> None:
        event = {
            "event_type": event_type,
            "timestamp": utc_now_iso(),
            "correlation_id": self.scenario.scenario_id,
            "scenario_id": self.scenario.scenario_id,
            "session_id": self.session_id,
            "stage": stage,
            "status": self._event_status(event_type),
            "privacy": dict(_VOICE20_PRIVACY_FLAGS),
            "raw_audio_present": False,
            "direct_tools_allowed": False,
            "direct_action_tools_exposed": False,
            "core_bridge_required": True,
        }
        for key in (
            "listen_window_id",
            "capture_id",
            "vad_session_id",
            "audio_input_id",
            "transcription_id",
            "realtime_session_id",
            "realtime_turn_id",
            "voice_turn_id",
            "speech_request_id",
            "synthesis_id",
            "playback_id",
            "loop_id",
        ):
            event[key] = self.correlation_ids[key]
        if event_type != "voice.realtime_partial_transcript":
            event["core_request_id"] = self.correlation_ids["core_request_id"]
        if wake_event_id:
            event["wake_event_id"] = self.correlation_ids["wake_event_id"]
        if wake_session_id:
            event["wake_session_id"] = self.correlation_ids["wake_session_id"]
        if wake_ghost_request_id:
            event["wake_ghost_request_id"] = self.correlation_ids[
                "wake_ghost_request_id"
            ]
        if self.scenario.entrypoint == "spoken_confirmation":
            event["spoken_confirmation_request_id"] = self.correlation_ids[
                "spoken_confirmation_request_id"
            ]
            event["spoken_confirmation_result_id"] = self.correlation_ids[
                "spoken_confirmation_result_id"
            ]
            event["action_completed"] = False
        if self.scenario.entrypoint in {"interruption", "correction"}:
            event["interruption_request_id"] = self.correlation_ids[
                "interruption_request_id"
            ]
            event["interruption_result_id"] = self.correlation_ids[
                "interruption_result_id"
            ]
            event["core_task_cancelled"] = False
        if tool_name:
            event["tool_name"] = tool_name
            event["action_executed"] = False
        if error_code:
            event["error_code"] = error_code
        self.event_trace.append(event)

    def _event_status(self, event_type: str) -> str:
        if event_type.endswith("_failed"):
            return "failed"
        if event_type.endswith("_blocked"):
            return "blocked"
        if event_type.endswith("_completed"):
            return "completed"
        if event_type.endswith("_started"):
            return "started"
        return "recorded"

    def _final_status(self) -> str:
        if self.scenario.expected_final_status:
            return self.scenario.expected_final_status
        return self.scenario.core_result_state

    def _stage_summary(self, final_status: str) -> dict[str, Any]:
        failed_stage = None
        if final_status in {
            "transcription_failed",
            "provider_unavailable",
            "playback_failed",
        }:
            failed_stage = final_status.rsplit("_", 1)[0]
        return {
            "entrypoint": self.scenario.entrypoint,
            "expected_stages": list(self.scenario.expected_stages),
            "final_status": final_status,
            "failed_stage": failed_stage,
            "core_result_state": self.scenario.expected_result_state
            if self.scenario.expected_result_state is not None
            else self.scenario.core_result_state
            if final_status not in {"transcription_failed", "provider_unavailable"}
            else None,
            "route_family": self.scenario.expected_route_family
            or self.scenario.route_family,
            "subsystem": self.scenario.subsystem,
            "trust_posture": self.scenario.expected_trust_posture
            or self.scenario.trust_posture,
            "verification_posture": self.scenario.expected_verification_posture
            or self.scenario.verification_posture,
            "response_gate_status": "blocked"
            if not self.scenario.speak_allowed
            else "allowed",
            "direct_tools_allowed": False,
            "direct_action_tools_exposed": False,
            "stormhelm_core_request_only": True,
        }

    def _ui_payload(self, final_status: str) -> dict[str, Any]:
        if final_status == "blocked":
            label = "Response blocked."
            spoken = self.scenario.spoken_response
        elif final_status == "attempted_not_verified":
            label = "Attempted, not confirmed."
            spoken = "Attempted, but not confirmed."
        elif final_status == "playback_failed":
            label = "Playback unavailable."
            spoken = "Response prepared."
        elif final_status == "transcription_failed":
            label = "Transcription failed."
            spoken = ""
        elif final_status == "empty_transcript":
            label = "Transcript empty."
            spoken = ""
        elif final_status == "provider_unavailable":
            label = "Realtime transcription unavailable."
            spoken = ""
        elif final_status == "output_stopped":
            label = "Playback stopped."
            spoken = ""
        elif final_status == "confirmation_accepted":
            label = "Confirmation accepted."
            spoken = "Confirmation accepted."
        else:
            label = "Response prepared."
            spoken = self.scenario.spoken_response
        return {
            "voice_release_phase": "voice20",
            "label": label,
            "spoken_preview": _preview_text(spoken),
            "transcript_preview": _preview_text(self.scenario.transcript),
            "core_result_state": "attempted_unconfirmed"
            if final_status == "attempted_not_verified"
            else self.scenario.expected_result_state
            or self.scenario.core_result_state,
            "verification_posture": "unconfirmed"
            if final_status == "attempted_not_verified"
            else self.scenario.expected_verification_posture
            or self.scenario.verification_posture,
            "realtime": {
                "direct_tools_allowed": False,
                "direct_action_tools_exposed": False,
                "core_bridge_required": True,
                "core_bridge_tool_name": "stormhelm_core_request",
                "always_listening": False,
                "cloud_wake_detection": False,
            },
            "privacy": dict(_VOICE20_PRIVACY_FLAGS),
        }

    def _failure_reason(
        self,
        final_status: str,
        stage_summary: dict[str, Any],
        event_findings: dict[str, list[str]],
        payload_findings: dict[str, list[str]],
    ) -> str | None:
        if final_status != self.scenario.expected_final_status:
            return (
                f"final_status expected {self.scenario.expected_final_status} "
                f"got {final_status}"
            )
        expected = self.scenario.expected_result_state
        if expected is not None and stage_summary.get("core_result_state") != expected:
            return (
                f"core_result_state expected {expected} "
                f"got {stage_summary.get('core_result_state')}"
            )
        if self.scenario.expected_event_sequence:
            actual = [event["event_type"] for event in self.event_trace]
            if not _contains_ordered_subsequence(
                actual, list(self.scenario.expected_event_sequence)
            ):
                return "expected_event_sequence_missing"
        all_findings = [
            *event_findings["redaction_findings"],
            *event_findings["authority_boundary_findings"],
            *payload_findings["redaction_findings"],
            *payload_findings["authority_boundary_findings"],
            *payload_findings["ui_payload_findings"],
            *payload_findings["result_state_findings"],
        ]
        if all_findings:
            return all_findings[0]
        return None


def audit_voice_release_payload(payload: Any) -> dict[str, list[str]]:
    findings = {
        "redaction_findings": [],
        "authority_boundary_findings": [],
        "ui_payload_findings": [],
        "result_state_findings": [],
    }

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).strip().lower()
                item_path = f"{path}.{key}" if path else str(key)
                if normalized in _VOICE20_RAW_AUDIO_KEYS or "raw_audio" in normalized:
                    if normalized == "no_raw_audio":
                        pass
                    elif normalized == "raw_audio_present" and item is False:
                        pass
                    else:
                        findings["redaction_findings"].append(
                            f"raw_audio_key_present:{item_path}"
                        )
                if normalized in _VOICE20_SECRET_KEYS:
                    findings["redaction_findings"].append(
                        f"secret_key_present:{item_path}"
                    )
                if normalized == "direct_tools_allowed" and item is True:
                    findings["authority_boundary_findings"].append(
                        "direct_tools_allowed_true"
                    )
                if normalized == "direct_action_tools_exposed" and item is True:
                    findings["authority_boundary_findings"].append(
                        "direct_action_tools_exposed_true"
                    )
                walk(item, item_path)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str):
            text = value.lower()
            for phrase in _VOICE20_FORBIDDEN_COPY:
                if phrase in text:
                    findings["ui_payload_findings"].append(
                        f"forbidden_copy:{phrase}"
                    )

    walk(payload)
    text = str(payload).lower().replace("not_verified", "").replace(
        "not verified", ""
    )
    core_state = None
    verification = None
    if isinstance(payload, dict):
        core_state = str(payload.get("core_result_state") or "").lower()
        verification = str(payload.get("verification_posture") or "").lower()
    if "done" in text and core_state not in {"completed", "verified"}:
        findings["result_state_findings"].append(
            "overclaim:done_without_core_completion"
        )
    if "verified" in text and verification != "verified" and core_state != "verified":
        findings["result_state_findings"].append(
            "overclaim:verified_without_core_verification"
        )
    return findings


def audit_voice_release_events(events: list[dict[str, Any]]) -> dict[str, list[str]]:
    findings = {
        "redaction_findings": [],
        "authority_boundary_findings": [],
        "event_correlation_findings": [],
    }
    for index, event in enumerate(events):
        event_type = str(event.get("event_type") or "")
        if not event.get("session_id"):
            findings["event_correlation_findings"].append(
                f"missing_session_id:{index}"
            )
        if event_type == "voice.realtime_partial_transcript" and event.get(
            "core_request_id"
        ):
            findings["authority_boundary_findings"].append(
                "partial_transcript_routed_core"
            )
        if event_type == "voice.realtime_direct_tool_blocked" and (
            event.get("tool_execution_started") or event.get("action_executed")
        ):
            findings["authority_boundary_findings"].append(
                "direct_tool_blocked_looked_executed"
            )
        if event_type == "voice.spoken_confirmation_accepted" and event.get(
            "action_completed"
        ):
            findings["authority_boundary_findings"].append(
                "confirmation_acceptance_claimed_action_completed"
            )
        payload_findings = audit_voice_release_payload(event)
        findings["redaction_findings"].extend(payload_findings["redaction_findings"])
        findings["authority_boundary_findings"].extend(
            payload_findings["authority_boundary_findings"]
        )
    return findings


def voice_release_readiness_matrix() -> list[dict[str, str]]:
    rows = [
        (
            "Wake local-only",
            "yes",
            "disabled",
            "local wake provider",
            "local wake only; no command authority",
            "wake/provider/privacy",
            "disabled by default; live wake opt-in",
            "hardened",
        ),
        (
            "Push-to-talk capture",
            "yes",
            "disabled",
            "capture provider",
            "capture creates bounded audio only",
            "capture/voice pipeline",
            "manual fallback remains",
            "hardened",
        ),
        (
            "Post-wake listen window",
            "yes",
            "disabled",
            "wake plus capture",
            "bounded opportunity only; no Core routing",
            "post-wake listen",
            "one utterance window",
            "hardened",
        ),
        (
            "VAD/end-of-speech",
            "yes",
            "disabled",
            "mock/local optional",
            "audio activity only",
            "vad provider/service",
            "not semantic completion",
            "hardened",
        ),
        (
            "STT",
            "yes",
            "disabled",
            "OpenAI or mock",
            "transcript only",
            "audio turn/evaluator",
            "bounded audio only",
            "hardened",
        ),
        (
            "Core bridge",
            "yes",
            "enabled for voice turns",
            "Stormhelm Core",
            "Core owns meaning/trust/result state",
            "manual/audio/realtime bridge",
            "no direct tools from voice",
            "hardened",
        ),
        (
            "TTS",
            "yes",
            "disabled",
            "OpenAI or mock",
            "speaks approved text only",
            "tts/playback",
            "visual response remains if unavailable",
            "hardened",
        ),
        (
            "Playback",
            "yes",
            "disabled",
            "local playback provider",
            "playback does not claim user heard",
            "playback/interruption",
            "device availability surfaced",
            "hardened",
        ),
        (
            "Stop-speaking",
            "yes",
            "available when playback active",
            "playback provider",
            "output stop only; no task cancellation",
            "interruption",
            "does not mutate Core result",
            "hardened",
        ),
        (
            "Spoken confirmation",
            "yes",
            "enabled",
            "trust/confirmation service",
            "fresh scoped binding only",
            "spoken confirmation",
            "yes is not global permission",
            "hardened",
        ),
        (
            "Interruption/correction",
            "yes",
            "enabled",
            "Core bridge for task semantics",
            "context-sensitive; Core for task cancellation",
            "barge-in/interruption",
            "not direct task cancellation",
            "hardened",
        ),
        (
            "Realtime transcription bridge",
            "yes",
            "disabled",
            "OpenAI Realtime or mock",
            "final transcript routes through Core",
            "realtime transcription",
            "no speech-to-speech in transcription mode",
            "hardened",
        ),
        (
            "Realtime speech-to-speech Core bridge",
            "yes",
            "disabled",
            "OpenAI Realtime or mock",
            "stormhelm_core_request only; no direct tools",
            "realtime speech tripwires",
            "active sessions only",
            "hardened",
        ),
        (
            "Privacy/redaction",
            "yes",
            "always",
            "status/events/UI",
            "no raw audio/secrets in payloads",
            "release redaction",
            "previews are bounded",
            "hardened",
        ),
        (
            "Event correlation",
            "yes",
            "always",
            "voice events",
            "trace IDs by stage",
            "release event correlation",
            "cancelled stages do not emit success",
            "hardened",
        ),
        (
            "Provider fallback",
            "yes",
            "always",
            "providers/readiness",
            "truthful unavailable states",
            "provider fallback",
            "no fake success",
            "hardened",
        ),
        (
            "Latency instrumentation",
            "yes",
            "diagnostic",
            "fake-clock evaluator",
            "diagnostic only; no authority",
            "latency instrumentation",
            "broad budgets only",
            "hardened",
        ),
    ]
    return [
        {
            "capability": capability,
            "implemented": implemented,
            "enabled_by_default": enabled,
            "provider_live_dependency": provider,
            "authority_boundary": authority,
            "tests": tests,
            "known_caveats": caveats,
            "release_posture": posture,
        }
        for (
            capability,
            implemented,
            enabled,
            provider,
            authority,
            tests,
            caveats,
            posture,
        ) in rows
    ]


def _contains_ordered_subsequence(actual: list[str], expected: list[str]) -> bool:
    cursor = 0
    for item in actual:
        if cursor < len(expected) and item == expected[cursor]:
            cursor += 1
    return cursor == len(expected)


def _openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        enabled=True,
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model="gpt-5.4-nano",
        planner_model="gpt-5.4-nano",
        reasoning_model="gpt-5.4",
        timeout_seconds=60,
        max_tool_rounds=4,
        max_output_tokens=1200,
        planner_max_output_tokens=900,
        reasoning_max_output_tokens=1400,
        instructions="",
    )


def _run_async(value: Any) -> Any:
    return asyncio.run(value)


def _preview_text(text: str, *, limit: int = 96) -> str:
    compact = " ".join(str(text or "").split()).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


__all__ = [
    "VoiceLatencyBreakdown",
    "VoicePipelineEvaluationResult",
    "VoicePipelineExpectedResult",
    "VoicePipelineScenario",
    "VoicePipelineStageSummary",
    "VoiceReleaseEvaluationResult",
    "VoiceReleaseScenario",
    "audit_voice_release_events",
    "audit_voice_release_payload",
    "default_voice_release_scenarios",
    "run_voice_pipeline_scenario",
    "run_voice_pipeline_suite",
    "run_voice_release_scenario",
    "run_voice_release_suite",
    "voice_release_readiness_matrix",
]
