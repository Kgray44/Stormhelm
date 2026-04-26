from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.workspace.models import (
    WorkspaceContinuitySnapshot,
    WorkspaceRecord,
    WorkspaceSessionPosture,
)
from stormhelm.core.workspace.service import (
    WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT,
    WorkspaceService,
)


def _item(index: int) -> dict[str, object]:
    return {
        "itemId": f"item-{index}",
        "kind": "file",
        "viewer": "text",
        "title": f"Workspace item {index}",
        "subtitle": "Fixture",
        "module": "files",
        "section": "references",
        "path": f"C:/Stormhelm/fixture-{index}.md",
        "summary": "summary " + ("x" * 900),
        "content": "body " + ("y" * 4000),
        "metadata": {"large": "z" * 4000},
    }


def test_workspace_view_payload_caps_embedded_item_lists() -> None:
    service = WorkspaceService.__new__(WorkspaceService)
    items = [_item(index) for index in range(WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT + 75)]
    workspace = WorkspaceRecord(
        workspace_id="workspace-fixture",
        name="Fixture Workspace",
        topic="payload guardrails",
        summary="Fixture workspace for payload guardrails.",
        references=items,
        findings=items,
        session_notes=items,
    )
    continuity = WorkspaceContinuitySnapshot(
        opened_items=items,
        references=items,
        findings=items,
        session_notes=items,
        active_item=items[0],
    )
    surface_content = {
        "references": {
            "items": items,
        },
        "opened-items": {
            "items": items,
        },
    }

    payload = service._workspace_view_payload(
        workspace,
        continuity=continuity,
        session_posture=WorkspaceSessionPosture(),
        surface_content=surface_content,
    )

    assert len(payload["references"]) == WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT
    assert payload["referencesSummary"]["total_count"] == len(items)
    assert payload["referencesSummary"]["truncated"] is True
    assert payload["referencesSummary"]["omitted_count"] == len(items) - WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT
    assert len(payload["continuity"]["openedItems"]) == WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT
    assert payload["continuity"]["openedItemsSummary"]["truncated"] is True
    assert len(payload["surfaceContent"]["references"]["items"]) == WORKSPACE_DEFAULT_EMBEDDED_ITEM_LIMIT
    assert payload["surfaceContent"]["references"]["itemsSummary"]["truncated"] is True
    assert "content" not in payload["references"][0]
    assert "metadata" not in payload["references"][0]
    assert payload["payloadGuardrails"]["truncated_workspace_items"] is True
    assert payload["payloadGuardrails"]["payload_guardrail_triggered"] is True


def test_no_context_routine_save_routes_to_native_clarification() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "save this as a routine called cleanup",
        session_id="routine-empty",
        surface_mode="ghost",
        active_module="chartroom",
        active_request_state={},
        active_context={},
        recent_tool_results=[],
    )
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}

    assert route_state["winner"]["route_family"] == "routine"
    assert decision.tool_requests == []
    assert decision.clarification_reason is not None
    assert decision.clarification_reason.code == "missing_routine_context"
    assert "steps" in str(decision.assistant_message).lower()
    assert "generic_provider" not in {candidate["route_family"] for candidate in route_state["candidates"][:1]}
    diagnostics = decision.debug["structured_query"]["slots"]["routine_save_precondition_state"]
    assert diagnostics["active_context_available"] is False
    assert diagnostics["deictic_binding_status"] == "missing"


def test_active_context_routine_save_keeps_native_tool_path() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "save this as a routine called cleanup",
        session_id="routine-active",
        surface_mode="ghost",
        active_module="chartroom",
        active_request_state={
            "family": "maintenance",
            "subject": "downloads",
            "parameters": {"action": "cleanup_downloads"},
        },
        active_context={
            "current_resolution": {"kind": "maintenance", "summary": "Clean downloads."},
        },
        recent_tool_results=[],
    )
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}

    assert route_state["winner"]["route_family"] == "routine"
    assert [request.tool_name for request in decision.tool_requests] == ["routine_save"]
    assert decision.tool_requests[0].arguments["routine_name"] == "cleanup"
    assert decision.tool_requests[0].arguments["routine_save_precondition_state"]["active_context_available"] is True
    assert decision.tool_requests[0].arguments["routine_save_precondition_state"]["active_context_bounded"] is True
