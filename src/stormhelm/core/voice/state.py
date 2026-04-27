from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from stormhelm.config.models import VoiceConfig
from stormhelm.core.voice.availability import VoiceAvailability
from stormhelm.shared.time import utc_now_iso


class VoiceState(str, Enum):
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    DORMANT = "dormant"
    MANUAL_INPUT_RECEIVED = "manual_input_received"
    CAPTURING = "capturing"
    CAPTURE_STOPPED = "capture_stopped"
    CAPTURE_CANCELLED = "capture_cancelled"
    CAPTURE_FAILED = "capture_failed"
    WAKE_DETECTED = "wake_detected"
    CONNECTING = "connecting"
    LISTENING = "listening"
    SPEECH_STARTED = "speech_started"
    SPEECH_STOPPED = "speech_stopped"
    TRANSCRIBING = "transcribing"
    CORE_ROUTING = "core_routing"
    THINKING = "thinking"
    SPEAKING_READY = "speaking_ready"
    SPEAKING = "speaking"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    INTERRUPTED = "interrupted"
    MUTED = "muted"
    ERROR = "error"


class VoiceTransitionError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class VoiceStateSnapshot:
    state: VoiceState
    previous_state: VoiceState | None
    availability: VoiceAvailability
    session_id: str | None
    turn_id: str | None
    last_event_id: str | None
    last_transition_at: str
    error_code: str | None
    error_message: str | None
    source: str
    mode: str
    speaking_allowed: bool
    listening_allowed: bool
    core_bridge_required: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "availability": self.availability.to_dict(),
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "last_event_id": self.last_event_id,
            "last_transition_at": self.last_transition_at,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "source": self.source,
            "mode": self.mode,
            "speaking_allowed": self.speaking_allowed,
            "listening_allowed": self.listening_allowed,
            "core_bridge_required": self.core_bridge_required,
        }


_LEGAL_TRANSITIONS: dict[VoiceState, set[VoiceState]] = {
    VoiceState.DORMANT: {
        VoiceState.MANUAL_INPUT_RECEIVED,
        VoiceState.CAPTURING,
        VoiceState.WAKE_DETECTED,
        VoiceState.CONNECTING,
        VoiceState.LISTENING,
        VoiceState.TRANSCRIBING,
        VoiceState.MUTED,
        VoiceState.ERROR,
    },
    VoiceState.MANUAL_INPUT_RECEIVED: {VoiceState.CORE_ROUTING, VoiceState.ERROR},
    VoiceState.CAPTURING: {
        VoiceState.CAPTURE_STOPPED,
        VoiceState.CAPTURE_CANCELLED,
        VoiceState.CAPTURE_FAILED,
        VoiceState.TRANSCRIBING,
        VoiceState.ERROR,
    },
    VoiceState.CAPTURE_STOPPED: {VoiceState.DORMANT, VoiceState.TRANSCRIBING, VoiceState.ERROR},
    VoiceState.CAPTURE_CANCELLED: {VoiceState.DORMANT, VoiceState.ERROR},
    VoiceState.CAPTURE_FAILED: {VoiceState.DORMANT, VoiceState.ERROR},
    VoiceState.WAKE_DETECTED: {VoiceState.CONNECTING, VoiceState.LISTENING, VoiceState.ERROR},
    VoiceState.CONNECTING: {VoiceState.LISTENING, VoiceState.ERROR},
    VoiceState.LISTENING: {
        VoiceState.SPEECH_STARTED,
        VoiceState.SPEECH_STOPPED,
        VoiceState.TRANSCRIBING,
        VoiceState.INTERRUPTED,
        VoiceState.MUTED,
        VoiceState.DORMANT,
        VoiceState.ERROR,
    },
    VoiceState.SPEECH_STARTED: {VoiceState.SPEECH_STOPPED, VoiceState.TRANSCRIBING, VoiceState.INTERRUPTED, VoiceState.ERROR},
    VoiceState.SPEECH_STOPPED: {VoiceState.TRANSCRIBING, VoiceState.LISTENING, VoiceState.ERROR},
    VoiceState.TRANSCRIBING: {VoiceState.CORE_ROUTING, VoiceState.ERROR},
    VoiceState.CORE_ROUTING: {VoiceState.THINKING, VoiceState.AWAITING_CONFIRMATION, VoiceState.SPEAKING, VoiceState.ERROR},
    VoiceState.THINKING: {
        VoiceState.SPEAKING_READY,
        VoiceState.SPEAKING,
        VoiceState.AWAITING_CONFIRMATION,
        VoiceState.DORMANT,
        VoiceState.ERROR,
    },
    VoiceState.SPEAKING_READY: {VoiceState.DORMANT, VoiceState.LISTENING, VoiceState.AWAITING_CONFIRMATION, VoiceState.ERROR},
    VoiceState.SPEAKING: {VoiceState.DORMANT, VoiceState.LISTENING, VoiceState.INTERRUPTED, VoiceState.ERROR},
    VoiceState.AWAITING_CONFIRMATION: {VoiceState.LISTENING, VoiceState.DORMANT, VoiceState.INTERRUPTED, VoiceState.ERROR},
    VoiceState.INTERRUPTED: {VoiceState.LISTENING, VoiceState.DORMANT, VoiceState.ERROR},
    VoiceState.MUTED: {VoiceState.DORMANT, VoiceState.ERROR},
    VoiceState.ERROR: {VoiceState.DORMANT, VoiceState.UNAVAILABLE, VoiceState.DISABLED},
}


