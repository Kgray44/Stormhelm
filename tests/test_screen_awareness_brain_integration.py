from __future__ import annotations

from datetime import datetime, timezone

from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import ScreenObservation
from stormhelm.core.screen_awareness import ScreenObservationScope
from stormhelm.core.screen_awareness import ScreenSensitivityLevel
from stormhelm.core.screen_awareness import ScreenSourceType
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem


class SequencedObservationSource:
    name = "sequenced-phase10-observer"

    def __init__(self, observations: list[ScreenObservation]) -> None:
        self._observations = list(observations)

    def observe(
        self,
        *,
        session_id: str,
        surface_mode: str,
        active_module: str,
        active_context: dict[str, object],
        workspace_context: dict[str, object],
    ) -> ScreenObservation:
        del session_id, surface_mode, active_module, active_context, workspace_context
        if len(self._observations) > 1:
            return self._observations.pop(0)
        return self._observations[0]


def _phase10_screen_config(temp_config):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase10"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.debug_events_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
    temp_config.screen_awareness.adapters_enabled = True
    temp_config.screen_awareness.problem_solving_enabled = True
    temp_config.screen_awareness.workflow_learning_enabled = True
    temp_config.screen_awareness.brain_integration_enabled = True
    temp_config.screen_awareness.action_policy_mode = "confirm_before_act"
    return temp_config.screen_awareness


def _workspace_observation(
    *,
    title: str,
    workspace_snapshot: dict[str, object],
    selected_text: str | None = None,
    sensitivity: ScreenSensitivityLevel = ScreenSensitivityLevel.NORMAL,
) -> ScreenObservation:
    source_types = [ScreenSourceType.FOCUS_STATE, ScreenSourceType.WORKSPACE_CONTEXT]
    if selected_text:
        source_types.append(ScreenSourceType.SELECTION)
    return ScreenObservation(
        scope=ScreenObservationScope.ACTIVE_WINDOW,
        source_types_used=source_types,
        app_identity="chrome",
        window_metadata={"window_title": title},
        workspace_snapshot=workspace_snapshot,
        selected_text=selected_text,
        selection_metadata={"kind": "text"} if selected_text else {},
        focus_metadata={"window_title": title, "process_name": "chrome", "window_handle": 9311},
        sensitivity=sensitivity,
    )


def _screen_resolution(
    *,
    intent: str,
    analysis_result: dict[str, object],
    captured_at: str | None = None,
) -> dict[str, object]:
    resolution = {
        "kind": "screen_awareness",
        "intent": intent,
        "analysis_result": analysis_result,
    }
    if captured_at is not None:
        resolution["captured_at"] = captured_at
    return resolution


def _release_workflow_resolutions() -> list[dict[str, object]]:
    captured_at = datetime.now(timezone.utc).isoformat()
    return [
        _screen_resolution(
            intent="guide_navigation",
            captured_at=captured_at,
            analysis_result={
                "current_screen_context": {
                    "summary": "Chrome is focused on Release Form.",
                    "candidate_next_steps": ["Use Continue to move to review."],
                },
                "grounding_result": {
                    "winning_target": {
                        "candidate_id": "button-continue",
                        "label": "Continue",
                        "role": "button",
                        "source_channel": "workspace_context",
                        "source_type": "workspace_context",
                        "enabled": True,
                    },
                    "ambiguity_status": "resolved",
                    "confidence": {"score": 0.88, "level": "high", "note": "The visible footer CTA is well grounded."},
                    "provenance": {
                        "channels_used": ["workspace_context"],
                        "dominant_channel": "workspace_context",
                        "signal_names": ["opened_items"],
                    },
                    "explanation": {"summary": "The visible footer Continue button is the strongest grounded target."},
                },
                "navigation_result": {
                    "step_state": {
                        "status": "ready",
                        "current_step_summary": "The release form is ready for review.",
                        "expected_target_label": "Continue",
                        "on_path": True,
                        "blocked": False,
                        "wrong_page": False,
                        "reentry_possible": True,
                    },
                    "winning_candidate": {
                        "candidate_id": "button-continue",
                        "label": "Continue",
                        "role": "button",
                        "source_channel": "workspace_context",
                        "score": 0.86,
                    },
                    "guidance": {
                        "instruction": "Use Continue to move to review.",
                        "reasoning_summary": "The footer Continue button is the next likely control.",
                        "provenance_note": "Based on the current form state.",
                    },
                    "confidence": {"score": 0.84, "level": "high", "note": "Single strong next-step target."},
                    "provenance": {
                        "channels_used": ["workspace_context"],
                        "dominant_channel": "workspace_context",
                        "signal_names": ["Continue"],
                    },
                },
            },
        ),
        _screen_resolution(
            intent="verify_screen_state",
            captured_at=captured_at,
            analysis_result={
                "current_screen_context": {
                    "summary": "Chrome is focused on Review Step.",
                    "candidate_next_steps": ["Submit the release review."],
                },
                "verification_result": {
                    "completion_status": "completed",
                    "comparison": {
                        "basis": "prior_screen_bearing",
                        "basis_reason": "Verification reused a prior screen bearing.",
                        "comparison_ready": True,
                        "change_classification": "verified_change",
                        "summary": "The review step became visible after the Continue action.",
                    },
                    "explanation": {
                        "summary": "The review step is now visible after the Continue action.",
                    },
                    "confidence": {"score": 0.84, "level": "high", "note": "The follow-up screen state supports completion."},
                    "provenance": {
                        "channels_used": ["workspace_context"],
                        "dominant_channel": "workspace_context",
                        "signal_names": ["Review step"],
                    },
                },
            },
        ),
    ]


