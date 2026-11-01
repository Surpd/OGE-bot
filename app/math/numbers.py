"""Deterministic OGE-7 text families with exact rational arithmetic."""

from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import AnswerFormat, AnswerPolicy

GENERATOR_VERSION = "0.2.0"
FAMILIES = tuple(f"OGE07-C{i:02}" for i in range(1, 7))
ENABLED_FAMILIES: tuple[str, ...] = ()
POLICY = AnswerPolicy("oge07.single-choice", "1", AnswerFormat.SINGLE_NUMBER)
SOURCES: dict[str, tuple[str, ...]] = {
    "OGE07-C01": ("317132", "353058"),
    "OGE07-C02": ("317223", "337311", "352483", "425018"),
    "OGE07-C03": ("337389", "406570"),
    "OGE07-C04": ("369728",),
    "OGE07-C05": ("311420",),
    "OGE07-C06": ("461837",),
}
FAMILY_STATUS = {f: "implemented_disabled_pending_source_review" for f in FAMILIES}
_NUM = r"(?:−|-)?\d+(?:,\d+)?(?:/\d+)?"


def _parse_number(raw: str) -> Fraction:
    raw = raw.strip().replace("−", "-").replace(",", ".")
    if "/" in raw:
        a, b = raw.split("/", 1)
        return Fraction(int(a), int(b))
    return Fraction(raw)


def _decimal(value: Fraction) -> str:
    """Render the finite decimals used by the generators without float math."""
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        return f"{value.numerator}/{value.denominator}"
    scale = max(twos, fives)
    multiplier = 2 ** (scale - twos) * 5 ** (scale - fives)
    n = value.numerator * multiplier
    sign = "−" if n < 0 else ""
    digits = str(abs(n)).rjust(scale + 1, "0")
    if not scale:
        return sign + digits
    return sign + digits[:-scale] + "," + digits[-scale:]


@dataclass(frozen=True, slots=True)
class Problem:
    problem_id: str
    family_id: str
    seed: int
    generator_version: str
    reference_ids: tuple[str, ...]
    condition: str
    options: tuple[str, str, str, str]
    correct_option_index: int
    hints: tuple[str, ...]
    solution: tuple[str, ...]
    fingerprint: str

    def to_snapshot(self) -> dict[str, object]:
        return {
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "reference_ids": list(self.reference_ids),
            "content_provenance": "generated_analogue",
            "condition": self.condition,
            "options": list(self.options),
            "correct_option_index": self.correct_option_index,
            "correct_answer": str(self.correct_option_index),
            "answer_policy_id": POLICY.policy_id,
            "answer_policy_version": POLICY.version,
            "hints": list(self.hints),
            "solution": list(self.solution),
            "fingerprint": self.fingerprint,
        }


def _build(
    family: str,
    seed: int,
    condition: str,
    options: list[str],
    correct: int,
    hints: tuple[str, ...],
    solution: tuple[str, ...],
) -> Problem:
    options = options[:]
    correct_text = options[correct]
    random.Random(f"oge07-options:{family}:{seed}").shuffle(options)
    options_tuple = cast(tuple[str, str, str, str], tuple(options))
    index = options.index(correct_text) + 1
    fingerprint = hashlib.sha256(
        (family + "|" + condition + "|" + "|".join(sorted(options))).encode()
    ).hexdigest()
    pid = str(uuid5(NAMESPACE_URL, f"oge07:{GENERATOR_VERSION}:{family}:{seed}"))
    return Problem(
        pid,
        family,
        seed,
        GENERATOR_VERSION,
        SOURCES[family],
        condition,
        options_tuple,
        index,
        hints,
        solution,
        fingerprint,
    )


