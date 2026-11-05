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

GENERATOR_VERSION = "paper-v3"
WORLD_VERSION = "paper-world-v1"
ANSWER_POLICY_VERSION = "1"

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
def _table_png(rows: tuple[tuple[str, int, int], ...]) -> bytes:
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
    headings = ("НОМЕР ЛИСТА", "ДЛИНА (мм)", "ШИРИНА (мм)")
    x = x0
    for heading, col_width in zip(headings, col_widths, strict=True):
        _draw_bitmap_text(draw, (x + 20, y0 + 44), heading, 3, ink)
        x += col_width
    y = y0 + header_h
    for index, (label, long_mm, short_mm) in enumerate(rows, start=1):
        x = x0
        draw.rectangle((x0, y, x0 + width, y + row_h), fill="white")
        values = (f"{index}. {label}", str(long_mm), str(short_mm))
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


def _round_ratio_tenths(numerator: int, denominator: int) -> str:
    if numerator < 0 or denominator <= 0:
        raise ValueError("Ratio must be non-negative with a positive denominator")
    scaled, remainder = divmod(numerator * 10, denominator)
    tenths = scaled + (2 * remainder >= denominator)
    return f"{tenths // 10},{tenths % 10}"


def _decimal_round_ratio_tenths(numerator: int, denominator: int) -> str:
    value = Decimal(numerator) / Decimal(denominator)
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return str(rounded).replace(".", ",")


def _decimal_round_sqrt_ratio_tenths(square_sum: int, denominator: int) -> str:
    value = Decimal(square_sum).sqrt() / Decimal(denominator)
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return str(rounded).replace(".", ",")


def _round_sqrt_ratio_tenths(square_sum: int, denominator: int) -> str:
    """Round sqrt(square_sum)/denominator using exact integer comparisons."""
    scaled_floor = isqrt(square_sum * 100) // denominator
    # Compare the unrounded ratio to the exact half-tenth threshold.
    rounds_up = 400 * square_sum >= (2 * scaled_floor + 1) ** 2 * denominator**2
    tenths = scaled_floor + rounds_up
    return f"{tenths // 10},{tenths % 10}"


