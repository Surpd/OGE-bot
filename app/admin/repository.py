"""Borrow the application's existing connection for bounded read-only reports."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg

from app.admin.queries import PAGE_SIZE


class AdminUnavailable(Exception):
    """The application connection cannot safely serve an administrative report."""


class AdminRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._report_slot = asyncio.Semaphore(1)

    @asynccontextmanager
    async def _read(self, *, projections: bool) -> AsyncIterator[asyncpg.Connection]:
        async with (
            self._report_slot,
            self._pool.acquire(timeout=4) as conn,
            conn.transaction(readonly=True, isolation="repeatable_read"),
        ):
            source = await conn.fetchval("SELECT current_schema()")
            if (
                not isinstance(source, str)
                or source.startswith(("oge_test_bot_", "pg_"))
                or source == "information_schema"
                or len(source.encode("utf-8")) > 57
            ):
                raise AdminUnavailable
            # Transaction-local settings are restored before the connection can serve a student.
            # Qualify the schema name via PostgreSQL rather than interpolating it into SQL.
            await conn.execute("""
                SELECT set_config('search_path', format('pg_catalog,%I,pg_temp', $1::text), true),
                       set_config('statement_timeout', '3500', true),
                       set_config('idle_in_transaction_session_timeout', '5000', true)
            """, f"{source}_admin" if projections else source)
            yield conn

    @asynccontextmanager
    async def read(self) -> AsyncIterator[asyncpg.Connection]:
        async with self._read(projections=True) as conn:
            yield conn

    async def telegram_user_ids(
        self, user_ids: list[UUID], excluded_keys: tuple[str, ...]
    ) -> dict[UUID, int]:
        """Resolve just a visible page using the same bounded READ ONLY connection."""
        if len(user_ids) > PAGE_SIZE:
            raise ValueError("Too many learner identities")
        if not user_ids:
            return {}
        async with self._read(projections=False) as conn:
            rows = await conn.fetch(
                """SELECT id,telegram_user_id FROM users
                   WHERE id=ANY($1::uuid[])
                     AND NOT (md5(telegram_user_id::text)=ANY($2::text[]))
                   LIMIT $3""",
                user_ids, excluded_keys, PAGE_SIZE,
            )
        return {row["id"]: row["telegram_user_id"] for row in rows}
