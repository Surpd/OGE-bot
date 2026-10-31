import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest

from app.math.oge9_scheduler import build_task9_candidate_batch
from app.math.oge10_scheduler import build_task10_candidate_batch
from app.math.scheduler import build_candidate_batch
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
            "migrations/0005_task10_sessions.sql",
        ):
            await pool.execute(await read_migration(migration))
        repository = PostgresRepository(pool)
        await repository.ensure_task9_session(user_id)
        batch = build_task9_candidate_batch({}, 76543)
        problem = await repository.advance_task9_problem(user_id, None, batch)
        problem_id = str(problem["problem_id"])
        await repository.save_user_state(user_id, "task9")
        assert await repository.task9_hint(user_id, problem_id) is not None
        assert await repository.task9_hint(user_id, problem_id) is not None
        assert await repository.task9_hint(user_id, problem_id) is None
        state = await repository.task9_state(user_id)
        assert state is not None and state["state"]["hints_used"] == 2
        assert await repository.set_task9_prompt_message(user_id, problem_id, 777001)
        await repository.save_user_state(user_id, "task9")
        late = await repository.task9_attempt(
            user_id, problem_id, str(problem["correct_answer"]), True, 777000, 777001
        )
        assert late == {"status": "stale", "attempt": 0}
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


@pytest.mark.asyncio
async def test_postgres_mixed_sessions_are_independent_and_stale_actions_are_serialized() -> None:
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
        repo = PostgresRepository(pool)
        await repo.register_user(user_id)
        await repo.ensure_task6_session(user_id)
        problem6 = await repo.advance_task6_problem(user_id, None, build_candidate_batch({}, 911))
        assert await repo.set_task6_prompt_message(user_id, str(problem6["problem_id"]), 810_006)
        await repo.save_user_state(user_id, "task6")

        await repo.ensure_task9_session(user_id)
        problem9 = await repo.advance_task9_problem(
            user_id, None, build_task9_candidate_batch({}, 919)
        )
        assert await repo.set_task9_prompt_message(user_id, str(problem9["problem_id"]), 810_009)
        await repo.save_user_state(user_id, "task9")

        await repo.ensure_task10_session(user_id)
        problem10 = await repo.advance_task10_problem(
            user_id, None, build_task10_candidate_batch({}, 9110)
        )
        assert await repo.set_task10_condition_message(
            user_id, str(problem10["problem_id"]), 810_010
        )
        await repo.save_user_state(user_id, "task10")

        restarted = PostgresRepository(pool)
        saved6 = await restarted.task6_state(user_id)
        saved9 = await restarted.task9_state(user_id)
        saved10 = await restarted.task10_state(user_id)
        assert saved6 is not None and saved9 is not None and saved10 is not None
        assert saved6["problem"]["problem_id"] == problem6["problem_id"]
        assert saved9["problem"]["problem_id"] == problem9["problem_id"]
        assert saved10["problem"]["problem_id"] == problem10["problem_id"]

        await restarted.save_user_state(user_id, "progress")
        stale6 = await restarted.task6_attempt(
            user_id,
            str(problem6["problem_id"]),
            str(problem6["correct_answer"]),
            True,
            telegram_message_id=810_106,
            expected_prompt_message_id=810_006,
        )
        assert stale6 == {"status": "stale", "attempt": 0}
        assert (await restarted.task6_progress(user_id))["attempts"] == 0
        stale10 = await restarted.task10_attempt(
            user_id,
            str(problem10["problem_id"]),
            str(problem10["correct_answer"]),
            True,
            telegram_message_id=810_110,
            expected_prompt_message_id=810_010,
        )
        assert stale10 == {"status": "stale", "attempt": 0}
        assert (await restarted.task10_progress(user_id))["attempts"] == 0

        await restarted.save_user_state(user_id, "task9")
        problem9_id = str(problem9["problem_id"])
        answer_and_pause = await asyncio.gather(
            restarted.task9_attempt(
                user_id,
                problem9_id,
                str(problem9["correct_answer"]),
                True,
                telegram_message_id=810_109,
                expected_prompt_message_id=810_009,
            ),
            restarted.transition_task_screen(
                user_id,
                "task9",
                problem9_id,
                "main_menu",
                expected_prompt_message_id=810_009,
            ),
        )
        outcome = answer_and_pause[0]
        assert answer_and_pause[1] is True
        assert outcome is not None and outcome["status"] in {"solved", "stale"}
        attempts = (await restarted.task9_progress(user_id))["attempts"]
        assert attempts in {0, 1}
        assert await restarted.task9_attempt(
            user_id,
            problem9_id,
            str(problem9["correct_answer"]),
            True,
            telegram_message_id=810_110,
            expected_prompt_message_id=810_009,
        ) == {"status": "stale", "attempt": 0}

        await restarted.save_user_state(user_id, "task9")
        current9 = await restarted.task9_state(user_id)
        assert current9 is not None
        candidates_a = build_task9_candidate_batch(current9["state"], 920)
        candidates_b = build_task9_candidate_batch(current9["state"], 921)
        concurrent_next = await asyncio.gather(
            restarted.advance_task9_problem(
                user_id,
                problem9_id,
                candidates_a,
                expected_screen="task9",
                expected_prompt_message_id=810_009,
            ),
            restarted.advance_task9_problem(
                user_id,
                problem9_id,
                candidates_b,
                expected_screen="task9",
                expected_prompt_message_id=810_009,
            ),
        )
        transitioned = [item for item in concurrent_next if item.get("_transitioned") is True]
        assert len(transitioned) == 1
        assert (await restarted.task9_progress(user_id))["issued"] == 2
    finally:
        async with pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id FROM users WHERE telegram_user_id = $1", user_id
            )
            if user is not None:
                await connection.execute("DELETE FROM users WHERE id = $1", user["id"])
        await pool.close()
