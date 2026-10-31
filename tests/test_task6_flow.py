from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot.router import (
    choose_task6,
    continue_session,
    return_to_menu,
    show_progress,
    show_progress_details,
    start,
    task6_answer,
    task6_callback,
    task6_hint,
    task6_next,
    task6_skip,
    task6_solution,
    unknown_message,
)
from app.persistence.repository import MemoryRepository

_message_id = 1


def _message(user_id: int, text: str) -> AsyncMock:
    global _message_id
    incoming_id = _message_id
    bot_reply_id = _message_id + 1
    _message_id += 2
    message = AsyncMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="Student")
    message.text = text
    message.message_id = incoming_id
    message.answer.return_value.message_id = bot_reply_id
    return message


def _answer(repository: MemoryRepository, user_id: int, text: str) -> AsyncMock:
    message = _message(user_id, text)
    state = repository.training[user_id]["state"]
    message.reply_to_message = SimpleNamespace(
        message_id=state.get("problem_prompt_message_id", state["input_prompt_message_id"])
    )
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

    first = _answer(repository, 777, "999")
    await task6_answer(first, repository)
    first_feedback = first.answer.await_args.args[0]
    assert "Пока неверно" in first_feedback
    assert correct_answer not in first_feedback
    assert repository.training[777]["state"]["attempts"] == 1

    second = _answer(repository, 777, "999")
    await task6_answer(second, repository)
    second_feedback = second.answer.await_args.args[0]
    assert "Вторая попытка неверна" in second_feedback
    assert correct_answer in second_feedback
    assert repository.training[777]["state"]["attempts"] == 2


@pytest.mark.asyncio
async def test_task6_accepts_plain_numeric_message_without_reply() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(776, "№6 · Вычисления"), repository)
    state = await repository.task6_state(776)
    assert state is not None and isinstance(state["problem"], dict)
    answer = _message(776, str(state["problem"]["correct_answer"]))
    answer.reply_to_message = None
    await task6_answer(answer, repository)
    assert repository.training[776]["state"]["status"] == "solved"


@pytest.mark.asyncio
async def test_invalid_text_does_not_consume_a_task6_attempt() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(773, "№6 · Вычисления"), repository)
    invalid = _message(773, "не знаю")
    invalid.reply_to_message = None
    await task6_answer(invalid, repository)
    assert repository.training[773]["state"]["attempts"] == 0
    assert (await repository.task6_progress(773))["attempts"] == 0


@pytest.mark.asyncio
async def test_correct_answer_is_counted_once_and_next_issues_a_new_problem() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(778, "№6 · Вычисления"), repository)
    state = await repository.task6_state(778)
    assert state is not None
    problem = state["problem"]
    assert isinstance(problem, dict)
    answer = str(problem["correct_answer"])
    await task6_answer(_answer(repository, 778, answer), repository)
    assert repository.training[778]["state"]["status"] == "solved"
    attempts_after_correct = repository.training[778]["state"]["attempts"]
    await task6_answer(_answer(repository, 778, answer), repository)
    assert repository.training[778]["state"]["attempts"] == attempts_after_correct

    await task6_next(_message(778, "➡ Следующее"), repository)
    first_next = repository.training[778]["problem"]["problem_id"]
    await task6_next(_message(778, "➡ Следующее"), repository)
    assert repository.training[778]["problem"]["problem_id"] == first_next


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["next", "skip"])
async def test_repeated_old_transition_callback_does_not_advance_twice(action: str) -> None:
    repository = MemoryRepository()
    await choose_task6(_message(785, "№6 · Вычисления"), repository)
    first = repository.training[785]["problem"]
    first_id = str(first["problem_id"])

    async def tap(problem_id: str) -> None:
        if action == "next":
            await repository.task6_reveal_solution(785, problem_id)
        callback = AsyncMock()
        callback.data = f"t6:{action}:{problem_id}"
        callback.from_user = User(id=785, is_bot=False, first_name="Student")
        callback.message = AsyncMock()
        current = repository.training[785]
        callback.message.message_id = current["state"]["input_prompt_message_id"]
        callback.message.answer.return_value.message_id = int(callback.message.message_id) + 1
        await task6_callback(callback, repository)

    await tap(first_id)
    second_id = str(repository.training[785]["problem"]["problem_id"])
    assert second_id != first_id
    await tap(first_id)
    assert str(repository.training[785]["problem"]["problem_id"]) == second_id
    assert len(repository.issued_history[785]) == 2

    await tap(second_id)
    assert str(repository.training[785]["problem"]["problem_id"]) != second_id
    assert len(repository.issued_history[785]) == 3


