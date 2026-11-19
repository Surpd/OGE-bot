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
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from PIL import Image, ImageDraw, ImageFilter, ImageFont

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
GRID_COLUMNS = 3
GRID_ROWS = 7
PAD = 36
TILE_WIDTH = (WIDTH - 2 * PAD - 2 * 12) // GRID_COLUMNS
TILE_HEIGHT = 106
TILE_GAP_X = 12
TILE_GAP_Y = 12
GRID_TOP = 280
GRID_LEFT = (WIDTH - (GRID_COLUMNS * TILE_WIDTH + (GRID_COLUMNS - 1) * TILE_GAP_X)) // 2

PALETTE = {
    "background": "#F4F6F9",
    "card": "#FFFFFF",
    "ink": "#26344A",
    "muted": "#758198",
    "line": "#E7EBF1",
    "blue": "#527FE3",
    "blue_light": "#EAF0FF",
    "neutral": "#A0A9B8",
    "neutral_light": "#F1F3F6",
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
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def _canvas(height: int) -> Image.Image:
    return Image.new("RGBA", (WIDTH, height), PALETTE["background"])


def _card(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    radius: int = 22,
    fill: str = PALETTE["card"],
) -> None:
    x1, y1, x2, y2 = box
    shadow_pad = 12
    shadow = Image.new("RGBA", (x2 - x1 + shadow_pad * 2, y2 - y1 + shadow_pad * 2))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (shadow_pad, shadow_pad, shadow.width - shadow_pad, shadow.height - shadow_pad),
        radius=radius,
        fill=(38, 52, 74, 16),
    )
    image.alpha_composite(
        shadow.filter(ImageFilter.GaussianBlur(8)), (x1 - shadow_pad, y1 - shadow_pad + 3)
    )
    ImageDraw.Draw(image).rounded_rectangle(box, radius=radius, fill=fill)


def dashboard_tile_values(insights: dict[str, Any]) -> list[tuple[int, int, int, str, bool]]:
    """Return number, correct, answered, rate label, and sample sufficiency."""
    tiles = []
    numbers = insights.get("numbers", {})
    for number in range(1, 20):
        values = numbers.get(number, {})
        answered = max(0, int(values.get("answered_tasks", 0)))
        correct = min(answered, max(0, int(values.get("correct", 0))))
        rate = success_label({"answered_tasks": answered, "correct": correct})
        tiles.append((number, correct, answered, rate, answered >= MIN_ANSWERED_SAMPLE))
    return tiles


def _recommendation(insights: dict[str, Any]) -> str:
    number = recommended_number(insights["numbers"], insights.get("families"))
    if number is not None:
        return f"Можно потренировать №{number}."
    sampled_count = recommendation_sample_count(insights["numbers"])
    if sampled_count < 2 or not has_recommendation_sample(insights["numbers"]):
        return f"Пока недостаточно данных: нужно {MIN_ANSWERED_SAMPLE} ответов на номер."
    return "По изученным номерам явной слабой темы нет."


