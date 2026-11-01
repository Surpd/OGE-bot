"""Exact, Telegram-independent pilot generators for OGE task 13."""

from __future__ import annotations

import hashlib
import random
import re
import struct
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import AnswerFormat, AnswerPolicy

GENERATOR_VERSION = "0.2.0"
SUPPORTED_GENERATOR_VERSIONS = frozenset({GENERATOR_VERSION})
ENABLED_FAMILIES: tuple[str, ...] = ()
FAMILIES = (
    "OGE13-L01",
    "OGE13-L02",
    "OGE13-Q01",
    "OGE13-Q02",
    "OGE13-Q03",
    "OGE13-Q04",
    "OGE13-S01",
    "OGE13-S02",
    "OGE13-S03",
)
ALL_FAMILIES = FAMILIES
REFERENCE_IDS = {
    "OGE13-L01": ("311409", "338590"),
    "OGE13-L02": ("314612", "107"),
    "OGE13-Q01": ("311310",),
    "OGE13-Q02": ("311309",),
    "OGE13-Q03": ("311311",),
    "OGE13-Q04": ("369736", "369833"),
    "OGE13-S01": ("340580", "311672"),
    "OGE13-S02": ("348461", "340832"),
    "OGE13-S03": ("333109", "341322"),
}
_SYSTEM_TENTHS = tuple(Fraction(i, 10) for i in range(-40, 41))
_SYSTEM_INTERCEPTS = tuple(Fraction(i, 10) for i in range(-20, 21))
_VISUALLY_SEPARATED_BOUNDS = tuple(
    (lower, upper) for lower in _SYSTEM_TENTHS for upper in _SYSTEM_TENTHS if upper - lower >= 1
)
POLICY = AnswerPolicy("oge13.option-number", "1", AnswerFormat.CHOICE_NUMBER)


@dataclass(frozen=True, slots=True)
class Interval:
    left: Fraction | None
    right: Fraction | None
    left_closed: bool = False
    right_closed: bool = False


IntervalSet = tuple[Interval, ...]


def _is_canonical_interval_set(items: IntervalSet) -> bool:
    previous: Interval | None = None
    for item in items:
        if item.left is None and item.left_closed:
            return False
        if item.right is None and item.right_closed:
            return False
        if item.left is not None and item.right is not None:
            if item.left > item.right:
                return False
            if item.left == item.right and not (item.left_closed and item.right_closed):
                return False
        if previous is not None:
            if previous.right is None or item.left is None:
                return False
            if item.left < previous.right:
                return False
            if item.left == previous.right and (previous.right_closed or item.left_closed):
                return False
        previous = item
    return True


@dataclass(frozen=True, slots=True)
class InequalityProblem:
    problem_id: str
    seed: int
    generator_version: str
    family_id: str
    reference_ids: tuple[str, ...]
    condition: str
    solution_set: IntervalSet
    options: tuple[IntervalSet, IntervalSet, IntervalSet, IntervalSet]
    option_texts: tuple[str, str, str, str]
    option_svgs: tuple[str, str, str, str]
    display_order: tuple[int, int, int, int]
    correct_option_number: int
    correct_answer: str
    answer_policy_id: str
    answer_policy_version: str
    condition_audit: str
    special_cases: tuple[str, ...]
    hints: tuple[str, ...]
    solution: tuple[str, ...]
    fingerprint: str

    def accepts(self, answer: str) -> bool:
        return parse_answer(self, answer) == self.correct_option_number

    def to_snapshot(self) -> dict[str, object]:
        return {
            "problem_id": self.problem_id,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "family_id": self.family_id,
            "reference_ids": list(self.reference_ids),
            "condition": self.condition,
            "solution_set": [_interval_snapshot(i) for i in self.solution_set],
            "options": [list(map(_interval_snapshot, option)) for option in self.options],
            "option_texts": list(self.option_texts),
            "option_svgs": list(self.option_svgs),
            "display_order": list(self.display_order),
            "correct_option_number": self.correct_option_number,
            "correct_answer": self.correct_answer,
            "answer_policy_id": self.answer_policy_id,
            "answer_policy_version": self.answer_policy_version,
            "condition_audit": self.condition_audit,
            "special_cases": list(self.special_cases),
            "hints": list(self.hints),
            "solution": list(self.solution),
            "fingerprint": self.fingerprint,
            "content_provenance": "generated_analogue",
            "rendering_version": "svg-line-2",
        }


def _interval_snapshot(item: Interval) -> dict[str, object]:
    return {
        "left": _fraction_text(item.left) if item.left is not None else None,
        "right": _fraction_text(item.right) if item.right is not None else None,
        "left_closed": item.left_closed if item.left is not None else False,
        "right_closed": item.right_closed if item.right is not None else False,
    }


def _fraction_text(value: Fraction) -> str:
    return (
        str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    )


def _parse_displayed_number(raw: str) -> Fraction:
    return Fraction(raw.replace(",", "."))


def _display(value: Fraction | None) -> str:
    if value is None:
        return "∞"
    if value.denominator == 1:
        return str(value.numerator)
    # All generated boundaries have terminating decimal expansions.
    scaled = value.numerator * 100 // value.denominator
    whole, rem = divmod(abs(scaled), 100)
    sign = "-" if scaled < 0 else ""
    frac = f"{rem:02d}".rstrip("0")
    return f"{sign}{whole},{frac}" if frac else f"{sign}{whole}"


