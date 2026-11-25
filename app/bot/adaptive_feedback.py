from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.adaptive.skills import title
from app.adaptive.store import sync
from app.config import get_settings

MILESTONES = {
    "gap_opened": "Ошибки повторились. Этот тип появился в персональной тренировке.",
    "gap_reopened": "Снова было несколько ошибок. Вернём этот тип в тренировку.",
    "skill_confirmed": "Три новых варианта подряд решены без помощи.",
    "gap_closed": "Три новых варианта подряд решены без помощи. Пробел закрыт.",
}


class AdaptiveFeedback(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        if not get_settings().oge_adaptive_enabled or not isinstance(
            event, Message | CallbackQuery
        ):
            return result
        message = event.message if isinstance(event, CallbackQuery) else event
        pool = getattr(data.get("repository"), "_pool", None)
        if pool is None or not event.from_user or not isinstance(message, Message):
            return result
        async with pool.acquire() as conn, conn.transaction():
            owner = await conn.fetchval(
                """SELECT id FROM users u WHERE telegram_user_id=$1
                AND EXISTS(SELECT FROM adaptive_dirty WHERE owner=u.id)""",
                event.from_user.id,
            )
            notices = await sync(conn, owner) if owner else []
        for skill, reason in notices:
            if reason in MILESTONES:
                await message.answer(f"{title(skill)}\n{MILESTONES[reason]}")
        return result
