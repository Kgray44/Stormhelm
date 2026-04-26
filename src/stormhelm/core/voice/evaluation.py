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
    "VoicePipelineEvaluationResult",
    "VoicePipelineExpectedResult",
    "VoicePipelineScenario",
    "VoicePipelineStageSummary",
    "run_voice_pipeline_scenario",
    "run_voice_pipeline_suite",
]
