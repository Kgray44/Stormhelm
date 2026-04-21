from __future__ import annotations

import ast
import operator
from typing import Any

from stormhelm.core.screen_awareness.models import GroundingAmbiguityStatus
from stormhelm.core.screen_awareness.models import GroundingCandidateRole
from stormhelm.core.screen_awareness.models import ScreenAnalysisResult
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenLimitationCode
from stormhelm.core.screen_awareness.models import ScreenResponse
from stormhelm.core.screen_awareness.observation import best_visible_text


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _preview(text: str | None, *, limit: int = 120) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _first_sentence(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return "Standing by."
    stop = len(cleaned)
    for marker in (". ", "! ", "? "):
        index = cleaned.find(marker)
        if index != -1:
            stop = min(stop, index + 1)
    return cleaned[:stop].strip() or cleaned


def _safe_math_eval(expression: str) -> float | int | None:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None

    def _evaluate(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return _evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = _evaluate(node.left)
            right = _evaluate(node.right)
            return _BINARY_OPERATORS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            operand = _evaluate(node.operand)
            return _UNARY_OPERATORS[type(node.op)](operand)
        raise ValueError("unsupported expression")

    try:
        value = _evaluate(tree)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None

    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _explain_error(error_text: str) -> str:
    lowered = error_text.lower()
    if "nameerror" in lowered:
        name = ""
        marker = "name '"
        start = error_text.find(marker)
        if start != -1:
            remainder = error_text[start + len(marker) :]
            name = remainder.split("'", 1)[0]
        if name:
            return f"This looks like a Python NameError, which means `{name}` was referenced before Python knew what it referred to."
        return "This looks like a Python NameError, which means something was referenced before it was defined or imported."
    if "traceback" in lowered:
        return "This looks like a Python traceback, which is the runtime showing where execution failed."
    if "warning" in lowered:
        return "This reads like a warning rather than a confirmed failure."
    if "failed" in lowered or "exception" in lowered or "error" in lowered:
        return "This reads like a visible failure message, but I would want the surrounding context before claiming a specific fix."
    return "This looks like notable visible content, but the signal is still partial."


def _describe_grounded_target(analysis: ScreenAnalysisResult) -> str:
    grounding = analysis.grounding_result
    if grounding is None or grounding.winning_target is None:
        return "the current visible target"
    role = grounding.winning_target.role.value
    label = grounding.winning_target.label
    if role == GroundingCandidateRole.UNKNOWN.value:
        return label
    return f"the {role} \"{label}\""


def _grounding_outcome_reason(analysis: ScreenAnalysisResult) -> str:
    grounding = analysis.grounding_result
    if grounding is None:
        return "grounding_not_requested"
    if grounding.ambiguity_status == GroundingAmbiguityStatus.RESOLVED:
        return grounding.explanation.summary
    if grounding.ambiguity_status == GroundingAmbiguityStatus.AMBIGUOUS:
        return grounding.explanation.ambiguity_note or grounding.explanation.summary
    return grounding.clarification_need.reason if grounding.clarification_need is not None else grounding.explanation.summary


def _candidate_telemetry(analysis: ScreenAnalysisResult) -> list[dict[str, Any]]:
    grounding = analysis.grounding_result
    if grounding is None:
        return []
    winning_id = grounding.winning_target.candidate_id if grounding.winning_target is not None else None
    top_score = grounding.ranked_candidates[0].score.final_score if grounding.ranked_candidates else 0.0
    candidates: list[dict[str, Any]] = []
    for candidate in grounding.ranked_candidates[:4]:
        candidates.append(
            {
                "candidate_id": candidate.candidate_id,
                "label": candidate.label,
                "role": candidate.role.value,
                "source_channel": candidate.source_channel.value,
                "source_type": candidate.source_type.value if candidate.source_type is not None else None,
                "score": candidate.score.final_score,
                "score_gap_from_top": max(0.0, top_score - candidate.score.final_score),
                "relative_outcome": "winner" if candidate.candidate_id == winning_id else "alternative",
                "score_components": candidate.score.to_dict(),
                "evidence_summary": [evidence.signal for evidence in candidate.evidence],
                "evidence_channels": list(dict.fromkeys(evidence.channel.value for evidence in candidate.evidence)),
                "evidence_notes": [evidence.note for evidence in candidate.evidence[:4]],
                "truth_states": list(dict.fromkeys(evidence.truth_state.value for evidence in candidate.evidence)),
            }
        )
    return candidates


class ScreenResponseComposer:
    def compose(
        self,
        *,
        intent: ScreenIntentType,
        analysis: ScreenAnalysisResult,
    ) -> ScreenResponse:
        observation = analysis.observation
        interpretation = analysis.interpretation
        current_context = analysis.current_screen_context
        visible_text = best_visible_text(observation) if observation is not None else None
        limitation_codes = {limitation.code for limitation in analysis.limitations}
        grounding = analysis.grounding_result

        if ScreenLimitationCode.OBSERVATION_UNAVAILABLE in limitation_codes:
            text = (
                "I don't have a reliable screen bearing right now. "
                "Observed: there was no focused window, selected text, or grounded workspace surface I could trust. "
                "Inference: I can't safely describe the visible state from this signal."
            )
            return self._response("Screen Bearings", text, analysis)

        if intent == ScreenIntentType.DETECT_VISIBLE_CHANGE:
            text = (
                "Observed: I only have a single current bearing, not a before-and-after comparison. "
                "Inference: I can't tell what changed without a prior screen observation to compare against, and I won't claim a verified change."
            )
            return self._response("Change Bearing", text, analysis)

        if grounding is not None:
            if grounding.ambiguity_status == GroundingAmbiguityStatus.AMBIGUOUS and grounding.clarification_need is not None:
                labels = ", ".join(candidate.label for candidate in grounding.ranked_candidates[:2])
                text = (
                    f"Observed: I found two plausible grounded targets: {labels}. "
                    f"Inference: I can't honestly collapse that ambiguity yet. {grounding.clarification_need.prompt}"
                )
                return self._response("Grounded Bearings", text, analysis)
            if grounding.ambiguity_status == GroundingAmbiguityStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE:
                prompt = grounding.clarification_need.prompt if grounding.clarification_need is not None else "Please give me a stronger visible anchor."
                text = (
                    "Observed: I do not have enough grounded evidence to resolve a single target safely. "
                    f"Inference: {prompt}"
                )
                return self._response("Grounded Bearings", text, analysis)
            if grounding.winning_target is not None:
                grounded_target = _describe_grounded_target(analysis)
                if intent == ScreenIntentType.EXPLAIN_VISIBLE_CONTENT and grounding.winning_target.visible_text:
                    explanation = _explain_error(grounding.winning_target.visible_text)
                    text = (
                        f"Observed: I grounded this request to {grounded_target}. "
                        f"Inference: {explanation}"
                    )
                    return self._response("Grounded Meaning", text, analysis)
                if intent == ScreenIntentType.SOLVE_VISIBLE_PROBLEM and grounding.winning_target.visible_text:
                    solution = _safe_math_eval(grounding.winning_target.visible_text)
                    if solution is not None:
                        text = (
                            f"Observed: I grounded this request to {grounded_target}. "
                            f"Inference: it evaluates to {solution}."
                        )
                        return self._response("Grounded Solution", text, analysis)
                text = (
                    f"Observed: I grounded this request to {grounded_target}. "
                    f"Inference: {grounding.explanation.summary}"
                )
                return self._response("Grounded Bearings", text, analysis)

        if intent == ScreenIntentType.EXPLAIN_VISIBLE_CONTENT and interpretation is not None and interpretation.visible_errors:
            error_text = interpretation.visible_errors[0]
            text = (
                f"Observed: the visible message reads {_preview(error_text)}. "
                f"Inference: {_explain_error(error_text)}"
            )
            if observation is not None and not observation.selected_text:
                text += " The bearing is still partial because I did not have a direct selection from the screen."
            return self._response("Visible Meaning", text, analysis)

        if intent == ScreenIntentType.SOLVE_VISIBLE_PROBLEM and visible_text:
            solution = _safe_math_eval(visible_text)
            if solution is not None:
                text = (
                    f"Observed: the visible expression is {_preview(visible_text)}. "
                    f"Inference: it evaluates to {solution}."
                )
                return self._response("Visible Solution", text, analysis)

        if current_context is not None and interpretation is not None:
            observed = current_context.summary or "The current screen context is partially available."
            inference = interpretation.likely_task or interpretation.visible_purpose or "The visible state is only partially grounded."
            text = f"Observed: {observed} Inference: this most likely reflects {inference}."
            if ScreenLimitationCode.LOW_CONFIDENCE in limitation_codes:
                text += " The bearing is low-confidence because the visible signal is incomplete."
            return self._response("Screen Bearings", text, analysis)

        text = (
            "Observed: I secured only a fragmentary bearing from the current screen state. "
            "Inference: I need stronger visible context to answer cleanly."
        )
        return self._response("Screen Bearings", text, analysis)

    def _response(self, bearing_title: str, text: str, analysis: ScreenAnalysisResult) -> ScreenResponse:
        return ScreenResponse(
            analysis=analysis,
            assistant_response=text,
            response_contract={
                "bearing_title": bearing_title,
                "micro_response": _first_sentence(text),
                "full_response": text,
            },
            telemetry={
                "observation": {
                    "attempted": analysis.observation is not None,
                    "source_types_used": [
                        source.value
                        for source in (analysis.observation.source_types_used if analysis.observation is not None else [])
                    ],
                    "sensitivity": analysis.observation.sensitivity.value if analysis.observation is not None else "unknown",
                },
                "interpretation": {
                    "likely_environment": analysis.interpretation.likely_environment if analysis.interpretation is not None else None,
                    "visible_errors": list(analysis.interpretation.visible_errors if analysis.interpretation is not None else []),
                    "likely_task": analysis.interpretation.likely_task if analysis.interpretation is not None else None,
                },
                "grounding": {
                    "requested": analysis.grounding_result is not None,
                    "outcome": analysis.grounding_result.ambiguity_status.value if analysis.grounding_result is not None else "not_requested",
                    "outcome_reason": _grounding_outcome_reason(analysis),
                    "candidate_count": len(analysis.grounding_result.ranked_candidates) if analysis.grounding_result is not None else 0,
                    "confidence": analysis.grounding_result.confidence.to_dict() if analysis.grounding_result is not None else None,
                    "winning_candidate_id": (
                        analysis.grounding_result.winning_target.candidate_id
                        if analysis.grounding_result is not None and analysis.grounding_result.winning_target is not None
                        else None
                    ),
                    "dominant_channel": (
                        analysis.grounding_result.provenance.dominant_channel.value
                        if analysis.grounding_result is not None and analysis.grounding_result.provenance.dominant_channel is not None
                        else None
                    ),
                    "provenance_channels": (
                        [channel.value for channel in analysis.grounding_result.provenance.channels_used]
                        if analysis.grounding_result is not None
                        else []
                    ),
                    "explanation": (
                        analysis.grounding_result.explanation.summary if analysis.grounding_result is not None else ""
                    ),
                    "planner_result": (
                        analysis.grounding_result.planner_result.to_dict()
                        if analysis.grounding_result is not None and analysis.grounding_result.planner_result is not None
                        else None
                    ),
                    "ranked_candidates": _candidate_telemetry(analysis),
                },
                "limitations": [limitation.to_dict() for limitation in analysis.limitations],
            },
        )
