from __future__ import annotations

from decimal import Decimal

from stormhelm.core.calculations.formatter import format_decimal
from stormhelm.core.calculations.formatter import format_expression_for_display
from stormhelm.core.calculations.models import CalculationExplanation
from stormhelm.core.calculations.models import CalculationNormalizationDetail
from stormhelm.core.calculations.models import CalculationOutputMode
from stormhelm.core.calculations.parser import BinaryNode
from stormhelm.core.calculations.parser import NumberNode
from stormhelm.core.calculations.parser import UnaryNode


ROUNDING_NOTE = "Displayed result rounded for readability."


def explanation_mode_used(mode: CalculationOutputMode) -> CalculationOutputMode:
    if mode == CalculationOutputMode.SHORT_EXPRESSION:
        return CalculationOutputMode.SHORT_BREAKDOWN
    return mode


def render_direct_explanation(
    *,
    requested_mode: CalculationOutputMode,
    normalized_expression: str,
    syntax_tree: object,
    formatted_value: str,
    approximate: bool,
    normalization_details: list[CalculationNormalizationDetail],
    follow_up_reuse: bool,
) -> CalculationExplanation | None:
    mode = explanation_mode_used(requested_mode)
    relation = "~=" if approximate else "="
    summary = f"{format_expression_for_display(normalized_expression)} {relation} {formatted_value}"
    rounding_note = ROUNDING_NOTE if approximate else None
    if mode == CalculationOutputMode.ANSWER_ONLY:
        return None
    if mode == CalculationOutputMode.SHORT_BREAKDOWN:
        return CalculationExplanation(
            mode=mode,
            source_type="direct_expression",
            summary=summary,
            rounding_note=rounding_note,
            reused_prior_result=follow_up_reuse,
        )
    if mode == CalculationOutputMode.FORMULA_SUBSTITUTION:
        return CalculationExplanation(
            mode=CalculationOutputMode.SHORT_BREAKDOWN,
            source_type="direct_expression",
            summary=summary,
            rounding_note=rounding_note,
            reused_prior_result=follow_up_reuse,
        )
    if mode == CalculationOutputMode.STEP_BY_STEP:
        steps = _normalization_steps(normalization_details)
        reduction_steps = _reduction_steps(syntax_tree)
        steps.extend(reduction_steps)
        if rounding_note:
            steps.append(rounding_note)
        return CalculationExplanation(
            mode=mode,
            source_type="direct_expression",
            summary=summary,
            steps=steps,
            formula=format_expression_for_display(normalized_expression),
            rounding_note=rounding_note,
            reused_prior_result=follow_up_reuse,
        )
    return CalculationExplanation(
        mode=mode,
        source_type="direct_expression",
        summary=summary,
        rounding_note=rounding_note,
        reused_prior_result=follow_up_reuse,
    )


def render_helper_explanation(
    *,
    requested_mode: CalculationOutputMode,
    helper_label: str,
    formatted_value: str,
    approximate: bool,
    formula_symbolic: str | None,
    substitution_rows: list[str],
    follow_up_reuse: bool,
) -> CalculationExplanation | None:
    mode = explanation_mode_used(requested_mode)
    relation = "~=" if approximate else "="
    answer_only = f"{helper_label} {relation} {formatted_value}"
    rounding_note = ROUNDING_NOTE if approximate else None
    if mode == CalculationOutputMode.ANSWER_ONLY:
        return None
    if not formula_symbolic or not substitution_rows:
        return CalculationExplanation(
            mode=CalculationOutputMode.SHORT_BREAKDOWN,
            source_type="helper",
            summary=answer_only,
            rounding_note=rounding_note,
            reused_prior_result=follow_up_reuse,
        )
    lhs = formula_symbolic.split("=", 1)[0].strip()
    substituted = substitution_rows[0].strip()
    substituted_rhs = substituted.split("=", 1)[1].strip() if "=" in substituted else substituted
    condensed = f"{formula_symbolic} = {substituted_rhs} {relation} {formatted_value}"
    if mode == CalculationOutputMode.SHORT_BREAKDOWN:
        return CalculationExplanation(
            mode=mode,
            source_type="helper",
            summary=condensed,
            formula=formula_symbolic,
            substitution_rows=list(substitution_rows),
            rounding_note=rounding_note,
            reused_prior_result=follow_up_reuse,
        )
    if mode == CalculationOutputMode.FORMULA_SUBSTITUTION:
        rows = [formula_symbolic, *substitution_rows, f"{lhs} {relation} {formatted_value}"]
        if rounding_note:
            rows.append(rounding_note)
        return CalculationExplanation(
            mode=mode,
            source_type="helper",
            summary=condensed,
            formula=formula_symbolic,
            substitution_rows=list(substitution_rows),
            steps=rows,
            rounding_note=rounding_note,
            reused_prior_result=follow_up_reuse,
        )
    if mode == CalculationOutputMode.STEP_BY_STEP:
        rows = [formula_symbolic, *substitution_rows, f"Evaluate {substituted_rhs}", f"{lhs} {relation} {formatted_value}"]
        if rounding_note:
            rows.append(rounding_note)
        return CalculationExplanation(
            mode=mode,
            source_type="helper",
            summary=condensed,
            formula=formula_symbolic,
            substitution_rows=list(substitution_rows),
            steps=rows,
            rounding_note=rounding_note,
            reused_prior_result=follow_up_reuse,
        )
    return CalculationExplanation(
        mode=mode,
        source_type="helper",
        summary=answer_only,
        formula=formula_symbolic,
        substitution_rows=list(substitution_rows),
        rounding_note=rounding_note,
        reused_prior_result=follow_up_reuse,
    )


