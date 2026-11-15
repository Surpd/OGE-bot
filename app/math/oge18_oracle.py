"""Independent exact coordinate oracle, with no generator imports."""

from fractions import Fraction
from math import isqrt

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


def answer_family(family: str, points: tuple[Point, ...]) -> Fraction:
    """Independent integer-coordinate oracle for the six audited grid structures."""
    if family == "OGE18-D05":
        if len(points) != 2 or points[0] == points[1]:
            raise ValueError("Distance requires two distinct points")
        if any(
            type(value) is not int or not 2 <= value <= 17 for point in points for value in point
        ):
            raise ValueError("Point outside grid bounds")
        square = sum((a - b) ** 2 for a, b in zip(points[0], points[1], strict=True))
        root = isqrt(square)
        if root * root != square:
            raise ValueError("Distance is not an exact integer")
        return Fraction(root)
    if family == "OGE18-L02":
        if len(points) != 3:
            raise ValueError("Right triangle requires three vertices")
        if any(type(v) is not int or not 2 <= v <= 17 for point in points for v in point):
            raise ValueError("Vertex outside grid bounds")
        for i in range(3):
            vertex, a, c = points[i], points[(i + 1) % 3], points[(i + 2) % 3]
            u = (a[0] - vertex[0], a[1] - vertex[1])
            v = (c[0] - vertex[0], c[1] - vertex[1])
            if u[0] * v[0] + u[1] * v[1] == 0:
                aa, bb = u[0] ** 2 + u[1] ** 2, v[0] ** 2 + v[1] ** 2
                hyp = (a[0] - c[0]) ** 2 + (a[1] - c[1]) ** 2
                if aa != bb and isqrt(aa) ** 2 == aa and isqrt(bb) ** 2 == bb and hyp == aa + bb:
                    return Fraction(max(isqrt(aa), isqrt(bb)))
        raise ValueError("No unique larger perpendicular integer leg")
    if family not in {"OGE18-A01", "OGE18-A03", "OGE18-A04", "OGE18-A05"}:
        raise ValueError("Unknown family")
    if len(points) != (3 if family == "OGE18-A03" else 4):
        raise ValueError("Wrong polygon vertex count")
    if any(type(v) is not int or not 2 <= v <= 17 for point in points for v in point):
        raise ValueError("Vertex outside grid bounds")
    edges = [
        (b[0] - a[0], b[1] - a[1]) for a, b in zip(points, (*points[1:], points[0]), strict=True)
    ]
    turns = [u[0] * v[1] - u[1] * v[0] for u, v in zip(edges, (*edges[1:], edges[0]), strict=True)]
    if not (all(turn > 0 for turn in turns) or all(turn < 0 for turn in turns)):
        raise ValueError("Polygon must be strictly convex and correctly ordered")
    area2 = abs(
        sum(
            a[0] * b[1] - a[1] * b[0] for a, b in zip(points, (*points[1:], points[0]), strict=True)
        )
    )
    if area2 == 0:
        raise ValueError("Degenerate polygon")
    if family == "OGE18-A03":
        a, b, c = points
        horizontal = a[1] == c[1] and min(a[0], c[0]) < b[0] < max(a[0], c[0])
        if not horizontal or 2 * min(abs(b[0] - a[0]), abs(c[0] - b[0])) < abs(b[1] - a[1]):
            raise ValueError("Triangle angle is below readable-model threshold")
        cross = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
        if cross != area2:
            raise ValueError("Triangle determinant and shoelace disagree")
        return Fraction(area2, 2)
    a, b, c, d = points
    if family == "OGE18-A01":
        if not (a[1] == d[1] and b[1] == c[1] and a[1] != b[1]):
            raise ValueError("Invalid trapezoid bases")
        lower, upper = d[0] - a[0], c[0] - b[0]
        if lower <= 0 or upper <= 0:
            raise ValueError("Invalid base lengths")
        expected = Fraction((lower + upper) * abs(a[1] - b[1]), 2)
        if expected != Fraction(area2, 2):
            raise ValueError("Trapezoid formula and shoelace disagree")
        return expected
    if family == "OGE18-A04":
        if (a[0] + c[0], a[1] + c[1]) != (b[0] + d[0], b[1] + d[1]):
            raise ValueError("Not a parallelogram")
        cross = abs((b[0] - a[0]) * (d[1] - a[1]) - (b[1] - a[1]) * (d[0] - a[0]))
        if 2 * cross != area2:
            raise ValueError("Parallelogram cross product and shoelace disagree")
        return Fraction(area2, 2)
    sides = [
        (points[(i + 1) % 4][0] - points[i][0]) ** 2 + (points[(i + 1) % 4][1] - points[i][1]) ** 2
        for i in range(4)
    ]
    if len(set(sides)) != 1:
        raise ValueError("Not a rhombus")
    u = (c[0] - a[0], c[1] - a[1])
    v = (d[0] - b[0], d[1] - b[1])
    if (a[0] + c[0], a[1] + c[1]) != (b[0] + d[0], b[1] + d[1]):
        raise ValueError("Rhombus diagonals do not bisect each other")
    if u[0] * v[0] + u[1] * v[1] != 0:
        raise ValueError("Rhombus diagonals are not perpendicular")
    diagonal_product = (u[0] ** 2 + u[1] ** 2) * (v[0] ** 2 + v[1] ** 2)
    if diagonal_product != area2**2:
        raise ValueError("Rhombus diagonal formula and shoelace disagree")
    return Fraction(area2, 2)
