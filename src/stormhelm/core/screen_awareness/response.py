from __future__ import annotations

from typing import Any

from stormhelm.core.screen_awareness.models import ActionExecutionStatus
from stormhelm.core.screen_awareness.models import GroundingAmbiguityStatus
from stormhelm.core.screen_awareness.models import GroundingCandidateRole
from stormhelm.core.screen_awareness.models import ChangeClassification
from stormhelm.core.screen_awareness.models import CompletionStatus
from stormhelm.core.screen_awareness.models import NavigationStepStatus
from stormhelm.core.screen_awareness.models import ScreenAnalysisResult
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenLimitationCode
from stormhelm.core.screen_awareness.models import ScreenResponse
from stormhelm.core.screen_awareness.observation import best_visible_text

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


def _navigation_outcome_reason(analysis: ScreenAnalysisResult) -> str:
    navigation = analysis.navigation_result
    if navigation is None:
        return "navigation_not_requested"
    if navigation.guidance is not None:
        return navigation.guidance.reasoning_summary
    if navigation.blocker is not None:
        return navigation.blocker.summary
    if navigation.recovery_hint is not None:
        return navigation.recovery_hint.summary
    if navigation.clarification_need is not None:
        return navigation.clarification_need.prompt
    return navigation.step_state.current_step_summary


def _navigation_candidate_telemetry(analysis: ScreenAnalysisResult) -> list[dict[str, Any]]:
    navigation = analysis.navigation_result
    if navigation is None:
        return []
    winning_id = navigation.winning_candidate.candidate_id if navigation.winning_candidate is not None else None
    top_score = navigation.ranked_candidates[0].score if navigation.ranked_candidates else 0.0
    return [
        {
            "candidate_id": candidate.candidate_id,
            "label": candidate.label,
            "role": candidate.role.value,
            "source_channel": candidate.source_channel.value,
            "source_type": candidate.source_type.value if candidate.source_type is not None else None,
            "score": candidate.score,
            "score_gap_from_top": max(0.0, top_score - candidate.score),
            "relative_outcome": "winner" if candidate.candidate_id == winning_id else "alternative",
            "reasons": list(candidate.reasons),
            "based_on_grounding": candidate.based_on_grounding,
        }
        for candidate in navigation.ranked_candidates[:4]
    ]


def _verification_outcome_reason(analysis: ScreenAnalysisResult) -> str:
    verification = analysis.verification_result
    if verification is None:
        return "verification_not_requested"
    if verification.explanation.summary:
        return verification.explanation.summary
    return verification.comparison.summary


def _verification_change_telemetry(analysis: ScreenAnalysisResult) -> list[dict[str, Any]]:
    verification = analysis.verification_result
    if verification is None:
        return []
    return [
        {
            "change_type": change.change_type,
            "classification": change.classification.value,
            "summary": change.summary,
            "from_value": change.from_value,
            "to_value": change.to_value,
            "evidence_summary": list(change.evidence_summary),
        }
        for change in verification.change_observations[:4]
    ]


def _calculation_telemetry(analysis: ScreenAnalysisResult) -> dict[str, Any]:
    activity = analysis.calculation_activity
    if activity is None:
        return {
            "requested": False,
            "used": False,
            "status": "not_requested",
            "caller_intent": None,
            "input_origin": None,
            "internal_validation": False,
            "result_visibility": None,
            "trace": None,
            "result": None,
            "failure": None,
        }
    return {
        "requested": True,
        "used": activity.status == "resolved",
        "status": activity.status,
        "caller_intent": activity.caller_intent,
        "input_origin": activity.input_origin,
        "internal_validation": activity.internal_validation,
        "result_visibility": activity.result_visibility,
        "trace": dict(activity.calculation_trace),
        "result": dict(activity.calculation_result or {}) if isinstance(activity.calculation_result, dict) else None,
        "failure": dict(activity.calculation_failure or {}) if isinstance(activity.calculation_failure, dict) else None,
    }


