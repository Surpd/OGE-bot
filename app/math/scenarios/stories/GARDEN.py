"""Research-bounded garden plot adapter for the OGE 1–5 scenario engine.

The parameterized plan retains the Sosnovka arrangement of objects.
Legacy snapshots keep their original vector geometry.
"""

# SVG path/data strings are intentionally long single attributes.
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from hashlib import sha256
from math import ceil
from random import Random
from re import findall, search
from types import MappingProxyType
from typing import cast
from xml.etree import ElementTree

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

VERSION = "garden-sosnovka-1.8"
_FIXED_GEOMETRY_VERSION = "garden-sosnovka-1.7"
PREVIOUS_VERSION = "garden-sosnovka-1.6"
SOURCE_PLAN_VERSIONS = frozenset({VERSION, _FIXED_GEOMETRY_VERSION, PREVIOUS_VERSION, "garden-sosnovka-1.5"})
HEAT_TABLE_ONLY_VERSIONS = frozenset({VERSION, _FIXED_GEOMETRY_VERSION})
_MODERN_HEAT_VERSIONS = HEAT_TABLE_ONLY_VERSIONS | {PREVIOUS_VERSION}
_PRE_HEAT_VERSION = "garden-sosnovka-1.3"
_PRE_GEOMETRY_VERSION = "garden-sosnovka-1.4"
POLICY_VERSION = "1"
SOURCE_IDS = ("408405", "408413", "408424", "408432", "408438")
FAMILIES = tuple(
    f"GARDEN-{n:02d}-{name}"
    for n, name in (
        (1, "IDENTIFY"),
        (2, "TILES-PACKS"),
        (4, "PERIMETER-POLYGON"),
        (7, "PERCENT-BUILDINGS"),
        (9, "HEAT-BREAKEVEN"),
    )
)


def _world(seed: int) -> dict[str, JsonValue]:
    rng = Random(seed ^ 0x6A4D)
    # Bounded source-preserving tariff variants; geometry and non-economic values
    # remain the exact single confirmed Sosnovka fixture.
    hours = 500 if seed == 0 else rng.randrange(5, 26) * 50
    gas_hourly = 784
    electric_hourly = 2058
    premium = (electric_hourly - gas_hourly) * hours // 100
    base = 29_000 if seed == 0 else 29_000 + rng.randrange(0, 100) * 100
    roles = ("house", "bath", "garage", "greenhouse", "shed", "orchard")
    numbers = [7, 4, 2, 5, 1, 3]
    if seed:
        Random(seed ^ 0xC137).shuffle(numbers)
    labels: dict[str, JsonValue] = {**dict(zip(roles, numbers, strict=True)), "garden": 6}
    return {
        "template_id": "SOSNOVKA-2025-1.1",
        "world_version": _FIXED_GEOMETRY_VERSION,
        "grid_side_m": 2,
        "plot_area_m2": 600,
        "labels": labels,
        "building_areas_m2": (68, 36, 48, 24),
        "exposed_perimeter_edges": 18,
        "path_tiles": 25,
        "pad_tiles": 40,
        "tiles_per_pack": 10 if seed == 0 else Random(seed ^ 0x91AB).choice(
            (5, 6, 8, 9, 10, 12, 13, 15)
        ),
        "garden_area_m2": 120,
        "greenhouse_area_m2": 12,
        "heat": {
            "gas_heater_cost": 20_000,
            "gas_installation_cost": 9_000 + premium + (base - 29_000),
            "electric_heater_cost": 15_000,
            "electric_installation_cost": 14_000 + (base - 29_000),
            "gas_m3_per_hour_tenths": 16,
            "gas_price_per_m3_tenths": 49,
            "electric_kw_tenths": 49,
            "electric_price_per_kwh_tenths": 42,
            "break_even_hours": hours,
        },
        "scenario_seed": seed,
    }


def _svg_legacy(ctx: Mapping[str, JsonValue]) -> bytes:
    # Fixed 30 m x 20 m plot. One metre is 10 SVG units, matching the
    # 20-unit grid and 10-unit (1 m) paved paths.
    labels = cast(Mapping[str, int], ctx["labels"])
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 400 300">',
        '<rect width="400" height="300" fill="#fff"/>',
        '<g stroke="#d9e3d2" stroke-width=".7">',
    ]
    for x in range(20, 321, 20):
        parts.append(f'<path d="M{x} 20V220"/>')
    for y in range(20, 221, 20):
        parts.append(f'<path d="M20 {y}H320"/>')
    parts.extend(
        [
            "</g>",
            '<path d="M20 20H320V110 M320 130V220H20Z" fill="none" stroke="#283b2d" stroke-width="3"/>',
            '<text x="322" y="124" font-size="8">Ворота</text>',
            '<path data-role="paving" d="M320 120H200V180H110" fill="none" stroke="#b99d6b" stroke-width="10" stroke-linecap="butt" stroke-linejoin="round"/>',
            '<rect data-role="pad" x="210" y="100" width="80" height="50" fill="#d9c99e" stroke="#725f3e"/>',
            '<path data-role="house" d="M120 20H200V80H220V100H120Z" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="bath" x="40" y="130" width="60" height="80" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="garage" x="260" y="160" width="40" height="60" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="shed" x="240" y="20" width="60" height="60" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="garden" x="80" y="100" width="120" height="100" fill="#a8d88a" stroke="#39783d"/>',
            '<rect data-role="greenhouse" x="120" y="130" width="30" height="40" fill="#a9dce6" stroke="#267085"/>',
            '<g data-role="orchard" fill="#478e42"><circle cx="50" cy="50" r="7"/><circle cx="75" cy="50" r="7"/><circle cx="50" cy="75" r="7"/></g>',
        ]
    )
    label_points = {
        "house": (170, 50),
        "bath": (70, 170),
        "garage": (280, 190),
        "shed": (270, 50),
        "greenhouse": (135, 152),
        "garden": (170, 180),
        "orchard": (62, 100),
    }
    for role, (x, y) in label_points.items():
        parts.append(
            f'<text data-label="{role}" x="{x}" y="{y}" text-anchor="middle" font-size="9">{labels[role]}</text>'
        )
    parts.extend(
        [
            '<text x="338" y="40" font-size="8">Условные обозначения</text>',
            '<text x="338" y="56" font-size="7">1 — сарай</text><text x="338" y="70" font-size="7">2 — гараж</text>',
            '<text x="338" y="84" font-size="7">3 — яблони</text><text x="338" y="98" font-size="7">4 — баня</text>',
            '<text x="338" y="112" font-size="7">5 — теплица</text><text x="338" y="126" font-size="7">6 — огород</text>',
            '<text x="338" y="140" font-size="7">7 — жилой дом</text>',
            '<path d="M340 180H390" stroke="#333" stroke-width="2"/><path d="M340 176V184M390 176V184" stroke="#333"/>',
            '<text x="340" y="194" font-size="7">Масштаб: 2 м на клетку</text>',
            '<text x="24" y="240" font-size="8">Дорожки и площадка вымощены плиткой 1×1 м; ширина дорожки — 1 м.</text>',
            '<text x="24" y="258" font-size="8">Аналог ОГЭ: схема участка, клетка — 2 м.</text>',
            "</svg>",
        ]
    )
    image = "".join(parts)
    if ctx["world_version"] not in {
        "garden-sosnovka-1.2", _PRE_HEAT_VERSION, _PRE_GEOMETRY_VERSION
    }:
        return image.encode("utf-8")
    start = image.index('<path data-role="paving"')
    end = image.index('<rect data-role="pad"', start)
    # Coordinates in tenths of a metre. The four strips meet at their edges.
    strips = ((290, 115, 30, 10), (200, 115, 10, 10),
              (200, 125, 10, 90), (80, 210, 120, 10))
    paving = "".join(
        f'<rect data-role="paving" x="{x}" y="{y}" width="{w}" height="{h}" fill="#b99d6b"/>'
        for x, y, w, h in strips
    )
    image = image[:start] + paving + image[end:]
    image = image.replace('data-role="bath" x="40"', 'data-role="bath" x="20"')
    image = image.replace('data-label="bath" x="70"', 'data-label="bath" x="50"')
    start = image.index('<text x="338"')
    end = image.index('<text x="24" y="240"', start)
    image = image[:start] + image[end:]
    return image.encode("utf-8")


