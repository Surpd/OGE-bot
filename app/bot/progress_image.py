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

WIDTH = 900
PHOTO_LIMIT = 10 * 1024 * 1024
GRID_COLUMNS = 5
GRID_ROWS = 4
PAD = 22
TILE_WIDTH = (WIDTH - 2 * PAD - 4 * 6) // GRID_COLUMNS
TILE_HEIGHT = 88
TILE_GAP_X = 6
TILE_GAP_Y = 6
GRID_TOP = 242
GRID_LEFT = (WIDTH - (GRID_COLUMNS * TILE_WIDTH + (GRID_COLUMNS - 1) * TILE_GAP_X)) // 2

PALETTE = {
    "background": "#F7F7F1",
    "card": "#FFFFFF",
    "ink": "#203832",
    "muted": "#53665D",
    "line": "#CBD5CB",
    "blue": "#527FE3",
    "blue_light": "#EAF0FF",
    "neutral": "#536479",
    "neutral_light": "#F1F3F6",
    "red": "#AC3545",
    "yellow": "#895707",
    "green": "#176F4C",
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
    footer = GRID_TOP + ((len(tiles) + 4) // 5) * (TILE_HEIGHT + TILE_GAP_Y)
    image = Image.new("RGB", (WIDTH, footer + 74), PALETTE["background"])
    draw = ImageDraw.Draw(image)
    identity = insights.get("display_identity", "")
    if identity:
        draw_fitted_text(draw, (PAD, 12), identity, max_width=WIDTH - 2 * PAD, size=24)
    draw.text((PAD, 44), "Твой прогресс", font=_font(48, True), fill=PALETTE["ink"], anchor="lt")
    draw.line((PAD, 109, WIDTH - PAD, 109), fill=PALETTE["line"], width=2)
    metrics = (
        (
            "Успешность",
            success_label(total),
            _rate_color(total["correct"], total["answered_tasks"]),
        ),
        ("Верно", str(total["correct"]), PALETTE["ink"]),
        ("Пропущено", str(total["skipped"]), PALETTE["ink"]),
    )
    for index, (label, value, color) in enumerate(metrics):
        x = PAD + index * ((WIDTH - 2 * PAD) // 3)
        draw_fitted_text(draw, (x, 120), value, max_width=270, size=45, bold=True, fill=color)
        draw.text((x, 171), label, font=_font(23), fill=PALETTE["muted"], anchor="lt")
    draw.text((PAD, 211), "По номерам", font=_font(25, True), fill=PALETTE["ink"], anchor="lt")
    for number, correct, answered, rate, _ in tiles:
        row, col = divmod(number - 1, GRID_COLUMNS)
        x = GRID_LEFT + col * (TILE_WIDTH + TILE_GAP_X)
        y = GRID_TOP + row * (TILE_HEIGHT + TILE_GAP_Y)
        draw.rounded_rectangle((x, y, x + TILE_WIDTH, y + TILE_HEIGHT), radius=10, fill="#E9EEE7")
        draw.rounded_rectangle(
            (x + 78, y + 6, x + TILE_WIDTH - 5, y + TILE_HEIGHT - 6), radius=7, fill="#DFE7DF"
        )
        draw_fitted_text(
            draw,
            (x + 6, y + 14),
            f"№{number}",
            max_width=68,
            size=28,
            bold=True,
            fill=dashboard_tile_accent(correct, answered),
        )
        draw_fitted_text(draw, (x + 6, y + 53), f"{correct}/{answered}", max_width=68, size=25)
        draw_fitted_text(
            draw,
            (x + (78 + TILE_WIDTH - 5) // 2, y + TILE_HEIGHT // 2),
            rate,
            max_width=75,
            size=32,
            bold=True,
            fill=_rate_color(correct, answered),
            anchor="mm",
        )
    draw.text(
        (PAD, footer + 7),
        "До 5 ответов процент предварительный.",
        font=_font(23),
        fill=PALETTE["muted"],
        anchor="lt",
    )
    draw_fitted_text(
        draw, (PAD, footer + 41), _recommendation(insights), max_width=WIDTH - 2 * PAD, size=23
    )
    return image


def render_progress_image(
    insights: dict[str, Any], page: str = "summary", *, task_count: int = 19
) -> bytes:
    """Render the one-page, all-numbers dashboard; other screens are text."""
    del page
    image = render_overview(insights, task_count)
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
    return await training_insights(repository, user_id, "summary")


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
        insights = {**insights, "display_identity": f"{viewer.full_name}  {handle}".strip()}
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
