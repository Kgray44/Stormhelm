from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from stormhelm.core.screen_awareness.grounding import DeterministicGroundingEngine
from stormhelm.core.screen_awareness.models import CurrentScreenContext
from stormhelm.core.screen_awareness.models import GroundedTarget
from stormhelm.core.screen_awareness.models import GroundingAmbiguityStatus
from stormhelm.core.screen_awareness.models import GroundingCandidate
from stormhelm.core.screen_awareness.models import GroundingCandidateRole
from stormhelm.core.screen_awareness.models import GroundingEvidenceChannel
from stormhelm.core.screen_awareness.models import GroundingOutcome
from stormhelm.core.screen_awareness.models import GroundingProvenance
from stormhelm.core.screen_awareness.models import NavigationAmbiguityState
from stormhelm.core.screen_awareness.models import NavigationBlocker
from stormhelm.core.screen_awareness.models import NavigationCandidate
from stormhelm.core.screen_awareness.models import NavigationClarificationNeed
from stormhelm.core.screen_awareness.models import NavigationContext
from stormhelm.core.screen_awareness.models import NavigationGuidance
from stormhelm.core.screen_awareness.models import NavigationOutcome
from stormhelm.core.screen_awareness.models import NavigationRecoveryHint
from stormhelm.core.screen_awareness.models import NavigationRequest
from stormhelm.core.screen_awareness.models import NavigationRequestType
from stormhelm.core.screen_awareness.models import NavigationStepState
from stormhelm.core.screen_awareness.models import NavigationStepStatus
from stormhelm.core.screen_awareness.models import PlannerNavigationResult
from stormhelm.core.screen_awareness.models import ScreenConfidence
from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenInterpretation
from stormhelm.core.screen_awareness.models import ScreenObservation
from stormhelm.core.screen_awareness.models import ScreenSourceType
from stormhelm.core.screen_awareness.models import confidence_level_for_score
from stormhelm.core.screen_awareness.observation import best_visible_text


_ROLE_KEYWORDS: dict[GroundingCandidateRole, tuple[str, ...]] = {
    GroundingCandidateRole.BUTTON: ("button", "cta"),
    GroundingCandidateRole.CHECKBOX: ("checkbox", "toggle"),
    GroundingCandidateRole.FIELD: ("field", "input", "textbox", "text-field"),
    GroundingCandidateRole.WARNING: ("warning", "alert", "banner"),
    GroundingCandidateRole.ERROR: ("error", "failure"),
    GroundingCandidateRole.POPUP: ("popup", "dialog", "modal"),
    GroundingCandidateRole.MESSAGE: ("message", "notice", "prompt"),
    GroundingCandidateRole.TAB: ("tab", "browser-tab"),
    GroundingCandidateRole.DOCUMENT: ("page", "document", "settings-page"),
    GroundingCandidateRole.WINDOW: ("window",),
}
_NAVIGATION_STOP_WORDS = {
    "what",
    "should",
    "i",
    "click",
    "next",
    "where",
    "do",
    "go",
    "from",
    "here",
    "am",
    "on",
    "the",
    "right",
    "page",
    "wrong",
    "place",
    "field",
    "button",
    "screen",
    "looking",
    "for",
    "use",
    "supposed",
    "to",
    "how",
    "get",
    "step",
    "stuck",
    "now",
    "this",
    "that",
    "is",
    "my",
    "me",
}
_NEXT_STEP_HINTS = (
    "what should i click next",
    "where do i go from here",
    "what do i do now",
    "how do i get to the next step",
    "what am i looking for on this screen",
    "walk me through this",
)
_TARGET_SELECTION_HINTS = (
    "which field am i supposed to use",
    "which button am i supposed to use",
    "what field should i use",
)
_RIGHT_PAGE_HINTS = (
    "is this the right page",
    "am i on the right page",
    "i think i'm in the wrong place",
    "i think im in the wrong place",
    "am i in the wrong place",
)
_BLOCKER_HINTS = (
    "i'm stuck",
    "im stuck",
    "i am stuck",
    "what is blocking me",
)
_NEXT_STEP_LABEL_PRIORS = {
    "next": 0.24,
    "continue": 0.22,
    "save": 0.18,
    "submit": 0.22,
    "allow": 0.2,
    "apply": 0.18,
    "confirm": 0.18,
    "finish": 0.18,
    "open": 0.12,
    "review": 0.12,
    "enable": 0.18,
}
_RECOVERY_LABEL_PRIORS = {
    "back": 0.12,
    "return": 0.12,
    "security": 0.14,
    "settings": 0.1,
    "permissions": 0.1,
}
_NEGATIVE_NEXT_STEP_LABELS = {"cancel", "close"}
_BLOCKER_TOKENS = {
    "blocked",
    "required",
    "permission",
    "permissions",
    "denied",
    "disabled",
    "unavailable",
    "failed",
    "error",
    "warning",
    "expired",
    "loading",
    "wait",
}
_STRONG_BLOCKER_TOKENS = {
    "blocked",
    "required",
    "permission",
    "permissions",
    "denied",
    "disabled",
    "unavailable",
    "failed",
    "error",
    "expired",
    "loading",
    "wait",
    "must",
    "cannot",
    "can't",
}
_WRONG_PAGE_PATTERNS = (
    re.compile(r"\bopen\s+([a-z0-9 \-]+?)\s+(settings|page|tab|section)\b", flags=re.IGNORECASE),
    re.compile(r"\bgo\s+to\s+([a-z0-9 \-]+?)\s+(settings|page|tab|section)\b", flags=re.IGNORECASE),
    re.compile(r"\bswitch\s+to\s+([a-z0-9 \-]+?)\s+(settings|page|tab|section)\b", flags=re.IGNORECASE),
)
_HELP_SURFACE_TOKENS = {
    "help:",
    "help ",
    "learn more",
    "documentation",
    "docs",
    "support",
    "guide",
    "tip:",
    "tips",
    "sidebar",
}
_MODAL_CONTAINER_TOKENS = {"modal", "dialog", "popup", "sheet", "overlay"}
_STALE_METADATA_KEYS = {"stale", "background", "inactive", "cached", "hidden"}


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_text(value))


