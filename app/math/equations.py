"""Verified, Telegram-independent equation generator for OGE task 9."""

from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass
from fractions import Fraction
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import AnswerFormat, AnswerPolicy, format_decimal

GENERATOR_VERSION = "0.2.0"


@dataclass(frozen=True, slots=True)
class Number:
    value: Fraction


@dataclass(frozen=True, slots=True)
class Variable:
    degree: int = 1

    def __post_init__(self) -> None:
        if self.degree not in {1, 2}:
            raise ValueError("Only linear and quadratic variables are supported")


@dataclass(frozen=True, slots=True)
class Group:
    expression: Expr


@dataclass(frozen=True, slots=True)
class Unary:
    operator: str
    expression: Expr

    def __post_init__(self) -> None:
        if self.operator != "-":
            raise ValueError("Only unary minus is supported")


@dataclass(frozen=True, slots=True)
class Operation:
    operator: str
    left: Expr
    right: Expr

    def __post_init__(self) -> None:
        if self.operator not in {"+", "-", "*", "/"}:
            raise ValueError(f"Unsupported equation operator {self.operator}")


type Expr = Number | Variable | Group | Unary | Operation


@dataclass(frozen=True, slots=True)
class Equation:
    left: Expr
    right: Expr


@dataclass(frozen=True, slots=True)
class EquationProblem:
    problem_id: str
    seed: int
    generator_version: str
    family_id: str
    reference_structure_id: str
    reference_ids: tuple[str, ...]
    condition: str
    equation_text: str
    target_root: Fraction
    roots: tuple[Fraction, ...]
    correct_answer: str
    answer_policy_id: str
    answer_policy_version: str
    answer_target: str
    hints: tuple[str, ...]
    solution: tuple[str, ...]
    fingerprint: str

    def to_snapshot(self) -> dict[str, object]:
        return {
            "problem_id": self.problem_id,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "family_id": self.family_id,
            "reference_structure_id": self.reference_structure_id,
            "reference_ids": list(self.reference_ids),
            "condition": self.condition,
            "equation_text": self.equation_text,
            "target_root": _format_root(self.target_root),
            "roots": [_format_root(root) for root in self.roots],
            "correct_answer": self.correct_answer,
            "answer_policy_id": self.answer_policy_id,
            "answer_policy_version": self.answer_policy_version,
            "answer_target": self.answer_target,
            "hints": list(self.hints),
            "solution": list(self.solution),
            "fingerprint": self.fingerprint,
        }


POLICY = AnswerPolicy(
    policy_id="oge9.numeric-single-root",
    version="1",
    answer_format=AnswerFormat.SINGLE_NUMBER,
    max_decimal_places=2,
    max_absolute_value=100,
)
ANSWER_POLICIES_BY_SNAPSHOT = {
    (policy_id, POLICY.version): POLICY
    for policy_id in (
        POLICY.policy_id,
        "oge9.numeric-lesser-root",
        "oge9.numeric-greater-root",
    )
}

_SOURCES: dict[str, tuple[str, ...]] = {
    "OGE09-L1": ("338606", "338658"),
    "OGE09-L2": ("338488", "338557"),
    "OGE09-L3": ("338509",),
    "OGE09-L4A": ("85",),
    "OGE09-L4B": ("338495",),
    "OGE09-K2": ("357568",),
    "OGE09-K3": ("357133", "357135"),
    "OGE09-K6": ("357173",),
}
ENABLED_FAMILIES = tuple(_SOURCES)
FAMILY_GROUP = {
    family: ("linear" if family.startswith("OGE09-L") else "quadratic") for family in _SOURCES
}
ROOT_SELECTION = {
    family: ("greater" if family == "OGE09-K2" else "lesser")
    for family in _SOURCES
    if family.startswith("OGE09-K")
}


def _fmt(value: Fraction) -> str:
    return (
        str(value.numerator)
        if value.denominator == 1
        else f"({value.numerator}/{value.denominator})"
    )


