"""Navigation claim concurrency/persistence on PostgreSQL; never use app credentials here."""
import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from app.persistence.repository import PostgresRepository, read_migration


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
    assert not await restarted.claim_navigation_message(other_user_id, 300)
    assert await restarted.claim_navigation_message(user_id, 300)
    assert await restarted.claim_navigation_message(other_user_id, 301)


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
