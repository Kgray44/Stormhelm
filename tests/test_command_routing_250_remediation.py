from __future__ import annotations

from pathlib import Path

from stormhelm.config.loader import load_config
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.orchestrator.router import IntentRouter
from stormhelm.core.tools.builtins import register_builtin_tools
from stormhelm.core.tools.registry import ToolRegistry


def _plan(
    message: str,
    *,
    active_context: dict[str, object] | None = None,
    active_request_state: dict[str, object] | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="routing-250-remediation",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context={},
        active_posture={},
        active_request_state=active_request_state or {},
        active_context=active_context or {},
        recent_tool_results=[],
    )


def _winner_family(decision) -> str:
    route_state = decision.route_state.to_dict() if decision.route_state is not None else {}
    winner = route_state.get("winner") if isinstance(route_state.get("winner"), dict) else {}
    return str(winner.get("route_family") or "")


def _tool_names(decision) -> list[str]:
    return [request.tool_name for request in decision.tool_requests]


def test_exact_250_operator_wrappers_route_native_instead_of_generic_provider() -> None:
    cases = [
        ("hey can you what is 18 / 3", "calculations", []),
        ("pls what is 18 / 3", "calculations", []),
        ("I need the Stormhelm route for this: what is 18 / 3", "calculations", []),
        ("uhhh what is 18 / 3 -- quick quick", "calculations", []),
        ("could you what is 18 / 3?", "calculations", []),
        ("yo what is 18 / 3 real quick", "calculations", []),
        ("hey can you open youtube in a browser", "browser_destination", ["external_open_url"]),
        ("I need the Stormhelm route for this: what browser page am I on", "watch_runtime", ["browser_context"]),
        ("hey can you install Firefox", "software_control", []),
        ("hey can you send this to Baby on Discord", "discord_relay", []),
    ]

    for prompt, expected_family, expected_tools in cases:
        decision = _plan(
            prompt,
            active_context={
                "selection": {
                    "kind": "text",
                    "value": "Selected context for the remediation prompt.",
                    "preview": "Selected context for the remediation prompt.",
                }
            },
        )

        assert _winner_family(decision) == expected_family, prompt
        assert _tool_names(decision) == expected_tools, prompt


def test_unseen_operator_wrapper_variants_route_by_family_rules() -> None:
    cases = [
        ("please what is 42 / 7", "calculations", []),
        ("could you open github in a browser", "browser_destination", ["external_open_url"]),
        ("yo install VLC real quick", "software_control", []),
        ("please send this to Baby on Discord", "discord_relay", []),
        ("could you show the selection", "context_action", ["context_action"]),
    ]

    for prompt, expected_family, expected_tools in cases:
        decision = _plan(
            prompt,
            active_context={
                "selection": {
                    "kind": "text",
                    "value": "Selected text for unseen operator-wrapper validation.",
                    "preview": "Selected text for unseen operator-wrapper validation.",
                }
            },
        )

        assert _winner_family(decision) == expected_family, prompt
        assert _tool_names(decision) == expected_tools, prompt


def test_wrapped_direct_slash_commands_route_through_direct_router() -> None:
    router = IntentRouter()

    assert [tool.tool_name for tool in router.route("hey can you /system").tool_calls] == ["system_info"]
    assert [tool.tool_name for tool in router.route("pls /echo harness ping").tool_calls] == ["echo"]
    assert [tool.tool_name for tool in router.route("I need the Stormhelm route for this: /note Eval | note").tool_calls] == [
        "notes_write"
    ]


def test_native_status_prompts_from_250_have_owned_routes() -> None:
    cases = [
        ("what apps are open", "app_control", ["active_apps"]),
        ("am I online", "network", ["network_status"]),
        ("what windows are open", "window_control", ["window_status"]),
        ("what is my CPU and memory usage", "resources", ["resource_status"]),
    ]

    for prompt, expected_family, expected_tools in cases:
        decision = _plan(prompt)

        assert _winner_family(decision) == expected_family, prompt
        assert _tool_names(decision) == expected_tools, prompt


def test_unseen_status_variants_route_without_exact_sentence_matching() -> None:
    cases = [
        ("which applications are running", "app_control", ["active_apps"]),
        ("list active programs", "app_control", ["active_apps"]),
        ("are we online", "network", ["network_status"]),
        ("show active windows", "window_control", ["window_status"]),
        ("which window is focused", "window_control", ["window_status"]),
    ]

    for prompt, expected_family, expected_tools in cases:
        decision = _plan(prompt)

        assert _winner_family(decision) == expected_family, prompt
        assert _tool_names(decision) == expected_tools, prompt


def test_system_control_tool_is_available_to_command_eval_dry_run(tmp_path: Path) -> None:
    config = load_config(
        project_root=Path.cwd(),
        env={
            "STORMHELM_DATA_DIR": str(tmp_path),
            "STORMHELM_OPENAI_ENABLED": "false",
            "STORMHELM_COMMAND_EVAL_DRY_RUN": "true",
        },
    )

    assert config.tools.enabled.is_enabled("system_control")
    registry = ToolRegistry()
    register_builtin_tools(registry)
    assert registry.get("system_control").name == "system_control"


def test_unsupported_external_purchase_request_is_native_unsupported_not_provider_fallback() -> None:
    decision = _plan("book me a real flight and pay for it now")

    assert _winner_family(decision) == "unsupported"
    assert _tool_names(decision) == []
    assert decision.assistant_message
    assert "can't" in decision.assistant_message.lower() or "cannot" in decision.assistant_message.lower()


def test_unseen_unsupported_external_commitments_decline_natively() -> None:
    cases = [
        "buy me a real concert ticket and pay now",
        "order a hotel reservation and pay for it now",
        "purchase a real train ticket for me now",
    ]

    for prompt in cases:
        decision = _plan(prompt)

        assert _winner_family(decision) == "unsupported", prompt
        assert _tool_names(decision) == [], prompt
        assert decision.assistant_message


def test_operator_wrapper_near_misses_do_not_get_overcaptured() -> None:
    cases = [
        "hey can you tell me why browsers are stressful",
        "I need the Stormhelm route for this: almost open youtube in a browser, but not exactly",
        "pls explain what an app is",
        "which application window pattern should I use in this code",
        "can you explain online payments",
    ]

    for prompt in cases:
        decision = _plan(prompt)

        assert _winner_family(decision) == "generic_provider", prompt
        assert _tool_names(decision) == [], prompt


def test_ambiguous_or_missing_context_prompts_do_not_become_overconfident() -> None:
    cases = [
        "could you open settings",
        "show open things",
        "pay for it",
    ]

    for prompt in cases:
        decision = _plan(prompt)

        assert _winner_family(decision) in {"generic_provider", "unsupported"}, prompt
        assert _tool_names(decision) == [], prompt
