"""Deterministic, fail-closed apartment-plan adapter for OGE tasks 1–5.

The geometry is authored on a 0.4 m integer lattice. PNG and SVG are rendered
from that model; neither is a modified third-party raster.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from fractions import Fraction
from random import Random
from typing import Any, cast

from PIL import Image, ImageDraw, ImageFont

from app.math.scenario_engine import (
    FamilyRegistration,
    FamilyStatus,
    JsonValue,
    QuestionDraft,
    RenderedScenario,
    ScenarioAssetRef,
    ScenarioDraft,
    ScenarioSnapshot,
    StoryAdapter,
)

GENERATOR_VERSION = "flat-grid-1.0.0"
COMPATIBILITY_VERSION = "flat-compat-1"
CELL_M = Fraction(2, 5)
SOURCE_VECTOR_SEED = 20220523

# Fixed authored topology reconstructed from the shared plan dimensions in the
# fixture. Rectangles are half-open integer cell bounds; hall is L-shaped.
ROOM_PARTS: dict[str, tuple[tuple[int, int, int, int], ...]] = {
    "bedroom": ((0, 0, 6, 13),),
    "bedroom_2": ((18, 0, 24, 13),),
    "living": ((6, 0, 18, 13),),
    "hall": ((9, 13, 24, 19), (5, 18, 9, 19)),
    "pantry": ((5, 13, 9, 18),),
    "bathroom": ((0, 13, 5, 19),),
    "loggia_1": ((-3, 1, 0, 11),),
    "loggia_2": ((18, -5, 24, 0),),
}
ROOM_NAMES = {
    "bedroom": "спальня",
    "bedroom_2": "вторая спальня",
    "living": "гостиная",
    "hall": "коридор",
    "pantry": "кладовая",
    "bathroom": "санузел",
    "loggia_1": "первая лоджия",
    "loggia_2": "вторая лоджия",
}
# Gaps are doors in shared walls; this graph never changes with seed.
DOORS = (
    ("living", "bedroom"),
    ("living", "bedroom_2"),
    ("hall", "bedroom_2"),
    ("hall", "living"),
    ("hall", "pantry"),
    ("pantry", "bathroom"),
    ("bedroom", "loggia_1"),
    ("bedroom_2", "loggia_2"),
)
DOOR_MARKS = (
    (6, 6, "v"),
    (18, 6, "v"),
    (21, 13, "h"),
    (12, 13, "h"),
    (9, 15, "v"),
    (5, 15, "v"),
    (0, 6, "v"),
    (21, 0, "h"),
)
WINDOW_MARKS = ((10, 0, "h"), (0, 16, "v"))
FAMILY_POSITION = {
    "FLAT-01-ROOM-MATCH": 1,
    "FLAT-02-TILE-PACK": 2,
    "FLAT-02-PARQUET-PACK": 2,
    "FLAT-03-RECT-AREA": 3,
    "FLAT-04-RECT-PERCENT": 4,
    "FLAT-05-WASHER-MIN": 5,
    "FLAT-05-INTERNET-MIN": 5,
}
FAMILY_SOURCES = {
    "FLAT-01-ROOM-MATCH": ("400935", "424898", "409274"),
    "FLAT-02-TILE-PACK": ("409278",),
    "FLAT-02-PARQUET-PACK": ("409286", "409281", "424899"),
    "FLAT-03-RECT-AREA": ("424900",),
    "FLAT-04-RECT-PERCENT": ("424901",),
    "FLAT-05-WASHER-MIN": ("409311", "403919", "409308"),
    "FLAT-05-INTERNET-MIN": ("424902",),
}


def _decimal(value: Fraction) -> str:
    """Format exact terminating tenths/hundredths without float arithmetic."""
    if value.denominator not in (1, 2, 4, 5, 10, 20, 25, 50, 100):
        raise ValueError("Displayed measurement is not an exact decimal")
    decimal = value.numerator * (100 // value.denominator)
    whole, cents = divmod(decimal, 100)
    if cents == 0:
        return str(whole)
    if cents % 10 == 0:
        return f"{whole},{cents // 10}"
    return f"{whole},{cents:02d}"


def _room_area_cells(room: str) -> int:
    return sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in ROOM_PARTS[room])


def _to_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Boolean is not an integer measurement")
    if isinstance(value, int):
        return value
    if isinstance(value, Fraction) and value.denominator == 1:
        return value.numerator
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    raise ValueError("Expected an exact integer value")


class _NumericPolicy:
    policy_id = "oge15.flat.numeric"
    version = "1"

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool:
        raw = raw_answer.strip().replace(" ", "").replace(".", ",")
        if not re.fullmatch(r"\d+(?:,\d{1,2})?", raw):
            return False
        try:
            return Fraction(raw.replace(",", ".")) == Fraction(canonical_answer.replace(",", "."))
        except (ValueError, ZeroDivisionError):
            return False


class _Generator:
    def generate_scenario(self, seed: int) -> ScenarioDraft:
        if not 0 <= seed < 2**63:
            raise ValueError("Seed must fit a non-negative PostgreSQL bigint")
        rng = Random(f"oge15-flat:{GENERATOR_VERSION}:{seed}")
        labels = list(range(1, 9))
        rng.shuffle(labels)
        room_labels = dict(zip(ROOM_PARTS, labels, strict=True))
        if seed == SOURCE_VECTOR_SEED:
            room_labels = {
                "bathroom": 1,
                "pantry": 3,
                "bedroom": 4,
                "living": 6,
                "bedroom_2": 2,
                "hall": 5,
                "loggia_1": 7,
                "loggia_2": 8,
            }
        # Measurements remain on the fixed 0.4 m lattice. Integer multipliers
        # are bounded by the same fixed room topology; no wall is randomized.
        room_cells = {name: _room_area_cells(name) for name in ROOM_PARTS}
        tile_pack = rng.choice((10, 12, 15, 18, 20))
        parquet_pack = 14 if seed == SOURCE_VECTOR_SEED else rng.choice((8, 10, 12, 14))
        tile_cells = room_cells["bathroom"]
        area_room = "loggia_1"
        percent_base = room_cells["pantry"]
        percent_delta = room_cells["bathroom"] - percent_base
        washer_models = [
            {
                "model": "А",
                "type": "фронтальная",
                "capacity": 6,
                "height": 85,
                "price": 28000,
                "install": 1000,
                "delivery_pct": 10,
            },
            {
                "model": "Б",
                "type": "фронтальная",
                "capacity": 7,
                "height": 84,
                "price": 31000,
                "install": 0,
                "delivery_pct": 0,
            },
            {
                "model": "В",
                "type": "вертикальная",
                "capacity": 8,
                "height": 86,
                "price": 30000,
                "install": 1500,
                "delivery_pct": 0,
            },
            {
                "model": "Г",
                "type": "фронтальная",
                "capacity": 7,
                "height": 82,
                "price": 33000,
                "install": 0,
                "delivery_pct": 0,
            },
            {
                "model": "Д",
                "type": "фронтальная",
                "capacity": 8,
                "height": 84,
                "price": 31900,
                "install": 500,
                "delivery_pct": 15,
            },
            {
                "model": "Е",
                "type": "вертикальная",
                "capacity": 7,
                "height": 82,
                "price": 29500,
                "install": 500,
                "delivery_pct": 0,
            },
        ]
        traffic = 800 + rng.randrange(0, 6) * 100
        context: dict[str, Any] = {
            "grid_cell_m": "0.4",
            "topology_id": "flat_2room_8label_v1",
            "room_parts": {
                key: [list(rect) for rect in value] for key, value in ROOM_PARTS.items()
            },
            "room_labels": room_labels,
            "door_graph": [list(pair) for pair in DOORS],
            "tile": {"room": "bathroom", "tile_cells": 1, "pack": tile_pack, "count": tile_cells},
            "parquet": {
                "room": "living",
                "width_cells": 12,
                "height_cells": 13,
                "board_m": ["0.2", "0.8"],
                "pack": parquet_pack,
                "count": 156,
            },
            "area_room": area_room,
            "percent": {"base": percent_base, "delta": percent_delta},
            "washers": washer_models,
            "internet": {
                "traffic_mb": 1000 if seed == SOURCE_VECTOR_SEED else traffic,
                "plans": [
                    {"name": "Базовый", "included_mb": 600, "fee": 650, "overage": "2"},
                    {"name": "Оптимальный", "included_mb": 900, "fee": 820, "overage": "1.5"},
                    {"name": "Безлимитный", "included_mb": None, "fee": 950, "overage": "0"},
                ],
            },
        }
        return ScenarioDraft(
            story_code="FLAT",
            seed=seed,
            generator_version=GENERATOR_VERSION,
            context=cast(Mapping[str, JsonValue], context),
            compatibility_matrix_version=COMPATIBILITY_VERSION,
            provenance=(
                "sdamgia:424898",
                "sdamgia:424899",
                "sdamgia:424900",
                "sdamgia:424901",
                "sdamgia:424902",
                "catalog-attributed; not independently verified as FIPI originals",
            ),
        )


class _QuestionBuilder:
    def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft:
        c = cast(Mapping[str, Any], scenario.context)
        labels = cast(Mapping[str, int], c["room_labels"])
        variant = (
            1
            if scenario.seed == SOURCE_VECTOR_SEED
            else Random(f"flat-family:{scenario.seed}:{position}").randrange(2)
        )
        family = {
            1: "FLAT-01-ROOM-MATCH",
            2: ("FLAT-02-TILE-PACK", "FLAT-02-PARQUET-PACK")[variant],
            3: "FLAT-03-RECT-AREA",
            4: "FLAT-04-RECT-PERCENT",
            5: ("FLAT-05-WASHER-MIN", "FLAT-05-INTERNET-MIN")[variant],
        }.get(position)
        if family is None:
            raise ValueError("Question position must be 1 through 5")
        if position == 1:
            rooms = ("bathroom", "pantry", "bedroom", "living")
            answer = "".join(str(labels[name]) for name in rooms)
            condition = (
                "На плане коридор расположен у входа. Кладовая имеет двери в коридор и санузел, "
                "а в санузле только одна дверь. Спальня выходит на левую лоджию; гостиная — "
                "самое большое помещение. Запишите номера в порядке: санузел, кладовая, "
                "спальня, гостиная."
            )
            model: dict[str, object] = {"rooms_in_order": list(rooms), "labels": dict(labels)}
            solution = (
                "Определите номера помещений по подписям на плане.",
                f"В заданном порядке получаем {answer}.",
            )
        elif position == 2 and family == "FLAT-02-TILE-PACK":
            tile = cast(Mapping[str, object], c["tile"])
            count, pack = _to_int(tile["count"]), _to_int(tile["pack"])
            answer = str((count + pack - 1) // pack)
            condition = (
                f"Пол санузла выложен плитками {_decimal(CELL_M)}×{_decimal(CELL_M)} м. "
                f"В упаковке {pack} плиток. Сколько упаковок потребуется? Резка не нужна."
            )
            model = {
                "family_alternatives": ["FLAT-02-TILE-PACK", "FLAT-02-PARQUET-PACK"],
                "room_cells": count,
                "tile_cells": 1,
                "pack": pack,
                "count": count,
            }
            solution = (
                f"На плане помещение занимает {count} клеток; столько плиток требуется.",
                f"{count} : {pack} с округлением вверх = {answer} упаковок.",
            )
        elif position == 2:
            parquet = cast(Mapping[str, object], c["parquet"])
            count, pack = _to_int(parquet["count"]), _to_int(parquet["pack"])
            answer = str((count + pack - 1) // pack)
            condition = (
                "Размер гостиной на плане 4,8×5,2 м. Её покрывают паркетными досками "
                f"0,2×0,8 м без распила. В упаковке {pack} досок. "
                "Сколько упаковок потребуется?"
            )
            model = {
                "room": "living",
                "width_cells": 12,
                "height_cells": 13,
                "board_m": ["0.2", "0.8"],
                "pack": pack,
                "count": count,
            }
            solution = (
                "При укладке без распила помещается 6×26 = 156 досок.",
                f"156 : {pack} с округлением вверх = {answer} упаковок.",
            )
        elif position == 3:
            room = "loggia_1"
            area = Fraction(_room_area_cells(room), 1) * CELL_M * CELL_M
            answer = _decimal(area)
            condition = (
                f"Найдите площадь помещения «{ROOM_NAMES[room]}», если сторона клетки плана "
                "равна 0,4 м. Ответ дайте в квадратных метрах."
            )
            model = {"room": room, "area_cells": _room_area_cells(room), "cell_area": "0.16"}
            solution = (
                f"Площадь составляет {_room_area_cells(room)} клеток.",
                f"{_room_area_cells(room)} · 0,16 = {answer} м².",
            )
        elif position == 4 and family == "FLAT-04-RECT-PERCENT":
            pct = cast(Mapping[str, int], c["percent"])
            base, delta = pct["base"], pct["delta"]
            answer = str(100 * delta // base)
            condition = (
                f"Площадь кладовой равна {base} клеткам, а площадь санузла на {delta} клеток "
                "больше. На сколько процентов площадь санузла больше площади кладовой?"
            )
            model = {"base_cells": base, "delta_cells": delta, "denominator": "кладовая"}
            solution = (
                f"Разность площадей равна {delta} клеткам.",
                f"{delta}/{base} · 100% = {answer}%.",
            )
        elif position == 4:
            base, delta = (
                _room_area_cells("pantry"),
                _room_area_cells("bathroom") - _room_area_cells("pantry"),
            )
            if base <= 0 or (100 * delta) % base:
                raise ValueError("Plan areas do not produce an exact percentage")
            answer = str(100 * delta // base)
            condition = (
                "Площадь санузла на плане больше площади кладовой. На сколько процентов площадь "
                "санузла больше площади кладовой? Сторона клетки — 0,4 м."
            )
            model = {
                "base_cells": base,
                "delta_cells": delta,
                "denominator": "кладовая",
                "bathroom_cells": _room_area_cells("bathroom"),
            }
            solution = (
                f"Площадь кладовой — {base} клеток, санузла — {base + delta} клеток.",
                f"{delta}/{base} · 100% = {answer}%.",
            )
        elif position == 5 and family == "FLAT-05-WASHER-MIN":
            models = cast(list[dict[str, object]], c["washers"])
            eligible = [
                m
                for m in models
                if m["type"] == "фронтальная"
                and _to_int(m["capacity"]) >= 7
                and _to_int(m["height"]) <= 85
            ]
            costs = [
                _to_int(m["price"])
                + _to_int(m["install"])
                + _to_int(m["price"]) * _to_int(m["delivery_pct"]) // 100
                for m in eligible
            ]
            winner = min(range(len(costs)), key=costs.__getitem__)
            answer = str(costs[winner])
            rows = "; ".join(
                f"{m['model']}: {m['type']}, загрузка {m['capacity']} кг, высота {m['height']} см, "
                f"цена {m['price']} руб., установка {m['install']} руб., "
                f"доставка {m['delivery_pct']}%"
                for m in models
            )
            condition = (
                "Нужна фронтальная машина загрузкой не менее 7 кг и высотой не более 85 см. "
                f"Сравните модели с учётом цены, установки и доставки: {rows}. "
                "Найдите минимальную полную стоимость."
            )
            model = {
                "models": models,
                "eligible": [m["model"] for m in eligible],
                "costs": costs,
                "winner": eligible[winner]["model"],
            }
            solution = (
                "После ограничений подходят модели "
                f"{', '.join(cast(list[str], model['eligible']))}.",
                f"Минимальная полная стоимость — {answer} руб.",
            )
        else:
            internet = cast(Mapping[str, object], c["internet"])
            traffic = _to_int(internet["traffic_mb"])
            plans = cast(list[dict[str, object]], internet["plans"])
            tariff_costs = [
                _to_int(p["fee"])
                + max(0, traffic - _to_int(p["included_mb"] or traffic))
                * Fraction(str(p["overage"]))
                for p in plans
            ]
            if any(cost.denominator != 1 for cost in tariff_costs):
                raise ValueError("Tariff cost must be an integer for the displayed data")
            integer_costs = [_to_int(cost) for cost in tariff_costs]
            winner = min(range(len(tariff_costs)), key=tariff_costs.__getitem__)
            answer = str(integer_costs[winner])
            rows = "; ".join(
                f"{p['name']}: абонплата {p['fee']} руб., включено "
                f"{p['included_mb'] or 'безлимит'} МБ, сверх лимита {p['overage']} руб./МБ"
                for p in plans
            )
            condition = (
                f"За месяц использовано {traffic} МБ. Выберите тариф с наименьшей стоимостью: "
                f"{rows}. Сколько рублей нужно заплатить?"
            )
            model = {
                "traffic_mb": traffic,
                "plans": plans,
                "costs": integer_costs,
                "winner": plans[winner]["name"],
            }
            solution = (
                f"Стоимость тарифов по порядку: {', '.join(map(str, integer_costs))} руб.",
                f"Минимальная стоимость — {answer} руб.",
            )
        hints = {
            "FLAT-01-ROOM-MATCH": (
                "Начните с коридора у входа и проверьте связи помещений по дверным проёмам.",
                "Отделите санузел с одной дверью от кладовой, которая соединяет его с коридором.",
            ),
            "FLAT-02-TILE-PACK": (
                "Измерьте санузел по клеткам плана и переведите длины в метры.",
                "Сравните размеры клетки с плиткой, затем посчитайте упаковки с округлением вверх.",
            ),
            "FLAT-02-PARQUET-PACK": (
                "Сопоставьте длины гостиной и доски, чтобы определить число рядов.",
                "Проверьте, сколько досок войдёт в каждый ряд без распила, "
                "затем разделите на размер упаковки.",
            ),
            "FLAT-03-RECT-AREA": (
                "Найдите ширину и длину лоджии в клетках плана.",
                "Сначала умножьте число клеток на площадь одной клетки в квадратных метрах.",
            ),
            "FLAT-04-RECT-PERCENT": (
                "Найдите разность площадей санузла и кладовой.",
                "Для процента увеличения разделите разность на площадь кладовой.",
            ),
            "FLAT-05-WASHER-MIN": (
                "Сначала оставьте модели нужного типа, загрузки и высоты.",
                "К цене каждой подходящей модели прибавьте установку и доставку, "
                "рассчитанную от цены машины.",
            ),
            "FLAT-05-INTERNET-MIN": (
                "Для каждого ограниченного плана найдите объём сверх включённого лимита.",
                "Прибавьте плату за превышение к абонентской плате и сравните "
                "все три итоговые суммы.",
            ),
        }[family]
        q = QuestionDraft(
            position,
            scenario.seed,
            family,
            GENERATOR_VERSION,
            condition,
            "oge15.flat.numeric",
            "1",
            answer,
            hints,
            solution,
            cast(Mapping[str, JsonValue], model),
        )
        return q


class _Renderer:
    def _svg(self, scenario: ScenarioDraft) -> bytes:
        c = scenario.context
        labels = cast(Mapping[str, int], c["room_labels"])
        scale, ox, oy = 36, 150, 210
        width, height = 1120, 1000
        parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            '<text x="40" y="48" font-size="26" font-family="sans-serif">'
            "План квартиры · клетка 0,4 м</text>",
            '<text x="40" y="78" font-size="17" font-family="sans-serif">'
            "Синие проёмы — двери · бирюзовые — окна · вход отмечен красным</text>",
        ]
        for room, rectangles in ROOM_PARTS.items():
            for x1, y1, x2, y2 in rectangles:
                x, y = ox + x1 * scale, oy + y1 * scale
                w, h = (x2 - x1) * scale, (y2 - y1) * scale
                parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff"/>')
                for gx in range(x1 + 1, x2):
                    px = ox + gx * scale
                    parts.append(
                        f'<path d="M {px} {y} V {y + h}" stroke="#dce4eb" stroke-width="1"/>'
                    )
                for gy in range(y1 + 1, y2):
                    py = oy + gy * scale
                    parts.append(
                        f'<path d="M {x} {py} H {x + w}" stroke="#dce4eb" stroke-width="1"/>'
                    )
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                    'fill="none" stroke="#202b38" stroke-width="4"/>'
                )
            x1, y1, x2, y2 = rectangles[0]
            cx, cy = ox + (x1 + x2) * scale // 2, oy + (y1 + y2) * scale // 2
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="17" fill="#e9f2ff" '
                f'stroke="#1463a5" stroke-width="2"/><text x="{cx}" y="{cy + 7}" '
                f'text-anchor="middle" font-size="19" '
                f'font-family="sans-serif">{labels[room]}</text>'
            )
        # Door gaps are symbolized with short colored segments on fixed shared walls.
        for x, y, orientation in DOOR_MARKS:
            px, py = ox + x * scale, oy + y * scale
            start, end = (
                (f"{px - 12} {py}", f"{px + 12} {py}")
                if orientation == "h"
                else (f"{px} {py - 12}", f"{px} {py + 12}")
            )
            parts.append(
                f'<path d="M {start} L {end}" stroke="white" stroke-width="8"/>'
                f'<path d="M {start} L {end}" stroke="#1463a5" stroke-width="3"/>'
            )
        for x, y, orientation in WINDOW_MARKS:
            px, py = ox + x * scale, oy + y * scale
            start, end = (
                (f"{px - 30} {py}", f"{px + 30} {py}")
                if orientation == "h"
                else (f"{px} {py - 30}", f"{px} {py + 30}")
            )
            parts.append(
                f'<path d="M {start} L {end}" stroke="white" stroke-width="9"/>'
                f'<path d="M {start} L {end}" stroke="#008b8b" stroke-width="4"/>'
            )
        entry_x, entry_y = ox + 7 * scale, oy + 19 * scale
        parts.append(
            f'<path d="M {entry_x - 30} {entry_y} L {entry_x + 30} {entry_y}" '
            'stroke="white" stroke-width="9"/>'
            f'<path d="M {entry_x - 30} {entry_y} L {entry_x + 30} {entry_y}" '
            'stroke="#bd3030" stroke-width="5"/>'
            f'<text x="{entry_x - 20}" y="{entry_y + 28}" font-size="18">Вход</text>'
        )
        parts.append("</svg>")
        return "".join(parts).encode()

    def _png(self, scenario: ScenarioDraft) -> bytes:
        c = scenario.context
        labels = cast(Mapping[str, int], c["room_labels"])
        scale, ox, oy = 36, 150, 210
        image = Image.new("RGB", (1120, 1000), "white")
        draw = ImageDraw.Draw(image)
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except OSError:
            font = ImageFont.load_default()
        draw.text((40, 30), "План квартиры · клетка 0,4 м", fill="#202b38", font=font)
        draw.text(
            (40, 62),
            "Сторона клетки 0,4 м · синие проёмы — двери · бирюзовые — окна · вход красный",
            fill="#202b38",
            font=font,
        )
        for room, rectangles in ROOM_PARTS.items():
            for x1, y1, x2, y2 in rectangles:
                box = (ox + x1 * scale, oy + y1 * scale, ox + x2 * scale, oy + y2 * scale)
                draw.rectangle(box, fill="white")
                for gx in range(x1 + 1, x2):
                    px = ox + gx * scale
                    draw.line((px, box[1], px, box[3]), fill="#dce4eb", width=1)
                for gy in range(y1 + 1, y2):
                    py = oy + gy * scale
                    draw.line((box[0], py, box[2], py), fill="#dce4eb", width=1)
                draw.rectangle(box, outline="#202b38", width=4)
            x1, y1, x2, y2 = rectangles[0]
            cx, cy = ox + (x1 + x2) * scale // 2, oy + (y1 + y2) * scale // 2
            draw.ellipse(
                (cx - 17, cy - 17, cx + 17, cy + 17), fill="#e9f2ff", outline="#1463a5", width=2
            )
            draw.text((cx - 6, cy - 12), str(labels[room]), fill="#102b45", font=font)
        for x, y, orientation in DOOR_MARKS:
            px, py = ox + x * scale, oy + y * scale
            bounds = (
                (px - 12, py, px + 12, py) if orientation == "h" else (px, py - 12, px, py + 12)
            )
            draw.line(bounds, fill="white", width=8)
            draw.line(bounds, fill="#1463a5", width=3)
        for x, y, orientation in WINDOW_MARKS:
            px, py = ox + x * scale, oy + y * scale
            bounds = (
                (px - 30, py, px + 30, py) if orientation == "h" else (px, py - 30, px, py + 30)
            )
            draw.line(bounds, fill="white", width=9)
            draw.line(bounds, fill="#008b8b", width=4)
        entry_x, entry_y = ox + 7 * scale, oy + 19 * scale
        draw.line((entry_x - 30, entry_y, entry_x + 30, entry_y), fill="white", width=9)
        draw.line((entry_x - 30, entry_y, entry_x + 30, entry_y), fill="#bd3030", width=5)
        draw.text((entry_x - 20, entry_y + 8), "Вход", fill="#202b38", font=font)
        from io import BytesIO

        buf = BytesIO()
        image.save(buf, format="PNG", optimize=False)
        return buf.getvalue()

    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario:
        svg, png = self._svg(scenario), self._png(scenario)
        assets = tuple(
            ScenarioAssetRef(
                hashlib.sha256(data).hexdigest(),
                mime,
                f"sha256/{hashlib.sha256(data).hexdigest()}.{ext}",
            )
            for data, mime, ext in ((png, "image/png", "png"), (svg, "image/svg+xml", "svg"))
        )
        context = (
            "План квартиры: восемь помещений с цифровыми метками; сторона клетки 0,4 м. "
            "Коридор у входа; кладовая имеет двери в коридор и санузел; в санузле одна дверь. "
            "Спальня выходит на левую лоджию; гостиная — самое большое помещение. "
            "Синие штрихи обозначают двери, бирюзовые — окна, красный — вход. "
            "Это собственная SVG/PNG схема фиксированной топологии."
        )
        return RenderedScenario(context, assets)

    def restore_asset(self, snapshot: ScenarioSnapshot, asset: ScenarioAssetRef) -> bytes:
        if snapshot.story_code != "FLAT" or snapshot.generator_version != GENERATOR_VERSION:
            raise ValueError("Unsupported FLAT snapshot renderer version")
        scenario = ScenarioDraft(
            "FLAT",
            snapshot.seed,
            snapshot.generator_version,
            snapshot.context,
            snapshot.compatibility_matrix_version,
            snapshot.provenance,
        )
        data = (
            self._png(scenario)
            if asset.content_type == "image/png"
            else self._svg(scenario)
            if asset.content_type == "image/svg+xml"
            else b""
        )
        return data


class _Oracle:
    def validate_scenario(self, scenario: ScenarioDraft) -> None:
        c = cast(Mapping[str, Any], scenario.context)
        labels = cast(Mapping[str, int], c["room_labels"])
        if set(labels) != set(ROOM_PARTS) or set(labels.values()) != set(range(1, 9)):
            raise ValueError("Room labels must be a bijection over the fixed 8-room plan")
        if c["grid_cell_m"] != "0.4" or c["topology_id"] != "flat_2room_8label_v1":
            raise ValueError("Plan scale/topology differs from the validated fixed template")
        if tuple(tuple(edge) for edge in c["door_graph"]) != DOORS:
            raise ValueError("Door graph differs from the fixed visible plan topology")
        if len(DOOR_MARKS) != len(DOORS):
            raise ValueError("Door drawing and door graph have different edge counts")
        actual_parts = cast(Mapping[str, object], c["room_parts"])
        expected_parts = {
            key: tuple(tuple(rect) for rect in value) for key, value in ROOM_PARTS.items()
        }
        if actual_parts != expected_parts:
            raise ValueError("Room geometry differs from the fixed rendered plan")
        if CELL_M != Fraction(2, 5) or _room_area_cells("living") <= max(
            _room_area_cells(r) for r in ROOM_PARTS if r != "living"
        ):
            raise ValueError("Scale or largest-room invariant failed")
        occupancy: dict[tuple[int, int], str] = {}
        for room, rectangles in ROOM_PARTS.items():
            if room.startswith("loggia"):
                continue
            for x1, y1, x2, y2 in rectangles:
                for x in range(x1, x2):
                    for y in range(y1, y2):
                        if (x, y) in occupancy:
                            raise ValueError("Room polygons overlap on the integer grid")
                        occupancy[(x, y)] = room
        if set(occupancy) != {(x, y) for x in range(24) for y in range(19)}:
            raise ValueError("Room polygons leave gaps or exceed the apartment outline")
        for (x, y, orientation), (left_room, right_room) in zip(DOOR_MARKS, DOORS, strict=True):
            adjacent = {(x - 1, y), (x, y)} if orientation == "v" else {(x, y - 1), (x, y)}
            if any(cell not in occupancy for cell in adjacent):
                # Balcony doors are the two intentional exterior connections.
                if (left_room, right_room) == ("bedroom", "loggia_1"):
                    adjacent = {(x - 1, y), (x, y)}
                    rooms = {"bedroom": (x, y), "loggia_1": (x - 1, y)}
                elif (left_room, right_room) == ("bedroom_2", "loggia_2"):
                    adjacent = {(x, y - 1), (x, y)}
                    rooms = {"bedroom_2": (x, y), "loggia_2": (x, y - 1)}
                else:
                    raise ValueError("Door mark is not on a shared wall")
                if any(
                    ROOM_PARTS[room][0][0] <= cell[0] < ROOM_PARTS[room][0][2]
                    and ROOM_PARTS[room][0][1] <= cell[1] < ROOM_PARTS[room][0][3]
                    for room, cell in rooms.items()
                ):
                    continue
                raise ValueError("Exterior door mark does not connect its declared rooms")
            room_names = {occupancy[cell] for cell in adjacent}
            if room_names != {left_room, right_room}:
                raise ValueError("Visible door gap does not match the language door graph")
        tile = cast(Mapping[str, int], c["tile"])
        if tile["tile_cells"] != 1 or tile["count"] != _room_area_cells("bathroom"):
            raise ValueError("Tile count does not match exact room lattice")
        parquet = cast(Mapping[str, object], c["parquet"])
        if (parquet["width_cells"], parquet["height_cells"], parquet["count"]) != (12, 13, 156):
            raise ValueError("Parquet room dimensions and count do not match fixed plan")
        room_width_m = _to_int(parquet["width_cells"]) * CELL_M
        room_height_m = _to_int(parquet["height_cells"]) * CELL_M
        board_width, board_length = (
            Fraction(value) for value in cast(list[str], parquet["board_m"])
        )
        if room_width_m % board_length or room_height_m % board_width:
            raise ValueError("Parquet dimensions do not tile in the displayed orientation")
        if _to_int(room_width_m / board_length) * _to_int(room_height_m / board_width) != _to_int(
            parquet["count"]
        ):
            raise ValueError("Parquet placement count differs from exact row/column layout")
        if not set(cast(Mapping[str, object], c["internet"])):
            raise ValueError("Internet tariff table missing")

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None:
        self.validate_scenario(scenario)
        if (
            question.scenario_seed != scenario.seed
            or question.position != FAMILY_POSITION[question.family_id]
        ):
            raise ValueError("Question is detached from scenario seed or registered position")
        # Re-parse the visible numbers/model and recompute independently.
        model = question.math_model
        if question.position == 1:
            labels = cast(Mapping[str, int], model["labels"])
            if labels != scenario.context["room_labels"]:
                raise ValueError("Visible room number map differs from the immutable plan")
            expected = "".join(str(labels[key]) for key in cast(list[str], model["rooms_in_order"]))
            if expected != question.canonical_answer or len(set(expected)) != 4:
                raise ValueError("Room matching answer/order does not match visible label model")
            condition = question.condition.casefold()
            if (
                "кладовая имеет двери в коридор и санузел" not in condition
                or "самое большое помещение" not in condition
            ):
                raise ValueError("Room identity clues do not match the fixed plan")
        elif question.position == 2 and question.family_id == "FLAT-02-TILE-PACK":
            shown_pack = re.search(r"В упаковке (\d+) плиток", question.condition)
            if shown_pack is None or _to_int(shown_pack.group(1)) != _to_int(model["pack"]):
                raise ValueError("Visible tile condition lost pack count")
            if "0,4×0,4 м" not in question.condition:
                raise ValueError("Tile dimensions differ from the exact 0.4 m grid")
            if _to_int(question.canonical_answer) != (
                _to_int(model["count"]) + _to_int(model["pack"]) - 1
            ) // _to_int(model["pack"]):
                raise ValueError("Tile packages must round up")
            if (
                _to_int(model["count"]) != _room_area_cells("bathroom")
                or _to_int(model["tile_cells"]) != 1
            ):
                raise ValueError("Tile dimensions do not tile the visible bathroom")
        elif question.position == 2:
            if "4,8×5,2" not in question.condition or "0,2×0,8" not in question.condition:
                raise ValueError("Visible parquet room/board dimensions changed")
            if (
                _to_int(model["width_cells"]) != 12
                or _to_int(model["height_cells"]) != 13
                or cast(tuple[str, ...], model["board_m"]) != ("0.2", "0.8")
            ):
                raise ValueError("Parquet orientation or room outline differs from the fixed plan")
            if Fraction("4.8") / Fraction("0.8") != 6 or Fraction("5.2") / Fraction("0.2") != 26:
                raise ValueError("Visible board orientation does not form an exact rectangle")
            if _to_int(model["count"]) != 156 or _to_int(model["count"]) != _to_int(
                model["width_cells"]
            ) * _to_int(model["height_cells"]):
                raise ValueError("Parquet board count does not match room grid")
            if question.canonical_answer != str(
                (_to_int(model["count"]) + _to_int(model["pack"]) - 1) // _to_int(model["pack"])
            ):
                raise ValueError("Parquet packages must round up after exact placement")
        elif question.position == 3:
            room = str(model["room"])
            if _to_int(model["area_cells"]) != _room_area_cells(room):
                raise ValueError("Area model differs from exact visible room footprint")
            exact = Fraction(_to_int(model["area_cells"])) * Fraction(16, 100)
            if (
                _decimal(exact) != question.canonical_answer
                or ROOM_NAMES[room] not in question.condition
                or "0,4 м" not in question.condition
            ):
                raise ValueError("Area answer or visible room name mismatches plan")
        elif question.position == 4:
            base, delta = _to_int(model["base_cells"]), _to_int(model["delta_cells"])
            if (base, delta) != (
                _room_area_cells("pantry"),
                _room_area_cells("bathroom") - _room_area_cells("pantry"),
            ):
                raise ValueError("Percentage areas differ from the two visible room footprints")
            shown = re.search(
                r"равна (\d+) клеткам, а площадь санузла на (\d+) клеток больше", question.condition
            )
            if shown is None or tuple(map(int, shown.groups())) != (base, delta):
                raise ValueError("Visible percentage numbers differ from room geometry")
            if 100 * delta % base or str(100 * delta // base) != question.canonical_answer:
                raise ValueError("Percent answer is not exact or denominator is wrong")
            if (
                "кладовой" not in question.condition
                or "больше площади кладовой" not in question.condition
            ):
                raise ValueError("Visible percentage comparison denominator is ambiguous")
        elif question.family_id == "FLAT-05-WASHER-MIN":
            models = cast(list[dict[str, object]], model["models"])
            eligible = [
                m
                for m in models
                if m["type"] == "фронтальная"
                and _to_int(m["capacity"]) >= 7
                and _to_int(m["height"]) <= 85
            ]
            costs = [
                _to_int(m["price"])
                + _to_int(m["install"])
                + _to_int(m["price"]) * _to_int(m["delivery_pct"]) // 100
                for m in eligible
            ]
            if not 6 <= len(models) <= 10 or "фронтальная машина" not in question.condition:
                raise ValueError("Washer table or requested load type is outside validated bounds")
            if costs.count(min(costs)) != 1 or question.canonical_answer != str(min(costs)):
                raise ValueError("Equipment constraints/costs must have a unique exact minimum")
            expected_rows = "; ".join(
                f"{m['model']}: {m['type']}, загрузка {m['capacity']} кг, высота {m['height']} см, "
                f"цена {m['price']} руб., установка {m['install']} руб., "
                f"доставка {m['delivery_pct']}%"
                for m in models
            )
            expected_condition = (
                "Нужна фронтальная машина загрузкой не менее 7 кг и высотой не более 85 см. "
                f"Сравните модели с учётом цены, установки и доставки: {expected_rows}. "
                "Найдите минимальную полную стоимость."
            )
            if question.condition != expected_condition:
                raise ValueError("Visible equipment table differs from its model")
        else:
            plans = cast(list[dict[str, object]], model["plans"])
            tariff_costs = [
                _to_int(p["fee"])
                + max(
                    0,
                    _to_int(model["traffic_mb"]) - _to_int(p["included_mb"] or model["traffic_mb"]),
                )
                * Fraction(str(p["overage"]))
                for p in plans
            ]
            if (
                any(cost.denominator != 1 for cost in tariff_costs)
                or str(min(tariff_costs)) != question.canonical_answer
                or tariff_costs.count(min(tariff_costs)) != 1
            ):
                raise ValueError("Tariff table must have exact costs and unique optimum")
            if any(str(p["fee"]) not in question.condition for p in plans):
                raise ValueError("Rendered tariff condition omits a table fee")
            expected_rows = "; ".join(
                f"{p['name']}: абонплата {p['fee']} руб., включено "
                f"{p['included_mb'] or 'безлимит'} МБ, сверх лимита {p['overage']} руб./МБ"
                for p in plans
            )
            expected_condition = (
                f"За месяц использовано {_to_int(model['traffic_mb'])} МБ. "
                f"Выберите тариф с наименьшей стоимостью: {expected_rows}. "
                "Сколько рублей нужно заплатить?"
            )
            if question.condition != expected_condition:
                raise ValueError("Visible tariff table differs from its model")
        if len(question.hints) < 2 or len(question.solution_steps) < 2:
            raise ValueError("Question requires two hints and checked solution steps")
        if not rendered.assets or not any(a.content_type == "image/png" for a in rendered.assets):
            raise ValueError("Shared apartment plan image is required")

    def validate_bundle(
        self,
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        rendered: RenderedScenario,
    ) -> None:
        if tuple(q.position for q in questions) != (1, 2, 3, 4, 5) or any(
            q.scenario_seed != scenario.seed for q in questions
        ):
            raise ValueError(
                "Bundle must be five ordered questions from one unchanged apartment plan"
            )
        for question in questions:
            self.validate_question(scenario, question, rendered)
        # Independent graph/area predicates distinguish the requested rooms.
        graph = [tuple(edge) for edge in cast(Any, scenario.context["door_graph"])]
        degree = {room: sum(room in edge for edge in graph) for room in ROOM_PARTS}
        if degree["bathroom"] != 1 or set(edge for edge in graph if "pantry" in edge) != {
            ("hall", "pantry"),
            ("pantry", "bathroom"),
        }:
            raise ValueError("Room door clues do not uniquely identify bathroom and pantry")
        if ("bedroom", "loggia_1") not in graph or _room_area_cells("living") != max(
            _room_area_cells(room) for room in ROOM_PARTS
        ):
            raise ValueError(
                "Room balcony/largest-area clues do not identify bedroom and living room"
            )


def build_adapter() -> StoryAdapter:
    """Return the FLAT candidate adapter. All source families remain disabled."""
    policy = _NumericPolicy()
    registrations = tuple(
        FamilyRegistration(
            family,
            position,
            FamilyStatus.ENABLED_CANDIDATE,
            policy.policy_id,
            policy.version,
            enabled=False,
            source_ids=FAMILY_SOURCES[family],
        )
        for family, position in FAMILY_POSITION.items()
    ) + (
        FamilyRegistration(
            "FLAT-04-COMPOSITE-PERCENT",
            4,
            FamilyStatus.ENABLED_CANDIDATE,
            policy.policy_id,
            policy.version,
            enabled=False,
            source_ids=("409306",),
        ),
        FamilyRegistration(
            "FLAT-ALT-TOPOLOGY",
            1,
            FamilyStatus.RESEARCH_ONLY,
            policy.policy_id,
            policy.version,
            enabled=False,
            source_ids=(),
        ),
        FamilyRegistration(
            "FLAT-02-CUTTING-WASTE",
            2,
            FamilyStatus.BLOCKED,
            policy.policy_id,
            policy.version,
            enabled=False,
            source_ids=(),
        ),
    )
    return cast(
        StoryAdapter,
        type(
            "FlatAdapter",
            (),
            {
                "story_code": "FLAT",
                "generator": _Generator(),
                "question_builder": _QuestionBuilder(),
                "independent_oracle": _Oracle(),
                "renderer": _Renderer(),
                "answer_policies": {(policy.policy_id, policy.version): policy},
                "family_registry": registrations,
            },
        )(),
    )


__all__ = ["build_adapter"]
