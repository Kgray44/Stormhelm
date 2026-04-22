from __future__ import annotations

from stormhelm.core.screen_awareness import ExplanationMode
from stormhelm.core.screen_awareness import ProblemAmbiguityState
from stormhelm.core.screen_awareness import ProblemAnswerStatus
from stormhelm.core.screen_awareness import ScreenArtifactKind
from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import ScreenProblemType
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem


class FakeObservationProbe:
    def __init__(self, *, focused_window: dict[str, object] | None = None, windows: list[dict[str, object]] | None = None) -> None:
        self._focused_window = focused_window
        self._windows = list(windows or ([focused_window] if focused_window else []))

    def window_status(self) -> dict[str, object]:
        return {
            "focused_window": self._focused_window,
            "windows": list(self._windows),
            "monitors": [{"index": 1, "device_name": "\\\\.\\DISPLAY1", "is_primary": True}],
        }


def _phase8_screen_config(temp_config, *, action_policy_mode: str = "confirm_before_act"):
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase8"
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
    temp_config.screen_awareness.action_policy_mode = action_policy_mode
    return temp_config.screen_awareness


def _focused_window(*, process_name: str, title: str, window_handle: int) -> dict[str, object]:
    return {
        "process_name": process_name,
        "window_title": title,
        "window_handle": window_handle,
        "pid": 8000 + window_handle,
        "monitor_index": 1,
        "path": f"C:\\Program Files\\{process_name}\\{process_name}.exe",
        "is_focused": True,
        "minimized": False,
    }


def _browser_semantics(
    *,
    page_title: str,
    url: str,
    validation_messages: list[str] | None = None,
    form_fields: list[dict[str, object]] | None = None,
    freshness_seconds: float = 2.0,
) -> dict[str, object]:
    return {
        "page": {"title": page_title, "url": url},
        "tab": {"title": page_title, "index": 1, "active": True},
        "loading_state": "complete",
        "freshness_seconds": freshness_seconds,
        "validation_messages": list(validation_messages or []),
        "form_fields": list(form_fields or []),
    }


def test_phase8_error_triage_explains_visible_name_error_without_claiming_hidden_root_cause(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase8_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_window(
                process_name="code",
                title="main.py - Visual Studio Code",
                window_handle=1001,
            )
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what does this error mean?",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {
                "kind": "text",
                "value": "NameError: name 'foo' is not defined",
                "preview": "NameError: name 'foo' is not defined",
            },
            "clipboard": {},
        },
    )

    problem = response.analysis.problem_solving_result

    assert problem is not None
    assert problem.problem_type == ScreenProblemType.CODE_ERROR
    assert problem.artifact_kind == ScreenArtifactKind.CODE
    assert problem.explanation_mode == ExplanationMode.CONCISE_EXPLANATION
    assert problem.answer_status == ProblemAnswerStatus.EXPLANATION_ONLY
    assert problem.ambiguity_state == ProblemAmbiguityState.CLEAR
    assert problem.triage is not None
    assert "nameerror" in (problem.triage.classification or "").lower()
    assert "python" in response.assistant_response.lower()
    assert "foo" in response.assistant_response
    assert "definitely" not in response.assistant_response.lower()
    assert response.telemetry["problem_solving"]["outcome"] == "resolved"


def test_phase8_visible_problem_solving_preserves_partial_honesty_for_truncated_statement(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase8_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_window(
                process_name="chrome",
                title="Homework Portal - Google Chrome",
                window_handle=1002,
            )
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="can you solve this?",
        intent=ScreenIntentType.SOLVE_VISIBLE_PROBLEM,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {
                "kind": "text",
                "value": "A 10 ohm resistor is connected in series with ...",
                "preview": "A 10 ohm resistor is connected in series with ...",
            },
            "clipboard": {},
        },
    )

    problem = response.analysis.problem_solving_result

    assert problem is not None
    assert problem.answer_status == ProblemAnswerStatus.PARTIAL
    assert problem.ambiguity_state in {
        ProblemAmbiguityState.PARTIAL,
        ProblemAmbiguityState.INSUFFICIENT_EVIDENCE,
    }
    assert response.telemetry["problem_solving"]["refusal_reason"] == "truncated_visible_problem"
    assert "partial" in response.assistant_response.lower() or "can't justify an exact solution" in response.assistant_response.lower()