def render_overview(insights: dict[str, Any]) -> Image.Image:
    total = insights["total"]
    image = _canvas(1240)
    draw = ImageDraw.Draw(image)
    draw.text((PAD, 24), "Мой прогресс", font=_font(42, True), fill=PALETTE["ink"])
    draw.text((PAD, 76), "ОГЭ по математике · задания №1–19", font=_font(23), fill=PALETTE["muted"])

    metric_y, metric_h, metric_gap = 122, 112, 12
    metric_width = (WIDTH - 2 * PAD - 2 * metric_gap) // 3
    metrics = (
        ("Верно", str(max(0, int(total.get("correct", 0))))),
        ("Успешность", success_label(total)),
        ("Пропущено", str(max(0, int(total.get("skipped", 0))))),
    )
    for index, (label, value) in enumerate(metrics):
        x = PAD + index * (metric_width + metric_gap)
        _card(image, (x, metric_y, x + metric_width, metric_y + metric_h), radius=20)
        draw = ImageDraw.Draw(image)
        draw_fitted_text(
            draw,
            (x + 18, metric_y + 12),
            value,
            max_width=metric_width - 36,
            size=46,
            minimum_size=24,
            fill=PALETTE["blue"],
            bold=True,
        )
        draw.text((x + 18, metric_y + 73), label, font=_font(22), fill=PALETTE["muted"])

    draw = ImageDraw.Draw(image)
    draw.text((PAD, 252), "Результаты по номерам", font=_font(24, True), fill=PALETTE["ink"])
    for number, correct, answered, rate, sufficient in dashboard_tile_values(insights):
        index = number - 1
        row, column = divmod(index, GRID_COLUMNS)
        x = GRID_LEFT + column * (TILE_WIDTH + TILE_GAP_X)
        y = GRID_TOP + row * (TILE_HEIGHT + TILE_GAP_Y)
        _card(image, (x, y, x + TILE_WIDTH, y + TILE_HEIGHT), radius=18)
        draw = ImageDraw.Draw(image)
        stripe = PALETTE["blue"] if sufficient else PALETTE["line"]
        draw.rounded_rectangle(
            (x + 12, y + 15, x + 18, y + TILE_HEIGHT - 15), radius=4, fill=stripe
        )
        draw.text(
            (x + 28, y + 14),
            f"№{number}",
            font=_font(22, True),
            fill=PALETTE["ink"] if sufficient else PALETTE["muted"],
        )
        draw.text(
            (x + 28, y + 52), f"{correct}/{answered}", font=_font(25, True), fill=PALETTE["ink"]
        )
        draw_fitted_text(
            draw,
            (x + TILE_WIDTH - 14, y + 53),
            rate,
            max_width=78,
            size=28,
            minimum_size=21,
            fill=PALETTE["blue"] if sufficient else PALETTE["neutral"],
            bold=True,
            anchor="rt",
        )

    rec_y = GRID_TOP + GRID_ROWS * (TILE_HEIGHT + TILE_GAP_Y) - TILE_GAP_Y + 18
    _card(image, (PAD, rec_y, WIDTH - PAD, rec_y + 88), radius=18, fill=PALETTE["blue_light"])
    draw = ImageDraw.Draw(image)
    draw.text(
        (PAD + 20, rec_y + 12), _recommendation(insights), font=_font(22, True), fill=PALETTE["ink"]
    )
    draw.text(
        (PAD + 20, rec_y + 49), "Пропуски показаны отдельно.", font=_font(19), fill=PALETTE["muted"]
    )
    return image.crop((0, 0, WIDTH, rec_y + 102)).convert("RGB")


def render_progress_image(insights: dict[str, Any], page: str = "summary") -> bytes:
    """Render the one-page, all-numbers dashboard; other screens are text."""
    del page
    image = render_overview(insights)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True, compress_level=9)
    data = output.getvalue()
    if len(data) > PHOTO_LIMIT or max(image.size) > 10000:
        raise ValueError("Progress image exceeds Telegram photo limits")
    return data


def progress_image_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Подробнее о номере", callback_data="progress:details")],
            [
                InlineKeyboardButton(text="⚠️ Мои ошибки", callback_data="progress:errors:0"),
                InlineKeyboardButton(text="🕘 История", callback_data="progress:history:0"),
            ],
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="progress:refresh"),
                InlineKeyboardButton(text="↩ В меню", callback_data="nav:main"),
            ],
        ]
    )


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
) -> bool:
    """Render off-loop and send/edit one revision-guarded dashboard photo."""
    from app.bot.navigation import (
        bind_navigation,
        navigation_revision,
        prepare_navigation_markup,
    )

    insights = await load_progress_page(repository, user_id, page)
    try:
        image = await asyncio.to_thread(render_progress_image, insights)
    except (OSError, RuntimeError, ValueError):
        logger.warning("progress_png_render_unavailable")
        return False
    markup = cast(InlineKeyboardMarkup, prepare_navigation_markup(progress_image_keyboard()))
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
