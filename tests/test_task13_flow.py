from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot.menu import number_menu, task13_menu
from app.bot.router import choose_task13, continue_session, task13_callback
from app.math import inequalities, oge13_scheduler
from app.math.inequalities import render_option_sheet_snapshot_png
from app.persistence.repository import MemoryRepository


@pytest.fixture(autouse=True)
def restore_task13_enabled_families():
    original = oge13_scheduler.ENABLED_FAMILIES
    yield
    oge13_scheduler.ENABLED_FAMILIES = original


def _message(user_id: int, text: str = "№13") -> AsyncMock:
    message = AsyncMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="Student")
    message.text = text
    message.message_id = 90_000 + user_id % 1000
    message.reply_to_message = None
    message.answer.return_value.message_id = message.message_id + 1
    message.answer_photo.return_value.message_id = message.message_id + 1
    return message


def _callback(
    user_id: int,
    action: str,
    problem_id: str,
    message_id: int,
    callback_id: str,
) -> AsyncMock:
    callback = AsyncMock()
    callback.id = callback_id
    callback.data = f"t13:{action}:{problem_id}"
    callback.from_user = User(id=user_id, is_bot=False, first_name="Student")
    callback.message = _message(user_id)
    callback.message.message_id = message_id
    callback.message.answer.return_value.message_id = message_id + 1
    return callback


def test_disabled_task13_is_hidden_from_number_menu() -> None:
    oge13_scheduler.ENABLED_FAMILIES = ()
    labels = [button.text for row in number_menu().keyboard for button in row]
    assert not any(label and label.startswith("№13") for label in labels)
    assert any(label and label.startswith("№8") for label in labels)


@pytest.mark.asyncio
async def test_disabled_task13_families_are_not_issued_to_students() -> None:
    repository = MemoryRepository()
    message = _message(913_000)

    await choose_task13(message, repository)

    message.answer.assert_awaited_once()
    assert "пока выключены" in message.answer.await_args.args[0]
    state = await repository.task13_state(913_000)
    assert state is not None and state.get("problem") is None


@pytest.mark.asyncio
async def test_graph_choices_render_saved_snapshot_and_duplicate_choice_is_idempotent(
    monkeypatch,
) -> None:
    oge13_scheduler.ENABLED_FAMILIES = ("OGE13-Q04",)
    repository = MemoryRepository()
    user_id = 913_001
    message = _message(user_id)

    await choose_task13(message, repository)
    state = await repository.task13_state(user_id)
    assert state is not None and isinstance(state.get("problem"), dict)
    problem = state["problem"]
    assert problem["family_id"] == "OGE13-Q04"
    message.answer_photo.assert_awaited_once()
    assert b"PNG" in message.answer_photo.await_args.args[0].data[1:4]
    original_png = message.answer_photo.await_args.args[0].data
    assert original_png == render_option_sheet_snapshot_png(problem)

    def fail_if_regenerated(*_args, **_kwargs):
        pytest.fail("A persisted task must be rendered from its stored options")

    monkeypatch.setattr(inequalities, "generate", fail_if_regenerated)
    resumed_message = _message(user_id)
    await continue_session(resumed_message, repository)
    resumed_message.answer_photo.assert_awaited_once()
    assert resumed_message.answer_photo.await_args.args[0].data == original_png

    markup = task13_menu(str(problem["problem_id"]), choices=True)
    assert [button.text for button in markup.inline_keyboard[0]] == ["1", "2", "3", "4"]
    control_id = int(state["state"]["input_prompt_message_id"])
    choice = "1"
    first = _callback(
        user_id,
        "choose",
        str(problem["problem_id"]),
        control_id,
        "callback-stable-1",
    )
    first.data = f"t13:choose:{problem['problem_id']}:{choice}"
    await task13_callback(first, repository)
    after_first = await repository.task13_state(user_id)
    assert after_first is not None and after_first["state"]["attempts"] == 1

    # Telegram can redeliver a callback update; it must not spend a second attempt.
    await task13_callback(first, repository)
    after_duplicate = await repository.task13_state(user_id)
    assert after_duplicate is not None and after_duplicate["state"]["attempts"] == 1


@pytest.mark.asyncio
async def test_task13_pause_keeps_problem_and_other_number_sessions_independent() -> None:
    oge13_scheduler.ENABLED_FAMILIES = ("OGE13-L01",)
    repository = MemoryRepository()
    user_id = 913_002
    await repository.ensure_task6_session(user_id)
    await repository.save_user_state(user_id, "task6")
    task6_id = "task6-kept"
    repository.training[user_id] = {
        "session_id": "memory6",
        "problem": {"problem_id": task6_id, "condition": "fixture"},
        "state": {"status": "active", "attempts": 1},
    }

    await choose_task13(_message(user_id), repository)
    state = await repository.task13_state(user_id)
    assert state is not None and isinstance(state.get("problem"), dict)
    problem_id = str(state["problem"]["problem_id"])
    control_id = int(state["state"]["input_prompt_message_id"])
    menu = _callback(user_id, "menu", problem_id, control_id, "callback-menu-13")
    menu.data = f"t13:menu:{problem_id}"
    await task13_callback(menu, repository)

    paused = await repository.task13_state(user_id)
    assert paused is not None and paused["problem"]["problem_id"] == problem_id
    assert paused["state"]["attempts"] == 0
    assert await repository.user_state(user_id) == "main_menu"
    assert (await repository.task6_state(user_id))["problem"]["problem_id"] == task6_id


@pytest.mark.asyncio
async def test_text_options_still_offer_inline_choices_without_png() -> None:
    oge13_scheduler.ENABLED_FAMILIES = ("OGE13-L01",)
    repository = MemoryRepository()
    user_id = 913_003
    message = _message(user_id)

    await choose_task13(message, repository)
    state = await repository.task13_state(user_id)
    assert state is not None and isinstance(state.get("problem"), dict)
    problem = state["problem"]
    assert problem["family_id"] == "OGE13-L01"
    message.answer.assert_awaited_once()
    message.answer_photo.assert_not_awaited()
    assert "1." in message.answer.await_args.args[0]
    assert "4." in message.answer.await_args.args[0]
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert [button.text for button in markup.inline_keyboard[0]] == ["1", "2", "3", "4"]

    control_id = int(state["state"]["input_prompt_message_id"])
    choice = _callback(
        user_id,
        "choose",
        str(problem["problem_id"]),
        control_id,
        "callback-text-choice-1",
    )
    choice.data = f"t13:choose:{problem['problem_id']}:1"
    await task13_callback(choice, repository)
    after = await repository.task13_state(user_id)
    assert after is not None and after["state"]["attempts"] == 1
