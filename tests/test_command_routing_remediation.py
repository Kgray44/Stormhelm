from __future__ import annotations

import pytest

from stormhelm.core.orchestrator.command_eval.runner import _approval_observed
from stormhelm.core.orchestrator.command_eval.runner import _subsystem_for_observation
from stormhelm.core.orchestrator.command_eval import build_command_usability_corpus
from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _plan(
    message: str,
    *,
    workspace_context: dict[str, object] | None = None,
    active_context: dict[str, object] | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="routing-remediation",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=workspace_context or {},
        active_request_state={},
        active_context=active_context or {},
        recent_tool_results=[],
    )


def _winner_family(decision) -> str:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    return str(winner.get("route_family") or "")


def _tool_names(decision) -> list[str]:
    return [request.tool_name for request in decision.tool_requests]


@pytest.mark.parametrize(
    ("prompt", "expected_family", "expected_tools"),
    [
        ("Stormhelm, what is 18 / 3", "calculations", []),
        ("Stormhelm, install Firefox", "software_control", []),
        ("Stormhelm, update VLC", "software_control", []),
        ("Stormhelm, open youtube in a browser", "browser_destination", ["external_open_url"]),
        ("Stormhelm, open https://example.com in the deck", "browser_destination", ["deck_open_url"]),
        ("Stormhelm, send this to Baby on Discord", "discord_relay", []),
        ("Stormhelm, run trusted hook build-check", "routine", ["trusted_hook_execute"]),
    ],
)
def test_invocation_prefix_does_not_bypass_native_routes(prompt: str, expected_family: str, expected_tools: list[str]) -> None:
    decision = _plan(prompt)

    assert _winner_family(decision) == expected_family
    assert _tool_names(decision) == expected_tools


@pytest.mark.parametrize(
    ("prompt", "expected_family", "expected_tools"),
    [
        ("restore my docs workspace", "workspace_operations", ["workspace_restore"]),
        ("show my workspaces", "workspace_operations", ["workspace_list"]),
        ("clear the current workspace", "workspace_operations", ["workspace_clear"]),
        ("archive the current workspace", "workspace_operations", ["workspace_archive"]),
        ("what should I do next in this workspace", "task_continuity", ["workspace_next_steps"]),
    ],
)
def test_workspace_prompts_route_natively_instead_of_provider_fallback(
    prompt: str,
    expected_family: str,
    expected_tools: list[str],
) -> None:
    decision = _plan(
        prompt,
        workspace_context={
            "workspace": {"workspaceId": "ws-docs", "name": "Docs Workspace", "topic": "Stormhelm docs"},
            "module": "chartroom",
        },
    )

    assert _winner_family(decision) == expected_family
    assert _tool_names(decision) == expected_tools


@pytest.mark.parametrize(
    ("prompt", "expected_tool"),
    [
        (r"open C:\Stormhelm\README.md externally", "external_open_file"),
        (r"open C:\Stormhelm\README.md in the deck", "deck_open_file"),
        (r"Stormhelm, open C:\Stormhelm\README.md externally", "external_open_file"),
    ],
)
def test_file_paths_are_not_misrouted_to_app_control(prompt: str, expected_tool: str) -> None:
    decision = _plan(prompt)

    assert _winner_family(decision) == "file"
    assert _tool_names(decision) == [expected_tool]


@pytest.mark.parametrize(
    ("prompt", "expected_family", "expected_tools"),
    [
        ("what browser page am I on", "watch_runtime", ["browser_context"]),
        ("Stormhelm, what did I miss", "watch_runtime", ["activity_summary"]),
        ("what is my battery at", "power", ["power_status"]),
        ("how long until my battery is full", "power", ["power_projection"]),
    ],
)
def test_status_runtime_and_power_prompts_keep_feature_map_route_family(
    prompt: str,
    expected_family: str,
    expected_tools: list[str],
) -> None:
    decision = _plan(prompt)

    assert _winner_family(decision) == expected_family
    assert _tool_names(decision) == expected_tools


@pytest.mark.parametrize(
    "prompt",
    [
        "show my workspace inspiration board ideas",
        r"tell me about the path C:\Stormhelm\README.md without opening it",
        "what is battery acid",
        "open up about why browsers are stressful",
    ],
)
def test_near_miss_prompts_do_not_get_overcaptured_by_native_routes(prompt: str) -> None:
    decision = _plan(prompt)

    assert _winner_family(decision) == "generic_provider"
    assert _tool_names(decision) == []


def test_watch_runtime_reports_context_subsystem_for_browser_context_only() -> None:
    assert _subsystem_for_observation("watch_runtime", ("browser_context",)) == "context"
    assert _subsystem_for_observation("watch_runtime", ("activity_summary",)) == "operations"


def test_expected_or_preview_accepts_dry_run_and_prepared_plan_preview() -> None:
    assert _approval_observed(
        (
            {
                "data": {"dry_run": True, "preview_required": True},
                "adapter_execution": {"claim_ceiling": "preview", "verification_observed": "dry_run"},
            },
        ),
        {},
        {},
    )
    assert _approval_observed(
        (),
        {},
        {"content": "Prepared a local install plan for Firefox. I have not installed anything yet."},
    )


def test_plain_dry_run_is_not_counted_as_approval_or_preview() -> None:
    assert not _approval_observed(
        (
            {
                "data": {"dry_run": True, "approval_required": False, "preview_required": False},
                "adapter_execution": {"claim_ceiling": "preview", "verification_observed": "dry_run"},
            },
        ),
        {},
        {"content": "Dry-run only: would execute Status. No external action was performed."},
    )


@pytest.mark.parametrize("case_id", ["browser_deck_canonical_00", "file_deck_canonical_00"])
def test_command_deck_internal_opens_do_not_expect_external_approval(case_id: str) -> None:
    cases = {case.case_id: case for case in build_command_usability_corpus(min_cases=1000)}

    assert cases[case_id].expected.approval == "not_expected"


@pytest.mark.parametrize(
    ("case_id", "expected_family", "expected_tools"),
    [
        ("workflow_execute_canonical_00", "workflow", ["workflow_execute"]),
        ("file_operation_canonical_00", "file_operation", ["file_operation"]),
        ("context_action_canonical_00", "context_action", ["context_action"]),
    ],
)
def test_focused_routeability_cases_use_supported_native_phrasing(
    case_id: str,
    expected_family: str,
    expected_tools: list[str],
) -> None:
    cases = {case.case_id: case for case in build_command_usability_corpus(min_cases=1000)}
    case = cases[case_id]

    decision = _plan(case.message, active_context=case.input_context)

    assert _winner_family(decision) == expected_family
    assert _tool_names(decision) == expected_tools