def format_set(items: IntervalSet) -> str:
    if not items:
        return "∅"
    parts = []
    for i in items:
        left = "(" if i.left is None or not i.left_closed else "["
        right = ")" if i.right is None or not i.right_closed else "]"
        a = "−∞" if i.left is None else _display(i.left)
        b = "+∞" if i.right is None else _display(i.right)
        parts.append(f"{left}{a};{b}{right}")
    return " ∪ ".join(parts)


def _solution_steps(condition: str, family_id: str, solution: IntervalSet) -> tuple[str, ...]:
    if family_id.startswith("OGE13-L"):
        relations = list(re.finditer(r"<=|>=|<|>", condition))
        if len(relations) != 1:
            raise ValueError("Expected one comparison in a linear inequality")
        relation_match = relations[0]
        relation = relation_match.group()
        left_coefficient, left_constant = _parse_linear_expression(
            condition[: relation_match.start()]
        )
        right_coefficient, right_constant = _parse_linear_expression(
            condition[relation_match.end() :]
        )
        coefficient = left_coefficient - right_coefficient
        if coefficient == 0:
            raise ValueError("Linear explanation requires a nonzero coefficient")
        right_side = right_constant - left_constant
        boundary = right_side / coefficient
        division_relation = relation
        sign_note = "знак сохраняется"
        if coefficient < 0:
            division_relation = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}[
                relation
            ]
            sign_note = "знак меняется"
        if independent_solve(condition, family_id) != solution:
            raise ValueError("Linear solution steps do not match the visible inequality")
        coefficient_text = (
            "x"
            if coefficient == 1
            else "-x"
            if coefficient == -1
            else f"{_display(coefficient)}x"
        )
        divisor_note = "<0" if coefficient < 0 else ">0"
        return (
            f"Исходное неравенство: {condition}.",
            f"Переносим слагаемые: {coefficient_text} {relation} {_display(right_side)}.",
            f"Делим обе части на {_display(coefficient)} ({divisor_note}), {sign_note}: "
            f"x {division_relation} {_display(boundary)}.",
            "Ответ: " + format_set(solution) + ".",
        )
    if family_id.startswith("OGE13-Q"):
        roots, leading_sign, relation, factorization = _quadratic_explanation_data(
            condition, family_id
        )
        left_root, right_root = roots
        strict = len(relation) == 1
        desired_sign = -1 if relation[0] == "<" else 1
        outside_sign = leading_sign
        inside_sign = -leading_sign
        if desired_sign == outside_sign:
            explained_solution = (
                Interval(None, left_root, False, not strict),
                Interval(right_root, None, not strict, False),
            )
        else:
            explained_solution = (Interval(left_root, right_root, not strict, not strict),)
        if explained_solution != solution:
            raise ValueError("Quadratic explanation does not match visible condition")
        sign_regions = (
            f"(−∞;{_display(left_root)}): {'+' if outside_sign > 0 else '−'}",
            f"({_display(left_root)};{_display(right_root)}): "
            f"{'+' if inside_sign > 0 else '−'}",
            f"({_display(right_root)};+∞): {'+' if outside_sign > 0 else '−'}",
        )
        root_inclusion = (
            "не включаем, так как неравенство строгое"
            if strict
            else "включаем, так как знак неравенства нестрогий"
        )
        return (
            f"{factorization}; корни: x = {_display(left_root)} и x = {_display(right_root)}.",
            "Знаки выражения на промежутках: " + "; ".join(sign_regions) + ".",
            f"Для условия {relation} 0 выбираем подходящие промежутки; корни {root_inclusion}.",
            "Ответ: " + format_set(explained_solution) + ".",
        )
    if not family_id.startswith("OGE13-S"):
        raise ValueError(f"Unsupported OGE13 family for solution steps: {family_id}")
    rows = condition.splitlines()
    first, second = (_solve_linear_inequality(row) for row in rows)
    return (
        f"1) {rows[0]} ⇒ {format_set(first)}",
        f"2) {rows[1]} ⇒ {format_set(second)}",
        "Пересечение полученных множеств: " + format_set(solution),
    )


