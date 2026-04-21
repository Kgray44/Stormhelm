from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _plan(message: str):
    planner = DeterministicPlanner()
    return planner.plan(
        message,
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )


def test_planner_exposes_structured_current_metric_query_for_gpu_usage() -> None:
    decision = _plan("what is my GPU usage right now")

    assert decision.structured_query is not None
    assert decision.structured_query.domain == "gpu"
    assert decision.structured_query.query_shape == "current_metric"
    assert decision.structured_query.requested_metric == "usage"
    assert decision.structured_query.timescale == "now"
    assert decision.response_mode == "numeric_metric"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "retrieve_live_metric"
    assert decision.tool_requests[0].tool_name == "resource_status"
    assert decision.tool_requests[0].arguments["query_kind"] == "telemetry"
    assert decision.tool_requests[0].arguments["metric"] == "usage"


def test_planner_exposes_structured_current_metric_query_for_cpu_temperature() -> None:
    decision = _plan("CPU temp")

    assert decision.structured_query is not None
    assert decision.structured_query.domain == "cpu"
    assert decision.structured_query.query_shape == "current_metric"
    assert decision.structured_query.requested_metric == "temperature"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "retrieve_live_metric"
    assert decision.tool_requests[0].tool_name == "resource_status"
    assert decision.tool_requests[0].arguments["focus"] == "cpu"
    assert decision.tool_requests[0].arguments["metric"] == "temperature"


def test_planner_blocks_internet_speed_metric_when_no_throughput_capability_exists() -> None:
    decision = _plan("what is my current internet speed")

    assert decision.structured_query is not None
    assert decision.structured_query.domain == "network"
    assert decision.structured_query.query_shape == "current_metric"
    assert decision.structured_query.requested_metric == "internet_speed"
    assert decision.capability_plan is not None
    assert decision.capability_plan.supported is False
    assert decision.capability_plan.unsupported_reason is not None
    assert "throughput" in decision.capability_plan.unsupported_reason.lower()
    assert decision.tool_requests == []
    assert decision.assistant_message is not None
    assert "throughput" in decision.assistant_message.lower()
    assert "isn't available" in decision.assistant_message.lower()


def test_planner_distinguishes_network_status_from_network_diagnosis_and_history() -> None:
    status = _plan("what network am I on")
    diagnosis = _plan("why does my internet keep skipping")
    history = _plan("has my Wi-Fi been unstable today")

    assert status.structured_query is not None
    assert status.structured_query.query_shape == "current_status"
    assert status.tool_requests[0].tool_name == "network_status"

    assert diagnosis.structured_query is not None
    assert diagnosis.structured_query.query_shape == "diagnostic_causal"
    assert diagnosis.tool_requests[0].tool_name == "network_diagnosis"

    assert history.structured_query is not None
    assert history.structured_query.query_shape == "history_trend"
    assert history.tool_requests[0].tool_name == "network_diagnosis"
    assert history.tool_requests[0].arguments["focus"] == "history"


def test_planner_asks_for_missing_file_targets_on_comparison_requests() -> None:
    decision = _plan("compare these two files")

    assert decision.structured_query is not None
    assert decision.structured_query.query_shape == "comparison_request"
    assert decision.structured_query.domain == "files"
    assert decision.tool_requests == []
    assert decision.assistant_message == "Which two files should I compare?"


def test_planner_debug_trace_exposes_staged_planning_artifacts() -> None:
    decision = _plan("what is my GPU usage right now")

    assert decision.debug is not None
    assert decision.debug["normalized_command"]["normalized_text"] == "what is my gpu usage right now"
    assert decision.debug["semantic_parse_proposal"]["query_shape"] == "current_metric"
    assert decision.debug["structured_query"]["requested_metric"] == "usage"
    assert decision.debug["capability_plan"]["supported"] is True
    assert decision.debug["execution_plan"]["plan_type"] == "retrieve_live_metric"
    assert decision.debug["response_mode"] == "numeric_metric"
