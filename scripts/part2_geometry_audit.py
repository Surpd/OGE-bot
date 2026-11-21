"""Offline exact check of the numerical geometry answers in the static atlas.

The models below use the givens from the statement without using the
illustration or the reference solution. Dependencies match part2_algebra_audit.
"""

import json
import re
from collections import Counter

from part2_algebra_audit import ATLAS, expression, formulas
from sympy import Rational as Q
from sympy import asin, cos, pi, simplify, sin, sqrt


def geometric_result(subtype, givens, statement):
    if subtype == "right-projection" and "площадь треугольника" in statement:
        segment, hyp = givens
        return sqrt(segment * hyp) * sqrt((hyp - segment) * hyp) / 2
    if subtype == "right-bisectors" and "площадь треугольника" in statement:
        hyp, difference = givens
        return (hyp**2 - difference**2) / 4
    if subtype == "right-circle-rectangle" and "BP =" in statement:
        hyp, projection = givens
        return sqrt(hyp * projection)
    if subtype == "parallel-segment" and "четырёхугольника" in statement:
        small, whole = givens
        return (whole / small) ** 2 - 1
    if subtype == "parallel-diagonals" and "площади" in statement:
        am, mc = givens
        return (mc / am) ** 2
    if subtype == "trapezoid-trig" and "разность AD" in statement:
        B, C, leg = givens
        h = leg * sin(pi * C / 180)
        return -leg * cos(pi * C / 180) - h * cos(pi * B / 180) / sin(pi * B / 180)
    if subtype == "trapezoid-bisector-area" and "Найдите CD" in statement:
        base, height, area = givens
        return 2 * area / height
    if subtype == "trapezoid-midpoint-segments" and "площади" in statement:
        _, _, half_sum, half_diff = givens
        ratio = (half_sum - half_diff) / (half_sum + half_diff)
        return ratio**2 / (1 - ratio**2)
    if subtype == "parallelogram-bisectors" and "Периметр" in statement:
        perimeter, ab, area = givens
        return area / (perimeter - 2 * ab)
    if subtype == "tangent-trapezoid" and "радиуса" in statement:
        radius, low, high = givens
        # For a tangential isosceles trapezoid the product of the bases is h².
        small = 2 * radius * sqrt(low / high)
        large = 2 * radius * sqrt(high / low)
        return radius * (small + large)
    if subtype == "incenter-distance" and "Найдите AO" in statement:
        area, d, r = givens
        tangent = area / (2 * r) - area / (d + r)
        return sqrt(tangent**2 + r**2)
    if subtype == "circumcenter-chord" and "Найдите AB" in statement:
        ac, cd = givens
        return sqrt(ac * (ac - cd))
    if subtype == "secant-tangent" and "большего основания" in statement:
        difference, squared = givens
        return (difference + sqrt(difference**2 + 4 * squared)) / 2
    if subtype == "two-circle-tangents" and "меньший радиус" in statement:
        centers, chords = givens
        return (centers - sqrt(centers * (centers - chords))) / 2
    if subtype == "orthocenter-semicircle" and "Найдите MD" in statement:
        ad, ah = givens
        return sqrt(ad * (ad - ah))
    if subtype == "median-bisector" and "Квадрат длины" in statement:
        (ab_squared,) = givens
        return 12 * ab_squared / 13
    if subtype == "angle-height-bisector":
        if "больше угла C" in statement:
            return givens[0] - 2 * givens[1]
        return abs(givens[0] - givens[1]) / 2
    if subtype == "angle-tangent-arc":
        return abs(90 - givens[0])
    if subtype == "right-bisectors":
        return sqrt(givens[0] ** 2 + givens[1] ** 2)
    if subtype == "right-circle-rectangle":
        return givens[0]
    if subtype == "right-projection":
        return sqrt(givens[0] * givens[1])
    if subtype == "right-median":
        if "относятся" in statement:
            a, b, total = givens
            c = sqrt(a * a + b * b)
            return total * c / (2 * (a + b + c))
        a, b = givens
        if "гипотенузе равна" in statement:
            return sqrt((2 * a) ** 2 - b * b)
        if "Площадь" in statement:
            return sqrt(b * b + (2 * a / b) ** 2) / 2
        return sqrt(a * a + b * b) / 2
    # Similar triangles on parallel sections determine the oriented side ratio.
    if subtype == "parallel-segment":
        mn, ac, nc = givens
        return mn * nc / (ac - mn)
    if subtype == "parallel-diagonals":
        ab, dc, ac = givens
        return ac * dc / (ab + dc)
    if subtype == "trapezoid-area":
        if "Проекция боковой стороны" in statement:
            base, leg, run = givens
            return (base + run) * sqrt(leg**2 - run**2)
        a, b, P = givens
        leg = (P - a - b) / 2
        return (a + b) / 2 * sqrt(leg * leg - ((a - b) / 2) ** 2)
    if subtype == "trapezoid-midpoints":
        return (
            givens[0] + 2 * givens[1]
            if "большее основание" in statement
            else abs(givens[0] - givens[1]) / 2
        )
    # Reflect the bisector through the leg midpoint: the two bases sum to CD.
    if subtype == "trapezoid-bisector-area":
        ab, cd, bc = givens
        delta = cd - 2 * bc
        run = (ab**2 - cd**2 + delta**2) / (2 * delta)
        return cd / 2 * sqrt(ab**2 - run**2)
    if subtype == "trapezoid-parallel-section" and len(givens) == 4:
        ad, bc, u, v = givens
        return bc + (ad - bc) * u / (u + v)
    if subtype == "tangent-trapezoid":
        P, S = givens
        h = 4 * S / P
        sm = P / 2
        return h * (1 - sqrt(1 - 4 * h**2 / sm**2)) / 2
    if subtype == "parallelogram-bisectors" and "расстояние от K до прямой AB" in statement:
        return 2 * givens[0] * givens[1]
    if subtype == "incircle-excircle" and len(givens) == 2:
        return givens[0] ** 2 / (4 * givens[1])
    # Tangent length from A is sqrt(AO²-r²); h=distance(O,AD)+r and S=r·s.
    if subtype == "incenter-distance":
        ao, d, r = givens
        return 2 * r * sqrt(ao * ao - r * r) * (d + r) / (d - r)
    if subtype == "cyclic-diagonals" and len(givens) == 3 and givens[2] == 60:
        a, b, _ = givens
        return sqrt((a * a + a * b + b * b) / 3)
    if subtype == "circumcenter-chord":
        return givens[1] - givens[0] ** 2 / givens[1]
    if subtype == "secant-tangent":
        return sqrt(givens[0] * givens[1])
    if subtype == "two-circle-tangents":
        r, R = givens
        return 4 * r * R / (r + R)
    if subtype == "orthocenter-semicircle":
        h, d = givens
        return h - d * d / h
    # Place the perpendicular median and bisector on coordinate axes. The
    # bisector theorem gives AG=GD=L/2, BG=3L/4, where G is their intersection.
    if subtype == "median-bisector":
        return [givens[0] * sqrt(13) / 4, givens[0] * sqrt(13) / 2, 3 * givens[0] * sqrt(5) / 4]

    if subtype == "rhombus":
        a, b = givens
        if "стороны равно" in statement:
            alpha = 360 * asin(2 * a / b) / pi
            return [alpha, 180 - alpha]
        return sqrt((a + b) ** 2 - a**2)
    if subtype == "parallelogram-bisectors":
        if "периметр" in statement:
            return 2 * (2 * givens[0] + givens[1])
        if "углов A и B" in statement:
            return 2 * givens[0] * givens[1]
        return givens[0] * (givens[0] + givens[1]) * sin(pi * givens[2] / 180)
    if subtype == "trapezoid-trig":
        a, b, cd = givens
        return cd * sin(pi * b / 180) / sin(pi * a / 180)
    if subtype == "sine-rule":
        a, b = givens[:2]
        s = sin((180 - a - b) * pi / 180)
        if "Найдите BC" in statement:
            return 2 * s * givens[2]
        side = expression(formulas(statement)[-1].split("=")[-1])
        return side / (2 * s)
    if subtype == "trapezoid-midpoint-segments":
        a, b = sorted(givens[-2:], reverse=True)
        return [a - b, a + b]
    if subtype == "incircle-excircle":
        r = expression(formulas(statement)[0])
        return 2 * sqrt(r * givens[-1])
    if subtype == "incircle-similarity":
        r, u, v = givens
        scale = u / sqrt(u * u + v * v)
        return r * scale if "радиус вписанной окружности BCP" in statement else r / scale
    if subtype == "cyclic-diagonals":
        a, b = givens
        return a * a / b - b
    if subtype == "circumradius-hidden":
        if "четырёхугольнике" in statement:
            bc, B, C = givens
            return -bc / cos(pi * (B + C) / 180)
        u, v, bc = givens
        return bc * u / (2 * sqrt(u * u - v * v))
    # Set A=(0,0), B=(0,1), C=(2,0), K=(z,1-z). Determinants give S(BKP)/S(BMC).
    if subtype == "median-area":
        u, v = givens
        z = u / (u + v)
        fraction = z * z / (2 - z)
        return 1 - fraction if "Какую долю" in statement else fraction / (1 - fraction)
    if subtype == "trapezoid-parallel-section":
        a, b = givens
        w = 2 * a * b / (a + b)
        return a * (a + w) / (b * (w + b))


def main():
    checked = Counter()
    for line in ATLAS.read_text().splitlines():
        card = json.loads(line)
        if card["number"] not in {23, 25}:
            continue
        statement = card["statement"]
        givens = [Q(v.replace(",", ".")) for v in re.findall(r"\d+(?:[.,]\d+)?", statement)]
        result = geometric_result(card["subtype_id"].split("-", 1)[1], givens, statement)
        if result is None:
            raise ValueError(f"Unsupported problem: {card['task_id']}")
        tex = (formulas(card["answer_or_claim"]) or [card["answer_or_claim"]])[0]
        tex = tex.replace(r"^\circ", "").replace("°", "")
        actual = result if isinstance(result, list) else [result]
        expected = [expression(v.replace(":", "/")) for v in tex.split(",")]
        if len(actual) != len(expected) or any(
            simplify(a - b) != 0 for a, b in zip(actual, expected, strict=True)
        ):
            raise ValueError(f"{card['task_id']}: geometry gives {actual}, atlas {expected}")
        checked[card["number"]] += 1
    print(f"Verified numerical geometry answers: {dict(checked)}")


if __name__ == "__main__":
    main()