def _quadratic_explanation_data(
    condition: str, family_id: str
) -> tuple[tuple[Fraction, Fraction], int, str, str]:
    number = r"\d+(?:,\d{1,2})?"
    if family_id.endswith("Q01"):
        match = re.fullmatch(rf"x² - ({number})x (<) 0", condition)
        if match is None:
            raise ValueError("Condition audit could not explain Q01")
        coefficient = _parse_displayed_number(match.group(1))
        return (
            (Fraction(0), coefficient),
            1,
            match.group(2),
            f"Раскладываем: x² - {_display(coefficient)}x "
            f"= x(x - {_display(coefficient)})",
        )
    if family_id.endswith("Q02"):
        match = re.fullmatch(rf"x² \+ ({number})x (>=) 0", condition)
        if match is None:
            raise ValueError("Condition audit could not explain Q02")
        coefficient = _parse_displayed_number(match.group(1))
        return (
            (-coefficient, Fraction(0)),
            1,
            match.group(2),
            f"Раскладываем: x² + {_display(coefficient)}x "
            f"= x(x + {_display(coefficient)})",
        )
    if family_id.endswith("Q03"):
        match = re.fullmatch(rf"-x² - ({number})x (<=) 0", condition)
        if match is None:
            raise ValueError("Condition audit could not explain Q03")
        coefficient = _parse_displayed_number(match.group(1))
        return (
            (-coefficient, Fraction(0)),
            -1,
            match.group(2),
            f"Раскладываем: −x² − {_display(coefficient)}x "
            f"= −x(x + {_display(coefficient)})",
        )
    match = re.fullmatch(
        rf"(-?)\(x ([+-]) ({number})\)\(x ([+-]) ({number})\) ([<>]=?) 0",
        condition,
    )
    if match is None:
        raise ValueError("Condition audit could not explain Q04")
    leading, first_sign, first_number, second_sign, second_number, relation = match.groups()
    first_root = _parse_displayed_number(first_number) * (1 if first_sign == "-" else -1)
    second_root = _parse_displayed_number(second_number) * (1 if second_sign == "-" else -1)
    roots = tuple(sorted((first_root, second_root)))
    if roots[0] == roots[1]:
        raise ValueError("Quadratic roots must differ")
    relation_start = re.search(r"[<>]=? 0$", condition)
    if relation_start is None:
        raise ValueError("Condition audit could not locate Q04 comparison")
    factorization = (
        "Выражение уже разложено на множители: "
        + condition[: relation_start.start()].rstrip()
    )
    return cast(tuple[Fraction, Fraction], roots), (-1 if leading else 1), relation, factorization


def parse_answer(problem: InequalityProblem, answer: str) -> int | None:
    """Parse a displayed option number or exact textual interval option."""
    value = answer.strip().replace("−", "-")
    if re.fullmatch(r"[1-4]", value):
        return int(value)
    for idx, text in enumerate(problem.option_texts, 1):
        if value == text.replace("−", "-"):
            return idx
    return None


def _svg(items: IntervalSet, index: int) -> str:
    """Generate a small self-contained number line, using semantic coordinates."""
    low, high, center, scale = -14, 14, 640, 36
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="180" viewBox="0 0 1280 180">',
        '<rect width="1280" height="180" fill="white"/>',
        '<text x="48" y="42" font-size="30" font-family="sans-serif">' + str(index) + "</text>",
        '<path d="M 100 100 H 1180" stroke="#222" stroke-width="3"/>',
        '<path d="M 100 100 l 18 -10 v20 z M 1180 100 l -18 -10 v20 z" fill="#222"/>',
    ]
    if not items:
        parts.append('<text x="610" y="108" font-size="32" font-family="sans-serif">∅</text>')
    for tick in range(low, high + 1, 2):
        x = center + tick * scale
        parts.append(
            f'<path d="M{x} 92v16" stroke="#555"/>'
            f'<text x="{x - 10}" y="142" font-size="22" '
            f'font-family="sans-serif">{tick}</text>'
        )
    for interval in items:
        lx = (
            100
            if interval.left is None
            else max(100, min(1180, center + float(interval.left) * scale))
        )
        rx = (
            1180
            if interval.right is None
            else max(100, min(1180, center + float(interval.right) * scale))
        )
        if interval.left is None:
            parts.append(
                f'<path d="M{lx} 100h{max(0, rx - lx)}" stroke="#1769aa" stroke-width="8"/>'
            )
        elif interval.right is None:
            parts.append(
                f'<path d="M{lx} 100h{max(0, rx - lx)}" stroke="#1769aa" stroke-width="8"/>'
            )
        else:
            parts.append(f'<path d="M{lx} 100H{rx}" stroke="#1769aa" stroke-width="8"/>')
        if interval.left is not None:
            parts.append(
                f'<circle cx="{lx}" cy="100" r="10" '
                f'fill="{"#1769aa" if interval.left_closed else "white"}" '
                'stroke="#1769aa" stroke-width="4"/>'
            )
        if interval.right is not None:
            parts.append(
                f'<circle cx="{rx}" cy="100" r="10" '
                f'fill="{"#1769aa" if interval.right_closed else "white"}" '
                'stroke="#1769aa" stroke-width="4"/>'
            )
        if interval.left is not None:
            parts.append(
                f'<text x="{lx - 24}" y="165" font-size="20" '
                f'font-family="sans-serif">{_display(interval.left)}</text>'
            )
        if interval.right is not None:
            parts.append(
                f'<text x="{rx - 24}" y="165" font-size="20" '
                f'font-family="sans-serif">{_display(interval.right)}</text>'
            )
    return "".join(parts) + "</svg>"


def _intersect(a: Interval, b: Interval) -> IntervalSet:
    if a.left is None:
        left, lc = b.left, b.left_closed
    elif b.left is None:
        left, lc = a.left, a.left_closed
    elif a.left > b.left:
        left, lc = a.left, a.left_closed
    elif b.left > a.left:
        left, lc = b.left, b.left_closed
    else:
        left, lc = a.left, a.left_closed and b.left_closed
    if a.right is None:
        right, rc = b.right, b.right_closed
    elif b.right is None:
        right, rc = a.right, a.right_closed
    elif a.right < b.right:
        right, rc = a.right, a.right_closed
    elif b.right < a.right:
        right, rc = b.right, b.right_closed
    else:
        right, rc = a.right, a.right_closed and b.right_closed
    if left is not None and right is not None:
        if left > right or (left == right and not (lc and rc)):
            return ()
    return (Interval(left, right, lc, rc),)


