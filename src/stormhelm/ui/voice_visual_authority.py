from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from stormhelm.core.voice.reactive_real_environment_probe import sanitize_scalar_payload


ACTIVE_PLAYBACK_STATUSES = {
    "active",
    "opened",
    "playback_active",
    "playing",
    "prerolling",
    "stable",
    "started",
    "streaming",
}
TERMINAL_PLAYBACK_STATUSES = {
    "cancelled",
    "completed",
    "failed",
    "idle",
    "stopped",
    "unavailable",
}
REQUESTED_PLAYBACK_STATUSES = {"requested"}


@dataclass
class _VoiceVisualState:
    active_playback_id: str | None = None
    authoritative_playback_id: str | None = None
    playback_request_id: str | None = None
    speech_request_id: str | None = None
    session_id: str | None = None
    playback_status: str = "idle"
    voice_visual_active: bool = False
    voice_visual_energy: float = 0.0
    voice_visual_source: str = "unavailable"
    first_active_time_ms: float | None = None
    playback_start_time_ms: float | None = None
    playback_complete_time_ms: float | None = None
    last_hot_update_time_ms: float | None = None
    last_snapshot_update_time_ms: float | None = None
    release_deadline_ms: float | None = None
    stale_reason: str = ""
    speaking_entered_reason: str = ""
    speaking_exited_reason: str = ""
    last_playback_id: str | None = None
    accepted_playback_id: str | None = None
    ignored_playback_id: str | None = None
    speaking_entered_playback_id: str | None = None
    speaking_exited_playback_id: str | None = None
    last_accepted_update_source: str = "initial"
    last_ignored_update_source: str = ""
    last_external_sequence: int | None = None


