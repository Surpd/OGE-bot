from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot.router import (
    choose_task6,
    choose_task9,
    choose_task10,
    continue_session,
    return_to_menu,
    show_progress,
    start,
    task10_answer,
    task10_callback,
    unknown_message,
)
from app.persistence.repository import MemoryRepository

_message_id = 72000


def _message(user_id: int, text: str) -> AsyncMock:
    global _message_id
    value = _message_id
    _message_id += 2
    message = AsyncMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="Student")
    message.text = text
    message.message_id = value
    message.answer.return_value.message_id = value + 1
    return message


def _reply(repository: MemoryRepository, user_id: int, text: str) -> AsyncMock:
    message = _message(user_id, text)
    state = repository.training10[user_id]["state"]
    message.reply_to_message = SimpleNamespace(
        message_id=state.get("problem_prompt_message_id", state["input_prompt_message_id"])
    )
    return message


@pytest.mark.asyncio
async def test_task10_two_attempts_hints_solution_and_progress() -> None:
    repository = MemoryRepository()
    await choose_task10(_message(1001, "№10 · Вероятность"), repository)
    saved = await repository.task10_state(1001)
    assert saved is not None and isinstance(saved["problem"], dict)
    problem = saved["problem"]
    problem_id = str(problem["problem_id"])
    assert await repository.task10_hint(1001, problem_id)
    first = _reply(repository, 1001, "0,999")
    await task10_answer(first, repository)
    assert "Попробуйте ещё раз" in first.answer.await_args.args[0]
    assert str(problem["correct_answer"]) not in first.answer.await_args.args[0]
    assert repository.training10[1001]["state"]["attempts"] == 1
    second = _reply(repository, 1001, str(problem["correct_answer"]))
    await task10_answer(second, repository)
    assert repository.training10[1001]["state"]["status"] == "solved"
    progress = await repository.task10_progress(1001)
    assert progress["correct"] == 1 and progress["attempts"] == 2
    assert progress["hints_used"] == 1


@pytest.mark.asyncio
async def test_task10_answer_requires_reply_to_the_current_condition() -> None:
    repository = MemoryRepository()
    await choose_task10(_message(1005, "№10 · Вероятность"), repository)
    saved = await repository.task10_state(1005)
    assert saved is not None
    prompt_id = saved["state"]["problem_prompt_message_id"]
    message = _message(1005, "0,5")
    message.reply_to_message = None
    await task10_answer(message, repository)
    assert repository.training10[1005]["state"]["attempts"] == 0
    stale = _message(1005, "0,5")
    stale.reply_to_message = SimpleNamespace(message_id=int(prompt_id) - 1)
    await task10_answer(stale, repository)
    assert repository.training10[1005]["state"]["attempts"] == 0


@pytest.mark.asyncio
async def test_task10_solution_viewed_is_not_scored_and_menu_resume_preserves_state() -> None:
    repository = MemoryRepository()
    await choose_task10(_message(1002, "№10 · Вероятность"), repository)
    saved = await repository.task10_state(1002)
    assert saved is not None and isinstance(saved["problem"], dict)
    problem_id = str(saved["problem"]["problem_id"])
    callback = AsyncMock()
    callback.data = f"t10:solution:{problem_id}"
    callback.from_user = User(id=1002, is_bot=False, first_name="Student")
    callback.message = AsyncMock()
    callback.message.message_id = saved["state"]["input_prompt_message_id"]
    callback.message.answer.return_value.message_id = int(callback.message.message_id) + 2
    await task10_callback(callback, repository)
    assert repository.training10[1002]["state"]["status"] == "solution_viewed"
    assert (await repository.task10_progress(1002))["correct"] == 0
    next_callback = AsyncMock()
    next_callback.data = f"t10:next:{problem_id}"
    next_callback.from_user = User(id=1002, is_bot=False, first_name="Student")
    next_callback.message = AsyncMock()
    next_callback.message.message_id = repository.training10[1002]["state"][
        "input_prompt_message_id"
    ]
    next_callback.message.answer.return_value.message_id = int(next_callback.message.message_id) + 2
    await task10_callback(next_callback, repository)
    next_state = await repository.task10_state(1002)
    assert next_state is not None and isinstance(next_state["problem"], dict)
    next_problem = next_state["problem"]
    wrong = _reply(repository, 1002, "2")
    wrong.message_id = 890000
    await task10_answer(wrong, repository)
    attempts_before = repository.training10[1002]["state"]["attempts"]
    await return_to_menu(_message(1002, "↩ В меню"), repository)
    await start(_message(1002, "/start"), repository)
    await continue_session(_message(1002, "▶ Продолжить"), repository)
    resumed = await repository.task10_state(1002)
    assert resumed is not None and resumed["problem"]["problem_id"] == next_problem["problem_id"]
    assert resumed["state"]["attempts"] == attempts_before == 1
    assert await repository.user_state(1002) == "task10"


@pytest.mark.asyncio
async def test_task10_double_next_old_callback_and_stats_leave_only_latest_task_active() -> None:
    repository = MemoryRepository()
    await choose_task10(_message(1003, "№10 · Вероятность"), repository)
    first_id = str(repository.training10[1003]["problem"]["problem_id"])
    await repository.task10_reveal_solution(1003, first_id)

    async def click_next(problem_id: str) -> None:
        callback = AsyncMock()
        callback.data = f"t10:next:{problem_id}"
        callback.from_user = User(id=1003, is_bot=False, first_name="Student")
        callback.message = AsyncMock()
        callback.message.message_id = repository.training10[1003]["state"][
            "input_prompt_message_id"
        ]
        callback.message.answer.return_value.message_id = int(callback.message.message_id) + 1
        await task10_callback(callback, repository)

    await click_next(first_id)
    second_id = str(repository.training10[1003]["problem"]["problem_id"])
    await click_next(first_id)
    assert str(repository.training10[1003]["problem"]["problem_id"]) == second_id
    assert len(repository.issued10[1003]) == 2
    await show_progress(_message(1003, "📊 Прогресс"), repository)
    stray = _message(1003, "0,5")
    await unknown_message(stray, repository)
    assert repository.training10[1003]["state"]["attempts"] == 0


@pytest.mark.asyncio
async def test_task10_sessions_are_independent_and_continue_uses_latest_mode() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(1004, "№6 · Вычисления"), repository)
    await choose_task9(_message(1004, "№9 · Уравнения"), repository)
    await choose_task10(_message(1004, "№10 · Вероятность"), repository)
    assert repository.training.get(1004) is not None
    assert repository.training9.get(1004) is not None
    assert repository.training10.get(1004) is not None
    await return_to_menu(_message(1004, "↩ В меню"), repository)
    await continue_session(_message(1004, "▶ Продолжить"), repository)
    assert await repository.user_state(1004) == "task10"
