"""Research-backed, fail-closed adapter for OGE practical set 1–5 (tyres)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from io import BytesIO
from random import Random
from typing import cast

from PIL import Image, ImageDraw, ImageFont

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

STORY_CODE = "TYRES"
GENERATOR_VERSION = "tyres-v1"
COMPATIBILITY_MATRIX_VERSION = "fipi-2026-tyres-v1"
NUMBER_POLICY_ID = "oge.numeric-decimal"
NUMBER_POLICY_VERSION = "1"
_FIPI_2026_URL = "https://egesto.ru/math-oge/varianty/0"
_TASK_URLS = {
    "407953": "https://math-oge.sdamgia.ru/problem?id=407953",
    "462108": "https://math-oge.sdamgia.ru/problem?id=462108",
    "462128": "https://math-oge.sdamgia.ru/problem?id=462128",
    "408171": "https://math-oge.sdamgia.ru/problem?id=408171",
    "408172": "https://math-oge.sdamgia.ru/problem?id=408172",
    "408173": "https://math-oge.sdamgia.ru/problem?id=408173",
    "480721": "https://math-oge.sdamgia.ru/problem?id=480721",
}
_TIRE_PATTERN = re.compile(r"(?<!\d)(\d{3})/(\d{2})\s+R(\d{2})(?!\d)")
_WIDTHS = (165, 175, 185, 195, 205)
_ASPECTS = (45, 50, 55, 60, 65, 70)
_RIMS = tuple(range(12, 19))


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _decimal_answer(value: Decimal) -> str:
    return _decimal_text(value)


def _json_array(value: JsonValue, name: str) -> tuple[JsonValue, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be an array")
    return value


def _integer(value: JsonValue, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _text(value: JsonValue, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    return value


def _int_tuple(value: JsonValue, name: str, length: int) -> tuple[int, ...]:
    result = tuple(_integer(item, name) for item in _json_array(value, name))
    if len(result) != length:
        raise ValueError(f"{name} must contain {length} integers")
    return result


def _nested_int_tuple(
    value: JsonValue, name: str, rows: int, columns: int
) -> tuple[tuple[int, ...], ...]:
    result = tuple(_int_tuple(row, name, columns) for row in _json_array(value, name))
    if len(result) != rows:
        raise ValueError(f"{name} must contain {rows} rows")
    return result


def _int_cells(value: JsonValue, name: str, cells: int) -> tuple[tuple[int, ...], ...]:
    raw_cells = _json_array(value, name)
    if len(raw_cells) != cells:
        raise ValueError(f"{name} must contain {cells} cells")
    return tuple(
        tuple(_integer(item, name) for item in _json_array(cell, name)) for cell in raw_cells
    )


def _string_tuple(value: JsonValue, name: str) -> tuple[str, ...]:
    return tuple(_text(item, name) for item in _json_array(value, name))


class NumericAnswerPolicy:
    policy_id = NUMBER_POLICY_ID
    version = NUMBER_POLICY_VERSION

    def accepts(self, raw_answer: str, canonical_answer: str) -> bool:
        normalized = raw_answer.strip().replace(",", ".")
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", normalized):
            return False
        try:
            return Decimal(normalized) == Decimal(canonical_answer)
        except Exception:
            return False


def _wheel_png() -> bytes:
    """Render an invariant cross-section schematic; numeric data lives in text."""
    image = Image.new("RGB", (960, 620), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=34)
    small = ImageFont.load_default(size=27)
    dark = (28, 43, 58)
    blue = (36, 108, 177)
    orange = (224, 126, 36)
    light = (228, 235, 241)

    # Left: tire cross-section (B and H). Right: wheel face (D and d).
    draw.rounded_rectangle((42, 48, 448, 572), radius=24, outline=light, width=4)
    draw.text((78, 70), "Tire cross-section", fill=dark, font=small)
    tire = (142, 179, 218)
    draw.rounded_rectangle((154, 200, 330, 420), radius=72, fill=tire, outline=dark, width=5)
    draw.rounded_rectangle(
        (183, 245, 301, 376), radius=42, fill=(190, 203, 214), outline=dark, width=4
    )
    # Width B spans the sidewall; height H is a radial segment.
    draw.line((153, 455, 331, 455), fill=orange, width=5)
    draw.polygon(((153, 455), (171, 445), (171, 465)), fill=orange)
    draw.polygon(((331, 455), (313, 445), (313, 465)), fill=orange)
    draw.text((223, 472), "B", fill=dark, font=font)
    draw.line((341, 204, 341, 244), fill=orange, width=5)
    draw.polygon(((341, 204), (331, 222), (351, 222)), fill=orange)
    draw.polygon(((341, 244), (331, 226), (351, 226)), fill=orange)
    draw.text((359, 210), "H", fill=dark, font=font)

    draw.rounded_rectangle((490, 48, 918, 572), radius=24, outline=light, width=4)
    draw.text((525, 70), "Wheel diameter", fill=dark, font=small)
    draw.ellipse((584, 152, 824, 392), fill=tire, outline=dark, width=5)
    draw.ellipse((635, 203, 773, 341), fill=(190, 203, 214), outline=dark, width=4)
    draw.ellipse((681, 249, 727, 295), fill=(143, 158, 171), outline=dark, width=3)
    # Dimension arrows are intentionally schematic and not proportional.
    draw.line((562, 152, 562, 392), fill=blue, width=5)
    draw.polygon(((562, 152), (552, 170), (572, 170)), fill=blue)
    draw.polygon(((562, 392), (552, 374), (572, 374)), fill=blue)
    draw.text((514, 258), "D", fill=dark, font=font)
    draw.line((635, 272, 773, 272), fill=orange, width=5)
    draw.polygon(((635, 272), (653, 262), (653, 282)), fill=orange)
    draw.polygon(((773, 272), (755, 262), (755, 282)), fill=orange)
    draw.text((696, 292), "d", fill=dark, font=font)

    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


_WHEEL_BYTES = _wheel_png()
_WHEEL_SHA256 = sha256(_WHEEL_BYTES).hexdigest()
_WHEEL_ASSET = ScenarioAssetRef(_WHEEL_SHA256, "image/png", f"sha256/{_WHEEL_SHA256}.png")


def _tire_text(width: int, aspect: int, rim: int) -> str:
    return f"{width}/{aspect} R{rim}"


def _diameter_mm(width: int, aspect: int, rim: int) -> Decimal:
    return Decimal(rim) * Decimal("25.4") + Decimal(2 * width * aspect) / Decimal(100)


def _sidewall_mm(width: int, aspect: int) -> Decimal:
    return Decimal(width * aspect) / Decimal(100)


def _make_table(
    rng: Random, target_rim: int
) -> tuple[tuple[int, tuple[tuple[int, ...], ...]], ...]:
    widths = list(_WIDTHS)
    rng.shuffle(widths)
    widths = sorted(widths[: rng.randint(4, len(_WIDTHS))])
    values: list[tuple[int, tuple[tuple[int, ...], ...]]] = []
    # Each row has cells for three adjacent rim diameters; the queried column
    # is guaranteed to contain multiple candidates so min/max is unambiguous.
    rims = (target_rim - 1, target_rim, target_rim + 1)
    for width in widths:
        row: list[tuple[int, ...]] = []
        for rim in rims:
            if rim == target_rim:
                count = 1 if width == widths[0] else rng.randint(0, 2)
                if width == widths[-1]:
                    count = max(1, count)
            else:
                count = rng.randint(0, 2)
            aspects = tuple(sorted(rng.sample(_ASPECTS, count)))
            row.append(aspects)
        values.append((width, tuple(row)))
    return tuple(values)


def _render_table(
    table: tuple[tuple[int, tuple[tuple[int, ...], ...]], ...], rims: tuple[int, ...]
) -> str:
    lines = [
        "| Ширина шины (мм) \\ Диаметр диска (дюймы) | " + " | ".join(map(str, rims)) + " |",
        "|---:|" + "|".join("---:" for _ in rims) + "|",
    ]
    for width, cells in table:
        rendered = [
            "; ".join(_tire_text(width, aspect, rim) for aspect in aspects) or "—"
            for rim, aspects in zip(rims, cells, strict=True)
        ]
        lines.append("| " + str(width) + " | " + " | ".join(rendered) + " |")
    return "\n".join(lines)


def _generate_context(seed: int) -> dict[str, object]:
    rng = Random(seed)
    base_choices = [
        (width, aspect, rim)
        for width in _WIDTHS
        for aspect in _ASPECTS
        for rim in _RIMS
        if (width, aspect, rim) != (max(_WIDTHS), max(_ASPECTS), max(_RIMS))
    ]
    base_width, base_aspect, base_rim = rng.choice(base_choices)
    base_marking = _tire_text(base_width, base_aspect, base_rim)
    target_rim = rng.choice(_RIMS[1:-1])
    rims = (target_rim - 1, target_rim, target_rim + 1)
    table = _make_table(rng, target_rim)

    sidewall = (
        rng.choice(_WIDTHS),
        rng.choice(_ASPECTS),
        rng.choice(_RIMS),
    )
    comparison_rim = rng.choice(_RIMS)
    pair: list[tuple[int, int, int]] = []
    for _ in range(80):
        candidate = [
            (rng.choice(_WIDTHS), rng.choice(_ASPECTS), comparison_rim),
            (rng.choice(_WIDTHS), rng.choice(_ASPECTS), comparison_rim),
        ]
        if candidate[0][:2] != candidate[1][:2] and _sidewall_mm(*candidate[0][:2]) != _sidewall_mm(
            *candidate[1][:2]
        ):
            pair = candidate
            break
    if not pair:
        raise RuntimeError("Unable to create distinct tyre comparison")
    pair.sort(key=lambda item: _diameter_mm(*item))
    smaller, larger = pair

    replacements = [
        (width, aspect, rim)
        for width in _WIDTHS
        for aspect in _ASPECTS
        for rim in _RIMS
        if _diameter_mm(width, aspect, rim) > _diameter_mm(base_width, base_aspect, base_rim)
    ]
    replacement = rng.choice(replacements)

    table_value = [(width, cells[1]) for width, cells in table if cells[1]]
    if len(table_value) < 2:
        raise RuntimeError("Table query column must contain at least two widths")

    table_json = [
        {"width_mm": width, "aspect_ratios_by_rim": [list(cell) for cell in cells]}
        for width, cells in table
    ]
    return {
        "base_marking": base_marking,
        "base": [base_width, base_aspect, base_rim],
        "table_rims": list(rims),
        "table": table_json,
        "table_target_rim": target_rim,
        "sidewall_marking": _tire_text(*sidewall),
        "sidewall": list(sidewall),
        "comparison_markings": [_tire_text(*smaller), _tire_text(*larger)],
        "comparison": [list(smaller), list(larger)],
        "replacement_marking": _tire_text(*replacement),
        "replacement": list(replacement),
        "family_ids": [
            "TYRES-TABLE-EXTREME",
            "TYRES-SIDEWALL",
            "TYRES-DIAMETER",
            "TYRES-RADIUS-DELTA",
            "TYRES-PERCENT-ROTATION",
        ],
        "wheel_asset_sha256": _WHEEL_SHA256,
        "source_ids": [
            "FIPI-2026-TYRES-1",
            "FIPI-2026-TYRES-2",
            "FIPI-2026-TYRES-3",
            "FIPI-2026-TYRES-4",
            "FIPI-2026-TYRES-5",
            "407953",
            "462128",
            "408172",
            "408173",
        ],
    }


class TyresGenerator:
    def generate_scenario(self, seed: int) -> ScenarioDraft:
        context = _generate_context(seed)
        return ScenarioDraft(
            story_code=STORY_CODE,
            seed=seed,
            generator_version=GENERATOR_VERSION,
            context=cast(Mapping[str, object], context),  # type: ignore[arg-type]
            compatibility_matrix_version=COMPATIBILITY_MATRIX_VERSION,
            provenance=tuple(_TASK_URLS[item] for item in ("407953", "462128", "408172", "408173"))
            + (_FIPI_2026_URL,),
        )


class TyresQuestionBuilder:
    def build_question(self, scenario: ScenarioDraft, position: int) -> QuestionDraft:
        data = scenario.context
        table = _json_array(data["table"], "Scenario table")
        rows: list[tuple[int, tuple[tuple[int, ...], ...]]] = []
        for raw in table:
            if not isinstance(raw, Mapping):
                raise ValueError("Scenario table row must be an object")
            ratios = _int_cells(raw["aspect_ratios_by_rim"], "Scenario table cells", 3)
            rows.append(
                (
                    _integer(raw["width_mm"], "Scenario table width"),
                    ratios,
                )
            )
        base = _int_tuple(data["base"], "Factory marking", 3)
        sidewall = _int_tuple(data["sidewall"], "Sidewall marking", 3)
        comparison = _nested_int_tuple(data["comparison"], "Comparison markings", 2, 3)
        replacement = _int_tuple(data["replacement"], "Replacement marking", 3)
        steps: tuple[str, ...]

        if position == 1:
            condition = (
                "Шины какой наибольшей ширины можно устанавливать на автомобиль, "
                f"если диаметр диска равен {data['table_target_rim']} дюймам? "
                "Ответ дайте в миллиметрах."
            )
            maximum = max(width for width, cells in rows if cells[1])
            answer = str(maximum)
            hints = (
                "Найдите в таблице столбец с указанным диаметром диска.",
                "Среди непустых ячеек этого столбца выберите строку с наибольшей шириной.",
            )
            steps = (
                f"В столбце {data['table_target_rim']} дюйма сравниваем ширины из непустых ячеек.",
                f"Наибольшая ширина равна {answer} мм.",
            )
            model: dict[str, object] = {"rim": data["table_target_rim"], "extreme": "max"}
            family_id = "TYRES-TABLE-EXTREME"
        elif position == 2:
            condition = (
                "Сколько миллиметров составляет высота боковины шины маркировки "
                f"{_tire_text(*sidewall)}?"
            )
            answer = _decimal_answer(_sidewall_mm(*sidewall[:2]))
            hints = (
                "Второе число маркировки задаёт долю высоты боковины от ширины.",
                "Умножьте ширину шины на процент и разделите на 100.",
            )
            steps = (f"H = {sidewall[0]} · {sidewall[1]} / 100.", f"H = {answer} мм.")
            model = {"marking": _tire_text(*sidewall)}
            family_id = "TYRES-SIDEWALL"
        elif position == 3:
            condition = (
                "Найдите диаметр колеса автомобиля, выходящего с завода. Ответ дайте в миллиметрах."
            )
            answer = _decimal_answer(_diameter_mm(*base))
            h = _decimal_text(_sidewall_mm(*base[:2]))
            rim_mm = _decimal_text(Decimal(base[2]) * Decimal("25.4"))
            hints = (
                f"Из маркировки {data['base_marking']} найдите высоту боковины и диаметр диска.",
                "К диаметру диска прибавьте две высоты боковины.",
            )
            steps = (
                f"Высота боковины: {base[0]} · {base[1]} / 100 = {h} мм.",
                f"Диаметр диска: {base[2]} · 25,4 = {rim_mm} мм.",
                f"D = {rim_mm} + 2 · {h} = {answer} мм.",
            )
            model = {"factory_marking": data["base_marking"]}
            family_id = "TYRES-DIAMETER"
        elif position == 4:
            low, high = comparison
            first = _tire_text(*low)
            second = _tire_text(*high)
            condition = (
                f"На сколько миллиметров радиус колеса с шиной {first} меньше, "
                f"чем радиус колеса с шиной {second}?"
            )
            answer = _decimal_answer((_diameter_mm(*high) - _diameter_mm(*low)) / 2)
            hints = (
                "Вычислите высоту боковины каждой шины.",
                "Радиус равен половине диаметра; сравните радиусы в указанном порядке.",
            )
            diameter_delta = _decimal_text(_diameter_mm(*high) - _diameter_mm(*low))
            steps = (
                f"Разность диаметров: {diameter_delta} мм.",
                f"Разность радиусов в заданном направлении: {answer} мм.",
            )
            model = {"markings": [first, second], "direction": "first_smaller"}
            family_id = "TYRES-RADIUS-DELTA"
        elif position == 5:
            condition = (
                "На сколько процентов увеличится пробег автомобиля при одном обороте колеса, "
                f"если заменить заводские колёса шинами {_tire_text(*replacement)}? "
                "Результат округлите до десятых."
            )
            base_d = _diameter_mm(*base)
            new_d = _diameter_mm(*replacement)
            exact = (new_d / base_d - 1) * Decimal(100)
            answer = _decimal_answer(exact.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
            hints = (
                "Путь за один оборот пропорционален длине окружности πD.",
                "В относительном изменении множитель π сокращается; сравните диаметры.",
            )
            steps = (
                f"Dзавод = {_decimal_text(base_d)} мм; Dнов = {_decimal_text(new_d)} мм.",
                f"Изменение = 100 · (Dнов / Dзавод − 1) = {answer}% после округления до десятых.",
            )
            model = {
                "factory_marking": data["base_marking"],
                "replacement_marking": _tire_text(*replacement),
                "rounding": "0.1",
            }
            family_id = "TYRES-PERCENT-ROTATION"
        else:
            raise ValueError("TYRES has questions only at positions 1–5")

        return QuestionDraft(
            position=position,
            scenario_seed=scenario.seed,
            family_id=family_id,
            generator_version=GENERATOR_VERSION,
            condition=condition,
            answer_policy_id=NUMBER_POLICY_ID,
            answer_policy_version=NUMBER_POLICY_VERSION,
            canonical_answer=answer,
            hints=hints,
            solution_steps=steps,
            math_model=cast(Mapping[str, object], model),  # type: ignore[arg-type]
        )


class TyresRenderer:
    def render_scenario(self, scenario: ScenarioDraft) -> RenderedScenario:
        data = scenario.context
        base_marking = data.get("base_marking")
        raw_table = data.get("table")
        rims = data.get("table_rims")
        if (
            not isinstance(base_marking, str)
            or not isinstance(raw_table, tuple)
            or not isinstance(rims, tuple)
        ):
            raise ValueError("Scenario cannot be rendered")
        rows: list[tuple[int, tuple[tuple[int, ...], ...]]] = []
        for raw in raw_table:
            if not isinstance(raw, Mapping):
                raise ValueError("Malformed tyre table")
            cells = _int_cells(raw["aspect_ratios_by_rim"], "Rendered tyre table", 3)
            rows.append((_integer(raw["width_mm"], "Rendered tyre width"), cells))
        rim_headers = _int_tuple(rims, "Rendered rim headers", 3)
        context = (
            "**Ситуация.** Завод устанавливает на автомобили шины маркировки "
            f"**{base_marking}**. Первое число обозначает ширину шины в миллиметрах, "
            "второе — высоту боковины в процентах от ширины, а число после R — "
            "диаметр диска в дюймах (1 дюйм = 25,4 мм). Диаметр всего колеса равен "
            "диаметру диска в миллиметрах плюс две высоты боковины.\n\n"
            "В таблице приведены разрешённые размеры шин:\n\n"
            f"{_render_table(tuple(rows), rim_headers)}\n\n"
            "Схема показывает величины B, H, d и D. Рисунок условный и не в масштабе."
        )
        return RenderedScenario(context, (_WHEEL_ASSET,))

    def restore_asset(self, snapshot: ScenarioSnapshot, asset: ScenarioAssetRef) -> bytes:
        if asset.content_type != "image/png" or asset.sha256 != _WHEEL_SHA256:
            raise ValueError("Unknown TYRES scenario asset")
        if snapshot.context.get("wheel_asset_sha256") != _WHEEL_SHA256:
            raise ValueError("TYRES snapshot does not describe this wheel asset")
        return _WHEEL_BYTES


def _parse_marking(text: str) -> tuple[int, int, int]:
    match = _TIRE_PATTERN.search(text)
    if match is None:
        raise ValueError("Visible condition must contain a tyre marking B/P Rr")
    width, aspect, rim = (int(value) for value in match.groups())
    return width, aspect, rim


def _visible_table(shared_context: str) -> tuple[tuple[int, tuple[str, ...]], ...]:
    rows: list[tuple[int, tuple[str, ...]]] = []
    table_lines = [
        line.strip() for line in shared_context.splitlines() if line.strip().startswith("|")
    ]
    if len(table_lines) < 4:
        raise ValueError("Rendered tyre table is missing rows")
    for line in table_lines[2:]:
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if len(cells) != 4 or not cells[0].isdigit():
            raise ValueError("Rendered tyre table row has the wrong number of cells")
        rows.append((int(cells[0]), cells[1:]))
    return tuple(rows)


class TyresOracle:
    """Independent checker: parses the display text and solves from visible data."""

    def validate_scenario(self, scenario: ScenarioDraft) -> None:
        if scenario.story_code != STORY_CODE or scenario.generator_version != GENERATOR_VERSION:
            raise ValueError("Unexpected TYRES scenario version")
        data = scenario.context
        marking = _text(data.get("base_marking"), "Factory marking")
        table = _json_array(data.get("table"), "Table")
        rims = _int_tuple(data.get("table_rims"), "Table rim columns", 3)
        base = _int_tuple(data.get("base"), "Factory marking", 3)
        if _parse_marking(marking) != base:
            raise ValueError("Factory marking is inconsistent with its stored values")
        if tuple(sorted(rims)) != rims:
            raise ValueError("Table rim columns must be increasing")
        if len(table) < 3:
            raise ValueError("Table must contain at least three width rows")
        widths: list[int] = []
        for row in table:
            if not isinstance(row, Mapping):
                raise ValueError("Table row must be an object")
            width = _integer(row.get("width_mm"), "Table width")
            cells = _int_cells(row.get("aspect_ratios_by_rim"), "Table row", len(rims))
            if width not in _WIDTHS:
                raise ValueError("Table contains an unsupported width")
            widths.append(width)
            for ratios in cells:
                if any(value not in _ASPECTS for value in ratios):
                    raise ValueError("Table contains an invalid aspect ratio")
        if widths != sorted(set(widths)):
            raise ValueError("Table widths must be unique and increasing")
        if _integer(data.get("table_target_rim"), "Requested rim diameter") not in rims:
            raise ValueError("Requested rim diameter is not a table column")
        if data.get("wheel_asset_sha256") != _WHEEL_SHA256:
            raise ValueError("Wheel schematic does not match the invariant renderer")
        for key in ("sidewall_marking", "replacement_marking"):
            raw_marking = _text(data.get(key), key)
            if _TIRE_PATTERN.fullmatch(raw_marking) is None:
                raise ValueError("Scenario contains an invalid tyre marking")

    def validate_question(
        self, scenario: ScenarioDraft, question: QuestionDraft, rendered: RenderedScenario
    ) -> None:
        if (
            question.scenario_seed != scenario.seed
            or question.generator_version != GENERATOR_VERSION
        ):
            raise ValueError("Question belongs to a different TYRES scenario")
        if (
            question.answer_policy_id != NUMBER_POLICY_ID
            or question.answer_policy_version != NUMBER_POLICY_VERSION
        ):
            raise ValueError("Unexpected TYRES answer policy")
        if len(rendered.assets) != 1 or rendered.assets[0].sha256 != _WHEEL_SHA256:
            raise ValueError("Rendered wheel image is missing or changed")
        table = _visible_table(rendered.shared_context)
        data = scenario.context
        visible_base = _parse_marking(rendered.shared_context)
        if _tire_text(*visible_base) != data.get("base_marking"):
            raise ValueError("Visible factory marking differs from the scenario")
        expected_table: list[tuple[int, tuple[str, ...]]] = []
        raw_table = _json_array(data["table"], "Scenario table")
        rim_headers = _int_tuple(data["table_rims"], "Scenario rim headers", 3)
        for raw_row in raw_table:
            if not isinstance(raw_row, Mapping):
                raise ValueError("Scenario table row is malformed")
            width = _integer(raw_row["width_mm"], "Scenario table width")
            raw_cells = _int_cells(raw_row["aspect_ratios_by_rim"], "Scenario table row", 3)
            expected_cells = tuple(
                "; ".join(_tire_text(width, aspect, rim) for aspect in cell) or "—"
                for rim, cell in zip(rim_headers, raw_cells, strict=True)
            )
            expected_table.append((width, expected_cells))
        if table != tuple(expected_table):
            raise ValueError("Visible table cells differ from the saved table model")
        if question.position == 1:
            rim_match = re.search(r"диаметр диска равен (\d+) дюймам", question.condition)
            if (
                rim_match is None
                or "наибольшей ширины" not in question.condition
                or "миллиметрах" not in question.condition
            ):
                raise ValueError("Question 1 must ask for the largest width at a stated rim")
            rim = int(rim_match.group(1))
            header_line = next(
                line
                for line in rendered.shared_context.splitlines()
                if line.strip().startswith("|")
            )
            headers = tuple(int(value) for value in re.findall(r"\|\s*(\d+)\s*", header_line))
            if rim not in headers:
                raise ValueError("Question 1 requests a missing table column")
            column = headers.index(rim)
            candidates: list[int] = []
            for width, cells in table:
                cell = cells[column]
                if cell != "—":
                    for token in cell.split(";"):
                        marking = _parse_marking(token)
                        if marking[0] != width or marking[2] != rim:
                            raise ValueError("Table tyre marking disagrees with its row or column")
                    candidates.append(width)
            if len(candidates) < 2:
                raise ValueError("Question 1 needs at least two permitted widths")
            answer = str(max(candidates))
            if question.math_model.get("rim") != rim or question.math_model.get("extreme") != "max":
                raise ValueError("Question 1 math model disagrees with its visible table query")
        elif question.position == 2:
            marking = _parse_marking(question.condition)
            if "миллиметров" not in question.condition or question.math_model.get(
                "marking"
            ) != _tire_text(*marking):
                raise ValueError("Question 2 unit or math model disagrees with the visible marking")
            answer = _decimal_text(Decimal(marking[0]) * Decimal(marking[1]) / Decimal(100))
        elif question.position == 3:
            if "миллиметрах" not in question.condition:
                raise ValueError("Question 3 must request the diameter in millimetres")
            marking = _parse_marking(rendered.shared_context)
            if question.math_model.get("factory_marking") != _tire_text(*marking):
                raise ValueError("Question 3 math model disagrees with the factory marking")
            diameter = Decimal(marking[2]) * Decimal("25.4") + (
                Decimal(marking[0]) * Decimal(marking[1]) / Decimal(50)
            )
            answer = _decimal_text(diameter)
        elif question.position == 4:
            matches = _TIRE_PATTERN.findall(question.condition)
            if len(matches) != 2 or " меньше, чем " not in question.condition:
                raise ValueError("Question 4 must compare two tyres in a stated direction")
            first, second = (tuple(int(value) for value in marking) for marking in matches)
            visible_pair = [_tire_text(*first), _tire_text(*second)]
            if (
                "миллиметров" not in question.condition
                or _string_tuple(question.math_model.get("markings"), "Question 4 markings")
                != tuple(visible_pair)
                or question.math_model.get("direction") != "first_smaller"
            ):
                raise ValueError("Question 4 units or math model disagree with its comparison")
            first_d = Decimal(first[2]) * Decimal("25.4") + Decimal(first[0] * first[1]) / Decimal(
                50
            )
            second_d = Decimal(second[2]) * Decimal("25.4") + Decimal(
                second[0] * second[1]
            ) / Decimal(50)
            if first_d >= second_d:
                raise ValueError("Question 4 wording claims a smaller radius for the larger wheel")
            answer = _decimal_text((second_d - first_d) / Decimal(2))
        elif question.position == 5:
            matches = _TIRE_PATTERN.findall(question.condition)
            if len(matches) != 1 or "увеличится" not in question.condition:
                raise ValueError("Question 5 must state an increase and one replacement marking")
            base = _parse_marking(rendered.shared_context)
            replacement = tuple(int(value) for value in matches[0])
            if (
                "процентов" not in question.condition
                or question.math_model.get("factory_marking") != _tire_text(*base)
                or question.math_model.get("replacement_marking") != _tire_text(*replacement)
                or question.math_model.get("rounding") != "0.1"
            ):
                raise ValueError("Question 5 units, rounding, or math model is inconsistent")
            base_d = Decimal(base[2]) * Decimal("25.4") + Decimal(base[0] * base[1]) / Decimal(50)
            new_d = Decimal(replacement[2]) * Decimal("25.4") + Decimal(
                replacement[0] * replacement[1]
            ) / Decimal(50)
            if new_d <= base_d or "округлите до десятых" not in question.condition:
                raise ValueError("Question 5 requires a positive increase rounded to tenths")
            answer = _decimal_text(
                ((new_d / base_d - 1) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            )
        else:
            raise ValueError("Unexpected TYRES question position")
        if answer != question.canonical_answer:
            raise ValueError("Canonical answer differs from independently parsed visible content")
        if (
            not question.hints
            or not question.solution_steps
            or answer not in question.solution_steps[-1]
        ):
            raise ValueError("Hints and solution must expose a complete, checked answer path")
        family_ids = _string_tuple(data["family_ids"], "Scenario family IDs")
        if question.family_id != family_ids[question.position - 1]:
            raise ValueError("Question family is incompatible with this full kit")

    def validate_bundle(
        self,
        scenario: ScenarioDraft,
        questions: tuple[QuestionDraft, ...],
        rendered: RenderedScenario,
    ) -> None:
        if tuple(question.position for question in questions) != (1, 2, 3, 4, 5):
            raise ValueError("TYRES bundle must contain all five questions in order")
        if any(question.scenario_seed != scenario.seed for question in questions):
            raise ValueError("TYRES questions must share the same scenario seed")
        for question in questions:
            self.validate_question(scenario, question, rendered)
        base = _int_tuple(scenario.context["base"], "Factory marking", 3)
        if _parse_marking(rendered.shared_context) != base:
            raise ValueError("Shared rendered context has a different factory tyre")


_FAMILIES = (
    FamilyRegistration(
        "TYRES-TABLE-EXTREME",
        1,
        FamilyStatus.ENABLED_CANDIDATE,
        NUMBER_POLICY_ID,
        NUMBER_POLICY_VERSION,
        False,
        ("FIPI-2026-TYRES-1", "407953", "400984"),
    ),
    FamilyRegistration(
        "TYRES-SIDEWALL",
        2,
        FamilyStatus.ENABLED_CANDIDATE,
        NUMBER_POLICY_ID,
        NUMBER_POLICY_VERSION,
        False,
        ("FIPI-2026-TYRES-2", "462108", "462128"),
    ),
    FamilyRegistration(
        "TYRES-DIAMETER",
        3,
        FamilyStatus.ENABLED_CANDIDATE,
        NUMBER_POLICY_ID,
        NUMBER_POLICY_VERSION,
        False,
        ("FIPI-2026-TYRES-3", "408172"),
    ),
    FamilyRegistration(
        "TYRES-RADIUS-DELTA",
        4,
        FamilyStatus.ENABLED_CANDIDATE,
        NUMBER_POLICY_ID,
        NUMBER_POLICY_VERSION,
        False,
        ("FIPI-2026-TYRES-4",),
    ),
    FamilyRegistration(
        "TYRES-PERCENT-ROTATION",
        5,
        FamilyStatus.ENABLED_CANDIDATE,
        NUMBER_POLICY_ID,
        NUMBER_POLICY_VERSION,
        False,
        ("FIPI-2026-TYRES-5", "408173", "480721"),
    ),
    # V1 assigns task 408171 to position 3, but the live catalog card is type 4.
    # Keep the alternate family unavailable until a compatible full-block fixture exists.
    FamilyRegistration(
        "TYRES-DIAMETER-DELTA",
        4,
        FamilyStatus.ENABLED_CANDIDATE,
        NUMBER_POLICY_ID,
        NUMBER_POLICY_VERSION,
        False,
        ("408171",),
    ),
)


def build_adapter(*, enabled_families: frozenset[str] = frozenset()) -> StoryAdapter:
    """Return TYRES; explicit family activation is reserved for isolated tests."""
    supported = frozenset(family.family_id for family in _FAMILIES if family.position <= 5)
    unknown = enabled_families - supported
    if unknown:
        raise ValueError(f"Cannot enable unsupported TYRES families: {sorted(unknown)}")
    families = tuple(
        FamilyRegistration(
            family.family_id,
            family.position,
            family.status,
            family.answer_policy_id,
            family.answer_policy_version,
            family.family_id in enabled_families,
            family.source_ids,
        )
        for family in _FAMILIES
    )

    class Adapter:
        story_code = STORY_CODE
        generator = TyresGenerator()
        question_builder = TyresQuestionBuilder()
        independent_oracle = TyresOracle()
        renderer = TyresRenderer()
        answer_policies: Mapping[tuple[str, str], AnswerPolicy] = {
            (NUMBER_POLICY_ID, NUMBER_POLICY_VERSION): NumericAnswerPolicy()
        }
        family_registry = families

    return cast(StoryAdapter, Adapter())
