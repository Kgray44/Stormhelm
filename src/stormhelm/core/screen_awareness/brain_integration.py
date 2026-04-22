from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.intelligence.language import fuzzy_ratio
from stormhelm.core.screen_awareness.models import (
    ActionExecutionResult,
    AppAdapterResolution,
    BrainIntegrationRequestType,
    BrainIntegrationResult,
    BrainIntegrationStatus,
    CurrentScreenContext,
    EnvironmentQuirk,
    GroundingEvidenceChannel,
    GroundingOutcome,
    GroundingProvenance,
    LearnedPreference,
    LongTermMemoryBindingDecision,
    LongTermMemoryCandidate,
    MemoryBindingTarget,
    PlannerBrainIntegrationResult,
    ProactiveContinuitySuggestion,
    ScreenConfidence,
    ScreenIntentType,
    ScreenInterpretation,
    ScreenObservation,
    ScreenSensitivityLevel,
    SessionMemoryRecord,
    TaskGraph,
    TaskGraphLink,
    TaskGraphNode,
    VerificationOutcome,
    WorkflowContinuityResult,
    WorkflowLearningResult,
    confidence_level_for_score,
)


_REMEMBER_WORKFLOW_HINTS = (
    "remember this workflow for next time",
    "remember this for next time",
    "remember this workflow",
)
_PREFERENCE_HINTS = ("prefer", "preference", "keep this preference in mind")
_QUIRK_HINTS = (
    "this machine always needs that workaround",
    "learn that this environment behaves this way",
    "this always happens here",
)
_RECALL_HINTS = (
    "bring back the context from last time",
    "this looks like the same project as before",
    "this looks like the same thing as before",
)
_PROACTIVE_HINTS = ("proactively help me resume this when it makes sense",)


@dataclass(slots=True)
class _SessionState:
    task_graphs: dict[str, TaskGraph]
    session_memory: list[SessionMemoryRecord]


