"""Deterministic OGE-14 progression variants and independent text audit."""

# Fixed Russian exam-style templates and their strict regex counterparts are
# intentionally kept as single source-visible strings.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from fractions import Fraction
from uuid import NAMESPACE_URL, uuid5

from app.math.answer_policy import AnswerFormat, AnswerPolicy, decimal_places, format_decimal

GENERATOR_VERSION = "0.1.0"
MAX_GENERATION_ATTEMPTS = 64
MAX_CANDIDATES = 54
SEEDS_PER_FAMILY = 6

A01, A02, A03, A04, A05, A06, A07, A08, A09, A10, A11, G01, G02, G03, G04 = (
    f"OGE14-{family}"
    for family in (
        "A01",
        "A02",
        "A03",
        "A04",
        "A05",
        "A06",
        "A07",
        "A08",
        "A09",
        "A10",
        "A11",
        "G01",
        "G02",
        "G03",
        "G04",
    )
)
ALL_FAMILIES = (A01, A02, A03, A04, A05, A06, A07, A08, A09, A10, A11, G01, G02, G03, G04)
# Families are enabled only after their automated corpus gates pass.
ENABLED_FAMILIES: tuple[str, ...] = ()
FAMILY_STATUS = {family: "disabled_pending_quality_gates" for family in ALL_FAMILIES}
FAMILY_STATUS[A04] = "disabled_hold_historical_topic"
FAMILY_STATUS[A11] = "disabled_hold_degenerate_progression"
FAMILY_STATUS[A06] = "disabled_bounded_capacity_acceptance_review"

POLICY = AnswerPolicy(
    "oge14.numeric-short",
    "1",
    AnswerFormat.SINGLE_NUMBER,
    max_decimal_places=2,
    max_absolute_value=100_000,
)
POLICIES_BY_SNAPSHOT = {
    (family, POLICY.policy_id, POLICY.version): POLICY for family in ALL_FAMILIES
}

SOURCE_IDS: dict[str, tuple[str, ...]] = {
    A01: ("412190", "412187", "412237"),
    A02: ("412241", "449740"),
    A03: ("406645", "412286"),
    A04: ("412276", "412233"),
    A05: ("412218",),
    A06: ("459977",),
    A07: ("463386",),
    A08: ("459978",),
    A09: ("394279",),
    A10: ("FIPI-MR-2024-P7",),
    A11: ("406337",),
    G01: ("412192", "412266", "480730"),
    G02: ("412195",),
    G03: ("412198",),
    G04: ("412224", "459975"),
}
SOURCE_URLS = {
    family: tuple(
        "https://doc.fipi.ru/navigator-podgotovki/navigator-oge/MR_matematika_oge_2024.pdf"
        if source.startswith("FIPI")
        else f"https://math-oge.sdamgia.ru/problem?id={source}"
        for source in ids
    )
    for family, ids in SOURCE_IDS.items()
}


def _fmt(value: int | Fraction) -> str:
    return format_decimal(Fraction(value))


def _exact_fmt(value: Fraction) -> str:
    try:
        return _fmt(value)
    except ValueError:
        return f"{value.numerator}/{value.denominator}"


def _place_word(value: int) -> str:
    n = abs(value)
    if 11 <= n % 100 <= 14:
        return "мест"
    return {1: "место", 2: "места", 3: "места", 4: "места"}.get(n % 10, "мест")


def _minute_word(value: int) -> str:
    n = abs(value)
    if 11 <= n % 100 <= 14:
        return "минут"
    if n % 10 == 1:
        return "минуту"
    if 2 <= n % 10 <= 4:
        return "минуты"
    return "минут"


def _seconds_word(value: int) -> str:
    n = abs(value)
    if 11 <= n % 100 <= 14:
        return "секунд"
    if 2 <= n % 10 <= 4:
        return "секунды"
    return "секунд"


def _situps_word(value: int) -> str:
    n = abs(value)
    if 11 <= n % 100 <= 14:
        return "приседаний"
    if n % 10 == 1:
        return "приседание"
    if 2 <= n % 10 <= 4:
        return "приседания"
    return "приседаний"


def _days_word(value: int) -> str:
    n = abs(value)
    if 11 <= n % 100 <= 14:
        return "дней"
    if n % 10 == 1:
        return "день"
    if 2 <= n % 10 <= 4:
        return "дня"
    return "дней"