def test_phase10_binds_recent_screen_bearings_into_task_graph_session_memory_and_long_term_candidate(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase10_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Review Step - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase10-1", "title": "Release Workflow"},
                        "active_item": {"itemId": "review-step", "title": "Review Step", "kind": "step"},
                        "opened_items": [
                            {
                                "itemId": "button-submit",
                                "title": "Submit",
                                "kind": "button",
                                "pane": "footer",
                                "enabled": True,
                            }
                        ],
                    },
                )
            ]
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="remember this workflow for next time",
        intent=ScreenIntentType.BRAIN_INTEGRATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": _release_workflow_resolutions(),
        },
    )

    brain = response.analysis.brain_integration_result

    assert brain is not None
    assert brain.status.value == "candidate_created"
    assert brain.task_graph is not None
    assert len(brain.task_graph.nodes) >= 2
    assert len(brain.task_graph.links) >= 1
    assert brain.session_memory_entries
    assert brain.long_term_candidate is not None
    assert brain.binding_decision is not None
    assert brain.binding_decision.target_layer.value == "long_term_candidate"
    assert response.telemetry["brain_integration"]["requested"] is True
    assert response.telemetry["brain_integration"]["task_node_count"] >= 2
    assert response.telemetry["brain_integration"]["session_memory_count"] >= 1
    assert response.telemetry["brain_integration"]["binding_target"] == "long_term_candidate"
    assert "current evidence" in response.assistant_response.lower() or "candidate" in response.assistant_response.lower()


def test_phase10_defers_sensitive_workflow_binding_instead_of_promoting_it(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase10_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Secrets Review - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase10-2", "title": "Secrets Review"},
                        "active_item": {"itemId": "secrets-review", "title": "Secrets Review", "kind": "step"},
                        "opened_items": [],
                    },
                    selected_text="Token rotation checklist",
                    sensitivity=ScreenSensitivityLevel.RESTRICTED,
                )
            ]
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="remember this workflow for next time",
        intent=ScreenIntentType.BRAIN_INTEGRATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": _release_workflow_resolutions(),
        },
    )

    brain = response.analysis.brain_integration_result

    assert brain is not None
    assert brain.status.value == "deferred"
    assert brain.binding_decision is not None
    assert brain.binding_decision.privacy_blocked is True
    assert brain.binding_decision.target_layer.value in {"session_memory", "deferred"}
    assert brain.long_term_candidate is None
    assert response.telemetry["brain_integration"]["binding_target"] in {"session_memory", "deferred"}
    assert "sensitive" in response.assistant_response.lower() or "longer-lived memory" in response.assistant_response.lower()


