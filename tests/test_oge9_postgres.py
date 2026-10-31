import os
from uuid import uuid4

import asyncpg
import pytest

from app.math.oge9_scheduler import build_task9_candidate_batch
from app.persistence.repository import PostgresRepository, read_migration


@pytest.mark.asyncio
async def test_task9_postgres_hints_answers_and_snapshots_survive_repository_restart() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool = await asyncpg.create_pool(database_url)
    user_id = int(uuid4().int % (2**62)) + 1
    try:
        for migration in (
            "migrations/0001_foundation.sql",
            "migrations/0002_task6_training.sql",
            "migrations/0003_task6_session_quality.sql",
            "migrations/0004_task9_sessions.sql",
        ):
            await pool.execute(await read_migration(migration))
        repository = PostgresRepository(pool)
        await repository.ensure_task9_session(user_id)
        batch = build_task9_candidate_batch({}, 76543)
        problem = await repository.advance_task9_problem(user_id, None, batch)
        problem_id = str(problem["problem_id"])
        assert await repository.task9_hint(user_id, problem_id) is not None
        assert await repository.task9_hint(user_id, problem_id) is not None
        assert await repository.task9_hint(user_id, problem_id) is None
        state = await repository.task9_state(user_id)
        assert state is not None and state["state"]["hints_used"] == 2
        assert await repository.set_task9_prompt_message(user_id, problem_id, 777001)
        await repository.save_user_state(user_id, "task9")
        answer = await repository.task9_attempt(
            user_id, problem_id, str(problem["correct_answer"]), True, 777002, 777001
        )
        assert answer is not None and answer["status"] == "solved"

        restarted = PostgresRepository(pool)
        resumed = await restarted.task9_state(user_id)
        assert resumed is not None
        assert resumed["problem"]["problem_id"] == problem_id
        assert resumed["state"]["hints_used"] == 2
        assert resumed["state"]["attempts"] == 1
        progress = await restarted.task9_progress(user_id)
        assert progress["issued"] == 1
        assert progress["correct"] == 1
        assert progress["hints_used"] == 2
    finally:
        async with pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id FROM users WHERE telegram_user_id = $1", user_id
            )
            if user is not None:
                await connection.execute("DELETE FROM users WHERE id = $1", user["id"])
        await pool.close()
