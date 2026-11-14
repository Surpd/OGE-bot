"""Pillow-rendered, deterministic progress dashboard for Telegram photos."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import date, datetime
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path
from typing import Any, cast

from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.persistence.training_insights import (
    _STORY_NAMES,
    family_name,
    training_insights,
    training_record_detail,
)

logger = logging.getLogger(__name__)

WIDTH = 1200
PAGE_SIZE = 4
NUMBER_PAGE_SIZE = 7
PHOTO_LIMIT = 10 * 1024 * 1024

PALETTE = {
    "background": "#F4F6FB",
    "card": "#FFFFFF",
    "ink": "#25324A",
    "muted": "#7E8AA2",
    "line": "#E9EDF5",
    "blue": "#648BEA",
    "blue_light": "#ECF1FF",
    "purple": "#9A82DF",
    "purple_light": "#F1EDFF",
    "green": "#42AD7B",
    "green_light": "#E8F6EF",
    "red": "#D96973",
    "red_light": "#FCEDEF",
    "gray": "#AAB3C2",
    "gray_light": "#F0F2F6",
    "white": "#FFFFFF",
}

RADIUS = 30
PAD = 60


@lru_cache(maxsize=8)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    spec = find_spec("matplotlib")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("Matplotlib fonts are not installed")
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path(next(iter(spec.submodule_search_locations))) / "mpl-data" / "fonts" / "ttf" / name
    return ImageFont.truetype(str(path), size)


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), text or " ", font=font)
    return round(box[2] - box[0])


def draw_fitted_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    max_width: int,
    size: int,
    minimum_size: int = 24,
    fill: str = PALETTE["ink"],
    bold: bool = False,
    anchor: str = "lt",
) -> None:
    font_size = size
    font = _font(font_size, bold)
    while font_size > minimum_size and _measure(draw, text, font) > max_width:
        font_size -= 2
        font = _font(font_size, bold)
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    width: int,
    max_lines: int | None = None,
) -> list[str]:
    """Word-wrap Cyrillic, splitting exceptionally long tokens without clipping."""
    lines: list[str] = []
    current = ""
    for word in str(text).split():
        pieces = [word]
        if _measure(draw, word, font) > width:
            pieces = []
            piece = ""
            for char in word:
                candidate = piece + char
                if piece and _measure(draw, candidate, font) > width:
                    pieces.append(piece)
                    piece = char
                else:
                    piece = candidate
            if piece:
                pieces.append(piece)
        for piece in pieces:
            candidate = f"{current} {piece}" if current else piece
            if current and _measure(draw, candidate, font) > width:
                lines.append(current)
                current = piece
            else:
                current = candidate
    if current:
        lines.append(current)
    if not lines:
        return [""]
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and _measure(draw, last + "…", font) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def _draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    width: int,
    *,
    max_lines: int | None = None,
    line_gap: int = 8,
) -> int:
    x, y = xy
    lines = wrap_text(draw, text, font, width, max_lines)
    line_height = round(font.getbbox("Тд")[3] - font.getbbox("Тд")[1])
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill, anchor="lt")
        y += line_height + line_gap
    return y


def _canvas(height: int) -> Image.Image:
    return Image.new("RGBA", (WIDTH, height), PALETTE["background"])


def rounded_card(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    fill: str = PALETTE["card"],
    radius: int = RADIUS,
) -> None:
    x1, y1, x2, y2 = box
    shadow_pad = 20
    shadow = Image.new("RGBA", (x2 - x1 + shadow_pad * 2, y2 - y1 + shadow_pad * 2))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (shadow_pad, shadow_pad, shadow.width - shadow_pad, shadow.height - shadow_pad),
        radius=radius,
        fill=(34, 57, 99, 22),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    image.alpha_composite(shadow, (x1 - shadow_pad, y1 - shadow_pad + 5))
    ImageDraw.Draw(image).rounded_rectangle(box, radius=radius, fill=fill)


def draw_heading(
    draw: ImageDraw.ImageDraw,
    title: str,
    subtitle: str,
    *,
    y: int = 54,
    eyebrow: str | None = None,
) -> int:
    title_font = _font(58, True)
    subtitle_font = _font(31)
    if eyebrow:
        draw.text((PAD, y), eyebrow.upper(), font=_font(23, True), fill=PALETTE["blue"])
        y += 42
    draw.text((PAD, y), title, font=title_font, fill=PALETTE["ink"])
    y += 76
    draw.text((PAD, y), subtitle, font=subtitle_font, fill=PALETTE["muted"])
    return y + 56


def draw_metric(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: int | str,
    label: str,
    *,
    accent: str = PALETTE["blue"],
    value_size: int = 60,
) -> None:
    x, y = xy
    draw.text((x, y), str(value), font=_font(value_size, True), fill=accent, anchor="lt")
    value_height = _font(value_size, True).getbbox("72")[3]
    draw.text((x, y + value_height + 7), label, font=_font(27), fill=PALETTE["muted"], anchor="lt")


def _exclusive_segments(total: dict[str, Any]) -> list[tuple[str, int, str]]:
    completed = int(total["completed"])
    segments = [
        ("Без подсказки", int(total["unassisted_correct"]), PALETTE["green"]),
        ("С подсказкой", int(total["assisted_correct"]), PALETTE["blue"]),
        ("Старые данные · подсказка неизвестна", int(total["unknown_assistance"]), PALETTE["gray"]),
        ("Две ошибки", int(total["failed"]), PALETTE["red"]),
        ("Пропущено", int(total["skipped"]), "#CBD1DC"),
        ("Открыт разбор", int(total["solutions_viewed"]), PALETTE["purple"]),
    ]
    if sum(value for _, value, _ in segments) != completed:
        raise ValueError("Progress result categories do not partition completed tasks")
    return segments


def draw_donut(
    image: Image.Image,
    box: tuple[int, int, int, int],
    segments: list[tuple[str, int, str]],
    *,
    center_value: int,
) -> None:
    from PIL import ImageDraw as PillowDraw

    x1, y1, x2, y2 = box
    draw = PillowDraw.Draw(image)
    total = sum(value for _, value, _ in segments)
    if total == 0:
        draw.arc(box, 0, 359, fill=PALETTE["line"], width=60)
    else:
        start = -90.0
        for _, value, color in segments:
            if value <= 0:
                continue
            end = start + value * 360.0 / total
            draw.pieslice(box, start=start, end=end, fill=color)
            start = end
    inset = 78
    draw.ellipse((x1 + inset, y1 + inset, x2 - inset, y2 - inset), fill=PALETTE["card"])
    center_x, center_y = (x1 + x2) // 2, (y1 + y2) // 2
    font = _font(86, True)
    draw.text(
        (center_x, center_y - 6), str(center_value), font=font, fill=PALETTE["ink"], anchor="mm"
    )
    draw.text(
        (center_x, center_y + 54), "заданий", font=_font(25), fill=PALETTE["muted"], anchor="mm"
    )


def draw_progress_bar(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    value: int,
    maximum: int,
    *,
    color: str = PALETTE["green"],
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=(y2 - y1) // 2, fill=PALETTE["gray_light"])
    if value <= 0 or maximum <= 0:
        return
    width = round((x2 - x1) * min(value, maximum) / maximum)
    draw.rounded_rectangle((x1, y1, x1 + width, y2), radius=(y2 - y1) // 2, fill=color)


def _recommendation(insights: dict[str, Any]) -> str:
    total = insights["total"]
    if int(total["completed"]) < 5:
        return "Когда накопится больше завершённых заданий, здесь появится рекомендация."
    values = insights["numbers"]
    count, number = max(
        (
            (int(row["error_tasks"]) + int(row["skipped"]), int(n))
            for n, row in values.items()
            if int(row["completed"]) > 0
        ),
        default=(0, 0),
    )
    return f"Попробуй повторить №{number}" if count and number else "Продолжай в том же темпе."


def render_overview(insights: dict[str, Any]) -> Image.Image:
    total = insights["total"]
    completed = int(total["completed"])
    segments = _exclusive_segments(total)
    image = _canvas(1490)
    draw = ImageDraw.Draw(image)
    y = draw_heading(draw, "Мой прогресс", "ОГЭ по математике", eyebrow="ТВОЯ ПРАКТИКА")

    rounded_card(image, (PAD, y, WIDTH - PAD, y + 210), fill=PALETTE["blue_light"])
    draw = ImageDraw.Draw(image)
    draw.text((PAD + 38, y + 30), "Завершённых заданий", font=_font(31), fill=PALETTE["muted"])
    draw_fitted_text(
        draw,
        (PAD + 38, y + 73),
        str(completed),
        max_width=250,
        size=104,
        minimum_size=34,
        fill=PALETTE["ink"],
        bold=True,
    )
    draw.text((PAD + 320, y + 129), "из всех выданных", font=_font(29), fill=PALETTE["muted"])
    issued = int(total["issued"])
    draw_fitted_text(
        draw,
        (WIDTH - PAD - 210, y + 106),
        str(issued),
        max_width=170,
        size=48,
        minimum_size=28,
        fill=PALETTE["blue"],
        bold=True,
        anchor="mm",
    )
    draw.text(
        (WIDTH - PAD - 210, y + 157), "выдано", font=_font(24), fill=PALETTE["muted"], anchor="mm"
    )

    chart_y = y + 246
    rounded_card(image, (PAD, chart_y, WIDTH - PAD, chart_y + 625))
    draw = ImageDraw.Draw(image)
    draw.text((PAD + 34, chart_y + 28), "Результаты", font=_font(36, True), fill=PALETTE["ink"])
    donut_box = (PAD + 44, chart_y + 122, PAD + 474, chart_y + 552)
    draw_donut(image, donut_box, segments, center_value=completed)
    draw = ImageDraw.Draw(image)
    legend_x = PAD + 530
    legend_y = chart_y + 119
    for label, value, color in segments:
        draw.ellipse((legend_x, legend_y + 9, legend_x + 24, legend_y + 33), fill=color)
        _draw_wrapped(
            draw,
            (legend_x + 39, legend_y),
            label,
            _font(26),
            PALETTE["ink"],
            378,
            max_lines=2,
            line_gap=2,
        )
        draw.text(
            (WIDTH - PAD - 34, legend_y + 1),
            str(value),
            font=_font(30, True),
            fill=PALETTE["ink"],
            anchor="rt",
        )
        legend_y += 78

    bottom_y = chart_y + 660
    card_gap = 18
    card_width = (WIDTH - 2 * PAD - card_gap) // 2
    rounded_card(image, (PAD, bottom_y, PAD + card_width, bottom_y + 300))
    rounded_card(image, (PAD + card_width + card_gap, bottom_y, WIDTH - PAD, bottom_y + 300))
    draw = ImageDraw.Draw(image)
    draw.text((PAD + 30, bottom_y + 28), "Ошибки были", font=_font(27, True), fill=PALETTE["muted"])
    draw.text(
        (PAD + 30, bottom_y + 76),
        f"в {int(total['error_tasks'])} заданиях",
        font=_font(38, True),
        fill=PALETTE["red"] if total["error_tasks"] else PALETTE["ink"],
    )
    draw.text(
        (PAD + 30, bottom_y + 148),
        "Ошибочные попытки могут быть",
        font=_font(24),
        fill=PALETTE["muted"],
    )
    draw.text(
        (PAD + 30, bottom_y + 182), "и в решённых заданиях.", font=_font(24), fill=PALETTE["muted"]
    )

    right_x = PAD + card_width + card_gap + 30
    draw.text(
        (right_x, bottom_y + 28),
        "На что обратить внимание",
        font=_font(25, True),
        fill=PALETTE["muted"],
    )
    recommendation = _recommendation(insights)
    draw_round = ImageDraw.Draw(image)
    _draw_wrapped(
        draw_round,
        (right_x, bottom_y + 90),
        recommendation,
        _font(39, True),
        PALETTE["blue"],
        card_width - 60,
        max_lines=3,
        line_gap=8,
    )
    draw.text(
        (right_x, bottom_y + 232), "Без оценок и рейтингов", font=_font(22), fill=PALETTE["muted"]
    )
    return image.convert("RGB")


def render_numbers(insights: dict[str, Any], offset: int) -> Image.Image:
    start = 1 if offset < NUMBER_PAGE_SIZE else NUMBER_PAGE_SIZE + 1
    stop = min(start + NUMBER_PAGE_SIZE, 15)
    visible = list(range(start, stop))
    image = _canvas(1455)
    draw = ImageDraw.Draw(image)
    page_title = f"№{start}–{stop - 1}"
    y = draw_heading(draw, "По номерам", "Результаты завершённых заданий", eyebrow=page_title)
    for number in visible:
        values = insights["numbers"].get(number, {})
        completed = int(values.get("completed", 0))
        correct = int(values.get("correct", 0))
        errors = int(values.get("error_tasks", 0))
        skipped = int(values.get("skipped", 0))
        row_y = y
        rounded_card(image, (PAD, row_y, WIDTH - PAD, row_y + 145))
        draw = ImageDraw.Draw(image)
        number_fill = PALETTE["blue_light"] if completed else PALETTE["gray_light"]
        draw.rounded_rectangle(
            (PAD + 22, row_y + 26, PAD + 128, row_y + 119), radius=23, fill=number_fill
        )
        draw.text(
            (PAD + 75, row_y + 73),
            str(number),
            font=_font(53, True),
            fill=PALETTE["blue"] if completed else PALETTE["gray"],
            anchor="mm",
        )
        text_x = PAD + 160
        if completed:
            draw.text(
                (text_x, row_y + 18),
                f"{correct} из {completed} верно",
                font=_font(33, True),
                fill=PALETTE["ink"],
            )
            color = PALETTE["green"] if correct else PALETTE["red"]
            draw_progress_bar(
                draw,
                (text_x, row_y + 67, WIDTH - PAD - 38, row_y + 83),
                correct,
                completed,
                color=color,
            )
            if completed < 5:
                note = f"Мало данных · ошибки: {errors} · пропуски: {skipped}"
                note_color = PALETTE["muted"]
            else:
                note = f"Ошибки: {errors}   ·   Пропуски: {skipped}"
                note_color = PALETTE["muted"]
            draw.text((text_x, row_y + 94), note, font=_font(24), fill=note_color)
        else:
            draw.text(
                (text_x, row_y + 24), "Пока без занятий", font=_font(31), fill=PALETTE["muted"]
            )
            draw_progress_bar(
                draw,
                (text_x, row_y + 79, WIDTH - PAD - 38, row_y + 95),
                0,
                0,
                color=PALETTE["gray"],
            )
        y += 162
    return image.convert("RGB")


def _status(record: dict[str, Any]) -> tuple[str, str, str | None]:
    outcome = record.get("outcome")
    attempts = record.get("attempt_records") or []
    if outcome in {"issued", "active", "pending"}:
        return "В процессе", PALETTE["muted"], None
    if outcome == "solved":
        success = next((item for item in attempts if item.get("is_correct")), None)
        if success is not None and success.get("used_hint") is True:
            note = "Была ошибка" if record.get("has_error") else None
            return "Верно с подсказкой", PALETTE["blue"], note
        if success is not None and success.get("attempt_no") == 2:
            return "Верно со 2-й попытки", PALETTE["green"], "Была ошибка"
        if success is not None and success.get("attempt_no") == 1:
            note = "Была ошибка" if record.get("has_error") else None
            return "Верно с 1-й попытки", PALETTE["green"], note
        return "Верно · старые данные", PALETTE["green"], "Подсказка неизвестна"
    if outcome == "failed":
        return "Две ошибки", PALETTE["red"], None
    if outcome == "skipped":
        return "Пропущено", PALETTE["gray"], None
    if outcome == "solution_viewed":
        note = "Была ошибка" if record.get("has_error") else None
        return "Открыт разбор", PALETTE["purple"], note
    return "Результат неизвестен", PALETTE["gray"], None


def _date_label(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.strftime("%d.%m.%Y")
    return "Дата неизвестна"


def _record_title(record: dict[str, Any]) -> str:
    family_id = str(record.get("family_id", ""))
    if family_id.startswith("OGE15:"):
        story = _STORY_NAMES.get(family_id.partition(":")[2], "Практика")
        position = record.get("number", "")
        return f"№1–5 · {story}, вопрос {position}"
    number = record.get("number", "?")
    return f"№{number} · {family_name(family_id)}"


def draw_history_row(
    image: Image.Image,
    record: dict[str, Any],
    box: tuple[int, int, int, int],
) -> None:
    x1, y1, x2, y2 = box
    rounded_card(image, box)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((x1 + 20, y1 + 21, x1 + 33, y2 - 21), radius=6, fill=_status(record)[1])
    title = _record_title(record)
    text_x, max_width = x1 + 60, x2 - x1 - 88
    date = _date_label(record.get("issued_at"))
    draw.text((text_x, y1 + 16), date, font=_font(27), fill=PALETTE["muted"])
    status, status_color, note = _status(record)
    title_font = _font(36, True)
    title_lines = wrap_text(draw, title, title_font, max_width, max_lines=2)
    title_line_height = round(title_font.getbbox("Тд")[3] - title_font.getbbox("Тд")[1])
    _draw_wrapped(
        draw,
        (text_x, y1 + 53),
        title,
        title_font,
        PALETTE["ink"],
        max_width,
        max_lines=2,
        line_gap=3,
    )
    title_end = y1 + 53 + len(title_lines) * (title_line_height + 3)
    status_y = max(y1 + 112, title_end + 12)
    chip_text = status
    chip_font = _font(29, True)
    chip_width = min(max_width, _measure(draw, chip_text, chip_font) + 30)
    chip_fill = {
        PALETTE["green"]: PALETTE["green_light"],
        PALETTE["blue"]: PALETTE["blue_light"],
        PALETTE["red"]: PALETTE["red_light"],
        PALETTE["purple"]: PALETTE["purple_light"],
    }.get(status_color, PALETTE["gray_light"])
    draw.rounded_rectangle(
        (text_x, status_y, text_x + chip_width, status_y + 44), radius=18, fill=chip_fill
    )
    _draw_wrapped(
        draw,
        (text_x + 14, status_y + 4),
        chip_text,
        _font(27, True),
        status_color,
        max(1, chip_width - 28),
        max_lines=1,
        line_gap=0,
    )
    if note:
        note_color = PALETTE["red"] if note == "Была ошибка" else PALETTE["muted"]
        note_x = min(text_x + chip_width + 14, x2 - 210)
        _draw_wrapped(
            draw,
            (note_x, status_y + 7),
            note,
            _font(20),
            note_color,
            max(1, x2 - 20 - note_x),
            max_lines=1,
            line_gap=0,
        )


def _history_row_height(record: dict[str, Any]) -> int:
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = _font(36, True)
    title_lines = wrap_text(measure, _record_title(record), font, WIDTH - 2 * PAD - 88, 2)
    line_height = round(font.getbbox("Тд")[3] - font.getbbox("Тд")[1])
    status_y = max(112, 53 + len(title_lines) * (line_height + 3) + 12)
    return status_y + 65


def render_history(insights: dict[str, Any], page: str) -> Image.Image:
    section = page.partition(":")[0]
    errors_only = section == "errors"
    records = insights["errors"] if errors_only else insights["history"]
    count = int(insights.get("page_total", len(records)))
    image = _canvas(1360)
    draw = ImageDraw.Draw(image)
    title = "Ошибки" if errors_only else "История"
    subtitle = (
        f"{count} заданий с ошибками" if errors_only else f"Последние занятия · {count} записей"
    )
    y = draw_heading(
        draw, title, subtitle, eyebrow="РАЗБОР ПОПЫТОК" if errors_only else "ИСТОРИЯ ЗАНЯТИЙ"
    )
    if not records:
        rounded_card(image, (PAD, y, WIDTH - PAD, y + 330))
        draw = ImageDraw.Draw(image)
        draw.ellipse(
            (WIDTH // 2 - 39, y + 44, WIDTH // 2 + 39, y + 122), fill=PALETTE["green_light"]
        )
        draw.text(
            (WIDTH // 2, y + 83), "✓", font=_font(42, True), fill=PALETTE["green"], anchor="mm"
        )
        message = "Пока нет записей" if not errors_only else "Ошибок пока нет"
        draw.text(
            (WIDTH // 2, y + 176), message, font=_font(37, True), fill=PALETTE["ink"], anchor="mm"
        )
        draw.text(
            (WIDTH // 2, y + 235),
            "Здесь появятся результаты практики",
            font=_font(25),
            fill=PALETTE["muted"],
            anchor="mm",
        )
        return image.convert("RGB")
    for record in records[:PAGE_SIZE]:
        row_y = y
        row_height = _history_row_height(record)
        draw_history_row(image, record, (PAD, row_y, WIDTH - PAD, row_y + row_height))
        y += row_height + 16
    return image.convert("RGB")


def render_progress_image(insights: dict[str, Any], page: str = "summary") -> bytes:
    section, _, raw_offset = page.partition(":")
    offset = int(raw_offset) if raw_offset.isascii() and raw_offset.isdigit() else 0
    if section == "numbers":
        image = render_numbers(insights, offset)
    elif section in {"history", "errors"}:
        image = render_history(insights, page)
    else:
        image = render_overview(insights)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True, compress_level=9)
    data = output.getvalue()
    if len(data) > PHOTO_LIMIT or max(image.size) > 10000 or max(image.size) / min(image.size) > 20:
        raise ValueError("Progress image exceeds Telegram photo limits")
    return data


def progress_image_keyboard(section: str, offset: int, total: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📊 Обзор", callback_data="progress:summary"),
            InlineKeyboardButton(text="📚 По номерам", callback_data="progress:numbers:0"),
        ],
        [
            InlineKeyboardButton(text="🕘 История", callback_data="progress:history:0"),
            InlineKeyboardButton(text="⚠️ Ошибки", callback_data="progress:errors:0"),
        ],
        [InlineKeyboardButton(text="↩ В меню", callback_data="nav:main")],
    ]
    if section == "numbers":
        if offset > 0:
            page_buttons = [
                InlineKeyboardButton(text="← Назад", callback_data="progress:numbers:0")
            ]
        else:
            page_buttons = []
        if offset == 0:
            page_buttons.append(
                InlineKeyboardButton(
                    text="Дальше →", callback_data=f"progress:numbers:{NUMBER_PAGE_SIZE}"
                )
            )
        if page_buttons:
            rows.append(page_buttons)
    elif section in {"history", "errors"}:
        page_buttons = []
        if offset > 0:
            page_buttons.append(
                InlineKeyboardButton(
                    text="← Назад", callback_data=f"progress:{section}:{max(0, offset - PAGE_SIZE)}"
                )
            )
        if offset + PAGE_SIZE < total:
            page_buttons.append(
                InlineKeyboardButton(
                    text="Дальше →", callback_data=f"progress:{section}:{offset + PAGE_SIZE}"
                )
            )
        if page_buttons:
            rows.append(page_buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def load_progress_page(repository: Any, user_id: int, page: str) -> dict[str, Any]:
    insights = await training_insights(repository, user_id, page, PAGE_SIZE)
    section = page.partition(":")[0]
    if section in {"history", "errors"}:
        records = insights[section]
        for record in records:
            record_id = record.get("record_id")
            if isinstance(record_id, str):
                detail = await training_record_detail(repository, user_id, record_id)
                if detail is not None:
                    record["attempt_records"] = detail.get("attempt_records", [])
    return insights


async def send_progress_image(
    message: Any,
    repository: Any,
    user_id: int,
    page: str = "summary",
    *,
    edit_existing: bool = False,
) -> bool:
    """Render off-loop and send/edit one revision-guarded dashboard photo."""
    from app.bot.navigation import (
        bind_navigation,
        navigation_revision,
        prepare_navigation_markup,
    )

    insights = await load_progress_page(repository, user_id, page)
    try:
        image = await asyncio.to_thread(render_progress_image, insights, page)
    except (OSError, RuntimeError, ValueError):
        logger.warning("progress_png_render_unavailable")
        return False
    section, _, raw_offset = page.partition(":")
    offset = int(raw_offset) if raw_offset.isascii() and raw_offset.isdigit() else 0
    markup = progress_image_keyboard(section, offset, int(insights.get("page_total", 0)))
    markup = cast(InlineKeyboardMarkup, prepare_navigation_markup(markup))
    photo = BufferedInputFile(image, filename="progress.png")
    try:
        if edit_existing:
            sent = await message.edit_media(InputMediaPhoto(media=photo), reply_markup=markup)
        else:
            sent = await message.answer_photo(photo, reply_markup=markup)
    except (TelegramBadRequest, TelegramNotFound):
        logger.warning("progress_png_delivery_unavailable")
        return False
    if isinstance(sent, Message):
        nav_message = sent
    else:
        nav_message = cast(Message, message)
    await bind_navigation(nav_message, repository, user_id, "progress", navigation_revision(markup))
    return True
