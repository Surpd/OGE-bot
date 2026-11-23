"""Owner/private-chat perimeter and persistent QA interception before student handlers."""

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    TelegramObject,
    Update,
)

from app.bot.callbacks import answer_callback
from app.companion.qa import Desk
from app.companion.storage import TestRepository, assert_namespace
from app.config import Settings, test_settings
from app.persistence.repository import Repository


def allowed_payload(payload: dict[str, Any], owner: int | None) -> bool:
    """Also guards the raw Widget endpoint before claim_update or any user reads."""
    event = payload.get("message") or payload.get("callback_query") or payload.get("widget_query")
    if not isinstance(event, dict) or owner is None:
        return False
    sender = event.get("from")
    origin = event.get("message", event)
    if not isinstance(sender, dict) or sender.get("id") != owner or not isinstance(origin, dict):
        return False
    chat = origin.get("chat")
    return bool(
        isinstance(chat, dict)
        and chat.get("type") == "private"
        and chat.get("id") == owner
        and not event.get("inline_message_id")
        and not origin.get("forward_origin")
        and not origin.get("forward_date")
        and not origin.get("forward_from")
        and not origin.get("is_automatic_forward")
    )


@asynccontextmanager
async def state_for(repository: Repository, owner: int) -> AsyncIterator[dict[str, Any]]:
    pool = getattr(repository, "_pool", None)
    error: BaseException | None = None
    if pool is None:
        if not hasattr(repository, "_staging_states"):
            repository._staging_states = {}  # type: ignore[attr-defined]
            repository._staging_lock = asyncio.Lock()  # type: ignore[attr-defined]
        async with repository._staging_lock:  # type: ignore[attr-defined]
            state = repository._staging_states.setdefault(owner, {})  # type: ignore[attr-defined]
            yield state
        return
    async with pool.acquire() as conn, conn.transaction():
        if not isinstance(repository, TestRepository):
            raise RuntimeError("Companion requires its isolated repository")
        await assert_namespace(conn, repository.schema)
        await conn.execute("SELECT pg_advisory_xact_lock(74120609, $1)", owner % 2147483647)
        await conn.execute(
            "INSERT INTO qa_sessions(owner) VALUES($1) ON CONFLICT DO NOTHING", owner
        )
        raw = await conn.fetchval("SELECT payload FROM qa_sessions WHERE owner=$1", owner)
        state = json.loads(raw)
        try:
            yield state
        except BaseException as exc:
            # Consume callbacks even when Telegram delivery is uncertain. A retry is
            # explicit; webhook redelivery cannot generate another card/attempt.
            error = exc
        await conn.execute(
            "UPDATE qa_sessions SET payload=$2::jsonb,updated_at=now() WHERE owner=$1",
            owner,
            json.dumps(state),
        )
    if error is not None:
        raise error


class CompanionMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings, owner_ids: frozenset[int], sha: str) -> None:
        self.settings = settings.model_copy(
            update={
                "oge_part2_enabled": True,
                "oge_grading_enabled": False,
                "openai_api_key": None,
            }
        )
        self.owner_ids = owner_ids
        self.sha = sha

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        token = test_settings.set(self.settings)
        try:
            return await self.process(handler, event, data)
        finally:
            test_settings.reset(token)

    async def process(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update) or not any(
            allowed_payload(event.model_dump(mode="json", by_alias=True, exclude_none=True), owner)
            for owner in self.owner_ids
        ):
            return None
        callback: CallbackQuery | None = event.callback_query
        incoming = event.message
        message = callback.message if callback else incoming
        if not isinstance(message, Message):
            return None
        actor = callback.from_user if callback else message.from_user
        if actor is None:
            return None
        owner = actor.id
        repository = data["repository"]
        # The ordinary upload flow receives only a synthetic marker, never a real file ID.
        if incoming and incoming.photo:
            incoming = incoming.model_copy(
                update={
                    "photo": [
                        p.model_copy(
                            update={
                                "file_id": "companion-synthetic",
                                "file_unique_id": "companion-synthetic",
                            }
                        )
                        for p in incoming.photo
                    ],
                    "caption": None,
                }
            ).as_(message.bot)
            event = event.model_copy(update={"message": incoming}).as_(message.bot)
            message = incoming
        after = None
        handled = False
        async with state_for(repository, owner) as state:
            state["sha"] = self.sha
            desk = Desk(state, repository, owner)
            await desk.prepare()
            words = (incoming.text or "").split(maxsplit=1) if incoming else []
            command = words[0].split("@")[0] if words else ""
            if command in {"/api_test", "/api_status"} or (
                callback and (callback.data or "").startswith("p2:apitest:")
            ):
                await message.answer(
                    "Тестовый бот: внешние API запрещены. Фото проверяется заглушкой."
                )
                return None
            if command in {"/qa", "/start"} or (incoming and incoming.text == "🔬 Проверки"):
                state["visited"] = True
                await message.answer(f"Тестовый бот · кандидат {self.sha}")
                await desk.home(message)
                return None
            if callback and (callback.data or "").startswith("qa:"):
                handled = True
                parts = (callback.data or "").split(":", 2)
                if (
                    len(parts) != 3
                    or parts[1] != state.get("revision")
                    or message.message_id != state.get("menu")
                    or parts[2] not in state.get("actions", [])
                    or not state.get("active")
                ):
                    await answer_callback(
                        callback, "Эта кнопка устарела. Откройте «Проверки» в меню бота."
                    )
                    return None
                state["revision"] = None  # Claim while holding the database lock.
                await answer_callback(callback)
                if parts[2] == "exit":
                    state["active"] = False
                    state.pop("pending", None)
                    after = "student"
                elif parts[2] == "reset_confirm":
                    if not isinstance(repository, TestRepository):
                        raise RuntimeError("Reset requires isolated storage")
                    await repository.reset_owner(owner)
                    archive = state.get("archive", {})
                    state.clear()
                    state.update(archive=archive, sha=self.sha)
                    await desk.home(message)
                else:
                    try:
                        await desk.action(message, parts[2])
                    except (ValueError, KeyError, IndexError, TypeError):
                        await desk.say(
                            message,
                            "Точное восстановление недоступно. "
                            "Похожая задача не подставлена. Выберите сохранённый снимок "
                            "или поддерживаемую версию.",
                            [[("К проверкам", "home"), ("Выйти", "exit")]],
                        )
            elif state.get("active"):
                handled = True
                if callback:
                    await answer_callback(callback, "Сначала выйдите из точной проверки.")
                elif incoming:
                    # Redelivery does not run input twice, including seed/ID requests.
                    if incoming.message_id <= state.get("last_input", 0):
                        return None
                    state["last_input"] = incoming.message_id
                    try:
                        await desk.input(incoming)
                    except (ValueError, KeyError, IndexError, TypeError):
                        await desk.say(
                            message,
                            "Точный вариант недоступен или формат неверен. "
                            "Похожая задача не подставлена.",
                            [[("К проверкам", "home"), ("Выйти", "exit")]],
                        )
        if after in {"student", "menu"}:
            from app.bot.router import continue_session, start

            await message.answer(
                "Режим ученика · только тестовая история. Фото: явная имитация, без модели."
            )
            user_message = message.model_copy(update={"from_user": copy.copy(actor)}).as_(
                message.bot
            )
            if after == "student" and await repository.last_training_mode(owner):
                await continue_session(
                    user_message, repository, data.get("oge15_repository"), user_id_override=owner
                )
            else:
                await start(user_message, repository, data.get("oge15_repository"))
            await message.answer(
                "Вернуться к точным проверкам можно кнопкой под полем ввода.",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text="🔬 Проверки")]],
                    resize_keyboard=True,
                    is_persistent=True,
                ),
            )
        elif not handled:
            return await handler(event, data)
        return None
