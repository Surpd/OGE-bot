"""Closed OGE18 M01/M02 implementation; immutable self-contained snapshots."""

from __future__ import annotations

import base64
import hashlib
import json
import random
from dataclasses import dataclass
from fractions import Fraction
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import NUMERIC_SHORT_ANSWER
from app.math.oge18_oracle import answer
from app.math.oge18_render import VERSION as RENDERER_VERSION
from app.math.oge18_render import Point, audit, render

POLICY = NUMERIC_SHORT_ANSWER
GENERATOR_VERSION = "oge18-grid-1"
FAMILIES = ("OGE18-M01", "OGE18-M02")
ENABLED_FAMILIES: tuple[str, ...] = ()
SOURCES = {FAMILIES[0]: "348480", FAMILIES[1]: "348638"}
CONDITIONS = {
    FAMILIES[0]: "На клетчатой сетке со стороной клетки 1 изображён треугольник ABC. "
    "Найдите длину его средней линии, параллельной AC.",
    FAMILIES[1]: "На клетчатой сетке со стороной клетки 1 изображена трапеция. "
    "Найдите длину её средней линии.",
}


def decimal(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator // 2}.5"


def fingerprint(family: str, points: tuple[Point, ...]) -> str:
    a, b, c = points[:3]
    length = points[-1][0] - a[0]
    offset, height = b[0] - a[0], b[1] - a[1]
    upper = 0 if len(points) == 3 else c[0] - b[0]
    # Remove translations and reflection; labels and color never count as novelty.
    offset = min(offset, length - upper - offset)
    identity = f"{family}:{length}:{upper}:{offset}:{height}:midline"
    return hashlib.sha256(identity.encode()).hexdigest()


def teaching(family: str, points: tuple[Point, ...]) -> tuple[list[str], list[str]]:
    if family == FAMILIES[0]:
        base = points[2][0] - points[0][0]
        return (
            [
                "Посчитайте клетки вдоль стороны AC.",
                "Средняя линия треугольника равна половине параллельной стороны.",
            ],
            [
                f"Сторона AC занимает {base} клеток.",
                f"Длина средней линии: {base} : 2 = {base // 2}.",
            ],
        )
    lower, upper = points[3][0] - points[0][0], points[2][0] - points[1][0]
    result = decimal(Fraction(lower + upper, 2)).replace(".", ",")
    return (
        [
            "Найдите две параллельные стороны и посчитайте клетки вдоль них.",
            "Средняя линия трапеции равна полусумме оснований.",
        ],
        [
            f"Основания занимают {lower} и {upper} клеток.",
            f"Длина средней линии: ({lower} + {upper}) : 2 = {result}.",
        ],
    )


@dataclass(frozen=True, slots=True)
class Oge18Problem:
    serialized: str

    def to_snapshot(self) -> dict[str, Any]:
        return dict(json.loads(self.serialized))

    @property
    def png_bytes(self) -> bytes:
        return base64.b64decode(self.to_snapshot()["png_base64"], validate=True)

    @property
    def fingerprint(self) -> str:
        return str(self.to_snapshot()["fingerprint"])


def _pack(snapshot: dict[str, Any]) -> Oge18Problem:
    return Oge18Problem(json.dumps(snapshot, sort_keys=True, ensure_ascii=False))


def generate(family_id: str, seed: int, generator_version: str = GENERATOR_VERSION) -> Oge18Problem:
    if family_id not in FAMILIES or generator_version != GENERATOR_VERSION:
        raise ValueError("Unknown family or generator version")
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("Seed must be an unsigned signed-bigint-compatible integer")
    rng = random.Random(seed)
    x, y = rng.randint(2, 3), rng.randint(2, 3)
    points: tuple[Point, ...]
    if family_id == FAMILIES[0]:
        base = rng.choice((4, 6, 8, 10, 12, 14))
        offset, height = rng.randint(1, base - 1), rng.randint(3, 11)
        points = ((x, y), (x + offset, y + height), (x + base, y))
        result = Fraction(base, 2)
    else:
        lower = rng.randint(6, 12)
        upper = rng.randint(2, lower - 2)
        offset, height = rng.randint(1, lower - upper - 1), rng.randint(3, 8)
        points = (
            (x, y),
            (x + offset, y + height),
            (x + offset + upper, y + height),
            (x + lower, y),
        )
        result = Fraction(lower + upper, 2)
    if answer(points) != result:
        raise ValueError("Coordinate oracle mismatch")
    png = render(points, family_id == FAMILIES[0])
    hints, solution = teaching(family_id, points)
    source = SOURCES[family_id]
    snapshot = {
        "problem_id": str(uuid5(NAMESPACE_URL, f"{family_id}:{seed}:{generator_version}")),
        "family_id": family_id,
        "seed": seed,
        "generator_version": generator_version,
        "renderer_version": RENDERER_VERSION,
        "points": [list(p) for p in points],
        "grid": {"cell_size": 1, "columns": 20, "rows": 17, "step_px": 32},
        "condition": CONDITIONS[family_id],
        "correct_answer": decimal(result),
        "answer_policy_id": POLICY.policy_id,
        "answer_policy_version": POLICY.version,
        "provenance": {
            "task_id": source,
            "url": f"https://math-oge.sdamgia.ru/problem?id={source}",
            "kind": "generated_analogue",
        },
        "hints": hints,
        "solution": solution,
        "fingerprint": fingerprint(family_id, points),
        "attempt_index": 0,
        "png_base64": base64.b64encode(png).decode(),
        "image_sha256": hashlib.sha256(png).hexdigest(),
    }
    return from_snapshot(snapshot)


def from_snapshot(snapshot: dict[str, Any]) -> Oge18Problem:
    try:
        if len(json.dumps(snapshot)) > 250_000:
            raise ValueError("Snapshot too large")
        family = snapshot["family_id"]
        if (
            family not in FAMILIES
            or snapshot["generator_version"] != GENERATOR_VERSION
            or snapshot["renderer_version"] != RENDERER_VERSION
        ):
            raise ValueError("Unknown snapshot version")
        seed = snapshot["seed"]
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError("Invalid seed")
        identity = str(uuid5(NAMESPACE_URL, f"{family}:{seed}:{GENERATOR_VERSION}"))
        if snapshot["problem_id"] != identity:
            raise ValueError("Invalid identity")
        raw_points = snapshot["points"]
        if not isinstance(raw_points, list) or any(len(p) != 2 for p in raw_points):
            raise ValueError("Invalid points")
        points = tuple((p[0], p[1]) for p in raw_points)
        if len(points) != (3 if family == FAMILIES[0] else 4):
            raise ValueError("Wrong vertex count")
        result = answer(points)
        hints, solution = teaching(family, points)
        if (
            snapshot["condition"] != CONDITIONS[family]
            or snapshot["hints"] != hints
            or snapshot["solution"] != solution
            or snapshot["correct_answer"] != decimal(result)
            or snapshot["fingerprint"] != fingerprint(family, points)
            or snapshot["answer_policy_id"] != POLICY.policy_id
            or snapshot["answer_policy_version"] != POLICY.version
            or snapshot["attempt_index"] != 0
            or snapshot["grid"] != {"cell_size": 1, "columns": 20, "rows": 17, "step_px": 32}
        ):
            raise ValueError("Corrupted mathematical snapshot")
        source = SOURCES[family]
        if snapshot["provenance"] != {
            "task_id": source,
            "url": f"https://math-oge.sdamgia.ru/problem?id={source}",
            "kind": "generated_analogue",
        }:
            raise ValueError("Invalid provenance")
        png = base64.b64decode(snapshot["png_base64"], validate=True)
        if len(png) > 150_000 or hashlib.sha256(png).hexdigest() != snapshot["image_sha256"]:
            raise ValueError("Invalid PNG hash or size")
        audit(png, points, family == FAMILIES[0])
        return _pack(snapshot)
    except (KeyError, TypeError, IndexError, OverflowError) as exc:
        raise ValueError("Corrupted snapshot") from exc
