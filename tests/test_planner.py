from __future__ import annotations

from stormhelm.core.orchestrator.planner import DeterministicPlanner


def _active_subject(
    family: str,
    **parameters: object,
) -> dict[str, object]:
    return {
        "family": family,
        "parameters": parameters,
    }


def test_planner_routes_direct_weather_to_structured_tool_without_open() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "just get me the current weather",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_deterministic_fact"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "weather_current"
    assert decision.tool_requests[0].arguments["open_target"] == "none"
    assert decision.tool_requests[0].arguments["forecast_target"] == "current"


def test_planner_routes_direct_arithmetic_to_builtin_calculation_lane() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "2+2+4+4+4+4+5+10",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "calculation_response"
    assert decision.tool_requests == []
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "calculation_request"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "calculation_evaluate"
    assert decision.response_mode == "calculation_result"
    assert decision.debug["calculations"]["candidate"] is True
    assert decision.debug["calculations"]["extracted_expression"] == "2+2+4+4+4+4+5+10"


def test_planner_routes_explicit_calculation_request_with_malformed_expression_to_calculation_lane() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "calculate 2+*",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "calculation_response"
    assert decision.tool_requests == []
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "calculation_evaluate"
    assert decision.debug["calculations"]["candidate"] is True
    assert decision.debug["calculations"]["disposition"] == "direct_expression"


def test_planner_routes_engineering_style_expression_to_builtin_calculation_lane() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "3.3k * 2.2mA",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "calculation_response"
    assert decision.tool_requests == []
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "calculation_evaluate"
    assert decision.debug["calculations"]["candidate"] is True
    assert decision.debug["calculations"]["extracted_expression"] == "3.3k * 2.2mA"


def test_planner_routes_supported_rc_cutoff_helper_request_to_builtin_calculation_lane() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "what is the RC cutoff for 10k and 0.1uF",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "calculation_response"
    assert decision.debug["calculations"]["candidate"] is True
    assert decision.debug["calculations"]["helper_name"] == "rc_cutoff"
    assert decision.debug["calculations"]["disposition"] == "helper_request"


def test_planner_routes_supported_helper_request_to_builtin_calculation_lane() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "power at 12V and 1.5A",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "calculation_response"
    assert decision.tool_requests == []
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "calculation_evaluate"
    assert decision.debug["calculations"]["candidate"] is True
    assert decision.debug["calculations"]["helper_name"] == "power_from_voltage_current"
    assert decision.debug["calculations"]["disposition"] == "helper_request"


def test_planner_routes_under_specified_supported_helper_request_without_falling_through() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "power at 12V",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "calculation_response"
    assert decision.tool_requests == []
    assert decision.debug["calculations"]["candidate"] is True
    assert decision.debug["calculations"]["helper_name"] == "power_family"
    assert decision.debug["calculations"]["missing_arguments"]


def test_planner_does_not_hijack_unsupported_helper_like_prose() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "teach me ohm's law",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type != "calculation_response"
    assert decision.debug["calculations"]["candidate"] is False


def test_planner_routes_verification_request_to_builtin_calculation_lane() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "verify 2+2+4+4+4+4+5+10 = 28",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "calculation_response"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "calculation_evaluate"
    assert decision.debug["calculations"]["candidate"] is True
    assert decision.debug["calculations"]["disposition"] == "verification_request"
    assert decision.debug["calculations"]["verification_claim"] == "28"


def test_planner_routes_explanation_follow_up_to_prior_direct_calculation() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "show the steps",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
        active_context={
            "recent_context_resolutions": [
                {
                    "kind": "calculation",
                    "query": "3.3k * 2.2mA",
                    "result": {
                        "expression": "3.3k * 2.2mA",
                        "normalized_expression": "3300*0.0022",
                    },
                    "trace": {
                        "extracted_expression": "3.3k * 2.2mA",
                        "normalized_expression": "3300*0.0022",
                    },
                }
            ]
        },
    )

    assert decision.request_type == "calculation_response"
    assert decision.debug["calculations"]["candidate"] is True
    assert decision.debug["calculations"]["follow_up_reuse"] is True
    assert decision.debug["calculations"]["extracted_expression"] == "3.3k * 2.2mA"
    assert decision.debug["calculations"]["requested_mode"] == "step_by_step"


def test_planner_routes_formula_follow_up_to_prior_helper_calculation() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "show the formula",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
        active_context={
            "recent_context_resolutions": [
                {
                    "kind": "calculation",
                    "query": "power at 12V and 1.5A",
                    "result": {
                        "helper_used": "power_from_voltage_current",
                    },
                    "trace": {
                        "helper_used": "power_from_voltage_current",
                        "helper_arguments": {
                            "voltage": {"value": "12", "normalized_expression": "12"},
                            "current": {"value": "1.5", "normalized_expression": "1.5"},
                        },
                    },
                }
            ]
        },
    )

    assert decision.request_type == "calculation_response"
    assert decision.debug["calculations"]["candidate"] is True
    assert decision.debug["calculations"]["follow_up_reuse"] is True
    assert decision.debug["calculations"]["helper_name"] == "power_from_voltage_current"
    assert decision.debug["calculations"]["requested_mode"] == "formula_substitution"


