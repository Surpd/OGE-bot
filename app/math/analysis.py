from __future__ import annotations

from collections import Counter
from fractions import Fraction
from math import gcd, lcm

from app.math.answer_policy import decimal_places
from app.math.ast import (
    Decimal,
    Expr,
    FractionBar,
    FractionLiteral,
    Group,
    Integer,
    MixedNumber,
    Negative,
)


def structural_signature(expression: Expr) -> str:
    """Return a numeric-value-independent AST shape for prototype diversity checks."""
    if isinstance(expression, Integer):
        return "integer"
    if isinstance(expression, Decimal):
        return "decimal"
    if isinstance(expression, FractionLiteral):
        return "fraction"
    if isinstance(expression, MixedNumber):
        return "mixed_number"
    if isinstance(expression, Negative):
        return f"negative({structural_signature(expression.child)})"
    if isinstance(expression, Group):
        return f"group({structural_signature(expression.child)})"
    if isinstance(expression, FractionBar):
        return (
            f"fraction_bar({structural_signature(expression.numerator)},"
            f"{structural_signature(expression.denominator)})"
        )
    operator = {"+": "add", "-": "subtract", "*": "multiply", "/": "divide"}[expression.operator]
    return (
        f"{operator}({structural_signature(expression.left)},"
        f"{structural_signature(expression.right)})"
    )


def expression_metrics(expression: Expr) -> dict[str, object]:
    operators: Counter[str] = Counter()
    denominators: list[int] = []
    decimals: list[int] = []
    signed_values: list[Fraction] = []
    groups = 0

    def visit(node: Expr) -> None:
        nonlocal groups
        if isinstance(node, Integer):
            signed_values.append(Fraction(node.value))
        elif isinstance(node, Decimal):
            signed_values.append(node.value)
            decimals.append(node.places)
        elif isinstance(node, FractionLiteral):
            signed_values.append(node.value)
            denominators.append(node.denominator)
        elif isinstance(node, MixedNumber):
            signed_values.append(node.value)
            denominators.append(node.denominator)
        elif isinstance(node, Negative):
            visit(node.child)
        elif isinstance(node, Group):
            groups += 1
            visit(node.child)
        elif isinstance(node, FractionBar):
            operators["fraction_bar"] += 1
            visit(node.numerator)
            visit(node.denominator)
        else:
            operators[node.operator] += 1
            visit(node.left)
            visit(node.right)

    visit(expression)
    return {
        "signature": structural_signature(expression),
        "operations": dict(sorted(operators.items())),
        "action_count": sum(operators.values()),
        "group_count": groups,
        "operand_count": len(signed_values),
        "negative_operands": sum(value < 0 for value in signed_values),
        "zero_operands": sum(value == 0 for value in signed_values),
        "operand_min": str(min(signed_values)) if signed_values else None,
        "operand_max": str(max(signed_values)) if signed_values else None,
        "fraction_denominators": denominators,
        "decimal_operand_places": decimals,
    }


def answer_metrics(value: Fraction) -> dict[str, object]:
    places = decimal_places(value)
    return {
        "answer_class": "non_terminating"
        if places is None
        else ("integer" if places == 0 else f"decimal_{places}_places"),
        "decimal_places": places,
        "negative": value < 0,
        "zero": value == 0,
        "absolute_value": str(abs(value)),
    }


def calculation_diagnostics(expression: Expr) -> dict[str, int]:
    max_numerator = 0
    max_denominator = 1
    max_common_denominator = 1
    max_integer_factor = 0
    actions = 0
    transformations = 0
    cancellations = 0

    def record(value: Fraction) -> None:
        nonlocal max_numerator, max_denominator
        max_numerator = max(max_numerator, abs(value.numerator))
        max_denominator = max(max_denominator, value.denominator)

    def visit(node: Expr) -> Fraction:
        nonlocal max_common_denominator, max_integer_factor
        nonlocal actions, transformations, cancellations
        if isinstance(node, Integer):
            max_integer_factor = max(max_integer_factor, abs(node.value))
            value = Fraction(node.value)
        elif isinstance(node, Decimal):
            max_integer_factor = max(max_integer_factor, abs(node.unscaled))
            value = node.value
        elif isinstance(node, FractionLiteral):
            max_integer_factor = max(max_integer_factor, abs(node.numerator), node.denominator)
            value = node.value
        elif isinstance(node, MixedNumber):
            max_integer_factor = max(
                max_integer_factor, node.whole, node.numerator, node.denominator
            )
            transformations += 1
            value = node.value
        elif isinstance(node, Negative):
            value = -visit(node.child)
        elif isinstance(node, Group):
            value = visit(node.child)
        elif isinstance(node, FractionBar):
            numerator = visit(node.numerator)
            denominator = visit(node.denominator)
            if denominator == 0:
                raise ZeroDivisionError("Fraction bar denominator is zero")
            actions += 1
            transformations += 1
            cross_left = gcd(abs(numerator.numerator), abs(denominator.numerator))
            cross_right = gcd(denominator.denominator, numerator.denominator)
            cancellations += int(cross_left > 1) + int(cross_right > 1)
            value = numerator / denominator
        else:
            left = visit(node.left)
            right = visit(node.right)
            actions += 1
            if node.operator in {"+", "-"}:
                common = lcm(left.denominator, right.denominator)
                max_common_denominator = max(max_common_denominator, common)
                if left.denominator != right.denominator:
                    transformations += 1
                value = left + right if node.operator == "+" else left - right
            elif node.operator == "*":
                cross_left = gcd(abs(left.numerator), right.denominator)
                cross_right = gcd(abs(right.numerator), left.denominator)
                cancellations += int(cross_left > 1) + int(cross_right > 1)
                if cross_left > 1 or cross_right > 1:
                    transformations += 1
                value = left * right
            else:
                if right == 0:
                    raise ZeroDivisionError("Division by zero")
                transformations += 1
                cross_left = gcd(abs(left.numerator), abs(right.numerator))
                cross_right = gcd(left.denominator, right.denominator)
                cancellations += int(cross_left > 1) + int(cross_right > 1)
                value = left / right
        record(value)
        return value

    visit(expression)
    return {
        "max_intermediate_numerator": max_numerator,
        "max_intermediate_denominator": max_denominator,
        "max_common_denominator": max_common_denominator,
        "max_integer_factor": max_integer_factor,
        "arithmetic_actions": actions,
        "transformation_count": transformations,
        "cancellation_count": cancellations,
        "estimated_manual_steps": actions + transformations + cancellations,
    }