def _format_root(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    try:
        return format_decimal(value)
    except ValueError:
        return f"{value.numerator}/{value.denominator}"


def render_expr(expr: Expr) -> str:
    if isinstance(expr, Number):
        return _fmt(expr.value)
    if isinstance(expr, Variable):
        return "x²" if expr.degree == 2 else "x"
    if isinstance(expr, Group):
        return f"({render_expr(expr.expression)})"
    if isinstance(expr, Unary):
        child = render_expr(expr.expression)
        return f"-({child})" if isinstance(expr.expression, Operation) else f"-{child}"
    if expr.operator == "*":
        if isinstance(expr.left, Number) and isinstance(expr.right, Variable):
            coefficient = expr.left.value
            if coefficient == 1:
                return render_expr(expr.right)
            if coefficient == -1:
                return f"-{render_expr(expr.right)}"
            return f"{_fmt(coefficient)}{render_expr(expr.right)}"
        if isinstance(expr.left, Number) and isinstance(expr.right, Group):
            return f"{_fmt(expr.left.value)}{render_expr(expr.right)}"
        return f"{render_expr(expr.left)}·{render_expr(expr.right)}"
    if expr.operator == "/":
        return f"({render_expr(expr.left)})/({render_expr(expr.right)})"
    left, right = render_expr(expr.left), render_expr(expr.right)
    if expr.operator == "+" and isinstance(expr.right, Number) and expr.right.value < 0:
        return f"{left} - {_fmt(-expr.right.value)}"
    if expr.operator == "+" and isinstance(expr.right, Operation) and expr.right.operator == "*":
        if isinstance(expr.right.left, Number) and expr.right.left.value < 0:
            factor = render_expr(Operation("*", Number(-expr.right.left.value), expr.right.right))
            return f"{left} - {factor}"
    if expr.operator == "+" and isinstance(expr.right, Unary):
        return f"{left} - {render_expr(expr.right.expression)}"
    return f"{left} {expr.operator} {right}"


def render_equation(equation: Equation) -> str:
    return f"{render_expr(equation.left)} = {render_expr(equation.right)}"


Poly = tuple[Fraction, Fraction, Fraction]
OraclePoly = tuple[Fraction, Fraction, Fraction]


def _poly_add(left: Poly, right: Poly, sign: int = 1) -> Poly:
    return tuple(left[index] + sign * right[index] for index in range(3))  # type: ignore[return-value]


def _poly_mul(left: Poly, right: Poly) -> Poly:
    values = [Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0)]
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            values[i + j] += a * b
    if values[3] or values[4]:
        raise ValueError("Rendered equation has degree above two")
    return values[0], values[1], values[2]


def _oracle_add(left: OraclePoly, right: OraclePoly, subtract: bool = False) -> OraclePoly:
    """Independent coefficient combiner used only by the rendered-text oracle."""
    direction = Fraction(-1 if subtract else 1)
    return (
        left[0] + direction * right[0],
        left[1] + direction * right[1],
        left[2] + direction * right[2],
    )


def _oracle_multiply(left: OraclePoly, right: OraclePoly) -> OraclePoly:
    c0 = left[0] * right[0]
    c1 = left[0] * right[1] + left[1] * right[0]
    c2 = left[0] * right[2] + left[1] * right[1] + left[2] * right[0]
    if left[1] * right[2] + left[2] * right[1] or left[2] * right[2]:
        raise ValueError("Oracle display parser found degree above two")
    return c0, c1, c2


def _poly(expression: Expr) -> Poly:
    zero = Fraction(0)
    if isinstance(expression, Number):
        return expression.value, zero, zero
    if isinstance(expression, Variable):
        return (zero, Fraction(1), zero) if expression.degree == 1 else (zero, zero, Fraction(1))
    if isinstance(expression, Group):
        return _poly(expression.expression)
    if isinstance(expression, Unary):
        return tuple(-item for item in _poly(expression.expression))  # type: ignore[return-value]
    left, right = _poly(expression.left), _poly(expression.right)
    if expression.operator == "+":
        return _poly_add(left, right)
    if expression.operator == "-":
        return _poly_add(left, right, -1)
    if expression.operator == "*":
        return _poly_mul(left, right)
    if right[1] or right[2] or not right[0]:
        raise ValueError("Division by a non-constant expression is unsupported")
    return tuple(item / right[0] for item in left)  # type: ignore[return-value]


