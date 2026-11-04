"""Fail-closed ROUTE adapter for one coherent four-settlement GRID-4 block.

The source package contains other candidate mechanisms, but only the GRID-4
bundle (F01/F03/F05/F06/F09) is combined here.  The original raster map was not
available for a full visual audit, so registrations intentionally stay disabled.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256
from html import escape
from io import BytesIO
from math import isqrt
from random import Random
from types import MappingProxyType
from typing import cast
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw

from app.math.scenario_engine import (
    AnswerPolicy,
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

STORY_CODE = "ROUTE"
GENERATOR_VERSION = "route-grid4-v1"
COMPATIBILITY_VERSION = "route-grid4-bundle-v1"
POLICY_VERSION = "1"

F01 = "ROUTE-F01-GRID-MATCH"
F03 = "ROUTE-F03-ROAD-SUM"
F05 = "ROUTE-F05-PYTHAGORAS"
F06 = "ROUTE-F06-HIGHWAY-TIME"
F09 = "ROUTE-F09-SHOPPING-MIN"

SOURCES_BY_POSITION: dict[int, tuple[str, ...]] = {
    1: ("408182",),
    2: ("408186",),
    3: ("408188",),
    4: ("408190",),
    5: ("408193",),
}
NAMES = ("Камышевка", "Ясная", "Хомяково", "Луговая")
TRIPLES = ((3, 4, 5), (5, 12, 13), (8, 15, 17), (7, 24, 25), (9, 12, 15))
STORE_COUNT = 4


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("ROUTE scenario values must be integers")
    return value


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("ROUTE scenario data must be an object")
    return cast(Mapping[str, object], value)


def _source_shopping_table() -> dict[str, object]:
    # A synthetic basket witness preserving the archived basket totals.
    # It is not a transcription of the unavailable original table.
    return {
        "products": ["P1", "P2", "P3", "P4", "P5"],
        "quantities": [2, 3, 0, 0, 0],
        "stores": [
            {"id": "S1", "prices": [417, 100, 180, 200, 220]},
            {"id": "S2", "prices": [478, 100, 180, 200, 220]},
            {"id": "S3", "prices": [523, 100, 180, 200, 220]},
            {"id": "S4", "prices": [486, 100, 180, 200, 220]},
        ],
    }


def _generated_shopping_table(rng: Random) -> dict[str, object]:
    active_rows = set(rng.sample(range(5), k=rng.randint(2, 4)))
    quantities = [rng.randint(1, 5) if index in active_rows else 0 for index in range(5)]
    # Build four store price vectors with a unique minimum total by construction.
    base = [rng.randint(15, 250) for _ in range(5)]
    stores: list[dict[str, object]] = []
    for index in range(STORE_COUNT):
        prices = [price if index == 0 else price + rng.randint(10, 120) for price in base]
        total = sum(qty * price for qty, price in zip(quantities, prices, strict=True))
        stores.append({"id": f"S{index + 1}", "prices": prices, "total": total})
    return {
        "products": [f"P{index}" for index in range(1, 6)],
        "quantities": quantities,
        "stores": stores,
    }


def _make_context(seed: int) -> dict[str, JsonValue]:
    rng = Random(seed)
    if seed == 0:
        width, height, scale, speed = 32, 24, 1, 20
        labels = {"A": 2, "B": 1, "C": 3, "D": 4}
        names_by_node = {"A": NAMES[0], "B": NAMES[1], "C": NAMES[2], "D": NAMES[3]}
        shopping = _source_shopping_table()
    else:
        ax, by, _ = rng.choice(TRIPLES)
        scale = rng.choice((1, 2, 4))
        width, height = ax, by
        speed = 20
        digits = rng.sample((1, 2, 3, 4), k=4)
        labels = dict(zip(("A", "B", "C", "D"), digits, strict=True))
        names = rng.sample(NAMES, k=4)
        names_by_node = dict(zip(("A", "B", "C", "D"), names, strict=True))
        shopping = _generated_shopping_table(rng)

    points = {
        "A": [0, 0],
        "B": [width, 0],
        "C": [width, height],
        "D": [0, height],
    }
    edges = [
        {"id": "AB", "from": "A", "to": "B", "type": "highway"},
        {"id": "BC", "from": "B", "to": "C", "type": "highway"},
        {"id": "AC", "from": "A", "to": "C", "type": "dirt"},
        {"id": "DB", "from": "D", "to": "B", "type": "dirt"},
    ]
    return cast(
        dict[str, JsonValue],
        {
            "topology_id": "GRID4_RECTANGLE_ROADS_V1",
            "seed": seed,
            "scale_km_per_cell": scale,
            "nodes": [
                {
                    "id": node_id,
                    "x": xy[0],
                    "y": xy[1],
                    "number": labels[node_id],
                    "name": names_by_node[node_id],
                }
                for node_id, xy in points.items()
            ],
            "edges": edges,
            "highway_route": ["A", "B", "C"],
            "direct_pair": ["A", "C"],
            "highway_speed_kmh": speed,
            "shopping": shopping,
            "visual_audit": "pending_original_raster_audit",
        },
    )


class _RouteGenerator:
    def generate_scenario(self, seed: int) -> ScenarioDraft:
        context = _make_context(seed)
        return ScenarioDraft(
            story_code=STORY_CODE,
            seed=seed,
            generator_version=GENERATOR_VERSION,
            context=context,
            compatibility_matrix_version=COMPATIBILITY_VERSION,
            provenance=tuple(
                f"https://math-oge.sdamgia.ru/problem?id={source}"
                for position in range(1, 6)
                for source in SOURCES_BY_POSITION[position]
            ),
        )


def _node_map(scenario: ScenarioDraft) -> dict[str, Mapping[str, object]]:
    raw_nodes = scenario.context.get("nodes")
    if not isinstance(raw_nodes, tuple | list):
        raise ValueError("ROUTE graph has no nodes")
    return {str(_mapping(node)["id"]): _mapping(node) for node in raw_nodes}


def _length_km(left: Mapping[str, object], right: Mapping[str, object], scale: int) -> int:
    dx = _int(left["x"]) - _int(right["x"])
    dy = _int(left["y"]) - _int(right["y"])
    squared = (dx * dx + dy * dy) * scale * scale
    distance = isqrt(squared)
    if distance * distance != squared:
        raise ValueError("ROUTE distance is not an exact integer kilometre value")
    return distance


def _route_values(scenario: ScenarioDraft) -> dict[str, int]:
    context = scenario.context
    nodes = _node_map(scenario)
    scale = _int(context["scale_km_per_cell"])
    ab = _length_km(nodes["A"], nodes["B"], scale)
    bc = _length_km(nodes["B"], nodes["C"], scale)
    ac = _length_km(nodes["A"], nodes["C"], scale)
    speed = _int(context["highway_speed_kmh"])
    if speed <= 0:
        raise ValueError("ROUTE speed must be positive")
    return {"ab": ab, "bc": bc, "highway": ab + bc, "direct": ac, "speed": speed}


class _RouteQuestionBuilder:
    def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft:
        nodes = _node_map(scenario)
        data = _route_values(scenario)

        def label(node_id: str) -> int:
            return _int(nodes[node_id]["number"])

        def name(node_id: str) -> str:
            return str(nodes[node_id]["name"])

        family, policy, answer, condition, steps, math_model = _question_data(
            scenario, position, nodes, data, label, name
        )
        return QuestionDraft(
            position=position,
            scenario_seed=scenario.seed,
            family_id=family,
            generator_version=GENERATOR_VERSION,
            condition=condition,
            answer_policy_id=policy,
            answer_policy_version=POLICY_VERSION,
            canonical_answer=answer,
            hints=(
                "Найдите нужные пункты на общей схеме.",
                "Составьте выражение в требуемых единицах.",
            ),
            solution_steps=tuple(steps),
            math_model=math_model,
        )


def _question_data(
    scenario: ScenarioDraft,
    position: int,
    nodes: Mapping[str, Mapping[str, object]],
    data: Mapping[str, int],
    label: Callable[[str], int],
    name: Callable[[str], str],
) -> tuple[str, str, str, str, tuple[str, ...], Mapping[str, JsonValue]]:
    if position == 1:
        names = ", ".join(name(node) for node in ("A", "B", "C"))
        return (
            F01,
            "route.code.exact",
            f"{label('A')}{label('B')}{label('C')}",
            (
                "На схеме числами отмечены пункты. Двигаясь по шоссе от западного конца "
                "до поворота, "
                f"а затем до северного конца, вы встретите пункты {names}. Запишите код из чисел "
                "на схеме в указанном порядке."
            ),
            (
                f"Пункты идут в порядке {name('A')} → {name('B')} → {name('C')}.",
                f"Код: {label('A')}{label('B')}{label('C')} .",
            ),
            {
                "ordered_nodes": ("A", "B", "C"),
                "ordered_names": tuple(name(n) for n in ("A", "B", "C")),
            },
        )
    if position == 2:
        return (
            F03,
            "route.integer_km",
            str(data["highway"]),
            (
                f"Найдите длину маршрута по шоссе из пункта {name('A')} в пункт {name('C')} "
                f"через {name('B')}. Ответ дайте в километрах."
            ),
            (
                (
                    f"{name('A')}—{name('B')}: {data['ab']} км; "
                    f"{name('B')}—{name('C')}: {data['bc']} км."
                ),
                f"{data['ab']} + {data['bc']} = {data['highway']} км.",
            ),
            {"route": ("A", "B", "C"), "edge_lengths_km": (data["ab"], data["bc"])},
        )
    if position == 3:
        return (
            F05,
            "route.integer_km",
            str(data["direct"]),
            (
                f"Найдите расстояние по прямой между пунктами {name('A')} и {name('C')}. "
                "Ответ дайте в километрах."
            ),
            (
                f"Катеты равны {data['ab']} км и {data['bc']} км.",
                f"√({data['ab']}² + {data['bc']}²) = {data['direct']} км.",
            ),
            {"endpoints": ("A", "C"), "legs_km": (data["ab"], data["bc"])},
        )
    if position == 4:
        numerator = 60 * data["highway"]
        if numerator % data["speed"]:
            raise ValueError("ROUTE time must be an exact whole number of minutes")
        answer = numerator // data["speed"]
        return (
            F06,
            "route.integer_min",
            str(answer),
            (
                f"Сколько минут потребуется на маршрут по шоссе из пункта {name('A')} в пункт "
                f"{name('C')} через {name('B')} при скорости {data['speed']} км/ч?"
            ),
            (
                f"Длина маршрута: {data['highway']} км.",
                f"60 · {data['highway']} / {data['speed']} = {answer} мин.",
            ),
            {"route": ("A", "B", "C"), "distance_km": data["highway"], "speed_kmh": data["speed"]},
        )
    if position == 5:
        table = _mapping(scenario.context["shopping"])
        stores = cast(list[Mapping[str, object]], table["stores"])
        quantities = cast(list[int], table["quantities"])
        totals = [
            sum(q * p for q, p in zip(quantities, cast(list[int], store["prices"]), strict=True))
            for store in stores
        ]
        answer = min(totals)
        index = totals.index(answer)
        calculation_step_list: list[str] = []
        for store, total in zip(stores, totals, strict=True):
            prices = cast(list[int], store["prices"])
            terms = [
                f"{quantity} · {price}"
                for quantity, price in zip(quantities, prices, strict=True)
                if quantity > 0
            ]
            calculation_step_list.append(f"{' + '.join(terms)} = {total} ₽ ({store['id']}).")
        calculation_steps = tuple(calculation_step_list)
        return (
            F09,
            "route.integer_rub",
            str(answer),
            (
                "В таблице указаны цены за единицу товаров и количества в наборе для "
                "четырёх магазинов. Найдите наименьшую стоимость набора. Ответ дайте в рублях."
            ),
            (*calculation_steps, f"Минимум — {answer} ₽ (магазин {stores[index]['id']})."),
            {
                "basket_quantities": tuple(quantities),
                "store_totals": tuple(totals),
                "target": "minimum_cost",
            },
        )
    raise ValueError("ROUTE position must be from 1 through 5")


def _svg(context: Mapping[str, object]) -> bytes:
    nodes = cast(list[Mapping[str, object]], context["nodes"])
    edges = cast(list[Mapping[str, object]], context["edges"])
    by_id = {str(node["id"]): node for node in nodes}
    scale = _int(context["scale_km_per_cell"])
    width_km = max(_int(node["x"]) for node in nodes)
    height_km = max(_int(node["y"]) for node in nodes)
    factor = min(420 / max(width_km, 1), 250 / max(height_km, 1))
    origin_x, origin_y = 90, 340
    coordinates = {
        node_id: (origin_x + _int(node["x"]) * factor, origin_y - _int(node["y"]) * factor)
        for node_id, node in by_id.items()
    }
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="560" viewBox="0 0 900 560">',
        '<rect width="900" height="560" fill="#fff"/>',
        '<g id="grid" stroke="#e7edf3" stroke-width="1">',
    ]
    for cell_x in range(width_km + 1):
        grid_x = origin_x + cell_x * factor
        parts.append(f'<path d="M{grid_x:.2f} 55V390"/>')
    for cell_y in range(height_km + 1):
        grid_y = origin_y - cell_y * factor
        parts.append(f'<path d="M40 {grid_y:.2f}H510"/>')
    parts.extend(["</g>", f'<text x="540" y="70" font-size="18">1 клетка = {scale} км</text>'])
    for edge in edges:
        left, right = coordinates[str(edge["from"])], coordinates[str(edge["to"])]
        road_type = str(edge["type"])
        length = _length_km(by_id[str(edge["from"])], by_id[str(edge["to"])], scale)
        dash = ' stroke-dasharray="9 7"' if road_type == "dirt" else ""
        parts.append(
            f'<line id="edge-{edge["id"]}" data-edge-id="{edge["id"]}" '
            f'data-road-type="{road_type}" data-from="{edge["from"]}" data-to="{edge["to"]}" '
            f'data-distance-km="{length}" '
            f'x1="{left[0]:.2f}" y1="{left[1]:.2f}" x2="{right[0]:.2f}" y2="{right[1]:.2f}" '
            f'stroke="{"#285c8e" if road_type == "highway" else "#886235"}" '
            f'stroke-width="{"7" if road_type == "highway" else "4"}"{dash}/>'
        )
        ratio = 0.5 if road_type == "highway" else 0.25
        label_x = left[0] + (right[0] - left[0]) * ratio
        label_y = left[1] + (right[1] - left[1]) * ratio - 9
        parts.append(
            f'<text data-edge-label="{edge["id"]}" x="{label_x:.2f}" '
            f'y="{label_y:.2f}" font-size="14" text-anchor="middle" '
            'paint-order="stroke" stroke="white" stroke-width="4">'
            f"{length} км</text>"
        )
    # The diagonal roads cross geometrically but do not create a graph vertex.
    cross = (
        (coordinates["A"][0] + coordinates["C"][0]) / 2,
        (coordinates["A"][1] + coordinates["C"][1]) / 2,
    )
    parts.append(
        f'<circle id="non-junction-crossing" cx="{cross[0]:.2f}" '
        f'cy="{cross[1]:.2f}" r="9" fill="white"/>'
    )
    parts.append(
        f'<path d="M{cross[0] - 8:.2f} {cross[1]:.2f} q8 -11 16 0" '
        'fill="none" stroke="#886235" stroke-width="4"/>'
    )
    for node_id, node in by_id.items():
        x, y = coordinates[node_id]
        parts.append(
            f'<circle data-node-id="{node_id}" cx="{x:.2f}" cy="{y:.2f}" '
            'r="17" fill="#f7cf67" stroke="#26364a" stroke-width="2"/>'
        )
        parts.append(
            f'<text data-node-number="{node_id}" x="{x:.2f}" '
            f'y="{y + 6:.2f}" text-anchor="middle" font-size="17" '
            f'font-weight="700">{_int(node["number"])}</text>'
        )
    table = _mapping(context["shopping"])
    parts.extend(
        [
            '<g id="shopping-table" transform="translate(545 115)">',
            '<text x="0" y="0" font-size="18" font-weight="700">Цены за единицу (₽)</text>',
        ]
    )
    quantities = cast(list[int], table["quantities"])
    products = cast(list[str], table["products"])
    stores = cast(list[Mapping[str, object]], table["stores"])
    parts.append('<text x="0" y="30" font-size="14">Товар × количество</text>')
    for i, (product, quantity) in enumerate(zip(products, quantities, strict=True)):
        shown_quantity = quantity if quantity > 0 else "—"
        parts.append(
            f'<text data-product-id="{escape(product)}" data-quantity="{quantity}" '
            f'x="0" y="{58 + i * 27}" font-size="14">{escape(product)} · {shown_quantity}</text>'
        )
    for j, store in enumerate(stores):
        x = 145 + j * 55
        store_id = escape(str(store["id"]))
        parts.append(
            f'<text data-store-id="{store_id}" x="{x}" y="30" font-size="14">{store_id}</text>'
        )
        prices = cast(list[int], store["prices"])
        for i, price in enumerate(prices):
            parts.append(
                f'<text data-store-id="{store_id}" data-product-id="{escape(products[i])}" '
                f'data-price="{price}" x="{x}" y="{58 + i * 27}" font-size="14">{price}</text>'
            )
    parts.extend(["</g>", "</svg>"])
    return "".join(parts).encode("utf-8")


def _png(context: Mapping[str, object]) -> bytes:
    nodes = cast(list[Mapping[str, object]], context["nodes"])
    edges = cast(list[Mapping[str, object]], context["edges"])
    by_id = {str(node["id"]): node for node in nodes}
    scale = _int(context["scale_km_per_cell"])
    width_km = max(_int(node["x"]) for node in nodes)
    height_km = max(_int(node["y"]) for node in nodes)
    factor = min(400 / max(width_km, 1), 235 / max(height_km, 1))
    coords = {
        n: (70 + _int(v["x"]) * factor, 300 - _int(v["y"]) * factor) for n, v in by_id.items()
    }
    image = Image.new("RGB", (900, 470), "white")
    draw = ImageDraw.Draw(image)
    for cell_x in range(width_km + 1):
        grid_x = 70 + cell_x * factor
        draw.line((grid_x, 35, grid_x, 345), fill="#e7edf3", width=1)
    for cell_y in range(height_km + 1):
        grid_y = 300 - cell_y * factor
        draw.line((35, grid_y, 515, grid_y), fill="#e7edf3", width=1)
    for edge in edges:
        left, right = coords[str(edge["from"])], coords[str(edge["to"])]
        color = "#285c8e" if edge["type"] == "highway" else "#886235"
        if edge["type"] == "highway":
            draw.line((left, right), fill=color, width=7)
        else:
            dx, dy = right[0] - left[0], right[1] - left[1]
            length_px = max((dx * dx + dy * dy) ** 0.5, 1)
            for start in range(0, int(length_px), 16):
                end = min(start + 9, int(length_px))
                draw.line(
                    (
                        left[0] + dx * start / length_px,
                        left[1] + dy * start / length_px,
                        left[0] + dx * end / length_px,
                        left[1] + dy * end / length_px,
                    ),
                    fill=color,
                    width=4,
                )
        distance = _length_km(by_id[str(edge["from"])], by_id[str(edge["to"])], scale)
        ratio = 0.5 if edge["type"] == "highway" else 0.25
        label_xy = (
            left[0] + (right[0] - left[0]) * ratio,
            left[1] + (right[1] - left[1]) * ratio - 12,
        )
        draw.text(
            label_xy,
            f"{distance} km",
            fill="#17202b",
            stroke_width=3,
            stroke_fill="white",
        )
    center = ((coords["A"][0] + coords["C"][0]) / 2, (coords["A"][1] + coords["C"][1]) / 2)
    draw.ellipse((center[0] - 9, center[1] - 9, center[0] + 9, center[1] + 9), fill="white")
    draw.arc(
        (center[0] - 9, center[1] - 12, center[0] + 9, center[1] + 9),
        180,
        360,
        fill="#886235",
        width=4,
    )
    for node_id, node in by_id.items():
        x, y = coords[node_id]
        draw.ellipse((x - 17, y - 17, x + 17, y + 17), fill="#f7cf67", outline="#26364a", width=2)
        draw.text((x - 4, y - 7), str(node["number"]), fill="#17202b")
    draw.text((545, 40), f"1 cell = {scale} km", fill="#17202b")
    table = _mapping(context["shopping"])
    draw.text((545, 75), "SHOPPING PRICES (rub/unit)", fill="#17202b")
    products = cast(list[str], table["products"])
    quantities = cast(list[int], table["quantities"])
    stores = cast(list[Mapping[str, object]], table["stores"])
    draw.text((545, 105), "Product x quantity; rub/unit", fill="#17202b")
    for i, (product, quantity) in enumerate(zip(products, quantities, strict=True)):
        shown_quantity = quantity if quantity > 0 else "-"
        draw.text((545, 130 + i * 26), f"{product} x {shown_quantity}", fill="#17202b")
    for j, store in enumerate(stores):
        x = 690 + j * 52
        draw.text((x, 105), str(store["id"]), fill="#17202b")
        for i, price in enumerate(cast(list[int], store["prices"])):
            draw.text((x, 130 + i * 26), str(price), fill="#17202b")
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


class _RouteRenderer:
    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario:
        svg = _svg(scenario.context)
        png = _png(scenario.context)
        assets = tuple(
            _asset(data, kind) for data, kind in ((svg, "image/svg+xml"), (png, "image/png"))
        )
        summary = _shared_text(scenario)
        return RenderedScenario(summary, assets)

    def restore_asset(self, snapshot: ScenarioSnapshot, asset: ScenarioAssetRef) -> bytes:
        context = cast(Mapping[str, object], snapshot.context)
        if asset.content_type == "image/svg+xml":
            data = _svg(context)
        elif asset.content_type == "image/png":
            data = _png(context)
        else:
            raise ValueError("Unsupported ROUTE asset content type")
        return data


def _asset(data: bytes, content_type: str) -> ScenarioAssetRef:
    digest = sha256(data).hexdigest()
    extension = "svg" if content_type == "image/svg+xml" else "png"
    return ScenarioAssetRef(digest, content_type, f"sha256/{digest}.{extension}")


def _shared_text(scenario: ScenarioDraft) -> str:
    values = _route_values(scenario)
    return (
        f"Карта: поселения GRID-4; масштаб — {scenario.context['scale_km_per_cell']} км на клетку. "
        f"Шоссе: {values['ab']} км и {values['bc']} км; грунтовые дороги показаны пунктиром. "
        "Пересечение диагоналей обозначено мостом и не является развязкой. "
        "Таблица цен относится к тому же набору продуктов и тому же миру."
    )


class _RouteOracle:
    def validate_scenario(self, scenario: ScenarioDraft) -> None:
        if scenario.story_code != STORY_CODE or scenario.generator_version != GENERATOR_VERSION:
            raise ValueError("ROUTE scenario identity/version mismatch")
        context = scenario.context
        if context.get("topology_id") != "GRID4_RECTANGLE_ROADS_V1":
            raise ValueError("ROUTE topology is outside the audited grid family")
        nodes = _node_map(scenario)
        if set(nodes) != {"A", "B", "C", "D"}:
            raise ValueError("ROUTE grid must have exactly four named nodes")
        expected_points = {"A": (0, 0), "B": (None, 0), "C": (None, None), "D": (0, None)}
        for node_id, node in nodes.items():
            x, y = _int(node["x"]), _int(node["y"])
            exp_x, exp_y = expected_points[node_id]
            if exp_x is not None and x != exp_x or exp_y is not None and y != exp_y:
                raise ValueError("ROUTE nodes violate rectangle coordinates")
            if not 1 <= _int(node["number"]) <= 4:
                raise ValueError("ROUTE map labels must be 1..4")
        if len({node["number"] for node in nodes.values()}) != 4:
            raise ValueError("ROUTE node labels must form a bijection")
        names = [str(node["name"]) for node in nodes.values()]
        if any(not name.strip() for name in names) or len(set(names)) != 4:
            raise ValueError("ROUTE village names must be unique and non-empty")
        b_x, c_x = _int(nodes["B"]["x"]), _int(nodes["C"]["x"])
        c_y, d_y = _int(nodes["C"]["y"]), _int(nodes["D"]["y"])
        if min(b_x, c_y) <= 0 or b_x != c_x or c_y != d_y:
            raise ValueError("ROUTE rectangle dimensions must be positive")
        scale = _int(context["scale_km_per_cell"])
        if scale not in (1, 2, 3, 4):
            raise ValueError("ROUTE cell scale is outside the allowed integer range")
        raw_edges = cast(list[Mapping[str, object]], context["edges"])
        edge_values = {
            (str(edge["from"]), str(edge["to"]), str(edge["type"])) for edge in raw_edges
        }
        expected_edges = {
            ("A", "B", "highway"),
            ("B", "C", "highway"),
            ("A", "C", "dirt"),
            ("D", "B", "dirt"),
        }
        if edge_values != expected_edges or len(raw_edges) != 4:
            raise ValueError("ROUTE road topology or type differs from GRID-4")
        data = _route_values(scenario)
        if data["highway"] > 200:
            raise ValueError("ROUTE highway length exceeds the supported range")
        shopping = _mapping(context["shopping"])
        quantities = cast(list[int], shopping["quantities"])
        stores = cast(list[Mapping[str, object]], shopping["stores"])
        products = cast(list[str], shopping["products"])
        store_ids = [str(store["id"]) for store in stores]
        if (
            len(stores) != 4
            or len(quantities) != 5
            or len(products) != 5
            or len(set(products)) != 5
            or len(set(store_ids)) != 4
            or not 2 <= sum(quantity > 0 for quantity in quantities) <= 4
            or any(quantity < 0 for quantity in quantities)
        ):
            raise ValueError("ROUTE shopping table has invalid dimensions")
        if any(len(cast(list[int], store["prices"])) != 5 for store in stores):
            raise ValueError("ROUTE shopping table must show five product prices per store")
        totals = [
            sum(q * p for q, p in zip(quantities, cast(list[int], store["prices"]), strict=True))
            for store in stores
        ]
        if totals.count(min(totals)) != 1 or any(
            price <= 0 for store in stores for price in cast(list[int], store["prices"])
        ):
            raise ValueError("ROUTE shopping prices must be positive with a strict minimum")

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None:
        self.validate_scenario(scenario)
        data = _route_values(scenario)
        expected_family = {1: F01, 2: F03, 3: F05, 4: F06, 5: F09}[question.position]
        if question.family_id != expected_family or question.scenario_seed != scenario.seed:
            raise ValueError("ROUTE question does not belong to the single GRID-4 bundle")
        if not rendered.shared_context.startswith("Карта: поселения GRID-4;"):
            raise ValueError("ROUTE rendered context is missing its visible map description")
        _validate_svg_manifest(_svg(scenario.context), scenario)
        if question.position == 1:
            match = "".join(str(_int(_node_map(scenario)[n]["number"])) for n in ("A", "B", "C"))
            if any(
                str(_node_map(scenario)[node]["name"]) not in question.condition
                for node in ("A", "B", "C")
            ):
                raise ValueError("ROUTE visible name sequence differs from the map model")
        elif question.position == 2:
            match = str(data["highway"])
        elif question.position == 3:
            match = str(data["direct"])
        elif question.position == 4:
            match = str(60 * data["highway"] // data["speed"])
            if (60 * data["highway"]) % data["speed"]:
                raise ValueError("ROUTE time is not exactly representable in whole minutes")
        else:
            table = _mapping(scenario.context["shopping"])
            quantities = cast(list[int], table["quantities"])
            totals = [
                sum(
                    q * p for q, p in zip(quantities, cast(list[int], store["prices"]), strict=True)
                )
                for store in cast(list[Mapping[str, object]], table["stores"])
            ]
            match = str(min(totals))
            if (
                "наименьшую стоимость" not in question.condition
                or "цены за единицу" not in question.condition
                or "таблице" not in question.condition
                or "маршрут" in question.condition.lower()
            ):
                raise ValueError("ROUTE position 5 must ask for the basket minimum")
        if question.position != 5:
            expected_condition_token = {
                1: "Запишите код",
                2: "через",
                3: "по прямой",
                4: "при скорости",
            }[question.position]
            if expected_condition_token not in question.condition:
                raise ValueError("ROUTE visible condition does not state the modeled operation")
            if question.position in (2, 4) and any(
                str(_node_map(scenario)[node]["name"]) not in question.condition
                for node in ("A", "B", "C")
            ):
                raise ValueError("ROUTE route condition names a different or missing settlement")
            if question.position in (2, 3, 4) and not all(
                str(value) in rendered.shared_context for value in (data["ab"], data["bc"])
            ):
                raise ValueError("ROUTE visible map description is missing edge lengths")
            if question.position == 4 and str(data["speed"]) not in question.condition:
                raise ValueError("ROUTE visible speed differs from the time model")
        if question.canonical_answer != match:
            raise ValueError("ROUTE visible answer differs from independently solved graph/table")
        if (
            question.position == 2
            and f"{data['ab']} + {data['bc']} = {data['highway']}"
            not in " ".join(question.solution_steps)
        ):
            raise ValueError("ROUTE path sum solution is inconsistent")
        if (
            question.position == 3
            and f"√({data['ab']}² + {data['bc']}²) = {data['direct']}"
            not in " ".join(question.solution_steps)
        ):
            raise ValueError("ROUTE diagonal solution is inconsistent")
        if (
            question.position == 4
            and f"60 · {data['highway']} / {data['speed']} = {match}"
            not in " ".join(question.solution_steps)
        ):
            raise ValueError("ROUTE time solution has a distance, speed or conversion error")
        if question.position == 5:
            table = _mapping(scenario.context["shopping"])
            quantities = cast(list[int], table["quantities"])
            stores = cast(list[Mapping[str, object]], table["stores"])
            expected_step_list: list[str] = []
            for store in stores:
                prices = cast(list[int], store["prices"])
                terms = [
                    f"{quantity} · {price}"
                    for quantity, price in zip(quantities, prices, strict=True)
                    if quantity > 0
                ]
                total = sum(
                    quantity * price for quantity, price in zip(quantities, prices, strict=True)
                )
                expected_step_list.append(f"{' + '.join(terms)} = {total} ₽ ({store['id']}).")
            exact_totals = tuple(
                sum(
                    q * price
                    for q, price in zip(quantities, cast(list[int], store["prices"]), strict=True)
                )
                for store in stores
            )
            expected_step_list.append(
                f"Минимум — {min(exact_totals)} ₽ "
                f"(магазин {stores[exact_totals.index(min(exact_totals))]['id']})."
            )
            expected_steps = tuple(expected_step_list)
            if question.solution_steps != expected_steps:
                raise ValueError(
                    "ROUTE shopping calculation steps differ from the visible price table"
                )

    def validate_bundle(
        self,
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        rendered: RenderedScenario,
    ) -> None:
        if tuple(question.position for question in questions) != (1, 2, 3, 4, 5):
            raise ValueError("ROUTE bundle must contain positions 1..5 in order")
        if any(question.scenario_seed != scenario.seed for question in questions):
            raise ValueError("ROUTE bundle cannot mix scenario seeds")
        if tuple(question.family_id for question in questions) != (F01, F03, F05, F06, F09):
            raise ValueError("ROUTE bundle mixes incompatible source kits")
        for question in questions:
            self.validate_question(scenario, question, rendered)
        expected_assets = {
            _asset(_svg(scenario.context), "image/svg+xml"),
            _asset(_png(scenario.context), "image/png"),
        }
        if set(rendered.assets) != expected_assets:
            raise ValueError("ROUTE rendered asset hashes do not match the immutable world")
        _validate_png_manifest(_png(scenario.context), scenario)
        if len({asset.sha256 for asset in rendered.assets}) != 2:
            raise ValueError("ROUTE must include one SVG and one PNG for the shared world")
        if {asset.content_type for asset in rendered.assets} != {"image/svg+xml", "image/png"}:
            raise ValueError("ROUTE renderer must provide SVG and PNG assets")


def _validate_svg_manifest(svg: bytes, scenario: ScenarioDraft) -> None:
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as error:
        raise ValueError("ROUTE SVG is not parseable") from error
    labels = {
        node.get("data-node-id"): (node.get("cx"), node.get("cy"))
        for node in root.iter()
        if node.get("data-node-id")
    }
    edges = {
        edge.get("data-edge-id"): (
            edge.get("data-from"),
            edge.get("data-to"),
            edge.get("data-road-type"),
            edge.get("data-distance-km"),
        )
        for edge in root.iter()
        if edge.get("data-edge-id")
    }
    if set(labels) != {"A", "B", "C", "D"} or set(edges) != {"AB", "BC", "AC", "DB"}:
        raise ValueError("ROUTE SVG omits or duplicates a graph element")
    context = scenario.context
    node_map = _node_map(scenario)
    scale = _int(context["scale_km_per_cell"])
    expected = {
        "AB": ("A", "B", "highway", str(_length_km(node_map["A"], node_map["B"], scale))),
        "BC": ("B", "C", "highway", str(_length_km(node_map["B"], node_map["C"], scale))),
        "AC": ("A", "C", "dirt", str(_length_km(node_map["A"], node_map["C"], scale))),
        "DB": ("D", "B", "dirt", str(_length_km(node_map["D"], node_map["B"], scale))),
    }
    if edges != expected:
        raise ValueError(
            "ROUTE SVG edge topology, road style or visible length differs from the graph"
        )
    edge_labels = {
        element.get("data-edge-label"): (element.text or "").strip()
        for element in root.iter()
        if element.get("data-edge-label")
    }
    if edge_labels != {edge_id: f"{attributes[3]} км" for edge_id, attributes in expected.items()}:
        raise ValueError("ROUTE visible SVG edge labels differ from the graph lengths")
    width = max(_int(node["x"]) for node in node_map.values())
    height = max(_int(node["y"]) for node in node_map.values())
    factor = min(420 / max(width, 1), 250 / max(height, 1))
    for node_id, node in node_map.items():
        expected_xy = (
            f"{90 + _int(node['x']) * factor:.2f}",
            f"{340 - _int(node['y']) * factor:.2f}",
        )
        if labels[node_id] != expected_xy:
            raise ValueError("ROUTE SVG node position differs from the mathematical grid")
    grid_group = next((element for element in root.iter() if element.get("id") == "grid"), None)
    if grid_group is None:
        raise ValueError("ROUTE SVG is missing its coordinate grid")
    actual_grid = {element.get("d") for element in grid_group if element.tag.endswith("path")}
    expected_grid = {
        *(f"M{90 + cell_x * factor:.2f} 55V390" for cell_x in range(width + 1)),
        *(f"M40 {340 - cell_y * factor:.2f}H510" for cell_y in range(height + 1)),
    }
    if actual_grid != expected_grid:
        raise ValueError("ROUTE SVG grid spacing differs from the coordinate scale")
    visible_numbers = {
        element.get("data-node-number"): (element.text or "").strip()
        for element in root.iter()
        if element.get("data-node-number")
    }
    expected_numbers = {node_id: str(_int(node["number"])) for node_id, node in node_map.items()}
    if visible_numbers != expected_numbers:
        raise ValueError("ROUTE SVG number labels differ from the scenario graph")
    scale_text = " ".join(
        (element.text or "") for element in root.iter() if element.tag.endswith("text")
    )
    if f"1 клетка = {scale} км" not in scale_text:
        raise ValueError("ROUTE SVG scale caption is missing or wrong")
    shopping = _mapping(context["shopping"])
    quantity_rows = {
        element.get("data-product-id"): (
            element.get("data-quantity"),
            (element.text or "").strip(),
        )
        for element in root.iter()
        if element.get("data-product-id") and element.get("data-quantity")
    }
    products = cast(list[str], shopping["products"])
    quantities = cast(list[int], shopping["quantities"])
    expected_quantities = {
        product: (str(quantity), f"{product} · {quantity if quantity > 0 else '—'}")
        for product, quantity in zip(products, quantities, strict=True)
    }
    if quantity_rows != expected_quantities:
        raise ValueError("ROUTE SVG shopping quantities differ from the scenario table")
    price_cells = {
        (element.get("data-store-id"), element.get("data-product-id")): (
            element.get("data-price"),
            (element.text or "").strip(),
        )
        for element in root.iter()
        if element.get("data-store-id") and element.get("data-price")
    }
    expected_prices = {
        (str(store["id"]), product): (str(price), str(price))
        for store in cast(list[Mapping[str, object]], shopping["stores"])
        for product, price in zip(products, cast(list[int], store["prices"]), strict=True)
    }
    if price_cells != expected_prices:
        raise ValueError("ROUTE SVG shopping table differs from the scenario table")


def _validate_png_manifest(png: bytes, scenario: ScenarioDraft) -> None:
    try:
        image = Image.open(BytesIO(png)).convert("RGB")
    except OSError as error:
        raise ValueError("ROUTE PNG cannot be decoded") from error
    if image.size != (900, 470):
        raise ValueError("ROUTE PNG has unexpected dimensions")
    nodes = _node_map(scenario)
    width = max(_int(node["x"]) for node in nodes.values())
    height = max(_int(node["y"]) for node in nodes.values())
    factor = min(400 / max(width, 1), 235 / max(height, 1))
    for node in nodes.values():
        x = round(70 + _int(node["x"]) * factor)
        y = round(300 - _int(node["y"]) * factor)
        if not (17 <= x < image.width - 17 and 17 <= y < image.height - 17):
            raise ValueError("ROUTE PNG clips a settlement symbol")
        if image.getpixel((x + 12, y + 8)) != (247, 207, 103):
            raise ValueError("ROUTE PNG settlement position differs from the graph")


class _Policy:
    def __init__(self, policy_id: str, kind: str) -> None:
        self.policy_id = policy_id
        self.version = POLICY_VERSION
        self._kind = kind

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool:
        raw = raw_answer.strip()
        if self._kind == "code":
            return raw == canonical_answer and raw.isdigit()
        normalized = raw.replace(",", ".")
        if not normalized or normalized.startswith(("+", "-")):
            return False
        try:
            return float(normalized).is_integer() and int(float(normalized)) == int(
                canonical_answer
            )
        except ValueError:
            return False


def build_adapter() -> StoryAdapter:
    policies: Mapping[tuple[str, str], AnswerPolicy] = MappingProxyType(
        {
            ("route.code.exact", POLICY_VERSION): _Policy("route.code.exact", "code"),
            ("route.integer_km", POLICY_VERSION): _Policy("route.integer_km", "number"),
            ("route.integer_min", POLICY_VERSION): _Policy("route.integer_min", "number"),
            ("route.integer_rub", POLICY_VERSION): _Policy("route.integer_rub", "number"),
        }
    )
    registrations = tuple(
        FamilyRegistration(
            family_id=family_id,
            position=position,
            status=FamilyStatus.ENABLED_CANDIDATE,
            answer_policy_id=policy_id,
            answer_policy_version=POLICY_VERSION,
            enabled=False,
            source_ids=SOURCES_BY_POSITION[position],
        )
        for position, family_id, policy_id in (
            (1, F01, "route.code.exact"),
            (2, F03, "route.integer_km"),
            (3, F05, "route.integer_km"),
            (4, F06, "route.integer_min"),
            (5, F09, "route.integer_rub"),
        )
    )
    return cast(
        StoryAdapter,
        type(
            "RouteStoryAdapter",
            (),
            {
                "story_code": STORY_CODE,
                "generator": _RouteGenerator(),
                "question_builder": _RouteQuestionBuilder(),
                "independent_oracle": _RouteOracle(),
                "renderer": _RouteRenderer(),
                "answer_policies": policies,
                "family_registry": registrations,
            },
        )(),
    )
