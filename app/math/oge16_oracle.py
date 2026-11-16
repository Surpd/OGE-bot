"""Independent full-text parser and Euclidean witness checks (no generator imports)."""

from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any

from app.math.answer_policy import NUMERIC_SHORT_ANSWER, format_decimal

N = r"([0-9]+(?:,[0-9]+)?)"
PATTERNS = {
    "OGE16-A02": (
        rf"Точки A, B, C лежат на окружности с центром O\. Угол AOB равен {N}°\. "
        rf"Точка C лежит на большей дуге AB\. Найдите угол ACB в градусах\."
    ),
    "OGE16-A05": (
        rf"Треугольник ABC вписан в окружность с центром O\. AC — диаметр\. Угол "
        rf"A равен {N}°\. Найдите угол C в градусах\."
    ),
    "OGE16-B01": (
        rf"На отрезке AB выбрана точка C: AC = {N}, CB = {N}\. Окружность с "
        rf"центром A проходит через C\. BT — касательная, T — точка касания\. "
        rf"Найдите BT\."
    ),
    "OGE16-B03": (
        rf"Радиус окружности с центром O равен {N} см\. Расстояние от O до хорды "
        rf"AB равно {N} см\. M — основание перпендикуляра из O на AB\. Найдите "
        rf"AB в сантиметрах\."
    ),
    "OGE16-C01": (
        rf"Квадрат ABCD описан около окружности с центром O радиуса {N}\. "
        rf"Найдите площадь квадрата\."
    ),
    "OGE16-D01": (
        rf"Выпуклый четырёхугольник ABCD вписан в окружность\. Угол A равен "
        rf"{N}°\. Найдите угол C в градусах\."
    ),
    "OGE16-B04": (
        rf"Через точку A, лежащую вне окружности, проведены две прямые\. Одна прямая "
        rf"касается окружности в точке K\. Другая прямая пересекает окружность в точках "
        rf"B и C, причём AB = {N}, AC = {N}\. Найдите AK\."
    ),
    "OGE16-C02": (
        rf"Радиус окружности, вписанной в равнобедренную трапецию, равен {N}\. "
        rf"Найдите высоту этой трапеции\."
    ),
    "OGE16-C03": (
        rf"Периметр треугольника равен {N}, одна из сторон равна {N}, а радиус "
        rf"вписанной в него окружности равен {N}\. Найдите площадь этого треугольника\."
    ),
}
TRAPEZOID_D01 = (
    rf"Трапеция ABCD с основаниями AD и BC вписана в окружность\. Угол A равен "
    rf"{N}°\. Найдите угол C в градусах\."
)
TRAPEZOID_C02 = (
    rf"Радиус окружности, вписанной в трапецию, равен {N}\. "
    rf"Найдите высоту этой трапеции\."
)
THEOREMS = {
    "OGE16-A02": "Вписанный угол равен половине центрального угла, опирающегося на ту же дугу.",
    "OGE16-A05": "Угол ABC опирается на диаметр AC и равен 90°. Острые углы в сумме дают 90°.",
    "OGE16-B01": (
        "Радиус AT перпендикулярен касательной BT. В треугольнике ATB применим теорему Пифагора."
    ),
    "OGE16-B03": (
        "Перпендикуляр из центра к хорде делит её пополам. В треугольнике OMA "
        "применим теорему Пифагора."
    ),
    "OGE16-C01": (
        "Сторона квадрата равна диаметру вписанной окружности. Площадь "
        "квадрата равна квадрату стороны."
    ),
    "OGE16-D01": "Сумма противоположных углов вписанного четырёхугольника равна 180°.",
    "OGE16-B04": "По теореме о касательной и секущей AK² = AB · AC.",
    "OGE16-C02": (
        "Высота трапеции равна расстоянию между основаниями; оно равно диаметру окружности."
    ),
    "OGE16-C03": (
        "Площадь треугольника равна произведению полупериметра на радиус вписанной окружности."
    ),
}
SEGMENTS = {
    "OGE16-A02": {"AO", "BO", "AB", "AC", "BC"},
    "OGE16-A05": {"AB", "BC", "AC"},
    "OGE16-B01": {"AB", "BT", "AT"},
    "OGE16-B03": {"AB", "MO"},
    "OGE16-C01": {"AB", "BC", "CD", "AD"},
    "OGE16-D01": {"AB", "BC", "CD", "AD"},
    "OGE16-B04": {"AC", "AK", "KO"},
    "OGE16-C02": {"AB", "BC", "CD", "AD"},
    "OGE16-C03": {"AB", "BC", "AC"},
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def near(actual: float, expected: float) -> None:
    require(
        math.isfinite(actual)
        and math.isfinite(expected)
        and math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-7),
        "Geometry mismatch",
    )