_LINEAR_TERM = re.compile(r"([+-]?)(?:(\d+(?:,\d{1,2})?)?x|(\d+(?:,\d{1,2})?))")


def _parse_linear_expression(expression: str) -> tuple[Fraction, Fraction]:
    compact = expression.replace(" ", "")
    if not compact:
        raise ValueError("Linear expression is empty")
    coefficient = Fraction(0)
    constant = Fraction(0)
    cursor = 0
    while cursor < len(compact):
        match = _LINEAR_TERM.match(compact, cursor)
        if match is None:
            raise ValueError("Linear expression contains an unsupported term")
        sign, raw_coefficient, raw_constant = match.groups()
        multiplier = Fraction(-1 if sign == "-" else 1)
        if raw_constant is None:
            coefficient += multiplier * (
                Fraction(1) if not raw_coefficient else _parse_displayed_number(raw_coefficient)
            )
        else:
            constant += multiplier * _parse_displayed_number(raw_constant)
        cursor = match.end()
    return coefficient, constant


def _solve_linear_inequality(row: str) -> IntervalSet:
    relations = list(re.finditer(r"<=|>=|<|>", row))
    if len(relations) != 1:
        raise ValueError("Expected one comparison in a linear inequality")
    relation_match = relations[0]
    relation = relation_match.group()
    left_coefficient, left_constant = _parse_linear_expression(row[: relation_match.start()])
    right_coefficient, right_constant = _parse_linear_expression(row[relation_match.end() :])
    coefficient = left_coefficient - right_coefficient
    constant = left_constant - right_constant

    if coefficient == 0:
        is_true = {
            "<": constant < 0,
            "<=": constant <= 0,
            ">": constant > 0,
            ">=": constant >= 0,
        }[relation]
        return (Interval(None, None),) if is_true else ()

    boundary = -constant / coefficient
    less = relation[0] == "<"
    if coefficient < 0:
        less = not less
    strict = len(relation) == 1
    if less:
        return (Interval(None, boundary, False, not strict),)
    return (Interval(boundary, None, not strict, False),)


def independent_solve(condition: str, family_id: str) -> IntervalSet:
    """Reconstructs visible expressions from text and solves with exact fractions."""
    if family_id.startswith("OGE13-L"):
        m = re.fullmatch(
            r"(-?(?:\d+)?)x ([+-]) (\d+) ([<>]=?) (-?(?:\d+)?)x ([+-]) (\d+)", condition
        )
        if not m:
            raise ValueError("Condition audit could not parse linear expression")
        a, op1, b, rel, c, op2, d = m.groups()
        a = "-1" if a == "-" else "1" if a == "" else a
        c = "-1" if c == "-" else "1" if c == "" else c
        coef = int(a) - int(c)
        const = (int(b) if op1 == "+" else -int(b)) - (int(d) if op2 == "+" else -int(d))
        if coef == 0:
            raise ValueError("Degenerate linear inequality")
        root = Fraction(-const, coef)
        less = rel[0] == "<"
        strict = len(rel) == 1
        if coef < 0:
            less = not less
        return (
            (Interval(None, root, False, not strict),)
            if less
            else (Interval(root, None, not strict, False),)
        )
    if family_id.startswith("OGE13-Q"):
        if family_id.endswith("Q01"):
            m = re.fullmatch(r"x² - (\d+(?:,\d{1,2})?)x < 0", condition)
            if not m:
                raise ValueError("Condition audit could not parse Q01 polynomial")
            root = _parse_displayed_number(m.group(1))
            return (Interval(Fraction(0), root),)
        if family_id.endswith("Q02"):
            m = re.fullmatch(r"x² \+ (\d+(?:,\d{1,2})?)x >= 0", condition)
            if not m:
                raise ValueError("Condition audit could not parse Q02 polynomial")
            root = _parse_displayed_number(m.group(1))
            return (Interval(None, -root, False, True), Interval(Fraction(0), None, True, False))
        if family_id.endswith("Q03"):
            m = re.fullmatch(r"-x² - (\d+(?:,\d{1,2})?)x <= 0", condition)
            if not m:
                raise ValueError("Condition audit could not parse Q03 polynomial")
            root = _parse_displayed_number(m.group(1))
            return (Interval(None, -root, False, True), Interval(Fraction(0), None, True, False))
        number = r"\d+(?:,\d{1,2})?"
        m = re.fullmatch(
            rf"([+-]?\d*)\(x ([+-]) ({number})\)\(x ([+-]) ({number})\) ([<>]=?) 0", condition
        )
        if not m:
            raise ValueError("Condition audit could not parse factored quadratic")
        leading, s1, n1, s2, n2, rel = m.groups()
        aa = -1 if leading in ("-", "−") else int(leading or "1")
        roots = sorted(
            (
                _parse_displayed_number(n1) * (-1 if s1 == "+" else 1),
                _parse_displayed_number(n2) * (-1 if s2 == "+" else 1),
            )
        )
        if roots[0] == roots[1]:
            raise ValueError("Quadratic roots must differ")
        outside = (rel[0] == ">") == (aa > 0)
        closed = len(rel) == 2
        x, y = roots
        if outside:
            return (Interval(None, x, False, closed), Interval(y, None, closed, False))
        return (Interval(x, y, closed, closed),)
    if family_id.startswith("OGE13-S"):
        rows = condition.split("\n")
        if len(rows) != 2:
            raise ValueError("System must contain exactly two visible rows")
        first = _solve_linear_inequality(rows[0])
        second = _solve_linear_inequality(rows[1])
        if not first or not second:
            return ()
        return _intersect(first[0], second[0])
    raise ValueError("Unsupported family")


