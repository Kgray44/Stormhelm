from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def _phase6_screen_config(temp_config):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase6"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
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
        focus_metadata={"window_title": title, "process_name": "chrome", "window_handle": 9101},
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


def test_phase6_continuity_resumes_recent_flow_with_grounded_resume_candidate(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase6_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Release Form - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-cont-1", "title": "Release Form"},
                        "active_item": {
                            "itemId": "field-email",
                            "title": "Release email",
                            "kind": "text-field",
                            "focused": True,
                        },
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
                )
            ]
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="continue where we left off",
        intent=ScreenIntentType.CONTINUE_WORKFLOW,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [
                _screen_resolution(
                    intent="guide_navigation",
                    captured_at=datetime.now(timezone.utc).isoformat(),
                    analysis_result={
                        "current_screen_context": {
                            "summary": "Chrome is focused on Release Form.",
                            "candidate_next_steps": ["Continue to the review step."],
                        },
                        "grounding_result": {
                            "winning_target": {
                                "candidate_id": "button-continue",
                                "label": "Continue",
                                "role": "button",
                                "source_channel": "workspace_context",
                            },
                            "ambiguity_status": "resolved",
                            "confidence": {"score": 0.89, "level": "high", "note": "Focused footer CTA remains visible."},
                            "provenance": {
                                "channels_used": ["workspace_context"],
                                "dominant_channel": "workspace_context",
                                "signal_names": ["opened_items"],
                            },
                        },
                        "navigation_result": {
                            "step_state": {
                                "status": "ready",
                                "current_step_summary": "The form is ready to continue.",
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
                                "instruction": "Continue to the review step.",
                                "reasoning_summary": "The footer Continue button is the next likely control.",
                                "provenance_note": "Based on the current form state.",
                            },
                            "confidence": {"score": 0.84, "level": "high", "note": "Single strong next-step target."},
                        },
                        "verification_result": {
                            "completion_status": "not_completed",
                            "comparison": {
                                "basis": "current_state_only",
                                "prior_state_available": False,
                                "comparison_ready": False,
                                "change_classification": "insufficient_evidence",
                            },
                        },
                    },
                )
            ],
        },
    )

    continuity = response.analysis.continuity_result

    assert continuity is not None
    assert continuity.status.value == "resume_ready"
    assert continuity.resume_candidate is not None
    assert continuity.resume_candidate.label == "Continue"
    assert continuity.planner_result is not None
    assert continuity.planner_result.resume_candidate_id == "button-continue"
    assert response.telemetry["continuity"]["outcome"] == "resume_ready"
    assert response.telemetry["continuity"]["navigation_reused"] is True
    assert response.telemetry["continuity"]["grounding_reused"] is True
    assert "continue" in response.assistant_response.lower()


def test_phase6_continuity_detects_popup_detour_and_offers_recovery(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase6_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Permissions Prompt - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-cont-2", "title": "Release Form"},
                        "active_item": {
                            "itemId": "permissions-dialog",
                            "title": "Permissions required",
                            "kind": "dialog",
                        },
                        "opened_items": [
                            {
                                "itemId": "permissions-dialog",
                                "title": "Permissions required",
                                "kind": "dialog",
                                "pane": "modal",
                                "enabled": True,
                            },
                            {
                                "itemId": "button-allow",
                                "title": "Allow",
                                "kind": "button",
                                "pane": "modal-footer",
                                "enabled": True,
                            },
                        ],
                    },
                )
            ]
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="this popup interrupted me, what now?",
        intent=ScreenIntentType.CONTINUE_WORKFLOW,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [
                _screen_resolution(
                    intent="guide_navigation",
                    captured_at=datetime.now(timezone.utc).isoformat(),
                    analysis_result={
                        "current_screen_context": {
                            "summary": "Chrome is focused on Release Form.",
                            "candidate_next_steps": ["Use Continue after the required permission step."],
                        },
                        "navigation_result": {
                            "step_state": {
                                "status": "ready",
                                "current_step_summary": "The form is ready to continue.",
                                "expected_target_label": "Continue",
                                "on_path": True,
                                "blocked": False,
                                "wrong_page": False,
                                "reentry_possible": True,
                            },
                            "guidance": {
                                "instruction": "Use Continue after the required permission step.",
                                "reasoning_summary": "Continue is still the next likely control once the modal is resolved.",
                            },
                        },
                    },
                )
            ],
        },
    )

    continuity = response.analysis.continuity_result

    assert continuity is not None
    assert continuity.status.value == "recovery_ready"
    assert continuity.detour_state is not None
    assert continuity.detour_state.active is True
    assert continuity.detour_state.detour_type == "popup_detour"
    assert continuity.recovery_hint is not None
    assert "continue" in continuity.recovery_hint.summary.lower()
    assert response.telemetry["continuity"]["detour_active"] is True
    assert response.telemetry["continuity"]["outcome"] == "recovery_ready"
    assert "popup" in response.assistant_response.lower() or "dialog" in response.assistant_response.lower()


