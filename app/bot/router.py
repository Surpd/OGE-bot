import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.bot.menu import MAIN_MENU, main_menu
from app.persistence.repository import Repository

logger = logging.getLogger(__name__)


async def start(message: Message, repository: Repository) -> None:
    if message.from_user is None:
        return
    await repository.register_user(message.from_user.id)
    await repository.save_user_state(message.from_user.id, "main_menu")
    logger.info("user_started")
    await message.answer(
        "Привет! Это OGE Trainer — тренажёр первой части ОГЭ по математике.\n"
        "Выберите раздел в меню. Задания пока готовятся.",
        reply_markup=main_menu(),
    )


async def cancel(message: Message, repository: Repository) -> None:
    if message.from_user is not None:
        await repository.save_user_state(message.from_user.id, "main_menu")
    await message.answer("Текущий раздел закрыт.", reply_markup=main_menu())


async def continue_session(message: Message, repository: Repository) -> None:
    if message.from_user is None:
        return
    session = await repository.current_session(message.from_user.id)
    if session is None:
        await message.answer("У вас нет незавершённой тренировки.", reply_markup=main_menu())
        return
    await message.answer(
        "Тренировка сохранена и готова к продолжению. Раздел заданий пока готовится.",
        reply_markup=main_menu(has_session=True),
    )


async def choose_number(message: Message, repository: Repository) -> None:
    if message.from_user is not None:
        await repository.save_user_state(message.from_user.id, "number_selection")
    await message.answer(
        "Выберите номер задания. Все номера 1–19 пока готовятся.",
        reply_markup=main_menu(),
    )


async def menu_section(message: Message) -> None:
    await message.answer(
        "Этот раздел находится в разработке. Задания появятся после отдельной проверки качества.",
        reply_markup=main_menu(),
    )


async def unknown_message(message: Message) -> None:
    await message.answer("Используйте кнопки меню или команду /start.", reply_markup=main_menu())


def build_router() -> Router:
    router = Router()
    router.message.register(start, CommandStart())
    router.message.register(cancel, Command("cancel"))
    router.message.register(continue_session, F.text == "▶ Продолжить")
    router.message.register(choose_number, F.text == "🧮 По номеру")
    router.message.register(menu_section, F.text.in_(MAIN_MENU))
    router.message.register(unknown_message)
    return router
