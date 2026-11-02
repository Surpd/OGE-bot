from html import unescape
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.bot.presentation import format_math_message, hint_message, send_photo, send_text


@pytest.mark.parametrize(
    "expression",
    [
        "(−3/4 + 1/2) : 0,5",
        "−2 < x ≤ 3",
        "√(49) = 7",
        "aₙ = a₁ + (n − 1)d",
        "x² − 5x + 6 = 0",
        "E = mv²/2",
        "P(A) = 3/10",
        "y = kx + b",
        "А → 1; Б → 2; В → 3",
        "2^(-3) = 1/8",
        "<script>& 1 > 0",
    ],
)
def test_presentation_preserves_mathematics_and_escapes_html(expression):
    rendered = format_math_message(expression)
    assert unescape(rendered) == expression
    assert "<script>" not in rendered
    assert "<tg-math" not in rendered


def test_owned_headings_are_distinct_and_source_html_is_literal():
    assert format_math_message("Задание №13 · неравенства\n\nx < 2") == (
        "<b>Задание №13 · неравенства</b>\n\nx &lt; 2"
    )
    assert format_math_message(hint_message("Умножьте на −1: x > 2")) == (
        "<b>Подсказка:</b>\n\nУмножьте на −1: x &gt; 2"
    )
    assert format_math_message("Разбор:\n1. x < 2\n\nОтвет: 1") == (
        "<b>Разбор:</b>\n1. x &lt; 2\n\n<b>Ответ:</b> 1"
    )
    assert format_math_message("<b>Ответ:</b> 2") == "&lt;b&gt;<b>Ответ:</b>&lt;/b&gt; 2"


@pytest.mark.asyncio
async def test_text_and_photo_use_same_explicit_html_transport():
    message = SimpleNamespace(answer=AsyncMock(), answer_photo=AsyncMock(), from_user=None)
    repository = AsyncMock()
    text = "Задание №7\n\nx < 3 & x > 1"
    await send_text(message, repository, text)
    message.answer.assert_awaited_once_with(format_math_message(text), parse_mode="HTML")
    photo = object()
    await send_photo(message, repository, photo, caption=text)
    message.answer_photo.assert_awaited_once_with(
        photo, caption=format_math_message(text), parse_mode="HTML"
    )
    repository.set_navigation_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("photo", [False, True])
async def test_callback_bot_sender_binds_navigation_to_explicit_user(photo):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    sent = SimpleNamespace(message_id=982)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=999, is_bot=True),
        answer=AsyncMock(return_value=sent),
        answer_photo=AsyncMock(return_value=sent),
    )
    repository = AsyncMock()
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="По номеру", callback_data="nav:numbers")]]
    )
    if photo:
        await send_photo(
            message, repository, object(), caption="Меню", reply_markup=markup, user_id_override=42
        )
        call = message.answer_photo.await_args
    else:
        await send_text(message, repository, "Меню", reply_markup=markup, user_id_override=42)
        call = message.answer.await_args
    assert "user_id_override" not in call.kwargs
    repository.set_navigation_message.assert_awaited_once_with(42, "main_menu", 982)
