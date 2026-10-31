import logging
import secrets
from typing import cast
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.bot.menu import MAIN_MENU, main_menu, number_menu, task6_menu
from app.math.generator import generate_random
from app.math.registry import SPEC_BY_ID
from app.persistence.repository import Repository

logger = logging.getLogger(__name__)
TASK6_LABEL = "№6 · Вычисления"
TASK6_ACTIONS = ("💡 Подсказка", "📘 Разбор", "➡ Следующее", "⏭ Пропустить", "↩ В меню")


def _user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user is not None else None


async def _send_problem(message: Message, repository: Repository, *, new: bool) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    await repository.ensure_task6_session(user_id)
    if new:
        problem = generate_random(secrets.randbelow(2**63))
        snapshot = problem.to_snapshot()
        snapshot["problem_id"] = str(uuid4())
        snapshot["reference_structure_id"] = problem.reference_structure_id
        await repository.issue_task6_problem(user_id, snapshot)
    state = await repository.task6_state(user_id)
    if state is None or not isinstance(state.get("problem"), dict):
        await message.answer("Не удалось восстановить задачу. Попробуйте ещё раз.")
        return
    saved_problem = cast(dict[str, object], state["problem"])
    status = cast(dict[str, object], state.get("state", {})).get("status")
    if status != "active":
        problem = generate_random(secrets.randbelow(2**63))
        snapshot = problem.to_snapshot()
        snapshot["problem_id"] = str(uuid4())
        snapshot["reference_structure_id"] = problem.reference_structure_id
        saved_problem = await repository.issue_task6_problem(user_id, snapshot)
    await message.answer(
        f"Задание №6 · вычисления\n\n{saved_problem['condition']}\n\n"
        "Введите ответ сообщением. Десятичную дробь можно записать через запятую.",
        reply_markup=task6_menu(),
    )


async def start(message: Message, repository: Repository) -> None:
    if message.from_user is None:
        return
    await repository.register_user(message.from_user.id)
    await repository.save_user_state(message.from_user.id, "main_menu")
    logger.info("user_started")
    await message.answer(
        "Привет! Это OGE Trainer — тренажёр первой части ОГЭ по математике.\n"
        "Выберите раздел в меню.",
        reply_markup=main_menu(),
    )


