"""Real aiogram routing and real PostgreSQL; only Telegram HTTP is substituted."""

import fnmatch
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
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

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 (aiogram interface)
        self.calls.append(method)
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


async def exercise_navigation(repository):
    session = TelegramSession()
    bot = Bot("123456:TEST", session=session)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    user = User(id=42, is_bot=False, first_name="Synthetic student")
    update_id = 1

    async def feed(update):
        await dispatcher.feed_update(bot, update, repository=repository)

    async def click(action, message=None):
        nonlocal update_id
        message = message or list(session.messages.values())[-1]
        data = next(
            button.callback_data
            for row in message.reply_markup.inline_keyboard
            for button in row
            if (button.callback_data or "").partition("~")[0] == action
        )
        update_id += 1
        await feed(
            Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=f"synthetic-{update_id}",
                    from_user=user,
                    chat_instance="synthetic",
                    message=message,
                    data=data,
                ),
            )
        )

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
        await click("nav:progress", original_menu)
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
        await click("nav:task:8")
        assert await repository.user_state(42) == "family_selection:8"
        await click("nav:numbers")
        await click("nav:main")
        await click("nav:progress")
        await click("progress:families")
        assert await repository.user_state(42) == "progress"
        await click("nav:main")
        assert (await repository.task6_state(42))["problem"]["problem_id"] == problem_id
    finally:
        await bot.session.close()


@pytest.mark.asyncio
async def test_dispatcher_inline_navigation_memory():
    await exercise_navigation(MemoryRepository())


@pytest.mark.asyncio
async def test_dispatcher_inline_navigation_postgres(navigation_pool):
    await exercise_navigation(PostgresRepository(navigation_pool))


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
