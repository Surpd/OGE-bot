"""Constructive extensions sharing the original Pillow scene contract."""

import math
import random
from fractions import Fraction
from typing import Any

from app.math.answer_policy import format_decimal

FAMILIES = ("OGE17-R04", "OGE17-E01", "OGE17-E02", "OGE17-P03")


def parameters(family: str, rng: random.Random) -> dict[str, int]:
    if family == "OGE17-R04":
        return {"side": 2 * rng.randint(2, 40)}
    if family == "OGE17-E01":
        return {"angle": rng.choice([a for a in range(20, 71) if a != 45])}
    if family == "OGE17-E02":
        return {"coefficient": rng.randint(2, 60)}
    if family == "OGE17-P03":
        base = rng.randint(4, 30)
        return {"base": base, "height": 4 * rng.randint(2, min(12, base // 2))}
    raise ValueError("Unknown additional family")


def build(family: str, p: dict[str, int]) -> dict[str, Any]:
    segments = ["AB", "BC", "CD", "DA"]
    marks: list[list[str]] = []
    if family == "OGE17-R04":
        side = p["side"]
        x, h = side * math.sqrt(3) / 2, side / 2
        points = {"A": (0, 0), "B": (x, h), "C": (x + side, h), "D": (side, 0), "H": (x, 0)}
        segments += ["BH"]
        marks = [["B", "H", "D"]]
        condition = (
            f"Сторона ромба равна {side}, а один из его углов равен 150°. Найдите высоту ромба."
        )
        answer = Fraction(side, 2)
        hints = ["Острый угол ромба равен 30°. Рассмотрите прямоугольный треугольник с высотой."]
        solution = [
            "Острый угол: 180° − 150° = 30°.",
            f"Высота равна {side} · sin 30° = {format_decimal(answer)}.",
        ]
    elif family == "OGE17-E01":
        alpha = p["angle"]
        h, w = 10.0, 10 * math.tan(math.radians(alpha))
        points = {"A": (0, 0), "B": (0, h), "C": (w, h), "D": (w, 0), "O": (w / 2, h / 2)}
        segments += ["AC", "BD"]
        condition = (
            f"Диагональ прямоугольника образует угол {alpha}° с одной из его сторон. "
            "Найдите острый угол между диагоналями. Ответ дайте в градусах."
        )
        answer = Fraction(min(2 * alpha, 180 - 2 * alpha))
        hints = ["Диагонали образуют две пары равных углов. Требуется острый угол."]
        solution = [
            f"Углы между диагоналями равны {2 * alpha}° и {180 - 2 * alpha}°.",
            f"Острый угол равен {answer}°.",
        ]
    elif family == "OGE17-E02":
        coefficient = p["coefficient"]
        square_side = coefficient * math.sqrt(2)
        points = {
            "A": (0, 0),
            "B": (0, square_side),
            "C": (square_side, square_side),
            "D": (square_side, 0),
        }
        segments += ["AC"]
        condition = f"Сторона квадрата равна {coefficient}√2. Найдите диагональ квадрата."
        answer = Fraction(2 * coefficient)
        hints = ["Диагональ квадрата в √2 раза больше его стороны."]
        solution = [f"Диагональ: {coefficient}√2 · √2 = {answer}."]
    elif family == "OGE17-P03":
        base, height = p["base"], p["height"]
        points = {
            "A": (0, 0),
            "B": (3, height),
            "C": (base + 3, height),
            "D": (base, 0),
            "E": (base + 1.5, height / 2),
        }
        segments += ["AE"]
        condition = (
            f"Площадь параллелограмма ABCD равна {base * height}. "
            "Точка E — середина стороны CD. Найдите площадь трапеции AECB."
        )
        answer = Fraction(3 * base * height, 4)
        hints = ["Треугольник ADE занимает четверть площади параллелограмма."]
        solution = [
            f"S(ADE) = {base * height} / 4 = {base * height // 4}.",
            f"S(AECB) = {base * height} − {base * height // 4} = {answer}.",
        ]
    else:
        raise ValueError("Unknown additional family")
    return {
        "exact_model": {"construction": family, "parameters": p},
        "points": points,
        "segments": segments,
        "right_angles": marks,
        "length_labels": {},
        "condition": condition,
        "hints": hints,
        "solution": solution,
        "correct_answer": format_decimal(answer),
    }
