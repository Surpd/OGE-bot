import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot.router import choose_task6, choose_task9, task6_answer, task9_answer
from app.persistence.repository import MemoryRepository


@pytest.mark.parametrize("task_number", [6, 9])
@pytest.mark.asyncio
async def test_late_wrong_feedback_cannot_replace_solved_keyboard(task_number: int) -> None:
    repository = MemoryRepository()
    user_id = 9100 + task_number
    start = AsyncMock()
    start.from_user = User(id=user_id, is_bot=False, first_name="Student")
    start.text = f"№{task_number}"
    start.answer.return_value.message_id = 80_000
    if task_number == 6:
        await choose_task6(start, repository)
        state = await repository.task6_state(user_id)
    else:
        await choose_task9(start, repository)
        state = await repository.task9_state(user_id)
    assert state is not None and isinstance(state["problem"], dict)
    problem = state["problem"]
    condition_id = state["state"]["problem_prompt_message_id"]
    correct_answer = str(problem["correct_answer"])
    wrong_answer = "999999999999999"
    assert wrong_answer != correct_answer

    feedback_started = asyncio.Event()
    release_feedback = asyncio.Event()
    stale_feedback = SimpleNamespace(message_id=80_005, edit_reply_markup=AsyncMock())
    incorrect = AsyncMock()
    incorrect.from_user = User(id=user_id, is_bot=False, first_name="Student")
    incorrect.text = wrong_answer
    incorrect.message_id = 80_001
    incorrect.reply_to_message = SimpleNamespace(message_id=condition_id)

    async def delay_wrong_feedback(*args: object, **kwargs: object) -> object:
        feedback_started.set()
        await release_feedback.wait()
        return stale_feedback

    incorrect.answer.side_effect = delay_wrong_feedback
    correct = AsyncMock()
    correct.from_user = User(id=user_id, is_bot=False, first_name="Student")
    correct.text = correct_answer
    correct.message_id = 80_002
    correct.reply_to_message = SimpleNamespace(message_id=condition_id)
    solved_feedback = SimpleNamespace(message_id=80_004, edit_reply_markup=AsyncMock())
    correct.answer.return_value = solved_feedback

    first_handler = asyncio.create_task(
        task6_answer(incorrect, repository)
        if task_number == 6
        else task9_answer(incorrect, repository)
    )
    await feedback_started.wait()
    if task_number == 6:
        await task6_answer(correct, repository)
        final_state = await repository.task6_state(user_id)
    else:
        await task9_answer(correct, repository)
        final_state = await repository.task9_state(user_id)
    assert final_state is not None
    assert final_state["state"]["status"] == "solved"
    assert final_state["state"]["input_prompt_message_id"] == solved_feedback.message_id
    next_keyboard = correct.answer.await_args.kwargs["reply_markup"]
    assert next_keyboard.inline_keyboard[0][0].text == "➡ Следующее"

    release_feedback.set()
    await first_handler
    stale_feedback.edit_reply_markup.assert_awaited_once_with(reply_markup=None)

