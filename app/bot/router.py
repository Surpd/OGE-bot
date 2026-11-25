import asyncio
import base64
import logging
import secrets
from collections.abc import Awaitable, Callable
from functools import partial
from typing import cast

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.callbacks import answer_callback
from app.bot.menu import (
    MAIN_MENU,
    main_menu,
    number_page,
    saved_training_menu,
    task6_menu,
    task7_menu,
    task9_menu,
    task11_menu,
    task13_menu,
)
from app.bot.mixed_training import mixed_answer, mixed_callback
from app.bot.mixed_training import start_mixed as _start_mixed
from app.bot.navigation import navigation_callback, show_display_options
from app.bot.presentation import hint_message, send_photo, send_text
from app.bot.scenario_training import (
    PUBLIC_LABEL,
    show_public_oge15,
)
from app.bot.scenario_training import (
    answer_message as oge15_answer,
)
from app.bot.scenario_training import (
    handle_callback as oge15_callback,
)
from app.bot.scenario_training import (
    render_session as render_oge15_session,
)
from app.bot.task_view import answer_instruction, question_text, system_rows
from app.bot.task_view import task13_is_graph_choice as _task13_is_graph_choice
from app.bot.training_engine import (
    NUMERIC_TRAININGS,
    persist_open_training,
    recover_saved_training,
    send_problem,
    training_answer,
    training_callback,
)
from app.bot.training_ux import TERMINAL_RESULTS, matches_current_condition, resumed_result
from app.bot.trainings import TRAININGS
from app.math.equations import ANSWER_POLICIES_BY_SNAPSHOT
from app.math.family_cycle import ordinary_candidates
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
from app.persistence.rotation_history import specialist_state as rotation_state
from app.persistence.scenario_repository import ScenarioPostgresRepository

logger = logging.getLogger(__name__)
TASK6_LABEL = "№6 · Вычисления"
TASK7_LABEL = "№7 · Числа и координатная прямая"
TASK9_LABEL = "№9 · Уравнения"
TASK10_LABEL = "№10 · Вероятность"
TASK12_LABEL = "№12 · Формулы"
TASK14_LABEL = "№14 · Прогрессии"
TASK16_LABEL = "№16 · Окружности"
TASK17_LABEL = "№17 · Четырёхугольники"
TASK19_LABEL = "№19 · Геометрические утверждения"
TASK8_LABEL = "№8 · Степени и корни"
TASK13_LABEL = "№13 · Неравенства"
TASK11_LABEL = "№11 · Графики функций"


def _user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user is not None else None


async def _pause_oge15_foreground(
    user_id: int | None, oge15_repository: ScenarioPostgresRepository | None
) -> None:
    if user_id is not None and oge15_repository is not None:
        await oge15_repository.pause_foreground(user_id)


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
    return isinstance(session_state, dict) and session_state.get("status") in {
        "active",
        "solved",
        "failed",
        "solution_viewed",
    }


def _has_resumable_task9(state: dict[str, object] | None) -> bool:
    if state is None or not isinstance(state.get("problem"), dict):
        return False
    session_state = state.get("state")
    return isinstance(session_state, dict) and session_state.get("status") in {
        "active",
        "solved",
        "failed",
        "solution_viewed",
    }


