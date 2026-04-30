from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any

from stormhelm.core.screen_awareness.models import CurrentScreenContext
from stormhelm.core.screen_awareness.models import ClarificationNeed
from stormhelm.core.screen_awareness.models import GroundedTarget
from stormhelm.core.screen_awareness.models import GroundingAmbiguityStatus
from stormhelm.core.screen_awareness.models import GroundingCandidate
from stormhelm.core.screen_awareness.models import GroundingCandidateRole
from stormhelm.core.screen_awareness.models import GroundingEvidence
from stormhelm.core.screen_awareness.models import GroundingEvidenceChannel
from stormhelm.core.screen_awareness.models import GroundingExplanation
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import GroundingProvenance
from stormhelm.core.screen_awareness.models import GroundingRequest
from stormhelm.core.screen_awareness.models import GroundingRequestType
from stormhelm.core.screen_awareness.models import GroundingScore
from stormhelm.core.screen_awareness.models import PlannerGroundingResult
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenInterpretation
from stormhelm.core.screen_awareness.models import ScreenObservation
from stormhelm.core.screen_awareness.models import ScreenSourceType
from stormhelm.core.screen_awareness.models import ScreenTruthState
from stormhelm.core.screen_awareness.models import confidence_level_for_score
from stormhelm.core.screen_awareness.observation import best_visible_text


_ROLE_KEYWORDS: dict[GroundingCandidateRole, tuple[str, ...]] = {
    GroundingCandidateRole.BUTTON: ("button", "cta"),
    GroundingCandidateRole.CHECKBOX: ("checkbox", "toggle"),
    GroundingCandidateRole.FIELD: ("field", "input", "textbox", "text-field"),
    GroundingCandidateRole.WARNING: ("warning", "alert", "banner"),
    GroundingCandidateRole.ERROR: ("error", "failure"),
    GroundingCandidateRole.POPUP: ("popup", "dialog", "modal"),
    GroundingCandidateRole.MESSAGE: ("message", "notice"),
    GroundingCandidateRole.TAB: ("tab", "browser-tab"),
    GroundingCandidateRole.DOCUMENT: ("page", "document", "settings-page"),
    GroundingCandidateRole.WINDOW: ("window",),
    GroundingCandidateRole.REGION: ("region", "selection"),
}
_ORDINAL_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_SPATIAL_WORDS = {
    "left",
    "right",
    "top",
    "bottom",
    "upper",
    "lower",
    "selected",
    "focused",
    "current",
    "under",
    "cursor",
}
_APPEARANCE_WORDS = {"red", "blue", "green", "yellow", "orange", "purple"}
_REQUEST_STOP_WORDS = {
    "what",
    "is",
    "this",
    "that",
    "these",
    "those",
    "does",
    "mean",
    "which",
    "are",
    "you",
    "talking",
    "about",
    "the",
    "a",
    "an",
    "explain",
    "solve",
    "can",
    "why",
    "on",
    "my",
    "screen",
    "selected",
    "current",
    "field",
    "button",
    "checkbox",
    "popup",
    "warning",
    "problem",
    "blocking",
    "me",
    "click",
    "press",
    "type",
    "enter",
    "fill",
    "put",
    "write",
    "focus",
    "select",
    "scroll",
    "open",
    "hover",
    "go",
    "ahead",
    "do",
    "it",
    "into",
    "here",
}
_GROUNDING_HINTS = (
    "what is this",
    "what is that",
    "what does this",
    "what does that",
    "explain this",
    "solve this",
    "which button",
    "which checkbox",
    "selected field",
    "is this the problem",
    "what do you think i mean",
)
_VISUAL_PROVIDER_REASON = "provider_visual_grounding_unavailable_without_capture_reference"


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _preview(value: str | None, *, limit: int = 120) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _bounds_from_mapping(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("bounds"), dict):
        return dict(payload["bounds"])
    bounds: dict[str, Any] = {}
    for key in ("left", "top", "width", "height", "x", "y"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            bounds[key] = int(value)
    return bounds


def _score_confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_text(value))


def _extract_roles(text: str) -> list[GroundingCandidateRole]:
    lowered = _normalize_text(text)
    roles: list[GroundingCandidateRole] = []
    for role, keywords in _ROLE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            roles.append(role)
    return roles


def _extract_spatial(text: str) -> list[str]:
    tokens = _tokenize(text)
    values = [token for token in tokens if token in _SPATIAL_WORDS]
    for ordinal in _ORDINAL_WORDS:
        if ordinal in tokens:
            values.append(ordinal)
    return values


