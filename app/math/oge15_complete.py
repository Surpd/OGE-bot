"""Version 2 triangle contracts and learner content for F01–F22."""

from __future__ import annotations

import random
from fractions import Fraction
from math import isqrt

VERSION = "oge15-triangles-2"
ALL_FAMILIES = tuple(f"OGE15-F{n:02}" for n in range(1, 23))
SOURCE_IDS = (
    "348885",
    "348610",
    "356190",
    "356180",
    "311680",
    "350010",
    "472372",
    "339390",
    "339544",
    "480731",
    "349690",
    "341524",
    "356242",
    "350527",
    "356089",
    "118",
    "311790",
    "353022",
    "348554",
    "169853",
    "356159",
    "348380",
)


def number(family: str) -> int:
    if family not in ALL_FAMILIES:
        raise ValueError("Unknown triangle family")
    return int(family[-2:])


def display(value: int | Fraction) -> str:
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    # Parameters are deliberately restricted to terminating decimals.
    denominator = value.denominator
    for factor in (2, 5):
        while denominator % factor == 0:
            denominator //= factor
    if denominator != 1:
        return f"{value.numerator}/{value.denominator}"
    digits = 0
    scaled = value
    while scaled.denominator != 1:
        digits += 1
        scaled *= 10
    s = str(scaled.numerator).zfill(digits + 1)
    return s[:-digits] + "," + s[-digits:]