@pytest.mark.asyncio
async def test_replayed_telegram_message_does_not_consume_second_attempt() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(783, "№6 · Вычисления"), repository)
    first = _answer(repository, 783, "999")
    first.message_id = 123456
    await task6_answer(first, repository)
    replay = _answer(repository, 783, "999")
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

    answer = _answer(repository, 784, str(state["problem"]["correct_answer"]))
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
    await task6_answer(_answer(repository, 781, correct_answer), repository)

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

    await task6_answer(_answer(repository, 782, "999"), repository)
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
async def test_paused_text_and_reply_to_old_task_cannot_consume_active_attempt() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(786, "№6 · Вычисления"), repository)
    original_problem_id = str(repository.training[786]["problem"]["problem_id"])
    original_prompt_id = repository.training[786]["state"]["input_prompt_message_id"]
    await task6_answer(_answer(repository, 786, "999"), repository)
    assert repository.training[786]["state"]["attempts"] == 1

    await return_to_menu(_message(786, "↩ В меню"), repository)
    await start(_message(786, "/start"), repository)
    paused_message = _message(786, "123")
    paused_message.reply_to_message = SimpleNamespace(message_id=original_prompt_id)
    await unknown_message(paused_message, repository)
    assert repository.training[786]["state"]["attempts"] == 1

    await continue_session(_message(786, "▶ Продолжить"), repository)
    resumed = await repository.task6_state(786)
    assert resumed is not None and isinstance(resumed["problem"], dict)
    assert resumed["problem"]["problem_id"] == original_problem_id
    assert repository.states[786] == "task6"
    new_prompt_id = resumed["state"]["input_prompt_message_id"]
    assert new_prompt_id != original_prompt_id

    stale_reply = _message(786, "999")
    stale_reply.reply_to_message = SimpleNamespace(message_id=original_prompt_id)
    await unknown_message(stale_reply, repository)
    assert repository.training[786]["state"]["attempts"] == 1
    assert "предыдущему заданию" in stale_reply.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_answer_transaction_rechecks_active_interface_and_prompt() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(788, "№6 · Вычисления"), repository)
    problem = repository.training[788]["problem"]
    prompt_id = repository.training[788]["state"]["input_prompt_message_id"]
    await repository.save_user_state(788, "main_menu")

    outcome = await repository.task6_attempt(
        788,
        str(problem["problem_id"]),
        str(problem["correct_answer"]),
        True,
        telegram_message_id=900_001,
        expected_prompt_message_id=prompt_id,
    )

    assert outcome == {"status": "stale", "attempt": 0}
    assert repository.training[788]["state"]["attempts"] == 0