async def cancel(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is not None:
        await repository.task6_finish_problem(user_id, "menu")
        await repository.save_user_state(user_id, "main_menu")
    await message.answer("Текущий раздел закрыт.", reply_markup=main_menu())


async def continue_session(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    state = await repository.task6_state(user_id)
    if state is not None and isinstance(state.get("problem"), dict):
        await _send_problem(message, repository, new=False)
        return
    session = await repository.current_session(user_id)
    if session is None:
        await message.answer("У вас нет незавершённой тренировки.", reply_markup=main_menu())
        return
    await message.answer(
        "Сохранённая тренировка доступна.", reply_markup=main_menu(has_session=True)
    )


async def choose_number(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is not None:
        await repository.save_user_state(user_id, "number_selection")
    await message.answer("Выберите номер задания:", reply_markup=number_menu())


async def choose_task6(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is not None:
        await repository.save_user_state(user_id, "task6")
    await _send_problem(message, repository, new=True)


async def task6_next(message: Message, repository: Repository) -> None:
    await _send_problem(message, repository, new=True)


async def task6_skip(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    await repository.task6_finish_problem(user_id, "skipped")
    await _send_problem(message, repository, new=True)


async def task6_hint(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    hint = await repository.task6_hint(user_id) if user_id is not None else None
    await message.answer(hint or "Сначала откройте активное задание.", reply_markup=task6_menu())


async def task6_solution(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    state = await repository.task6_state(user_id) if user_id is not None else None
    problem = state.get("problem") if state is not None else None
    if not isinstance(problem, dict):
        await message.answer("Сначала откройте активное задание.", reply_markup=task6_menu())
        return
    solution = problem.get("solution", [])
    answer = str(problem.get("correct_answer", ""))
    text = "\n".join(str(step) for step in solution) if isinstance(solution, list) else ""
    await message.answer(f"Разбор:\n{text}\n\nОтвет: {answer}", reply_markup=task6_menu())


async def task6_answer(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None or message.text is None:
        return
    state = await repository.task6_state(user_id)
    problem = state.get("problem") if state is not None else None
    session_state = state.get("state", {}) if state is not None else {}
    if not isinstance(problem, dict) or not isinstance(session_state, dict):
        await message.answer("Сначала выберите «По номеру → №6».", reply_markup=main_menu())
        return
    if session_state.get("status") != "active":
        await message.answer(
            "Это задание уже завершено. Нажмите «➡ Следующее».", reply_markup=task6_menu()
        )
        return
    family_id = str(problem.get("family_id", ""))
    spec = SPEC_BY_ID.get(family_id)
    if spec is None:
        await message.answer("Это задание временно недоступно. Вернитесь в меню.")
        return
    expected = str(problem.get("correct_answer", ""))
    parsed = spec.policy.parse(message.text)
    if parsed is None:
        await message.answer(
            "Введите числовой ответ. Например: 2,5 или −3.", reply_markup=task6_menu()
        )
        return
    is_correct = spec.policy.accepts(message.text, expected)
    outcome = await repository.task6_attempt(user_id, message.text, is_correct)
    if outcome is None:
        await message.answer("Активное задание не найдено. Выберите №6 в меню.")
    elif outcome["status"] == "solved":
        await message.answer(
            "Верно! Ответ засчитан. Нажмите «➡ Следующее».", reply_markup=task6_menu()
        )
    elif outcome["status"] == "active":
        await message.answer(
            "Пока неверно. Попробуйте ещё раз; правильный ответ не раскрываю.",
            reply_markup=task6_menu(),
        )
    elif outcome["status"] == "failed":
        saved_problem = cast(dict[str, object], outcome["problem"])
        solution = saved_problem.get("solution", [])
        steps = "\n".join(str(step) for step in solution) if isinstance(solution, list) else ""
        await message.answer(
            f"Вторая попытка неверна. Правильный ответ: {saved_problem['correct_answer']}.\n\n"
            f"Разбор:\n{steps}\n\nНажмите «➡ Следующее».",
            reply_markup=task6_menu(),
        )
    else:
        await message.answer("Ответ по этому заданию уже обработан. Нажмите «➡ Следующее».")


async def menu_section(message: Message) -> None:
    await message.answer(
        "Этот раздел пока не включён: сначала для него требуется отдельная проверка качества.",
        reply_markup=main_menu(),
    )


async def return_to_menu(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is not None:
        await repository.task6_finish_problem(user_id, "menu")
        await repository.save_user_state(user_id, "main_menu")
    await message.answer("Главное меню.", reply_markup=main_menu())


async def show_progress(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    progress = await repository.task6_progress(user_id)
    issued = progress["issued"]
    answered = progress["answered"]
    correct = progress["correct"]
    attempts = progress["attempts"]
    accuracy = (correct * 100 + answered // 2) // answered if answered else 0
    await message.answer(
        "📊 Прогресс по заданию №6\n"
        f"Выдано задач: {issued}\n"
        f"Задач с ответом: {answered}\n"
        f"Решено верно: {correct}\n"
        f"Попыток: {attempts}\n"
        f"Точность: {accuracy}%",
        reply_markup=main_menu(has_session=issued > answered),
    )


async def unknown_message(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    state = await repository.task6_state(user_id) if user_id is not None else None
    if state is not None and isinstance(state.get("problem"), dict):
        session_state = cast(dict[str, object], state.get("state", {}))
        if session_state.get("status") == "active":
            await task6_answer(message, repository)
            return
    await message.answer("Используйте кнопки меню или команду /start.", reply_markup=main_menu())


def build_router() -> Router:
    router = Router()
    router.message.register(start, CommandStart())
    router.message.register(cancel, Command("cancel"))
    router.message.register(continue_session, F.text == "▶ Продолжить")
    router.message.register(choose_number, F.text == "🧮 По номеру")
    router.message.register(choose_task6, F.text == TASK6_LABEL)
    router.message.register(task6_next, F.text == "➡ Следующее")
    router.message.register(task6_skip, F.text == "⏭ Пропустить")
    router.message.register(task6_hint, F.text == "💡 Подсказка")
    router.message.register(task6_solution, F.text == "📘 Разбор")
    router.message.register(return_to_menu, F.text == "↩ В меню")
    router.message.register(show_progress, F.text == "📊 Прогресс")
    router.message.register(menu_section, F.text.in_(MAIN_MENU))
    router.message.register(unknown_message)
    return router
