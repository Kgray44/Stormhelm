from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from stormhelm.core.calculations import CalculationResultVisibility
from stormhelm.core.screen_awareness.calculations import run_screen_calculation
from stormhelm.core.screen_awareness.models import ChangeClassification
from stormhelm.core.screen_awareness.models import ChangeObservation
from stormhelm.core.screen_awareness.models import CompletionStatus
from stormhelm.core.screen_awareness.models import CurrentScreenContext
from stormhelm.core.screen_awareness.models import GroundingEvidenceChannel
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import GroundingProvenance
from stormhelm.core.screen_awareness.models import NavigationOutcome
from stormhelm.core.screen_awareness.models import PlannerVerificationResult
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenInterpretation
from stormhelm.core.screen_awareness.models import ScreenObservation
from stormhelm.core.screen_awareness.models import ScreenTruthState
from stormhelm.core.screen_awareness.models import UnresolvedCondition
from stormhelm.core.screen_awareness.models import VerificationComparison
from stormhelm.core.screen_awareness.models import VerificationContext
from stormhelm.core.screen_awareness.models import VerificationEvidence
from stormhelm.core.screen_awareness.models import VerificationExpectation
from stormhelm.core.screen_awareness.models import VerificationExplanation
from stormhelm.core.screen_awareness.models import VerificationOutcome
from stormhelm.core.screen_awareness.models import VerificationRequest
from stormhelm.core.screen_awareness.models import VerificationRequestType
from stormhelm.core.screen_awareness.models import confidence_level_for_score
from stormhelm.core.screen_awareness.observation import best_visible_text


_RESULT_HINTS = {"did that work", "did it work", "did that button actually do anything"}
_CHANGE_HINTS = {"what changed", "what changed on my screen", "did anything change", "did this change"}
_COMPLETION_HINTS = {"am i done with this step", "am i done", "did this finish"}
_PAGE_HINTS = {"is this the page i was trying to get to", "is this the page i wanted"}
_ERROR_HINTS = {"did the error go away", "is the error gone", "did the warning go away", "is the warning gone"}
_BLOCKER_HINTS = {"what is still preventing me from continuing", "what is still blocking me", "is it still loading"}
_NUMERIC_VERIFICATION_HINTS = {
    "do these numbers add up",
    "do these values add up",
    "does this add up",
    "does this total add up",
    "is this total right",
    "what do these add up to",
    "double check this total",
}
_SUCCESS_TOKENS = {"saved successfully", "success", "completed", "done", "finished", "approved", "connected"}
_BROWSER_SUFFIX = re.compile(r"\s*-\s*(google chrome|microsoft edge|firefox|brave)\s*$", flags=re.IGNORECASE)
_PRIOR_BEARING_STALE_SECONDS = 15 * 60
_MODAL_KINDS = {"dialog", "modal", "popup", "prompt", "sheet"}
_MODAL_KEYWORDS = ("dialog", "modal", "popup", "prompt")


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_text(value))


def _score_confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


def _current_page_label(observation: ScreenObservation) -> str | None:
    active_item = observation.workspace_snapshot.get("active_item")
    if isinstance(active_item, dict):
        label = str(active_item.get("title") or active_item.get("name") or "").strip()
        if label:
            return label
    title = str(observation.focus_metadata.get("window_title") or "").strip()
    if not title:
        return None
    cleaned = _BROWSER_SUFFIX.sub("", title).strip()
    return cleaned or title


def _workspace_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    active_item = snapshot.get("active_item")
    if isinstance(active_item, dict):
        items.append(active_item)
    items.extend(item for item in snapshot.get("opened_items") or [] if isinstance(item, dict))
    return items


def _modal_label_from_snapshot(snapshot: dict[str, Any]) -> str | None:
    for item in _workspace_items(snapshot):
        kind = str(item.get("kind") or item.get("viewer") or "").strip().lower()
        title = str(item.get("title") or item.get("name") or "").strip()
        lowered_title = title.lower()
        if kind in _MODAL_KINDS or any(keyword in lowered_title for keyword in _MODAL_KEYWORDS):
            return title or kind
    return None


def _current_modal_label(observation: ScreenObservation) -> str | None:
    return _modal_label_from_snapshot(observation.workspace_snapshot)


def _success_signal(observation: ScreenObservation, interpretation: ScreenInterpretation) -> str | None:
    visible_text = best_visible_text(observation)
    normalized = _normalize_text(visible_text)
    if any(token in normalized for token in _SUCCESS_TOKENS):
        return visible_text
    for item in observation.workspace_snapshot.get("opened_items") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("title") or item.get("name") or "").strip()
        if label and any(token in label.lower() for token in _SUCCESS_TOKENS):
            return label
    for message in interpretation.visible_messages:
        if any(token in message.lower() for token in _SUCCESS_TOKENS):
            return message
    return None


