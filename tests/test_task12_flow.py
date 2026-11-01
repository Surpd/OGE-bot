from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot.router import (
    choose_task6,
    choose_task9,
    choose_task12,
    continue_session,
    return_to_menu,
    show_progress,
    start,
    task6_answer,
    task9_answer,
    task12_answer,
    task12_callback,
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
    state = repository.training12[user_id]["state"]
    message.reply_to_message = SimpleNamespace(
        message_id=state.get("problem_prompt_message_id", state["input_prompt_message_id"])
    )
    return message


@pytest.mark.asyncio
async def test_task12_two_attempts_hints_solution_and_progress() -> None:
    repository = MemoryRepository()
    await choose_task12(_message(1001, "№12 · Формулы"), repository)
    saved = await repository.task12_state(1001)
    assert saved is not None and isinstance(saved["problem"], dict)
    problem = saved["problem"]
    problem_id = str(problem["problem_id"])
    assert await repository.task12_hint(1001, problem_id)
    first = _reply(repository, 1001, "0,999")
    await task12_answer(first, repository)
    assert "Попробуйте ещё раз" in first.answer.await_args.args[0]
    assert str(problem["correct_answer"]) not in first.answer.await_args.args[0]
    assert repository.training12[1001]["state"]["attempts"] == 1
    second = _reply(repository, 1001, str(problem["correct_answer"]))
    await task12_answer(second, repository)
    assert repository.training12[1001]["state"]["status"] == "solved"
    progress = await repository.task12_progress(1001)
    assert progress["correct"] == 1 and progress["attempts"] == 2
    assert progress["hints_used"] == 1


@pytest.mark.asyncio
async def test_task12_generated_content_is_labeled_as_an_analogue() -> None:
    repository = MemoryRepository()
    message = _message(1006, "№12 · Формулы")
    await choose_task12(message, repository)
    text = message.answer.await_args.args[0]
    assert "Тренировочный аналог" in text
    assert "не оригинальное опубликованное задание ОГЭ" in text
    saved = await repository.task12_state(1006)
    assert saved is not None
    assert saved["problem"]["content_provenance"] == "generated_analogue"


@pytest.mark.asyncio
async def test_task12_accepts_plain_answer_and_current_reply_on_second_attempt() -> None:
    repository = MemoryRepository()
    await choose_task12(_message(1005, "№12 · Формулы"), repository)
    saved = await repository.task12_state(1005)
    assert saved is not None
    prompt_id = int(saved["state"]["problem_prompt_message_id"])
    problem = saved["problem"]
    wrong = _message(1005, "0,999")
    wrong.reply_to_message = None
    await task12_answer(wrong, repository)
    assert repository.training12[1005]["state"]["attempts"] == 1
    assert "Попробуйте ещё раз" in wrong.answer.await_args.args[0]

    correct = _message(1005, str(problem["correct_answer"]))
    correct.reply_to_message = SimpleNamespace(message_id=prompt_id)
    await task12_answer(correct, repository)
    assert repository.training12[1005]["state"]["attempts"] == 2
    assert repository.training12[1005]["state"]["status"] == "solved"


@pytest.mark.asyncio
async def test_task12_rejects_reply_to_old_condition_after_advancing() -> None:
    repository = MemoryRepository()
    await choose_task12(_message(1006, "№12 · Формулы"), repository)
    old = await repository.task12_state(1006)
    assert old is not None
    old_id = str(old["problem"]["problem_id"])
    old_condition_id = int(old["state"]["problem_prompt_message_id"])
    await repository.task12_reveal_solution(1006, old_id)
    from app.math.oge12_scheduler import build_task12_candidate_batch

    candidates = build_task12_candidate_batch(
        {"recent_fingerprints": [old["problem"]["fingerprint"]]}, 88991
    )
    await repository.advance_task12_problem(
        1006, old_id, candidates, expected_screen="task12", skip_active=False
    )
    current = repository.training12[1006]
    await repository.set_task12_condition_message(
        1006, str(current["problem"]["problem_id"]), old_condition_id + 10
    )
    stale = _message(1006, "0,5")
    stale.reply_to_message = SimpleNamespace(message_id=old_condition_id)
    await task12_answer(stale, repository)
    assert current["state"]["attempts"] == 0
    assert "предыдущему" in stale.answer.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "choose", "answer"),
    [
        ("task6", choose_task6, task6_answer),
        ("task9", choose_task9, task9_answer),
        ("task12", choose_task12, task12_answer),
    ],
)
async def test_extra_text_after_solved_task_keeps_next_available(mode, choose, answer) -> None:
    repository = MemoryRepository()
    user_id = {"task6": 1011, "task9": 1012, "task12": 1013}[mode]
    await choose(_message(user_id, f"{mode}"), repository)
    state_method = getattr(repository, f"{mode}_state")
    state = await state_method(user_id)
    assert state is not None
    result = await state_method(user_id)
    assert result is not None
    correct = str(result["problem"]["correct_answer"])
    response = _message(user_id, correct)
    response.reply_to_message = None
    await answer(response, repository)
    solved = await state_method(user_id)
    assert solved is not None and solved["state"]["status"] == "solved"
    problem_id = solved["problem"]["problem_id"]

    extra = _message(user_id, "Спасибо, понял")
    await unknown_message(extra, repository)
    after = await state_method(user_id)
    assert await repository.user_state(user_id) == mode
    assert after is not None and after["problem"]["problem_id"] == problem_id
    assert "Следующее" in extra.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_task12_solution_viewed_is_not_scored_and_menu_resume_preserves_state() -> None:
    repository = MemoryRepository()
    await choose_task12(_message(1002, "№12 · Формулы"), repository)
    saved = await repository.task12_state(1002)
    assert saved is not None and isinstance(saved["problem"], dict)
    problem_id = str(saved["problem"]["problem_id"])
    callback = AsyncMock()
    callback.data = f"t12:solution:{problem_id}"
    callback.from_user = User(id=1002, is_bot=False, first_name="Student")
    callback.message = AsyncMock()
    callback.message.message_id = saved["state"]["input_prompt_message_id"]
    callback.message.answer.return_value.message_id = int(callback.message.message_id) + 2
    await task12_callback(callback, repository)
    assert repository.training12[1002]["state"]["status"] == "solution_viewed"
    assert (await repository.task12_progress(1002))["correct"] == 0
    next_callback = AsyncMock()
    next_callback.data = f"t12:next:{problem_id}"
    next_callback.from_user = User(id=1002, is_bot=False, first_name="Student")
    next_callback.message = AsyncMock()
    next_callback.message.message_id = repository.training12[1002]["state"][
        "input_prompt_message_id"
    ]
    next_callback.message.answer.return_value.message_id = int(next_callback.message.message_id) + 2
    await task12_callback(next_callback, repository)
    next_state = await repository.task12_state(1002)
    assert next_state is not None and isinstance(next_state["problem"], dict)
    next_problem = next_state["problem"]
    wrong = _reply(repository, 1002, "2")
    wrong.message_id = 890000
    await task12_answer(wrong, repository)
    attempts_before = repository.training12[1002]["state"]["attempts"]
    await return_to_menu(_message(1002, "↩ В меню"), repository)
    await start(_message(1002, "/start"), repository)
    await continue_session(_message(1002, "▶ Продолжить"), repository)
    resumed = await repository.task12_state(1002)
    assert resumed is not None and resumed["problem"]["problem_id"] == next_problem["problem_id"]
    assert resumed["state"]["attempts"] == attempts_before == 1
    assert await repository.user_state(1002) == "task12"