@pytest.mark.asyncio
async def test_reply_to_previous_problem_is_rejected_after_next_callback() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(787, "№6 · Вычисления"), repository)
    old_prompt_id = repository.training[787]["state"]["input_prompt_message_id"]
    old_problem_id = str(repository.training[787]["problem"]["problem_id"])
    await repository.task6_reveal_solution(787, old_problem_id)

    callback = AsyncMock()
    callback.data = f"t6:next:{old_problem_id}"
    callback.from_user = User(id=787, is_bot=False, first_name="Student")
    callback.message = AsyncMock()
    callback.message.message_id = old_prompt_id
    callback.message.answer.return_value.message_id = _message(787, "new prompt").message_id
    await task6_callback(callback, repository)
    assert repository.training[787]["problem"]["problem_id"] != old_problem_id

    stale_reply = _message(787, "999")
    stale_reply.reply_to_message = SimpleNamespace(message_id=old_prompt_id)
    await unknown_message(stale_reply, repository)
    assert repository.training[787]["state"]["attempts"] == 0
    assert "предыдущему заданию" in stale_reply.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_progress_counts_issued_answered_solved_and_attempts() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(780, "№6 · Вычисления"), repository)
    state = await repository.task6_state(780)
    assert state is not None
    problem = state["problem"]
    assert isinstance(problem, dict)
    await task6_answer(_answer(repository, 780, "999"), repository)
    await task6_answer(_answer(repository, 780, str(problem["correct_answer"])), repository)

    progress_message = _message(780, "📊 Прогресс")
    await show_progress(progress_message, repository)
    text = progress_message.answer.await_args.args[0]
    assert "№6 · выдано 1" in text
    assert "отвечал 1" in text
    assert "решил 1" in text
    assert "правильно 100%" in text
    details = _message(780, "📊 Подробнее")
    await show_progress_details(details, repository)
    details_text = details.answer.await_args.args[0]
    assert "неверных попыток — 1" in details_text
    assert "правильно с первой попытки — 0" in details_text


@pytest.mark.asyncio
async def test_empty_progress_uses_zero_accuracy_without_division_error() -> None:
    repository = MemoryRepository()
    message = _message(772, "📊 Прогресс")
    await show_progress(message, repository)
    text = message.answer.await_args.args[0]
    assert "№6 · выдано 0 · отвечал 0" in text
    assert "№9 · выдано 0 · отвечал 0" in text
    assert text.count("правильно 0%") == 3


@pytest.mark.asyncio
async def test_progress_details_switches_screen_before_arbitrary_text() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(771, "№6 · Вычисления"), repository)

    await show_progress_details(_message(771, "📊 Подробнее"), repository)
    assert await repository.user_state(771) == "progress"

    random_text = _message(771, "случайный текст")
    await unknown_message(random_text, repository)
    assert (await repository.task6_progress(771))["attempts"] == 0
    assert repository.training[771]["state"]["attempts"] == 0


@pytest.mark.asyncio
async def test_active_and_completed_task6_buttons_are_distinct() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(775, "№6 · Вычисления"), repository)
    active_message = repository.training[775]["problem"]
    assert isinstance(active_message, dict)
    prompt = await repository.task6_state(775)
    assert prompt is not None and isinstance(prompt["problem"], dict)
    wrong = _answer(repository, 775, "999")
    await task6_answer(wrong, repository)
    active_keyboard = wrong.answer.await_args.kwargs["reply_markup"]
    assert {button.text for row in active_keyboard.inline_keyboard for button in row} == {
        "💡 Подсказка",
        "📘 Разбор",
        "⏭ Пропустить",
        "↩ В меню",
    }
    correct = _answer(repository, 775, str(prompt["problem"]["correct_answer"]))
    await task6_answer(correct, repository)
    completed_keyboard = correct.answer.await_args.kwargs["reply_markup"]
    assert {button.text for row in completed_keyboard.inline_keyboard for button in row} == {
        "➡ Следующее",
        "↩ В меню",
    }


@pytest.mark.asyncio
async def test_task6_skip_records_skipped_outcome() -> None:
    repository = MemoryRepository()
    await choose_task6(_message(774, "№6 · Вычисления"), repository)
    problem_id = str(repository.training[774]["problem"]["problem_id"])
    callback = AsyncMock()
    callback.data = f"t6:skip:{problem_id}"
    callback.from_user = User(id=774, is_bot=False, first_name="Student")
    callback.message = AsyncMock()
    callback.message.message_id = repository.training[774]["state"]["input_prompt_message_id"]
    callback.message.answer.return_value.message_id = callback.message.message_id + 1
    await task6_callback(callback, repository)
    assert repository.outcomes[774][problem_id] == "skipped"