def _sqrt_fraction(value: Fraction) -> Fraction | None:
    if value < 0:
        return None
    n, d = math.isqrt(value.numerator), math.isqrt(value.denominator)
    return Fraction(n, d) if n * n == value.numerator and d * d == value.denominator else None


def solve_equation(equation: Equation) -> tuple[Fraction, ...]:
    polynomial = _poly(equation.left)
    polynomial = _poly_add(polynomial, _poly(equation.right), -1)
    c, b, a = polynomial
    if a == 0:
        if b == 0:
            raise ValueError("Equation is degenerate or has infinitely many roots")
        return (-c / b,)
    discriminant = b * b - 4 * a * c
    square_root = _sqrt_fraction(discriminant)
    if square_root is None:
        raise ValueError("Equation does not have rational real roots")
    roots = sorted({(-b - square_root) / (2 * a), (-b + square_root) / (2 * a)})
    if not roots:
        raise ValueError("Equation has no real roots")
    return tuple(roots)


def _n(value: int | Fraction) -> Number:
    return Number(Fraction(value))


def _op(operator: str, left: Expr, right: Expr) -> Operation:
    return Operation(operator, left, right)


def _x() -> Variable:
    return Variable()


def _x2() -> Variable:
    return Variable(2)


def _linear_from_coefficients(a: int, b: int, c: int, d: int) -> Equation:
    return Equation(_op("+", _op("*", _n(a), _x()), _n(b)), _op("+", _op("*", _n(c), _x()), _n(d)))


def _choose_root(rng: random.Random) -> Fraction:
    if rng.randrange(5) == 0:
        return Fraction(rng.choice([-15, -10, -5, 5, 10, 15]), 10)
    return Fraction(rng.randint(-10, 10))


