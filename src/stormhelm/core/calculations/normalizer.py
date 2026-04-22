from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re

from stormhelm.core.calculations.models import CalculationFailureType
from stormhelm.core.calculations.models import CalculationNormalizationDetail
from stormhelm.core.calculations.models import CalculationOutputMode
from stormhelm.core.calculations.models import NormalizedCalculation


DIRECT_EXPRESSION_PATTERN = re.compile(r"^[0-9eE+\-*/^().,\sA-Za-z\u00b5\u03a9\u2212\u2012\u2013\u2014\u00d7\u00f7]+$")
NORMALIZED_EXPRESSION_PATTERN = re.compile(r"^[0-9eE+\-*/^().]+$")
EXPLICIT_REQUEST_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:calculate|compute|evaluate|double[- ]check|recompute|what(?:'s| is))\s+(?P<expr>.+?)\s*[?.!]*\s*$",
    re.IGNORECASE,
)
SOLVE_REQUEST_PATTERN = re.compile(r"^\s*solve\s+(?P<expr>.+?)\s*[?.!]*\s*$", re.IGNORECASE)
STEP_REQUEST_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:show(?: me)?(?: the)? steps?|walk me through|show your work|how did you get)\s+(?:for\s+)?(?P<expr>.+?)\s*[?.!]*\s*$",
    re.IGNORECASE,
)
FORMULA_REQUEST_PATTERN = re.compile(
    r"^\s*(?:please\s+)?show(?: me)?(?: the)? formula(?: substitution)?(?: for)?\s+(?P<expr>.+?)\s*[?.!]*\s*$",
    re.IGNORECASE,
)
BREAKDOWN_REQUEST_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:break down|show(?: me)?(?: the)? breakdown(?: for)?)\s+(?P<expr>.+?)\s*[?.!]*\s*$",
    re.IGNORECASE,
)
CODE_HINT_PATTERN = re.compile(r"\b(?:python|javascript|script|code|program|function)\b", re.IGNORECASE)

ENGINEERING_SUFFIXES = {
    "G": Decimal("1e9"),
    "M": Decimal("1e6"),
    "k": Decimal("1e3"),
    "m": Decimal("1e-3"),
    "u": Decimal("1e-6"),
    "n": Decimal("1e-9"),
    "p": Decimal("1e-12"),
}
ENGINEERING_SUFFIX_CHARS = set(ENGINEERING_SUFFIXES) | {"\u00b5"}
SUPPORTED_UNIT_LABELS = {
    "a": "A",
    "v": "V",
    "w": "W",
    "f": "F",
    "h": "H",
    "hz": "Hz",
    "ohm": "ohm",
    "ohms": "ohms",
    "ω": "\u03a9",
    "s": "s",
}
UNIT_LABEL_CHAR_PATTERN = re.compile(r"[A-Za-z\u03a9]")


@dataclass(slots=True)
class ExpressionCandidate:
    candidate: bool
    explicit_request: bool = False
    extracted_expression: str | None = None
    requested_mode: CalculationOutputMode = CalculationOutputMode.ANSWER_ONLY
    reasons: list[str] = field(default_factory=list)
    route_confidence: float = 0.0


class CalculationNormalizationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        failure_type: CalculationFailureType = CalculationFailureType.NORMALIZATION_ERROR,
        user_message: str | None = None,
        position: int | None = None,
        recovery_hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_type = failure_type
        self.user_message = user_message or "Stormhelm could not normalize that expression cleanly."
        self.position = position
        self.recovery_hint = recovery_hint


