import logging
import secrets
from typing import cast

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.bot.menu import MAIN_MENU, main_menu, number_menu, task6_menu
from app.math.registry import ANSWER_POLICY_BY_SNAPSHOT
from app.math.scheduler import build_candidate_batch
from app.persistence.repository import Repository

logger = logging.getLogger(__name__)
TASK6_LABEL = "№6 · Вычисления"


def _user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user is not None else None


async def _send_problem(
    message: Message,
    repository: Repository,
    *,
    action: str,
) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    await repository.ensure_task6_session(user_id)
    state = await repository.task6_state(user_id)
    state_value = cast(dict[str, object], state.get("state", {})) if state else {}
    current_problem = state.get("problem") if state else None
    if action == "resume":
        if isinstance(current_problem, dict) and state_value.get("status") == "active":
            saved_problem = current_problem
        elif isinstance(current_problem, dict):
            await message.answer(
                "Последнее задание уже завершено. Нажмите «➡ Следующее», чтобы продолжить.",
                reply_markup=task6_menu(),
            )
            return
        else:
            await message.answer("У вас нет незавершённой тренировки.", reply_markup=main_menu())
            return
    else:
        expected_problem_id = None
        if action == "advance" and isinstance(current_problem, dict):
            expected_problem_id = str(current_problem.get("problem_id", ""))
        candidates = build_candidate_batch(state_value, secrets.randbelow(2**63))
        try:
            saved_problem = await repository.advance_task6_problem(
                user_id, expected_problem_id, candidates
            )
        except RuntimeError:
            await message.answer(
                "Не удалось подготовить неповторяющееся задание. Попробуйте ещё раз.",
                reply_markup=task6_menu(),
            )
            return
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
    state = await repository.task6_state(message.from_user.id)
    has_session = bool(state and isinstance(state.get("problem"), dict))
    logger.info("user_started")
    await message.answer(
        "Привет! Это OGE Trainer — тренажёр первой части ОГЭ по математике.\n"
        "Выберите раздел в меню.",
        reply_markup=main_menu(has_session=has_session),
    )


async def cancel(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    has_session = False
    if user_id is not None:
        await repository.save_user_state(user_id, "main_menu")
        state = await repository.task6_state(user_id)
        has_session = bool(state and isinstance(state.get("problem"), dict))
    await message.answer("Текущий раздел закрыт.", reply_markup=main_menu(has_session=has_session))


async def continue_session(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    state = await repository.task6_state(user_id)
    if state is not None and isinstance(state.get("problem"), dict):
        await _send_problem(message, repository, action="resume")
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
    await _send_problem(message, repository, action="start")


async def task6_next(message: Message, repository: Repository) -> None:
    await _send_problem(message, repository, action="advance")


async def task6_skip(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    await _send_problem(message, repository, action="advance")


async def task6_hint(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    state = await repository.task6_state(user_id) if user_id is not None else None
    problem = state.get("problem") if state else None
    problem_id = str(problem.get("problem_id", "")) if isinstance(problem, dict) else ""
    hint = (
        await repository.task6_hint(user_id, problem_id)
        if user_id is not None and problem_id
        else None
    )
    await message.answer(hint or "Сначала откройте активное задание.", reply_markup=task6_menu())


async def task6_solution(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    state = await repository.task6_state(user_id) if user_id is not None else None
    problem = state.get("problem") if state is not None else None
    if not isinstance(problem, dict):
        await message.answer("Сначала откройте активное задание.", reply_markup=task6_menu())
        return
    problem_id = str(problem.get("problem_id", ""))
    revealed = (
        await repository.task6_reveal_solution(user_id, problem_id) if user_id is not None else None
    )
    saved_problem = revealed.get("problem") if revealed is not None else None
    if not isinstance(saved_problem, dict):
        await message.answer("Это задание уже сменилось. Откройте разбор для текущего задания.")
        return
    solution = saved_problem.get("solution", [])
    answer = str(saved_problem.get("correct_answer", ""))
    text = "\n".join(str(step) for step in solution) if isinstance(solution, list) else ""
    await message.answer(
        f"Разбор (самостоятельное решение не засчитывается):\n{text}\n\nОтвет: {answer}",
        reply_markup=task6_menu(),
    )


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
    policy_id = str(problem.get("answer_policy_id", ""))
    policy_version = str(problem.get("answer_policy_version", ""))
    policy = ANSWER_POLICY_BY_SNAPSHOT.get((family_id, policy_id, policy_version))
    if policy is None:
        await message.answer("Это задание временно недоступно. Вернитесь в меню.")
        return
    expected_problem_id = str(problem.get("problem_id", ""))
    expected = str(problem.get("correct_answer", ""))
    parsed = policy.parse(message.text)
    if parsed is None:
        await message.answer(
            "Введите числовой ответ. Например: 2,5 или −3.", reply_markup=task6_menu()
        )
        return
    is_correct = policy.accepts(message.text, expected)
    outcome = await repository.task6_attempt(
        user_id,
        expected_problem_id,
        message.text,
        is_correct,
        message.message_id if type(message.message_id) is int else None,
    )
    if outcome is None:
        await message.answer("Активное задание не найдено. Выберите №6 в меню.")
    elif outcome["status"] == "stale":
        await message.answer(
            "Ответ к уже сменившемуся заданию проигнорирован.",
            reply_markup=task6_menu(),
        )
    elif outcome["status"] == "duplicate":
        await message.answer("Это сообщение уже было обработано.", reply_markup=task6_menu())
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
    has_session = False
    if user_id is not None:
        await repository.save_user_state(user_id, "main_menu")
        state = await repository.task6_state(user_id)
        has_session = bool(state and isinstance(state.get("problem"), dict))
    await message.answer("Главное меню.", reply_markup=main_menu(has_session=has_session))


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
        f"Попыток всего: {attempts}\n"
        f"Попыток №1 / №2: {progress['first_attempts']} / {progress['second_attempts']}\n"
        f"Решено с первой / второй попытки: {progress['solved_first_try']} / "
        f"{progress['solved_second_try']}\n"
        f"Подсказок: {progress['hints_used']} · Разборов: {progress['solutions_viewed']}\n"
        f"Пропущено: {progress['skipped']}\n"
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
