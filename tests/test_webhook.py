import asyncio
import os
import secrets
from typing import cast
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
from app.math.scheduler import build_candidate_batch
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
        await pool.execute(await read_migration("migrations/0002_task6_training.sql"))
        await pool.execute(await read_migration("migrations/0002_task6_training.sql"))
        await pool.execute(await read_migration("migrations/0003_task6_session_quality.sql"))
        await pool.execute(await read_migration("migrations/0003_task6_session_quality.sql"))
        await pool.execute(await read_migration("migrations/0004_task9_sessions.sql"))
        await pool.execute(await read_migration("migrations/0004_task9_sessions.sql"))
        await pool.execute(await read_migration("migrations/0005_task10_sessions.sql"))
        await pool.execute(await read_migration("migrations/0005_task10_sessions.sql"))
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
async def test_postgres_task6_flow_survives_restart_and_locks_duplicate_answers() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool = await asyncpg.create_pool(database_url)
    telegram_user_id = 800_000_000 + secrets.randbelow(100_000_000)
    try:
        await pool.execute(await read_migration("migrations/0001_foundation.sql"))
        await pool.execute(await read_migration("migrations/0002_task6_training.sql"))
        await pool.execute(await read_migration("migrations/0003_task6_session_quality.sql"))
        await pool.execute(await read_migration("migrations/0004_task9_sessions.sql"))
        await pool.execute(await read_migration("migrations/0005_task10_sessions.sql"))
        repository = PostgresRepository(pool)
        await repository.register_user(telegram_user_id)
        session_id = await repository.ensure_task6_session(telegram_user_id)
        issued = await repository.advance_task6_problem(
            telegram_user_id, None, build_candidate_batch({}, 17)
        )
        duplicate_issue = await repository.advance_task6_problem(
            telegram_user_id, None, build_candidate_batch({}, 18)
        )
        assert duplicate_issue["problem_id"] == issued["problem_id"]

        restarted_repository = PostgresRepository(pool)
        restored = await restarted_repository.task6_state(telegram_user_id)
        assert restored is not None
        assert restored["session_id"] == session_id
        restored_problem = restored["problem"]
        assert isinstance(restored_problem, dict)
        assert restored_problem["problem_id"] == issued["problem_id"]

        expected_problem_id = str(issued["problem_id"])
        assert await restarted_repository.set_task6_prompt_message(
            telegram_user_id, expected_problem_id, 71_001
        )
        await restarted_repository.save_user_state(telegram_user_id, "task6")
        assert await restarted_repository.task6_hint(telegram_user_id, expected_problem_id)
        assert await restarted_repository.task6_hint(telegram_user_id, expected_problem_id)
        after_hints = await PostgresRepository(pool).task6_state(telegram_user_id)
        assert after_hints is not None
        assert after_hints["state"]["hints_used"] == 2
        assert after_hints["state"]["input_prompt_message_id"] == 71_001
        assert (await PostgresRepository(pool).task6_progress(telegram_user_id))["hints_used"] == 2

        late = await restarted_repository.task6_attempt(
            telegram_user_id,
            expected_problem_id,
            str(issued["correct_answer"]),
            True,
            telegram_message_id=71_000,
            expected_prompt_message_id=71_001,
        )
        assert late == {"status": "stale", "attempt": 0}

        await restarted_repository.save_user_state(telegram_user_id, "main_menu")
        paused_answer = await restarted_repository.task6_attempt(
            telegram_user_id,
            expected_problem_id,
            str(issued["correct_answer"]),
            True,
            telegram_message_id=49_999,
            expected_prompt_message_id=71_001,
        )
        assert paused_answer == {"status": "stale", "attempt": 0}
        assert (await restarted_repository.task6_progress(telegram_user_id))["attempts"] == 0
        await restarted_repository.save_user_state(telegram_user_id, "task6")

        first = await restarted_repository.task6_attempt(
            telegram_user_id, expected_problem_id, "999", False
        )
        assert first is not None and first["status"] == "active"
        correct = str(issued["correct_answer"])
        concurrent_answers = await asyncio.gather(
            restarted_repository.task6_attempt(
                telegram_user_id, expected_problem_id, correct, True, telegram_message_id=50_001
            ),
            restarted_repository.task6_attempt(
                telegram_user_id, expected_problem_id, correct, True, telegram_message_id=50_001
            ),
        )
        assert (
            sum(result is not None and result["attempt"] == 2 for result in concurrent_answers) == 1
        )
        assert (
            sum(result is not None and result["attempt"] == 0 for result in concurrent_answers) == 1
        )
        progress = await restarted_repository.task6_progress(telegram_user_id)
        assert progress["issued"] == 1
        assert progress["answered"] == 1
        assert progress["correct"] == 1
        assert progress["attempts"] == 2
        assert progress["second_attempts"] == 1
        assert progress["solved_second_try"] == 1

        before_next = await restarted_repository.task6_state(telegram_user_id)
        assert before_next is not None
        candidates_a = build_candidate_batch(cast(dict[str, object], before_next["state"]), 19)
        candidates_b = build_candidate_batch(cast(dict[str, object], before_next["state"]), 20)
        simultaneous_next = await asyncio.gather(
            restarted_repository.advance_task6_problem(
                telegram_user_id, expected_problem_id, candidates_a
            ),
            restarted_repository.advance_task6_problem(
                telegram_user_id, expected_problem_id, candidates_b
            ),
        )
        issued_next = simultaneous_next[0]
        assert issued_next["problem_id"] != issued["problem_id"]
        assert simultaneous_next[1]["problem_id"] == issued_next["problem_id"]
        assert (await restarted_repository.task6_progress(telegram_user_id))["issued"] == 2

        next_id = str(issued_next["problem_id"])
        next_state = await restarted_repository.task6_state(telegram_user_id)
        assert next_state is not None
        skip_candidates = build_candidate_batch(cast(dict[str, object], next_state["state"]), 21)
        skip_task = restarted_repository.advance_task6_problem(
            telegram_user_id, next_id, skip_candidates, skip_active=True
        )
        answer_task = restarted_repository.task6_attempt(telegram_user_id, next_id, "999", False)
        skipped_or_answered, answer_result = await asyncio.gather(skip_task, answer_task)
        assert skipped_or_answered["problem_id"] != next_id
        assert answer_result is None or answer_result["status"] in {"stale", "active"}
        if answer_result is None or answer_result["status"] == "stale":
            assert (await restarted_repository.task6_progress(telegram_user_id))["attempts"] == 2
        else:
            assert (await restarted_repository.task6_progress(telegram_user_id))["attempts"] == 3
        old_outcome = await pool.fetchval(
            "SELECT outcome FROM issued_problems WHERE id = $1", next_id
        )
        assert old_outcome == "skipped"
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id = $1", telegram_user_id)
        await pool.close()


