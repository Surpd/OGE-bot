import os
from unittest.mock import AsyncMock

import asyncpg
import pytest
from aiogram import Bot
from aiogram.types import User
from fastapi.testclient import TestClient

from app.bot.menu import MAIN_MENU, main_menu
from app.bot.router import choose_number, continue_session, menu_section, start
from app.config import get_settings
from app.main import create_app
from app.persistence.repository import MemoryRepository, PostgresRepository, read_migration


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
    get_settings.cache_clear()
    repository = MemoryRepository()
    bot = Bot(token="123456:TEST_TOKEN")
    app = create_app(repository=repository, bot=bot, run_schema_migrations=False)
    with TestClient(app) as test_client:
        yield test_client, repository
    get_settings.cache_clear()


def test_health(client) -> None:
    response = client[0].get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_secret_is_required(client) -> None:
    response = client[0].post("/telegram/webhook", json={"update_id": 10})
    assert response.status_code == 403


def test_update_is_idempotent(client) -> None:
    test_client, repository = client
    headers = {"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"}
    payload = {
        "update_id": 100,
        "inline_query": {
            "id": "query-100",
            "from": {"id": 1, "is_bot": False, "first_name": "Test"},
            "query": "",
            "offset": "",
        },
    }
    first = test_client.post("/telegram/webhook", json=payload, headers=headers)
    replay = test_client.post("/telegram/webhook", json=payload, headers=headers)
    assert first.status_code == replay.status_code == 200
    assert repository.updates[100] == "processed"
    assert len(repository.updates) == 1


@pytest.mark.asyncio
async def test_postgres_registration_and_state_survive_new_repository() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool = await asyncpg.create_pool(database_url)
    try:
        await pool.execute(await read_migration("migrations/0001_foundation.sql"))
        await pool.execute("DELETE FROM telegram_updates WHERE update_id = 444")
        first = PostgresRepository(pool)
        assert await pool.fetchval(
            "SELECT relrowsecurity FROM pg_class WHERE oid = 'users'::regclass"
        )
        assert await pool.fetchval(
            "SELECT relrowsecurity FROM pg_class WHERE oid = 'telegram_updates'::regclass"
        )
        assert await first.claim_update(444)
        await first.finish_update(444)
        assert not await first.claim_update(444)
        await pool.execute("DELETE FROM users WHERE telegram_user_id = $1", 987654321)
        await first.register_user(987654321)
        await first.register_user(987654321)
        await first.save_user_state(987654321, "number_selection")
        count = await pool.fetchval(
            "SELECT count(*) FROM users WHERE telegram_user_id = $1", 987654321
        )
        assert count == 1
        user_id = await pool.fetchval("SELECT id FROM users WHERE telegram_user_id = $1", 987654321)
        await pool.execute(
            "INSERT INTO sessions (user_id, mode, state) VALUES ($1, $2, $3::jsonb)",
            user_id,
            "practice",
            '{"step":"menu"}',
        )
        after_restart = PostgresRepository(pool)
        assert await after_restart.user_state(987654321) == "number_selection"
        session = await after_restart.current_session(987654321)
        assert session is not None
        assert session["mode"] == "practice"
        await pool.execute("DELETE FROM users WHERE telegram_user_id = $1", 987654321)
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_migration_has_rls_and_update_uniqueness() -> None:
    sql = await read_migration("migrations/0001_foundation.sql")
    assert "telegram_updates (\n    update_id bigint PRIMARY KEY" in sql
    for table in ("users", "sessions", "issued_problems", "attempts", "telegram_updates"):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql


@pytest.mark.asyncio
async def test_start_registers_user_and_returns_main_menu() -> None:
    repository = MemoryRepository()
    message = AsyncMock()
    message.from_user = User(id=12345, is_bot=False, first_name="Student")
    await start(message, repository)
    assert repository.users == {12345}
    assert repository.states[12345] == "main_menu"
    message.answer.assert_awaited_once()
    assert "Привет" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_training_menu_button_returns_safe_placeholder() -> None:
    message = AsyncMock()
    await menu_section(message)
    assert "в разработке" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_number_menu_saves_navigation_state() -> None:
    repository = MemoryRepository()
    await repository.register_user(12346)
    message = AsyncMock()
    message.from_user = User(id=12346, is_bot=False, first_name="Student")
    await choose_number(message, repository)
    assert await repository.user_state(12346) == "number_selection"
    assert "готовятся" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_continue_button_handles_missing_session() -> None:
    message = AsyncMock()
    message.from_user = User(id=12347, is_bot=False, first_name="Student")
    await continue_session(message, MemoryRepository())
    assert "нет незавершённой тренировки" in message.answer.await_args.args[0]


def test_main_menu_contains_the_product_sections() -> None:
    markup = main_menu()
    labels = {button.text for row in markup.keyboard for button in row}
    assert labels == set(MAIN_MENU) - {"▶ Продолжить"}
