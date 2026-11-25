"""Run only the companion via polling against a disposable local PostgreSQL database."""

import argparse
import asyncio
import logging
import re
import subprocess
import sys
from getpass import getpass
from urllib.parse import urlsplit

import asyncpg
from aiogram import Bot, Dispatcher
from pydantic import SecretStr

from app.bot.router import build_router
from app.companion.middleware import CompanionMiddleware
from app.companion.runtime import Companion, owners
from app.companion.storage import open_storage
from app.config import Settings, test_settings


def validate_target(url: str, primary_id: int, companion_id: int) -> None:
    db = urlsplit(url)
    if (
        db.scheme not in {"postgresql", "postgres"}
        or db.hostname not in {"127.0.0.1", "::1"}
        or db.query
        or db.fragment
        or not re.fullmatch(r"/oge_companion_qa(?:_[a-z0-9]+)?", db.path)
    ):
        raise ValueError("Use a dedicated loopback database named oge_companion_qa")
    if min(primary_id, companion_id) <= 0 or primary_id == companion_id:
        raise ValueError("Provide two distinct Telegram bot IDs")


async def poll(
    settings: Settings, url: str, primary_id: int, companion_id: int, sha: str
) -> None:
    validate_target(url, primary_id, companion_id)
    token = settings.telegram_test_bot_token
    if token is None:
        raise ValueError("Missing companion token")
    runtime = Companion(settings, primary_id)
    runtime.owner_ids = owners(settings.telegram_test_owner_ids)
    runtime.bot = Bot(token.get_secret_value())
    try:
        bot = runtime.bot
        if bot.id != companion_id:
            raise ValueError("Token does not belong to the expected companion")
        async with asyncio.timeout(15):
            if (await bot.get_me()).id != companion_id:
                raise ValueError("Unexpected Telegram identity")
            if (await bot.get_webhook_info()).url:
                raise ValueError("Companion already has a webhook. Use a dedicated test bot.")
        conn = await asyncpg.connect(url, timeout=10)
        try:
            if await conn.fetchval("SELECT to_regclass('public.users') IS NOT NULL"):
                raise ValueError("Database has a primary-bot schema. Use a fresh test database.")
        finally:
            await conn.close()
        context = test_settings.set(settings)
        try:
            runtime.repository = await open_storage(url, companion_id)
        finally:
            test_settings.reset(context)
        runtime.dispatcher = Dispatcher()
        runtime.dispatcher.update.outer_middleware(
            CompanionMiddleware(settings, runtime.owner_ids, sha)
        )
        runtime.dispatcher.include_router(build_router())
        print(f"Companion ready · {sha}", flush=True)
        offset = None
        while True:
            updates = await bot.get_updates(
                offset=offset, timeout=25, request_timeout=35,
                allowed_updates=["message", "callback_query"],
            )
            for update in updates:
                await runtime.feed(update.model_dump(mode="json", by_alias=True, exclude_none=True))
                offset = update.update_id + 1
    finally:
        await runtime.close_resources()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-bot-id", type=int, required=True)
    parser.add_argument("--companion-bot-id", type=int, required=True)
    parser.add_argument("--owners", required=True, help="Allowed Telegram IDs, comma separated")
    args = parser.parse_args()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"]):
        parser.error("Use a clean checkout of the candidate commit")
    if not sys.stdin.isatty():
        parser.error("Use an interactive terminal with hidden input")
    url = getpass("Disposable local PostgreSQL URL: ")
    try:
        validate_target(url, args.primary_bot_id, args.companion_bot_id)
    except ValueError:
        parser.error("Use a dedicated loopback database and distinct Telegram bot IDs")
    # Discard environment defaults. Only the supplied token and local URL are used.
    settings = Settings.model_construct(
        telegram_test_bot_token=SecretStr(getpass("Companion bot token: ")),
        telegram_test_owner_ids=args.owners,
        oge_companion_adaptive_enabled=True,
    )
    logging.basicConfig(level=logging.CRITICAL)
    try:
        asyncio.run(poll(settings, url, args.primary_bot_id, args.companion_bot_id, sha))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        # Telegram errors may include the token or request data.
        print(f"Companion stopped ({type(exc).__name__}). Check local database, IDs and token.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