def detect_expression_candidate(raw_text: str, normalized_text: str) -> ExpressionCandidate:
    raw = str(raw_text or "").strip()
    normalized = str(normalized_text or "").strip()
    if not raw:
        return ExpressionCandidate(candidate=False)

    if CODE_HINT_PATTERN.search(normalized):
        return ExpressionCandidate(candidate=False, reasons=["code execution request detected"])

    direct_expression = _strip_terminal_punctuation(raw)
    if _looks_like_direct_expression(direct_expression):
        operator_count = _operator_count(direct_expression)
        requested_mode = (
            CalculationOutputMode.SHORT_EXPRESSION if operator_count >= 4 else CalculationOutputMode.ANSWER_ONLY
        )
        return ExpressionCandidate(
            candidate=True,
            extracted_expression=direct_expression,
            requested_mode=requested_mode,
            reasons=["direct numeric expression matched"],
            route_confidence=0.99,
        )

    for pattern, requested_mode, reason in (
        (STEP_REQUEST_PATTERN, CalculationOutputMode.STEP_BY_STEP, "step explanation phrase matched"),
        (FORMULA_REQUEST_PATTERN, CalculationOutputMode.FORMULA_SUBSTITUTION, "formula explanation phrase matched"),
        (BREAKDOWN_REQUEST_PATTERN, CalculationOutputMode.SHORT_BREAKDOWN, "breakdown explanation phrase matched"),
    ):
        match = pattern.match(raw)
        if not match:
            continue
        expression = _strip_terminal_punctuation(match.group("expr"))
        if expression and _looks_like_direct_expression(expression):
            return ExpressionCandidate(
                candidate=True,
                explicit_request=True,
                extracted_expression=expression,
                requested_mode=requested_mode,
                reasons=[reason],
                route_confidence=0.95,
            )

    explicit_match = EXPLICIT_REQUEST_PATTERN.match(raw)
    if explicit_match:
        expression = _strip_terminal_punctuation(explicit_match.group("expr"))
        raw_lower = raw.lower()
        if raw_lower.startswith(("what is", "what's")):
            candidate_allowed = bool(expression) and _starts_like_expression(expression) and (
                _looks_like_direct_expression(expression) or _contains_operator(expression)
            )
        else:
            candidate_allowed = bool(expression) and (
                _looks_like_direct_expression(expression)
                or (_starts_like_expression(expression) and (_contains_numeric_signal(expression) or _contains_alpha(expression)))
                or _contains_operator(expression)
            )
        if candidate_allowed:
            requested_mode = (
                CalculationOutputMode.SHORT_EXPRESSION
                if normalized.startswith("double check") or normalized.startswith("double-check")
                else CalculationOutputMode.ANSWER_ONLY
            )
            return ExpressionCandidate(
                candidate=True,
                explicit_request=True,
                extracted_expression=expression,
                requested_mode=requested_mode,
                reasons=["explicit calculation phrase matched"],
                route_confidence=0.95,
            )

    solve_match = SOLVE_REQUEST_PATTERN.match(raw)
    if solve_match:
        expression = _strip_terminal_punctuation(solve_match.group("expr"))
        if expression and (_contains_numeric_signal(expression) or _contains_alpha(expression)):
            return ExpressionCandidate(
                candidate=True,
                explicit_request=True,
                extracted_expression=expression,
                requested_mode=CalculationOutputMode.SHORT_EXPRESSION,
                reasons=["solve phrase matched"],
                route_confidence=0.88,
            )

    return ExpressionCandidate(candidate=False)


def normalize_expression_text(expression: str) -> NormalizedCalculation:
    normalized = str(expression or "")
    notes: list[str] = []
    details: list[CalculationNormalizationDetail] = []

    replacements = {
        "\u2212": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u00d7": "*",
        "\u00f7": "/",
        "\u00b5": "u",
    }
    for source, target in replacements.items():
        if source in normalized:
            normalized = normalized.replace(source, target)
            notes.append(f"normalized '{source}' to '{target}'")

    if "**" in normalized:
        normalized = normalized.replace("**", "^")
        notes.append("normalized '**' to '^'")

    collapsed = re.sub(r"(?<=\d),(?=\d)", "", normalized)
    if collapsed != normalized:
        normalized = collapsed
        notes.append("removed numeric grouping commas")

    stripped_whitespace = "".join(normalized.split())
    if stripped_whitespace != normalized:
        normalized = stripped_whitespace
        notes.append("removed whitespace")
    normalized = stripped_whitespace

    fragments: list[str] = []
    index = 0
    prefers_engineering_display = False
    while index < len(normalized):
        character = normalized[index]
        if character in "+-*/^()":
            fragments.append(character)
            index += 1
            continue
        if character.isdigit() or character == ".":
            numeric_fragment, detail, consumed, note, prefers_engineering = _consume_numeric_token(normalized, index)
            fragments.append(numeric_fragment)
            details.append(detail)
            if note:
                notes.append(note)
            prefers_engineering_display = prefers_engineering_display or prefers_engineering
            index = consumed
            continue
        if UNIT_LABEL_CHAR_PATTERN.match(character):
            raise CalculationNormalizationError(
                f"Unsupported semantic text '{character}' inside direct numeric expression.",
                failure_type=CalculationFailureType.OUT_OF_SCOPE,
                user_message="Stormhelm can handle direct numeric expressions locally in this pass, but not that formula wording yet.",
                position=index,
                recovery_hint="Send the math as a direct expression such as 3.3k*2.2mA or 1.2e-3*4700.",
            )
        raise CalculationNormalizationError(
            f"Unexpected token '{character}'.",
            failure_type=CalculationFailureType.NORMALIZATION_ERROR,
            user_message="Stormhelm could not normalize that expression cleanly.",
            position=index,
            recovery_hint="Use direct arithmetic with digits, parentheses, operators, and supported suffixes like k, M, m, u, n, or p.",
        )

    normalized_expression = "".join(fragments)
    return NormalizedCalculation(
        normalized_expression=normalized_expression,
        normalization_notes=notes,
        normalization_details=details,
        parseable_boolean=looks_like_supported_expression(normalized_expression),
        display_preference="engineering" if prefers_engineering_display else "decimal",
    )