def generate(family_id: str, seed: int, generator_version: str = GENERATOR_VERSION) -> Problem:
    if generator_version != GENERATOR_VERSION or family_id not in FAMILIES:
        raise ValueError("Unsupported OGE07 family or generator version")
    rng = random.Random(f"oge07:{family_id}:{seed}:{generator_version}")
    if family_id == "OGE07-C01":
        q = rng.randrange(2, 101)
        p = rng.randrange(1, q)
        x = Fraction(p, q)
        lo = Fraction(x * 10 // 1, 10)
        if lo == x:
            lo -= Fraction(1, 10)
        bounds = [
            (lo, lo + Fraction(1, 10)),
            (lo - Fraction(1, 5), lo - Fraction(1, 10)),
            (lo + Fraction(1, 5), lo + Fraction(3, 10)),
            (lo - Fraction(2, 5), lo - Fraction(3, 10)),
        ]
        opts = [f"[{_decimal(a)}; {_decimal(b)}]" for a, b in bounds]
        return _build(
            family_id,
            seed,
            f"Какой из указанных десятичных отрезков содержит число {p}/{q}?",
            opts,
            0,
            (
                "Сравните дробь с границами отрезков.",
                f"{_decimal(lo)} < {p}/{q} < {_decimal(lo + Fraction(1, 10))}.",
            ),
            (
                f"{_decimal(lo)} < {p}/{q} < {_decimal(lo + Fraction(1, 10))}.",
                "Ответ — единственный содержащий число отрезок.",
            ),
        )
    if family_id == "OGE07-C02":
        n = rng.choice([v for v in range(5, 10_000) if math.isqrt(v) ** 2 != v])
        k = math.isqrt(n)
        opts = [
            f"между {k} и {k + 1}",
            f"между {k - 1} и {k}",
            f"между {k + 1} и {k + 2}",
            f"между {k - 2} и {k - 1}",
        ]
        return _build(
            family_id,
            seed,
            f"Между какими двумя последовательными целыми числами заключено число √{n}?",
            opts,
            0,
            (
                "Сравните n с квадратами последовательных целых.",
                f"{k}²={k * k} < {n} < {(k + 1) ** 2}={(k + 1) ** 2}.",
            ),
            (
                f"{k * k} < {n} < {(k + 1) ** 2}, поэтому {k} < √{n} < {k + 1}.",
                "Ответ: первый промежуток.",
            ),
        )
    if family_id == "OGE07-C03":
        a = rng.randrange(1, 8)
        b = a + rng.randrange(2, 6)
        target = rng.randrange(a * a, b * b + 1)
        other = [n for n in range(1, 100) if n != target and not (a * a <= n <= b * b)]
        vals = [target, *rng.sample(other, 3)]
        rng.shuffle(vals)
        idx = vals.index(target)
        opts = [f"√{n}" for n in vals]
        return _build(
            family_id,
            seed,
            f"Какое из чисел принадлежит отрезку [{a}; {b}]?",
            opts,
            idx,
            ("Для неотрицательного √n сравните n с квадратами концов.", f"{a * a} ≤ n ≤ {b * b}."),
            (
                f"Только подкоренное выражение {target} удовлетворяет {a * a} ≤ n ≤ {b * b}.",
                f"Ответ: √{target}.",
            ),
        )
    if family_id == "OGE07-C04":
        a = rng.randrange(-4, 4)
        b = a + rng.randrange(2, 6)
        den = rng.choice((2, 3, 4, 5, 10))
        p = rng.randrange(a * den, b * den + 1)
        x = Fraction(p, den)
        others = [
            Fraction(n, den)
            for n in range(a * den - 3, b * den + 4)
            if Fraction(n, den) != x and not (a <= Fraction(n, den) <= b)
        ]
        vals_c04 = [x, *rng.sample(others, 3)]
        rng.shuffle(vals_c04)
        idx = vals_c04.index(x)
        opts = [_decimal(v) for v in vals_c04]
        return _build(
            family_id,
            seed,
            f"Какое из чисел принадлежит отрезку [{a}; {b}]?",
            opts,
            idx,
            ("Сравните каждое число с концами отрезка.", f"{a} ≤ число ≤ {b}."),
            (f"Только {_decimal(x)} принадлежит [{a}; {b}].", f"Ответ: {_decimal(x)}."),
        )
    if family_id == "OGE07-C05":
        left = rng.randrange(-10, 8)
        width = rng.randrange(3, 8)
        right = left + width
        target_c05 = Fraction(left * 10 + rng.randrange(1, width * 10), 10)
        vals_c05: list[Fraction] = [
            target_c05,
            target_c05 + width + 1,
            target_c05 - width - 1,
            Fraction(left),
            Fraction(right),
        ]
        vals_c05 = list(dict.fromkeys(vals_c05))
        vals_c05.remove(target_c05)
        vals_c05 = rng.sample(vals_c05, 3)
        vals_c05.append(target_c05)
        rng.shuffle(vals_c05)
        idx = vals_c05.index(target_c05)
        opts = [_decimal(v) for v in vals_c05]
        return _build(
            family_id,
            seed,
            f"Какое число лежит между {left} и {right}?",
            opts,
            idx,
            (
                "Для открытого промежутка границы не включаются.",
                f"Проверьте строгое условие {left} < x < {right}.",
            ),
            (
                f"Только {_decimal(target_c05)} удовлетворяет {left} < x < {right}.",
                f"Ответ: {_decimal(target_c05)}.",
            ),
        )
    # C06: signed rational and its unique pair of consecutive integer bounds.
    den = rng.randrange(2, 12)
    p = rng.choice([v for v in range(-100, 101) if v % den])
    x = Fraction(p, den)
    floor = x.numerator // x.denominator
    opts = [
        f"между {floor} и {floor + 1}",
        f"между {floor - 2} и {floor - 1}",
        f"между {floor + 1} и {floor + 2}",
        f"между {floor - 1} и {floor}",
    ]
    return _build(
        family_id,
        seed,
        f"Между какими двумя последовательными целыми числами заключена дробь {p}/{den}?",
        opts,
        0,
        ("Используйте целую часть с учётом знака дроби.", f"{floor} < {p}/{den} < {floor + 1}."),
        (f"{floor} < {p}/{den} < {floor + 1}.", "Ответ: первый промежуток."),
    )


def audit_condition(
    family: str, condition: str, options: tuple[str, ...] | list[str], answer: int
) -> bool:
    """Parse only displayed text/options and independently establish one answer."""
    if family not in FAMILIES or len(options) != 4 or answer not in range(1, 5):
        return False
    if len(set(options)) != 4 or any(not option.strip() for option in options):
        return False
    try:
        if family == "OGE07-C01":
            match = re.fullmatch(
                r"Какой из указанных десятичных отрезков содержит число (\d+)/(\d+)\?", condition
            )
            if not match:
                return False
            value = Fraction(int(match[1]), int(match[2]))
            truths = []
            for option in options:
                bounds = re.fullmatch(r"\[([^;]+);\s*([^]]+)\]", option)
                if not bounds:
                    return False
                lo, hi = map(_parse_number, bounds.groups())
                truths.append(lo <= value <= hi)
        elif family == "OGE07-C02":
            match = re.fullmatch(
                r"Между какими двумя последовательными целыми числами заключено число √(\d+)\?",
                condition,
            )
            if not match:
                return False
            n = int(match[1])
            k = math.isqrt(n)
            if k * k == n:
                return False
            truths = [o == f"между {k} и {k + 1}" for o in options]
        elif family == "OGE07-C03":
            match = re.fullmatch(
                r"Какое из чисел принадлежит отрезку \[(\d+); (\d+)\]\?", condition
            )
            if not match:
                return False
            lo_c03, hi_c03 = map(int, match.groups())
            if lo_c03 < 0 or lo_c03 >= hi_c03:
                return False
            values = [re.fullmatch(r"√(\d+)", o) for o in options]
            if any(v is None for v in values):
                return False
            radicands = [int(v[1]) for v in values if v is not None]
            truths = [lo_c03 * lo_c03 <= n <= hi_c03 * hi_c03 for n in radicands]
        elif family == "OGE07-C04":
            match = re.fullmatch(
                r"Какое из чисел принадлежит отрезку \[(-?\d+); (-?\d+)\]\?", condition
            )
            if not match:
                return False
            lo_c04, hi_c04 = map(int, match.groups())
            if lo_c04 >= hi_c04:
                return False
            values_c04 = [_parse_number(o) for o in options]
            truths = [lo_c04 <= x <= hi_c04 for x in values_c04]
        elif family == "OGE07-C05":
            match = re.fullmatch(r"Какое число лежит между (-?\d+) и (-?\d+)\?", condition)
            if not match:
                return False
            lo_c05, hi_c05 = map(int, match.groups())
            if lo_c05 >= hi_c05:
                return False
            values_c05 = [_parse_number(o) for o in options]
            truths = [lo_c05 < x < hi_c05 for x in values_c05]
        else:  # OGE07-C06
            match = re.fullmatch(
                r"Между какими двумя последовательными целыми числами "
                r"заключена дробь (-?\d+)/(\d+)\?",
                condition,
            )
            if not match:
                return False
            x = Fraction(int(match[1]), int(match[2]))
            k = x.numerator // x.denominator
            if x == k:
                return False
            truths = [o == f"между {k} и {k + 1}" for o in options]
        return sum(truths) == 1 and truths[answer - 1]
    except (ValueError, ZeroDivisionError):
        return False