def vector(a: Any, b: Any) -> tuple[float, float]:
    return float(b[0] - a[0]), float(b[1] - a[1])


def dot(u: Any, v: Any) -> float:
    return float(u[0] * v[0] + u[1] * v[1])


def cross(u: Any, v: Any) -> float:
    return float(u[0] * v[1] - u[1] * v[0])


def distance(a: Any, b: Any) -> float:
    return math.hypot(*vector(a, b))


def angle(a: Any, vertex: Any, b: Any) -> float:
    u, v = vector(vertex, a), vector(vertex, b)
    require(math.hypot(*u) * math.hypot(*v) > 1e-10, "Degenerate angle")
    return math.degrees(math.atan2(abs(cross(u, v)), dot(u, v)))


def square_root(value: Fraction) -> Fraction:
    require(value >= 0, "Negative square")
    n, d = math.isqrt(value.numerator), math.isqrt(value.denominator)
    require(n * n == value.numerator and d * d == value.denominator, "Irrational answer")
    return Fraction(n, d)


def visible_values(family: str, condition: str) -> tuple[Fraction, ...]:
    pattern = (
        TRAPEZOID_D01
        if family == "OGE16-D01" and condition.startswith("Трапеция")
        else TRAPEZOID_C02
        if family == "OGE16-C02" and "равнобедренную" not in condition
        else PATTERNS.get(family)
    )
    if pattern is None:
        raise ValueError("Unknown family")
    match = re.fullmatch(pattern, condition)
    require(match is not None, "Statement shape/target/units changed")
    assert match is not None
    return tuple(Fraction(s.replace(",", ".")) for s in match.groups())


