from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True, frozen=True)
class SpokenResponseRequest:
    source_result_state: str
    spoken_summary: str
    visual_text: str
    speak_allowed: bool
    spoken_responses_enabled: bool
    speech_length_hint: str = "brief"
    persona_mode: str = "stormhelm"
    max_spoken_chars: int = 220


@dataclass(slots=True, frozen=True)
class SpokenResponseResult:
    speech_length_hint: str
    persona_mode: str
    source_result_state: str
    spoken_text: str
    visual_text: str
    should_speak: bool
    reason_if_not_speaking: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SpokenResponseRenderer:
    def render(self, request: SpokenResponseRequest) -> SpokenResponseResult:
        if not request.spoken_responses_enabled:
            return self._silent(request, "spoken_responses_disabled")
        if not request.speak_allowed:
            return self._silent(request, "core_result_disallows_speech")

        spoken_text = str(request.spoken_summary or "").strip()
        if not spoken_text:
            spoken_text = self._conservative_fallback(request.source_result_state)

        return SpokenResponseResult(
            speech_length_hint=request.speech_length_hint,
            persona_mode=request.persona_mode,
            source_result_state=request.source_result_state,
            spoken_text=self._shorten(spoken_text, request.max_spoken_chars),
            visual_text=request.visual_text,
            should_speak=True,
            reason_if_not_speaking=None,
        )

    def _silent(self, request: SpokenResponseRequest, reason: str) -> SpokenResponseResult:
        return SpokenResponseResult(
            speech_length_hint=request.speech_length_hint,
            persona_mode=request.persona_mode,
            source_result_state=request.source_result_state,
            spoken_text="",
            visual_text=request.visual_text,
            should_speak=False,
            reason_if_not_speaking=reason,
        )

    def _conservative_fallback(self, result_state: str) -> str:
        normalized = str(result_state or "unknown").strip().lower().replace("_", " ") or "unknown"
        if normalized == "completed":
            return "Core reports the request completed. Verification is not claimed here."
        if normalized == "verified":
            return "Core reports the request is verified."
        if normalized == "failed":
            return "The request failed. Details are visible in Stormhelm."
        if normalized in {"pending approval", "requires confirmation", "awaiting confirmation"}:
            return "Confirmation is required before Stormhelm can act."
        if normalized == "clarification required":
            return "I need one more bearing before acting."
        if normalized == "blocked":
            return "The request is blocked. Details are visible in Stormhelm."
        return f"The request is {normalized}. Details are visible in Stormhelm."

    def _shorten(self, text: str, max_chars: int) -> str:
        limit = max(32, int(max_chars or 220))
        compact = " ".join(str(text or "").split()).strip()
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."
