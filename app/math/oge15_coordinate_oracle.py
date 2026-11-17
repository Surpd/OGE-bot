"""Independent coordinate checks for complete triangle scenes, tolerance 1e-8."""

from __future__ import annotations

from fractions import Fraction
from math import isclose, isfinite, sqrt
from typing import Any

from app.math.oge15_geometry import angle, cross, dot, length, midpoint, sub


def exact_answer_contract(n: int, p: tuple[int, ...], result: Fraction) -> None:
    """Algebraic identities are exact; coordinate tolerance must not round answers."""
    a = p[0]
    b = p[1] if len(p) > 1 else 0
    if result <= 0:
        raise ValueError("Nonpositive triangle answer")
    if n == 1:
        valid = result + a + b == 180
    elif n == 2:
        valid = 2 * result == a
    elif n == 3:
        valid = result + a == 180
    elif n in (4, 7, 18):
        valid = result + a == 90
    elif n == 5:
        valid = result + 2 * (180 - a) == 180
    elif n == 6:
        valid = 3 * result**2 == 4 * (3 * a * a)
    elif n == 8:
        valid = 4 * result == 3 * (4 * a)
    elif n == 9:
        valid = result + b == 180
    elif n == 10:
        valid = result + 3 * a == 180
    elif n == 11:
        valid = 2 * result == p[2]
    elif n == 12:
        valid = result == 4 * a
    elif n == 13:
        valid = result * a * a == p[2] * b * b
    elif n == 14:
        valid = result**2 == (b * b if len(p) > 2 and p[2] == 1 else a * a + b * b)
    elif n == 15:
        kind = p[2] if len(p) > 2 else 0
        valid = (
            (result * b == a)
            if kind == 2
            else (result**2 * (a * a + b * b) == (a * a if kind == 1 else b * b))
        )
    elif n == 16:
        valid = result * Fraction(b, a) == b
    elif n == 17:
        valid = result * p[2] == a * b
    elif n in (19, 20):
        valid = 2 * result == a * b
    elif n == 21:
        valid = 2 * result * p[3] == a * b * p[2]
    elif n == 22:
        valid = result * p[2] == p[1]
    else:
        raise ValueError("Unknown exact answer contract")
    if not valid:
        raise ValueError("Exact triangle answer invariant failed")


