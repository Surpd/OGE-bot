import os
from typing import cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest

from app.config import get_settings
from app.main import _migration_files, create_app
from app.persistence.repository import PostgresRepository, read_migration


async def _create_test_database(database_url: str) -> tuple[asyncpg.Connection, str, str]:
    admin = await asyncpg.connect(database_url)
    database_name = f"oge_migrations_{uuid4().hex}"
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    parsed = urlsplit(database_url)
    test_url = urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{database_name}", parsed.query, parsed.fragment)
    )
    return admin, database_name, test_url


async def _drop_test_database(admin: asyncpg.Connection, database_name: str) -> None:
    await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
    await admin.close()


@pytest.mark.asyncio
async def test_create_app_lifespan_applies_ordered_migrations_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    admin, database_name, test_url = await _create_test_database(database_url)
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")
    get_settings.cache_clear()
    app = create_app()
    expected_versions = [migration.name for migration in _migration_files()]

    try:
        async with app.router.lifespan_context(app):
            repository = cast(PostgresRepository, app.state.repository)
            rows = await repository._pool.fetch(
                "SELECT version FROM app_schema_migrations ORDER BY version"
            )
            assert [row["version"] for row in rows] == expected_versions
            assert "0007_task14_sessions.sql" in expected_versions
            assert "0009_task8_sessions.sql" in expected_versions
            assert [int(version[:4]) for version in expected_versions] == sorted(
                int(version[:4]) for version in expected_versions
            )

        async with app.router.lifespan_context(app):
            repository = cast(PostgresRepository, app.state.repository)
            rows = await repository._pool.fetch(
                "SELECT version FROM app_schema_migrations ORDER BY version"
            )
            assert [row["version"] for row in rows] == expected_versions
            assert await repository._pool.fetchval(
                "SELECT to_regclass('sessions_one_active_task8_per_user') IS NOT NULL"
            )
    finally:
        get_settings.cache_clear()
        await _drop_test_database(admin, database_name)


@pytest.mark.asyncio
async def test_create_app_fails_before_unique_index_without_changing_duplicate_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    admin, database_name, test_url = await _create_test_database(database_url)
    seed_pool = await asyncpg.create_pool(test_url)
    try:
        await seed_pool.execute(await read_migration("migrations/0001_foundation.sql"))
        user_id = await seed_pool.fetchval(
            "INSERT INTO users (telegram_user_id) VALUES ($1) RETURNING id",
            int(uuid4().int % (2**62)) + 1,
        )
        await seed_pool.execute(
            "INSERT INTO sessions (user_id, mode, state) VALUES ($1, 'task8', '{}'::jsonb), "
            "($1, 'task8', '{}'::jsonb)",
            user_id,
        )
    finally:
        await seed_pool.close()

    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST_TOKEN")
    get_settings.cache_clear()
    app = create_app()
    try:
        with pytest.raises(RuntimeError, match="duplicate active task8 sessions"):
            async with app.router.lifespan_context(app):
                pytest.fail("Startup must stop before creating an index over duplicate sessions")

        verify_pool = await asyncpg.create_pool(test_url)
        try:
            assert await verify_pool.fetchval(
                "SELECT count(*) FROM sessions WHERE user_id=$1 AND mode='task8' "
                "AND finished_at IS NULL",
                user_id,
            ) == 2
            assert await verify_pool.fetchval(
                "SELECT to_regclass('sessions_one_active_task8_per_user') IS NULL"
            )
        finally:
            await verify_pool.close()
    finally:
        get_settings.cache_clear()
        await _drop_test_database(admin, database_name)