def _normalize(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _score_confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


def _parse_time(raw_value: str | None) -> datetime | None:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _freshness_seconds(raw_value: str | None) -> float | None:
    parsed = _parse_time(raw_value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def _analysis_payload(resolution: dict[str, Any]) -> dict[str, Any]:
    payload = resolution.get("analysis_result")
    return dict(payload) if isinstance(payload, dict) else {}


def _workspace_title(observation: ScreenObservation, workspace_context: dict[str, Any] | None) -> str:
    workspace_context = workspace_context or {}
    workspace = workspace_context.get("workspace")
    if isinstance(workspace, dict):
        title = str(workspace.get("title") or workspace.get("workspaceId") or "").strip()
        if title:
            return title
    workspace_snapshot = observation.workspace_snapshot if isinstance(observation.workspace_snapshot, dict) else {}
    workspace = workspace_snapshot.get("workspace")
    if isinstance(workspace, dict):
        title = str(workspace.get("title") or workspace.get("workspaceId") or "").strip()
        if title:
            return title
    active_item = workspace_snapshot.get("active_item")
    if isinstance(active_item, dict):
        title = str(active_item.get("title") or active_item.get("itemId") or "").strip()
        if title:
            return title
    title = str(observation.window_metadata.get("window_title") or "").strip()
    if title:
        return re.sub(r"\s*-\s*(google chrome|microsoft edge|firefox|brave)\s*$", "", title, flags=re.IGNORECASE).strip() or title
    return "Screen task"


def _current_node_label(observation: ScreenObservation, current_context: CurrentScreenContext) -> str:
    workspace_snapshot = observation.workspace_snapshot if isinstance(observation.workspace_snapshot, dict) else {}
    active_item = workspace_snapshot.get("active_item")
    if isinstance(active_item, dict):
        title = str(active_item.get("title") or active_item.get("itemId") or "").strip()
        if title:
            return title
    summary = str(current_context.summary or "").strip()
    if summary:
        return summary
    return "Current screen state"


def _request_type(operator_text: str) -> BrainIntegrationRequestType:
    normalized = _normalize(operator_text)
    if any(hint in normalized for hint in _REMEMBER_WORKFLOW_HINTS):
        return BrainIntegrationRequestType.REMEMBER_WORKFLOW
    if any(hint in normalized for hint in _RECALL_HINTS):
        return BrainIntegrationRequestType.RECALL_CONTEXT
    if any(hint in normalized for hint in _PROACTIVE_HINTS):
        return BrainIntegrationRequestType.ENABLE_PROACTIVE_CONTINUITY
    if any(hint in normalized for hint in _QUIRK_HINTS):
        return BrainIntegrationRequestType.LEARN_ENVIRONMENT_QUIRK
    if any(hint in normalized for hint in _PREFERENCE_HINTS):
        return BrainIntegrationRequestType.LEARN_PREFERENCE
    return BrainIntegrationRequestType.AUTO_INTEGRATE


def _explicit_preference(operator_text: str) -> tuple[str, str] | None:
    normalized = _normalize(operator_text)
    if "step-by-step" in normalized or "step by step" in normalized:
        return ("guidance_style", "step_by_step")
    if "concise" in normalized:
        return ("response_density", "concise")
    if "detailed" in normalized:
        return ("response_density", "detailed")
    if "guide mode" in normalized:
        return ("continuation_style", "guide_mode")
    return None


def _next_step_summaries(
    *,
    continuity_result: WorkflowContinuityResult | None,
    recent_resolutions: list[dict[str, Any]],
) -> list[str]:
    labels: list[str] = []
    if continuity_result is not None and continuity_result.resume_candidate is not None:
        label = str(continuity_result.resume_candidate.step_label or "").strip()
        if label:
            labels.append(label)
    for resolution in recent_resolutions:
        payload = _analysis_payload(resolution)
        navigation = payload.get("navigation_result")
        if isinstance(navigation, dict):
            step_state = navigation.get("step_state")
            if isinstance(step_state, dict):
                label = str(step_state.get("expected_target_label") or "").strip()
                if label and label not in labels:
                    labels.append(label)
    return labels[:4]


def _verified_outcomes(
    *,
    verification_result: VerificationOutcome | None,
    action_result: ActionExecutionResult | None,
    recent_resolutions: list[dict[str, Any]],
) -> list[str]:
    summaries: list[str] = []
    if verification_result is not None and verification_result.explanation.summary:
        summaries.append(verification_result.explanation.summary)
    if action_result is not None and action_result.status.value == "verified_success" and action_result.explanation_summary:
        summaries.append(action_result.explanation_summary)
    for resolution in recent_resolutions:
        payload = _analysis_payload(resolution)
        verification = payload.get("verification_result")
        if isinstance(verification, dict):
            explanation = verification.get("explanation")
            summary = str(explanation.get("summary") or "").strip() if isinstance(explanation, dict) else ""
            if summary and summary not in summaries:
                summaries.append(summary)
    return summaries[:4]


def _blocker_summaries(
    *,
    observation: ScreenObservation,
    current_context: CurrentScreenContext,
    continuity_result: WorkflowContinuityResult | None,
    recent_resolutions: list[dict[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    for item in current_context.blockers_or_prompts[:4]:
        text = str(item).strip()
        if text and text not in blockers:
            blockers.append(text)
    selected = str(observation.selected_text or "").strip()
    if selected and any(keyword in selected.lower() for keyword in {"error", "warning", "permission", "required", "failed"}):
        if selected not in blockers:
            blockers.append(selected)
    if continuity_result is not None and continuity_result.detour_state is not None:
        summary = str(continuity_result.detour_state.summary or "").strip()
        if summary and summary not in blockers:
            blockers.append(summary)
    for resolution in recent_resolutions:
        payload = _analysis_payload(resolution)
        context = payload.get("current_screen_context")
        if isinstance(context, dict):
            items = context.get("blockers_or_prompts")
            if isinstance(items, list):
                for item in items:
                    text = str(item).strip()
                    if text and text not in blockers:
                        blockers.append(text)
    return blockers[:4]


def _quirk_summary(observation: ScreenObservation, current_context: CurrentScreenContext, recent_resolutions: list[dict[str, Any]]) -> str | None:
    blockers = _blocker_summaries(
        observation=observation,
        current_context=current_context,
        continuity_result=None,
        recent_resolutions=recent_resolutions,
    )
    if blockers:
        return blockers[0]
    return None


def _provenance_channels(
    *,
    grounding_result: GroundingOutcome | None,
    verification_result: VerificationOutcome | None,
    action_result: ActionExecutionResult | None,
    continuity_result: WorkflowContinuityResult | None,
    workflow_learning_result: WorkflowLearningResult | None,
    adapter_resolution: AppAdapterResolution | None,
    recent_resolutions: list[dict[str, Any]],
) -> list[GroundingEvidenceChannel]:
    channels: list[GroundingEvidenceChannel] = []
    for result in (grounding_result, verification_result, action_result, continuity_result, workflow_learning_result):
        provenance = getattr(result, "provenance", None)
        used = getattr(provenance, "channels_used", None)
        if isinstance(used, list):
            for channel in used:
                if isinstance(channel, GroundingEvidenceChannel) and channel not in channels:
                    channels.append(channel)
    if adapter_resolution is not None and adapter_resolution.available and GroundingEvidenceChannel.ADAPTER_SEMANTICS not in channels:
        channels.append(GroundingEvidenceChannel.ADAPTER_SEMANTICS)
    for resolution in recent_resolutions:
        payload = _analysis_payload(resolution)
        for key in ("grounding_result", "verification_result", "action_result", "continuity_result", "workflow_learning_result"):
            section = payload.get(key)
            if not isinstance(section, dict):
                continue
            provenance = section.get("provenance")
            raw_channels = provenance.get("channels_used") if isinstance(provenance, dict) else None
            if not isinstance(raw_channels, list):
                continue
            for raw_channel in raw_channels:
                try:
                    channel = GroundingEvidenceChannel(str(raw_channel))
                except ValueError:
                    continue
                if channel not in channels:
                    channels.append(channel)
    return channels


class DeterministicBrainIntegrationEngine:
    def __init__(self, config: ScreenAwarenessConfig) -> None:
        self.config = config
        self._sessions: dict[str, _SessionState] = {}
        self._long_term_candidates: dict[str, LongTermMemoryCandidate] = {}
        self._learned_preferences: dict[str, LearnedPreference] = {}
        self._quirk_evidence_counts: dict[str, int] = {}
        self._environment_quirks: dict[str, EnvironmentQuirk] = {}

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "session_count": len(self._sessions),
            "task_graph_count": sum(len(state.task_graphs) for state in self._sessions.values()),
            "session_memory_count": sum(len(state.session_memory) for state in self._sessions.values()),
            "long_term_candidate_count": len(self._long_term_candidates),
            "learned_preference_count": len(self._learned_preferences),
            "environment_quirk_count": len(self._environment_quirks),
        }

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
        verification_result: VerificationOutcome | None,
        action_result: ActionExecutionResult | None,
        continuity_result: WorkflowContinuityResult | None,
        workflow_learning_result: WorkflowLearningResult | None,
        adapter_resolution: AppAdapterResolution | None,
        active_context: dict[str, Any] | None,
        workspace_context: dict[str, Any] | None,
    ) -> BrainIntegrationResult:
        del interpretation, intent
        active_context = active_context or {}
        recent_resolutions = active_context.get("recent_context_resolutions") if isinstance(active_context.get("recent_context_resolutions"), list) else []
        request_type = _request_type(operator_text)
        state = self._sessions.setdefault(session_id, _SessionState(task_graphs={}, session_memory=[]))
        task_label = _workspace_title(observation, workspace_context)
        current_node_label = _current_node_label(observation, current_context)
        graph_key = _normalize(task_label) or f"graph-{uuid4().hex}"
        existing_graph = state.task_graphs.get(graph_key)
        now = _timestamp()
        task_graph = existing_graph or TaskGraph(
            graph_id=f"task-graph-{uuid4().hex}",
            task_label=task_label,
            session_id=session_id,
            last_updated_at=now,
        )
        current_node = TaskGraphNode(
            node_id=f"task-node-{uuid4().hex}",
            label=current_node_label,
            node_type="workflow_stage",
            status="active",
            last_seen_at=now,
        )
        next_steps = _next_step_summaries(
            continuity_result=continuity_result,
            recent_resolutions=[item for item in recent_resolutions if isinstance(item, dict)],
        )
        blockers = _blocker_summaries(
            observation=observation,
            current_context=current_context,
            continuity_result=continuity_result,
            recent_resolutions=[item for item in recent_resolutions if isinstance(item, dict)],
        )
        outcomes = _verified_outcomes(
            verification_result=verification_result,
            action_result=action_result,
            recent_resolutions=[item for item in recent_resolutions if isinstance(item, dict)],
        )
        current_node.blocker_summaries = blockers
        current_node.verified_outcomes = outcomes
        current_node.resumable_next_step = next_steps[0] if next_steps else None
        task_graph.nodes = [node for node in task_graph.nodes if _normalize(node.label) != _normalize(current_node.label)]
        task_graph.nodes.insert(0, current_node)
        task_graph.current_node_id = current_node.node_id
        task_graph.last_updated_at = now
        task_graph.freshness_seconds = _freshness_seconds(task_graph.last_updated_at) or 0.0
        task_graph.links = []
        for step in next_steps[:2]:
            next_node = TaskGraphNode(
                node_id=f"task-node-{uuid4().hex}",
                label=step,
                node_type="next_step",
                status="pending",
                last_seen_at=now,
            )
            task_graph.nodes.append(next_node)
            task_graph.links.append(
                TaskGraphLink(
                    link_id=f"task-link-{uuid4().hex}",
                    from_node_id=current_node.node_id,
                    to_node_id=next_node.node_id,
                    relation="next_step",
                    summary=f'The current task points toward "{step}".',
                    confidence=_score_confidence(0.78, "The next-step link is grounded by recent screen bearings."),
                )
            )
        for outcome in outcomes[:2]:
            outcome_node = TaskGraphNode(
                node_id=f"task-node-{uuid4().hex}",
                label=outcome,
                node_type="verified_outcome",
                status="completed",
                last_seen_at=now,
            )
            task_graph.nodes.append(outcome_node)
            task_graph.links.append(
                TaskGraphLink(
                    link_id=f"task-link-{uuid4().hex}",
                    from_node_id=current_node.node_id,
                    to_node_id=outcome_node.node_id,
                    relation="verified_outcome",
                    summary=outcome,
                    confidence=_score_confidence(0.82, "The verified-outcome link is supported by a prior verified bearing."),
                )
            )
        state.task_graphs[graph_key] = task_graph

        new_memory: list[SessionMemoryRecord] = []
        for category, summary in [("next_step", step) for step in next_steps[:2]] + [("verified_outcome", outcome) for outcome in outcomes[:2]] + [("blocker", blocker) for blocker in blockers[:2]]:
            normalized_summary = _normalize(summary)
            existing_record = next(
                (
                    record
                    for record in state.session_memory
                    if record.task_graph_id == task_graph.graph_id
                    and record.category == category
                    and _normalize(record.summary) == normalized_summary
                ),
                None,
            )
            if existing_record is not None:
                existing_record.evidence_count += 1
                existing_record.created_at = now
                existing_record.freshness_seconds = 0.0
                continue
            record = SessionMemoryRecord(
                record_id=f"session-memory-{uuid4().hex}",
                category=category,
                summary=summary,
                task_graph_id=task_graph.graph_id,
                created_at=now,
                provenance_kind="screen_awareness",
                evidence_count=1,
                freshness_seconds=0.0,
                sensitive=observation.sensitivity in {ScreenSensitivityLevel.SENSITIVE, ScreenSensitivityLevel.RESTRICTED},
            )
            state.session_memory.insert(0, record)
            new_memory.append(record)
        state.session_memory = state.session_memory[:16]

        provenance_channels = _provenance_channels(
            grounding_result=grounding_result,
            verification_result=verification_result,
            action_result=action_result,
            continuity_result=continuity_result,
            workflow_learning_result=workflow_learning_result,
            adapter_resolution=adapter_resolution,
            recent_resolutions=[item for item in recent_resolutions if isinstance(item, dict)],
        )
        provenance = GroundingProvenance(
            channels_used=list(provenance_channels),
            dominant_channel=provenance_channels[0] if provenance_channels else None,
            signal_names=[signal for signal in [task_label, current_node_label] + next_steps[:1] + blockers[:1] if signal],
        )

        status = BrainIntegrationStatus.SESSION_INTEGRATED
        explanation = f'Bound the current screen-aware state into the task graph for "{task_label}" and updated session memory selectively.'
        confidence = _score_confidence(0.7, "The task graph and session memory are grounded in current screen-aware state.")
        binding_decision = LongTermMemoryBindingDecision(
            target_layer=MemoryBindingTarget.SESSION_MEMORY,
            reason="Selective session memory is appropriate for the current screen-aware state.",
        )
        long_term_candidate: LongTermMemoryCandidate | None = None
        learned_preference: LearnedPreference | None = None
        environment_quirk: EnvironmentQuirk | None = None
        proactive_suggestion: ProactiveContinuitySuggestion | None = None

        is_sensitive = observation.sensitivity in {ScreenSensitivityLevel.SENSITIVE, ScreenSensitivityLevel.RESTRICTED}
        if request_type == BrainIntegrationRequestType.REMEMBER_WORKFLOW:
            meaningful_evidence = len(new_memory) + len(next_steps) + len(outcomes)
            if is_sensitive:
                status = BrainIntegrationStatus.DEFERRED
                binding_decision = LongTermMemoryBindingDecision(
                    target_layer=MemoryBindingTarget.SESSION_MEMORY,
                    reason="The current bearing is sensitive, so Stormhelm will not promote it into longer-lived memory.",
                    explicit_request=True,
                    privacy_blocked=True,
                )
                explanation = "I bound the recent task state into session memory, but I am not promoting it into longer-lived memory because the current bearing is sensitive."
                confidence = _score_confidence(0.42, "Sensitive screen state should remain session-bounded.")
            elif meaningful_evidence >= 2:
                long_term_candidate = LongTermMemoryCandidate(
                    candidate_id=f"memory-candidate-{uuid4().hex}",
                    category="workflow",
                    summary=task_label,
                    source_task_graph_id=task_graph.graph_id,
                    evidence_count=meaningful_evidence,
                    usefulness_score=min(1.0, 0.45 + 0.1 * meaningful_evidence),
                    sensitivity=observation.sensitivity,
                    created_at=now,
                    freshness_seconds=0.0,
                    confidence=_score_confidence(
                        min(0.92, 0.58 + (0.08 * meaningful_evidence)),
                        "The workflow candidate is supported by recent grounded screen bearings and session memory.",
                    ),
                )
                self._long_term_candidates[_normalize(task_label)] = long_term_candidate
                status = BrainIntegrationStatus.CANDIDATE_CREATED
                binding_decision = LongTermMemoryBindingDecision(
                    target_layer=MemoryBindingTarget.LONG_TERM_CANDIDATE,
                    reason="The recent screen-aware task structure is strong enough to keep as a bounded long-term candidate.",
                    explicit_request=True,
                )
                explanation = f'Bound the recent screen-aware steps into a task graph and stored a bounded long-term memory candidate for "{task_label}". Current evidence will still outrank remembered context later.'
                confidence = long_term_candidate.confidence
            else:
                status = BrainIntegrationStatus.DEFERRED
                binding_decision = LongTermMemoryBindingDecision(
                    target_layer=MemoryBindingTarget.SESSION_MEMORY,
                    reason="There is not enough structured evidence yet to justify longer-lived workflow memory.",
                    explicit_request=True,
                )
                explanation = "I updated the task graph and session memory, but I can't justify longer-lived workflow memory from this evidence yet."
                confidence = _score_confidence(0.38, "The current workflow evidence is still too thin for durable promotion.")

        elif request_type == BrainIntegrationRequestType.LEARN_PREFERENCE:
            parsed = _explicit_preference(operator_text)
            if parsed is None:
                status = BrainIntegrationStatus.DEFERRED
                binding_decision = LongTermMemoryBindingDecision(
                    target_layer=MemoryBindingTarget.DEFERRED,
                    reason="No bounded preference could be identified from the current request.",
                    explicit_request=True,
                )
                explanation = "I updated the current task state, but I couldn't identify a bounded preference to learn safely."
                confidence = _score_confidence(0.26, "No bounded preference signal was available.")
            else:
                key, value = parsed
                pref_key = f"{key}:{_normalize(task_label) or 'screen'}"
                prior = self._learned_preferences.get(pref_key)
                evidence_count = (prior.evidence_count if prior is not None else 0) + 1
                learned_preference = LearnedPreference(
                    preference_key=pref_key,
                    value=value,
                    scope=task_label,
                    evidence_count=evidence_count,
                    learned_at=now,
                    confidence=_score_confidence(
                        0.84 if evidence_count == 1 else min(0.94, 0.84 + 0.04 * evidence_count),
                        "The user explicitly asked Stormhelm to remember a bounded preference.",
                    ),
                )
                self._learned_preferences[pref_key] = learned_preference
                status = BrainIntegrationStatus.PREFERENCE_LEARNED
                binding_decision = LongTermMemoryBindingDecision(
                    target_layer=MemoryBindingTarget.LEARNED_PREFERENCE,
                    reason="The user explicitly provided a bounded preference.",
                    explicit_request=True,
                )
                explanation = f'I learned a bounded preference for "{task_label}": {value.replace("_", " ")}.'
                confidence = learned_preference.confidence

        elif request_type == BrainIntegrationRequestType.LEARN_ENVIRONMENT_QUIRK:
            summary = _quirk_summary(observation, current_context, [item for item in recent_resolutions if isinstance(item, dict)])
            if not summary:
                status = BrainIntegrationStatus.DEFERRED
                binding_decision = LongTermMemoryBindingDecision(
                    target_layer=MemoryBindingTarget.DEFERRED,
                    reason="No recurring environment quirk could be grounded from the current evidence.",
                    explicit_request=True,
                )
                explanation = "I updated the task graph, but I couldn't ground a recurring environment quirk from the current evidence."
                confidence = _score_confidence(0.24, "No recurring environment quirk was grounded.")
            else:
                quirk_key = f"{_normalize(task_label)}::{_normalize(summary)}"
                evidence_count = self._quirk_evidence_counts.get(quirk_key, 0) + 1
                self._quirk_evidence_counts[quirk_key] = evidence_count
                if evidence_count >= 2:
                    environment_quirk = EnvironmentQuirk(
                        quirk_id=f"environment-quirk-{uuid4().hex}",
                        summary=summary,
                        scope=task_label,
                        evidence_count=evidence_count,
                        learned_at=now,
                        confidence=_score_confidence(
                            min(0.9, 0.62 + 0.08 * evidence_count),
                            "The same blocker has repeated enough times to count as a bounded environment quirk.",
                        ),
                    )
                    self._environment_quirks[quirk_key] = environment_quirk
                    status = BrainIntegrationStatus.QUIRK_LEARNED
                    binding_decision = LongTermMemoryBindingDecision(
                        target_layer=MemoryBindingTarget.ENVIRONMENT_QUIRK,
                        reason="The blocker has repeated enough times to count as an environment-local quirk.",
                        explicit_request=True,
                    )
                    explanation = f'I am treating "{summary}" as an environment-local quirk for "{task_label}", not as a universal rule.'
                    confidence = environment_quirk.confidence
                else:
                    status = BrainIntegrationStatus.DEFERRED
                    binding_decision = LongTermMemoryBindingDecision(
                        target_layer=MemoryBindingTarget.DEFERRED,
                        reason="A single blocker recurrence is not enough to justify a learned environment quirk.",
                        explicit_request=True,
                    )
                    explanation = "I noted the current blocker in session memory, but one recurrence is not enough to learn an environment quirk yet."
                    confidence = _score_confidence(0.36, "One blocker recurrence is not enough to learn a quirk safely.")

        elif request_type in {BrainIntegrationRequestType.RECALL_CONTEXT, BrainIntegrationRequestType.ENABLE_PROACTIVE_CONTINUITY}:
            best_candidate = None
            best_score = 0.0
            current_signature = _normalize(task_label)
            for signature, candidate in self._long_term_candidates.items():
                score = max(
                    fuzzy_ratio(current_signature, signature),
                    fuzzy_ratio(current_signature, _normalize(candidate.summary)),
                )
                if score > best_score:
                    best_score = score
                    best_candidate = candidate
            if best_candidate is not None and best_score >= 0.72:
                basis_parts = [f'remembered workflow candidate "{best_candidate.summary}"']
                matching_preference = next(
                    (
                        pref
                        for pref in self._learned_preferences.values()
                        if fuzzy_ratio(_normalize(pref.scope), current_signature) >= 0.72
                    ),
                    None,
                )
                matching_quirk = next(
                    (
                        quirk
                        for quirk in self._environment_quirks.values()
                        if fuzzy_ratio(_normalize(quirk.scope), current_signature) >= 0.72
                    ),
                    None,
                )
                if matching_preference is not None:
                    basis_parts.append(f'learned preference "{matching_preference.value.replace("_", " ")}"')
                if matching_quirk is not None:
                    basis_parts.append(f'environment quirk "{matching_quirk.summary}"')
                proactive_suggestion = ProactiveContinuitySuggestion(
                    suggestion_id=f"proactive-suggestion-{uuid4().hex}",
                    summary=(
                        f'This looks like the same task as "{best_candidate.summary}". '
                        f"Last time the next useful bearing was {next_steps[0]}."
                        if next_steps
                        else f'This looks like the same task as "{best_candidate.summary}".'
                    ),
                    basis_summary=", ".join(basis_parts),
                    task_graph_id=best_candidate.source_task_graph_id,
                    confidence=_score_confidence(min(0.88, best_score), "The recall suggestion is based on a close task match plus bounded remembered context."),
                    suppressible=True,
                )
                status = BrainIntegrationStatus.CONTEXT_RECALLED if request_type == BrainIntegrationRequestType.RECALL_CONTEXT else BrainIntegrationStatus.PROACTIVE_SUGGESTION
                binding_decision = LongTermMemoryBindingDecision(
                    target_layer=MemoryBindingTarget.WORKING_MEMORY,
                    reason="Remembered context was surfaced as a bounded suggestion rather than live truth.",
                    explicit_request=request_type == BrainIntegrationRequestType.RECALL_CONTEXT,
                )
                explanation = f'Current evidence suggests this may be the same task as "{best_candidate.summary}". I am surfacing the prior bearing as a suggestion, not treating it as live truth.'
                confidence = proactive_suggestion.confidence
            else:
                status = BrainIntegrationStatus.DEFERRED if request_type == BrainIntegrationRequestType.RECALL_CONTEXT else BrainIntegrationStatus.REFUSED
                binding_decision = LongTermMemoryBindingDecision(
                    target_layer=MemoryBindingTarget.DEFERRED,
                    reason="No close prior task match was available for a truthful continuity suggestion.",
                    explicit_request=request_type == BrainIntegrationRequestType.RECALL_CONTEXT,
                )
                explanation = "I can't justify treating this as the same task from the current evidence, so I won't merge it into a remembered continuity story."
                confidence = _score_confidence(0.31, "No close prior task match was available.")

        planner_result = PlannerBrainIntegrationResult(
            resolved=True,
            status=status,
            task_graph_id=task_graph.graph_id,
            binding_target=binding_decision.target_layer if binding_decision is not None else None,
            long_term_candidate_id=long_term_candidate.candidate_id if long_term_candidate is not None else None,
            preference_key=learned_preference.preference_key if learned_preference is not None else None,
            environment_quirk_id=environment_quirk.quirk_id if environment_quirk is not None else None,
            proactive_suggestion_present=proactive_suggestion is not None,
            explanation_summary=explanation,
            provenance_channels=list(provenance_channels),
        )
        return BrainIntegrationResult(
            request_type=request_type,
            status=status,
            task_graph=task_graph,
            session_memory_entries=list(state.session_memory),
            long_term_candidate=long_term_candidate,
            binding_decision=binding_decision,
            learned_preference=learned_preference,
            environment_quirk=environment_quirk,
            proactive_suggestion=proactive_suggestion,
            explanation_summary=explanation,
            planner_result=planner_result,
            provenance=provenance,
            confidence=confidence,
            reused_workflow_learning=workflow_learning_result is not None,
            reused_continuity=continuity_result is not None,
            reused_verification=verification_result is not None,
            reused_action=action_result is not None,
            reused_adapter=adapter_resolution is not None and adapter_resolution.available,
        )