def validate(n: int, p: tuple[int, ...], scene: dict[str, Any], result: Fraction) -> None:
    pts = scene["points"]
    a, b, c = (pts[k] for k in "ABC")

    def close(x: float, y: float | Fraction) -> None:
        if not isclose(x, y, rel_tol=1e-8, abs_tol=1e-8):
            raise ValueError("Triangle coordinate invariant failed")

    def same(x: tuple[float, float], y: tuple[float, float]) -> None:
        close(x[0], y[0])
        close(x[1], y[1])

    def inside(name: str, start: str, end: str) -> None:
        point = pts[name]
        u = sub(pts[end], pts[start])
        v = sub(point, pts[start])
        close(cross(u, v), 0)
        t = dot(u, v) / dot(u, u)
        if not 0 < t < 1:
            raise ValueError("Construction point outside side")

    if any(not isfinite(x) for point in pts.values() for x in point):
        raise ValueError("Nonfinite coordinate")
    area = abs(cross(sub(b, a), sub(c, a))) / 2
    if area < 1e-6 or min(angle(b, a, c), angle(a, b, c), angle(a, c, b)) < 8:
        raise ValueError("Degenerate or unreadable triangle")
    ab, bc, ac = length(a, b), length(b, c), length(a, c)
    aa, bb, cc = angle(b, a, c), angle(a, b, c), angle(a, c, b)
    close(aa + bb + cc, 180)
    if n == 1:
        close(aa, p[0])
        close(bb, p[1])
        computed = cc
    elif n == 2:
        inside("D", "B", "C")
        close(angle(b, a, pts["D"]), angle(pts["D"], a, c))
        close(aa, p[0])
        close(cc, p[1])
        computed = angle(b, a, pts["D"])
    elif n in (3, 5):
        close(cross(sub(c, a), sub(pts["X"], c)), 0)
        if dot(sub(c, a), sub(pts["X"], c)) <= 0:
            raise ValueError("Wrong exterior ray")
        if n == 3:
            close(cc, p[0])
            computed = angle(b, c, pts["X"])
        else:
            close(ab, bc)
            close(aa, cc)
            close(angle(b, c, pts["X"]), p[0])
            computed = bb
    elif n == 4:
        inside("H", "A", "C")
        close(dot(sub(b, pts["H"]), sub(c, a)), 0)
        close(aa, p[0])
        computed = angle(a, b, pts["H"])
    elif n == 6:
        close(ab, bc)
        close(bc, ac)
        same(pts["H"], midpoint(a, c))
        close(dot(sub(b, pts["H"]), sub(c, a)), 0)
        close(length(b, pts["H"]) ** 2, 3 * p[0] ** 2)
        computed = ac
    elif n == 7:
        same(pts["M"], midpoint(a, c))
        close(length(b, pts["M"]), ac / 2)
        close(bb, 90)
        close(cc, p[0])
        computed = aa
    elif n in (8, 9):
        same(pts["M"], midpoint(a, c))
        inside("H", "M", "C")
        close(dot(sub(b, pts["H"]), sub(c, a)), 0)
        close(length(b, pts["M"]), bc)
        close(ac, 4 * p[0])
        if n == 8:
            computed = length(a, pts["H"])
        else:
            close(length(pts["H"], c), p[0])
            close(cc, p[1])
            computed = angle(a, pts["M"], b)
    elif n == 10:
        inside("K", "B", "C")
        close(length(a, pts["K"]), length(pts["K"], c))
        close(angle(b, a, pts["K"]), angle(pts["K"], a, c))
        close(cc, p[0])
        computed = bb
    elif n == 11:
        same(pts["M"], midpoint(a, b))
        same(pts["N"], midpoint(b, c))
        close(cross(sub(pts["N"], pts["M"]), sub(c, a)), 0)
        for x, y in zip((ab, bc, ac), p, strict=True):
            close(x, y)
        computed = length(pts["M"], pts["N"])
    elif n == 12:
        same(pts["D"], midpoint(a, c))
        same(pts["E"], midpoint(b, c))
        small = abs(cross(sub(pts["D"], c), sub(pts["E"], c))) / 2
        close(small, p[0])
        computed = area
    elif n == 13:
        inside("M", "A", "B")
        inside("N", "B", "C")
        close(cross(sub(pts["N"], pts["M"]), sub(c, a)), 0)
        close(ac, p[0])
        close(length(pts["M"], pts["N"]), p[1])
        close(area, p[2])
        computed = abs(cross(sub(pts["M"], b), sub(pts["N"], b))) / 2
    elif n in (14, 15, 16, 17, 18, 19):
        close(dot(sub(a, c), sub(b, c)), 0)
        close(ab * ab, ac * ac + bc * bc)
        if n == 14:
            close(ac, p[0])
            close(bc, p[1])
            computed = bc if len(p) > 2 and p[2] == 1 else ab
        elif n == 15:
            close(ac, p[0])
            close(bc, p[1])
            kind = p[2] if len(p) > 2 else 0
            computed = ac / bc if kind == 2 else ac / ab if kind == 1 else bc / ab
        elif n == 16:
            close(bc, p[1])
            close(bc / ab, Fraction(p[1], p[0]))
            computed = ab
        elif n == 17:
            close(ac, p[0])
            close(bc / ac, Fraction(p[1], p[2]))
            computed = bc
        elif n == 18:
            close(aa, p[0])
            computed = bb
        else:
            close(ac, p[0])
            close(bc, p[1])
            computed = area
    elif n == 20:
        inside("H", "A", "C")
        close(ac, p[0])
        close(length(b, pts["H"]), p[1])
        close(dot(sub(b, pts["H"]), sub(c, a)), 0)
        computed = area
    elif n == 21:
        close(ab, p[0])
        close(bc, p[1])
        sine = abs(cross(sub(a, b), sub(c, b))) / (ab * bc)
        close(sine, Fraction(p[2], p[3]))
        computed = area
    elif n == 22:
        inside("H", "A", "B")
        close(dot(sub(a, c), sub(b, c)), 0)
        close(dot(sub(c, pts["H"]), sub(b, a)), 0)
        close(ac, p[0] * p[2])
        close(length(c, pts["H"]) ** 2, p[0] ** 2 * (p[2] ** 2 - p[1] ** 2))
        computed = sqrt(ac * ac - length(c, pts["H"]) ** 2) / ac
        close(computed, ac / ab)
    else:
        raise ValueError("Unknown coordinate model")
    for start, vertex, end in scene["right"]:
        close(dot(sub(pts[start], pts[vertex]), sub(pts[end], pts[vertex])), 0)
    for group in scene["equal"]:
        distances = [length(pts[x], pts[y]) for x, y in group]
        for d in distances:
            close(d, distances[0])
    exact_answer_contract(n, p, result)
    close(computed, float(result))
