"""Real aiogram routing and real PostgreSQL; only Telegram HTTP is substituted."""

import fnmatch
import html
import re
import shutil
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
    PhotoSize,
    Update,
    User,
)
from test_navigation_postgres import navigation_pool as navigation_pool

__all__ = ["navigation_pool"]  # Explicitly re-export the existing isolated PG fixture.

from app.bot.router import build_router
from app.persistence.repository import MemoryRepository, PostgresRepository


class TelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.messages: dict[int, Message] = {}
        self.calls: list[Any] = []
        self.next_message_id = 100
        self.expired_acks = False

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 (aiogram interface)
        self.calls.append(method)
        if method.__api_method__ == "answerCallbackQuery" and self.expired_acks:
            raise TelegramBadRequest(
                method=method,
                message="query is too old and response timeout expired or query ID is invalid",
            )
        if method.__api_method__ == "getMe":
            return User(id=123456, is_bot=True, first_name="Test bot", username="TestBot")
        if method.__api_method__ == "answerCallbackQuery":
            return True
        if method.__api_method__ == "deleteMessage":
            self.messages.pop(method.message_id)
            return True
        if method.__api_method__ == "editMessageReplyMarkup":
            message = self.messages[method.message_id]
            self.messages[method.message_id] = message.model_copy(
                update={"reply_markup": method.reply_markup}
            )
            return True
        if method.__api_method__ == "editMessageCaption":
            message = self.messages[method.message_id].model_copy(
                update={
                    "caption": method.caption,
                    "reply_markup": method.reply_markup,
                    "show_caption_above_media": method.show_caption_above_media,
                }
            )
            self.messages[method.message_id] = message
            return message
        message_id = getattr(method, "message_id", None)
        if message_id is None:
            message_id = self.next_message_id
            self.next_message_id += 1
        markup = getattr(method, "reply_markup", None)
        previous = self.messages.get(message_id)
        reply_parameters = getattr(method, "reply_parameters", None)
        reply = (
            self.messages.get(reply_parameters.message_id)
            if reply_parameters is not None
            else previous.reply_to_message if previous is not None else None
        )
        is_photo = method.__api_method__ in {"sendPhoto", "editMessageMedia"}
        text = getattr(method, "text", None)
        if method.__api_method__ == "sendRichMessage":
            rich_message = getattr(method, "rich_message", None)
            rich_html = getattr(rich_message, "html", "")
            # The fake transport exposes Rich Message copy as readable text so
            # dispatcher tests can assert what a Telegram user sees.
            text = html.unescape(re.sub(r"<[^>]*>", "", rich_html))
            text = re.sub(r"\{([,])\}", r"\1", text)
            text = text.replace(r"\cdot", "·").replace(r"\div", ":")
            text = text.replace(r"\left(", "(").replace(r"\right)", ")")
            text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2", text)
        message = Message(
            message_id=message_id,
            date=datetime.now(UTC),
            chat=Chat(id=42, type="private"),
            from_user=User(id=123456, is_bot=True, first_name="Test bot"),
            text=text,
            reply_to_message=reply,
            photo=(
                [
                    PhotoSize(
                        file_id=f"photo-{message_id}",
                        file_unique_id="fixture",
                        width=1200,
                        height=1570,
                    )
                ]
                if is_photo
                else None
            ),
            caption=(
                method.media.caption if method.__api_method__ == "editMessageMedia"
                else getattr(method, "caption", None)
            ),
            reply_markup=markup if isinstance(markup, InlineKeyboardMarkup) else None,
        ).as_(bot)
        self.messages[message_id] = message
        return message


