"""Callback acknowledgement is a notification, never a training transaction."""

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)


async def answer_callback(
    callback: CallbackQuery, text: str | None = None, *, show_alert: bool | None = None
) -> bool:
    try:
        if show_alert is None:
            await callback.answer(text)
        else:
            await callback.answer(text, show_alert=show_alert)
    except TelegramBadRequest as error:
        # Delayed/replayed updates can outlive Telegram's query. The authenticated
        # update still needs its normal revision/idempotency checks and processing.
        expired = any(
            reason in error.message.lower()
            for reason in (
                "query is too old",
                "query id is invalid",
                "query_id_invalid",
            )
        )
        if not isinstance(error.method, AnswerCallbackQuery) or not expired:
            raise
        logger.warning("telegram_callback_ack_expired")
        return False
    return True