def _condition(family: str, rng: random.Random) -> tuple[str, tuple[str, ...]]:
    if family.startswith("OGE13-L"):
        root = Fraction(rng.randint(-8, 8))
        # Make varied coefficients while preserving an exact visible root.
        a, c = rng.choice(((1, -1), (2, 1), (-1, 1)))
        b = rng.randint(-6, 6)
        d = int(Fraction(a - c) * root + b)
        rel = (
            rng.choice(("<", ">", "<=", ">=")) if family.endswith("L02") else rng.choice(("<", ">"))
        )
        opb = "+" if b >= 0 else "-"
        opd = "+" if d >= 0 else "-"
        term_a = f"{'-' if a == -1 else ''}{'' if abs(a) == 1 else abs(a)}x"
        term_c = f"{'-' if c == -1 else ''}{'' if abs(c) == 1 else abs(c)}x"
        cond = f"{term_a} {opb} {abs(b)} {rel} {term_c} {opd} {abs(d)}"
        return cond, ()
    if family.startswith("OGE13-Q"):
        if family.endswith("Q01"):
            k = Fraction(rng.randint(1, 1200), 100)
            return f"x² - {_display(k)}x < 0", ()
        elif family.endswith("Q02"):
            k = Fraction(rng.randint(1, 1200), 100)
            return f"x² + {_display(k)}x >= 0", ()
        elif family.endswith("Q03"):
            k = Fraction(rng.randint(1, 1200), 100)
            return f"-x² - {_display(k)}x <= 0", ("negative_leading_coefficient",)
        else:
            values = [Fraction(i, 2) for i in range(-24, 25)]
            pairs = [(left, right) for left in values for right in values if right - left >= 1]
            aa, bb = rng.choice(pairs)
            pair = (aa, bb)
            rel = rng.choice((">", "<"))
            lead = 1
        x, y = pair
        # Labeled as x (±n), with nonzero integer roots accepted by all pilot families.
        s1 = "-" if x >= 0 else "+"
        n1 = _display(abs(x))
        s2 = "-" if y >= 0 else "+"
        n2 = _display(abs(y))
        # Explicit zero is rendered x, not x - 0.
        left = f"(x {s1} {n1})"
        right = f"(x {s2} {n2})"
        cond = f"{'-' if lead < 0 else ''}{left}{right} {rel} 0"
        return cond, ("negative_leading_coefficient",) if lead < 0 else ()
    intercepts = _SYSTEM_INTERCEPTS
    if family.endswith("S01"):
        lower, upper = rng.choice(_VISUALLY_SEPARATED_BOUNDS)
        upper_coefficient, lower_coefficient = rng.randint(1, 4), rng.randint(1, 4)
        upper_intercept = rng.choice(intercepts)
        lower_intercept = rng.choice(intercepts)
        upper_right = upper_coefficient * upper + upper_intercept
        lower_right = lower_coefficient * lower + lower_intercept
        return (
            f"{_format_ax_plus_b(upper_coefficient, upper_intercept)} <= {_display(upper_right)}\n"
            f"{_format_ax_plus_b(lower_coefficient, lower_intercept)} >= {_display(lower_right)}",
            ("source_algebra_preserved", "coefficient_transfer", "decimal_exact"),
        )
    if family.endswith("S02"):
        first, second = rng.sample(_SYSTEM_TENTHS, 2)
        first_coefficient, second_coefficient = rng.randint(1, 4), rng.randint(1, 4)
        first_intercept = rng.choice(intercepts)
        second_intercept = rng.choice(intercepts)
        first_right = first_coefficient * first + first_intercept
        second_right = second_coefficient * second + second_intercept
        return (
            f"{_format_ax_plus_b(first_coefficient, first_intercept)} >= {_display(first_right)}\n"
            f"{_format_ax_plus_b(second_coefficient, second_intercept)} "
            f">= {_display(second_right)}",
            ("source_algebra_preserved", "coefficient_transfer", "decimal_exact"),
        )
    if family.endswith("S03"):
        lower, upper = rng.choice(_VISUALLY_SEPARATED_BOUNDS)
        negative_coefficient = rng.randint(1, 4)
        upper_intercept = rng.choice(intercepts)
        upper_constant = negative_coefficient * upper + upper_intercept
        left = (
            f"{_display(upper_constant)} - "
            f"{'x' if negative_coefficient == 1 else f'{negative_coefficient}x'}"
            if upper_constant != 0
            else ("-x" if negative_coefficient == 1 else f"-{negative_coefficient}x")
        )
        return (
            f"x > {_display(lower)}\n{left} > {_display(upper_intercept)}",
            ("source_algebra_preserved", "negative_coefficient", "strict_boundaries"),
        )
    raise ValueError(f"Unsupported OGE13 family: {family}")


