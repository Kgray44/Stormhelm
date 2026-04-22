from __future__ import annotations

from decimal import Decimal

from stormhelm.config.models import CalculationsConfig
from stormhelm.core.calculations import CalculationFailureType
from stormhelm.core.calculations import CalculationCallerContext
from stormhelm.core.calculations import CalculationInputOrigin
from stormhelm.core.calculations import CalculationOutputMode
from stormhelm.core.calculations import CalculationProvenance
from stormhelm.core.calculations import CalculationRequest
from stormhelm.core.calculations import CalculationResultVisibility
from stormhelm.core.calculations import build_helper_registry
from stormhelm.core.calculations import build_calculations_subsystem


def test_calculations_subsystem_evaluates_simple_expression() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="2+2",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("4")
    assert response.result.formatted_value == "4"
    assert response.result.provenance == CalculationProvenance.DETERMINISTIC_LOCAL_EXPRESSION
    assert response.trace.extracted_expression == "2+2"
    assert response.trace.normalized_expression == "2+2"
    assert response.trace.parse_success is True


def test_calculations_subsystem_evaluates_operator_precedence_and_exponentiation() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="(48/3)+7^2",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("65")
    assert response.result.formatted_value == "65"
    assert response.trace.parse_success is True


def test_calculations_subsystem_supports_step_by_step_for_direct_expression() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="(48/3)+7^2",
        surface_mode="ghost",
        active_module="chartroom",
        request=CalculationRequest(
            request_id="calc-direct-steps",
            source_surface="ghost",
            raw_input="(48/3)+7^2",
            user_visible_text="(48/3)+7^2",
            extracted_expression="(48/3)+7^2",
            requested_mode=CalculationOutputMode.STEP_BY_STEP,
        ),
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.explanation is not None
    assert response.result.explanation.mode == CalculationOutputMode.STEP_BY_STEP
    assert response.result.explanation.steps == [
        "48 / 3 = 16",
        "7 ^ 2 = 49",
        "16 + 49 = 65",
    ]
    assert response.assistant_response == "48 / 3 = 16\n7 ^ 2 = 49\n16 + 49 = 65"
    assert response.trace.explanation_mode_used == "step_by_step"


def test_calculations_subsystem_preserves_decimal_precision_for_simple_arithmetic() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="2.5+3.25",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("5.75")
    assert response.result.formatted_value == "5.75"


def test_calculations_subsystem_normalizes_engineering_suffix_tokens_deterministically() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="3.3k * 2.2mA",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("7.26")
    assert response.result.formatted_value == "7.26"
    assert response.trace.normalized_expression == "3300*0.0022"
    assert response.trace.parse_success is True


def test_calculations_subsystem_preserves_scientific_notation_with_clean_display() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="1.2e-3 * 4700",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("5.64")
    assert response.result.formatted_value == "5.64"
    assert response.trace.normalized_expression == "1.2e-3*4700"


def test_calculations_subsystem_formats_tiny_values_in_engineering_notation_when_helpful() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="47nF * 10k",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("0.00047")
    assert response.result.formatted_value == "470u"
    assert response.trace.result == "470u"


def test_calculations_subsystem_reports_honest_failure_for_malformed_expression() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="calculate 2+*",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.result is None
    assert response.failure is not None
    assert response.failure.failure_type == CalculationFailureType.PARSE_ERROR
    assert response.trace.parse_success is False
    assert "parse" in response.assistant_response.lower()


def test_calculations_subsystem_rejects_invalid_engineering_suffix_combinations_honestly() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="calculate 4.7kk",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.result is None
    assert response.failure is not None
    assert response.trace.parse_success is False
    assert response.trace.failure_stage == "normalization"
    assert "suffix" in response.assistant_response.lower()


def test_calculations_subsystem_rejects_unsupported_attached_unit_text_without_guessing() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="calculate 4.7kg * 2",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.result is None
    assert response.failure is not None
    assert response.trace.parse_success is False
    assert response.trace.failure_stage == "normalization"
    assert "unsupported" in response.failure.internal_reason.lower() or "unit" in response.failure.user_safe_message.lower()