def _build_linear(family: str, rng: random.Random) -> Equation:
    root = _choose_root(rng)
    denominator = root.denominator
    a = rng.choice([denominator, denominator * 2, denominator * 3, denominator * 4])
    b = rng.randint(-15, 15)
    c = a * root.numerator // denominator + b
    if family == "OGE09-L1":
        return Equation(_op("+", _op("*", _n(a), _x()), _n(b)), _n(c))
    if family == "OGE09-L2":
        right_a = a + rng.choice([-2, -1, 1, 2]) * denominator
        right_b = a * root.numerator // denominator + b - right_a * root.numerator // denominator
        return _linear_from_coefficients(a, b, right_a, right_b)
    if family == "OGE09-L3":
        root = Fraction(rng.randint(-12, 12), 2)
        denominator = root.denominator
        a = rng.choice([denominator * value for value in (2, 3, 4)])
        shift = rng.randint(-6, 6)
        right = a * root.numerator // denominator + a * shift
        return Equation(_op("*", _n(a), Group(_op("+", _x(), _n(shift)))), _n(right))
    if family == "OGE09-L4A":
        root = Fraction(rng.choice([value for value in range(-10, 11) if value]), 2)
        grouped_coefficient = rng.randint(2, 4)
        inner_coefficient = rng.randint(2, 3)
        shift, constant = rng.randint(-4, 4), rng.randint(-6, 6)
        compatible_deltas = [
            delta
            for delta in range(-4, 5)
            if delta != 0
            and 2 <= grouped_coefficient * inner_coefficient + delta <= 8
            and (delta * root).denominator == 1
        ]
        delta = rng.choice(compatible_deltas)
        right_coefficient = grouped_coefficient * inner_coefficient + delta
        right_constant = (
            constant
            - grouped_coefficient * shift
            + (right_coefficient - grouped_coefficient * inner_coefficient) * root
        )
        return Equation(
            _op(
                "-",
                _n(constant),
                _op(
                    "*",
                    _n(grouped_coefficient),
                    Group(_op("+", _op("*", _n(inner_coefficient), _x()), _n(shift))),
                ),
            ),
            _op("+", _n(right_constant), _op("*", _n(-right_coefficient), _x())),
        )
    if family == "OGE09-L4B":
        # Preserve the two-sided grouped form observed in #338495:
        # -x + a + b(x+c) = d(e-x) + f.
        root = Fraction(rng.choice([value for value in range(-10, 11) if value]), 2)
        compatible_pairs = [
            (grouped_left, grouped_right)
            for grouped_left in range(2, 5)
            for grouped_right in range(2, 5)
            if ((grouped_left + grouped_right - 1) * root).denominator == 1
        ]
        grouped_left, grouped_right = rng.choice(compatible_pairs)
        for _ in range(32):
            left_constant = rng.randint(-4, 4)
            inner_left = rng.randint(-4, 4)
            inner_right = rng.randint(-4, 4)
            right_constant = (
                left_constant
                + grouped_left * inner_left
                + (grouped_left + grouped_right - 1) * root
                - grouped_right * inner_right
            )
            if abs(right_constant) <= 60:
                break
        else:
            left_constant = inner_left = inner_right = 0
            right_constant = (grouped_left + grouped_right - 1) * root
        left = _op(
            "+",
            _op("+", Unary("-", _x()), _n(left_constant)),
            _op("*", _n(grouped_left), Group(_op("+", _x(), _n(inner_left)))),
        )
        right_expr = _op(
            "+",
            _op("*", _n(grouped_right), Group(_op("+", _n(inner_right), Unary("-", _x())))),
            _n(right_constant),
        )
        return Equation(left, right_expr)
    # Fallback for future explicitly registered linear forms.
    # Two grouped linear expressions, with a nonzero combined x coefficient.
    left_a, right_a = rng.randint(1, 6), rng.randint(1, 6)
    while 2 * left_a == right_a:
        right_a = rng.randint(1, 6)
    left_b, right_b = rng.randint(-8, 8), rng.randint(-8, 8)
    left_const = rng.randint(-10, 10)
    xcoef = 2 * left_a - right_a
    target = xcoef * root + left_a * left_b + left_const - right_a * right_b
    if target.denominator != 1:
        scale = denominator
        left_a *= scale
        right_a *= scale
        xcoef = 2 * left_a - right_a
        target = xcoef * root + left_a * left_b + left_const - right_a * right_b
    return Equation(
        _op(
            "+",
            _n(left_const),
            _op("*", _n(left_a), Group(_op("+", _op("*", _n(2), _x()), _n(left_b)))),
        ),
        _op("+", _n(int(target)), _op("*", _n(right_a), Group(_op("+", _x(), _n(right_b))))),
    )


def _choose_roots(rng: random.Random) -> tuple[int, int]:
    choices = [value for value in range(-12, 13) if value != 0]
    while True:
        first, second = rng.sample(choices, 2)
        if first + second != 0:
            break
    return min(first, second), max(first, second)


def _choose_rational_roots(rng: random.Random) -> tuple[Fraction, Fraction]:
    values = {
        Fraction(number, denominator)
        for denominator in (1, 2)
        for number in range(-8, 9)
        if number != 0
    }
    choices = sorted(values)
    while True:
        first, second = rng.sample(choices, 2)
        if first + second != 0:
            return min(first, second), max(first, second)


def k6_parameter_domain() -> tuple[tuple[int, Fraction], ...]:
    """Return the exact finite parameter domain for the enabled K6 prototype."""
    return tuple(
        (value, coefficient)
        for value in range(1, 13)
        for numerator in range(1, 11)
        for denominator in range(1, 11)
        for coefficient in (Fraction(numerator, denominator),)
        if (coefficient * value * value).denominator == 1
        and coefficient * value * value <= 196
    )


