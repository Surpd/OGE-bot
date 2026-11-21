"""Telegram presentation only: never rewrite stored mathematical content.

Rich HTML is sent only through sendRichMessage. Confirmed Rich incompatibility falls
back to one locally typeset photo. Ambiguous network failures are never retried
as a different message, preventing duplicate problem delivery.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable
from html import escape
from typing import Any

from aiogram.exceptions import (
    ClientDecodeError,
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramServerError,
)
from aiogram.types import (
    BufferedInputFile,
    InputMediaPhoto,
    InputRichMessage,
    InputRichMessageMedia,
    Message,
)
from aiogram.utils.formatting import Text

from app.bot.explicit_math import flatten_math_lines, formulas, plain_text
from app.bot.family_display import formats, template_key, typeset_family_text
from app.bot.math_fragments import MathFragment
from app.bot.math_layout import action_prefix, layout_text
from app.bot.math_notation import (
    math_spans,
    parse_formula,
    rich_inline,
    rich_needs_png_fallback,
)
from app.persistence.repository import Repository

_HEADING = re.compile(
    r"^((?:.+ · )?Задание №[^\n]+|Мой прогресс[^\n]*|Подробнее о номере|"
    r"Практика №[^\n]*|Оценка:[^\n]*|Что правильно:|Где ошибка:|Как исправить:|"
    r"Почему именно [^:]+:|Оценка не выставлена\.|Письменные работы|"
    r"История(?: · №\d+)?|Мои ошибки(?: · №\d+)?|"
    r"№\d+ · [^\n]+|Исходное условие:|Результат:|Попытки:|По семействам:|"
    r"Разбор(?: \(самостоятельное решение не засчитывается\))?:|"
    r"Подсказка(?: №\d+)?:|Ответ:|Правильный ответ:|Правильный вариант:)"
)
_INLINE_ANSWER = re.compile(r"(Ответ:|Правильный ответ:|Правильный вариант:)")


def format_math_message(text: str | MathFragment) -> str:
    """Escape data once; emphasize owned headings without changing notation.

    Normal paragraphs wrap naturally on narrow screens. Avoid code blocks,
    tables, formula images, or interpreting arbitrary source text as HTML/LaTeX.
    """
    source = text if isinstance(text, str) else text.unicode()
    if source.startswith(("Разбор:", "Вторая попытка неверна.")):
        source = layout_text(source)
    source = plain_text(source)
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


def hint_message(hint: str, problem: object = None, *, numbered: bool = True) -> str:
    hints = problem.get("hints") if isinstance(problem, dict) else None
    number = ""
    if numbered and isinstance(hints, list | tuple) and len(hints) > 1 and hint in hints:
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
    source_lines = layout_text(flatten_math_lines(source)).split("\n")
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
            parts = math_spans(line.strip().removesuffix("."))
            if len(parts) == 1 and parts[0].latex:
                punctuation = "." if line.endswith(".") else ""
                lines.append(
                    "<tg-math-block>" + escape(parts[0].latex) + punctuation + "</tg-math-block>"
                )
                continue
            prefix = action_prefix(line)
            if prefix is not None:
                body = "<b>" + escape(prefix) + "</b>" + rich_inline(line[len(prefix) :])
            else:
                body = rich_inline(line)
            lines.append(f"<p>{body}</p>")
        else:
            spans = math_spans(line.strip())
            if len(spans) == 1 and spans[0].latex is not None and "∞" not in spans[0].source:
                lines.append("<tg-math-block>" + escape(spans[0].latex) + "</tg-math-block>")
            else:
                lines.append("<p>" + rich_inline(line) + "</p>")
    return "".join(lines)


def has_mathematics(text: str | MathFragment) -> bool:
    return not isinstance(text, str) or any(
        span.latex is not None and (span.explicit or not span.source.isdecimal())
        for span in math_spans(text)
    )


def _has_telegram_transport(message: object) -> bool:
    return isinstance(message, Message) or isinstance(getattr(message, "_message", None), Message)


async def _prefer_png(
    message: Message, repository: Repository, override: int | None, key: str | None
) -> bool:
    user_id = override
    if user_id is None and message.from_user is not None and not message.from_user.is_bot:
        user_id = message.from_user.id
    if user_id is None and message.chat.type == "private":
        user_id = message.chat.id
    if key is not None:
        return await repository.math_display(user_id, key) == "png"
    return user_id is not None and await repository.math_display(user_id) == "png"


class MathDeliveryUncertain(Exception):
    """Telegram may have created the message before its response was lost."""


async def _deliver_math(request: Awaitable[Message]) -> Message:
    try:
        return await request
    except (TelegramNetworkError, TelegramServerError, ClientDecodeError, TimeoutError) as error:
        raise MathDeliveryUncertain from error


def _rich_incompatible(error: TelegramBadRequest | TelegramNotFound) -> bool:
    # The method rejected the content or explicitly does not implement Rich.
    # A missing chat, invalid keyboard, missing attachment or generic 404
    # describes neither the mathematical template nor its compatibility.
    reason = error.message.casefold().strip()
    reason = reason.removeprefix("bad request: ").removeprefix("not found: ")
    if isinstance(error, TelegramNotFound):
        return reason in {"method not found", "sendrichmessage not found", "method not available"}
    return reason.startswith((
        "can't parse entities", "can't parse rich message html", "can't parse math",
        "unsupported start tag", "unsupported rich message", "unsupported math",
        "can't parse rich message: unsupported tag",
        "can't parse rich message: unsupported start tag",
        "rich messages are not supported",
        "method not found",
    ))


async def _send_mathematics(
    message: Message,
    text: str | MathFragment,
    photo: BufferedInputFile | None,
    kwargs: dict[str, Any],
    *,
    repository: Repository,
    force_png: bool,
    key: str | None,
    system_rows: tuple[str, ...] | None = None,
    diagram_caption: str | None = None,
) -> Message:
    fallback = formats()[key] == "png" if key is not None else rich_needs_png_fallback(text)
    if force_png or fallback:
        logging.getLogger(__name__).debug(
            "math_image_reason=%s", "effective_preference" if force_png else "template_or_notation"
        )
        return await _send_math_image(message, text, photo, kwargs, system_rows, diagram_caption)
    rich = format_rich_message(text, system_rows=system_rows)
    media = None
    if photo is not None:
        rich = '<img src="tg://photo?id=diagram"/>' + rich
        media = [InputRichMessageMedia(id="diagram", media=InputMediaPhoto(media=photo))]
    try:
        bot = message.bot
        if bot is None:
            raise RuntimeError("Mathematical transport needs a mounted bot")
        return await _deliver_math(bot.send_rich_message(
            chat_id=message.chat.id,
            message_thread_id=message.message_thread_id,
            rich_message=InputRichMessage(html=rich, media=media),
            **kwargs,
        ))
    except (TelegramBadRequest, TelegramNotFound) as error:
        if not _rich_incompatible(error):
            raise
        if key is not None:
            await repository.remember_png_template(key)
        logging.getLogger(__name__).info("math_image_reason=rich_incompatible template=%s", key)
        # Only a definite rejection means no message was created. Timeouts,
        # transport failures, rate limits and server errors must propagate.
        return await _send_math_image(message, text, photo, kwargs, system_rows, diagram_caption)


async def _send_math_image(
    message: Message,
    text: str | MathFragment,
    photo: BufferedInputFile | None,
    kwargs: dict[str, Any],
    system_rows: tuple[str, ...] | None = None,
    diagram_caption: str | None = None,
) -> Message:
    from app.bot.math_image import render_math_image

    standalone = photo if diagram_caption is not None else None
    image = await asyncio.to_thread(
        render_math_image,
        text,
        None if photo is None or standalone is not None else photo.data,
        system_rows,
    )
    bot = message.bot
    if bot is None:
        raise RuntimeError("Mathematical transport needs a mounted bot")
    if standalone is not None:
        await _deliver_math(bot.send_photo(
            chat_id=message.chat.id,
            message_thread_id=message.message_thread_id,
            photo=standalone,
            caption=diagram_caption,
        ))
    return await _deliver_math(bot.send_photo(
        chat_id=message.chat.id,
        message_thread_id=message.message_thread_id,
        photo=BufferedInputFile(image, filename="mathematics.png"),
        **kwargs,
    ))


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
    text: str | MathFragment | Text,
    *,
    user_id_override: int | None = None,
    math_family: object = None,
    math_system_rows: tuple[str, ...] | None = None,
    rich_with_navigation: bool = False,
    **kwargs: Any,
) -> Message:
    from app.bot.navigation import navigation_screen, prepare_navigation_markup

    has_navigation = navigation_screen(kwargs.get("reply_markup")) is not None
    key = template_key(math_family)
    if "reply_markup" in kwargs:
        kwargs["reply_markup"] = prepare_navigation_markup(kwargs["reply_markup"])
    if isinstance(text, Text):
        sent = await message.answer(**text.as_kwargs(), **kwargs)
    elif (
        _has_telegram_transport(message)
        and (
            key is not None
            or not has_navigation
            or rich_with_navigation
            or isinstance(text, str)
            and next(formulas(text), None) is not None
        )
        and (key is not None or has_mathematics(text))
    ):
        construction = None
        if (
            key in {"OGE18-A06", "OGE18-A07", "OGE18-C01"}
            and isinstance(math_family, dict)
            and isinstance(text, str)
            and any(s.startswith("Разбор") for s in text.splitlines())
        ):
            from app.math.oge18_render import polygon_construction

            points = tuple((x, y) for x, y in math_family["points"])
            png = await asyncio.to_thread(polygon_construction, key, points)
            construction = BufferedInputFile(png, filename="construction.png")
        sent = await _send_mathematics(
            message,
            typeset_family_text(text, math_family) if isinstance(text, str) else text,
            construction,
            kwargs,
            repository=repository,
            force_png=await _prefer_png(message, repository, user_id_override, key),
            system_rows=(
                tuple(typeset_family_text(row, math_family) for row in math_system_rows)
                if math_system_rows
                else None
            ),
            key=key,
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
    math_family: object = None,
    math_system_rows: tuple[str, ...] | None = None,
    diagram_caption: str | None = None,
    **kwargs: Any,
) -> Message:
    from app.bot.navigation import prepare_navigation_markup

    key = template_key(math_family)
    if "reply_markup" in kwargs:
        kwargs["reply_markup"] = prepare_navigation_markup(kwargs["reply_markup"])
    if (
        isinstance(math_family, dict)
        and key
        and key.startswith(("OGE07-", "OGE11-", "OGE16-"))
        and _has_telegram_transport(message)
    ):
        from app.bot.diagram_layout import mobile_diagram

        photo = BufferedInputFile(
            await asyncio.to_thread(mobile_diagram, photo.data, math_family),
            filename=photo.filename or "diagram.png",
        )
    if _has_telegram_transport(message) and (
        key is not None
        or has_mathematics(caption)
        or isinstance(caption, str)
        and len(caption) > 950
    ):
        sent = await _send_mathematics(
            message,
            typeset_family_text(caption, math_family) if isinstance(caption, str) else caption,
            photo,
            kwargs,
            repository=repository,
            force_png=await _prefer_png(message, repository, user_id_override, key),
            system_rows=(
                tuple(typeset_family_text(row, math_family) for row in math_system_rows)
                if math_system_rows
                else None
            ),
            key=key,
            diagram_caption=diagram_caption,
        )
    else:
        sent = await message.answer_photo(
            photo, caption=format_math_message(caption), parse_mode="HTML", **kwargs
        )
    await _bind_navigation(message, repository, sent, kwargs.get("reply_markup"), user_id_override)
    return sent
