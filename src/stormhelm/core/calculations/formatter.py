from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from decimal import ROUND_HALF_UP

from stormhelm.core.calculations.models import CalculationOutputMode


ENGINEERING_SUFFIXES = {
    -12: "p",
    -9: "n",
    -6: "u",
    -3: "m",
    0: "",
    3: "k",
    6: "M",
    9: "G",
}
PLAIN_DISPLAY_MAX_SIGNIFICANT_DIGITS = 12
ENGINEERING_DISPLAY_MAX_SIGNIFICANT_DIGITS = 6


@dataclass(slots=True)
class FormattedCalculationValue:
    text: str
    mode: str
    approximate: bool = False
    engineering_applied: bool = False


def format_decimal(value: Decimal) -> str:
    return _trim_decimal_text(value)


def format_calculation_value(
    value: Decimal,
    *,
    prefer_engineering: bool = False,
) -> FormattedCalculationValue:
    if value == 0:
        return FormattedCalculationValue(text="0", mode="decimal")

    absolute_value = abs(value)
    use_engineering = (
        prefer_engineering and (absolute_value < Decimal("0.001") or absolute_value >= Decimal("1000"))
    ) or absolute_value < Decimal("0.0001") or absolute_value >= Decimal("1000000")
    if use_engineering:
        formatted = _format_engineering(value)
        if formatted is not None:
            return formatted

    rounded, approximate = _round_for_display(value, PLAIN_DISPLAY_MAX_SIGNIFICANT_DIGITS)
    text = _trim_decimal_text(rounded)
    if _should_use_scientific_text(text):
        text = _format_scientific(rounded)
        return FormattedCalculationValue(text=text, mode="scientific", approximate=approximate)
    return FormattedCalculationValue(text=text, mode="decimal", approximate=approximate)


def format_expression_for_display(expression: str) -> str:
    pieces: list[str] = []
    previous_kind = "start"
    for character in expression:
        if character in {"+", "*", "/", "^"}:
            pieces.append(f" {character} ")
            previous_kind = "operator"
            continue
        if character == "-":
            if previous_kind in {"start", "operator", "lparen"}:
                pieces.append("-")
            else:
                pieces.append(" - ")
            previous_kind = "operator"
            continue
        if character == "(":
            pieces.append("(")
            previous_kind = "lparen"
            continue
        if character == ")":
            pieces.append(")")
            previous_kind = "rparen"
            continue
        pieces.append(character)
        previous_kind = "value"
    return " ".join("".join(pieces).split())


def compose_success_response(
    *,
    normalized_expression: str,
    formatted_value: str,
    output_mode: CalculationOutputMode,
    approximate: bool = False,
) -> str:
    if output_mode == CalculationOutputMode.SHORT_EXPRESSION:
        relation = "\u2248" if approximate else "="
        return f"{format_expression_for_display(normalized_expression)} {relation} {formatted_value}"
    return f"\u2248 {formatted_value}" if approximate else formatted_value


def _format_engineering(value: Decimal) -> FormattedCalculationValue | None:
    adjusted = value.adjusted()
    exponent = (adjusted // 3) * 3
    if exponent not in ENGINEERING_SUFFIXES:
        return None
    scaled = value / (Decimal(10) ** exponent)
    rounded, approximate = _round_for_display(scaled, ENGINEERING_DISPLAY_MAX_SIGNIFICANT_DIGITS)
    text = f"{_trim_decimal_text(rounded)}{ENGINEERING_SUFFIXES[exponent]}"
    return FormattedCalculationValue(
        text=text,
        mode="engineering",
        approximate=approximate,
        engineering_applied=True,
    )


def _round_for_display(value: Decimal, max_significant_digits: int) -> tuple[Decimal, bool]:
    if value == 0:
        return value, False
    exponent = value.adjusted() - max_significant_digits + 1
    quantizer = Decimal(f"1e{exponent}")
    rounded = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    return rounded, rounded != value


def _trim_decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    if value == value.to_integral_value():
        return format(value.quantize(Decimal("1")), "f")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _should_use_scientific_text(text: str) -> bool:
    return len(text.replace("-", "").replace(".", "")) > 12 or (text.startswith("0.0000") and text != "0")


def _format_scientific(value: Decimal) -> str:
    mantissa, exponent = f"{value:.12E}".split("E")
    mantissa = mantissa.rstrip("0").rstrip(".")
    exponent_value = int(exponent)
    return f"{mantissa}e{exponent_value}"
