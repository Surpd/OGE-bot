"""The only PostgreSQL connection used by the admin analytics service."""

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from pydantic import SecretStr


class AdminUnavailable(Exception):
    """The configured connection cannot safely serve an administrative report."""


class AdminRepository:
    def __init__(self, dsn: SecretStr, schema: str) -> None:
        self._dsn = dsn
        self._schema = schema
        self._pool: asyncpg.Pool | None = None
        self._start_lock = asyncio.Lock()

    async def _connect(self) -> asyncpg.Pool:
        async with self._start_lock:
            if self._pool is not None:
                return self._pool
            if not re.fullmatch(r"[a-z_][a-z0-9_]{0,56}_admin", self._schema):
                raise AdminUnavailable
            dsn = self._dsn.get_secret_value()
            if not dsn.startswith(("postgresql://", "postgres://")):
                raise AdminUnavailable
            self._pool = await asyncpg.create_pool(
                dsn,
                min_size=0,
                max_size=2,
                timeout=4,
                command_timeout=4,
                max_inactive_connection_lifetime=60,
                server_settings={
                    "application_name": "bop-admin",
                    "search_path": f'pg_catalog,"{self._schema}"',
                    "default_transaction_read_only": "on",
                    "statement_timeout": "3500",
                    "idle_in_transaction_session_timeout": "5000",
                },
            )
            return self._pool

    @asynccontextmanager
    async def read(self) -> AsyncIterator[asyncpg.Connection]:
        pool = await self._connect()
        async with pool.acquire(timeout=5) as conn, conn.transaction(
            readonly=True, isolation="repeatable_read"
        ):
            # A DSN for an application role is a configuration error. In addition to
            # role attributes, forbid login roles that can assume other memberships.
            permitted: Any = await conn.fetchval("""
                SELECT r.rolcanlogin AND NOT (r.rolsuper OR r.rolbypassrls
                        OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication)
                  AND pg_has_role(r.oid, 'oge_admin_reader', 'USAGE')
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_roles inherited
                      WHERE inherited.oid <> r.oid AND inherited.rolname <> 'oge_admin_reader'
                      AND pg_has_role(r.oid, inherited.oid, 'MEMBER')
                  )
                FROM pg_roles r WHERE r.rolname = current_user
            """)
            if not permitted:
                raise AdminUnavailable
            yield conn

    async def close(self) -> None:
        async with self._start_lock:
            pool, self._pool = self._pool, None
            if pool is not None:
                try:
                    async with asyncio.timeout(5):
                        await pool.close()
                except TimeoutError:
                    pool.terminate()