class VoiceVisualPlaybackAuthority:
    """Authoritative scalar voice visual state keyed by the current playback id."""

    version = "AR6"

    def __init__(self, *, release_tail_ms: int = 700) -> None:
        self.release_tail_ms = int(max(0, min(1000, release_tail_ms)))
        self._state = _VoiceVisualState()
        self._sequence = 0
        self._stale_broad_snapshot_ignored_count = 0
        self._hot_path_accepted_count = 0
        self._terminal_event_accepted_count = 0
        self._playback_id_switch_count = 0
        self._playback_id_mismatch_ignored_count = 0
        self._voice_visual_active_flap_count = 0
        self._last_output_active = False
        self._false_speaking_without_audio_detected = False
        self._stuck_speaking_after_audio_detected = False

    def apply_hot_path_update(
        self,
        payload: Mapping[str, Any] | None,
        *,
        now_ms: float | int | None = None,
    ) -> dict[str, Any]:
        now = _time_ms(now_ms)
        clean = sanitize_scalar_payload(payload)
        playback_id = (
            _playback_id(clean)
            or self._state.active_playback_id
            or self._state.authoritative_playback_id
        )
        external_sequence = _sequence(clean)
        if self._is_old_sequence(external_sequence, playback_id):
            self._ignore("hot_path", "old_sequence")
            return self.snapshot(now_ms=now)

        status = _playback_status(clean) or self._state.playback_status
        active_flag = _bool(clean.get("voice_visual_active"), False)
        if not status or status == "idle":
            status = "playing" if active_flag else self._state.playback_status
        if _terminal_status(status):
            terminal_id = playback_id or self._state.active_playback_id or self._state.authoritative_playback_id
            if (
                self._state.active_playback_id
                and terminal_id
                and terminal_id != self._state.active_playback_id
            ):
                self._ignore("hot_path", "terminal_playback_id_mismatch", terminal_id)
                self._playback_id_mismatch_ignored_count += 1
                return self.snapshot(now_ms=now)
            if terminal_id:
                self._accept_terminal(terminal_id, status, now, f"hot_path_terminal_{status}")
                self._accept_external_sequence(external_sequence)
                self._advance_sequence()
            return self.snapshot(now_ms=now)
        status_active = _playback_active(status) or _playback_active(
            self._state.playback_status
        )

        if playback_id and self._state.active_playback_id and playback_id != self._state.active_playback_id:
            self._playback_id_switch_count += 1
            self._reset_for_new_playback(playback_id, now)
        elif playback_id and not self._state.active_playback_id:
            self._reset_for_new_playback(playback_id, now)

        if playback_id:
            self._state.active_playback_id = playback_id if status_active or active_flag else self._state.active_playback_id
            self._state.authoritative_playback_id = playback_id

        self._apply_request_ids(clean)
        self._state.playback_status = _normalize_status(status, default="playing")
        self._state.voice_visual_source = _source(clean) or self._state.voice_visual_source or "pcm_stream_meter"
        if self._state.voice_visual_source in {"", "none", "unavailable"}:
            self._state.voice_visual_source = "pcm_stream_meter"
        self._state.voice_visual_energy = _clamp01(clean.get("voice_visual_energy"))
        self._state.last_hot_update_time_ms = now
        self._state.last_accepted_update_source = "hot_path"
        self._state.last_ignored_update_source = ""
        self._state.stale_reason = ""
        self._accept_external_sequence(external_sequence)

        should_be_active = active_flag or status_active
        if should_be_active:
            self._enter_playback(now, "playback_active_hot_path")
        else:
            self._state.voice_visual_active = False

        self._hot_path_accepted_count += 1
        self._advance_sequence()
        return self.snapshot(now_ms=now)

    def apply_snapshot_update(
        self,
        payload: Mapping[str, Any] | None,
        *,
        now_ms: float | int | None = None,
    ) -> dict[str, Any]:
        now = _time_ms(now_ms)
        clean = sanitize_scalar_payload(payload)
        self._state.last_snapshot_update_time_ms = now
        playback_id = _playback_id(clean)
        status = _playback_status(clean)
        external_sequence = _sequence(clean)

        if self._state.active_playback_id:
            if self._is_old_sequence(external_sequence, playback_id):
                self._ignore("broad_snapshot", "old_sequence", playback_id)
                self._stale_broad_snapshot_ignored_count += 1
                return self.snapshot(now_ms=now)
            if playback_id and playback_id != self._state.active_playback_id:
                self._ignore("broad_snapshot", "playback_id_mismatch", playback_id)
                self._playback_id_mismatch_ignored_count += 1
                self._stale_broad_snapshot_ignored_count += 1
                return self.snapshot(now_ms=now)
            if _terminal_status(status) and playback_id == self._state.active_playback_id:
                self._accept_terminal(playback_id, status, now, "snapshot_terminal")
                self._accept_external_sequence(external_sequence)
                self._advance_sequence()
                return self.snapshot(now_ms=now)
            if _playback_active(status) and playback_id == self._state.active_playback_id:
                self._state.playback_status = _normalize_status(status, default=self._state.playback_status)
                self._apply_request_ids(clean)
                carries_visual_clear = (
                    ("voice_visual_active" in clean and not _bool(clean.get("voice_visual_active"), False))
                    or ("voice_visual_energy" in clean and _clamp01(clean.get("voice_visual_energy")) <= 0.0001)
                )
                if carries_visual_clear and self._state.voice_visual_active:
                    self._ignore("broad_snapshot", "active_hot_path_wins", playback_id)
                    self._stale_broad_snapshot_ignored_count += 1
                else:
                    self._state.last_accepted_update_source = "broad_snapshot_metadata"
                self._accept_external_sequence(external_sequence)
                self._advance_sequence()
                return self.snapshot(now_ms=now)

            broad_active = _bool(clean.get("voice_visual_active"), False)
            broad_energy = _clamp01(clean.get("voice_visual_energy"))
            if not broad_active or broad_energy <= 0.0001 or not playback_id:
                self._ignore("broad_snapshot", "active_hot_path_wins", playback_id)
                self._stale_broad_snapshot_ignored_count += 1
                return self.snapshot(now_ms=now)

        if playback_id and (_playback_active(status) or _bool(clean.get("voice_visual_active"), False)):
            self._reset_for_new_playback(playback_id, now)
            self._apply_request_ids(clean)
            self._state.playback_status = _normalize_status(status, default="playing")
            self._state.voice_visual_source = _source(clean) or "pcm_stream_meter"
            self._state.voice_visual_energy = _clamp01(clean.get("voice_visual_energy"))
            self._enter_playback(now, "snapshot_active_playback")
            self._state.last_accepted_update_source = "broad_snapshot"
            self._accept_external_sequence(external_sequence)
            self._advance_sequence()
            return self.snapshot(now_ms=now)

        if _terminal_status(status):
            self._state.playback_status = _normalize_status(status, default="idle")
            self._state.voice_visual_active = False
            self._state.voice_visual_energy = 0.0
            self._state.active_playback_id = None
            self._state.last_accepted_update_source = "broad_snapshot_idle"
            self._accept_external_sequence(external_sequence)
            self._advance_sequence()
            return self.snapshot(now_ms=now)

        self._state.last_accepted_update_source = "broad_snapshot_idle"
        self._advance_sequence()
        return self.snapshot(now_ms=now)

    def apply_playback_event(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None,
        *,
        now_ms: float | int | None = None,
    ) -> dict[str, Any]:
        now = _time_ms(now_ms)
        clean = sanitize_scalar_payload(payload)
        event_key = str(event_type or "").strip().lower()
        playback_id = _playback_id(clean)
        status = _event_status(event_key, clean)
        if not status:
            return self.snapshot(now_ms=now)

        if _terminal_status(status):
            if self._state.active_playback_id and playback_id and playback_id != self._state.active_playback_id:
                self._ignore("terminal_event", "playback_id_mismatch", playback_id)
                self._playback_id_mismatch_ignored_count += 1
                return self.snapshot(now_ms=now)
            terminal_id = playback_id or self._state.active_playback_id or self._state.authoritative_playback_id
            if terminal_id:
                self._accept_terminal(terminal_id, status, now, f"terminal_{status}")
                self._advance_sequence()
            return self.snapshot(now_ms=now)

        if playback_id and self._state.active_playback_id and playback_id != self._state.active_playback_id:
            self._playback_id_switch_count += 1
            self._reset_for_new_playback(playback_id, now)
        elif playback_id and not self._state.active_playback_id:
            self._reset_for_new_playback(playback_id, now)

        self._apply_request_ids(clean)
        self._state.playback_status = _normalize_status(status, default="requested")
        if playback_id:
            self._state.active_playback_id = playback_id
            self._state.authoritative_playback_id = playback_id
        if _playback_active(status):
            reason = "playback_started" if event_key == "voice.playback_started" else f"playback_{status}"
            self._enter_playback(now, reason)
        else:
            self._state.last_accepted_update_source = "playback_event"
        self._advance_sequence()
        return self.snapshot(now_ms=now)

    def snapshot(self, *, now_ms: float | int | None = None) -> dict[str, Any]:
        now = _time_ms(now_ms)
        state = self._state
        playback_active = _playback_active(state.playback_status)
        speaking_active = bool(state.voice_visual_active or playback_active)
        active_playback_id = state.active_playback_id if playback_active or state.voice_visual_active else None
        playback_id = state.authoritative_playback_id or active_playback_id
        latest_age = (
            max(0.0, now - state.last_hot_update_time_ms)
            if state.last_hot_update_time_ms is not None
            else None
        )
        output_active = bool(state.voice_visual_active)
        if output_active != self._last_output_active:
            if self._last_output_active and output_active is False and playback_active:
                self._voice_visual_active_flap_count += 1
            self._last_output_active = output_active

        payload = {
            "authoritativeVoiceStateVersion": self.version,
            "activePlaybackId": active_playback_id,
            "activePlaybackStatus": state.playback_status,
            "authoritativePlaybackId": playback_id,
            "authoritativePlaybackStatus": state.playback_status,
            "authoritativeVoiceVisualActive": output_active,
            "authoritativeVoiceVisualEnergy": round(state.voice_visual_energy, 6),
            "authoritativeStateSequence": int(self._sequence),
            "authoritativeStateSource": state.voice_visual_source,
            "lastAcceptedUpdateSource": state.last_accepted_update_source,
            "lastIgnoredUpdateSource": state.last_ignored_update_source,
            "staleBroadSnapshotIgnored": state.last_ignored_update_source == "broad_snapshot",
            "staleBroadSnapshotIgnoredCount": int(self._stale_broad_snapshot_ignored_count),
            "hotPathAcceptedCount": int(self._hot_path_accepted_count),
            "terminalEventAcceptedCount": int(self._terminal_event_accepted_count),
            "playbackIdSwitchCount": int(self._playback_id_switch_count),
            "playbackIdMismatchIgnoredCount": int(self._playback_id_mismatch_ignored_count),
            "speakingEnteredReason": state.speaking_entered_reason,
            "speakingExitedReason": state.speaking_exited_reason,
            "currentAnchorPlaybackId": playback_id,
            "lastAnchorPlaybackId": state.last_playback_id or playback_id,
            "anchorPlaybackIdSwitchCount": int(self._playback_id_switch_count),
            "anchorAcceptedPlaybackId": state.accepted_playback_id or playback_id,
            "anchorIgnoredPlaybackId": state.ignored_playback_id,
            "anchorSpeakingEntryPlaybackId": state.speaking_entered_playback_id,
            "anchorSpeakingExitPlaybackId": state.speaking_exited_playback_id,
            "anchorSpeakingEntryReason": state.speaking_entered_reason,
            "anchorSpeakingExitReason": state.speaking_exited_reason,
            "finalSpeakingEnergyPlaybackId": playback_id,
            "blobDrivePlaybackId": playback_id,
            "releaseDeadlineMs": _round_optional(state.release_deadline_ms),
            "releaseTailMs": int(self.release_tail_ms),
            "staleReason": state.stale_reason,
            "falseSpeakingWithoutAudioDetected": bool(self._false_speaking_without_audio_detected),
            "stuckSpeakingAfterAudioDetected": bool(self._stuck_speaking_after_audio_detected),
            "voiceVisualActiveFlapCount": int(self._voice_visual_active_flap_count),
            "playback_id": playback_id,
            "voice_visual_playback_id": playback_id,
            "active_playback_id": active_playback_id,
            "active_playback_status": state.playback_status,
            "voice_visual_active": output_active,
            "voice_visual_available": state.voice_visual_source == "pcm_stream_meter",
            "voice_visual_energy": round(state.voice_visual_energy, 6),
            "voice_visual_source": state.voice_visual_source,
            "voice_visual_energy_source": state.voice_visual_source,
            "voice_visual_latest_age_ms": _round_optional(latest_age),
            "voice_visual_sequence": int(self._sequence),
            "speaking_visual_active": speaking_active,
            "voice_visual_started_at_ms": _round_optional(state.first_active_time_ms),
            "playback_start_time_ms": _round_optional(state.playback_start_time_ms),
            "playback_complete_time_ms": _round_optional(state.playback_complete_time_ms),
            "last_hot_update_time_ms": _round_optional(state.last_hot_update_time_ms),
            "last_snapshot_update_time_ms": _round_optional(state.last_snapshot_update_time_ms),
            "playback_request_id": state.playback_request_id,
            "speech_request_id": state.speech_request_id,
            "session_id": state.session_id,
            "raw_audio_present": False,
        }
        return sanitize_scalar_payload(payload)

    def _reset_for_new_playback(self, playback_id: str, now: float) -> None:
        previous_playback_id = self._state.authoritative_playback_id or self._state.active_playback_id
        if previous_playback_id and previous_playback_id != playback_id:
            self._state.last_playback_id = previous_playback_id
        self._state.active_playback_id = playback_id
        self._state.authoritative_playback_id = playback_id
        self._state.accepted_playback_id = playback_id
        self._state.ignored_playback_id = None
        self._state.playback_status = "requested"
        self._state.voice_visual_active = False
        self._state.voice_visual_energy = 0.0
        self._state.voice_visual_source = "pcm_stream_meter"
        self._state.first_active_time_ms = None
        self._state.playback_start_time_ms = None
        self._state.playback_complete_time_ms = None
        self._state.release_deadline_ms = None
        self._state.stale_reason = ""
        self._state.speaking_entered_reason = ""
        self._state.speaking_exited_reason = ""
        self._state.speaking_entered_playback_id = None
        self._state.speaking_exited_playback_id = None
        self._state.last_external_sequence = None
        self._state.last_accepted_update_source = "playback_boundary"
        self._state.last_ignored_update_source = ""
        self._last_output_active = False

    def _enter_playback(self, now: float, reason: str) -> None:
        if self._state.first_active_time_ms is None:
            self._state.first_active_time_ms = now
        if self._state.playback_start_time_ms is None:
            self._state.playback_start_time_ms = now
        if not self._state.voice_visual_active:
            self._state.speaking_entered_reason = reason
            self._state.speaking_entered_playback_id = (
                self._state.authoritative_playback_id or self._state.active_playback_id
            )
        self._state.voice_visual_active = True
        self._state.release_deadline_ms = None
        self._state.speaking_exited_reason = ""
        self._state.speaking_exited_playback_id = None
        self._state.last_accepted_update_source = (
            "hot_path" if "hot_path" in reason else "playback_event"
        )

    def _accept_terminal(
        self,
        playback_id: str,
        status: str,
        now: float,
        reason: str,
    ) -> None:
        self._state.authoritative_playback_id = playback_id
        self._state.accepted_playback_id = playback_id
        self._state.active_playback_id = None
        self._state.playback_status = _normalize_status(status, default="completed")
        self._state.voice_visual_active = False
        self._state.voice_visual_energy = 0.0
        self._state.playback_complete_time_ms = now
        self._state.release_deadline_ms = now + self.release_tail_ms
        self._state.speaking_exited_reason = reason
        self._state.speaking_exited_playback_id = playback_id
        self._state.last_accepted_update_source = "terminal_event"
        self._state.last_ignored_update_source = ""
        self._terminal_event_accepted_count += 1

    def _apply_request_ids(self, payload: Mapping[str, Any]) -> None:
        for key, attr in (
            ("playback_request_id", "playback_request_id"),
            ("speech_request_id", "speech_request_id"),
            ("session_id", "session_id"),
        ):
            value = _text(payload.get(key))
            if value:
                setattr(self._state, attr, value)

    def _ignore(self, source: str, reason: str, playback_id: str | None = None) -> None:
        self._state.last_ignored_update_source = source
        self._state.stale_reason = reason
        if playback_id:
            self._state.ignored_playback_id = playback_id

    def _advance_sequence(self) -> None:
        self._sequence += 1

    def _accept_external_sequence(self, value: int | None) -> None:
        if value is not None:
            self._state.last_external_sequence = value

    def _is_old_sequence(self, value: int | None, playback_id: str | None) -> bool:
        if value is None:
            return False
        if playback_id and self._state.authoritative_playback_id and playback_id != self._state.authoritative_playback_id:
            return False
        prior = self._state.last_external_sequence
        return prior is not None and value <= prior