def _font_answer(old_pt: int, source_long: int, target_long: int) -> str:
    scaled = Decimal(old_pt * target_long) / Decimal(source_long)
    return str(int(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def _make_world(seed: int) -> dict[str, object]:
    rng = Random(seed ^ 0x5041504552)
    # The common table supplies the dimensions needed by positions 3 and 4.
    selected_formats = [0, 3, 4, *rng.sample((1, 2, 5, 6), 1)]
    row_formats = selected_formats.copy()
    rng.shuffle(row_formats)
    rows = [
        (f"A{index}", DIMENSIONS_MM[index][0], DIMENSIONS_MM[index][1]) for index in row_formats
    ]
    target_order = rng.sample(selected_formats, 4)
    table_rows = tuple(rows)
    table_digest = sha256(_table_png(table_rows)).hexdigest()

    source_index = rng.randrange(6)
    target_index = rng.randrange(source_index + 1, 7)
    round_format, round_side, round_multiple = (0, "short", 10)
    ratio_kind = rng.choice(("PAPER-F04", "PAPER-F06"))
    ratio_index = 3 if ratio_kind == "PAPER-F04" else 2
    font_source, font_target = 4, 3
    font_old_pt = rng.choice((10, 15))

    return {
        "seed": seed,
        "world_version": WORLD_VERSION,
        "rows": rows,
        "target_order": [f"A{index}" for index in target_order],
        "asset_manifest": {
            "diagram_asset_id": "paper-a0-a5-folding-v1",
            "diagram_sha256": _DIAGRAM_DIGEST,
            "table_asset_id": "paper-dimensions-v1",
            "table_sha256": table_digest,
        },
        "questions": {
            "2": {"source_index": source_index, "target_index": target_index},
            "3": {
                "format_index": round_format,
                "side": round_side,
                "multiple": round_multiple,
            },
            "4": {"family_id": ratio_kind, "format_index": ratio_index},
            "5": {
                "source_index": font_source,
                "target_index": font_target,
                "old_pt": font_old_pt,
            },
        },
    }


class PaperGenerator:
    def generate_scenario(self, seed: int) -> ScenarioDraft:
        context = _make_world(seed)
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
    return QuestionDraft(
        position=position,
        scenario_seed=scenario.seed,
        family_id=family_id,
        generator_version=GENERATOR_VERSION,
        condition=condition,
        answer_policy_id=policy_id,
        answer_policy_version=ANSWER_POLICY_VERSION,
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
        {"target_order": list(order), "rows": [list(row) for row in rows]},
        ("Площадь A0 близка к 1 000 000 мм². У каждого следующего формата "
         "площадь примерно вдвое меньше.",)
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
    answer = str(2 ** (j - i))
    condition = (
        f"Из одного листа формата A{i} последовательно получают листы формата A{j}. "
        "Сколько листов A" + str(j) + " получится из одного листа A" + str(i) + "?"
    )
    return _new_question(
        scenario,
        2,
        "PAPER-F02",
        condition,
        answer,
        "paper.sheet_count",
        {"source_index": i, "target_index": j},
        (
            f"От A{i} до A{j} выполняется {j - i} последовательных делений пополам.",
            f"При каждом делении один лист даёт два листа следующего формата: "
            f"2^{j - i} = {answer}.",
        ),
    )


def _build_rounding_question(scenario: ScenarioDraft, model: Mapping[str, object]) -> QuestionDraft:
    index, multiple = _get_int(model, "format_index"), _get_int(model, "multiple")
    side = model.get("side")
    rows = _get_rows(scenario.context)
    a0 = next((row for row in rows if row[0] == "A0"), None)
    if (index, side, multiple) != (0, "short", 10) or a0 is None:
        raise ValueError("PAPER rounding parameters are outside the individually checked examples")
    exact_value = a0[2]
    answer = str(_round_multiple_half_up(exact_value, multiple))
    condition = (
        f"Найдите ширину листа бумаги формата A0. Ответ дайте в миллиметрах и округлите "
        f"до ближайшего целого числа, кратного {multiple}."
    )
    return _new_question(
        scenario,
        3,
        "PAPER-F03",
        condition,
        answer,
        "paper.rounded_mm",
        {"format_index": index, "side": side, "value_mm": exact_value, "multiple": multiple},
        (
            f"В общей таблице ширина листа A0 равна {exact_value} мм.",
            f"Округляем эту ширину до кратного {multiple}: {exact_value} мм → {answer} мм.",
        ),
    )


def _build_ratio_question(scenario: ScenarioDraft, model: Mapping[str, object]) -> QuestionDraft:
    family_id = model.get("family_id")
    index = _get_int(model, "format_index")
    if family_id == "PAPER-F04":
        a3 = next((row for row in _get_rows(scenario.context) if row[0] == "A3"), None)
        if index != 3 or a3 is None or a3[1:] != DIMENSIONS_MM[3]:
            raise ValueError("PAPER F04 requires verified A3 dimensions in the shared table")
        long_mm, short_mm = a3[1], a3[2]
        answer = _round_ratio_tenths(short_mm, long_mm)
        condition = (
            "Найдите отношение длины меньшей стороны листа формата A3 к большей. "
            "Ответ округлите до десятых."
        )
        solution = (
            f"В общей таблице A3 имеет размеры {long_mm} × {short_mm} мм.",
            f"Делим короткую сторону на длинную: {short_mm} : {long_mm} ≈ "
            f"{_decimal_round_ratio_tenths(short_mm, long_mm)}.",
            f"Ответ после округления до десятых: {answer}.",
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
            },
            solution,
        )
    if family_id == "PAPER-F06":
        index = 2
        long_mm, short_mm = DIMENSIONS_MM[index]
        a3 = next((row for row in _get_rows(scenario.context) if row[0] == "A3"), None)
        if a3 is None or a3[1:] != DIMENSIONS_MM[3]:
            raise ValueError("PAPER F06 requires verified A3 dimensions in the shared table")
        short_mm, long_mm = a3[1], 2 * a3[2]
        square_sum = long_mm**2 + short_mm**2
        answer = _decimal_round_sqrt_ratio_tenths(square_sum, short_mm)
        condition = (
            "Найдите отношение длины диагонали листа формата A2 к его меньшей стороне. "
            "Ответ округлите до десятых."
        )
        diagonal = Decimal(square_sum).sqrt()
        diagonal_value = diagonal.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        solution_steps: tuple[str, ...] = (
            f"В общей таблице A3 равен {a3[1]} × {a3[2]} мм. Поэтому меньшая сторона A2 равна "
            f"{short_mm} мм, а большая — 2 × {a3[2]} = {long_mm} мм.",
            f"По теореме Пифагора диагональ равна √({long_mm}² + {short_mm}²) ≈ "
            f"{str(diagonal_value).replace('.', ',')} мм.",
            f"Делим диагональ на меньшую сторону A2 ({short_mm} мм): ответ {answer}.",
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
            },
            solution_steps,
        )
    raise ValueError("Unsupported PAPER position 4 family")


def _build_font_question(scenario: ScenarioDraft, model: Mapping[str, object]) -> QuestionDraft:
    source_index = _get_int(model, "source_index")
    target_index = _get_int(model, "target_index")
    old_pt = _get_int(model, "old_pt")
    rows = _get_rows(scenario.context)
    a4 = next((row for row in rows if row[0] == "A4"), None)
    a3 = next((row for row in rows if row[0] == "A3"), None)
    if (
        (source_index, target_index) != (4, 3)
        or old_pt not in (10, 15)
        or a4 is None
        or a3 is None
        or a4[1:] != DIMENSIONS_MM[4]
        or a3[1:] != DIMENSIONS_MM[3]
    ):
        raise ValueError("PAPER font scaling requires verified A4→A3 dimensions and point size")
    source_long, target_long = a4[1], a3[1]
    answer = _font_answer(old_pt, source_long, target_long)
    condition = (
        f"Размер шрифта на листе A{source_index} равен {old_pt} пт. "
        f"После изменения формата листа на A{target_index} размер шрифта меняют "
        "пропорционально соответствующей стороне формата. "
        "Округлите новый размер до целого числа пунктов."
    )
    exact = Decimal(old_pt * target_long) / Decimal(source_long)
    solution = (
        f"В общей таблице длинные стороны A4 и A3 равны {source_long} и {target_long} мм. "
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


def _table_text(rows: tuple[tuple[str, int, int], ...]) -> str:
    return "\n".join(
        f"{row_id}. {label}: {long_mm} × {short_mm} мм"
        for row_id, (label, long_mm, short_mm) in enumerate(rows, start=1)
    )


class PaperRenderer:
    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario:
        rows = _get_rows(scenario.context)
        table_bytes = _table_png(rows)
        assets = (
            _asset_ref(_DIAGRAM_PNG, "image/png"),
            _asset_ref(table_bytes, "image/png"),
        )
        context = (
            "Форматы бумаги серии A: площадь A0 принята равной 1 м²; "
            "при переходе к следующему формату площадь листа делится пополам. "
            "Схема показывает последовательное деление A0–A5 и является схемой "
            "отношений, а не чертежом в масштабе.\n"
            "Таблица размеров (длина × ширина, мм):\n"
            f"{_table_text(rows)}"
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
        table_bytes = _table_png(rows)
        if sha256(table_bytes).hexdigest() != asset.sha256:
            raise ValueError("PAPER PNG digest is not reproducible from the snapshot")
        return table_bytes


def _asset_ref(content: bytes, content_type: str) -> ScenarioAssetRef:
    digest = sha256(content).hexdigest()
    extension = "png" if content_type == "image/png" else "svg"
    return ScenarioAssetRef(digest, content_type, f"sha256/{digest}.{extension}")


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
        if not {"A0", "A3", "A4"}.issubset(labels):
            raise ValueError("PAPER common table must include the A0, A3, and A4 source inputs")
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
        if manifest.get("table_asset_id") != "paper-dimensions-v1":
            raise ValueError("PAPER scenario references an unknown dimensions table version")
        if manifest.get("table_sha256") != sha256(_table_png(rows)).hexdigest():
            raise ValueError("PAPER table manifest hash does not match its stored rows")
        questions = scenario.context.get("questions")
        if not isinstance(questions, Mapping) or set(questions) != {"2", "3", "4", "5"}:
            raise ValueError(
                "PAPER world must contain exactly the shared parameters for positions 2–5"
            )
        _validate_question_parameters(questions)

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
        answer, model = _independent_visible_answer(scenario, question, rendered)
        if answer != question.canonical_answer or answer != expected.canonical_answer:
            raise ValueError("PAPER answer does not match the visible mathematical condition")
        plain_model = _plain_json(question.math_model)
        if not isinstance(plain_model, dict) or any(
            plain_model.get(key) != value for key, value in model.items()
        ):
            raise ValueError("PAPER question math model does not match its visible condition")
        if not isinstance(plain_model, dict) or plain_model.get("source_ids") != list(
            _SOURCE_IDS[question.family_id]
        ):
            raise ValueError("PAPER question source references differ from its registered family")
        if question.math_model.get("content_kind") != "generated_analogue":
            raise ValueError("PAPER generated task is missing its analogue provenance")
        if question.condition != expected.condition:
            raise ValueError("PAPER question condition differs from the source-bounded renderer")
        if question.hints != expected.hints or question.solution_steps != expected.solution_steps:
            raise ValueError("PAPER hints or solution do not match the visible calculation")
        if (
            question.answer_policy_id != expected.answer_policy_id
            or question.answer_policy_version != ANSWER_POLICY_VERSION
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


def _validate_question_parameters(questions: Mapping[str, object]) -> None:
    q2, q3, q4, q5 = (questions.get(str(i)) for i in (2, 3, 4, 5))
    if not all(isinstance(value, Mapping) for value in (q2, q3, q4, q5)):
        raise ValueError("PAPER question parameters must be objects")
    assert isinstance(q2, Mapping) and isinstance(q3, Mapping)
    assert isinstance(q4, Mapping) and isinstance(q5, Mapping)
    i, j = _get_int(q2, "source_index"), _get_int(q2, "target_index")
    if not 0 <= i < j <= 6:
        raise ValueError("PAPER question 2 has invalid format direction")
    r_index, multiple = _get_int(q3, "format_index"), _get_int(q3, "multiple")
    if (r_index, q3.get("side"), multiple) not in ((0, "short", 10), (7, "long", 5)):
        raise ValueError("PAPER question 3 uses an unverified rounded-dimension combination")
    family_id, ratio_index = q4.get("family_id"), _get_int(q4, "format_index")
    if family_id == "PAPER-F04" and ratio_index != 3:
        raise ValueError("PAPER side-ratio question must use the verified A3 case")
    if family_id == "PAPER-F06" and ratio_index != 2:
        raise ValueError("PAPER diagonal-ratio question must use the verified A2 case")
    if family_id not in ("PAPER-F04", "PAPER-F06"):
        raise ValueError("PAPER question 4 uses a non-candidate family")
    f_source, f_target = _get_int(q5, "source_index"), _get_int(q5, "target_index")
    font = _get_int(q5, "old_pt")
    if (f_source, f_target) != (4, 3):
        raise ValueError("PAPER font formats must match the verified A4-to-A3 direction")
    if font not in (10, 15):
        raise ValueError("PAPER font point size is outside the individually verified examples")


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
    expected_digests = {manifest.get("diagram_sha256"), manifest.get("table_sha256")}
    if {asset.sha256 for asset in rendered.assets} != expected_digests:
        raise ValueError("PAPER PNG references do not match the shared table and diagram")


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _parse_visible_rows(rendered: RenderedScenario) -> tuple[tuple[str, int, int], ...]:
    matches = re.findall(r"(?m)^(\d+)\. (A[0-7]): (\d+) × (\d+) мм$", rendered.shared_context)
    if len(matches) != 4:
        raise ValueError("PAPER visible table must contain exactly four complete rows")
    rows: list[tuple[str, int, int]] = []
    for expected_row, (row_id, label, long_mm, short_mm) in enumerate(matches, start=1):
        if int(row_id) != expected_row:
            raise ValueError("PAPER visible table row labels are not consecutive")
        rows.append((label, int(long_mm), int(short_mm)))
    return tuple(rows)


def _independent_visible_answer(
    scenario: ScenarioDraft, expected: QuestionDraft, rendered: RenderedScenario
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
        match = re.search(
            r"из одного листа формата A([0-6]).*?формата A([1-6])",
            expected.condition,
            flags=re.IGNORECASE,
        )
        if match is None:
            raise ValueError("PAPER question 2 omits a format or has unsupported wording")
        i, j = int(match.group(1)), int(match.group(2))
        if not i < j:
            raise ValueError("PAPER question 2 reverses the supported cutting direction")
        # Independent repeated-doubling oracle, intentionally not 2**(j-i).
        sheets = 1
        for _ in range(j - i):
            sheets *= 2
        return str(sheets), {"source_index": i, "target_index": j}
    if position == 3:
        match = re.search(
            r"Найдите ширину листа бумаги формата A0\. Ответ дайте в миллиметрах и округлите "
            r"до ближайшего целого числа, кратного (10)\.",
            expected.condition,
        )
        if match is None:
            raise ValueError("PAPER question 3 does not match a verified dimension-rounding form")
        a0 = next((row for row in _parse_visible_rows(rendered) if row[0] == "A0"), None)
        if a0 is None:
            raise ValueError("PAPER question 3 has no visible A0 width in the common table")
        index, value, multiple, side = 0, a0[2], int(match.group(1)), "short"
        # Independent nearest-multiple check by exact integer distance.
        lower = (value // multiple) * multiple
        upper = lower + multiple
        answer = str(upper if value - lower >= upper - value else lower)
        return answer, {
            "format_index": index,
            "side": side,
            "value_mm": value,
            "multiple": multiple,
        }
    if position == 4:
        f04_condition = (
            "Найдите отношение длины меньшей стороны листа формата A3 к большей. "
            "Ответ округлите до десятых."
        )
        if expected.condition == f04_condition:
            a3 = next((row for row in _parse_visible_rows(rendered) if row[0] == "A3"), None)
            if a3 is None or a3[1:] != DIMENSIONS_MM[3]:
                raise ValueError("PAPER side-ratio question has no valid visible A3 dimensions")
            index, long_mm, short_mm = 3, a3[1], a3[2]
            answer = _decimal_round_ratio_tenths(short_mm, long_mm)
            return answer, {
                "family_id": "PAPER-F04",
                "format_index": index,
                "short_mm": short_mm,
                "long_mm": long_mm,
            }
        if expected.condition != (
            "Найдите отношение длины диагонали листа формата A2 к его меньшей стороне. "
            "Ответ округлите до десятых."
        ):
            raise ValueError("PAPER diagonal-ratio condition has mutated format or direction")
        a3 = next((row for row in _parse_visible_rows(rendered) if row[0] == "A3"), None)
        if a3 is None or a3[1:] != DIMENSIONS_MM[3]:
            raise ValueError("PAPER diagonal-ratio question has no valid visible A3 dimensions")
        long_mm, short_mm = 2 * a3[2], a3[1]
        square_sum = long_mm**2 + short_mm**2
        answer = _round_sqrt_ratio_tenths(square_sum, short_mm)
        return answer, {
            "family_id": "PAPER-F06",
            "format_index": 2,
            "short_mm": short_mm,
            "long_mm": long_mm,
        }
    if position == 5:
        match = re.search(
            r"Размер шрифта на листе A4 равен (10|15) пт\. "
            r"После изменения формата листа на A3 размер шрифта меняют "
            r"пропорционально соответствующей стороне формата\. "
            r"Округлите новый размер до целого числа пунктов\.",
            expected.condition,
        )
        if match is None:
            raise ValueError("PAPER font condition is missing its formats, units, or rounding rule")
        old_pt = int(match.group(1))
        rows = _parse_visible_rows(rendered)
        a4 = next((row for row in rows if row[0] == "A4"), None)
        a3 = next((row for row in rows if row[0] == "A3"), None)
        if a4 is None or a3 is None or a4[1:] != DIMENSIONS_MM[4] or a3[1:] != DIMENSIONS_MM[3]:
            raise ValueError("PAPER font condition has no valid visible A4/A3 dimensions")
        source_index, target_index = 4, 3
        source_long, target_long = a4[1], a3[1]
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
            answer_policy_version=ANSWER_POLICY_VERSION,
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
