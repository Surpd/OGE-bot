"""Versioned text-only geometry №15; separate from practical tasks №1–5."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from fractions import Fraction
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import NUMERIC_SHORT_ANSWER
from app.math.oge15_oracle import answer

POLICY = NUMERIC_SHORT_ANSWER
GENERATOR_VERSION = "oge15-triangles-1"
FAMILIES = tuple(f"OGE15-F{n:02}" for n in (1, 3, 11, 14, 19, 20))
ENABLED_FAMILIES: tuple[str, ...] = ()
SOURCES = dict(
    zip(FAMILIES, ("348885", "356190", "349690", "350527", "348554", "169853"), strict=True)
)


def decimal(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator // 2}.5"


def parameters_for_seed(family: str, seed: int) -> tuple[int, ...]:
    rng = random.Random(f"{GENERATOR_VERSION}:{family}:{seed}")
    if family == FAMILIES[0]:
        a = rng.randint(20, 120)
        return a, rng.randint(20, min(120, 160 - a))
    if family == FAMILIES[1]:
        return (rng.randint(20, 160),)
    if family == FAMILIES[2]:
        ac = rng.randint(10, 80)
        ab = rng.randint(max(8, ac // 2), ac + 15)
        bc = rng.randint(abs(ac - ab) + 4, ac + ab - 4)
        return ab, bc, ac
    if family == FAMILIES[3]:
        a, b, _ = rng.choice(((3, 4, 5), (5, 12, 13), (8, 15, 17), (7, 24, 25)))
        k = rng.randint(1, 5)
        return tuple(sorted((a * k, b * k)))
    if family in FAMILIES[4:]:
        return rng.randint(3, 30), rng.randint(3, 25)
    raise ValueError("Unknown triangle family")


def content(family: str, p: tuple[int, ...]) -> tuple[str, list[str], list[str], Fraction]:
    a = p[0]
    b = p[1] if len(p) > 1 else 0
    if family == FAMILIES[0]:
        result = Fraction(180 - a - b)
        return (
            f"Два угла треугольника равны {a}° и {b}°. Найдите третий угол. Ответ "
            f"дайте в градусах.",
            ["Сумма внутренних углов треугольника равна 180°."],
            [f"Третий угол равен 180° − {a}° − {b}° = {decimal(result)}°."],
            result,
        )
    if family == FAMILIES[1]:
        result = Fraction(180 - a)
        return (
            f"В треугольнике ABC угол C равен {a}°. Найдите внешний угол при вершине "
            f"C. Ответ дайте в градусах.",
            ["Внешний и внутренний углы при одной вершине смежные."],
            [f"Внешний угол равен 180° − {a}° = {decimal(result)}°."],
            result,
        )
    if family == FAMILIES[2]:
        c = p[2]
        result = Fraction(c, 2)
        return (
            f"Точки M и N — середины сторон AB и BC треугольника ABC. AB = {a}, BC = "
            f"{b}, AC = {c}. Найдите MN.",
            ["Отрезок, соединяющий середины двух сторон треугольника, — средняя линия."],
            [
                "Средняя линия параллельна третьей стороне и равна её половине.",
                f"MN = {c} / 2 = {decimal(result).replace('.', ',')}.",
            ],
            result,
        )
    if family == FAMILIES[3]:
        from math import isqrt

        result = Fraction(isqrt(a * a + b * b))
        return (
            f"Катеты прямоугольного треугольника равны {a} и {b}. Найдите гипотенузу.",
            ["По теореме Пифагора квадрат гипотенузы равен сумме квадратов катетов."],
            [f"c² = {a}² + {b}² = {a * a + b * b}.", f"c = {decimal(result)}."],
            result,
        )
    if family in FAMILIES[4:]:
        result = Fraction(a * b, 2)
        condition = (
            f"Катеты прямоугольного треугольника равны {a} и {b}. Найдите его площадь."
            if family == FAMILIES[4]
            else f"Сторона треугольника равна {a}, а проведённая к ней высота равна {b}. "
            f"Найдите площадь треугольника."
        )
        return (
            condition,
            ["Площадь треугольника равна половине произведения основания на высоту."],
            [f"S = {a} · {b} / 2 = {decimal(result).replace('.', ',')}."],
            result,
        )
    raise ValueError("Unknown triangle family")


@dataclass(frozen=True, slots=True)
class TriangleProblem:
    serialized: str

    def to_snapshot(self) -> dict[str, Any]:
        return dict(json.loads(self.serialized))

    @property
    def fingerprint(self) -> str:
        return str(self.to_snapshot()["fingerprint"])


def generate(
    family_id: str, seed: int, generator_version: str = GENERATOR_VERSION
) -> TriangleProblem:
    if generator_version != GENERATOR_VERSION or family_id not in FAMILIES:
        raise ValueError("Unknown generator contract")
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("Invalid seed")
    p = parameters_for_seed(family_id, seed)
    condition, hints, solution, result = content(family_id, p)
    if result != answer(family_id, p):
        raise ValueError("Independent oracle mismatch")
    normalized = sorted(p) if family_id in {FAMILIES[0], FAMILIES[4]} else p
    fingerprint = hashlib.sha256(json.dumps([family_id, normalized]).encode()).hexdigest()
    snapshot = {
        "problem_id": str(uuid5(NAMESPACE_URL, f"{family_id}:{seed}:{generator_version}")),
        "family_id": family_id,
        "generator_version": generator_version,
        "seed": seed,
        "parameters": list(p),
        "condition": condition,
        "hints": hints,
        "solution": solution,
        "correct_answer": decimal(result),
        "answer_policy_id": POLICY.policy_id,
        "answer_policy_version": POLICY.version,
        "fingerprint": fingerprint,
        "attempt_index": 0,
        "provenance": {
            "task_id": SOURCES[family_id],
            "url": f"https://math-oge.sdamgia.ru/problem?id={SOURCES[family_id]}",
            "kind": "generated_analogue",
        },
    }
    return TriangleProblem(json.dumps(snapshot, sort_keys=True, ensure_ascii=False))


def from_snapshot(snapshot: dict[str, Any]) -> TriangleProblem:
    try:
        if len(json.dumps(snapshot)) > 16000:
            raise ValueError("Snapshot too large")
        expected = generate(snapshot["family_id"], snapshot["seed"], snapshot["generator_version"])
        # Queue metadata is transport-only; every mathematical field is immutable.
        if any(snapshot.get(key) != value for key, value in expected.to_snapshot().items()):
            raise ValueError("Corrupted triangle snapshot")
        return expected
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid triangle snapshot") from exc