def _svg_current(ctx: Mapping[str, JsonValue]) -> bytes:
    labels = cast(Mapping[str, int], ctx["labels"])
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 400 300">',
        '<rect width="400" height="300" fill="#fff"/>',
        '<g stroke="#d9e3d2" stroke-width=".7">',
    ]
    for x in range(20, 321, 20):
        parts.append(f'<path d="M{x} 20V220"/>')
    for y in range(20, 221, 20):
        parts.append(f'<path d="M20 {y}H320"/>')
    parts.extend(
        [
            "</g>",
            '<path d="M20 20H320V120 M320 140V220H20Z" fill="none" stroke="#283b2d" stroke-width="3"/>',
            '<text x="322" y="134" font-size="8">Ворота</text>',
            '<rect data-role="paving" x="60" y="140" width="220" height="10" fill="#b99d6b"/>',
            '<rect data-role="paving" x="150" y="120" width="10" height="20" fill="#b99d6b"/>',
            '<rect data-role="paving" x="60" y="150" width="10" height="10" fill="#b99d6b"/>',
            '<rect data-role="pad" x="280" y="60" width="40" height="100" fill="#d9c99e" stroke="#725f3e"/>',
            '<polygon data-role="house" points="140,40 240,40 240,100 180,100 180,120 140,120" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="bath" x="20" y="160" width="60" height="60" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="garage" x="240" y="160" width="80" height="60" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="shed" x="260" y="20" width="60" height="40" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>',
            '<rect data-role="garden" x="20" y="20" width="100" height="120" fill="#a8d88a" stroke="#39783d"/>',
            '<rect data-role="greenhouse" x="40" y="40" width="60" height="20" fill="#a9dce6" stroke="#267085"/>',
            '<g data-role="orchard" data-grid-bounds="3,7,11,10" fill="#478e42">',
        ]
    )
    for x in (100, 220):
        for y in (170, 210):
            parts.append(f'<circle cx="{x}" cy="{y}" r="6"/>')
    parts.append("</g>")
    label_points = {
        "house": (160, 75),
        "bath": (50, 190),
        "garage": (280, 190),
        "shed": (290, 40),
        "greenhouse": (70, 50),
        "garden": (85, 115),
        "orchard": (160, 190),
    }
    for role, (x, y) in label_points.items():
        parts.append(
            f'<text data-label="{role}" x="{x}" y="{y}" text-anchor="middle" font-size="9">{labels[role]}</text>'
        )
    parts.extend(
        [
            '<path d="M340 180H390" stroke="#333" stroke-width="2"/><path d="M340 176V184M390 176V184" stroke="#333"/>',
            '<text x="340" y="194" font-size="7">Масштаб: 2 м на клетку</text>',
            '<text x="24" y="258" font-size="8">Дорожки — 1 м, плитка — 1×1 м; площадка у ворот.</text>',
            '<text x="24" y="276" font-size="8">Аналог ОГЭ: план участка, клетка — 2 м.</text>',
            "</svg>",
        ]
    )
    return "".join(parts).encode("utf-8")


def _vary_geometry(seed: int) -> dict[str, JsonValue]:
    rng = Random(seed ^ 0x9F60)
    if seed == 0:
        house_w, main_h, wing_w, wing_h = 5, 3, 2, 1
        bath_w, bath_h, garage_w, garage_h, shed_w, shed_h, pad_w = 3, 3, 4, 3, 3, 2, 2
    else:
        house_w, main_h = rng.randint(4, 7), rng.randint(2, 8)
        wing_w, wing_h = rng.randint(2, 3), rng.randint(1, 2)
        bath_w, bath_h = rng.randint(3, 4), rng.randint(2, 3)
        garage_w, garage_h = rng.randint(3, 5), rng.randint(2, 3)
        shed_w, shed_h, pad_w = rng.randint(2, 3), rng.randint(2, 3), rng.randint(2, 3)

    # Coordinates are metres from the upper left corner. Buildings follow the
    # 2 m grid. The paving strips occupy whole one-metre squares.
    house_right = 12 + house_w * 2
    shoulder = 2 + main_h * 2
    house_bottom = shoulder + wing_h * 2
    path_y = max(12, house_bottom + 2)
    plot_w = max(30, house_right + 2 + pad_w * 2)
    plot_h = path_y + 8
    pad_x = plot_w - pad_w * 2
    pad_y = shed_h * 2
    bath_top = plot_h - bath_h * 2
    garage_left = plot_w - garage_w * 2
    paths: tuple[tuple[int, int, int, int], ...] = (
        (4, path_y, pad_x - 4, 1),
        (13, house_bottom, 1, path_y - house_bottom),
        (4, path_y + 1, 1, bath_top - path_y - 1),
        (plot_w - 1, path_y + 2, 1, 2),
    )
    # The source arrangement has the garage touching the pad. A shorter
    # garage instead meets a one-metre paved extension.
    if garage_h == 3:
        paths = paths[:3]
    rects = {
        "bath": (0, bath_top, bath_w * 2, bath_h * 2),
        "garage": (garage_left, plot_h - garage_h * 2, garage_w * 2, garage_h * 2),
        "shed": (plot_w - shed_w * 2, 0, shed_w * 2, shed_h * 2),
        "garden": (0, 0, 10, 12),
        "greenhouse": (2, 2, 6, 2),
        "pad": (pad_x, pad_y, pad_w * 2, path_y + 2 - pad_y),
    }
    return {
        "plot_size": (plot_w, plot_h),
        "gate_y": path_y - 1,
        "house_polygon": (
            (12, 2), (house_right, 2), (house_right, shoulder),
            (12 + wing_w * 2, shoulder), (12 + wing_w * 2, house_bottom), (12, house_bottom),
        ),
        "rects": rects,
        "path_rects": paths,
        "orchard_bounds": (bath_w * 2, path_y + 2, garage_left, plot_h),
        "plot_area_m2": plot_w * plot_h,
        "building_areas_m2": tuple(
            4 * n for n in (house_w * main_h + wing_w * wing_h,
                            bath_w * bath_h, garage_w * garage_h, shed_w * shed_h)
        ),
        "exposed_perimeter_edges": 2 * (house_w + main_h + wing_h),
        "path_tiles": sum(width * height for _, _, width, height in paths),
        "pad_tiles": rects["pad"][2] * rects["pad"][3],
    }


