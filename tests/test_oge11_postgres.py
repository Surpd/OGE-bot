from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest

from app.math.oge11 import all_matching_codes, generate
from app.persistence.repository import PostgresRepository, read_migration


async def _prepare(database_url: str) -> tuple[asyncpg.Pool, PostgresRepository, int]:
    pool = await asyncpg.create_pool(database_url)
    for migration in sorted(__import__("pathlib").Path("migrations").glob("*.sql")):
        await pool.execute(await read_migration(str(migration)))
    user_id = int(uuid4().int % (2**62)) + 1
    repository = PostgresRepository(pool)
    await repository.register_user(user_id)
    await repository.ensure_task11_session(user_id)
    return pool, repository, user_id


def _problem(seed: int) -> dict[str, object]:
    return generate("OGE11-F01", seed).to_snapshot()


@pytest.mark.asyncio
async def test_task11_postgres_snapshot_png_attempts_and_history_survive_restart() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool, repository, user_id = await _prepare(database_url)
    try:
        snapshot = _problem(11101)
        issued = await repository.advance_task11_problem(user_id, None, [snapshot])
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task11")
        assert await repository.set_task11_condition_message(user_id, problem_id, 911001)
        assert await repository.task11_hint(user_id, problem_id, 911001)
        wrong = next(
            answer for answer in all_matching_codes() if answer != str(issued["correct_answer"])
        )
        first = await repository.task11_attempt(user_id, problem_id, wrong, False, 911002, 911001)
        assert first is not None and first["status"] == "active"
        duplicate = await repository.task11_attempt(
            user_id, problem_id, wrong, False, 911002, 911001
        )
        assert duplicate is not None and duplicate["status"] == "duplicate"

        restarted = PostgresRepository(pool)
        restored = await restarted.task11_state(user_id)
        assert restored is not None
        assert restored["problem"]["problem_id"] == problem_id
        assert restored["problem"]["png_base64"] == snapshot["png_base64"]
        assert restored["problem"]["image_sha256"] == snapshot["image_sha256"]
        second = await restarted.task11_attempt(
            user_id, problem_id, str(issued["correct_answer"]), True, 911003, 911001
        )
        assert second is not None and second["status"] == "solved"
        progress = await restarted.task11_progress(user_id)
        assert progress["attempts"] == 2 and progress["correct"] == 1
        history = await restarted.task11_history(user_id)
        assert history[0]["condition"] == snapshot["condition"]
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()


@pytest.mark.asyncio
async def test_task11_postgres_concurrent_skip_advances_once() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool, repository, user_id = await _prepare(database_url)
    try:
        first = _problem(11102)
        issued = await repository.advance_task11_problem(user_id, None, [first])
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task11")
        assert await repository.set_task11_condition_message(user_id, problem_id, 911101)
        candidates = [_problem(11103), _problem(11104)]
        results = await asyncio.gather(
            *(
                repository.advance_task11_problem(
                    user_id, problem_id, candidates, "task11", 911101, True
                )
                for _ in range(2)
            )
        )
        assert sum(result.get("_transitioned") is True for result in results) == 1
        state = await repository.task11_state(user_id)
        assert state is not None and state["problem"]["problem_id"] != problem_id
        progress = await repository.task11_progress(user_id)
        assert progress["issued"] == 2 and progress["skipped"] == 1
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()
