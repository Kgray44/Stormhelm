from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _plan(
    message: str,
    *,
    active_context: dict[str, object] | None = None,
    active_request_state: dict[str, object] | None = None,
):
    return DeterministicPlanner().plan(
        message,
        session_id="route-context-arbitration",
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


def _clarifies(decision, missing_slot: str) -> bool:
    return (
        decision.request_type == "clarification_request"
        and decision.clarification_reason is not None
        and missing_slot in decision.clarification_reason.missing_slots
    )


def _selection_context() -> dict[str, object]:
    return {
        "selection": {
            "kind": "text",
            "value": "Selected notes about the Stormhelm routing pass.",
            "preview": "Selected notes about the Stormhelm routing pass.",
        }
    }


def _calculation_context() -> dict[str, object]:
    return {
        "recent_context_resolutions": [
            {
                "kind": "calculation",
                "result": {"expression": "18 / 3", "display_result": "6"},
                "trace": {"extracted_expression": "18 / 3"},
            }
        ]
    }


def _browser_context() -> dict[str, object]:
    return {
        "recent_entities": [
            {
                "kind": "page",
                "title": "Stormhelm docs",
                "url": "https://docs.example.com/stormhelm",
                "freshness": "current",
            }
        ]
    }


def _file_context() -> dict[str, object]:
    return {
        "recent_entities": [
            {
                "kind": "file",
                "title": "README.md",
                "path": r"C:\Stormhelm\README.md",
                "freshness": "current",
            }
        ]
    }


def test_calculation_context_arbitration_handles_noisy_direct_math_and_followups() -> None:
    positives = [
        "tiny math: 9 times 8",
        "diagnose nothing else, just answer 6 x 7",
        "math rq 13*4",
        "diagnose the answer to 10 + 5",
        "quick arithmetic, 11 times 6",
        "just the result: 14 x 3",
        "can you solve 48 over 6",
        "route this as math: 21 plus 21",
        "compute this please: 100 minus 37",
        "answer only, 8 multiplied by 9",
        "check 144 divided by 12",
        "what does 7 times 8 equal",
    ]
    for prompt in positives:
        decision = _plan(prompt)

        assert _winner_family(decision) == "calculations", prompt
        assert _tool_names(decision) == [], prompt

    followups = [
        "show me the arithmetic for that",
        "now multiply that by 5",
        "same setup but use 30 instead",
        "compare that answer with 10",
        "redo it with 36 / 6",
        "walk through that calculation",
        "what changes if it is 24 / 4",
        "use the same math with 15 instead",
    ]
    for prompt in followups:
        decision = _plan(
            prompt,
            active_context=_calculation_context(),
            active_request_state={
                "family": "calculations",
                "subject": "recent calculation",
                "parameters": {"request_stage": "preview"},
            },
        )

        assert _winner_family(decision) == "calculations", prompt
        assert decision.request_type != "unclassified", prompt

    missing_context = [
        "show me the arithmetic for that",
        "now multiply that by 5",
        "same setup but use 30 instead",
        "compare that answer with 10",
        "redo it",
    ]
    for prompt in missing_context:
        decision = _plan(prompt, active_request_state={"family": "calculations", "subject": "recent calculation"})

        assert _winner_family(decision) == "calculations", prompt
        assert _clarifies(decision, "calculation_context"), prompt

    near_misses = [
        "math teaching ideas for a workshop",
        "compare neural network training costs",
        "open the Calculator app",
        "why is multiplication useful",
        "diagnose why this formula is confusing",
    ]
    for prompt in near_misses:
        decision = _plan(prompt)

        assert _winner_family(decision) != "calculations", prompt


def test_browser_file_and_selected_context_arbitration_routes_or_clarifies_natively() -> None:
    browser_missing = [
        "open that website",
        "open that site from before",
        "bring up that link",
        "show that page",
        "open the website we just used",
    ]
    for prompt in browser_missing:
        decision = _plan(prompt)

        assert _winner_family(decision) == "browser_destination", prompt
        assert _clarifies(decision, "destination_context"), prompt
        assert _tool_names(decision) == [], prompt

    browser_bound = [
        "open that website",
        "show that page again",
        "bring up the previous link",
    ]
    for prompt in browser_bound:
        decision = _plan(prompt, active_context=_browser_context())

        assert _winner_family(decision) == "browser_destination", prompt
        assert _tool_names(decision) == ["external_open_url"], prompt

    file_bound = [
        "open that file from before",
        "show that document again",
        "bring up the previous file",
    ]
    for prompt in file_bound:
        decision = _plan(prompt, active_context=_file_context())

        assert _winner_family(decision) == "file", prompt
        assert _tool_names(decision) in (["external_open_file"], ["deck_open_file"]), prompt

    file_missing = [
        "open that file from before",
        "show that document again",
        "bring up the previous file",
        "read the earlier file",
        "summarize that document",
    ]
    for prompt in file_missing:
        decision = _plan(prompt)

        assert _winner_family(decision) == "file", prompt
        assert _clarifies(decision, "file_context"), prompt

    selected_bound = [
        "summarize the selected text, not the page",
        "use the highlighted bit",
        "turn the selected text into tasks",
        "make tasks from the highlighted text",
        "open the selected text",
    ]
    for prompt in selected_bound:
        decision = _plan(prompt, active_context=_selection_context())

        assert _winner_family(decision) in {"context_action", "task_continuity"}, prompt
        assert _tool_names(decision) == ["context_action"], prompt

    selected_missing = [
        "use the highlighted bit",
        "summarize the selected text",
        "turn the highlighted text into tasks",
        "open the selected text",
        "use the selection for that",
    ]
    for prompt in selected_missing:
        decision = _plan(prompt)

        assert _winner_family(decision) == "context_action", prompt
        assert _clarifies(decision, "context"), prompt

    near_misses = [
        "explain selection bias",
        "open app design principles",
        "what is a website",
        "file naming philosophy",
        "highlighted text typography ideas",
    ]
    for prompt in near_misses:
        decision = _plan(prompt)

        assert _winner_family(decision) == "generic_provider", prompt


def test_screen_status_trust_and_lifecycle_arbitration_preserves_boundaries() -> None:
    screen_missing = [
        "tap that button",
        "select that menu",
        "press submit",
        "click next",
    ]
    for prompt in screen_missing:
        decision = _plan(prompt)

        assert _winner_family(decision) == "screen_awareness", prompt
        assert _clarifies(decision, "visible_screen"), prompt
        assert _tool_names(decision) == [], prompt

    status_positives = [
        "open or diagnose the wifi status",
        "which wifi am I on",
        "what did I miss while I was away",
        "what happened while I was away",
        "what changed while I stepped away",
    ]
    expected = ["network", "network", "watch_runtime", "watch_runtime", "watch_runtime"]
    for prompt, family in zip(status_positives, expected, strict=True):
        decision = _plan(prompt)

        assert _winner_family(decision) == family, prompt
        assert _tool_names(decision), prompt

    trust_missing = [
        "approve it",
        "approve that trusted hook",
        "allow that",
        "deny it",
        "why do you need permission for that",
    ]
    for prompt in trust_missing:
        decision = _plan(prompt)

        assert _winner_family(decision) == "trust_approvals", prompt
        assert _clarifies(decision, "approval_object"), prompt

    lifecycle = [
        "remove Slack from this machine",
        "uninstall Slack from this computer",
        "get rid of Zoom on this PC",
    ]
    for prompt in lifecycle:
        decision = _plan(prompt)

        assert _winner_family(decision) == "software_control", prompt
        assert decision.request_type != "guardrail_clarify", prompt

    near_misses = [
        "compare neural network designs",
        "press coverage analysis",
        "delete all downloads without asking",
        "trust hook design ideas",
        "workflow philosophy",
        "click that one",
        "press it",
        "scroll there",
    ]
    for prompt in near_misses:
        decision = _plan(prompt)

        assert _winner_family(decision) not in {"screen_awareness", "network"}, prompt


def test_generic_provider_gate_hands_missing_native_context_to_native_routes() -> None:
    cases = [
        ("send this there", "discord_relay", "payload"),
        ("rename it", "file_operation", "file_context"),
        ("run the thing", "routine", "routine_context"),
        ("open that file from before", "file", "file_context"),
        ("use the highlighted bit", "context_action", "context"),
    ]
    for prompt, family, slot in cases:
        decision = _plan(prompt)

        assert _winner_family(decision) == family, prompt
        assert _clarifies(decision, slot), prompt
        assert _tool_names(decision) == [], prompt


def test_explicit_file_read_does_not_become_app_launch() -> None:
    positives = [
        r"read C:\Stormhelm\README.md, do not open an app",
        r"summarize C:\Stormhelm\README.md without opening an app",
        r"show me the contents of C:\Stormhelm\README.md",
    ]
    for prompt in positives:
        decision = _plan(prompt)

        assert _winner_family(decision) == "file", prompt
        assert _tool_names(decision) == ["file_reader"], prompt

    near_misses = [
        "read the room",
        "summarize app launch design",
        "open Notepad",
        "show running apps",
        "read about Stormhelm architecture",
    ]
    for prompt in near_misses:
        decision = _plan(prompt)

        assert not (_winner_family(decision) == "file" and _tool_names(decision) == ["file_reader"]), prompt
