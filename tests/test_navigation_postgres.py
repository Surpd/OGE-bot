"""Navigation claim concurrency/persistence on PostgreSQL; never use app credentials here."""
import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from aiogram.types import User

from app.bot import router
from app.bot.router import (
    _has_resumable_session,
    choose_task6,
    choose_task9,
    choose_task12,
    continue_session,
    return_to_menu,
    start,
    task6_next,
    task12_callback,
)
from app.math.oge07_scheduler import build_task7_candidate_batch
from app.persistence.repository import PostgresRepository, read_migration

_telegram_message_id = 88000


def telegram_message(user_id: int, text: str) -> AsyncMock:
    global _telegram_message_id
    message_id = _telegram_message_id
    _telegram_message_id += 2
    message = AsyncMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="Integration")
    message.text = text
    message.message_id = message_id
    message.answer.return_value.message_id = message_id + 1
    return message


@pytest_asyncio.fixture
async def navigation_pool() -> AsyncIterator[asyncpg.Pool]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    connection = await asyncpg.connect(database_url)
    # A private test schema prevents migrations and cleanup touching application tables.
    schema = f"test_navigation_{uuid4().hex}"
    pool = None
    try:
        version = int(await connection.fetchval("SHOW server_version_num"))
        assert version >= 170000, "Navigation integration requires PostgreSQL 17 or later"
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        pool = await asyncpg.create_pool(
            database_url, min_size=1, max_size=5,
            server_settings={"search_path": f'"{schema}", public'},
        )
        for migration in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(await read_migration(str(migration)))
        yield pool
    finally:
        if pool is not None:
            await pool.close()
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()


async def register(pool: asyncpg.Pool) -> tuple[PostgresRepository, int]:
    repository = PostgresRepository(pool)
    user_id = int(uuid4().int % (2**62)) + 1
    await repository.register_user(user_id)
    await repository.save_user_state(user_id, "main_menu")
    return repository, user_id


@pytest.mark.asyncio
async def test_postgres_rejects_stale_navigation_on_the_same_screen(navigation_pool):
    repository, user_id = await register(navigation_pool)
    assert await repository.set_navigation_message(user_id, "main_menu", 100)
    assert await repository.set_navigation_message(user_id, "main_menu", 101)
    assert not await repository.claim_navigation_message(user_id, 100)
    assert not await repository.set_navigation_message(user_id, "progress", 102)
    assert await repository.claim_navigation_message(user_id, 101)
    assert not await repository.claim_navigation_message(user_id, 101)
    # Editing an existing menu keeps its Telegram ID. Only its current
    # keyboard revision may change the screen.
    assert await repository.set_navigation_message(user_id, "main_menu", 101, "old")
    assert await repository.claim_navigation_message(user_id, 101, "old")
    assert await repository.set_navigation_message(user_id, "main_menu", 101, "new")
    assert not await repository.claim_navigation_message(user_id, 101, "old")
    assert not await repository.claim_navigation_message(user_id, 101)
    assert await repository.claim_navigation_message(user_id, 101, "new")


@pytest.mark.asyncio
async def test_postgres_concurrent_duplicate_claims_have_one_winner(navigation_pool):
    repository, user_id = await register(navigation_pool)
    assert await repository.set_navigation_message(user_id, "main_menu", 200)
    results = await asyncio.gather(*(
        PostgresRepository(navigation_pool).claim_navigation_message(user_id, 200)
        for _ in range(12)
    ))
    assert results.count(True) == 1
    assert results.count(False) == 11


@pytest.mark.asyncio
async def test_postgres_navigation_survives_repository_restart_and_is_user_scoped(navigation_pool):
    repository, user_id = await register(navigation_pool)
    other_repository, other_user_id = await register(navigation_pool)
    assert await repository.set_navigation_message(user_id, "main_menu", 300)
    assert await other_repository.set_navigation_message(other_user_id, "main_menu", 301)
    restarted = PostgresRepository(navigation_pool)
    assert await restarted.math_display(user_id) == "auto"
    await repository.set_math_display(user_id, "png")
    assert await restarted.math_display(user_id) == "png"
    assert await restarted.math_display(other_user_id) == "auto"
    assert not await restarted.claim_navigation_message(other_user_id, 300)
    assert await restarted.claim_navigation_message(user_id, 300)
    assert await restarted.claim_navigation_message(other_user_id, 301)


@pytest.mark.asyncio
async def test_postgres_last_used_training_survives_navigation_and_repository_restart(
    navigation_pool,
):
    repository, user_id = await register(navigation_pool)
    await repository.save_user_state(user_id, "task9")
    await repository.save_user_state(user_id, "number_selection")
    await repository.save_user_state(user_id, "display_settings")
    restarted = PostgresRepository(navigation_pool)
    assert await restarted.last_training_mode(user_id) == "task9"
    await restarted.save_user_state(user_id, "task12")
    await restarted.save_user_state(user_id, "main_menu")
    final_repository = PostgresRepository(navigation_pool)
    assert await final_repository.last_training_mode(user_id) == "task12"


