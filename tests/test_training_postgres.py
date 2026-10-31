import os
from uuid import uuid4

import asyncpg
import pytest

from app.math.oge9_scheduler import build_task9_candidate_batch
from app.math.scheduler import build_candidate_batch
from app.persistence.repository import PostgresRepository, read_migration


@pytest.mark.parametrize("task_number", [6, 9])
@pytest.mark.asyncio
async def test_postgres_skip_next_answer_solution_and_next_transitions(task_number: int) -> None:
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
        await repository.register_user(user_id)
        if task_number == 6:
            await repository.ensure_task6_session(user_id)
            initial = await repository.advance_task6_problem(
                user_id, None, build_candidate_batch({}, 61001)
            )
            advance = repository.advance_task6_problem
            condition = repository.set_task6_condition_message
            answer = repository.task6_attempt
            reveal = repository.task6_reveal_solution
            progress = repository.task6_progress
            candidates = build_candidate_batch
        else:
            await repository.ensure_task9_session(user_id)
            initial = await repository.advance_task9_problem(
                user_id, None, build_task9_candidate_batch({}, 91001)
            )
            advance = repository.advance_task9_problem
            condition = repository.set_task9_condition_message
            answer = repository.task9_attempt
            reveal = repository.task9_reveal_solution
            progress = repository.task9_progress
            candidates = build_task9_candidate_batch

        await repository.save_user_state(user_id, f"task{task_number}")
        initial_id = str(initial["problem_id"])
        initial_prompt = 910_000 + task_number * 10
        assert await condition(user_id, initial_id, initial_prompt)
        if task_number == 6:
            skipped_state = await repository.task6_state(user_id)
        else:
            skipped_state = await repository.task9_state(user_id)
        assert skipped_state is not None
        skipped_next = await advance(
            user_id,
            initial_id,
            candidates(skipped_state["state"], 61002 + task_number),
            expected_screen=f"task{task_number}",
            expected_prompt_message_id=initial_prompt,
            skip_active=True,
        )
        assert skipped_next.get("_transitioned") is True
        next_id = str(skipped_next["problem_id"])
        assert next_id != initial_id
        assert (await progress(user_id))["skipped"] == 1

        next_prompt = initial_prompt + 100
        assert await condition(user_id, next_id, next_prompt)
        solved = await answer(
            user_id,
            next_id,
            str(skipped_next["correct_answer"]),
            True,
            telegram_message_id=next_prompt + 1,
            expected_prompt_message_id=next_prompt,
        )
        assert solved is not None and solved["status"] == "solved"
        viewed_solved = await reveal(
            user_id, next_id, expected_prompt_message_id=next_prompt
        )
        assert viewed_solved is not None and viewed_solved["status"] == "solved"
        if task_number == 6:
            solved_state = await repository.task6_state(user_id)
        else:
            solved_state = await repository.task9_state(user_id)
        assert solved_state is not None and solved_state["state"]["status"] == "solved"
        assert (await progress(user_id))["correct"] == 1
        assert (await progress(user_id))["solutions_viewed"] == 1

        solved_next = await advance(
            user_id,
            next_id,
            candidates(solved_state["state"], 61010 + task_number),
            expected_screen=f"task{task_number}",
            expected_prompt_message_id=next_prompt,
        )
        assert solved_next.get("_transitioned") is True
        solution_id = str(solved_next["problem_id"])
        solution_prompt = next_prompt + 100
        assert await condition(user_id, solution_id, solution_prompt)
        viewed_active = await reveal(
            user_id, solution_id, expected_prompt_message_id=solution_prompt
        )
        assert viewed_active is not None and viewed_active["status"] == "active"
        if task_number == 6:
            solution_state = await repository.task6_state(user_id)
        else:
            solution_state = await repository.task9_state(user_id)
        assert solution_state is not None
        assert solution_state["state"]["status"] == "solution_viewed"
        assert (await progress(user_id))["solutions_viewed"] == 2

        after_solution = await advance(
            user_id,
            solution_id,
            candidates(solution_state["state"], 61020 + task_number),
            expected_screen=f"task{task_number}",
            expected_prompt_message_id=solution_prompt,
        )
        assert after_solution.get("_transitioned") is True
    finally:
        async with pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id FROM users WHERE telegram_user_id = $1", user_id
            )
            if user is not None:
                await connection.execute("DELETE FROM users WHERE id = $1", user["id"])
        await pool.close()
