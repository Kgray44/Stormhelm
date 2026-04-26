from __future__ import annotations

import inspect
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.voice.availability import VoiceAvailability
from stormhelm.core.voice.availability import compute_voice_availability
from stormhelm.core.voice.bridge import VoiceCoreRequest
from stormhelm.core.voice.bridge import VoiceCoreResult
from stormhelm.core.voice.bridge import submit_voice_core_request
from stormhelm.core.voice.events import VoiceEventType
from stormhelm.core.voice.events import publish_voice_event
from stormhelm.core.voice.models import VoiceTurn
from stormhelm.core.voice.models import VoiceTurnResult
from stormhelm.core.voice.models import VoiceAudioInput
from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.models import VoicePlaybackRequest
from stormhelm.core.voice.models import VoicePlaybackResult
from stormhelm.core.voice.models import VoiceSpeechRequest
from stormhelm.core.voice.models import VoiceSpeechSynthesisResult
from stormhelm.core.voice.models import VoiceTranscriptionResult
from stormhelm.core.voice.providers import LocalPlaybackProvider
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.providers import OpenAIVoiceProvider
from stormhelm.core.voice.providers import VoicePlaybackProvider
from stormhelm.core.voice.providers import VoiceProvider
from stormhelm.core.voice.providers import VoiceProviderOperationResult
from stormhelm.core.voice.speech_renderer import SpokenResponseRenderer
from stormhelm.core.voice.speech_renderer import SpokenResponseRequest
from stormhelm.core.voice.speech_renderer import SpokenResponseResult
from stormhelm.core.voice.state import VoiceState
from stormhelm.core.voice.state import VoiceStateController
from stormhelm.core.voice.state import VoiceStateSnapshot
from stormhelm.core.voice.state import VoiceTransitionError


_SUPPORTED_AUDIO_MIME_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/webm",
}

_UNCLEAR_SHORT_TRANSCRIPTS = {"um", "uh", "hm", "hmm", "mm"}
_UNSAFE_SPEECH_MARKERS = {"```", "traceback", "api_key", "authorization:", "secret=", "password="}
_UNSAFE_UNAPPROVED_PHRASES = {"all set", "that worked"}
_SUPPORTED_PLAYBACK_FORMATS = {"mp3", "wav", "aac", "flac", "opus", "pcm"}