def solve_visible(family: str, condition: str, geometry: dict[str, Any]) -> Fraction:
    """Solve visible statement, then independently verify the coordinate witness."""
    require(family in PATTERNS, "Unknown family")
    values = visible_values(family, condition)
    require(all(0 <= v <= 1000 for v in values), "Manual complexity limit")
    g = geometry
    p = g["points"]
    r = g["radius"]
    require(type(r) in (int, float) and 0 < r <= 1000, "Invalid radius")
    if family == "OGE16-B04":
        require(g["center"] == p["O"], "Circle center disagrees with point O")
    elif family == "OGE16-C02":
        require(
            isinstance(g["center"], list)
            and len(g["center"]) == 2
            and math.isclose(g["center"][1], r),
            "Invalid incircle center",
        )
    elif family == "OGE16-C03":
        require(
            isinstance(g["center"], list)
            and len(g["center"]) == 2
            and all(math.isfinite(v) for v in g["center"]),
            "Invalid incircle center",
        )
    else:
        require(g["center"] == [0.0, 0.0], "Unexpected center")
    for point in p.values():
        require(isinstance(point, list) and len(point) == 2, "Invalid point")
        require(all(type(v) in (int, float) and math.isfinite(v) for v in point), "Nonfinite point")
    names = {
        "OGE16-A02": "OABC",
        "OGE16-A05": "OABC",
        "OGE16-B01": "ACBT",
        "OGE16-B03": "OABM",
        "OGE16-C01": "OABCD",
        "OGE16-D01": "ABCD",
        "OGE16-B04": "OABCK",
        "OGE16-C02": "ABCD",
        "OGE16-C03": "ABC",
    }
    require(set(p) == set(names[family]), "Point labels changed")
    edges = g["segments"]
    require(
        len(edges) == len(SEGMENTS[family])
        and {"".join(sorted(e)) for e in edges} == SEGMENTS[family],
        "Topology changed",
    )
    if family != "OGE16-A02":
        require(g["arc"] is None, "Unexpected arc")
    center = (
        g["center"]
        if family in {"OGE16-C02", "OGE16-C03"}
        else p.get("O", p["A"] if family == "OGE16-B01" else [0.0, 0.0])
    )
    near(distance(center, g["center"]), 0)
    on_circle = {
        "OGE16-A02": "ABC",
        "OGE16-A05": "ABC",
        "OGE16-B01": "CT",
        "OGE16-B03": "AB",
        "OGE16-C01": "",
        "OGE16-D01": "ABCD",
        "OGE16-B04": "BCK",
        "OGE16-C02": "",
        "OGE16-C03": "",
    }
    for name in on_circle[family]:
        near(distance(center, p[name]), r)
    a = values[0]
    if family == "OGE16-A02":
        require(0 < a < 180 and a.denominator == 1 and a % 2 == 0, "Central angle domain")
        require(g["arc"] == ["A", "B", "ccw_minor"], "Arc orientation changed")
        theta = {n: math.atan2(p[n][1], p[n][0]) % math.tau for n in "ABC"}
        sweep = (theta["B"] - theta["A"]) % math.tau
        require(
            0 < sweep < math.pi and (theta["C"] - theta["A"]) % math.tau > sweep,
            "C lies on the intercepted arc",
        )
        near(math.degrees(sweep), float(a))
        near(angle(p["A"], center, p["B"]), float(a))
        result = a / 2
        near(angle(p["A"], p["C"], p["B"]), float(result))
    elif family == "OGE16-A05":
        require(0 < a < 90 and a.denominator == 1, "Acute angle domain")
        near(distance(p["A"], p["C"]), 2 * r)
        near(angle(p["A"], p["B"], p["C"]), 90)
        near(angle(p["B"], p["A"], p["C"]), float(a))
        result = 90 - a
        near(angle(p["A"], p["C"], p["B"]), float(result))
    elif family == "OGE16-B01":
        radius, outside = values
        require(radius > 0 and outside > 0, "External point required")
        d = radius + outside
        near(r, float(radius))
        near(distance(p["A"], p["B"]), float(d))
        near(distance(p["C"], p["B"]), float(outside))
        near(cross(vector(p["A"], p["C"]), vector(p["A"], p["B"])), 0)
        require(
            dot(vector(p["A"], p["C"]), vector(p["C"], p["B"])) > 0, "C must be between A and B"
        )
        near(dot(vector(p["T"], p["A"]), vector(p["T"], p["B"])), 0)
        result = square_root(d * d - radius * radius)
        near(distance(p["B"], p["T"]), float(result))
    elif family == "OGE16-B03":
        radius, d = values
        require(radius > 0 and 0 <= d < radius, "Chord domain")
        near(r, float(radius))
        for axis in (0, 1):
            near(p["M"][axis], (p["A"][axis] + p["B"][axis]) / 2)
        near(distance(center, p["M"]), float(d))
        near(dot(vector(center, p["M"]), vector(p["A"], p["B"])), 0)
        result = 2 * square_root(radius * radius - d * d)
        near(distance(p["A"], p["B"]), float(result))
    elif family == "OGE16-B04":
        external, whole = values
        require(0 < external < whole, "Secant lengths must be positive and ordered")
        require(r > 0, "Circle radius must be positive")
        near(distance(p["A"], p["B"]), float(external))
        near(distance(p["A"], p["C"]), float(whole))
        near(distance(p["B"], p["C"]), float(whole - external))
        near(cross(vector(p["A"], p["B"]), vector(p["A"], p["C"])), 0)
        require(dot(vector(p["A"], p["B"]), vector(p["B"], p["C"])) > 0, "Invalid secant order")
        near(distance(center, p["K"]), r)
        near(dot(vector(p["K"], p["A"]), vector(p["K"], center)), 0)
        result = square_root(external * whole)
        near(distance(p["A"], p["K"]), float(result))
    elif family == "OGE16-C02":
        require(a > 0, "Positive inradius required")
        vertices = [p[n] for n in "ABCD"]
        ab, cd = vector(p["A"], p["B"]), vector(p["C"], p["D"])
        near(cross(ab, cd), 0)
        near(distance(p["A"], p["D"]), distance(p["B"], p["C"]))
        near(abs(p["A"][1] - p["D"][1]), 2 * float(a))
        for first, second in zip(vertices, (*vertices[1:], vertices[0]), strict=True):
            tangent_vector = vector(first, second)
            near(
                abs(cross(tangent_vector, vector(first, center))) / math.hypot(*tangent_vector),
                float(a),
            )
        result = 2 * a
    elif family == "OGE16-C03":
        perimeter, triangle_side, radius = values
        require(perimeter > triangle_side > 0 and radius > 0, "Triangle input domain")
        vertices = [p[n] for n in "ABC"]
        edge_vectors = [vector(vertices[i], vertices[(i + 1) % 3]) for i in range(3)]
        lengths = [math.hypot(*edge) for edge in edge_vectors]
        near(sum(lengths), float(perimeter))
        near(lengths[0], float(triangle_side))
        area = abs(cross(edge_vectors[0], vector(vertices[0], vertices[2]))) / 2
        result = perimeter / 2 * radius
        near(area, float(result))
        turns = [cross(edge_vectors[i], edge_vectors[(i + 1) % 3]) for i in range(3)]
        require(all(t > 0 for t in turns) or all(t < 0 for t in turns), "Triangle not convex")
        distances = [
            abs(cross(edge_vectors[i], vector(vertices[i], center))) / lengths[i] for i in range(3)
        ]
        for distance_to_side in distances:
            near(distance_to_side, float(radius))
    elif family == "OGE16-C01":
        require(a > 0, "Positive radius required")
        near(r, float(a))
        vertices = [p[n] for n in "ABCD"]
        sides = [vector(vertices[i], vertices[(i + 1) % 4]) for i in range(4)]
        for i, side in enumerate(sides):
            near(math.hypot(*side), 2 * r)
            near(dot(side, sides[(i + 1) % 4]), 0)
            near(abs(cross(side, vector(vertices[i], center))) / math.hypot(*side), r)
        signs = [cross(sides[i], vector(vertices[i], center)) for i in range(4)]
        require(all(s > 0 for s in signs) or all(s < 0 for s in signs), "Circle outside square")
        result = 4 * a * a
        near(
            abs(sum(cross(vertices[i], vertices[(i + 1) % 4]) for i in range(4))) / 2, float(result)
        )
    else:
        require(0 < a < 180 and a.denominator == 1, "Cyclic angle domain")
        vertices = [p[n] for n in "ABCD"]
        turns = [
            cross(
                vector(vertices[i], vertices[(i + 1) % 4]),
                vector(vertices[(i + 1) % 4], vertices[(i + 2) % 4]),
            )
            for i in range(4)
        ]
        require(
            all(t > 1e-8 for t in turns) or all(t < -1e-8 for t in turns),
            "Nonconvex or self-intersecting quadrilateral",
        )
        near(angle(p["B"], p["A"], p["D"]), float(a))
        result = 180 - a
        near(angle(p["B"], p["C"], p["D"]), float(result))
        if condition.startswith("Трапеция"):
            ad = vector(p["A"], p["D"])
            bc = vector(p["B"], p["C"])
            near(cross(ad, bc), 0)
            require(abs(dot(ad, bc)) > 1e-8, "Degenerate trapezoid")
    require(0 < result <= 40000, "Answer complexity limit")
    return result


