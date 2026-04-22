from __future__ import annotations

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


def _phase5_screen_config(temp_config, *, action_policy_mode: str = "trusted_action"):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase5"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
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
        focus_metadata={"window_title": title, "process_name": "chrome", "window_handle": 9001},
        sensitivity=sensitivity,
    )


def test_phase5_action_executes_grounded_click_and_verifies_visible_success(temp_config) -> None:
    executor = FakeActionExecutor()
    subsystem = build_screen_awareness_subsystem(
        _phase5_screen_config(temp_config, action_policy_mode="trusted_action"),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Deploy Settings - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-act-1", "title": "Deploy Settings"},
                        "active_item": {"itemId": "settings-page", "title": "Deploy Settings", "kind": "settings-page"},
                        "opened_items": [
                            {
                                "itemId": "button-save",
                                "title": "Save",
                                "kind": "button",
                                "pane": "footer",
                                "enabled": True,
                                "bounds": {"left": 120, "top": 220, "width": 90, "height": 32},
                            }
                        ],
                    },
                ),
                _workspace_observation(
                    title="Deploy Settings - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-act-1", "title": "Deploy Settings"},
                        "active_item": {
                            "itemId": "save-success",
                            "title": "Saved successfully",
                            "kind": "status-banner",
                        },
                        "opened_items": [
                            {
                                "itemId": "button-save",
                                "title": "Save",
                                "kind": "button",
                                "pane": "footer",
                                "enabled": True,
                                "bounds": {"left": 120, "top": 220, "width": 90, "height": 32},
                            }
                        ],
                    },
                ),
            ]
        ),
        action_executor=executor,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="click the Save button",
        intent=ScreenIntentType.EXECUTE_UI_ACTION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    action = response.analysis.action_result

    assert action is not None
    assert action.status.value == "verified_success"
    assert action.gate.allowed is True
    assert action.plan.target is not None
    assert action.plan.target.label == "Save"
    assert action.attempt is not None
    assert action.post_action_verification is not None
    assert action.post_action_verification.completion_status.value == "completed"
    assert len(executor.calls) == 1
    assert response.telemetry["action"]["outcome"] == "verified_success"
    assert response.telemetry["action"]["attempted"] is True
    assert response.telemetry["action"]["post_action_verification_status"] == "completed"


def test_phase5_action_preserves_ambiguity_and_refuses_execution(temp_config) -> None:
    executor = FakeActionExecutor()
    subsystem = build_screen_awareness_subsystem(
        _phase5_screen_config(temp_config, action_policy_mode="trusted_action"),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Shipping Wizard - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-act-2", "title": "Shipping Wizard"},
                        "active_item": {"itemId": "wizard-page", "title": "Shipping Wizard", "kind": "settings-page"},
                        "opened_items": [
                            {
                                "itemId": "button-continue-top",
                                "title": "Continue",
                                "kind": "button",
                                "pane": "toolbar",
                                "enabled": True,
                                "bounds": {"left": 80, "top": 90, "width": 110, "height": 30},
                            },
                            {
                                "itemId": "button-continue-bottom",
                                "title": "Continue",
                                "kind": "button",
                                "pane": "footer",
                                "enabled": True,
                                "bounds": {"left": 420, "top": 620, "width": 110, "height": 30},
                            },
                        ],
                    },
                )
            ]
        ),
        action_executor=executor,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="click Continue",
        intent=ScreenIntentType.EXECUTE_UI_ACTION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    action = response.analysis.action_result

    assert action is not None
    assert action.status.value == "ambiguous"
    assert action.gate.allowed is False
    assert action.gate.outcome == "ambiguous"
    assert executor.calls == []
    assert response.telemetry["action"]["outcome"] == "ambiguous"
    assert response.telemetry["action"]["attempted"] is False