@pytest.mark.parametrize("number", range(6, 15))
@pytest.mark.asyncio
async def test_postgres_entering_training_invalidates_old_navigation(navigation_pool, number):
    repository, user_id = await register(navigation_pool)
    assert await repository.set_navigation_message(user_id, "main_menu", 400)
    await repository.save_user_state(user_id, f"task{number}")
    assert not await PostgresRepository(navigation_pool).claim_navigation_message(user_id, 400)
    assert not await repository.set_navigation_message(user_id, "main_menu", 401)
    state = await navigation_pool.fetchval(
        "SELECT current_state->>'screen' FROM users WHERE telegram_user_id=$1", user_id)
    assert state == f"task{number}"


@pytest.mark.asyncio
async def test_postgres_existing_migration_chain_is_idempotent_and_preserves_data(navigation_pool):
    repository, user_id = await register(navigation_pool)
    assert await repository.set_navigation_message(user_id, "main_menu", 500)
    before = await navigation_pool.fetchrow(
        "SELECT id, current_state, preferences, created_at FROM users WHERE telegram_user_id=$1",
        user_id,
    )
    # The fixture already applied every migration once. Reapply the exact existing chain.
    for migration in sorted(Path("migrations").glob("*.sql")):
        await navigation_pool.execute(await read_migration(str(migration)))
    after = await navigation_pool.fetchrow(
        "SELECT id, current_state, preferences, created_at FROM users WHERE telegram_user_id=$1",
        user_id,
    )
    assert after == before
    assert await PostgresRepository(navigation_pool).claim_navigation_message(user_id, 500)


@pytest.mark.parametrize("terminal", [False, True], ids=["active", "terminal"])
@pytest.mark.asyncio
async def test_postgres_global_continue_selects_latest_task_and_advances_once(
    navigation_pool, terminal: bool
):
    repository, user_id = await register(navigation_pool)
    await choose_task9(telegram_message(user_id, "№9 · Уравнения"), repository)
    task9_before = await repository.task9_state(user_id)
    assert task9_before is not None and isinstance(task9_before["problem"], dict)
    task9_problem_id = str(task9_before["problem"]["problem_id"])

    await choose_task12(telegram_message(user_id, "№12 · Формулы"), repository)
    task12_before = await repository.task12_state(user_id)
    assert task12_before is not None and isinstance(task12_before["problem"], dict)
    task12_problem_id = str(task12_before["problem"]["problem_id"])
    if terminal:
        assert await repository.task12_reveal_solution(user_id, task12_problem_id)
        old_prompt_id = int(task12_before["state"]["input_prompt_message_id"])

    # Leaving for a menu and constructing a fresh repository must preserve the
    # selected training and the exact problem/snapshot in PostgreSQL.
    await return_to_menu(telegram_message(user_id, "↩ В меню"), repository)
    restarted = PostgresRepository(navigation_pool)
    assert await restarted.last_training_mode(user_id) == "task12"
    before_progress = await restarted.task12_progress(user_id)
    if terminal:
        await asyncio.gather(
            continue_session(telegram_message(user_id, "▶ Продолжить"), restarted),
            continue_session(telegram_message(user_id, "▶ Продолжить"), restarted),
        )
    else:
        await continue_session(telegram_message(user_id, "▶ Продолжить"), restarted)

    after_continue = await restarted.task12_state(user_id)
    assert after_continue is not None and isinstance(after_continue["problem"], dict)
    if terminal:
        next_problem_id = str(after_continue["problem"]["problem_id"])
        assert next_problem_id != task12_problem_id
        assert after_continue["state"]["status"] == "active"
        after_progress = await restarted.task12_progress(user_id)
        assert after_progress["issued"] == before_progress["issued"] + 1
        assert after_progress["solutions_viewed"] == before_progress["solutions_viewed"]
        stale_callback = AsyncMock()
        stale_callback.data = f"t12:next:{task12_problem_id}"
        stale_callback.from_user = User(id=user_id, is_bot=False, first_name="Integration")
        stale_callback.message = AsyncMock()
        stale_callback.message.message_id = old_prompt_id
        stale_callback.message.answer.return_value.message_id = old_prompt_id + 2
        await task12_callback(stale_callback, restarted)
        await task12_callback(stale_callback, restarted)
        after_stale_callbacks = await restarted.task12_state(user_id)
        assert after_stale_callbacks is not None
        assert after_stale_callbacks["problem"]["problem_id"] == next_problem_id
        assert (await restarted.task12_progress(user_id))["issued"] == after_progress["issued"]
        # A second Continue while the new problem is active restores it rather
        # than issuing another one.
        await return_to_menu(telegram_message(user_id, "↩ В меню"), restarted)
        await continue_session(telegram_message(user_id, "▶ Продолжить"), restarted)
        repeated = await restarted.task12_state(user_id)
        assert repeated is not None and repeated["problem"]["problem_id"] == next_problem_id
        assert (await restarted.task12_progress(user_id))["issued"] == after_progress["issued"]
    else:
        assert after_continue["problem"]["problem_id"] == task12_problem_id
        assert after_continue["state"]["status"] == "active"
        assert after_continue["state"]["attempts"] == task12_before["state"]["attempts"]
        assert (await restarted.task12_progress(user_id))["issued"] == before_progress["issued"]

    # Switching to #12 never overwrites the saved #9 problem or its outcome.
    task9_after = await restarted.task9_state(user_id)
    assert task9_after is not None and task9_after["problem"]["problem_id"] == task9_problem_id
    assert task9_after["state"]["status"] == "active"