def audit(snapshot: dict[str, Any], *, pixels: bool = True) -> Fraction:
    """Validate every mathematical field and proof step; fail closed on corrupt data."""
    try:
        if snapshot.get("generator_version") == "oge16-circles-3":
            from app.math.oge16_complete_oracle import solve
            from app.math.oge16_raster_oracle import audit_png

            require(snapshot["snapshot_version"] == 1, "Unknown snapshot version")
            require(type(snapshot["seed"]) is int and 0 <= snapshot["seed"] < 2**63, "Invalid seed")
            require(
                snapshot["answer_policy_id"] == NUMERIC_SHORT_ANSWER.policy_id
                and snapshot["answer_policy_version"] == NUMERIC_SHORT_ANSWER.version,
                "Unknown answer policy",
            )
            result = solve(snapshot)
            if pixels:
                audit_png(snapshot)
            return result
        family = snapshot["family_id"]
        require(
            snapshot["generator_version"] in {"oge16-circles-1", "oge16-circles-2"}
            and snapshot["snapshot_version"] == 1,
            "Unknown snapshot contract",
        )
        require(type(snapshot["seed"]) is int and 0 <= snapshot["seed"] < 2**63, "Invalid seed")
        result = solve_visible(family, snapshot["condition"], snapshot["geometry"])
        v = list(visible_values(family, snapshot["condition"]))
        if family == "OGE16-D01":
            model_p: tuple[Fraction, ...] = (
                (v[0], Fraction(1)) if snapshot["condition"].startswith("Трапеция") else (v[0],)
            )
        elif family == "OGE16-C02":
            model_p = (
                v[0],
                Fraction(int("равнобедренную" in snapshot["condition"])),
            )
        else:
            model_p = (v[0], sum(v, Fraction(0))) if family == "OGE16-B01" else tuple(v)
        require(
            snapshot["parameters"] == [str(n) for n in model_p], "Parameters disagree with text"
        )
        require(
            snapshot["answer_policy_id"] == NUMERIC_SHORT_ANSWER.policy_id
            and snapshot["answer_policy_version"] == NUMERIC_SHORT_ANSWER.version,
            "Unknown answer policy",
        )
        require(snapshot["correct_answer"] == format_decimal(result), "Incorrect exact answer")
        a, out = format_decimal(v[0]), format_decimal(result)
        if family == "OGE16-A02":
            calculation = f"∠ACB = {a} / 2 = {out}°."
        elif family in ("OGE16-A05", "OGE16-D01"):
            total = 90 if family == "OGE16-A05" else 180
            calculation = f"∠C = {total} − {a} = {out}°."
        elif family == "OGE16-B01":
            b, d = format_decimal(v[1]), format_decimal(sum(v, Fraction(0)))
            calculation = (
                f"AB = {a} + {b} = {d}; BT² = {d}² − {a}² = "
                f"{format_decimal(result**2)}; BT = {out}."
            )
        elif family == "OGE16-B03":
            d, h, h2 = (
                format_decimal(v[1]),
                format_decimal(result / 2),
                format_decimal((result / 2) ** 2),
            )
            calculation = f"AM² = {a}² − {d}² = {h2}; AM = {h}; AB = 2 · {h} = {out}."
        elif family == "OGE16-B04":
            external, whole = format_decimal(v[0]), format_decimal(v[1])
            calculation = f"AK² = {external} · {whole} = {format_decimal(v[0] * v[1])}; AK = {out}."
        elif family == "OGE16-C02":
            calculation = f"h = 2r = 2 · {a} = {out}."
        elif family == "OGE16-C03":
            radius = format_decimal(v[2])
            calculation = f"S = p · r = {format_decimal(v[0] / 2)} · {radius} = {out}."
        else:
            side = format_decimal(2 * v[0])
            calculation = f"a = 2 · {a} = {side}; S = {side}² = {out}."
        require(
            snapshot["hints"] == [THEOREMS[family]]
            and snapshot["solution"] == [THEOREMS[family], calculation],
            "Invalid proof/hint",
        )
        if pixels:
            from app.math.oge16_raster_oracle import audit_png

            audit_png(snapshot)
        return result
    except (
        KeyError,
        TypeError,
        IndexError,
        ArithmeticError,
        AttributeError,
        SyntaxError,
        RecursionError,
    ) as exc:
        raise ValueError("Malformed circle snapshot") from exc