def _svg_diverse(ctx: Mapping[str, JsonValue]) -> bytes:
    labels = cast(Mapping[str, int], ctx["labels"])
    plot_w, plot_h = cast(tuple[int, int], ctx["plot_size"])
    gate_y = cast(int, ctx["gate_y"])
    right, bottom, gate = 20 + 10 * plot_w, 20 + 10 * plot_h, 20 + 10 * gate_y
    width, height = right + 80, bottom + 80
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width * 3}" height="{height * 3}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#fff"/>',
    ]
    for x, y, w, h in cast(tuple[tuple[int, int, int, int], ...], ctx["path_rects"]):
        parts.append(f'<rect data-role="paving" x="{20 + x * 10}" y="{20 + y * 10}" width="{w * 10}" height="{h * 10}" fill="#b99d6b"/>')
    rects = cast(Mapping[str, tuple[int, int, int, int]], ctx["rects"])
    fills = {"pad": "#d9c99e", "garden": "#a8d88a", "greenhouse": "#a9dce6"}
    label_points = {}
    for role, (x, y, w, h) in rects.items():
        fill = fills.get(role, "#e7b88e")
        parts.append(f'<rect data-role="{role}" x="{20 + x * 10}" y="{20 + y * 10}" width="{w * 10}" height="{h * 10}" fill="{fill}" stroke="#503d30"/>')
        label_points[role] = (20 + 10 * x + 5 * w, 20 + 10 * y + 5 * h)
    house = cast(tuple[tuple[int, int], ...], ctx["house_polygon"])
    points = " ".join(f"{20 + 10 * x},{20 + 10 * y}" for x, y in house)
    parts.append(f'<polygon data-role="house" points="{points}" fill="#e7b88e" stroke="#503d30" stroke-width="2"/>')
    label_points["house"] = (20 + 5 * (house[0][0] + house[1][0]), 20 + 5 * (house[0][1] + house[2][1]))
    x1, y1, x2, y2 = cast(tuple[int, int, int, int], ctx["orchard_bounds"])
    parts.append('<g data-role="orchard" fill="#478e42">')
    for x in (x1 + 1, x2 - 1):
        for y in (y1 + 1, y2 - 1):
            parts.append(f'<circle cx="{20 + x * 10}" cy="{20 + y * 10}" r="6"/>')
    parts.append("</g>")
    label_points["orchard"] = (20 + 5 * (x1 + x2), 20 + 5 * (y1 + y2))
    label_points["garden"] = (85, 115)
    parts.append('<g stroke="#849486" stroke-width=".7" opacity=".45">')
    parts.extend(f'<path d="M{x} 20V{bottom}"/>' for x in range(20, right + 1, 20))
    parts.extend(f'<path d="M20 {y}H{right}"/>' for y in range(20, bottom + 1, 20))
    parts.append("</g>")
    parts.extend((
        f'<path data-plot="{right},{bottom}" data-gate="{gate}" d="M20 20H{right}V{gate - 10} M{right} {gate + 10}V{bottom}H20Z" fill="none" stroke="#283b2d" stroke-width="3"/>',
        f'<text x="{right + 2}" y="{gate + 4}" font-size="8">Ворота</text>',
    ))
    for role, number in labels.items():
        x, y = label_points[role]
        parts.extend((
            f'<circle cx="{x}" cy="{y}" r="7" fill="white" stroke="#283b2d"/>',
            f'<text data-label="{role}" x="{x}" y="{y}" text-anchor="middle" dominant-baseline="central" font-size="9">{number}</text>',
        ))
    parts.extend((
        f'<text x="24" y="{bottom + 35}" font-size="8">Клетка — 2 м · дорожки — 1 м · плитка — 1×1 м</text>',
        "</svg>",
    ))
    return "".join(parts).encode("utf-8")




def _svg(ctx: Mapping[str, JsonValue]) -> bytes:
    if ctx.get("world_version") == VERSION:
        return _svg_diverse(ctx)
    if ctx.get("world_version") in SOURCE_PLAN_VERSIONS:
        return _svg_current(ctx)
    return _svg_legacy(ctx)


class _Policy:
    policy_id = "integer_or_code"
    version = POLICY_VERSION

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool:
        return raw_answer.strip() == canonical_answer


class _Generator:
    def generate_scenario(self, seed: int) -> ScenarioDraft:
        ctx = {**_world(seed), **_vary_geometry(seed), "world_version": VERSION}
        return ScenarioDraft(
            "GARDEN",
            seed,
            VERSION,
            ctx,
            "garden-compat-1",
            ("408405", "408413", "408424", "408432", "408438"),
        )


