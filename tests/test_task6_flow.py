from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot.router import (
    choose_task6,
    continue_session,
    return_to_menu,
    show_progress,
    task6_answer,
    task6_hint,
    task6_next,
    task6_skip,
    task6_solution,
)
from app.persistence.repository import MemoryRepository


def _message(user_id: int, text: str) -> AsyncMock:
    message = AsyncMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="Student")
    message.text = text
    return message


@pytest.mark.asyncio
async def test_task6_wrong_first_attempt_does_not_reveal_answer_then_second_does() -> None:
    repository = MemoryRepository()
    initial = _message(777, "№6 · Вычисления")
    await choose_task6(initial, repository)
    state = await repository.task6_state(777)
    assert state is not None
    problem = state["problem"]
    assert isinstance(problem, dict)
    correct_answer = str(problem["correct_answer"])

    first = _message(777, "999")
    await task6_answer(first, repository)
    first_feedback = first.answer.await_args.args[0]
    assert "Пока неверно" in first_feedback
    assert correct_answer not in first_feedback
    assert repository.training[777]["state"]["attempts"] == 1

    second = _message(777, "999")
    await task6_answer(second, repository)
    second_feedback = second.answer.await_args.args[0]
    assert "Вторая попытка неверна" in second_feedback
    assert correct_answer in second_feedback
    assert repository.training[777]["state"]["attempts"] == 2


@pytest.mark.asyncio
async def test_correct_answer_is_counted_once_and_next_issues_a_new_problem() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(778, "№6 · Вычисления"), repository)
    state = await repository.task6_state(778)
    assert state is not None
    problem = state["problem"]
    assert isinstance(problem, dict)
    answer = str(problem["correct_answer"])
    await task6_answer(_message(778, answer), repository)
    assert repository.training[778]["state"]["status"] == "solved"
    attempts_after_correct = repository.training[778]["state"]["attempts"]
    await task6_answer(_message(778, answer), repository)
    assert repository.training[778]["state"]["attempts"] == attempts_after_correct

    await task6_next(_message(778, "➡ Следующее"), repository)
    first_next = repository.training[778]["problem"]["problem_id"]
    await task6_next(_message(778, "➡ Следующее"), repository)
    assert repository.training[778]["problem"]["problem_id"] != first_next


@pytest.mark.asyncio
async def test_replayed_telegram_message_does_not_consume_second_attempt() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(783, "№6 · Вычисления"), repository)
    first = _message(783, "999")
    first.message_id = 123456
    await task6_answer(first, repository)
    replay = _message(783, "999")
    replay.message_id = 123456
    await task6_answer(replay, repository)

    state = await repository.task6_state(783)
    assert state is not None
    assert state["state"]["attempts"] == 1
    assert len(repository.attempt_history[783]) == 1
    assert "уже было обработано" in replay.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_answer_uses_the_saved_policy_version() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(784, "№6 · Вычисления"), repository)
    state = await repository.task6_state(784)
    assert state is not None and isinstance(state["problem"], dict)
    state["problem"]["answer_policy_version"] = "unregistered-version"

    answer = _message(784, str(state["problem"]["correct_answer"]))
    await task6_answer(answer, repository)

    progress = await repository.task6_progress(784)
    assert progress["attempts"] == 0
    assert "временно недоступно" in answer.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_skip_issues_a_distinct_persisted_problem() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(779, "№6 · Вычисления"), repository)
    previous = repository.training[779]["problem"]["problem_id"]
    await task6_skip(_message(779, "⏭ Пропустить"), repository)
    assert repository.training[779]["problem"]["problem_id"] != previous


@pytest.mark.asyncio
async def test_opening_solution_closes_self_scoring_for_the_problem() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(781, "№6 · Вычисления"), repository)
    state = await repository.task6_state(781)
    assert state is not None and isinstance(state["problem"], dict)
    problem = state["problem"]
    correct_answer = str(problem["correct_answer"])

    await task6_solution(_message(781, "📘 Разбор"), repository)
    state_after_solution = await repository.task6_state(781)
    assert state_after_solution is not None
    assert state_after_solution["state"]["status"] == "solution_viewed"
    await task6_answer(_message(781, correct_answer), repository)

    progress = await repository.task6_progress(781)
    assert progress["correct"] == 0
    assert progress["attempts"] == 0
    assert progress["solutions_viewed"] == 1

    await task6_next(_message(781, "➡ Следующее"), repository)
    assert repository.training[781]["problem"]["problem_id"] != problem["problem_id"]


@pytest.mark.asyncio
async def test_menu_and_restart_restore_the_same_active_problem_and_counts() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(782, "№6 · Вычисления"), repository)
    initial = await repository.task6_state(782)
    assert initial is not None and isinstance(initial["problem"], dict)
    problem_id = initial["problem"]["problem_id"]

    await task6_answer(_message(782, "999"), repository)
    await task6_hint(_message(782, "💡 Подсказка"), repository)
    await return_to_menu(_message(782, "↩ В меню"), repository)
    await continue_session(_message(782, "▶ Продолжить"), repository)

    resumed = await repository.task6_state(782)
    assert resumed is not None and isinstance(resumed["problem"], dict)
    assert resumed["problem"]["problem_id"] == problem_id
    assert resumed["state"]["attempts"] == 1
    assert resumed["state"]["hints_used"] == 1
    assert repository.training[782]["state"]["status"] == "active"


@pytest.mark.asyncio
async def test_progress_counts_issued_answered_solved_and_attempts() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(780, "№6 · Вычисления"), repository)
    state = await repository.task6_state(780)
    assert state is not None
    problem = state["problem"]
    assert isinstance(problem, dict)
    await task6_answer(_message(780, "999"), repository)
    await task6_answer(_message(780, str(problem["correct_answer"])), repository)

    progress_message = _message(780, "📊 Прогресс")
    await show_progress(progress_message, repository)
    text = progress_message.answer.await_args.args[0]
    assert "Выдано задач: 1" in text
    assert "Задач с ответом: 1" in text
    assert "Решено верно: 1" in text
    assert "Попыток всего: 2" in text
    assert "Попыток №1 / №2: 1 / 1" in text
    assert "Решено с первой / второй попытки: 0 / 1" in text
