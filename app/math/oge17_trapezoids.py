"""Source-specific trapezoid constructions; shared scene, distinct question targets."""

import math
import random
from fractions import Fraction
from typing import Any

from app.math.answer_policy import format_decimal

FAMILIES = ("OGE17-T02", "OGE17-T05", "OGE17-T07", "OGE17-T08")


def parameters(family: str, rng: random.Random) -> dict[str, int]:
    if family == "OGE17-T05":
        upper = rng.randint(3, 20)
        return {"upper": upper, "lower": upper + rng.randint(4, 20), "height": rng.randint(8, 20)}
    return {"angle": rng.randint(35, 80)}


def build(family: str, p: dict[str, int]) -> dict[str, Any]:
    points: dict[str, tuple[float, float]]
    marks: list[list[str]] = []
    segments = ["AB", "BC", "CD", "DA"]
    if family == "OGE17-T05":
        upper, lower, height = (p[k] for k in ("upper", "lower", "height"))
        x = (lower - upper) / 3
        points = {"A": (0, 0), "B": (x, height), "C": (x + upper, height), "D": (lower, 0)}
        points.update(M=(x / 2, height / 2), N=((x + upper + lower) / 2, height / 2))
        points["H"] = (x, 0)
        segments += ["MN", "BH"]
        marks = [["B", "H", "D"]]
        text = (
            f"Основания трапеции ABCD равны {upper} и {lower}, а высота равна {height}."
            f" Найдите среднюю линию MN этой трапеции."
        )
        answer = Fraction(upper + lower, 2)
        hints = ["Средняя линия соединяет середины боковых сторон и равна полусумме оснований."]
        solution = [f"MN = ({upper} + {lower}) / 2 = {format_decimal(answer)}."]
    else:
        alpha = p["angle"]
        trapheight = 10.0
        projection = trapheight / math.tan(math.radians(alpha))
        upper = 10
        right = family == "OGE17-T08"
        x = 0.0 if right else projection
        traplower = upper + projection + x
        points = {
            "A": (0, 0),
            "B": (x, trapheight),
            "C": (x + upper, trapheight),
            "D": (traplower, 0),
        }
        if family == "OGE17-T02":
            text = (
                f"Сумма двух углов равнобедренной трапеции равна {2 * alpha}°."
                f" Найдите больший угол трапеции. Ответ дайте в градусах."
            )
            hints = [
                "Сумма односторонних углов равна 180°."
                " В условии сложены два равных угла при основании."
            ]
            solution = [
                f"Меньший угол равен {2 * alpha}° / 2 = {alpha}°.",
                f"Больший угол: 180° − {alpha}° = {180 - alpha}°.",
            ]
        else:
            shape = "прямоугольной" if right else "равнобедренной"
            text = (
                f"Один из углов {shape} трапеции равен {alpha}°."
                f" Найдите больший угол этой трапеции. Ответ дайте в градусах."
            )
            hints = ["Два угла, прилежащие к одной боковой стороне трапеции, дают в сумме 180°."]
            solution = [f"Больший угол: 180° − {alpha}° = {180 - alpha}°."]
        answer = Fraction(180 - alpha)
    return {
        "exact_model": {"construction": family, "parameters": p},
        "points": points,
        "segments": segments,
        "right_angles": marks,
        "length_labels": {},
        "condition": text,
        "correct_answer": format_decimal(answer),
        "hints": hints,
        "solution": solution,
    }
