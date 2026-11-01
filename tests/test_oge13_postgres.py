from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest

from app.math import oge13_scheduler
from app.math.oge13_scheduler import build_task13_candidate_batch
from app.persistence.repository import PostgresRepository, read_migration


@pytest.mark.asyncio
async def test_task13_postgres_choice_callback_is_idempotent_and_snapshot_survives_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    monkeypatch.setattr(oge13_scheduler, "ENABLED_FAMILIES", ("OGE13-L01",))
    pool = await asyncpg.create_pool(database_url)
    user_id = int(uuid4().int % (2**62)) + 1
    try:
        version = await pool.fetchval("SHOW server_version_num")
        assert int(version) >= 170000
        for migration in (
            "migrations/0001_foundation.sql",
            "migrations/0002_task6_training.sql",
            "migrations/0003_task6_session_quality.sql",
            "migrations/0004_task9_sessions.sql",
            "migrations/0005_task10_sessions.sql",
            "migrations/0006_task12_sessions.sql",
            "migrations/0007_task14_sessions.sql",
            "migrations/0008_task13_sessions.sql",
        ):
            sql = await read_migration(migration)
            await pool.execute(sql)
            if migration.endswith("0008_task13_sessions.sql"):
                await pool.execute(sql)

        repository = PostgresRepository(pool)
        await repository.ensure_task13_session(user_id)
        first = build_task13_candidate_batch({}, 131301)[0]
        issued = await repository.advance_task13_problem(user_id, None, [first])
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task13")
        assert await repository.set_task13_condition_message(user_id, problem_id, 931301)

        wrong = "2" if issued["correct_answer"] != "2" else "1"
        attempt = await repository.task13_attempt(
            user_id, problem_id, wrong, False, None, 931301, "callback-131301"
        )
        assert attempt is not None and attempt["status"] == "active"
        restarted = PostgresRepository(pool)
        duplicate = await restarted.task13_attempt(
            user_id, problem_id, wrong, False, None, 931301, "callback-131301"
        )
        assert duplicate is not None and duplicate["status"] == "duplicate"
        restored = await restarted.task13_state(user_id)
        assert restored is not None and restored["problem"]["problem_id"] == problem_id
        assert restored["state"]["attempts"] == 1
        solved = await restarted.task13_attempt(
            user_id, problem_id, str(issued["correct_answer"]), True, 931302, 931301
        )
        assert solved is not None and solved["status"] == "solved"
        progress = await restarted.task13_progress(user_id)
        assert progress["attempts"] == 2 and progress["correct"] == 1
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()


@pytest.mark.asyncio
async def test_task13_postgres_concurrent_answer_and_skip_have_one_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    monkeypatch.setattr(oge13_scheduler, "ENABLED_FAMILIES", ("OGE13-L01",))
    pool = await asyncpg.create_pool(database_url)
    user_id = int(uuid4().int % (2**62)) + 1
    try:
        for migration in (
            "migrations/0001_foundation.sql",
            "migrations/0002_task6_training.sql",
            "migrations/0003_task6_session_quality.sql",
            "migrations/0004_task9_sessions.sql",
            "migrations/0005_task10_sessions.sql",
            "migrations/0006_task12_sessions.sql",
            "migrations/0007_task14_sessions.sql",
            "migrations/0008_task13_sessions.sql",
        ):
            await pool.execute(await read_migration(migration))
        repository = PostgresRepository(pool)
        await repository.ensure_task13_session(user_id)
        first = build_task13_candidate_batch({}, 131302)[0]
        issued = await repository.advance_task13_problem(user_id, None, [first])
        problem_id = str(issued["problem_id"])
        await repository.save_user_state(user_id, "task13")
        condition_id = 931401
        assert await repository.set_task13_condition_message(user_id, problem_id, condition_id)
        candidates = build_task13_candidate_batch(
            {"recent_fingerprints": [issued["fingerprint"]]}, 131303
        )
        answer = repository.task13_attempt(
            user_id,
            problem_id,
            str(issued["correct_answer"]),
            True,
            931402,
            condition_id,
        )
        skip = repository.advance_task13_problem(
            user_id,
            problem_id,
            candidates,
            expected_screen="task13",
            expected_prompt_message_id=condition_id,
            skip_active=True,
        )
        answer_result, skip_result = await asyncio.gather(answer, skip)
        progress = await repository.task13_progress(user_id)
        assert progress["correct"] + progress["skipped"] == 1
        assert progress["issued"] == 1 + progress["skipped"]
        current = await repository.task13_state(user_id)
        assert current is not None
        if answer_result is not None and answer_result["status"] == "solved":
            assert skip_result.get("_transitioned") is False
            assert current["problem"]["problem_id"] == problem_id
        else:
            assert skip_result.get("_transitioned") is True
            assert current["problem"]["problem_id"] != problem_id
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()
