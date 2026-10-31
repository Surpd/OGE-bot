from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot.router import (
    choose_task9,
    continue_session,
    return_to_menu,
    start,
    task9_answer,
    task9_callback,
)
from app.persistence.repository import MemoryRepository

_message_id = 51000


def _message(user_id: int, text: str) -> AsyncMock:
    global _message_id
    incoming = _message_id
    _message_id += 2
    message = AsyncMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="Student")
    message.text = text
    message.message_id = incoming
    message.answer.return_value.message_id = incoming + 1
    return message


def _reply(repository: MemoryRepository, user_id: int, text: str) -> AsyncMock:
    message = _message(user_id, text)
    state = repository.training9[user_id]["state"]
    message.reply_to_message = SimpleNamespace(message_id=state["input_prompt_message_id"])
    return message


@pytest.mark.asyncio
async def test_task9_two_attempts_solution_hints_and_progress_are_separate_from_task6() -> None:
    repository = MemoryRepository()
    await choose_task9(_message(901, "№9 · Уравнения"), repository)
    state = await repository.task9_state(901)
    assert state is not None and isinstance(state["problem"], dict)
    problem = state["problem"]
    assert str(problem["family_id"]).startswith("OGE09-")

    await repository.task9_hint(901, str(problem["problem_id"]))
    wrong = _reply(repository, 901, "999")
    wrong.message_id = 61001
    await task9_answer(wrong, repository)
    assert "ответ не раскрываю" in wrong.answer.await_args.args[0]
    assert repository.training9[901]["state"]["attempts"] == 1
    assert repository.training.get(901) is None

    duplicate = _reply(repository, 901, "999")
    duplicate.message_id = 61001
    await task9_answer(duplicate, repository)
    assert "уже было обработано" in duplicate.answer.await_args.args[0]

    await repository.task9_reveal_solution(901, str(problem["problem_id"]))
    attempt = _reply(repository, 901, str(problem["correct_answer"]))
    await task9_answer(attempt, repository)
    assert repository.training9[901]["state"]["attempts"] == 1
    progress = await repository.task9_progress(901)
    assert progress["correct"] == 0
    assert progress["attempts"] == 1
    assert progress["hints_used"] == 1


@pytest.mark.asyncio
async def test_task9_pause_resume_and_old_prompt_reply_are_safe() -> None:
    repository = MemoryRepository()
    await choose_task9(_message(902, "№9 · Уравнения"), repository)
    initial = await repository.task9_state(902)
    assert initial is not None and isinstance(initial["problem"], dict)
    problem_id = str(initial["problem"]["problem_id"])
    old_prompt = initial["state"]["input_prompt_message_id"]
    first = _reply(repository, 902, "999")
    await task9_answer(first, repository)
    await return_to_menu(_message(902, "↩ В меню"), repository)
    await start(_message(902, "/start"), repository)
    await continue_session(_message(902, "▶ Продолжить"), repository)
    resumed = await repository.task9_state(902)
    assert resumed is not None and isinstance(resumed["problem"], dict)
    assert resumed["problem"]["problem_id"] == problem_id
    assert resumed["state"]["attempts"] == 1
    assert resumed["state"]["input_prompt_message_id"] != old_prompt

    stale = _message(902, "999")
    stale.reply_to_message = SimpleNamespace(message_id=old_prompt)
    await task9_answer(stale, repository)
    assert repository.training9[902]["state"]["attempts"] == 1
    assert "реплаем" in stale.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_old_callback_and_double_next_do_not_skip_multiple_problems() -> None:
    repository = MemoryRepository()
    await choose_task9(_message(903, "№9 · Уравнения"), repository)
    first_id = str(repository.training9[903]["problem"]["problem_id"])

    async def click(problem_id: str) -> None:
        callback = AsyncMock()
        callback.data = f"t9:next:{problem_id}"
        callback.from_user = User(id=903, is_bot=False, first_name="Student")
        callback.message = AsyncMock()
        callback.message.answer.return_value.message_id = _message(903, "new prompt").message_id
        await task9_callback(callback, repository)

    await click(first_id)
    second_id = str(repository.training9[903]["problem"]["problem_id"])
    assert second_id != first_id
    await click(first_id)
    assert str(repository.training9[903]["problem"]["problem_id"]) == second_id
    assert len(repository.issued9[903]) == 2


@pytest.mark.asyncio
async def test_task9_wrong_first_answer_does_not_show_correct_value() -> None:
    repository = MemoryRepository()
    await choose_task9(_message(904, "№9 · Уравнения"), repository)
    message = _reply(repository, 904, "999")
    await task9_answer(message, repository)
    feedback = message.answer.await_args.args[0]
    correct = str(repository.training9[904]["problem"]["correct_answer"])
    assert "не раскрываю" in feedback
    assert correct not in feedback