def _format_ax_plus_b(coefficient: int, constant: Fraction) -> str:
    if coefficient == 1:
        variable = "x"
    elif coefficient == -1:
        variable = "-x"
    else:
        variable = f"{coefficient}x"
    if constant > 0:
        return f"{variable} + {_display(constant)}"
    if constant < 0:
        return f"{variable} - {_display(abs(constant))}"
    return variable


def _distractors(solution: IntervalSet, rng: random.Random) -> tuple[IntervalSet, ...]:
    if not _is_canonical_interval_set(solution):
        raise ValueError("Correct answer must be a canonical interval set")
    candidates: list[IntervalSet] = []
    if not solution:
        candidates.extend(
            IntervalSet((Interval(Fraction(point), Fraction(point), True, True),))
            for point in (-3, 0, 4)
        )
    for item in solution:
        candidates += [
            (
                Interval(
                    item.left,
                    item.right,
                    not item.left_closed if item.left is not None else False,
                    item.right_closed,
                ),
            ),
            (
                Interval(
                    item.left,
                    item.right,
                    item.left_closed,
                    not item.right_closed if item.right is not None else False,
                ),
            ),
        ]
        for edge in (item.left, item.right):
            if edge is not None:
                shifted = edge + 1 if edge < 10 else edge - 1
                candidates.append(
                    (
                        Interval(
                            shifted if edge == item.left else item.left,
                            shifted if edge == item.right else item.right,
                            item.left_closed,
                            item.right_closed,
                        ),
                    )
                )
    if solution and solution[0].left is None:
        candidates.append((Interval(solution[0].right, None, False, False),))
    elif solution:
        candidates.append((Interval(None, solution[-1].left, False, False),))
    else:
        candidates.append(())
    unique: list[IntervalSet] = []
    for candidate in candidates:
        if (
            _is_canonical_interval_set(candidate)
            and candidate != solution
            and candidate not in unique
        ):
            unique.append(candidate)
    if len(unique) < 3:
        unique.extend(
            [
                (Interval(Fraction(i), Fraction(i + 2), False, False),)
                for i in range(-12, 12)
                if (Interval(Fraction(i), Fraction(i + 2), False, False),) != solution
                and (Interval(Fraction(i), Fraction(i + 2), False, False),) not in unique
            ]
        )
    if len(unique) < 3:
        raise RuntimeError("Could not construct three valid, distinct distractors")
    rng.shuffle(unique)
    return (solution, *unique[:3])


def generate(
    family_id: str, seed: int, generator_version: str = GENERATOR_VERSION
) -> InequalityProblem:
    if family_id not in FAMILIES:
        raise ValueError(f"Unsupported OGE13 family: {family_id}")
    if generator_version not in SUPPORTED_GENERATOR_VERSIONS:
        raise ValueError(f"Unsupported OGE13 generator version: {generator_version}")
    rng = random.Random(f"oge13:{family_id}:{seed}:{generator_version}")
    condition, special = _condition(family_id, rng)
    solution = independent_solve(condition, family_id)
    semantic_options = _distractors(solution, rng)
    order = list(range(4))
    rng.shuffle(order)
    ordered = cast(
        tuple[IntervalSet, IntervalSet, IntervalSet, IntervalSet],
        tuple(semantic_options[i] for i in order),
    )
    texts = cast(tuple[str, str, str, str], tuple(format_set(o) for o in ordered))
    svg = cast(tuple[str, str, str, str], tuple(_svg(o, i + 1) for i, o in enumerate(ordered)))
    correct = order.index(0) + 1
    display_order = (order[0], order[1], order[2], order[3])
    audit = independent_solve(condition, family_id)
    if (
        audit != solution
        or not _is_canonical_interval_set(solution)
        or any(not _is_canonical_interval_set(option) for option in ordered)
        or len(set(ordered)) != 4
        or ordered[correct - 1] != solution
    ):
        raise RuntimeError("OGE13 generated condition/options failed semantic audit")
    fp = hashlib.sha256(f"{family_id}|{condition}".encode()).hexdigest()
    problem_id = str(uuid5(NAMESPACE_URL, f"oge13:{family_id}:{seed}:{generator_version}"))
    flags = list(special)
    if any(
        (item.left is not None and item.left_closed)
        or (item.right is not None and item.right_closed)
        for item in solution
    ):
        flags.append("included_boundary")
    if not solution:
        flags.append("empty_set")
    if len(solution) == 2:
        flags.append("two_rays")
    return InequalityProblem(
        problem_id,
        seed,
        generator_version,
        family_id,
        REFERENCE_IDS[family_id],
        condition,
        solution,
        ordered,
        texts,
        svg,
        display_order,
        correct,
        str(correct),
        POLICY.policy_id,
        POLICY.version,
        "Rendered condition independently parsed and solved with exact Fraction arithmetic.",
        tuple(flags),
        ("Решите неравенство; учтите знак сравнения и граничные точки.",),
        _solution_steps(condition, family_id, solution),
        fp,
    )