def _build_quadratic(family: str, rng: random.Random) -> Equation:
    low, high = _choose_roots(rng)
    if family == "OGE09-K2":
        return Equation(
            _op("+", _op("+", _x2(), _op("*", _n(-(low + high)), _x())), _n(low * high)),
            _n(0),
        )
    if family == "OGE09-K3":
        rational_low, rational_high = _choose_rational_roots(rng)
        denominator_scale = math.lcm(rational_low.denominator, rational_high.denominator) ** 2
        leading = rng.randint(2, 3) * denominator_scale
        linear = -leading * (rational_low + rational_high)
        constant = leading * rational_low * rational_high
        divisor = math.gcd(math.gcd(leading, abs(linear.numerator)), abs(constant.numerator))
        leading //= divisor
        linear_int = linear.numerator // divisor
        constant_int = constant.numerator // divisor
        if leading == 1:
            leading *= 2
            linear_int *= 2
            constant_int *= 2
        return Equation(
            _op(
                "+",
                _op("+", _op("*", _n(leading), _x2()), _op("*", _n(linear_int), _x())),
                _n(constant_int),
            ),
            _n(0),
        )
    if family == "OGE09-K4":
        return Equation(_op("+", _x2(), _op("*", _n(-(low + high)), _x())), _n(-low * high))
    if family == "OGE09-K5":
        first_slope, second_slope = rng.randint(1, 5), rng.randint(1, 5)
        first = _op("+", _op("*", _n(first_slope), _x()), _n(-first_slope * low))
        second = _op("+", _op("*", _n(second_slope), _x()), _n(-second_slope * high))
        return Equation(_op("*", Group(first), Group(second)), _n(0))
    # K6: no linear term; preserve the observed ax²-c form, including simple
    # fractional leading coefficients such as the catalog's 4/3 x² - 48 = 0.
    candidates = k6_parameter_domain()
    value, coefficient = rng.choice(candidates)
    constant = coefficient * value * value
    return Equation(_op("-", _op("*", _n(coefficient), _x2()), _n(constant)), _n(0))


def generate_equation(
    family_id: str, seed: int, generator_version: str = GENERATOR_VERSION
) -> EquationProblem:
    if family_id not in _SOURCES:
        raise KeyError(f"Equation family {family_id!r} is not enabled")
    if not -(2**63) <= seed < 2**63:
        raise ValueError("Seed must fit a signed 64-bit integer")
    rng = random.Random(f"{generator_version}:{family_id}:{seed}")
    equation = (
        _build_linear(family_id, rng)
        if FAMILY_GROUP[family_id] == "linear"
        else _build_quadratic(family_id, rng)
    )
    _check_manual_complexity(equation)
    roots = solve_equation(equation)
    if any(abs(root) > 100 for root in roots):
        raise ValueError("Root magnitude exceeds the task-9 manual-answer limit")
    if len(roots) > 1 and FAMILY_GROUP[family_id] == "linear":
        raise ValueError("Linear generator produced multiple roots")
    answer_target = ROOT_SELECTION.get(family_id, "unique")
    target = roots[-1] if answer_target == "greater" else roots[0]
    answer = POLICY.format(target)
    equation_text = render_equation(equation)
    statement = (
        f"Решите уравнение: {equation_text}"
        if FAMILY_GROUP[family_id] == "linear"
        else (
            f"Найдите {'больший' if answer_target == 'greater' else 'меньший'} корень "
            f"уравнения {equation_text}"
        )
    )
    polynomial = _poly_add(_poly(equation.left), _poly(equation.right), -1)
    c, b, a = polynomial
    if a:
        disc = b * b - 4 * a * c
        solution: tuple[str, ...] = (
            f"Перенесём всё в левую часть: {_fmt(a)}x² + {_fmt(b)}x + {_fmt(c)} = 0.",
            f"Дискриминант D = b² − 4ac = {_format_root(disc)}.",
            f"Действительные корни: {_format_root(roots[0])} и {_format_root(roots[-1])}.",
            (
                f"Требуется {'больший' if answer_target == 'greater' else 'меньший'} корень, "
                f"поэтому ответ: {answer}."
            ),
        )
        hints = (
            "Сначала приведи уравнение к виду ax² + bx + c = 0.",
            (
                "Сравни действительные корни и выбери больший."
                if answer_target == "greater"
                else "Сравни действительные корни и выбери меньший."
            ),
        )
    else:
        solution = (
            f"Перенесём слагаемые с x влево и числа вправо: {_fmt(b)}x = {_fmt(-c)}.",
            f"Разделим обе части на {_fmt(b)}: x = {answer}.",
        )
        hints = (
            "Раскрой скобки и собери слагаемые с x отдельно от чисел.",
            "Раздели свободную часть на коэффициент при x.",
        )
    structure_id = family_id.replace("OGE09-", "oge9.").lower().replace("-", ".")
    problem_id = str(uuid5(NAMESPACE_URL, f"oge9:{generator_version}:{family_id}:{seed}"))
    fingerprint = hashlib.sha256(f"{structure_id}|{equation_text}|{answer}".encode()).hexdigest()
    return EquationProblem(
        problem_id=problem_id,
        seed=seed,
        generator_version=generator_version,
        family_id=family_id,
        reference_structure_id=structure_id,
        reference_ids=_SOURCES[family_id],
        condition=statement,
        equation_text=equation_text,
        target_root=target,
        roots=roots,
        correct_answer=answer,
        answer_policy_id=(
            f"oge9.numeric-{answer_target}-root"
            if answer_target in {"greater", "lesser"}
            else POLICY.policy_id
        ),
        answer_policy_version=POLICY.version,
        answer_target=answer_target,
        hints=hints,
        solution=solution,
        fingerprint=fingerprint,
    )


