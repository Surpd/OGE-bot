"""Trapezoid oracle reads the stated values and measures the actual configuration."""

import math
import re
from fractions import Fraction
from typing import Any

from app.math.answer_policy import format_decimal


def audit(d: dict[str, Any], points: dict[str, tuple[float, float]]) -> Fraction:
    from app.math.oge17_oracle import angle, close, cross, dot, require, sub

    a, b, c, e = (points[k] for k in "ABCD")
    family, text, p = d["family_id"], d["condition"], d["exact_model"]["parameters"]
    segments = ["AB", "BC", "CD", "DA"]
    expected_points = set("ABCD")
    marks: list[list[str]] = []
    if family == "OGE17-T05":
        m = re.fullmatch(
            r"Основания трапеции ABCD равны (\d+) и (\d+), а высота равна (\d+)\."
            r" Найдите среднюю линию MN этой трапеции\.",
            text,
        )
        require(m is not None, "Midline question structure")
        assert m is not None
        upper, lower, height = (int(m[i]) for i in (1, 2, 3))
        require(p == {"upper": upper, "lower": lower, "height": height}, "Visible trapezoid data")
        require(
            3 <= upper <= 20 and 4 <= lower - upper <= 20 and 5 <= height <= 20, "Midline domain"
        )
        require(close(math.dist(b, c), upper) and close(math.dist(a, e), lower), "Wrong bases")
        require(close(abs(b[1] - a[1]), height), "Wrong height")
        mid, end = points["M"], points["N"]
        require(
            all(close(2 * mid[i], a[i] + b[i]) and close(2 * end[i], c[i] + e[i]) for i in (0, 1)),
            "Wrong side midpoints",
        )
        result = Fraction(upper + lower, 2)
        require(close(math.dist(mid, end), float(result)), "Incorrect midline length")
        solution = [f"MN = ({upper} + {lower}) / 2 = {format_decimal(result)}."]
        foot = points["H"]
        require(
            close(cross(sub(foot, a), sub(e, a)), 0)
            and close(dot(sub(b, foot), sub(e, a)), 0)
            and close(math.dist(b, foot), height),
            "Wrong drawn height",
        )
        segments += ["MN", "BH"]
        expected_points.update("MNH")
        marks = [["B", "H", "D"]]
    else:
        if family == "OGE17-T02":
            m = re.fullmatch(
                r"Сумма двух углов равнобедренной трапеции равна (\d+)°\."
                r" Найдите больший угол трапеции\. Ответ дайте в градусах\.",
                text,
            )
            require(m is not None, "Angle sum question")
            assert m is not None
            total = int(m[1])
            require(total % 2 == 0 and total != 180, "Ambiguous angle sum")
            alpha = total // 2
        else:
            shape = "прямоугольной" if family == "OGE17-T08" else "равнобедренной"
            m = re.fullmatch(
                rf"Один из углов {shape} трапеции равен (\d+)°\."
                rf" Найдите больший угол этой трапеции\. Ответ дайте в градусах\.",
                text,
            )
            require(m is not None, "Trapezoid larger angle question")
            assert m is not None
            alpha = int(m[1])
        require(p == {"angle": alpha} and 35 <= alpha <= 80, "Trapezoid angle bounds")
        vertices = [a, b, c, e]
        angles = [
            angle(sub(vertices[(i - 1) % 4], v), sub(vertices[(i + 1) % 4], v))
            for i, v in enumerate(vertices)
        ]
        if family == "OGE17-T08":
            require(sum(close(x, 90) for x in angles) == 2, "Not a right trapezoid")
        else:
            require(
                close(math.dist(a, b), math.dist(c, e))
                and close(angles[0], angles[3])
                and close(angles[1], angles[2]),
                "Not isosceles trapezoid",
            )
        require(close(min(angles), alpha), "Wrong drawn acute angle")
        result = Fraction(180 - alpha)
        require(close(max(angles), float(result)), "Wrong drawn larger angle")
        solution = (
            [f"Меньший угол равен {2 * alpha}° / 2 = {alpha}°."] if family == "OGE17-T02" else []
        ) + [f"Больший угол: 180° − {alpha}° = {180 - alpha}°."]
    require(
        set(points) == expected_points and d["segments"] == segments, "Wrong trapezoid construction"
    )
    require(d["right_angles"] == marks and d["length_labels"] == {}, "Unjustified annotations")
    require(
        d["correct_answer"] == format_decimal(result) and d["solution"] == solution,
        "Wrong trapezoid answer/solution",
    )
    return result
