"""Telegram presentation only: never rewrite stored mathematical content.

Rich HTML is sent only through sendRichMessage. Definite API rejection falls
back to one locally typeset photo. Ambiguous network failures are never retried
as a different message, preventing duplicate problem delivery.
"""

import asyncio
import re
from html import escape
from typing import Any

from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.types import (
    BufferedInputFile,
    InputMediaPhoto,
    InputRichMessage,
    InputRichMessageMedia,
    Message,
)

from app.bot.math_fragments import MathFragment
from app.bot.math_layout import action_prefix, layout_text
from app.bot.math_notation import math_spans, parse_formula, rich_inline
from app.persistence.repository import Repository

_HEADING = re.compile(
    r"^(Задание №[^\n]+|Разбор(?: \(самостоятельное решение не засчитывается\))?:|"
    r"Подсказка(?: №\d+)?:|Ответ:|Правильный ответ:|Правильный вариант:)"
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


def hint_message(hint: str, problem: object = None) -> str:
    hints = problem.get("hints") if isinstance(problem, dict) else None
    number = ""
    if isinstance(hints, list | tuple) and len(hints) > 1 and hint in hints:
        number = f" №{hints.index(hint) + 1}"
    return f"Подсказка{number}:\n\n{hint}"


def format_rich_message(
    source: str | MathFragment,
    *,
    system_rows: tuple[str, ...] | None = None,
) -> str:
    if not isinstance(source, str):
        return "<tg-math-block>" + escape(source.latex()) + "</tg-math-block>"
    lines = []
    solution = False
    source_lines = layout_text(source).split("\n")
    skipped = 0
    for index, line in enumerate(source_lines):
        if skipped:
            skipped -= 1
            continue
        if system_rows and source_lines[index : index + len(system_rows)] == list(system_rows):
            formulas = [parse_formula(row) for row in system_rows]
            if all(formula is not None for formula in formulas):
                latex = (
                    r"\begin{cases}" + r" \\ ".join(str(row) for row in formulas) + r"\end{cases}"
                )
                lines.append("<tg-math-block>" + escape(latex) + "</tg-math-block>")
                skipped = len(system_rows) - 1
                continue
        match = _HEADING.match(line)
        if match:
            title = match.group(0)
            lines.append(
                "<p><b>" + escape(title) + "</b>" + rich_inline(line[len(title) :]) + "</p>"
            )
            solution = title.startswith("Разбор")
        elif solution and line.strip():
            # Action names are separated from the checked formula by a colon.
            prefix = action_prefix(line)
            if prefix is not None:
                body = "<b>" + escape(prefix) + "</b>" + rich_inline(line[len(prefix) :])
            else:
                body = rich_inline(line)
            lines.append(f"<p>{body}</p>")
        else:
            spans = math_spans(line.strip())
            if (
                len(spans) == 1
                and spans[0].latex is not None
                and "∞" not in spans[0].source
            ):
                lines.append("<tg-math-block>" + escape(spans[0].latex) + "</tg-math-block>")
            else:
                lines.append("<p>" + rich_inline(line) + "</p>")
    return "".join(lines)


def _has_math(text: str | MathFragment) -> bool:
    return not isinstance(text, str) or any(span.latex is not None for span in math_spans(text))


def _has_telegram_transport(message: object) -> bool:
    return isinstance(message, Message) or isinstance(getattr(message, "_message", None), Message)


async def _prefer_png(message: Message, repository: Repository, override: int | None) -> bool:
    user_id = override
    if user_id is None and message.from_user is not None and not message.from_user.is_bot:
        user_id = message.from_user.id
    if user_id is None and message.chat.type == "private":
        user_id = message.chat.id
    return user_id is not None and await repository.math_display(user_id) == "png"


async def _send_mathematics(
    message: Message,
    text: str | MathFragment,
    photo: BufferedInputFile | None,
    kwargs: dict[str, Any],
    force_png: bool = False,
    system_rows: tuple[str, ...] | None = None,
) -> Message:
    if force_png:
        return await _send_math_image(message, text, photo, kwargs, system_rows)
    rich = format_rich_message(text, system_rows=system_rows)
    media = None
    if photo is not None:
        rich = '<img src="tg://photo?id=diagram"/>' + rich
        media = [InputRichMessageMedia(id="diagram", media=InputMediaPhoto(media=photo))]
    try:
        bot = message.bot
        if bot is None:
            raise RuntimeError("Mathematical transport needs a mounted bot")
        return await bot.send_rich_message(
            chat_id=message.chat.id,
            message_thread_id=message.message_thread_id,
            rich_message=InputRichMessage(html=rich, media=media),
            **kwargs,
        )
    except (TelegramBadRequest, TelegramNotFound):
        # Only a definite rejection means no message was created. Timeouts,
        # transport failures, rate limits and server errors must propagate.
        return await _send_math_image(message, text, photo, kwargs, system_rows)


async def _send_math_image(
    message: Message,
    text: str | MathFragment,
    photo: BufferedInputFile | None,
    kwargs: dict[str, Any],
    system_rows: tuple[str, ...] | None = None,
) -> Message:
    from app.bot.math_image import render_math_image

    image = await asyncio.to_thread(
        render_math_image,
        text,
        None if photo is None else photo.data,
        system_rows,
    )
    bot = message.bot
    if bot is None:
        raise RuntimeError("Mathematical transport needs a mounted bot")
    return await bot.send_photo(
        chat_id=message.chat.id,
        message_thread_id=message.message_thread_id,
        photo=BufferedInputFile(image, filename="mathematics.png"),
        **kwargs,
    )


async def _bind_navigation(
    message: Message,
    repository: Repository,
    sent: Message,
    markup: object,
    user_id_override: int | None = None,
) -> None:
    # Lazy import keeps presentation usable independently of navigation routing.
    from app.bot.navigation import bind_navigation, navigation_revision, navigation_screen

    screen = navigation_screen(markup)
    user_id = user_id_override
    if user_id is None and message.from_user is not None:
        user_id = message.from_user.id
    if screen is not None and user_id is not None:
        await bind_navigation(sent, repository, user_id, screen, navigation_revision(markup))


async def send_text(
    message: Message,
    repository: Repository,
    text: str | MathFragment,
    *,
    user_id_override: int | None = None,
    math_system_rows: tuple[str, ...] | None = None,
    **kwargs: Any,
) -> Message:
    from app.bot.navigation import navigation_screen, prepare_navigation_markup

    if "reply_markup" in kwargs:
        kwargs["reply_markup"] = prepare_navigation_markup(kwargs["reply_markup"])
    if (
        _has_telegram_transport(message)
        and navigation_screen(kwargs.get("reply_markup")) is None
        and _has_math(text)
    ):
        sent = await _send_mathematics(
            message,
            text,
            None,
            kwargs,
            force_png=await _prefer_png(message, repository, user_id_override),
            system_rows=math_system_rows,
        )
    else:
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
    math_system_rows: tuple[str, ...] | None = None,
    **kwargs: Any,
) -> Message:
    from app.bot.navigation import prepare_navigation_markup

    if "reply_markup" in kwargs:
        kwargs["reply_markup"] = prepare_navigation_markup(kwargs["reply_markup"])
    if _has_telegram_transport(message) and _has_math(caption):
        sent = await _send_mathematics(
            message,
            caption,
            photo,
            kwargs,
            force_png=await _prefer_png(message, repository, user_id_override),
            system_rows=math_system_rows,
        )
    else:
        sent = await message.answer_photo(
            photo, caption=format_math_message(caption), parse_mode="HTML", **kwargs
        )
    await _bind_navigation(message, repository, sent, kwargs.get("reply_markup"), user_id_override)
    return sent
