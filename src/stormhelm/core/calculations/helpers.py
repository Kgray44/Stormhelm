from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from decimal import InvalidOperation
from decimal import ROUND_HALF_UP
from functools import lru_cache
import re
from typing import Any
from typing import Callable

from stormhelm.core.calculations.formatter import FormattedCalculationValue
from stormhelm.core.calculations.formatter import format_calculation_value
from stormhelm.core.calculations.formatter import format_decimal
from stormhelm.core.calculations.models import CalculationFailureType
from stormhelm.core.calculations.normalizer import CalculationNormalizationError
from stormhelm.core.calculations.normalizer import normalize_expression_text
from stormhelm.core.calculations.parser import CalculationParseError
from stormhelm.core.calculations.parser import parse_expression
from stormhelm.core.calculations.evaluator import CalculationEvaluationError
from stormhelm.core.calculations.evaluator import evaluate_expression


_POWER_PATTERN = re.compile(r"\bpower\b(?:\s+(?:at|from|with|for))?\s+(?P<tail>.+)$", re.IGNORECASE)
_CURRENT_PATTERN = re.compile(r"(?:what(?:'s| is)\s+)?current\b(?:\s+(?:at|from|with|for))?\s+(?P<tail>.+)$", re.IGNORECASE)
_OHMS_LAW_PATTERN = re.compile(r"\bohm'?s law\b(?:\s+(?:with|for))?\s+(?P<tail>.+)$", re.IGNORECASE)
_PARALLEL_RESISTANCE_PATTERN = re.compile(r"\bparallel resistance\b(?:\s+of)?\s+(?P<tail>.+)$", re.IGNORECASE)
_SERIES_RESISTANCE_PATTERN = re.compile(r"\bseries resistance\b(?:\s+of)?\s+(?P<tail>.+)$", re.IGNORECASE)
_RC_CUTOFF_PATTERN = re.compile(
    r"(?:what(?:'s| is)\s+)?(?:the\s+)?rc cutoff(?:\s+for)?\s+(?P<tail>.+)$",
    re.IGNORECASE,
)
_PERCENT_CHANGE_PATTERN = re.compile(r"\bpercent change from (?P<start>.+?) to (?P<end>.+)$", re.IGNORECASE)
_PERCENT_ERROR_PATTERN = re.compile(r"\bpercent error from (?P<expected>.+?) to (?P<observed>.+)$", re.IGNORECASE)
_VOLTAGE_PATTERN = re.compile(r"(?:what(?:'s| is)\s+)?voltage\b(?:\s+(?:at|from|with|for))?\s+(?P<tail>.+)$", re.IGNORECASE)
_RESISTANCE_PATTERN = re.compile(r"(?:what(?:'s| is)\s+)?resistance\b(?:\s+(?:at|from|with|for))?\s+(?P<tail>.+)$", re.IGNORECASE)
_VOLTAGE_DIVIDER_PATTERN = re.compile(
    r"\bvoltage divider(?: output)?\b(?:\s+for)?\s+(?P<tail>.+)$",
    re.IGNORECASE,
)
_AVERAGE_PATTERN = re.compile(r"\baverage(?: of)?\s+(?P<tail>.+)$", re.IGNORECASE)
_SUM_PATTERN = re.compile(r"\bsum(?: of)?\s+(?P<tail>.+)$", re.IGNORECASE)
_MIN_PATTERN = re.compile(r"\bmin(?:imum)?(?: of)?\s+(?P<tail>.+)$", re.IGNORECASE)
_MAX_PATTERN = re.compile(r"\bmax(?:imum)?(?: of)?\s+(?P<tail>.+)$", re.IGNORECASE)
_LIST_SPLIT_PATTERN = re.compile(r"\s*(?:,|and)\s*", re.IGNORECASE)
_SCALAR_VALUE_PATTERN = re.compile(r"^-?(?:\d+(?:\.\d+)?|\.\d+)(?:e[+\-]?\d+)?$", re.IGNORECASE)

_PI = Decimal("3.141592653589793238462643383279502884")


@dataclass(slots=True)
class ParsedQuantity:
    raw_text: str
    normalized_expression: str
    value: Decimal
    unit_label: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_expression": self.normalized_expression,
            "value": str(self.value),
            "unit_label": self.unit_label,
        }


@dataclass(slots=True)
class CalculationHelperMatch:
    candidate: bool = False
    helper_name: str | None = None
    helper_status: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    missing_arguments: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    route_confidence: float = 0.0
    failure_type: CalculationFailureType | None = None
    user_message: str | None = None
    internal_reason: str | None = None
    suggested_recovery: str | None = None


