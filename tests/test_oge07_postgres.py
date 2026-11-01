"""PostgreSQL lifecycle checks for OGE-7 snapshots and atomic transitions.

These tests apply the migrations directly to the CI PostgreSQL 17 service. They do
not assert that the current application's startup path discovers migration 0010.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from uuid import uuid4

import asyncpg
import pytest

from app.math.oge07_scheduler import build_task7_candidate_batch
from app.persistence.repository import PostgresRepository, read_migration

BASE_MIGRATIONS = (
    "migrations/0001_foundation.sql",
    "migrations/0002_task6_training.sql",
    "migrations/0003_task6_session_quality.sql",
    "migrations/0004_task9_sessions.sql",
    "migrations/0005_task10_sessions.sql",
    "migrations/0006_task12_sessions.sql",
    "migrations/0007_task14_sessions.sql",
    "migrations/0008_task13_sessions.sql",
    "migrations/0009_task8_sessions.sql",
)
TASK7_MIGRATION = "migrations/0010_task7_sessions.sql"


async def _prepare(pool: asyncpg.Pool) -> None:
    for migration in (*BASE_MIGRATIONS, TASK7_MIGRATION):
        await pool.execute(await read_migration(migration))


async def _new_repository(database_url: str) -> tuple[asyncpg.Pool, PostgresRepository, int]:
    pool = await asyncpg.create_pool(database_url)
    await _prepare(pool)
    user_id = int(uuid4().int % (2**62)) + 1
    repository = PostgresRepository(pool)
    await repository.ensure_task7_session(user_id)
    return pool, repository, user_id


def _candidates(family: str, seed: int) -> list[dict[str, object]]:
    return build_task7_candidate_batch({}, seed, family_ids=(family,))


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ("OGE07-C01", "OGE07-N01"))
async def test_task7_postgres_restores_text_and_png_snapshots_and_answers(
    family: str,
) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool, repository, user_id = await _new_repository(database_url)
    try:
        issued = await repository.advance_task7_problem(user_id, None, _candidates(family, 701))
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task7")
        assert await repository.set_task7_condition_message(user_id, problem_id, 77001)
        assert await repository.task7_hint(user_id, problem_id, 77001)

        restarted = PostgresRepository(pool)
        restored = await restarted.task7_state(user_id)
        assert restored is not None
        snapshot = restored["problem"]
        assert snapshot["problem_id"] == problem_id
        assert restored["state"]["hints_used"] == 1
        if family == "OGE07-N01":
            saved_graph_model = json.loads(json.dumps(issued["graph_model"]))
            assert snapshot["graph_model"] == saved_graph_model
            assert base64.b64decode(str(snapshot["graph_png_base64"]))
        correct = await restarted.task7_attempt(
            user_id, problem_id, str(snapshot["correct_answer"]), True, 77002, 77001
        )
        assert correct is not None and correct["status"] == "solved"
        duplicate = await restarted.task7_attempt(
            user_id, problem_id, str(snapshot["correct_answer"]), True, 77002, 77001
        )
        assert duplicate is not None and duplicate["status"] == "duplicate"
        progress = await restarted.task7_progress(user_id)
        assert progress["issued"] == progress["correct"] == progress["attempts"] == 1
        assert progress["hints_used"] == 1
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()


@pytest.mark.asyncio
async def test_task7_postgres_concurrent_answers_are_serialized_and_screen_isolated() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool, repository, user_id = await _new_repository(database_url)
    try:
        issued = await repository.advance_task7_problem(
            user_id, None, _candidates("OGE07-C01", 702)
        )
        task7_session_id = await repository.ensure_task7_session(user_id)
        task8_session_id = await repository.ensure_task8_session(user_id)
        assert task7_session_id != task8_session_id
        assert (await repository.task8_progress(user_id))["issued"] == 0
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task7")
        assert await repository.set_task7_condition_message(user_id, problem_id, 77101)

        stale = await repository.task7_attempt(user_id, problem_id, "1", False, 77100, 77101)
        assert stale is not None and stale["status"] == "stale"
        await repository.save_user_state(user_id, "task8")
        paused = await repository.task7_attempt(user_id, problem_id, "1", False, 77102, 77101)
        assert paused is not None and paused["status"] == "stale"
        await repository.save_user_state(user_id, "task7")

        results = await asyncio.gather(
            repository.task7_attempt(user_id, problem_id, "1", False, 77103, 77101),
            repository.task7_attempt(user_id, problem_id, "2", False, 77104, 77101),
        )
        assert sorted(str(result["status"]) for result in results if result) == [
            "active",
            "failed",
        ]
        state = await repository.task7_state(user_id)
        assert state is not None and state["state"]["attempts"] == 2
        progress = await repository.task7_progress(user_id)
        assert progress["attempts"] == 2 and progress["answered"] == 1
        assert (await repository.task8_progress(user_id))["attempts"] == 0
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()


@pytest.mark.asyncio
async def test_task7_migration_is_idempotent() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool = await asyncpg.create_pool(database_url)
    try:
        await _prepare(pool)
        await pool.execute(await read_migration(TASK7_MIGRATION))
        index_count = await pool.fetchval(
            "SELECT count(*) FROM pg_indexes WHERE indexname='sessions_one_active_task7_per_user'"
        )
        assert index_count == 1
    finally:
        await pool.close()
