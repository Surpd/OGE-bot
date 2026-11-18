from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from app.persistence.mixed_training import MixedTrainingRepository
from app.persistence.repository import PostgresRepository, read_migration
from app.persistence.training_insights import training_insights


@pytest.mark.asyncio
async def test_postgres_mixed_session_resume_attempt_dedupe_and_progress() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")

    connection = await asyncpg.connect(database_url)
    schema = f"test_mixed_{uuid4().hex}"
    pool: asyncpg.Pool | None = None
    user_id = int(uuid4().int % (2**62)) + 1
    try:
        assert int(await connection.fetchval("SHOW server_version_num")) >= 170000
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        pool = await asyncpg.create_pool(
            database_url,
            min_size=1,
            max_size=4,
            server_settings={"search_path": f'"{schema}", public'},
        )
        for migration in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(await read_migration(str(migration)))

        repo = PostgresRepository(pool)
        store = MixedTrainingRepository(repo)
        started = await store.start(user_id, [6])
        expected = await store.expected_number(user_id)
        assert expected is not None
        number, revision = expected
        snapshot = {
            "problem_id": str(uuid4()),
            "family_id": f"OGE{number:02}-MIXED-TEST",
            "fingerprint": "postgres-mixed-fixture",
            "condition": "Вычислите.",
            "correct_answer": "5",
            "hints": ["Сложите числа."],
            "solution": ["2 + 3 = 5."],
        }
        issued = await store.issue_current(user_id, revision, number, snapshot)
        assert issued is not None
        problem_id = str(issued["problem_id"])
        assert await store.set_prompt(user_id, problem_id, 901)

        restarted = MixedTrainingRepository(PostgresRepository(pool))
        await restarted.start(user_id, [6])
        restored = await restarted.state(user_id)
        assert restored is not None
        assert restored["id"] == started["id"]
        assert restored["problem"]["problem_id"] == problem_id
        assert restored["problem"]["condition"] == "Вычислите."
        assert await restarted.action(user_id, problem_id, "hint")

        wrong = await restarted.answer(user_id, problem_id, "4", False, 902, 901)
        duplicate = await restarted.answer(user_id, problem_id, "4", False, 902, 901)
        assert wrong is not None and wrong["status"] == "active"
        assert duplicate == {"status": "duplicate"}
        second = await restarted.answer(user_id, problem_id, "4", False, 903, 901)
        assert second is not None and second["status"] == "failed"

        summary = await training_insights(PostgresRepository(pool), user_id)
        assert summary["total"]["issued"] == 1
        assert summary["total"]["attempts"] == 2
        assert summary["total"]["failed"] == 1
        assert summary["total"]["hints_used"] == 1

        from app.bot.mixed_training import _scenario, _scenario_question

        story_user_id = user_id + 1
        story_store = MixedTrainingRepository(PostgresRepository(pool))
        await story_store.start(story_user_id, [1])
        story_expected = await story_store.expected_number(story_user_id)
        assert story_expected is not None
        scenario = _scenario(seed=192509)
        story_problem = await story_store.issue_current(
            story_user_id,
            story_expected[1],
            1,
            _scenario_question(scenario, 1),
            scenario_snapshot=scenario,
        )
        assert story_problem is not None
        stored_question = await pool.fetchval(
            "SELECT snapshot FROM mixed_training_problems WHERE id=$1::uuid",
            story_problem["problem_id"],
        )
        assert "scenario_snapshot" not in stored_question
        restored_story = await story_store.state(story_user_id)
        assert restored_story is not None
        assert restored_story["problem"]["scenario_snapshot"] == scenario

        # Two competing advances cannot issue two next problems.
        candidates = [
            {
                "problem_id": str(uuid4()),
                "family_id": "OGE06-MIXED-TEST",
                "fingerprint": f"next-{index}",
                "condition": "Новое задание.",
                "correct_answer": "1",
            }
            for index in range(2)
        ]
        advanced = await asyncio.gather(
            restarted.advance(user_id, problem_id, candidates[0], number, new_cycle=[number]),
            restarted.advance(user_id, problem_id, candidates[1], number, new_cycle=[number]),
        )
        assert sum(result is not None for result in advanced) == 1
        transition = next(result for result in advanced if result is not None)
        pending = transition.get("pending_snapshot")
        assert isinstance(pending, dict)
        opened = await restarted.issue_current(
            user_id,
            int(transition["expected_revision"]),
            int(transition["number"]),
            pending,
        )
        assert opened is not None
        current = await restarted.state(user_id)
        assert current is not None and current["problem"]["condition"] == "Новое задание."
    finally:
        if pool is not None:
            await pool.close()
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()