def _modern_heat_solution(heat: Mapping[str, int]) -> tuple[str, tuple[str, ...]]:
    gas_initial = heat["gas_heater_cost"] + heat["gas_installation_cost"]
    electric_initial = heat["electric_heater_cost"] + heat["electric_installation_cost"]
    gas_hourly = heat["gas_m3_per_hour_tenths"] * heat["gas_price_per_m3_tenths"]
    electric_hourly = heat["electric_kw_tenths"] * heat["electric_price_per_kwh_tenths"]
    numerator = (gas_initial - electric_initial) * 100
    denominator = electric_hourly - gas_hourly
    if denominator <= 0 or numerator <= 0 or numerator % denominator:
        raise ValueError("Heating data has no positive whole-hour break-even point")
    answer = str(numerator // denominator)
    return answer, (
        f"Начальные затраты: газ {heat['gas_heater_cost']} + {heat['gas_installation_cost']} = "
        f"{gas_initial} руб.; электричество {heat['electric_heater_cost']} + "
        f"{heat['electric_installation_cost']} = {electric_initial} руб.",
        f"За час: газ {heat['gas_m3_per_hour_tenths'] / 10:.1f} × "
        f"{heat['gas_price_per_m3_tenths'] / 10:.1f} = {gas_hourly / 100:.2f} руб.; "
        f"электричество {heat['electric_kw_tenths'] / 10:.1f} × "
        f"{heat['electric_price_per_kwh_tenths'] / 10:.1f} = {electric_hourly / 100:.2f} руб.",
        f"Разница начальных затрат — {gas_initial - electric_initial} руб., экономия газа — "
        f"{(electric_hourly - gas_hourly) / 100:.2f} руб./ч. Ответ: {answer} ч.",
    )


def _geometry_solution(
    context: Mapping[str, JsonValue], position: int, answer: str,
) -> tuple[str, ...]:
    if position == 2:
        paths = cast(tuple[tuple[int, int, int, int], ...], context["path_rects"])
        lengths = ", ".join(str(max(w, h)) for _, _, w, h in paths)
        _, _, pad_w, pad_h = cast(Mapping[str, tuple[int, int, int, int]], context["rects"])["pad"]
        total = cast(int, context["path_tiles"]) + cast(int, context["pad_tiles"])
        return (
            f"Длины полос шириной 1 м: {lengths} м. Их общая площадь {context['path_tiles']} м².",
            f"Площадка {pad_w} × {pad_h} м занимает {context['pad_tiles']} м². Всего нужно {total} плиток по 1 м².",
            f"Округляем {total} / {context['tiles_per_pack']} вверх. Ответ: {answer}.",
        )
    if position == 3:
        edges = context["exposed_perimeter_edges"]
        return (
            f"Внешний контур состоит из {edges} сторон клеток.",
            f"Периметр: {edges} × 2 = {answer} м.",
        )
    cells = tuple(area // 4 for area in cast(tuple[int, ...], context["building_areas_m2"]))
    width, height = cast(tuple[int, int], context["plot_size"])
    occupied = sum(cells) * 4
    plot = width * height
    counts = " + ".join(map(str, cells))
    return (
        f"Дом занимает {cells[0]} клеток, баня — {cells[1]}, гараж — {cells[2]}, сарай — {cells[3]}.",
        f"Площадь клетки — 4 м². Постройки занимают ({counts}) × 4 = {occupied} м².",
        f"Площадь участка: {width} × {height} = {plot} м².",
        f"Вычисляем {occupied} / {plot} × 100 и округляем до целого. Ответ: {answer} %.",
    )




class _Builder:
    def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft:
        c = scenario.context
        labels = cast(Mapping[str, int], c["labels"])
        areas = cast(tuple[int, ...], c["building_areas_m2"])
        pack = cast(int, c["tiles_per_pack"])
        if position == 1:
            answer = "".join(str(labels[k]) for k in ("house", "bath", "garage", "greenhouse"))
            condition = (
                "Найдите на плане номера жилого дома, бани, гаража и теплицы. "
                "Запишите четыре цифры в указанном порядке."
            )
        elif position == 2:
            answer = str(
                ceil(
                    (cast(int, c["path_tiles"]) + cast(int, c["pad_tiles"]))
                    / cast(int, c["tiles_per_pack"])
                )
            )
            condition = f"Сколько пачек плитки нужно для дорожек и прямоугольной площадки у ворот? Сторона клетки плана 2 м, ширина дорожки 1 м, размер плитки 1 × 1 м. В пачке {pack} плиток. Покрытие укладывают без зазоров."
        elif position == 3:
            answer = str(cast(int, c["exposed_perimeter_edges"]) * cast(int, c["grid_side_m"]))
            condition = "Дом имеет ломаную форму по сторонам клеток плана. Найдите периметр его внешнего контура в метрах, если сторона клетки 2 м."
        elif position == 4:
            plot_area = cast(int, c["plot_area_m2"])
            if scenario.generator_version == VERSION:
                answer = str((200 * sum(areas) + plot_area) // (2 * plot_area))
            else:
                answer = str(round(sum(areas) / plot_area * 100))
            condition = "Найдите по плану, сколько процентов площади участка занимают дом, баня, гараж и сарай. Это четыре бежевых строения. Сторона клетки 2 м. Ответ округлите до целого."
        elif position == 5:
            heat = cast(Mapping[str, int], c["heat"])
            if scenario.generator_version in _MODERN_HEAT_VERSIONS:
                gas_initial = heat["gas_heater_cost"] + heat["gas_installation_cost"]
                electric_initial = heat["electric_heater_cost"] + heat["electric_installation_cost"]
                gas_rate = heat["gas_m3_per_hour_tenths"] * heat["gas_price_per_m3_tenths"]
                electric_rate = heat["electric_kw_tenths"] * heat["electric_price_per_kwh_tenths"]
                answer = str((gas_initial - electric_initial) * 100 // (electric_rate - gas_rate))
                if scenario.generator_version in HEAT_TABLE_ONLY_VERSIONS:
                    condition = (
                        "Для одного и того же дома выбирают отопление газом или электричеством. "
                        "Используйте таблицу исходных данных. Через сколько часов суммарные "
                        "затраты на оборудование, установку и энергию сравняются?"
                    )
                else:
                    condition = (
                        "Для одного и того же дома выбирают отопление газом или электричеством. "
                        f"Стоимость оборудования и установки: газовый котёл {heat['gas_heater_cost']} руб. "
                        f"и монтаж {heat['gas_installation_cost']} руб.; электрический котёл "
                        f"{heat['electric_heater_cost']} руб. и монтаж {heat['electric_installation_cost']} руб. "
                        f"Расход газа — {heat['gas_m3_per_hour_tenths'] / 10:.1f} м³ в час, цена газа — "
                        f"{heat['gas_price_per_m3_tenths'] / 10:.1f} руб. за м³; мощность электрического "
                        f"котла — {heat['electric_kw_tenths'] / 10:.1f} кВт, цена электроэнергии — "
                        f"{heat['electric_price_per_kwh_tenths'] / 10:.1f} руб. за кВт·ч. "
                        "Через сколько часов суммарные затраты на оборудование, установку и топливо сравняются?"
                    )
            else:
                answer = str(heat["break_even_hours"])
                condition = f"Сравните отопление газом и электричеством по плану и данным: начальные затраты газ — {heat['gas_upfront']} руб., электричество — {heat['electric_upfront']} руб.; расходы за час — {heat['gas_hourly_cents'] / 100:.2f} и {heat['electric_hourly_cents'] / 100:.2f} руб. Через сколько часов суммарные затраты сравняются?"
        else:
            raise ValueError("Garden position must be 1..5")
        hints = {
            1: "Сопоставьте объекты с описанием их расположения на плане.",
            2: "Сложите число плиток и округлите число пачек вверх.",
            3: "Считайте только стороны клеток на внешней границе дома.",
            4: "Разделите суммарную площадь построек на площадь участка.",
            5: "Найдите разницу начальных затрат и экономию за один час.",
        }
        solutions = {
            1: (f"В указанном порядке на плане получаем номера {', '.join(answer)}.",),
            2: ("Длины четырёх полос шириной 1 м: 3, 1, 9 и 12 м. Их площадь 25 м².",
                "Площадка 8 × 5 м занимает 40 м². Всего нужно 65 плиток по 1 м².",
                f"Округляем 65 / {pack} вверх: нужно {answer} пачек."),
            3: ("Внешний контур состоит из 18 сторон клеток.", "Периметр: 18 × 2 = 36 м."),
            4: ("Клетка занимает 4 м². На плане дом занимает 17 клеток, "
                "баня — 9, гараж — 12, сарай — 6.",
                "Постройки занимают (17 + 9 + 12 + 6) × 4 = 176 м².",
                "Весь участок занимает 15 × 10 × 4 = 600 м².",
                "176 / 600 × 100 ≈ 29,33 %. После округления получаем 29 %."),
        }
        if position == 5:
            heat = cast(Mapping[str, int], c["heat"])
            if scenario.generator_version in _MODERN_HEAT_VERSIONS:
                checked_answer, solutions[5] = _modern_heat_solution(heat)
                if answer != checked_answer:
                    raise ValueError("Heating answer and source operands disagree")
            else:
                difference = heat["gas_upfront"] - heat["electric_upfront"]
                savings = (heat["electric_hourly_cents"] - heat["gas_hourly_cents"]) / 100
                solutions[5] = (
                    f"Газовое отопление дороже при установке на {difference} руб.",
                    f"За час оно экономит 20,58 − 7,84 = {savings:.2f} руб.",
                    f"Затраты сравняются через {difference} / {savings:.2f} = {answer} ч.",
                )
        if scenario.generator_version == VERSION and position in (2, 3, 4):
            solutions[position] = _geometry_solution(c, position, answer)
        model: dict[str, JsonValue] = {"position": position, "expected": answer}
        if position == 1:
            model["answer_grid"] = {
                "columns": ("Жилой дом", "Баня", "Гараж", "Теплица"),
                "header": "Объект",
                "row": "Цифра на плане",
            }
        return QuestionDraft(
            position,
            scenario.seed,
            FAMILIES[position - 1],
            scenario.generator_version,
            condition,
            "integer_or_code",
            POLICY_VERSION,
            answer,
            (hints[position],),
            solutions[position],
            model,
        )


class _Renderer:
    @staticmethod
    def _shared_context(scenario: ScenarioDraft) -> str:
        if scenario.generator_version in HEAT_TABLE_ONLY_VERSIONS:
            return (
                "На плане изображён дачный участок в посёлке Сосновка. Единственные ворота "
                "расположены на правой границе. При входе слева находится гараж, справа — сарай, "
                "а чуть дальше — жилой дом. Напротив дома находятся яблоневые посадки. "
                "Огород отмечен цифрой 6, теплица расположена внутри огорода; баня находится "
                "в нижней левой части участка. Клетка плана — 2 м; дорожки имеют ширину 1 м, "
                "плитка — 1×1 м.\n"
                "Отопление одного дома можно организовать газовым или электрическим котлом. "
                "Для сравнения учитывают стоимость котла, монтажа и потребляемой энергии; "
                "числовые исходные данные приведены в отдельной таблице.\n"
                "Все пять вопросов относятся к одному плану. Аналог ОГЭ."
            )
        if scenario.generator_version == PREVIOUS_VERSION:
            h = cast(Mapping[str, int], scenario.context["heat"])
            return (
                "На плане изображён дачный участок в посёлке Сосновка. Единственные ворота "
                "расположены на правой границе. При входе слева находится гараж, справа — сарай, "
                "а чуть дальше — жилой дом. Напротив дома находятся яблоневые посадки. "
                "Огород отмечен цифрой 6, теплица расположена внутри огорода; баня находится "
                "в нижней левой части участка. Клетка плана — 2 м; дорожки имеют ширину 1 м, "
                "плитка — 1×1 м.\n"
                "Отопление одного дома (общие данные):\n"
                f"Газ: котёл {h['gas_heater_cost']} руб., монтаж {h['gas_installation_cost']} руб.; "
                f"{h['gas_m3_per_hour_tenths'] / 10:.1f} м³/ч, {h['gas_price_per_m3_tenths'] / 10:.1f} руб./м³.\n"
                f"Электричество: котёл {h['electric_heater_cost']} руб., монтаж "
                f"{h['electric_installation_cost']} руб.; {h['electric_kw_tenths'] / 10:.1f} кВт, "
                f"{h['electric_price_per_kwh_tenths'] / 10:.1f} руб./(кВт·ч).\n"
                "Все пять вопросов относятся к одному плану. Аналог ОГЭ."
            )
        return (
            "На плане изображён дачный участок в посёлке Сосновка. Единственные ворота "
            "расположены на правой границе. При входе слева находится гараж, справа — сарай, "
            "а чуть дальше — жилой дом. Напротив дома находятся яблоневые посадки. "
            "Огород отмечен цифрой 6, теплица расположена внутри огорода; баня находится "
            "в нижней левой части участка. Клетка плана — 2 м; дорожки имеют ширину 1 м, "
            "плитка — 1×1 м.\n"
            "Все пять вопросов относятся к одному плану. Аналог ОГЭ."
        )

    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario:
        image = _svg(scenario.context)
        digest = sha256(image).hexdigest()
        ref = ScenarioAssetRef(digest, "image/svg+xml", f"sha256/{digest}.svg")
        return RenderedScenario(self._shared_context(scenario), (ref,))

    def restore_asset(self, snapshot: ScenarioSnapshot, asset: ScenarioAssetRef) -> bytes:
        if asset.content_type != "image/svg+xml":
            raise ValueError("Unknown garden asset")
        return _svg(snapshot.context)


def _visible_geometry(scenario: ScenarioDraft) -> tuple[int, int, int, int]:
    """Measure the rendered plan using one-metre squares and exposed edges."""
    c = scenario.context
    root = ElementTree.fromstring(_svg(c))
    fence = root.find(".//*[@data-plot]")
    if fence is None:
        raise ValueError("Missing garden fence")
    parsed = search(r"^M20 20H(\d+)V(\d+) M\1 (\d+)V(\d+)H20Z$", fence.attrib["d"])
    if parsed is None:
        raise ValueError("Garden fence must be rectangular with a gate on the right")
    right, gate_start, gate_end, bottom = map(int, parsed.groups())
    if (gate_end - gate_start != 20 or (right - 20) % 20 or (bottom - 20) % 20
            or root.attrib["viewBox"] != f"0 0 {right + 80} {bottom + 80}"):
        raise ValueError("Invalid garden scale or gate")
    width, height = (right - 20) // 10, (bottom - 20) // 10
    grid = {node.attrib["d"] for node in root.findall(".//{*}path") if node is not fence}
    if grid != (
        {f"M{x} 20V{bottom}" for x in range(20, right + 1, 20)}
        | {f"M20 {y}H{right}" for y in range(20, bottom + 1, 20)}
    ):
        raise ValueError("Displayed grid differs from the two-metre scale")

    def rectangle(node: ElementTree.Element) -> set[tuple[int, int]]:
        x, y, w, h = (int(node.attrib[key]) for key in ("x", "y", "width", "height"))
        if any(n % 10 for n in (x, y, w, h)) or min(w, h) <= 0:
            raise ValueError("Garden rectangle must occupy whole tiles")
        return {(col, row) for col in range((x - 20) // 10, (x + w - 20) // 10)
                for row in range((y - 20) // 10, (y + h - 20) // 10)}

    def region(role: str) -> ElementTree.Element:
        nodes = root.findall(f".//*[@data-role='{role}']")
        if len(nodes) != 1:
            raise ValueError(f"Missing or duplicate garden role {role}")
        return nodes[0]

    points = [tuple(map(int, point.split(","))) for point in region("house").attrib["points"].split()]
    edges = tuple(zip(points, (*points[1:], points[0]), strict=True))
    if any((x1 == x2) == (y1 == y2) for (x1, y1), (x2, y2) in edges):
        raise ValueError("House contour must have nonzero rectilinear segments")
    for role in ("bath", "garage", "shed", "garden", "greenhouse"):
        if any(int(region(role).attrib[key]) % 20 for key in ("x", "y", "width", "height")):
            raise ValueError("Building must align to the displayed grid")
    if any(x % 20 or y % 20 for x, y in points):
        raise ValueError("House vertices must align to the displayed grid")
    house: set[tuple[int, int]] = set()
    for row in range(height):
        scan_y = 25 + 10 * row
        crossings = sorted(
            x1 for (x1, y1), (x2, y2) in edges if x1 == x2 and min(y1, y2) < scan_y < max(y1, y2)
        )
        for left, end in zip(crossings[::2], crossings[1::2], strict=True):
            house.update((x, row) for x in range((left - 20) // 10, (end - 20) // 10))
    perimeter = sum(
        (x + dx, y + dy) not in house
        for x, y in house for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
    )
    vertices_perimeter = sum(abs(x1 - x2) + abs(y1 - y2) for (x1, y1), (x2, y2) in edges)
    if not house or vertices_perimeter != 10 * perimeter:
        raise ValueError("House contour and occupied cells disagree")

    bath, garage, shed, garden, greenhouse, pad = (
        rectangle(region(role)) for role in ("bath", "garage", "shed", "garden", "greenhouse", "pad")
    )
    if not greenhouse < garden:
        raise ValueError("Greenhouse must lie inside the garden")
    if not (any((width - 1, row) in pad for row in range((gate_start - 20) // 10, (gate_end - 20) // 10))
            and max(y for _, y in shed) < (gate_start - 20) // 10 <= min(y for _, y in garage)):
        raise ValueError("Garage and shed must be on opposite sides of the paved entrance")

    paving: set[tuple[int, int]] = set()
    for node in root.findall(".//*[@data-role='paving']"):
        if min(int(node.attrib[key]) for key in ("width", "height")) != 10:
            raise ValueError("Paving strips must be one metre wide")
        strip = rectangle(node)
        if paving & strip:
            raise ValueError("Paving strips overlap")
        paving.update(strip)
    occupied: set[tuple[int, int]] = set()
    for surface in (house, bath, garage, shed, garden, pad, paving):
        if surface & occupied or any(not (0 <= x < width and 0 <= y < height) for x, y in surface):
            raise ValueError("Garden objects overlap or extend beyond the plot")
        occupied.update(surface)

    areas = tuple(map(len, (house, bath, garage, shed)))
    plot = width * height
    if (areas != c["building_areas_m2"] or perimeter != 2 * cast(int, c["exposed_perimeter_edges"])
            or (len(paving), len(pad), plot) != (c["path_tiles"], c["pad_tiles"], c["plot_area_m2"])):
        raise ValueError("Rendered garden geometry differs from the immutable operands")
    labels = cast(Mapping[str, int], c["labels"])
    label_nodes = {node.attrib["data-label"]: node for node in root.findall(".//*[@data-label]")}
    if {role: node.text for role, node in label_nodes.items()} != {role: str(n) for role, n in labels.items()}:
        raise ValueError("Visible labels differ from the immutable labels")
    for role, surface in zip(("house", "bath", "garage", "shed", "garden", "greenhouse"),
                             (house, bath, garage, shed, garden - greenhouse, greenhouse), strict=True):
        node = label_nodes[role]
        if tuple((int(node.attrib[k]) - 20) // 10 for k in ("x", "y")) not in surface:
            raise ValueError(f"Label lies outside the visible {role} region")
    trees = region("orchard").findall(".//{*}circle")
    if len(trees) != 4:
        raise ValueError("Orchard symbol requires four trees")
    orchard_points = [
        *((int(tree.attrib["cx"]), int(tree.attrib["cy"])) for tree in trees),
        (int(label_nodes["orchard"].attrib["x"]), int(label_nodes["orchard"].attrib["y"])),
    ]
    left, right = max(x for x, _ in bath) + 1, min(x for x, _ in garage)
    first_row = min(y for _, y in bath) - 2
    for point_x, point_y in orchard_points:
        x, y = (point_x - 20) // 10, (point_y - 20) // 10
        if not (left <= x < right and first_row <= y < height and (x, y) not in occupied):
            raise ValueError("Orchard symbols must lie across from the house between bath and garage")
    return len(paving) + len(pad), perimeter, sum(areas), plot




class _Oracle:
    def validate_svg_bytes(self, scenario: ScenarioDraft, image: bytes) -> None:
        """Reject moved structures, changed labels, scale, or paving width."""
        if image != _svg(scenario.context):
            raise ValueError("SVG bytes do not match the immutable garden geometry")
        ElementTree.fromstring(image)

    def validate_scenario(self, scenario: ScenarioDraft) -> None:
        c = scenario.context
        if (c.get("template_id") != "SOSNOVKA-2025-1.1" or c.get("scenario_seed") != scenario.seed
                or c.get("grid_side_m") != 2):
            raise ValueError("Unverified garden topology or mismatched seed")
        if scenario.generator_version == VERSION and c.get("world_version") != VERSION:
            raise ValueError("Garden generator and plan versions differ")
        labels = cast(Mapping[str, int], c["labels"])
        if len(set(labels.values())) != len(labels) or set(labels.values()) != set(range(1, 8)):
            raise ValueError("Garden labels must be a unique source-verified mapping")
        heat = cast(Mapping[str, int], c["heat"])
        if scenario.generator_version in _MODERN_HEAT_VERSIONS:
            gas_hourly = int(heat["gas_m3_per_hour_tenths"]) * int(heat["gas_price_per_m3_tenths"])
            electric_hourly = int(heat["electric_kw_tenths"]) * int(heat["electric_price_per_kwh_tenths"])
            gas_upfront = int(heat["gas_heater_cost"]) + int(heat["gas_installation_cost"])
            electric_upfront = int(heat["electric_heater_cost"]) + int(heat["electric_installation_cost"])
        else:
            gas_hourly = int(heat["gas_hourly_cents"])
            electric_hourly = int(heat["electric_hourly_cents"])
            gas_upfront = int(heat["gas_upfront"])
            electric_upfront = int(heat["electric_upfront"])
        if gas_hourly >= electric_hourly:
            raise ValueError("Invalid heating rates")
        if (gas_upfront - electric_upfront) * 100 != (electric_hourly - gas_hourly) * int(heat["break_even_hours"]):
            raise ValueError("Heating figures do not break even")

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None:
        self.validate_scenario(scenario)
        if rendered.shared_context != _Renderer._shared_context(scenario):
            raise ValueError("Shared plan/table text differs from the immutable world")
        if (
            question.scenario_seed != scenario.seed
            or question.family_id != FAMILIES[question.position - 1]
        ):
            raise ValueError("Question family/seed mismatch")
        diverse = scenario.generator_version == VERSION
        total_tiles, perimeter, occupied, plot = (
            _visible_geometry(scenario) if diverse and question.position != 5 else (65, 36, 176, 600)
        )
        if diverse and question.position in (2, 3, 4):
            if question.solution_steps != _geometry_solution(scenario.context, question.position, question.canonical_answer):
                raise ValueError("Garden solutions differ from the visible plan")
        if question.position == 1:
            labels = cast(Mapping[str, int], scenario.context["labels"])
            expected = "".join(str(labels[k]) for k in ("house", "bath", "garage", "greenhouse"))
            if question.canonical_answer != expected:
                raise ValueError("Rendered object order differs from plan")
            if question.math_model.get("answer_grid") != {
                "columns": ("Жилой дом", "Баня", "Гараж", "Теплица"),
                "header": "Объект",
                "row": "Цифра на плане",
            }:
                raise ValueError("Garden matching grid differs from the requested object order")
            condition = question.condition.lower()
            shared = rendered.shared_context.lower()
            for term in (
                "дом", "бан", "гараж", "теплиц", "указанном порядке",
            ):
                if term not in condition:
                    raise ValueError("Identify wording does not match its answer order")
            for term in (
                "единственные ворота", "слева находится гараж", "справа — сарай",
                "напротив дома", "цифрой 6", "теплица расположена внутри огорода",
            ):
                if term not in shared:
                    raise ValueError("Shared garden narrative omits an identification clue")
        elif question.position == 2:
            pack = cast(int, scenario.context["tiles_per_pack"])
            if question.canonical_answer != str(ceil(Fraction(total_tiles, pack))):
                raise ValueError("Tile pack answer mismatch")
            if not all(value in question.condition for value in ("2 м", "1 м", f"В пачке {pack} плиток")):
                raise ValueError("Tile values in text differ from plan")
        elif question.position == 3:
            if question.canonical_answer != str(perimeter):
                raise ValueError("Perimeter mismatch")
            if "2 м" not in question.condition or "внешнего контура" not in question.condition:
                raise ValueError("Perimeter wording or scale mismatch")
        elif question.position == 4:
            percentage = int(Fraction(100 * occupied, plot) + Fraction(1, 2))
            if question.canonical_answer != str(percentage):
                raise ValueError("Building percentage mismatch")
            if not all(
                value in question.condition for value in ("четыре бежевых", "2 м", "целого")
            ):
                raise ValueError("Building areas or denominator differ from plan")
        elif question.position == 5:
            heat = cast(Mapping[str, int], scenario.context["heat"])
            if scenario.generator_version in HEAT_TABLE_ONLY_VERSIONS:
                answer, expected_steps = _modern_heat_solution(heat)
                if question.canonical_answer != answer:
                    raise ValueError("Heating answer mismatch")
                visible_operands = (
                    str(heat["gas_heater_cost"]), str(heat["gas_installation_cost"]),
                    str(heat["electric_heater_cost"]), str(heat["electric_installation_cost"]),
                    f"{heat['gas_m3_per_hour_tenths'] / 10:.1f}",
                    f"{heat['gas_price_per_m3_tenths'] / 10:.1f}",
                    f"{heat['electric_kw_tenths'] / 10:.1f}",
                    f"{heat['electric_price_per_kwh_tenths'] / 10:.1f}",
                )
                if any(
                    value in rendered.shared_context or value in question.condition
                    for value in visible_operands
                ):
                    raise ValueError("Heating operands must be shown only in the attached table")
                if "таблицу исходных данных" not in question.condition:
                    raise ValueError("Heating question must point to its presented data table")
                if question.solution_steps != expected_steps:
                    raise ValueError("Heating solution steps disagree with the source operands")
            elif scenario.generator_version == PREVIOUS_VERSION:
                gas_row = search(
                    r"Газ: котёл (\d+) руб\., монтаж (\d+) руб\.; ([\d.]+) м³/ч, ([\d.]+) руб\./м³",
                    rendered.shared_context,
                )
                electric_row = search(
                    r"Электричество: котёл (\d+) руб\., монтаж (\d+) руб\.; ([\d.]+) кВт, ([\d.]+) руб\./\(кВт·ч\)",
                    rendered.shared_context,
                )
                if gas_row is None or electric_row is None:
                    raise ValueError("Heating table rows are missing or malformed")
                gas_initial = int(gas_row[1]) + int(gas_row[2])
                electric_initial = int(electric_row[1]) + int(electric_row[2])
                gas_rate = Fraction(gas_row[3]) * Fraction(gas_row[4]) * 100
                electric_rate = Fraction(electric_row[3]) * Fraction(electric_row[4]) * 100
                if gas_rate.denominator != 1 or electric_rate.denominator != 1:
                    raise ValueError("Displayed hourly costs must resolve to whole cents")
                gas_hourly = gas_rate.numerator
                electric_hourly = electric_rate.numerator
                if gas_hourly >= electric_hourly or gas_initial <= electric_initial:
                    raise ValueError("Displayed heating data cannot produce a positive break-even time")
                numerator = (gas_initial - electric_initial) * 100
                denominator = electric_hourly - gas_hourly
                if numerator % denominator:
                    raise ValueError("Displayed heating data has no whole-hour break-even point")
                parsed_answer = numerator // denominator
                if question.canonical_answer != str(parsed_answer):
                    raise ValueError("Heating answer mismatch")
                expected_operands = (
                    str(heat["gas_heater_cost"]), str(heat["gas_installation_cost"]),
                    str(heat["electric_heater_cost"]), str(heat["electric_installation_cost"]),
                    f"{heat['gas_m3_per_hour_tenths'] / 10:.1f}",
                    f"{heat['gas_price_per_m3_tenths'] / 10:.1f}",
                    f"{heat['electric_kw_tenths'] / 10:.1f}",
                    f"{heat['electric_price_per_kwh_tenths'] / 10:.1f}",
                )
                displayed_operands = (*gas_row.groups(), *electric_row.groups())
                if not all(value in rendered.shared_context for value in expected_operands) or not displayed_operands:
                    raise ValueError("Heating table differs from source operands")
                if any(value in rendered.shared_context or value in question.condition for value in ("7.84", "20.58")):
                    raise ValueError("Derived hourly costs must not be supplied as ready values")
                def rubles(cents: int) -> str:
                    return f"{cents // 100}.{cents % 100:02d}"

                expected_steps = (
                    f"Начальные затраты: газ {gas_row[1]} + {gas_row[2]} = {gas_initial} руб.; "
                    f"электричество {electric_row[1]} + {electric_row[2]} = {electric_initial} руб.",
                    f"За час: газ {gas_row[3]} × {gas_row[4]} = {rubles(gas_hourly)} руб.; "
                    f"электричество {electric_row[3]} × {electric_row[4]} = "
                    f"{rubles(electric_hourly)} руб.",
                    f"Разница начальных затрат — {gas_initial - electric_initial} руб., "
                    f"экономия газа — {rubles(electric_hourly - gas_hourly)} руб./ч. "
                    f"Ответ: {parsed_answer} ч.",
                )
                if question.solution_steps != expected_steps:
                    raise ValueError("Heating solution steps disagree with the displayed table")
            else:
                if question.canonical_answer != str(heat["break_even_hours"]):
                    raise ValueError("Heating answer mismatch")
                visible = (str(heat["gas_upfront"]), str(heat["electric_upfront"]),
                           f"{heat['gas_hourly_cents'] / 100:.2f}", f"{heat['electric_hourly_cents'] / 100:.2f}")
                if not all(value in question.condition for value in visible):
                    raise ValueError("Heating table differs from condition")

    def validate_bundle(
        self,
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        rendered: RenderedScenario,
    ) -> None:
        if tuple(q.position for q in questions) != (1, 2, 3, 4, 5):
            raise ValueError("Garden bundle must be a coherent ordered five")
        for q in questions:
            self.validate_question(scenario, q, rendered)
        image = _svg(scenario.context)
        self.validate_svg_bytes(scenario, image)
        root = ElementTree.fromstring(image)
        if scenario.generator_version == VERSION:
            return
        if scenario.generator_version in SOURCE_PLAN_VERSIONS:
            self._validate_current_geometry(scenario, questions, root)
            return
        if (
            len(root.findall(".//*[@data-role='house']")) != 1
            or len(root.findall(".//*[@data-role='greenhouse']")) != 1
        ):
            raise ValueError("Garden plan is missing a required shape")
        labels = {el.attrib["data-label"]: el.text for el in root.findall(".//*[@data-label]")}
        expected = cast(Mapping[str, int], scenario.context["labels"])
        if any(labels.get(role) != str(value) for role, value in expected.items()):
            raise ValueError("SVG labels differ from world model")
        paving = root.findall(".//*[@data-role='paving']")
        pad = root.find(".//*[@data-role='pad']")
        if pad is None or not paving:
            raise ValueError("Missing paved surfaces")
        def rectangle(node: ElementTree.Element) -> tuple[int, int, int, int]:
            x, y, w, h = (int(node.attrib[key]) for key in ("x", "y", "width", "height"))
            return x, y, x + w, y + h

        surfaces = [rectangle(node) for node in (*paving, pad)]
        occupied = [
            rectangle(node)
            for role in ("bath", "garage", "shed", "garden")
            for node in root.findall(f".//*[@data-role='{role}']")
        ]
        area = 0
        for i, (x1, y1, x2, y2) in enumerate(surfaces):
            if not (20 <= x1 < x2 <= 320 and 20 <= y1 < y2 <= 220):
                raise ValueError("Paving extends beyond the plot")
            for a, b, c, d in (*surfaces[:i], *occupied):
                if max(x1, a) < min(x2, c) and max(y1, b) < min(y2, d):
                    raise ValueError("Paving overlaps another visible surface")
            area += (x2 - x1) * (y2 - y1)
        if area != 6500:
            raise ValueError("Visible paving must cover 65 square metres")
        image_text = image.decode("utf-8")
        if "2 м" not in image_text or "1 м" not in image_text:
            raise ValueError("SVG scale/path width labels missing")
        if root.attrib.get("viewBox") != "0 0 400 300":
            raise ValueError("SVG scale has changed")
        # Independent measurements in SVG units (10 units = 1 metre).
        plot_area = (320 - 20) * (220 - 20) / 100
        house_shape = root.find(".//*[@data-role='house']")
        if house_shape is None:
            raise ValueError("Missing house polygon")
        tokens = findall(r"[MHVZ]|\d+", house_shape.attrib["d"])
        if len(tokens) < 6 or tokens[0] != "M" or tokens[-1] != "Z":
            raise ValueError("House must be a closed rectilinear polygon")
        x, y = int(tokens[1]), int(tokens[2])
        house = [(x, y)]
        for command, coordinate in zip(tokens[3:-1:2], tokens[4:-1:2], strict=True):
            if command == "H":
                x = int(coordinate)
            elif command == "V":
                y = int(coordinate)
            else:
                raise ValueError("Unexpected house segment")
            house.append((x, y))
        area2 = sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(house, (*house[1:], house[0]), strict=True)
        )
        house_area = abs(area2) / 2 / 100
        perimeter = (
            sum(
                abs(x2 - x1) + abs(y2 - y1)
                for (x1, y1), (x2, y2) in zip(house, (*house[1:], house[0]), strict=True)
            )
            / 10
        )
        if plot_area != scenario.context["plot_area_m2"]:
            raise ValueError("Plot dimensions and displayed area are inconsistent")
        if house_area != 68 or perimeter != 36:
            raise ValueError("House polygon area/perimeter differ from the task model")
        building_areas = [house_area]
        for role in ("bath", "garage", "shed"):
            building = root.find(f".//*[@data-role='{role}']")
            if building is None:
                raise ValueError("Missing building required for the percentage question")
            x1, y1, x2, y2 = rectangle(building)
            building_areas.append((x2 - x1) * (y2 - y1) / 100)
        if tuple(building_areas) != scenario.context["building_areas_m2"]:
            raise ValueError("Building areas do not match their visible dimensions")
        if str(round(sum(building_areas) / plot_area * 100)) != questions[3].canonical_answer:
            raise ValueError("Visible plan gives a different percentage")
        garden_rect = (80, 100, 200, 200)
        greenhouse_rect = (120, 130, 150, 170)
        if not (
            garden_rect[0] <= greenhouse_rect[0]
            and garden_rect[1] <= greenhouse_rect[1]
            and greenhouse_rect[2] <= garden_rect[2]
            and greenhouse_rect[3] <= garden_rect[3]
        ):
            raise ValueError("Greenhouse must be contained in the garden")

    @staticmethod
    def _validate_current_geometry(
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        root: ElementTree.Element,
    ) -> None:
        if root.attrib.get("viewBox") != "0 0 400 300":
            raise ValueError("Source plan grid scale has changed")
        if scenario.context["plot_area_m2"] != 600:
            raise ValueError("Source plot area must be 600 m²")

        def rect(role: str) -> tuple[int, int, int, int]:
            node = root.find(f".//*[@data-role='{role}']")
            if node is None or not node.tag.endswith("rect"):
                raise ValueError(f"Missing source-plan rectangle: {role}")
            x, y, width, height = (int(node.attrib[key]) for key in ("x", "y", "width", "height"))
            return x, y, x + width, y + height

        expected_rects = {
            "shed": (260, 20, 320, 60),
            "garage": (240, 160, 320, 220),
            "bath": (20, 160, 80, 220),
            "garden": (20, 20, 120, 140),
            "greenhouse": (40, 40, 100, 60),
            "pad": (280, 60, 320, 160),
        }
        if any(rect(role) != bounds for role, bounds in expected_rects.items()):
            raise ValueError("Building or paved-area position differs from the source grid")
        house = root.find(".//*[@data-role='house']")
        if house is None or not house.tag.endswith("polygon"):
            raise ValueError("Missing source house polygon")
        points: list[tuple[int, int]] = []
        for point in house.attrib["points"].split():
            coordinates = point.split(",")
            if len(coordinates) != 2:
                raise ValueError("Source house polygon has a malformed point")
            points.append((int(coordinates[0]), int(coordinates[1])))
        if points != [(140, 40), (240, 40), (240, 100), (180, 100), (180, 120), (140, 120)]:
            raise ValueError("House vertices differ from the source grid")

        def polygon_measure(vertices: list[tuple[int, int]]) -> tuple[int, int]:
            area2 = sum(
                x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(vertices, (*vertices[1:], vertices[0]), strict=True)
            )
            perimeter = sum(
                abs(x2 - x1) + abs(y2 - y1)
                for (x1, y1), (x2, y2) in zip(vertices, (*vertices[1:], vertices[0]), strict=True)
            )
            return abs(area2) // 2 // 100, perimeter // 10

        house_area, house_perimeter = polygon_measure(points)
        building_areas = {
            role: ((x2 - x1) * (y2 - y1)) // 100
            for role, (x1, y1, x2, y2) in (
                (role, rect(role)) for role in ("bath", "garage", "shed")
            )
        }
        areas = {"house": house_area, **building_areas}
        if areas != {"house": 68, "bath": 36, "garage": 48, "shed": 24}:
            raise ValueError("Source-plan building areas do not match the task model")
        if house_perimeter != 36:
            raise ValueError("Source-plan house perimeter must be 36 m")
        if tuple(areas[key] for key in ("house", "bath", "garage", "shed")) != cast(
            tuple[int, ...], scenario.context["building_areas_m2"]
        ):
            raise ValueError("Building area snapshot differs from visible source plan")
        plot_area_m2 = cast(int, scenario.context["plot_area_m2"])
        if str(round(sum(areas.values()) / plot_area_m2 * 100)) != questions[3].canonical_answer:
            raise ValueError("Displayed source plan gives a different building percentage")

        paving = [
            (
                int(node.attrib["x"]), int(node.attrib["y"]),
                int(node.attrib["x"]) + int(node.attrib["width"]),
                int(node.attrib["y"]) + int(node.attrib["height"]),
            )
            for node in root.findall(".//*[@data-role='paving']")
        ]
        if paving != [(60, 140, 280, 150), (150, 120, 160, 140), (60, 150, 70, 160)]:
            raise ValueError("Path strips differ from source plan")
        path_area_m2 = sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in paving) // 100
        pad_bounds = rect("pad")
        pad_area_m2 = (pad_bounds[2] - pad_bounds[0]) * (pad_bounds[3] - pad_bounds[1]) // 100
        if (path_area_m2, pad_area_m2, path_area_m2 + pad_area_m2) != (25, 40, 65):
            raise ValueError("Rendered paths and pad do not match the source tile count")
        orchard = root.find(".//*[@data-role='orchard']")
        if orchard is None or orchard.attrib.get("data-grid-bounds") != "3,7,11,10":
            raise ValueError("Orchard position differs from the source grid")
        for circle in orchard.findall(".//{*}circle"):
            x, y, radius = (int(circle.attrib[key]) for key in ("cx", "cy", "r"))
            if not (80 <= x - radius and x + radius <= 240 and 160 <= y - radius and y + radius <= 220):
                raise ValueError("Orchard symbol lies outside the source orchard region")
        garden = rect("garden")
        greenhouse = rect("greenhouse")
        if not (
            garden[0] <= greenhouse[0] and garden[1] <= greenhouse[1]
            and greenhouse[2] <= garden[2] and greenhouse[3] <= garden[3]
        ):
            raise ValueError("Greenhouse must be contained in the source garden")


def build_adapter(*, enabled_families: frozenset[str] = frozenset()) -> StoryAdapter:
    supported_families = frozenset(FAMILIES)
    unknown = enabled_families - supported_families
    if unknown:
        raise ValueError(f"Cannot enable unsupported GARDEN families: {sorted(unknown)}")
    policy: AnswerPolicy = _Policy()
    families = tuple(
        FamilyRegistration(
            fid,
            i,
            FamilyStatus.ENABLED_CANDIDATE,
            policy.policy_id,
            policy.version,
            enabled=fid in enabled_families,
            source_ids=(SOURCE_IDS[i - 1],),
        )
        for i, fid in enumerate(FAMILIES, 1)
    )
    # The non-selected candidate structures remain explicitly unavailable.
    families += tuple(
        FamilyRegistration(
            fid,
            pos,
            status,
            policy.policy_id,
            policy.version,
            enabled=False,
            source_ids=((source,) if source else ()),
        )
        for fid, pos, source, status in (
            ("GARDEN-03-AREA-BUILDING", 3, "366579", FamilyStatus.ENABLED_CANDIDATE),
            ("GARDEN-05-DISTANCE-ORTHOGONAL", 4, "408425", FamilyStatus.ENABLED_CANDIDATE),
            ("GARDEN-06-DISTANCE-DIAGONAL", 4, "366581", FamilyStatus.ENABLED_CANDIDATE),
            ("GARDEN-08-PERCENT-GREENHOUSE", 4, "408433", FamilyStatus.ENABLED_CANDIDATE),
            ("GARDEN-10-PAINT-CHEAPEST", 5, "408450", FamilyStatus.RESEARCH_ONLY),
            ("GARDEN-11-OPEN-SOIL", 3, "408430", FamilyStatus.BLOCKED),
            ("GARDEN-12-PERCENT-AREA-DIFF", 4, "", FamilyStatus.RESEARCH_ONLY),
        )
    )
    adapter = type(
        "GardenAdapter",
        (),
        {
            "story_code": "GARDEN",
            "generator": _Generator(),
            "question_builder": _Builder(),
            "independent_oracle": _Oracle(),
            "renderer": _Renderer(),
            "answer_policies": MappingProxyType({(policy.policy_id, policy.version): policy}),
            "family_registry": families,
        },
    )()
    return cast(StoryAdapter, adapter)
