"""Shared numeric-training state machine; adapters retain versioned policies and schedulers."""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol, cast

from aiogram.types import CallbackQuery, Message

from app.bot.menu import main_menu, training_menu
from app.bot.presentation import hint_message, send_text
from app.bot.training_ux import matches_current_condition
from app.math.formulas import POLICY as FORMULA_POLICY
from app.math.oge8 import POLICY as POWERS_POLICY
from app.math.oge8_scheduler import build_task8_candidate_batch
from app.math.oge10_scheduler import build_task10_candidate_batch
from app.math.oge12_scheduler import build_task12_candidate_batch
from app.math.oge14_scheduler import build_task14_candidate_batch
from app.math.probability import ANSWER_POLICY as PROBABILITY_POLICY
from app.math.progressions import POLICY as PROGRESSION_POLICY
from app.persistence.repository import Repository


class NumericPolicy(Protocol):
    @property
    def policy_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def parse(self, raw: str) -> object: ...
    def accepts(self, raw: str, expected: str) -> bool: ...


@dataclass(frozen=True)
class NumericTraining:
    number: int
    title: str
    policy: NumericPolicy
    candidates: Callable[[dict[str, object], int], list[dict[str, object]]]
    invalid_answer: str = "Введите числовой ответ, например 12 или 3,5."

    @property
    def mode(self) -> str:
        return f"task{self.number}"

    @property
    def families(self) -> tuple[str, ...]:
        module = import_module(f"app.math.oge{self.number}_scheduler")
        return tuple(module.ENABLED_FAMILIES)

    def operation(self, repository: Repository, suffix: str) -> Any:
        # Persistence keeps existing per-number transactions and snapshot storage.
        return getattr(repository, f"task{self.number}_{suffix}")

    def menu(self, problem_id: str, *, completed: bool = False) -> Any:
        return training_menu(self.number, problem_id, completed=completed)


NUMERIC_TRAININGS = {
    8: NumericTraining(8, "степени и корни", POWERS_POLICY, build_task8_candidate_batch),
    10: NumericTraining(
        10,
        "вероятность",
        PROBABILITY_POLICY,
        build_task10_candidate_batch,
        "Введите вероятность числом, например 0,25.",
    ),
    12: NumericTraining(12, "расчёты по формулам", FORMULA_POLICY, build_task12_candidate_batch),
    14: NumericTraining(14, "прогрессии", PROGRESSION_POLICY, build_task14_candidate_batch),
}


