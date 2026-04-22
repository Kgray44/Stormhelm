from __future__ import annotations

from decimal import Context, Decimal, localcontext

from stormhelm.core.calculations.parser import BinaryNode
from stormhelm.core.calculations.parser import NumberNode
from stormhelm.core.calculations.parser import UnaryNode


class CalculationEvaluationError(ValueError):
    pass


def evaluate_expression(node: object) -> Decimal:
    with localcontext(Context(prec=50)):
        return _evaluate(node)


def _evaluate(node: object) -> Decimal:
    if isinstance(node, NumberNode):
        return node.value
    if isinstance(node, UnaryNode):
        value = _evaluate(node.operand)
        if node.operator == "-":
            return -value
        raise CalculationEvaluationError(f"Unsupported unary operator '{node.operator}'.")
    if isinstance(node, BinaryNode):
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if node.operator == "+":
            return left + right
        if node.operator == "-":
            return left - right
        if node.operator == "*":
            return left * right
        if node.operator == "/":
            if right == 0:
                raise CalculationEvaluationError("Division by zero is not defined.")
            return left / right
        if node.operator == "^":
            return _power(left, right)
        raise CalculationEvaluationError(f"Unsupported binary operator '{node.operator}'.")
    raise CalculationEvaluationError("Unsupported expression node.")


def _power(base: Decimal, exponent: Decimal) -> Decimal:
    if exponent != exponent.to_integral_value():
        raise CalculationEvaluationError("Fractional exponentiation is outside Calc-0 scope.")
    integer_exponent = int(exponent)
    if integer_exponent >= 0:
        return base**integer_exponent
    powered = base ** abs(integer_exponent)
    if powered == 0:
        raise CalculationEvaluationError("Division by zero is not defined.")
    return Decimal(1) / powered
