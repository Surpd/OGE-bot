"""Persist per-number family preferences without changing saved problem snapshots."""

import asyncpg


class PostgresTrainingPreferences:
    _pool: asyncpg.Pool

    async def training_family(self, user_id: int, number: int) -> str | None:
        value = await self._pool.fetchval(
            "SELECT preferences->'training_families'->>$2::text FROM users "
            "WHERE telegram_user_id=$1",
            user_id,
            str(number),
        )
        return value if isinstance(value, str) else None

    async def set_training_family(self, user_id: int, number: int, family: str | None) -> None:
        await self._pool.execute(
            """UPDATE users SET preferences=jsonb_set(preferences, '{training_families}',
                 COALESCE(preferences->'training_families', '{}'::jsonb)
                   || jsonb_build_object($2::text, $3::text), true)
               WHERE telegram_user_id=$1""",
            user_id,
            str(number),
            family,
        )


class MemoryTrainingPreferences:
    training_preferences: dict[tuple[int, int], str | None]

    async def training_family(self, user_id: int, number: int) -> str | None:
        return self.training_preferences.get((user_id, number))

    async def set_training_family(self, user_id: int, number: int, family: str | None) -> None:
        self.training_preferences[user_id, number] = family
