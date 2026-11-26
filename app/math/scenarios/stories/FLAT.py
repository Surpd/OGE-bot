"""Deterministic, fail-closed apartment-plan adapter for OGE tasks 1–5.

The geometry uses an integer lattice with an exact metric scale. PNG and SVG are rendered
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

LEGACY_VERSION = "flat-grid-1.0.0"
PREVIOUS_VERSION = "flat-grid-2.1.0"
FIXED_VERSION = "flat-grid-2.2.0"
GENERATOR_VERSION = "flat-grid-3.0.0"
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
    "loggia_1": "левая лоджия",
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
WINDOW_MARKS: tuple[tuple[int, int, str], ...] = ((10, 0, "h"), (0, 16, "v"))
# Frozen geometry and symbols retain byte-for-byte restoration of v1 assets.
LEGACY_ROOM_PARTS, LEGACY_DOOR_MARKS, LEGACY_WINDOW_MARKS = ROOM_PARTS, DOOR_MARKS, WINDOW_MARKS
# Reconstructed from source 424898/get_file?id=90064, on its original grid.
ROOM_PARTS = {
    "bedroom": ((22, 4, 33, 13),),
    "kitchen": ((0, 3, 10, 12),),
    "living": ((10, 0, 22, 13),),
    "hall": ((5, 13, 29, 18), (5, 12, 10, 13)),
    "pantry": ((29, 13, 33, 18),),
    "bathroom": ((0, 12, 5, 18),),
    "loggia_1": ((0, 0, 10, 3),),
    "loggia_2": ((22, 0, 33, 4),),
}
ROOM_NAMES = {**ROOM_NAMES, "kitchen": "кухня", "loggia_1": "меньшая лоджия"}
DOORS = (
    ("living", "kitchen"),
    ("hall", "kitchen"),
    ("hall", "bedroom"),
    ("hall", "living"),
    ("hall", "pantry"),
    ("hall", "bathroom"),
    ("kitchen", "loggia_1"),
    ("bedroom", "loggia_2"),
)
DOOR_MARKS = (
    (10, 6, "v"),
    (7, 12, "h"),
    (25, 13, "h"),
    (13, 13, "h"),
    (29, 16, "v"),
    (5, 15, "v"),
    (6, 3, "h"),
    (25, 4, "h"),
)
WINDOW_MARKS = ((5, 0, "h"), (16, 0, "h"), (27, 0, "h"), (30, 4, "h"), (3, 3, "h"))


def plan_symbols(
    version: str,
    context: Mapping[str, JsonValue] | None = None,
) -> tuple[
    dict[str, tuple[tuple[int, int, int, int], ...]],
    tuple[tuple[int, int, str], ...],
    tuple[tuple[int, int, str], ...],
]:
    if version == LEGACY_VERSION:
        return LEGACY_ROOM_PARTS, LEGACY_DOOR_MARKS, LEGACY_WINDOW_MARKS
    if version in (PREVIOUS_VERSION, FIXED_VERSION, "flat-grid-2.0.0"):
        return ROOM_PARTS, DOOR_MARKS, WINDOW_MARKS
    if version != GENERATOR_VERSION or context is None:
        raise ValueError("Unsupported FLAT geometry version")

    # Use the authored room order even when a JSONB roundtrip reorders keys.
    stored = cast(Mapping[str, tuple[tuple[int, int, int, int], ...]], context["room_parts"])
    parts = {room: stored[room] for room in ROOM_PARTS}
    _, kitchen_top, kitchen_right, kitchen_bottom = parts["kitchen"][0]
    _, _, living_right, living_bottom = parts["living"][0]
    _, bedroom_top, width, _ = parts["bedroom"][0]
    bath_right, _, pantry_left, bottom = parts["hall"][0]
    doors = (
        (kitchen_right, (kitchen_top + kitchen_bottom) // 2 - 1, "v"),
        ((bath_right + kitchen_right) // 2, kitchen_bottom, "h"),
        (living_right + 3, living_bottom, "h"),
        (kitchen_right + 3, living_bottom, "h"),
        (pantry_left, bottom - 2, "v"),
        (bath_right, living_bottom + 2, "v"),
        (kitchen_right - 4, kitchen_top, "h"),
        (living_right + 3, bedroom_top, "h"),
    )
    windows = (
        (kitchen_right // 2, 0, "h"),
        (kitchen_right + 6, 0, "h"),
        (living_right + 5, 0, "h"),
        (width - 3, bedroom_top, "h"),
        (3, kitchen_top, "h"),
    )
    return parts, doors, windows


def plan_annotations(
    version: str,
    geometry: Mapping[str, tuple[tuple[int, int, int, int], ...]],
) -> tuple[tuple[int, int, int] | None, tuple[int, int]]:
    if version == LEGACY_VERSION:
        return None, (7, 19)
    hall_left, hall_top, _, hall_bottom = geometry["hall"][0]
    return (hall_left, hall_top, geometry["kitchen"][0][2]), (hall_left + 5, hall_bottom)


# Exact integer percentage and practical dimensions on the shared hall wall.
_BATH_PANTRY_DIMENSIONS = tuple(
    (bath_width, pantry_width, hall_depth)
    for bath_width in range(4, 8)
    for pantry_width in range(3, 7)
    for hall_depth in range(4, 9)
    if 0
    < 100 * (bath_width * (hall_depth + 1) - pantry_width * hall_depth)
    <= 150 * pantry_width * hall_depth
    and 100 * bath_width * (hall_depth + 1) % (pantry_width * hall_depth) == 0
)


def _variable_parts(rng: Random) -> dict[str, tuple[tuple[int, int, int, int], ...]]:
    bath_width, pantry_width, hall_depth = rng.choice(_BATH_PANTRY_DIMENSIONS)
    kitchen_right = rng.randint(max(9, bath_width + 3), 12)
    living_width = rng.choice((10, 12, 14) if kitchen_right <= 10 else (12, 14))
    living_right = kitchen_right + living_width
    width = living_right + rng.randint(10, min(12, living_width))
    pantry_left = width - pantry_width
    hall_cells = (pantry_left - bath_width) * hall_depth + kitchen_right - bath_width
    min_living_depth = hall_cells // living_width + 1
    hall_top = rng.randint(max(12, min_living_depth), max(16, min_living_depth))
    bottom = hall_top + hall_depth
    kitchen_top = rng.choice((2, 3))
    bedroom_top = rng.choice((4, 5))
    return {
        "bedroom": ((living_right, bedroom_top, width, hall_top),),
        "kitchen": ((0, kitchen_top, kitchen_right, hall_top - 1),),
        "living": ((kitchen_right, 0, living_right, hall_top),),
        "hall": (
            (bath_width, hall_top, pantry_left, bottom),
            (bath_width, hall_top - 1, kitchen_right, hall_top),
        ),
        "pantry": ((pantry_left, hall_top, width, bottom),),
        "bathroom": ((0, hall_top - 1, bath_width, bottom),),
        "loggia_1": ((0, 0, kitchen_right, kitchen_top),),
        "loggia_2": ((living_right, 0, width, bedroom_top),),
    }


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


def _room_area_cells(
    parts: Mapping[str, tuple[tuple[int, int, int, int], ...]],
    room: str,
) -> int:
    return sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in parts[room])


def _rect_dimensions(
    parts: Mapping[str, tuple[tuple[int, int, int, int], ...]],
    room: str,
) -> tuple[int, int]:
    ((x1, y1, x2, y2),) = parts[room]
    return x2 - x1, y2 - y1


def _cell_m(context: Mapping[str, object]) -> Fraction:
    return Fraction(str(context["grid_cell_m"]))


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
        source = seed == SOURCE_VECTOR_SEED
        parts = ROOM_PARTS if source else _variable_parts(rng)
        cell_m = CELL_M if source else rng.choice((Fraction(2, 5), Fraction(1, 2)))
        width, height = _rect_dimensions(parts, "living")
        labels = list(range(1, 9))
        rng.shuffle(labels)
        room_labels = dict(zip(ROOM_PARTS, labels, strict=True))
        if seed == SOURCE_VECTOR_SEED:
            room_labels = {
                "bathroom": 1,
                "pantry": 3,
                "bedroom": 4,
                "living": 6,
                "kitchen": 7,
                "hall": 2,
                "loggia_1": 8,
                "loggia_2": 5,
            }
        room_cells = {name: _room_area_cells(parts, name) for name in parts}
        tile_pack = rng.choice((4, 5, 6, 8, 10, 12, 15, 18, 20))
        parquet_pack = 14 if source else rng.choice((8, 10, 12, 14, 16, 18, 20))
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
        traffic = 1000
        plans: list[dict[str, int | str | None]] = [
            {"name": "Базовый", "included_mb": 600, "fee": 650, "overage": "2"},
            {"name": "Оптимальный", "included_mb": 900, "fee": 820, "overage": "1.5"},
            {"name": "Безлимитный", "included_mb": None, "fee": 950, "overage": "0"},
        ]
        if not source:
            # The two eligible models are drawn from disjoint total-cost bands.
            # Either row can win, even though list order stays stable.
            low, high = ((22000, 26000), (30500, 34500))
            eligible_bands = iter(rng.sample((low, high), 2))
            for model in washer_models:
                if model["type"] == "вертикальная":
                    lower, upper = next(eligible_bands)
                else:
                    lower, upper = (23000, 36000)
                model["price"] = rng.randrange(lower, upper, 100)
                model["install"] = rng.randrange(0, 1501, 100)
                model["delivery_pct"] = rng.choice((0, 5, 10))
                model["capacity"] = rng.randint(6, 9)
            traffic = rng.randrange(500, 1301, 50)
            # Distinct residues modulo 5 distinguish totals. Overage increments
            # are multiples of 25 because traffic and limits are multiples of 50.
            plans[0].update(
                included_mb=rng.randrange(500, 751, 50),
                fee=rng.randrange(500, 651, 5),
                overage=rng.choice(("1.5", "2")),
            )
            plans[1].update(
                included_mb=rng.randrange(800, 1051, 50),
                fee=rng.randrange(701, 852, 5),
                overage=rng.choice(("1", "1.5")),
            )
            plans[2]["fee"] = rng.randrange(902, 1053, 5)
        context: dict[str, Any] = {
            "grid_cell_m": _decimal(cell_m).replace(",", "."),
            "topology_id": "flat_2room_8label_v3",
            "room_parts": {key: [list(rect) for rect in value] for key, value in parts.items()},
            "room_labels": room_labels,
            "door_graph": [list(pair) for pair in DOORS],
            "tile": {"room": "bathroom", "tile_cells": 1, "pack": tile_pack, "count": tile_cells},
            "parquet": {
                "room": "living",
                "width_cells": width,
                "height_cells": height,
                "board_m": [
                    _decimal(cell_m / 2).replace(",", "."),
                    _decimal(cell_m * 2).replace(",", "."),
                ],
                "pack": parquet_pack,
                "count": width * height,
            },
            "area_room": area_room,
            "percent": {"base": percent_base, "delta": percent_delta},
            "washers": washer_models,
            "internet": {"traffic_mb": traffic, "plans": plans},
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
        return self.build_question_for_family(scenario, position, family)

    def build_question_for_family(
        self, scenario: ScenarioDraft, position: int, family: str
    ) -> QuestionDraft:
        if FAMILY_POSITION.get(family) != position:
            raise ValueError("FLAT family does not belong to this question position")
        c = cast(Mapping[str, Any], scenario.context)
        labels = cast(Mapping[str, int], c["room_labels"])
        parts, _, _ = plan_symbols(scenario.generator_version, scenario.context)
        cell_m = _cell_m(c)
        solution: tuple[str, ...]
        if position == 1:
            rooms = ("bathroom", "pantry", "bedroom", "living")
            answer = "".join(str(labels[name]) for name in rooms)
            condition = (
                "Определите по плану номера помещений. Запишите номера в порядке: "
                "санузел, кладовая, спальня, гостиная."
            )
            model: dict[str, object] = {
                "rooms_in_order": list(rooms),
                "labels": dict(labels),
                "answer_grid": {
                    "columns": ["Санузел", "Кладовая", "Спальня", "Гостиная"],
                    "header": "Помещение",
                    "row": "Цифра на плане",
                },
            }
            solution = (
                "Определите номера помещений по подписям на плане.",
                f"В заданном порядке получаем {answer}.",
            )
        elif position == 2 and family == "FLAT-02-TILE-PACK":
            tile = cast(Mapping[str, object], c["tile"])
            count, pack = _to_int(tile["count"]), _to_int(tile["pack"])
            answer = str((count + pack - 1) // pack)
            condition = (
                f"Пол санузла выложен плитками {_decimal(cell_m)}×{_decimal(cell_m)} м. "
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
            width, height = _rect_dimensions(parts, "living")
            board_width, board_length = cast(tuple[str, str], parquet["board_m"])
            room_width_m, room_height_m = width * cell_m, height * cell_m
            along = room_width_m / Fraction(board_length)
            across = room_height_m / Fraction(board_width)
            condition = (
                "Пол гостиной покрывают паркетными досками "
                f"{_decimal(Fraction(board_width))}×{_decimal(Fraction(board_length))} м "
                f"без распила. В упаковке {pack} досок. Сколько упаковок потребуется?"
            )
            model = dict(parquet)
            solution = (
                f"Гостиная на плане: {width}×{height} клеток, "
                f"то есть {_decimal(room_width_m)}×{_decimal(room_height_m)} м.",
                f"При укладке без распила помещается {along}×{across} = {count} досок.",
                f"{count} : {pack} с округлением вверх = {answer} упаковок.",
            )
        elif position == 3:
            room = "loggia_1"
            width, height = _rect_dimensions(parts, room)
            other_width, other_height = _rect_dimensions(parts, "loggia_2")
            cells, other_cells = width * height, other_width * other_height
            cell_area = _decimal(cell_m**2)
            answer = _decimal(cells * cell_m**2)
            condition = (
                "Найдите площадь меньшей лоджии, если сторона клетки плана "
                f"равна {_decimal(cell_m)} м. Ответ дайте в квадратных метрах."
            )
            model = {"room": room, "area_cells": cells, "cell_area": cell_area.replace(",", ".")}
            solution = (
                f"Число клеток на лоджиях: {width}×{height} = {cells} "
                f"и {other_width}×{other_height} = {other_cells}.",
                f"{cells} · {cell_area} = {answer} м².",
            )
        elif position == 4 and family == "FLAT-04-RECT-PERCENT":
            pct = cast(Mapping[str, int], c["percent"])
            base, delta = pct["base"], pct["delta"]
            answer = str(100 * delta // base)
            condition = (
                "По плану определите, на сколько процентов площадь санузла больше площади кладовой?"
            )
            model = {"base_cells": base, "delta_cells": delta, "denominator": "кладовая"}
            solution = (
                f"Кладовая занимает {base} клеток, санузел — {base + delta}. "
                f"Их разность — {delta}.",
                f"{delta}/{base} · 100% = {answer}%.",
            )
        elif position == 5 and family == "FLAT-05-WASHER-MIN":
            models = cast(list[dict[str, object]], c["washers"])
            eligible = [
                m for m in models if m["type"] == "вертикальная" and _to_int(m["capacity"]) >= 6
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
                "Нужна машина с вертикальной загрузкой вместимостью не менее 6 кг. "
                f"Сравните модели с учётом цены, установки и доставки: {rows}. "
                "Доставка указана в процентах от цены машины. Найдите минимальную полную стоимость."
            )
            model = {
                "models": models,
                "eligible": [m["model"] for m in eligible],
                "costs": costs,
                "winner": eligible[winner]["model"],
            }
            solution = (
                (
                    "После ограничений подходят модели "
                    f"{', '.join(cast(list[str], model['eligible']))}.",
                )
                + tuple(
                    f"{m['model']}: {m['price']} + {m['install']} + "
                    f"{m['price']} · {m['delivery_pct']} / 100 = {cost} руб."
                    for m, cost in zip(eligible, costs, strict=True)
                )
                + (f"Минимальная полная стоимость — {answer} руб.",)
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
                "Санузел находится слева от входа, а кладовая — в противоположном конце коридора.",
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
                "Оставьте модели с вертикальной загрузкой и вместимостью не менее 6 кг.",
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
            scenario.generator_version,
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
    @staticmethod
    def _layout(
        version: str,
        geometry: Mapping[str, tuple[tuple[int, int, int, int], ...]],
    ) -> tuple[int, int, int]:
        if version == LEGACY_VERSION:
            return 36, 150, 210
        if version == GENERATOR_VERSION:
            width = geometry["bedroom"][0][2]
            height = geometry["hall"][0][3]
            return min(29, 1000 // width, 750 // height), 60, 155
        return 29, 65, 170

    def _svg(self, scenario: ScenarioDraft) -> bytes:
        c = scenario.context
        labels = cast(Mapping[str, int], c["room_labels"])
        geometry, doors, windows = plan_symbols(scenario.generator_version, c)
        scale, ox, oy = self._layout(scenario.generator_version, geometry)
        seam, entry = plan_annotations(scenario.generator_version, geometry)
        cell_label = (
            _decimal(_cell_m(c)) if scenario.generator_version == GENERATOR_VERSION else "0,4"
        )
        width, height = 1120, 1000
        parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            '<text x="40" y="48" font-size="26" font-family="sans-serif">'
            f"План квартиры · клетка {cell_label} м</text>",
            '<text x="40" y="78" font-size="17" font-family="sans-serif">'
            "Синие проёмы — двери · бирюзовые — окна · вход отмечен красным</text>",
        ]
        for room, rectangles in geometry.items():
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
        if seam is not None:
            left, y, right = seam
            parts.append(
                f'<path d="M {ox + left * scale} {oy + y * scale} '
                f'H {ox + right * scale}" stroke="#dce4eb" stroke-width="4"/>'
            )
        # Door gaps are symbolized with short colored segments on fixed shared walls.
        for x, y, orientation in doors:
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
        for x, y, orientation in windows:
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
        entry_x, entry_y = ox + entry[0] * scale, oy + entry[1] * scale
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
        geometry, doors, windows = plan_symbols(scenario.generator_version, c)
        scale, ox, oy = self._layout(scenario.generator_version, geometry)
        seam, entry = plan_annotations(scenario.generator_version, geometry)
        cell_label = (
            _decimal(_cell_m(c)) if scenario.generator_version == GENERATOR_VERSION else "0,4"
        )
        image = Image.new("RGB", (1120, 1000), "white")
        draw = ImageDraw.Draw(image)
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except OSError:
            font = ImageFont.load_default()
        draw.text((40, 30), f"План квартиры · клетка {cell_label} м", fill="#202b38", font=font)
        draw.text(
            (40, 62),
            f"Сторона клетки {cell_label} м · синие проёмы — двери · "
            "бирюзовые — окна · вход красный",
            fill="#202b38",
            font=font,
        )
        for room, rectangles in geometry.items():
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
        if seam is not None:
            left, y, right = seam
            draw.line(
                (ox + left * scale, oy + y * scale, ox + right * scale, oy + y * scale),
                fill="#dce4eb",
                width=4,
            )
        for x, y, orientation in doors:
            px, py = ox + x * scale, oy + y * scale
            bounds = (
                (px - 12, py, px + 12, py) if orientation == "h" else (px, py - 12, px, py + 12)
            )
            draw.line(bounds, fill="white", width=8)
            draw.line(bounds, fill="#1463a5", width=3)
        for x, y, orientation in windows:
            px, py = ox + x * scale, oy + y * scale
            bounds = (
                (px - 30, py, px + 30, py) if orientation == "h" else (px, py - 30, px, py + 30)
            )
            draw.line(bounds, fill="white", width=9)
            draw.line(bounds, fill="#008b8b", width=4)
        entry_x, entry_y = ox + entry[0] * scale, oy + entry[1] * scale
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
        cell_label = _decimal(_cell_m(scenario.context))
        context = (
            f"План квартиры: восемь помещений с цифровыми метками; сторона клетки {cell_label} м. "
            "Коридор у входа; санузел слева от входа, кладовая в противоположном конце. "
            "Рядом с кладовой спальня с лоджией. Гостиная соединяет коридор и кухню; "
            "кухня выходит на другую лоджию. Гостиная — самое большое помещение. "
            "Обе лоджии расположены в верхних углах плана. "
            "Синие штрихи обозначают двери, бирюзовые — окна, красный — вход."
        )
        return RenderedScenario(context, assets)

    def restore_asset(self, snapshot: ScenarioSnapshot, asset: ScenarioAssetRef) -> bytes:
        if snapshot.story_code != "FLAT" or snapshot.generator_version not in (
            LEGACY_VERSION,
            "flat-grid-2.0.0",
            PREVIOUS_VERSION,
            FIXED_VERSION,
            GENERATOR_VERSION,
        ):
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
        parts, door_marks, windows = plan_symbols(scenario.generator_version, scenario.context)
        cell_m = _cell_m(c)
        if (
            set(labels) != set(ROOM_PARTS)
            or any(type(label) is not int for label in labels.values())
            or set(labels.values()) != set(range(1, 9))
        ):
            raise ValueError("Room labels must be a bijection over the 8-room plan")
        topology = (
            "flat_2room_8label_v3"
            if scenario.generator_version == GENERATOR_VERSION
            else "flat_2room_8label_v2"
        )
        if cell_m not in (Fraction(2, 5), Fraction(1, 2)) or c["topology_id"] != topology:
            raise ValueError("Plan scale or topology is outside the validated ranges")
        if c["door_graph"] != DOORS:
            raise ValueError("Door graph differs from the visible plan topology")
        if set(c["room_parts"]) != set(parts) or c["room_parts"] != parts:
            raise ValueError("Stored room polygons differ from the rendered plan")

        occupied: dict[tuple[int, int], str] = {}
        for room, rectangles in parts.items():
            if len(rectangles) != (2 if room == "hall" else 1):
                raise ValueError("Unexpected room polygon structure")
            for x1, y1, x2, y2 in rectangles:
                if not (0 <= x1 < x2 <= 38 and 0 <= y1 < y2 <= 31):
                    raise ValueError("Invalid room polygon bounds")
                for x in range(x1, x2):
                    for y in range(y1, y2):
                        if (x, y) in occupied:
                            raise ValueError("Room polygons overlap on the integer grid")
                        occupied[x, y] = room
        width, height = max(x for x, _ in occupied) + 1, max(y for _, y in occupied) + 1
        if set(occupied) != {(x, y) for x in range(width) for y in range(height)}:
            raise ValueError("Room polygons leave gaps in the apartment outline")

        def sides(x: int, y: int, orientation: str) -> frozenset[str | None]:
            a = (x - 1, y) if orientation == "v" else (x, y - 1)
            return frozenset((occupied.get(a), occupied.get((x, y))))

        for (x, y, orientation), edge in zip(door_marks, DOORS, strict=True):
            before = (x, y - 1) if orientation == "v" else (x - 1, y)
            if sides(x, y, orientation) != set(edge) or sides(*before, orientation) != set(edge):
                raise ValueError("Visible door gap does not match the language door graph")
        for x, y, orientation in windows:
            if len(sides(x, y, orientation)) != 2:
                raise ValueError("Window must lie on a wall")
        seam, (entry_x, entry_y) = plan_annotations(scenario.generator_version, parts)
        if sides(entry_x, entry_y, "h") != {"hall", None} or seam is None:
            raise ValueError("Entrance must lead to the hall from the exterior")
        left, y, right = seam
        if left >= right or any(sides(x, y, "h") != {"hall"} for x in range(left, right)):
            raise ValueError("Hall segments must meet along the shared grid line")
        if occupied[0, 0] != "loggia_1" or occupied[width - 1, 0] != "loggia_2":
            raise ValueError("The room matching clues require loggias in the upper corners")
        if not (
            sides(parts["pantry"][0][0], parts["pantry"][0][1], "h") == {"bedroom", "pantry"}
            and parts["bathroom"][0][2] < entry_x < parts["pantry"][0][0]
        ):
            raise ValueError("Room locations contradict the entrance clues")

        areas = {room: sum(value == room for value in occupied.values()) for room in parts}
        if areas["living"] <= max(area for room, area in areas.items() if room != "living"):
            raise ValueError("The living room must be the largest room")
        if c["area_room"] != "loggia_1" or areas["loggia_1"] >= areas["loggia_2"]:
            raise ValueError("The smaller loggia must be uniquely determined")
        base = areas["pantry"]
        delta = areas["bathroom"] - base
        if delta <= 0 or 100 * delta % base or c["percent"] != {"base": base, "delta": delta}:
            raise ValueError("Bathroom and pantry must give an exact positive percentage")
        tile = c["tile"]
        if (tile["room"], tile["tile_cells"], tile["count"]) != ("bathroom", 1, areas["bathroom"]):
            raise ValueError("Tile count does not match exact room lattice")
        self._check_pack(tile["pack"])

        parquet = c["parquet"]
        living_cells = [(x, y) for (x, y), room in occupied.items() if room == "living"]
        width = len({x for x, _ in living_cells})
        height = len({y for _, y in living_cells})
        if (parquet["room"], parquet["width_cells"], parquet["height_cells"]) != (
            "living",
            width,
            height,
        ):
            raise ValueError("Parquet room dimensions do not match the plan")
        board_width, board_length = map(Fraction, parquet["board_m"])
        room_width, room_height = width * cell_m, height * cell_m
        if (
            min(board_width, board_length) <= 0
            or room_width % board_length
            or room_height % board_width
        ):
            raise ValueError("Parquet boards do not tile the displayed room without cutting")
        if parquet["count"] != (room_width / board_length) * (room_height / board_width):
            raise ValueError("Parquet count does not match the plan and board dimensions")
        self._check_pack(parquet["pack"])

    @staticmethod
    def _check_pack(pack: object) -> None:
        if not 1 <= _to_int(pack) <= 30:
            raise ValueError("Invalid package size")

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None:
        self.validate_scenario(scenario)
        if (
            question.scenario_seed != scenario.seed
            or question.generator_version != scenario.generator_version
            or question.position != FAMILY_POSITION[question.family_id]
        ):
            raise ValueError("Question is detached from scenario seed or registered position")
        # Check the visible wording against the operands and recompute independently.
        parts, _, _ = plan_symbols(scenario.generator_version, scenario.context)
        cell_m = _cell_m(scenario.context)
        if f"сторона клетки {_decimal(cell_m)} м." not in rendered.shared_context:
            raise ValueError("Shared text scale differs from the plan")
        model = question.math_model
        if question.position == 1:
            labels = cast(Mapping[str, int], model["labels"])
            if labels != scenario.context["room_labels"]:
                raise ValueError("Visible room number map differs from the immutable plan")
            expected = "".join(str(labels[key]) for key in cast(list[str], model["rooms_in_order"]))
            if expected != question.canonical_answer or len(set(expected)) != 4:
                raise ValueError("Room matching answer/order does not match visible label model")
            if model.get("answer_grid") != {
                "columns": ("Санузел", "Кладовая", "Спальня", "Гостиная"),
                "header": "Помещение",
                "row": "Цифра на плане",
            }:
                raise ValueError("Apartment matching grid differs from the requested room order")
            condition = question.condition.casefold()
            if (
                "санузел, кладовая, спальня, гостиная" not in condition
                or "санузел слева от входа" not in rendered.shared_context.casefold()
                or "самое большое помещение" not in rendered.shared_context.casefold()
            ):
                raise ValueError("Room identity clues do not match the fixed plan")
        elif question.position == 2 and question.family_id == "FLAT-02-TILE-PACK":
            tile = cast(Mapping[str, int], scenario.context["tile"])
            pack, count = tile["pack"], tile["count"]
            side = _decimal(cell_m)
            expected = (
                f"Пол санузла выложен плитками {side}×{side} м. "
                f"В упаковке {pack} плиток. Сколько упаковок потребуется? Резка не нужна."
            )
            if (
                question.condition != expected
                or model["room_cells"] != count
                or model["count"] != count
                or model["tile_cells"] != 1
                or model["pack"] != pack
                or _to_int(question.canonical_answer) != -(-count // pack)
            ):
                raise ValueError("Visible tile geometry, packaging or answer differs from the plan")
        elif question.position == 2:
            parquet = cast(Mapping[str, Any], scenario.context["parquet"])
            board = "×".join(_decimal(Fraction(side)) for side in parquet["board_m"])
            expected = (
                f"Пол гостиной покрывают паркетными досками {board} м без распила. "
                f"В упаковке {parquet['pack']} досок. Сколько упаковок потребуется?"
            )
            if (
                question.condition != expected
                or model != parquet
                or _to_int(question.canonical_answer) != -(-parquet["count"] // parquet["pack"])
            ):
                raise ValueError("Parquet geometry, packaging or answer differs from the plan")
        elif question.position == 3:
            width, height = _rect_dimensions(parts, "loggia_1")
            other_width, other_height = _rect_dimensions(parts, "loggia_2")
            cells = width * height
            expected_steps = (
                f"Число клеток на лоджиях: {width}×{height} = {cells} "
                f"и {other_width}×{other_height} = {other_width * other_height}.",
                f"{cells} · {_decimal(cell_m**2)} = {_decimal(cells * cell_m**2)} м².",
            )
            if (
                model["room"] != "loggia_1"
                or model["area_cells"] != cells
                or Fraction(str(model["cell_area"])) != cell_m**2
                or _decimal(cells * cell_m**2) != question.canonical_answer
                or question.condition
                != (
                    "Найдите площадь меньшей лоджии, если сторона клетки плана "
                    f"равна {_decimal(cell_m)} м. Ответ дайте в квадратных метрах."
                )
                or question.solution_steps != expected_steps
            ):
                raise ValueError("Area question or solution differs from the smaller loggia")
        elif question.position == 4:
            base = _room_area_cells(parts, "pantry")
            bathroom = _room_area_cells(parts, "bathroom")
            delta = bathroom - base
            result = Fraction(100 * delta, base)
            expected_steps = (
                f"Кладовая занимает {base} клеток, санузел — {bathroom}. Их разность — {delta}.",
                f"{delta}/{base} · 100% = {result}%.",
            )
            if (
                (model["base_cells"], model["delta_cells"]) != (base, delta)
                or result.denominator != 1
                or str(result) != question.canonical_answer
                or question.condition
                != (
                    "По плану определите, на сколько процентов площадь санузла "
                    "больше площади кладовой?"
                )
                or question.solution_steps != expected_steps
            ):
                raise ValueError("Percentage question or solution differs from the visible rooms")
        elif question.family_id == "FLAT-05-WASHER-MIN":
            models = cast(tuple[Mapping[str, JsonValue], ...], model["models"])
            if models != scenario.context["washers"]:
                raise ValueError("Equipment offers differ from the issued scenario")
            eligible = [
                m for m in models if m["type"] == "вертикальная" and _to_int(m["capacity"]) >= 6
            ]
            costs = [
                Fraction(_to_int(m["price"])) * Fraction(100 + _to_int(m["delivery_pct"]), 100)
                + _to_int(m["install"])
                for m in eligible
            ]
            if (
                not 6 <= len(models) <= 10
                or len(eligible) < 2
                or any(cost.denominator != 1 for cost in costs)
                or costs.count(min(costs)) != 1
                or question.canonical_answer != str(min(costs))
                or model["eligible"] != tuple(m["model"] for m in eligible)
                or model["costs"] != tuple(map(_to_int, costs))
                or model["winner"] != eligible[costs.index(min(costs))]["model"]
            ):
                raise ValueError("Equipment constraints/costs must have a unique exact minimum")
            expected_rows = "; ".join(
                f"{m['model']}: {m['type']}, загрузка {m['capacity']} кг, высота {m['height']} см, "
                f"цена {m['price']} руб., установка {m['install']} руб., "
                f"доставка {m['delivery_pct']}%"
                for m in models
            )
            expected_condition = (
                "Нужна машина с вертикальной загрузкой вместимостью не менее 6 кг. "
                f"Сравните модели с учётом цены, установки и доставки: {expected_rows}. "
                "Доставка указана в процентах от цены машины. Найдите минимальную полную стоимость."
            )
            if question.condition != expected_condition:
                raise ValueError("Visible equipment table differs from its model")
        else:
            plans = cast(tuple[Mapping[str, JsonValue], ...], model["plans"])
            internet = cast(Mapping[str, object], scenario.context["internet"])
            if plans != internet["plans"] or model["traffic_mb"] != internet["traffic_mb"]:
                raise ValueError("Internet offers or traffic differ from the issued scenario")
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
                or model["costs"] != tuple(map(_to_int, tariff_costs))
                or model["winner"] != plans[tariff_costs.index(min(tariff_costs))]["name"]
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