def parameters(n: int, seed: int) -> tuple[int, ...]:
    rng = random.Random(f"{VERSION}:F{n:02}:{seed}")
    if n == 1:
        a = rng.randint(30, 100)
        return a, rng.randint(30, 150 - a)
    if n == 2:
        return 2 * rng.randint(15, 45), rng.randint(40, 65)
    if n == 3:
        return (rng.randint(45, 140),)
    if n == 4:
        return (rng.randint(25, 65),)
    if n == 5:
        return (rng.randint(105, 150),)
    if n == 6:
        return (rng.randint(3, 30),)
    if n == 7:
        return (rng.randint(25, 65),)
    if n == 8:
        k = rng.randint(3, 25)
        return k, rng.randint(k, 3 * k)
    if n == 9:
        return rng.randint(3, 30), rng.randint(35, 65)
    if n == 10:
        return (rng.randint(20, 45),)
    if n == 11:
        base = rng.randint(12, 60)
        return rng.randint(base * 3 // 4, base), rng.randint(base * 3 // 4, base), base
    if n == 12:
        return (rng.randint(10, 120),)
    if n == 13:
        q = rng.randint(4, 12)
        return 2 * q, 2 * rng.randint(max(2, (q + 2) // 3), 2 * q // 3), q * q * rng.randint(1, 3)
    if n == 14:
        a, b, _ = rng.choice(((3, 4, 5), (5, 12, 13), (8, 15, 17), (7, 24, 25), (40, 9, 41)))
        k = rng.randint(1, 5)
        return a * k, b * k, rng.randrange(2)
    if n == 15:
        kind = rng.randrange(3)
        if kind == 2:
            return rng.randint(3, 15), rng.choice((4, 5, 8, 10)), kind
        a, b, _ = rng.choice(((3, 4, 5), (4, 3, 5), (7, 24, 25), (24, 7, 25)))
        k = rng.randint(1, 4)
        return a * k, b * k, kind
    if n == 16:
        k = rng.randint(1, 5)
        return 10 * k, rng.randint(3, 8) * k
    if n == 17:
        return rng.randint(5, 20), rng.randint(1, 4), 2
    if n == 18:
        return (rng.randint(25, 65),)
    if n in (19, 20):
        a = rng.randint(6, 25)
        return a, rng.randint(max(4, a // 2), 2 * a)
    if n == 21:
        nu, de = rng.choice(((1, 3), (1, 2), (3, 5), (4, 5)))
        a = 2 * de * rng.randint(1, 3)
        return a, rng.randint(max(4, a // 2), 2 * a), nu, de
    if n == 22:
        nu, de = rng.choice(((2, 5), (1, 2), (3, 5), (4, 5)))
        return rng.randint(2, 12), nu, de
    raise ValueError("Unknown family")


def content(n: int, p: tuple[int, ...]) -> tuple[str, list[str], list[str], Fraction]:
    a = p[0]
    b = p[1] if len(p) > 1 else 0
    if n == 1:
        value = Fraction(180 - a - b)
        text = (
            f"Два угла треугольника равны {a}° и {b}°. Найдите третий угол. Ответ дайте в градусах."
        )
        hint = "Сумма внутренних углов треугольника равна 180°."
        solution = [f"Третий угол: 180° − {a}° − {b}° = {display(value)}°."]
    elif n == 2:
        value = Fraction(a, 2)
        text = (
            f"В треугольнике ABC угол BAC равен {a}°, AD — биссектриса. Найдите "
            f"угол BAD. Ответ дайте в градусах."
        )
        hint = "Биссектриса делит угол на две равные части."
        solution = [f"∠BAD = ∠DAC = {a}° / 2 = {display(value)}°."]
    elif n == 3:
        value = Fraction(180 - a)
        text = (
            f"В треугольнике ABC угол C равен {a}°. Найдите внешний угол при "
            f"вершине C. Ответ дайте в градусах."
        )
        hint = "Внешний угол смежен с внутренним углом при той же вершине."
        solution = [f"Внешний угол: 180° − {a}° = {display(value)}°."]
    elif n == 4:
        value = Fraction(90 - a)
        text = (
            f"В остроугольном треугольнике ABC проведена высота BH, угол BAC "
            f"равен {a}°. Найдите угол ABH. Ответ дайте в градусах."
        )
        hint = "Рассмотрите прямоугольный треугольник ABH."
        solution = [
            "BH ⟂ AC, поэтому ∠AHB = 90°.",
            f"∠ABH = 180° − 90° − {a}° = {display(value)}°.",
        ]
    elif n == 5:
        value = Fraction(2 * a - 180)
        text = (
            f"В равнобедренном треугольнике ABC с основанием AC внешний угол "
            f"при вершине C равен {a}°. Найдите угол ABC. Ответ дайте в "
            f"градусах."
        )
        hint = "Углы при основании равнобедренного треугольника равны."
        solution = [
            f"∠A = ∠C = 180° − {a}° = {180 - a}°.",
            f"∠B = 180° − 2 · {180 - a}° = {display(value)}°.",
        ]
    elif n == 6:
        value = Fraction(2 * a)
        text = f"Медиана равностороннего треугольника равна {a}√3. Найдите сторону треугольника."
        hint = "Медиана равностороннего треугольника является также высотой."
        solution = [
            "Высота равностороннего треугольника равна a√3 / 2.",
            f"a = 2 · {a}√3 / √3 = {display(value)}.",
        ]
    elif n == 7:
        value = Fraction(90 - a)
        text = (
            f"В треугольнике ABC проведена медиана BM. Найдите угол A, если "
            f"угол C равен {a}° и BM = AM = MC. Ответ дайте в градусах."
        )
        hint = "Рассмотрите равнобедренные треугольники ABM и CBM."
        solution = [
            "Пусть ∠A = x. Тогда ∠ABM = x, а ∠MBC = ∠C.",
            f"2x + 2 · {a}° = 180°. Значит, x = 90° − {a}° = {display(value)}°.",
        ]
    elif n == 8:
        value = Fraction(3 * a)
        text = (
            f"В треугольнике ABC проведены медиана BM и высота BH. AC = "
            f"{4 * a}, BC = BM. Найдите AH."
        )
        hint = "Треугольник BMC равнобедренный. Его высота является медианой."
        solution = [
            f"AM = MC = {4 * a} / 2 = {2 * a}.",
            f"MH = HC = {2 * a} / 2 = {a}.",
            f"AH = AM + MH = {2 * a} + {a} = {display(value)}.",
        ]
    elif n == 9:
        value = Fraction(180 - b)
        text = (
            f"В треугольнике ABC проведены медиана BM и высота BH. AC = "
            f"{4 * a}, HC = {a}, угол ACB равен {b}°. Найдите угол AMB. Ответ "
            f"дайте в градусах."
        )
        hint = "Сравните отрезки MH и HC, затем треугольники BHM и BHC."
        solution = [
            f"MC = {4 * a} / 2 = {2 * a}, MH = {2 * a} − {a} = {a} = HC.",
            f"Прямоугольные треугольники BHM и BHC равны по катетам. Поэтому ∠BMC = ∠C = {b}°.",
            f"∠AMB = 180° − {b}° = {display(value)}°.",
        ]
    elif n == 10:
        value = Fraction(180 - 3 * a)
        text = (
            f"В треугольнике ABC проведена биссектриса AK. Найдите угол B, если "
            f"угол C равен {a}° и AK = KC. Ответ дайте в градусах."
        )
        hint = "Треугольник AKC равнобедренный. Используйте также свойство биссектрисы."
        solution = [
            f"AK = KC, поэтому ∠KAC = ∠C = {a}°.",
            f"AK — биссектриса, значит ∠A = 2 · {a}° = {2 * a}°.",
            f"∠B = 180° − {2 * a}° − {a}° = {display(value)}°.",
        ]
    elif n == 11:
        c = p[2]
        value = Fraction(c, 2)
        text = (
            f"Точки M и N — середины сторон AB и BC треугольника ABC. AB = {a}, "
            f"BC = {b}, AC = {c}. Найдите MN."
        )
        hint = "Отрезок, соединяющий середины двух сторон, — средняя линия треугольника."
        solution = [f"MN = AC / 2 = {c} / 2 = {display(value)}."]
    elif n == 12:
        value = Fraction(4 * a)
        text = (
            f"В треугольнике ABC отрезок DE — средняя линия. Площадь "
            f"треугольника CDE равна {a}. Найдите площадь треугольника ABC."
        )
        hint = "Площади подобных треугольников относятся как квадраты соответствующих сторон."
        solution = [
            "DE = AB / 2. Отношение площадей ABC и CDE равно 2² = 4.",
            f"S = 4 · {a} = {display(value)}.",
        ]
    elif n == 13:
        area = p[2]
        value = Fraction(area * b * b, a * a)
        text = (
            f"Прямая, параллельная стороне AC треугольника ABC, пересекает AB и "
            f"BC в точках M и N. AC = {a}, MN = {b}. Площадь ABC равна {area}. "
            f"Найдите площадь MBN."
        )
        hint = "Треугольники MBN и ABC подобны. Найдите отношение их соответствующих сторон."
        solution = [
            f"Коэффициент подобия: MN / AC = {b} / {a}.",
            f"S_MBN = {area} · ({b} / {a})² = {display(value)}.",
        ]
    elif n == 14:
        hyp = isqrt(a * a + b * b)
        if len(p) > 2 and p[2] == 1:
            value = Fraction(b)
            text = (
                f"В прямоугольном треугольнике катет и гипотенуза равны {a} и {hyp}. "
                "Найдите другой катет."
            )
            solution = [f"b² = {hyp}² − {a}² = {b * b}.", f"b = {b}."]
        else:
            value = Fraction(hyp)
            text = f"Катеты прямоугольного треугольника равны {a} и {b}. Найдите гипотенузу."
            solution = [f"c² = {a}² + {b}² = {hyp * hyp}.", f"c = {hyp}."]
        hint = "Квадрат гипотенузы равен сумме квадратов катетов."
    elif n == 15:
        kind = p[2] if len(p) > 2 else 0
        hyp = isqrt(a * a + b * b)
        if kind == 2:
            value = Fraction(a, b)
            text = f"В треугольнике ABC угол C равен 90°, BC = {b}, AC = {a}. Найдите tg B."
            hint = "Тангенс — отношение противолежащего катета к прилежащему."
            solution = [f"tg B = AC / BC = {a} / {b} = {display(value)}."]
        elif kind == 1:
            value = Fraction(a, hyp)
            text = f"В треугольнике ABC угол C равен 90°, AC = {a}, AB = {hyp}. Найдите sin B."
            hint = "Синус — отношение противолежащего катета к гипотенузе."
            solution = [f"sin B = AC / AB = {a} / {hyp} = {display(value)}."]
        else:
            value = Fraction(b, hyp)
            text = f"В треугольнике ABC угол C равен 90°, BC = {b}, AB = {hyp}. Найдите cos B."
            hint = "Косинус — отношение прилежащего катета к гипотенузе."
            solution = [f"cos B = BC / AB = {b} / {hyp} = {display(value)}."]
    elif n == 16:
        ratio = Fraction(b, a)
        value = Fraction(a)
        text = f"В треугольнике ABC угол C прямой, BC = {b}, sin A = {display(ratio)}. Найдите AB."
        hint = "Запишите синус угла A как отношение противолежащего катета к гипотенузе."
        solution = ["sin A = BC / AB.", f"AB = {b} / {display(ratio)} = {display(value)}."]
    elif n == 17:
        ratio = Fraction(b, p[2])
        value = a * ratio
        text = (
            f"В треугольнике ABC угол C равен 90°, AC = {a}, tg A = {display(ratio)}. Найдите BC."
        )
        hint = "Тангенс — отношение противолежащего катета к прилежащему."
        solution = ["tg A = BC / AC.", f"BC = {a} · {display(ratio)} = {display(value)}."]
    elif n == 18:
        value = Fraction(90 - a)
        text = (
            f"Один из острых углов прямоугольного треугольника равен {a}°. "
            f"Найдите другой острый угол. Ответ дайте в градусах."
        )
        hint = "Сумма острых углов прямоугольного треугольника равна 90°."
        solution = [f"Другой угол: 90° − {a}° = {display(value)}°."]
    elif n in (19, 20):
        value = Fraction(a * b, 2)
        text = (
            f"Катеты прямоугольного треугольника равны {a} и {b}. Найдите его площадь."
            if n == 19
            else f"Сторона треугольника равна {a}, а проведённая к ней высота равна "
            f"{b}. Найдите площадь треугольника."
        )
        hint = "Площадь треугольника — половина произведения основания на высоту."
        solution = [f"S = {a} · {b} / 2 = {display(value)}."]
    elif n == 21:
        nu, de = p[2:]
        value = Fraction(a * b * nu, 2 * de)
        text = (
            f"В треугольнике ABC AB = {a}, BC = {b}, sin ∠ABC = "
            f"{display(Fraction(nu, de))}. Найдите площадь ABC."
        )
        hint = "Используйте площадь через две стороны и синус угла между ними."
        solution = [
            f"S = AB · BC · sin B / 2 = {a} · {b} · {display(Fraction(nu, de))} "
            f"/ 2 = {display(value)}."
        ]
    elif n == 22:
        k, nu, de = p
        value = Fraction(nu, de)
        rad = de * de - nu * nu
        height = str(k * isqrt(rad)) if isqrt(rad) ** 2 == rad else f"{k}√{rad}"
        text = (
            f"В прямоугольном треугольнике ABC катет AC = {k * de}, а высота "
            f"CH, опущенная на гипотенузу, равна {height}. Найдите sin ∠ABC."
        )
        hint = "Найдите AH по теореме Пифагора в треугольнике ACH. Сравните углы ABC и ACH."
        solution = [
            f"AH² = AC² − CH² = {k * de}² − ({height})² = {k * k * nu * nu}. "
            f"Значит, AH = {k * nu}.",
            "∠ABC = ∠ACH: их стороны соответственно перпендикулярны.",
            f"sin B = AH / AC = {k * nu} / {k * de} = {display(value)}.",
        ]
    else:
        raise ValueError("Unknown family")
    return text, [hint], solution, value


def content_key(n: int, p: tuple[int, ...]) -> tuple[int, ...]:
    """Exclude shape-only parameters and interchangeable given angle/leg order."""
    if n in (2, 8):
        return (p[0],)
    if n in (1, 19) or (n == 14 and p[2] == 0):
        return tuple(sorted(p[:2])) + (p[2:] if n == 14 else ())
    return p