@pytest.mark.asyncio
async def test_postgres_disabled_last_used_training_hides_continue_without_fallback(
    navigation_pool, monkeypatch
):
    repository, user_id = await register(navigation_pool)
    await choose_task9(telegram_message(user_id, "№9 · Уравнения"), repository)
    task9_before = await repository.task9_state(user_id)
    assert task9_before is not None and isinstance(task9_before["problem"], dict)
    task9_problem_id = str(task9_before["problem"]["problem_id"])

    await repository.ensure_task7_session(user_id)
    candidates = build_task7_candidate_batch({}, 74821, family_ids=("OGE07-C01",))
    assert candidates
    task7_problem = await repository.advance_task7_problem(user_id, None, candidates)
    await repository.set_task7_condition_message(
        user_id, str(task7_problem["problem_id"]), 74822
    )
    await repository.save_user_state(user_id, "task7")
    assert await repository.task7_state(user_id) is not None

    import app.math.oge07_scheduler as scheduler

    monkeypatch.setattr(scheduler, "ENABLED_FAMILIES", ())
    assert not await _has_resumable_session(repository, user_id)
    restarted = PostgresRepository(navigation_pool)
    menu_message = telegram_message(user_id, "/start")
    await start(menu_message, restarted)
    menu = menu_message.answer.await_args_list[-1].kwargs["reply_markup"]
    assert all(
        button.callback_data.partition("~")[0] != "nav:resume"
        for row in menu.inline_keyboard
        for button in row
    )

    await continue_session(telegram_message(user_id, "▶ Продолжить"), restarted)
    assert await restarted.user_state(user_id) == "main_menu"
    assert await restarted.last_training_mode(user_id) == "task7"
    assert (await restarted.task7_state(user_id))["problem"]["problem_id"] == task7_problem[
        "problem_id"
    ]
    task9_after = await restarted.task9_state(user_id)
    assert task9_after is not None
    assert task9_after["problem"]["problem_id"] == task9_problem_id
    assert task9_after["state"]["status"] == "active"


@pytest.mark.asyncio
async def test_postgres_late_next_send_cannot_replace_new_number_as_last_used(
    navigation_pool, monkeypatch
):
    repository, user_id = await register(navigation_pool)
    await choose_task6(telegram_message(user_id, "№6 · Вычисления"), repository)
    task6_before = await repository.task6_state(user_id)
    assert task6_before is not None and isinstance(task6_before["problem"], dict)
    assert await repository.task6_reveal_solution(
        user_id, str(task6_before["problem"]["problem_id"])
    )
    entered_send = asyncio.Event()
    finish_send = asyncio.Event()
    original_send_text = router.send_text

    async def delayed_send(message, repo, text, **kwargs):
        if text.startswith("Задание №6 ·"):
            entered_send.set()
            await finish_send.wait()
        return await original_send_text(message, repo, text, **kwargs)

    monkeypatch.setattr(router, "send_text", delayed_send)
    late_next = asyncio.create_task(
        task6_next(telegram_message(user_id, "➡ Следующее"), repository)
    )
    await asyncio.wait_for(entered_send.wait(), timeout=5)
    task6_issued = await repository.task6_progress(user_id)
    assert task6_issued["issued"] == 2

    await choose_task12(telegram_message(user_id, "№12 · Формулы"), repository)
    task12_before = await repository.task12_state(user_id)
    assert task12_before is not None and isinstance(task12_before["problem"], dict)
    task12_problem_id = str(task12_before["problem"]["problem_id"])
    assert await repository.user_state(user_id) == "task12"
    assert await repository.last_training_mode(user_id) == "task12"
    finish_send.set()
    await late_next

    assert await repository.user_state(user_id) == "task12"
    assert await repository.last_training_mode(user_id) == "task12"
    task12_after = await PostgresRepository(navigation_pool).task12_state(user_id)
    assert task12_after is not None
    assert task12_after["problem"]["problem_id"] == task12_problem_id
    task6_after = await repository.task6_state(user_id)
    assert task6_after is not None and task6_after["problem"]["problem_id"] != (
        task6_before["problem"]["problem_id"]
    )
    assert (await repository.task6_progress(user_id))["issued"] == 2