def _extract_appearance(text: str) -> list[str]:
    return [token for token in _tokenize(text) if token in _APPEARANCE_WORDS]


def _extract_label_tokens(text: str) -> list[str]:
    lowered = _normalize_text(text)
    role_words = {keyword for keywords in _ROLE_KEYWORDS.values() for keyword in keywords}
    return [
        token
        for token in _tokenize(lowered)
        if token not in _REQUEST_STOP_WORDS and token not in role_words and token not in _SPATIAL_WORDS and token not in _APPEARANCE_WORDS
    ]


def _infer_request_type(operator_text: str, intent: ScreenIntentType) -> GroundingRequestType:
    lowered = _normalize_text(operator_text)
    if "which " in lowered or "what do you think i mean" in lowered or "do you mean" in lowered:
        return GroundingRequestType.DISAMBIGUATION
    if "blocking" in lowered or "problem" in lowered:
        return GroundingRequestType.PROBLEM_IDENTIFICATION
    if intent == ScreenIntentType.SOLVE_VISIBLE_PROBLEM:
        return GroundingRequestType.SOLUTION
    if intent == ScreenIntentType.EXPLAIN_VISIBLE_CONTENT:
        return GroundingRequestType.EXPLANATION
    return GroundingRequestType.REFERENCE_RESOLUTION


def _detect_role(label: str, *, kind: str = "", default: GroundingCandidateRole = GroundingCandidateRole.UNKNOWN) -> GroundingCandidateRole:
    lowered = _normalize_text(f"{kind} {label}")
    for role, keywords in _ROLE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return role
    return default


def _looks_like_math_expression(text: str | None) -> bool:
    candidate = str(text or "").strip()
    return bool(candidate and len(candidate) <= 64 and re.fullmatch(r"[0-9\.\+\-\*\/\(\)\s%]+", candidate))


def _is_execution_request(request: GroundingRequest) -> bool:
    return "action_execution" in request.mode_flags


def _is_actionable_candidate(candidate: GroundingCandidate) -> bool:
    return candidate.role in {
        GroundingCandidateRole.BUTTON,
        GroundingCandidateRole.CHECKBOX,
        GroundingCandidateRole.FIELD,
        GroundingCandidateRole.TAB,
    }


