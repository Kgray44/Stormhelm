from __future__ import annotations

from stormhelm.core.orchestrator.route_family_specs import default_route_family_specs


REQUIRED_FAMILIES = {
    "calculations",
    "browser_destination",
    "app_control",
    "file",
    "file_operation",
    "context_action",
    "screen_awareness",
    "workspace_operations",
    "routine",
    "workflow",
    "task_continuity",
    "discord_relay",
    "software_control",
    "watch_runtime",
    "maintenance",
    "trust_approvals",
    "terminal",
    "desktop_search",
    "power",
    "machine",
}


def test_route_family_specs_cover_required_contract_fields() -> None:
    specs = default_route_family_specs()

    assert REQUIRED_FAMILIES <= set(specs)
    for family in REQUIRED_FAMILIES:
        spec = specs[family]

        assert spec.route_family == family
        assert spec.subsystem
        assert spec.owned_operations
        assert spec.owned_target_types
        assert spec.positive_intent_signals
        assert spec.negative_intent_signals
        assert spec.near_miss_examples
        assert spec.missing_context_behavior
        assert spec.ambiguity_behavior
        assert spec.generic_provider_allowed_when
        assert spec.clarification_template
        assert spec.expected_result_states
        assert spec.confidence_floor > 0
        assert spec.overcapture_guards
        assert "intent_frame" in spec.telemetry_fields


def test_high_risk_specs_have_negative_guards_and_missing_context_contracts() -> None:
    specs = default_route_family_specs()

    assert "calculator app" in " ".join(specs["calculations"].negative_intent_signals)
    assert "neural network" in " ".join(specs["calculations"].negative_intent_signals)
    assert "destination_context" in specs["browser_destination"].clarification_template
    assert "file_context" in specs["file"].clarification_template
    assert "visible" in specs["screen_awareness"].clarification_template
    assert "software_lifecycle" in specs["software_control"].risk_classes
    assert "install" in specs["software_control"].owned_operations
    assert "quit" in specs["app_control"].owned_operations
    assert "install" in specs["app_control"].disallowed_context_types
    assert "payload" in specs["discord_relay"].clarification_template
