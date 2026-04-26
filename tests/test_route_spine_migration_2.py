from __future__ import annotations

from pathlib import Path

from stormhelm.core.orchestrator.intent_frame import IntentFrameExtractor
from stormhelm.core.orchestrator.route_spine import RouteSpine


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ROUTING_FILES = [
    ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "intent_frame.py",
    ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "route_spine.py",
    ROOT / "src" / "stormhelm" / "core" / "orchestrator" / "route_family_specs.py",
]


def test_migration_2_removes_exact_deictic_benchmark_phrase_from_route_spine_code() -> None:
    for path in PRODUCT_ROUTING_FILES:
        text = path.read_text(encoding="utf-8")

        assert "use this for that" not in text


def test_calculation_followup_uses_general_deictic_pattern_with_prior_calculation_context() -> None:
    frame = IntentFrameExtractor().extract(
        "use this for that",
        active_context={},
        active_request_state={"family": "calculations"},
        recent_tool_results=[],
    )

    assert frame.operation == "calculate"
    assert frame.native_owner_hint == "calculations"
    assert frame.context_reference in {"this", "that", "previous_calculation"}
    assert frame.generic_provider_allowed is False


def test_route_spine_owns_high_impact_legacy_families_after_migration_2() -> None:
    cases = [
        ("restore my docs workspace", "workspace_operations"),
        ("set up my writing environment", "workflow"),
        ("clean up my downloads", "maintenance"),
        ("continue where I left off", "task_continuity"),
        ("why are you asking for approval", "trust_approvals"),
        ("find README.md on this computer", "desktop_search"),
        ("open PowerShell here", "terminal"),
    ]
    spine = RouteSpine()

    for prompt, expected in cases:
        decision = spine.route(prompt, active_context={}, active_request_state={}, recent_tool_results=[])

        assert decision.routing_engine == "route_spine", prompt
        assert decision.winner.route_family == expected, prompt
        assert decision.selected_route_spec == expected, prompt
        assert decision.intent_frame.native_owner_hint == expected, prompt
        assert decision.generic_provider_allowed is False, prompt
        assert decision.legacy_fallback_used is False, prompt


def test_route_spine_migration_2_preserves_near_miss_rejection() -> None:
    cases = [
        "workspace design theory",
        "clean up this paragraph",
        "what is approval voting",
        "search algorithms explanation",
        "terminal velocity explanation",
        "workflow theory",
    ]
    spine = RouteSpine()

    for prompt in cases:
        decision = spine.route(prompt, active_context={}, active_request_state={}, recent_tool_results=[])

        assert decision.winner.route_family == "generic_provider", prompt
        assert decision.generic_provider_allowed is True, prompt
        assert decision.legacy_fallback_used is False, prompt


def test_route_spine_migration_2_clarifies_missing_context_inside_native_family() -> None:
    cases = [
        ("rename it", "file_operation"),
        ("open the terminal there", "terminal"),
        ("approve that request", "trust_approvals"),
        ("run that workflow again", "workflow"),
    ]
    spine = RouteSpine()

    for prompt, expected in cases:
        decision = spine.route(prompt, active_context={}, active_request_state={}, recent_tool_results=[])

        assert decision.routing_engine == "route_spine", prompt
        assert decision.winner.route_family == expected, prompt
        assert decision.clarification_needed is True, prompt
        assert decision.missing_preconditions, prompt
        assert decision.generic_provider_allowed is False, prompt
