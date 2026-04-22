from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(slots=True)
class Token:
    kind: str
    text: str
    position: int


@dataclass(slots=True)
class NumberNode:
    value: Decimal
    raw: str


@dataclass(slots=True)
class UnaryNode:
    operator: str
    operand: object


@dataclass(slots=True)
class BinaryNode:
    left: object
    operator: str
    right: object


class CalculationParseError(ValueError):
    def __init__(self, message: str, *, position: int | None = None) -> None:
        super().__init__(message)
        self.position = position


def parse_expression(expression: str) -> object:
    tokens = _tokenize(expression)
    parser = _ExpressionParser(tokens)
    result = parser.parse()
    parser.expect("EOF")
    return result


def _tokenize(expression: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    while index < len(expression):
        character = expression[index]
        if character in "+-*/^()":
            tokens.append(Token(kind=character, text=character, position=index))
            index += 1
            continue
        if character.isdigit() or character == ".":
            start = index
            saw_decimal = character == "."
            saw_digit = character.isdigit()
            index += 1
            while index < len(expression):
                current = expression[index]
                if current.isdigit():
                    saw_digit = True
                    index += 1
                    continue
                if current == "." and not saw_decimal:
                    saw_decimal = True
                    index += 1
                    continue
                break
            if not saw_digit:
                raise CalculationParseError("Expected digits in numeric literal.", position=start)
            if index < len(expression) and expression[index] in {"e", "E"}:
                exponent_index = index + 1
                if exponent_index < len(expression) and expression[exponent_index] in {"+", "-"}:
                    exponent_index += 1
                exponent_start = exponent_index
                while exponent_index < len(expression) and expression[exponent_index].isdigit():
                    exponent_index += 1
                if exponent_index == exponent_start:
                    raise CalculationParseError("Scientific notation exponent is incomplete.", position=index)
                index = exponent_index
            raw = expression[start:index]
            try:
                Decimal(raw)
            except InvalidOperation as error:
                raise CalculationParseError("Invalid numeric literal.", position=start) from error
            tokens.append(Token(kind="NUMBER", text=raw, position=start))
            continue
        raise CalculationParseError(f"Unexpected token '{character}'.", position=index)
    tokens.append(Token(kind="EOF", text="", position=len(expression)))
    return tokens


class _ExpressionParser:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._index = 0

    @property
    def current(self) -> Token:
        return self._tokens[self._index]

    def parse(self) -> object:
        return self._parse_expression()

    def expect(self, kind: str) -> Token:
        token = self.current
        if token.kind != kind:
            raise CalculationParseError(f"Expected '{kind}' but found '{token.text or token.kind}'.", position=token.position)
        self._index += 1
        return token

    def _parse_expression(self) -> object:
        node = self._parse_term()
        while self.current.kind in {"+", "-"}:
            operator = self.expect(self.current.kind).kind
            right = self._parse_term()
            node = BinaryNode(left=node, operator=operator, right=right)
        return node

    def _parse_term(self) -> object:
        node = self._parse_power()
        while self.current.kind in {"*", "/"}:
            operator = self.expect(self.current.kind).kind
            right = self._parse_power()
            node = BinaryNode(left=node, operator=operator, right=right)
        return node

    def _parse_power(self) -> object:
        node = self._parse_unary()
        if self.current.kind == "^":
            operator = self.expect("^").kind
            right = self._parse_power()
            return BinaryNode(left=node, operator=operator, right=right)
        return node

    def _parse_unary(self) -> object:
        if self.current.kind == "-":
            self.expect("-")
            return UnaryNode(operator="-", operand=self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> object:
        token = self.current
        if token.kind == "NUMBER":
            self.expect("NUMBER")
            return NumberNode(value=Decimal(token.text), raw=token.text)
        if token.kind == "(":
            self.expect("(")
            node = self._parse_expression()
            self.expect(")")
            return node
        raise CalculationParseError("Expected a number or parenthesized expression.", position=token.position)