@dataclass(slots=True)
class CalculationHelperExecution:
    helper_name: str
    numeric_value: Decimal
    formatted_value: str
    assistant_response: str
    display_mode: str
    normalized_expression: str
    approximate: bool = False
    engineering_applied: bool = False
    formula_symbolic: str | None = None
    substitution_rows: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _HelperSpec:
    name: str
    evaluator: Callable[[dict[str, Any]], Decimal]
    presenter: Callable[[Decimal], CalculationHelperExecution]
    expression_builder: Callable[[dict[str, Any]], str]


class CalculationHelperRegistry:
    def __init__(self) -> None:
        self._helper_specs: dict[str, _HelperSpec] = {
            "voltage_from_current_resistance": _HelperSpec(
                name="voltage_from_current_resistance",
                evaluator=lambda arguments: _decimal(arguments["current"]) * _decimal(arguments["resistance"]),
                presenter=lambda value: _present_named_result("Voltage", value, suffix=" V"),
                expression_builder=lambda arguments: f"{_scalar_expr(arguments['current'])}*{_scalar_expr(arguments['resistance'])}",
            ),
            "current_from_voltage_resistance": _HelperSpec(
                name="current_from_voltage_resistance",
                evaluator=lambda arguments: _decimal(arguments["voltage"]) / _decimal(arguments["resistance"]),
                presenter=lambda value: _present_named_result("Current", value, suffix=" A"),
                expression_builder=lambda arguments: f"{_scalar_expr(arguments['voltage'])}/{_scalar_expr(arguments['resistance'])}",
            ),
            "resistance_from_voltage_current": _HelperSpec(
                name="resistance_from_voltage_current",
                evaluator=lambda arguments: _decimal(arguments["voltage"]) / _decimal(arguments["current"]),
                presenter=lambda value: _present_named_result("Resistance", value, suffix=" ohms"),
                expression_builder=lambda arguments: f"{_scalar_expr(arguments['voltage'])}/{_scalar_expr(arguments['current'])}",
            ),
            "power_from_voltage_current": _HelperSpec(
                name="power_from_voltage_current",
                evaluator=lambda arguments: _decimal(arguments["voltage"]) * _decimal(arguments["current"]),
                presenter=lambda value: _present_named_result("Power", value, suffix=" W"),
                expression_builder=lambda arguments: f"{_scalar_expr(arguments['voltage'])}*{_scalar_expr(arguments['current'])}",
            ),
            "power_from_current_resistance": _HelperSpec(
                name="power_from_current_resistance",
                evaluator=lambda arguments: (_decimal(arguments["current"]) ** 2) * _decimal(arguments["resistance"]),
                presenter=lambda value: _present_named_result("Power", value, suffix=" W"),
                expression_builder=lambda arguments: f"({_scalar_expr(arguments['current'])}^2)*{_scalar_expr(arguments['resistance'])}",
            ),
            "power_from_voltage_resistance": _HelperSpec(
                name="power_from_voltage_resistance",
                evaluator=lambda arguments: (_decimal(arguments["voltage"]) ** 2) / _decimal(arguments["resistance"]),
                presenter=lambda value: _present_named_result("Power", value, suffix=" W"),
                expression_builder=lambda arguments: f"({_scalar_expr(arguments['voltage'])}^2)/{_scalar_expr(arguments['resistance'])}",
            ),
            "series_resistance": _HelperSpec(
                name="series_resistance",
                evaluator=lambda arguments: sum((_decimal(item) for item in _list_argument(arguments, "values")), start=Decimal("0")),
                presenter=lambda value: _present_named_result("Series resistance", value, suffix=" ohms"),
                expression_builder=lambda arguments: "+".join(_scalar_expr(item) for item in _list_argument(arguments, "values")),
            ),
            "parallel_resistance": _HelperSpec(
                name="parallel_resistance",
                evaluator=_parallel_resistance,
                presenter=lambda value: _present_named_result("Parallel resistance", value, suffix=" ohms"),
                expression_builder=lambda arguments: "0"
                if any(_decimal(item) == 0 for item in _list_argument(arguments, "values"))
                else f"1/({'+'.join(f'1/{_scalar_expr(item)}' for item in _list_argument(arguments, 'values'))})",
            ),
            "voltage_divider": _HelperSpec(
                name="voltage_divider",
                evaluator=lambda arguments: _decimal(arguments["source_voltage"])
                * _decimal(arguments["bottom_resistance"])
                / (_decimal(arguments["top_resistance"]) + _decimal(arguments["bottom_resistance"])),
                presenter=lambda value: _present_named_result("Voltage divider output", value, suffix=" V"),
                expression_builder=lambda arguments: f"{_scalar_expr(arguments['source_voltage'])}*({_scalar_expr(arguments['bottom_resistance'])}/({_scalar_expr(arguments['top_resistance'])}+{_scalar_expr(arguments['bottom_resistance'])}))",
            ),
            "rc_cutoff": _HelperSpec(
                name="rc_cutoff",
                evaluator=lambda arguments: Decimal("1")
                / (Decimal("2") * _PI * _decimal(arguments["resistance"]) * _decimal(arguments["capacitance"])),
                presenter=_present_rc_cutoff,
                expression_builder=lambda arguments: f"1/(2*pi*{_scalar_expr(arguments['resistance'])}*{_scalar_expr(arguments['capacitance'])})",
            ),
            "percent_change": _HelperSpec(
                name="percent_change",
                evaluator=lambda arguments: ((_decimal(arguments["new"]) - _decimal(arguments["old"])) / _decimal(arguments["old"]))
                * Decimal("100"),
                presenter=lambda value: _present_named_result("Percent change", value, suffix="%"),
                expression_builder=lambda arguments: f"(({_scalar_expr(arguments['new'])}-{_scalar_expr(arguments['old'])})/{_scalar_expr(arguments['old'])})*100",
            ),
            "percent_error": _HelperSpec(
                name="percent_error",
                evaluator=lambda arguments: (abs(_decimal(arguments["actual"]) - _decimal(arguments["expected"])) / _decimal(arguments["expected"]))
                * Decimal("100"),
                presenter=lambda value: _present_named_result("Percent error", value, suffix="%"),
                expression_builder=lambda arguments: f"abs(({_scalar_expr(arguments['actual'])}-{_scalar_expr(arguments['expected'])})/{_scalar_expr(arguments['expected'])})*100",
            ),
            "sum_list": _HelperSpec(
                name="sum_list",
                evaluator=lambda arguments: sum((_decimal(item) for item in _list_argument(arguments, "values")), start=Decimal("0")),
                presenter=lambda value: _present_named_result("Sum", value),
                expression_builder=lambda arguments: "+".join(_scalar_expr(item) for item in _list_argument(arguments, "values")),
            ),
            "average_list": _HelperSpec(
                name="average_list",
                evaluator=lambda arguments: sum((_decimal(item) for item in _list_argument(arguments, "values")), start=Decimal("0"))
                / Decimal(str(len(_list_argument(arguments, "values")))),
                presenter=lambda value: _present_named_result("Average", value),
                expression_builder=lambda arguments: f"({'+'.join(_scalar_expr(item) for item in _list_argument(arguments, 'values'))})/{len(_list_argument(arguments, 'values'))}",
            ),
            "min_list": _HelperSpec(
                name="min_list",
                evaluator=lambda arguments: min(_decimal(item) for item in _list_argument(arguments, "values")),
                presenter=lambda value: _present_named_result("Minimum", value),
                expression_builder=lambda arguments: f"min({','.join(_scalar_expr(item) for item in _list_argument(arguments, 'values'))})",
            ),
            "max_list": _HelperSpec(
                name="max_list",
                evaluator=lambda arguments: max(_decimal(item) for item in _list_argument(arguments, "values")),
                presenter=lambda value: _present_named_result("Maximum", value),
                expression_builder=lambda arguments: f"max({','.join(_scalar_expr(item) for item in _list_argument(arguments, 'values'))})",
            ),
        }

    def helper_names(self) -> list[str]:
        return list(self._helper_specs)

    def match_request(self, *, raw_text: str, normalized_text: str) -> CalculationHelperMatch:
        raw = _strip_terminal_punctuation(raw_text)
        normalized = _strip_terminal_punctuation(normalized_text)
        if not raw or not normalized:
            return CalculationHelperMatch()
        if not re.search(r"\d", raw):
            return CalculationHelperMatch()

        if match := _match_power_request(raw, normalized):
            return match
        if match := _match_current_request(raw, normalized):
            return match
        if match := _match_voltage_divider_request(raw, normalized):
            return match
        if match := _match_voltage_request(raw, normalized):
            return match
        if match := _match_resistance_request(raw, normalized):
            return match
        if match := _match_ohms_law_request(raw, normalized):
            return match
        if match := _match_parallel_resistance_request(raw, normalized):
            return match
        if match := _match_series_resistance_request(raw, normalized):
            return match
        if match := _match_rc_cutoff_request(raw, normalized):
            return match
        if match := _match_percent_change_request(raw, normalized):
            return match
        if match := _match_percent_error_request(raw, normalized):
            return match
        if match := _match_sum_request(raw, normalized):
            return match
        if match := _match_average_request(raw, normalized):
            return match
        if match := _match_min_request(raw, normalized):
            return match
        if match := _match_max_request(raw, normalized):
            return match
        return CalculationHelperMatch()

    def execute(self, helper_name: str, arguments: dict[str, Any]) -> CalculationHelperExecution:
        helper = self._helper_specs[helper_name]
        coerced_arguments = _coerce_arguments(arguments)
        numeric_value = helper.evaluator(coerced_arguments)
        presented = helper.presenter(numeric_value)
        formula_symbolic, substitution_rows = _helper_formula_payload(helper_name, arguments)
        return CalculationHelperExecution(
            helper_name=presented.helper_name,
            numeric_value=presented.numeric_value,
            formatted_value=presented.formatted_value,
            assistant_response=presented.assistant_response,
            display_mode=presented.display_mode,
            normalized_expression=helper.expression_builder(arguments),
            approximate=presented.approximate,
            engineering_applied=presented.engineering_applied,
            formula_symbolic=formula_symbolic,
            substitution_rows=substitution_rows,
        )