def test_phase6_continuity_refuses_stale_basis_and_preserves_uncertainty(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase6_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="General Settings - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-cont-3", "title": "General Settings"},
                        "active_item": {
                            "itemId": "general-settings",
                            "title": "General Settings",
                            "kind": "settings-page",
                        },
                    },
                )
            ]
        ),
    )

    stale_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    response = subsystem.handle_request(
        session_id="default",
        operator_text="continue where we left off",
        intent=ScreenIntentType.CONTINUE_WORKFLOW,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [
                _screen_resolution(
                    intent="guide_navigation",
                    captured_at=stale_time,
                    analysis_result={
                        "current_screen_context": {"summary": "Chrome is focused on Release Form."},
                        "navigation_result": {
                            "step_state": {
                                "status": "ready",
                                "current_step_summary": "The form is ready to continue.",
                                "expected_target_label": "Continue",
                            },
                            "guidance": {"instruction": "Continue to the review step."},
                        },
                    },
                )
            ],
        },
    )

    continuity = response.analysis.continuity_result

    assert continuity is not None
    assert continuity.status.value == "weak_basis"
    assert continuity.resume_candidate is None
    assert continuity.clarification_needed is True
    assert response.telemetry["continuity"]["outcome"] == "weak_basis"
    assert response.telemetry["continuity"]["resume_candidate_id"] is None
    assert "can't justify" in response.assistant_response.lower() or "don't have enough recent evidence" in response.assistant_response.lower()


def test_phase6_continuity_preserves_ambiguity_when_multiple_resume_paths_remain_plausible(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase6_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Checkout - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-cont-4", "title": "Checkout"},
                        "active_item": {
                            "itemId": "checkout-page",
                            "title": "Checkout",
                            "kind": "settings-page",
                        },
                    },
                )
            ]
        ),
    )

    now = datetime.now(timezone.utc)
    response = subsystem.handle_request(
        session_id="default",
        operator_text="continue where we left off",
        intent=ScreenIntentType.CONTINUE_WORKFLOW,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [
                _screen_resolution(
                    intent="guide_navigation",
                    captured_at=now.isoformat(),
                    analysis_result={
                        "current_screen_context": {"summary": "Chrome is focused on Checkout."},
                        "navigation_result": {
                            "step_state": {
                                "status": "ready",
                                "current_step_summary": "Shipping details are ready.",
                                "expected_target_label": "Continue",
                            },
                            "winning_candidate": {
                                "candidate_id": "button-continue",
                                "label": "Continue",
                                "role": "button",
                                "source_channel": "workspace_context",
                                "score": 0.74,
                            },
                        },
                    },
                ),
                _screen_resolution(
                    intent="guide_navigation",
                    captured_at=(now - timedelta(seconds=20)).isoformat(),
                    analysis_result={
                        "current_screen_context": {"summary": "Chrome is focused on Checkout."},
                        "navigation_result": {
                            "step_state": {
                                "status": "ready",
                                "current_step_summary": "Payment details are ready.",
                                "expected_target_label": "Review order",
                            },
                            "winning_candidate": {
                                "candidate_id": "button-review",
                                "label": "Review order",
                                "role": "button",
                                "source_channel": "workspace_context",
                                "score": 0.72,
                            },
                        },
                    },
                ),
            ],
        },
    )

    continuity = response.analysis.continuity_result

    assert continuity is not None
    assert continuity.status.value == "ambiguous"
    assert continuity.resume_candidate is None
    assert len(continuity.resume_options) >= 2
    assert response.telemetry["continuity"]["outcome"] == "ambiguous"
    assert response.telemetry["continuity"]["candidate_count"] >= 2
    assert "two plausible" in response.assistant_response.lower() or "multiple plausible" in response.assistant_response.lower()


def test_phase6_continuity_detects_backtracking_and_offers_bounded_undo_hint(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase6_screen_config(temp_config),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Account Overview - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-cont-5", "title": "Account Overview"},
                        "active_item": {
                            "itemId": "account-overview",
                            "title": "Account Overview",
                            "kind": "settings-page",
                        },
                        "opened_items": [
                            {
                                "itemId": "button-back",
                                "title": "Back",
                                "kind": "button",
                                "pane": "toolbar",
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
        operator_text="I think I went backward, where was I supposed to be?",
        intent=ScreenIntentType.CONTINUE_WORKFLOW,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {},
            "clipboard": {},
            "recent_context_resolutions": [
                _screen_resolution(
                    intent="guide_navigation",
                    captured_at=datetime.now(timezone.utc).isoformat(),
                    analysis_result={
                        "current_screen_context": {"summary": "Chrome is focused on Security Settings."},
                        "navigation_result": {
                            "step_state": {
                                "status": "ready",
                                "current_step_summary": "Security Settings was the active step.",
                                "expected_target_label": "Continue",
                            },
                            "winning_candidate": {
                                "candidate_id": "button-continue",
                                "label": "Continue",
                                "role": "button",
                                "source_channel": "workspace_context",
                                "score": 0.78,
                            },
                        },
                    },
                )
            ],
        },
    )

    continuity = response.analysis.continuity_result

    assert continuity is not None
    assert continuity.status.value == "recovery_ready"
    assert continuity.recovery_hint is not None
    assert continuity.recovery_hint.bounded_undo_hint is True
    assert "continue" in continuity.recovery_hint.summary.lower()
    assert response.telemetry["continuity"]["outcome"] == "recovery_ready"