def _disabled_control(observation: ScreenObservation) -> str | None:
    for item in _workspace_items(observation.workspace_snapshot):
        label = str(item.get("title") or item.get("name") or "").strip()
        if label and item.get("enabled") is False:
            return label
    return None


def _screen_resolutions(active_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(active_context, dict):
        return []
    recent = active_context.get("recent_context_resolutions")
    if not isinstance(recent, list):
        return []
    return [
        dict(entry)
        for entry in recent
        if isinstance(entry, dict) and str(entry.get("kind") or "").strip() == "screen_awareness"
    ]


def _prior_analysis(prior_resolution: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(prior_resolution, dict):
        return {}
    analysis = prior_resolution.get("analysis_result")
    return dict(analysis) if isinstance(analysis, dict) else {}


def _prior_visible_errors(prior_analysis: dict[str, Any]) -> list[str]:
    interpretation = prior_analysis.get("interpretation")
    if not isinstance(interpretation, dict):
        return []
    return [str(item).strip() for item in interpretation.get("visible_errors", []) if str(item).strip()]


def _prior_summary(prior_analysis: dict[str, Any]) -> str | None:
    context = prior_analysis.get("current_screen_context")
    if not isinstance(context, dict):
        return None
    summary = str(context.get("summary") or "").strip()
    return summary or None


def _prior_page_label(prior_analysis: dict[str, Any]) -> str | None:
    context = prior_analysis.get("current_screen_context")
    if not isinstance(context, dict):
        return None
    summary = str(context.get("summary") or "").strip()
    match = re.search(r'on "([^"]+)"', summary)
    if match:
        return str(match.group(1)).strip()
    match = re.search(r"focused on ([^.]+)", summary, flags=re.IGNORECASE)
    if match:
        return str(match.group(1)).strip().strip('"')
    return None


def _prior_modal_label(prior_analysis: dict[str, Any]) -> str | None:
    observation = prior_analysis.get("observation")
    if not isinstance(observation, dict):
        return None
    workspace_snapshot = observation.get("workspace_snapshot")
    if not isinstance(workspace_snapshot, dict):
        return None
    return _modal_label_from_snapshot(workspace_snapshot)


def _resolution_age_seconds(resolution: dict[str, Any]) -> float | None:
    captured_at = resolution.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at.strip():
        return None
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - captured.astimezone(timezone.utc)).total_seconds())


def _expected_target_label(prior_analysis: dict[str, Any], grounding_result: GroundingOutcome | None) -> str | None:
    navigation = prior_analysis.get("navigation_result")
    if isinstance(navigation, dict):
        step_state = navigation.get("step_state")
        if isinstance(step_state, dict):
            label = str(step_state.get("expected_target_label") or "").strip()
            if label:
                return label
        winning_candidate = navigation.get("winning_candidate")
        if isinstance(winning_candidate, dict):
            label = str(winning_candidate.get("label") or "").strip()
            if label:
                return label
    return None


def _comparison_reason_summary(reason: str) -> str:
    if reason == "stale_prior_bearing":
        return "The prior bearing is too stale or weakly anchored to support a trustworthy before-and-after comparison."
    if reason == "prior_bearing_too_thin":
        return "The prior bearing did not carry enough comparable signals for a meaningful before-and-after check."
    return "I only have the current bearing, not a prior screen state to compare against."