def test_planner_routes_explanation_follow_up_to_prior_screen_aware_calculation() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "show the steps",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={
            "recent_context_resolutions": [
                {
                    "kind": "screen_awareness",
                    "intent": "solve_visible_problem",
                    "analysis_result": {
                        "calculation_activity": {
                            "status": "resolved",
                            "calculation_trace": {
                                "extracted_expression": "(48/3)+7^2",
                                "helper_used": None,
                                "result_visibility": "user_facing",
                            },
                            "calculation_result": {
                                "expression": "(48/3)+7^2",
                                "normalized_expression": "(48/3)+7^2",
                            },
                        }
                    },
                }
            ]
        },
    )

    assert decision.request_type == "calculation_response"
    assert decision.debug["calculations"]["candidate"] is True
    assert decision.debug["calculations"]["follow_up_reuse"] is True
    assert decision.debug["calculations"]["extracted_expression"] == "(48/3)+7^2"
    assert decision.debug["calculations"]["requested_mode"] == "step_by_step"


def test_planner_records_screen_awareness_candidate_without_hijacking_when_routing_is_disabled(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.planner_routing_enabled = False
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    decision = planner.plan(
        "what am I looking at",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "unclassified"
    assert decision.tool_requests == []
    assert decision.debug["screen_awareness"]["candidate"] is True
    assert decision.debug["screen_awareness"]["disposition"] == "routing_disabled"


def test_planner_routes_screen_grounded_request_to_phase1_analysis_when_enabled(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase1"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    decision = planner.plan(
        "what am I looking at",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "screen_awareness_response"
    assert decision.tool_requests == []
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "screen_awareness_request"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "screen_awareness_analyze"
    assert decision.response_mode == "summary_result"
    assert decision.capability_plan is not None
    assert decision.capability_plan.supported is True
    assert decision.capability_plan.missing_capabilities == []
    assert decision.unsupported_reason is None
    assert decision.assistant_message is None
    assert decision.debug["screen_awareness"]["disposition"] == "phase1_analyze"


def test_planner_routes_grounding_disambiguation_request_to_phase2_screen_awareness_when_enabled(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase2"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    decision = planner.plan(
        "which button are you talking about",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "screen_awareness_response"
    assert decision.tool_requests == []
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "screen_awareness_request"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "screen_awareness_analyze"
    assert decision.capability_plan is not None
    assert "screen_grounding" in decision.capability_plan.required_capabilities
    assert decision.debug["screen_awareness"]["disposition"] == "phase2_ground"


def test_planner_routes_guided_navigation_request_to_phase3_screen_awareness_when_enabled(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase3"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    decision = planner.plan(
        "what should I click next?",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "screen_awareness_response"
    assert decision.tool_requests == []
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "screen_awareness_request"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "screen_awareness_analyze"
    assert decision.capability_plan is not None
    assert "screen_grounding" in decision.capability_plan.required_capabilities
    assert "screen_guidance" in decision.capability_plan.required_capabilities
    assert decision.debug["screen_awareness"]["disposition"] == "phase3_guide"
    assert decision.debug["screen_awareness"]["intent"] == "guide_navigation"


def test_planner_routes_phase4_verification_request_to_screen_awareness_when_enabled(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase4"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    decision = planner.plan(
        "did that work?",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "screen_awareness_response"
    assert decision.tool_requests == []
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "screen_awareness_request"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "screen_awareness_analyze"
    assert decision.capability_plan is not None
    assert "screen_grounding" in decision.capability_plan.required_capabilities
    assert "screen_verification" in decision.capability_plan.required_capabilities
    assert decision.debug["screen_awareness"]["disposition"] == "phase4_verify"


def test_planner_routes_phase4_numeric_verification_request_to_screen_awareness_when_enabled(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase4"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    decision = planner.plan(
        "do these numbers add up?",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        active_context={
            "selection": {
                "kind": "text",
                "value": "2 + 2 + 4 + 4 + 4 + 4 + 5 + 10 = 28",
                "preview": "2 + 2 + 4 + 4 + 4 + 4 + 5 + 10 = 28",
            }
        },
    )

    assert decision.request_type == "screen_awareness_response"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "screen_awareness_analyze"
    assert decision.debug["screen_awareness"]["disposition"] == "phase4_verify"
    assert decision.debug["screen_awareness"]["intent"] == "verify_screen_state"


def test_planner_routes_phase5_action_request_to_screen_awareness_when_enabled(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase5"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.action_policy_mode = "confirm_before_act"
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    decision = planner.plan(
        "click the Save button",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "screen_awareness_response"
    assert decision.tool_requests == []
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "screen_awareness_request"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "screen_awareness_act"
    assert decision.response_mode == "action_result"
    assert decision.capability_plan is not None
    assert "screen_grounding" in decision.capability_plan.required_capabilities
    assert "screen_verification" in decision.capability_plan.required_capabilities
    assert "screen_action_execution" in decision.capability_plan.required_capabilities
    assert decision.debug["screen_awareness"]["disposition"] == "phase5_act"
    assert decision.debug["screen_awareness"]["intent"] == "execute_ui_action"


def test_planner_routes_phase6_continuity_request_to_screen_awareness_when_enabled(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase6"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    temp_config.screen_awareness.verification_enabled = True
    temp_config.screen_awareness.action_enabled = True
    temp_config.screen_awareness.memory_enabled = True
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    decision = planner.plan(
        "continue where we left off",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
        active_context={
            "recent_context_resolutions": [
                {
                    "kind": "screen_awareness",
                    "intent": "guide_navigation",
                    "analysis_result": {
                        "navigation_result": {
                            "step_state": {"status": "ready", "expected_target_label": "Continue"},
                        }
                    },
                }
            ]
        },
    )

    assert decision.request_type == "screen_awareness_response"
    assert decision.tool_requests == []
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "screen_awareness_request"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "screen_awareness_continue"
    assert decision.response_mode == "summary_result"
    assert decision.capability_plan is not None
    assert "screen_grounding" in decision.capability_plan.required_capabilities
    assert "screen_guidance" in decision.capability_plan.required_capabilities
    assert "screen_verification" in decision.capability_plan.required_capabilities
    assert "screen_continuity" in decision.capability_plan.required_capabilities
    assert decision.debug["screen_awareness"]["disposition"] == "phase6_continue"
    assert decision.debug["screen_awareness"]["intent"] == "continue_workflow"


def test_planner_preserves_phase2_grounding_route_for_explanation_requests_in_phase3(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase3"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    temp_config.screen_awareness.grounding_enabled = True
    temp_config.screen_awareness.guidance_enabled = True
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    decision = planner.plan(
        "what does this warning mean",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
        active_context={"selection": {"value": "Warning: Token expired"}, "clipboard": {}},
    )

    assert decision.capability_plan is not None
    assert "screen_grounding" in decision.capability_plan.required_capabilities
    assert "screen_guidance" not in decision.capability_plan.required_capabilities
    assert decision.debug["screen_awareness"]["disposition"] == "phase2_ground"


def test_planner_does_not_hijack_unrelated_requests_when_screen_awareness_is_on(temp_config) -> None:
    temp_config.screen_awareness.enabled = True
    temp_config.screen_awareness.phase = "phase1"
    temp_config.screen_awareness.planner_routing_enabled = True
    temp_config.screen_awareness.observation_enabled = True
    temp_config.screen_awareness.interpretation_enabled = True
    planner = DeterministicPlanner(screen_awareness_config=temp_config.screen_awareness)

    decision = planner.plan(
        "search GitHub for planner architecture",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "browser_search"
    assert decision.tool_requests
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.debug["screen_awareness"]["candidate"] is False
    assert decision.debug["screen_awareness"]["disposition"] == "not_requested"


def test_planner_routes_send_this_to_baby_to_discord_relay_preview(temp_config) -> None:
    planner = DeterministicPlanner(
        screen_awareness_config=temp_config.screen_awareness,
        calculations_config=temp_config.calculations,
        discord_relay_config=temp_config.discord_relay,
    )

    decision = planner.plan(
        "send this to Baby",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "discord_relay_dispatch"
    assert decision.tool_requests == []
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "discord_relay_request"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "discord_relay_preview"
    assert decision.response_mode == "action_result"
    assert decision.structured_query.slots["destination_alias"] == "Baby"
    assert decision.structured_query.slots["payload_hint"] == "contextual"


def test_planner_routes_discord_relay_confirmation_follow_up_to_dispatch(temp_config) -> None:
    planner = DeterministicPlanner(
        screen_awareness_config=temp_config.screen_awareness,
        calculations_config=temp_config.calculations,
        discord_relay_config=temp_config.discord_relay,
    )

    decision = planner.plan(
        "send it",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={
            "family": "discord_relay",
            "parameters": {
                "destination_alias": "Baby",
                "payload_hint": "page_link",
                "note_text": None,
                "pending_preview": {
                    "destination": {"alias": "Baby", "label": "Baby", "destination_kind": "personal_dm", "route_mode": "local_client_automation"},
                    "payload": {"kind": "page_link", "summary": "Current page", "provenance": "workspace_active_item", "confidence": 0.9, "url": "https://example.com"},
                    "policy": {"outcome": "allowed", "warnings": [], "blocks": [], "requires_confirmation": True},
                    "route_mode": "local_client_automation",
                    "state": "ready",
                },
            },
        },
        recent_tool_results=[],
    )

    assert decision.request_type == "discord_relay_dispatch"
    assert decision.tool_requests == []
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "discord_relay_dispatch"
    assert decision.structured_query is not None
    assert decision.structured_query.slots["request_stage"] == "dispatch"
    assert decision.structured_query.slots["pending_preview"]["route_mode"] == "local_client_automation"


def test_planner_routes_create_research_workspace_to_workspace_assembly() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "create a research workspace for motor torque",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "workspace_assembly"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "workspace_assemble"


def test_planner_routes_open_troubleshooting_workspace_to_workspace_restore() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open my troubleshooting workspace",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "workspace_restore"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "workspace_restore"


def test_planner_obeys_explicit_deck_routing_for_weather() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "show me the weather in the Deck",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "weather_current"
    assert decision.tool_requests[0].arguments["open_target"] == "deck"


def test_planner_mutates_weather_follow_up_to_tomorrow() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "what about tomorrow?",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state=_active_subject(
            "weather",
            forecast_target="current",
            open_target="none",
            location_mode="auto",
            allow_home_fallback=True,
        ),
        recent_tool_results=[
            {
                "tool_name": "weather_current",
                "family": "weather",
                "captured_at": "2026-04-19T00:00:00+00:00",
                "arguments": {"forecast_target": "current"},
                "result": {"data": {"location": {"label": "Queens, New York"}}},
            }
        ],
    )

    assert decision.request_type == "follow_up_grounded"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "weather_current"
    assert decision.tool_requests[0].arguments["forecast_target"] == "tomorrow"
    assert decision.tool_requests[0].arguments["open_target"] == "none"


def test_planner_mutates_weather_follow_up_to_answer_only() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "no, just answer, don't open anything",
        session_id="default",
        surface_mode="deck",
        active_module="browser",
        workspace_context=None,
        active_posture={},
        active_request_state=_active_subject(
            "weather",
            forecast_target="current",
            open_target="deck",
            location_mode="auto",
            allow_home_fallback=True,
        ),
        recent_tool_results=[
            {
                "tool_name": "weather_current",
                "family": "weather",
                "captured_at": "2026-04-19T00:00:00+00:00",
                "arguments": {"forecast_target": "current", "open_target": "deck"},
                "result": {"data": {"deck_url": "https://weather.test"}},
            }
        ],
    )

    assert decision.request_type == "follow_up_grounded"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "weather_current"
    assert decision.tool_requests[0].arguments["forecast_target"] == "current"
    assert decision.tool_requests[0].arguments["open_target"] == "none"


def test_planner_routes_recent_power_follow_up_to_projection_tool() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "how long until 100%?",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state=_active_subject("power", focus="level"),
        recent_tool_results=[
            {
                "tool_name": "power_status",
                "family": "power",
                "captured_at": "2026-04-19T00:00:00+00:00",
                "arguments": {"focus": "level"},
                "result": {"data": {"battery_percent": 72, "ac_line_status": "online"}},
            }
        ],
    )

    assert decision.request_type == "follow_up_grounded"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "power_projection"
    assert decision.tool_requests[0].arguments["metric"] == "time_to_percent"
    assert decision.tool_requests[0].arguments["target_percent"] == 100
    assert decision.tool_requests[0].arguments["assume_unplugged"] is False


def test_planner_mutates_power_projection_follow_up_to_unplugged_threshold() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "how long until 50% if I unplug now?",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state=_active_subject(
            "power_projection",
            metric="time_to_percent",
            target_percent=100,
            assume_unplugged=False,
        ),
        recent_tool_results=[
            {
                "tool_name": "power_projection",
                "family": "power",
                "captured_at": "2026-04-19T00:01:00+00:00",
                "arguments": {"metric": "time_to_percent", "target_percent": 100, "assume_unplugged": False},
                "result": {"data": {"battery_percent": 72, "ac_line_status": "online"}},
            }
        ],
    )

    assert decision.request_type == "follow_up_grounded"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "power_projection"
    assert decision.tool_requests[0].arguments["metric"] == "time_to_percent"
    assert decision.tool_requests[0].arguments["target_percent"] == 50
    assert decision.tool_requests[0].arguments["assume_unplugged"] is True


def test_planner_routes_battery_drain_question_to_power_diagnosis() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "is my battery draining unusually fast?",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "deterministic_diagnostic_request"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "power_diagnosis"


def test_planner_routes_machine_slowdown_question_to_resource_diagnosis() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "what's slowing this machine down?",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "deterministic_diagnostic_request"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "resource_diagnosis"


def test_planner_routes_gpu_identity_question_to_identity_metric() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "what GPU do I have",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_deterministic_fact"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "resource_status"
    assert decision.tool_requests[0].arguments["focus"] == "gpu"
    assert decision.tool_requests[0].arguments["query_kind"] == "identity"
    assert decision.tool_requests[0].arguments["metric"] == "identity"


def test_planner_routes_current_gpu_usage_question_to_live_metric() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "what is my GPU at currently",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_deterministic_fact"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "resource_status"
    assert decision.tool_requests[0].arguments["focus"] == "gpu"
    assert decision.tool_requests[0].arguments["query_kind"] == "telemetry"
    assert decision.tool_requests[0].arguments["metric"] == "usage"


def test_planner_routes_cpu_temp_question_to_temperature_metric() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "CPU temp",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_deterministic_fact"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "resource_status"
    assert decision.tool_requests[0].arguments["focus"] == "cpu"
    assert decision.tool_requests[0].arguments["query_kind"] == "telemetry"
    assert decision.tool_requests[0].arguments["metric"] == "temperature"


def test_planner_routes_direct_domain_browser_open_to_external_url_plan() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open docs.python.org in Firefox",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.structured_query is not None
    assert decision.structured_query.query_shape == "open_browser_destination"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "resolve_url_then_open_in_browser"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://docs.python.org/"
    assert decision.tool_requests[0].arguments["browser_target"] == "firefox"
    assert decision.structured_query.slots["destination_type"] == "direct_domain"
    assert decision.structured_query.slots["destination_resolution_kind"] == "direct_domain"
    assert decision.structured_query.slots["destination_site_domain"] == "docs.python.org"


def test_planner_routes_expanded_native_browser_search_provider_catalog() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "search tripadvisor for boston hotels in chrome",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.structured_query is not None
    assert decision.structured_query.query_shape == "search_browser_destination"
    assert decision.execution_plan is not None
    assert decision.execution_plan.plan_type == "resolve_search_url_then_open_in_browser"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://www.tripadvisor.com/Search?q=boston+hotels"
    assert decision.tool_requests[0].arguments["browser_target"] == "chrome"
    assert decision.structured_query.slots["search_provider"] == "tripadvisor"
    assert decision.structured_query.slots["search_resolution_kind"] == "native_provider"


def test_planner_routes_gpu_under_load_question_to_resource_interpretation() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "is my GPU under load",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "deterministic_diagnostic_request"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "resource_status"
    assert decision.tool_requests[0].arguments["focus"] == "gpu"
    assert decision.tool_requests[0].arguments["query_kind"] == "diagnostic"
    assert decision.tool_requests[0].arguments["metric"] == "usage"


def test_planner_distinguishes_current_location_from_saved_home_request() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "what is my current location",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_deterministic_fact"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "location_status"
    assert decision.tool_requests[0].arguments["mode"] == "current"
    assert decision.tool_requests[0].arguments["allow_home_fallback"] is False


def test_planner_routes_save_home_location_to_deterministic_tool() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "save this as my home location",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state=_active_subject("weather", forecast_target="current", location_mode="current"),
        recent_tool_results=[
            {
                "tool_name": "weather_current",
                "family": "weather",
                "captured_at": "2026-04-19T00:00:00+00:00",
                "arguments": {"forecast_target": "current"},
                "result": {"data": {"location": {"label": "Queens, New York", "source": "approximate_device"}}},
            }
        ],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "save_location"
    assert decision.tool_requests[0].arguments["target"] == "home"
    assert decision.tool_requests[0].arguments["source_mode"] == "current"


def test_planner_routes_open_location_settings_to_external_settings_uri() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open location settings",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "ms-settings:privacy-location"


def test_planner_answers_weather_source_follow_up_from_structured_state() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "which location did you use?",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state=_active_subject("weather", forecast_target="current", location_mode="current"),
        recent_tool_results=[
            {
                "tool_name": "weather_current",
                "family": "weather",
                "captured_at": "2026-04-19T00:00:00+00:00",
                "arguments": {"forecast_target": "current"},
                "result": {"data": {"location": {"label": "Queens, New York", "source": "approximate_device"}}},
            }
        ],
    )

    assert decision.request_type == "follow_up_grounded"
    assert decision.tool_requests == []
    assert decision.assistant_message is not None
    assert "approximate device fix" in decision.assistant_message.lower()


def test_planner_routes_named_location_weather_request_through_deterministic_weather_tool() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "what's the weather for my studio location",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_deterministic_fact"
    assert decision.tool_requests[0].tool_name == "weather_current"
    assert decision.tool_requests[0].arguments["location_mode"] == "named"
    assert decision.tool_requests[0].arguments["named_location"] == "studio"


def test_planner_routes_explicit_town_state_weather_request_through_place_query() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "what's the weather in Concord, New Hampshire",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_deterministic_fact"
    assert decision.tool_requests[0].tool_name == "weather_current"
    assert decision.tool_requests[0].arguments["location_mode"] == "named"
    assert decision.tool_requests[0].arguments["named_location"] == "concord, new hampshire"


def test_planner_routes_zip_code_weather_request_through_place_query() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "what's the weather in 90210",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_deterministic_fact"
    assert decision.tool_requests[0].tool_name == "weather_current"
    assert decision.tool_requests[0].arguments["location_mode"] == "named"
    assert decision.tool_requests[0].arguments["named_location"] == "90210"


def test_planner_tolerates_weather_shorthand_and_routes_tomorrow_forecast() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "whats the weather tmrw",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "deterministic_projection_request"
    assert decision.tool_requests[0].tool_name == "weather_current"
    assert decision.tool_requests[0].arguments["forecast_target"] == "tomorrow"
    assert decision.tool_requests[0].arguments["open_target"] == "none"


def test_planner_tolerates_battery_shorthand_and_routes_to_power_status() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "how much bat do i got left",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_deterministic_fact"
    assert decision.tool_requests[0].tool_name == "power_status"
    assert decision.tool_requests[0].arguments["focus"] == "level"


def test_planner_tolerates_resource_shorthand_for_ram_usage() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "ram usage rn",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_deterministic_fact"
    assert decision.tool_requests[0].tool_name == "resource_status"
    assert decision.tool_requests[0].arguments["focus"] == "ram"


def test_planner_routes_clear_workspace_directly_without_reasoner() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "clear workspace",
        session_id="default",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={"workspace": {"workspaceId": "ws-1", "name": "Packaging Workspace"}},
        active_posture={"workspace": {"workspaceId": "ws-1", "name": "Packaging Workspace"}},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "workspace_clear"


def test_planner_routes_cleanup_routine_to_saved_routine_execution() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "run my cleanup routine",
        session_id="default",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "routine_execution"
    assert decision.tool_requests[0].tool_name == "routine_execute"
    assert decision.tool_requests[0].arguments["routine_name"] == "cleanup routine"


def test_planner_routes_save_this_as_a_routine_from_active_repair_state() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "save this as a routine called network health check",
        session_id="default",
        surface_mode="deck",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state=_active_subject("repair", repair_kind="connectivity_checks", target="network"),
        recent_tool_results=[],
    )

    assert decision.request_type == "routine_save"
    assert decision.tool_requests[0].tool_name == "routine_save"
    assert decision.tool_requests[0].arguments["routine_name"] == "network health check"
    assert decision.tool_requests[0].arguments["execution_kind"] == "repair"
    assert decision.tool_requests[0].arguments["parameters"]["repair_kind"] == "connectivity_checks"


def test_planner_routes_archive_old_screenshots_to_maintenance_action() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "archive old screenshots",
        session_id="default",
        surface_mode="deck",
        active_module="files",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "maintenance_execution"
    assert decision.tool_requests[0].tool_name == "maintenance_action"
    assert decision.tool_requests[0].arguments["maintenance_kind"] == "archive_old_screenshots"


def test_planner_routes_rename_screenshots_by_date_to_file_operation() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "rename these screenshots by date",
        session_id="default",
        surface_mode="deck",
        active_module="files",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "file_operation"
    assert decision.tool_requests[0].tool_name == "file_operation"
    assert decision.tool_requests[0].arguments["operation"] == "rename_by_date"


def test_planner_routes_explicit_trusted_hook_execution() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "run trusted hook project log collector",
        session_id="default",
        surface_mode="deck",
        active_module="watch",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "trusted_hook_execution"
    assert decision.tool_requests[0].tool_name == "trusted_hook_execute"
    assert decision.tool_requests[0].arguments["hook_name"] == "project log collector"


def test_planner_routes_open_what_i_copied_to_context_action() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open what I copied",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
        active_context={
            "clipboard": {
                "kind": "url",
                "value": "https://example.com/docs",
                "preview": "https://example.com/docs",
            }
        },
    )

    assert decision.request_type == "context_action"
    assert decision.tool_requests[0].tool_name == "context_action"
    assert decision.tool_requests[0].arguments["operation"] == "open"
    assert decision.tool_requests[0].arguments["source"] == "clipboard"


def test_planner_routes_turn_this_into_tasks_using_selection() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "turn this into tasks",
        session_id="default",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context={"workspace": {"workspaceId": "ws-1", "name": "Packaging Workspace"}},
        active_posture={"workspace": {"workspaceId": "ws-1", "name": "Packaging Workspace"}},
        active_request_state={},
        recent_tool_results=[],
        active_context={
            "selection": {
                "kind": "text",
                "value": "Update README\nCheck installer\nShip release notes",
                "preview": "Update README",
            }
        },
    )

    assert decision.request_type == "context_action"
    assert decision.tool_requests[0].tool_name == "context_action"
    assert decision.tool_requests[0].arguments["operation"] == "extract_tasks"
    assert decision.tool_requests[0].arguments["source"] == "selection"


def test_planner_routes_close_snipping_tool_to_app_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "close Snipping Tool",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "app_control"
    assert decision.tool_requests[0].arguments["action"] == "close"
    assert decision.tool_requests[0].arguments["app_name"] == "snipping tool"


def test_planner_clarifies_ambiguous_delete_scope() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "delete that folder",
        session_id="default",
        surface_mode="ghost",
        active_module="files",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
        active_context={},
    )

    assert decision.tool_requests == []
    assert decision.assistant_message == "Delete scope is too broad without a clearer target."


def test_planner_routes_network_diagnostic_questions_to_diagnosis_tool() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "why does my internet keep skipping?",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "deterministic_diagnostic_request"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "network_diagnosis"
    assert decision.tool_requests[0].arguments["focus"] == "overview"
    assert decision.tool_requests[0].arguments["diagnostic_burst"] is True


def test_planner_mutates_network_follow_up_to_local_vs_upstream_attribution() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "is this my router or the isp?",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state=_active_subject("network_diagnosis", focus="overview", diagnostic_burst=True),
        recent_tool_results=[
            {
                "tool_name": "network_diagnosis",
                "family": "network_diagnosis",
                "captured_at": "2026-04-20T00:00:00+00:00",
                "arguments": {"focus": "overview", "diagnostic_burst": True},
                "result": {"data": {"assessment": {"headline": "Local Wi-Fi instability likely"}}},
            }
        ],
    )

    assert decision.request_type == "follow_up_grounded"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "network_diagnosis"
    assert decision.tool_requests[0].arguments["focus"] == "attribution"


def test_planner_routes_focus_app_command_to_deterministic_app_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "focus Visual Studio Code",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "app_control"
    assert decision.tool_requests[0].arguments["action"] == "focus"
    assert decision.tool_requests[0].arguments["app_name"] == "visual studio code"


def test_planner_routes_force_quit_command_to_deterministic_app_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "force quit Chrome",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert len(decision.tool_requests) == 1
    assert decision.tool_requests[0].tool_name == "app_control"
    assert decision.tool_requests[0].arguments["action"] == "force_quit"
    assert decision.tool_requests[0].arguments["app_name"] == "chrome"


def test_planner_routes_minimize_request_to_app_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "minimize spotify",
        session_id="default",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "app_control"
    assert decision.tool_requests[0].arguments["action"] == "minimize"
    assert decision.tool_requests[0].arguments["app_name"] == "spotify"


def test_planner_routes_maximize_request_to_app_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "maximize discord",
        session_id="default",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "app_control"
    assert decision.tool_requests[0].arguments["action"] == "maximize"
    assert decision.tool_requests[0].arguments["app_name"] == "discord"


def test_planner_routes_restore_window_request_to_app_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "restore vscode",
        session_id="default",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "app_control"
    assert decision.tool_requests[0].arguments["action"] == "restore"
    assert decision.tool_requests[0].arguments["app_name"] == "vscode"


def test_planner_routes_open_app_command_to_deterministic_app_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open Chrome",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "app_control"
    assert decision.tool_requests[0].arguments["action"] == "launch"
    assert decision.tool_requests[0].arguments["app_name"] == "chrome"


def test_planner_routes_maximize_this_to_window_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "maximize this",
        session_id="default",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "window_control"
    assert decision.tool_requests[0].arguments["action"] == "maximize"
    assert decision.tool_requests[0].arguments["target_mode"] == "focused"


def test_planner_routes_snap_right_request_to_window_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "snap Spotify to the right",
        session_id="default",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "window_control"
    assert decision.tool_requests[0].arguments["action"] == "snap_right"
    assert decision.tool_requests[0].arguments["app_name"] == "spotify"


def test_planner_routes_move_to_monitor_request_to_window_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "move Chrome to monitor 2",
        session_id="default",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "window_control"
    assert decision.tool_requests[0].arguments["action"] == "move_to_monitor"
    assert decision.tool_requests[0].arguments["app_name"] == "chrome"
    assert decision.tool_requests[0].arguments["monitor_index"] == 2


def test_planner_routes_lock_computer_to_system_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "lock my computer",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "system_control"
    assert decision.tool_requests[0].arguments["action"] == "lock"


def test_planner_routes_volume_command_to_system_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "turn volume down to 20%",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "system_control"
    assert decision.tool_requests[0].arguments["action"] == "set_volume"
    assert decision.tool_requests[0].arguments["value"] == 20


def test_planner_routes_open_task_manager_to_system_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open Task Manager",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "system_control"
    assert decision.tool_requests[0].arguments["action"] == "open_task_manager"


def test_planner_routes_open_bluetooth_settings_to_system_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open Bluetooth settings",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "system_control"
    assert decision.tool_requests[0].arguments["action"] == "open_settings_page"
    assert decision.tool_requests[0].arguments["target"] == "bluetooth"


def test_planner_routes_toggle_wifi_off_to_system_control() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "turn wi-fi off",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "system_control"
    assert decision.tool_requests[0].arguments["action"] == "toggle_wifi"
    assert decision.tool_requests[0].arguments["state"] == "off"


def test_planner_routes_writing_setup_to_workflow_execute() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "set up my writing environment",
        session_id="default",
        surface_mode="deck",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "workflow_execution"
    assert decision.tool_requests[0].tool_name == "workflow_execute"
    assert decision.tool_requests[0].arguments["workflow_kind"] == "writing_setup"


def test_planner_routes_find_latest_pdf_and_open_to_search_and_act() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "find the latest PDF and open it",
        session_id="default",
        surface_mode="ghost",
        active_module="files",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "search_and_act"
    assert decision.tool_requests[0].tool_name == "desktop_search"
    assert decision.tool_requests[0].arguments["action"] == "open"
    assert decision.tool_requests[0].arguments["latest_only"] is True
    assert ".pdf" in decision.tool_requests[0].arguments["file_extensions"]


def test_planner_routes_open_documents_file_request_to_desktop_search() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open the Stormhelm docs in Documents",
        session_id="default",
        surface_mode="ghost",
        active_module="files",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "search_and_act"
    assert decision.tool_requests[0].tool_name == "desktop_search"
    assert decision.tool_requests[0].arguments["action"] == "open"
    assert decision.tool_requests[0].arguments["domains"] == ["files"]
    assert decision.tool_requests[0].arguments["folder_hint"] == "Documents"
    assert decision.tool_requests[0].arguments["prefer_folders"] is False


def test_planner_routes_show_folder_request_to_desktop_search_preferring_folders() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "show the screenshots folder in Pictures",
        session_id="default",
        surface_mode="ghost",
        active_module="files",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "search_and_act"
    assert decision.tool_requests[0].tool_name == "desktop_search"
    assert decision.tool_requests[0].arguments["action"] == "open"
    assert decision.tool_requests[0].arguments["domains"] == ["files"]
    assert decision.tool_requests[0].arguments["folder_hint"] == "Pictures"
    assert decision.tool_requests[0].arguments["prefer_folders"] is True


def test_planner_routes_fix_wifi_to_repair_action() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "try fixing my Wi-Fi",
        session_id="default",
        surface_mode="ghost",
        active_module="systems",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "repair_execution"
    assert decision.tool_requests[0].tool_name == "repair_action"
    assert decision.tool_requests[0].arguments["repair_kind"] == "network_repair"


def test_planner_routes_known_site_browser_destination_to_external_open_url() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open YouTube in a browser",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "open_browser_destination"
    assert decision.structured_query.execution_type == "resolve_url_then_open_in_browser"
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://www.youtube.com/"
    assert decision.structured_query.slots["destination_name"] == "youtube"
    assert decision.structured_query.slots["destination_scope"] == "general"


def test_planner_routes_personal_youtube_history_browser_destination_to_known_history_url() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open my personal youtube history in a browser",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "open_browser_destination"
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://www.youtube.com/feed/history"
    assert decision.structured_query.slots["destination_name"] == "youtube_history"
    assert decision.structured_query.slots["destination_scope"] == "personal"


def test_planner_routes_youtube_search_phrase_to_browser_search_open() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "search YouTube for lo-fi music",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "browser_search"
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://www.youtube.com/results?search_query=lo-fi+music"
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "search_browser_destination"
    assert decision.structured_query.execution_type == "resolve_search_url_then_open_in_browser"
    assert decision.structured_query.slots["search_provider"] == "youtube"


def test_planner_routes_lookup_phrase_to_web_search_open() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "look up OpenAI pricing",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "browser_search"
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://www.google.com/search?q=OpenAI+pricing"
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "search_browser_destination"
    assert decision.structured_query.slots["search_provider"] == "web"


def test_planner_routes_known_destination_search_phrase_to_site_search_open() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "search OpenAI for pricing",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "browser_search"
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://www.google.com/search?q=site%3Aopenai.com+pricing"
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "search_browser_destination"
    assert decision.structured_query.execution_type == "resolve_search_url_then_open_in_browser"
    assert decision.structured_query.slots["search_provider"] == "openai"


def test_planner_routes_domain_phrase_to_site_search_open() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "search docs.python.org for pathlib glob",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "browser_search"
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://www.google.com/search?q=site%3Adocs.python.org+pathlib+glob"
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "search_browser_destination"
    assert decision.structured_query.slots["search_provider"] == "docs.python.org"


def test_planner_routes_browser_destination_with_explicit_browser_target() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open Gmail in Firefox",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "direct_action"
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://mail.google.com/mail/u/0/#inbox"
    assert decision.tool_requests[0].arguments["browser_target"] == "firefox"
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "open_browser_destination"
    assert decision.structured_query.slots["browser_preference"] == "firefox"


def test_planner_routes_browser_search_with_explicit_browser_target() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "search github for issue templates in chrome",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "browser_search"
    assert decision.tool_requests[0].tool_name == "external_open_url"
    assert decision.tool_requests[0].arguments["url"] == "https://github.com/search?q=issue+templates"
    assert decision.tool_requests[0].arguments["browser_target"] == "chrome"
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "search_browser_destination"
    assert decision.structured_query.slots["browser_preference"] == "chrome"


def test_planner_reports_unknown_browser_search_provider_specifically() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "search orbitz for flights",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
    )

    assert decision.request_type == "browser_search"
    assert decision.tool_requests == []
    assert decision.assistant_message == "I couldn't determine which browser search route to use for that request."
    assert decision.structured_query is not None
    assert decision.structured_query.query_shape.value == "search_browser_destination"
    assert decision.structured_query.slots["browser_search_failure_reason"] == "search_provider_unresolved"


def test_planner_reports_browser_open_capability_unavailable_specifically() -> None:
    planner = DeterministicPlanner()

    decision = planner.plan(
        "open Gmail in a browser",
        session_id="default",
        surface_mode="ghost",
        active_module="chartroom",
        workspace_context=None,
        active_posture={},
        active_request_state={},
        recent_tool_results=[],
        available_tools={"app_control"},
    )

    assert decision.request_type == "unsupported_capability"
    assert decision.unsupported_reason is not None
    assert decision.unsupported_reason.code == "browser_opening_unavailable"
    assert decision.assistant_message == "Browser opening isn't available in the current environment."
