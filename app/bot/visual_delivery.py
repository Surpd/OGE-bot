"""Optional presentation transport for the branded menu and progress cards."""

import asyncio
import logging
from collections.abc import Callable
from functools import lru_cache
from typing import cast

from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    ReplyParameters,
)

from app.bot.visual_models import VisualCard
from app.config import get_settings
from app.persistence.repository import Repository

logger = logging.getLogger(__name__)
PHOTO_LIMIT = 10 * 1024 * 1024
_MENU_CARDS = frozenset({"welcome", "numbers", "part2", "stories", "types"})
_SCREEN_FLAGS = {
    screen: f"oge_visual_{screen}_enabled"
    for screen in (*_MENU_CARDS, "number_progress", "training_result")
}


def _viewer_id(message: Message, override: int | None) -> int | None:
    if override is not None:
        return override
    viewer = message.from_user
    return viewer.id if viewer is not None and not viewer.is_bot else None


@lru_cache(maxsize=16)
def _allowed_users(value: str) -> frozenset[int]:
    parts = [part.strip() for part in value.split(",")]
    if not all(part.isascii() and part.isdecimal() and len(part) <= 20 for part in parts):
        return frozenset()
    return frozenset(int(part) for part in parts if int(part) > 0)


def visual_enabled(screen: str, message: Message, user_id_override: int | None = None) -> bool:
    settings = get_settings()
    flag = _SCREEN_FLAGS.get(screen)
    if (
        flag is None
        or not getattr(settings, flag)
        or settings.oge_visual_companion_only
        or (screen == "part2" and not settings.oge_part2_enabled)
        or message.chat.type != "private"
    ):
        return False
    user_id = _viewer_id(message, user_id_override)
    allowlist = settings.oge_visual_user_ids.strip()
    return user_id is not None and (not allowlist or user_id in _allowed_users(allowlist))


def build_visual[T](screen: str, factory: Callable[[], T]) -> T | None:
    """A failing optional projection should leave the original navigation intact."""
    try:
        return factory()
    except Exception as error:
        logger.warning(
            "visual_png_projection_failed screen=%s type=%s", screen, type(error).__name__
        )
        return None


def _render_png(card: VisualCard) -> bytes:
    from app.bot.visual_cards import render_card

    png = render_card(card)
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > PHOTO_LIMIT:
        raise ValueError("Invalid visual PNG")
    return png


@lru_cache(maxsize=48)
def _render_menu_png(card: VisualCard) -> bytes:
    return _render_png(card)


async def try_send_visual(
    message: Message,
    repository: Repository,
    card: VisualCard,
    markup: InlineKeyboardMarkup | None = None,
    *,
    user_id_override: int | None = None,
    reply_parameters: ReplyParameters | None = None,
) -> Message | None:
    """Return None for the legacy path when the card cannot be created or accepted."""
    if not visual_enabled(card.screen, message, user_id_override):
        return None
    from app.bot.navigation import (
        NavigationMessage,
        bind_navigation,
        navigation_revision,
        navigation_screen,
        prepare_navigation_markup,
    )

    try:
        render = _render_menu_png if card.screen in _MENU_CARDS else _render_png
        png = await asyncio.to_thread(render, card)
    except Exception as error:
        logger.warning(
            "visual_png_render_failed screen=%s type=%s", card.screen, type(error).__name__
        )
        return None

    prepared = cast(InlineKeyboardMarkup | None, prepare_navigation_markup(markup))
    screen = navigation_screen(prepared)
    photo = BufferedInputFile(png, filename=f"bop-{card.screen.replace('_', '-')}.png")
    edit_target = message.visual_edit_target() if isinstance(message, NavigationMessage) else None
    sent = None
    if screen is not None and reply_parameters is None and edit_target is not None:
        try:
            edited = await edit_target.edit_media(
                InputMediaPhoto(media=photo), reply_markup=prepared
            )
            sent = edited if isinstance(edited, Message) else edit_target
        except (TelegramBadRequest, TelegramNotFound):
            # A rejected edit has no delivery side effect. Try a fresh photo once.
            pass
    if sent is None:
        try:
            sent = await message.answer_photo(
                photo, reply_markup=prepared, reply_parameters=reply_parameters
            )
        except (TelegramBadRequest, TelegramNotFound) as error:
            logger.warning(
                "visual_png_delivery_rejected screen=%s type=%s", card.screen, type(error).__name__
            )
            return None
    # Network errors are ambiguous. Never issue a second message or bind a menu
    # until Telegram returns the actual message ID.
    user_id = _viewer_id(message, user_id_override)
    if screen is not None and user_id is not None:
        await bind_navigation(sent, repository, user_id, screen, navigation_revision(prepared))
    return sent
