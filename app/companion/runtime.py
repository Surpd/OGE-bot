"""Optional second bot. No references to the primary repository or bot session."""

import asyncio
import hmac
import logging
import os
import re
import secrets
from typing import Any
from urllib.parse import urlsplit

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, Message, Update

from app.admin.repository import AdminRepository
from app.admin.service import AdminService, make_service
from app.bot.router import build_router
from app.companion.middleware import CompanionMiddleware, allowed_payload
from app.companion.storage import TestRepository, open_storage
from app.config import Settings
from app.persistence.scenario_repository import ScenarioPostgresRepository

logger = logging.getLogger("oge_trainer")
PATH = "/telegram/test-webhook"


def running_sha() -> str:
    value = os.getenv("RENDER_GIT_COMMIT") or (os.getenv("APP_BUILD_SHA") or "")
    return value if re.fullmatch("[0-9a-f]{40}", value) else "local / SHA не задан"


def owners(value: str) -> frozenset[int]:
    entries = value.split(",")
    if not 1 <= len(entries) <= 5 or any(
        not re.fullmatch(r"[1-9][0-9]{0,14}", entry.strip()) for entry in entries
    ):
        raise ValueError("Invalid test owner allowlist")
    return frozenset(int(entry.strip()) for entry in entries)


class Companion:
    def __init__(
        self,
        settings: Settings,
        primary_id: int,
        *,
        analytics_repository: AdminRepository | None = None,
    ) -> None:
        self.settings = settings
        self.primary_id = primary_id
        self.sha = running_sha()
        self.bot: Bot | None = None
        self.identity: Any | None = None
        self.repository: TestRepository | None = None
        self.admin_service: AdminService | None = None
        self._analytics_repository = analytics_repository
        self.dispatcher: Dispatcher | None = None
        self.secret = secrets.token_urlsafe(32)
        self.owner_ids: frozenset[int] = frozenset()
        self.status = "disabled"
        self.lock = asyncio.Lock()
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self.settings.telegram_test_bot_token:
            self.task = asyncio.create_task(self.initialize())

    async def initialize(self) -> None:
        self.status = "starting"
        try:
            async with asyncio.timeout(120):
                self.owner_ids = owners(self.settings.telegram_test_owner_ids)
                origin = urlsplit(self.settings.webhook_base_url or "")
                if (
                    origin.scheme != "https"
                    or not origin.hostname
                    or origin.username
                    or origin.password
                    or origin.path not in ("", "/")
                    or origin.query
                    or origin.fragment
                    or not self.settings.database_url
                ):
                    raise ValueError("Missing companion origin or database")
                token = self.settings.telegram_test_bot_token
                if token is None:
                    raise ValueError("Missing test token")
                self.bot = Bot(token.get_secret_value())
                if self.bot.id == self.primary_id:
                    raise ValueError("Primary bot token cannot be used for companion")
                async with asyncio.timeout(10):
                    identity = await self.bot.get_me()
                self.identity = identity
                if identity.id != self.bot.id or identity.id == self.primary_id:
                    raise ValueError("Unexpected test bot identity")
                self.repository = await open_storage(self.settings.database_url, identity.id)
                self.admin_service = make_service(
                    self.settings, self.owner_ids, self.primary_id, self._analytics_repository
                )
                self.secret = await self.repository._pool.fetchval(
                    "SELECT webhook_secret FROM companion_identity"
                )
                if (
                    not isinstance(self.secret, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", self.secret)
                    or self.secret == self.settings.telegram_webhook_secret
                ):
                    raise ValueError("Invalid companion webhook secret")
                self.dispatcher = Dispatcher()
                self.dispatcher.update.outer_middleware(
                    CompanionMiddleware(
                        self.settings,
                        self.owner_ids,
                        self.sha,
                        admin_service=self.admin_service,
                        companion=self,
                    )
                )
                self.dispatcher.include_router(build_router())
                async with asyncio.timeout(10):
                    await self.bot.set_my_commands(
                        commands=[
                            BotCommand(command="start", description="Меню тестового бота"),
                            BotCommand(command="qa", description="Точные проверки"),
                        ]
                    )
                    webhook_ready = await self.bot.set_webhook(
                        url=f"{(self.settings.webhook_base_url or '').rstrip('/')}{PATH}",
                        secret_token=self.secret,
                        drop_pending_updates=False,
                        allowed_updates=["message", "callback_query"],
                    )
                if not webhook_ready:
                    raise RuntimeError("Telegram did not confirm the companion webhook")
                self.status = "ready"
                logging.getLogger("uvicorn.error").info(
                    "companion_ready release=%s bot=%s", self.sha, identity.username or "-"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Telegram errors may contain the secret token. Never log their text.
            self.status = "unavailable"
            logger.warning("companion_unavailable type=%s", type(exc).__name__)
            try:
                await self.close_resources()
            except Exception as cleanup:
                logger.warning("companion_cleanup_failed type=%s", type(cleanup).__name__)

        if self.status == "ready" and self._analytics_repository is not None:
            await self._probe_analytics()

    async def _probe_analytics(self) -> None:
        if self.admin_service is None:
            return
        try:
            report = await self.admin_service.load("home", "28")
        except Exception as exc:
            logger.warning("companion_analytics_probe_failed type=%s", type(exc).__name__)
            return
        if report.unavailable:
            logger.warning("companion_analytics_unavailable status=%s", report.unavailable)
            return
        # Use the actual report, logging availability and activity presence rather than counts.
        logging.getLogger("uvicorn.error").info(
            "companion_analytics_ready release=%s has_accounts=%s has_learning_activity=%s",
            self.sha,
            bool(report.data.get("registered")),
            bool(report.data.get("active")),
        )

    def accepts(self, secret: str | None) -> bool:
        return bool(self.status == "ready" and secret and hmac.compare_digest(secret, self.secret))

    async def feed(self, payload: dict[str, Any]) -> None:
        if not any(allowed_payload(payload, owner) for owner in self.owner_ids):
            return
        assert self.bot and self.dispatcher and self.repository
        update = Update.model_validate(payload)
        callback = update.callback_query
        if callback and (
            not isinstance(callback.message, Message)
            or not callback.message.from_user
            or callback.message.from_user.id != self.bot.id
        ):
            return
        # One owner operation at a time; the writable test pool stays isolated.
        async with asyncio.timeout(45), self.lock:
            repo = self.repository
            if not await repo.claim_update(update.update_id, bot_id=self.bot.id):
                return
            try:
                await self.dispatcher.feed_update(
                    self.bot,
                    update,
                    repository=repo,
                    oge15_repository=ScenarioPostgresRepository(repo._pool, bot_id=self.bot.id),
                )
            finally:
                # Do not replay an uncertain Telegram send automatically. Exact retry is explicit.
                await repo.finish_update(update.update_id, bot_id=self.bot.id)

    async def close_resources(self) -> None:
        if self.bot:
            try:
                await self.bot.session.close()
            except Exception as exc:
                logger.warning("companion_bot_cleanup_failed type=%s", type(exc).__name__)
        if self.repository:
            try:
                async with asyncio.timeout(5):
                    await self.repository._pool.close()
            except Exception as exc:
                logger.warning("companion_storage_cleanup_failed type=%s", type(exc).__name__)
        if self.admin_service:
            try:
                await self.admin_service.close()
            except Exception as exc:
                logger.warning("companion_admin_cleanup_failed type=%s", type(exc).__name__)
            finally:
                self.admin_service = None
        self.bot = None
        self.repository = None
        self.identity = None
        # Intentionally no deleteWebhook, for either identity.

    async def close(self) -> None:
        self.status = "disabled"
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        try:
            await self.close_resources()
        except Exception as exc:
            logger.warning("companion_cleanup_failed type=%s", type(exc).__name__)
