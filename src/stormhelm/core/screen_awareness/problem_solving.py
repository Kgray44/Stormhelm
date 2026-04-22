from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from stormhelm.core.calculations import CalculationOutputMode
from stormhelm.core.calculations import CalculationResultVisibility
from stormhelm.core.screen_awareness.calculations import run_screen_calculation
from stormhelm.core.screen_awareness.models import (
    ActionExecutionResult,
    AppAdapterResolution,
    CurrentScreenContext,
    ErrorTriageOutcome,
    ExplanationMode,
    GroundingEvidenceChannel,
    GroundingOutcome,
    GroundingProvenance,
    NavigationOutcome,
    PlannerProblemSolvingResult,
    ProblemAmbiguityState,
    ProblemAnswerStatus,
    ProblemSolvingResult,
    ScreenArtifactInterpretation,
    ScreenArtifactKind,
    ScreenCalculationActivity,
    ScreenConfidence,
    ScreenIntentType,
    ScreenInterpretation,
    ScreenObservation,
    ScreenProblemContext,
    ScreenProblemType,
    TeachingMode,
    VerificationOutcome,
    WorkflowContinuityResult,
    confidence_level_for_score,
)
from stormhelm.core.screen_awareness.observation import best_visible_text


_STEP_HINTS = ("step by step", "walk me through", "show me how", "break it down")
_TEACH_HINTS = ("teach me", "help me understand", "explain why")
_STRESS_HINTS = ("stressed", "overwhelmed", "panic", "anxious")
_CHART_HINTS = ("chart:", "x-axis", "y-axis", "bars:", "line:")
_NAME_PATTERN = re.compile(r"name '([^']+)' is not defined", re.IGNORECASE)
_VALUE_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _preview(text: str, *, limit: int = 140) -> str:
    cleaned = _clean(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


def _select_modes(operator_text: str, intent: ScreenIntentType) -> tuple[ExplanationMode, TeachingMode]:
    lower = _clean(operator_text).lower()
    if any(token in lower for token in _STRESS_HINTS):
        return ExplanationMode.STRESSED_USER, TeachingMode.STRESSED_USER
    if any(token in lower for token in _STEP_HINTS):
        return ExplanationMode.STEP_BY_STEP, TeachingMode.TEACHING
    if any(token in lower for token in _TEACH_HINTS):
        return ExplanationMode.TEACHING, TeachingMode.TEACHING
    if intent == ScreenIntentType.SOLVE_VISIBLE_PROBLEM:
        return ExplanationMode.DIRECT_ANSWER, TeachingMode.NONE
    return ExplanationMode.CONCISE_EXPLANATION, TeachingMode.NONE


def _calc_mode(mode: ExplanationMode) -> CalculationOutputMode:
    if mode in {ExplanationMode.STEP_BY_STEP, ExplanationMode.STRESSED_USER}:
        return CalculationOutputMode.STEP_BY_STEP
    if mode == ExplanationMode.TEACHING:
        return CalculationOutputMode.SHORT_BREAKDOWN
    return CalculationOutputMode.ANSWER_ONLY


def _dedupe_channels(channels: list[GroundingEvidenceChannel]) -> list[GroundingEvidenceChannel]:
    ordered: list[GroundingEvidenceChannel] = []
    for channel in channels:
        if channel not in ordered:
            ordered.append(channel)
    return ordered


def _dominant_channel(channels: list[GroundingEvidenceChannel]) -> GroundingEvidenceChannel | None:
    priority = [
        GroundingEvidenceChannel.NATIVE_OBSERVATION,
        GroundingEvidenceChannel.ADAPTER_SEMANTICS,
        GroundingEvidenceChannel.WORKSPACE_CONTEXT,
        GroundingEvidenceChannel.INTERPRETATION,
        GroundingEvidenceChannel.VISUAL_PROVIDER,
    ]
    for candidate in priority:
        if candidate in channels:
            return candidate
    return channels[0] if channels else None


def _base_channels(
    *,
    observation: ScreenObservation,
    interpretation: ScreenInterpretation,
    grounding_result: GroundingOutcome | None,
    navigation_result: NavigationOutcome | None,
    verification_result: VerificationOutcome | None,
    action_result: ActionExecutionResult | None,
    continuity_result: WorkflowContinuityResult | None,
    adapter_resolution: AppAdapterResolution | None,
) -> list[GroundingEvidenceChannel]:
    channels: list[GroundingEvidenceChannel] = []
    if observation.selected_text or observation.clipboard_text or observation.focus_metadata:
        channels.append(GroundingEvidenceChannel.NATIVE_OBSERVATION)
    workspace = observation.workspace_snapshot
    if workspace and (workspace.get("workspace") or workspace.get("active_item") or workspace.get("opened_items")):
        channels.append(GroundingEvidenceChannel.WORKSPACE_CONTEXT)
    if interpretation.visible_errors or interpretation.question_relevant_findings:
        channels.append(GroundingEvidenceChannel.INTERPRETATION)
    if adapter_resolution is not None and adapter_resolution.available:
        channels.append(GroundingEvidenceChannel.ADAPTER_SEMANTICS)
    for result in (grounding_result, navigation_result, verification_result, action_result, continuity_result):
        provenance = getattr(result, "provenance", None)
        if provenance is not None:
            channels.extend(list(provenance.channels_used))
    return _dedupe_channels(channels)


def _problem_context(
    *,
    visible_text: str,
    channels: list[GroundingEvidenceChannel],
    grounding_result: GroundingOutcome | None,
    navigation_result: NavigationOutcome | None,
    verification_result: VerificationOutcome | None,
    action_result: ActionExecutionResult | None,
    continuity_result: WorkflowContinuityResult | None,
    adapter_resolution: AppAdapterResolution | None,
) -> ScreenProblemContext:
    return ScreenProblemContext(
        visible_text_preview=_preview(visible_text),
        grounding_reused=grounding_result is not None,
        navigation_reused=navigation_result is not None,
        verification_reused=verification_result is not None,
        action_reused=action_result is not None,
        continuity_reused=continuity_result is not None,
        adapter_reused=adapter_resolution is not None and adapter_resolution.available,
        provenance_channels=channels,
    )


def _planner_result(
    *,
    problem_type: ScreenProblemType,
    artifact_kind: ScreenArtifactKind,
    explanation_mode: ExplanationMode,
    answer_status: ProblemAnswerStatus,
    ambiguity_state: ProblemAmbiguityState,
    confidence: ScreenConfidence,
    refusal_reason: str | None,
    channels: list[GroundingEvidenceChannel],
    adapter_contribution: bool,
) -> PlannerProblemSolvingResult:
    return PlannerProblemSolvingResult(
        resolved=answer_status != ProblemAnswerStatus.REFUSED,
        problem_type=problem_type,
        artifact_kind=artifact_kind,
        explanation_mode=explanation_mode,
        answer_status=answer_status,
        ambiguity_state=ambiguity_state,
        confidence=confidence,
        refusal_reason=refusal_reason,
        provenance_channels=list(channels),
        adapter_contribution=adapter_contribution,
    )


def _code_error_summary(
    *,
    error_text: str,
    specific: str,
    background: str,
    explanation_mode: ExplanationMode,
    name: str,
) -> str:
    observed = _preview(error_text)
    if explanation_mode == ExplanationMode.STRESSED_USER:
        missing_name = f"`{name}`" if name else "that name"
        return (
            f'Observed: the visible message reads "{observed}". '
            f"Inference: {specific} "
            f"Background: the important part is that Python hit {missing_name} and does not know it yet. "
            f"Start with where {missing_name} should have been defined or imported before this line ran."
        )
    if explanation_mode == ExplanationMode.STEP_BY_STEP:
        return (
            f'Observed: the visible message reads "{observed}". '
            f"Inference: {specific} "
            f"Background: {background} "
            "Step 1: find the line using that name. "
            "Step 2: trace upward to where it should have been defined or imported. "
            "Step 3: confirm the spelling matches in both places."
        )
    if explanation_mode == ExplanationMode.TEACHING:
        return (
            f'Observed: the visible message reads "{observed}". '
            f"Inference: {specific} "
            f"Background: {background} "
            "In plain terms, Python only understands names that already exist in the current scope or were imported first."
        )
    return f'Observed: the visible message reads "{observed}". Inference: {specific} Background: {background}'


@dataclass(slots=True)
class ProblemSolvingEnvelope:
    result: ProblemSolvingResult | None = None
    calculation_activity: ScreenCalculationActivity | None = None


@dataclass(slots=True)
class DeterministicProblemSolvingEngine:
    calculations: Any | None = None

    def solve(
        self,
        *,
        session_id: str,
        operator_text: str,
        intent: ScreenIntentType,
        surface_mode: str,
        active_module: str,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        verification_result: VerificationOutcome | None,
        action_result: ActionExecutionResult | None,
        continuity_result: WorkflowContinuityResult | None,
        adapter_resolution: AppAdapterResolution | None,
        active_context: dict[str, Any] | None,
    ) -> ProblemSolvingEnvelope | None:
        del active_context, current_context
        if intent not in {ScreenIntentType.EXPLAIN_VISIBLE_CONTENT, ScreenIntentType.SOLVE_VISIBLE_PROBLEM}:
            return None
        visible_text = best_visible_text(observation) or ""
        explanation_mode, teaching_mode = _select_modes(operator_text, intent)
        channels = _base_channels(
            observation=observation,
            interpretation=interpretation,
            grounding_result=grounding_result,
            navigation_result=navigation_result,
            verification_result=verification_result,
            action_result=action_result,
            continuity_result=continuity_result,
            adapter_resolution=adapter_resolution,
        )
        provenance = GroundingProvenance(
            channels_used=list(channels),
            dominant_channel=_dominant_channel(channels),
            signal_names=[name for name in [
                "selected_text" if observation.selected_text else "",
                "adapter_semantics" if adapter_resolution is not None and adapter_resolution.available else "",
                "visible_error" if interpretation.visible_errors else "",
            ] if name],
        )
        context = _problem_context(
            visible_text=visible_text,
            channels=channels,
            grounding_result=grounding_result,
            navigation_result=navigation_result,
            verification_result=verification_result,
            action_result=action_result,
            continuity_result=continuity_result,
            adapter_resolution=adapter_resolution,
        )
        validation = self._validation_match(visible_text=visible_text, adapter_resolution=adapter_resolution)
        if validation is not None:
            confidence = _confidence(0.85 if validation["adapter_used"] else 0.73, "Visible validation cues support the explanation.")
            return ProblemSolvingEnvelope(
                result=ProblemSolvingResult(
                    problem_type=ScreenProblemType.VALIDATION_ERROR,
                    artifact_kind=ScreenArtifactKind.FORM,
                    explanation_mode=explanation_mode,
                    teaching_mode=teaching_mode,
                    answer_status=ProblemAnswerStatus.EXPLANATION_ONLY,
                    ambiguity_state=ProblemAmbiguityState.CLEAR,
                    context=context,
                    triage=ErrorTriageOutcome(
                        classification="visible_validation_error",
                        severity="error",
                        observed_message=validation["message"],
                        meaning_summary=validation["meaning"],
                        bounded_next_step=validation["next_step"],
                        confidence=confidence,
                    ),
                    artifact_interpretation=ScreenArtifactInterpretation(
                        artifact_kind=ScreenArtifactKind.FORM,
                        observed_excerpt=_preview(validation["message"]),
                        structured_summary=validation["meaning"],
                    ),
                    answer_summary=(
                        f'Observed: the visible form message says "{validation["message"]}". '
                        f'Inference: {validation["meaning"]} '
                        "Background: this is a visible validation failure, not proof of a deeper hidden account problem."
                    ),
                    background_note="General form-validation knowledge was used to explain the visible message.",
                    planner_result=_planner_result(
                        problem_type=ScreenProblemType.VALIDATION_ERROR,
                        artifact_kind=ScreenArtifactKind.FORM,
                        explanation_mode=explanation_mode,
                        answer_status=ProblemAnswerStatus.EXPLANATION_ONLY,
                        ambiguity_state=ProblemAmbiguityState.CLEAR,
                        confidence=confidence,
                        refusal_reason=None,
                        channels=channels,
                        adapter_contribution=validation["adapter_used"],
                    ),
                    provenance=provenance,
                    confidence=confidence,
                    reused_adapter=validation["adapter_used"],
                    reused_grounding=grounding_result is not None,
                    reused_navigation=navigation_result is not None,
                    reused_verification=verification_result is not None,
                    reused_action=action_result is not None,
                    reused_continuity=continuity_result is not None,
                )
            )

        if interpretation.visible_errors:
            error_text = interpretation.visible_errors[0]
            if "nameerror" in error_text.lower() or observation.selection_metadata.get("kind") == "code":
                name_match = _NAME_PATTERN.search(error_text)
                name = name_match.group(1) if name_match else ""
                specific = f"This is a Python NameError involving `{name}`." if name else "This is a Python NameError."
                background = (
                    f"In Python, that usually means `{name}` was referenced before it was defined or imported."
                    if name
                    else "In Python, that usually means a name was referenced before it was defined or imported."
                )
                confidence = _confidence(0.84, "The visible error text directly identifies a Python runtime error.")
                return ProblemSolvingEnvelope(
                    result=ProblemSolvingResult(
                        problem_type=ScreenProblemType.CODE_ERROR,
                        artifact_kind=ScreenArtifactKind.CODE,
                        explanation_mode=explanation_mode,
                        teaching_mode=teaching_mode,
                        answer_status=ProblemAnswerStatus.EXPLANATION_ONLY,
                        ambiguity_state=ProblemAmbiguityState.CLEAR,
                        context=context,
                        triage=ErrorTriageOutcome(
                            classification="python_nameerror",
                            severity="error",
                            observed_message=error_text,
                            meaning_summary=specific,
                            bounded_next_step="Check where the missing name should be defined or imported before the failing line runs.",
                            confidence=confidence,
                        ),
                        artifact_interpretation=ScreenArtifactInterpretation(
                            artifact_kind=ScreenArtifactKind.CODE,
                            observed_excerpt=_preview(error_text),
                            structured_summary=specific,
                        ),
                        answer_summary=_code_error_summary(
                            error_text=error_text,
                            specific=specific,
                            background=background,
                            explanation_mode=explanation_mode,
                            name=name,
                        ),
                        background_note="General Python error knowledge was used to explain the visible message.",
                        planner_result=_planner_result(
                            problem_type=ScreenProblemType.CODE_ERROR,
                            artifact_kind=ScreenArtifactKind.CODE,
                            explanation_mode=explanation_mode,
                            answer_status=ProblemAnswerStatus.EXPLANATION_ONLY,
                            ambiguity_state=ProblemAmbiguityState.CLEAR,
                            confidence=confidence,
                            refusal_reason=None,
                            channels=channels,
                            adapter_contribution=False,
                        ),
                        provenance=provenance,
                        confidence=confidence,
                        reused_grounding=grounding_result is not None,
                        reused_navigation=navigation_result is not None,
                        reused_verification=verification_result is not None,
                        reused_action=action_result is not None,
                        reused_continuity=continuity_result is not None,
                    )
                )

        if _clean(visible_text).lower().startswith("chart:") or any(token in _clean(visible_text).lower() for token in _CHART_HINTS):
            values = [match.group(0) for match in _VALUE_PATTERN.finditer(visible_text)]
            trend = self._chart_trend(values)
            confidence = _confidence(0.66 if trend else 0.48, "The chart explanation comes from visible labels and values only.")
            return ProblemSolvingEnvelope(
                result=ProblemSolvingResult(
                    problem_type=ScreenProblemType.CHART_INTERPRETATION,
                    artifact_kind=ScreenArtifactKind.CHART,
                    explanation_mode=explanation_mode,
                    teaching_mode=teaching_mode,
                    answer_status=ProblemAnswerStatus.APPROXIMATE if trend else ProblemAnswerStatus.EXPLANATION_ONLY,
                    ambiguity_state=ProblemAmbiguityState.CLEAR if trend else ProblemAmbiguityState.PARTIAL,
                    context=context,
                    artifact_interpretation=ScreenArtifactInterpretation(
                        artifact_kind=ScreenArtifactKind.CHART,
                        observed_excerpt=_preview(visible_text),
                        structured_summary=trend or "The visible chart text is only partial.",
                        visible_values=values,
                        uncertainty_notes=["This only describes the visible trend, not the hidden cause behind it."],
                    ),
                    answer_summary=(
                        f"Observed: the chart text reads {_preview(visible_text)}. "
                        f"Inference: {trend or 'I can only describe the visible structure, not a full chart story.'} "
                        "Background: that is a bounded trend description from the visible chart, not a causal diagnosis."
                    ),
                    background_note="General chart-reading knowledge was used to describe the visible trend.",
                    planner_result=_planner_result(
                        problem_type=ScreenProblemType.CHART_INTERPRETATION,
                        artifact_kind=ScreenArtifactKind.CHART,
                        explanation_mode=explanation_mode,
                        answer_status=ProblemAnswerStatus.APPROXIMATE if trend else ProblemAnswerStatus.EXPLANATION_ONLY,
                        ambiguity_state=ProblemAmbiguityState.CLEAR if trend else ProblemAmbiguityState.PARTIAL,
                        confidence=confidence,
                        refusal_reason=None if trend else "partial_chart_signal",
                        channels=channels,
                        adapter_contribution=False,
                    ),
                    provenance=provenance,
                    confidence=confidence,
                    reused_adapter=adapter_resolution is not None and adapter_resolution.available,
                    reused_grounding=grounding_result is not None,
                    reused_navigation=navigation_result is not None,
                    reused_verification=verification_result is not None,
                    reused_action=action_result is not None,
                    reused_continuity=continuity_result is not None,
                    refusal_reason=None if trend else "partial_chart_signal",
                )
            )

        if intent == ScreenIntentType.SOLVE_VISIBLE_PROBLEM:
            if "..." in visible_text or "…" in visible_text:
                confidence = _confidence(0.31, "The visible problem statement is truncated.")
                return ProblemSolvingEnvelope(
                    result=ProblemSolvingResult(
                        problem_type=ScreenProblemType.GENERAL_VISIBLE_PROBLEM,
                        artifact_kind=ScreenArtifactKind.TEXT,
                        explanation_mode=explanation_mode,
                        teaching_mode=teaching_mode,
                        answer_status=ProblemAnswerStatus.PARTIAL,
                        ambiguity_state=ProblemAmbiguityState.PARTIAL,
                        context=context,
                        artifact_interpretation=ScreenArtifactInterpretation(
                            artifact_kind=ScreenArtifactKind.TEXT,
                            observed_excerpt=_preview(visible_text),
                            structured_summary="The visible problem statement is truncated, so the givens are incomplete.",
                            uncertainty_notes=["The visible text appears clipped or unfinished."],
                        ),
                        answer_summary=(
                            f"Observed: the visible problem reads {_preview(visible_text)}. "
                            "Inference: I can only give a partial bearing because the statement appears truncated. "
                            "I can't justify an exact solution from this visible fragment."
                        ),
                        refusal_reason="truncated_visible_problem",
                        planner_result=_planner_result(
                            problem_type=ScreenProblemType.GENERAL_VISIBLE_PROBLEM,
                            artifact_kind=ScreenArtifactKind.TEXT,
                            explanation_mode=explanation_mode,
                            answer_status=ProblemAnswerStatus.PARTIAL,
                            ambiguity_state=ProblemAmbiguityState.PARTIAL,
                            confidence=confidence,
                            refusal_reason="truncated_visible_problem",
                            channels=channels,
                            adapter_contribution=False,
                        ),
                        provenance=provenance,
                        confidence=confidence,
                        reused_adapter=adapter_resolution is not None and adapter_resolution.available,
                    )
                )
            preferred_text = (
                grounding_result.winning_target.visible_text
                if grounding_result is not None and grounding_result.winning_target is not None
                else None
            )
            activity = run_screen_calculation(
                calculations=self.calculations,
                session_id=session_id,
                surface_mode=surface_mode,
                active_module=active_module,
                operator_text=operator_text,
                observation=observation,
                caller_intent="solve_visible_problem",
                preferred_text=preferred_text,
                requested_mode=_calc_mode(explanation_mode),
                internal_validation=False,
                result_visibility=CalculationResultVisibility.USER_FACING,
            )
            if activity is not None:
                return ProblemSolvingEnvelope(
                    result=self._calculation_result(
                        activity=activity,
                        explanation_mode=explanation_mode,
                        teaching_mode=teaching_mode,
                        visible_text=visible_text,
                        context=context,
                        provenance=provenance,
                        channels=channels,
                        adapter_resolution=adapter_resolution,
                    ),
                    calculation_activity=activity,
                )

        if not visible_text:
            confidence = _confidence(0.0, "No visible text was available for Phase 8 problem solving.")
            return ProblemSolvingEnvelope(
                result=ProblemSolvingResult(
                    problem_type=ScreenProblemType.UNKNOWN,
                    artifact_kind=ScreenArtifactKind.UNKNOWN,
                    explanation_mode=explanation_mode,
                    teaching_mode=teaching_mode,
                    answer_status=ProblemAnswerStatus.REFUSED,
                    ambiguity_state=ProblemAmbiguityState.INSUFFICIENT_EVIDENCE,
                    context=context,
                    answer_summary=(
                        "Observed: I do not have a reliable visible problem artifact yet. "
                        "Inference: I can't ground a truthful explanation from the current screen signal."
                    ),
                    refusal_reason="no_visible_problem_signal",
                    planner_result=_planner_result(
                        problem_type=ScreenProblemType.UNKNOWN,
                        artifact_kind=ScreenArtifactKind.UNKNOWN,
                        explanation_mode=explanation_mode,
                        answer_status=ProblemAnswerStatus.REFUSED,
                        ambiguity_state=ProblemAmbiguityState.INSUFFICIENT_EVIDENCE,
                        confidence=confidence,
                        refusal_reason="no_visible_problem_signal",
                        channels=channels,
                        adapter_contribution=False,
                    ),
                    provenance=provenance,
                    confidence=confidence,
                )
            )

        confidence = _confidence(0.46, "The visible problem can only be described at a bounded level.")
        return ProblemSolvingEnvelope(
            result=ProblemSolvingResult(
                problem_type=ScreenProblemType.GENERAL_VISIBLE_PROBLEM,
                artifact_kind=ScreenArtifactKind.TEXT,
                explanation_mode=explanation_mode,
                teaching_mode=teaching_mode,
                answer_status=ProblemAnswerStatus.EXPLANATION_ONLY,
                ambiguity_state=ProblemAmbiguityState.PARTIAL,
                context=context,
                artifact_interpretation=ScreenArtifactInterpretation(
                    artifact_kind=ScreenArtifactKind.TEXT,
                    observed_excerpt=_preview(visible_text),
                    structured_summary="The visible text supports a bounded explanation, but not a full diagnosis.",
                    uncertainty_notes=list(interpretation.uncertainty_notes),
                ),
                answer_summary=(
                    f"Observed: {_preview(visible_text)}. "
                    "Inference: I can explain the visible problem at a bounded level, but I can't justify a stronger claim from the current evidence."
                ),
                planner_result=_planner_result(
                    problem_type=ScreenProblemType.GENERAL_VISIBLE_PROBLEM,
                    artifact_kind=ScreenArtifactKind.TEXT,
                    explanation_mode=explanation_mode,
                    answer_status=ProblemAnswerStatus.EXPLANATION_ONLY,
                    ambiguity_state=ProblemAmbiguityState.PARTIAL,
                    confidence=confidence,
                    refusal_reason=None,
                    channels=channels,
                    adapter_contribution=adapter_resolution is not None and adapter_resolution.available,
                ),
                provenance=provenance,
                confidence=confidence,
                reused_adapter=adapter_resolution is not None and adapter_resolution.available,
            )
        )

    def _validation_match(
        self,
        *,
        visible_text: str,
        adapter_resolution: AppAdapterResolution | None,
    ) -> dict[str, Any] | None:
        message = _clean(visible_text)
        if not message or "required" not in message.lower():
            return None
        adapter_used = False
        next_step = "Fill the visible field the message refers to, then try again."
        if (
            adapter_resolution is not None
            and adapter_resolution.available
            and adapter_resolution.semantic_context is not None
            and adapter_resolution.semantic_context.browser is not None
        ):
            browser = adapter_resolution.semantic_context.browser
            for validation in browser.validation_messages:
                if _clean(validation).lower() == message.lower():
                    adapter_used = True
                    label = next(
                        (
                            _clean(field.label)
                            for field in browser.form_fields
                            if _clean(field.label) and _clean(field.label).lower() in message.lower()
                        ),
                        "",
                    )
                    if label:
                        next_step = f"Use the visible {label} field before continuing."
                    break
        return {
            "message": message,
            "meaning": "The visible form is waiting for a required value before it can continue.",
            "next_step": next_step,
            "adapter_used": adapter_used,
        }

    def _calculation_result(
        self,
        *,
        activity: ScreenCalculationActivity,
        explanation_mode: ExplanationMode,
        teaching_mode: TeachingMode,
        visible_text: str,
        context: ScreenProblemContext,
        provenance: GroundingProvenance,
        channels: list[GroundingEvidenceChannel],
        adapter_resolution: AppAdapterResolution | None,
    ) -> ProblemSolvingResult:
        if activity.status == "resolved":
            formatted_value = ""
            if isinstance(activity.calculation_result, dict):
                formatted_value = _clean(activity.calculation_result.get("formatted_value"))
            formatted_value = formatted_value or _clean(activity.summary)
            steps = [line.strip() for line in str(activity.summary or "").splitlines() if line.strip()]
            if explanation_mode == ExplanationMode.STEP_BY_STEP:
                numbered_steps = [
                    line if line[:2] in {"1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."} else f"{index}. {line}"
                    for index, line in enumerate(steps, start=1)
                ]
                summary = (
                    f"Observed: the visible expression is {_preview(visible_text or activity.source_text_preview)}.\n"
                    + "\n".join(numbered_steps)
                )
            elif explanation_mode == ExplanationMode.STRESSED_USER:
                summary = (
                    f"Observed: the visible expression is {_preview(visible_text or activity.source_text_preview)}. "
                    "The important part is to solve one piece at a time. Start with the parentheses, then finish the multiplication. "
                    f"The current answer comes out to {formatted_value}."
                )
            else:
                summary = (
                    f"Observed: the visible expression is {_preview(visible_text or activity.source_text_preview)}. "
                    f"Inference: {formatted_value}"
                )
            status = ProblemAnswerStatus.DIRECT_ANSWER
            ambiguity = ProblemAmbiguityState.CLEAR
            refusal_reason = None
        else:
            steps = []
            summary = (
                f"Observed: the visible numeric request is {_preview(visible_text or activity.source_text_preview)}. "
                f"Inference: {activity.summary or 'I could not isolate enough numeric signal to solve it yet.'}"
            )
            status = ProblemAnswerStatus.PARTIAL
            ambiguity = ProblemAmbiguityState.PARTIAL
            refusal_reason = activity.ambiguous_reason or "unsupported_visible_expression"

        return ProblemSolvingResult(
            problem_type=ScreenProblemType.EQUATION_SOLVE,
            artifact_kind=ScreenArtifactKind.EQUATION,
            explanation_mode=explanation_mode,
            teaching_mode=teaching_mode,
            answer_status=status,
            ambiguity_state=ambiguity,
            context=context,
            artifact_interpretation=ScreenArtifactInterpretation(
                artifact_kind=ScreenArtifactKind.EQUATION,
                observed_excerpt=_preview(visible_text or activity.source_text_preview),
                structured_summary="The visible expression can be evaluated directly from the available numeric text."
                if activity.status == "resolved"
                else "The numeric artifact is visible, but the solvable expression is incomplete.",
                visible_values=[match.group(0) for match in _VALUE_PATTERN.finditer(visible_text or activity.source_text_preview)],
                uncertainty_notes=[] if activity.status == "resolved" else [activity.summary or "The visible numeric signal was incomplete."],
            ),
            answer_summary=summary,
            answer_steps=steps,
            refusal_reason=refusal_reason,
            planner_result=_planner_result(
                problem_type=ScreenProblemType.EQUATION_SOLVE,
                artifact_kind=ScreenArtifactKind.EQUATION,
                explanation_mode=explanation_mode,
                answer_status=status,
                ambiguity_state=ambiguity,
                confidence=activity.confidence,
                refusal_reason=refusal_reason,
                channels=channels,
                adapter_contribution=adapter_resolution is not None and adapter_resolution.available,
            ),
            provenance=provenance,
            confidence=activity.confidence,
            reused_adapter=adapter_resolution is not None and adapter_resolution.available,
        )

    def _chart_trend(self, values: list[str]) -> str | None:
        numbers: list[float] = []
        for value in values[:6]:
            try:
                numbers.append(float(value))
            except ValueError:
                continue
        if len(numbers) < 2:
            return None
        start, peak, end = numbers[0], max(numbers), numbers[-1]
        if peak > start and end < peak:
            return f"The visible series rises from {start:g} to a peak of {peak:g}, then dips slightly to {end:g}."
        if end > start:
            return f"The visible series rises overall from {start:g} to {end:g}."
        if end < start:
            return f"The visible series trends downward from {start:g} to {end:g}."
        return f"The visible series stays relatively stable around {end:g}."
