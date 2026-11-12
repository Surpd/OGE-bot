"""Real aiogram routing and real PostgreSQL; only Telegram HTTP is substituted."""

import fnmatch
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
        if method.__api_method__ in {"answerCallbackQuery", "editMessageReplyMarkup"}:
            return True
        message_id = getattr(method, "message_id", None)
        if message_id is None:
            message_id = self.next_message_id
            self.next_message_id += 1
        markup = getattr(method, "reply_markup", None)
        message = Message(
            message_id=message_id,
            date=datetime.now(UTC),
            chat=Chat(id=42, type="private"),
            from_user=User(id=123456, is_bot=True, first_name="Test bot"),
            text=getattr(method, "text", None),
            reply_markup=markup if isinstance(markup, InlineKeyboardMarkup) else None,
        ).as_(bot)
        self.messages[message_id] = message
        return message


async def exercise_navigation(
    repository, *, expired_stale_ack=False, expire_all_acks=False, webhook=False, graphics=False
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
        # Same message ID, previous keyboard revision: must not change the screen.
        session.expired_acks = expired_stale_ack or expire_all_acks
        await click("nav:progress", original_menu, repeat=webhook)
        session.expired_acks = expire_all_acks
        assert await repository.user_state(42) == "number_selection"
        await click("nav:main")
        await click("nav:progress")
        assert await repository.user_state(42) == "progress"
        await click("nav:main")
        await click("nav:display")
        await click("nav:math:png")
        assert await repository.math_display(42) == "png"
        await click("nav:main")
        await click("nav:numbers")
        await click("nav:task:6")
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
        await click(f"t6:menu:{restarted_problem_id}")
        await click("nav:numbers")
        await click("nav:task:8")
        assert await repository.user_state(42) == "family_selection:8"
        await click("nav:numbers")
        await click("nav:main")
        await click("nav:progress")
        await click("progress:families")
        assert await repository.user_state(42) == "progress"
        await click("nav:main")
        assert (await repository.task6_state(42))["problem"]["problem_id"] == restarted_problem_id
        if graphics:
            for number, family_prefix in ((7, "OGE07-N"), (11, "OGE11-F"), (13, "OGE13-S")):
                await click("nav:numbers")
                photo_count = sum(c.__api_method__ == "sendPhoto" for c in session.calls)
                await click(f"nav:task:{number}")
                assert (
                    sum(c.__api_method__ == "sendPhoto" for c in session.calls) == photo_count + 1
                )
                state_reader = getattr(repository, f"task{number}_state")
                issued = await state_reader(42)
                assert issued["problem"]["family_id"].startswith(family_prefix)
                image = next(
                    call.photo
                    for call in reversed(session.calls)
                    if call.__api_method__ == "sendPhoto"
                )
                assert image.data.startswith(b"\x89PNG\r\n\x1a\n")
                task_id = issued["problem"]["problem_id"]
                await click(f"t{number}:menu:{task_id}")
                await click("nav:resume")
                assert (await state_reader(42))["problem"]["problem_id"] == task_id
                await click(f"t{number}:menu:{task_id}")

        # Switching №9 → №12 and selecting saved №9 restores its exact problem.
        await click("nav:numbers")
        await click("nav:task:9")
        task9 = await repository.task9_state(42)
        assert task9 is not None and isinstance(task9["problem"], dict)
        task9_id = str(task9["problem"]["problem_id"])
        await click(f"t9:menu:{task9_id}")
        await click("nav:numbers")
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
