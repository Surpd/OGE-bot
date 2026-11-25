"""Compact, single-image progress dashboard for Telegram."""

from __future__ import annotations

import asyncio
import io
import logging
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path
from typing import Any, cast

from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from PIL import Image, ImageColor, ImageDraw, ImageFont

from app.persistence.training_insights import (
    MIN_ANSWERED_SAMPLE,
    has_recommendation_sample,
    recommendation_sample_count,
    recommended_number,
    success_label,
    training_insights,
)

logger = logging.getLogger(__name__)

WIDTH = 1200
PHOTO_LIMIT = 10 * 1024 * 1024
GRID_COLUMNS = 5
GRID_ROWS = 4
PAD = 44
TILE_GAP_X = 9
TILE_GAP_Y = 9
TILE_WIDTH = (WIDTH - 2 * PAD - (GRID_COLUMNS - 1) * TILE_GAP_X) // GRID_COLUMNS
TILE_HEIGHT = 126
GRID_TOP = 407

PALETTE = {
    "background": "#F7F7F1",
    "card": "#FFFFFF",
    "ink": "#1F3531",
    "muted": "#53665D",
    "line": "#CBD5CB",
    "blue": "#527FE3",
    "blue_light": "#EAF0FF",
    "neutral": "#1F3531",
    "neutral_light": "#F1F3F6",
    "red": "#AD3732",
    "yellow": "#916A15",
    "green": "#256D49",
}


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
    minimum_size: int = 18,
    fill: str = PALETTE["ink"],
    bold: bool = False,
    anchor: str = "lt",
) -> None:
    font_size = size
    font = _font(font_size, bold)
    while font_size > minimum_size and _measure(draw, text, font) > max_width:
        font_size -= 1
        font = _font(font_size, bold)
    if _measure(draw, text, font) > max_width:
        while text and _measure(draw, text + "…", font) > max_width:
            text = text[:-1]
        text += "…"
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def dashboard_tile_values(
    insights: dict[str, Any], task_count: int = 19
) -> list[tuple[int, int, int, str, bool]]:
    """Return number, correct, answered, rate label, and sample sufficiency."""
    tiles = []
    numbers = insights.get("numbers", {})
    if task_count not in (19, 25):
        raise ValueError("Unsupported dashboard size")
    for number in range(1, task_count + 1):
        values = numbers.get(number, {})
        if number > 19:
            written = insights.get("written", {}).get(number, {})
            values = {
                "correct": written.get("first_full", 0),
                "answered_tasks": written.get("first_graded", 0),
            }
        answered = max(0, int(values.get("answered_tasks", 0)))
        correct = min(answered, max(0, int(values.get("correct", 0))))
        rate = success_label({"answered_tasks": answered, "correct": correct})
        tiles.append((number, correct, answered, rate, answered >= MIN_ANSWERED_SAMPLE))
    return tiles


def _rate_color(correct: int, answered: int) -> str:
    if not answered:
        return PALETTE["muted"]
    scaled = 2 * min(1, max(0, correct / answered))
    left, right = ("red", "yellow") if scaled <= 1 else ("yellow", "green")
    weight = scaled if scaled <= 1 else scaled - 1
    channels = zip(ImageColor.getrgb(PALETTE[left]), ImageColor.getrgb(PALETTE[right]), strict=True)
    return "#" + "".join(f"{round(a + (b - a) * weight):02X}" for a, b in channels)


def dashboard_tile_accent(correct: int, answered: int) -> str:
    return _rate_color(correct, answered) if answered >= MIN_ANSWERED_SAMPLE else PALETTE["neutral"]


def _recommendation(insights: dict[str, Any]) -> str:
    if insights.get("personal_tip"):
        return str(insights["personal_tip"])
    if insights["total"]["answered_tasks"] == 0:
        return "Начните со смешанной тренировки."
    number = recommended_number(insights["numbers"], insights.get("families"))
    if number is not None:
        return f"Можно потренировать №{number}."
    sampled_count = recommendation_sample_count(insights["numbers"])
    if sampled_count < 2 or not has_recommendation_sample(insights["numbers"]):
        return f"Пока недостаточно данных: нужно {MIN_ANSWERED_SAMPLE} ответов на номер."
    return "По изученным номерам явной слабой темы нет."


