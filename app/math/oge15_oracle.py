"""Independent exact invariants for text-only triangle problems."""

from fractions import Fraction
from math import isqrt


def answer(family: str, parameters: tuple[int, ...]) -> Fraction:
    if any(type(p) is not int or p <= 0 for p in parameters):
        raise ValueError("Positive integer parameters required")
    if family == "OGE15-F01":
        a, b = parameters
        c = 180 - sum(parameters)
        if min(a, b, c) <= 0 or sum((a, b, c)) != 180:
            raise ValueError("Invalid triangle angles")
        return Fraction(c)
    if family == "OGE15-F03":
        (gamma,) = parameters
        if gamma >= 180:
            raise ValueError("Invalid interior angle")
        # Two other positive angles witness a nondegenerate triangle.
        other = Fraction(180 - gamma, 2)
        if gamma + 2 * other != 180 or other <= 0:
            raise ValueError("No triangle")
        return 2 * other
    if family == "OGE15-F11":
        ab, bc, ac = parameters
        if 2 * max(parameters) >= sum(parameters):
            raise ValueError("Triangle inequality")
        # B=(0,0), A=u, C=v. M=u/2, N=v/2: N-M=(v-u)/2.
        # Gram determinant witnesses independent, noncollinear side vectors.
        dot = Fraction(ab * ab + bc * bc - ac * ac, 2)
        if ab * ab * bc * bc - dot * dot <= 0:
            raise ValueError("Degenerate midpoint geometry")
        mn_squared = Fraction(ab * ab + bc * bc, 4) - dot / 2
        if mn_squared != Fraction(ac * ac, 4):
            raise ValueError("Invalid midline")
        return Fraction(ac, 2)
    if family in {"OGE15-F14", "OGE15-F19", "OGE15-F20"}:
        a, b = parameters
        # A=(0,0), C=(a,0), B=(offset,b); dot((a,0),(0,b))=0.
        offset = a // 2 if family == "OGE15-F20" else 0
        determinant = a * b - 0 * offset
        if family != "OGE15-F14":
            return Fraction(abs(determinant), 2)
        squared = a * a + b * b
        root = isqrt(squared)
        if root * root != squared:
            raise ValueError("Nonintegral hypotenuse")
        return Fraction(root)
    raise ValueError("Unknown triangle family")
