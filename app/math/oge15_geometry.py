"""Triangle constructions in mathematical coordinates (not display coordinates)."""

from __future__ import annotations

from math import acos, cos, degrees, hypot, radians, sin, sqrt
from typing import Any

Point = tuple[float, float]
TOLERANCE = 1e-8


def sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def length(a: Point, b: Point) -> float:
    return hypot(*sub(a, b))


def angle(a: Point, b: Point, c: Point) -> float:
    u, v = sub(a, b), sub(c, b)
    return degrees(acos(max(-1.0, min(1.0, dot(u, v) / (hypot(*u) * hypot(*v))))))


def midpoint(a: Point, b: Point) -> Point:
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def interpolate(a: Point, b: Point, ratio: float) -> Point:
    return a[0] + ratio * (b[0] - a[0]), a[1] + ratio * (b[1] - a[1])


def triangle_angles(a: float, c: float, base: float = 10) -> dict[str, Point]:
    ab = base * sin(radians(c)) / sin(radians(180 - a - c))
    return {"A": (0, 0), "B": (ab * cos(radians(a)), ab * sin(radians(a))), "C": (base, 0)}


def construct(number: int, p: tuple[int, ...]) -> dict[str, Any]:
    points: dict[str, Point]
    a: float
    b: float
    segments = [("A", "B"), ("B", "C"), ("C", "A")]
    right: list[tuple[str, str, str]] = []
    equal: list[list[tuple[str, str]]] = []
    bisectors: list[tuple[str, str, str, str]] = []
    labels = ["A", "B", "C"]
    angle_arcs: list[tuple[str, str, str]] = []
    if number in (1, 2, 3, 4, 5, 10):
        if number == 1:
            points = triangle_angles(p[0], 180 - p[0] - p[1])
        elif number == 2:
            points = triangle_angles(p[0], p[1])
        elif number == 3:
            points = triangle_angles((180 - p[0]) / 2, p[0])
        elif number == 4:
            points = triangle_angles(p[0], 90 - p[0] / 2)
        elif number == 5:
            points = triangle_angles(180 - p[0], 180 - p[0])
            equal = [[("A", "B"), ("B", "C")]]
        else:
            points = triangle_angles(2 * p[0], p[0])
        if number in (2, 10):
            name = "D" if number == 2 else "K"
            ratio = length(points["A"], points["B"]) / (
                length(points["A"], points["B"]) + length(points["A"], points["C"])
            )
            points[name] = interpolate(points["B"], points["C"], ratio)
            segments.append(("A", name))
            bisectors.append(("B", "A", name, "C"))
            if number == 10:
                # The source marks the bisector; do not add equality ticks absent there.
                pass
        if number in (3, 5):
            points["X"] = (12.5, 0)
            segments.append(("C", "X"))
            if number == 3:
                angle_arcs.append(("B", "C", "X"))
        if number == 4:
            points["H"] = (points["B"][0], 0)
            segments.append(("B", "H"))
            right.append(("B", "H", "C"))
    elif number == 6:
        k = p[0]
        points = {"A": (0, 0), "B": (k, k * sqrt(3)), "C": (2 * k, 0), "H": (k, 0)}
        segments.append(("B", "H"))
        equal = [[("A", "H"), ("H", "C")]]
    elif number == 7:
        c = radians(p[0])
        points = {
            "A": (0, 0),
            "C": (10, 0),
            "B": (10 * sin(c) ** 2, 10 * sin(c) * cos(c)),
            "M": (5, 0),
        }
        segments.append(("B", "M"))
        equal = [[("A", "M"), ("M", "C"), ("B", "M")]]
    elif number in (8, 9):
        k = p[0]
        height = p[1] if number == 8 else k * sin(radians(p[1])) / cos(radians(p[1]))
        points = {
            "A": (0, 0),
            "C": (4 * k, 0),
            "M": (2 * k, 0),
            "H": (3 * k, 0),
            "B": (3 * k, height),
        }
        segments.extend((("B", "M"), ("B", "H")))
        right.append(("B", "H", "C"))
    elif number == 11:
        ab, bc, ac = p
        x = (ab * ab + ac * ac - bc * bc) / (2 * ac)
        points = {"A": (0, 0), "B": (x, sqrt(ab * ab - x * x)), "C": (ac, 0)}
        points["M"] = midpoint(points["A"], points["B"])
        points["N"] = midpoint(points["B"], points["C"])
        segments.append(("M", "N"))
        equal = [[("A", "M"), ("M", "B")], [("B", "N"), ("N", "C")]]
    elif number == 12:
        base = sqrt(8 * p[0])
        points = {"A": (0, 0), "B": (base, 0), "C": (base * 0.4, base)}
        points["D"] = midpoint(points["A"], points["C"])
        points["E"] = midpoint(points["B"], points["C"])
        segments.append(("D", "E"))
    elif number == 13:
        base, inner, area = p
        points = {"A": (0, 0), "B": (base * 0.4, 2 * area / base), "C": (base, 0)}
        points["M"] = interpolate(points["B"], points["A"], inner / base)
        points["N"] = interpolate(points["B"], points["C"], inner / base)
        segments.append(("M", "N"))
    elif number in (14, 15, 16, 17, 18, 19):
        if number == 14:
            a, b = p[:2]
        elif number == 15:
            a, b = p[:2]  # AC, BC; third parameter selects cos/sin/tan.
        elif number == 16:
            a, b = sqrt(p[0] ** 2 - p[1] ** 2), p[1]  # AB, BC given via sin A.
        elif number == 17:
            a, b = p[0], p[0] * p[1] / p[2]
        elif number == 18:
            a, b = 10 * cos(radians(p[0])), 10 * sin(radians(p[0]))
        else:
            a, b = p
        points = {"A": (a, 0), "B": (0, b), "C": (0, 0)}
        right.append(("A", "C", "B"))
        if number in (14, 18, 19):
            labels = []  # Source diagrams carry no vertex letters.
    elif number == 20:
        base, height = p
        points = {"A": (0, 0), "B": (base * 0.4, height), "C": (base, 0), "H": (base * 0.4, 0)}
        segments.append(("B", "H"))
        right.append(("B", "H", "C"))
        labels = []
    elif number == 21:
        a, b, numerator, denominator = p
        sine = numerator / denominator
        points = {"B": (0, 0), "A": (a, 0), "C": (b * sqrt(1 - sine * sine), b * sine)}
    elif number == 22:
        k, n, d = p
        ac = k * d
        points = {"A": (0, 0), "C": (ac, 0), "B": (ac, ac * sqrt(d * d - n * n) / n)}
        u = sub(points["B"], points["A"])
        ratio = dot(sub(points["C"], points["A"]), u) / dot(u, u)
        points["H"] = interpolate(points["A"], points["B"], ratio)
        segments.append(("C", "H"))
        right.append(("C", "H", "B"))
    else:
        raise ValueError("Unknown triangle construction")
    labels += [name for name in points if name not in {"A", "B", "C", "X"}] if labels else []
    return {
        "points": points,
        "segments": segments,
        "right": right,
        "equal": equal,
        "bisectors": bisectors,
        "angle_arcs": angle_arcs,
        "labels": labels,
    }