def build_helper_registry() -> CalculationHelperRegistry:
    return CalculationHelperRegistry()


@lru_cache(maxsize=1)
def get_cached_helper_registry() -> CalculationHelperRegistry:
    return build_helper_registry()


def helper_registry_cache_info():
    return get_cached_helper_registry.cache_info()


def helper_registry_cache_clear() -> None:
    get_cached_helper_registry.cache_clear()


def _match_power_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    match = _POWER_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        quantities = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("power_family", error, "power helper matched but an input could not be normalized")
    quantity_map = _map_quantities_by_measurement(quantities)
    voltage = quantity_map.get("voltage")
    current = quantity_map.get("current")
    resistance = quantity_map.get("resistance")
    if voltage and current:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="power_from_voltage_current",
            helper_status="matched",
            arguments={"voltage": voltage, "current": current},
            reasons=["power helper matched from voltage and current"],
            route_confidence=0.96,
        )
    if current and resistance:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="power_from_current_resistance",
            helper_status="matched",
            arguments={"current": current, "resistance": resistance},
            reasons=["power helper matched from current and resistance"],
            route_confidence=0.94,
        )
    if voltage and resistance:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="power_from_voltage_resistance",
            helper_status="matched",
            arguments={"voltage": voltage, "resistance": resistance},
            reasons=["power helper matched from voltage and resistance"],
            route_confidence=0.94,
        )
    if voltage:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="power_family",
            helper_status="under_specified",
            arguments={"known": voltage},
            missing_arguments=["current or resistance"],
            reasons=["power helper needs a second quantity"],
            route_confidence=0.88,
            failure_type=CalculationFailureType.HELPER_UNDER_SPECIFIED,
            user_message="Stormhelm can calculate power locally if you provide voltage with current or resistance.",
            internal_reason="power_helper_missing_second_value",
            suggested_recovery="Send a request like power at 12V and 1.5A or power at 12V and 8 ohms.",
        )
    if current:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="power_family",
            helper_status="under_specified",
            arguments={"known": current},
            missing_arguments=["voltage or resistance"],
            reasons=["power helper needs a second quantity"],
            route_confidence=0.84,
            failure_type=CalculationFailureType.HELPER_UNDER_SPECIFIED,
            user_message="Stormhelm can calculate power locally if you provide current with voltage or resistance.",
            internal_reason="power_helper_missing_second_value",
            suggested_recovery="Send a request like power at 1.5A and 8 ohms.",
        )
    if resistance:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="power_family",
            helper_status="under_specified",
            arguments={"known": resistance},
            missing_arguments=["voltage or current"],
            reasons=["power helper needs a second quantity"],
            route_confidence=0.84,
            failure_type=CalculationFailureType.HELPER_UNDER_SPECIFIED,
            user_message="Stormhelm can calculate power locally if you provide resistance with voltage or current.",
            internal_reason="power_helper_missing_second_value",
            suggested_recovery="Send a request like power at 12V and 8 ohms.",
        )
    return None