@dataclass(slots=True)
class VoiceService:
    config: VoiceConfig
    openai_config: OpenAIConfig
    events: EventBuffer | None = None
    availability: VoiceAvailability = field(init=False)
    state_controller: VoiceStateController = field(init=False)
    provider: VoiceProvider = field(init=False)
    playback_provider: VoicePlaybackProvider = field(init=False)
    speech_renderer: SpokenResponseRenderer = field(default_factory=SpokenResponseRenderer)
    core_bridge: Any | None = None
    last_event: dict[str, Any] | None = field(default=None, init=False)
    last_manual_turn_result: VoiceTurnResult | None = field(default=None, init=False)
    last_audio_turn_result: VoiceTurnResult | None = field(default=None, init=False)
    last_transcription_result: VoiceTranscriptionResult | None = field(default=None, init=False)
    last_audio_input_metadata: dict[str, Any] | None = field(default=None, init=False)
    last_audio_validation_error: dict[str, str | None] = field(default_factory=lambda: {"code": None, "message": None}, init=False)
    last_openai_call_attempted: bool = field(default=False, init=False)
    last_openai_call_blocked_reason: str | None = field(default=None, init=False)
    last_speech_request: VoiceSpeechRequest | None = field(default=None, init=False)
    last_synthesis_result: VoiceSpeechSynthesisResult | None = field(default=None, init=False)
    last_openai_tts_call_attempted: bool = field(default=False, init=False)
    last_openai_tts_call_blocked_reason: str | None = field(default=None, init=False)
    last_playback_request: VoicePlaybackRequest | None = field(default=None, init=False)
    last_playback_result: VoicePlaybackResult | None = field(default=None, init=False)
    last_error: dict[str, str | None] = field(default_factory=lambda: {"code": None, "message": None}, init=False)

    def __post_init__(self) -> None:
        self.availability = compute_voice_availability(self.config, self.openai_config)
        self.state_controller = VoiceStateController(config=self.config, availability=self.availability)
        self.provider = (
            MockVoiceProvider()
            if self.config.debug_mock_provider
            else OpenAIVoiceProvider(config=self.config, openai_config=self.openai_config)
        )
        self.playback_provider = (
            MockPlaybackProvider()
            if self.config.playback.provider == "mock" or (self.config.debug_mock_provider and self.config.playback.allow_dev_playback)
            else LocalPlaybackProvider(config=self.config)
        )

    def attach_core_bridge(self, core_bridge: Any) -> None:
        self.core_bridge = core_bridge

    def refresh(self) -> VoiceStateSnapshot:
        previous = self.availability
        self.availability = compute_voice_availability(self.config, self.openai_config)
        self.state_controller = VoiceStateController(config=self.config, availability=self.availability)
        if previous != self.availability and self.events is not None:
            event = publish_voice_event(
                self.events,
                VoiceEventType.AVAILABILITY_CHANGED,
                message="Voice availability changed.",
                provider=self.availability.provider_name,
                mode=self.availability.mode,
                state=self.state_controller.snapshot().state.value,
                metadata={"available": self.availability.available, "reason": self.availability.unavailable_reason},
            )
            self.last_event = event.to_dict()
        return self.state_controller.snapshot()

    async def submit_manual_voice_turn(
        self,
        transcript: str,
        *,
        mode: str = "ghost",
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        screen_context_permission: str = "not_requested",
        confirmation_intent: str | None = None,
        interrupt_intent: str | None = None,
    ) -> VoiceTurnResult:
        normalized_transcript = " ".join(str(transcript or "").split()).strip()
        if not normalized_transcript:
            return self._record_failed_turn(
                error_code="empty_transcript",
                error_message="Manual voice transcript was empty.",
            )

        allowed, blocked_reason, manual_dev_override = self._manual_turn_allowed()
        if not allowed:
            return self._record_failed_turn(
                error_code=blocked_reason,
                error_message=f"Manual voice turn blocked: {blocked_reason}.",
            )
        if self.core_bridge is None:
            return self._record_failed_turn(
                error_code="core_bridge_missing",
                error_message="Manual voice turns require the Stormhelm Core bridge.",
                core_result=VoiceCoreResult(
                    result_state="failed",
                    spoken_summary="",
                    visual_summary="Manual voice turns require the Stormhelm Core bridge.",
                    route_family=None,
                    subsystem="voice",
                    trust_posture=None,
                    verification_posture=None,
                    task_id=None,
                    speak_allowed=False,
                    continue_listening=False,
                    error_code="core_bridge_missing",
                    provenance={"source": "voice"},
                ),
            )

        active_session_id = str(session_id or "default").strip() or "default"
        interaction_mode = self._normalize_interaction_mode(mode)
        turn_metadata = dict(metadata or {})
        if manual_dev_override:
            turn_metadata["manual_dev_override"] = True

        original_availability = self.availability
        turn_availability = self._manual_turn_availability(manual_dev_override)
        self.state_controller = VoiceStateController(
            config=self.config,
            availability=turn_availability,
            session_id=active_session_id,
        )
        state_transitions = [self.state_controller.snapshot().to_dict()]
        state_before = state_transitions[0]
        if self.state_controller.snapshot().state != VoiceState.DORMANT:
            return self._record_failed_turn(
                error_code="unsupported_voice_state",
                error_message=f"Manual voice turn cannot start from {self.state_controller.snapshot().state.value}.",
                state_transitions=state_transitions,
            )

        turn = VoiceTurn(
            session_id=active_session_id,
            transcript=normalized_transcript,
            normalized_transcript=normalized_transcript,
            interaction_mode=interaction_mode,
            availability_snapshot=original_availability.to_dict(),
            voice_state_before=state_before,
            screen_context_permission=screen_context_permission,
            confirmation_intent=confirmation_intent,
            interrupt_intent=interrupt_intent,
            metadata=turn_metadata,
            core_bridge_required=True,
        )
        self._publish(
            VoiceEventType.MANUAL_TURN_RECEIVED,
            message="Manual voice transcript received.",
            turn=turn,
            state=VoiceState.MANUAL_INPUT_RECEIVED.value,
            metadata={"transcript_preview": self._preview_text(normalized_transcript)},
        )
        state_transitions.append(
            self.state_controller.transition_to(
                VoiceState.MANUAL_INPUT_RECEIVED,
                event_id=self._last_event_id(),
                turn_id=turn.turn_id,
                source="manual_voice",
            ).to_dict()
        )
        self._publish(
            VoiceEventType.STATE_CHANGED,
            message="Voice state changed for manual input.",
            turn=turn,
            state=VoiceState.MANUAL_INPUT_RECEIVED.value,
        )
        state_transitions.append(
            self.state_controller.transition_to(
                VoiceState.CORE_ROUTING,
                event_id=self._last_event_id(),
                turn_id=turn.turn_id,
                source="manual_voice",
            ).to_dict()
        )
        self._publish(
            VoiceEventType.CORE_REQUEST_STARTED,
            message="Manual voice turn entered the Core bridge.",
            turn=turn,
            state=VoiceState.CORE_ROUTING.value,
        )

        core_request = VoiceCoreRequest(
            transcript=normalized_transcript,
            session_id=active_session_id,
            turn_id=turn.turn_id,
            voice_mode="manual",
            interaction_mode=interaction_mode,
            screen_context_permission=screen_context_permission,
            confirmation_intent=confirmation_intent,
            interrupt_intent=interrupt_intent,
            metadata=turn_metadata,
        )

        try:
            core_result = await submit_voice_core_request(self.core_bridge, core_request)
            state_transitions.append(
                self.state_controller.transition_to(
                    VoiceState.THINKING,
                    event_id=self._last_event_id(),
                    turn_id=turn.turn_id,
                    source="core_bridge",
                ).to_dict()
            )
            self._publish(
                VoiceEventType.CORE_REQUEST_COMPLETED,
                message="Manual voice Core bridge request completed.",
                turn=turn,
                state=VoiceState.THINKING.value,
                result_state=core_result.result_state,
                route_family=core_result.route_family,
                subsystem=core_result.subsystem,
            )
        except Exception as error:
            core_result = VoiceCoreResult(
                result_state="failed",
                spoken_summary="",
                visual_summary="Manual voice Core bridge failed.",
                route_family=None,
                subsystem="voice",
                trust_posture=None,
                verification_posture=None,
                task_id=None,
                speak_allowed=False,
                continue_listening=False,
                error_code=f"core_bridge_failed:{error}",
                provenance={"source": "voice", "error": str(error)},
            )
            try:
                state_transitions.append(
                    self.state_controller.transition_to(
                        VoiceState.ERROR,
                        event_id=self._last_event_id(),
                        turn_id=turn.turn_id,
                        source="core_bridge",
                        error_code="core_bridge_failed",
                        error_message=str(error),
                    ).to_dict()
                )
            except VoiceTransitionError:
                state_transitions.append(self.state_controller.snapshot().to_dict())
            result = VoiceTurnResult(
                ok=False,
                turn=turn,
                core_request=core_request,
                core_result=core_result,
                voice_state_before=state_before,
                voice_state_after=self.state_controller.snapshot().to_dict(),
                state_transitions=state_transitions,
                error_code="core_bridge_failed",
                error_message=str(error),
                provider_network_call_count=self._provider_network_call_count(),
            )
            self._publish(
                VoiceEventType.TURN_FAILED,
                message="Manual voice turn failed in Core bridge.",
                turn=turn,
                state=VoiceState.ERROR.value,
                result_state="failed",
                error_code="core_bridge_failed",
            )
            return self._remember_turn_result(result)

        spoken_response = self.speech_renderer.render(
            SpokenResponseRequest(
                source_result_state=core_result.result_state,
                spoken_summary=core_result.spoken_summary,
                visual_text=core_result.visual_summary,
                speak_allowed=core_result.speak_allowed,
                spoken_responses_enabled=self.config.spoken_responses_enabled,
            )
        )
        self._publish(
            VoiceEventType.SPOKEN_RESPONSE_PREPARED,
            message="Manual voice spoken response preview prepared.",
            turn=turn,
            state=self.state_controller.snapshot().state.value,
            result_state=core_result.result_state,
            route_family=core_result.route_family,
            subsystem=core_result.subsystem,
            metadata={"should_speak": spoken_response.should_speak, "text_only_preview": True},
        )

        next_state = self._state_after_core_result(core_result)
        if next_state == VoiceState.AWAITING_CONFIRMATION:
            state_transitions.append(
                self.state_controller.transition_to(
                    VoiceState.AWAITING_CONFIRMATION,
                    event_id=self._last_event_id(),
                    turn_id=turn.turn_id,
                    source="core_bridge",
                ).to_dict()
            )
        else:
            if spoken_response.should_speak:
                state_transitions.append(
                    self.state_controller.transition_to(
                        VoiceState.SPEAKING_READY,
                        event_id=self._last_event_id(),
                        turn_id=turn.turn_id,
                        source="spoken_response_renderer",
                    ).to_dict()
                )
            state_transitions.append(
                self.state_controller.transition_to(
                    VoiceState.DORMANT,
                    event_id=self._last_event_id(),
                    turn_id=turn.turn_id,
                    source="manual_voice",
                ).to_dict()
            )

        final_state = self.state_controller.snapshot().to_dict()
        turn = replace(turn, voice_state_after=final_state)
        ok = core_result.result_state not in {"failed", "blocked_unavailable"}
        result = VoiceTurnResult(
            ok=ok,
            turn=turn,
            core_request=core_request,
            core_result=core_result,
            spoken_response=spoken_response,
            voice_state_before=state_before,
            voice_state_after=final_state,
            state_transitions=state_transitions,
            error_code=core_result.error_code,
            error_message=None,
            provider_network_call_count=self._provider_network_call_count(),
            no_real_audio=True,
            stt_invoked=False,
            tts_invoked=False,
            realtime_invoked=False,
            audio_playback_started=False,
        )
        self._publish(
            VoiceEventType.TURN_COMPLETED if ok else VoiceEventType.TURN_FAILED,
            message="Manual voice turn completed." if ok else "Manual voice turn failed.",
            turn=turn,
            state=self.state_controller.snapshot().state.value,
            result_state=core_result.result_state,
            route_family=core_result.route_family,
            subsystem=core_result.subsystem,
            error_code=core_result.error_code,
        )
        return self._remember_turn_result(result)

    async def submit_audio_voice_turn(
        self,
        audio: VoiceAudioInput,
        *,
        mode: str = "ghost",
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        screen_context_permission: str = "not_requested",
        confirmation_intent: str | None = None,
        interrupt_intent: str | None = None,
    ) -> VoiceTurnResult:
        active_session_id = str(session_id or "default").strip() or "default"
        interaction_mode = self._normalize_interaction_mode(mode)

        allowed, blocked_reason, audio_dev_override = self._audio_turn_allowed()
        if not allowed:
            self.last_openai_call_attempted = False
            self.last_openai_call_blocked_reason = blocked_reason
            return self._remember_audio_turn_result(
                VoiceTurnResult(
                    ok=False,
                    voice_state_before=self.state_controller.snapshot().to_dict(),
                    voice_state_after=self.state_controller.snapshot().to_dict(),
                    state_transitions=[self.state_controller.snapshot().to_dict()],
                    error_code=blocked_reason,
                    error_message=f"Audio voice turn blocked: {blocked_reason}.",
                    provider_network_call_count=self._provider_network_call_count(),
                    stt_invoked=False,
                    tts_invoked=False,
                    realtime_invoked=False,
                    audio_playback_started=False,
                )
            )

        self.last_audio_input_metadata = audio.to_metadata()
        validation_error = self._validate_audio_input(audio)
        if validation_error is not None:
            code, message = validation_error
            self.last_audio_validation_error = {"code": code, "message": message}
            self.last_openai_call_attempted = False
            self.last_openai_call_blocked_reason = code
            self._publish(
                VoiceEventType.AUDIO_VALIDATION_FAILED,
                message=message,
                session_id=active_session_id,
                input_id=audio.input_id,
                provider=self.provider.name,
                mode=interaction_mode,
                source=audio.source,
                error_code=code,
                metadata={"audio_input": audio.to_metadata()},
            )
            return self._remember_audio_turn_result(
                VoiceTurnResult(
                    ok=False,
                    voice_state_before=self.state_controller.snapshot().to_dict(),
                    voice_state_after=self.state_controller.snapshot().to_dict(),
                    state_transitions=[self.state_controller.snapshot().to_dict()],
                    error_code=code,
                    error_message=message,
                    provider_network_call_count=self._provider_network_call_count(),
                    stt_invoked=False,
                    tts_invoked=False,
                    realtime_invoked=False,
                    audio_playback_started=False,
                )
            )
        self.last_audio_validation_error = {"code": None, "message": None}
        self.last_openai_call_blocked_reason = None

        turn_availability = self._audio_turn_availability(audio_dev_override)
        self.state_controller = VoiceStateController(
            config=self.config,
            availability=turn_availability,
            session_id=active_session_id,
        )
        state_transitions = [self.state_controller.snapshot().to_dict()]
        state_before = state_transitions[0]
        if self.state_controller.snapshot().state != VoiceState.DORMANT:
            return self._remember_audio_turn_result(
                VoiceTurnResult(
                    ok=False,
                    voice_state_before=state_before,
                    voice_state_after=self.state_controller.snapshot().to_dict(),
                    state_transitions=state_transitions,
                    error_code="unsupported_voice_state",
                    error_message=f"Audio voice turn cannot start from {self.state_controller.snapshot().state.value}.",
                    provider_network_call_count=self._provider_network_call_count(),
                )
            )

        self._publish(
            VoiceEventType.AUDIO_INPUT_RECEIVED,
            message="Controlled voice audio input received.",
            session_id=active_session_id,
            input_id=audio.input_id,
            provider=self.provider.name,
            mode=interaction_mode,
            source=audio.source,
            state=VoiceState.DORMANT.value,
            metadata={"audio_input": audio.to_metadata()},
        )
        state_transitions.append(
            self.state_controller.transition_to(
                VoiceState.TRANSCRIBING,
                event_id=self._last_event_id(),
                source="controlled_audio",
            ).to_dict()
        )
        self._publish(
            VoiceEventType.TRANSCRIPTION_STARTED,
            message="Controlled voice audio transcription started.",
            session_id=active_session_id,
            input_id=audio.input_id,
            provider=self.provider.name,
            model=self._stt_model_name(),
            mode=interaction_mode,
            source="voice_stt",
            state=VoiceState.TRANSCRIBING.value,
        )

        transcription_result = await self._transcribe_audio(audio)
        transcription_result = self._apply_transcription_quality_rules(transcription_result)
        self.last_transcription_result = transcription_result
        self.last_openai_call_attempted = transcription_result.provider == "openai" and self._provider_network_call_count() > 0

        if not transcription_result.ok or not transcription_result.usable_for_core_turn:
            try:
                state_transitions.append(
                    self.state_controller.transition_to(
                        VoiceState.ERROR,
                        event_id=self._last_event_id(),
                        source="stt_provider",
                        error_code=transcription_result.error_code,
                        error_message=transcription_result.error_message,
                    ).to_dict()
                )
            except VoiceTransitionError:
                state_transitions.append(self.state_controller.snapshot().to_dict())
            self._publish(
                VoiceEventType.TRANSCRIPTION_FAILED,
                message=transcription_result.error_message or "Controlled voice audio transcription failed.",
                session_id=active_session_id,
                input_id=audio.input_id,
                transcription_id=transcription_result.transcription_id,
                provider=transcription_result.provider,
                model=transcription_result.model,
                mode=interaction_mode,
                source=transcription_result.source,
                state=self.state_controller.snapshot().state.value,
                error_code=transcription_result.error_code,
            )
            core_result = None
            spoken_response = None
            if transcription_result.error_code == "transcription_uncertain":
                core_result = VoiceCoreResult(
                    result_state="clarification_required",
                    spoken_summary="I need a clearer transcript before acting.",
                    visual_summary="The controlled audio transcription was uncertain.",
                    route_family=None,
                    subsystem="voice",
                    trust_posture="none",
                    verification_posture="not_verified",
                    task_id=None,
                    speak_allowed=True,
                    continue_listening=False,
                    error_code="transcription_uncertain",
                    provenance={"source": transcription_result.source, "input_id": audio.input_id},
                )
                spoken_response = self.speech_renderer.render(
                    SpokenResponseRequest(
                        source_result_state=core_result.result_state,
                        spoken_summary=core_result.spoken_summary,
                        visual_text=core_result.visual_summary,
                        speak_allowed=core_result.speak_allowed,
                        spoken_responses_enabled=self.config.spoken_responses_enabled,
                    )
                )
            result = VoiceTurnResult(
                ok=False,
                core_result=core_result,
                transcription_result=transcription_result,
                spoken_response=spoken_response,
                voice_state_before=state_before,
                voice_state_after=self.state_controller.snapshot().to_dict(),
                state_transitions=state_transitions,
                error_code=transcription_result.error_code,
                error_message=transcription_result.error_message,
                provider_network_call_count=self._provider_network_call_count(),
                stt_invoked=True,
                tts_invoked=False,
                realtime_invoked=False,
                audio_playback_started=False,
            )
            self._publish(
                VoiceEventType.TURN_FAILED,
                message="Audio voice turn failed before Core routing.",
                session_id=active_session_id,
                input_id=audio.input_id,
                transcription_id=transcription_result.transcription_id,
                provider=transcription_result.provider,
                model=transcription_result.model,
                mode=interaction_mode,
                source=transcription_result.source,
                state=self.state_controller.snapshot().state.value,
                error_code=transcription_result.error_code,
                result_state=core_result.result_state if core_result is not None else "failed",
            )
            return self._remember_audio_turn_result(result)

        self._publish(
            VoiceEventType.TRANSCRIPTION_COMPLETED,
            message="Controlled voice audio transcription completed.",
            session_id=active_session_id,
            input_id=audio.input_id,
            transcription_id=transcription_result.transcription_id,
            provider=transcription_result.provider,
            model=transcription_result.model,
            mode=interaction_mode,
            source=transcription_result.source,
            state=VoiceState.TRANSCRIBING.value,
            metadata={
                "transcript_preview": self._preview_text(transcription_result.transcript),
                "uncertain": transcription_result.transcription_uncertain,
            },
        )

        turn_metadata = dict(metadata or {})
        turn_metadata.update(
            {
                "turn_source": transcription_result.source,
                "no_microphone_capture": True,
                "controlled_audio_transcript": True,
                "audio_input": audio.to_metadata(),
                "transcription": {
                    "transcription_id": transcription_result.transcription_id,
                    "provider": transcription_result.provider,
                    "model": transcription_result.model,
                    "source": transcription_result.source,
                    "confidence": transcription_result.confidence,
                    "uncertain": transcription_result.transcription_uncertain,
                    "usable_for_core_turn": transcription_result.usable_for_core_turn,
                },
            }
        )
        if audio_dev_override:
            turn_metadata["audio_dev_override"] = True

        normalized_transcript = " ".join(transcription_result.transcript.split()).strip()
        turn = VoiceTurn(
            session_id=active_session_id,
            transcript=normalized_transcript,
            normalized_transcript=normalized_transcript,
            source=transcription_result.source,
            interaction_mode=interaction_mode,
            availability_snapshot=self.availability.to_dict(),
            voice_state_before=state_before,
            screen_context_permission=screen_context_permission,
            confirmation_intent=confirmation_intent,
            interrupt_intent=interrupt_intent,
            transcript_confidence=transcription_result.confidence,
            transcription_provider=transcription_result.provider,
            transcription_model=transcription_result.model,
            transcription_uncertain=transcription_result.transcription_uncertain,
            transcription_id=transcription_result.transcription_id,
            metadata=turn_metadata,
            core_bridge_required=True,
        )

        state_transitions.append(
            self.state_controller.transition_to(
                VoiceState.CORE_ROUTING,
                event_id=self._last_event_id(),
                turn_id=turn.turn_id,
                source=transcription_result.source,
            ).to_dict()
        )
        self._publish(
            VoiceEventType.CORE_REQUEST_STARTED,
            message="Audio voice turn entered the Core bridge.",
            turn=turn,
            input_id=audio.input_id,
            transcription_id=transcription_result.transcription_id,
            provider=transcription_result.provider,
            model=transcription_result.model,
            state=VoiceState.CORE_ROUTING.value,
        )
        core_request = VoiceCoreRequest(
            transcript=normalized_transcript,
            session_id=active_session_id,
            turn_id=turn.turn_id,
            voice_mode="stt",
            interaction_mode=interaction_mode,
            screen_context_permission=screen_context_permission,
            confirmation_intent=confirmation_intent,
            interrupt_intent=interrupt_intent,
            metadata=turn_metadata,
        )

        try:
            core_result = await submit_voice_core_request(self.core_bridge, core_request)
            state_transitions.append(
                self.state_controller.transition_to(
                    VoiceState.THINKING,
                    event_id=self._last_event_id(),
                    turn_id=turn.turn_id,
                    source="core_bridge",
                ).to_dict()
            )
            self._publish(
                VoiceEventType.CORE_REQUEST_COMPLETED,
                message="Audio voice Core bridge request completed.",
                turn=turn,
                input_id=audio.input_id,
                transcription_id=transcription_result.transcription_id,
                provider=transcription_result.provider,
                model=transcription_result.model,
                state=VoiceState.THINKING.value,
                result_state=core_result.result_state,
                route_family=core_result.route_family,
                subsystem=core_result.subsystem,
            )
        except Exception as error:
            core_result = VoiceCoreResult(
                result_state="failed",
                spoken_summary="",
                visual_summary="Audio voice Core bridge failed.",
                route_family=None,
                subsystem="voice",
                trust_posture=None,
                verification_posture=None,
                task_id=None,
                speak_allowed=False,
                continue_listening=False,
                error_code=f"core_bridge_failed:{error}",
                provenance={"source": "voice", "error": str(error)},
            )
            try:
                state_transitions.append(
                    self.state_controller.transition_to(
                        VoiceState.ERROR,
                        event_id=self._last_event_id(),
                        turn_id=turn.turn_id,
                        source="core_bridge",
                        error_code="core_bridge_failed",
                        error_message=str(error),
                    ).to_dict()
                )
            except VoiceTransitionError:
                state_transitions.append(self.state_controller.snapshot().to_dict())
            result = VoiceTurnResult(
                ok=False,
                turn=turn,
                core_request=core_request,
                core_result=core_result,
                transcription_result=transcription_result,
                voice_state_before=state_before,
                voice_state_after=self.state_controller.snapshot().to_dict(),
                state_transitions=state_transitions,
                error_code="core_bridge_failed",
                error_message=str(error),
                provider_network_call_count=self._provider_network_call_count(),
                stt_invoked=True,
            )
            self._publish(
                VoiceEventType.TURN_FAILED,
                message="Audio voice turn failed in Core bridge.",
                turn=turn,
                input_id=audio.input_id,
                transcription_id=transcription_result.transcription_id,
                provider=transcription_result.provider,
                model=transcription_result.model,
                state=VoiceState.ERROR.value,
                result_state="failed",
                error_code="core_bridge_failed",
            )
            return self._remember_audio_turn_result(result)

        spoken_response = self.speech_renderer.render(
            SpokenResponseRequest(
                source_result_state=core_result.result_state,
                spoken_summary=core_result.spoken_summary,
                visual_text=core_result.visual_summary,
                speak_allowed=core_result.speak_allowed,
                spoken_responses_enabled=self.config.spoken_responses_enabled,
            )
        )
        self._publish(
            VoiceEventType.SPOKEN_RESPONSE_PREPARED,
            message="Audio voice spoken response preview prepared.",
            turn=turn,
            input_id=audio.input_id,
            transcription_id=transcription_result.transcription_id,
            provider=transcription_result.provider,
            model=transcription_result.model,
            state=self.state_controller.snapshot().state.value,
            result_state=core_result.result_state,
            route_family=core_result.route_family,
            subsystem=core_result.subsystem,
            metadata={"should_speak": spoken_response.should_speak, "text_only_preview": True},
        )

        next_state = self._state_after_core_result(core_result)
        if next_state == VoiceState.AWAITING_CONFIRMATION:
            state_transitions.append(
                self.state_controller.transition_to(
                    VoiceState.AWAITING_CONFIRMATION,
                    event_id=self._last_event_id(),
                    turn_id=turn.turn_id,
                    source="core_bridge",
                ).to_dict()
            )
        else:
            if spoken_response.should_speak:
                state_transitions.append(
                    self.state_controller.transition_to(
                        VoiceState.SPEAKING_READY,
                        event_id=self._last_event_id(),
                        turn_id=turn.turn_id,
                        source="spoken_response_renderer",
                    ).to_dict()
                )
            state_transitions.append(
                self.state_controller.transition_to(
                    VoiceState.DORMANT,
                    event_id=self._last_event_id(),
                    turn_id=turn.turn_id,
                    source=transcription_result.source,
                ).to_dict()
            )

        final_state = self.state_controller.snapshot().to_dict()
        turn = replace(turn, voice_state_after=final_state)
        ok = core_result.result_state not in {"failed", "blocked_unavailable"}
        result = VoiceTurnResult(
            ok=ok,
            turn=turn,
            core_request=core_request,
            core_result=core_result,
            transcription_result=transcription_result,
            spoken_response=spoken_response,
            voice_state_before=state_before,
            voice_state_after=final_state,
            state_transitions=state_transitions,
            error_code=core_result.error_code,
            error_message=None,
            provider_network_call_count=self._provider_network_call_count(),
            stt_invoked=True,
            tts_invoked=False,
            realtime_invoked=False,
            audio_playback_started=False,
        )
        self._publish(
            VoiceEventType.TURN_COMPLETED if ok else VoiceEventType.TURN_FAILED,
            message="Audio voice turn completed." if ok else "Audio voice turn failed.",
            turn=turn,
            input_id=audio.input_id,
            transcription_id=transcription_result.transcription_id,
            provider=transcription_result.provider,
            model=transcription_result.model,
            state=self.state_controller.snapshot().state.value,
            result_state=core_result.result_state,
            route_family=core_result.route_family,
            subsystem=core_result.subsystem,
            error_code=core_result.error_code,
        )
        return self._remember_audio_turn_result(result)

    async def synthesize_turn_response(
        self,
        turn_result: VoiceTurnResult,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceSpeechSynthesisResult:
        spoken_response = turn_result.spoken_response
        if spoken_response is None and turn_result.core_result is not None:
            spoken_response = self.speech_renderer.render(
                SpokenResponseRequest(
                    source_result_state=turn_result.core_result.result_state,
                    spoken_summary=turn_result.core_result.spoken_summary,
                    visual_text=turn_result.core_result.visual_summary,
                    speak_allowed=turn_result.core_result.speak_allowed,
                    spoken_responses_enabled=self.config.spoken_responses_enabled,
                )
            )
        active_session_id = session_id or (turn_result.turn.session_id if turn_result.turn is not None else None)
        turn_id = turn_result.turn.turn_id if turn_result.turn is not None else None
        if spoken_response is None or not spoken_response.should_speak:
            request = self._build_speech_request(
                text="",
                source="core_spoken_summary",
                persona_mode=turn_result.turn.interaction_mode if turn_result.turn is not None else "ghost",
                speech_length_hint="short",
                session_id=active_session_id,
                turn_id=turn_id,
                result_state_source=turn_result.core_result.result_state if turn_result.core_result is not None else None,
                metadata=metadata,
                allowed_to_synthesize=False,
                blocked_reason="spoken_response_not_allowed",
            )
            return self._remember_synthesis_result(
                self._blocked_synthesis_result(
                    request,
                    error_code="spoken_response_not_allowed",
                    error_message="Spoken response candidate is not approved for synthesis.",
                )
            )

        request = self._build_speech_request(
            text=spoken_response.spoken_text,
            source="core_spoken_summary",
            persona_mode=turn_result.turn.interaction_mode if turn_result.turn is not None else "ghost",
            speech_length_hint=spoken_response.speech_length_hint,
            session_id=active_session_id,
            turn_id=turn_id,
            result_state_source=turn_result.core_result.result_state if turn_result.core_result is not None else spoken_response.source_result_state,
            metadata={
                **dict(metadata or {}),
                "core_result": turn_result.core_result.to_dict() if turn_result.core_result is not None else None,
            },
        )
        return await self.synthesize_speech_request(request)

    async def synthesize_speech_text(
        self,
        text: str,
        *,
        source: str = "manual_test",
        persona_mode: str = "test",
        speech_length_hint: str = "short",
        session_id: str | None = None,
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceSpeechSynthesisResult:
        request = self._build_speech_request(
            text=text,
            source=source,
            persona_mode=persona_mode,
            speech_length_hint=speech_length_hint,
            session_id=session_id,
            turn_id=turn_id,
            metadata=metadata,
        )
        return await self.synthesize_speech_request(request)

    async def synthesize_speech_request(self, request: VoiceSpeechRequest) -> VoiceSpeechSynthesisResult:
        block_reason = request.blocked_reason or self._tts_request_block_reason(request)
        if block_reason is not None:
            blocked_request = replace(request, allowed_to_synthesize=False, blocked_reason=block_reason)
            self.last_openai_tts_call_attempted = False
            self.last_openai_tts_call_blocked_reason = block_reason
            self._publish(
                VoiceEventType.SPEECH_REQUEST_BLOCKED,
                message=f"Voice speech request blocked: {block_reason}.",
                session_id=blocked_request.session_id,
                speech_request_id=blocked_request.speech_request_id,
                provider=blocked_request.provider,
                model=blocked_request.model,
                voice=blocked_request.voice,
                format=blocked_request.format,
                mode=blocked_request.persona_mode,
                source=blocked_request.source,
                error_code=block_reason,
                status="blocked",
                metadata={"speech_request": blocked_request.to_metadata()},
            )
            return self._remember_synthesis_result(
                self._blocked_synthesis_result(
                    blocked_request,
                    error_code=block_reason,
                    error_message=f"Voice speech synthesis blocked: {block_reason}.",
                )
            )

        allowed_request = replace(request, allowed_to_synthesize=True, blocked_reason=None)
        self.last_speech_request = allowed_request
        self.last_openai_tts_call_blocked_reason = None
        self._publish(
            VoiceEventType.SPEECH_REQUEST_CREATED,
            message="Voice speech request created.",
            session_id=allowed_request.session_id,
            turn_id=allowed_request.turn_id,
            speech_request_id=allowed_request.speech_request_id,
            provider=allowed_request.provider,
            model=allowed_request.model,
            voice=allowed_request.voice,
            format=allowed_request.format,
            mode=allowed_request.persona_mode,
            source=allowed_request.source,
            status="created",
            metadata={"speech_request": allowed_request.to_metadata()},
        )
        self._publish(
            VoiceEventType.SYNTHESIS_STARTED,
            message="Voice speech synthesis started.",
            session_id=allowed_request.session_id,
            turn_id=allowed_request.turn_id,
            speech_request_id=allowed_request.speech_request_id,
            provider=allowed_request.provider,
            model=allowed_request.model,
            voice=allowed_request.voice,
            format=allowed_request.format,
            mode=allowed_request.persona_mode,
            source=allowed_request.source,
            status="started",
        )

        before_network_count = self._provider_network_call_count()
        synthesis = await self._synthesize_with_provider(allowed_request)
        after_network_count = self._provider_network_call_count()
        self.last_openai_tts_call_attempted = (
            synthesis.provider == "openai" and after_network_count > before_network_count
        )
        event_type = VoiceEventType.SYNTHESIS_COMPLETED if synthesis.ok else VoiceEventType.SYNTHESIS_FAILED
        self._publish(
            event_type,
            message="Voice speech synthesis completed." if synthesis.ok else "Voice speech synthesis failed.",
            session_id=allowed_request.session_id,
            turn_id=allowed_request.turn_id,
            speech_request_id=allowed_request.speech_request_id,
            synthesis_id=synthesis.synthesis_id,
            audio_output_id=synthesis.audio_output.output_id if synthesis.audio_output is not None else None,
            provider=synthesis.provider,
            model=synthesis.model,
            voice=synthesis.voice,
            format=synthesis.format,
            mode=allowed_request.persona_mode,
            source=allowed_request.source,
            status=synthesis.status,
            error_code=synthesis.error_code,
            metadata={
                "audio_output": synthesis.audio_output.to_metadata() if synthesis.audio_output is not None else None,
                "playable": synthesis.playable,
                "persisted": synthesis.persisted,
            },
        )
        if synthesis.ok and synthesis.audio_output is not None:
            self._publish(
                VoiceEventType.AUDIO_OUTPUT_CREATED,
                message="Voice speech audio output artifact created.",
                session_id=allowed_request.session_id,
                turn_id=allowed_request.turn_id,
                speech_request_id=allowed_request.speech_request_id,
                synthesis_id=synthesis.synthesis_id,
                audio_output_id=synthesis.audio_output.output_id,
                provider=synthesis.provider,
                model=synthesis.model,
                voice=synthesis.voice,
                format=synthesis.format,
                mode=allowed_request.persona_mode,
                source="tts",
                status="created",
                metadata={"audio_output": synthesis.audio_output.to_metadata()},
            )
        return self._remember_synthesis_result(synthesis)

    async def play_speech_output(
        self,
        audio_output: VoiceAudioOutput | VoiceSpeechSynthesisResult | None,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoicePlaybackResult:
        output, synthesis = self._resolve_playback_audio_output(audio_output)
        resolved_session_id = session_id
        resolved_turn_id = turn_id
        synthesis_id = synthesis.synthesis_id if synthesis is not None else None
        if synthesis is not None and synthesis.speech_request is not None:
            resolved_session_id = resolved_session_id or synthesis.speech_request.session_id
            resolved_turn_id = resolved_turn_id or synthesis.speech_request.turn_id

        request = self._build_playback_request(
            output,
            synthesis_id=synthesis_id,
            session_id=resolved_session_id,
            turn_id=resolved_turn_id,
            metadata=metadata,
            blocked_reason="missing_audio_output" if output is None else None,
        )
        return await self.playback_request(request)

    async def play_turn_response(
        self,
        turn_result: VoiceTurnResult,
        *,
        synthesize_if_needed: bool = True,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoicePlaybackResult:
        if not synthesize_if_needed:
            request = self._build_playback_request(
                None,
                session_id=session_id or (turn_result.turn.session_id if turn_result.turn is not None else None),
                turn_id=turn_result.turn.turn_id if turn_result.turn is not None else None,
                metadata=metadata,
                blocked_reason="synthesis_required",
            )
            return await self.playback_request(request)
        synthesis = await self.synthesize_turn_response(turn_result, session_id=session_id, metadata=metadata)
        return await self.play_speech_output(
            synthesis,
            session_id=session_id,
            turn_id=turn_result.turn.turn_id if turn_result.turn is not None else None,
            metadata=metadata,
        )

    async def playback_request(self, request: VoicePlaybackRequest) -> VoicePlaybackResult:
        block_reason = self._playback_request_block_reason(request)
        if block_reason is not None:
            blocked_request = replace(request, allowed_to_play=False, blocked_reason=block_reason)
            self._publish(
                VoiceEventType.PLAYBACK_BLOCKED,
                message=f"Voice playback request blocked: {block_reason}.",
                session_id=blocked_request.session_id,
                turn_id=blocked_request.turn_id,
                playback_request_id=blocked_request.playback_request_id,
                audio_output_id=blocked_request.audio_output_id,
                synthesis_id=blocked_request.synthesis_id,
                provider=blocked_request.provider,
                device=blocked_request.device,
                mode=self.config.mode,
                source=blocked_request.source,
                status="blocked",
                error_code=block_reason,
                metadata={"playback_request": blocked_request.to_metadata()},
            )
            return self._remember_playback_result(
                self._blocked_playback_result(
                    blocked_request,
                    error_code=block_reason,
                    error_message=f"Voice playback blocked: {block_reason}.",
                )
            )

        allowed_request = replace(request, allowed_to_play=True, blocked_reason=None)
        self.last_playback_request = allowed_request
        self._publish(
            VoiceEventType.PLAYBACK_REQUEST_CREATED,
            message="Voice playback request created.",
            session_id=allowed_request.session_id,
            turn_id=allowed_request.turn_id,
            playback_request_id=allowed_request.playback_request_id,
            audio_output_id=allowed_request.audio_output_id,
            synthesis_id=allowed_request.synthesis_id,
            provider=allowed_request.provider,
            device=allowed_request.device,
            mode=self.config.mode,
            source=allowed_request.source,
            status="created",
            metadata={"playback_request": allowed_request.to_metadata()},
        )
        self._transition_to_speaking(allowed_request)

        result = await self._play_with_provider(allowed_request)
        if result.ok and result.status in {"started", "completed"}:
            self._publish_playback_started(result)
        if result.status == "completed":
            self._publish_playback_terminal(VoiceEventType.PLAYBACK_COMPLETED, result, "Voice playback completed.")
            self._cleanup_transient_playback_audio(allowed_request)
            self._transition_from_speaking(completed=True)
        elif result.status == "started":
            self._publish(
                VoiceEventType.STATE_CHANGED,
                message="Voice state changed for local playback.",
                session_id=result.session_id,
                turn_id=result.turn_id,
                playback_request_id=result.playback_request_id,
                playback_id=result.playback_id,
                audio_output_id=result.audio_output_id,
                synthesis_id=result.synthesis_id,
                provider=result.provider,
                device=result.device,
                state=VoiceState.SPEAKING.value,
                status=result.status,
                source="playback",
            )
        elif result.status == "blocked":
            self._publish_playback_terminal(VoiceEventType.PLAYBACK_BLOCKED, result, "Voice playback blocked.")
            self._transition_from_speaking(completed=False)
        else:
            self._publish_playback_terminal(VoiceEventType.PLAYBACK_FAILED, result, "Voice playback failed.")
            self._transition_from_speaking(completed=False)
        return self._remember_playback_result(result)

    async def stop_playback(
        self,
        playback_id: str | None = None,
        *,
        reason: str = "user_requested",
    ) -> VoicePlaybackResult:
        operation = getattr(self.playback_provider, "stop", None)
        if not callable(operation):
            result = VoicePlaybackResult(
                ok=False,
                playback_request_id=None,
                audio_output_id=None,
                provider=self._playback_provider_name(),
                device=self.config.playback.device,
                status="unavailable",
                error_code="provider_unavailable",
                error_message="Voice playback provider does not support stop.",
                output_metadata={"reason": reason},
                played_locally=False,
                user_heard_claimed=False,
            )
        else:
            result = operation(playback_id, reason=reason)
            if inspect.isawaitable(result):
                result = await result

        if result.status == "stopped":
            self._publish_playback_terminal(VoiceEventType.PLAYBACK_STOPPED, result, "Voice playback stopped.")
            self._transition_from_speaking(stopped=True)
        else:
            self._publish_playback_terminal(VoiceEventType.PLAYBACK_FAILED, result, "Voice playback stop request found no active playback.")
        return self._remember_playback_result(result)

    def status_snapshot(self) -> dict[str, Any]:
        state = self.state_controller.snapshot()
        availability = self.availability.to_dict()
        played_locally = bool(self.last_playback_result and self.last_playback_result.played_locally)
        return {
            "phase": "voice0",
            "current_phase": "voice4",
            "configured": True,
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "openai": {
                "enabled": self.openai_config.enabled,
                "configured": bool(self.openai_config.api_key),
                "base_url": self.openai_config.base_url,
            },
            "provider": {
                "name": self.availability.provider_name or self.config.provider,
                "configured": self.availability.provider_configured,
                "availability": availability,
                "mock_provider_active": self.availability.mock_provider_active,
                "implementation": self.provider.name,
            },
            "state": state.to_dict(),
            "realtime_enabled": self.config.realtime_enabled,
            "wake_enabled": self.config.wake_word_enabled,
            "spoken_responses_enabled": self.config.spoken_responses_enabled,
            "manual_input_enabled": self.config.manual_input_enabled,
            "mock_provider_active": self.availability.mock_provider_active,
            "last_error": {
                "code": self.last_error.get("code") or state.error_code,
                "message": self.last_error.get("message") or state.error_message,
            },
            "last_event": self.last_event,
            "last_state_transition": state.last_transition_at,
            "manual_turns": self._manual_turn_status_snapshot(),
            "stt": self._stt_status_snapshot(),
            "tts": self._tts_status_snapshot(),
            "playback": self._playback_status_snapshot(),
            "runtime_truth": {
                "manual_transcript_path_available": True,
                "controlled_audio_file_or_blob_only": True,
                "controlled_tts_audio_artifacts_only": True,
                "controlled_local_playback_boundary": True,
                "no_real_audio": True,
                "no_microphone": True,
                "no_microphone_capture": True,
                "no_wake_word": True,
                "no_vad": True,
                "no_live_listening": True,
                "no_live_stt": True,
                "no_stt": False,
                "no_tts": False,
                "no_live_tts": True,
                "no_realtime": True,
                "no_audio_playback": not played_locally,
                "no_live_conversation_loop": True,
                "no_continuous_loop": True,
                "user_heard_claimed": False,
            },
            "capabilities": {
                "configuration_loaded": True,
                "availability_model": True,
                "state_machine": True,
                "provider_interfaces": True,
                "mock_provider": True,
                "core_bridge_contract": True,
                "spoken_response_renderer": True,
                "voice_events": True,
                "manual_transcript_turns": True,
                "controlled_audio_transcription": True,
                "openai_stt_provider": True,
                "controlled_tts_synthesis": True,
                "openai_tts_provider": True,
                "controlled_local_playback": True,
                "core_bridge_routing": self.core_bridge is not None,
                "real_microphone_capture": False,
                "real_wake_word_detection": False,
                "real_openai_stt": True,
                "real_openai_tts": True,
                "openai_realtime_sessions": False,
                "audio_playback": bool(self.config.playback.enabled),
            },
            "truthfulness_contract": {
                "core_bridge_required": True,
                "direct_tool_execution_allowed": False,
                "openai_required_when_provider_openai": True,
                "mock_provider_must_be_reported": True,
                "no_audio_runtime_in_voice0": True,
                "manual_turns_route_through_core": True,
                "audio_turns_route_through_core": True,
                "tts_uses_approved_spoken_response": True,
                "tts_generation_does_not_imply_playback": True,
                "playback_does_not_imply_task_success": True,
                "playback_does_not_claim_user_heard": True,
                "raw_audio_persisted_by_default": False,
            },
            "planned_not_implemented": {
                "microphone_capture": "not_implemented",
                "wake_word_detection": "not_implemented",
                "openai_stt": "controlled_audio_only",
                "openai_tts": "controlled_audio_output_only",
                "openai_realtime": "not_implemented",
                "streaming_transcription": "not_implemented",
                "continuous_listening": "not_implemented",
                "barge_in": "not_implemented",
                "audio_playback": "controlled_local_boundary_only",
            },
        }

    def _build_speech_request(
        self,
        *,
        text: str,
        source: str,
        persona_mode: str,
        speech_length_hint: str,
        session_id: str | None = None,
        turn_id: str | None = None,
        result_state_source: str | None = None,
        metadata: dict[str, Any] | None = None,
        allowed_to_synthesize: bool = False,
        blocked_reason: str | None = None,
    ) -> VoiceSpeechRequest:
        return VoiceSpeechRequest(
            source=str(source or "manual_test").strip() or "manual_test",
            text=text,
            persona_mode=str(persona_mode or "ghost").strip().lower() or "ghost",
            speech_length_hint=str(speech_length_hint or "short").strip().lower() or "short",
            provider=getattr(self.provider, "name", self.availability.provider_name or self.config.provider),
            model=self._tts_model_name(),
            voice=self._tts_voice_name(),
            format=self._tts_format_name(),
            result_state_source=result_state_source,
            turn_id=turn_id,
            session_id=session_id,
            metadata=dict(metadata or {}),
            allowed_to_synthesize=allowed_to_synthesize,
            blocked_reason=blocked_reason,
        )

    def _tts_request_block_reason(self, request: VoiceSpeechRequest) -> str | None:
        if not self.config.enabled or str(self.config.mode or "").strip().lower() == "disabled":
            return "voice_disabled"
        if not self.config.spoken_responses_enabled:
            return "spoken_responses_disabled"
        if not self.availability.available and not self.config.debug_mock_provider:
            return self.availability.unavailable_reason or "provider_unavailable"
        if not self.availability.tts_allowed and not self.config.debug_mock_provider:
            return "tts_disabled"

        text = str(request.text or "").strip()
        if not text:
            return "empty_speech_text"
        if len(text) > int(self.config.openai.max_tts_chars or 0):
            return "text_too_long"

        lowered = text.lower()
        if any(marker in lowered for marker in _UNSAFE_SPEECH_MARKERS):
            return "unsafe_speech_text"
        if (
            request.source != "core_spoken_summary"
            and any(phrase in lowered for phrase in _UNSAFE_UNAPPROVED_PHRASES)
        ):
            return "unsafe_speech_text"
        if "verified" in lowered and str(request.result_state_source or "").strip().lower() != "verified":
            return "unsupported_verification_claim"
        return None

    async def _synthesize_with_provider(self, request: VoiceSpeechRequest) -> VoiceSpeechSynthesisResult:
        operation = getattr(self.provider, "synthesize_speech", None)
        if not callable(operation):
            return self._blocked_synthesis_result(
                request,
                error_code="provider_unavailable",
                error_message="Voice provider does not implement text-to-speech.",
                status="unavailable",
            )
        result = operation(request)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, VoiceSpeechSynthesisResult):
            return result
        if isinstance(result, VoiceProviderOperationResult):
            status = "succeeded" if result.ok else "failed"
            return VoiceSpeechSynthesisResult(
                ok=result.ok,
                speech_request_id=request.speech_request_id,
                speech_request=request,
                provider=result.provider_name,
                model=request.model,
                voice=request.voice,
                format=request.format,
                status=status,
                error_code=result.error_code,
                error_message=result.error_message,
                raw_provider_metadata=dict(result.payload),
                playable=False,
                persisted=False,
            )
        return self._blocked_synthesis_result(
            request,
            error_code="provider_invalid_result",
            error_message="Voice TTS provider returned an unsupported result.",
            status="failed",
        )

    def _blocked_synthesis_result(
        self,
        request: VoiceSpeechRequest,
        *,
        error_code: str,
        error_message: str,
        status: str = "blocked",
    ) -> VoiceSpeechSynthesisResult:
        return VoiceSpeechSynthesisResult(
            ok=False,
            speech_request_id=request.speech_request_id,
            speech_request=request,
            provider=request.provider,
            model=request.model,
            voice=request.voice,
            format=request.format,
            status=status,
            error_code=error_code,
            error_message=error_message,
            playable=False,
            persisted=False,
        )

    def _remember_synthesis_result(self, result: VoiceSpeechSynthesisResult) -> VoiceSpeechSynthesisResult:
        self.last_speech_request = result.speech_request
        self.last_synthesis_result = result
        if result.error_code:
            self.last_error = {"code": result.error_code, "message": result.error_message}
        else:
            self.last_error = {"code": None, "message": None}
        return result

    def _resolve_playback_audio_output(
        self,
        value: VoiceAudioOutput | VoiceSpeechSynthesisResult | None,
    ) -> tuple[VoiceAudioOutput | None, VoiceSpeechSynthesisResult | None]:
        if isinstance(value, VoiceSpeechSynthesisResult):
            return value.audio_output if value.ok else None, value
        if isinstance(value, VoiceAudioOutput):
            return value, None
        return None, None

    def _build_playback_request(
        self,
        audio_output: VoiceAudioOutput | None,
        *,
        synthesis_id: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        blocked_reason: str | None = None,
    ) -> VoicePlaybackRequest:
        audio_metadata = audio_output.to_metadata() if audio_output is not None else {}
        duration = audio_metadata.get("duration_ms")
        nested_metadata = audio_metadata.get("metadata")
        if not isinstance(duration, int) and isinstance(nested_metadata, dict):
            nested_duration = nested_metadata.get("duration_ms")
            duration = nested_duration if isinstance(nested_duration, int) else duration
        request_metadata = dict(metadata or {})
        if audio_metadata:
            request_metadata["audio_output"] = audio_metadata
        return VoicePlaybackRequest(
            audio_output_id=audio_output.output_id if audio_output is not None else None,
            synthesis_id=synthesis_id,
            session_id=session_id,
            turn_id=turn_id,
            source="tts_output" if audio_output is not None else "missing_audio",
            audio_ref=audio_output.bytes_ref if audio_output is not None else None,
            file_path=audio_output.file_path if audio_output is not None else None,
            format=audio_output.format if audio_output is not None else "",
            mime_type=audio_output.mime_type if audio_output is not None else "",
            size_bytes=audio_output.size_bytes if audio_output is not None else 0,
            duration_ms=duration if isinstance(duration, int) else None,
            provider=self._playback_provider_name(),
            device=self.config.playback.device,
            volume=self.config.playback.volume,
            expires_at=audio_output.expires_at if audio_output is not None else None,
            metadata=request_metadata,
            allowed_to_play=False,
            blocked_reason=blocked_reason,
        )

    def _playback_request_block_reason(self, request: VoicePlaybackRequest) -> str | None:
        if not self.config.enabled or str(self.config.mode or "").strip().lower() == "disabled":
            return "voice_disabled"
        if not self.config.playback.enabled:
            return "playback_disabled"
        if not self.availability.available and not (self.config.debug_mock_provider and self.config.playback.allow_dev_playback):
            return self.availability.unavailable_reason or "voice_unavailable"
        if request.blocked_reason:
            return request.blocked_reason
        if not request.audio_output_id or (not request.audio_ref and not request.file_path):
            return "missing_audio_output"
        if request.size_bytes <= 0:
            return "empty_audio_output"
        if request.size_bytes > int(self.config.playback.max_audio_bytes or 0):
            return "audio_too_large"
        if request.duration_ms is not None and request.duration_ms > int(self.config.playback.max_duration_ms or 0):
            return "audio_too_long"
        if request.format not in _SUPPORTED_PLAYBACK_FORMATS:
            return "unsupported_playback_format"
        if request.expires_at and self._is_expired(request.expires_at):
            return "audio_output_expired"
        return None

    async def _play_with_provider(self, request: VoicePlaybackRequest) -> VoicePlaybackResult:
        operation = getattr(self.playback_provider, "play", None)
        if not callable(operation):
            return self._blocked_playback_result(
                request,
                error_code="provider_unavailable",
                error_message="Voice playback provider does not implement playback.",
                status="unavailable",
            )
        result = operation(request)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, VoicePlaybackResult):
            return result
        return self._blocked_playback_result(
            request,
            error_code="provider_invalid_result",
            error_message="Voice playback provider returned an unsupported result.",
            status="failed",
        )

    def _blocked_playback_result(
        self,
        request: VoicePlaybackRequest,
        *,
        error_code: str,
        error_message: str,
        status: str = "blocked",
    ) -> VoicePlaybackResult:
        return VoicePlaybackResult(
            ok=False,
            playback_request_id=request.playback_request_id,
            audio_output_id=request.audio_output_id,
            synthesis_id=request.synthesis_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            provider=request.provider,
            device=request.device,
            status=status,
            error_code=error_code,
            error_message=error_message,
            output_metadata={
                "audio_output_id": request.audio_output_id,
                "format": request.format,
                "mime_type": request.mime_type,
                "size_bytes": request.size_bytes,
                "duration_ms": request.duration_ms,
            },
            played_locally=False,
            user_heard_claimed=False,
        )

    def _remember_playback_result(self, result: VoicePlaybackResult) -> VoicePlaybackResult:
        self.last_playback_result = result
        if result.error_code:
            self.last_error = {"code": result.error_code, "message": result.error_message}
        else:
            self.last_error = {"code": None, "message": None}
        return result

    def _playback_provider_name(self) -> str:
        return str(getattr(self.playback_provider, "name", self.config.playback.provider) or self.config.playback.provider).strip().lower()

    def _playback_provider_availability(self) -> dict[str, Any]:
        operation = getattr(self.playback_provider, "get_availability", None)
        if callable(operation):
            try:
                value = operation()
            except Exception as error:
                return {"provider": self._playback_provider_name(), "available": False, "unavailable_reason": str(error)}
            if isinstance(value, dict):
                return dict(value)
        return {"provider": self._playback_provider_name(), "available": False, "unavailable_reason": "provider_unavailable"}

    def _active_playback(self) -> VoicePlaybackResult | None:
        operation = getattr(self.playback_provider, "get_active_playback", None)
        if not callable(operation):
            return None
        try:
            value = operation()
        except Exception:
            return None
        return value if isinstance(value, VoicePlaybackResult) else None

    def _publish_playback_started(self, result: VoicePlaybackResult) -> None:
        self._publish(
            VoiceEventType.PLAYBACK_STARTED,
            message="Voice local playback started.",
            session_id=result.session_id,
            turn_id=result.turn_id,
            playback_request_id=result.playback_request_id,
            playback_id=result.playback_id,
            audio_output_id=result.audio_output_id,
            synthesis_id=result.synthesis_id,
            provider=result.provider,
            device=result.device,
            mode=self.config.mode,
            state=VoiceState.SPEAKING.value,
            status="started",
            source="playback",
            metadata={"playback": result.to_dict()},
        )

    def _publish_playback_terminal(
        self,
        event_type: VoiceEventType,
        result: VoicePlaybackResult,
        message: str,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=result.session_id,
            turn_id=result.turn_id,
            playback_request_id=result.playback_request_id,
            playback_id=result.playback_id,
            audio_output_id=result.audio_output_id,
            synthesis_id=result.synthesis_id,
            provider=result.provider,
            device=result.device,
            mode=self.config.mode,
            state=self.state_controller.snapshot().state.value,
            status=result.status,
            source="playback",
            error_code=result.error_code,
            metadata={"playback": result.to_dict()},
        )

    def _transition_to_speaking(self, request: VoicePlaybackRequest) -> None:
        if self.state_controller.snapshot().state == VoiceState.SPEAKING:
            return
        try:
            self.state_controller.transition_to(
                VoiceState.SPEAKING,
                event_id=self._last_event_id(),
                turn_id=request.turn_id,
                source="playback",
            )
        except VoiceTransitionError:
            return

    def _transition_from_speaking(self, *, completed: bool = False, stopped: bool = False) -> None:
        if self.state_controller.snapshot().state != VoiceState.SPEAKING:
            return
        try:
            if stopped:
                self.state_controller.transition_to(
                    VoiceState.INTERRUPTED,
                    event_id=self._last_event_id(),
                    source="playback",
                )
            self.state_controller.transition_to(
                VoiceState.DORMANT,
                event_id=self._last_event_id(),
                source="playback_completed" if completed else "playback",
            )
        except VoiceTransitionError:
            return

    def _cleanup_transient_playback_audio(self, request: VoicePlaybackRequest) -> None:
        if not self.config.playback.delete_transient_after_playback:
            return
        audio_output = request.metadata.get("audio_output")
        if not isinstance(audio_output, dict) or not audio_output.get("transient"):
            return
        file_path = audio_output.get("file_path")
        if not file_path:
            return
        try:
            Path(str(file_path)).unlink(missing_ok=True)
        except OSError:
            return

    def _is_expired(self, value: str) -> bool:
        try:
            normalized = str(value).replace("Z", "+00:00")
            expires_at = datetime.fromisoformat(normalized)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        return expires_at <= datetime.now(timezone.utc)

    def _manual_turn_allowed(self) -> tuple[bool, str | None, bool]:
        if not self.config.enabled or str(self.config.mode or "").strip().lower() == "disabled":
            return False, "voice_disabled", False
        if not self.config.manual_input_enabled:
            return False, "manual_input_disabled", False
        if self.availability.available:
            return True, None, False
        if self.config.debug_mock_provider:
            return True, None, True
        return False, self.availability.unavailable_reason or "voice_unavailable", False

    def _manual_turn_availability(self, manual_dev_override: bool) -> VoiceAvailability:
        if not manual_dev_override:
            return self.availability
        return replace(
            self.availability,
            available=True,
            unavailable_reason=None,
            provider_configured=True,
            mode=str(self.config.mode or "manual").strip().lower() or "manual",
            stt_allowed=True,
            mock_provider_active=True,
        )

    def _audio_turn_allowed(self) -> tuple[bool, str | None, bool]:
        if not self.config.enabled or str(self.config.mode or "").strip().lower() == "disabled":
            return False, "voice_disabled", False
        if self.availability.available and self.availability.stt_allowed:
            return True, None, False
        if self.config.debug_mock_provider:
            return True, None, True
        return False, self.availability.unavailable_reason or "provider_unavailable", False

    def _audio_turn_availability(self, audio_dev_override: bool) -> VoiceAvailability:
        if not audio_dev_override:
            return self.availability
        return replace(
            self.availability,
            available=True,
            unavailable_reason=None,
            provider_configured=True,
            mode=str(self.config.mode or "manual").strip().lower() or "manual",
            stt_allowed=True,
            mock_provider_active=True,
        )

    def _validate_audio_input(self, audio: VoiceAudioInput) -> tuple[str, str] | None:
        if not isinstance(audio, VoiceAudioInput):
            return "invalid_audio_input", "Audio voice turn requires a typed VoiceAudioInput."
        source = str(audio.source or "").strip().lower()
        if source not in {"file", "bytes", "fixture", "mock"}:
            return "unsupported_audio_source", f"Unsupported voice audio source: {source or 'unknown'}."
        if source == "file":
            file_path = Path(str(audio.file_path or ""))
            if not audio.file_path or not file_path.exists() or not file_path.is_file():
                return "missing_audio_file", "Voice audio file was missing."
        if audio.size_bytes <= 0:
            return "empty_audio", "Voice audio input was empty."
        max_audio_bytes = int(self.config.openai.max_audio_bytes or 0)
        if max_audio_bytes > 0 and audio.size_bytes > max_audio_bytes:
            return "audio_too_large", "Voice audio input exceeded the configured size limit."
        max_audio_seconds = float(self.config.openai.max_audio_seconds or 0)
        if max_audio_seconds > 0 and audio.duration_ms is not None and audio.duration_ms > int(max_audio_seconds * 1000):
            return "audio_too_long", "Voice audio input exceeded the configured duration limit."
        mime_type = str(audio.mime_type or "").strip().lower()
        if mime_type not in _SUPPORTED_AUDIO_MIME_TYPES:
            return "unsupported_audio_type", f"Unsupported voice audio MIME type: {mime_type or 'unknown'}."
        return None

    async def _transcribe_audio(self, audio: VoiceAudioInput) -> VoiceTranscriptionResult:
        operation = getattr(self.provider, "transcribe_audio", None)
        if not callable(operation):
            return VoiceTranscriptionResult(
                ok=False,
                input_id=audio.input_id,
                provider=self.provider.name,
                model=self._stt_model_name(),
                transcript="",
                error_code="provider_unavailable",
                error_message="Voice provider does not implement speech-to-text.",
                source=f"{self.provider.name}_stt",
                usable_for_core_turn=False,
                transcription_uncertain=True,
                status="failed",
                audio_input_metadata=audio.to_metadata(),
            )
        result = operation(audio)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, VoiceTranscriptionResult):
            return result
        if isinstance(result, VoiceProviderOperationResult):
            transcript = " ".join(str(result.payload.get("transcript") or "").split()).strip()
            return VoiceTranscriptionResult(
                ok=result.ok and bool(transcript),
                input_id=audio.input_id,
                provider=result.provider_name,
                model=self._stt_model_name(),
                transcript=transcript,
                confidence=result.payload.get("confidence") if isinstance(result.payload.get("confidence"), float) else None,
                error_code=result.error_code or (None if transcript else "empty_transcript"),
                error_message=result.error_message,
                source=f"{result.provider_name}_stt",
                usable_for_core_turn=result.ok and bool(transcript),
                transcription_uncertain=not bool(transcript),
                status="completed" if result.ok and transcript else "failed",
                audio_input_metadata=audio.to_metadata(),
            )
        return VoiceTranscriptionResult(
            ok=False,
            input_id=audio.input_id,
            provider=self.provider.name,
            model=self._stt_model_name(),
            transcript="",
            error_code="provider_invalid_result",
            error_message="Voice STT provider returned an unsupported result.",
            source=f"{self.provider.name}_stt",
            usable_for_core_turn=False,
            transcription_uncertain=True,
            status="failed",
            audio_input_metadata=audio.to_metadata(),
        )

    def _apply_transcription_quality_rules(self, result: VoiceTranscriptionResult) -> VoiceTranscriptionResult:
        transcript = " ".join(str(result.transcript or "").split()).strip()
        if not result.ok:
            return result
        if not transcript:
            return replace(
                result,
                ok=False,
                transcript="",
                error_code="empty_transcript",
                error_message="Speech-to-text returned an empty transcript.",
                usable_for_core_turn=False,
                transcription_uncertain=True,
                status="failed",
            )
        lowered = transcript.lower()
        if len(lowered) <= 2 or lowered in _UNCLEAR_SHORT_TRANSCRIPTS:
            return replace(
                result,
                ok=False,
                transcript=transcript,
                error_code="transcription_uncertain",
                error_message="Speech-to-text returned an uncertain short transcript.",
                usable_for_core_turn=False,
                transcription_uncertain=True,
                status="uncertain",
            )
        return replace(result, transcript=transcript)

    def _state_after_core_result(self, core_result: VoiceCoreResult) -> VoiceState:
        result_state = str(core_result.result_state or "").strip().lower()
        if result_state in {"pending_approval", "requires_confirmation", "awaiting_confirmation"}:
            return VoiceState.AWAITING_CONFIRMATION
        return VoiceState.DORMANT

    def _record_failed_turn(
        self,
        *,
        error_code: str | None,
        error_message: str | None,
        core_result: VoiceCoreResult | None = None,
        state_transitions: list[dict[str, Any]] | None = None,
    ) -> VoiceTurnResult:
        self.last_error = {"code": error_code, "message": error_message}
        result = VoiceTurnResult(
            ok=False,
            core_result=core_result,
            voice_state_before=self.state_controller.snapshot().to_dict(),
            voice_state_after=self.state_controller.snapshot().to_dict(),
            state_transitions=list(state_transitions or [self.state_controller.snapshot().to_dict()]),
            error_code=error_code,
            error_message=error_message,
            provider_network_call_count=self._provider_network_call_count(),
        )
        return self._remember_turn_result(result)

    def _remember_turn_result(self, result: VoiceTurnResult) -> VoiceTurnResult:
        self.last_manual_turn_result = result
        if result.error_code:
            self.last_error = {"code": result.error_code, "message": result.error_message}
        else:
            self.last_error = {"code": None, "message": None}
        return result

    def _remember_audio_turn_result(self, result: VoiceTurnResult) -> VoiceTurnResult:
        self.last_audio_turn_result = result
        if result.transcription_result is not None:
            self.last_transcription_result = result.transcription_result
        if result.error_code:
            self.last_error = {"code": result.error_code, "message": result.error_message}
        else:
            self.last_error = {"code": None, "message": None}
        return result

    def _publish(
        self,
        event_type: VoiceEventType,
        *,
        message: str,
        turn: VoiceTurn | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        input_id: str | None = None,
        transcription_id: str | None = None,
        speech_request_id: str | None = None,
        synthesis_id: str | None = None,
        audio_output_id: str | None = None,
        playback_request_id: str | None = None,
        playback_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        format: str | None = None,
        device: str | None = None,
        status: str | None = None,
        mode: str | None = None,
        state: str | None = None,
        result_state: str | None = None,
        route_family: str | None = None,
        subsystem: str | None = None,
        error_code: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.events is None:
            return
        resolved_session_id = turn.session_id if turn is not None else session_id
        resolved_turn_id = turn.turn_id if turn is not None else turn_id
        resolved_provider = provider or self.availability.provider_name
        resolved_mode = turn.interaction_mode if turn is not None else mode
        resolved_source = source or (turn.source if turn is not None else "voice")
        playback_event = event_type in {
            VoiceEventType.PLAYBACK_STARTED,
            VoiceEventType.PLAYBACK_COMPLETED,
            VoiceEventType.PLAYBACK_STOPPED,
        }
        event = publish_voice_event(
            self.events,
            event_type,
            message=message,
            session_id=resolved_session_id,
            turn_id=resolved_turn_id,
            provider=resolved_provider,
            mode=resolved_mode,
            state=state,
            input_id=input_id,
            transcription_id=transcription_id,
            speech_request_id=speech_request_id,
            synthesis_id=synthesis_id,
            audio_output_id=audio_output_id,
            playback_request_id=playback_request_id,
            playback_id=playback_id,
            model=model,
            voice=voice,
            format=format,
            device=device,
            status=status,
            result_state=result_state,
            route_family=route_family,
            subsystem=subsystem,
            source=resolved_source,
            error_code=error_code,
            privacy={
                "no_raw_audio": True,
                "no_raw_audio_output": True,
                "no_microphone_capture": True,
                "no_realtime": True,
                "no_audio_playback": not playback_event,
                "user_heard_claimed": False,
            },
            metadata=metadata,
        )
        self.last_event = event.to_dict()

    def _last_event_id(self) -> str | None:
        if not isinstance(self.last_event, dict):
            return None
        value = self.last_event.get("event_id")
        return str(value) if value is not None else None

    def _normalize_interaction_mode(self, mode: str) -> str:
        normalized = str(mode or "ghost").strip().lower()
        if normalized in {"ghost", "deck", "background"}:
            return normalized
        return "ghost"

    def _provider_network_call_count(self) -> int:
        try:
            return int(getattr(self.provider, "network_call_count", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _stt_model_name(self) -> str:
        return str(getattr(self.provider, "stt_model", self.config.openai.stt_model) or self.config.openai.stt_model).strip()

    def _tts_model_name(self) -> str:
        return str(getattr(self.provider, "tts_model", self.config.openai.tts_model) or self.config.openai.tts_model).strip()

    def _tts_voice_name(self) -> str:
        return str(getattr(self.provider, "tts_voice", self.config.openai.tts_voice) or self.config.openai.tts_voice).strip()

    def _tts_format_name(self) -> str:
        return str(getattr(self.provider, "tts_format", self.config.openai.tts_format) or self.config.openai.tts_format).strip().lower()

    def _manual_turn_status_snapshot(self) -> dict[str, Any]:
        result = self.last_manual_turn_result
        turn = result.turn if result is not None else None
        core_result = result.core_result if result is not None else None
        spoken_response: SpokenResponseResult | None = result.spoken_response if result is not None else None
        return {
            "enabled": self.config.manual_input_enabled,
            "path": "manual_transcript_only",
            "last_turn_id": turn.turn_id if turn is not None else None,
            "last_transcript_preview": self._preview_text(turn.transcript) if turn is not None else None,
            "last_core_result_state": core_result.result_state if core_result is not None else None,
            "last_route_family": core_result.route_family if core_result is not None else None,
            "last_subsystem": core_result.subsystem if core_result is not None else None,
            "last_trust_posture": core_result.trust_posture if core_result is not None else None,
            "last_verification_posture": core_result.verification_posture if core_result is not None else None,
            "last_spoken_response_candidate": spoken_response.to_dict() if spoken_response is not None else None,
            "last_error": dict(self.last_error),
            "mock_dev_override_active": bool(turn and turn.metadata.get("manual_dev_override")),
            "no_real_audio": True,
            "no_stt": True,
            "no_tts": True,
            "no_realtime": True,
        }

    def _stt_status_snapshot(self) -> dict[str, Any]:
        result = self.last_audio_turn_result
        transcription = self.last_transcription_result
        turn = result.turn if result is not None else None
        provider_name = getattr(self.provider, "name", self.availability.provider_name)
        return {
            "enabled": bool(self.config.enabled and (self.availability.stt_allowed or self.config.debug_mock_provider)),
            "path": "controlled_audio_file_or_blob_only",
            "provider": transcription.provider if transcription is not None else provider_name,
            "model": transcription.model if transcription is not None else self._stt_model_name(),
            "last_turn_id": turn.turn_id if turn is not None else None,
            "last_transcription_id": transcription.transcription_id if transcription is not None else None,
            "last_transcription_state": transcription.status if transcription is not None else None,
            "last_transcript_preview": self._preview_text(transcription.transcript) if transcription is not None else None,
            "last_audio_input_metadata": self.last_audio_input_metadata,
            "last_provider_latency_ms": transcription.provider_latency_ms if transcription is not None else None,
            "last_transcription_error": {
                "code": transcription.error_code if transcription is not None else None,
                "message": transcription.error_message if transcription is not None else None,
            },
            "last_audio_validation_error": dict(self.last_audio_validation_error),
            "last_openai_call_attempted": self.last_openai_call_attempted,
            "last_openai_call_blocked_reason": self.last_openai_call_blocked_reason,
            "mock_provider_active": bool(getattr(self.provider, "is_mock", False)),
            "no_microphone_capture": True,
            "no_tts": False,
            "no_live_tts": True,
            "no_realtime": True,
            "no_audio_playback": True,
        }

    def _tts_status_snapshot(self) -> dict[str, Any]:
        request = self.last_speech_request
        synthesis = self.last_synthesis_result
        provider_name = synthesis.provider if synthesis is not None else getattr(self.provider, "name", self.availability.provider_name)
        audio_output = synthesis.audio_output if synthesis is not None else None
        return {
            "enabled": bool(self.config.enabled and self.config.spoken_responses_enabled and (self.availability.tts_allowed or self.config.debug_mock_provider)),
            "path": "controlled_tts_audio_output_only",
            "spoken_responses_enabled": self.config.spoken_responses_enabled,
            "provider": provider_name,
            "model": synthesis.model if synthesis is not None else self._tts_model_name(),
            "voice": synthesis.voice if synthesis is not None else self._tts_voice_name(),
            "format": synthesis.format if synthesis is not None else self._tts_format_name(),
            "last_speech_request_id": request.speech_request_id if request is not None else None,
            "last_synthesis_id": synthesis.synthesis_id if synthesis is not None else None,
            "last_synthesis_state": synthesis.status if synthesis is not None else None,
            "last_spoken_text_preview": self._preview_text(request.text) if request is not None else None,
            "last_audio_output_metadata": audio_output.to_metadata() if audio_output is not None else None,
            "last_provider_latency_ms": synthesis.provider_latency_ms if synthesis is not None else None,
            "last_synthesis_error": {
                "code": synthesis.error_code if synthesis is not None else None,
                "message": synthesis.error_message if synthesis is not None else None,
            },
            "last_openai_tts_call_attempted": self.last_openai_tts_call_attempted,
            "last_openai_tts_call_blocked_reason": self.last_openai_tts_call_blocked_reason,
            "mock_provider_active": bool(getattr(self.provider, "is_mock", False)),
            "audio_generated": bool(synthesis is not None and synthesis.ok and synthesis.audio_output is not None),
            "playback_available": bool(self.config.playback.enabled and self._playback_provider_availability().get("available")),
            "no_microphone_capture": True,
            "no_wake_word": True,
            "no_realtime": True,
            "no_live_conversation_loop": True,
            "no_audio_playback": not bool(self.last_playback_result and self.last_playback_result.played_locally),
        }

    def _playback_status_snapshot(self) -> dict[str, Any]:
        request = self.last_playback_request
        result = self.last_playback_result
        active = self._active_playback()
        availability = self._playback_provider_availability()
        return {
            "enabled": self.config.playback.enabled,
            "provider": result.provider if result is not None else self._playback_provider_name(),
            "available": bool(self.config.playback.enabled and availability.get("available")),
            "unavailable_reason": availability.get("unavailable_reason"),
            "device": result.device if result is not None else self.config.playback.device,
            "volume": self.config.playback.volume,
            "last_playback_request_id": request.playback_request_id if request is not None else None,
            "last_playback_id": result.playback_id if result is not None else None,
            "last_playback_status": result.status if result is not None else None,
            "last_audio_output_id": result.audio_output_id if result is not None else None,
            "last_synthesis_id": result.synthesis_id if result is not None else None,
            "last_playback_error": {
                "code": result.error_code if result is not None else None,
                "message": result.error_message if result is not None else None,
            },
            "last_output_metadata": dict(result.output_metadata) if result is not None else None,
            "active_playback_id": active.playback_id if active is not None else None,
            "active_playback_status": active.status if active is not None else None,
            "playback_started_at": result.started_at if result is not None else None,
            "playback_completed_at": result.completed_at if result is not None else None,
            "playback_stopped_at": result.stopped_at if result is not None else None,
            "played_locally": bool(result and result.played_locally),
            "user_heard_claimed": False,
            "mock_provider_active": bool(getattr(self.playback_provider, "is_mock", False)),
            "no_microphone_capture": True,
            "no_wake_word": True,
            "no_vad": True,
            "no_realtime": True,
            "no_continuous_loop": True,
            "raw_audio_included": False,
        }

    def _preview_text(self, text: str, *, limit: int = 72) -> str:
        compact = " ".join(str(text or "").split()).strip()
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."


def build_voice_subsystem(
    config: VoiceConfig,
    openai_config: OpenAIConfig,
    *,
    events: EventBuffer | None = None,
) -> VoiceService:
    return VoiceService(config=config, openai_config=openai_config, events=events)