@dataclass(frozen=True, slots=True)
class ProgressionProblem:
    problem_id: str
    seed: int
    generator_version: str
    family_id: str
    reference_ids: tuple[str, ...]
    parameters: dict[str, int]
    condition: str
    exact_value: Fraction
    correct_answer: str
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
            "content_provenance": "generated_analogue",
            "reference_ids": list(self.reference_ids),
            "parameters": dict(self.parameters),
            "condition": self.condition,
            "exact_numerator": self.exact_value.numerator,
            "exact_denominator": self.exact_value.denominator,
            "correct_answer": self.correct_answer,
            "answer_policy_id": POLICY.policy_id,
            "answer_policy_version": POLICY.version,
            "hints": list(self.hints),
            "solution": list(self.solution),
            "fingerprint": self.fingerprint,
            "generation_attempts": self.generation_attempts,
        }


def _sample(family: str, rng: random.Random) -> dict[str, int]:
    if family == A01:
        rows, a1, d = rng.randint(10, 20), rng.randint(12, 30), rng.randint(1, 5)
        k = rng.randint(2, rows)
        return {"rows": rows, "a1": a1, "d": d, "k": k}
    if family == A02:
        rows, a1, d = rng.randint(10, 20), rng.randint(10, 25), rng.randint(1, 5)
        i, j = sorted(rng.sample(range(2, min(rows, 13) + 1), 2))
        return {"rows": rows, "a1": a1, "d": d, "i": i, "j": j}
    if family == A03:
        return {"rows": rng.randint(8, 18), "a1": rng.randint(10, 26), "d": rng.randint(1, 5)}
    if family == A05:
        t0, rate, minutes = rng.randint(-10, 25), rng.randint(1, 8), rng.randint(6, 15)
        return {"t0": t0, "rate": rate, "minutes": minutes, "t": rng.randint(1, minutes)}
    if family == A06:
        n, d = rng.randint(3, 8), rng.randint(2, 8)
        return {"n": n, "d": d, "a1": n * d}
    if family == A07:
        n = rng.randint(3, 8)
        d = rng.randint(2, min(7, 44 // (n - 1)))
        return {"n": n, "d": d, "a1": rng.randint((n - 1) * d + 1, 45)}
    if family == A08:
        return {"n": rng.randint(5, 12), "a1t": rng.randint(1, 12), "dt": rng.randint(2, 9)}
    if family == A09:
        n, a1, d = rng.randint(3, 12), rng.randint(10, 30), rng.randint(2, 6)
        return {"n": n, "a1": a1, "d": d}
    if family == A10:
        n, a1, d = rng.randint(7, 20), rng.randint(10, 40), rng.randint(2, 9)
        return {"n": n, "a1": a1, "d": d, "k": rng.randint(2, n - 1)}
    if family == G01:
        return {
            "m0": rng.randint(4, 25) * 2 ** rng.randint(2, 5),
            "cycles": rng.randint(2, 5),
            "period": rng.randint(5, 15),
        }
    if family == G02:
        return {
            "m0": rng.randint(2, 15),
            "factor": rng.randint(2, 3),
            "cycles": rng.randint(2, 4),
            "period": rng.randint(10, 30),
        }
    if family == G03:
        return {
            "m0": rng.randint(4, 25) * 2 ** rng.randint(2, 5),
            "cycles": rng.randint(1, 5),
            "period": rng.randint(5, 15),
        }
    if family == G04:
        return {
            "h1": rng.randint(40, 180) * 2,
            "factor": rng.choice((2, 3, 4)),
            "threshold": rng.randint(2, 15),
        }
    raise ValueError("Family has no generator")


def _model(family: str, p: dict[str, int]) -> Fraction:
    if family == A01:
        return Fraction(p["a1"] + (p["k"] - 1) * p["d"])
    if family == A02:
        return Fraction(p["a1"] + (p["rows"] - 1) * p["d"])
    if family == A03:
        return Fraction(p["rows"] * (2 * p["a1"] + (p["rows"] - 1) * p["d"]) // 2)
    if family == A05:
        return Fraction(p["t0"] - p["t"] * p["rate"])
    if family in {A06, A07}:
        return Fraction(sum(p["a1"] - i * p["d"] for i in range(p["n"])))
    if family == A08:
        return Fraction(p["n"] * (2 * p["a1t"] + (p["n"] - 1) * p["dt"]), 20)
    if family == A09:
        return Fraction(p["n"] * (2 * p["a1"] + (p["n"] - 1) * p["d"]) // 2)
    if family == A10:
        return Fraction(p["a1"] + (p["k"] - 1) * p["d"])
    if family == G01:
        return Fraction(p["m0"], 2 ** p["cycles"])
    if family == G02:
        return Fraction(p["m0"] * p["factor"] ** p["cycles"])
    if family == G03:
        return Fraction(p["m0"] - p["m0"] // (2 ** p["cycles"]))
    if family == G04:
        k = 1
        while Fraction(p["h1"], p["factor"] ** (k - 1)) >= p["threshold"]:
            k += 1
        return Fraction(k)
    raise ValueError("Family has no model")


def _render(family: str, p: dict[str, int]) -> str:
    if family == A01:
        return f"В амфитеатре {p['rows']} рядов. В первом ряду {p['a1']} {_place_word(p['a1'])}, и в каждом следующем на {p['d']} {_place_word(p['d'])} больше, чем в предыдущем. Сколько мест в {p['k']}-м ряду?"
    if family == A02:
        ai, aj = p["a1"] + (p["i"] - 1) * p["d"], p["a1"] + (p["j"] - 1) * p["d"]
        return f"В амфитеатре {p['rows']} рядов. В {p['i']}-м ряду {ai} мест, а в {p['j']}-м ряду {aj} мест. В каждом следующем ряду мест на одно и то же число больше. Сколько мест в последнем ряду?"
    if family == A03:
        return f"В амфитеатре {p['rows']} рядов. В первом ряду {p['a1']} {_place_word(p['a1'])}, и в каждом следующем на {p['d']} {_place_word(p['d'])} больше, чем в предыдущем. Сколько всего мест в амфитеатре?"
    if family == A05:
        return f"Температура вещества была {p['t0']} °C и каждую минуту равномерно уменьшалась на {p['rate']} °C. Какой была температура через {p['t']} {_minute_word(p['t'])}?"
    if family == A06:
        return f"При торможении автомобиль за первую секунду прошёл {p['a1']} м, а каждую следующую секунду тормозной путь уменьшался на {p['d']} м. Какой путь прошёл автомобиль с начала торможения до полной остановки?"
    if family == A07:
        return f"При торможении за первую секунду автомобиль прошёл {p['a1']} м, а каждую следующую секунду тормозной путь уменьшался на {p['d']} м. Какой путь автомобиль прошёл за первые {p['n']} {_seconds_word(p['n'])}?"
    if family == A08:
        return f"При разгоне поезд за первую секунду прошёл {_fmt(Fraction(p['a1t'], 10))} м, а за каждую следующую секунду проходил на {_fmt(Fraction(p['dt'], 10))} м больше, чем за предыдущую. Какой путь поезд прошёл за первые {p['n']} {_seconds_word(p['n'])}?"
    if family == A09:
        last_day = p["a1"] + (p["n"] - 1) * p["d"]
        total = _model(family, p)
        return f"Забор длиной {_fmt(total)} м нужно построить за несколько дней. В первый день построили {p['a1']} м, а в последний — {last_day} м. Каждый день строили на одинаковую длину больше, чем в предыдущий. За сколько дней построили забор?"
    if family == A10:
        total = _model(family, p)
        return f"За {p['n']} дней спортсмен сделал всего {int(total)} приседаний. Каждый день он делал на {p['d']} {_situps_word(p['d'])} больше, чем в предыдущий, а в первый день сделал {p['a1']}. Сколько приседаний он сделал в {p['k']}-й день?"
    if family == G01:
        t = p["cycles"] * p["period"]
        return f"Масса радиоактивного вещества в начальный момент была {p['m0']} мг. Каждые {p['period']} минут распадается половина вещества. Какова масса вещества через {t} минут?"
    if family == G02:
        t = p["cycles"] * p["period"]
        return f"Масса колонии микроорганизмов в начальный момент составляла {p['m0']} мг и каждые {p['period']} минут увеличивалась в {p['factor']} раза. Какой станет масса через {t} минут?"
    if family == G03:
        t = p["cycles"] * p["period"]
        return f"В начальный момент масса радиоактивного вещества А составляла {p['m0']} мг. Каждые {p['period']} минут половина вещества А превращается в вещество Б. Какова масса вещества Б через {t} минут?"
    if family == G04:
        return f"Мяч после удара отскакивает на высоту, в {p['factor']} раза меньшую, чем высота предыдущего отскока. Высота первого отскока равна {p['h1']} см. После какого по счёту отскока высота впервые станет меньше {p['threshold']} см?"
    raise ValueError("Family has no renderer")


def audit_condition(family: str, condition: str, parameters: dict[str, int]) -> bool:
    """Strict visible-slot audit: render from independently stored semantic parameters."""
    if family not in ALL_FAMILIES or family in {A04, A11}:
        return False
    try:
        return condition == _render(family, parameters)
    except (KeyError, ValueError, ZeroDivisionError):
        return False


def solve_condition(family: str, condition: str) -> Fraction | None:
    """Recover the displayed numeric slots and independently evaluate the family model."""
    # Match the approved fixed template first, then extract values from its fixed slots.
    patterns: dict[str, str] = {
        A01: r"В амфитеатре (\d+) рядов\. В первом ряду (\d+) (?:место|места|мест), и в каждом следующем на (\d+) (?:место|места|мест) больше, чем в предыдущем\. Сколько мест в (\d+)-м ряду\?",
        A02: r"В амфитеатре (\d+) рядов\. В (\d+)-м ряду (\d+) мест, а в (\d+)-м ряду (\d+) мест\. В каждом следующем ряду мест на одно и то же число больше\. Сколько мест в последнем ряду\?",
        A03: r"В амфитеатре (\d+) рядов\. В первом ряду (\d+) (?:место|места|мест), и в каждом следующем на (\d+) (?:место|места|мест) больше, чем в предыдущем\. Сколько всего мест в амфитеатре\?",
        A06: r"При торможении автомобиль за первую секунду прошёл (\d+) м, а каждую следующую секунду тормозной путь уменьшался на (\d+) м\. Какой путь прошёл автомобиль с начала торможения до полной остановки\?",
        A05: r"Температура вещества была (-?\d+) °C и каждую минуту равномерно уменьшалась на (\d+) °C\. Какой была температура через (\d+) минут(?:у|ы)?\?",
        A07: r"При торможении за первую секунду автомобиль прошёл (\d+) м, а каждую следующую секунду тормозной путь уменьшался на (\d+) м\. Какой путь автомобиль прошёл за первые (\d+) (?:секунд|секунды)\?",
        A08: r"При разгоне поезд за первую секунду прошёл ([\d,]+) м, а за каждую следующую секунду проходил на ([\d,]+) м больше, чем за предыдущую\. Какой путь поезд прошёл за первые (\d+) (?:секунд|секунды)\?",
        A09: r"Забор длиной ([\d,]+) м нужно построить за несколько дней\. В первый день построили (\d+) м, а в последний — (\d+) м\. Каждый день строили на одинаковую длину больше, чем в предыдущий\. За сколько дней построили забор\?",
        A10: r"За (\d+) дней спортсмен сделал всего (\d+) приседаний\. Каждый день он делал на (\d+) (?:приседание|приседания|приседаний) больше, чем в предыдущий, а в первый день сделал (\d+)\. Сколько приседаний он сделал в (\d+)-й день\?",
        G01: r"Масса радиоактивного вещества в начальный момент была (\d+) мг\. Каждые (\d+) минут распадается половина вещества\. Какова масса вещества через (\d+) минут\?",
        G02: r"Масса колонии микроорганизмов в начальный момент составляла (\d+) мг и каждые (\d+) минут увеличивалась в (\d+) раза\. Какой станет масса через (\d+) минут\?",
        G03: r"В начальный момент масса радиоактивного вещества А составляла (\d+) мг\. Каждые (\d+) минут половина вещества А превращается в вещество Б\. Какова масса вещества Б через (\d+) минут\?",
        G04: r"Мяч после удара отскакивает на высоту, в (\d+) раза меньшую, чем высота предыдущего отскока\. Высота первого отскока равна (\d+) см\. После какого по счёту отскока высота впервые станет меньше (\d+) см\?",
    }
    match = re.fullmatch(patterns.get(family, r"(?!)"), condition)
    if not match:
        return None
    vals = [Fraction(value.replace(",", ".")) for value in match.groups()]
    try:
        if family == A01:
            rows, a1, d, k = map(int, vals)
            p = {"rows": rows, "a1": a1, "d": d, "k": k}
        elif family == A02:
            rows, i, ai, j, aj = map(int, vals)
            if i >= j or (aj - ai) % (j - i):
                return None
            d = (aj - ai) // (j - i)
            a1 = ai - (i - 1) * d
            p = {"rows": rows, "i": i, "j": j, "d": d, "a1": a1}
        elif family == A03:
            rows, a1, d = map(int, vals)
            p = {"rows": rows, "a1": a1, "d": d}
        elif family == A06:
            a1, d = map(int, vals)
            if a1 % d:
                return None
            p = {"a1": a1, "d": d, "n": a1 // d}
        elif family == A05:
            t0, rate, t = map(int, vals)
            p = {"t0": t0, "rate": rate, "t": t}
        elif family == A07:
            a1, d, n = map(int, vals)
            p = {"a1": a1, "d": d, "n": n}
        elif family == A08:
            a1t, dt, n = vals[0] * 10, vals[1] * 10, int(vals[2])
            p = {"a1t": int(a1t), "dt": int(dt), "n": n}
        elif family == A09:
            total_value, first_value, last_value = vals
            terms = int(Fraction(2) * total_value / (first_value + last_value))
            difference = int((last_value - first_value) / (terms - 1))
            p = {"n": terms, "a1": int(first_value), "d": difference}
            if _model(family, p) != total_value:
                return None
        elif family == A10:
            days, total_value_int, delta_int, first_int, target_index = map(int, vals)
            p = {
                "n": days,
                "a1": first_int,
                "d": delta_int,
                "k": target_index,
            }
            if _model(family, p) != total_value_int:
                return None
        elif family == G01:
            m0, period, t = map(int, vals)
            if t % period:
                return None
            p = {"m0": m0, "period": period, "cycles": t // period}
        elif family == G02:
            m0, period, factor, t = map(int, vals)
            if t % period:
                return None
            p = {"m0": m0, "period": period, "factor": factor, "cycles": t // period}
        elif family == G03:
            m0, period, t = map(int, vals)
            if t % period:
                return None
            p = {"m0": m0, "period": period, "cycles": t // period}
        else:
            factor, h1, threshold = map(int, vals)
            p = {"factor": factor, "h1": h1, "threshold": threshold}
        if not _valid(family, p):
            return None
        # A03/A08/A09/A10 and geometric models are also independently checked by iteration.
        return _enumerate(family, p)
    except (ValueError, KeyError, ZeroDivisionError, OverflowError):
        return None


def _valid(family: str, p: dict[str, int]) -> bool:
    if family == A01:
        return 1 < p["k"] <= p["rows"] and p["d"] > 0
    if family == A02:
        return 1 < p["i"] < p["j"] < p["rows"] and p["d"] > 0 and p["a1"] > 0
    if family == A03:
        return 1 <= p["rows"] <= 30 and p["d"] > 0
    if family == A06:
        return p["n"] >= 1 and p["a1"] == p["n"] * p["d"] and p["d"] > 0
    if family == A05:
        return 1 <= p["t"] <= 15 and p["rate"] > 0
    if family == A07:
        return p["n"] >= 1 and p["a1"] - (p["n"] - 1) * p["d"] > 0
    if family == A08:
        return p["n"] >= 1 and p["a1t"] > 0 and p["dt"] > 0
    if family == A09:
        return p["n"] >= 2 and p["d"] > 0
    if family == A10:
        return 2 <= p["k"] < p["n"] and p["d"] > 0
    if family in {G01, G03}:
        return p["cycles"] >= (1 if family == G03 else 0) and p["m0"] > 0
    if family == G02:
        return p["cycles"] >= 1 and p["factor"] > 1
    if family == G04:
        return p["factor"] > 1 and p["h1"] > 0 and p["threshold"] > 0
    return False


def _enumerate(family: str, p: dict[str, int]) -> Fraction:
    if family == A01:
        return Fraction(sum([p["a1"]] + [p["d"]] * (p["k"] - 1)))
    if family == A02:
        return Fraction(p["a1"] + (p["rows"] - 1) * p["d"])
    if family == A03:
        return Fraction(sum(p["a1"] + i * p["d"] for i in range(p["rows"])))
    if family == A05:
        return Fraction(p["t0"] - sum([p["rate"]] * p["t"]))
    if family in {A06, A07}:
        return Fraction(sum(p["a1"] - i * p["d"] for i in range(p["n"])))
    if family == A08:
        return sum((Fraction(p["a1t"] + i * p["dt"], 10) for i in range(p["n"])), Fraction())
    if family in {A09, A10}:
        return (
            Fraction(sum(p["a1"] + i * p["d"] for i in range(p["n"])))
            if family == A09
            else Fraction(p["a1"] + (p["k"] - 1) * p["d"])
        )
    if family == G01:
        return Fraction(p["m0"], 2 ** p["cycles"])
    if family == G02:
        return Fraction(p["m0"] * p["factor"] ** p["cycles"])
    if family == G03:
        return Fraction(p["m0"] - Fraction(p["m0"], 2 ** p["cycles"]))
    if family == G04:
        height = Fraction(p["h1"])
        k = 1
        while height >= p["threshold"]:
            height /= p["factor"]
            k += 1
        return Fraction(k)
    raise ValueError("No independent enumerator")


def _explanation(
    family: str, p: dict[str, int], answer: Fraction
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    result = _fmt(answer)
    first_hint = "Сначала определите вид прогрессии и её первый член."
    if family == A01:
        return (first_hint, "Используйте формулу aₖ = a₁ + (k−1)d."), (
            "Число мест в рядах образует арифметическую прогрессию.",
            f"aₖ = {p['a1']} + ({p['k']}−1)·{p['d']} = {result}.",
            "Подставим номер ряда и проверим найденное число мест.",
        )
    if family == A02:
        ai = p["a1"] + (p["i"] - 1) * p["d"]
        aj = p["a1"] + (p["j"] - 1) * p["d"]
        return (first_hint, "Найдите разность по двум известным рядам."), (
            "Число мест образует арифметическую прогрессию.",
            f"d = ({aj}−{ai})/({p['j']}−{p['i']}) = {p['d']}.",
            f"aₙ = aⱼ + ({p['rows']}−{p['j']})d = {result} мест.",
        )
    if family == A03:
        return (first_hint, "Для суммы используйте Sₙ = n(a₁+aₙ)/2."), (
            "Число мест образует арифметическую прогрессию.",
            f"aₙ = {p['a1']} + ({p['rows']}−1)·{p['d']}.",
            f"Sₙ = {p['rows']}·({p['a1']}+{p['a1'] + (p['rows'] - 1) * p['d']})/2 = {result} мест.",
        )
    if family == A05:
        return (first_hint, "В момент t=0 температура равна T₀; затем вычитайте t·δ."), (
            "Изменение температуры за равные промежутки постоянно, это арифметическая прогрессия.",
            f"T({p['t']}) = T₀ − t·δ = {p['t0']} − {p['t']}·{p['rate']}.",
            f"Температура через {p['t']} минут: {result} °C.",
        )
    if family in {A06, A07, A08}:
        n = p["n"]
        first = Fraction(p["a1t"], 10) if family == A08 else Fraction(p["a1"])
        delta = Fraction(p["dt"], 10) if family == A08 else Fraction(p["d"])
        last = first + (n - 1) * delta if family == A08 else first - (n - 1) * delta
        stop_note = (
            f"Следующий отрезок равен 0, поэтому учитываются только {n} положительных отрезков."
            if family == A06
            else f"Последний учитываемый отрезок {_fmt(last)} м положителен."
        )
        condition = (
            "сумма убывающей арифметической прогрессии"
            if family != A08
            else "сумма возрастающей арифметической прогрессии"
        )
        return (first_hint, "Найдите число учитываемых отрезков и сложите их."), (
            f"Путь за каждую секунду образует {condition}.",
            f"Sₙ = n(a₁+aₙ)/2 = {n}·({_fmt(first)}+{_fmt(last)})/2.",
            stop_note,
            f"Общий путь равен {result} м.",
        )
    if family == A09:
        last_day = p["a1"] + (p["n"] - 1) * p["d"]
        total_days = int(answer)
        return (first_hint, "Используйте число дней n = 2S/(a₁+aₙ)."), (
            "Длина построенного забора по дням образует арифметическую прогрессию.",
            f"n = 2·{total_days}/({p['a1']}+{last_day}) = {result}.",
            f"Ответ: забор строили {result} {_days_word(int(answer))}.",
        )
    if family == A10:
        total = int(_model(family, p))
        return (first_hint, "Проверьте сумму n членов, затем найдите нужный член."), (
            "Число приседаний по дням образует арифметическую прогрессию.",
            f"Sₙ = n(2a₁+(n−1)d)/2 = {p['n']}·(2·{p['a1']}+({p['n']}−1)·{p['d']})/2 = {total}.",
            f"aₖ = a₁+(k−1)d = {p['a1']}+({p['k']}−1)·{p['d']} = {result}.",
            "Найден член для указанного дня, а не последний член ряда.",
        )
    if family in {G01, G02, G03}:
        cycles = p["cycles"]
        period = p["period"]
        factor = "1/2" if family in {G01, G03} else str(p["factor"])
        base = "уменьшается вдвое" if family in {G01, G03} else f"увеличивается в {factor} раза"
        return (
            "Ряд масс — геометрическая прогрессия.",
            f"За {cycles} интервалов примените множитель {factor} ровно {cycles} раз.",
        ), (
            f"За каждый интервал {period} минут масса {base}; момент t=0 — начальная масса {p['m0']} мг.",
            f"Через {cycles} интервалов прошло {cycles * period} минут.",
            (
                f"Остаток А = {p['m0']}/2^{cycles}; масса Б = {p['m0']} − остаток А = {result} мг."
                if family == G03
                else (
                    f"M = M₀·{factor}^{cycles} = {p['m0']}·{factor}^{cycles} = {result} мг."
                    if family == G02
                    else f"M = M₀/2^{cycles} = {p['m0']}/2^{cycles} = {result} мг."
                )
            ),
        )
    if family == G04:
        index = int(answer)
        current = Fraction(p["h1"], p["factor"] ** (index - 1))
        previous = Fraction(p["h1"], p["factor"] ** (index - 2))
        return (
            "Высоты отскоков — геометрическая прогрессия, первый отскок имеет номер 1.",
            "Проверяйте каждый отскок по строгому условию hₖ < порога.",
        ), (
            f"hₖ = {p['h1']}/{p['factor']}ᵏ⁻¹ см, k=1,2,… .",
            f"Перед этим отскоком высота {_exact_fmt(previous)} см не меньше {p['threshold']} см.",
            f"После отскока {index} высота {_exact_fmt(current)} см меньше {p['threshold']} см.",
            f"Минимальный номер отскока — {index}.",
        )
    raise ValueError("No explanation for family")


def generate(
    family_id: str, seed: int, generator_version: str = GENERATOR_VERSION
) -> ProgressionProblem:
    if generator_version != GENERATOR_VERSION:
        raise ValueError("Unsupported generator version")
    if family_id not in ALL_FAMILIES or family_id in {A04, A11}:
        raise ValueError("Family is not implemented")
    rng = random.Random(f"oge14:{family_id}:{seed}:{generator_version}")
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        p = _sample(family_id, rng)
        answer = _model(family_id, p)
        places = decimal_places(answer)
        if not _valid(family_id, p) or places is None or places > 2 or abs(answer) > 100_000:
            continue
        condition = _render(family_id, p)
        if (
            not audit_condition(family_id, condition, p)
            or solve_condition(family_id, condition) != answer
        ):
            continue
        text = _fmt(answer)
        hints, solution = _explanation(family_id, p, answer)
        fp = hashlib.sha256(f"{family_id}|{condition}|{text}".encode()).hexdigest()
        return ProgressionProblem(
            str(uuid5(NAMESPACE_URL, f"oge14:{family_id}:{seed}:{generator_version}")),
            seed,
            generator_version,
            family_id,
            SOURCE_IDS[family_id],
            p,
            condition,
            answer,
            text,
            hints,
            solution,
            fp,
            attempt,
        )
    raise RuntimeError(f"No valid OGE-14 candidate for {family_id}")