def validate(problem: InequalityProblem) -> bool:
    """Run the independent visible-condition and option uniqueness audit."""
    try:
        solved = independent_solve(problem.condition, problem.family_id)
        expected_solution_steps = _solution_steps(problem.condition, problem.family_id, solved)
    except (ValueError, ZeroDivisionError):
        return False
    if (
        solved != problem.solution_set
        or problem.solution != expected_solution_steps
        or not _is_canonical_interval_set(problem.solution_set)
        or len(problem.options) != 4
        or type(problem.correct_option_number) is not int
        or not 1 <= problem.correct_option_number <= 4
    ):
        return False
    if (
        len(set(problem.options)) != 4
        or any(not _is_canonical_interval_set(option) for option in problem.options)
        or problem.options[problem.correct_option_number - 1] != solved
    ):
        return False
    if sorted(problem.display_order) != [0, 1, 2, 3]:
        return False
    if problem.display_order[problem.correct_option_number - 1] != 0:
        return False
    if problem.correct_answer != str(problem.correct_option_number):
        return False
    return (
        tuple(format_set(option) for option in problem.options) == problem.option_texts
        and tuple(_svg(option, index + 1) for index, option in enumerate(problem.options))
        == problem.option_svgs
    )


def _snapshot_fraction(value: object) -> Fraction | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Interval snapshot endpoint must be a string or null")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("Interval snapshot endpoint is not an exact fraction") from exc


def _snapshot_interval_set(value: object) -> IntervalSet:
    if not isinstance(value, list):
        raise ValueError("Interval snapshot must be a list")
    intervals: list[Interval] = []
    for raw_interval in value:
        if not isinstance(raw_interval, Mapping):
            raise ValueError("Interval snapshot entry must be an object")
        left_closed, right_closed = (
            raw_interval.get("left_closed"),
            raw_interval.get("right_closed"),
        )
        if type(left_closed) is not bool or type(right_closed) is not bool:
            raise ValueError("Interval snapshot closure flags must be booleans")
        intervals.append(
            Interval(
                _snapshot_fraction(raw_interval.get("left")),
                _snapshot_fraction(raw_interval.get("right")),
                left_closed,
                right_closed,
            )
        )
    result = tuple(intervals)
    if not _is_canonical_interval_set(result):
        raise ValueError("Interval snapshot is not canonical")
    return result


def _snapshot_options(snapshot: Mapping[str, object]) -> tuple[IntervalSet, ...]:
    version = snapshot.get("generator_version")
    if not isinstance(version, str) or version not in SUPPORTED_GENERATOR_VERSIONS:
        raise ValueError(f"Unsupported OGE13 generator version in snapshot: {version}")
    family_id = snapshot.get("family_id")
    if not isinstance(family_id, str) or family_id not in FAMILIES:
        raise ValueError("Unsupported OGE13 family in snapshot")
    raw_options = snapshot.get("options")
    if not isinstance(raw_options, list) or len(raw_options) != 4:
        raise ValueError("Snapshot must preserve all four answer options")
    options = tuple(_snapshot_interval_set(option) for option in raw_options)
    if len(set(options)) != 4:
        raise ValueError("Snapshot answer options must be mathematically distinct")
    correct_number = snapshot.get("correct_option_number")
    if type(correct_number) is not int or not 1 <= correct_number <= 4:
        raise ValueError("Snapshot correct option number must be between 1 and 4")
    solution = _snapshot_interval_set(snapshot.get("solution_set"))
    if options[correct_number - 1] != solution:
        raise ValueError("Snapshot correct number does not identify its saved solution")
    option_texts = snapshot.get("option_texts")
    if (
        not isinstance(option_texts, list)
        or len(option_texts) != 4
        or tuple(option_texts) != tuple(format_set(option) for option in options)
        or snapshot.get("correct_answer") != str(correct_number)
    ):
        raise ValueError("Snapshot text options do not match saved mathematical options")
    if (
        snapshot.get("answer_policy_id") != POLICY.policy_id
        or snapshot.get("answer_policy_version") != POLICY.version
    ):
        raise ValueError("Snapshot answer policy is unsupported")
    condition = snapshot.get("condition")
    if not isinstance(condition, str) or independent_solve(condition, family_id) != solution:
        raise ValueError("Snapshot condition does not match its saved solution")
    raw_svgs = snapshot.get("option_svgs")
    expected_svgs = tuple(_svg(option, index + 1) for index, option in enumerate(options))
    if not isinstance(raw_svgs, list) or tuple(raw_svgs) != expected_svgs:
        raise ValueError("Snapshot graph options do not match saved mathematical options")
    return options


def validate_snapshot(snapshot: Mapping[str, object]) -> bool:
    try:
        _snapshot_options(snapshot)
    except (ValueError, TypeError, ZeroDivisionError):
        return False
    return True


def render_option_sheet_snapshot_png(snapshot: Mapping[str, object]) -> bytes:
    """Render the four saved options without regenerating a persisted task."""
    return _render_option_sets_png(_snapshot_options(snapshot))


def render_option_sheet_png(problem: InequalityProblem) -> bytes:
    """Render four verified number-line options to a deterministic 1280×1120 RGB PNG."""
    if not validate(problem):
        raise ValueError("Cannot render an invalid OGE13 problem")
    return _render_option_sets_png(problem.options)