def looks_like_supported_expression(normalized_expression: str) -> bool:
    return bool(normalized_expression) and bool(NORMALIZED_EXPRESSION_PATTERN.fullmatch(normalized_expression))


def detect_requested_output_mode(raw_text: str, normalized_text: str) -> CalculationOutputMode:
    raw = str(raw_text or "").strip()
    normalized = str(normalized_text or "").strip()
    if not raw or not normalized:
        return CalculationOutputMode.ANSWER_ONLY
    if FORMULA_REQUEST_PATTERN.match(raw) or "show the formula" in normalized:
        return CalculationOutputMode.FORMULA_SUBSTITUTION
    if any(
        phrase in normalized
        for phrase in (
            "show the steps",
            "show me the steps",
            "walk me through",
            "how did you get that",
            "show your work",
            "why is that the answer",
        )
    ):
        return CalculationOutputMode.STEP_BY_STEP
    if any(phrase in normalized for phrase in ("break down", "show the breakdown", "short breakdown")):
        return CalculationOutputMode.SHORT_BREAKDOWN
    return CalculationOutputMode.ANSWER_ONLY


def _strip_terminal_punctuation(text: str) -> str:
    return str(text or "").strip().rstrip("?.!").strip()


def _looks_like_direct_expression(text: str) -> bool:
    if not text or not re.search(r"\d", text):
        return False
    if not _starts_like_expression(text):
        return False
    if not DIRECT_EXPRESSION_PATTERN.fullmatch(text):
        return False
    try:
        normalized = normalize_expression_text(text)
        return normalized.parseable_boolean
    except CalculationNormalizationError:
        return _looks_like_engineeringish_expression(text)