@dataclass(slots=True)
class DeterministicVerificationEngine:
    calculations: Any | None = None

    def should_verify(self, *, operator_text: str, intent: ScreenIntentType) -> bool:
        lowered = _normalize_text(operator_text)
        return intent in {ScreenIntentType.VERIFY_SCREEN_STATE, ScreenIntentType.DETECT_VISIBLE_CHANGE} or any(
            phrase in lowered
            for phrase in (
                *_RESULT_HINTS,
                *_CHANGE_HINTS,
                *_COMPLETION_HINTS,
                *_PAGE_HINTS,
                *_ERROR_HINTS,
                *_BLOCKER_HINTS,
                *_NUMERIC_VERIFICATION_HINTS,
            )
        )

    def build_request(self, *, operator_text: str, intent: ScreenIntentType) -> VerificationRequest:
        lowered = _normalize_text(operator_text)
        request_type = VerificationRequestType.RESULT_CHECK
        if intent == ScreenIntentType.DETECT_VISIBLE_CHANGE or any(phrase in lowered for phrase in _CHANGE_HINTS):
            request_type = VerificationRequestType.CHANGE_CHECK
        elif any(phrase in lowered for phrase in _COMPLETION_HINTS):
            request_type = VerificationRequestType.COMPLETION_CHECK
        elif any(phrase in lowered for phrase in _PAGE_HINTS):
            request_type = VerificationRequestType.PAGE_CHECK
        elif any(phrase in lowered for phrase in _ERROR_HINTS):
            request_type = VerificationRequestType.ERROR_CHECK
        elif any(phrase in lowered for phrase in _BLOCKER_HINTS):
            request_type = VerificationRequestType.BLOCKER_CHECK
        return VerificationRequest(
            utterance=operator_text,
            request_type=request_type,
            referenced_tokens=_tokenize(lowered),
            wants_change_summary=request_type == VerificationRequestType.CHANGE_CHECK,
            wants_completion_check=request_type in {VerificationRequestType.RESULT_CHECK, VerificationRequestType.COMPLETION_CHECK},
            wants_page_check=request_type == VerificationRequestType.PAGE_CHECK,
            wants_error_check=request_type == VerificationRequestType.ERROR_CHECK,
            wants_blocker_check=request_type == VerificationRequestType.BLOCKER_CHECK,
            mode_flags=[flag for flag, present in {"deictic": any(token in lowered.split() for token in {"this", "that", "it"})}.items() if present],
        )

    def verify(
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
        active_context: dict[str, Any] | None,
    ) -> VerificationOutcome | None:
        if not self.should_verify(operator_text=operator_text, intent=intent):
            return None

        request = self.build_request(operator_text=operator_text, intent=intent)
        lowered = _normalize_text(operator_text)
        if any(phrase in lowered for phrase in _NUMERIC_VERIFICATION_HINTS):
            calculation_activity = run_screen_calculation(
                calculations=self.calculations,
                session_id=session_id,
                surface_mode=surface_mode,
                active_module=active_module,
                operator_text=operator_text,
                observation=observation,
                caller_intent="numeric_screen_verification",
                internal_validation=True,
                result_visibility=CalculationResultVisibility.SILENT_INTERNAL,
            )
            if calculation_activity is not None:
                return self._numeric_verification_outcome(
                    request=request,
                    observation=observation,
                    calculation_activity=calculation_activity,
                )

        current_page = _current_page_label(observation)
        current_errors = list(interpretation.visible_errors)
        current_modal = _current_modal_label(observation)
        success_signal = _success_signal(observation, interpretation)
        disabled_control = _disabled_control(observation)
        (
            prior_analysis,
            prior_page,
            prior_errors,
            prior_modal,
            expected_target,
            prior_basis_reason,
        ) = self._select_prior_analysis(
            active_context=active_context,
            request=request,
            grounding_result=grounding_result,
        )

        context = VerificationContext(
            current_summary=current_context.summary or "",
            prior_summary=_prior_summary(prior_analysis),
            current_page_label=current_page,
            prior_page_label=prior_page,
            expected_target_label=expected_target,
            prior_resolution_available=bool(prior_analysis),
            grounding_reused=bool(prior_analysis.get("grounding_result")),
            navigation_reused=bool(prior_analysis.get("navigation_result")),
            provenance_channels=self._provenance_channels(
                observation=observation,
                grounding_result=grounding_result,
                navigation_result=navigation_result,
            ),
        )
        expectation = self._expectation(request=request, expected_target=expected_target, prior_errors=prior_errors)
        comparison, change_observations = self._comparison(
            request=request,
            prior_analysis=prior_analysis,
            prior_basis_reason=prior_basis_reason,
            prior_errors=prior_errors,
            current_errors=current_errors,
            prior_modal=prior_modal,
            current_modal=current_modal,
            prior_page=prior_page,
            current_page=current_page,
            expected_target=expected_target,
        )
        unresolved_conditions = self._unresolved_conditions(
            request=request,
            current_errors=current_errors,
            disabled_control=disabled_control,
            current_page=current_page,
            expected_target=expected_target,
            comparison=comparison,
        )
        completion_status = self._completion_status(
            request=request,
            comparison=comparison,
            unresolved_conditions=unresolved_conditions,
            success_signal=success_signal,
            current_errors=current_errors,
            current_page=current_page,
            expected_target=expected_target,
        )
        evidence = self._evidence(
            comparison=comparison,
            context=context,
            success_signal=success_signal,
            current_errors=current_errors,
            disabled_control=disabled_control,
        )
        provenance = GroundingProvenance(
            channels_used=list(context.provenance_channels),
            dominant_channel=context.provenance_channels[0] if context.provenance_channels else None,
            signal_names=[item.signal for item in evidence],
        )
        confidence = self._confidence(
            comparison=comparison,
            completion_status=completion_status,
            success_signal=success_signal,
            current_errors=current_errors,
            expected_target=expected_target,
            current_page=current_page,
        )
        explanation = self._explanation(
            request=request,
            comparison=comparison,
            completion_status=completion_status,
            success_signal=success_signal,
            current_errors=current_errors,
            current_page=current_page,
            expected_target=expected_target,
            change_observations=change_observations,
        )
        planner_result = PlannerVerificationResult(
            request_type=request.request_type,
            resolved=completion_status == CompletionStatus.COMPLETED,
            completion_status=completion_status,
            change_classification=comparison.change_classification,
            confidence=confidence,
            explanation_summary=explanation.summary,
            provenance_channels=list(provenance.channels_used),
            grounding_reused=context.grounding_reused,
            navigation_reused=context.navigation_reused,
            comparison_ready=comparison.comparison_ready,
        )
        return VerificationOutcome(
            request=request,
            context=context,
            expectation=expectation,
            evidence=evidence,
            comparison=comparison,
            completion_status=completion_status,
            change_observations=change_observations,
            unresolved_conditions=unresolved_conditions,
            explanation=explanation,
            planner_result=planner_result,
            provenance=provenance,
            confidence=confidence,
        )

    def _numeric_verification_outcome(
        self,
        *,
        request: VerificationRequest,
        observation: ScreenObservation,
        calculation_activity,
    ) -> VerificationOutcome:
        trace = calculation_activity.calculation_trace if isinstance(calculation_activity.calculation_trace, dict) else {}
        result = calculation_activity.calculation_result if isinstance(calculation_activity.calculation_result, dict) else {}
        verification_match = trace.get("verification_match")
        claim_text = str(trace.get("verification_claim") or calculation_activity.claim_text or "").strip() or None
        evidence_channel = (
            GroundingEvidenceChannel.WORKSPACE_CONTEXT
            if calculation_activity.input_origin == "screen_visible_text"
            else GroundingEvidenceChannel.NATIVE_OBSERVATION
        )
        if calculation_activity.status == "resolved":
            completion_status = (
                CompletionStatus.COMPLETED
                if verification_match is True or claim_text is None
                else CompletionStatus.NOT_COMPLETED
            )
            summary = calculation_activity.summary or "Stormhelm verified the visible numbers through the deterministic calculation seam."
            comparison = VerificationComparison(
                basis="deterministic_numeric_verification",
                prior_state_available=False,
                comparison_ready=True,
                change_classification=ChangeClassification.VERIFIED_CHANGE,
                compared_signals=["visible_numeric_input"],
                summary=summary,
                basis_reason="screen_calculation_reuse",
            )
            explanation = VerificationExplanation(summary=summary, evidence_summary=[summary])
            planner_result = PlannerVerificationResult(
                request_type=request.request_type,
                resolved=True,
                completion_status=completion_status,
                change_classification=comparison.change_classification,
                confidence=calculation_activity.confidence,
                explanation_summary=summary,
                provenance_channels=[evidence_channel],
                grounding_reused=False,
                navigation_reused=False,
                comparison_ready=True,
            )
            return VerificationOutcome(
                request=request,
                context=VerificationContext(
                    current_summary="Deterministic numeric verification reused the current visible screen text.",
                    prior_resolution_available=False,
                    provenance_channels=[evidence_channel],
                ),
                evidence=[
                    VerificationEvidence(
                        signal="deterministic_numeric_calculation",
                        channel=evidence_channel,
                        score=calculation_activity.confidence.score,
                        note=calculation_activity.confidence.note,
                    )
                ],
                comparison=comparison,
                completion_status=completion_status,
                explanation=explanation,
                planner_result=planner_result,
                provenance=GroundingProvenance(
                    channels_used=[evidence_channel],
                    dominant_channel=evidence_channel,
                    signal_names=["deterministic_numeric_calculation"],
                ),
                confidence=calculation_activity.confidence,
                calculation_activity=calculation_activity,
            )

        summary = calculation_activity.summary or "Stormhelm could not isolate a trustworthy visible numeric expression."
        comparison = VerificationComparison(
            basis="deterministic_numeric_verification",
            prior_state_available=False,
            comparison_ready=False,
            change_classification=ChangeClassification.INSUFFICIENT_EVIDENCE,
            compared_signals=["visible_numeric_input"],
            summary=summary,
            basis_reason=calculation_activity.ambiguous_reason or "screen_calculation_ambiguous",
        )
        planner_result = PlannerVerificationResult(
            request_type=request.request_type,
            resolved=False,
            completion_status=CompletionStatus.AMBIGUOUS,
            change_classification=comparison.change_classification,
            confidence=calculation_activity.confidence,
            explanation_summary=summary,
            provenance_channels=[evidence_channel],
            grounding_reused=False,
            navigation_reused=False,
            comparison_ready=False,
        )
        return VerificationOutcome(
            request=request,
            context=VerificationContext(
                current_summary="Visible numeric verification stayed ambiguous because the extracted screen input was weak.",
                prior_resolution_available=False,
                provenance_channels=[evidence_channel],
            ),
            evidence=[
                VerificationEvidence(
                    signal="weak_visible_numeric_input",
                    channel=evidence_channel,
                    score=calculation_activity.confidence.score,
                    note=calculation_activity.confidence.note,
                    truth_state=ScreenTruthState.UNVERIFIED,
                )
            ],
            comparison=comparison,
            completion_status=CompletionStatus.AMBIGUOUS,
            explanation=VerificationExplanation(summary=summary, evidence_summary=[summary]),
            planner_result=planner_result,
            provenance=GroundingProvenance(
                channels_used=[evidence_channel],
                dominant_channel=evidence_channel,
                signal_names=["weak_visible_numeric_input"],
            ),
            confidence=calculation_activity.confidence,
            calculation_activity=calculation_activity,
        )

    def _select_prior_analysis(
        self,
        *,
        active_context: dict[str, Any] | None,
        request: VerificationRequest,
        grounding_result: GroundingOutcome | None,
    ) -> tuple[dict[str, Any], str | None, list[str], str | None, str | None, str]:
        last_reason = "no_prior_bearing"
        for resolution in _screen_resolutions(active_context):
            prior_analysis = _prior_analysis(resolution)
            if not prior_analysis:
                last_reason = "prior_bearing_too_thin"
                continue
            prior_page = _prior_page_label(prior_analysis)
            prior_errors = _prior_visible_errors(prior_analysis)
            prior_modal = _prior_modal_label(prior_analysis)
            expected_target = _expected_target_label(prior_analysis, grounding_result)
            age_seconds = _resolution_age_seconds(resolution)
            if (
                age_seconds is not None
                and age_seconds > _PRIOR_BEARING_STALE_SECONDS
                and not (prior_errors or prior_modal or expected_target)
            ):
                last_reason = "stale_prior_bearing"
                continue
            has_page_basis = bool(prior_page) and (
                request.request_type in {VerificationRequestType.CHANGE_CHECK, VerificationRequestType.PAGE_CHECK}
                or bool(expected_target)
            )
            if not any((prior_errors, prior_modal, has_page_basis)):
                last_reason = "prior_bearing_too_thin"
                continue
            return prior_analysis, prior_page, prior_errors, prior_modal, expected_target, ""
        return {}, None, [], None, None, last_reason

    def _expectation(
        self,
        *,
        request: VerificationRequest,
        expected_target: str | None,
        prior_errors: list[str],
    ) -> VerificationExpectation:
        if request.request_type == VerificationRequestType.PAGE_CHECK and expected_target:
            return VerificationExpectation(
                summary=f'The current page should align with "{expected_target}".',
                target_label=expected_target,
                derived_from="prior_navigation_context",
                expected_presence=[expected_target],
            )
        if request.request_type == VerificationRequestType.ERROR_CHECK and prior_errors:
            return VerificationExpectation(
                summary="The previously visible warning or error should no longer be present.",
                derived_from="prior_visible_error",
                expected_absence=prior_errors[:2],
            )
        if request.request_type == VerificationRequestType.CHANGE_CHECK:
            return VerificationExpectation(
                summary="A meaningful visible before-and-after change should be supported by comparison evidence.",
                derived_from="current_request",
            )
        return VerificationExpectation(
            summary="The current screen should show evidence that the expected result landed.",
            target_label=expected_target,
            derived_from="current_request",
        )

    def _comparison(
        self,
        *,
        request: VerificationRequest,
        prior_analysis: dict[str, Any],
        prior_basis_reason: str,
        prior_errors: list[str],
        current_errors: list[str],
        prior_modal: str | None,
        current_modal: str | None,
        prior_page: str | None,
        current_page: str | None,
        expected_target: str | None,
    ) -> tuple[VerificationComparison, list[ChangeObservation]]:
        if not prior_analysis:
            return (
                VerificationComparison(
                    basis="current_state_only",
                    prior_state_available=False,
                    comparison_ready=False,
                    change_classification=ChangeClassification.INSUFFICIENT_EVIDENCE,
                    compared_signals=["current_visible_state"],
                    summary=_comparison_reason_summary(prior_basis_reason),
                    basis_reason=prior_basis_reason or "no_prior_bearing",
                ),
                [],
            )

        observations: list[ChangeObservation] = []
        if prior_errors and not current_errors:
            observations.append(
                ChangeObservation(
                    change_type="warning_disappeared",
                    classification=ChangeClassification.VERIFIED_CHANGE,
                    summary=f'The previously visible warning "{prior_errors[0]}" disappeared and is no longer visible in the current bearing.',
                    evidence_summary=["The prior bearing included the warning and the current bearing does not."],
                    from_value=prior_errors[0],
                )
            )
        elif not prior_errors and current_errors:
            observations.append(
                ChangeObservation(
                    change_type="warning_appeared",
                    classification=ChangeClassification.VERIFIED_CHANGE,
                    summary=f'The warning "{current_errors[0]}" is visible now and was not present in the prior bearing.',
                    evidence_summary=["The current bearing includes a warning that was absent before."],
                    to_value=current_errors[0],
                )
            )
        elif prior_errors and current_errors and _normalize_text(prior_errors[0]) == _normalize_text(current_errors[0]):
            return (
                VerificationComparison(
                    basis="prior_screen_bearing",
                    prior_state_available=True,
                    comparison_ready=True,
                    change_classification=ChangeClassification.NO_VISIBLE_CHANGE,
                    compared_signals=["visible_errors"],
                    summary="The same visible warning remains present across the available before-and-after bearings.",
                    basis_reason="prior_screen_bearing",
                ),
                [],
            )

        if prior_modal and not current_modal:
            observations.append(
                ChangeObservation(
                    change_type="modal_disappeared",
                    classification=ChangeClassification.VERIFIED_CHANGE,
                    summary=f'The dialog "{prior_modal}" disappeared and is no longer visible in the current bearing.',
                    evidence_summary=["The prior bearing included a visible dialog or modal and the current bearing does not."],
                    from_value=prior_modal,
                )
            )
        elif not prior_modal and current_modal:
            observations.append(
                ChangeObservation(
                    change_type="modal_appeared",
                    classification=ChangeClassification.VERIFIED_CHANGE,
                    summary=f'The dialog "{current_modal}" is visible now and was not present in the prior bearing.',
                    evidence_summary=["The current bearing includes a visible dialog or modal that was absent before."],
                    to_value=current_modal,
                )
            )

        if prior_page and current_page and _normalize_text(prior_page) != _normalize_text(current_page):
            classification = ChangeClassification.VERIFIED_CHANGE
            if expected_target and _normalize_text(current_page) != _normalize_text(expected_target):
                classification = ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD
            observations.append(
                ChangeObservation(
                    change_type="page_label_changed",
                    classification=classification,
                    summary=f'The visible page label changed from "{prior_page}" to "{current_page}".',
                    evidence_summary=["The current page label differs from the prior screen bearing."],
                    from_value=prior_page,
                    to_value=current_page,
                )
            )

        if not observations:
            return (
                VerificationComparison(
                    basis="prior_screen_bearing",
                    prior_state_available=True,
                    comparison_ready=True,
                    change_classification=ChangeClassification.NO_VISIBLE_CHANGE,
                    compared_signals=["visible_errors", "modal_visibility", "page_label"],
                    summary="I do not see a meaningful visible difference between the available before-and-after bearings.",
                    basis_reason="prior_screen_bearing",
                ),
                [],
            )

        classification = ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD if any(
            item.classification == ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD for item in observations
        ) else ChangeClassification.VERIFIED_CHANGE
        summary = (
            "I can see that something changed between the prior and current screen bearings, but the meaning of that change is still unclear."
            if classification == ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD
            else "The current bearing shows a meaningful visible change relative to the prior screen state."
        )
        if (
            request.request_type == VerificationRequestType.CHANGE_CHECK
            and classification == ChangeClassification.VERIFIED_CHANGE
            and expected_target
            and current_page
            and _normalize_text(current_page) != _normalize_text(expected_target)
        ):
            classification = ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD
            summary = "I can see a visible change, but it does not clearly line up with the expected target or success state."
        return (
            VerificationComparison(
                basis="prior_screen_bearing",
                prior_state_available=True,
                comparison_ready=True,
                change_classification=classification,
                compared_signals=["visible_errors", "modal_visibility", "page_label"],
                summary=summary,
                basis_reason="prior_screen_bearing",
            ),
            observations,
        )

    def _unresolved_conditions(
        self,
        *,
        request: VerificationRequest,
        current_errors: list[str],
        disabled_control: str | None,
        current_page: str | None,
        expected_target: str | None,
        comparison: VerificationComparison,
    ) -> list[UnresolvedCondition]:
        conditions: list[UnresolvedCondition] = []
        if current_errors:
            conditions.append(
                UnresolvedCondition(
                    condition_type="visible_warning",
                    summary=f'The visible warning "{current_errors[0]}" is still present.',
                    evidence_summary=["The current screen still contains a visible warning or error."],
                )
            )
        if disabled_control:
            conditions.append(
                UnresolvedCondition(
                    condition_type="disabled_control",
                    summary=f'The control "{disabled_control}" is still disabled.',
                    evidence_summary=["A disabled control is still visible in the current workflow state."],
                )
            )
        if request.request_type == VerificationRequestType.PAGE_CHECK and expected_target and current_page and _normalize_text(current_page) != _normalize_text(expected_target):
            conditions.append(
                UnresolvedCondition(
                    condition_type="wrong_page",
                    summary=f'The current page looks like "{current_page}", not "{expected_target}".',
                    evidence_summary=["The current page label does not match the expected target label."],
                )
            )
        if comparison.change_classification == ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD:
            conditions.append(
                UnresolvedCondition(
                    condition_type="meaning_unclear",
                    summary="A visible change occurred, but its workflow meaning is still unclear.",
                    evidence_summary=["The before-and-after bearings differ, but they do not cleanly map to a known success or blocker removal."],
                    still_present=False,
                )
            )
        return conditions

    def _completion_status(
        self,
        *,
        request: VerificationRequest,
        comparison: VerificationComparison,
        unresolved_conditions: list[UnresolvedCondition],
        success_signal: str | None,
        current_errors: list[str],
        current_page: str | None,
        expected_target: str | None,
    ) -> CompletionStatus:
        if any(item.condition_type == "wrong_page" for item in unresolved_conditions):
            return CompletionStatus.DIVERTED
        if any(item.condition_type == "disabled_control" for item in unresolved_conditions):
            return CompletionStatus.BLOCKED
        if request.request_type == VerificationRequestType.PAGE_CHECK:
            if expected_target and current_page and _normalize_text(current_page) == _normalize_text(expected_target):
                return CompletionStatus.COMPLETED
            return CompletionStatus.AMBIGUOUS
        if request.request_type == VerificationRequestType.ERROR_CHECK:
            if current_errors:
                return CompletionStatus.NOT_COMPLETED
            if comparison.change_classification in {ChangeClassification.VERIFIED_CHANGE, ChangeClassification.LIKELY_CHANGE}:
                return CompletionStatus.COMPLETED
            return CompletionStatus.AMBIGUOUS
        if request.request_type == VerificationRequestType.CHANGE_CHECK:
            if comparison.change_classification == ChangeClassification.INSUFFICIENT_EVIDENCE:
                return CompletionStatus.AMBIGUOUS
            if comparison.change_classification == ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD:
                return CompletionStatus.AMBIGUOUS
            if comparison.change_classification == ChangeClassification.NO_VISIBLE_CHANGE:
                return CompletionStatus.NOT_COMPLETED
            if success_signal:
                return CompletionStatus.COMPLETED
            return CompletionStatus.AMBIGUOUS
        if current_errors:
            return CompletionStatus.NOT_COMPLETED
        if success_signal:
            return CompletionStatus.COMPLETED
        if comparison.change_classification == ChangeClassification.NO_VISIBLE_CHANGE and comparison.comparison_ready:
            return CompletionStatus.NOT_COMPLETED
        if comparison.change_classification == ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD:
            return CompletionStatus.AMBIGUOUS
        return CompletionStatus.AMBIGUOUS

    def _evidence(
        self,
        *,
        comparison: VerificationComparison,
        context: VerificationContext,
        success_signal: str | None,
        current_errors: list[str],
        disabled_control: str | None,
    ) -> list[VerificationEvidence]:
        evidence: list[VerificationEvidence] = []
        if success_signal:
            evidence.append(
                VerificationEvidence(
                    signal="success_signal",
                    channel=GroundingEvidenceChannel.WORKSPACE_CONTEXT,
                    score=0.36,
                    note="A direct success signal is visible in the current workspace state.",
                    truth_state=ScreenTruthState.OBSERVED,
                )
            )
        if current_errors:
            evidence.append(
                VerificationEvidence(
                    signal="visible_error",
                    channel=GroundingEvidenceChannel.NATIVE_OBSERVATION,
                    score=0.34,
                    note="The current screen still shows a visible warning or error.",
                    truth_state=ScreenTruthState.OBSERVED,
                )
            )
        if disabled_control:
            evidence.append(
                VerificationEvidence(
                    signal="disabled_control",
                    channel=GroundingEvidenceChannel.WORKSPACE_CONTEXT,
                    score=0.3,
                    note="A disabled control is still visible in the current screen state.",
                    truth_state=ScreenTruthState.OBSERVED,
                )
            )
        if comparison.comparison_ready:
            evidence.append(
                VerificationEvidence(
                    signal="comparison_ready",
                    channel=GroundingEvidenceChannel.WORKSPACE_CONTEXT if context.prior_resolution_available else GroundingEvidenceChannel.NATIVE_OBSERVATION,
                    score=0.28,
                    note="A prior screen bearing was available for before-and-after comparison.",
                    truth_state=ScreenTruthState.OBSERVED,
                )
            )
        return evidence

    def _provenance_channels(
        self,
        *,
        observation: ScreenObservation,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
    ) -> list[GroundingEvidenceChannel]:
        channels: list[GroundingEvidenceChannel] = []
        if observation.selected_text or observation.focus_metadata:
            channels.append(GroundingEvidenceChannel.NATIVE_OBSERVATION)
        if observation.workspace_snapshot.get("active_item") or observation.workspace_snapshot.get("opened_items"):
            if GroundingEvidenceChannel.WORKSPACE_CONTEXT not in channels:
                channels.append(GroundingEvidenceChannel.WORKSPACE_CONTEXT)
        if grounding_result is not None:
            for channel in grounding_result.provenance.channels_used:
                if channel not in channels:
                    channels.append(channel)
        if navigation_result is not None:
            for channel in navigation_result.provenance.channels_used:
                if channel not in channels:
                    channels.append(channel)
        if not channels:
            channels.append(GroundingEvidenceChannel.INTERPRETATION)
        return channels

    def _confidence(
        self,
        *,
        comparison: VerificationComparison,
        completion_status: CompletionStatus,
        success_signal: str | None,
        current_errors: list[str],
        expected_target: str | None,
        current_page: str | None,
    ) -> ScreenConfidence:
        score = 0.42
        if comparison.change_classification == ChangeClassification.INSUFFICIENT_EVIDENCE:
            score = 0.18
        elif completion_status == CompletionStatus.COMPLETED and success_signal:
            score = 0.82 if comparison.comparison_ready else 0.74
        elif completion_status in {CompletionStatus.NOT_COMPLETED, CompletionStatus.BLOCKED} and (current_errors or comparison.comparison_ready):
            score = 0.74
        elif completion_status == CompletionStatus.DIVERTED and expected_target and current_page:
            score = 0.72
        elif completion_status == CompletionStatus.AMBIGUOUS:
            score = 0.46 if comparison.comparison_ready else 0.28
        return _score_confidence(score, "Verification confidence reflects the current evidence quality and any explicit comparison basis.")

    def _explanation(
        self,
        *,
        request: VerificationRequest,
        comparison: VerificationComparison,
        completion_status: CompletionStatus,
        success_signal: str | None,
        current_errors: list[str],
        current_page: str | None,
        expected_target: str | None,
        change_observations: list[ChangeObservation],
    ) -> VerificationExplanation:
        evidence_summary = [item.summary for item in change_observations[:2]]
        if completion_status == CompletionStatus.COMPLETED and request.request_type == VerificationRequestType.PAGE_CHECK and expected_target:
            return VerificationExplanation(summary=f'The current page label matches "{expected_target}".', evidence_summary=evidence_summary)
        if completion_status == CompletionStatus.COMPLETED and success_signal:
            return VerificationExplanation(summary=f'The success signal "{success_signal}" is visible in the current screen state.', evidence_summary=evidence_summary)
        if current_errors:
            return VerificationExplanation(summary=f'The visible warning "{current_errors[0]}" is still present.', evidence_summary=evidence_summary, unresolved_summary=current_errors[0])
        if completion_status == CompletionStatus.DIVERTED and expected_target and current_page:
            return VerificationExplanation(summary=f'The current page looks like "{current_page}" rather than the expected "{expected_target}".', evidence_summary=evidence_summary, unresolved_summary="The current page does not align with the expected target.")
        if comparison.change_classification == ChangeClassification.INSUFFICIENT_EVIDENCE:
            return VerificationExplanation(summary="I only have the current bearing, not a prior screen state to compare against.", evidence_summary=evidence_summary)
        if comparison.change_classification == ChangeClassification.CHANGED_BUT_NOT_UNDERSTOOD:
            return VerificationExplanation(summary="The available before-and-after bearings show a visible change, but its meaning is still unclear.", evidence_summary=evidence_summary, unresolved_summary="A visible change occurred without a clean success or blocker-resolution interpretation.")
        if comparison.change_classification == ChangeClassification.NO_VISIBLE_CHANGE:
            return VerificationExplanation(summary="The available before-and-after bearings do not show a meaningful visible difference.", evidence_summary=evidence_summary)
        if change_observations:
            return VerificationExplanation(summary=change_observations[0].summary, evidence_summary=evidence_summary)
        return VerificationExplanation(summary="The current verification bearing is only partially grounded.", evidence_summary=evidence_summary)
