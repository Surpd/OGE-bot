"""Two actual aiogram dispatchers; Telegram is an offline recording transport."""

import asyncio
import copy
import os
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import httpx
import pytest
from aiogram import Bot
from aiogram.types import User
from test_inline_dispatcher_postgres import TelegramSession

from app.companion.storage import TestRepository, assert_namespace, open_storage
from app.config import Settings, get_settings, test_settings
from app.main import create_app
from app.persistence.repository import MemoryRepository, PostgresRepository


class Transport(TelegramSession):
    def __init__(self, fail=None, blocked=None):
        super().__init__()
        self.fail = fail
        self.blocked = blocked
        self.closed = False

    async def close(self):
        self.closed = True

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        name = method.__api_method__
        if name in {"getFile", "deleteWebhook"}:
            raise AssertionError(f"Forbidden operation: {name}")
        if name == self.fail:
            raise RuntimeError("synthetic secret must not be logged")
        if name == "getMe" and self.blocked:
            await self.blocked.wait()
        if name == "getMe":
            self.calls.append(method)
            return User(id=bot.id, is_bot=True, first_name="Synthetic test bot")
        if name in {"setWebhook", "setMyCommands"}:
            self.calls.append(method)
            return True
        result = await super().make_request(bot, method, timeout)
        if hasattr(result, "from_user"):
            result = result.model_copy(
                update={
                    "from_user": User(id=bot.id, is_bot=True, first_name="Synthetic bot"),
                }
            ).as_(bot)
            self.messages[result.message_id] = result
        return result


def settings(**overrides):
    return Settings(
        _env_file=None,
        **{
            "telegram_webhook_secret": "primary-secret",
            "webhook_base_url": "https://existing.example.invalid",
            "telegram_test_owner_ids": "42",
            "telegram_test_bot_token": "123456:TEST",
            "database_url": "postgresql://not-used/test",
            **overrides,
        },
    )


def message(update_id=1, owner=42, text="/start"):
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1000 + update_id,
            "date": int(datetime.now(UTC).timestamp()),
            "chat": {"id": owner, "type": "private"},
            "from": {"id": owner, "is_bot": False, "first_name": "Synthetic"},
            "text": text,
        },
    }


def install(monkeypatch, config, transport):
    monkeypatch.setattr("app.main.get_settings", lambda: config)
    monkeypatch.setattr("app.companion.runtime.Bot", lambda token: Bot(token, session=transport))


@pytest.mark.parametrize(
    "change,fail",
    [
        ({"telegram_test_bot_token": None}, None),
        ({"telegram_test_bot_token": "invalid"}, None),
        ({"telegram_test_bot_token": "654321:TEST"}, None),
        ({"telegram_test_owner_ids": ""}, None),
        ({"telegram_test_owner_ids": "not-an-id"}, None),
        ({}, "getMe"),
        ({}, "setWebhook"),
    ],
)
async def test_optional_failure_never_gates_primary(monkeypatch, caplog, change, fail):
    transport = Transport(fail=fail)
    config = settings(**change)
    install(monkeypatch, config, transport)
    fake_pool = type(
        "Pool",
        (),
        {
            "close": lambda self: asyncio.sleep(0),
            "fetchval": lambda self, query: asyncio.sleep(0, result="s" * 43),
        },
    )()

    async def storage(*args):
        return TestRepository(fake_pool, "oge_test_bot_123456")

    monkeypatch.setattr("app.companion.runtime.open_storage", storage)
    primary_transport = Transport()
    primary = Bot("654321:PRIMARY", session=primary_transport)
    repo = MemoryRepository()
    app = create_app(repository=repo, bot=primary)
    async with app.router.lifespan_context(app):
        if app.state.companion.task:
            await app.state.companion.task
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            assert (await c.get("/health")).json() == {"status": "ok"}
            assert (await c.post("/telegram/test-webhook", json=message())).status_code == 403
            response = await c.post(
                "/telegram/webhook",
                json=message(),
                headers={
                    "X-Telegram-Bot-Api-Secret-Token": "primary-secret",
                },
            )
            assert response.status_code == 200
            assert repo.updates[primary.id, 1] == "processed"
        assert len([m for m in primary_transport.calls if m.__api_method__ == "setWebhook"]) == 1
        assert app.state.companion.status != "ready"
    assert "synthetic secret" not in caplog.text
    assert not primary_transport.closed  # Injected primary remains owned by its caller.
    await primary.session.close()


