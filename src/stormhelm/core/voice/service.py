from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from stormhelm.config.models import OpenAIConfig
from stormhelm.config.models import VoiceConfig
from stormhelm.core.events import EventBuffer
from stormhelm.core.trust.models import ApprovalState
from stormhelm.core.trust.models import AuditRecord
from stormhelm.core.trust.models import PermissionScope
from stormhelm.core.trust.models import TrustDecisionOutcome
from stormhelm.core.voice.availability import VoiceAvailability
from stormhelm.core.voice.availability import compute_voice_availability
from stormhelm.core.voice.bridge import VoiceCoreRequest
from stormhelm.core.voice.bridge import VoiceCoreResult
from stormhelm.core.voice.bridge import submit_voice_core_request
from stormhelm.core.voice.events import VoiceEventType
from stormhelm.core.voice.events import publish_voice_event
from stormhelm.core.voice.models import VoiceTurn
from stormhelm.core.voice.models import VoiceTurnResult
from stormhelm.core.voice.models import VoiceActivityEvent
from stormhelm.core.voice.models import VoiceAudioInput
from stormhelm.core.voice.models import VoiceAudioOutput
from stormhelm.core.voice.models import VoiceCaptureRequest
from stormhelm.core.voice.models import VoiceCaptureResult
from stormhelm.core.voice.models import VoiceCaptureSession
from stormhelm.core.voice.models import VoiceCaptureTurnResult
from stormhelm.core.voice.models import VoiceConfirmationBinding
from stormhelm.core.voice.models import VoiceConfirmationStrength
from stormhelm.core.voice.models import VoiceInterruptionClassification
from stormhelm.core.voice.models import VoiceInterruptionIntent
from stormhelm.core.voice.models import VoiceInterruptionRequest
from stormhelm.core.voice.models import VoiceInterruptionResult
from stormhelm.core.voice.models import VoiceFirstAudioLatency
from stormhelm.core.voice.models import VoiceLivePlaybackRequest
from stormhelm.core.voice.models import VoiceLivePlaybackResult
from stormhelm.core.voice.models import VoiceLivePlaybackSession
from stormhelm.core.voice.models import VoiceOutputPrewarmResult
from stormhelm.core.voice.models import VoicePlaybackRequest
from stormhelm.core.voice.models import VoicePlaybackPrewarmRequest
from stormhelm.core.voice.models import VoicePlaybackPrewarmResult
from stormhelm.core.voice.models import VoicePlaybackResult
from stormhelm.core.voice.models import VoicePipelineStageSummary
from stormhelm.core.voice.models import VoicePostWakeListenWindow
from stormhelm.core.voice.models import VoiceProviderPrewarmRequest
from stormhelm.core.voice.models import VoiceProviderPrewarmResult
from stormhelm.core.voice.models import VoiceReadinessReport
from stormhelm.core.voice.models import VoiceRealtimeCoreBridgeCall
from stormhelm.core.voice.models import VoiceRealtimeReadiness
from stormhelm.core.voice.models import VoiceRealtimeResponseGate
from stormhelm.core.voice.models import VoiceRealtimeSession
from stormhelm.core.voice.models import VoiceRealtimeTranscriptEvent
from stormhelm.core.voice.models import VoiceRealtimeTurnResult
from stormhelm.core.voice.models import VoiceRuntimeModeReadiness
from stormhelm.core.voice.models import VoiceSpeechRequest
from stormhelm.core.voice.models import VoiceSpeechSynthesisResult
from stormhelm.core.voice.models import VoiceStreamingSpeechOutputResult
from stormhelm.core.voice.models import VoiceStreamingTTSRequest
from stormhelm.core.voice.models import VoiceStreamingTTSResult
from stormhelm.core.voice.models import VoiceSpokenConfirmationIntent
from stormhelm.core.voice.models import VoiceSpokenConfirmationIntentKind
from stormhelm.core.voice.models import VoiceSpokenConfirmationRequest
from stormhelm.core.voice.models import VoiceSpokenConfirmationResult
from stormhelm.core.voice.models import VoiceTranscriptionResult
from stormhelm.core.voice.models import VoiceVADReadiness
from stormhelm.core.voice.models import VoiceVADSession
from stormhelm.core.voice.models import VoiceWakeEvent
from stormhelm.core.voice.models import VoiceWakeGhostRequest
from stormhelm.core.voice.models import VoiceWakeReadiness
from stormhelm.core.voice.models import VoiceWakeSession
from stormhelm.core.voice.models import VoiceWakeSupervisedLoopResult
from stormhelm.core.voice.providers import LocalPlaybackProvider
from stormhelm.core.voice.providers import LocalCaptureProvider
from stormhelm.core.voice.providers import LocalWakeWordProvider
from stormhelm.core.voice.providers import MockPlaybackProvider
from stormhelm.core.voice.providers import MockCaptureProvider
from stormhelm.core.voice.providers import MockRealtimeProvider
from stormhelm.core.voice.providers import MockVADProvider
from stormhelm.core.voice.providers import MockWakeWordProvider
from stormhelm.core.voice.providers import MockVoiceProvider
from stormhelm.core.voice.providers import OpenAIVoiceProvider
from stormhelm.core.voice.providers import UnavailableVADProvider
from stormhelm.core.voice.providers import UnavailableRealtimeProvider
from stormhelm.core.voice.providers import UnavailableWakeWordProvider
from stormhelm.core.voice.providers import RealtimeTranscriptionProvider
from stormhelm.core.voice.providers import VoiceActivityDetector
from stormhelm.core.voice.providers import VoiceCaptureProvider
from stormhelm.core.voice.providers import VoicePlaybackProvider
from stormhelm.core.voice.providers import VoiceProvider
from stormhelm.core.voice.providers import VoiceProviderOperationResult
from stormhelm.core.voice.providers import WakeWordProvider
from stormhelm.core.voice.speech_renderer import SpokenResponseRenderer
from stormhelm.core.voice.speech_renderer import SpokenResponseRequest
from stormhelm.core.voice.speech_renderer import SpokenResponseResult
from stormhelm.core.voice.state import VoiceState
from stormhelm.core.voice.state import VoiceStateController
from stormhelm.core.voice.state import VoiceStateSnapshot
from stormhelm.core.voice.state import VoiceTransitionError
from stormhelm.core.voice.visualizer import VoiceAudioEnvelope
from stormhelm.core.voice.visualizer import build_voice_anchor_payload
from stormhelm.core.voice.visualizer import compute_voice_audio_envelope
from stormhelm.shared.time import utc_now_iso


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
_UNSAFE_SPEECH_MARKERS = {
    "```",
    "traceback",
    "api_key",
    "authorization:",
    "secret=",
    "password=",
}
_UNSAFE_UNAPPROVED_PHRASES = {"all set", "that worked"}
_SUPPORTED_PLAYBACK_FORMATS = {"mp3", "wav", "aac", "flac", "opus", "pcm"}
_SUPPORTED_CAPTURE_FORMATS = {"wav", "webm", "mp3", "m4a", "mp4"}

_CONFIRM_WEAK_PHRASES = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay"}
_CONFIRM_NORMAL_PHRASES = {"proceed", "go ahead", "approve", "approve it"}
_CONFIRM_EXPLICIT_PHRASES = {
    "confirm",
    "confirmed",
    "do it",
    "send it",
    "install it",
}
_REJECT_PHRASES = {"no", "nope", "reject", "decline", "do not", "don't", "dont"}
_CANCEL_CONFIRMATION_PHRASES = {
    "cancel",
    "never mind",
    "nevermind",
    "forget it",
    "stop that",
    "don't do that",
    "dont do that",
}
_SHOW_PLAN_PHRASES = {
    "show me the plan",
    "show the plan",
    "what are you going to do",
}
_EXPLAIN_RISK_PHRASES = {
    "explain the risk",
    "why do you need confirmation",
    "why are you asking",
}
_REPEAT_PROMPT_PHRASES = {"repeat that", "say that again"}
_WAIT_PHRASES = {"wait", "hold on", "pause", "not yet"}
_OUTPUT_STOP_PHRASES = {
    "stop talking",
    "stop speaking",
    "be quiet",
    "quiet",
    "stop playback",
    "stop audio",
}
_MUTE_OUTPUT_PHRASES = {"mute", "mute voice", "mute spoken output"}
_UNMUTE_OUTPUT_PHRASES = {"unmute", "unmute voice", "unmute spoken output"}
_CAPTURE_CANCEL_PHRASES = {
    "cancel capture",
    "stop recording",
    "stop listening",
    "cancel this request",
}
_CORE_CANCEL_PHRASES = {
    "cancel the task",
    "stop the task",
    "cancel that task",
    "abort the operation",
    "stop the install",
    "cancel the send",
    "cancel the workflow",
}
_CORRECTION_PREFIXES = {
    "actually",
    "actually wait",
    "actually do this",
    "correction",
    "no i meant",
    "no, i meant",
    "change that to",
    "instead",
}
_CONFIRMATION_STRENGTH_RANK = {
    VoiceConfirmationStrength.NONE: 0,
    VoiceConfirmationStrength.WEAK_ACK: 1,
    VoiceConfirmationStrength.NORMAL_CONFIRM: 2,
    VoiceConfirmationStrength.EXPLICIT_CONFIRM: 3,
    VoiceConfirmationStrength.DESTRUCTIVE_CONFIRM: 4,
}


@dataclass(slots=True)
class VoiceService:
    config: VoiceConfig
    openai_config: OpenAIConfig
    events: EventBuffer | None = None
    availability: VoiceAvailability = field(init=False)
    state_controller: VoiceStateController = field(init=False)
    provider: VoiceProvider = field(init=False)
    playback_provider: VoicePlaybackProvider = field(init=False)
    capture_provider: VoiceCaptureProvider = field(init=False)
    wake_provider: WakeWordProvider = field(init=False)
    vad_provider: VoiceActivityDetector = field(init=False)
    realtime_provider: RealtimeTranscriptionProvider = field(init=False)
    speech_renderer: SpokenResponseRenderer = field(
        default_factory=SpokenResponseRenderer
    )
    core_bridge: Any | None = None
    trust_service: Any | None = None
    last_event: dict[str, Any] | None = field(default=None, init=False)
    last_manual_turn_result: VoiceTurnResult | None = field(default=None, init=False)
    last_audio_turn_result: VoiceTurnResult | None = field(default=None, init=False)
    last_transcription_result: VoiceTranscriptionResult | None = field(
        default=None, init=False
    )
    last_audio_input_metadata: dict[str, Any] | None = field(default=None, init=False)
    last_audio_validation_error: dict[str, str | None] = field(
        default_factory=lambda: {"code": None, "message": None}, init=False
    )
    last_openai_call_attempted: bool = field(default=False, init=False)
    last_openai_call_blocked_reason: str | None = field(default=None, init=False)
    last_speech_request: VoiceSpeechRequest | None = field(default=None, init=False)
    last_synthesis_result: VoiceSpeechSynthesisResult | None = field(
        default=None, init=False
    )
    last_openai_tts_call_attempted: bool = field(default=False, init=False)
    last_openai_tts_call_blocked_reason: str | None = field(default=None, init=False)
    last_playback_request: VoicePlaybackRequest | None = field(default=None, init=False)
    last_playback_result: VoicePlaybackResult | None = field(default=None, init=False)
    last_streaming_tts_request: VoiceStreamingTTSRequest | None = field(
        default=None, init=False
    )
    last_streaming_tts_result: VoiceStreamingTTSResult | None = field(
        default=None, init=False
    )
    last_live_playback_request: VoiceLivePlaybackRequest | None = field(
        default=None, init=False
    )
    last_live_playback_session: VoiceLivePlaybackSession | None = field(
        default=None, init=False
    )
    last_live_playback_result: VoiceLivePlaybackResult | None = field(
        default=None, init=False
    )
    last_provider_prewarm_result: VoiceProviderPrewarmResult | None = field(
        default=None, init=False
    )
    last_playback_prewarm_result: VoicePlaybackPrewarmResult | None = field(
        default=None, init=False
    )
    last_voice_output_prewarm_result: VoiceOutputPrewarmResult | None = field(
        default=None, init=False
    )
    last_first_audio_latency: VoiceFirstAudioLatency | None = field(
        default=None, init=False
    )
    last_voice_output_envelope: VoiceAudioEnvelope | None = field(
        default=None, init=False
    )
    last_capture_request: VoiceCaptureRequest | None = field(default=None, init=False)
    last_capture_session: VoiceCaptureSession | None = field(default=None, init=False)
    last_capture_result: VoiceCaptureResult | None = field(default=None, init=False)
    last_interruption_request: VoiceInterruptionRequest | None = field(
        default=None, init=False
    )
    last_interruption_result: VoiceInterruptionResult | None = field(
        default=None, init=False
    )
    last_wake_event: VoiceWakeEvent | None = field(default=None, init=False)
    last_wake_session: VoiceWakeSession | None = field(default=None, init=False)
    active_wake_session: VoiceWakeSession | None = field(default=None, init=False)
    last_wake_ghost_request: VoiceWakeGhostRequest | None = field(
        default=None, init=False
    )
    active_wake_ghost_request: VoiceWakeGhostRequest | None = field(
        default=None, init=False
    )
    wake_events: dict[str, VoiceWakeEvent] = field(default_factory=dict, init=False)
    wake_sessions: dict[str, VoiceWakeSession] = field(default_factory=dict, init=False)
    wake_ghost_requests: dict[str, VoiceWakeGhostRequest] = field(
        default_factory=dict, init=False
    )
    wake_monitoring_active: bool = field(default=False, init=False)
    last_vad_session: VoiceVADSession | None = field(default=None, init=False)
    active_vad_session: VoiceVADSession | None = field(default=None, init=False)
    last_activity_event: VoiceActivityEvent | None = field(default=None, init=False)
    vad_sessions: dict[str, VoiceVADSession] = field(default_factory=dict, init=False)
    activity_events: dict[str, VoiceActivityEvent] = field(
        default_factory=dict, init=False
    )
    last_wake_supervised_loop_result: VoiceWakeSupervisedLoopResult | None = field(
        default=None, init=False
    )
    last_post_wake_listen_window: VoicePostWakeListenWindow | None = field(
        default=None, init=False
    )
    active_post_wake_listen_window: VoicePostWakeListenWindow | None = field(
        default=None, init=False
    )
    post_wake_listen_windows: dict[str, VoicePostWakeListenWindow] = field(
        default_factory=dict, init=False
    )
    last_spoken_confirmation_intent: VoiceSpokenConfirmationIntent | None = field(
        default=None, init=False
    )
    last_spoken_confirmation_request: VoiceSpokenConfirmationRequest | None = field(
        default=None, init=False
    )
    last_spoken_confirmation_binding: VoiceConfirmationBinding | None = field(
        default=None, init=False
    )
    last_spoken_confirmation_result: VoiceSpokenConfirmationResult | None = field(
        default=None, init=False
    )
    last_interruption_classification: VoiceInterruptionClassification | None = field(
        default=None, init=False
    )
    last_realtime_session: VoiceRealtimeSession | None = field(default=None, init=False)
    active_realtime_session: VoiceRealtimeSession | None = field(
        default=None, init=False
    )
    realtime_sessions: dict[str, VoiceRealtimeSession] = field(
        default_factory=dict, init=False
    )
    last_realtime_transcript_event: VoiceRealtimeTranscriptEvent | None = field(
        default=None, init=False
    )
    realtime_transcript_events: dict[str, VoiceRealtimeTranscriptEvent] = field(
        default_factory=dict, init=False
    )
    last_realtime_turn_result: VoiceRealtimeTurnResult | None = field(
        default=None, init=False
    )
    last_realtime_core_bridge_call: VoiceRealtimeCoreBridgeCall | None = field(
        default=None, init=False
    )
    realtime_core_bridge_calls: dict[str, VoiceRealtimeCoreBridgeCall] = field(
        default_factory=dict, init=False
    )
    last_realtime_response_gate: VoiceRealtimeResponseGate | None = field(
        default=None, init=False
    )
    realtime_response_gates: dict[str, VoiceRealtimeResponseGate] = field(
        default_factory=dict, init=False
    )
    active_wake_supervised_loop_id: str | None = field(default=None, init=False)
    active_wake_supervised_loop_stage: str | None = field(default=None, init=False)
    _last_wake_event_monotonic_ms: float | None = field(
        default=None, init=False, repr=False
    )
    spoken_output_muted: bool = field(default=False, init=False)
    muted_scope: str | None = field(default=None, init=False)
    muted_since: str | None = field(default=None, init=False)
    muted_reason: str | None = field(default=None, init=False)
    current_response_suppressed: bool = field(default=False, init=False)
    suppressed_turn_id: str | None = field(default=None, init=False)
    suppressed_reason: str | None = field(default=None, init=False)
    last_capture_error: dict[str, str | None] = field(
        default_factory=lambda: {"code": None, "message": None}, init=False
    )
    last_error: dict[str, str | None] = field(
        default_factory=lambda: {"code": None, "message": None}, init=False
    )

    def __post_init__(self) -> None:
        self.availability = compute_voice_availability(self.config, self.openai_config)
        self.state_controller = VoiceStateController(
            config=self.config, availability=self.availability
        )
        self.provider = (
            MockVoiceProvider()
            if self.config.debug_mock_provider
            else OpenAIVoiceProvider(
                config=self.config, openai_config=self.openai_config
            )
        )
        self.playback_provider = (
            MockPlaybackProvider()
            if self.config.playback.provider == "mock"
            or (
                self.config.debug_mock_provider
                and self.config.playback.allow_dev_playback
            )
            else LocalPlaybackProvider(config=self.config)
        )
        self.capture_provider = (
            MockCaptureProvider()
            if self.config.capture.provider == "mock"
            or (
                self.config.debug_mock_provider
                and self.config.capture.allow_dev_capture
            )
            else LocalCaptureProvider(config=self.config)
        )
        self.wake_provider = (
            MockWakeWordProvider(config=self.config.wake)
            if self.config.wake.provider == "mock"
            else LocalWakeWordProvider(config=self.config.wake)
            if self.config.wake.provider == "local"
            else UnavailableWakeWordProvider(
                config=self.config.wake,
                unavailable_reason="provider_not_configured",
            )
        )
        self.vad_provider = (
            MockVADProvider(config=self.config.vad)
            if self.config.vad.provider == "mock"
            else UnavailableVADProvider(
                config=self.config.vad,
                unavailable_reason="provider_not_configured",
            )
        )
        self.realtime_provider = (
            MockRealtimeProvider(config=self.config.realtime)
            if self.config.realtime.provider == "mock"
            and self.config.realtime.allow_dev_realtime
            else UnavailableRealtimeProvider(
                config=self.config.realtime,
                openai_config=self.openai_config,
                unavailable_reason="provider_not_configured",
            )
        )

    def attach_core_bridge(self, core_bridge: Any) -> None:
        self.core_bridge = core_bridge

    def attach_trust_service(self, trust_service: Any) -> None:
        self.trust_service = trust_service

    def refresh(self) -> VoiceStateSnapshot:
        previous = self.availability
        self.availability = compute_voice_availability(self.config, self.openai_config)
        self.state_controller = VoiceStateController(
            config=self.config, availability=self.availability
        )
        if previous != self.availability and self.events is not None:
            event = publish_voice_event(
                self.events,
                VoiceEventType.AVAILABILITY_CHANGED,
                message="Voice availability changed.",
                provider=self.availability.provider_name,
                mode=self.availability.mode,
                state=self.state_controller.snapshot().state.value,
                metadata={
                    "available": self.availability.available,
                    "reason": self.availability.unavailable_reason,
                },
            )
            self.last_event = event.to_dict()
        return self.state_controller.snapshot()

    def classify_spoken_confirmation(
        self,
        transcript: str,
        *,
        source: str = "manual_voice",
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> VoiceSpokenConfirmationIntent:
        normalized = self._normalize_confirmation_phrase(transcript)
        intent = VoiceSpokenConfirmationIntentKind.NOT_CONFIRMATION
        family: str | None = None
        strength = VoiceConfirmationStrength.NONE
        confidence = 0.0
        ambiguity_reason: str | None = None

        if not normalized:
            intent = VoiceSpokenConfirmationIntentKind.NONE
        elif normalized in _CONFIRM_WEAK_PHRASES:
            intent = VoiceSpokenConfirmationIntentKind.CONFIRM
            family = "confirm_weak"
            strength = VoiceConfirmationStrength.WEAK_ACK
            confidence = 0.8
        elif normalized in _CONFIRM_NORMAL_PHRASES:
            intent = VoiceSpokenConfirmationIntentKind.CONFIRM
            family = "confirm_normal"
            strength = VoiceConfirmationStrength.NORMAL_CONFIRM
            confidence = 0.9
        elif normalized in _CONFIRM_EXPLICIT_PHRASES:
            intent = VoiceSpokenConfirmationIntentKind.CONFIRM
            family = "confirm_explicit"
            strength = VoiceConfirmationStrength.EXPLICIT_CONFIRM
            confidence = 0.95
        elif normalized in _REJECT_PHRASES:
            intent = VoiceSpokenConfirmationIntentKind.REJECT
            family = "reject"
            strength = VoiceConfirmationStrength.NORMAL_CONFIRM
            confidence = 0.9
        elif normalized in _CANCEL_CONFIRMATION_PHRASES:
            intent = VoiceSpokenConfirmationIntentKind.CANCEL_PENDING_CONFIRMATION
            family = "cancel_pending_confirmation"
            strength = VoiceConfirmationStrength.NORMAL_CONFIRM
            confidence = 0.85
        elif normalized in _SHOW_PLAN_PHRASES:
            intent = VoiceSpokenConfirmationIntentKind.SHOW_PLAN
            family = "show_plan"
            confidence = 0.9
        elif normalized in _EXPLAIN_RISK_PHRASES:
            intent = VoiceSpokenConfirmationIntentKind.EXPLAIN_RISK
            family = "explain_risk"
            confidence = 0.9
        elif normalized in _REPEAT_PROMPT_PHRASES:
            intent = VoiceSpokenConfirmationIntentKind.REPEAT_PROMPT
            family = "repeat_prompt"
            confidence = 0.9
        elif normalized in _WAIT_PHRASES:
            intent = VoiceSpokenConfirmationIntentKind.WAIT
            family = "wait"
            confidence = 0.85
        elif any(token in normalized.split() for token in _CONFIRM_WEAK_PHRASES):
            intent = VoiceSpokenConfirmationIntentKind.AMBIGUOUS
            family = "ambiguous_confirmation"
            confidence = 0.35
            ambiguity_reason = "confirmation_phrase_mixed_with_other_words"
        else:
            intent = VoiceSpokenConfirmationIntentKind.NOT_CONFIRMATION

        result = VoiceSpokenConfirmationIntent(
            transcript=transcript,
            normalized_phrase=normalized,
            intent=intent,
            confidence=confidence,
            source=source,
            session_id=session_id,
            turn_id=turn_id,
            matched_phrase_family=family,
            provided_strength=strength,
            requires_pending_confirmation=intent
            in {
                VoiceSpokenConfirmationIntentKind.CONFIRM,
                VoiceSpokenConfirmationIntentKind.REJECT,
                VoiceSpokenConfirmationIntentKind.CANCEL_PENDING_CONFIRMATION,
                VoiceSpokenConfirmationIntentKind.SHOW_PLAN,
                VoiceSpokenConfirmationIntentKind.REPEAT_PROMPT,
                VoiceSpokenConfirmationIntentKind.EXPLAIN_RISK,
                VoiceSpokenConfirmationIntentKind.WAIT,
                VoiceSpokenConfirmationIntentKind.AMBIGUOUS,
            },
            allowed_without_pending_confirmation=False,
            ambiguity_reason=ambiguity_reason,
        )
        self.last_spoken_confirmation_intent = result
        return result

    async def handle_spoken_confirmation(
        self, request: VoiceSpokenConfirmationRequest
    ) -> VoiceSpokenConfirmationResult:
        self.last_spoken_confirmation_request = request
        intent = self.classify_spoken_confirmation(
            request.transcript,
            source=request.source,
            session_id=request.session_id,
            turn_id=request.turn_id,
        )
        self._publish_spoken_confirmation_event(
            VoiceEventType.SPOKEN_CONFIRMATION_RECEIVED,
            request=request,
            intent=intent,
            message="Spoken confirmation received.",
            status="received",
        )
        self._publish_spoken_confirmation_event(
            VoiceEventType.SPOKEN_CONFIRMATION_CLASSIFIED,
            request=request,
            intent=intent,
            message="Spoken confirmation classified.",
            status=intent.intent.value,
        )

        if not self.config.confirmation.enabled:
            return self._remember_spoken_confirmation_result(
                self._spoken_confirmation_result(
                    request=request,
                    intent=intent,
                    status="unsupported",
                    reason="spoken_confirmation_disabled",
                    user_message="Spoken confirmation is disabled.",
                    error_code="spoken_confirmation_disabled",
                ),
                event_type=VoiceEventType.SPOKEN_CONFIRMATION_FAILED,
            )

        if intent.intent == VoiceSpokenConfirmationIntentKind.NOT_CONFIRMATION:
            return self._remember_spoken_confirmation_result(
                self._spoken_confirmation_result(
                    request=request,
                    intent=intent,
                    status="unsupported",
                    reason="not_confirmation",
                    user_message="That was not handled as a confirmation.",
                ),
                event_type=VoiceEventType.SPOKEN_CONFIRMATION_FAILED,
            )
        if intent.intent == VoiceSpokenConfirmationIntentKind.AMBIGUOUS:
            return self._remember_spoken_confirmation_result(
                self._spoken_confirmation_result(
                    request=request,
                    intent=intent,
                    status="ambiguous",
                    reason=intent.ambiguity_reason or "ambiguous_confirmation",
                    user_message="I need a clearer confirmation.",
                    spoken_response_candidate="I need a clearer confirmation.",
                ),
                event_type=VoiceEventType.SPOKEN_CONFIRMATION_AMBIGUOUS,
            )

        pending = self._resolve_pending_confirmation(request)
        if pending is None:
            return self._remember_spoken_confirmation_result(
                self._spoken_confirmation_result(
                    request=request,
                    intent=intent,
                    status="no_pending_confirmation",
                    reason="no_pending_confirmation",
                    user_message="No pending confirmation.",
                    error_code="no_pending_confirmation",
                ),
                event_type=VoiceEventType.SPOKEN_CONFIRMATION_REJECTED,
            )

        binding = self._build_confirmation_binding(intent, request, pending)
        self.last_spoken_confirmation_binding = binding
        self._publish_spoken_confirmation_event(
            VoiceEventType.SPOKEN_CONFIRMATION_BOUND,
            request=request,
            intent=intent,
            binding=binding,
            message="Spoken confirmation binding evaluated.",
            status="bound" if binding.valid else "binding_failed",
        )
        if not binding.valid:
            status = self._binding_failure_status(binding)
            return self._remember_spoken_confirmation_result(
                self._spoken_confirmation_result(
                    request=request,
                    intent=intent,
                    status=status,
                    binding=binding,
                    reason=binding.invalid_reason or "binding_failed",
                    user_message=self._binding_failure_message(binding),
                    error_code=binding.invalid_reason or "binding_failed",
                ),
                event_type=VoiceEventType.SPOKEN_CONFIRMATION_EXPIRED
                if status in {"expired", "stale"}
                else VoiceEventType.SPOKEN_CONFIRMATION_REJECTED,
            )

        if intent.intent in {
            VoiceSpokenConfirmationIntentKind.SHOW_PLAN,
            VoiceSpokenConfirmationIntentKind.EXPLAIN_RISK,
            VoiceSpokenConfirmationIntentKind.REPEAT_PROMPT,
            VoiceSpokenConfirmationIntentKind.WAIT,
        }:
            return self._remember_spoken_confirmation_result(
                self._spoken_confirmation_result(
                    request=request,
                    intent=intent,
                    status="shown",
                    binding=binding,
                    reason="pending_confirmation_detail_shown",
                    user_message=self._spoken_confirmation_detail_message(
                        pending, intent
                    ),
                    spoken_response_candidate=self._spoken_confirmation_detail_message(
                        pending, intent
                    ),
                ),
                event_type=VoiceEventType.SPOKEN_CONFIRMATION_CLASSIFIED,
            )

        if intent.intent in {
            VoiceSpokenConfirmationIntentKind.REJECT,
            VoiceSpokenConfirmationIntentKind.CANCEL_PENDING_CONFIRMATION,
        }:
            decision = self.trust_service.respond_to_request(
                approval_request_id=pending.approval_request_id,
                decision="deny",
                session_id=request.session_id,
                task_id=request.task_id or pending.task_id,
            )
            return self._remember_spoken_confirmation_result(
                self._spoken_confirmation_result(
                    request=request,
                    intent=intent,
                    status="rejected",
                    ok=True,
                    binding=replace(binding, consumed_at=utc_now_iso()),
                    consumed=True,
                    reason=decision.reason,
                    user_message="Confirmation rejected.",
                    spoken_response_candidate="Confirmation rejected.",
                ),
                event_type=VoiceEventType.SPOKEN_CONFIRMATION_REJECTED,
                consumed=True,
            )

        decision = self.trust_service.respond_to_request(
            approval_request_id=pending.approval_request_id,
            decision="approve",
            session_id=request.session_id,
            scope=PermissionScope.ONCE,
            task_id=request.task_id or pending.task_id,
        )
        if decision.outcome != TrustDecisionOutcome.ALLOWED:
            return self._remember_spoken_confirmation_result(
                self._spoken_confirmation_result(
                    request=request,
                    intent=intent,
                    status="blocked",
                    binding=binding,
                    reason=decision.reason,
                    user_message=decision.operator_message,
                    error_code="trust_confirmation_blocked",
                ),
                event_type=VoiceEventType.SPOKEN_CONFIRMATION_FAILED,
            )

        return self._remember_spoken_confirmation_result(
            self._spoken_confirmation_result(
                request=request,
                intent=intent,
                status="confirmed",
                ok=True,
                binding=replace(binding, consumed_at=utc_now_iso()),
                consumed=True,
                reason=decision.reason,
                user_message="Confirmation accepted.",
                spoken_response_candidate="Confirmation accepted.",
            ),
            event_type=VoiceEventType.SPOKEN_CONFIRMATION_ACCEPTED,
            consumed=True,
        )

    def _normalize_confirmation_phrase(self, transcript: str) -> str:
        compact = " ".join(str(transcript or "").lower().split()).strip()
        compact = compact.strip(" .,!?:;\"'")
        return compact.replace("’", "'")

    def _resolve_pending_confirmation(
        self, request: VoiceSpokenConfirmationRequest
    ) -> Any | None:
        if self.trust_service is None:
            return None
        repository = getattr(self.trust_service, "repository", None)
        if repository is None:
            return None
        if request.pending_confirmation_id:
            return repository.get_approval_request(request.pending_confirmation_id)
        pending = repository.list_pending_requests(session_id=request.session_id)
        if len(pending) == 1:
            return pending[0]
        return None

    def _build_confirmation_binding(
        self,
        intent: VoiceSpokenConfirmationIntent,
        request: VoiceSpokenConfirmationRequest,
        pending: Any,
    ) -> VoiceConfirmationBinding:
        details = dict(getattr(pending, "details", {}) or {})
        pending_state = getattr(pending, "state", None)
        pending_state_value = getattr(pending_state, "value", str(pending_state))
        route_family = str(details.get("route_family") or pending.family or "").strip()
        subsystem = str(details.get("subsystem") or route_family or "").strip()
        required = self._required_confirmation_strength(details, pending)
        invalid_reason: str | None = None
        stale = False
        same_task = True
        same_payload = True
        same_route = True
        same_session = True
        same_action = True

        if pending_state != ApprovalState.PENDING_OPERATOR_CONFIRMATION:
            stale = True
            invalid_reason = "already_consumed"
        elif pending.expires_at and self._is_expired(pending.expires_at):
            stale = True
            invalid_reason = "expired"
        elif self._confirmation_age_expired(pending.created_at):
            stale = True
            invalid_reason = "stale"

        if not invalid_reason:
            same_session = str(pending.session_id or "default") == request.session_id
            if not same_session:
                invalid_reason = "session_mismatch"
            expected_task = str(pending.task_id or "").strip()
            request_task = str(request.task_id or "").strip()
            same_task = not expected_task or not request_task or expected_task == request_task
            if (
                self.config.confirmation.reject_on_task_switch
                and not same_task
            ):
                invalid_reason = "task_mismatch"

        expected_payload = str(details.get("payload_hash") or "").strip()
        request_payload = str(request.metadata.get("payload_hash") or "").strip()
        if not invalid_reason and expected_payload and request_payload:
            same_payload = expected_payload == request_payload
            if (
                self.config.confirmation.reject_on_payload_change
                and not same_payload
            ):
                invalid_reason = "payload_mismatch"

        if not invalid_reason and request.route_family:
            same_route = str(request.route_family).strip() == route_family
            if not same_route:
                invalid_reason = "route_family_mismatch"

        if not invalid_reason and intent.normalized_phrase == "send it":
            same_action = "send" in str(pending.action_key or "").lower()
            if not same_action:
                invalid_reason = "action_phrase_mismatch"
        if not invalid_reason and intent.normalized_phrase == "install it":
            same_action = "install" in str(pending.action_key or "").lower()
            if not same_action:
                invalid_reason = "action_phrase_mismatch"

        if (
            not invalid_reason
            and intent.intent == VoiceSpokenConfirmationIntentKind.CONFIRM
            and not self._confirmation_strength_sufficient(
                intent.provided_strength, required
            )
        ):
            invalid_reason = "confirmation_strength_insufficient"

        return VoiceConfirmationBinding(
            pending_confirmation_id=pending.approval_request_id,
            approval_request_id=pending.approval_request_id,
            task_id=pending.task_id or None,
            action_id=pending.action_key,
            route_family=route_family or None,
            subsystem=subsystem or None,
            target_summary=str(
                details.get("target_summary")
                or pending.operator_message
                or pending.subject
                or ""
            ),
            payload_hash=expected_payload or None,
            recipient_id=str(
                details.get("recipient_id") or details.get("recipient_alias") or ""
            )
            or None,
            risk_level=str(details.get("risk_level") or "unknown").strip().lower(),
            required_confirmation_strength=required,
            provided_confirmation_strength=intent.provided_strength,
            source_turn_id=str(details.get("source_turn_id") or "") or None,
            current_turn_id=request.turn_id,
            session_id=request.session_id,
            expires_at=pending.expires_at or None,
            stale=stale,
            valid=invalid_reason is None,
            invalid_reason=invalid_reason,
            same_task=same_task,
            same_action=same_action,
            same_payload=same_payload,
            same_route_family=same_route,
            same_session=same_session,
            restart_boundary_valid=not stale,
            confidence=intent.confidence,
        )

    def _required_confirmation_strength(
        self, details: dict[str, Any], pending: Any
    ) -> VoiceConfirmationStrength:
        configured = str(
            details.get("required_confirmation_strength") or ""
        ).strip().lower()
        if configured:
            return VoiceConfirmationStrength(configured)
        risk = str(details.get("risk_level") or "").strip().lower()
        if risk in {"destructive", "critical"}:
            return VoiceConfirmationStrength.DESTRUCTIVE_CONFIRM
        if risk in {"high", "sensitive"}:
            return VoiceConfirmationStrength.EXPLICIT_CONFIRM
        if (
            risk in {"low", "visual", "preview"}
            and self.config.confirmation.allow_soft_yes_for_low_risk
        ):
            return VoiceConfirmationStrength.WEAK_ACK
        if getattr(pending, "action_kind", None) in {"software_control"}:
            return VoiceConfirmationStrength.EXPLICIT_CONFIRM
        return VoiceConfirmationStrength.NORMAL_CONFIRM

    def _confirmation_strength_sufficient(
        self,
        provided: VoiceConfirmationStrength | str,
        required: VoiceConfirmationStrength | str,
    ) -> bool:
        provided_strength = (
            provided
            if isinstance(provided, VoiceConfirmationStrength)
            else VoiceConfirmationStrength(str(provided))
        )
        required_strength = (
            required
            if isinstance(required, VoiceConfirmationStrength)
            else VoiceConfirmationStrength(str(required))
        )
        return _CONFIRMATION_STRENGTH_RANK[provided_strength] >= (
            _CONFIRMATION_STRENGTH_RANK[required_strength]
        )

    def _confirmation_age_expired(self, created_at: str) -> bool:
        try:
            created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return False
        age_ms = (datetime.now(timezone.utc) - created).total_seconds() * 1000
        return age_ms > self.config.confirmation.max_confirmation_age_ms

    def _binding_failure_status(self, binding: VoiceConfirmationBinding) -> str:
        if binding.invalid_reason == "expired":
            return "expired"
        if binding.invalid_reason in {"stale", "already_consumed"}:
            return "stale"
        return "binding_failed"

    def _binding_failure_message(self, binding: VoiceConfirmationBinding) -> str:
        if binding.invalid_reason == "confirmation_strength_insufficient":
            return "I need a clearer confirmation."
        if binding.invalid_reason == "payload_mismatch":
            return "That confirmation no longer matches the current action."
        if binding.invalid_reason == "task_mismatch":
            return "That confirmation belongs to a different task."
        if binding.invalid_reason == "expired":
            return "Confirmation expired."
        if binding.invalid_reason == "already_consumed":
            return "That confirmation is no longer pending."
        return "That confirmation does not match the pending action."

    def _spoken_confirmation_detail_message(
        self,
        pending: Any,
        intent: VoiceSpokenConfirmationIntent,
    ) -> str:
        details = dict(getattr(pending, "details", {}) or {})
        if intent.intent == VoiceSpokenConfirmationIntentKind.EXPLAIN_RISK:
            return (
                pending.operator_justification
                or "Approval is required before Stormhelm continues."
            )
        target = (
            pending.operator_message
            or details.get("target_summary")
            or pending.operator_justification
            or pending.subject
        )
        return self._preview_text(str(target or "Approval is required."), limit=180)

    def _spoken_confirmation_result(
        self,
        *,
        request: VoiceSpokenConfirmationRequest,
        intent: VoiceSpokenConfirmationIntent,
        status: str,
        ok: bool = False,
        binding: VoiceConfirmationBinding | None = None,
        consumed: bool = False,
        reason: str = "",
        user_message: str = "",
        spoken_response_candidate: str | None = None,
        error_code: str | None = None,
    ) -> VoiceSpokenConfirmationResult:
        return VoiceSpokenConfirmationResult(
            request_id=request.request_id,
            intent=intent.intent,
            status=status,
            ok=ok,
            binding=binding,
            pending_confirmation_id=binding.pending_confirmation_id
            if binding is not None
            else request.pending_confirmation_id,
            consumed_confirmation=consumed,
            action_executed=False,
            route_family=binding.route_family if binding is not None else request.route_family,
            subsystem=binding.subsystem if binding is not None else None,
            reason=reason,
            user_message=user_message,
            spoken_response_candidate=spoken_response_candidate,
            error_code=error_code,
            metadata={
                "intent": intent.to_dict(),
                "request": request.to_dict(),
                "binding_valid": binding.valid if binding is not None else False,
                "confirmation_accepted_does_not_execute_action": True,
                "listen_window_id": self._metadata_listen_window_id(
                    request.metadata
                ),
                "listen_window_is_provenance_not_authority": bool(
                    self._metadata_listen_window_id(request.metadata)
                ),
            },
        )

    def _remember_spoken_confirmation_result(
        self,
        result: VoiceSpokenConfirmationResult,
        *,
        event_type: VoiceEventType,
        consumed: bool = False,
    ) -> VoiceSpokenConfirmationResult:
        self.last_spoken_confirmation_result = result
        self._record_spoken_confirmation_audit(result)
        self._publish_spoken_confirmation_event(
            event_type,
            request=self.last_spoken_confirmation_request,
            intent=self.last_spoken_confirmation_intent,
            binding=result.binding,
            result=result,
            message=result.user_message or "Spoken confirmation handled.",
            status=result.status,
        )
        if consumed:
            self._publish_spoken_confirmation_event(
                VoiceEventType.SPOKEN_CONFIRMATION_CONSUMED,
                request=self.last_spoken_confirmation_request,
                intent=self.last_spoken_confirmation_intent,
                binding=result.binding,
                result=result,
                message="Spoken confirmation consumed.",
                status=result.status,
            )
        return result

    def _record_spoken_confirmation_audit(
        self, result: VoiceSpokenConfirmationResult
    ) -> None:
        if self.trust_service is None or result.pending_confirmation_id is None:
            return
        repository = getattr(self.trust_service, "repository", None)
        if repository is None:
            return
        binding = result.binding
        event_kind = f"voice.spoken_confirmation.{result.status}"
        repository.save_audit_record(
            AuditRecord(
                audit_id=f"audit-{uuid4()}",
                event_kind=event_kind,
                family=result.route_family or (binding.route_family if binding else "voice"),
                action_key=binding.action_id if binding is not None else "voice.confirmation",
                subject=binding.target_summary if binding is not None else "",
                session_id=self.last_spoken_confirmation_request.session_id
                if self.last_spoken_confirmation_request is not None
                else "default",
                task_id=binding.task_id if binding is not None else "",
                approval_request_id=result.pending_confirmation_id,
                approval_state=ApprovalState.APPROVED_ONCE
                if result.status == "confirmed"
                else ApprovalState.DENIED
                if result.status == "rejected"
                else ApprovalState.PENDING_OPERATOR_CONFIRMATION,
                summary=result.user_message or result.reason,
                details={
                    "status": result.status,
                    "intent": result.intent.value,
                    "action_executed": False,
                    "core_task_cancelled": False,
                    "core_result_mutated": False,
                    "binding_valid": binding.valid if binding is not None else False,
                    "invalid_reason": binding.invalid_reason if binding else None,
                },
                created_at=utc_now_iso(),
            )
        )

    def _publish_spoken_confirmation_event(
        self,
        event_type: VoiceEventType,
        *,
        request: VoiceSpokenConfirmationRequest | None,
        intent: VoiceSpokenConfirmationIntent | None,
        message: str,
        status: str,
        binding: VoiceConfirmationBinding | None = None,
        result: VoiceSpokenConfirmationResult | None = None,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=request.session_id if request is not None else None,
            turn_id=request.turn_id if request is not None else None,
            spoken_confirmation_intent_id=intent.spoken_confirmation_intent_id
            if intent is not None
            else None,
            spoken_confirmation_request_id=request.request_id
            if request is not None
            else None,
            spoken_confirmation_result_id=result.result_id
            if result is not None
            else None,
            pending_confirmation_id=(
                result.pending_confirmation_id
                if result is not None
                else binding.pending_confirmation_id
                if binding is not None
                else request.pending_confirmation_id
                if request is not None
                else None
            ),
            listen_window_id=self._metadata_listen_window_id(request.metadata)
            if request is not None
            else None,
            task_id=binding.task_id if binding is not None else request.task_id
            if request is not None
            else None,
            action_id=binding.action_id if binding is not None else None,
            route_family=binding.route_family if binding is not None else None,
            subsystem=binding.subsystem if binding is not None else None,
            intent=intent.intent.value if intent is not None else None,
            confidence=intent.confidence if intent is not None else None,
            required_strength=binding.required_confirmation_strength.value
            if binding is not None
            else None,
            provided_strength=intent.provided_strength.value
            if intent is not None
            else None,
            binding_valid=binding.valid if binding is not None else None,
            invalid_reason=binding.invalid_reason if binding is not None else None,
            consumed=result.consumed_confirmation if result is not None else None,
            action_executed=False,
            core_task_cancelled=False,
            core_result_mutated=False,
            status=status,
            source=request.source if request is not None else "voice_confirmation",
            metadata={
                "spoken_confirmation_intent": intent.to_dict()
                if intent is not None
                else None,
                "spoken_confirmation_request": request.to_dict()
                if request is not None
                else None,
                "spoken_confirmation_binding": binding.to_dict()
                if binding is not None
                else None,
                "spoken_confirmation_result": result.to_dict()
                if result is not None
                else None,
                "no_raw_audio": True,
                "action_executed": False,
                "listen_window_is_provenance_not_authority": bool(
                    request is not None
                    and self._metadata_listen_window_id(request.metadata)
                ),
            },
        )

    async def _maybe_handle_spoken_confirmation_turn(
        self,
        transcript: str,
        *,
        session_id: str,
        mode: str,
        source: str,
        metadata: dict[str, Any],
        transcription_result: VoiceTranscriptionResult | None = None,
    ) -> VoiceTurnResult | None:
        intent = self.classify_spoken_confirmation(
            transcript, source=source, session_id=session_id
        )
        if intent.intent in {
            VoiceSpokenConfirmationIntentKind.NONE,
            VoiceSpokenConfirmationIntentKind.NOT_CONFIRMATION,
            VoiceSpokenConfirmationIntentKind.UNKNOWN,
        }:
            return None
        confirmation_metadata = dict(metadata)
        listen_window_id = self._metadata_listen_window_id(confirmation_metadata)
        if listen_window_id:
            confirmation_metadata.setdefault("listen_window_id", listen_window_id)
            confirmation_metadata.setdefault(
                "post_wake_listen",
                {
                    "listen_window_id": listen_window_id,
                    "provenance_only": True,
                    "command_authority_granted": False,
                },
            )
        result = await self.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript=transcript,
                normalized_phrase=intent.normalized_phrase,
                session_id=session_id,
                source=source,
                pending_confirmation_id=confirmation_metadata.get(
                    "pending_confirmation_id"
                ),
                task_id=confirmation_metadata.get("task_id"),
                route_family=confirmation_metadata.get("route_family"),
                metadata=confirmation_metadata,
            )
        )
        return self._spoken_confirmation_turn_result(
            transcript=transcript,
            session_id=session_id,
            mode=mode,
            source=source,
            metadata=metadata,
            confirmation_result=result,
            transcription_result=transcription_result,
        )

    def _spoken_confirmation_turn_result(
        self,
        *,
        transcript: str,
        session_id: str,
        mode: str,
        source: str,
        metadata: dict[str, Any],
        confirmation_result: VoiceSpokenConfirmationResult,
        transcription_result: VoiceTranscriptionResult | None = None,
    ) -> VoiceTurnResult:
        state_before = self.state_controller.snapshot().to_dict()
        turn = VoiceTurn(
            session_id=session_id,
            transcript=transcript,
            normalized_transcript=transcript,
            interaction_mode=mode,
            source=source,
            availability_snapshot=self.availability.to_dict(),
            voice_state_before=state_before,
            confirmation_intent=confirmation_result.intent.value,
            metadata={
                **dict(metadata),
                "spoken_confirmation": confirmation_result.to_dict(),
            },
            core_bridge_required=False,
            transcription_id=transcription_result.transcription_id
            if transcription_result is not None
            else None,
            transcription_provider=transcription_result.provider
            if transcription_result is not None
            else None,
            transcription_model=transcription_result.model
            if transcription_result is not None
            else None,
        )
        result_state = {
            "confirmed": "confirmation_accepted",
            "rejected": "confirmation_rejected",
            "cancelled": "confirmation_rejected",
            "shown": "confirmation_detail_shown",
            "ambiguous": "clarification_required",
            "expired": "confirmation_expired",
            "stale": "confirmation_stale",
            "no_pending_confirmation": "no_pending_confirmation",
        }.get(confirmation_result.status, "confirmation_blocked")
        core_result = VoiceCoreResult(
            result_state=result_state,
            spoken_summary=confirmation_result.spoken_response_candidate or "",
            visual_summary=confirmation_result.user_message
            or confirmation_result.reason
            or "Spoken confirmation handled.",
            route_family=confirmation_result.route_family,
            subsystem=confirmation_result.subsystem or "voice_confirmation",
            trust_posture="voice_confirmation_bound"
            if confirmation_result.binding is not None
            else "voice_confirmation_unbound",
            verification_posture="not_verified",
            task_id=confirmation_result.binding.task_id
            if confirmation_result.binding is not None
            else metadata.get("task_id"),
            speak_allowed=bool(confirmation_result.spoken_response_candidate),
            continue_listening=False,
            error_code=confirmation_result.error_code,
            provenance={
                "source": "voice_confirmation",
                "voice_confirmation": confirmation_result.to_dict(),
            },
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
        return VoiceTurnResult(
            ok=confirmation_result.ok,
            turn=turn,
            core_result=core_result,
            transcription_result=transcription_result,
            spoken_response=spoken_response,
            voice_state_before=state_before,
            voice_state_after=self.state_controller.snapshot().to_dict(),
            state_transitions=[state_before, self.state_controller.snapshot().to_dict()],
            error_code=confirmation_result.error_code,
            error_message=None
            if confirmation_result.ok
            else confirmation_result.user_message or confirmation_result.reason,
            provider_network_call_count=self._provider_network_call_count(),
            stt_invoked=transcription_result is not None,
            tts_invoked=False,
            realtime_invoked=False,
            audio_playback_started=False,
        )

    def wake_readiness_report(self) -> VoiceWakeReadiness:
        availability = self._wake_provider_availability()
        blocking_reasons: list[str] = []
        warnings: list[str] = []
        if not self.config.wake.enabled:
            blocking_reasons.append("wake_disabled")
        elif not availability.get("available"):
            blocking_reasons.append(
                str(availability.get("unavailable_reason") or "wake_unavailable")
            )
        if availability.get("mock_provider_active"):
            warnings.append("mock_wake_provider_active")
        return VoiceWakeReadiness(
            wake_enabled=self.config.wake.enabled,
            wake_provider=self._wake_provider_name(),
            wake_provider_kind=str(
                availability.get("provider_kind") or self._wake_provider_name()
            ),
            wake_available=bool(
                self.config.wake.enabled and availability.get("available")
            ),
            wake_monitoring_active=bool(self.wake_monitoring_active),
            wake_phrase_configured=bool(str(self.config.wake.wake_phrase).strip()),
            wake_phrase=self.config.wake.wake_phrase,
            confidence_threshold=self.config.wake.confidence_threshold,
            cooldown_ms=self.config.wake.cooldown_ms,
            last_wake_event_id=self.last_wake_event.wake_event_id
            if self.last_wake_event is not None
            else None,
            last_wake_status=self.last_wake_event.status
            if self.last_wake_event is not None
            else None,
            last_wake_confidence=self.last_wake_event.confidence
            if self.last_wake_event is not None
            else None,
            wake_backend=availability.get("backend"),
            dependency_available=availability.get("dependency_available"),
            platform_supported=availability.get("platform_supported"),
            device=availability.get("device"),
            device_available=availability.get("device_available"),
            permission_state=availability.get("permission_state"),
            permission_error=availability.get("permission_error"),
            blocking_reasons=self._dedupe_strings(blocking_reasons),
            warnings=self._dedupe_strings(warnings),
            no_cloud_wake_audio=True,
            openai_wake_detection=False,
            cloud_wake_detection=False,
            command_routing_from_wake=False,
            always_listening=False,
            realtime_wake_detection=False,
        )

    def vad_readiness_report(self) -> VoiceVADReadiness:
        availability = self._vad_provider_availability()
        active = self.get_active_vad_session()
        blocking_reasons: list[str] = []
        warnings: list[str] = []
        if not self.config.vad.enabled:
            blocking_reasons.append("vad_disabled")
        elif not availability.get("available"):
            blocking_reasons.append(
                str(availability.get("unavailable_reason") or "vad_unavailable")
            )
        if availability.get("mock_provider_active"):
            warnings.append("mock_vad_provider_active")
        return VoiceVADReadiness(
            vad_enabled=self.config.vad.enabled,
            vad_provider=self._vad_provider_name(),
            vad_provider_kind=str(
                availability.get("provider_kind") or self._vad_provider_name()
            ),
            vad_available=bool(
                self.config.vad.enabled and availability.get("available")
            ),
            vad_active=active is not None,
            active_capture_id=active.capture_id if active is not None else None,
            active_listen_window_id=active.listen_window_id
            if active is not None
            else None,
            silence_ms=self.config.vad.silence_ms,
            speech_start_threshold=self.config.vad.speech_start_threshold,
            speech_stop_threshold=self.config.vad.speech_stop_threshold,
            max_utterance_ms=self.config.vad.max_utterance_ms,
            blocking_reasons=self._dedupe_strings(blocking_reasons),
            warnings=self._dedupe_strings(warnings),
            semantic_completion_claimed=False,
            realtime_vad=False,
            command_authority=False,
        )

    def realtime_readiness_report(self) -> VoiceRealtimeReadiness:
        availability = self._realtime_provider_availability()
        active = self.get_active_realtime_session()
        blocking_reasons: list[str] = []
        warnings: list[str] = []
        supported_mode = self.config.realtime.mode in {
            "transcription_bridge",
            "speech_to_speech_core_bridge",
        }
        speech_mode = self.config.realtime.mode == "speech_to_speech_core_bridge"
        if not self.config.realtime.enabled:
            blocking_reasons.append("realtime_disabled")
        elif not supported_mode:
            blocking_reasons.append("unsupported_realtime_mode")
        elif speech_mode and not self.config.realtime.speech_to_speech_enabled:
            blocking_reasons.append("speech_to_speech_not_enabled")
        elif speech_mode and not self.config.realtime.audio_output_from_realtime:
            blocking_reasons.append("realtime_audio_output_not_enabled")
        elif not availability.get("available"):
            blocking_reasons.append(
                str(availability.get("unavailable_reason") or "realtime_unavailable")
            )
        if availability.get("mock_provider_active"):
            warnings.append("mock_realtime_provider_active")
        if self.config.realtime.semantic_vad_enabled:
            warnings.append("semantic_vad_metadata_only")
        return VoiceRealtimeReadiness(
            realtime_enabled=self.config.realtime.enabled,
            realtime_provider=self._realtime_provider_name(),
            realtime_provider_kind=str(
                availability.get("provider_kind") or self._realtime_provider_name()
            ),
            realtime_available=bool(
                self.config.realtime.enabled and availability.get("available")
            ),
            realtime_mode=self.config.realtime.mode,
            model=self.config.realtime.model,
            voice=self.config.realtime.voice,
            turn_detection=self.config.realtime.turn_detection,
            semantic_vad_enabled=bool(self.config.realtime.semantic_vad_enabled),
            session_active=active is not None,
            active_session_id=active.realtime_session_id
            if active is not None
            else None,
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=bool(
                speech_mode and self.config.realtime.speech_to_speech_enabled
            ),
            audio_output_from_realtime=bool(
                speech_mode and self.config.realtime.audio_output_from_realtime
            ),
            core_bridge_tool_enabled=bool(
                speech_mode and self.config.realtime.speech_to_speech_enabled
            ),
            direct_action_tools_exposed=False,
            require_core_for_commands=True,
            allow_smalltalk_without_core=bool(
                self.config.realtime.allow_smalltalk_without_core
            ),
            blocking_reasons=self._dedupe_strings(blocking_reasons),
            warnings=self._dedupe_strings(warnings),
            openai_configured=bool(availability.get("openai_configured")),
            api_key_present=bool(availability.get("api_key_present")),
            provider_configured=bool(
                str(self.config.realtime.provider or "").strip()
            ),
            no_cloud_wake_detection=True,
            wake_detection_local_only=True,
            command_authority="stormhelm_core",
        )

    async def start_realtime_session(
        self,
        *,
        session_id: str | None = None,
        source: str = "test",
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeSession:
        availability = self._realtime_provider_availability()
        speech_mode = self.config.realtime.mode == "speech_to_speech_core_bridge"
        failed_event = (
            VoiceEventType.REALTIME_SPEECH_SESSION_FAILED
            if speech_mode
            else VoiceEventType.REALTIME_SESSION_FAILED
        )
        if not self.config.realtime.enabled or not availability.get("available"):
            session = self._terminal_realtime_session(
                session_id=session_id,
                source=source,
                listen_window_id=listen_window_id,
                capture_id=capture_id,
                status="unavailable",
                error_code=str(
                    availability.get("unavailable_reason") or "realtime_unavailable"
                ),
                error_message="Realtime transcription bridge is unavailable.",
            )
            self._remember_realtime_session(session)
            self._publish_realtime_session_event(
                failed_event,
                session,
                message=session.error_message or "Realtime session unavailable.",
            )
            return session

        active = self.get_active_realtime_session()
        if active is not None:
            session = self._terminal_realtime_session(
                session_id=session_id,
                source=source,
                listen_window_id=listen_window_id,
                capture_id=capture_id,
                status="failed",
                error_code="realtime_session_already_active",
                error_message="A Realtime transcription session is already active.",
            )
            self._remember_realtime_session(session)
            self._publish_realtime_session_event(
                failed_event,
                session,
                message=session.error_message or "Realtime session already active.",
            )
            return session

        create = getattr(self.realtime_provider, "create_session", None)
        if not callable(create):
            session = self._terminal_realtime_session(
                session_id=session_id,
                source=source,
                listen_window_id=listen_window_id,
                capture_id=capture_id,
                status="unavailable",
                error_code="provider_unavailable",
                error_message="Realtime provider does not implement sessions.",
            )
            self._remember_realtime_session(session)
            return session

        created = create(
            session_id=session_id,
            source=source,
            listen_window_id=listen_window_id,
            capture_id=capture_id,
        )
        created = replace(
            created,
            expires_at=self._realtime_session_expires_at(),
            status="created" if created.status == "created" else created.status,
        )
        self._remember_realtime_session(created)
        self._publish_realtime_session_event(
            VoiceEventType.REALTIME_SPEECH_SESSION_CREATED
            if speech_mode
            else VoiceEventType.REALTIME_SESSION_CREATED,
            created,
            message="Realtime speech session created."
            if speech_mode
            else "Realtime transcription session created.",
        )

        start = getattr(self.realtime_provider, "start_session", None)
        started = start(created.realtime_session_id) if callable(start) else created
        started = replace(started, expires_at=created.expires_at)
        self._remember_realtime_session(started)
        self._publish_realtime_session_event(
            (
                VoiceEventType.REALTIME_SPEECH_SESSION_STARTED
                if speech_mode
                else VoiceEventType.REALTIME_SESSION_STARTED
            )
            if started.status == "active"
            else failed_event,
            started,
            message=(
                "Realtime speech session started."
                if speech_mode
                else "Realtime transcription session started."
            )
            if started.status == "active"
            else (
                started.error_message
                or (
                    "Realtime speech session failed."
                    if speech_mode
                    else "Realtime transcription session failed."
                )
            ),
        )
        return started

    async def close_realtime_session(
        self,
        realtime_session_id: str | None = None,
        *,
        reason: str = "closed",
    ) -> VoiceRealtimeSession:
        active = self.get_active_realtime_session()
        operation = getattr(self.realtime_provider, "close_session", None)
        if callable(operation):
            session = operation(
                realtime_session_id or (active.realtime_session_id if active else None),
                reason=reason,
            )
        elif active is not None:
            status = "cancelled" if reason == "cancelled" else "closed"
            session = replace(active, status=status, closed_at=self._now())
        else:
            session = self._terminal_realtime_session(
                session_id=None,
                source="test",
                listen_window_id=None,
                capture_id=None,
                status="closed",
                error_code="no_active_realtime_session",
                error_message="No active Realtime transcription session exists.",
            )
        self._remember_realtime_session(session)
        speech_mode = session.mode == "speech_to_speech_core_bridge"
        event_type = (
            VoiceEventType.REALTIME_SESSION_CANCELLED
            if session.status == "cancelled"
            else (
                VoiceEventType.REALTIME_SPEECH_SESSION_CLOSED
                if speech_mode
                else VoiceEventType.REALTIME_SESSION_CLOSED
            )
        )
        self._publish_realtime_session_event(
            event_type,
            session,
            message="Realtime session cancelled."
            if session.status == "cancelled"
            else (
                "Realtime speech session closed."
                if speech_mode
                else "Realtime transcription session closed."
            ),
        )
        return session

    async def cancel_realtime_session(
        self, realtime_session_id: str | None = None
    ) -> VoiceRealtimeSession:
        return await self.close_realtime_session(
            realtime_session_id, reason="cancelled"
        )

    def get_active_realtime_session(self) -> VoiceRealtimeSession | None:
        active = self.active_realtime_session
        if active is not None and active.expires_at and self._is_expired(
            active.expires_at
        ):
            expired = replace(active, status="expired", closed_at=self._now())
            self._remember_realtime_session(expired)
            self._publish_realtime_session_event(
                VoiceEventType.REALTIME_SESSION_EXPIRED,
                expired,
                message="Realtime transcription session expired.",
            )
        return self.active_realtime_session

    async def simulate_realtime_partial_transcript(
        self,
        transcript: str,
        *,
        realtime_session_id: str | None = None,
        listen_window_id: str | None = None,
        capture_id: str | None = None,
    ) -> VoiceRealtimeTranscriptEvent:
        operation = getattr(self.realtime_provider, "simulate_partial_transcript", None)
        if not callable(operation):
            raise RuntimeError("Realtime provider does not support simulated partials.")
        event = operation(
            transcript,
            realtime_session_id=realtime_session_id,
            listen_window_id=listen_window_id,
            capture_id=capture_id,
        )
        self._remember_realtime_transcript_event(event)
        self._publish_realtime_transcript_event(
            VoiceEventType.REALTIME_PARTIAL_TRANSCRIPT,
            event,
            message="Realtime partial transcript received.",
        )
        return event

    async def simulate_realtime_final_transcript(
        self,
        transcript: str,
        *,
        realtime_session_id: str | None = None,
        listen_window_id: str | None = None,
        capture_id: str | None = None,
        mode: str = "ghost",
        screen_context_permission: str = "not_requested",
        metadata: dict[str, Any] | None = None,
    ) -> VoiceRealtimeTurnResult:
        operation = getattr(self.realtime_provider, "simulate_final_transcript", None)
        if not callable(operation):
            return self._remember_realtime_turn_result(
                VoiceRealtimeTurnResult(
                    realtime_turn_id=f"voice-realtime-turn-{uuid4().hex[:12]}",
                    realtime_session_id=realtime_session_id or "",
                    final_transcript=transcript,
                    final_status="failed",
                    failed_stage="realtime",
                    error_code="provider_unavailable",
                    error_message="Realtime provider does not support final transcripts.",
                )
            )
        event = operation(
            transcript,
            realtime_session_id=realtime_session_id,
            listen_window_id=listen_window_id,
            capture_id=capture_id,
        )
        self._remember_realtime_transcript_event(event)
        self._publish_realtime_transcript_event(
            VoiceEventType.REALTIME_FINAL_TRANSCRIPT,
            event,
            message="Realtime final transcript received.",
        )
        return await self.submit_realtime_final_transcript(
            event,
            mode=mode,
            screen_context_permission=screen_context_permission,
            metadata=metadata,
        )

    async def submit_realtime_final_transcript(
        self,
        event: VoiceRealtimeTranscriptEvent,
        *,
        mode: str = "ghost",
        screen_context_permission: str = "not_requested",
        metadata: dict[str, Any] | None = None,
    ) -> VoiceRealtimeTurnResult:
        transcript = " ".join(str(event.transcript_text or "").split()).strip()
        if not transcript:
            result = VoiceRealtimeTurnResult(
                realtime_turn_id=event.realtime_turn_id,
                realtime_session_id=event.realtime_session_id,
                final_transcript="",
                source=event.source,
                final_status="empty_transcript",
                failed_stage="realtime_transcription",
                error_code="empty_transcript",
                error_message="Realtime final transcript was empty.",
            )
            return self._remember_realtime_turn_result(result)

        turn_metadata = dict(metadata or {})
        turn_metadata.update(
            {
                "turn_source": event.source,
                "realtime": {
                    "realtime_session_id": event.realtime_session_id,
                    "realtime_turn_id": event.realtime_turn_id,
                    "realtime_event_id": event.realtime_event_id,
                    "mode": self.config.realtime.mode,
                    "model": self.config.realtime.model,
                    "direct_tools_allowed": False,
                    "core_bridge_required": True,
                    "speech_to_speech_enabled": False,
                    "audio_output_from_realtime": False,
                    "raw_audio_present": False,
                },
                "raw_audio_present": False,
                "bounded_active_session_audio_only": True,
                "realtime_transcription_bridge": True,
            }
        )
        if event.listen_window_id:
            turn_metadata["listen_window_id"] = event.listen_window_id
            turn_metadata.setdefault(
                "post_wake_listen",
                {
                    "listen_window_id": event.listen_window_id,
                    "provenance_only": True,
                    "command_authority_granted": False,
                },
            )
        if event.capture_id:
            turn_metadata["capture_id"] = event.capture_id

        self._publish(
            VoiceEventType.REALTIME_TURN_CREATED,
            message="Realtime final transcript created a VoiceTurn candidate.",
            session_id=event.session_id,
            listen_window_id=event.listen_window_id,
            capture_id=event.capture_id,
            realtime_session_id=event.realtime_session_id,
            realtime_turn_id=event.realtime_turn_id,
            realtime_event_id=event.realtime_event_id,
            provider=self._realtime_provider_name(),
            provider_kind=self.realtime_readiness_report().realtime_provider_kind,
            model=self.config.realtime.model,
            mode=self.config.realtime.mode,
            source=event.source,
            is_final=True,
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=False,
            audio_output_from_realtime=False,
            raw_audio_present=False,
            metadata={"transcript_preview": self._preview_text(transcript)},
        )
        if self.core_bridge is not None:
            self._publish(
                VoiceEventType.REALTIME_TURN_SUBMITTED_TO_CORE,
                message="Realtime final transcript submitted through the Core bridge.",
                session_id=event.session_id,
                listen_window_id=event.listen_window_id,
                capture_id=event.capture_id,
                realtime_session_id=event.realtime_session_id,
                realtime_turn_id=event.realtime_turn_id,
                realtime_event_id=event.realtime_event_id,
                provider=self._realtime_provider_name(),
                provider_kind=self.realtime_readiness_report().realtime_provider_kind,
                model=self.config.realtime.model,
                mode=self.config.realtime.mode,
                source=event.source,
                is_final=True,
                direct_tools_allowed=False,
                core_bridge_required=True,
                speech_to_speech_enabled=False,
                audio_output_from_realtime=False,
                raw_audio_present=False,
                metadata={"transcript_preview": self._preview_text(transcript)},
            )

        turn_result = await self.submit_manual_voice_turn(
            transcript,
            mode=mode,
            session_id=event.session_id,
            metadata=turn_metadata,
            screen_context_permission=screen_context_permission,
        )
        if turn_result.turn is not None:
            patched_turn = replace(
                turn_result.turn,
                source=event.source,
                metadata={
                    **dict(turn_result.turn.metadata),
                    "realtime": turn_metadata["realtime"],
                },
            )
            turn_result = replace(
                turn_result,
                turn=patched_turn,
                realtime_invoked=True,
                stt_invoked=False,
            )
            self.last_manual_turn_result = turn_result
        core = turn_result.core_result
        final_status = (
            core.result_state
            if core is not None and core.result_state
            else ("completed" if turn_result.ok else turn_result.error_code or "failed")
        )
        if final_status == "confirmation_accepted":
            final_status = "confirmed"
        result = VoiceRealtimeTurnResult(
            realtime_turn_id=event.realtime_turn_id,
            realtime_session_id=event.realtime_session_id,
            final_transcript=transcript,
            source=event.source,
            voice_turn_id=turn_result.turn.turn_id
            if turn_result.turn is not None
            else None,
            core_request_id=turn_result.core_request.request_id
            if turn_result.core_request is not None
            else None,
            core_result_state=core.result_state if core is not None else None,
            route_family=core.route_family if core is not None else None,
            subsystem=core.subsystem if core is not None else None,
            trust_posture=core.trust_posture if core is not None else None,
            verification_posture=core.verification_posture if core is not None else None,
            spoken_response_status="prepared"
            if turn_result.spoken_response is not None
            else None,
            final_status=final_status,
            failed_stage=None if turn_result.ok else "core_bridge",
            completed_at=self._now(),
            error_code=turn_result.error_code,
            error_message=turn_result.error_message,
            metadata={
                "voice_turn_result": turn_result.to_dict(),
                "realtime_transcription_bridge_only": True,
            },
        )
        self._remember_realtime_turn_result(result)
        self._publish(
            VoiceEventType.REALTIME_TURN_COMPLETED
            if turn_result.ok
            else VoiceEventType.REALTIME_TURN_FAILED,
            message="Realtime transcript turn completed."
            if turn_result.ok
            else "Realtime transcript turn failed.",
            session_id=event.session_id,
            turn_id=result.voice_turn_id,
            listen_window_id=event.listen_window_id,
            capture_id=event.capture_id,
            realtime_session_id=event.realtime_session_id,
            realtime_turn_id=event.realtime_turn_id,
            realtime_event_id=event.realtime_event_id,
            provider=self._realtime_provider_name(),
            provider_kind=self.realtime_readiness_report().realtime_provider_kind,
            model=self.config.realtime.model,
            mode=self.config.realtime.mode,
            source=event.source,
            result_state=result.core_result_state,
            route_family=result.route_family,
            subsystem=result.subsystem,
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=False,
            audio_output_from_realtime=False,
            raw_audio_present=False,
            metadata={"realtime_turn_result": result.to_dict()},
        )
        return result

    def realtime_session_instructions(self) -> str:
        return "\n".join(
            [
                "You are Stormhelm's voice surface.",
                "Stormhelm is a calm naval intelligence; be concise, composed, and restrained.",
                "Do not use fake pirate slang or playful nautical filler.",
                "For any command, action, system request, cancellation, correction, approval, or risky request, call stormhelm_core_request.",
                "Do not execute actions directly.",
                "Do not approve actions directly.",
                "Do not verify outcomes directly.",
                "Do not expose or call direct tools.",
                "Do not bypass trust gates, task graph, adapter contracts, recovery, verification, or command routing.",
                "If unsure whether a request is an action, call Core.",
                "Use Core-provided spoken_summary for action-related or safety-sensitive results.",
                "If Core says confirmation required, speak the confirmation prompt only.",
                "If Core says blocked, speak the block reason only.",
                "If Core says attempted but unverified, do not say done or verified.",
                "Do not claim completion, verification, permission, or action unless Core returned it.",
            ]
        )

    async def stormhelm_core_request(
        self,
        *,
        transcript: str,
        realtime_session_id: str | None = None,
        realtime_turn_id: str | None = None,
        session_id: str | None = None,
        source: str = "realtime_speech",
        interaction_mode: str = "ghost",
        route_context: dict[str, Any] | None = None,
        listen_window_id: str | None = None,
        capture_id: str | None = None,
        pending_confirmation_id: str | None = None,
        interruption_intent: str | None = None,
        correction_context: dict[str, Any] | None = None,
        screen_context_permission: str = "not_requested",
        metadata: dict[str, Any] | None = None,
    ) -> VoiceRealtimeCoreBridgeCall:
        normalized = " ".join(str(transcript or "").split()).strip()
        active = self.get_active_realtime_session()
        resolved_session_id = (
            str(session_id or "").strip()
            or (active.session_id if active is not None else "")
            or "default"
        )
        resolved_realtime_session_id = realtime_session_id or (
            active.realtime_session_id if active is not None else None
        )
        resolved_realtime_turn_id = realtime_turn_id or (
            active.active_turn_id if active is not None else None
        )
        if not resolved_realtime_turn_id:
            resolved_realtime_turn_id = f"voice-realtime-turn-{uuid4().hex[:12]}"
        turn_metadata = dict(metadata or {})
        if route_context:
            turn_metadata["route_context"] = dict(route_context)
        if correction_context:
            turn_metadata["correction_context"] = dict(correction_context)
        if listen_window_id:
            turn_metadata["listen_window_id"] = listen_window_id
        if capture_id:
            turn_metadata["capture_id"] = capture_id
        if pending_confirmation_id:
            turn_metadata["pending_confirmation_id"] = pending_confirmation_id
        provider_injected_ignored = any(
            key in turn_metadata
            for key in {
                "provider_injected_route_family",
                "provider_injected_action",
                "provider_injected_result_state",
                "provider_injected_tool",
            }
        )
        turn_metadata.update(
            {
                "turn_source": source,
                "core_bridge_tool_name": "stormhelm_core_request",
                "provider_injected_route_family_ignored": provider_injected_ignored,
                "provider_injected_action_ignored": provider_injected_ignored,
                "direct_tools_allowed": False,
                "direct_action_tools_exposed": False,
                "core_bridge_required": True,
                "speech_to_speech_enabled": bool(
                    self.config.realtime.mode == "speech_to_speech_core_bridge"
                    and self.config.realtime.speech_to_speech_enabled
                ),
                "audio_output_from_realtime": bool(
                    self.config.realtime.mode == "speech_to_speech_core_bridge"
                    and self.config.realtime.audio_output_from_realtime
                ),
                "raw_audio_present": False,
                "bounded_active_session_audio_only": True,
                "realtime": {
                    "realtime_session_id": resolved_realtime_session_id,
                    "realtime_turn_id": resolved_realtime_turn_id,
                    "mode": self.config.realtime.mode,
                    "model": self.config.realtime.model,
                    "voice": self.config.realtime.voice,
                    "direct_tools_allowed": False,
                    "direct_action_tools_exposed": False,
                    "core_bridge_required": True,
                    "core_bridge_tool_name": "stormhelm_core_request",
                    "speech_to_speech_enabled": bool(
                        self.config.realtime.mode == "speech_to_speech_core_bridge"
                        and self.config.realtime.speech_to_speech_enabled
                    ),
                    "audio_output_from_realtime": bool(
                        self.config.realtime.mode == "speech_to_speech_core_bridge"
                        and self.config.realtime.audio_output_from_realtime
                    ),
                    "raw_audio_present": False,
                },
            }
        )
        if not normalized:
            call = VoiceRealtimeCoreBridgeCall(
                transcript="",
                session_id=resolved_session_id,
                realtime_session_id=resolved_realtime_session_id,
                realtime_turn_id=resolved_realtime_turn_id,
                status="empty_transcript",
                result_state="empty_transcript",
                speak_allowed=False,
                error_code="empty_transcript",
                error_message="Realtime speech transcript was empty.",
                completed_at=self._now(),
                metadata=turn_metadata,
            )
            return self._remember_realtime_core_bridge_call(call)

        confirmation_turn = await self._maybe_handle_spoken_confirmation_turn(
            normalized,
            session_id=resolved_session_id,
            mode=interaction_mode,
            source=source,
            metadata=turn_metadata,
        )
        if confirmation_turn is not None:
            core = confirmation_turn.core_result
            status = core.result_state if core is not None else "handled"
            if status == "confirmation_accepted":
                status = "confirmed"
            call = VoiceRealtimeCoreBridgeCall(
                transcript=normalized,
                session_id=resolved_session_id,
                realtime_session_id=resolved_realtime_session_id,
                realtime_turn_id=resolved_realtime_turn_id,
                status=status,
                voice_turn_id=confirmation_turn.turn.turn_id
                if confirmation_turn.turn is not None
                else None,
                result_state=core.result_state if core is not None else status,
                route_family=core.route_family if core is not None else None,
                subsystem=core.subsystem if core is not None else "voice_confirmation",
                trust_posture=core.trust_posture if core is not None else None,
                verification_posture=core.verification_posture
                if core is not None
                else None,
                task_id=core.task_id if core is not None else None,
                spoken_summary=core.spoken_summary if core is not None else "",
                visual_summary=core.visual_summary if core is not None else "",
                speak_allowed=core.speak_allowed if core is not None else False,
                continue_listening=core.continue_listening
                if core is not None
                else False,
                completed_at=self._now(),
                metadata={
                    **turn_metadata,
                    "voice_turn_result": confirmation_turn.to_dict(),
                    "confirmation_handled_by_voice16": True,
                },
            )
            return self._remember_realtime_core_bridge_call(call)

        call = VoiceRealtimeCoreBridgeCall(
            transcript=normalized,
            session_id=resolved_session_id,
            realtime_session_id=resolved_realtime_session_id,
            realtime_turn_id=resolved_realtime_turn_id,
            status="started",
            metadata=turn_metadata,
        )
        self._remember_realtime_core_bridge_call(call)
        self._publish(
            VoiceEventType.REALTIME_CORE_BRIDGE_CALL_STARTED,
            message="Realtime speech turn submitted to the Stormhelm Core bridge.",
            session_id=resolved_session_id,
            listen_window_id=listen_window_id,
            capture_id=capture_id,
            realtime_session_id=resolved_realtime_session_id,
            realtime_turn_id=resolved_realtime_turn_id,
            provider=self._realtime_provider_name(),
            provider_kind=self.realtime_readiness_report().realtime_provider_kind,
            model=self.config.realtime.model,
            voice=self.config.realtime.voice,
            mode=self.config.realtime.mode,
            source=source,
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=call.metadata.get("speech_to_speech_enabled"),
            audio_output_from_realtime=call.metadata.get(
                "audio_output_from_realtime"
            ),
            raw_audio_present=False,
            metadata={
                "core_bridge_call_id": call.core_bridge_call_id,
                "core_bridge_tool_name": call.core_bridge_tool_name,
                "transcript_preview": self._preview_text(normalized),
                "direct_action_tools_exposed": False,
            },
        )
        if self.core_bridge is None:
            failed = replace(
                call,
                status="failed",
                result_state="failed",
                speak_allowed=False,
                error_code="core_bridge_missing",
                error_message="Realtime speech requires the Stormhelm Core bridge.",
                completed_at=self._now(),
            )
            self._remember_realtime_core_bridge_call(failed)
            self._publish(
                VoiceEventType.REALTIME_CORE_BRIDGE_CALL_FAILED,
                message="Realtime speech Core bridge call failed.",
                session_id=resolved_session_id,
                listen_window_id=listen_window_id,
                capture_id=capture_id,
                realtime_session_id=resolved_realtime_session_id,
                realtime_turn_id=resolved_realtime_turn_id,
                provider=self._realtime_provider_name(),
                provider_kind=self.realtime_readiness_report().realtime_provider_kind,
                model=self.config.realtime.model,
                voice=self.config.realtime.voice,
                mode=self.config.realtime.mode,
                source=source,
                status=failed.status,
                error_code=failed.error_code,
                result_state=failed.result_state,
                direct_tools_allowed=False,
                core_bridge_required=True,
                speech_to_speech_enabled=call.metadata.get(
                    "speech_to_speech_enabled"
                ),
                audio_output_from_realtime=call.metadata.get(
                    "audio_output_from_realtime"
                ),
                raw_audio_present=False,
                metadata={"realtime_core_bridge_call": failed.to_dict()},
            )
            return failed

        voice_turn = VoiceTurn(
            session_id=resolved_session_id,
            transcript=normalized,
            normalized_transcript=normalized,
            interaction_mode=interaction_mode,
            source=source,
            availability_snapshot=self.availability.to_dict(),
            voice_state_before=self.state_controller.snapshot().to_dict(),
            screen_context_permission=screen_context_permission,
            interrupt_intent=interruption_intent,
            metadata=turn_metadata,
            core_bridge_required=True,
        )
        core_request = VoiceCoreRequest(
            transcript=normalized,
            session_id=resolved_session_id,
            turn_id=voice_turn.turn_id,
            source=source,
            voice_mode="realtime_speech",
            interaction_mode=interaction_mode,
            screen_context_permission=screen_context_permission,
            interrupt_intent=interruption_intent,
            metadata=turn_metadata,
            core_bridge_required=True,
        )
        try:
            core_result = await submit_voice_core_request(self.core_bridge, core_request)
        except Exception as exc:
            failed = replace(
                call,
                status="failed",
                voice_turn_id=voice_turn.turn_id,
                core_request_id=core_request.request_id,
                result_state="failed",
                speak_allowed=False,
                error_code=type(exc).__name__,
                error_message=str(exc),
                completed_at=self._now(),
            )
            self._remember_realtime_core_bridge_call(failed)
            self._publish(
                VoiceEventType.REALTIME_CORE_BRIDGE_CALL_FAILED,
                message="Realtime speech Core bridge call failed.",
                session_id=resolved_session_id,
                turn_id=voice_turn.turn_id,
                listen_window_id=listen_window_id,
                capture_id=capture_id,
                realtime_session_id=resolved_realtime_session_id,
                realtime_turn_id=resolved_realtime_turn_id,
                provider=self._realtime_provider_name(),
                provider_kind=self.realtime_readiness_report().realtime_provider_kind,
                model=self.config.realtime.model,
                voice=self.config.realtime.voice,
                mode=self.config.realtime.mode,
                source=source,
                status=failed.status,
                error_code=failed.error_code,
                result_state=failed.result_state,
                direct_tools_allowed=False,
                core_bridge_required=True,
                speech_to_speech_enabled=call.metadata.get(
                    "speech_to_speech_enabled"
                ),
                audio_output_from_realtime=call.metadata.get(
                    "audio_output_from_realtime"
                ),
                raw_audio_present=False,
                metadata={"realtime_core_bridge_call": failed.to_dict()},
            )
            return failed

        completed = replace(
            call,
            status="completed",
            voice_turn_id=voice_turn.turn_id,
            core_request_id=core_request.request_id,
            result_state=core_result.result_state,
            route_family=core_result.route_family,
            subsystem=core_result.subsystem,
            trust_posture=core_result.trust_posture,
            verification_posture=core_result.verification_posture,
            task_id=core_result.task_id,
            approval_required=core_result.result_state == "requires_confirmation"
            or core_result.trust_posture == "approval_required",
            confirmation_prompt=core_result.spoken_summary
            if core_result.result_state == "requires_confirmation"
            else None,
            spoken_summary=core_result.spoken_summary,
            visual_summary=core_result.visual_summary,
            speak_allowed=core_result.speak_allowed,
            continue_listening=core_result.continue_listening,
            followup_binding=dict(core_result.followup_binding or {}),
            error_code=core_result.error_code,
            provenance_summary=dict(core_result.provenance or {}),
            completed_at=self._now(),
            metadata={
                **turn_metadata,
                "voice_turn": voice_turn.to_dict(),
                "core_request": core_request.to_dict(),
                "core_result": core_result.to_dict(),
            },
        )
        self._remember_realtime_core_bridge_call(completed)
        self._publish(
            VoiceEventType.REALTIME_CORE_BRIDGE_CALL_COMPLETED,
            message="Realtime speech Core bridge call completed.",
            session_id=resolved_session_id,
            turn_id=voice_turn.turn_id,
            listen_window_id=listen_window_id,
            capture_id=capture_id,
            realtime_session_id=resolved_realtime_session_id,
            realtime_turn_id=resolved_realtime_turn_id,
            provider=self._realtime_provider_name(),
            provider_kind=self.realtime_readiness_report().realtime_provider_kind,
            model=self.config.realtime.model,
            voice=self.config.realtime.voice,
            mode=self.config.realtime.mode,
            source=source,
            task_id=completed.task_id,
            status=completed.status,
            result_state=completed.result_state,
            route_family=completed.route_family,
            subsystem=completed.subsystem,
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=call.metadata.get("speech_to_speech_enabled"),
            audio_output_from_realtime=call.metadata.get(
                "audio_output_from_realtime"
            ),
            raw_audio_present=False,
            metadata={"realtime_core_bridge_call": completed.to_dict()},
        )
        return completed

    def gate_realtime_spoken_response(
        self, call: VoiceRealtimeCoreBridgeCall
    ) -> VoiceRealtimeResponseGate:
        if not call.speak_allowed:
            gate = VoiceRealtimeResponseGate(
                core_bridge_call_id=call.core_bridge_call_id,
                realtime_session_id=call.realtime_session_id,
                realtime_turn_id=call.realtime_turn_id,
                result_state=call.result_state,
                status="blocked",
                speak_allowed=False,
                spoken_text="",
                spoken_summary_source="blocked",
                reason="core_speak_not_allowed",
                route_family=call.route_family,
                subsystem=call.subsystem,
                trust_posture=call.trust_posture,
                verification_posture=call.verification_posture,
                metadata={"realtime_core_bridge_call": call.to_dict()},
            )
        else:
            gate = VoiceRealtimeResponseGate(
                core_bridge_call_id=call.core_bridge_call_id,
                realtime_session_id=call.realtime_session_id,
                realtime_turn_id=call.realtime_turn_id,
                result_state=call.result_state,
                status="allowed",
                speak_allowed=True,
                spoken_text=call.spoken_summary,
                spoken_summary_source="core",
                reason=None,
                route_family=call.route_family,
                subsystem=call.subsystem,
                trust_posture=call.trust_posture,
                verification_posture=call.verification_posture,
                metadata={"realtime_core_bridge_call": call.to_dict()},
            )
        self._remember_realtime_response_gate(gate)
        self._publish(
            VoiceEventType.REALTIME_RESPONSE_GATED,
            message="Realtime spoken response gated through Core result state.",
            session_id=call.session_id,
            realtime_session_id=call.realtime_session_id,
            realtime_turn_id=call.realtime_turn_id,
            provider=self._realtime_provider_name(),
            provider_kind=self.realtime_readiness_report().realtime_provider_kind,
            model=self.config.realtime.model,
            voice=self.config.realtime.voice,
            mode=self.config.realtime.mode,
            source="realtime_speech",
            status=gate.status,
            result_state=gate.result_state,
            route_family=gate.route_family,
            subsystem=gate.subsystem,
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=True,
            audio_output_from_realtime=True,
            raw_audio_present=False,
            metadata={
                "core_bridge_call_id": call.core_bridge_call_id,
                "response_gate": gate.to_dict(),
            },
        )
        self._publish(
            VoiceEventType.REALTIME_SPOKEN_RESPONSE_ALLOWED
            if gate.status == "allowed"
            else VoiceEventType.REALTIME_SPOKEN_RESPONSE_BLOCKED,
            message="Realtime spoken response allowed."
            if gate.status == "allowed"
            else "Realtime spoken response blocked.",
            session_id=call.session_id,
            realtime_session_id=call.realtime_session_id,
            realtime_turn_id=call.realtime_turn_id,
            provider=self._realtime_provider_name(),
            provider_kind=self.realtime_readiness_report().realtime_provider_kind,
            model=self.config.realtime.model,
            voice=self.config.realtime.voice,
            mode=self.config.realtime.mode,
            source="realtime_speech",
            status=gate.status,
            result_state=gate.result_state,
            route_family=gate.route_family,
            subsystem=gate.subsystem,
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=True,
            audio_output_from_realtime=True,
            raw_audio_present=False,
            metadata={
                "core_bridge_call_id": call.core_bridge_call_id,
                "spoken_preview": self._preview_text(gate.spoken_text),
                "response_gate_id": gate.response_gate_id,
            },
        )
        return gate

    def block_realtime_direct_tool_attempt(
        self,
        tool_name: str,
        *,
        realtime_session_id: str | None = None,
        realtime_turn_id: str | None = None,
        arguments: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        active = self.get_active_realtime_session()
        resolved_session_id = (
            str(session_id or "").strip()
            or (active.session_id if active is not None else "")
            or "default"
        )
        result = {
            "status": "blocked",
            "tool_name": str(tool_name or "unknown").strip() or "unknown",
            "realtime_session_id": realtime_session_id
            or (active.realtime_session_id if active is not None else None),
            "realtime_turn_id": realtime_turn_id
            or (active.active_turn_id if active is not None else None),
            "direct_tools_allowed": False,
            "direct_action_tools_exposed": False,
            "action_executed": False,
            "core_task_cancelled": False,
            "core_result_mutated": False,
            "argument_keys": sorted((arguments or {}).keys()),
            "reason": "realtime_direct_tools_are_not_exposed",
            "raw_audio_present": False,
        }
        self._publish(
            VoiceEventType.REALTIME_DIRECT_TOOL_BLOCKED,
            message="Realtime direct tool attempt blocked.",
            session_id=resolved_session_id,
            realtime_session_id=result["realtime_session_id"],
            realtime_turn_id=result["realtime_turn_id"],
            provider=self._realtime_provider_name(),
            provider_kind=self.realtime_readiness_report().realtime_provider_kind,
            model=self.config.realtime.model,
            voice=self.config.realtime.voice,
            mode=self.config.realtime.mode,
            source="realtime_speech",
            status="blocked",
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=bool(
                self.config.realtime.mode == "speech_to_speech_core_bridge"
                and self.config.realtime.speech_to_speech_enabled
            ),
            audio_output_from_realtime=bool(
                self.config.realtime.mode == "speech_to_speech_core_bridge"
                and self.config.realtime.audio_output_from_realtime
            ),
            raw_audio_present=False,
            action_executed=False,
            core_task_cancelled=False,
            core_result_mutated=False,
            metadata=result,
        )
        return result

    async def start_wake_monitoring(
        self, *, session_id: str | None = None
    ) -> VoiceProviderOperationResult:
        del session_id
        block_reason = self._wake_block_reason()
        if block_reason is not None:
            result = VoiceProviderOperationResult(
                ok=False,
                status="blocked",
                provider_name=self._wake_provider_name(),
                error_code=block_reason,
                error_message=f"Wake monitoring blocked: {block_reason}.",
                payload=self._wake_provider_availability(),
            )
            self._publish_wake_event(
                VoiceEventType.WAKE_ERROR,
                message=result.error_message or "Wake monitoring blocked.",
                status=result.status,
                error_code=block_reason,
            )
            return result
        operation = getattr(self.wake_provider, "start_wake_monitoring", None)
        result = (
            operation()
            if callable(operation)
            else VoiceProviderOperationResult(
                ok=False,
                status="unavailable",
                provider_name=self._wake_provider_name(),
                error_code="provider_unavailable",
                error_message="Wake provider does not implement monitoring.",
            )
        )
        self.wake_monitoring_active = bool(result.ok)
        if result.ok:
            self._publish_wake_event(
                VoiceEventType.WAKE_MONITORING_STARTED,
                message="Wake monitoring started.",
                status=result.status,
            )
        else:
            self._publish_wake_event(
                VoiceEventType.WAKE_ERROR,
                message=result.error_message or "Wake monitoring failed.",
                status=result.status,
                error_code=result.error_code,
            )
        return result

    async def stop_wake_monitoring(
        self, *, session_id: str | None = None
    ) -> VoiceProviderOperationResult:
        del session_id
        operation = getattr(self.wake_provider, "stop_wake_monitoring", None)
        result = (
            operation()
            if callable(operation)
            else VoiceProviderOperationResult(
                ok=True,
                status="stopped",
                provider_name=self._wake_provider_name(),
                payload={"monitoring_active": False},
            )
        )
        self.wake_monitoring_active = False
        self._publish_wake_event(
            VoiceEventType.WAKE_MONITORING_STOPPED,
            message="Wake monitoring stopped.",
            status=result.status,
        )
        return result

    async def simulate_wake_event(
        self,
        *,
        session_id: str | None = None,
        confidence: float | None = None,
        source: str = "mock",
    ) -> VoiceWakeEvent:
        block_reason = self._wake_simulation_block_reason()
        if block_reason is not None:
            event = self._blocked_wake_event(
                reason=block_reason,
                session_id=session_id,
                confidence=confidence,
                source=source,
            )
            self._remember_wake_event(event)
            self._publish_wake_event(
                VoiceEventType.WAKE_REJECTED,
                wake_event=event,
                message=f"Wake event rejected: {block_reason}.",
                status=event.status,
                error_code=block_reason,
            )
            return event

        cooldown_active = self._wake_cooldown_active()
        if cooldown_active:
            event = self._blocked_wake_event(
                reason="cooldown_active",
                session_id=session_id,
                confidence=confidence,
                source=source,
                cooldown_active=True,
            )
            self._remember_wake_event(event)
            self._publish_wake_event(
                VoiceEventType.WAKE_REJECTED,
                wake_event=event,
                message="Wake event rejected: cooldown active.",
                status=event.status,
                error_code="cooldown_active",
            )
            return event

        operation = getattr(self.wake_provider, "simulate_wake", None)
        if not callable(operation):
            event = self._blocked_wake_event(
                reason="provider_unavailable",
                session_id=session_id,
                confidence=confidence,
                source=source,
            )
        else:
            event = operation(
                session_id=session_id,
                confidence=confidence,
                source=source,
            )

        if event.confidence < self.config.wake.confidence_threshold:
            event = replace(
                event,
                accepted=False,
                rejected_reason="low_confidence",
                false_positive_candidate=True,
                status="rejected",
            )
            self._remember_wake_event(event)
            self._publish_wake_event(
                VoiceEventType.WAKE_REJECTED,
                wake_event=event,
                message="Wake event rejected: low confidence.",
                status=event.status,
                error_code="low_confidence",
            )
            return event

        self._last_wake_event_monotonic_ms = time.monotonic() * 1000.0
        self._remember_wake_event(event)
        self._publish_wake_event(
            VoiceEventType.WAKE_DETECTED,
            wake_event=event,
            message="Mock wake event detected.",
            status=event.status,
        )
        return event

    async def record_wake_candidate(
        self,
        *,
        session_id: str | None = None,
        confidence: float | None = None,
        source: str = "local",
    ) -> VoiceWakeEvent:
        block_reason = self._wake_block_reason()
        if block_reason is not None:
            event = self._blocked_wake_event(
                reason=block_reason,
                session_id=session_id,
                confidence=confidence,
                source=source,
            )
            self._remember_wake_event(event)
            self._publish_wake_event(
                VoiceEventType.WAKE_REJECTED,
                wake_event=event,
                message=f"Wake event rejected: {block_reason}.",
                status=event.status,
                error_code=block_reason,
            )
            return event
        if not self.wake_monitoring_active:
            event = self._blocked_wake_event(
                reason="no_active_wake_monitoring",
                session_id=session_id,
                confidence=confidence,
                source=source,
            )
            self._remember_wake_event(event)
            self._publish_wake_event(
                VoiceEventType.WAKE_REJECTED,
                wake_event=event,
                message="Wake event rejected: no active wake monitoring.",
                status=event.status,
                error_code="no_active_wake_monitoring",
            )
            return event
        cooldown_active = self._wake_cooldown_active()
        if cooldown_active:
            event = self._blocked_wake_event(
                reason="cooldown_active",
                session_id=session_id,
                confidence=confidence,
                source=source,
                cooldown_active=True,
            )
            self._remember_wake_event(event)
            self._publish_wake_event(
                VoiceEventType.WAKE_REJECTED,
                wake_event=event,
                message="Wake event rejected: cooldown active.",
                status=event.status,
                error_code="cooldown_active",
            )
            return event
        operation = getattr(self.wake_provider, "simulate_wake", None)
        if not callable(operation):
            event = self._blocked_wake_event(
                reason="provider_unavailable",
                session_id=session_id,
                confidence=confidence,
                source=source,
            )
        else:
            event = operation(
                session_id=session_id,
                confidence=confidence,
                source=source,
            )
        if event.rejected_reason:
            self._remember_wake_event(event)
            self._publish_wake_event(
                VoiceEventType.WAKE_REJECTED,
                wake_event=event,
                message=f"Wake event rejected: {event.rejected_reason}.",
                status=event.status,
                error_code=event.rejected_reason,
            )
            return event
        if event.confidence < self.config.wake.confidence_threshold:
            event = replace(
                event,
                accepted=False,
                rejected_reason="low_confidence",
                false_positive_candidate=True,
                status="rejected",
            )
            self._remember_wake_event(event)
            self._publish_wake_event(
                VoiceEventType.WAKE_REJECTED,
                wake_event=event,
                message="Wake event rejected: low confidence.",
                status=event.status,
                error_code="low_confidence",
            )
            return event
        self._last_wake_event_monotonic_ms = time.monotonic() * 1000.0
        self._remember_wake_event(event)
        self._publish_wake_event(
            VoiceEventType.WAKE_DETECTED,
            wake_event=event,
            message="Local wake event detected.",
            status=event.status,
        )
        return event

    async def accept_wake_event(
        self,
        wake_event_id: str | None = None,
        *,
        session_id: str | None = None,
    ) -> VoiceWakeSession:
        event = self._resolve_wake_event(wake_event_id)
        if event is None:
            session = self._terminal_wake_session(
                status="rejected",
                wake_event_id=wake_event_id or "missing",
                session_id=session_id,
                error_code="wake_event_missing",
                error_message="No wake event is available to accept.",
            )
            self._remember_wake_session(session)
            return session
        if event.rejected_reason:
            session = self._terminal_wake_session(
                status="rejected",
                wake_event_id=event.wake_event_id,
                session_id=event.session_id or session_id,
                error_code=event.rejected_reason,
                error_message=f"Wake event was rejected: {event.rejected_reason}.",
                confidence=event.confidence,
                source=event.source,
            )
            self._remember_wake_session(session)
            return session

        accepted_event = replace(event, accepted=True, status="accepted")
        self._remember_wake_event(accepted_event)
        wake_session = VoiceWakeSession(
            wake_event_id=accepted_event.wake_event_id,
            session_id=accepted_event.session_id or session_id or "default",
            source=accepted_event.source,
            confidence=accepted_event.confidence,
            expires_at=self._wake_session_expires_at(),
            status="active",
            mode_after_wake="ghost",
            metadata={
                "wake_provider": accepted_event.provider,
                "wake_provider_kind": accepted_event.provider_kind,
                "voice10_foundation_only": True,
            },
        )
        self._remember_wake_session(wake_session)
        self._publish_wake_event(
            VoiceEventType.WAKE_SESSION_STARTED,
            wake_event=accepted_event,
            wake_session=wake_session,
            message="Wake session started.",
            status=wake_session.status,
        )
        self._show_wake_ghost_for_session(wake_session, reason="wake_accepted")
        return wake_session

    async def reject_wake_event(
        self,
        wake_event_id: str | None = None,
        *,
        reason: str = "false_positive",
    ) -> VoiceWakeEvent:
        event = self._resolve_wake_event(wake_event_id)
        if event is None:
            event = self._blocked_wake_event(reason="wake_event_missing")
        rejected = replace(
            event,
            accepted=False,
            rejected_reason=str(reason or "rejected").strip() or "rejected",
            false_positive_candidate=True,
            status="rejected",
        )
        self._remember_wake_event(rejected)
        self._publish_wake_event(
            VoiceEventType.WAKE_REJECTED,
            wake_event=rejected,
            message=f"Wake event rejected: {rejected.rejected_reason}.",
            status=rejected.status,
            error_code=rejected.rejected_reason,
        )
        return rejected

    async def expire_wake_session(
        self, wake_session_id: str | None = None
    ) -> VoiceWakeSession:
        session = self._resolve_wake_session(wake_session_id)
        if session is None:
            session = self._terminal_wake_session(
                status="expired",
                wake_event_id=self.last_wake_event.wake_event_id
                if self.last_wake_event is not None
                else "missing",
                error_code="wake_session_missing",
                error_message="No wake session is available to expire.",
            )
        else:
            session = replace(
                session,
                status="expired",
                error_code=None,
                error_message=None,
            )
        self._remember_wake_session(session)
        self._expire_wake_ghost_for_session(session.wake_session_id)
        self._publish_wake_event(
            VoiceEventType.WAKE_SESSION_EXPIRED,
            wake_session=session,
            message="Wake session expired.",
            status=session.status,
            error_code=session.error_code,
        )
        return session

    async def cancel_wake_session(
        self,
        wake_session_id: str | None = None,
        *,
        reason: str = "user_cancelled",
    ) -> VoiceWakeSession:
        session = self._resolve_wake_session(wake_session_id)
        if session is None:
            session = self._terminal_wake_session(
                status="cancelled",
                wake_event_id=self.last_wake_event.wake_event_id
                if self.last_wake_event is not None
                else "missing",
                error_code="wake_session_missing",
                error_message="No wake session is available to cancel.",
            )
        else:
            reason = str(reason or "user_cancelled").strip() or "user_cancelled"
            session = replace(
                session,
                status="cancelled",
                error_code=reason,
                error_message=f"Wake session cancelled: {reason}.",
            )
        self._remember_wake_session(session)
        self._cancel_wake_ghost_for_session(
            session.wake_session_id,
            reason=reason,
        )
        self._publish_wake_event(
            VoiceEventType.WAKE_SESSION_CANCELLED,
            wake_session=session,
            message="Wake session cancelled.",
            status=session.status,
            error_code=session.error_code,
        )
        return session

    def get_active_wake_session(self) -> VoiceWakeSession | None:
        active = self.active_wake_session
        if (
            active is not None
            and active.expires_at
            and self._is_expired(active.expires_at)
        ):
            self.active_wake_session = replace(active, status="expired")
            self.last_wake_session = self.active_wake_session
            self.wake_sessions[self.active_wake_session.wake_session_id] = (
                self.active_wake_session
            )
            return None
        return self.active_wake_session

    async def create_wake_ghost_request(
        self,
        wake_session_id: str | None = None,
    ) -> VoiceWakeGhostRequest:
        session = self._resolve_wake_session(wake_session_id)
        if session is None or session.status != "active":
            return self._terminal_wake_ghost_request(
                status="blocked",
                wake_session_id=wake_session_id or "missing",
                reason="wake_session_not_active",
            )
        return self._show_wake_ghost_for_session(
            session,
            reason="wake_accepted",
        )

    async def show_wake_ghost(
        self,
        wake_session_id: str | None = None,
    ) -> VoiceWakeGhostRequest:
        return await self.create_wake_ghost_request(wake_session_id)

    async def expire_wake_ghost(
        self,
        wake_session_id: str | None = None,
    ) -> VoiceWakeGhostRequest:
        return self._expire_wake_ghost_for_session(wake_session_id)

    async def cancel_wake_ghost(
        self,
        wake_session_id: str | None = None,
        *,
        reason: str = "operator_dismissed",
    ) -> VoiceWakeGhostRequest:
        ghost = self._cancel_wake_ghost_for_session(wake_session_id, reason=reason)
        session = self._resolve_wake_session(wake_session_id)
        if session is not None and session.status == "active":
            cancelled_session = replace(
                session,
                status="cancelled",
                error_code=reason,
                error_message=f"Wake session cancelled: {reason}.",
            )
            self._remember_wake_session(cancelled_session)
            self._publish_wake_event(
                VoiceEventType.WAKE_SESSION_CANCELLED,
                wake_session=cancelled_session,
                message="Wake session cancelled.",
                status=cancelled_session.status,
                error_code=cancelled_session.error_code,
            )
        return ghost

    def get_active_wake_ghost_request(self) -> VoiceWakeGhostRequest | None:
        active = self.active_wake_ghost_request
        if (
            active is not None
            and active.expires_at
            and self._is_expired(active.expires_at)
        ):
            self._expire_wake_ghost_for_session(active.wake_session_id)
            return None
        return self.active_wake_ghost_request

    async def open_post_wake_listen_window(
        self,
        wake_session_id: str,
        *,
        auto_start_capture: bool | None = None,
    ) -> VoicePostWakeListenWindow:
        config = self.config.post_wake
        session = self._resolve_wake_session(wake_session_id)
        if session is None:
            return self._remember_post_wake_listen_window(
                self._post_wake_listen_failure(
                    wake_session_id=wake_session_id,
                    error_code="wake_session_missing",
                    error_message="Post-wake listen requires an accepted wake session.",
                )
            )
        if not config.enabled:
            return self._remember_post_wake_listen_window(
                self._post_wake_listen_failure(
                    wake_session_id=session.wake_session_id,
                    wake_event_id=session.wake_event_id,
                    session_id=session.session_id,
                    error_code="post_wake_listen_disabled",
                    error_message="Post-wake listen windows are disabled.",
                )
            )
        if not config.allow_dev_post_wake:
            return self._remember_post_wake_listen_window(
                self._post_wake_listen_failure(
                    wake_session_id=session.wake_session_id,
                    wake_event_id=session.wake_event_id,
                    session_id=session.session_id,
                    error_code="dev_post_wake_not_allowed",
                    error_message="Post-wake listen requires explicit dev/operator allowance.",
                )
            )
        if session.status != "active":
            return self._remember_post_wake_listen_window(
                self._post_wake_listen_failure(
                    wake_session_id=session.wake_session_id,
                    wake_event_id=session.wake_event_id,
                    session_id=session.session_id,
                    error_code=f"wake_session_{session.status}",
                    error_message="Post-wake listen requires an active wake session.",
                )
            )
        active = self.get_active_post_wake_listen_window()
        if active is not None and active.wake_session_id == session.wake_session_id:
            return active

        ghost = (
            self.get_active_wake_ghost_request()
            or await self.create_wake_ghost_request(session.wake_session_id)
        )
        if ghost is None or ghost.status not in {"requested", "shown"}:
            return self._remember_post_wake_listen_window(
                self._post_wake_listen_failure(
                    wake_session_id=session.wake_session_id,
                    wake_event_id=session.wake_event_id,
                    session_id=session.session_id,
                    error_code="wake_ghost_unavailable",
                    error_message="Post-wake listen requires wake Ghost presentation.",
                )
            )

        started_at = self._now()
        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(milliseconds=config.listen_window_ms)
        ).isoformat()
        window = VoicePostWakeListenWindow(
            wake_event_id=session.wake_event_id,
            wake_session_id=session.wake_session_id,
            wake_ghost_request_id=ghost.wake_ghost_request_id,
            session_id=session.session_id,
            status="active",
            started_at=started_at,
            expires_at=expires_at,
            listen_window_ms=config.listen_window_ms,
            max_utterance_ms=config.max_utterance_ms,
            metadata={
                "bounded": True,
                "one_utterance": True,
                "continuous_listening": False,
                "realtime_used": False,
                "listen_window_does_not_route_core": True,
            },
        )
        window = self._remember_post_wake_listen_window(window)
        self._publish_post_wake_listen_event(
            VoiceEventType.POST_WAKE_LISTEN_OPENED,
            window,
            "Post-wake listen window opened.",
            status=window.status,
        )
        self._publish_post_wake_listen_event(
            VoiceEventType.POST_WAKE_LISTEN_STARTED,
            window,
            "Post-wake listen window started.",
            status=window.status,
        )

        should_start = (
            config.auto_start_capture if auto_start_capture is None else auto_start_capture
        )
        if should_start:
            await self.start_post_wake_capture(window.listen_window_id)
            return self.last_post_wake_listen_window or window
        return window

    async def start_post_wake_capture(
        self, listen_window_id: str
    ) -> VoiceCaptureSession | VoiceCaptureResult:
        window = self._post_wake_listen_window_for_id(listen_window_id)
        if window is None:
            return self._post_wake_capture_failure(
                listen_window_id=listen_window_id,
                error_code="listen_window_missing",
                error_message="Post-wake listen window was not found.",
            )
        if window.expires_at and self._is_expired(window.expires_at):
            expired = self._expire_post_wake_listen_window_sync(
                window.listen_window_id,
                reason="listen_window_expired",
            )
            return self._post_wake_capture_failure(
                listen_window_id=expired.listen_window_id,
                wake_session_id=expired.wake_session_id,
                wake_event_id=expired.wake_event_id,
                error_code="listen_window_expired",
                error_message="Post-wake listen window expired before capture.",
            )
        if window.status not in {"active", "pending"}:
            return self._post_wake_capture_failure(
                listen_window_id=window.listen_window_id,
                wake_session_id=window.wake_session_id,
                wake_event_id=window.wake_event_id,
                error_code=f"listen_window_{window.status}",
                error_message="Post-wake capture requires an active listen window.",
            )

        capture_start = await self.start_push_to_talk_capture(
            session_id=window.session_id,
            metadata={
                "listen_window_id": window.listen_window_id,
                "post_wake_listen": {
                    "listen_window_id": window.listen_window_id,
                    "wake_event_id": window.wake_event_id,
                    "wake_session_id": window.wake_session_id,
                    "wake_ghost_request_id": window.wake_ghost_request_id,
                    "bounded": True,
                    "one_utterance": True,
                    "continuous_listening": False,
                    "realtime_used": False,
                    "listen_window_does_not_route_core": True,
                },
            },
        )
        if isinstance(capture_start, VoiceCaptureResult):
            result = self._with_post_wake_capture_result_metadata(
                capture_start, window
            )
            failed = replace(
                window,
                status="failed",
                capture_id=result.capture_id,
                error_code=result.error_code,
                error_message=result.error_message,
                stop_reason=result.status,
            )
            self._remember_post_wake_listen_window(failed)
            self._publish_post_wake_listen_event(
                VoiceEventType.POST_WAKE_LISTEN_FAILED,
                failed,
                "Post-wake listen capture failed to start.",
                status=failed.status,
                capture_id=result.capture_id,
                error_code=result.error_code,
            )
            return self._remember_capture_result(result)

        session = self._with_post_wake_capture_session_metadata(capture_start, window)
        self.last_capture_session = session
        active = replace(
            window,
            status="capturing",
            capture_id=session.capture_id,
            capture_started=True,
        )
        self._remember_post_wake_listen_window(active)
        self._publish_post_wake_listen_event(
            VoiceEventType.POST_WAKE_LISTEN_CAPTURE_STARTED,
            active,
            "Post-wake listen capture started.",
            status=active.status,
            capture_id=session.capture_id,
        )
        return session

    async def complete_post_wake_capture(
        self,
        listen_window_id: str,
        capture_result: VoiceCaptureResult | None = None,
    ) -> VoicePostWakeListenWindow:
        result = capture_result or self.last_capture_result
        return self._complete_post_wake_capture_sync(listen_window_id, result)

    async def submit_post_wake_listen_window(
        self,
        listen_window_id: str,
        capture_result: VoiceCaptureResult | None = None,
        *,
        mode: str = "ghost",
    ) -> VoiceTurnResult:
        window = self._post_wake_listen_window_for_id(listen_window_id)
        result = capture_result or self.last_capture_result
        if window is None or result is None or not result.ok:
            return self._remember_audio_turn_result(
                VoiceTurnResult(
                    ok=False,
                    error_code="listen_window_not_captured",
                    error_message="Post-wake listen window has no completed capture.",
                    voice_state_before=self.state_controller.snapshot().to_dict(),
                    voice_state_after=self.state_controller.snapshot().to_dict(),
                )
            )
        turn_result = await self.submit_captured_audio_turn(
            result,
            mode=mode,
            session_id=window.session_id,
            metadata={
                "post_wake_listen": {
                    "listen_window_id": window.listen_window_id,
                    "wake_event_id": window.wake_event_id,
                    "wake_session_id": window.wake_session_id,
                    "wake_ghost_request_id": window.wake_ghost_request_id,
                }
            },
        )
        self._mark_post_wake_listen_submitted(window.listen_window_id, turn_result)
        return turn_result

    async def cancel_post_wake_listen_window(
        self,
        listen_window_id: str,
        *,
        reason: str = "user_cancelled",
    ) -> VoicePostWakeListenWindow:
        window = self._post_wake_listen_window_for_id(listen_window_id)
        if window is None:
            return self._remember_post_wake_listen_window(
                self._post_wake_listen_failure(
                    wake_session_id=None,
                    error_code="listen_window_missing",
                    error_message="Post-wake listen window was not found.",
                    stop_reason=reason,
                )
            )
        if window.status == "capturing" and window.capture_id:
            await self.cancel_capture(window.capture_id, reason=reason)
            window = self._post_wake_listen_window_for_id(listen_window_id) or window
        cancelled = replace(
            window,
            status="cancelled",
            stop_reason=reason,
            capture_started=window.capture_started,
            stt_started=False,
            core_routed=False,
        )
        self._remember_post_wake_listen_window(cancelled)
        self._publish_post_wake_listen_event(
            VoiceEventType.POST_WAKE_LISTEN_CANCELLED,
            cancelled,
            "Post-wake listen window cancelled.",
            status=cancelled.status,
            capture_id=cancelled.capture_id,
        )
        return cancelled

    async def expire_post_wake_listen_window(
        self,
        listen_window_id: str,
        *,
        reason: str = "listen_window_expired",
    ) -> VoicePostWakeListenWindow:
        window = self._post_wake_listen_window_for_id(listen_window_id)
        if window is not None and window.status == "capturing" and window.capture_id:
            await self.cancel_capture(window.capture_id, reason=reason)
        return self._expire_post_wake_listen_window_sync(listen_window_id, reason=reason)

    def get_active_post_wake_listen_window(self) -> VoicePostWakeListenWindow | None:
        active = self.active_post_wake_listen_window
        if active is not None and active.expires_at and self._is_expired(
            active.expires_at
        ):
            self._expire_post_wake_listen_window_sync(
                active.listen_window_id,
                reason="listen_window_expired",
            )
            return None
        return self.active_post_wake_listen_window

    async def run_wake_supervised_voice_loop(
        self,
        wake_session_id: str | None = None,
        *,
        mode: str = "ghost",
        synthesize_response: bool = False,
        play_response: bool = False,
        finalize_with_vad: bool = False,
    ) -> VoiceWakeSupervisedLoopResult:
        loop_id = f"voice-wake-loop-{uuid4().hex[:12]}"
        listen_window_id: str | None = None
        created_at = self._now()
        self.active_wake_supervised_loop_id = loop_id
        self.active_wake_supervised_loop_stage = "wake"
        stage_results: dict[str, dict[str, Any]] = {
            "wake": {"status": "skipped"},
            "ghost": {"status": "skipped"},
            "listen": {"status": "skipped"},
            "capture": {"status": "skipped"},
            "vad": {"status": "skipped"},
            "stt": {"status": "skipped"},
            "core": {"status": "skipped"},
            "spoken_response": {"status": "skipped"},
            "tts": {"status": "skipped"},
            "playback": {"status": "skipped"},
        }
        session = self._resolve_wake_session(wake_session_id)
        ghost = self.get_active_wake_ghost_request() or self.last_wake_ghost_request
        capture_result: VoiceCaptureResult | None = None
        turn_result: VoiceTurnResult | None = None
        synthesis_result: VoiceSpeechSynthesisResult | None = None
        playback_result: VoicePlaybackResult | None = None
        vad_status: str | None = None
        listen_status = "skipped"

        async def finish(
            *,
            final_status: str,
            ok: bool,
            failed_stage: str | None = None,
            stopped_stage: str | None = None,
            blocked_stage: str | None = None,
            cancelled_stage: str | None = None,
            last_successful_stage: str | None = None,
            current_blocker: str | None = None,
            error_code: str | None = None,
            error_message: str | None = None,
            stand_down: bool = True,
        ) -> VoiceWakeSupervisedLoopResult:
            nonlocal ghost
            core_result = turn_result.core_result if turn_result is not None else None
            transcription = (
                turn_result.transcription_result if turn_result is not None else None
            )
            turn = turn_result.turn if turn_result is not None else None
            spoken = turn_result.spoken_response if turn_result is not None else None
            result = VoiceWakeSupervisedLoopResult(
                loop_id=loop_id,
                session_id=session.session_id if session is not None else "default",
                ok=ok,
                final_status=final_status,
                wake_event_id=session.wake_event_id if session is not None else None,
                wake_session_id=session.wake_session_id
                if session is not None
                else None,
                wake_ghost_request_id=ghost.wake_ghost_request_id
                if ghost is not None
                else None,
                listen_window_id=listen_window_id
                if listen_status != "skipped"
                else None,
                capture_id=capture_result.capture_id
                if capture_result is not None
                else None,
                audio_input_id=capture_result.audio_input.input_id
                if capture_result is not None and capture_result.audio_input is not None
                else None,
                transcription_id=transcription.transcription_id
                if transcription is not None
                else None,
                voice_turn_id=turn.turn_id if turn is not None else None,
                core_request_id=turn_result.core_request.request_id
                if turn_result is not None and turn_result.core_request is not None
                else None,
                speech_request_id=synthesis_result.speech_request_id
                if synthesis_result is not None
                else None,
                synthesis_id=synthesis_result.synthesis_id
                if synthesis_result is not None
                else None,
                playback_id=playback_result.playback_id
                if playback_result is not None
                else None,
                wake_status=session.status if session is not None else None,
                ghost_status=ghost.status if ghost is not None else None,
                listen_status=listen_status,
                capture_status=capture_result.status
                if capture_result is not None
                else stage_results["capture"]["status"],
                vad_status=vad_status,
                transcription_status=transcription.status
                if transcription is not None
                else stage_results["stt"]["status"],
                core_result_state=core_result.result_state
                if core_result is not None
                else None,
                spoken_response_status="prepared"
                if spoken is not None
                else stage_results["spoken_response"]["status"],
                synthesis_status=synthesis_result.status
                if synthesis_result is not None
                else stage_results["tts"]["status"],
                playback_status=playback_result.status
                if playback_result is not None
                else stage_results["playback"]["status"],
                failed_stage=failed_stage,
                stopped_stage=stopped_stage,
                blocked_stage=blocked_stage,
                cancelled_stage=cancelled_stage,
                last_successful_stage=last_successful_stage,
                current_blocker=current_blocker,
                route_family=core_result.route_family
                if core_result is not None
                else None,
                subsystem=core_result.subsystem if core_result is not None else None,
                trust_posture=core_result.trust_posture
                if core_result is not None
                else None,
                verification_posture=core_result.verification_posture
                if core_result is not None
                else None,
                transcript_preview=self._preview_text(
                    transcription.transcript if transcription is not None else "",
                    limit=96,
                ),
                spoken_preview=self._preview_text(
                    spoken.spoken_text if spoken is not None else "",
                    limit=96,
                ),
                created_at=created_at,
                completed_at=self._now(),
                error_code=error_code,
                error_message=error_message,
                stage_results=stage_results,
            )
            self.last_wake_supervised_loop_result = result
            event_type = (
                VoiceEventType.WAKE_SUPERVISED_LOOP_COMPLETED
                if ok
                else VoiceEventType.WAKE_SUPERVISED_LOOP_BLOCKED
                if blocked_stage is not None
                else VoiceEventType.WAKE_SUPERVISED_LOOP_FAILED
            )
            self._publish(
                event_type,
                message=f"Wake supervised voice loop {final_status}.",
                session_id=result.session_id,
                wake_event_id=result.wake_event_id,
                wake_session_id=result.wake_session_id,
                wake_ghost_request_id=result.wake_ghost_request_id,
                listen_window_id=result.listen_window_id,
                capture_id=result.capture_id,
                input_id=result.audio_input_id,
                transcription_id=result.transcription_id,
                speech_request_id=result.speech_request_id,
                synthesis_id=result.synthesis_id,
                playback_id=result.playback_id,
                status=final_status,
                result_state=result.core_result_state,
                route_family=result.route_family,
                subsystem=result.subsystem,
                error_code=error_code,
                metadata={
                    "loop_id": loop_id,
                    "wake_supervised_loop": result.to_dict(),
                    "one_bounded_request": True,
                    "continuous_listening": False,
                    "realtime_used": False,
                },
            )
            if (
                stand_down
                and session is not None
                and session.status == "active"
                and self.active_wake_session is not None
                and self.active_wake_session.wake_session_id == session.wake_session_id
            ):
                await self.expire_wake_session(session.wake_session_id)
            return result

        try:
            self._publish(
                VoiceEventType.WAKE_SUPERVISED_LOOP_STARTED,
                message="Wake supervised voice loop started.",
                session_id=session.session_id if session is not None else None,
                wake_event_id=session.wake_event_id if session is not None else None,
                wake_session_id=session.wake_session_id
                if session is not None
                else None,
                status="started",
                metadata={
                    "loop_id": loop_id,
                    "one_bounded_request": True,
                    "continuous_listening": False,
                    "realtime_used": False,
                },
            )
            if session is None:
                stage_results["wake"] = {"status": "missing"}
                return await finish(
                    final_status="wake_expired",
                    ok=False,
                    failed_stage="wake",
                    stopped_stage="wake",
                    current_blocker="wake_session_missing",
                    error_code="wake_session_missing",
                    stand_down=False,
                )
            stage_results["wake"] = {
                "status": session.status,
                "wake_event_id": session.wake_event_id,
                "wake_session_id": session.wake_session_id,
            }
            if session.status == "rejected":
                return await finish(
                    final_status="wake_rejected",
                    ok=False,
                    blocked_stage="wake",
                    stopped_stage="wake",
                    current_blocker=session.error_code or "wake_rejected",
                    error_code=session.error_code or "wake_rejected",
                    stand_down=False,
                )
            if session.status in {"expired", "cancelled"}:
                return await finish(
                    final_status="wake_expired"
                    if session.status == "expired"
                    else "capture_cancelled",
                    ok=False,
                    cancelled_stage="wake" if session.status == "cancelled" else None,
                    stopped_stage="wake",
                    current_blocker=session.error_code or f"wake_{session.status}",
                    error_code=session.error_code or f"wake_{session.status}",
                    stand_down=False,
                )
            if session.status != "active":
                return await finish(
                    final_status="wake_expired",
                    ok=False,
                    failed_stage="wake",
                    stopped_stage="wake",
                    current_blocker="wake_session_not_active",
                    error_code="wake_session_not_active",
                    stand_down=False,
                )

            ghost = (
                self.get_active_wake_ghost_request()
                or await self.create_wake_ghost_request(session.wake_session_id)
            )
            stage_results["ghost"] = {
                "status": ghost.status if ghost is not None else "missing",
                "wake_ghost_request_id": ghost.wake_ghost_request_id
                if ghost is not None
                else None,
            }
            if ghost is None or ghost.status not in {"shown", "requested"}:
                return await finish(
                    final_status="failed",
                    ok=False,
                    failed_stage="ghost",
                    stopped_stage="ghost",
                    current_blocker="wake_ghost_unavailable",
                    error_code="wake_ghost_unavailable",
                )

            self.active_wake_supervised_loop_stage = "listening"
            listen_window = await self.open_post_wake_listen_window(
                session.wake_session_id,
                auto_start_capture=False,
            )
            listen_window_id = listen_window.listen_window_id
            listen_status = listen_window.status
            stage_results["listen"] = {
                "status": listen_status,
                "listen_window_id": listen_window_id,
                "bounded": True,
                "error_code": listen_window.error_code,
            }
            if listen_window.status not in {"active", "capturing"}:
                return await finish(
                    final_status="listen_timeout"
                    if listen_window.status == "expired"
                    else "failed",
                    ok=False,
                    failed_stage="listen",
                    stopped_stage="listen",
                    last_successful_stage="ghost",
                    current_blocker=listen_window.error_code
                    or f"listen_window_{listen_window.status}",
                    error_code=listen_window.error_code
                    or f"listen_window_{listen_window.status}",
                    error_message=listen_window.error_message,
                )

            capture_start = await self.start_post_wake_capture(listen_window_id)
            if isinstance(capture_start, VoiceCaptureResult):
                capture_result = capture_start
                listen_status = "failed"
                stage_results["listen"]["status"] = listen_status
                stage_results["capture"] = {
                    "status": capture_result.status,
                    "error_code": capture_result.error_code,
                }
                return await finish(
                    final_status="capture_failed",
                    ok=False,
                    failed_stage="capture",
                    stopped_stage="capture",
                    current_blocker=capture_result.error_code,
                    error_code=capture_result.error_code,
                    error_message=capture_result.error_message,
                )

            capture_session = capture_start
            stage_results["capture"] = {
                "status": capture_session.status,
                "capture_id": capture_session.capture_id,
            }
            self.active_wake_supervised_loop_stage = "capturing"
            if finalize_with_vad and self.config.vad.enabled:
                started = await self.simulate_speech_started(
                    capture_id=capture_session.capture_id,
                    listen_window_id=listen_window_id,
                )
                stopped = await self.simulate_speech_stopped(
                    capture_id=capture_session.capture_id,
                    listen_window_id=listen_window_id,
                )
                vad_status = stopped.status
                stage_results["vad"] = {
                    "status": stopped.status,
                    "vad_session_id": stopped.vad_session_id,
                    "speech_started_event_id": started.activity_event_id,
                    "speech_stopped_event_id": stopped.activity_event_id,
                    "semantic_completion_claimed": False,
                    "command_authority": False,
                }
                capture_result = self.last_capture_result
            else:
                capture_result = await self.stop_push_to_talk_capture(
                    capture_session.capture_id,
                    reason="post_wake_bounded_stop",
                )
            if capture_result is None:
                capture_result = VoiceCaptureResult(
                    ok=False,
                    capture_request_id=capture_session.capture_request_id,
                    capture_id=capture_session.capture_id,
                    status="failed",
                    provider=capture_session.provider,
                    device=capture_session.device,
                    stopped_at=self._now(),
                    error_code="capture_result_missing",
                    error_message="Post-wake capture did not produce a terminal result.",
                )
            listen_status = (
                "captured" if capture_result.status == "completed" else "failed"
            )
            completed_window = self._post_wake_listen_window_for_id(listen_window_id)
            if completed_window is None or completed_window.status not in {
                "captured",
                "cancelled",
                "timeout",
                "failed",
            }:
                completed_window = self._complete_post_wake_capture_sync(
                    listen_window_id,
                    capture_result,
                )
            listen_status = completed_window.status
            stage_results["listen"]["status"] = listen_status
            stage_results["capture"] = {
                "status": capture_result.status,
                "capture_id": capture_result.capture_id,
                "audio_input_id": capture_result.audio_input.input_id
                if capture_result.audio_input is not None
                else None,
                "error_code": capture_result.error_code,
            }
            if not capture_result.ok:
                final_status = (
                    "capture_cancelled"
                    if capture_result.status == "cancelled"
                    else "listen_timeout"
                    if capture_result.status == "timeout"
                    else "capture_failed"
                )
                return await finish(
                    final_status=final_status,
                    ok=False,
                    failed_stage="capture"
                    if final_status == "capture_failed"
                    else None,
                    cancelled_stage="capture"
                    if final_status == "capture_cancelled"
                    else None,
                    stopped_stage="capture",
                    last_successful_stage="listen",
                    current_blocker=capture_result.error_code,
                    error_code=capture_result.error_code,
                    error_message=capture_result.error_message,
                )

            self.active_wake_supervised_loop_stage = "transcribing"
            turn_result = await self.submit_captured_audio_turn(
                capture_result,
                mode=mode,
                session_id=session.session_id,
                metadata={
                    "wake_supervised_loop": {
                        "loop_id": loop_id,
                        "wake_event_id": session.wake_event_id,
                        "wake_session_id": session.wake_session_id,
                        "wake_ghost_request_id": ghost.wake_ghost_request_id,
                        "listen_window_id": listen_window_id,
                    }
                },
            )
            submitted_window = self._mark_post_wake_listen_submitted(
                listen_window_id,
                turn_result,
            )
            if submitted_window is not None:
                listen_status = submitted_window.status
                stage_results["listen"]["status"] = listen_status
            transcription = turn_result.transcription_result
            stage_results["stt"] = {
                "status": transcription.status
                if transcription is not None
                else "skipped",
                "input_id": transcription.input_id
                if transcription is not None
                else None,
                "transcription_id": transcription.transcription_id
                if transcription is not None
                else None,
                "error_code": transcription.error_code
                if transcription is not None
                else turn_result.error_code,
            }
            core_result = turn_result.core_result
            stage_results["core"] = {
                "status": "completed" if core_result is not None else "skipped",
                "result_state": core_result.result_state
                if core_result is not None
                else None,
                "error_code": core_result.error_code
                if core_result is not None
                else None,
            }
            stage_results["spoken_response"] = {
                "status": "prepared"
                if turn_result.spoken_response is not None
                else "skipped",
                "should_speak": turn_result.spoken_response.should_speak
                if turn_result.spoken_response is not None
                else False,
            }
            if not turn_result.ok and core_result is None:
                error = turn_result.error_code or "transcription_failed"
                final_status = (
                    "empty_transcript"
                    if error == "empty_transcript"
                    else "transcription_failed"
                )
                return await finish(
                    final_status=final_status,
                    ok=False,
                    failed_stage="stt",
                    stopped_stage="stt",
                    last_successful_stage="capture",
                    current_blocker=error,
                    error_code=error,
                    error_message=turn_result.error_message,
                )

            if core_result is None:
                return await finish(
                    final_status="core_failed",
                    ok=False,
                    failed_stage="core",
                    stopped_stage="core",
                    last_successful_stage="stt",
                    current_blocker=turn_result.error_code or "core_missing",
                    error_code=turn_result.error_code or "core_missing",
                    error_message=turn_result.error_message,
                )

            core_final = self._wake_loop_final_status_for_core(core_result.result_state)
            if core_result.result_state in {"blocked", "failed", "unavailable"}:
                return await finish(
                    final_status=core_final,
                    ok=core_result.result_state != "failed",
                    failed_stage="core"
                    if core_result.result_state != "blocked"
                    else None,
                    blocked_stage="core"
                    if core_result.result_state == "blocked"
                    else None,
                    stopped_stage="core",
                    last_successful_stage="stt",
                    current_blocker=core_result.error_code or core_result.result_state,
                    error_code=core_result.error_code,
                )

            final_status = core_final
            last_successful_stage = "core"
            if synthesize_response or play_response:
                self.active_wake_supervised_loop_stage = "synthesizing"
                synthesis_result = await self.synthesize_turn_response(
                    turn_result,
                    session_id=session.session_id,
                    metadata={"wake_supervised_loop": {"loop_id": loop_id}},
                )
                stage_results["tts"] = {
                    "status": synthesis_result.status,
                    "speech_request_id": synthesis_result.speech_request_id,
                    "synthesis_id": synthesis_result.synthesis_id,
                    "error_code": synthesis_result.error_code,
                }
                if not synthesis_result.ok:
                    if synthesis_result.error_code in {
                        "spoken_output_muted",
                        "current_response_suppressed",
                    }:
                        return await finish(
                            final_status="suppressed_or_muted",
                            ok=True,
                            stopped_stage="tts",
                            last_successful_stage="core",
                            current_blocker=synthesis_result.error_code,
                            error_code=synthesis_result.error_code,
                        )
                    return await finish(
                        final_status="tts_disabled"
                        if synthesis_result.status == "blocked"
                        else "tts_failed",
                        ok=True,
                        failed_stage="tts"
                        if synthesis_result.status == "failed"
                        else None,
                        blocked_stage="tts"
                        if synthesis_result.status == "blocked"
                        else None,
                        stopped_stage="tts",
                        last_successful_stage="core",
                        current_blocker=synthesis_result.error_code,
                        error_code=synthesis_result.error_code,
                        error_message=synthesis_result.error_message,
                    )
                last_successful_stage = "tts"
                if final_status == "completed" and not play_response:
                    final_status = "response_ready"

            if play_response:
                self.active_wake_supervised_loop_stage = "playing"
                if synthesis_result is None:
                    synthesis_result = await self.synthesize_turn_response(
                        turn_result,
                        session_id=session.session_id,
                        metadata={"wake_supervised_loop": {"loop_id": loop_id}},
                    )
                    stage_results["tts"] = {
                        "status": synthesis_result.status,
                        "speech_request_id": synthesis_result.speech_request_id,
                        "synthesis_id": synthesis_result.synthesis_id,
                        "error_code": synthesis_result.error_code,
                    }
                playback_result = await self.play_speech_output(
                    synthesis_result,
                    session_id=session.session_id,
                    turn_id=turn_result.turn.turn_id
                    if turn_result.turn is not None
                    else None,
                    metadata={"wake_supervised_loop": {"loop_id": loop_id}},
                )
                stage_results["playback"] = {
                    "status": playback_result.status,
                    "playback_id": playback_result.playback_id,
                    "synthesis_id": playback_result.synthesis_id,
                    "error_code": playback_result.error_code,
                    "user_heard_claimed": False,
                }
                if not playback_result.ok:
                    return await finish(
                        final_status="playback_unavailable"
                        if playback_result.status in {"blocked", "unavailable"}
                        else "playback_failed",
                        ok=True,
                        failed_stage="playback"
                        if playback_result.status == "failed"
                        else None,
                        blocked_stage="playback"
                        if playback_result.status in {"blocked", "unavailable"}
                        else None,
                        stopped_stage="playback",
                        last_successful_stage="tts",
                        current_blocker=playback_result.error_code,
                        error_code=playback_result.error_code,
                        error_message=playback_result.error_message,
                    )
                last_successful_stage = "playback"
                if playback_result.status == "stopped":
                    final_status = "playback_stopped"
                elif final_status == "response_ready":
                    final_status = "completed"

            return await finish(
                final_status=final_status,
                ok=True,
                last_successful_stage=last_successful_stage,
            )
        finally:
            self.active_wake_supervised_loop_id = None
            self.active_wake_supervised_loop_stage = None

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
        active_session_id = str(session_id or "default").strip() or "default"
        interaction_mode = self._normalize_interaction_mode(mode)
        turn_metadata = dict(metadata or {})
        if manual_dev_override:
            turn_metadata["manual_dev_override"] = True

        confirmation_result = await self._maybe_handle_spoken_confirmation_turn(
            normalized_transcript,
            session_id=active_session_id,
            mode=interaction_mode,
            source="manual_voice",
            metadata=turn_metadata,
        )
        if confirmation_result is not None:
            return self._remember_turn_result(confirmation_result)

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
        if self.config.playback.prewarm_enabled and self.config.spoken_responses_enabled:
            self.prewarm_voice_output(
                session_id=active_session_id,
                turn_id=turn.turn_id,
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
            core_result = await submit_voice_core_request(
                self.core_bridge, core_request
            )
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
            metadata={
                "should_speak": spoken_response.should_speak,
                "text_only_preview": True,
            },
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
            message="Manual voice turn completed."
            if ok
            else "Manual voice turn failed.",
            turn=turn,
            state=self.state_controller.snapshot().state.value,
            result_state=core_result.result_state,
            route_family=core_result.route_family,
            subsystem=core_result.subsystem,
            error_code=core_result.error_code,
        )
        return self._remember_turn_result(result)

    async def start_push_to_talk_capture(
        self,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceCaptureSession | VoiceCaptureResult:
        request = self._build_capture_request(session_id=session_id, metadata=metadata)
        block_reason = self._capture_request_block_reason(request)
        if block_reason is not None:
            blocked_request = replace(
                request, allowed_to_capture=False, blocked_reason=block_reason
            )
            status = (
                "unavailable"
                if block_reason
                in {"provider_unavailable", "local_capture_not_implemented"}
                else "blocked"
            )
            result = self._blocked_capture_result(
                blocked_request,
                status=status,
                error_code=block_reason,
                error_message=f"Push-to-talk capture blocked: {block_reason}.",
            )
            self._publish_capture_blocked(result, blocked_request)
            return self._remember_capture_result(result)

        allowed_request = replace(request, allowed_to_capture=True, blocked_reason=None)
        request_listen_window_id = self._metadata_listen_window_id(
            allowed_request.metadata
        )
        self.last_capture_request = allowed_request
        self._publish(
            VoiceEventType.CAPTURE_REQUEST_CREATED,
            message="Push-to-talk capture request created.",
            session_id=allowed_request.session_id,
            turn_id=allowed_request.turn_id,
            capture_request_id=allowed_request.capture_request_id,
            listen_window_id=request_listen_window_id,
            provider=allowed_request.provider,
            device=allowed_request.device,
            mode=allowed_request.source,
            source="push_to_talk",
            status="created",
            metadata={"capture_request": allowed_request.to_metadata()},
        )

        session_or_result = await self._start_capture_with_provider(allowed_request)
        if isinstance(session_or_result, VoiceCaptureResult):
            event_type = self._capture_terminal_event_type(session_or_result)
            self._publish_capture_terminal(
                event_type, session_or_result, "Push-to-talk capture did not start."
            )
            return self._remember_capture_result(session_or_result)

        session = session_or_result
        self.last_capture_session = session
        capture_listen_window_id = self._metadata_listen_window_id(
            session.metadata
        ) or request_listen_window_id
        self._transition_to_capturing(session)
        self._publish(
            VoiceEventType.CAPTURE_STARTED,
            message="Push-to-talk capture started.",
            session_id=session.session_id,
            turn_id=session.turn_id,
            capture_request_id=session.capture_request_id,
            capture_id=session.capture_id,
            listen_window_id=capture_listen_window_id,
            provider=session.provider,
            device=session.device,
            mode=self.config.capture.mode,
            source="push_to_talk",
            state=VoiceState.CAPTURING.value,
            status=session.status,
            metadata={"capture": session.to_dict()},
        )
        self._publish(
            VoiceEventType.STATE_CHANGED,
            message="Voice state changed for push-to-talk capture.",
            session_id=session.session_id,
            turn_id=session.turn_id,
            capture_request_id=session.capture_request_id,
            capture_id=session.capture_id,
            listen_window_id=capture_listen_window_id,
            provider=session.provider,
            device=session.device,
            state=VoiceState.CAPTURING.value,
            status=session.status,
            source="push_to_talk",
        )
        if self.config.vad.enabled:
            listen_window_id = self._metadata_listen_window_id(session.metadata)
            if listen_window_id is None:
                request_metadata = getattr(allowed_request, "metadata", None)
                listen_window_id = self._metadata_listen_window_id(request_metadata)
            self._start_vad_detection_sync(
                capture_id=session.capture_id,
                listen_window_id=listen_window_id,
                session_id=session.session_id,
            )
        return session

    async def stop_push_to_talk_capture(
        self,
        capture_id: str | None = None,
        *,
        reason: str = "user_released",
    ) -> VoiceCaptureResult:
        operation = getattr(self.capture_provider, "stop_capture", None)
        if not callable(operation):
            result = VoiceCaptureResult(
                ok=False,
                capture_request_id=None,
                capture_id=capture_id,
                status="unavailable",
                provider=self._capture_provider_name(),
                device=self.config.capture.device,
                stopped_at=self._now(),
                stop_reason=reason,
                error_code="provider_unavailable",
                error_message="Voice capture provider does not support stop.",
            )
        else:
            result = operation(capture_id, reason=reason)
            if inspect.isawaitable(result):
                result = await result
        self._handle_capture_terminal_state(result)
        self._stop_vad_detection_for_capture(result.capture_id, reason=result.status)
        return self._remember_capture_result(result)

    async def cancel_capture(
        self,
        capture_id: str | None = None,
        *,
        reason: str = "user_cancelled",
    ) -> VoiceCaptureResult:
        operation = getattr(self.capture_provider, "cancel_capture", None)
        if not callable(operation):
            result = VoiceCaptureResult(
                ok=False,
                capture_request_id=None,
                capture_id=capture_id,
                status="unavailable",
                provider=self._capture_provider_name(),
                device=self.config.capture.device,
                stopped_at=self._now(),
                stop_reason=reason,
                error_code="provider_unavailable",
                error_message="Voice capture provider does not support cancellation.",
            )
        else:
            result = operation(capture_id, reason=reason)
            if inspect.isawaitable(result):
                result = await result
        self._handle_capture_terminal_state(result)
        self._stop_vad_detection_for_capture(result.capture_id, reason=result.status)
        return self._remember_capture_result(result)

    def get_active_vad_session(self) -> VoiceVADSession | None:
        provider_active = self._provider_active_vad_session()
        if provider_active is not None:
            return provider_active
        if self.active_vad_session is not None and (
            self.active_vad_session.status == "active"
        ):
            return self.active_vad_session
        return None

    async def start_vad_detection(
        self,
        *,
        capture_id: str | None = None,
        listen_window_id: str | None = None,
        session_id: str | None = None,
    ) -> VoiceVADSession:
        session = self._start_vad_detection_sync(
            capture_id=capture_id,
            listen_window_id=listen_window_id,
            session_id=session_id,
        )
        return session

    async def stop_vad_detection(
        self,
        vad_session_id: str | None = None,
        *,
        reason: str = "stopped",
    ) -> VoiceVADSession:
        return self._stop_vad_detection_sync(vad_session_id, reason=reason)

    async def simulate_speech_started(
        self,
        *,
        capture_id: str | None = None,
        listen_window_id: str | None = None,
        confidence: float | None = None,
    ) -> VoiceActivityEvent:
        if self.get_active_vad_session() is None:
            self._start_vad_detection_sync(
                capture_id=capture_id,
                listen_window_id=listen_window_id,
                session_id=self.last_capture_session.session_id
                if self.last_capture_session is not None
                else None,
            )
        operation = getattr(self.vad_provider, "simulate_speech_started", None)
        event = (
            operation(confidence=confidence)
            if callable(operation)
            else self._vad_error_event("provider_unavailable")
        )
        if event.listen_window_id is None:
            inferred_listen_window_id = listen_window_id or self._listen_window_id_for_capture(
                capture_id or event.capture_id
            )
            if inferred_listen_window_id:
                event = replace(event, listen_window_id=inferred_listen_window_id)
        self._remember_activity_event(event)
        self._publish_activity_event(
            VoiceEventType.SPEECH_ACTIVITY_STARTED
            if event.status == "speech_started"
            else VoiceEventType.VAD_ERROR,
            event,
            "Speech activity detected."
            if event.status == "speech_started"
            else "VAD activity failed.",
        )
        self._mark_vad_speech_started(event)
        return event

    async def simulate_speech_stopped(
        self,
        *,
        capture_id: str | None = None,
        listen_window_id: str | None = None,
        confidence: float | None = None,
    ) -> VoiceActivityEvent:
        if self.get_active_vad_session() is None:
            self._start_vad_detection_sync(
                capture_id=capture_id,
                listen_window_id=listen_window_id,
                session_id=self.last_capture_session.session_id
                if self.last_capture_session is not None
                else None,
            )
        operation = getattr(self.vad_provider, "simulate_speech_stopped", None)
        event = (
            operation(confidence=confidence)
            if callable(operation)
            else self._vad_error_event("provider_unavailable")
        )
        if event.listen_window_id is None:
            inferred_listen_window_id = listen_window_id or self._listen_window_id_for_capture(
                capture_id or event.capture_id
            )
            if inferred_listen_window_id:
                event = replace(event, listen_window_id=inferred_listen_window_id)
        self._remember_activity_event(event)
        self._publish_activity_event(
            VoiceEventType.SPEECH_ACTIVITY_STOPPED
            if event.status == "speech_stopped"
            else VoiceEventType.VAD_ERROR,
            event,
            "Speech activity stopped."
            if event.status == "speech_stopped"
            else "VAD activity failed.",
        )
        self._mark_vad_speech_stopped(event)
        if (
            event.status == "speech_stopped"
            and self.config.vad.auto_finalize_capture
            and event.capture_id
        ):
            self._publish_activity_event(
                VoiceEventType.SILENCE_TIMEOUT,
                event,
                "VAD silence threshold reached.",
            )
            result = await self.stop_push_to_talk_capture(
                event.capture_id,
                reason="vad_silence_timeout",
            )
            if self.last_vad_session is not None:
                self.last_vad_session = replace(
                    self.last_vad_session,
                    finalized_capture=result.status == "completed",
                    finalization_reason="vad_silence_timeout",
                )
                self.vad_sessions[self.last_vad_session.vad_session_id] = (
                    self.last_vad_session
                )
        return event

    async def submit_captured_audio_turn(
        self,
        capture_result: VoiceCaptureResult,
        *,
        mode: str = "ghost",
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        screen_context_permission: str = "not_requested",
        confirmation_intent: str | None = None,
        interrupt_intent: str | None = None,
    ) -> VoiceTurnResult:
        if (
            not isinstance(capture_result, VoiceCaptureResult)
            or capture_result.status != "completed"
        ):
            return self._remember_audio_turn_result(
                VoiceTurnResult(
                    ok=False,
                    error_code="capture_not_completed",
                    error_message="Captured audio was not completed and will not be routed.",
                    voice_state_before=self.state_controller.snapshot().to_dict(),
                    voice_state_after=self.state_controller.snapshot().to_dict(),
                    state_transitions=[self.state_controller.snapshot().to_dict()],
                    stt_invoked=False,
                    tts_invoked=False,
                    realtime_invoked=False,
                    audio_playback_started=False,
                )
            )
        if capture_result.audio_input is None:
            return self._remember_audio_turn_result(
                VoiceTurnResult(
                    ok=False,
                    error_code="capture_audio_missing",
                    error_message="Completed capture did not include a VoiceAudioInput.",
                    voice_state_before=self.state_controller.snapshot().to_dict(),
                    voice_state_after=self.state_controller.snapshot().to_dict(),
                    state_transitions=[self.state_controller.snapshot().to_dict()],
                    stt_invoked=False,
                    tts_invoked=False,
                    realtime_invoked=False,
                    audio_playback_started=False,
                )
            )
        capture_metadata = {
            "capture_id": capture_result.capture_id,
            "capture_request_id": capture_result.capture_request_id,
            "capture_status": capture_result.status,
            "capture_provider": capture_result.provider,
            "capture_device": capture_result.device,
            "duration_ms": capture_result.duration_ms,
            "size_bytes": capture_result.size_bytes,
            "push_to_talk": True,
            "always_listening_claimed": False,
            "wake_word_claimed": False,
        }
        turn_result = await self.submit_audio_voice_turn(
            capture_result.audio_input,
            mode=mode,
            session_id=session_id,
            metadata={**dict(metadata or {}), "capture": capture_metadata},
            screen_context_permission=screen_context_permission,
            confirmation_intent=confirmation_intent,
            interrupt_intent=interrupt_intent,
        )
        cleanup_warning = self._cleanup_captured_audio_after_turn(capture_result)
        if cleanup_warning:
            capture_result.metadata["cleanup_warning"] = cleanup_warning
            self.last_capture_error = {
                "code": "capture_cleanup_warning",
                "message": cleanup_warning,
            }
        return turn_result

    async def capture_and_submit_turn(
        self,
        capture_id: str | None = None,
        *,
        mode: str = "ghost",
        synthesize_response: bool = False,
        play_response: bool = False,
    ) -> VoiceCaptureTurnResult:
        capture_result = await self.stop_push_to_talk_capture(
            capture_id, reason="user_released"
        )
        if not capture_result.ok:
            return VoiceCaptureTurnResult(
                capture_result=capture_result,
                final_status=capture_result.status,
                error_code=capture_result.error_code,
                stopped_stage="capture",
            )

        turn_result = await self.submit_captured_audio_turn(
            capture_result,
            mode=mode,
            session_id=self.last_capture_session.session_id
            if self.last_capture_session is not None
            else None,
        )
        if not turn_result.ok:
            return VoiceCaptureTurnResult(
                capture_result=capture_result,
                voice_turn_result=turn_result,
                final_status="failed",
                error_code=turn_result.error_code,
                stopped_stage="core",
            )

        synthesis = None
        playback = None
        streaming_output = None
        streaming_requested = bool(
            play_response
            and self.config.openai.stream_tts_outputs
            and self.config.playback.streaming_enabled
        )
        if streaming_requested:
            streaming_output = await self.stream_turn_response(
                turn_result,
                metadata={
                    "capture_turn_play_response": True,
                    "audio_voice_stream_response": True,
                },
                source="core_spoken_summary",
            )
            if not streaming_output.ok:
                stopped_stage = (
                    "playback"
                    if streaming_output.playback_result is not None
                    else "tts"
                )
                return VoiceCaptureTurnResult(
                    capture_result=capture_result,
                    voice_turn_result=turn_result,
                    streaming_output_result=streaming_output,
                    final_status="playback_failed"
                    if stopped_stage == "playback"
                    else "speech_synthesis_failed",
                    error_code=streaming_output.error_code,
                    stopped_stage=stopped_stage,
                )
            return VoiceCaptureTurnResult(
                capture_result=capture_result,
                voice_turn_result=turn_result,
                streaming_output_result=streaming_output,
                final_status="completed",
            )
        if synthesize_response:
            synthesis = await self.synthesize_turn_response(turn_result)
            if not synthesis.ok:
                return VoiceCaptureTurnResult(
                    capture_result=capture_result,
                    voice_turn_result=turn_result,
                    synthesis_result=synthesis,
                    final_status="speech_synthesis_failed",
                    error_code=synthesis.error_code,
                    stopped_stage="tts",
                )
        if play_response:
            if synthesis is None:
                synthesis = await self.synthesize_turn_response(turn_result)
            playback = await self.play_speech_output(synthesis)
            if not playback.ok:
                return VoiceCaptureTurnResult(
                    capture_result=capture_result,
                    voice_turn_result=turn_result,
                    synthesis_result=synthesis,
                    playback_result=playback,
                    final_status="playback_failed",
                    error_code=playback.error_code,
                    stopped_stage="playback",
                )
        return VoiceCaptureTurnResult(
            capture_result=capture_result,
            voice_turn_result=turn_result,
            synthesis_result=synthesis,
            playback_result=playback,
            final_status="completed",
        )

    async def stream_turn_response(
        self,
        turn_result: VoiceTurnResult,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        source: str = "core_spoken_summary",
    ) -> VoiceStreamingSpeechOutputResult:
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
        active_session_id = session_id or (
            turn_result.turn.session_id if turn_result.turn is not None else None
        )
        turn_id = turn_result.turn.turn_id if turn_result.turn is not None else None
        core_result = turn_result.core_result
        result_state = core_result.result_state if core_result is not None else None
        persona_mode = (
            turn_result.turn.interaction_mode
            if turn_result.turn is not None
            else "ghost"
        )
        stream_metadata = {
            **dict(metadata or {}),
            "core_result": core_result.to_dict() if core_result is not None else None,
            "voice_stream_used_by_normal_path": True,
        }
        if spoken_response is None or not spoken_response.should_speak:
            return await self.stream_core_approved_spoken_text(
                "",
                speak_allowed=False,
                session_id=active_session_id,
                turn_id=turn_id,
                source=source,
                persona_mode=persona_mode,
                result_state_source=result_state,
                metadata={
                    **stream_metadata,
                    "streaming_miss_reason": "spoken_response_not_allowed",
                },
            )
        return await self.stream_core_approved_spoken_text(
            spoken_response.spoken_text,
            speak_allowed=bool(core_result and core_result.speak_allowed),
            session_id=active_session_id,
            turn_id=turn_id,
            source=source,
            persona_mode=persona_mode,
            speech_length_hint=spoken_response.speech_length_hint,
            result_state_source=result_state or spoken_response.source_result_state,
            metadata=stream_metadata,
        )

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
        turn_input_metadata = dict(metadata or {})
        audio_listen_window_id = self._metadata_listen_window_id(
            turn_input_metadata
        ) or self._metadata_listen_window_id(audio.metadata)

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
            listen_window_id=audio_listen_window_id,
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
            listen_window_id=audio_listen_window_id,
            provider=self.provider.name,
            model=self._stt_model_name(),
            mode=interaction_mode,
            source="voice_stt",
            state=VoiceState.TRANSCRIBING.value,
        )

        transcription_result = await self._transcribe_audio(audio)
        transcription_result = self._apply_transcription_quality_rules(
            transcription_result
        )
        self.last_transcription_result = transcription_result
        self.last_openai_call_attempted = (
            transcription_result.provider == "openai"
            and self._provider_network_call_count() > 0
        )

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
                message=transcription_result.error_message
                or "Controlled voice audio transcription failed.",
                session_id=active_session_id,
                input_id=audio.input_id,
                transcription_id=transcription_result.transcription_id,
                listen_window_id=audio_listen_window_id,
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
                    provenance={
                        "source": transcription_result.source,
                        "input_id": audio.input_id,
                    },
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
                listen_window_id=audio_listen_window_id,
                provider=transcription_result.provider,
                model=transcription_result.model,
                mode=interaction_mode,
                source=transcription_result.source,
                state=self.state_controller.snapshot().state.value,
                error_code=transcription_result.error_code,
                result_state=core_result.result_state
                if core_result is not None
                else "failed",
            )
            return self._remember_audio_turn_result(result)

        self._publish(
            VoiceEventType.TRANSCRIPTION_COMPLETED,
            message="Controlled voice audio transcription completed.",
            session_id=active_session_id,
            input_id=audio.input_id,
            transcription_id=transcription_result.transcription_id,
            listen_window_id=audio_listen_window_id,
            provider=transcription_result.provider,
            model=transcription_result.model,
            mode=interaction_mode,
            source=transcription_result.source,
            state=VoiceState.TRANSCRIBING.value,
            metadata={
                "transcript_preview": self._preview_text(
                    transcription_result.transcript
                ),
                "uncertain": transcription_result.transcription_uncertain,
            },
        )

        confirmation_turn = await self._maybe_handle_spoken_confirmation_turn(
            transcription_result.transcript,
            session_id=active_session_id,
            mode=interaction_mode,
            source=transcription_result.source or "openai_stt",
            metadata=dict(metadata or {}),
            transcription_result=transcription_result,
        )
        if confirmation_turn is not None:
            return self._remember_audio_turn_result(confirmation_turn)

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

        normalized_transcript = " ".join(
            transcription_result.transcript.split()
        ).strip()
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
        if self.config.playback.prewarm_enabled and self.config.spoken_responses_enabled:
            self.prewarm_voice_output(
                session_id=active_session_id,
                turn_id=turn.turn_id,
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
            core_result = await submit_voice_core_request(
                self.core_bridge, core_request
            )
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
            metadata={
                "should_speak": spoken_response.should_speak,
                "text_only_preview": True,
            },
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
        active_session_id = session_id or (
            turn_result.turn.session_id if turn_result.turn is not None else None
        )
        turn_id = turn_result.turn.turn_id if turn_result.turn is not None else None
        if spoken_response is None or not spoken_response.should_speak:
            request = self._build_speech_request(
                text="",
                source="core_spoken_summary",
                persona_mode=turn_result.turn.interaction_mode
                if turn_result.turn is not None
                else "ghost",
                speech_length_hint="short",
                session_id=active_session_id,
                turn_id=turn_id,
                result_state_source=turn_result.core_result.result_state
                if turn_result.core_result is not None
                else None,
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
            persona_mode=turn_result.turn.interaction_mode
            if turn_result.turn is not None
            else "ghost",
            speech_length_hint=spoken_response.speech_length_hint,
            session_id=active_session_id,
            turn_id=turn_id,
            result_state_source=turn_result.core_result.result_state
            if turn_result.core_result is not None
            else spoken_response.source_result_state,
            metadata={
                **dict(metadata or {}),
                "core_result": turn_result.core_result.to_dict()
                if turn_result.core_result is not None
                else None,
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

    async def synthesize_speech_request(
        self, request: VoiceSpeechRequest
    ) -> VoiceSpeechSynthesisResult:
        block_reason = request.blocked_reason or self._tts_request_block_reason(request)
        if block_reason is not None:
            blocked_request = replace(
                request, allowed_to_synthesize=False, blocked_reason=block_reason
            )
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
            if block_reason in {"current_response_suppressed", "spoken_output_muted"}:
                self._publish(
                    VoiceEventType.SPEECH_SUPPRESSED,
                    message=f"Voice speech output suppressed: {block_reason}.",
                    session_id=blocked_request.session_id,
                    turn_id=blocked_request.turn_id,
                    speech_request_id=blocked_request.speech_request_id,
                    provider=blocked_request.provider,
                    model=blocked_request.model,
                    voice=blocked_request.voice,
                    format=blocked_request.format,
                    mode=blocked_request.persona_mode,
                    source=blocked_request.source,
                    error_code=block_reason,
                    status="suppressed",
                    spoken_output_suppressed=True,
                    metadata={"speech_request": blocked_request.to_metadata()},
                )
            return self._remember_synthesis_result(
                self._blocked_synthesis_result(
                    blocked_request,
                    error_code=block_reason,
                    error_message=f"Voice speech synthesis blocked: {block_reason}.",
                )
            )

        allowed_request = replace(
            request, allowed_to_synthesize=True, blocked_reason=None
        )
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
            synthesis.provider == "openai"
            and after_network_count > before_network_count
        )
        event_type = (
            VoiceEventType.SYNTHESIS_COMPLETED
            if synthesis.ok
            else VoiceEventType.SYNTHESIS_FAILED
        )
        self._publish(
            event_type,
            message="Voice speech synthesis completed."
            if synthesis.ok
            else "Voice speech synthesis failed.",
            session_id=allowed_request.session_id,
            turn_id=allowed_request.turn_id,
            speech_request_id=allowed_request.speech_request_id,
            synthesis_id=synthesis.synthesis_id,
            audio_output_id=synthesis.audio_output.output_id
            if synthesis.audio_output is not None
            else None,
            provider=synthesis.provider,
            model=synthesis.model,
            voice=synthesis.voice,
            format=synthesis.format,
            mode=allowed_request.persona_mode,
            source=allowed_request.source,
            status=synthesis.status,
            error_code=synthesis.error_code,
            metadata={
                "audio_output": synthesis.audio_output.to_metadata()
                if synthesis.audio_output is not None
                else None,
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

    def prewarm_voice_output(
        self,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> VoiceOutputPrewarmResult:
        start = time.perf_counter()
        provider_result: VoiceProviderPrewarmResult | None = None
        playback_result: VoicePlaybackPrewarmResult | None = None

        provider_operation = getattr(self.provider, "prewarm_speech_provider", None)
        provider_request = VoiceProviderPrewarmRequest(
            session_id=session_id,
            turn_id=turn_id,
            provider=getattr(self.provider, "name", self.availability.provider_name),
            model=self._tts_model_name(),
            voice=self._tts_voice_name(),
            live_format=self._tts_live_format_name(),
            artifact_format=self._tts_artifact_format_name(),
        )
        if callable(provider_operation):
            provider_result = provider_operation(provider_request)
        else:
            provider_result = VoiceProviderPrewarmResult(
                ok=False,
                request_id=provider_request.request_id,
                provider=provider_request.provider,
                status="unavailable",
                model=provider_request.model,
                voice=provider_request.voice,
                live_format=provider_request.live_format,
                artifact_format=provider_request.artifact_format,
                error_code="provider_prewarm_unsupported",
                error_message="Voice provider does not expose a prewarm hook.",
            )
        self.last_provider_prewarm_result = provider_result
        self._publish(
            VoiceEventType.PROVIDER_PREWARMED,
            message="Voice TTS provider shell prewarmed.",
            session_id=session_id,
            turn_id=turn_id,
            provider=provider_result.provider,
            model=provider_result.model,
            voice=provider_result.voice,
            format=provider_result.live_format,
            status=provider_result.status,
            error_code=provider_result.error_code,
            metadata={"provider_prewarm": provider_result.to_dict()},
        )

        playback_operation = getattr(self.playback_provider, "prewarm_playback", None)
        playback_request = VoicePlaybackPrewarmRequest(
            session_id=session_id,
            turn_id=turn_id,
            provider=self._playback_provider_name(),
            device=self.config.playback.device,
            audio_format=self._tts_live_format_name(),
        )
        if callable(playback_operation):
            playback_result = playback_operation(playback_request)
        else:
            playback_result = VoicePlaybackPrewarmResult(
                ok=False,
                request_id=playback_request.request_id,
                provider=playback_request.provider,
                device=playback_request.device,
                audio_format=playback_request.audio_format,
                status="unavailable",
                error_code="playback_prewarm_unsupported",
                error_message="Voice playback provider does not expose a prewarm hook.",
            )
        self.last_playback_prewarm_result = playback_result
        self._publish(
            VoiceEventType.PLAYBACK_PREWARMED,
            message="Voice playback sink prewarmed.",
            session_id=session_id,
            turn_id=turn_id,
            provider=playback_result.provider,
            device=playback_result.device,
            format=playback_result.audio_format,
            status=playback_result.status,
            error_code=playback_result.error_code,
            metadata={"playback_prewarm": playback_result.to_dict()},
        )

        result = VoiceOutputPrewarmResult(
            ok=bool(provider_result.ok and playback_result.ok),
            status="prepared"
            if provider_result.ok and playback_result.ok
            else "partial"
            if provider_result.ok or playback_result.ok
            else "unavailable",
            provider_result=provider_result,
            playback_result=playback_result,
            prewarm_ms=int(max(0.0, (time.perf_counter() - start) * 1000.0)),
        )
        self.last_voice_output_prewarm_result = result
        return result

    async def stream_core_approved_spoken_text(
        self,
        text: str,
        *,
        speak_allowed: bool,
        session_id: str | None = None,
        turn_id: str | None = None,
        source: str = "core_spoken_summary",
        persona_mode: str = "ghost",
        speech_length_hint: str = "short",
        result_state_source: str | None = "completed",
        core_result_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        request_started_ms: int | float | None = None,
        core_result_completed_ms: int | float | None = None,
    ) -> VoiceStreamingSpeechOutputResult:
        input_metadata = dict(metadata or {})
        normal_path_stream = bool(
            input_metadata.get("voice_stream_used_by_normal_path")
            or input_metadata.get("assistant_response_voice_output")
            or input_metadata.get("capture_turn_play_response")
            or input_metadata.get("manual_voice_stream_response")
            or input_metadata.get("audio_voice_stream_response")
        )
        speech_request = self._build_speech_request(
            text=text,
            source=source,
            persona_mode=persona_mode,
            speech_length_hint=speech_length_hint,
            session_id=session_id,
            turn_id=turn_id,
            result_state_source=result_state_source,
            metadata={**input_metadata, "core_result_id": core_result_id},
            allowed_to_synthesize=speak_allowed,
            blocked_reason=None if speak_allowed else "speak_not_allowed",
        )
        if speak_allowed:
            speech_request = replace(
                speech_request,
                format=self._tts_live_format_name(),
                allowed_to_synthesize=True,
                blocked_reason=None,
            )
        else:
            self.last_speech_request = speech_request
            return self._streaming_speech_blocked_result(
                speech_request,
                error_code="speak_not_allowed",
                error_message="Speech output was not allowed for this Core result.",
            )

        block_reason = self._tts_request_block_reason(speech_request)
        if block_reason is not None:
            blocked_request = replace(
                speech_request,
                allowed_to_synthesize=False,
                blocked_reason=block_reason,
            )
            self.last_speech_request = blocked_request
            return self._streaming_speech_blocked_result(
                blocked_request,
                error_code=block_reason,
                error_message=f"Voice streaming speech blocked: {block_reason}.",
            )

        streaming_enabled = bool(
            self.config.openai.stream_tts_outputs
            and self.config.playback.streaming_enabled
        )
        if not streaming_enabled:
            if not self.config.openai.streaming_fallback_to_buffered:
                self.last_speech_request = speech_request
                return self._streaming_speech_blocked_result(
                    speech_request,
                    error_code="streaming_tts_disabled",
                    error_message="Streaming TTS output is disabled.",
                )
            synthesis = await self.synthesize_speech_request(speech_request)
            playback_result = await self.play_speech_output(synthesis)
            latency = VoiceFirstAudioLatency(
                streaming_enabled=False,
                streaming_transport_kind="buffered_fallback",
                first_chunk_before_complete=False,
                live_format=self._tts_live_format_name(),
                artifact_format=self._tts_artifact_format_name(),
                fallback_used=True,
                prewarm_used=self.last_voice_output_prewarm_result is not None,
                prewarm_ms=(
                    self.last_voice_output_prewarm_result.prewarm_ms
                    if self.last_voice_output_prewarm_result is not None
                    else None
                ),
                playback_prewarmed=bool(
                    self.last_playback_prewarm_result
                    and self.last_playback_prewarm_result.ok
                ),
                provider_prewarmed=bool(
                    self.last_provider_prewarm_result
                    and self.last_provider_prewarm_result.ok
                ),
                first_audio_available=bool(playback_result.ok),
                voice_stream_used_by_normal_path=normal_path_stream,
                streaming_miss_reason="streaming_tts_disabled",
                user_heard_claimed=False,
            )
            self.last_first_audio_latency = latency
            return VoiceStreamingSpeechOutputResult(
                ok=bool(synthesis.ok and playback_result.ok),
                status=playback_result.status if playback_result else synthesis.status,
                speech_request_id=speech_request.speech_request_id,
                session_id=session_id,
                turn_id=turn_id,
                streaming_enabled=False,
                first_audio_available=bool(playback_result.ok),
                streaming_transport_kind="buffered_fallback",
                first_chunk_before_complete=False,
                stream_used_by_normal_path=normal_path_stream,
                streaming_miss_reason="streaming_tts_disabled",
                buffered_synthesis_result=synthesis,
                latency=latency,
                fallback_used=True,
                error_code=playback_result.error_code or synthesis.error_code,
                error_message=playback_result.error_message or synthesis.error_message,
                metadata={"fallback_to_buffered": True},
            )

        streaming_request = VoiceStreamingTTSRequest.from_speech_request(
            speech_request,
            live_format=self._tts_live_format_name(),
            artifact_format=self._tts_artifact_format_name(),
            metadata={"source": source, "core_result_id": core_result_id},
        )
        self.last_speech_request = speech_request
        self.last_streaming_tts_request = streaming_request
        self._publish(
            VoiceEventType.TTS_STREAM_STARTED,
            message="Voice streaming TTS started.",
            session_id=session_id,
            turn_id=turn_id,
            speech_request_id=speech_request.speech_request_id,
            provider=speech_request.provider,
            model=speech_request.model,
            voice=speech_request.voice,
            format=streaming_request.live_format,
            source=source,
            status="started",
            metadata={"streaming_tts_request": streaming_request.to_metadata()},
        )

        tts_started_ms = int(max(0.0, float(core_result_completed_ms or 0.0)))
        if request_started_ms is None:
            request_started_ms = 0
        operation = getattr(self.provider, "stream_speech", None)
        if not callable(operation):
            tts_result = VoiceStreamingTTSResult(
                ok=False,
                tts_stream_id=streaming_request.tts_stream_id,
                speech_request_id=speech_request.speech_request_id,
                provider=speech_request.provider,
                model=speech_request.model,
                voice=speech_request.voice,
                live_format=streaming_request.live_format,
                artifact_format=streaming_request.artifact_format,
                status="unavailable",
                streaming_transport_kind="unsupported",
                first_chunk_before_complete=False,
                error_code="streaming_tts_unsupported",
                error_message="Voice provider does not implement streaming TTS.",
            )
        else:
            tts_result = operation(streaming_request)
        if inspect.isawaitable(tts_result):
            tts_result = await tts_result
        self.last_streaming_tts_result = tts_result
        if tts_result.chunks:
            first_chunk = tts_result.chunks[0]
            self._remember_voice_output_envelope(
                first_chunk.data,
                audio_format=first_chunk.live_format or tts_result.live_format,
                source="streaming_chunk_envelope",
            )

        first_chunk_delta = tts_result.first_audio_byte_ms
        first_chunk_ms = (
            tts_started_ms + int(first_chunk_delta or 0)
            if tts_result.first_chunk_at is not None
            else None
        )
        if (
            not tts_result.ok
            and not tts_result.chunks
            and self.config.openai.streaming_fallback_to_buffered
        ):
            synthesis = await self.synthesize_speech_request(speech_request)
            buffered_playback = await self.play_speech_output(synthesis)
            latency = VoiceFirstAudioLatency(
                core_result_to_tts_start_ms=0,
                streaming_enabled=True,
                streaming_transport_kind=tts_result.streaming_transport_kind,
                first_chunk_before_complete=tts_result.first_chunk_before_complete,
                stream_complete_ms=tts_result.stream_complete_ms,
                live_format=streaming_request.live_format,
                artifact_format=streaming_request.artifact_format,
                fallback_used=True,
                prewarm_used=self.last_voice_output_prewarm_result is not None,
                prewarm_ms=(
                    self.last_voice_output_prewarm_result.prewarm_ms
                    if self.last_voice_output_prewarm_result is not None
                    else None
                ),
                playback_prewarmed=bool(
                    self.last_playback_prewarm_result
                    and self.last_playback_prewarm_result.ok
                ),
                provider_prewarmed=bool(
                    self.last_provider_prewarm_result
                    and self.last_provider_prewarm_result.ok
                ),
                first_audio_available=bool(buffered_playback.ok),
                voice_stream_used_by_normal_path=normal_path_stream,
                streaming_miss_reason=tts_result.error_code
                or "streaming_failed_before_first_audio",
                user_heard_claimed=False,
            )
            self.last_first_audio_latency = latency
            self._publish(
                VoiceEventType.SYNTHESIS_FAILED,
                message="Voice streaming TTS failed before first audio; buffered fallback used.",
                session_id=session_id,
                turn_id=turn_id,
                speech_request_id=speech_request.speech_request_id,
                provider=tts_result.provider,
                model=tts_result.model,
                voice=tts_result.voice,
                format=tts_result.live_format,
                source=source,
                status="fallback_buffered",
                error_code=tts_result.error_code,
                metadata={
                    "streaming_tts_result": tts_result.to_dict(),
                    "buffered_fallback": True,
                    "buffered_synthesis_result": synthesis.to_dict(),
                    "buffered_playback_result": buffered_playback.to_dict(),
                },
            )
            return VoiceStreamingSpeechOutputResult(
                ok=bool(synthesis.ok and buffered_playback.ok),
                status=buffered_playback.status if buffered_playback else synthesis.status,
                speech_request_id=speech_request.speech_request_id,
                session_id=session_id,
                turn_id=turn_id,
                streaming_enabled=True,
                first_audio_available=bool(buffered_playback.ok),
                streaming_transport_kind=tts_result.streaming_transport_kind,
                first_chunk_before_complete=tts_result.first_chunk_before_complete,
                stream_used_by_normal_path=normal_path_stream,
                streaming_miss_reason=tts_result.error_code
                or "streaming_failed_before_first_audio",
                tts_result=replace(tts_result, fallback_used=True),
                buffered_synthesis_result=synthesis,
                buffered_playback_result=buffered_playback,
                latency=latency,
                fallback_used=True,
                error_code=tts_result.error_code,
                error_message=tts_result.error_message,
                metadata={"streaming_failed_before_first_audio": True},
            )
        live_request: VoiceLivePlaybackRequest | None = None
        live_session: VoiceLivePlaybackSession | None = None
        live_result: VoiceLivePlaybackResult | None = None
        playback_started_ms: int | None = None

        if tts_result.chunks:
            live_request = VoiceLivePlaybackRequest(
                speech_request_id=speech_request.speech_request_id,
                provider=self._playback_provider_name(),
                device=self.config.playback.device,
                audio_format=streaming_request.live_format,
                tts_stream_id=tts_result.tts_stream_id,
                session_id=session_id,
                turn_id=turn_id,
                volume=self.config.playback.volume,
                allowed_to_play=True,
                metadata={"source": "streaming_tts"},
            )
            self.last_live_playback_request = live_request
            start_operation = getattr(self.playback_provider, "start_stream", None)
            if not callable(start_operation):
                live_session = VoiceLivePlaybackSession(
                    playback_stream_id=live_request.playback_stream_id,
                    playback_request_id=live_request.playback_request_id,
                    provider=live_request.provider,
                    device=live_request.device,
                    audio_format=live_request.audio_format,
                    status="unsupported",
                    session_id=session_id,
                    turn_id=turn_id,
                    tts_stream_id=tts_result.tts_stream_id,
                    speech_request_id=speech_request.speech_request_id,
                    error_code="streaming_playback_unsupported",
                    error_message="Playback provider does not implement live streaming.",
                )
            else:
                live_session = start_operation(live_request)
            self.last_live_playback_session = live_session
            self._publish(
                VoiceEventType.PLAYBACK_STREAM_STARTED,
                message="Voice playback stream started.",
                session_id=session_id,
                turn_id=turn_id,
                speech_request_id=speech_request.speech_request_id,
                playback_request_id=live_session.playback_request_id,
                playback_id=live_session.playback_stream_id,
                provider=live_session.provider,
                device=live_session.device,
                format=live_session.audio_format,
                status=live_session.status,
                error_code=live_session.error_code,
                metadata={"playback_stream": live_session.to_dict()},
            )

            if live_session.status in {"started", "playing"}:
                feed_operation = getattr(self.playback_provider, "feed_stream_chunk", None)
                for chunk in tts_result.chunks:
                    if self._speech_output_block_reason(turn_id) is not None:
                        cancel_operation = getattr(self.playback_provider, "cancel_stream", None)
                        if callable(cancel_operation):
                            live_result = cancel_operation(
                                live_session.playback_stream_id,
                                reason=self._speech_output_block_reason(turn_id)
                                or "speech_suppressed",
                            )
                        break
                    if callable(feed_operation):
                        chunk_result = feed_operation(
                            live_session.playback_stream_id,
                            chunk.data or b"",
                            chunk_index=chunk.chunk_index,
                        )
                        self._remember_voice_output_envelope(
                            chunk.data,
                            audio_format=chunk.live_format,
                            source="playback_output_envelope"
                            if chunk_result.ok
                            else "streaming_chunk_envelope",
                        )
                        if playback_started_ms is None and chunk_result.playback_started:
                            playback_started_ms = (first_chunk_ms or tts_started_ms) + int(
                                max(0, chunk_result.chunk_index - chunk.chunk_index)
                            )
                            self._publish(
                                VoiceEventType.TTS_FIRST_CHUNK_RECEIVED,
                                message="Voice first TTS chunk received.",
                                session_id=session_id,
                                turn_id=turn_id,
                                speech_request_id=speech_request.speech_request_id,
                                playback_request_id=live_session.playback_request_id,
                                playback_id=live_session.playback_stream_id,
                                provider=tts_result.provider,
                                model=tts_result.model,
                                voice=tts_result.voice,
                                format=tts_result.live_format,
                                status="first_audio_available",
                                size_bytes=chunk.size_bytes,
                                metadata={
                                    "chunk": chunk.to_dict(),
                                    "playback_chunk_result": chunk_result.to_dict(),
                                },
                            )
                        if not chunk_result.ok:
                            live_result = VoiceLivePlaybackResult(
                                ok=False,
                                playback_stream_id=live_session.playback_stream_id,
                                playback_request_id=live_session.playback_request_id,
                                provider=live_session.provider,
                                device=live_session.device,
                                audio_format=live_session.audio_format,
                                status=chunk_result.status,
                                session_id=session_id,
                                turn_id=turn_id,
                                tts_stream_id=tts_result.tts_stream_id,
                                speech_request_id=speech_request.speech_request_id,
                                started_at=live_session.started_at,
                                first_chunk_received_at=chunk_result.first_chunk_received_at,
                                playback_started_at=chunk_result.playback_started_at,
                                partial_playback=playback_started_ms is not None,
                                error_code=chunk_result.error_code,
                                error_message=chunk_result.error_message,
                                user_heard_claimed=False,
                            )
                            break
                if live_result is None:
                    if tts_result.ok:
                        complete_operation = getattr(self.playback_provider, "complete_stream", None)
                        if callable(complete_operation):
                            live_result = complete_operation(live_session.playback_stream_id)
                    else:
                        cancel_operation = getattr(self.playback_provider, "cancel_stream", None)
                        if callable(cancel_operation):
                            live_result = cancel_operation(
                                live_session.playback_stream_id,
                                reason=tts_result.error_code or "streaming_tts_failed",
                            )
                if live_result is None:
                    live_result = VoiceLivePlaybackResult(
                        ok=False,
                        playback_stream_id=live_session.playback_stream_id,
                        playback_request_id=live_session.playback_request_id,
                        provider=live_session.provider,
                        device=live_session.device,
                        audio_format=live_session.audio_format,
                        status="failed",
                        session_id=session_id,
                        turn_id=turn_id,
                        tts_stream_id=tts_result.tts_stream_id,
                        speech_request_id=speech_request.speech_request_id,
                        error_code="streaming_playback_no_result",
                        error_message="Playback stream did not return a terminal result.",
                    )
            else:
                live_result = VoiceLivePlaybackResult(
                    ok=False,
                    playback_stream_id=live_session.playback_stream_id,
                    playback_request_id=live_session.playback_request_id,
                    provider=live_session.provider,
                    device=live_session.device,
                    audio_format=live_session.audio_format,
                    status=live_session.status,
                    session_id=session_id,
                    turn_id=turn_id,
                    tts_stream_id=tts_result.tts_stream_id,
                    speech_request_id=speech_request.speech_request_id,
                    started_at=live_session.started_at,
                    error_code=live_session.error_code,
                    error_message=live_session.error_message,
                )
            self.last_live_playback_result = live_result
            terminal_event = (
                VoiceEventType.PLAYBACK_STREAM_COMPLETED
                if live_result.ok and live_result.status == "completed"
                else VoiceEventType.PLAYBACK_STREAM_FAILED
            )
            self._publish(
                terminal_event,
                message="Voice playback stream completed."
                if terminal_event == VoiceEventType.PLAYBACK_STREAM_COMPLETED
                else "Voice playback stream ended without completed playback.",
                session_id=session_id,
                turn_id=turn_id,
                speech_request_id=speech_request.speech_request_id,
                playback_request_id=live_result.playback_request_id,
                playback_id=live_result.playback_stream_id,
                provider=live_result.provider,
                device=live_result.device,
                format=live_result.audio_format,
                status=live_result.status,
                error_code=live_result.error_code,
                metadata={"playback_stream_result": live_result.to_dict()},
            )

        if playback_started_ms is None and live_result is not None:
            playback_started_ms = first_chunk_ms if first_chunk_ms is not None else None
        first_audio_available = playback_started_ms is not None
        core_completed = int(max(0.0, float(core_result_completed_ms or 0.0)))
        request_started = int(max(0.0, float(request_started_ms or 0.0)))
        latency = VoiceFirstAudioLatency(
            core_result_to_tts_start_ms=max(0, tts_started_ms - core_completed),
            tts_start_to_first_chunk_ms=(
                max(0, (first_chunk_ms or 0) - tts_started_ms)
                if first_chunk_ms is not None
                else None
            ),
            first_chunk_to_playback_start_ms=(
                max(0, (playback_started_ms or 0) - (first_chunk_ms or 0))
                if first_chunk_ms is not None and playback_started_ms is not None
                else None
            ),
            core_result_to_first_audio_ms=(
                max(0, playback_started_ms - core_completed)
                if playback_started_ms is not None
                else None
            ),
            request_to_first_audio_ms=(
                max(0, playback_started_ms - request_started)
                if playback_started_ms is not None
                else None
            ),
            streaming_enabled=True,
            streaming_transport_kind=tts_result.streaming_transport_kind,
            first_chunk_before_complete=tts_result.first_chunk_before_complete,
            stream_complete_ms=tts_result.stream_complete_ms,
            playback_complete_ms=None,
            live_format=streaming_request.live_format,
            artifact_format=streaming_request.artifact_format,
            fallback_used=bool(tts_result.fallback_used),
            prewarm_used=self.last_voice_output_prewarm_result is not None,
            prewarm_ms=(
                self.last_voice_output_prewarm_result.prewarm_ms
                if self.last_voice_output_prewarm_result is not None
                else None
            ),
            playback_prewarmed=bool(
                self.last_playback_prewarm_result
                and self.last_playback_prewarm_result.ok
            ),
            provider_prewarmed=bool(
                self.last_provider_prewarm_result and self.last_provider_prewarm_result.ok
            ),
            first_audio_available=first_audio_available,
            first_audio_budget_exceeded=bool(
                playback_started_ms is not None
                and max(0, playback_started_ms - request_started) > 3000
            ),
            partial_playback=bool(
                live_result is not None
                and (live_result.partial_playback or live_result.status == "cancelled")
            ),
            voice_stream_used_by_normal_path=normal_path_stream,
            user_heard_claimed=False,
        )
        self.last_first_audio_latency = latency
        self._publish(
            VoiceEventType.TTS_STREAM_COMPLETED
            if tts_result.ok
            else VoiceEventType.SYNTHESIS_FAILED,
            message="Voice streaming TTS completed."
            if tts_result.ok
            else "Voice streaming TTS failed.",
            session_id=session_id,
            turn_id=turn_id,
            speech_request_id=speech_request.speech_request_id,
            provider=tts_result.provider,
            model=tts_result.model,
            voice=tts_result.voice,
            format=tts_result.live_format,
            source=source,
            status=tts_result.status,
            error_code=tts_result.error_code,
            metadata={"streaming_tts_result": tts_result.to_dict()},
        )
        return VoiceStreamingSpeechOutputResult(
            ok=bool(tts_result.ok and live_result is not None and live_result.ok),
            status=(
                "completed"
                if tts_result.ok and live_result is not None and live_result.ok
                else live_result.status
                if live_result is not None
                else tts_result.status
            ),
            speech_request_id=speech_request.speech_request_id,
            session_id=session_id,
            turn_id=turn_id,
            streaming_enabled=True,
            first_audio_available=first_audio_available,
            streaming_transport_kind=tts_result.streaming_transport_kind,
            first_chunk_before_complete=tts_result.first_chunk_before_complete,
            stream_used_by_normal_path=normal_path_stream,
            streaming_miss_reason=""
            if first_audio_available
            else (live_result.error_code if live_result is not None else tts_result.error_code)
            or "first_audio_unavailable",
            tts_result=tts_result,
            playback_result=live_result,
            latency=latency,
            fallback_used=bool(tts_result.fallback_used),
            partial_playback=latency.partial_playback,
            error_code=(live_result.error_code if live_result is not None else None)
            or tts_result.error_code,
            error_message=(live_result.error_message if live_result is not None else None)
            or tts_result.error_message,
            metadata={
                "live_playback_requested": live_request.to_metadata()
                if live_request is not None
                else None,
                "core_result_id": core_result_id,
            },
        )

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
            resolved_session_id = (
                resolved_session_id or synthesis.speech_request.session_id
            )
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
                session_id=session_id
                or (
                    turn_result.turn.session_id
                    if turn_result.turn is not None
                    else None
                ),
                turn_id=turn_result.turn.turn_id
                if turn_result.turn is not None
                else None,
                metadata=metadata,
                blocked_reason="synthesis_required",
            )
            return await self.playback_request(request)
        synthesis = await self.synthesize_turn_response(
            turn_result, session_id=session_id, metadata=metadata
        )
        return await self.play_speech_output(
            synthesis,
            session_id=session_id,
            turn_id=turn_result.turn.turn_id if turn_result.turn is not None else None,
            metadata=metadata,
        )

    async def playback_request(
        self, request: VoicePlaybackRequest
    ) -> VoicePlaybackResult:
        block_reason = self._playback_request_block_reason(request)
        if block_reason is not None:
            blocked_request = replace(
                request, allowed_to_play=False, blocked_reason=block_reason
            )
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
            if block_reason in {"current_response_suppressed", "spoken_output_muted"}:
                self._publish(
                    VoiceEventType.SPEECH_SUPPRESSED,
                    message=f"Voice playback suppressed: {block_reason}.",
                    session_id=blocked_request.session_id,
                    turn_id=blocked_request.turn_id,
                    playback_request_id=blocked_request.playback_request_id,
                    audio_output_id=blocked_request.audio_output_id,
                    synthesis_id=blocked_request.synthesis_id,
                    provider=blocked_request.provider,
                    device=blocked_request.device,
                    mode=self.config.mode,
                    source=blocked_request.source,
                    status="suppressed",
                    error_code=block_reason,
                    spoken_output_suppressed=True,
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
            self._publish_playback_terminal(
                VoiceEventType.PLAYBACK_COMPLETED, result, "Voice playback completed."
            )
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
        elif result.status == "stopped":
            self._publish_playback_terminal(
                VoiceEventType.PLAYBACK_STOPPED, result, "Voice playback stopped."
            )
            self._cleanup_transient_playback_audio(allowed_request)
            self._transition_from_speaking(completed=False)
        elif result.status == "blocked":
            self._publish_playback_terminal(
                VoiceEventType.PLAYBACK_BLOCKED, result, "Voice playback blocked."
            )
            self._transition_from_speaking(completed=False)
        else:
            self._publish_playback_terminal(
                VoiceEventType.PLAYBACK_FAILED, result, "Voice playback failed."
            )
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

        if result.status in {"stopped", "cancelled"}:
            self._publish_playback_terminal(
                VoiceEventType.PLAYBACK_STOPPED, result, "Voice playback stopped."
            )
            self._transition_from_speaking(stopped=True)
        else:
            self._publish_playback_terminal(
                VoiceEventType.PLAYBACK_FAILED,
                result,
                "Voice playback stop request found no active playback.",
            )
        return self._remember_playback_result(result)

    def classify_voice_interruption(
        self,
        transcript: str,
        *,
        source: str = "manual_voice",
        session_id: str | None = None,
        turn_id: str | None = None,
        listen_window_id: str | None = None,
        capture_id: str | None = None,
        realtime_session_id: str | None = None,
        playback_id: str | None = None,
        pending_confirmation_id: str | None = None,
        active_loop_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> VoiceInterruptionClassification:
        normalized = self._normalize_confirmation_phrase(transcript)
        active_playback = self._active_playback()
        active_capture = self._active_capture()
        active_listen = self.get_active_post_wake_listen_window()
        active_realtime = self.get_active_realtime_session()
        context_used = {
            "active_output": bool(
                (active_playback is not None and active_playback.status in {"started", "playing"})
                or playback_id
            ),
            "active_capture": bool(active_capture is not None or capture_id),
            "active_listen_window": bool(active_listen is not None or listen_window_id),
            "active_realtime_session": bool(
                active_realtime is not None or realtime_session_id
            ),
            "pending_confirmation": bool(pending_confirmation_id),
            "active_loop": bool(active_loop_id or self.active_wake_supervised_loop_id),
        }
        context_used.update(dict(context or {}))

        intent = VoiceInterruptionIntent.UNCLEAR
        family: str | None = "unclear"
        confidence = 0.25
        ambiguity_reason: str | None = None
        unsafe_reason: str | None = None

        if not normalized:
            ambiguity_reason = "empty_interruption_phrase"
        elif normalized in _MUTE_OUTPUT_PHRASES:
            intent = VoiceInterruptionIntent.MUTE_SPOKEN_OUTPUT
            family = "output_mute"
            confidence = 0.95
        elif normalized in _UNMUTE_OUTPUT_PHRASES:
            intent = VoiceInterruptionIntent.UNMUTE_SPOKEN_OUTPUT
            family = "output_unmute"
            confidence = 0.95
        elif normalized in _OUTPUT_STOP_PHRASES:
            intent = VoiceInterruptionIntent.STOP_OUTPUT_ONLY
            family = "output_stop"
            confidence = 0.95
        elif normalized in _SHOW_PLAN_PHRASES:
            intent = VoiceInterruptionIntent.SHOW_PLAN
            family = "show_plan"
            confidence = 0.9
        elif normalized in _REPEAT_PROMPT_PHRASES:
            intent = VoiceInterruptionIntent.REPEAT_PROMPT
            family = "repeat_prompt"
            confidence = 0.9
        elif normalized in _WAIT_PHRASES:
            intent = VoiceInterruptionIntent.WAIT
            family = "wait"
            confidence = 0.85
        elif normalized in _CORE_CANCEL_PHRASES:
            intent = VoiceInterruptionIntent.CORE_ROUTED_CANCEL_REQUEST
            family = "core_routed_cancel"
            confidence = 0.9
        elif (
            normalized in _REJECT_PHRASES
            or normalized in _CANCEL_CONFIRMATION_PHRASES
            or normalized == "cancel that"
        ) and context_used.get("pending_confirmation"):
            intent = (
                VoiceInterruptionIntent.REJECT_PENDING_CONFIRMATION
                if normalized in _REJECT_PHRASES
                else VoiceInterruptionIntent.CANCEL_PENDING_CONFIRMATION
            )
            family = "pending_confirmation_rejection"
            confidence = 0.9
        elif normalized in _CAPTURE_CANCEL_PHRASES or normalized in {
            "never mind",
            "nevermind",
            "cancel",
        }:
            if context_used.get("active_listen_window"):
                intent = VoiceInterruptionIntent.CANCEL_LISTEN_WINDOW
                family = "listen_cancel"
                confidence = 0.9
            elif context_used.get("active_realtime_session"):
                intent = VoiceInterruptionIntent.CANCEL_LISTEN_WINDOW
                family = "realtime_transcription_cancel"
                confidence = 0.85
            elif context_used.get("active_capture"):
                intent = VoiceInterruptionIntent.CANCEL_CAPTURE
                family = "capture_cancel"
                confidence = 0.9
            else:
                intent = VoiceInterruptionIntent.UNCLEAR
                family = "context_required_cancel"
                confidence = 0.35
                ambiguity_reason = "cancel_phrase_without_active_capture_or_listen"
        elif any(
            normalized == prefix or normalized.startswith(prefix + " ")
            for prefix in _CORRECTION_PREFIXES
        ) or normalized.startswith("no i meant ") or normalized.startswith("no, i meant "):
            intent = VoiceInterruptionIntent.CORRECTION
            family = "correction"
            confidence = 0.85
        elif normalized.startswith("cancel ") or normalized.startswith("stop "):
            intent = VoiceInterruptionIntent.CORE_ROUTED_CANCEL_REQUEST
            family = "core_routed_cancel"
            confidence = 0.65
            unsafe_reason = "voice_layer_must_route_task_cancellation_through_core"
        else:
            ambiguity_reason = "unsupported_or_ambiguous_interruption_phrase"

        result = VoiceInterruptionClassification(
            transcript=transcript,
            normalized_phrase=normalized,
            intent=intent,
            confidence=confidence,
            source=source,
            session_id=session_id,
            turn_id=turn_id,
            listen_window_id=listen_window_id,
            capture_id=capture_id,
            realtime_session_id=realtime_session_id,
            playback_id=playback_id,
            pending_confirmation_id=pending_confirmation_id,
            active_loop_id=active_loop_id,
            matched_phrase_family=family,
            context_used=context_used,
            ambiguity_reason=ambiguity_reason,
            unsafe_reason=unsafe_reason,
        )
        self.last_interruption_classification = result
        return result

    async def handle_voice_interruption(
        self, request: VoiceInterruptionRequest
    ) -> VoiceInterruptionResult:
        request = replace(request, allowed_to_interrupt=True, blocked_reason=None)
        transcript = request.transcript or request.normalized_phrase or ""
        classification = self.classify_voice_interruption(
            transcript,
            source=request.source,
            session_id=request.session_id,
            turn_id=request.turn_id,
            listen_window_id=request.listen_window_id,
            capture_id=request.capture_id,
            realtime_session_id=request.realtime_session_id,
            playback_id=request.playback_id,
            pending_confirmation_id=request.pending_confirmation_id,
            active_loop_id=request.active_loop_id,
            context=request.metadata.get("interruption_context")
            if isinstance(request.metadata.get("interruption_context"), dict)
            else None,
        )
        if request.intent not in {
            VoiceInterruptionIntent.UNKNOWN,
            VoiceInterruptionIntent.NONE,
        }:
            classification = replace(classification, intent=request.intent)
            self.last_interruption_classification = classification
        request = replace(
            request,
            intent=classification.intent,
            normalized_phrase=classification.normalized_phrase,
        )
        self.last_interruption_request = request
        self._publish_interruption_trace_event(
            VoiceEventType.INTERRUPTION_RECEIVED,
            request,
            classification=classification,
            status="received",
            message="Voice interruption received.",
        )
        self._publish_interruption_trace_event(
            VoiceEventType.INTERRUPTION_CLASSIFIED,
            request,
            classification=classification,
            status=classification.intent.value,
            message="Voice interruption classified.",
        )
        if (
            classification.context_used.get("active_output")
            or classification.context_used.get("active_capture")
            or classification.context_used.get("active_realtime_session")
        ):
            self._publish_interruption_trace_event(
                VoiceEventType.BARGE_IN_DETECTED,
                request,
                classification=classification,
                status=classification.intent.value,
                message="Voice barge-in candidate detected.",
            )

        if classification.intent in {
            VoiceInterruptionIntent.STOP_OUTPUT_ONLY,
            VoiceInterruptionIntent.STOP_PLAYBACK,
            VoiceInterruptionIntent.STOP_SPEAKING,
            VoiceInterruptionIntent.MUTE_SPOKEN_OUTPUT,
            VoiceInterruptionIntent.UNMUTE_SPOKEN_OUTPUT,
            VoiceInterruptionIntent.MUTE_SPOKEN_RESPONSES,
            VoiceInterruptionIntent.UNMUTE_SPOKEN_RESPONSES,
            VoiceInterruptionIntent.CANCEL_CAPTURE,
            VoiceInterruptionIntent.CANCEL_LISTEN_WINDOW,
        }:
            result = await self.interrupt_voice_output(request)
            result = replace(result, classification_id=classification.classification_id)
            self.last_interruption_result = result
            if result.output_stopped:
                self._publish_interruption_trace_event(
                    VoiceEventType.OUTPUT_INTERRUPTED,
                    request,
                    classification=classification,
                    result=result,
                    status=result.status,
                    message="Voice output interrupted.",
                )
            if result.capture_cancelled:
                self._publish_interruption_trace_event(
                    VoiceEventType.CAPTURE_INTERRUPTED,
                    request,
                    classification=classification,
                    result=result,
                    status=result.status,
                    message="Voice capture interrupted.",
                )
            if result.listen_window_cancelled:
                self._publish_interruption_trace_event(
                    VoiceEventType.LISTEN_WINDOW_INTERRUPTED,
                    request,
                    classification=classification,
                    result=result,
                    status=result.status,
                    message="Post-wake listen window interrupted.",
                )
            return result

        if classification.intent in {
            VoiceInterruptionIntent.REJECT_PENDING_CONFIRMATION,
            VoiceInterruptionIntent.CANCEL_PENDING_CONFIRMATION,
            VoiceInterruptionIntent.CANCEL_PENDING_PROMPT,
            VoiceInterruptionIntent.SHOW_PLAN,
            VoiceInterruptionIntent.REPEAT_PROMPT,
            VoiceInterruptionIntent.WAIT,
        }:
            result = await self._handle_confirmation_interruption(request, classification)
            return self._remember_interruption_result(request, result)

        if classification.intent in {
            VoiceInterruptionIntent.CORE_ROUTED_CANCEL_REQUEST,
            VoiceInterruptionIntent.CORRECTION,
            VoiceInterruptionIntent.NEW_REQUEST,
        }:
            result = await self._route_interruption_through_core(request, classification)
            return self._remember_interruption_result(request, result)

        result = VoiceInterruptionResult(
            ok=False,
            interruption_id=request.interruption_id,
            classification_id=classification.classification_id,
            intent=classification.intent,
            status="ambiguous",
            error_code="ambiguous_interruption",
            error_message=classification.ambiguity_reason
            or "Voice interruption phrase was ambiguous.",
            reason=classification.ambiguity_reason or "ambiguous_interruption",
            user_message="I need a clearer instruction.",
        )
        return self._remember_interruption_result(request, result)

    async def _handle_confirmation_interruption(
        self,
        request: VoiceInterruptionRequest,
        classification: VoiceInterruptionClassification,
    ) -> VoiceInterruptionResult:
        confirmation_result = await self.handle_spoken_confirmation(
            VoiceSpokenConfirmationRequest(
                transcript=request.transcript or classification.transcript,
                normalized_phrase=classification.normalized_phrase,
                session_id=request.session_id or "default",
                turn_id=request.turn_id,
                source=request.source,
                pending_confirmation_id=request.pending_confirmation_id,
                task_id=str(request.metadata.get("task_id") or "") or None,
                route_family=str(request.metadata.get("route_family") or "") or None,
                metadata=dict(request.metadata),
            )
        )
        rejected = confirmation_result.status in {"rejected", "cancelled"}
        status = (
            "completed"
            if confirmation_result.status not in {"unsupported", "no_pending_confirmation"}
            else confirmation_result.status
        )
        result = VoiceInterruptionResult(
            ok=confirmation_result.ok,
            interruption_id=request.interruption_id,
            classification_id=classification.classification_id,
            intent=classification.intent,
            status=status,
            affected_confirmation_id=confirmation_result.pending_confirmation_id,
            confirmation_rejected=rejected,
            core_task_cancelled=False,
            core_result_mutated=False,
            action_executed=False,
            reason=confirmation_result.reason,
            user_message=confirmation_result.user_message,
            spoken_response_candidate=confirmation_result.spoken_response_candidate,
            error_code=confirmation_result.error_code,
            metadata={
                "spoken_confirmation_result": confirmation_result.to_dict(),
                "listen_window_id": request.listen_window_id,
                "listen_window_is_provenance_not_authority": bool(request.listen_window_id),
            },
        )
        self._publish_interruption_trace_event(
            VoiceEventType.CONFIRMATION_INTERRUPTED,
            request,
            classification=classification,
            result=result,
            status=result.status,
            message="Pending confirmation handled through spoken confirmation.",
        )
        return result

    async def _route_interruption_through_core(
        self,
        request: VoiceInterruptionRequest,
        classification: VoiceInterruptionClassification,
    ) -> VoiceInterruptionResult:
        phrase = request.transcript or classification.transcript
        metadata = dict(request.metadata)
        metadata["voice_interruption"] = classification.to_dict()
        metadata["interruption_request_id"] = request.interruption_id
        if request.listen_window_id:
            metadata["listen_window_id"] = request.listen_window_id
        if request.active_loop_id:
            metadata["active_loop_id"] = request.active_loop_id
        route_event = (
            VoiceEventType.CORE_CANCELLATION_REQUESTED
            if classification.intent == VoiceInterruptionIntent.CORE_ROUTED_CANCEL_REQUEST
            else VoiceEventType.CORRECTION_ROUTED
        )
        self._publish_interruption_trace_event(
            route_event,
            request,
            classification=classification,
            status="routed_to_core",
            message="Voice interruption routed through Core.",
        )
        turn_result = await self.submit_manual_voice_turn(
            phrase,
            mode="ghost",
            session_id=request.session_id,
            metadata=metadata,
            interrupt_intent=classification.intent.value,
        )
        core_request_id = (
            turn_result.core_request.request_id
            if turn_result.core_request is not None
            else None
        )
        status = "routed_to_core" if turn_result.core_request is not None else "unsupported"
        error_code = turn_result.error_code if not turn_result.ok else None
        return VoiceInterruptionResult(
            ok=turn_result.core_request is not None,
            interruption_id=request.interruption_id,
            classification_id=classification.classification_id,
            intent=classification.intent,
            status=status,
            core_request_id=core_request_id,
            core_task_cancelled=False,
            core_result_mutated=False,
            action_executed=False,
            routed_as_new_request=classification.intent == VoiceInterruptionIntent.NEW_REQUEST,
            routed_as_correction=classification.intent == VoiceInterruptionIntent.CORRECTION,
            reason="routed_through_core" if turn_result.core_request is not None else "core_route_unavailable",
            user_message="I routed that cancellation through Core."
            if classification.intent == VoiceInterruptionIntent.CORE_ROUTED_CANCEL_REQUEST
            else "I routed that through Core.",
            error_code=error_code,
            error_message=turn_result.error_message if not turn_result.ok else None,
            metadata={
                "voice_turn_result": turn_result.to_dict(),
                "core_cancellation_requested": classification.intent
                == VoiceInterruptionIntent.CORE_ROUTED_CANCEL_REQUEST,
                "voice_layer_did_not_cancel_task": True,
            },
        )

    async def interrupt_voice_output(
        self, request: VoiceInterruptionRequest
    ) -> VoiceInterruptionResult:
        request = replace(request, allowed_to_interrupt=True, blocked_reason=None)
        self.last_interruption_request = request
        self._publish_interruption_event(
            VoiceEventType.INTERRUPTION_REQUESTED,
            request,
            status="requested",
            message="Voice interruption requested.",
        )

        if request.intent in {
            VoiceInterruptionIntent.STOP_OUTPUT_ONLY,
            VoiceInterruptionIntent.STOP_PLAYBACK,
            VoiceInterruptionIntent.STOP_SPEAKING,
        }:
            playback_result = await self.stop_playback(
                request.playback_id, reason=request.reason
            )
            if playback_result.status in {"stopped", "cancelled"}:
                result = VoiceInterruptionResult(
                    ok=True,
                    interruption_id=request.interruption_id,
                    intent=request.intent,
                    status="completed",
                    playback_result=playback_result,
                    affected_playback_id=playback_result.playback_id,
                    spoken_output_suppressed=True,
                    output_stopped=True,
                    reason=request.reason,
                    user_message="Playback stopped.",
                )
            elif playback_result.error_code == "no_active_playback":
                no_active_status = (
                    "no_active_output"
                    if request.intent == VoiceInterruptionIntent.STOP_OUTPUT_ONLY
                    else "no_active_playback"
                )
                result = VoiceInterruptionResult(
                    ok=False,
                    interruption_id=request.interruption_id,
                    intent=request.intent,
                    status=no_active_status,
                    playback_result=playback_result,
                    error_code="no_active_playback",
                    error_message="No active playback exists.",
                    spoken_output_suppressed=False,
                    reason="no_active_output",
                    user_message="No active voice output.",
                )
            else:
                result = VoiceInterruptionResult(
                    ok=False,
                    interruption_id=request.interruption_id,
                    intent=request.intent,
                    status=playback_result.status or "failed",
                    playback_result=playback_result,
                    affected_playback_id=playback_result.playback_id,
                    error_code=playback_result.error_code,
                    error_message=playback_result.error_message,
                    spoken_output_suppressed=False,
                    reason=playback_result.error_code or playback_result.status,
                )
            return self._remember_interruption_result(request, result)

        if request.intent == VoiceInterruptionIntent.SUPPRESS_CURRENT_RESPONSE:
            self.current_response_suppressed = True
            self.suppressed_turn_id = request.turn_id
            self.suppressed_reason = request.reason
            result = VoiceInterruptionResult(
                ok=True,
                interruption_id=request.interruption_id,
                intent=request.intent,
                status="completed",
                spoken_output_suppressed=True,
                metadata={"turn_id": request.turn_id},
            )
            self._publish_interruption_event(
                VoiceEventType.SPEECH_SUPPRESSED,
                request,
                result=result,
                status=result.status,
                message="Voice speech output suppressed for current response.",
            )
            return self._remember_interruption_result(request, result)

        if request.intent in {
            VoiceInterruptionIntent.MUTE_SPOKEN_OUTPUT,
            VoiceInterruptionIntent.MUTE_SPOKEN_RESPONSES,
            VoiceInterruptionIntent.UNMUTE_SPOKEN_OUTPUT,
            VoiceInterruptionIntent.UNMUTE_SPOKEN_RESPONSES,
        }:
            muted = request.intent in {
                VoiceInterruptionIntent.MUTE_SPOKEN_OUTPUT,
                VoiceInterruptionIntent.MUTE_SPOKEN_RESPONSES,
            }
            self.spoken_output_muted = muted
            self.muted_scope = request.muted_scope or "session" if muted else None
            self.muted_reason = request.reason if muted else None
            self.muted_since = self._now() if muted else None
            result = VoiceInterruptionResult(
                ok=True,
                interruption_id=request.interruption_id,
                intent=request.intent,
                status="completed",
                spoken_output_suppressed=muted,
                muted_scope=request.muted_scope or "session",
                muted=muted,
                reason=request.reason,
                user_message="Voice speech output muted."
                if muted
                else "Voice speech output unmuted.",
            )
            self._publish_interruption_event(
                VoiceEventType.SPOKEN_OUTPUT_MUTED
                if muted
                else VoiceEventType.SPOKEN_OUTPUT_UNMUTED,
                request,
                result=result,
                status=result.status,
                message="Voice speech output muted."
                if muted
                else "Voice speech output unmuted.",
            )
            return self._remember_interruption_result(request, result)

        if request.intent == VoiceInterruptionIntent.CANCEL_CAPTURE:
            capture_result = await self.cancel_capture(
                request.capture_id, reason=request.reason or "user_cancelled"
            )
            result = VoiceInterruptionResult(
                ok=capture_result.status == "cancelled",
                interruption_id=request.interruption_id,
                intent=request.intent,
                status="completed"
                if capture_result.status == "cancelled"
                else capture_result.status,
                capture_result=capture_result,
                affected_capture_id=capture_result.capture_id,
                error_code=capture_result.error_code,
                error_message=capture_result.error_message,
                capture_cancelled=capture_result.status == "cancelled",
                reason=request.reason or "user_cancelled",
                user_message="Capture cancelled."
                if capture_result.status == "cancelled"
                else "No active capture.",
            )
            return self._remember_interruption_result(request, result)

        if request.intent == VoiceInterruptionIntent.CANCEL_LISTEN_WINDOW:
            active_window = (
                self._post_wake_listen_window_for_id(request.listen_window_id)
                if request.listen_window_id
                else self.get_active_post_wake_listen_window()
            )
            active_realtime = (
                self.realtime_sessions.get(request.realtime_session_id)
                if request.realtime_session_id
                else self.get_active_realtime_session()
            )
            if active_window is None:
                if active_realtime is not None:
                    cancelled_realtime = await self.cancel_realtime_session(
                        active_realtime.realtime_session_id
                    )
                    result = VoiceInterruptionResult(
                        ok=cancelled_realtime.status == "cancelled",
                        interruption_id=request.interruption_id,
                        intent=request.intent,
                        status="completed"
                        if cancelled_realtime.status == "cancelled"
                        else cancelled_realtime.status,
                        affected_realtime_session_id=cancelled_realtime.realtime_session_id,
                        realtime_session_cancelled=cancelled_realtime.status
                        == "cancelled",
                        core_task_cancelled=False,
                        core_result_mutated=False,
                        action_executed=False,
                        reason=request.reason or "user_cancelled",
                        user_message="Realtime transcription session cancelled.",
                    )
                    return self._remember_interruption_result(request, result)
                result = VoiceInterruptionResult(
                    ok=False,
                    interruption_id=request.interruption_id,
                    intent=request.intent,
                    status="no_active_listen_window",
                    error_code="no_active_listen_window",
                    error_message="No active post-wake listen window exists.",
                    reason="no_active_listen_window",
                    user_message="No active request window.",
                )
                return self._remember_interruption_result(request, result)
            cancelled = await self.cancel_post_wake_listen_window(
                active_window.listen_window_id,
                reason=request.reason or "user_cancelled",
            )
            cancelled_realtime = (
                await self.cancel_realtime_session(active_realtime.realtime_session_id)
                if active_realtime is not None
                else None
            )
            result = VoiceInterruptionResult(
                ok=cancelled.status == "cancelled",
                interruption_id=request.interruption_id,
                intent=request.intent,
                status="completed" if cancelled.status == "cancelled" else cancelled.status,
                affected_listen_window_id=cancelled.listen_window_id,
                affected_capture_id=cancelled.capture_id,
                affected_realtime_session_id=cancelled_realtime.realtime_session_id
                if cancelled_realtime is not None
                else None,
                listen_window_cancelled=cancelled.status == "cancelled",
                capture_cancelled=bool(cancelled.capture_id),
                realtime_session_cancelled=bool(
                    cancelled_realtime is not None
                    and cancelled_realtime.status == "cancelled"
                ),
                reason=request.reason or "user_cancelled",
                user_message="Request cancelled."
                if cancelled.status == "cancelled"
                else "Request window was not cancelled.",
            )
            return self._remember_interruption_result(request, result)

        result = VoiceInterruptionResult(
            ok=False,
            interruption_id=request.interruption_id,
            intent=request.intent,
            status="unsupported",
            error_code="unsupported_interruption_intent",
            error_message="Voice interruption intent is not supported.",
            spoken_output_suppressed=False,
            reason="unsupported_interruption_intent",
        )
        return self._remember_interruption_result(request, result)

    async def stop_speaking(
        self,
        *,
        session_id: str | None = None,
        playback_id: str | None = None,
        reason: str = "user_requested",
    ) -> VoiceInterruptionResult:
        return await self.interrupt_voice_output(
            VoiceInterruptionRequest(
                intent=VoiceInterruptionIntent.STOP_SPEAKING,
                source="api",
                session_id=session_id,
                playback_id=playback_id,
                reason=reason,
            )
        )

    async def suppress_current_response(
        self,
        *,
        turn_id: str | None = None,
        reason: str = "user_requested",
        session_id: str | None = None,
    ) -> VoiceInterruptionResult:
        return await self.interrupt_voice_output(
            VoiceInterruptionRequest(
                intent=VoiceInterruptionIntent.SUPPRESS_CURRENT_RESPONSE,
                source="api",
                session_id=session_id,
                turn_id=turn_id,
                reason=reason,
            )
        )

    async def set_spoken_output_muted(
        self,
        muted: bool,
        *,
        scope: str = "session",
        reason: str = "user_requested",
        session_id: str | None = None,
    ) -> VoiceInterruptionResult:
        return await self.interrupt_voice_output(
            VoiceInterruptionRequest(
                intent=VoiceInterruptionIntent.MUTE_SPOKEN_RESPONSES
                if muted
                else VoiceInterruptionIntent.UNMUTE_SPOKEN_RESPONSES,
                source="api",
                session_id=session_id,
                reason=reason,
                muted_scope=scope,
            )
        )

    def runtime_mode_readiness_report(self) -> VoiceRuntimeModeReadiness:
        selected_mode = self._runtime_mode_name(self.config.mode)
        effective_mode = "disabled" if not self.config.enabled else selected_mode
        availability = self.availability
        capture_availability = self._capture_provider_availability()
        playback_availability = self._playback_provider_availability()
        wake_availability = self._wake_provider_availability()
        vad_availability = self._vad_provider_availability()
        realtime_availability = self._realtime_provider_availability()

        voice_available = bool(availability.available)
        tts_available = bool(
            self.config.enabled
            and self.openai_config.enabled
            and bool(self.openai_config.api_key)
            and availability.tts_allowed
            and self.config.spoken_responses_enabled
        )
        stt_available = bool(
            self.config.enabled
            and self.openai_config.enabled
            and bool(self.openai_config.api_key)
            and availability.stt_allowed
        )
        live_playback_available = bool(
            self.config.playback.enabled and playback_availability.get("available")
        )
        capture_available = bool(
            self.config.capture.enabled and capture_availability.get("available")
        )
        wake_available = bool(
            self.config.wake.enabled and wake_availability.get("available")
        )
        post_wake_ready = bool(
            self.config.post_wake.enabled
            and self.config.post_wake.allow_dev_post_wake
            and self.config.wake.enabled
            and self.config.capture.enabled
        )
        vad_available = bool(self.config.vad.enabled and vad_availability.get("available"))
        realtime_available = bool(
            self.config.realtime.enabled and realtime_availability.get("available")
        )
        core_bridge_available = self.core_bridge is not None
        trust_confirmation_available = bool(self.config.confirmation.enabled)

        mode_requirements = self._runtime_mode_requirements(effective_mode)
        required_config_flags = list(mode_requirements["required_config_flags"])
        required_providers = list(mode_requirements["required_providers"])
        required_subcomponents = list(mode_requirements["required_subcomponents"])
        forbidden_subcomponents = list(mode_requirements["forbidden_subcomponents"])
        expected_posture = dict(mode_requirements["expected_subsystem_posture"])

        missing: list[str] = []
        blocking_reasons: list[str] = []
        warnings: list[str] = []
        contradictions: list[str] = []

        if effective_mode == "disabled":
            blocking_reasons.append("voice_disabled")
        elif not voice_available:
            blocking_reasons.append(
                availability.unavailable_reason or "voice_provider_unavailable"
            )
            missing.append("voice")

        if effective_mode == "output_only":
            if not self.config.spoken_responses_enabled:
                blocking_reasons.append("output_voice_configured_but_spoken_disabled")
                missing.append("spoken_responses")
            if not tts_available:
                blocking_reasons.append("output_voice_configured_but_tts_unavailable")
                missing.append("openai_tts")
            if not self.config.playback.enabled:
                blocking_reasons.append("output_voice_configured_but_playback_disabled")
                missing.append("live_playback")
            elif not live_playback_available:
                blocking_reasons.append(
                    "output_voice_configured_but_playback_unavailable"
                )
                missing.append("live_playback")
            if self.config.capture.enabled:
                contradictions.append("output_only_capture_should_be_disabled")
            if self.config.wake.enabled:
                contradictions.append("output_only_wake_should_be_disabled")
            if self.config.post_wake.enabled:
                contradictions.append("output_only_post_wake_should_be_disabled")
            if self.config.vad.enabled:
                contradictions.append("output_only_vad_should_be_disabled")
            if self.config.realtime.enabled:
                contradictions.append("output_only_realtime_should_be_disabled")

        elif effective_mode == "push_to_talk":
            if not stt_available:
                blocking_reasons.append("push_to_talk_stt_unavailable")
                missing.append("openai_stt")
            if not self.config.capture.enabled:
                blocking_reasons.append("push_to_talk_capture_disabled")
                missing.append("capture")
            elif not capture_available:
                blocking_reasons.append("push_to_talk_capture_unavailable")
                missing.append("capture")
            if self.config.wake.enabled:
                contradictions.append("push_to_talk_wake_should_be_disabled")
            if self.config.realtime.enabled:
                contradictions.append("push_to_talk_realtime_should_be_disabled")

        elif effective_mode == "wake_supervised":
            if not wake_available:
                blocking_reasons.append("wake_supervised_wake_unavailable")
                missing.append("wake")
            if not post_wake_ready:
                blocking_reasons.append("wake_supervised_post_wake_unavailable")
                missing.append("post_wake")
            if not capture_available:
                blocking_reasons.append("wake_supervised_capture_unavailable")
                missing.append("capture")
            if not stt_available:
                blocking_reasons.append("wake_supervised_stt_unavailable")
                missing.append("openai_stt")
            if not core_bridge_available:
                blocking_reasons.append("wake_supervised_core_bridge_unavailable")
                missing.append("core_bridge")

        elif effective_mode == "realtime_transcription":
            if self.config.realtime.mode != "transcription_bridge":
                blocking_reasons.append("realtime_transcription_mode_mismatch")
            if not realtime_available:
                blocking_reasons.append("realtime_transcription_provider_unavailable")
                missing.append("realtime")
            if not core_bridge_available:
                blocking_reasons.append("realtime_transcription_core_bridge_unavailable")
                missing.append("core_bridge")
            if self.config.realtime.direct_tools_allowed:
                blocking_reasons.append("realtime_direct_tools_forbidden")

        elif effective_mode == "realtime_speech_core_bridge":
            if self.config.realtime.mode != "speech_to_speech_core_bridge":
                blocking_reasons.append("realtime_speech_mode_mismatch")
            if not self.config.realtime.speech_to_speech_enabled:
                blocking_reasons.append("realtime_speech_disabled")
                missing.append("speech_to_speech")
            if not self.config.realtime.audio_output_from_realtime:
                blocking_reasons.append("realtime_speech_audio_output_disabled")
                missing.append("realtime_audio_output")
            if not realtime_available:
                blocking_reasons.append("realtime_speech_provider_unavailable")
                missing.append("realtime")
            if not core_bridge_available:
                blocking_reasons.append("realtime_speech_core_bridge_unavailable")
                missing.append("core_bridge")
            if self.config.realtime.direct_tools_allowed:
                blocking_reasons.append("realtime_direct_tools_forbidden")

        elif effective_mode == "manual_only":
            if not self.config.manual_input_enabled:
                blocking_reasons.append("manual_input_disabled")
                missing.append("manual_input")
            if not voice_available:
                missing.append("voice")

        else:
            blocking_reasons.append("unsupported_voice_mode")

        if contradictions and not blocking_reasons:
            warnings.extend(contradictions)
        missing = self._dedupe_strings(missing)
        blocking_reasons = self._dedupe_strings(blocking_reasons)
        warnings = self._dedupe_strings(warnings)
        contradictions = self._dedupe_strings(contradictions)

        if effective_mode == "disabled":
            status = "disabled"
        elif blocking_reasons:
            status = "blocked"
        elif warnings:
            status = "degraded"
        else:
            status = "ready"

        provider_availability = {
            "voice": {
                "configured": bool(availability.provider_configured),
                "enabled": bool(self.config.enabled),
                "available": voice_available,
                "active": self.state_controller.snapshot().state.value != "disabled",
                "mocked": bool(availability.mock_provider_active),
                "unavailable_reason": availability.unavailable_reason,
                "blocked_by_config": not self.config.enabled,
                "blocked_by_missing_provider": not bool(availability.provider_configured),
            },
            "tts": {
                "configured": bool(self.openai_config.enabled),
                "enabled": bool(self.config.spoken_responses_enabled),
                "available": tts_available,
                "active": bool(self.last_synthesis_result),
                "mocked": bool(getattr(self.provider, "is_mock", False)),
                "unavailable_reason": None if tts_available else self._tts_unavailable_reason(),
                "blocked_by_config": not self.config.spoken_responses_enabled,
                "blocked_by_missing_provider": not self.openai_config.enabled
                or not bool(self.openai_config.api_key),
            },
            "stt": {
                "configured": bool(self.openai_config.enabled),
                "enabled": bool(self.config.enabled),
                "available": stt_available,
                "active": False,
                "mocked": bool(getattr(self.provider, "is_mock", False)),
                "unavailable_reason": None if stt_available else self._stt_unavailable_reason(),
                "blocked_by_config": not self.config.enabled,
                "blocked_by_missing_provider": not self.openai_config.enabled
                or not bool(self.openai_config.api_key),
            },
            "playback": {
                **dict(playback_availability),
                "configured": bool(self.config.playback.provider),
                "enabled": bool(self.config.playback.enabled),
                "active": self._active_playback() is not None,
                "mocked": bool(getattr(self.playback_provider, "is_mock", False)),
                "blocked_by_config": not self.config.playback.enabled,
                "blocked_by_missing_provider": not bool(
                    playback_availability.get("available")
                )
                and bool(self.config.playback.enabled),
            },
            "capture": {
                **dict(capture_availability),
                "configured": bool(self.config.capture.provider),
                "enabled": bool(self.config.capture.enabled),
                "available": capture_available,
                "active": self._active_capture() is not None,
                "mocked": bool(getattr(self.capture_provider, "is_mock", False)),
                "blocked_by_config": not self.config.capture.enabled,
            },
            "wake": {
                **dict(wake_availability),
                "configured": bool(self.config.wake.provider),
                "enabled": bool(self.config.wake.enabled),
                "available": wake_available,
                "active": bool(self.wake_monitoring_active),
                "mocked": bool(getattr(self.wake_provider, "is_mock", False)),
                "blocked_by_config": not self.config.wake.enabled,
            },
            "vad": {
                **dict(vad_availability),
                "configured": bool(self.config.vad.provider),
                "enabled": bool(self.config.vad.enabled),
                "available": vad_available,
                "active": self.active_vad_session is not None,
                "mocked": bool(getattr(self.vad_provider, "is_mock", False)),
                "blocked_by_config": not self.config.vad.enabled,
            },
            "realtime": {
                **dict(realtime_availability),
                "configured": bool(self.config.realtime.provider),
                "enabled": bool(self.config.realtime.enabled),
                "available": realtime_available,
                "active": self.active_realtime_session is not None,
                "mocked": bool(getattr(self.realtime_provider, "is_mock", False)),
                "direct_tools_allowed": False,
                "direct_action_tools_exposed": False,
                "core_bridge_required": True,
                "blocked_by_config": not self.config.realtime.enabled,
            },
            "core_bridge": {
                "configured": self.core_bridge is not None,
                "enabled": True,
                "available": core_bridge_available,
                "active": False,
                "mocked": False,
                "unavailable_reason": None
                if core_bridge_available
                else "core_bridge_unavailable",
            },
            "trust_confirmation": {
                "configured": True,
                "enabled": bool(self.config.confirmation.enabled),
                "available": trust_confirmation_available,
                "active": False,
                "mocked": False,
                "unavailable_reason": None
                if trust_confirmation_available
                else "confirmation_disabled",
            },
        }

        return VoiceRuntimeModeReadiness(
            selected_mode=selected_mode,
            effective_mode=effective_mode,
            status=status,
            ready=status == "ready",
            degraded=status == "degraded",
            blocked=status == "blocked",
            disabled=status == "disabled",
            required_config_flags=required_config_flags,
            required_providers=required_providers,
            required_subcomponents=required_subcomponents,
            forbidden_subcomponents=forbidden_subcomponents,
            expected_subsystem_posture=expected_posture,
            missing_requirements=missing,
            contradictory_settings=contradictions,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            user_facing_summary=self._runtime_mode_user_summary(
                effective_mode, status, blocking_reasons, warnings
            ),
            next_fix=self._runtime_mode_next_fix(effective_mode, blocking_reasons),
            provider_availability=provider_availability,
            live_playback_available=live_playback_available,
            artifact_persistence_enabled=bool(self.config.openai.persist_tts_outputs),
            artifact_persistence_counts_as_live_playback=False,
            core_bridge_available=core_bridge_available,
            trust_confirmation_available=trust_confirmation_available,
            truth_flags={
                "command_authority": "stormhelm_core",
                "openai_voice_not_command_authority": True,
                "wake_detection_local_only": True,
                "cloud_wake_detection": False,
                "always_listening": False,
                "continuous_listening": False,
                "direct_realtime_tools_allowed": False,
                "direct_realtime_action_tools_exposed": False,
                "playback_does_not_claim_user_heard": True,
                "artifact_persistence_is_not_live_playback": True,
            },
        )

    def _runtime_mode_name(self, mode: str | None) -> str:
        normalized = str(mode or "disabled").strip().lower()
        aliases = {
            "manual": "manual_only",
            "manual_voice": "manual_only",
            "ptt": "push_to_talk",
            "wake": "wake_supervised",
            "wake_loop": "wake_supervised",
            "realtime": "realtime_transcription",
            "realtime_speech": "realtime_speech_core_bridge",
            "speech_to_speech_core_bridge": "realtime_speech_core_bridge",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized in {
            "disabled",
            "manual_only",
            "output_only",
            "push_to_talk",
            "wake_supervised",
            "realtime_transcription",
            "realtime_speech_core_bridge",
        }:
            return normalized
        return "unsupported"

    def _runtime_mode_requirements(self, mode: str) -> dict[str, Any]:
        base = {
            "required_config_flags": ["voice.enabled"],
            "required_providers": [],
            "required_subcomponents": ["voice"],
            "forbidden_subcomponents": [],
            "expected_subsystem_posture": {},
        }
        table: dict[str, dict[str, Any]] = {
            "disabled": {
                **base,
                "required_config_flags": [],
                "required_subcomponents": [],
                "expected_subsystem_posture": {
                    "capture": "disabled",
                    "wake": "disabled",
                    "post_wake": "disabled",
                    "vad": "disabled",
                    "realtime": "disabled",
                    "playback": "disabled",
                },
            },
            "manual_only": {
                **base,
                "required_config_flags": ["voice.enabled", "voice.manual_input_enabled"],
                "required_subcomponents": ["voice", "manual_input"],
                "forbidden_subcomponents": ["capture", "wake", "post_wake", "realtime"],
                "expected_subsystem_posture": {
                    "capture": "disabled",
                    "wake": "disabled",
                    "post_wake": "disabled",
                    "realtime": "disabled",
                },
            },
            "output_only": {
                **base,
                "required_config_flags": [
                    "voice.enabled",
                    "voice.spoken_responses_enabled",
                    "voice.playback.enabled",
                ],
                "required_providers": ["openai_tts", "local_playback"],
                "required_subcomponents": [
                    "voice",
                    "openai_tts",
                    "spoken_responses",
                    "live_playback",
                ],
                "forbidden_subcomponents": [
                    "capture",
                    "wake",
                    "post_wake",
                    "vad",
                    "realtime",
                ],
                "expected_subsystem_posture": {
                    "capture": "disabled",
                    "wake": "disabled",
                    "post_wake": "disabled",
                    "vad": "disabled",
                    "realtime": "disabled",
                    "playback": "enabled_available",
                },
            },
            "push_to_talk": {
                **base,
                "required_config_flags": [
                    "voice.enabled",
                    "voice.capture.enabled",
                ],
                "required_providers": ["openai_stt", "capture"],
                "required_subcomponents": ["voice", "capture", "openai_stt"],
                "forbidden_subcomponents": ["wake", "post_wake", "realtime"],
                "expected_subsystem_posture": {
                    "capture": "enabled_available",
                    "wake": "disabled",
                    "post_wake": "disabled",
                    "realtime": "disabled",
                },
            },
            "wake_supervised": {
                **base,
                "required_config_flags": [
                    "voice.enabled",
                    "voice.wake.enabled",
                    "voice.post_wake.enabled",
                    "voice.capture.enabled",
                ],
                "required_providers": ["local_wake", "capture", "openai_stt"],
                "required_subcomponents": [
                    "voice",
                    "wake",
                    "post_wake",
                    "capture",
                    "openai_stt",
                    "core_bridge",
                ],
                "forbidden_subcomponents": ["realtime"],
                "expected_subsystem_posture": {
                    "wake": "enabled_available",
                    "post_wake": "enabled",
                    "capture": "enabled_available",
                    "realtime": "disabled",
                },
            },
            "realtime_transcription": {
                **base,
                "required_config_flags": [
                    "voice.enabled",
                    "voice.realtime.enabled",
                    "voice.realtime.core_bridge_required",
                ],
                "required_providers": ["realtime"],
                "required_subcomponents": ["voice", "realtime", "core_bridge"],
                "forbidden_subcomponents": ["direct_realtime_tools"],
                "expected_subsystem_posture": {
                    "realtime": "enabled_available",
                    "direct_realtime_tools": "disabled",
                },
            },
            "realtime_speech_core_bridge": {
                **base,
                "required_config_flags": [
                    "voice.enabled",
                    "voice.realtime.enabled",
                    "voice.realtime.speech_to_speech_enabled",
                    "voice.realtime.audio_output_from_realtime",
                    "voice.realtime.core_bridge_required",
                ],
                "required_providers": ["realtime"],
                "required_subcomponents": [
                    "voice",
                    "realtime",
                    "realtime_audio_output",
                    "core_bridge",
                ],
                "forbidden_subcomponents": ["direct_realtime_tools"],
                "expected_subsystem_posture": {
                    "realtime": "enabled_available",
                    "direct_realtime_tools": "disabled",
                    "core_bridge": "required",
                },
            },
        }
        return table.get(mode, base)

    def _runtime_mode_user_summary(
        self,
        mode: str,
        status: str,
        blocking_reasons: list[str],
        warnings: list[str],
    ) -> str:
        if status == "disabled":
            return "Voice is disabled."
        if "output_voice_configured_but_playback_disabled" in blocking_reasons:
            return "Output voice is enabled, but local playback is disabled."
        if "output_voice_configured_but_playback_unavailable" in blocking_reasons:
            return "Output voice is enabled, but local playback is unavailable."
        if "output_voice_configured_but_tts_unavailable" in blocking_reasons:
            return "Output voice is enabled, but OpenAI TTS is unavailable."
        if mode == "output_only" and status == "ready":
            return "Output voice is ready: OpenAI TTS and local playback are available."
        if status == "blocked":
            return f"{self._runtime_mode_title(mode)} mode is blocked."
        if status == "degraded":
            if warnings:
                return f"{self._runtime_mode_title(mode)} mode has contradictory settings."
            return f"{self._runtime_mode_title(mode)} mode is degraded."
        return f"{self._runtime_mode_title(mode)} mode is ready."

    def _runtime_mode_title(self, mode: str) -> str:
        return str(mode or "voice").replace("_", " ").title()

    def _runtime_mode_next_fix(
        self, mode: str, blocking_reasons: list[str]
    ) -> str | None:
        if "voice_disabled" in blocking_reasons:
            return "Enable voice.enabled."
        if "output_voice_configured_but_playback_disabled" in blocking_reasons:
            return "Enable voice.playback.enabled for output-only live speech."
        if "output_voice_configured_but_playback_unavailable" in blocking_reasons:
            return "Fix local playback availability for output-only live speech."
        if "output_voice_configured_but_tts_unavailable" in blocking_reasons:
            return "Enable OpenAI TTS configuration for output-only speech."
        if "push_to_talk_capture_disabled" in blocking_reasons:
            return "Enable voice.capture.enabled for push-to-talk."
        if "push_to_talk_capture_unavailable" in blocking_reasons:
            return "Fix capture provider availability for push-to-talk."
        if "wake_supervised_wake_unavailable" in blocking_reasons:
            return "Enable and configure the local wake provider."
        if "wake_supervised_post_wake_unavailable" in blocking_reasons:
            return "Enable post-wake listen and its dev/live gate."
        if "realtime_direct_tools_forbidden" in blocking_reasons:
            return "Set voice.realtime.direct_tools_allowed=false."
        if mode.startswith("realtime") and any("core_bridge" in item for item in blocking_reasons):
            return "Attach the Stormhelm Core bridge before starting Realtime voice."
        return None

    def _tts_unavailable_reason(self) -> str:
        if not self.config.spoken_responses_enabled:
            return "spoken_responses_disabled"
        if not self.openai_config.enabled:
            return "openai_disabled"
        if not self.openai_config.api_key:
            return "api_key_missing"
        if not self.availability.tts_allowed:
            return self.availability.unavailable_reason or "tts_unavailable"
        return "tts_unavailable"

    def _stt_unavailable_reason(self) -> str:
        if not self.openai_config.enabled:
            return "openai_disabled"
        if not self.openai_config.api_key:
            return "api_key_missing"
        if not self.availability.stt_allowed:
            return self.availability.unavailable_reason or "stt_unavailable"
        return "stt_unavailable"

    def readiness_report(self) -> VoiceReadinessReport:
        availability = self.availability
        runtime_mode = self.runtime_mode_readiness_report()
        capture_availability = self._capture_provider_availability()
        playback_availability = self._playback_provider_availability()
        current_phase = self.pipeline_stage_summary().stage
        provider_name = availability.provider_name or self.config.provider
        provider_kind = self._readiness_provider_kind(
            provider_name, capture_availability
        )
        voice_available = bool(availability.available)
        credential_present = bool(self.openai_config.api_key)
        manual_ready = bool(
            self.config.enabled and self.config.manual_input_enabled and voice_available
        )
        stt_ready = bool(self.config.enabled and voice_available)
        tts_ready = bool(
            self.config.enabled
            and voice_available
            and self.config.spoken_responses_enabled
        )
        capture_ready = bool(
            self.config.enabled
            and voice_available
            and self.config.capture.enabled
            and capture_availability.get("available")
        )
        playback_ready = bool(
            self.config.enabled
            and voice_available
            and self.config.playback.enabled
            and playback_availability.get("available")
        )
        local_capture_ready = bool(
            capture_ready and self._capture_provider_name() == "local"
        )

        blocking_reasons: list[str] = []
        warnings: list[str] = []
        if not self.config.enabled:
            blocking_reasons.append("voice_disabled")
        if not self.openai_config.enabled:
            blocking_reasons.append("openai_disabled")
        elif not credential_present:
            blocking_reasons.append("api_key_missing")
        if not availability.provider_configured:
            blocking_reasons.append("provider_not_configured")
        if (
            availability.unavailable_reason
            and availability.unavailable_reason not in blocking_reasons
        ):
            blocking_reasons.append(availability.unavailable_reason)

        if runtime_mode.blocked and runtime_mode.effective_mode != "manual_only":
            blocking_reasons.extend(runtime_mode.blocking_reasons)
        if runtime_mode.degraded and runtime_mode.effective_mode != "manual_only":
            warnings.extend(runtime_mode.warnings)

        if not self.config.capture.enabled:
            if runtime_mode.effective_mode != "output_only":
                warnings.append("capture_disabled")
        elif not capture_ready:
            reason = str(
                capture_availability.get("unavailable_reason") or "provider_unavailable"
            )
            if reason == "dependency_missing":
                blocking_reasons.append("capture_dependency_missing")
            elif reason == "device_unavailable":
                blocking_reasons.append("capture_device_unavailable")
            elif reason == "permission_denied":
                blocking_reasons.append("capture_permission_denied")
            else:
                blocking_reasons.append(f"capture_{reason}")

        if not self.config.spoken_responses_enabled:
            warnings.append("spoken_responses_disabled")
        if not self.config.playback.enabled:
            if runtime_mode.effective_mode == "output_only":
                blocking_reasons.append("output_voice_configured_but_playback_disabled")
            else:
                warnings.append("playback_disabled")
        elif not playback_ready:
            reason = str(
                playback_availability.get("unavailable_reason")
                or "provider_unavailable"
            )
            if runtime_mode.effective_mode == "output_only":
                blocking_reasons.append(
                    "output_voice_configured_but_playback_unavailable"
                )
            else:
                warnings.append(f"playback_{reason}")
        if availability.mock_provider_active or bool(
            getattr(self.capture_provider, "is_mock", False)
        ):
            warnings.append("mock_provider_active")

        blocking_reasons = self._dedupe_strings(blocking_reasons)
        warnings = self._dedupe_strings(warnings)
        overall_status = self._readiness_overall_status(
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            manual_ready=manual_ready,
            capture_ready=capture_ready,
        )
        user_reason = self._readiness_user_reason(
            overall_status=overall_status,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            capture_ready=capture_ready,
            runtime_mode=runtime_mode,
        )
        next_setup_action = self._readiness_next_setup_action(
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            runtime_mode=runtime_mode,
        )
        return VoiceReadinessReport(
            overall_status=overall_status,
            voice_enabled=self.config.enabled,
            openai_enabled=self.openai_config.enabled,
            api_key_present=credential_present,
            credential_status="credential present"
            if credential_present
            else "credential missing",
            provider=provider_name,
            provider_available=voice_available,
            provider_kind=provider_kind,
            current_phase=current_phase,
            manual_transcript_ready=manual_ready,
            stt_ready=stt_ready,
            tts_ready=tts_ready,
            playback_ready=playback_ready,
            capture_ready=capture_ready,
            local_capture_ready=local_capture_ready,
            ghost_controls_ready=capture_ready,
            deck_surface_ready=True,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            next_setup_action=next_setup_action,
            user_facing_reason=user_reason,
            runtime_mode=runtime_mode.to_dict(),
            truth_flags=self._voice_truth_flags(),
        )

    def pipeline_stage_summary(self) -> VoicePipelineStageSummary:
        active_capture = self._active_capture()
        active_listen_window = self.get_active_post_wake_listen_window()
        last_listen_window = self.last_post_wake_listen_window
        listen_window = active_listen_window or last_listen_window
        capture_status = (
            active_capture.status
            if active_capture is not None
            else (
                self.last_capture_result.status
                if self.last_capture_result is not None
                else None
            )
        )
        transcription = self.last_transcription_result
        manual_or_audio_result = (
            self.last_audio_turn_result or self.last_manual_turn_result
        )
        core_result = (
            manual_or_audio_result.core_result
            if manual_or_audio_result is not None
            else None
        )
        synthesis = self.last_synthesis_result
        playback = self.last_playback_result
        interruption = self.last_interruption_result
        transcription_status = (
            transcription.status if transcription is not None else None
        )
        core_state = core_result.result_state if core_result is not None else None
        synthesis_status = synthesis.status if synthesis is not None else None
        playback_status = playback.status if playback is not None else None

        stage = "idle"
        last_successful_stage: str | None = None
        failed_stage: str | None = None
        current_blocker: str | None = None
        if active_capture is not None and active_capture.status in {
            "started",
            "recording",
        }:
            stage = "capturing"
        elif (
            active_listen_window is not None
            and active_listen_window.status in {"active", "pending"}
        ):
            stage = "post_wake_listening"
        elif capture_status == "cancelled":
            stage = "cancelled"
        elif capture_status in {"failed", "timeout", "blocked", "unavailable"}:
            stage = (
                "blocked" if capture_status in {"blocked", "unavailable"} else "failed"
            )
            failed_stage = "capture"
            current_blocker = self._capture_error_code()
        elif transcription_status in {"started", "transcribing", "in_progress"}:
            stage = "transcribing"
            last_successful_stage = "capture"
        elif transcription_status in {"failed", "blocked", "unavailable"}:
            stage = "failed"
            failed_stage = "stt"
            current_blocker = (
                transcription.error_code if transcription is not None else None
            )
        elif self.state_controller.snapshot().state in {
            VoiceState.CORE_ROUTING,
            VoiceState.THINKING,
        }:
            stage = "core_routing"
            last_successful_stage = (
                "stt" if transcription is not None else "manual_transcript"
            )
        elif core_state in {"blocked", "failed", "unavailable"}:
            stage = "blocked" if core_state == "blocked" else "failed"
            failed_stage = "core"
            current_blocker = (
                core_result.error_code if core_result is not None else None
            )
        elif synthesis_status in {"started", "synthesizing", "in_progress"}:
            stage = "synthesizing"
            last_successful_stage = "core"
        elif synthesis_status in {"failed", "blocked", "unavailable"}:
            stage = "failed" if synthesis_status == "failed" else "blocked"
            failed_stage = "tts"
            current_blocker = synthesis.error_code if synthesis is not None else None
        elif playback_status in {"started", "playing"}:
            stage = "playing"
            last_successful_stage = "audio_prepared"
        elif playback_status in {"failed", "blocked", "unavailable"}:
            stage = "failed" if playback_status == "failed" else "blocked"
            failed_stage = "playback"
            current_blocker = playback.error_code if playback is not None else None
        elif playback_status == "completed":
            stage = "completed"
            last_successful_stage = "playback"
        elif playback_status == "stopped":
            stage = "completed"
            last_successful_stage = "playback"
        elif synthesis_status in {"succeeded", "completed"}:
            stage = "audio_prepared"
            last_successful_stage = "tts"
        elif core_state:
            stage = "response_prepared"
            last_successful_stage = "core"
        elif capture_status in {"completed", "stopped"}:
            stage = "completed"
            last_successful_stage = "capture"

        transcript = ""
        if transcription is not None:
            transcript = transcription.transcript
        elif (
            manual_or_audio_result is not None
            and manual_or_audio_result.turn is not None
        ):
            transcript = manual_or_audio_result.turn.transcript
        spoken_text = ""
        if self.last_speech_request is not None:
            spoken_text = self.last_speech_request.text
        elif (
            manual_or_audio_result is not None
            and manual_or_audio_result.spoken_response is not None
        ):
            spoken_text = manual_or_audio_result.spoken_response.spoken_text
        return VoicePipelineStageSummary(
            stage=stage,
            listen_window_status=listen_window.status
            if listen_window is not None
            else None,
            listen_window_id=listen_window.listen_window_id
            if listen_window is not None
            else None,
            capture_status=capture_status,
            transcription_status=transcription_status,
            core_result_state=core_state,
            synthesis_status=synthesis_status,
            playback_status=playback_status,
            current_blocker=current_blocker,
            last_successful_stage=last_successful_stage,
            failed_stage=failed_stage,
            transcript_preview=self._preview_text(transcript, limit=96),
            spoken_preview=self._preview_text(spoken_text, limit=96),
            route_family=core_result.route_family if core_result is not None else None,
            subsystem=core_result.subsystem if core_result is not None else None,
            trust_posture=core_result.trust_posture
            if core_result is not None
            else None,
            verification_posture=core_result.verification_posture
            if core_result is not None
            else None,
            final_status=interruption.status if interruption is not None else stage,
            output_stopped=bool(
                interruption is not None
                and interruption.intent
                in {
                    VoiceInterruptionIntent.STOP_PLAYBACK,
                    VoiceInterruptionIntent.STOP_SPEAKING,
                }
                and interruption.status in {"completed", "no_active_playback"}
            ),
            output_suppressed=bool(
                self.current_response_suppressed or self.spoken_output_muted
            ),
            playback_stopped=playback_status == "stopped",
            muted=self.spoken_output_muted,
            no_active_playback=bool(
                interruption is not None and interruption.status == "no_active_playback"
            ),
            timestamps={
                "last_capture_at": self.last_capture_result.stopped_at
                if self.last_capture_result is not None
                else None,
                "last_transcription_at": transcription.created_at
                if transcription is not None
                else None,
                "last_synthesis_at": synthesis.created_at
                if synthesis is not None
                else None,
                "last_playback_started_at": playback.started_at
                if playback is not None
                else None,
                "last_playback_completed_at": playback.completed_at
                if playback is not None
                else None,
            },
        )

    def _wake_loop_final_status_for_core(self, result_state: str | None) -> str:
        normalized = str(result_state or "").strip().lower()
        if normalized == "clarification_required":
            return "core_clarification_required"
        if normalized == "requires_confirmation":
            return "core_confirmation_required"
        if normalized == "blocked":
            return "core_blocked"
        if normalized in {"failed", "unavailable", "blocked_unavailable"}:
            return "core_failed"
        return "completed"

    def _wake_supervised_loop_status_snapshot(self) -> dict[str, Any]:
        result = self.last_wake_supervised_loop_result
        wake_ready = self.wake_readiness_report()
        vad_ready = self.vad_readiness_report()
        post_wake = self._post_wake_listen_status_snapshot()
        capture_available = bool(
            self.config.capture.enabled
            and self._capture_provider_availability().get("available")
        )
        stt_ready = bool(
            self.config.enabled
            and self.openai_config.enabled
            and (bool(self.openai_config.api_key) or self.config.debug_mock_provider)
        )
        ready = bool(
            wake_ready.wake_available
            and post_wake["ready"]
            and capture_available
            and stt_ready
            and self.core_bridge is not None
        )
        missing: list[str] = []
        if not wake_ready.wake_available:
            missing.append("wake")
        if not post_wake["ready"]:
            missing.append("post_wake_listen")
        if not capture_available:
            missing.append("capture")
        if not stt_ready:
            missing.append("stt")
        if self.core_bridge is None:
            missing.append("core_bridge")
        return {
            "enabled": bool(self.config.enabled and self.config.wake.enabled),
            "ready": ready,
            "required_capabilities": [
                "local_or_mock_wake",
                "wake_ghost",
                "post_wake_listen_window",
                "bounded_capture",
                "stt",
                "core_bridge",
                "spoken_response_renderer",
                "tts_optional",
                "playback_optional",
            ],
            "missing_capabilities": missing,
            "active_loop_id": self.active_wake_supervised_loop_id,
            "active_loop_stage": self.active_wake_supervised_loop_stage,
            "last_loop_result": result.to_dict() if result is not None else None,
            "final_status": result.final_status if result is not None else None,
            "failed_stage": result.failed_stage if result is not None else None,
            "stopped_stage": result.stopped_stage if result is not None else None,
            "last_successful_stage": result.last_successful_stage
            if result is not None
            else None,
            "wake_supervised_loop_ready": ready,
            "wake_available": wake_ready.wake_available,
            "post_wake_listen_ready": post_wake["ready"],
            "capture_available": capture_available,
            "stt_ready": stt_ready,
            "tts_ready": bool(self.config.spoken_responses_enabled),
            "playback_ready": bool(self.config.playback.enabled),
            "vad_ready": vad_ready.vad_available,
            "ready_visual_only": bool(wake_ready.wake_available and capture_available),
            "ready_full_audio_response": bool(ready and self.config.playback.enabled),
            "no_realtime": True,
            "continuous_listening": False,
            "cloud_wake_detection": False,
            "command_authority": "stormhelm_core",
            "user_heard_claimed": False,
        }

    def _post_wake_listen_status_snapshot(self) -> dict[str, Any]:
        active = self.get_active_post_wake_listen_window()
        last = self.last_post_wake_listen_window
        enabled = bool(self.config.post_wake.enabled)
        ready = bool(
            enabled
            and self.config.post_wake.allow_dev_post_wake
            and self.config.wake.enabled
            and self.config.capture.enabled
        )
        return {
            "enabled": enabled,
            "ready": ready,
            "listen_window_ms": self.config.post_wake.listen_window_ms,
            "max_utterance_ms": self.config.post_wake.max_utterance_ms,
            "auto_start_capture": self.config.post_wake.auto_start_capture,
            "auto_submit_on_capture_complete": self.config.post_wake.auto_submit_on_capture_complete,
            "allow_dev_post_wake": self.config.post_wake.allow_dev_post_wake,
            "active": active is not None,
            "active_listen_window_id": active.listen_window_id
            if active is not None
            else None,
            "active_listen_window_status": active.status if active is not None else None,
            "active_listen_window_expires_at": active.expires_at
            if active is not None
            else None,
            "last_listen_window_id": last.listen_window_id if last is not None else None,
            "last_listen_window_status": last.status if last is not None else None,
            "last_listen_window_stop_reason": last.stop_reason
            if last is not None
            else None,
            "listen_window_capture_id": last.capture_id if last is not None else None,
            "listen_window_audio_input_id": last.audio_input_id
            if last is not None
            else None,
            "listen_window_vad_session_id": last.vad_session_id
            if last is not None
            else None,
            "last_window": last.to_dict() if last is not None else None,
            "no_realtime": True,
            "continuous_listening": False,
            "command_authority": "stormhelm_core",
            "listen_window_does_not_route_core": True,
            "raw_audio_present": False,
            "openai_used": False,
        }

    def _realtime_status_snapshot(self) -> dict[str, Any]:
        readiness = self.realtime_readiness_report().to_dict()
        active = self.get_active_realtime_session()
        last_session = self.last_realtime_session
        last_event = self.last_realtime_transcript_event
        last_turn = self.last_realtime_turn_result
        last_core_call = self.last_realtime_core_bridge_call
        last_gate = self.last_realtime_response_gate
        speech_mode = self.config.realtime.mode == "speech_to_speech_core_bridge"
        return {
            "enabled": bool(self.config.realtime.enabled),
            "provider": self._realtime_provider_name(),
            "provider_kind": readiness["realtime_provider_kind"],
            "available": bool(readiness["realtime_available"]),
            "ready": bool(readiness["realtime_available"]),
            "mode": self.config.realtime.mode,
            "model": self.config.realtime.model,
            "voice": self.config.realtime.voice,
            "turn_detection": self.config.realtime.turn_detection,
            "semantic_vad_enabled": bool(self.config.realtime.semantic_vad_enabled),
            "session_active": active is not None,
            "active_realtime_session_id": active.realtime_session_id
            if active is not None
            else None,
            "active_realtime_session": active.to_dict()
            if active is not None
            else None,
            "last_realtime_session_id": last_session.realtime_session_id
            if last_session is not None
            else None,
            "last_realtime_session_status": last_session.status
            if last_session is not None
            else None,
            "last_realtime_session": last_session.to_dict()
            if last_session is not None
            else None,
            "active_realtime_turn_id": active.active_turn_id
            if active is not None
            else None,
            "last_realtime_event_id": last_event.realtime_event_id
            if last_event is not None
            else None,
            "partial_transcript_preview": last_event.transcript_preview
            if last_event is not None and last_event.is_partial
            else "",
            "final_transcript_preview": last_turn.final_transcript_preview
            if last_turn is not None
            else (
                last_event.transcript_preview
                if last_event is not None and last_event.is_final
                else ""
            ),
            "last_realtime_turn_result": last_turn.to_dict()
            if last_turn is not None
            else None,
            "core_bridge_tool_enabled": bool(
                speech_mode and self.config.realtime.speech_to_speech_enabled
            ),
            "direct_action_tools_exposed": False,
            "require_core_for_commands": True,
            "allow_smalltalk_without_core": bool(
                self.config.realtime.allow_smalltalk_without_core
            ),
            "last_core_bridge_call_id": last_core_call.core_bridge_call_id
            if last_core_call is not None
            else None,
            "last_core_bridge_call": last_core_call.to_dict()
            if last_core_call is not None
            else None,
            "last_core_result_state": last_core_call.result_state
            if last_core_call is not None
            else None,
            "last_spoken_summary_source": last_gate.spoken_summary_source
            if last_gate is not None
            else (
                active.last_spoken_summary_source
                if active is not None
                else (
                    last_session.last_spoken_summary_source
                    if last_session is not None
                    else "none"
                )
            ),
            "last_response_gate": last_gate.to_dict()
            if last_gate is not None
            else None,
            "last_realtime_error": {
                "code": last_session.error_code if last_session is not None else None,
                "message": last_session.error_message
                if last_session is not None
                else None,
            },
            "direct_tools_allowed": False,
            "core_bridge_required": True,
            "speech_to_speech_enabled": bool(
                speech_mode and self.config.realtime.speech_to_speech_enabled
            ),
            "audio_output_from_realtime": bool(
                speech_mode and self.config.realtime.audio_output_from_realtime
            ),
            "raw_audio_present": False,
            "no_cloud_wake_detection": True,
            "wake_detection_local_only": True,
            "command_authority": "stormhelm_core",
            "stormhelm_core_is_command_authority": True,
            "realtime_transcription_bridge_only": self.config.realtime.mode
            == "transcription_bridge",
            "speech_to_speech_core_bridge": speech_mode,
            "readiness": readiness,
            "blocking_reasons": readiness["blocking_reasons"],
            "warnings": readiness["warnings"],
        }

    def status_snapshot(self) -> dict[str, Any]:
        state = self.state_controller.snapshot()
        availability = self.availability.to_dict()
        played_locally = bool(
            self.last_playback_result and self.last_playback_result.played_locally
        )
        readiness = self.readiness_report().to_dict()
        pipeline_summary = self.pipeline_stage_summary().to_dict()
        post_wake_listen = self._post_wake_listen_status_snapshot()
        wake_supervised_loop = self._wake_supervised_loop_status_snapshot()
        realtime_status = self._realtime_status_snapshot()
        runtime_mode = dict(readiness.get("runtime_mode") or {})
        snapshot = {
            "phase": "voice0",
            "current_phase": "voice5",
            "operator_readiness_phase": "voice7",
            "output_interruption_phase": "voice9",
            "wake_foundation_phase": "voice10",
            "local_wake_provider_phase": "voice11",
            "wake_to_ghost_phase": "voice12",
            "post_wake_listen_phase": "voice13r",
            "wake_supervised_loop_phase": "voice15",
            "spoken_confirmation_phase": "voice16",
            "interruption_hardening_phase": "voice17",
            "realtime_transcription_phase": "voice18",
            "realtime_speech_phase": "voice19",
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
            "wake_enabled": self.config.wake.enabled,
            "legacy_wake_word_enabled": self.config.wake_word_enabled,
            "spoken_responses_enabled": self.config.spoken_responses_enabled,
            "manual_input_enabled": self.config.manual_input_enabled,
            "runtime_mode": runtime_mode,
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
            "capture": self._capture_status_snapshot(),
            "wake": self._wake_status_snapshot(),
            "wake_ghost": self._wake_ghost_status_snapshot(),
            "post_wake_listen": post_wake_listen,
            "vad": self._vad_status_snapshot(),
            "realtime": realtime_status,
            "interruption": self._interruption_status_snapshot(),
            "spoken_confirmation": self._spoken_confirmation_status_snapshot(),
            "wake_supervised_loop": wake_supervised_loop,
            "readiness": readiness,
            "pipeline_summary": pipeline_summary,
            "runtime_truth": {
                "manual_transcript_path_available": True,
                "controlled_audio_file_or_blob_only": True,
                "controlled_tts_audio_artifacts_only": True,
                "controlled_local_playback_boundary": True,
                "controlled_push_to_talk_capture_boundary": True,
                "push_to_talk_capture_only": True,
                "wake_foundation_only": True,
                "local_wake_provider_boundary": True,
                "wake_to_ghost_presentation_only": True,
                "post_wake_listen_window_backfilled": True,
                "post_wake_listen_window_active": bool(
                    post_wake_listen.get("active", False)
                ),
                "post_wake_listen_is_bounded": True,
                "listen_window_does_not_route_core": True,
                "wake_supervised_loop_handles_one_bounded_request": True,
                "spoken_confirmation_requires_pending_binding": True,
                "spoken_confirmation_consumed_once": True,
                "spoken_confirmation_does_not_execute_actions": True,
                "spoken_confirmation_does_not_bypass_trust": True,
                "wake_supervised_loop_active": bool(
                    self.active_wake_supervised_loop_id
                ),
                "vad_foundation_only": True,
                "vad_detects_audio_activity_only": True,
                "vad_semantic_completion_claimed": False,
                "vad_command_authority": False,
                "realtime_vad": False,
                "wake_monitoring_active": bool(self.wake_monitoring_active),
                "wake_detection_is_not_command_authority": True,
                "wake_does_not_start_capture": True,
                "wake_does_not_route_core": True,
                "wake_to_ghost_does_not_create_voice_turn": True,
                "no_real_audio": True,
                "no_microphone": True,
                "no_microphone_capture": True,
                "always_listening": False,
                "no_wake_word": self._wake_provider_name() != "local",
                "no_real_wake_detection": self._wake_provider_name() != "local",
                "no_cloud_wake_audio": True,
                "openai_wake_detection": False,
                "cloud_wake_detection": False,
                "no_vad": not self.config.vad.enabled,
                "no_live_listening": True,
                "no_live_stt": True,
                "no_stt": False,
                "no_tts": False,
                "no_live_tts": not bool(self.config.openai.stream_tts_outputs),
                "no_realtime": not bool(self.config.realtime.enabled),
                "no_audio_playback": not played_locally,
                "no_live_conversation_loop": True,
                "no_continuous_loop": True,
                "continuous_listening": False,
                "user_heard_claimed": False,
                "openai_voice_boundary_law": "stt_tts_only",
                "openai_stt_transcript_provider_only": True,
                "openai_tts_speech_rendering_provider_only": True,
                "openai_voice_not_command_authority": True,
                "openai_realtime_requires_core_bridge": True,
                "realtime_transcription_bridge_only": self.config.realtime.mode
                == "transcription_bridge",
                "realtime_speech_to_speech_core_bridge": self.config.realtime.mode
                == "speech_to_speech_core_bridge",
                "speech_to_speech_enabled": bool(
                    self.config.realtime.mode == "speech_to_speech_core_bridge"
                    and self.config.realtime.speech_to_speech_enabled
                ),
                "audio_output_from_realtime": bool(
                    self.config.realtime.mode == "speech_to_speech_core_bridge"
                    and self.config.realtime.audio_output_from_realtime
                ),
                "direct_realtime_tools_allowed": False,
                "direct_realtime_action_tools_exposed": False,
                "stop_speaking_does_not_cancel_core_tasks": True,
                "core_task_cancelled_by_voice": False,
                "core_result_mutated_by_voice": False,
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
                "controlled_push_to_talk_capture": True,
                "wake_word_foundation": True,
                "local_wake_provider_boundary": True,
                "wake_to_ghost_presentation": True,
                "post_wake_listen_window": True,
                "wake_driven_supervised_loop": True,
                "spoken_confirmation_handling": True,
                "vad_foundation": True,
                "realtime_transcription_bridge": True,
                "realtime_speech_core_bridge": self.config.realtime.mode
                == "speech_to_speech_core_bridge",
                "mock_vad_provider": self.config.vad.provider == "mock",
                "mock_realtime_provider": self.config.realtime.provider == "mock",
                "mock_wake_provider": self.config.wake.provider == "mock",
                "core_bridge_routing": self.core_bridge is not None,
                "real_microphone_capture": False,
                "real_wake_word_detection": self._wake_provider_name() == "local",
                "real_openai_stt": True,
                "real_openai_tts": True,
                "openai_realtime_sessions": bool(self.config.realtime.enabled),
                "audio_playback": bool(self.config.playback.enabled),
                "wake_word_detection": self._wake_provider_name() == "local",
                "real_wake_monitoring": bool(
                    self._wake_provider_availability().get(
                        "real_microphone_monitoring", False
                    )
                ),
                "continuous_listening": False,
                "realtime_vad": False,
            },
            "truthfulness_contract": {
                "core_bridge_required": True,
                "direct_tool_execution_allowed": False,
                "openai_required_when_provider_openai": True,
                "openai_voice_provider_boundary": "stt_tts_only",
                "openai_voice_not_command_authority": True,
                "openai_stt_is_transcript_provider_only": True,
                "openai_tts_is_speech_rendering_provider_only": True,
                "openai_does_not_route_or_execute_voice_commands": True,
                "openai_realtime_requires_core_bridge": True,
                "realtime_receives_no_direct_action_tools": True,
                "realtime_speech_uses_core_spoken_summary": True,
                "mock_provider_must_be_reported": True,
                "no_audio_runtime_in_voice0": True,
                "manual_turns_route_through_core": True,
                "audio_turns_route_through_core": True,
                "tts_uses_approved_spoken_response": True,
                "tts_generation_does_not_imply_playback": True,
                "playback_does_not_imply_task_success": True,
                "playback_does_not_claim_user_heard": True,
                "capture_does_not_imply_transcription": True,
                "capture_cancellation_does_not_cancel_core_tasks": True,
                "stop_speaking_does_not_cancel_core_tasks": True,
                "wake_detection_is_not_command_authority": True,
                "wake_does_not_start_capture": True,
                "wake_does_not_route_core": True,
                "wake_to_ghost_is_presentation_only": True,
                "post_wake_listen_is_request_capture_window_only": True,
                "listen_window_does_not_route_core": True,
                "vad_detects_audio_activity_only": True,
                "vad_is_not_command_authority": True,
                "vad_does_not_route_core": True,
                "spoken_yes_is_not_global_permission": True,
                "spoken_confirmation_is_not_command_authority": True,
                "confirmation_accepted_does_not_mean_action_completed": True,
                "speech_stopped_does_not_mean_request_understood": True,
                "openai_not_used_for_wake_detection": True,
                "cloud_not_used_for_wake_detection": True,
                "dormant_wake_audio_sent_to_openai": False,
                "dormant_wake_audio_sent_to_cloud": False,
                "core_task_cancelled_by_voice": False,
                "core_result_mutated_by_voice": False,
                "raw_audio_persisted_by_default": False,
            },
            "planned_not_implemented": {
                "microphone_capture": "mock_or_stub_push_to_talk_boundary_only",
                "post_wake_capture": "bounded_post_wake_listen_window_backfilled",
                "real_wake_monitoring": "disabled_by_default_local_boundary",
                "openai_stt": "controlled_audio_only",
                "openai_tts": "controlled_audio_output_only",
                "openai_realtime": "speech_to_speech_core_bridge_disabled_by_default"
                if self.config.realtime.mode == "speech_to_speech_core_bridge"
                else "transcription_bridge_only_disabled_by_default",
                "streaming_transcription": "realtime_transcription_or_speech_core_bridge",
                "continuous_listening": "not_implemented",
                "barge_in": "not_implemented",
                "audio_playback": "controlled_local_boundary_only",
                "always_listening": "not_implemented",
                "semantic_vad": "not_implemented",
            },
        }
        envelope = (
            self.last_voice_output_envelope.to_dict()
            if self.last_voice_output_envelope is not None
            else None
        )
        if envelope is not None:
            snapshot["voice_output_envelope"] = envelope
        voice_anchor = build_voice_anchor_payload(snapshot)
        snapshot["voice_anchor"] = voice_anchor
        snapshot["voice_anchor_state"] = voice_anchor.get("state")
        snapshot["speaking_visual_active"] = voice_anchor.get("speaking_visual_active")
        snapshot["voice_motion_intensity"] = voice_anchor.get("motion_intensity")
        snapshot["voice_audio_reactive_source"] = voice_anchor.get(
            "audio_reactive_source"
        )
        snapshot["voice_audio_reactive_available"] = voice_anchor.get(
            "audio_reactive_available"
        )
        snapshot["voice_smoothed_output_level"] = voice_anchor.get(
            "smoothed_output_level"
        )
        return snapshot

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
            speech_length_hint=str(speech_length_hint or "short").strip().lower()
            or "short",
            provider=getattr(
                self.provider,
                "name",
                self.availability.provider_name or self.config.provider,
            ),
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

    def _build_capture_request(
        self,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        blocked_reason: str | None = None,
    ) -> VoiceCaptureRequest:
        return VoiceCaptureRequest(
            source=str(self.config.capture.mode or "push_to_talk").strip().lower()
            or "push_to_talk",
            provider=self._capture_provider_name(),
            device=self.config.capture.device,
            sample_rate=self.config.capture.sample_rate,
            channels=self.config.capture.channels,
            format=self.config.capture.format,
            max_duration_ms=self.config.capture.max_duration_ms,
            max_audio_bytes=self.config.capture.max_audio_bytes,
            persist_audio=self.config.capture.persist_captured_audio,
            session_id=session_id,
            turn_id=turn_id,
            metadata=dict(metadata or {}),
            allowed_to_capture=False,
            blocked_reason=blocked_reason,
        )

    def _capture_request_block_reason(self, request: VoiceCaptureRequest) -> str | None:
        if (
            not self.config.enabled
            or str(self.config.mode or "").strip().lower() == "disabled"
        ):
            return "voice_disabled"
        if not self.config.capture.enabled:
            return "capture_disabled"
        if request.source not in {
            "push_to_talk",
            "manual_capture",
            "test_capture",
            "mock",
        }:
            return "unsupported_capture_mode"
        if request.format not in _SUPPORTED_CAPTURE_FORMATS:
            return "unsupported_capture_format"
        if request.max_duration_ms <= 0:
            return "invalid_capture_duration"
        if request.max_audio_bytes <= 0:
            return "invalid_capture_size_limit"
        if self._active_capture() is not None:
            return "active_capture_exists"
        if not self.availability.available and not (
            self.config.debug_mock_provider and self.config.capture.allow_dev_capture
        ):
            return self.availability.unavailable_reason or "voice_unavailable"
        availability = self._capture_provider_availability()
        if not availability.get("available"):
            return str(availability.get("unavailable_reason") or "provider_unavailable")
        if request.blocked_reason:
            return request.blocked_reason
        return None

    async def _start_capture_with_provider(
        self,
        request: VoiceCaptureRequest,
    ) -> VoiceCaptureSession | VoiceCaptureResult:
        operation = getattr(self.capture_provider, "start_capture", None)
        if not callable(operation):
            return self._blocked_capture_result(
                request,
                status="unavailable",
                error_code="provider_unavailable",
                error_message="Voice capture provider does not implement start_capture.",
            )
        result = operation(request)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, (VoiceCaptureSession, VoiceCaptureResult)):
            return result
        return self._blocked_capture_result(
            request,
            status="failed",
            error_code="provider_invalid_result",
            error_message="Voice capture provider returned an unsupported result.",
        )

    def _blocked_capture_result(
        self,
        request: VoiceCaptureRequest,
        *,
        status: str,
        error_code: str,
        error_message: str,
    ) -> VoiceCaptureResult:
        return VoiceCaptureResult(
            ok=False,
            capture_request_id=request.capture_request_id,
            capture_id=None,
            status=status,
            provider=request.provider,
            device=request.device,
            stopped_at=self._now(),
            error_code=error_code,
            error_message=error_message,
            metadata={"capture_request": request.to_metadata()},
            raw_audio_persisted=False,
            microphone_was_active=False,
            always_listening_claimed=False,
            wake_word_claimed=False,
        )

    def _remember_post_wake_listen_window(
        self, window: VoicePostWakeListenWindow
    ) -> VoicePostWakeListenWindow:
        self.post_wake_listen_windows[window.listen_window_id] = window
        self.last_post_wake_listen_window = window
        if window.status in {"active", "capturing"}:
            self.active_post_wake_listen_window = window
        elif (
            self.active_post_wake_listen_window is not None
            and self.active_post_wake_listen_window.listen_window_id
            == window.listen_window_id
        ):
            self.active_post_wake_listen_window = None
        return window

    def _post_wake_listen_window_for_id(
        self, listen_window_id: str | None
    ) -> VoicePostWakeListenWindow | None:
        if not listen_window_id:
            return self.get_active_post_wake_listen_window()
        active = self.active_post_wake_listen_window
        if active is not None and active.listen_window_id == listen_window_id:
            return active
        return self.post_wake_listen_windows.get(listen_window_id)

    def _post_wake_listen_failure(
        self,
        *,
        wake_session_id: str | None,
        wake_event_id: str | None = None,
        session_id: str | None = None,
        error_code: str,
        error_message: str,
        stop_reason: str | None = None,
    ) -> VoicePostWakeListenWindow:
        return VoicePostWakeListenWindow(
            wake_event_id=wake_event_id or "",
            wake_session_id=wake_session_id or "",
            wake_ghost_request_id=None,
            session_id=session_id or "default",
            status="failed",
            expires_at=self._now(),
            listen_window_ms=self.config.post_wake.listen_window_ms,
            max_utterance_ms=self.config.post_wake.max_utterance_ms,
            stop_reason=stop_reason,
            error_code=error_code,
            error_message=error_message,
        )

    def _post_wake_capture_failure(
        self,
        *,
        listen_window_id: str,
        error_code: str,
        error_message: str,
        wake_session_id: str | None = None,
        wake_event_id: str | None = None,
    ) -> VoiceCaptureResult:
        return VoiceCaptureResult(
            ok=False,
            capture_request_id=None,
            capture_id=None,
            status="failed",
            provider=self._capture_provider_name(),
            device=self.config.capture.device,
            stopped_at=self._now(),
            error_code=error_code,
            error_message=error_message,
            metadata={
                "listen_window_id": listen_window_id,
                "post_wake_listen": {
                    "listen_window_id": listen_window_id,
                    "wake_session_id": wake_session_id,
                    "wake_event_id": wake_event_id,
                },
                "raw_audio_present": False,
                "openai_used": False,
                "realtime_used": False,
            },
        )

    def _metadata_listen_window_id(self, metadata: dict[str, Any] | None) -> str | None:
        if not isinstance(metadata, dict):
            return None
        direct = metadata.get("listen_window_id")
        if direct:
            return str(direct)
        for key in ("post_wake_listen", "wake_supervised_loop"):
            nested = metadata.get(key)
            if isinstance(nested, dict) and nested.get("listen_window_id"):
                return str(nested["listen_window_id"])
        return None

    def _listen_window_id_for_capture(self, capture_id: str | None) -> str | None:
        if not capture_id:
            return None
        for window in self.post_wake_listen_windows.values():
            if window.capture_id == capture_id:
                return window.listen_window_id
        session = self.last_capture_session
        if session is not None and session.capture_id == capture_id:
            return self._metadata_listen_window_id(session.metadata)
        result = self.last_capture_result
        if result is not None and result.capture_id == capture_id:
            return self._metadata_listen_window_id(result.metadata)
        return None

    def _with_post_wake_capture_session_metadata(
        self,
        session: VoiceCaptureSession,
        window: VoicePostWakeListenWindow,
    ) -> VoiceCaptureSession:
        metadata = dict(session.metadata or {})
        metadata.setdefault("listen_window_id", window.listen_window_id)
        metadata["post_wake_listen"] = {
            **dict(metadata.get("post_wake_listen") or {}),
            "listen_window_id": window.listen_window_id,
            "wake_event_id": window.wake_event_id,
            "wake_session_id": window.wake_session_id,
            "wake_ghost_request_id": window.wake_ghost_request_id,
            "bounded": True,
            "one_utterance": True,
            "continuous_listening": False,
            "realtime_used": False,
            "listen_window_does_not_route_core": True,
        }
        return replace(session, metadata=metadata)

    def _with_post_wake_capture_result_metadata(
        self,
        result: VoiceCaptureResult,
        window: VoicePostWakeListenWindow,
    ) -> VoiceCaptureResult:
        metadata = dict(result.metadata or {})
        metadata.setdefault("listen_window_id", window.listen_window_id)
        metadata["post_wake_listen"] = {
            **dict(metadata.get("post_wake_listen") or {}),
            "listen_window_id": window.listen_window_id,
            "wake_event_id": window.wake_event_id,
            "wake_session_id": window.wake_session_id,
            "wake_ghost_request_id": window.wake_ghost_request_id,
            "bounded": True,
            "one_utterance": True,
            "continuous_listening": False,
            "realtime_used": False,
            "listen_window_does_not_route_core": True,
        }
        audio_input = result.audio_input
        if audio_input is not None:
            audio_metadata = dict(audio_input.metadata or {})
            audio_metadata.setdefault("listen_window_id", window.listen_window_id)
            audio_metadata["post_wake_listen"] = {
                **dict(audio_metadata.get("post_wake_listen") or {}),
                "listen_window_id": window.listen_window_id,
                "wake_event_id": window.wake_event_id,
                "wake_session_id": window.wake_session_id,
                "wake_ghost_request_id": window.wake_ghost_request_id,
            }
            audio_input = replace(audio_input, metadata=audio_metadata)
        return replace(result, metadata=metadata, audio_input=audio_input)

    def _complete_post_wake_capture_sync(
        self,
        listen_window_id: str | None,
        capture_result: VoiceCaptureResult | None,
    ) -> VoicePostWakeListenWindow:
        window = self._post_wake_listen_window_for_id(listen_window_id)
        if window is None:
            window = self._post_wake_listen_failure(
                wake_session_id=None,
                error_code="listen_window_missing",
                error_message="Post-wake listen window was not found.",
            )
        result = capture_result
        if result is not None:
            result = self._with_post_wake_capture_result_metadata(result, window)
            self.last_capture_result = result
        status = "captured" if result is not None and result.ok else "failed"
        if result is not None and result.status in {"cancelled", "timeout"}:
            status = result.status
        updated = replace(
            window,
            status=status,
            capture_id=result.capture_id if result is not None else window.capture_id,
            audio_input_id=result.audio_input.input_id
            if result is not None and result.audio_input is not None
            else window.audio_input_id,
            stop_reason=result.stop_reason if result is not None else window.stop_reason,
            error_code=result.error_code if result is not None else window.error_code,
            error_message=result.error_message
            if result is not None
            else window.error_message,
            capture_started=True if result is not None else window.capture_started,
            stt_started=False,
            core_routed=False,
        )
        self._remember_post_wake_listen_window(updated)
        event_type = (
            VoiceEventType.POST_WAKE_LISTEN_CAPTURED
            if updated.status == "captured"
            else VoiceEventType.POST_WAKE_LISTEN_CANCELLED
            if updated.status == "cancelled"
            else VoiceEventType.POST_WAKE_LISTEN_EXPIRED
            if updated.status == "timeout"
            else VoiceEventType.POST_WAKE_LISTEN_FAILED
        )
        self._publish_post_wake_listen_event(
            event_type,
            updated,
            "Post-wake listen capture completed."
            if updated.status == "captured"
            else "Post-wake listen capture stopped.",
            status=updated.status,
            capture_id=updated.capture_id,
            input_id=updated.audio_input_id,
            error_code=updated.error_code,
        )
        return updated

    def _mark_post_wake_listen_submitted(
        self,
        listen_window_id: str | None,
        turn_result: VoiceTurnResult,
    ) -> VoicePostWakeListenWindow | None:
        window = self._post_wake_listen_window_for_id(listen_window_id)
        if window is None:
            return None
        submitted = replace(
            window,
            status="submitted",
            stt_started=True,
            core_routed=turn_result.core_result is not None,
            voice_turn_id=turn_result.turn.turn_id
            if turn_result.turn is not None
            else window.voice_turn_id,
        )
        self._remember_post_wake_listen_window(submitted)
        self._publish_post_wake_listen_event(
            VoiceEventType.POST_WAKE_LISTEN_SUBMITTED,
            submitted,
            "Post-wake listen submitted captured audio to the voice pipeline.",
            status=submitted.status,
            capture_id=submitted.capture_id,
            input_id=submitted.audio_input_id,
        )
        return submitted

    def _expire_post_wake_listen_window_sync(
        self,
        listen_window_id: str,
        *,
        reason: str = "listen_window_expired",
    ) -> VoicePostWakeListenWindow:
        window = self._post_wake_listen_window_for_id(listen_window_id)
        if window is None:
            return self._remember_post_wake_listen_window(
                self._post_wake_listen_failure(
                    wake_session_id=None,
                    error_code="listen_window_missing",
                    error_message="Post-wake listen window was not found.",
                    stop_reason=reason,
                )
            )
        expired = replace(
            window,
            status="expired",
            stop_reason=reason,
            stt_started=False,
            core_routed=False,
        )
        self._remember_post_wake_listen_window(expired)
        self._publish_post_wake_listen_event(
            VoiceEventType.POST_WAKE_LISTEN_EXPIRED,
            expired,
            "Post-wake listen window expired.",
            status=expired.status,
            capture_id=expired.capture_id,
        )
        return expired

    def _publish_post_wake_listen_event(
        self,
        event_type: VoiceEventType,
        window: VoicePostWakeListenWindow,
        message: str,
        *,
        status: str | None = None,
        capture_id: str | None = None,
        input_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=window.session_id,
            wake_event_id=window.wake_event_id or None,
            wake_session_id=window.wake_session_id or None,
            wake_ghost_request_id=window.wake_ghost_request_id,
            listen_window_id=window.listen_window_id,
            capture_id=capture_id or window.capture_id,
            input_id=input_id or window.audio_input_id,
            vad_session_id=window.vad_session_id,
            status=status or window.status,
            error_code=error_code or window.error_code,
            source="post_wake_listen",
            openai_used=window.openai_used,
            raw_audio_present=window.raw_audio_present,
            metadata={
                "post_wake_listen_window": window.to_dict(),
                "capture_started": window.capture_started,
                "stt_started": window.stt_started,
                "core_routed": window.core_routed,
                "command_authority_granted": False,
                "continuous_listening": False,
                "realtime_used": False,
            },
        )

    def _remember_capture_result(
        self, result: VoiceCaptureResult
    ) -> VoiceCaptureResult:
        listen_window_id = self._metadata_listen_window_id(result.metadata)
        if listen_window_id is None:
            listen_window_id = self._listen_window_id_for_capture(result.capture_id)
        window = self._post_wake_listen_window_for_id(listen_window_id)
        if window is not None:
            result = self._with_post_wake_capture_result_metadata(result, window)
            if window.status in {"active", "capturing"}:
                self._complete_post_wake_capture_sync(window.listen_window_id, result)
        self.last_capture_result = result
        self.last_capture_error = {
            "code": result.error_code,
            "message": result.error_message,
        }
        if result.error_code:
            self.last_error = {
                "code": result.error_code,
                "message": result.error_message,
            }
        else:
            self.last_error = {"code": None, "message": None}
        return result

    def _publish_capture_blocked(
        self, result: VoiceCaptureResult, request: VoiceCaptureRequest
    ) -> None:
        self._publish(
            VoiceEventType.CAPTURE_BLOCKED,
            message=result.error_message or "Push-to-talk capture blocked.",
            session_id=request.session_id,
            turn_id=request.turn_id,
            capture_request_id=request.capture_request_id,
            capture_id=result.capture_id,
            provider=result.provider,
            device=result.device,
            mode=request.source,
            source="push_to_talk",
            status=result.status,
            error_code=result.error_code,
            metadata={"capture_request": request.to_metadata()},
        )

    def _handle_capture_terminal_state(self, result: VoiceCaptureResult) -> None:
        listen_window_id = self._metadata_listen_window_id(result.metadata)
        if listen_window_id is None:
            listen_window_id = self._listen_window_id_for_capture(result.capture_id)
        event_type = self._capture_terminal_event_type(result)
        if result.status == "completed":
            message = "Push-to-talk capture stopped."
        elif result.status == "cancelled":
            message = "Push-to-talk capture cancelled."
        elif result.status == "timeout":
            message = "Push-to-talk capture reached its max duration."
        else:
            message = result.error_message or "Push-to-talk capture failed."
        self._publish_capture_terminal(event_type, result, message)
        if result.ok and result.audio_input is not None:
            self._publish(
                VoiceEventType.CAPTURE_AUDIO_CREATED,
                message="Push-to-talk capture produced bounded audio input.",
                session_id=self.last_capture_session.session_id
                if self.last_capture_session is not None
                else None,
                capture_request_id=result.capture_request_id,
                capture_id=result.capture_id,
                input_id=result.audio_input.input_id,
                listen_window_id=listen_window_id,
                provider=result.provider,
                device=result.device,
                mode=self.config.capture.mode,
                source="push_to_talk",
                status="created",
                duration_ms=result.duration_ms,
                size_bytes=result.size_bytes,
                metadata={"audio_input": result.audio_input.to_metadata()},
            )
        self._transition_from_capturing(result)

    def _capture_terminal_event_type(
        self, result: VoiceCaptureResult
    ) -> VoiceEventType:
        if result.status == "completed":
            return VoiceEventType.CAPTURE_STOPPED
        if result.status == "cancelled":
            return VoiceEventType.CAPTURE_CANCELLED
        if result.status == "timeout":
            return VoiceEventType.CAPTURE_TIMEOUT
        if result.status == "blocked":
            return VoiceEventType.CAPTURE_BLOCKED
        return VoiceEventType.CAPTURE_FAILED

    def _publish_capture_terminal(
        self,
        event_type: VoiceEventType,
        result: VoiceCaptureResult,
        message: str,
    ) -> None:
        listen_window_id = self._metadata_listen_window_id(result.metadata)
        if listen_window_id is None:
            listen_window_id = self._listen_window_id_for_capture(result.capture_id)
        self._publish(
            event_type,
            message=message,
            session_id=self.last_capture_session.session_id
            if self.last_capture_session is not None
            else None,
            capture_request_id=result.capture_request_id,
            capture_id=result.capture_id,
            input_id=result.audio_input.input_id
            if result.audio_input is not None
            else None,
            listen_window_id=listen_window_id,
            provider=result.provider,
            device=result.device,
            mode=self.config.capture.mode,
            source="push_to_talk",
            state=self.state_controller.snapshot().state.value,
            status=result.status,
            duration_ms=result.duration_ms,
            size_bytes=result.size_bytes,
            error_code=result.error_code,
            metadata={"capture": result.to_dict()},
        )

    def _transition_to_capturing(self, session: VoiceCaptureSession) -> None:
        if self.state_controller.snapshot().state in {
            VoiceState.DISABLED,
            VoiceState.UNAVAILABLE,
        }:
            self.state_controller = VoiceStateController(
                config=self.config,
                availability=self._capture_turn_availability(),
                session_id=session.session_id,
            )
        if self.state_controller.snapshot().state == VoiceState.CAPTURING:
            return
        try:
            self.state_controller.transition_to(
                VoiceState.CAPTURING,
                event_id=self._last_event_id(),
                turn_id=session.turn_id,
                source="push_to_talk",
            )
        except VoiceTransitionError:
            return

    def _transition_from_capturing(self, result: VoiceCaptureResult) -> None:
        if self.state_controller.snapshot().state != VoiceState.CAPTURING:
            return
        next_state = {
            "completed": VoiceState.CAPTURE_STOPPED,
            "cancelled": VoiceState.CAPTURE_CANCELLED,
            "timeout": VoiceState.CAPTURE_FAILED,
        }.get(result.status, VoiceState.CAPTURE_FAILED)
        try:
            self.state_controller.transition_to(
                next_state,
                event_id=self._last_event_id(),
                source="push_to_talk",
                error_code=result.error_code,
                error_message=result.error_message,
            )
            self.state_controller.transition_to(
                VoiceState.DORMANT,
                event_id=self._last_event_id(),
                source="push_to_talk",
            )
        except VoiceTransitionError:
            return

    def _voice_truth_flags(self) -> dict[str, Any]:
        return {
            "no_wake_word": True,
            "no_vad": True,
            "no_realtime": True,
            "no_continuous_loop": True,
            "always_listening": False,
            "microphone_requires_explicit_start": True,
            "wake_foundation_only": True,
            "no_real_wake_detection": True,
            "no_cloud_wake_audio": True,
            "openai_wake_detection": False,
            "wake_detection_is_not_command_authority": True,
            "wake_does_not_start_capture": True,
            "wake_does_not_route_core": True,
            "openai_voice_boundary_law": "stt_tts_only",
            "openai_voice_not_command_authority": True,
            "openai_stt_transcript_provider_only": True,
            "openai_tts_speech_rendering_provider_only": True,
            "openai_realtime_requires_core_bridge": True,
        }

    def _readiness_provider_kind(
        self, provider_name: str, capture_availability: dict[str, Any]
    ) -> str:
        if self.availability.mock_provider_active or bool(
            getattr(self.provider, "is_mock", False)
        ):
            return "mock"
        capture_provider = self._capture_provider_name()
        if bool(getattr(self.capture_provider, "is_mock", False)):
            return "mock"
        if capture_provider in {"local", "stub", "unavailable"}:
            return capture_provider
        normalized = str(provider_name or "").strip().lower()
        if normalized:
            return normalized
        if not capture_availability.get("available"):
            return "unavailable"
        return "unavailable"

    def _readiness_overall_status(
        self,
        *,
        blocking_reasons: list[str],
        warnings: list[str],
        manual_ready: bool,
        capture_ready: bool,
    ) -> str:
        if "voice_disabled" in blocking_reasons:
            return "disabled"
        if any(
            reason in blocking_reasons
            for reason in {
                "openai_disabled",
                "api_key_missing",
                "provider_not_configured",
                "provider_missing",
                "unsupported_provider",
            }
        ):
            return "misconfigured"
        if any(reason.startswith("output_voice_configured_but_") for reason in blocking_reasons):
            return "misconfigured"
        if manual_ready or capture_ready:
            return "degraded" if blocking_reasons or warnings else "ready"
        return "unavailable" if blocking_reasons else "degraded"

    def _readiness_user_reason(
        self,
        *,
        overall_status: str,
        blocking_reasons: list[str],
        warnings: list[str],
        capture_ready: bool,
        runtime_mode: VoiceRuntimeModeReadiness | None = None,
    ) -> str:
        if overall_status == "disabled":
            return "Voice is disabled."
        if runtime_mode is not None and runtime_mode.effective_mode != "manual_only":
            if runtime_mode.status in {"ready", "blocked", "degraded"}:
                return runtime_mode.user_facing_summary
        if "api_key_missing" in blocking_reasons:
            return "OpenAI is not configured."
        if "openai_disabled" in blocking_reasons:
            return "Voice requires OpenAI configuration."
        if "capture_dependency_missing" in blocking_reasons:
            return "Local capture provider is unavailable: dependency missing."
        if "capture_device_unavailable" in blocking_reasons:
            return "Local capture device is unavailable."
        if capture_ready:
            return "Push-to-talk ready."
        if "capture_disabled" in warnings:
            return "Capture disabled."
        if "playback_disabled" in warnings:
            return "Playback is unavailable, but response audio can be prepared."
        if blocking_reasons:
            return "Voice is unavailable."
        return "Voice readiness is degraded."

    def _readiness_next_setup_action(
        self,
        *,
        blocking_reasons: list[str],
        warnings: list[str],
        runtime_mode: VoiceRuntimeModeReadiness | None = None,
    ) -> str | None:
        if "voice_disabled" in blocking_reasons:
            return "Enable voice in configuration."
        if (
            runtime_mode is not None
            and runtime_mode.effective_mode != "manual_only"
            and runtime_mode.next_fix
        ):
            return runtime_mode.next_fix
        if "api_key_missing" in blocking_reasons:
            return "Configure an OpenAI API key."
        if "openai_disabled" in blocking_reasons:
            return "Enable OpenAI configuration."
        if "capture_dependency_missing" in blocking_reasons:
            return "Install or enable the local capture backend."
        if "capture_device_unavailable" in blocking_reasons:
            return "Check the configured capture device."
        if "capture_disabled" in warnings:
            return "Enable capture for push-to-talk."
        if "playback_disabled" in warnings:
            return "Enable playback only if local output is intended."
        return None

    def _dedupe_strings(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _capture_error_code(self) -> str | None:
        if self.last_capture_result is not None and self.last_capture_result.error_code:
            return self.last_capture_result.error_code
        return self.last_capture_error.get("code")

    def _capture_provider_availability(self) -> dict[str, Any]:
        operation = getattr(self.capture_provider, "get_availability", None)
        if not callable(operation):
            return {
                "provider": self._capture_provider_name(),
                "available": False,
                "unavailable_reason": "provider_unavailable",
                "mock": bool(getattr(self.capture_provider, "is_mock", False)),
            }
        try:
            value = operation()
        except Exception:
            return {
                "provider": self._capture_provider_name(),
                "available": False,
                "unavailable_reason": "provider_unavailable",
                "mock": bool(getattr(self.capture_provider, "is_mock", False)),
            }
        return dict(value) if isinstance(value, dict) else {}

    def _cleanup_captured_audio_after_turn(
        self, capture_result: VoiceCaptureResult
    ) -> str | None:
        audio_input = capture_result.audio_input
        if audio_input is None or not audio_input.file_path:
            return None
        if (
            capture_result.raw_audio_persisted
            or not self.config.capture.delete_transient_after_turn
        ):
            return None
        operation = getattr(self.capture_provider, "cleanup_capture_audio", None)
        if callable(operation):
            try:
                warning = operation(audio_input)
            except Exception as error:
                return str(error)
            return str(warning) if warning else None
        try:
            Path(audio_input.file_path).unlink(missing_ok=True)
        except Exception as error:
            return str(error)
        return None

    def _capture_provider_name(self) -> str:
        return (
            str(
                getattr(self.capture_provider, "name", self.config.capture.provider)
                or self.config.capture.provider
            )
            .strip()
            .lower()
        )

    def _vad_provider_name(self) -> str:
        return (
            str(getattr(self.vad_provider, "name", self.config.vad.provider) or "mock")
            .strip()
            .lower()
            or "mock"
        )

    def _vad_provider_availability(self) -> dict[str, Any]:
        operation = getattr(self.vad_provider, "get_availability", None)
        if not callable(operation):
            return self._unavailable_vad_payload("provider_unavailable")
        try:
            value = operation()
        except Exception:
            return self._unavailable_vad_payload("provider_unavailable")
        return dict(value) if isinstance(value, dict) else {}

    def _unavailable_vad_payload(self, reason: str) -> dict[str, Any]:
        return {
            "provider": self._vad_provider_name(),
            "provider_kind": "unavailable",
            "available": False,
            "unavailable_reason": reason,
            "mock_provider_active": bool(getattr(self.vad_provider, "is_mock", False)),
            "semantic_completion_claimed": False,
            "command_authority": False,
            "realtime_vad": False,
            "raw_audio_present": False,
        }

    def _realtime_provider_name(self) -> str:
        return (
            str(
                getattr(self.realtime_provider, "name", self.config.realtime.provider)
                or "unavailable"
            )
            .strip()
            .lower()
            or "unavailable"
        )

    def _realtime_provider_availability(self) -> dict[str, Any]:
        operation = getattr(self.realtime_provider, "get_availability", None)
        if not callable(operation):
            return self._unavailable_realtime_payload("provider_unavailable")
        try:
            value = operation()
        except Exception:
            return self._unavailable_realtime_payload("provider_unavailable")
        return dict(value) if isinstance(value, dict) else {}

    def _unavailable_realtime_payload(self, reason: str) -> dict[str, Any]:
        return {
            "provider": self._realtime_provider_name(),
            "provider_kind": "unavailable",
            "available": False,
            "unavailable_reason": reason,
            "mode": self.config.realtime.mode,
            "model": self.config.realtime.model,
            "voice": self.config.realtime.voice,
            "turn_detection": self.config.realtime.turn_detection,
            "semantic_vad_enabled": bool(self.config.realtime.semantic_vad_enabled),
            "active": False,
            "direct_tools_allowed": False,
            "core_bridge_required": True,
            "speech_to_speech_enabled": bool(
                self.config.realtime.mode == "speech_to_speech_core_bridge"
                and self.config.realtime.speech_to_speech_enabled
            ),
            "audio_output_from_realtime": bool(
                self.config.realtime.mode == "speech_to_speech_core_bridge"
                and self.config.realtime.audio_output_from_realtime
            ),
            "core_bridge_tool_enabled": bool(
                self.config.realtime.mode == "speech_to_speech_core_bridge"
                and self.config.realtime.speech_to_speech_enabled
            ),
            "direct_action_tools_exposed": False,
            "require_core_for_commands": True,
            "openai_configured": bool(self.openai_config.enabled),
            "api_key_present": bool(self.openai_config.api_key),
            "mock_provider_active": bool(
                getattr(self.realtime_provider, "is_mock", False)
            ),
            "raw_audio_present": False,
            "cloud_wake_detection": False,
            "wake_detection_local_only": True,
            "command_authority": "stormhelm_core",
        }

    def _provider_active_vad_session(self) -> VoiceVADSession | None:
        operation = getattr(self.vad_provider, "get_active_detection", None)
        if not callable(operation):
            return None
        try:
            active = operation()
        except Exception:
            return None
        return active if isinstance(active, VoiceVADSession) else None

    def _start_vad_detection_sync(
        self,
        *,
        capture_id: str | None = None,
        listen_window_id: str | None = None,
        session_id: str | None = None,
    ) -> VoiceVADSession:
        availability = self._vad_provider_availability()
        if not self.config.vad.enabled:
            session = self._terminal_vad_session(
                status="failed",
                error_code="vad_disabled",
                error_message="VAD is disabled.",
                capture_id=capture_id,
                listen_window_id=listen_window_id,
                session_id=session_id,
            )
            self._remember_vad_session(session)
            return session
        if not availability.get("available"):
            session = self._terminal_vad_session(
                status="failed",
                error_code=str(
                    availability.get("unavailable_reason") or "vad_unavailable"
                ),
                error_message="VAD provider unavailable.",
                capture_id=capture_id,
                listen_window_id=listen_window_id,
                session_id=session_id,
            )
            self._remember_vad_session(session)
            self._publish_vad_session_event(
                VoiceEventType.VAD_ERROR,
                session,
                message=session.error_message or "VAD provider unavailable.",
            )
            return session
        operation = getattr(self.vad_provider, "start_detection", None)
        if not callable(operation):
            session = self._terminal_vad_session(
                status="failed",
                error_code="provider_unavailable",
                error_message="VAD provider does not implement detection.",
                capture_id=capture_id,
                listen_window_id=listen_window_id,
                session_id=session_id,
            )
        else:
            session = operation(
                capture_id=capture_id,
                listen_window_id=listen_window_id,
                session_id=session_id,
            )
        self._remember_vad_session(session)
        self._publish_vad_session_event(
            VoiceEventType.VAD_DETECTION_STARTED
            if session.status == "active"
            else VoiceEventType.VAD_ERROR,
            session,
            message="VAD detection started."
            if session.status == "active"
            else (session.error_message or "VAD detection failed."),
        )
        return session

    def _stop_vad_detection_sync(
        self,
        vad_session_id: str | None = None,
        *,
        reason: str = "stopped",
    ) -> VoiceVADSession:
        operation = getattr(self.vad_provider, "stop_detection", None)
        if callable(operation):
            session = operation(vad_session_id, reason=reason)
        else:
            active = self.get_active_vad_session()
            session = (
                replace(
                    active,
                    status="stopped",
                    stopped_at=self._now(),
                    finalization_reason=reason,
                )
                if active is not None
                else self._terminal_vad_session(
                    status="stopped",
                    error_code="no_active_vad",
                    error_message="No active VAD detection session exists.",
                )
            )
        self.active_vad_session = None
        self._remember_vad_session(session)
        self._publish_vad_session_event(
            VoiceEventType.VAD_DETECTION_STOPPED,
            session,
            message="VAD detection stopped.",
        )
        return session

    def _stop_vad_detection_for_capture(
        self, capture_id: str | None, *, reason: str
    ) -> VoiceVADSession | None:
        active = self.get_active_vad_session()
        if active is None or (capture_id and active.capture_id != capture_id):
            return None
        return self._stop_vad_detection_sync(active.vad_session_id, reason=reason)

    def _terminal_vad_session(
        self,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
        capture_id: str | None = None,
        listen_window_id: str | None = None,
        session_id: str | None = None,
    ) -> VoiceVADSession:
        return VoiceVADSession(
            provider=self._vad_provider_name(),
            provider_kind="unavailable",
            capture_id=capture_id,
            listen_window_id=listen_window_id,
            session_id=session_id,
            status=status,
            stopped_at=self._now(),
            error_code=error_code,
            error_message=error_message,
        )

    def _remember_vad_session(self, session: VoiceVADSession) -> VoiceVADSession:
        self.last_vad_session = session
        self.vad_sessions[session.vad_session_id] = session
        self.active_vad_session = session if session.status == "active" else None
        window = self._post_wake_listen_window_for_id(session.listen_window_id)
        if window is not None and session.listen_window_id:
            self._remember_post_wake_listen_window(
                replace(window, vad_session_id=session.vad_session_id)
            )
        return session

    def _remember_activity_event(self, event: VoiceActivityEvent) -> VoiceActivityEvent:
        self.last_activity_event = event
        self.activity_events[event.activity_event_id] = event
        return event

    def _mark_vad_speech_started(self, event: VoiceActivityEvent) -> None:
        session = self.get_active_vad_session()
        if session is None:
            return
        updated = replace(
            session,
            speech_started_at=event.timestamp,
            last_activity_event_id=event.activity_event_id,
        )
        self._remember_vad_session(updated)

    def _mark_vad_speech_stopped(self, event: VoiceActivityEvent) -> None:
        session = self.get_active_vad_session()
        if session is None:
            return
        updated = replace(
            session,
            speech_stopped_at=event.timestamp,
            last_activity_event_id=event.activity_event_id,
        )
        self._remember_vad_session(updated)

    def _vad_error_event(self, error_code: str) -> VoiceActivityEvent:
        return VoiceActivityEvent(
            provider=self._vad_provider_name(),
            provider_kind="unavailable",
            status="vad_error",
            metadata={"error_code": error_code},
        )

    def _publish_vad_session_event(
        self,
        event_type: VoiceEventType,
        session: VoiceVADSession,
        *,
        message: str,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=session.session_id,
            capture_id=session.capture_id,
            vad_session_id=session.vad_session_id,
            listen_window_id=session.listen_window_id,
            provider=session.provider,
            provider_kind=session.provider_kind,
            status=session.status,
            error_code=session.error_code,
            raw_audio_present=False,
            metadata={
                "vad_session": session.to_dict(),
                "semantic_completion_claimed": False,
                "command_authority": False,
                "realtime_vad": False,
            },
        )

    def _publish_activity_event(
        self,
        event_type: VoiceEventType,
        event: VoiceActivityEvent,
        message: str,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=event.session_id,
            capture_id=event.capture_id,
            vad_session_id=event.vad_session_id,
            activity_event_id=event.activity_event_id,
            listen_window_id=event.listen_window_id,
            provider=event.provider,
            provider_kind=event.provider_kind,
            status=event.status,
            confidence=event.confidence,
            duration_ms=event.duration_ms,
            silence_ms=event.silence_ms,
            raw_audio_present=False,
            metadata={
                "activity_event": event.to_dict(),
                "semantic_completion_claimed": False,
                "command_intent_claimed": False,
                "core_routed": False,
            },
        )

    def _wake_provider_name(self) -> str:
        return (
            str(
                getattr(self.wake_provider, "name", self.config.wake.provider) or "mock"
            )
            .strip()
            .lower()
            or "mock"
        )

    def _wake_provider_availability(self) -> dict[str, Any]:
        operation = getattr(self.wake_provider, "get_availability", None)
        if not callable(operation):
            return {
                "provider": self._wake_provider_name(),
                "provider_kind": "unavailable",
                "available": False,
                "unavailable_reason": "provider_unavailable",
                "mock_provider_active": bool(
                    getattr(self.wake_provider, "is_mock", False)
                ),
                "real_microphone_monitoring": False,
                "no_cloud_wake_audio": True,
                "openai_used": False,
                "raw_audio_present": False,
                "always_listening": False,
            }
        try:
            value = operation()
        except Exception:
            return {
                "provider": self._wake_provider_name(),
                "provider_kind": "unavailable",
                "available": False,
                "unavailable_reason": "provider_unavailable",
                "mock_provider_active": bool(
                    getattr(self.wake_provider, "is_mock", False)
                ),
                "real_microphone_monitoring": False,
                "no_cloud_wake_audio": True,
                "openai_used": False,
                "raw_audio_present": False,
                "always_listening": False,
            }
        if isinstance(value, VoiceAvailability):
            return {
                "provider": value.provider_name,
                "provider_kind": "mock"
                if value.mock_provider_active
                else value.provider_name,
                "available": value.available,
                "unavailable_reason": value.unavailable_reason,
                "mock_provider_active": value.mock_provider_active,
                "real_microphone_monitoring": False,
                "no_cloud_wake_audio": True,
                "openai_used": False,
                "raw_audio_present": False,
                "always_listening": False,
            }
        return dict(value) if isinstance(value, dict) else {}

    def _wake_block_reason(self) -> str | None:
        if (
            not self.config.enabled
            or str(self.config.mode or "").strip().lower() == "disabled"
        ):
            return "voice_disabled"
        if not self.config.wake.enabled:
            return "wake_disabled"
        availability = self._wake_provider_availability()
        if not availability.get("available"):
            return str(availability.get("unavailable_reason") or "wake_unavailable")
        return None

    def _wake_simulation_block_reason(self) -> str | None:
        block_reason = self._wake_block_reason()
        if block_reason is not None:
            return block_reason
        provider_kind = (
            str(self._wake_provider_availability().get("provider_kind") or "")
            .strip()
            .lower()
        )
        if provider_kind != "mock" or not bool(
            getattr(self.wake_provider, "is_mock", False)
        ):
            return "mock_wake_required"
        if not self.config.wake.allow_dev_wake:
            return "dev_wake_not_allowed"
        return None

    def _wake_cooldown_active(self) -> bool:
        if self._last_wake_event_monotonic_ms is None:
            return False
        cooldown = int(self.config.wake.cooldown_ms or 0)
        if cooldown <= 0:
            return False
        return (
            time.monotonic() * 1000.0 - self._last_wake_event_monotonic_ms
        ) < cooldown

    def _blocked_wake_event(
        self,
        *,
        reason: str,
        session_id: str | None = None,
        confidence: float | None = None,
        source: str = "mock",
        cooldown_active: bool = False,
    ) -> VoiceWakeEvent:
        availability = self._wake_provider_availability()
        return VoiceWakeEvent(
            provider=self._wake_provider_name(),
            provider_kind=str(availability.get("provider_kind") or "unavailable"),
            backend=availability.get("backend"),
            device=availability.get("device"),
            wake_phrase=self.config.wake.wake_phrase,
            confidence=0.0 if confidence is None else confidence,
            session_id=session_id,
            accepted=False,
            rejected_reason=reason,
            cooldown_active=cooldown_active,
            false_positive_candidate=True,
            source=source,
            status="rejected",
            metadata={
                "blocking_reason": reason,
                "voice10_foundation_only": True,
                "openai_wake_detection": False,
            },
        )

    def _remember_wake_event(self, event: VoiceWakeEvent) -> VoiceWakeEvent:
        self.last_wake_event = event
        self.wake_events[event.wake_event_id] = event
        return event

    def _resolve_wake_event(
        self, wake_event_id: str | None = None
    ) -> VoiceWakeEvent | None:
        if wake_event_id:
            return self.wake_events.get(str(wake_event_id))
        return self.last_wake_event

    def _remember_wake_session(self, session: VoiceWakeSession) -> VoiceWakeSession:
        self.last_wake_session = session
        self.wake_sessions[session.wake_session_id] = session
        if session.status == "active":
            self.active_wake_session = session
        elif (
            self.active_wake_session is not None
            and self.active_wake_session.wake_session_id == session.wake_session_id
        ):
            self.active_wake_session = None
        return session

    def _remember_wake_ghost_request(
        self,
        request: VoiceWakeGhostRequest,
    ) -> VoiceWakeGhostRequest:
        self.last_wake_ghost_request = request
        self.wake_ghost_requests[request.wake_ghost_request_id] = request
        if request.status in {"requested", "shown"}:
            self.active_wake_ghost_request = request
        elif (
            self.active_wake_ghost_request is not None
            and self.active_wake_ghost_request.wake_ghost_request_id
            == request.wake_ghost_request_id
        ):
            self.active_wake_ghost_request = None
        return request

    def _resolve_wake_session(
        self, wake_session_id: str | None = None
    ) -> VoiceWakeSession | None:
        if wake_session_id:
            return self.wake_sessions.get(str(wake_session_id))
        return self.active_wake_session or self.last_wake_session

    def _resolve_wake_ghost_request(
        self,
        wake_session_id: str | None = None,
    ) -> VoiceWakeGhostRequest | None:
        if wake_session_id:
            for request in self.wake_ghost_requests.values():
                if request.wake_session_id == wake_session_id:
                    return request
            return None
        return self.active_wake_ghost_request or self.last_wake_ghost_request

    def _terminal_wake_session(
        self,
        *,
        status: str,
        wake_event_id: str,
        session_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        confidence: float = 0.0,
        source: str = "mock",
    ) -> VoiceWakeSession:
        return VoiceWakeSession(
            wake_event_id=wake_event_id,
            session_id=session_id or "default",
            source=source,
            confidence=confidence,
            expires_at=self._wake_session_expires_at(),
            status=status,
            error_code=error_code,
            error_message=error_message,
            metadata={"voice10_foundation_only": True},
        )

    def _terminal_wake_ghost_request(
        self,
        *,
        status: str,
        wake_session_id: str,
        reason: str,
    ) -> VoiceWakeGhostRequest:
        session = self._resolve_wake_session(wake_session_id)
        event = self._resolve_wake_event(session.wake_event_id) if session else None
        request = VoiceWakeGhostRequest(
            wake_event_id=event.wake_event_id if event is not None else "missing",
            wake_session_id=wake_session_id,
            session_id=session.session_id if session is not None else "default",
            wake_phrase=event.wake_phrase
            if event is not None
            else self.config.wake.wake_phrase,
            confidence=event.confidence if event is not None else 0.0,
            status=status,
            expires_at=session.expires_at if session is not None else None,
            reason=reason,
            metadata={"wake_to_ghost_presentation_only": True},
        )
        self._remember_wake_ghost_request(request)
        self._publish_wake_ghost_event(
            VoiceEventType.WAKE_GHOST_FAILED
            if status in {"failed", "blocked"}
            else VoiceEventType.WAKE_GHOST_CANCELLED,
            request=request,
            message=f"Wake Ghost request {status}: {reason}.",
            error_code=reason,
        )
        return request

    def _show_wake_ghost_for_session(
        self,
        session: VoiceWakeSession,
        *,
        reason: str,
    ) -> VoiceWakeGhostRequest:
        event = self._resolve_wake_event(session.wake_event_id)
        if event is None or session.status != "active":
            return self._terminal_wake_ghost_request(
                status="blocked",
                wake_session_id=session.wake_session_id,
                reason="wake_session_not_active",
            )
        existing = self._resolve_wake_ghost_request(session.wake_session_id)
        if existing is not None and existing.status in {"requested", "shown"}:
            return existing
        requested = VoiceWakeGhostRequest(
            wake_event_id=event.wake_event_id,
            wake_session_id=session.wake_session_id,
            session_id=session.session_id,
            wake_phrase=event.wake_phrase,
            confidence=event.confidence,
            status="requested",
            expires_at=session.expires_at,
            reason=reason,
            metadata={
                "wake_to_ghost_presentation_only": True,
                "wake_provider": event.provider,
                "wake_provider_kind": event.provider_kind,
            },
        )
        self._remember_wake_ghost_request(requested)
        self._publish_wake_ghost_event(
            VoiceEventType.WAKE_GHOST_REQUESTED,
            request=requested,
            message="Wake requested Ghost presentation.",
        )
        shown = replace(requested, status="shown")
        self._remember_wake_ghost_request(shown)
        self._publish_wake_ghost_event(
            VoiceEventType.WAKE_GHOST_SHOWN,
            request=shown,
            message="Wake Ghost presentation shown.",
        )
        return shown

    def _expire_wake_ghost_for_session(
        self,
        wake_session_id: str | None = None,
    ) -> VoiceWakeGhostRequest:
        request = self._resolve_wake_ghost_request(wake_session_id)
        if request is None:
            return self._terminal_wake_ghost_request(
                status="expired",
                wake_session_id=wake_session_id or "missing",
                reason="wake_ghost_missing",
            )
        if request.status == "expired":
            return request
        expired = replace(request, status="expired", reason="wake_session_expired")
        self._remember_wake_ghost_request(expired)
        self._publish_wake_ghost_event(
            VoiceEventType.WAKE_GHOST_EXPIRED,
            request=expired,
            message="Wake Ghost presentation expired.",
            error_code=expired.reason,
        )
        return expired

    def _cancel_wake_ghost_for_session(
        self,
        wake_session_id: str | None = None,
        *,
        reason: str = "operator_dismissed",
    ) -> VoiceWakeGhostRequest:
        request = self._resolve_wake_ghost_request(wake_session_id)
        if request is None:
            return self._terminal_wake_ghost_request(
                status="cancelled",
                wake_session_id=wake_session_id or "missing",
                reason="wake_ghost_missing",
            )
        if request.status == "cancelled":
            return request
        cancelled = replace(
            request,
            status="cancelled",
            reason=str(reason or "operator_dismissed").strip() or "operator_dismissed",
        )
        self._remember_wake_ghost_request(cancelled)
        self._publish_wake_ghost_event(
            VoiceEventType.WAKE_GHOST_CANCELLED,
            request=cancelled,
            message="Wake Ghost presentation cancelled.",
            error_code=cancelled.reason,
        )
        return cancelled

    def _wake_session_expires_at(self) -> str:
        return (
            datetime.now(timezone.utc)
            + timedelta(milliseconds=int(self.config.wake.max_wake_session_ms or 1))
        ).isoformat()

    def _publish_wake_ghost_event(
        self,
        event_type: VoiceEventType,
        *,
        request: VoiceWakeGhostRequest,
        message: str,
        error_code: str | None = None,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=request.session_id,
            wake_event_id=request.wake_event_id,
            wake_session_id=request.wake_session_id,
            wake_ghost_request_id=request.wake_ghost_request_id,
            wake_phrase=request.wake_phrase,
            provider=self._wake_provider_name(),
            provider_kind=str(
                self._wake_provider_availability().get("provider_kind")
                or self._wake_provider_name()
            ),
            confidence=request.confidence,
            openai_used=False,
            raw_audio_present=False,
            mode="wake_to_ghost",
            state="wake_ready" if request.status == "shown" else request.status,
            status=request.status,
            source="wake",
            error_code=error_code,
            metadata={
                "wake_ghost_request": request.to_dict(),
                "wake_to_ghost_presentation_only": True,
                "capture_started": False,
                "stt_started": False,
                "core_routed": False,
                "voice_turn_created": False,
                "command_authority_granted": False,
                "openai_wake_detection": False,
            },
        )

    def _publish_wake_event(
        self,
        event_type: VoiceEventType,
        *,
        message: str,
        wake_event: VoiceWakeEvent | None = None,
        wake_session: VoiceWakeSession | None = None,
        status: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=(
                wake_session.session_id
                if wake_session is not None
                else (wake_event.session_id if wake_event is not None else None)
            ),
            wake_event_id=wake_event.wake_event_id if wake_event is not None else None,
            wake_session_id=(
                wake_session.wake_session_id if wake_session is not None else None
            ),
            provider=(
                wake_event.provider
                if wake_event is not None
                else self._wake_provider_name()
            ),
            provider_kind=(
                wake_event.provider_kind
                if wake_event is not None
                else str(
                    self._wake_provider_availability().get("provider_kind")
                    or self._wake_provider_name()
                )
            ),
            backend=(
                wake_event.backend
                if wake_event is not None
                else self._wake_provider_availability().get("backend")
            ),
            confidence=wake_event.confidence if wake_event is not None else None,
            accepted=wake_event.accepted if wake_event is not None else None,
            rejected_reason=(
                wake_event.rejected_reason if wake_event is not None else None
            ),
            cooldown_active=(
                wake_event.cooldown_active if wake_event is not None else None
            ),
            false_positive_candidate=(
                wake_event.false_positive_candidate if wake_event is not None else None
            ),
            openai_used=False,
            cloud_used=False,
            raw_audio_present=False,
            device=(
                wake_event.device
                if wake_event is not None
                else self._wake_provider_availability().get("device")
            ),
            mode="wake_foundation",
            state=self.state_controller.snapshot().state.value,
            status=status,
            source="wake",
            error_code=error_code,
            metadata={
                "wake_event": wake_event.to_dict() if wake_event is not None else None,
                "wake_session": wake_session.to_dict()
                if wake_session is not None
                else None,
                "no_cloud_wake_audio": True,
                "openai_wake_detection": False,
                "cloud_wake_detection": False,
                "local_wake_provider_boundary": True,
                "voice11_local_provider_boundary": True,
            },
        )

    def _active_capture(self) -> VoiceCaptureSession | None:
        operation = getattr(self.capture_provider, "get_active_capture", None)
        if not callable(operation):
            return None
        try:
            value = operation()
        except Exception:
            return None
        return value if isinstance(value, VoiceCaptureSession) else None

    def _capture_turn_availability(self) -> VoiceAvailability:
        if self.availability.available:
            return self.availability
        if self.config.debug_mock_provider and self.config.capture.allow_dev_capture:
            return replace(
                self.availability,
                available=True,
                unavailable_reason=None,
                provider_configured=True,
                stt_allowed=True,
                mock_provider_active=True,
            )
        return self.availability

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _tts_request_block_reason(self, request: VoiceSpeechRequest) -> str | None:
        if (
            not self.config.enabled
            or str(self.config.mode or "").strip().lower() == "disabled"
        ):
            return "voice_disabled"
        suppression_reason = self._speech_output_block_reason(request.turn_id)
        if suppression_reason is not None:
            return suppression_reason
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
        if request.source != "core_spoken_summary" and any(
            phrase in lowered for phrase in _UNSAFE_UNAPPROVED_PHRASES
        ):
            return "unsafe_speech_text"
        if (
            "verified" in lowered
            and str(request.result_state_source or "").strip().lower() != "verified"
        ):
            return "unsupported_verification_claim"
        return None

    async def _synthesize_with_provider(
        self, request: VoiceSpeechRequest
    ) -> VoiceSpeechSynthesisResult:
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

    def _streaming_speech_blocked_result(
        self,
        request: VoiceSpeechRequest,
        *,
        error_code: str,
        error_message: str,
    ) -> VoiceStreamingSpeechOutputResult:
        latency = VoiceFirstAudioLatency(
            streaming_enabled=bool(self.config.openai.stream_tts_outputs),
            streaming_transport_kind="blocked",
            first_chunk_before_complete=False,
            live_format=self._tts_live_format_name(),
            artifact_format=self._tts_artifact_format_name(),
            fallback_used=False,
            prewarm_used=self.last_voice_output_prewarm_result is not None,
            prewarm_ms=(
                self.last_voice_output_prewarm_result.prewarm_ms
                if self.last_voice_output_prewarm_result is not None
                else None
            ),
            playback_prewarmed=bool(
                self.last_playback_prewarm_result
                and self.last_playback_prewarm_result.ok
            ),
            provider_prewarmed=bool(
                self.last_provider_prewarm_result and self.last_provider_prewarm_result.ok
            ),
            first_audio_available=False,
            streaming_miss_reason=error_code,
            user_heard_claimed=False,
        )
        self.last_first_audio_latency = latency
        return VoiceStreamingSpeechOutputResult(
            ok=False,
            status="blocked",
            speech_request_id=request.speech_request_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            streaming_enabled=bool(self.config.openai.stream_tts_outputs),
            first_audio_available=False,
            streaming_transport_kind="blocked",
            first_chunk_before_complete=False,
            streaming_miss_reason=error_code,
            latency=latency,
            error_code=error_code,
            error_message=error_message,
            metadata={"speech_request": request.to_metadata()},
        )

    def _remember_synthesis_result(
        self, result: VoiceSpeechSynthesisResult
    ) -> VoiceSpeechSynthesisResult:
        self.last_speech_request = result.speech_request
        self.last_synthesis_result = result
        audio_output = result.audio_output
        if (
            result.ok
            and audio_output is not None
            and audio_output.data
            and str(audio_output.format or "").strip().lower() in {"pcm", "wav"}
        ):
            self._remember_voice_output_envelope(
                audio_output.data,
                audio_format=audio_output.format,
                source="precomputed_artifact_envelope",
            )
        if result.error_code:
            self.last_error = {
                "code": result.error_code,
                "message": result.error_message,
            }
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
            audio_output_id=audio_output.output_id
            if audio_output is not None
            else None,
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
            data=audio_output.data if audio_output is not None else None,
        )

    def _playback_request_block_reason(
        self, request: VoicePlaybackRequest
    ) -> str | None:
        if (
            not self.config.enabled
            or str(self.config.mode or "").strip().lower() == "disabled"
        ):
            return "voice_disabled"
        suppression_reason = self._speech_output_block_reason(request.turn_id)
        if suppression_reason is not None:
            return suppression_reason
        if not self.config.playback.enabled:
            return "playback_disabled"
        if not self.availability.available and not (
            self.config.debug_mock_provider and self.config.playback.allow_dev_playback
        ):
            return self.availability.unavailable_reason or "voice_unavailable"
        if request.blocked_reason:
            return request.blocked_reason
        if not request.audio_output_id or (
            not request.audio_ref and not request.file_path
        ):
            return "missing_audio_output"
        if request.size_bytes <= 0:
            return "empty_audio_output"
        if request.size_bytes > int(self.config.playback.max_audio_bytes or 0):
            return "audio_too_large"
        if request.duration_ms is not None and request.duration_ms > int(
            self.config.playback.max_duration_ms or 0
        ):
            return "audio_too_long"
        if request.format not in _SUPPORTED_PLAYBACK_FORMATS:
            return "unsupported_playback_format"
        if request.expires_at and self._is_expired(request.expires_at):
            return "audio_output_expired"
        return None

    async def _play_with_provider(
        self, request: VoicePlaybackRequest
    ) -> VoicePlaybackResult:
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

    def _remember_playback_result(
        self, result: VoicePlaybackResult
    ) -> VoicePlaybackResult:
        self.last_playback_result = result
        if result.error_code:
            self.last_error = {
                "code": result.error_code,
                "message": result.error_message,
            }
        else:
            self.last_error = {"code": None, "message": None}
        return result

    def _remember_interruption_result(
        self, request: VoiceInterruptionRequest, result: VoiceInterruptionResult
    ) -> VoiceInterruptionResult:
        self.last_interruption_request = request
        self.last_interruption_result = result
        if result.error_code:
            self.last_error = {
                "code": result.error_code,
                "message": result.error_message,
            }
        else:
            self.last_error = {"code": None, "message": None}
        if result.status in {
            "completed",
            "no_active_playback",
            "no_active_output",
            "routed_to_core",
        }:
            event_type = VoiceEventType.INTERRUPTION_COMPLETED
        elif result.status in {
            "blocked",
            "unsupported",
            "unavailable",
            "no_active_capture",
            "no_active_listen_window",
            "no_pending_confirmation",
        }:
            event_type = VoiceEventType.INTERRUPTION_BLOCKED
        else:
            event_type = VoiceEventType.INTERRUPTION_FAILED
        self._publish_interruption_event(
            event_type,
            request,
            result=result,
            status=result.status,
            message="Voice interruption completed."
            if event_type == VoiceEventType.INTERRUPTION_COMPLETED
            else "Voice interruption did not complete.",
        )
        return result

    def _publish_interruption_trace_event(
        self,
        event_type: VoiceEventType,
        request: VoiceInterruptionRequest,
        *,
        classification: VoiceInterruptionClassification | None = None,
        result: VoiceInterruptionResult | None = None,
        status: str,
        message: str,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=request.session_id,
            turn_id=request.turn_id,
            playback_id=request.playback_id
            or (result.affected_playback_id if result is not None else None),
            capture_id=request.capture_id
            or (result.affected_capture_id if result is not None else None),
            listen_window_id=request.listen_window_id
            or (result.affected_listen_window_id if result is not None else None),
            realtime_session_id=request.realtime_session_id
            or (result.affected_realtime_session_id if result is not None else None),
            pending_confirmation_id=request.pending_confirmation_id
            or (result.affected_confirmation_id if result is not None else None),
            interruption_id=request.interruption_id,
            intent=(classification.intent.value if classification is not None else request.intent.value),
            status=status,
            source=request.source,
            correlation_id=request.active_loop_id,
            error_code=result.error_code if result is not None else None,
            core_task_cancelled=False,
            core_result_mutated=False,
            spoken_output_suppressed=result.spoken_output_suppressed
            if result is not None
            else None,
            action_executed=False,
            metadata={
                "interruption_request": request.to_dict(),
                "interruption_classification": classification.to_dict()
                if classification is not None
                else None,
                "interruption_result": result.to_dict() if result is not None else None,
                "core_task_cancelled": False,
                "core_result_mutated": False,
                "output_stopped": result.output_stopped if result is not None else False,
                "capture_cancelled": result.capture_cancelled if result is not None else False,
                "listen_window_cancelled": result.listen_window_cancelled
                if result is not None
                else False,
                "realtime_session_cancelled": result.realtime_session_cancelled
                if result is not None
                else False,
                "confirmation_rejected": result.confirmation_rejected
                if result is not None
                else False,
                "routed_to_core": result.status == "routed_to_core"
                if result is not None
                else False,
                "ambiguity_reason": classification.ambiguity_reason
                if classification is not None
                else None,
            },
        )

    def _publish_interruption_event(
        self,
        event_type: VoiceEventType,
        request: VoiceInterruptionRequest,
        *,
        result: VoiceInterruptionResult | None = None,
        status: str,
        message: str,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=request.session_id,
            turn_id=request.turn_id,
            playback_id=request.playback_id
            or (result.affected_playback_id if result is not None else None),
            capture_id=request.capture_id
            or (result.affected_capture_id if result is not None else None),
            listen_window_id=request.listen_window_id
            or (result.affected_listen_window_id if result is not None else None),
            realtime_session_id=request.realtime_session_id
            or (result.affected_realtime_session_id if result is not None else None),
            pending_confirmation_id=request.pending_confirmation_id
            or (result.affected_confirmation_id if result is not None else None),
            interruption_id=request.interruption_id,
            intent=request.intent.value,
            muted_scope=request.muted_scope
            or (result.muted_scope if result is not None else None),
            status=status,
            source=request.source,
            correlation_id=request.active_loop_id,
            error_code=result.error_code if result is not None else None,
            core_task_cancelled=False,
            core_result_mutated=False,
            action_executed=False,
            spoken_output_suppressed=result.spoken_output_suppressed
            if result is not None
            else None,
            metadata={
                "interruption_request": request.to_dict(),
                "interruption_result": result.to_dict() if result is not None else None,
            },
        )

    def _speech_output_block_reason(self, turn_id: str | None = None) -> str | None:
        if self.spoken_output_muted:
            return "spoken_output_muted"
        if self.current_response_suppressed and (
            self.suppressed_turn_id is None or self.suppressed_turn_id == turn_id
        ):
            return "current_response_suppressed"
        return None

    def _playback_provider_name(self) -> str:
        return (
            str(
                getattr(self.playback_provider, "name", self.config.playback.provider)
                or self.config.playback.provider
            )
            .strip()
            .lower()
        )

    def _playback_provider_availability(self) -> dict[str, Any]:
        operation = getattr(self.playback_provider, "get_availability", None)
        if callable(operation):
            try:
                value = operation()
            except Exception as error:
                return {
                    "provider": self._playback_provider_name(),
                    "available": False,
                    "unavailable_reason": str(error),
                }
            if isinstance(value, dict):
                return dict(value)
        return {
            "provider": self._playback_provider_name(),
            "available": False,
            "unavailable_reason": "provider_unavailable",
        }

    def _active_playback(self) -> VoicePlaybackResult | None:
        operation = getattr(self.playback_provider, "get_active_playback", None)
        if not callable(operation):
            return None
        try:
            value = operation()
        except Exception:
            return None
        return value if isinstance(value, VoicePlaybackResult) else None

    def _active_playback_stream(self) -> VoiceLivePlaybackSession | None:
        operation = getattr(self.playback_provider, "get_active_playback_stream", None)
        if not callable(operation):
            return None
        try:
            value = operation()
        except Exception:
            return None
        return value if isinstance(value, VoiceLivePlaybackSession) else None

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
        current_state = self.state_controller.snapshot().state
        if current_state == VoiceState.SPEAKING:
            return
        try:
            if current_state == VoiceState.DORMANT:
                self.state_controller.transition_to(
                    VoiceState.SPEAKING_READY,
                    event_id=self._last_event_id(),
                    turn_id=request.turn_id,
                    source="playback",
                )
            self.state_controller.transition_to(
                VoiceState.SPEAKING,
                event_id=self._last_event_id(),
                turn_id=request.turn_id,
                source="playback",
            )
        except VoiceTransitionError:
            return

    def _transition_from_speaking(
        self, *, completed: bool = False, stopped: bool = False
    ) -> None:
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
        if (
            not self.config.enabled
            or str(self.config.mode or "").strip().lower() == "disabled"
        ):
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
        if (
            not self.config.enabled
            or str(self.config.mode or "").strip().lower() == "disabled"
        ):
            return False, "voice_disabled", False
        if self.availability.available and self.availability.stt_allowed:
            return True, None, False
        if self.config.debug_mock_provider:
            return True, None, True
        return (
            False,
            self.availability.unavailable_reason or "provider_unavailable",
            False,
        )

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
            return (
                "invalid_audio_input",
                "Audio voice turn requires a typed VoiceAudioInput.",
            )
        source = str(audio.source or "").strip().lower()
        if source not in {"file", "bytes", "fixture", "mock"}:
            return (
                "unsupported_audio_source",
                f"Unsupported voice audio source: {source or 'unknown'}.",
            )
        if source == "file":
            file_path = Path(str(audio.file_path or ""))
            if not audio.file_path or not file_path.exists() or not file_path.is_file():
                return "missing_audio_file", "Voice audio file was missing."
        if audio.size_bytes <= 0:
            return "empty_audio", "Voice audio input was empty."
        max_audio_bytes = int(self.config.openai.max_audio_bytes or 0)
        if max_audio_bytes > 0 and audio.size_bytes > max_audio_bytes:
            return (
                "audio_too_large",
                "Voice audio input exceeded the configured size limit.",
            )
        max_audio_seconds = float(self.config.openai.max_audio_seconds or 0)
        if (
            max_audio_seconds > 0
            and audio.duration_ms is not None
            and audio.duration_ms > int(max_audio_seconds * 1000)
        ):
            return (
                "audio_too_long",
                "Voice audio input exceeded the configured duration limit.",
            )
        mime_type = str(audio.mime_type or "").strip().lower()
        if mime_type not in _SUPPORTED_AUDIO_MIME_TYPES:
            return (
                "unsupported_audio_type",
                f"Unsupported voice audio MIME type: {mime_type or 'unknown'}.",
            )
        return None

    async def _transcribe_audio(
        self, audio: VoiceAudioInput
    ) -> VoiceTranscriptionResult:
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
            transcript = " ".join(
                str(result.payload.get("transcript") or "").split()
            ).strip()
            return VoiceTranscriptionResult(
                ok=result.ok and bool(transcript),
                input_id=audio.input_id,
                provider=result.provider_name,
                model=self._stt_model_name(),
                transcript=transcript,
                confidence=result.payload.get("confidence")
                if isinstance(result.payload.get("confidence"), float)
                else None,
                error_code=result.error_code
                or (None if transcript else "empty_transcript"),
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

    def _apply_transcription_quality_rules(
        self, result: VoiceTranscriptionResult
    ) -> VoiceTranscriptionResult:
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
        if result_state in {
            "pending_approval",
            "requires_confirmation",
            "awaiting_confirmation",
        }:
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
            state_transitions=list(
                state_transitions or [self.state_controller.snapshot().to_dict()]
            ),
            error_code=error_code,
            error_message=error_message,
            provider_network_call_count=self._provider_network_call_count(),
        )
        return self._remember_turn_result(result)

    def _remember_turn_result(self, result: VoiceTurnResult) -> VoiceTurnResult:
        self.last_manual_turn_result = result
        if result.error_code:
            self.last_error = {
                "code": result.error_code,
                "message": result.error_message,
            }
        else:
            self.last_error = {"code": None, "message": None}
        return result

    def _remember_audio_turn_result(self, result: VoiceTurnResult) -> VoiceTurnResult:
        self.last_audio_turn_result = result
        if result.transcription_result is not None:
            self.last_transcription_result = result.transcription_result
        if result.error_code:
            self.last_error = {
                "code": result.error_code,
                "message": result.error_message,
            }
        else:
            self.last_error = {"code": None, "message": None}
        return result

    def _remember_realtime_session(
        self, session: VoiceRealtimeSession
    ) -> VoiceRealtimeSession:
        self.last_realtime_session = session
        self.realtime_sessions[session.realtime_session_id] = session
        self.active_realtime_session = (
            session if session.status in {"created", "connecting", "active"} else None
        )
        return session

    def _remember_realtime_transcript_event(
        self, event: VoiceRealtimeTranscriptEvent
    ) -> VoiceRealtimeTranscriptEvent:
        self.last_realtime_transcript_event = event
        self.realtime_transcript_events[event.realtime_event_id] = event
        active = self.active_realtime_session
        if active is not None and active.realtime_session_id == event.realtime_session_id:
            self.active_realtime_session = replace(
                active,
                active_turn_id=event.realtime_turn_id,
                last_event_id=event.realtime_event_id,
            )
            self.realtime_sessions[active.realtime_session_id] = (
                self.active_realtime_session
            )
        return event

    def _remember_realtime_turn_result(
        self, result: VoiceRealtimeTurnResult
    ) -> VoiceRealtimeTurnResult:
        self.last_realtime_turn_result = result
        if result.error_code:
            self.last_error = {"code": result.error_code, "message": result.error_message}
        return result

    def _remember_realtime_core_bridge_call(
        self, call: VoiceRealtimeCoreBridgeCall
    ) -> VoiceRealtimeCoreBridgeCall:
        self.last_realtime_core_bridge_call = call
        self.realtime_core_bridge_calls[call.core_bridge_call_id] = call
        active = self.active_realtime_session
        if active is not None and (
            call.realtime_session_id is None
            or active.realtime_session_id == call.realtime_session_id
        ):
            self.active_realtime_session = replace(
                active,
                active_turn_id=call.realtime_turn_id or active.active_turn_id,
                last_core_bridge_call_id=call.core_bridge_call_id,
                last_core_result_state=call.result_state,
            )
            self.realtime_sessions[active.realtime_session_id] = (
                self.active_realtime_session
            )
            self.last_realtime_session = self.active_realtime_session
        return call

    def _remember_realtime_response_gate(
        self, gate: VoiceRealtimeResponseGate
    ) -> VoiceRealtimeResponseGate:
        self.last_realtime_response_gate = gate
        self.realtime_response_gates[gate.response_gate_id] = gate
        active = self.active_realtime_session
        if active is not None and (
            gate.realtime_session_id is None
            or active.realtime_session_id == gate.realtime_session_id
        ):
            self.active_realtime_session = replace(
                active,
                active_turn_id=gate.realtime_turn_id or active.active_turn_id,
                last_spoken_summary_source=gate.spoken_summary_source,
            )
            self.realtime_sessions[active.realtime_session_id] = (
                self.active_realtime_session
            )
            self.last_realtime_session = self.active_realtime_session
        return gate

    def _terminal_realtime_session(
        self,
        *,
        session_id: str | None,
        source: str,
        listen_window_id: str | None,
        capture_id: str | None,
        status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> VoiceRealtimeSession:
        return VoiceRealtimeSession(
            provider=self._realtime_provider_name(),
            provider_kind="unavailable",
            mode=self.config.realtime.mode,
            model=self.config.realtime.model,
            voice=self.config.realtime.voice,
            session_id=session_id or "default",
            source=source,
            status=status,
            closed_at=self._now(),
            turn_detection_mode=self.config.realtime.turn_detection,
            semantic_vad_enabled=bool(self.config.realtime.semantic_vad_enabled),
            speech_to_speech_enabled=bool(
                self.config.realtime.speech_to_speech_enabled
            ),
            audio_output_from_realtime=bool(
                self.config.realtime.audio_output_from_realtime
            ),
            listen_window_id=listen_window_id,
            capture_id=capture_id,
            error_code=error_code,
            error_message=error_message,
        )

    def _realtime_session_expires_at(self) -> str:
        return (
            datetime.now(timezone.utc)
            + timedelta(milliseconds=int(self.config.realtime.max_session_ms or 1))
        ).isoformat()

    def _publish_realtime_session_event(
        self,
        event_type: VoiceEventType,
        session: VoiceRealtimeSession,
        *,
        message: str,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=session.session_id,
            listen_window_id=session.listen_window_id,
            capture_id=session.capture_id,
            realtime_session_id=session.realtime_session_id,
            realtime_turn_id=session.active_turn_id,
            provider=session.provider,
            provider_kind=session.provider_kind,
            model=session.model,
            voice=session.voice,
            mode=session.mode,
            source=session.source,
            status=session.status,
            error_code=session.error_code,
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=session.speech_to_speech_enabled,
            audio_output_from_realtime=session.audio_output_from_realtime,
            raw_audio_present=False,
            metadata={
                "realtime_session": session.to_dict(),
                "realtime_transcription_bridge_only": (
                    session.mode == "transcription_bridge"
                ),
                "core_bridge_tool_enabled": session.core_bridge_tool_enabled,
                "direct_action_tools_exposed": session.direct_action_tools_exposed,
            },
        )

    def _publish_realtime_transcript_event(
        self,
        event_type: VoiceEventType,
        event: VoiceRealtimeTranscriptEvent,
        *,
        message: str,
    ) -> None:
        self._publish(
            event_type,
            message=message,
            session_id=event.session_id,
            listen_window_id=event.listen_window_id,
            capture_id=event.capture_id,
            realtime_session_id=event.realtime_session_id,
            realtime_turn_id=event.realtime_turn_id,
            realtime_event_id=event.realtime_event_id,
            provider=self._realtime_provider_name(),
            provider_kind=self.realtime_readiness_report().realtime_provider_kind,
            model=self.config.realtime.model,
            mode=self.config.realtime.mode,
            source=event.source,
            confidence=event.confidence,
            is_partial=event.is_partial,
            is_final=event.is_final,
            direct_tools_allowed=False,
            core_bridge_required=True,
            speech_to_speech_enabled=bool(
                self.config.realtime.mode == "speech_to_speech_core_bridge"
                and self.config.realtime.speech_to_speech_enabled
            ),
            audio_output_from_realtime=bool(
                self.config.realtime.mode == "speech_to_speech_core_bridge"
                and self.config.realtime.audio_output_from_realtime
            ),
            raw_audio_present=False,
            metadata={
                "transcript_preview": event.transcript_preview,
                "provider_metadata": dict(event.provider_metadata),
                "realtime_transcript_event": event.to_dict(),
            },
        )

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
        capture_request_id: str | None = None,
        capture_id: str | None = None,
        interruption_id: str | None = None,
        wake_event_id: str | None = None,
        wake_session_id: str | None = None,
        wake_ghost_request_id: str | None = None,
        vad_session_id: str | None = None,
        activity_event_id: str | None = None,
        spoken_confirmation_intent_id: str | None = None,
        spoken_confirmation_request_id: str | None = None,
        spoken_confirmation_result_id: str | None = None,
        pending_confirmation_id: str | None = None,
        listen_window_id: str | None = None,
        realtime_session_id: str | None = None,
        realtime_turn_id: str | None = None,
        realtime_event_id: str | None = None,
        wake_phrase: str | None = None,
        intent: str | None = None,
        muted_scope: str | None = None,
        action_id: str | None = None,
        required_strength: str | None = None,
        provided_strength: str | None = None,
        binding_valid: bool | None = None,
        invalid_reason: str | None = None,
        consumed: bool | None = None,
        action_executed: bool | None = None,
        provider_kind: str | None = None,
        backend: str | None = None,
        core_task_cancelled: bool | None = None,
        core_result_mutated: bool | None = None,
        spoken_output_suppressed: bool | None = None,
        confidence: float | None = None,
        accepted: bool | None = None,
        rejected_reason: str | None = None,
        cooldown_active: bool | None = None,
        false_positive_candidate: bool | None = None,
        openai_used: bool | None = None,
        cloud_used: bool | None = None,
        raw_audio_present: bool | None = None,
        is_partial: bool | None = None,
        is_final: bool | None = None,
        direct_tools_allowed: bool | None = None,
        core_bridge_required: bool | None = None,
        speech_to_speech_enabled: bool | None = None,
        audio_output_from_realtime: bool | None = None,
        duration_ms: int | None = None,
        silence_ms: int | None = None,
        size_bytes: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        format: str | None = None,
        device: str | None = None,
        status: str | None = None,
        mode: str | None = None,
        state: str | None = None,
        task_id: str | None = None,
        result_state: str | None = None,
        route_family: str | None = None,
        subsystem: str | None = None,
        error_code: str | None = None,
        correlation_id: str | None = None,
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
        resolved_listen_window_id = listen_window_id
        if resolved_listen_window_id is None and turn is not None:
            resolved_listen_window_id = self._metadata_listen_window_id(turn.metadata)
        playback_event = event_type in {
            VoiceEventType.PLAYBACK_STARTED,
            VoiceEventType.PLAYBACK_COMPLETED,
            VoiceEventType.PLAYBACK_STOPPED,
        }
        vad_event = event_type in {
            VoiceEventType.VAD_READINESS_CHANGED,
            VoiceEventType.VAD_DETECTION_STARTED,
            VoiceEventType.VAD_DETECTION_STOPPED,
            VoiceEventType.SPEECH_ACTIVITY_STARTED,
            VoiceEventType.SPEECH_ACTIVITY_STOPPED,
            VoiceEventType.SILENCE_TIMEOUT,
            VoiceEventType.VAD_ERROR,
        }
        realtime_event = str(event_type.value).startswith("voice.realtime")
        event = publish_voice_event(
            self.events,
            event_type,
            message=message,
            correlation_id=correlation_id or self.active_wake_supervised_loop_id,
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
            capture_request_id=capture_request_id,
            capture_id=capture_id,
            interruption_id=interruption_id,
            wake_event_id=wake_event_id,
            wake_session_id=wake_session_id,
            wake_ghost_request_id=wake_ghost_request_id,
            vad_session_id=vad_session_id,
            activity_event_id=activity_event_id,
            spoken_confirmation_intent_id=spoken_confirmation_intent_id,
            spoken_confirmation_request_id=spoken_confirmation_request_id,
            spoken_confirmation_result_id=spoken_confirmation_result_id,
            pending_confirmation_id=pending_confirmation_id,
            listen_window_id=resolved_listen_window_id,
            realtime_session_id=realtime_session_id,
            realtime_turn_id=realtime_turn_id,
            realtime_event_id=realtime_event_id,
            wake_phrase=wake_phrase,
            intent=intent,
            muted_scope=muted_scope,
            action_id=action_id,
            required_strength=required_strength,
            provided_strength=provided_strength,
            binding_valid=binding_valid,
            invalid_reason=invalid_reason,
            consumed=consumed,
            action_executed=action_executed,
            provider_kind=provider_kind,
            backend=backend,
            core_task_cancelled=core_task_cancelled,
            core_result_mutated=core_result_mutated,
            spoken_output_suppressed=spoken_output_suppressed,
            confidence=confidence,
            accepted=accepted,
            rejected_reason=rejected_reason,
            cooldown_active=cooldown_active,
            false_positive_candidate=false_positive_candidate,
            openai_used=openai_used,
            cloud_used=cloud_used,
            raw_audio_present=raw_audio_present,
            is_partial=is_partial,
            is_final=is_final,
            direct_tools_allowed=direct_tools_allowed,
            core_bridge_required=core_bridge_required,
            speech_to_speech_enabled=speech_to_speech_enabled,
            audio_output_from_realtime=audio_output_from_realtime,
            duration_ms=duration_ms,
            silence_ms=silence_ms,
            size_bytes=size_bytes,
            model=model,
            voice=voice,
            format=format,
            device=device,
            status=status,
            task_id=task_id,
            result_state=result_state,
            route_family=route_family,
            subsystem=subsystem,
            source=resolved_source,
            error_code=error_code,
            privacy={
                "no_raw_audio": True,
                "no_raw_audio_output": True,
                "no_microphone_capture": True,
                "no_realtime": not realtime_event,
                "realtime_transcription_bridge_only": self.config.realtime.mode
                == "transcription_bridge",
                "realtime_speech_core_bridge": self.config.realtime.mode
                == "speech_to_speech_core_bridge",
                "no_audio_playback": not playback_event,
                "always_listening": False,
                "no_wake_word": True,
                "no_cloud_wake_audio": True,
                "openai_wake_detection": False,
                "cloud_wake_detection": False,
                "no_vad": not vad_event,
                "semantic_completion_claimed": False,
                "command_intent_claimed": False,
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
        return str(
            getattr(self.provider, "stt_model", self.config.openai.stt_model)
            or self.config.openai.stt_model
        ).strip()

    def _tts_model_name(self) -> str:
        return str(
            getattr(self.provider, "tts_model", self.config.openai.tts_model)
            or self.config.openai.tts_model
        ).strip()

    def _tts_voice_name(self) -> str:
        return str(
            getattr(self.provider, "tts_voice", self.config.openai.tts_voice)
            or self.config.openai.tts_voice
        ).strip()

    def _tts_format_name(self) -> str:
        return (
            str(
                getattr(self.provider, "tts_format", self.config.openai.tts_format)
                or self.config.openai.tts_format
            )
            .strip()
            .lower()
        )

    def _tts_live_format_name(self) -> str:
        return (
            str(
                getattr(
                    self.provider,
                    "tts_live_format",
                    self.config.openai.tts_live_format,
                )
                or self.config.openai.tts_live_format
                or self.config.openai.tts_format
            )
            .strip()
            .lower()
            or "pcm"
        )

    def _tts_artifact_format_name(self) -> str:
        return (
            str(
                getattr(
                    self.provider,
                    "tts_artifact_format",
                    self.config.openai.tts_artifact_format,
                )
                or self.config.openai.tts_artifact_format
                or self.config.openai.tts_format
            )
            .strip()
            .lower()
            or "mp3"
        )

    def _manual_turn_status_snapshot(self) -> dict[str, Any]:
        result = self.last_manual_turn_result
        turn = result.turn if result is not None else None
        core_result = result.core_result if result is not None else None
        spoken_response: SpokenResponseResult | None = (
            result.spoken_response if result is not None else None
        )
        return {
            "enabled": self.config.manual_input_enabled,
            "path": "manual_transcript_only",
            "last_turn_id": turn.turn_id if turn is not None else None,
            "last_transcript_preview": self._preview_text(turn.transcript)
            if turn is not None
            else None,
            "last_core_result_state": core_result.result_state
            if core_result is not None
            else None,
            "last_route_family": core_result.route_family
            if core_result is not None
            else None,
            "last_subsystem": core_result.subsystem
            if core_result is not None
            else None,
            "last_trust_posture": core_result.trust_posture
            if core_result is not None
            else None,
            "last_verification_posture": core_result.verification_posture
            if core_result is not None
            else None,
            "last_spoken_response_candidate": spoken_response.to_dict()
            if spoken_response is not None
            else None,
            "last_error": dict(self.last_error),
            "mock_dev_override_active": bool(
                turn and turn.metadata.get("manual_dev_override")
            ),
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
            "enabled": bool(
                self.config.enabled
                and (self.availability.stt_allowed or self.config.debug_mock_provider)
            ),
            "path": "controlled_audio_file_or_blob_only",
            "provider": transcription.provider
            if transcription is not None
            else provider_name,
            "model": transcription.model
            if transcription is not None
            else self._stt_model_name(),
            "last_turn_id": turn.turn_id if turn is not None else None,
            "last_transcription_id": transcription.transcription_id
            if transcription is not None
            else None,
            "last_transcription_state": transcription.status
            if transcription is not None
            else None,
            "last_transcript_preview": self._preview_text(transcription.transcript)
            if transcription is not None
            else None,
            "last_audio_input_metadata": self.last_audio_input_metadata,
            "last_provider_latency_ms": transcription.provider_latency_ms
            if transcription is not None
            else None,
            "last_transcription_error": {
                "code": transcription.error_code if transcription is not None else None,
                "message": transcription.error_message
                if transcription is not None
                else None,
            },
            "last_audio_validation_error": dict(self.last_audio_validation_error),
            "last_openai_call_attempted": self.last_openai_call_attempted,
            "last_openai_call_blocked_reason": self.last_openai_call_blocked_reason,
            "mock_provider_active": bool(getattr(self.provider, "is_mock", False)),
            "no_microphone_capture": True,
            "no_tts": False,
            "no_live_tts": not bool(self.config.openai.stream_tts_outputs),
            "no_realtime": True,
            "no_audio_playback": True,
        }

    def _remember_voice_output_envelope(
        self,
        audio: bytes | bytearray | memoryview | None,
        *,
        audio_format: str,
        source: str,
    ) -> VoiceAudioEnvelope | None:
        if not audio:
            return self.last_voice_output_envelope
        try:
            self.last_voice_output_envelope = compute_voice_audio_envelope(
                audio,
                audio_format=audio_format,
                source=source,
                previous=self.last_voice_output_envelope,
            )
        except Exception:
            return self.last_voice_output_envelope
        return self.last_voice_output_envelope

    def _tts_status_snapshot(self) -> dict[str, Any]:
        request = self.last_speech_request
        synthesis = self.last_synthesis_result
        provider_name = (
            synthesis.provider
            if synthesis is not None
            else getattr(self.provider, "name", self.availability.provider_name)
        )
        audio_output = synthesis.audio_output if synthesis is not None else None
        streaming = self.last_streaming_tts_result
        first_audio = self.last_first_audio_latency
        provider_prewarm = self.last_provider_prewarm_result
        envelope = self.last_voice_output_envelope
        streaming_transport_kind = (
            streaming.streaming_transport_kind
            if streaming is not None
            else first_audio.streaming_transport_kind
            if first_audio is not None
            else ""
        )
        return {
            "enabled": bool(
                self.config.enabled
                and self.config.spoken_responses_enabled
                and (self.availability.tts_allowed or self.config.debug_mock_provider)
            ),
            "path": "controlled_tts_audio_output_only",
            "spoken_responses_enabled": self.config.spoken_responses_enabled,
            "provider": provider_name,
            "model": synthesis.model
            if synthesis is not None
            else self._tts_model_name(),
            "voice": synthesis.voice
            if synthesis is not None
            else self._tts_voice_name(),
            "format": synthesis.format
            if synthesis is not None
            else self._tts_format_name(),
            "streaming_tts_enabled": bool(self.config.openai.stream_tts_outputs),
            "streaming_enabled": bool(self.config.openai.stream_tts_outputs),
            "streaming_transport_kind": streaming_transport_kind or None,
            "streaming_tts_status": streaming.status if streaming is not None else None,
            "tts_streaming_active": bool(
                streaming is not None
                and streaming.streaming_started
                and not streaming.streaming_completed
                and not streaming.streaming_cancelled
            ),
            "live_format": self._tts_live_format_name(),
            "artifact_format": self._tts_artifact_format_name(),
            "last_tts_stream_id": streaming.tts_stream_id if streaming is not None else None,
            "last_stream_status": streaming.status if streaming is not None else None,
            "first_chunk_before_complete": bool(
                streaming and streaming.first_chunk_before_complete
            ),
            "bytes_total_summary_only": int(
                streaming.bytes_total_summary_only
                if streaming is not None
                else 0
            ),
            "provider_prewarmed": bool(provider_prewarm and provider_prewarm.ok),
            "prewarm_used": bool(self.last_voice_output_prewarm_result is not None),
            "fallback_used": bool(first_audio and first_audio.fallback_used),
            "first_audio_pending": bool(
                streaming is not None and streaming.first_chunk_at is None
            ),
            "first_audio_started": bool(
                first_audio is not None and first_audio.first_audio_available
            ),
            "first_audio_available": bool(
                first_audio is not None and first_audio.first_audio_available
            ),
            "first_audio_ms": (
                first_audio.request_to_first_audio_ms
                if first_audio is not None
                else None
            ),
            "first_audio_latency": first_audio.to_dict()
            if first_audio is not None
            else None,
            "voice_output_envelope": envelope.to_dict()
            if envelope is not None
            and envelope.source in {"streaming_chunk_envelope", "precomputed_artifact_envelope"}
            else None,
            "voice_stream_used_by_normal_path": bool(
                first_audio and first_audio.voice_stream_used_by_normal_path
            ),
            "last_streaming_error": {
                "code": streaming.error_code if streaming is not None else None,
                "message": streaming.error_message if streaming is not None else None,
            },
            "last_speech_request_id": request.speech_request_id
            if request is not None
            else None,
            "last_synthesis_id": synthesis.synthesis_id
            if synthesis is not None
            else None,
            "last_synthesis_state": synthesis.status if synthesis is not None else None,
            "last_spoken_text_preview": self._preview_text(request.text)
            if request is not None
            else None,
            "last_audio_output_metadata": audio_output.to_metadata()
            if audio_output is not None
            else None,
            "last_provider_latency_ms": synthesis.provider_latency_ms
            if synthesis is not None
            else None,
            "last_synthesis_error": {
                "code": synthesis.error_code if synthesis is not None else None,
                "message": synthesis.error_message if synthesis is not None else None,
            },
            "last_openai_tts_call_attempted": self.last_openai_tts_call_attempted,
            "last_openai_tts_call_blocked_reason": self.last_openai_tts_call_blocked_reason,
            "mock_provider_active": bool(getattr(self.provider, "is_mock", False)),
            "audio_generated": bool(
                synthesis is not None
                and synthesis.ok
                and synthesis.audio_output is not None
            ),
            "playback_available": bool(
                self.config.playback.enabled
                and self._playback_provider_availability().get("available")
            ),
            "no_microphone_capture": True,
            "no_wake_word": True,
            "no_realtime": True,
            "no_live_conversation_loop": True,
            "no_audio_playback": not bool(
                self.last_playback_result and self.last_playback_result.played_locally
            ),
            "spoken_output_muted": self.spoken_output_muted,
            "muted_scope": self.muted_scope,
            "muted_reason": self.muted_reason,
            "current_response_suppressed": self.current_response_suppressed,
            "active_tts_suppressible": bool(request is not None and synthesis is None),
        }

    def _playback_status_snapshot(self) -> dict[str, Any]:
        request = self.last_playback_request
        result = self.last_playback_result
        active = self._active_playback()
        active_stream = self._active_playback_stream()
        live_result = self.last_live_playback_result
        playback_prewarm = self.last_playback_prewarm_result
        first_audio = self.last_first_audio_latency
        envelope = self.last_voice_output_envelope
        availability = self._playback_provider_availability()
        live_playback_supported = bool(
            self.config.playback.enabled
            and self.config.playback.streaming_enabled
            and availability.get("available")
            and callable(getattr(self.playback_provider, "start_stream", None))
            and callable(getattr(self.playback_provider, "feed_stream_chunk", None))
        )
        if live_result is not None and live_result.status == "unsupported":
            live_playback_supported = False
        return {
            "enabled": self.config.playback.enabled,
            "provider": result.provider
            if result is not None
            else self._playback_provider_name(),
            "available": bool(
                self.config.playback.enabled and availability.get("available")
            ),
            "unavailable_reason": availability.get("unavailable_reason"),
            "device": result.device
            if result is not None
            else self.config.playback.device,
            "volume": self.config.playback.volume,
            "last_playback_request_id": request.playback_request_id
            if request is not None
            else None,
            "last_playback_id": result.playback_id if result is not None else None,
            "last_playback_status": result.status if result is not None else None,
            "last_audio_output_id": result.audio_output_id
            if result is not None
            else None,
            "last_synthesis_id": result.synthesis_id if result is not None else None,
            "last_playback_error": {
                "code": result.error_code if result is not None else None,
                "message": result.error_message if result is not None else None,
            },
            "last_output_metadata": dict(result.output_metadata)
            if result is not None
            else None,
            "active_playback_id": active.playback_id if active is not None else None,
            "active_playback_status": active.status if active is not None else None,
            "active_playback_interruptible": bool(
                active is not None and active.status in {"started", "playing"}
            ),
            "playback_started_at": result.started_at if result is not None else None,
            "playback_completed_at": result.completed_at
            if result is not None
            else None,
            "playback_stopped_at": result.stopped_at if result is not None else None,
            "played_locally": bool(result and result.played_locally),
            "live_playback_enabled": bool(self.config.playback.streaming_enabled),
            "live_playback_supported": live_playback_supported,
            "live_playback_status": (
                live_result.status if live_result is not None else None
            ),
            "unsupported_reason": (
                live_result.error_code
                if live_result is not None and live_result.status == "unsupported"
                else None
            ),
            "streaming_enabled": bool(self.config.playback.streaming_enabled),
            "playback_streaming_active": bool(
                active_stream is not None
                and active_stream.status in {"started", "playing"}
            ),
            "playback_prewarmed": bool(playback_prewarm and playback_prewarm.ok),
            "provider_prewarmed": bool(
                self.last_provider_prewarm_result
                and self.last_provider_prewarm_result.ok
            ),
            "live_format": self._tts_live_format_name(),
            "stream_status": (
                active_stream.status
                if active_stream is not None
                else live_result.status
                if live_result is not None
                else None
            ),
            "last_playback_stream_id": (
                active_stream.playback_stream_id
                if active_stream is not None
                else live_result.playback_stream_id
                if live_result is not None
                else None
            ),
            "first_audio_pending": bool(
                self.last_streaming_tts_result is not None
                and self.last_streaming_tts_result.first_chunk_at is None
            ),
            "first_audio_started": bool(
                first_audio is not None and first_audio.first_audio_available
            ),
            "first_audio_ms": (
                first_audio.request_to_first_audio_ms
                if first_audio is not None
                else None
            ),
            "voice_output_envelope": envelope.to_dict()
            if envelope is not None
            and envelope.source in {"playback_output_envelope", "streaming_chunk_envelope"}
            else None,
            "partial_playback": bool(
                (result is not None and result.partial_playback)
                or (live_result is not None and live_result.partial_playback)
            ),
            "fallback_used": bool(first_audio and first_audio.fallback_used),
            "interruption_available": bool(
                active is not None
                or active_stream is not None
                or self.last_streaming_tts_result is not None
            ),
            "stop_speaking_available": bool(active is not None or active_stream is not None),
            "user_heard_claimed": False,
            "mock_provider_active": bool(
                getattr(self.playback_provider, "is_mock", False)
            ),
            "no_microphone_capture": True,
            "no_wake_word": True,
            "no_vad": True,
            "no_realtime": True,
            "no_continuous_loop": True,
            "raw_audio_included": False,
        }

    def _interruption_status_snapshot(self) -> dict[str, Any]:
        request = self.last_interruption_request
        result = self.last_interruption_result
        classification = self.last_interruption_classification
        playback_result = result.playback_result if result is not None else None
        core_cancellation_requested = bool(
            result is not None
            and (
                result.intent == VoiceInterruptionIntent.CORE_ROUTED_CANCEL_REQUEST
                or result.metadata.get("core_cancellation_requested") is True
            )
        )
        return {
            "active_interruption": False,
            "spoken_output_muted": self.spoken_output_muted,
            "muted_scope": self.muted_scope,
            "muted_since": self.muted_since,
            "muted_reason": self.muted_reason,
            "current_response_suppressed": self.current_response_suppressed,
            "suppressed_turn_id": self.suppressed_turn_id,
            "suppressed_reason": self.suppressed_reason,
            "active_playback_interruptible": bool(
                self._active_playback() is not None
                and self._active_playback().status in {"started", "playing"}
            ),
            "active_tts_suppressible": bool(
                self.last_speech_request is not None
                and self.last_synthesis_result is None
            ),
            "last_interruption_id": result.interruption_id
            if result is not None
            else None,
            "last_interruption_intent": result.intent.value
            if result is not None
            else None,
            "last_interruption_status": result.status if result is not None else None,
            "last_interruption": result.to_dict() if result is not None else None,
            "last_interruption_result": result.to_dict()
            if result is not None
            else None,
            "last_interruption_request": request.to_dict()
            if request is not None
            else None,
            "last_interruption_classification": classification.to_dict()
            if classification is not None
            else None,
            "last_playback_stop_result": playback_result.to_dict()
            if playback_result is not None
            else None,
            "output_interrupted": bool(result.output_stopped)
            if result is not None
            else False,
            "capture_interrupted": bool(result.capture_cancelled)
            if result is not None
            else False,
            "listen_window_interrupted": bool(result.listen_window_cancelled)
            if result is not None
            else False,
            "confirmation_interrupted": bool(result.confirmation_rejected)
            if result is not None
            else False,
            "core_cancellation_requested": core_cancellation_requested,
            "correction_routed": bool(result.routed_as_correction)
            if result is not None
            else False,
            "routed_as_new_request": bool(result.routed_as_new_request)
            if result is not None
            else False,
            "ambiguity_reason": classification.ambiguity_reason
            if classification is not None
            else None,
            "core_task_cancelled_by_voice": False,
            "core_result_mutated_by_voice": False,
            "user_heard_claimed": False,
            "no_wake_word": True,
            "no_vad": True,
            "no_realtime": True,
            "no_continuous_loop": True,
            "raw_audio_included": False,
        }

    def _spoken_confirmation_status_snapshot(self) -> dict[str, Any]:
        intent = self.last_spoken_confirmation_intent
        request = self.last_spoken_confirmation_request
        binding = self.last_spoken_confirmation_binding
        result = self.last_spoken_confirmation_result
        pending_count = 0
        if self.trust_service is not None:
            repository = getattr(self.trust_service, "repository", None)
            if repository is not None:
                try:
                    pending_count = len(
                        repository.list_pending_requests(session_id="default")
                    )
                except Exception:
                    pending_count = 0
        return {
            "enabled": bool(self.config.confirmation.enabled),
            "trust_service_attached": self.trust_service is not None,
            "max_confirmation_age_ms": self.config.confirmation.max_confirmation_age_ms,
            "allow_soft_yes_for_low_risk": self.config.confirmation.allow_soft_yes_for_low_risk,
            "require_strong_phrase_for_destructive": self.config.confirmation.require_strong_phrase_for_destructive,
            "consume_once": self.config.confirmation.consume_once,
            "reject_on_task_switch": self.config.confirmation.reject_on_task_switch,
            "reject_on_payload_change": self.config.confirmation.reject_on_payload_change,
            "reject_on_session_restart": self.config.confirmation.reject_on_session_restart,
            "pending_confirmation_count": pending_count,
            "last_intent": intent.to_dict() if intent is not None else None,
            "last_request": request.to_dict() if request is not None else None,
            "last_binding": binding.to_dict() if binding is not None else None,
            "last_result": result.to_dict() if result is not None else None,
            "last_status": result.status if result is not None else None,
            "last_pending_confirmation_id": result.pending_confirmation_id
            if result is not None
            else None,
            "confirmation_is_command_authority": False,
            "confirmation_requires_pending_binding": True,
            "confirmation_accepted_does_not_execute_action": True,
            "core_task_cancelled_by_voice": False,
            "core_result_mutated_by_voice": False,
            "action_executed_by_voice_confirmation": False,
            "raw_audio_included": False,
            "secrets_included": False,
        }

    def _capture_status_snapshot(self) -> dict[str, Any]:
        request = self.last_capture_request
        session = self.last_capture_session
        result = self.last_capture_result
        active = self._active_capture()
        availability = self._capture_provider_availability()
        audio_input = result.audio_input if result is not None else None
        audio_metadata = audio_input.to_metadata() if audio_input is not None else None
        if audio_metadata is not None:
            audio_metadata["file_path"] = None
        file_metadata = (
            dict(result.metadata.get("file") or {}) if result is not None else {}
        )
        active_metadata = dict(active.metadata) if active is not None else {}
        return {
            "enabled": self.config.capture.enabled,
            "provider": result.provider
            if result is not None
            else self._capture_provider_name(),
            "available": bool(
                self.config.capture.enabled and availability.get("available")
            ),
            "unavailable_reason": availability.get("unavailable_reason"),
            "local_capture_enabled": bool(
                self.config.capture.enabled and self.config.capture.provider == "local"
            ),
            "allow_dev_capture": self.config.capture.allow_dev_capture,
            "dependency": active_metadata.get(
                "dependency", availability.get("dependency")
            ),
            "dependency_available": availability.get("dependency_available"),
            "platform": active_metadata.get("platform", availability.get("platform")),
            "platform_supported": availability.get("platform_supported"),
            "device_available": active_metadata.get(
                "device_available", availability.get("device_available")
            ),
            "permission_state": active_metadata.get(
                "permission_state", availability.get("permission_state")
            ),
            "permission_error": availability.get("permission_error"),
            "device": result.device
            if result is not None
            else self.config.capture.device,
            "mode": self.config.capture.mode,
            "sample_rate": self.config.capture.sample_rate,
            "channels": self.config.capture.channels,
            "format": self.config.capture.format,
            "max_duration_ms": self.config.capture.max_duration_ms,
            "max_audio_bytes": self.config.capture.max_audio_bytes,
            "active_capture_id": active.capture_id if active is not None else None,
            "active_capture_status": active.status if active is not None else None,
            "active_capture_started_at": active.started_at
            if active is not None
            else None,
            "last_capture_request_id": result.capture_request_id
            if result is not None
            else (request.capture_request_id if request is not None else None),
            "last_capture_id": result.capture_id
            if result is not None
            else (session.capture_id if session is not None else None),
            "last_capture_status": result.status if result is not None else None,
            "last_capture_duration_ms": result.duration_ms
            if result is not None
            else None,
            "last_capture_size_bytes": result.size_bytes
            if result is not None
            else None,
            "last_capture_error": {
                "code": result.error_code
                if result is not None
                else self.last_capture_error.get("code"),
                "message": result.error_message
                if result is not None
                else self.last_capture_error.get("message"),
            },
            "last_capture_audio_input_metadata": audio_metadata,
            "last_capture_file_metadata": file_metadata or None,
            "last_capture_cleanup_warning": result.metadata.get("cleanup_warning")
            if result is not None
            else availability.get("cleanup_warning"),
            "mock_provider_active": bool(
                getattr(self.capture_provider, "is_mock", False)
            ),
            "raw_audio_persisted": bool(result and result.raw_audio_persisted),
            "microphone_was_active": bool(result and result.microphone_was_active),
            "always_listening": False,
            "no_wake_word": True,
            "no_vad": True,
            "no_realtime": True,
            "no_continuous_loop": True,
            "raw_audio_included": False,
        }

    def _vad_status_snapshot(self) -> dict[str, Any]:
        availability = self._vad_provider_availability()
        active = self.get_active_vad_session()
        last_event = self.last_activity_event
        last_event_payload = last_event.to_dict() if last_event is not None else None
        if last_event_payload is not None:
            last_event_payload.pop("raw_audio_present", None)
        readiness = self.vad_readiness_report().to_dict()
        return {
            "enabled": self.config.vad.enabled,
            "provider": self._vad_provider_name(),
            "provider_kind": str(
                availability.get("provider_kind") or self._vad_provider_name()
            ),
            "available": bool(
                self.config.vad.enabled and availability.get("available")
            ),
            "unavailable_reason": availability.get("unavailable_reason"),
            "active": active is not None,
            "active_vad_session": active.to_dict() if active is not None else None,
            "active_vad_session_id": active.vad_session_id
            if active is not None
            else None,
            "active_capture_id": active.capture_id if active is not None else None,
            "active_listen_window_id": active.listen_window_id
            if active is not None
            else None,
            "silence_ms": self.config.vad.silence_ms,
            "speech_start_threshold": self.config.vad.speech_start_threshold,
            "speech_stop_threshold": self.config.vad.speech_stop_threshold,
            "min_speech_ms": self.config.vad.min_speech_ms,
            "max_utterance_ms": self.config.vad.max_utterance_ms,
            "pre_roll_ms": self.config.vad.pre_roll_ms,
            "post_roll_ms": self.config.vad.post_roll_ms,
            "auto_finalize_capture": self.config.vad.auto_finalize_capture,
            "mock_provider_active": bool(getattr(self.vad_provider, "is_mock", False)),
            "last_activity_event": last_event_payload,
            "last_speech_activity_status": last_event.status
            if last_event is not None
            else None,
            "last_speech_started_at": self.last_vad_session.speech_started_at
            if self.last_vad_session is not None
            else None,
            "last_speech_stopped_at": self.last_vad_session.speech_stopped_at
            if self.last_vad_session is not None
            else None,
            "last_silence_timeout": bool(
                last_event is not None and last_event.status == "speech_stopped"
            ),
            "semantic_completion_claimed": False,
            "command_authority": False,
            "realtime_vad": False,
            "no_realtime": True,
            "readiness": readiness,
            "audio_bytes_included": False,
            "secrets_included": False,
        }

    def _wake_status_snapshot(self) -> dict[str, Any]:
        readiness = self.wake_readiness_report().to_dict()
        availability = self._wake_provider_availability()
        active = self.get_active_wake_session()
        wake_ghost = self._wake_ghost_status_snapshot()
        return {
            "enabled": self.config.wake.enabled,
            "provider": self._wake_provider_name(),
            "provider_kind": str(
                availability.get("provider_kind") or readiness["wake_provider_kind"]
            ),
            "wake_backend": availability.get("backend"),
            "dependency": availability.get("dependency"),
            "dependency_available": availability.get("dependency_available"),
            "platform": availability.get("platform"),
            "platform_supported": availability.get("platform_supported"),
            "device": availability.get("device"),
            "device_available": availability.get("device_available"),
            "permission_state": availability.get("permission_state"),
            "permission_error": availability.get("permission_error"),
            "available": readiness["wake_available"],
            "unavailable_reason": availability.get("unavailable_reason"),
            "monitoring_active": bool(self.wake_monitoring_active),
            "active_monitoring_started_at": availability.get(
                "active_monitoring_started_at"
            ),
            "wake_phrase_configured": readiness["wake_phrase_configured"],
            "wake_phrase": self.config.wake.wake_phrase,
            "sample_rate": self.config.wake.sample_rate,
            "sensitivity": self.config.wake.sensitivity,
            "confidence_threshold": self.config.wake.confidence_threshold,
            "cooldown_ms": self.config.wake.cooldown_ms,
            "max_wake_session_ms": self.config.wake.max_wake_session_ms,
            "false_positive_window_ms": self.config.wake.false_positive_window_ms,
            "allow_dev_wake": self.config.wake.allow_dev_wake,
            "readiness": readiness,
            "active_wake_session": self._wake_session_status(active),
            "last_wake_event": self._wake_event_status(self.last_wake_event),
            "last_wake_session": self._wake_session_status(self.last_wake_session),
            "ghost": wake_ghost,
            "last_wake_rejection_reason": self.last_wake_event.rejected_reason
            if self.last_wake_event is not None
            else None,
            "cooldown_active": self._wake_cooldown_active(),
            "mock_provider_active": bool(getattr(self.wake_provider, "is_mock", False)),
            "real_microphone_monitoring": bool(
                availability.get("real_microphone_monitoring", False)
            ),
            "no_cloud_wake_audio": True,
            "openai_wake_detection": False,
            "cloud_wake_detection": False,
            "realtime_wake_detection": False,
            "always_listening": False,
            "no_vad": True,
            "no_realtime": True,
            "wake_detection_is_command_authority": False,
            "command_routing_from_wake": False,
            "wake_starts_capture": False,
            "wake_routes_core": False,
        }

    def _wake_ghost_status_snapshot(self) -> dict[str, Any]:
        active = self.get_active_wake_ghost_request()
        request = active or self.last_wake_ghost_request
        if request is None:
            return {
                "requested": False,
                "active": False,
                "status": None,
                "wake_ghost_request_id": None,
                "wake_event_id": None,
                "wake_session_id": None,
                "session_id": None,
                "wake_phrase": None,
                "wake_confidence": None,
                "wake_status_label": None,
                "wake_prompt_text": None,
                "expires_at": None,
                "wake_timeout_ms": self.config.wake.max_wake_session_ms,
                "capture_started": False,
                "stt_started": False,
                "core_routed": False,
                "voice_turn_created": False,
                "command_authority_granted": False,
                "no_post_wake_capture": True,
                "no_vad": True,
                "no_realtime": True,
                "no_command_from_wake": True,
                "openai_used": False,
            }
        return {
            "requested": request.status in {"requested", "shown"},
            "active": active is not None and request.status == "shown",
            "status": request.status,
            "wake_ghost_request_id": request.wake_ghost_request_id,
            "wake_event_id": request.wake_event_id,
            "wake_session_id": request.wake_session_id,
            "session_id": request.session_id,
            "wake_phrase": request.wake_phrase,
            "wake_confidence": request.confidence,
            "wake_status_label": request.wake_status_label,
            "wake_prompt_text": request.wake_prompt_text,
            "expires_at": request.expires_at,
            "wake_timeout_ms": self.config.wake.max_wake_session_ms,
            "reason": request.reason,
            "capture_started": False,
            "stt_started": False,
            "core_routed": False,
            "voice_turn_created": False,
            "command_authority_granted": False,
            "no_post_wake_capture": True,
            "no_vad": True,
            "no_realtime": True,
            "no_command_from_wake": True,
            "openai_used": False,
        }

    def _wake_event_status(self, event: VoiceWakeEvent | None) -> dict[str, Any] | None:
        if event is None:
            return None
        return {
            "wake_event_id": event.wake_event_id,
            "provider": event.provider,
            "provider_kind": event.provider_kind,
            "backend": event.backend,
            "device": event.device,
            "wake_phrase": event.wake_phrase,
            "confidence": event.confidence,
            "timestamp": event.timestamp,
            "session_id": event.session_id,
            "accepted": event.accepted,
            "rejected_reason": event.rejected_reason,
            "cooldown_active": event.cooldown_active,
            "false_positive_candidate": event.false_positive_candidate,
            "source": event.source,
            "status": event.status,
            "openai_used": False,
            "cloud_used": False,
            "audio_payload_present": False,
        }

    def _wake_session_status(
        self, session: VoiceWakeSession | None
    ) -> dict[str, Any] | None:
        if session is None:
            return None
        return {
            "wake_session_id": session.wake_session_id,
            "wake_event_id": session.wake_event_id,
            "session_id": session.session_id,
            "started_at": session.started_at,
            "expires_at": session.expires_at,
            "status": session.status,
            "source": session.source,
            "confidence": session.confidence,
            "mode_after_wake": session.mode_after_wake,
            "capture_started": False,
            "core_routed": False,
            "created_ghost_request": False,
            "error_code": session.error_code,
            "error_message": session.error_message,
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
