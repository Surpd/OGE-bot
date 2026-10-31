import logging
import secrets
from typing import cast

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.menu import MAIN_MENU, main_menu, number_menu, progress_menu, task6_menu, task9_menu
from app.math.equations import ANSWER_POLICIES_BY_SNAPSHOT
from app.math.oge9_scheduler import build_task9_candidate_batch
from app.math.registry import ANSWER_POLICY_BY_SNAPSHOT
from app.math.scheduler import build_candidate_batch
from app.persistence.repository import Repository

logger = logging.getLogger(__name__)
TASK6_LABEL = "№6 · Вычисления"
TASK9_LABEL = "№9 · Уравнения"


def _user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user is not None else None


def _has_resumable_task6(state: dict[str, object] | None) -> bool:
    if state is None or not isinstance(state.get("problem"), dict):
        return False
    session_state = state.get("state")
    return isinstance(session_state, dict) and session_state.get("status") == "active"


def _has_resumable_task9(state: dict[str, object] | None) -> bool:
    if state is None or not isinstance(state.get("problem"), dict):
        return False
    session_state = state.get("state")
    return isinstance(session_state, dict) and session_state.get("status") == "active"


async def _has_resumable_session(repository: Repository, user_id: int) -> bool:
    state6, state9 = await repository.task6_state(user_id), await repository.task9_state(user_id)
    return _has_resumable_task6(state6) or _has_resumable_task9(state9)


async def _send_problem(
    message: Message,
    repository: Repository,
    *,
    action: str,
    expected_problem_id: str | None = None,
    expected_screen: str | None = None,
    expected_prompt_message_id: int | None = None,
    user_id_override: int | None = None,
    skip_active: bool = False,
) -> bool:
    user_id = user_id_override if user_id_override is not None else _user_id(message)
    if user_id is None:
        return False
    await repository.ensure_task6_session(user_id)
    state = await repository.task6_state(user_id)
    state_value = cast(dict[str, object], state.get("state", {})) if state else {}
    current_problem = state.get("problem") if state else None
    if action == "resume":
        if isinstance(current_problem, dict) and state_value.get("status") == "active":
            saved_problem = current_problem
            await repository.save_user_state(user_id, "task6")
        elif isinstance(current_problem, dict):
            await message.answer(
                "Последнее задание уже завершено. Нажмите «➡ Следующее», чтобы продолжить.",
                reply_markup=task6_menu(str(current_problem["problem_id"])),
            )
            return False
        else:
            await message.answer("У вас нет незавершённой тренировки.", reply_markup=main_menu())
            return False
    else:
        if (
            action == "advance"
            and expected_problem_id is None
            and isinstance(current_problem, dict)
        ):
            expected_problem_id = str(current_problem.get("problem_id", ""))
        candidates = build_candidate_batch(state_value, secrets.randbelow(2**63))
        try:
            saved_problem = await repository.advance_task6_problem(
                user_id,
                expected_problem_id,
                candidates,
                expected_screen=expected_screen,
                expected_prompt_message_id=expected_prompt_message_id,
                skip_active=skip_active,
            )
        except RuntimeError:
            await message.answer(
                "Не удалось подготовить неповторяющееся задание. Попробуйте ещё раз.",
                reply_markup=(
                    task6_menu(expected_problem_id)
                    if expected_problem_id is not None
                    else main_menu(has_session=False)
                ),
            )
            return False
        if (
            action == "advance"
            and expected_problem_id is not None
            and saved_problem.get("_transitioned") is False
        ):
            return False
    sent = await message.answer(
        f"Задание №6 · вычисления\n\n{saved_problem['condition']}\n\n"
        "Напишите ответ числом в чат. Дробную часть можно отделять запятой или точкой.",
        reply_markup=task6_menu(str(saved_problem["problem_id"])),
    )
    prompt_message_id = getattr(sent, "message_id", None)
    if type(prompt_message_id) is int:
        await repository.set_task6_prompt_message(
            user_id, str(saved_problem["problem_id"]), prompt_message_id
        )
    return True