def test_phase8_teaching_modes_change_response_shape_without_changing_grounded_problem(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase8_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_window(
                process_name="chrome",
                title="Homework Portal - Google Chrome",
                window_handle=1003,
            )
        ),
    )

    direct = subsystem.handle_request(
        session_id="default",
        operator_text="can you solve this?",
        intent=ScreenIntentType.SOLVE_VISIBLE_PROBLEM,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {"kind": "text", "value": "12 * (3 + 4)", "preview": "12 * (3 + 4)"},
            "clipboard": {},
        },
    )
    stepped = subsystem.handle_request(
        session_id="default",
        operator_text="walk me through this problem step by step",
        intent=ScreenIntentType.SOLVE_VISIBLE_PROBLEM,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {"kind": "text", "value": "12 * (3 + 4)", "preview": "12 * (3 + 4)"},
            "clipboard": {},
        },
    )
    stressed = subsystem.handle_request(
        session_id="default",
        operator_text="explain this like i'm stressed",
        intent=ScreenIntentType.SOLVE_VISIBLE_PROBLEM,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {"kind": "text", "value": "12 * (3 + 4)", "preview": "12 * (3 + 4)"},
            "clipboard": {},
        },
    )

    direct_problem = direct.analysis.problem_solving_result
    stepped_problem = stepped.analysis.problem_solving_result
    stressed_problem = stressed.analysis.problem_solving_result

    assert direct_problem is not None
    assert stepped_problem is not None
    assert stressed_problem is not None
    assert direct_problem.problem_type == stepped_problem.problem_type == stressed_problem.problem_type == ScreenProblemType.EQUATION_SOLVE
    assert direct_problem.explanation_mode == ExplanationMode.DIRECT_ANSWER
    assert stepped_problem.explanation_mode == ExplanationMode.STEP_BY_STEP
    assert stressed_problem.explanation_mode == ExplanationMode.STRESSED_USER
    assert "84" in direct.assistant_response
    assert "1." in stepped.assistant_response
    assert "important part" in stressed.assistant_response.lower() or "start with" in stressed.assistant_response.lower()


def test_phase8_chart_interpretation_stays_bounded_and_truthful(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase8_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_window(
                process_name="chrome",
                title="Metrics Dashboard - Google Chrome",
                window_handle=1004,
            )
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="explain this chart on my screen",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {
                "kind": "text",
                "value": "Chart: Requests by hour\nX-axis: Hour\nY-axis: Requests\nBars: 10, 18, 31, 29",
                "preview": "Chart: Requests by hour X-axis: Hour Y-axis: Requests Bars: 10, 18, 31, 29",
            },
            "clipboard": {},
        },
    )

    problem = response.analysis.problem_solving_result

    assert problem is not None
    assert problem.artifact_kind == ScreenArtifactKind.CHART
    assert problem.answer_status in {ProblemAnswerStatus.APPROXIMATE, ProblemAnswerStatus.EXPLANATION_ONLY}
    assert "trend" in response.assistant_response.lower() or "rises" in response.assistant_response.lower()
    assert "definitely" not in response.assistant_response.lower()


def test_phase8_adapter_backed_validation_error_reuses_adapter_and_native_evidence(temp_config) -> None:
    subsystem = build_screen_awareness_subsystem(
        _phase8_screen_config(temp_config),
        system_probe=FakeObservationProbe(
            focused_window=_focused_window(
                process_name="chrome",
                title="Sign in - Google Chrome",
                window_handle=1005,
            )
        ),
    )

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what does this error mean?",
        intent=ScreenIntentType.EXPLAIN_VISIBLE_CONTENT,
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_context={
            "selection": {"kind": "text", "value": "Email is required", "preview": "Email is required"},
            "clipboard": {},
            "adapter_semantics": {
                "browser": _browser_semantics(
                    page_title="Sign in",
                    url="https://example.test/login",
                    validation_messages=["Email is required"],
                    form_fields=[
                        {"field_id": "field-email", "label": "Email", "role": "field", "visible": True, "enabled": True}
                    ],
                )
            },
        },
    )

    problem = response.analysis.problem_solving_result

    assert problem is not None
    assert problem.reused_adapter is True
    assert "adapter_semantics" in response.telemetry["problem_solving"]["provenance_channels"]
    assert "native_observation" in response.telemetry["problem_solving"]["provenance_channels"]
    assert response.telemetry["problem_solving"]["adapter_contribution"] is True
    assert "email is required" in response.assistant_response.lower()
