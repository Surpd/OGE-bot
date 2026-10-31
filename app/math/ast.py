from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class Integer:
    value: int


@dataclass(frozen=True, slots=True)
class Decimal:
    unscaled: int
    places: int

    @property
    def value(self) -> Fraction:
        return Fraction(self.unscaled, 10**self.places)


@dataclass(frozen=True, slots=True)
class FractionLiteral:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.denominator <= 0:
            raise ValueError("Fraction denominator must be positive")

    @property
    def value(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


@dataclass(frozen=True, slots=True)
class MixedNumber:
    whole: int
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.whole < 0 or self.denominator <= 0:
            raise ValueError("Invalid mixed number")
        if not 0 < self.numerator < self.denominator:
            raise ValueError("Mixed-number fraction must be proper")

    @property
    def value(self) -> Fraction:
        return Fraction(self.whole * self.denominator + self.numerator, self.denominator)


@dataclass(frozen=True, slots=True)
class Negative:
    child: Atom


type Atom = Integer | Decimal | FractionLiteral | MixedNumber | Negative


@dataclass(frozen=True, slots=True)
class Group:
    child: Expr


@dataclass(frozen=True, slots=True)
class FractionBar:
    numerator: Expr
    denominator: Expr


@dataclass(frozen=True, slots=True)
class Binary:
    operator: str
    left: Expr
    right: Expr

    def __post_init__(self) -> None:
        if self.operator not in {"+", "-", "*", "/"}:
            raise ValueError(f"Unsupported operator: {self.operator}")


type Expr = Atom | Group | FractionBar | Binary


def evaluate(expression: Expr) -> Fraction:
    if isinstance(expression, Integer):
        return Fraction(expression.value)
    if isinstance(expression, Decimal):
        return expression.value
    if isinstance(expression, FractionLiteral):
        return expression.value
    if isinstance(expression, MixedNumber):
        return expression.value
    if isinstance(expression, Negative):
        return -evaluate(expression.child)
    if isinstance(expression, Group):
        return evaluate(expression.child)
    if isinstance(expression, FractionBar):
        denominator = evaluate(expression.denominator)
        if denominator == 0:
            raise ZeroDivisionError("Fraction-bar denominator is zero")
        return evaluate(expression.numerator) / denominator
    left = evaluate(expression.left)
    right = evaluate(expression.right)
    if expression.operator == "+":
        return left + right
    if expression.operator == "-":
        return left - right
    if expression.operator == "*":
        return left * right
    if right == 0:
        raise ZeroDivisionError("Division by zero in generated expression")
    return left / right


def render(expression: Expr) -> str:
    if isinstance(expression, Integer):
        return str(expression.value)
    if isinstance(expression, Decimal):
        scale = 10**expression.places
        whole, remainder = divmod(abs(expression.unscaled), scale)
        if expression.places == 0:
            return f"{'-' if expression.unscaled < 0 else ''}{whole}"
        fraction = f"{remainder:0{expression.places}d}"
        return f"{'-' if expression.unscaled < 0 else ''}{whole},{fraction}"
    if isinstance(expression, FractionLiteral):
        sign = "-" if expression.numerator < 0 else ""
        return f"{sign}{abs(expression.numerator)}/{expression.denominator}"
    if isinstance(expression, MixedNumber):
        return f"{expression.whole} {expression.numerator}/{expression.denominator}"
    if isinstance(expression, Negative):
        child = render(expression.child)
        return f"-({child})" if isinstance(expression.child, Binary) else f"-{child}"
    if isinstance(expression, Group):
        return f"({render(expression.child)})"
    if isinstance(expression, FractionBar):
        return f"{render(expression.numerator)}/{render(expression.denominator)}"

    left = render(expression.left)
    right = render(expression.right)
    if expression.operator in {"+", "-"}:
        return f"{left} {expression.operator} {right}"
    symbol = "·" if expression.operator == "*" else ":"
    return f"{left} {symbol} {right}"


def fraction_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"