async def send_problem(
    adapter: NumericTraining,
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
    from app.bot.router import _user_id

    user_id = user_id_override if user_id_override is not None else _user_id(message)
    if user_id is None:
        return False
    await getattr(repository, f"ensure_{adapter.mode}_session")(user_id)
    state = await adapter.operation(repository, "state")(user_id)
    state_value = cast(dict[str, object], state.get("state", {})) if state else {}
    current = state.get("problem") if state else None
    if action == "resume":
        if not isinstance(current, dict) or state_value.get("status") != "active":
            await send_text(
                message,
                repository,
                f"Нет незавершённой тренировки №{adapter.number}.",
                reply_markup=main_menu(),
            )
            return False
        problem = current
        await repository.save_user_state(user_id, adapter.mode)
    else:
        if (
            action == "start"
            and isinstance(current, dict)
            and state_value.get("status") == "active"
        ):
            problem = current
            await repository.save_user_state(user_id, adapter.mode)
        else:
            if action == "start" and isinstance(current, dict):
                expected_problem_id = str(current.get("problem_id", ""))
                action = "advance"
            if action == "advance" and expected_problem_id is None and isinstance(current, dict):
                expected_problem_id = str(current.get("problem_id", ""))
            selected = await repository.training_family(user_id, adapter.number)
            candidate_state = dict(state_value)
            if selected is not None:
                if selected not in adapter.families:
                    from app.bot.family_selection import family_exhausted

                    await family_exhausted(message, repository, user_id, adapter.number)
                    return False
                candidate_state["family_queue"] = [selected]
            candidates = adapter.candidates(candidate_state, secrets.randbelow(2**63))
            if selected is not None:
                candidates = [item for item in candidates if item.get("family_id") == selected]
                if not candidates:
                    from app.bot.family_selection import family_exhausted

                    await family_exhausted(message, repository, user_id, adapter.number)
                    return False
            try:
                problem = await getattr(repository, f"advance_{adapter.mode}_problem")(
                    user_id,
                    expected_problem_id,
                    candidates,
                    expected_screen,
                    expected_prompt_message_id,
                    skip_active,
                )
            except RuntimeError:
                if selected is not None:
                    from app.bot.family_selection import family_exhausted

                    await family_exhausted(message, repository, user_id, adapter.number)
                    return False
                await send_text(
                    message,
                    repository,
                    f"Не удалось подготовить задание №{adapter.number}. Попробуйте ещё раз.",
                )
                return False
            if action == "advance" and problem.get("_transitioned") is False:
                return False
            if expected_screen is None:
                await repository.save_user_state(user_id, adapter.mode)
    sent = await send_text(
        message,
        repository,
        f"Задание №{adapter.number} · {adapter.title}\n\n{problem['condition']}\n\n"
        "Напишите ответ числом в чат. Дробную часть можно отделять запятой или точкой.",
        reply_markup=adapter.menu(str(problem["problem_id"])),
    )
    prompt_id = getattr(sent, "message_id", None)
    if type(prompt_id) is int:
        await getattr(repository, f"set_{adapter.mode}_condition_message")(
            user_id, str(problem["problem_id"]), prompt_id
        )
    return True


async def training_callback(
    adapter: NumericTraining, callback: CallbackQuery, repository: Repository
) -> None:
    from app.bot.router import (
        _disable_stale_keyboard,
        _has_resumable_session,
        _solution_display_status,
    )

    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != f"t{adapter.number}" or callback.message is None:
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
            user_id, adapter.mode, expected_id, "main_menu", prompt_id
        )
        if not changed:
            await callback.answer("Тренировка приостановлена или задание уже сменилось.")
            return
        await send_text(
            message,
            repository,
            "Главное меню.",
            reply_markup=main_menu(has_session=await _has_resumable_session(repository, user_id)),
            user_id_override=user_id,
        )
        await callback.answer()
        return
    if await repository.user_state(user_id) != adapter.mode:
        await callback.answer("Тренировка приостановлена. Нажмите «Продолжить».")
        return
    state = await adapter.operation(repository, "state")(user_id)
    problem = state.get("problem") if state else None
    if not isinstance(problem, dict) or str(problem.get("problem_id")) != expected_id:
        await callback.answer("Это задание уже сменилось.")
        return
    if action in {"next", "skip"}:
        advanced = await send_problem(
            adapter,
            message,
            repository,
            action="advance",
            expected_problem_id=expected_id,
            expected_screen=adapter.mode,
            expected_prompt_message_id=prompt_id,
            user_id_override=user_id,
            skip_active=action == "skip",
        )
        await callback.answer(None if advanced else "Это задание уже сменилось.")
        return
    if action == "hint":
        hint = await adapter.operation(repository, "hint")(user_id, expected_id, prompt_id)
        await send_text(
            message, repository, hint_message(hint, problem) if hint else "Подсказок больше нет."
        )
    elif action == "solution":
        revealed = await adapter.operation(repository, "reveal_solution")(
            user_id, expected_id, prompt_id
        )
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
            reply_markup=adapter.menu(expected_id, completed=True),
        )
        result_id = getattr(sent, "message_id", None)
        if type(result_id) is int:
            saved = await getattr(repository, f"set_{adapter.mode}_prompt_message")(
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


async def training_answer(
    adapter: NumericTraining, message: Message, repository: Repository
) -> None:
    from app.bot.router import _disable_stale_keyboard, _user_id

    user_id = _user_id(message)
    if user_id is None or message.text is None:
        return
    state = await adapter.operation(repository, "state")(user_id)
    problem = state.get("problem") if state else None
    session_state = state.get("state", {}) if state else {}
    if (
        not isinstance(problem, dict)
        or not isinstance(session_state, dict)
        or session_state.get("status") != "active"
    ):
        await send_text(
            message, repository, f"Сначала откройте активную тренировку №{adapter.number}."
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
        problem.get("answer_policy_id") != adapter.policy.policy_id
        or problem.get("answer_policy_version") != adapter.policy.version
    ):
        await send_text(message, repository, "Политика ответа этой задачи недоступна.")
        return
    if adapter.policy.parse(message.text) is None:
        await send_text(message, repository, adapter.invalid_answer)
        return
    problem_id = str(problem.get("problem_id", ""))
    correct = adapter.policy.accepts(message.text, str(problem.get("correct_answer", "")))
    outcome = await adapter.operation(repository, "attempt")(
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
        message, repository, text, reply_markup=adapter.menu(problem_id, completed=completed)
    )
    result_id = getattr(sent, "message_id", None)
    if type(result_id) is int:
        saved = await getattr(repository, f"set_{adapter.mode}_prompt_message")(
            user_id, problem_id, result_id, expected_status=str(status)
        )
        await _disable_stale_keyboard(sent, saved)
