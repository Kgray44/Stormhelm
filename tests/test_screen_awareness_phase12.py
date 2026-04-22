from __future__ import annotations

from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import ScreenScenarioDefinition
from stormhelm.core.screen_awareness import ScreenScenarioEvaluator
from stormhelm.core.screen_awareness import ScreenScenarioExpectation
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem


class Phase12Probe:
    def __init__(self, *, focused_window: dict[str, object] | None = None, windows: list[dict[str, object]] | None = None) -> None:
        self._focused_window = focused_window
        self._windows = list(windows or ([focused_window] if focused_window else []))

    def window_status(self) -> dict[str, object]:
        return {
            "focused_window": self._focused_window,
            "windows": list(self._windows),
            "monitors": [{"index": 1, "device_name": "\\\\.\\DISPLAY1", "is_primary": True}],
        }


def _phase12_screen_config(temp_config):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase12"
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
    temp_config.screen_awareness.brain_integration_enabled = True
    temp_config.screen_awareness.power_features_enabled = True
    temp_config.screen_awareness.action_policy_mode = "confirm_before_act"
    return temp_config.screen_awareness


def test_phase12_service_emits_trace_audit_policy_and_recovery_surfaces(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase12_screen_config(temp_config),
        system_probe=Phase12Probe(
            focused_window={
                "process_name": "chrome",
                "window_title": "Deploy Dashboard - Google Chrome",
                "window_handle": 901,
                "pid": 4100,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="phase12-audit",
        operator_text="did anything change?",
        intent=ScreenIntentType.DETECT_VISIBLE_CHANGE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={"workspace": {"workspaceId": "ws-phase12", "title": "Deploy Dashboard"}},
        active_context={
            "selection": {
                "kind": "text",
                "value": "Deployment failed. Try again.",
                "preview": "Deployment failed. Try again.",
            },
            "clipboard": {},
        },
    )

    assert response.analysis.trace_id
    assert response.analysis.latency_trace is not None
    assert response.analysis.truthfulness_audit is not None
    assert response.analysis.policy_state is not None
    assert response.analysis.recovery_state is not None
    assert response.telemetry["trace"]["trace_id"] == response.analysis.trace_id
    assert response.telemetry["timing"]["total_duration_ms"] >= 0
    assert response.telemetry["truthfulness_audit"]["passed"] is True
    assert response.telemetry["policy"]["phase"] == "phase12"
    assert response.telemetry["recovery"]["status"] == "unresolved"

    snapshot = subsystem.status_snapshot()
    assert snapshot["hardening"]["enabled"] is True
    assert snapshot["hardening"]["recent_trace_count"] == 1
    assert snapshot["hardening"]["latest_trace"]["trace_id"] == response.analysis.trace_id


def test_phase12_scenario_evaluator_links_trace_and_explicit_assertions(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase12_screen_config(temp_config),
        system_probe=Phase12Probe(
            focused_window={
                "process_name": "chrome",
                "window_title": "PyInstaller Docs - Google Chrome",
                "window_handle": 902,
                "pid": 4200,
                "monitor_index": 1,
                "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "is_focused": True,
                "minimized": False,
            }
        ),
    )

    response = subsystem.handle_request(
        session_id="phase12-scenario",
        operator_text="what am I looking at",
        intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={
            "workspace": {"workspaceId": "ws-phase12-2", "title": "PyInstaller Research"},
            "active_item": {
                "itemId": "page-1",
                "title": "PyInstaller Docs",
                "url": "https://pyinstaller.org/en/stable/",
                "kind": "browser-tab",
            },
        },
        active_context={
            "selection": {
                "kind": "text",
                "value": "PyInstaller bundles a Python application into a single executable.",
                "preview": "PyInstaller bundles a Python application into a single executable.",
            },
            "clipboard": {},
        },
    )

    evaluator = ScreenScenarioEvaluator()
    result = evaluator.evaluate(
        definition=ScreenScenarioDefinition(
            scenario_id="phase12-scenario-1",
            title="Structured scenario audit",
            intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
            expectations=[
                ScreenScenarioExpectation(
                    name="trace id available",
                    evidence_path="analysis.trace_id",
                    contains="screen-",
                ),
                ScreenScenarioExpectation(
                    name="truthfulness audit passed",
                    evidence_path="telemetry.truthfulness_audit.passed",
                    equals=True,
                ),
                ScreenScenarioExpectation(
                    name="phase surfaced in policy",
                    evidence_path="telemetry.policy.phase",
                    equals="phase12",
                ),
                ScreenScenarioExpectation(
                    name="summary carries observed subject",
                    evidence_path="analysis.current_screen_context.summary",
                    contains="PyInstaller",
                ),
            ],
        ),
        response=response,
    )

    assert result.passed is True
    assert result.trace_id == response.analysis.trace_id
    assert len(result.checks) == 4
    assert all(check.passed for check in result.checks)