def _extract_roles(text: str) -> list[GroundingCandidateRole]:
    lowered = _normalize_text(text)
    roles: list[GroundingCandidateRole] = []
    for role, keywords in _ROLE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            roles.append(role)
    return roles


def _extract_label_tokens(text: str) -> list[str]:
    lowered = _normalize_text(text)
    role_words = {keyword for keywords in _ROLE_KEYWORDS.values() for keyword in keywords}
    return [token for token in _tokenize(lowered) if token not in _NAVIGATION_STOP_WORDS and token not in role_words]


def _score_confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


@dataclass(slots=True)
class DeterministicNavigationEngine:
    grounding_engine: DeterministicGroundingEngine

    def should_guide(self, *, operator_text: str, intent: ScreenIntentType) -> bool:
        lowered = _normalize_text(operator_text)
        return intent == ScreenIntentType.GUIDE_NAVIGATION or any(
            hint in lowered for hint in (*_NEXT_STEP_HINTS, *_TARGET_SELECTION_HINTS, *_RIGHT_PAGE_HINTS, *_BLOCKER_HINTS)
        )

    def build_request(self, *, operator_text: str) -> NavigationRequest:
        lowered = _normalize_text(operator_text)
        request_type = NavigationRequestType.NEXT_STEP
        if any(hint in lowered for hint in _TARGET_SELECTION_HINTS):
            request_type = NavigationRequestType.TARGET_SELECTION
        elif any(hint in lowered for hint in _RIGHT_PAGE_HINTS):
            request_type = NavigationRequestType.RIGHT_PAGE_CHECK
        elif any(hint in lowered for hint in _BLOCKER_HINTS):
            request_type = NavigationRequestType.BLOCKER_CHECK
        elif "next step" in lowered or "go from here" in lowered or "walk me through" in lowered:
            request_type = NavigationRequestType.RECOVERY if "walk me through" in lowered else NavigationRequestType.NEXT_STEP
        return NavigationRequest(
            utterance=operator_text,
            request_type=request_type,
            label_tokens=_extract_label_tokens(lowered),
            role_descriptors=_extract_roles(lowered),
            wants_next_step_guidance=request_type in {NavigationRequestType.NEXT_STEP, NavigationRequestType.RECOVERY},
            wants_page_check=request_type == NavigationRequestType.RIGHT_PAGE_CHECK,
            wants_recovery=request_type == NavigationRequestType.RECOVERY,
            wants_blocker_check=request_type == NavigationRequestType.BLOCKER_CHECK,
            mode_flags=[flag for flag, present in {"deictic": any(token in lowered.split() for token in {"this", "that", "these", "those"})}.items() if present],
        )

    def resolve(
        self,
        *,
        operator_text: str,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
    ) -> NavigationOutcome | None:
        if not self.should_guide(operator_text=operator_text, intent=ScreenIntentType.GUIDE_NAVIGATION):
            return None

        request = self.build_request(operator_text=operator_text)
        context = self._build_context(observation=observation, current_context=current_context, grounding_result=grounding_result)

        blocker = self._detect_blocker(request=request, observation=observation, interpretation=interpretation, grounding_result=grounding_result)
        if blocker is not None:
            return self._blocked_outcome(request=request, context=context, blocker=blocker)

        if request.request_type == NavigationRequestType.TARGET_SELECTION and grounding_result is not None:
            grounded_outcome = self._outcome_from_grounding(request=request, context=context, grounding_result=grounding_result)
            if grounded_outcome is not None:
                return grounded_outcome

        wrong_page = self._detect_wrong_page(request=request, observation=observation, current_context=current_context)
        if wrong_page is not None:
            return self._wrong_page_outcome(request=request, context=context, current_context=current_context, wrong_page=wrong_page)

        base_candidates = self.grounding_engine.collect_candidates(observation=observation, interpretation=interpretation)
        navigation_candidates = self._rank_candidates(
            request=request,
            candidates=base_candidates,
            current_context=current_context,
            grounding_result=grounding_result,
        )
        return self._candidate_outcome(
            request=request,
            context=context,
            ranked_candidates=navigation_candidates,
            grounding_result=grounding_result,
        )

    def _build_context(
        self,
        *,
        observation: ScreenObservation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
    ) -> NavigationContext:
        active_item = observation.workspace_snapshot.get("active_item")
        active_label = str(active_item.get("title") or active_item.get("name") or "").strip() if isinstance(active_item, dict) else None
        active_kind = str(active_item.get("kind") or "").strip() if isinstance(active_item, dict) else None
        return NavigationContext(
            current_summary=current_context.summary or "",
            visible_task_state=current_context.visible_task_state,
            candidate_next_steps=list(current_context.candidate_next_steps),
            blocker_cues=list(current_context.blockers_or_prompts),
            active_item_label=active_label or None,
            active_item_kind=active_kind or None,
            grounded_target=grounding_result.winning_target if grounding_result is not None else None,
            grounding_status=grounding_result.ambiguity_status if grounding_result is not None else GroundingAmbiguityStatus.NOT_REQUESTED,
            grounding_reused=False,
            provenance_channels=list(grounding_result.provenance.channels_used) if grounding_result is not None else [],
        )

    def _outcome_from_grounding(
        self,
        *,
        request: NavigationRequest,
        context: NavigationContext,
        grounding_result: GroundingOutcome,
    ) -> NavigationOutcome | None:
        if grounding_result.ambiguity_status == GroundingAmbiguityStatus.AMBIGUOUS and grounding_result.clarification_need is not None:
            labels = [candidate.label for candidate in grounding_result.ranked_candidates[:3]]
            ambiguity = NavigationAmbiguityState(
                ambiguous=True,
                reason="multiple_plausible_grounded_targets",
                candidate_labels=labels,
            )
            clarification = NavigationClarificationNeed(
                needed=True,
                reason="multiple_plausible_grounded_targets",
                prompt=grounding_result.clarification_need.prompt,
                candidate_labels=labels,
            )
            confidence = grounding_result.confidence
            step_state = NavigationStepState(
                status=NavigationStepStatus.AMBIGUOUS,
                current_step_summary=context.current_summary or "Multiple plausible targets are visible.",
                blocked=False,
                wrong_page=False,
                reentry_possible=True,
            )
            planner_result = PlannerNavigationResult(
                request_type=request.request_type,
                resolved=False,
                next_candidate_id=None,
                alternative_candidate_ids=[candidate.candidate_id for candidate in grounding_result.ranked_candidates[:3]],
                step_status=NavigationStepStatus.AMBIGUOUS,
                confidence=confidence,
                explanation_summary="Guided navigation is preserving the ambiguity from the Phase 2 grounded target.",
                provenance_channels=list(grounding_result.provenance.channels_used),
                clarification_needed=True,
            )
            return NavigationOutcome(
                request=request,
                context=context,
                step_state=step_state,
                ranked_candidates=[
                    NavigationCandidate(
                        candidate_id=candidate.candidate_id,
                        label=candidate.label,
                        role=candidate.role,
                        source_channel=candidate.source_channel,
                        source_type=candidate.source_type,
                        enabled=candidate.enabled,
                        parent_container=candidate.parent_container,
                        bounds=dict(candidate.bounds),
                        score=candidate.score.final_score,
                        reasons=["Phase 2 grounding still sees this as a plausible target."],
                        based_on_grounding=True,
                        semantic_metadata=dict(candidate.semantic_metadata),
                    )
                    for candidate in grounding_result.ranked_candidates[:3]
                ],
                ambiguity_state=ambiguity,
                clarification_need=clarification,
                planner_result=planner_result,
                provenance=grounding_result.provenance,
                confidence=confidence,
            )

        if grounding_result.ambiguity_status == GroundingAmbiguityStatus.UNRESOLVED_INSUFFICIENT_EVIDENCE:
            prompt = (
                grounding_result.clarification_need.prompt
                if grounding_result.clarification_need is not None
                else "Please give me a clearer visible anchor."
            )
            clarification = NavigationClarificationNeed(
                needed=True,
                reason="grounding_insufficient_evidence",
                prompt=prompt,
                candidate_labels=[candidate.label for candidate in grounding_result.ranked_candidates[:3]],
            )
            confidence = grounding_result.confidence
            step_state = NavigationStepState(
                status=NavigationStepStatus.UNRESOLVED,
                current_step_summary=context.current_summary or "The current workflow state is only partially grounded.",
                blocked=False,
                wrong_page=False,
                reentry_possible=True,
            )
            planner_result = PlannerNavigationResult(
                request_type=request.request_type,
                resolved=False,
                step_status=NavigationStepStatus.UNRESOLVED,
                confidence=confidence,
                explanation_summary="Guided navigation could not reuse a grounded winner because Phase 2 lacked enough evidence.",
                provenance_channels=list(grounding_result.provenance.channels_used),
                clarification_needed=True,
            )
            return NavigationOutcome(
                request=request,
                context=context,
                step_state=step_state,
                clarification_need=clarification,
                planner_result=planner_result,
                provenance=grounding_result.provenance,
                confidence=confidence,
            )

        if grounding_result.winning_target is None:
            return None

        winning_candidate = self._candidate_from_grounded_target(grounding_result.winning_target)
        winning_candidate.score = max(0.72, grounding_result.confidence.score)
        winning_candidate.reasons.append("Phase 2 already grounded this target from the current evidence.")
        winning_candidate.based_on_grounding = True
        context.grounding_reused = True
        context.grounded_target = grounding_result.winning_target
        confidence = _score_confidence(
            max(grounding_result.confidence.score, 0.72),
            "Navigation confidence reflects the strength of the reused grounded target.",
        )
        guidance = self._guidance_from_candidate(
            request=request,
            candidate=winning_candidate,
            confidence=confidence,
            provenance_note=self._candidate_provenance(winning_candidate),
            reused_grounding=True,
        )
        step_state = NavigationStepState(
            status=NavigationStepStatus.READY,
            current_step_summary=context.current_summary or "The current workflow state is available.",
            expected_target_label=winning_candidate.label,
            on_path=True,
            blocked=False,
            wrong_page=False,
            reentry_possible=True,
        )
        planner_result = PlannerNavigationResult(
            request_type=request.request_type,
            resolved=True,
            next_candidate_id=winning_candidate.candidate_id,
            alternative_candidate_ids=[
                candidate.candidate_id
                for candidate in grounding_result.ranked_candidates[1:3]
                if candidate.candidate_id != winning_candidate.candidate_id
            ],
            step_status=NavigationStepStatus.READY,
            confidence=confidence,
            explanation_summary=guidance.reasoning_summary,
            provenance_channels=list(grounding_result.provenance.channels_used),
        )
        return NavigationOutcome(
            request=request,
            context=context,
            step_state=step_state,
            winning_candidate=winning_candidate,
            ranked_candidates=[winning_candidate],
            guidance=guidance,
            planner_result=planner_result,
            provenance=grounding_result.provenance,
            confidence=confidence,
        )

    def _detect_blocker(
        self,
        *,
        request: NavigationRequest,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        grounding_result: GroundingOutcome | None,
    ) -> NavigationBlocker | None:
        del request
        candidates = self.grounding_engine.collect_candidates(observation=observation, interpretation=interpretation)
        if interpretation.visible_errors:
            text = interpretation.visible_errors[0]
            if self._is_blocking_message(text):
                confidence = _score_confidence(
                    0.86 if observation.selected_text else 0.68,
                    "Blocker confidence rises when the blocking message is directly visible.",
                )
                return NavigationBlocker(
                    blocker_type="visible_error",
                    summary=text,
                    evidence_summary=["A visible blocking message is currently present.", "The next step should wait until that message is addressed."],
                    confidence=confidence,
                    candidate_id=grounding_result.winning_target.candidate_id if grounding_result and grounding_result.winning_target else None,
                )

        for candidate in candidates:
            label = _normalize_text(candidate.label)
            if candidate.enabled is False:
                if self._has_enabled_alternate(candidate=candidate, candidates=candidates):
                    continue
                confidence = _score_confidence(0.72, "The candidate is visible but disabled, which is a direct blocker signal.")
                return NavigationBlocker(
                    blocker_type="disabled_target",
                    summary=f'"{candidate.label}" is visible but disabled right now.',
                    evidence_summary=["A likely next-step control is disabled.", "The flow is blocked until the requirement that enables it is satisfied."],
                    confidence=confidence,
                    candidate_id=candidate.candidate_id,
                )
            if candidate.role in {
                GroundingCandidateRole.WARNING,
                GroundingCandidateRole.ERROR,
                GroundingCandidateRole.POPUP,
                GroundingCandidateRole.MESSAGE,
            } and self._is_blocking_message(label):
                confidence = _score_confidence(0.76, "The current screen includes a visible blocker-like surface.")
                return NavigationBlocker(
                    blocker_type="visible_blocker_surface",
                    summary=candidate.label,
                    evidence_summary=["A warning, popup, or message is visible in the current workflow.", "That surface may need attention before the next step."],
                    confidence=confidence,
                    candidate_id=candidate.candidate_id,
                )
        return None

    def _detect_wrong_page(
        self,
        *,
        request: NavigationRequest,
        observation: ScreenObservation,
        current_context: CurrentScreenContext,
    ) -> tuple[str, str] | None:
        if not request.wants_page_check:
            return None
        visible_text = best_visible_text(observation) or " ".join(current_context.blockers_or_prompts)
        if not visible_text or self._looks_like_help_surface(observation=observation, visible_text=visible_text):
            return None
        active_item = observation.workspace_snapshot.get("active_item")
        current_label = (
            str(active_item.get("title") or observation.focus_metadata.get("window_title") or "").strip()
            if isinstance(active_item, dict)
            else str(observation.focus_metadata.get("window_title") or "").strip()
        )
        current_lower = _normalize_text(current_label)
        for pattern in _WRONG_PAGE_PATTERNS:
            match = pattern.search(visible_text or "")
            if not match:
                continue
            target_label = " ".join(str(match.group(1) or "").split()).strip()
            if target_label and _normalize_text(target_label) not in current_lower:
                return target_label, current_label
        return None

    def _blocked_outcome(
        self,
        *,
        request: NavigationRequest,
        context: NavigationContext,
        blocker: NavigationBlocker,
    ) -> NavigationOutcome:
        recovery = NavigationRecoveryHint(
            summary=self._blocker_recovery(blocker),
            reason="visible_blocker_recovery",
            confidence=_score_confidence(max(0.45, blocker.confidence.score - 0.12), "Recovery confidence stays cautious because the blocker is visible but unresolved."),
        )
        step_state = NavigationStepState(
            status=NavigationStepStatus.BLOCKED,
            current_step_summary=context.current_summary or "The current workflow appears blocked.",
            blocked=True,
            wrong_page=False,
            reentry_possible=True,
        )
        planner_result = PlannerNavigationResult(
            request_type=request.request_type,
            resolved=False,
            step_status=NavigationStepStatus.BLOCKED,
            confidence=blocker.confidence,
            explanation_summary=blocker.summary,
            provenance_channels=list(context.provenance_channels),
            blocker_present=True,
            clarification_needed=False,
        )
        return NavigationOutcome(
            request=request,
            context=context,
            step_state=step_state,
            blocker=blocker,
            recovery_hint=recovery,
            planner_result=planner_result,
            provenance=GroundingProvenance(
                channels_used=list(context.provenance_channels),
                dominant_channel=context.provenance_channels[0] if context.provenance_channels else GroundingEvidenceChannel.WORKSPACE_CONTEXT,
                signal_names=["visible_blocker"],
            ),
            confidence=blocker.confidence,
        )

    def _wrong_page_outcome(
        self,
        *,
        request: NavigationRequest,
        context: NavigationContext,
        current_context: CurrentScreenContext,
        wrong_page: tuple[str, str],
    ) -> NavigationOutcome:
        expected_page, current_page = wrong_page
        confidence = _score_confidence(
            0.72,
            "Wrong-page confidence comes from a visible instruction that names a different page or section.",
        )
        recovery = NavigationRecoveryHint(
            summary=f'You may need to go back and look for the "{expected_page}" page or section before continuing.',
            reason="wrong_page_recovery",
            confidence=_score_confidence(0.64, "Recovery remains cautious because Stormhelm is guiding, not executing."),
        )
        step_state = NavigationStepState(
            status=NavigationStepStatus.WRONG_PAGE,
            current_step_summary=current_context.summary or "The current page appears different from the visible requirement.",
            on_path=False,
            blocked=False,
            wrong_page=True,
            reentry_possible=True,
        )
        planner_result = PlannerNavigationResult(
            request_type=request.request_type,
            resolved=False,
            step_status=NavigationStepStatus.WRONG_PAGE,
            confidence=confidence,
            explanation_summary=f'The current page looks like "{current_page}", but the visible guidance points to "{expected_page}".',
            provenance_channels=list(context.provenance_channels),
            wrong_page=True,
        )
        return NavigationOutcome(
            request=request,
            context=context,
            step_state=step_state,
            recovery_hint=recovery,
            planner_result=planner_result,
            provenance=GroundingProvenance(
                channels_used=list(context.provenance_channels),
                dominant_channel=context.provenance_channels[0] if context.provenance_channels else GroundingEvidenceChannel.NATIVE_OBSERVATION,
                signal_names=["wrong_page_message", "current_page_context"],
            ),
            confidence=confidence,
        )

    def _rank_candidates(
        self,
        *,
        request: NavigationRequest,
        candidates: list[GroundingCandidate],
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
    ) -> list[NavigationCandidate]:
        ranked: list[NavigationCandidate] = []
        grounded_id = grounding_result.winning_target.candidate_id if grounding_result and grounding_result.winning_target else None
        modal_present = any(self._is_modal_surface(candidate) for candidate in candidates)
        for candidate in candidates:
            if candidate.role in {
                GroundingCandidateRole.WARNING,
                GroundingCandidateRole.ERROR,
                GroundingCandidateRole.POPUP,
                GroundingCandidateRole.MESSAGE,
            }:
                continue
            navigation_candidate = NavigationCandidate(
                candidate_id=candidate.candidate_id,
                label=candidate.label,
                role=candidate.role,
                source_channel=candidate.source_channel,
                source_type=candidate.source_type,
                enabled=candidate.enabled,
                parent_container=candidate.parent_container,
                bounds=dict(candidate.bounds),
                based_on_grounding=candidate.candidate_id == grounded_id,
                semantic_metadata=dict(candidate.semantic_metadata),
            )
            score = 0.0
            reasons: list[str] = []

            source_score = {
                GroundingEvidenceChannel.NATIVE_OBSERVATION: 0.26,
                GroundingEvidenceChannel.WORKSPACE_CONTEXT: 0.22,
                GroundingEvidenceChannel.INTERPRETATION: 0.12,
                GroundingEvidenceChannel.VISUAL_PROVIDER: 0.1,
            }.get(candidate.source_channel, 0.1)
            score += source_score
            reasons.append(f"{candidate.source_channel.value} provides the base navigation evidence.")

            if navigation_candidate.based_on_grounding:
                score += 0.34
                reasons.append("Phase 2 grounding already identified this as the strongest current target.")

            if modal_present:
                if self._is_modal_candidate(candidate):
                    score += 0.22
                    reasons.append("A visible modal or popup detour makes this candidate more immediate.")
                else:
                    score -= 0.12 if self._is_current_anchor(candidate) else 0.18
                    reasons.append("A visible modal detour makes background surfaces less immediate.")

            if self._is_current_anchor(candidate):
                score += 0.16
                reasons.append("Current focus or active-item state supports this candidate.")

            if candidate.enabled is True:
                score += 0.08
                reasons.append("The candidate appears enabled.")
            elif candidate.enabled is False:
                score -= 0.2
                reasons.append("The candidate appears disabled.")

            if self._is_stale_candidate(candidate):
                score -= 0.18
                reasons.append("Background or stale metadata makes this candidate less trustworthy.")

            if request.request_type in {NavigationRequestType.NEXT_STEP, NavigationRequestType.RECOVERY, NavigationRequestType.BLOCKER_CHECK}:
                if candidate.role in {GroundingCandidateRole.BUTTON, GroundingCandidateRole.TAB, GroundingCandidateRole.DOCUMENT, GroundingCandidateRole.ITEM}:
                    score += 0.12
                    reasons.append("The candidate is an actionable next-step surface.")
            if request.request_type == NavigationRequestType.TARGET_SELECTION and candidate.role in {
                GroundingCandidateRole.FIELD,
                GroundingCandidateRole.BUTTON,
                GroundingCandidateRole.CHECKBOX,
            }:
                score += 0.14
                reasons.append("The candidate matches the requested control type.")
            if request.request_type == NavigationRequestType.RIGHT_PAGE_CHECK and candidate.role in {
                GroundingCandidateRole.DOCUMENT,
                GroundingCandidateRole.TAB,
                GroundingCandidateRole.WINDOW,
                GroundingCandidateRole.ITEM,
            }:
                score += 0.14
                reasons.append("The candidate can anchor a page or section check.")

            label_score = self._label_match(request, candidate.label)
            if label_score > 0.0:
                score += label_score
                reasons.append("The candidate label matches the wording of the navigation request.")

            prior_score = self._label_prior(request, candidate.label)
            if prior_score > 0.0:
                score += prior_score
                reasons.append("The candidate label looks like a plausible next step.")

            next_step_hint_score = self._contextual_next_step_score(current_context, candidate.label)
            if next_step_hint_score > 0.0:
                score += next_step_hint_score
                reasons.append("Current context hints line up with this candidate.")

            navigation_candidate.score = max(0.0, min(1.0, score))
            navigation_candidate.reasons = reasons[:5]
            ranked.append(navigation_candidate)

        ranked.sort(key=lambda candidate: candidate.score, reverse=True)
        return ranked

    def _candidate_outcome(
        self,
        *,
        request: NavigationRequest,
        context: NavigationContext,
        ranked_candidates: list[NavigationCandidate],
        grounding_result: GroundingOutcome | None,
    ) -> NavigationOutcome:
        if not ranked_candidates:
            return self._unresolved_outcome(
                request=request,
                context=context,
                reason="No visible next-step candidates were strong enough to guide safely.",
            )

        top = ranked_candidates[0]
        second = ranked_candidates[1] if len(ranked_candidates) > 1 else None
        gap = top.score - (second.score if second is not None else 0.0)
        confidence = _score_confidence(
            top.score if second is None else max(0.0, min(1.0, top.score - max(0.0, 0.1 - gap))),
            "Navigation confidence reflects the strength of the next-step evidence and the gap to alternatives.",
        )

        if request.request_type == NavigationRequestType.RIGHT_PAGE_CHECK and not request.label_tokens:
            return self._unresolved_outcome(
                request=request,
                context=context,
                reason="I can't confirm whether this is the right page from the current evidence alone.",
                ranked_candidates=ranked_candidates,
                confidence=confidence,
                prompt="Please point me to the page title, section label, or target setting so I can check page alignment truthfully.",
            )

        if top.score < 0.5:
            return self._unresolved_outcome(
                request=request,
                context=context,
                reason="I can't justify a single next step from the current evidence.",
                ranked_candidates=ranked_candidates,
                confidence=confidence,
            )

        if self._is_weak_navigation_request(request=request) and not self._context_has_current_anchor(context) and top.score < 0.68:
            return self._unresolved_outcome(
                request=request,
                context=context,
                reason="I do not have a strong enough current anchor for a truthful next-step winner.",
                ranked_candidates=ranked_candidates,
                confidence=confidence,
            )

        if second is not None and second.score >= 0.48 and gap < 0.08:
            ambiguity = NavigationAmbiguityState(
                ambiguous=True,
                reason="multiple_plausible_navigation_targets",
                candidate_labels=[candidate.label for candidate in ranked_candidates[:3]],
            )
            clarification = NavigationClarificationNeed(
                needed=True,
                reason="multiple_plausible_navigation_targets",
                prompt=f'I see multiple plausible next targets. Which one do you mean: {", ".join(candidate.label for candidate in ranked_candidates[:3])}?',
                candidate_labels=[candidate.label for candidate in ranked_candidates[:3]],
            )
            step_state = NavigationStepState(
                status=NavigationStepStatus.AMBIGUOUS,
                current_step_summary=context.current_summary or "Multiple next-step targets remain plausible.",
                blocked=False,
                wrong_page=False,
                reentry_possible=True,
            )
            provenance = self._build_provenance(ranked_candidates, None, grounding_result)
            planner_result = PlannerNavigationResult(
                request_type=request.request_type,
                resolved=False,
                next_candidate_id=None,
                alternative_candidate_ids=[candidate.candidate_id for candidate in ranked_candidates[:3]],
                step_status=NavigationStepStatus.AMBIGUOUS,
                confidence=confidence,
                explanation_summary="Guided navigation preserved ambiguity because multiple next targets stayed close.",
                provenance_channels=list(provenance.channels_used),
                clarification_needed=True,
            )
            return NavigationOutcome(
                request=request,
                context=context,
                step_state=step_state,
                ranked_candidates=ranked_candidates,
                ambiguity_state=ambiguity,
                clarification_need=clarification,
                planner_result=planner_result,
                provenance=provenance,
                confidence=confidence,
            )

        if not self._has_navigation_anchor(request=request, candidate=top) and top.score < 0.64:
            return self._unresolved_outcome(
                request=request,
                context=context,
                reason="I do not have a strong enough current anchor for a truthful next-step winner.",
                ranked_candidates=ranked_candidates,
                confidence=confidence,
            )

        provenance = self._build_provenance(ranked_candidates, top, grounding_result)
        guidance = self._guidance_from_candidate(
            request=request,
            candidate=top,
            confidence=confidence,
            provenance_note=self._candidate_provenance(top),
            reused_grounding=top.based_on_grounding,
        )
        step_status = NavigationStepStatus.REENTRY if request.wants_recovery else NavigationStepStatus.READY
        step_state = NavigationStepState(
            status=step_status,
            current_step_summary=context.current_summary or "The current workflow state is available.",
            expected_target_label=top.label,
            on_path=True,
            blocked=False,
            wrong_page=False,
            reentry_possible=request.wants_recovery,
        )
        planner_result = PlannerNavigationResult(
            request_type=request.request_type,
            resolved=True,
            next_candidate_id=top.candidate_id,
            alternative_candidate_ids=[candidate.candidate_id for candidate in ranked_candidates[1:3]],
            step_status=step_status,
            confidence=confidence,
            explanation_summary=guidance.reasoning_summary,
            provenance_channels=list(provenance.channels_used),
        )
        context.grounding_reused = bool(top.based_on_grounding)
        return NavigationOutcome(
            request=request,
            context=context,
            step_state=step_state,
            winning_candidate=top,
            ranked_candidates=ranked_candidates,
            guidance=guidance,
            planner_result=planner_result,
            provenance=provenance,
            confidence=confidence,
        )

    def _unresolved_outcome(
        self,
        *,
        request: NavigationRequest,
        context: NavigationContext,
        reason: str,
        ranked_candidates: list[NavigationCandidate] | None = None,
        confidence: ScreenConfidence | None = None,
        prompt: str | None = None,
    ) -> NavigationOutcome:
        candidates = list(ranked_candidates or [])
        clarification = NavigationClarificationNeed(
            needed=True,
            reason="insufficient_navigation_evidence",
            prompt=prompt
            or "Please select the control, mention its label, or tell me which area of the screen you mean so I can guide truthfully.",
            candidate_labels=[candidate.label for candidate in candidates[:3]],
        )
        step_state = NavigationStepState(
            status=NavigationStepStatus.UNRESOLVED,
            current_step_summary=context.current_summary or "The current workflow state is only partially available.",
            blocked=False,
            wrong_page=False,
            reentry_possible=True,
        )
        final_confidence = confidence or _score_confidence(0.0, "No justified navigation winner is available.")
        provenance = self._build_provenance(candidates, None, None)
        planner_result = PlannerNavigationResult(
            request_type=request.request_type,
            resolved=False,
            step_status=NavigationStepStatus.UNRESOLVED,
            confidence=final_confidence,
            explanation_summary=reason,
            provenance_channels=list(provenance.channels_used),
            clarification_needed=True,
        )
        return NavigationOutcome(
            request=request,
            context=context,
            step_state=step_state,
            ranked_candidates=candidates,
            clarification_need=clarification,
            planner_result=planner_result,
            provenance=provenance,
            confidence=final_confidence,
        )

    def _guidance_from_candidate(
        self,
        *,
        request: NavigationRequest,
        candidate: NavigationCandidate,
        confidence: ScreenConfidence,
        provenance_note: str,
        reused_grounding: bool,
    ) -> NavigationGuidance:
        label = candidate.label
        if candidate.role == GroundingCandidateRole.BUTTON:
            instruction = f'The next step is likely the button "{label}".'
        elif candidate.role == GroundingCandidateRole.FIELD:
            instruction = f'The strongest field to use next is "{label}".'
        elif candidate.role in {GroundingCandidateRole.DOCUMENT, GroundingCandidateRole.TAB}:
            instruction = f'Look for the page or tab "{label}" next.'
        else:
            instruction = f'The strongest next visible target is "{label}".'
        if request.request_type == NavigationRequestType.TARGET_SELECTION and candidate.role == GroundingCandidateRole.FIELD:
            instruction = f'The field "{label}" is the strongest current match to use.'
        reasoning = f"Based on {provenance_note}, this is the strongest current navigation target."
        if reused_grounding:
            reasoning += " Phase 3 is reusing the existing Phase 2 grounded target rather than re-guessing it."
        look_for = None
        if candidate.parent_container:
            look_for = f'Look in the {candidate.parent_container} area for "{label}".'
        return NavigationGuidance(
            instruction=instruction,
            look_for=look_for,
            reasoning_summary=reasoning,
            confidence=confidence,
            provenance_note=provenance_note,
            target_candidate_id=candidate.candidate_id,
        )

    def _candidate_from_grounded_target(self, target: GroundedTarget) -> NavigationCandidate:
        return NavigationCandidate(
            candidate_id=target.candidate_id,
            label=target.label,
            role=target.role,
            source_channel=target.source_channel,
            source_type=target.source_type,
            enabled=target.enabled,
            parent_container=target.parent_container,
            bounds=dict(target.bounds),
            semantic_metadata=dict(target.semantic_metadata),
        )

    def _candidate_provenance(self, candidate: NavigationCandidate) -> str:
        if candidate.based_on_grounding:
            return "the previously grounded target"
        if candidate.source_type == ScreenSourceType.SELECTION:
            return "the selected text"
        if candidate.source_type == ScreenSourceType.FOCUS_STATE:
            return "the focused window"
        if candidate.semantic_metadata.get("active_item"):
            return "the current active item"
        if candidate.semantic_metadata.get("focused") or candidate.semantic_metadata.get("selected"):
            return "the current focus state"
        if candidate.source_channel == GroundingEvidenceChannel.NATIVE_OBSERVATION:
            return "native observation"
        if candidate.source_channel == GroundingEvidenceChannel.WORKSPACE_CONTEXT:
            return "workspace context"
        if candidate.source_channel == GroundingEvidenceChannel.INTERPRETATION:
            return "interpreted visible content"
        return "the current screen context"

    def _build_provenance(
        self,
        candidates: list[NavigationCandidate],
        winning_candidate: NavigationCandidate | None,
        grounding_result: GroundingOutcome | None,
    ) -> GroundingProvenance:
        focus = winning_candidate or (candidates[0] if candidates else None)
        channels: list[GroundingEvidenceChannel] = []
        if focus is not None:
            channels.append(focus.source_channel)
        if grounding_result is not None:
            for channel in grounding_result.provenance.channels_used:
                if channel not in channels:
                    channels.append(channel)
        dominant = focus.source_channel if focus is not None else (channels[0] if channels else None)
        signals = ["navigation_candidate_selection"] if focus is not None else []
        if focus is not None and focus.based_on_grounding:
            signals.append("reused_grounding_target")
        return GroundingProvenance(
            channels_used=channels,
            dominant_channel=dominant,
            signal_names=signals,
        )

    def _label_match(self, request: NavigationRequest, label: str) -> float:
        if not request.label_tokens:
            return 0.0
        normalized_label = _normalize_text(label)
        if all(token in normalized_label for token in request.label_tokens):
            return 0.24
        ratio = SequenceMatcher(None, " ".join(request.label_tokens), normalized_label).ratio()
        if ratio >= 0.6:
            return 0.12
        return 0.0

    def _label_prior(self, request: NavigationRequest, label: str) -> float:
        tokens = _tokenize(label)
        score = 0.0
        priors = _RECOVERY_LABEL_PRIORS if request.wants_recovery else _NEXT_STEP_LABEL_PRIORS
        for token in tokens:
            score = max(score, priors.get(token, 0.0))
        if not request.wants_recovery and any(token in tokens for token in _NEGATIVE_NEXT_STEP_LABELS):
            score -= 0.08
        return score

    def _contextual_next_step_score(self, current_context: CurrentScreenContext, label: str) -> float:
        hints = " ".join(current_context.candidate_next_steps).lower()
        if not hints:
            return 0.0
        normalized_label = _normalize_text(label)
        if normalized_label and normalized_label in hints:
            return 0.12
        if any(token in hints for token in _tokenize(label)):
            return 0.06
        return 0.0

    def _is_current_anchor(self, candidate: GroundingCandidate) -> bool:
        return bool(
            candidate.semantic_metadata.get("focused")
            or candidate.semantic_metadata.get("selected")
            or candidate.semantic_metadata.get("active_item")
            or candidate.source_type in {ScreenSourceType.SELECTION, ScreenSourceType.FOCUS_STATE}
        )

    def _has_navigation_anchor(self, *, request: NavigationRequest, candidate: NavigationCandidate) -> bool:
        if candidate.based_on_grounding:
            return True
        if candidate.source_type in {ScreenSourceType.SELECTION, ScreenSourceType.FOCUS_STATE}:
            return True
        if candidate.semantic_metadata.get("focused") or candidate.semantic_metadata.get("selected") or candidate.semantic_metadata.get("active_item"):
            return True
        if request.label_tokens and self._label_match(request, candidate.label) > 0.0:
            return True
        return False

    def _has_enabled_alternate(
        self,
        *,
        candidate: GroundingCandidate,
        candidates: list[GroundingCandidate],
    ) -> bool:
        for other in candidates:
            if other.candidate_id == candidate.candidate_id:
                continue
            if other.enabled is not True or other.role != candidate.role:
                continue
            if self._shares_navigation_family(candidate.label, other.label):
                return True
        return False

    def _shares_navigation_family(self, left: str, right: str) -> bool:
        left_tokens = set(_tokenize(left))
        right_tokens = set(_tokenize(right))
        if left_tokens & right_tokens:
            return True
        return SequenceMatcher(None, _normalize_text(left), _normalize_text(right)).ratio() >= 0.55

    def _is_blocking_message(self, text: str) -> bool:
        lowered = _normalize_text(text)
        return any(token in lowered for token in _STRONG_BLOCKER_TOKENS)

    def _looks_like_help_surface(self, *, observation: ScreenObservation, visible_text: str) -> bool:
        lowered = _normalize_text(visible_text)
        if any(token in lowered for token in _HELP_SURFACE_TOKENS):
            return True
        for item in observation.workspace_snapshot.get("opened_items") or []:
            if not isinstance(item, dict):
                continue
            item_text = _normalize_text(
                " ".join(
                    [
                        str(item.get("title") or item.get("name") or ""),
                        str(item.get("pane") or ""),
                        str(item.get("kind") or ""),
                    ]
                )
            )
            if any(token in item_text for token in _HELP_SURFACE_TOKENS):
                return True
        return False

    def _is_modal_surface(self, candidate: GroundingCandidate) -> bool:
        container_text = _normalize_text(
            " ".join(
                [
                    str(candidate.parent_container or ""),
                    str(candidate.semantic_metadata.get("pane") or ""),
                    str(candidate.semantic_metadata.get("container") or ""),
                    str(candidate.semantic_metadata.get("kind") or ""),
                ]
            )
        )
        return candidate.role == GroundingCandidateRole.POPUP or any(token in container_text for token in _MODAL_CONTAINER_TOKENS)

    def _is_modal_candidate(self, candidate: GroundingCandidate) -> bool:
        return self._is_modal_surface(candidate) or any(
            token in _normalize_text(str(candidate.parent_container or "")) for token in _MODAL_CONTAINER_TOKENS
        )

    def _is_stale_candidate(self, candidate: GroundingCandidate) -> bool:
        metadata = candidate.semantic_metadata
        return any(bool(metadata.get(key)) for key in _STALE_METADATA_KEYS)

    def _context_has_current_anchor(self, context: NavigationContext) -> bool:
        return bool(context.active_item_label)

    def _is_weak_navigation_request(self, *, request: NavigationRequest) -> bool:
        return (
            request.request_type in {NavigationRequestType.NEXT_STEP, NavigationRequestType.RECOVERY, NavigationRequestType.BLOCKER_CHECK}
            and not request.label_tokens
            and not request.role_descriptors
            and "deictic" not in request.mode_flags
        )

    def _blocker_recovery(self, blocker: NavigationBlocker) -> str:
        lowered = blocker.summary.lower()
        if "permission" in lowered:
            return "Address the visible permission prompt before looking for the next control."
        if "disabled" in lowered:
            return "Look for the requirement that enables that control before continuing."
        if "warning" in lowered or "error" in lowered or "failed" in lowered:
            return "Resolve the visible warning or error before taking the next step."
        return "Clear the visible blocker first, then reassess the next step."