@pytest.mark.asyncio
async def test_migration_has_rls_and_update_uniqueness() -> None:
    sql = await read_migration("migrations/0001_foundation.sql")
    assert "telegram_updates (\n    update_id bigint PRIMARY KEY" in sql
    for table in ("users", "sessions", "issued_problems", "attempts", "telegram_updates"):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
    training_sql = await read_migration("migrations/0002_task6_training.sql")
    assert "sessions_active_problem_id_fkey" in training_sql
    assert "sessions_one_active_task6_per_user" in training_sql
    quality_sql = await read_migration("migrations/0003_task6_session_quality.sql")
    assert "solution_viewed_at" in quality_sql
    assert "hints_used" in quality_sql
    assert "selection_attempts" in quality_sql
    task9_sql = await read_migration("migrations/0004_task9_sessions.sql")
    assert "sessions_one_active_task9_per_user" in task9_sql
    task10_sql = await read_migration("migrations/0005_task10_sessions.sql")
    assert "sessions_one_active_task10_per_user" in task10_sql


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
    repository = MemoryRepository()
    message = AsyncMock()
    message.from_user = User(id=12348, is_bot=False, first_name="Student")
    await menu_section(message, repository)
    assert "не включён" in message.answer.await_args.args[0]
    assert await repository.user_state(12348) == "main_menu"


@pytest.mark.asyncio
async def test_number_menu_saves_navigation_state() -> None:
    repository = MemoryRepository()
    await repository.register_user(12346)
    message = AsyncMock()
    message.from_user = User(id=12346, is_bot=False, first_name="Student")
    await choose_number(message, repository)
    assert await repository.user_state(12346) == "number_selection"
    assert "Выберите номер" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_continue_button_handles_missing_session() -> None:
    message = AsyncMock()
    message.from_user = User(id=12347, is_bot=False, first_name="Student")
    await continue_session(message, MemoryRepository())
    assert "нет незавершённой тренировки" in message.answer.await_args.args[0]


def test_production_startup_registers_the_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("WEBHOOK_BASE_URL", "https://oge-trainer.example.onrender.com/")
    get_settings.cache_clear()
    set_webhook = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "set_webhook", set_webhook)
    app = create_app(repository=MemoryRepository(), bot=Bot(token="123456:TEST_TOKEN"))
    with TestClient(app):
        pass
    set_webhook.assert_awaited_once_with(
        url="https://oge-trainer.example.onrender.com/telegram/webhook",
        secret_token="test-webhook-secret",
        drop_pending_updates=False,
    )
    get_settings.cache_clear()


def test_main_menu_contains_the_product_sections() -> None:
    markup = main_menu()
    labels = {button.text for row in markup.keyboard for button in row}
    assert labels == set(MAIN_MENU) - {"▶ Продолжить"}
