from __future__ import annotations

from datetime import datetime, timezone

from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import ScreenObservation
from stormhelm.core.screen_awareness import ScreenObservationScope
from stormhelm.core.screen_awareness import ScreenSensitivityLevel
from stormhelm.core.screen_awareness import ScreenSourceType
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem


class SequencedObservationSource:
    name = "sequenced-test-observer"

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


class FakeActionExecutor:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def execute_plan(self, *, plan: object) -> dict[str, object]:
        self.calls.append(plan)
        return {"success": True, "driver": "fake"}


def _phase9_screen_config(temp_config, *, action_policy_mode: str = "confirm_before_act"):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase9"
    temp_config.screen_awareness.planner_routing_enabled = True
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
    temp_config.screen_awareness.action_policy_mode = action_policy_mode
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
        focus_metadata={"window_title": title, "process_name": "chrome", "window_handle": 9201},
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
            intent="execute_ui_action",
            captured_at=captured_at,
            analysis_result={
                "current_screen_context": {
                    "summary": "Chrome is focused on Release Form.",
                },
                "action_result": {
                    "status": "verified_success",
                    "request": {"intent": "click"},
                    "plan": {
                        "action_intent": "click",
                        "target": {
                            "candidate_id": "button-continue",
                            "label": "Continue",
                            "role": "button",
                            "source_channel": "workspace_context",
                            "source_type": "workspace_context",
                            "enabled": True,
                            "semantic_metadata": {"pane": "footer"},
                        },
                        "preview_summary": "Stormhelm can click on the button \"Continue\".",
                        "grounding_reused": True,
                        "navigation_reused": True,
                        "verification_reused": True,
                        "text_payload_redacted": False,
                    },
                    "confidence": {"score": 0.82, "level": "high", "note": "The action target is strongly grounded."},
                    "planner_result": {
                        "resolved": True,
                        "execution_status": "verified_success",
                    },
                    "provenance": {
                        "channels_used": ["workspace_context"],
                        "dominant_channel": "workspace_context",
                        "signal_names": ["Continue"],
                    },
                    "explanation_summary": "Stormhelm executed the planned UI action and the follow-up verification bearing supports success.",
                },
                "verification_result": {
                    "completion_status": "completed",
                    "comparison": {
                        "basis": "prior_screen_bearing",
                        "basis_reason": "Action verification reused a prior screen bearing.",
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


def test_phase9_starts_bounded_workflow_observation_session(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase9_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Release Form - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase9-1", "title": "Release Form"},
                        "active_item": {"itemId": "release-form", "title": "Release Form", "kind": "form"},
                        "opened_items": [],
                    },
                )
            ]
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="watch me do this and remember the workflow",
        intent=ScreenIntentType.LEARN_WORKFLOW_REUSE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    workflow = response.analysis.workflow_learning_result

    assert workflow is not None
    assert workflow.status.value == "observing"
    assert workflow.observation_session is not None
    assert workflow.observation_session.active is True
    assert response.telemetry["workflow_learning"]["requested"] is True
    assert response.telemetry["workflow_learning"]["outcome"] == "observing"
    assert "workflow" in response.assistant_response.lower()


def test_phase9_saves_reusable_workflow_from_recent_screen_bearings(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase9_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Release Form - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase9-2", "title": "Release Form"},
                        "active_item": {"itemId": "release-form", "title": "Release Form", "kind": "form"},
                        "opened_items": [],
                    },
                ),
                _workspace_observation(
                    title="Release Form - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase9-2", "title": "Release Form"},
                        "active_item": {"itemId": "release-form", "title": "Release Form", "kind": "form"},
                        "opened_items": [],
                    },
                ),
            ]
        ),
    )

    subsystem.handle_request(
        session_id="default",
        operator_text="watch me do this and remember the workflow",
        intent=ScreenIntentType.LEARN_WORKFLOW_REUSE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="save this process",
        intent=ScreenIntentType.LEARN_WORKFLOW_REUSE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": _release_workflow_resolutions(),
        },
    )

    workflow = response.analysis.workflow_learning_result

    assert workflow is not None
    assert workflow.status.value == "reusable_accepted"
    assert workflow.reusable_workflow is not None
    assert workflow.reusable_workflow.step_sequence.steps
    assert workflow.reusable_workflow.label.primary_label
    assert response.telemetry["workflow_learning"]["capture_status"] == "reusable_accepted"
    assert response.telemetry["workflow_learning"]["stored_workflow_count"] >= 1


def test_phase9_strong_match_reuses_existing_action_path_without_bypassing_verification(temp_config) -> None:
    executor = FakeActionExecutor()
    subsystem = build_screen_awareness_subsystem(
        _phase9_screen_config(temp_config, action_policy_mode="trusted_action"),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Release Form - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase9-3", "title": "Release Form"},
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
                _workspace_observation(
                    title="Release Form - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase9-3", "title": "Release Form"},
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
                _workspace_observation(
                    title="Release Form - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase9-3", "title": "Release Form"},
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
                _workspace_observation(
                    title="Review Step - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase9-3", "title": "Release Form"},
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
                ),
            ]
        ),
        action_executor=executor,
    )

    subsystem.handle_request(
        session_id="default",
        operator_text="watch me do this and remember the workflow",
        intent=ScreenIntentType.LEARN_WORKFLOW_REUSE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )
    subsystem.handle_request(
        session_id="default",
        operator_text="save this process",
        intent=ScreenIntentType.LEARN_WORKFLOW_REUSE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": _release_workflow_resolutions(),
        },
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="can you do that same workflow again?",
        intent=ScreenIntentType.LEARN_WORKFLOW_REUSE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    workflow = response.analysis.workflow_learning_result
    action = response.analysis.action_result

    assert workflow is not None
    assert workflow.match_result is not None
    assert workflow.match_result.status.value == "strong_match"
    assert workflow.reuse_plan is not None
    assert workflow.reuse_plan.navigation_reused is True
    assert workflow.reuse_plan.verification_reused is True
    assert action is not None
    assert action.status.value in {"verified_success", "attempted_unverified"}
    assert len(executor.calls) == 1
    assert response.telemetry["workflow_learning"]["match_status"] == "strong_match"
    assert response.telemetry["workflow_learning"]["attempted_reuse"] is True
    assert response.telemetry["workflow_learning"]["reused_action_path"] is True


def test_phase9_weak_match_downgrades_reuse_instead_of_claiming_equivalence(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase9_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Account Settings - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase9-4", "title": "Account Settings"},
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
                _workspace_observation(
                    title="Account Settings - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-phase9-4", "title": "Account Settings"},
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

    subsystem.handle_request(
        session_id="default",
        operator_text="watch me do this and remember the workflow",
        intent=ScreenIntentType.LEARN_WORKFLOW_REUSE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )
    subsystem.handle_request(
        session_id="default",
        operator_text="save this process",
        intent=ScreenIntentType.LEARN_WORKFLOW_REUSE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": _release_workflow_resolutions(),
        },
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="reuse the steps from that prior task",
        intent=ScreenIntentType.LEARN_WORKFLOW_REUSE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    workflow = response.analysis.workflow_learning_result

    assert workflow is not None
    assert workflow.match_result is not None
    assert workflow.match_result.status.value in {"downgraded_match", "refused"}
    assert response.analysis.action_result is None
    assert response.telemetry["workflow_learning"]["attempted_reuse"] is False
    assert response.telemetry["workflow_learning"]["outcome"] in {"downgraded_match", "refused"}
    assert "can't" in response.assistant_response.lower() or "different" in response.assistant_response.lower()
