import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request, Response

from app.bot.router import build_router
from app.config import get_settings
from app.persistence.repository import PostgresRepository, Repository, read_migration

logger = logging.getLogger("oge_trainer")


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
                await pool.execute(await read_migration("migrations/0001_foundation.sql"))
        if telegram_bot is None:
            if not settings.telegram_bot_token:
                raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
            telegram_bot = Bot(settings.telegram_bot_token)
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