def test_helper_registry_exposes_approved_calc2_helper_set() -> None:
    registry = build_helper_registry()

    assert {
        "voltage_from_current_resistance",
        "current_from_voltage_resistance",
        "resistance_from_voltage_current",
        "power_from_voltage_current",
        "power_from_current_resistance",
        "power_from_voltage_resistance",
        "series_resistance",
        "parallel_resistance",
        "voltage_divider",
        "rc_cutoff",
        "percent_change",
        "percent_error",
        "sum_list",
        "average_list",
        "min_list",
        "max_list",
    }.issubset(set(registry.helper_names()))


def test_calculations_subsystem_handles_power_helper_deterministically() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="power at 12V and 1.5A",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("18")
    assert response.result.formatted_value == "18 W"
    assert response.result.provenance == CalculationProvenance.DETERMINISTIC_LOCAL_HELPER
    assert response.result.helper_used == "power_from_voltage_current"
    assert response.trace.helper_used == "power_from_voltage_current"
    assert response.assistant_response == "Power = 18 W"


def test_calculations_subsystem_supports_formula_substitution_for_helpers() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="power at 12V and 1.5A",
        surface_mode="ghost",
        active_module="chartroom",
        request=CalculationRequest(
            request_id="calc-helper-formula",
            source_surface="ghost",
            raw_input="power at 12V and 1.5A",
            user_visible_text="power at 12V and 1.5A",
            requested_mode=CalculationOutputMode.FORMULA_SUBSTITUTION,
            helper_name="power_from_voltage_current",
            arguments={"voltage": {"value": "12", "normalized_expression": "12"}, "current": {"value": "1.5", "normalized_expression": "1.5"}},
        ),
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.explanation is not None
    assert response.result.explanation.formula == "P = V * I"
    assert response.result.explanation.substitution_rows == ["P = 12 * 1.5"]
    assert response.assistant_response == "P = V * I\nP = 12 * 1.5\nP = 18 W"
    assert response.trace.explanation_mode_used == "formula_substitution"


def test_calculations_subsystem_supports_verification_explanations() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="verify 2+2+4+4+4+4+5+10 = 28",
        surface_mode="ghost",
        active_module="chartroom",
        request=CalculationRequest(
            request_id="calc-verify",
            source_surface="ghost",
            raw_input="verify 2+2+4+4+4+4+5+10 = 28",
            user_visible_text="verify 2+2+4+4+4+4+5+10 = 28",
            extracted_expression="2+2+4+4+4+4+5+10",
            requested_mode=CalculationOutputMode.VERIFICATION_EXPLANATION,
            verification_claim="28",
        ),
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.provenance == CalculationProvenance.DETERMINISTIC_LOCAL_VERIFICATION
    assert response.result.verification is not None
    assert response.result.verification.matches is False
    assert response.assistant_response == "2 + 2 + 4 + 4 + 4 + 4 + 5 + 10 = 35, so 28 is incorrect."
    assert response.trace.explanation_mode_used == "verification_explanation"
    assert response.trace.verification_match is False


def test_calculations_subsystem_handles_ohms_law_current_helper() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what is current at 24V and 8 ohms",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("3")
    assert response.result.formatted_value == "3 A"
    assert response.result.helper_used == "current_from_voltage_resistance"
    assert response.assistant_response == "Current = 3 A"


def test_calculations_subsystem_handles_ohms_law_voltage_helper() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="what is voltage at 2A and 8 ohms",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("16")
    assert response.result.formatted_value == "16 V"
    assert response.result.helper_used == "voltage_from_current_resistance"
    assert response.assistant_response == "Voltage = 16 V"


def test_calculations_subsystem_handles_parallel_resistance_helper() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="parallel resistance of 220 and 330",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("132")
    assert response.result.formatted_value == "132 ohms"
    assert response.result.helper_used == "parallel_resistance"
    assert response.assistant_response == "Parallel resistance = 132 ohms"


def test_calculations_subsystem_handles_series_resistance_helper() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="series resistance of 100, 220, 470",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("790")
    assert response.result.formatted_value == "790 ohms"
    assert response.result.helper_used == "series_resistance"


