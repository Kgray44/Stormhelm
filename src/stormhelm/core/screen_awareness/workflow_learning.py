from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.screen_awareness.action import ActionExecutionEnvelope
from stormhelm.core.screen_awareness.action import DeterministicActionEngine
from stormhelm.core.screen_awareness.models import ActionExecutionResult
from stormhelm.core.screen_awareness.models import ActionExecutionStatus
from stormhelm.core.screen_awareness.models import ActionIntent
from stormhelm.core.screen_awareness.models import AppAdapterResolution
from stormhelm.core.screen_awareness.models import CurrentScreenContext
from stormhelm.core.screen_awareness.models import GroundingEvidenceChannel
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import GroundingProvenance
from stormhelm.core.screen_awareness.models import NavigationOutcome
from stormhelm.core.screen_awareness.models import PlannerWorkflowReuseResult
from stormhelm.core.screen_awareness.models import ReusableWorkflow
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenInterpretation
from stormhelm.core.screen_awareness.models import ScreenObservation
from stormhelm.core.screen_awareness.models import VerificationOutcome
from stormhelm.core.screen_awareness.models import WorkflowCandidate
from stormhelm.core.screen_awareness.models import WorkflowLabel
from stormhelm.core.screen_awareness.models import WorkflowLearningRequestType
from stormhelm.core.screen_awareness.models import WorkflowLearningResult
from stormhelm.core.screen_awareness.models import WorkflowLearningStatus
from stormhelm.core.screen_awareness.models import WorkflowMatchResult
from stormhelm.core.screen_awareness.models import WorkflowMatchStatus
from stormhelm.core.screen_awareness.models import WorkflowObservationSession
from stormhelm.core.screen_awareness.models import WorkflowReusePlan
from stormhelm.core.screen_awareness.models import WorkflowReuseSafetyState
from stormhelm.core.screen_awareness.models import WorkflowStepEvent
from stormhelm.core.screen_awareness.models import WorkflowStepSequence
from stormhelm.core.screen_awareness.models import confidence_level_for_score


_BROWSER_SUFFIX = re.compile(r"\s*-\s*(google chrome|microsoft edge|firefox|brave)\s*$", flags=re.IGNORECASE)
_START_HINTS = (
    "watch me do this and remember the workflow",
    "watch me do this",
    "remember the workflow",
)
_SAVE_HINTS = ("save this process", "save this workflow", "remember this process", "save this flow")
_MATCH_HINTS = (
    "does this match the workflow from before",
    "this looks like the same thing as last time",
    "recognize this workflow",
    "does this match",
)
_REUSE_HINTS = (
    "can you do that same workflow again",
    "do that same workflow again",
    "reuse the steps from that prior task",
    "reuse the steps",
    "reuse the workflow",
    "apply the same flow here",
    "apply the same flow",
    "run it again",
    "do that same thing again",
)


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _score_confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


def _parse_timestamp(raw_value: str | None) -> datetime | None:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _analysis_payload(resolution: dict[str, Any]) -> dict[str, Any]:
    analysis = resolution.get("analysis_result")
    return dict(analysis) if isinstance(analysis, dict) else {}


def _provenance_channels(payload: dict[str, Any]) -> list[GroundingEvidenceChannel]:
    for key in ("action_result", "verification_result", "navigation_result", "grounding_result", "continuity_result", "problem_solving_result"):
        section = payload.get(key)
        if not isinstance(section, dict):
            continue
        provenance = section.get("provenance")
        if not isinstance(provenance, dict):
            continue
        raw_channels = provenance.get("channels_used")
        if not isinstance(raw_channels, list):
            continue
        channels: list[GroundingEvidenceChannel] = []
        for raw_channel in raw_channels:
            try:
                channel = GroundingEvidenceChannel(str(raw_channel))
            except ValueError:
                continue
            if channel not in channels:
                channels.append(channel)
        if channels:
            return channels
    return []


def _page_from_analysis(payload: dict[str, Any]) -> str | None:
    context = payload.get("current_screen_context")
    if isinstance(context, dict):
        summary = str(context.get("summary") or "").strip()
        match = re.search(r"focused on ([^.]+)", summary, flags=re.IGNORECASE)
        if match:
            return str(match.group(1)).strip().strip('"')
    observation = payload.get("observation")
    if isinstance(observation, dict):
        focus = observation.get("focus_metadata")
        if isinstance(focus, dict):
            title = str(focus.get("window_title") or "").strip()
            if title:
                cleaned = _BROWSER_SUFFIX.sub("", title).strip()
                return cleaned or title
    return None