def render_overview(insights: dict[str, Any], task_count: int = 19) -> Image.Image:
    total = insights["total"]
    tiles = dashboard_tile_values(insights, task_count)
    row_count = (len(tiles) + GRID_COLUMNS - 1) // GRID_COLUMNS
    grid_bottom = GRID_TOP + row_count * TILE_HEIGHT + (row_count - 1) * TILE_GAP_Y
    right = WIDTH - PAD
    name = " ".join(insights.get("display_identity", "").split())
    handle = insights.get("display_handle", "")
    shift = 0 if name or handle else 56
    image = Image.new("RGB", (WIDTH, grid_bottom + 113 - shift), PALETTE["background"])
    draw = ImageDraw.Draw(image)
    ink, muted, line = PALETTE["ink"], PALETTE["muted"], PALETTE["line"]

    if name or handle:
        account = name or handle
        draw.ellipse((PAD, 42, PAD + 58, 100), fill=ink)
        draw.text(
            (PAD + 29, 70),
            account.lstrip("@")[:1].upper(),
            font=_font(34, True),
            fill=PALETTE["background"],
            anchor="mm",
        )
        draw_fitted_text(
            draw,
            (PAD + 78, 38 if name and handle else 55),
            account,
            max_width=right - PAD - 78,
            size=34,
            bold=True,
        )
        if name and handle:
            draw_fitted_text(
                draw, (PAD + 78, 80), handle, max_width=right - PAD - 78, size=25, fill=muted
            )
    title_y = 123 - shift
    draw.text((PAD - 3, title_y), "Твой прогресс", font=_font(69, True), fill=ink, anchor="lt")
    draw.rounded_rectangle((PAD, title_y + 73, PAD + 148, title_y + 81), radius=4, fill="#F15E45")
    for y in (231, 347):
        draw.line((PAD, y - shift, right, y - shift), fill=line, width=2)
    metrics = (
        (
            "УСПЕШНОСТЬ",
            success_label(total),
            _rate_color(total["correct"], total["answered_tasks"]),
        ),
        ("ВЕРНО", str(total["correct"]), ink),
        ("ПРОПУЩЕНО", str(total["skipped"]), ink),
    )
    if task_count == 25:
        draw.text(
            (right, title_y + 81), "СВОДКА №1–19", font=_font(24, True), fill=muted, anchor="rb"
        )
    for index, (label, value, color) in enumerate(metrics):
        x = (PAD, 471, 840)[index]
        if index:
            draw.line((x - 32, 248 - shift, x - 32, 331 - shift), fill=line, width=2)
        draw_fitted_text(
            draw,
            (x, 247 - shift),
            value,
            max_width=right - x if index == 2 else 335,
            size=68,
            bold=True,
            fill=color,
        )
        draw.text((x, 314 - shift), label, font=_font(25, True), fill=muted, anchor="lt")
    draw.text((PAD, 366 - shift), "По номерам", font=_font(38, True), fill=ink, anchor="lt")
    draw.text(
        (right, 395 - shift), f"{task_count} ЗАДАНИЙ", font=_font(24, True), fill=muted, anchor="rb"
    )

    for number, correct, answered, rate, sufficient in tiles:
        row, col = divmod(number - 1, GRID_COLUMNS)
        x = PAD + col * (TILE_WIDTH + TILE_GAP_X)
        y = GRID_TOP + row * (TILE_HEIGHT + TILE_GAP_Y) - shift
        draw.rounded_rectangle(
            (x, y, x + TILE_WIDTH, y + TILE_HEIGHT),
            radius=13,
            fill="#EAEEE6",
            outline="#D8DED5",
            width=2,
        )
        accent = _rate_color(correct, answered)
        panel = "#E1E7E0"
        if answered:
            tint = 0.14 if sufficient else 0.085
            rgb = ImageColor.getrgb(accent)
            paper = ImageColor.getrgb(PALETTE["background"])
            panel = "#" + "".join(
                f"{round(base * (1 - tint) + channel * tint):02x}"
                for base, channel in zip(paper, rgb, strict=True)
            )
        panel_left, panel_right = x + 102, x + TILE_WIDTH - 10
        draw.rounded_rectangle(
            (panel_left, y + 13, panel_right, y + TILE_HEIGHT - 13), radius=9, fill=panel
        )
        draw_fitted_text(
            draw,
            (x + 12, y + 19),
            f"№{number}",
            max_width=86,
            size=34,
            bold=True,
            fill=dashboard_tile_accent(correct, answered),
        )
        draw_fitted_text(draw, (x + 12, y + 81), f"{correct}/{answered}", max_width=86, size=30)
        draw_fitted_text(
            draw,
            ((panel_left + panel_right) // 2, y + TILE_HEIGHT // 2),
            rate,
            max_width=panel_right - panel_left - 9,
            size=36,
            bold=True,
            fill=accent,
            anchor="mm",
        )

    footer = grid_bottom - shift
    draw.line((PAD, footer + 19, right, footer + 19), fill=line, width=2)
    draw.text(
        (PAD, footer + 34),
        "До 5 ответов процент предварительный.",
        font=_font(26),
        fill=muted,
        anchor="lt",
    )
    legend_width = 200
    for i in range(legend_width):
        gx = right - legend_width + i
        draw.line((gx, footer + 38, gx, footer + 47), fill=_rate_color(i, legend_width - 1))
    for x, label, anchor in ((right - legend_width, "0%", "lt"), (right, "100%", "rt")):
        draw.text((x, footer + 56), label, font=_font(22), fill=muted, anchor=anchor)
    note = (
        "№20–25 · Первые работы с 2 баллами из оценённых GPT."
        if task_count == 25
        else _recommendation(insights)
    )
    draw_fitted_text(draw, (PAD, footer + 73), note, max_width=right - PAD, size=26, fill=ink)
    return image


def render_progress_image(
    insights: dict[str, Any], page: str = "summary", *, task_count: int = 19
) -> bytes:
    """Render the one-page, all-numbers dashboard; other screens are text."""
    del page
    image = render_overview(insights, 25 if "written" in insights else task_count)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True, compress_level=9)
    data = output.getvalue()
    if len(data) > PHOTO_LIMIT or max(image.size) > 10000:
        raise ValueError("Progress image exceeds Telegram photo limits")
    return data


