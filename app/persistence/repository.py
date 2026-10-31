from typing import Protocol, cast

import asyncpg


class Repository(Protocol):
    async def register_user(self, telegram_user_id: int) -> None: ...

    async def save_user_state(self, telegram_user_id: int, screen: str) -> None: ...

    async def user_state(self, telegram_user_id: int) -> str | None: ...

    async def current_session(self, telegram_user_id: int) -> dict[str, object] | None: ...

    async def claim_update(self, update_id: int) -> bool: ...

    async def finish_update(self, update_id: int, *, failed: bool = False) -> None: ...


class PostgresRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def register_user(self, telegram_user_id: int) -> None:
        await self._pool.execute(
            """INSERT INTO users (telegram_user_id) VALUES ($1)
               ON CONFLICT (telegram_user_id) DO NOTHING""",
            telegram_user_id,
        )

    async def save_user_state(self, telegram_user_id: int, screen: str) -> None:
        await self._pool.execute(
            "UPDATE users SET current_state = jsonb_build_object('screen', $2::text) "
            "WHERE telegram_user_id = $1",
            telegram_user_id,
            screen,
        )

    async def user_state(self, telegram_user_id: int) -> str | None:
        state = await self._pool.fetchval(
            "SELECT current_state ->> 'screen' FROM users WHERE telegram_user_id = $1",
            telegram_user_id,
        )
        return cast(str | None, state)

    async def current_session(self, telegram_user_id: int) -> dict[str, object] | None:
        row = await self._pool.fetchrow(
            """SELECT s.id, s.mode, s.state FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE u.telegram_user_id = $1 AND s.finished_at IS NULL
               ORDER BY s.started_at DESC LIMIT 1""",
            telegram_user_id,
        )
        return dict(row) if row is not None else None

    async def claim_update(self, update_id: int) -> bool:
        async with self._pool.acquire() as connection:
            inserted = await connection.fetchval(
                """INSERT INTO telegram_updates (update_id, status, claimed_at)
                   VALUES ($1, 'processing', now())
                   ON CONFLICT (update_id) DO NOTHING RETURNING update_id""",
                update_id,
            )
            if inserted is not None:
                return True
            reclaimed = await connection.fetchval(
                """UPDATE telegram_updates SET status = 'processing', claimed_at = now()
                   WHERE update_id = $1 AND (
                     status = 'failed' OR
                     (status = 'processing' AND claimed_at < now() - interval '5 minutes')
                   )
                   RETURNING update_id""",
                update_id,
            )
            return reclaimed is not None

    async def finish_update(self, update_id: int, *, failed: bool = False) -> None:
        await self._pool.execute(
            """UPDATE telegram_updates SET status = $2, processed_at = now()
               WHERE update_id = $1""",
            update_id,
            "failed" if failed else "processed",
        )


class MemoryRepository:
    """Small adapter for isolated handler tests; production always uses PostgreSQL."""

    def __init__(self) -> None:
        self.users: set[int] = set()
        self.states: dict[int, str] = {}
        self.updates: dict[int, str] = {}
        self.sessions: dict[int, dict[str, object]] = {}

    async def register_user(self, telegram_user_id: int) -> None:
        self.users.add(telegram_user_id)

    async def save_user_state(self, telegram_user_id: int, screen: str) -> None:
        self.states[telegram_user_id] = screen

    async def user_state(self, telegram_user_id: int) -> str | None:
        return self.states.get(telegram_user_id)

    async def current_session(self, telegram_user_id: int) -> dict[str, object] | None:
        return self.sessions.get(telegram_user_id)

    async def claim_update(self, update_id: int) -> bool:
        state = self.updates.get(update_id)
        if state is None or state == "failed":
            self.updates[update_id] = "processing"
            return True
        return False

    async def finish_update(self, update_id: int, *, failed: bool = False) -> None:
        self.updates[update_id] = "failed" if failed else "processed"


async def read_migration(path: str) -> str:
    from pathlib import Path

    return Path(path).read_text(encoding="utf-8")