async def exercise_navigation(
    repository, *, expired_stale_ack=False, expire_all_acks=False, webhook=False, graphics=False,
    saved17=False, cycle_number=None
):
    session = TelegramSession()
    session.expired_acks = expire_all_acks
    bot = Bot("123456:TEST", session=session)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    user = User(id=42, is_bot=False, first_name="Synthetic student")
    update_id = 1
    stack = AsyncExitStack()
    await stack.__aenter__()
    client = None
    if webhook:
        from app.main import create_app

        app = create_app(repository=repository, bot=bot, run_schema_migrations=False)
        await stack.enter_async_context(app.router.lifespan_context(app))
        client = await stack.enter_async_context(
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        )

    async def feed(update):
        if client is None:
            await dispatcher.feed_update(bot, update, repository=repository)
        else:
            response = await client.post(
                "/telegram/webhook",
                json=update.model_dump(mode="json", exclude_none=True),
                headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret"},
            )
            assert response.status_code == 200, response.text

    async def click(action, message=None, *, repeat=False):
        nonlocal update_id
        message = message or list(session.messages.values())[-1]
        data = next(
            button.callback_data
            for row in message.reply_markup.inline_keyboard
            for button in row
            if (button.callback_data or "").partition("~")[0] == action
        )
        update_id += 1
        update = Update(
            update_id=update_id,
            callback_query=CallbackQuery(
                id=f"synthetic-{update_id}",
                from_user=user,
                chat_instance="synthetic",
                message=message,
                data=data,
            ),
        )
        await feed(update)
        if repeat:
            calls = len(session.calls)
            await feed(update)
            assert len(session.calls) == calls

    try:
        await feed(
            Update(
                update_id=1,
                message=Message(
                    message_id=1,
                    date=datetime.now(UTC),
                    chat=Chat(id=42, type="private"),
                    from_user=user,
                    text="/start",
                    entities=[MessageEntity(type="bot_command", offset=0, length=6)],
                ),
            )
        )
        original_menu = list(session.messages.values())[-1]
        await click("nav:numbers")
        assert await repository.user_state(42) == "number_selection"
        if saved17:

            async def numbers_to_17():
                await click("nav:numbers:1")
                await click("nav:numbers:2")
                await click("nav:task:17")

            await numbers_to_17()
            await click("nav:family:17:random")
            await click("nav:begin:17")
            state = await repository.task17_state(42)
            saved = state["problem"]
            pid = saved["problem_id"]
            await click(f"t17:menu:{pid}")
            await click("nav:numbers")
            await numbers_to_17()
            old = list(session.messages.values())[-1]
            await click(f"nav:tr:r:17:{pid}")
            await click(f"nav:tr:n:17:{pid}")
            fresh = list(session.messages.values())[-1]
            repository = PostgresRepository(repository._pool)
            dispatcher = Dispatcher()
            dispatcher.include_router(build_router())
            await click(f"nav:tr:c:17:{pid}", old)
            assert session.calls[-1].text.startswith("Это меню устарело")
            await click(f"nav:tr:c:17:{pid}", fresh)
            assert await repository.user_state(42) == "task17"
            assert (await repository.task17_state(42))["problem"] == saved
            await click(f"t17:menu:{pid}")
            await click("nav:resume")
            assert await repository.user_state(42) == "task17"
            assert (await repository.task17_state(42))["problem"] == saved
            await click(f"t17:menu:{pid}")
            await click("nav:numbers")
            await numbers_to_17()
            await click("nav:families:17")
            await click("nav:family:17:0")
            await click("nav:begin:17")
            await click(f"nav:tr:r:17:{pid}")
            await click(f"nav:tr:y:17:{pid}")
            after = (await repository.task17_state(42))["problem"]
            assert after["problem_id"] != pid
            assert after["family_id"] == await repository.training_family(42, 17)
            return
        if cycle_number is not None:
            from app.persistence.rotation_history import enabled

            n = cycle_number
            for page in range(1, (n - 5) // 6 + 1):
                await click(f"nav:numbers:{page}")
            await click(f"nav:task:{n}")
            await click(f"nav:family:{n}:random")
            await click(f"nav:begin:{n}")
            families = enabled(n)
            previous_last = None
            kinds = []
            for _ in range(2):
                seen = []
                for pos in range(len(families)):
                    # Read from a fresh repository and recreate the dispatcher halfway.
                    if pos == len(families) // 2:
                        repository = PostgresRepository(repository._pool)
                        dispatcher = Dispatcher()
                        dispatcher.include_router(build_router())
                    state = await getattr(repository, f"task{n}_state")(42)
                    problem = state["problem"]
                    seen.append(problem["family_id"])
                    if n == 19:
                        kinds.append((problem["question_kind"], len(problem["answer_mask"])))
                    original = list(session.messages.values())[-1]
                    skip = f"t{n}:skip:{problem['problem_id']}"
                    await click(skip, original)
                    if pos == 0:
                        after = await getattr(repository, f"task{n}_state")(42)
                        await click(skip, original)
                        again = await getattr(repository, f"task{n}_state")(42)
                        assert again["problem"]["problem_id"] == after["problem"]["problem_id"]
                assert set(seen) == set(families)
                assert seen[0] != previous_last
                previous_last = seen[-1]
            if n == 19:
                assert kinds == [("find_true", 1), ("find_true", 2),
                                 ("find_false", 1), ("find_false", 2)] * 3
            return
        # Same message ID, previous keyboard revision: must not change the screen.
        session.expired_acks = expired_stale_ack or expire_all_acks
        await click("nav:progress", original_menu, repeat=webhook)
        session.expired_acks = expire_all_acks
        assert await repository.user_state(42) == "number_selection"
        await click("nav:main")
        await click("nav:progress")
        assert await repository.user_state(42) == "progress"
        assert (await repository.task6_progress(42))["issued"] == 0
        overview_photo = list(session.messages.values())[-1]
        assert overview_photo.photo
        assert not any(call.__api_method__ == "sendWidget" for call in session.calls)
        keyboard = overview_photo.reply_markup.inline_keyboard
        assert [[button.text for button in row] for row in keyboard] == [
            ["Подробнее по номерам"],
            ["История и ошибки"],
            ["🎲 Смешанная тренировка"],
            ["↩ В меню"],
        ]
        await click("progress:details", overview_photo)
        number_picker = list(session.messages.values())[-1]
        assert number_picker.reply_to_message.message_id == overview_photo.message_id
        assert session.messages[overview_photo.message_id].photo == overview_photo.photo
        assert session.messages[overview_photo.message_id].reply_markup is None
        await click("progress:details", overview_photo)
        assert list(session.messages.values())[-1].message_id == number_picker.message_id
        await click("progress:number:6")
        number_detail = list(session.messages.values())[-1]
        assert "№6" in (number_detail.text or "")
        assert any(
            (button.callback_data or "").partition("~")[0] == "nav:task:6"
            for row in number_detail.reply_markup.inline_keyboard
            for button in row
        )
        assert any(
            (button.callback_data or "").partition("~")[0] == "progress:numhist:6:0"
            for row in number_detail.reply_markup.inline_keyboard
            for button in row
        )
        assert number_detail.message_id == number_picker.message_id
        await click("progress:details")
        await click("progress:number:6")
        photos_sent = sum(call.__api_method__ == "sendPhoto" for call in session.calls)
        await click("progress:summary")
        assert number_picker.message_id not in session.messages
        assert list(session.messages.values())[-1].message_id == overview_photo.message_id
        assert sum(call.__api_method__ == "sendPhoto" for call in session.calls) == photos_sent
        await click("progress:history:0")
        await click("progress:errors:0")
        assert await repository.user_state(42) == "progress"
        await click("progress:summary")
        await click("nav:main")
        update_id += 1
        await feed(
            Update(
                update_id=update_id,
                message=Message(
                    message_id=900 + update_id,
                    date=datetime.now(UTC),
                    chat=Chat(id=42, type="private"),
                    from_user=user,
                    text="/progress",
                    entities=[MessageEntity(type="bot_command", offset=0, length=9)],
                ),
            )
        )
        fallback = list(session.messages.values())[-1]
        assert "Мой прогресс" in (fallback.text or "")
        assert not fallback.photo
        await click("nav:main")
        await click("nav:numbers")
        await click("nav:task:6")
        await click("nav:family:6:random")
        await click("nav:begin:6")
        state = await repository.task6_state(42)
        assert state is not None and state["state"]["status"] == "active"
        assert await repository.user_state(42) == "task6"
        problem_id = state["problem"]["problem_id"]
        await click(f"t6:menu:{problem_id}")
        await click("nav:resume")
        resumed = await repository.task6_state(42)
        assert resumed["problem"]["problem_id"] == problem_id
        assert resumed["state"]["attempts"] == 0
        await click(f"t6:menu:{problem_id}")
        await click("nav:numbers")
        await click("nav:task:6")
        choice = list(session.messages.values())[-1]
        assert "Сохранена практика: №6" in (choice.text or "")
        assert (await repository.task6_state(42))["problem"]["problem_id"] == problem_id
        await click(f"nav:tr:r:6:{problem_id}", choice)
        confirmation = list(session.messages.values())[-1]
        assert "Активное задание останется без результата" in (confirmation.text or "")
        assert (await repository.task6_state(42))["problem"]["problem_id"] == problem_id
        await click(f"nav:tr:n:6:{problem_id}", confirmation)
        choice = list(session.messages.values())[-1]
        assert "Сохранена практика: №6" in (choice.text or "")
        await click(f"nav:tr:r:6:{problem_id}", choice)
        confirmation = list(session.messages.values())[-1]
        await click(f"nav:tr:y:6:{problem_id}", confirmation)
        restarted = await repository.task6_state(42)
        assert restarted is not None and restarted["problem"]["problem_id"] != problem_id
        assert restarted["state"]["status"] == "active"
        assert (await repository.task6_progress(42))["issued"] == 2
        assert await repository.user_state(42) == "task6"
        restarted_problem_id = restarted["problem"]["problem_id"]
        wrong_answer = "1" if str(restarted["problem"]["correct_answer"]) == "0" else "0"
        update_id += 1
        await feed(
            Update(
                update_id=update_id,
                message=Message(
                    message_id=700 + update_id,
                    date=datetime.now(UTC),
                    chat=Chat(id=42, type="private"),
                    from_user=user,
                    text=wrong_answer,
                ),
            )
        )
        assert (await repository.task6_progress(42))["attempts"] == 1
        await click(f"t6:menu:{restarted_problem_id}")
        await click("nav:numbers")
        await click("nav:task:8")
        assert await repository.user_state(42) == "family_selection:8"
        first_page = list(session.messages.values())[-1]
        await click("nav:families:8:1", first_page, repeat=webhook)
        second_page = list(session.messages.values())[-1]
        assert "Страница 2" in (second_page.text or "")
        await click("nav:family:8:0", first_page)
        assert await repository.training_family(42, 8) is None
        await click("nav:family:8:6", second_page, repeat=webhook)
        from app.persistence.rotation_history import enabled
        from app.persistence.training_insights import family_name

        assert await repository.training_family(42, 8) == enabled(8)[6]
        assert family_name(enabled(8)[6]) in (list(session.messages.values())[-1].text or "")
        await click("nav:families:8:1")
        assert "Страница 2" in (list(session.messages.values())[-1].text or "")
        await click("nav:numbers")
        await click("nav:main")
        await click("nav:progress")
        assert list(session.messages.values())[-1].photo
        assert not any(call.__api_method__ == "sendWidget" for call in session.calls)
        await click("progress:details")
        await click("progress:number:8")
        assert await repository.user_state(42) == "progress"
        await click("progress:summary")
        from app.persistence.training_insights import training_insights

        before_history_view = await training_insights(repository, 42)
        await click("progress:history:0")
        await click("progress:errors:0")
        error_list = list(session.messages.values())[-1]
        item_action = next(
            button.callback_data.partition("~")[0]
            for row in error_list.reply_markup.inline_keyboard
            for button in row
            if (button.callback_data or "").startswith("progress:item:")
        )
        detail_call_start = len(session.calls)
        await click(item_action)
        error_detail = list(session.messages.values())[-1]
        assert "Исходное условие:" in (error_detail.text or "")
        assert "Ошибка была: да" in (error_detail.text or "")
        condition = str(restarted["problem"]["condition"])
        delivery = next(
            call for call in reversed(session.calls[detail_call_start:])
            if call.__api_method__ in {"sendRichMessage", "sendMessage", "editMessageText"}
        )
        if delivery.__api_method__ == "sendRichMessage":
            from app.bot.family_display import typeset_family_text
            from app.bot.presentation import format_rich_message

            # The history view formats the original snapshot's family before
            # serializing Rich HTML, including №6's mixed-number fraction.
            rich_condition = typeset_family_text(condition, restarted["problem"])
            assert format_rich_message(rich_condition) in delivery.rich_message.html
        else:
            assert condition in (error_detail.text or "")
        return_action = next(
            button.callback_data.partition("~")[0]
            for row in error_detail.reply_markup.inline_keyboard
            for button in row
            if (button.callback_data or "").startswith("progress:return:")
        )
        if not graphics:
            replay_action = next(
                button.callback_data.partition("~")[0]
                for row in error_detail.reply_markup.inline_keyboard
                for button in row
                if (button.callback_data or "").startswith("progress:replay:")
            )
            await click(replay_action)
            original_prompt = list(session.messages.values())[-1]
            hint_action = next(
                button.callback_data.partition("~")[0]
                for row in original_prompt.reply_markup.inline_keyboard
                for button in row
                if (button.callback_data or "").startswith("replay:")
            )
            await click(hint_action, original_prompt, repeat=webhook)
            assert "Подсказка" in (list(session.messages.values())[-1].text or "")
            await click(hint_action, original_prompt)
            assert "Подсказка" in (list(session.messages.values())[-1].text or "")
            update_id += 1
            await feed(
                Update(
                    update_id=update_id,
                    message=Message(
                        message_id=800 + update_id,
                        date=datetime.now(UTC),
                        chat=Chat(id=42, type="private"),
                        from_user=user,
                        text=str(restarted["problem"]["correct_answer"]),
                        reply_to_message=original_prompt,
                    ),
                )
            )
            result = list(session.messages.values())[-1]
            assert "Ошибка исправлена" in (result.text or "")
            await click("progress:errors:0", result)
            await click(item_action)
            corrected = list(session.messages.values())[-1]
            assert "Ошибка исправлена" in (corrected.text or "")
            assert all(
                not (button.callback_data or "").startswith("progress:replay:")
                for row in corrected.reply_markup.inline_keyboard
                for button in row
            )
        await click(return_action)
        assert "С ошибками" in (list(session.messages.values())[-1].text or "")
        after_history_view = await training_insights(repository, 42)
        assert before_history_view["total"] == after_history_view["total"]
        assert before_history_view["numbers"] == after_history_view["numbers"]
        await click("progress:summary")
        await click("nav:main")
        assert (await repository.task6_state(42))["problem"]["problem_id"] == restarted_problem_id
        await click("nav:display")
        await click("nav:math:png")
        await click("nav:main")
        if graphics:
            for number, family_prefix in ((7, "OGE07-N"), (11, "OGE11-F"), (13, "OGE13-S")):
                await click("nav:numbers")
                call_count = len(session.calls)
                if number >= 11:
                    await click("nav:numbers:1")
                await click(f"nav:task:{number}")
                from app.persistence.rotation_history import enabled

                index = next(
                    i for i, f in enumerate(enabled(number)) if f.startswith(family_prefix)
                )
                if index >= 6:
                    await click(f"nav:families:{number}:{index // 6}")
                await click(f"nav:family:{number}:{index}")
                await click(f"nav:begin:{number}")
                photos = [c for c in session.calls[call_count:] if c.__api_method__ == "sendPhoto"]
                assert len(photos) == (1 if number == 7 else 2)
                if len(photos) == 2:
                    assert photos[0].reply_markup is None
                    assert photos[1].reply_markup is not None
                state_reader = getattr(repository, f"task{number}_state")
                issued = await state_reader(42)
                assert issued["problem"]["family_id"].startswith(family_prefix)
                assert all(call.photo.data.startswith(b"\x89PNG\r\n\x1a\n") for call in photos)
                if number == 11:
                    import base64
                    from io import BytesIO

                    from PIL import Image, ImageChops

                    from app.math.oge11_render import PLOT, ROW_HEIGHT

                    raw = base64.b64decode(issued["problem"]["png_base64"], validate=True)
                    with Image.open(BytesIO(raw)) as source, Image.open(
                        BytesIO(photos[0].photo.data)
                    ) as sent:
                        for i, (x, y) in enumerate(((10, 35), (434, 35), (222, 466))):
                            offset = i * ROW_HEIGHT
                            rect = (PLOT[0] - 2, offset + PLOT[1] - 2,
                                    PLOT[2] + 3, offset + PLOT[3] + 3)
                            plot = source.convert("RGB").crop(rect)
                            visible = sent.crop((x, y, x + plot.width, y + plot.height))
                            assert ImageChops.difference(plot, visible).getbbox() is None
                if number == 13:
                    from app.math.inequalities import render_option_sheet_snapshot_png

                    assert photos[0].photo.data == render_option_sheet_snapshot_png(
                        issued["problem"]
                    )
                task_id = issued["problem"]["problem_id"]
                await click(f"t{number}:menu:{task_id}")
                await click("nav:resume")
                assert (await state_reader(42))["problem"]["problem_id"] == task_id
                await click(f"t{number}:menu:{task_id}")

        # Switching №9 → №12 and selecting saved №9 restores its exact problem.
        await click("nav:numbers")
        await click("nav:task:9")
        await click("nav:family:9:random")
        await click("nav:begin:9")
        task9 = await repository.task9_state(42)
        assert task9 is not None and isinstance(task9["problem"], dict)
        task9_id = str(task9["problem"]["problem_id"])
        await click(f"t9:menu:{task9_id}")
        await click("nav:numbers")
        await click("nav:numbers:1")
        await click("nav:task:12")
        await click("nav:family:12:random")
        await click("nav:begin:12")
        task12 = await repository.task12_state(42)
        assert task12 is not None and isinstance(task12["problem"], dict)
        task12_id = str(task12["problem"]["problem_id"])
        await click(f"t12:menu:{task12_id}")
        await click("nav:numbers")
        await click("nav:task:9")
        choice = list(session.messages.values())[-1]
        assert "Сохранена практика: №9" in (choice.text or "")
        assert (await repository.task9_state(42))["problem"]["problem_id"] == task9_id
        await click(f"nav:tr:c:9:{task9_id}", choice)
        restored_task9 = await repository.task9_state(42)
        assert restored_task9 is not None
        assert restored_task9["problem"]["problem_id"] == task9_id
        assert await repository.user_state(42) == "task9"
    finally:
        await stack.aclose()
        await bot.session.close()


@pytest.mark.asyncio
async def test_dispatcher_inline_navigation_memory():
    await exercise_navigation(MemoryRepository())


@pytest.mark.asyncio
async def test_dispatcher_inline_navigation_and_graphic_issuance_postgres(
    navigation_pool, monkeypatch
):
    monkeypatch.setattr("app.bot.router.secrets.randbelow", lambda _: 3)
    await exercise_navigation(PostgresRepository(navigation_pool), graphics=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("expiration", ["stale", "all"])
async def test_expired_stale_callback_webhook_postgres(navigation_pool, monkeypatch, expiration):
    from app.config import get_settings

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "synthetic-secret")
    monkeypatch.setenv("WEBHOOK_BASE_URL", "")
    get_settings.cache_clear()
    try:
        await exercise_navigation(
            PostgresRepository(navigation_pool),
            expired_stale_ack=True,
            expire_all_acks=expiration == "all",
            webhook=True,
        )
        assert (
            await navigation_pool.fetchval(
                "SELECT count(*) FROM telegram_updates WHERE status <> 'processed'"
            )
            == 0
        )
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unrelated_callback_api_error_is_not_hidden():
    from app.bot.callbacks import answer_callback

    session = TelegramSession()
    bot = Bot("123456:TEST", session=session)
    callback = CallbackQuery(
        id="synthetic",
        from_user=User(id=42, is_bot=False, first_name="Synthetic"),
        chat_instance="synthetic",
        data="nav:main",
    ).as_(bot)

    async def unrelated(bot, method, timeout=None):  # noqa: ASYNC109 (aiogram interface)
        assert method.show_alert is True
        raise TelegramBadRequest(method=method, message="unrelated bad request")

    session.make_request = unrelated
    try:
        with pytest.raises(TelegramBadRequest, match="unrelated bad request"):
            await answer_callback(callback, "Опция недоступна", show_alert=True)
    finally:
        await bot.session.close()


@pytest.mark.asyncio
async def test_dispatcher_postgres_with_production_container_assets(
    navigation_pool, tmp_path, monkeypatch
):
    from app.persistence import training_insights

    root = Path(__file__).resolve().parents[1]
    # Mirror atlas COPY/context filtering rather than silently using the host repo.
    ignored = (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    if any(
        line.startswith("COPY atlas ") for line in (root / "Dockerfile").read_text().splitlines()
    ):
        for source in (root / "atlas").glob("*.json"):
            relative = source.relative_to(root).as_posix()
            included = True
            for rule in ignored:
                pattern = rule.removeprefix("!")
                if fnmatch.fnmatch(relative, pattern) or relative.startswith(pattern + "/"):
                    included = rule.startswith("!")
            if included:
                destination = tmp_path / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
    monkeypatch.setattr(
        training_insights, "__file__", str(tmp_path / "app/persistence/training_insights.py")
    )
    training_insights.family_names.cache_clear()
    try:
        await exercise_navigation(PostgresRepository(navigation_pool))
    finally:
        training_insights.family_names.cache_clear()

@pytest.mark.parametrize("number", range(6, 20))
async def test_ordinary_random_menu_commits_two_cycles(navigation_pool, number):
    await exercise_navigation(PostgresRepository(navigation_pool), cycle_number=number)


async def test_task17_saved_menu_after_process_restart(navigation_pool):
    await exercise_navigation(PostgresRepository(navigation_pool), saved17=True)
