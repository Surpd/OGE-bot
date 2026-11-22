"""No imports of a model client, photo downloader or grading reservations."""

from aiogram.types import InlineKeyboardMarkup, Message

from app.bot.presentation import send_text
from app.persistence.repository import Repository

NOTICE = "ИМИТАЦИЯ: фото не скачивается и не отправляется модели; точность оценки не проверяется."


async def simulate(
    message: Message,
    repo: Repository,
    owner: int,
    markup: InlineKeyboardMarkup,
    *,
    error: bool = False,
) -> Message:
    await message.answer("ИМИТАЦИЯ · Проверяю решение…")
    text = (
        "ИМИТАЦИЯ · Ошибка проверки. Балл не выставлен. Можно повторить."
        if error
        else "ИМИТАЦИЯ · Пример результата: 1/2. Это заданный ответ заглушки, "
        "не оценка вашей работы. Пример обратной связи: обоснуйте переход к x² = 4."
    )
    return await send_text(
        message,
        repo,
        text + "\n\n" + NOTICE,
        reply_markup=markup,
        user_id_override=owner,
        text_on_photo_rejection=True,
    )