def _check_manual_complexity(equation: Equation) -> None:
    """Fail closed on oversized visible operands or expanded coefficients."""
    visible_values: list[Fraction] = []
    operations = 0

    def visit(expr: Expr) -> None:
        nonlocal operations
        if isinstance(expr, Number):
            visible_values.append(expr.value)
        elif isinstance(expr, Variable):
            return
        elif isinstance(expr, Group | Unary):
            if isinstance(expr, Unary):
                operations += 1
            visit(expr.expression)
        else:
            operations += 1
            visit(expr.left)
            visit(expr.right)

    visit(equation.left)
    visit(equation.right)
    difference = _poly_add(_poly(equation.left), _poly(equation.right), -1)
    if operations > 18 or any(abs(value) > 500 for value in visible_values):
        raise ValueError("Equation exceeds the visible manual-complexity budget")
    if any(abs(value) > 500 for value in difference):
        raise ValueError("Equation exceeds the intermediate-coefficient limit")


class _RenderedParser:
    """Independent parser/oracle for the exact visible equation string."""

    _token = re.compile(r"x²|x|\d+|[()+\-·/=]")

    def __init__(self, text: str) -> None:
        compact = text.replace(" ", "")
        self.tokens = self._token.findall(compact)
        if "".join(self.tokens) != compact:
            raise ValueError("Displayed expression contains an unsupported character")
        self.index = 0

    def parse(self) -> Poly:
        result = self._sum()
        if self.index != len(self.tokens):
            raise ValueError(f"Unexpected token {self.tokens[self.index]}")
        return result

    def _sum(self) -> Poly:
        value = self._product()
        while self._peek() in {"+", "-"}:
            operator = self._pop()
            value = _oracle_add(value, self._product(), operator == "-")
        return value

    def _product(self) -> Poly:
        value = self._unary()
        while self._peek() in {"·", "/", "(", "x", "x²"}:
            operator = self._pop() if self._peek() in {"·", "/"} else "·"
            right = self._unary()
            if operator == "/":
                if right[1] or right[2] or not right[0]:
                    raise ValueError("Display divides by a non-constant or zero")
                value = tuple(item / right[0] for item in value)  # type: ignore[assignment]
            else:
                value = _oracle_multiply(value, right)
        return value

    def _unary(self) -> Poly:
        if self._peek() == "-":
            self._pop()
            return tuple(-item for item in self._unary())  # type: ignore[return-value]
        if self._peek() == "+":
            self._pop()
            return self._unary()
        token = self._pop()
        if token == "(":
            value = self._sum()
            if self._pop() != ")":
                raise ValueError("Unclosed parenthesis")
            return value
        if token == "x":
            return Fraction(0), Fraction(1), Fraction(0)
        if token == "x²":
            return Fraction(0), Fraction(0), Fraction(1)
        if token.isdigit():
            return Fraction(int(token)), Fraction(0), Fraction(0)
        raise ValueError(f"Unexpected token {token}")

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _pop(self) -> str:
        token = self._peek()
        if token is None:
            raise ValueError("Unexpected end of rendered expression")
        self.index += 1
        return token


