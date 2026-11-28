from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from test_inline_dispatcher_postgres import TelegramSession

from app.admin import telegram as admin_telegram
from app.admin.screens import render_screen
from app.admin.telegram import handle_admin_update
from app.persistence.repository import MemoryRepository


class ReportService:
    def __init__(self):
        self.calls = []

    async def load(self, screen, period, **kwargs):
        self.calls.append((screen, period, kwargs))
        return SimpleNamespace(data={"registered": 8, "active": 3}, unavailable=None)


def _image_view(screen, data, **context):
    _, markup = render_screen(screen, data, revision=context["revision"])
    if screen == "usage":
        return SimpleNamespace(text="<b>Использование</b>", markup=markup, photo=None, caption=None)
    return SimpleNamespace(
        text=f"<b>{screen}</b>", markup=markup, photo=b"synthetic-png", caption=f"<b>{screen}</b>"
    )


def _message(bot, message_id, *, sender=None, text=None, photo=False):
    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=42, type="private"),
        from_user=sender or User(id=42, is_bot=False, first_name="Synthetic owner"),
        text=text,
        photo=[{"file_id": "photo", "file_unique_id": "photo", "width": 1200, "height": 1400}]
        if photo
        else None,
    ).as_(bot)


def _click(bot, message, action):
    button = next(
        item
        for row in message.reply_markup.inline_keyboard
        for item in row
        if item.callback_data.endswith(f":{action}")
    )
    callback = CallbackQuery(
        id=f"synthetic-{action}",
        from_user=User(id=42, is_bot=False, first_name="Synthetic owner"),
        chat_instance="synthetic",
        message=message,
        data=button.callback_data,
    ).as_(bot)
    return callback


@pytest.mark.asyncio
async def test_photo_menu_switches_to_formatted_text_and_back(monkeypatch):
    monkeypatch.setattr(admin_telegram, "render_admin_view", _image_view)
    session = TelegramSession()
    bot = Bot("123456:TEST", session=session)
    repository = MemoryRepository()
    dispatcher = __import__("aiogram").Dispatcher()

    # Run each complete update through aiogram's normal dispatcher, middleware,
    # and production companion router with only Telegram HTTP replaced.
    from app.bot.router import build_router
    from app.companion.middleware import CompanionMiddleware
    from app.config import Settings

    dispatcher.include_router(build_router())
    dispatcher.update.outer_middleware(
        CompanionMiddleware(
            Settings(_env_file=None, telegram_test_owner_ids="42"),
            frozenset({42}),
            "a" * 40,
            admin_service=ReportService(),
        )
    )
    start = _message(bot, 1, text="/start")
    update = Update(update_id=1, message=start).as_(bot)
    await dispatcher.feed_update(
        bot,
        update,
        repository=repository,
        oge15_repository=SimpleNamespace(),
        admin_service=ReportService(),
    )
    admin_photo = next(message for message in session.messages.values() if message.photo)
    assert admin_photo.reply_markup is not None
    assert "adm:" in admin_photo.reply_markup.inline_keyboard[0][0].callback_data

    usage_click = _click(bot, admin_photo, "usage")
    await dispatcher.feed_update(
        bot,
        Update(update_id=2, callback_query=usage_click).as_(bot),
        repository=repository,
        oge15_repository=SimpleNamespace(),
        admin_service=ReportService(),
    )
    usage_text = next(
        message for message in session.messages.values() if message.text == "<b>Использование</b>"
    )
    assert usage_text.reply_markup is not None
    assert admin_photo.message_id not in session.messages

    back_click = _click(bot, usage_text, "back")
    await dispatcher.feed_update(
        bot,
        Update(update_id=3, callback_query=back_click).as_(bot),
        repository=repository,
        oge15_repository=SimpleNamespace(),
        admin_service=ReportService(),
    )
    home_photo = next(
        message
        for message in session.messages.values()
        if message.photo and message.message_id != admin_photo.message_id
    )
    assert home_photo.reply_markup is not None
    assert usage_text.message_id not in session.messages
    await bot.session.close()


@pytest.mark.asyncio
async def test_stale_admin_visual_callback_does_not_change_or_reload_report():
    session = TelegramSession()
    bot = Bot("123456:TEST", session=session)
    message = _message(bot, 12, sender=User(id=123456, is_bot=True, first_name="Bot"), photo=True)
    state = {
        "admin_revision": "current",
        "admin_menu": 12,
        "admin_actions": ["usage"],
        "admin_active": True,
        "admin_screen": "home",
    }
    service = ReportService()
    callback = CallbackQuery(
        id="old-revision",
        from_user=User(id=42, is_bot=False, first_name="Synthetic owner"),
        chat_instance="synthetic",
        message=message,
        data="adm:expired:usage",
    ).as_(bot)

    assert await handle_admin_update(message, state, service, SimpleNamespace(), callback)
    assert service.calls == []
    assert state["admin_revision"] == "current"
    assert session.calls[-1].__api_method__ == "answerCallbackQuery"
    await bot.session.close()


class FailedPhotoSession(TelegramSession):
    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 (aiogram interface)
        if method.__api_method__ == "sendPhoto":
            raise TelegramNetworkError(method=method, message="synthetic timeout")
        return await super().make_request(bot, method, timeout)


class RejectedPhotoSession(TelegramSession):
    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 (aiogram interface)
        if method.__api_method__ == "sendPhoto":
            self.calls.append(method)
            raise TelegramBadRequest(method=method, message="synthetic photo rejection")
        return await super().make_request(bot, method, timeout)


@pytest.mark.asyncio
async def test_start_does_not_replace_menu_revision_when_photo_send_is_ambiguous(monkeypatch):
    monkeypatch.setattr(admin_telegram, "render_admin_view", _image_view)
    bot = Bot("123456:TEST", session=FailedPhotoSession())
    state = {"admin_revision": "old", "admin_menu": 10, "admin_active": True}
    message = _message(bot, 11, text="/start")

    with pytest.raises(TelegramNetworkError):
        await admin_telegram.present_admin(
            message,
            state,
            ReportService(),
            SimpleNamespace(status="ready", sha="test"),
        )

    assert state == {"admin_revision": "old", "admin_menu": 10, "admin_active": True}
    await bot.session.close()


@pytest.mark.asyncio
async def test_definite_photo_rejection_falls_back_once_to_the_full_html_menu(monkeypatch):
    monkeypatch.setattr(admin_telegram, "render_admin_view", _image_view)
    session = RejectedPhotoSession()
    bot = Bot("123456:TEST", session=session)
    state = {}
    await admin_telegram.present_admin(
        _message(bot, 11, text="/start"),
        state,
        ReportService(),
        SimpleNamespace(status="ready", sha="test"),
    )

    assert [call.__api_method__ for call in session.calls] == ["sendPhoto", "sendMessage"]
    sent = session.messages[state["admin_menu"]]
    assert sent.text == "<b>home</b>"
    assert sent.reply_markup is not None
    assert state["admin_revision"] in sent.reply_markup.inline_keyboard[0][0].callback_data
    await bot.session.close()