def test_calculations_subsystem_handles_rc_cutoff_helper() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="RC cutoff for 10k and 0.1uF",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.helper_used == "rc_cutoff"
    assert response.result.formatted_value == "159.155 Hz"
    assert response.trace.helper_used == "rc_cutoff"
    assert response.trace.display_is_approximate is True
    assert response.assistant_response == "RC cutoff ≈ 159.155 Hz"


def test_calculations_subsystem_handles_percent_change_helper() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="percent change from 40 to 55",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("37.5")
    assert response.result.formatted_value == "37.5%"
    assert response.result.helper_used == "percent_change"
    assert response.assistant_response == "Percent change = 37.5%"


def test_calculations_subsystem_handles_percent_error_helper() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="percent error from 100 to 92",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("8")
    assert response.result.formatted_value == "8%"
    assert response.result.helper_used == "percent_error"
    assert response.assistant_response == "Percent error = 8%"


def test_calculations_subsystem_handles_average_list_helper() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="average of 12, 15, 19, 22",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("17")
    assert response.result.formatted_value == "17"
    assert response.result.helper_used == "average_list"
    assert response.assistant_response == "Average = 17"


def test_calculations_subsystem_handles_voltage_divider_helper() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="voltage divider for 12V with 220 and 330",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.failure is None
    assert response.result is not None
    assert response.result.numeric_value == Decimal("7.2")
    assert response.result.formatted_value == "7.2 V"
    assert response.result.helper_used == "voltage_divider"
    assert response.assistant_response == "Voltage divider output = 7.2 V"


def test_calculations_subsystem_asks_briefly_when_helper_request_is_under_specified() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="power at 12V",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.result is None
    assert response.failure is not None
    assert response.failure.failure_type == CalculationFailureType.HELPER_UNDER_SPECIFIED
    assert response.trace.failure_stage == "helper_match"
    assert "current or resistance" in response.assistant_response.lower()


def test_calculations_subsystem_rejects_ambiguous_helper_target_without_guessing() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.handle_request(
        session_id="default",
        operator_text="ohms law with 12V and 220 ohms",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.result is None
    assert response.failure is not None
    assert response.failure.failure_type == CalculationFailureType.HELPER_AMBIGUOUS
    assert response.trace.failure_stage == "helper_match"
    assert "voltage, current, or resistance" in response.assistant_response.lower()


def test_calculations_shared_execute_seam_preserves_cross_subsystem_caller_trace() -> None:
    subsystem = build_calculations_subsystem(CalculationsConfig())

    response = subsystem.execute(
        session_id="default",
        active_module="chartroom",
        request=CalculationRequest(
            request_id="calc-screen-trace",
            source_surface="ghost",
            raw_input="2+2",
            user_visible_text="2+2",
            extracted_expression="2+2",
            caller=CalculationCallerContext(
                subsystem="screen_awareness",
                caller_intent="numeric_screen_verification",
                input_origin=CalculationInputOrigin.SCREEN_SELECTION,
                visual_extraction_dependency=True,
                internal_validation=True,
                result_visibility=CalculationResultVisibility.SILENT_INTERNAL,
                reuse_path="screen_awareness.verification",
                provenance_stack=["screen_selection", "numeric_screen_verification"],
                evidence_confidence=0.78,
                evidence_confidence_note="Selected screen text provided a bounded numeric claim.",
            ),
        ),
    )

    assert response.failure is None
    assert response.result is not None
    assert response.trace.caller_subsystem == "screen_awareness"
    assert response.trace.caller_intent == "numeric_screen_verification"
    assert response.trace.input_origin == "screen_selection"
    assert response.trace.visual_extraction_dependency is True
    assert response.trace.internal_validation is True
    assert response.trace.result_visibility == "silent_internal"
    assert response.trace.caller_reuse_path == "screen_awareness.verification"
    assert response.trace.provenance_stack[:2] == ["screen_selection", "numeric_screen_verification"]
    assert response.trace.provenance_stack[-1] == CalculationProvenance.DETERMINISTIC_LOCAL_EXPRESSION.value
    assert response.result.provenance_stack[-1] == CalculationProvenance.DETERMINISTIC_LOCAL_EXPRESSION.value
