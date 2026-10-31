from __future__ import annotations

import re
from fractions import Fraction

from app.math.problem import Problem

_TOKEN = re.compile(
    r"\s*(?:(?P<mixed>\d+\s+\d+/\d+)|(?P<decimal>\d+[,.]\d+)|"
    r"(?P<integer>\d+)|(?P<operator>[()+\-*/·:×]))"
)
_EXPRESSION = re.compile(
    r"(?:Вычислите:|Найдите значение выражения:?)\s*(.+?)"
    r"(?:\. Представьте результат в виде несократимой|\. Запишите выражение|$)"
)


class OracleParseError(ValueError):
    pass


class _RenderedExpressionParser:
    """A separate parser: it evaluates the expression text delivered to the student."""

    def __init__(self, text: str) -> None:
        self.tokens: list[tuple[str, str]] = []
        cursor = 0
        while cursor < len(text):
            match = _TOKEN.match(text, cursor)
            if match is None:
                if text[cursor:].strip() == ".":
                    cursor = len(text)
                    break
                raise OracleParseError(f"Unexpected rendered character at {cursor}")
            kind = next(name for name, value in match.groupdict().items() if value is not None)
            self.tokens.append((kind, match.group(kind)))
            cursor = match.end()
        self.index = 0

    def parse(self) -> Fraction:
        value = self._sum()
        if self.index != len(self.tokens):
            raise OracleParseError("Trailing tokens in rendered expression")
        return value

    def _peek(self) -> str | None:
        return self.tokens[self.index][1] if self.index < len(self.tokens) else None

    def _take(self) -> tuple[str, str]:
        if self.index >= len(self.tokens):
            raise OracleParseError("Unexpected end of rendered expression")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def _sum(self) -> Fraction:
        value = self._product()
        while self._peek() in {"+", "-"}:
            operator = self._take()[1]
            right = self._product()
            value = value + right if operator == "+" else value - right
        return value

    def _product(self) -> Fraction:
        value = self._unary()
        while self._peek() in {"*", "/", "·", ":", "×"}:
            operator = self._take()[1]
            right = self._unary()
            if operator in {"*", "·", "×"}:
                value *= right
            else:
                if right == 0:
                    raise OracleParseError("Rendered division by zero")
                value /= right
        return value

    def _unary(self) -> Fraction:
        if self._peek() == "+":
            self._take()
            return self._unary()
        if self._peek() == "-":
            self._take()
            return -self._unary()
        kind, text = self._take()
        if text == "(":
            value = self._sum()
            if self._peek() != ")":
                raise OracleParseError("Unclosed parenthesis")
            self._take()
            return value
        if kind == "mixed":
            whole, numerator, denominator = map(int, re.split(r"\s+|/", text))
            if denominator == 0 or numerator >= denominator:
                raise OracleParseError("Invalid rendered mixed number")
            return Fraction(whole * denominator + numerator, denominator)
        if kind == "decimal":
            decimal_whole, decimal_part = re.split(r"[,.]", text)
            return Fraction(int(decimal_whole + decimal_part), 10 ** len(decimal_part))
        if kind == "integer":
            return Fraction(int(text))
        raise OracleParseError("Expected a rendered number")


def evaluate_rendered_condition(condition: str) -> Fraction:
    match = _EXPRESSION.search(condition)
    if match is None:
        raise OracleParseError("Condition does not contain a supported calculation prompt")
    expression = match.group(1).strip()
    if expression.endswith("."):
        expression = expression[:-1].rstrip()
    return _RenderedExpressionParser(expression).parse()


def validate_rendered_problem(problem: Problem) -> None:
    rendered_value = evaluate_rendered_condition(problem.condition)
    from app.math.answer_policy import AnswerFormat
    from app.math.ast import evaluate

    if rendered_value != evaluate(problem.expression):
        raise AssertionError("Rendered condition differs from its AST value")
    if problem.answer_policy.answer_format == AnswerFormat.PRESCRIBED_NUMERATOR:
        denominator_match = re.search(r"знаменателем\s+(\d+)", problem.condition)
        if denominator_match is None:
            raise AssertionError("Prescribed-denominator prompt has no denominator")
        scaled = rendered_value * int(denominator_match.group(1))
        if scaled.denominator != 1:
            raise AssertionError("Expression cannot be represented with the prescribed denominator")
        expected = problem.answer_policy.format(Fraction(scaled.numerator))
    else:
        expected = problem.answer_policy.format(rendered_value)
    if expected != problem.correct_answer:
        raise AssertionError("Displayed answer policy does not match rendered expression")
