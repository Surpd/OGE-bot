import base64
import logging
import secrets
from typing import cast

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.menu import (
    MAIN_MENU,
    main_menu,
    number_menu,
    task6_menu,
    task7_menu,
    task9_menu,
    task11_menu,
    task13_menu,
)
from app.bot.navigation import navigation_callback
from app.bot.presentation import hint_message, send_photo, send_text
from app.bot.training_engine import (
    NUMERIC_TRAININGS,
    send_problem,
    training_answer,
    training_callback,
)
from app.bot.training_ux import matches_current_condition
from app.bot.trainings import TRAININGS
from app.math.equations import ANSWER_POLICIES_BY_SNAPSHOT
from app.math.inequalities import ENABLED_FAMILIES as TASK13_ENABLED_FAMILIES
from app.math.inequalities import POLICY as TASK13_ANSWER_POLICY
from app.math.inequalities import render_option_sheet_snapshot_png
from app.math.inequalities import validate_snapshot as validate_task13_snapshot
from app.math.numbers import POLICY as TASK7_ANSWER_POLICY
from app.math.oge07_scheduler import ENABLED_FAMILIES as TASK7_ENABLED_FAMILIES
from app.math.oge07_scheduler import build_task7_candidate_batch
from app.math.oge07_validation import validate_task7_snapshot
from app.math.oge9_scheduler import build_task9_candidate_batch
from app.math.oge11 import ENABLED_FAMILIES as TASK11_ENABLED_FAMILIES
from app.math.oge11 import POLICY_ID as TASK11_POLICY_ID
from app.math.oge11 import POLICY_VERSION as TASK11_POLICY_VERSION
from app.math.oge11 import from_snapshot as task11_from_snapshot
from app.math.oge11 import parse_answer as parse_task11_answer
from app.math.oge11_scheduler import build_task11_candidate_batch
from app.math.oge13_scheduler import build_task13_candidate_batch
from app.math.registry import ANSWER_POLICY_BY_SNAPSHOT
from app.math.scheduler import build_candidate_batch
from app.persistence.repository import Repository

logger = logging.getLogger(__name__)
TASK6_LABEL = "№6 · Вычисления"
TASK7_LABEL = "№7 · Числа и координатная прямая"
TASK9_LABEL = "№9 · Уравнения"
TASK10_LABEL = "№10 · Вероятность"
TASK12_LABEL = "№12 · Формулы"
TASK14_LABEL = "№14 · Прогрессии"
TASK8_LABEL = "№8 · Степени и корни"
TASK13_LABEL = "№13 · Неравенства"
TASK11_LABEL = "№11 · Графики функций"


def _user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user is not None else None


async def _disable_stale_keyboard(message: Message, saved: bool) -> None:
    if not saved:
        await message.edit_reply_markup(reply_markup=None)


