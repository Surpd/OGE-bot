"""Deterministic, exact generators and a rendered-text oracle for OGE task 12."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from math import isqrt
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import AnswerFormat, AnswerPolicy, decimal_places, format_decimal

GENERATOR_VERSION = "0.1.0"
MAX_GENERATION_ATTEMPTS = 64
MAX_CANDIDATES = 54
SEEDS_PER_FAMILY = 6

R001 = "OGE12-R001"
R002 = "OGE12-R002"
R003 = "OGE12-R003"
R004 = "OGE12-R004"
R005 = "OGE12-R005"
R006 = "OGE12-R006"
R007 = "OGE12-R007"
R008 = "OGE12-R008"
R009 = "OGE12-R009"
R010 = "OGE12-R010"
R011 = "OGE12-R011"
R012 = "OGE12-R012"
R013 = "OGE12-R013"
R014 = "OGE12-R014"
R015 = "OGE12-R015"
R016 = "OGE12-R016"
R017 = "OGE12-R017"

# These are the only structures whose task-12 source, target operation and
# answer shape are confirmed well enough for the first release.
ENABLED_FAMILIES = (R001, R002, R003, R004, R005, R010, R011, R012)
ALL_FAMILIES = tuple(f"OGE12-R{i:03d}" for i in range(1, 18))

POLICY = AnswerPolicy(
    "oge12.numeric-short",
    "1",
    AnswerFormat.SINGLE_NUMBER,
    max_decimal_places=10,
    max_absolute_value=10**12,
)
POLICIES_BY_SNAPSHOT = {
    (family, POLICY.policy_id, POLICY.version): POLICY for family in ALL_FAMILIES
}

SOURCE_IDS: dict[str, tuple[str, ...]] = {
    R001: ("480728",),
    R002: ("311920",),
    R003: ("357575",),
    R004: ("311824",),
    R005: ("311543",),
    R006: ("311348",),
    R007: ("311528",),
    R008: ("311530",),
    R009: ("311541",),
    R010: ("474304",),
    R011: ("459974",),
    R012: ("459972",),
    R013: ("450510",),
    R014: ("124",),
    R015: ("98",),
    R016: ("311537",),
    R017: ("311538",),
}


@dataclass(frozen=True, slots=True)
class FormulaProblem:
    problem_id: str
    seed: int
    generator_version: str
    family_id: str
    reference_ids: tuple[str, ...]
    variables: dict[str, str]
    formula: str
    target: str
    units: dict[str, str]
    constraints: tuple[str, ...]
    condition: str
    exact_value: Fraction
    correct_answer: str
    answer_policy_id: str
    answer_policy_version: str
    hints: tuple[str, ...]
    solution: tuple[str, ...]
    fingerprint: str
    generation_attempts: int = 1

    def to_snapshot(self) -> dict[str, object]:
        return {
            "problem_id": self.problem_id,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "family_id": self.family_id,
            "reference_ids": list(self.reference_ids),
            "variables": self.variables,
            "formula": self.formula,
            "target": self.target,
            "units": self.units,
            "constraints": list(self.constraints),
            "condition": self.condition,
            "exact_numerator": self.exact_value.numerator,
            "exact_denominator": self.exact_value.denominator,
            "correct_answer": self.correct_answer,
            "answer_policy_id": self.answer_policy_id,
            "answer_policy_version": self.answer_policy_version,
            "hints": list(self.hints),
            "solution": list(self.solution),
            "fingerprint": self.fingerprint,
            "generation_attempts": self.generation_attempts,
        }


def _f(value: int | Fraction) -> str:
    return format_decimal(Fraction(value))


def _exact_text(value: Fraction) -> str:
    return (
        _f(value) if decimal_places(value) is not None else f"{value.numerator}/{value.denominator}"
    )


def _format_tenths(value: Fraction) -> str:
    tenths = _round_tenths(value) * 10
    units = tenths.numerator // tenths.denominator
    sign = "-" if units < 0 else ""
    units = abs(units)
    return f"{sign}{units // 10},{units % 10}"


def _round_tenths(value: Fraction) -> Fraction:
    scaled = value * 10
    sign = -1 if scaled < 0 else 1
    quotient, remainder = divmod(abs(scaled.numerator), scaled.denominator)
    if remainder * 2 >= scaled.denominator:
        quotient += 1
    return Fraction(sign * quotient, 10)


def _sample(
    family: str, rng: random.Random
) -> tuple[dict[str, Fraction], str, str, str, tuple[str, ...], tuple[str, ...]]:
    if family == R001:
        current = Fraction(rng.randint(1, 400), 20)
        resistance = Fraction(rng.randint(1, 100))
        power = current * current * resistance
        values = {"P_W": power, "I_A": current}
        formula, target = "P = I²·R", "R"
        first = f"P = I²·R. Сопротивление R измеряется в омах, сила тока I — в амперах. Мощность P равна {_f(power)} Вт, а сила тока I равна {_f(current)} А. Найдите сопротивление R. Ответ дайте в омах."  # noqa: E501
        hints = (
            "Искомое сопротивление стоит множителем рядом с квадратом силы тока.",
            "Выразите R делением мощности P на I².",
        )
        solution = (
            "Формула: P = I²·R.",
            "Выразим сопротивление: R = P/I².",
            f"Подставим значения: R = {_f(power)}/({_f(current)})².",
            f"Получаем R = {_f(resistance)} Ом.",
        )
        return values, formula, target, first, hints, solution
    if family == R002:
        omega = Fraction(rng.randint(2, 30))
        radius = Fraction(rng.randint(1, 80))
        acceleration = omega * omega * radius
        values = {"a": acceleration, "omega": omega}
        formula = "a = ω²·R"
        condition = f"Центростремительное ускорение a (в м/с²) вычисляют по формуле a = ω²·R, где ω — угловая скорость в с⁻¹, R — радиус в метрах. Если ω = {_f(omega)} с⁻¹ и a = {_f(acceleration)} м/с², найдите R в метрах."  # noqa: E501
        return (
            values,
            formula,
            "R",
            condition,
            (
                "Найдите в формуле множитель R.",
                "Разделите ускорение a на квадрат угловой скорости ω.",
            ),
            (
                "Формула: a = ω²·R.",
                "Выразим радиус: R = a/ω².",
                f"Подставим: R = {_f(acceleration)}/({_f(omega)})² = {_f(radius)} м.",
            ),
        )
    if family == R003:
        celsius = Fraction(rng.randint(-100, 100))
        fahrenheit = Fraction(9, 5) * celsius + 32
        condition = f"Температуру по Фаренгейту вычисляют по формуле F = 1,8·C + 32, где C — температура в градусах Цельсия, F — в градусах Фаренгейта. Какая температура по Фаренгейту соответствует {_f(celsius)} °C?"  # noqa: E501
        return (
            {"C": celsius},
            "F = 1,8·C + 32",
            "F",
            condition,
            ("Подставьте значение температуры C в формулу.", "Умножьте C на 1,8 и прибавьте 32."),
            (
                "Формула: F = 1,8·C + 32.",
                f"Подставим: F = 1,8·({_f(celsius)}) + 32.",
                f"Получаем F = {_f(fahrenheit)} °F.",
            ),
        )
    if family == R004:
        fahrenheit = Fraction(rng.randint(-100, 300))
        exact = (fahrenheit - 32) * Fraction(5, 9)
        rounded = _round_tenths(exact)
        condition = f"Температуры по шкалам Цельсия C и Фаренгейта F связаны формулой F = 1,8·C + 32. Найдите C, если F = {_f(fahrenheit)} °F. Ответ округлите до десятых."  # noqa: E501
        return (
            {"F": fahrenheit},
            "F = 1,8·C + 32",
            "C",
            condition,
            (
                "Выразите C из формулы перевода температур.",
                "Вычтите 32 из F и разделите на 1,8; затем округлите до десятых.",
            ),
            (
                "Формула: F = 1,8·C + 32.",
                f"Выразим C: C = (F − 32)/1,8 = ({_f(fahrenheit)} − 32)/1,8.",
                f"Точное значение: C = {_exact_text(exact)} °C.",
                f"После округления до десятых: C = {_f(rounded)} °C.",
            ),
        )
    if family == R005:
        d1 = Fraction(rng.randint(1, 6) * 10)
        d2 = Fraction(rng.randint(2, 60))
        denominator = rng.choice((2, 4, 5, 8, 10))
        numerator = rng.randint(1, denominator)
        sine = Fraction(numerator, denominator)
        area = d1 * d2 * sine / 2
        condition = f"Площадь выпуклого четырёхугольника вычисляют по формуле S = d₁·d₂·sin(α)/2, где d₁ и d₂ — диагонали, α — угол между ними. Найдите sin(α), если S = {_f(area)}, d₁ = {_f(d1)}, d₂ = {_f(d2)}."  # noqa: E501
        return (
            {"S": area, "d1": d1, "d2": d2},
            "S = d₁·d₂·sin(α)/2",
            "sin_alpha",
            condition,
            (
                "В формуле неизвестен множитель sin(α).",
                "Умножьте площадь на 2 и разделите на произведение диагоналей.",
            ),
            (
                "Формула: S = d₁·d₂·sin(α)/2.",
                "Выразим синус: sin(α) = 2S/(d₁·d₂).",
                f"Подставим: sin(α) = 2·{_f(area)}/({_f(d1)}·{_f(d2)}) = {_f(sine)}.",
            ),
        )
    if family == R006:
        d1, d2 = Fraction(rng.randint(1, 80)), Fraction(rng.randint(1, 80))
        area = d1 * d2 / 2
        return (
            {"S": area, "d2": d2},
            "S = d₁·d₂/2",
            "d1",
            f"Площадь ромба S (в м²) равна d₁·d₂/2, где d₁ и d₂ — диагонали в метрах. Найдите d₁, если S = {_f(area)} м², d₂ = {_f(d2)} м.",  # noqa: E501
            (
                "Найдите неизвестную диагональ из формулы площади ромба.",
                "Умножьте S на 2 и разделите на d₂.",
            ),
            (
                "Формула: S = d₁·d₂/2.",
                "Выразим d₁: d₁ = 2S/d₂.",
                f"Подставим: d₁ = 2·{_f(area)}/{_f(d2)} = {_f(d1)} м.",
            ),
        )
    if family == R007:
        side, height = Fraction(rng.randint(1, 80)), Fraction(rng.randint(1, 80))
        area = side * height / 2
        return (
            {"S": area, "h": height},
            "S = a·h/2",
            "a",
            f"Площадь треугольника S (в м²) вычисляется по формуле S = a·h/2, где h — высота к стороне a. Найдите сторону a, если S = {_f(area)} м², h = {_f(height)} м.",  # noqa: E501
            (
                "Неизвестна сторона, умноженная на высоту.",
                "Умножьте площадь на 2 и разделите на высоту.",
            ),
            (
                "Формула: S = a·h/2.",
                "Выразим сторону: a = 2S/h.",
                f"Подставим: a = 2·{_f(area)}/{_f(height)} = {_f(side)} м.",
            ),
        )
    if family == R008:
        a, b, height = (
            Fraction(rng.randint(1, 50)),
            Fraction(rng.randint(1, 50)),
            Fraction(rng.randint(1, 60)),
        )
        area = (a + b) * height / 2
        return (
            {"S": area, "a": a, "b": b},
            "S = (a+b)·h/2",
            "h",
            f"Площадь трапеции S (в м²) вычисляют по формуле S = (a+b)·h/2, где a и b — основания, h — высота. Найдите h, если a = {_f(a)} м, b = {_f(b)} м, S = {_f(area)} м².",  # noqa: E501
            (
                "Сначала сложите оба основания в скобках.",
                "Умножьте площадь на 2 и разделите на сумму оснований.",
            ),
            (
                "Формула: S = (a+b)·h/2.",
                f"Выразим высоту: h = 2S/(a+b) = 2·{_f(area)}/({_f(a)}+{_f(b)}).",
                f"Получаем h = {_f(height)} м.",
            ),
        )
    if family == R009:
        height, base_area = Fraction(rng.randint(1, 60)), Fraction(rng.randint(1, 50) * 3)
        volume = base_area * height / 3
        return (
            {"V": volume, "S": base_area},
            "V = S·h/3",
            "h",
            f"Объём пирамиды V вычисляют по формуле V = S·h/3, где S — площадь основания, h — высота. Найдите высоту, если V = {_f(volume)} м³, S = {_f(base_area)} м².",  # noqa: E501
            (
                "В формуле неизвестна высота пирамиды.",
                "Умножьте объём на 3 и разделите на площадь основания.",
            ),
            (
                "Формула: V = S·h/3.",
                "Выразим высоту: h = 3V/S.",
                f"Подставим: h = 3·{_f(volume)}/{_f(base_area)} = {_f(height)} м.",
            ),
        )
    if family == R010:
        mass, speed = Fraction(rng.randint(1, 50) * 100), Fraction(rng.randint(2, 100))
        energy = mass * speed * speed / 2
        energy_text = (
            f"{_f(energy / 1000)} тысяч Дж"
            if energy.denominator == 1 and energy.numerator % 1000 == 0
            else f"{_f(energy)} Дж"
        )
        condition = f"Кинетическая энергия E автомобиля массой m равна m·v²/2, где m — масса в килограммах, v — скорость в метрах в секунду, E — энергия в джоулях. Найдите скорость автомобиля массой {_f(mass)} кг, если E = {energy_text}. Ответ дайте в метрах в секунду."  # noqa: E501
        return (
            {"E_J": energy, "m_kg": mass},
            "E = m·v²/2",
            "v_nonnegative",
            condition,
            (
                "Искомая скорость входит в формулу в квадрате.",
                "Выразите v как неотрицательный квадратный корень из 2E/m.",
            ),
            (
                "Формула: E = m·v²/2.",
                "Выразим скорость: v = √(2E/m).",
                f"Подставим: v = √(2·{_f(energy)} / {_f(mass)}) = {_f(speed)} м/с.",
            ),
        )
    if family == R011:
        mass, height = Fraction(rng.randint(1, 50)), Fraction(rng.randint(1, 100))
        energy = mass * Fraction(49, 5) * height
        condition = f"Потенциальная энергия тела P (в джоулях) вычисляется по формуле P = m·g·h, где g = 9,8 м/с², m — масса в килограммах, h — высота в метрах. Найдите массу тела, если P = {_f(energy)} Дж и h = {_f(height)} м."  # noqa: E501
        return (
            {"P_J": energy, "h_m": height, "g": Fraction(49, 5)},
            "P = m·g·h",
            "m",
            condition,
            (
                "Выразите массу из формулы потенциальной энергии.",
                "Разделите энергию P на произведение g·h.",
            ),
            (
                "Формула: P = m·g·h.",
                "Выразим массу: m = P/(g·h).",
                f"Подставим: m = {_f(energy)}/(9,8·{_f(height)}) = {_f(mass)} кг.",
            ),
        )
    if family == R012:
        volume = Fraction(rng.randint(1, 500), 100)
        force = Fraction(1000) * Fraction(49, 5) * volume
        condition = f"Сила Архимеда F для тела в воде равна ρ·g·V, где ρ = 1000 кг/м³, g = 9,8 м/с², V — объём в м³. Найдите F для тела объёмом {_f(volume)} м³. Ответ дайте в ньютонах."  # noqa: E501
        return (
            {"rho": Fraction(1000), "g": Fraction(49, 5), "V": volume},
            "F = ρ·g·V",
            "F",
            condition,
            (
                "Подставьте плотность воды, ускорение свободного падения и объём.",
                "Перемножьте ρ, g и V.",
            ),
            (
                "Формула: F = ρ·g·V.",
                f"Подставим: F = 1000·9,8·{_f(volume)}.",
                f"Получаем F = {_f(force)} Н.",
            ),
        )
    if family == R013:
        capacitance, voltage = Fraction(1, 10000), Fraction(rng.randint(1, 200))
        energy = capacitance * voltage * voltage / 2
        return (
            {"C_F": capacitance, "U_V": voltage},
            "W = C·U²/2",
            "W",
            f"Энергия конденсатора W (в джоулях) вычисляется по формуле W = C·U²/2, где C — ёмкость в фарадах, U — напряжение в вольтах. Найдите W, если C = 10⁻⁴ Ф и U = {_f(voltage)} В.",  # noqa: E501
            (
                "Напряжение в формуле возводится в квадрат.",
                "Умножьте ёмкость на U² и разделите на 2.",
            ),
            (
                "Формула: W = C·U²/2.",
                f"Подставим: W = 10⁻⁴·({_f(voltage)})²/2.",
                f"Получаем W = {_f(energy)} Дж.",
            ),
        )
    if family == R014:
        count, fixed, per_ring = rng.randint(1, 100), Fraction(6000), Fraction(4100)
        cost = fixed + per_ring * count
        return (
            {"a": fixed, "b": per_ring, "n": Fraction(count)},
            "C = a + b·n",
            "C",
            f"Стоимость колодца C (в рублях) равна a+b·n, где a — фиксированная часть, b — стоимость кольца, n — число колец. Найдите C для колодца из {count} колец, если a = 6000 руб. и b = 4100 руб.",  # noqa: E501
            (
                "Разделите стоимость на фиксированную и зависящую от числа колец части.",
                "Умножьте цену одного кольца на их число и прибавьте фиксированную стоимость.",
            ),
            (
                "Формула: C = a+b·n.",
                f"Подставим: C = 6000 + 4100·{count}.",
                f"Получаем C = {_f(cost)} руб.",
            ),
        )
    if family == R015:
        time = Fraction(rng.randint(6, 120))
        cost = Fraction(150) + 11 * (time - 5)
        return (
            {"a": Fraction(150), "b": Fraction(11), "t": time, "t0": Fraction(5)},
            "C = a + b·(t−t₀)",
            "C",
            f"Стоимость поездки C (в рублях) при t > 5 минут вычисляют по формуле C = 150 + 11·(t−5), где t — время поездки в минутах. Найдите стоимость поездки длительностью {_f(time)} минут.",  # noqa: E501
            (
                "Сначала найдите длительность сверх первых пяти минут.",
                "Умножьте число дополнительных минут на 11 и прибавьте 150 рублей.",
            ),
            (
                "Формула: C = 150+11·(t−5), применима при t>5.",
                f"Подставим: C = 150+11·({_f(time)}−5).",
                f"Получаем C = {_f(cost)} руб.",
            ),
        )
    if family == R016:
        b, c = Fraction(rng.randint(2, 100)), Fraction(rng.randint(2, 100))
        angle = rng.choice((30, 90, 150))
        sine = Fraction(1, 2) if angle in (30, 150) else Fraction(1)
        area = b * c * sine / 2
        return (
            {"b": b, "c": c, "sin_alpha": sine, "angle_degrees": Fraction(angle)},
            "S = b·c·sin(α)/2",
            "S",
            f"Площадь треугольника S вычисляют по формуле S = b·c·sin(α)/2, где b и c — стороны, α — угол между ними. Найдите S, если b = {_f(b)}, c = {_f(c)}, α = {angle}°.",  # noqa: E501
            (
                "Для начала определите sin заданного угла.",
                "Подставьте стороны и значение синуса в формулу площади.",
            ),
            (
                f"Угол α = {angle}°, поэтому sin(α) = {_f(sine)}.",
                "Формула: S = b·c·sin(α)/2.",
                f"Подставим: S = {_f(b)}·{_f(c)}·{_f(sine)}/2 = {_f(area)}.",
            ),
        )
    if family == R017:
        scale = rng.randint(1, 1000)
        a, b, c = Fraction(3 * scale), Fraction(4 * scale), Fraction(5 * scale)
        radius, area = Fraction(scale), Fraction(6 * scale * scale)
        return (
            {"S": area, "a": a, "b": b, "r": radius},
            "S = (a+b+c)·r/2",
            "c",
            f"Площадь треугольника S связана со сторонами и радиусом вписанной окружности формулой S = (a+b+c)·r/2. Найдите c, если S = {_f(area)}, a = {_f(a)}, b = {_f(b)}, r = {_f(radius)}.",  # noqa: E501
            (
                "Выразите периметр через S и r, затем найдите неизвестную сторону.",
                "Сложите известные стороны и вычтите их из 2S/r.",
            ),
            (
                "Формула: S = (a+b+c)·r/2.",
                "Выразим c: c = 2S/r − a − b.",
                f"Подставим: c = 2·{_f(area)}/{_f(radius)} − {_f(a)} − {_f(b)} = {_f(c)}.",
            ),
        )
    raise ValueError(f"Unknown OGE-12 family: {family}")


def _displayed_parameters(family: str, condition: str) -> dict[str, Fraction] | None:
    """Extract numeric givens from the student-facing condition, not model state."""
    if family == R010:
        mass = re.search(r"массой\s+([\d,.]+)\s*кг", condition)
        energy = re.search(
            r"(?:если\s+E\s*=|энергией)\s*([\d,.]+)(\s*тысяч\s*Дж|\s*Дж)",
            condition,
            re.IGNORECASE,
        )
        if mass is not None and energy is not None:
            mass_value = Fraction(mass.group(1).replace(",", "."))
            energy_value = Fraction(energy.group(1).replace(",", "."))
            if "тысяч" in energy.group(2).lower():
                energy_value *= 1000
            return {"m_kg": mass_value, "E_J": energy_value}
    patterns: dict[str, tuple[str, ...]] = {
        R001: (
            r"Мощность P равна ([\d,.]+) Вт, а сила тока I равна ([\d,.]+) А",
            r"P = ([\d,.]+) Вт, а I = ([\d,.]+) А",
        ),
        R002: (r"ω = ([\d,.]+) с⁻¹ и a = ([\d,.]+) м/с²",),
        R003: (r"соответствует (?:температура )?([−-]?[\d,.]+) °C",),
        R004: (r"F = ([−-]?[\d,.]+) °F",),
        R005: (r"S = ([\d,.]+), d₁ = ([\d,.]+), d₂ = ([\d,.]+)",),
        R006: (r"S = ([\d,.]+) м², d₂ = ([\d,.]+) м",),
        R007: (r"S = ([\d,.]+) м², h = ([\d,.]+) м",),
        R008: (r"a = ([\d,.]+) м, b = ([\d,.]+) м, S = ([\d,.]+) м²",),
        R009: (r"V = ([\d,.]+) м³,\s*(?:а\s*)?S = ([\d,.]+) м²",),
        R010: (
            r"массой ([\d,.]+) кг, если E = ([\d,.]+)( тысяч Дж| Дж)",
            r"массой ([\d,.]+) кг[^.]*энергией ([\d,.]+)( тысяч Дж| Дж)",
        ),
        R011: (r"[PE] = ([\d,.]+) Дж и h = ([\d,.]+) м",),
        R012: (r"объёмом ([\d,.]+) м³",),
        R013: (r"U = ([\d,.]+) В",),
        R014: (
            r"из ([\d]+) колец, если a = ([\d,.]+) руб\. и b = ([\d,.]+) руб\.",
            r"C = ([\d,.]+) \+ ([\d,.]+)·n.*?из ([\d]+) колец",
        ),
        R015: (r"длительностью ([\d,.]+) минут",),
        R016: (r"b = ([\d,.]+), c = ([\d,.]+), α = ([\d]+)°",),
        R017: (r"S = ([\d,.]+), a = ([\d,.]+), b = ([\d,.]+), r = ([\d,.]+)",),
    }
    for pattern_index, pattern in enumerate(patterns[family]):
        match = re.search(pattern, condition)
        if match:
            raw = [
                group for group in match.groups() if group is not None and not group.startswith(" ")
            ]
            values = [Fraction(value.replace("−", "-").replace(",", ".")) for value in raw]
            keys = {
                R001: ("P_W", "I_A"),
                R002: ("omega", "a"),
                R003: ("C",),
                R004: ("F",),
                R005: ("S", "d1", "d2"),
                R006: ("S", "d2"),
                R007: ("S", "h"),
                R008: ("a", "b", "S"),
                R009: ("V", "S"),
                R010: ("m_kg", "E_J"),
                R011: ("P_J", "h_m"),
                R012: ("V",),
                R013: ("U_V",),
                R014: ("n", "a", "b"),
                R015: ("t",),
                R016: ("b", "c", "angle_degrees"),
                R017: ("S", "a", "b", "r"),
            }[family]
            if family == R014 and pattern_index == 1:
                keys = ("a", "b", "n")
            result = dict(zip(keys, values, strict=True))
            if family == R010 and "тысяч" in condition:
                result["E_J"] *= 1000
            return result
    return None


def solve_rendered_condition(family_id: str, condition: str) -> Fraction | None:
    """Independent formula dispatch from parsed displayed values."""
    if (
        family_id not in ALL_FAMILIES
        or not _formula_and_units_present(family_id, condition)
        or not _target_asked(family_id, condition)
    ):
        return None
    v = _displayed_parameters(family_id, condition)
    if v is None:
        return None
    try:
        if family_id == R001:
            if v["I_A"] == 0 or "Вт" not in condition or "ом" not in condition.lower():
                return None
            result = v["P_W"] / v["I_A"] ** 2
        elif family_id == R002:
            if v["omega"] == 0 or "с⁻¹" not in condition or "м/с²" not in condition:
                return None
            result = v["a"] / v["omega"] ** 2
        elif family_id == R003:
            result = Fraction(9, 5) * v["C"] + 32
        elif family_id == R004:
            if "Ответ округлите до десятых." not in condition:
                return None
            result = _round_tenths((v["F"] - 32) * Fraction(5, 9))
        elif family_id == R005:
            result = 2 * v["S"] / (v["d1"] * v["d2"])
            if not 0 < result <= 1:
                return None
        elif family_id == R006:
            result = 2 * v["S"] / v["d2"]
        elif family_id == R007:
            result = 2 * v["S"] / v["h"]
        elif family_id == R008:
            result = 2 * v["S"] / (v["a"] + v["b"])
        elif family_id == R009:
            result = 3 * v["V"] / v["S"]
        elif family_id == R010:
            if v["m_kg"] <= 0 or v["E_J"] < 0:
                return None
            square = Fraction(2) * v["E_J"] / v["m_kg"]
            if (
                isqrt(square.numerator) ** 2 != square.numerator
                or isqrt(square.denominator) ** 2 != square.denominator
            ):
                return None
            result = Fraction(isqrt(square.numerator), isqrt(square.denominator))
            if result < 0:
                return None
        elif family_id == R011:
            if v["h_m"] <= 0:
                return None
            result = v["P_J"] / (Fraction(49, 5) * v["h_m"])
        elif family_id == R012:
            result = 1000 * Fraction(49, 5) * v["V"]
        elif family_id == R013:
            if not re.search(r"C = 10⁻⁴ Ф", condition):
                return None
            result = Fraction(1, 10000) * v["U_V"] ** 2 / 2
        elif family_id == R014:
            result = v["a"] + v["b"] * v["n"]
        elif family_id == R015:
            if v["t"] <= 5:
                return None
            result = 150 + 11 * (v["t"] - 5)
        elif family_id == R016:
            angle = v["angle_degrees"]
            if angle not in (30, 90, 150):
                return None
            sine = Fraction(1) if angle == 90 else Fraction(1, 2)
            result = v["b"] * v["c"] * sine / 2
        else:
            c = 2 * v["S"] / v["r"] - v["a"] - v["b"]
            if c <= 0 or not (v["a"] + v["b"] > c and v["a"] + c > v["b"] and v["b"] + c > v["a"]):
                return None
            semiperimeter = (v["a"] + v["b"] + c) / 2
            area_square = (
                semiperimeter
                * (semiperimeter - v["a"])
                * (semiperimeter - v["b"])
                * (semiperimeter - c)
            )
            if (
                area_square < 0
                or isqrt(area_square.numerator) ** 2 != area_square.numerator
                or isqrt(area_square.denominator) ** 2 != area_square.denominator
            ):
                return None
            area = Fraction(isqrt(area_square.numerator), isqrt(area_square.denominator))
            if area != v["S"] or area / semiperimeter != v["r"]:
                return None
            result = c
    except (KeyError, ZeroDivisionError, ValueError):
        return None
    return result


def _formula_and_units_present(family: str, condition: str) -> bool:
    rendered = condition.lower()
    compact = re.sub(r"\s+", "", rendered)
    required: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
        R001: (("p=i²·r",), ("вт", "а", "ом")),
        R002: (("a=ω²·r",), ("м/с²", "с⁻¹", "радиус")),
        R003: (("f=1,8·c+32",), ("°c", "фаренгейт")),
        R004: (("f=1,8·c+32",), ("°f", "десятых")),
        R005: (("sin(α)", "sinα"), ("четырёхугольника", "d₁", "d₂")),
        R006: (("d₁·d₂/2",), ("ромба", "м²")),
        R007: (("a·h/2",), ("треугольника", "м²")),
        R008: (("(a+b)·h/2",), ("трапеции", "м²")),
        R009: (("s·h/3",), ("пирамиды", "м³")),
        R010: (("m·v²/2",), ("кинетическая энергия", "кг")),
        R011: (("m·g·h",), ("потенциальная энергия", "9,8 м/с²")),
        R012: (("ρ·g·v",), ("архимеда", "1000 кг/м³", "ньютон")),
        R013: (("w=c·u²/2",), ("10⁻⁴ ф", "вольтах")),
        R014: (("a+b·n", "6000+4100·n"), ("колодца", "колец")),
        R015: (("150+11·(t−5)",), ("поездки", "минут")),
        R016: (("b·c·sinα/2", "b·c·sin(α)/2"), ("треугольника", "угол")),
        R017: (("(a+b+c)·r/2",), ("вписанной окружности",)),
    }
    formulas, context = required[family]
    if not any(signature.lower() in compact for signature in formulas):
        return False
    if not all(token.lower() in rendered for token in context):
        return False
    if family == R015 and "t > 5" not in rendered and "больше 5 минут" not in rendered:
        return False
    if family == R017 and "сторонами" not in rendered and "стороны" not in rendered:
        return False
    if family == R010 and "метрах в секунду" not in rendered and "м/с" not in rendered:
        return False
    return True


def _target_asked(family: str, condition: str) -> bool:
    text = condition.lower()
    patterns = {
        R001: r"найдите сопротивление\s*r",
        R002: r"найдите\s*r",
        R003: r"(?:какая температура по фаренгейту|скольким градусам фаренгейта)",
        R004: r"(?:найдите\s*c|температуру по цельсию)",
        R005: r"найдите\s*sin\s*\(?α\)?",
        R006: r"(?:найдите|вычислите)\s*d₁",
        R007: r"(?:найдите|вычислите)\s*(?:сторону\s*)?a\b",
        R008: r"найдите\s*h\b",
        R009: r"найдите высоту",
        R010: r"найдите (?:его )?скорость",
        R011: r"найдите массу",
        R012: r"найдите\s*f\b|найдите силу архимеда",
        R013: r"найдите\s*w\b",
        R014: r"(?:найдите\s*c|сколько будет стоить)",
        R015: r"(?:найдите стоимость|рассчитайте стоимость)",
        R016: r"найдите (?:площадь|s\b)",
        R017: r"(?:найдите|вычислите)\s*c\b",
    }
    return re.search(patterns[family], text) is not None


def validate_rendered_problem(problem: FormulaProblem) -> bool:
    values = _displayed_parameters(problem.family_id, problem.condition)
    if values is None or not _formula_and_units_present(problem.family_id, problem.condition):
        return False
    if solve_rendered_condition(problem.family_id, problem.condition) != POLICY.parse(
        problem.correct_answer
    ):
        return False
    for key, value in values.items():
        if (
            key not in problem.variables
            or Fraction(problem.variables[key].replace(",", ".")) != value
        ):
            return False
    if problem.family_id == R017:
        return len(problem.solution) >= 3 and f"{problem.correct_answer}" in problem.solution[-1]
    return bool(problem.solution and problem.correct_answer in problem.solution[-1])


Sample = tuple[dict[str, Fraction], str, str, str, tuple[str, ...], tuple[str, ...]]
Generator = Callable[[random.Random], Sample]


def _make_generator(family_id: str) -> Generator:
    def generate_for_family(rng: random.Random) -> Sample:
        return _sample(family_id, rng)

    return generate_for_family


_GENERATORS: dict[str, Generator] = {family: _make_generator(family) for family in ALL_FAMILIES}


def generate(
    family_id: str, seed: int, generator_version: str = GENERATOR_VERSION
) -> FormulaProblem:
    if generator_version != GENERATOR_VERSION:
        raise ValueError(f"Unsupported OGE-12 generator version: {generator_version}")
    if family_id not in _GENERATORS:
        raise ValueError(f"Unknown OGE-12 family: {family_id}")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    generator = _GENERATORS[family_id]
    for attempt in range(MAX_GENERATION_ATTEMPTS):
        rng = random.Random(f"oge12:{generator_version}:{family_id}:{seed + attempt}")
        variables, formula, target, condition, hints, solution = generator(rng)
        displayed = _displayed_parameters(family_id, condition)
        if displayed is None:
            continue
        exact = solve_rendered_condition(family_id, condition)
        if exact is None:
            continue
        places = decimal_places(exact)
        if (
            places is None
            or places > POLICY.max_decimal_places
            or abs(exact) > POLICY.max_absolute_value
        ):
            continue
        answer = _format_tenths(exact) if family_id == R004 else POLICY.format(exact)
        fingerprint_values = [
            family_id,
            sorted((key, _f(value)) for key, value in displayed.items()),
            formula,
            target,
        ]
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_values, separators=(",", ":")).encode()
        ).hexdigest()
        problem = FormulaProblem(
            problem_id=str(uuid5(NAMESPACE_URL, f"oge12:{generator_version}:{family_id}:{seed}")),
            seed=seed,
            generator_version=generator_version,
            family_id=family_id,
            reference_ids=SOURCE_IDS[family_id],
            variables={key: _f(value) for key, value in variables.items()},
            formula=formula,
            target=target,
            units={"answer": _answer_unit(family_id)},
            constraints=_constraints(family_id),
            condition=condition,
            exact_value=exact,
            correct_answer=answer,
            answer_policy_id=POLICY.policy_id,
            answer_policy_version=POLICY.version,
            hints=hints,
            solution=solution,
            fingerprint=fingerprint,
            generation_attempts=attempt + 1,
        )
        if validate_rendered_problem(problem):
            return problem
    raise RuntimeError(f"Bounded generation failed for {family_id} at seed {seed}")


def _answer_unit(family: str) -> str:
    return {
        R001: "Ом",
        R002: "м",
        R003: "°F",
        R004: "°C",
        R005: "",
        R006: "м",
        R007: "м",
        R008: "м",
        R009: "м",
        R010: "м/с",
        R011: "кг",
        R012: "Н",
        R013: "Дж",
        R014: "руб.",
        R015: "руб.",
        R016: "м²",
        R017: "",
    }[family]


def _constraints(family: str) -> tuple[str, ...]:
    return {
        R001: ("I ≠ 0", "P ≥ 0", "R ≥ 0"),
        R002: ("ω ≠ 0", "a ≥ 0", "R > 0"),
        R003: ("Температура может быть отрицательной",),
        R004: ("Округление до десятых, half-up; точное вычисление через Fraction",),
        R005: ("d₁,d₂,S > 0", "0 < sin(α) ≤ 1"),
        R006: ("d₁,d₂,S > 0",),
        R007: ("a,h,S > 0",),
        R008: ("a,b,h,S > 0",),
        R009: ("S,h,V > 0",),
        R010: ("m > 0", "E ≥ 0", "v — неотрицательный точный квадратный корень"),
        R011: ("m,h > 0", "g = 9,8 м/с²"),
        R012: ("ρ = 1000 кг/м³", "g = 9,8 м/с²", "V > 0"),
        R013: ("C = 10⁻⁴ Ф", "U > 0"),
        R014: ("n — целое положительное",),
        R015: ("t > 5 минут",),
        R016: ("α ∈ {30°, 90°, 150°}", "b,c > 0"),
        R017: ("Неравенства треугольника", "Площадь по формуле Герона", "r = S/s"),
    }[family]


def check_answer(
    family_id: str, policy_id: str, policy_version: str, text: str, expected: str
) -> bool:
    policy = POLICIES_BY_SNAPSHOT.get((family_id, policy_id, policy_version))
    return policy is not None and policy.accepts(text, expected)