def _render_option_sets_png(options: tuple[IntervalSet, ...]) -> bytes:
    """Render already validated four interval sets to a deterministic PNG."""
    if len(options) != 4 or any(not _is_canonical_interval_set(option) for option in options):
        raise ValueError("PNG renderer needs four canonical interval sets")
    width, height = 1280, 1120
    pixels = bytearray([255, 255, 255] * width * height)
    ink, blue, gray = (34, 34, 34), (23, 105, 170), (110, 110, 110)

    def dot(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            at = (y * width + x) * 3
            pixels[at : at + 3] = bytes(color)

    def line(
        x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int], thick: int = 2
    ) -> None:
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for n in range(steps + 1):
            x = round(x1 + (x2 - x1) * n / steps)
            y = round(y1 + (y2 - y1) * n / steps)
            for dx in range(-thick, thick + 1):
                for dy in range(-thick, thick + 1):
                    dot(x + dx, y + dy, color)

    def ring(cx: int, cy: int, filled: bool) -> None:
        for dy in range(-12, 13):
            for dx in range(-12, 13):
                d = dx * dx + dy * dy
                if d <= 144 and (filled or d >= 72):
                    dot(cx + dx, cy + dy, blue)
                elif d <= 144 and not filled:
                    dot(cx + dx, cy + dy, (255, 255, 255))

    # Numeric ticks use a compact deterministic 3×5 bitmap font.
    glyphs = {
        "0": (7, 5, 5, 5, 7),
        "1": (2, 6, 2, 2, 7),
        "2": (7, 1, 7, 4, 7),
        "3": (7, 1, 7, 1, 7),
        "4": (5, 5, 7, 1, 1),
        "5": (7, 4, 7, 1, 7),
        "6": (7, 4, 7, 5, 7),
        "7": (7, 1, 2, 2, 2),
        "8": (7, 5, 7, 5, 7),
        "9": (7, 5, 7, 1, 7),
        "-": (0, 0, 7, 0, 0),
        ",": (0, 0, 0, 2, 4),
    }

    def label(value: str, x: int, y: int) -> None:
        cell = 8
        start = x - len(value) * (3 * cell + cell) // 2
        for ci, char in enumerate(value):
            for row, bits in enumerate(glyphs.get(char, ())):
                for col in range(3):
                    if bits & (1 << (2 - col)):
                        for sy in range(cell):
                            for sx in range(cell):
                                dot(
                                    start + ci * (4 * cell) + col * cell + sx,
                                    y + row * cell + sy,
                                    gray,
                                )

    for index, option in enumerate(options):
        cy = 185 + index * 250
        # Draw axis with arrowheads and identical scale in every panel.
        line(100, cy, 1180, cy, ink, 1)
        line(100, cy, 115, cy - 8, ink, 1)
        line(100, cy, 115, cy + 8, ink, 1)
        line(1180, cy, 1165, cy - 8, ink, 1)
        line(1180, cy, 1165, cy + 8, ink, 1)
        label(str(index + 1), 44, cy - 12)
        for tick in range(-12, 13, 4):
            x = 640 + tick * 36
            line(x, cy - 7, x, cy + 7, gray, 1)
            label(str(tick), x, cy + 16)
        if not option:
            ring(640, cy, False)
            line(632, cy - 8, 648, cy + 8, blue, 2)
        endpoints: list[tuple[int, str, bool]] = []
        for interval in option:
            leftx = (
                100
                if interval.left is None
                else max(100, min(1180, round(640 + float(interval.left) * 36)))
            )
            rightx = (
                1180
                if interval.right is None
                else max(100, min(1180, round(640 + float(interval.right) * 36)))
            )
            line(leftx, cy, rightx, cy, blue, 4)
            # Show explicit continuation arrows for unbounded rays.
            if interval.left is None:
                line(100, cy, 112, cy - 7, blue, 3)
                line(100, cy, 112, cy + 7, blue, 3)
            if interval.right is None:
                line(1180, cy, 1168, cy - 7, blue, 3)
                line(1180, cy, 1168, cy + 7, blue, 3)
            if interval.left is not None:
                ring(leftx, cy, interval.left_closed)
                endpoints.append((leftx, _display(interval.left), interval.left_closed))
            if interval.right is not None:
                ring(rightx, cy, interval.right_closed)
                endpoints.append((rightx, _display(interval.right), interval.right_closed))
        # Keep close boundary labels readable by moving colliding labels to
        # separate lanes above the same number line.
        lane_right_edges: list[int] = []
        for endpoint_x, endpoint_label, _ in sorted(endpoints):
            label_width = len(endpoint_label) * 32
            left_edge = endpoint_x - label_width // 2
            lane = next(
                (
                    candidate
                    for candidate, right_edge in enumerate(lane_right_edges)
                    if right_edge + 8 <= left_edge
                ),
                len(lane_right_edges),
            )
            if lane == len(lane_right_edges):
                lane_right_edges.append(endpoint_x + label_width // 2)
            else:
                lane_right_edges[lane] = endpoint_x + label_width // 2
            label(endpoint_label, endpoint_x, cy - 44 - lane * 40)
    raw = b"".join(
        b"\0" + bytes(pixels[row * width * 3 : (row + 1) * width * 3]) for row in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
