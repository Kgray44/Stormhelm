from __future__ import annotations

import asyncio
import json

from test_assistant_orchestrator import FakeSystemProbe
from test_assistant_orchestrator import _build_assistant_with_workspace


def _run_profiled_assistant(
    assistant,
    jobs,
    executor,
    *,
    message: str,
    response_profile: str | None,
    workspace_context: dict[str, object] | None = None,
) -> dict[str, object]:
    async def runner() -> dict[str, object]:
        await jobs.start()
        try:
            return await assistant.handle_message(
                message,
                surface_mode="ghost",
                active_module="chartroom",
                workspace_context=workspace_context,
                response_profile=response_profile,
            )
        finally:
            await jobs.stop()
            executor.shutdown()

    return asyncio.run(runner())


def _large_workspace_context(count: int = 80) -> dict[str, object]:
    items = [
        {
            "itemId": f"item-{index}",
            "kind": "file",
            "viewer": "deck",
            "title": f"Latency Payload Evidence {index}",
            "subtitle": "payload audit",
            "module": "files",
            "section": "references",
            "path": f"C:/Stormhelm/docs/evidence-{index}.md",
            "summary": "Detailed workspace evidence. " * 30,
            "detail": "Deck-only detail. " * 60,
            "inclusionReasons": [
                {
                    "code": "payload_test",
                    "label": "Payload Test",
                    "detail": "Large repeated workspace inclusion reason. " * 20,
                    "score": 1.0,
                    "source": "test",
                }
            ],
        }
        for index in range(count)
    ]
    return {
        "workspace": {
            "workspaceId": "latency-payload-workspace",
            "name": "Latency Payload Workspace",
            "topic": "latency payload",
            "summary": "Workspace used to verify compact response profiles.",
            "surfaceContent": {
                "references": {
                    "surface": "references",
                    "title": "References",
                    "purpose": "Evidence for this payload test.",
                    "presentationKind": "collection",
                    "items": list(items),
                }
            },
            "references": list(items),
            "pendingNextSteps": ["Keep payloads compact.", "Preserve truth fields."],
        },
        "opened_items": list(items),
        "active_item": items[0],
        "section": "references",
    }


def test_command_eval_compact_profile_preserves_eval_fields_and_summarizes_workspace(temp_config) -> None:
    assistant, jobs, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )

    payload = _run_profiled_assistant(
        assistant,
        jobs,
        executor,
        message="assemble a workspace for latency payload",
        response_profile="command_eval_compact",
        workspace_context=_large_workspace_context(),
    )

    assert payload["response_profile"] == "command_eval_compact"
    assert payload["payload_diagnostics"]["compacted"] is True
    assert "full_planner_capability_specs" in payload["payload_diagnostics"]["omitted_sections"]
    assert len(json.dumps(payload, default=str)) < 220_000

    assistant_message = payload["assistant_message"]
    metadata = assistant_message["metadata"]
    assert metadata["response_profile"] == "command_eval_compact"
    assert metadata["stage_timings_ms"]["payload_compaction_ms"] >= 0
    assert metadata["stage_timings_ms"]["response_compose_ms"] >= 0
    assert metadata["route_state"]["winner"]["route_family"] == "workspace_operations"
    assert metadata["planner_debug"]["planner_v2"]["route_decision"]["selected_route_spec"]
    assert "capability_specs" not in metadata["planner_debug"]["planner_v2"]
    assert metadata["planner_obedience"]["actual_result_mode"] == "workspace_result"

    job = payload["jobs"][0]
    assert job["tool_name"] == "workspace_assemble"
    workspace = job["result"]["data"]["workspace"]
    assert "surfaceContentSummary" in workspace
    assert "surfaceContent" not in workspace
    assert workspace["referencesSummary"]["truncated"] is True
    assert payload["actions"][0]["workspace"]["surfaceContentSummary"]["surface_count"] >= 1