def test_phase10_requires_repeat_support_before_learning_environment_quirk(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase10_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Installer Permissions - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase10-3", "title": "Installer"},
                        "active_item": {"itemId": "installer", "title": "Installer", "kind": "workflow"},
                        "opened_items": [],
                    },
                    selected_text="Administrator permission required",
                ),
                _workspace_observation(
                    title="Installer Permissions - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase10-3", "title": "Installer"},
                        "active_item": {"itemId": "installer", "title": "Installer", "kind": "workflow"},
                        "opened_items": [],
                    },
                    selected_text="Administrator permission required",
                ),
            ]
        ),
    )

    first = subsystem.handle_request(
        session_id="default",
        operator_text="learn that this environment behaves this way",
        intent=ScreenIntentType.BRAIN_INTEGRATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )
    second = subsystem.handle_request(
        session_id="default",
        operator_text="learn that this environment behaves this way",
        intent=ScreenIntentType.BRAIN_INTEGRATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    first_brain = first.analysis.brain_integration_result
    second_brain = second.analysis.brain_integration_result

    assert first_brain is not None
    assert first_brain.status.value == "deferred"
    assert first_brain.environment_quirk is None

    assert second_brain is not None
    assert second_brain.status.value == "quirk_learned"
    assert second_brain.environment_quirk is not None
    assert second_brain.environment_quirk.evidence_count >= 2
    assert second.telemetry["brain_integration"]["environment_quirk_id"] is not None
    assert second.telemetry["brain_integration"]["environment_quirk_evidence_count"] >= 2


def test_phase10_recalls_prior_context_with_proactive_continuity_without_treating_it_as_live_truth(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase10_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Review Step - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase10-4", "title": "Release Workflow"},
                        "active_item": {"itemId": "review-step", "title": "Review Step", "kind": "step"},
                        "opened_items": [],
                    },
                ),
                _workspace_observation(
                    title="Release Form - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase10-4", "title": "Release Workflow"},
                        "active_item": {"itemId": "release-form", "title": "Release Form", "kind": "form"},
                        "opened_items": [
                            {
                                "itemId": "button-continue",
                                "title": "Continue",
                                "kind": "button",
                                "pane": "footer",
                                "enabled": True,
                            }
                        ],
                    },
                ),
            ]
        ),
    )

    remembered = subsystem.handle_request(
        session_id="default",
        operator_text="remember this workflow for next time",
        intent=ScreenIntentType.BRAIN_INTEGRATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": _release_workflow_resolutions(),
        },
    )
    recalled = subsystem.handle_request(
        session_id="default",
        operator_text="bring back the context from last time",
        intent=ScreenIntentType.BRAIN_INTEGRATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    remembered_brain = remembered.analysis.brain_integration_result
    recalled_brain = recalled.analysis.brain_integration_result

    assert remembered_brain is not None
    assert remembered_brain.long_term_candidate is not None
    assert recalled_brain is not None
    assert recalled_brain.status.value == "context_recalled"
    assert recalled_brain.proactive_suggestion is not None
    assert recalled.telemetry["brain_integration"]["proactive_suggestion_present"] is True
    assert "looks like" in recalled.assistant_response.lower() or "earlier" in recalled.assistant_response.lower()
    assert "definitely" not in recalled.assistant_response.lower()


def test_phase10_refuses_to_merge_weakly_related_workflows_on_recall(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase10_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Review Step - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase10-5a", "title": "Release Workflow"},
                        "active_item": {"itemId": "review-step", "title": "Review Step", "kind": "step"},
                        "opened_items": [],
                    },
                ),
                _workspace_observation(
                    title="Account Settings - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase10-5b", "title": "Account Settings"},
                        "active_item": {"itemId": "settings-root", "title": "Account Settings", "kind": "settings-page"},
                        "opened_items": [
                            {
                                "itemId": "button-save",
                                "title": "Save",
                                "kind": "button",
                                "pane": "footer",
                                "enabled": True,
                            }
                        ],
                    },
                ),
            ]
        ),
    )

    remembered = subsystem.handle_request(
        session_id="default",
        operator_text="remember this workflow for next time",
        intent=ScreenIntentType.BRAIN_INTEGRATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": _release_workflow_resolutions(),
        },
    )
    recalled = subsystem.handle_request(
        session_id="default",
        operator_text="this looks like the same project as before",
        intent=ScreenIntentType.BRAIN_INTEGRATION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    remembered_brain = remembered.analysis.brain_integration_result
    recalled_brain = recalled.analysis.brain_integration_result

    assert remembered_brain is not None
    assert remembered_brain.long_term_candidate is not None
    assert recalled_brain is not None
    assert recalled_brain.status.value in {"deferred", "refused"}
    assert recalled_brain.proactive_suggestion is None
    assert recalled_brain.task_graph is not None
    assert recalled_brain.task_graph.graph_id != remembered_brain.long_term_candidate.source_task_graph_id
    assert "can't" in recalled.assistant_response.lower() or "don't" in recalled.assistant_response.lower()
