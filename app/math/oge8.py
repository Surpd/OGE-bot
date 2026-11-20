"""Exact, deterministic generators and an independent visible-text oracle for OGE task 8.
"""

from __future__ import annotations

import ast
import hashlib
import random
import re
from dataclasses import dataclass
from fractions import Fraction
from math import isqrt
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import AnswerFormat, AnswerPolicy

GENERATOR_VERSION = "0.1.0"
MAX_CANDIDATES = 32
SEEDS_PER_FAMILY = 4
MAX_GENERATION_ATTEMPTS = 64

R02 = "OGE08-R02"
R03 = "OGE08-R03"
R01 = "OGE08-R01"
R05 = "OGE08-R05"
R06 = "OGE08-R06"
R04 = "OGE08-R04"
R08 = "OGE08-R08"
ENABLED_FAMILIES = (R01, R02, R03, R04, R05, R06, R08)
ALL_FAMILIES = tuple(f"OGE08-R{i:02d}" for i in range(1, 18))
REFERENCE_IDS = {
    R02: ("355406",), R03: ("FIPI-2027-8",),
    R01: ("460990",), R04: ("137285",), R05: ("406280",),
    R06: ("369495",), R08: ("400942",),
}

POLICY = AnswerPolicy(
    "oge8.numeric-short", "1", AnswerFormat.SINGLE_NUMBER,
    max_decimal_places=0, max_absolute_value=10_000,
)
POLICIES_BY_SNAPSHOT = {
    (family, POLICY.policy_id, POLICY.version): POLICY for family in ALL_FAMILIES
}


@dataclass(frozen=True, slots=True)
class _Surd:
    """Exact sum of rational multiples of square-free square roots."""

    terms: tuple[tuple[int, Fraction], ...]

    @classmethod
    def from_terms(cls, terms: dict[int, Fraction]) -> _Surd:
        return cls(tuple(sorted((key, value) for key, value in terms.items() if value)))

    @classmethod
    def rational(cls, value: Fraction | int) -> _Surd:
        return cls.from_terms({1: Fraction(value)})

    def as_dict(self) -> dict[int, Fraction]:
        return dict(self.terms)

    def __add__(self, other: _Surd) -> _Surd:
        result = self.as_dict()
        for key, value in other.terms:
            result[key] = result.get(key, Fraction()) + value
        return _Surd.from_terms(result)

    def __neg__(self) -> _Surd:
        return _Surd.from_terms({key: -value for key, value in self.terms})

    def __sub__(self, other: _Surd) -> _Surd:
        return self + -other

    def __mul__(self, other: _Surd) -> _Surd:
        result: dict[int, Fraction] = {}
        for left_rad, left_coefficient in self.terms:
            for right_rad, right_coefficient in other.terms:
                coefficient, radicand = _simplify_sqrt(left_rad * right_rad)
                result[radicand] = result.get(radicand, Fraction()) + (
                    left_coefficient * right_coefficient * coefficient
                )
        return _Surd.from_terms(result)

    def __truediv__(self, other: _Surd) -> _Surd:
        if not other.terms:
            raise ZeroDivisionError
        if len(other.terms) == 1:
            radicand, coefficient = other.terms[0]
            if radicand == 1:
                return self * _Surd.rational(1 / coefficient)
            reciprocal = _Surd.from_terms({radicand: 1 / (coefficient * radicand)})
            return self * reciprocal
        raise ValueError("Oracle division requires a rational or single-root denominator")

    def __pow__(self, exponent: int) -> _Surd:
        if abs(exponent) > 12:
            raise ValueError("Exponent exceeds the visible-expression limit")
        if exponent < 0:
            return _Surd.rational(1) / (self ** -exponent)
        result = _Surd.rational(1)
        for _ in range(exponent):
            result = result * self
        return result

    def rational_value(self) -> Fraction:
        if not self.terms:
            return Fraction()
        if len(self.terms) != 1 or self.terms[0][0] != 1:
            raise ValueError("Displayed expression does not simplify to a rational answer")
        return self.terms[0][1]


def _simplify_sqrt(value: int) -> tuple[int, int]:
    if value < 0:
        raise ValueError("Negative radicand")
    if value == 0:
        return 0, 1
    outside = 1
    inside = value
    factor = 2
    while factor * factor <= inside:
        square = factor * factor
        while inside % square == 0:
            outside *= factor
            inside //= square
        factor += 1
    return outside, inside


