from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.planner_v2 import PlannerV2


def _plan(message: str):
    return DeterministicPlanner().plan(
        message,
        session_id="camera-awareness-test",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state={},
        active_context={},
        recent_tool_results=[],
    )


def _plan_with_screen_context(message: str):
    screen_context = {
        "visible_ui": {
            "label": "Visible installer error",
            "source": "screen",
            "evidence_kind": "screen_capture",
        }
    }
    return DeterministicPlanner().plan(
        message,
        session_id="camera-awareness-screen-test",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=screen_context,
        active_posture={},
        active_request_state={},
        active_context=screen_context,
        recent_tool_results=[],
    )


def _winner(decision) -> str:  # noqa: ANN001
    return decision.route_state.to_dict()["winner"]["route_family"]


def test_planner_v2_routes_obvious_camera_requests_to_camera_awareness() -> None:
    cases = [
        "What is this I'm holding?",
        "What am I holding?",
        "Can you identify this thing I'm holding?",
        "Look at this with the camera.",
        "Take a camera look at this part.",
        "What resistor value is this?",
        "What connector is this?",
        "Can you read this label in front of me?",
        "Does this solder joint look bad?",
    ]

    for message in cases:
        trace = PlannerV2().plan(message)
        assert trace.route_decision.selected_route_family == "camera_awareness", message
        assert trace.intent_frame.target_type == "camera_frame"
        assert trace.plan_draft.operation == "inspect"


def test_deterministic_planner_exposes_camera_route_state_and_query_shape() -> None:
    decision = _plan("What resistor value is this?")

    assert _winner(decision) == "camera_awareness"
    assert decision.structured_query.query_shape.value == "camera_awareness_request"
    assert decision.structured_query.domain == "camera_awareness"
    assert decision.active_request_state["family"] == "camera_awareness"
    assert decision.active_request_state["source_provenance"] == "camera_request"
    assert decision.response_mode == "clarification"
    assert "camera capture needs confirmation" in decision.assistant_message.lower()


def test_ambiguous_visual_questions_do_not_default_to_camera() -> None:
    cases = [
        "What is this?",
        "Can you read this?",
        "What am I looking at?",
        "What does this say?",
    ]

    for message in cases:
        decision = _plan(message)
        assert _winner(decision) != "camera_awareness", message


def test_screen_awareness_keeps_authority_for_screen_requests() -> None:
    cases = [
        "What is on my screen?",
        "What window am I looking at?",
        "What does this popup mean?",
    ]

    for message in cases:
        decision = _plan_with_screen_context(message)
        assert _winner(decision) == "screen_awareness", message


def test_general_camera_and_electronics_questions_do_not_route_to_camera_awareness() -> None:
    cases = [
        "What is a JST connector?",
        "How do resistor color codes work?",
        "Show me examples of cold solder joints.",
        "Explain how cameras work.",
        "Open the camera settings.",
        "Find camera drivers online.",
    ]

    for message in cases:
        decision = _plan(message)
        assert _winner(decision) != "camera_awareness", message
