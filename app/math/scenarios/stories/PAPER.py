"""Deterministic, source-bounded PAPER adapter for OGE positions 1–5.

All generated conditions are analogues of the catalog structures listed in
``specs/coverage/OGE15_PAPER_COVERAGE.md``.  The adapter deliberately keeps the
area and paper-mass families disabled because the research records two
mathematically valid, conflicting interpretations for each.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from math import isqrt
from random import Random
from types import MappingProxyType

from PIL import Image, ImageDraw

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

GENERATOR_VERSION = "paper-v5"
WORLD_VERSION = "paper-world-v2"
ANSWER_POLICY_VERSION = "1"
RATIO_POLICY_VERSION = "2"

# Rounded ISO 216 dimensions in millimetres.  The order is always long, short.
DIMENSIONS_MM: Mapping[int, tuple[int, int]] = MappingProxyType(
    {
        0: (1189, 841),
        1: (841, 594),
        2: (594, 420),
        3: (420, 297),
        4: (297, 210),
        5: (210, 148),
        6: (148, 105),
        7: (105, 74),
    }
)

_ROUNDING_OPTIONS = tuple(
    (index, side, multiple)
    for index, sizes in DIMENSIONS_MM.items()
    for side, value in zip(("long", "short"), sizes, strict=True)
    for multiple in (5, 10)
    if value % multiple
)
# Only reconstruct a larger sheet where doubling the shorter side of the
# next format reproduces the rounded ISO dimensions exactly.
_DIAGONAL_FORMATS = tuple(
    index
    for index in range(7)
    if DIMENSIONS_MM[index]
    == (
        2 * DIMENSIONS_MM[index + 1][1],
        DIMENSIONS_MM[index + 1][0],
    )
)
_FONT_SIZES = range(8, 25)
_PRECISION_NAMES = {1: "десятых", 2: "сотых"}
_FONT_TRANSITIONS = ((4, 3), (3, 4))


_SOURCE_IDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "PAPER-F01": ("408268", "SPB-2025-2502"),
        "PAPER-F02": ("408281", "408284"),
        "PAPER-F03": ("408300", "408313"),
        "PAPER-F04": ("408314",),
        "PAPER-F06": ("408320",),
        "PAPER-F07": ("408333", "408343", "460960"),
    }
)

_ALL_SOURCE_IDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        **_SOURCE_IDS,
        "PAPER-F05": ("no_catalog_task_id",),
        "PAPER-F08": ("408294",),
        "PAPER-F09": ("408323", "408331"),
    }
)


def _static_diagram_png() -> bytes:
    """Render the fixed A0–A5 vector specification as PNG using Pillow."""
    image = Image.new("RGB", (960, 640), "white")
    draw = ImageDraw.Draw(image)
    ink = (23, 50, 77)
    # Adjacent rectangles have half the area and an approximately √2 side ratio.
    rectangles = (
        (30, 50, 390, 305, "A0"),
        (430, 50, 685, 230, "A1"),
        (720, 50, 900, 177, "A2"),
        (730, 250, 857, 340, "A3"),
        (590, 390, 680, 454, "A4"),
        (405, 500, 469, 545, "A5"),
    )
    for left, top, right, bottom, label in rectangles:
        draw.rectangle((left, top, right, bottom), outline=ink, width=5)
        _draw_bitmap_text(draw, (left + 6, top + 6), label, 4, ink)
    arrows = (
        ((390, 180), (420, 140), ((412, 153), (413, 137), (427, 143))),
        ((685, 140), (720, 112), ((710, 120), (712, 105), (725, 115))),
        ((810, 177), (793, 250), ((786, 238), (800, 240), (793, 255))),
        ((730, 340), (680, 390), ((688, 375), (694, 387), (680, 395))),
        ((590, 454), (469, 500), ((480, 487), (484, 500), (469, 504))),
    )
    for start, end, arrowhead in arrows:
        draw.line((start, end), fill=ink, width=4)
        draw.polygon(arrowhead, fill=ink)
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


# A small built-in 5x7 glyph set keeps the table independent of host fonts and
# guarantees Cyrillic headings in the Linux container as well as local runs.
_GLYPHS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "А": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
        "Д": ("00110", "01010", "01010", "01010", "10001", "11111", "10001"),
        "Е": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
        "И": ("10001", "10011", "10101", "10101", "11001", "10001", "10001"),
        "К": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
        "Л": ("00111", "01001", "01001", "01001", "10001", "10001", "10001"),
        "М": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
        "Н": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
        "О": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
        "Р": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
        "С": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
        "Т": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
        "Ш": ("10101", "10101", "10101", "10101", "10101", "10101", "11111"),
        "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
        "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
        "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
        "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
        "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
        "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
        "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
        "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
        "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
        "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
        "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
        " ": ("00000",) * 7,
        "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
        ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
        "м": ("00000", "00000", "10101", "10101", "10101", "10101", "11011"),
        ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    }
)


def _draw_bitmap_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    scale: int,
    fill: tuple[int, int, int],
) -> None:
    x, y = xy
    for character in text:
        glyph = _GLYPHS.get(character)
        if glyph is None:
            raise ValueError(f"Unsupported table glyph: {character!r}")
        for row, line in enumerate(glyph):
            for column, pixel in enumerate(line):
                if pixel == "1":
                    draw.rectangle(
                        (
                            x + column * scale,
                            y + row * scale,
                            x + (column + 1) * scale - 1,
                            y + (row + 1) * scale - 1,
                        ),
                        fill=fill,
                    )
        x += 6 * scale


_DIAGRAM_PNG = _static_diagram_png()
_DIAGRAM_DIGEST = sha256(_DIAGRAM_PNG).hexdigest()


@lru_cache(maxsize=1024)
def _table_png(rows: tuple[tuple[str, int, int], ...], *, labeled: bool = True) -> bytes:
    """Render the four-row dimensions table without host-font dependencies."""
    if len(rows) != 4 or len({row[0] for row in rows}) != 4:
        raise ValueError("PAPER table requires four distinct formats")
    image = Image.new("RGB", (1024, 520), "white")
    draw = ImageDraw.Draw(image)
    ink = (23, 50, 77)
    pale = (232, 241, 248)
    x0, y0, width, header_h, row_h = 24, 24, 976, 112, 88
    col_widths = (270, 353, 353)
    draw.rectangle((x0, y0, x0 + width, y0 + header_h), fill=pale)
    headings = ("НОМЕР ЛИСТА" if labeled else "СТРОКА", "ДЛИНА (мм)", "ШИРИНА (мм)")
    x = x0
    for heading, col_width in zip(headings, col_widths, strict=True):
        _draw_bitmap_text(draw, (x + 20, y0 + 44), heading, 3, ink)
        x += col_width
    y = y0 + header_h
    for index, (label, long_mm, short_mm) in enumerate(rows, start=1):
        x = x0
        draw.rectangle((x0, y, x0 + width, y + row_h), fill="white")
        values = (f"{index}. {label}" if labeled else str(index), str(long_mm), str(short_mm))
        for value, col_width in zip(values, col_widths, strict=True):
            draw.rectangle((x, y, x + col_width, y + row_h), outline=ink, width=2)
            _draw_bitmap_text(draw, (x + 40, y + 24), value, 5 if value.startswith("A") else 6, ink)
            x += col_width
        y += row_h
    # Draw the outer boundary after cells so no row/column edge is clipped.
    draw.rectangle((x0, y0, x0 + width, y0 + header_h + 4 * row_h), outline=ink, width=3)
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def _round_multiple_half_up(value: int, multiple: int) -> int:
    if value < 0 or multiple <= 0:
        raise ValueError("Rounding requires a non-negative value and positive multiple")
    quotient, remainder = divmod(value, multiple)
    return (quotient + (2 * remainder >= multiple)) * multiple


def _round_ratio(numerator: int, denominator: int, places: int = 1) -> str:
    if numerator < 0 or denominator <= 0:
        raise ValueError("Ratio must be non-negative with a positive denominator")
    factor = 10**places
    scaled, remainder = divmod(numerator * factor, denominator)
    whole, fraction = divmod(scaled + (2 * remainder >= denominator), factor)
    return f"{whole},{fraction:0{places}d}"


def _decimal_round_ratio(numerator: int, denominator: int, places: int = 1) -> str:
    value = Decimal(numerator) / Decimal(denominator)
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return str(rounded).replace(".", ",")


def _decimal_round_sqrt_ratio(square_sum: int, denominator: int, places: int = 1) -> str:
    value = Decimal(square_sum).sqrt() / Decimal(denominator)
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return str(rounded).replace(".", ",")


def _round_sqrt_ratio(square_sum: int, denominator: int, places: int = 1) -> str:
    """Round sqrt(square_sum)/denominator using exact integer comparisons."""
    factor = 10**places
    scaled_square = square_sum * factor**2
    scaled_floor = isqrt(scaled_square) // denominator
    rounds_up = 4 * scaled_square >= (2 * scaled_floor + 1) ** 2 * denominator**2
    whole, fraction = divmod(scaled_floor + rounds_up, factor)
    return f"{whole},{fraction:0{places}d}"


def _font_answer(old_pt: int, source_long: int, target_long: int) -> str:
    scaled = Decimal(old_pt * target_long) / Decimal(source_long)
    return str(int(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def _make_world(seed: int, ratio_family: str | None = None) -> dict[str, object]:
    rng = Random(seed ^ 0x5041504552)
    source_index, target_index = sorted(rng.sample(range(7), 2))
    source_count = rng.randint(1, 5)
    round_format, round_side, round_multiple = rng.choice(_ROUNDING_OPTIONS)
    default_ratio_family = rng.choice(("PAPER-F04", "PAPER-F06"))
    ratio_kind = ratio_family or default_ratio_family
    ratio_index = rng.choice(
        tuple(DIMENSIONS_MM) if ratio_kind == "PAPER-F04" else _DIAGONAL_FORMATS
    )
    ratio_places = rng.choice((1, 2))
    diagonal_side = rng.choice(("short", "long"))
    font_source, font_target = rng.choice(_FONT_TRANSITIONS)
    font_old_pt = rng.choice(_FONT_SIZES)

    needed = {font_source, font_target, round_format}
    needed.add(ratio_index if ratio_kind == "PAPER-F04" else ratio_index + 1)
    row_formats = sorted(needed)
    row_formats.extend(rng.sample(sorted(DIMENSIONS_MM.keys() - needed), 4 - len(needed)))
    rng.shuffle(row_formats)
    rows = [(f"A{index}", *DIMENSIONS_MM[index]) for index in row_formats]
    target_order = rng.sample(row_formats, 4)

    return {
        "seed": seed,
        "world_version": WORLD_VERSION,
        "rows": rows,
        "target_order": [f"A{index}" for index in target_order],
        "asset_manifest": {
            "diagram_asset_id": "paper-a0-a5-folding-v1",
            "diagram_sha256": _DIAGRAM_DIGEST,
            "table_asset_id": "paper-dimensions-v2",
        },
        "questions": {
            "2": {
                "source_index": source_index,
                "target_index": target_index,
                "source_count": source_count,
            },
            "3": {
                "format_index": round_format,
                "side": round_side,
                "multiple": round_multiple,
            },
            "4": {
                "family_id": ratio_kind,
                "format_index": ratio_index,
                "decimal_places": ratio_places,
                "denominator_side": diagonal_side if ratio_kind == "PAPER-F06" else "long",
            },
            "5": {
                "source_index": font_source,
                "target_index": font_target,
                "old_pt": font_old_pt,
            },
        },
    }


class PaperGenerator:
    def generate_scenario(self, seed: int) -> ScenarioDraft:
        return self._generate(seed)

    def generate_scenario_for_family(
        self, seed: int, position: int, family_id: str
    ) -> ScenarioDraft:
        return self._generate(seed, family_id if position == 4 else None)

    def _generate(self, seed: int, ratio_family: str | None = None) -> ScenarioDraft:
        context = _make_world(seed, ratio_family)
        return ScenarioDraft(
            story_code="PAPER",
            seed=seed,
            generator_version=GENERATOR_VERSION,
            compatibility_matrix_version=WORLD_VERSION,
            context=context,  # type: ignore[arg-type]
            provenance=tuple(
                f"{family}:{source_id}:generated_analogue"
                for family, source_ids in _SOURCE_IDS.items()
                for source_id in source_ids
            ),
        )


class PaperQuestionBuilder:
    def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft:
        context = scenario.context
        rows = _get_rows(context)
        questions = context.get("questions")
        if not isinstance(questions, Mapping):
            raise ValueError("PAPER scenario is missing its question parameters")
        if position == 1:
            return _build_mapping_question(scenario, rows)
        raw = questions.get(str(position))
        if not isinstance(raw, Mapping):
            raise ValueError("PAPER scenario is missing a supported question position")
        if position == 2:
            return _build_count_question(scenario, raw)
        if position == 3:
            return _build_rounding_question(scenario, raw)
        if position == 4:
            return _build_ratio_question(scenario, raw)
        if position == 5:
            return _build_font_question(scenario, raw)
        raise ValueError("PAPER question position must be from 1 through 5")


def _new_question(
    scenario: ScenarioDraft,
    position: int,
    family_id: str,
    condition: str,
    canonical_answer: str,
    policy_id: str,
    model: Mapping[str, object],
    solution_steps: tuple[str, ...],
) -> QuestionDraft:
    question_model = {
        **model,
        "source_ids": list(_SOURCE_IDS[family_id]),
        "content_kind": "generated_analogue",
    }
    policy_version = (
        RATIO_POLICY_VERSION if family_id in {"PAPER-F04", "PAPER-F06"} else ANSWER_POLICY_VERSION
    )
    return QuestionDraft(
        position=position,
        scenario_seed=scenario.seed,
        family_id=family_id,
        generator_version=scenario.generator_version,
        condition=condition,
        answer_policy_id=policy_id,
        answer_policy_version=policy_version,
        canonical_answer=canonical_answer,
        hints=(
            "Вспомните, как соседние форматы листа связаны друг с другом.",
            "Сначала выпишите нужные размеры и единицы, затем выполните указанное действие.",
        ),
        solution_steps=solution_steps,
        math_model=question_model,  # type: ignore[arg-type]
    )


def _build_mapping_question(
    scenario: ScenarioDraft, rows: tuple[tuple[str, int, int], ...]
) -> QuestionDraft:
    order = _get_target_order(scenario.context)
    row_by_format = {row[0]: index for index, row in enumerate(rows, start=1)}
    answer = "".join(str(row_by_format[label]) for label in order)
    condition = (
        "Соотнесите форматы бумаги с размерами в общей таблице. "
        f"Форматы в указанном порядке: {', '.join(order)}. "
        "Запишите номера соответствующих строк четырьмя цифрами, без пробелов."
    )
    return _new_question(
        scenario,
        1,
        "PAPER-F01",
        condition,
        answer,
        "paper.mapping_four",
        {
            "target_order": list(order),
            "rows": [list(row) for row in rows],
            "answer_grid": {
                "columns": list(order),
                "header": "Формат",
                "row": "Номер строки",
            },
        },
        (
            "Площадь A0 близка к 1 000 000 мм². У каждого следующего формата "
            "площадь примерно вдвое меньше.",
        )
        + tuple(
            f"Строка {index}: {length} × {width} = {length * width} мм², это формат {label}."
            for index, (label, length, width) in enumerate(rows, 1)
        )
        + (f"В заданном порядке номера строк образуют код {answer}.",),
    )


def _get_rows(context: Mapping[str, object]) -> tuple[tuple[str, int, int], ...]:
    raw_rows = context.get("rows")
    if not isinstance(raw_rows, tuple | list):
        raise ValueError("PAPER scenario table rows are missing")
    rows: list[tuple[str, int, int]] = []
    for row in raw_rows:
        if not isinstance(row, tuple | list) or len(row) != 3:
            raise ValueError("PAPER scenario table row is malformed")
        label, long_mm, short_mm = row
        if (
            not isinstance(label, str)
            or not isinstance(long_mm, int)
            or not isinstance(short_mm, int)
        ):
            raise ValueError("PAPER scenario table contains invalid cell types")
        rows.append((label, long_mm, short_mm))
    return tuple(rows)


def _get_target_order(context: Mapping[str, object]) -> tuple[str, ...]:
    raw_order = context.get("target_order")
    if not isinstance(raw_order, tuple | list) or any(not isinstance(x, str) for x in raw_order):
        raise ValueError("PAPER format order is malformed")
    return tuple(raw_order)


def _get_int(model: Mapping[str, object], key: str) -> int:
    value = model.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"PAPER parameter {key} must be an integer")
    return value


def _build_count_question(scenario: ScenarioDraft, model: Mapping[str, object]) -> QuestionDraft:
    i, j = _get_int(model, "source_index"), _get_int(model, "target_index")
    if not 0 <= i < j <= 6:
        raise ValueError("PAPER sheet-count indices must satisfy 0 <= i < j <= 6")
    count = _get_int(model, "source_count")
    answer = str(count * 2 ** (j - i))
    condition = (
        f"Есть листы формата A{i} в количестве {count} шт. Каждый лист разрезают "
        f"пополам и продолжают разрезать полученные листы до формата A{j}. "
        f"Сколько листов формата A{j} получится всего?"
    )
    return _new_question(
        scenario,
        2,
        "PAPER-F02",
        condition,
        answer,
        "paper.sheet_count",
        {"source_index": i, "target_index": j, "source_count": count},
        (
            f"От A{i} до A{j} выполняется {j - i} последовательных делений пополам.",
            f"При каждом делении один лист даёт два листа следующего формата: "
            f"2^{j - i} = {2 ** (j - i)} листов из одного.",
            f"Всего: {count} · {2 ** (j - i)} = {answer}.",
        ),
    )


def _build_rounding_question(scenario: ScenarioDraft, model: Mapping[str, object]) -> QuestionDraft:
    index, multiple = _get_int(model, "format_index"), _get_int(model, "multiple")
    side = model.get("side")
    rows = _get_rows(scenario.context)
    row = next((row for row in rows if row[0] == f"A{index}"), None)
    if (index, side, multiple) not in _ROUNDING_OPTIONS or row is None:
        raise ValueError("PAPER rounding parameters are outside the supported dimension cases")
    exact_value = row[1] if side == "long" else row[2]
    quantity = "длина" if side == "long" else "ширина"
    requested = "длину" if side == "long" else "ширину"
    answer = str(_round_multiple_half_up(exact_value, multiple))
    condition = (
        f"Найдите {requested} листа бумаги формата A{index}. "
        f"Ответ дайте в миллиметрах и округлите до ближайшего целого числа, кратного {multiple}."
    )
    if 2 * (exact_value % multiple) == multiple:
        condition += " Если два кратных одинаково близки, выберите большее."
    return _new_question(
        scenario,
        3,
        "PAPER-F03",
        condition,
        answer,
        "paper.rounded_mm",
        {"format_index": index, "side": side, "value_mm": exact_value, "multiple": multiple},
        (
            f"По общей таблице {quantity} листа A{index} равна {exact_value} мм.",
            f"Округляем до кратного {multiple}: {exact_value} мм → {answer} мм.",
        ),
    )


def _build_ratio_question(scenario: ScenarioDraft, model: Mapping[str, object]) -> QuestionDraft:
    family_id = model.get("family_id")
    index = _get_int(model, "format_index")
    places = _get_int(model, "decimal_places")
    precision = _PRECISION_NAMES[places]
    if family_id == "PAPER-F04":
        row = next((row for row in _get_rows(scenario.context) if row[0] == f"A{index}"), None)
        if row is None or row[1:] != DIMENSIONS_MM[index]:
            raise ValueError("PAPER F04 requires the requested dimensions in the shared table")
        long_mm, short_mm = row[1], row[2]
        answer = _round_ratio(short_mm, long_mm, places)
        condition = (
            f"Найдите отношение длины меньшей стороны листа формата A{index} к большей. "
            f"Ответ округлите до {precision}."
        )
        solution = (
            f"По общей таблице A{index} имеет размеры {long_mm} × {short_mm} мм.",
            f"Делим короткую сторону на длинную: {short_mm} : {long_mm} ≈ "
            f"{_decimal_round_ratio(short_mm, long_mm, places)}.",
            f"Ответ после округления до {precision}: {answer}.",
        )
        return _new_question(
            scenario,
            4,
            "PAPER-F04",
            condition,
            answer,
            "paper.ratio_tenths",
            {
                "family_id": family_id,
                "format_index": index,
                "short_mm": short_mm,
                "long_mm": long_mm,
                "decimal_places": places,
            },
            solution,
        )
    if family_id == "PAPER-F06":
        next_index = index + 1
        next_row = next(
            (row for row in _get_rows(scenario.context) if row[0] == f"A{next_index}"), None
        )
        if index not in _DIAGONAL_FORMATS or next_row is None:
            raise ValueError("PAPER F06 requires an exact reversible cut and its visible next row")
        short_mm, long_mm = next_row[1], 2 * next_row[2]
        square_sum = long_mm**2 + short_mm**2
        side = model.get("denominator_side")
        side_name = "меньшей" if side == "short" else "большей"
        denominator = short_mm if side == "short" else long_mm
        answer = _decimal_round_sqrt_ratio(square_sum, denominator, places)
        condition = (
            f"Найдите отношение длины диагонали листа формата A{index} к его {side_name} стороне. "
            f"Используйте размеры листа A{next_index} из таблицы. "
            f"Ответ округлите до {precision}."
        )
        diagonal = Decimal(square_sum).sqrt()
        diagonal_value = diagonal.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        solution_steps: tuple[str, ...] = (
            f"По таблице A{next_index} имеет размеры {next_row[1]} × {next_row[2]} мм. "
            f"Меньшая сторона A{index} равна {short_mm} мм, "
            f"а большая — 2 × {next_row[2]} = {long_mm} мм.",
            f"По теореме Пифагора диагональ равна √({long_mm}² + {short_mm}²) ≈ "
            f"{str(diagonal_value).replace('.', ',')} мм.",
            f"Делим диагональ на {denominator} мм и округляем до {precision}: {answer}.",
        )
        return _new_question(
            scenario,
            4,
            "PAPER-F06",
            condition,
            answer,
            "paper.diagonal_ratio_tenths",
            {
                "family_id": family_id,
                "format_index": index,
                "short_mm": short_mm,
                "long_mm": long_mm,
                "decimal_places": places,
                "denominator_side": side,
            },
            solution_steps,
        )
    raise ValueError("Unsupported PAPER position 4 family")


def _build_font_question(scenario: ScenarioDraft, model: Mapping[str, object]) -> QuestionDraft:
    source_index = _get_int(model, "source_index")
    target_index = _get_int(model, "target_index")
    old_pt = _get_int(model, "old_pt")
    rows = _get_rows(scenario.context)
    source = next((row for row in rows if row[0] == f"A{source_index}"), None)
    target = next((row for row in rows if row[0] == f"A{target_index}"), None)
    if (
        (source_index, target_index) not in _FONT_TRANSITIONS
        or old_pt not in _FONT_SIZES
        or source is None
        or target is None
    ):
        raise ValueError("PAPER font scaling requires verified formats, dimensions and point size")
    source_long, target_long = source[1], target[1]
    answer = _font_answer(old_pt, source_long, target_long)
    condition = (
        f"Размер шрифта на листе A{source_index} равен {old_pt} пт. "
        f"После изменения формата листа на A{target_index} размер шрифта меняют "
        "пропорционально длине большей стороны листа. "
        "Округлите новый размер до целого числа пунктов."
    )
    exact = Decimal(old_pt * target_long) / Decimal(source_long)
    solution = (
        f"По таблице длинные стороны A{source_index} и A{target_index} равны "
        f"{source_long} и {target_long} мм. "
        f"При переходе A{source_index} → A{target_index} масштаб равен "
        f"{target_long}/{source_long}.",
        f"Новый размер: {old_pt} · {target_long}/{source_long} ≈ "
        f"{str(exact.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)).replace('.', ',')} пт.",
        f"Округляем до целого пункта: {answer}.",
    )
    return _new_question(
        scenario,
        5,
        "PAPER-F07",
        condition,
        answer,
        "paper.font_scale",
        {
            "source_index": source_index,
            "target_index": target_index,
            "old_pt": old_pt,
            "source_long_mm": source_long,
            "target_long_mm": target_long,
        },
        solution,
    )


def _table_text(rows: tuple[tuple[str, int, int], ...], *, labeled: bool = False) -> str:
    return "\n".join(
        f"{row_id}. {label + ': ' if labeled else ''}{long_mm} × {short_mm} мм"
        for row_id, (label, long_mm, short_mm) in enumerate(rows, start=1)
    )


class PaperRenderer:
    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario:
        rows = _get_rows(scenario.context)
        labeled = scenario.generator_version != GENERATOR_VERSION
        assets = (_asset_ref(_DIAGRAM_PNG, "image/png"), _table_asset_ref(rows, labeled=labeled))
        context = (
            "Форматы бумаги серии A: площадь A0 принята равной 1 м²; "
            "при переходе к следующему формату площадь листа делится пополам. "
            "Схема показывает последовательное деление A0–A5 и является схемой "
            "отношений, а не чертежом в масштабе.\n"
            "Таблица размеров (длина × ширина, мм):\n"
            f"{_table_text(rows, labeled=labeled)}"
        )
        return RenderedScenario(shared_context=context, assets=assets)

    def restore_asset(self, snapshot: ScenarioSnapshot, asset: ScenarioAssetRef) -> bytes:
        if asset not in snapshot.assets:
            raise ValueError("PAPER asset is not part of the immutable snapshot")
        if asset.content_type != "image/png":
            raise ValueError("PAPER renderer only restores PNG assets")
        if asset.sha256 == _DIAGRAM_DIGEST:
            return _DIAGRAM_PNG
        rows = _get_rows(snapshot.context)
        table_bytes = _table_png(rows, labeled=snapshot.generator_version != GENERATOR_VERSION)
        if sha256(table_bytes).hexdigest() != asset.sha256:
            raise ValueError("PAPER PNG digest is not reproducible from the snapshot")
        return table_bytes


def _asset_ref(content: bytes, content_type: str) -> ScenarioAssetRef:
    digest = sha256(content).hexdigest()
    extension = "png" if content_type == "image/png" else "svg"
    return ScenarioAssetRef(digest, content_type, f"sha256/{digest}.{extension}")


@lru_cache(maxsize=1024)
def _table_asset_ref(rows: tuple[tuple[str, int, int], ...], *, labeled: bool) -> ScenarioAssetRef:
    return _asset_ref(_table_png(rows, labeled=labeled), "image/png")


@dataclass(frozen=True, slots=True)
class _TextNumberPolicy:
    policy_id: str
    version: str
    kind: str

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool:
        raw = raw_answer.strip()
        if self.kind == "four_digit_permutation":
            return (
                bool(re.fullmatch(r"[1-4]{4}", raw))
                and len(set(raw)) == 4
                and raw == canonical_answer
            )
        if self.kind == "positive_integer":
            return bool(re.fullmatch(r"[1-9]\d*", raw)) and raw == canonical_answer
        if self.kind == "nonnegative_integer":
            return bool(re.fullmatch(r"\d+", raw)) and raw == canonical_answer
        if self.kind == "variable_decimal":
            normalized = raw.replace(".", ",")
            return bool(re.fullmatch(r"\d+,\d{1,2}", normalized)) and normalized == canonical_answer
        if self.kind == "one_decimal":
            normalized = raw.replace(".", ",")
            return bool(re.fullmatch(r"\d+,\d", normalized)) and normalized == canonical_answer
        return False


class PaperOracle:
    def validate_scenario(self, scenario: ScenarioDraft) -> None:
        if scenario.story_code != "PAPER" or scenario.generator_version != GENERATOR_VERSION:
            raise ValueError("PAPER scenario has an unsupported story or generator version")
        if scenario.compatibility_matrix_version != WORLD_VERSION:
            raise ValueError("PAPER scenario uses an unsupported compatibility matrix")
        if scenario.context.get("seed") != scenario.seed:
            raise ValueError("PAPER scenario context seed does not match its snapshot seed")
        if scenario.context.get("world_version") != WORLD_VERSION:
            raise ValueError("PAPER scenario world version is inconsistent")
        rows = _get_rows(scenario.context)
        labels = [label for label, _, _ in rows]
        if len(rows) != 4 or len(set(labels)) != 4:
            raise ValueError("PAPER table must contain four distinct format rows")
        for label, long_mm, short_mm in rows:
            match = re.fullmatch(r"A([0-7])", label)
            if match is None or DIMENSIONS_MM[int(match.group(1))] != (long_mm, short_mm):
                raise ValueError("PAPER table contains an unknown format or mutated dimensions")
        order = _get_target_order(scenario.context)
        if len(order) != 4 or len(set(order)) != 4 or set(order) != set(labels):
            raise ValueError("PAPER matching order must be a permutation of the four table formats")
        manifest = scenario.context.get("asset_manifest")
        if not isinstance(manifest, Mapping):
            raise ValueError("PAPER scenario is missing its immutable graphic manifest")
        if manifest.get("diagram_asset_id") != "paper-a0-a5-folding-v1":
            raise ValueError("PAPER scenario references an unknown diagram asset version")
        if manifest.get("diagram_sha256") != _DIAGRAM_DIGEST:
            raise ValueError("PAPER diagram manifest hash is not the supported static asset")
        if manifest.get("table_asset_id") != "paper-dimensions-v2":
            raise ValueError("PAPER scenario references an unknown dimensions table version")
        questions = scenario.context.get("questions")
        if not isinstance(questions, Mapping) or set(questions) != {"2", "3", "4", "5"}:
            raise ValueError(
                "PAPER world must contain exactly the shared parameters for positions 2–5"
            )
        _validate_question_parameters(questions, set(labels))

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None:
        _validate_rendered_context(scenario, rendered)
        if (
            question.scenario_seed != scenario.seed
            or question.generator_version != GENERATOR_VERSION
        ):
            raise ValueError("PAPER question does not belong to its scenario")
        expected = PaperQuestionBuilder().build_question(scenario, question.position)
        if question.family_id != expected.family_id:
            raise ValueError("PAPER question family does not match the shared scenario")
        answer, model = _independent_visible_answer(question, rendered)
        if answer != question.canonical_answer or answer != expected.canonical_answer:
            raise ValueError("PAPER answer does not match the visible mathematical condition")
        plain_model = _plain_json(question.math_model)
        if not isinstance(plain_model, dict) or any(
            plain_model.get(key) != value for key, value in model.items()
        ):
            raise ValueError("PAPER question math model does not match its visible condition")
        if plain_model != _plain_json(expected.math_model):
            raise ValueError("PAPER question model differs from its registered family and inputs")
        if question.condition != expected.condition:
            raise ValueError("PAPER question condition differs from the source-bounded renderer")
        if question.hints != expected.hints or question.solution_steps != expected.solution_steps:
            raise ValueError("PAPER hints or solution do not match the visible calculation")
        if (
            question.answer_policy_id != expected.answer_policy_id
            or question.answer_policy_version != expected.answer_policy_version
        ):
            raise ValueError("PAPER question uses the wrong answer policy")

    def validate_bundle(
        self,
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        rendered: RenderedScenario,
    ) -> None:
        if tuple(question.position for question in questions) != (1, 2, 3, 4, 5):
            raise ValueError("PAPER bundle must contain all five positions in order")
        if {question.scenario_seed for question in questions} != {scenario.seed}:
            raise ValueError("PAPER bundle mixes scenario seeds")
        if len({question.family_id for question in questions if question.position != 4}) != 4:
            raise ValueError("PAPER bundle must use the expected family at positions 1, 2, 3 and 5")
        for question in questions:
            self.validate_question(scenario, question, rendered)


def _validate_question_parameters(questions: Mapping[str, object], labels: set[str]) -> None:
    q2, q3, q4, q5 = (questions.get(str(i)) for i in (2, 3, 4, 5))
    if not all(isinstance(value, Mapping) for value in (q2, q3, q4, q5)):
        raise ValueError("PAPER question parameters must be objects")
    assert isinstance(q2, Mapping) and isinstance(q3, Mapping)
    assert isinstance(q4, Mapping) and isinstance(q5, Mapping)
    i, j = _get_int(q2, "source_index"), _get_int(q2, "target_index")
    if not 0 <= i < j <= 6 or not 1 <= _get_int(q2, "source_count") <= 5:
        raise ValueError("PAPER question 2 has invalid cutting inputs")
    index, multiple = _get_int(q3, "format_index"), _get_int(q3, "multiple")
    if (index, q3.get("side"), multiple) not in _ROUNDING_OPTIONS or f"A{index}" not in labels:
        raise ValueError("PAPER question 3 requires a supported rounding case and a visible row")
    family_id, ratio_index = q4.get("family_id"), _get_int(q4, "format_index")
    if _get_int(q4, "decimal_places") not in _PRECISION_NAMES:
        raise ValueError("PAPER ratio question has unsupported precision")
    if q4.get("denominator_side") not in ("short", "long"):
        raise ValueError("PAPER ratio question has an invalid denominator")
    if family_id == "PAPER-F04":
        if f"A{ratio_index}" not in labels or q4.get("denominator_side") != "long":
            raise ValueError(
                "PAPER side-ratio question requires smaller over larger and a visible row"
            )
    elif family_id == "PAPER-F06":
        if ratio_index not in _DIAGONAL_FORMATS or f"A{ratio_index + 1}" not in labels:
            raise ValueError("PAPER diagonal-ratio question requires an exact cut and visible row")
    else:
        raise ValueError("PAPER question 4 uses a non-candidate family")
    f_source, f_target = _get_int(q5, "source_index"), _get_int(q5, "target_index")
    if (f_source, f_target) not in _FONT_TRANSITIONS or not {"A3", "A4"}.issubset(labels):
        raise ValueError("PAPER font scaling requires the verified A4-to-A3 direction and rows")
    if _get_int(q5, "old_pt") not in _FONT_SIZES:
        raise ValueError("PAPER font point size is outside the supported range")


def _validate_rendered_context(scenario: ScenarioDraft, rendered: RenderedScenario) -> None:
    rows = _get_rows(scenario.context)
    if _table_text(rows) not in rendered.shared_context:
        raise ValueError("PAPER rendered table labels or dimensions differ from the scenario")
    if "1 м²" not in rendered.shared_context or "A0–A5" not in rendered.shared_context:
        raise ValueError("PAPER shared statement omits the format definition or diagram scope")
    if len(rendered.assets) != 2 or any(
        asset.content_type != "image/png" for asset in rendered.assets
    ):
        raise ValueError("PAPER shared graphics must contain the diagram and table PNG")
    manifest = scenario.context.get("asset_manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("PAPER scenario is missing its graphic digest manifest")
    table_ref = _table_asset_ref(rows, labeled=False)
    if "table_sha256" in manifest and manifest["table_sha256"] != table_ref.sha256:
        raise ValueError("PAPER table manifest hash does not match its stored rows")
    if rendered.assets != (_asset_ref(_DIAGRAM_PNG, "image/png"), table_ref):
        raise ValueError("PAPER PNG references do not match the shared table and diagram")


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _parse_visible_rows(rendered: RenderedScenario) -> tuple[tuple[str, int, int], ...]:
    matches = re.findall(r"(?m)^(\d+)\. (\d+) × (\d+) мм$", rendered.shared_context)
    if len(matches) != 4:
        raise ValueError("PAPER visible table must contain exactly four complete unlabeled rows")
    rows: list[tuple[str, int, int]] = []
    # Infer the format by its area relative to the ideal A0 area. ISO sides
    # are rounded, but no supported area is near the boundary between formats.
    for expected_row, (row_id, long_mm, short_mm) in enumerate(matches, start=1):
        if int(row_id) != expected_row:
            raise ValueError("PAPER visible table row labels are not consecutive")
        length, width = int(long_mm), int(short_mm)
        index = min(range(8), key=lambda n: abs((length * width << n) - 1_000_000))
        rows.append((f"A{index}", length, width))
    return tuple(rows)


def _independent_visible_answer(
    expected: QuestionDraft, rendered: RenderedScenario
) -> tuple[str, Mapping[str, object]]:
    position = expected.position
    if position == 1:
        rows = _parse_visible_rows(rendered)
        order_match = re.search(
            r"Форматы в указанном порядке: (A[0-7](?:, A[0-7]){3})\.", expected.condition
        )
        if order_match is None:
            raise ValueError("PAPER question 1 does not show four target formats")
        order = tuple(order_match.group(1).split(", "))
        if len(set(order)) != 4 or set(order) != {label for label, _, _ in rows}:
            raise ValueError("PAPER visible table and target formats are not a bijection")
        row_ids = {label: index for index, (label, _, _) in enumerate(rows, start=1)}
        answer = "".join(str(row_ids[label]) for label in order)
        return answer, {"target_order": list(order), "rows": [list(row) for row in rows]}
    if position == 2:
        match = re.fullmatch(
            r"Есть листы формата A([0-6]) в количестве ([1-5]) шт\. Каждый лист разрезают "
            r"пополам и продолжают разрезать полученные листы до формата A([1-6])\. "
            r"Сколько листов формата A\3 получится всего\?",
            expected.condition,
        )
        if match is None:
            raise ValueError(
                "PAPER question 2 cutting condition omits an input or has unsupported wording"
            )
        i, count, j = map(int, match.groups())
        if not i < j:
            raise ValueError("PAPER question 2 reverses the supported cutting direction")
        # Independent repeated-doubling oracle, intentionally not 2**(j-i).
        sheets = count
        for _ in range(j - i):
            sheets *= 2
        return str(sheets), {"source_index": i, "target_index": j, "source_count": count}
    if position == 3:
        match = re.fullmatch(
            r"Найдите (ширину|длину) листа бумаги формата A([0-7])\. "
            r"Ответ дайте в миллиметрах и округлите до ближайшего целого числа, кратного (5|10)\."
            r"( Если два кратных одинаково близки, выберите большее\.)?",
            expected.condition,
        )
        if match is None:
            raise ValueError("PAPER question 3 does not match a dimension-rounding form")
        word, index_text, step, tie_rule = match.groups()
        index, multiple = int(index_text), int(step)
        row = next((row for row in _parse_visible_rows(rendered) if row[0] == f"A{index}"), None)
        if row is None:
            raise ValueError("PAPER question 3 has no visible dimensions in the common table")
        side = "short" if word == "ширину" else "long"
        value = row[2] if side == "short" else row[1]
        # Independent nearest-multiple check by exact integer distance.
        lower = (value // multiple) * multiple
        upper = lower + multiple
        if value - lower == upper - value and not tie_rule:
            raise ValueError("PAPER question 3 needs a tie-breaking rule")
        answer = str(upper if value - lower >= upper - value else lower)
        return answer, {
            "format_index": index,
            "side": side,
            "value_mm": value,
            "multiple": multiple,
        }
    if position == 4:
        direct = re.fullmatch(
            r"Найдите отношение длины меньшей стороны листа формата A([0-7]) к большей\. "
            r"Ответ округлите до (десятых|сотых)\.",
            expected.condition,
        )
        dimensions = {
            label: (length, width) for label, length, width in _parse_visible_rows(rendered)
        }
        if direct:
            index = int(direct.group(1))
            pair = dimensions.get(f"A{index}")
            if pair is None:
                raise ValueError("PAPER side-ratio question has no valid visible dimensions")
            long_mm, short_mm = pair
            places = 1 if direct.group(2) == "десятых" else 2
            answer = _decimal_round_ratio(short_mm, long_mm, places)
            return answer, {
                "family_id": "PAPER-F04",
                "format_index": index,
                "short_mm": short_mm,
                "long_mm": long_mm,
                "decimal_places": places,
            }
        diagonal = re.fullmatch(
            r"Найдите отношение длины диагонали листа формата A([0-6]) "
            r"к его (меньшей|большей) стороне\. "
            r"Используйте размеры листа A([1-7]) из таблицы\. "
            r"Ответ округлите до (десятых|сотых)\.",
            expected.condition,
        )
        if diagonal is None:
            raise ValueError("PAPER diagonal-ratio condition has mutated format or direction")
        index, next_index = int(diagonal.group(1)), int(diagonal.group(3))
        side = "short" if diagonal.group(2) == "меньшей" else "long"
        places = 1 if diagonal.group(4) == "десятых" else 2
        pair = dimensions.get(f"A{next_index}")
        if next_index != index + 1 or pair is None:
            raise ValueError("PAPER diagonal-ratio question requires the next format in its table")
        long_mm, short_mm = pair[1] + pair[1], pair[0]
        if (long_mm, short_mm) != DIMENSIONS_MM[index]:
            raise ValueError("PAPER diagonal-ratio reconstruction does not match exact ISO sides")
        square_sum = long_mm**2 + short_mm**2
        answer = _round_sqrt_ratio(square_sum, short_mm if side == "short" else long_mm, places)
        return answer, {
            "family_id": "PAPER-F06",
            "format_index": index,
            "short_mm": short_mm,
            "long_mm": long_mm,
            "decimal_places": places,
            "denominator_side": side,
        }
    if position == 5:
        match = re.search(
            r"Размер шрифта на листе A([34]) равен (\d+) пт\. "
            r"После изменения формата листа на A([34]) размер шрифта меняют "
            r"пропорционально длине большей стороны листа\. "
            r"Округлите новый размер до целого числа пунктов\.",
            expected.condition,
        )
        if match is None:
            raise ValueError("PAPER font condition is missing its formats, units, or rounding rule")
        source_index, old_pt, target_index = map(int, match.groups())
        visible = {label: length for label, length, _ in _parse_visible_rows(rendered)}
        source_long, target_long = visible.get(f"A{source_index}"), visible.get(f"A{target_index}")
        if source_long is None or target_long is None or source_index == target_index:
            raise ValueError("PAPER font condition has no valid visible format transition")
        # Independent exact half-up rounding using quotient/remainder.
        numerator = old_pt * target_long
        quotient, remainder = divmod(numerator, source_long)
        answer = str(quotient + (2 * remainder >= source_long))
        return answer, {
            "source_index": source_index,
            "target_index": target_index,
            "old_pt": old_pt,
            "source_long_mm": source_long,
            "target_long_mm": target_long,
        }
    raise ValueError("Unsupported PAPER question position")


def _make_policies() -> Mapping[tuple[str, str], AnswerPolicy]:
    policies: dict[tuple[str, str], AnswerPolicy] = {}
    entries = (
        ("paper.mapping_four", "four_digit_permutation"),
        ("paper.sheet_count", "positive_integer"),
        ("paper.rounded_mm", "positive_integer"),
        ("paper.ratio_tenths", "one_decimal"),
        ("paper.diagonal_ratio_tenths", "one_decimal"),
        ("paper.font_scale", "positive_integer"),
    )
    for policy_id, kind in entries:
        policies[(policy_id, ANSWER_POLICY_VERSION)] = _TextNumberPolicy(
            policy_id, ANSWER_POLICY_VERSION, kind
        )
    for policy_id in ("paper.ratio_tenths", "paper.diagonal_ratio_tenths"):
        policies[(policy_id, RATIO_POLICY_VERSION)] = _TextNumberPolicy(
            policy_id, RATIO_POLICY_VERSION, "variable_decimal"
        )
    return MappingProxyType(policies)


def _registrations(
    enabled_families: frozenset[str] = frozenset(),
) -> tuple[FamilyRegistration, ...]:
    definitions = (
        ("PAPER-F01", 1, FamilyStatus.ENABLED_CANDIDATE, "paper.mapping_four"),
        ("PAPER-F02", 2, FamilyStatus.ENABLED_CANDIDATE, "paper.sheet_count"),
        ("PAPER-F03", 3, FamilyStatus.ENABLED_CANDIDATE, "paper.rounded_mm"),
        ("PAPER-F04", 4, FamilyStatus.ENABLED_CANDIDATE, "paper.ratio_tenths"),
        ("PAPER-F05", 4, FamilyStatus.RESEARCH_ONLY, "paper.ratio_tenths_inverse"),
        ("PAPER-F06", 4, FamilyStatus.ENABLED_CANDIDATE, "paper.diagonal_ratio_tenths"),
        ("PAPER-F07", 5, FamilyStatus.ENABLED_CANDIDATE, "paper.font_scale"),
        ("PAPER-F08", 3, FamilyStatus.BLOCKED, "paper.area_dual_unresolved"),
        ("PAPER-F09", 5, FamilyStatus.BLOCKED, "paper.mass_model_unresolved"),
    )
    return tuple(
        FamilyRegistration(
            family_id=family_id,
            position=position,
            status=status,
            answer_policy_id=policy_id,
            answer_policy_version=(
                RATIO_POLICY_VERSION
                if family_id in {"PAPER-F04", "PAPER-F06"}
                else ANSWER_POLICY_VERSION
            ),
            enabled=family_id in enabled_families,
            source_ids=_ALL_SOURCE_IDS[family_id],
        )
        for family_id, position, status, policy_id in definitions
    )


@dataclass(frozen=True, slots=True)
class PaperAdapter:
    story_code: str = "PAPER"
    generator: PaperGenerator = PaperGenerator()
    question_builder: PaperQuestionBuilder = PaperQuestionBuilder()
    independent_oracle: PaperOracle = PaperOracle()
    renderer: PaperRenderer = PaperRenderer()
    answer_policies: Mapping[tuple[str, str], AnswerPolicy] = _make_policies()
    family_registry: tuple[FamilyRegistration, ...] = _registrations()


def build_adapter(*, enabled_families: frozenset[str] = frozenset()) -> PaperAdapter:
    """Return PAPER; explicit family activation is reserved for isolated tests."""
    supported = frozenset(_SOURCE_IDS)
    unknown = enabled_families - supported
    if unknown:
        raise ValueError(f"Cannot enable unsupported PAPER families: {sorted(unknown)}")
    return PaperAdapter(family_registry=_registrations(enabled_families))


__all__ = ["build_adapter"]