def _time_ms(value: float | int | None) -> float:
    if value is None:
        import time

        return time.monotonic() * 1000.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return math.isfinite(float(value)) and float(value) != 0.0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return default


def _clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _round_optional(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 3)


def _sequence(payload: Mapping[str, Any]) -> int | None:
    for key in (
        "authoritativeStateSequence",
        "voice_visual_sequence",
        "sequence_number",
        "sequence",
    ):
        try:
            value = int(payload.get(key))
        except (TypeError, ValueError):
            continue
        return value
    return None


def _playback_id(payload: Mapping[str, Any]) -> str | None:
    for key in (
        "authoritativePlaybackId",
        "activePlaybackId",
        "voice_visual_playback_id",
        "playback_id",
        "active_playback_stream_id",
        "active_playback_id",
    ):
        value = _text(payload.get(key))
        if value:
            return value
    return None


def _source(payload: Mapping[str, Any]) -> str:
    return _text(
        payload.get("authoritativeStateSource")
        or payload.get("voice_visual_source")
        or payload.get("voice_visual_energy_source")
    )


def _playback_status(payload: Mapping[str, Any]) -> str:
    return _normalize_status(
        payload.get("authoritativePlaybackStatus")
        or payload.get("activePlaybackStatus")
        or payload.get("active_playback_status")
        or payload.get("playback_status")
        or payload.get("live_playback_status")
    )


def _normalize_status(value: Any, *, default: str = "") -> str:
    text = _text(value).lower().replace("-", "_")
    if text == "started":
        return "playing"
    if text == "playback_active":
        return "playing"
    if text == "streaming":
        return "playing"
    return text or default


def _playback_active(status: str) -> bool:
    return _normalize_status(status) in ACTIVE_PLAYBACK_STATUSES


def _terminal_status(status: str) -> bool:
    return _normalize_status(status) in TERMINAL_PLAYBACK_STATUSES


def _event_status(event_type: str, payload: Mapping[str, Any]) -> str:
    if event_type in {"voice.playback_request_created"}:
        return "requested"
    if event_type in {"voice.playback_stream_started"}:
        return "prerolling"
    if event_type in {"voice.playback_started"}:
        return "playing"
    if event_type in {"voice.playback_completed", "voice.playback_stream_completed"}:
        return "completed"
    if event_type in {"voice.playback_stopped"}:
        return "stopped"
    if event_type in {"voice.playback_failed", "voice.playback_stream_failed"}:
        return "failed"
    return _playback_status(payload)