def _oracle_text(text: str) -> Fraction:
    """Parse and evaluate only the mathematical text shown to the learner."""
    match = re.fullmatch(r"Вычислите: (.+)", text.strip())
    if match is None:
        raise ValueError("Unexpected task-8 condition format")
    expression = match.group(1).replace("√", "sqrt").replace("·", "*").replace("^", "**")
    tree = ast.parse(expression, mode="eval")

    def visit(node: ast.AST) -> _Surd:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return _Surd.rational(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -visit(node.operand)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sqrt"
        ):
            if len(node.args) != 1 or node.keywords:
                raise ValueError("Invalid square-root syntax")
            radicand = visit(node.args[0]).rational_value()
            if radicand.denominator != 1:
                raise ValueError("Only integer radicands are supported")
            outside, inside = _simplify_sqrt(radicand.numerator)
            return _Surd.from_terms({inside: Fraction(outside)})
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                exponent = right.rational_value()
                if exponent.denominator != 1:
                    raise ValueError("Non-integer exponent")
                return left ** exponent.numerator
        raise ValueError(f"Unsupported visible syntax: {type(node).__name__}")

    return visit(tree.body).rational_value()


def _pretty(expression: str) -> str:
    return expression.replace("sqrt", "√").replace("**", "^").replace("*", "·")


@dataclass(frozen=True, slots=True)
class Oge8Problem:
    problem_id: str
    seed: int
    generator_version: str
    family_id: str
    reference_structure_id: str
    reference_ids: tuple[str, ...]
    subtype: str
    expression: str
    condition: str
    answer_policy: AnswerPolicy
    exact_value: Fraction
    correct_answer: str
    hints: tuple[str, ...]
    solution: tuple[str, ...]
    fingerprint: str
    parameters: tuple[int, ...]

    def to_snapshot(self) -> dict[str, object]:
        return {
            "problem_id": self.problem_id,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "family_id": self.family_id,
            "reference_structure_id": self.reference_structure_id,
            "reference_ids": list(self.reference_ids),
            "subtype": self.subtype,
            "expression": self.expression,
            "expression_ast": ast.dump(
                ast.parse(
                    self.expression.replace("√", "sqrt").replace("·", "*").replace("^", "**"),
                    mode="eval",
                ),
                include_attributes=False,
            ),
            "content_provenance": "generated_analogue",
            "condition": self.condition,
            "answer_policy_id": self.answer_policy.policy_id,
            "answer_policy_version": self.answer_policy.version,
            "exact_numerator": self.exact_value.numerator,
            "exact_denominator": self.exact_value.denominator,
            "correct_answer": self.correct_answer,
            "hints": list(self.hints),
            "solution": list(self.solution),
            "fingerprint": self.fingerprint,
            "parameters": list(self.parameters),
        }


def _build(
    family_id: str, seed: int, expression: str, parameters: tuple[int, ...],
    hints: tuple[str, ...], solution: tuple[str, ...], subtype: str,
    expected_value: Fraction,
) -> Oge8Problem:
    expression = _pretty(expression)
    condition = f"Вычислите: {expression}"
    exact = _oracle_text(condition)
    if exact != expected_value:
        raise ArithmeticError("Visible-text oracle differs from the generator's independent model")
    answer = POLICY.format(exact)
    fingerprint = hashlib.sha256(
        f"{family_id}|{POLICY.policy_id}|{condition}|{answer}".encode()
    ).hexdigest()
    return Oge8Problem(
        str(uuid5(NAMESPACE_URL, f"oge8:{GENERATOR_VERSION}:{family_id}:{seed}")),
        seed, GENERATOR_VERSION, family_id, family_id, REFERENCE_IDS[family_id],
        subtype, expression, condition, POLICY, exact, answer, hints, solution,
        fingerprint, parameters,
    )