async def test_slow_optional_startup_and_shutdown_do_not_wait_for_telegram(monkeypatch):
    blocked = asyncio.Event()
    transport = Transport(blocked=blocked)
    install(monkeypatch, settings(), transport)
    primary = Bot("654321:PRIMARY", session=Transport())
    app = create_app(repository=MemoryRepository(), bot=primary)
    async with asyncio.timeout(2), app.router.lifespan_context(app):
        await asyncio.sleep(0)
        assert app.state.companion.status == "starting"
        assert not blocked.is_set()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            assert (await c.get("/health")).status_code == 200
    assert transport.closed
    await primary.session.close()


async def test_context_settings_are_task_local():
    primary = get_settings()
    ready, release = asyncio.Event(), asyncio.Event()

    async def secondary():
        token = test_settings.set(settings(oge_part2_enabled=True, oge_grading_enabled=False))
        try:
            ready.set()
            await release.wait()
            assert get_settings().oge_part2_enabled
        finally:
            test_settings.reset(token)

    task = asyncio.create_task(secondary())
    await ready.wait()
    assert get_settings() is primary
    release.set()
    await task
    assert get_settings() is primary


async def test_real_pg_isolation_two_sessions_cross_routes_and_restart(bank_pool, monkeypatch):
    url = os.environ["DATABASE_URL"]
    bot_id = 200000000 + int(uuid4().hex[:7], 16)
    test_repo = await open_storage(url, bot_id)
    primary_repo = PostgresRepository(bank_pool)
    primary_transport, transport = Transport(), Transport()
    primary = Bot("654321:PRIMARY", session=primary_transport)
    config = settings(database_url=url, telegram_test_bot_token=f"{bot_id}:TEST")
    install(monkeypatch, config, transport)

    async def storage(*args):
        return test_repo

    monkeypatch.setattr("app.companion.runtime.open_storage", storage)
    app = create_app(repository=primary_repo, bot=primary)

    async def dump():
        tables = await bank_pool.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
        )
        return {
            r["tablename"]: await bank_pool.fetchval(
                f"SELECT coalesce(jsonb_agg(to_jsonb(t)),'[]') FROM \"{r['tablename']}\" t"
            )
            for r in tables
        }

    try:
        await primary_repo.register_user(42)
        await primary_repo.save_user_state(42, "main_menu")
        async with app.router.lifespan_context(app):
            await app.state.companion.task
            second = app.state.companion
            assert second.status == "ready"
            assert second.bot is not primary
            assert second.bot.session is not primary.session
            assert second.secret != config.telegram_webhook_secret
            baseline = await dump()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as c:
                for path, secret in [
                    ("/telegram/webhook", second.secret),
                    ("/telegram/test-webhook", "primary-secret"),
                ]:
                    assert (
                        await c.post(
                            path,
                            json=message(),
                            headers={
                                "X-Telegram-Bot-Api-Secret-Token": secret,
                            },
                        )
                    ).status_code == 403
                headers = {"X-Telegram-Bot-Api-Secret-Token": second.secret}
                assert (
                    await c.post("/telegram/test-webhook", json=message(owner=43), headers=headers)
                ).status_code == 200
                assert not transport.messages
                await c.post("/telegram/test-webhook", json=message(), headers=headers)
                home = next(
                    m for m in reversed(list(transport.messages.values())) if m.reply_markup
                )
                assert "bop Admin" in home.text
                assert "не настроен" in home.text
                button = home.reply_markup.inline_keyboard[0][0]
                callback = {
                    "update_id": 2,
                    "callback_query": {
                        "id": "synthetic",
                        "from": {"id": 42, "is_bot": False, "first_name": "S"},
                        "chat_instance": "s",
                        "data": button.callback_data,
                        "message": home.model_dump(mode="json", by_alias=True, exclude_none=True),
                    },
                }
                foreign = copy.deepcopy(callback)
                foreign["callback_query"]["message"]["from"]["id"] = primary.id
                await c.post("/telegram/test-webhook", json=foreign, headers=headers)
                assert not await test_repo._pool.fetchval(
                    "SELECT count(*) FROM telegram_updates WHERE update_id=2"
                )
                await c.post("/telegram/test-webhook", json=callback, headers=headers)
                before = len(transport.calls)
                await c.post("/telegram/test-webhook", json=callback, headers=headers)
                assert len(transport.calls) == before
                await test_repo.register_user(42)
                await test_repo.reset_owner(42)
                assert not await test_repo._pool.fetchval(
                    "SELECT count(*) FROM users WHERE telegram_user_id=42"
                )
                assert await dump() == baseline
                assert await test_repo._pool.fetchval("SELECT count(*) FROM qa_sessions") == 1
                # Same update ID in the primary route must still be handled independently.
                await c.post(
                    "/telegram/webhook",
                    json=message(),
                    headers={
                        "X-Telegram-Bot-Api-Secret-Token": "primary-secret",
                    },
                )
                assert primary_transport.messages
            # Missing tables must error, never fall back to a primary table.
            async with test_repo._pool.acquire() as conn:
                await assert_namespace(conn, test_repo.schema)
                with pytest.raises(asyncpg.UndefinedTableError):
                    await conn.fetch("SELECT * FROM nonexistent_primary_only")
                with pytest.raises(RuntimeError):
                    await assert_namespace(conn, "public")
            snapshot = await test_repo._pool.fetchval(
                "SELECT payload FROM qa_sessions WHERE owner=42"
            )
        reopened = await open_storage(url, bot_id)
        try:
            assert (
                await reopened._pool.fetchval("SELECT payload FROM qa_sessions WHERE owner=42")
                == snapshot
            )
            # All four FK/check constraints have their own copies despite the primary names.
            assert (
                await reopened._pool.fetchval(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE connamespace=current_schema()::regnamespace "
                    "AND conname IN ('sessions_active_problem_id_fkey',"
                    "'issued_problems_outcome_check',"
                    "'issued_problems_hints_used_check','issued_problems_selection_attempts_check')"
                )
                == 4
            )
        finally:
            await reopened._pool.close()
    finally:
        await primary.session.close()
        await test_repo._pool.close()
        conn = await asyncpg.connect(url)
        await conn.execute(f'DROP SCHEMA "{test_repo.schema}" CASCADE')
        await conn.close()