@pytest.mark.asyncio
async def test_task12_double_next_old_callback_and_stats_leave_only_latest_task_active() -> None:
    repository = MemoryRepository()
    await choose_task12(_message(1003, "№12 · Формулы"), repository)
    first_id = str(repository.training12[1003]["problem"]["problem_id"])
    await repository.task12_reveal_solution(1003, first_id)

    async def click_next(problem_id: str) -> None:
        callback = AsyncMock()
        callback.data = f"t12:next:{problem_id}"
        callback.from_user = User(id=1003, is_bot=False, first_name="Student")
        callback.message = AsyncMock()
        callback.message.message_id = repository.training12[1003]["state"][
            "input_prompt_message_id"
        ]
        callback.message.answer.return_value.message_id = int(callback.message.message_id) + 1
        await task12_callback(callback, repository)

    await click_next(first_id)
    second_id = str(repository.training12[1003]["problem"]["problem_id"])
    await click_next(first_id)
    assert str(repository.training12[1003]["problem"]["problem_id"]) == second_id
    assert len(repository.issued12[1003]) == 2
    await show_progress(_message(1003, "📊 Прогресс"), repository)
    stray = _message(1003, "0,5")
    await unknown_message(stray, repository)
    assert repository.training12[1003]["state"]["attempts"] == 0


@pytest.mark.asyncio
async def test_task12_sessions_are_independent_and_continue_uses_latest_mode() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(1004, "№6 · Вычисления"), repository)
    await choose_task9(_message(1004, "№9 · Уравнения"), repository)
    await choose_task12(_message(1004, "№12 · Формулы"), repository)
    assert repository.training.get(1004) is not None
    assert repository.training9.get(1004) is not None
    assert repository.training12.get(1004) is not None
    await return_to_menu(_message(1004, "↩ В меню"), repository)
    await continue_session(_message(1004, "▶ Продолжить"), repository)
    assert await repository.user_state(1004) == "task12"