async def start(message: Message, repository: Repository) -> None:
    if message.from_user is None:
        return
    await repository.register_user(message.from_user.id)
    await repository.save_user_state(message.from_user.id, "main_menu")
    state = await repository.task6_state(message.from_user.id)
    state9 = await repository.task9_state(message.from_user.id)
    has_session = _has_resumable_task6(state) or _has_resumable_task9(state9)
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
        has_session = await _has_resumable_session(repository, user_id)
    await message.answer("Текущий раздел закрыт.", reply_markup=main_menu(has_session=has_session))


async def continue_session(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    resume_mode = await repository.last_training_mode(user_id)
    state9 = await repository.task9_state(user_id)
    state6 = await repository.task6_state(user_id)
    if resume_mode == "task9" and _has_resumable_task9(state9):
        await _send_task9_problem(message, repository, action="resume")
        return
    if resume_mode == "task6" and _has_resumable_task6(state6):
        await _send_problem(message, repository, action="resume")
        return
    if _has_resumable_task9(state9):
        await _send_task9_problem(message, repository, action="resume")
        return
    if _has_resumable_task6(state6):
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


async def _send_task9_problem(
    message: Message,
    repository: Repository,
    *,
    action: str,
    expected_problem_id: str | None = None,
    expected_screen: str | None = None,
    expected_prompt_message_id: int | None = None,
    user_id_override: int | None = None,
    skip_active: bool = False,
) -> bool:
    user_id = user_id_override if user_id_override is not None else _user_id(message)
    if user_id is None:
        return False
    await repository.ensure_task9_session(user_id)
    state = await repository.task9_state(user_id)
    state_value = cast(dict[str, object], state.get("state", {})) if state else {}
    current_problem = state.get("problem") if state else None
    if action == "resume":
        if not isinstance(current_problem, dict) or state_value.get("status") != "active":
            await message.answer("Нет незавершённой тренировки №9.", reply_markup=main_menu())
            return False
        saved_problem = current_problem
        await repository.save_user_state(user_id, "task9")
    else:
        if action == "start" and isinstance(current_problem, dict):
            if state_value.get("status") == "active":
                saved_problem = current_problem
                await repository.save_user_state(user_id, "task9")
                sent = await message.answer(
                    f"Задание №9 · уравнения\n\n{saved_problem['condition']}\n\n"
                    "Напишите ответ числом в чат. Дробную часть можно отделять запятой или точкой.",
                    reply_markup=task9_menu(str(saved_problem["problem_id"])),
                )
                prompt_id = getattr(sent, "message_id", None)
                if type(prompt_id) is int:
                    await repository.set_task9_prompt_message(
                        user_id, str(saved_problem["problem_id"]), prompt_id
                    )
                return True
            expected_problem_id = str(current_problem.get("problem_id", ""))
            action = "advance"
        if (
            action == "advance"
            and expected_problem_id is None
            and isinstance(current_problem, dict)
        ):
            expected_problem_id = str(current_problem.get("problem_id", ""))
        candidates = build_task9_candidate_batch(state_value, secrets.randbelow(2**63))
        try:
            saved_problem = await repository.advance_task9_problem(
                user_id,
                expected_problem_id,
                candidates,
                expected_screen=expected_screen,
                expected_prompt_message_id=expected_prompt_message_id,
                skip_active=skip_active,
            )
        except RuntimeError:
            await message.answer("Не удалось подготовить задачу №9. Попробуйте ещё раз.")
            return False
        if action == "advance" and saved_problem.get("_transitioned") is False:
            return False
        if expected_screen is None:
            await repository.save_user_state(user_id, "task9")
    sent = await message.answer(
        f"Задание №9 · уравнения\n\n{saved_problem['condition']}\n\n"
        "Напишите ответ числом в чат. Дробную часть можно отделять запятой или точкой.",
        reply_markup=task9_menu(str(saved_problem["problem_id"])),
    )
    prompt_id = getattr(sent, "message_id", None)
    if type(prompt_id) is int:
        await repository.set_task9_prompt_message(
            user_id, str(saved_problem["problem_id"]), prompt_id
        )
    return True


async def choose_task9(message: Message, repository: Repository) -> None:
    await _send_task9_problem(message, repository, action="start")


async def task6_next(message: Message, repository: Repository) -> None:
    await _send_problem(message, repository, action="advance", expected_screen="task6")


async def task6_skip(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    await _send_problem(
        message, repository, action="advance", expected_screen="task6", skip_active=True
    )


async def task6_callback(callback: CallbackQuery, repository: Repository) -> None:
    data = callback.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "t6" or callback.message is None:
        await callback.answer()
        return
    _, action, expected_problem_id = parts
    user_id = callback.from_user.id
    message = cast(Message, callback.message)
    control_message_id = getattr(message, "message_id", None)
    if type(control_message_id) is not int:
        await callback.answer("Кнопка больше не связана с активным заданием.")
        return
    if action == "menu":
        transitioned = await repository.transition_task_screen(
            user_id,
            "task6",
            expected_problem_id,
            "main_menu",
            expected_prompt_message_id=control_message_id,
        )
        if not transitioned:
            await callback.answer("Тренировка приостановлена или задание уже сменилось.")
            return
        has_session = await _has_resumable_session(repository, user_id)
        await message.answer("Главное меню.", reply_markup=main_menu(has_session=has_session))
        await callback.answer()
        return

    if await repository.user_state(user_id) != "task6":
        await callback.answer("Тренировка приостановлена. Нажмите «Продолжить».")
        return

    state = await repository.task6_state(user_id)
    problem = state.get("problem") if state else None
    current_id = str(problem.get("problem_id", "")) if isinstance(problem, dict) else ""
    if current_id != expected_problem_id:
        await callback.answer("Это задание уже сменилось.")
        return

    if action in {"next", "skip"}:
        advanced = await _send_problem(
            message,
            repository,
            action="advance",
            expected_problem_id=expected_problem_id,
            expected_screen="task6",
            expected_prompt_message_id=control_message_id,
            user_id_override=user_id,
            skip_active=action == "skip",
        )
        await callback.answer("Задание уже сменилось." if not advanced else None)
        return

    if action == "hint":
        hint = await repository.task6_hint(
            user_id, expected_problem_id, expected_prompt_message_id=control_message_id
        )
        await message.answer(hint or "Подсказок больше нет.")
    elif action == "solution":
        revealed = await repository.task6_reveal_solution(
            user_id, expected_problem_id, expected_prompt_message_id=control_message_id
        )
        saved_problem = revealed.get("problem") if revealed else None
        if not isinstance(saved_problem, dict):
            await callback.answer("Это задание уже сменилось.")
            return
        solution = saved_problem.get("solution", [])
        steps = "\n".join(str(step) for step in solution) if isinstance(solution, list) else ""
        sent = await message.answer(
            "Разбор (самостоятельное решение не засчитывается):\n"
            f"{steps}\n\nОтвет: {saved_problem['correct_answer']}",
            reply_markup=task6_menu(expected_problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            await repository.set_task6_prompt_message(user_id, expected_problem_id, result_id)
    else:
        await callback.answer()
        return
    await callback.answer()


async def task6_hint(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None or await repository.user_state(user_id) != "task6":
        await message.answer("Сначала откройте активную тренировку №6.")
        return
    state = await repository.task6_state(user_id) if user_id is not None else None
    problem = state.get("problem") if state else None
    problem_id = str(problem.get("problem_id", "")) if isinstance(problem, dict) else ""
    hint = (
        await repository.task6_hint(user_id, problem_id)
        if user_id is not None and problem_id
        else None
    )
    await message.answer(
        hint or "Сначала откройте активное задание."
    )


async def task6_solution(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None or await repository.user_state(user_id) != "task6":
        await message.answer("Сначала откройте активную тренировку №6.")
        return
    state = await repository.task6_state(user_id) if user_id is not None else None
    problem = state.get("problem") if state is not None else None
    if not isinstance(problem, dict):
        await message.answer("Сначала откройте активное задание.")
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
    sent = await message.answer(
        f"Разбор (самостоятельное решение не засчитывается):\n{text}\n\nОтвет: {answer}",
        reply_markup=task6_menu(problem_id, completed=True),
    )
    result_id = getattr(sent, "message_id", None)
    if type(result_id) is int and user_id is not None:
        await repository.set_task6_prompt_message(user_id, problem_id, result_id)


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
        await message.answer("Это задание уже завершено. Нажмите «➡ Следующее».")
        return
    prompt_message_id = session_state.get("input_prompt_message_id")
    replied_to = getattr(message.reply_to_message, "message_id", None)
    if type(prompt_message_id) is not int or (
        replied_to is not None and replied_to != prompt_message_id
    ):
        await message.answer("Ответ к предыдущему заданию не принят. Напишите ответ числом в чат.")
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
        await message.answer("Введите числовой ответ. Например: 2,5 или −3.")
        return
    is_correct = policy.accepts(message.text, expected)
    outcome = await repository.task6_attempt(
        user_id,
        expected_problem_id,
        message.text,
        is_correct,
        message.message_id if type(message.message_id) is int else None,
        prompt_message_id,
    )
    if outcome is None:
        await message.answer("Активное задание не найдено. Выберите №6 в меню.")
    elif outcome["status"] == "stale":
        await message.answer("Ответ к уже сменившемуся заданию проигнорирован.")
    elif outcome["status"] == "duplicate":
        await message.answer("Это сообщение уже было обработано.")
    elif outcome["status"] == "solved":
        sent = await message.answer(
            "✅ Верно!\nОтвет засчитан.",
            reply_markup=task6_menu(expected_problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            await repository.set_task6_prompt_message(user_id, expected_problem_id, result_id)
    elif outcome["status"] == "active":
        sent = await message.answer(
            "Пока неверно. Попробуйте ещё раз.",
            reply_markup=task6_menu(expected_problem_id),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            await repository.set_task6_prompt_message(user_id, expected_problem_id, result_id)
    elif outcome["status"] == "failed":
        saved_problem = cast(dict[str, object], outcome["problem"])
        solution = saved_problem.get("solution", [])
        steps = "\n".join(str(step) for step in solution) if isinstance(solution, list) else ""
        sent = await message.answer(
            f"Вторая попытка неверна. Правильный ответ: {saved_problem['correct_answer']}.\n\n"
            f"Разбор:\n{steps}",
            reply_markup=task6_menu(expected_problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            await repository.set_task6_prompt_message(user_id, expected_problem_id, result_id)
    else:
        await message.answer("Ответ по этому заданию уже обработан. Нажмите «➡ Следующее».")


async def task9_callback(callback: CallbackQuery, repository: Repository) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "t9" or callback.message is None:
        await callback.answer()
        return
    _, action, expected_problem_id = parts
    user_id = callback.from_user.id
    message = cast(Message, callback.message)
    control_message_id = getattr(message, "message_id", None)
    if type(control_message_id) is not int:
        await callback.answer("Кнопка больше не связана с активным заданием.")
        return
    if action == "menu":
        transitioned = await repository.transition_task_screen(
            user_id,
            "task9",
            expected_problem_id,
            "main_menu",
            expected_prompt_message_id=control_message_id,
        )
        if not transitioned:
            await callback.answer("Тренировка приостановлена или задание уже сменилось.")
            return
        await message.answer(
            "Главное меню.",
            reply_markup=main_menu(has_session=await _has_resumable_session(repository, user_id)),
        )
        await callback.answer()
        return
    if await repository.user_state(user_id) != "task9":
        await callback.answer("Тренировка приостановлена. Нажмите «Продолжить».")
        return
    state = await repository.task9_state(user_id)
    problem = state.get("problem") if state else None
    current_id = str(problem.get("problem_id", "")) if isinstance(problem, dict) else ""
    if current_id != expected_problem_id:
        await callback.answer("Это задание уже сменилось.")
        return
    if action in {"next", "skip"}:
        advanced = await _send_task9_problem(
            message,
            repository,
            action="advance",
            expected_problem_id=expected_problem_id,
            expected_screen="task9",
            expected_prompt_message_id=control_message_id,
            user_id_override=user_id,
            skip_active=action == "skip",
        )
        await callback.answer(None if advanced else "Это задание уже сменилось.")
        return
    if action == "hint":
        hint = await repository.task9_hint(
            user_id, expected_problem_id, expected_prompt_message_id=control_message_id
        )
        await message.answer(hint or "Подсказок больше нет.")
    elif action == "solution":
        revealed = await repository.task9_reveal_solution(
            user_id, expected_problem_id, expected_prompt_message_id=control_message_id
        )
        snapshot = revealed.get("problem") if revealed else None
        if not isinstance(snapshot, dict):
            await callback.answer("Это задание уже сменилось.")
            return
        steps = snapshot.get("solution", [])
        rendered_steps = "\n".join(str(step) for step in steps) if isinstance(steps, list) else ""
        sent = await message.answer(
            "Разбор (самостоятельное решение не засчитывается):\n"
            f"{rendered_steps}\n\nОтвет: {snapshot['correct_answer']}",
            reply_markup=task9_menu(expected_problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            await repository.set_task9_prompt_message(user_id, expected_problem_id, result_id)
    else:
        await callback.answer()
        return
    await callback.answer()


async def task9_answer(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None or message.text is None:
        return
    state = await repository.task9_state(user_id)
    problem = state.get("problem") if state else None
    session_state = state.get("state", {}) if state else {}
    if not isinstance(problem, dict) or not isinstance(session_state, dict):
        await message.answer("Сначала выберите «По номеру → №9».", reply_markup=main_menu())
        return
    problem_id = str(problem.get("problem_id", ""))
    if session_state.get("status") != "active":
        await message.answer("Задание завершено. Нажмите «➡ Следующее».")
        return
    prompt_id = session_state.get("input_prompt_message_id")
    replied_to = getattr(message.reply_to_message, "message_id", None)
    if type(prompt_id) is not int or (replied_to is not None and replied_to != prompt_id):
        await message.answer("Ответ к предыдущему заданию не принят. Напишите ответ числом в чат.")
        return
    task9_policy = ANSWER_POLICIES_BY_SNAPSHOT.get(
        (str(problem.get("answer_policy_id", "")), str(problem.get("answer_policy_version", "")))
    )
    if task9_policy is None:
        await message.answer("Политика ответа этой задачи недоступна; откройте новое задание.")
        return
    parsed = task9_policy.parse(message.text)
    if parsed is None:
        await message.answer("Введите один числовой корень, например −3 или 2,5.")
        return
    correct = task9_policy.accepts(message.text, str(problem.get("correct_answer", "")))
    outcome = await repository.task9_attempt(
        user_id,
        problem_id,
        message.text,
        correct,
        message.message_id if type(message.message_id) is int else None,
        prompt_id,
    )
    if outcome is None or outcome.get("status") == "stale":
        await message.answer("Ответ к уже сменившемуся заданию проигнорирован.")
    elif outcome.get("status") == "duplicate":
        await message.answer("Это сообщение уже было обработано.")
    elif outcome.get("status") == "solved":
        sent = await message.answer(
            "✅ Верно!\nОтвет засчитан.",
            reply_markup=task9_menu(problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            await repository.set_task9_prompt_message(user_id, problem_id, result_id)
    elif outcome.get("status") == "active":
        sent = await message.answer(
            "Пока неверно. Попробуйте ещё раз.", reply_markup=task9_menu(problem_id)
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            await repository.set_task9_prompt_message(user_id, problem_id, result_id)
    elif outcome.get("status") == "failed":
        snapshot = cast(dict[str, object], outcome["problem"])
        solution = snapshot.get("solution", [])
        rendered_steps = (
            "\n".join(str(step) for step in solution) if isinstance(solution, list) else ""
        )
        sent = await message.answer(
            f"Вторая попытка неверна. Правильный ответ: {snapshot['correct_answer']}.\n\n"
            f"Разбор:\n{rendered_steps}",
            reply_markup=task9_menu(problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            await repository.set_task9_prompt_message(user_id, problem_id, result_id)
    else:
        await message.answer("Ответ уже обработан. Нажмите «➡ Следующее».")


async def menu_section(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    has_session = False
    if user_id is not None:
        await repository.save_user_state(user_id, "main_menu")
        has_session = await _has_resumable_session(repository, user_id)
    await message.answer(
        "Этот раздел пока не включён: сначала для него требуется отдельная проверка качества.",
        reply_markup=main_menu(has_session=has_session),
    )


async def return_to_menu(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    has_session = False
    if user_id is not None:
        await repository.save_user_state(user_id, "main_menu")
        has_session = await _has_resumable_session(repository, user_id)
    await message.answer("Главное меню.", reply_markup=main_menu(has_session=has_session))


async def show_progress(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    await repository.save_user_state(user_id, "progress")
    progress = await repository.task6_progress(user_id)
    issued = progress["issued"]
    answered = progress["answered"]
    correct = progress["correct"]
    accuracy = (correct * 100 + answered // 2) // answered if answered else 0
    state = await repository.task6_state(user_id)
    progress9 = await repository.task9_progress(user_id)
    state9 = await repository.task9_state(user_id)
    has_session = _has_resumable_task6(state) or _has_resumable_task9(state9)
    accuracy9 = (
        (progress9["correct"] * 100 + progress9["answered"] // 2) // progress9["answered"]
        if progress9["answered"]
        else 0
    )
    await message.answer(
        "📊 Прогресс\n\n"
        f"№6 · выдано {issued} · отвечал {answered} · решил {correct} · "
        f"пропустил {progress['skipped']} · правильно {accuracy}%\n"
        f"№9 · выдано {progress9['issued']} · отвечал {progress9['answered']} · "
        f"решил {progress9['correct']} · пропустил {progress9['skipped']} · "
        f"правильно {accuracy9}%\n\n"
        "Процент считается среди задач, на которые вы отвечали.",
        reply_markup=progress_menu(has_session=has_session),
    )


async def show_progress_details(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    progress6 = await repository.task6_progress(user_id)
    progress9 = await repository.task9_progress(user_id)
    state6 = await repository.task6_state(user_id)
    state9 = await repository.task9_state(user_id)
    has_session = _has_resumable_task6(state6) or _has_resumable_task9(state9)

    def detail(number: str, values: dict[str, int]) -> str:
        return (
            f"№{number}: правильно с первой попытки — {values.get('solved_first_try', 0)}, "
            f"со второй — {values.get('solved_second_try', 0)}; "
            f"неверных попыток — {max(values['attempts'] - values['correct'], 0)}; "
            f"подсказок — {values['hints_used']}; "
            f"разборов просмотрено — {values['solutions_viewed']}."
        )

    await message.answer(
        "📊 Подробнее\n\n"
        f"{detail('6', progress6)}\n\n{detail('9', progress9)}\n\n"
        "Неверный ответ, пропуск и просмотр разбора учитываются отдельно.",
        reply_markup=progress_menu(has_session=has_session),
    )


async def unknown_message(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    screen = await repository.user_state(user_id) if user_id is not None else None
    state = await repository.task6_state(user_id) if user_id is not None else None
    if screen == "task6" and state is not None and isinstance(state.get("problem"), dict):
        session_state = cast(dict[str, object], state.get("state", {}))
        if session_state.get("status") == "active":
            await task6_answer(message, repository)
            return
    state9 = await repository.task9_state(user_id) if user_id is not None else None
    if screen == "task9" and state9 is not None and isinstance(state9.get("problem"), dict):
        session_state9 = cast(dict[str, object], state9.get("state", {}))
        if session_state9.get("status") == "active":
            await task9_answer(message, repository)
            return
    has_session = _has_resumable_task6(state)
    has_session = has_session or _has_resumable_task9(state9)
    if user_id is not None:
        await repository.save_user_state(user_id, "main_menu")
    await message.answer(
        "Используйте кнопки меню или команду /start.",
        reply_markup=main_menu(has_session=has_session),
    )


def build_router() -> Router:
    router = Router()
    router.message.register(start, CommandStart())
    router.message.register(cancel, Command("cancel"))
    router.message.register(continue_session, F.text == "▶ Продолжить")
    router.message.register(choose_number, F.text == "🧮 По номеру")
    router.message.register(choose_task6, F.text == TASK6_LABEL)
    router.message.register(choose_task9, F.text == TASK9_LABEL)
    # Transitions are inline callbacks bound to a specific problem ID. Text commands
    # have no reliable association with the task shown when the user tapped them.
    router.message.register(task6_hint, F.text == "💡 Подсказка")
    router.message.register(task6_solution, F.text == "📘 Разбор")
    router.message.register(return_to_menu, F.text == "↩ В меню")
    router.message.register(show_progress, F.text == "📊 Прогресс")
    router.message.register(show_progress_details, F.text == "📊 Подробнее")
    router.message.register(menu_section, F.text.in_(MAIN_MENU))
    router.message.register(unknown_message)
    router.callback_query.register(task6_callback, F.data.startswith("t6:"))
    router.callback_query.register(task9_callback, F.data.startswith("t9:"))
    return router