def _match_current_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _CURRENT_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        quantities = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("current_from_voltage_resistance", error, "current helper matched but an input could not be normalized")
    quantity_map = _map_quantities_by_measurement(quantities)
    voltage = quantity_map.get("voltage")
    resistance = quantity_map.get("resistance")
    if voltage and resistance:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="current_from_voltage_resistance",
            helper_status="matched",
            arguments={"voltage": voltage, "resistance": resistance},
            reasons=["ohm's law current helper matched"],
            route_confidence=0.95,
        )
    return None


def _match_ohms_law_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _OHMS_LAW_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        quantities = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("ohms_law_family", error, "ohm's law helper matched but an input could not be normalized")
    measurement_names = sorted(_map_quantities_by_measurement(quantities))
    if len(measurement_names) >= 2:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="ohms_law_family",
            helper_status="ambiguous",
            arguments={"quantities": quantities},
            reasons=["ohm's law request does not specify the target quantity"],
            route_confidence=0.82,
            failure_type=CalculationFailureType.HELPER_AMBIGUOUS,
            user_message="Stormhelm can apply Ohm's law here, but tell me whether you want voltage, current, or resistance.",
            internal_reason="ohms_law_target_not_specified",
            suggested_recovery="Ask for current, voltage, or resistance explicitly.",
        )
    return None


