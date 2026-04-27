from __future__ import annotations

from stormhelm.core.orchestrator.command_eval.corpus import build_command_usability_corpus
from stormhelm.core.orchestrator.command_eval.runner import _clarification_observed
from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _plan(
    message: str,
    *,
    active_request_state: dict[str, object] | None = None,
    active_context: dict[str, object] | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="planner-v2-main-reconciliation",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state=active_request_state or {},
        active_context=active_context or {},
        recent_tool_results=[],
    )


def _case(case_id: str):
    for case in build_command_usability_corpus(min_cases=250):
        if case.case_id == case_id:
            return case
    raise AssertionError(f"missing corpus case {case_id}")


def _winner(decision) -> dict[str, object]:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    return winner


def _tools(decision) -> tuple[str, ...]:
    planned = _winner(decision).get("planned_tools")
    planned_tools = planned if isinstance(planned, list) else []
    explicit = [request.tool_name for request in decision.tool_requests]
    return tuple(dict.fromkeys([*planned_tools, *explicit]))


def _plan_draft(decision) -> dict[str, object]:
    draft = decision.debug.get("planner_v2", {}).get("plan_draft", {})
    return draft if isinstance(draft, dict) else {}


def test_no_owner_deictic_corpus_rows_expect_context_clarification_without_native_context() -> None:
    for case_id in (
        "calculations_deictic_00",
        "context_action_deictic_00",
        "discord_relay_deictic_00",
        "routine_save_deictic_00",
    ):
        case = _case(case_id)

        assert case.message == "use this for that"
        assert case.expected.route_family == "context_clarification"
        assert case.expected.subsystem == "context"
        assert case.expected.tools == ()
        assert case.expected.clarification == "expected"
        assert case.expected.response_terms == ()
        assert "recent_context_resolutions" not in case.input_context


def test_restored_direct_status_followups_use_planner_v2_not_generic_provider() -> None:
    examples = {
        "development": ("echo", "development", {"source_case": "echo", "tool_name": "echo"}),
        "time": ("clock", "system", {"source_case": "clock", "tool_name": "clock"}),
        "storage": ("storage_status", "system", {"source_case": "storage_status", "tool_name": "storage_status"}),
        "location": ("location_status", "location", {"source_case": "location_status", "tool_name": "location_status"}),
        "weather": ("weather_current", "weather", {"source_case": "weather_current", "tool_name": "weather_current"}),
        "power": ("power_status", "system", {"source_case": "power_status", "tool_name": "power_status"}),
        "resources": ("resource_status", "system", {"source_case": "resource_status", "tool_name": "resource_status"}),
        "window_control": ("window_status", "system", {"source_case": "window_status", "tool_name": "window_status"}),
        "file_operation": ("file_operation", "files", {"source_case": "file_operation", "tool_name": "file_operation"}),
        "maintenance": ("maintenance_action", "maintenance", {"source_case": "maintenance", "tool_name": "maintenance_action"}),
        "notes": ("notes_write", "workspace", {"source_case": "notes_write", "tool_name": "notes_write"}),
        "software_recovery": ("repair_action", "software_recovery", {"source_case": "software_recovery", "tool_name": "repair_action"}),
    }
    for family, (tool, subsystem, parameters) in examples.items():
        subject = "harness ping" if family == "development" else family.replace("_", " ")
        if family == "development":
            parameters = {**parameters, "echo_text": "harness ping"}
        decision = _plan(
            "do the same thing as before",
            active_request_state={
                "family": family,
                "subject": subject,
                "parameters": {"request_stage": "preview", **parameters},
            },
        )

        assert decision.debug["routing_engine"] == "planner_v2", family
        assert _winner(decision).get("route_family") == family
        assert _plan_draft(decision).get("subsystem") == subsystem
        if family == "development":
            assert decision.tool_requests[0].arguments.get("text") == "harness ping"
        assert tool in _tools(decision)
        assert _winner(decision).get("route_family") != "generic_provider"
        assert decision.debug["generic_provider_gate_reason"] == "native_route_candidate_present"


def test_restored_direct_status_canonical_rows_use_planner_v2_authority() -> None:
    examples = {
        "what time is it": ("time", "clock"),
        "how much disk space do I have": ("storage", "storage_status"),
        "where am I": ("location", "location_status"),
        "what is the weather here": ("weather", "weather_current"),
        "what is my battery at": ("power", "power_status"),
        "what is my CPU and memory usage": ("resources", "resource_status"),
        "what windows are open": ("window_control", "window_status"),
        "/echo harness ping": ("development", "echo"),
        "/note Eval note: remember this test note": ("notes", "notes_write"),
        "rename my screenshots by date": ("file_operation", "file_operation"),
        "clean up my downloads": ("maintenance", "maintenance_action"),
        "fix my wifi": ("software_recovery", "repair_action"),
    }
    for message, (family, tool) in examples.items():
        decision = _plan(message)

        assert decision.debug["routing_engine"] == "planner_v2", message
        assert _winner(decision).get("route_family") == family
        assert tool in _tools(decision)
        assert _winner(decision).get("route_family") != "generic_provider"


def test_browser_context_followup_preserves_browser_context_tool_and_context_subsystem() -> None:
    decision = _plan(
        "do the same thing as before",
        active_request_state={
            "family": "watch_runtime",
            "subject": "browser page",
            "parameters": {"source_case": "browser_context", "tool_name": "browser_context", "request_stage": "preview"},
        },
    )

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner(decision).get("route_family") == "watch_runtime"
    assert _plan_draft(decision).get("subsystem") == "context"
    assert "browser_context" in _tools(decision)
    assert "activity_summary" not in _tools(decision)


def test_software_install_followup_preserves_install_preview_posture() -> None:
    decision = _plan(
        "do the same thing as before",
        active_request_state={
            "family": "software_control",
            "subject": "Firefox",
            "parameters": {"source_case": "software_control_install", "target_name": "Firefox", "request_stage": "preview"},
        },
    )

    intent = decision.debug["intent_frame"]
    result_state = decision.debug["planner_v2"]["result_state_draft"]["result_state"]

    assert decision.debug["routing_engine"] == "planner_v2"
    assert _winner(decision).get("route_family") == "software_control"
    assert intent["operation"] == "install"
    assert intent["risk_class"] == "software_lifecycle"
    assert result_state in {"dry_run_ready", "requires_approval"}


def test_screen_unavailable_response_is_counted_as_clarification() -> None:
    assert _clarification_observed(
        {},
        {},
        {
            "content": (
                "I don't have a reliable screen bearing right now. "
                "Observed: there was no focused window, selected text, or grounded workspace surface I could trust. "
                "Inference: I can't safely describe the visible state from this signal."
            )
        },
    )
