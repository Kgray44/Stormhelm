from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from stormhelm.core.screen_awareness.models import ActionExecutionResult
from stormhelm.core.screen_awareness.models import CurrentScreenContext
from stormhelm.core.screen_awareness.models import GroundingEvidenceChannel
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import GroundingProvenance
from stormhelm.core.screen_awareness.models import NavigationOutcome
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenInterpretation
from stormhelm.core.screen_awareness.models import ScreenObservation
from stormhelm.core.screen_awareness.models import VerificationOutcome
from stormhelm.core.screen_awareness.models import WorkflowContinuityContext
from stormhelm.core.screen_awareness.models import WorkflowContinuityRequest
from stormhelm.core.screen_awareness.models import WorkflowContinuityRequestType
from stormhelm.core.screen_awareness.models import WorkflowContinuityResult
from stormhelm.core.screen_awareness.models import WorkflowContinuityStatus
from stormhelm.core.screen_awareness.models import WorkflowDetourState
from stormhelm.core.screen_awareness.models import WorkflowRecoveryHint
from stormhelm.core.screen_awareness.models import WorkflowResumeCandidate
from stormhelm.core.screen_awareness.models import WorkflowStepState
from stormhelm.core.screen_awareness.models import WorkflowTimelineEvent
from stormhelm.core.screen_awareness.models import PlannerContinuityResult
from stormhelm.core.screen_awareness.models import confidence_level_for_score


_CONTINUITY_HINTS = (
    "continue where we left off",
    "what was i doing here",
    "what was i just doing",
    "this popup interrupted me",
    "what step was next",
    "i think i went backward",
    "where was i supposed to be",
    "how do i recover from this",
    "help me resume this workflow",
    "how do i get back to the thing i was just doing",
)
_RESUME_HINTS = ("continue where we left off", "resume this workflow", "what step was next")
_STATUS_HINTS = ("what was i doing here", "what was i just doing")
_DETOUR_HINTS = ("popup interrupted", "interrupted me", "get back to the thing i was just doing")
_BACKTRACK_HINTS = ("went backward", "where was i supposed to be", "get back")
_UNDO_HINTS = ("undo that", "go back", "back out")
_BROWSER_SUFFIX = re.compile(r"\s*-\s*(google chrome|microsoft edge|firefox|brave)\s*$", flags=re.IGNORECASE)
_MODAL_KINDS = {"dialog", "modal", "popup", "prompt", "sheet", "overlay"}
_STALE_SECONDS = 20 * 60


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _score_confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


def _workspace_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    active_item = snapshot.get("active_item")
    if isinstance(active_item, dict):
        items.append(active_item)
    items.extend(item for item in snapshot.get("opened_items") or [] if isinstance(item, dict))
    return items


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


def _current_modal_label(observation: ScreenObservation) -> str | None:
    for item in _workspace_items(observation.workspace_snapshot):
        kind = str(item.get("kind") or item.get("viewer") or "").strip().lower()
        label = str(item.get("title") or item.get("name") or "").strip()
        if kind in _MODAL_KINDS:
            return label or kind
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


def _analysis_payload(resolution: dict[str, Any]) -> dict[str, Any]:
    analysis = resolution.get("analysis_result")
    return dict(analysis) if isinstance(analysis, dict) else {}


def _resolution_age_seconds(resolution: dict[str, Any]) -> float | None:
    captured_at = resolution.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at.strip():
        return None
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - captured.astimezone(timezone.utc)).total_seconds())


def _summary_from_analysis(analysis: dict[str, Any], fallback: str = "") -> str:
    context = analysis.get("current_screen_context")
    if isinstance(context, dict):
        summary = str(context.get("summary") or "").strip()
        if summary:
            return summary
    return fallback


def _page_from_analysis(analysis: dict[str, Any]) -> str | None:
    context = analysis.get("current_screen_context")
    if isinstance(context, dict):
        summary = str(context.get("summary") or "").strip()
        match = re.search(r"focused on ([^.]+)", summary, flags=re.IGNORECASE)
        if match:
            return str(match.group(1)).strip().strip('"')
    observation = analysis.get("observation")
    if isinstance(observation, dict):
        focus = observation.get("focus_metadata")
        if isinstance(focus, dict):
            title = str(focus.get("window_title") or "").strip()
            if title:
                cleaned = _BROWSER_SUFFIX.sub("", title).strip()
                return cleaned or title
    return None


