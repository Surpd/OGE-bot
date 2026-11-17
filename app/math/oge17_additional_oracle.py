"""Independent visible task and coordinate checks for additional constructions."""

import math
import re
from fractions import Fraction
from typing import Any

from app.math.answer_policy import format_decimal


def audit(d: dict[str, Any], points: dict[str, tuple[float, float]]) -> Fraction:
    from app.math.oge17_oracle import angle, close, cross, dot, require, sub

    family, text = d["family_id"], d["condition"]
    a, b, c, e = (points[k] for k in "ABCD")
    require(close(cross(sub(b, a), sub(e, c)), 0), "Opposite sides not parallel")
    base_segments = ["AB", "BC", "CD", "DA"]
    expected_points = set("ABCD")
    marks: list[list[str]] = []
    p = d["exact_model"]["parameters"]
    if family == "OGE17-R04":
        m = re.fullmatch(
            r"Сторона ромба равна (\d+), а один из его углов равен 150°\. Найдите высоту ромба\.",
            text,
        )
        require(m is not None, "Rhombus height question")
        assert m is not None
        side = int(m[1])
        require(p == {"side": side} and side % 2 == 0 and 4 <= side <= 80, "Side domain")
        require(
            all(
                close(math.dist(points[x], points[y]), side)
                for x, y in zip("ABCD", "BCDA", strict=True)
            ),
            "Not a rhombus",
        )
        require(close(angle(sub(a, b), sub(c, b)), 150), "Wrong rhombus angle")
        foot = points["H"]
        require(
            close(cross(sub(foot, a), sub(e, a)), 0) and close(dot(sub(b, foot), sub(e, a)), 0),
            "Wrong height foot",
        )
        result = Fraction(str(math.dist(b, foot))).limit_denominator(2)
        require(
            close(float(result), math.dist(b, foot)) and result == Fraction(side, 2), "Wrong height"
        )
        expected_points.add("H")
        base_segments += ["BH"]
        marks = [["B", "H", "D"]]
        solution = [
            "Острый угол: 180° − 150° = 30°.",
            f"Высота равна {side} · sin 30° = {format_decimal(result)}.",
        ]
    elif family == "OGE17-E01":
        m = re.fullmatch(
            r"Диагональ прямоугольника образует угол (\d+)° с одной из его сторон\. "
            r"Найдите острый угол между диагоналями\. Ответ дайте в градусах\.",
            text,
        )
        require(m is not None, "Rectangle diagonal angle question")
        assert m is not None
        alpha = int(m[1])
        require(p == {"angle": alpha} and 20 <= alpha <= 70 and alpha != 45, "Angle domain")
        for x, y, z in [(a, b, c), (b, c, e), (c, e, a), (e, a, b)]:
            require(close(dot(sub(x, y), sub(z, y)), 0), "Not a rectangle")
        require(close(angle(sub(e, b), sub(a, b)), alpha), "Wrong diagonal to side angle")
        diagonal_angle = angle(sub(c, a), sub(e, b))
        result = Fraction(round(min(diagonal_angle, 180 - diagonal_angle)))
        require(
            close(float(result), min(diagonal_angle, 180 - diagonal_angle)),
            "Noninteger diagonal angle",
        )
        o = points["O"]
        require(
            all(close(2 * o[i], a[i] + c[i]) and close(2 * o[i], b[i] + e[i]) for i in (0, 1)),
            "Wrong diagonal intersection",
        )
        expected_points.add("O")
        base_segments += ["AC", "BD"]
        solution = [
            f"Углы между диагоналями равны {2 * alpha}° и {180 - 2 * alpha}°.",
            f"Острый угол равен {result}°.",
        ]
    elif family == "OGE17-E02":
        m = re.fullmatch(r"Сторона квадрата равна (\d+)√2\. Найдите диагональ квадрата\.", text)
        require(m is not None, "Square diagonal question")
        assert m is not None
        k = int(m[1])
        require(p == {"coefficient": k} and 2 <= k <= 60, "Square domain")
        for x, y, z in [(a, b, c), (b, c, e), (c, e, a), (e, a, b)]:
            require(
                close(math.dist(x, y) ** 2, 2 * k * k) and close(dot(sub(x, y), sub(z, y)), 0),
                "Not the stated square",
            )
        result = Fraction(round(math.dist(a, c)))
        require(close(float(result), math.dist(a, c)), "Square diagonal not exact integer")
        base_segments += ["AC"]
        solution = [f"Диагональ: {k}√2 · √2 = {result}."]
    elif family == "OGE17-P03":
        m = re.fullmatch(
            r"Площадь параллелограмма ABCD равна (\d+)\. Точка E — середина стороны CD\. "
            r"Найдите площадь трапеции AECB\.",
            text,
        )
        require(m is not None, "Partition area question")
        assert m is not None
        total = int(m[1])
        require(
            4 <= p["base"] <= 30 and 8 <= p["height"] <= 2 * p["base"] and p["height"] % 4 == 0,
            "Partition proportions",
        )
        require(p["base"] * p["height"] == total, "Visible total area")
        require(close(abs(cross(sub(b, a), sub(e, a))), total), "Wrong total area")
        midpoint = points["E"]
        require(all(close(2 * midpoint[i], c[i] + e[i]) for i in (0, 1)), "Not side midpoint")
        poly = [a, midpoint, c, b]
        area = abs(sum(cross(poly[i], poly[(i + 1) % 4]) for i in range(4))) / 2
        result = Fraction(str(area))
        require(result == Fraction(3 * total, 4), "Wrong partition area")
        expected_points.add("E")
        base_segments += ["AE"]
        solution = [
            f"S(ADE) = {total} / 4 = {total // 4}.",
            f"S(AECB) = {total} − {total // 4} = {result}.",
        ]
    else:
        raise ValueError("Unknown additional family")
    require(
        set(points) == expected_points and d["segments"] == base_segments, "Unexpected construction"
    )
    require(d["right_angles"] == marks and d["length_labels"] == {}, "Wrong annotations")
    require(
        d["solution"] == solution and d["correct_answer"] == format_decimal(result),
        "Wrong solution/answer",
    )
    require(0 < result <= 10000 and result.denominator in (1, 2), "Answer bounds")
    return result
