"""Closed OGE18 M01/M02 implementation; immutable self-contained snapshots."""

from __future__ import annotations

import base64
import hashlib
import json
import random
from dataclasses import dataclass
from fractions import Fraction
from math import isqrt
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import NUMERIC_SHORT_ANSWER
from app.math.oge18_oracle import answer, answer_family
from app.math.oge18_render import VERSION as RENDERER_VERSION
from app.math.oge18_render import VERSION_V2, Point, audit, audit_family, render, render_family

POLICY = NUMERIC_SHORT_ANSWER
GENERATOR_VERSION = "oge18-grid-1"
FAMILIES = ("OGE18-M01", "OGE18-M02")
NEW_FAMILIES = ("OGE18-D05", "OGE18-L02", "OGE18-A01", "OGE18-A03", "OGE18-A04", "OGE18-A05")
GENERATOR_VERSION_V2 = "oge18-grid-2"
LEARNER_CONTENT_VERSION = 2
ENABLED_FAMILIES: tuple[str, ...] = ()
SOURCES = {FAMILIES[0]: "348480", FAMILIES[1]: "348638"}
SOURCES.update(
    dict(
        zip(NEW_FAMILIES, ("461848", "348467", "348613", "348403", "348499", "356974"), strict=True)
    )
)
CONDITIONS = {
    FAMILIES[0]: "На клетчатой сетке со стороной клетки 1 изображён треугольник ABC. "
    "Найдите длину его средней линии, параллельной AC.",
    FAMILIES[1]: "На клетчатой сетке со стороной клетки 1 изображена трапеция. "
    "Найдите длину её средней линии.",
}
CONDITIONS.update(
    {
        "OGE18-D05": (
            "На клетчатой бумаге с размером клетки 1 × 1 изображены две точки. "
            "Найдите расстояние между ними."
        ),
        "OGE18-L02": (
            "На клетчатой бумаге с размером клетки 1 × 1 изображён прямоугольный "
            "треугольник. Найдите длину его большего катета."
        ),
        "OGE18-A01": (
            "На клетчатой бумаге с размером клетки 1 × 1 изображена трапеция. Найдите её площадь."
        ),
        "OGE18-A03": (
            "На клетчатой бумаге с размером клетки 1 × 1 изображён треугольник. "
            "Найдите его площадь."
        ),
        "OGE18-A04": (
            "На клетчатой бумаге с размером клетки 1 × 1 изображён параллелограмм. "
            "Найдите его площадь."
        ),
        "OGE18-A05": (
            "На клетчатой бумаге с размером клетки 1 × 1 изображён ромб. "
            "Найдите площадь этого ромба."
        ),
    }
)
CONDITIONS_V1 = dict(CONDITIONS)
CONDITIONS_V1.update(
    {
        "OGE18-L02": (
            "На клетчатой бумаге с размером клетки 1 × 1 изображён прямоугольный "
            "треугольник. Найдите больший катет."
        ),
        "OGE18-A01": (
            "На клетчатой бумаге с размером клетки 1 × 1 изображена трапеция. "
            "Найдите её площадь в см²."
        ),
        "OGE18-A05": (
            "На клетчатой бумаге с размером клетки 1 × 1 изображён ромб. Найдите его площадь."
        ),
    }
)
SOURCES_V1 = dict(SOURCES)
SOURCES_V1["OGE18-A01"] = "311388"


