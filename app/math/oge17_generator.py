"""Closed experimental №17 generators, without Telegram, database or scheduling."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import random
from fractions import Fraction
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import format_decimal
from app.math.oge17_models import (
    FAMILIES,
    GENERATOR_VERSION,
    ORACLE_VERSION,
    POLICY,
    RENDERER_VERSION,
    SOURCES,
    QuadrilateralProblem,
)


def parameters(family: str, seed: int) -> dict[str, int]:
    rng = random.Random(f"{GENERATOR_VERSION}:{family}:{seed}")
    if family == FAMILIES[0]:
        return {"angle_b": rng.randint(40, 140), "side": 10}
    if family == FAMILIES[1]:
        half = rng.randint(8, 80)  # twice BO: half-integers, bounded short arithmetic
        return {"twice_bo": half, "ab": rng.randint(max(3, half // 3), half * 3 // 4)}
    if family == FAMILIES[2]:
        s, h, side = rng.choice(((3, 4, 5), (5, 12, 13), (8, 15, 17)))
        k = rng.randint(1, 5)
        return {
            "s": s * k,
            "t": rng.randint(4, min(35, 4 * h * k - 2 * s * k)),
            "h": h * k,
            "side": side * k,
        }
    if family == FAMILIES[3]:
        bd = rng.randint(12, 70)
        ac = rng.randint(max(10, bd * 17 // 20), bd * 23 // 20)
        ab = rng.randint(max(abs(ac - bd) // 2 + 2, min(ac, bd) // 3), min(ac, bd) // 2)
        return {"ac": ac, "bd": bd, "ab": ab}
    if family in FAMILIES[4:]:
        lower = rng.randint(9, 60)
        upper = rng.randint(max(2, lower // 4), lower - 3)
        return {
            "lower": lower,
            "upper": upper,
            "h": rng.randint(max(6, (lower + 3) // 4), 25),
            "offset": max(1, (lower - upper) // 3),
        }
    raise ValueError("Unknown family")


def build(family: str, p: dict[str, int]) -> dict[str, Any]:
    """Exact parameters define construction; floating coordinates are only its layout."""
    pts: dict[str, tuple[float, float]]
    exact: dict[str, Any]
    lines: list[str] = ["AB", "BC", "CD", "DA"]
    marks: list[list[str]] = []
    labels: dict[str, str] = {}
    if family == FAMILIES[0]:
        b, side = p["angle_b"], p["side"]
        vx, vy = -side * math.cos(math.radians(b)), side * math.sin(math.radians(b))
        pts = {"A": (0, 0), "B": (vx, vy), "C": (vx + side, vy), "D": (side, 0)}
        lines += ["AC"]
        condition = f"В ромбе ABCD угол ABC равен {b}°. Найдите угол ACD. Ответ дайте в градусах."
        result = Fraction(180 - b, 2)
        hints = [
            "Соседние углы ромба в сумме дают 180°.",
            "Диагональ ромба делит угол при своей вершине пополам.",
        ]
        solution = [
            f"∠BCD = 180° − {b}° = {180 - b}°.",
            f"∠ACD = {180 - b}° / 2 = {format_decimal(result)}°.",
        ]
        exact = {
            "construction": "u=(s,0); v=(-s*cos(B),s*sin(B)); A=0,B=v,C=u+v,D=u",
            "angle_unit": "degrees",
            "parameters": p,
        }
    elif family == FAMILIES[1]:
        d, ab = p["twice_bo"], p["ab"]
        width = math.sqrt(d * d - ab * ab)
        pts = {
            "A": (0, 0),
            "B": (0, ab),
            "C": (width, ab),
            "D": (width, 0),
            "O": (width / 2, ab / 2),
        }
        lines += ["AC", "BD"]
        condition = (
            "Диагонали AC и BD прямоугольника ABCD пересекаются в точке O, "
            f"BO = {format_decimal(Fraction(d, 2))}, AB = {ab}. Найдите AC."
        )
        result = Fraction(d)
        hints = ["Диагонали прямоугольника равны и делятся точкой пересечения пополам."]
        solution = [f"AC = BD = 2 · BO = 2 · {format_decimal(Fraction(d, 2))} = {d}."]
        exact = {
            "construction": "A=(0,0),B=(0,ab),C=(sqrt(d²-ab²),ab),D=(sqrt(d²-ab²),0)",
            "width_squared": d * d - ab * ab,
            "parameters": p,
        }
    elif family == FAMILIES[2]:
        s, t, h = p["s"], p["t"], p["h"]
        pts = {"A": (0, 0), "B": (s, h), "C": (2 * s + t, h), "D": (s + t, 0), "H": (s, 0)}
        lines += ["BH"]
        marks = [["B", "H", "D"]]
        labels = {"AH": str(s), "HD": str(t), "BH": str(h), "AB": str(p["side"])}
        condition = "Найдите площадь параллелограмма, изображённого на рисунке."
        result = Fraction((s + t) * h)
        hints = ["Сложите два отрезка основания, затем используйте высоту."]
        solution = [f"AD = {s} + {t} = {s + t}.", f"S = AD · BH = {s + t} · {h} = {result}."]
        exact = {"construction": "A=(0,0),B=(s,h),C=(2s+t,h),D=(s+t,0),H=(s,0)", "parameters": p}
    elif family == FAMILIES[3]:
        ac, bd, ab = p["ac"], p["bd"], p["ab"]
        # A=0, B=v, D=u. From |u+v|=AC, |u-v|=BD, |v|=AB.
        u2 = Fraction(ac * ac + bd * bd, 2) - ab * ab
        uv = Fraction(ac * ac - bd * bd, 4)
        u = math.sqrt(float(u2))
        x = float(uv) / u
        y = math.sqrt(ab * ab - x * x)
        pts = {
            "A": (0, 0),
            "B": (x, y),
            "C": (u + x, y),
            "D": (u, 0),
            "O": ((u + x) / 2, y / 2),
        }
        lines += ["AC", "BD"]
        condition = (
            "Диагонали AC и BD параллелограмма ABCD пересекаются в точке O, "
            f"AC = {ac}, BD = {bd}, AB = {ab}. Найдите DO."
        )
        result = Fraction(bd, 2)
        hints = ["Диагонали параллелограмма делятся точкой пересечения пополам."]
        solution = [f"DO = BD / 2 = {bd} / 2 = {format_decimal(result)}."]
        exact = {
            "construction": "A=0,B=v,C=u+v,D=u; O=(u+v)/2",
            "u_squared": str(u2),
            "v_squared": str(ab * ab),
            "u_dot_v": str(uv),
            "parameters": p,
        }
    elif family in FAMILIES[4:]:
        lower, upper, h, x = (p[k] for k in ("lower", "upper", "h", "offset"))
        pts = {"A": (0, 0), "B": (x, h), "C": (x + upper, h), "D": (lower, 0)}
        if family == FAMILIES[4]:
            pts.update(
                M=(x / 2, h / 2), N=((x + upper + lower) / 2, h / 2), K=((x + lower) / 2, h / 2)
            )
            lines += ["MN", "BD"]
            condition = (
                f"Основания трапеции ABCD равны {upper} и {lower}. "
                "MN — средняя линия, K — точка её пересечения с диагональю BD. "
                "Найдите больший из отрезков MK и KN."
            )
            result = Fraction(lower, 2)
            hints = ["Отрезки средней линии являются средними линиями двух треугольников."]
            solution = [
                f"MK = AD / 2 = {format_decimal(Fraction(lower, 2))}; "
                f"KN = BC / 2 = {format_decimal(Fraction(upper, 2))}.",
                f"Больший отрезок MK равен {format_decimal(result)}.",
            ]
        else:
            pts["H"] = (x, 0)
            lines += ["BH"]
            marks = [["B", "H", "D"]]
            condition = (
                f"Основания трапеции ABCD равны {upper} и {lower}, "
                f"а высота BH равна {h}. Найдите площадь этой трапеции."
            )
            result = Fraction((lower + upper) * h, 2)
            hints = ["Площадь трапеции равна произведению полусуммы оснований на высоту."]
            solution = [f"S = ({upper} + {lower}) · {h} / 2 = {format_decimal(result)}."]
        exact = {"construction": "A=(0,0),B=(x,h),C=(x+u,h),D=(L,0)", "parameters": p}
    else:
        raise ValueError("Unknown family")
    return {
        "exact_model": exact,
        "points": pts,
        "segments": lines,
        "right_angles": marks,
        "length_labels": labels,
        "condition": condition,
        "hints": hints,
        "solution": solution,
        "correct_answer": format_decimal(result),
    }


def generate(
    family_id: str, seed: int, generator_version: str = GENERATOR_VERSION
) -> QuadrilateralProblem:
    if family_id not in FAMILIES or generator_version != GENERATOR_VERSION:
        raise ValueError("Unknown №17 generator contract")
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("Invalid seed")
    return _pack(family_id, seed, parameters(family_id, seed))


def _pack(family: str, seed: int, p: dict[str, int]) -> QuadrilateralProblem:
    from app.math.oge17_oracle import audit_math
    from app.math.oge17_render import audit_png, render

    data = build(family, p)
    # Fingerprint excludes nonessential layout, reflection, scale and redundant data.
    semantic = (
        {"angle_b": p["angle_b"]}
        if family == FAMILIES[0]
        else {"twice_bo": p["twice_bo"], "ab": p["ab"]}
        if family == FAMILIES[1]
        else {"s": p["s"], "t": p["t"], "h": p["h"]}
        if family == FAMILIES[2]
        else p
        if family == FAMILIES[3]
        else {
            k: p[k]
            for k in (("lower", "upper") if family == FAMILIES[4] else ("lower", "upper", "h"))
        }
    )
    data.update(
        family_id=family,
        seed=seed,
        generator_version=GENERATOR_VERSION,
        renderer_version=RENDERER_VERSION,
        oracle_version=ORACLE_VERSION,
        problem_id=str(uuid5(NAMESPACE_URL, f"{family}:{seed}:{GENERATOR_VERSION}")),
        answer_policy_id=POLICY.policy_id,
        answer_policy_version=POLICY.version,
        sources=[
            {"task_id": i, "url": f"https://math-oge.sdamgia.ru/problem?id={i}"}
            for i in SOURCES[family]
        ],
        provenance="generated_analogue",
        fingerprint=hashlib.sha256(
            json.dumps([family, semantic], sort_keys=True).encode()
        ).hexdigest(),
    )
    result = audit_math(data)
    if POLICY.format(result) != data["correct_answer"]:
        raise ValueError("Numeric answer policy mismatch")
    points = list(data["points"].values())
    aspect = (max(v[1] for v in points) - min(v[1] for v in points)) / (
        max(v[0] for v in points) - min(v[0] for v in points)
    )
    if not 0.20 <= aspect <= 4:
        raise ValueError("Diagram is too flat")
    png = render(data)
    audit_png(png, data)
    data.update(
        png_base64=base64.b64encode(png).decode(), png_sha256=hashlib.sha256(png).hexdigest()
    )
    return QuadrilateralProblem(json.dumps(data, ensure_ascii=False, sort_keys=True))


def from_snapshot(snapshot: dict[str, Any], *, expected_problem_id: str) -> QuadrilateralProblem:
    """Trusted issuance ID is required: self-consistent seed substitution is not authenticity.

    A complete replacement snapshot cannot be detected without external trusted identity.
    """
    from app.math.oge17_oracle import audit_math
    from app.math.oge17_render import audit_png

    try:
        if len(json.dumps(snapshot)) > 250_000 or snapshot["problem_id"] != expected_problem_id:
            raise ValueError("Snapshot identity/size mismatch")
        audit_math(snapshot)
        png = base64.b64decode(snapshot["png_base64"], validate=True)
        if hashlib.sha256(png).hexdigest() != snapshot["png_sha256"]:
            raise ValueError("PNG digest mismatch")
        audit_png(png, snapshot)
        replay = generate(snapshot["family_id"], snapshot["seed"], snapshot["generator_version"])
        if replay.to_snapshot() != snapshot:
            raise ValueError("Snapshot deterministic replay mismatch")
        return replay
    except (KeyError, TypeError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError("Invalid №17 snapshot") from exc
