"""Deterministic STOVE story adapter for OGE questions 1–5.

The adapter keeps one immutable sauna room and stove catalogue per seed.  The
oracle intentionally solves from the rendered text and SVG instead of trusting
the generator's answer fields.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from math import isqrt
from random import Random
from types import MappingProxyType
from typing import cast

from PIL import Image, ImageDraw, ImageFont

from app.math.scenario_engine import (
    AnswerPolicy,
    FamilyRegistration,
    FamilyStatus,
    QuestionDraft,
    RenderedScenario,
    ScenarioAssetRef,
    ScenarioDraft,
    ScenarioSnapshot,
)

GENERATOR_VERSION = "stove-v1.4"
COMPATIBILITY_MATRIX_VERSION = "stove-bundle-v1"
LEGACY_RENDERER_VERSION = "stove-svg-png-v1"
RENDERER_VERSION = "stove-svg-png-v2"
SOURCE_DATE = "2026-11-02"

FAMILY_IDS = (
    "STOVE-F01-CAPACITY-LIMITS",
    "STOVE-F02-ATTRIBUTE-MATCH",
    "STOVE-F03-VOLUME",
    "STOVE-F04-FLOOR-AREA",
    "STOVE-F05-WALL-AREA-NET",
    "STOVE-F06-PURCHASE-EXTRA-COSTS",
    "STOVE-F07-FIT-WOOD-DELIVERY",
    "STOVE-F08-COST-COMPARISON",
    "STOVE-F09-DIRECT-DISCOUNT",
    "STOVE-F10-REVERSE-DISCOUNT",
    "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS",
    "STOVE-F12-ARCH-RADIUS",
)

SOURCE_IDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "STOVE-F01-CAPACITY-LIMITS": ("383591", "406325"),
        "STOVE-F02-ATTRIBUTE-MATCH": ("408218", "408219", "448919"),
        "STOVE-F03-VOLUME": ("383592", "392833"),
        "STOVE-F04-FLOOR-AREA": ("408225",),
        "STOVE-F05-WALL-AREA-NET": ("406273",),
        "STOVE-F06-PURCHASE-EXTRA-COSTS": ("383593",),
        "STOVE-F07-FIT-WOOD-DELIVERY": ("448921",),
        "STOVE-F08-COST-COMPARISON": ("406274", "392860"),
        "STOVE-F09-DIRECT-DISCOUNT": ("383594",),
        "STOVE-F10-REVERSE-DISCOUNT": ("408246",),
        "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS": ("392836",),
        "STOVE-F12-ARCH-RADIUS": ("383595", "408256"),
    }
)

_FAMILY_POSITION: Mapping[str, int] = MappingProxyType(
    {
        family_id: position
        for position, ids in {
            1: FAMILY_IDS[:2],
            2: FAMILY_IDS[2:3],
            3: FAMILY_IDS[3:8],
            4: FAMILY_IDS[8:11],
            5: FAMILY_IDS[11:],
        }.items()
        for family_id in ids
    }
)
_PYTHAGOREAN_PAIRS = tuple(
    (half * 2, rise)
    for half in range(20, 81)
    for rise in range(20, 91)
    if (root := isqrt(half * half + rise * rise)) ** 2 == half * half + rise * rise and root > rise
)


@dataclass(frozen=True, slots=True)
class NumericAnswerPolicy:
    policy_id: str
    version: str = "1"

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool:
        normalized = raw_answer.strip().replace(" ", "").replace(",", ".")
        expected = canonical_answer.strip().replace(" ", "").replace(",", ".")
        try:
            return Decimal(normalized) == Decimal(expected)
        except (InvalidOperation, ValueError):
            return False


class ExactSequencePolicy:
    policy_id = "digit_sequence_exact_3"
    version = "1"

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool:
        return raw_answer.strip() == canonical_answer and bool(
            re.fullmatch(r"[1-3]{3}", canonical_answer)
        )


class StoveGenerator:
    def generate_scenario(self, seed: int) -> ScenarioDraft:
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
            raise ValueError("STOVE seed must be a non-negative PostgreSQL bigint")
        rng = Random(seed ^ 0x5707E)

        # Search a bounded integer-tenths space for a room whose volume allows
        # exactly one wood model and at least one electric model to be selected.
        room: tuple[int, int, int] | None = None
        for _ in range(1200):
            length = rng.randint(24, 38)
            width = rng.randint(19, 29)
            height = rng.randint(19, 27)
            volume = Fraction(length * width * height, 1000)
            if Fraction(13) <= volume <= Fraction(20):
                room = (length, width, height)
                break
        if room is None:
            raise RuntimeError("Bounded STOVE room generation exhausted")
        length, width, height = room
        volume = Fraction(length * width * height, 1000)

        # The limits deliberately put only wood stove 2 in the room's range;
        # both selected stoves for the comparison are unique and explicit.
        lower = max(8, volume.numerator // volume.denominator - 1)
        upper = lower + 7
        wood_low = max(5, lower - 7)
        wood_high = lower - 1
        electric_low = max(7, lower - 4)
        electric_high = upper + 3
        stove_rows = [
            {"id": 1, "kind": "дровяная", "min_m3": wood_low, "max_m3": wood_high},
            {"id": 2, "kind": "дровяная", "min_m3": lower, "max_m3": upper},
            {"id": 3, "kind": "электрическая", "min_m3": electric_low, "max_m3": electric_high},
        ]
        # Attribute values are exact and unique.  F01/F02 permutations are
        # drawn independently so visual row order and requested order differ.
        masses = [rng.randrange(31, 73), rng.randrange(74, 116), rng.randrange(117, 161)]
        prices = [
            rng.randrange(90, 151) * 100,
            rng.randrange(151, 211) * 100,
            rng.randrange(211, 301) * 100,
        ]
        for row, mass, price in zip(stove_rows, masses, prices, strict=True):
            row["mass_kg"] = mass
            row["price_rub"] = price

        door_width_cm = rng.randrange(55, min(91, width * 10 - 1))
        door_height_cm = rng.randrange(165, min(211, height * 10 - 1))
        installation = rng.randrange(3500, 8001, 100)
        delivery = rng.randrange(500, 1801, 100)
        room_view = {"length_tenths": length, "width_tenths": width, "height_tenths": height}
        arc_width, arc_height = _PYTHAGOREAN_PAIRS[seed % len(_PYTHAGOREAN_PAIRS)]

        # Per-position family choice is deterministic and stable for the seed.
        family_plan = {
            "1": FAMILY_IDS[rng.randrange(2)],
            "2": FAMILY_IDS[2],
            "3": FAMILY_IDS[3 + rng.randrange(5)],
            "4": FAMILY_IDS[8 + rng.randrange(3)],
            "5": FAMILY_IDS[11],
        }
        context: dict[str, object] = {
            "renderer_version": RENDERER_VERSION,
            "room": room_view,
            "arc_width_cm": arc_width,
            "arc_height_cm": arc_height,
            "door_width_cm": door_width_cm,
            "door_height_cm": door_height_cm,
            "stoves": stove_rows,
            "installation_rub": installation,
            "delivery_rub": delivery,
            "family_plan": family_plan,
        }
        # ScenarioDraft's public JSON type is stricter than object; the engine
        # validates and freezes nested values at construction.
        return ScenarioDraft(
            story_code="STOVE",
            seed=seed,
            generator_version=GENERATOR_VERSION,
            compatibility_matrix_version=COMPATIBILITY_MATRIX_VERSION,
            context=cast(Mapping[str, object], context),  # type: ignore[arg-type]
            provenance=("OGE_1_5_ALL_STORIES_RESEARCH_V1/STORIES/STOVE",),
        )


def _context_dict(scenario: ScenarioDraft) -> dict[str, object]:
    return cast(dict[str, object], _thaw(scenario.context))


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _room(context: Mapping[str, object]) -> tuple[int, int, int]:
    room = cast(Mapping[str, int], context["room"])
    return room["length_tenths"], room["width_tenths"], room["height_tenths"]


def _rows(context: Mapping[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], context["stoves"])


def _money(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _decimal_text(value: Fraction) -> str:
    decimal = Decimal(value.numerator) / Decimal(value.denominator)
    text = format(decimal.normalize(), "f")
    return text.replace(".", ",")


def _room_text(context: Mapping[str, object]) -> str:
    length, width, height = _room(context)
    return (
        f"Размеры парной: {_decimal_text(Fraction(length, 10))} × "
        f"{_decimal_text(Fraction(width, 10))} × {_decimal_text(Fraction(height, 10))} м. "
        f"Дверь: {context['door_width_cm']} см × {context['door_height_cm']} см; окон нет."
    )


def _table_text(context: Mapping[str, object]) -> str:
    lines = ["Печь | Тип | Объём парной, м³ | Масса, кг | Цена, руб."]
    for row in _rows(context):
        lines.append(
            f"{row['id']} | {row['kind']} | {row['min_m3']}–{row['max_m3']} | "
            f"{row['mass_kg']} | {_money(cast(int, row['price_rub']))}"
        )
    return "\n".join(lines)


class StoveQuestionBuilder:
    def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft:
        if position not in (1, 2, 3, 4, 5):
            raise ValueError("STOVE question position must be 1–5")
        context = _context_dict(scenario)
        plan = cast(Mapping[str, str], context["family_plan"])
        return self.build_question_for_family(scenario, position, plan[str(position)])

    def build_question_for_family(
        self, scenario: ScenarioDraft, position: int, family_id: str
    ) -> QuestionDraft:
        if family_id not in FAMILY_IDS or _FAMILY_POSITION[family_id] != position:
            raise ValueError("STOVE family does not belong to this question position")
        context = _context_dict(scenario)
        rows = _rows(context)
        length, width, height = _room(context)
        room_volume = Fraction(length * width * height, 1000)
        model: dict[str, object] = {"family_id": family_id}
        answer: str
        condition: str
        hints: tuple[str, ...]
        steps: tuple[str, ...]

        if family_id == FAMILY_IDS[0]:
            boundary = "min_m3" if scenario.seed % 2 == 0 else "max_m3"
            values = [cast(int, row[boundary]) for row in rows]
            displayed = values[:]
            Random(scenario.seed ^ 0xF01).shuffle(displayed)
            answer = "".join(
                str(next(cast(int, row["id"]) for row in rows if row[boundary] == val))
                for val in displayed
            )
            condition = (
                f"Укажите номера печей, соответствующие значениям {'наименьших' if boundary == 'min_m3' else 'наибольших'} границ диапазона объёма, в таком же порядке: "  # noqa: E501
                + ", ".join(map(str, displayed))
                + "."
            )
            model.update({"boundary": boundary, "displayed_values": displayed})
            hints = (
                "Найдите в таблице столбец диапазона объёма.",
                "Сопоставьте каждое значение с одной строкой таблицы.",
            )
            steps = (
                f"По столбцу {'нижней' if boundary == 'min_m3' else 'верхней'} границы найдём номера печей: {answer}.",  # noqa: E501
            )
        elif family_id == FAMILY_IDS[1]:
            key = "mass_kg" if scenario.seed % 2 == 0 else "price_rub"
            displayed_rows = rows[:]
            Random(scenario.seed ^ 0xF02).shuffle(displayed_rows)
            displayed = [cast(int, row[key]) for row in displayed_rows]
            label = "массы (кг)" if key == "mass_kg" else "цены (руб.)"
            answer = "".join(str(row["id"]) for row in displayed_rows)
            condition = (
                f"Укажите номера печей, соответствующие значениям {label} в указанном порядке: "
                + ", ".join(_money(v) for v in displayed)
                + "."
            )
            model.update({"attribute": key, "displayed_values": displayed})
            hints = (
                f"Найдите в таблице столбец «{label}».",
                "Для каждого значения запишите номер соответствующей строки.",
            )
            steps = (f"Сопоставление строк таблицы даёт последовательность {answer}.",)
        elif family_id in (FAMILY_IDS[2], FAMILY_IDS[3], FAMILY_IDS[4]):
            if family_id == FAMILY_IDS[2]:
                answer_fraction = room_volume
                condition = f"Найдите объём парной. {_room_text(context)}"
                operation = "volume"
                hints = (
                    "Объём прямоугольного помещения равен произведению длины, ширины и высоты.",
                    "Умножьте три размера в метрах.",
                )
                steps = (
                    f"V = {_decimal_text(Fraction(length, 10))} · {_decimal_text(Fraction(width, 10))} · {_decimal_text(Fraction(height, 10))} = {_decimal_text(answer_fraction)} м³.",  # noqa: E501
                )
            elif family_id == FAMILY_IDS[3]:
                answer_fraction = Fraction(length * width, 100)
                condition = f"Найдите площадь пола парной. {_room_text(context)}"
                operation = "floor_area"
                hints = (
                    "Площадь прямоугольного пола равна произведению длины на ширину.",
                    "Высота помещения для площади пола не нужна.",
                )
                steps = (
                    f"S = {_decimal_text(Fraction(length, 10))} · {_decimal_text(Fraction(width, 10))} = {_decimal_text(answer_fraction)} м².",  # noqa: E501
                )
            else:
                door = Fraction(cast(int, context["door_width_cm"]), 100) * Fraction(
                    cast(int, context["door_height_cm"]), 100
                )
                answer_fraction = 2 * (Fraction(length + width, 10)) * Fraction(height, 10) - door
                condition = (
                    f"Найдите площадь всех стен парной без дверного проёма. {_room_text(context)}"
                )
                operation = "walls_minus_door"
                hints = (
                    "Найдите периметр основания и умножьте его на высоту.",
                    "Переведите ширину и высоту двери из сантиметров в метры и вычтите её площадь.",
                )
                steps = (
                    f"S стен = 2 · ({_decimal_text(Fraction(length, 10))} + {_decimal_text(Fraction(width, 10))}) · {_decimal_text(Fraction(height, 10))} = {_decimal_text(2 * Fraction(length + width, 10) * Fraction(height, 10))} м².",  # noqa: E501
                    f"S двери = {context['door_width_cm']} см · {context['door_height_cm']} см = {_decimal_text(door)} м².",  # noqa: E501
                    f"Без проёма: {_decimal_text(answer_fraction)} м².",
                )
            answer = _decimal_text(answer_fraction)
            model.update({"operation": operation})
            hints = tuple(hints)
        elif family_id == FAMILY_IDS[5]:
            electric = rows[2]
            installation = cast(int, context["installation_rub"])
            delivery = cast(int, context["delivery_rub"])
            answer = str(cast(int, electric["price_rub"]) + installation + delivery)
            condition = f"Сколько рублей будет стоить электрическая печь №3 с установкой и доставкой? Установка стоит {_money(installation)} руб., доставка — {_money(delivery)} руб."  # noqa: E501
            model.update({"operation": "purchase_extra_costs"})
            hints = (
                "Возьмите цену электрической печи №3 из таблицы.",
                "Прибавьте и установку, и доставку.",
            )
            steps = (
                f"{_money(cast(int, electric['price_rub']))} + {_money(installation)} + {_money(delivery)} = {_money(int(answer))} руб.",  # noqa: E501
            )
        elif family_id == FAMILY_IDS[6]:
            wood = rows[1]
            delivery = cast(int, context["delivery_rub"])
            answer = str(cast(int, wood["price_rub"]) + delivery)
            condition = f"Для парной из условия выберите подходящую дровяную печь по объёму и найдите её стоимость с доставкой. Доставка стоит {_money(delivery)} руб. {_room_text(context)}"  # noqa: E501
            model.update({"operation": "wood_fit_delivery"})
            hints = (
                "Сначала вычислите объём парной.",
                "Проверьте объём в диапазонах только дровяных печей; границы включаются.",
                "К цене единственной подходящей печи прибавьте доставку.",
            )
            steps = (
                f"V = {_decimal_text(room_volume)} м³; подходит дровяная печь №2.",
                f"{_money(cast(int, wood['price_rub']))} + {_money(delivery)} = {_money(int(answer))} руб.",  # noqa: E501
            )
        elif family_id == FAMILY_IDS[7]:
            wood_options = [
                row
                for row in rows[:2]
                if cast(int, row["min_m3"]) <= room_volume <= cast(int, row["max_m3"])
            ]
            if len(wood_options) != 1:
                raise ValueError("Cost comparison requires one suitable wood stove")
            wood, electric = wood_options[0], rows[2]
            with_installation = scenario.seed % 2 == 0
            electric_total = cast(int, electric["price_rub"]) + (
                cast(int, context["installation_rub"]) if with_installation else 0
            )
            wood_total = cast(int, wood["price_rub"])
            wood_is_cheaper = wood_total < electric_total
            comparison = "дешевле" if wood_is_cheaper else "дороже"
            difference = abs(wood_total - electric_total)
            inclusion = "с учётом установки" if with_installation else "без учёта установки"
            condition = f"Определите по объёму парной подходящую дровяную печь. На сколько рублей её покупка обойдётся {comparison} электрической {inclusion}? Установка электрической печи стоит {_money(cast(int, context['installation_rub']))} руб."  # noqa: E501
            answer = str(difference)
            model.update(
                {
                    "operation": "cost_comparison",
                    "installation_included": with_installation,
                    "comparison": comparison,
                    "wood_stove_id": cast(int, wood["id"]),
                    "electric_stove_id": cast(int, electric["id"]),
                }
            )
            hints = (
                "Сначала вычислите объём парной и проверьте диапазоны дровяных печей.",
                "Для электрической печи добавьте установку только если это сказано.",
                "Из большей стоимости вычтите меньшую.",
            )
            steps = (
                f"Объём парной: {_decimal_text(room_volume)} м³; подходит дровяная печь "
                f"№{wood['id']}.",
                f"Стоимость подходящей дровяной печи: {_money(wood_total)} руб.",
                f"Стоимость электрической печи {inclusion}: {_money(electric_total)} руб.",
                f"Разность равна {_money(difference)} руб.",
            )
        elif family_id in (FAMILY_IDS[8], FAMILY_IDS[9]):
            if family_id == FAMILY_IDS[8]:
                stove = rows[scenario.seed % 2]
                discount = 10
                base = cast(int, stove["price_rub"])
                answer_value = Fraction(base * (100 - discount), 100)
                condition = (
                    f"На дровяную печь массой {stove['mass_kg']} кг предоставлена "
                    f"скидка {discount}%. Сколько будет стоить печь после скидки?"
                )
                operation = "direct_discount"
                hints = (
                    f"После скидки остаётся {100 - discount}% цены.",
                    "По массе найдите строку этой печи в таблице, затем "
                    "умножьте её цену на оставшуюся долю.",
                )
                steps = (
                    f"По массе {stove['mass_kg']} кг находим дровяную печь "
                    f"№{stove['id']}: {_money(base)} руб.",
                    f"{_money(base)} · ({100} − {discount}) / 100 = {_money(int(answer_value))} руб.",  # noqa: E501
                )
            else:
                listed_prices = {cast(int, row["price_rub"]) for row in rows}
                choices = []
                for row in rows:
                    current_price = cast(int, row["price_rub"])
                    for rate in (10, 15, 20, 25, 30, 35, 40, 50):
                        previous = Fraction(current_price * 100, 100 - rate)
                        if previous.denominator == 1 and previous not in listed_prices:
                            choices.append((row, rate, current_price, previous))
                # At least the most expensive row with a 20% discount works:
                # prices are multiples of 100, and the old price exceeds the catalogue maximum.
                stove, discount, current, answer_value = choices[scenario.seed % len(choices)]
                condition = (
                    f"В таблице указана нынешняя цена печи №{stove['id']}. "
                    f"По сравнению с прошлым годом она снижена на {discount}%. "
                    "Сколько рублей стоила эта печь в прошлом году?"
                )
                operation = "reverse_discount"
                hints = (
                    f"После скидки осталось {100 - discount}% исходной стоимости.",
                    "Найдите текущую цену этой модели в таблице и разделите на оставшуюся долю.",
                )
                steps = (
                    f"C до скидки = {_money(current)} · 100 / ({100} − {discount}) = {_money(int(answer_value))} руб.",  # noqa: E501
                )
            if answer_value.denominator != 1:
                raise ValueError("Discount generator produced a non-integer ruble answer")
            answer = str(answer_value.numerator)
            model.update({"operation": operation})
            if family_id == FAMILY_IDS[8]:
                model.update(
                    {
                        "stove_id": cast(int, stove["id"]),
                        "mass_kg": cast(int, stove["mass_kg"]),
                        "discount_percent": discount,
                    }
                )
            else:
                model.update(
                    {"stove_id": cast(int, stove["id"]), "discount_percent": discount}
                )
        elif family_id == FAMILY_IDS[10]:
            price = cast(int, rows[1]["price_rub"])
            threshold = price - 1000
            item_discount = 5
            delivery_discount = 20
            delivery = cast(int, context["delivery_rub"])
            answer_value = Fraction(
                price * (100 - item_discount) + delivery * (100 - delivery_discount), 100
            )
            if price <= threshold or answer_value.denominator != 1:
                raise ValueError("Conditional discount parameters are invalid")
            condition = f"Если цена покупки дороже {_money(threshold)} руб., на печь действует скидка {item_discount}%, а на доставку — скидка {delivery_discount}%. Сколько нужно заплатить за печь №2 с доставкой, если доставка стоит {_money(delivery)} руб.?"  # noqa: E501
            answer = str(answer_value.numerator)
            model.update(
                {
                    "operation": "conditional_two_discounts",
                    "stove_id": 2,
                    "threshold_rub": threshold,
                    "item_discount_percent": item_discount,
                    "delivery_discount_percent": delivery_discount,
                    "delivery_rub": delivery,
                }
            )
            hints = (
                "Сравните цену покупки с порогом: условие говорит строго «дороже».",
                "Уменьшите цену печи на её скидку.",
                "Отдельно уменьшите стоимость доставки на её скидку и сложите.",
            )
            steps = (
                f"Покупка дороже порога: {_money(price)} > {_money(threshold)}.",
                f"Печь после скидки: {_money(price)} · 95/100 = {_money(price * 95 // 100)} руб.",
                f"Доставка после скидки: {_money(delivery)} · 80/100 = {_money(delivery * 80 // 100)} руб.",  # noqa: E501
                f"Итого: {_money(int(answer))} руб.",
            )
        else:
            width_cm = cast(int, context["arc_width_cm"])
            height_cm = cast(int, context["arc_height_cm"])
            half_width = width_cm // 2
            radius = isqrt(half_width * half_width + height_cm * height_cm)
            condition = "Найдите радиус дуги арки кожуха печи. Размеры кожуха указаны на рисунке. Центр окружности находится в середине нижнего основания."  # noqa: E501
            answer = str(radius)
            model.update({"operation": "arc_radius", "width_cm": width_cm, "height_cm": height_cm})
            hints = (
                "Соедините центр окружности с точкой примыкания дуги: получится радиус.",
                "Половина ширины основания и высота образуют катеты прямоугольного треугольника.",
                "Примените теорему Пифагора.",
            )
            steps = (
                f"Половина ширины: {width_cm}/2 = {half_width} см.",
                f"R² = {half_width}² + {height_cm}² = {radius * radius}.",
                f"R = {radius} см.",
            )
        policy_id = (
            "digit_sequence_exact_3"
            if family_id in FAMILY_IDS[:2]
            else "integer_centimeters"
            if family_id == FAMILY_IDS[11]
            else "decimal_exact"
            if family_id in FAMILY_IDS[2:5]
            else "integer_rubles"
        )
        return QuestionDraft(
            position=position,
            scenario_seed=scenario.seed,
            family_id=family_id,
            generator_version=GENERATOR_VERSION,
            condition=condition,
            answer_policy_id=policy_id,
            answer_policy_version="1",
            canonical_answer=answer,
            hints=tuple(hints),
            solution_steps=tuple(steps),
            math_model=cast(Mapping[str, object], model),  # type: ignore[arg-type]
        )


class StoveRenderer:
    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario:
        context = _context_dict(scenario)
        shared = (
            "Сюжет: печи для бани. Все пять вопросов относятся к одной парной и одному каталогу печей.\n"  # noqa: E501
            + _room_text(context)
            + "\n"
            + _table_text(context)
        )
        payloads = _render_assets(context)
        refs = tuple(_asset_ref(mime, payload) for mime, payload in payloads.values())
        return RenderedScenario(shared_context=shared, assets=refs)

    def restore_asset(self, snapshot: ScenarioSnapshot, asset: ScenarioAssetRef) -> bytes:
        context = cast(Mapping[str, object], _thaw(snapshot.context))
        payloads = _render_assets(context)
        for mime, payload in payloads.values():
            if _asset_ref(mime, payload) == asset:
                return payload
        raise ValueError("STOVE asset is not produced by this snapshot renderer")


def _asset_ref(mime: str, payload: bytes) -> ScenarioAssetRef:
    digest = sha256(payload).hexdigest()
    extension = "png" if mime == "image/png" else "svg"
    return ScenarioAssetRef(digest, mime, f"sha256/{digest}.{extension}")


def _svg_table(context: Mapping[str, object]) -> bytes:
    rows = _rows(context)
    columns = ["№", "Тип печи", "Объём парной, м³", "Масса, кг", "Цена, руб."]
    x = [45, 145, 390, 700, 900, 1155]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="430" viewBox="0 0 1200 430" data-renderer="{context["renderer_version"]}">',  # noqa: E501
        '<rect width="1200" height="430" fill="#fff"/>',
    ]
    parts.append(
        '<text x="600" y="42" text-anchor="middle" font-family="sans-serif" font-size="25" font-weight="bold">Печи для бани</text>'  # noqa: E501
    )
    y0, row_h = 75, 78
    for row_index in range(4):
        y = y0 + row_index * row_h
        parts.append(
            f'<line x1="45" y1="{y}" x2="1155" y2="{y}" stroke="#263746" stroke-width="2"/>'
        )
    parts.append(
        f'<line x1="45" y1="{y0 + 4 * row_h}" x2="1155" y2="{y0 + 4 * row_h}" stroke="#263746" stroke-width="2"/>'  # noqa: E501
    )
    for xx in x:
        parts.append(
            f'<line x1="{xx}" y1="{y0}" x2="{xx}" y2="{y0 + 4 * row_h}" stroke="#9aabb7" stroke-width="1.5"/>'  # noqa: E501
        )
    for i, title in enumerate(columns):
        parts.append(
            f'<text x="{(x[i] + x[i + 1]) // 2}" y="{y0 + 48}" text-anchor="middle" font-family="sans-serif" font-size="17" font-weight="bold">{title}</text>'  # noqa: E501
        )
    for ri, row in enumerate(rows):
        vals = [
            str(row["id"]),
            str(row["kind"]),
            f"{row['min_m3']}–{row['max_m3']}",
            str(row["mass_kg"]),
            _money(cast(int, row["price_rub"])),
        ]
        for ci, value in enumerate(vals):
            parts.append(
                f'<text x="{(x[ci] + x[ci + 1]) // 2}" y="{y0 + row_h * (ri + 1) + 48}" text-anchor="middle" font-family="sans-serif" font-size="20">{value}</text>'  # noqa: E501
            )
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def _svg_arc(width_cm: int, height_cm: int, *, legacy: bool = False) -> bytes:
    version = LEGACY_RENDERER_VERSION if legacy else RENDERER_VERSION
    half = Fraction(width_cm, 2)
    radius = isqrt(width_cm * width_cm // 4 + height_cm * height_cm)
    scale = 4
    ox, oy = 400, 500
    coords: list[tuple[float, float]] = []
    for i in range(81):
        x_cm = width_cm * i / 80
        y_cm = (radius * radius - (x_cm - float(half)) ** 2) ** 0.5
        coords.append((ox - float(half) * scale + x_cm * scale, oy - y_cm * scale))
    path = "M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in coords)
    arc_top = oy - radius * scale
    left_x = ox - float(half) * scale
    right_x = ox + float(half) * scale
    top_y = oy - height_cm * scale
    width_y = oy + 80
    height_x = left_x - 40
    radius_attribute = f' data-radius-cm="{radius}"' if legacy else ""
    title = f"Арка кожуха печи · R={radius} см" if legacy else "Арка кожуха печи"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600" data-renderer="{version}" data-width-cm="{width_cm}" data-height-cm="{height_cm}"{radius_attribute}>'  # noqa: E501
        '<rect width="800" height="600" fill="#fff"/>'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">'
        '<path d="M 8 0 L 0 4 L 8 8" fill="none" stroke="#71818b"/></marker></defs>'
        f'<path d="{path}" fill="none" stroke="#1c5d7a" stroke-width="5"/>'
        f'<line x1="{ox}" y1="{oy}" x2="{ox}" y2="{arc_top}" stroke="#d17a22" stroke-width="3" stroke-dasharray="8 6"/>'  # noqa: E501
        f'<line x1="{left_x}" y1="{oy}" x2="{left_x}" y2="{top_y}" stroke="#263746" stroke-width="3"/>'  # noqa: E501
        f'<line x1="{right_x}" y1="{oy}" x2="{right_x}" y2="{top_y}" stroke="#263746" stroke-width="3"/>'  # noqa: E501
        f'<line x1="{ox}" y1="{oy}" x2="{right_x}" y2="{oy}" stroke="#495a67" stroke-width="2" stroke-dasharray="6 5"/>'  # noqa: E501
        f'<line x1="{right_x}" y1="{oy}" x2="{right_x}" y2="{top_y}" stroke="#495a67" stroke-width="2" stroke-dasharray="6 5"/>'  # noqa: E501
        f'<line x1="{ox}" y1="{oy}" x2="{right_x}" y2="{top_y}" stroke="#d17a22" stroke-width="3"/>'
        f'<line x1="{left_x}" y1="{oy}" x2="{left_x}" y2="{width_y}" stroke="#71818b" stroke-width="2"/>'  # noqa: E501
        f'<line x1="{right_x}" y1="{oy}" x2="{right_x}" y2="{width_y}" stroke="#71818b" stroke-width="2"/>'  # noqa: E501
        f'<line x1="{left_x}" y1="{width_y}" x2="{right_x}" y2="{width_y}" stroke="#71818b" stroke-width="2" marker-start="url(#arrow)" marker-end="url(#arrow)"/>'  # noqa: E501
        f'<line x1="{height_x}" y1="{oy}" x2="{left_x}" y2="{oy}" stroke="#71818b" stroke-width="2"/>'  # noqa: E501
        f'<line x1="{height_x}" y1="{top_y}" x2="{left_x}" y2="{top_y}" stroke="#71818b" stroke-width="2"/>'  # noqa: E501
        f'<line x1="{height_x}" y1="{top_y}" x2="{height_x}" y2="{oy}" stroke="#71818b" stroke-width="2" marker-start="url(#arrow)" marker-end="url(#arrow)"/>'  # noqa: E501
        f'<circle cx="{ox}" cy="{oy}" r="6" fill="#d17a22"/><text x="{ox + 12}" y="{oy + 23}" font-size="20">O</text>'  # noqa: E501
        f'<text x="{height_x - 10}" y="{(oy + top_y) // 2}" text-anchor="end" font-size="18">{height_cm} см</text>'  # noqa: E501
        f'<text x="{ox + 30}" y="{oy - 18}" font-size="18">{width_cm // 2} см</text>'
        f'<text x="{ox}" y="{width_y + 28}" text-anchor="middle" font-size="18">{width_cm} см</text>'  # noqa: E501
        f'<text x="400" y="30" text-anchor="middle" font-size="24">{title}</text></svg>'  # noqa: E501
    ).encode()


@lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _png_table(context: Mapping[str, object]) -> bytes:
    image = Image.new("RGB", (1200, 430), "white")
    draw = ImageDraw.Draw(image)
    draw.text((600, 24), "Печи для бани", fill="#18313f", font=_font(25), anchor="mt")
    xs = [45, 145, 390, 700, 900, 1155]
    y0, row_h = 75, 78
    for j in range(5):
        draw.line((xs[j], y0, xs[j], y0 + 4 * row_h), fill="#9aabb7", width=2)
    for i in range(5):
        draw.line((45, y0 + i * row_h, 1155, y0 + i * row_h), fill="#263746", width=3)
    heads = ["№", "Тип печи", "Объём, м³", "Масса, кг", "Цена, руб."]
    for i, title in enumerate(heads):
        draw.text(
            ((xs[i] + xs[i + 1]) // 2, y0 + 22), title, fill="#18313f", font=_font(17), anchor="mm"
        )
    for r, row in enumerate(_rows(context)):
        vals = [
            str(row["id"]),
            str(row["kind"]),
            f"{row['min_m3']}–{row['max_m3']}",
            str(row["mass_kg"]),
            _money(cast(int, row["price_rub"])),
        ]
        for i, val in enumerate(vals):
            draw.text(
                ((xs[i] + xs[i + 1]) // 2, y0 + row_h * (r + 1) + 24),
                val,
                fill="#182a35",
                font=_font(20),
                anchor="mm",
            )
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=1)
    return output.getvalue()


def _png_arc(width_cm: int, height_cm: int, *, legacy: bool = False) -> bytes:
    half = width_cm // 2
    radius = isqrt(half * half + height_cm * height_cm)
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    points = []
    for i in range(81):
        x = width_cm * i / 80
        y = (radius * radius - (x - half) ** 2) ** 0.5
        points.append((int(400 - half * 4 + x * 4), int(500 - y * 4)))
    draw.line(points, fill="#1c5d7a", width=5)
    draw.line((400, 500, 400, 500 - radius * 4), fill="#d17a22", width=3)
    left_x, right_x = 400 - half * 4, 400 + half * 4
    top_y, width_y = 500 - height_cm * 4, 580
    draw.line((left_x, 500, left_x, top_y), fill="#263746", width=3)
    draw.line((right_x, 500, right_x, top_y), fill="#263746", width=3)
    draw.line((400, 500, right_x, 500, right_x, top_y), fill="#495a67", width=2)
    draw.line((400, 500, right_x, top_y), fill="#d17a22", width=3)
    draw.line((left_x, width_y, right_x, width_y), fill="#71818b", width=2)
    draw.polygon(
        [(left_x, width_y), (left_x + 9, width_y - 5), (left_x + 9, width_y + 5)],
        fill="#71818b",
    )
    draw.polygon(
        [(right_x, width_y), (right_x - 9, width_y - 5), (right_x - 9, width_y + 5)],
        fill="#71818b",
    )
    height_x = left_x - 40
    draw.line((height_x, 500, height_x, top_y), fill="#71818b", width=2)
    draw.polygon(
        [(height_x, top_y), (height_x - 5, top_y + 9), (height_x + 5, top_y + 9)],
        fill="#71818b",
    )
    draw.polygon(
        [(height_x, 500), (height_x - 5, 491), (height_x + 5, 491)],
        fill="#71818b",
    )
    draw.ellipse((394, 494, 406, 506), fill="#d17a22")
    draw.text((410, 500), "O", fill="#18313f", font=_font(18))
    title = f"Арка кожуха печи · R={radius} см" if legacy else "Арка кожуха печи"
    draw.text((412, 26), title, fill="#18313f", font=_font(22))
    draw.text(
        (height_x - 36, (500 + top_y) // 2), f"{height_cm} см", fill="#18313f", font=_font(18)
    )
    draw.text((432, 480), f"{half} см", fill="#18313f", font=_font(18))
    draw.text((380, 548), f"{width_cm} см", fill="#18313f", font=_font(18))
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=1)
    return output.getvalue()


def _render_assets(context: Mapping[str, object]) -> dict[str, tuple[str, bytes]]:
    width = cast(int, context["arc_width_cm"])
    height = cast(int, context["arc_height_cm"])
    legacy = context["renderer_version"] == LEGACY_RENDERER_VERSION
    return {
        "table.svg": ("image/svg+xml", _svg_table(context)),
        "table.png": ("image/png", _png_table(context)),
        "arc.svg": ("image/svg+xml", _svg_arc(width, height, legacy=legacy)),
        "arc.png": ("image/png", _png_arc(width, height, legacy=legacy)),
    }


class StoveOracle:
    def validate_scenario(self, scenario: ScenarioDraft) -> None:
        if scenario.story_code != "STOVE" or scenario.generator_version != GENERATOR_VERSION:
            raise ValueError("STOVE scenario identity/version mismatch")
        context = _context_dict(scenario)
        length, width, height = _room(context)
        if not (24 <= length <= 38 and 19 <= width <= 29 and 19 <= height <= 27):
            raise ValueError("STOVE room dimensions are outside the supported domain")
        rows = _rows(context)
        if [row["id"] for row in rows] != [1, 2, 3]:
            raise ValueError("Stove rows must preserve IDs 1, 2, 3")
        for key in ("mass_kg", "price_rub"):
            values = [row[key] for row in rows]
            if len(set(values)) != 3:
                raise ValueError(f"Stove {key} values must be unique")
        vol = Fraction(length * width * height, 1000)
        wood_fit = [
            r
            for r in rows[:2]
            if Fraction(cast(int, r["min_m3"])) <= vol <= Fraction(cast(int, r["max_m3"]))
        ]
        electric_fit = [
            r
            for r in rows[2:]
            if Fraction(cast(int, r["min_m3"])) <= vol <= Fraction(cast(int, r["max_m3"]))
        ]
        if len(wood_fit) != 1 or len(electric_fit) != 1:
            raise ValueError("Room must have exactly one fitting wood and electric stove")
        door_width_cm = cast(int, context["door_width_cm"])
        door_height_cm = cast(int, context["door_height_cm"])
        if not (0 < door_width_cm < min(length, width) * 10):
            raise ValueError("Door width must fit a single room wall")
        if not (0 < door_height_cm < height * 10):
            raise ValueError("Door height must be below the room height")

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None:
        if question.scenario_seed != scenario.seed or question.position != _FAMILY_POSITION.get(
            question.family_id
        ):
            raise ValueError("Question seed/position does not match its family")
        answer = self._solve_visible(question, rendered, scenario)
        if answer != question.canonical_answer:
            raise ValueError(f"STOVE oracle mismatch: visible condition yields {answer}")
        self._validate_solution_steps(question, rendered.shared_context)
        self._validate_rendered_assets(scenario, rendered)
        if question.family_id not in FAMILY_IDS:
            raise ValueError("Unregistered STOVE family")

    def validate_bundle(
        self,
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        rendered: RenderedScenario,
    ) -> None:
        if tuple(q.position for q in questions) != (1, 2, 3, 4, 5):
            raise ValueError("STOVE bundle must have exactly one ordered question per position")
        if any(q.scenario_seed != scenario.seed for q in questions):
            raise ValueError("STOVE bundle questions must share a seed")
        for question in questions:
            self.validate_question(scenario, question, rendered)
        # All questions share identical visible dimensions/table; extracting
        # them from the same presentation prevents independent-world bundles.
        if (
            rendered.shared_context.count("Печь | Тип") != 1
            or rendered.shared_context.count("Размеры парной:") != 1
        ):
            raise ValueError("STOVE bundle must carry one common room and one common table")

    def _solve_visible(
        self, question: QuestionDraft, rendered: RenderedScenario, scenario: ScenarioDraft
    ) -> str:
        shared = rendered.shared_context
        family = question.family_id
        context = _parse_visible_context(shared)
        rows = cast(list[dict[str, object]], context["rows"])
        condition = question.condition
        if family == FAMILY_IDS[0]:
            vals = [int(x) for x in re.findall(r"(?<!\d)\d+(?!\d)", condition)]
            if len(vals) != 3:
                raise ValueError("Capacity question must show three boundary values")
            boundary = (
                "min_m3"
                if "наименьших" in condition
                else "max_m3"
                if "наибольших" in condition
                else ""
            )
            if not boundary:
                raise ValueError("Capacity direction is missing")
            matching_ids = [[r["id"] for r in rows if r[boundary] == value] for value in vals]
            if any(len(matches) != 1 for matches in matching_ids):
                raise ValueError("Each requested capacity boundary must identify one stove")
            return "".join(str(matches[0]) for matches in matching_ids)
        if family == FAMILY_IDS[1]:
            numbers = [_parse_rub_or_int(s) for s in re.findall(r"\d[\d  ]*", condition)]
            if len(numbers) != 3:
                raise ValueError("Attribute question must show exactly three values")
            key = (
                "mass_kg"
                if "массы (кг)" in condition
                else "price_rub"
                if "цены (руб.)" in condition
                else ""
            )
            if not key:
                raise ValueError("Attribute target is missing")
            matching_ids = [[r["id"] for r in rows if r[key] == number] for number in numbers]
            if any(len(matches) != 1 for matches in matching_ids):
                raise ValueError("Each requested stove attribute must identify one row")
            return "".join(str(matches[0]) for matches in matching_ids)
        if family in FAMILY_IDS[2:5]:
            dims = _parse_room_condition(condition)
            length_m, width_m, height_m = dims
            if family == FAMILY_IDS[2]:
                return _decimal_text(length_m * width_m * height_m)
            if family == FAMILY_IDS[3]:
                return _decimal_text(length_m * width_m)
            dw_match = re.search(r"Дверь: (\d+) см × (\d+) см", condition)
            if not dw_match or "окон нет" not in condition:
                raise ValueError(
                    "Wall question requires visible door dimensions and no-window statement"
                )
            door = Fraction(int(dw_match.group(1)), 100) * Fraction(int(dw_match.group(2)), 100)
            return _decimal_text(2 * (length_m + width_m) * height_m - door)
        if family == FAMILY_IDS[5]:
            price = cast(int, rows[2]["price_rub"])
            install = _extract_money(condition, "Установка стоит")
            delivery = _extract_money(condition, "доставка —")
            if "с установкой и доставкой" not in condition:
                raise ValueError("Purchase question omits a required cost")
            return str(price + install + delivery)
        if family == FAMILY_IDS[6]:
            length_m, width_m, height_m = _parse_room_condition(condition)
            volume = length_m * width_m * height_m
            fitting = [
                r for r in rows[:2] if cast(int, r["min_m3"]) <= volume <= cast(int, r["max_m3"])
            ]
            if len(fitting) != 1:
                raise ValueError("Wood selection must have exactly one fitting stove")
            delivery = _extract_money(condition, "Доставка стоит")
            return str(cast(int, fitting[0]["price_rub"]) + delivery)
        if family == FAMILY_IDS[7]:
            if "Определите по объёму парной подходящую дровяную печь." not in condition:
                raise ValueError("Comparison must require finding a fitting wood stove")
            length_m, width_m, height_m = cast(
                tuple[Fraction, Fraction, Fraction], context["room_dimensions_m"]
            )
            volume = length_m * width_m * height_m
            wood_fit = [
                row
                for row in rows[:2]
                if cast(int, row["min_m3"]) <= volume <= cast(int, row["max_m3"])
            ]
            if len(wood_fit) != 1:
                raise ValueError("Comparison room must identify one suitable wood stove")
            installation = _extract_money(condition, "Установка электрической печи стоит")
            includes_installation = "с учётом установки" in condition
            if not includes_installation and "без учёта установки" not in condition:
                raise ValueError("Comparison must state whether installation is counted")
            electric = cast(int, rows[2]["price_rub"]) + (
                installation if includes_installation else 0
            )
            wood = cast(int, wood_fit[0]["price_rub"])
            comparison = "дешевле" if wood < electric else "дороже" if wood > electric else "равна"
            if comparison == "равна" or f"обойдётся {comparison} электрической" not in condition:
                raise ValueError("Comparison direction does not match visible prices")
            return str(abs(wood - electric))
        if family in FAMILY_IDS[8:10]:
            if family == FAMILY_IDS[8]:
                match = re.fullmatch(
                    r"На дровяную печь массой (\d+) кг предоставлена скидка (\d+)%. "
                    r"Сколько будет стоить печь после скидки\?",
                    condition,
                )
                if not match:
                    raise ValueError("Direct discount wording is invalid")
                mass, discount = map(int, match.groups())
                matching_rows = [
                    row
                    for row in rows
                    if str(row["kind"]).casefold() == "дровяная" and row["mass_kg"] == mass
                ]
                if len(matching_rows) != 1:
                    raise ValueError("Discount mass must identify one wood stove in the table")
                base = cast(int, matching_rows[0]["price_rub"])
                return _integer_fraction(Fraction(base * (100 - discount), 100))
            reverse = re.fullmatch(
                r"В таблице указана нынешняя цена печи №([1-3])\. "
                r"По сравнению с прошлым годом она снижена на (\d+)%. "
                r"Сколько рублей стоила эта печь в прошлом году\?",
                condition.split("Печь | Тип", maxsplit=1)[0].rstrip(),
            )
            if not reverse:
                raise ValueError("Reverse discount wording is invalid")
            row_id, discount = map(int, reverse.groups())
            catalogue = {r["id"]: r["price_rub"] for r in rows}
            current = cast(int, catalogue.get(row_id, 0))
            if current <= 0 or not 0 < discount < 100:
                raise ValueError("Reverse discount row or rate is invalid")
            previous = Fraction(current * 100, 100 - discount)
            if previous in catalogue.values():
                raise ValueError("The previous price is disclosed in the catalogue")
            return _integer_fraction(previous)
        if family == FAMILY_IDS[10]:
            match = re.search(
                r"Если цена покупки дороже ([\d  ]+) руб\., на печь действует скидка (\d+)%, "
                r"а на доставку — скидка (\d+)%\. Сколько нужно заплатить за печь №(\d+) "
                r"с доставкой, если доставка стоит ([\d  ]+) руб\.\?",
                condition,
            )
            if not match:
                raise ValueError("Conditional discount wording is invalid")
            threshold, item_d, delivery_d, row_id, delivery = map(
                _parse_rub_or_int, match.groups()
            )
            if row_id != 2:
                raise ValueError("Conditional purchase task must use the referenced stove row")
            price = cast(int, rows[row_id - 1]["price_rub"])
            if price <= threshold:
                raise ValueError("Strict 'дороже' condition is not met")
            result = Fraction(price * (100 - item_d) + delivery * (100 - delivery_d), 100)
            return _integer_fraction(result)
        if family == FAMILY_IDS[11]:
            if "Размеры кожуха указаны на рисунке" not in condition or (
                "Центр окружности находится в середине нижнего основания" not in condition
            ):
                raise ValueError("Arc condition lacks the confirmed circle-center construction")
            scenario_context = _context_dict(scenario)
            arc_svg = _svg_arc(
                cast(int, scenario_context["arc_width_cm"]),
                cast(int, scenario_context["arc_height_cm"]),
            )
            arc_digest = sha256(arc_svg).hexdigest()
            if not any(
                asset.content_type == "image/svg+xml" and asset.sha256 == arc_digest
                for asset in rendered.assets
            ):
                raise ValueError("Visible arc SVG is absent or differs from the scenario")
            root_element = ET.fromstring(arc_svg)
            visible_text = " ".join(
                (node.text or "").strip()
                for node in root_element.iter()
                if node.tag.endswith("text") and (node.text or "").strip()
            )
            width_cm = int(root_element.attrib.get("data-width-cm", "0"))
            height_cm = int(root_element.attrib.get("data-height-cm", "0"))
            if not width_cm or not height_cm or f"{width_cm} см" not in visible_text or (
                f"{height_cm} см" not in visible_text
            ):
                raise ValueError("Visible arc dimensions are missing from the figure")
            root = isqrt((width_cm // 2) ** 2 + height_cm**2)
            _validate_arc_svg(arc_svg, width_cm, height_cm, root)
            return str(root)
        raise ValueError("STOVE family has no independent solver")

    def _validate_rendered_assets(
        self, scenario: ScenarioDraft, rendered: RenderedScenario
    ) -> None:
        context = _context_dict(scenario)
        table_payload = _svg_table(context)
        arc_payload = _svg_arc(
            cast(int, context["arc_width_cm"]), cast(int, context["arc_height_cm"])
        )
        expected_svg_hashes = {sha256(table_payload).hexdigest(), sha256(arc_payload).hexdigest()}
        actual_svg_hashes = {
            asset.sha256 for asset in rendered.assets if asset.content_type == "image/svg+xml"
        }
        png_assets = [asset for asset in rendered.assets if asset.content_type == "image/png"]
        expected_png_hashes = {
            sha256(_png_table(context)).hexdigest(),
            sha256(
                _png_arc(
                    cast(int, context["arc_width_cm"]), cast(int, context["arc_height_cm"])
                )
            ).hexdigest(),
        }
        if (
            expected_svg_hashes != actual_svg_hashes
            or {asset.sha256 for asset in png_assets} != expected_png_hashes
            or len(png_assets) != 2
        ):
            raise ValueError("Rendered STOVE SVG/PNG asset references do not match scenario data")
        table_svg = ET.fromstring(table_payload)
        visible_svg_text = " ".join(text.strip() for text in table_svg.itertext() if text.strip())
        for row in _rows(context):
            for value in (
                str(row["id"]),
                str(row["mass_kg"]),
                str(row["min_m3"]),
                str(row["max_m3"]),
            ):
                if value not in visible_svg_text:
                    raise ValueError("Table SVG omits a visible table value")
        if _table_text(context) not in rendered.shared_context:
            raise ValueError("Shared text table differs from scenario table")

    def _validate_solution_steps(self, question: QuestionDraft, shared: str) -> None:
        if not question.solution_steps or not question.hints:
            raise ValueError("STOVE question requires hints and a worked solution")
        # Ensure no stale catalog key (notably 408240's answer '2') enters the
        # generated solution text or canonical answers.
        if (
            question.canonical_answer == "2"
            and question.position == 3
            and "15000" in question.condition
        ):
            raise ValueError("Conflicted catalog key 408240 is prohibited")


def _parse_rub_or_int(value: str) -> int:
    return int(value.replace(" ", "").replace(" ", ""))


def _extract_money(condition: str, marker: str) -> int:
    match = re.search(re.escape(marker) + r"\s*([\d  ]+)\s*руб\.", condition)
    if not match:
        raise ValueError(f"Visible condition is missing money after {marker}")
    return _parse_rub_or_int(match.group(1))


def _parse_room_condition(condition: str) -> tuple[Fraction, Fraction, Fraction]:
    match = re.search(r"Размеры парной: ([\d,]+) × ([\d,]+) × ([\d,]+) м", condition)
    if not match:
        raise ValueError("Question must render all three room dimensions")
    return tuple(Fraction(value.replace(",", ".")) for value in match.groups())  # type: ignore[return-value]  # noqa: E501


def _parse_visible_context(shared: str) -> dict[str, object]:
    row_re = re.compile(r"^(\d) \| ([^|]+) \| (\d+)–(\d+) \| (\d+) \| ([\d  ]+)$", re.MULTILINE)
    rows = [
        {
            "id": int(i),
            "kind": kind.strip(),
            "min_m3": int(low),
            "max_m3": int(high),
            "mass_kg": int(mass),
            "price_rub": _parse_rub_or_int(price),
        }
        for i, kind, low, high, mass, price in row_re.findall(shared)
    ]
    if len(rows) != 3:
        raise ValueError("Visible shared table must contain exactly three stove rows")
    room_match = re.search(
        r"Размеры парной: ([\d,]+) × ([\d,]+) × ([\d,]+) м", shared
    )
    if not room_match:
        raise ValueError("Visible shared context must include room dimensions")
    room_dimensions_m = tuple(
        Fraction(value.replace(",", ".")) for value in room_match.groups()
    )
    return {"rows": rows, "room_dimensions_m": room_dimensions_m}


def _integer_fraction(value: Fraction) -> str:
    if value.denominator != 1:
        raise ValueError("Expected a whole-ruble answer")
    return str(value.numerator)


def _validate_arc_svg(svg: bytes, width_cm: int, height_cm: int, radius: int) -> None:
    root = ET.fromstring(svg)
    if int(root.attrib.get("data-width-cm", "-1")) != width_cm:
        raise ValueError("Arc SVG width label differs from the visible condition")
    if int(root.attrib.get("data-height-cm", "-1")) != height_cm:
        raise ValueError("Arc SVG height label differs from the visible condition")
    texts = " ".join((node.text or "") for node in root.iter() if node.tag.endswith("text"))
    if "data-radius-cm" in root.attrib or "R=" in texts:
        raise ValueError("Arc SVG reveals the requested radius")
    for label in (f"{width_cm} см", f"{height_cm} см", "O"):
        if label not in texts:
            raise ValueError("Arc SVG is missing a required visible label")
    center = next((node for node in root.iter() if node.tag.endswith("circle")), None)
    if center is None or center.attrib.get("cx") != "400" or center.attrib.get("cy") != "500":
        raise ValueError("Arc SVG center must be the midpoint of the lower base")
    arc_path = next(
        (
            node
            for node in root.iter()
            if node.tag.endswith("path") and node.attrib.get("stroke") == "#1c5d7a"
        ),
        None,
    )
    if arc_path is None:
        raise ValueError("Arc SVG is missing the visible circle segment")
    points = [
        (float(x), float(y))
        for x, y in re.findall(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", arc_path.attrib["d"])
    ]
    half_width = width_cm // 2
    scale, cx, cy = 4, 400, 500
    left = (cx - half_width * scale, cy - height_cm * scale)
    right = (cx + half_width * scale, cy - height_cm * scale)
    peak = (cx, cy - radius * scale)
    if not points or any(
        abs(actual[axis] - expected[axis]) > 0.001
        for actual, expected in (
            (points[0], left),
            (points[-1], right),
            (min(points, key=lambda p: p[1]), peak),
        )
        for axis in (0, 1)
    ):
        raise ValueError("Arc path endpoints or highest point disagree with the room geometry")
    dimension_lines = [
        node
        for node in root.iter()
        if node.tag.endswith("line")
        and node.attrib.get("marker-start") == "url(#arrow)"
        and node.attrib.get("marker-end") == "url(#arrow)"
    ]
    if len(dimension_lines) != 2:
        raise ValueError("Arc SVG must show width and height dimensions with arrows")


class StoveAdapter:
    story_code = "STOVE"
    generator = StoveGenerator()
    question_builder = StoveQuestionBuilder()
    independent_oracle = StoveOracle()
    renderer = StoveRenderer()
    answer_policies: Mapping[tuple[str, str], AnswerPolicy] = MappingProxyType(
        {
            (policy.policy_id, policy.version): policy
            for policy in (
                ExactSequencePolicy(),
                NumericAnswerPolicy("decimal_exact"),
                NumericAnswerPolicy("integer_rubles"),
                NumericAnswerPolicy("integer_centimeters"),
            )
        }
    )
    family_registry = tuple(
        FamilyRegistration(
            family_id=family_id,
            position=_FAMILY_POSITION[family_id],
            status=FamilyStatus.ENABLED_CANDIDATE,
            answer_policy_id=(
                "digit_sequence_exact_3"
                if family_id in FAMILY_IDS[:2]
                else "integer_centimeters"
                if family_id == FAMILY_IDS[11]
                else "decimal_exact"
                if family_id in FAMILY_IDS[2:5]
                else "integer_rubles"
            ),
            answer_policy_version="1",
            enabled=False,
            source_ids=SOURCE_IDS[family_id],
        )
        for family_id in FAMILY_IDS
    )


def build_adapter() -> StoveAdapter:
    """Return the isolated, fail-closed STOVE story adapter."""
    return StoveAdapter()