def test_phase5_action_refuses_disabled_target_as_blocked(temp_config) -> None:
    executor = FakeActionExecutor()
    subsystem = build_screen_awareness_subsystem(
        _phase5_screen_config(temp_config, action_policy_mode="trusted_action"),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Deploy Settings - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-act-3", "title": "Deploy Settings"},
                        "active_item": {"itemId": "settings-page", "title": "Deploy Settings", "kind": "settings-page"},
                        "opened_items": [
                            {
                                "itemId": "button-save",
                                "title": "Save",
                                "kind": "button",
                                "pane": "footer",
                                "enabled": False,
                                "bounds": {"left": 120, "top": 220, "width": 90, "height": 32},
                            }
                        ],
                    },
                )
            ]
        ),
        action_executor=executor,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="click Save",
        intent=ScreenIntentType.EXECUTE_UI_ACTION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    action = response.analysis.action_result

    assert action is not None
    assert action.status.value == "blocked"
    assert action.gate.allowed is False
    assert action.gate.outcome == "blocked"
    assert executor.calls == []
    assert response.telemetry["action"]["outcome"] == "blocked"


def test_phase5_action_reports_attempted_but_unverified_when_post_action_signal_stays_weak(temp_config) -> None:
    executor = FakeActionExecutor()
    subsystem = build_screen_awareness_subsystem(
        _phase5_screen_config(temp_config, action_policy_mode="trusted_action"),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Deploy Settings - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-act-4", "title": "Deploy Settings"},
                        "active_item": {"itemId": "settings-page", "title": "Deploy Settings", "kind": "settings-page"},
                        "opened_items": [
                            {
                                "itemId": "button-save",
                                "title": "Save",
                                "kind": "button",
                                "pane": "footer",
                                "enabled": True,
                                "bounds": {"left": 120, "top": 220, "width": 90, "height": 32},
                            }
                        ],
                    },
                ),
                _workspace_observation(
                    title="Deploy Settings - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-act-4", "title": "Deploy Settings"},
                        "active_item": {"itemId": "settings-page", "title": "Deploy Settings", "kind": "settings-page"},
                        "opened_items": [
                            {
                                "itemId": "button-save",
                                "title": "Save",
                                "kind": "button",
                                "pane": "footer",
                                "enabled": True,
                                "bounds": {"left": 120, "top": 220, "width": 90, "height": 32},
                            }
                        ],
                    },
                ),
            ]
        ),
        action_executor=executor,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="click the Save button",
        intent=ScreenIntentType.EXECUTE_UI_ACTION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    action = response.analysis.action_result

    assert action is not None
    assert action.status.value == "attempted_unverified"
    assert action.attempt is not None
    assert action.post_action_verification is not None
    assert action.post_action_verification.completion_status.value != "completed"
    assert len(executor.calls) == 1
    assert response.telemetry["action"]["outcome"] == "attempted_unverified"
    assert response.telemetry["action"]["post_action_verification_status"] != "completed"


def test_phase5_action_redacts_sensitive_typed_input_and_refuses_execution(temp_config) -> None:
    executor = FakeActionExecutor()
    subsystem = build_screen_awareness_subsystem(
        _phase5_screen_config(temp_config, action_policy_mode="trusted_action"),
        observation_source=SequencedObservationSource(
            [
                _workspace_observation(
                    title="Security Settings - Google Chrome",
                    workspace_snapshot={
                        "workspace": {"workspaceId": "ws-act-5", "title": "Security Settings"},
                        "active_item": {
                            "itemId": "field-password",
                            "title": "Password",
                            "kind": "text-field",
                            "focused": True,
                            "selected": True,
                            "bounds": {"left": 140, "top": 240, "width": 240, "height": 28},
                        },
                        "opened_items": [
                            {
                                "itemId": "field-password",
                                "title": "Password",
                                "kind": "text-field",
                                "focused": True,
                                "selected": True,
                                "bounds": {"left": 140, "top": 240, "width": 240, "height": 28},
                            }
                        ],
                    },
                    sensitivity=ScreenSensitivityLevel.RESTRICTED,
                )
            ]
        ),
        action_executor=executor,
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="type hunter2 into the password field",
        intent=ScreenIntentType.EXECUTE_UI_ACTION,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={"selection": {}, "clipboard": {}},
    )

    action = response.analysis.action_result

    assert action is not None
    assert action.status.value == "gated"
    assert action.gate.allowed is False
    assert action.gate.risk_level.value == "restricted"
    assert action.plan.text_payload_redacted is True
    assert executor.calls == []
    assert response.telemetry["action"]["text_payload_redacted"] is True
    assert "hunter2" not in response.assistant_response.lower()