@dataclass(slots=True)
class DeterministicGroundingEngine:
    provider: Any | None = None

    def should_ground(self, *, operator_text: str, intent: ScreenIntentType, observation: ScreenObservation) -> bool:
        lowered = _normalize_text(operator_text)
        if any(hint in lowered for hint in _GROUNDING_HINTS):
            return True
        if intent == ScreenIntentType.EXECUTE_UI_ACTION and (
            _extract_label_tokens(lowered)
            or _extract_roles(lowered)
            or observation.workspace_snapshot.get("active_item")
        ):
            return True
        if _extract_roles(lowered) or _extract_spatial(lowered) or _extract_appearance(lowered):
            return True
        if intent in {ScreenIntentType.EXPLAIN_VISIBLE_CONTENT, ScreenIntentType.SOLVE_VISIBLE_PROBLEM} and (
            observation.selected_text or observation.visual_text or observation.workspace_snapshot.get("active_item")
        ):
            return True
        return False

    def build_request(self, *, operator_text: str, intent: ScreenIntentType, observation: ScreenObservation) -> GroundingRequest:
        lowered = _normalize_text(operator_text)
        mode_flags = [flag for flag, present in {"deictic": any(token in lowered.split() for token in {"this", "that", "these", "those"})}.items() if present]
        if intent == ScreenIntentType.EXECUTE_UI_ACTION:
            mode_flags.append("action_execution")
        return GroundingRequest(
            utterance=operator_text,
            request_type=_infer_request_type(operator_text, intent),
            target_phrase=lowered,
            label_tokens=_extract_label_tokens(lowered),
            spatial_descriptors=_extract_spatial(lowered),
            role_descriptors=_extract_roles(lowered),
            appearance_descriptors=_extract_appearance(lowered),
            has_selected_region=bool(observation.selected_text),
            has_focus_anchor=bool(observation.focus_metadata or observation.workspace_snapshot.get("active_item")),
            has_cursor_anchor=bool(observation.cursor_metadata),
            mode_flags=mode_flags,
        )

    def resolve(
        self,
        *,
        operator_text: str,
        intent: ScreenIntentType,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
    ) -> GroundingOutcome | None:
        if not self.should_ground(operator_text=operator_text, intent=intent, observation=observation):
            return None

        request = self.build_request(operator_text=operator_text, intent=intent, observation=observation)
        candidates = self._collect_candidates(
            observation=observation,
            interpretation=interpretation,
            current_context=current_context,
        )
        ranked = self._score_candidates(request=request, candidates=candidates, observation=observation)
        ambiguity_status, confidence, winning_candidate = self._resolve_outcome(request=request, ranked_candidates=ranked)
        explanation = self._build_explanation(
            request=request,
            candidates=ranked,
            ambiguity_status=ambiguity_status,
            winning_candidate=winning_candidate,
        )
        clarification_need = self._clarification_need(
            request=request,
            candidates=ranked,
            ambiguity_status=ambiguity_status,
        )
        provenance = self._build_provenance(ranked, winning_candidate)
        winning_target = self._winning_target(winning_candidate)
        planner_result = PlannerGroundingResult(
            request_type=request.request_type,
            resolved=winning_target is not None,
            winning_candidate_id=winning_target.candidate_id if winning_target is not None else None,
            alternative_candidate_ids=[
                candidate.candidate_id
                for candidate in ranked[1:3]
                if candidate.candidate_id != (winning_target.candidate_id if winning_target is not None else None)
            ],
            ambiguity_status=ambiguity_status,
            confidence=confidence,
            explanation_summary=explanation.summary,
            provenance_channels=list(provenance.channels_used),
        )
        return GroundingOutcome(
            request=request,
            winning_target=winning_target,
            ranked_candidates=ranked,
            confidence=confidence,
            ambiguity_status=ambiguity_status,
            explanation=explanation,
            provenance=provenance,
            clarification_need=clarification_need,
            planner_result=planner_result,
            sensitivity_markers=list(current_context.sensitivity_markers),
        )

    def provider_grounding_status(self, observation: ScreenObservation) -> dict[str, Any]:
        capture_reference = str(observation.capture_reference or "").strip()
        if self.provider is None:
            return {"attempted": False, "used": False, "reason": "provider_unavailable"}
        if not capture_reference:
            return {"attempted": False, "used": False, "reason": _VISUAL_PROVIDER_REASON}
        return {"attempted": False, "used": False, "reason": "provider_visual_grounding_deferred"}

    def collect_candidates(
        self,
        *,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext | None = None,
    ) -> list[GroundingCandidate]:
        return self._collect_candidates(
            observation=observation,
            interpretation=interpretation,
            current_context=current_context,
        )

    def _collect_candidates(
        self,
        *,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext | None = None,
    ) -> list[GroundingCandidate]:
        candidates: list[GroundingCandidate] = []
        seen_workspace_ids: set[str] = set()
        if observation.selected_text:
            label = _preview(observation.selected_text)
            candidates.append(
                GroundingCandidate(
                    candidate_id="selection",
                    label=label,
                    role=_detect_role(label, kind=str(observation.selection_metadata.get("kind") or ""), default=GroundingCandidateRole.REGION),
                    source_channel=GroundingEvidenceChannel.NATIVE_OBSERVATION,
                    source_type=ScreenSourceType.SELECTION,
                    visible_text=observation.selected_text,
                    semantic_metadata=dict(observation.selection_metadata),
                )
            )
        if observation.visual_text:
            label = _preview(observation.visual_text)
            source_type = ScreenSourceType.PROVIDER_VISION if observation.visual_metadata.get("visual_text_source") == "provider_vision" else ScreenSourceType.LOCAL_OCR
            candidates.append(
                GroundingCandidate(
                    candidate_id="visual_text",
                    label=label,
                    role=_detect_role(label, kind="screen_capture", default=GroundingCandidateRole.REGION),
                    source_channel=GroundingEvidenceChannel.NATIVE_OBSERVATION,
                    source_type=source_type,
                    visible_text=observation.visual_text,
                    semantic_metadata=dict(observation.visual_metadata),
                )
            )
        active_item = observation.workspace_snapshot.get("active_item")
        if isinstance(active_item, dict) and active_item:
            candidate = self._workspace_candidate(active_item, is_active=True)
            if candidate is not None:
                candidates.append(candidate)
                seen_workspace_ids.add(candidate.candidate_id)
        for item in observation.workspace_snapshot.get("opened_items") or []:
            if not isinstance(item, dict):
                continue
            candidate = self._workspace_candidate(item, is_active=False)
            if candidate is None or candidate.candidate_id in seen_workspace_ids:
                continue
            candidates.append(candidate)
            seen_workspace_ids.add(candidate.candidate_id)
        if observation.focus_metadata:
            label = str(observation.focus_metadata.get("window_title") or observation.focus_metadata.get("process_name") or "").strip()
            if label:
                candidates.append(
                    GroundingCandidate(
                        candidate_id="focused_window",
                        label=label,
                        role=_detect_role(label, kind="window", default=GroundingCandidateRole.WINDOW),
                        source_channel=GroundingEvidenceChannel.NATIVE_OBSERVATION,
                        source_type=ScreenSourceType.FOCUS_STATE,
                        visible_text=label,
                        semantic_metadata=dict(observation.focus_metadata),
                    )
                )
        for index, error in enumerate(interpretation.visible_errors):
            label = _preview(error)
            candidates.append(
                GroundingCandidate(
                    candidate_id=f"visible_error_{index}",
                    label=label,
                    role=_detect_role(label, kind="error", default=GroundingCandidateRole.ERROR),
                    source_channel=GroundingEvidenceChannel.INTERPRETATION,
                    source_type=None,
                    visible_text=error,
                    semantic_metadata={"derived_from": "visible_errors"},
                )
            )
        if observation.clipboard_text and not observation.selected_text:
            label = _preview(observation.clipboard_text)
            candidates.append(
                GroundingCandidate(
                    candidate_id="clipboard",
                    label=label,
                    role=_detect_role(label, kind="clipboard", default=GroundingCandidateRole.MESSAGE),
                    source_channel=GroundingEvidenceChannel.NATIVE_OBSERVATION,
                    source_type=ScreenSourceType.CLIPBOARD,
                    visible_text=observation.clipboard_text,
                    semantic_metadata={},
                )
            )
        if current_context is not None:
            for semantic_target in current_context.semantic_targets:
                candidates.append(
                    GroundingCandidate(
                        candidate_id=semantic_target.candidate_id,
                        label=semantic_target.label,
                        role=semantic_target.role,
                        source_channel=GroundingEvidenceChannel.ADAPTER_SEMANTICS,
                        source_type=ScreenSourceType.APP_ADAPTER,
                        visible_text=semantic_target.label,
                        enabled=semantic_target.enabled,
                        parent_container=semantic_target.parent_container,
                        bounds=dict(semantic_target.bounds),
                        semantic_metadata=dict(semantic_target.semantic_metadata),
                    )
                )
        return candidates

    def _workspace_candidate(self, item: dict[str, Any], *, is_active: bool) -> GroundingCandidate | None:
        label = str(item.get("title") or item.get("name") or item.get("url") or "").strip()
        if not label:
            return None
        candidate_id = str(item.get("itemId") or item.get("id") or label).strip().lower().replace(" ", "_")
        metadata = dict(item)
        if is_active:
            metadata["active_item"] = True
        return GroundingCandidate(
            candidate_id=candidate_id,
            label=label,
            role=_detect_role(label, kind=str(item.get("kind") or ""), default=GroundingCandidateRole.ITEM),
            source_channel=GroundingEvidenceChannel.WORKSPACE_CONTEXT,
            source_type=ScreenSourceType.WORKSPACE_CONTEXT,
            visible_text=str(item.get("text") or item.get("title") or "").strip() or None,
            enabled=item.get("enabled") if isinstance(item.get("enabled"), bool) else None,
            parent_container=str(item.get("parent") or item.get("pane") or item.get("container") or "").strip() or None,
            bounds=_bounds_from_mapping(item),
            semantic_metadata=metadata,
        )

    def _score_candidates(
        self,
        *,
        request: GroundingRequest,
        candidates: list[GroundingCandidate],
        observation: ScreenObservation,
    ) -> list[GroundingCandidate]:
        ranked: list[GroundingCandidate] = []
        for candidate in candidates:
            score = GroundingScore()
            evidence: list[GroundingEvidence] = []
            score.source_trust_weight = self._source_trust_weight(candidate)
            evidence.append(
                GroundingEvidence(
                    signal="source_trust_weight",
                    channel=candidate.source_channel,
                    score=score.source_trust_weight,
                    note=f"{candidate.source_channel.value} contributes the base trust weight.",
                    truth_state=ScreenTruthState.OBSERVED if candidate.source_channel != GroundingEvidenceChannel.INTERPRETATION else ScreenTruthState.INFERRED,
                )
            )
            if request.has_selected_region and candidate.source_type == ScreenSourceType.SELECTION:
                score.selection_match = 0.34
                evidence.append(
                    GroundingEvidence(
                        signal="selection_match",
                        channel=GroundingEvidenceChannel.NATIVE_OBSERVATION,
                        score=score.selection_match,
                        note="The selected region is the strongest native anchor for this utterance.",
                    )
                )
            if request.has_focus_anchor and self._is_focus_match(candidate):
                score.focus_match = 0.22
                evidence.append(
                    GroundingEvidence(
                        signal="focus_match",
                        channel=candidate.source_channel,
                        score=score.focus_match,
                        note="Focus or active-item state supports this candidate.",
                    )
                )
            score.label_match = self._label_match(request, candidate)
            if score.label_match > 0.0:
                evidence.append(
                    GroundingEvidence(
                        signal="label_match",
                        channel=candidate.source_channel,
                        score=score.label_match,
                        note="Candidate label matches the user's referential language.",
                    )
                )
            score.role_match = self._role_match(request, candidate)
            if score.role_match > 0.0:
                evidence.append(
                    GroundingEvidence(
                        signal="role_match",
                        channel=candidate.source_channel,
                        score=score.role_match,
                        note="Candidate role matches the explicit role in the request.",
                    )
                )
            score.positional_match = self._positional_match(request, candidate)
            if score.positional_match > 0.0:
                evidence.append(
                    GroundingEvidence(
                        signal="positional_match",
                        channel=candidate.source_channel,
                        score=score.positional_match,
                        note="Spatial or ordinal descriptors match this candidate.",
                    )
                )
            score.appearance_match = self._appearance_match(request, candidate)
            if score.appearance_match > 0.0:
                evidence.append(
                    GroundingEvidence(
                        signal="appearance_match",
                        channel=candidate.source_channel,
                        score=score.appearance_match,
                        note="Appearance descriptors support this candidate.",
                    )
                )
            score.semantic_match = self._semantic_match(request, candidate, observation)
            if score.semantic_match > 0.0:
                evidence.append(
                    GroundingEvidence(
                        signal="semantic_match",
                        channel=candidate.source_channel,
                        score=score.semantic_match,
                        note="Request type and candidate semantics align.",
                        truth_state=ScreenTruthState.INFERRED,
                    )
                )
            score.penalty = self._penalty(request, candidate)
            if score.penalty > 0.0:
                evidence.append(
                    GroundingEvidence(
                        signal="penalty",
                        channel=candidate.source_channel,
                        score=-score.penalty,
                        note="Some request constraints do not match this candidate.",
                        truth_state=ScreenTruthState.INFERRED,
                    )
                )
            score.final_score = max(
                0.0,
                min(
                    1.0,
                    score.source_trust_weight
                    + score.selection_match
                    + score.focus_match
                    + score.label_match
                    + score.role_match
                    + score.positional_match
                    + score.appearance_match
                    + score.semantic_match
                    - score.penalty,
                ),
            )
            candidate.score = score
            candidate.evidence = evidence
            ranked.append(candidate)
        ranked.sort(key=lambda candidate: candidate.score.final_score, reverse=True)
        return ranked

    def _resolve_outcome(
        self,
        *,
        request: GroundingRequest,
        ranked_candidates: list[GroundingCandidate],
    ) -> tuple[GroundingAmbiguityStatus, ScreenConfidence, GroundingCandidate | None]:
        if not ranked_candidates:
            confidence = _score_confidence(0.0, "No grounding candidates were available from the current screen context.")
            return GroundingAmbiguityStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE, confidence, None

        top = ranked_candidates[0]
        second = ranked_candidates[1] if len(ranked_candidates) > 1 else None
        top_score = top.score.final_score
        gap = top_score - (second.score.final_score if second is not None else 0.0)
        confidence = _score_confidence(
            top_score if second is None else max(0.0, min(1.0, top_score - max(0.0, 0.08 - gap))),
            "Grounding confidence reflects the strength of the winning evidence and the gap to alternatives.",
        )
        if top_score < 0.46:
            return GroundingAmbiguityStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE, confidence, None
        if second is not None and self._should_preserve_ambiguity(request=request, top=top, second=second, gap=gap):
            return GroundingAmbiguityStatus.AMBIGUOUS, confidence, None
        if self._should_refuse_weak_winner(request=request, candidate=top):
            return GroundingAmbiguityStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE, confidence, None
        return GroundingAmbiguityStatus.RESOLVED, confidence, top

    def _build_explanation(
        self,
        *,
        request: GroundingRequest,
        candidates: list[GroundingCandidate],
        ambiguity_status: GroundingAmbiguityStatus,
        winning_candidate: GroundingCandidate | None,
    ) -> GroundingExplanation:
        del request
        if ambiguity_status == GroundingAmbiguityStatus.RESOLVED and winning_candidate is not None:
            reasons = [
                evidence.note
                for evidence in winning_candidate.evidence
                if evidence.score > 0 and evidence.signal != "source_trust_weight"
            ][:3]
            if not reasons:
                reasons = [f"{self._provenance_phrase(winning_candidate)} is the strongest current anchor."]
            summary = (
                f"I grounded this to {winning_candidate.label} from {self._provenance_phrase(winning_candidate)} "
                f"because {self._reason_join(reasons)}."
            )
            return GroundingExplanation(summary=summary, evidence_summary=reasons)
        if ambiguity_status == GroundingAmbiguityStatus.AMBIGUOUS:
            top_labels = [candidate.label for candidate in candidates[:2]]
            reasons = [
                "Multiple candidates remain plausible with similar evidence.",
                self._ambiguity_reason(candidates[:2]),
                f"Plausible targets: {', '.join(top_labels)}.",
            ]
            return GroundingExplanation(
                summary=(
                    f"There are multiple plausible matches for this request: {', '.join(top_labels)}. "
                    f"{self._ambiguity_reason(candidates[:2])}"
                ),
                evidence_summary=reasons,
                ambiguity_note="Ambiguity is being preserved rather than collapsed into false certainty.",
            )
        reasons = [
            "I do not yet have a direct anchor like selection, current focus, or a distinctive label match.",
            "No candidate had enough evidence across label, role, focus, or selection signals.",
            "A stronger visible anchor such as selection, focus, or a more specific label is needed.",
        ]
        return GroundingExplanation(
            summary="I do not have enough grounded evidence to resolve a single target safely.",
            evidence_summary=reasons,
            ambiguity_note="The current screen signal is too weak for a truthful winner.",
        )

    def _clarification_need(
        self,
        *,
        request: GroundingRequest,
        candidates: list[GroundingCandidate],
        ambiguity_status: GroundingAmbiguityStatus,
    ) -> ClarificationNeed | None:
        if ambiguity_status == GroundingAmbiguityStatus.RESOLVED:
            return None
        if ambiguity_status == GroundingAmbiguityStatus.AMBIGUOUS:
            labels = [candidate.label for candidate in candidates[:3]]
            role_hint = request.role_descriptors[0].value if request.role_descriptors else "target"
            return ClarificationNeed(
                needed=True,
                reason="multiple_plausible_candidates",
                prompt=f"I can see multiple plausible {role_hint} candidates. Which one do you mean: {', '.join(labels)}?",
                candidate_labels=labels,
            )
        return ClarificationNeed(
            needed=True,
            reason="insufficient_evidence",
            prompt="Please select the control, mention its label, or give a clearer position so I can ground it truthfully.",
            candidate_labels=[candidate.label for candidate in candidates[:3]],
        )

    def _build_provenance(
        self,
        candidates: list[GroundingCandidate],
        winning_candidate: GroundingCandidate | None,
    ) -> GroundingProvenance:
        focus = winning_candidate or (candidates[0] if candidates else None)
        if focus is None:
            return GroundingProvenance(channels_used=[], dominant_channel=None, signal_names=[])
        signal_names = [evidence.signal for evidence in focus.evidence]
        channel_order: list[GroundingEvidenceChannel] = []
        for evidence in focus.evidence:
            if evidence.channel not in channel_order:
                channel_order.append(evidence.channel)
        dominant = focus.source_channel if focus.source_channel in channel_order else (channel_order[0] if channel_order else None)
        return GroundingProvenance(
            channels_used=channel_order,
            dominant_channel=dominant,
            signal_names=signal_names,
        )

    def _winning_target(self, candidate: GroundingCandidate | None) -> GroundedTarget | None:
        if candidate is None:
            return None
        return GroundedTarget(
            candidate_id=candidate.candidate_id,
            label=candidate.label,
            role=candidate.role,
            source_channel=candidate.source_channel,
            source_type=candidate.source_type,
            visible_text=candidate.visible_text,
            enabled=candidate.enabled,
            parent_container=candidate.parent_container,
            bounds=dict(candidate.bounds),
            semantic_metadata=dict(candidate.semantic_metadata),
        )

    def _source_trust_weight(self, candidate: GroundingCandidate) -> float:
        if candidate.source_channel == GroundingEvidenceChannel.NATIVE_OBSERVATION:
            return 0.34
        if candidate.source_channel == GroundingEvidenceChannel.ADAPTER_SEMANTICS:
            return 0.31
        if candidate.source_channel == GroundingEvidenceChannel.WORKSPACE_CONTEXT:
            return 0.28
        if candidate.source_channel == GroundingEvidenceChannel.VISUAL_PROVIDER:
            return 0.18
        return 0.16

    def _is_focus_match(self, candidate: GroundingCandidate) -> bool:
        metadata = candidate.semantic_metadata
        return bool(
            metadata.get("focused")
            or metadata.get("selected")
            or metadata.get("active_item")
            or candidate.source_type == ScreenSourceType.FOCUS_STATE
        )

    def _label_match(self, request: GroundingRequest, candidate: GroundingCandidate) -> float:
        if not request.label_tokens:
            return 0.0
        label = _normalize_text(candidate.label)
        if all(token in label for token in request.label_tokens):
            return 0.24
        joined = " ".join(request.label_tokens)
        ratio = SequenceMatcher(None, joined, label).ratio()
        if ratio >= 0.6:
            return 0.14
        return 0.0

    def _role_match(self, request: GroundingRequest, candidate: GroundingCandidate) -> float:
        if not request.role_descriptors:
            return 0.0
        if candidate.role in request.role_descriptors:
            return 0.22
        if any(role in {GroundingCandidateRole.WARNING, GroundingCandidateRole.ERROR} for role in request.role_descriptors) and candidate.role in {
            GroundingCandidateRole.WARNING,
            GroundingCandidateRole.ERROR,
            GroundingCandidateRole.MESSAGE,
            GroundingCandidateRole.POPUP,
        }:
            return 0.18
        return 0.0

    def _positional_match(self, request: GroundingRequest, candidate: GroundingCandidate) -> float:
        if not request.spatial_descriptors:
            return 0.0
        metadata_text = _normalize_text(
            " ".join(
                [
                    str(candidate.parent_container or ""),
                    str(candidate.semantic_metadata.get("pane") or ""),
                    str(candidate.semantic_metadata.get("region") or ""),
                    str(candidate.semantic_metadata.get("position") or ""),
                ]
            )
        )
        score = 0.0
        if "selected" in request.spatial_descriptors and (
            candidate.source_type == ScreenSourceType.SELECTION or candidate.semantic_metadata.get("selected")
        ):
            score = max(score, 0.2)
        if "focused" in request.spatial_descriptors or "current" in request.spatial_descriptors:
            if self._is_focus_match(candidate):
                score = max(score, 0.18)
        for ordinal, expected in _ORDINAL_WORDS.items():
            if ordinal in request.spatial_descriptors and int(candidate.semantic_metadata.get("ordinal") or 0) == expected:
                score = max(score, 0.14)
        if any(word in request.spatial_descriptors for word in {"left", "right", "top", "bottom", "upper", "lower"}):
            if any(word in metadata_text for word in request.spatial_descriptors):
                score = max(score, 0.12)
        return score

    def _appearance_match(self, request: GroundingRequest, candidate: GroundingCandidate) -> float:
        if not request.appearance_descriptors:
            return 0.0
        metadata_text = _normalize_text(
            " ".join(
                [
                    candidate.label,
                    str(candidate.semantic_metadata.get("color") or ""),
                    str(candidate.semantic_metadata.get("appearance") or ""),
                ]
            )
        )
        if all(descriptor in metadata_text for descriptor in request.appearance_descriptors):
            return 0.14
        return 0.0

    def _semantic_match(
        self,
        request: GroundingRequest,
        candidate: GroundingCandidate,
        observation: ScreenObservation,
    ) -> float:
        if request.request_type == GroundingRequestType.PROBLEM_IDENTIFICATION and candidate.role in {
            GroundingCandidateRole.WARNING,
            GroundingCandidateRole.ERROR,
            GroundingCandidateRole.POPUP,
            GroundingCandidateRole.MESSAGE,
        }:
            return 0.12
        if request.request_type == GroundingRequestType.SOLUTION and _looks_like_math_expression(candidate.visible_text or candidate.label):
            return 0.18
        if request.request_type == GroundingRequestType.EXPLANATION and candidate.visible_text:
            visible_text = _normalize_text(candidate.visible_text)
            role_compatible = not request.role_descriptors or self._role_match(request, candidate) > 0.0
            if visible_text and visible_text == _normalize_text(best_visible_text(observation)) and role_compatible:
                return 0.08
        if _is_execution_request(request) and _is_actionable_candidate(candidate) and (
            request.label_tokens or request.role_descriptors or request.spatial_descriptors
        ):
            return 0.08
        return 0.0

    def _penalty(self, request: GroundingRequest, candidate: GroundingCandidate) -> float:
        penalty = 0.0
        if request.role_descriptors and self._role_match(request, candidate) == 0.0:
            penalty += 0.08
        if request.appearance_descriptors and self._appearance_match(request, candidate) == 0.0:
            penalty += 0.08
        if request.spatial_descriptors and self._positional_match(request, candidate) == 0.0 and any(
            word in request.spatial_descriptors for word in {"selected", "focused", "current"}
        ):
            penalty += 0.05
        if (
            _is_execution_request(request)
            and (request.label_tokens or request.role_descriptors or request.spatial_descriptors)
            and not _is_actionable_candidate(candidate)
            and candidate.role in {
                GroundingCandidateRole.WINDOW,
                GroundingCandidateRole.DOCUMENT,
                GroundingCandidateRole.REGION,
                GroundingCandidateRole.UNKNOWN,
            }
            and self._label_match(request, candidate) == 0.0
            and self._role_match(request, candidate) == 0.0
        ):
            penalty += 0.24
        return penalty

    def _reason_join(self, reasons: list[str]) -> str:
        filtered = [reason.rstrip(".") for reason in reasons if reason]
        if not filtered:
            return "the current evidence is the strongest available"
        if len(filtered) == 1:
            return filtered[0].lower()
        return ", ".join(reason.lower() for reason in filtered[:-1]) + f", and {filtered[-1].lower()}"

    def _should_preserve_ambiguity(
        self,
        *,
        request: GroundingRequest,
        top: GroundingCandidate,
        second: GroundingCandidate,
        gap: float,
    ) -> bool:
        second_score = second.score.final_score
        if second_score < 0.46:
            return False
        if gap < 0.08 and (top.label == second.label or request.request_type == GroundingRequestType.DISAMBIGUATION):
            return True
        if gap < 0.05:
            return True
        if (
            self._is_deictic_role_only_request(request)
            and gap < 0.12
            and not self._has_specific_anchor(top)
            and not self._has_specific_anchor(second)
        ):
            return True
        if (
            request.role_descriptors
            and gap < 0.1
            and top.score.role_match > 0.0
            and second.score.role_match > 0.0
            and not self._has_specific_anchor(top)
            and not self._has_specific_anchor(second)
        ):
            return True
        return False

    def _should_refuse_weak_winner(self, *, request: GroundingRequest, candidate: GroundingCandidate) -> bool:
        if self._has_specific_anchor(candidate):
            return False
        if self._is_deictic_role_only_request(request) and candidate.score.final_score < 0.72:
            return True
        if request.role_descriptors and not request.label_tokens and candidate.score.role_match > 0.0 and candidate.score.final_score < 0.62:
            return True
        return False

    def _has_specific_anchor(self, candidate: GroundingCandidate) -> bool:
        score = candidate.score
        return any(
            value > 0.0
            for value in (
                score.selection_match,
                score.focus_match,
                score.label_match,
                score.positional_match,
                score.appearance_match,
            )
        )

    def _is_deictic_role_only_request(self, request: GroundingRequest) -> bool:
        return (
            "deictic" in request.mode_flags
            and bool(request.role_descriptors)
            and not request.label_tokens
            and not request.appearance_descriptors
            and not request.spatial_descriptors
        )

    def _provenance_phrase(self, candidate: GroundingCandidate) -> str:
        if candidate.source_type == ScreenSourceType.SELECTION:
            return "the selected text"
        if candidate.source_type == ScreenSourceType.FOCUS_STATE:
            return "the current focused window"
        if candidate.semantic_metadata.get("active_item"):
            return "the current active item"
        if candidate.semantic_metadata.get("focused") or candidate.semantic_metadata.get("selected"):
            return "the current focus state"
        if candidate.source_channel == GroundingEvidenceChannel.WORKSPACE_CONTEXT:
            return "workspace context"
        if candidate.source_channel == GroundingEvidenceChannel.ADAPTER_SEMANTICS:
            adapter_id = str(candidate.semantic_metadata.get("adapter_id") or "app").replace("_", " ")
            return f"{adapter_id} adapter semantics"
        if candidate.source_channel == GroundingEvidenceChannel.NATIVE_OBSERVATION:
            return "native observation"
        if candidate.source_channel == GroundingEvidenceChannel.INTERPRETATION:
            return "interpreted visible content"
        if candidate.source_channel == GroundingEvidenceChannel.VISUAL_PROVIDER:
            return "provider visual evidence"
        return "the current screen context"

    def _ambiguity_reason(self, candidates: list[GroundingCandidate]) -> str:
        if candidates and not any(self._has_specific_anchor(candidate) for candidate in candidates):
            return "I only have weak role-level or workspace-level evidence here, not a direct anchor like selection or focus."
        return "The competing candidates stay too close to justify a single truthful winner."