async def test_unmarked_namespace_is_not_adopted(bank_pool):
    url = os.environ["DATABASE_URL"]
    bot_id = 500000000 + int(uuid4().hex[:7], 16)
    schema = f"oge_test_bot_{bot_id}"
    conn = await asyncpg.connect(url)
    await conn.execute(f'CREATE SCHEMA "{schema}"')
    try:
        with pytest.raises(RuntimeError, match="Unmarked"):
            await open_storage(url, bot_id)
        assert not await conn.fetchval(
            "SELECT count(*) FROM pg_tables WHERE schemaname=$1",
            schema,
        )
    finally:
        await conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await conn.close()


async def test_namespace_never_falls_back_to_public(bank_pool):
    url = os.environ["DATABASE_URL"]
    bot_id = 600000000 + int(uuid4().hex[:7], 16)
    name = "companion_probe_" + uuid4().hex
    conn = await asyncpg.connect(url)
    await conn.execute(f'CREATE TABLE public."{name}" (sentinel text)')
    await conn.execute(f"INSERT INTO public.\"{name}\" VALUES('synthetic production sentinel')")
    repo = await open_storage(url, bot_id)
    try:
        with pytest.raises(asyncpg.UndefinedTableError):
            await repo._pool.fetch(f'SELECT * FROM "{name}"')
        assert (
            await conn.fetchval(f'SELECT sentinel FROM public."{name}"')
            == "synthetic production sentinel"
        )
    finally:
        await repo._pool.close()
        await conn.execute(f'DROP SCHEMA "{repo.schema}" CASCADE')
        await conn.execute(f'DROP TABLE public."{name}"')
        await conn.close()