def _modal_from_analysis(analysis: dict[str, Any]) -> str | None:
    observation = analysis.get("observation")
    if not isinstance(observation, dict):
        return None
    snapshot = observation.get("workspace_snapshot")
    if not isinstance(snapshot, dict):
        return None
    for item in _workspace_items(snapshot):
        kind = str(item.get("kind") or item.get("viewer") or "").strip().lower()
        label = str(item.get("title") or item.get("name") or "").strip()
        if kind in _MODAL_KINDS:
            return label or kind
    return None


def _target_from_analysis(analysis: dict[str, Any]) -> tuple[str | None, str | None, str]:
    navigation = analysis.get("navigation_result")
    if isinstance(navigation, dict):
        winning_candidate = navigation.get("winning_candidate")
        winning_label = ""
        winning_candidate_id: str | None = None
        if isinstance(winning_candidate, dict):
            winning_label = str(winning_candidate.get("label") or "").strip()
            winning_candidate_id = str(winning_candidate.get("candidate_id") or "").strip() or None
        step_state = navigation.get("step_state")
        if isinstance(step_state, dict):
            label = str(step_state.get("expected_target_label") or "").strip()
            if label:
                return label, winning_candidate_id, "navigation"
        if winning_label:
            return winning_label, winning_candidate_id, "navigation"
    action = analysis.get("action_result")
    if isinstance(action, dict):
        plan = action.get("plan")
        if isinstance(plan, dict):
            target = plan.get("target")
            if isinstance(target, dict):
                label = str(target.get("label") or "").strip()
                candidate_id = str(target.get("candidate_id") or "").strip() or None
                if label:
                    return label, candidate_id, "action"
    grounding = analysis.get("grounding_result")
    if isinstance(grounding, dict):
        target = grounding.get("winning_target")
        if isinstance(target, dict):
            label = str(target.get("label") or "").strip()
            candidate_id = str(target.get("candidate_id") or "").strip() or None
            if label:
                return label, candidate_id, "grounding"
    return None, None, ""


def _completion_from_analysis(analysis: dict[str, Any]) -> str | None:
    verification = analysis.get("verification_result")
    if isinstance(verification, dict):
        completion = str(verification.get("completion_status") or "").strip()
        if completion:
            return completion
    action = analysis.get("action_result")
    if isinstance(action, dict):
        status = str(action.get("status") or "").strip()
        if status:
            return status
    return None


def _confidence_from_analysis(analysis: dict[str, Any]) -> float:
    for key in ("continuity_result", "action_result", "verification_result", "navigation_result", "grounding_result"):
        payload = analysis.get(key)
        if not isinstance(payload, dict):
            continue
        confidence = payload.get("confidence")
        if isinstance(confidence, dict):
            score = confidence.get("score")
            if isinstance(score, (int, float)):
                return float(score)
    return 0.0


def _provenance_from_analysis(analysis: dict[str, Any]) -> list[GroundingEvidenceChannel]:
    for key in ("continuity_result", "action_result", "verification_result", "navigation_result", "grounding_result"):
        payload = analysis.get(key)
        if not isinstance(payload, dict):
            continue
        provenance = payload.get("provenance")
        if not isinstance(provenance, dict):
            continue
        channels = provenance.get("channels_used")
        if not isinstance(channels, list):
            continue
        parsed: list[GroundingEvidenceChannel] = []
        for channel in channels:
            try:
                parsed.append(GroundingEvidenceChannel(str(channel)))
            except ValueError:
                continue
        if parsed:
            return parsed
    return []


def _reused_layers(analysis: dict[str, Any]) -> tuple[bool, bool, bool, bool]:
    return (
        isinstance(analysis.get("grounding_result"), dict),
        isinstance(analysis.get("navigation_result"), dict),
        isinstance(analysis.get("verification_result"), dict),
        isinstance(analysis.get("action_result"), dict),
    )


