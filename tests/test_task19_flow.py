from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from app.bot import router
from app.bot.family_selection import family_keyboard, select_family
from app.math import oge19_scheduler
from app.math.oge19_scheduler import FAMILY_THEMES
from app.persistence.repository import MemoryRepository


def incoming(text: str = "", message_id: int = 100):
    message = AsyncMock()
    message.from_user = User(id=419, is_bot=False, first_name="Student")
    message.message_id = message_id
    message.text = text
    message.reply_to_message = None
    message.answer.return_value.message_id = message_id + 1
    return message


@pytest.fixture
def enabled_task19(monkeypatch):
    monkeypatch.setattr(oge19_scheduler, "ENABLED_FAMILIES", tuple(FAMILY_THEMES))


@pytest.mark.asyncio
async def test_task19_is_one_number_entry_with_compact_theme_selector(enabled_task19):
    menu = incoming()
    await router.choose_number(menu, MemoryRepository())
    labels = [
        button.text
        for row in menu.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert labels.count("№19 · Геометрические утверждения") == 1
    selector = family_keyboard(19)
    theme_labels = [button.text for row in selector.inline_keyboard for button in row]
    assert len(theme_labels) == 7  # all themes, five topic groups, and back
    assert theme_labels[0] == "🎲 Все темы"
    assert "Окружности" in theme_labels


@pytest.mark.asyncio
async def test_closed_public_gate_hides_task19_and_rejects_direct_callback(monkeypatch):
    monkeypatch.setattr(oge19_scheduler, "ENABLED_FAMILIES", ())
    repo = MemoryRepository()
    menu = incoming()
    await router.choose_number(menu, repo)
    labels = [
        button.text
        for row in menu.answer.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "№19 · Геометрические утверждения" not in labels

    callback = AsyncMock()
    callback.data = "t19:hint:00000000-0000-0000-0000-000000000001"
    callback.from_user = User(id=419, is_bot=False, first_name="Student")
    callback.message = incoming(message_id=101)
    await router.task19_callback(callback, repo)
    callback.answer.assert_awaited_once()
    assert "выключены" in callback.answer.await_args.args[0]
    assert await repo.task19_state(419) is None


@pytest.mark.asyncio
async def test_first_task19_entry_offers_the_all_themes_path(enabled_task19):
    repo = MemoryRepository()
    chooser = incoming()
    await router.choose_task19(chooser, repo)
    assert (await repo.task19_state(419)) is None
    await select_family(incoming(message_id=102), repo, 19, "random")
    assert await repo.training_family(419, 19) == "OGE19-MIXED"
    await router.choose_task19(incoming(message_id=104), repo)
    assert (await repo.task19_state(419))["problem"]["family_id"] == "OGE19-MIXED"


@pytest.mark.asyncio
async def test_task19_accepts_two_tries_and_ignores_malformed_input(enabled_task19):
    repo = MemoryRepository()
    await repo.set_training_family(419, 19, "OGE19-MIXED")
    prompt = incoming()
    await router.choose_task19(prompt, repo)
    saved = await repo.task19_state(419)
    problem = saved["problem"]
    assert "Какое из следующих утверждений является истинным высказыванием?" in problem["condition"]
    assert len(problem["condition"].splitlines()) >= 5
    assert problem["correct_answer"] in {"1", "2", "3"}

    await router.task19_answer(incoming("4", 102), repo)
    assert (await repo.task19_state(419))["state"]["attempts"] == 0
    wrong = "1" if problem["correct_answer"] != "1" else "2"
    await router.task19_answer(incoming(wrong, 103), repo)
    assert (await repo.task19_state(419))["state"]["attempts"] == 1
    await router.task19_answer(incoming(problem["correct_answer"], 104), repo)
    assert (await repo.task19_state(419))["state"]["status"] == "solved"
    assert (await repo.task19_progress(419))["correct"] == 1


@pytest.mark.asyncio
async def test_task19_hint_skip_resume_and_theme_are_persisted(enabled_task19):
    repo = MemoryRepository()
    await repo.set_training_family(419, 19, "OGE19-CIRCLES")
    prompt = incoming()
    await router.choose_task19(prompt, repo)
    saved = await repo.task19_state(419)
    first = saved["problem"]
    assert first["family_id"] == "OGE19-CIRCLES"
    assert all(item["topic"] in {"circles", "tangency"} for item in first["statements"])

    callback = AsyncMock()
    callback.data = f"t19:hint:{first['problem_id']}"
    callback.from_user = User(id=419, is_bot=False, first_name="Student")
    callback.message = AsyncMock()
    callback.message.message_id = 101
    await router.task19_callback(callback, repo)
    assert (await repo.task19_state(419))["state"]["attempts"] == 0
    hint_text = callback.message.answer.await_args.args[0]
    assert first["correct_answer"] not in hint_text

    await repo.save_user_state(419, "main_menu")
    resumed = incoming(message_id=106)
    await router.continue_session(resumed, repo)
    assert (await repo.task19_state(419))["problem"]["condition"] == first["condition"]

    callback = AsyncMock()
    callback.data = f"t19:skip:{first['problem_id']}"
    callback.from_user = User(id=419, is_bot=False, first_name="Student")
    callback.message = incoming(message_id=107)
    callback.message.message_id = 107
    await router.task19_callback(callback, repo)
    next_problem = (await repo.task19_state(419))["problem"]
    assert next_problem["family_id"] == "OGE19-CIRCLES"
    assert next_problem["problem_id"] != first["problem_id"]
    stale = AsyncMock()
    stale.data = f"t19:hint:{first['problem_id']}"
    stale.from_user = User(id=419, is_bot=False, first_name="Student")
    stale.message = AsyncMock()
    stale.message.message_id = 109
    await router.task19_callback(stale, repo)
    assert (await repo.task19_state(419))["problem"]["problem_id"] == next_problem["problem_id"]
    assert (await repo.task19_state(419))["state"]["hints_used"] == 0


@pytest.mark.asyncio
async def test_task19_restart_and_duplicate_answer_webhook(enabled_task19):
    repo = MemoryRepository()
    await repo.set_training_family(419, 19, "OGE19-MIXED")
    opened = incoming()
    await router.choose_task19(opened, repo)
    first = (await repo.task19_state(419))["problem"]
    wrong = "1" if first["correct_answer"] != "1" else "2"
    duplicate = incoming(wrong, 102)
    await router.task19_answer(duplicate, repo)
    await router.task19_answer(duplicate, repo)
    assert (await repo.task19_state(419))["state"]["attempts"] == 1

    await repo.save_user_state(419, "number_selection")
    await router.saved_training_navigation(
        incoming(message_id=105), repo, 419, "confirm", 19, first["problem_id"]
    )
    restarted = (await repo.task19_state(419))["problem"]
    assert restarted["problem_id"] != first["problem_id"]
    assert (await repo.task19_state(419))["state"]["attempts"] == 0


@pytest.mark.asyncio
async def test_task19_second_wrong_answer_reveals_each_statement_reason(enabled_task19):
    repo = MemoryRepository()
    await repo.set_training_family(419, 19, "OGE19-MIXED")
    await router.choose_task19(incoming(), repo)
    problem = (await repo.task19_state(419))["problem"]
    wrong = "1" if problem["correct_answer"] != "1" else "2"
    await router.task19_answer(incoming(wrong, 102), repo)
    second = incoming(wrong, 103)
    await router.task19_answer(second, repo)
    assert (await repo.task19_state(419))["state"]["status"] == "failed"
    output = second.answer.await_args.args[0]
    for index, statement in enumerate(problem["statements"], 1):
        assert f"{index}." in output
        assert statement["explanation"] in output