@dataclass(slots=True)
class VoiceStateController:
    config: VoiceConfig
    availability: VoiceAvailability
    session_id: str | None = None
    _snapshot: VoiceStateSnapshot = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._snapshot = self._build_snapshot(
            state=self._initial_state(),
            previous_state=None,
            turn_id=None,
            last_event_id=None,
            error_code=self.availability.unavailable_reason if not self.availability.available and self.config.enabled else None,
            error_message=None,
            source="state_initializer",
        )

    def snapshot(self) -> VoiceStateSnapshot:
        return self._snapshot

    def transition_to(
        self,
        next_state: VoiceState | str,
        *,
        event_id: str | None = None,
        turn_id: str | None = None,
        source: str = "voice_service",
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> VoiceStateSnapshot:
        resolved_next = next_state if isinstance(next_state, VoiceState) else VoiceState(str(next_state))
        current = self._snapshot.state
        allowed = _LEGAL_TRANSITIONS.get(current, set())
        if resolved_next not in allowed:
            message = f"Illegal voice transition: {current.value} -> {resolved_next.value}"
            self._snapshot = self._build_snapshot(
                state=VoiceState.ERROR,
                previous_state=current,
                turn_id=turn_id if turn_id is not None else self._snapshot.turn_id,
                last_event_id=event_id,
                error_code="illegal_transition",
                error_message=message,
                source=source,
            )
            raise VoiceTransitionError(message)

        self._snapshot = self._build_snapshot(
            state=resolved_next,
            previous_state=current,
            turn_id=turn_id if turn_id is not None else self._snapshot.turn_id,
            last_event_id=event_id,
            error_code=error_code,
            error_message=error_message,
            source=source,
        )
        return self._snapshot

    def _initial_state(self) -> VoiceState:
        mode = str(self.config.mode or "").strip().lower()
        if not self.config.enabled or mode == "disabled":
            return VoiceState.DISABLED
        if not self.availability.available:
            return VoiceState.UNAVAILABLE
        return VoiceState.DORMANT

    def _build_snapshot(
        self,
        *,
        state: VoiceState,
        previous_state: VoiceState | None,
        turn_id: str | None,
        last_event_id: str | None,
        error_code: str | None,
        error_message: str | None,
        source: str,
    ) -> VoiceStateSnapshot:
        listening_allowed = (
            self.availability.stt_allowed
            and (bool(self.config.manual_input_enabled) or bool(getattr(self.config, "capture", None) and self.config.capture.enabled))
            and state not in {VoiceState.DISABLED, VoiceState.UNAVAILABLE, VoiceState.MUTED, VoiceState.ERROR}
        )
        speaking_allowed = (
            self.availability.tts_allowed
            and state not in {VoiceState.DISABLED, VoiceState.UNAVAILABLE, VoiceState.MUTED, VoiceState.ERROR}
        )
        return VoiceStateSnapshot(
            state=state,
            previous_state=previous_state,
            availability=self.availability,
            session_id=self.session_id,
            turn_id=turn_id,
            last_event_id=last_event_id,
            last_transition_at=utc_now_iso(),
            error_code=error_code,
            error_message=error_message,
            source=source,
            mode=self.availability.mode,
            speaking_allowed=speaking_allowed,
            listening_allowed=listening_allowed,
            core_bridge_required=True,
        )
