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
async def test_task10_postgres_concurrent_next_after_solution_viewed_advances_once() -> None:
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


async def _new_task10_repository(database_url: str) -> tuple[asyncpg.Pool, PostgresRepository, int]:
    pool = await asyncpg.create_pool(database_url)
    user_id = int(uuid4().int % (2**62)) + 1
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
    return pool, repository, user_id


def _distinct_task10_candidates(problem: dict[str, object], seed: int) -> list[dict[str, object]]:
    return build_task10_candidate_batch(
        {
            "family_queue": problem.get("_family_queue_after", []),
            "recent_fingerprints": [problem["fingerprint"]],
            "last_family_id": problem.get("_last_family_after"),
        },
        seed,
    )


@pytest.mark.asyncio
async def test_task10_postgres_skip_marks_outcome_and_updates_statistics() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool, repository, user_id = await _new_task10_repository(database_url)
    try:
        first = build_task10_candidate_batch({}, 17201)[0]
        issued = await repository.advance_task10_problem(user_id, None, [first])
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task10")
        assert await repository.set_task10_condition_message(user_id, problem_id, 871001)
        candidates = _distinct_task10_candidates(issued, 17202)
        skipped = await repository.advance_task10_problem(
            user_id,
            problem_id,
            candidates,
            expected_screen="task10",
            expected_prompt_message_id=871001,
            skip_active=True,
        )
        assert skipped.get("_transitioned") is True
        assert skipped["problem_id"] != problem_id
        progress = await repository.task10_progress(user_id)
        assert progress["issued"] == 2 and progress["skipped"] == 1
        assert progress["answered"] == progress["correct"] == 0
        current = await repository.task10_state(user_id)
        assert current is not None
        assert current["problem"]["problem_id"] == skipped["problem_id"]
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("completion", ["solved", "solution_viewed"])
async def test_task10_postgres_next_after_solved_or_solution_viewed(completion: str) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool, repository, user_id = await _new_task10_repository(database_url)
    try:
        first = build_task10_candidate_batch({}, 17301)[0]
        issued = await repository.advance_task10_problem(user_id, None, [first])
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task10")
        assert await repository.set_task10_condition_message(user_id, problem_id, 872001)
        if completion == "solved":
            result = await repository.task10_attempt(
                user_id,
                problem_id,
                str(issued["correct_answer"]),
                True,
                telegram_message_id=872002,
                expected_prompt_message_id=872001,
            )
            assert result is not None and result["status"] == "solved"
        else:
            assert await repository.task10_reveal_solution(user_id, problem_id, 872001)
        candidates = _distinct_task10_candidates(issued, 17302)
        next_task = await repository.advance_task10_problem(
            user_id,
            problem_id,
            candidates,
            expected_screen="task10",
            expected_prompt_message_id=872001,
            skip_active=False,
        )
        assert next_task.get("_transitioned") is True
        progress = await repository.task10_progress(user_id)
        assert progress["issued"] == 2 and progress["skipped"] == 0
        assert progress["correct"] == (1 if completion == "solved" else 0)
        assert progress["solutions_viewed"] == (1 if completion == "solution_viewed" else 0)
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()


@pytest.mark.asyncio
async def test_task10_postgres_concurrent_answer_and_skip_has_one_atomic_outcome() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool, repository, user_id = await _new_task10_repository(database_url)
    try:
        first = build_task10_candidate_batch({}, 17401)[0]
        issued = await repository.advance_task10_problem(user_id, None, [first])
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task10")
        assert await repository.set_task10_condition_message(user_id, problem_id, 873001)
        candidates = _distinct_task10_candidates(issued, 17402)
        answer_result, skip_result = await asyncio.gather(
            repository.task10_attempt(
                user_id,
                problem_id,
                str(issued["correct_answer"]),
                True,
                telegram_message_id=873002,
                expected_prompt_message_id=873001,
            ),
            repository.advance_task10_problem(
                user_id,
                problem_id,
                candidates,
                expected_screen="task10",
                expected_prompt_message_id=873001,
                skip_active=True,
            ),
        )
        progress = await repository.task10_progress(user_id)
        state = await repository.task10_state(user_id)
        assert state is not None
        if answer_result is not None and answer_result["status"] == "solved":
            assert skip_result.get("_transitioned") is False
            assert progress["issued"] == 1 and progress["correct"] == 1 and progress["skipped"] == 0
            assert state["problem"]["problem_id"] == problem_id
        else:
            assert answer_result is not None and answer_result["status"] == "stale"
            assert skip_result.get("_transitioned") is True
            assert progress["issued"] == 2 and progress["correct"] == 0 and progress["skipped"] == 1
            assert state["problem"]["problem_id"] != problem_id
        assert progress["issued"] == 1 + progress["skipped"]
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()


@pytest.mark.asyncio
async def test_task10_postgres_duplicate_skip_callback_only_issues_one_current_problem() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool, repository, user_id = await _new_task10_repository(database_url)
    try:
        first = build_task10_candidate_batch({}, 17501)[0]
        issued = await repository.advance_task10_problem(user_id, None, [first])
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task10")
        assert await repository.set_task10_condition_message(user_id, problem_id, 874001)
        candidates = _distinct_task10_candidates(issued, 17502)
        results = await asyncio.gather(
            *(
                repository.advance_task10_problem(
                    user_id,
                    problem_id,
                    candidates,
                    expected_screen="task10",
                    expected_prompt_message_id=874001,
                    skip_active=True,
                )
                for _ in range(2)
            )
        )
        assert sum(result.get("_transitioned") is True for result in results) == 1
        current = await repository.task10_state(user_id)
        assert current is not None and current["problem"]["problem_id"] != problem_id
        progress = await repository.task10_progress(user_id)
        assert progress["issued"] == 2 and progress["skipped"] == 1
        stale_repeat = await repository.advance_task10_problem(
            user_id,
            problem_id,
            candidates,
            expected_screen="task10",
            expected_prompt_message_id=874001,
            skip_active=True,
        )
        assert stale_repeat.get("_transitioned") is False
        assert (await repository.task10_progress(user_id))["issued"] == 2
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()
