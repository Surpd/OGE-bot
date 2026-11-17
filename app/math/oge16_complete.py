"""Source-faithful v3 circle constructions; all lengths have exact short answers."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction
from typing import Any

from app.math.answer_policy import format_decimal
from app.math.oge16_model import CircleGeometry

SOURCE_VARIANTS = {
    "A01": ("116", "142", "314850"),
    "A02": ("311956", "314811"),
    "A03": ("311517", "349314"),
    "A04": ("339419",),
    "A05": ("341673", "348379", "339503", "341329"),
    "A06": ("348961",),
    "B01": ("340174",),
    "B02": ("340337",),
    "B03": ("340587",),
    "B04": ("356543",),
    "B05": ("369504",),
    "C01": ("324364", "341707", "356369", "356399"),
    "C02": ("355413", "448769"),
    "C03": ("356329",),
    "C04": ("356488", "356498", "356518", "472375"),
    "C05": ("356579", "356603", "438296"),
    "C06": ("472385",),
    "D01": ("356438", "356448"),
    "D02": ("356533",),
    "D03": ("369738",),
    "D04": ("450514",),
    "D05": ("462105",),
    "D06": ("472378",),
}
FAMILIES = tuple("OGE16-" + key for key in SOURCE_VARIANTS)


def parameters(family: str, seed: int) -> tuple[Fraction, ...]:
    key = family.removeprefix("OGE16-")
    variants = len(SOURCE_VARIANTS[key])
    # Ten exact metric scales; angular constructions vary angles independently.
    variant = seed % variants
    scale = (seed // variants) % 10 + 1
    # Keep the large original radius 83 as a control, without manufacturing
    # oversized arithmetic. Other confirmed metric models scale naturally.
    if key == "C01" and variant == 0:
        scale = 1
    return Fraction(variant), Fraction(scale)


def source(family: str, p: tuple[Fraction, ...]) -> str:
    return SOURCE_VARIANTS[family.removeprefix("OGE16-")][int(p[0])]


def content(
    family: str, p: tuple[Fraction, ...]
) -> tuple[str, list[str], list[str], Fraction, CircleGeometry]:
    key = family.removeprefix("OGE16-")
    v, scale = int(p[0]), p[1]
    k = float(scale)

    def n(value: Any) -> str:
        return format_decimal(Fraction(value))

    def polar(deg: float, radius: float = 1.0) -> tuple[float, float]:
        return radius * math.cos(math.radians(deg)), radius * math.sin(math.radians(deg))

    def scene(radius: float, points: dict[str, tuple[float, float]], edges: str) -> CircleGeometry:
        return CircleGeometry(
            radius, tuple(points.items()), tuple((e[0], e[1]) for e in edges.split())
        )

    def polygon(radius: float, points: dict[str, tuple[float, float]]) -> CircleGeometry:
        names = list(points)
        return CircleGeometry(
            radius,
            tuple(points.items()),
            tuple((a, b) for a, b in zip(names, names[1:] + names[:1], strict=True)),
        )

    a = 0
    target = ""
    inscribed = Fraction(0)
    theorem: str
    answer: Fraction
    if key == "A01":
        a = (30 if v == 1 else 70) + (int(scale) - 1)
        points = {
            "O": (0.0, 0.0),
            "A": polar(0),
            "B": polar(180 - 2 * a),
            "C": polar(-2 * a),
            "D": polar(180),
        }
        given, target = ("OCD", "OAB") if v == 1 else ("OAB", "OCD")
        text = (
            f"В окружности с центром O проведены диаметры AD и BC. Угол {given} равен "
            f"{a}°. Найдите угол {target}. Ответ дайте в градусах."
        )
        answer = Fraction(a)
        theorem = (
            "Треугольники AOB и COD равнобедренные, а углы AOB и COD вертикальные. Их "
            "углы при основаниях равны."
        )
        g = scene(1.0, points, "AD BC AB CD")
    elif key == "A02":
        a = (48 if v == 0 else 84) + 2 * (int(scale) - 1)
        text = (
            f"Треугольник ABC вписан в окружность с центром O. Угол AOB равен {a}°. "
            f"Найдите угол ACB. Ответ дайте в градусах."
        )
        answer = Fraction(a, 2)
        theorem = "Вписанный угол равен половине центрального угла, опирающегося на ту же дугу."
        g = scene(
            1.0,
            {"A": polar(-90 - a / 2), "B": polar(-90 + a / 2), "C": polar(90), "O": (0.0, 0.0)},
            "OA OB AC BC AB",
        )
    elif key == "A03":
        a = (110 if v == 0 else 108) - 4 * (int(scale) - 1)
        inscribed = Fraction(180 - a, 2)
        given = f"Угол AOD равен {a}°" if v == 0 else f"Угол ACB равен {n(inscribed)}°"
        target = "ACB" if v == 0 else "AOD"
        text = (
            f"В окружности с центром O отрезки AC и BD — диаметры. {given}. Найдите "
            f"угол {target}. Ответ дайте в градусах."
        )
        answer = inscribed if v == 0 else Fraction(a)
        theorem = "Углы AOB и AOD в сумме равны 180°. Угол ACB равен половине угла AOB."
        g = scene(
            1.0,
            {"A": polar(0), "B": polar(180 - a), "C": polar(180), "D": polar(-a), "O": (0.0, 0.0)},
            "AC BD CB AB",
        )
    elif key == "A04":
        a = 38 + int(scale) - 1
        text = (
            f"На окружности по разные стороны от диаметра AB взяты точки M и N. Угол "
            f"NBA равен {a}°. Найдите угол NMB. Ответ дайте в градусах."
        )
        answer = Fraction(90 - a)
        theorem = (
            "Угол ANB опирается на диаметр и равен 90°. Углы NAB и NMB опираются на одну дугу NB."
        )
        g = scene(
            1.0,
            {"A": (-1.0, 0.0), "B": (1.0, 0.0), "N": polar(-180 + 2 * a), "M": polar(70)},
            "AB BN NM MB",
        )
    elif key == "A05":
        a = (75, 30, 75, 44)[v] + int(scale) - 1
        diameter, target = ("AB", "ABC") if v == 1 else ("AC", "C")
        text = (
            f"Центр окружности, описанной около треугольника ABC, лежит на стороне "
            f"{diameter}. Угол BAC равен {a}°. Найдите угол {target}. Ответ дайте в "
            f"градусах."
        )
        answer = Fraction(90 - a)
        theorem = (
            "Угол, опирающийся на диаметр, прямой. Острые углы прямоугольного "
            "треугольника в сумме равны 90°."
        )
        pts = (
            {"A": (-1.0, 0.0), "B": (1.0, 0.0), "C": polar(2 * a)}
            if v == 1
            else {"A": (-1.0, 0.0), "C": (1.0, 0.0), "B": polar(2 * a)}
        )
        g = scene(1.0, pts, "AB BC CA")
    elif key == "A06":
        text = (
            f"Центр окружности, описанной около треугольника ABC, лежит на стороне AB. "
            f"Радиус окружности равен {n(Fraction(13, 2) * scale)}. Найдите AC, если "
            f"BC = {n(12 * scale)}."
        )
        answer = 5 * scale
        theorem = "AB — диаметр; угол ACB прямой. По теореме Пифагора AC² = (2R)² − BC²."
        # endpoints are translated so the circumcenter is exactly (0,0)
        g = scene(
            6.5 * k,
            {"A": (-6.5 * k, 0.0), "B": (6.5 * k, 0.0), "C": (-119 * k / 26, 60 * k / 13)},
            "AB BC CA",
        )
    elif key == "B01":
        text = (
            f"На отрезке AB выбрана точка C так, что AC = {n(75 * scale)}, BC = "
            f"{n(10 * scale)}. Окружность с центром A проходит через C. Найдите длину "
            f"касательной, проведённой из точки B к этой окружности."
        )
        answer = 40 * scale
        theorem = (
            "Радиус в точке касания перпендикулярен касательной. Её длина находится "
            "по теореме Пифагора."
        )
        g = scene(
            75 * k,
            {
                "A": (0.0, 0.0),
                "B": (85 * k, 0.0),
                "C": (75 * k, 0.0),
                "T": (1125 * k / 17, -600 * k / 17),
                "L": (-75 * k, 0.0),
            },
            "LB BT",
        )
    elif key == "B02":
        a = 72 + 2 * (int(scale) - 1)
        text = (
            f"Касательные в точках A и B к окружности с центром O пересекаются под "
            f"углом {a}°. Найдите угол ABO. Ответ дайте в градусах."
        )
        answer = Fraction(a, 2)
        theorem = (
            "Сумма углов между касательными и радиусами равна 180°. В равнобедренном "
            "треугольнике AOB угол ABO равен половине угла между касательными."
        )
        theta = (180 - a) / 2
        x, y = polar(theta)
        g = scene(
            1.0, {"A": (x, y), "B": (x, -y), "O": (0.0, 0.0), "P": (1 / x, 0.0)}, "PA PB AO BO AB"
        )
    elif key == "B03":
        text = (
            f"Найдите длину хорды окружности радиусом {n(13 * scale)}, если "
            f"расстояние от центра окружности до хорды равно {n(5 * scale)}."
        )
        answer = 24 * scale
        theorem = "Перпендикуляр из центра делит хорду пополам; половина хорды равна √(R² − d²)."
        g = scene(
            13 * k,
            {"A": (-12 * k, -5 * k), "B": (12 * k, -5 * k), "O": (0.0, 0.0), "M": (0.0, -5 * k)},
            "AB OM",
        )
    elif key == "B04":
        text = (
            f"Через точку A вне окружности проведены касательная AK и секущая ABC. AB "
            f"= {n(2 * scale)}, AC = {n(8 * scale)}. Найдите AK."
        )
        answer = 4 * scale
        theorem = (
            "Квадрат касательной равен произведению внешней части секущей на всю "
            "секущую: AK² = AB · AC."
        )
        g = scene(
            3 * k,
            {"A": (-5 * k, 0.0), "B": (-3 * k, 0.0), "C": (3 * k, 0.0), "K": (-1.8 * k, 2.4 * k)},
            "AC AK",
        )
    elif key == "B05":
        a = 72 + 2 * (int(scale) - 1)
        text = (
            f"На окружности отмечены точки A и B так, что меньшая дуга AB равна {a}°. "
            f"Прямая BC касается окружности в точке B так, что угол ABC острый. "
            f"Найдите угол ABC. Ответ дайте в градусах."
        )
        answer = Fraction(a, 2)
        theorem = (
            "Угол между касательной и хордой равен половине градусной меры "
            "заключённой между ними дуги."
        )
        g = scene(1.0, {"B": polar(0), "A": polar(a), "C": (1.0, 1.4)}, "AB BC")
    elif key == "C01":
        if v < 2:
            given_r = (83 if v == 0 else 7) * scale
            text = f"Найдите площадь квадрата, описанного вокруг окружности радиуса {n(given_r)}."
            answer = 4 * given_r * given_r
            r = float(given_r)
        elif v == 2:
            r = 2 * k * math.sqrt(2)
            text = (
                f"Радиус вписанной в квадрат окружности равен {n(2 * scale)}√2. "
                f"Найдите диагональ этого квадрата."
            )
            answer = 8 * scale
        else:
            r = float(3 * scale)
            text = (
                f"Сторона квадрата равна {n(6 * scale)}. Найдите радиус окружности, "
                f"вписанной в этот квадрат."
            )
            answer = 3 * scale
        r = float(r)
        theorem = (
            "Сторона квадрата равна диаметру вписанной окружности; диагональ равна "
            "стороне, умноженной на √2."
        )
        g = polygon(r, {"A": (-r, -r), "B": (-r, r), "C": (r, r), "D": (r, -r)})
    elif key == "C02":
        given_r = (16 if v == 0 else 12) * scale
        adjective = "равнобедренную " if v else ""
        text = (
            f"Радиус окружности, вписанной в {adjective}трапецию, равен {n(given_r)}. "
            f"Найдите высоту этой трапеции."
        )
        answer = 2 * given_r
        theorem = "Расстояние между параллельными основаниями равно диаметру вписанной окружности."
        z = float(given_r)
        g = polygon(z, {"A": (-2 * z, -z), "B": (-z / 2, z), "C": (z / 2, z), "D": (2 * z, -z)})
    elif key == "C03":
        text = (
            f"Периметр треугольника равен {n(50 * scale)}, одна из сторон равна "
            f"{n(20 * scale)}, а радиус вписанной в него окружности равен "
            f"{n(4 * scale)}. Найдите площадь этого треугольника."
        )
        answer = 100 * scale * scale
        theorem = (
            "Площадь треугольника равна произведению полупериметра на радиус вписанной окружности."
        )
        cx = (10 - 3 * math.sqrt(5)) * k
        ix = (10 - 2 * math.sqrt(5)) * k
        g = scene(
            4 * k,
            {"A": (-ix, -4 * k), "B": (20 * k - ix, -4 * k), "C": (cx - ix, 6 * k)},
            "AB BC CA",
        )
    elif key in {"C04", "D02"}:
        if key == "D02":
            text = (
                f"Радиус окружности, описанной около равностороннего треугольника, "
                f"равен {n(2 * scale)}√3. Найдите длину стороны этого треугольника."
            )
            answer = 6 * scale
            r = 2 * k * math.sqrt(3)
        elif v == 0:
            text = (
                f"Сторона равностороннего треугольника равна {n(2 * scale)}√3. Найдите "
                f"радиус окружности, вписанной в этот треугольник."
            )
            answer = scale
            r = k
        elif v == 1:
            text = (
                f"Радиус окружности, вписанной в равносторонний треугольник, равен "
                f"{n(5 * scale)}. Найдите высоту этого треугольника."
            )
            answer = 15 * scale
            r = 5 * k
        elif v == 2:
            text = (
                f"Радиус окружности, вписанной в равносторонний треугольник, равен "
                f"{n(2 * scale)}√3. Найдите длину стороны этого треугольника."
            )
            answer = 12 * scale
            r = 2 * k * math.sqrt(3)
        else:
            text = (
                f"В окружность с центром O вписан равносторонний треугольник. "
                f"Расстояние от точки O до сторон треугольника равно {n(scale)}√3/2. "
                f"Найдите длину стороны треугольника."
            )
            answer = 3 * scale
            r = k * math.sqrt(3) / 2
        theorem = "Для равностороннего треугольника R = 2r, h = 3r, a = 2r√3 = R√3."
        R = r if key == "D02" else 2 * r
        g = scene(r, {"A": polar(90, R), "B": polar(210, R), "C": polar(330, R)}, "AB BC CA")
        if key == "C04" and v == 3:
            pts = dict(g.points)
            pts["O"] = (0.0, 0.0)
            g = CircleGeometry(2 * r, tuple(pts.items()), g.segments)
    elif key == "C05":
        if v == 0:
            text = (
                f"Четырёхугольник ABCD описан около окружности. AB = {n(7 * scale)}, "
                f"BC = {n(10 * scale)}, CD = {n(14 * scale)}. Найдите AD."
            )
            answer = 11 * scale
            # Tangent lengths at A,B,C,D: 3,4,6,8. Opposite sums 7+14=10+11.
            # The incircle radius solves sum atan(r/t_i)=pi.
            lengths = [3 * k, 4 * k, 6 * k, 8 * k]
            lo, hi = 0.0, 20 * k
            for _ in range(60):
                mid = (lo + hi) / 2
                if sum(math.atan(mid / t) for t in lengths) < math.pi:
                    lo = mid
                else:
                    hi = mid
            r = (lo + hi) / 2
            normals = [0.0]
            for t in lengths[1:]:
                normals.append(normals[-1] + 2 * math.atan(t / r))
            vertices = {}
            for i, name in enumerate("ABCD"):
                prev = normals[i - 1] if i else normals[-1] - math.tau
                curr = normals[i]
                delta = (curr - prev) / 2
                ang = (curr + prev) / 2
                vertices[name] = polar(math.degrees(ang), r / math.cos(delta))
            g = polygon(r, vertices)
        else:
            text = (
                f"Трапеция ABCD с основаниями AD и BC описана около окружности. AB = "
                f"{n(11 * scale)}, BC = {n(6 * scale)}, CD = {n(9 * scale)}. Найдите "
                f"AD."
            )
            answer = 14 * scale
            # bases 14,6, legs 11,9, horizontal offsets 6.5 and 1.5
            h = math.sqrt(78.75) * k
            r = h / 2
            # incenter x from left leg distance r: x=(11+6.5)/2=8.75 from A
            g = polygon(
                r,
                {
                    "A": (-8.75 * k, -r),
                    "B": (-2.25 * k, r),
                    "C": (3.75 * k, r),
                    "D": (5.25 * k, -r),
                },
            )
        theorem = (
            "В описанном четырёхугольнике суммы противоположных сторон равны: AB + CD = BC + AD."
        )
    elif key == "C06":
        text = (
            f"Диагональ AC ромба ABCD равна {n(48 * scale)}, а тангенс угла BCA равен "
            f"7/24. Найдите радиус окружности, вписанной в ромб."
        )
        answer = Fraction(168, 25) * scale
        theorem = (
            "Диагонали ромба перпендикулярны, а AC делит угол C пополам. Радиус равен "
            "(AC/2) · sin(∠BCA); sin = 7/25."
        )
        g = polygon(
            float(answer),
            {"A": (-24 * k, 0.0), "B": (0.0, 7 * k), "C": (24 * k, 0.0), "D": (0.0, -7 * k)},
        )
        g = CircleGeometry(g.radius, g.points, g.segments + (("A", "C"),))
    elif key == "D01":
        a = (82 if v == 0 else 81) + int(scale) - 1
        noun = "Четырёхугольник ABCD" if v == 0 else "Трапеция ABCD с основаниями AD и BC"
        text = (
            f"{noun} вписан{'а' if v else ''} в окружность. Угол A равен {a}°. Найдите "
            f"угол C. Ответ дайте в градусах."
        )
        answer = Fraction(180 - a)
        theorem = "Сумма противоположных углов вписанного четырёхугольника равна 180°."
        if v:
            phi = 60.0
            psi = phi + 180 - 2 * a
            pts = {
                "A": polar(180 - phi),
                "B": polar(180 + psi),
                "C": polar(360 - psi),
                "D": polar(phi),
            }
        else:
            pts = {"A": (-1.0, 0.0), "B": polar(a), "C": (1.0, 0.0), "D": polar(-a)}
        g = polygon(1.0, pts)
    elif key == "D03":
        text = (
            f"Радиус окружности, описанной около квадрата, равен {n(16 * scale)}√2. "
            f"Найдите длину стороны этого квадрата."
        )
        answer = 32 * scale
        theorem = "Диагональ квадрата равна диаметру окружности, а сторона равна R√2."
        g = polygon(
            16 * k * math.sqrt(2),
            {
                "A": (-16 * k, -16 * k),
                "B": (-16 * k, 16 * k),
                "C": (16 * k, 16 * k),
                "D": (16 * k, -16 * k),
            },
        )
    elif key == "D04":
        text = (
            f"В треугольнике ABC угол C равен 45°, AB = {n(6 * scale)}√2. Найдите "
            f"радиус окружности, описанной около этого треугольника."
        )
        answer = 6 * scale
        theorem = "По теореме синусов AB = 2R · sin C, значит R = AB/(2 sin C)."
        g = scene(
            6 * k,
            {"A": polar(-135, 6 * k), "B": polar(-45, 6 * k), "C": polar(90, 6 * k)},
            "AB BC CA",
        )
    elif key == "D05":
        text = (
            f"Точка O является серединой стороны CD квадрата ABCD. Радиус окружности с "
            f"центром O, проходящей через вершину A, равен {n(5 * scale)}. Найдите "
            f"площадь квадрата ABCD."
        )
        answer = 20 * scale * scale
        theorem = "Если сторона квадрата a, то OA² = a² + (a/2)² = 5a²/4. Поэтому S = 4R²/5."
        side_length = 2 * math.sqrt(5) * k
        g = scene(
            5 * k,
            {
                "A": (-side_length / 2, side_length),
                "B": (side_length / 2, side_length),
                "C": (side_length / 2, 0.0),
                "D": (-side_length / 2, 0.0),
                "O": (0.0, 0.0),
                "L": (-5 * k, 0.0),
                "R": (5 * k, 0.0),
            },
            "AB BC CD DA LR",
        )
    elif key == "D06":
        text = (
            f"Синус угла между стороной и диагональю прямоугольника равен 0,6. Диаметр "
            f"описанной около него окружности равен {n(10 * scale)}. Найдите площадь "
            f"прямоугольника."
        )
        answer = 48 * scale * scale
        theorem = (
            "Диагональ — диаметр окружности. Стороны равны d · sin α и d · cos α; cos α = 0,8."
        )
        g = scene(
            5 * k,
            {
                "A": (-4 * k, -3 * k),
                "B": (-4 * k, 3 * k),
                "C": (4 * k, 3 * k),
                "D": (4 * k, -3 * k),
            },
            "AB BC CD DA AC",
        )
    else:
        raise ValueError("Unknown source construction")
    hidden = {
        "B01": ("T", "L"),
        "B02": ("P",),
        "B03": ("A", "B", "O", "M"),
        "C01": tuple("ABCD"),
        "C02": tuple("ABCD"),
        "C03": tuple("ABC"),
        "C04": tuple("ABC"),
        "D02": tuple("ABC"),
        "D03": tuple("ABCD"),
        "D05": ("L", "R"),
        "D06": tuple("ABCD"),
    }.get(key, ())
    g = replace(g, hidden_labels=hidden)
    formulas: dict[str, Callable[[], str]] = {
        "A01": lambda: ("Углы при основаниях равны: искомый угол"),
        "A02": lambda: (f"∠ACB = {n(a)}/2"),
        "A03": lambda: (
            f"∠{target} = " + (f"180 − 2 · {n(inscribed)}" if v else f"(180 − {n(a)})/2")
        ),
        "A04": lambda: (f"∠NMB = 90 − {n(a)}"),
        "A05": lambda: (f"Искомый угол = 90 − {n(a)}"),
        "A06": lambda: (f"AC = √((2 · {n(Fraction(13, 2) * scale)})² − {n(12 * scale)}²)"),
        "B01": lambda: (
            f"Длина касательной = √(({n(75 * scale)} + {n(10 * scale)})² − {n(75 * scale)}²)"
        ),
        "B02": lambda: (f"∠ABO = {n(a)}/2"),
        "B03": lambda: (f"Длина хорды = 2√({n(13 * scale)}² − {n(5 * scale)}²)"),
        "B04": lambda: (f"AK = √({n(2 * scale)} · {n(8 * scale)})"),
        "B05": lambda: (f"∠ABC = {n(a)}/2"),
        "C01": (
            lambda: (
                f"S = (2 · {n((83 if v == 0 else 7) * scale)})²"
                if v < 2
                else f"d = 2 · {n(2 * scale)}√2 · √2"
                if v == 2
                else f"r = {n(6 * scale)}/2"
            )
        ),
        "C02": lambda: (f"h = 2 · {n((16 if v == 0 else 12) * scale)}"),
        "C03": lambda: (f"S = ({n(50 * scale)}/2) · {n(4 * scale)}"),
        "C04": lambda: (
            f"r = {n(2 * scale)}√3 · √3/6"
            if v == 0
            else f"h = 3 · {n(5 * scale)}"
            if v == 1
            else f"a = 2 · {n(2 * scale)}√3 · √3"
            if v == 2
            else f"a = 2√3 · ({n(scale)}√3/2)"
        ),
        "C05": lambda: (
            f"AD = {n((7 if v == 0 else 11) * scale)} + "
            f"{n((14 if v == 0 else 9) * scale)} − {n((10 if v == 0 else 6) * scale)}"
        ),
        "C06": lambda: (f"r = ({n(48 * scale)}/2) · 7/25"),
        "D01": lambda: (f"∠C = 180 − {n(a)}"),
        "D02": lambda: (f"a = {n(2 * scale)}√3 · √3"),
        "D03": lambda: (f"a = {n(16 * scale)}√2 · √2"),
        "D04": lambda: (f"R = {n(6 * scale)}√2/(2 · sin 45°)"),
        "D05": lambda: (f"S = 4 · {n(5 * scale)}²/5"),
        "D06": lambda: (f"S = {n(10 * scale)}² · 0,6 · 0,8"),
    }
    calculation = f"{formulas[key]()} = {n(answer)}."
    return text, [theorem], [theorem, calculation], answer, g