def _match_parallel_resistance_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _PARALLEL_RESISTANCE_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        values = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("parallel_resistance", error, "parallel resistance helper matched but an input could not be normalized")
    if len(values) >= 2:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="parallel_resistance",
            helper_status="matched",
            arguments={"values": values},
            reasons=["parallel resistance helper matched"],
            route_confidence=0.95,
        )
    return CalculationHelperMatch(
        candidate=True,
        helper_name="parallel_resistance",
        helper_status="under_specified",
        missing_arguments=["at least two resistance values"],
        reasons=["parallel resistance helper needs multiple values"],
        route_confidence=0.8,
        failure_type=CalculationFailureType.HELPER_UNDER_SPECIFIED,
        user_message="Stormhelm needs at least two resistance values for that helper.",
        internal_reason="parallel_resistance_requires_two_values",
        suggested_recovery="Send a request like parallel resistance of 220 and 330.",
    )


def _match_series_resistance_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _SERIES_RESISTANCE_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        values = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("series_resistance", error, "series resistance helper matched but an input could not be normalized")
    if len(values) >= 2:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="series_resistance",
            helper_status="matched",
            arguments={"values": values},
            reasons=["series resistance helper matched"],
            route_confidence=0.95,
        )
    return CalculationHelperMatch(
        candidate=True,
        helper_name="series_resistance",
        helper_status="under_specified",
        missing_arguments=["at least two resistance values"],
        reasons=["series resistance helper needs multiple values"],
        route_confidence=0.8,
        failure_type=CalculationFailureType.HELPER_UNDER_SPECIFIED,
        user_message="Stormhelm needs at least two resistance values for that helper.",
        internal_reason="series_resistance_requires_two_values",
        suggested_recovery="Send a request like series resistance of 100, 220, 470.",
    )


def _match_voltage_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _VOLTAGE_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        quantities = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("voltage_from_current_resistance", error, "voltage helper matched but an input could not be normalized")
    quantity_map = _map_quantities_by_measurement(quantities)
    current = quantity_map.get("current")
    resistance = quantity_map.get("resistance")
    if current and resistance:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="voltage_from_current_resistance",
            helper_status="matched",
            arguments={"current": current, "resistance": resistance},
            reasons=["ohm's law voltage helper matched"],
            route_confidence=0.95,
        )
    return None


def _match_resistance_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _RESISTANCE_PATTERN.search(raw_text)
    if not match:
        return None
    if _PARALLEL_RESISTANCE_PATTERN.search(raw_text) or _SERIES_RESISTANCE_PATTERN.search(raw_text):
        return None
    try:
        quantities = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("resistance_from_voltage_current", error, "resistance helper matched but an input could not be normalized")
    quantity_map = _map_quantities_by_measurement(quantities)
    voltage = quantity_map.get("voltage")
    current = quantity_map.get("current")
    if voltage and current:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="resistance_from_voltage_current",
            helper_status="matched",
            arguments={"voltage": voltage, "current": current},
            reasons=["ohm's law resistance helper matched"],
            route_confidence=0.95,
        )
    return None


def _match_voltage_divider_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _VOLTAGE_DIVIDER_PATTERN.search(raw_text)
    if not match:
        return None
    tail = _strip_terminal_punctuation(match.group("tail"))
    if " with " not in tail.lower():
        return CalculationHelperMatch(
            candidate=True,
            helper_name="voltage_divider",
            helper_status="under_specified",
            missing_arguments=["source voltage, top resistance, and bottom resistance"],
            reasons=["voltage divider helper needs a source voltage and two resistances"],
            route_confidence=0.8,
            failure_type=CalculationFailureType.HELPER_UNDER_SPECIFIED,
            user_message="Stormhelm needs the source voltage plus the top and bottom resistances for a voltage divider.",
            internal_reason="voltage_divider_missing_inputs",
            suggested_recovery="Send a request like voltage divider for 12V with 220 and 330.",
        )
    head, tail_values = re.split(r"\bwith\b", tail, maxsplit=1, flags=re.IGNORECASE)
    try:
        source_voltage = _parse_scalar(head)
        resistance_values = _parse_quantity_parts(tail_values)
    except CalculationNormalizationError as error:
        return _invalid_helper_match("voltage_divider", error, "voltage divider helper matched but an input could not be normalized")
    if len(resistance_values) < 2:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="voltage_divider",
            helper_status="under_specified",
            arguments={"source_voltage": source_voltage},
            missing_arguments=["top resistance and bottom resistance"],
            reasons=["voltage divider helper needs two resistance values"],
            route_confidence=0.82,
            failure_type=CalculationFailureType.HELPER_UNDER_SPECIFIED,
            user_message="Stormhelm needs both the top and bottom resistance values for that voltage divider.",
            internal_reason="voltage_divider_missing_resistances",
            suggested_recovery="Send a request like voltage divider for 12V with 220 and 330.",
        )
    return CalculationHelperMatch(
        candidate=True,
        helper_name="voltage_divider",
        helper_status="matched",
        arguments={
            "source_voltage": source_voltage,
            "top_resistance": resistance_values[0],
            "bottom_resistance": resistance_values[1],
        },
        reasons=["voltage divider helper matched"],
        route_confidence=0.93,
    )