def render_verification_explanation(
    *,
    normalized_expression: str,
    formatted_actual_value: str,
    claim_text: str,
    matches: bool,
    follow_up_reuse: bool,
) -> CalculationExplanation:
    relation = "matches" if matches else "does not match"
    summary = (
        f"{format_expression_for_display(normalized_expression)} = {formatted_actual_value}, so {claim_text} is correct."
        if matches
        else f"{format_expression_for_display(normalized_expression)} = {formatted_actual_value}, so {claim_text} is incorrect."
    )
    return CalculationExplanation(
        mode=CalculationOutputMode.VERIFICATION_EXPLANATION,
        source_type="verification",
        summary=summary,
        steps=[
            f"Computed {format_expression_for_display(normalized_expression)} = {formatted_actual_value}",
            f"The claim {claim_text} {relation} the deterministic result.",
        ],
        verification_summary=summary,
        reused_prior_result=follow_up_reuse,
    )


def compose_explanation_response(explanation: CalculationExplanation | None, *, default_response: str) -> str:
    if explanation is None:
        return default_response
    if explanation.mode == CalculationOutputMode.VERIFICATION_EXPLANATION:
        return explanation.summary or default_response
    if explanation.mode in {
        CalculationOutputMode.SHORT_BREAKDOWN,
        CalculationOutputMode.FORMULA_SUBSTITUTION,
        CalculationOutputMode.STEP_BY_STEP,
    } and explanation.steps:
        return "\n".join(explanation.steps)
    return explanation.summary or default_response


def _normalization_steps(details: list[CalculationNormalizationDetail]) -> list[str]:
    lines: list[str] = []
    for detail in details:
        if detail.raw_token == detail.normalized_token:
            continue
        lines.append(f"{detail.raw_token} -> {detail.normalized_token}")
    return lines


def _reduction_steps(node: object) -> list[str]:
    _, steps, _ = _reduce_node(node)
    return steps


def _reduce_node(node: object) -> tuple[str, list[str], Decimal]:
    if isinstance(node, NumberNode):
        return _format_value(node.value), [], node.value
    if isinstance(node, UnaryNode):
        operand_display, steps, operand_value = _reduce_node(node.operand)
        result = -operand_value
        line = f"-{operand_display} = {_format_value(result)}"
        return _format_value(result), [*steps, line], result
    if isinstance(node, BinaryNode):
        left_display, left_steps, left_value = _reduce_node(node.left)
        right_display, right_steps, right_value = _reduce_node(node.right)
        result = _apply_operator(left_value, node.operator, right_value)
        line = f"{left_display} {node.operator} {right_display} = {_format_value(result)}"
        return _format_value(result), [*left_steps, *right_steps, line], result
    raise ValueError("Unsupported expression node for explanation rendering.")


def _apply_operator(left: Decimal, operator: str, right: Decimal) -> Decimal:
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if operator == "/":
        return left / right
    if operator == "^":
        return left ** int(right)
    raise ValueError(f"Unsupported operator '{operator}'.")


def _format_value(value: Decimal) -> str:
    return format_decimal(value)