def _summary_from_analysis(payload: dict[str, Any], fallback: str = "") -> str:
    action = payload.get("action_result")
    if isinstance(action, dict):
        summary = str(action.get("explanation_summary") or "").strip()
        if summary:
            return summary
    verification = payload.get("verification_result")
    if isinstance(verification, dict):
        explanation = verification.get("explanation")
        if isinstance(explanation, dict):
            summary = str(explanation.get("summary") or "").strip()
            if summary:
                return summary
    navigation = payload.get("navigation_result")
    if isinstance(navigation, dict):
        guidance = navigation.get("guidance")
        if isinstance(guidance, dict):
            summary = str(guidance.get("reasoning_summary") or "").strip()
            if summary:
                return summary
    grounding = payload.get("grounding_result")
    if isinstance(grounding, dict):
        explanation = grounding.get("explanation")
        if isinstance(explanation, dict):
            summary = str(explanation.get("summary") or "").strip()
            if summary:
                return summary
    context = payload.get("current_screen_context")
    if isinstance(context, dict):
        summary = str(context.get("summary") or "").strip()
        if summary:
            return summary
    return fallback


def _target_from_analysis(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    action = payload.get("action_result")
    if isinstance(action, dict):
        plan = action.get("plan")
        if isinstance(plan, dict):
            target = plan.get("target")
            if isinstance(target, dict):
                label = str(target.get("label") or "").strip()
                candidate_id = str(target.get("candidate_id") or "").strip() or None
                if label:
                    return label, candidate_id
    navigation = payload.get("navigation_result")
    if isinstance(navigation, dict):
        step_state = navigation.get("step_state")
        if isinstance(step_state, dict):
            label = str(step_state.get("expected_target_label") or "").strip()
            if label:
                candidate = navigation.get("winning_candidate")
                candidate_id = str(candidate.get("candidate_id") or "").strip() if isinstance(candidate, dict) else ""
                return label, candidate_id or None
        candidate = navigation.get("winning_candidate")
        if isinstance(candidate, dict):
            label = str(candidate.get("label") or "").strip()
            candidate_id = str(candidate.get("candidate_id") or "").strip() or None
            if label:
                return label, candidate_id
    grounding = payload.get("grounding_result")
    if isinstance(grounding, dict):
        target = grounding.get("winning_target")
        if isinstance(target, dict):
            label = str(target.get("label") or "").strip()
            candidate_id = str(target.get("candidate_id") or "").strip() or None
            if label:
                return label, candidate_id
    return None, None


def _action_intent_from_analysis(payload: dict[str, Any]) -> ActionIntent | None:
    action = payload.get("action_result")
    if not isinstance(action, dict):
        return None
    plan = action.get("plan")
    if not isinstance(plan, dict):
        return None
    raw_intent = str(plan.get("action_intent") or "").strip()
    if not raw_intent:
        request = action.get("request")
        raw_intent = str(request.get("intent") or "").strip() if isinstance(request, dict) else ""
    if not raw_intent:
        return None
    try:
        return ActionIntent(raw_intent)
    except ValueError:
        return None


def _completion_from_analysis(payload: dict[str, Any]) -> str | None:
    verification = payload.get("verification_result")
    if isinstance(verification, dict):
        completion = str(verification.get("completion_status") or "").strip()
        if completion:
            return completion
    action = payload.get("action_result")
    if isinstance(action, dict):
        status = str(action.get("status") or "").strip()
        if status:
            return status
    return None


def _confidence_score(payload: dict[str, Any]) -> float:
    for key in ("action_result", "verification_result", "navigation_result", "grounding_result", "continuity_result", "problem_solving_result"):
        section = payload.get(key)
        if not isinstance(section, dict):
            continue
        confidence = section.get("confidence")
        if not isinstance(confidence, dict):
            continue
        score = confidence.get("score")
        if isinstance(score, (int, float)):
            return float(score)
    return 0.0


def _sensitive_from_analysis(payload: dict[str, Any]) -> bool:
    action = payload.get("action_result")
    if isinstance(action, dict):
        plan = action.get("plan")
        if isinstance(plan, dict) and bool(plan.get("text_payload_redacted")):
            return True
    observation = payload.get("observation")
    if isinstance(observation, dict):
        sensitivity = str(observation.get("sensitivity") or "").strip().lower()
        if sensitivity in {"sensitive", "restricted"}:
            return True
    return False


def _event_from_resolution(resolution: dict[str, Any]) -> WorkflowStepEvent | None:
    payload = _analysis_payload(resolution)
    summary = _summary_from_analysis(payload, fallback=str(resolution.get("query") or "").strip())
    target_label, target_candidate_id = _target_from_analysis(payload)
    action_intent = _action_intent_from_analysis(payload)
    completion_status = _completion_from_analysis(payload)
    if not any((summary, target_label, action_intent is not None, completion_status)):
        return None
    return WorkflowStepEvent(
        event_id=f"workflow-step-{uuid4().hex}",
        source_intent=str(resolution.get("intent") or "").strip(),
        summary=summary or "Recent screen-awareness bearing.",
        captured_at=str(resolution.get("captured_at") or ""),
        page_label=_page_from_analysis(payload),
        target_label=target_label,
        target_candidate_id=target_candidate_id,
        action_intent=action_intent,
        completion_status=completion_status,
        confidence_score=_confidence_score(payload),
        provenance_channels=_provenance_channels(payload),
        sensitive=_sensitive_from_analysis(payload),
    )


def _sequence_from_resolutions(resolutions: list[dict[str, Any]]) -> WorkflowStepSequence:
    steps: list[WorkflowStepEvent] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for resolution in resolutions:
        event = _event_from_resolution(resolution)
        if event is None:
            continue
        dedupe_key = (
            event.source_intent,
            _normalize_text(event.target_label),
            event.action_intent.value if event.action_intent is not None else "",
            _normalize_text(event.summary),
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        steps.append(event)
    stable_signals = list(
        dict.fromkeys(
            signal
            for event in steps
            for signal in (event.page_label, event.target_label)
            if signal
        )
    )
    variable_signals = list(
        dict.fromkeys(
            event.action_intent.value
            for event in steps
            if event.action_intent in {ActionIntent.TYPE_TEXT, ActionIntent.HOTKEY}
        )
    )
    sensitive_signals = list(
        dict.fromkeys(
            signal
            for event in steps
            for signal in (event.target_label, event.summary)
            if event.sensitive and signal
        )
    )
    summary = " -> ".join(event.target_label for event in steps if event.target_label) or (steps[0].summary if steps else "")
    return WorkflowStepSequence(
        steps=steps,
        summary=summary,
        stable_signals=stable_signals,
        variable_signals=variable_signals,
        sensitive_signals=sensitive_signals,
    )


def _label_from_sequence(sequence: WorkflowStepSequence, *, label_hint: str | None) -> WorkflowLabel:
    primary = str(label_hint or "").strip()
    if primary:
        return WorkflowLabel(primary_label=primary)
    if sequence.stable_signals:
        return WorkflowLabel(primary_label=f"{sequence.stable_signals[0]} workflow")
    if sequence.summary:
        return WorkflowLabel(primary_label=sequence.summary)
    return WorkflowLabel(primary_label="Screen workflow")


def _candidate_from_resolutions(
    resolutions: list[dict[str, Any]],
    *,
    label_hint: str | None,
) -> WorkflowCandidate | None:
    sequence = _sequence_from_resolutions(resolutions)
    if not sequence.steps:
        return None
    allowed_modes = ["guide", "suggest_action"]
    if not sequence.sensitive_signals and not sequence.variable_signals:
        allowed_modes.append("execute")
    confidence_score = min(0.9, 0.46 + 0.14 * min(len(sequence.steps), 3))
    label = _label_from_sequence(sequence, label_hint=label_hint)
    return WorkflowCandidate(
        candidate_id=f"workflow-candidate-{uuid4().hex}",
        label=label,
        step_sequence=sequence,
        summary=sequence.summary or f"Reusable workflow for {label.primary_label}.",
        confidence=_score_confidence(
            confidence_score,
            "Workflow candidate confidence reflects how many grounded screen bearings were captured into a bounded step sequence.",
        ),
        environment_hints=list(sequence.stable_signals[:3]),
        known_failure_notes=(
            ["This workflow contains sensitive or redacted steps, so execution reuse should stay disabled."]
            if sequence.sensitive_signals
            else []
        ),
        allowed_reuse_modes=allowed_modes,
    )


def _current_page_label(observation: ScreenObservation, current_context: CurrentScreenContext) -> str | None:
    active_item = observation.workspace_snapshot.get("active_item")
    if isinstance(active_item, dict):
        label = str(active_item.get("title") or active_item.get("name") or "").strip()
        if label:
            return label
    summary = str(current_context.summary or "").strip()
    if summary:
        match = re.search(r"focused on ([^.]+)", summary, flags=re.IGNORECASE)
        if match:
            return str(match.group(1)).strip().strip('"')
    title = str(observation.focus_metadata.get("window_title") or "").strip()
    if not title:
        return None
    cleaned = _BROWSER_SUFFIX.sub("", title).strip()
    return cleaned or title


def _current_target(grounding_result: GroundingOutcome | None, navigation_result: NavigationOutcome | None) -> tuple[str | None, str | None]:
    if grounding_result is not None and grounding_result.winning_target is not None:
        return grounding_result.winning_target.label, grounding_result.winning_target.candidate_id
    if navigation_result is not None and navigation_result.winning_candidate is not None:
        return navigation_result.winning_candidate.label, navigation_result.winning_candidate.candidate_id
    return None, None


def _request_type(operator_text: str) -> WorkflowLearningRequestType:
    lowered = _normalize_text(operator_text)
    if any(phrase in lowered for phrase in _SAVE_HINTS):
        return WorkflowLearningRequestType.SAVE_WORKFLOW
    if any(phrase in lowered for phrase in _MATCH_HINTS):
        return WorkflowLearningRequestType.MATCH_WORKFLOW
    if any(phrase in lowered for phrase in _REUSE_HINTS):
        return WorkflowLearningRequestType.REUSE_WORKFLOW
    return WorkflowLearningRequestType.START_OBSERVATION


def _workflow_match_score(
    workflow: ReusableWorkflow,
    *,
    current_page: str | None,
    current_target_label: str | None,
    current_target_candidate_id: str | None,
    operator_text: str,
) -> tuple[float, list[str]]:
    score = 0.0
    evidence: list[str] = []
    normalized_page = _normalize_text(current_page)
    normalized_target = _normalize_text(current_target_label)
    label_tokens = {_normalize_text(workflow.label.primary_label)}
    label_tokens.update(_normalize_text(alias) for alias in workflow.label.aliases)
    if normalized_page and any(normalized_page == _normalize_text(signal) for signal in workflow.environment_hints):
        score += 0.42
        evidence.append(f'The current page matches the stored workflow environment "{current_page}".')
    if normalized_target and any(normalized_target == _normalize_text(step.target_label) for step in workflow.step_sequence.steps if step.target_label):
        score += 0.38
        evidence.append(f'The current grounded target matches the stored workflow step "{current_target_label}".')
    if current_target_candidate_id and any(current_target_candidate_id == step.target_candidate_id for step in workflow.step_sequence.steps if step.target_candidate_id):
        score += 0.08
        evidence.append("The current candidate id matches a previously captured workflow step.")
    lowered = _normalize_text(operator_text)
    if any(token and token in lowered for token in label_tokens):
        score += 0.08
        evidence.append("The request text references the stored workflow label.")
    if workflow.step_sequence.sensitive_signals:
        score -= 0.05
    return max(0.0, min(score, 1.0)), evidence


def _synthesize_action_request(step: WorkflowStepEvent) -> str | None:
    if step.action_intent is None:
        if step.target_label:
            return f"click {step.target_label}"
        return None
    if step.action_intent == ActionIntent.CLICK and step.target_label:
        return f"click {step.target_label}"
    if step.action_intent == ActionIntent.FOCUS and step.target_label:
        return f"focus {step.target_label}"
    if step.action_intent == ActionIntent.SELECT and step.target_label:
        return f"select {step.target_label}"
    if step.action_intent == ActionIntent.PRESS_KEY:
        return "press Enter"
    if step.action_intent == ActionIntent.SCROLL:
        return "scroll down a bit"
    return None


@dataclass(slots=True)
class WorkflowLearningEnvelope:
    result: WorkflowLearningResult
    action_result: ActionExecutionResult | None = None
    observation: ScreenObservation | None = None
    interpretation: ScreenInterpretation | None = None
    current_context: CurrentScreenContext | None = None
    verification: VerificationOutcome | None = None


@dataclass(slots=True)
class DeterministicWorkflowLearningEngine:
    config: ScreenAwarenessConfig
    sessions: dict[str, WorkflowObservationSession] = field(default_factory=dict)
    workflows: dict[str, ReusableWorkflow] = field(default_factory=dict)

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "active_session_count": sum(1 for session in self.sessions.values() if session.active),
            "stored_workflow_count": len(self.workflows),
        }

    def should_assess(self, *, operator_text: str, intent: ScreenIntentType) -> bool:
        lowered = _normalize_text(operator_text)
        return intent == ScreenIntentType.LEARN_WORKFLOW_REUSE or any(
            phrase in lowered for phrase in (*_START_HINTS, *_SAVE_HINTS, *_MATCH_HINTS, *_REUSE_HINTS)
        )

    def assess(
        self,
        *,
        session_id: str,
        operator_text: str,
        intent: ScreenIntentType,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        verification_result: VerificationOutcome | None,
        action_result: ActionExecutionResult | None,
        continuity_result: Any,
        adapter_resolution: AppAdapterResolution | None,
        problem_solving_result: Any,
        active_context: dict[str, Any] | None,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any],
        action_engine: DeterministicActionEngine,
    ) -> WorkflowLearningEnvelope | None:
        del continuity_result, adapter_resolution, problem_solving_result
        if not self.should_assess(operator_text=operator_text, intent=intent):
            return None
        request_type = _request_type(operator_text)
        current_page = _current_page_label(observation, current_context)
        current_target_label, current_target_candidate_id = _current_target(grounding_result, navigation_result)
        provenance_channels: list[GroundingEvidenceChannel] = []
        if grounding_result is not None:
            provenance_channels.extend(channel for channel in grounding_result.provenance.channels_used if channel not in provenance_channels)
        if navigation_result is not None:
            provenance_channels.extend(channel for channel in navigation_result.provenance.channels_used if channel not in provenance_channels)
        if verification_result is not None:
            provenance_channels.extend(channel for channel in verification_result.provenance.channels_used if channel not in provenance_channels)
        if action_result is not None:
            provenance_channels.extend(channel for channel in action_result.provenance.channels_used if channel not in provenance_channels)

        if request_type == WorkflowLearningRequestType.START_OBSERVATION:
            session = WorkflowObservationSession(
                session_id=session_id,
                started_at=datetime.now(timezone.utc).isoformat(),
                active=True,
                label_hint=current_page,
            )
            self.sessions[session_id] = session
            result = WorkflowLearningResult(
                request_type=request_type,
                status=WorkflowLearningStatus.OBSERVING,
                observation_session=session,
                explanation_summary="Stormhelm started a bounded workflow-observation session and will use subsequent screen bearings instead of hidden background watching.",
                capture_status=WorkflowLearningStatus.OBSERVING.value,
                planner_result=PlannerWorkflowReuseResult(
                    resolved=True,
                    status=WorkflowLearningStatus.OBSERVING,
                    explanation_summary="A bounded workflow-observation session is active.",
                    provenance_channels=list(provenance_channels),
                ),
                provenance=GroundingProvenance(
                    channels_used=list(provenance_channels),
                    dominant_channel=provenance_channels[0] if provenance_channels else None,
                    signal_names=[signal for signal in (current_page, current_target_label) if signal],
                ),
                confidence=_score_confidence(0.72, "Workflow observation has begun and will use subsequent grounded screen bearings."),
            )
            return WorkflowLearningEnvelope(result=result)

        if request_type == WorkflowLearningRequestType.SAVE_WORKFLOW:
            session = self.sessions.get(session_id)
            if session is None or not session.active:
                result = WorkflowLearningResult(
                    request_type=request_type,
                    status=WorkflowLearningStatus.WEAK_BASIS,
                    explanation_summary="I do not have an active bounded workflow-observation session to finalize yet.",
                    capture_status=WorkflowLearningStatus.WEAK_BASIS.value,
                    available_workflows=list(self.workflows.values())[:4],
                    planner_result=PlannerWorkflowReuseResult(
                        resolved=False,
                        status=WorkflowLearningStatus.WEAK_BASIS,
                        explanation_summary="No active workflow observation session was available.",
                        provenance_channels=list(provenance_channels),
                    ),
                    provenance=GroundingProvenance(channels_used=list(provenance_channels)),
                    confidence=_score_confidence(0.24, "No active workflow observation session was available to finalize."),
                )
                return WorkflowLearningEnvelope(result=result)
            recent_resolutions = active_context.get("recent_context_resolutions") if isinstance(active_context, dict) else []
            resolutions: list[dict[str, Any]] = []
            started_at = _parse_timestamp(session.started_at)
            for resolution in recent_resolutions if isinstance(recent_resolutions, list) else []:
                if not isinstance(resolution, dict) or str(resolution.get("kind") or "").strip() != "screen_awareness":
                    continue
                if str(resolution.get("intent") or "").strip() == ScreenIntentType.LEARN_WORKFLOW_REUSE.value:
                    continue
                captured_at = _parse_timestamp(str(resolution.get("captured_at") or ""))
                if started_at is not None and captured_at is not None and captured_at < started_at:
                    continue
                resolutions.append(dict(resolution))
            candidate = _candidate_from_resolutions(resolutions, label_hint=session.label_hint)
            session.observed_resolution_count = len(resolutions)
            session.captured_step_count = len(candidate.step_sequence.steps) if candidate is not None else 0
            session.last_captured_at = str(resolutions[0].get("captured_at") or "") if resolutions else None
            session.active = False
            if candidate is None:
                result = WorkflowLearningResult(
                    request_type=request_type,
                    status=WorkflowLearningStatus.WEAK_BASIS,
                    observation_session=session,
                    explanation_summary="I do not have enough grounded screen bearings from that session to save a reusable workflow safely.",
                    capture_status=WorkflowLearningStatus.WEAK_BASIS.value,
                    available_workflows=list(self.workflows.values())[:4],
                    planner_result=PlannerWorkflowReuseResult(
                        resolved=False,
                        status=WorkflowLearningStatus.WEAK_BASIS,
                        explanation_summary="The recent session did not capture enough reusable workflow structure.",
                        provenance_channels=list(provenance_channels),
                    ),
                    provenance=GroundingProvenance(channels_used=list(provenance_channels)),
                    confidence=_score_confidence(
                        0.28,
                        "The bounded workflow session did not capture enough grounded step structure to save safely.",
                    ),
                )
                return WorkflowLearningEnvelope(result=result)
            workflow = ReusableWorkflow(
                workflow_id=f"workflow-{uuid4().hex}",
                label=candidate.label,
                summary=candidate.summary,
                step_sequence=candidate.step_sequence,
                accepted_at=datetime.now(timezone.utc).isoformat(),
                confidence=candidate.confidence,
                environment_hints=list(candidate.environment_hints),
                known_failure_notes=list(candidate.known_failure_notes),
                allowed_reuse_modes=list(candidate.allowed_reuse_modes),
            )
            self.workflows[workflow.workflow_id] = workflow
            result = WorkflowLearningResult(
                request_type=request_type,
                status=WorkflowLearningStatus.REUSABLE_ACCEPTED,
                observation_session=session,
                candidate=candidate,
                reusable_workflow=workflow,
                available_workflows=list(self.workflows.values())[:4],
                explanation_summary=f'Captured a bounded reusable workflow for "{workflow.label.primary_label}" from the recent grounded screen bearings.',
                capture_status=WorkflowLearningStatus.REUSABLE_ACCEPTED.value,
                planner_result=PlannerWorkflowReuseResult(
                    resolved=True,
                    status=WorkflowLearningStatus.REUSABLE_ACCEPTED,
                    workflow_id=workflow.workflow_id,
                    explanation_summary=f'Reusable workflow "{workflow.label.primary_label}" was saved.',
                    provenance_channels=list(provenance_channels),
                ),
                provenance=GroundingProvenance(
                    channels_used=list(provenance_channels),
                    dominant_channel=provenance_channels[0] if provenance_channels else None,
                    signal_names=list(candidate.step_sequence.stable_signals[:4]),
                ),
                confidence=_score_confidence(
                    max(0.56, workflow.confidence.score),
                    "The workflow was captured from recent grounded screen bearings and stored as a bounded reusable structure.",
                ),
            )
            return WorkflowLearningEnvelope(result=result)

        ranked: list[tuple[ReusableWorkflow, float, list[str]]] = []
        for workflow in self.workflows.values():
            score, evidence = _workflow_match_score(
                workflow,
                current_page=current_page,
                current_target_label=current_target_label,
                current_target_candidate_id=current_target_candidate_id,
                operator_text=operator_text,
            )
            ranked.append((workflow, score, evidence))
        ranked.sort(key=lambda item: item[1], reverse=True)
        if not ranked:
            result = WorkflowLearningResult(
                request_type=request_type,
                status=WorkflowLearningStatus.REFUSED,
                explanation_summary="I do not have a stored reusable workflow to match against yet.",
                available_workflows=[],
                clarification_needed=True,
                clarification_prompt="Start a bounded workflow-observation session first if you want me to save and reuse a flow.",
                planner_result=PlannerWorkflowReuseResult(
                    resolved=False,
                    status=WorkflowLearningStatus.REFUSED,
                    explanation_summary="No reusable workflow record was available.",
                    provenance_channels=list(provenance_channels),
                ),
                provenance=GroundingProvenance(channels_used=list(provenance_channels)),
                confidence=_score_confidence(0.18, "No reusable workflows are stored yet."),
            )
            return WorkflowLearningEnvelope(result=result)

        best_workflow, best_score, best_evidence = ranked[0]
        ambiguous = len(ranked) > 1 and abs(best_score - ranked[1][1]) < 0.12 and ranked[1][1] >= 0.45
        match_status = WorkflowMatchStatus.REFUSED
        learning_status = WorkflowLearningStatus.REFUSED
        if ambiguous:
            match_status = WorkflowMatchStatus.AMBIGUOUS_MATCH
            learning_status = WorkflowLearningStatus.AMBIGUOUS_MATCH
        elif best_score >= 0.74:
            match_status = WorkflowMatchStatus.STRONG_MATCH
            learning_status = WorkflowLearningStatus.STRONG_MATCH
        elif best_score >= 0.45:
            match_status = WorkflowMatchStatus.PARTIAL_MATCH
            learning_status = (
                WorkflowLearningStatus.PARTIAL_MATCH
                if request_type == WorkflowLearningRequestType.MATCH_WORKFLOW
                else WorkflowLearningStatus.DOWNGRADED_MATCH
            )
        elif best_score >= 0.3:
            match_status = WorkflowMatchStatus.DOWNGRADED_MATCH
            learning_status = WorkflowLearningStatus.DOWNGRADED_MATCH

        match_result = WorkflowMatchResult(
            workflow_id=best_workflow.workflow_id,
            workflow_label=best_workflow.label.primary_label,
            status=match_status,
            match_score=best_score,
            explanation_summary=(
                f'The current page and grounded target align with the stored workflow "{best_workflow.label.primary_label}".'
                if match_status == WorkflowMatchStatus.STRONG_MATCH
                else f'The current state only partially aligns with the stored workflow "{best_workflow.label.primary_label}".'
                if match_status in {WorkflowMatchStatus.PARTIAL_MATCH, WorkflowMatchStatus.DOWNGRADED_MATCH}
                else f'I cannot justify a clean workflow match for "{best_workflow.label.primary_label}" from the current evidence.'
            ),
            evidence_summary=list(best_evidence),
            matched_step_labels=[step.target_label for step in best_workflow.step_sequence.steps if step.target_label][:4],
            provenance_channels=list(provenance_channels),
            confidence=_score_confidence(best_score, "Workflow match confidence reflects page, target, and reuse-label overlap."),
        )
        if match_status == WorkflowMatchStatus.AMBIGUOUS_MATCH:
            result = WorkflowLearningResult(
                request_type=request_type,
                status=WorkflowLearningStatus.AMBIGUOUS_MATCH,
                match_result=match_result,
                available_workflows=[item[0] for item in ranked[:3]],
                clarification_needed=True,
                clarification_prompt="I see more than one plausible stored workflow here. Tell me which one you want to reuse.",
                explanation_summary="Multiple stored workflows remain plausible from the current evidence, so I won't collapse them into a single reuse story.",
                planner_result=PlannerWorkflowReuseResult(
                    resolved=False,
                    status=WorkflowLearningStatus.AMBIGUOUS_MATCH,
                    workflow_id=best_workflow.workflow_id,
                    match_score=best_score,
                    explanation_summary="Multiple stored workflows remain plausible.",
                    provenance_channels=list(provenance_channels),
                ),
                provenance=GroundingProvenance(
                    channels_used=list(provenance_channels),
                    dominant_channel=provenance_channels[0] if provenance_channels else None,
                    signal_names=[signal for signal in (current_page, current_target_label) if signal],
                ),
                confidence=_score_confidence(best_score, "Multiple workflow matches remain too close to collapse honestly."),
            )
            return WorkflowLearningEnvelope(result=result)

        next_step = next((step for step in best_workflow.step_sequence.steps if step.target_label or step.action_intent is not None), None)
        current_target_supported = bool(
            current_target_label and next_step is not None and next_step.target_label and _normalize_text(current_target_label) == _normalize_text(next_step.target_label)
        )
        wants_direct_reuse = request_type == WorkflowLearningRequestType.REUSE_WORKFLOW
        action_request_text = _synthesize_action_request(next_step) if next_step is not None else None
        allowed_execute = bool(
            wants_direct_reuse
            and match_status == WorkflowMatchStatus.STRONG_MATCH
            and current_target_supported
            and action_request_text
            and "execute" in best_workflow.allowed_reuse_modes
            and navigation_result is not None
            and navigation_result.winning_candidate is not None
        )
        reuse_mode = "execute" if allowed_execute else "guide"
        reuse_plan = WorkflowReusePlan(
            workflow_id=best_workflow.workflow_id,
            workflow_label=best_workflow.label.primary_label,
            reuse_mode=reuse_mode,
            explanation_summary=match_result.explanation_summary,
            next_step_label=next_step.target_label if next_step is not None else None,
            current_target_candidate_id=current_target_candidate_id,
            action_request_text=action_request_text,
            grounding_reused=grounding_result is not None,
            navigation_reused=navigation_result is not None,
            verification_reused=bool(self.config.verification_enabled),
            action_reused=True,
            safety_state=WorkflowReuseSafetyState(
                allowed=allowed_execute or not wants_direct_reuse,
                reason=(
                    "The stored workflow step and the current grounded target line up cleanly."
                    if allowed_execute or not wants_direct_reuse
                    else "The stored workflow step does not line up strongly enough with the current grounded target for automatic reuse."
                ),
                verification_ready=bool(self.config.verification_enabled),
                current_target_supported=current_target_supported,
                sensitive=bool(best_workflow.step_sequence.sensitive_signals),
            ),
        )
        result = WorkflowLearningResult(
            request_type=request_type,
            status=learning_status,
            available_workflows=[item[0] for item in ranked[:4]],
            match_result=match_result,
            reuse_plan=reuse_plan,
            explanation_summary=match_result.explanation_summary,
            planner_result=PlannerWorkflowReuseResult(
                resolved=match_status == WorkflowMatchStatus.STRONG_MATCH,
                status=learning_status,
                workflow_id=best_workflow.workflow_id,
                match_score=best_score,
                reuse_mode=reuse_mode,
                next_step_label=reuse_plan.next_step_label,
                explanation_summary=match_result.explanation_summary,
                provenance_channels=list(provenance_channels),
            ),
            provenance=GroundingProvenance(
                channels_used=list(provenance_channels),
                dominant_channel=provenance_channels[0] if provenance_channels else None,
                signal_names=[signal for signal in (current_page, current_target_label, best_workflow.label.primary_label) if signal],
            ),
            confidence=match_result.confidence,
        )
        if not wants_direct_reuse or reuse_mode != "execute" or not reuse_plan.safety_state.allowed:
            return WorkflowLearningEnvelope(result=result)

        action_envelope: ActionExecutionEnvelope = action_engine.execute(
            session_id=session_id,
            operator_text=action_request_text or operator_text,
            observation=observation,
            interpretation=interpretation,
            current_context=current_context,
            grounding_result=grounding_result,
            navigation_result=navigation_result,
            active_context=active_context,
            surface_mode=surface_mode,
            active_module=active_module,
            workspace_context=workspace_context,
        )
        executed_action = action_envelope.result
        result.attempted_reuse = executed_action.status in {
            ActionExecutionStatus.ATTEMPTED_UNVERIFIED,
            ActionExecutionStatus.VERIFIED_SUCCESS,
            ActionExecutionStatus.FAILED,
        }
        result.verified_reuse = executed_action.status == ActionExecutionStatus.VERIFIED_SUCCESS
        if executed_action.status == ActionExecutionStatus.VERIFIED_SUCCESS:
            result.status = WorkflowLearningStatus.REUSE_VERIFIED_SUCCESS
        elif executed_action.status == ActionExecutionStatus.ATTEMPTED_UNVERIFIED:
            result.status = WorkflowLearningStatus.REUSE_ATTEMPTED_UNVERIFIED
        elif executed_action.status == ActionExecutionStatus.PLANNED:
            result.status = WorkflowLearningStatus.REUSE_PLANNED
        else:
            result.status = WorkflowLearningStatus.REUSE_ATTEMPTED
        if result.planner_result is not None:
            result.planner_result.status = result.status
            result.planner_result.attempted_reuse = result.attempted_reuse
            result.planner_result.verified_reuse = result.verified_reuse
            result.planner_result.confirmation_required = bool(executed_action.gate.confirmation_required)
        if result.reuse_plan is not None:
            result.reuse_plan.confirmation_required = bool(executed_action.gate.confirmation_required)
        return WorkflowLearningEnvelope(
            result=result,
            action_result=executed_action,
            observation=action_envelope.observation,
            interpretation=action_envelope.interpretation,
            current_context=action_envelope.current_context,
            verification=action_envelope.verification,
        )