def _consume_numeric_token(
    expression: str,
    start_index: int,
) -> tuple[str, CalculationNormalizationDetail, int, str | None, bool]:
    index = start_index
    saw_digit = False
    saw_decimal = False
    saw_exponent = False

    while index < len(expression):
        current = expression[index]
        if current.isdigit():
            saw_digit = True
            index += 1
            continue
        if current == "." and not saw_decimal and not saw_exponent:
            saw_decimal = True
            index += 1
            continue
        break

    if not saw_digit:
        raise CalculationNormalizationError(
            "Expected digits in numeric literal.",
            failure_type=CalculationFailureType.NORMALIZATION_ERROR,
            user_message="Stormhelm expected digits in that numeric token.",
            position=start_index,
            recovery_hint="Send the expression with explicit digits, such as 4.7k or 1.2e-3.",
        )

    if index < len(expression) and expression[index] in {"e", "E"}:
        saw_exponent = True
        exponent_index = index + 1
        if exponent_index < len(expression) and expression[exponent_index] in {"+", "-"}:
            exponent_index += 1
        exponent_start = exponent_index
        while exponent_index < len(expression) and expression[exponent_index].isdigit():
            exponent_index += 1
        if exponent_index == exponent_start:
            raise CalculationNormalizationError(
                "Scientific notation exponent is incomplete.",
                failure_type=CalculationFailureType.NORMALIZATION_ERROR,
                user_message="Stormhelm could not normalize that scientific notation token cleanly.",
                position=index,
                recovery_hint="Use scientific notation like 1.2e-3.",
            )
        index = exponent_index

    raw_number = expression[start_index:index]
    try:
        base_value = Decimal(raw_number)
    except InvalidOperation as error:
        raise CalculationNormalizationError(
            "Invalid numeric literal.",
            failure_type=CalculationFailureType.NORMALIZATION_ERROR,
            user_message="Stormhelm could not normalize that numeric token cleanly.",
            position=start_index,
        ) from error

    engineering_suffix: str | None = None
    note: str | None = None
    if index < len(expression) and expression[index] in ENGINEERING_SUFFIX_CHARS:
        if saw_exponent:
            raise CalculationNormalizationError(
                "Scientific notation and engineering suffixes cannot be combined in one token yet.",
                failure_type=CalculationFailureType.NORMALIZATION_ERROR,
                user_message="Stormhelm could not normalize that token because it mixes scientific notation with an engineering suffix.",
                position=index,
                recovery_hint="Use either 1.2e-3 or 1.2m, but not both on the same number.",
            )
        engineering_suffix = "u" if expression[index] == "u" else expression[index]
        scale = ENGINEERING_SUFFIXES[engineering_suffix]
        base_value *= scale
        note = f"expanded engineering suffix '{engineering_suffix}'"
        index += 1

    unit_start = index
    while index < len(expression) and UNIT_LABEL_CHAR_PATTERN.match(expression[index]):
        index += 1
    raw_unit_label = expression[unit_start:index]

    if raw_unit_label and raw_unit_label[0] in ENGINEERING_SUFFIX_CHARS:
        raise CalculationNormalizationError(
            f"Invalid engineering suffix combination '{expression[start_index:index]}'.",
            failure_type=CalculationFailureType.NORMALIZATION_ERROR,
            user_message="Stormhelm could not normalize that engineering suffix combination cleanly.",
            position=unit_start,
            recovery_hint="Use one supported engineering suffix per numeric token, such as 4.7k or 2.2mA.",
        )

    unit_label = _normalize_unit_label(raw_unit_label) if raw_unit_label else None
    if raw_unit_label and unit_label is None:
        raise CalculationNormalizationError(
            f"Unsupported attached unit text '{raw_unit_label}'.",
            failure_type=CalculationFailureType.NORMALIZATION_ERROR,
            user_message="Stormhelm could not normalize that engineering token cleanly because the attached unit text is not supported yet.",
            position=unit_start,
            recovery_hint="Keep attached unit text to simple labels like A, V, F, Hz, ohm, or \u03a9 if you want Stormhelm to treat it as a numeric token.",
        )

    if engineering_suffix is None and unit_label is None:
        normalized_token = raw_number
        token_kind = "numeric_literal"
    else:
        normalized_token = _format_decimal_token(base_value)
        token_kind = "engineering_literal" if engineering_suffix is not None else "unit_annotated_literal"
    if unit_label is not None:
        note = f"{note}; stripped unit label '{unit_label}'" if note else f"stripped unit label '{unit_label}'"

    detail = CalculationNormalizationDetail(
        raw_token=expression[start_index:index],
        normalized_token=normalized_token,
        token_kind=token_kind,
        start_index=start_index,
        end_index=index,
        engineering_suffix=engineering_suffix,
        unit_label=unit_label,
    )
    prefers_engineering_display = engineering_suffix is not None or (
        unit_label is not None and abs(base_value) != 0 and (abs(base_value) < Decimal("0.001") or abs(base_value) >= Decimal("1000"))
    )
    return normalized_token, detail, index, note, prefers_engineering_display


def _normalize_unit_label(raw_unit_label: str) -> str | None:
    if not raw_unit_label:
        return None
    canonical = raw_unit_label.replace("\u00b5", "u")
    return SUPPORTED_UNIT_LABELS.get(canonical.lower())


def _format_decimal_token(value: Decimal) -> str:
    if value == 0:
        return "0"
    if value == value.to_integral_value():
        return format(value.quantize(Decimal("1")), "f")
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _contains_numeric_signal(text: str) -> bool:
    return bool(re.search(r"[\d()+\-*/^]", text))


def _contains_alpha(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text))


def _contains_operator(text: str) -> bool:
    return bool(re.search(r"[+\-*/^()]", text))


def _starts_like_expression(text: str) -> bool:
    return bool(re.match(r"^[\s(.\-0-9]", text))


def _looks_like_engineeringish_expression(text: str) -> bool:
    if not DIRECT_EXPRESSION_PATTERN.fullmatch(text):
        return False
    if not re.search(r"\d", text):
        return False
    if _contains_operator(text):
        return True
    if "." in text or re.search(r"[eE]", text):
        return True
    return bool(re.search(r"\d(?:[GMkmunp\u00b5]|[A-Za-z\u03a9]{1,4}$)", text))


def _operator_count(text: str) -> int:
    return sum(1 for character in text if character in "+-*/^")
