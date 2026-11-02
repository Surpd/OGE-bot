import os
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest
from aiogram.types import User

from app.bot.family_selection import family_keyboard, select_family
from app.bot.navigation import navigation_screen
from app.bot.training_engine import NUMERIC_TRAININGS, send_problem
from app.persistence.repository import MemoryRepository, PostgresRepository, read_migration


def message(user=123):
    result = AsyncMock()
    result.from_user = User(id=user, is_bot=False, first_name="Student")
    result.message_id = 100
    result.answer.return_value.message_id = 101
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("number", [8, 10, 12, 14])
async def test_family_choice_preserves_active_problem_and_applies_to_next(number):
    repository = MemoryRepository()
    adapter = NUMERIC_TRAININGS[number]
    first = message()
    assert await send_problem(adapter, first, repository, action="start")
    original = await adapter.operation(repository, "state")(123)
    chosen = adapter.families[-1]
    await select_family(first, repository, number, str(len(adapter.families) - 1))
    assert await repository.user_state(123) == f"family_selection:{number}"
    assert await adapter.operation(repository, "state")(123) == original
    assert await repository.training_family(123, number) == chosen
    assert await send_problem(adapter, first, repository, action="start")
    resumed = await adapter.operation(repository, "state")(123)
    assert resumed["problem"]["problem_id"] == original["problem"]["problem_id"]
    assert await send_problem(adapter, first, repository, action="advance", skip_active=True)
    subsequent = await adapter.operation(repository, "state")(123)
    assert subsequent["problem"]["family_id"] == chosen
    await select_family(first, repository, number, "random")
    assert await repository.training_family(123, number) is None


@pytest.mark.asyncio
async def test_invalid_family_index_never_overwrites_preference():
    repository = MemoryRepository()
    family = NUMERIC_TRAININGS[10].families[0]
    await repository.set_training_family(123, 10, family)
    for value in ("-1", "99999", "nope", "١"):
        await select_family(message(), repository, 10, value)
    assert await repository.training_family(123, 10) == family
    assert await repository.training_family(123, 12) is None


@pytest.mark.asyncio
async def test_selected_family_never_silently_falls_back():
    repository = MemoryRepository()
    family = NUMERIC_TRAININGS[10].families[0]
    await repository.set_training_family(123, 10, family)
    observed = []

    def wrong_family(state, seed):
        observed.append(state["family_queue"])
        return [{"family_id": "wrong"}]

    adapter = replace(NUMERIC_TRAININGS[10], candidates=wrong_family)
    outgoing = message()
    assert not await send_problem(adapter, outgoing, repository, action="start")
    assert observed == [[family]]
    state = await repository.task10_state(123)
    assert not state or not state.get("problem")
    assert await repository.user_state(123) == "family_selection:10"
    assert "Все типы" in outgoing.answer.await_args.args[0]


@pytest.mark.parametrize("number", [8, 10, 12, 14])
def test_family_keyboard_is_bound_and_only_lists_enabled_families(number):
    keyboard = family_keyboard(number)
    assert navigation_screen(keyboard) == f"family_selection:{number}"
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks == [
        f"nav:family:{number}:random",
        *[
            f"nav:family:{number}:{index}"
            for index in range(len(NUMERIC_TRAININGS[number].families))
        ],
        "nav:numbers",
    ]


@pytest.mark.asyncio
async def test_postgres_preferences_survive_repository_restart():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool = await asyncpg.create_pool(database_url)
    user_id = int(uuid4().int % (2**62)) + 1
    try:
        await pool.execute(await read_migration("migrations/0001_foundation.sql"))
        repository = PostgresRepository(pool)
        await repository.register_user(user_id)
        await repository.set_training_family(user_id, 10, "OGE10-test")
        await repository.set_training_family(user_id, 12, "OGE12-test")
        restarted = PostgresRepository(pool)
        assert await restarted.training_family(user_id, 10) == "OGE10-test"
        assert await restarted.training_family(user_id, 12) == "OGE12-test"
        await restarted.set_training_family(user_id, 10, None)
        assert await restarted.training_family(user_id, 10) is None
        assert await restarted.training_family(user_id, 12) == "OGE12-test"
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()