async def _has_resumable_session(
    repository: Repository,
    user_id: int,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> bool:
    from app.config import get_settings

    adaptive = None
    if getattr(repository, "_pool", None) is not None:
        from app.adaptive.session import Session

        adaptive = await Session(repository, user_id).current()
        if (
            adaptive is not None
            and get_settings().oge_adaptive_enabled
            and await repository.personal_enabled(user_id)
        ):
            return True
    mode = await repository.last_training_mode(user_id)
    if mode == "adaptive" and adaptive is not None:
        scope = adaptive["scope"] or {}
        if isinstance(scope, str):
            import json

            scope = json.loads(scope)
        mode = scope.get("resume_fallback")
    if mode == "part2":
        from app.bot.part2 import store

        bank = store(repository)
        return bank is not None and await bank.current(user_id) is not None
    if mode == "mixed":
        from app.persistence.mixed_training import MixedTrainingRepository

        return await MixedTrainingRepository(repository).state(user_id) is not None
    if mode == "oge15":
        return bool(
            oge15_repository is not None
            and await oge15_repository.last_used_session(user_id) is not None
        )
    training = next((item for item in TRAININGS if item.mode == mode), None)
    if training is None or not training.available:
        return False
    state = await getattr(repository, f"task{training.number}_state")(user_id)
    if _has_resumable_task6(state):
        return True
    saved = state.get("state") if state else None
    return isinstance(saved, dict) and saved.get("status") == "restart_ready"


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
    status = state_value.get("status")
    terminal = action == "resume" and isinstance(status, str) and status in TERMINAL_RESULTS
    if action == "resume":
        if not isinstance(current_problem, dict) or (status != "active" and not terminal):
            return False
        if (
            expected_problem_id is not None
            and current_problem.get("problem_id") != expected_problem_id
        ):
            return False
        saved_problem = current_problem
    else:
        if (
            action == "advance"
            and expected_problem_id is None
            and isinstance(current_problem, dict)
        ):
            expected_problem_id = str(current_problem.get("problem_id", ""))
        state_value = await rotation_state(repository, user_id, 6, state_value)
        candidates = ordinary_candidates(
            build_candidate_batch, state_value, secrets.randbelow(2**63)
        )
        if selected := state_value.get("selected_family_id"):
            candidates = [item for item in candidates if item["family_id"] == selected]
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
    body = f"Задание №6\n\n{saved_problem['condition']}"
    if terminal:
        body += "\n\n" + (resumed_result(status, saved_problem) or "")
    sent = await send_text(
        message,
        repository,
        body,
        reply_markup=task6_menu(str(saved_problem["problem_id"]), completed=terminal),
        math_family=saved_problem,
    )
    prompt_message_id = getattr(sent, "message_id", None)
    if type(prompt_message_id) is int:
        if terminal:
            saved = await repository.set_task6_prompt_message(
                user_id, str(saved_problem["problem_id"]), prompt_message_id,
                expected_status=str(status),
            )
            if not saved:
                await _disable_stale_keyboard(sent, saved)
                return False
        else:
            await repository.set_task6_condition_message(
                user_id, str(saved_problem["problem_id"]), prompt_message_id
            )
    return await persist_open_training(
        repository,
        user_id,
        "task6",
        str(saved_problem["problem_id"]),
        prompt_message_id if type(prompt_message_id) is int else None,
        expected_screen,
    )


async def start(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    from aiogram.types import ReplyKeyboardRemove

    from app.config import get_settings

    if message.from_user is None:
        return
    await repository.register_user(message.from_user.id)
    await _pause_oge15_foreground(message.from_user.id, oge15_repository)
    await repository.save_user_state(message.from_user.id, "main_menu")
    has_session = await _has_resumable_session(repository, message.from_user.id, oge15_repository)
    logger.info("user_started")
    await send_text(
        message,
        repository,
        ("Привет! Здесь можно тренировать задания ОГЭ по математике №1–25."
         if get_settings().oge_part2_enabled
         else "Привет! Это OGE Trainer — тренажёр первой части ОГЭ по математике."),
        reply_markup=ReplyKeyboardRemove(),
    )
    await send_text(
        message,
        repository,
        "Выберите раздел в меню.",
        reply_markup=main_menu(has_session=has_session),
    )


async def cancel(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    user_id = _user_id(message)
    has_session = False
    if user_id is not None:
        await _pause_oge15_foreground(user_id, oge15_repository)
        await repository.save_user_state(user_id, "main_menu")
        has_session = await _has_resumable_session(repository, user_id, oge15_repository)
    await send_text(
        message,
        repository,
        "Текущий раздел закрыт.",
        reply_markup=main_menu(has_session=has_session),
    )


async def continue_session(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
    user_id_override: int | None = None,
) -> None:
    actor_id = user_id_override if user_id_override is not None else _user_id(message)
    if actor_id is None:
        return
    user_id: int = actor_id

    from app.config import get_settings

    adaptive = None
    if getattr(repository, "_pool", None) is not None:
        from app.adaptive.session import Session
        from app.bot.adaptive import present

        short = Session(repository, user_id)
        adaptive = await short.current()
        if (
            adaptive is not None
            and get_settings().oge_adaptive_enabled
            and await repository.personal_enabled(user_id)
        ):
            await short.start([])
            await present(message, repository, user_id)
            return

    async def resume_pilot() -> bool:
        if oge15_repository is None:
            return False
        scenario_session = await oge15_repository.last_used_session(user_id)
        if scenario_session is not None:
            scenario_session = await oge15_repository.resume_paused(
                user_id, scenario_session.session_id
            )
        if scenario_session is None:
            return False
        await render_oge15_session(
            message,
            oge15_repository,
            scenario_session,
            show_assets=True,
            user_id_override=user_id,
            repository=repository,
        )
        await repository.save_user_state(user_id, "oge15")
        return True

    last = await repository.last_training_mode(user_id)
    if last == "adaptive" and adaptive is not None:
        scope = adaptive["scope"] or {}
        if isinstance(scope, str):
            import json

            scope = json.loads(scope)
        last = scope.get("resume_fallback")
    if last == "part2":
        from app.bot.part2 import resume

        if await resume(message, repository, user_id):
            return
    if last == "mixed":
        from app.bot.mixed_training import continue_mixed

        if await continue_mixed(message, repository, user_id):
            return
    if last == "oge15" and await resume_pilot():
        return
    training = next((item for item in TRAININGS if item.mode == last), None)
    if training is not None and training.available:
        state = await recover_saved_training(repository, user_id, training.mode)
        if state is not None and _has_resumable_task6(state):
            current = cast(dict[str, object], state["problem"])
            sender = _saved_problem_sender(training.number)
            source_screen = await repository.user_state(user_id)
            await _pause_oge15_foreground(user_id, oge15_repository)
            await sender(
                message,
                repository,
                action="resume",
                expected_problem_id=str(current["problem_id"]),
                expected_screen=source_screen,
                user_id_override=user_id,
            )
            return
    await repository.save_user_state(user_id, "main_menu")
    await send_text(
        message, repository, "Нет незавершённых заданий. Выберите номер.", reply_markup=main_menu()
    )


async def start_mixed(message: Message, repository: Repository) -> None:
    await _start_mixed(message, repository)


async def choose_number(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
    *, page: int = 0,
) -> None:
    user_id = _user_id(message)
    if user_id is not None:
        await _pause_oge15_foreground(user_id, oge15_repository)
        await repository.save_user_state(user_id, "number_selection")
    text, keyboard = number_page(
        include_task7=bool(TASK7_ENABLED_FAMILIES),
        include_task13=bool(TASK13_ENABLED_FAMILIES),
        include_task11=bool(TASK11_ENABLED_FAMILIES),
        page=page,
    )
    await send_text(message, repository, text, reply_markup=keyboard)


def _saved_problem_sender(number: int) -> Callable[..., Awaitable[bool]]:
    if number in NUMERIC_TRAININGS:
        return partial(send_problem, NUMERIC_TRAININGS[number])
    return {
        6: _send_problem, 7: _send_task7_problem, 9: _send_task9_problem,
        11: _send_task11_problem, 13: _send_task13_problem,
    }[number]


async def _show_saved_training_choice(
    message: Message, repository: Repository, number: int, user_id: int | None
) -> bool:
    if user_id is None or not any(item.number == number and item.available for item in TRAININGS):
        return False
    state = await recover_saved_training(repository, user_id, f"task{number}")
    problem = state.get("problem") if state else None
    saved = state.get("state") if state else None
    status = saved.get("status") if isinstance(saved, dict) else None
    if not isinstance(problem, dict) or status not in {
        "active",
        "solved",
        "failed",
        "solution_viewed",
    }:
        return False
    title = next((item.title for item in TRAININGS if item.number == number), f"№{number}")
    problem_id = str(problem.get("problem_id", ""))
    await repository.save_user_state(user_id, "number_selection")
    await send_text(
        message,
        repository,
        f"Сохранена практика: №{number} · {title}.\nМожно продолжить её или начать заново.",
        reply_markup=saved_training_menu(number, problem_id),
    )
    return True


async def saved_training_navigation(
    message: Message,
    repository: Repository,
    user_id: int,
    action: str,
    number: int,
    problem_id: str,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    training = next((item for item in TRAININGS if item.number == number and item.available), None)
    if training is None or action not in {"continue", "restart", "confirm", "cancel"}:
        await send_text(message, repository, "Этот вариант тренировки недоступен.")
        return
    state = await recover_saved_training(repository, user_id, training.mode)
    problem = state.get("problem") if state else None
    saved = state.get("state") if state else None
    status = saved.get("status") if isinstance(saved, dict) else None
    if not isinstance(problem, dict) or str(problem.get("problem_id")) != problem_id:
        await send_text(message, repository, "Это сохранённое задание уже изменилось.")
        return
    sender = _saved_problem_sender(number)
    if action == "restart":
        await send_text(
            message,
            repository,
            f"Начать новую практику №{number} · {training.title}? "
            "Завершённые результаты сохранятся. Активное задание останется без результата.",
            reply_markup=saved_training_menu(number, problem_id, confirm_restart=True),
        )
        return
    if action == "cancel":
        await _show_saved_training_choice(message, repository, number, user_id)
        return
    await _pause_oge15_foreground(user_id, oge15_repository)
    if action == "confirm":
        previous_status = await repository.prepare_training_restart(
            user_id, training.mode, problem_id, "number_selection"
        )
        if previous_status is None:
            await send_text(
                message, repository, "Тренировка уже изменилась. Выберите номер ещё раз."
            )
            return
        opened = await sender(
            message,
            repository,
            action="advance",
            expected_problem_id=problem_id,
            expected_screen="number_selection",
            user_id_override=user_id,
        )
        if not opened:
            await repository.restore_training_restart(
                user_id, training.mode, problem_id, previous_status
            )
        return
    if status == "active" or status in TERMINAL_RESULTS:
        await sender(
            message,
            repository,
            action="resume",
            expected_problem_id=problem_id,
            expected_screen="number_selection",
            user_id_override=user_id,
        )
    else:
        await send_text(message, repository, "Эту тренировку нельзя продолжить.")


async def choose_task6(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    user_id = _user_id(message)
    if user_id is not None:
        await _pause_oge15_foreground(user_id, oge15_repository)
    if await _show_saved_training_choice(message, repository, 6, user_id):
        return
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
    status = state_value.get("status")
    terminal = action == "resume" and isinstance(status, str) and status in TERMINAL_RESULTS
    if action == "resume":
        if not isinstance(current_problem, dict) or (status != "active" and not terminal):
            return False
        if (
            expected_problem_id is not None
            and current_problem.get("problem_id") != expected_problem_id
        ):
            return False
        saved_problem = current_problem
    else:
        if action == "start" and isinstance(current_problem, dict):
            if state_value.get("status") == "active":
                saved_problem = current_problem
                sent = await send_text(
                    message,
                    repository,
                    f"Задание №9\n\n{saved_problem['condition']}",
                    reply_markup=task9_menu(str(saved_problem["problem_id"])),
                    math_family=saved_problem,
                )
                prompt_id = getattr(sent, "message_id", None)
                if type(prompt_id) is int:
                    await repository.set_task9_condition_message(
                        user_id, str(saved_problem["problem_id"]), prompt_id
                    )
                return await persist_open_training(
                    repository,
                    user_id,
                    "task9",
                    str(saved_problem["problem_id"]),
                    prompt_id if type(prompt_id) is int else None,
                    expected_screen,
                )
            expected_problem_id = str(current_problem.get("problem_id", ""))
            action = "advance"
        if (
            action == "advance"
            and expected_problem_id is None
            and isinstance(current_problem, dict)
        ):
            expected_problem_id = str(current_problem.get("problem_id", ""))
        state_value = await rotation_state(repository, user_id, 9, state_value)
        candidates = ordinary_candidates(
            build_task9_candidate_batch, state_value, secrets.randbelow(2**63)
        )
        if selected := state_value.get("selected_family_id"):
            candidates = [item for item in candidates if item["family_id"] == selected]
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
    body = f"Задание №9\n\n{saved_problem['condition']}"
    if terminal:
        body += "\n\n" + (resumed_result(status, saved_problem) or "")
    sent = await send_text(
        message,
        repository,
        body,
        reply_markup=task9_menu(str(saved_problem["problem_id"]), completed=terminal),
        math_family=saved_problem,
    )
    prompt_id = getattr(sent, "message_id", None)
    if type(prompt_id) is int:
        if terminal:
            saved = await repository.set_task9_prompt_message(
                user_id, str(saved_problem["problem_id"]), prompt_id,
                expected_status=str(status),
            )
            if not saved:
                await _disable_stale_keyboard(sent, saved)
                return False
        else:
            await repository.set_task9_condition_message(
                user_id, str(saved_problem["problem_id"]), prompt_id
            )
    return await persist_open_training(
        repository,
        user_id,
        "task9",
        str(saved_problem["problem_id"]),
        prompt_id if type(prompt_id) is int else None,
        expected_screen,
    )


async def choose_task9(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    await _pause_oge15_foreground(_user_id(message), oge15_repository)
    if await _show_saved_training_choice(message, repository, 9, _user_id(message)):
        return
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


async def choose_task10(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    await _pause_oge15_foreground(_user_id(message), oge15_repository)
    if await _show_saved_training_choice(message, repository, 10, _user_id(message)):
        return
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
    freshly_generated = False
    status = state_value.get("status")
    terminal = action == "resume" and isinstance(status, str) and status in TERMINAL_RESULTS
    if action == "resume":
        if not isinstance(current, dict) or (status != "active" and not terminal):
            return False
        if expected_problem_id is not None and current.get("problem_id") != expected_problem_id:
            return False
        problem = current
    elif action == "start" and isinstance(current, dict) and state_value.get("status") == "active":
        problem = current
    else:
        if action == "start" and isinstance(current, dict):
            expected_problem_id = str(current.get("problem_id", ""))
            action = "advance"
        if action == "advance" and expected_problem_id is None and isinstance(current, dict):
            expected_problem_id = str(current.get("problem_id", ""))
        state_value = await rotation_state(repository, user_id, 11, state_value)
        candidates = await asyncio.to_thread(
            ordinary_candidates, build_task11_candidate_batch,
            state_value,
            secrets.randbelow(2**63),
            enabled_families=TASK11_ENABLED_FAMILIES,
            limit=1,
        )
        if selected := state_value.get("selected_family_id"):
            candidates = [item for item in candidates if item["family_id"] == selected]
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
        freshly_generated = problem.get("_transitioned") is True
        if action == "advance" and problem.get("_transitioned") is False:
            return False
    try:
        # Fresh candidates have already passed the independent raster oracle in generate().
        restored = await asyncio.to_thread(
            task11_from_snapshot, problem, audit_raster=not freshly_generated
        )
    except ValueError:
        await send_text(
            message, repository, "Сохранённое задание №11 повреждено; ответ не обработан."
        )
        return False
    caption = (
        "Задание №11\n"
        f"{restored.condition}\n\n"
        + (
            (resumed_result(status, problem) or "") if terminal
            else answer_instruction(11, problem)
        )
    )
    sent = await send_photo(
        message,
        repository,
        BufferedInputFile(restored.png_bytes, filename="oge11.png"),
        caption=caption,
        diagram_caption="Графики к заданию №11",
        reply_markup=task11_menu(restored.problem_id, completed=terminal),
        math_family=problem,
    )
    condition_id = getattr(sent, "message_id", None)
    if type(condition_id) is int:
        if terminal:
            saved = await repository.set_task11_prompt_message(
                user_id, restored.problem_id, condition_id,
                expected_status=str(status),
            )
            if not saved:
                await _disable_stale_keyboard(sent, saved)
                return False
        else:
            await repository.set_task11_condition_message(
                user_id, restored.problem_id, condition_id
            )
    return await persist_open_training(
        repository,
        user_id,
        "task11",
        restored.problem_id,
        condition_id if type(condition_id) is int else None,
        expected_screen,
    )


async def choose_task11(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    await _pause_oge15_foreground(_user_id(message), oge15_repository)
    if await _show_saved_training_choice(message, repository, 11, _user_id(message)):
        return
    await _send_task11_problem(message, repository, action="start")


async def task11_callback(callback: CallbackQuery, repository: Repository) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "t11" or callback.message is None:
        await answer_callback(callback)
        return
    _, action, expected_id = parts
    user_id = callback.from_user.id
    message = cast(Message, callback.message)
    condition_id = getattr(message, "message_id", None)
    if type(condition_id) is not int:
        await answer_callback(callback, "Кнопка больше не связана с заданием.")
        return
    if action == "menu":
        changed = await repository.transition_task_screen(
            user_id, "task11", expected_id, "main_menu", condition_id
        )
        if not changed:
            await answer_callback(callback, "Тренировка приостановлена или задание уже сменилось.")
            return
        await send_text(
            message,
            repository,
            "Главное меню.",
            user_id_override=user_id,
            reply_markup=main_menu(has_session=await _has_resumable_session(repository, user_id)),
        )
        await answer_callback(callback)
        return
    if await repository.user_state(user_id) != "task11":
        await answer_callback(callback, "Тренировка приостановлена. Нажмите «Продолжить».")
        return
    state = await repository.task11_state(user_id)
    problem = state.get("problem") if state else None
    if not isinstance(problem, dict) or str(problem.get("problem_id")) != expected_id:
        await answer_callback(callback, "Это задание уже сменилось.")
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
        await answer_callback(callback, None if advanced else "Это задание уже сменилось.")
        return
    if action == "hint":
        hint = await repository.task11_hint(user_id, expected_id, condition_id)
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет.",
            math_family=problem,
        )
    elif action == "solution":
        revealed = await repository.task11_reveal_solution(user_id, expected_id, condition_id)
        snapshot = revealed.get("problem") if revealed else None
        if not isinstance(snapshot, dict):
            await answer_callback(callback, "Это задание уже сменилось.")
            return
        try:
            restored = task11_from_snapshot(snapshot)
        except ValueError:
            await answer_callback(callback, "Сохранённое условие повреждено.", show_alert=True)
            return
        sent = await send_text(
            message,
            repository,
            "Разбор (самостоятельное решение не засчитывается):\n"
            + "\n".join(restored.solution)
            + f"\n\nОтвет: {restored.correct_answer}",
            reply_markup=task11_menu(expected_id, completed=True),
            math_family=problem,
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task11_prompt_message(
                user_id, expected_id, result_id, expected_status=_solution_display_status(revealed)
            )
            await _disable_stale_keyboard(sent, saved)
    else:
        await answer_callback(callback)
        return
    await answer_callback(callback)


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
        math_family=problem,
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


async def choose_task12(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    await _pause_oge15_foreground(_user_id(message), oge15_repository)
    if await _show_saved_training_choice(message, repository, 12, _user_id(message)):
        return
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


async def choose_task14(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    await _pause_oge15_foreground(_user_id(message), oge15_repository)
    if await _show_saved_training_choice(message, repository, 14, _user_id(message)):
        return
    await _send_task14_problem(message, repository, action="start")


async def task14_callback(callback: CallbackQuery, repository: Repository) -> None:
    await training_callback(NUMERIC_TRAININGS[14], callback, repository)


async def task14_answer(message: Message, repository: Repository) -> None:
    await training_answer(NUMERIC_TRAININGS[14], message, repository)


async def choose_task17(message: Message, repository: Repository) -> None:
    if await _show_saved_training_choice(message, repository, 17, _user_id(message)):
        return
    await send_problem(NUMERIC_TRAININGS[17], message, repository, action="start")


async def task17_callback(callback: CallbackQuery, repository: Repository) -> None:
    await training_callback(NUMERIC_TRAININGS[17], callback, repository)


async def task17_or_scenario_answer(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    user_id = _user_id(message)
    if user_id is not None and await repository.user_state(user_id) == "task17":
        await task17_answer(message, repository)
        return
    await oge15_answer(message, oge15_repository, repository)


async def task17_answer(message: Message, repository: Repository) -> None:
    await training_answer(NUMERIC_TRAININGS[17], message, repository)


async def _send_task15_problem(
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
        NUMERIC_TRAININGS[15],
        message,
        repository,
        action=action,
        expected_problem_id=expected_problem_id,
        expected_screen=expected_screen,
        expected_prompt_message_id=expected_prompt_message_id,
        user_id_override=user_id_override,
        skip_active=skip_active,
    )


async def choose_task15(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    if not NUMERIC_TRAININGS[15].families:
        await send_text(message, repository, "Задания №15 пока выключены.")
        return
    await _pause_oge15_foreground(_user_id(message), oge15_repository)
    if await _show_saved_training_choice(message, repository, 15, _user_id(message)):
        return
    await _send_task15_problem(message, repository, action="start")


async def task15_callback(callback: CallbackQuery, repository: Repository) -> None:
    await training_callback(NUMERIC_TRAININGS[15], callback, repository)


async def task15_answer(message: Message, repository: Repository) -> None:
    await training_answer(NUMERIC_TRAININGS[15], message, repository)


async def _send_task16_problem(
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
        NUMERIC_TRAININGS[16],
        message,
        repository,
        action=action,
        expected_problem_id=expected_problem_id,
        expected_screen=expected_screen,
        expected_prompt_message_id=expected_prompt_message_id,
        user_id_override=user_id_override,
        skip_active=skip_active,
    )


async def choose_task16(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    if message.from_user is None:
        return
    if not NUMERIC_TRAININGS[16].families:
        await send_text(message, repository, "Задания №16 пока выключены.")
        return
    await _pause_oge15_foreground(message.from_user.id, oge15_repository)
    if await _show_saved_training_choice(message, repository, 16, message.from_user.id):
        return
    await _send_task16_problem(message, repository, action="start")


async def task16_callback(callback: CallbackQuery, repository: Repository) -> None:
    await training_callback(NUMERIC_TRAININGS[16], callback, repository)


async def task16_answer(message: Message, repository: Repository) -> None:
    await training_answer(NUMERIC_TRAININGS[16], message, repository)


async def _send_task18_problem(
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
        NUMERIC_TRAININGS[18],
        message,
        repository,
        action=action,
        expected_problem_id=expected_problem_id,
        expected_screen=expected_screen,
        expected_prompt_message_id=expected_prompt_message_id,
        user_id_override=user_id_override,
        skip_active=skip_active,
    )


async def choose_task18(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    if not NUMERIC_TRAININGS[18].families:
        await send_text(message, repository, "Задания №18 пока выключены.")
        return
    await _pause_oge15_foreground(_user_id(message), oge15_repository)
    if await _show_saved_training_choice(message, repository, 18, _user_id(message)):
        return
    await _send_task18_problem(message, repository, action="start")


async def task18_callback(callback: CallbackQuery, repository: Repository) -> None:
    await training_callback(NUMERIC_TRAININGS[18], callback, repository)


async def task18_answer(message: Message, repository: Repository) -> None:
    await training_answer(NUMERIC_TRAININGS[18], message, repository)


async def choose_task19(message: Message, repository: Repository) -> None:
    if not NUMERIC_TRAININGS[19].families:
        await send_text(message, repository, "Задания №19 пока выключены.")
        return
    user_id = _user_id(message)
    if user_id is None:
        return
    if await _show_saved_training_choice(message, repository, 19, user_id):
        return
    if (await repository.training_family(user_id, 19) is None
            and await repository.user_state(user_id) != "family_selection:19"):
        from app.bot.family_selection import show_families

        await show_families(message, repository, 19)
        return
    await send_problem(NUMERIC_TRAININGS[19], message, repository, action="start")


async def _send_task19_problem(
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
        NUMERIC_TRAININGS[19],
        message,
        repository,
        action=action,
        expected_problem_id=expected_problem_id,
        expected_screen=expected_screen,
        expected_prompt_message_id=expected_prompt_message_id,
        user_id_override=user_id_override,
        skip_active=skip_active,
    )


async def task19_callback(callback: CallbackQuery, repository: Repository) -> None:
    await training_callback(NUMERIC_TRAININGS[19], callback, repository)


async def task19_answer(message: Message, repository: Repository) -> None:
    await training_answer(NUMERIC_TRAININGS[19], message, repository)


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


async def choose_task8(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    await _pause_oge15_foreground(_user_id(message), oge15_repository)
    if await _show_saved_training_choice(message, repository, 8, _user_id(message)):
        return
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
    if isinstance(current, dict) and not await asyncio.to_thread(validate_task7_snapshot, current):
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
    status = state_value.get("status")
    terminal = action == "resume" and isinstance(status, str) and status in TERMINAL_RESULTS
    if action == "resume":
        if not isinstance(current, dict) or (status != "active" and not terminal):
            return False
        if expected_problem_id is not None and current.get("problem_id") != expected_problem_id:
            return False
        problem = current
    else:
        if (
            action == "start"
            and isinstance(current, dict)
            and state_value.get("status") == "active"
        ):
            problem = current
        else:
            if action == "start" and isinstance(current, dict):
                expected_problem_id = str(current.get("problem_id", ""))
                action = "advance"
            if action == "advance" and expected_problem_id is None and isinstance(current, dict):
                expected_problem_id = str(current.get("problem_id", ""))
            state_value = await rotation_state(repository, user_id, 7, state_value)
            candidates = await asyncio.to_thread(
                ordinary_candidates,
                build_task7_candidate_batch,
                state_value,
                secrets.randbelow(2**63),
                limit=1,
            )
            if selected := state_value.get("selected_family_id"):
                candidates = [item for item in candidates if item["family_id"] == selected]
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
    if problem.get("family_id") not in TASK7_ENABLED_FAMILIES or (
        problem is not current and not await asyncio.to_thread(validate_task7_snapshot, problem)
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
    footer = resumed_result(status, problem) if terminal else answer_instruction(7, problem)
    caption = f"Задание №7\n{question_text(7, problem)}\n\n{footer}"

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
            reply_markup=task7_menu(str(problem["problem_id"]), completed=terminal),
            math_family=problem,
        )
    else:
        sent = await send_text(
            message, repository, caption,
            reply_markup=task7_menu(str(problem["problem_id"]), completed=terminal),
            math_family=problem,
        )
    prompt_id = getattr(sent, "message_id", None)
    if type(prompt_id) is int:
        if terminal:
            saved = await repository.set_task7_prompt_message(
                user_id, str(problem["problem_id"]), prompt_id,
                expected_status=str(status),
            )
            if not saved:
                await _disable_stale_keyboard(sent, saved)
                return False
        else:
            await repository.set_task7_condition_message(
                user_id, str(problem["problem_id"]), prompt_id
            )
    return await persist_open_training(
        repository,
        user_id,
        "task7",
        str(problem["problem_id"]),
        prompt_id if type(prompt_id) is int else None,
        expected_screen,
    )


async def choose_task7(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    if not TASK7_ENABLED_FAMILIES:
        await send_text(
            message, repository, "Семейства задания №7 проходят приёмку и пока выключены."
        )
        return
    await _pause_oge15_foreground(_user_id(message), oge15_repository)
    if await _show_saved_training_choice(message, repository, 7, _user_id(message)):
        return
    await _send_task7_problem(message, repository, action="start")


async def task7_callback(callback: CallbackQuery, repository: Repository) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "t7" or callback.message is None:
        await answer_callback(callback)
        return
    _, action, expected_id = parts
    user_id = callback.from_user.id
    message = cast(Message, callback.message)
    prompt_id = getattr(message, "message_id", None)
    if type(prompt_id) is not int:
        await answer_callback(callback, "Кнопка больше не связана с заданием.")
        return
    if action == "menu":
        changed = await repository.transition_task_screen(
            user_id, "task7", expected_id, "main_menu", prompt_id
        )
        if not changed:
            await answer_callback(callback, "Тренировка приостановлена или задание уже сменилось.")
            return
        await send_text(
            message,
            repository,
            "Главное меню.",
            user_id_override=user_id,
            reply_markup=main_menu(has_session=await _has_resumable_session(repository, user_id)),
        )
        await answer_callback(callback)
        return
    if await repository.user_state(user_id) != "task7":
        await answer_callback(callback, "Тренировка приостановлена. Нажмите «Продолжить».")
        return
    state = await repository.task7_state(user_id)
    problem = state.get("problem") if state else None
    if not isinstance(problem, dict) or str(problem.get("problem_id")) != expected_id:
        await answer_callback(callback, "Это задание уже сменилось.")
        return
    if problem.get("family_id") not in TASK7_ENABLED_FAMILIES:
        await repository.save_user_state(user_id, "main_menu")
        await answer_callback(callback, "Это семейство задания №7 выключено.", show_alert=True)
        return
    if not validate_task7_snapshot(problem):
        await repository.save_user_state(user_id, "main_menu")
        await answer_callback(
            callback, "Сохранённое задание повреждено; оно не было обработано.", show_alert=True
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
        await answer_callback(callback, None if advanced else "Это задание уже сменилось.")
        return
    if action == "hint":
        hint = await repository.task7_hint(user_id, expected_id, prompt_id)
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет.",
            math_family=problem,
        )
    elif action == "solution":
        revealed = await repository.task7_reveal_solution(user_id, expected_id, prompt_id)
        snapshot = revealed.get("problem") if revealed else None
        if not isinstance(snapshot, dict):
            await answer_callback(callback, "Это задание уже сменилось.")
            return
        steps = snapshot.get("solution", [])
        sent = await send_text(
            message,
            repository,
            "Разбор (самостоятельное решение не засчитывается):\n"
            + "\n".join(str(step) for step in steps)
            + f"\n\nОтвет: {snapshot['correct_answer']}",
            reply_markup=task7_menu(expected_id, completed=True),
            math_family=problem,
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
        await answer_callback(callback)
        return
    await answer_callback(callback)


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
        message, repository, text, reply_markup=task7_menu(problem_id, completed=completed),
        math_family=problem,
    )
    result_id = getattr(sent, "message_id", None)
    if type(result_id) is int:
        saved = await repository.set_task7_prompt_message(
            user_id, problem_id, result_id, expected_status=str(status)
        )
        await _disable_stale_keyboard(sent, saved)


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
    status = state_value.get("status")
    terminal = action == "resume" and isinstance(status, str) and status in TERMINAL_RESULTS
    if action == "resume":
        if not isinstance(current, dict) or (status != "active" and not terminal):
            return False
        if expected_problem_id is not None and current.get("problem_id") != expected_problem_id:
            return False
        problem = current
    else:
        if (
            action == "start"
            and isinstance(current, dict)
            and state_value.get("status") == "active"
        ):
            problem = current
        else:
            if action == "start" and isinstance(current, dict):
                expected_problem_id = str(current.get("problem_id", ""))
                action = "advance"
            if action == "advance" and expected_problem_id is None and isinstance(current, dict):
                expected_problem_id = str(current.get("problem_id", ""))
            state_value = await rotation_state(repository, user_id, 13, state_value)
            candidates = await asyncio.to_thread(
                ordinary_candidates,
                build_task13_candidate_batch,
                state_value,
                secrets.randbelow(2**63),
                limit=1,
            )
            if selected := state_value.get("selected_family_id"):
                candidates = [item for item in candidates if item["family_id"] == selected]
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
    problem_id = str(problem["problem_id"])
    graph_choice = _task13_is_graph_choice(problem)
    if not graph_choice and not validate_task13_snapshot(problem):
        await repository.save_user_state(user_id, "main_menu")
        await send_text(
            message,
            repository,
            "Сохранённое задание №13 использует неподдерживаемую версию или повреждённые "
            "варианты. Оно не было заменено новым заданием.",
            reply_markup=main_menu(),
        )
        return False
    image = None
    if graph_choice:
        try:
            image = await asyncio.to_thread(render_option_sheet_snapshot_png, problem)
        except (ValueError, TypeError, ZeroDivisionError):
            await repository.save_user_state(user_id, "main_menu")
            await send_text(
                message,
                repository,
                "Не удалось отобразить сохранённые варианты №13; задание не пересоздавалось.",
                reply_markup=main_menu(),
            )
            return False
    footer = resumed_result(status, problem) if terminal else (
        "Выберите вариант кнопкой или напишите его номер в чат."
    )
    caption = f"Задание №13\n{question_text(13, problem)}\n\n{footer}"
    markup = task13_menu(problem_id, completed=terminal, choices=True)
    math_system_rows = system_rows(13, problem)
    if image is not None:
        sent = await send_photo(
            message,
            repository,
            BufferedInputFile(image, filename="oge13-options.png"),
            caption=caption,
            diagram_caption="Варианты ответа к заданию №13",
            reply_markup=markup,
            math_system_rows=math_system_rows,
            math_family=problem,
        )
    else:
        sent = await send_text(
            message, repository, caption, reply_markup=markup, math_system_rows=math_system_rows,
            math_family=problem,
        )
    prompt_id = getattr(sent, "message_id", None)
    if type(prompt_id) is int:
        if terminal:
            saved = await repository.set_task13_prompt_message(
                user_id, problem_id, prompt_id,
                expected_status=str(status),
            )
            if not saved:
                await _disable_stale_keyboard(sent, saved)
                return False
        else:
            await repository.set_task13_condition_message(
                user_id, problem_id, prompt_id
            )
    return await persist_open_training(
        repository,
        user_id,
        "task13",
        str(problem["problem_id"]),
        prompt_id if type(prompt_id) is int else None,
        expected_screen,
    )


async def choose_task13(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    await _pause_oge15_foreground(_user_id(message), oge15_repository)
    if await _show_saved_training_choice(message, repository, 13, _user_id(message)):
        return
    await _send_task13_problem(message, repository, action="start")


async def task13_callback(callback: CallbackQuery, repository: Repository) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) not in {3, 4} or parts[0] != "t13" or callback.message is None:
        await answer_callback(callback)
        return
    _, action, expected_id = parts[:3]
    user_id = callback.from_user.id
    message = cast(Message, callback.message)
    prompt_id = getattr(message, "message_id", None)
    if type(prompt_id) is not int:
        await answer_callback(callback, "Кнопка больше не связана с заданием.")
        return
    if action == "menu":
        changed = await repository.transition_task_screen(
            user_id, "task13", expected_id, "main_menu", prompt_id
        )
        if not changed:
            await answer_callback(callback, "Тренировка приостановлена или задание уже сменилось.")
            return
        await send_text(
            message,
            repository,
            "Главное меню.",
            user_id_override=user_id,
            reply_markup=main_menu(has_session=await _has_resumable_session(repository, user_id)),
        )
        await answer_callback(callback)
        return
    if await repository.user_state(user_id) != "task13":
        await answer_callback(callback, "Тренировка приостановлена. Нажмите «Продолжить».")
        return
    state = await repository.task13_state(user_id)
    problem = state.get("problem") if state else None
    if not isinstance(problem, dict) or str(problem.get("problem_id")) != expected_id:
        await answer_callback(callback, "Это задание уже сменилось.")
        return
    if action == "choose":
        if len(parts) != 4 or parts[3] not in {"1", "2", "3", "4"}:
            await answer_callback(callback, "Выберите вариант от 1 до 4.")
            return
        state_value = state.get("state", {}) if state else {}
        condition_id = (
            state_value.get("problem_prompt_message_id") if isinstance(state_value, dict) else None
        )
        current_prompt = (
            state_value.get("input_prompt_message_id") if isinstance(state_value, dict) else None
        )
        if current_prompt != prompt_id or type(condition_id) is not int:
            await answer_callback(callback, "Эта кнопка уже устарела.")
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
        await answer_callback(callback)
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
        await answer_callback(callback, None if advanced else "Это задание уже сменилось.")
        return
    if action == "hint":
        hint = await repository.task13_hint(user_id, expected_id, prompt_id)
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет.",
            math_family=problem,
        )
    elif action == "solution":
        revealed = await repository.task13_reveal_solution(user_id, expected_id, prompt_id)
        snapshot = revealed.get("problem") if revealed else None
        if not isinstance(snapshot, dict):
            await answer_callback(callback, "Это задание уже сменилось.")
            return
        steps = snapshot.get("solution", [])
        sent = await send_text(
            message,
            repository,
            "Разбор (самостоятельное решение не засчитывается):\n"
            + "\n".join(str(step) for step in steps)
            + f"\n\nОтвет: вариант {snapshot['correct_answer']}",
            reply_markup=task13_menu(expected_id, completed=True),
            math_family=problem,
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
        await answer_callback(callback)
        return
    await answer_callback(callback)


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
        math_family=problem,
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
        await answer_callback(callback)
        return
    _, action, expected_problem_id = parts
    user_id = callback.from_user.id
    message = cast(Message, callback.message)
    control_message_id = getattr(message, "message_id", None)
    if type(control_message_id) is not int:
        await answer_callback(callback, "Кнопка больше не связана с активным заданием.")
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
            await answer_callback(callback, "Тренировка приостановлена или задание уже сменилось.")
            return
        has_session = await _has_resumable_session(repository, user_id)
        await send_text(
            message,
            repository,
            "Главное меню.",
            user_id_override=user_id,
            reply_markup=main_menu(has_session=has_session),
        )
        await answer_callback(callback)
        return

    if await repository.user_state(user_id) != "task6":
        await answer_callback(callback, "Тренировка приостановлена. Нажмите «Продолжить».")
        return

    state = await repository.task6_state(user_id)
    problem = state.get("problem") if state else None
    current_id = str(problem.get("problem_id", "")) if isinstance(problem, dict) else ""
    if current_id != expected_problem_id:
        await answer_callback(callback, "Это задание уже сменилось.")
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
        await answer_callback(callback, "Задание уже сменилось." if not advanced else None)
        return

    if action == "hint":
        hint = await repository.task6_hint(
            user_id, expected_problem_id, expected_prompt_message_id=control_message_id
        )
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет.",
            math_family=problem,
        )
    elif action == "solution":
        revealed = await repository.task6_reveal_solution(
            user_id, expected_problem_id, expected_prompt_message_id=control_message_id
        )
        saved_problem = revealed.get("problem") if revealed else None
        if not isinstance(saved_problem, dict):
            await answer_callback(callback, "Это задание уже сменилось.")
            return
        solution = saved_problem.get("solution", [])
        steps = "\n".join(str(step) for step in solution) if isinstance(solution, list) else ""
        sent = await send_text(
            message,
            repository,
            "Разбор (самостоятельное решение не засчитывается):\n"
            f"{steps}\n\nОтвет: {saved_problem['correct_answer']}",
            reply_markup=task6_menu(expected_problem_id, completed=True),
            math_family=problem,
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
        await answer_callback(callback)
        return
    await answer_callback(callback)


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
        math_family=problem,
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
        math_family=saved_problem,
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
            math_family=saved_problem,
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
        await answer_callback(callback)
        return
    _, action, expected_problem_id = parts
    user_id = callback.from_user.id
    message = cast(Message, callback.message)
    control_message_id = getattr(message, "message_id", None)
    if type(control_message_id) is not int:
        await answer_callback(callback, "Кнопка больше не связана с активным заданием.")
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
            await answer_callback(callback, "Тренировка приостановлена или задание уже сменилось.")
            return
        await send_text(
            message,
            repository,
            "Главное меню.",
            user_id_override=user_id,
            reply_markup=main_menu(has_session=await _has_resumable_session(repository, user_id)),
        )
        await answer_callback(callback)
        return
    if await repository.user_state(user_id) != "task9":
        await answer_callback(callback, "Тренировка приостановлена. Нажмите «Продолжить».")
        return
    state = await repository.task9_state(user_id)
    problem = state.get("problem") if state else None
    current_id = str(problem.get("problem_id", "")) if isinstance(problem, dict) else ""
    if current_id != expected_problem_id:
        await answer_callback(callback, "Это задание уже сменилось.")
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
        await answer_callback(callback, None if advanced else "Это задание уже сменилось.")
        return
    if action == "hint":
        hint = await repository.task9_hint(
            user_id, expected_problem_id, expected_prompt_message_id=control_message_id
        )
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет.",
            math_family=problem,
        )
    elif action == "solution":
        revealed = await repository.task9_reveal_solution(
            user_id, expected_problem_id, expected_prompt_message_id=control_message_id
        )
        snapshot = revealed.get("problem") if revealed else None
        if not isinstance(snapshot, dict):
            await answer_callback(callback, "Это задание уже сменилось.")
            return
        steps = snapshot.get("solution", [])
        rendered_steps = "\n".join(str(step) for step in steps) if isinstance(steps, list) else ""
        sent = await send_text(
            message,
            repository,
            "Разбор (самостоятельное решение не засчитывается):\n"
            f"{rendered_steps}\n\nОтвет: {snapshot['correct_answer']}",
            reply_markup=task9_menu(expected_problem_id, completed=True),
            math_family=problem,
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
        await answer_callback(callback)
        return
    await answer_callback(callback)


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
            math_family=problem,
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await repository.set_task9_prompt_message(
                user_id, problem_id, result_id, expected_status="failed"
            )
            await _disable_stale_keyboard(sent, saved)
    else:
        await send_text(message, repository, "Ответ уже обработан. Нажмите «➡ Следующее».")


async def menu_section(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    user_id = _user_id(message)
    has_session = False
    if user_id is not None:
        await _pause_oge15_foreground(user_id, oge15_repository)
        await repository.save_user_state(user_id, "main_menu")
        has_session = await _has_resumable_session(repository, user_id)
    await send_text(
        message,
        repository,
        "Этот раздел пока не включён: сначала для него требуется отдельная проверка качества.",
        reply_markup=main_menu(has_session=has_session),
    )


async def return_to_menu(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
    user_id_override: int | None = None,
) -> None:
    user_id = user_id_override if user_id_override is not None else _user_id(message)
    has_session = False
    if user_id is not None:
        await _pause_oge15_foreground(user_id, oge15_repository)
        await repository.save_user_state(user_id, "main_menu")
        has_session = await _has_resumable_session(repository, user_id, oge15_repository)
    await send_text(
        message,
        repository,
        "Главное меню.",
        user_id_override=user_id,
        reply_markup=main_menu(has_session=has_session),
    )


async def show_progress(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    from app.bot.progress import progress_keyboard, render_progress
    from app.bot.progress_image import send_progress_image
    from app.persistence.training_insights import training_insights

    user_id = _user_id(message)
    if user_id is None:
        return
    await _pause_oge15_foreground(user_id, oge15_repository)
    await repository.save_user_state(user_id, "progress")
    wrapped_message = getattr(message, "_message", None)
    edit_existing = isinstance(wrapped_message, Message) and bool(wrapped_message.photo)
    if await send_progress_image(message, repository, user_id, edit_existing=edit_existing):
        return
    insights = await training_insights(repository, user_id)
    await send_text(
        message, repository, render_progress(insights),
        reply_markup=progress_keyboard(insights=insights),
    )


async def show_progress_text(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    """Explicit text-only route for clients that do not display Telegram Widgets."""
    from app.bot.progress import progress_keyboard, render_progress
    from app.persistence.training_insights import training_insights

    user_id = _user_id(message)
    if user_id is None:
        return
    await _pause_oge15_foreground(user_id, oge15_repository)
    await repository.save_user_state(user_id, "progress")
    insights = await training_insights(repository, user_id)
    await send_text(
        message, repository, render_progress(insights),
        reply_markup=progress_keyboard(insights=insights),
    )


async def show_progress_details(
    message: Message,
    repository: Repository,
    oge15_repository: ScenarioPostgresRepository | None = None,
) -> None:
    from app.bot.progress import progress_keyboard, render_progress
    from app.persistence.training_insights import training_insights

    user_id = _user_id(message)
    if user_id is None:
        return
    await _pause_oge15_foreground(user_id, oge15_repository)
    await repository.save_user_state(user_id, "progress")
    insights = await training_insights(repository, user_id)
    await send_text(
        message,
        repository,
        render_progress(insights, "details"),
        reply_markup=progress_keyboard("details"),
    )


async def unknown_message(message: Message, repository: Repository) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    screen = await repository.user_state(user_id)
    if screen == "error_replay":
        from app.bot.error_replay import answer as error_replay_answer

        await error_replay_answer(message, repository)
        return
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
    from app.bot.adaptive_feedback import AdaptiveFeedback

    router = Router()
    router.message.middleware(AdaptiveFeedback())
    router.callback_query.middleware(AdaptiveFeedback())
    router.callback_query.register(
        navigation_callback,
        F.data.startswith(("nav:", "p2:", "progress:", "replay:")),
    )
    from app.bot import adaptive

    router.callback_query.register(adaptive.callback, F.data.startswith(("ad:", "train:")))
    router.callback_query.register(mixed_callback, F.data.startswith("mixed:"))
    router.message.register(start, CommandStart())
    from app.bot.api_diagnostics import api_status, api_test

    router.message.register(api_status, Command("api_status"))
    router.message.register(api_test, Command("api_test"))
    router.message.register(cancel, Command("cancel"))
    router.message.register(continue_session, F.text == "▶ Продолжить")
    router.message.register(choose_number, F.text == "🧮 По номеру")
    router.message.register(choose_task6, F.text == TASK6_LABEL)
    router.message.register(choose_task9, F.text == TASK9_LABEL)
    router.message.register(choose_task10, F.text == TASK10_LABEL)
    router.message.register(choose_task12, F.text == TASK12_LABEL)
    router.message.register(choose_task14, F.text == TASK14_LABEL)
    router.message.register(choose_task17, F.text == TASK17_LABEL)
    router.message.register(choose_task15, F.text == "№15 · Треугольники")
    router.message.register(choose_task16, F.text == TASK16_LABEL)
    router.message.register(choose_task18, F.text == "№18 · Фигуры на клетчатой сетке")
    router.message.register(choose_task19, F.text == TASK19_LABEL)
    router.message.register(choose_task7, F.text == TASK7_LABEL)
    router.message.register(choose_task8, F.text == TASK8_LABEL)
    router.message.register(choose_task13, F.text == TASK13_LABEL)
    router.message.register(choose_task11, F.text == TASK11_LABEL)
    router.message.register(show_public_oge15, Command("oge15"))
    router.message.register(show_public_oge15, F.text == PUBLIC_LABEL)
    # Transitions are inline callbacks bound to a specific problem ID. Text commands
    # have no reliable association with the task shown when the user tapped them.
    router.message.register(task6_hint, F.text == "💡 Подсказка")
    router.message.register(task6_solution, F.text == "📘 Разбор")
    router.message.register(return_to_menu, F.text == "↩ В меню")
    router.message.register(show_progress, F.text == "📊 Прогресс")
    router.message.register(show_progress, F.text == "📊 Мой прогресс")
    router.message.register(show_progress_text, Command("progress"))
    router.message.register(show_progress_details, F.text == "📊 Подробнее")
    router.message.register(show_display_options, F.text == "⚙️ Настройки")
    from app.bot.part2 import collect

    router.message.register(collect, F.text | F.photo)
    router.message.register(adaptive.answer, F.text)
    router.message.register(mixed_answer, F.text)
    router.message.register(task17_or_scenario_answer)
    router.message.register(menu_section, F.text.in_(MAIN_MENU))
    router.message.register(unknown_message)
    router.callback_query.register(task6_callback, F.data.startswith("t6:"))
    router.callback_query.register(task9_callback, F.data.startswith("t9:"))
    router.callback_query.register(task10_callback, F.data.startswith("t10:"))
    router.callback_query.register(task12_callback, F.data.startswith("t12:"))
    router.callback_query.register(task14_callback, F.data.startswith("t14:"))
    router.callback_query.register(task17_callback, F.data.startswith("t17:"))
    router.callback_query.register(task15_callback, F.data.startswith("t15:"))
    router.callback_query.register(task16_callback, F.data.startswith("t16:"))
    router.callback_query.register(task18_callback, F.data.startswith("t18:"))
    router.callback_query.register(task19_callback, F.data.startswith("t19:"))
    router.callback_query.register(task7_callback, F.data.startswith("t7:"))
    router.callback_query.register(task8_callback, F.data.startswith("t8:"))
    router.callback_query.register(task13_callback, F.data.startswith("t13:"))
    router.callback_query.register(task11_callback, F.data.startswith("t11:"))
    router.callback_query.register(oge15_callback, F.data.startswith(("oge15:", "o:a:")))
    return router