def _match_rc_cutoff_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _RC_CUTOFF_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        quantities = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("rc_cutoff", error, "rc cutoff helper matched but an input could not be normalized")
    capacitance = next((quantity for quantity in quantities if (quantity.unit_label or "").lower() == "f"), None)
    resistance = next((quantity for quantity in quantities if quantity is not capacitance), None)
    if capacitance and resistance:
        return CalculationHelperMatch(
            candidate=True,
            helper_name="rc_cutoff",
            helper_status="matched",
            arguments={"resistance": resistance, "capacitance": capacitance},
            reasons=["rc cutoff helper matched"],
            route_confidence=0.93,
        )
    return CalculationHelperMatch(
        candidate=True,
        helper_name="rc_cutoff",
        helper_status="under_specified",
        missing_arguments=["resistance and capacitance"],
        reasons=["rc cutoff helper needs both resistance and capacitance"],
        route_confidence=0.8,
        failure_type=CalculationFailureType.HELPER_UNDER_SPECIFIED,
        user_message="Stormhelm needs both resistance and capacitance for that RC cutoff.",
        internal_reason="rc_cutoff_missing_inputs",
        suggested_recovery="Send a request like RC cutoff for 10k and 0.1uF.",
    )


def _match_percent_change_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _PERCENT_CHANGE_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        start = _parse_scalar(match.group("start"))
        end = _parse_scalar(match.group("end"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("percent_change", error, "percent change helper matched but an input could not be normalized")
    return CalculationHelperMatch(
        candidate=True,
        helper_name="percent_change",
        helper_status="matched",
        arguments={"old": start, "new": end},
        reasons=["percent change helper matched"],
        route_confidence=0.95,
    )


def _match_percent_error_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _PERCENT_ERROR_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        expected = _parse_scalar(match.group("expected"))
        observed = _parse_scalar(match.group("observed"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("percent_error", error, "percent error helper matched but an input could not be normalized")
    return CalculationHelperMatch(
        candidate=True,
        helper_name="percent_error",
        helper_status="matched",
        arguments={"expected": expected, "actual": observed},
        reasons=["percent error helper matched"],
        route_confidence=0.94,
    )


def _match_sum_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _SUM_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        values = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("sum_list", error, "sum helper matched but an input could not be normalized")
    if not values:
        return None
    return CalculationHelperMatch(
        candidate=True,
        helper_name="sum_list",
        helper_status="matched",
        arguments={"values": values},
        reasons=["sum helper matched"],
        route_confidence=0.92,
    )


def _match_average_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _AVERAGE_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        values = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("average_list", error, "average helper matched but an input could not be normalized")
    if not values:
        return None
    return CalculationHelperMatch(
        candidate=True,
        helper_name="average_list",
        helper_status="matched",
        arguments={"values": values},
        reasons=["average helper matched"],
        route_confidence=0.92,
    )


def _match_min_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _MIN_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        values = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("min_list", error, "minimum helper matched but an input could not be normalized")
    if not values:
        return None
    return CalculationHelperMatch(
        candidate=True,
        helper_name="min_list",
        helper_status="matched",
        arguments={"values": values},
        reasons=["minimum helper matched"],
        route_confidence=0.92,
    )


def _match_max_request(raw_text: str, normalized_text: str) -> CalculationHelperMatch | None:
    del normalized_text
    match = _MAX_PATTERN.search(raw_text)
    if not match:
        return None
    try:
        values = _parse_quantity_parts(match.group("tail"))
    except CalculationNormalizationError as error:
        return _invalid_helper_match("max_list", error, "maximum helper matched but an input could not be normalized")
    if not values:
        return None
    return CalculationHelperMatch(
        candidate=True,
        helper_name="max_list",
        helper_status="matched",
        arguments={"values": values},
        reasons=["maximum helper matched"],
        route_confidence=0.92,
    )


def _parse_quantity_parts(tail: str) -> list[ParsedQuantity]:
    parts = [part for part in _LIST_SPLIT_PATTERN.split(_strip_terminal_punctuation(tail)) if part]
    return [_parse_scalar(part) for part in parts]


def _parse_value_list(tail: str) -> list[Decimal]:
    return [quantity.value for quantity in _parse_quantity_parts(tail)]


def _parse_scalar(raw_value: str) -> ParsedQuantity:
    cleaned = _strip_terminal_punctuation(raw_value)
    try:
        normalized = normalize_expression_text(cleaned)
        if not normalized.parseable_boolean or not _SCALAR_VALUE_PATTERN.fullmatch(normalized.normalized_expression):
            raise CalculationNormalizationError(
                "Helper inputs must be single numeric values.",
                failure_type=CalculationFailureType.OUT_OF_SCOPE,
                user_message="Stormhelm can handle this helper locally, but each helper input needs to be a single numeric value in Calc-2.",
                recovery_hint="Send helper inputs like 12V, 220 ohms, or 0.1uF rather than nested formulas.",
            )
        syntax_tree = parse_expression(normalized.normalized_expression)
        value = evaluate_expression(syntax_tree)
    except (CalculationNormalizationError, CalculationParseError, CalculationEvaluationError) as error:
        if isinstance(error, CalculationNormalizationError):
            raise error
        raise CalculationNormalizationError(
            f"Stormhelm could not parse helper quantity '{cleaned}'.",
            failure_type=CalculationFailureType.NORMALIZATION_ERROR,
            user_message="Stormhelm could not normalize one of those helper inputs cleanly.",
            recovery_hint="Use plain numeric values such as 12V, 220 ohms, 0.1uF, or 37.5.",
        ) from error
    unit_label = next(
        (detail.unit_label for detail in normalized.normalization_details if detail.unit_label is not None),
        None,
    )
    return ParsedQuantity(
        raw_text=cleaned,
        normalized_expression=normalized.normalized_expression,
        value=value,
        unit_label=unit_label,
    )


def _map_quantities_by_measurement(quantities: list[ParsedQuantity]) -> dict[str, ParsedQuantity]:
    mapped: dict[str, ParsedQuantity] = {}
    for quantity in quantities:
        measurement = _measurement_name(quantity.unit_label)
        if measurement is None or measurement in mapped:
            continue
        mapped[measurement] = quantity
    return mapped


def _measurement_name(unit_label: str | None) -> str | None:
    if unit_label is None:
        return None
    lowered = unit_label.lower()
    if lowered == "v":
        return "voltage"
    if lowered == "a":
        return "current"
    if lowered in {"ohm", "ohms", "\u03a9"}:
        return "resistance"
    if lowered == "f":
        return "capacitance"
    return None


def _parallel_resistance(arguments: dict[str, Any]) -> Decimal:
    if any(_decimal(item) == 0 for item in _list_argument(arguments, "values")):
        return Decimal("0")
    reciprocals = [Decimal("1") / _decimal(item) for item in _list_argument(arguments, "values")]
    return Decimal("1") / sum(reciprocals, start=Decimal("0"))


def _present_named_result(name: str, value: Decimal, *, suffix: str = "") -> CalculationHelperExecution:
    formatted = format_calculation_value(value)
    rendered_value = f"{formatted.text}{suffix}"
    relation = "\u2248" if formatted.approximate else "="
    return CalculationHelperExecution(
        helper_name=name,
        numeric_value=value,
        formatted_value=rendered_value,
        assistant_response=f"{name} {relation} {rendered_value}",
        display_mode=formatted.mode,
        normalized_expression="",
        approximate=formatted.approximate,
        engineering_applied=formatted.engineering_applied,
    )


def _present_rc_cutoff(value: Decimal) -> CalculationHelperExecution:
    rounded = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    formatted_value = f"{format_decimal(rounded)} Hz"
    return CalculationHelperExecution(
        helper_name="RC cutoff",
        numeric_value=value,
        formatted_value=formatted_value,
        assistant_response=f"RC cutoff \u2248 {formatted_value}",
        display_mode="decimal",
        normalized_expression="",
        approximate=True,
        engineering_applied=False,
    )


def _decimal(value: Any) -> Decimal:
    if isinstance(value, ParsedQuantity):
        return value.value
    if isinstance(value, dict):
        if "value" in value:
            return Decimal(str(value["value"]))
        if "numeric_value" in value:
            return Decimal(str(value["numeric_value"]))
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError(f"Stormhelm could not coerce '{value}' into a Decimal.") from error


def _list_argument(arguments: dict[str, Any], key: str) -> list[Any]:
    value = arguments.get(key)
    if isinstance(value, list):
        return value
    return [value] if value is not None else []


def _coerce_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, list):
            coerced[key] = [_decimal(item) for item in value]
            continue
        try:
            coerced[key] = _decimal(value)
        except ValueError:
            coerced[key] = value
    return coerced


def _scalar_expr(value: Any) -> str:
    if isinstance(value, ParsedQuantity):
        return value.normalized_expression
    if isinstance(value, dict):
        if value.get("normalized_expression"):
            return str(value["normalized_expression"])
        if value.get("normalized_value"):
            return str(value["normalized_value"])
        if value.get("value") is not None:
            return str(value["value"])
    return format_decimal(_decimal(value))


def _helper_formula_payload(helper_name: str, arguments: dict[str, Any]) -> tuple[str | None, list[str]]:
    if helper_name == "voltage_from_current_resistance":
        return "V = I * R", [f"V = {_scalar_expr(arguments['current'])} * {_scalar_expr(arguments['resistance'])}"]
    if helper_name == "current_from_voltage_resistance":
        return "I = V / R", [f"I = {_scalar_expr(arguments['voltage'])} / {_scalar_expr(arguments['resistance'])}"]
    if helper_name == "resistance_from_voltage_current":
        return "R = V / I", [f"R = {_scalar_expr(arguments['voltage'])} / {_scalar_expr(arguments['current'])}"]
    if helper_name == "power_from_voltage_current":
        return "P = V * I", [f"P = {_scalar_expr(arguments['voltage'])} * {_scalar_expr(arguments['current'])}"]
    if helper_name == "power_from_current_resistance":
        return "P = I^2 * R", [f"P = {_scalar_expr(arguments['current'])}^2 * {_scalar_expr(arguments['resistance'])}"]
    if helper_name == "power_from_voltage_resistance":
        return "P = V^2 / R", [f"P = {_scalar_expr(arguments['voltage'])}^2 / {_scalar_expr(arguments['resistance'])}"]
    if helper_name == "series_resistance":
        joined = " + ".join(_scalar_expr(item) for item in _list_argument(arguments, "values"))
        return "R_total = R1 + R2 + ...", [f"R_total = {joined}"]
    if helper_name == "parallel_resistance":
        parts = [f"1 / {_scalar_expr(item)}" for item in _list_argument(arguments, "values")]
        return "R_total = 1 / (1 / R1 + 1 / R2 + ...)", [f"R_total = 1 / ({' + '.join(parts)})"]
    if helper_name == "voltage_divider":
        return (
            "V_out = V_in * (R_bottom / (R_top + R_bottom))",
            [
                "V_out = "
                f"{_scalar_expr(arguments['source_voltage'])} * "
                f"({_scalar_expr(arguments['bottom_resistance'])} / "
                f"({_scalar_expr(arguments['top_resistance'])} + {_scalar_expr(arguments['bottom_resistance'])}))"
            ],
        )
    if helper_name == "rc_cutoff":
        return (
            "f_c = 1 / (2 * pi * R * C)",
            [
                "f_c = 1 / (2 * pi * "
                f"{_scalar_expr(arguments['resistance'])} * {_scalar_expr(arguments['capacitance'])})"
            ],
        )
    if helper_name == "percent_change":
        return (
            "percent_change = ((new - old) / old) * 100",
            [
                "percent_change = "
                f"(({_scalar_expr(arguments['new'])} - {_scalar_expr(arguments['old'])}) / {_scalar_expr(arguments['old'])}) * 100"
            ],
        )
    if helper_name == "percent_error":
        return (
            "percent_error = abs((actual - expected) / expected) * 100",
            [
                "percent_error = "
                f"abs(({_scalar_expr(arguments['actual'])} - {_scalar_expr(arguments['expected'])}) / {_scalar_expr(arguments['expected'])}) * 100"
            ],
        )
    if helper_name == "sum_list":
        joined = " + ".join(_scalar_expr(item) for item in _list_argument(arguments, "values"))
        return "sum = x1 + x2 + ...", [f"sum = {joined}"]
    if helper_name == "average_list":
        joined = " + ".join(_scalar_expr(item) for item in _list_argument(arguments, "values"))
        count = len(_list_argument(arguments, "values"))
        return "average = (x1 + x2 + ...) / n", [f"average = ({joined}) / {count}"]
    if helper_name == "min_list":
        joined = ", ".join(_scalar_expr(item) for item in _list_argument(arguments, "values"))
        return "minimum = min(values)", [f"minimum = min({joined})"]
    if helper_name == "max_list":
        joined = ", ".join(_scalar_expr(item) for item in _list_argument(arguments, "values"))
        return "maximum = max(values)", [f"maximum = max({joined})"]
    return None, []


def _invalid_helper_match(helper_name: str, error: CalculationNormalizationError, reason: str) -> CalculationHelperMatch:
    return CalculationHelperMatch(
        candidate=True,
        helper_name=helper_name,
        helper_status="invalid",
        reasons=[reason],
        route_confidence=0.86,
        failure_type=error.failure_type,
        user_message=error.user_message,
        internal_reason=str(error),
        suggested_recovery=error.recovery_hint,
    )


def _strip_terminal_punctuation(text: str) -> str:
    return str(text or "").strip().rstrip("?.!").strip()
