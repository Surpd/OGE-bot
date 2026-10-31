import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest

from app.math.oge10_scheduler import build_task10_candidate_batch
from app.persistence.repository import PostgresRepository, read_migration


@pytest.mark.asyncio
async def test_task10_postgres_hints_answer_and_snapshot_survive_repository_restart() -> None:
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
            "migrations/0005_task10_sessions.sql",
        ):
            await pool.execute(await read_migration(migration))
        repository = PostgresRepository(pool)
        await repository.ensure_task10_session(user_id)
        first = build_task10_candidate_batch({}, 17101)[0]
        issued = await repository.advance_task10_problem(user_id, None, [first])
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task10")
        assert await repository.set_task10_condition_message(user_id, problem_id, 870001)
        assert await repository.task10_hint(user_id, problem_id, 870001)
        assert await repository.task10_hint(user_id, problem_id, 870001)
        assert await repository.task10_hint(user_id, problem_id, 870001) is None
        state = await repository.task10_state(user_id)
        assert state is not None and state["state"]["hints_used"] == 2

        restarted = PostgresRepository(pool)
        restored = await restarted.task10_state(user_id)
        assert restored is not None and restored["state"]["hints_used"] == 2
        assert restored["problem"]["problem_id"] == problem_id
        first_attempt = await restarted.task10_attempt(
            user_id, problem_id, "0", False, 870002, 870001
        )
        assert first_attempt is not None and first_attempt["status"] == "active"
        duplicate = await restarted.task10_attempt(user_id, problem_id, "0", False, 870002, 870001)
        assert duplicate is not None and duplicate["status"] == "duplicate"
        second_attempt = await restarted.task10_attempt(
            user_id, problem_id, str(issued["correct_answer"]), True, 870003, 870001
        )
        assert second_attempt is not None and second_attempt["status"] == "solved"
        progress = await restarted.task10_progress(user_id)
        assert progress["correct"] == 1 and progress["hints_used"] == 2
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()


@pytest.mark.asyncio
async def test_task10_postgres_concurrent_next_and_skip_transition_only_once() -> None:
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
            "migrations/0005_task10_sessions.sql",
        ):
            await pool.execute(await read_migration(migration))
        repository = PostgresRepository(pool)
        await repository.ensure_task10_session(user_id)
        first = build_task10_candidate_batch({}, 17102)[0]
        issued = await repository.advance_task10_problem(user_id, None, [first])
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task10")
        await repository.set_task10_condition_message(user_id, problem_id, 870101)
        await repository.task10_reveal_solution(user_id, problem_id, 870101)
        candidates = build_task10_candidate_batch(
            {
                "family_queue": issued.get("_family_queue_after", []),
                "recent_fingerprints": [issued["fingerprint"]],
            },
            17103,
        )
        results = await asyncio.gather(
            repository.advance_task10_problem(
                user_id,
                problem_id,
                candidates,
                expected_screen="task10",
                expected_prompt_message_id=870101,
                skip_active=False,
            ),
            repository.advance_task10_problem(
                user_id,
                problem_id,
                candidates,
                expected_screen="task10",
                expected_prompt_message_id=870101,
                skip_active=False,
            ),
        )
        assert sum(result.get("_transitioned") is True for result in results) == 1
        current = await repository.task10_state(user_id)
        assert current is not None and current["problem"]["problem_id"] != problem_id
        assert (await repository.task10_progress(user_id))["issued"] == 2
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()
