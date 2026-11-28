import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from aiogram import Bot
from aiogram.types import ChatFullInfo
from test_admin_analytics_postgres import _answer, _issue
from test_companion_runtime import Transport, install, settings

from app.admin.repository import AdminRepository
from app.main import create_app
from app.persistence.repository import PostgresRepository


async def test_profile_identity_mapping_uses_requested_ids_and_preserves_shared_pool(bank_pool):
    await bank_pool.execute("INSERT INTO users(telegram_user_id) VALUES(101),(102),(103)")
    users = {
        row["telegram_user_id"]: row["id"]
        for row in await bank_pool.fetch("SELECT id,telegram_user_id FROM users")
    }
    repository = AdminRepository(bank_pool)
    excluded = (hashlib.md5(b"102").hexdigest(),)
    assert await repository.telegram_user_ids([users[101], users[102]], excluded) == {
        users[101]: 101
    }
    assert await bank_pool.fetchval("SELECT count(*) FROM users WHERE telegram_user_id=103") == 1
    async with bank_pool.acquire() as conn:
        assert await conn.fetchval("SHOW transaction_read_only") == "off"
        assert await conn.fetchval("SHOW statement_timeout") == "0"
        assert (await conn.fetchval("SELECT current_schema()")).startswith("p2_")


async def test_real_runtime_enriches_only_visible_learners_through_primary_bot(
    bank_pool, monkeypatch
):
    class PrimaryTransport(Transport):
        username = "SyntheticLearner"

        async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
            if method.__api_method__ == "getChat":
                assert bot.id == 654321
                assert method.chat_id == 101
                self.calls.append(method)
                return ChatFullInfo.model_construct(
                    id=101, type="private", first_name="Synthetic learner", username=self.username
                )
            return await super().make_request(bot, method, timeout)

    await bank_pool.execute("INSERT INTO users(telegram_user_id) VALUES(42),(101),(103)")
    users = {
        row["telegram_user_id"]: row["id"]
        for row in await bank_pool.fetch("SELECT id,telegram_user_id FROM users")
    }
    stamp = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    for identity in (users[42], users[101]):
        issue = await _issue(bank_pool, identity, stamp)
        await _answer(bank_pool, identity, issue, 1, True, stamp)

    bot_id = 300000000 + int(uuid4().hex[:7], 16)
    companion_transport = Transport(fail="getChat")
    primary_transport = PrimaryTransport()
    primary = Bot("654321:PRIMARY", session=primary_transport)
    config = settings(
        database_url=os.environ["DATABASE_URL"], telegram_test_bot_token=f"{bot_id}:TEST"
    )
    install(monkeypatch, config, companion_transport)
    app = create_app(repository=PostgresRepository(bank_pool), bot=primary)
    try:
        async with app.router.lifespan_context(app):
            await app.state.companion.task
            companion = app.state.companion
            assert companion.status == "ready"
            service = companion.admin_service
            report = await service.load("learners", "7")
            assert report.unavailable is None
            assert len(report.data["rows"]) == 1
            learner = report.data["rows"][0]
            assert learner["user_id"] == users[101]
            assert learner["display_name"] == "Synthetic learner"
            assert learner["username"] == "SyntheticLearner"
            assert "telegram_user_id" not in learner
            assert sum(call.__api_method__ == "getChat" for call in primary_transport.calls) == 1

            # The owner is filtered again in the individual card and is never looked up.
            excluded = await service.load("learner", "7", key=str(users[42]))
            assert not excluded.data["found"]
            assert "display_name" not in excluded.data
            primary_transport.username = None
            refreshed = await service.load("learner", "7", key=str(users[101]), refresh=True)
            assert refreshed.data["display_name"] == "Synthetic learner"
            assert refreshed.data["username"] is None
            assert sum(call.__api_method__ == "getChat" for call in primary_transport.calls) == 2
            assert not any(call.__api_method__ == "getChat" for call in companion_transport.calls)
            assert companion.repository.schema == f"oge_test_bot_{bot_id}"
            assert companion.repository._pool is not bank_pool
        assert not primary_transport.closed
    finally:
        await primary.session.close()
        await bank_pool.execute(f'DROP SCHEMA IF EXISTS "oge_test_bot_{bot_id}" CASCADE')
