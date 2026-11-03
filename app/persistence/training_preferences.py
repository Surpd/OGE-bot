"""Persist per-number family preferences without changing saved problem snapshots."""

import asyncpg


class PostgresTrainingPreferences:
    _pool: asyncpg.Pool

    async def math_display(self, user_id: int) -> str:
        value = await self._pool.fetchval(
            "SELECT preferences->>'math_display' FROM users WHERE telegram_user_id=$1", user_id
        )
        return "png" if value == "png" else "auto"

    async def set_math_display(self, user_id: int, mode: str) -> None:
        if mode not in {"auto", "png"}:
            raise ValueError("Unsupported math display mode")
        await self._pool.execute(
            "UPDATE users SET preferences=jsonb_set(preferences, '{math_display}', "
            "to_jsonb($2::text), true) WHERE telegram_user_id=$1", user_id, mode
        )

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
    math_preferences: dict[int, str]

    async def math_display(self, user_id: int) -> str:
        return self.math_preferences.get(user_id, "auto")

    async def set_math_display(self, user_id: int, mode: str) -> None:
        if mode not in {"auto", "png"}:
            raise ValueError("Unsupported math display mode")
        self.math_preferences[user_id] = mode

    async def training_family(self, user_id: int, number: int) -> str | None:
        return self.training_preferences.get((user_id, number))

    async def set_training_family(self, user_id: int, number: int, family: str | None) -> None:
        self.training_preferences[user_id, number] = family
