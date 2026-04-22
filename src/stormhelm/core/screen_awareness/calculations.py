from __future__ import annotations

from dataclasses import dataclass
import re

from stormhelm.core.calculations import CalculationCallerContext
from stormhelm.core.calculations import CalculationInputOrigin
from stormhelm.core.calculations import CalculationOutputMode
from stormhelm.core.calculations import CalculationRequest
from stormhelm.core.calculations import CalculationResultVisibility
from stormhelm.core.calculations import CalculationsSubsystem
from stormhelm.core.calculations.normalizer import detect_expression_candidate
from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.screen_awareness.models import ScreenCalculationActivity
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import confidence_level_for_score
from stormhelm.core.screen_awareness.observation import best_visible_text


_EQUATION_PATTERN = re.compile(r"^\s*(?P<expr>.+?)\s*=\s*(?P<claim>.+?)\s*$")


@dataclass(slots=True)
class _ScreenCalculationSource:
    text: str
    input_origin: CalculationInputOrigin
    confidence_score: float
    confidence_note: str


def _preview(text: str, *, limit: int = 120) -> str:
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


def _pick_source(
    *,
    observation,
    preferred_text: str | None,
) -> _ScreenCalculationSource | None:
    if preferred_text and str(preferred_text).strip():
        return _ScreenCalculationSource(
            text=str(preferred_text).strip(),
            input_origin=CalculationInputOrigin.SCREEN_VISIBLE_TEXT,
            confidence_score=0.66,
            confidence_note="Grounded visible text provided the numeric source.",
        )
    if observation.selected_text:
        return _ScreenCalculationSource(
            text=str(observation.selected_text).strip(),
            input_origin=CalculationInputOrigin.SCREEN_SELECTION,
            confidence_score=0.88,
            confidence_note="Selected screen text provided the numeric source.",
        )
    if observation.clipboard_text:
        return _ScreenCalculationSource(
            text=str(observation.clipboard_text).strip(),
            input_origin=CalculationInputOrigin.SCREEN_CLIPBOARD,
            confidence_score=0.72,
            confidence_note="Clipboard text provided the numeric source.",
        )
    visible_text = best_visible_text(observation)
    if visible_text:
        return _ScreenCalculationSource(
            text=str(visible_text).strip(),
            input_origin=CalculationInputOrigin.SCREEN_VISIBLE_TEXT,
            confidence_score=0.58,
            confidence_note="Visible text provided the numeric source, but the screen evidence is weaker than a direct selection.",
        )
    return None


def _extract_expression_and_claim(text: str) -> tuple[str | None, str | None]:
    equation_match = _EQUATION_PATTERN.match(text)
    if equation_match:
        expression = str(equation_match.group("expr") or "").strip()
        claim = str(equation_match.group("claim") or "").strip()
        candidate = detect_expression_candidate(expression, normalize_phrase(expression))
        if candidate.candidate and candidate.extracted_expression:
            return candidate.extracted_expression, claim or None
    candidate = detect_expression_candidate(text, normalize_phrase(text))
    if candidate.candidate and candidate.extracted_expression:
        return candidate.extracted_expression, None
    return None, None


def run_screen_calculation(
    *,
    calculations: CalculationsSubsystem | None,
    session_id: str,
    surface_mode: str,
    active_module: str,
    operator_text: str,
    observation,
    caller_intent: str,
    preferred_text: str | None = None,
    requested_mode: CalculationOutputMode = CalculationOutputMode.ANSWER_ONLY,
    internal_validation: bool = False,
    result_visibility: CalculationResultVisibility = CalculationResultVisibility.USER_FACING,
) -> ScreenCalculationActivity | None:
    if calculations is None:
        return None
    source = _pick_source(observation=observation, preferred_text=preferred_text)
    if source is None:
        return ScreenCalculationActivity(
            status="ambiguous",
            caller_intent=caller_intent,
            input_origin=CalculationInputOrigin.SCREEN_VISIBLE_TEXT.value,
            internal_validation=internal_validation,
            result_visibility=result_visibility.value,
            ambiguous_reason="no_visible_numeric_source",
            summary="I can see this is a numeric request, but I do not have a reliable visible numeric source to evaluate yet.",
            confidence=_confidence(0.0, "No selected, clipboard, or grounded visible text was available for numeric evaluation."),
        )

    expression, claim = _extract_expression_and_claim(source.text)
    if not expression:
        return ScreenCalculationActivity(
            status="ambiguous",
            caller_intent=caller_intent,
            input_origin=source.input_origin.value,
            source_text_preview=_preview(source.text),
            internal_validation=internal_validation,
            result_visibility=result_visibility.value,
            ambiguous_reason="no_supported_visible_expression",
            summary="I can see this is a numeric check request, but I couldn't isolate enough visible numeric input to verify it yet.",
            confidence=_confidence(source.confidence_score * 0.5, source.confidence_note),
        )

    response = calculations.execute(
        session_id=session_id,
        active_module=active_module,
        request=CalculationRequest(
            request_id=f"screen-calc-{caller_intent}",
            source_surface=surface_mode,
            raw_input=operator_text,
            user_visible_text=source.text,
            extracted_expression=expression,
            requested_mode=requested_mode,
            verification_claim=claim,
            caller=CalculationCallerContext(
                subsystem="screen_awareness",
                caller_intent=caller_intent,
                input_origin=source.input_origin,
                visual_extraction_dependency=True,
                internal_validation=internal_validation,
                result_visibility=result_visibility,
                reuse_path=f"screen_awareness.{caller_intent}",
                provenance_stack=[source.input_origin.value, caller_intent],
                evidence_confidence=source.confidence_score,
                evidence_confidence_note=source.confidence_note,
            ),
        ),
    )
    status = "resolved" if response.result is not None else "failed"
    return ScreenCalculationActivity(
        status=status,
        caller_intent=caller_intent,
        input_origin=source.input_origin.value,
        source_text_preview=_preview(source.text),
        extracted_expression=expression,
        claim_text=claim,
        internal_validation=internal_validation,
        result_visibility=result_visibility.value,
        summary=response.assistant_response,
        calculation_trace=response.trace.to_dict(),
        calculation_result=response.result.to_dict() if response.result is not None else None,
        calculation_failure=response.failure.to_dict() if response.failure is not None else None,
        confidence=_confidence(source.confidence_score, source.confidence_note),
    )
