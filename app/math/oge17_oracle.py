"""Independent coordinate and visible-content oracle; never imports the generator."""

from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any

from app.math.answer_policy import format_decimal
from app.math.oge17_models import FAMILIES, Point


def sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-8)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def angle(a: Point, b: Point) -> float:
    return math.degrees(math.atan2(abs(cross(a, b)), dot(a, b)))


def audit_math(data: dict[str, Any]) -> Fraction:
    """Solve the displayed task and check every named construction against its coordinates."""
    try:
        return _audit(data)
    except (KeyError, TypeError, IndexError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("Malformed №17 mathematical model") from exc


def _audit(d: dict[str, Any]) -> Fraction:
    family = d["family_id"]
    require(family in FAMILIES, "Unknown family")
    p = d["exact_model"]["parameters"]
    require(all(type(v) is int and 0 < v <= 200 for v in p.values()), "Parameter bounds")
    points = {k: (float(v[0]), float(v[1])) for k, v in d["points"].items()}
    require(
        all(math.isfinite(x) and abs(x) < 500 for v in points.values() for x in v),
        "Nonfinite/outside layout",
    )
    a, b, c, e = (points[k] for k in "ABCD")
    edges = [sub(b, a), sub(c, b), sub(e, c), sub(a, e)]
    turns = [cross(edges[i], edges[(i + 1) % 4]) for i in range(4)]
    require(
        all(t > 1e-6 for t in turns) or all(t < -1e-6 for t in turns),
        "Nonconvex, crossing or degenerate polygon",
    )
    lengths = [math.hypot(*v) for v in edges]
    require(min(lengths) > 0.1, "Collapsed edge")
    require(close(cross(edges[1], edges[3]), 0), "Bases not parallel")
    area = abs(sum(cross(points[x], points[y]) for x, y in zip("ABCD", "BCDA", strict=True))) / 2
    segments = ["AB", "BC", "CD", "DA"]
    expected_labels: dict[str, str] = {}
    expected_marks: list[list[str]] = []
    expected_points = set("ABCD")
    text = d["condition"]
    numbers = [Fraction(n.replace(",", ".")) for n in re.findall(r"\d+(?:,\d+)?", text)]
    if family in FAMILIES[:4]:
        require(
            close(cross(edges[0], edges[2]), 0)
            and close(lengths[0], lengths[2])
            and close(lengths[1], lengths[3]),
            "Not a parallelogram",
        )
    if family == FAMILIES[0]:
        require(len(numbers) == 1 and numbers[0] == p["angle_b"], "Visible rhombus angle")
        require(
            re.fullmatch(
                r"В ромбе ABCD угол ABC равен \d+°. Найдите угол ACD. "
                r"Ответ дайте в градусах\.",
                text,
            )
            is not None,
            "Rhombus target",
        )
        require(40 <= p["angle_b"] <= 140 and p["side"] == 10, "Rhombus range")
        require(all(close(v, p["side"]) for v in lengths), "Unequal rhombus sides")
        require(close(angle(sub(a, b), sub(c, b)), float(numbers[0])), "Wrong drawn angle ABC")
        ca, cb, cd = sub(a, c), sub(b, c), sub(e, c)
        require(close(angle(cb, ca), angle(ca, cd)), "Diagonal does not bisect C")
        require(
            close(angle(sub(b, a), sub(c, a)), angle(sub(c, a), sub(e, a))),
            "Diagonal does not bisect A",
        )
        result = (180 - numbers[0]) / 2
        require(close(angle(ca, cd), float(result)), "Wrong angle ACD")
        segments += ["AC"]
        expected_solution = [
            f"∠BCD = 180° − {p['angle_b']}° = {180 - p['angle_b']}°.",
            f"∠ACD = {180 - p['angle_b']}° / 2 = {format_decimal(result)}°.",
        ]
    elif family in (FAMILIES[1], FAMILIES[3]):
        is_rectangle = family == FAMILIES[1]
        shape = "прямоугольника" if is_rectangle else "параллелограмма"
        tail = (
            r"BO = (\d+(?:,\d+)?), AB = (\d+). Найдите AC\."
            if is_rectangle
            else r"AC = (\d+), BD = (\d+), AB = (\d+). Найдите DO\."
        )
        require(
            re.fullmatch(
                "Диагонали AC и BD " + shape + " ABCD пересекаются в точке O, " + tail, text
            )
            is not None,
            "Diagonal question structure",
        )
        expected_points.add("O")
        o = points["O"]
        require(
            all(close(2 * o[i], a[i] + c[i]) and close(2 * o[i], b[i] + e[i]) for i in (0, 1)),
            "Wrong diagonal midpoint",
        )
        ac, bd = math.dist(a, c), math.dist(b, e)
        if is_rectangle:
            require(
                all(close(dot(edges[i], edges[(i + 1) % 4]), 0) for i in range(4)),
                "Rectangle has a nonright angle",
            )
            require(close(ac, bd), "Rectangle diagonal inequality")
            require(
                numbers == [Fraction(p["twice_bo"], 2), Fraction(p["ab"])], "Visible rectangle data"
            )
            require(
                close(math.dist(b, o), float(numbers[0])) and close(lengths[0], float(numbers[1])),
                "Rectangle length mismatch",
            )
            result = 2 * numbers[0]
            expected_solution = [
                f"AC = BD = 2 · BO = 2 · {format_decimal(numbers[0])} = {format_decimal(result)}."
            ]
        else:
            require(
                numbers == [Fraction(p[k]) for k in ("ac", "bd", "ab")], "Visible diagonals data"
            )
            require(
                close(ac, float(numbers[0]))
                and close(bd, float(numbers[1]))
                and close(lengths[0], float(numbers[2])),
                "Wrong parallelogram lengths",
            )
            require(
                abs(numbers[0] - numbers[1]) < 2 * numbers[2] < numbers[0] + numbers[1],
                "Impossible diagonal/side Gram matrix",
            )
            result = Fraction(str(math.dist(e, o))).limit_denominator(2)
            require(
                close(math.dist(e, o), float(result)) and result == numbers[1] / 2,
                "DO not a short exact half",
            )
            expected_solution = [f"DO = BD / 2 = {p['bd']} / 2 = {format_decimal(result)}."]
        segments += ["AC", "BD"]
    elif family == FAMILIES[2]:
        require(
            text == "Найдите площадь параллелограмма, изображённого на рисунке.",
            "Area question structure",
        )
        s, t, h, side = (p[k] for k in ("s", "t", "h", "side"))
        require(s * s + h * h == side * side, "False labelled hypotenuse")
        expected_labels = {"AH": str(s), "HD": str(t), "BH": str(h), "AB": str(side)}
        expected_points.add("H")
        foot = points["H"]
        require(
            close(math.dist(a, foot), s)
            and close(math.dist(foot, e), t)
            and close(math.dist(a, e), s + t)
            and close(math.dist(b, foot), h)
            and close(math.dist(a, b), side),
            "False dimension labels",
        )
        require(close(cross(sub(foot, a), sub(e, a)), 0), "Foot outside base line")
        require(close(dot(sub(b, foot), sub(e, a)), 0), "False perpendicular height")
        result = Fraction(s + t) * h
        require(
            close(area, float(result)) and close(abs(cross(edges[0], sub(e, a))), area),
            "Area not equal to drawn parallelogram",
        )
        segments += ["BH"]
        expected_marks = [["B", "H", "D"]]
        expected_solution = [
            f"AD = {s} + {t} = {s + t}.",
            f"S = AD · BH = {s + t} · {h} = {result}.",
        ]
    else:
        lower, upper, h = (p[k] for k in ("lower", "upper", "h"))
        require(
            lower > upper > 0 and close(lengths[1], upper) and close(lengths[3], lower),
            "Trapezoid bases",
        )
        height = abs(cross(sub(b, a), sub(e, a))) / math.dist(a, e)
        require(close(height, h), "Wrong perpendicular distance between bases")
        if family == FAMILIES[4]:
            pattern = (
                r"Основания трапеции ABCD равны (\d+) и (\d+). MN — средняя линия, "
                r"K — точка её пересечения с диагональю BD. "
                r"Найдите больший из отрезков MK и KN\."
            )
            require(
                re.fullmatch(pattern, text) is not None and numbers == [upper, lower],
                "Midline question structure/data",
            )
            expected_points.update("MNK")
            m, n, k = (points[key] for key in "MNK")
            require(
                all(close(2 * m[i], a[i] + b[i]) and close(2 * n[i], c[i] + e[i]) for i in (0, 1)),
                "Not side midpoints",
            )
            # Solve m+t(n-m)=b+q(d-b), rather than inserting an expected half-base.
            direction, diag = sub(n, m), sub(e, b)
            t = cross(sub(b, m), diag) / cross(direction, diag)
            intersection = (m[0] + t * direction[0], m[1] + t * direction[1])
            require(
                0 < t < 1 and math.dist(k, intersection) < 1e-8,
                "Wrong diagonal/midline intersection",
            )
            parts = sorted((math.dist(m, k), math.dist(k, n)))
            require(
                close(parts[0], upper / 2)
                and close(parts[1], lower / 2)
                and close(math.dist(m, n), (lower + upper) / 2),
                "False middle-line lengths",
            )
            result = Fraction(str(parts[1])).limit_denominator(2)
            require(close(float(result), parts[1]), "Inexact midline answer")
            segments += ["MN", "BD"]
            expected_solution = [
                f"MK = AD / 2 = {format_decimal(Fraction(lower, 2))}; "
                f"KN = BC / 2 = {format_decimal(Fraction(upper, 2))}.",
                f"Больший отрезок MK равен {format_decimal(result)}.",
            ]
        else:
            pattern = (
                r"Основания трапеции ABCD равны (\d+) и (\d+), "
                r"а высота BH равна (\d+). Найдите площадь этой трапеции\."
            )
            require(
                re.fullmatch(pattern, text) is not None and numbers == [upper, lower, h],
                "Trapezoid question structure/data",
            )
            # Shoelace in exact rationals, independently from area formula.
            coords = [tuple(Fraction(str(v)) for v in points[key]) for key in "ABCD"]
            result = (
                abs(
                    sum(
                        (
                            coords[i][0] * coords[(i + 1) % 4][1]
                            - coords[(i + 1) % 4][0] * coords[i][1]
                            for i in range(4)
                        ),
                        start=Fraction(0),
                    )
                )
                / 2
            )
            require(result == Fraction((upper + lower) * h, 2), "Trapezoid area mismatch")
            expected_points.add("H")
            foot = points["H"]
            require(
                close(cross(sub(foot, a), sub(e, a)), 0)
                and close(dot(sub(b, foot), sub(e, a)), 0)
                and close(math.dist(b, foot), h),
                "Incorrect drawn trapezoid height",
            )
            segments += ["BH"]
            expected_marks = [["B", "H", "D"]]
            expected_solution = [f"S = ({upper} + {lower}) · {h} / 2 = {format_decimal(result)}."]
    require(set(points) == expected_points, "Extra/missing named points")
    require(d["segments"] == segments, "Unexpected/missing construction")
    require(d["right_angles"] == expected_marks, "False right-angle marks")
    require(d["length_labels"] == expected_labels, "Wrong drawing annotations")
    require(d["solution"] == expected_solution, "Invalid worked solution")
    require(d["correct_answer"] == format_decimal(result), "Wrong short answer")
    require(0 < result <= 10000 and result.denominator in (1, 2), "Manual complexity/answer bounds")
    return result