def _solution_display_status(revealed: dict[str, object] | None) -> str:
    status = revealed.get("status") if revealed is not None else None
    return "solution_viewed" if status == "active" else str(status or "")


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
    for training in TRAININGS:
        state = await getattr(repository, f"task{training.number}_state")(user_id)
        if _has_resumable_task6(state):
            return True
    return False


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
            await send_text(
                message,
                repository,
                "Последнее задание уже завершено. Нажмите «➡ Следующее», чтобы продолжить.",
                reply_markup=task6_menu(str(current_problem["problem_id"])),
            )
            return False
        else:
            await send_text(
                message, repository, "У вас нет незавершённой тренировки.", reply_markup=main_menu()
            )
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
            await send_text(
                message,
                repository,
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
    sent = await send_text(
        message,
        repository,
        f"Задание №6 · вычисления\n\n{saved_problem['condition']}\n\n"
        "Напишите ответ числом в чат. Дробную часть можно отделять запятой или точкой.",
        reply_markup=task6_menu(str(saved_problem["problem_id"])),
    )
    prompt_message_id = getattr(sent, "message_id", None)
    if type(prompt_message_id) is int:
        await repository.set_task6_condition_message(
            user_id, str(saved_problem["problem_id"]), prompt_message_id
        )
    return True


async def start(message: Message, repository: Repository) -> None:
    from aiogram.types import ReplyKeyboardRemove

    if message.from_user is None:
        return
    await repository.register_user(message.from_user.id)
    await repository.save_user_state(message.from_user.id, "main_menu")
    has_session = await _has_resumable_session(repository, message.from_user.id)
    logger.info("user_started")
    await send_text(
        message,
        repository,
        "Привет! Это OGE Trainer — тренажёр первой части ОГЭ по математике.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await send_text(
        message, repository, "Выберите раздел в меню.",
        reply_markup=main_menu(has_session=has_session),
    )


async def cancel(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    has_session = False
    if user_id is not None:
        await repository.save_user_state(user_id, "main_menu")
        has_session = await _has_resumable_session(repository, user_id)
    await send_text(
        message,
        repository,
        "Текущий раздел закрыт.",
        reply_markup=main_menu(has_session=has_session),
    )


async def continue_session(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    last = await repository.last_training_mode(user_id)
    ordered = sorted(TRAININGS, key=lambda item: item.mode != last)
    for training in ordered:
        state = await getattr(repository, f"task{training.number}_state")(user_id)
        if training.available and _has_resumable_task6(state):
            sender = (
                _send_problem
                if training.number == 6
                else globals()[f"_send_task{training.number}_problem"]
            )
            await sender(message, repository, action="resume")
            return
    await repository.save_user_state(user_id, "main_menu")
    await send_text(
        message, repository, "Нет незавершённых заданий. Выберите номер.", reply_markup=main_menu()
    )


async def choose_number(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is not None:
        await repository.save_user_state(user_id, "number_selection")
    await send_text(
        message,
        repository,
        "Выберите номер задания:",
        reply_markup=number_menu(
            include_task7=bool(TASK7_ENABLED_FAMILIES),
            include_task13=bool(TASK13_ENABLED_FAMILIES),
            include_task11=bool(TASK11_ENABLED_FAMILIES),
        ),
    )


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
            await send_text(
                message, repository, "Нет незавершённой тренировки №9.", reply_markup=main_menu()
            )
            return False
        saved_problem = current_problem
        await repository.save_user_state(user_id, "task9")
    else:
        if action == "start" and isinstance(current_problem, dict):
            if state_value.get("status") == "active":
                saved_problem = current_problem
                await repository.save_user_state(user_id, "task9")
                sent = await send_text(
                    message,
                    repository,
                    f"Задание №9 · уравнения\n\n{saved_problem['condition']}\n\n"
                    "Напишите ответ числом в чат. Дробную часть можно отделять запятой или точкой.",
                    reply_markup=task9_menu(str(saved_problem["problem_id"])),
                )
                prompt_id = getattr(sent, "message_id", None)
                if type(prompt_id) is int:
                    await repository.set_task9_condition_message(
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
            await send_text(
                message, repository, "Не удалось подготовить задачу №9. Попробуйте ещё раз."
            )
            return False
        if action == "advance" and saved_problem.get("_transitioned") is False:
            return False
        if expected_screen is None:
            await repository.save_user_state(user_id, "task9")
    sent = await send_text(
        message,
        repository,
        f"Задание №9 · уравнения\n\n{saved_problem['condition']}\n\n"
        "Напишите ответ числом в чат. Дробную часть можно отделять запятой или точкой.",
        reply_markup=task9_menu(str(saved_problem["problem_id"])),
    )
    prompt_id = getattr(sent, "message_id", None)
    if type(prompt_id) is int:
        await repository.set_task9_condition_message(
            user_id, str(saved_problem["problem_id"]), prompt_id
        )
    return True


async def choose_task9(message: Message, repository: Repository) -> None:
    await _send_task9_problem(message, repository, action="start")


async def _send_task10_problem(
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
    return await send_problem(
        NUMERIC_TRAININGS[10],
        message,
        repository,
        action=action,
        expected_problem_id=expected_problem_id,
        expected_screen=expected_screen,
        expected_prompt_message_id=expected_prompt_message_id,
        user_id_override=user_id_override,
        skip_active=skip_active,
    )


async def choose_task10(message: Message, repository: Repository) -> None:
    await _send_task10_problem(message, repository, action="start")


async def task10_callback(callback: CallbackQuery, repository: Repository) -> None:
    await training_callback(NUMERIC_TRAININGS[10], callback, repository)


async def task10_answer(message: Message, repository: Repository) -> None:
    await training_answer(NUMERIC_TRAININGS[10], message, repository)


async def _send_task11_problem(
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
    if not TASK11_ENABLED_FAMILIES:
        await send_text(
            message, repository, "Семейства задания №11 проходят проверку и пока выключены."
        )
        return False
    await repository.ensure_task11_session(user_id)
    state = await repository.task11_state(user_id)
    state_value = cast(dict[str, object], state.get("state", {})) if state else {}
    current = state.get("problem") if state else None
    if action == "resume":
        if not isinstance(current, dict) or state_value.get("status") != "active":
            await send_text(
                message, repository, "Нет незавершённой тренировки №11.", reply_markup=main_menu()
            )
            return False
        problem = current
        await repository.save_user_state(user_id, "task11")
    elif action == "start" and isinstance(current, dict) and state_value.get("status") == "active":
        problem = current
        await repository.save_user_state(user_id, "task11")
    else:
        if action == "start" and isinstance(current, dict):
            expected_problem_id = str(current.get("problem_id", ""))
            action = "advance"
        if action == "advance" and expected_problem_id is None and isinstance(current, dict):
            expected_problem_id = str(current.get("problem_id", ""))
        candidates = build_task11_candidate_batch(
            state_value, secrets.randbelow(2**63), enabled_families=TASK11_ENABLED_FAMILIES
        )
        if not candidates:
            await send_text(
                message,
                repository,
                "Для №11 пока нет проверенных семейств.",
                reply_markup=main_menu(),
            )
            return False
        try:
            problem = await repository.advance_task11_problem(
                user_id,
                expected_problem_id,
                candidates,
                expected_screen,
                expected_prompt_message_id,
                skip_active,
            )
        except RuntimeError:
            await send_text(
                message, repository, "Не удалось подготовить задание №11. Попробуйте ещё раз."
            )
            return False
        if action == "advance" and problem.get("_transitioned") is False:
            return False
        if expected_screen is None:
            await repository.save_user_state(user_id, "task11")
    try:
        restored = task11_from_snapshot(problem)
    except ValueError:
        await send_text(
            message, repository, "Сохранённое задание №11 повреждено; ответ не обработан."
        )
        return False
    caption = (
        "Задание №11 · графики функций\n"
        f"{restored.condition}\n\n"
        "Введите три цифры в порядке А, Б, В. Используйте 1, 2 и 3 по одному разу."
    )
    sent = await send_photo(
        message,
        repository,
        BufferedInputFile(restored.png_bytes, filename="oge11.png"),
        caption=caption,
        reply_markup=task11_menu(restored.problem_id),
    )
    condition_id = getattr(sent, "message_id", None)
    if type(condition_id) is int:
        await repository.set_task11_condition_message(user_id, restored.problem_id, condition_id)
    return True


async def choose_task11(message: Message, repository: Repository) -> None:
    await _send_task11_problem(message, repository, action="start")


async def task11_callback(callback: CallbackQuery, repository: Repository) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "t11" or callback.message is None:
        await callback.answer()
        return
    _, action, expected_id = parts
    user_id = callback.from_user.id
    message = cast(Message, callback.message)
    condition_id = getattr(message, "message_id", None)
    if type(condition_id) is not int:
        await callback.answer("Кнопка больше не связана с заданием.")
        return
    if action == "menu":
        changed = await repository.transition_task_screen(
            user_id, "task11", expected_id, "main_menu", condition_id
        )
        if not changed:
            await callback.answer("Тренировка приостановлена или задание уже сменилось.")
            return
        await send_text(
            message,
            repository,
            "Главное меню.",
            user_id_override=user_id,
            reply_markup=main_menu(has_session=await _has_resumable_session(repository, user_id)),
        )
        await callback.answer()
        return
    if await repository.user_state(user_id) != "task11":
        await callback.answer("Тренировка приостановлена. Нажмите «Продолжить».")
        return
    state = await repository.task11_state(user_id)
    problem = state.get("problem") if state else None
    if not isinstance(problem, dict) or str(problem.get("problem_id")) != expected_id:
        await callback.answer("Это задание уже сменилось.")
        return
    if action in {"next", "skip"}:
        advanced = await _send_task11_problem(
            message,
            repository,
            action="advance",
            expected_problem_id=expected_id,
            expected_screen="task11",
            expected_prompt_message_id=condition_id,
            user_id_override=user_id,
            skip_active=action == "skip",
        )
        await callback.answer(None if advanced else "Это задание уже сменилось.")
        return
    if action == "hint":
        hint = await repository.task11_hint(user_id, expected_id, condition_id)
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет."
        )
    elif action == "solution":
        revealed = await repository.task11_reveal_solution(user_id, expected_id, condition_id)
        snapshot = revealed.get("problem") if revealed else None
        if not isinstance(snapshot, dict):
            await callback.answer("Это задание уже сменилось.")
            return
        try:
            restored = task11_from_snapshot(snapshot)
        except ValueError:
            await callback.answer("Сохранённое условие повреждено.", show_alert=True)
            return
        sent = await send_text(
            message,
            repository,
            "Разбор (самостоятельное решение не засчитывается):\n"
            + "\n".join(restored.solution)
            + f"\n\nОтвет: {restored.correct_answer}",
            reply_markup=task11_menu(expected_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task11_prompt_message(
                user_id, expected_id, result_id, expected_status=_solution_display_status(revealed)
            )
            await _disable_stale_keyboard(sent, saved)
    else:
        await callback.answer()
        return
    await callback.answer()


async def task11_answer(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None or message.text is None:
        return
    state = await repository.task11_state(user_id)
    problem = state.get("problem") if state else None
    session_state = state.get("state", {}) if state else {}
    if (
        not isinstance(problem, dict)
        or not isinstance(session_state, dict)
        or session_state.get("status") != "active"
    ):
        await send_text(message, repository, "Сначала откройте активную тренировку №11.")
        return
    condition_id = session_state.get(
        "problem_prompt_message_id", session_state.get("input_prompt_message_id")
    )
    if not matches_current_condition(message, cast(dict[str, object], session_state)):
        await send_text(
            message,
            repository,
            "Ответ к предыдущему заданию не принят. Введите код к активному условию.",
        )
        return
    if (
        problem.get("answer_policy_id") != TASK11_POLICY_ID
        or problem.get("answer_policy_version") != TASK11_POLICY_VERSION
    ):
        await send_text(message, repository, "Политика ответа этой задачи недоступна.")
        return
    answer = parse_task11_answer(message.text)
    if answer is None:
        await send_text(
            message, repository, "Введите ровно три цифры: каждую из 1, 2 и 3 по одному разу."
        )
        return
    problem_id = str(problem.get("problem_id", ""))
    outcome = await repository.task11_attempt(
        user_id,
        problem_id,
        answer,
        answer == str(problem.get("correct_answer", "")),
        message.message_id if type(message.message_id) is int else None,
        condition_id if type(condition_id) is int else None,
    )
    if outcome is None or outcome.get("status") in {"stale", "duplicate"}:
        await send_text(message, repository, "Ответ к уже сменившемуся заданию проигнорирован.")
        return
    status = outcome.get("status")
    if status == "solved":
        text = "✅ Верно! Ответ засчитан."
    elif status == "active":
        text = "Пока неверно. Попробуйте ещё раз."
    elif status == "failed":
        snapshot = cast(dict[str, object], outcome["problem"])
        text = (
            f"Вторая попытка неверна. Ответ: {snapshot['correct_answer']}\n\nРазбор:\n"
            + "\n".join(map(str, cast(list[object], snapshot.get("solution", []))))
        )
    else:
        await send_text(message, repository, "Ответ уже обработан. Нажмите «Следующее».")
        return
    sent = await send_text(
        message,
        repository,
        text,
        reply_markup=task11_menu(problem_id, completed=status != "active"),
    )
    result_id = getattr(sent, "message_id", None)
    if type(result_id) is int:
        saved = await repository.set_task11_prompt_message(
            user_id, problem_id, result_id, expected_status=str(status)
        )
        await _disable_stale_keyboard(sent, saved)


async def _send_task12_problem(
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
    return await send_problem(
        NUMERIC_TRAININGS[12],
        message,
        repository,
        action=action,
        expected_problem_id=expected_problem_id,
        expected_screen=expected_screen,
        expected_prompt_message_id=expected_prompt_message_id,
        user_id_override=user_id_override,
        skip_active=skip_active,
    )


async def choose_task12(message: Message, repository: Repository) -> None:
    await _send_task12_problem(message, repository, action="start")


async def task12_callback(callback: CallbackQuery, repository: Repository) -> None:
    await training_callback(NUMERIC_TRAININGS[12], callback, repository)


async def task12_answer(message: Message, repository: Repository) -> None:
    await training_answer(NUMERIC_TRAININGS[12], message, repository)


async def _send_task14_problem(
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
    return await send_problem(
        NUMERIC_TRAININGS[14],
        message,
        repository,
        action=action,
        expected_problem_id=expected_problem_id,
        expected_screen=expected_screen,
        expected_prompt_message_id=expected_prompt_message_id,
        user_id_override=user_id_override,
        skip_active=skip_active,
    )


async def choose_task14(message: Message, repository: Repository) -> None:
    await _send_task14_problem(message, repository, action="start")


async def task14_callback(callback: CallbackQuery, repository: Repository) -> None:
    await training_callback(NUMERIC_TRAININGS[14], callback, repository)


async def task14_answer(message: Message, repository: Repository) -> None:
    await training_answer(NUMERIC_TRAININGS[14], message, repository)


async def _send_task8_problem(
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
    return await send_problem(
        NUMERIC_TRAININGS[8],
        message,
        repository,
        action=action,
        expected_problem_id=expected_problem_id,
        expected_screen=expected_screen,
        expected_prompt_message_id=expected_prompt_message_id,
        user_id_override=user_id_override,
        skip_active=skip_active,
    )


async def choose_task8(message: Message, repository: Repository) -> None:
    await _send_task8_problem(message, repository, action="start")


async def task8_callback(callback: CallbackQuery, repository: Repository) -> None:
    await training_callback(NUMERIC_TRAININGS[8], callback, repository)


async def task8_answer(message: Message, repository: Repository) -> None:
    await training_answer(NUMERIC_TRAININGS[8], message, repository)


async def _send_task7_problem(
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
    await repository.ensure_task7_session(user_id)
    state = await repository.task7_state(user_id)
    state_value = cast(dict[str, object], state.get("state", {})) if state else {}
    current = state.get("problem") if state else None
    if state is not None and (
        (current is not None and not isinstance(current, dict))
        or (current is None and state_value.get("status") == "active")
    ):
        await repository.save_user_state(user_id, "main_menu")
        await send_text(
            message,
            repository,
            "Сохранённое задание №7 повреждено. Оно не отправлено и не заменено новым заданием.",
            reply_markup=main_menu(),
        )
        return False
    if isinstance(current, dict) and not validate_task7_snapshot(current):
        await repository.save_user_state(user_id, "main_menu")
        await send_text(
            message,
            repository,
            "Сохранённое задание №7 повреждено или использует неподдерживаемую версию. "
            "Оно не отправлено и не заменено новым заданием.",
            reply_markup=main_menu(),
        )
        return False
    if isinstance(current, dict) and current.get("family_id") not in TASK7_ENABLED_FAMILIES:
        await repository.save_user_state(user_id, "main_menu")
        await send_text(
            message,
            repository,
            "Сохранённое семейство №7 сейчас выключено. Задание не отправлено и не заменено новым.",
            reply_markup=main_menu(),
        )
        return False
    if action == "resume":
        if not isinstance(current, dict) or state_value.get("status") != "active":
            await send_text(
                message, repository, "Нет незавершённой тренировки №7.", reply_markup=main_menu()
            )
            return False
        problem = current
        await repository.save_user_state(user_id, "task7")
    else:
        if (
            action == "start"
            and isinstance(current, dict)
            and state_value.get("status") == "active"
        ):
            problem = current
            await repository.save_user_state(user_id, "task7")
        else:
            if action == "start" and isinstance(current, dict):
                expected_problem_id = str(current.get("problem_id", ""))
                action = "advance"
            if action == "advance" and expected_problem_id is None and isinstance(current, dict):
                expected_problem_id = str(current.get("problem_id", ""))
            candidates = build_task7_candidate_batch(state_value, secrets.randbelow(2**63))
            try:
                problem = await repository.advance_task7_problem(
                    user_id,
                    expected_problem_id,
                    candidates,
                    expected_screen,
                    expected_prompt_message_id,
                    skip_active,
                )
            except RuntimeError:
                await send_text(
                    message, repository, "Не удалось подготовить задание №7. Попробуйте ещё раз."
                )
                return False
            if action == "advance" and problem.get("_transitioned") is False:
                return False
            if expected_screen is None:
                await repository.save_user_state(user_id, "task7")
    if problem.get("family_id") not in TASK7_ENABLED_FAMILIES or not validate_task7_snapshot(
        problem
    ):
        await repository.save_user_state(user_id, "main_menu")
        await send_text(
            message,
            repository,
            "Сохранённое задание №7 повреждено или использует неподдерживаемую версию. "
            "Оно не отправлено и не заменено новым заданием.",
            reply_markup=main_menu(),
        )
        return False
    options = problem.get("options", [])
    option_lines = (
        "\n".join(f"{i}. {v}" for i, v in enumerate(options, 1))
        if isinstance(options, list)
        else ""
    )
    caption = (
        "Задание №7 · числа и координатная прямая\n"
        f"{problem['condition']}\n\n{option_lines}\n\nВведите номер варианта 1–4."
    )
    encoded = problem.get("graph_png_base64")
    if isinstance(encoded, str):
        try:
            photo = BufferedInputFile(
                base64.b64decode(encoded, validate=True), filename="oge07.png"
            )
        except ValueError:
            await send_text(message, repository, "Сохранённое изображение задания повреждено.")
            return False
        sent = await send_photo(
            message,
            repository,
            photo,
            caption=caption,
            reply_markup=task7_menu(str(problem["problem_id"])),
        )
    else:
        sent = await send_text(
            message, repository, caption, reply_markup=task7_menu(str(problem["problem_id"]))
        )
    prompt_id = getattr(sent, "message_id", None)
    if type(prompt_id) is int:
        await repository.set_task7_condition_message(user_id, str(problem["problem_id"]), prompt_id)
    return True


async def choose_task7(message: Message, repository: Repository) -> None:
    if not TASK7_ENABLED_FAMILIES:
        await send_text(
            message, repository, "Семейства задания №7 проходят приёмку и пока выключены."
        )
        return
    await _send_task7_problem(message, repository, action="start")


async def task7_callback(callback: CallbackQuery, repository: Repository) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "t7" or callback.message is None:
        await callback.answer()
        return
    _, action, expected_id = parts
    user_id = callback.from_user.id
    message = cast(Message, callback.message)
    prompt_id = getattr(message, "message_id", None)
    if type(prompt_id) is not int:
        await callback.answer("Кнопка больше не связана с заданием.")
        return
    if action == "menu":
        changed = await repository.transition_task_screen(
            user_id, "task7", expected_id, "main_menu", prompt_id
        )
        if not changed:
            await callback.answer("Тренировка приостановлена или задание уже сменилось.")
            return
        await send_text(
            message,
            repository,
            "Главное меню.",
            user_id_override=user_id,
            reply_markup=main_menu(has_session=await _has_resumable_session(repository, user_id)),
        )
        await callback.answer()
        return
    if await repository.user_state(user_id) != "task7":
        await callback.answer("Тренировка приостановлена. Нажмите «Продолжить».")
        return
    state = await repository.task7_state(user_id)
    problem = state.get("problem") if state else None
    if not isinstance(problem, dict) or str(problem.get("problem_id")) != expected_id:
        await callback.answer("Это задание уже сменилось.")
        return
    if problem.get("family_id") not in TASK7_ENABLED_FAMILIES:
        await repository.save_user_state(user_id, "main_menu")
        await callback.answer("Это семейство задания №7 выключено.", show_alert=True)
        return
    if not validate_task7_snapshot(problem):
        await repository.save_user_state(user_id, "main_menu")
        await callback.answer(
            "Сохранённое задание повреждено; оно не было обработано.", show_alert=True
        )
        return
    if action in {"next", "skip"}:
        advanced = await _send_task7_problem(
            message,
            repository,
            action="advance",
            expected_problem_id=expected_id,
            expected_screen="task7",
            expected_prompt_message_id=prompt_id,
            user_id_override=user_id,
            skip_active=action == "skip",
        )
        await callback.answer(None if advanced else "Это задание уже сменилось.")
        return
    if action == "hint":
        hint = await repository.task7_hint(user_id, expected_id, prompt_id)
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет."
        )
    elif action == "solution":
        revealed = await repository.task7_reveal_solution(user_id, expected_id, prompt_id)
        snapshot = revealed.get("problem") if revealed else None
        if not isinstance(snapshot, dict):
            await callback.answer("Это задание уже сменилось.")
            return
        steps = snapshot.get("solution", [])
        sent = await send_text(
            message,
            repository,
            "Разбор (самостоятельное решение не засчитывается):\n"
            + "\n".join(str(step) for step in steps)
            + f"\n\nОтвет: {snapshot['correct_answer']}",
            reply_markup=task7_menu(expected_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task7_prompt_message(
                user_id,
                expected_id,
                result_id,
                expected_status=_solution_display_status(revealed),
            )
            await _disable_stale_keyboard(sent, saved)
    else:
        await callback.answer()
        return
    await callback.answer()


async def task7_answer(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None or message.text is None:
        return
    state = await repository.task7_state(user_id)
    problem = state.get("problem") if state else None
    session_state = state.get("state", {}) if state else {}
    if (
        not isinstance(problem, dict)
        or not isinstance(session_state, dict)
        or session_state.get("status") != "active"
    ):
        await send_text(message, repository, "Сначала откройте активную тренировку №7.")
        return
    if problem.get("family_id") not in TASK7_ENABLED_FAMILIES:
        await repository.save_user_state(user_id, "main_menu")
        await send_text(
            message, repository, "Это семейство задания №7 выключено; ответ не обработан."
        )
        return
    if not validate_task7_snapshot(problem):
        await repository.save_user_state(user_id, "main_menu")
        await send_text(
            message,
            repository,
            "Сохранённое задание №7 повреждено; ответ не обработан и новое задание не создано.",
            reply_markup=main_menu(),
        )
        return
    prompt_id = session_state.get(
        "problem_prompt_message_id", session_state.get("input_prompt_message_id")
    )
    if not matches_current_condition(message, cast(dict[str, object], session_state)):
        await send_text(
            message,
            repository,
            "Ответ к предыдущему заданию не принят. Напишите ответ числом в чат.",
        )
        return
    if (
        problem.get("answer_policy_id") != TASK7_ANSWER_POLICY.policy_id
        or problem.get("answer_policy_version") != TASK7_ANSWER_POLICY.version
    ):
        await send_text(message, repository, "Политика ответа этой задачи недоступна.")
        return
    parsed = TASK7_ANSWER_POLICY.parse(message.text)
    if parsed is None or parsed.denominator != 1 or parsed.numerator not in range(1, 5):
        await send_text(message, repository, "Введите номер варианта от 1 до 4.")
        return
    problem_id = str(problem.get("problem_id", ""))
    correct = TASK7_ANSWER_POLICY.accepts(message.text, str(problem.get("correct_answer", "")))
    outcome = await repository.task7_attempt(
        user_id,
        problem_id,
        message.text,
        correct,
        message.message_id if type(message.message_id) is int else None,
        prompt_id,
    )
    if outcome is None or outcome.get("status") in {"stale", "duplicate"}:
        await send_text(message, repository, "Ответ к уже сменившемуся заданию проигнорирован.")
        return
    status = outcome.get("status")
    if status == "solved":
        text = "✅ Верно! Ответ засчитан."
    elif status == "active":
        text = "Пока неверно. Попробуйте ещё раз."
    elif status == "failed":
        snapshot = cast(dict[str, object], outcome["problem"])
        text = (
            f"Вторая попытка неверна. Ответ: {snapshot['correct_answer']}\n\nРазбор:\n"
            + "\n".join(map(str, cast(list[object], snapshot.get("solution", []))))
        )
    else:
        await send_text(message, repository, "Ответ уже обработан. Нажмите «Следующее».")
        return
    completed = status != "active"
    sent = await send_text(
        message, repository, text, reply_markup=task7_menu(problem_id, completed=completed)
    )
    result_id = getattr(sent, "message_id", None)
    if type(result_id) is int:
        saved = await repository.set_task7_prompt_message(
            user_id, problem_id, result_id, expected_status=str(status)
        )
        await _disable_stale_keyboard(sent, saved)


_TASK13_TEXT_FAMILIES = {"OGE13-L01", "OGE13-Q01", "OGE13-Q02", "OGE13-Q03"}


def _task13_choice_text(problem: dict[str, object]) -> str:
    choices = problem.get("option_texts", [])
    if str(problem.get("family_id", "")) not in _TASK13_TEXT_FAMILIES or not isinstance(
        choices, list
    ):
        return ""
    return "\n".join(f"{index}. {choice}" for index, choice in enumerate(choices, 1))


def _task13_is_graph_choice(problem: dict[str, object]) -> bool:
    return str(problem.get("family_id", "")) not in _TASK13_TEXT_FAMILIES


async def _send_task13_problem(
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
    await repository.ensure_task13_session(user_id)
    state = await repository.task13_state(user_id)
    state_value = cast(dict[str, object], state.get("state", {})) if state else {}
    current = state.get("problem") if state else None
    if action == "resume":
        if not isinstance(current, dict) or state_value.get("status") != "active":
            await send_text(
                message, repository, "Нет незавершённой тренировки №13.", reply_markup=main_menu()
            )
            return False
        problem = current
        await repository.save_user_state(user_id, "task13")
    else:
        if (
            action == "start"
            and isinstance(current, dict)
            and state_value.get("status") == "active"
        ):
            problem = current
            await repository.save_user_state(user_id, "task13")
        else:
            if action == "start" and isinstance(current, dict):
                expected_problem_id = str(current.get("problem_id", ""))
                action = "advance"
            if action == "advance" and expected_problem_id is None and isinstance(current, dict):
                expected_problem_id = str(current.get("problem_id", ""))
            candidates = build_task13_candidate_batch(state_value, secrets.randbelow(2**63))
            if not candidates:
                await send_text(
                    message,
                    repository,
                    "Семейства задания №13 проходят проверку и пока выключены.",
                    reply_markup=main_menu(),
                )
                return False
            try:
                problem = await repository.advance_task13_problem(
                    user_id,
                    expected_problem_id,
                    candidates,
                    expected_screen,
                    expected_prompt_message_id,
                    skip_active,
                )
            except RuntimeError:
                await send_text(
                    message, repository, "Не удалось подготовить задание №13. Попробуйте ещё раз."
                )
                return False
            if action == "advance" and problem.get("_transitioned") is False:
                return False
            if expected_screen is None:
                await repository.save_user_state(user_id, "task13")
    problem_id = str(problem["problem_id"])
    if not validate_task13_snapshot(problem):
        await repository.save_user_state(user_id, "main_menu")
        await send_text(
            message,
            repository,
            "Сохранённое задание №13 использует неподдерживаемую версию или повреждённые "
            "варианты. Оно не было заменено новым заданием.",
            reply_markup=main_menu(),
        )
        return False
    graph_choice = _task13_is_graph_choice(problem)
    caption = (
        "Задание №13 · неравенства\n"
        f"{problem['condition']}\n\n"
        + _task13_choice_text(problem)
        + ("\n" if _task13_choice_text(problem) else "")
        + "Выберите один из вариантов (1–4) кнопкой или напишите его номер в чат."
    )
    markup = task13_menu(problem_id, choices=True)
    system_rows = (
        tuple(str(problem["condition"]).splitlines())
        if str(problem.get("family_id", "")).startswith("OGE13-S")
        else None
    )
    if graph_choice:
        try:
            image = render_option_sheet_snapshot_png(problem)
        except ValueError:
            await repository.save_user_state(user_id, "main_menu")
            await send_text(
                message,
                repository,
                "Не удалось отобразить сохранённые варианты №13; задание не пересоздавалось.",
                reply_markup=main_menu(),
            )
            return False
        sent = await send_photo(
            message,
            repository,
            BufferedInputFile(image, filename="oge13-options.png"),
            caption=caption,
            reply_markup=markup,
            math_system_rows=system_rows,
        )
    else:
        sent = await send_text(
            message, repository, caption, reply_markup=markup, math_system_rows=system_rows
        )
    prompt_id = getattr(sent, "message_id", None)
    if type(prompt_id) is int:
        await repository.set_task13_condition_message(
            user_id, str(problem["problem_id"]), prompt_id
        )
    return True


async def choose_task13(message: Message, repository: Repository) -> None:
    await _send_task13_problem(message, repository, action="start")


async def task13_callback(callback: CallbackQuery, repository: Repository) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) not in {3, 4} or parts[0] != "t13" or callback.message is None:
        await callback.answer()
        return
    _, action, expected_id = parts[:3]
    user_id = callback.from_user.id
    message = cast(Message, callback.message)
    prompt_id = getattr(message, "message_id", None)
    if type(prompt_id) is not int:
        await callback.answer("Кнопка больше не связана с заданием.")
        return
    if action == "menu":
        changed = await repository.transition_task_screen(
            user_id, "task13", expected_id, "main_menu", prompt_id
        )
        if not changed:
            await callback.answer("Тренировка приостановлена или задание уже сменилось.")
            return
        await send_text(
            message,
            repository,
            "Главное меню.",
            user_id_override=user_id,
            reply_markup=main_menu(has_session=await _has_resumable_session(repository, user_id)),
        )
        await callback.answer()
        return
    if await repository.user_state(user_id) != "task13":
        await callback.answer("Тренировка приостановлена. Нажмите «Продолжить».")
        return
    state = await repository.task13_state(user_id)
    problem = state.get("problem") if state else None
    if not isinstance(problem, dict) or str(problem.get("problem_id")) != expected_id:
        await callback.answer("Это задание уже сменилось.")
        return
    if action == "choose":
        if len(parts) != 4 or parts[3] not in {"1", "2", "3", "4"}:
            await callback.answer("Выберите вариант от 1 до 4.")
            return
        state_value = state.get("state", {}) if state else {}
        condition_id = (
            state_value.get("problem_prompt_message_id") if isinstance(state_value, dict) else None
        )
        current_prompt = (
            state_value.get("input_prompt_message_id") if isinstance(state_value, dict) else None
        )
        if current_prompt != prompt_id or type(condition_id) is not int:
            await callback.answer("Эта кнопка уже устарела.")
            return
        await _task13_record_answer(
            message,
            repository,
            user_id,
            problem,
            parts[3],
            condition_id,
            prompt_id,
            telegram_event_id=str(callback.id),
        )
        await callback.answer()
        return
    if action in {"next", "skip"}:
        advanced = await _send_task13_problem(
            message,
            repository,
            action="advance",
            expected_problem_id=expected_id,
            expected_screen="task13",
            expected_prompt_message_id=prompt_id,
            user_id_override=user_id,
            skip_active=action == "skip",
        )
        await callback.answer(None if advanced else "Это задание уже сменилось.")
        return
    if action == "hint":
        hint = await repository.task13_hint(user_id, expected_id, prompt_id)
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет."
        )
    elif action == "solution":
        revealed = await repository.task13_reveal_solution(user_id, expected_id, prompt_id)
        snapshot = revealed.get("problem") if revealed else None
        if not isinstance(snapshot, dict):
            await callback.answer("Это задание уже сменилось.")
            return
        steps = snapshot.get("solution", [])
        sent = await send_text(
            message,
            repository,
            "Разбор (самостоятельное решение не засчитывается):\n"
            + "\n".join(str(step) for step in steps)
            + f"\n\nОтвет: вариант {snapshot['correct_answer']}",
            reply_markup=task13_menu(expected_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task13_prompt_message(
                user_id,
                expected_id,
                result_id,
                expected_status=_solution_display_status(revealed),
            )
            await _disable_stale_keyboard(sent, saved)
    else:
        await callback.answer()
        return
    await callback.answer()


async def _task13_record_answer(
    message: Message,
    repository: Repository,
    user_id: int,
    problem: dict[str, object],
    answer: str,
    condition_id: int | None,
    control_id: int | None,
    *,
    telegram_event_id: str | None = None,
) -> None:
    if (
        problem.get("answer_policy_id") != TASK13_ANSWER_POLICY.policy_id
        or problem.get("answer_policy_version") != TASK13_ANSWER_POLICY.version
    ):
        await send_text(message, repository, "Политика ответа этой задачи недоступна.")
        return
    if answer.strip() not in {"1", "2", "3", "4"}:
        await send_text(message, repository, "Введите номер варианта от 1 до 4.")
        return
    problem_id = str(problem.get("problem_id", ""))
    outcome = await repository.task13_attempt(
        user_id,
        problem_id,
        answer,
        answer.strip() == str(problem.get("correct_answer", "")),
        (
            message.message_id
            if telegram_event_id is None and type(message.message_id) is int
            else None
        ),
        condition_id,
        telegram_event_id,
    )
    if outcome is None or outcome.get("status") in {"stale", "duplicate"}:
        await send_text(message, repository, "Ответ к уже сменившемуся заданию проигнорирован.")
        return
    status = outcome.get("status")
    if status == "solved":
        text = "✅ Верно! Ответ засчитан."
    elif status == "active":
        text = "Пока неверно. Попробуйте ещё раз."
    elif status == "failed":
        snapshot = cast(dict[str, object], outcome["problem"])
        text = (
            f"Вторая попытка неверна. Правильный вариант: {snapshot['correct_answer']}\n\nРазбор:\n"
            + "\n".join(map(str, cast(list[object], snapshot.get("solution", []))))
        )
    else:
        await send_text(message, repository, "Ответ уже обработан. Нажмите «Следующее».")
        return
    completed = status != "active"
    sent = await send_text(
        message,
        repository,
        text,
        reply_markup=task13_menu(
            problem_id,
            completed=completed,
            choices=not completed,
        ),
    )
    result_id = getattr(sent, "message_id", None)
    if type(result_id) is int:
        saved = await repository.set_task13_prompt_message(
            user_id, problem_id, result_id, expected_status=str(status)
        )
        await _disable_stale_keyboard(sent, saved)


async def task13_answer(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None or message.text is None:
        return
    state = await repository.task13_state(user_id)
    problem = state.get("problem") if state else None
    session_state = state.get("state", {}) if state else {}
    if (
        not isinstance(problem, dict)
        or not isinstance(session_state, dict)
        or session_state.get("status") != "active"
    ):
        await send_text(message, repository, "Сначала откройте активную тренировку №13.")
        return
    prompt_id = session_state.get(
        "problem_prompt_message_id", session_state.get("input_prompt_message_id")
    )
    if not matches_current_condition(message, cast(dict[str, object], session_state)):
        await send_text(
            message,
            repository,
            "Ответ к предыдущему заданию не принят. Напишите номер варианта в чат.",
        )
        return
    if (
        problem.get("answer_policy_id") != TASK13_ANSWER_POLICY.policy_id
        or problem.get("answer_policy_version") != TASK13_ANSWER_POLICY.version
    ):
        await send_text(message, repository, "Политика ответа этой задачи недоступна.")
        return
    await _task13_record_answer(
        message,
        repository,
        user_id,
        problem,
        message.text,
        prompt_id if type(prompt_id) is int else None,
        (
            session_state.get("input_prompt_message_id")
            if type(session_state.get("input_prompt_message_id")) is int
            else None
        ),
    )


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
        await send_text(
            message,
            repository,
            "Главное меню.",
            user_id_override=user_id,
            reply_markup=main_menu(has_session=has_session),
        )
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
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет."
        )
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
        sent = await send_text(
            message,
            repository,
            "Разбор (самостоятельное решение не засчитывается):\n"
            f"{steps}\n\nОтвет: {saved_problem['correct_answer']}",
            reply_markup=task6_menu(expected_problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task6_prompt_message(
                user_id,
                expected_problem_id,
                result_id,
                expected_status=_solution_display_status(revealed),
            )
            await _disable_stale_keyboard(sent, saved)
    else:
        await callback.answer()
        return
    await callback.answer()


async def task6_hint(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None or await repository.user_state(user_id) != "task6":
        await send_text(message, repository, "Сначала откройте активную тренировку №6.")
        return
    state = await repository.task6_state(user_id) if user_id is not None else None
    problem = state.get("problem") if state else None
    problem_id = str(problem.get("problem_id", "")) if isinstance(problem, dict) else ""
    hint = (
        await repository.task6_hint(user_id, problem_id)
        if user_id is not None and problem_id
        else None
    )
    await send_text(
        message,
        repository,
        hint_message(hint, problem) if hint else "Сначала откройте активное задание.",
    )


async def task6_solution(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None or await repository.user_state(user_id) != "task6":
        await send_text(message, repository, "Сначала откройте активную тренировку №6.")
        return
    state = await repository.task6_state(user_id) if user_id is not None else None
    problem = state.get("problem") if state is not None else None
    if not isinstance(problem, dict):
        await send_text(message, repository, "Сначала откройте активное задание.")
        return
    problem_id = str(problem.get("problem_id", ""))
    revealed = (
        await repository.task6_reveal_solution(user_id, problem_id) if user_id is not None else None
    )
    saved_problem = revealed.get("problem") if revealed is not None else None
    if not isinstance(saved_problem, dict):
        await send_text(
            message, repository, "Это задание уже сменилось. Откройте разбор для текущего задания."
        )
        return
    solution = saved_problem.get("solution", [])
    answer = str(saved_problem.get("correct_answer", ""))
    text = "\n".join(str(step) for step in solution) if isinstance(solution, list) else ""
    sent = await send_text(
        message,
        repository,
        f"Разбор (самостоятельное решение не засчитывается):\n{text}\n\nОтвет: {answer}",
        reply_markup=task6_menu(problem_id, completed=True),
    )
    result_id = getattr(sent, "message_id", None)
    if type(result_id) is int and user_id is not None:
        saved = await repository.set_task6_prompt_message(
            user_id,
            problem_id,
            result_id,
            expected_status=_solution_display_status(revealed),
        )
        await _disable_stale_keyboard(sent, saved)


async def task6_answer(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None or message.text is None:
        return
    state = await repository.task6_state(user_id)
    problem = state.get("problem") if state is not None else None
    session_state = state.get("state", {}) if state is not None else {}
    if not isinstance(problem, dict) or not isinstance(session_state, dict):
        await send_text(
            message, repository, "Сначала выберите «По номеру → №6».", reply_markup=main_menu()
        )
        return
    if session_state.get("status") != "active":
        await send_text(message, repository, "Это задание уже завершено. Нажмите «➡ Следующее».")
        return
    prompt_message_id = session_state.get(
        "problem_prompt_message_id", session_state.get("input_prompt_message_id")
    )
    if not matches_current_condition(message, cast(dict[str, object], session_state)):
        await send_text(
            message,
            repository,
            "Ответ к предыдущему заданию не принят. Напишите ответ числом в чат.",
        )
        return
    family_id = str(problem.get("family_id", ""))
    policy_id = str(problem.get("answer_policy_id", ""))
    policy_version = str(problem.get("answer_policy_version", ""))
    policy = ANSWER_POLICY_BY_SNAPSHOT.get((family_id, policy_id, policy_version))
    if policy is None:
        await send_text(message, repository, "Это задание временно недоступно. Вернитесь в меню.")
        return
    expected_problem_id = str(problem.get("problem_id", ""))
    expected = str(problem.get("correct_answer", ""))
    parsed = policy.parse(message.text)
    if parsed is None:
        await send_text(message, repository, "Введите числовой ответ. Например: 2,5 или −3.")
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
        await send_text(message, repository, "Активное задание не найдено. Выберите №6 в меню.")
    elif outcome["status"] == "stale":
        await send_text(message, repository, "Ответ к уже сменившемуся заданию проигнорирован.")
    elif outcome["status"] == "duplicate":
        await send_text(message, repository, "Это сообщение уже было обработано.")
    elif outcome["status"] == "solved":
        sent = await send_text(
            message,
            repository,
            "✅ Верно!\nОтвет засчитан.",
            reply_markup=task6_menu(expected_problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task6_prompt_message(
                user_id, expected_problem_id, result_id, expected_status="solved"
            )
            await _disable_stale_keyboard(sent, saved)
    elif outcome["status"] == "active":
        sent = await send_text(
            message,
            repository,
            "Пока неверно. Попробуйте ещё раз.",
            reply_markup=task6_menu(expected_problem_id),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task6_prompt_message(
                user_id, expected_problem_id, result_id, expected_status="active"
            )
            await _disable_stale_keyboard(sent, saved)
    elif outcome["status"] == "failed":
        saved_problem = cast(dict[str, object], outcome["problem"])
        solution = saved_problem.get("solution", [])
        steps = "\n".join(str(step) for step in solution) if isinstance(solution, list) else ""
        sent = await send_text(
            message,
            repository,
            f"Вторая попытка неверна. Правильный ответ: {saved_problem['correct_answer']}.\n\n"
            f"Разбор:\n{steps}",
            reply_markup=task6_menu(expected_problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task6_prompt_message(
                user_id, expected_problem_id, result_id, expected_status="failed"
            )
            await _disable_stale_keyboard(sent, saved)
    else:
        await send_text(
            message, repository, "Ответ по этому заданию уже обработан. Нажмите «➡ Следующее»."
        )


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
        await send_text(
            message,
            repository,
            "Главное меню.",
            user_id_override=user_id,
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
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет."
        )
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
        sent = await send_text(
            message,
            repository,
            "Разбор (самостоятельное решение не засчитывается):\n"
            f"{rendered_steps}\n\nОтвет: {snapshot['correct_answer']}",
            reply_markup=task9_menu(expected_problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task9_prompt_message(
                user_id,
                expected_problem_id,
                result_id,
                expected_status=_solution_display_status(revealed),
            )
            await _disable_stale_keyboard(sent, saved)
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
        await send_text(
            message, repository, "Сначала выберите «По номеру → №9».", reply_markup=main_menu()
        )
        return
    problem_id = str(problem.get("problem_id", ""))
    if session_state.get("status") != "active":
        await send_text(message, repository, "Задание завершено. Нажмите «➡ Следующее».")
        return
    prompt_id = session_state.get(
        "problem_prompt_message_id", session_state.get("input_prompt_message_id")
    )
    if not matches_current_condition(message, cast(dict[str, object], session_state)):
        await send_text(
            message,
            repository,
            "Ответ к предыдущему заданию не принят. Напишите ответ числом в чат.",
        )
        return
    task9_policy = ANSWER_POLICIES_BY_SNAPSHOT.get(
        (str(problem.get("answer_policy_id", "")), str(problem.get("answer_policy_version", "")))
    )
    if task9_policy is None:
        await send_text(
            message, repository, "Политика ответа этой задачи недоступна; откройте новое задание."
        )
        return
    parsed = task9_policy.parse(message.text)
    if parsed is None:
        await send_text(message, repository, "Введите один числовой корень, например −3 или 2,5.")
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
        await send_text(message, repository, "Ответ к уже сменившемуся заданию проигнорирован.")
    elif outcome.get("status") == "duplicate":
        await send_text(message, repository, "Это сообщение уже было обработано.")
    elif outcome.get("status") == "solved":
        sent = await send_text(
            message,
            repository,
            "✅ Верно!\nОтвет засчитан.",
            reply_markup=task9_menu(problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task9_prompt_message(
                user_id, problem_id, result_id, expected_status="solved"
            )
            await _disable_stale_keyboard(sent, saved)
    elif outcome.get("status") == "active":
        sent = await send_text(
            message,
            repository,
            "Пока неверно. Попробуйте ещё раз.",
            reply_markup=task9_menu(problem_id),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task9_prompt_message(
                user_id, problem_id, result_id, expected_status="active"
            )
            await _disable_stale_keyboard(sent, saved)
    elif outcome.get("status") == "failed":
        snapshot = cast(dict[str, object], outcome["problem"])
        solution = snapshot.get("solution", [])
        rendered_steps = (
            "\n".join(str(step) for step in solution) if isinstance(solution, list) else ""
        )
        sent = await send_text(
            message,
            repository,
            f"Вторая попытка неверна. Правильный ответ: {snapshot['correct_answer']}.\n\n"
            f"Разбор:\n{rendered_steps}",
            reply_markup=task9_menu(problem_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task9_prompt_message(
                user_id, problem_id, result_id, expected_status="failed"
            )
            await _disable_stale_keyboard(sent, saved)
    else:
        await send_text(message, repository, "Ответ уже обработан. Нажмите «➡ Следующее».")


async def menu_section(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    has_session = False
    if user_id is not None:
        await repository.save_user_state(user_id, "main_menu")
        has_session = await _has_resumable_session(repository, user_id)
    await send_text(
        message,
        repository,
        "Этот раздел пока не включён: сначала для него требуется отдельная проверка качества.",
        reply_markup=main_menu(has_session=has_session),
    )


async def return_to_menu(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    has_session = False
    if user_id is not None:
        await repository.save_user_state(user_id, "main_menu")
        has_session = await _has_resumable_session(repository, user_id)
    await send_text(
        message, repository, "Главное меню.", reply_markup=main_menu(has_session=has_session)
    )


async def show_progress(message: Message, repository: Repository) -> None:
    from app.bot.progress import progress_keyboard, render_progress
    from app.persistence.training_insights import training_insights

    user_id = _user_id(message)
    if user_id is None:
        return
    await repository.save_user_state(user_id, "progress")
    insights = await training_insights(repository, user_id)
    await send_text(
        message, repository, render_progress(insights), reply_markup=progress_keyboard()
    )


async def show_progress_details(message: Message, repository: Repository) -> None:
    from app.bot.progress import progress_keyboard, render_progress
    from app.persistence.training_insights import training_insights

    user_id = _user_id(message)
    if user_id is None:
        return
    await repository.save_user_state(user_id, "progress")
    insights = await training_insights(repository, user_id, "numbers")
    await send_text(
        message,
        repository,
        render_progress(insights, "numbers"),
        reply_markup=progress_keyboard("numbers"),
    )


async def unknown_message(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    screen = await repository.user_state(user_id)
    for training in TRAININGS:
        if screen != training.mode:
            continue
        state = await getattr(repository, f"task{training.number}_state")(user_id)
        if state is not None and isinstance(state.get("problem"), dict):
            session_state = state.get("state", {})
            if isinstance(session_state, dict) and session_state.get("status") == "active":
                await globals()[f"task{training.number}_answer"](message, repository)
            else:
                await send_text(
                    message,
                    repository,
                    "Задание завершено. Используйте кнопку «➡ Следующее» "
                    "на сообщении с результатом.",
                )
            return
    has_session = await _has_resumable_session(repository, user_id)
    await repository.save_user_state(user_id, "main_menu")
    await send_text(
        message,
        repository,
        "Используйте кнопки меню или команду /start.",
        reply_markup=main_menu(has_session=has_session),
    )


def build_router() -> Router:
    router = Router()
    router.callback_query.register(
        navigation_callback, F.data.startswith("nav:") | F.data.startswith("progress:")
    )
    router.message.register(start, CommandStart())
    router.message.register(cancel, Command("cancel"))
    router.message.register(continue_session, F.text == "▶ Продолжить")
    router.message.register(choose_number, F.text == "🧮 По номеру")
    router.message.register(choose_task6, F.text == TASK6_LABEL)
    router.message.register(choose_task9, F.text == TASK9_LABEL)
    router.message.register(choose_task10, F.text == TASK10_LABEL)
    router.message.register(choose_task12, F.text == TASK12_LABEL)
    router.message.register(choose_task14, F.text == TASK14_LABEL)
    router.message.register(choose_task7, F.text == TASK7_LABEL)
    router.message.register(choose_task8, F.text == TASK8_LABEL)
    router.message.register(choose_task13, F.text == TASK13_LABEL)
    router.message.register(choose_task11, F.text == TASK11_LABEL)
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
    router.callback_query.register(task10_callback, F.data.startswith("t10:"))
    router.callback_query.register(task12_callback, F.data.startswith("t12:"))
    router.callback_query.register(task14_callback, F.data.startswith("t14:"))
    router.callback_query.register(task7_callback, F.data.startswith("t7:"))
    router.callback_query.register(task8_callback, F.data.startswith("t8:"))
    router.callback_query.register(task13_callback, F.data.startswith("t13:"))
    router.callback_query.register(task11_callback, F.data.startswith("t11:"))
    return router