@dataclass(slots=True)
class DeterministicContinuityEngine:
    def should_assess(self, *, operator_text: str, intent: ScreenIntentType) -> bool:
        lowered = _normalize_text(operator_text)
        return intent == ScreenIntentType.CONTINUE_WORKFLOW or any(phrase in lowered for phrase in _CONTINUITY_HINTS)

    def build_request(self, *, operator_text: str) -> WorkflowContinuityRequest:
        lowered = _normalize_text(operator_text)
        request_type = WorkflowContinuityRequestType.RESUME
        if any(phrase in lowered for phrase in _STATUS_HINTS):
            request_type = WorkflowContinuityRequestType.FLOW_STATUS
        elif any(phrase in lowered for phrase in _DETOUR_HINTS):
            request_type = WorkflowContinuityRequestType.DETOUR_RECOVERY
        elif any(phrase in lowered for phrase in _BACKTRACK_HINTS):
            request_type = WorkflowContinuityRequestType.BACKTRACK_CHECK
        elif any(phrase in lowered for phrase in _UNDO_HINTS):
            request_type = WorkflowContinuityRequestType.UNDO_HINT
        elif "recover" in lowered:
            request_type = WorkflowContinuityRequestType.RECOVERY
        return WorkflowContinuityRequest(
            utterance=operator_text,
            request_type=request_type,
            wants_resume=request_type in {WorkflowContinuityRequestType.RESUME, WorkflowContinuityRequestType.FLOW_STATUS},
            wants_recovery=request_type in {
                WorkflowContinuityRequestType.DETOUR_RECOVERY,
                WorkflowContinuityRequestType.RECOVERY,
                WorkflowContinuityRequestType.BACKTRACK_CHECK,
                WorkflowContinuityRequestType.UNDO_HINT,
            },
            wants_detour_help=request_type == WorkflowContinuityRequestType.DETOUR_RECOVERY,
            wants_backtrack_check=request_type == WorkflowContinuityRequestType.BACKTRACK_CHECK,
            wants_undo_hint=request_type == WorkflowContinuityRequestType.UNDO_HINT,
            mode_flags=[flag for flag, present in {"deictic": any(token in lowered.split() for token in {"this", "that", "here"})}.items() if present],
        )

    def assess(
        self,
        *,
        operator_text: str,
        intent: ScreenIntentType,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        verification_result: VerificationOutcome | None,
        action_result: ActionExecutionResult | None,
        active_context: dict[str, Any] | None,
    ) -> WorkflowContinuityResult | None:
        if not self.should_assess(operator_text=operator_text, intent=intent):
            return None

        request = self.build_request(operator_text=operator_text)
        current_page = _current_page_label(observation)
        current_modal = _current_modal_label(observation)
        timeline_events = self._timeline_events(active_context=active_context)
        resolution_analyses = [_analysis_payload(resolution) for resolution in _screen_resolutions(active_context)]
        grounding_reused = any(_reused_layers(analysis)[0] for analysis in resolution_analyses)
        navigation_reused = any(_reused_layers(analysis)[1] for analysis in resolution_analyses)
        verification_reused = any(_reused_layers(analysis)[2] for analysis in resolution_analyses)
        action_reused = any(_reused_layers(analysis)[3] for analysis in resolution_analyses)
        provenance_channels = list(
            dict.fromkeys(
                channel
                for event in timeline_events
                for channel in event.provenance_channels
            )
        )
        if not provenance_channels:
            provenance_channels = list(
                dict.fromkeys(
                    channel
                    for channel in (
                        grounding_result.provenance.channels_used if grounding_result is not None else []
                    )
                )
            )

        context = WorkflowContinuityContext(
            current_summary=current_context.summary or "",
            current_page_label=current_page,
            current_modal_label=current_modal,
            recent_event_count=len(timeline_events),
            recent_screen_available=bool(timeline_events),
            grounding_reused=grounding_reused,
            navigation_reused=navigation_reused,
            verification_reused=verification_reused,
            action_reused=action_reused,
            provenance_channels=provenance_channels,
        )

        active_step = self._active_step(timeline_events)
        resume_options = self._resume_candidates(timeline_events=timeline_events, current_page=current_page)
        detour_state = self._detour_state(
            current_modal=current_modal,
            active_step=active_step,
            timeline_events=timeline_events,
        )
        blocker_visible = bool(interpretation.blockers or current_context.blockers_or_prompts)
        best_candidate = resume_options[0] if resume_options else None

        status = WorkflowContinuityStatus.WEAK_BASIS
        recovery_hint: WorkflowRecoveryHint | None = None
        clarification_needed = False
        clarification_prompt: str | None = None
        explanation_summary = "I do not have enough recent workflow evidence to justify a resume point."

        if blocker_visible and request.wants_recovery and current_modal is None:
            status = WorkflowContinuityStatus.BLOCKED
            explanation_summary = "A visible blocker is still present, so the workflow does not yet look ready to resume."
            recovery_hint = WorkflowRecoveryHint(
                summary="The visible blocker may need attention before the workflow can continue.",
                reason="visible_blocker_present",
                target_label=None,
                confidence=_score_confidence(0.68, "A current blocker cue is visible."),
            )
        elif (
            request.wants_backtrack_check or request.wants_undo_hint
        ) and active_step is not None and active_step.page_label and current_page and active_step.page_label.lower() != current_page.lower():
            status = WorkflowContinuityStatus.RECOVERY_READY
            target_label = best_candidate.label if best_candidate is not None else active_step.expected_target_label or active_step.page_label
            recovery_hint = WorkflowRecoveryHint(
                summary=(
                    f'You may have drifted back to "{current_page}". '
                    f'Look for "{target_label}" to rejoin the earlier step.'
                ),
                reason="backtracked_from_recent_step",
                target_label=target_label,
                bounded_undo_hint=request.wants_undo_hint or request.wants_backtrack_check,
                confidence=_score_confidence(0.74, "The current page differs from the most recent non-stale workflow page."),
            )
            explanation_summary = "The current page no longer matches the most recent workflow bearing, so a short recovery step is more justified than a fresh guess."
        elif detour_state is not None and detour_state.active:
            status = WorkflowContinuityStatus.RECOVERY_READY
            target_label = best_candidate.label if best_candidate is not None else active_step.expected_target_label if active_step is not None else None
            recovery_hint = WorkflowRecoveryHint(
                summary=(
                    f'Resolve "{detour_state.current_label}" first, then return to {target_label}.'
                    if target_label
                    else f'Resolve "{detour_state.current_label}" first, then return to the previous task.'
                ),
                reason="popup_detour",
                target_label=target_label,
                confidence=_score_confidence(0.8, "A modal detour is visible on top of the recent task flow."),
            )
            explanation_summary = "A popup or dialog is visible on top of the recent workflow, so the flow looks temporarily detoured."
        elif len(resume_options) >= 2 and abs(resume_options[0].score - resume_options[1].score) < 0.12:
            status = WorkflowContinuityStatus.AMBIGUOUS
            clarification_needed = True
            clarification_prompt = "I see multiple plausible places to resume. Tell me which visible step you want to pick back up."
            explanation_summary = "Multiple recent workflow branches remain plausible, so I cannot justify a single resume point."
        elif best_candidate is not None and best_candidate.score >= 0.58:
            status = WorkflowContinuityStatus.RESUME_READY
            explanation_summary = f'The strongest recent workflow bearing still points to "{best_candidate.label}" as the next place to resume.'
        elif timeline_events:
            status = WorkflowContinuityStatus.WEAK_BASIS
            clarification_needed = True
            clarification_prompt = "I need a fresher visible anchor before I can place the workflow accurately."
            explanation_summary = "I have some recent workflow traces, but they are too stale or weak to support a precise resume claim."
        else:
            clarification_needed = True
            clarification_prompt = "I need a recent visible workflow bearing before I can help resume this task."

        confidence_score = best_candidate.score if best_candidate is not None else (0.74 if status == WorkflowContinuityStatus.RECOVERY_READY else 0.24 if timeline_events else 0.0)
        confidence = _score_confidence(confidence_score, "Workflow continuity confidence reflects the freshness and specificity of the recent screen-bearing timeline.")
        provenance = GroundingProvenance(
            channels_used=provenance_channels,
            dominant_channel=provenance_channels[0] if provenance_channels else None,
            signal_names=[event.event_type for event in timeline_events[:4]],
        )
        planner_result = PlannerContinuityResult(
            request_type=request.request_type,
            resolved=status in {WorkflowContinuityStatus.RESUME_READY, WorkflowContinuityStatus.RECOVERY_READY},
            status=status,
            resume_candidate_id=best_candidate.candidate_id if best_candidate is not None else None,
            alternative_resume_candidate_ids=[
                candidate.candidate_id
                for candidate in resume_options[1:3]
                if candidate.candidate_id is not None
            ],
            confidence=confidence,
            explanation_summary=explanation_summary,
            provenance_channels=list(provenance.channels_used),
            detour_active=detour_state.active if detour_state is not None else False,
            blocked=status == WorkflowContinuityStatus.BLOCKED,
            clarification_needed=clarification_needed,
        )
        return WorkflowContinuityResult(
            request=request,
            context=context,
            status=status,
            active_step=active_step,
            detour_state=detour_state,
            recovery_hint=recovery_hint,
            resume_candidate=best_candidate if status == WorkflowContinuityStatus.RESUME_READY else None,
            resume_options=resume_options[:4],
            timeline_events=timeline_events[:6],
            clarification_needed=clarification_needed,
            clarification_prompt=clarification_prompt,
            explanation_summary=explanation_summary,
            planner_result=planner_result,
            provenance=provenance,
            confidence=confidence,
        )

    def _timeline_events(self, *, active_context: dict[str, Any] | None) -> list[WorkflowTimelineEvent]:
        events: list[WorkflowTimelineEvent] = []
        for resolution in _screen_resolutions(active_context):
            analysis = _analysis_payload(resolution)
            age_seconds = _resolution_age_seconds(resolution)
            stale = age_seconds is not None and age_seconds > _STALE_SECONDS
            summary = _summary_from_analysis(analysis, fallback=str(resolution.get("query") or "").strip())
            page_label = _page_from_analysis(analysis)
            target_label, target_candidate_id, source_layer = _target_from_analysis(analysis)
            completion_status = _completion_from_analysis(analysis)
            confidence_score = _confidence_from_analysis(analysis)
            channels = _provenance_from_analysis(analysis)
            grounding_reused, navigation_reused, verification_reused, action_reused = _reused_layers(analysis)
            layer_name = (
                "action"
                if action_reused and source_layer == "action"
                else "verification"
                if verification_reused and completion_status is not None
                else "navigation"
                if navigation_reused
                else "grounding"
                if grounding_reused
                else "screen"
            )
            events.append(
                WorkflowTimelineEvent(
                    event_id=f"workflow-event-{uuid4().hex}",
                    event_type=f"{layer_name}_bearing",
                    source_intent=str(resolution.get("intent") or "").strip(),
                    summary=summary,
                    captured_at=str(resolution.get("captured_at") or ""),
                    page_label=page_label,
                    target_label=target_label,
                    target_candidate_id=target_candidate_id,
                    completion_status=completion_status,
                    confidence_score=confidence_score,
                    stale=stale,
                    provenance_channels=channels,
                )
            )
        return events

    def _active_step(self, timeline_events: list[WorkflowTimelineEvent]) -> WorkflowStepState | None:
        if not timeline_events:
            return None
        event = timeline_events[0]
        return WorkflowStepState(
            summary=event.summary,
            expected_target_label=event.target_label,
            page_label=event.page_label,
            source_intent=event.source_intent,
            completion_status=event.completion_status,
            verified=str(event.completion_status or "").strip().lower() in {"completed", "verified_success"},
        )

    def _resume_candidates(
        self,
        *,
        timeline_events: list[WorkflowTimelineEvent],
        current_page: str | None,
    ) -> list[WorkflowResumeCandidate]:
        ranked: list[WorkflowResumeCandidate] = []
        seen_labels: set[str] = set()
        for event in timeline_events:
            if event.stale or not event.target_label:
                continue
            label_key = event.target_label.lower()
            if label_key in seen_labels:
                continue
            score = max(0.0, min(event.confidence_score + (0.12 if current_page and event.page_label and event.page_label.lower() == current_page.lower() else 0.0) + (0.08 if "navigation" in event.event_type else 0.04), 1.0))
            ranked.append(
                WorkflowResumeCandidate(
                    candidate_id=event.target_candidate_id,
                    label=event.target_label,
                    source_layer=event.event_type.replace("_bearing", ""),
                    summary=event.summary,
                    score=score,
                    evidence_summary=[
                        f"Recent {event.event_type.replace('_bearing', '')} bearing referenced this target.",
                        f"Page: {event.page_label}." if event.page_label else "Page label was partial.",
                    ],
                    from_event_id=event.event_id,
                )
            )
            seen_labels.add(label_key)
        ranked.sort(key=lambda candidate: candidate.score, reverse=True)
        return ranked

    def _detour_state(
        self,
        *,
        current_modal: str | None,
        active_step: WorkflowStepState | None,
        timeline_events: list[WorkflowTimelineEvent],
    ) -> WorkflowDetourState | None:
        if not current_modal:
            return None
        prior_non_modal = next((event for event in timeline_events if not event.stale and event.target_label), None)
        if prior_non_modal is None:
            return WorkflowDetourState(
                active=True,
                detour_type="popup_detour",
                summary="A popup or dialog is visible, but the interrupted task basis is still weak.",
                current_label=current_modal,
                prior_task_summary=active_step.summary if active_step is not None else None,
                confidence=_score_confidence(0.54, "A modal is visible, but the prior workflow anchor is weak."),
            )
        return WorkflowDetourState(
            active=True,
            detour_type="popup_detour",
            summary="A popup or dialog is visible on top of the recent workflow.",
            current_label=current_modal,
            prior_task_summary=prior_non_modal.summary,
            confidence=_score_confidence(0.8, "A visible modal interrupts the most recent non-stale workflow bearing."),
        )