def test_compact_profile_preserves_safety_and_provider_audit_shape(temp_config) -> None:
    assistant, jobs, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )
    try:
        payload = {
            "session_id": "default",
            "user_message": {"role": "user", "content": "repair the app", "metadata": {}},
            "assistant_message": {
                "role": "assistant",
                "content": "Dry-run only.",
                "metadata": {
                    "planner_debug": {
                        "routing_engine": "planner_v2",
                        "planner_v2": {
                            "route_decision": {
                                "selected_route_spec": "software_recovery",
                                "generic_provider_gate_reason": "native_route_candidate_present",
                            },
                            "capability_specs": [{"route_family": "software_recovery"} for _ in range(20)],
                        },
                    },
                    "route_state": {"winner": {"route_family": "software_recovery"}},
                    "planner_obedience": {"actual_result_mode": "action_result"},
                    "stage_timings_ms": {},
                },
            },
            "job": None,
            "jobs": [
                {
                    "job_id": "job-1",
                    "tool_name": "repair_action",
                    "arguments": {"target": "Example App"},
                    "status": "completed",
                    "result": {
                        "success": True,
                        "summary": "Dry-run only.",
                        "data": {
                            "dry_run": True,
                            "approval_required": True,
                            "preview_required": True,
                            "adapter_contract_status": {"healthy": True},
                            "route_handler_subspans": {"repair_action_lookup_ms": 1.0},
                        },
                        "adapter_execution": {
                            "claim_ceiling": "preview",
                            "approval_required": True,
                            "preview_required": True,
                            "verification_observed": "dry_run",
                        },
                    },
                }
            ],
            "actions": [],
            "active_request_state": {
                "family": "software_recovery",
                "context_freshness": "current",
                "context_reusable": True,
                "parameters": {"target_name": "Example App", "tool_name": "repair_action"},
                "structured_query": {
                    "query_shape": "software_recovery_request",
                    "slots": {"target_name": "Example App"},
                },
            },
            "recent_context_resolutions": [],
            "active_task": {},
        }

        compact = assistant._apply_response_profile(
            payload,
            profile="command_eval_compact",
            reason="unit_test",
        )
    finally:
        executor.shutdown()

    result = compact["jobs"][0]["result"]
    data = result["data"]
    assert data["dry_run"] is True
    assert data["approval_required"] is True
    assert data["preview_required"] is True
    assert result["adapter_execution"]["verification_observed"] == "dry_run"
    assert compact["active_request_state"]["family"] == "software_recovery"
    assert compact["active_request_state"]["parameters"]["tool_name"] == "repair_action"
    assert "capability_specs" not in compact["assistant_message"]["metadata"]["planner_debug"]["planner_v2"]
    assert compact["assistant_message"]["metadata"]["planner_debug"]["planner_v2"]["capability_specs_summary"]["total_count"] == 20


def test_deck_detail_profile_remains_backward_compatible(temp_config) -> None:
    assistant, jobs, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )

    payload = _run_profiled_assistant(
        assistant,
        jobs,
        executor,
        message="what time is it",
        response_profile="deck_detail",
    )

    assert payload["response_profile"] == "deck_detail"
    assert "payload_diagnostics" in payload
    assert payload["assistant_message"]["metadata"]["response_profile"] == "deck_detail"


def test_ghost_surface_defaults_to_compact_response_profile(temp_config) -> None:
    temp_config.environment = "dev"
    assistant, jobs, executor, _, _ = _build_assistant_with_workspace(
        temp_config,
        system_probe=FakeSystemProbe(),
    )

    payload = _run_profiled_assistant(
        assistant,
        jobs,
        executor,
        message="5*4/2",
        response_profile=None,
    )

    assert payload["response_profile"] == "ghost_compact"
    assert payload["payload_diagnostics"]["compacted"] is True
    assert (
        payload["assistant_message"]["metadata"]["response_profile_reason"]
        == "ghost_hot_path_default"
    )
