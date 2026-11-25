"""Dedicated pool whose search_path can never fall through to production tables."""

import re
import secrets

import asyncpg

from app.persistence.part2_bank import import_bank
from app.persistence.repository import PostgresRepository


class TestRepository(PostgresRepository):
    __test__ = False

    def __init__(self, pool: asyncpg.Pool, schema: str) -> None:
        super().__init__(pool)
        if not re.fullmatch(r"oge_test_bot_[1-9][0-9]{0,19}", schema):
            raise ValueError("Invalid companion namespace")
        self.schema = schema

    async def reset_owner(self, owner: int) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await assert_namespace(conn, self.schema)
            for table in ("part2_grades", "part2_work"):
                await conn.execute(
                    f"DELETE FROM {table} WHERE issue_id IN "
                    "(SELECT id FROM part2_issues WHERE owner=$1)",
                    owner,
                )
            await conn.execute("DELETE FROM part2_issues WHERE owner=$1", owner)
            await conn.execute("DELETE FROM users WHERE telegram_user_id=$1", owner)


async def assert_namespace(conn: asyncpg.Connection, schema: str) -> None:
    # No public, $user or inherited schema fallback in this pool.
    if await conn.fetchval("SHOW search_path") != schema:
        raise RuntimeError("Unsafe companion search_path")
    if await conn.fetchval("SELECT current_schema()") != schema:
        raise RuntimeError("Missing companion namespace")


async def open_storage(url: str, bot_id: int) -> TestRepository:
    from app.main import _run_schema_migrations

    schema = f"oge_test_bot_{bot_id}"
    if not re.fullmatch(r"oge_test_bot_[1-9][0-9]{0,19}", schema):
        raise ValueError("Invalid test bot identity")
    # Validate the DB connection's default namespace without reading any user tables.
    probe = await asyncpg.connect(url, command_timeout=10)
    try:
        if schema in await probe.fetchval("SELECT current_schemas(false)"):
            raise RuntimeError("Companion namespace is on the primary search_path")
    finally:
        await probe.close()
    pool = await asyncpg.create_pool(
        url,
        min_size=1,
        max_size=3,
        command_timeout=15,
        server_settings={
            "search_path": schema, "application_name": "oge-companion",
        },
    )
    assert pool is not None
    try:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(74120610, hashtext($1))", schema)
            existed = await conn.fetchval(
                "SELECT EXISTS(SELECT FROM pg_namespace WHERE nspname=$1)", schema
            )
            if existed:
                # Never adopt an unrelated schema just because its name matches.
                if not await conn.fetchval("SELECT to_regclass('companion_identity')"):
                    raise RuntimeError("Unmarked companion namespace")
                if await conn.fetchval("SELECT bot_id FROM companion_identity") != bot_id:
                    raise RuntimeError("Companion namespace identity mismatch")
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            await conn.execute("""CREATE TABLE IF NOT EXISTS companion_identity (
                singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
                bot_id bigint NOT NULL, webhook_secret text NOT NULL);
                ALTER TABLE companion_identity ENABLE ROW LEVEL SECURITY;
                REVOKE ALL ON companion_identity FROM PUBLIC""")
            await conn.execute(
                "INSERT INTO companion_identity(bot_id,webhook_secret) VALUES($1,$2) "
                "ON CONFLICT DO NOTHING",
                bot_id,
                secrets.token_urlsafe(32),
            )
            await conn.execute(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC')
            for role in ("anon", "authenticated"):
                if await conn.fetchval(
                    "SELECT EXISTS(SELECT FROM pg_roles WHERE rolname=$1)", role
                ):
                    await conn.execute(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{role}"')
            await assert_namespace(conn, schema)
        await _run_schema_migrations(pool, lock_id=-74120608)
        async with pool.acquire() as conn:
            await assert_namespace(conn, schema)
            await conn.execute("""CREATE TABLE IF NOT EXISTS qa_sessions (
                owner bigint PRIMARY KEY, payload jsonb NOT NULL DEFAULT '{}',
                updated_at timestamptz NOT NULL DEFAULT now());
                ALTER TABLE qa_sessions ENABLE ROW LEVEL SECURITY;
                REVOKE ALL ON qa_sessions FROM PUBLIC""")
            await import_bank(conn)
        repository = TestRepository(pool, schema)
        return repository
    except BaseException:
        await pool.close()
        raise