def generate(family_id: str, seed: int, generator_version: str = GENERATOR_VERSION) -> Oge8Problem:
    if generator_version != GENERATOR_VERSION:
        raise ValueError(f"Unsupported OGE-8 generator version: {generator_version}")
    rng = random.Random(f"oge8:{family_id}:{seed}")
    if family_id == R01:
        base = rng.randint(2, 9)
        negative = rng.randint(1, 5)
        denominator = rng.randint(1, 5)
        exponent = rng.randint(1, min(4, 12 - negative - denominator))
        positive = exponent + negative + denominator
        return _build(
            R01, seed, f"{base}**(-{negative})*{base}**{positive}/{base}**{denominator}",
            (base, negative, positive, denominator),
            ("В числителе сложите показатели степеней с одинаковым основанием.",
             "При делении вычтите из полученного показателя показатель знаменателя."),
            (f"Показатель произведения: −{negative} + {positive} = {positive - negative}.",
             f"При делении: {positive - negative} − {denominator} = {exponent}.",
             f"Получаем {base}^{exponent} = {base**exponent}."),
            "multiply_and_divide_powers", Fraction(base**exponent),
        )
    if family_id == R02:
        base = rng.randint(2, 8)
        inner, outer = rng.randint(2, 4), rng.randint(2, 4)
        exponent = rng.randint(max(1, inner * outer - 12), min(4, inner * outer - 1))
        negative = inner * outer - exponent
        return _build(
            R02, seed, f"{base}**(-{negative})*({base}**{inner})**{outer}",
            (base, negative, inner, outer),
            ("При возведении степени в степень перемножьте показатели.",
             "При умножении степеней одного основания сложите их показатели."),
            (f"Показатель второй степени: {inner} · {outer} = {inner*outer}.",
             f"Общий показатель: −{negative} + {inner*outer} = {exponent}.",
             f"Ответ: {base}^{exponent} = {base**exponent}."),
            "nested_power_product", Fraction(base**exponent),
        )
    if family_id == R03:
        a, b = rng.sample(range(2, 11), 2)
        common, extra = rng.randint(2, 7), rng.randint(1, 3)
        return _build(
            R03, seed, f"{a}**{common+extra}*{b}**{common}/{a*b}**{common}",
            (a, b, common, extra),
            ("Разложите основание степени в знаменателе на множители.",
             "Сократите степени каждого основания отдельно."),
            (f"Знаменатель: ({a}·{b})^{common} = {a}^{common}·{b}^{common}.",
             f"Сокращаем {b}^{common}; остаётся {a}^({common+extra} − {common}).",
             f"Получаем {a}^{extra} = {a**extra}."),
            "composite_denominator", Fraction(a**extra),
        )
    if family_id == R05:
        factor = rng.randint(2, 12)
        left, right = sorted(rng.sample(range(2, 10), 2))
        a, b, c = left * factor, right * factor, left * right
        return _build(
            R05, seed, f"sqrt({a})*sqrt({b})/sqrt({c})", (a, b, c),
            ("Произведение положительных корней можно записать под одним корнем.",
             "Внесите знаменатель под корень и сократите дробь."),
            (f"Получаем √(({a}·{b})/{c}).",
             f"Под корнем {a*b}/{c} = {factor**2}.",
             f"Квадратный корень из {factor**2} равен {factor}."),
            "radical_product_over_root", Fraction(factor),
        )
    if family_id == R06:
        n = rng.choice([x for x in range(2, 81) if isqrt(x)**2 != x])
        k = rng.randint(1, 8)
        return _build(
            R06, seed, f"(sqrt({n})-{k})*(sqrt({n})+{k})", (n, k),
            ("У множителей одинаковые слагаемые, но разные знаки.",
             "Примените формулу (a − b)(a + b) = a² − b²."),
            (f"Получаем (√{n})² − {k}².",
             f"Вычитаем квадраты: {n} − {k*k} = {n-k*k}."),
            "conjugate_radicals", Fraction(n-k*k),
        )
    if family_id == R04:
        left_rad = rng.randint(2, 12)
        right_rad = rng.randint(2, min(12, 100 // left_rad))
        left_coeff, right_coeff = rng.randint(1, 5), rng.randint(1, 5)
        expression = (
            f"{left_coeff}*sqrt({left_rad})*{right_coeff}*sqrt({right_rad})"
            f"*sqrt({left_rad * right_rad})"
        )
        return _build(
            R04, seed, expression, (left_rad, right_rad, left_coeff, right_coeff),
            (
                "Сгруппируйте корни и используйте √a·√b = √(ab) для неотрицательных a и b.",
                (
                    f"Под корнем получится квадрат числа {left_rad * right_rad}: "
                    f"√({left_rad * right_rad}²) = {left_rad * right_rad}."
                ),
            ),
            (
                f"{left_coeff}·{right_coeff}·√({left_rad}·{right_rad}·{left_rad * right_rad})"
                f" = {left_coeff * right_coeff}·{left_rad * right_rad}"
                f" = {left_coeff * right_coeff * left_rad * right_rad}.",
                f"Ответ: {left_coeff * right_coeff * left_rad * right_rad}.",
            ),
            "multiply_three_radicals",
            Fraction(left_coeff * right_coeff * left_rad * right_rad),
        )
    if family_id == R08:
        radicand = rng.randint(2, 80)
        while isqrt(radicand) ** 2 == radicand:
            radicand = rng.randint(2, 80)
        coefficient = rng.randint(1, 7)
        expression = f"(sqrt({radicand})+{coefficient})**2-2*{coefficient}*sqrt({radicand})"
        answer = radicand + coefficient**2
        return _build(
            R08, seed, expression, (radicand, coefficient),
            (
                "Раскройте квадрат суммы; смешанный член сократится с последним слагаемым.",
                f"После сокращения останется {radicand} + {coefficient}².",
            ),
            (f"n + {coefficient}² = {radicand} + {coefficient**2}.", f"Ответ: {answer}."),
            "binomial_square_cancel_radical",
            Fraction(answer),
        )
    raise ValueError(f"OGE-8 family is not enabled: {family_id}")


def verify_problem(problem: Oge8Problem) -> bool:
    if problem.family_id not in ENABLED_FAMILIES:
        return False
    try:
        exact = _oracle_text(problem.condition)
        return (
            exact == problem.exact_value
            and problem.condition == f"Вычислите: {problem.expression}"
            and POLICY.format(exact) == problem.correct_answer
            and problem.fingerprint == hashlib.sha256(
                (
                    f"{problem.family_id}|{POLICY.policy_id}|{problem.condition}|"
                    f"{problem.correct_answer}"
                ).encode()
            ).hexdigest()
        )
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError):
        return False
