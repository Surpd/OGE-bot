"""Telegram presentation only: never rewrite stored mathematical content.

HTML is supported by pinned aiogram 3.22. Rich-message LaTeX requires a newer
transport and is deliberately not sent through ordinary sendMessage/sendPhoto.
"""

import re
from html import escape
from typing import Any

from aiogram.types import BufferedInputFile, Message

from app.bot.math_fragments import MathFragment
from app.persistence.repository import Repository

_HEADING = re.compile(
    r"^(Задание №[^\n]+|Разбор(?: \(самостоятельное решение не засчитывается\))?:|"
    r"Подсказка:|Ответ:|Правильный ответ:|Правильный вариант:)"
)
_INLINE_ANSWER = re.compile(r"(Ответ:|Правильный ответ:|Правильный вариант:)")


def format_math_message(text: str | MathFragment) -> str:
    """Escape data once; emphasize owned headings without changing notation.

    Normal paragraphs wrap naturally on narrow screens. Avoid code blocks,
    tables, formula images, or interpreting arbitrary source text as HTML/LaTeX.
    """
    source = text if isinstance(text, str) else text.unicode()
    lines = []
    for line in source.split("\n"):
        match = _HEADING.match(line)
        if match:
            title = match.group(0)
            lines.append(f"<b>{escape(title)}</b>{escape(line[len(title) :])}")
        else:
            # Feedback can put the answer after its first sentence.
            match = _INLINE_ANSWER.search(line)
            if match:
                lines.append(
                    escape(line[: match.start()])
                    + f"<b>{escape(match.group(0))}</b>"
                    + escape(line[match.end() :])
                )
            else:
                lines.append(escape(line))
    return "\n".join(lines)


def render_math_fragment(fragment: MathFragment) -> str:
    """Controlled Unicode display; LaTeX export is never sent through this path."""
    return format_math_message(fragment.unicode())


def hint_message(hint: str) -> str:
    return f"Подсказка:\n\n{hint}"


async def _bind_navigation(
    message: Message,
    repository: Repository,
    sent: Message,
    markup: object,
    user_id_override: int | None = None,
) -> None:
    # Lazy import keeps presentation usable independently of navigation routing.
    from app.bot.navigation import bind_navigation, navigation_screen

    screen = navigation_screen(markup)
    user_id = user_id_override
    if user_id is None and message.from_user is not None:
        user_id = message.from_user.id
    if screen is not None and user_id is not None:
        await bind_navigation(sent, repository, user_id, screen)


async def send_text(
    message: Message,
    repository: Repository,
    text: str | MathFragment,
    *,
    user_id_override: int | None = None,
    **kwargs: Any,
) -> Message:
    sent = await message.answer(format_math_message(text), parse_mode="HTML", **kwargs)
    await _bind_navigation(message, repository, sent, kwargs.get("reply_markup"), user_id_override)
    return sent


async def send_photo(
    message: Message,
    repository: Repository,
    photo: BufferedInputFile,
    *,
    caption: str | MathFragment,
    user_id_override: int | None = None,
    **kwargs: Any,
) -> Message:
    sent = await message.answer_photo(
        photo, caption=format_math_message(caption), parse_mode="HTML", **kwargs
    )
    await _bind_navigation(message, repository, sent, kwargs.get("reply_markup"), user_id_override)
    return sent
