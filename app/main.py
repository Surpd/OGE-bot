import hmac
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request, Response

from app.bot.router import build_router
from app.config import get_settings
from app.persistence.repository import PostgresRepository, Repository, read_migration

logger = logging.getLogger("oge_trainer")
_MIGRATION_PATTERN = re.compile(r"(?P<number>\d{4})_[a-z0-9_]+\.sql\Z")
_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
_MIGRATION_LOCK_ID = 74120608


def _migration_files() -> list[Path]:
    migrations = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    seen: dict[int, str] = {}
    for migration in migrations:
        match = _MIGRATION_PATTERN.fullmatch(migration.name)
        if match is None:
            raise RuntimeError(f"Invalid migration filename: {migration.name}")
        number = int(match.group("number"))
        previous = seen.get(number)
        if previous is not None:
            raise RuntimeError(
                f"Duplicate migration number {number:04d}: {previous}, {migration.name}"
            )
        seen[number] = migration.name
    return migrations


async def _assert_no_duplicate_active_sessions(
    connection: asyncpg.Connection, mode: str
) -> None:
    duplicate = await connection.fetchrow(
        """SELECT mode, user_id, count(*) AS session_count
           FROM sessions
           WHERE finished_at IS NULL
             AND mode = $1
           GROUP BY mode, user_id
           HAVING count(*) > 1
           ORDER BY mode, user_id
           LIMIT 1""",
        mode,
    )
    if duplicate is not None:
        raise RuntimeError(
            "Cannot apply session uniqueness migrations: duplicate active "
            f"{duplicate['mode']} sessions exist for user {duplicate['user_id']} "
            f"({duplicate['session_count']} rows). Resolve them manually before retrying."
        )


async def _run_schema_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as connection:
        await connection.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK_ID)
        try:
            await connection.execute(
                """CREATE TABLE IF NOT EXISTS app_schema_migrations (
                       version text PRIMARY KEY,
                       applied_at timestamptz NOT NULL DEFAULT now()
                   )"""
            )
            await connection.execute("ALTER TABLE app_schema_migrations ENABLE ROW LEVEL SECURITY")
            await connection.execute("REVOKE ALL ON app_schema_migrations FROM PUBLIC")
            await connection.execute(
                """DO $$
                   BEGIN
                       IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                           REVOKE ALL ON app_schema_migrations FROM anon;
                       END IF;
                       IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                           REVOKE ALL ON app_schema_migrations FROM authenticated;
                       END IF;
                   END $$"""
            )
            for migration in _migration_files():
                version = migration.name
                applied = await connection.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM app_schema_migrations WHERE version=$1)",
                    version,
                )
                if applied:
                    continue
                sql = await read_migration(str(migration))
                session_index = re.search(
                    r"CREATE\s+UNIQUE\s+INDEX[\s\S]+?\bON\s+sessions\b"
                    r"[\s\S]+?\bWHERE\s+mode\s*=\s*'(?P<mode>[^']+)'",
                    sql,
                    re.IGNORECASE,
                )
                if session_index is not None:
                    await _assert_no_duplicate_active_sessions(
                        connection, session_index.group("mode")
                    )
                await connection.execute(sql)
                await connection.execute(
                    "INSERT INTO app_schema_migrations (version) VALUES ($1)", version
                )
        finally:
            await connection.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_LOCK_ID)


def create_app(
    *,
    repository: Repository | None = None,
    bot: Bot | None = None,
    run_schema_migrations: bool = True,
) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        repo = repository
        telegram_bot = bot
        pool: asyncpg.Pool | None = None
        if repo is None:
            if not settings.database_url:
                raise RuntimeError("DATABASE_URL is required")
            pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
            repo = PostgresRepository(pool)
            if run_schema_migrations:
                try:
                    await _run_schema_migrations(pool)
                except BaseException:
                    await pool.close()
                    raise
        if telegram_bot is None:
            if not settings.telegram_bot_token:
                raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
            telegram_bot = Bot(settings.telegram_bot_token)
        if settings.app_env == "production":
            if not settings.telegram_webhook_secret:
                raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is required in production")
            if not settings.webhook_base_url or not settings.webhook_base_url.startswith(
                "https://"
            ):
                raise RuntimeError("WEBHOOK_BASE_URL must be an HTTPS origin in production")
        if settings.webhook_base_url and settings.telegram_webhook_secret:
            await telegram_bot.set_webhook(
                url=f"{settings.webhook_base_url.rstrip('/')}/telegram/webhook",
                secret_token=settings.telegram_webhook_secret,
                drop_pending_updates=False,
            )
        dispatcher = Dispatcher()
        dispatcher.include_router(build_router())
        application.state.repository = repo
        application.state.bot = telegram_bot
        application.state.dispatcher = dispatcher
        yield
        if bot is None:
            await telegram_bot.session.close()
        if pool is not None:
            await pool.close()

    application = FastAPI(title="OGE Trainer", lifespan=lifespan)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> Response:
        expected = settings.telegram_webhook_secret
        if (
            not expected
            or not x_telegram_bot_api_secret_token
            or not hmac.compare_digest(x_telegram_bot_api_secret_token, expected)
        ):
            raise HTTPException(status_code=403, detail="Forbidden")
        try:
            payload: Any = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid update") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid update")
        update_id = payload.get("update_id")
        if type(update_id) is not int or update_id < 0:
            raise HTTPException(status_code=400, detail="Invalid update")
        repo: Repository = request.app.state.repository
        if not await repo.claim_update(update_id):
            return Response(status_code=200)
        try:
            update = Update.model_validate(payload)
            dispatcher: Dispatcher = request.app.state.dispatcher
            telegram_bot: Bot = request.app.state.bot
            await dispatcher.feed_update(telegram_bot, update, repository=repo)
            await repo.finish_update(update_id)
        except Exception as exc:
            await repo.finish_update(update_id, failed=True)
            logger.error(
                "telegram_update_failed",
                extra={"update_id": update_id, "error_type": type(exc).__name__},
            )
            raise HTTPException(status_code=500, detail="Update processing failed") from None
        return Response(status_code=200)

    return application


app = create_app()