def _action_outcome_reason(analysis: ScreenAnalysisResult) -> str:
    action = analysis.action_result
    if action is None:
        return "action_not_requested"
    if action.explanation_summary:
        return action.explanation_summary
    return action.gate.reason


def _continuity_outcome_reason(analysis: ScreenAnalysisResult) -> str:
    continuity = analysis.continuity_result
    if continuity is None:
        return "continuity_not_requested"
    if continuity.explanation_summary:
        return continuity.explanation_summary
    if continuity.recovery_hint is not None:
        return continuity.recovery_hint.summary
    if continuity.detour_state is not None:
        return continuity.detour_state.summary
    return continuity.status.value


def _action_telemetry(analysis: ScreenAnalysisResult) -> dict[str, Any]:
    action = analysis.action_result
    if action is None:
        return {
            "requested": False,
            "outcome": "not_requested",
            "outcome_reason": "action_not_requested",
            "attempted": False,
            "confidence": None,
            "risk_level": None,
            "gate_decision": None,
            "confirmation_required": False,
            "target_candidate_id": None,
            "dominant_channel": None,
            "provenance_channels": [],
            "grounding_reused": False,
            "navigation_reused": False,
            "verification_reused": False,
            "text_payload_redacted": False,
            "post_action_verification_status": None,
            "planner_result": None,
        }
    return {
        "requested": True,
        "outcome": action.status.value,
        "outcome_reason": _action_outcome_reason(analysis),
        "attempted": action.attempt is not None,
        "confidence": action.confidence.to_dict(),
        "risk_level": action.gate.risk_level.value,
        "gate_decision": action.gate.outcome,
        "confirmation_required": action.gate.confirmation_required,
        "target_candidate_id": action.plan.target.candidate_id if action.plan.target is not None else None,
        "dominant_channel": action.provenance.dominant_channel.value if action.provenance.dominant_channel is not None else None,
        "provenance_channels": [channel.value for channel in action.provenance.channels_used],
        "grounding_reused": action.plan.grounding_reused,
        "navigation_reused": action.plan.navigation_reused,
        "verification_reused": action.plan.verification_reused,
        "text_payload_redacted": action.plan.text_payload_redacted,
        "post_action_verification_status": (
            action.post_action_verification.completion_status.value
            if action.post_action_verification is not None
            else None
        ),
        "planner_result": action.planner_result.to_dict() if action.planner_result is not None else None,
    }


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

        action = analysis.action_result
        if action is not None:
            target = (
                f'the {action.plan.target.role.value} "{action.plan.target.label}"'
                if action.plan.target is not None and action.plan.target.label
                else "the current focus"
            )
            if action.status == ActionExecutionStatus.PLANNED:
                text = (
                    f"Observed: {action.plan.preview_summary} "
                    "Inference: I'm holding that plan until you explicitly confirm the action."
                )
                return self._response("Action Bearings", text, analysis)
            if action.status == ActionExecutionStatus.AMBIGUOUS:
                text = (
                    f"Observed: {action.gate.reason} "
                    "Inference: I won't execute until the target ambiguity is resolved."
                )
                return self._response("Action Bearings", text, analysis)
            if action.status == ActionExecutionStatus.BLOCKED:
                text = (
                    f"Observed: {action.gate.reason} "
                    "Inference: the current state appears to block a safe execution attempt."
                )
                return self._response("Action Bearings", text, analysis)
            if action.status == ActionExecutionStatus.GATED:
                text = (
                    f"Observed: {action.gate.reason} "
                    "Inference: the current policy or risk posture keeps Stormhelm from executing this directly."
                )
                return self._response("Action Bearings", text, analysis)
            if action.status == ActionExecutionStatus.FAILED:
                text = (
                    f"Observed: I attempted the action on {target}, but the native execution layer reported a failure. "
                    "Inference: I cannot claim that the UI changed."
                )
                return self._response("Action Bearings", text, analysis)
            if action.status == ActionExecutionStatus.VERIFIED_SUCCESS:
                verification_summary = (
                    action.post_action_verification.explanation.summary
                    if action.post_action_verification is not None
                    else "The follow-up bearing supports the expected result."
                )
                text = (
                    f"Observed: I executed the action on {target}. {verification_summary} "
                    "Inference: the action appears successful from the current verification bearing."
                )
                return self._response("Action Bearings", text, analysis)
            if action.status == ActionExecutionStatus.ATTEMPTED_UNVERIFIED:
                verification_summary = (
                    action.post_action_verification.explanation.summary
                    if action.post_action_verification is not None
                    else "The follow-up bearing stayed weak."
                )
                text = (
                    f"Observed: I attempted the action on {target}. {verification_summary} "
                    "Inference: the action was attempted, but I can't verify success from the current evidence."
                )
                return self._response("Action Bearings", text, analysis)

        continuity = analysis.continuity_result
        if continuity is not None:
            if continuity.status.value == "resume_ready" and continuity.resume_candidate is not None:
                text = (
                    f'Observed: {continuity.explanation_summary} '
                    f'Inference: based on the recent workflow bearing, the next place to resume is "{continuity.resume_candidate.label}".'
                )
                return self._response("Continuity Bearings", text, analysis)
            if continuity.status.value == "recovery_ready" and continuity.recovery_hint is not None:
                text = (
                    f"Observed: {continuity.explanation_summary} "
                    f"{continuity.detour_state.summary if continuity.detour_state is not None else ''} "
                    f"{continuity.recovery_hint.summary} "
                    "Inference: this looks like a short detour rather than a completed workflow transition."
                )
                return self._response("Continuity Bearings", text, analysis)
            if continuity.status.value == "blocked":
                text = (
                    f"Observed: {continuity.explanation_summary} "
                    "Inference: I do not see a clean recovery path until the visible blocker changes."
                )
                return self._response("Continuity Bearings", text, analysis)
            if continuity.status.value == "ambiguous":
                text = (
                    f"Observed: {continuity.explanation_summary} "
                    "Inference: I see multiple plausible places to resume, so I won't collapse them into one story."
                )
                return self._response("Continuity Bearings", text, analysis)
            text = (
                f"Observed: {continuity.explanation_summary} "
                "Inference: I can't justify a precise resume point from the current continuity evidence."
            )
            return self._response("Continuity Bearings", text, analysis)

        verification = analysis.verification_result
        calculation_activity = analysis.calculation_activity
        if verification is not None:
            if calculation_activity is not None and calculation_activity.status == "resolved":
                if calculation_activity.internal_validation:
                    if verification.completion_status == CompletionStatus.COMPLETED:
                        text = (
                            f"Observed: {calculation_activity.summary} "
                            "Inference: the visible numeric claim checks out against the deterministic local calculation."
                        )
                    elif verification.completion_status == CompletionStatus.NOT_COMPLETED:
                        text = (
                            f"Observed: {calculation_activity.summary} "
                            "Inference: the displayed numeric claim does not match the deterministic local calculation."
                        )
                    else:
                        text = (
                            f"Observed: {calculation_activity.summary} "
                            "Inference: I verified the visible numeric input locally, but the surrounding screen meaning is still limited."
                        )
                    return self._response("Verification Bearings", text, analysis)
            if (
                verification.request.request_type.name == "CHANGE_CHECK"
                and verification.comparison.change_classification == ChangeClassification.INSUFFICIENT_EVIDENCE
            ):
                text = (
                    f"Observed: {verification.explanation.summary} "
                    "Inference: I can't verify a meaningful change because I do not have enough comparison basis."
                )
                return self._response("Verification Bearings", text, analysis)
            if verification.completion_status == CompletionStatus.COMPLETED:
                inference = "the expected visible result appears completed."
                if verification.request.wants_page_check and verification.expectation is not None and verification.expectation.target_label:
                    inference = "this matches the page you were aiming for."
                elif verification.request.wants_error_check:
                    inference = "the error condition appears cleared from the current evidence."
                elif not verification.comparison.comparison_ready:
                    inference = "based on the current screen state, the expected visible result appears completed."
                text = f"Observed: {verification.explanation.summary} Inference: {inference}"
                return self._response("Verification Bearings", text, analysis)
            if verification.completion_status == CompletionStatus.BLOCKED:
                text = (
                    f"Observed: {verification.explanation.summary} "
                    "Inference: something visible still appears to be blocking progress."
                )
                return self._response("Verification Bearings", text, analysis)
            if verification.completion_status == CompletionStatus.DIVERTED:
                text = (
                    f"Observed: {verification.explanation.summary} "
                    "Inference: you may be in a different page or section than the one you were aiming for."
                )
                return self._response("Verification Bearings", text, analysis)
            if verification.completion_status == CompletionStatus.NOT_COMPLETED:
                text = (
                    f"Observed: {verification.explanation.summary} "
                    "Inference: I do not see evidence that the expected result completed yet."
                )
                return self._response("Verification Bearings", text, analysis)
            if verification.comparison.change_classification == ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD:
                text = (
                    f"Observed: {verification.explanation.summary} "
                    "Inference: I can't yet tell what that change means for the workflow."
                )
                return self._response("Verification Bearings", text, analysis)
            cleanup_change = next(
                (
                    change
                    for change in verification.change_observations
                    if change.change_type in {"warning_disappeared", "modal_disappeared"}
                ),
                None,
            )
            if cleanup_change is not None:
                text = (
                    f"Observed: {cleanup_change.summary} "
                    "Inference: I cannot yet verify that the step completed."
                )
                return self._response("Verification Bearings", text, analysis)
            text = (
                f"Observed: {verification.explanation.summary} "
                "Inference: the current verification bearing is still ambiguous."
            )
            return self._response("Verification Bearings", text, analysis)

        if intent == ScreenIntentType.DETECT_VISIBLE_CHANGE:
            text = (
                "Observed: I only have a single current bearing, not a before-and-after comparison. "
                "Inference: I can't tell what changed without a prior screen observation to compare against, and I won't claim a verified change."
            )
            return self._response("Change Bearing", text, analysis)

        navigation = analysis.navigation_result
        if navigation is not None:
            if navigation.step_state.status == NavigationStepStatus.BLOCKED and navigation.blocker is not None:
                recovery = f" {navigation.recovery_hint.summary}" if navigation.recovery_hint is not None else ""
                text = (
                    f"Observed: {navigation.blocker.summary} is visible in the current workflow. "
                    f"Inference: that is likely blocking the next step.{recovery}"
                )
                return self._response("Guided Bearings", text, analysis)
            if navigation.step_state.status == NavigationStepStatus.WRONG_PAGE:
                recovery = navigation.recovery_hint.summary if navigation.recovery_hint is not None else "I need a clearer page cue to recover safely."
                text = (
                    "Observed: the current page does not appear to match the visible guidance cue for the next step. "
                    f"Inference: you may be in the wrong place. {recovery}"
                )
                return self._response("Guided Bearings", text, analysis)
            if navigation.step_state.status == NavigationStepStatus.AMBIGUOUS and navigation.clarification_need is not None:
                labels = ", ".join(candidate.label for candidate in navigation.ranked_candidates[:2])
                text = (
                    f"Observed: I see multiple plausible next targets: {labels}. "
                    f"Inference: I can't justify a single next step yet. {navigation.clarification_need.prompt}"
                )
                return self._response("Guided Bearings", text, analysis)
            if navigation.step_state.status == NavigationStepStatus.UNRESOLVED:
                prompt = navigation.clarification_need.prompt if navigation.clarification_need is not None else "Please give me a stronger visible anchor."
                if navigation.request.wants_page_check:
                    text = (
                        "Observed: I don't have enough direct page evidence to confirm or deny the current page alignment. "
                        f"Inference: {prompt}"
                    )
                else:
                    text = (
                        "Observed: I can't justify a single next step from the current evidence. "
                        f"Inference: {prompt}"
                    )
                return self._response("Guided Bearings", text, analysis)
            if navigation.guidance is not None and navigation.winning_candidate is not None:
                target = f'the {navigation.winning_candidate.role.value} "{navigation.winning_candidate.label}"'
                look_for = f" {navigation.guidance.look_for}" if navigation.guidance.look_for else ""
                text = (
                    f"Observed: Based on {navigation.guidance.provenance_note}, the strongest next target is {target}. "
                    f"Inference: {navigation.guidance.instruction}{look_for}"
                )
                return self._response("Guided Bearings", text, analysis)

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
                if (
                    intent == ScreenIntentType.SOLVE_VISIBLE_PROBLEM
                    and calculation_activity is not None
                    and calculation_activity.status == "resolved"
                ):
                        text = (
                            f"Observed: I grounded this request to {grounded_target}. "
                            f"Inference: {calculation_activity.summary}"
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

        if intent == ScreenIntentType.SOLVE_VISIBLE_PROBLEM and calculation_activity is not None:
            if calculation_activity.status == "resolved":
                text = (
                    f"Observed: the visible expression is {_preview(calculation_activity.source_text_preview)}. "
                    f"Inference: {calculation_activity.summary}"
                )
                return self._response("Visible Solution", text, analysis)
            if calculation_activity.status == "ambiguous":
                text = (
                    f"Observed: the visible numeric signal is still partial. "
                    f"Inference: {calculation_activity.summary}"
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
                "navigation": {
                    "requested": analysis.navigation_result is not None,
                    "outcome": analysis.navigation_result.step_state.status.value if analysis.navigation_result is not None else "not_requested",
                    "outcome_reason": _navigation_outcome_reason(analysis),
                    "candidate_count": len(analysis.navigation_result.ranked_candidates) if analysis.navigation_result is not None else 0,
                    "confidence": analysis.navigation_result.confidence.to_dict() if analysis.navigation_result is not None else None,
                    "winning_candidate_id": (
                        analysis.navigation_result.winning_candidate.candidate_id
                        if analysis.navigation_result is not None and analysis.navigation_result.winning_candidate is not None
                        else None
                    ),
                    "dominant_channel": (
                        analysis.navigation_result.provenance.dominant_channel.value
                        if analysis.navigation_result is not None and analysis.navigation_result.provenance.dominant_channel is not None
                        else None
                    ),
                    "provenance_channels": (
                        [channel.value for channel in analysis.navigation_result.provenance.channels_used]
                        if analysis.navigation_result is not None
                        else []
                    ),
                    "grounding_reused": (
                        analysis.navigation_result.context.grounding_reused
                        if analysis.navigation_result is not None
                        else False
                    ),
                    "blocker_present": (
                        analysis.navigation_result.blocker is not None
                        if analysis.navigation_result is not None
                        else False
                    ),
                    "wrong_page": (
                        analysis.navigation_result.step_state.wrong_page
                        if analysis.navigation_result is not None
                        else False
                    ),
                    "clarification_needed": (
                        analysis.navigation_result.clarification_need.needed
                        if analysis.navigation_result is not None and analysis.navigation_result.clarification_need is not None
                        else False
                    ),
                    "planner_result": (
                        analysis.navigation_result.planner_result.to_dict()
                        if analysis.navigation_result is not None and analysis.navigation_result.planner_result is not None
                        else None
                    ),
                    "explanation": (
                        analysis.navigation_result.guidance.reasoning_summary
                        if analysis.navigation_result is not None and analysis.navigation_result.guidance is not None
                        else _navigation_outcome_reason(analysis)
                    ),
                    "ranked_candidates": _navigation_candidate_telemetry(analysis),
                },
                "verification": {
                    "requested": analysis.verification_result is not None,
                    "outcome": analysis.verification_result.completion_status.value if analysis.verification_result is not None else "not_requested",
                    "outcome_reason": _verification_outcome_reason(analysis),
                    "confidence": analysis.verification_result.confidence.to_dict() if analysis.verification_result is not None else None,
                    "change_classification": (
                        analysis.verification_result.comparison.change_classification.value
                        if analysis.verification_result is not None
                        else "not_requested"
                    ),
                    "comparison_basis": (
                        analysis.verification_result.comparison.basis
                        if analysis.verification_result is not None
                        else "unavailable"
                    ),
                    "comparison_basis_reason": (
                        analysis.verification_result.comparison.basis_reason
                        if analysis.verification_result is not None
                        else ""
                    ),
                    "comparison_ready": (
                        analysis.verification_result.comparison.comparison_ready
                        if analysis.verification_result is not None
                        else False
                    ),
                    "compared_signals": (
                        list(analysis.verification_result.comparison.compared_signals)
                        if analysis.verification_result is not None
                        else []
                    ),
                    "dominant_channel": (
                        analysis.verification_result.provenance.dominant_channel.value
                        if analysis.verification_result is not None and analysis.verification_result.provenance.dominant_channel is not None
                        else None
                    ),
                    "provenance_channels": (
                        [channel.value for channel in analysis.verification_result.provenance.channels_used]
                        if analysis.verification_result is not None
                        else []
                    ),
                    "grounding_reused": (
                        analysis.verification_result.context.grounding_reused
                        if analysis.verification_result is not None
                        else False
                    ),
                    "navigation_reused": (
                        analysis.verification_result.context.navigation_reused
                        if analysis.verification_result is not None
                        else False
                    ),
                    "planner_result": (
                        analysis.verification_result.planner_result.to_dict()
                        if analysis.verification_result is not None and analysis.verification_result.planner_result is not None
                        else None
                    ),
                    "change_observations": _verification_change_telemetry(analysis),
                },
                "calculation": _calculation_telemetry(analysis),
                "action": _action_telemetry(analysis),
                "continuity": {
                    "requested": analysis.continuity_result is not None,
                    "outcome": analysis.continuity_result.status.value if analysis.continuity_result is not None else "not_requested",
                    "outcome_reason": _continuity_outcome_reason(analysis),
                    "confidence": analysis.continuity_result.confidence.to_dict() if analysis.continuity_result is not None else None,
                    "candidate_count": len(analysis.continuity_result.resume_options) if analysis.continuity_result is not None else 0,
                    "resume_candidate_id": (
                        analysis.continuity_result.resume_candidate.candidate_id
                        if analysis.continuity_result is not None and analysis.continuity_result.resume_candidate is not None
                        else None
                    ),
                    "timeline_event_count": len(analysis.continuity_result.timeline_events) if analysis.continuity_result is not None else 0,
                    "detour_active": (
                        analysis.continuity_result.detour_state.active
                        if analysis.continuity_result is not None and analysis.continuity_result.detour_state is not None
                        else False
                    ),
                    "grounding_reused": (
                        analysis.continuity_result.context.grounding_reused
                        if analysis.continuity_result is not None
                        else False
                    ),
                    "navigation_reused": (
                        analysis.continuity_result.context.navigation_reused
                        if analysis.continuity_result is not None
                        else False
                    ),
                    "verification_reused": (
                        analysis.continuity_result.context.verification_reused
                        if analysis.continuity_result is not None
                        else False
                    ),
                    "action_reused": (
                        analysis.continuity_result.context.action_reused
                        if analysis.continuity_result is not None
                        else False
                    ),
                    "dominant_channel": (
                        analysis.continuity_result.provenance.dominant_channel.value
                        if analysis.continuity_result is not None and analysis.continuity_result.provenance.dominant_channel is not None
                        else None
                    ),
                    "provenance_channels": (
                        [channel.value for channel in analysis.continuity_result.provenance.channels_used]
                        if analysis.continuity_result is not None
                        else []
                    ),
                    "clarification_needed": analysis.continuity_result.clarification_needed if analysis.continuity_result is not None else False,
                    "planner_result": (
                        analysis.continuity_result.planner_result.to_dict()
                        if analysis.continuity_result is not None and analysis.continuity_result.planner_result is not None
                        else None
                    ),
                },
                "limitations": [limitation.to_dict() for limitation in analysis.limitations],
            },
        )