def decimal(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator // 2}.5"


def fingerprint(family: str, points: tuple[Point, ...]) -> str:
    if family in NEW_FAMILIES:
        shape: object
        if family == "OGE18-D05":
            dx = abs(points[1][0] - points[0][0])
            dy = abs(points[1][1] - points[0][1])
            shape = tuple(sorted((dx, dy)))
        else:
            variants: list[tuple[Point, ...]] = []
            for swap_axes in (False, True):
                for sign_x, sign_y in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                    transformed = tuple(
                        (
                            sign_x * (point[1] if swap_axes else point[0]),
                            sign_y * (point[0] if swap_axes else point[1]),
                        )
                        for point in points
                    )
                    min_x = min(point[0] for point in transformed)
                    min_y = min(point[1] for point in transformed)
                    normalized = tuple((x - min_x, y - min_y) for x, y in transformed)
                    for sequence in (normalized, tuple(reversed(normalized))):
                        variants.extend(sequence[i:] + sequence[:i] for i in range(len(sequence)))
            shape = min(variants)
        identity = f"{family}:{shape}"
        return hashlib.sha256(identity.encode()).hexdigest()
    a, b, c = points[:3]
    length = points[-1][0] - a[0]
    offset, height = b[0] - a[0], b[1] - a[1]
    upper = 0 if len(points) == 3 else c[0] - b[0]
    # Remove translations and reflection; labels and color never count as novelty.
    offset = min(offset, length - upper - offset)
    identity = f"{family}:{length}:{upper}:{offset}:{height}:midline"
    return hashlib.sha256(identity.encode()).hexdigest()


def teaching(family: str, points: tuple[Point, ...]) -> tuple[list[str], list[str]]:
    if family in NEW_FAMILIES:
        result = answer_family(family, points)
        value = decimal(result).replace(".", ",")

        def length(first: Point, second: Point) -> int:
            square = (second[0] - first[0]) ** 2 + (second[1] - first[1]) ** 2
            exact = isqrt(square)
            if exact * exact != square:
                raise ValueError("The supported teaching model requires integer lengths")
            return exact

        if family == "OGE18-D05":
            dx = abs(points[1][0] - points[0][0])
            dy = abs(points[1][1] - points[0][1])
            return (
                [
                    "Сосчитайте горизонтальное и вертикальное расстояния по клеткам.",
                    "Используйте теорему Пифагора для расстояния между точками.",
                ],
                [
                    f"По клеткам: Δx = {dx}, Δy = {dy}.",
                    f"По теореме Пифагора: d = √({dx}² + {dy}²) = {value}.",
                ],
            )
        if family == "OGE18-L02":
            legs: tuple[int, int] | None = None
            for i in range(3):
                vertex = points[i]
                first, second = points[(i + 1) % 3], points[(i + 2) % 3]
                u = (first[0] - vertex[0], first[1] - vertex[1])
                v = (second[0] - vertex[0], second[1] - vertex[1])
                if u[0] * v[0] + u[1] * v[1] == 0:
                    legs = (length(vertex, first), length(vertex, second))
                    break
            if legs is None:
                raise ValueError("Right angle is missing")
            shorter, longer = sorted(legs)
            return (
                [
                    "Найдите вершину прямого угла.",
                    "Сосчитайте клетки вдоль каждого катета и сравните длины.",
                ],
                [
                    f"Длины катетов: {shorter} и {longer}.",
                    f"Больший катет: {longer}.",
                ],
            )
        if family == "OGE18-A01":
            a, b, c, d = points
            lower, upper = length(a, d), length(b, c)
            height = Fraction(
                abs((d[0] - a[0]) * (b[1] - a[1]) - (d[1] - a[1]) * (b[0] - a[0])), lower
            )
            h = decimal(height).replace(".", ",")
            return (
                [
                    "Сосчитайте клетки вдоль оснований и найдите высоту трапеции.",
                    "Подставьте значения в формулу площади трапеции.",
                ],
                [
                    f"Основания: {lower} и {upper}, высота: {h}.",
                    f"S = ({lower} + {upper}) · {h} / 2 = {value}.",
                ],
            )
        if family == "OGE18-A03":
            a, _, c = points
            base = length(a, c)
            cross = abs(
                (points[1][0] - a[0]) * (c[1] - a[1]) - (points[1][1] - a[1]) * (c[0] - a[0])
            )
            height = Fraction(cross, base)
            h = decimal(height).replace(".", ",")
            return (
                [
                    "Сосчитайте клетки вдоль основания и найдите высоту треугольника.",
                    "Площадь треугольника равна половине произведения основания на высоту.",
                ],
                [f"Основание: {base}, высота: {h}.", f"S = {base} · {h} / 2 = {value}."],
            )
        if family == "OGE18-A04":
            a, b, _, d = points
            base = length(a, b)
            cross = abs((b[0] - a[0]) * (d[1] - a[1]) - (b[1] - a[1]) * (d[0] - a[0]))
            height = Fraction(cross, base)
            h = decimal(height).replace(".", ",")
            return (
                [
                    "Сосчитайте клетки вдоль основания и найдите перпендикулярную высоту.",
                    "Площадь параллелограмма равна произведению основания на высоту.",
                ],
                [f"Основание: {base}, высота: {h}.", f"S = {base} · {h} = {value}."],
            )
        a, b, c, d = points
        first_diagonal, second_diagonal = length(a, c), length(b, d)
        return (
            [
                "Найдите длины диагоналей ромба по клеткам.",
                "Площадь ромба равна половине произведения диагоналей.",
            ],
            [
                f"Диагонали: {first_diagonal} и {second_diagonal}.",
                f"S = {first_diagonal} · {second_diagonal} / 2 = {value}.",
            ],
        )
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
    formatted_result = decimal(Fraction(lower + upper, 2)).replace(".", ",")
    return (
        [
            "Найдите две параллельные стороны и посчитайте клетки вдоль них.",
            "Средняя линия трапеции равна полусумме оснований.",
        ],
        [
            f"Основания занимают {lower} и {upper} клеток.",
            f"Длина средней линии: ({lower} + {upper}) : 2 = {formatted_result}.",
        ],
    )


def _teaching_v1(family: str, points: tuple[Point, ...]) -> tuple[list[str], list[str]]:
    """Restore the initial OGE18-grid-2 learner content for existing snapshots."""
    if family not in NEW_FAMILIES:
        return teaching(family, points)
    value = decimal(answer_family(family, points)).replace(".", ",")
    if family == "OGE18-D05":
        return (
            [
                "Сосчитайте горизонтальное и вертикальное расстояния по клеткам.",
                "Используйте теорему Пифагора для расстояния между точками.",
            ],
            [
                "Квадрат расстояния равен сумме квадратов катетов.",
                f"Расстояние между точками равно {value}.",
            ],
        )
    if family == "OGE18-L02":
        return (
            [
                "Найдите вершину прямого угла.",
                "Сосчитайте клетки вдоль каждого катета и сравните длины.",
            ],
            [
                "Катеты перпендикулярны; равенство длин проверяется по координатам.",
                f"Больший катет равен {value}.",
            ],
        )
    label = {
        "OGE18-A01": "трапеции",
        "OGE18-A03": "треугольника",
        "OGE18-A04": "параллелограмма",
        "OGE18-A05": "ромба",
    }[family]
    unit = " см²" if family == "OGE18-A01" else ""
    return (
        ["Определите размеры фигуры по клеткам.", f"Используйте формулу площади {label}."],
        [f"Площадь по координатам равна {value}{unit}."],
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


def _model_for_seed(
    family_id: str, seed: int, version: str = GENERATOR_VERSION
) -> tuple[tuple[Point, ...], Fraction]:
    points: tuple[Point, ...]
    rng = random.Random(seed)
    x, y = rng.randint(2, 3), rng.randint(2, 3)
    if family_id == FAMILIES[0]:
        base = rng.choice((4, 6, 8, 10, 12, 14))
        offset, height = rng.randint(1, base - 1), rng.randint(3, 11)
        return ((x, y), (x + offset, y + height), (x + base, y)), Fraction(base, 2)
    if family_id == FAMILIES[1]:
        lower = rng.randint(6, 12)
        upper = rng.randint(2, lower - 2)
        offset, height = rng.randint(1, lower - upper - 1), rng.randint(3, 8)
        points = (
            (x, y),
            (x + offset, y + height),
            (x + offset + upper, y + height),
            (x + lower, y),
        )
        return points, Fraction(lower + upper, 2)
    if version == GENERATOR_VERSION_V2 and family_id in NEW_FAMILIES:
        if family_id == "OGE18-D05":
            triples = ((3, 4, 5), (5, 12, 13), (8, 15, 17))
            dx, dy, _ = rng.choice(triples)
            if rng.randrange(2):
                dx, dy = dy, dx
            if rng.randrange(2):
                dx = -dx
            if rng.randrange(2):
                dy = -dy
            x = rng.randint(2 + max(0, -dx), 17 - max(0, dx))
            y = rng.randint(2 + max(0, -dy), 17 - max(0, dy))
            return ((x, y), (x + dx, y + dy)), Fraction(isqrt(dx * dx + dy * dy))
        if family_id == "OGE18-L02":
            w, h = rng.randint(3, 9), rng.randint(3, 9)
            while w == h:
                h = rng.randint(3, 9)
            x, y = rng.randint(2, 17 - w), rng.randint(2, 17 - h)
            return ((x, y), (x, y + h), (x + w, y + h)), Fraction(max(w, h))
        if family_id == "OGE18-A01":
            lower, h = rng.randint(6, 12), rng.randint(3, 8)
            upper = rng.randint(2, min(5, lower - 2))
            shift = rng.randint(1, lower - upper - 1)
            x, y = rng.randint(2, 17 - lower), rng.randint(2, 17 - h)
            points = ((x, y), (x + shift, y + h), (x + shift + upper, y + h), (x + lower, y))
            return points, answer_family(family_id, points)
        if family_id == "OGE18-A03":
            base = rng.randint(5, 12)
            height = rng.randint(2, min(8, 2 * (base // 2)))
            shifts = tuple(
                shift for shift in range(1, base) if 2 * min(shift, base - shift) >= height
            )
            shift = rng.choice(shifts)
            x, y = rng.randint(2, 17 - base), rng.randint(2, 17 - height)
            points = ((x, y), (x + shift, y + height), (x + base, y))
            return points, answer_family(family_id, points)
        if family_id == "OGE18-A04":
            base = rng.randint(5, 9)
            dx = rng.choice((-3, -2, -1, 1, 2, 3))
            height = rng.randint(3, 7)
            x = rng.randint(2 - min(dx, 0), 17 - base - max(0, dx))
            y = rng.randint(2, 17 - height)
            points = ((x, y), (x + base, y), (x + base + dx, y + height), (x + dx, y + height))
            return points, answer_family(family_id, points)
        if family_id == "OGE18-A05":
            p = rng.randint(2, 5)
            q = rng.choice(tuple(v for v in range(2, 6) if v != p))
            cx, cy = rng.randint(7, 12), rng.randint(7, 12)
            points = ((cx - p, cy), (cx, cy + q), (cx + p, cy), (cx, cy - q))
            return points, answer_family(family_id, points)
    raise ValueError("Unknown family")


def generate(family_id: str, seed: int, generator_version: str = GENERATOR_VERSION) -> Oge18Problem:
    if generator_version not in {GENERATOR_VERSION, GENERATOR_VERSION_V2}:
        raise ValueError("Unknown generator version")
    if family_id in NEW_FAMILIES and generator_version != GENERATOR_VERSION_V2:
        raise ValueError("New families require generator version 2")
    if family_id in FAMILIES and generator_version != GENERATOR_VERSION:
        raise ValueError("Legacy families require their original generator version")
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("Seed must be an unsigned signed-bigint-compatible integer")
    points, result = _model_for_seed(family_id, seed, generator_version)
    oracle = answer(points) if family_id in FAMILIES else answer_family(family_id, points)
    if oracle != result:
        raise ValueError("Coordinate oracle mismatch")
    png = (
        render(points, family_id == FAMILIES[0])
        if family_id in FAMILIES
        else render_family(family_id, points)
    )
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
    if family_id in NEW_FAMILIES:
        snapshot["renderer_version"] = VERSION_V2
        snapshot["geometry_model"] = "oge18-grid-model-2"
        snapshot["learner_content_version"] = LEARNER_CONTENT_VERSION
    # The generator already checked coordinates against its independent oracle.
    # Full snapshot validation belongs at persistence and restore boundaries.
    return _pack(snapshot)


def from_snapshot(snapshot: dict[str, Any], *, audit_pixels: bool = True) -> Oge18Problem:
    try:
        if len(json.dumps(snapshot)) > 250_000:
            raise ValueError("Snapshot too large")
        family = snapshot["family_id"]
        is_legacy = family in FAMILIES
        expected_gv = GENERATOR_VERSION if is_legacy else GENERATOR_VERSION_V2
        expected_rv = RENDERER_VERSION if is_legacy else VERSION_V2
        content_version = 1 if is_legacy else snapshot.get("learner_content_version", 1)
        if content_version not in (1, LEARNER_CONTENT_VERSION):
            raise ValueError("Unknown learner content version")
        if (
            family not in (*FAMILIES, *NEW_FAMILIES)
            or snapshot["generator_version"] != expected_gv
            or snapshot["renderer_version"] != expected_rv
        ):
            raise ValueError("Unknown snapshot version")
        seed = snapshot["seed"]
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError("Invalid seed")
        identity = str(uuid5(NAMESPACE_URL, f"{family}:{seed}:{expected_gv}"))
        if snapshot["problem_id"] != identity:
            raise ValueError("Invalid identity")
        raw_points = snapshot["points"]
        if not isinstance(raw_points, list) or any(len(p) != 2 for p in raw_points):
            raise ValueError("Invalid points")
        points = tuple((p[0], p[1]) for p in raw_points)
        if len(points) != (
            3
            if family == FAMILIES[0]
            else 4
            if family == FAMILIES[1]
            else 2
            if family == "OGE18-D05"
            else 3
            if family in {"OGE18-L02", "OGE18-A03"}
            else 4
        ):
            raise ValueError("Wrong vertex count")
        expected_points, expected_result = _model_for_seed(family, seed, expected_gv)
        if points != expected_points:
            raise ValueError("Coordinates do not match family seed and generator version")
        result = answer(points) if is_legacy else answer_family(family, points)
        if result != expected_result:
            raise ValueError("Seed-derived answer mismatch")
        hints, solution = (
            _teaching_v1(family, points) if content_version == 1 else teaching(family, points)
        )
        conditions = CONDITIONS if content_version == LEARNER_CONTENT_VERSION else CONDITIONS_V1
        if (
            snapshot["condition"] != conditions[family]
            or snapshot["hints"] != hints
            or snapshot["solution"] != solution
            or snapshot["correct_answer"] != decimal(result)
            or snapshot["fingerprint"] != fingerprint(family, points)
            or snapshot["answer_policy_id"] != POLICY.policy_id
            or snapshot["answer_policy_version"] != POLICY.version
            or snapshot["attempt_index"] != 0
            or snapshot["grid"] != {"cell_size": 1, "columns": 20, "rows": 17, "step_px": 32}
            or (not is_legacy and snapshot["geometry_model"] != "oge18-grid-model-2")
        ):
            raise ValueError("Corrupted mathematical snapshot")
        source = (
            SOURCES[family] if content_version == LEARNER_CONTENT_VERSION else SOURCES_V1[family]
        )
        if snapshot["provenance"] != {
            "task_id": source,
            "url": f"https://math-oge.sdamgia.ru/problem?id={source}",
            "kind": "generated_analogue",
        }:
            raise ValueError("Invalid provenance")
        png = base64.b64decode(snapshot["png_base64"], validate=True)
        if len(png) > 150_000 or hashlib.sha256(png).hexdigest() != snapshot["image_sha256"]:
            raise ValueError("Invalid PNG hash or size")
        if audit_pixels:
            if is_legacy:
                audit(png, points, family == FAMILIES[0])
            else:
                audit_family(png, family, points)
        elif png != (
            render(points, family == FAMILIES[0]) if is_legacy else render_family(family, points)
        ):
            raise ValueError("PNG does not match versioned renderer")
        return _pack(snapshot)
    except (KeyError, TypeError, IndexError, OverflowError) as exc:
        raise ValueError("Corrupted snapshot") from exc
