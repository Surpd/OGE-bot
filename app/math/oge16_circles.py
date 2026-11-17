"""Versioned circle training: 23 source-backed constructions and immutable PNGs."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import random
from dataclasses import dataclass
from fractions import Fraction
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import NUMERIC_SHORT_ANSWER, format_decimal
from app.math.oge16_complete import FAMILIES as FAMILIES
from app.math.oge16_model import CircleGeometry, Point

GENERATOR_VERSION = "oge16-circles-3"
GENERATOR_VERSION_V2 = "oge16-circles-2"
GENERATOR_VERSION_V1 = "oge16-circles-1"
LEGACY_FAMILIES = (
    "OGE16-A02",
    "OGE16-A05",
    "OGE16-B01",
    "OGE16-B03",
    "OGE16-C01",
    "OGE16-D01",
    "OGE16-B04",
    "OGE16-C02",
    "OGE16-C03",
)
ENABLED_FAMILIES: tuple[str, ...] = ()  # Public enablement requires a separate release decision.
POLICY = NUMERIC_SHORT_ANSWER
SOURCES = dict(
    zip(
        LEGACY_FAMILIES,
        (
            "314811",
            "341673",
            "340174",
            "340587",
            "341707",
            "356438",
            "356543",
            "355413",
            "356329",
        ),
        strict=True,
    )
)
LEGACY_CAPACITY = dict(zip(LEGACY_FAMILIES, (61, 51, 400, 400, 291, 82, 20, 2, 1), strict=True))
CAPACITY = dict(
    zip(
        FAMILIES,
        (
            20,
            20,
            20,
            10,
            30,
            10,
            10,
            10,
            10,
            10,
            10,
            31,
            20,
            10,
            40,
            20,
            10,
            20,
            10,
            10,
            10,
            10,
            10,
        ),
        strict=True,
    )
)
TRIPLES = ((3, 4, 5), (5, 12, 13), (8, 15, 17), (7, 24, 25))


def polar(angle: float, radius: float = 1.0) -> Point:
    return radius * math.cos(math.radians(angle)), radius * math.sin(math.radians(angle))


def parameters(
    family: str, seed: int, generator_version: str = GENERATOR_VERSION
) -> tuple[Fraction, ...]:
    if generator_version not in (GENERATOR_VERSION, GENERATOR_VERSION_V2, GENERATOR_VERSION_V1):
        raise ValueError("Unknown generator contract")
    if generator_version == GENERATOR_VERSION:
        from app.math.oge16_complete import parameters as complete_parameters

        return complete_parameters(family, seed)
    # Keep the random stream stable across the additive v2 source subtype.
    rng = random.Random(f"{family}:{seed}:{GENERATOR_VERSION_V1}")
    if family == LEGACY_FAMILIES[0]:
        return (Fraction(2 * rng.randint(20, 80)),)
    if family == LEGACY_FAMILIES[1]:
        return (Fraction(rng.randint(20, 70)),)
    if family in LEGACY_FAMILIES[2:4]:
        a, b, c = rng.choice(TRIPLES)
        k = Fraction(rng.randint(1, 100), 10)
        return (a * k, c * k) if family == LEGACY_FAMILIES[2] else (c * k, a * k)
    if family == LEGACY_FAMILIES[4]:
        return (Fraction(rng.randint(10, 300), 10),)
    if family == LEGACY_FAMILIES[5]:
        # Preserve the confirmed #356448 trapezoid question alongside the broader
        # cyclic-quadrilateral formulation represented by #356438.
        angle = rng.randint(50, 130)
        if generator_version == GENERATOR_VERSION_V1:
            return (Fraction(angle),)
        return (Fraction(81), Fraction(1)) if seed % 2 else (Fraction(angle),)
    if family == LEGACY_FAMILIES[6]:
        scale = seed % 20 + 1
        return Fraction(2 * scale), Fraction(8 * scale)
    if family == LEGACY_FAMILIES[7]:
        return (Fraction(16), Fraction(0)) if seed % 2 == 0 else (Fraction(12), Fraction(1))
    if family == LEGACY_FAMILIES[8]:
        return Fraction(50), Fraction(20), Fraction(4)
    raise ValueError("Unknown circle family")


def content(
    family: str, p: tuple[Fraction, ...], generator_version: str = GENERATOR_VERSION
) -> tuple[str, list[str], list[str], Fraction, CircleGeometry]:
    if generator_version == GENERATOR_VERSION:
        from app.math.oge16_complete import content as complete_content

        return complete_content(family, p)
    a = p[0]
    text_a = format_decimal(a)
    x = float(a)
    points: tuple[tuple[str, Point], ...]
    if family == LEGACY_FAMILIES[0]:
        result = a / 2
        condition = (
            f"Точки A, B, C лежат на окружности с центром O. Угол AOB равен {text_a}°. "
            "Точка C лежит на большей дуге AB. Найдите угол ACB в градусах."
        )
        theorem = "Вписанный угол равен половине центрального угла, опирающегося на ту же дугу."
        calculation = f"∠ACB = {text_a} / 2 = {format_decimal(result)}°."
        points = (
            ("O", (0.0, 0.0)),
            ("A", polar(-90 - x / 2)),
            ("B", polar(-90 + x / 2)),
            ("C", polar(90)),
        )
        scene = CircleGeometry(
            1.0,
            points,
            (("O", "A"), ("O", "B"), ("A", "B"), ("A", "C"), ("B", "C")),
            arc=("A", "B", "ccw_minor"),
        )
    elif family == LEGACY_FAMILIES[1]:
        result = 90 - a
        condition = (
            f"Треугольник ABC вписан в окружность с центром O. AC — диаметр. Угол A равен "
            f"{text_a}°. Найдите угол C в градусах."
        )
        theorem = "Угол ABC опирается на диаметр AC и равен 90°. Острые углы в сумме дают 90°."
        calculation = f"∠C = 90 − {text_a} = {format_decimal(result)}°."
        scene = CircleGeometry(
            1.0,
            (("O", (0.0, 0.0)), ("A", (-1.0, 0.0)), ("B", polar(2 * x)), ("C", (1.0, 0.0))),
            (("A", "B"), ("B", "C"), ("C", "A")),
        )
    elif family == LEGACY_FAMILIES[2]:
        radius, distance = p
        t2 = distance**2 - radius**2
        result = Fraction(math.isqrt(t2.numerator), math.isqrt(t2.denominator))
        condition = (
            f"На отрезке AB выбрана точка C: AC = {text_a}, CB = "
            f"{format_decimal(distance - radius)}. Окружность с центром A проходит через C. "
            "BT — касательная, T — точка касания. Найдите BT."
        )
        theorem = (
            "Радиус AT перпендикулярен касательной BT. В треугольнике ATB "
            "применим теорему Пифагора."
        )
        calculation = (
            f"AB = {text_a} + {format_decimal(distance - radius)} = {format_decimal(distance)}; "
            f"BT² = {format_decimal(distance)}² − {text_a}² = {format_decimal(t2)}; "
            f"BT = {format_decimal(result)}."
        )
        d = float(distance)
        scene = CircleGeometry(
            x,
            (
                ("A", (0.0, 0.0)),
                ("C", (x, 0.0)),
                ("B", (d, 0.0)),
                ("T", (x * x / d, -x * float(result) / d)),
            ),
            (("A", "B"), ("B", "T"), ("A", "T")),
        )
    elif family == LEGACY_FAMILIES[3]:
        radius, distance = p
        half2 = radius**2 - distance**2
        half = Fraction(math.isqrt(half2.numerator), math.isqrt(half2.denominator))
        result = 2 * half
        condition = (
            f"Радиус окружности с центром O равен {text_a} см. Расстояние от O до хорды AB "
            f"равно {format_decimal(distance)} см. M — основание перпендикуляра из O на AB. "
            "Найдите AB в сантиметрах."
        )
        theorem = (
            "Перпендикуляр из центра к хорде делит её пополам. В треугольнике "
            "OMA применим теорему Пифагора."
        )
        calculation = (
            f"AM² = {text_a}² − {format_decimal(distance)}² = {format_decimal(half2)}; "
            f"AM = {format_decimal(half)}; AB = 2 · {format_decimal(half)} = "
            f"{format_decimal(result)}."
        )
        h, d = float(half), float(distance)
        scene = CircleGeometry(
            x,
            (("O", (0.0, 0.0)), ("A", (-h, -d)), ("B", (h, -d)), ("M", (0.0, -d))),
            (("A", "B"), ("O", "M")),
        )
    elif family == LEGACY_FAMILIES[4]:
        result = 4 * a * a
        condition = (
            f"Квадрат ABCD описан около окружности с центром O радиуса {text_a}. "
            f"Найдите площадь квадрата."
        )
        theorem = (
            "Сторона квадрата равна диаметру вписанной окружности. Площадь "
            "квадрата равна квадрату стороны."
        )
        calculation = (
            f"a = 2 · {text_a} = {format_decimal(2 * a)}; S = "
            f"{format_decimal(2 * a)}² = {format_decimal(result)}."
        )
        scene = CircleGeometry(
            x,
            (("O", (0.0, 0.0)), ("A", (-x, -x)), ("B", (-x, x)), ("C", (x, x)), ("D", (x, -x))),
            (("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")),
        )
    elif family == LEGACY_FAMILIES[5]:
        result = 180 - a
        trapezoid = len(p) > 1 and p[1] == 1
        condition = (
            f"Трапеция ABCD с основаниями AD и BC вписана в окружность. Угол A равен "
            f"{text_a}°. Найдите угол C в градусах."
            if trapezoid
            else f"Выпуклый четырёхугольник ABCD вписан в окружность. Угол A равен "
            f"{text_a}°. Найдите угол C в градусах."
        )
        theorem = "Сумма противоположных углов вписанного четырёхугольника равна 180°."
        calculation = f"∠C = 180 − {text_a} = {format_decimal(result)}°."
        if trapezoid:
            phi = 60.0
            psi = phi + 180.0 - 2.0 * x
            scene = CircleGeometry(
                1.0,
                tuple(
                    (name, polar(degrees))
                    for name, degrees in (
                        ("A", 180 - phi),
                        ("B", 180 + psi),
                        ("C", 360 - psi),
                        ("D", phi),
                    )
                ),
                (("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")),
            )
        else:
            scene = CircleGeometry(
                1.0,
                (("A", (-1.0, 0.0)), ("B", polar(x)), ("C", (1.0, 0.0)), ("D", polar(-x))),
                (("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")),
            )
    elif family == LEGACY_FAMILIES[6]:
        external, whole = p
        product = external * whole
        result = Fraction(math.isqrt(product.numerator), math.isqrt(product.denominator))
        condition = (
            f"Через точку A, лежащую вне окружности, проведены две прямые. Одна прямая "
            f"касается окружности в точке K. Другая прямая пересекает окружность в точках "
            f"B и C, причём AB = {format_decimal(external)}, AC = {format_decimal(whole)}. "
            "Найдите AK."
        )
        theorem = "По теореме о касательной и секущей AK² = AB · AC."
        calculation = (
            f"AK² = {format_decimal(external)} · {format_decimal(whole)} = "
            f"{format_decimal(product)}; AK = {format_decimal(result)}."
        )
        scale = float(external / 2)
        points = (
            ("A", (0.0, 0.0)),
            ("B", (2 * scale, 0.0)),
            ("C", (8 * scale, 0.0)),
            ("K", (16 * scale / 5, 12 * scale / 5)),
            ("O", (5 * scale, 0.0)),
        )
        center = (5 * scale, 0.0)
        scene = CircleGeometry(
            3 * scale,
            points,
            (("A", "C"), ("A", "K"), ("O", "K")),
            center=center,
        )
    elif family == LEGACY_FAMILIES[7]:
        radius = a
        isosceles = len(p) > 1 and p[1] == 1
        result = 2 * radius
        condition = (
            f"Радиус окружности, вписанной в "
            f"{'равнобедренную ' if isosceles else ''}трапецию, равен "
            f"{text_a}. Найдите высоту этой трапеции."
        )
        theorem = (
            "Высота трапеции равна расстоянию между основаниями; оно равно диаметру окружности."
        )
        calculation = f"h = 2r = 2 · {text_a} = {format_decimal(result)}."
        r = float(radius)
        scene = CircleGeometry(
            r,
            (
                ("A", (-2 * r, 0.0)),
                ("B", (2 * r, 0.0)),
                ("C", (r / 2, 2 * r)),
                ("D", (-r / 2, 2 * r)),
            ),
            (("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")),
            center=(0.0, r),
        )
    elif family == LEGACY_FAMILIES[8]:
        perimeter, given_side, radius = p
        semiperimeter = perimeter / 2
        result = semiperimeter * radius
        condition = (
            f"Периметр треугольника равен {format_decimal(perimeter)}, одна из сторон равна "
            f"{format_decimal(given_side)}, а радиус вписанной в него окружности равен "
            f"{format_decimal(radius)}. Найдите площадь этого треугольника."
        )
        theorem = (
            "Площадь треугольника равна произведению полупериметра на радиус вписанной окружности."
        )
        calculation = (
            f"S = p · r = {format_decimal(semiperimeter)} · "
            f"{format_decimal(radius)} = {format_decimal(result)}."
        )
        root5 = math.sqrt(5)
        side_bc, side_ca = 15 + 2 * root5, 15 - 2 * root5
        cx = (side_ca**2 + float(given_side**2) - side_bc**2) / (2 * float(given_side))
        cy = 10.0
        wa, wb, wc = side_bc, side_ca, float(given_side)
        center = (
            (wa * 0 + wb * float(given_side) + wc * cx) / float(perimeter),
            wc * cy / float(perimeter),
        )
        scene = CircleGeometry(
            float(radius),
            (("A", (0.0, 0.0)), ("B", (float(given_side), 0.0)), ("C", (cx, cy))),
            (("A", "B"), ("B", "C"), ("C", "A")),
            center=center,
        )
    else:
        raise ValueError("Unknown circle family")
    return condition, [theorem], [theorem, calculation], result, scene


@dataclass(frozen=True, slots=True)
class CircleProblem:
    serialized: str

    def to_snapshot(self) -> dict[str, Any]:
        return dict(json.loads(self.serialized))

    @property
    def fingerprint(self) -> str:
        return str(self.to_snapshot()["fingerprint"])

    @property
    def png(self) -> bytes:
        return base64.b64decode(self.to_snapshot()["figure"]["png_base64"], validate=True)


def generate(
    family_id: str, seed: int, generator_version: str = GENERATOR_VERSION
) -> CircleProblem:
    from app.math.oge16_oracle import audit
    from app.math.oge16_render import RENDERER_VERSION, render

    if family_id not in FAMILIES or generator_version not in (
        GENERATOR_VERSION,
        GENERATOR_VERSION_V2,
        GENERATOR_VERSION_V1,
    ):
        raise ValueError("Unknown generator contract")
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("Invalid seed")
    p = parameters(family_id, seed, generator_version)
    condition, hints, solution, result, scene = content(family_id, p, generator_version)
    identity = json.dumps(
        [family_id, condition]
        if generator_version == GENERATOR_VERSION
        else [family_id, [str(v) for v in p]]
    )
    source_id = (
        "356448"
        if family_id == "OGE16-D01" and len(p) > 1 and p[1] == 1
        else "448769"
        if family_id == "OGE16-C02" and len(p) > 1 and p[1] == 1
        else SOURCES.get(family_id, "")
    )
    if generator_version == GENERATOR_VERSION:
        from app.math.oge16_complete import source

        source_id = source(family_id, p)
    png, layout = render(scene)
    snapshot = {
        "snapshot_version": 1,
        "problem_id": str(uuid5(NAMESPACE_URL, f"{family_id}:{seed}:{generator_version}")),
        "family_id": family_id,
        "seed": seed,
        "generator_version": generator_version,
        "parameters": [str(v) for v in p],
        "condition": condition,
        "hints": hints,
        "solution": solution,
        "correct_answer": format_decimal(result),
        "answer_policy_id": POLICY.policy_id,
        "answer_policy_version": POLICY.version,
        "fingerprint": hashlib.sha256(identity.encode()).hexdigest(),
        "attempt_index": 0,
        "geometry": scene.to_dict(),
        "figure": {
            "renderer_version": (
                "oge16-pillow-1" if generator_version == GENERATOR_VERSION_V1 else RENDERER_VERSION
            ),
            "width": 720,
            "height": 720,
            "png_base64": base64.b64encode(png).decode(),
            "sha256": hashlib.sha256(png).hexdigest(),
            "layout": layout,
        },
        "provenance": {
            "task_id": source_id,
            "url": f"https://math-oge.sdamgia.ru/problem?id={source_id}",
            "kind": "generated_analogue",
        },
    }
    audit(snapshot)
    return CircleProblem(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False))


def from_snapshot(snapshot: dict[str, Any]) -> CircleProblem:
    """Restore saved bytes, never regenerate the picture or reinterpret old versions."""
    from app.math.oge16_oracle import audit

    try:
        if len(json.dumps(snapshot)) > 150_000:
            raise ValueError("Snapshot too large")
        audit(snapshot)
        # Reconstruct only the mathematical identity. Stored PNGs are audited as-is.
        family, seed = snapshot["family_id"], snapshot["seed"]
        generator_version = snapshot["generator_version"]
        if generator_version not in (GENERATOR_VERSION, GENERATOR_VERSION_V2, GENERATOR_VERSION_V1):
            raise ValueError("Unknown generator version")
        p = parameters(family, seed, generator_version)
        condition, hints, solution, result, scene = content(family, p, generator_version)
        expected = {
            "problem_id": str(uuid5(NAMESPACE_URL, f"{family}:{seed}:{generator_version}")),
            "parameters": [str(v) for v in p],
            "geometry": scene.to_dict(),
            "condition": condition,
            "hints": hints,
            "solution": solution,
            "correct_answer": format_decimal(result),
            "fingerprint": hashlib.sha256(
                json.dumps(
                    [family, condition]
                    if generator_version == GENERATOR_VERSION
                    else [family, [str(v) for v in p]]
                ).encode()
            ).hexdigest(),
            "provenance": {
                "task_id": (
                    "356448"
                    if family == "OGE16-D01" and len(p) > 1 and p[1] == 1
                    else "448769"
                    if family == "OGE16-C02" and len(p) > 1 and p[1] == 1
                    else SOURCES.get(family, "")
                ),
                "url": "https://math-oge.sdamgia.ru/problem?id="
                + (
                    "356448"
                    if family == "OGE16-D01" and len(p) > 1 and p[1] == 1
                    else "448769"
                    if family == "OGE16-C02" and len(p) > 1 and p[1] == 1
                    else SOURCES.get(family, "")
                ),
                "kind": "generated_analogue",
            },
        }
        if generator_version == GENERATOR_VERSION:
            from app.math.oge16_complete import source

            source_id = source(family, p)
            expected["provenance"] = {
                "task_id": source_id,
                "url": f"https://math-oge.sdamgia.ru/problem?id={source_id}",
                "kind": "generated_analogue",
            }
        if any(snapshot.get(k) != v for k, v in expected.items()):
            raise ValueError("Corrupted circle snapshot")
        if type(snapshot.get("attempt_index")) is not int or snapshot["attempt_index"] not in (
            0,
            1,
            2,
        ):
            raise ValueError("Invalid attempt index")
        return CircleProblem(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False)
        )
    except (KeyError, TypeError, OverflowError, ArithmeticError) as exc:
        raise ValueError("Invalid circle snapshot") from exc
