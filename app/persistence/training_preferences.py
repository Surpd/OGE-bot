"""Persist per-number family preferences without changing saved problem snapshots."""

import asyncpg


class PostgresTrainingPreferences:
    _pool: asyncpg.Pool

    async def personal_enabled(self, user_id: int) -> bool:
        value = await self._pool.fetchval(
            "SELECT preferences->>'personal_training' FROM users WHERE telegram_user_id=$1", user_id
        )
        return not (isinstance(value, str) and value == "false")

    async def set_personal_enabled(self, user_id: int, enabled: bool) -> None:
        await self._pool.execute(
            """UPDATE users SET preferences=jsonb_set(preferences,'{personal_training}',
            to_jsonb($2::boolean)) WHERE telegram_user_id=$1""",
            user_id,
            enabled,
        )

    async def math_display(self, user_id: int | None, template_id: str | None = None) -> str:
        if template_id is not None:
            pinned_or_requested = await self._pool.fetchval(
                """SELECT EXISTS (SELECT FROM math_template_png_fallbacks WHERE template_id=$2)
                       OR EXISTS (SELECT FROM users WHERE telegram_user_id=$1
                                  AND preferences->>'math_display'='png')""",
                user_id,
                template_id,
            )
            return "png" if pinned_or_requested else "auto"
        value = await self._pool.fetchval(
            "SELECT preferences->>'math_display' FROM users WHERE telegram_user_id=$1", user_id
        )
        return "png" if value == "png" else "auto"

    async def remember_png_template(self, template_id: str) -> None:
        await self._pool.execute(
            "INSERT INTO math_template_png_fallbacks (template_id) VALUES($1) "
            "ON CONFLICT DO NOTHING",
            template_id,
        )

    async def set_math_display(self, user_id: int, mode: str) -> None:
        if mode not in {"auto", "png"}:
            raise ValueError("Unsupported math display mode")
        await self._pool.execute(
            "UPDATE users SET preferences=jsonb_set(preferences, '{math_display}', "
            "to_jsonb($2::text), true) WHERE telegram_user_id=$1",
            user_id,
            mode,
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
    png_templates: set[str]
    personal_preferences: dict[int, bool]

    async def personal_enabled(self, user_id: int) -> bool:
        return self.personal_preferences.get(user_id, True)

    async def set_personal_enabled(self, user_id: int, enabled: bool) -> None:
        self.personal_preferences[user_id] = enabled

    async def math_display(self, user_id: int | None, template_id: str | None = None) -> str:
        if template_id in self.png_templates:
            return "png"
        return self.math_preferences.get(user_id, "auto") if user_id is not None else "auto"

    async def remember_png_template(self, template_id: str) -> None:
        self.png_templates.add(template_id)

    async def set_math_display(self, user_id: int, mode: str) -> None:
        if mode not in {"auto", "png"}:
            raise ValueError("Unsupported math display mode")
        self.math_preferences[user_id] = mode

    async def training_family(self, user_id: int, number: int) -> str | None:
        return self.training_preferences.get((user_id, number))

    async def set_training_family(self, user_id: int, number: int, family: str | None) -> None:
        self.training_preferences[user_id, number] = family