def progress_image_keyboard(insights: dict[str, Any] | None = None) -> InlineKeyboardMarkup:
    from app.bot.progress import progress_keyboard

    return progress_keyboard(insights=insights)


async def load_progress_page(
    repository: Any, user_id: int, page: str = "summary"
) -> dict[str, Any]:
    del page
    insights = await training_insights(repository, user_id, "summary")
    from app.bot.part2 import store
    from app.persistence.part2_insights import summary

    bank = store(repository)
    if bank:
        insights["written"] = await summary(bank.pool, user_id)
    return insights


async def send_progress_image(
    message: Any,
    repository: Any,
    user_id: int,
    page: str = "summary",
    *,
    edit_existing: bool = False,
    viewer: Any = None,
) -> bool:
    """Render off-loop and send/edit one revision-guarded dashboard photo."""
    from app.bot.navigation import (
        bind_navigation,
        navigation_revision,
        prepare_navigation_markup,
    )

    insights = await load_progress_page(repository, user_id, page)
    viewer = viewer or getattr(message, "from_user", None)
    if viewer and viewer.id == user_id and not viewer.is_bot:
        handle = f"@{viewer.username}" if viewer.username else ""
        insights = {**insights, "display_identity": viewer.full_name, "display_handle": handle}
    try:
        image = await asyncio.to_thread(render_progress_image, insights)
    except (OSError, RuntimeError, ValueError):
        logger.warning("progress_png_render_unavailable")
        return False
    markup = cast(
        InlineKeyboardMarkup, prepare_navigation_markup(progress_image_keyboard(insights))
    )
    photo = BufferedInputFile(image, filename="progress.png")
    try:
        if edit_existing:
            sent = await message.edit_media(InputMediaPhoto(media=photo), reply_markup=markup)
        else:
            sent = await message.answer_photo(photo, reply_markup=markup)
    except (TelegramBadRequest, TelegramNotFound):
        logger.warning("progress_png_delivery_unavailable")
        return False
    nav_message = sent if isinstance(sent, Message) else cast(Message, message)
    await bind_navigation(nav_message, repository, user_id, "progress", navigation_revision(markup))
    return True
