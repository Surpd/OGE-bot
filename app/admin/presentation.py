"""Assemble a Telegram report without binding it to a chat or storage."""

from dataclasses import dataclass
from html import unescape
from re import sub
from typing import Any

from aiogram.types import InlineKeyboardMarkup

from app.admin.screens import Data, screen_copy
from app.admin.visuals import render_summary
from app.bot.visual_delivery import PHOTO_LIMIT, build_visual

CAPTION_LIMIT = 1024


@dataclass(frozen=True)
class AdminView:
    text: str
    markup: InlineKeyboardMarkup
    photo: bytes | None = None
    caption: str | None = None


def render_admin_view(screen: str, data: Data, **context: Any) -> AdminView:
    copy = screen_copy(screen, data, **context)
    if context.get("expanded"):
        return AdminView(copy.text, copy.markup)
    # Telegram's caption bound applies to visible text after parsing entities.
    plain = unescape(sub(r"</?(?:b|code)>", "", copy.caption))
    if len(plain.encode("utf-16-le")) > CAPTION_LIMIT * 2:
        return AdminView(copy.text, copy.markup)
    photo = build_visual(screen, lambda: render_summary(screen, data, **context))
    if photo is not None and len(photo) <= PHOTO_LIMIT:
        return AdminView(copy.text, copy.markup, photo, copy.caption or None)
    return AdminView(copy.compact_text or copy.text, copy.markup)
