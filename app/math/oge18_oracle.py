"""Independent exact coordinate oracle, with no generator imports."""

from fractions import Fraction

Point = tuple[int, int]


def answer(points: tuple[Point, ...]) -> Fraction:
    if len(points) not in (3, 4):
        raise ValueError("Wrong polygon")
    if any(type(v) is not int or not 2 <= v <= 17 for p in points for v in p):
        raise ValueError("Non-grid or unsafe vertex")
    edges = [
        (b[0] - a[0], b[1] - a[1]) for a, b in zip(points, (*points[1:], points[0]), strict=True)
    ]
    turns = [u[0] * v[1] - u[1] * v[0] for u, v in zip(edges, (*edges[1:], edges[0]), strict=True)]
    if not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
        raise ValueError("Nonconvex or intersecting polygon")
    area2 = abs(
        sum(
            a[0] * b[1] - a[1] * b[0] for a, b in zip(points, (*points[1:], points[0]), strict=True)
        )
    )
    if area2 <= 0:
        raise ValueError("Degenerate polygon")
    a, b, c = points[:3]
    if len(points) == 3:
        if a[1] != c[1] or not a[0] < b[0] < c[0] or not 3 <= b[1] - a[1] <= 11:
            raise ValueError("Unsupported triangle")
        base = c[0] - a[0]
        if base not in (4, 6, 8, 10, 12, 14):
            raise ValueError("Unsupported base")
        ends = (a, c)
        mid1 = tuple(Fraction(x + y, 2) for x, y in zip(a, b, strict=True))
        mid2 = tuple(Fraction(x + y, 2) for x, y in zip(b, c, strict=True))
        expected = Fraction(base, 2)
    else:
        d = points[3]
        lower, upper = d[0] - a[0], c[0] - b[0]
        if (
            a[1] != d[1]
            or b[1] != c[1]
            or not 6 <= lower <= 12
            or not 2 <= upper <= lower - 2
            or not a[0] < b[0] < c[0] < d[0]
            or not 3 <= b[1] - a[1] <= 8
        ):
            raise ValueError("Unsupported trapezoid")
        ends = (a, d)
        mid1 = tuple(Fraction(x + y, 2) for x, y in zip(a, b, strict=True))
        mid2 = tuple(Fraction(x + y, 2) for x, y in zip(c, d, strict=True))
        expected = Fraction(lower + upper, 2)
    dx, dy = mid2[0] - mid1[0], mid2[1] - mid1[1]
    base_dx, base_dy = ends[1][0] - ends[0][0], ends[1][1] - ends[0][1]
    if dx * base_dy != dy * base_dx or dx * dx + dy * dy != expected * expected:
        raise ValueError("Midpoint oracle mismatch")
    return expected