def solve_rendered_equation(equation_text: str) -> tuple[Fraction, ...]:
    if equation_text.count("=") != 1:
        raise ValueError("Rendered equation must contain exactly one equality sign")
    left, right = equation_text.split("=", maxsplit=1)
    left_poly, right_poly = _RenderedParser(left).parse(), _RenderedParser(right).parse()
    difference = _oracle_add(left_poly, right_poly, True)
    c, b, a = difference
    if a == 0:
        if b == 0:
            raise ValueError("Rendered linear equation is degenerate")
        return (-c / b,)
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        raise ValueError("Rendered quadratic equation has no exact real roots")
    nroot, droot = math.isqrt(discriminant.numerator), math.isqrt(discriminant.denominator)
    if nroot * nroot != discriminant.numerator or droot * droot != discriminant.denominator:
        raise ValueError("Rendered quadratic equation has irrational roots")
    root = Fraction(nroot, droot)
    return tuple(sorted({(-b - root) / (2 * a), (-b + root) / (2 * a)}))


def validate_rendered_problem(problem: EquationProblem) -> None:
    roots = solve_rendered_equation(problem.equation_text)
    if roots != problem.roots:
        raise ValueError("Rendered equation's full root set differs from the generated model")
    expected_target = roots[-1] if problem.answer_target == "greater" else roots[0]
    if problem.target_root != expected_target or problem.correct_answer != POLICY.format(
        expected_target
    ):
        raise ValueError("Displayed condition and answer policy disagree")
    _validate_visible_shape(problem.family_id, problem.equation_text)
    if len(problem.hints) not in {1, 2} or not problem.solution:
        raise ValueError("Problem must include hints and a worked solution")


def _validate_visible_shape(family_id: str, equation_text: str) -> None:
    left, right = equation_text.split("=", maxsplit=1)

    def variable_count(text: str) -> int:
        return text.count("x") - text.count("x²")

    if family_id == "OGE09-L1" and (
        variable_count(left) != 1 or variable_count(right) or "(" in equation_text
    ):
        raise ValueError("L1 must render one linear term equal to a number")
    if family_id == "OGE09-L2" and (
        not variable_count(left) or not variable_count(right) or "(" in equation_text
    ):
        raise ValueError("L2 must visibly contain x on both sides without grouped terms")
    if family_id == "OGE09-L3" and (
        left.count("(") != 1 or right.count("(") or variable_count(right)
    ):
        raise ValueError("L3 must show one multiplied group and a numeric right side")
    if family_id == "OGE09-L4A" and (
        left.count("(") != 1 or right.count("(") or not variable_count(right)
    ):
        raise ValueError("L4A must show one left group and an ungrouped variable on the right")
    if family_id == "OGE09-L4B" and (left.count("(") < 1 or right.count("(") < 1):
        raise ValueError("L4B must visibly show groups on both sides")
    if family_id == "OGE09-K2" and (
        not left.startswith("x²") or variable_count(left) != 1 or right.strip() != "0"
    ):
        raise ValueError("K2 must be a monic full quadratic equal to zero")
    if family_id == "OGE09-K3" and (
        not re.match(r"(?:[2-9]|[1-9]\d+)x²", left)
        or not variable_count(left)
        or right.strip() != "0"
    ):
        raise ValueError("K3 must be a non-monic full quadratic equal to zero")
    if family_id == "OGE09-K6" and (
        "x²" not in left or variable_count(left) or right.strip() != "0"
    ):
        raise ValueError("K6 must be incomplete with no visible linear term")
