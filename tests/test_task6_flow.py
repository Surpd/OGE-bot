from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot.router import (
    choose_task6,
    show_progress,
    task6_answer,
    task6_next,
    task6_skip,
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
async def test_correct_answer_is_counted_once_and_next_button_is_idempotent() -> None:
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
    assert repository.training[778]["problem"]["problem_id"] == first_next


@pytest.mark.asyncio
async def test_skip_issues_a_distinct_persisted_problem() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(779, "№6 · Вычисления"), repository)
    previous = repository.training[779]["problem"]["problem_id"]
    await task6_skip(_message(779, "⏭ Пропустить"), repository)
    assert repository.training[779]["problem"]["problem_id"] != previous


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
    assert "Попыток: 2" in text
